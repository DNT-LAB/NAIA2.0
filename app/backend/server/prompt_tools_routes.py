from __future__ import annotations

import io
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from core import result_image_payload_service as result_images
from core.headless_generation_service import HeadlessGenerationService
from core.web_session_context import WebSessionContext


PROMPT_ENGINEERING_PRESET_MODES = ("NAI", "WEBUI", "COMFYUI")
AsyncRunner = Callable[..., Awaitable[Any]]
JsonBroadcaster = Callable[[set[Any], dict[str, Any]], Awaitable[None]]
GenerationRunnerStarter = Callable[[WebSessionContext, set[Any]], None]


def prompt_highlight_empty_index() -> dict[str, object]:
    return {
        "version": "runtime-empty",
        "groups": {},
        "tags": {},
        "stats": {
            "source": "runtime",
            "total": 0,
        },
    }


def _no_cache_headers() -> dict[str, str]:
    return {"Cache-Control": "no-store, max-age=0"}


def _generation_service(context: WebSessionContext) -> HeadlessGenerationService:
    service = getattr(context, "headless_generation_service", None)
    if service is None:
        service = HeadlessGenerationService(context)
        context.headless_generation_service = service
    return service


def _image_media_type_for_path(image_path: str | Path) -> str:
    return result_images.image_media_type_for_path(image_path)


def _tag_data_roots(context: WebSessionContext) -> list[Path]:
    roots: list[Path] = []
    runtime_paths = getattr(context, "runtime_paths", None)
    if runtime_paths is not None:
        roots.append(runtime_paths.data_dir)
    roots.append(Path(context.repo_root) / "data")
    return roots


def _prompt_highlight_data_file(context: WebSessionContext, *parts: str) -> Path:
    for root in _tag_data_roots(context):
        candidate = root.joinpath(*parts)
        if candidate.exists():
            return candidate
    roots = _tag_data_roots(context)
    return roots[0].joinpath(*parts) if roots else Path(*parts)


def _prompt_highlight_norm_tag(value: Any) -> str:
    return (
        str(value or "")
        .replace("\\(", "(")
        .replace("\\)", ")")
        .replace("_", " ")
        .strip()
        .lower()
    )


def _prompt_highlight_add_tags(target: set[str], values: Any) -> None:
    if not values:
        return
    for value in values:
        tag = _prompt_highlight_norm_tag(value)
        if tag:
            target.add(tag)


def _prompt_highlight_read_json_tags(path: Path) -> set[str]:
    tags: set[str] = set()
    if not path.exists():
        return tags
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        def _collect_tag_lists(node: Any, depth: int = 0) -> None:
            if depth > 4:
                return
            if isinstance(node, list):
                _prompt_highlight_add_tags(tags, node)
                return
            if not isinstance(node, dict):
                return
            for key in ("tags", "modifiers", "uncategorized"):
                if isinstance(node.get(key), list):
                    _prompt_highlight_add_tags(tags, node.get(key))
            for key in ("groups", "categories", "regions"):
                value = node.get(key)
                if isinstance(value, dict):
                    for child in value.values():
                        _collect_tag_lists(child, depth + 1)
                elif isinstance(value, list):
                    _prompt_highlight_add_tags(tags, value)

        if isinstance(data, dict):
            _collect_tag_lists(data)
        elif isinstance(data, list):
            _prompt_highlight_add_tags(tags, data)
    except Exception as exc:
        print(f"Remote: prompt highlight taglist load failed ({path}): {exc}")
    return tags


