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

import math
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


def placed_size(base_image: Image.Image, scale: Any) -> tuple[int, int]:
    """확대만 먹였을 때의 크기. `transform_base` 와 **같은 식**으로 센다.

    회전한 뒤의 크기는 `rotated_size` 가 따로 센다 - 그쪽은 PIL 의 행렬과 반올림을
    그대로 옮겨야 맞는다(순진한 공식은 어긋난다. 그 함수 주석 참조).
    """
    factor = clamp_scale(scale)
    return (max(1, int(round(base_image.width * factor))),
            max(1, int(round(base_image.height * factor))))


def scaled_visible_part(
    base_image: Image.Image, placed_w: int, placed_h: int,
    canvas_w: int, canvas_h: int, offset_x: int, offset_y: int,
) -> tuple[Image.Image | None, int, int]:
    """확대한 그림 중 **캔버스에 걸리는 부분만** 만든다. `(그림, 붙일 x, 붙일 y)`.

    ⚠️ 이게 이 파일에서 제일 값진 최적화다. 예전에는 4배 확대에서 3840x4352(16.7M
       픽셀)를 통째로 만든 뒤 960x1088 캔버스에 붙였다 - 만든 것의 **94% 를 즉시
       버렸다.** 실측(2026-08-27, 960x1088 베이스): 4배 확대 한 번이 230ms 였고 그중
       227ms 가 이 리샘플이었다.

    PIL 의 `resize(size, box=...)` 는 원본의 일부만 리샘플한다. 보이는 사각형만
    캔버스 해상도로 뽑으면 비용이 **배율과 무관**해진다: 4배 199ms -> 20ms.
    `compose_canvas` 와 `uncovered_mask` 는 어차피 붙이기만 하고 캔버스 밖은 PIL 이
    잘라내므로, 잘려 나갈 것을 애초에 안 만드는 것뿐이다.

    ⚠️ **완전히 같지는 않다.** 배율이 정수가 아니면(1.5x, 3x 등) box 의 끝이 원본의
       소수 좌표에 떨어져 LANCZOS 필터의 위상이 미세하게 달라진다 - 실측: 채널당
       **최대 1/255**, 그것도 일부 픽셀에서만. 기하(놓인 크기·오프셋)와 **마스크
       바이트는 완전히 동일**하다. 즉 NAI 가 무엇을 다시 그릴지는 한 치도 안 바뀌고,
       눈에 보이는 차이도 없다. 회귀 테스트가 이 경계(<=1)를 못 박는다.
    """
    left = max(0, -int(offset_x))
    top = max(0, -int(offset_y))
    right = min(int(placed_w), int(canvas_w) - int(offset_x))
    bottom = min(int(placed_h), int(canvas_h) - int(offset_y))
    if right <= left or bottom <= top:
        return None, 0, 0
    # 원본 좌표로 되돌린다. 배율이 아니라 **실제 놓인 크기**로 나눠야 반올림까지 맞는다.
    source = base_image if base_image.mode in ("RGB", "RGBA") else base_image.convert("RGB")
    if (placed_w, placed_h) == (source.width, source.height):
        # 확대도 축소도 아니면 리샘플할 것이 없다 - 잘라내기만 한다(예전 경로도
        # `transform_base` 에서 resize 를 건너뛰었다. 여기서도 건너뛰어야 1.0배가
        # 예전보다 느려지지 않는다).
        if (left, top, right, bottom) == (0, 0, source.width, source.height):
            return source, int(offset_x), int(offset_y)      # 통째로 보인다 - 복사도 아깝다
        return source.crop((left, top, right, bottom)), int(offset_x) + left, int(offset_y) + top
    sx = source.width / float(placed_w)
    sy = source.height / float(placed_h)
    box = (left * sx, top * sy, right * sx, bottom * sy)
    visible = source.resize((right - left, bottom - top), Image.Resampling.LANCZOS, box=box)
    return visible, int(offset_x) + left, int(offset_y) + top


