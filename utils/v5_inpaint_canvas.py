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

# `자동 마스킹` 이 빈 곳 바깥으로 더 물고 들어가는 폭(캔버스 픽셀).
# ⚠️ 빈 곳만 딱 열면 **경계선이 그대로 남는다.** 베이스를 밀거나 돌린 자리에는 늘
#    이음매가 생기고, 그 위를 조금 덮어야 모델이 이어 그린다(사용자 지정 2026-08-26:
#    "빈칸 + 빈칸과 겹친 모서리(약 16px 이상)").
AUTO_MASK_RADIUS_PX = 16


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


# 베이스 확대/축소 한계. 너무 줄이면 캔버스에 점만 남고, 너무 키우면 합성이 느려진다.
MIN_SCALE = 0.1
MAX_SCALE = 4.0


def clamp_scale(value: Any) -> float:
    try:
        scale = float(value)
    except (TypeError, ValueError):
        return 1.0
    if scale != scale or scale <= 0:      # NaN 방어
        return 1.0
    return round(min(MAX_SCALE, max(MIN_SCALE, scale)), 4)


def normalize_rotation(value: Any) -> float:
    """0~360 으로 접는다. 임의 각도를 받는다 - 90도 배수로 제한하지 않는다."""
    try:
        angle = float(value)
    except (TypeError, ValueError):
        return 0.0
    if angle != angle:
        return 0.0
    return round(angle % 360.0, 2)


def transform_base(base_image: Image.Image, scale: Any = 1.0, rotation: Any = 0.0) -> Image.Image:
    """베이스에 확대/회전을 먹인다. 회전하면 **RGBA** 로 나온다.

    ⚠️ 회전은 `expand=True` 다. 안 그러면 기울인 모서리가 잘려 나간다 - 사용자는
       '회전했더니 그림이 깎였다' 로만 본다.
    ⚠️ 회전으로 생기는 삼각형 여백은 **투명**으로 남긴다. 예전에는 캔버스 배경색으로
       채웠는데, 그러면 `uncovered_mask` 가 그 쐐기까지 '덮인 곳' 으로 세어 **영영
       다시 그려지지 않는다** - 화면에는 회색 삼각형으로 남는다(사용자 제보 2026-08-26).
       색은 어차피 `compose_canvas` 가 배경 위에 얹어 같아 보인다.
    """
    source = base_image if base_image.mode in ("RGB", "RGBA") else base_image.convert("RGB")
    factor = clamp_scale(scale)
    if factor != 1.0:
        width = max(1, int(round(source.width * factor)))
        height = max(1, int(round(source.height * factor)))
        source = source.resize((width, height), Image.Resampling.LANCZOS)
    angle = normalize_rotation(rotation)
    if angle:
        source = source.convert("RGBA").rotate(
            angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(0, 0, 0, 0)
        )
    return source


def coverage_mask(image: Image.Image) -> Image.Image:
    """이 그림이 **실제로 색을 칠하는** 자리(흰색). 투명한 곳은 검정."""
    if image.mode == "RGBA":
        return image.getchannel("A").point(lambda v: 255 if v >= 128 else 0, "L")
    return Image.new("L", image.size, 255)


def dilate_mask(mask: Image.Image, radius_px: Any, scale: int = 1) -> Image.Image:
    """마스크를 바깥으로 `radius_px` 만큼 부풀린다.

    `scale` 은 마스크가 이미 줄어든 배율이다(1/8 마스크면 8) - 반지름을 그 배율로
    나눠 **캔버스 픽셀 기준**으로 맞춘다.
    """
    from PIL import ImageFilter

    try:
        radius = int(round(float(radius_px) / max(1, int(scale))))
    except (TypeError, ValueError):
        return mask
    if radius <= 0:
        return mask
    return mask.convert("L").filter(ImageFilter.MaxFilter(2 * radius + 1))


