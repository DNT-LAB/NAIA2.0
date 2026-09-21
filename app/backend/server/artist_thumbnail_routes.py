from __future__ import annotations

import uuid
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request

from app.backend.server.install_manager_routes import _is_local_request
from fastapi.responses import JSONResponse, Response

from core.artist_affinity import default_pack as artist_affinity_pack
from core.artist_groups import ArtistGroupError, ArtistGroupStore
from core.artist_mixes import ArtistMixError, ArtistMixStore
from core.artist_search import ArtistSearchError, search as artist_search, suggest as artist_suggest
from core.artist_thumbnail_service import ArtistThumbnailService
from core.headless_generation_service import HeadlessGenerationService
from core.headless_random_prompt_service import HeadlessRandomPromptService
from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]
GenerationRunnerStarter = Callable[[WebSessionContext, set[Any]], None]


def artist_group_store(context: WebSessionContext) -> ArtistGroupStore:
    """그룹 저장소는 세션에 하나. 파일은 artist_state.json 과 **같은 폴더, 다른 파일**이다."""
    store = getattr(context, "artist_group_store", None)
    if store is None:
        store = ArtistGroupStore(artist_thumbnail_service(context).state_root)
        context.artist_group_store = store
    return store


def artist_mix_store(context: WebSessionContext) -> ArtistMixStore:
    """저장된 믹스 조합. 그룹과 **같은 폴더, 다른 파일**이다(`artist_mixes.json`)."""
    store = getattr(context, "artist_mix_store", None)
    if store is None:
        store = ArtistMixStore(artist_thumbnail_service(context).state_root)
        context.artist_mix_store = store
    return store


# 한 라우트가 op 로 갈라 받는다 - 프론트 호출부가 작아지고 검증이 한 곳에 모인다.
_GROUP_OPS = {"create", "rename", "delete", "add", "remove", "reorder", "weight"}
_MIX_OPS = {"save", "rename", "delete"}


def _apply_mix_op(store: ArtistMixStore, payload: dict, service: ArtistThumbnailService | None = None) -> dict:
    op = str(payload.get("op") or "").strip()
    if op == "save":
        blocks = payload.get("blocks")
        names = [str(b.get("artist") or "").strip() for b in (blocks if isinstance(blocks, list) else [])[:400]
                 if isinstance(b, dict) and b.get("kind", "artist") == "artist"]
        images, warnings = service.capture_artist_images(payload.get("mode", ""), names) if service else ({}, [])
        result = store.save(payload.get("name"), blocks, text=payload.get("text"), mix_id=payload.get("id"),
                            artist_images=images, fallback=payload.get("fallback", "mosaic"))
        result["warnings"].extend(warnings)
        return result
    if op == "rename":
        return store.rename(payload.get("id"), payload.get("name"))
    if op == "delete":
        return store.delete(payload.get("id"))
    raise ArtistMixError(f"unknown op: {op or '(empty)'}")


def _apply_group_op(store: ArtistGroupStore, payload: dict) -> dict:
    op = str(payload.get("op") or "").strip()
    gid = payload.get("id")
    if op == "create":
        # temp 는 "이름을 아직 안 붙였다" 는 표다 - 이름은 서버가 붙인다.
        return store.create(payload.get("name"), payload.get("items"),
                            temp=bool(payload.get("temp")))
    if op == "rename":
        return store.rename(gid, payload.get("name"))
    if op == "delete":
        return store.delete(gid)
    if op == "add":
        return store.add(gid, payload.get("items"))
    if op == "remove":
        return store.remove(gid, payload.get("artists"))
    if op == "reorder":
        return store.reorder(gid, payload.get("artists"))
    if op == "weight":
        return store.set_weight(gid, payload.get("artist"), payload.get("weight"))
    raise ArtistGroupError(f"unknown op: {op or '(empty)'}")


def artist_thumbnail_service(context: WebSessionContext) -> ArtistThumbnailService:
    service = getattr(context, "artist_thumbnail_service", None)
    if service is None:
        mode_data_root = None
        runtime_paths = getattr(context, "runtime_paths", None)
        if runtime_paths is not None:
            mode_data_root = runtime_paths.ui_assets_dir / "artist_thumb"
        service = ArtistThumbnailService(
            context.repo_root,
            mode_getter=context.get_api_mode,
            mode_data_root=mode_data_root,
            state_root=mode_data_root,
            wildcards_root=runtime_paths.wildcards_dir if runtime_paths is not None else None,
        )
        context.artist_thumbnail_service = service
    return service


