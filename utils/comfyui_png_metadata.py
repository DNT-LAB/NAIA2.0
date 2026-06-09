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

WORKFLOW_SOURCE_KEY = "_naia_workflow_source"
WORKFLOW_SOURCE_JSON = "json"

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


UI_WIDGET_KEYS_BY_CLASS = {
    "CheckpointLoaderSimple": ["ckpt_name"],
    "UNETLoader": ["unet_name", "weight_dtype"],
    "CLIPLoader": ["clip_name", "type", "device"],
    "VAELoader": ["vae_name"],
    "CLIPTextEncode": ["text"],
    "EmptyLatentImage": ["width", "height", "batch_size"],
    "KSampler": ["seed", None, "steps", "cfg", "sampler_name", "scheduler", "denoise"],
    "ModelSamplingDiscrete": ["sampling", "zsnr"],
    "RescaleCFG": ["multiplier"],
    "SaveImage": ["filename_prefix"],
    "SaveAnimatedWEBP": ["filename_prefix", "fps", "lossless", "quality", "method"],
    "PrimitiveString": ["value"],
    "PrimitiveInt": ["value"],
}


def _normalize_comfyui_workflow_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    metadata = dict(metadata or {})
    if not metadata.get("prompt") and metadata.get("workflow_api"):
        metadata["prompt"] = metadata["workflow_api"]
    if metadata.get("prompt") and not (metadata.get("workflow") or metadata.get("workflow_api")):
        metadata["workflow_api"] = metadata["prompt"]
    return metadata


def _loads_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _looks_like_comfyui_api_workflow(data: Any) -> bool:
    if not isinstance(data, dict) or not data:
        return False
    return any(
        isinstance(node, dict) and isinstance(node.get("class_type"), str)
        for node in data.values()
    )


def _looks_like_comfyui_ui_workflow(data: Any) -> bool:
    return isinstance(data, dict) and isinstance(data.get("nodes"), list)


def _comfyui_ui_workflow_to_api(workflow: Dict[str, Any]) -> Dict[str, Any]:
    links = {
        link[0]: link
        for link in workflow.get("links", [])
        if isinstance(link, list) and len(link) >= 6
    }
    api_workflow: Dict[str, Any] = {}

    for node in workflow.get("nodes", []):
        if not isinstance(node, dict):
            continue
        raw_node_id = node.get("id")
        if raw_node_id is None:
            continue
        node_id = str(raw_node_id)
        class_type = node.get("type") or node.get("class_type")
        if not class_type:
            continue

        inputs: Dict[str, Any] = {}
        for input_slot in node.get("inputs", []) or []:
            if not isinstance(input_slot, dict):
                continue
            slot_name = input_slot.get("name")
            link_id = input_slot.get("link")
            link = links.get(link_id)
            if not slot_name or not link:
                continue
            inputs[str(slot_name)] = [str(link[1]), link[2]]

        widget_keys = UI_WIDGET_KEYS_BY_CLASS.get(str(class_type), [])
        widgets = node.get("widgets_values", [])
        if isinstance(widgets, dict):
            for key, value in widgets.items():
                inputs.setdefault(str(key), value)
        elif isinstance(widgets, list):
            for index, key in enumerate(widget_keys):
                if key and index < len(widgets):
                    inputs.setdefault(key, widgets[index])

        api_workflow[node_id] = {
            "class_type": str(class_type),
            "inputs": inputs,
        }
        title = node.get("title") or (node.get("properties") or {}).get("Node name for S&R")
        if title:
            api_workflow[node_id]["_meta"] = {"title": title}

    return api_workflow