def compose_canvas(
    base_image: Image.Image, canvas_w: int, canvas_h: int, offset_x: int, offset_y: int
) -> Image.Image:
    """베이스를 오프셋 위치에 올린 캔버스. 나머지는 배경색.

    베이스는 이미 `transform_base` 를 거친 것을 넘겨야 한다 - 여기서는 붙이기만 한다.
    """
    canvas = Image.new("RGB", (int(canvas_w), int(canvas_h)), CANVAS_BACKGROUND)
    source = base_image
    if source.mode == "RGBA":
        # 투명한 곳(회전 여백)은 배경이 그대로 비친다 - 색은 예전과 같아 보이지만
        # `uncovered_mask` 는 이제 그곳을 빈 곳으로 셀 수 있다.
        canvas.paste(source, (int(offset_x), int(offset_y)), source)
        return canvas
    if source.mode != "RGB":
        source = source.convert("RGB")
    canvas.paste(source, (int(offset_x), int(offset_y)))
    return canvas


def uncovered_mask(
    canvas_w: int, canvas_h: int, base_w: int, base_h: int, offset_x: int, offset_y: int,
    coverage: Image.Image | None = None,
) -> Image.Image:
    """베이스가 덮지 못한 자리만 흰색(=생성)인 캔버스 크기 마스크.

    `coverage` 를 주면 사각형 대신 **실제로 색이 칠해진 자리**를 덮인 것으로 본다.
    회전하면 놓인 상자는 사각형이지만 그림은 마름모라, 그 차이가 곧 모서리 쐐기다.
    """
    mask = Image.new("L", (int(canvas_w), int(canvas_h)), 255)
    if coverage is None:
        covered = Image.new("L", (int(base_w), int(base_h)), 0)
    else:
        covered = coverage.point(lambda v: 0 if v >= 128 else 255, "L")
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
    scale: Any = 1.0,
    rotation: Any = 0.0,
    user_mask: Image.Image | None = None,
    anchor: tuple[float, float, float, float] | None = None,
    encode_canvas: bool = True,
) -> dict[str, Any]:
    """인페인트 요청에 실을 캔버스/마스크 한 벌.

    마스크는 **사용자가 칠한 것 + 베이스가 못 덮은 빈 곳**을 합친 것이다.

    ⚠️ 확대/회전을 **먼저** 먹인다. 변형 뒤의 크기로 오프셋을 가두고 빈 곳을 재야
       한다 - 원본 크기로 재면 회전해서 커진 만큼이 빈 곳으로 잘못 잡힌다.

    `anchor=(ax, ay, u, v)` 를 주면 `offset` 을 무시하고, **캔버스의 (ax, ay) 가 놓인
    그림의 비율 좌표 (u, v) 를 계속 가리키도록** 오프셋을 새로 잡는다. 확대/회전의
    기준점이 이것이다.

    ⚠️ 크기를 미리 계산하지 않는다. `transform_base` 를 한 번 돌린 **그 결과의 크기**로
       잡는다 - 회전 상자 공식을 따로 세우면 PIL 의 반올림과 1px 씩 어긋나고, 그
       어긋남이 매 조작마다 쌓인다.
    """
    placed = transform_base(base_image, scale, rotation)
    if anchor is not None:
        anchor_x, anchor_y, ratio_u, ratio_v = anchor
        offset_x = int(round(anchor_x - ratio_u * placed.width))
        offset_y = int(round(anchor_y - ratio_v * placed.height))
    offset_x, offset_y = clamp_offset(
        canvas_w, canvas_h, placed.width, placed.height, offset_x, offset_y
    )
    canvas = compose_canvas(placed, canvas_w, canvas_h, offset_x, offset_y)
    gap = uncovered_mask(
        canvas_w, canvas_h, placed.width, placed.height, offset_x, offset_y,
        coverage=coverage_mask(placed),
    )
    if mask_is_empty(gap):
        gap = None
    merged = merge_masks(user_mask, gap) if (user_mask is not None or gap is not None) else None
    return {
        "canvas_image": canvas,
        # ⚠️ 굽는 데 62ms 든다(실측, 일러스트급 832x1216). 조작 중에는 필요 없다 -
        #    화면은 미리보기만 보고, 이건 생성할 때 실려 나가는 물건이다.
        "canvas_bytes": png_bytes(canvas) if encode_canvas else b"",
        "mask_image": merged,
        "mask_bytes": png_bytes(downscale_mask(merged)) if merged is not None else b"",
        "width": int(canvas.width),
        "height": int(canvas.height),
        "offset_x": offset_x,
        "offset_y": offset_y,
        "placed_width": int(placed.width),
        "placed_height": int(placed.height),
        "scale": clamp_scale(scale),
        "rotation": normalize_rotation(rotation),
        "has_mask": merged is not None and not mask_is_empty(merged),
    }