def _random_service(context: WebSessionContext) -> HeadlessRandomPromptService:
    service = getattr(context, "headless_random_prompt_service", None)
    if service is None:
        service = HeadlessRandomPromptService(context)
        context.headless_random_prompt_service = service
    return service


def _generation_service(context: WebSessionContext) -> HeadlessGenerationService:
    service = getattr(context, "headless_generation_service", None)
    if service is None:
        service = HeadlessGenerationService(context)
        context.headless_generation_service = service
    return service


def register_artist_thumbnail_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
    clients: set[Any],
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    @app.get("/api/artist-thumb/state")
    async def api_artist_thumb_state(req: Request):
        try:
            payload = await run_in_thread(artist_thumbnail_service(session_context).state)
            # 호스트에서만 되는 동작(폴더 열기)의 단추를 원격에서 숨기기 위한 표시.
            if isinstance(payload, dict):
                payload = {**payload, "local": _is_local_request(req)}
            return payload
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb state failed: {exc}"}, status_code=500)

    @app.post("/api/artist-thumb/open-folder")
    async def api_artist_thumb_open_folder(req: Request):
        # 탐색기 창은 **NAIA 를 돌리는 PC** 에 뜬다 - 원격이 호스트 화면을 여는 길을 막는다
        # (이 저장소의 다른 호스트 동작과 같은 규칙).
        if not _is_local_request(req):
            return JSONResponse(
                {"ok": False, "error": "폴더 열기는 NAIA 를 실행 중인 PC 에서만 가능합니다."},
                status_code=403,
            )

        def _open_folder():
            import os
            import subprocess
            import sys

            folder = artist_thumbnail_service(session_context).mode_data_root.resolve()
            folder.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(folder))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
            return str(folder)

        try:
            opened = await run_in_thread(_open_folder)
            return {"ok": True, "path": opened}
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    @app.get("/api/artist-thumb/list")
    async def api_artist_thumb_list(
        mode: str = "",
        filter: str = "all",
        query: str = "",
        page: int = 0,
        per_page: int = 48,
        random_sample: bool = False,
    ):
        try:
            return await run_in_thread(
                artist_thumbnail_service(session_context).build_list,
                mode,
                filter,
                query,
                page,
                per_page,
                random_sample,
            )
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb list failed: {exc}"}, status_code=500)

    @app.get("/api/artist-thumb/image")
    async def api_artist_thumb_image(mode: str = "", artist: str = ""):
        try:
            image_bytes, media_type = await run_in_thread(
                artist_thumbnail_service(session_context).image_payload,
                mode,
                artist,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except (FileNotFoundError, KeyError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb image failed: {exc}"}, status_code=500)
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/api/artist-thumb/favorite-image")
    async def api_artist_thumb_favorite_image(artist: str = ""):
        try:
            image_bytes, media_type = await run_in_thread(
                artist_thumbnail_service(session_context).favorite_image_payload,
                artist,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except (FileNotFoundError, KeyError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb favorite image failed: {exc}"}, status_code=500)
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/api/artist-thumb/generated-image")
    async def api_artist_thumb_generated_image(artist: str = "", model: str = "", api: str = ""):
        """Artist 탭에서 그 아티스트로 생성한 그림. 매번 덮어쓰므로 느스러운
        캐시를 주면 새 그림을 넣어도 역 그림이 남는다 — 재검증하게 한다."""
        try:
            image_bytes, media_type = await run_in_thread(
                artist_thumbnail_service(session_context).generated_image_payload,
                artist,
                model,
                api,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except (FileNotFoundError, KeyError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb generated image failed: {exc}"}, status_code=500)
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": "no-cache"},
        )

    @app.post("/api/artist-thumb/describe")
    async def api_artist_thumb_describe(req: Request):
        """이름 목록 -> 격자 카드와 같은 모양(그림 주소 포함). 그룹 창이 쓴다."""
        try:
            payload = await req.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict) or not isinstance(payload.get("artists"), list):
            return JSONResponse({"error": "artists list required"}, status_code=400)
        try:
            return await run_in_thread(
                artist_thumbnail_service(session_context).describe_artists,
                payload.get("mode", ""),
                payload.get("artists"),
            )
        except Exception as exc:
            return JSONResponse({"error": f"Artist describe failed: {exc}"}, status_code=500)

    # ── 아티스트 매칭 검색 (사용자 지정 2026-09-19) ─────────────────────
    #  depth 를 쌓아 작가를 좁힌다. 자료는 `artist_tag_affinity.naiapack` 하나다.
    #  ⚠️ 팩이 없는 것은 **고장이 아니다** - `state: missing` 을 200 으로 돌려주고
    #     화면이 단추를 안 살린다(이벤트 맵과 같은 규칙).
    @app.get("/api/artist-affinity/state")
    async def api_artist_affinity_state():
        state = await run_in_thread(artist_affinity_pack().state)
        return state

    @app.post("/api/artist-affinity/search")
    async def api_artist_affinity_search(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            return JSONResponse({"error": "json object required"}, status_code=400)
        try:
            limit = min(max(int(payload.get("limit") or 300), 1), 1000)
        except (TypeError, ValueError):
            return JSONResponse({"error": "limit must be an integer"}, status_code=400)
        try:
            result = await run_in_thread(
                artist_search, artist_affinity_pack(), payload.get("stack"),
                order=str(payload.get("order") or "wilson"),
                limit=limit,
                offset=int(payload.get("offset") or 0))
        except ArtistSearchError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return result

    @app.get("/api/artist-affinity/suggest")
    async def api_artist_affinity_suggest(req: Request):
        """검색칸 자동완성. **색인에 있는 낱말만** 고를 수 있다(사용자 지정)."""
        prefix = str(req.query_params.get("q") or "").strip()
        axis = str(req.query_params.get("axis") or "").strip() or None
        if not prefix:
            return {"state": "ready", "rows": []}
        return await run_in_thread(artist_suggest, artist_affinity_pack(), prefix,
                                   axis=axis, limit=20)

    @app.get("/api/artist-groups")
    async def api_artist_groups_list():
        try:
            groups = await run_in_thread(artist_group_store(session_context).list)
            return {"groups": groups}
        except Exception as exc:
            # 읽을 수 없는 파일은 **덮어쓰지 않는다** - 원본은 그대로 두고 알린다.
            return JSONResponse({"error": f"Artist groups unreadable: {exc}"}, status_code=500)

    @app.post("/api/artist-groups")
    async def api_artist_groups_mutate(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            return JSONResponse({"error": "JSON object body required"}, status_code=400)
        if str(payload.get("op") or "") not in _GROUP_OPS:
            return JSONResponse({"error": f"op must be one of {sorted(_GROUP_OPS)}"}, status_code=400)
        try:
            return await run_in_thread(_apply_group_op, artist_group_store(session_context), payload)
        except ArtistGroupError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)
        except Exception as exc:
            return JSONResponse({"error": f"Artist groups update failed: {exc}"}, status_code=500)

    @app.get("/api/artist-mixes")
    async def api_artist_mixes_list():
        try:
            mixes = await run_in_thread(artist_mix_store(session_context).list)
            return {"mixes": mixes}
        except Exception as exc:
            # 읽을 수 없는 파일은 **덮어쓰지 않는다** - 원본은 그대로 두고 알린다.
            return JSONResponse({"error": f"Artist mixes unreadable: {exc}"}, status_code=500)

    @app.get("/api/artist-mixes/thumb")
    async def api_artist_mix_thumb(id: str = "", file: str = ""):
        try:
            data = await run_in_thread(artist_mix_store(session_context).thumbnail, id, file)
            return Response(data, media_type="image/webp", headers={"Cache-Control": "private, max-age=86400"})
        except ArtistMixError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)

    @app.post("/api/artist-mixes")
    async def api_artist_mixes_mutate(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            return JSONResponse({"error": "JSON object body required"}, status_code=400)
        if str(payload.get("op") or "") not in _MIX_OPS:
            return JSONResponse({"error": f"op must be one of {sorted(_MIX_OPS)}"}, status_code=400)
        try:
            return await run_in_thread(_apply_mix_op, artist_mix_store(session_context), payload,
                                       artist_thumbnail_service(session_context))
        except ArtistMixError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)
        except Exception as exc:
            return JSONResponse({"error": f"Artist mixes update failed: {exc}"}, status_code=500)

    @app.post("/api/artist-thumb/favorite")
    async def api_artist_thumb_favorite(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await run_in_thread(
                artist_thumbnail_service(session_context).set_favorite,
                payload.get("artist", ""),
                bool(payload.get("favorite", True)),
                payload.get("mode", ""),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb favorite failed: {exc}"}, status_code=500)

    @app.post("/api/artist-thumb/ban")
    async def api_artist_thumb_ban(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await run_in_thread(
                artist_thumbnail_service(session_context).set_banned,
                payload.get("artist", ""),
                bool(payload.get("banned", True)),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb ban failed: {exc}"}, status_code=500)

    @app.post("/api/artist-thumb/options")
    async def api_artist_thumb_options(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await run_in_thread(artist_thumbnail_service(session_context).save_options, payload)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb options failed: {exc}"}, status_code=500)

    @app.get("/api/artist-thumb/download")
    async def api_artist_thumb_download_state():
        try:
            return await run_in_thread(artist_thumbnail_service(session_context).download_snapshot)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb download state failed: {exc}"}, status_code=500)

    @app.post("/api/artist-thumb/download")
    async def api_artist_thumb_download(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await run_in_thread(artist_thumbnail_service(session_context).start_download, payload.get("mode", ""))
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb download failed: {exc}"}, status_code=500)

    @app.post("/api/artist-thumb/download/cancel")
    async def api_artist_thumb_download_cancel():
        try:
            return await run_in_thread(artist_thumbnail_service(session_context).cancel_download)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb download cancel failed: {exc}"}, status_code=500)

    @app.post("/api/artist-thumb/random-prompt")
    async def api_artist_thumb_random_prompt(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        artist_prompt = str(payload.get("artist_prompt") or "").strip()
        # 앵커 그룹이 오면 선행 아티스트는 비어 있을 수 있다(전부 앵커 안에 들어간 경우).
        raw_groups = payload.get("anchor_groups")
        if raw_groups is not None and not isinstance(raw_groups, dict):
            return JSONResponse({"error": "anchor_groups must be an object"}, status_code=400)
        if not artist_prompt and not raw_groups:
            return JSONResponse(
                {"error": "artist_prompt or anchor_groups is required"}, status_code=400)
        try:
            from core.prompt_engineering_settings import get_prompt_engineering_store

            module_settings = get_prompt_engineering_store(session_context).collect_settings(
                session_context.get_api_mode()
            )
            peng_override = await run_in_thread(
                artist_thumbnail_service(session_context).random_prompt_override,
                artist_prompt,
                module_settings,
                raw_groups,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb random prompt setup failed: {exc}"}, status_code=500)

        request_id = str(uuid.uuid4())
        previous_override = getattr(session_context, "session_p_eng_override", None)
        session_context.session_p_eng_override = peng_override
        try:
            result = await run_in_thread(
                _random_service(session_context).generate,
                active_ratings=session_context.get_active_ratings(),
                overrides={"auto_generate": False},
                random_request_id=request_id,
            )
        finally:
            if getattr(session_context, "session_p_eng_override", None) is peng_override:
                session_context.session_p_eng_override = previous_override
        if not result.success:
            return JSONResponse(result.websocket_payload(), status_code=500)
        return {
            "request_id": request_id,
            "prompt": result.prompt,
            "negative_prompt": session_context.negative_prompt_text,
            "remaining": result.remaining,
            "source": "artist_thumb_random",
            "detected_resolution": result.detected_resolution,
        }

    @app.post("/api/artist-thumb/generate")
    async def api_artist_thumb_generate(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            overrides = await run_in_thread(
                artist_thumbnail_service(session_context).generation_overrides,
                payload,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        dispatch = await run_in_thread(
            _generation_service(session_context).enqueue_remote_request,
            {
                "type": "generate",
                "api_mode": overrides.get("api_mode") or session_context.get_api_mode(),
                "overrides": overrides,
            },
        )
        if not dispatch.ok:
            return JSONResponse(dispatch.websocket_payload(), status_code=409)
        if session_context.headless_generation_execute_enabled:
            start_generation_runner(session_context, clients)
        return {"ok": True, **dispatch.websocket_payload()}
