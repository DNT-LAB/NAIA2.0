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
from core.ollama_assistant_service import OllamaAssistantService
from core.web_session_context import WebSessionContext

AsyncRunner = Callable[..., Awaitable[Any]]

# get_assist_service 첫 생성 직렬화 — Auto Boost 오버랩에서 prefetch 생산자(백그라운드)와
# 메인 경로가 동시에 첫 호출하면 서비스 인스턴스가 중복 생성될 수 있다. 상주 상태가
# 인스턴스에 살기 때문에, 중복되면 토글 warm/unload와 boost의 keep_alive 판정이 서로
# 다른 인스턴스를 보게 된다(캐시가 한쪽으로 정착하기 전까지). 단일 인스턴스 보장.
_ASSIST_SVC_LOCK = threading.Lock()
# LLM 검색 인덱스 첫 빌드 직렬화(빌드 ~1s, 중복 빌드 낭비 방지).
_LLM_INDEX_LOCK = threading.Lock()


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


def get_assist_service(context: WebSessionContext) -> "Any":
    """OllamaTagAssistService를 context에 캐시·반환(라우트/생성 경로 공용 팩토리).

    base_url은 OllamaAssistantService에서, 검색기/번역기/이벤트조합은 app 레이어에서
    주입한다(core가 app을 모르도록). Auto Boost 등 라우트 밖에서도 동일 서비스를
    쓰기 위해 모듈 레벨로 노출.
    """
    from core.ollama_assistant_service import DEFAULT_MODEL
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
            default_model=DEFAULT_MODEL,
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
    nl_weight(0.75~3)·effort(concise/standard/rich)·scene_brief·include_prefix/postfix/e621."""
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
    scene_brief: bool | None = None,
) -> dict[str, Any]:
    """Ollama Auto Boost — 주어진 프롬프트를 Scene Boost로 강화한다(best-effort).

    토글(``context.ollama_auto_boost``)이 OFF면 그대로 통과. ON이어도 Ollama가 꺼져
    있으면 scene_boost 내부 chat이 빠르게 실패(connection refused)해 원문을 돌려준다 —
    생성 루프를 절대 깨지 않는다. 반환은 scene_boost 결과 dict(없으면 패스 표시).
    level/scene_brief 미지정 시 PE 저장 설정을 쓴다.
    """
    src = str(prompt or "")
    if not getattr(context, "ollama_auto_boost", False) or not src.strip():
        return {"ok": False, "skipped": True, "prompt": src}
    settings: dict[str, Any] | None = None
    if level is None:
        settings = ollama_boost_settings(context)
        level = settings.get("effort") or "rich"
    if scene_brief is None:
        if settings is None:
            settings = ollama_boost_settings(context)
        scene_brief = bool(settings.get("scene_brief"))
    try:
        svc = get_assist_service(context)
        if not hasattr(svc, "scene_boost"):
            return {"ok": False, "skipped": True, "prompt": src}
        result = svc.scene_boost(
            src,
            options={"level": str(level or "rich"), "scene_brief": bool(scene_brief)},
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

    @app.get("/api/ollama/status")
    async def ollama_status(request: Request, model: str | None = None, fresh: int = 0):
        # 서브프로세스 프로브(+HTTP)라 스레드로 — 이벤트 루프 비차단.
        # 비-루프백 클라이언트에는 호스트 인벤토리(버전/모델 목록/엔드포인트)를
        # 제외한 요약만 준다 (install-manager의 원격 새니타이즈와 동일 결정).
        # fresh=1(다시 확인 버튼)은 CLI 프로브 캐시를 우회한다.
        local = _is_local_request(request)
        return await run_in_thread(
            lambda: service().status(model, include_details=local, fresh=bool(fresh) and local)
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
        return await run_in_thread(lambda: _dataset_service().start(main_only=True))

    @app.post("/api/ollama/pull/cancel")
    async def ollama_pull_cancel(request: Request):
        if not _is_local_request(request):
            return _loopback_only_response()
        return service().cancel_pull()

    def assist_service() -> "OllamaTagAssistService":
        # 공용 모듈 레벨 팩토리에 위임(Auto Boost 등 라우트 밖 경로와 동일 인스턴스 공유).
        return get_assist_service(context)

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

    @app.post("/api/ollama/assist")
    async def ollama_assist(request: Request):
        # 추론은 생성과 같은 제품 기능 — 원격 세션(폰/터널)에도 공개.
        # 무거운 LLM 호출 + 인덱스 검색이라 스레드로.
        # mode=fast → 원샷(1호출, 빠르지만 보수적), 그 외 → 파이프라인(정밀).
        text = ""
        model = None
        mode = "manual"
        options: dict[str, Any] = {}
        try:
            payload = await request.json()
            if isinstance(payload, dict):
                text = str(payload.get("text") or "")
                model = payload.get("model")
                mode = str(payload.get("mode") or "manual").lower()
                if isinstance(payload.get("options"), dict):
                    options = payload["options"]
        except Exception:
            text = ""
        svc = assist_service()
        if mode == "fast":
            return await run_in_thread(lambda: svc.assist_oneshot(text, model=model, options=options))
        return await run_in_thread(lambda: svc.assist(text, model=model, options=options))

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
