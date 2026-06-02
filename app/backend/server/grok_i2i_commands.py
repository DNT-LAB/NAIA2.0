"""Grok(xAI) I2I — 이미지 우클릭 → 변형 (제거 가능 모듈).

우클릭한 결과 이미지를 소스로, 사용자가 입력한 프롬프트로 xAI Images /v1/images/edits 를
(번들 progrok 프록시 경유) 호출해 변형 이미지를 만들고, NAI 업스케일과 동일한 결과 파이프라인
(result_store.add_api_result → broadcast_image/viewer_new_image_payload → save_history_item)에
주입한다. 단독 생성 모드 아님(우클릭으로만 진입). planner/web-search 우회 — 프롬프트 직송.

제거: 이 파일 + websocket_session.py 의 GROK_I2I 임포트/분기 + 프론트 grokI2iModal 삭제.
"""
from __future__ import annotations

import base64
import io
import math
from typing import Any

import requests
from PIL import Image

from app.backend.server.grok_routes import DEFAULT_GROK_PROXY_URL, load_grok_config, normalize_grok_proxy_url

GROK_I2I_COMMAND_TYPES = {"grok_i2i"}

_SUPPORTED_ASPECTS = (
    "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3",
    "2:1", "1:2", "19.5:9", "9:19.5", "20:9", "9:20",
)
_GROK_EDIT_TIMEOUT = 180.0


def _aspect_value(aspect: str) -> float:
    w, h = aspect.split(":")
    return float(w) / float(h)


def _closest_aspect(w: int, h: int) -> str:
    target = w / h
    best = "1:1"
    best_dist = abs(math.log(target / _aspect_value(best)))
    for aspect in _SUPPORTED_ASPECTS:
        dist = abs(math.log(target / _aspect_value(aspect)))
        if dist < best_dist:
            best, best_dist = aspect, dist
    return best


def _map_size(w: int, h: int) -> dict[str, str]:
    """소스 크기 → xAI aspect_ratio + resolution (ima2 grokSizeMapper 포팅)."""
    if w <= 0 or h <= 0:
        return {"aspect_ratio": "auto"}
    resolution = "2k" if (max(w, h) >= 2048 or w * h >= 2_000_000) else "1k"
    return {"aspect_ratio": _closest_aspect(w, h), "resolution": resolution}


def _grok_proxy_url() -> str:
    try:
        return normalize_grok_proxy_url(load_grok_config().get("proxy_url") or "")
    except Exception:
        return DEFAULT_GROK_PROXY_URL


_MAX_EXTRA_IMAGES = 5


def grok_edit_image(image_bytes: bytes, prompt: str, quality: str = "", extra_data_urls: list | None = None) -> dict[str, Any]:
    """progrok 프록시의 /v1/images/edits 호출 → {'status','image'(PIL),'raw_bytes'(PNG)}.
    소스 이미지 + (선택) 추가 참조 이미지들을 함께 보낸다(ima2 패턴: 1장=image, 여러장=images).
    Bearer dummy 는 프록시가 서버측에서 실 OAuth 토큰으로 치환한다. planner 우회."""
    proxy = _grok_proxy_url()
    model = "grok-imagine-image-quality" if str(quality).lower() == "high" else "grok-imagine-image"
    try:
        with Image.open(io.BytesIO(image_bytes)) as src:
            sw, sh = src.size
    except Exception:
        sw, sh = 0, 0
    b64 = base64.b64encode(image_bytes).decode("ascii")
    image_urls = [f"data:image/png;base64,{b64}"]
    for url in (extra_data_urls or [])[:_MAX_EXTRA_IMAGES]:
        if isinstance(url, str) and url.startswith("data:"):
            image_urls.append(url)
    payload = {
        "model": model,
        "prompt": str(prompt or ""),
        "n": 1,
        "response_format": "b64_json",
        **_map_size(int(sw), int(sh)),
    }
    if len(image_urls) == 1:
        payload["image"] = {"type": "image_url", "url": image_urls[0]}
    else:
        payload["images"] = [{"type": "image_url", "url": u} for u in image_urls]
    try:
        resp = requests.post(
            f"{proxy}/v1/images/edits",
            headers={"Content-Type": "application/json", "Authorization": "Bearer dummy"},
            json=payload,
            timeout=_GROK_EDIT_TIMEOUT,
        )
    except requests.exceptions.ConnectionError:
        return {"status": "error", "message": "Grok 프록시에 연결할 수 없습니다. API 설정 → GROK 에서 로그인하세요."}
    except requests.exceptions.Timeout:
        return {"status": "error", "message": "Grok 생성 시간 초과."}
    except Exception as exc:
        return {"status": "error", "message": f"Grok 요청 실패: {exc}"}

    if resp.status_code == 401:
        return {"status": "error", "message": "Grok 로그인이 필요합니다 (API 설정 → GROK)."}
    if resp.status_code == 403:
        return {"status": "error", "message": "Grok 이미지 권한이 없습니다 (SuperGrok Heavy 티어 필요 가능)."}
    if resp.status_code == 429:
        return {"status": "error", "message": "Grok 요청이 제한되었습니다 (rate limit). 잠시 후 다시 시도하세요."}
    if resp.status_code >= 400:
        return {"status": "error", "message": f"Grok 오류 (HTTP {resp.status_code}): {resp.text[:200]}"}

    try:
        data = resp.json()
        items = data.get("data") if isinstance(data, dict) else None
        b64_out = items[0].get("b64_json") if isinstance(items, list) and items else None
    except Exception:
        b64_out = None
    if not b64_out:
        return {"status": "error", "message": "Grok 응답에 이미지가 없습니다."}
    try:
        raw = base64.b64decode(b64_out)
        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            pil = img.convert("RGB")
        out = io.BytesIO()
        pil.save(out, format="PNG")
        png_bytes = out.getvalue()
    except Exception as exc:
        return {"status": "error", "message": f"Grok 이미지 디코드 실패: {exc}"}
    return {"status": "success", "image": pil, "raw_bytes": png_bytes, "message": "Grok I2I 완료"}


