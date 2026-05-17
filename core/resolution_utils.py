import math
import re
from typing import Any, MutableMapping, Tuple


MAX_1MP_PIXELS = 1024 * 1024
STANDARD_1MP_RESOLUTIONS: tuple[tuple[int, int], ...] = (
    (1024, 1024),
    (960, 1088),
    (896, 1152),
    (832, 1216),
    (1088, 960),
    (1152, 896),
    (1216, 832),
)
STANDARD_1MP_RESOLUTION_LABELS: tuple[str, ...] = tuple(
    f"{width} x {height}" for width, height in STANDARD_1MP_RESOLUTIONS
)

ANIMA_MIN_PIXELS = 512 * 512
ANIMA_MAX_PIXELS = 1536 * 1536
ANIMA_MAX_DIMENSION = 1792
ANIMA_RESOLUTIONS: tuple[tuple[int, int], ...] = (
    (512, 512),
    (768, 768),
    (704, 832),
    (704, 896),
    (640, 960),
    (832, 704),
    (896, 704),
    (960, 640),
    (1024, 1024),
    (960, 1088),
    (896, 1152),
    (832, 1216),
    (1088, 960),
    (1152, 896),
    (1216, 832),
    (1152, 1152),
    (1088, 1216),
    (1024, 1280),
    (960, 1408),
    (1216, 1088),
    (1280, 1024),
    (1408, 960),
    (1216, 1216),
    (1152, 1280),
    (1088, 1344),
    (960, 1472),
    (1280, 1152),
    (1344, 1088),
    (1472, 960),
    (1344, 1344),
    (1280, 1472),
    (1216, 1536),
    (1088, 1600),
    (1472, 1280),
    (1536, 1216),
    (1600, 1088),
    (1536, 1536),
    (1408, 1600),
    (1344, 1728),
    (1216, 1792),
    (1600, 1408),
    (1728, 1344),
    (1792, 1216),
)
ANIMA_RESOLUTION_LABELS: tuple[str, ...] = tuple(
    f"{width} x {height}" for width, height in ANIMA_RESOLUTIONS
)
ANIMA_RESOLUTION_PRESETS: dict[str, tuple[tuple[int, int], ...]] = {
    "draft": (
        (512, 512),
    ),
    "compact": (
        (768, 768),
        (704, 832),
        (704, 896),
        (640, 960),
        (832, 704),
        (896, 704),
        (960, 640),
    ),
    "standard": (
        (1024, 1024),
        (960, 1088),
        (896, 1152),
        (832, 1216),
        (1088, 960),
        (1152, 896),
        (1216, 832),
    ),
    "hd": (
        (1152, 1152),
        (1088, 1216),
        (1024, 1280),
        (960, 1408),
        (1216, 1088),
        (1280, 1024),
        (1408, 960),
    ),
    "hd_plus": (
        (1216, 1216),
        (1152, 1280),
        (1088, 1344),
        (960, 1472),
        (1280, 1152),
        (1344, 1088),
        (1472, 960),
    ),
    "quality": (
        (1344, 1344),
        (1280, 1472),
        (1216, 1536),
        (1088, 1600),
        (1472, 1280),
        (1536, 1216),
        (1600, 1088),
    ),
    "max": (
        (1536, 1536),
        (1408, 1600),
        (1344, 1728),
        (1216, 1792),
        (1600, 1408),
        (1728, 1344),
        (1792, 1216),
    ),
}
ANIMA_RESOLUTION_PRESET_LABELS: dict[str, tuple[str, ...]] = {
    key: tuple(f"{width} x {height}" for width, height in values)
    for key, values in ANIMA_RESOLUTION_PRESETS.items()
}
ANIMA_RESOLUTION_PRESET_SQUARE_LABELS: dict[str, str] = {
    key: f"{values[0][0]} x {values[0][1]}"
    for key, values in ANIMA_RESOLUTION_PRESETS.items()
}


