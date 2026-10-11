"""NovelAI Director Tools 의 Remove BG (`/ai/augment-image` · req_type "bg-removal").

실측(2026-10-11 · 768x1344 한 장): 응답은 zip 하나에 PNG 셋 - 차례대로 Masked · Generated · Blend.
셋 다 **같은 알파**를 가진 RGBA 다(투명한 자리의 RGB 는 검정).

  Masked    원본 픽셀을 그대로 오려 낸 것(안쪽 차이 0) - 가장자리에 흰 배경이 묻어 테가 남는다
  Generated 통째로 다시 그린 것 - 안쪽까지 달라진다
  Blend     안쪽은 원본(평균 차이 0.09 / 255) · 가장자리만 다시 그린 것 - 옮길 때 쓰는 것은 이것이다

Anlas 가 든다. 부르는 쪽이 사용자에게 먼저 알린다.
"""

from __future__ import annotations

import base64
import io
import zipfile

NAI_AUGMENT_URL = "https://image.novelai.net/ai/augment-image"
MAX_PIXELS = 1024 * 1024
RESULT_NAMES = ("masked", "generated", "blend")
_TIMEOUT = 180.0


class BackgroundRemovalError(RuntimeError):
    """NovelAI 가 거절했거나 답을 읽을 수 없다. 메시지는 사용자에게 그대로 보인다."""


def source_png(image_bytes: bytes) -> tuple[bytes, int, int]:
    """보낼 그림. 알파는 떼고(흰 바탕에 얹는다) 크기는 건드리지 않는다 - 줄여 보내면 사본이 원본과 달라진다."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(bytes(image_bytes or b""))) as image:
            image.load()
            rgba = image.convert("RGBA")
    except Exception as exc:  # noqa: BLE001 - 그림이 아니다
        raise ValueError(f"image could not be read: {exc}") from exc
    if rgba.width * rgba.height > MAX_PIXELS:
        raise ValueError("배경 제거는 1024x1024 넓이까지의 그림만 받습니다")
    flat = Image.new("RGB", rgba.size, (255, 255, 255))
    flat.paste(rgba, (0, 0), rgba)
    output = io.BytesIO()
    flat.save(output, format="PNG")
    return output.getvalue(), flat.width, flat.height


def remove_background(token: str, image_bytes: bytes) -> list[bytes]:
    """PNG 셋(Masked · Generated · Blend)을 돌려준다. 실패는 `BackgroundRemovalError`."""
    import requests

    if not str(token or "").strip():
        raise BackgroundRemovalError("NAI 로그인이 필요합니다 (API 설정 → NAI).")
    data, width, height = source_png(image_bytes)
    body = {"req_type": "bg-removal", "width": width, "height": height,
            "image": base64.b64encode(data).decode("ascii")}
    try:
        with requests.Session() as session:
            response = session.post(NAI_AUGMENT_URL, json=body,
                                    headers={"Authorization": f"Bearer {token}"}, timeout=_TIMEOUT)
    except requests.exceptions.ConnectionError as exc:
        raise BackgroundRemovalError("NovelAI 에 연결할 수 없습니다.") from exc
    except requests.exceptions.Timeout as exc:
        raise BackgroundRemovalError("배경 제거 시간 초과.") from exc
    except Exception as exc:  # noqa: BLE001
        raise BackgroundRemovalError(f"배경 제거 요청 실패: {type(exc).__name__}") from exc
    if response.status_code == 401:
        raise BackgroundRemovalError("NAI 인증 실패 (토큰 만료/무효).")
    if response.status_code == 402:
        raise BackgroundRemovalError("Anlas 가 부족합니다.")
    if response.status_code >= 400:
        message = f"NAI 오류 (HTTP {response.status_code})"
        try:
            message += f": {str(response.json().get('message', ''))[:200]}"
        except Exception:  # noqa: BLE001
            pass
        raise BackgroundRemovalError(message)
    try:
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        results = [archive.read(info) for info in archive.infolist()]
    except Exception as exc:  # noqa: BLE001
        raise BackgroundRemovalError("배경 제거 응답을 읽을 수 없습니다.") from exc
    if len(results) < len(RESULT_NAMES):
        raise BackgroundRemovalError("배경 제거 응답에 그림이 모자랍니다.")
    return results[:len(RESULT_NAMES)]
