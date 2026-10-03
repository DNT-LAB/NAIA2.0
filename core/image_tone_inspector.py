"""이미지의 톤을 수치로 뽑는다 - 명도 · 채도 · 색도(치우침) · 색상 의존도 · 질감 · 선.

PyQt · 네트워크 · 모델 추론이 없다. numpy + Pillow + scipy.ndimage 만 쓴다(한 장 832x1216 에 0.25초쯤).

숫자는 **판정이 아니라 측정**이다. '누렇다' 같은 말은 붙이되(`direction`, `strength`) 좋다/나쁘다는 붙이지 않는다 -
같은 값이 한 작가에게는 결함이고 다른 작가에게는 화풍이다. 판정은 대조와 견주는 쪽이 한다.

색 공간:
  * 명도 = CIELAB L* (0~100) · 채도 = C* = hypot(a*, b*) · 치우침 = (a*, b*)
    a* 는 초록(-) ~ 빨강(+), b* 는 파랑(-) ~ 노랑(+).
  * 색상 이름은 HSV 색상각 30도 12칸으로 나눈다(사람이 아는 이름과 맞는 쪽). 무게는 C* 로 준다 -
    거의 무채색인 픽셀의 색상각은 잡음이라 세지 않는다(`NEUTRAL_CHROMA` 미만).

선(`lines`)은 **선 위에서 직접** 잰다. 화면 전체의 스펙트럼은 장면(배경의 자잘함 · 구도)이 지배해서 '선이 무르다' 를
못 가른다 - 실측(2026-10-03)에서 스펙트럼 기울기는 대조 2.0~2.6 · 무른 작가 2.4~2.6 으로 겹쳤고, 선 단면의 가파르기는
대조 16~27 · 무른 작가 8.6~11.5 로 갈렸다. 그래서 스펙트럼은 청할 때만 낸다(`spectrum=True`).

⚠️ `regions` 는 **분할이 아니다.** 화면 가운데 상자와 그 바깥을 나눈 어림이다. 배경이 통째로 바뀌는
   프롬프트(`colorful` 가중치 1 이 돌담을 추상 무늬로 바꿨다)는 전체 평균만 보면 '개선' 으로 오독한다 -
   그걸 거르려고 둔다. 세로 인물 구도에 맞춘 상자라 가로 구도에서는 덜 맞는다.
"""

from __future__ import annotations

import io
import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

SCHEMA = "naia.tone-inspect.v1"

#: 긴 변이 이보다 크면 줄여서 잰다. NAI 기본 해상도(긴 변 1216)는 그대로 통과한다 - 질감 지표가 축소에 민감하다.
MAX_SIDE = 1280
#: C* 가 이보다 낮으면 무채색으로 센다.
NEUTRAL_CHROMA = 6.0
VIVID_CHROMA = 40.0
DARK_L = 30.0
BRIGHT_L = 85.0
#: (left, top, right, bottom) 비율 - 인물이 있을 법한 가운데.
CENTER_BOX = (0.27, 0.12, 0.73, 0.97)
PALETTE_COLORS = 6
#: 색상 통계는 두 칸에 하나만 본다 - 몫은 거의 안 변하고 네 배 빠르다.
HUE_STRIDE = 2

# 선 단면 재기
LINE_SIGMA = 1.5            # 1~4px 굵기의 선에 맞춘 척도
LINE_SAMPLES = 6000
LINE_MIN_DEPTH = 8.0        # 선 한가운데가 양옆보다 이만큼(L*)은 어두워야 선으로 친다
# Valid cross-section fraction, NOT ridge candidate density. Calibrated only on
# the 10 SRS examples (3 present / 6 absent / 1 middle), not a lineart classifier.
LINE_MIN_VALID_SHARE = 0.88
_LINE_OFFSETS = np.arange(-8.0, 8.01, 0.5, dtype=np.float32)
_LINE_CENTRE = len(_LINE_OFFSETS) // 2
_LINE_REACH = 12            # 가운데에서 양쪽으로 6px

