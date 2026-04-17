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
            "1koma",
            "reference inset",
            _join_tags(general_tags),
            _join_tags(quality_tags),
        )
    )


def prepare_reference_inpaint_canvas(
    source_image: Image.Image,
    spec: ReferenceInsetPreprocessSpec | None = None,
) -> ReferenceInsetPreprocessResult:
    """
    Create the left-anchored reference canvas and matching full/small masks.

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

    placement = _resolve_reference_placement(reference.size, spec)
    resized = reference.resize((placement.width, placement.height), Image.Resampling.LANCZOS)

    canvas = Image.new("RGB", (spec.canvas_width, spec.canvas_height), spec.background_rgb)
    canvas.paste(resized, (placement.x, placement.y))

    if spec.reference_border_px > 0:
        _draw_reference_border(canvas, placement, spec)

    full_mask = _build_reference_inpaint_mask(placement, spec)
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
