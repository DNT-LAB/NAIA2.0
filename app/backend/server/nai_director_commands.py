"""NAI Director Tools — GENERATION INFO 의 [Director] 버튼 → 이미지 변형 (제거 가능 모듈).

현재 결과 이미지를 소스로, NovelAI Director Tools(`/ai/augment-image`)를 호출해 변형 이미지를
만들고, Grok I2I 와 동일한 결과 파이프라인(result_store.add_api_result → broadcast_image/
viewer_new_image_payload → save_history_item)에 주입한다. NAI 계정(nai_token)이 등록돼 있으면
모드와 무관하게 사용 가능(augment-image 는 NAI 토큰만 있으면 동작).

지원 변형(req_type): declutter / lineart / sketch / colorize + 24개 emotion.
- declutter / lineart / sketch : req_type 만 (프롬프트·defry 없음)
- colorize                     : + prompt + defry
- emotion(Happy/Sad/...)       : req_type="emotion", prompt="<emotion>;;<user prompt>;" + defry
defry(강도): Normal=0 … Weakest=5 (값이 클수록 원본 변화가 약함). 1.5 NAIA_generation.augment_image_NAI 포팅.

제거: 이 파일 + websocket_session.py 의 NAI_DIRECTOR 임포트/분기 + 프론트 naiDirectorModal 삭제.
"""
from __future__ import annotations

import base64
import io
from typing import Any

import requests
from PIL import Image, ImageOps

NAI_AUGMENT_URL = "https://image.novelai.net/ai/augment-image"
NAI_DIRECTOR_COMMAND_TYPES = {"nai_director"}

# req_type 만 보내는 변형(프롬프트·defry 없음).
_BARE_MODES = {"declutter", "lineart", "sketch"}
# req_type + prompt + defry.
_PROMPT_MODES = {"colorize"}
_AUGMENT_TIMEOUT = 180.0

# defry 라벨 → NAI 정수값 (1.5 dfval). 라벨이 아니면 0.
_DEFRY_MAP = {
    "Normal": 0,
    "Slightly Weak": 1,
    "Weak": 2,
    "Even Weaker": 3,
    "Very Weak": 4,
    "Weakest": 5,
}

# 프론트 드롭다운에 노출되는 24개 emotion (1.5 em_list). 변형 4종(declutter/lineart/sketch/colorize)과
# 합쳐 하나의 드롭다운으로 제공된다. 백엔드 검증/정규화에만 사용(임의 문자열도 emotion 으로 폴백).
EMOTIONS = (
    "Neutral", "Happy", "Sad", "Angry", "Scared", "Surprised", "Tired", "Excited",
    "Nervous", "Thinking", "Confused", "Shy", "Disgusted", "Smug", "Bored", "Laughing",
    "Irritated", "Aroused", "Embarrassed", "Worried", "Love", "Determined", "Hurt", "Playful",
)


def _defry_value(label: Any) -> int:
    return _DEFRY_MAP.get(str(label or "").strip(), 0)


# NAI augment-image 는 소스 ~1MP 상한. Director 대상은 현재 결과(NAI 모드에서 업스케일된 hires 가
# 흔함)라 초과 시 NAI 가 non-ZIP 오류를 반환 → "디코드 실패"로 실패한다. 1.5 find_max_resolution
# (1,048,576px·/64 정렬) 의 결정적(랜덤 nudge 제외) 포팅. 이미 상한 이내면 원본 그대로 둔다.
def _augment_target_size(width: int, height: int, max_pixels: int = 1048576, multiple_of: int = 64) -> tuple[int, int]:
    if width <= 0 or height <= 0 or width * height <= max_pixels:
        return width, height
    ratio = width / height
    mw = int((max_pixels * ratio) ** 0.5) // multiple_of * multiple_of
    mh = int((max_pixels / ratio) ** 0.5) // multiple_of * multiple_of
    while mw > multiple_of and mh > multiple_of and mw * mh > max_pixels:
        mw -= multiple_of
        mh = int(mw / ratio) // multiple_of * multiple_of
    return max(multiple_of, mw), max(multiple_of, mh)


