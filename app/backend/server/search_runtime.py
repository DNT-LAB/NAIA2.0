from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from core.web_session_context import WebSessionContext


CUSTOM_PARQUET_SCOPE = "custom_parquet"
TAG_ARCHIVE_SCOPE = "tag_archive"


def _tag_archive_sort_key(path: Path) -> tuple[int, str]:
    try:
        return int(path.stem.split("_", 1)[1]), path.name
    except (IndexError, ValueError):
        return 10**9, path.name


def rating_counts_from_frame(frame: Any) -> dict[str, int]:
    if frame is None or getattr(frame, "empty", True) or "rating" not in frame.columns:
        return {rating: 0 for rating in "gsqe"}
    counts = frame["rating"].value_counts()
    return {rating: int(counts.get(rating, 0)) for rating in "gsqe"}


def search_base_frame(context: WebSessionContext):
    base = getattr(context, "search_results_master_base_snapshot", None)
    if base is not None and not getattr(base, "empty", True):
        return base.copy()
    snapshot = getattr(context, "search_results_snapshot", None)
    if snapshot is not None and not getattr(snapshot, "empty", True):
        context.search_results_master_base_snapshot = snapshot.copy()
        return snapshot.copy()
    if context.search_results is not None and not context.search_results.is_empty():
        frame = context.search_results.get_dataframe().copy()
        context.search_results_master_base_snapshot = frame.copy()
        return frame
    return None


def _dedup_by_id(frame):
    """검색/합치기 결과의 post id 중복 제거(keep-first). id-keyed 태그필터 적용(`id.isin`)이 행 단위
    매칭과 어긋나지 않도록 데이터 정합을 원천 보장한다(중복 id면 매칭 안 된 형제 행까지 적용 풀에
    딸려 들어가 검색 count와 어긋나는 문제). 정상(유니크 id) 데이터엔 무영향 — 중복이 실제로 있을
    때만 행을 줄인다(주로 겹치는 custom parquet 합치기). 'cheap defense'."""
    try:
        if frame is not None and not getattr(frame, "empty", True) and "id" in frame.columns:
            if frame["id"].duplicated().any():
                return frame.drop_duplicates(subset="id", keep="first").reset_index(drop=True)
    except Exception:
        pass
    return frame


def normalize_custom_parquet_frame(frame):
    if frame is None or getattr(frame, "empty", True):
        return frame
    import pandas as pd

    # Foreign/custom parquet files may carry a scrambled or non-unique index.
    # SearchEngine.search_in_file normalizes this before tag filtering; the
    # upload and saved-parquet paths must do the same.
    if not isinstance(frame.index, pd.RangeIndex):
        frame = frame.reset_index(drop=True)
    return _dedup_by_id(frame)


def _reset_active_tag_filter_assignment(context: WebSessionContext) -> None:
    context.active_tag_filter_ids = None
    context.pending_tag_filter = None
    context.active_tag_filter = None
    if hasattr(context, "_tag_filter_cache"):
        context._tag_filter_cache = None


def install_custom_parquet_frame(context: WebSessionContext, frame) -> None:
    context.search_results.set_dataframe(frame)
    context.search_results_snapshot = context.search_results.get_dataframe().copy()
    context.search_results_master_base_snapshot = context.search_results_snapshot.copy()
    context.search_results_scope = CUSTOM_PARQUET_SCOPE
    _reset_active_tag_filter_assignment(context)
    # Custom parquet rows can contain any rating. Loading/merging a new result
    # base also invalidates the active tag-filter assignment; preserve any draft
    # chips but mark them inactive so old id sets cannot filter the new snapshot.
    context.search_query_ratings = set("gsqe")
    context.save_search_filter_state(
        ratings=["g", "s", "q", "e"],
        search_ratings=["g", "s", "q", "e"],
        tag_filter_active=False,
    )
    # 작업 데이터셋이 바뀌었으니 마지막-검색 영속도 갱신 (Part 3 — 재시작/가져오기 복원용).
    context.persist_last_search()


