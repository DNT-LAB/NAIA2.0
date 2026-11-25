"""NAI Character Reference(웹 이름 'Precise Reference') - 모델마다 갈라진 사양을 한 곳에 둔다(2026-11-25 V5 출시).

출처 = NovelAI 웹 클라이언트 번들(2026-11-25 실측 · `novelai.net/image`). 모델 능력값:

| 능력 | V4.5 | V5 (5C · 5F · 각 인페인트) | V5 Full Medium |
|---|---|---|---|
| characterReferences | O | O | **X** |
| characterReferenceStrengthMax | 1 | **5** | - |
| characterReferenceFidelity | O | **X** (fidelity 를 1 로 - secondary 0) | - |
| outfitReferences | X | **O** (`costume` · `*_anyoutfit` · `*_mainoutfit`) | - |
| 이미지 | resize = 고정 캔버스에 검은 여백 | **bucket = 버킷 97종 중 비율이 가장 가까운 것에 덮어 맞추고 가운데 잘라 냄** | - |
| charRefInpainting | O | **X** (마스크가 있으면 CR 을 안 싣는다) | - |

유형(`description` = caption 의 base_caption):
- `character&style` (Prefer same outfit 켬) / `character&style_anyoutfit` (끔)
- `character_mainoutfit` (Character + Prefer same outfit 켬) / `character` (끔)
- `style` · `costume`(화면 이름 Outfit)
옷 유형을 모르는 모델(V4.5)로 보낼 때: `costume` 은 뺀다 · `_mainoutfit` -> `character` · `_anyoutfit` -> `character&style`(웹과 같다).

저장(프레임 · 보관함)은 모델과 상관없는 값 그대로 두고, **요청 목(api_service)에서 `adapt_payload` 가 한 번** 모델에 맞춘다.
그래서 프레임의 `image_data` 는 여백 없는 원본(면적 상한만)이다 - 캔버스 여백 · 버킷 잘라 냄은 목에서 한다.
"""
from __future__ import annotations

import base64
import hashlib
import io
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

REFERENCE_TYPES = (
    "character&style", "character&style_anyoutfit",
    "character", "character_mainoutfit",
    "style", "costume",
)
DEFAULT_REFERENCE_TYPE = "character&style"
STRENGTH_STORE_MAX = 5.0          # 저장 · 화면 상한(모델 상한 중 큰 것). 보낼 때 모델 상한으로 다시 자른다.
SOURCE_MAX_AREA = 1536 * 1536     # 프레임에 들고 있는 원본의 면적 상한 - 4.5 캔버스(1472²) · V5 버킷(약 1MP)보다 크다


def normalize_reference_type(value: Any, default: str = DEFAULT_REFERENCE_TYPE) -> str:
    text = str(value or "").strip().lower()
    return text if text in REFERENCE_TYPES else default


