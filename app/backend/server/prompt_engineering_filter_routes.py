"""Prompt Engineering - 카테고리 전처리 필터 사전 조회 라우트.

Setting & Preview 편집기가 "이 카테고리 필터가 실제로 어떤 태그를 갖고 있는지"
탐색하고 검색해서 클릭 한 번으로 제외할 수 있도록, 각 전처리 카테고리의 사전
목록(filter_data_manager)을 페이지네이션/검색해서 돌려준다.

오버라이드 저장/영속화 자체는 기존 WS set_module_param(category_filters) 경로가
담당한다 - 이 라우트는 읽기 전용 조회다.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from core.headless_random_prompt_service import ensure_filter_data_manager
from core.prompt_engineering_settings import CATEGORY_FILTER_OPTION_KEYS
from core.tag_filter_helpers import compile_hide_pattern
from core.web_session_context import WebSessionContext


def _pattern_normalize(value: Any) -> str:
    # lower만(strip 금지) — _x_/_x/x_ 의 경계 공백을 needle 안에 유지해 __x__와 구분.
    return str(value or "").lower()


AsyncRunner = Callable[..., Awaitable[Any]]

# 카테고리 option_key -> filter_data_manager 사전 속성. remove_noise_tags 는 빈도
# 기반이라 사전이 없어 여기서 제외한다(unsupported 로 응답).
CATEGORY_SOURCE_ATTR: dict[str, str] = {
    "remove_character_features": "characteristic_list",
    "remove_clothes": "clothes_list",
    "remove_clothing_event": "_clothing_event_set",
    "remove_color": "color_list",
    "remove_location_and_background_color": "_location_set",
    "remove_expression": "_expression_set",
    "remove_pose_action": "_pose_action_set",
    "remove_meta_tags": "_meta_set",
    "remove_object_tags": "_object_set",
}

DEFAULT_LIMIT = 200
MAX_LIMIT = 500


def _filter_manager(context: Any):
    """공유 FilterDataManager 반환 — 필요 시 사전 로더만 좁게 보장한다.

    filter_data_manager 는 워밍업/첫 생성 시점에 lazy 생성되므로, 서버 기동 직후
    이 API 가 먼저 맞으면 None 이다. 읽기 전용 사전 조회가 와일드카드 매니저/
    파이프라인 훅까지 세우지 않도록 전체 _ensure_headless_runtime() 대신 전용
    ensure_filter_data_manager() 만 호출한다(Codex 리뷰 반영). run_in_thread
    안에서 호출되므로 이벤트 루프 비차단."""
    return ensure_filter_data_manager(context)


def _sorted_category_tags(context: Any, category: str):
    """카테고리의 정렬된 사전 태그 리스트(캐시). filter_data_manager 부재면 None.

    11k 리스트를 매 요청 재정렬하지 않도록 context._pp_category_dict_cache 에
    카테고리별 1회 캐시한다.
    """
    cache = getattr(context, "_pp_category_dict_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        setattr(context, "_pp_category_dict_cache", cache)
    if category in cache:
        return cache[category]
    fm = _filter_manager(context)
    if fm is None:
        return None
    attr = CATEGORY_SOURCE_ATTR.get(category)
    raw = getattr(fm, attr, None) or []
    tags = sorted({str(t) for t in raw if str(t).strip()}, key=lambda s: s.lower())
    cache[category] = tags
    return tags


def classify_tag_payload(context: Any, tag: str) -> tuple[dict[str, Any], int]:
    """우클릭 '자동 숨김 (랜덤 프롬프트 - X)' 항목의 이름과 활성 여부.

    known=True 면 그 태그가 개별 카테고리 그룹에 속한다는 뜻이고, label 이 그 이름이다.
    어느 그룹에도 없으면 랜덤 프롬프트로 나오지 않으므로 화면이 그 항목을 막는다.

    ⚠️ **Auto-Hide 항목은 여기를 보지 않는다**(사양 변경 2026-08-31). Tag Index 수록
       여부로 막았더니 실재하지만 미수록인 태그를 숨길 방법이 없었다.
    """
    text = str(tag or "").strip()
    if not text:
        return {"tag": "", "known": False, "category": "", "label": ""}, 200
    service = context._prompt_engineering_service()
    option_key, label = service._classify_hidden_tag(text)
    return {
        "tag": text,
        "known": bool(option_key),
        "category": option_key,
        "label": label,
    }, 200

def category_tags_payload(
    context: Any,
    category: str,
    q: str = "",
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
) -> tuple[dict[str, Any], int]:
    """(payload, status_code) 반환. 순수 함수라 테스트에서 직접 호출 가능."""
    category = str(category or "").strip()
    if category not in CATEGORY_FILTER_OPTION_KEYS:
        return {"error": f"Unknown category: {category}", "category": category}, 400
    # 빈도 기반 노이즈 라운드는 사전이 없다.
    if category == "remove_noise_tags":
        return {"category": category, "supported": False, "reason": "frequency-based"}, 200
    tags = _sorted_category_tags(context, category)
    if tags is None:
        return {"category": category, "supported": False, "reason": "not_loaded"}, 200

    try:
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    limit = max(1, min(MAX_LIMIT, limit))

    # q 가 Auto-Hide 묶음 문법(__x__/_x_/_x/x_)이면 substring 대신 패턴 매치로 필터.
    # plain q 는 기존 substring 유지.
    q_text = str(q or "").strip()
    is_pattern = False
    if q_text:
        pattern_pred = compile_hide_pattern(q_text, normalize=_pattern_normalize)
        if pattern_pred is not None:
            filtered = [t for t in tags if pattern_pred(t)]
            is_pattern = True
        else:
            needle = q_text.lower()
            filtered = [t for t in tags if needle in t.lower()]
    else:
        filtered = tags
    total = len(filtered)
    page = filtered[offset:offset + limit]
    payload = {
        "category": category,
        "supported": True,
        "total": total,
        "offset": offset,
        "limit": limit,
        "tags": page,
        # 페이지 태그별 autocomplete 설명 정보(있는 것만) — 프론트 chip 호버 툴팁용.
        "info": _tag_info_map(context, page),
    }
    if is_pattern:
        payload["pattern"] = True
    return payload, 200


def _tag_info_map(context: Any, tags: list) -> dict[str, Any]:
    """autocomplete 와 같은 TagSearchIndex 에서 desc 가 있는 태그만 정보 맵으로.

    best-effort — 인덱스 확보 실패 시 빈 맵(사전 목록 자체는 정상 응답). 인덱스는
    autocomplete 가 이미 세션에 적재해 두는 것을 재사용하고, 없으면 동일 ensure
    경로로 1회 로드한다(run_in_thread 안이라 이벤트 루프 비차단)."""
    index = getattr(context, "tag_search_index", None)
    if index is None:
        try:
            from app.backend.server.autocomplete_commands import ensure_tag_search_index

            index = ensure_tag_search_index(context)
        except Exception:
            return {}
    if index is None or not hasattr(index, "entry_for"):
        return {}
    info: dict[str, Any] = {}
    for tag in tags:
        try:
            entry = index.entry_for(tag)
        except Exception:
            continue
        if entry is None:
            continue
        desc = str(getattr(entry, "desc", "") or "")
        count = int(getattr(entry, "freq", 0) or 0)
        group = str(getattr(entry, "category", "") or "")
        # desc 없는 태그도 count/group 만으로 툴팁을 띄운다 (설명 미등재 해소).
        if not desc and count <= 0 and not group:
            continue
        payload: dict[str, Any] = {}
        if desc:
            payload["desc"] = desc
        if count > 0:
            payload["count"] = count
        if group:
            payload["group"] = group
        info[str(tag)] = payload
    return info


def register_pe_filter_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
) -> None:
    @app.get("/api/prompt-engineering/classify-tag")
    async def api_pe_classify_tag(tag: str = ''):
        try:
            payload, status = await run_in_thread(classify_tag_payload, session_context, tag)
        except Exception as exc:
            return JSONResponse({"error": f"Classify failed: {exc}"}, status_code=500)
        if status != 200:
            return JSONResponse(payload, status_code=status)
        return payload

    @app.get("/api/prompt-engineering/category-tags")
    async def api_pe_category_tags(
        category: str = "",
        q: str = "",
        offset: int = 0,
        limit: int = DEFAULT_LIMIT,
    ):
        try:
            payload, status = await run_in_thread(
                category_tags_payload, session_context, category, q, offset, limit
            )
        except Exception as exc:
            return JSONResponse({"error": f"Category tags failed: {exc}"}, status_code=500)
        if status != 200:
            return JSONResponse(payload, status_code=status)
        return payload
