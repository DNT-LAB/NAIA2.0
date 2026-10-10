"""
Reference-inset preprocessing utilities for NovelAI-style inpainting.

This module codifies the currently validated workflow:

1. Generate a tall reference image at 768x1344 using a "1koma" full-body prompt.
2. Place that image on the left side of a 1152x896 canvas.
3. Let the pasted reference bleed slightly outside the canvas on the left/top/bottom.
4. Build an inpaint mask that preserves the reference image, but re-opens a thin
   editable strip on the right edge so the model can blend across the seam.
5. Downscale the binary mask to NovelAI's 1/8-size mask format.

Why the right-edge overlap exists:
- NovelAI's inpaint docs warn that content outside the mask can leak into the
  masked area when the mask edge is too tight.
- In the opposite direction, a seam can look unnaturally hard if the editable
  area starts exactly after the preserved reference edge.
- Re-opening a narrow strip on the reference image's right edge gives the model
  a small amount of room to fuse the inset and the generated area together.

Official NovelAI docs consulted:
- Strength & Noise:
  https://docs.novelai.net/en/image/strengthnoise/
- Inpaint:
  https://docs.novelai.net/en/image/inpaint/

Important interpretation:
- The official docs explicitly describe inpaint strength and show that strength=1
  gives the prompt maximal control over the masked area.
- The official reference-inpainting guide specifically recommends keeping
  reference strength at 1 unless there is a good reason not to.
- The official docs describe "noise" for Image2Image in general, but the Inpaint
  page only documents Strength and the current web UI does not expose a Noise
  slider for inpainting.
- Because of that, this module recommends strength=1.0 and noise=0.0 for
  reference-inset inpainting by default. The noise recommendation is an
  engineering choice based on the docs plus observed UI behavior, not a direct
  low-level REST spec from NovelAI.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from io import BytesIO
from typing import Iterable, Sequence

import numpy as np
from PIL import Image, ImageDraw


def _join_tags(parts: Iterable[str]) -> str:
    """Join non-empty tag fragments with commas."""
    return ", ".join(part.strip() for part in parts if part and part.strip())


@dataclass(frozen=True)
class ReferenceGenerationSpec:
    """Prompt defaults for the initial tall reference image."""

    width: int = 768
    height: int = 1344
    base_subject: str = "1girl"
    base_tags: tuple[str, ...] = (
        "solo",
        "1koma",
        "standing",
        "looking away",
        "white background",
        "simple background",
        "centered composition",
        "occupying most of frame",
        "front view",
        "narrow margins",
        "top of head near top edge",
        "feet near bottom edge",
        "full-body portrait",
        "white seamless background",
        "rating:general",
        "safe",
    )

    def build_prompt(
        self,
        artists: Sequence[str] = (),
        reference_tags: Sequence[str] = (),
        quality_tags: Sequence[str] = (),
    ) -> str:
        return _join_tags(
            (
                self.base_subject,
                _join_tags(artists),
                _join_tags(reference_tags),
                _join_tags(self.base_tags),
                _join_tags(quality_tags),
            )
        )


# V5 에서 고를 수 있는 인셋 캔버스(사용자 지정 2026-08-25). 예전에는 1152x896 하나로
# 못 박혀 있었다. 세로 레퍼런스를 캔버스 높이에 맞춰 키워 왼쪽에 붙이므로, **캔버스가
# 넓을수록 인셋이 차지하는 비율이 줄고 생성 영역이 넓어진다** - 그게 고르는 이유다.
#
# ⚠️ 여기가 유일한 목록이다. 화면은 `reference_inset_state()` 가 실어 보내는 이 값을
#    그려야 한다 - 프런트에 표를 복사하면 한쪽만 고쳐져 서로 다른 말을 하게 된다.
#
# 비율(종류)별로 고른다(사용자 지정 2026-10-10: "종류별로 지원 - 1024x1024 · 1280x1280 · 1472x1472 …").
# 비율마다 세 급이다: **1MP(무료 대역) · Large · Wallpaper**. 값은 NAIA 의 NAI 해상도 밴드 표
# (`core/resolution_utils.NAI_RESOLUTION_PRESETS` 의 normal · large · wallpaper)에서 같은 비율의 줄을 가져왔다 -
# 가로로 쓸 수 있는 것만(세로 캔버스는 왼쪽에 칸을 둘 자리가 안 난다). 16:9 의 Large 만 그 표에 없어
# 같은 넓이대의 64 배수(1664x960)로 채웠다.
# ⚠️ 1MP 를 넘는 캔버스는 **Anlas 가 든다.** 그래서 금액 표시(`core/nai_anlas_cost.cost_params_for_context`)가
#    인셋 캔버스를 본다 - 이 목록을 늘릴 때 그 길이 살아 있는지 함께 볼 것.
# ⚠️ 1088x960 은 뺐다(사용자 지정 2026-08-25) - 세로에 가까워 인셋이 캔버스의 절반을 넘게 차지했다.
REFERENCE_INSET_CANVAS_KINDS: tuple[tuple[str, tuple[tuple[int, int], ...]], ...] = (
    ("1:1", ((1024, 1024), (1280, 1280), (1472, 1472))),
    ("9:7", ((1152, 896), (1408, 1088), (1664, 1280))),
    ("3:2", ((1216, 832), (1536, 1024), (1728, 1216))),
    ("16:9", ((1344, 768), (1664, 960), (1920, 1088))),
)
REFERENCE_INSET_CANVAS_SIZES: tuple[tuple[int, int], ...] = tuple(
    size for _label, sizes in REFERENCE_INSET_CANVAS_KINDS for size in sizes
)
DEFAULT_REFERENCE_INSET_CANVAS: tuple[int, int] = (1152, 896)


def resolve_reference_inset_canvas(width: object, height: object) -> tuple[int, int]:
    """고를 수 있는 캔버스인지 확인해 돌려준다. 목록에 없으면 기본값.

    ⚠️ 임의 크기를 받지 않는다. 이 값이 그대로 NAI 인페인트 요청의 width/height 가
       되므로, 아무 숫자나 통과시키면 **돈이 나가는 요청이 엉뚱한 크기로** 나간다.
    """
    try:
        pair = (int(width), int(height))
    except (TypeError, ValueError):
        return DEFAULT_REFERENCE_INSET_CANVAS
    return pair if pair in REFERENCE_INSET_CANVAS_SIZES else DEFAULT_REFERENCE_INSET_CANVAS


@dataclass(frozen=True)
class ReferenceInsetPreprocessSpec:
    """Layout and mask rules for the reference-inset canvas."""

    canvas_width: int = 1152
    canvas_height: int = 896
    background_rgb: tuple[int, int, int] = (255, 255, 255)

    # Empirical bleed that produced a stable inpaint region in practice.
    left_bleed_px: int = 16
    top_bleed_px: int = 16
    bottom_bleed_px: int = 16

    # Optional black border around the preserved reference inset.
    reference_border_px: int = 0
    reference_border_rgb: tuple[int, int, int] = (0, 0, 0)

    # Re-open a thin editable band on the right edge of the reference image.
    seam_overlap_px: int = 8

    # 이음매 **바로 안쪽**(보존되는 쪽)에 긋는 검은 세로선 - 칸을 가르는 테두리다
    # (사용자 지정 2026-08-25).
    #
    # ⚠️ **마스크가 열리는 쪽이 아니라 그 반대편에 긋는다.** 편집 가능한 띠 안에 그으면
    #    모델이 그 위를 덮어 버려 아무것도 안 남는다. 보존 구간에 그어야 결과에 그대로
    #    실린다.
    # ⚠️ 0 이면 긋지 않는다 - 예전 판과 같은 그림이 된다.
    seam_edge_line_px: int = 8
    seam_edge_line_rgb: tuple[int, int, int] = (0, 0, 0)
    # 그 선의 오른쪽 몇 px 을 **마스크가 덮게** 할 것인가(사용자 지정 2026-08-25).
    # 선 전체를 보존 구간에 두면 가장자리가 칼같이 서서 붙여 넣은 티가 난다 -
    # 끝을 조금 물려 두면 모델이 그 위에서 생성 영역으로 자연스럽게 넘어간다.
    # ⚠️ 이음매 띠(`seam_overlap_px`)보다 크면 안 된다 - 아래에서 잘라 준다.
    seam_edge_line_masked_px: int = 2
    # Keep disabled by default. The older rounded wrap looked acceptable in raw
    # mask math, but it becomes a visible stepped protrusion once the inpaint
    # editor quantizes the mask to NovelAI's 8x8 grid.
    seam_corner_wrap_px: int = 0

    # NovelAI uses 1/8 masks for native infill.
    mask_downscale: int = 8

    def recommended_inpaint_settings(self) -> dict[str, float]:
        """
        Recommended NovelAI inpaint defaults.

        Rationale:
        - NovelAI docs show that strength=1 lets prompt changes dominate.
        - The inpaint UI documents Strength but not an inpaint-specific Noise slider.
        - Noise is therefore kept at 0.0 to minimize artifacts in reference-inset mode.
        """
        return {
            "strength": 1.0,
            "noise": 0.0,
        }

    def recommended_novelai_parameters(self) -> dict[str, object]:
        """
        Recommended NovelAI-side parameter fragment for reference-inset inpainting.

        Notes:
        - `inpaintImg2ImgStrength=1.0` follows the official reference-inpainting guide.
        - `noise=0.0` is a conservative engineering default because the official Inpaint
          docs do not expose an inpaint-specific Noise slider, while the broader
          Image2Image docs warn that too much noise can introduce artifacts.
        """
        return {
            "add_original_image": True,
            "inpaintImg2ImgStrength": 1.0,
            "noise": 0.0,
            "reference_inset_tag_required": True,
        }


@dataclass(frozen=True)
class PlacementBox:
    """Resolved placement for the reference image on the target canvas."""

    x: int
    y: int
    width: int
    height: int
    visible_left: int
    visible_top: int
    visible_right: int
    visible_bottom: int


@dataclass(frozen=True)
class ReferenceInsetPreprocessResult:
    """All images and metadata needed for a reference-inset inpaint request."""

    canvas_image: Image.Image
    full_mask_image: Image.Image
    small_mask_image: Image.Image
    placement: PlacementBox
    canvas_width: int
    canvas_height: int
    recommended_strength: float
    recommended_noise: float

    def to_api_payload_fields(self) -> dict[str, object]:
        """Convert generated images to the core fields expected by the API layer."""
        canvas_bytes = BytesIO()
        self.canvas_image.save(canvas_bytes, format="PNG")

        full_mask_bytes = BytesIO()
        self.full_mask_image.save(full_mask_bytes, format="PNG")

        small_mask_bytes = BytesIO()
        self.small_mask_image.save(small_mask_bytes, format="PNG")

        return {
            "image_bytes": canvas_bytes.getvalue(),
            "mask_bytes": small_mask_bytes.getvalue(),
            "full_mask_bytes": full_mask_bytes.getvalue(),
            "width": self.canvas_width,
            "height": self.canvas_height,
            "strength": self.recommended_strength,
            "noise": self.recommended_noise,
        }


def build_reference_inpaint_prompt(
    artists: Sequence[str] = (),
    general_tags: Sequence[str] = (),
    quality_tags: Sequence[str] = (),
    base_subject: str = "1girl",
) -> str:
    """Build the prompt for the actual reference-inset inpaint generation."""
    return _join_tags(
        (
            base_subject,
            _join_tags(artists),
            "borderless panels",
            _join_tags(general_tags),
            _join_tags(quality_tags),
        )
    )


def prepare_reference_inpaint_canvas(
    source_image: Image.Image,
    spec: ReferenceInsetPreprocessSpec | None = None,
    box: dict | None = None,
    divider: object = None,
) -> ReferenceInsetPreprocessResult:
    """
    Create the left-anchored reference canvas and matching full/small masks.

    ``box``(칸 안의 그림 자리 · 높이) 나 ``divider``(경계선 = 칸의 너비)를 주면 **칸** 방식으로 굽는다
    (사용자 지정 2026-10-09): 왼쪽 가장자리부터 경계선까지가 칸이고, 그림은 칸 안에서만 보이며, 칸은
    흰 바탕까지 통째로 보존한다. 둘 다 안 주면 예전 그림 그대로다(높이에 꽉 채우고 그림의 끝이 경계).

    Output semantics:
    - canvas_image:
      The full 1152x896 inpaint canvas with the reference image pasted on the left.
    - full_mask_image:
      Binary mask at full canvas resolution.
      0 = preserve, 255 = editable.
    - small_mask_image:
      Binary 1/8 mask for NovelAI native infill.
    """
    spec = spec or ReferenceInsetPreprocessSpec()
    reference = source_image.convert("RGB")

    panelled = box is not None or divider is not None
    if not panelled:
        placement = _resolve_reference_placement(reference.size, spec)
    else:
        divider_px = normalize_reference_inset_divider(divider, reference.size, spec)
        placed = normalize_reference_inset_box(box, reference.size, spec, divider=divider_px)
        placement = _panel_placement(placed, divider_px, spec)

    canvas = Image.new("RGB", (spec.canvas_width, spec.canvas_height), spec.background_rgb)
    if panelled:
        # 그림은 칸 안에서만 보인다 - **보이는 부분만** 줄여(늘려) 놓는다. 통째로 줄인 뒤 자르면 안 된다.
        visible = _resize_visible_part(reference, placement)
        if visible is not None:
            canvas.paste(visible[0], visible[1])
    else:
        resized = reference.resize((placement.width, placement.height), Image.Resampling.LANCZOS)
        canvas.paste(resized, (placement.x, placement.y))

    if spec.reference_border_px > 0:
        _draw_reference_border(canvas, placement, spec)

    if not panelled:
        _draw_seam_edge_line(canvas, placement, spec)
        full_mask = _build_reference_inpaint_mask(placement, spec)
    else:
        _draw_inner_edge_lines(canvas, placement, spec)
        full_mask = _build_boxed_inpaint_mask(placement, spec)
    small_mask = _downscale_binary_mask(full_mask, spec.mask_downscale)

    recommended = spec.recommended_inpaint_settings()
    return ReferenceInsetPreprocessResult(
        canvas_image=canvas,
        full_mask_image=full_mask,
        small_mask_image=small_mask,
        placement=placement,
        canvas_width=spec.canvas_width,
        canvas_height=spec.canvas_height,
        recommended_strength=recommended["strength"],
        recommended_noise=recommended["noise"],
    )


def _resolve_reference_placement(
    source_size: tuple[int, int],
    spec: ReferenceInsetPreprocessSpec,
) -> PlacementBox:
    """Scale to the canvas height plus bleed, then anchor from the left edge."""
    src_w, src_h = source_size
    target_h = spec.canvas_height + spec.top_bleed_px + spec.bottom_bleed_px
    scale = target_h / src_h
    target_w = max(1, int(round(src_w * scale)))

    x = -spec.left_bleed_px
    y = -spec.top_bleed_px

    visible_left = max(0, x)
    visible_top = max(0, y)
    visible_right = min(spec.canvas_width, x + target_w)
    visible_bottom = min(spec.canvas_height, y + target_h)

    return PlacementBox(
        x=x,
        y=y,
        width=target_w,
        height=target_h,
        visible_left=visible_left,
        visible_top=visible_top,
        visible_right=visible_right,
        visible_bottom=visible_bottom,
    )


def _draw_reference_border(
    canvas: Image.Image,
    placement: PlacementBox,
    spec: ReferenceInsetPreprocessSpec,
) -> None:
    """Optional black border around the visible reference inset area."""
    if placement.visible_right <= placement.visible_left or placement.visible_bottom <= placement.visible_top:
        return

    draw = ImageDraw.Draw(canvas)
    for offset in range(spec.reference_border_px):
        draw.rectangle(
            (
                placement.visible_left + offset,
                placement.visible_top + offset,
                placement.visible_right - 1 - offset,
                placement.visible_bottom - 1 - offset,
            ),
            outline=spec.reference_border_rgb,
        )


def seam_edge_line_bounds(
    placement: PlacementBox,
    spec: ReferenceInsetPreprocessSpec,
) -> tuple[int, int] | None:
    """이음매 안쪽 검은 선이 차지할 x 구간 ``[left, right)``. 그을 자리가 없으면 None.

    마스크가 열리는 띠(`seam_overlap_px`)의 **왼쪽**, 즉 보존되는 쪽에 붙인다.
    선이 인셋 왼쪽 끝을 넘지 않도록 자른다.
    """
    line_px = max(0, spec.seam_edge_line_px)
    if line_px <= 0:
        return None
    if placement.visible_right <= placement.visible_left:
        return None
    seam_overlap = max(0, spec.seam_overlap_px)
    seam_left = max(placement.visible_left, placement.visible_right - seam_overlap)
    # 선을 오른쪽으로 밀어 끝 몇 px 이 이음매(편집 가능) 안으로 들어가게 한다.
    masked = max(0, min(spec.seam_edge_line_masked_px, seam_overlap, line_px))
    right = min(placement.visible_right, seam_left + masked)
    left = max(placement.visible_left, right - line_px)
    if right <= left:
        return None
    return left, right


def _draw_seam_edge_line(
    canvas: Image.Image,
    placement: PlacementBox,
    spec: ReferenceInsetPreprocessSpec,
) -> None:
    """인셋과 생성 영역을 가르는 검은 세로선(보존 구간 안쪽)."""
    bounds = seam_edge_line_bounds(placement, spec)
    if bounds is None:
        return
    left, right = bounds
    draw = ImageDraw.Draw(canvas)
    draw.rectangle(
        (left, placement.visible_top, right - 1, placement.visible_bottom - 1),
        fill=spec.seam_edge_line_rgb,
    )


def _build_reference_inpaint_mask(
    placement: PlacementBox,
    spec: ReferenceInsetPreprocessSpec,
) -> Image.Image:
    """
    Build a full-resolution binary mask.

    Preserve logic:
    - The reference inset remains preserved by default.
    - A narrow right-edge strip is reopened as editable to soften the seam.
    - Optional top-right/bottom-right rounded wraps can reopen a little more area
      around the seam corners, but they are disabled by default because the
      inpaint editor's 8x8 quantization makes them read as stepped protrusions.
    """
    mask = np.full((spec.canvas_height, spec.canvas_width), 255, dtype=np.uint8)

    if placement.visible_right <= placement.visible_left or placement.visible_bottom <= placement.visible_top:
        return Image.fromarray(mask, mode="L")

    mask[
        placement.visible_top:placement.visible_bottom,
        placement.visible_left:placement.visible_right,
    ] = 0

    seam_overlap = max(0, spec.seam_overlap_px)
    if seam_overlap > 0:
        seam_left = max(placement.visible_left, placement.visible_right - seam_overlap)
        mask[
            placement.visible_top:placement.visible_bottom,
            seam_left:placement.visible_right,
        ] = 255

    result = Image.fromarray(mask, mode="L")
    if spec.seam_corner_wrap_px > 0 and seam_overlap > 0:
        _paint_corner_wrap(
            result,
            placement=placement,
            seam_overlap=seam_overlap,
            radius=spec.seam_corner_wrap_px,
        )
    return result


def _paint_corner_wrap(
    mask: Image.Image,
    placement: PlacementBox,
    seam_overlap: int,
    radius: int,
) -> None:
    """
    Add rounded editable lobes at the top-right/bottom-right seam corners.

    This keeps the behavior local to the seam instead of rounding all four
    corners of the preserved reference rectangle.
    """
    draw = ImageDraw.Draw(mask)
    cx = placement.visible_right - seam_overlap

    top_box = (
        cx - radius,
        placement.visible_top,
        cx + radius,
        placement.visible_top + 2 * radius,
    )
    bottom_box = (
        cx - radius,
        placement.visible_bottom - 2 * radius,
        cx + radius,
        placement.visible_bottom,
    )

    draw.ellipse(top_box, fill=255)
    draw.ellipse(bottom_box, fill=255)


def _downscale_binary_mask(full_mask: Image.Image, factor: int) -> Image.Image:
    """Resize the mask to NovelAI's 1/factor resolution using hard thresholding."""
    width, height = full_mask.size
    small_w = max(1, width // factor)
    small_h = max(1, height // factor)
    small = full_mask.resize((small_w, small_h), Image.Resampling.NEAREST)
    arr = np.array(small)
    arr = np.where(arr > 127, 255, 0).astype(np.uint8)
    return Image.fromarray(arr, mode="L")


# ---------------------------------------------------------------------------
# 인셋 칸의 너비와 그 안의 그림을 사용자가 정한다(사용자 지정 2026-10-09)
# ---------------------------------------------------------------------------
# 예전: 그림을 캔버스 높이에 꽉 채워 왼쪽에 붙였고, 그림의 오른쪽 끝이 곧 경계였다(한 가지뿐).
# 이제: **칸**(왼쪽 가장자리 ~ 경계선 · 캔버스 높이 전체)과 **그 안의 그림**을 따로 다룬다.
#   - 경계선을 좌우로 끌어 칸의 너비를 정한다. 칸은 늘 왼쪽에 붙어 있다.
#   - 칸 안의 그림은 끌어서 옮기고, 휠 · 손잡이로 키우고 줄인다(비율 고정). 경계선 밖으로 나간 부분은 잘린다.
#   - 칸 안은 그림이 안 덮은 흰 바탕까지 통째로 보존한다. 경계선 안쪽에 예전과 같은 칸 선 · 이음매를 둔다.
#
# 경위(같은 날 세 번 바뀌었다 - 되돌리기 전에 읽을 것): 자유롭게 옮기는 박스 → "좌측은 무조건 왼쪽에 고정 ·
# 사이즈만 · 이동 불가"(그림을 키우면 머리 쪽만 보였다) → "기존 사양처럼 경계선이 필요하고 내부 드래그 가능해야".
# 그래서 **칸은 왼쪽 고정, 옮기는 것은 칸 안의 그림**이다.
#
# ⚠️ 한계 값의 SSOT 는 여기다. 화면은 `reference_inset_state()` 가 실어 보내는 `limits` 로 같은 계산을 한다 -
#    프런트에 숫자를 복사하면 한쪽만 고쳐져 서로 다른 말을 한다.
REFERENCE_INSET_BOX_GRID_PX = 8
REFERENCE_INSET_BOX_MIN_HEIGHT_PX = 192
# 그림의 이만큼은 언제나 칸 안에 남는다(밖으로 끌어내 잃어버리지 않게).
REFERENCE_INSET_BOX_MIN_VISIBLE_PX = 64
# 경계선이 갈 수 있는 범위 = **그릴 곳이 캔버스의 51% ~ 60%**(사용자 지정 2026-10-09). 칸이 절반을 넘으면
# 생성 영역이 좁아 결과가 나빠지고(1088x960 을 목록에서 뺀 것과 같은 까닭), 너무 좁으면 인셋이 힘을 못 쓴다.
# ⚠️ **기본 경계에도 건다.** 처음에는 예전과 같은 그림을 지키려고 손대지 않은 기본 경계를 범위 밖에 뒀는데
#    (1216x832 = 61% · 1344x768 = 67%), 해상도를 바꾸면 조건이 무시되는 것으로 보였다(사용자 제보 2026-10-09).
#    그래서 예전과 바이트까지 같은 그림이 나가는 것은 예전 배치가 범위 안인 캔버스(1152x896 = 55%)뿐이다.
REFERENCE_INSET_OPEN_PERCENT_MIN = 51
REFERENCE_INSET_OPEN_PERCENT_MAX = 60
# ⚠️ **캔버스 크기와 무관하게 같은 범위다.** 고해상도(1MP 초과)에서만 65% 까지 푼 적이 있는데 사용자가 같은 날 되돌렸다
#    (2026-10-10: "고해상도라고 봐주는건 없었네요") - 캔버스가 커도 칸이 좁아지면 결과가 나빠진다. 다시 풀지 말 것.


def _round_half_up(value: float) -> int:
    """화면(JS `Math.round`)과 같은 반올림. 파이썬 `round` 는 .5 를 짝수로 보내 1px 씩 어긋난다."""
    return int(math.floor(value + 0.5))


def _finite(value: object, fallback: float) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback


def reference_inset_box_limits(spec: ReferenceInsetPreprocessSpec | None = None) -> dict[str, float]:
    spec = spec or ReferenceInsetPreprocessSpec()
    grid = REFERENCE_INSET_BOX_GRID_PX
    return {
        "grid": grid,
        "min_height": REFERENCE_INSET_BOX_MIN_HEIGHT_PX,
        # 캔버스보다 크게도 놓는다(얼굴만 크게 걸치기) - 두 배까지.
        "max_height": spec.canvas_height * 2,
        "min_visible": REFERENCE_INSET_BOX_MIN_VISIBLE_PX,
        # 정수로만 센다(0.4 * 1152 같은 소수 곱은 460.79999… 가 되어 격자 한 칸이 갈린다).
        # 가장 좁은 칸 = 그릴 곳 60% 를 넘지 않게 올림, 가장 넓은 칸 = 그릴 곳 51% 밑으로 안 가게 내림.
        "min_divider": -(-spec.canvas_width * (100 - REFERENCE_INSET_OPEN_PERCENT_MAX) // (100 * grid)) * grid,
        "max_divider": spec.canvas_width * (100 - REFERENCE_INSET_OPEN_PERCENT_MIN) // (100 * grid) * grid,
    }


def classic_reference_inset_layout(
    source_size: tuple[int, int],
    spec: ReferenceInsetPreprocessSpec | None = None,
) -> tuple[dict[str, int], int]:
    """예전 배치 그대로: 그림을 캔버스 높이에 꽉 채워 왼쪽에 붙이고, 그림의 오른쪽 끝이 경계다. `(box, divider)`."""
    placement = _resolve_reference_placement(source_size, spec or ReferenceInsetPreprocessSpec())
    box = {"x": placement.x, "y": placement.y, "width": placement.width, "height": placement.height}
    return box, placement.visible_right


def default_reference_inset_divider(
    source_size: tuple[int, int],
    spec: ReferenceInsetPreprocessSpec | None = None,
) -> int:
    """기본 경계 = 예전 배치의 경계(그림의 오른쪽 끝)를 **범위 안으로 넣은 것**.

    범위 안이면 예전 값 그대로다(격자에 안 맞춘다 - 그래야 예전과 같은 그림이 나간다).
    """
    spec = spec or ReferenceInsetPreprocessSpec()
    _box, classic = classic_reference_inset_layout(source_size, spec)
    limits = reference_inset_box_limits(spec)
    return max(int(limits["min_divider"]), min(int(limits["max_divider"]), classic))


def default_reference_inset_box(
    source_size: tuple[int, int],
    spec: ReferenceInsetPreprocessSpec | None = None,
) -> dict[str, int]:
    """기본 그림 자리. [기본값] 이 돌아가는 곳이다.

    예전 배치의 경계가 범위 안이면 예전 자리 그대로(높이에 꽉 채워 왼쪽). 범위에 맞추느라 칸이 넓어지거나
    좁아졌으면 같은 크기의 그림을 **칸의 가운데**에 놓는다 - 왼쪽에 붙여 두면 넓어진 칸의 오른쪽이 휑하게 비고,
    좁아진 칸에서는 한쪽만 잘린다.
    """
    spec = spec or ReferenceInsetPreprocessSpec()
    box, classic = classic_reference_inset_layout(source_size, spec)
    divider = default_reference_inset_divider(source_size, spec)
    if divider != classic:
        box = {**box, "x": (divider - box["width"]) // 2}
    return box


# 생성 결과에서 인셋 칸을 잘라 낼 때: 경계선에서 이만큼은 모델이 칸 테두리를 이어 그리는 자리라 함께 버린다
# (라이브 실측 2026-10-09 · NAID5F: 경계선 오른쪽 10px 이 검정). 더 두껍게 그려졌으면 검은 세로줄이 끝나는
# 데까지 더 민다.
REFERENCE_INSET_RESULT_CROP_MARGIN_PX = 16
REFERENCE_INSET_BORDER_SCAN_PX = 32
REFERENCE_INSET_BORDER_DARK_MEAN = 40.0


def trim_panel_border_left(image: Image.Image, start: int) -> int:
    """`start` 부터 오른쪽으로 '위아래로 내내 검은 세로줄'(칸 테두리)이 이어지는 동안 민 자리를 돌려준다."""
    width, _height = image.size
    left = max(0, min(width - 1, int(start)))
    luminance = np.asarray(image.convert("L"), dtype=np.float32)
    for x in range(left, min(width - 1, left + REFERENCE_INSET_BORDER_SCAN_PX)):
        if float(luminance[:, x].mean()) >= REFERENCE_INSET_BORDER_DARK_MEAN:
            break
        left = x + 1
    return left


def reference_inset_result_crop_box(image: Image.Image, divider: int) -> tuple[int, int, int, int]:
    """생성 결과에서 **그린 부분만** 남기는 자리 `(left, top, right, bottom)` - 인셋 칸과 칸 테두리를 뺀다."""
    width, height = image.size
    left = trim_panel_border_left(image, int(divider) + REFERENCE_INSET_RESULT_CROP_MARGIN_PX)
    return left, 0, width, height


def normalize_reference_inset_divider(
    value: object,
    source_size: tuple[int, int],
    spec: ReferenceInsetPreprocessSpec | None = None,
) -> int:
    """경계선(칸의 너비)을 격자와 한계에 맞춘다. 못 읽으면 기본 경계다.

    기본 경계와 **같은 값**이면 그대로 둔다 - 그래야 손대지 않은 인셋이 예전과 같은 그림으로 나간다.
    """
    spec = spec or ReferenceInsetPreprocessSpec()
    base = default_reference_inset_divider(source_size, spec)
    wanted = _finite(value, float(base))
    if wanted == base:
        return base
    limits = reference_inset_box_limits(spec)
    grid = int(limits["grid"])
    return max(int(limits["min_divider"]), min(int(limits["max_divider"]), _round_half_up(wanted / grid) * grid))


def normalize_reference_inset_box(
    box: object,
    source_size: tuple[int, int],
    spec: ReferenceInsetPreprocessSpec | None = None,
    divider: int | None = None,
) -> dict[str, int]:
    """칸 안의 그림 자리 · 높이를 한계에 맞춘다. 너비는 받지 않는다 - 원본 비율에서 나온다.

    높이는 격자에, 자리는 1px 에 맞춘다(끄는 대로 따라온다). 그림의 `min_visible` 만큼은 늘 칸 안에 남긴다.
    못 읽는 값은 기본 배치의 값으로 채운다. 기본 배치를 넣으면 그대로 나온다(멱등).
    """
    spec = spec or ReferenceInsetPreprocessSpec()
    src_w, src_h = max(1, int(source_size[0])), max(1, int(source_size[1]))
    base = default_reference_inset_box((src_w, src_h), spec)
    if divider is None:
        divider = default_reference_inset_divider((src_w, src_h), spec)
    limits = reference_inset_box_limits(spec)
    grid = int(limits["grid"])
    data = box if isinstance(box, dict) else {}
    wanted = _round_half_up(_finite(data.get("height"), float(base["height"])) / grid) * grid
    height = max(int(limits["min_height"]), min(int(limits["max_height"]), wanted))
    scale = height / src_h
    width = max(1, int(round(src_w * scale)))
    keep = int(limits["min_visible"])
    x = max(keep - width, min(int(divider) - keep, _round_half_up(_finite(data.get("x"), float(base["x"])))))
    y = max(keep - height, min(spec.canvas_height - keep, _round_half_up(_finite(data.get("y"), float(base["y"])))))
    return {"x": x, "y": y, "width": width, "height": height}


def reference_inset_open_ratio(divider: int, spec: ReferenceInsetPreprocessSpec | None = None) -> float:
    """캔버스에서 칸이 **안 덮은** 넓이의 비율(0 ~ 1) - 모델이 그릴 수 있는 곳. 칸은 높이 전체라 너비만 본다."""
    spec = spec or ReferenceInsetPreprocessSpec()
    return 1.0 - max(0, min(spec.canvas_width, int(divider))) / float(spec.canvas_width)


def _panel_placement(box: dict[str, int], divider: int, spec: ReferenceInsetPreprocessSpec) -> PlacementBox:
    """그림은 `box` 에 놓이지만, 보존하는 것은 **칸 전체**(왼쪽 가장자리 ~ 경계선 · 높이 전체)다."""
    return PlacementBox(
        x=int(box["x"]),
        y=int(box["y"]),
        width=int(box["width"]),
        height=int(box["height"]),
        visible_left=0,
        visible_top=0,
        visible_right=max(1, min(spec.canvas_width, int(divider))),
        visible_bottom=spec.canvas_height,
    )


def _resize_visible_part(reference: Image.Image, placement: PlacementBox) -> tuple[Image.Image, tuple[int, int]] | None:
    """칸 안에 보이는 부분만 원본에서 바로 그 크기로 만든다 -> ``(그림, 놓을 자리)``. 보이는 것이 없으면 None.

    ⚠️ 그림을 놓일 크기로 **통째로** 만든 뒤 칸으로 자르면 안 된다. 놓일 크기는 원본의 비율이 정하는데, 가로로 긴
       그림(예: 4096x16 - 붙여넣기의 한계는 통과한다)은 높이를 맞추는 순간 237568x928 = 2억 2천만 픽셀이 된다
       (Codex 리뷰 2026-10-10). 여기서는 만드는 그림이 칸보다 커질 수 없다.
    결과는 통째로 만들어 자른 것과 같은 그림이다 - `resize(box=)` 는 그 영역을 같은 배율로 줄이고, 경계의 필터는
    영역 밖의 진짜 이웃 픽셀을 읽는다.
    """
    left = max(placement.visible_left, placement.x)
    top = max(placement.visible_top, placement.y)
    right = min(placement.visible_right, placement.x + placement.width)
    bottom = min(placement.visible_bottom, placement.y + placement.height)
    if right <= left or bottom <= top:
        return None
    scale_x = reference.width / float(placement.width)
    scale_y = reference.height / float(placement.height)
    source_box = (
        (left - placement.x) * scale_x, (top - placement.y) * scale_y,
        (right - placement.x) * scale_x, (bottom - placement.y) * scale_y,
    )
    part = reference.resize((right - left, bottom - top), Image.Resampling.LANCZOS, box=source_box)
    return part, (left, top)


def _inner_edges(placement: PlacementBox, spec: ReferenceInsetPreprocessSpec) -> tuple[str, ...]:
    """캔버스 가장자리에 닿지 않은 변 - 그림과 생성 영역이 맞닿는 곳이다. 칸 선과 이음매는 여기에만 둔다."""
    edges = []
    if placement.visible_left > 0:
        edges.append("left")
    if placement.visible_top > 0:
        edges.append("top")
    if placement.visible_right < spec.canvas_width:
        edges.append("right")
    if placement.visible_bottom < spec.canvas_height:
        edges.append("bottom")
    return tuple(edges)


def _edge_band(placement: PlacementBox, edge: str, near: int, far: int) -> tuple[int, int, int, int] | None:
    """그 변에서 안쪽으로 ``[near, far)`` 만큼 떨어진 띠 ``(left, top, right, bottom)``. 보이는 부분으로 자른다."""
    left, top = placement.visible_left, placement.visible_top
    right, bottom = placement.visible_right, placement.visible_bottom
    if edge == "right":
        band = (max(left, right - far), top, right - near, bottom)
    elif edge == "left":
        band = (left + near, top, min(right, left + far), bottom)
    elif edge == "bottom":
        band = (left, max(top, bottom - far), right, bottom - near)
    else:
        band = (left, top + near, right, min(bottom, top + far))
    if band[2] <= band[0] or band[3] <= band[1]:
        return None
    return band


def _seam_line_distances(spec: ReferenceInsetPreprocessSpec) -> tuple[int, int, int]:
    """(이음매 띠 폭, 칸 선이 시작하는 거리, 끝나는 거리) - 예전 오른쪽 변의 규칙을 거리로 적은 것."""
    seam = max(0, spec.seam_overlap_px)
    line = max(0, spec.seam_edge_line_px)
    masked = max(0, min(spec.seam_edge_line_masked_px, seam, line))
    return seam, seam - masked, seam - masked + line


def _draw_inner_edge_lines(
    canvas: Image.Image,
    placement: PlacementBox,
    spec: ReferenceInsetPreprocessSpec,
) -> None:
    _seam, near, far = _seam_line_distances(spec)
    if far <= near:
        return
    draw = ImageDraw.Draw(canvas)
    for edge in _inner_edges(placement, spec):
        band = _edge_band(placement, edge, near, far)
        if band is not None:
            draw.rectangle((band[0], band[1], band[2] - 1, band[3] - 1), fill=spec.seam_edge_line_rgb)


def _build_boxed_inpaint_mask(placement: PlacementBox, spec: ReferenceInsetPreprocessSpec) -> Image.Image:
    """인셋의 보이는 부분은 보존, 나머지는 편집. 안쪽 변마다 이음매 띠를 다시 연다(예전 오른쪽 변과 같은 규칙)."""
    mask = np.full((spec.canvas_height, spec.canvas_width), 255, dtype=np.uint8)
    if placement.visible_right <= placement.visible_left or placement.visible_bottom <= placement.visible_top:
        return Image.fromarray(mask, mode="L")
    mask[placement.visible_top:placement.visible_bottom, placement.visible_left:placement.visible_right] = 0
    seam, _near, _far = _seam_line_distances(spec)
    if seam > 0:
        for edge in _inner_edges(placement, spec):
            band = _edge_band(placement, edge, 0, seam)
            if band is not None:
                mask[band[1]:band[3], band[0]:band[2]] = 255
    return Image.fromarray(mask, mode="L")


# ---------------------------------------------------------------------------
# Narrow-mask variant for single-character variations (Character Asset tab)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VariationInpaintSpec:
    """Reference-inset inpaint whose editable region is clamped to a single,
    character-sized rectangle on the right-hand free area.

    Why the reference-inset layout is preserved:
    - NovelAI's inpaint uses the preserved pixels as context for the edit
      area. That means we need a real reference image sitting on the canvas
      (not white letterbox) or the model has no character features to trace.
    - The classic ``ReferenceInsetPreprocessSpec`` (1152x896 with the 768x1344
      reference anchored on the left) is the layout that actually ships the
      character's silhouette/design into the model.

    What changes vs. the classic spec:
    - The editable area is not the whole right-hand side anymore. Only a
      narrow vertical rectangle in the middle of the free area is opened for
      edit — sized for one full-body figure. This prevents NovelAI from
      populating the empty space with a second character, which is the failure
      mode observed when letting the entire free area stay editable.

    Geometry (defaults):
    - canvas: 1152x896 (same as the classic spec)
    - reference placement: identical to classic spec (left-anchored, small bleed)
    - editable rect: x ∈ [576, 1088], y ∈ [0, 896] → 512x896
      → aspect ratio exactly 4:7 = 768:1344, so the worker can resize the
        whole rect to 768x1344 without any aspect warping and without
        cropping off body parts (head / feet)
      → 8-aligned for NAI's 1/8 mask
      → sits right of the reference (free area 514..1152) so NAI traces the
        preserved character but has the entire vertical canvas to compose
      → reference occupies x ∈ [0, 514], so there is no overlap
    - seam overlap (8 px) on the reference's right edge is preserved for
      blending between the inset and the generated area.
    """

    # Mirror of ``ReferenceInsetPreprocessSpec`` — the reference sits on the
    # left of this canvas, bleeding outward on three sides.
    canvas_width: int = 1152
    canvas_height: int = 896
    background_rgb: tuple[int, int, int] = (255, 255, 255)
    left_bleed_px: int = 16
    top_bleed_px: int = 16
    bottom_bleed_px: int = 16

    reference_border_px: int = 0
    reference_border_rgb: tuple[int, int, int] = (0, 0, 0)

    # Soften the reference/edit boundary so the fused result doesn't look pasted.
    seam_overlap_px: int = 8

    # Editable rectangle: 512 × 896, exact 4:7 ratio so the worker can scale
    # it to 768×1344 without aspect warp or cropping body parts.
    edit_left: int = 576
    edit_top: int = 0
    edit_right: int = 1088
    edit_bottom: int = 896

    mask_downscale: int = 8

    def recommended_inpaint_settings(self) -> dict[str, float]:
        return {"strength": 1.0, "noise": 0.0}


def prepare_variation_inpaint_canvas(
    source_image: Image.Image,
    spec: VariationInpaintSpec | None = None,
) -> ReferenceInsetPreprocessResult:
    """Produce a reference-inset canvas with a narrow editable rectangle.

    The reference image is placed on the left exactly like
    ``prepare_reference_inpaint_canvas`` so NovelAI's inpaint has the source
    character's pixels to trace. Only a small rectangle on the right-hand
    free area is opened for editing — the rest (reference + the free area's
    top/bottom/right margins) stays preserved, which both traces character
    features and keeps NovelAI from inventing a second figure.
    """
    spec = spec or VariationInpaintSpec()
    reference = source_image.convert("RGB")

    placement = _resolve_variation_reference_placement(reference.size, spec)
    resized = reference.resize((placement.width, placement.height), Image.Resampling.LANCZOS)

    canvas = Image.new("RGB", (spec.canvas_width, spec.canvas_height), spec.background_rgb)
    canvas.paste(resized, (placement.x, placement.y))

    if spec.reference_border_px > 0:
        _draw_variation_reference_border(canvas, placement, spec)

    full_mask = _build_variation_inpaint_mask(placement, spec)
    small_mask = _downscale_binary_mask(full_mask, spec.mask_downscale)

    recommended = spec.recommended_inpaint_settings()
    return ReferenceInsetPreprocessResult(
        canvas_image=canvas,
        full_mask_image=full_mask,
        small_mask_image=small_mask,
        placement=placement,
        canvas_width=spec.canvas_width,
        canvas_height=spec.canvas_height,
        recommended_strength=recommended["strength"],
        recommended_noise=recommended["noise"],
    )


def _resolve_variation_reference_placement(
    source_size: tuple[int, int],
    spec: VariationInpaintSpec,
) -> PlacementBox:
    """Same anchoring rule as ``_resolve_reference_placement`` — scale the
    reference to ``canvas_height + top_bleed + bottom_bleed`` and slide it
    left by ``left_bleed_px`` so it bleeds beyond the canvas edges."""
    src_w, src_h = source_size
    target_h = spec.canvas_height + spec.top_bleed_px + spec.bottom_bleed_px
    scale = target_h / max(1, src_h)
    target_w = max(1, int(round(src_w * scale)))

    x = -spec.left_bleed_px
    y = -spec.top_bleed_px

    visible_left = max(0, x)
    visible_top = max(0, y)
    visible_right = min(spec.canvas_width, x + target_w)
    visible_bottom = min(spec.canvas_height, y + target_h)

    return PlacementBox(
        x=x,
        y=y,
        width=target_w,
        height=target_h,
        visible_left=visible_left,
        visible_top=visible_top,
        visible_right=visible_right,
        visible_bottom=visible_bottom,
    )


def _draw_variation_reference_border(
    canvas: Image.Image,
    placement: PlacementBox,
    spec: VariationInpaintSpec,
) -> None:
    if placement.visible_right <= placement.visible_left or placement.visible_bottom <= placement.visible_top:
        return
    draw = ImageDraw.Draw(canvas)
    for offset in range(spec.reference_border_px):
        draw.rectangle(
            (
                placement.visible_left + offset,
                placement.visible_top + offset,
                placement.visible_right - 1 - offset,
                placement.visible_bottom - 1 - offset,
            ),
            outline=spec.reference_border_rgb,
        )


def _build_variation_inpaint_mask(
    placement: PlacementBox,
    spec: VariationInpaintSpec,
) -> Image.Image:
    """Preserve everything by default, open only the narrow edit rect and a
    thin seam band on the reference's right edge."""
    mask = np.zeros((spec.canvas_height, spec.canvas_width), dtype=np.uint8)

    # Narrow editable rectangle.
    ex1 = max(0, min(spec.canvas_width, spec.edit_left))
    ex2 = max(ex1, min(spec.canvas_width, spec.edit_right))
    ey1 = max(0, min(spec.canvas_height, spec.edit_top))
    ey2 = max(ey1, min(spec.canvas_height, spec.edit_bottom))
    mask[ey1:ey2, ex1:ex2] = 255

    # Seam overlap — reopen a thin editable band on the reference's right edge
    # so the generated area can fuse with the preserved silhouette.
    seam = max(0, spec.seam_overlap_px)
    if seam > 0 and placement.visible_right > placement.visible_left:
        seam_left = max(placement.visible_left, placement.visible_right - seam)
        mask[placement.visible_top:placement.visible_bottom, seam_left:placement.visible_right] = 255

    return Image.fromarray(mask, mode="L")
