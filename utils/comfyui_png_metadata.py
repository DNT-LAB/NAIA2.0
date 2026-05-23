import io
import json
from copy import deepcopy
from typing import Any, Dict, Optional, Tuple

from PIL import Image
from PIL.PngImagePlugin import PngInfo


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "credential",
    "image_bytes",
    "mask_bytes",
    "password",
    "raw_bytes",
    "secret",
    "token",
}

WORKFLOW_KEYS = {
    "workflow",
    "workflow_api",
    "_comfyui_workflow_ui",
}

TEXT_PNG_KEYS = (
    "Title",
    "Author",
    "Description",
    "Software",
    "Source",
    "Comment",
    "Generation time",
    "parameters",
    "prompt",
    "workflow",
    "workflow_api",
    "naia_generation_params",
    "naia_prompt_context",
    "naia_api_metadata",
)


def _has_comfyui_workflow_metadata(metadata: Dict[str, Any]) -> bool:
    return bool(metadata.get("prompt") and (metadata.get("workflow") or metadata.get("workflow_api")))


def _normalize_comfyui_workflow_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    metadata = dict(metadata or {})
    if not metadata.get("prompt") and metadata.get("workflow_api"):
        metadata["prompt"] = metadata["workflow_api"]
    if metadata.get("prompt") and not (metadata.get("workflow") or metadata.get("workflow_api")):
        metadata["workflow_api"] = metadata["prompt"]
    return metadata


def _extract_prefixed_json_metadata_from_text(text: str) -> Dict[str, str]:
    metadata: Dict[str, str] = {}
    if not text:
        return metadata

    decoder = json.JSONDecoder()
    for key in ("prompt", "workflow", "workflow_api"):
        marker = f"{key}:"
        start = 0
        while True:
            marker_index = text.find(marker, start)
            if marker_index < 0:
                break
            value_start = marker_index + len(marker)
            while value_start < len(text) and text[value_start].isspace():
                value_start += 1
            try:
                _, value_end = decoder.raw_decode(text[value_start:])
            except Exception:
                start = value_start
                continue
            metadata[key] = text[value_start:value_start + value_end]
            break
    return metadata


def _extract_prefixed_json_metadata(value: Any) -> Dict[str, str]:
    text = _text_value(value)
    if text is None:
        return {}
    return _extract_prefixed_json_metadata_from_text(text)


def _copy_text_metadata(source_info: Dict[str, Any]) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}
    for key, value in (source_info or {}).items():
        if isinstance(value, bytes):
            text = _text_value(value)
            if text is not None and str(key) in {"prompt", "workflow", "workflow_api"}:
                metadata[str(key)] = text
            metadata.update(_extract_prefixed_json_metadata(value))
            continue
        metadata[str(key)] = value
        metadata.update(_extract_prefixed_json_metadata(value))
    return metadata


def _extract_webp_exif_metadata(image: Image.Image) -> Dict[str, str]:
    metadata: Dict[str, str] = {}
    try:
        exif = image.getexif()
    except Exception:
        return metadata

    for value in exif.values():
        text = _text_value(value)
        if not text or ":" not in text:
            continue
        key, payload = text.split(":", 1)
        key = key.strip()
        if key in {"prompt", "workflow", "workflow_api"} and payload:
            metadata[key] = payload
    return metadata


def extract_comfyui_workflow_metadata_from_image(image: Image.Image) -> Dict[str, Any]:
    metadata = _copy_text_metadata(dict(getattr(image, "info", {}) or {}))
    metadata.update(_extract_webp_exif_metadata(image))
    metadata = _normalize_comfyui_workflow_metadata(metadata)
    if not _has_comfyui_workflow_metadata(metadata):
        raise ValueError("No ComfyUI workflow metadata found in the selected image.")
    return metadata


def extract_comfyui_workflow_metadata_from_image_bytes(image_bytes: bytes) -> Dict[str, Any]:
    if not image_bytes:
        raise ValueError("No image data")

    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            return extract_comfyui_workflow_metadata_from_image(image)
    except ValueError as exc:
        fallback = _normalize_comfyui_workflow_metadata(_extract_prefixed_json_metadata(image_bytes))
        if _has_comfyui_workflow_metadata(fallback):
            return fallback
        raise exc
    except Exception as exc:
        raise ValueError(f"Image metadata parse failed: {exc}") from exc


def is_png_bytes(raw_bytes: Optional[bytes]) -> bool:
    return bool(raw_bytes and raw_bytes.startswith(PNG_SIGNATURE))


