from __future__ import annotations

import json
import re
import uuid
from functools import partial
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request

from app.backend.server.install_manager_routes import _is_local_request
from fastapi.responses import JSONResponse, Response

from core.artist_affinity import default_pack as artist_affinity_pack
from core.artist_bench_views import ArtistBenchViewError, ArtistBenchViewStore
from core.artist_groups import LINK_SLOT, LINK_SLOT_NAME, ArtistGroupError, ArtistGroupStore
from core.artist_mixes import ArtistMixError, ArtistMixStore, MIX_SETTING_KEYS
from core.artist_insert_tracker import artist_insert_tracker, current_scope
from core.artist_search import ArtistSearchError, search as artist_search, suggest as artist_suggest
from core.artist_thumbnail_service import ArtistLoadCancelled, ArtistThumbnailService
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


def artist_bench_view_store(context: WebSessionContext) -> ArtistBenchViewStore:
    """보기(벤치 설정) 저장소. 그룹과 **같은 폴더, 다른 파일**이다(`artist_bench_views.json`)."""
    store = getattr(context, "artist_bench_view_store", None)
    if store is None:
        store = ArtistBenchViewStore(artist_thumbnail_service(context).state_root)
        context.artist_bench_view_store = store
    return store


_VIEW_OPS = {"create", "update", "rename", "delete", "select"}


def _bench_current_characters(context: WebSessionContext, mode: str) -> list[dict]:
    """지금 굴려 둔 캐릭터(스냅숏 우선 - 새로 굴리지 않는다). 못 읽으면 없는 것으로."""
    try:
        from core.character_settings import character_params_from_settings

        params = character_params_from_settings(context, mode=mode, prefer_snapshot=True) or {}
    except Exception:
        return []
    prompts = list(params.get("characters") or [])
    ucs = list(params.get("uc") or [])
    return [{"prompt": str(p or ""), "uc": str(ucs[i] if i < len(ucs) else "")}
            for i, p in enumerate(prompts) if str(p or "").strip()]


def _bench_current_spec(context: WebSessionContext) -> dict:
    """'지금 설정' 한 벌 - 새 보기의 기본값(사용자 지정 2026-09-26).

    글은 **지금 PE 프리셋의 prefix/postfix** 에서 뜬다(리모컨 머리줄의 그 글 - 벤치에 쓰는
    artist_bench_recommend · V5 영점이 여기 산다). ⚠️ 작가 태그와 믹스 앵커 표식은 걷는다 -
    남겨 두면 모든 벤치가 그 작가와의 **혼합**이 된다(`artist:sasamashin` 실측). 가중치 묶음은
    통째로만 걷는다(`strip_artists` 규칙 - 반쪽을 빼면 가중치가 다른 태그에 붙는다).
    생성 설정은 믹스 조합과 같은 여섯 키, 캐릭터는 지금 굴려 둔 스냅숏.
    """
    from core.artist_mix_preset import strip_artists

    mode = str(context.get_api_mode() or "NAI").upper()
    layers = _mix_current_layers(context)
    pre = post = preset = ""
    stripped: list[str] = []
    try:
        store = _pe_store(context)
        mode_key = store.mode()
        live = store.collect_settings(mode_key)
        preset = str(store.state(mode_key).get("current_preset") or "")
        # ⚠️ NAI 에서도 **접두 없는 이름**을 사전으로 가린다. 기본 `recommend` 프리셋이
        #    `0.4::tianliang duohe fangdongye, ixy ::` 처럼 `artist:` 없이 작가를 적어 둔다 -
        #    NAI 규칙(`artist:` 만 작가)으로만 거르면 그대로 남아 모든 벤치가 혼합이 됐다(실측).
        #    일반 태그가 우연히 작가 이름과 같으면 같이 빠질 수 있다 - 그래서 뺀 것을 알린다.
        known = _mix_known_artists(context)
        for key, slot in (("pre_prompt", "pre"), ("post_prompt", "post")):
            result = strip_artists(str(live.get(key) or ""), known=known, allow_bare=True, drop_anchors=True)
            stripped.extend(result["removed"])
            if slot == "pre":
                pre = result["text"]
            else:
                post = result["text"]
    except Exception:
        pre = post = preset = ""
        stripped = []
    width = height = 0
    try:
        width, height = (int(v) for v in str(context.remote_params.get("resolution") or "").lower().split("x"))
    except Exception:
        width, height = 832, 1216
    return {"api_mode": mode, "prefix": pre, "postfix": post, "negative": layers["negative"],
            # 캐릭터는 지금 굴려 둔 것을 **사본으로** 들고, 쓰는 것은 메인(생성 순간의 메인 캐릭터).
            # [독립] 으로 바꾸면 이 사본에서 시작한다.
            "characters": _bench_current_characters(context, mode), "character_mode": "main",
            "source_preset": preset,
            "width": width, "height": height, "settings": layers["settings"], "seed": -1,
            # 조건이 아니라 **알림**이다(저장소가 버린다) - 새 보기 화면이 '뺀 것' 으로 보여 준다.
            "stripped": stripped}


def _apply_view_op(context: WebSessionContext, payload: dict) -> dict:
    store = artist_bench_view_store(context)
    op = str(payload.get("op") or "").strip()
    if op == "create":
        spec = payload.get("spec") if isinstance(payload.get("spec"), dict) else _bench_current_spec(context)
        return store.create(payload.get("name"), spec)
    if op == "update":
        return store.update(payload.get("id"), payload.get("spec"))
    if op == "rename":
        return store.rename(payload.get("id"), payload.get("name"))
    if op == "delete":
        return store.delete(payload.get("id"))
    if op == "select":
        return store.set_group_view(payload.get("group"), payload.get("id"))
    raise ArtistBenchViewError(f"unknown op: {op or '(empty)'}")


def artist_mix_store(context: WebSessionContext) -> ArtistMixStore:
    """저장된 믹스 조합. 그룹과 **같은 폴더, 다른 파일**이다(`artist_mixes.json`)."""
    store = getattr(context, "artist_mix_store", None)
    if store is None:
        store = ArtistMixStore(artist_thumbnail_service(context).state_root)
        context.artist_mix_store = store
    return store


# 한 라우트가 op 로 갈라 받는다 - 프론트 호출부가 작아지고 검증이 한 곳에 모인다.
_GROUP_OPS = {"create", "rename", "delete", "add", "remove", "reorder", "weight"}
# 관심 작가 = 목록 맨 앞의 **고정 그룹**(사용자 지정 2026-09-26 - 일괄 벤치를 위해).
# 저장은 관심 목록 하나다(`artist_state.json`) - 그룹 파일에는 없다. 진짜 그룹의 아이디는
# 서버가 `g_...` 로 만들어 이 이름과 겹치지 않는다.
FAVORITES_GROUP_ID = "favorites"
FAVORITES_GROUP_NAME = "관심 작가"
_MIX_OPS = {"save", "rename", "delete", "set_main", "apply"}


def _mix_current_layers(context) -> dict:
    schema = context.generation_param_schema_payload()
    # 네거티브의 주인은 메인 편집칸과 같은 세션 값이다. PE 프리셋 파일은 동기화 대상이다.
    rescale_key = "rescale_cfg" if context.get_api_mode() == "COMFYUI" else "cfg_rescale"
    return {"negative": str(context.negative_prompt_text or ""), "settings": {
        "model": schema.get("model", ""), "sampler": schema.get("sampler", ""),
        "scheduler": schema.get("scheduler", ""), "steps": schema.get("steps", 28),
        "scale": schema.get("cfg_scale", 5), "cfg_rescale": schema.get(rescale_key, 0),
    }}


