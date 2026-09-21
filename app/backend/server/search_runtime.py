from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from core.search_pool_writer import search_pool_writer
from core.web_session_context import WebSessionContext


CUSTOM_PARQUET_SCOPE = "custom_parquet"
TAG_ARCHIVE_SCOPE = "tag_archive"

# Serializes the startup persisted-filter reconstruct so two concurrent
# get_search_state calls (one triggered by the frontend re-requesting state on
# load completion) can't both run the heavy 1M+ row tag-filter index build. The
# first sets active_tag_filter; the second re-checks the guard under the lock and
# returns fast.
_RECONSTRUCT_LOCK = threading.Lock()

# Serializes the per-dataset tags_text index build (str.cat + lower over 1M+
# rows — the first-chip bottleneck). Two concurrent tag_filter_search tasks
# (fast chip edits / multi-client, dispatched as live background tasks) would
# otherwise both see tags_text is None and both run the heavy build. Double-
# checked under this lock: the second reuses the freshly built index.
_TAG_INDEX_BUILD_LOCK = threading.Lock()

# Announce + gate the 'filter' phase only for pools this large. Below it the
# tag-filter scan is near-instant, so a lock/toast would only flash. Mirrors
# core.parquet_chunk_loader.DEFAULT_LOADING_THRESHOLD (kept as a literal to avoid
# import coupling on this hot module).
_POOL_LOADING_THRESHOLD = 200_000

# Row-batch size for the chunked tags_text index build. Caps the transient peak
# to one batch of (per-column str + cat + lower) instead of holding the whole
# pool's columns materialized at once, and yields a progress heartbeat per batch.
_TAGS_TEXT_BATCH = 100_000

