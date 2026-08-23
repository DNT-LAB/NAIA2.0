from __future__ import annotations

import io
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from core.character_viewer_service import CharacterViewerService
from core.headless_generation_service import HeadlessGenerationService
from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]
GenerationRunnerStarter = Callable[[WebSessionContext, set[Any]], None]


def character_viewer_service(context: WebSessionContext) -> CharacterViewerService:
    service = getattr(context, "character_viewer_service", None)
    if service is None:
        paths = context.runtime_paths
        save_root = paths.save_dir if paths is not None else None
        # 썸네일만 사용자 데이터 루트로 뺀다. `data_root` 는 넘기지 않는다 —
        # 번들 데이터(copyright_groups / character_analysis)가 리소스 트리에 있어야 해서
        # 통째로 바꾸면 탭이 죽는다(CharacterViewerService.__init__ 주석 참조).
        # 포터블: <install>/user-data/data/character_thumbnails  (업데이트 때 보존되는 유일한 곳)
        # 소스   : %APPDATA%/NAIA/data/character_thumbnails
        thumbnail_root = (paths.data_dir / "character_thumbnails") if paths is not None else None
        service = CharacterViewerService(context.repo_root, save_root=save_root,
                                         thumbnail_root=thumbnail_root)
        context.character_viewer_service = service
    return service


def _generation_service(context: WebSessionContext) -> HeadlessGenerationService:
    service = getattr(context, "headless_generation_service", None)
    if service is None:
        service = HeadlessGenerationService(context)
        context.headless_generation_service = service
    return service


