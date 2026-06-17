"""Ollama 로컬 어시스턴트 라우트.

상태/진행률 조회(GET)는 모든 클라이언트에 열려 있다(원격 세션도 진행률을
렌더해야 함). 호스트 머신에 부작용을 일으키는 동작 — ``ollama serve`` 스폰,
수 GB 모델 다운로드, 취소 — 은 install-manager/data-migration과 동일하게
루프백 게이트를 건다: 원격 Remote Web 클라이언트가 호스트에서 프로세스를
띄우거나 대용량 다운로드를 시작할 수 없어야 한다.
"""

from __future__ import annotations

import re
import threading
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.backend.server.install_manager_routes import _is_local_request
from app.backend.server.preset_services import clothes_preset_service
from core.intent_action_pipeline import (
    ACTION_PROMPT_SEARCH,
    ACTION_SEMANTIC_TAG_SEARCH,
    GenerationInfoContext,
    IntentActionPipeline,
    IntentDecision,
    IntentFrame,
    INTENT_CLOTHES_COMBINATION,
    INTENT_PROMPT_RECOMMENDATION,
    INTENT_TAG_DISCOVERY,
    ROUTE_BLOCKED,
    ROUTE_NAIA_TOOL,
    ROUTE_OUT_OF_SCOPE,
    decide_intent_route,
    extract_intent_frame,
    structured_output,
)
from core.ollama_assistant_service import OllamaAssistantService
from core.ollama_chat_pipeline import OllamaChatPipeline
from core.semantic_tag_discovery import ground_scene_segments, normalize_category_axis
from core.web_session_context import WebSessionContext

AsyncRunner = Callable[..., Awaitable[Any]]

# get_assist_service 첫 생성 직렬화 — Auto Boost 오버랩에서 prefetch 생산자(백그라운드)와
# 메인 경로가 동시에 첫 호출하면 서비스 인스턴스가 중복 생성될 수 있다. 상주 상태가
# 인스턴스에 살기 때문에, 중복되면 토글 warm/unload와 boost의 keep_alive 판정이 서로
# 다른 인스턴스를 보게 된다(캐시가 한쪽으로 정착하기 전까지). 단일 인스턴스 보장.
_ASSIST_SVC_LOCK = threading.Lock()
# LLM 검색 인덱스 첫 빌드 직렬화(빌드 ~1s, 중복 빌드 낭비 방지).
_LLM_INDEX_LOCK = threading.Lock()

_CHAT_GENERAL_HINTS = (
    "점심", "저녁", "아침", "메뉴", "음식", "레시피", "맛집", "날씨", "뉴스",
    "시간", "운세", "여행", "영화", "노래", "운동", "joke", "weather", "news",
    "lunch", "dinner", "breakfast", "recipe",
)
_CHAT_TOOL_OR_CONTEXT_HINTS = (
    "naia", "프롬프트", "prompt", "태그", "tag", "검색", "찾아", "여기", "현재",
    "이 프롬프트", "이 태그", "이거", "그거", "결과", "생성물", "이 이미지",
    "변형", "관련", "더", "뜻", "의상", "옷", "포즈", "표정", "배경", "구도",
)
_CHAT_STRONG_CONTEXT_REFS = (
    "여기", "이 프롬프트", "이 태그", "이거", "이 이미지", "이 그림", "현재", "지금",
)


def _loopback_only_response() -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": "Ollama 제어(서버 시작/모델 다운로드)는 NAIA가 실행 중인 PC에서만 가능합니다."},
        status_code=403,
    )


def _korean_to_english(text: str) -> "str | None":
    """NAIA 내장 번역(Google Translate). 어시스트 사전 번역용."""
    try:
        from utils.translator import korean_to_english

        return korean_to_english(text)
    except Exception:
        return None


_HANGUL_RE = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")


def _llm_index_source(context: WebSessionContext) -> "Any":
    """무효화 identity: 공유 원천(kr_tags_raw)이 있으면 그 객체, 없으면 None."""
    return getattr(context, "kr_tags_raw", None) or None


def ensure_llm_search_index(context: WebSessionContext) -> "Any":
    """LLM 어시스트 전용 검색 인덱스를 context에 캐시·반환.

    autocomplete와 동일 원천(`load_kr_tag_records`)에서 빌드하되 매칭/배제 규칙이
    다르다(core/llm_search_index.py 참조). 이미 autocomplete 인덱스가 떠 있으면
    그 raw(`context.kr_tags_raw`)를 재사용해 이중 로드를 피한다. autocomplete
    경로가 소유한 context 필드(kr_tags_raw/autocomplete_state)는 건드리지 않는다.

    스테일 방지(패널 B #4): 데이터 마이그레이션/태그 아카이브 교체는
    `kr_tags_raw`를 리셋한다(data_migration_service / install_manager_routes의
    refresh_tag_state). 인덱스에 빌드 원천 identity(`built_from`)를 박아 두고
    현재 kr_tags_raw와 불일치하면 재빌드한다 — 신규 어휘로 자가 갱신.
    """

    def _fresh(index: "Any") -> bool:
        return index is not None and getattr(index, "built_from", None) is _llm_index_source(context)

    index = getattr(context, "llm_search_index", None)
    if _fresh(index):
        return index
    with _LLM_INDEX_LOCK:
        index = getattr(context, "llm_search_index", None)
        if _fresh(index):
            return index
        from core.llm_search_index import LLMSearchIndex

        source = _llm_index_source(context)
        raw = source
        if not raw:
            from app.backend.server.autocomplete_commands import _tag_data_roots
            from core.kr_tag_loader import load_kr_tag_records

            raw = load_kr_tag_records(context.repo_root, data_roots=_tag_data_roots(context)).raw
        index = LLMSearchIndex.from_raw_tag_records(raw, built_from=source)
        context.llm_search_index = index
        try:
            stats = index.stats()
            print(
                f"Headless Remote: LLM search index ready - {stats['records']} tags, "
                f"{stats['stems']} stems", flush=True,
            )
        except Exception:
            pass
        return index