def filter_source_frame(
    frame: Any,
    *,
    query: str = "",
    exclude: str = "",
    ratings: set[str] | None = None,
    tag_ids: set[Any] | None = None,
):
    if frame is None or getattr(frame, "empty", True):
        return frame
    filtered = frame.copy()
    if query or exclude:
        from core.search_engine import SearchEngine

        engine = SearchEngine()
        for column in engine.TAG_COLUMNS:
            if column not in filtered.columns:
                filtered[column] = ""
        filtered = engine._apply_filters(filtered, str(query or ""), str(exclude or ""))
        if "tags_string" in filtered.columns:
            filtered = filtered.drop(columns=["tags_string"])
    # tag_ids 의미: None = 태그필터 비활성(스킵) / set()(빈) = 활성·0매치 → 0행(전체 아님) /
    # {...} = 활성·매칭. assign 은 0매치 시 빈 set 을 넣으므로(search_commands.py), truthy 검사로는
    # 빈 set 을 "필터 없음"으로 오인해 전체 풀을 노출한다 → 반드시 `is not None` 으로 구분.
    # ⚠️ id-keyed 한계(별도 후속 TODO): 같은 post-id 가 다른 태그로 여러 행에 흩어진 악성 중복
    #    데이터(겹치는 parquet 합치기 등)에선 isin 이 매칭 안 된 형제 행까지 포함 → 검색 count
    #    (per-row)와 적용 풀이 어긋남. 정상(유니크 id) 데이터엔 무영향. 근본 해결 = 검색/합치기 id dedup.
    if tag_ids is not None and "id" in filtered.columns:
        filtered = filtered[filtered["id"].isin(tag_ids)]
    if ratings and "rating" in filtered.columns:
        filtered = filtered[filtered["rating"].isin(ratings)]
    return filtered.copy()


def tag_archive_parquet_sources(context: WebSessionContext) -> list[tuple[Path, str]]:
    sources = getattr(context, "tag_archive_parquet_sources", None)
    if callable(sources):
        return sources()
    root = Path(getattr(context, "repo_root", Path.cwd()))
    tag_dir = root / "data" / "tags"
    if not tag_dir.is_dir():
        return []
    return [
        (path.resolve(), "source tag archive parquet")
        for path in sorted(tag_dir.glob("tags_*.parquet"), key=_tag_archive_sort_key)
        if path.is_file()
    ]


def search_tag_archive_frame(
    sources: list[tuple[Path, str]],
    *,
    query: str,
    exclude: str,
    ratings: set[str],
    progress_callback: Any = None,
):
    import os
    import pandas as pd
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from core.search_engine import SearchEngine

    search_params = {
        "query": query,
        "exclude_query": exclude,
        "rating_g": "g" in ratings,
        "rating_s": "s" in ratings,
        "rating_q": "q" in ratings,
        "rating_e": "e" in ratings,
    }
    # SearchEngine is stateless -> safe to share across worker threads. parquet
    # reads + PyArrow compute matching release the GIL, so a ThreadPool restores
    # the future01 "150 bucket" parallelism without multiprocessing.Pool's
    # Windows/spawn pickling risk.
    engine = SearchEngine()

    def _search_one(item: tuple[Path, str]):
        path, _label = item
        return engine.search_in_file(str(path), search_params)

    total = len(sources)
    # Collect by source index so the concatenated frame order is identical to a
    # sequential scan (as_completed itself is unordered; results[i] re-orders).
    results: list[Any] = [None] * total
    if sources:
        max_workers = min(total, max(2, min(8, os.cpu_count() or 4)))
        step = max(1, total // 20)  # ~20 progress ticks
        completed = 0
        with ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="tag-archive-search"
        ) as executor:
            future_to_index = {executor.submit(_search_one, item): i for i, item in enumerate(sources)}
            for future in as_completed(future_to_index):
                results[future_to_index[future]] = future.result()
                completed += 1
                if progress_callback is not None and (completed % step == 0 or completed == total):
                    try:
                        progress_callback(completed, total)
                    except Exception:
                        # Progress is best-effort; never fail the search on it.
                        pass
    frames = [r for r in results if r is not None and not getattr(r, "empty", True)]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def apply_search_runtime_filters(context: WebSessionContext) -> dict[str, Any]:
    source = getattr(context, "search_results_snapshot", None)
    if source is None or getattr(source, "empty", True):
        source = search_base_frame(context)
        if source is not None and not getattr(source, "empty", True):
            context.search_results_snapshot = source.copy()
    filtered = filter_source_frame(
        source,
        ratings=context.get_active_ratings(),
        tag_ids=getattr(context, "active_tag_filter_ids", None),
    )
    if filtered is None or getattr(filtered, "empty", True):
        import pandas as pd

        context.search_results.set_dataframe(pd.DataFrame())
    else:
        context.search_results.set_dataframe(filtered)
    return search_state_with_runner_save(context)