HUE_BINS: tuple[tuple[str, str], ...] = (
    ("red", "빨강"), ("orange", "주황"), ("yellow", "노랑"), ("chartreuse", "연두"),
    ("green", "초록"), ("spring", "청록빛 초록"), ("cyan", "청록"), ("azure", "하늘"),
    ("blue", "파랑"), ("violet", "보라"), ("magenta", "자주"), ("rose", "분홍"),
)
_WARM_BINS = (11, 0, 1, 2)      # 분홍 · 빨강 · 주황 · 노랑
_COOL_BINS = (6, 7, 8, 9)       # 청록 · 하늘 · 파랑 · 보라

# (a*, b*) 의 방향을 여덟 갈래로 부른다. 0도 = +a(붉은), 90도 = +b(누런), 180도 = -a(초록빛), 270도 = -b(푸른).
_TINT_DIRECTIONS = ("붉은", "주황빛", "누런", "연둣빛", "초록빛", "청록빛", "푸른", "보랏빛")
# 치우침의 크기를 부르는 문턱(C*). 서술용이지 합격선이 아니다.
_TINT_STRENGTHS = ((2.0, "중성"), (5.0, "약함"), (10.0, "뚜렷"), (math.inf, "강함"))

_SRGB_TO_LINEAR = np.where(
    np.arange(256) / 255.0 <= 0.04045,
    np.arange(256) / 255.0 / 12.92,
    ((np.arange(256) / 255.0 + 0.055) / 1.055) ** 2.4,
).astype(np.float32)
_RGB_TO_XYZ = np.array(
    [[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]],
    dtype=np.float32,
)
_WHITE = np.array([0.95047, 1.0, 1.08883], dtype=np.float32)


def _open(source: Any) -> Image.Image:
    if isinstance(source, Image.Image):
        return source
    if isinstance(source, (bytes, bytearray, memoryview)):
        return Image.open(io.BytesIO(bytes(source)))
    return Image.open(Path(source))


def load_rgb(source: Any, max_side: int = MAX_SIDE) -> tuple[np.ndarray, dict[str, Any]]:
    """그림을 RGB uint8 배열로. 투명한 그림은 흰 바탕에 얹는다(투명 BG 출력을 검정으로 읽지 않게)."""
    image = _open(source)
    image.load()
    width, height = image.size
    info: dict[str, Any] = {"width": width, "height": height, "has_alpha": False, "transparent_share": 0.0}
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        alpha = np.asarray(rgba.getchannel("A"))
        info["has_alpha"] = True
        info["transparent_share"] = round(float((alpha < 128).mean()), 4)
        if bool(np.all(alpha == 255)):
            # Opaque RGBA is common in generated PNGs; compositing cannot change
            # any pixel here. Keep partial transparency on the exact old path.
            image = rgba.convert("RGB")
        else:
            backdrop = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            image = Image.alpha_composite(backdrop, rgba).convert("RGB")
    else:
        image = image.convert("RGB")
    scale = 1.0
    longest = max(width, height)
    if max_side and longest > max_side:
        scale = max_side / longest
        image = image.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.BOX)
    info["analysis_width"], info["analysis_height"] = image.size
    info["analysis_scale"] = round(scale, 4)
    return np.asarray(image), info


def rgb_to_lab(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    linear = _SRGB_TO_LINEAR[rgb]
    xyz = (linear @ _RGB_TO_XYZ.T) / _WHITE
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16.0 / 116.0)
    lightness = 116.0 * f[..., 1] - 16.0
    a = 500.0 * (f[..., 0] - f[..., 1])
    b = 200.0 * (f[..., 1] - f[..., 2])
    return lightness, a, b


def _hsv_hue(rgb: np.ndarray) -> np.ndarray:
    values = rgb.astype(np.float32)
    r, g, b = values[..., 0], values[..., 1], values[..., 2]
    high = np.maximum(np.maximum(r, g), b)
    span = np.maximum(high - np.minimum(np.minimum(r, g), b), 1e-6)
    hue = np.where(high == r, ((g - b) / span) % 6.0, np.where(high == g, (b - r) / span + 2.0, (r - g) / span + 4.0))
    return (hue * 60.0) % 360.0


def _round(value: float, digits: int = 2) -> float:
    return round(float(value), digits)


