"""Grok(xAI) I2V — 이미지 우클릭 → 영상 (제거 가능 모듈).

소스 이미지 + 프롬프트로 xAI Videos /v1/videos/generations 를 (progrok 프록시 경유) 호출,
비동기 폴링으로 완성까지 기다린 뒤 mp4 를 캐시(grok_routes)에 저장한다. 결과는 모달 내
<video> 로 재생/저장 — 이미지와 달리 메인 결과 파이프라인에 주입하지 않는다(인모달 전용). planner 우회.

폴링이 길어(수 분) WS 핸들러를 막지 않도록 asyncio 백그라운드 태스크로 실행하고,
진행률은 WS {type:'grok_i2v_state'} 로 스트리밍한다.

제거: 이 파일 + websocket_session.py 의 GROK_I2V 분기/임포트 + grok_routes 비디오 라우트/캐시 + 프론트 grokI2vModal.
"""
from __future__ import annotations

import asyncio
import base64
import io
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from PIL import Image

from app.backend.server.grok_routes import (
    DEFAULT_GROK_PROXY_URL,
    load_grok_config,
    normalize_grok_proxy_url,
    save_grok_video_bytes,
)

GROK_I2V_COMMAND_TYPES = {"grok_i2v"}

_SUBMIT_TIMEOUT = 60.0
_POLL_TIMEOUT = 30.0
_DOWNLOAD_TIMEOUT = 180.0
_POLL_INTERVAL = 5.0
_TOTAL_BUDGET = 900.0  # 15분
_VIDEO_MODEL = "grok-imagine-video"


def _proxy() -> str:
    try:
        return normalize_grok_proxy_url(load_grok_config().get("proxy_url") or "")
    except Exception:
        return DEFAULT_GROK_PROXY_URL


def _headers() -> dict[str, str]:
    return {"Content-Type": "application/json", "Authorization": "Bearer dummy"}


def _clamp_duration(value: Any) -> int:
    try:
        d = int(round(float(value)))
    except Exception:
        d = 5
    return max(1, min(15, d))


def _clamp_resolution(value: Any) -> str:
    return "720p" if str(value or "").strip().lower() == "720p" else "480p"


def submit_grok_video(image_bytes: bytes, prompt: str, duration: int, resolution: str) -> str:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": _VIDEO_MODEL,
        "prompt": str(prompt or ""),
        "duration": duration,
        "resolution": resolution,
        "image": {"url": f"data:image/png;base64,{b64}"},
    }
    resp = requests.post(f"{_proxy()}/v1/videos/generations", headers=_headers(), json=payload, timeout=_SUBMIT_TIMEOUT)
    if resp.status_code == 401:
        raise RuntimeError("Grok 로그인이 필요합니다 (API 설정 → GROK).")
    if resp.status_code == 403:
        raise RuntimeError("Grok 영상 권한이 없습니다 (SuperGrok Heavy 티어 필요 가능).")
    if resp.status_code >= 400:
        raise RuntimeError(f"Grok 영상 요청 실패 (HTTP {resp.status_code}): {resp.text[:200]}")
    data = resp.json()
    request_id = data.get("request_id") or data.get("id")
    if not request_id:
        raise RuntimeError("Grok 영상 request_id 가 없습니다.")
    return str(request_id)


def poll_grok_video(request_id: str) -> dict[str, Any]:
    resp = requests.get(f"{_proxy()}/v1/videos/{request_id}", headers=_headers(), timeout=_POLL_TIMEOUT)
    if resp.status_code >= 400:
        raise RuntimeError(f"Grok 영상 폴링 실패 (HTTP {resp.status_code}).")
    data = resp.json()
    video = data.get("video") if isinstance(data.get("video"), dict) else {}
    error = data.get("error") if isinstance(data.get("error"), dict) else {}
    return {
        "status": data.get("status"),
        "progress": data.get("progress"),
        "video_url": video.get("url"),
        "respect_moderation": video.get("respect_moderation"),
        "failed_code": error.get("code"),
    }


def download_grok_video(video_url: str) -> bytes:
    resp = requests.get(video_url, timeout=_DOWNLOAD_TIMEOUT)
    if resp.status_code >= 400:
        raise RuntimeError(f"영상 다운로드 실패 (HTTP {resp.status_code}).")
    return resp.content


