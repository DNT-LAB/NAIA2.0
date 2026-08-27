"""NAI 인페인트 마스크 디코드 - img2img 서비스와 캐릭터 벤치가 공유.

api_service._process_mask_data(is_nai=True)는 검증 없이 마스크를 x8 NEAREST로
부풀린다(api_service.py:1863-1870). 풀사이즈 마스크를 그대로 넘기면 8배로
커져 요청이 깨지므로, 여기가 유일한 방어선이다:
- NAI payload용 마스크는 반드시 target의 1/8 크기로 축소하고
- 빈 마스크 / 너무 작은 마스크(painted_blocks < 8)는 요청 전에 거부한다.

세션 결합 없는 순수 함수 - headless_img2img_service._decode_mask는 세션에서
target_size를 뽑아 이 함수에 위임하고, 캐릭터 벤치는 핀 이미지 크기를 넘긴다.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

MIN_PAINTED_BLOCKS = 8


@dataclass(frozen=True)
class DecodedInpaintMask:
    small_png: bytes         # NAI payload용 1/8 마스크 PNG (mask_bytes)
    preview_data_url: str    # 풀사이즈 이진화 미리보기 (data URL)
    painted_blocks: int      # 1/8 그리드에서 칠해진 블록 수


def _data_url_payload(value: str) -> str:
    text = str(value or "").strip()
    if "," in text and text.lower().startswith("data:"):
        return text.split(",", 1)[1]
    return text


def _png_bytes(image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def decode_mask_to_small_png(
    value: str,
    target_size: tuple[int, int],
    *,
    require_exact_size: bool = False,
) -> DecodedInpaintMask:
    """마스크 data URL을 (1/8 PNG, 미리보기, 블록 수)로 디코드한다.

    require_exact_size=True면 입력 마스크가 target_size와 다를 때 거부한다.
    리사이즈는 클라이언트 좌표계 버그(엉뚱한 베이스 위에 그린 마스크)를
    숨기므로, 벤치처럼 베이스 크기를 정확히 아는 경로는 이 모드를 쓴다.
    img2img 경로는 기존 리사이즈 관용을 유지한다(False).

    실패는 전부 ValueError - 호출자가 자기 계층의 예외로 감싼다.
    """
    from PIL import Image

    width = max(1, int(target_size[0]))
    height = max(1, int(target_size[1]))
    try:
        mask_bytes = base64.b64decode(_data_url_payload(value))
    except Exception as exc:
        raise ValueError(f"invalid mask payload: {exc}") from exc
    try:
        with Image.open(io.BytesIO(mask_bytes)) as opened:
            if require_exact_size and opened.size != (width, height):
                raise ValueError(
                    f"mask size {opened.size[0]}x{opened.size[1]} does not match "
                    f"target {width}x{height}"
                )
            full_mask = opened.convert("L").resize((width, height))
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"invalid mask image: {exc}") from exc
    threshold = [0 if i <= 127 else 255 for i in range(256)]
    full_mask = full_mask.point(threshold, "L")
    white_pixels = int(full_mask.histogram()[255])
    small_size = (max(1, width // 8), max(1, height // 8))
    small_mask = full_mask.resize(small_size).point(threshold, "L")
    painted_blocks = int(small_mask.histogram()[255])
    if white_pixels <= 0:
        raise ValueError("Inpaint mask is empty")
    if painted_blocks < MIN_PAINTED_BLOCKS:
        raise ValueError("Inpaint mask is too small")
    # ⚠️ **알파를 함께 싣는다(LA).** 화면은 이 그림을 CSS `mask-image` 로 쓰는데,
    #    알파가 없는 흑백 PNG 는 브라우저가 **전체를 불투명**으로 보아 그림 전체가
    #    칠해진 것처럼 덮인다(사용자 제보 2026-08-27: "마스크가 전체에 다 들어간다").
    #    L 채널은 그대로 두므로 `convert("L")` 로 읽던 곳은 영향이 없다.
    preview = "data:image/png;base64," + base64.b64encode(
        _png_bytes(Image.merge("LA", (full_mask, full_mask)))).decode("ascii")
    return DecodedInpaintMask(_png_bytes(small_mask), preview, painted_blocks)


__all__ = ["DecodedInpaintMask", "MIN_PAINTED_BLOCKS", "decode_mask_to_small_png"]
