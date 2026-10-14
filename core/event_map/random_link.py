"""Session-owned Event Map source for ordinary Random and Auto Gen."""
from __future__ import annotations

import threading

from core.event_map.service import EventMapService, default_roots

_LOCK = threading.Lock()


def ensure_event_map_service(context):
    with _LOCK:
        service = getattr(context, "event_map_service", None)
        if service is None:
            service = EventMapService(default_roots(context))
            context.event_map_service = service
        if service.permanent_source is None:
            # 영구 제외 = Search 의 붉은 줄(search_filter_state.exclude_permanent) - 같은 글을 읽는다.
            service.permanent_source = lambda: str(context.normalize_search_filter_state(
                getattr(context, "search_filter_state", None)).get("exclude_permanent") or "")
        return service


def staging_store(context):
    """스테이징(동결한 조합의 랜덤 풀) - `save/event_map/staging.json`."""
    from core.event_map.staging import EventMapStaging
    return EventMapStaging(context._save_path("event_map", "staging.json"))


def link_state(context):
    return dict(getattr(context, "event_map_random_link", None) or {
        "enabled": False, "revision": 0,
    })


def result_is_current(context, result):
    revision = getattr(result, "event_map_revision", None)
    return revision is None or revision == link_state(context)["revision"]


def reject_stale_result(context, result):
    if not result_is_current(context, result):
        result.success = False
        result.error = "EV Random: 선택 조건이 변경되어 취소했습니다."
