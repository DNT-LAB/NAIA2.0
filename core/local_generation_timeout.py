"""로컬 생성(외부 ComfyUI · 내장 ANIMA · WEBUI) 한 장을 기다리는 한도 - Settings > Global > 생성.

사용자 제보 2026-11-24: 사양이 낮아 ComfyUI 한 장이 180초를 넘으면 Auto Gen 이 멈춘다. 재시도를 덧대는 대신
한도를 사용자가 정하게 한다(유지보수자 결정). 기본 180초 · 0 = Off(기다림 제한 없음). NAI 에는 걸지 않는다.

값은 서버가 쥔다 - ``context.local_generation_timeout_seconds``(정수). ``remote_options``(불린 전용 통로 · 매 요청의
파라미터 -> 그림의 생성 정보로 실림)에는 넣지 않고 remote_web 상태의 따로 된 키로 저장한다. 화면으로는 ``options``
메시지에 함께 실어 보내고(``get_options``), 화면은 같은 ``set_option`` 명령으로 바꾼다.

생성 길목은 둘뿐이다 - ``APIService._call_comfyui_api_once`` · ``APIService._call_webui_api``. 단발 [생성] · Auto Gen ·
창들의 생성이 모두 그 둘을 지나므로, 요청 파라미터가 아니라 **부르는 순간의 context** 에서 읽는다.
"""

from __future__ import annotations

import math
from typing import Any, Optional

OPTION_KEY = "local_generation_timeout_seconds"
# Auto Gen 이 도는 중에 시간 초과가 나면 같은 장을 3회까지 다시 보낸다(기본 꺼짐 - 사용자 지정 2026-11-24).
RETRY_OPTION_KEY = "local_timeout_retry_in_auto_gen"
DEFAULT_SECONDS = 180
OFF = 0
MIN_SECONDS = 30
MAX_SECONDS = 7200
SETTINGS_HINT = "시간 제한은 Settings > 생성에서 늘리거나 끌 수 있습니다"


def normalize_seconds(value: Any) -> int:
    """저장 · 입력 값을 정수 초로. 0(또는 'off') = Off. 없거나 읽을 수 없으면 기본 180.

    0 보다 크면 [MIN_SECONDS, MAX_SECONDS] 로 자른다 - 3초 같은 값은 생성마다 실패만 낸다."""
    if value is None or isinstance(value, bool):
        return DEFAULT_SECONDS
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"off", "none", "0"}:
            return OFF
        value = text
    try:
        number = float(value)
    except (TypeError, ValueError):
        return DEFAULT_SECONDS
    if not math.isfinite(number) or number < 0:
        return DEFAULT_SECONDS
    if number == 0:
        return OFF
    return int(min(MAX_SECONDS, max(MIN_SECONDS, round(number))))


def configured_seconds(context: Any) -> int:
    """설정된 값(정수 · 0 = Off). context 에 값이 없으면(옛 AppContext 등) 기본 180."""
    return normalize_seconds(getattr(context, OPTION_KEY, DEFAULT_SECONDS))


def timeout_seconds(context: Any) -> Optional[float]:
    """한 장을 기다릴 초. ``None`` = 제한 없음(Off)."""
    seconds = configured_seconds(context)
    return None if seconds == OFF else float(seconds)


def retry_timeout_in_auto_gen(context: Any) -> bool:
    """시간 초과를 다시 보내도 되는가 - 체크박스가 켜져 있고 Auto Gen 이 도는 중일 때만."""
    try:
        options = context.get_options()
    except Exception:  # noqa: BLE001 - 옛 AppContext 는 옵션 통로가 없다
        return False
    if not isinstance(options, dict):
        return False
    return bool(options.get(RETRY_OPTION_KEY)) and bool(options.get("auto_generate"))


def timeout_message(backend: str, seconds: float, detail: str) -> str:
    """시간 초과 안내 - 무엇이 넘었는지 · 서버 쪽 작업이 어떻게 됐는지 · 설정에서 바꿀 수 있다는 것."""
    return f"{backend} 생성 시간 초과({seconds:g}초) - {detail} · {SETTINGS_HINT}"
