# -*- coding: utf-8 -*-
"""번역 기록(Translation History) — 한↔영 번역을 JSONL로 영속 기록한다.

NAIA는 여러 곳에서 ``utils/translator.py``(Google Translate)로 한글→영어 번역을
수행한다(자동완성 등). 이 모듈은 실제로 일어난 번역을 한 줄당 1 JSON 레코드(JSONL)로
런타임 데이터 디렉터리(logs)에 누적 기록한다 — 번역이 이상할 때 파일을 열어 되짚는 용도.
기록을 보던 창(번역 기록 패널 · /api/translation-history)은 그 창을 열던 Ollama 어시스트와 함께
회수했다(2026-09-26) — 보는 쪽 함수(조회·검색·삭제·핀)도 함께 뺐다.

설계 원칙
---------
- **Best-effort**: 기록 실패가 번역 자체를 절대 깨뜨려서는 안 된다. 모든 공개 함수는
  내부에서 예외를 삼킨다(``log_translation``은 절대 raise하지 않는다).
- **Thread-safe**: 백엔드는 ``run_in_thread``로 번역을 호출하므로 여러 스레드가 동시에
  기록할 수 있다. 모듈 전역 ``RLock``으로 파일 append/trim을 직렬화한다.
- **런타임 데이터 디렉터리**: 저장 위치는 하드코딩된 레포 경로가 아니라
  ``RuntimePaths.logs_dir``(쓰기 가능 디렉터리)이며, 런타임 경로를 못 구하면 OS 임시
  디렉터리로 합리적으로 폴백한다.
- **파일 성장 제한**: 레코드 수가 상한(``MAX_RECORDS``)을 넘으면 가장 오래된 것을 버리고
  최신 N개만 다시 쓴다(rotation). 매 append마다 재작성하지 않도록 여유분을 둔다.

저장 포맷(JSONL, 한 줄당 1 레코드)::

    {"ts": "2026-06-07T14:10:00", "direction": "ko->en",
     "context": "autocomplete", "source": "고양이", "translated": "cat"}
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Iterator, Optional
import hashlib
import json
import tempfile


# 기록 파일명 (logs_dir 하위).
LOG_FILENAME = "translation_history.jsonl"

# 보관할 최대 레코드 수. 초과 시 가장 오래된 것을 버리고 최신 N개만 유지한다.
MAX_RECORDS = 5000

# trim은 비용이 있으므로 매 append마다 하지 않는다. 상한 + 여유분을 넘었을 때만
# 한 번에 잘라낸다(amortized).
_ROTATE_SLACK = 1000

# 단일 source/translated 필드가 비정상적으로 길 때 잘라낼 한도(메모리/디스크 보호).
_MAX_FIELD_LEN = 8000

# 파일 append/trim 직렬화용 전역 락(번역은 여러 워커 스레드에서 호출될 수 있음).
_LOCK = RLock()

# 매 호출마다 RuntimePaths를 재해석하지 않도록 1회 캐시.
_CACHED_LOG_PATH: Optional[Path] = None

# 신규 기록에 부여할 id의 단조 증가 카운터(같은 마이크로초에 여러 건이 들어와도
# 유일성 보장). 프로세스 수명 동안만 유효하면 충분하다(id는 파일에 영속됨).
_ID_COUNTER = 0

# 현재 호출 컨텍스트 라벨. ``utils/translator.py``의 단일 기록 훅이 모든 호출자를
# 커버하므로, 호출자는 ``korean_to_english(...)`` 직접 호출 대신 컨텍스트만 지정하면
# 된다(이중 기록 방지). ContextVar라 async 태스크/스레드 간 안전하게 격리된다.
_CONTEXT_VAR: ContextVar[str] = ContextVar("naia_translation_context", default="")
# 구조화 메타(예: 어시스트의 effort/level·rating·mode)를 기록에 함께 붙이기 위한 변수.
_META_VAR: ContextVar[dict] = ContextVar("naia_translation_meta", default={})


@contextmanager
def translation_context(label: str, meta: dict | None = None) -> Iterator[None]:
    """이 블록 안에서 일어나는 번역 기록에 ``label`` 컨텍스트를 붙인다.

    예::

        with translation_context("autocomplete"):
            english = korean_to_english(korean)   # 기록 context="autocomplete"

    번역 함수 자체를 바꾸지 않고도 호출 지점을 라벨링할 수 있어, 단일 기록 훅
    (translator)을 유지하면서 이중 기록을 피한다. best-effort — 라벨 설정 실패는 무시.
    """
    token = None
    try:
        token = _CONTEXT_VAR.set(_coerce_text(label))
    except Exception:
        token = None
    mtoken = None
    if meta is not None:
        try:
            mtoken = _META_VAR.set(dict(meta))
        except Exception:
            mtoken = None
    try:
        yield
    finally:
        if token is not None:
            try:
                _CONTEXT_VAR.reset(token)
            except Exception:
                pass
        if mtoken is not None:
            try:
                _META_VAR.reset(mtoken)
            except Exception:
                pass


def current_context(default: str = "") -> str:
    """현재 설정된 호출 컨텍스트 라벨을 반환한다(없으면 ``default``)."""
    try:
        return _CONTEXT_VAR.get() or default
    except Exception:
        return default


def current_meta() -> dict:
    """현재 설정된 구조화 메타(effort/rating 등)를 반환한다(없으면 빈 dict)."""
    try:
        m = _META_VAR.get()
        return dict(m) if isinstance(m, dict) else {}
    except Exception:
        return {}


def _coerce_text(value: Any) -> str:
    """임의 입력을 안전한 문자열로 강제 변환하고 과도한 길이를 자른다."""
    if value is None:
        return ""
    try:
        text = value if isinstance(value, str) else str(value)
    except Exception:
        return ""
    if len(text) > _MAX_FIELD_LEN:
        text = text[:_MAX_FIELD_LEN]
    return text


def _resolve_log_dir() -> Path:
    """기록 파일을 둘 쓰기 가능 디렉터리를 해석한다.

    우선순위:
      1. ``RuntimePaths.logs_dir`` (런타임 경로 — NAIA_USER_DATA_DIR/포터블/설치형 존중)
      2. OS 임시 디렉터리 하위 ``naia_logs`` (런타임 경로를 못 구할 때 폴백)
    어떤 경로도 디렉터리 생성에 실패하면 임시 디렉터리로 한 번 더 폴백한다.
    """
    # 1) 런타임 경로의 logs_dir.
    try:
        from app.backend.runtime.paths import resolve_runtime_paths

        logs_dir = resolve_runtime_paths().logs_dir
        logs_dir.mkdir(parents=True, exist_ok=True)
        return logs_dir
    except Exception:
        pass

    # 2) 임시 디렉터리 폴백.
    try:
        fallback = Path(tempfile.gettempdir()) / "naia_logs"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
    except Exception:
        # 최후의 보루: 현재 작업 디렉터리.
        return Path(".")


def get_log_path() -> Path:
    """기록 파일의 절대 경로를 반환한다(필요 시 디렉터리 생성)."""
    global _CACHED_LOG_PATH
    with _LOCK:
        if _CACHED_LOG_PATH is not None:
            return _CACHED_LOG_PATH
        path = (_resolve_log_dir() / LOG_FILENAME).resolve()
        _CACHED_LOG_PATH = path
        return path


def reset_log_path_cache() -> None:
    """해석된 경로 캐시를 비운다(주로 테스트에서 NAIA_USER_DATA_DIR 변경 후 사용)."""
    global _CACHED_LOG_PATH
    with _LOCK:
        _CACHED_LOG_PATH = None


def _read_all_lines(path: Path) -> list[str]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return fh.readlines()
    except FileNotFoundError:
        return []
    except Exception:
        return []


def _maybe_rotate_locked(path: Path) -> None:
    """레코드 수가 ``MAX_RECORDS + _ROTATE_SLACK``를 넘으면 최신 ``MAX_RECORDS``만 남긴다.

    호출자는 ``_LOCK``을 잡고 있어야 한다. 줄 단위로만 처리하므로 JSON 파싱 비용 없이
    꼬리(최신)를 보존한다. 손상 라인이 섞여 있어도 단순 보존된다(검색 단계에서 무시).
    """
    try:
        lines = _read_all_lines(path)
        if len(lines) <= MAX_RECORDS + _ROTATE_SLACK:
            return
        keep = lines[-MAX_RECORDS:]
        tmp = path.with_name(path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            fh.writelines(keep)
        tmp.replace(path)
    except Exception:
        # rotation 실패는 무시 — 기록 자체를 막지 않는다.
        pass


def log_translation(
    source: str,
    translated: str,
    *,
    direction: str = "ko->en",
    context: str = "",
    meta: dict | None = None,
) -> bool:
    """번역 1건을 JSONL로 append한다. **절대 raise하지 않는다(best-effort)**.

    Args:
        source: 원문(예: 한글 프롬프트).
        translated: 번역 결과(예: 영어).
        direction: 번역 방향 라벨(기본 ``"ko->en"``). ``"en->ko"`` 등 임의 라벨 허용.
        context: 호출 지점 라벨(예: ``"autocomplete"``). 선택.
            비우면 ``translation_context(...)``로 설정된 현재 컨텍스트를 사용한다.

    Returns:
        기록에 성공하면 True, 무시/실패하면 False(호출자는 보통 무시).
    """
    try:
        src = _coerce_text(source)
        dst = _coerce_text(translated)
        # 둘 다 비어 있으면 기록할 가치가 없다(빈 입력/실패한 번역 노이즈 차단).
        if not src.strip() and not dst.strip():
            return False

        ctx = _coerce_text(context)
        if not ctx:
            ctx = current_context()
        m = meta if meta is not None else current_meta()
        if not isinstance(m, dict):
            m = {}

        global _ID_COUNTER
        with _LOCK:
            now = datetime.now()
            _ID_COUNTER += 1
            # 안정적·유일한 id: 마이크로초 타임스탬프 + 단조 카운터를 해시.
            uid = hashlib.sha1(
                f"{now.isoformat()}|{_ID_COUNTER}".encode("utf-8", "replace")
            ).hexdigest()[:16]
            record = {
                "ts": now.isoformat(timespec="seconds"),
                "id": uid,
                "direction": _coerce_text(direction) or "ko->en",
                "context": ctx,
                "source": src,
                "translated": dst,
                "meta": m,
            }
            line = json.dumps(record, ensure_ascii=False)

            path = get_log_path()
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            _maybe_rotate_locked(path)
        return True
    except Exception:
        # 기록 실패가 번역을 깨뜨려서는 안 된다.
        return False


__all__ = [
    "LOG_FILENAME",
    "MAX_RECORDS",
    "get_log_path",
    "reset_log_path_cache",
    "log_translation",
    "translation_context",
    "current_context",
]
