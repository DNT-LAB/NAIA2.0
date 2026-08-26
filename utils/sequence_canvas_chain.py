"""I.Sequence 캔버스 연쇄 — 컷을 옆에 이어 그리는 기하.

원본(`C:/VNR/NAIA2.0/tabs/turbo_event_sequence/workers/sequence_generation_worker.py`)의
방식을 헤드리스로 옮긴 것이다. 컷마다 독립 t2i 를 내는 대신, **직전 이미지를 캔버스에
붙이고 빈 절반만 inpaint 로 메꾼 뒤 새로 생긴 절반만 잘라** 다음 컷으로 쓴다.

    가로(horizontal)                     세로(vertical)
    ┌──────────────┐ 832               ┌───────┬───────┐ 1216
    │  직전 이미지  │ 608               │ 직전  │ 생성  │ 832
    ├──────────────┤ ← 검은 띠          │ 이미지 │ 영역  │
    │  생성 영역    │ 608               └───────┴───────┘
    └──────────────┘ 1216                 608     608

⚠️ **마스크는 1/8 축소본**이다. NAI 의 인페인트 마스크 규약이고, 원본도 그렇게 보낸다
   (`canvas_width // 8`). 캔버스와 같은 크기로 보내면 안 된다.

⚠️ **검은 띠로 split 을 유도한다.** 경계가 흐리면 모델이 두 칸을 한 그림으로 이어
   그려서 잘라낸 컷에 직전 그림의 꼬리가 남는다. 원본은 여기에 더해 네거티브에
   `1.5::split screen, black border ::` 를 넣어 잘라낸 컷 안에 경계가 남지 않게 한다.

가져오지 않은 것: 원본의 `keep_background`(배경 물려받기)는 YOLO 인물 분할
(`person_yolov8n-seg.pt`)로 인물 모양 마스크를 만든다. **구사양이라 안 옮긴다**
(사용자 확인 2026-08-26) - 추가 의존성을 끌어올 이유가 없다. 여기서는 평평한 반쪽
마스크만 쓴다(원본에서도 YOLO 가 실패하면 이 폴백으로 떨어진다).
"""

from __future__ import annotations

from io import BytesIO
from typing import Literal

from PIL import Image, ImageDraw

Direction = Literal["horizontal", "vertical"]

# 1컷(t2i) 해상도 — 캔버스에 붙일 때의 비율과 맞아야 크롭 손실이 적다.
SAMPLE_SIZE: dict[str, tuple[int, int]] = {
    "horizontal": (1152, 832),
    "vertical": (832, 1152),
}

# 2컷~ 인페인트 캔버스. 생성 방향으로 정확히 두 배다.
CANVAS_SIZE: dict[str, tuple[int, int]] = {
    "horizontal": (832, 1216),
    "vertical": (1216, 832),
}

# 직전 이미지를 붙일 영역 = 캔버스의 정확히 절반.
PASTE_SIZE: dict[str, tuple[int, int]] = {
    "horizontal": (832, 608),
    "vertical": (608, 832),
}

# split 유도용 검은 띠. 절반 경계(608) 바로 앞 8px 을 칠한다.
SEAM_BAND_PX = 8

# 마스크 축소 배율(NAI 인페인트 규약).
MASK_SCALE = 8


def _half(direction: Direction) -> int:
    width, height = CANVAS_SIZE[direction]
    return height // 2 if direction == "horizontal" else width // 2


def resize_and_crop(image: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """비율을 지키며 target 을 꽉 채우도록 리사이즈한 뒤 가운데를 자른다."""
    src_w, src_h = image.size
    if src_w <= 0 or src_h <= 0:
        return image.resize((target_w, target_h), Image.Resampling.LANCZOS)
    scale = max(target_w / src_w, target_h / src_h)
    new_w = max(target_w, int(round(src_w * scale)))
    new_h = max(target_h, int(round(src_h * scale)))
    resized = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def build_canvas(prev_image: Image.Image, direction: Direction = "horizontal") -> Image.Image:
    """직전 이미지를 절반에 붙이고 나머지 절반은 검게 비워 둔 인페인트 캔버스."""
    canvas_w, canvas_h = CANVAS_SIZE[direction]
    paste_w, paste_h = PASTE_SIZE[direction]

    source = prev_image
    if hasattr(source, "load"):
        source.load()
    if source.mode != "RGB":
        source = source.convert("RGB")

    canvas = Image.new("RGB", (canvas_w, canvas_h), (0, 0, 0))
    canvas.paste(resize_and_crop(source, paste_w, paste_h), (0, 0))

    half = _half(direction)
    draw = ImageDraw.Draw(canvas)
    if direction == "horizontal":
        draw.rectangle([(0, half - SEAM_BAND_PX), (canvas_w, half)], fill=(0, 0, 0))
    else:
        draw.rectangle([(half - SEAM_BAND_PX, 0), (half, canvas_h)], fill=(0, 0, 0))
    return canvas


def build_mask(direction: Direction = "horizontal") -> Image.Image:
    """생성할 절반만 흰색인 1/8 축소 마스크."""
    canvas_w, canvas_h = CANVAS_SIZE[direction]
    mask_w, mask_h = canvas_w // MASK_SCALE, canvas_h // MASK_SCALE
    mask = Image.new("L", (mask_w, mask_h), 0)
    if direction == "horizontal":
        mask.paste(255, (0, mask_h // 2, mask_w, mask_h))
    else:
        mask.paste(255, (mask_w // 2, 0, mask_w, mask_h))
    return mask


def crop_result(result: Image.Image, direction: Direction = "horizontal") -> Image.Image:
    """인페인트 결과에서 **새로 생긴 절반**만 잘라낸다. 그것이 이번 컷이고 다음 컷의 씨앗이다."""
    canvas_w, canvas_h = result.size
    if direction == "horizontal":
        return result.crop((0, canvas_h // 2, canvas_w, canvas_h))
    return result.crop((canvas_w // 2, 0, canvas_w, canvas_h))


def _png_bytes(image: Image.Image) -> bytes:
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def inpaint_payload(prev_image: Image.Image, direction: Direction = "horizontal") -> dict:
    """다음 컷의 인페인트 오버라이드. `strength`/`noise` 는 레퍼런스 인셋과 같은 근거다
    (공식 문서: strength=1 이라야 프롬프트 변경이 지배한다)."""
    canvas = build_canvas(prev_image, direction)
    canvas_w, canvas_h = canvas.size
    return {
        "type": "inpaint",
        "image_bytes": _png_bytes(canvas),
        "mask_bytes": _png_bytes(build_mask(direction)),
        "width": canvas_w,
        "height": canvas_h,
        "strength": 1.0,
        "noise": 0.0,
        "add_original_image": True,
    }