# emotion/colorize 프롬프트는 NAI Director 가 ~62 토큰만 허용(초과 시 non-ZIP 오류). 1.5 process_prompt
# 처럼 콤마 단위로 ≤62 토큰까지 절단. token_calculator(tiktoken/CLIP 근사) 사용, 실패 시 4자≈1토큰 근사.
_MAX_PROMPT_TOKENS = 62


def _prompt_token_counter():
    try:
        from utils.token_calculator import count_tokens

        return lambda s: count_tokens(s, current_mode="NAI")
    except Exception:
        return lambda s: (len(s) + 3) // 4


def _cap_prompt(prompt: str) -> str:
    text = str(prompt or "")
    if not text.strip():
        return text
    counter = _prompt_token_counter()
    try:
        if counter(text) <= _MAX_PROMPT_TOKENS:
            return text
        while text and counter(text) > _MAX_PROMPT_TOKENS:
            last_comma = text.rfind(",")
            if last_comma == -1:
                text = text[: _MAX_PROMPT_TOKENS * 4]  # 콤마 없음 → 보수적 문자 절단(1토큰≈4자)
                break
            text = text[:last_comma]
    except Exception:
        return text[: _MAX_PROMPT_TOKENS * 4]
    return text.strip().rstrip(",")


def augment_image_nai(token: str, image_bytes: bytes, mode: str, prompt: str = "", defry: str = "") -> dict[str, Any]:
    """`/ai/augment-image` 호출 → {'status','image'(PIL),'raw_bytes'(PNG)}.
    mode 는 declutter/lineart/sketch/colorize 또는 emotion 이름(Happy 등). emotion 은 req_type='emotion'
    으로 보내고 prompt 에 '<emotion>;;<user prompt>;' 를 인코딩한다(1.5 문법). 응답은 ZIP(이미지 1장 이상);
    Director 변형은 ZIP 의 **마지막** 이미지를 결과로 사용한다(1.5 augment_image_NAI 동일)."""
    if not token:
        return {"status": "error", "message": "NAI 로그인이 필요합니다 (API 설정 → NAI)."}
    try:
        with Image.open(io.BytesIO(image_bytes)) as src:
            src.load()
            rgb = src.convert("RGB")
        tw, th = _augment_target_size(*rgb.size)  # ~1MP 초과 시 비율 유지 다운스케일(/64)
        if (tw, th) != rgb.size:
            rgb = rgb.resize((tw, th), Image.LANCZOS)
        iw, ih = rgb.size
        out = io.BytesIO()
        rgb.save(out, format="PNG")
        src_b64 = base64.b64encode(out.getvalue()).decode("ascii")
    except Exception as exc:
        return {"status": "error", "message": f"소스 이미지 디코드 실패: {exc}"}

    raw_mode = str(mode or "").strip()
    low = raw_mode.lower()
    if low in _BARE_MODES:
        req_type = low
        data: dict[str, Any] = {"req_type": req_type, "width": iw, "height": ih, "image": src_b64}
    elif low in _PROMPT_MODES:  # colorize
        req_type = low
        data = {"req_type": req_type, "width": iw, "height": ih, "image": src_b64,
                "prompt": _cap_prompt(prompt), "defry": _defry_value(defry)}
    else:  # emotion (Happy/Sad/...) — 임의 문자열도 emotion 으로 폴백
        req_type = "emotion"
        emotion = low or "neutral"
        data = {"req_type": req_type, "width": iw, "height": ih, "image": src_b64,
                "prompt": f"{emotion};;{_cap_prompt(prompt)};", "defry": _defry_value(defry)}

    try:
        resp = requests.post(
            NAI_AUGMENT_URL,
            json=data,
            headers={"Authorization": f"Bearer {token}"},
            timeout=_AUGMENT_TIMEOUT,
        )
    except requests.exceptions.ConnectionError:
        return {"status": "error", "message": "NovelAI 에 연결할 수 없습니다."}
    except requests.exceptions.Timeout:
        return {"status": "error", "message": "Director 변형 시간 초과."}
    except Exception as exc:
        return {"status": "error", "message": f"Director 요청 실패: {exc}"}

    if resp.status_code == 401:
        return {"status": "error", "message": "NAI 인증 실패 (토큰 만료/무효)."}
    if resp.status_code == 402:
        return {"status": "error", "message": "Anlas 가 부족합니다."}
    if resp.status_code >= 400:
        message = f"NAI 오류 (HTTP {resp.status_code})"
        try:
            message += f": {resp.json().get('message', '')[:200]}"
        except Exception:
            pass
        return {"status": "error", "message": message}

    try:
        import zipfile

        archive = zipfile.ZipFile(io.BytesIO(resp.content))
        infos = archive.infolist()
        if not infos:
            return {"status": "error", "message": "Director 응답이 비어 있습니다."}
        # Director 변형은 마지막 이미지를 결과로 사용(1.5 동일). exif 정규화 + RGB.
        last_bytes = archive.read(infos[-1])
        with Image.open(io.BytesIO(last_bytes)) as img:
            img.load()
            pil = ImageOps.exif_transpose(img).convert("RGB")
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        png_bytes = buf.getvalue()
    except Exception as exc:
        return {"status": "error", "message": f"Director 이미지 디코드 실패: {exc}"}
    return {"status": "success", "image": pil, "raw_bytes": png_bytes, "message": "Director 변형 완료"}


