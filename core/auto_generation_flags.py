"""Auto Generate / run-policy 공유 '특수 요청' 판정.

generation_runner(연쇄 억제·Automation 바인딩)와 core 소비자(Storyteller Use Vibe의
plain-generate 판정)가 같은 목록을 봐야 하므로 core에 둔다 — import 방향은
app/backend → core 만 허용되기 때문에 runner 쪽 로컬 정의를 이쪽으로 옮겼다.
"""

from __future__ import annotations

from typing import Any, Callable

# 특수 요청 마커: 이 플래그가 켜진 완료는 Auto Generate 연쇄/Automation 카운트에서
# 제외된다(이벤트 프리셋·캐릭터 뷰어·인핸스 등). Storyteller Use Vibe도 같은 기준으로
# "plain generate"가 아니면 캡처도 주입도 하지 않는다.
AUTO_GENERATE_SUPPRESSED_FLAGS = {
    "artist_thumb_request",
    "character_asset_request",
    "character_viewer_request",
    "event_preset_request",
    "interactive_mode_request",
    "prompt_preset_thumbnail_request",
    "remote_preset_request",
    "result_enhance_request",
    "sequence_preset_request",
    "studio_request",
    "turbo_sequence_request",
}

# img2img류 요청 타입: 위 플래그와 동일하게 특수 취급.
SPECIAL_REQUEST_TYPES = {"img2img", "inpaint", "outpaint", "auto_outpainting"}

# 레퍼런스 인셋 핀([C1 + 레퍼런스 인셋 적용])이 plain generate에 주입하는 마커.
# 이 생성은 type=inpaint로 나가지만 사용자 관점에선 일반 생성이다 - 특수 취급하면
# 핀 상태에서 Auto Gen 연쇄가 조용히 멈추고 Automation 카운트에서 빠진다.
REFERENCE_INSET_PIN_MARKER = "_reference_inset_pin"


# ----------------------------------------------------------------------
# Interactive 생성 게이트
# ----------------------------------------------------------------------

# Interactive 모드는 프롬프트를 블록에서 결정론적으로 조립한다. prompt_fixed(랜덤 생성 잠금)와
# wildcard_standalone(DB 태그 없이 빈 source_row 시작)은 그 전제와 충돌한다.
#
# 세션 옵션(set_option)으로 끄면 안 된다: set_option 은 전 클라이언트에 broadcast 되고
# (session_commands.py) remote_options 로 영속된다(headless_remote_ui_state_service.py).
# 한 탭이 Interactive 를 켜면 다른 탭의 설정이 꺼지고 그 값이 저장돼 버린다.
# 따라서 **요청 단위로만** 강제한다.
#
# 프론트는 두 옵션을 화면에서 비활성화만 한다(INTERACTIVE_BLOCKED_OPTIONS - 표시 전용,
# 같은 이유). 그래서 Interactive 를 켜기 **전에** 켜 뒀다면 저장값은 켜진 채 남고,
# `_normalized_params` 의 `params.update(get_options())` 가 그걸 매 요청에 싣는다.
# 실측(2026-08-11): 이미지 자체는 멀쩡했지만 `wildcard_standalone` 이 살아서
# source_row 가 사용자의 실제 행 대신 빈 행("wildcard_standalone")으로 바뀌었다 -
# 프롬프트 런 기록이 어느 행에서 나온 생성인지를 잃는다.
INTERACTIVE_FORCED_PARAMS = {
    "interactive_mode_request": True,   # 위 AUTO_GENERATE_SUPPRESSED_FLAGS 의 마커 재사용
    "prompt_fixed": False,
    "wildcard_standalone": False,
}


def apply_interactive_generation_gate(params: dict[str, Any]) -> dict[str, Any]:
    """Interactive 생성 요청에 플래그를 강제한다. 저장된 사용자 옵션은 건드리지 않는다.

    ``interactive_mode_request`` 는 AUTO_GENERATE_SUPPRESSED_FLAGS 에 이미 등록돼 있어
    Auto Generate 연쇄와 Automation 카운트에서 자동 제외된다(실측: 마커만으로 이미
    연쇄가 끊긴다 - 이 게이트가 거기서 더 하는 일은 없다).

    **마커가 이미 붙은 요청에만 걸어야 한다.** 무조건 부르면 모든 생성이 Interactive 로
    둔갑해 Auto Gen 연쇄가 통째로 멈춘다.
    """
    if not isinstance(params, dict):
        return dict(INTERACTIVE_FORCED_PARAMS)
    params.update(INTERACTIVE_FORCED_PARAMS)
    return params


def _default_coerce(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def is_special_request(
    params: dict[str, Any],
    coerce_bool: Callable[[Any], bool] | None = None,
) -> bool:
    """Auto Gen 억제 규칙과 동일한 '특수 요청' 판정(플래그 또는 img2img류 타입)."""
    if not isinstance(params, dict):
        return True
    coerce = coerce_bool if callable(coerce_bool) else _default_coerce
    if any(coerce(params.get(key, False)) for key in AUTO_GENERATE_SUPPRESSED_FLAGS):
        return True
    # 인셋 핀 마커가 있으면 plain generate다(억제 플래그가 없을 때만 - 벤치 인페인트
    # 등은 위 플래그가 먼저 잡는다). type=inpaint 판정보다 앞서야 한다.
    if coerce(params.get(REFERENCE_INSET_PIN_MARKER, False)):
        return False
    return str(params.get("type") or "").strip().lower() in SPECIAL_REQUEST_TYPES