def _apply_mix_layers(context, record: dict, payload: dict) -> dict:
    from core.headless_remote_state_service import HeadlessRemoteStateService

    selected = payload.get("layers")
    if not isinstance(selected, dict):
        raise ArtistMixError("layers object is required")
    mode = context.get_api_mode()
    service = HeadlessRemoteStateService(context)
    schema = context.generation_param_schema_payload()
    applied, skipped, values, warnings = [], {}, {}, []
    blocked_keys = payload.get("blocked_keys", [])
    if not isinstance(blocked_keys, list) or any(not isinstance(key, str) for key in blocked_keys):
        raise ArtistMixError("blocked_keys must be a list of setting names")
    blocked = set(blocked_keys)
    session = getattr(context, "img2img_session", {}) or {}
    if session.get("active") and session.get("canvas_supported"):
        blocked.add("model")
    if mode == "COMFYUI" and str(context.remote_params.get("comfyui_workflow_type", "")).lower() in {"free", "bypass"}:
        blocked.update({"model", "sampler", "scheduler", "steps", "scale", "cfg_rescale"})
    if selected.get("settings") is True:
        # 모델부터 적용하고 옵션을 다시 읽는다. 해상도와 시드는 허용 목록에 없다.
        for key in MIX_SETTING_KEYS:
            if key not in record.get("settings", {}):
                continue
            value = record["settings"][key]
            if key in blocked:
                skipped[key] = "현재 세션에서 잠긴 설정"
                continue
            if key in {"model", "sampler", "scheduler"}:
                options = schema.get(f"options_{key}") or []
                if value not in options:
                    skipped[key] = "현재 모델/모드의 선택지에 없음"
                    continue
            if key == "steps":
                low, high = schema.get("steps_range", [1, 150])
                if not low <= value <= high:
                    skipped[key] = f"허용 범위 {low}–{high} 밖"
                    continue
            if key == "cfg_rescale" and mode == "WEBUI":
                skipped[key] = "WEBUI에서 지원하지 않는 설정"
                continue
            param_key = {"scale": "cfg_scale", "cfg_rescale": "rescale_cfg" if mode == "COMFYUI" else "cfg_rescale"}.get(key, key)
            service.set_param(param_key, value, notify=False)
            values[param_key] = context.remote_params[param_key]
            applied.append(key)
            if key == "model":
                schema = context.generation_param_schema_payload()
    if selected.get("negative") is True and "negative" in record:
        context.negative_prompt_text = record["negative"]
        values["negative"] = record["negative"]
        applied.append("negative")
    if applied:
        # ⚠️ **세션에만** 건다 - 프리셋 파일에 쓰지 않는다(2026-09-21 감사).
        #    이 앱은 평소 파라미터 변경을 프리셋에 쓰지 않는다(프리셋 전환 코드:
        #    "generated Main is not a save" - 명시적 [저장] 때만 쓴다). 조합 적용도
        #    손으로 바꾼 것과 똑같이 동작해야 한다. 한때 여기서 지금 프리셋의
        #    main_settings 를 고쳐 썼다 - 사용자가 청하지 않은 **영구 변경**이었다.
        context.save_remote_ui_state()
        schema = context.generation_param_schema_payload()
        context.publish("remote_params_changed", schema)
    return {"applied": applied, "skipped": skipped, "warnings": warnings, "params": schema,
            "negative": context.negative_prompt_text}


def _apply_mix_op(store: ArtistMixStore, payload: dict, service: ArtistThumbnailService | None = None, result_store=None, context=None) -> dict:
    op = str(payload.get("op") or "").strip()
    if op == "apply":
        return _apply_mix_layers(context, store.one(payload.get("id")), payload)
    main_image = None
    if op in {"save", "set_main"} and payload.get("main_history_id"):
        item = result_store.get_item(str(payload["main_history_id"])) if result_store else None
        if item is None:
            raise ArtistMixError("히스토리 후보가 사라졌습니다. 다시 선택하세요.", status=404)
        main_image = item.webp_bytes
    if op == "set_main":
        return store.set_main(payload.get("id"), main_image=main_image, fallback=payload.get("fallback", "mosaic"))
    if op == "save":
        blocks = payload.get("blocks")
        names = [str(b.get("artist") or "").strip() for b in (blocks if isinstance(blocks, list) else [])[:400]
                 if isinstance(b, dict) and b.get("kind", "artist") == "artist"]
        images, warnings = service.capture_artist_images(payload.get("mode", ""), names) if service else ({}, [])
        layers = _mix_current_layers(context) if context else {}
        if isinstance(payload.get("settings"), dict):
            layers["settings"] = {**layers.get("settings", {}), **payload["settings"]}
        if isinstance(payload.get("negative"), str):
            layers["negative"] = payload["negative"]
        result = store.save(payload.get("name"), blocks, text=payload.get("text"), mix_id=payload.get("id"),
                            artist_images=images, fallback=payload.get("fallback", "mosaic"), main_image=main_image, **layers)
        result["warnings"].extend(warnings)
        return result
    if op == "rename":
        return store.rename(payload.get("id"), payload.get("name"))
    if op == "delete":
        return store.delete(payload.get("id"))
    raise ArtistMixError(f"unknown op: {op or '(empty)'}")


# ── 믹스 <-> PE 프리셋 (사용자 지정 2026-09-21) ────────────────────────────
#  규칙은 `core/artist_mix_preset.py` 머리말. 여기는 세션과 저장소를 잇는 한 곳이다.

class MixPresetExists(ArtistMixError):
    """같은 이름의 프리셋이 있다 - 프론트가 [덮어쓰기] 를 물을 수 있게 따로 가른다."""

    def __init__(self, name: str):
        super().__init__(f"같은 이름의 프리셋이 있습니다: {name}", status=409)
        self.name = name