def _result_token(context) -> str:
    try:
        return str(context.secure_token_manager.get_token("nai_token") or "").strip()
    except Exception:
        return ""


def perform_nai_director(context, payload: dict[str, Any] | None):
    """소스 해석 → augment → 표준 결과 파이프라인 주입. (run_in_thread 로 동기 실행)"""
    from app.backend.server.result_display_routes import (
        history_item_from_viewer_path,
        resolve_result_image_action_source,
    )
    from core.generation_request import GenerationRequest

    payload = payload if isinstance(payload, dict) else {}
    mode = str(payload.get("mode") or "").strip()
    if not mode:
        raise RuntimeError("변형 종류를 선택하세요.")
    token = _result_token(context)
    if not token:
        raise RuntimeError("NAI 로그인이 필요합니다 (API 설정 → NAI).")

    image_bytes, label, _gen_params, _prompt_ctx = resolve_result_image_action_source(context, payload)
    prompt = str(payload.get("prompt") or "")
    defry = str(payload.get("defry") or "")
    result = augment_image_nai(token, image_bytes, mode, prompt, defry)
    if not isinstance(result, dict) or result.get("status") != "success":
        raise RuntimeError(str((result or {}).get("message") or "Director 변형 실패"))

    params = {
        "input": prompt if prompt else mode,
        "negative_prompt": "",
        "api_mode": "NAI",
        "nai_director_request": True,
        "nai_director_mode": mode,
        "_remote_queue_source": "Director",
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
    return stored, str(result.get("message") or "Director 변형 완료")


async def handle_nai_director_command(ws, context, clients, command, *, run_in_thread) -> bool:
    """WS 'nai_director' 처리 — Grok I2I(handle_grok_command)와 동일 패턴."""
    command_type = str(command.get("type") or "").strip()
    if command_type not in NAI_DIRECTOR_COMMAND_TYPES:
        return False

    from app.backend.server.websocket_broadcast import broadcast_image, broadcast_json

    async def _send(obj: dict[str, Any]) -> None:
        try:
            await ws.send_json(obj)
        except Exception:
            pass

    await _send({"type": "nai_director_state", "running": True, "success": None, "message": "Director 변형 중…", "runtime": "web"})
    try:
        stored, message = await run_in_thread(perform_nai_director, context, command)
    except Exception as exc:
        msg = f"Director 변형 실패: {exc}"
        await _send({"type": "nai_director_state", "running": False, "success": False, "message": msg, "runtime": "web"})
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
    await _send({"type": "nai_director_state", "running": False, "success": True, "message": message, "runtime": "web"})
    await _send({"type": "toast", "level": "success", "message": message, "runtime": "web"})
    return True