def _tint(a: np.ndarray, b: np.ndarray) -> dict[str, Any]:
    """평균 (a*, b*) 와 그 방향 · 크기. 픽셀이 없으면 중성."""
    if a.size == 0:
        return {"a": 0.0, "b": 0.0, "chroma": 0.0, "hue_deg": 0.0, "direction": "", "strength": "중성"}
    mean_a, mean_b = float(a.mean()), float(b.mean())
    chroma = math.hypot(mean_a, mean_b)
    hue = math.degrees(math.atan2(mean_b, mean_a)) % 360.0
    strength = next(label for limit, label in _TINT_STRENGTHS if chroma < limit)
    direction = "" if strength == "중성" else _TINT_DIRECTIONS[int(((hue + 22.5) % 360.0) // 45.0)]
    return {"a": _round(mean_a), "b": _round(mean_b), "chroma": _round(chroma), "hue_deg": _round(hue, 1),
            "direction": direction, "strength": strength}


def _grain(lightness: np.ndarray, size: int = 5) -> float:
    """L* 국소 표준편차의 중앙값. 잡티뿐 아니라 반복 무늬도 반응하며 평평한 면을 분할하지 않는다."""
    mean = ndi.uniform_filter(lightness, size)
    square = ndi.uniform_filter(lightness * lightness, size)
    return float(np.median(np.sqrt(np.maximum(square - mean * mean, 0.0))))


def _first_crossing(side: np.ndarray, level: np.ndarray) -> np.ndarray:
    """가운데에서 바깥으로 가며 `level` 을 처음 넘는 자리(px, 표본 간격 0.5 를 선형 보간). 못 넘으면 nan."""
    above = side >= level[:, None]
    first = above.argmax(1)
    found = above.any(1) & (first > 0)
    index = np.clip(first, 1, side.shape[1] - 1)
    rows = np.arange(len(first))
    upper, lower = side[rows, index], side[rows, index - 1]
    fraction = np.where(upper > lower, (level - lower) / np.maximum(upper - lower, 1e-6), 0.0)
    return np.where(found, (index - 1 + fraction) * 0.5, np.nan)


def line_profile(lightness: np.ndarray, sigma: float = LINE_SIGMA, samples: int = LINE_SAMPLES) -> dict[str, Any]:
    """어두운 선을 가로질러 단면을 뜨고 굵기 · 대비 · 가파르기를 잰다.

    헤세 행렬의 큰 고윳값이 큰 자리 = 어두운 선의 한가운데, 그 고유벡터 = 선을 가로지르는 방향이다. 그 방향으로
    L* 을 0.5px 간격으로 떠서: 굵기 = 반치폭, 대비 = 양옆과 한가운데의 차, 옆면 폭 = 10~90% 구간의 길이.
    '무른 선' 은 가파르기(`steepness`)가 낮고 한가운데가 덜 어둡다(`floor` 가 높다).
    단, steepness는 대비에도 비례한다. depth/flank와 함께 읽고 단독 흐림 판정으로 쓰지 않는다.
    고정 sigma와 양옆 6px 탐색은 가는 선에 편향된다. samples=0의 0값은 측정 불가 표시다.
    """
    empty = {"samples": 0, "width": 0.0, "width_p25": 0.0, "width_p75": 0.0, "depth": 0.0, "floor": 0.0,
             "flank": 0.0, "steepness": 0.0, "width_reliable": False}
    if min(lightness.shape) < 32:
        return empty
    lxx = ndi.gaussian_filter(lightness, sigma, order=(0, 2))
    lyy = ndi.gaussian_filter(lightness, sigma, order=(2, 0))
    lxy = ndi.gaussian_filter(lightness, sigma, order=(1, 1))
    ridge = (lxx + lyy) / 2 + np.sqrt(((lxx - lyy) / 2) ** 2 + lxy ** 2)
    threshold = max(1.0, float(np.percentile(ridge[::2, ::2], 96)))
    # `>=` 다 - 선이 죄다 같은 세기인 그림(도면 · 합성 그림)은 문턱이 곧 최댓값이라 `>` 면 하나도 안 잡힌다.
    ys, xs = np.nonzero(ridge >= threshold)
    if len(ys) < 200:
        return empty
    # 좌표별 고정 우선순위 - 같은 그림은 같은 값을 낸다.
    # Coordinate priorities do not change when another candidate appears/disappears.
    priority = ys.astype(np.uint64) * np.uint64(0x9E3779B185EBCA87) ^ xs.astype(np.uint64)
    priority = (priority ^ (priority >> 30)) * np.uint64(0xBF58476D1CE4E5B9)
    priority = (priority ^ (priority >> 27)) * np.uint64(0x94D049BB133111EB)
    priority ^= priority >> 31
    count = min(samples, len(ys))
    pick = np.argpartition(priority, count - 1)[:count]
    ys, xs = ys[pick], xs[pick]
    theta = 0.5 * np.arctan2(2 * lxy[ys, xs], lxx[ys, xs] - lyy[ys, xs])
    coords = np.stack([ys[:, None] + _LINE_OFFSETS[None, :] * np.sin(theta)[:, None],
                       xs[:, None] + _LINE_OFFSETS[None, :] * np.cos(theta)[:, None]])
    profile = ndi.map_coordinates(lightness, coords, order=1, mode="nearest")
    rows = np.arange(len(profile))
    centre = _LINE_CENTRE + profile[:, _LINE_CENTRE - 4:_LINE_CENTRE + 5].argmin(1) - 4
    floor = profile[rows, centre]
    last = len(_LINE_OFFSETS) - 1
    left = np.stack([profile[rows, np.clip(centre - k, 0, last)] for k in range(_LINE_REACH + 1)], 1)
    right = np.stack([profile[rows, np.clip(centre + k, 0, last)] for k in range(_LINE_REACH + 1)], 1)
    depth = np.minimum(left.max(1), right.max(1)) - floor
    width = _first_crossing(left, floor + depth * 0.5) + _first_crossing(right, floor + depth * 0.5)
    flank = ((_first_crossing(left, floor + depth * 0.9) - _first_crossing(left, floor + depth * 0.1))
             + (_first_crossing(right, floor + depth * 0.9) - _first_crossing(right, floor + depth * 0.1))) / 2
    keep = (depth > LINE_MIN_DEPTH) & np.isfinite(width) & np.isfinite(flank) & (width < 12)
    if int(keep.sum()) < 100:
        return empty
    width, depth, flank, floor = width[keep], depth[keep], flank[keep], floor[keep]
    p25, p50, p75 = np.percentile(width, [25, 50, 75])
    return {
        "samples": int(keep.sum()),
        "width_reliable": bool(keep.mean() >= LINE_MIN_VALID_SHARE),
        "width": _round(p50), "width_p25": _round(p25), "width_p75": _round(p75),   # 반치폭(px)
        "depth": _round(np.median(depth), 1),        # 양옆 대비 얼마나 어두운가(L*)
        "floor": _round(np.median(floor), 1),        # 선 한가운데의 L* - 낮을수록 검은 선
        "flank": _round(np.median(flank)),           # 옆면 10~90% 폭(px) - 클수록 번진 선
        "steepness": _round(np.median(depth * 0.8 / np.maximum(flank, 0.25)), 1),   # L*/px - 낮을수록 무르다
    }


def spectrum_profile(lightness: np.ndarray) -> dict[str, Any]:
    """L* 의 방사 평균 전력 스펙트럼. ⚠️ 장면이 지배한다 - 같은 프롬프트 · 시드의 전후 비교에만 쓴다."""
    height, width = lightness.shape
    window = np.outer(np.hanning(height), np.hanning(width)).astype(np.float32)
    power = np.abs(np.fft.rfft2((lightness - lightness.mean()) * window)) ** 2
    radius = np.hypot(np.fft.fftfreq(height)[:, None], np.fft.rfftfreq(width)[None, :])
    valid = (radius > 0) & (radius <= 0.5)
    total = float(power[valid].sum()) or 1.0
    edges = (0.0, 1 / 64, 1 / 16, 1 / 8, 1 / 4, 0.5)
    names = ("over_64px", "16_64px", "8_16px", "4_8px", "2_4px")      # 무늬의 주기
    bands = {name: _round(float(power[(radius > low) & (radius <= high)].sum()) / total, 4)
             for name, low, high in zip(names, edges[:-1], edges[1:])}
    bins = np.linspace(0.01, 0.4, 40)
    index = np.digitize(radius.ravel(), bins)
    summed = np.bincount(index, weights=power.ravel(), minlength=len(bins) + 1)[1:-1]
    counted = np.maximum(np.bincount(index, minlength=len(bins) + 1)[1:-1], 1)
    centres = (bins[:-1] + bins[1:]) / 2
    slope = float(np.polyfit(np.log10(centres), np.log10(summed / counted + 1e-12), 1)[0])
    return {
        "slope": _round(-slope, 3),                  # 클수록 고주파가 빨리 죽는다(흐리다 · 단순하다)
        "centroid": _round(float((power * radius)[valid].sum()) / total, 4),      # 주기/px
        "bands": bands,
    }


def _lightness_stats(lightness: np.ndarray, percentiles=None) -> dict[str, float]:
    p01, p10, p50, p90, p99 = (np.percentile(lightness, [1, 10, 50, 90, 99])
                              if percentiles is None else percentiles)
    return {
        "mean": _round(lightness.mean()), "median": _round(p50), "std": _round(lightness.std()),
        "p01": _round(p01), "p10": _round(p10), "p90": _round(p90), "p99": _round(p99),
        "dark_share": _round((lightness < DARK_L).mean(), 4),
        "bright_share": _round((lightness > BRIGHT_L).mean(), 4),
    }


def _chroma_stats(chroma: np.ndarray) -> dict[str, float]:
    p50, p90 = np.percentile(chroma, [50, 90])
    return {
        "mean": _round(chroma.mean()), "median": _round(p50), "p90": _round(p90),
        "neutral_share": _round((chroma < NEUTRAL_CHROMA).mean(), 4),
        "vivid_share": _round((chroma > VIVID_CHROMA).mean(), 4),
    }


def _hue_stats(rgb: np.ndarray, chroma: np.ndarray) -> dict[str, Any]:
    rgb, chroma = rgb[::HUE_STRIDE, ::HUE_STRIDE], chroma[::HUE_STRIDE, ::HUE_STRIDE]
    hue = _hsv_hue(rgb)
    chromatic = chroma >= NEUTRAL_CHROMA
    index = (np.rint(hue[chromatic] / 30.0).astype(np.int64)) % 12
    weight = np.bincount(index, weights=chroma[chromatic], minlength=12).astype(np.float64)
    count = np.bincount(index, minlength=12).astype(np.float64)
    total_weight = float(weight.sum())
    share = weight / total_weight if total_weight > 0 else np.zeros(12)
    pixels = float(chroma.size)
    bins = [{"key": key, "label": label, "center_deg": i * 30, "share": _round(share[i], 4),
             "pixel_share": _round(count[i] / pixels, 4)} for i, (key, label) in enumerate(HUE_BINS)]
    order = np.argsort(-share)
    positive = share[share > 0]
    entropy = float(-(positive * np.log2(positive)).sum()) if positive.size else 0.0
    return {
        "bins": bins,
        "dominant": [{"key": HUE_BINS[i][0], "label": HUE_BINS[i][1], "share": _round(share[i], 4)}
                     for i in order[:3] if share[i] > 0],
        "top1_share": _round(share[order[0]], 4),
        "top2_share": _round(share[order[0]] + share[order[1]], 4),
        "entropy_bits": _round(entropy, 3),
        # 고르게 쓰인 색상 칸이 몇 개꼴인가(1 = 한 색상에 전부 기댄다, 12 = 고르다).
        "effective_hues": _round(2.0 ** entropy, 2),
        "warm_share": _round(sum(share[i] for i in _WARM_BINS), 4),
        "cool_share": _round(sum(share[i] for i in _COOL_BINS), 4),
        "chromatic_pixel_share": _round(float(chromatic.mean()), 4),
    }


def _hue_label(rgb: tuple[int, int, int]) -> str:
    pixel = np.array([[rgb]], dtype=np.uint8)
    lightness, a, b = rgb_to_lab(pixel)
    if math.hypot(float(a[0, 0]), float(b[0, 0])) < NEUTRAL_CHROMA:
        return "무채색"
    return HUE_BINS[int(np.rint(float(_hsv_hue(pixel)[0, 0]) / 30.0)) % 12][1]


def _palette(rgb: np.ndarray, colors: int = PALETTE_COLORS) -> list[dict[str, Any]]:
    """대표색 몇 개와 그 넓이. 작은 사본을 중앙값 자르기로 양자화한다."""
    small = Image.fromarray(rgb)
    small.thumbnail((160, 160), Image.Resampling.BOX)
    quantized = small.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    table = quantized.getpalette() or []
    counts = quantized.getcolors() or []
    pixels = float(sum(count for count, _ in counts)) or 1.0
    result = []
    for count, index in sorted(counts, reverse=True):
        color = tuple(int(v) for v in table[index * 3:index * 3 + 3])
        if len(color) != 3:
            continue
        lightness, a, b = rgb_to_lab(np.array([[color]], dtype=np.uint8))
        result.append({
            "rgb": list(color), "hex": "#%02x%02x%02x" % color, "share": _round(count / pixels, 4),
            "lightness": _round(lightness[0, 0], 1), "chroma": _round(math.hypot(float(a[0, 0]), float(b[0, 0])), 1),
            "hue_label": _hue_label(color),
        })
    return result


def _region(lightness: np.ndarray, a: np.ndarray, b: np.ndarray, chroma: np.ndarray, mask: np.ndarray) -> dict[str, Any]:
    if not mask.any():
        return {"pixel_share": 0.0}
    return {
        "pixel_share": _round(mask.mean(), 4),
        "lightness_mean": _round(lightness[mask].mean()),
        "chroma_mean": _round(chroma[mask].mean()),
        "neutral_share": _round((chroma[mask] < NEUTRAL_CHROMA).mean(), 4),
        "tint": _tint(a[mask], b[mask]),
    }


def _extreme_rgb(rgb: np.ndarray, mask: np.ndarray) -> list[int]:
    if not mask.any():
        return [0, 0, 0]
    return [int(round(v)) for v in rgb[mask].mean(0)]


def _rgb_balance(rgb: np.ndarray, mask: np.ndarray | None = None) -> dict[str, Any]:
    """평균색(0~255)과 세 채널의 치우침. 치우침 = 채널 평균 - 세 채널의 평균이라 합이 0 이다.

    ⚠️ 치우침 0 이 '정상' 이 아니다 - 인물 그림은 살색 때문에 늘 R 쪽이다. 화면은 0점(표본의 가운데)과 견줘 보여 준다.
    """
    pixels = rgb.reshape(-1, 3) if mask is None else rgb[mask]
    if pixels.size == 0:
        return {"mean": {"r": 0.0, "g": 0.0, "b": 0.0}, "bias": {"r": 0.0, "g": 0.0, "b": 0.0}}
    mean = pixels.mean(0, dtype=np.float64)
    grey = float(mean.mean())
    return {"mean": {k: _round(v, 1) for k, v in zip("rgb", mean)},
            "bias": {k: _round(v - grey, 1) for k, v in zip("rgb", mean)}}


def inspect_arrays(rgb: np.ndarray, spectrum: bool = False) -> dict[str, Any]:
    """RGB uint8 배열 하나를 잰다. `inspect_image` 가 이걸 부른다 - 시험은 배열을 직접 넣는다."""
    lightness, a, b = rgb_to_lab(rgb)
    chroma = np.hypot(a, b)
    p01, p02, p10, p25, p50, p75, p90, p98, p99 = np.percentile(
        lightness, [1, 2, 10, 25, 50, 75, 90, 98, 99])
    highlights = lightness >= p90
    shadows = lightness <= p10
    midtones = (lightness >= p25) & (lightness <= p75)

    height, width = lightness.shape
    left, top, right, bottom = CENTER_BOX
    center = np.zeros(lightness.shape, dtype=bool)
    center[int(height * top):int(height * bottom), int(width * left):int(width * right)] = True

    laplacian = (lightness[1:-1, 1:-1] * 4.0 - lightness[:-2, 1:-1] - lightness[2:, 1:-1]
                 - lightness[1:-1, :-2] - lightness[1:-1, 2:]) if min(height, width) >= 3 else np.zeros((1, 1))

    result = {
        "lightness": _lightness_stats(lightness, (p01, p10, p50, p90, p99)),
        "chroma": _chroma_stats(chroma),
        "tint": {
            "overall": _tint(a, b),
            "highlights": _tint(a[highlights], b[highlights]),
            "midtones": _tint(a[midtones], b[midtones]),
            "shadows": _tint(a[shadows], b[shadows]),
            # 가장 밝은 2% · 가장 어두운 2% 의 평균색 - '흰색이어야 할 곳' 과 '검정이어야 할 곳'.
            "white_point_rgb": _extreme_rgb(rgb, lightness >= p98),
            "black_point_rgb": _extreme_rgb(rgb, lightness <= p02),
        },
        # 그림 전체 · 밝은 영역(상위 10%) · 어두운 영역(하위 10%)의 평균색과 채널 치우침.
        "rgb": {
            "overall": _rgb_balance(rgb),
            "highlights": _rgb_balance(rgb, highlights),
            "shadows": _rgb_balance(rgb, shadows),
        },
        "hue": _hue_stats(rgb, chroma),
        "palette": _palette(rgb),
        "texture": {
            "grain": _round(_grain(lightness), 3),
            # 고주파 에너지(라플라시안 분산). 선 · 잡티 · 배경의 자잘함이 다 섞인다 - 선만 보려면 `lines`.
            "sharpness": _round(laplacian.var(), 1),
        },
        "lines": line_profile(lightness),
        "regions": {
            "box": list(CENTER_BOX),
            "center": _region(lightness, a, b, chroma, center),
            "border": _region(lightness, a, b, chroma, ~center),
        },
    }
    if spectrum:
        result["spectrum"] = spectrum_profile(lightness)
    return result


def inspect_image(source: Any, max_side: int = MAX_SIDE, spectrum: bool = False) -> dict[str, Any]:
    """경로 · 바이트 · PIL 이미지를 받아 톤 지표를 낸다."""
    rgb, info = load_rgb(source, max_side)
    return {"schema": SCHEMA, "image": info, **inspect_arrays(rgb, spectrum=spectrum)}


#: 두 측정의 차이를 낼 때 보는 숫자들 - (구역, 키).
_DELTA_FIELDS: tuple[tuple[str, ...], ...] = (
    ("lightness", "mean"), ("lightness", "median"), ("lightness", "p01"), ("lightness", "p99"), ("lightness", "std"),
    ("lightness", "dark_share"), ("chroma", "mean"), ("chroma", "neutral_share"),
    ("tint", "overall", "a"), ("tint", "overall", "b"), ("tint", "highlights", "a"), ("tint", "highlights", "b"),
    ("hue", "top1_share"), ("hue", "effective_hues"), ("hue", "warm_share"), ("hue", "cool_share"),
    ("texture", "grain"), ("texture", "sharpness"),
    ("lines", "width"), ("lines", "depth"), ("lines", "floor"), ("lines", "flank"), ("lines", "steepness"),
    ("regions", "center", "lightness_mean"), ("regions", "center", "chroma_mean"),
    ("regions", "border", "lightness_mean"), ("regions", "border", "chroma_mean"),
)


def _dig(data: dict[str, Any], path: tuple[str, ...]) -> float | None:
    node: Any = data
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return float(node) if isinstance(node, (int, float)) else None


def compare_inspections(before: dict[str, Any], after: dict[str, Any]) -> dict[str, float]:
    """`after - before`. 키는 `lightness.mean` 꼴."""
    delta: dict[str, float] = {}
    for path in _DELTA_FIELDS:
        old, new = _dig(before, path), _dig(after, path)
        if old is not None and new is not None:
            delta[".".join(path)] = _round(new - old, 4)
    return delta


def pixel_delta(before: Any, after: Any, max_side: int = MAX_SIDE) -> dict[str, float] | None:
    """같은 크기의 두 그림을 픽셀 단위로 뺀다(같은 시드 · 같은 프롬프트의 전후 비교용). 크기가 다르면 None.

    구도가 달라진 만큼 `abs_lightness` 가 커진다 - 평균 차이가 작아도 이 값이 크면 그림이 통째로 바뀐 것이다.
    """
    first, _ = load_rgb(before, max_side)
    second, _ = load_rgb(after, max_side)
    if first.shape != second.shape:
        return None
    l0, a0, b0 = rgb_to_lab(first)
    l1, a1, b1 = rgb_to_lab(second)
    return {
        "lightness": _round((l1 - l0).mean()), "a": _round((a1 - a0).mean()), "b": _round((b1 - b0).mean()),
        "chroma": _round((np.hypot(a1, b1) - np.hypot(a0, b0)).mean()),
        "abs_lightness": _round(np.abs(l1 - l0).mean()),
    }
