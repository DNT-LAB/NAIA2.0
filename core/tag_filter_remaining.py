"""Tag Filter 이어 하기 - 남은 행 색인을 저장해 두고, 재시작 뒤 필터를 다시 걸 때 그만큼만 남긴다(사용자 2026-10-18).

사용자 제보: 2,400행 중 1,600장을 만들고 껐다 켜면 다시 2,400 이 된다. 재시작은 마지막 검색 원본을 통째로 되살리고
Tag Filter 를 다시 걸 뿐이라 쓴 행의 기록이 없다(남은 풀 캐시 naia_temp_rows 는 필터가 켜져 있으면 저장 · 복원을 건너뛴다).

- 저장: Tag Filter 의 남은 id 집합(active_tag_filter["ids"] - 행을 쓸 때마다 하나씩 빠진다)이 0 < n < REMAINING_MAX 이면
  `naia_tag_filter_remaining.parquet`(id 한 열) + 명함 `.json` 을 쓴다. **종료할 때 한 번만** 쓴다(주기 저장은 큰 풀에서
  5초마다 0.3초 · 2.4MB 를 써서 걷었다). 포터블은 백엔드를 강제로 끄므로(taskkill /F) Electron 이 끄기 전에
  POST /api/session/prepare-shutdown 을 부르고 답을 기다린다(main.cjs). 헤드리스 정상 종료는 lifespan 이 같은 저장을 한다.
- 명함 = 필터 조건 + **필터가 걸었던 전체 id 집합의 지문**(active_tag_filter_snapshot["ids"] - 적용 순간의 불변 집합).
  재시작 재조립이 다시 건 전체 집합의 지문과 같을 때만 이어 간다. 처음엔 마지막 검색 파일의 크기 · 수정 시각을 썼는데,
  풀을 바꾼 뒤 그 파일이 아직 안 써졌거나 쓰기가 실패하면 새 풀의 id 가 옛 파일과 짝지어졌다(Codex P1 - 기록 추적으로는
  못 막았다: 풀을 먼저 바꾸고 기록을 나중에 부르는 길이 있다). 지문은 데이터가 같을 때만 맞으므로 그 짝이 생길 수 없다.
- 다 쓴 뒤 되채우는 기준(active_tag_filter_snapshot)은 그대로 전체다. 맞지 않으면 아무것도 거르지 않는다(안전한 쪽).
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

REMAINING_MAX = 500_000      # 남은 행이 이보다 많으면 저장하지 않는다(사용자 지정 - 큰 풀은 이어 하기 대상이 아니다)
FORMAT_VERSION = 2
_SAVE_LOCK = threading.Lock()   # 종료 요청 · lifespan · 읽기가 겹쳐도 한 번에 하나(같은 임시 파일 이름을 쓴다 - Codex P2)


def _paths(context: Any) -> tuple[Path, Path]:
    runtime = getattr(context, "runtime_paths", None)
    base = runtime.cache_dir if runtime is not None else Path(getattr(context, "repo_root", "."))
    return base / "naia_tag_filter_remaining.parquet", base / "naia_tag_filter_remaining.json"


def _norm_id(value: Any) -> str:
    """id 를 비교용 문자열로. 정수는 **정확히**(float 를 거치면 2**53 위에서 이웃 id 와 같아진다 - Codex)."""
    try:
        import numpy as np

        if isinstance(value, (int, np.integer)) and not isinstance(value, bool):
            return str(int(value))
    except Exception:
        pass
    text = str(value).strip()
    if text.lstrip("-").isdigit():
        return str(int(text))
    if text.endswith(".0") and text[:-2].lstrip("-").isdigit():
        return str(int(text[:-2]))
    return text


def fingerprint(ids: Any) -> str:
    """id 집합의 지문(순서 무관). 정수면 numpy 로 정렬해 해시(150만 개 ~0.1초), 아니면 정규화 문자열로."""
    values = list(ids or [])
    try:
        import numpy as np

        array = np.fromiter((int(v) for v in values), dtype=np.int64, count=len(values))
        array.sort()
        return "i:" + hashlib.sha1(array.tobytes()).hexdigest()
    except (TypeError, ValueError, OverflowError):
        joined = "\n".join(sorted(_norm_id(v) for v in values))
        return "s:" + hashlib.sha1(joined.encode("utf-8")).hexdigest()


def _condition(tags: Any, branches: Any) -> dict[str, Any]:
    return {"tags": [str(t) for t in (tags or [])], "branches": [[str(t) for t in b] for b in (branches or [])]}


def _invalidate(path: Path) -> bool:
    """지운다 - 없으면 성공. 지우지 못하면 False(그때는 짝을 바꾸지 않는다 - Codex P2)."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return True


def _remove(*paths: Path) -> None:
    for path in paths:
        _invalidate(path)


