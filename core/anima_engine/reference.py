"""ANIMA 참조(Ref Adapter v2 · 사용자 지정 2026-11-05) - 켠 Char Ref 칸 + 설정 -> 관리형 생성 요청.

- 칸은 Character Reference 서비스의 것 그대로다. 그 서비스는 칸을 모드별 파일(CharacterReferenceModule_{mode}.json)에
  두므로 ANIMA(COMFYUI 모드)의 칸은 NAI 의 칸과 따로다. 그림 보관함(save/character_reference/images)은 같이 쓴다.
- 설정(참조 세기 등)은 칸이 아니라 ANIMA 참조 전체에 하나 - save/anima_reference.json. 기본값 = 제작자 기본값.
- 여러 장(최대 MAX_REFS)은 NAIA 가 높이를 맞춰 왼쪽부터 나란히 붙여 한 장으로 보낸다(어댑터는 그림 하나를 받고, 두
  캐릭터는 나란히 붙인 그림으로 그리는 방식 - 원격 실측 11-05: 2 · 3장 모두 제자리에 나왔고 시간은 1장과 같다).
- 큐에 넣을 때 켠 칸(해시)과 설정을 잡고(snapshot), 보낼 때 그림을 읽어 붙이고 엔진 input 에 올린다(upload).
"""
from __future__ import annotations

import hashlib
import io
import json
from typing import Any

from .profile import REF_CORRECTIONS, REF_DEFAULTS, REF_RANGES

MAX_REFS = 3
SETTINGS_FILE = "anima_reference.json"
STITCH_HEIGHT_RANGE = (512, 1536)


def _clean(key: str, value: Any):
    if key == "correction":
        return value if value in REF_CORRECTIONS else None
    if key not in REF_RANGES or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:        # NaN
        return None
    low, high = REF_RANGES[key]
    return round(min(high, max(low, number)), 2)


def load_settings(context) -> dict:
    values = dict(REF_DEFAULTS)
    try:
        raw = json.loads(context._existing_save_path(SETTINGS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError, AttributeError):
        raw = {}
    if isinstance(raw, dict):
        for key in REF_DEFAULTS:
            cleaned = _clean(key, raw.get(key))
            if cleaned is not None:
                values[key] = cleaned
    return values


def save_setting(context, key: str, value: Any) -> dict:
    """한 값만 바꾼다. 'reset' 은 전부 기본값으로."""
    values = load_settings(context)
    if key == "reset":
        values = dict(REF_DEFAULTS)
    else:
        cleaned = _clean(key, value)
        if cleaned is None:
            raise ValueError(key)
        values[key] = cleaned
    path = context._save_path(SETTINGS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, indent=2), encoding="utf-8")
    return values


def enabled_hashes(context) -> list[str]:
    # Char Ref 서비스가 없는 context(시험용 · 최소 런타임)는 참조 없음
    factory = getattr(context, "_character_reference_service", None)
    if factory is None:
        return []
    factory()._ensure_loaded()
    frames = getattr(context, "character_reference_frames", None) or []
    hashes = [str(f.get("file_hash") or "") for f in frames if f.get("is_enabled")]
    return [h for h in hashes if h][:MAX_REFS]


def snapshot(context, params: dict) -> None:
    """큐에 넣는 순간의 참조 - 기다리는 동안 칸을 바꿔도 이 생성은 그대로(LoRA · 모델과 같은 규칙).
    캐릭터 에셋처럼 '레퍼런스를 붙이지 마라' 고 표시한 요청은 건너뛴다(NAI Char Ref 와 같은 표식)."""
    params.pop("_anima_reference", None)
    if params.get("_skip_character_reference_late_binding"):
        return
    hashes = enabled_hashes(context)
    if hashes:
        params["_anima_reference"] = {"hashes": hashes, "settings": load_settings(context)}


def _flatten(image):
    from PIL import Image
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, (255, 255, 255))
        canvas.paste(rgba, mask=rgba.getchannel("A"))
        return canvas
    return image.convert("RGB")


