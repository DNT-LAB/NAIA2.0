"""이번 세션에 **무료로** 나간 V5 생성이 몇 장인가.

배경
----
V5 사용량 배지는 퍼센트를 보여 줬는데, 그 값이 정수라 **1% 가 약 17장**이다. 한 장
뽑아도 눈금이 안 움직여서 "생성했는데 배지가 그대로" 로 보인다. 그래서 퍼센트 게이지
대신 **이번 세션에 무료로 뽑은 장수**를 센다(사용자 지시 2026-08-21).

무료 판정
--------
**28스텝 이하 · 1MP 이하** 두 가지다. 모델은 안 본다.

⚠️ 처음엔 V5 만 무료로 셌는데 **틀렸다**(사용자 지적 2026-08-21). Opus 구독의
무료 생성은 V4.5 이하에도 여태 적용돼 왔다 - 그래서 V4.5 화면의 무료 카운터가 영영
0 이었다("NAID4.5에서 이번 세션 무료 생성 카운트가 업데이트 되지 않습니다").

계열 차이는 **무료냐** 가 아니라 **무엇을 깎느냐** 다:
    V4.5 이하  무료 생성은 아무것도 깎지 않는다(무제한).
    V5        무료 생성이 Opus 사용량 %(약 1730장)에서 깎인다.
어느 쪽이든 1MP·28스텝을 넘으면 Anlas 로 청구된다.

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

# 이번 세션에 나간 **모든** NAI 생성 장수(무료·유료 가리지 않는다).
#
# ⚠️ 비V5 화면이 이 값을 쓴다. 처음엔 거기도 무료 카운터를 띄웠는데, V4.5 생성은
# 정의상 무료가 아니라 **숫자가 영영 안 움직였다**(사용자 지적 2026-08-21:
# "NAID4.5에서 이번 세션 무료 생성 카운트가 업데이트 되지 않습니다"). 그 화면이
# 답해야 하는 질문은 "이번 세션에 몇 장 뽑았나" 이므로 전체를 센다.
_TOTAL_COUNT_ATTR = "nai_session_generation_count"

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
    """이 생성이 Anlas 를 안 물고 나갔는가(= 1MP·28스텝 이하 txt2img).

    ⚠️ **고른 모델이 아니라 실제로 나간 것을 봐야 한다.** img2img/인페인트/Enhance 는
    해상도·스텝이 아무리 작아도 Anlas 로 청구된다(Codex 리뷰 2026-08-21 지적,
    실측 확인). 대체(V5->4.5)를 카운터보다 나중에 넣고 카운터를 다시 안 봐서
    **유료 작업이 무료로 집계되고 있었다.**
    """
    params = params or {}

    # 이미지를 싣고 온 요청(img2img · 인페인트 · Enhance)은 무료가 아니다.
    if params.get("image_bytes") is not None or params.get("init_image_bytes") is not None:
        return False
    # 대체가 실제로 일어났다는 표식이 있으면 그것도 유료다(경로가 늘어나도 안전하게).
    if params.get("_nai_img2img_fallback_model") or params.get("_nai_inpaint_fallback_model"):
        return False
    # 사용자가 payload 를 직접 덮어썼으면 우리가 아는 steps/해상도가 실제와 다를 수
    # 있다 - 모르면 무료로 치지 않는다.
    if params.get("use_custom_api_params"):
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
    """생성 1장을 반영하고 현재까지의 무료 장수를 돌려준다.

    총 장수는 무료 여부와 상관없이 **항상** 오른다.
    """
    setattr(context, _TOTAL_COUNT_ATTR, total_count(context) + 1)
    if not is_free_generation(context, params):
        return free_count(context)
    count = free_count(context) + 1
    setattr(context, _FREE_COUNT_ATTR, count)
    return count


def _count(context: Any, attr: str) -> int:
    value = getattr(context, attr, 0)
    return value if isinstance(value, int) and value >= 0 else 0


def free_count(context: Any) -> int:
    return _count(context, _FREE_COUNT_ATTR)


def total_count(context: Any) -> int:
    return _count(context, _TOTAL_COUNT_ATTR)


def session_elapsed_seconds() -> int:
    return max(0, int(time.monotonic() - _PROCESS_START))


def session_payload(context: Any) -> dict[str, Any]:
    """배지/패널이 쓰는 세션 요약."""
    return {
        "free_generations": free_count(context),
        "session_generations": total_count(context),
        "elapsed_seconds": session_elapsed_seconds(),
    }