def _mix_known_artists(context, thumb_mode: str = "") -> frozenset:
    """작가 사전(+ 팩 이름). 사전 파일을 매번 실행하면 느리다 - 세션에 한 번 담아 둔다.
    SD 글에서 접두 없는 토큰이 작가인지 가르는 유일한 근거다."""
    cache = getattr(context, "_mix_known_artists_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        context._mix_known_artists_cache = cache
    key = str(thumb_mode or "")
    if key not in cache:
        weights = artist_thumbnail_service(context)._artist_weights(key)
        cache[key] = frozenset(" ".join(str(name).split()).casefold() for name in weights)
    return cache[key]


def _pe_store(context):
    from core.prompt_engineering_settings import get_prompt_engineering_store
    return get_prompt_engineering_store(context)


def _preset_source(context, name: str) -> dict:
    """프리셋의 글. **지금 쓰는 프리셋이면 살아 있는 글**을 읽는다 - 파일은 아직 저장
    안 된 편집을 모른다. 다른 프리셋은 파일이 곧 원본이다."""
    store = _pe_store(context)
    mode_key = store.mode()
    clean = str(name or "").strip()
    data = store.read_preset_data(clean, mode_key) if clean else {}
    if not data:
        raise ArtistMixError(f"프리셋을 찾을 수 없습니다: {clean}", status=404)
    is_current = clean == str(store.state(mode_key).get("current_preset") or "")
    source = store.collect_settings(mode_key) if is_current else (data.get("module_settings") or {})
    return {"store": store, "mode": mode_key, "name": clean, "data": data, "is_current": is_current,
            "pre": str(source.get("pre_prompt") or ""), "post": str(source.get("post_prompt") or "")}


def _mix_preset_list(context, thumb_mode: str = "") -> dict:
    from core.artist_mix_preset import parse_pieces
    from core.prompt_engineering_settings import preset_thumbnail_url_map

    store = _pe_store(context)
    mode_key = store.mode()
    names = store.list_preset_names(mode_key)
    thumbs = preset_thumbnail_url_map(context, names, mode_key)
    current = str(store.state(mode_key).get("current_preset") or "")
    # NAI 글의 작가는 늘 `artist:` 를 단다 - 세는 데 사전이 필요 없다. 사전은 접두 없는
    # 이름을 가려야 하는 SD 계열에서만 싣는다(첫 적재가 무겁다).
    allow_bare = mode_key != "NAI"
    known = _mix_known_artists(context, thumb_mode) if allow_bare else frozenset()
    rows = []
    for name in names:
        data = store.read_preset_data(name, mode_key)
        settings = data.get("module_settings") or {}
        count = 0
        for key in ("pre_prompt", "post_prompt"):
            for piece in parse_pieces(str(settings.get(key) or ""), known=known, allow_bare=allow_bare):
                count += sum(1 for m in (piece.get("members") or [piece]) if m.get("kind") == "artist")
        rows.append({"name": name, "thumbnail_url": thumbs.get(name, ""), "artists": count,
                     "is_current": name == current, "has_mix": isinstance(data.get("artist_mix"), dict)})
    return {"mode": mode_key, "current": current, "presets": rows}


def _mix_from_preset(context, name: str, thumb_mode: str = "") -> dict:
    """프리셋 -> 띠 모양. 지금 쓰는 프리셋이면 **글에서 작가 빼기** 안도 함께 낸다
    (띠와 글로 두 번 나가지 않게 - 적용은 프론트가 사용자에게 보여 주고 고른다)."""
    from core.artist_mix_preset import import_blocks, parse_pieces, strip_artists

    src = _preset_source(context, name)
    allow_bare = src["mode"] != "NAI"
    known = _mix_known_artists(context, thumb_mode)
    result = import_blocks(src["data"], src["pre"], src["post"], known_fn=lambda: known, allow_bare=allow_bare)
    names = {str(b.get("artist") or "") for b in result["blocks"] if b.get("kind") == "artist"}
    payload = {"name": src["name"], "mode": src["mode"], "is_current": src["is_current"], **result}
    if src["is_current"]:
        payload["strip"] = {slot: strip_artists(src[slot], known=known, allow_bare=allow_bare, drop_anchors=True)
                            for slot in ("pre", "post")}
        payload["text"] = {"pre": src["pre"], "post": src["post"]}
    else:
        # 다른 프리셋에서 가져올 때는 지금 글을 건드리지 않는다 - 겹치는 이름만 알린다.
        live = _pe_store(context).collect_settings(src["mode"])
        overlap = []
        for key in ("pre_prompt", "post_prompt"):
            for piece in parse_pieces(str(live.get(key) or ""), known=known, allow_bare=allow_bare):
                for m in (piece.get("members") or [piece]):
                    if m.get("kind") == "artist" and m["artist"] in names and m["artist"] not in overlap:
                        overlap.append(m["artist"])
        payload["overlap"] = overlap
    return payload


def _export_mix_preset(context, payload: dict, mix_store: ArtistMixStore, result_store=None) -> dict:
    """지금 띠 -> 프리셋 파일. 현재 프리셋은 **바꾸지 않는다**(사용자 결정 2026-09-21).

    ⚠️ 글은 생성 때 나가는 것과 같게 **표식을 펼쳐** 쓴다(`baked_texts`).
    ⚠️ 메인 프롬프트는 싣지 않는다 - 대개 마지막 랜덤 결과지 조합의 일부가 아니다.
       (`_apply_main_settings` 는 `prompt` 키가 없으면 메인 프롬프트를 안 건드린다.)
    ⚠️ 그림은 JSON 을 쓴 **뒤에** 쓴다 - 파일이 안 써졌는데 그림만 남으면 안 된다.
    """
    from core.artist_mix_preset import baked_texts, copy_record

    store = _pe_store(context)
    mode_key = store.mode()
    name = str(payload.get("name") or "").strip()
    settings = store.collect_settings(mode_key)
    try:
        texts = baked_texts(settings.get("pre_prompt", ""), settings.get("post_prompt", ""),
                            payload.get("artist_prompt", ""), payload.get("anchor_groups"))
    except ValueError as exc:
        raise ArtistMixError(str(exc)) from exc
    settings["pre_prompt"], settings["post_prompt"] = texts["pre"], texts["post"]
    main_settings = context._prompt_engineering_service()._capture_main_settings()
    main_settings.pop("prompt", None)
    data = {"module_settings": settings, "main_settings": main_settings,
            "artist_mix": copy_record(payload.get("blocks"), texts["pre"], texts["post"])}
    existed = name in store.list_preset_names(mode_key)
    old = store.read_preset_data(name, mode_key) if existed else {}
    if old.get("description"):
        data["description"] = old["description"]
    ok, message = store.export_preset(name, mode_key, data, overwrite=bool(payload.get("overwrite")))
    if not ok:
        if message == "exists":
            raise MixPresetExists(name)
        raise ArtistMixError(message)
    image = None
    if payload.get("main_history_id"):
        item = result_store.get_item(str(payload["main_history_id"])) if result_store else None
        image = item.webp_bytes if item is not None else None
    elif payload.get("mix_id"):
        record = mix_store.one(payload["mix_id"])
        main = (record.get("thumbs") or {}).get("main")
        image = mix_store.thumbnail(record["id"], main) if main else None
    thumbnail = None
    warnings = []
    if image:
        from app.backend.server.prompt_tools_routes import save_prompt_engineering_thumbnail_bytes
        try:
            thumbnail = save_prompt_engineering_thumbnail_bytes(context, message, mode_key, image)
        except Exception as exc:     # 그림은 장식이다 - 프리셋은 이미 써졌다
            warnings.append(f"썸네일을 쓰지 못했습니다: {exc}")
    return {"ok": True, "name": message, "mode": mode_key, "overwritten": existed,
            "thumbnail": thumbnail, "warnings": warnings}


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


def _refresh_favorite_wildcard(context: WebSessionContext, path: Path) -> None:
    """관심 작가 파일을 고친 뒤 돌고 있는 와일드카드 관리자에 그 한 개만 다시 읽힌다.

    관리자의 폴더 밖이면(설정이 갈린 경우) 아무것도 안 한다 - 거기 쓴 파일은 원래
    `__favorite_artist__` 로 불리지 않는다.
    """
    manager = getattr(context, "wildcard_manager", None)
    if manager is None or not hasattr(manager, "reload_one"):
        return
    try:
        rel = Path(path).resolve().relative_to(Path(manager.wildcards_dir).resolve())
    except ValueError:
        return
    manager.reload_one(rel.as_posix())


def _favorites_group(context: WebSessionContext) -> dict:
    names = artist_thumbnail_service(context).favorite_artists()
    return {"id": FAVORITES_GROUP_ID, "name": FAVORITES_GROUP_NAME, "temp": False, "fixed": True,
            "wildcard": "favorite_artist",
            "items": [{"artist": name} for name in names]}


# ── 그룹 = 와일드카드 (사용자 지정 2026-09-26) ────────────────────────────────
#  그룹마다 `wildcards/artist_group/<그룹 이름>.txt` - **작가 이름만** 한 줄에 하나(가중치·`artist:` 없음,
#  관심 작가 `favorite_artist.txt` 와 같은 약속). 부르는 쪽이 `artist:__artist_group/이름__` 처럼 감싼다.
#  ⚠️ 이 폴더에 사용자가 손으로 둔 파일은 건드리지 않는다 - 내가 만든 파일 이름을 목록(`.naia_artist_groups.json`)
#     에 적어 두고 **그 안에서만** 지운다(그룹을 지우거나 이름을 바꿀 때).
GROUP_WILDCARD_DIR = "artist_group"
GROUP_WILDCARD_MANIFEST = ".naia_artist_groups.json"


def _group_wildcard_files(groups: list, foreign: set[str] | None = None) -> dict[str, str]:
    """그룹 id -> 파일 이름(확장자 없이). 파일에 못 쓰는 글자는 `_` 로 - 겹치면 뒤 그룹에 id 꼬리를 단다.
    `foreign` = 그 폴더에 **사용자가 둔** 파일 이름(소문자, 확장자 없이) - 그 이름도 겹침으로 친다(Codex 리뷰
    2026-09-26 #1: 사용자의 `artist_group/mine.txt` 가 있는데 `mine` 그룹을 만들면 덮어쓰고, 그룹을 지우면 지웠다)."""
    out: dict[str, str] = {}
    used: set[str] = set(foreign or ())
    for group in groups:
        base = re.sub(r'[<>:"/\\|?*]', "_", str(group.get("name") or "").strip()).strip(". ") or "group"
        name = base
        if name.casefold() in used:
            name = f"{base} ({str(group.get('id') or '')[-4:]})"
        n = 2
        while name.casefold() in used:          # 꼬리를 달아도 겹치면(사용자 파일 · 같은 꼬리) 번호를 더한다
            name = f"{base} ({str(group.get('id') or '')[-4:]}-{n})"
            n += 1
        used.add(name.casefold())
        out[str(group.get("id") or "")] = name
    return out


def _owned_group_wildcards(root: Path) -> set[str]:
    """내가 만든 파일 이름들(목록 파일). ⚠️ 목록을 그대로 믿지 않는다 - 이 폴더 바로 아래의 `*.txt` 이름만
    받는다(Codex 리뷰 #4: 목록에 `../../victim.txt` 가 있으면 wildcards 밖의 파일을 지웠다)."""
    try:
        listed = json.loads((root / GROUP_WILDCARD_MANIFEST).read_text(encoding="utf-8")).get("files") or []
    except Exception:
        return set()
    owned = set()
    for name in listed:
        name = str(name)
        if (name.endswith(".txt") and Path(name).name == name and name not in {".", ".."}
                and "/" not in name and "\\" not in name and ":" not in name):
            owned.add(name)
    return owned


def _foreign_group_wildcards(root: Path, owned: set[str]) -> set[str]:
    """그 폴더에 있지만 내가 만들지 않은 `*.txt` - 그 이름은 그룹이 쓰지 않는다."""
    try:
        return {p.stem.casefold() for p in root.glob("*.txt") if p.is_file() and p.name not in owned}
    except OSError:
        return set()


def _group_wildcard_root(context: WebSessionContext) -> Path:
    return Path(artist_thumbnail_service(context).wildcards_root) / GROUP_WILDCARD_DIR


def _sync_group_wildcards(context: WebSessionContext) -> None:
    """그룹 목록 -> `artist_group/*.txt`. 바뀐 파일만 쓰고, 돌고 있는 와일드카드 관리자에 그것만 다시 읽힌다.
    빈 그룹은 파일을 두지 않는다(빈 와일드카드는 원래 싣지 않는다). 실패해도 본 요청은 성공이다."""
    try:
        groups = artist_group_store(context).list()
        root = _group_wildcard_root(context)
        manifest = root / GROUP_WILDCARD_MANIFEST
        previous = _owned_group_wildcards(root)
        names = _group_wildcard_files(groups, _foreign_group_wildcards(root, previous))
        wanted: dict[str, str] = {}
        for group in groups:
            artists = [str(i.get("artist") or "").strip() for i in (group.get("items") or [])]
            text = "".join(f"{a}\n" for a in artists if a)
            if text:
                wanted[names[str(group.get("id") or "")] + ".txt"] = text
        changed: list[Path] = []
        if wanted or previous:
            root.mkdir(parents=True, exist_ok=True)
        for filename, text in wanted.items():
            path = root / filename
            try:
                if path.read_text(encoding="utf-8") == text:
                    continue
            except OSError:
                pass
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(path)
            changed.append(path)
        for filename in previous - set(wanted):
            path = root / filename
            if path.parent.resolve() != root.resolve():       # 한 번 더 - 이 폴더 밖이면 손대지 않는다
                continue
            if path.is_file():
                path.unlink()
                changed.append(path)
        if set(wanted) != previous:
            manifest.write_text(json.dumps({"files": sorted(wanted)}, ensure_ascii=False, indent=1) + "\n",
                                encoding="utf-8")
        for path in changed:
            _refresh_favorite_wildcard(context, path)       # 한 파일만 다시 읽힌다(이름과 달리 어느 파일이든)
    except Exception as exc:  # noqa: BLE001
        print(f"[artist-groups] wildcard sync failed: {exc}", flush=True)


def _with_favorites(context: WebSessionContext, groups: list) -> list:
    """관심 목록을 못 읽어도 그룹 목록은 살린다 - 한쪽 고장이 다른 쪽을 가리지 않게.
    각 그룹에 와일드카드 이름(`wildcard`)을 싣는다 - 머리줄 복사 단추가 **이 값**을 쓴다(겹침 꼬리 포함)."""
    # ⚠️ 동기화와 **같은 이름**이어야 한다(사용자 파일을 비켜 간 꼬리 포함) - 복사 단추가 이 값을 쓴다.
    try:
        root = _group_wildcard_root(context)
        foreign = _foreign_group_wildcards(root, _owned_group_wildcards(root))
    except Exception:  # noqa: BLE001
        foreign = set()
    names = _group_wildcard_files(groups, foreign)
    groups = [{**g, "wildcard": f"{GROUP_WILDCARD_DIR}/{names[str(g.get('id') or '')]}"} for g in groups]
    try:
        return [_favorites_group(context), *groups]
    except Exception:
        return list(groups)


def _apply_favorites_op(context: WebSessionContext, payload: dict) -> dict:
    op = str(payload.get("op") or "").strip()
    service = artist_thumbnail_service(context)
    counts: dict = {}
    if op == "add":
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        names = [item.get("artist") if isinstance(item, dict) else item for item in items]
        counts = service.add_favorites(names, str(payload.get("mode") or ""))
    elif op == "remove":
        counts = service.remove_favorites(payload.get("artists") if isinstance(payload.get("artists"), list) else [])
    elif op == "reorder":
        counts = service.reorder_favorites(payload.get("artists") if isinstance(payload.get("artists"), list) else [])
    elif op == "weight":
        raise ArtistGroupError("관심 작가에는 가중치를 둘 수 없습니다")
    else:
        raise ArtistGroupError("관심 작가 그룹은 이름을 바꾸거나 지울 수 없습니다")
    return {"group": _favorites_group(context),
            "groups": _with_favorites(context, artist_group_store(context).list()), **counts}


def _sync_group_thumbnails(context: WebSessionContext) -> None:
    """그룹에 든 작가 전부의 썸네일 사본을 맞춘다(없는 것은 채우고, 빠진 작가는 지운다).

    그룹이 바뀐 뒤와 그룹 창이 그림을 물을 때(describe) 부른다. 실패해도 본 요청은 성공이다 -
    사본은 보기 좋으라고 두는 것이지 그룹의 일부가 아니다.
    """
    try:
        groups = artist_group_store(context).list()
        artists = [item.get("artist") for g in groups for item in (g.get("items") or [])]
        artist_thumbnail_service(context).sync_group_thumbnail_cache(artists)
    except Exception:
        pass


def _search_thumb_scope(context: WebSessionContext, payload: dict) -> Callable[[str], bool] | None:
    """검색의 [썸네일 있음 | 모두](사용자 지정 2026-09-30).

    `thumbs: has` 면 **카드에 그림이 뜨는 작가만** 남기는 판정을, 아니면 None(= 모두,
    예전 그대로)을 돌려준다. 모드는 화면이 지금 보는 썸네일 모드(`thumb_mode`)다 -
    격자가 그 모드로 그림을 그리므로 판정도 같은 모드로 해야 둘이 맞는다.
    """
    if str(payload.get("thumbs") or "").strip().lower() != "has":
        return None
    return artist_thumbnail_service(context).image_presence(str(payload.get("thumb_mode") or ""))


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
            on_favorites_written=lambda path: _refresh_favorite_wildcard(context, path),
        )
        context.artist_thumbnail_service = service
    return service