def prompt_highlight_index(context: WebSessionContext) -> dict[str, Any]:
    raw_tags = getattr(context, "kr_tags_raw", None)
    if not isinstance(raw_tags, dict) or not raw_tags:
        from core.kr_tag_loader import load_kr_tag_records
        from core.tag_relation_ranker import TagRelationRanker

        load_result = load_kr_tag_records(context.repo_root, data_roots=_tag_data_roots(context))
        raw_tags = load_result.raw
        context.kr_tags_raw = raw_tags
        context.tag_relation_ranker = TagRelationRanker(raw_tags) if raw_tags else None
    if not isinstance(raw_tags, dict):
        raw_tags = {}

    raw_id = id(raw_tags)
    cached = getattr(context, "_prompt_highlight_index_cache", None)
    cached_raw_id = getattr(context, "_prompt_highlight_index_cache_raw_id", None)
    if isinstance(cached, dict) and cached_raw_id == raw_id:
        return cached

    high_value: set[str] = set()
    high_value.update(_prompt_highlight_read_json_tags(_prompt_highlight_data_file(context, "taglist", "expression_tags.json")))
    high_value.update(_prompt_highlight_read_json_tags(_prompt_highlight_data_file(context, "taglist", "pose_action_tags.json")))

    mid_value: set[str] = set()
    mid_value.update(_prompt_highlight_read_json_tags(_prompt_highlight_data_file(context, "taglist", "object_tags.json")))
    mid_value.update(_prompt_highlight_read_json_tags(_prompt_highlight_data_file(context, "taglist", "clothing_regions.json")))
    clothes_path = _prompt_highlight_data_file(context, "clothes_list.txt")
    if clothes_path.exists():
        try:
            with open(clothes_path, "r", encoding="utf-8") as f:
                _prompt_highlight_add_tags(mid_value, [line.strip() for line in f if line.strip()])
        except Exception as exc:
            print(f"Remote: prompt highlight clothes list load failed: {exc}")

    artist_tags: set[str] = set()
    character_tags: set[str] = set()
    copyright_tags: set[str] = set()
    known_tags: set[str] = set()
    for tag_lower, info in raw_tags.items():
        if not isinstance(info, dict):
            continue
        tag = _prompt_highlight_norm_tag(info.get("_tag", tag_lower))
        if not tag:
            continue
        cat = str(info.get("_cat", "") or "")
        if cat == "artist":
            artist_tags.add(tag)
        elif cat == "character":
            character_tags.add(tag)
        elif cat == "copyright":
            copyright_tags.add(tag)
        else:
            known_tags.add(tag)

    known_tags.update(high_value)
    known_tags.update(mid_value)
    known_tags.update(_prompt_highlight_read_json_tags(_prompt_highlight_data_file(context, "taglist", "style_meta_tags.json")))
    known_tags.difference_update(artist_tags)
    known_tags.difference_update(character_tags)
    known_tags.difference_update(copyright_tags)

    payload = {
        "version": "runtime-loaded",
        "highValueTags": sorted(high_value),
        "midValueTags": sorted(mid_value),
        "knownTags": sorted(known_tags),
        "artistTags": sorted(artist_tags),
        "characterTags": sorted(character_tags),
        "copyrightTags": sorted(copyright_tags),
        "stats": {
            "high": len(high_value),
            "mid": len(mid_value),
            "known": len(known_tags),
            "artists": len(artist_tags),
            "characters": len(character_tags),
            "copyrights": len(copyright_tags),
        },
    }
    context._prompt_highlight_index_cache = payload
    context._prompt_highlight_index_cache_raw_id = raw_id
    return payload


def _companion_map(context: WebSessionContext) -> dict[str, list[str]]:
    """`data/tag_cooccurrence.json` 의 동반 사전. 한 번 읽어 컨텍스트에 캐시한다.

    605KB / 9,928 태그라 요청마다 읽을 것이 아니다. 파일이 없으면 빈 사전 —
    아직 빌더를 안 돌린 설치본에서 조회가 죽지 않게 한다.
    """
    cached = getattr(context, "_tag_companion_map", None)
    if cached is not None:
        return cached
    table: dict[str, list[str]] = {}
    try:
        root = Path(getattr(context, "repo_root", "."))
        path = root / "data" / "tag_cooccurrence.json"
        if path.exists():
            doc = json.loads(path.read_text(encoding="utf-8"))
            for key, vals in (doc.get("companions") or {}).items():
                if isinstance(vals, list):
                    table[str(key).strip().lower()] = [str(v) for v in vals]
    except Exception:
        table = {}
    context._tag_companion_map = table
    return table