def clamp_strength(value: Any, default: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if not math.isfinite(number):
        number = default
    return max(0.0, min(STRENGTH_STORE_MAX, number))


@dataclass(frozen=True)
class CrProfile:
    strength_max: float
    fidelity: bool
    outfit: bool
    bucket: bool
    inpaint: bool

    def to_payload(self) -> dict[str, Any]:
        return {"strength_max": self.strength_max, "fidelity": self.fidelity, "outfit": self.outfit,
                "bucket": self.bucket, "inpaint": self.inpaint}


V45_PROFILE = CrProfile(strength_max=1.0, fidelity=True, outfit=False, bucket=False, inpaint=True)
V5_PROFILE = CrProfile(strength_max=5.0, fidelity=False, outfit=True, bucket=True, inpaint=False)


def is_v5_medium(spec: Any) -> bool:
    return "medium" in str(getattr(spec, "api_model", "") or "").lower()


def cr_profile(spec: Any) -> CrProfile | None:
    """이 모델의 CR 사양. CR 을 못 쓰면 None."""
    if spec is None:
        return None
    profile = str(getattr(spec, "payload_profile", "") or "")
    if profile == "v4.5":
        return V45_PROFILE
    if profile == "v5" and not is_v5_medium(spec):
        return V5_PROFILE
    return None


def wire_type(ref_type: Any, profile: CrProfile) -> str | None:
    """보낼 유형 - 그 모델이 모르는 옷 유형은 웹처럼 바꾸거나(None = 이 장을 뺀다)."""
    text = normalize_reference_type(ref_type)
    if profile.outfit:
        return text
    if text == "costume":
        return None
    if text == "character_mainoutfit":
        return "character"
    if text == "character&style_anyoutfit":
        return "character&style"
    return text


def wire_strength(value: Any, profile: CrProfile) -> float:
    number = min(profile.strength_max, clamp_strength(value))
    return round(number * 20) / 20.0


# ── 이미지 ───────────────────────────────────────────────────────────────
# 웹 번들의 버킷 표 그대로(97개 · 64 단위 · 넓이 약 1MP).
BUCKETS: tuple[tuple[int, int], ...] = tuple(
    [(256, h) for h in range(4096, 3327, -64)]
    + [(320, h) for h in range(3264, 2751, -64)]
    + [(384, h) for h in range(2688, 2367, -64)]
    + [(448, h) for h in range(2304, 2111, -64)]
    + [(512, h) for h in range(2048, 1855, -64)]
    + [(576, 1792), (576, 1728), (576, 1664), (640, 1600), (640, 1536), (704, 1472), (704, 1408),
       (768, 1344), (768, 1280), (832, 1216), (896, 1152), (960, 1088), (1024, 1024),
       (1088, 960), (1152, 896), (1216, 832), (1280, 768), (1344, 768), (1408, 704), (1472, 704),
       (1536, 640), (1600, 640), (1664, 576), (1728, 576), (1792, 576)]
    + [(w, 512) for w in range(1856, 2049, 64)]
    + [(w, 448) for w in range(2112, 2305, 64)]
    + [(w, 384) for w in range(2368, 2689, 64)]
    + [(w, 320) for w in range(2752, 3265, 64)]
    + [(w, 256) for w in range(3328, 4097, 64)]
)


def bucket_geometry(width: int, height: int) -> dict[str, int | bool]:
    """웹의 버킷 계산 그대로: 비율(log)이 가장 가까운 버킷 · 덮도록 키우고 · 가운데를 잘라 낸다."""
    aspect = math.log(max(width, 1) / max(height, 1))
    best = BUCKETS[0]
    gap = abs(aspect - math.log(best[0] / best[1]))
    for bucket in BUCKETS:
        diff = abs(aspect - math.log(bucket[0] / bucket[1]))
        if diff < gap:
            best, gap = bucket, diff
    bw, bh = best
    scale = max(bw / max(width, 1), bh / max(height, 1))
    rw = max(math.floor(width * scale + 0.5), bw)
    rh = max(math.floor(height * scale + 0.5), bh)
    return {"width": bw, "height": bh, "resize_width": rw, "resize_height": rh,
            "left": (rw - bw) // 2, "top": (rh - bh) // 2, "unchanged": width == bw and height == bh}


def _png_b64(image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def source_image_data(image) -> str:
    """프레임이 들고 있을 원본(여백 없음) - 투명은 그대로 · 면적 상한만 넘으면 줄인다."""
    from PIL import Image

    source = image.convert("RGBA") if image.mode in ("RGBA", "LA", "P") and _has_alpha(image) else image.convert("RGB")
    width, height = source.size
    area = width * height
    if area > SOURCE_MAX_AREA:
        ratio = math.sqrt(SOURCE_MAX_AREA / area)
        source = source.resize((max(1, int(width * ratio)), max(1, int(height * ratio))), Image.Resampling.LANCZOS)
    return _png_b64(source)


def _has_alpha(image) -> bool:
    if image.mode in ("RGBA", "LA"):
        return True
    return image.mode == "P" and "transparency" in image.info


def canvas_fit(image) -> str:
    """V4.5: 2:3 · 3:2 · 1:1 캔버스(1024x1536 · 1536x1024 · 1472x1472)에 검은 여백으로(옛 image_data 그대로)."""
    from PIL import Image

    source = image.convert("RGBA") if image.mode == "RGBA" else image.convert("RGB")
    width, height = source.size
    aspect_ratio = width / max(1, height)
    ratios = {"2:3": (2 / 3, 1024, 1536), "3:2": (3 / 2, 1536, 1024), "1:1": (1, 1472, 1472)}
    _, canvas_width, canvas_height = min(ratios.values(), key=lambda item: abs(aspect_ratio - item[0]))
    canvas = Image.new("RGB", (canvas_width, canvas_height), (0, 0, 0))
    scale = min(canvas_width / max(1, width), canvas_height / max(1, height))
    new_width = max(1, int(width * scale))
    new_height = max(1, int(height * scale))
    resized = source.resize((new_width, new_height), Image.Resampling.LANCZOS)
    offset = ((canvas_width - new_width) // 2, (canvas_height - new_height) // 2)
    if resized.mode == "RGBA":
        canvas.paste(resized, offset, resized)
    else:
        canvas.paste(resized, offset)
    return _png_b64(canvas)


_CANVAS_SIZES = {(1024, 1536), (1536, 1024), (1472, 1472)}


def bucket_fit(image) -> str:
    """V5: 버킷에 덮어 맞추고 가운데를 잘라 낸다(여백 없음 · 투명 유지 - 웹과 같다)."""
    from PIL import Image

    source = image.convert("RGBA") if _has_alpha(image) else image.convert("RGB")
    if source.mode == "RGB" and source.size in _CANVAS_SIZES:
        # 옛 판이 4.5 캔버스(검은 여백)로 저장해 둔 그림(Interactive 보관 프레임) - 여백을 걷고 맞춘다.
        box = source.getbbox()
        if box and box != (0, 0, *source.size):
            source = source.crop(box)
    geo = bucket_geometry(*source.size)
    if geo["unchanged"]:
        return _png_b64(source)
    resized = source.resize((int(geo["resize_width"]), int(geo["resize_height"])), Image.Resampling.LANCZOS)
    left, top = int(geo["left"]), int(geo["top"])
    return _png_b64(resized.crop((left, top, left + int(geo["width"]), top + int(geo["height"]))))


_cache: "OrderedDict[tuple[str, str], str]" = OrderedDict()
_cache_lock = threading.Lock()
_CACHE_SIZE = 24


def fit_image_data(image_b64: str, profile: CrProfile) -> str:
    """보낼 그림 - 모델에 맞춘다(같은 그림은 기억해 두고 다시 안 그린다 · Auto Gen)."""
    from PIL import Image

    mode = "bucket" if profile.bucket else "canvas"
    key = (hashlib.sha1(image_b64.encode("ascii", "ignore")).hexdigest(), mode)
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
            return hit
    try:
        with Image.open(io.BytesIO(base64.b64decode(image_b64))) as opened:
            opened.load()
            fitted = bucket_fit(opened) if profile.bucket else canvas_fit(opened)
    except Exception as exc:  # 맞추기 실패로 생성을 깨지 않는다 - 받은 그대로 보낸다
        print(f"[CR] image fit skipped: {type(exc).__name__}")
        return image_b64
    with _cache_lock:
        _cache[key] = fitted
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return fitted


DIRECTOR_LIST_FIELDS = (
    "director_reference_descriptions", "director_reference_images", "director_reference_information_extracted",
    "director_reference_strength_values", "director_reference_secondary_strength_values",
)


def strip_payload(api_parameters: dict[str, Any]) -> None:
    for key in DIRECTOR_LIST_FIELDS:
        api_parameters.pop(key, None)


def adapt_payload(api_parameters: dict[str, Any], spec: Any, *, inpainting: bool = False) -> list[str]:
    """요청 목에서 한 번 - CR 필드를 이 모델의 사양으로 바꾼다. 무엇을 바꿨는지 짧은 글로 돌려준다(로그)."""
    images = api_parameters.get("director_reference_images")
    if not images:
        return []
    profile = cr_profile(spec)
    if profile is None:
        strip_payload(api_parameters)
        return ["이 모델은 Character Reference 를 받지 않는다 - 뺐다"]
    if inpainting and not profile.inpaint:
        strip_payload(api_parameters)
        return ["V5 인페인트는 Character Reference 를 받지 않는다(웹과 같다) - 뺐다"]
    count = len(images)
    lists = {key: list(api_parameters.get(key) or []) for key in DIRECTOR_LIST_FIELDS}
    if any(len(values) != count for values in lists.values()):
        return ["CR 목록 길이가 서로 달라 손대지 않았다"]
    notes: list[str] = []
    out = {key: [] for key in DIRECTOR_LIST_FIELDS}
    for index in range(count):
        description = lists["director_reference_descriptions"][index]
        caption = (description or {}).get("caption") if isinstance(description, dict) else None
        raw_type = (caption or {}).get("base_caption") if isinstance(caption, dict) else None
        sent_type = wire_type(raw_type, profile)
        if sent_type is None:
            notes.append(f"R{index + 1}: Outfit 은 이 모델에서 못 쓴다 - 뺐다")
            continue
        out["director_reference_descriptions"].append(
            {"caption": {"base_caption": sent_type, "char_captions": []}, "legacy_uc": False})
        out["director_reference_images"].append(fit_image_data(str(images[index]), profile))
        out["director_reference_information_extracted"].append(lists["director_reference_information_extracted"][index])
        out["director_reference_strength_values"].append(
            wire_strength(lists["director_reference_strength_values"][index], profile))
        secondary = lists["director_reference_secondary_strength_values"][index]
        out["director_reference_secondary_strength_values"].append(
            max(0.0, min(1.0, float(secondary or 0.0))) if profile.fidelity else 0.0)
    if not out["director_reference_images"]:
        strip_payload(api_parameters)
        notes.append("보낼 CR 이 남지 않았다")
        return notes
    api_parameters.update(out)
    return notes
