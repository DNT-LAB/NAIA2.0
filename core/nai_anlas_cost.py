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
import threading
import uuid
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


def _reference_inset_canvas(context: Any) -> tuple[int, int] | None:
    """레퍼런스 인셋이 켜져 있으면 그 캔버스 - 일반 생성이 그 크기의 인페인트로 나간다. 아니면 None."""
    try:
        getter = getattr(context, "_character_asset_service", None)
        service = getter() if callable(getter) else None
        canvas = service.reference_inset_active_canvas() if service is not None else None
    except Exception:   # noqa: BLE001 - 판정 실패가 표시를 막으면 안 된다
        return None
    if (isinstance(canvas, tuple) and len(canvas) == 2
            and all(isinstance(side, int) and side > 0 for side in canvas)):
        return canvas
    return None


# 금액의 차례를 매기는 자리. 번호는 이 실행(프로세스) 안에서만 뜻이 있다 - 다시 켜면 표식(`session`)이 바뀐다.
_COST_REV_LOCK = threading.Lock()
_COST_REV_SESSION = uuid.uuid4().hex[:12]


def cost_snapshot_for_context(context: Any) -> dict[str, Any]:
    """지금 [Generate] 를 누르면 나갈 금액과 **그 금액의 차례**.

    돌려주는 것: `nai_anlas_cost` · `nai_anlas_cost_if_paid`(NAI 가 아니면 0) · `nai_inset_cost` ·
    `nai_inset_cost_if_paid` · `nai_cost_rev` = `{session, rev}` · `params`(계산에 쓴 파라미터 - 화면에 보내지 않는다).

    ⚠️ **금액은 두 벌이다.** `nai_anlas_cost` 는 레퍼런스 인셋 **없이** 나가는 요청의 금액이고(Params 탭 해상도 또는
       인페인트 세션의 캔버스 - 인셋이 생기기 전과 같은 뜻), `nai_inset_cost` 는 인셋으로 나가는 요청의 금액이다
       (인셋이 꺼져 있거나 인페인트 세션이 열려 있으면 None). 서버는 화면이 어느 탭에 있는지 · Interactive 가 켜져
       있는지 모른다 - 프리셋 · 시퀀스 탭과 Interactive 의 생성은 인셋이 주입되지 않는다. 한 벌만 보내면 어느 한쪽이
       틀린다(Codex 리뷰 8차: 무료 인셋을 켠 채 유료 해상도로 프리셋 생성 - 금액 0). 화면이 실제로 나갈 길을 고른다.

    화면은 금액을 여러 길로 받는다 - 파라미터 메시지(WS)와 레퍼런스 인셋의 상태(HTTP). 길이 다르면 순서가 뒤바뀐다:
    스텝이나 해상도를 바꿔 새 금액을 받은 뒤에 **그 전에 계산된** 답이 늦게 오면 옛 금액이 새 금액을 덮는다(유료인데
    금액 칩이 사라졌다 - Codex 리뷰 2026-10-10). 그래서 금액을 계산할 때마다 여기서 번호를 붙인다: 금액이나 그 근거
    (모드 · 모델 · 스텝 · 샘플링 옵션 · **실제로 나갈 해상도**)가 앞의 계산과 달라지면 +1. 화면은 번호가 낮은 금액을 버린다.

    ⚠️ 읽기 · 계산 · 번호 붙이기를 **한 잠금 안에서** 한다. 밖에서 계산하고 들어와 번호만 받으면, 먼저 읽은(낡은)
       계산이 나중에 들어와 더 높은 번호를 받는다.
    ⚠️ 이 잠금을 쥔 채 `cost_params_for_context` 가 캐릭터 에셋 서비스의 `_retain_lock` 을 잡는다(순서: 이 잠금 ->
       `_retain_lock`). 그 잠금을 쥔 채 이 함수를 부르지 말 것.
    """
    with _COST_REV_LOCK:
        params = cost_params_for_context(context, with_inset=False)
        try:
            mode = str(context.get_api_mode() or "").upper()
        except Exception:   # noqa: BLE001
            mode = ""
        if mode == "NAI":
            price = int(estimate_anlas_cost(context, params))
            price_if_paid = int(estimate_anlas_cost(context, params, ignore_free=True))
        else:
            price = price_if_paid = 0
        # 인셋으로 나가는 요청의 금액(인셋이 켜져 있고 인페인트 세션이 없을 때만 그런 요청이 있다).
        inset_price = inset_price_if_paid = None
        session = getattr(context, "img2img_session", None)
        canvas = None if isinstance(session, dict) and session.get("active") else _reference_inset_canvas(context)
        if canvas:
            through = {**params, "width": canvas[0], "height": canvas[1], "resolution": f"{canvas[0]} x {canvas[1]}"}
            if mode == "NAI":
                inset_price = int(estimate_anlas_cost(context, through))
                inset_price_if_paid = int(estimate_anlas_cost(context, through, ignore_free=True))
            else:
                inset_price = inset_price_if_paid = 0
        basis = "|".join(str(part) for part in (
            mode, price, price_if_paid, inset_price, inset_price_if_paid, canvas,
            _pixels(params), params.get("width"), params.get("height"),
            params.get("model"), params.get("steps"), params.get("SMEA"), params.get("DYN"),
            params.get("use_custom_api_params"),
        ))
        state = getattr(context, "_nai_cost_rev_state", None)
        if not isinstance(state, dict) or state.get("basis") != basis:
            state = {"basis": basis, "rev": int(state.get("rev", 0)) + 1 if isinstance(state, dict) else 1}
            try:
                setattr(context, "_nai_cost_rev_state", state)
            except Exception:   # noqa: BLE001 - 못 적으면 매번 같은 번호가 나갈 뿐이다(화면은 같은 번호를 받는다)
                pass
        return {
            "nai_anlas_cost": price,
            "nai_anlas_cost_if_paid": price_if_paid,
            "nai_inset_cost": inset_price,
            "nai_inset_cost_if_paid": inset_price_if_paid,
            "nai_cost_rev": {"session": _COST_REV_SESSION, "rev": int(state["rev"])},
            "params": params,
        }


