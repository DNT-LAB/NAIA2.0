"""투명 배경(Transparent BG) - V5 t2i 에서만 프롬프트에 태그 하나를 더 싣는다.

사용자 지정 2026-08-29. NAI 공홈의 "Transparent BG" 스위치와 같은 동작이다
(`Adds "transparent background" to the prompt.`).

**왜 화면이 아니라 여기서 붙이는가.** 프롬프트 창의 글은 사용자의 것이다 - 거기에
태그를 심으면 프리셋으로 저장되고, 스위치를 꺼도 글에 남는다. 나가는 자리에서만
실으면 스위치가 곧 진실이 된다(`reference_inset_service` 와 같은 관용).

**t2i 한정인 이유**: i2i/인페인트는 이미 배경이 있는 그림을 고쳐 그린다. 거기에
`transparent background` 를 실으면 NAI 가 없는 알파를 지어내려다 원본을 흐린다.
"""
from __future__ import annotations

from typing import Any, Dict

# 공홈이 넣는 그 태그 그대로.
TRANSPARENT_BACKGROUND_TAG = "transparent background"
# `remote_params` 키. 프론트의 알약과 같은 이름을 쓴다.
TRANSPARENT_BACKGROUND_PARAM = "transparent_background"
# 이 액션에서만 싣는다. `api_service` 의 `action_type` 값과 같은 어휘다
# (`generate` = t2i · `img2img` · `infill`).
TRANSPARENT_BACKGROUND_ACTION = "generate"


def transparent_background_requested(params: Dict[str, Any] | None) -> bool:
    """사용자가 스위치를 켜 두었는가.

    문자열 `"true"` 로도 온다 - 프론트가 `set_param` 으로 보내는 값은 문자열일 수
    있고, 프리셋/메타데이터 경로는 또 다르다. 세는 자를 하나로 둔다.
    """
    if not params:
        return False
    value = params.get(TRANSPARENT_BACKGROUND_PARAM)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"true", "1", "yes", "on"}


def model_spec_is_v5(model_spec: Any) -> bool:
    """이 요청이 V5 로 나가는가. 판정의 SSOT 는 모델 계약이다.

    ⚠️ 문자열(`"nai-diffusion-5-full"`)을 여기서 따로 뒤지지 않는다. 계약이
       `payload_profile` 을 들고 있고, 사용자 등록 모델도 그 프로필을 고른다 -
       문자열을 뒤지면 커스텀 V5 가 빠진다.
    """
    return str(getattr(model_spec, "payload_profile", "") or "") == "v5"


def should_inject_transparent_background(
    params: Dict[str, Any] | None,
    *,
    action_type: str,
    model_spec: Any,
) -> bool:
    """세 조건이 모두 참일 때만. 스위치 · V5 · t2i."""
    if not transparent_background_requested(params):
        return False
    if str(action_type or "") != TRANSPARENT_BACKGROUND_ACTION:
        return False
    return model_spec_is_v5(model_spec)


def transparent_background_already_present(prompt: str) -> bool:
    """이미 글 안에 있으면 또 넣지 않는다.

    ⚠️ 태그 단위로 자르지 않고 **부분 문자열**로 본다. 와일드카드 전개는 원소 하나에
       여러 태그를 콤마로 묶어 넣는 일이 잦고, 가중치 문법(`1.2::tag::`)도 붙는다 -
       정확히 자르려다 놓치는 쪽이 나쁘다(`reference_inset_service` 와 같은 판단).
    """
    return TRANSPARENT_BACKGROUND_TAG in str(prompt or "").lower()


def inject_transparent_background(prompt: str) -> str:
    """프롬프트 **끝**에 태그를 붙인 문자열. 이미 있으면 그대로 돌려준다.

    끝에 붙이는 이유: 공홈의 문구가 "adds to the prompt" 이고, 사용자가 쓴 글의
    순서를 흐트러뜨리지 않는 자리가 끝이다. 품질 태그 뒤가 된다.
    """
    text = str(prompt or "")
    if transparent_background_already_present(text):
        return text
    stripped = text.rstrip()
    if not stripped:
        return TRANSPARENT_BACKGROUND_TAG
    # 이미 쉼표로 끝나면 쉼표를 겹치지 않는다.
    if stripped.endswith(","):
        return f"{stripped} {TRANSPARENT_BACKGROUND_TAG}"
    return f"{stripped}, {TRANSPARENT_BACKGROUND_TAG}"