# Tag Filter 색인 빌드·칩 매칭 스레드 수. pyarrow 가 GIL 을 풀어 배치 병렬이 실제로 먹힌다.
_TAG_FILTER_WORKERS = max(1, min(8, (os.cpu_count() or 2) // 2))
_TAG_FILTER_POOL: ThreadPoolExecutor | None = None
_TAG_FILTER_POOL_GUARD = threading.Lock()

# 파이썬 re 의 `\s`(str) 와 같은 문자 집합을 RE2 로 쓴 것 = str.isspace() 가 참인 문자 전부.
# RE2 의 `\s` 는 [\t\n\f\r ] 뿐이라 NBSP(\xa0)·전각 공백(　) 등을 못 먹는다.
_RE2_PY_WS = (
    r"[\t\n\x{0b}\f\r\x{1c}-\x{1f} \x{85}\x{a0}\x{1680}\x{2000}-\x{200a}"
    r"\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]"
)


def search_pool_state_guard(context: WebSessionContext):
    """Return the context-owned guard, with a no-op fallback for test doubles."""
    getter = getattr(context, "search_pool_state_guard", None)
    if callable(getter):
        return getter()
    lock = getattr(context, "_search_pool_state_lock", None)
    return lock if lock is not None else nullcontext()


def current_search_pool_generation(context: WebSessionContext) -> int:
    getter = getattr(context, "search_pool_generation", None)
    if callable(getter):
        return int(getter() or 0)
    return int(getattr(context, "_search_pool_generation", 0) or 0)


def mark_search_pool_replaced(context: WebSessionContext) -> int:
    marker = getattr(context, "mark_search_pool_replaced", None)
    if callable(marker):
        return int(marker() or 0)
    value = current_search_pool_generation(context) + 1
    setattr(context, "_search_pool_generation", value)
    return value


def current_tag_filter_revision(context: WebSessionContext) -> int:
    getter = getattr(context, "tag_filter_revision", None)
    if callable(getter):
        return int(getter() or 0)
    return int(getattr(context, "_tag_filter_revision", 0) or 0)


def mark_tag_filter_changed(context: WebSessionContext) -> int:
    marker = getattr(context, "mark_tag_filter_changed", None)
    if callable(marker):
        return int(marker() or 0)
    value = current_tag_filter_revision(context) + 1
    setattr(context, "_tag_filter_revision", value)
    return value


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
    # 스냅샷도 함께 버린다 - 남겨 두면 해제한 조건이 되살아난다.
    context.active_tag_filter_snapshot = None
    context.pending_tag_filter = None
    pending_by_client = getattr(context, "pending_tag_filters", None)
    if isinstance(pending_by_client, dict):
        pending_by_client.clear()
    context.active_tag_filter = None
    context.active_tag_filter_frame = None
    context.active_tag_filter_frame_for = None
    context.active_tag_filter_frame_snapshot = None
    if hasattr(context, "_tag_filter_cache"):
        context._tag_filter_cache = None
    mark_tag_filter_changed(context)


def reset_active_tag_filter_assignment(context: WebSessionContext) -> None:
    """Public invalidation hook for pool-replacement paths outside this module."""
    _reset_active_tag_filter_assignment(context)


def merge_base_frame(context: WebSessionContext):
    """합치기의 기준 = 현재 데이터셋 전체(snapshot).

    ⚠️ `search_results.get_dataframe()` 은 **남은 풀**이다 - 등급·태그필터가 걸려 있고 Random 이
    뽑아 쓴 행도 빠져 있다. 거기에 합치면 필터 중 합치기가 행을 조용히 잃고(1.3M 풀 + 5만 행 합치기
    → 67만 행), 뽑아 쓴 행이 데이터셋에서 영영 사라진다.
    ⚠️ master_base 도 아니다 - 심층검색으로 좁힌 셋(snapshot ⊂ master_base)이 합치기에서 풀린다.
    snapshot 은 Tag Filter 가 훑는 풀·last-search 가 쓰는 풀과 같은 것이다."""
    snapshot = getattr(context, "search_results_snapshot", None)
    if snapshot is not None and not getattr(snapshot, "empty", True):
        return snapshot
    return search_base_frame(context)


def pool_provenance(context: WebSessionContext) -> Any:
    """지금 풀(snapshot)이 어떻게 만들어졌나 - 저장할 때 명함 recipe 의 뿌리가 된다."""
    return getattr(context, "search_pool_provenance", None)


def _set_pool_provenance(context: WebSessionContext, recipe: Any, *, base: bool = False) -> None:
    """풀을 바꾸는 모든 자리에서 부른다. base=True 면 복원 기준(master_base)의 출처도 같이.

    ⚠️ 풀을 바꾸는 자리(mark_search_pool_replaced 호출처)마다 빠짐없이 걸어야 한다 - 하나라도
    빠지면 명함이 거짓말을 한다(tests/test_custom_parquet_provenance.py 가 진입점을 전수한다)."""
    context.search_pool_provenance = recipe
    if base:
        context.search_pool_base_provenance = recipe


def _search_recipe(context: WebSessionContext, query: str, exclude: str, ratings, bucket_range) -> dict[str, Any]:
    recipe: dict[str, Any] = {
        "source": "search",
        "query": str(query or ""),
        "exclude": str(exclude or ""),
        "ratings": sorted(ratings or []),
    }
    if bucket_range is not None:
        s, e = bucket_range
        recipe["bucket"] = [int(s), int(e)]
        try:
            from core.tag_bucket_dates import load_bucket_dates

            buckets = load_bucket_dates(context).get("buckets") or []
            if 0 <= s < len(buckets) and 0 <= e < len(buckets):
                recipe["period"] = f"{buckets[s].get('start_ym')}~{buckets[e].get('end_ym')}"
        except Exception:
            pass
    return recipe


def _last_search_meta(context: WebSessionContext, frame) -> dict[str, Any]:
    from core.custom_parquet_library import make_meta

    return make_meta("last_search", pool_provenance(context), len(frame))


def install_custom_parquet_frame(context: WebSessionContext, frame, provenance: Any = None) -> None:
    with search_pool_state_guard(context):
        _set_pool_provenance(context, provenance, base=True)
        context.search_results.set_dataframe(frame)
        context.search_results_snapshot = context.search_results.get_dataframe().copy()
        context.search_results_master_base_snapshot = context.search_results_snapshot.copy()
        context.search_results_scope = CUSTOM_PARQUET_SCOPE
        mark_search_pool_replaced(context)
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
        # 응답을 막지 않게 백그라운드로, 한 번만 쓴다(core/search_pool_writer.py).
        # 프레임은 **락 안에서** 캡처한 snapshot 참조 - 백그라운드에서 get_dataframe() 을 부르면
        # Random pop 과 경쟁한다. 설치 직후엔 남은 풀(runner 대상) == snapshot 이므로(등급 전부 ON,
        # 태그필터 해제, pop 없음) runner 는 last-search 파일을 복사한다.
        pool_frame = context.search_results_snapshot
        runner_path = None if _should_skip_auto_runner_save(context) else context.runner_parquet_path()
        last_path = context.last_search_parquet_path()
    if pool_frame is not None and not getattr(pool_frame, "empty", True):
        search_pool_writer(context).submit(last_path, pool_frame, runner_path, meta=_last_search_meta(context, pool_frame))


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
    # tag_ids 의미: None = 태그필터 비활성(스킵) / set()(빈) = 활성·0매치 → 0행(전체 아님) /
    # {...} = 활성·매칭. assign 은 0매치 시 빈 set 을 넣으므로(search_commands.py), truthy 검사로는
    # 빈 set 을 "필터 없음"으로 오인해 전체 풀을 노출한다 → 반드시 `is not None` 으로 구분.
    # ⚠️ id-keyed 한계(별도 후속 TODO): 같은 post-id 가 다른 태그로 여러 행에 흩어진 악성 중복
    #    데이터(겹치는 parquet 합치기 등)에선 isin 이 매칭 안 된 형제 행까지 포함 → 검색 count
    #    (per-row)와 적용 풀이 어긋남. 정상(유니크 id) 데이터엔 무영향. 근본 해결 = 검색/합치기 id dedup.
    if not query and not exclude:
        # 빠른 경로(라이브 태그필터/등급 적용): 전체 스냅샷을 두 번 copy 하지 않고 단일 boolean
        # mask 로 한 번만 슬라이스+copy 한다(대형 풀에서 assign 비용 절반). query/exclude 가 없을
        # 때만 — _apply_filters 경로는 컬럼 보강/tags_string 부수효과가 있어 기존대로 둔다.
        import pandas as pd

        mask = pd.Series(True, index=frame.index)
        if tag_ids is not None and "id" in frame.columns:
            mask &= frame["id"].isin(tag_ids)
        if ratings and "rating" in frame.columns:
            mask &= frame["rating"].isin(ratings)
        return frame[mask].copy()
    filtered = frame.copy()
    from core.search_engine import SearchEngine

    engine = SearchEngine()
    for column in engine.TAG_COLUMNS:
        if column not in filtered.columns:
            filtered[column] = ""
    filtered = engine._apply_filters(filtered, str(query or ""), str(exclude or ""))
    if "tags_string" in filtered.columns:
        filtered = filtered.drop(columns=["tags_string"])
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
            source = context.search_results_snapshot
    active_ids = getattr(context, "active_tag_filter_ids", None)
    # B3: assign 직후엔 tag_filter_search 가 이미 슬라이스한 매칭 프레임(등급-무관)을 재사용해
    # 전체 스냅샷 isin 재스캔/이중 copy 를 건너뛴다. 가드(identity): 프레임이 *현재*
    # active_tag_filter_ids 객체(assign 이 세팅한 그 set)와 *현재* snapshot 에 귀속될 때만 재사용.
    # 다른 경로(reconstruct/random/depth/clear)가 active_tag_filter_ids 를 새 객체로 재할당하거나
    # snapshot 이 교체되면 identity 가 어긋나 안전하게 filter_source_frame 폴백 — 무효화 사이트를
    # 일일이 건드릴 필요가 없다.
    reuse_frame = getattr(context, "active_tag_filter_frame", None)
    reuse_for = getattr(context, "active_tag_filter_frame_for", None)
    reuse_snap = getattr(context, "active_tag_filter_frame_snapshot", None)
    if (
        reuse_frame is not None
        and active_ids is not None
        and reuse_for is active_ids
        and source is not None
        and reuse_snap is source
    ):
        ratings = context.get_active_ratings()
        if ratings and "rating" in reuse_frame.columns:
            filtered = reuse_frame[reuse_frame["rating"].isin(ratings)].copy()
        else:
            filtered = reuse_frame.copy()
    else:
        filtered = filter_source_frame(
            source,
            ratings=context.get_active_ratings(),
            tag_ids=active_ids,
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
    # 백그라운드 writer 와 같은 파일 락 + 대기 중인 runner 복사 취소(더 오래된 풀이 덮지 않게).
    search_pool_writer(context).write_now(path, frame, kind="runner")
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
    with search_pool_state_guard(context):
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


def reconstruct_active_tag_filter(context: WebSessionContext) -> bool:
    # Serialized: only one reconstruct builds the heavy index; a concurrent caller
    # re-checks the guard inside and returns fast (no duplicate 1M-row scan).
    with _RECONSTRUCT_LOCK:
        return _reconstruct_active_tag_filter_impl(context)


def _reconstruct_active_tag_filter_impl(context: WebSessionContext) -> bool:
    """재시작/가져오기 후 영속된 '활성' 태그필터를 백엔드가 스냅샷 위에서 직접 재조립한다(권위 SSOT).

    in-memory 할당(active_tag_filter / active_tag_filter_ids)은 영속되지 않으므로 재시작 직후엔
    None 이다. 하지만 디스크 search_filter_state.tag_filter_active 는 True 로 남아 프론트엔 칩이
    보이고 카운트도 필터 기준으로 표시된다 → 사용자에겐 '필터 적용 중'으로 보이지만 실제 랜덤
    풀은 미적용(전체)이거나, 프론트의 1회성 warmup 재적용이 타이밍을 놓치면 표시 카운트와 실제
    풀이 어긋난다(사용자 리포트: 재시작 후 Random 이 필터를 무시/꼬임 → Quick→Clear 후 재입력
    해야 정상. result.success=True 라 빈-풀 failsafe 도 안 잡힘). 백엔드가 스냅샷 위에서 직접
    재검색→재할당하면 프론트 타이밍과 무관하게 '표시 == 실제 풀' 정합이 보장된다.

    - 이미 in-memory 할당이 있으면(=정상 작동 중) no-op.
    - import(install_custom_parquet_frame)/일반 검색(run_search_command)은 의도적으로
      tag_filter_active=False 로 두므로 여기서 재구성되지 않는다(기존 설계 보존).
    - 0매치여도 '활성' 의도는 보존한다(빈 풀은 handle_random_command failsafe 가 흡수). 백엔드가
      사용자 필터를 임의 해제하지 않는다.
    """
    if getattr(context, "active_tag_filter", None) or getattr(context, "active_tag_filter_ids", None) is not None:
        return False
    state = context.normalize_search_filter_state(getattr(context, "search_filter_state", None))
    if not state.get("tag_filter_active"):
        return False
    include = [str(tag) for tag in (state.get("tag_filter") or []) if str(tag).strip()]
    exclude = [str(tag) for tag in (state.get("tag_filter_exclude") or []) if str(tag).strip()]
    if not include and not exclude:
        return False
    snapshot = getattr(context, "search_results_snapshot", None)
    if snapshot is None or getattr(snapshot, "empty", True):
        return False
    tags = [*include, *[f"-{tag}" for tag in exclude]]
    result = tag_filter_search(context, tags)
    ids = result.get("_ids", set())
    source_snapshot = result.get("_source_snapshot")
    source_generation = int(result.get("_pool_generation") or 0)
    # 쓰기 순서 주의(Codex F2): 각 속성 대입은 GIL 하에서 원자적이고, 소비자 우선순위가 active_tag_filter
    # (dict)이므로 dict 를 마지막에 둔다 → dict 가 보이면 ids 도 이미 set. 반대(ids set·dict None)로
    # 찢긴 읽기는 _active_tag_filter_state 가 ids 로 임시 상태를 복원해 graceful. 동시 호출(get_search_state
    # + random 레이스)은 guard 를 둘 다 통과해 tag_filter_search 가 중복 실행될 수 있으나 결과가 동일
    # (idempotent)이라 무해 — 시작 시점 한정 드문 경우라 락은 두지 않는다.
    with search_pool_state_guard(context):
        if (
            source_snapshot is not getattr(context, "search_results_snapshot", None)
            or source_generation != current_search_pool_generation(context)
        ):
            return False
        context.active_tag_filter_ids = set(ids)
        context.active_tag_filter = {
            "tags": [str(tag) for tag in result.get("tags", [])],
            "ids": set(ids),
            "count": int(result.get("count") or 0),
            "request_id": "",
            "rating_counts": dict(result.get("rating_counts") or {}),
        }
        mark_tag_filter_changed(context)
        apply_search_runtime_filters(context)
    return True


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
        bucket_range = None
        if bucket_start is not None or bucket_end is not None:
            from core.tag_bucket_dates import clamp_bucket_range
            s, e = clamp_bucket_range(bucket_start, bucket_end, len(archive_sources))
            archive_sources = archive_sources[s:e + 1]
            bucket_range = (s, e)
        searched = search_tag_archive_frame(
            archive_sources,
            query=query,
            exclude=exclude,
            ratings=ratings,
            progress_callback=progress_callback,
        )
        searched = _dedup_by_id(searched)
        with search_pool_state_guard(context):
            context.search_results.set_dataframe(searched)
            context.search_results_snapshot = searched.copy()
            context.search_results_master_base_snapshot = searched.copy()
            context.search_results_scope = TAG_ARCHIVE_SCOPE
            mark_search_pool_replaced(context)
            _set_pool_provenance(context, _search_recipe(context, query, exclude, ratings, bucket_range), base=True)
            _reset_active_tag_filter_assignment(context)
            context.save_search_filter_state(tag_filter_active=False)
            context.remote_active_ratings = set("gsqe")
        context.persist_last_search()  # Part 3: 재시작/가져오기 후 복원용
        return apply_search_runtime_filters(context)

    base = search_base_frame(context)
    if base is None:
        return context.search_state_payload()
    searched = _dedup_by_id(filter_source_frame(base, query=query, exclude=exclude, ratings=ratings))
    with search_pool_state_guard(context):
        context.search_results_snapshot = searched.copy() if searched is not None else None
        mark_search_pool_replaced(context)
        # 아카이브가 없을 때: 불러온 셋 안에서 검색한 것 - 부모(복원 기준)를 품는다.
        recipe = _search_recipe(context, query, exclude, ratings, None)
        recipe["parent"] = getattr(context, "search_pool_base_provenance", None)
        _set_pool_provenance(context, recipe)
        _reset_active_tag_filter_assignment(context)
        context.save_search_filter_state(tag_filter_active=False)
        context.remote_active_ratings = set("gsqe")
    context.persist_last_search()  # Part 3: 재시작/가져오기 후 복원용
    return apply_search_runtime_filters(context)


def restore_search_snapshot(context: WebSessionContext) -> dict[str, Any]:
    base = search_base_frame(context)
    if base is not None:
        with search_pool_state_guard(context):
            context.search_results_snapshot = base.copy()
            mark_search_pool_replaced(context)
            _set_pool_provenance(context, getattr(context, "search_pool_base_provenance", None))
            _reset_active_tag_filter_assignment(context)
            context.save_search_filter_state(tag_filter_active=False)
            context.search_results.set_dataframe(base.copy())
    return search_state_with_runner_save(context)


def commit_pending_tag_filter_assignment(
    context: WebSessionContext,
    pending: dict[str, Any],
    request_id: str,
    client_key: str = "",
) -> dict[str, Any]:
    """Atomically validate and commit one pending tag-filter result.

    ``tag_filter_search`` is deliberately lock-free while scanning a large frame.
    This commit point is the ownership boundary: the pending object, request id,
    source DataFrame identity, and pool generation must all still match. Holding
    the pool-state lock through the cheap pre-sliced-frame apply prevents a
    concurrent parquet/search replacement from landing between validation and
    assignment.
    """
    with search_pool_state_guard(context):
        pending_by_client = getattr(context, "pending_tag_filters", None)
        if client_key and isinstance(pending_by_client, dict):
            pending_is_current = pending_by_client.get(client_key) is pending
        else:
            pending_is_current = getattr(context, "pending_tag_filter", None) is pending
        if not pending_is_current:
            return {"ok": False, "reason": "superseded"}
        if request_id and str(pending.get("request_id") or "") != request_id:
            return {"ok": False, "reason": "request_mismatch"}
        if (
            pending.get("source_snapshot") is not getattr(context, "search_results_snapshot", None)
            or int(pending.get("pool_generation") or 0) != current_search_pool_generation(context)
        ):
            if client_key and isinstance(pending_by_client, dict):
                pending_by_client.pop(client_key, None)
            if getattr(context, "pending_tag_filter", None) is pending:
                context.pending_tag_filter = None
            return {"ok": False, "reason": "pool_changed"}

        context.active_tag_filter_ids = set(pending.get("ids") or set())
        context.active_tag_filter_frame = pending.get("frame")
        context.active_tag_filter_frame_for = context.active_tag_filter_ids
        context.active_tag_filter_frame_snapshot = pending.get("source_snapshot")
        tags = [str(tag) for tag in pending.get("tags", [])]
        context.active_tag_filter = {
            "tags": tags,
            "ids": set(context.active_tag_filter_ids),
            "count": int(pending.get("count") or 0),
            "request_id": request_id,
            "rating_counts": dict(pending.get("rating_counts") or {}),
        }
        # ⚠️ **여기가 "검색이 적용되는 시점"** 이다 - 스냅샷은 여기서 뜬다
        #    (사용자 지정 2026-08-31). `active_tag_filter_ids` 는 뽑을 때마다 하나씩
        #    소모되는 집합이라, 다 쓰고 나면 풀이 빈다. 그때 등급을 열고 필터를
        #    해제하던 것이 **오작동**이었다 - 사용자가 걸어 둔 조건이 말없이 사라졌다.
        #    이제는 이 스냅샷을 되돌려 **같은 조건으로 다시 채운다**.
        context.active_tag_filter_snapshot = {
            "ids": set(context.active_tag_filter_ids),
            "tags": list(tags),
            "count": int(pending.get("count") or 0),
            "rating_counts": dict(pending.get("rating_counts") or {}),
            "request_id": request_id,
        }
        mark_tag_filter_changed(context)
        context.save_search_filter_state(
            tag_filter=[tag for tag in tags if not tag.startswith("-")],
            tag_filter_exclude=[tag.lstrip("-") for tag in tags if tag.startswith("-")],
            tag_filter_active=True,
        )
        if client_key and isinstance(pending_by_client, dict):
            pending_by_client.pop(client_key, None)
        if getattr(context, "pending_tag_filter", None) is pending:
            context.pending_tag_filter = None
        state = apply_search_runtime_filters(context)
        return {
            "ok": True,
            "state": state,
            "count": int(pending.get("count") or 0),
            "tags": tags,
            "rating_counts": dict(pending.get("rating_counts") or {}),
        }


_TAG_HITS_CAP = 4000  # 한 데이터셋 내 칩별 캐시 상한 (초과 시 비우고 lazy 재계산; tags_text는 유지)


def _tag_filter_cache(context: WebSessionContext, snapshot) -> dict:
    """칩(태그) 단위 캐시 — 데이터셋(snapshot) 객체 기준.

    snapshot 은 데이터셋이 바뀔 때마다(새 검색 / Parquet 로드·합치기 / 복원 — 전부 `.copy()`로
    새 객체 할당) 교체되므로, 캐시가 들고 있는 snapshot 과 identity(`is`)가 어긋나면 통째로 폐기한다
    (= "Parquet 교체 시 캐시 삭제"가 별도 훅 없이 자동 충족). 등급/assign 은 snapshot 을 교체하지
    않으므로 캐시가 유지된다.

    구조: tags_text(행별 소문자 태그 문자열, 데이터셋당 1회 계산) + tag_hits{태그 → 행별 numpy bool 마스크}.
    """
    cache = getattr(context, "_tag_filter_cache", None)
    if cache is None or cache.get("snapshot") is not snapshot:
        cache = {"snapshot": snapshot, "tags_text": None, "tag_hits": {}}
        context._tag_filter_cache = cache
    return cache


# Pool-loading ownership (Tag/Tag-Filter lock + Random gate + toast) lives on
# WebSessionContext: context.pool_loading_begin/progress/end. The counter + lock +
# publish-under-lock are shared with the chunked parquet LOAD phase so neither phase
# clears the other's still-active flag and the WS event order matches the state
# transition (no stale loading:true after loading:false). This module calls those
# methods directly (tag_filter_search gating + build/match heartbeats).


def _tag_filter_executor() -> ThreadPoolExecutor:
    """Tag Filter 색인 빌드·칩 매칭용 공유 스레드 풀(프로세스 하나).

    pyarrow compute 는 GIL 을 풀기 때문에 행 배치를 스레드로 나누면 실제로 병렬이 된다.
    실측(1.3M 행, 16코어, 8스레드): 빌드 4.77s→1.34s, 칩 12개 매칭 12.67s→1.01s, 결과 동일."""
    global _TAG_FILTER_POOL
    if _TAG_FILTER_POOL is None:
        with _TAG_FILTER_POOL_GUARD:
            if _TAG_FILTER_POOL is None:
                _TAG_FILTER_POOL = ThreadPoolExecutor(
                    max_workers=_TAG_FILTER_WORKERS, thread_name_prefix="naia-tagfilter"
                )
    return _TAG_FILTER_POOL


def _tag_filter_memory_pool():
    """Tag Filter 연산 전용 = 시스템 메모리 풀(해제 즉시 OS 반환). 이유는 _build_tags_text 참조."""
    import pyarrow as pa

    return pa.system_memory_pool()


def _build_tags_text(frame, tag_columns: list[str], heartbeat=None):
    """행별 소문자 태그 텍스트 색인 - pyarrow ChunkedArray(large_string), 배치(10만 행)당 청크 1개.

    배치를 스레드 풀에서 나눠 만든다. 청크 순서 = 행 순서라 positional 마스크가 ``frame`` 과
    정렬된다. 내용은 예전 ``str.cat(sep=',').str.lower()`` 와 **같다**(1.3M 실데이터 전 행 동일).
    ⚠️ pandas 3 의 문자열 열은 이미 arrow 라 예전 경로도 utf8_lower 였다 - 소문자화 의미 불변.
    ``heartbeat(loaded_rows, total_rows)`` 는 호출 스레드에서 배치가 끝날 때마다 부른다."""
    import pyarrow as pa
    import pyarrow.compute as pc

    n = len(frame)
    if n == 0:
        return pa.chunked_array([], type=pa.large_string())
    # 열 Series 는 호출 스레드에서 꺼낸다 - 작업 스레드는 읽기 전용 iloc 슬라이스만 한다.
    columns = [frame[c] for c in tag_columns]
    sep = pa.scalar(",", pa.large_string())
    empty = pa.scalar("", pa.large_string())
    # ⚠️ 시스템 메모리 풀로 한정한다. 기본 풀(mimalloc)은 병렬 배치의 중간 배열을 해제해도 OS 에
    #    돌려주지 않아 RSS 가 텍스트 크기의 약 3배(+1.86GB / 1.3M 행)로 남았다. 이 연산에만
    #    시스템 풀을 쓰면 +0.89GB, 속도는 같다(실측). 프로세스 전역 풀은 건드리지 않는다.
    mp = _tag_filter_memory_pool()

    def build(start: int):
        sl = slice(start, start + _TAGS_TEXT_BATCH)
        arrs = [
            pa.array(col.iloc[sl].fillna("").astype(str), type=pa.large_string(), memory_pool=mp)
            for col in columns
        ]
        joined = arrs[0] if len(arrs) == 1 else pc.binary_join_element_wise(*arrs, sep, memory_pool=mp)
        return pc.utf8_lower(pc.coalesce(joined, empty, memory_pool=mp), memory_pool=mp)

    starts = list(range(0, n, _TAGS_TEXT_BATCH))
    chunks = []
    for start, chunk in zip(starts, _tag_filter_executor().map(build, starts)):  # map = 순서 보존
        chunks.append(chunk)
        if heartbeat is not None:
            try:
                heartbeat(min(start + _TAGS_TEXT_BATCH, n), n)
            except Exception:
                pass
    return pa.chunked_array(chunks, type=pa.large_string())


def _match_tags_text(tags_text, pattern: str):
    """RE2 정규식으로 청크별 병렬 매칭 → 행별 numpy bool 마스크.

    부분일치도 ``re.escape(key)`` 리터럴 정규식으로 돈다 - 같은 리터럴이라도 RE2 경로가
    ``match_substring`` 보다 1.6~3.5배 빠르다(실측). 태그 텍스트가 행당 평균 499바이트라
    1.3M 행이면 칩 하나가 659MB 를 훑는다 - 병렬이 아니면 칩당 ~1초였다."""
    import numpy as np
    import pyarrow.compute as pc

    if tags_text.num_chunks == 0:
        return np.zeros(0, dtype=bool)

    mp = _tag_filter_memory_pool()

    def match(chunk):
        hits = pc.match_substring_regex(chunk, pattern, memory_pool=mp)
        return pc.coalesce(hits, False, memory_pool=mp).to_numpy(zero_copy_only=False)

    return np.concatenate(list(_tag_filter_executor().map(match, tags_text.chunks)))


def tag_filter_search(context: WebSessionContext, tags: list[Any]) -> dict[str, Any]:
    return _tag_filter_search_impl(context, tags)


def _tag_filter_search_impl(context: WebSessionContext, tags: list[Any]) -> dict[str, Any]:
    # Capture snapshot identity and its monotonic generation under the same lock.
    # The expensive scan runs lock-free, but result/assign must prove both values
    # are still current before publishing or committing the matched frame.
    with search_pool_state_guard(context):
        snapshot = getattr(context, "search_results_snapshot", None)
        if snapshot is None or getattr(snapshot, "empty", True):
            snapshot = search_base_frame(context)
            if snapshot is not None:
                context.search_results_snapshot = snapshot.copy()
                snapshot = context.search_results_snapshot
        source_generation = current_search_pool_generation(context)
    normalized = WebSessionContext.normalize_filter_tags(tags)
    if snapshot is None or getattr(snapshot, "empty", True):
        return {
            "type": "tag_filter_result",
            "count": 0,
            "tags": normalized,
            "rating_counts": rating_counts_from_frame(None),
            "_ids": set(),
            "_source_snapshot": snapshot,
            "_pool_generation": source_generation,
        }

    # Announce + gate the 'filter' phase AFTER the snapshot is resolved — the
    # resolution above can recover a LARGE frame via search_base_frame, which a
    # pre-resolution size check (in the caller) would miss and then scan un-gated.
    # Large pool (cached or not): even a cached index runs one str.contains per chip
    # over the whole pool, and with many persisted chips that interval can outlast
    # the frontend safety timers. Small pools (< threshold) stay silent — near-
    # instant, so a lock/toast would only flash. The heartbeat re-arms both frontend
    # timers across the entire build + per-chip matching lifetime.
    heavy = False
    try:
        heavy = len(snapshot) >= _POOL_LOADING_THRESHOLD
    except Exception:
        heavy = False
    if not heavy:
        result = _run_tag_filter(context, snapshot, tags, heartbeat=None)
        result["_source_snapshot"] = snapshot
        result["_pool_generation"] = source_generation
        return result
    context.pool_loading_begin("filter")
    try:
        def heartbeat(loaded: int, total: int) -> None:
            context.pool_loading_progress("filter", loaded, total)

        result = _run_tag_filter(context, snapshot, tags, heartbeat=heartbeat)
        result["_source_snapshot"] = snapshot
        result["_pool_generation"] = source_generation
        return result
    finally:
        context.pool_loading_end()


def _run_tag_filter(context: WebSessionContext, snapshot, tags: list[Any], *, heartbeat=None) -> dict[str, Any]:
    cache = _tag_filter_cache(context, snapshot)
    if cache["tags_text"] is None:
        # Double-checked build under a lock so a concurrent search reuses the
        # index instead of rebuilding the whole 1M+ row text column.
        with _TAG_INDEX_BUILD_LOCK:
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
                # 행별 소문자 태그-텍스트 인덱스를 row-batch 청크로 빌드(_build_tags_text). 피크 메모리를
                # 배치 1개분으로 상한(전체 parts×N + cat + lower 동시보유 제거) + 배치마다 heartbeat 로
                # 프론트 안전타이머 재무장. 결과는 단일 패스 str.cat/lower 와 동일(순서/인덱스 보존).
                cache["tags_text"] = _build_tags_text(frame, tag_columns, heartbeat=heartbeat)
    tags_text = cache["tags_text"]
    row_count = cache["row_count"]

    def _store_mask(cache_key, mask):
        if len(cache["tag_hits"]) >= _TAG_HITS_CAP:
            cache["tag_hits"].clear()  # 메모리 상한 — tags_text 유지라 재계산 저렴
        cache["tag_hits"][cache_key] = mask
        return mask

    def _hit_mask(key: str, exact: bool = False):
        # 행(positional) 단위 boolean 마스크(numpy). id 가 아니라 행 위치 기준이라 중복 id(합친
        # parquet)에서도 구버전 per-row mask 와 동치. 파이썬 int frozenset(원소당 ~28바이트) 대신
        # 1 byte/row bool 배열 → 대형 풀에서 매칭 메모리 스파이크(스와핑)를 제거한다.
        #
        # ⚠️ 캐시 키는 **(exact, key) 튜플**이다. 문자열 하나로 두면 `sky` 와 `*sky` 가 같은
        #    마스크를 공유해 토글해도 결과가 안 바뀐다(조용히 틀린다). 튜플이라 sigil 문자와
        #    충돌할 여지도 없다.
        cache_key = (exact, key)
        cached = cache["tag_hits"].get(cache_key)
        if cached is not None:
            return cached
        if not exact:
            return _store_mask(cache_key, _match_tags_text(tags_text, re.escape(key)))
        # 퍼펙트 매칭: SEARCH(`core/search_engine.py` contains_exact)와 **같은 경계**를 쓴다 -
        # 쉼표뿐. 같은 `*tag` 가 화면마다 다른 뜻이 되는 것이 최악이라 의도적으로 복제한다.
        # ⚠️ 예전엔 경계가 쉼표 **또는 공백**이라 `*sky` 가 `cloudy sky` 에도 걸렸다 -
        #    태그 전체 일치가 아니었다. 양쪽을 같이 고쳤다(사용자 제보 2026-08-25).
        # ⚠️ 공백 클래스는 `\s` 가 아니라 `_RE2_PY_WS` 다. RE2 의 `\s` 는 ASCII 뿐인데 예전 경로
        #    (파이썬 re)의 `\s` 는 NBSP·전각 공백까지 먹었다 - 그대로 쓰면 `a,\xa0b` 에서 `*b` 가 빠진다.
        # (예전의 '부분 마스크 후보만 훑기'는 뺐다 - 병렬 전체 스캔이 칩당 ~0.1초라 이득이 없다.)
        pattern = r"(?:^|,)" + _RE2_PY_WS + "*" + re.escape(key) + _RE2_PY_WS + r"*(?:,|$)"
        return _store_mask(cache_key, _match_tags_text(tags_text, pattern))

    def _beat():
        # bracket 하트비트: 각 (미캐시 가능) str.contains scan 직전과 최종 materialize 직전에 발행 →
        # 개별 scan tail 이나 결과 슬라이싱이 안전타이머(180s/90s)를 넘겨도 잠금 유지(총 텍스트만 표시).
        if heartbeat is None:
            return
        try:
            heartbeat(0, 0)
        except Exception:
            pass

    # 먼저 모든 칩을 (clean, negate)로 분해 — 프론트가 "1girl, armpits" 한 칩을 통째로 보내도 두
    # 태그로 매칭/표기(예약 버그). negate('-')는 분리 후 서브토큰별 판정('1girl, -armpits' →
    # include 1girl + exclude armpits).
    parsed: list[tuple[str, bool, bool]] = []
    clean_tags: list[str] = []
    for item in tags:
        for raw in re.split(r"[,\n]", str(item or "")):
            raw = raw.strip()
            if not raw:
                continue
            negate = raw.startswith("-")
            # replace 후 strip: 프론트가 보낸 "_armpits"의 선행 '_'(원래 공백)가 공백→제거되도록
            # (strip→replace 순서면 " armpits"로 남아 매칭이 깨진다).
            clean = raw.lstrip("-").replace("_", " ").strip()
            # 선행 `*` = 퍼펙트 매칭(SEARCH 와 같은 표기). **예약 문자**다 - 지금 태그 사전
            # 150개 parquet 전수에 `*` 를 포함한 실제 태그는 0개지만, 커스텀 parquet 은
            # 태그 문자를 검증하지 않으므로 규약으로 못박는다.
            # ⚠️ `lstrip("*")` 으로 **전부** 벗긴다. SEARCH 도 그렇고(`search_engine.py:49`)
            #    프런트 `baseTag` 도 그렇다 - 여기만 하나씩 벗기면 `**tag` 가 SEARCH 에선
            #    `tag`, 칩에선 literal `*tag` 를 골라 같은 입력이 두 화면에서 갈린다.
            exact = clean.startswith("*")
            if exact:
                clean = clean.lstrip("*").strip()
            if not clean:
                continue
            # ⚠️ **영속 토큰에 `*` 를 되살린다.** 여기서 만든 `clean_tags` 가 pending 을 거쳐
            #    그대로 디스크(`save_search_filter_state`)에 쓰인다 - 벗겨낸 채로 두면
            #    재시작 시 exact 가 조용히 부분일치로 강등된다(Codex 지적).
            clean_tags.append(("-" if negate else "") + ("*" if exact else "") + clean)
            parsed.append((clean, negate, exact))

    include_mask = None                                  # None = 아직 제한 없음(전체 행)
    exclude_mask = np.zeros(row_count, dtype=bool)
    for clean, negate, exact in parsed:
        _beat()                                          # 이 칩의 str.contains scan 직전
        m = _hit_mask(clean.lower(), exact)
        if negate:
            exclude_mask |= m
        elif include_mask is None:
            include_mask = m.copy()                      # copy → 이후 &= 가 캐시 마스크를 변형하지 않음
        else:
            include_mask &= m
    if include_mask is None:
        include_mask = np.ones(row_count, dtype=bool)
    _beat()                                              # 마지막 scan tail + 최종 materialize 직전
    final_mask = include_mask & ~exclude_mask if exclude_mask.any() else include_mask

    frame = cache["frame"]
    matched = frame[final_mask]                           # positional boolean index (set(range())/sorted() 제거)
    ids = set(matched["id"].tolist()) if cache["has_id"] else set(matched.index.tolist())
    return {
        "type": "tag_filter_result",
        "count": int(len(matched)),
        "tags": clean_tags,
        "rating_counts": rating_counts_from_frame(matched),
        "_ids": ids,
        # B3: 이미 슬라이스된 매칭 프레임(등급-무관)을 동봉 → assign 이 active 로 이관해
        # apply_search_runtime_filters 가 전체 스냅샷 isin 재스캔을 건너뛴다(가드는 호출부).
        "_frame": matched,
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
    from core.parquet_chunk_loader import read_parquet_chunked, make_search_load_progress

    # Chunked read + progress broadcast so a large custom parquet load/merge shows
    # the Tag/Tag-Filter lock + '풀 로딩 N%' (the frontend also locks on click).
    from core.custom_parquet_library import file_recipe, merge_recipe

    progress, done = make_search_load_progress(context)
    try:
        frame = read_parquet_chunked(path, progress=progress)
        frame = normalize_custom_parquet_frame(frame)
        provenance = file_recipe(path)
        if merge:
            current = merge_base_frame(context)
            if current is not None and not current.empty:
                frame = pd.concat([current, frame], ignore_index=True)
                frame = normalize_custom_parquet_frame(frame)
                provenance = merge_recipe(pool_provenance(context), provenance)
        install_custom_parquet_frame(context, frame, provenance=provenance)
    finally:
        done()
    # runner 는 install 이 백그라운드로 복사한다 - 여기서 다시 쓰면 응답 전에 풀 전체를 또 쓴다.
    state = context.search_state_payload()
    state["merged" if merge else "loaded"] = path.name
    verb = "merged" if merge else "loaded"
    return state, {"type": "toast", "message": f"{path.name} {verb} ({len(frame):,})", "level": "success"}


def export_condition_frame(context: WebSessionContext):
    """'조건에 맞는 행 전체' = snapshot × 활성 등급 × 활성 태그필터 (사용자 결정 D2).

    ⚠️ `search_results.get_dataframe()` 이 아니다 - 그건 Random 이 뽑아 쓴 행이 빠진 남은 풀이라
    저장할 때마다 내용이 줄어든다. 반환: (frame, recipe)."""
    with search_pool_state_guard(context):
        source = getattr(context, "search_results_snapshot", None)
        if source is None or getattr(source, "empty", True):
            source = search_base_frame(context)
        ratings = context.get_active_ratings()
        tag_ids = getattr(context, "active_tag_filter_ids", None)
        active = getattr(context, "active_tag_filter", None) or {}
        parent = pool_provenance(context)
    frame = filter_source_frame(source, ratings=ratings, tag_ids=tag_ids)
    recipe: dict[str, Any] = {"source": "export", "parent": parent, "ratings": sorted(ratings or [])}
    tags = [str(t) for t in (active.get("tags") or [])] if tag_ids is not None else []
    if tags:
        recipe["tag_filter"] = {
            "include": [t for t in tags if not t.startswith("-")],
            "exclude": [t[1:] for t in tags if t.startswith("-")],
        }
    return frame, recipe


def _library_toast(message: str, level: str = "success") -> dict[str, Any]:
    return {"type": "toast", "message": message, "level": level}


_LIBRARY_ERRORS = {
    "invalid_source": "잘못된 파일 이름입니다",
    "invalid_name": "쓸 수 없는 이름입니다",
    "not_found": "파일을 찾을 수 없습니다",
    "exists": "같은 이름의 파일이 이미 있습니다",
}


def search_parquet_action(context: WebSessionContext, command: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    from core import custom_parquet_library as lib

    action = str(command.get("action") or "").strip()
    directory = context.custom_parquet_dir()
    if action == "rename":
        ok, info = lib.rename(directory, str(command.get("filename") or ""), str(command.get("new_name") or ""))
        if not ok:
            return context.search_state_payload(), _library_toast(_LIBRARY_ERRORS.get(info, info), "error")
        return context.search_state_payload(), _library_toast(f"이름을 바꿨습니다 → {info}")
    if action == "trash":
        ok, info = lib.trash(directory, str(command.get("filename") or ""))
        if not ok:
            return context.search_state_payload(), _library_toast(_LIBRARY_ERRORS.get(info, info), "error")
        return context.search_state_payload(), _library_toast(f"휴지통으로 옮겼습니다 ({lib.TRASH_DIR}/{info})")
    if action == "export_results":
        frame, recipe = export_condition_frame(context)
        if frame is None or frame.empty:
            return context.search_state_payload(), _library_toast("저장할 행이 없습니다", "error")
        requested = str(command.get("filename") or "").strip()
        path = next_custom_parquet_path(context, requested, fallback_prefix="search_export")
        # 이름을 직접 적었는데 이미 있으면 덮어쓰지 않는다(예전엔 조용히 덮었다).
        if requested and path.exists():
            return context.search_state_payload(), _library_toast(_LIBRARY_ERRORS["exists"], "error")
        lib.write_parquet(frame, path, lib.make_meta(recipe.get("source", "export"), recipe, len(frame)))
        return context.search_state_payload(), _library_toast(f"저장했습니다 {path.name} ({len(frame):,}행)")
    frame = context.search_results.get_dataframe() if context.search_results else None
    if frame is None or frame.empty:
        return context.search_state_payload(), {"type": "toast", "message": "No search results to save", "level": "error"}
    if action == "save_runner":
        path = context.runner_parquet_path()
        search_pool_writer(context).write_now(path, frame, kind="runner")
        message = f"Saved runner parquet ({len(frame):,})"
    else:
        return context.search_state_payload(), {"type": "toast", "message": "Unsupported parquet action", "level": "error"}
    return context.search_state_payload(), {"type": "toast", "message": message, "level": "success"}
