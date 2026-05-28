from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import WebSocket

from app.backend.server.preset_services import (
    clothes_preset_service,
    event_preset_service,
    expression_preset_service,
)
from app.backend.server.prompt_tools_routes import tag_lookup_info
from core.web_session_context import WebSessionContext
from utils.translator import english_to_korean, korean_to_english


AsyncRunner = Callable[..., Awaitable[Any]]

AUTOCOMPLETE_COMMAND_TYPES = {
    "tag_search",
    "tag_filter_ac",
    "autocomplete",
    "autocomplete_translate",
    "autocomplete_wildcard",
    "autocomplete_chunk",
    "autocomplete_vibe_cluster",
    "autocomplete_preset",
    "tag_lookup",
    "translate_text",
}


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


def _tag_data_roots(context: WebSessionContext) -> list[Path]:
    roots: list[Path] = []
    runtime_paths = getattr(context, "runtime_paths", None)
    if runtime_paths is not None:
        roots.append(runtime_paths.data_dir)
    roots.append(Path(context.repo_root) / "data")
    return roots


def ensure_tag_search_index(context: WebSessionContext):
    index = getattr(context, "tag_search_index", None)
    if index is not None:
        return index
    from core.kr_tag_loader import load_kr_tag_records
    from core.tag_search_index import TagSearchIndex

    result = load_kr_tag_records(context.repo_root, data_roots=_tag_data_roots(context))
    context.kr_tags_raw = result.raw
    context.autocomplete_state.kr_tags_loaded = bool(result.raw)
    index = TagSearchIndex.from_raw_tag_records(result.raw)
    context.tag_search_index = index
    return index


def _autocomplete_row(result: Any) -> dict[str, Any]:
    entry = result.entry
    return {
        "tag": result.tag,
        "count": int(getattr(entry, "freq", 0) or 0),
        "desc": getattr(entry, "desc", "") or "",
        "group": getattr(entry, "category", "") or "",
        "cat": getattr(entry, "cat", "") or "",
    }


def search_kr_tags(context: WebSessionContext, query: str, limit: int = 20) -> list[dict[str, Any]]:
    from core.tag_search_index import normalize_search_query

    raw_query = str(query or "")
    q = normalize_search_query(raw_query)
    if not q:
        return []
    cats = None
    if q.startswith("@"):
        cats = {"artist"}
        q = normalize_search_query(q[1:])
    else:
        for prefix in ("artist:", "character:"):
            if q.startswith(prefix):
                cats = {prefix[:-1]}
                q = normalize_search_query(q[len(prefix):])
                break
    if not q:
        return []
    index = ensure_tag_search_index(context)
    rows = [_autocomplete_row(result) for result in index.search_autocomplete(q, limit=limit, cats=cats)]
    if len(rows) < limit and re.search(r"[가-힣ㄱ-ㅎㅏ-ㅣ]", raw_query):
        seen = {row["tag"] for row in rows}
        for result in index.search_metadata_fallback(q, limit=limit, exclude_noisy_categories=True):
            row = _autocomplete_row(result)
            if row["tag"] in seen:
                continue
            seen.add(row["tag"])
            rows.append(row)
            if len(rows) >= limit:
                break
    return rows[:limit]


def _has_hangul_text(text: str) -> bool:
    return bool(re.search(r"[가-힣ㄱ-ㅎㅏ-ㅣ]", str(text or "")))


