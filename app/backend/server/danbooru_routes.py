from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Awaitable, Callable
from urllib.parse import quote, urljoin, urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.danbooru_client import DANBOORU_BASE_URL, fetch_danbooru_post
from core.headless_random_prompt_service import HeadlessRandomPromptService
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


def build_danbooru_post_payload(context: WebSessionContext, query: str) -> dict[str, Any]:
    post = fetch_danbooru_post(
        query,
        characteristic_tags=_load_characteristic_tags(context),
    )
    post["prompt"] = _danbooru_prompt_preview(context, post.get("tags", {}))
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
        return {"ok": True, "url": target_url, "headless": True, "open_external": True}
