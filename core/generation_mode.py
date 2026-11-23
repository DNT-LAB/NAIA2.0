"""Identify the generation backend recorded on a history item or image."""

import json
import re


MODES = ("NAI", "WEBUI", "COMFYUI", "ANIMA")


def mode_from_generation_params(params: dict | None, api_metadata: dict | None = None) -> str:
    try:
        params = params or {}
        api_metadata = api_metadata or {}
        if params.get("_anima_meta") or params.get("_comfyui_workflow_mode") == "managed":
            return "ANIMA"
        # History items record the engine that actually ran (the request itself only says COMFYUI).
        recorded_mode = str(api_metadata.get("generation_mode") or "").upper()
        if recorded_mode == "ANIMA":
            return "ANIMA"
        # Imported images are tagged with the mode that was active when they were
        # pasted in, not the mode that made them - let the embedded metadata decide, or the mode
        # read from the original file before it was converted to PNG (EXIF is lost on conversion).
        if params.get("imported_external"):
            return recorded_mode if recorded_mode in MODES else ""
        recorded = params.get("api_mode") or api_metadata.get("backend") or api_metadata.get("api_mode")
        mode = str(recorded or "").upper()
        return mode if mode in ("NAI", "WEBUI", "COMFYUI") else ""
    except Exception:
        return ""


def _json_object(value) -> dict | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, (str, bytes)):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, RecursionError):
            pass
    return None


_WEBUI_STEPS = re.compile(r"(?:^|[\n,])\s*Steps:\s*\d+")


def _looks_like_webui_parameters(value) -> bool:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    return isinstance(value, str) and bool(_WEBUI_STEPS.search(value))


def _is_novelai_software(chunks: dict) -> bool:
    return chunks.get("Software") in ("NovelAI", b"NovelAI")


def _looks_like_comfyui_graph(value) -> bool:
    # API graph: {"3": {"class_type": ...}, ...} / UI workflow: {"nodes": [...]}.
    data = _json_object(value)
    if not data:
        return False
    if isinstance(data.get("nodes"), list):
        return True
    return any(isinstance(node, dict) and "class_type" in node for node in data.values())


def _mode_from_extracted(extracted: dict, chunks: dict) -> str:
    # The extractor labels any parseable text with a type (a plain photo Comment becomes "nai", any
    # lowercase comment "webui", any JSON workflow chunk "comfyui"); only the tool's own record shape counts.
    kind = extracted.get("type")
    if kind == "comfyui":
        graphs = (extracted.get(key) for key in ("prompt_api", "workflow", "workflow_api"))
        return "COMFYUI" if any(_looks_like_comfyui_graph(graph) for graph in graphs) else ""
    if kind == "nai":
        comment = extracted.get("Comment")
        if _is_novelai_software(chunks) or (isinstance(comment, dict) and "prompt" in comment):
            return "NAI"
        # Text form ('"prompt": "..."' scraped from a Comment chunk or the stealth alpha payload). Plain text
        # chunks named "type" / "prompt" are merged into the extraction as-is - they are not that evidence.
        prompt = extracted.get("prompt")
        comment = chunks.get("Comment")
        from_comment = isinstance(comment, (str, bytes)) and '"prompt"' in (
            comment.decode("utf-8", errors="ignore") if isinstance(comment, bytes) else comment)
        from_stealth = "Comment" not in chunks and not any(key in chunks for key in ("type", "prompt"))
        return "NAI" if isinstance(prompt, str) and prompt.strip() and (from_comment or from_stealth) else ""
    if kind == "webui":
        params = extracted.get("parameters")
        steps = params.get("steps") if isinstance(params, dict) else None
        return "WEBUI" if isinstance(steps, int) and not isinstance(steps, bool) else ""
    return ""


def mode_from_image_metadata(info: dict | None, extracted: dict | None = None,
                             exif_user_comment: str | None = None) -> str:
    try:
        chunks = dict(info or {})
        for value in (*chunks.values(), exif_user_comment):
            wrapped = (_json_object(value) or {}).get("naia_png_text")
            if isinstance(wrapped, dict):
                chunks.update(wrapped)

        if "naia_profile" in chunks:
            return "ANIMA"
        params = _json_object(chunks.get("naia_generation_params"))
        if params is not None:
            mode = mode_from_generation_params(params, _json_object(chunks.get("naia_api_metadata")))
            if mode:
                return mode
        mode = _mode_from_extracted(extracted or {}, chunks)
        if mode:
            return mode
        # Chunk names alone are not proof (a photo can carry a plain Comment): the content must look
        # like that tool's own record.
        if _is_novelai_software(chunks) or "prompt" in (_json_object(chunks.get("Comment")) or {}):
            return "NAI"
        # The extractor mis-keys multi-line prompts ("hills\nsteps"); read the raw settings line instead.
        if any(_looks_like_webui_parameters(text) for text in (chunks.get("parameters"), chunks.get("comment"),
                                                                 exif_user_comment)):
            return "WEBUI"
        if any(_looks_like_comfyui_graph(chunks.get(key)) for key in ("prompt", "workflow", "workflow_api")):
            return "COMFYUI"
    except Exception:
        return ""
    return ""
