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