def _recommendable(context, raw_tags):
    """사전 칩으로 **권할 값이 있는 태그인가**를 판정하는 술어를 만든다.

    전수 조사(2026-08-01): 그리드 태그 10,116개의 추천 4줄에서 그림 없는 칩이
    2,299종 11,380회 나왔다. 그중 상당수는 그림이 없는 게 아니라 **애초에 권할
    값이 없는 것**이었다.

      · freq < 300      그리드 축의 절단선과 같다. 축에 못 들어갈 태그를 칩으로
                        권할 이유가 없다(1,351종 2,198회).
      · 작품명 괄호      `gem uniform (houseki no kuni)` 가 혼자 173회 나왔다.
                        특정 작품 전용이라 다른 캐릭터에 걸면 안 맞는다.
                        **괄호를 통째로 막지 않는다** — `orange (fruit)`·
                        `pokemon (creature)`·`pearl (gemstone)` 은 일반명의
                        동음이의 표기다. 괄호 안이 작품/캐릭터 태그일 때만 뺀다.
      · 결함 태그        `bad anatomy`·`bad proportions`. 네거티브에 있는 것을
                        권하는 꼴이다.

    `manly` 같은 주관 태그는 **빼지 않는다.** 유의미하다는 사용자 지적이 있었고,
    실제로 `subjective` 서브그룹에는 `hot`·`cold`·`motherly` 처럼 그릴 수 있는
    것이 섞여 있다 — 서브그룹 단위로 자르면 그것들까지 날아간다.
    """
    cache = getattr(context, "_recommendable_cache", None)
    if cache is None:
        cache = {}
        context._recommendable_cache = cache

    def ok(tag: str) -> bool:
        key = str(tag).strip().lower()
        hit = cache.get(key)
        if hit is not None:
            return hit
        rec = raw_tags.get(key) or {}
        verdict = True
        if int(rec.get("freq", 0) or 0) < 300:
            verdict = False
        elif key.startswith("bad "):
            verdict = False
        elif "(" in key and key.endswith(")"):
            inner = key[key.rindex("(") + 1:-1].strip()
            owner = raw_tags.get(inner) or {}
            # group 은 `작품 > 만화`·`캐릭터 > 게임` 처럼 계층 표기라 정확히 비교하면
            # 안 걸린다(실측: houseki no kuni 가 통과했다). 첫 마디로 본다.
            head = str(owner.get("group", "") or "").split(">")[0].strip().lower()
            if head in ("copyright", "character", "artist", "작품", "캐릭터", "작가"):
                verdict = False
        cache[key] = verdict
        return verdict

    return ok