def _main_random_artist_override(context: WebSessionContext, clients: set[Any] | None = None):
    """[메인 랜덤 버튼 연결] - 메인 Random 이 부른다(`HeadlessRandomPromptService.random_artist_link`).
    {token, artist, weight, pick, page?} · 꺼져 있으면 None.
    [이번 세션 중복 스킵] 으로 뽑을 작가가 바닥났으면 뽑을 때마다 화면에 알린다(빨간 토스트 · 사용자 지정 2026-11-04).
    Auto Gen 이 미리 만드는 컷도 이 길이라 장마다 뜬다."""
    service = artist_thumbnail_service(context)
    picked = service.main_random_token(context.get_api_mode())
    if isinstance(picked, dict) and service.random_tools().get("main_exclusive"):
        # [다른 작가 숨김] - PE 훅이 이 표식을 보고 다른 작가를 걷는다(`artist_insert_tracker.exclusive_options`).
        picked = {**picked, "exclusive": True}
    if isinstance(picked, dict) and picked.get("exhausted") and clients:
        _announce_pool_exhausted(context, clients, str(picked.get("source") or "tab"))
    return picked


def _announce_pool_exhausted(context: WebSessionContext, clients: set[Any], source: str) -> None:
    """일꾼 스레드에서 부른다 - 주 이벤트 루프에 WS 알림을 넘긴다(기다리지 않는다)."""
    loop = getattr(context, "headless_main_loop", None)
    if loop is None or not loop.is_running():
        return
    try:
        import asyncio

        from app.backend.server.websocket_broadcast import broadcast_json

        asyncio.run_coroutine_threadsafe(broadcast_json(clients, {"type": "artist_pool_exhausted", "source": source}), loop)
    except Exception:  # noqa: BLE001 - 알림이 뽑기를 막지 않는다
        pass


# ── 결과 화면 작가 패널(사용자 지정 2026-11-03) ─────────────────────────────
#  [메인 랜덤 버튼 연결] 이 켜져 있으면 결과 화면 왼쪽 아래에 늘 뜬다. 다루는 작가 = **보이는 그림에 붙은 작가**
#  (히스토리 `linked_artist`). 조작 넷: [고정](빌린 정책 · `ArtistThumbnailService.link_pin`) · [임시](패널 전용
#  그룹 한 칸 · `ArtistGroupStore.toggle_link_slot`) · [숨김](제외 작가) · [그룹](관심 작가 포함).
#  `weight` = 가중치 손잡이 - 랜덤 작가 가중치만 바꾼다(고정하지 않는다). [삽입] 은 화면이 PE Prefix 를 고친다.
LINK_PANEL_OPS = {"pin", "unpin", "weight", "ban", "unban", "slot", "group", "group_new"}


def _link_panel_state(context: WebSessionContext, artist: str, mode: str = "") -> dict:
    service = artist_thumbnail_service(context)
    name = " ".join(str(artist or "").split())
    out: dict[str, Any] = {"tools": service.random_tools(), "artist": name}
    if not name:
        return out
    image_url = ""
    count = None
    try:
        items = (service.describe_artists(mode, [name]) or {}).get("items") or []
        image_url = str(items[0].get("image_url") or "") if items else ""
        # 게시물 수(격자 카드에 적힌 그 수 - `weight` 칸) - 이름에 마우스를 올리면 보인다(사용자 지정 2026-11-04).
        count = int(items[0].get("weight") or 0) if items and items[0].get("known") else None
    except Exception:  # noqa: BLE001 - 그림 · 수는 장식이다
        pass
    favorite = name in set(service.favorite_artists())
    groups = artist_group_store(context).list()
    key = name.casefold()

    def has(group: dict) -> bool:
        return any(str(item.get("artist") or "").casefold() == key for item in group.get("items") or [])

    slot = next((g for g in groups if g.get("slot") == LINK_SLOT), None)
    out.update(
        image_url=image_url,
        count=count,
        banned=name in set(service._banned()),
        slot={"id": slot["id"], "name": slot["name"], "has": has(slot), "count": len(slot.get("items") or [])}
        if slot else {"id": "", "name": LINK_SLOT_NAME, "has": False, "count": 0},
        groups=[{"id": FAVORITES_GROUP_ID, "name": FAVORITES_GROUP_NAME, "has": favorite, "fixed": True},
                *({"id": g["id"], "name": g["name"], "has": has(g)} for g in groups if not g.get("temp"))],
    )
    return out


