"""이번 세션에 **무료로** 나간 V5 생성이 몇 장인가.

배경
----
V5 사용량 배지는 퍼센트를 보여 줬는데, 그 값이 정수라 **1% 가 약 17장**이다. 한 장
뽑아도 눈금이 안 움직여서 "생성했는데 배지가 그대로" 로 보인다. 그래서 퍼센트 게이지
대신 **이번 세션에 무료로 뽑은 장수**를 센다(사용자 지시 2026-08-21).

무료 판정
--------
NAI 안내문 그대로 **V5 모델 · 28스텝 이하 · 1MP 이하**. 이 셋을 다 만족한 생성만
Opus 무료 사용량에서 나간다. 하나라도 넘으면 Anlas 로 청구되므로 세지 않는다.

⚠️ 여기서 넉넉하게 세면 사용자가 "무료로 N장 썼다" 고 믿는 숫자가 실제와 어긋난다.
경계는 **이하(<=)** 다 - NAI 가 "up to 28 steps" 라고 쓴 그대로.
"""

from __future__ import annotations

import time
from typing import Any

# NAI 안내문: "free NovelAI Diffusion V5 generations at normal resolutions and
# up to 28 steps".
FREE_STEPS_MAX = 28
FREE_PIXELS_MAX = 1024 * 1024

_FREE_COUNT_ATTR = "nai_session_free_generation_count"

# 백엔드 프로세스가 뜬 시각. "현재 세션의 총 실행 시간" 의 기준이다.
# ⚠️ `time.time()` 이 아니라 monotonic 이다 - 시계가 뒤로 가면(NTP 보정·절전 복귀)
# 경과 시간이 음수가 될 수 있다.
_PROCESS_START = time.monotonic()


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def is_free_generation(context: Any, params: dict[str, Any] | None) -> bool:
    """이 생성이 V5 무료 범위 안에서 나갔는가."""
    params = params or {}
    try:
        from core.nai_model_contract import resolve_nai_model_for_context

        model_key = str(params.get("model") or "")
        if not model_key:
            model_key = str(context._current_model_key() or "")
        if not resolve_nai_model_for_context(context, model_key).uses_opus_usage_limit:
            return False
    except Exception:
        return False

    if _as_int(params.get("steps"), 9999) > FREE_STEPS_MAX:
        return False

    width = _as_int(params.get("width"))
    height = _as_int(params.get("height"))
    if not (width and height):
        # 해상도 문자열("1024 x 1024")만 있는 경로를 위한 폴백.
        raw = str(params.get("resolution") or "").lower().replace(" ", "")
        if "x" in raw:
            left, _, right = raw.partition("x")
            width, height = _as_int(left), _as_int(right)
    if not (width and height):
        return False                    # 크기를 모르면 무료라고 단정하지 않는다
    return width * height <= FREE_PIXELS_MAX


def note_generation(context: Any, params: dict[str, Any] | None) -> int:
    """생성 1장을 반영하고 현재까지의 무료 장수를 돌려준다."""
    if not is_free_generation(context, params):
        return free_count(context)
    count = free_count(context) + 1
    setattr(context, _FREE_COUNT_ATTR, count)
    return count


def free_count(context: Any) -> int:
    value = getattr(context, _FREE_COUNT_ATTR, 0)
    return value if isinstance(value, int) and value >= 0 else 0


def session_elapsed_seconds() -> int:
    return max(0, int(time.monotonic() - _PROCESS_START))


def session_payload(context: Any) -> dict[str, Any]:
    """배지/패널이 쓰는 세션 요약."""
    return {
        "free_generations": free_count(context),
        "elapsed_seconds": session_elapsed_seconds(),
    }