def tag_lookup_info(context: WebSessionContext, tag: str) -> dict[str, Any]:
    raw_tags = getattr(context, "kr_tags_raw", None)
    if not isinstance(raw_tags, dict) or not raw_tags:
        from core.kr_tag_loader import load_kr_tag_records

        load_result = load_kr_tag_records(context.repo_root, data_roots=_tag_data_roots(context))
        raw_tags = load_result.raw
        context.kr_tags_raw = raw_tags
    if not raw_tags:
        return {}
    # **랭커 생성은 raw 적재와 분리해야 한다.** 전에는 위 `if` 안에서만 만들었는데,
    # `autocomplete_commands.py` 가 시작 시 `context.kr_tags_raw` 를 먼저 채우면 그 블록을
    # 건너뛰어 랭커가 영영 None 이었다. 그러면 아래 폴백(원본 siblings+word_match 를
    # 필터 없이 이어붙이는 경로)이 돌아, `muscular` 의 "비슷한 것" 에 `loli` 가 나왔다.
    # 즉 랭커의 모든 필터링이 런타임에서 한 번도 동작한 적이 없었다(실측 2026-07-30).
    ranker = getattr(context, "tag_relation_ranker", None)
    if ranker is None:
        from core.tag_relation_ranker import TagRelationRanker

        ranker = TagRelationRanker(raw_tags)
        context.tag_relation_ranker = ranker
    tag_lower = re.sub(r"\\([()])", r"\1", str(tag or "").strip()).lower()
    info = raw_tags.get(tag_lower)
    if not info:
        return {}
    result = {
        "tag": info.get("_tag", tag),
        "count": info.get("freq", 0),
        "desc": info.get("description", ""),
        "group": info.get("group", ""),
        "subgroup": info.get("subgroup", ""),
        "cat": info.get("_cat", ""),
    }
    keep = _recommendable(context, raw_tags)
    relations = info.get("relations", {}) if isinstance(info.get("relations"), dict) else {}
    parents = relations.get("parent", [])
    if isinstance(parents, str):
        parents = [parents]
    if ranker is not None:
        parents = ranker.valid_implications(tag_lower, info, limit=8)
        parents = [x for x in parents if keep(x)]
    if parents:
        result["implications"] = parents[:8]
    if ranker is not None:
        # '더 구체적인 것'(children)은 '비슷한 것'과 성격이 달라 목록을 나눠 보낸다 —
        # 전에는 한 통에 섞였고 children 이 최고점이라 siblings 를 밀어냈다
        # (Codex 전수조사 2026-07-30: children 보유 태그의 99.94%에서 첫 칩이 children).
        specific = ranker.rank_specific(tag_lower, info, limit=8)
        specific = [x for x in specific if keep(x)]
        if specific:
            result["specific"] = specific
        related = ranker.rank_related(tag_lower, info, limit=8)
        related = [x for x in related if keep(x)]
    else:
        # 랭커가 없으면 **아무것도 내보내지 않는다.** 전에는 원본 `siblings` +
        # `word_match` 를 필터 없이 이어붙였는데, 그것이 `no panties` 를 `panties` 의
        # "비슷한 것" 으로, `loli` 를 `muscular` 의 "비슷한 것" 으로 내놓던 경로다.
        # 사용자가 그 칩을 눌러 프롬프트에 넣는 자리이므로 빈 목록이 낫다.
        related = []
    if related:
        result["related"] = related[:8]
    # ── 함께 쓰이는 것(동반) ────────────────────────────────────────────────
    # 위 세 줄은 태그 **사전**의 관계다. 랭커를 바로잡은 뒤 freq>=1000 태그의 65.4%가
    # 셋 다 비었다 — 근거 없는 유사어를 안 내놓기로 한 결과지만, 사용자에게는 "정보창이
    # 안 뜬다" 로 보인다. 사전에 관계가 없을 뿐 **실제 게시물에는 함께 쓰인 태그가 있다.**
    # 그래서 이벤트 코퍼스 449만 건에서 오프라인으로 뽑아 둔 것을 네 번째 줄로 낸다.
    # 위 세 줄과 겹치는 후보, 성인/작가/캐릭터/메타 분류, 배경이 너무 흔한 후보는
    # 빌더가 미리 걷었다(tools/build_tag_cooccurrence.py). 근거 없으면 **빈 목록**이다.
    companions = _companion_map(context).get(tag_lower)
    if companions:
        companions = [x for x in companions if keep(x)]
    if companions:
        result["companions"] = list(companions)[:8]
    extra_info = {}
    for extra_tag in (list(result.get("implications", [])) + list(result.get("related", []))
                      + list(result.get("companions", []))):
        extra = raw_tags.get(str(extra_tag).strip().lower())
        if not extra:
            continue
        extra_info[str(extra_tag)] = {
            "tag": extra.get("_tag", str(extra_tag)),
            "count": extra.get("freq", 0),
            "desc": extra.get("description", ""),
            "group": extra.get("group", ""),
            "subgroup": extra.get("subgroup", ""),
            "cat": extra.get("_cat", ""),
        }
    if extra_info:
        result["extra_tag_info"] = extra_info
    if result.get("cat") == "character":
        try:
            from app.backend.server.character_viewer_routes import character_viewer_service

            match = character_viewer_service(context).find_by_tag(tag)
            if match is not None:
                group_key, cdata = match
                distribution = ((cdata.get("breast_size") or {}).get("distribution") or [])
                bs_top = ""
                if isinstance(distribution, list) and distribution:
                    valid_distribution = [entry for entry in distribution if isinstance(entry, dict)]
                    if valid_distribution:
                        best = max(valid_distribution, key=lambda entry: float(entry.get("pct") or 0))
                        bs_top = str(best.get("tag") or "")
                result["character_details"] = {
                    "copyright": group_key,
                    "personal_color": cdata.get("personal_color", []),
                    "characteristics": cdata.get("characteristics", []),
                    "breast_size_top": bs_top,
                    "total_rows": cdata.get("total_rows", 0),
                }
        except Exception:
            pass
    return result


