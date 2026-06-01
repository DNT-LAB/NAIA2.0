from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Awaitable, Callable
from urllib.parse import quote, urljoin, urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.danbooru_client import DANBOORU_BASE_URL, fetch_danbooru_post
from core.headless_random_prompt_service import HeadlessRandomPromptService
from core.tag_filter_helpers import _is_color_exception
from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]


def _random_service(context: WebSessionContext) -> HeadlessRandomPromptService:
    service = getattr(context, "headless_random_prompt_service", None)
    if service is None:
        service = HeadlessRandomPromptService(context)
        context.headless_random_prompt_service = service
    return service


def normalize_danbooru_browser_url(value: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        return f"{DANBOORU_BASE_URL}/posts?tags=rating%3Ageneral&z=5"
    if text.isdigit():
        return f"{DANBOORU_BASE_URL}/posts/{text}"
    if text.startswith("//"):
        text = "https:" + text
    elif text.startswith("/"):
        text = urljoin(DANBOORU_BASE_URL, text)
    elif re.match(r"^(?:www\.)?danbooru\.donmai\.us(?:/|$)", text, re.IGNORECASE):
        text = "https://" + text
    elif not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text):
        text = f"{DANBOORU_BASE_URL}/posts?tags={quote(text, safe=':-_~')}"

    parsed = urlparse(text)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or hostname not in {"danbooru.donmai.us", "www.danbooru.donmai.us"}:
        raise ValueError("Danbooru URL, post ID, or tag query is required")
    return text


def _load_characteristic_tags(context: WebSessionContext) -> set[str]:
    path = Path(context.repo_root) / "data" / "characteristic_list.txt"
    try:
        return {
            line.strip().replace("_", " ")
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    except Exception:
        return set()


def _fallback_danbooru_prompt(tags: dict[str, Any]) -> str:
    general_tags = tags.get("general") if isinstance(tags, dict) and isinstance(tags.get("general"), list) else []
    return ", ".join(map(str, general_tags))


def _danbooru_prompt_preview(context: WebSessionContext, tags: dict[str, Any]) -> str:
    try:
        _random_service(context)._ensure_headless_runtime()
        service = getattr(context, "prompt_generation_service", None)
        settings = {
            "api_mode": context.get_api_mode(),
            "auto_generate": False,
            "prompt_fixed": False,
            "wildcard_standalone": False,
        }
        if service is not None and hasattr(service, "generate_instant_source_silent"):
            prompt = service.generate_instant_source_silent(tags, settings)
            if prompt:
                return str(prompt)
    except Exception as exc:
        print(f"Headless Remote: Danbooru prompt preview failed - {exc}", flush=True)
    return _fallback_danbooru_prompt(tags)


# --- GENERAL BREAKDOWN classifier (ported from future01 tabs/web_view.py:34-704) ---
# Buckets a post's (post-promotion) general tags into 12 display groups using the
# shared FilterDataManager. Display-only: never mutates the flat 5-category tags that
# feed the prompt preview / generate path. Tag format is space-form on both sides
# (_split_tag_string -> spaces; FilterDataManager data files are space-form), so no
# conversion is needed. character_features stays empty here by design (characteristic
# tags were already promoted into 'character' upstream), mirroring the desktop flow.
DANBOORU_GENERAL_BREAKDOWN_KEYS = (
    "character_features",
    "subject_count",
    "clothing_events",
    "clothes",
    "colors",
    "location_background",
    "expression",
    "pose_action",
    "objects",
    "meta_like",
    "noise",
    "other",
)
_PERSON_COUNT_RE = re.compile(
    r"^(?:[1-5](?:boy|boys|girl|girls|other|others)|6\+(?:boys|girls|others))$"
)


def _danbooru_filter_manager(context: WebSessionContext):
    """Return the shared FilterDataManager (portable-path aware), loading it once."""
    try:
        _random_service(context)._ensure_headless_runtime()
    except Exception:
        pass
    return getattr(context, "filter_data_manager", None)


def _general_tag_bucket(tag: str, fm: Any) -> str:
    if _PERSON_COUNT_RE.match(tag):
        return "subject_count"
    if tag in fm.characteristic_list:
        return "character_features"
    if tag in fm._clothing_event_set:
        return "clothing_events"
    if tag in fm.clothes_list or fm.get_garment_region(tag):
        return "clothes"
    if (
        fm.color_list
        and not _is_color_exception(tag)
        and any(color in tag for color in fm.color_list)
    ):
        return "colors"
    if tag in fm._location_set:
        return "location_background"
    if tag in fm._expression_set:
        return "expression"
    if tag in fm._pose_action_set:
        return "pose_action"
    if tag in fm._object_set:
        return "objects"
    if tag in fm._meta_set:
        return "meta_like"
    if fm._valid_tag_whitelist and tag not in fm._valid_tag_whitelist:
        return "noise"
    return "other"


def _classify_general_breakdown(
    context: WebSessionContext, general_tags: list[str]
) -> dict[str, list[str]]:
    breakdown: dict[str, list[str]] = {key: [] for key in DANBOORU_GENERAL_BREAKDOWN_KEYS}
    tags = [t for t in (general_tags or []) if isinstance(t, str) and t]
    if not tags:
        return breakdown
    fm = _danbooru_filter_manager(context)
    if fm is None:
        breakdown["other"] = list(tags)
        return breakdown
    for tag in tags:
        breakdown[_general_tag_bucket(tag, fm)].append(tag)
    return breakdown


def build_danbooru_post_payload(context: WebSessionContext, query: str) -> dict[str, Any]:
    post = fetch_danbooru_post(
        query,
        characteristic_tags=_load_characteristic_tags(context),
    )
    tags = post.get("tags", {}) if isinstance(post.get("tags"), dict) else {}
    post["prompt"] = _danbooru_prompt_preview(context, tags)
    general = tags.get("general") if isinstance(tags.get("general"), list) else []
    post["general_breakdown"] = _classify_general_breakdown(context, general)
    return post


def register_danbooru_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
) -> None:
    @app.post("/api/danbooru/post")
    async def api_danbooru_post(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        query = str(payload.get("query") or req.query_params.get("query") or "").strip()
        try:
            return await run_in_thread(build_danbooru_post_payload, session_context, query)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Danbooru lookup failed: {exc}"}, status_code=502)

    @app.post("/api/danbooru/browser/open")
    async def api_danbooru_browser_open(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        query = str(payload.get("url") or payload.get("query") or req.query_params.get("url") or "").strip()
        try:
            target_url = normalize_danbooru_browser_url(query)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return {"ok": True, "url": target_url, "runtime": "web", "open_external": True}