def _apply_link_panel_op(context: WebSessionContext, payload: dict) -> bool:
    """패널 조작 하나. 돌려주는 값 = 랜덤 도구(고정 · 정책)가 바뀌었을 수 있는가."""
    op = str(payload.get("op") or "")
    artist = " ".join(str(payload.get("artist") or "").split())
    if not artist:
        raise ValueError("artist is required")
    service = artist_thumbnail_service(context)
    if op in ("pin", "unpin"):
        service.link_pin(artist, payload.get("weight"), pin=op == "pin")
        return True
    if op == "weight":
        service.set_random_weight(payload.get("weight"))
        return True
    if op in ("ban", "unban"):
        service.set_banned(artist, op == "ban", return_state=False)
        return True
    store = artist_group_store(context)
    if op == "slot":
        store.toggle_link_slot(artist)
    elif op == "group":
        gid = str(payload.get("group_id") or "")
        add = bool(payload.get("add", True))
        if gid == FAVORITES_GROUP_ID:
            _apply_favorites_op(context, {"op": "add", "items": [{"artist": artist}], "mode": payload.get("mode")}
                                if add else {"op": "remove", "artists": [artist]})
        elif add:
            store.add(gid, [{"artist": artist}])
        else:
            store.remove(gid, [artist])
    elif op == "group_new":
        store.create(payload.get("name"), [{"artist": artist}])
    _sync_group_thumbnails(context)
    _sync_group_wildcards(context)
    return False


INSERT_TRACKER_OPS = {"add", "update", "remove", "solo", "commit"}


def _apply_insert_tracker_op(context, payload):
    tracker = artist_insert_tracker(context)
    preset, mode = current_scope(context)
    tracker.check_scope(preset, mode)
    op = payload.get("op")
    if op == "add":
        return tracker.add(payload.get("artist"), payload.get("weight", 1.0), payload.get("slot", "pre"),
                           payload.get("with_prefix", True), preset=preset, mode=mode)
    if op == "update":
        return tracker.update(payload.get("id"), **{k: v for k, v in payload.items() if k not in ("op", "id")})
    if op == "remove":
        return tracker.remove(payload.get("id"))
    if op == "solo":
        if "id" not in payload:
            raise ValueError("id is required (null clears solo)")
        return tracker.set_solo(payload["id"], payload.get("scope", "all"))
    if op == "commit":
        return tracker.clear()
    raise ValueError("Unknown insert tracker op")


def _link_pending_weight(context: WebSessionContext, payload: dict) -> dict:
    """결과 화면 작가 패널의 '다음' 작가(이번 Random 에 붙었고 아직 그림이 없다)의 가중치를 지금 프롬프트에서 바꾼다
    (사용자 지정 2026-11-14). 생성은 하지 않는다.

    글과 그 prompt run 의 기록(`final_prompt` · `linked_artist` 가중치)을 **함께** 고친다 - 글만 고치면 다음 생성 요청이
    run 과 어긋나(`HeadlessGenerationService._prompt_run_id_for_command`) 그 그림에 작가 기록이 안 남는다.
    그사이 글을 손으로 고쳤으면(`seen` 불일치) · 다른 Random 이 와서 붙은 작가가 바뀌었으면 · Draft 가 글을 쥐었으면 고치지 않는다.
    """
    from core.event_map.draft import active as draft_active
    from core.headless_random_prompt_service import pipeline_swap_lock
    from core.prompt_artist_strip import ReweightError, reweight_artist

    artist = " ".join(str(payload.get("artist") or "").split())
    seen = str(payload.get("seen") or "")
    wrap = str(payload.get("wrap") or "")
    one = str(payload.get("one") or "")
    try:
        weight = round(float(payload.get("weight")), 2)
    except (TypeError, ValueError):
        raise ReweightError("bad_request") from None
    if not artist or not wrap or weight != weight:
        raise ReweightError("bad_request")
    known = _mix_known_artists(context)
    with pipeline_swap_lock(context):
        if draft_active(context):
            raise ReweightError("draft")
        ctx = getattr(context, "current_prompt_context", None)
        meta = getattr(ctx, "metadata", None) if ctx is not None else None
        linked = meta.get("linked_artist") if isinstance(meta, dict) else None
        if not isinstance(linked, dict) or str(linked.get("artist") or "").strip().casefold() != artist.casefold():
            raise ReweightError("gone")
        current = str(context.prompt_text or "")
        if current != seen:
            raise ReweightError("edited")
        result = reweight_artist(current, artist, wrap, one=one, known=known)
        prompt = str(result.get("prompt") or "")
        if not result.get("changed") or not prompt or prompt == current:   # 껍질을 갈아 끼워도 같은 글일 수 있다
            return {"prompt": current, "changed": False}
        run_holds = str(getattr(ctx, "final_prompt", "") or "").strip() == current.strip()
        context.prompt_text = prompt
        if run_holds:
            ctx.final_prompt = prompt
        meta["linked_artist"] = {**linked, "weight": weight}
        context.save_remote_ui_state()
    return {"prompt": prompt, "changed": True}


async def _broadcast_random_tools(context: WebSessionContext, clients: set[Any], run_in_thread) -> None:
    """랜덤 도구가 바뀌었다 - 결과 화면 작가 패널 · 아티스트 창(다른 탭 포함)이 같은 값을 보게 한다."""
    try:
        from app.backend.server.websocket_broadcast import broadcast_json

        tools = await run_in_thread(artist_thumbnail_service(context).random_tools)
        await broadcast_json(clients, {"type": "artist_random_tools", "tools": tools})
    except Exception:  # noqa: BLE001 - 알림이 본 요청을 실패시키지 않는다
        pass


async def _reset_deleted_random_source(context: WebSessionContext, clients: set[Any], run_in_thread,
                                       group_id: Any) -> None:
    """메인 Random 출처였던 그룹을 지웠다 - 출처를 아티스트 탭으로 되돌리고 알린다(사용자 지정 2026-11-04)."""
    service = artist_thumbnail_service(context)
    source = (await run_in_thread(service.random_tools)).get("source") or {}
    if source.get("kind") != "group" or source.get("id") != str(group_id or ""):
        return
    await run_in_thread(service.set_random_source, {"kind": "tab"})
    from app.backend.server.generation_commands import invalidate_auto_gen_prefetch

    invalidate_auto_gen_prefetch(context)                   # 미리 만든 컷은 지운 그룹에서 뽑았다
    await _broadcast_random_tools(context, clients, run_in_thread)


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


_SMALL_BODY_LIMIT = 512 * 1024