def _preview_path(context: WebSessionContext, preset_name: str, mode: str = "") -> Path | None:
    # 파일 탐색 로직은 core로 이동 — 상태 요약(preset_summary)과 이 라우트가
    # 같은 해석을 공유해야 "파일은 있는데 항상 No image"가 재발하지 않는다.
    from core.prompt_engineering_settings import preset_preview_file

    mode_key = _normalize_preset_mode(context, mode, allow_empty=True)
    return preset_preview_file(context, preset_name, mode_key)


def _normalize_preset_mode(
    context: WebSessionContext,
    mode: str = "",
    *,
    allow_empty: bool = False,
) -> str:
    value = str(mode or "").strip().upper()
    if not value:
        if allow_empty:
            return ""
        current_mode = str(context.get_api_mode() or "").strip().upper()
        return current_mode if current_mode in PROMPT_ENGINEERING_PRESET_MODES else "NAI"
    if value not in PROMPT_ENGINEERING_PRESET_MODES:
        raise ValueError("Invalid preset mode")
    return value


def _thumbnail_target(context: WebSessionContext, preset_name: str) -> Path:
    safe_name = Path(str(preset_name or "").strip()).name
    if not safe_name or safe_name == "*randomized":
        raise ValueError("Preset name is required")
    target_dir = context._save_path("presets", "previews")
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{safe_name}.png"


def _thumbnail_update_payload(context: WebSessionContext, preset_name: str, mode: str = "") -> dict[str, Any]:
    safe_name = Path(str(preset_name or "").strip()).name
    mode_key = _normalize_preset_mode(context, mode, allow_empty=True)
    target = _preview_path(context, safe_name, mode_key)
    if not target:
        target = _thumbnail_target(context, safe_name)
    version = int(target.stat().st_mtime) if target.exists() else int(time.time())
    return {
        "ok": True,
        "name": safe_name,
        "mode": mode_key,
        "has_thumbnail": target.exists(),
        "thumbnail_url": (
            f"/api/prompt-engineering/preset-thumbnail"
            f"?name={quote(safe_name, safe='')}&mode={quote(mode_key, safe='')}&v={version}"
        ),
    }


def save_prompt_engineering_thumbnail_bytes(
    context: WebSessionContext,
    preset_name: str,
    mode: str,
    image_bytes: bytes,
) -> dict[str, Any]:
    if not image_bytes:
        raise ValueError("Image payload is empty")
    if len(image_bytes) > 24 * 1024 * 1024:
        raise ValueError("Image is too large")
    from PIL import Image

    mode_key = _normalize_preset_mode(context, mode, allow_empty=True)
    target = _thumbnail_target(context, preset_name)
    with Image.open(io.BytesIO(image_bytes)) as opened:
        opened.load()
        opened.convert("RGBA").save(target, format="PNG")
    return _thumbnail_update_payload(context, preset_name, mode_key)


def _preset_file(context: WebSessionContext, preset_name: str, mode: str = "") -> Path | None:
    safe_name = Path(str(preset_name or "").strip()).name
    if not safe_name:
        return None
    mode_candidates: list[str] = []
    if mode:
        mode_candidates.append(_normalize_preset_mode(context, mode))
    current_mode = _normalize_preset_mode(context, context.get_api_mode(), allow_empty=True)
    if current_mode and current_mode not in mode_candidates:
        mode_candidates.append(current_mode)
    for fallback_mode in PROMPT_ENGINEERING_PRESET_MODES:
        if fallback_mode not in mode_candidates:
            mode_candidates.append(fallback_mode)
    for mode_name in mode_candidates:
        candidate = context._existing_save_path("presets", mode_name, f"{safe_name}.json")
        if candidate.exists():
            return candidate
    return None


def _thumbnail_generation_prompt(context: WebSessionContext, preset_name: str, mode: str = "") -> str:
    pieces: list[str] = []
    preset_file = _preset_file(context, preset_name, mode)
    if preset_file:
        try:
            data = json.loads(preset_file.read_text(encoding="utf-8"))
            settings = data.get("module_settings", {}) if isinstance(data, dict) else {}
            pre_prompt = str(settings.get("pre_prompt", "") or "").strip()
            if pre_prompt:
                pieces.append(pre_prompt)
        except Exception:
            pass
    pieces.append("1girl, original, solo, upper body")
    return ", ".join(piece for piece in pieces if piece)