def perform_grok_i2i(context, payload: dict[str, Any] | None):
    """소스 해석 → grok edit → 표준 결과 파이프라인 주입. (run_in_thread 로 동기 실행)"""
    from app.backend.server.result_display_routes import (
        history_item_from_viewer_path,
        resolve_result_image_action_source,
    )
    from core.generation_request import GenerationRequest

    payload = payload if isinstance(payload, dict) else {}
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise RuntimeError("프롬프트를 입력하세요.")

    image_bytes, label, _gen_params, _prompt_ctx = resolve_result_image_action_source(context, payload)
    extras = payload.get("extra_images") if isinstance(payload.get("extra_images"), list) else []
    result = grok_edit_image(image_bytes, prompt, str(payload.get("quality") or ""), extras)
    if not isinstance(result, dict) or result.get("status") != "success":
        raise RuntimeError(str((result or {}).get("message") or "Grok I2I 실패"))

    params = {
        "input": prompt,
        "negative_prompt": "",
        "api_mode": "GROK",
        "grok_i2i_request": True,
        "grok_i2i_source_label": label,
        "_remote_queue_source": "Grok I2I",
        "_remote_queue_label": label,
    }
    rel_path = str(payload.get("path") or "").strip()
    source_item = history_item_from_viewer_path(context, rel_path) if rel_path else None
    if source_item is None:
        source_item = getattr(context.result_store, "latest_item", None)
    request = GenerationRequest(params=params, source_row=getattr(source_item, "source_row", None))

    stored = context.result_store.add_api_result(result, request)
    if context._coerce_bool(context.auto_save_state.get("auto_save", True)):
        try:
            context.save_history_item(stored.item)
        except Exception:
            pass
    return stored, str(result.get("message") or "Grok I2I 완료")


async def handle_grok_command(ws, context, clients, command, *, run_in_thread) -> bool:
    """WS 'grok_i2i' 처리 — result_upscale 핸들러와 동일 패턴(상태 메시지 + 결과 브로드캐스트)."""
    command_type = str(command.get("type") or "").strip()
    if command_type not in GROK_I2I_COMMAND_TYPES:
        return False

    from app.backend.server.websocket_broadcast import broadcast_image, broadcast_json

    async def _send(obj: dict[str, Any]) -> None:
        try:
            await ws.send_json(obj)
        except Exception:
            pass

    await _send({"type": "grok_i2i_state", "running": True, "success": None, "message": "Grok 생성 중…", "runtime": "web"})
    try:
        stored, message = await run_in_thread(perform_grok_i2i, context, command)
    except Exception as exc:
        msg = f"Grok I2I 실패: {exc}"
        await _send({"type": "grok_i2i_state", "running": False, "success": False, "message": msg, "runtime": "web"})
        await _send({"type": "toast", "level": "error", "message": msg, "runtime": "web"})
        return True

    await broadcast_image(clients, stored.item.webp_bytes, stored.image_meta)
    await broadcast_json(clients, context.result_store.viewer_new_image_payload(stored.item))
    for evicted in stored.evicted_payloads:
        await broadcast_json(clients, evicted)
    try:
        await broadcast_json(clients, context.auto_save_state_payload())
    except Exception:
        pass
    await _send({"type": "grok_i2i_state", "running": False, "success": True, "message": message, "runtime": "web"})
    await _send({"type": "toast", "level": "success", "message": message, "runtime": "web"})
    return True