def json_dumps_for_png(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_safe_copy(value: Any, *, max_depth: int = 8) -> Any:
    if max_depth < 0:
        return str(value)
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            key_text = str(key)
            key_lower = key_text.lower()
            if key_text in WORKFLOW_KEYS:
                continue
            if key_lower in SENSITIVE_KEYS or any(marker in key_lower for marker in ("token", "secret", "password", "authorization", "api_key")):
                continue
            cleaned[key_text] = json_safe_copy(item, max_depth=max_depth - 1)
        return cleaned
    if isinstance(value, (list, tuple, set)):
        return [json_safe_copy(item, max_depth=max_depth - 1) for item in value]
    if isinstance(value, bytes):
        return f"<bytes {len(value)}>"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def _text_value(value: Any) -> Optional[str]:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    if isinstance(value, str) and value:
        return value
    return None


def _add_text(pnginfo: PngInfo, key: str, value: Any) -> bool:
    text = _text_value(value)
    if text is None and value is not None:
        try:
            text = json_dumps_for_png(value)
        except Exception:
            text = str(value)
    if not text:
        return False
    pnginfo.add_text(key, text)
    return True


def build_pnginfo(
    source_info: Optional[Dict[str, Any]] = None,
    *,
    workflow_api: Optional[Dict[str, Any]] = None,
    workflow_ui: Optional[Dict[str, Any]] = None,
    generation_params: Optional[Dict[str, Any]] = None,
    prompt_context: Optional[Dict[str, Any]] = None,
    api_metadata: Optional[Dict[str, Any]] = None,
) -> PngInfo:
    pnginfo = PngInfo()
    source_info = source_info or {}

    override_keys = set()
    if workflow_api:
        override_keys.update({"prompt", "workflow_api"})
    if workflow_ui:
        override_keys.add("workflow")
    if generation_params:
        override_keys.add("naia_generation_params")
    if prompt_context:
        override_keys.add("naia_prompt_context")
    if api_metadata:
        override_keys.add("naia_api_metadata")

    for key in TEXT_PNG_KEYS:
        if key in override_keys:
            continue
        if key in source_info:
            _add_text(pnginfo, key, source_info.get(key))

    if workflow_api:
        workflow_api_text = json_dumps_for_png(workflow_api)
        _add_text(pnginfo, "prompt", workflow_api_text)
        _add_text(pnginfo, "workflow_api", workflow_api_text)
    if workflow_ui:
        _add_text(pnginfo, "workflow", json_dumps_for_png(workflow_ui))

    if generation_params:
        _add_text(pnginfo, "naia_generation_params", json_dumps_for_png(json_safe_copy(generation_params)))
    if prompt_context:
        _add_text(pnginfo, "naia_prompt_context", json_dumps_for_png(json_safe_copy(prompt_context)))
    if api_metadata:
        _add_text(pnginfo, "naia_api_metadata", json_dumps_for_png(json_safe_copy(api_metadata)))

    if not source_info.get("Software") and (workflow_api or generation_params or prompt_context or api_metadata):
        _add_text(pnginfo, "Software", "NAIA2 ComfyUI")

    return pnginfo


def image_to_png_bytes(
    image: Image.Image,
    *,
    pnginfo: Optional[PngInfo] = None,
) -> bytes:
    buffer = io.BytesIO()
    save_kwargs: Dict[str, Any] = {}
    if pnginfo is not None:
        save_kwargs["pnginfo"] = pnginfo
    icc_profile = (getattr(image, "info", {}) or {}).get("icc_profile")
    if icc_profile:
        save_kwargs["icc_profile"] = icc_profile
    dpi = (getattr(image, "info", {}) or {}).get("dpi")
    if dpi:
        save_kwargs["dpi"] = dpi
    image.save(buffer, format="PNG", **save_kwargs)
    return buffer.getvalue()


def enrich_comfyui_png_bytes(
    raw_bytes: Optional[bytes],
    image: Optional[Image.Image] = None,
    *,
    workflow_api: Optional[Dict[str, Any]] = None,
    workflow_ui: Optional[Dict[str, Any]] = None,
    generation_params: Optional[Dict[str, Any]] = None,
    prompt_context: Optional[Dict[str, Any]] = None,
    api_metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[bytes, Image.Image, bool]:
    if raw_bytes and is_png_bytes(raw_bytes):
        opened = Image.open(io.BytesIO(raw_bytes))
        opened.load()
    elif image is not None:
        opened = image.copy()
    else:
        raise ValueError("Either PNG bytes or a PIL image is required.")

    source_info = dict(getattr(opened, "info", {}) or {})
    needs_workflow_api = workflow_api and (not source_info.get("prompt") or not source_info.get("workflow_api"))
    needs_workflow_key = workflow_ui and not source_info.get("workflow")
    needs_naia = generation_params and not source_info.get("naia_generation_params")
    should_rewrite = bool(needs_workflow_api or needs_workflow_key or needs_naia or prompt_context or api_metadata)

    if not should_rewrite and raw_bytes:
        return raw_bytes, opened, False

    pnginfo = build_pnginfo(
        source_info,
        workflow_api=workflow_api,
        workflow_ui=workflow_ui,
        generation_params=generation_params,
        prompt_context=prompt_context,
        api_metadata=api_metadata,
    )
    enriched_bytes = image_to_png_bytes(opened, pnginfo=pnginfo)
    enriched_image = Image.open(io.BytesIO(enriched_bytes))
    enriched_image.load()
    return enriched_bytes, enriched_image, True


def build_comfyui_extra_pnginfo(
    workflow_api: Optional[Dict[str, Any]],
    workflow_ui: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    extra_pnginfo: Dict[str, Any] = {}
    if workflow_ui:
        extra_pnginfo["workflow"] = deepcopy(workflow_ui)
    if workflow_api:
        extra_pnginfo["workflow_api"] = deepcopy(workflow_api)
    return extra_pnginfo