def cost_params_for_context(context: Any, *, with_inset: bool = True) -> dict[str, Any]:
    """지금 [Generate] 를 누르면 **실제로 나갈** 파라미터.

    ``with_inset=False`` 면 레퍼런스 인셋을 안 본다 - 인셋이 주입되지 않는 요청(프리셋 · 시퀀스 · Interactive)의
    금액을 매길 때 쓴다(`cost_snapshot_for_context` 가 두 벌을 다 계산한다).

    ⚠️ 인페인트/img2img 세션이 열려 있으면 나가는 것은 Params 탭의 해상도가 아니라
       **캔버스**다. 도크에서 Wallpaper 로 옮겨 놓고도 화면이 옛 해상도의 금액을
       말하면 안 된다(실측 2026-08-28: 1280x1280 로 바꾸니 실제 청구는 14 였다).
    ⚠️ 스텝은 세션에 없다 - 인페인트도 Params 탭 값을 그대로 쓰므로 손대지 않는다.
    ⚠️ **유료 표식을 여기서 세우지 않는다.** 한때 "인페인트는 이미지를 싣고 가니
       무조건 유료" 라고 `image_bytes` 를 끼워 넣었는데, 라이브 실측이 그것을
       뒤집었다 - 1MP·28스텝 이하 인페인트는 Anlas 를 **안 문다**. 판정은
       `is_free_generation` 하나에 맡긴다(그쪽 주석에 실측표가 있다).
    """
    params = dict(getattr(context, "remote_params", {}) or {})
    # 모델이 고정하는 값(Medium: 14스텝)이 있으면 그것이 실제로 나간다 - 저장된 steps 40 으로
    # 값을 매기면 있지도 않은 금액이 뜬다. 사본에만 덧씌운다.
    try:
        from core.nai_model_contract import apply_nai_fixed_params

        apply_nai_fixed_params(context, params)
    except Exception:   # noqa: BLE001 - 판정 실패가 표시를 막으면 안 된다
        pass
    session = getattr(context, "img2img_session", None)
    if not isinstance(session, dict) or not session.get("active"):
        # ⚠️ 레퍼런스 인셋이 켜져 있으면 일반 생성은 Params 탭의 해상도가 아니라 **인셋 캔버스**로 나간다. 그 캔버스는
        #    1MP 를 넘을 수 있다(고해상도 캔버스 - 사용자 지정 2026-10-10). 여기서 안 보면 금액이 0 으로 보이면서
        #    Anlas 가 나간다. (인페인트 세션이 열려 있으면 인셋은 주입되지 않는다 - 아래 세션 캔버스가 맞다.)
        canvas = _reference_inset_canvas(context) if with_inset else None
        if canvas:
            params["width"], params["height"] = canvas
            params["resolution"] = f"{canvas[0]} x {canvas[1]}"
        return params
    width = int(session.get("width") or 0)
    height = int(session.get("height") or 0)
    if width > 0 and height > 0:
        params["width"], params["height"] = width, height
        params["resolution"] = f"{width} x {height}"
    return params