def register_prompt_tools_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
    clients: set[Any],
    broadcast_json: JsonBroadcaster,
    start_generation_runner: GenerationRunnerStarter,
) -> None:

    @app.get("/api/prompt-highlight-index")
    async def api_prompt_highlight_index():
        try:
            data = await run_in_thread(prompt_highlight_index, session_context)
        except Exception:
            data = prompt_highlight_empty_index()
        return Response(
            content=json.dumps(data, ensure_ascii=False),
            media_type="application/json",
            headers=_no_cache_headers(),
        )

    @app.get("/api/tag/lookup")
    async def api_tag_lookup(tag: str = ""):
        try:
            return await run_in_thread(tag_lookup_info, session_context, tag)
        except Exception as exc:
            return JSONResponse({"error": f"Tag lookup failed: {exc}"}, status_code=500)

    @app.get("/api/prompt-engineering/preset-thumbnail")
    async def api_prompt_engineering_preset_thumbnail(name: str = "", mode: str = "", v: str = ""):
        try:
            target = await run_in_thread(_preview_path, session_context, name, mode)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if not target:
            return JSONResponse({"error": "Preset thumbnail not found"}, status_code=404)
        return FileResponse(
            str(target),
            media_type=_image_media_type_for_path(target),
            headers=_no_cache_headers(),
        )

    @app.post("/api/prompt-engineering/preset-thumbnail/upload")
    async def api_prompt_engineering_preset_thumbnail_upload(req: Request, name: str = "", mode: str = ""):
        try:
            image_bytes = await req.body()
            payload = await run_in_thread(
                save_prompt_engineering_thumbnail_bytes,
                session_context,
                name,
                mode,
                image_bytes,
            )
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Preset thumbnail upload failed: {exc}"}, status_code=500)
        await broadcast_json(clients, {
            "type": "prompt_engineering_preset_thumbnail_updated",
            **payload,
        })
        return payload

    @app.post("/api/prompt-engineering/preset-thumbnail/generate")
    async def api_prompt_engineering_preset_thumbnail_generate(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            name = Path(str(payload.get("name") or "").strip()).name
            mode = _normalize_preset_mode(session_context, payload.get("mode") or "")
            if not name or name == "*randomized":
                raise ValueError("Preset name is required")
            if not _preset_file(session_context, name, mode):
                raise FileNotFoundError(f"Preset not found: {name}")
            request_id = str(payload.get("request_id") or uuid.uuid4().hex)
            prompt = _thumbnail_generation_prompt(session_context, name, mode)
            overrides = {
                "input": prompt,
                "_raw_input": prompt,
                "negative_prompt": session_context.negative_prompt_text,
                "width": 1088,
                "height": 960,
                "random_resolution": False,
                "prompt_preset_thumbnail_request": True,
                "prompt_preset_thumbnail_request_id": request_id,
                "prompt_preset_thumbnail_name": name,
                "prompt_preset_thumbnail_mode": mode,
                "_skip_vibe_transfer_late_binding": True,
                "_remote_queue_source": "Preset Thumb",
                "_remote_queue_label": name,
            }
            dispatch = await run_in_thread(
                _generation_service(session_context).enqueue_remote_request,
                {"type": "generate", "overrides": overrides},
            )
        except FileNotFoundError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Preset thumbnail generation failed: {exc}"}, status_code=500)
        if not dispatch.ok:
            return JSONResponse(dispatch.websocket_payload(), status_code=409)
        await broadcast_json(clients, session_context.queue_state_payload())
        if session_context.headless_generation_execute_enabled:
            start_generation_runner(session_context, clients)
        return {
            "ok": True,
            "status": "generation_requested",
            "request_id": request_id,
            "name": name,
            "mode": mode,
            "vibe_active": False,
            "vibe_count": 0,
            "message": f"{name} 임시 썸네일 생성을 요청했습니다.",
        }