def _translate_autocomplete_query(context: WebSessionContext, query: str) -> str:
    from core.tag_search_index import normalize_search_query

    normalized = normalize_search_query(query)
    if not normalized or not _has_hangul_text(normalized):
        return ""
    cache = getattr(context, "autocomplete_translation_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        context.autocomplete_translation_cache = cache
    cached = cache.get(normalized)
    if cached is not None:
        return str(cached)
    translated = normalize_search_query(korean_to_english(normalized) or "")
    if not translated or _has_hangul_text(translated) or translated == normalized:
        translated = ""
    if len(cache) > 256:
        cache.clear()
    cache[normalized] = translated
    return translated


def _translation_hint_row(translated: str) -> dict[str, Any]:
    return {
        "tag": translated,
        "count": 0,
        "desc": "translation hint",
        "group": "[translation hint]",
        "cat": "",
        "_wc_type": "fallback_recommended",
        "_fallback_recommended": True,
        "candidate": {
            "type": "translation_hint",
            "source": "translation_fallback",
            "confidence": 0.2,
            "insertPolicy": "manual",
        },
        "candidateType": "translation_hint",
        "source": "translation_fallback",
        "confidence": 0.2,
        "insertPolicy": "manual",
    }


def search_kr_tags_with_translation(
    context: WebSessionContext,
    query: str,
    limit: int = 20,
) -> tuple[list[dict[str, Any]], str]:
    from core.tag_search_index import normalize_search_query

    translated = _translate_autocomplete_query(context, query)
    base_rows = search_kr_tags(context, query, limit)
    if not translated:
        return base_rows, ""

    merged: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []

    def add_row(row: dict[str, Any], *, translated_match: bool = False) -> None:
        tag = str(row.get("tag") or "")
        key = normalize_search_query(tag)
        if not key or key in merged:
            return
        item = dict(row)
        if translated_match:
            item["_translated"] = True
            item.setdefault("candidateType", "tag_translated")
            item.setdefault("source", "translation_search")
            item.setdefault("confidence", 0.75)
            item.setdefault("insertPolicy", "default")
            candidate = dict(item.get("candidate") or {})
            candidate.setdefault("type", item["candidateType"])
            candidate.setdefault("source", item["source"])
            candidate.setdefault("confidence", item["confidence"])
            candidate.setdefault("insertPolicy", item["insertPolicy"])
            item["candidate"] = candidate
        merged[key] = item
        rows.append(item)

    for row in search_kr_tags(context, translated, limit):
        add_row(row, translated_match=True)
    for row in base_rows:
        add_row(row)

    translated_key = normalize_search_query(translated)
    if translated_key and translated_key not in merged:
        hint_row = _translation_hint_row(translated)
        if len(rows) >= limit:
            rows = rows[:max(0, limit - 1)] + [hint_row]
        else:
            add_row(hint_row)
    return rows[:limit], translated


def search_wildcards(context: WebSessionContext, query: str, limit: int = 12) -> list[dict[str, Any]]:
    # 빈 쿼리(`__` 만 입력)도 허용 → 전체 와일드카드 상위 N개를 나열한다.
    q = str(query or "").strip().lower()
    base = context._wildcard_base_dir()
    if not base.exists():
        return []
    # 1) 경로만 먼저 수집/필터 (entries 파일 읽기는 상위 N개로 지연 — 빈 쿼리 성능)
    matched: list[tuple[str, Any]] = []
    for path in base.rglob("*.txt"):
        try:
            rel = path.relative_to(base).with_suffix("").as_posix()
        except Exception:
            continue
        if q and q not in rel.lower():
            continue
        matched.append((rel, path))
    if q:
        matched.sort(key=lambda rp: (rp[0].lower() != q, not rp[0].lower().startswith(q), rp[0].lower()))
    else:
        matched.sort(key=lambda rp: rp[0].lower())
    # 2) 상위 N개만 entries 카운트
    results: list[dict[str, Any]] = []
    for rel, path in matched[:limit]:
        try:
            entries = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except Exception:
            entries = []
        results.append({
            "tag": rel,
            "count": len(entries),
            "desc": f"{len(entries)} entries",
            "group": "wildcard",
            "cat": "",
            "_wc_type": "wildcard",
        })
    return results


def search_chunks(context: WebSessionContext, query: str, limit: int = 12) -> list[dict[str, Any]]:
    store = context._instant_wildcard_store()
    tree = dict(store.get("instant_wildcard_tree") or {})
    raw = str(query or "").strip()
    if raw.startswith("$"):
        raw = raw[1:].strip()
    q = raw.lower()

    def preview(value: Any, max_len: int = 96) -> str:
        text = str(value or "").replace("\n", " ").strip()
        return text[:max_len] + "..." if len(text) > max_len else text

    def rank(text: str) -> int | None:
        haystack = str(text or "").lower()
        if not q:
            return 4
        if haystack == q:
            return 0
        if haystack.startswith(q):
            return 1
        if q in haystack:
            return 2
        return None

    rows: list[tuple[int, int, dict[str, Any]]] = []
    if ":" in raw:
        group_name, item_query = raw.split(":", 1)
        q = item_query.strip().lower()
        groups = [(name, items) for name, items in tree.items() if str(name).lower() == group_name.strip().lower()]
    else:
        groups = list(tree.items())
    index = 0
    for group_name, items in groups:
        group_rank = rank(group_name)
        if group_rank is not None and ":" not in raw:
            rows.append((group_rank, index, {
                "tag": str(group_name),
                "value": f"${group_name}:",
                "count": len(items or {}),
                "desc": f"{len(items or {})} entries",
                "group": "chunk group",
                "cat": "",
                "_wc_type": "chunk_group",
            }))
            index += 1
        if isinstance(items, dict):
            for key, value in items.items():
                item_rank = min([r for r in (rank(key), rank(value)) if r is not None], default=None)
                if item_rank is None:
                    continue
                rows.append((item_rank, index, {
                    "tag": str(key),
                    "value": str(value or ""),
                    "count": 0,
                    "desc": preview(value),
                    "group": str(group_name),
                    "cat": "",
                    "preview": str(value or ""),
                    "_wc_type": "chunk",
                }))
                index += 1
    rows.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in rows[:limit]]