def _image_media_type(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def character_viewer_thumbnail_payload(
    context: WebSessionContext,
    group: str,
    character: str,
    variant: str = "",
    size: str = "",
) -> tuple[bytes, str, str]:
    """``(bytes, media_type, source_kind)`` — kind 는 ``"user"`` / ``"fallback"``.

    kind 를 같이 돌려주는 이유는 **캐시 정책이 출처마다 달라야** 하기 때문이다.
    사용자 썸네일은 덮어써지는 가변물이고 남의 눈에 띄면 안 되는 개인 이미지지만,
    번들 폴백은 릴리즈에 딸려오는 불변물이라 길게 캐시해도 된다.
    """
    service = character_viewer_service(context)
    group = str(group or "")
    character = str(character or "")
    variant = str(variant or "")
    try:
        path = service.thumbnail_path(group, character, variant)
    except FileNotFoundError:
        # **1순위는 사용자가 만든 썸네일, 2순위가 번들 미리보기 팩이다**(사용자 지정).
        # 여기까지 왔다는 것은 1순위가 없다는 뜻이라 폴백을 준다. 폴백은 이미 256px webp 라
        # 다시 줄이지 않는다 — grid 요청(384px)보다 작지만 목록 칸이 80px 이라 충분하다.
        raw = service.preview_thumb(group, character, variant)
        if raw is None:
            raise
        return raw, "image/webp", "fallback"
    size_key = str(size or "").strip().lower()
    if size_key == "grid":
        cache = getattr(context, "character_viewer_grid_thumb_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            context.character_viewer_grid_thumb_cache = cache
        stat = path.stat()
        cache_key = (str(path), stat.st_mtime_ns, stat.st_size, size_key)
        cached = cache.get(cache_key)
        if cached is not None:
            # 캐시는 (bytes, media_type) 만 담는다 — 여기까지 온 것은 사용자 파일 경로다.
            return cached[0], cached[1], "user"
        from PIL import Image

        with Image.open(path) as image:
            image.thumbnail((384, 384), Image.Resampling.BILINEAR)
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, "WEBP", quality=72, method=0)
        payload = (buffer.getvalue(), "image/webp")
        if len(cache) > 256:
            cache.clear()
        cache[cache_key] = payload
        return payload[0], payload[1], "user"

    raw = path.read_bytes()
    return raw, _image_media_type(raw), "user"


def register_character_viewer_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
    clients: set[Any],
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    @app.get("/api/character-viewer/state")
    async def api_character_viewer_state():
        try:
            state = await run_in_thread(character_viewer_service(session_context).state)
            state["generation_delay_ms"] = 500
            return state
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer state failed: {exc}"}, status_code=500)

    @app.get("/api/character-viewer/groups")
    async def api_character_viewer_groups(query: str = ""):
        try:
            return await run_in_thread(character_viewer_service(session_context).build_groups, query)
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer groups failed: {exc}"}, status_code=500)

    @app.get("/api/character-viewer/list")
    async def api_character_viewer_list(
        group: str = "",
        query: str = "",
        page: int = 0,
        per_page: int = 48,
        thumb_first: bool = True,
        include_all: bool = False,
    ):
        try:
            group_key = str(group or CharacterViewerService.GROUP_ALL)
            return await run_in_thread(
                character_viewer_service(session_context).build_list,
                group_key,
                query,
                page,
                per_page,
                thumb_first,
                include_all,
            )
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer list failed: {exc}"}, status_code=500)

    @app.post("/api/character-viewer/detail")
    async def api_character_viewer_detail(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await run_in_thread(
                character_viewer_service(session_context).build_detail,
                str(payload.get("group") or ""),
                str(payload.get("character") or ""),
                str(payload.get("variant") or ""),
                payload.get("options") if isinstance(payload.get("options"), dict) else {},
                session_context.get_api_mode(),
            )
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer detail failed: {exc}"}, status_code=500)

    @app.post("/api/character-viewer/prompt")
    async def api_character_viewer_prompt(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await run_in_thread(
                character_viewer_service(session_context).build_prompt,
                str(payload.get("group") or ""),
                str(payload.get("character") or ""),
                str(payload.get("variant") or ""),
                payload.get("options") if isinstance(payload.get("options"), dict) else payload,
                session_context.get_api_mode(),
            )
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer prompt failed: {exc}"}, status_code=500)

    @app.post("/api/character-viewer/options")
    async def api_character_viewer_options(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await run_in_thread(character_viewer_service(session_context).save_options, payload)
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer options failed: {exc}"}, status_code=500)

    @app.get("/api/character-preset")
    async def api_character_preset(group: str = "", character: str = ""):
        # Interactive 캐릭터 프리셋 팝업이 여는 **단 한 번의 요청**이다.
        # 슬롯 배정표(data/character_presets.json)와 태그 사전 카드에 필요한
        # 설명/분류/빈도(tag_lookup_info)를 여기서 합쳐 준다 — 팝업 하나에 왕복을
        # 두 번 하지 않기 위해서다. 둘 다 순수 조회라 상태를 바꾸지 않는다.
        def _payload() -> dict[str, Any]:
            service = character_viewer_service(session_context)
            data = service.character_preset(group, character)
            # 순환 import 를 피하려고 함수 안에서 가져온다(같은 패키지의 다른 라우트 모듈).
            from app.backend.server.prompt_tools_routes import tag_lookup_info

            info: dict[str, Any] = {}
            try:
                looked = tag_lookup_info(session_context, data["name"])
            except Exception:
                looked = {}
            if isinstance(looked, dict) and looked.get("tag"):
                details = looked.get("character_details")
                info = {
                    "tag": looked.get("tag", ""),
                    "count": looked.get("count", 0),
                    "desc": looked.get("desc", ""),
                    "group": " > ".join(
                        part for part in (looked.get("group"), looked.get("subgroup")) if part
                    ),
                    "cat": looked.get("cat", ""),
                    "details": details if isinstance(details, dict) else {},
                }
            data["info"] = info
            return data

        try:
            return await run_in_thread(_payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except FileNotFoundError as exc:
            # 사전이 안 깔린 배포. 팝업이 이유를 그대로 보여줄 수 있게 문구를 살린다.
            return JSONResponse({"error": str(exc)}, status_code=503)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Character preset failed: {exc}"}, status_code=500)

    @app.get("/api/character-viewer/thumbnail")
    async def api_character_viewer_thumbnail(
        group: str = "", character: str = "", variant: str = "", size: str = "", v: str = ""
    ):
        # `v` 는 캐시 버스트용 판(revision)이라 서버가 읽지 않는다. `_thumb_url` 이
        # 파일 mtime/크기로 만들어 붙이므로 **내용이 바뀌면 URL 이 바뀐다**.
        # 선례: `/api/prompt-engineering/preset-thumbnail` 이 같은 방식을 쓴다.
        try:
            image_bytes, media_type, source_kind = await run_in_thread(
                character_viewer_thumbnail_payload,
                session_context,
                group,
                character,
                variant,
                size,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except (FileNotFoundError, KeyError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer thumbnail failed: {exc}"}, status_code=500)
        # 사용자 썸네일은 개인 이미지이자 가변물이라 `private`. 번들 폴백은 릴리즈에
        # 딸려오는 불변물이라 길게 캐시한다. **헤더만으로는 부족하다** — URL 이 그대로면
        # 신선한 캐시가 서버에 닿지도 않아 새 헤더를 받을 기회조차 없다. 위의 `v=` 와
        # 짝이어야 뜻이 산다.
        cache_control = (
            "private, max-age=3600" if source_kind == "user" else "public, max-age=86400"
        )
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": cache_control},
        )

    @app.post("/api/character-viewer/thumbnail/delete")
    async def api_character_viewer_thumbnail_delete(req: Request):
        # 확인 없이 즉시 삭제(사용자 지시). 파일 + index.json 항목을 함께 지운다.
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            result = await run_in_thread(
                character_viewer_service(session_context).delete_thumbnail,
                str(payload.get("group") or ""),
                str(payload.get("character") or ""),
                str(payload.get("variant") or ""),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse(
                {"error": f"Character Viewer thumbnail delete failed: {exc}"}, status_code=500
            )
        return {"ok": True, **result}

    @app.post("/api/character-viewer/generate")
    async def api_character_viewer_generate(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            overrides = await run_in_thread(
                character_viewer_service(session_context).build_generation_overrides,
                payload,
                session_context.get_api_mode(),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        dispatch = await run_in_thread(
            _generation_service(session_context).enqueue_remote_request,
            {"type": "generate", "overrides": overrides},
        )
        if not dispatch.ok:
            return JSONResponse(dispatch.websocket_payload(), status_code=409)
        if session_context.headless_generation_execute_enabled:
            start_generation_runner(session_context, clients)
        return {"ok": True, **dispatch.websocket_payload()}