# PIL 의 회전을 **픽셀을 돌리지 않고** 따라 계산하기 위한 두 함수.
#
# ⚠️ 이 파일에는 오래도록 "회전 상자는 미리 못 센다" 는 주석이 있었다. 절반만 맞다:
#    **순진한 `|w·cos| + |h·sin|` 공식은 어긋난다**(실측 600 조합 중 373 건이 1px 차).
#    PIL 은 픽셀 처리 전에 네 모서리만 변환해 `ceil(max) - floor(min)` 로 크기를
#    정하므로(Pillow 10.4.0 `Image.py:2460-2469`), **그 계산을 그대로 옮기면 정확하다**
#    (같은 600 조합 0 건 차이). 아래 두 함수가 그 옮긴 것이다.
# ⚠️ 그래서 Pillow 판올림 때 이 계약이 깨질 수 있다. 회귀 테스트가 PIL 과 전수 대조한다.


def rotation_matrix(width: int, height: int, angle: float) -> list[float]:
    """PIL `rotate(angle, expand=True)` 가 쓰는 **역 아핀 행렬**(목적지 -> 원본).

    Pillow 10.4.0 `Image.py:2431-2474` 를 그대로 옮긴다 - 15자리 반올림과 중심
    기준 평행이동까지. 한 자리라도 다르면 픽셀이 어긋난다.
    """
    rad = -math.radians(angle)
    matrix = [round(math.cos(rad), 15), round(math.sin(rad), 15), 0.0,
              round(-math.sin(rad), 15), round(math.cos(rad), 15), 0.0]

    def apply(x: float, y: float) -> tuple[float, float]:
        a, b, c, d, e, f = matrix
        return a * x + b * y + c, d * x + e * y + f

    center_x, center_y = width / 2, height / 2
    matrix[2], matrix[5] = apply(-center_x, -center_y)
    matrix[2] += center_x
    matrix[5] += center_y

    corners = [apply(x, y) for x, y in
               ((0, 0), (width, 0), (width, height), (0, height))]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    new_w = math.ceil(max(xs)) - math.floor(min(xs))
    new_h = math.ceil(max(ys)) - math.floor(min(ys))
    # expand 보정: 목적지 원점이 옮겨진 만큼 평행이동을 다시 잡는다.
    matrix[2], matrix[5] = apply(-(new_w - width) / 2.0, -(new_h - height) / 2.0)
    return matrix


def rotated_size(width: int, height: int, angle: Any) -> tuple[int, int]:
    """`rotate(angle, expand=True)` 의 출력 크기. 픽셀은 만들지 않는다."""
    angle = normalize_rotation(angle) % 360.0
    if angle in (0.0, 180.0):
        return int(width), int(height)
    if angle in (90.0, 270.0):
        return int(height), int(width)
    rad = -math.radians(angle)
    matrix = [round(math.cos(rad), 15), round(math.sin(rad), 15), 0.0,
              round(-math.sin(rad), 15), round(math.cos(rad), 15), 0.0]

    def apply(x: float, y: float) -> tuple[float, float]:
        a, b, c, d, e, f = matrix
        return a * x + b * y + c, d * x + e * y + f

    center_x, center_y = width / 2, height / 2
    matrix[2], matrix[5] = apply(-center_x, -center_y)
    matrix[2] += center_x
    matrix[5] += center_y
    corners = [apply(x, y) for x, y in
               ((0, 0), (width, 0), (width, height), (0, height))]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return (math.ceil(max(xs)) - math.floor(min(xs)),
            math.ceil(max(ys)) - math.floor(min(ys)))


