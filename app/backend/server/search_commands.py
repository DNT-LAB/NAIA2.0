from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

from fastapi import WebSocket

from app.backend.server.search_runtime import (
    apply_search_runtime_filters,
    clear_active_tag_filter,
    commit_pending_tag_filter_assignment,
    current_search_pool_generation,
    load_or_merge_custom_parquet,
    reconstruct_active_tag_filter,
    restore_search_snapshot,
    run_search_command,
    search_parquet_action,
    search_pool_state_guard,
    tag_filter_search,
)
from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]
BroadcastJson = Callable[[set[WebSocket], dict[str, Any]], Awaitable[None]]

SEARCH_COMMAND_TYPES = {
    "set_active_ratings",
    "get_search_state",
    "save_search_filter_state",
    "get_bucket_dates",
    "search",
    "load_parquet",
    "merge_parquet",
    "search_parquet_action",
    "restore_snapshot",
    "tag_filter_search",
    "tag_filter_assign",
    "tag_filter_clear",
    "save_filter_preset",
    "delete_filter_preset",
}


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


async def _send_shared_search_state(
    ws: WebSocket,
    payload: dict[str, Any],
    *,
    clients: set[WebSocket] | None,
    broadcast_json: BroadcastJson | None,
) -> None:
    """Publish one authoritative search state to every connected view.

    Direct unit callers do not own a client registry, so they retain the old
    requester-only behavior. The websocket runtime supplies both arguments.
    """
    if clients is not None and broadcast_json is not None:
        await broadcast_json(clients, payload)
    else:
        await _send_json(ws, payload)


