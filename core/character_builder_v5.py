"""Fixed V5 asset-builder contract, catalog cache and request validation."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from core.nai_anlas_cost import estimate_anlas_cost
from core.nai_model_contract import apply_nai_fixed_params, resolve_nai_model_spec

MODEL = "NAID5FM"
SCALE = 5.0
RESOLUTIONS = {"standard": (832, 1216), "high": (1024, 1536), "ultra": (1152, 1728)}
GENDERS = {"girl": "1girl", "boy": "1boy", "other": "1other"}
BLOCKS = ("hair", "face", "body", "species", "outfit", "accessory", "item")
POSE_DEFAULT = "standing, full body"
MAX_COUNT = 4
# 신 사양의 그림은 **투명 배경**이다 - 구 사양(흰 배경)과 신 사양을 가르는 선(사용자 결정 2026-10-11).
# 투명하지 않은 그림은 버리지 않는다: 부품 구성을 떼고 **구 사양으로 저장**된다(저장의 목이 가른다).
# 알파 채널이 있고, 투명한 화소(알파 128 미만 - `core/image_tone_inspector` 와 같은 잣대)가 이 비율 이상이어야 한다.
# 전신 한 명이 서 있는 그림은 절반 가까이가 투명하다. 5% 는 "배경이 통째로 칠해졌다" 를 가르는 낮은 문턱이다.
TRANSPARENT_MIN_SHARE = 0.05
PROMPT_TEMPLATE = (
    "{count}, -1::artist collaboration ::, {pose}, year 2024, masterpiece, very aesthetic, "
    "high complexity, -0.25::low complexity, detailed background, sepia, muted color ::, "
    "0.15::ultra complexity ::, no text, transparent background"
)


class PartsCatalog:
    """Read once per mtime, keeping tag lookup and response on the same snapshot."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._revision = None
        self._data = None
        self._records = {}

    def read(self) -> tuple[dict, str, dict]:
        with self._lock:
            try:
                revision = self.path.stat().st_mtime_ns
            except FileNotFoundError:
                raise FileNotFoundError("character parts catalog is missing") from None
            if self._data is None or revision != self._revision:
                with self.path.open(encoding="utf-8") as handle:
                    data = json.load(handle)
                records = {
                    tag["tag"]: tag
                    for block in data["blocks"]
                    for part in block["parts"]
                    for tag in part["tags"]
                }
                self._data, self._records, self._revision = data, records, revision
            return self._data, str(self._revision), self._records


def specification() -> dict[str, Any]:
    # The estimator reads context._current_model_key for its V5 multiplier.
    # A fixed context prevents the live session model from affecting this spec.
    context = SimpleNamespace(_current_model_key=lambda: MODEL)
    resolutions = []
    for key, (width, height) in RESOLUTIONS.items():
        params = {"model": MODEL, "width": width, "height": height, "cfg_scale": SCALE}
        apply_nai_fixed_params(context, params)
        resolutions.append({"key": key, "width": width, "height": height,
                            "paid": estimate_anlas_cost(context, params) > 0})
    return {
        "model": MODEL, "model_label": resolve_nai_model_spec(MODEL).label, "scale": SCALE,
        "resolutions": resolutions, "genders": list(GENDERS), "pose_slot_default": POSE_DEFAULT,
        "prompt_template": PROMPT_TEMPLATE, "blocks": list(BLOCKS), "max_count": MAX_COUNT, "api_mode": "NAI",
    }


def normalize_pose(value: Any = "") -> str:
    if not isinstance(value, str):
        raise ValueError("pose_slot must be a string")
    if re.search(r"[^a-zA-Z0-9 _,\-'\.()!?+/&]", value) or "__" in value:
        raise ValueError("pose_slot contains unsupported characters")
    parts = [re.sub(" +", " ", part.strip()) for part in value.split(",") if part.strip()]
    if len(parts) > 12:
        raise ValueError("pose_slot must contain at most 12 tags")
    pose = ", ".join(parts) or POSE_DEFAULT
    if len(pose) > 200:
        raise ValueError("pose_slot must contain at most 200 characters")
    return pose


