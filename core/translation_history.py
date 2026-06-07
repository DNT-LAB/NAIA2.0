# -*- coding: utf-8 -*-
"""번역 기록(Translation History) — 한↔영 번역을 JSONL로 영속 기록 + 검색.

NAIA는 여러 곳에서 ``utils/translator.py``(Google Translate)로 한글→영어 번역을
수행한다(가장 중요한 경로는 Ollama 태그 어시스트 파이프라인). 이 모듈은 실제로
일어난 번역을 한 줄당 1 JSON 레코드(JSONL)로 런타임 데이터 디렉터리에 누적 기록하고,
나중에 사용자가 "무엇을 어떻게 번역했는지" 되돌아볼 수 있도록 검색 기능을 제공한다.

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
     "context": "ollama_assist", "source": "고양이", "translated": "cat"}
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
# 자동 기록 억제 플래그. 어시스트 파이프라인이 *중간* 번역(KR→EN)을 기록에서 빼고
# **최종 결과(태그+자연어)만** 명시적으로 남기기 위해 쓴다. ``force=True`` 기록은 무시한다.
_SUPPRESS_VAR: ContextVar[bool] = ContextVar("naia_translation_suppress", default=False)


@contextmanager
def translation_context(label: str, meta: dict | None = None) -> Iterator[None]:
    """이 블록 안에서 일어나는 번역 기록에 ``label`` 컨텍스트를 붙인다.

    예::

        with translation_context("ollama_assist"):
            english = korean_to_english(korean)   # 기록 context="ollama_assist"

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


@contextmanager
def suppress_logging() -> Iterator[None]:
    """이 블록 안의 **자동** 번역 기록을 막는다(중간 단계 번역을 기록에서 제외).

    어시스트 파이프라인이 KR→EN 중간 번역을 기록하지 않고, 대신 최종 결과(태그+자연어)를
    ``log_translation(..., force=True)``로 1건만 남기게 하는 용도. ``force=True`` 호출은
    이 억제를 무시한다. best-effort — 억제 설정 실패는 무시(그냥 평소대로 기록).
    """
    token = None
    try:
        token = _SUPPRESS_VAR.set(True)
    except Exception:
        token = None
    try:
        yield
    finally:
        if token is not None:
            try:
                _SUPPRESS_VAR.reset(token)
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


def _record_content_id(rec: dict[str, Any]) -> str:
    """레코드 내용으로부터 안정적인 16-hex 식별자를 만든다.

    기존 기록은 ``id``가 없으므로(레거시), 삭제/핀 토글이 정확히 같은 줄을 다시
    찾을 수 있도록 **내용 기반 해시**로 식별자를 결정론적으로 합성한다. ``ts`` +
    direction + context + source + translated를 해시하므로, 한 레코드를 지워도
    (내용이 동일한 중복이 아닌 한) 다른 레코드의 id는 바뀌지 않는다. 내용이 완전히
    동일한 중복은 호출부에서 등장 순번(occurrence index)을 붙여 추가로 구분한다.
    """
    basis = "\x1f".join((
        str(rec.get("ts", "")),
        str(rec.get("direction", "")),
        str(rec.get("context", "")),
        str(rec.get("source", "")),
        str(rec.get("translated", "")),
    ))
    return hashlib.sha1(basis.encode("utf-8", "replace")).hexdigest()[:16]


def _normalize_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """읽어들인 레코드에 ``id``/``pinned`` 필드를 일관되게 채운다(in place 변형 없음).

    - ``id``: 이미 있으면 존중, 없으면 내용 해시로 합성. 내용이 동일한 중복은
      ``<hash>-<n>``(n=등장 순번)으로 충돌을 푼다.
    - ``pinned``: bool로 정규화(없으면 False).
    입력 순서(최신 우선)를 그대로 보존한다.
    """
    seen: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for rec in records:
        norm = dict(rec)
        rid = str(norm.get("id") or "").strip()
        if not rid:
            base = _record_content_id(norm)
            n = seen.get(base, 0)
            seen[base] = n + 1
            rid = base if n == 0 else f"{base}-{n}"
        norm["id"] = rid
        norm["pinned"] = bool(norm.get("pinned", False))
        out.append(norm)
    return out


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
    force: bool = False,
) -> bool:
    """번역 1건을 JSONL로 append한다. **절대 raise하지 않는다(best-effort)**.

    Args:
        source: 원문(예: 한글 프롬프트).
        translated: 번역 결과(예: 영어).
        direction: 번역 방향 라벨(기본 ``"ko->en"``). ``"en->ko"`` 등 임의 라벨 허용.
        context: 호출 지점 라벨(예: ``"ollama_assist"``, ``"autocomplete"``). 선택.
            비우면 ``translation_context(...)``로 설정된 현재 컨텍스트를 사용한다.

    Returns:
        기록에 성공하면 True, 무시/실패하면 False(호출자는 보통 무시).
    """
    try:
        # 억제 블록(중간 번역 단계) 안의 자동 기록은 건너뛴다 — force=True는 무시.
        if not force:
            try:
                if _SUPPRESS_VAR.get():
                    return False
            except Exception:
                pass

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
                "pinned": False,
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


def _iter_records_newest_first(path: Path) -> list[dict[str, Any]]:
    """파일을 읽어 레코드 리스트(최신 우선)로 파싱한다. 손상 라인은 건너뛴다."""
    lines = _read_all_lines(path)
    records: list[dict[str, Any]] = []
    # 파일은 오래된→최신 순으로 append되므로 역순으로 순회하면 최신 우선.
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records