async def handle_search_command(
    ws: WebSocket,
    context: WebSessionContext,
    command: dict[str, Any],
    *,
    run_in_thread: AsyncRunner,
    clients: set[WebSocket] | None = None,
    broadcast_json: BroadcastJson | None = None,
) -> bool:
    command_type = str(command.get("type") or "").strip()
    if command_type not in SEARCH_COMMAND_TYPES:
        return False

    if command_type == "set_active_ratings":
        context.set_active_ratings(command.get("ratings"))
        context.save_search_filter_state(ratings=context.get_active_ratings())
        state = await run_in_thread(apply_search_runtime_filters, context)
        await _send_json(ws, state)
        return True

    if command_type == "get_search_state":
        # Startup-restore reliability: the random warmup that restores the last runner
        # parquet into search_results runs async during lifespan, so a client that asks
        # for search state before warmup finishes would see an empty pool. Lazily ensure
        # the results are restored here (idempotent; respects the same fallback-skip
        # rules as warmup — a filtered legacy cache is still skipped). Cheap no-op once
        # search_results is populated.
        # A chunked pool load already in flight (startup warmup or another client):
        # don't start a second read or block — lock this client with progress; the
        # load's completion broadcast prompts a refresh.
        loading = getattr(context, "_search_pool_loading", None)
        if isinstance(loading, dict) and loading.get("active"):
            payload = {
                "type": "search_loading",
                "loading": True,
                "loaded": int(loading.get("loaded") or 0),
                "total": int(loading.get("total") or 0),
            }
            if loading.get("phase"):
                payload["phase"] = loading.get("phase")
            await _send_json(ws, payload)
            return True
        if context.search_results is None or context.search_results.is_empty():
            service = getattr(context, "headless_random_prompt_service", None)
            if service is None:
                from core.headless_random_prompt_service import HeadlessRandomPromptService

                service = HeadlessRandomPromptService(context)
                context.headless_random_prompt_service = service
            await run_in_thread(service._ensure_search_results, {}, announce=True)
        # 영속된 활성 태그필터를 백엔드가 직접 재조립(권위) — 프론트 warmup 재적용 타이밍과 무관하게
        # 표시 카운트와 실제 랜덤 풀이 일치하도록(재시작/가져오기 후 'random 이 필터 무시/꼬임' 수정).
        await run_in_thread(reconstruct_active_tag_filter, context)
        await _send_json(ws, context.search_state_payload())
        return True

    if command_type == "get_bucket_dates":
        from core.tag_bucket_dates import load_bucket_dates, default_bucket_range
        data = await run_in_thread(load_bucket_dates, context)
        buckets = data.get("buckets", []) if isinstance(data, dict) else []
        default_start, default_end = default_bucket_range(buckets)
        state = context.normalize_search_filter_state(getattr(context, "search_filter_state", None))
        cur_start = state.get("bucket_start")
        cur_end = state.get("bucket_end")
        await _send_json(ws, {
            "type": "bucket_dates",
            "bucket_count": len(buckets),
            "buckets": buckets,
            "default_start": default_start,
            "default_end": default_end,
            "current_start": cur_start if cur_start is not None else default_start,
            "current_end": cur_end if cur_end is not None else default_end,
        })
        return True

    if command_type == "save_search_filter_state":
        await run_in_thread(context.save_search_filter_state_from_payload, command)
        return True

    if command_type == "search":
        archive_count = 0
        sources = getattr(context, "tag_archive_parquet_sources", None)
        # The green [검색] is always a full tag-archive search (a previously fast-loaded
        # custom parquet must not confine it — see run_search_command), so count the
        # archive sources for the progress bar regardless of the current scope.
        if callable(sources):
            archive_count = len(sources())
        # ⚠️ 기간 컷오프를 **여기서도 똑같이 적용한다.** 진행률의 여는/닫는 메시지는
        #    이 수를 쓰고 중간 메시지는 실제로 훑는 수를 쓰는데, 둘이 갈리면 막대가
        #    `0/175 -> 25/25 -> 175/175` 로 튄다. 슬라이싱 규칙은
        #    `run_search_command` 와 같아야 한다 - 다르면 또 갈린다.
        if archive_count and (command.get("bucket_start") is not None
                              or command.get("bucket_end") is not None):
            from core.tag_bucket_dates import clamp_bucket_range

            s, e = clamp_bucket_range(command.get("bucket_start"),
                                      command.get("bucket_end"), archive_count)
            archive_count = e - s + 1
        progress_total = max(1, archive_count)
        await _send_json(ws, {
            "type": "search_progress",
            "completed": 0,
            "total": progress_total,
        })
        # Stream per-file progress from the worker thread onto this event loop so
        # the "Searching... N/150" counter actually climbs instead of sitting at 0.
        loop = asyncio.get_running_loop()

        def _emit_progress(completed: int, total: int) -> None:
            asyncio.run_coroutine_threadsafe(
                _send_json(ws, {"type": "search_progress", "completed": completed, "total": total}),
                loop,
            )

        state = await run_in_thread(run_search_command, context, command, progress_callback=_emit_progress)
        await _send_json(ws, {
            "type": "search_progress",
            "completed": progress_total,
            "total": progress_total,
        })
        # 이 search_state 가 '실제 green 검색 완료'임을 표시한다. 검색은 워커 스레드로
        # 돌아(비블로킹) 그동안 rating 토글/tag_filter 공유 broadcast 등 다른 search_state 가
        # 끼어들 수 있는데, 프론트가 그걸 검색 완료로 오인해 Quick Filter '해제됨' 오버레이를
        # 잘못 띄우고 pool 잠금을 조기 해제하던 문제(Codex A3). 이 명령이 보내는 완료 state 에만
        # 마커를 달아, 프론트가 끼어든 broadcast 를 무시하게 한다.
        if isinstance(state, dict):
            state["search_completed"] = True
        await _send_json(ws, state)
        return True

    if command_type in {"load_parquet", "merge_parquet"}:
        state, toast = await run_in_thread(
            load_or_merge_custom_parquet,
            context,
            str(command.get("filename") or ""),
            merge=command_type == "merge_parquet",
        )
        await _send_json(ws, state)
        await _send_json(ws, toast)
        return True

    if command_type == "search_parquet_action":
        state, toast = await run_in_thread(search_parquet_action, context, command)
        await _send_json(ws, state)
        await _send_json(ws, toast)
        return True

    if command_type == "restore_snapshot":
        state = await run_in_thread(restore_search_snapshot, context)
        await _send_json(ws, state)
        return True

    if command_type == "tag_filter_search":
        tags = command.get("tags") if isinstance(command.get("tags"), list) else []
        request_id = str(command.get("request_id") or "")
        client_key = str(command.get("_tag_filter_client_key") or "")
        result = await run_in_thread(tag_filter_search, context, tags)
        # B4: 검색이 백그라운드 태스크(websocket_session)라 완료 시점에 더 새로운 검색이 시작됐을 수
        # 있다(to_thread 는 취소로 안 멈춤). superseded(seq 불일치) 면 pending 미기록·미전송으로 폐기
        # — 최신 seq 만 통과해 stale 결과가 pending 을 덮어쓰는 reorder 해저드를 막는다.
        seq = command.get("_seq")
        seq_guard = command.get("_seq_guard")
        if isinstance(seq_guard, dict):
            latest_seq = seq_guard.get("seq", seq)
        else:
            # Backward-compatible path for direct callers and older tests.
            latest_seq = getattr(context, "_tag_filter_search_seq", seq)
        if seq is not None and seq != latest_seq:
            return True
        ids = result.pop("_ids", set())
        # B3: 매칭 프레임은 DataFrame 이라 JSON 전송 전에 반드시 pop(직렬화 불가). assign 이 active 로 옮긴다.
        matched_frame = result.pop("_frame", None)
        source_snapshot = result.pop("_source_snapshot", None)
        source_generation = int(result.pop("_pool_generation", 0) or 0)
        if request_id:
            result["request_id"] = request_id
        with search_pool_state_guard(context):
            pool_changed = (
                source_snapshot is not getattr(context, "search_results_snapshot", None)
                or source_generation != current_search_pool_generation(context)
            )
            if not pool_changed:
                pending = {
                    "tags": result.get("tags", []),
                    "ids": ids,
                    "frame": matched_frame,
                    "source_snapshot": source_snapshot,
                    "pool_generation": source_generation,
                    "count": result.get("count", 0),
                    "request_id": request_id,
                    "rating_counts": result.get("rating_counts", {}),
                }
                context.pending_tag_filter = pending
                pending_by_client = getattr(context, "pending_tag_filters", None)
                if client_key and isinstance(pending_by_client, dict):
                    pending_by_client[client_key] = pending
        if pool_changed:
            await _send_json(ws, {
                "type": "tag_filter_stale",
                "request_id": request_id,
                "reason": "pool_changed",
            })
            return True
        await _send_json(ws, result)
        return True

    if command_type == "tag_filter_assign":
        client_key = str(command.get("_tag_filter_client_key") or "")
        pending_by_client = getattr(context, "pending_tag_filters", None)
        pending = (
            pending_by_client.get(client_key)
            if client_key and isinstance(pending_by_client, dict)
            else getattr(context, "pending_tag_filter", None)
        )
        request_id = str(command.get("request_id") or "")
        if not pending:
            await _send_json(ws, {
                "type": "tag_filter_stale",
                "request_id": request_id,
                "reason": "pending_missing",
            })
            return True
        if request_id and str(pending.get("request_id") or "") != request_id:
            await _send_json(ws, {
                "type": "tag_filter_stale",
                "request_id": request_id,
                "reason": "request_mismatch",
            })
            return True
        committed = await run_in_thread(
            commit_pending_tag_filter_assignment,
            context,
            pending,
            request_id,
            client_key,
        )
        if not committed.get("ok"):
            reason = str(committed.get("reason") or "stale")
            await _send_json(ws, {
                "type": "tag_filter_stale",
                "request_id": request_id,
                "reason": reason,
            })
            return True
        state = committed["state"]
        state["tag_filter_settled"] = True
        state["tag_filter_rating_counts"] = committed.get("rating_counts", {})
        await _send_json(ws, {
            "type": "tag_filter_assigned",
            "request_id": request_id,
            "tag_filter_revision": int(state.get("tag_filter_revision") or 0),
            "count": committed.get("count", 0),
            "tags": committed.get("tags", []),
            "rating_counts": committed.get("rating_counts", {}),
        })
        await _send_shared_search_state(
            ws,
            state,
            clients=clients,
            broadcast_json=broadcast_json,
        )
        return True

    if command_type == "tag_filter_clear":
        # keep_draft=True (chip edit) clears only the active assignment and keeps
        # the persisted include/exclude draft, so the search_state echo does not
        # wipe the remaining chips. Absent (explicit "Clear") resets the draft too.
        keep_draft = bool(command.get("keep_draft"))
        state = await run_in_thread(clear_active_tag_filter, context, not keep_draft)
        state["tag_filter_settled"] = True
        await _send_json(ws, {
            "type": "tag_filter_result",
            "count": 0,
            "tags": [],
            "rating_counts": {rating: 0 for rating in "gsqe"},
        })
        await _send_shared_search_state(
            ws,
            state,
            clients=clients,
            broadcast_json=broadcast_json,
        )
        return True

    if command_type == "save_filter_preset":
        name = str(command.get("name") or "").strip()
        include = command.get("include") if isinstance(command.get("include"), list) else []
        exclude = command.get("exclude") if isinstance(command.get("exclude"), list) else []
        if name:
            await run_in_thread(context.save_filter_preset, name, include, exclude)
        # 갱신된 filter_presets 를 search_state 로 echo (프런트가 목록 재렌더)
        await _send_json(ws, context.search_state_payload())
        return True

    if command_type == "delete_filter_preset":
        name = str(command.get("name") or "").strip()
        if name:
            await run_in_thread(context.delete_filter_preset, name)
        await _send_json(ws, context.search_state_payload())
        return True

    return False