def search_llm_tags(context: WebSessionContext, query: str, limit: int = 12) -> list[dict[str, Any]]:
    """어시스트 searcher 계약 구현: (query, limit) → [{tag, count, desc, group, cat}].

    한국어 쿼리(번역 실패/oneshot 일탈 경로 — 패널 B #8)는 한국어 키워드 색인을
    가진 구 검색에 위임해 현행 recall을 보존한다. 인덱스 빌드/검색 실패 시에도
    구 autocomplete 검색으로 폴백(어시스트 생존 우선) — 조용히 갈리지 않도록
    서버 로그에 1회 경고를 남긴다(silent [] 금지 — scene_boost validate 캐시가
    프로세스 수명이라 빈 결과는 세션 내내 오염된다).
    """
    if _HANGUL_RE.search(str(query or "")):
        from app.backend.server.autocomplete_commands import search_kr_tags

        return search_kr_tags(context, query, limit=limit)
    try:
        return ensure_llm_search_index(context).search(query, limit=limit)
    except Exception as exc:
        if not getattr(context, "_llm_search_fallback_warned", False):
            context._llm_search_fallback_warned = True
            print(
                f"Headless Remote: LLM search index unavailable, falling back to autocomplete search - {exc}",
                flush=True,
            )
        from app.backend.server.autocomplete_commands import search_kr_tags

        return search_kr_tags(context, query, limit=limit)


def _event_combo_tags(
    context: WebSessionContext, rating: str, person_id: str, query: str, top_events: int,
) -> list[tuple[str, int]]:
    """Event Preset(실제 관측 조합)에서 query에 맞는 이벤트들의 공기 태그를 빈도순
    집계. 인원수(person_id)+등급(rating) 파티션에 한정 — 어시스트의 B 하이브리드용."""
    try:
        from app.backend.server.preset_services import event_preset_service
        from core.ollama_tag_assist_service import is_generic_event_tag

        svc = event_preset_service(context)
        if svc.status().get("dataAvailability", {}).get("main") != "ready":
            return []
        boot = svc.bootstrap(rating_id=rating, person_id=person_id, search=query)
        event_ids: list[str] = []
        for cat in boot.get("categories", []):
            for sub in cat.get("subcategories", []):
                for ev in sub.get("events", []):
                    eid = ev.get("id") or ev.get("eventTag")
                    # 이벤트 태그 자체가 범용 노이즈(looking at viewer/standing 등)면
                    # 통째로 스킵 — 단어 폴백 쿼리("looking")가 이런 이벤트에 매칭되면
                    # 조합 집계가 전역 인기 포즈(v/holding hands)로 퇴화한다(실측).
                    if eid and not is_generic_event_tag(eid):
                        event_ids.append(str(eid))
        weights: dict[str, int] = {}
        for eid in event_ids[: max(1, top_events)]:
            det = svc.observed_combos({"ratingId": rating, "personId": person_id, "eventId": eid})
            event = det.get("event") or {}
            for combo in (event.get("observedCombos") or [])[:12]:
                cnt = int(combo.get("count") or 1)
                for tag in combo.get("tags") or []:
                    t = str(tag).strip()
                    if t:
                        weights[t] = weights.get(t, 0) + cnt
        return sorted(weights.items(), key=lambda kv: kv[1], reverse=True)[:30]
    except Exception:
        return []


def _event_combo_tag_stats(
    context: WebSessionContext, rating: str, person_id: str, query: str, top_events: int,
) -> list[dict[str, Any]]:
    """Event co-occurrence rows with corroborating event support counts."""
    try:
        from app.backend.server.preset_services import event_preset_service
        from core.ollama_tag_assist_service import is_generic_event_tag

        svc = event_preset_service(context)
        if svc.status().get("dataAvailability", {}).get("main") != "ready":
            return []
        boot = svc.bootstrap(rating_id=rating, person_id=person_id, search=query)
        event_ids: list[str] = []
        for cat in boot.get("categories", []):
            for sub in cat.get("subcategories", []):
                for ev in sub.get("events", []):
                    eid = str(ev.get("id") or ev.get("eventTag") or "").strip()
                    if eid and not is_generic_event_tag(eid):
                        event_ids.append(eid)
        weights: dict[str, dict[str, int]] = {}
        for eid in event_ids[: max(1, int(top_events or 1))]:
            det = svc.observed_combos({"ratingId": rating, "personId": person_id, "eventId": eid})
            event = det.get("event") or {}
            seen_in_event: set[str] = set()
            for combo in (event.get("observedCombos") or [])[:12]:
                cnt = int(combo.get("count") or 1)
                for tag in combo.get("tags") or []:
                    text = str(tag).strip()
                    if not text:
                        continue
                    row = weights.setdefault(text, {"count": 0, "support": 0})
                    row["count"] += cnt
                    seen_in_event.add(text)
            for tag in seen_in_event:
                weights.setdefault(tag, {"count": 0, "support": 0})["support"] += 1
        ranked = sorted(weights.items(), key=lambda item: item[1]["count"], reverse=True)
        return [
            {"tag": tag, "count": data["count"], "support": data["support"]}
            for tag, data in ranked[:30]
        ]
    except Exception:
        return []


_SCENE_EVENT_STOP_TAGS = {
    "girl",
    "boy",
    "character",
    "scene",
    "composition",
    "pose",
    "hands",
    "dog",
    "looking at viewer",
    "standing",
    "sitting",
    "holding",
}
_SCENE_EVENT_STOP_PARTS = (
    "pussy",
    "futanari",
    "genital",
    "pantyshot",
    "wardrobe malfunction",
    "popped button",
    "flying button",
    "clothes lift",
    "bikini top lift",
    "bikini pull",
    "bikini in mouth",
    "clothes in mouth",
    "tearing clothes",
    "torn clothes",
    "instrument on back",
    "mouth hold",
    "undone bikini",
    "onto self",
    "zettai ryouiki",
    "uniform",
    "blood from eyes",
)


def _event_label_text(event: dict[str, Any]) -> str:
    return str(
        event.get("labelKo")
        or event.get("labelEn")
        or event.get("label")
        or event.get("tag")
        or event.get("id")
        or ""
    ).strip()


