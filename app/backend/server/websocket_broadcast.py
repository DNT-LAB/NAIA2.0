from __future__ import annotations

import json
from typing import Any

from fastapi import WebSocket


async def broadcast_json(clients: set[WebSocket], data: dict[str, Any]) -> None:
    text = json.dumps(data, ensure_ascii=False)
    dead = []
    for client in list(clients):
        try:
            await client.send_text(text)
        except Exception:
            dead.append(client)
    for client in dead:
        clients.discard(client)


async def broadcast_image(clients: set[WebSocket], webp_bytes: bytes, metadata: dict[str, Any]) -> None:
    meta_text = json.dumps({"type": "image_meta", **metadata}, ensure_ascii=False)
    dead = []
    for client in list(clients):
        try:
            await client.send_text(meta_text)
            await client.send_bytes(webp_bytes)
        except Exception:
            dead.append(client)
    for client in dead:
        clients.discard(client)


async def broadcast_preview_image(clients: set[WebSocket], image_bytes: bytes, info: dict[str, Any]) -> None:
    """NAI 스트리밍 중간 프리뷰 프레임을 브로드캐스트한다.

    프론트엔드는 ``nai_preview_meta`` 메시지를 받으면 다음에 오는 바이너리 blob을
    '최종 결과'가 아닌 '중간 프리뷰'로 처리한다(히스토리/완료 처리 없이 뷰어에만 표시).
    """
    meta_text = json.dumps({"type": "nai_preview_meta", **info}, ensure_ascii=False)
    dead = []
    for client in list(clients):
        try:
            await client.send_text(meta_text)
            await client.send_bytes(image_bytes)
        except Exception:
            dead.append(client)
    for client in dead:
        clients.discard(client)