def preset_autocomplete_payload(
    context: WebSessionContext,
    query: str,
    limit: int = 12,
    preset_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        from core.preset_input_bridge import PresetInputBridge, update_app_preset_context

        token = str(query or "").strip()
        if not token.lower().startswith("preset:"):
            token = "preset:" + token
        preset_context = update_app_preset_context(
            context,
            preset_context if isinstance(preset_context, dict) else {},
            source="autocomplete",
        )
        bridge = getattr(context, "preset_autocomplete_bridge", None)
        if bridge is None:
            bridge = PresetInputBridge(
                Path(context.repo_root),
                event_service=event_preset_service(context),
                clothes_service=clothes_preset_service(context),
                expression_service=expression_preset_service(context),
                context=preset_context,
            )
            context.preset_autocomplete_bridge = bridge
        elif hasattr(bridge, "set_context"):
            bridge.set_context(preset_context)
        payload = bridge.suggest(token, limit=limit)
        rows = payload.get("suggestions") or []
        secondary = payload.get("secondaryResults") or payload.get("secondarySuggestions") or []
        if payload.get("stage") in {"loading", "unavailable"}:
            state = payload.get("loadState") or {}
            rows = [{
                "tag": str(state.get("main") or payload.get("stage") or "preset"),
                "value": token,
                "count": 0,
                "desc": str(state.get("message") or "Preset data is not ready."),
                "group": "preset",
                "cat": "preset",
                "_wc_type": "preset_status",
                "disabled": True,
            }]
            secondary = []
        return {
            "query": token,
            "results": rows,
            "secondaryResults": secondary,
            "preset": {
                "axis": payload.get("axis") or "",
                "stage": payload.get("stage") or "",
                "context": payload.get("presetContext") or preset_context,
                "loadState": payload.get("loadState") or {},
                "dataReady": bool(payload.get("dataReady")),
                "secondaryResults": secondary,
            },
        }
    except Exception as exc:
        print(f"Headless Remote: preset autocomplete failed - {exc}", flush=True)
        return {"query": str(query or ""), "results": [], "secondaryResults": [], "preset": {}}


async def handle_autocomplete_command(
    ws: WebSocket,
    context: WebSessionContext,
    command: dict[str, Any],
    *,
    run_in_thread: AsyncRunner,
) -> bool:
    command_type = str(command.get("type") or "").strip()
    if command_type not in AUTOCOMPLETE_COMMAND_TYPES:
        return False

    query = str(command.get("query") or "")
    if command_type == "tag_search":
        results = await run_in_thread(search_kr_tags, context, query, 20)
        await _send_json(ws, {"type": "tag_search_result", "query": query, "results": results})
        return True

    if command_type == "tag_filter_ac":
        results = await run_in_thread(search_kr_tags, context, query, 12)
        await _send_json(ws, {"type": "tag_filter_ac_result", "query": query, "results": results})
        return True

    if command_type == "autocomplete":
        results = await run_in_thread(search_kr_tags, context, query, 12)
        await _send_json(ws, {"type": "autocomplete_result", "query": query, "results": results})
        return True

    if command_type == "autocomplete_translate":
        request_id = str(command.get("requestId") or command.get("request_id") or "")
        results, translated = await run_in_thread(search_kr_tags_with_translation, context, query, 12)
        payload = {
            "type": "autocomplete_result",
            "query": query,
            "results": results,
            "translated_query": translated,
        }
        if request_id:
            payload["requestId"] = request_id
        await _send_json(ws, payload)
        return True

    if command_type == "autocomplete_wildcard":
        results = await run_in_thread(search_wildcards, context, query, 12)
        await _send_json(ws, {"type": "autocomplete_result", "query": query, "results": results})
        return True

    if command_type == "autocomplete_chunk":
        results = await run_in_thread(search_chunks, context, query, 12)
        await _send_json(ws, {"type": "autocomplete_result", "query": query, "results": results})
        return True

    if command_type == "autocomplete_vibe_cluster":
        from core.vibe_cluster_resolver import search_vibe_clusters

        results = await run_in_thread(
            search_vibe_clusters,
            query,
            12,
            context._existing_save_path("vibe_transfer_clusters"),
        )
        await _send_json(ws, {"type": "autocomplete_result", "query": query, "results": results})
        return True

    if command_type == "autocomplete_preset":
        payload = await run_in_thread(
            preset_autocomplete_payload,
            context,
            query,
            12,
            command.get("presetContext") if isinstance(command.get("presetContext"), dict) else command.get("context"),
        )
        await _send_json(ws, {
            "type": "autocomplete_result",
            "query": payload.get("query", query),
            "results": payload.get("results", []),
            "secondaryResults": payload.get("secondaryResults", []),
            "preset": payload.get("preset") or {},
        })
        return True

    if command_type == "translate_text":
        request_id = str(command.get("requestId") or command.get("request_id") or "")
        direction = str(command.get("direction") or "ko_en").strip().lower()
        text = str(command.get("text") or command.get("query") or "")
        translator = english_to_korean if direction in {"en_ko", "en-ko", "en2ko"} else korean_to_english
        try:
            translated = await run_in_thread(translator, text)
            payload = {
                "type": "translation_result",
                "text": text,
                "translated": translated or "",
                "direction": "en_ko" if translator is english_to_korean else "ko_en",
                "ok": bool(translated),
            }
        except Exception as exc:
            payload = {
                "type": "translation_result",
                "text": text,
                "translated": "",
                "direction": "en_ko" if translator is english_to_korean else "ko_en",
                "ok": False,
                "error": str(exc),
            }
        if request_id:
            payload["requestId"] = request_id
        await _send_json(ws, payload)
        return True

    info = await run_in_thread(tag_lookup_info, context, str(command.get("tag") or ""))
    await _send_json(ws, {"type": "tag_lookup_result", **info})
    return True
