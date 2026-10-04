"""검색의 현재 작업 뷰를 보존하되 backend 태그 필터 구현에는 의존하지 않는다."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable

from core.temporary_search import is_temporary_search


def capture_search(context: Any, stage: Path) -> dict[str, Any]:
    from core.custom_parquet_library import make_meta
    from core.search_pool_writer import SearchPoolWriter

    with context.search_pool_state_guard():
        if is_temporary_search(context):
            raise ValueError("Temporary search workspace is active")
        # persist_last_search와 같은 작업 뷰를 고른다. 소진된 라이브 풀을 저장하면 행이 유실된다.
        frame = getattr(context, "search_results_snapshot", None)
        if frame is None or getattr(frame, "empty", True):
            frame = getattr(context, "search_results_master_base_snapshot", None)
        if frame is None or getattr(frame, "empty", True):
            raise ValueError("No search dataset to capture")
        frame = frame.copy()
        state = context.normalize_search_filter_state(getattr(context, "search_filter_state", None))
        section = {
            "filter_state": state,
            "active_ratings": context.normalize_rating_list(context.get_active_ratings()),
            "provenance": copy.deepcopy(getattr(context, "search_pool_provenance", None)),
            "scope": str(getattr(context, "search_results_scope", "") or "custom_parquet"),
            "pool_file": "pool.parquet", "rows": len(frame),
            "summary": search_summary(state),
        }
    json.dumps(section, allow_nan=False)
    path = stage / "pool.parquet"
    try:
        # 동일 writer의 동기 경로를 독립 인스턴스로 쓴다. 세션 writer의 대기 중 last 기록을
        # 취소하면 단순 캡처가 재시작용 데이터셋을 잃게 한다. write_now는 스레드를 만들지 않는다.
        SearchPoolWriter().write_now(path, frame, kind="last",
                                    meta=make_meta("last_search", section["provenance"], len(frame)))
        section["bytes"] = path.stat().st_size
    except Exception:
        # 구역 실패 뒤 원자적으로 공개되는 폴더에 불완전한 풀을 남기지 않는다.
        for candidate in (path, path.with_suffix(".parquet.tmp")):
            candidate.unlink(missing_ok=True)
        raise
    return section


def search_summary(state: dict[str, Any]) -> str:
    chips = [*state["tag_filter"], *[f"-{tag}" for tag in state["tag_filter_exclude"]],
             *state["tag_filter_pinned"]]
    branches = state["tag_filter_applied_branches"] or [
        item["tags"] for item in state["tag_filter_branches"] if item["enabled"]]
    chips.extend("(" + ", ".join(branch) + ")" for branch in branches)
    values = (state["query"], state["exclude"], state["exclude_permanent"], ", ".join(chips))
    return " / ".join(f"{label}: {' '.join(value.split())}" for label, value in
                      zip(("query", "exclude", "exclude permanent", "tags"), values) if value)


def restore_search(context: Any, section: Any, pool_path: Path,
                   reset_filter: Callable[[], None] | None,
                   rebuild_filter: Callable[[], Any] | None) -> Path | None:
    # core 단독 사용은 실패를 숨기지 않는다. 콜백 확인을 풀/파일 변경보다 먼저 한다.
    if not callable(reset_filter) or not callable(rebuild_filter):
        raise ValueError("Search runtime callbacks are not registered")
    if is_temporary_search(context):
        # 임시 공간의 영속은 의도적으로 막혀 있어 재시작 복원 계약을 만족시킬 수 없다.
        raise ValueError("Temporary search workspace is active")
    if (not isinstance(section, dict) or section.get("pool_file") != "pool.parquet"
            or not isinstance(section.get("filter_state"), dict)
            or not isinstance(section.get("active_ratings"), list)
            or not isinstance(section.get("scope"), str)
            or (section.get("provenance") is not None and not isinstance(section["provenance"], dict))):
        raise ValueError("Malformed search section")
    from core.parquet_chunk_loader import read_parquet_chunked
    from core.search_result_model import SearchResultModel

    frame = read_parquet_chunked(pool_path)
    if frame is None or frame.empty or "general" not in frame.columns:
        raise ValueError("Search pool is empty or has no 'general' column")
    frame = frame.reset_index(drop=True)
    state = context.normalize_search_filter_state(section["filter_state"])
    # 활성 등급은 검색 체크박스와 다를 수 있다. 실제 풀의 등급을 다음 재시작에도 보존한다.
    state["ratings"] = context.normalize_rating_list(section["active_ratings"])
    with context.search_pool_state_guard():
        context.search_results = SearchResultModel(frame)
        context.search_results_snapshot = frame.copy()
        context.search_results_master_base_snapshot = frame.copy()
        context.search_results_scope = section["scope"]
        context.search_pool_provenance = copy.deepcopy(section.get("provenance"))
        context.search_pool_base_provenance = copy.deepcopy(section.get("provenance"))
        context.mark_search_pool_replaced()
        # ⚠️ 기존 할당이 남으면 reconstruct가 즉시 반환하여 새 풀에 옛 필터가 적용된다.
        reset_filter()
        # saver는 None 버킷을 '변경 없음'으로 해석한다. 완전 복원에서는 이전 버킷을 먼저 비운다.
        context.search_filter_state = {}
        context.save_search_filter_state(**state)
        context.search_query_ratings = set(state["search_ratings"])
    # reconstruct는 자체 잠금을 먼저 잡으므로 풀 잠금 밖에서 호출해 잠금 순서 역전을 피한다.
    rebuild_filter()
    return context.persist_last_search()