def rotated_visible_part(
    scaled: Image.Image, angle: float, rotated_w: int, rotated_h: int,
    canvas_w: int, canvas_h: int, offset_x: int, offset_y: int,
) -> tuple[Image.Image | None, int, int]:
    """돌린 그림 중 **캔버스에 걸리는 부분만** 만든다. `(그림, 붙일 x, 붙일 y)`.

    ⚠️ 실측(2026-08-27, 960x1088 베이스): 4배 확대 + 33.5° 회전은 5606x5750 =
       **32.2M 픽셀**을 만들어 캔버스가 쓰는 1.04M(3.2%)만 남기고 버렸다.
       회전 단계에만 1049ms 가 들었다.

    ⚠️ **근사가 아니다.** `rotate()` 자체가 `transform(size, AFFINE, matrix)` 이므로
       (Pillow `Image.py:2477-2479`), 같은 행렬에 목적지 원점만 옮겨 창을 좁히면
       각 픽셀이 **완전히 같은 자리를 같은 필터로** 샘플링한다. 잘려 나갈 픽셀을
       애초에 안 만드는 것뿐이다.
    """
    left = max(0, -int(offset_x))
    top = max(0, -int(offset_y))
    right = min(int(rotated_w), int(canvas_w) - int(offset_x))
    bottom = min(int(rotated_h), int(canvas_h) - int(offset_y))
    if right <= left or bottom <= top:
        return None, 0, 0
    matrix = rotation_matrix(scaled.width, scaled.height, float(angle))
    # 목적지 원점을 창의 좌상단으로 옮긴다(행렬은 목적지 -> 원본이므로 평행이동만 더한다).
    a, b, c, d, e, f = matrix
    shifted = [a, b, a * left + b * top + c, d, e, d * left + e * top + f]
    visible = scaled.convert("RGBA").transform(
        (right - left, bottom - top), Image.Transform.AFFINE, shifted,
        Image.Resampling.BICUBIC, fillcolor=(0, 0, 0, 0),
    )
    return visible, int(offset_x) + left, int(offset_y) + top


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

    ⚠️ 크기는 **픽셀을 만들기 전에** 센다. 확대만이면 한 줄이고(`placed_size`),
       회전이 있으면 PIL 의 행렬을 그대로 옮겨 센다(`rotated_size`).
       한때 여기에는 "회전 상자는 미리 못 센다" 고 적혀 있었는데 절반만 맞았다 -
       순진한 공식은 어긋나지만 PIL 의 계산을 옮기면 정확하다(그 함수 주석 참조).
       크기를 먼저 알아야 **보이는 부분만** 만들 수 있다.
    """
    # 크기를 먼저 세어 두면 그림 전체를 만들지 않고 **캔버스에 걸리는 부분만** 뽑아
    # 붙일 수 있다(`scaled_visible_part` / `rotated_visible_part` 주석 참조).
    angle = normalize_rotation(rotation)
    turning = bool(angle)
    scaled_w, scaled_h = placed_size(base_image, scale)
    if turning:
        # 회전 상자도 **픽셀을 돌리지 않고** 정확히 센다(`rotated_size` 주석 참조).
        placed_w, placed_h = rotated_size(scaled_w, scaled_h, angle)
    else:
        placed_w, placed_h = scaled_w, scaled_h

    if anchor is not None:
        anchor_x, anchor_y, ratio_u, ratio_v = anchor
        offset_x = int(round(anchor_x - ratio_u * placed_w))
        offset_y = int(round(anchor_y - ratio_v * placed_h))
    offset_x, offset_y = clamp_offset(
        canvas_w, canvas_h, placed_w, placed_h, offset_x, offset_y
    )

    if turning and angle % 90.0 == 0.0:
        # ⚠️ **직각은 옛 경로 그대로.** PIL 은 0/90/180/270 에서 리샘플이 아니라
        #    `transpose`(정확한 픽셀 순열)를 쓴다(Pillow `Image.py:2404-2411`).
        #    같은 각도를 아핀으로 태우면 알파 경계에서 보간이 달라 어긋난다
        #    (실측: 90°/180° + 알파에서 42·60 픽셀이 1 씩 차이).
        #    transpose 는 리샘플이 아니라 4배에서도 수십 ms 다.
        placed = transform_base(base_image, scale, angle)
        visible, paste_x, paste_y = placed, offset_x, offset_y
    elif turning:
        # 확대는 아직 전체를 만든다 - 그 단계까지 창으로 좁히면 LANCZOS 의 필터
        # 위상이 달라져(측정: 채널당 1) 회전 결과가 예전과 어긋난다.
        # 회전 단계만 좁혀도 4배에서 1049ms -> 캔버스 크기로 떨어진다.
        scaled = transform_base(base_image, scale, 0.0)
        visible, paste_x, paste_y = rotated_visible_part(
            scaled, angle, placed_w, placed_h, canvas_w, canvas_h, offset_x, offset_y
        )
    else:
        visible, paste_x, paste_y = scaled_visible_part(
            base_image, placed_w, placed_h, canvas_w, canvas_h, offset_x, offset_y
        )

    if visible is None:
        # 화면 밖으로 완전히 나갔다 - `clamp_offset` 이 막지만, 막지 못한 판이
        # 오더라도 캔버스는 비어 있을 뿐 예외가 나면 안 된다.
        canvas = Image.new("RGB", (int(canvas_w), int(canvas_h)), CANVAS_BACKGROUND)
        gap = Image.new("L", (int(canvas_w), int(canvas_h)), 255)
    else:
        canvas = compose_canvas(visible, canvas_w, canvas_h, paste_x, paste_y)
        gap = uncovered_mask(
            canvas_w, canvas_h, visible.width, visible.height, paste_x, paste_y,
            coverage=coverage_mask(visible),
        )
    if mask_is_empty(gap):
        gap = None
    # `mask_image` 는 **부풀리기 전**의 기하다 - `_auto_mask` 가 "빈 곳이 있나" 를
    # 판정하는 데만 쓴다. 실제로 나가는 것은 아래 `mask_bytes` 다.
    merged = merge_masks(user_mask, gap) if (user_mask is not None or gap is not None) else None
    # ⚠️ **빈 곳은 여기서도 16px 부풀린다**(사용자 제보 2026-08-29).
    #    [자동 마스킹] 버튼은 `빈 곳 + 16px` 로 칠하는데, 생성 시 자동 병합은 빈 곳을
    #    **그대로** 실어 보내고 있었다 - 규격이 갈렸다. 빈 곳만 딱 열면 이음매가 남고,
    #    캔버스 배경이 중간 회색(128,128,128)이라 그 이음매가 **회색 액자**로 굳는다.
    #    (`_auto_mask` 주석이 이미 같은 이유를 적어 뒀다 - 한쪽에만 적용돼 있었다.)
    # ⚠️ 부풀리는 것은 **빈 곳뿐**이다. 손으로 칠한 것까지 부풀리면 사용자가 그린
    #    범위가 말없이 커진다.
    # ⚠️ 1/8 로 줄인 뒤에 부풀린다 - 캔버스 크기에서 16px 커널을 돌리면 수천만 번이다
    #    (`_auto_mask` 와 같은 이유·같은 순서).
    gap_small = downscale_mask(gap) if gap is not None else None
    if gap_small is not None:
        gap_small = dilate_mask(gap_small, AUTO_MASK_RADIUS_PX, scale=MASK_SCALE)
    user_small = downscale_mask(user_mask) if user_mask is not None else None
    merged_small = merge_masks(user_small, gap_small)
    return {
        "canvas_image": canvas,
        # ⚠️ 굽는 데 62ms 든다(실측, 일러스트급 832x1216). 조작 중에는 필요 없다 -
        #    화면은 미리보기만 보고, 이건 생성할 때 실려 나가는 물건이다.
        "canvas_bytes": png_bytes(canvas) if encode_canvas else b"",
        "mask_image": merged,
        "mask_bytes": png_bytes(merged_small) if merged_small is not None else b"",
        "width": int(canvas.width),
        "height": int(canvas.height),
        "offset_x": offset_x,
        "offset_y": offset_y,
        "placed_width": int(placed_w),
        "placed_height": int(placed_h),
        "scale": clamp_scale(scale),
        "rotation": normalize_rotation(rotation),
        "has_mask": merged is not None and not mask_is_empty(merged),
    }