def validate_builder(payload: Any, catalog: PartsCatalog, *, saved: bool = False) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("builder must be an object")
    if saved and (type(payload.get("version")) is not int or payload["version"] != 1):
        raise ValueError("builder version must be 1")
    gender = payload.get("gender")
    if not isinstance(gender, str) or gender not in GENDERS:
        raise ValueError("unknown gender")
    resolution = payload.get("resolution")
    if not isinstance(resolution, str) or resolution not in RESOLUTIONS:
        raise ValueError("unknown resolution")
    seed = payload.get("seed")
    if seed is not None and (type(seed) is not int or not 0 <= seed <= 18446744073709551615):
        raise ValueError("seed must be null or an unsigned 64-bit integer")
    pose = normalize_pose(payload.get("pose_slot", ""))
    parts = payload.get("parts")
    if not isinstance(parts, dict):
        raise ValueError("parts must be an object")
    unknown = set(parts) - set(BLOCKS)
    if unknown:
        raise ValueError(f"unknown block: {next(iter(unknown))}")
    data, _revision, records = catalog.read()
    normalized = {}
    seen = set()
    for block in BLOCKS:
        if block not in parts:
            continue
        if not isinstance(parts[block], list):
            raise ValueError(f"parts.{block} must be a list")
        normalized[block] = []
        for entry in parts[block]:
            if isinstance(entry, str):
                tag, hold = entry, False
            elif isinstance(entry, dict):
                tag, hold = entry.get("tag"), entry.get("hold", False)
                if type(hold) is not bool:
                    raise ValueError("hold must be a boolean")
            else:
                raise ValueError("part must be a tag string or object")
            if not isinstance(tag, str) or tag not in data["index"]:
                raise ValueError(f"unknown catalog tag: {tag}")
            if data["index"][tag][0] != block:
                raise ValueError(f"tag belongs to a different block: {tag}")
            if hold and not records[tag].get("hold"):
                raise ValueError(f"tag does not support hold: {tag}")
            if tag in seen:
                continue
            seen.add(tag)
            normalized[block].append({"tag": tag, "hold": True} if hold else tag)
    if not seen:
        raise ValueError("at least one part is required")
    return {"version": 1, "gender": gender, "parts": normalized, "resolution": resolution,
            "seed": seed, "pose_slot": pose}


def transparency(data: bytes) -> dict[str, Any]:
    """그림이 투명 배경인가. 화면의 경고와 저장의 거절이 **이 함수 하나**를 본다(잣대를 둘로 두지 않는다)."""
    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(bytes(data or b""))) as image:
            image.load()
            has_alpha = image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info)
            share = 0.0
            if has_alpha:
                histogram = image.convert("RGBA").getchannel("A").histogram()
                share = sum(histogram[:128]) / max(1, image.width * image.height)
    except Exception as exc:      # noqa: BLE001 - 그림이 아니면 투명도 아니다
        raise ValueError(f"image could not be read: {exc}") from exc
    return {"has_alpha": has_alpha, "transparent_share": round(share, 4),
            "ok": bool(has_alpha and share >= TRANSPARENT_MIN_SHARE)}


def generation_count(payload: dict) -> int:
    count = payload.get("count", 1)
    if type(count) is not int or not 1 <= count <= MAX_COUNT:
        raise ValueError(f"count must be an integer between 1 and {MAX_COUNT}")
    return 1 if type(payload.get("seed")) is int else count


def build_overrides(payload: dict, candidate: int, catalog: PartsCatalog) -> dict[str, Any]:
    request_id = payload.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("request_id is required")
    generation_count(payload)
    builder = validate_builder(payload, catalog)
    _data, _revision, records = catalog.read()
    tags = []
    for entries in builder["parts"].values():
        for entry in entries:
            tags.append(records[entry["tag"]]["hold"] if isinstance(entry, dict) else entry)
    character = ", ".join([builder["gender"], *tags])
    prompt = PROMPT_TEMPLATE.format(count=GENDERS[builder["gender"]], pose=builder["pose_slot"])
    width, height = RESOLUTIONS[builder["resolution"]]
    return {
        "character_asset_request": True, "character_asset_request_id": request_id.strip(),
        "character_asset_candidate": int(candidate), "character_asset_flow": "builder_v5",
        "_remote_queue_source": "Character Asset", "_remote_queue_label": ", ".join(tags[:3])[:80],
        "input": prompt, "_raw_input": prompt, "negative_prompt": "", "characters": [character], "uc": [""],
        "character_positions": [], "sketchbook_character_prompts": [],
        "model": MODEL, "cfg_scale": SCALE, "width": width, "height": height,
        "random_resolution": False, "wildcard_standalone": True, "_literal_input": True,
        "_skip_vibe_transfer_late_binding": True, "_skip_character_reference_late_binding": True,
        "_skip_character_late_binding": True, "_interactive_reference_binding": False,
        "interactive_mode_request": False, "use_custom_api_params": False,
        "reference_image_multiple": [], "director_reference_images": [], "director_reference_descriptions": [],
        "reference_inset_tag_required": False, "cropped_image_request": False,
        "seed": builder["seed"] if builder["seed"] is not None else -1,
        "seed_fixed": builder["seed"] is not None,
    }


def builder_metadata(payload: Any, catalog: PartsCatalog) -> dict[str, Any]:
    builder = validate_builder(payload, catalog, saved=True)
    return {**builder, "model": MODEL, "scale": SCALE, "saved_at": datetime.now(timezone.utc).isoformat()}
