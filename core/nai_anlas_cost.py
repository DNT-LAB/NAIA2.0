"""이번 생성이 Anlas 를 얼마나 무는가 - Generate 버튼 옆에 미리 보여 주려고.

출처
----
NAI 웹 UI 의 `calculateCost` 를 옮긴 뒤, **NAI 웹에서 직접 측정해 보정**했다
(2026-08-28, Opus 계정, novelai.net/image 의 금액 표시를 읽음 - 생성은 하지 않음).
**공식 API 계약이 아니다** - NAI 가 가격을 바꾸면 여기 숫자가 조용히 낡는다.
그래서 이 값은 어디까지나 **표시용 추정치**이고, 실제 청구·집계에는 쓰지 않는다.

실측으로 바로잡은 것 둘
---------------------
1. **V5 는 x1.5 다.** 래퍼 구현의 식대로면 1472x1472 28스텝이 42 인데 웹은 63 을
   보여 준다. V4.5/V4/V3 은 42 그대로 - **V5 계열에만** 붙는 배수다.
   (V5 Full/Curated 값이 같은 것도 확인했다.)
2. **정사각 가격 보정이 사라졌다.** 래퍼에는 "1024x1024 를 832x1216 값으로 청구"
   하는 보정이 있는데, 지금 웹은 1024x1024 29스텝을 21(V4.5)/32(V5) 로 매긴다 -
   보정이 살아 있으면 20/30 이어야 한다. 모든 모델에서 빠졌다.

무료 조건은 그대로다: `steps <= 28 and px <= 1,048,576`(Opus). 1024x1024 는 28스텝
까지 0 이고 29스텝부터 값이 붙는 것을 확인했다.

⚠️ 첫 측정은 **무효였다.** 스텝 입력이 포커스를 뗄 때 커밋되는데 합성 이벤트로
   바꿔서 반영이 안 됐고, "스텝이 비용에 영향 없다" 는 틀린 결론이 나왔다
   (사용자 지적으로 바로잡음). 다시 잴 일이 있으면 **실제 입력(fill+Tab)** 을 써라.

무료 판정은 여기서 다시 하지 않고 `core.nai_free_usage.is_free_generation` 을 **그대로
쓴다**. 두 곳에서 따로 판정하면 "Generate 옆은 0 Anlas 인데 상단 알약은 점멸" 같은
어긋남이 생긴다 - 그 둘은 같은 사실을 말해야 한다.

검산(2026-08-28)
--------------
웹 실측 23점(1472x1472 스텝 1~50 · 28스텝 해상도 7종 · 무료 경계 5종)에 대해
아래 식이 **23/23 일치**한다. `tests/test_nai_anlas_cost.py` 가 그 표를 들고 있다.

모델링하지 않은 것
----------------
- `uncond_scale`(x1.3) : 앱에 그 파라미터가 없다.
- `n_samples`          : 이 앱은 항상 한 장씩 보낸다.
- img2img `strength`   : 인페인트/i2i 는 어차피 유료라 경고 목적은 이미 달성된다.
                         정확한 금액이 필요해지면 세션 strength 를 넘겨받아야 한다.
- SMEA/DYN 은 반영한다 - 다만 V4 이상은 autoSmea 를 쓰므로 실제로는 레거시(V3)에서만
  1 이 아닌 값이 된다(`core/api_service.py` 의 `uses_legacy_smea`).
"""

from __future__ import annotations

import math
from typing import Any

from core.nai_free_usage import is_free_generation

# NAI `calculateCost` 의 상수. 손대지 말 것 - 바꾸려면 **웹에서 다시 재라**.
_AREA_COEFF = 2951823174884865e-21
_AREA_STEP_COEFF = 5.753298233447344e-7
_MIN_PIXELS = 65536                 # 256x256. 이보다 작아도 이 값으로 친다.
_MIN_PER_SAMPLE = 2                 # 아무리 작아도 2 Anlas
# V5 계열에만 붙는 배수(2026-08-28 실측). V4.5 이하는 1.0 이다.
_V5_MULTIPLIER = 1.5


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _pixels(params: dict[str, Any]) -> int:
    width = _as_int(params.get("width"))
    height = _as_int(params.get("height"))
    if not (width and height):
        raw = str(params.get("resolution") or "").lower().replace(" ", "")
        if "x" in raw:
            left, _, right = raw.partition("x")
            width, height = _as_int(left), _as_int(right)
    if not (width and height):
        return 0
    return width * height


def _is_v5(context: Any) -> bool:
    """지금 고른 모델이 V5 계열인가.

    판정은 모델 계약이 SSOT 다(`context_uses_opus_usage_limit`) - 사용량 배지·부하
    분산 정책·무료 집계가 모두 그 함수를 본다. 여기서 따로 문자열을 뒤지면 한쪽만
    고쳐져 화면이 서로 다른 말을 한다.
    """
    try:
        from core.nai_model_contract import context_uses_opus_usage_limit

        return bool(context_uses_opus_usage_limit(context))
    except Exception:   # noqa: BLE001 - 판정 실패가 표시를 막으면 안 된다
        return False


def estimate_anlas_cost(context: Any, params: dict[str, Any] | None,
                        *, ignore_free: bool = False) -> int:
    """이번 생성의 Anlas 추정치. 무료면 0.

    크기를 모르면 0 을 돌려준다 - 모르면서 숫자를 지어내면 안 된다.

    `ignore_free=True` 는 **무료 대역이어도 값을 매긴다.** Opus 무료 풀(V5 사용량 %)이
    마르면 1MP·28스텝 이하도 Anlas 로 청구되기 때문이다 - 그때 화면이 "무료" 라고
    말하면 사용자가 모르는 사이에 돈이 나간다(사용자 지정 2026-08-28).
    실측 확인: 로그아웃(=무료분 없음) 상태의 NAI 웹이 832x1216 23스텝을 26 으로
    매기는데, 이 계산이 같은 26 을 낸다.
    """
    params = params or {}
    if not ignore_free and is_free_generation(context, params):
        return 0

    resolution = _pixels(params)
    if not resolution:
        return 0
    resolution = max(resolution, _MIN_PIXELS)

    steps = _as_int(params.get("steps"), 28)
    dyn = bool(params.get("DYN"))
    smea = bool(params.get("SMEA")) or dyn
    factor = 1.4 if dyn else (1.2 if smea else 1.0)
    if _is_v5(context):
        # ⚠️ 배수는 **안쪽 ceil 뒤에** 곱한다. 먼저 곱하면 35스텝 1472x1472 이
        #    76 이 되는데 웹은 77 이다(실측). 순서가 값을 바꾼다.
        factor *= _V5_MULTIPLIER

    per_sample = math.ceil(
        _AREA_COEFF * resolution + _AREA_STEP_COEFF * resolution * steps
    ) * factor
    return max(math.ceil(per_sample), _MIN_PER_SAMPLE)