def save_runner_parquet(context: WebSessionContext) -> Path | None:
    if _should_skip_auto_runner_save(context):
        return None
    frame = context.search_results.get_dataframe() if context.search_results else None
    if frame is None or getattr(frame, "empty", True):
        return None
    path = context.runner_parquet_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return path


def _should_skip_auto_runner_save(context: WebSessionContext) -> bool:
    state = context.normalize_search_filter_state(getattr(context, "search_filter_state", None))
    if state.get("query") or state.get("exclude") or state.get("tag_filter_active"):
        return True
    if getattr(context, "active_tag_filter_ids", None) is not None or getattr(context, "active_tag_filter", None):
        return True
    return False


def search_state_with_runner_save(context: WebSessionContext) -> dict[str, Any]:
    state = context.search_state_payload()
    try:
        path = save_runner_parquet(context)
        if path is not None:
            state["runner_parquet_path"] = str(path)
    except Exception as exc:
        state["runner_parquet_error"] = str(exc)
    return state


def clear_active_tag_filter(context: WebSessionContext, reset_draft: bool = True) -> dict[str, Any]:
    _reset_active_tag_filter_assignment(context)
    if reset_draft:
        # Explicit "Clear": drop the assigned filter AND the draft include/exclude
        # lists.
        context.save_search_filter_state(
            tag_filter=[],
            tag_filter_exclude=[],
            tag_filter_active=False,
        )
    else:
        # Chip edit: only the assignment is stale — keep the persisted draft lists
        # so the returned search_state echo does not wipe the remaining chips in
        # the popup (save_search_filter_state merges, leaving tag_filter intact).
        context.save_search_filter_state(tag_filter_active=False)
    return apply_search_runtime_filters(context)


def run_search_command(
    context: WebSessionContext,
    command: dict[str, Any],
    progress_callback: Any = None,
) -> dict[str, Any]:
    ratings = {
        rating
        for rating in "gsqe"
        if command.get(f"rating_{rating}", True)
    } or set("gsqe")
    query = str(command.get("query") or "")
    exclude = str(command.get("exclude") or "")
    bucket_start = command.get("bucket_start")
    bucket_end = command.get("bucket_end")
    context.search_query_ratings = ratings
    # Persist only the search checkbox state. The active/generation-pool ratings
    # are a separate user preference; if we overwrite them here, running an
    # explicit-inclusive search permanently changes the random pool. After the
    # result frame has already been filtered by the requested search ratings,
    # we temporarily open the runtime pool to all ratings so the just-searched
    # result set is not filtered a second time.
    # None values are ignored by the saver -> they keep the persisted range.
    context.save_search_filter_state(
        query=query, exclude=exclude,
        search_ratings=ratings,
        bucket_start=bucket_start, bucket_end=bucket_end,
    )

    # The green [검색] is the full tag-archive search and must ALWAYS scan the archive
    # when it is available — even if a custom parquet was previously fast-loaded (which
    # sets search_results_scope = CUSTOM_PARQUET_SCOPE). The old guard suppressed the
    # archive here whenever scope was custom, so basic search silently fell back to
    # filtering the small loaded parquet AND never reset the scope (the reset below lives
    # only in this archive branch) — a one-way trap that broke full search for the whole
    # session (user report: fast-load → 전체검색 먹통). Refining WITHIN a loaded set is the
    # 심층검색(refine) path; restore reverts to the loaded snapshot. So always prefer the
    # archive; the successful archive search resets scope to TAG_ARCHIVE_SCOPE below.
    archive_sources = tag_archive_parquet_sources(context)
    if archive_sources:
        # Date-cutoff slider: scan only buckets [start..end] (fewer files = faster).
        if bucket_start is not None or bucket_end is not None:
            from core.tag_bucket_dates import clamp_bucket_range
            s, e = clamp_bucket_range(bucket_start, bucket_end, len(archive_sources))
            archive_sources = archive_sources[s:e + 1]
        searched = search_tag_archive_frame(
            archive_sources,
            query=query,
            exclude=exclude,
            ratings=ratings,
            progress_callback=progress_callback,
        )
        searched = _dedup_by_id(searched)
        context.search_results.set_dataframe(searched)
        context.search_results_snapshot = searched.copy()
        context.search_results_master_base_snapshot = searched.copy()
        context.search_results_scope = TAG_ARCHIVE_SCOPE
        context.active_tag_filter_ids = None
        context.pending_tag_filter = None
        context.active_tag_filter = None
        context.save_search_filter_state(tag_filter_active=False)
        context.remote_active_ratings = set("gsqe")
        context.persist_last_search()  # Part 3: 재시작/가져오기 후 복원용
        return apply_search_runtime_filters(context)

    base = search_base_frame(context)
    if base is None:
        return context.search_state_payload()
    searched = _dedup_by_id(filter_source_frame(base, query=query, exclude=exclude, ratings=ratings))
    context.search_results_snapshot = searched.copy() if searched is not None else None
    context.active_tag_filter_ids = None
    context.pending_tag_filter = None
    context.active_tag_filter = None
    context.save_search_filter_state(tag_filter_active=False)
    context.remote_active_ratings = set("gsqe")
    context.persist_last_search()  # Part 3: 재시작/가져오기 후 복원용
    return apply_search_runtime_filters(context)