def stitch(images) -> bytes:
    """왼쪽부터 나란히 - 높이는 가장 낮은 그림에 맞춘다(512~1536 안으로). 투명한 자리는 흰색."""
    from PIL import Image
    flat = [_flatten(image) for image in images]
    low, high = STITCH_HEIGHT_RANGE
    height = max(low, min(high, min(image.height for image in flat)))
    resized = [image if image.height == height else
               image.resize((max(1, round(image.width * height / image.height)), height), Image.LANCZOS)
               for image in flat]
    canvas = Image.new("RGB", (sum(image.width for image in resized), height), (255, 255, 255))
    x = 0
    for image in resized:
        canvas.paste(image, (x, 0))
        x += image.width
    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


def engine_image_name(png: bytes) -> str:
    return "naia_ref_" + hashlib.sha256(png).hexdigest()[:16] + ".png"


def build(context, captured: dict) -> tuple[bytes, str, dict]:
    """잡아 둔 해시 -> (붙인 PNG, 엔진 파일 이름, 그래프 설정). 그림이 사라졌으면 거절한다(몰래 빼고 그리지 않는다)."""
    from PIL import Image
    from .runtime import ManagedEngineError
    hashes = [str(h) for h in (captured.get("hashes") or [])][:MAX_REFS]
    images = []
    for file_hash in hashes:
        path = context._existing_save_path("character_reference", "images", f"{file_hash}.png")
        try:
            with Image.open(path) as opened:
                opened.load()
                images.append(opened.copy())
        except OSError:
            raise ManagedEngineError("REFERENCE_NOT_FOUND", "참조 그림을 찾지 못했습니다.", file_hash) from None
    if not images:
        raise ManagedEngineError("REFERENCE_NOT_FOUND", "참조 그림을 찾지 못했습니다.")
    png = stitch(images)
    name = engine_image_name(png)
    settings = dict(REF_DEFAULTS)
    for key, value in (captured.get("settings") or {}).items():
        cleaned = _clean(key, value) if key in REF_DEFAULTS else None
        if cleaned is not None:
            settings[key] = cleaned
    return png, name, {"image": name, **settings}


def upload(url: str, png: bytes, name: str, *, post=None) -> None:
    """엔진 input 폴더로(POST /upload/image). 같은 그림이면 같은 이름이라 덮어써도 같다."""
    import requests
    from .runtime import ManagedEngineError
    response = (post or requests.post)(url + "/upload/image", files={"image": (name, png, "image/png")},
                                       data={"type": "input", "overwrite": "true"}, timeout=30)
    try:
        response.raise_for_status()
        saved = response.json()
    except Exception as exc:
        raise ManagedEngineError("REFERENCE_UPLOAD_FAILED", "참조 그림을 엔진에 올리지 못했습니다.", str(exc)) from None
    if saved.get("name") != name or saved.get("subfolder"):
        raise ManagedEngineError("REFERENCE_UPLOAD_FAILED", "참조 그림을 엔진에 올리지 못했습니다.", json.dumps(saved)[:200])


def engine_has_nodes(url: str, *, get=None) -> bool:
    import requests
    from .ref_adapter import NODE_CLASSES, WEIGHT
    from core.headless_api_option_service import extract_combo_options
    try:
        for name in (*NODE_CLASSES, "LoraLoaderModelOnly"):
            response = (get or requests.get)(url + "/object_info/" + name, timeout=10)
            response.raise_for_status()
            info = response.json().get(name)
            if not info:
                return False
            required = info["input"]["required"]
            if name == "AnimaRefAdapter" and not set(REF_DEFAULTS) | {"model", "vae", "image", "lora_name"} <= set(required):
                return False
            # 가중치가 엔진에 실제로 보이는가 - 어댑터 노드의 목록은 없는 파일도 보이고(없으면 HF 에서 받는다) ComfyUI 의
            # loras 목록(LoraLoaderModelOnly)은 있는 파일만 보인다. 모델 경로 파일의 naia_ref_adapter 칸을 엔진이 읽었는지.
            if name == "LoraLoaderModelOnly" and WEIGHT["filename"] not in extract_combo_options(required.get("lora_name")):
                return False
        return True
    except Exception:
        return False