def parse_resolution_pair(value: Any) -> tuple[int, int] | None:
    match = re.search(r"(\d+)\s*x\s*(\d+)", str(value or ""), re.IGNORECASE)
    if not match:
        return None
    try:
        width = int(match.group(1))
        height = int(match.group(2))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def nearest_standard_1mp_resolution(width: Any, height: Any) -> tuple[int, int]:
    try:
        source_width = int(width)
        source_height = int(height)
    except (TypeError, ValueError):
        return (1024, 1024)

    if source_width <= 0 or source_height <= 0:
        return (1024, 1024)

    if (source_width, source_height) in STANDARD_1MP_RESOLUTIONS:
        return source_width, source_height

    source_ratio = source_width / source_height

    def score(candidate: tuple[int, int]) -> tuple[float, int, int]:
        candidate_width, candidate_height = candidate
        candidate_ratio = candidate_width / candidate_height
        ratio_delta = abs(math.log(candidate_ratio / source_ratio))
        pixel_gap = abs(MAX_1MP_PIXELS - (candidate_width * candidate_height))
        orientation_penalty = 0
        if (source_width >= source_height) != (candidate_width >= candidate_height):
            orientation_penalty = 1
        return ratio_delta, orientation_penalty, pixel_gap

    return min(STANDARD_1MP_RESOLUTIONS, key=score)


def normalize_anima_resolution_preset_id(value: Any) -> str:
    preset_id = str(value or "").strip().lower().replace("-", "_")
    return preset_id if preset_id in ANIMA_RESOLUTION_PRESETS else "standard"


def anima_resolution_preset_candidates(value: Any) -> tuple[tuple[int, int], ...]:
    return ANIMA_RESOLUTION_PRESETS[normalize_anima_resolution_preset_id(value)]


def anima_resolution_preset_labels(value: Any) -> tuple[str, ...]:
    return ANIMA_RESOLUTION_PRESET_LABELS[normalize_anima_resolution_preset_id(value)]


def anima_resolution_preset_square_label(value: Any) -> str:
    return ANIMA_RESOLUTION_PRESET_SQUARE_LABELS[normalize_anima_resolution_preset_id(value)]


def nearest_anima_resolution(width: Any, height: Any) -> tuple[int, int]:
    return nearest_anima_preset_resolution(width, height, "__all__")


def nearest_anima_preset_resolution(width: Any, height: Any, preset_id: Any) -> tuple[int, int]:
    try:
        source_width = int(width)
        source_height = int(height)
    except (TypeError, ValueError):
        return (1024, 1024)

    if source_width <= 0 or source_height <= 0:
        return (1024, 1024)

    candidates = (
        ANIMA_RESOLUTIONS
        if str(preset_id or "").strip().lower() == "__all__"
        else anima_resolution_preset_candidates(preset_id)
    )
    if (source_width, source_height) in candidates:
        return source_width, source_height

    source_ratio = source_width / source_height
    source_pixels = source_width * source_height
    target_pixels = min(max(source_pixels, ANIMA_MIN_PIXELS), ANIMA_MAX_PIXELS)

    def score(candidate: tuple[int, int]) -> tuple[int, float, int, float]:
        candidate_width, candidate_height = candidate
        candidate_ratio = candidate_width / candidate_height
        ratio_delta = abs(math.log(candidate_ratio / source_ratio))
        area_delta = abs(math.log((candidate_width * candidate_height) / target_pixels))
        area_bucket = int(area_delta / math.log(1.2))
        orientation_penalty = 0
        if (source_width >= source_height) != (candidate_width >= candidate_height):
            orientation_penalty = 1
        return area_bucket, ratio_delta, orientation_penalty, area_delta

    return min(candidates, key=score)


def normalize_artist_thumbnail_resolution(
    params: MutableMapping[str, Any],
) -> tuple[bool, Tuple[int, int], Tuple[int, int]]:
    raw_width = params.get("width", 1024) or 1024
    raw_height = params.get("height", 1024) or 1024
    invalid = False
    try:
        original = (int(raw_width), int(raw_height))
    except (TypeError, ValueError):
        original = (0, 0)
        invalid = True
    normalized = nearest_standard_1mp_resolution(*original)
    if invalid or normalized != original:
        params["width"], params["height"] = normalized
        params["resolution"] = f"{normalized[0]} x {normalized[1]}"
        return True, original, normalized
    return False, original, normalized


def apply_resolution_to_comfyui_workflow(workflow: MutableMapping[str, Any], width: int, height: int) -> int:
    patched = 0
    for node in workflow.values():
        if not isinstance(node, MutableMapping):
            continue
        class_type = str(node.get("class_type") or node.get("type") or "")
        inputs = node.get("inputs")
        if not isinstance(inputs, MutableMapping):
            continue
        if "width" not in inputs or "height" not in inputs:
            continue
        if "EmptyLatent" not in class_type and not (
            "Latent" in class_type and "batch_size" in inputs
        ):
            continue
        inputs["width"] = width
        inputs["height"] = height
        patched += 1
    return patched