def _capture(context: Any) -> tuple[list[Any], dict[str, Any], list[Any]] | None:
    """남은 id · 조건 · 적용 순간의 전체 id 를 **한 잠금 안에서** 뜬다(셋이 한 풀의 것이어야 한다). 대상이 아니면 None."""
    from contextlib import nullcontext

    from core.temporary_search import is_temporary_search

    if is_temporary_search(context):
        return None
    guard = getattr(context, "search_pool_state_guard", None)
    with guard() if callable(guard) else nullcontext():
        tag_filter = getattr(context, "active_tag_filter", None)
        snapshot = getattr(context, "active_tag_filter_snapshot", None)
        if not isinstance(tag_filter, dict) or not isinstance(tag_filter.get("ids"), set):
            return None
        full = snapshot.get("ids") if isinstance(snapshot, dict) else None
        if not isinstance(full, set) or not full:
            return None
        return list(tag_filter["ids"]), _condition(tag_filter.get("tags"), tag_filter.get("branches")), list(full)


def save_remaining(context: Any) -> str:
    """남은 행 색인을 쓴다(또는 지운다). 반환 = 한 일('saved N' · 'removed' · 'skip …')."""
    with _SAVE_LOCK:
        parquet_path, meta_path = _paths(context)
        captured = _capture(context)
        if captured is None:
            return "skip"
        ids, condition, full = captured
        if not ids or len(ids) >= REMAINING_MAX:
            _remove(meta_path, parquet_path)
            return "removed"
        import pandas as pd

        matched = fingerprint(full)
        # 쌍 원자성(Codex P2): 명함을 먼저 지우고(못 지우면 멈춘다) -> id 파일 교체 -> 명함은 마지막.
        # 중간에 끊기면 명함이 없어 복원이 아무것도 거르지 않는다. 명함의 id 수를 읽을 때 맞춰 본다.
        if not _invalidate(meta_path):
            return "skip (card locked)"
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = parquet_path.with_suffix(".parquet.tmp")
        pd.DataFrame({"id": [_norm_id(i) for i in ids]}).to_parquet(tmp, index=False)
        tmp.replace(parquet_path)
        meta = {"version": FORMAT_VERSION, "condition": condition, "matched": matched,
                "matched_count": len(full), "count": len(ids)}
        tmp_meta = meta_path.with_suffix(".json.tmp")
        tmp_meta.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        tmp_meta.replace(meta_path)
        return f"saved {len(ids)}"


def load_remaining(context: Any, tags: Any, branches: Any, matched_ids: Any) -> set[str] | None:
    """지금(같은 조건 · 같은 전체 집합)에 맞는 저장본이 있으면 남은 id(정규화 문자열) 집합, 아니면 None.
    저장과 같은 잠금으로 읽는다 - 바꾸는 중의 옛 명함 + 새 id 를 짝으로 읽지 않게(Codex P2). 풀 잠금 밖에서 부른다."""
    with _SAVE_LOCK:
        parquet_path, meta_path = _paths(context)
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if meta.get("version") != FORMAT_VERSION or meta.get("condition") != _condition(tags, branches):
            return None
        if int(meta.get("matched_count") or -1) != len(matched_ids) or meta.get("matched") != fingerprint(matched_ids):
            return None          # 다른 데이터에 건 필터 - 이어 가지 않는다
        try:
            import pandas as pd

            frame = pd.read_parquet(parquet_path)
        except Exception:
            return None
        if "id" not in frame.columns or frame.empty or len(frame) != int(meta.get("count") or -1):
            return None          # 명함과 다른 id 파일(중간에 끊긴 쓰기) - 쓰지 않는다
        return {str(v) for v in frame["id"].tolist()}


def apply_remaining(context: Any, result: dict[str, Any], ids: set[Any]) -> tuple[set[Any], dict[str, int] | None]:
    """재조립된 필터 id 중 저장된 남은 행만 남긴다. 맞는 저장본이 없거나 겹침이 없으면 그대로(ids, None)."""
    remaining = load_remaining(context, result.get("tags"), result.get("branches"), ids)
    if not remaining:
        return ids, None
    kept = {i for i in ids if _norm_id(i) in remaining}
    if not kept or len(kept) == len(ids):
        return ids, None
    rating_counts: dict[str, int] | None = None
    snapshot = result.get("_source_snapshot")
    try:
        if snapshot is not None and "rating" in snapshot.columns and "id" in snapshot.columns:
            counts = snapshot.loc[snapshot["id"].isin(kept), "rating"].astype(str).str.strip().str.lower().value_counts()
            rating_counts = {r: int(counts.get(r, 0)) for r in "gsqe"}
    except Exception:
        rating_counts = None
    print(f"Headless Remote: tag filter resumed {len(kept)}/{len(ids)} rows", flush=True)
    return kept, rating_counts