def restore_search_snapshot(context: WebSessionContext) -> dict[str, Any]:
    base = search_base_frame(context)
    if base is not None:
        context.search_results_snapshot = base.copy()
        context.active_tag_filter_ids = None
        context.pending_tag_filter = None
        context.active_tag_filter = None
        context.save_search_filter_state(tag_filter_active=False)
        context.search_results.set_dataframe(base.copy())
    return search_state_with_runner_save(context)


_TAG_HITS_CAP = 4000  # 한 데이터셋 내 칩별 캐시 상한 (초과 시 비우고 lazy 재계산; tags_text는 유지)


def _tag_filter_cache(context: WebSessionContext, snapshot) -> dict:
    """칩(태그) 단위 캐시 — 데이터셋(snapshot) 객체 기준.

    snapshot 은 데이터셋이 바뀔 때마다(새 검색 / Parquet 로드·합치기 / 복원 — 전부 `.copy()`로
    새 객체 할당) 교체되므로, 캐시가 들고 있는 snapshot 과 identity(`is`)가 어긋나면 통째로 폐기한다
    (= "Parquet 교체 시 캐시 삭제"가 별도 훅 없이 자동 충족). 등급/assign 은 snapshot 을 교체하지
    않으므로 캐시가 유지된다.

    구조: tags_text(행별 소문자 태그 문자열, 데이터셋당 1회 계산) + tag_hits{태그 → 매칭 id frozenset}.
    """
    cache = getattr(context, "_tag_filter_cache", None)
    if cache is None or cache.get("snapshot") is not snapshot:
        cache = {"snapshot": snapshot, "tags_text": None, "tag_hits": {}}
        context._tag_filter_cache = cache
    return cache


def tag_filter_search(context: WebSessionContext, tags: list[Any]) -> dict[str, Any]:
    snapshot = getattr(context, "search_results_snapshot", None)
    if snapshot is None or getattr(snapshot, "empty", True):
        snapshot = search_base_frame(context)
        if snapshot is not None:
            context.search_results_snapshot = snapshot.copy()
            snapshot = context.search_results_snapshot
    normalized = WebSessionContext.normalize_filter_tags(tags)
    if snapshot is None or getattr(snapshot, "empty", True):
        return {
            "type": "tag_filter_result",
            "count": 0,
            "tags": normalized,
            "rating_counts": rating_counts_from_frame(None),
            "_ids": set(),
        }

    cache = _tag_filter_cache(context, snapshot)
    if cache["tags_text"] is None:
        tag_columns = [c for c in ("copyright", "character", "artist", "meta", "general") if c in snapshot.columns]
        if not tag_columns:
            frame = snapshot.copy()
            frame["general"] = ""
            tag_columns = ["general"]
        else:
            frame = snapshot
        cache["frame"] = frame
        cache["row_count"] = len(frame)
        cache["has_id"] = "id" in frame.columns
        cache["tags_text"] = frame[tag_columns].fillna("").astype(str).agg(",".join, axis=1).str.lower()
    tags_text = cache["tags_text"]
    row_count = cache["row_count"]

    def _hit_rows(key: str) -> frozenset:
        # 행(positional) 단위 매칭 집합. id 가 아니라 행 위치로 모아야 중복 id(예: 합친 parquet)에서도
        # 구버전의 per-row boolean mask 와 동치가 유지된다.
        cached = cache["tag_hits"].get(key)
        if cached is None:
            mask = tags_text.str.contains(key, na=False, regex=False)
            cached = frozenset(int(i) for i in mask.to_numpy().nonzero()[0])
            if len(cache["tag_hits"]) >= _TAG_HITS_CAP:
                cache["tag_hits"].clear()  # 메모리 상한 — tags_text 유지라 재계산 저렴
            cache["tag_hits"][key] = cached
        return cached

    include_rows = None          # None = 아직 제한 없음(전체 행)
    exclude_rows: set = set()
    clean_tags: list[str] = []
    for item in tags:
        raw = str(item or "").strip()
        if not raw:
            continue
        negate = raw.startswith("-")
        clean = raw.lstrip("-").strip().replace("_", " ")
        if not clean:
            continue
        clean_tags.append(("-" if negate else "") + clean)
        rows = _hit_rows(clean.lower())
        if negate:
            exclude_rows |= rows
        elif include_rows is None:
            include_rows = set(rows)
        else:
            include_rows &= rows
    if include_rows is None:
        include_rows = set(range(row_count))
    final_rows = include_rows - exclude_rows

    frame = cache["frame"]
    matched = frame.iloc[sorted(final_rows)]
    ids = set(matched["id"].tolist()) if cache["has_id"] else set(matched.index.tolist())
    return {
        "type": "tag_filter_result",
        "count": int(len(matched)),
        "tags": clean_tags,
        "rating_counts": rating_counts_from_frame(matched),
        "_ids": ids,
    }