def _scene_event_query_candidates(flat_tags: list[str], segments: list[dict[str, Any]]) -> list[str]:
    axis_rank = {
        "action": 0,
        "object": 1,
        "background": 2,
        "clothing": 3,
        "expression": 4,
        "body": 5,
        "gaze": 6,
        "general": 7,
    }
    tagged: list[tuple[int, str]] = []
    for segment in segments or ():
        axis = str(segment.get("axis") or "general").strip().lower()
        rank = axis_rank.get(axis, 7)
        for row in segment.get("tags") or ():
            tag = str(row.get("tag") or "").strip().lower().replace("_", " ")
            if tag:
                tagged.append((rank, tag))
            concept = str(row.get("concept") or "").strip().lower().replace("_", " ")
            if concept and concept != tag:
                tagged.append((rank, concept))
    for tag in flat_tags or ():
        text = str(tag or "").strip().lower().replace("_", " ")
        if text:
            tagged.append((5, text))
    tagged.sort(key=lambda item: item[0])

    out: list[str] = []

    def add(value: str) -> None:
        text = " ".join(str(value or "").strip().lower().replace("_", " ").split())
        if not text or _HANGUL_RE.search(text) or text in _SCENE_EVENT_STOP_TAGS:
            return
        if text not in out:
            out.append(text)

    tag_set = {tag for _rank, tag in tagged}
    tea_context = any("tea" in item or "teapot" in item for item in tag_set)
    if tea_context:
        add("teapot")
        add("holding teapot")
        add("serving")
    if "falling" in tag_set and "holding" in tag_set:
        add("catching")
    if "warrior" in tag_set and ("holding" in tag_set or "catching" in tag_set):
        add("holding sword")
        add("sword")

    catch_context = "falling" in tag_set and "holding" in tag_set
    for _rank, tag in tagged:
        if catch_context and tag == "falling":
            continue
        if tea_context and tag == "pouring":
            continue
        if "catch" in tag:
            add("catching")
        if "sword" in tag or "blade" in tag:
            if any("catch" in item for item in tag_set):
                add("catching")
            add("holding sword")
            add("sword")
        if "tea" in tag or "teapot" in tag:
            add("teapot")
            add("holding teapot")
            add("serving")
        if tag in {"lying", "on back"} or "lying" in tag:
            add("lying")
            add("on back")
        if tag in {"bikini", "swimsuit"}:
            add("bikini")
        if tag == "beach":
            add("beach")
        add(tag)
        if len(out) >= 10:
            break
    return out[:10]


def _scene_event_labels(
    context: WebSessionContext,
    *,
    rating: str,
    person_id: str,
    query: str,
    top_events: int,
) -> list[str]:
    try:
        from app.backend.server.preset_services import event_preset_service
        from core.ollama_tag_assist_service import is_generic_event_tag

        svc = event_preset_service(context)
        boot = svc.bootstrap(rating_id=rating, person_id=person_id, search=query)
        labels: list[str] = []
        for cat in boot.get("categories", []):
            for sub in cat.get("subcategories", []):
                for ev in sub.get("events", []):
                    eid = str(ev.get("id") or ev.get("eventTag") or "").strip()
                    if not eid or is_generic_event_tag(eid):
                        continue
                    label = _event_label_text(ev)
                    if label and label not in labels:
                        labels.append(label)
                    if len(labels) >= top_events:
                        return labels
        return labels
    except Exception:
        return []


def _scene_event_enrichment(
    context: WebSessionContext,
    *,
    flat_tags: list[str],
    segments: list[dict[str, Any]],
    limit: int = 15,
) -> dict[str, Any]:
    try:
        from app.backend.server.preset_services import event_preset_service
        from core.ollama_tag_assist_service import is_generic_event_tag

        status = event_preset_service(context).status()
        if status.get("dataAvailability", {}).get("main") != "ready":
            return {"eventTags": [], "eventLabels": [], "eventQuery": {}}
        existing = {
            " ".join(str(tag or "").strip().lower().replace("_", " ").split())
            for tag in flat_tags or []
        }
        weights: dict[str, int] = {}
        labels: list[str] = []
        queries = _scene_event_query_candidates(flat_tags, segments)
        ratings = ("s", "g")
        person_id = "1girl_solo"
        for query in queries[:8]:
            for rating in ratings:
                for label in _scene_event_labels(
                    context,
                    rating=rating,
                    person_id=person_id,
                    query=query,
                    top_events=3,
                ):
                    if label not in labels:
                        labels.append(label)
                for tag, count in _event_combo_tags(context, rating, person_id, query, 4):
                    norm = " ".join(str(tag or "").strip().lower().replace("_", " ").split())
                    if (
                        not norm
                        or norm in existing
                        or norm in _SCENE_EVENT_STOP_TAGS
                        or any(part in norm for part in _SCENE_EVENT_STOP_PARTS)
                        or is_generic_event_tag(norm)
                    ):
                        continue
                    weights[norm] = weights.get(norm, 0) + int(count or 0)
        ranked = sorted(weights.items(), key=lambda item: item[1], reverse=True)
        return {
            "eventTags": [
                {"tag": tag, "count": count}
                for tag, count in ranked[: max(0, int(limit or 15))]
            ],
            "eventLabels": labels[:8],
            "eventQuery": {
                "ratings": list(ratings),
                "personId": person_id,
                "queries": queries[:8],
            },
        }
    except Exception:
        return {"eventTags": [], "eventLabels": [], "eventQuery": {}}


def get_assist_service(context: WebSessionContext) -> "Any":
    """OllamaTagAssistService를 context에 캐시·반환(라우트/생성 경로 공용 팩토리).

    base_url은 OllamaAssistantService에서, 검색기/번역기/이벤트조합은 app 레이어에서
    주입한다(core가 app을 모르도록). Auto Boost 등 라우트 밖에서도 동일 서비스를
    쓰기 위해 모듈 레벨로 노출.
    """
    from core.ollama_tag_assist_service import OllamaTagAssistService

    # double-checked locking — 락 밖 빠른 경로(이미 캐시됨) + 락 안 재확인(첫 생성 직렬화).
    existing = getattr(context, "ollama_tag_assist_service", None)
    if existing is not None:
        return existing
    with _ASSIST_SVC_LOCK:
        existing = getattr(context, "ollama_tag_assist_service", None)
        if existing is not None:
            return existing
        assistant = getattr(context, "ollama_assistant_service", None)
        if assistant is None:
            assistant = OllamaAssistantService()
            context.ollama_assistant_service = assistant
        svc = OllamaTagAssistService(
            base_url=assistant.base_url,
            default_model=assistant.default_model,
            # LLM 전용 검색(exact 레인+whole-word 부분 레인) — UI autocomplete 재사용이
            # 모든 태그 오염의 뿌리였다(OLLAMA_LLM_SEARCH_INDEX_PLAN.md). 빌드 실패 시
            # search_kr_tags 폴백은 search_llm_tags 내부에서 처리.
            searcher=lambda query, limit: search_llm_tags(context, query, limit=limit),
            event_combo_provider=lambda rating, person_id, query, top: _event_combo_tags(
                context, rating, person_id, query, top
            ),
            translator=_korean_to_english,
        )
        context.ollama_tag_assist_service = svc
        return svc


