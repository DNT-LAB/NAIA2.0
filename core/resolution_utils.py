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

# ── NAI 전용 해상도 프리셋 ────────────────────────────────────────────────
#
# NAI 는 자기 UI 에서 **Small / Normal / Large / Wallpaper** 라는 이름을 쓴다.
# 그런데 NAI 가 이름당 주는 것은 Portrait/Landscape/Square **세 개뿐**이고,
# NAIA 의 해상도 체계는 1MP 종횡비 **일곱 개**(1024x1024 · 960x1088 · 896x1152 ·
# 832x1216 · 1088x960 · 1152x896 · 1216x832)로 돌아간다. 그대로 붙이면
# `1088x960`·`1152x896` 같은 비율이 Small/Large 에서 사라진다.
#
# 그래서 **각 밴드의 Portrait/Landscape 면적을 기준으로 일곱 비율을 스케일**하고
# 양변을 64 로 스냅해 표를 채웠다(사용자 지시 2026-08-28). 이 규칙은 검산을
# 통과한다 - NAI 공식 Small P/L/S 와 Large P/L 이 규칙에서 **그대로 나오고**,
# Normal 은 기존 `STANDARD_1MP_RESOLUTIONS` 와 완전히 같다.
#
# 규칙에서 벗어나는 두 자리는 사용자가 직접 정했다:
#   - Large Square : NAI 공식은 1472x1472 인데 같은 밴드 P/L 대비 **1.38배**라
#                    (Small·Normal 의 Square 는 1.04배) 밴드 안이 들쭉날쭉해진다.
#                    Wallpaper 가 1472 를 받으므로 여기는 규칙대로 **1280x1280**.
#   - Wallpaper    : 공식 두 값이 **16:9**(0.567/1.765)라 1MP 버킷 범위
#                    (0.684~1.462) **밖**이다 - 규칙으로는 못 만든다. 그래서
#                    파생 일곱에 **공식 16:9 두 개를 더해** 아홉 칸이다.
#
# 모든 값은 64 배수이고 NAI 자기 프리셋의 봉투(변 <= 1920 · 면적 <= 1472^2) 안에
# 있다 - `tests/test_nai_resolution_bands.py` 가 이 셋을 지킨다.
#
# 순서는 `STANDARD_1MP_RESOLUTIONS` 와 같다: 정사각 -> 세로(점점 길게) -> 가로.
NAI_RESOLUTION_PRESETS: dict[str, tuple[tuple[int, int], ...]] = {
    "small": (
        (640, 640),
        (576, 640),
        (576, 704),
        (512, 768),          # NAI 공식 Small Portrait
        (640, 576),
        (704, 576),
        (768, 512),          # NAI 공식 Small Landscape
    ),
    "normal": (
        (1024, 1024),        # NAI 공식 Normal Square
        (960, 1088),
        (896, 1152),
        (832, 1216),         # NAI 공식 Normal Portrait
        (1088, 960),
        (1152, 896),
        (1216, 832),         # NAI 공식 Normal Landscape
    ),
    "large": (
        (1280, 1280),        # 규칙값(공식 1472x1472 는 Wallpaper 로 - 사용자 결정)
        (1152, 1344),
        (1088, 1408),
        (1024, 1536),        # NAI 공식 Large Portrait
        (1344, 1152),
        (1408, 1088),
        (1536, 1024),        # NAI 공식 Large Landscape
    ),
    "wallpaper": (
        (1472, 1472),        # NAI 공식 Large Square 와 같은 치수 - 면적상 이 밴드다
        (1344, 1536),
        (1280, 1664),
        (1216, 1728),
        (1088, 1920),        # NAI 공식 Wallpaper Portrait (16:9)
        (1536, 1344),
        (1664, 1280),
        (1728, 1216),
        (1920, 1088),        # NAI 공식 Wallpaper Landscape (16:9)
    ),
}
NAI_RESOLUTION_PRESET_LABELS: dict[str, tuple[str, ...]] = {
    key: tuple(f"{width} x {height}" for width, height in values)
    for key, values in NAI_RESOLUTION_PRESETS.items()
}
# 밴드 합집합 - 해상도 관리자의 NAI 기본 후보로 쓴다.
NAI_RESOLUTIONS: tuple[tuple[int, int], ...] = tuple(
    dict.fromkeys(item for values in NAI_RESOLUTION_PRESETS.values() for item in values)
)
NAI_RESOLUTION_LABELS: tuple[str, ...] = tuple(
    f"{width} x {height}" for width, height in NAI_RESOLUTIONS
)
# 화면에 보이는 이름. NAI 자기 UI 의 표기를 그대로 쓴다 - 사용자가 NAI 에서 보던
# 것과 같은 말이어야 이 기능이 뜻을 갖는다.
NAI_RESOLUTION_PRESET_DISPLAY: dict[str, str] = {
    "small": "Small",
    "normal": "Normal",
    "large": "Large",
    "wallpaper": "Wallpaper",
}
# 프리셋을 안 쓰던 시절의 기본값 = Normal. 모르는 id 는 여기로 떨어진다.
NAI_DEFAULT_RESOLUTION_PRESET = "normal"


