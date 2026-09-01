# -*- coding: utf-8 -*-
"""NAI V4.5 Preview — V5 할당량을 안 쓰고 구도만 먼저 본다.

사용자 요청 2026-09-01:
  "NAI V5 모드에서, 할당량을 아끼고 생성하려는 이미지의 실제 구조를 볼 수 있도록
   하기위해 Small 해상도 Spec, 약 10 Step 에서 NAI 4.5로 생성하여 Preview를 보는
   기능을 도입하고자 합니다."

## 왜 이것이 공짜인가

`core.nai_free_usage` 가 적어 둔 그대로다 — 계열 차이는 **무료냐**가 아니라
**무엇을 깎느냐**다:

    V4.5 이하  무료 생성은 아무것도 깎지 않는다(무제한).
    V5        무료 생성이 Opus 사용량 %(약 1730장)에서 깎인다.

그래서 Small(<1MP) · 10스텝을 **V4.5 로** 뽑으면 Anlas 도 V5 사용량도 안 움직인다.
같은 그림을 V5 로 뽑으면 사용량이 깎인다 — 그 차이가 이 기능의 전부다.

## 돈이 새지 않게 하는 두 겹

1. **`assert_free` (여기)** — 디스패치 직전에 `is_free_generation` 으로 다시 묻는다.
   그 함수는 fail-safe 라 스텝이나 크기를 **모르면 유료로 눕는다**. 나중에 누가
   해상도 계산을 건드려도 이 문에서 걸린다.
2. **특수 요청 마커** — `nai_preview_request` 를 `AUTO_GENERATE_SUPPRESSED_FLAGS` 에
   등록해 두었다. 그러면 Vibe 주입 · 레퍼런스 인셋 핀 · 스트림 Vibe 가 **한 자리에서**
   빠진다([[feedback_gate_at_the_neck]]). ⚠️ Vibe 는 특히 중요하다 — 인코딩 자체가
   2 Anlas 라 `is_free_generation` 으로는 안 잡힌다.
"""

from __future__ import annotations

from typing import Any

from core.nai_free_usage import is_free_generation
from core.resolution_utils import nearest_nai_preset_resolution, parse_resolution_pair

# 사용자 지정: "약 10 Step". 무료 상한(28)에 한참 못 미쳐 여유가 있다.
PREVIEW_STEPS = 10
# 사용자 지정: "Small 해상도 Spec". 가장 큰 칸도 768x512 = 393,216px 로 1MP 의 37% 다.
PREVIEW_PRESET = "small"
# V5 를 쓰던 중이어도 프리뷰는 4.5 로 나간다 — 그것이 할당량을 아끼는 지점이다.
PREVIEW_MODEL_KEY = "NAID4.5F"
PREVIEW_REQUEST_FLAG = "nai_preview_request"


class PreviewNotFree(RuntimeError):
    """무료로 나간다고 확신할 수 없어 프리뷰를 거부했다."""


def preview_resolution(context: Any) -> tuple[int, int]:
    """지금 설정의 **종횡비를 지킨 채** Small 밴드로 내린 치수.

    ⚠️ 고정 치수를 쓰면 안 된다 — 세로 그림을 보려는데 정사각 프리뷰가 나오면
       "실제 구조" 를 못 본다. 그것이 이 기능의 목적 전부다.
    """
    params = dict(getattr(context, "remote_params", {}) or {})
    width = _as_int(params.get("width"))
    height = _as_int(params.get("height"))
    if not (width and height):
        pair = parse_resolution_pair(params.get("resolution"))
        if pair:
            width, height = pair
    if not (width and height):
        width, height = 1024, 1024
    return nearest_nai_preset_resolution(width, height, PREVIEW_PRESET)


def build_preview_overrides(context: Any, request_id: str = "") -> dict[str, Any]:
    """지금 [Generate] 하면 나갈 것을 Small · 10스텝 · V4.5 로 낮춘 오버라이드.

    프롬프트·캐릭터 프롬프트·좌표는 **그대로 간다**(사용자 결정: 구조 확인이 목적).
    """
    width, height = preview_resolution(context)
    overrides: dict[str, Any] = {
        "model": PREVIEW_MODEL_KEY,
        "steps": PREVIEW_STEPS,
        "width": width,
        "height": height,
        "resolution": f"{width} x {height}",
        PREVIEW_REQUEST_FLAG: True,
        "nai_preview_request_id": str(request_id or ""),
        # 프리뷰가 Auto Gen 연쇄를 이어받으면 사용자가 시키지 않은 그림이 계속 나간다.
        "auto_generate": False,
        # 업스케일/인핸스는 유료 경로다. 프리뷰에는 뜻도 없다.
        "enable_hr": False,
    }
    seed = _as_int(getattr(context, "remote_params", {}).get("seed"), -1)
    fixed = _coerce_bool(context, getattr(context, "remote_params", {}).get("seed_fixed"))
    # 시드를 고정해 둔 사용자는 프리뷰도 같은 구도로 반복해서 보고 싶다.
    # 안 고정했으면 매번 새로 뽑는다 — Generate 와 같은 감각이다.
    overrides["seed"] = seed if (fixed and seed > 0) else -1
    return overrides


def assert_free(context: Any, overrides: dict[str, Any]) -> None:
    """무료로 나간다고 **확신할 수 있을 때만** 통과시킨다. 아니면 던진다.

    ⚠️ 이 문이 마지막이다. 위에서 치수를 잘못 계산해도, 누가 스텝 상수를 올려도,
       여기서 멈춘다. `is_free_generation` 은 모르면 유료로 눕는 fail-safe 다.
    """
    if not is_free_generation(context, overrides):
        width = overrides.get("width")
        height = overrides.get("height")
        steps = overrides.get("steps")
        raise PreviewNotFree(
            f"프리뷰가 무료 범위를 벗어납니다({width}x{height}, {steps} steps) — 생성하지 않았습니다."
        )


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _coerce_bool(context: Any, value: Any) -> bool:
    coerce = getattr(context, "_coerce_bool", None)
    if callable(coerce):
        return bool(coerce(value))
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)