def ollama_boost_settings(context: WebSessionContext) -> dict[str, Any]:
    """PE 저장소의 ``ollama_boost_settings``를 정규화해 반환(없으면 기본값).
    nl_weight(0.75~3)·effort(concise/standard/rich)·include_prefix/postfix/e621·style options."""
    from core.prompt_engineering_settings import normalize_ollama_boost_settings
    try:
        from core.prompt_engineering_settings import get_prompt_engineering_store

        store = get_prompt_engineering_store(context)
        return normalize_ollama_boost_settings(store.collect_settings().get("ollama_boost_settings"))
    except Exception:
        return normalize_ollama_boost_settings(None)


def scene_boost_prompt(
    context: WebSessionContext,
    prompt: str,
    *,
    level: str | None = None,
    allow_scent_style: bool | None = None,
    allow_material_style: bool | None = None,
    allow_light_style: bool | None = None,
) -> dict[str, Any]:
    """Ollama Auto Boost — 주어진 프롬프트를 Scene Boost로 강화한다(best-effort).

    토글(``context.ollama_auto_boost``)이 OFF면 그대로 통과. ON이어도 Ollama가 꺼져
    있으면 scene_boost 내부 chat이 빠르게 실패(connection refused)해 원문을 돌려준다 —
    생성 루프를 절대 깨지 않는다. 반환은 scene_boost 결과 dict(없으면 패스 표시).
    level/style 옵션 미지정 시 설정값을 쓴다.
    """
    src = str(prompt or "")
    if not getattr(context, "ollama_auto_boost", False) or not src.strip():
        return {"ok": False, "skipped": True, "prompt": src}
    settings: dict[str, Any] | None = None
    if level is None:
        settings = ollama_boost_settings(context)
        level = settings.get("effort") or "rich"
    if allow_scent_style is None or allow_material_style is None or allow_light_style is None:
        if settings is None:
            settings = ollama_boost_settings(context)
        if allow_scent_style is None:
            allow_scent_style = bool(settings.get("allow_scent_style", True))
        if allow_material_style is None:
            allow_material_style = bool(settings.get("allow_material_style", True))
        if allow_light_style is None:
            allow_light_style = bool(settings.get("allow_light_style", True))
    try:
        svc = get_assist_service(context)
        if not hasattr(svc, "scene_boost"):
            return {"ok": False, "skipped": True, "prompt": src}
        result = svc.scene_boost(
            src,
            options={
                "level": str(level or "rich"),
                "allow_scent_style": bool(allow_scent_style),
                "allow_material_style": bool(allow_material_style),
                "allow_light_style": bool(allow_light_style),
            },
        )
        if isinstance(result, dict) and result.get("prompt"):
            return result
    except Exception:
        pass
    return {"ok": False, "skipped": True, "prompt": src}


