"""V5 인페인트 가상 캔버스 — 결과 이미지를 캔버스 위에 올리고 빈 곳을 열어 준다.

V5 에서는 인페인트를 별도 팝업으로 빼지 않고 Result 안에서 바로 고친다(사용자 지정
2026-08-26). 그러려면 "이미지 = 캔버스" 라는 기존 전제를 깨야 한다. 베이스 이미지를
캔버스 안에서 **옮길 수 있어야** 하고(왼쪽으로 밀고 오른쪽에 인물을 새로 넣는 식),
비게 된 자리는 자동으로 편집 가능해야 한다.

    캔버스 1216x832, 베이스 832x1216 을 x=-120 으로 민 경우

    ┌───────────────┬───────────────┐
    │  베이스(보존)  │  빈 곳(생성)   │   ← 자동으로 마스크가 열린다
    └───────────────┴───────────────┘
      offset.x 만큼 밀림

⚠️ **마스크는 두 겹이다.** 사용자가 칠한 것(canvas 좌표)과, 베이스가 덮지 못한 빈 곳.
   빈 곳을 안 열면 그 자리가 배경색 그대로 남는다 - 옮긴 의미가 없다.

⚠️ 좌표계는 전부 **캔버스 기준**이다. 베이스 기준으로 섞어 쓰면 offset 이 0 이 아닐 때
   마스크와 캐릭터 좌표가 서로 다른 곳을 가리킨다.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from PIL import Image

# 캔버스 배경. 마스크가 열려 있으므로 실제로는 다시 그려지지만, 열리지 않은 자리가
# 남았을 때 눈에 띄라고 중간 회색을 쓴다(검정은 그림자와 헷갈린다).
CANVAS_BACKGROUND = (128, 128, 128)

# 베이스를 아무리 밀어도 이만큼은 캔버스 안에 남긴다. 전부 밀어내면 인페인트가 아니라
# 그냥 t2i 이고, 되돌릴 방법도 화면에서 사라진다.
MIN_VISIBLE_PX = 64

# NAI 인페인트 마스크 축소 배율.
MASK_SCALE = 8


def clamp_offset(
    canvas_w: int, canvas_h: int, base_w: int, base_h: int, x: Any, y: Any
) -> tuple[int, int]:
    """베이스가 캔버스 밖으로 완전히 나가지 않도록 오프셋을 가둔다."""
    try:
        off_x = int(round(float(x)))
    except (TypeError, ValueError):
        off_x = 0
    try:
        off_y = int(round(float(y)))
    except (TypeError, ValueError):
        off_y = 0
    keep_x = min(MIN_VISIBLE_PX, base_w)
    keep_y = min(MIN_VISIBLE_PX, base_h)
    off_x = max(-(base_w - keep_x), min(canvas_w - keep_x, off_x))
    off_y = max(-(base_h - keep_y), min(canvas_h - keep_y, off_y))
    return off_x, off_y


def compose_canvas(
    base_image: Image.Image, canvas_w: int, canvas_h: int, offset_x: int, offset_y: int
) -> Image.Image:
    """베이스를 오프셋 위치에 올린 캔버스. 나머지는 배경색."""
    canvas = Image.new("RGB", (int(canvas_w), int(canvas_h)), CANVAS_BACKGROUND)
    source = base_image
    if source.mode != "RGB":
        source = source.convert("RGB")
    canvas.paste(source, (int(offset_x), int(offset_y)))
    return canvas


def uncovered_mask(
    canvas_w: int, canvas_h: int, base_w: int, base_h: int, offset_x: int, offset_y: int
) -> Image.Image:
    """베이스가 덮지 못한 자리만 흰색(=생성)인 캔버스 크기 마스크."""
    mask = Image.new("L", (int(canvas_w), int(canvas_h)), 255)
    covered = Image.new("L", (int(base_w), int(base_h)), 0)
    mask.paste(covered, (int(offset_x), int(offset_y)))
    return mask


def merge_masks(*masks: Image.Image | None) -> Image.Image | None:
    """여러 마스크를 합친다(하나라도 열려 있으면 열린다). 크기가 다르면 첫 것에 맞춘다."""
    layers = [m for m in masks if m is not None]
    if not layers:
        return None
    base = layers[0].convert("L")
    for layer in layers[1:]:
        other = layer.convert("L")
        if other.size != base.size:
            other = other.resize(base.size, Image.Resampling.NEAREST)
        base = Image.composite(Image.new("L", base.size, 255), base,
                               other.point(lambda v: 255 if v >= 128 else 0))
    return base


def downscale_mask(mask: Image.Image, scale: int = MASK_SCALE) -> Image.Image:
    """NAI 규약대로 1/scale 로 줄인다. 캔버스 크기 그대로 보내면 안 된다."""
    width = max(1, mask.width // scale)
    height = max(1, mask.height // scale)
    return mask.convert("L").resize((width, height), Image.Resampling.NEAREST)


def mask_is_empty(mask: Image.Image | None) -> bool:
    if mask is None:
        return True
    return not mask.convert("L").getbbox()


def to_canvas_position(
    canvas_w: int, canvas_h: int, x: Any, y: Any
) -> dict[str, float] | None:
    """캔버스 픽셀 좌표를 NAI 가 쓰는 0~1 비율로. 범위를 벗어나면 잘라 넣는다."""
    try:
        px = float(x)
        py = float(y)
    except (TypeError, ValueError):
        return None
    if canvas_w <= 0 or canvas_h <= 0:
        return None
    return {
        "x": round(min(1.0, max(0.0, px / canvas_w)), 3),
        "y": round(min(1.0, max(0.0, py / canvas_h)), 3),
    }


def png_bytes(image: Image.Image) -> bytes:
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def build_payload(
    base_image: Image.Image,
    *,
    canvas_w: int,
    canvas_h: int,
    offset_x: int,
    offset_y: int,
    user_mask: Image.Image | None = None,
) -> dict[str, Any]:
    """인페인트 요청에 실을 캔버스/마스크 한 벌.

    마스크는 **사용자가 칠한 것 + 베이스가 못 덮은 빈 곳**을 합친 것이다.
    """
    offset_x, offset_y = clamp_offset(
        canvas_w, canvas_h, base_image.width, base_image.height, offset_x, offset_y
    )
    canvas = compose_canvas(base_image, canvas_w, canvas_h, offset_x, offset_y)
    gap = uncovered_mask(
        canvas_w, canvas_h, base_image.width, base_image.height, offset_x, offset_y
    )
    if mask_is_empty(gap):
        gap = None
    merged = merge_masks(user_mask, gap) if (user_mask is not None or gap is not None) else None
    return {
        "canvas_image": canvas,
        "canvas_bytes": png_bytes(canvas),
        "mask_image": merged,
        "mask_bytes": png_bytes(downscale_mask(merged)) if merged is not None else b"",
        "width": int(canvas.width),
        "height": int(canvas.height),
        "offset_x": offset_x,
        "offset_y": offset_y,
        "has_mask": merged is not None and not mask_is_empty(merged),
    }
