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
    return str(params.get("type") or "").strip().lower() in SPECIAL_REQUEST_TYPES