def get_recent_translations(limit: int = 50) -> list[dict[str, Any]]:
    """가장 최근 기록을 최신 우선으로 반환한다(best-effort, 실패 시 빈 리스트).

    각 레코드는 ``id``/``pinned`` 필드를 포함한다(없던 레거시 레코드는 합성).
    """
    try:
        if limit is None or limit <= 0:
            limit = 50
        path = get_log_path()
        with _LOCK:
            records = _normalize_records(_iter_records_newest_first(path))
        return records[:limit]
    except Exception:
        return []


def get_pinned_translations(limit: int = 500) -> list[dict[str, Any]]:
    """핀(pinned=True) 처리된 기록만 최신 우선으로 반환한다(best-effort)."""
    try:
        if limit is None or limit <= 0:
            limit = 500
        path = get_log_path()
        with _LOCK:
            records = _normalize_records(_iter_records_newest_first(path))
        return [r for r in records if r.get("pinned")][:limit]
    except Exception:
        return []


def search_translations(
    query: str,
    *,
    limit: int = 50,
    direction: Optional[str] = None,
) -> list[dict[str, Any]]:
    """source+translated에 대한 대소문자 무시 부분 문자열 검색(최신 우선).

    Args:
        query: 검색어. 빈 문자열이면 (필터만 적용한) 최근 기록을 반환한다.
        limit: 최대 반환 개수(기본 50).
        direction: 지정 시 해당 ``direction``인 레코드만 반환(예: ``"ko->en"``).

    Returns:
        매칭 레코드 리스트(최신 우선). best-effort — 실패 시 빈 리스트.
    """
    try:
        if limit is None or limit <= 0:
            limit = 50
        needle = _coerce_text(query).strip().lower()
        dir_filter = _coerce_text(direction).strip().lower() if direction else ""

        path = get_log_path()
        with _LOCK:
            records = _normalize_records(_iter_records_newest_first(path))

        results: list[dict[str, Any]] = []
        for rec in records:
            if dir_filter:
                rec_dir = str(rec.get("direction", "")).strip().lower()
                if rec_dir != dir_filter:
                    continue
            if needle:
                haystack = (
                    str(rec.get("source", "")) + "\n" + str(rec.get("translated", ""))
                ).lower()
                if needle not in haystack:
                    continue
            results.append(rec)
            if len(results) >= limit:
                break
        return results
    except Exception:
        return []


def _rewrite_records_locked(path: Path, records_oldest_first: list[dict[str, Any]]) -> bool:
    """레코드 리스트(오래된→최신)를 파일에 원자적으로 다시 쓴다.

    호출자는 ``_LOCK``을 잡고 있어야 한다. tmp 파일에 쓴 뒤 ``replace``로 교체해
    중간 상태 노출을 막는다. best-effort — 실패 시 False(원본은 보존됨).
    """
    try:
        tmp = path.with_name(path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for rec in records_oldest_first:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        tmp.replace(path)
        return True
    except Exception:
        return False


def _mutate_record_by_id(record_id: str, mutator) -> bool:
    """``record_id``에 해당하는 레코드를 찾아 ``mutator(rec)``로 변형하고 파일을 다시 쓴다.

    ``mutator(rec)`` 반환값:
      - ``None``  → 그 레코드를 **삭제**(다시 쓰지 않음)
      - ``dict``  → 그 dict로 **치환**(핀 토글 등)
    매칭이 일어나면 True, 대상이 없거나 실패하면 False. **절대 raise하지 않는다.**

    삭제/치환 시 파싱 가능한 레코드만 다시 쓴다(손상 라인은 읽기 경로에서도 무시되며
    복구할 내용이 없음). id는 읽기 경로(``_normalize_records``)와 동일하게 계산하므로
    UI가 받은 id와 일치한다.
    """
    try:
        rid = _coerce_text(record_id).strip()
        if not rid:
            return False
        path = get_log_path()
        with _LOCK:
            # 최신 우선으로 정규화 → UI가 받은 id 체계와 동일하게 매칭.
            newest_first = _normalize_records(_iter_records_newest_first(path))
            matched = False
            kept_newest_first: list[dict[str, Any]] = []
            for rec in newest_first:
                if not matched and str(rec.get("id")) == rid:
                    matched = True
                    new_rec = mutator(rec)
                    if new_rec is None:
                        continue  # 삭제: 보존 목록에서 제외
                    kept_newest_first.append(new_rec)
                else:
                    kept_newest_first.append(rec)
            if not matched:
                return False
            # 파일은 오래된→최신 순으로 저장 → 역순으로 되돌려 기록.
            return _rewrite_records_locked(path, list(reversed(kept_newest_first)))
    except Exception:
        return False


def delete_translation(record_id: str) -> bool:
    """``record_id`` 레코드를 영구 삭제한다. best-effort — 절대 raise하지 않는다.

    Returns:
        삭제에 성공하면 True, 대상이 없거나 실패하면 False.
    """
    return _mutate_record_by_id(record_id, lambda rec: None)


def set_pinned(record_id: str, pinned: bool) -> bool:
    """``record_id`` 레코드의 핀 상태를 설정/해제하고 영속한다. best-effort.

    Args:
        record_id: 대상 레코드 id.
        pinned: True면 핀, False면 핀 해제.

    Returns:
        상태 변경에 성공하면 True, 대상이 없거나 실패하면 False.
    """
    want = bool(pinned)

    def _apply(rec: dict[str, Any]) -> dict[str, Any]:
        updated = dict(rec)
        updated["pinned"] = want
        return updated

    return _mutate_record_by_id(record_id, _apply)


__all__ = [
    "LOG_FILENAME",
    "MAX_RECORDS",
    "get_log_path",
    "reset_log_path_cache",
    "log_translation",
    "get_recent_translations",
    "get_pinned_translations",
    "search_translations",
    "delete_translation",
    "set_pinned",
    "translation_context",
    "suppress_logging",
    "current_context",
]