def comfyui_workflow_json_to_metadata(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("ComfyUI workflow JSON must be an object.")

    if data.get("prompt") or data.get("workflow") or data.get("workflow_api"):
        metadata = {}
        for key in ("prompt", "workflow", "workflow_api"):
            if key in data and data.get(key) is not None:
                metadata[key] = json_dumps_for_png(_loads_json_value(data.get(key)))
        metadata = _normalize_comfyui_workflow_metadata(metadata)
        if _has_comfyui_workflow_metadata(metadata):
            return metadata

        workflow_data = _loads_json_value(data.get("workflow") or data.get("workflow_api"))
        if _looks_like_comfyui_ui_workflow(workflow_data):
            prompt_api = _comfyui_ui_workflow_to_api(workflow_data)
            if prompt_api:
                return {
                    "workflow": json_dumps_for_png(workflow_data),
                    "prompt": json_dumps_for_png(prompt_api),
                    "workflow_api": json_dumps_for_png(prompt_api),
                }
        if _looks_like_comfyui_api_workflow(workflow_data):
            workflow_text = json_dumps_for_png(workflow_data)
            return {
                "workflow": workflow_text,
                "prompt": workflow_text,
                "workflow_api": workflow_text,
            }

    if _looks_like_comfyui_ui_workflow(data):
        prompt_api = _comfyui_ui_workflow_to_api(data)
        if not prompt_api:
            raise ValueError("ComfyUI UI workflow JSON has no usable nodes.")
        return {
            "workflow": json_dumps_for_png(data),
            "prompt": json_dumps_for_png(prompt_api),
            "workflow_api": json_dumps_for_png(prompt_api),
        }

    if _looks_like_comfyui_api_workflow(data):
        workflow_text = json_dumps_for_png(data)
        return {
            "workflow": workflow_text,
            "prompt": workflow_text,
            "workflow_api": workflow_text,
        }

    raise ValueError("No ComfyUI workflow data found in the selected JSON.")


def extract_comfyui_workflow_metadata_from_json_bytes(json_bytes: bytes) -> Dict[str, Any]:
    if not json_bytes:
        raise ValueError("No JSON data")
    try:
        data = json.loads(json_bytes.decode("utf-8-sig"))
    except Exception as exc:
        raise ValueError(f"Workflow JSON parse failed: {exc}") from exc
    metadata = comfyui_workflow_json_to_metadata(data)
    metadata[WORKFLOW_SOURCE_KEY] = WORKFLOW_SOURCE_JSON
    return metadata


def extract_comfyui_workflow_metadata_from_upload_bytes(upload_bytes: bytes) -> Dict[str, Any]:
    if not upload_bytes:
        raise ValueError("No upload data")
    stripped = upload_bytes.lstrip()
    if stripped.startswith(b"\xef\xbb\xbf"):
        stripped = stripped[3:].lstrip()
    if stripped.startswith((b"{", b"[")):
        return extract_comfyui_workflow_metadata_from_json_bytes(upload_bytes)
    return extract_comfyui_workflow_metadata_from_image_bytes(upload_bytes)


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


def png_has_generation_metadata(raw_bytes: Optional[bytes]) -> bool:
    """다운로드한 PNG가 이미 ComfyUI 생성 메타데이터(prompt/workflow 청크)를 담고 있는가.

    NAIA가 자체 메타데이터를 보강할지 판단하는 게이트 — **네이티브 메타데이터가 없을
    때만** 보강한다(사용자 요청). ComfyUI 서버가 ``--disable-metadata`` 등으로 아무것도
    임베드하지 않으면 False를 반환한다. prompt/workflow/workflow_api 중 하나라도 있으면
    "메타데이터 있음"으로 간주해 네이티브 값을 보존한다."""
    if not is_png_bytes(raw_bytes):
        return False
    try:
        with Image.open(io.BytesIO(raw_bytes)) as image:
            info = getattr(image, "info", {}) or {}
        return any(bool(info.get(key)) for key in ("prompt", "workflow", "workflow_api"))
    except Exception:
        return False


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
    source_info = getattr(image, "info", {}) or {}
    icc_profile = source_info.get("icc_profile")
    dpi = source_info.get("dpi")
    # PNG가 저장할 수 없는 모드(CMYK/YCbCr/HSV/F 등)는 RGB(A)로 변환한다. 변환 시 원본
    # ICC(예: CMYK 프로파일)는 더 이상 유효하지 않으므로 떨군다. ComfyUI는 보통 RGB(A)다.
    # ⚠️ PIL은 save_kwargs에 icc_profile이 없으면 image.info["icc_profile"]를 자동 사용하므로,
    #    변환본에 복사된 stale ICC를 info에서도 제거해야 실제로 기록되지 않는다.
    if image.mode not in ("1", "L", "LA", "I", "P", "RGB", "RGBA"):
        image = image.convert("RGBA" if ("A" in image.mode or "a" in image.mode) else "RGB")
        image.info.pop("icc_profile", None)
        icc_profile = None
    if icc_profile:
        save_kwargs["icc_profile"] = icc_profile
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