async def _small_json_body(req: Request, limit: int = _SMALL_BODY_LIMIT) -> dict | None:
    """프롬프트 한 편을 받는 라우트의 본문 - `limit` 바이트를 넘으면 None(413). 글이 아니거나 깨졌으면 빈 dict.

    `req.json()` 은 본문을 다 받은 뒤에야 길이를 볼 수 있다 - 글을 6만 자로 자르기 전에 100MB 를 통째로 버퍼에 올린다
    (Codex 리뷰 2026-11-12 #7). 받는 동안 센다(Content-Length 가 없는 조각 전송도 걸린다).
    """
    try:
        if int(req.headers.get("content-length") or 0) > limit:
            return None
    except ValueError:
        pass
    chunks, total = [], 0
    async for chunk in req.stream():
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)
    try:
        payload = json.loads(b"".join(chunks) or b"{}")
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def register_artist_thumbnail_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
    clients: set[Any],
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    # [메인 랜덤 버튼 연결] - 메인 Random 이 이 공급자를 부른다(core 는 app.backend 를 모른다).
    session_context.random_artist_override_provider = partial(_main_random_artist_override, session_context, clients)

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
        except ArtistLoadCancelled as exc:
            # 화면이 팩 읽기를 그만두라고 했다(외부 브라우저의 [중단]) - 고장이 아니다
            return JSONResponse({"error": str(exc), "cancelled": True}, status_code=409)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb list failed: {exc}"}, status_code=500)

    @app.get("/api/artist-thumb/load-status")
    async def api_artist_thumb_load_status():
        # 팩을 읽는 동안 화면이 '무엇을 기다리는지' 묻는다(외부 브라우저 - artist-viewer.html). 잠금을 잡지 않는
        # 조회라 스레드로 넘기지 않는다. 팩 하나를 파싱하는 동안에는 이 답도 못 나간다 - 팩 사이 · 파일을 읽는 동안에 나간다.
        return artist_thumbnail_service(session_context).load_status()

    @app.post("/api/artist-thumb/load-cancel")
    async def api_artist_thumb_load_cancel():
        # 읽고 있는 팩을 그만두라고 적는다. 멈추는 자리는 읽는 쪽이 정한다(파일을 읽은 뒤 · 다음 팩으로 넘어가기 전).
        return {"ok": True, "cancelling": artist_thumbnail_service(session_context).load_cancel()}

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

    # 아티스트 태그 관리 창(사용자 지시 2026-11-11) - 메인 프롬프트에 쓴 작가를 **부른 그때 한 번** 타일로 보여 준다.
    # 팩을 올리지 않고 자리 색인으로 그 작가의 그림만 읽는다(core/artist_pack_index).
    @app.post("/api/artist-thumb/used")
    async def api_artist_thumb_used(req: Request):
        payload = await _small_json_body(req)
        if payload is None:
            return JSONResponse({"ok": False, "error": "request body is too large"}, status_code=413)
        text = str(payload.get("text") or "")[:60000]
        mode = str(payload.get("mode") or "")
        # PE 의 prefix · postfix 글 - 타일마다 그 작가가 어느 칸에서 왔는지(`sources`) 적는다(사용자 지시 2026-11-13).
        fields = {"prefix": str(payload.get("pre") or "")[:60000], "postfix": str(payload.get("post") or "")[:60000]}

        def _run():
            from core.artist_mix_preset import _dict_key
            from core.prompt_artist_strip import find_artists_weighted

            known = _mix_known_artists(session_context)
            # 같은 작가를 두 번 썼으면 처음 것 하나만(가중치도 그것).
            first: dict[str, tuple[str, float]] = {}
            for row in find_artists_weighted(text, known=known):
                name = " ".join(str(row["name"]).split())
                if row.get("reason") != "anchor" and name:
                    first.setdefault(name.casefold(), (name, row["weight"]))
            owners = {label: {_dict_key(row["name"]) for row in find_artists_weighted(body, known=known)}
                      for label, body in fields.items() if body.strip()}
            service = artist_thumbnail_service(session_context)
            tiles = service.used_artist_tiles([n for n, _ in first.values()], mode)
            artists = [{**tile, "weight": weight,
                        "sources": [label for label, names in owners.items() if _dict_key(name) in names]}
                       for tile, (name, weight) in zip(tiles, first.values())]
            # 이 계열의 팩과 받았는지 - 창이 '데이터 없음' 이 있을 때 안 받은 팩의 [받기] 를 띄운다(사용자 지시 2026-11-13).
            return artists, service.used_pack_offers(mode)

        try:
            artists, offers = await run_in_thread(_run)
            return {"ok": True, "artists": artists, "family": offers["family"], "packs": offers["packs"]}
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Artist tags failed: {exc}"}, status_code=500)

    # [이 아티스트로만 생성] 이 보낼 글 - 작가를 전부 걷고 고른 작가의 태그(서식은 화면이 만든다) 하나만 넣는다.
    # 글만 돌려준다. 프롬프트 칸 · 세션 · 파일은 건드리지 않는다.
    @app.post("/api/artist-thumb/used-solo")
    async def api_artist_thumb_used_solo(req: Request):
        payload = await _small_json_body(req)
        if payload is None:
            return JSONResponse({"ok": False, "error": "request body is too large"}, status_code=413)
        text = str(payload.get("text") or "")[:60000]
        token = " ".join(str(payload.get("token") or "").split())[:400]
        if not token:
            return JSONResponse({"ok": False, "error": "token is required"}, status_code=400)

        def _run():
            from core.prompt_artist_strip import solo_artist

            return solo_artist(text, token, known=_mix_known_artists(session_context))

        try:
            result = await run_in_thread(_run)
            return {"ok": True, "prompt": result["prompt"], "removed": len(result["removed"])}
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Artist solo failed: {exc}"}, status_code=500)

    # [가중치를 업데이트하여 생성] · [이 가중치로 PE 업데이트] 가 쓸 글 - 고른 작가의 가중치만 바꾼다(사용자 지시 2026-11-13).
    # `wrap` = 화면이 모드에 맞게 만든 껍질(자리 표시 U+E000 하나) · `fresh` = 글에 없을 때 넣을 새 태그(빈 글이면 안 넣는다).
    # 글만 돌려준다. 프롬프트 칸 · PE · 파일은 건드리지 않는다.
    @app.post("/api/artist-thumb/used-reweight")
    async def api_artist_thumb_used_reweight(req: Request):
        payload = await _small_json_body(req)
        if payload is None:
            return JSONResponse({"ok": False, "error": "request body is too large"}, status_code=413)
        text = str(payload.get("text") or "")
        artist = " ".join(str(payload.get("artist") or "").split())
        wrap = str(payload.get("wrap") or "")
        fresh = " ".join(str(payload.get("fresh") or "").split())
        one = str(payload.get("one") or "")          # 가중치 1 을 드러내 적는 껍질(모드의 문법) - 없으면 NAI 꼴
        if not artist:
            return JSONResponse({"ok": False, "error": "artist is required"}, status_code=400)
        # 길면 자르지 않고 거절한다 - 잘린 글을 돌려주면 화면이 그것으로 프롬프트 칸 · PE 를 덮는다(Codex 리뷰 1차 #1).
        if len(text) > 60000 or len(artist) > 300 or len(wrap) > 400 or len(fresh) > 400 or len(one) > 400:
            return JSONResponse({"ok": False, "error": "too_long"}, status_code=413)

        def _run():
            from core.prompt_artist_strip import reweight_artist

            return reweight_artist(text, artist, wrap, fresh=fresh, one=one, known=_mix_known_artists(session_context))

        try:
            result = await run_in_thread(_run)
        except ValueError as exc:
            code = getattr(exc, "code", "") or "bad_request"
            return JSONResponse({"ok": False, "error": code}, status_code=409 if code != "bad_request" else 400)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Artist reweight failed: {exc}"}, status_code=500)
        return {"ok": True, **result}

    @app.post("/api/artist-thumb/link-pending-weight")
    async def api_artist_thumb_link_pending_weight(req: Request):
        # 결과 화면 작가 패널 - '다음' 작가의 [× 가중치] 가 지금 프롬프트의 그 작가 가중치도 고친다(`_link_pending_weight`).
        payload = await _small_json_body(req)
        if payload is None:
            return JSONResponse({"ok": False, "error": "request body is too large"}, status_code=413)
        if len(str(payload.get("seen") or "")) > 60000 or len(str(payload.get("wrap") or "")) > 400 \
                or len(str(payload.get("one") or "")) > 400 or len(str(payload.get("artist") or "")) > 300:
            return JSONResponse({"ok": False, "error": "too_long"}, status_code=413)
        try:
            result = await run_in_thread(_link_pending_weight, session_context, payload)
        except ValueError as exc:
            code = getattr(exc, "code", "") or "bad_request"
            return JSONResponse({"ok": False, "error": code}, status_code=400 if code == "bad_request" else 409)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Artist pending weight failed: {exc}"}, status_code=500)
        if result.get("changed"):
            try:
                from app.backend.server.websocket_broadcast import broadcast_json

                # 열린 탭들도 새 글을 받는다(force 없음 - 치는 중인 탭은 기존 규칙대로 제 글을 지킨다).
                await broadcast_json(clients, {"type": "prompt_sync", "prompt": result["prompt"]})
            except Exception:  # noqa: BLE001 - 알림이 본 요청을 실패시키지 않는다
                pass
        return {"ok": True, **result}

    @app.get("/api/artist-thumb/used-image")
    async def api_artist_thumb_used_image(mode: str = "", artist: str = ""):
        try:
            image_bytes, media_type = await run_in_thread(
                artist_thumbnail_service(session_context).used_image_payload, mode, artist)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except (FileNotFoundError, KeyError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb image failed: {exc}"}, status_code=500)
        return Response(content=image_bytes, media_type=media_type,
                        headers={"Cache-Control": "public, max-age=3600"})

    @app.get("/api/artist-bench-views")
    async def api_artist_bench_views_list():
        try:
            data = await run_in_thread(artist_bench_view_store(session_context).snapshot)
            current = await run_in_thread(_bench_current_spec, session_context)
            # 편집기의 모델·샘플러·스케줄러 칸이 고를 수 있는 값(지금 모드의 선택지).
            schema = await run_in_thread(session_context.generation_param_schema_payload)
            options = {key: list(schema.get(f"options_{key}") or []) for key in ("model", "sampler", "scheduler")}
            return {**data, "current": current, "options": options}
        except Exception as exc:
            # 읽을 수 없는 파일은 **덮어쓰지 않는다** - 원본은 그대로 두고 알린다.
            return JSONResponse({"error": f"Bench views unreadable: {exc}"}, status_code=500)

    @app.post("/api/artist-bench-views")
    async def api_artist_bench_views_mutate(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            return JSONResponse({"error": "JSON object body required"}, status_code=400)
        if str(payload.get("op") or "") not in _VIEW_OPS:
            return JSONResponse({"error": f"op must be one of {sorted(_VIEW_OPS)}"}, status_code=400)
        try:
            return await run_in_thread(_apply_view_op, session_context, payload)
        except ArtistBenchViewError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)
        except Exception as exc:
            return JSONResponse({"error": f"Bench views update failed: {exc}"}, status_code=500)

    @app.get("/api/artist-thumb/view-image")
    async def api_artist_thumb_view_image(view: str = "", artist: str = ""):
        try:
            image_bytes, media_type = await run_in_thread(
                artist_thumbnail_service(session_context).view_image_payload, view, artist,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb view image failed: {exc}"}, status_code=500)
        # 주소의 `t=` 가 파일 시각이라 다시 뽑으면 주소가 바뀐다 - 길게 캐시해도 된다.
        return Response(content=image_bytes, media_type=media_type,
                        headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/api/artist-thumb/group-image")
    async def api_artist_thumb_group_image(artist: str = ""):
        try:
            image_bytes, media_type = await run_in_thread(
                artist_thumbnail_service(session_context).group_image_payload,
                artist,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except (FileNotFoundError, KeyError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb group image failed: {exc}"}, status_code=500)
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": "no-cache"},
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
            await run_in_thread(_sync_group_thumbnails, session_context)
            return await run_in_thread(
                artist_thumbnail_service(session_context).describe_artists,
                payload.get("mode", ""),
                payload.get("artists"),
                str(payload.get("view") or ""),
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
            only = await run_in_thread(_search_thumb_scope, session_context, payload)
            result = await run_in_thread(
                artist_search, artist_affinity_pack(), payload.get("stack"),
                order=str(payload.get("order") or "wilson"),
                limit=limit,
                offset=int(payload.get("offset") or 0),
                only=only)
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
            await run_in_thread(_sync_group_wildcards, session_context)
            return {"groups": await run_in_thread(_with_favorites, session_context, groups)}
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
            if str(payload.get("id") or "") == FAVORITES_GROUP_ID:
                if payload.get("op") == "create":
                    raise ArtistGroupError("관심 작가 그룹은 새로 만들 수 없습니다")
                return await run_in_thread(_apply_favorites_op, session_context, payload)
            result = await run_in_thread(_apply_group_op, artist_group_store(session_context), payload)
            if payload.get("op") == "delete":
                await _reset_deleted_random_source(session_context, clients, run_in_thread, payload.get("id"))
            await run_in_thread(_sync_group_thumbnails, session_context)
            await run_in_thread(_sync_group_wildcards, session_context)
            if isinstance(result.get("groups"), list):
                result["groups"] = await run_in_thread(_with_favorites, session_context, result["groups"])
            return result
        except ArtistGroupError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)
        except Exception as exc:
            return JSONResponse({"error": f"Artist groups update failed: {exc}"}, status_code=500)

    @app.get("/api/artist-mixes")
    async def api_artist_mixes_list():
        try:
            mixes = await run_in_thread(artist_mix_store(session_context).summaries)
            return {"mixes": mixes}
        except Exception as exc:
            # 읽을 수 없는 파일은 **덮어쓰지 않는다** - 원본은 그대로 두고 알린다.
            return JSONResponse({"error": f"Artist mixes unreadable: {exc}"}, status_code=500)

    @app.get("/api/artist-mixes/current")
    async def api_artist_mix_current():
        return await run_in_thread(_mix_current_layers, session_context)

    @app.get("/api/artist-mixes/name")
    async def api_artist_mix_name(name: str = ""):
        return await run_in_thread(artist_mix_store(session_context).matching_name, name)

    @app.get("/api/artist-mixes/one")
    async def api_artist_mix_one(id: str = ""):
        try:
            return {"mix": await run_in_thread(artist_mix_store(session_context).one, id)}
        except ArtistMixError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)

    @app.post("/api/artist-mixes/candidates")
    async def api_artist_mix_candidates(req: Request):
        try:
            payload = await req.json()
            if not isinstance(payload, dict):
                raise ValueError("JSON object body required")
            rows = await run_in_thread(session_context.result_store.mix_candidates,
                                       payload.get("artists"), payload.get("limit", 24))
            return {"candidates": rows}
        except (ValueError, TypeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/api/artist-mixes/thumb")
    async def api_artist_mix_thumb(id: str = "", file: str = ""):
        try:
            data = await run_in_thread(artist_mix_store(session_context).thumbnail, id, file)
            return Response(data, media_type="image/webp", headers={"Cache-Control": "private, max-age=86400"})
        except ArtistMixError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)

    @app.get("/api/artist-mixes/presets")
    async def api_artist_mix_presets(mode: str = ""):
        try:
            return await run_in_thread(_mix_preset_list, session_context, mode)
        except Exception as exc:
            return JSONResponse({"error": f"Preset list failed: {exc}"}, status_code=500)

    @app.get("/api/artist-mixes/from-preset")
    async def api_artist_mix_from_preset(name: str = "", mode: str = ""):
        try:
            return await run_in_thread(_mix_from_preset, session_context, name, mode)
        except ArtistMixError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)
        except Exception as exc:
            return JSONResponse({"error": f"Preset read failed: {exc}"}, status_code=500)

    @app.post("/api/artist-mixes/export-preset")
    async def api_artist_mix_export_preset(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            return JSONResponse({"error": "JSON object body required"}, status_code=400)
        try:
            result = await run_in_thread(_export_mix_preset, session_context, payload,
                                         artist_mix_store(session_context), session_context.result_store)
        except MixPresetExists as exc:
            return JSONResponse({"error": str(exc), "exists": True, "name": exc.name}, status_code=409)
        except ArtistMixError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)
        except Exception as exc:
            return JSONResponse({"error": f"Preset export failed: {exc}"}, status_code=500)
        # Quick Preset 목록·썸네일이 곧바로 따라오게 알린다(현재 프리셋은 그대로다).
        from app.backend.server.websocket_broadcast import broadcast_json
        await broadcast_json(clients, session_context.module_state_payload("prompt_engineering"))
        if result.get("thumbnail"):
            await broadcast_json(clients, {"type": "prompt_engineering_preset_thumbnail_updated",
                                           **result["thumbnail"]})
        return result

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
            result = await run_in_thread(_apply_mix_op, artist_mix_store(session_context), payload,
                                         artist_thumbnail_service(session_context), session_context.result_store, session_context)
            if payload.get("op") == "apply" and result["applied"]:
                from app.backend.server.websocket_broadcast import broadcast_json
                await broadcast_json(clients, result["params"])
                if "negative" in result["applied"]:
                    await broadcast_json(clients, {"type": "prompt_sync", "prompt": session_context.prompt_text,
                                                  "negative": result["negative"], "negative_prompt": result["negative"]})
            return result
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
            result = await run_in_thread(
                artist_thumbnail_service(session_context).set_banned,
                payload.get("artist", ""),
                bool(payload.get("banned", True)),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb ban failed: {exc}"}, status_code=500)
        # 숨긴 작가가 Auto Gen 이 미리 만든 다음 컷에 붙어 있을 수 있다 - 그 컷을 버린다(Codex 리뷰).
        from app.backend.server.generation_commands import invalidate_auto_gen_prefetch

        invalidate_auto_gen_prefetch(session_context)
        await _broadcast_random_tools(session_context, clients, run_in_thread)
        return result

    @app.post("/api/artist-thumb/options")
    async def api_artist_thumb_options(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            saved = await run_in_thread(artist_thumbnail_service(session_context).save_options, payload)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb options failed: {exc}"}, status_code=500)
        if isinstance(payload.get("random_tools"), dict):
            # [메인 랜덤 버튼 연결] 설정이 바뀌었다 - Auto Gen 이 옛 설정으로 미리 만든 컷을 버린다(Codex 리뷰).
            from app.backend.server.generation_commands import invalidate_auto_gen_prefetch

            invalidate_auto_gen_prefetch(session_context)
            await _broadcast_random_tools(session_context, clients, run_in_thread)
        return saved

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

    # 랜덤 도구만 가볍게(사용자 지시 2026-10-19) - Result 의 [아티스트 탭 연동됨] 표시가 앱을 켤 때 묻는다.
    # `/state` 는 팩 · 관심 작가 썸네일까지 훑어서 무겁다.
    @app.get("/api/artist-thumb/random-tools")
    async def api_artist_thumb_random_tools():
        try:
            return await run_in_thread(artist_thumbnail_service(session_context).random_tools)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb random tools failed: {exc}"}, status_code=500)

    # 결과 화면 [… 연동됨] 메뉴(사용자 지정 2026-11-04) - 메인 Random 이 작가를 뽑는 곳.
    @app.get("/api/artist-thumb/random-sources")
    async def api_artist_thumb_random_sources():
        try:
            return await run_in_thread(artist_thumbnail_service(session_context).random_sources)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb random sources failed: {exc}"}, status_code=500)

    @app.post("/api/artist-thumb/random-sources")
    async def api_artist_thumb_random_source_set(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict) or not ({"kind", "range", "skip_seen"} & set(payload)):
            return JSONResponse({"error": "body must have kind/id, range or skip_seen"}, status_code=400)
        service = artist_thumbnail_service(session_context)
        try:
            if "kind" in payload:
                await run_in_thread(service.set_random_source, payload)
            if "range" in payload or "skip_seen" in payload:
                # 아티스트 탭 구간 · 이번 세션 중복 스킵(사용자 지정 2026-11-04)
                await run_in_thread(partial(service.set_random_source_options, range_value=payload.get("range"),
                                            skip_seen=payload["skip_seen"] if "skip_seen" in payload else None))
            result = await run_in_thread(service.random_sources)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb random source failed: {exc}"}, status_code=500)
        from app.backend.server.generation_commands import invalidate_auto_gen_prefetch

        invalidate_auto_gen_prefetch(session_context)            # 미리 만든 컷은 옛 출처로 뽑았다
        await _broadcast_random_tools(session_context, clients, run_in_thread)
        return result

    @app.get("/api/artist-thumb/insert-tracker")
    async def api_artist_insert_tracker():
        try:
            return await run_in_thread(artist_insert_tracker(session_context).snapshot)
        except Exception as exc:
            return JSONResponse({"error": f"Artist insert tracker failed: {exc}"}, status_code=500)

    @app.post("/api/artist-thumb/insert-tracker")
    async def api_artist_insert_tracker_op(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict) or str(payload.get("op") or "") not in INSERT_TRACKER_OPS:
            return JSONResponse({"error": f"op must be one of {sorted(INSERT_TRACKER_OPS)}"}, status_code=400)
        try:
            snapshot = await run_in_thread(_apply_insert_tracker_op, session_context, payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Artist insert tracker failed: {exc}"}, status_code=500)
        if payload["op"] in {"solo", "commit", "remove", "update"}:
            from app.backend.server.generation_commands import invalidate_auto_gen_prefetch

            invalidate_auto_gen_prefetch(session_context)
        try:
            from app.backend.server.websocket_broadcast import broadcast_json

            await broadcast_json(clients, {"type": "artist_insert_tracker", "tracker": snapshot})
        except Exception:  # 알림 실패가 본 요청을 실패시키지 않는다
            pass
        return snapshot

    @app.get("/api/artist-thumb/link-panel")
    async def api_artist_thumb_link_panel(artist: str = "", mode: str = ""):
        try:
            return await run_in_thread(_link_panel_state, session_context, artist, mode)
        except Exception as exc:
            return JSONResponse({"error": f"Artist link panel failed: {exc}"}, status_code=500)

    @app.post("/api/artist-thumb/link-panel")
    async def api_artist_thumb_link_panel_op(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = None
        if not isinstance(payload, dict) or str(payload.get("op") or "") not in LINK_PANEL_OPS:
            return JSONResponse({"error": f"op must be one of {sorted(LINK_PANEL_OPS)}"}, status_code=400)
        try:
            tools_changed = await run_in_thread(_apply_link_panel_op, session_context, payload)
        except ArtistGroupError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Artist link panel failed: {exc}"}, status_code=500)
        if tools_changed:
            # 붙일 작가 · 정책이 바뀌었다 - Auto Gen 이 옛 설정으로 미리 만든 컷을 버린다(옵션 저장과 같은 규칙).
            from app.backend.server.generation_commands import invalidate_auto_gen_prefetch

            invalidate_auto_gen_prefetch(session_context)
            await _broadcast_random_tools(session_context, clients, run_in_thread)
        try:
            return await run_in_thread(_link_panel_state, session_context, payload.get("artist", ""),
                                       str(payload.get("mode") or ""))
        except Exception as exc:
            return JSONResponse({"error": f"Artist link panel failed: {exc}"}, status_code=500)

    # [생성 버튼 -> 랜덤 아티스트] - 지금 목록에서 한 명(사용자 지시 2026-10-19).
    @app.post("/api/artist-thumb/random-pick")
    async def api_artist_thumb_random_pick(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            item = await run_in_thread(partial(
                artist_thumbnail_service(session_context).pick_random_artist,
                str(payload.get("mode") or ""),
                str(payload.get("filter") or "all"),
                str(payload.get("query") or ""),
                int(payload.get("per_page") or 48),
                search=payload.get("search"),            # 아티스트 창 [검색] 결과에서(사용자 지정 2026-11-04)
            ))
        except ArtistLoadCancelled as exc:
            return JSONResponse({"error": str(exc), "cancelled": True}, status_code=409)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb random pick failed: {exc}"}, status_code=500)
        if not item:
            return JSONResponse({"error": "지금 목록에 뽑을 작가가 없습니다."}, status_code=404)
        return item

    def _exclusive_artist_settings(module_settings):
        """[이 작가만] - PE 설정 **사본**에서 다른 작가를 걷는다(저장한 PE 는 그대로).

        - 프리픽스 · 포스트픽스의 작가 토큰(삽입 그룹 판이 넣은 것 포함)을 뺀다 - 삽입 솔로 '전체' 와 같은 걷기다.
        - 랜덤 행의 작가(Remove Author 가 꺼져 있을 때 앞에 붙는 것)를 이번에만 끈다.
        - 메인 랜덤 버튼 연결 작가는 따로 막지 않는다 - 이 길은 PE 오버라이드를 걸므로 원래 안 붙는다.
        ⚠️ 와일드카드가 펼쳐 넣는 작가는 못 걷는다(펼치기 전 글만 본다)."""
        from core.artist_insert_tracker import strip_other_artists_text

        settings = dict(module_settings or {})
        for key in ("pre_prompt", "post_prompt"):
            settings[key] = strip_other_artists_text(session_context, settings.get(key))
        options = dict(settings.get("preprocessing_options") or {})
        options["remove_author"] = True
        settings["preprocessing_options"] = options
        return settings

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
            # [이 작가만](휴대폰 Artists · 사용자 지정 2026-11-06) - 이번 한 장에는 고른 작가만 나가게 한다.
            exclusive = payload.get("exclusive_artist") is True
            if exclusive:
                module_settings = await run_in_thread(_exclusive_artist_settings, module_settings)
            peng_override = await run_in_thread(
                artist_thumbnail_service(session_context).random_prompt_override,
                artist_prompt,
                module_settings,
                raw_groups,
            )
            if exclusive:
                peng_override["exclusive_artist"] = True
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
        view_id = str(payload.get("bench_view") or "").strip()
        try:
            if view_id:
                view = await run_in_thread(artist_bench_view_store(session_context).get, view_id)
                current_mode = str(session_context.get_api_mode() or "NAI").upper()
                # ⚠️ 다른 백엔드의 보기로 뽑으면 모델 이름부터 뜻이 달라진다 - 거절한다.
                if view["api_mode"] != current_mode:
                    return JSONResponse({"error": f"'{view['name']}' 보기는 {view['api_mode']} 용입니다 "
                                                  f"(지금 {current_mode})"}, status_code=409)
                # 확인할 때의 조건과 같은가 - 예약 뒤에 보기를 고쳤으면(무료 -> 유료 포함) 남은 예약은 멈춘다(Codex #2).
                if str(payload.get("bench_view_rev") or "") != view["rev"]:
                    return JSONResponse({"error": f"'{view['name']}' 보기가 확인한 뒤에 바뀌었습니다 - "
                                                  "남은 예약을 멈췄습니다. 다시 [생성] 하세요"}, status_code=409)
                # 이 검사 전에 저장된 옛 보기 - NAI 가 64 배수로 반올림하면 무료 넓이를 넘을 수 있다(Codex #3).
                if view["api_mode"] == "NAI" and (int(view["width"]) % 64 or int(view["height"]) % 64):
                    return JSONResponse({"error": f"'{view['name']}' 보기의 해상도({view['width']}x{view['height']})를 "
                                                  "64 의 배수로 고쳐 저장하세요"}, status_code=400)
                schema = await run_in_thread(session_context.generation_param_schema_payload)
                from core.anima_engine.integration import managed_anima
                overrides = await run_in_thread(
                    partial(artist_thumbnail_service(session_context).view_generation_overrides,
                            payload, view, schema,
                            current_model=str((getattr(session_context, "remote_params", None) or {}).get("model") or ""),
                            managed_anima=current_mode == "COMFYUI" and managed_anima(session_context)),
                )
            else:
                overrides = await run_in_thread(
                    artist_thumbnail_service(session_context).generation_overrides,
                    payload,
                )
        except ArtistBenchViewError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)
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