def grok_videos_output_dir(context) -> Path:
    """영상 자동저장 폴더 — 이미지 출력 루트 아래 grok_videos/."""
    try:
        base = Path(context._output_root())
    except Exception:
        user_data_dir = os.environ.get("NAIA_USER_DATA_DIR")
        base = Path(user_data_dir).expanduser().resolve() if user_data_dir else Path(".")
    folder = base / "grok_videos"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def autosave_grok_video(context, data: bytes) -> str:
    """완성 mp4 를 출력 폴더에 자동 저장하고 절대 경로를 반환(실패 시 '')."""
    try:
        name = f"grok_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.mp4"
        target = grok_videos_output_dir(context) / name
        target.write_bytes(data)
        return str(target)
    except Exception:
        return ""


def _prepare_source_png(image_bytes: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img.load()
            rgb = img.convert("RGB")
        out = io.BytesIO()
        rgb.save(out, format="PNG")
        return out.getvalue()
    except Exception:
        return image_bytes


async def handle_grok_video_command(ws, context, clients, command, *, run_in_thread) -> bool:
    command_type = str(command.get("type") or "").strip()
    if command_type not in GROK_I2V_COMMAND_TYPES:
        return False
    # 긴 폴링이 WS 수신 루프를 막지 않도록 백그라운드 태스크로 분리.
    asyncio.create_task(_run_grok_video(ws, context, command, run_in_thread))
    return True


async def _run_grok_video(ws, context, command, run_in_thread) -> None:
    # 다중 인스턴스 라우팅: 프론트가 grok_i2v 에 실어 보낸 job_id 를 모든 grok_i2v_state 에 echo 한다.
    # (동시 생성 시 어느 인스턴스의 진행/완료인지 프론트가 구분) — 없으면 빈 문자열(구버전 단일 폴백).
    job_id = str(command.get("job_id") or "")

    async def _send(obj: dict[str, Any]) -> None:
        try:
            if isinstance(obj, dict) and obj.get("type") == "grok_i2v_state":
                obj = {**obj, "job_id": job_id}
            await ws.send_json(obj)
        except Exception:
            pass

    async def _fail(message: str) -> None:
        await _send({"type": "grok_i2v_state", "running": False, "success": False, "message": message, "runtime": "web"})
        await _send({"type": "toast", "level": "error", "message": message, "runtime": "web"})

    prompt = str(command.get("prompt") or "").strip()
    if not prompt:
        await _fail("프롬프트를 입력하세요.")
        return
    duration = _clamp_duration(command.get("duration"))
    resolution = _clamp_resolution(command.get("resolution"))

    await _send({"type": "grok_i2v_state", "running": True, "phase": "submitting", "message": "영상 요청 준비 중…", "runtime": "web"})
    try:
        from app.backend.server.result_display_routes import resolve_result_image_action_source

        image_bytes, _label, _gp, _pc = await run_in_thread(resolve_result_image_action_source, context, command)
        image_bytes = await run_in_thread(_prepare_source_png, image_bytes)
        request_id = await run_in_thread(submit_grok_video, image_bytes, prompt, duration, resolution)
    except Exception as exc:
        await _fail(f"Grok 영상 시작 실패: {exc}")
        return

    await _send({"type": "grok_i2v_state", "running": True, "phase": "submitted", "progress": 0, "message": "생성 중…", "runtime": "web"})
    deadline = time.monotonic() + _TOTAL_BUDGET
    poll: dict[str, Any] = {}
    try:
        while True:
            if time.monotonic() > deadline:
                await _fail("Grok 영상 생성 시간 초과.")
                return
            poll = await run_in_thread(poll_grok_video, request_id)
            status = str(poll.get("status") or "")
            if status == "done":
                break
            if status in {"failed", "expired"}:
                await _fail(f"Grok 영상 실패 ({poll.get('failed_code') or status}).")
                return
            progress = poll.get("progress")
            await _send({
                "type": "grok_i2v_state", "running": True, "phase": "progress",
                "progress": progress if isinstance(progress, (int, float)) else None,
                "message": "생성 중…", "runtime": "web",
            })
            await asyncio.sleep(_POLL_INTERVAL)

        if poll.get("respect_moderation") is False:
            await _fail("Grok 영상이 모더레이션에 의해 차단되었습니다.")
            return
        video_url = poll.get("video_url")
        if not video_url:
            await _fail("Grok 영상 URL 이 비어 있습니다.")
            return
        video_bytes = await run_in_thread(download_grok_video, video_url)
        video_id = await run_in_thread(save_grok_video_bytes, video_bytes)
        saved_path = await run_in_thread(autosave_grok_video, context, video_bytes)  # 자동 저장
    except Exception as exc:
        await _fail(f"Grok 영상 처리 실패: {exc}")
        return

    saved_name = os.path.basename(saved_path) if saved_path else ""
    await _send({
        "type": "grok_i2v_state", "running": False, "success": True, "video_id": video_id,
        "saved_path": saved_path, "saved_name": saved_name,
        "message": "Grok I2V 완료", "runtime": "web",
    })
    await _send({"type": "toast", "level": "success", "message": "Grok 영상 저장 완료", "runtime": "web"})


# ===== 영상 → 정지 썸네일(선명한 첫 프레임 + ▶) 히스토리 주입 + 클릭 시 mp4 재생 (제거 가능) =====
# 저화질 webp 변환을 버리고, 브라우저가 결과 video 의 첫 프레임(+▶ 합성)을 풀해상도로 떠 보내면
# 백엔드는 그걸 일반 이미지 결과로 히스토리에 넣는다(선명). 그리고 grok_video_registered 로
# rel_path↔video_id 를 알려주면 프론트가 그 썸네일 클릭 시 실제 mp4 를 재생한다(완벽 화질). 신규 의존성 0.
GROK_ANIMATE_COMMAND_TYPES = {"grok_animate"}


def _decode_frame(data_url: str) -> Image.Image:
    text = str(data_url or "")
    if text.startswith("data:") and "," in text:
        text = text.split(",", 1)[1]
    raw = base64.b64decode(text)
    img = Image.open(io.BytesIO(raw))
    img.load()
    return img.convert("RGB")


def perform_grok_video_thumb(context, payload: dict[str, Any]):
    from core.generation_request import GenerationRequest

    frames = payload.get("frames") if isinstance(payload.get("frames"), list) else []
    if not frames:
        raise RuntimeError("프레임이 없습니다.")
    still = _decode_frame(frames[0])
    buf = io.BytesIO()
    still.save(buf, format="PNG")
    png_bytes = buf.getvalue()
    video_id = str(payload.get("video_id") or "")
    label = str(payload.get("label") or "Grok 영상")
    params = {
        "input": str(payload.get("prompt") or ""),
        "negative_prompt": "",
        "api_mode": "GROK",
        "grok_video_id": video_id,
        "_remote_queue_source": "Grok 영상",
        "_remote_queue_label": label,
    }
    request = GenerationRequest(params=params, source_row=None)
    result = {"status": "success", "image": still, "raw_bytes": png_bytes}
    stored = context.result_store.add_api_result(result, request)
    # I2I(perform_grok_i2i)와 동일하게 Auto Save 를 존중해 저장한다. 저장하면 item.filepath 가
    # 채워져(history rel_path 는 history_id 기반 property 라 저장해도 불변) 프론트의
    # isUnsavedHistoryAsset 가 false 가 되어 새 썸네일로 포커스가 넘어가도 [저장][삭제] 미저장
    # 오버레이가 뜨지 않는다. rel_path 불변이라 grok_video_registered 의 썸네일 클릭→영상 재생
    # 매핑도 그대로 유지된다. Auto Save Off 면 다른 결과와 동일하게 미저장으로 남는다.
    if context._coerce_bool(context.auto_save_state.get("auto_save", True)):
        try:
            context.save_history_item(stored.item)
        except Exception:
            pass
    return stored, video_id


async def handle_grok_animate_command(ws, context, clients, command, *, run_in_thread) -> bool:
    command_type = str(command.get("type") or "").strip()
    if command_type not in GROK_ANIMATE_COMMAND_TYPES:
        return False
    from app.backend.server.websocket_broadcast import broadcast_image, broadcast_json

    try:
        stored, video_id = await run_in_thread(perform_grok_video_thumb, context, command)
    except Exception as exc:
        # 부가기능 — 실패해도 본 영상은 이미 저장됨. 조용히 경고만.
        try:
            await ws.send_json({"type": "toast", "level": "warning", "message": f"영상 썸네일 추가 실패: {exc}", "runtime": "web"})
        except Exception:
            pass
        return True
    await broadcast_image(clients, stored.item.webp_bytes, stored.image_meta)
    await broadcast_json(clients, context.result_store.viewer_new_image_payload(stored.item))
    for evicted in stored.evicted_payloads:
        await broadcast_json(clients, evicted)
    # 썸네일이 (Auto Save 에 따라) 저장됐을 수 있으니 미저장 카운트 배지를 동기화한다. (I2I 와 동일)
    try:
        await broadcast_json(clients, context.auto_save_state_payload())
    except Exception:
        pass
    # 이 썸네일(rel_path) 클릭 시 실제 mp4 를 재생하도록 프론트에 등록 알림.
    try:
        await ws.send_json({
            "type": "grok_video_registered",
            "rel_path": stored.item.rel_path,
            "video_id": video_id,
            "runtime": "web",
        })
    except Exception:
        pass
    return True