def normalize_custom_parquet_filename(filename: str, *, fallback_prefix: str = "search_export") -> str:
    clean = Path(str(filename or "").strip()).name
    if not clean:
        clean = f"{fallback_prefix}_{time.strftime('%Y%m%d_%H%M%S')}.parquet"
    if not clean.lower().endswith(".parquet"):
        clean += ".parquet"
    return clean


def next_custom_parquet_path(context: WebSessionContext, filename: str, *, fallback_prefix: str = "search_export") -> Path:
    explicit = bool(str(filename or "").strip())
    clean = normalize_custom_parquet_filename(filename, fallback_prefix=fallback_prefix)
    path = context.custom_parquet_dir() / clean
    if explicit or not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.stem}_{uuid.uuid4().hex[:8]}{path.suffix}")


def resolve_custom_parquet_path(context: WebSessionContext, filename: str) -> Path | None:
    raw = str(filename or "").strip()
    clean = normalize_custom_parquet_filename(raw)
    if raw and clean != raw:
        return None
    return context.custom_parquet_dir() / clean


def load_or_merge_custom_parquet(
    context: WebSessionContext,
    filename: str,
    *,
    merge: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = resolve_custom_parquet_path(context, filename)
    if path is None:
        return context.search_state_payload(), {"type": "toast", "message": "Invalid parquet filename", "level": "error"}
    if not path.exists():
        return context.search_state_payload(), {"type": "toast", "message": f"Parquet not found: {filename}", "level": "error"}
    import pandas as pd

    frame = pd.read_parquet(path)
    frame = normalize_custom_parquet_frame(frame)
    if merge:
        current = context.search_results.get_dataframe() if context.search_results else pd.DataFrame()
        if current is not None and not current.empty:
            frame = pd.concat([current, frame], ignore_index=True)
            frame = normalize_custom_parquet_frame(frame)
    install_custom_parquet_frame(context, frame)
    state = search_state_with_runner_save(context)
    state["merged" if merge else "loaded"] = path.name
    verb = "merged" if merge else "loaded"
    return state, {"type": "toast", "message": f"{path.name} {verb} ({len(frame):,})", "level": "success"}


def search_parquet_action(context: WebSessionContext, command: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    frame = context.search_results.get_dataframe() if context.search_results else None
    if frame is None or frame.empty:
        return context.search_state_payload(), {"type": "toast", "message": "No search results to save", "level": "error"}
    action = str(command.get("action") or "").strip()
    if action == "export_results":
        path = next_custom_parquet_path(context, str(command.get("filename") or ""), fallback_prefix="search_export")
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
        message = f"Exported {path.name} ({len(frame):,})"
    elif action == "save_runner":
        path = context.runner_parquet_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
        message = f"Saved runner parquet ({len(frame):,})"
    else:
        return context.search_state_payload(), {"type": "toast", "message": "Unsupported parquet action", "level": "error"}
    return context.search_state_payload(), {"type": "toast", "message": message, "level": "success"}