ANIMA_MIN_PIXELS = 384 * 640
ANIMA_MAX_PIXELS = 1536 * 1536
ANIMA_MAX_DIMENSION = 1792
ANIMA_RESOLUTIONS: tuple[tuple[int, int], ...] = (
    (512, 512),
    (448, 576),
    (448, 640),
    (384, 640),
    (576, 448),
    (640, 448),
    (640, 384),
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
        (448, 576),
        (448, 640),
        (384, 640),
        (576, 448),
        (640, 448),
        (640, 384),
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


def snap_dimension_to_multiple(value: Any, multiple: int = 64, *, minimum: int | None = None) -> int:
    """Round a single dimension to the nearest positive multiple of ``multiple``.

    NAI only accepts width/height that are multiples of 64, so any resolution
    headed for the NAI backend must be snapped or the request is rejected with a
    500. Rounding (not flooring) keeps the result as close as possible to the
    requested size, and the floor guarantees at least one full multiple.
    """
    if multiple <= 0:
        multiple = 64
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = float(multiple)
    floor_min = multiple if minimum is None else max(multiple, int(minimum))
    snapped = int(round(numeric / multiple)) * multiple
    return max(floor_min, snapped)


def snap_resolution_to_multiple(width: Any, height: Any, multiple: int = 64) -> tuple[int, int]:
    """Snap both sides of a resolution to the nearest multiple of ``multiple``."""
    return (
        snap_dimension_to_multiple(width, multiple),
        snap_dimension_to_multiple(height, multiple),
    )


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


def normalize_nai_resolution_preset_id(value: Any) -> str:
    """NAI 밴드 id 를 정규화한다. 모르는 값은 `normal`(무료 상한 밴드)로.

    ⚠️ ANIMA 쪽(`normalize_anima_resolution_preset_id`)과 **id 공간이 다르다.**
    섞어 쓰면 `normal` 이 `standard` 로 뭉개진다 - 파라미터 키도 따로 둔 이유다.
    """
    preset_id = str(value or "").strip().lower().replace("-", "_")
    return preset_id if preset_id in NAI_RESOLUTION_PRESETS else NAI_DEFAULT_RESOLUTION_PRESET


def nai_resolution_preset_candidates(value: Any) -> tuple[tuple[int, int], ...]:
    return NAI_RESOLUTION_PRESETS[normalize_nai_resolution_preset_id(value)]


def nai_resolution_preset_labels(value: Any) -> tuple[str, ...]:
    return NAI_RESOLUTION_PRESET_LABELS[normalize_nai_resolution_preset_id(value)]


def nearest_nai_preset_resolution(width: Any, height: Any, preset_id: Any) -> tuple[int, int]:
    """Auto Res 용 - 원본 비율에 가장 가까운 **그 밴드 안의** 해상도.

    `nearest_standard_1mp_resolution` 이 1MP 밴드에서 하던 일을 밴드별로 한다.
    """
    candidates = nai_resolution_preset_candidates(preset_id)
    pair = parse_resolution_pair(f"{width} x {height}")
    if not pair:
        return candidates[0]
    source_w, source_h = pair
    target = source_w / max(1, source_h)

    def score(candidate: tuple[int, int]) -> tuple[float, int]:
        cw, ch = candidate
        # 비율이 먼저, 같으면 원본 화소 수에 가까운 쪽.
        return (abs(cw / ch - target), abs(cw * ch - source_w * source_h))

    return min(candidates, key=score)


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