def register_ollama_routes(
    app: FastAPI,
    context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
) -> None:
    def service() -> OllamaAssistantService:
        existing = getattr(context, "ollama_assistant_service", None)
        if existing is None:
            existing = OllamaAssistantService()
            context.ollama_assistant_service = existing
        return existing

    def chat_pipeline_service() -> OllamaChatPipeline:
        existing = getattr(context, "ollama_chat_pipeline", None)
        assistant = service()
        assist = get_assist_service(context)
        if isinstance(existing, OllamaChatPipeline):
            existing.assistant = assistant
            existing.assist = assist
            return existing
        existing = OllamaChatPipeline(
            assistant=assistant,
            assist_helpers=assist,
            searcher=lambda query, limit, gen_context: (
                [] if _HANGUL_RE.search(str(query or "")) else search_llm_tags(context, query, limit=limit)
            ),
            event_provider=lambda rating, person_id, query, top: _event_combo_tag_stats(
                context, rating, person_id, query, top
            ),
            translator=_korean_to_english,
        )
        context.ollama_chat_pipeline = existing
        return existing

    @app.get("/api/ollama/status")
    async def ollama_status(request: Request, fresh: int = 0):
        # 서브프로세스 프로브(+HTTP)라 스레드로 — 이벤트 루프 비차단.
        # 비-루프백 클라이언트에는 호스트 인벤토리(버전/모델 목록/엔드포인트)를
        # 제외한 요약만 준다 (install-manager의 원격 새니타이즈와 동일 결정).
        # fresh=1(다시 확인 버튼)은 CLI 프로브 캐시를 우회한다.
        # 모델은 백엔드(연결 설정)가 SSOT — 클라이언트가 보낸 model 쿼리는 받지 않는다
        # (stale 캐시/원격 클라이언트가 옛 기본 모델을 강제하지 못하게). 항상
        # self.default_model 기준으로 model_installed를 판정한다.
        local = _is_local_request(request)
        return await run_in_thread(
            lambda: service().status(include_details=local, fresh=bool(fresh) and local)
        )

    @app.post("/api/ollama/server/start")
    async def ollama_server_start(request: Request):
        if not _is_local_request(request):
            return _loopback_only_response()
        return await run_in_thread(service().start_server)

    @app.post("/api/ollama/pull")
    async def ollama_pull(request: Request):
        if not _is_local_request(request):
            return _loopback_only_response()
        model = None
        try:
            payload = await request.json()
            if isinstance(payload, dict):
                model = payload.get("model")
        except Exception:
            model = None
        return await run_in_thread(service().start_pull, model)

    @app.get("/api/ollama/pull/status")
    async def ollama_pull_status():
        return service().pull_state()

    # ── 이벤트 데이터셋 브릿지 — Manual(B 실조합 참조)용. main(조합)만 받는다. ──
    def _dataset_service():
        from app.backend.server.preset_services import event_preset_download_service
        return event_preset_download_service(context)

    @app.get("/api/ollama/dataset")
    async def ollama_dataset_state():
        return await run_in_thread(_dataset_service().snapshot)

    @app.post("/api/ollama/dataset")
    async def ollama_dataset_download(request: Request):
        if not _is_local_request(request):
            return _loopback_only_response()
        force = False
        try:
            payload = await request.json()
            if isinstance(payload, dict):
                force = bool(payload.get("force"))
        except Exception:
            force = False
        return await run_in_thread(lambda: _dataset_service().start(main_only=True, force=force))

    @app.post("/api/ollama/pull/cancel")
    async def ollama_pull_cancel(request: Request):
        if not _is_local_request(request):
            return _loopback_only_response()
        return service().cancel_pull()

    # ── 고급 연결 설정 — 셀프호스팅(cloudflared 등) Ollama 엔드포인트/모델 지정. ──
    @app.get("/api/ollama/connection")
    async def ollama_connection_get(request: Request):
        # 호스트 인벤토리(엔드포인트 주소)라 루프백 전용 — 원격 클라이언트엔 미노출.
        if not _is_local_request(request):
            return _loopback_only_response()
        from core.ollama_assistant_service import (
            DEFAULT_MODEL,
            DEFAULT_OLLAMA_BASE,
            _endpoint_is_local,
        )

        svc = service()
        return {
            "ok": True,
            "endpoint": svc.base_url,
            "model": svc.default_model,
            "is_custom": (not _endpoint_is_local(svc.base_url)),
            "default_endpoint": DEFAULT_OLLAMA_BASE,
            "default_model": DEFAULT_MODEL,
        }

    @app.post("/api/ollama/connection")
    async def ollama_connection_set(request: Request):
        # 백엔드가 임의 주소로 프록시하게 만드는 SSRF 면 — 루프백 전용으로 막는다
        # (원격 폰/터널 클라이언트가 호스트의 Ollama 타깃을 바꿀 수 없게).
        if not _is_local_request(request):
            return _loopback_only_response()
        raw_endpoint = ""
        raw_model = ""
        try:
            payload = await request.json()
            if isinstance(payload, dict):
                raw_endpoint = str(payload.get("endpoint") or "").strip()
                raw_model = str(payload.get("model") or "").strip()
        except Exception:
            pass

        def _apply() -> dict[str, Any]:
            import os as _os

            from core.ollama_assistant_service import (
                DEFAULT_MODEL,
                DEFAULT_OLLAMA_BASE,
                _endpoint_is_local,
            )
            from core.prompt_engineering_settings import (
                normalize_ollama_connection_settings,
                save_ollama_connection_settings,
            )

            norm = normalize_ollama_connection_settings(
                {"endpoint": raw_endpoint, "model": raw_model}
            )
            # 입력은 있었지만 정규화가 비웠다 = 유효하지 않은 URL → 저장 않고 거부.
            if raw_endpoint and not norm["endpoint"]:
                return {"ok": False, "error": "올바른 http(s) 엔드포인트 주소가 아닙니다."}
            save_ollama_connection_settings(norm)
            # 영속값(빈값=리셋)을 라이브 base_url/model로 환원: 빈 endpoint→env→기본.
            resolved_url = (
                norm["endpoint"]
                or _os.environ.get("NAIA_OLLAMA_URL")
                or DEFAULT_OLLAMA_BASE
            ).rstrip("/")
            resolved_model = norm["model"] or DEFAULT_MODEL
            # 양 서비스 라이브 갱신(재시작 불요).
            assistant = service()
            assistant.set_connection(base_url=resolved_url, default_model=resolved_model)
            tag_svc = getattr(context, "ollama_tag_assist_service", None)
            if tag_svc is not None:
                try:
                    tag_svc.set_endpoint(
                        base_url=resolved_url, default_model=resolved_model
                    )
                    # 호스트가 바뀌었으니 Auto Boost가 켜져 있으면 새 호스트에 재-warm.
                    tag_svc.set_resident(
                        bool(getattr(context, "ollama_auto_boost", False))
                    )
                except Exception:
                    pass
            return {
                "ok": True,
                "endpoint": resolved_url,
                "model": resolved_model,
                "is_custom": (not _endpoint_is_local(resolved_url)),
            }

        return await run_in_thread(_apply)

    def assist_service() -> "OllamaTagAssistService":
        # 공용 모듈 레벨 팩토리에 위임(Auto Boost 등 라우트 밖 경로와 동일 인스턴스 공유).
        return get_assist_service(context)

    def _chat_latest_user(messages: list[dict[str, Any]]) -> str:
        for item in reversed(messages or []):
            if not isinstance(item, dict):
                continue
            if str(item.get("role") or "user").lower() == "user":
                text = str(item.get("content") or "").strip()
                if text:
                    return text
        return ""

    def _chat_generation_context(raw: Any) -> GenerationInfoContext:
        if not isinstance(raw, dict):
            raw = {}
        metadata: dict[str, Any] = {}
        if raw.get("negative"):
            metadata["negative_prompt"] = str(raw.get("negative") or "")[:3000]
        if raw.get("resultInfo"):
            metadata["result_info"] = str(raw.get("resultInfo") or "")[:3000]
        if isinstance(raw.get("metadata"), dict):
            metadata.update(raw["metadata"])
        return GenerationInfoContext.from_value({
            "prompt": raw.get("prompt") or raw.get("current_prompt") or "",
            "tags": raw.get("tags") or raw.get("current_tags") or [],
            "metadata": metadata,
        })

    def _chat_system_prompt(gen_context: GenerationInfoContext) -> str:
        parts = [
            "You are NAIA Ollama Chat. Answer briefly and pragmatically.",
            "The user is working in an image generation tool. Use the current generation context when relevant.",
            "You do not have authoritative NAIA source or documentation access in this chat. If unsure about NAIA-specific facts, say so instead of inventing details.",
            "Do not reveal private chain-of-thought. Give useful final answers only.",
            "If the request requires NAIA tool output, the server will provide grounded tool results separately.",
        ]
        if gen_context.prompt:
            parts.append(f"Current prompt:\n{gen_context.prompt[:3000]}")
        negative = str(gen_context.metadata.get("negative_prompt") or "")
        if negative:
            parts.append(f"Current negative prompt:\n{negative[:1200]}")
        result_info = str(gen_context.metadata.get("result_info") or "")
        if result_info:
            parts.append(f"Current generation info:\n{result_info[:1800]}")
        return "\n\n".join(parts)

    def _chat_tool_searcher(query: str, limit: int, _gen_context: GenerationInfoContext) -> list[dict[str, Any]]:
        # Chat 도구 검색은 pipeline에서 영어 subject/expansion으로 정리된 뒤 들어온다.
        # Hangul/mixed query는 pipeline의 최후 fallback에서만 도달한다.
        rows = search_llm_tags(context, query, limit=limit)
        if rows or _HANGUL_RE.search(str(query or "")):
            return rows
        if not ("(" in str(query or "") and ")" in str(query or "")):
            return rows
        try:
            from app.backend.server.autocomplete_commands import search_kr_tags

            fallback_rows = search_kr_tags(context, query, limit=limit)
        except Exception:
            return rows
        query_words = set(re.findall(r"[a-z0-9]+", str(query or "").lower()))
        if not query_words:
            return fallback_rows[:limit]
        filtered: list[dict[str, Any]] = []
        for row in fallback_rows:
            tag = str(row.get("tag") or "").lower().replace("_", " ")
            tag_words = set(re.findall(r"[a-z0-9]+", tag))
            if str(query or "").strip().lower() in tag or (query_words & tag_words):
                filtered.append(row)
            if len(filtered) >= limit:
                break
        return filtered

    def _chat_chip_rows(run: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for result in run.tool_results:
            if result.ok:
                rows.extend(result.rows)
        return rows

    def _chat_has_strong_context_ref(latest_user: str, gen_context: GenerationInfoContext) -> bool:
        if not (gen_context.prompt or gen_context.tags):
            return False
        text = str(latest_user or "")
        return any(ref in text for ref in _CHAT_STRONG_CONTEXT_REFS)

    def _chat_chips_message(run: Any, latest_user: str, gen_context: GenerationInfoContext) -> str:
        if run.intent.intent == INTENT_TAG_DISCOVERY:
            return "장면 설명과 맞는 실제 태그 후보입니다."
        if _chat_has_strong_context_ref(latest_user, gen_context):
            return "현재 프롬프트에 어울리는 후보입니다."
        return "요청하신 내용에 맞는 후보입니다."

    def _skip_llm_gate_for_confident_out_of_scope(latest_user: str, decision: IntentDecision) -> bool:
        if decision.route != ROUTE_OUT_OF_SCOPE:
            return False
        lowered = str(latest_user or "").lower()
        # Obvious general-chat turns should not pay a gate call before raw chat.
        # Ambiguous context/tool references still go through the JSON extractor.
        if any(hint in lowered for hint in _CHAT_TOOL_OR_CONTEXT_HINTS):
            return False
        return any(hint in lowered for hint in _CHAT_GENERAL_HINTS)

    def _coerce_chat_gate(
        raw: dict[str, Any],
        *,
        fallback_intent: IntentFrame,
        fallback_decision: IntentDecision,
    ) -> tuple[IntentFrame, IntentDecision]:
        route = str(raw.get("route") or fallback_decision.route).strip().lower()
        if route not in {"naia_tool", "naia_readonly", "out_of_scope", "blocked"}:
            route = fallback_decision.route
        # Deterministic blocked is a hard boundary. LLM cannot downgrade it.
        if fallback_decision.route == ROUTE_BLOCKED:
            route = ROUTE_BLOCKED
        domain = str(raw.get("domain") or ("naia" if route.startswith("naia") else "general")).strip().lower()
        if route in {"naia_tool", "naia_readonly"}:
            domain = "naia"
        elif route == "blocked":
            domain = "source_code"
        elif domain not in {"naia", "general", "source_code"}:
            domain = "general"
        subject = str(raw.get("subject") or fallback_intent.subject or "").strip()[:200]
        intent_name = str(raw.get("intent") or fallback_intent.intent or "unknown").strip().lower()[:80]
        allowed_tool_intents = {INTENT_TAG_DISCOVERY, INTENT_PROMPT_RECOMMENDATION, INTENT_CLOTHES_COMBINATION}
        if intent_name in {"semantic_tag_search", "tag_search", "tag_recommendation", "find_tags"}:
            intent_name = INTENT_TAG_DISCOVERY
        elif intent_name in {"clothes_combo", "clothing_combination", "outfit_combination", "outfit_combo", "clothing_combo"}:
            intent_name = INTENT_CLOTHES_COMBINATION
        elif route == "naia_tool" and intent_name not in allowed_tool_intents:
            intent_name = (
                fallback_intent.intent
                if fallback_intent.intent in allowed_tool_intents
                else INTENT_PROMPT_RECOMMENDATION
            )
        if route == "naia_tool" and not subject:
            # Tool-worthy지만 모델이 세부 subject를 비웠으면 기존 fallback을 유지한다.
            subject = subject or fallback_intent.subject
        if route == "naia_tool" and intent_name == "unknown":
            intent_name = (
                fallback_intent.intent
                if fallback_intent.intent in allowed_tool_intents
                else INTENT_PROMPT_RECOMMENDATION
            )
        try:
            confidence = float(raw.get("confidence", fallback_decision.confidence))
        except Exception:
            confidence = fallback_decision.confidence
        confidence = max(0.0, min(1.0, confidence))
        expansion_queries = _coerce_expansion_queries(raw)
        raw_category_axis = raw.get("category_axis") or (
            "clothing" if intent_name == INTENT_CLOTHES_COMBINATION else fallback_intent.category_axis
        )
        category_axis = (
            normalize_category_axis(raw_category_axis)
            if route == "naia_tool"
            else normalize_category_axis(fallback_intent.category_axis)
        )
        relation = fallback_intent.relation
        obj = fallback_intent.object
        action = fallback_intent.action
        if intent_name == INTENT_TAG_DISCOVERY:
            relation = "semantic"
            obj = "tag"
            action = "discover"
        elif intent_name == INTENT_CLOTHES_COMBINATION:
            relation = "combination"
            obj = "clothing"
            action = "combine"
        intent = IntentFrame(
            intent=(intent_name if route == "naia_tool" else intent_name),
            subject=subject,
            relation=relation if route == "naia_tool" else "",
            object=obj if route == "naia_tool" else "",
            action=action if route == "naia_tool" else "",
            language=fallback_intent.language,
            confidence=confidence,
            expansion_queries=expansion_queries if route == "naia_tool" else (),
            category_axis=category_axis if route == "naia_tool" else normalize_category_axis(fallback_intent.category_axis),
        )
        reason_code = str(raw.get("reason_code") or "").strip()[:100]
        if not reason_code:
            tool_reason = "llm_prompt_search_allowed"
            if intent_name == INTENT_TAG_DISCOVERY:
                tool_reason = "llm_semantic_tag_search_allowed"
            elif intent_name == INTENT_CLOTHES_COMBINATION:
                tool_reason = "llm_clothes_combination_allowed"
            reason_code = {
                "naia_tool": tool_reason,
                "naia_readonly": "llm_naia_readonly_question",
                "out_of_scope": "llm_non_naia_request",
                "blocked": "source_mutation_blocked",
            }.get(route, fallback_decision.reason_code)
        next_call = "none"
        if route == "naia_tool":
            if intent_name == INTENT_TAG_DISCOVERY:
                next_call = ACTION_SEMANTIC_TAG_SEARCH
            elif intent_name == INTENT_CLOTHES_COMBINATION:
                next_call = INTENT_CLOTHES_COMBINATION
            else:
                next_call = ACTION_PROMPT_SEARCH
        elif route == "naia_readonly":
            next_call = "readonly_answer"
        decision = IntentDecision(
            route=route,
            domain=domain,
            tool_allowed=(route == "naia_tool"),
            read_only=True,
            reason_code=reason_code,
            next_call=next_call,
            confidence=confidence,
            category_axis=category_axis,
        )
        return intent, decision

    def _coerce_expansion_queries(raw: dict[str, Any]) -> tuple[str, ...]:
        value = raw.get("expansion_queries")
        if value is None:
            value = raw.get("queries")
        if not isinstance(value, list):
            return ()
        out: list[str] = []
        for item in value:
            text = " ".join(str(item or "").strip().split())[:80]
            if text and text not in out:
                out.append(text)
            if len(out) >= 6:
                break
        return tuple(out)

    def _chat_gate(
        latest_user: str,
        gen_context: GenerationInfoContext,
        messages: list[dict[str, Any]],
    ) -> tuple[IntentFrame, IntentDecision]:
        fallback_intent = extract_intent_frame(latest_user, gen_context)
        fallback_decision = decide_intent_route(fallback_intent, latest_user, gen_context)
        if fallback_decision.route == ROUTE_BLOCKED:
            return fallback_intent, fallback_decision
        if _skip_llm_gate_for_confident_out_of_scope(latest_user, fallback_decision):
            return fallback_intent, fallback_decision
        extractor = getattr(service(), "extract_intent_decision", None)
        if not callable(extractor):
            return fallback_intent, fallback_decision
        result = extractor(
            user_input=latest_user,
            context=gen_context.summary(),
            history=messages,
        )
        if not isinstance(result, dict) or not result.get("ok") or not isinstance(result.get("data"), dict):
            return fallback_intent, fallback_decision
        return _coerce_chat_gate(
            result["data"],
            fallback_intent=fallback_intent,
            fallback_decision=fallback_decision,
        )

    @app.get("/api/ollama/assist/progress")
    async def ollama_assist_progress():
        # 현재 파이프라인 단계 + 경과초(FE 폴링). 백엔드 단일 블로킹 호출이라
        # 실제 단계는 서비스 내부 상태로만 알 수 있다. 진행 중이 아니면 빈 스냅샷.
        svc = getattr(context, "ollama_tag_assist_service", None)
        if svc is None:
            return {"active": False}
        try:
            return svc.progress()
        except Exception:
            return {"active": False}

    @app.get("/api/ollama/chat/progress")
    async def ollama_chat_progress():
        try:
            return chat_pipeline_service().progress()
        except Exception:
            return {"active": False}

    @app.post("/api/ollama/assist")
    async def ollama_assist(request: Request):
        # 추론은 생성과 같은 제품 기능 — 원격 세션(폰/터널)에도 공개.
        # 무거운 LLM 호출 + 인덱스 검색이라 스레드로.
        # mode=fast → 원샷(1호출, 빠르지만 보수적), 그 외 → 파이프라인(정밀).
        text = ""
        mode = "manual"
        options: dict[str, Any] = {}
        try:
            payload = await request.json()
            if isinstance(payload, dict):
                text = str(payload.get("text") or "")
                mode = str(payload.get("mode") or "manual").lower()
                if isinstance(payload.get("options"), dict):
                    options = payload["options"]
        except Exception:
            text = ""
        # 모델은 백엔드(연결 설정)가 SSOT — 클라이언트가 보낸 model은 무시하고 항상
        # self.default_model을 쓴다(원격/stale 클라이언트의 옛 기본 모델 강제 차단).
        svc = assist_service()
        if mode == "fast":
            return await run_in_thread(lambda: svc.assist_oneshot(text, options=options))
        return await run_in_thread(lambda: svc.assist(text, options=options))

    @app.post("/api/ollama/chat")
    async def ollama_chat(request: Request):
        # Chat + Tools 오케스트레이터. 클라이언트가 보낸 system/model은 신뢰하지 않는다.
        # 매 메시지마다 서버측 IntentDecision gate를 통과한 뒤 typed response를 반환한다.
        messages: list[dict[str, Any]] = []
        gen_context = GenerationInfoContext()
        temperature = 0.35
        num_predict = 512
        try:
            payload = await request.json()
            if isinstance(payload, dict):
                raw_messages = payload.get("messages")
                if isinstance(raw_messages, list):
                    messages = [m for m in raw_messages if isinstance(m, dict)]
                gen_context = _chat_generation_context(payload.get("context"))
                try:
                    temperature = float(payload.get("temperature", temperature))
                except Exception:
                    temperature = 0.35
                try:
                    num_predict = int(payload.get("num_predict", num_predict))
                except Exception:
                    num_predict = 512
        except Exception:
            pass
        latest_user = _chat_latest_user(messages)
        if not latest_user:
            return {"ok": False, "type": "chat", "error": "메시지를 입력하세요."}

        def _orchestrate() -> dict[str, Any]:
            fallback_intent = extract_intent_frame(latest_user, gen_context)
            fallback_decision = decide_intent_route(fallback_intent, latest_user, gen_context)
            if fallback_decision.route == ROUTE_BLOCKED:
                blocked_run = IntentActionPipeline(
                    searcher=_chat_tool_searcher,
                    journal_path=None,
                    translator=_korean_to_english,
                ).run(latest_user, gen_context, intent=fallback_intent, decision=fallback_decision)
                return {
                    "ok": True,
                    "type": "blocked",
                    "message": blocked_run.final_output,
                    "anchor": latest_user,
                    "decision": blocked_run.decision.summary(),
                    "structured_output": structured_output(blocked_run),
                }
            stepwise_intent = None
            if not _skip_llm_gate_for_confident_out_of_scope(latest_user, fallback_decision):
                stepwise = chat_pipeline_service().run(
                    latest_user,
                    gen_context=gen_context,
                    history=messages,
                )
                if isinstance(stepwise, dict) and stepwise.get("handled"):
                    stepwise.setdefault("anchor", latest_user)
                    return stepwise
                stepwise_intent = stepwise.get("intent") if isinstance(stepwise, dict) else None
            intent, decision = _chat_gate(latest_user, gen_context, messages)
            pipeline = IntentActionPipeline(
                searcher=_chat_tool_searcher,
                journal_path=None,
                translator=_korean_to_english,
            )
            run = pipeline.run(latest_user, gen_context, intent=intent, decision=decision)
            decision = run.decision.summary()
            if run.decision.route == ROUTE_BLOCKED:
                return {
                    "ok": True,
                    "type": "blocked",
                    "message": run.final_output,
                    "anchor": latest_user,
                    "decision": decision,
                    "structured_output": structured_output(run),
                }
            if run.decision.route == ROUTE_NAIA_TOOL and run.intent.intent == INTENT_TAG_DISCOVERY:
                segments: list[dict[str, Any]] = []
                try:
                    decompose = service().decompose_scene(latest_user)
                    if isinstance(decompose, dict) and decompose.get("ok") and isinstance(decompose.get("segments"), list):
                        def _scene_searcher(query: str, limit: int, _gen_context: GenerationInfoContext) -> list[dict[str, Any]]:
                            if _HANGUL_RE.search(str(query or "")):
                                return []
                            return search_llm_tags(context, query, limit=limit)

                        segments = ground_scene_segments(
                            decompose["segments"],
                            searcher=_scene_searcher,
                            context=run.context,
                            per_concept_limit=5,
                        )
                except Exception:
                    segments = []
                if segments:
                    flat_tags: list[str] = []
                    seen_flat: set[str] = set()
                    for segment in segments:
                        for tag_row in segment.get("tags") or ():
                            tag = str(tag_row.get("tag") or "")
                            if tag and tag not in seen_flat:
                                seen_flat.add(tag)
                                flat_tags.append(tag)
                    event_enrichment = _scene_event_enrichment(
                        context,
                        flat_tags=flat_tags,
                        segments=segments,
                        limit=15,
                    )
                    return {
                        "ok": True,
                        "type": "scene",
                        "message": "장면을 실제 태그 후보로 분해했습니다.",
                        "anchor": latest_user,
                        "segments": segments,
                        "flatTags": flat_tags,
                        "eventTags": event_enrichment.get("eventTags") or [],
                        "eventLabels": event_enrichment.get("eventLabels") or [],
                        "eventQuery": event_enrichment.get("eventQuery") or {},
                        "decision": decision,
                        "structured_output": structured_output(run),
                    }
            if run.decision.route == ROUTE_NAIA_TOOL and run.intent.intent == INTENT_CLOTHES_COMBINATION:
                try:
                    combos = clothes_preset_service(context).combos_for_tag(run.intent.subject, limit=8)
                except Exception:
                    combos = []
                if combos:
                    return {
                        "ok": True,
                        "type": "combos",
                        "subject": run.intent.subject,
                        "message": f"{run.intent.subject} 의상과 어울리는 조합입니다.",
                        "combos": combos,
                        "anchor": latest_user,
                        **({"intent": stepwise_intent} if stepwise_intent else {}),
                        "decision": decision,
                        "structured_output": structured_output(run),
                    }
            if run.decision.route == ROUTE_NAIA_TOOL:
                rows = _chat_chip_rows(run)
                chips = [
                    {
                        "tag": str(row.get("tag") or ""),
                        "count": int(row.get("count") or 0),
                        "desc": str(row.get("desc") or ""),
                        "group": str(row.get("group") or ""),
                        "cat": str(row.get("cat") or ""),
                        **({
                            "score": float(row.get("score") or 0.0),
                        } if row.get("score") is not None else {}),
                        **({"reason": str(row.get("reason") or "")} if row.get("reason") else {}),
                        **({"role": str(row.get("role") or "")} if row.get("role") else {}),
                    }
                    for row in rows
                    if row.get("tag")
                ]
                if not chips:
                    return {
                        "ok": True,
                        "type": "chat",
                        "message": run.final_output,
                        "anchor": latest_user,
                        "tool_empty": True,
                        **({"intent": stepwise_intent} if stepwise_intent else {}),
                        "decision": decision,
                        "structured_output": structured_output(run),
                    }
                return {
                    "ok": True,
                    "type": "chips",
                    "message": _chat_chips_message(run, latest_user, gen_context),
                    "anchor": latest_user,
                    "chips": chips,
                    **({"intent": stepwise_intent} if stepwise_intent else {}),
                    "decision": decision,
                    "structured_output": structured_output(run),
                }
            chat_result = service().chat(
                messages,
                system=_chat_system_prompt(gen_context),
                temperature=temperature,
                num_predict=num_predict,
            )
            return {
                "ok": bool(chat_result.get("ok")),
                "type": "chat",
                "message": str(chat_result.get("message") or ""),
                "model": str(chat_result.get("model") or service().default_model),
                "error": str(chat_result.get("error") or ""),
                "anchor": latest_user,
                **({"intent": stepwise_intent} if stepwise_intent else {}),
                "decision": decision,
                "structured_output": structured_output(run),
            }

        return await run_in_thread(_orchestrate)

    # ── Auto Boost 모델 상주 — 토글 ON 시 warm-up(미리 적재+상주), OFF 시 즉시 언로드. ──
    # 토글 핸들러(PE 서비스)가 publish하면 set_resident에 위임한다. set_resident는
    # 의도만 동기로 갱신하고 실제 warm/unload HTTP(최대 120s)는 내부 데몬 스레드에서
    # '마지막 토글 승리'로 처리 — 토글 응답/이벤트 루프를 막지 않는다.
    def _on_auto_boost_changed(*args: Any) -> None:
        enabled = bool(getattr(context, "ollama_auto_boost", False))
        if args and isinstance(args[0], dict) and "enabled" in args[0]:
            enabled = bool(args[0]["enabled"])
        try:
            get_assist_service(context).set_resident(enabled)
        except Exception:
            pass

    try:
        context.subscribe("ollama_auto_boost_changed", _on_auto_boost_changed)
    except Exception:
        pass
