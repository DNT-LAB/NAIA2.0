# -*- coding: utf-8 -*-
"""V4.5 프리뷰 설정 — 톱니 메뉴가 만지는 값들의 SSOT.

사용자 SPEC 2026-09-01. 기본값과 범위를 여기 한 곳에 둔다.

## ⚠️ 모든 조합이 무료 범위 안이어야 한다

이 설정으로 만든 요청은 `core.nai_preview_service.assert_free` 를 통과해야 나간다.
그래서 범위를 여기서 미리 좁혀 둔다 — 사용자가 어떤 조합을 골라도 돈이 안 나가게:

    steps      <= 28          (무료 한계와 **같다**. `is_free_generation` 은 `<=` 다)
    해상도      <= 1024x1024   (= 1,048,576px = 무료 한계와 **정확히 같다**)

Standard 밴드의 가장 큰 칸이 1024x1024 라 경계에 닿지만 넘지 않는다. 직접 선택도
640~1024 안에서만 고르므로 최대 면적이 같다. 그래도 마지막 문(`assert_free`)은
그대로 둔다 — 여기 숫자를 누가 바꿔도 거기서 걸린다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ── 사용자 SPEC 의 기본값 ────────────────────────────────────────────────
DEFAULT_PREFIX = "0.5::epi zero ::"
DEFAULT_POSTFIX = (
    "aesthetic, absurdres, amazing quality, masterpiece, year 2024, year 2023"
)
DEFAULT_NEGATIVE = (
    "lowres, worst quality, jpeg artifacts, blurry, watermark, signature, text, "
    "bad anatomy, bad hands, extra digits, scenery, detailed background, muted color, "
    "gradient background, sparkle, border, multiple views, cropped"
)

RESOLUTION_MODES = ("custom", "small", "standard")
SAMPLERS = (
    "k_dpmpp_2m", "k_dpmpp_2m_sde", "k_dpmpp_sde", "k_dpmpp_2s_ancestral",
    "k_euler", "k_euler_ancestral", "k_dpm_fast", "ddim_v3",
)
SCHEDULERS = ("native", "karras", "exponential", "polyexponential")

# 범위. ⚠️ 상한이 곧 무료 경계다 - 올리면 돈이 나간다.
STEPS_MIN, STEPS_MAX, STEPS_DEFAULT = 1, 28, 14
CFG_MIN, CFG_MAX, CFG_DEFAULT = 1.0, 7.0, 4.0
RESCALE_MIN, RESCALE_MAX, RESCALE_DEFAULT = -0.2, 1.0, 0.1
CUSTOM_EDGE_MIN, CUSTOM_EDGE_MAX = 640, 1024

PREVIEW_SETTINGS_FILE = "nai_preview_settings.json"

DEFAULTS: dict[str, Any] = {
    # 토글 — 기본값은 사용자 SPEC 그대로다.
    "on_random": False,          # 랜덤 버튼이 작동할 때 V4.5 생성을 요청
    "send_character": True,      # 캐릭터 프롬프트를 함께 보냄
    "alt_p_hotkey": True,        # ALT+P 로 요청
    # 해상도
    "resolution_mode": "standard",
    "custom_width": 832,
    "custom_height": 1216,
    # 생성 파라미터
    "sampler": "k_dpmpp_2m",
    "scheduler": "karras",
    "steps": STEPS_DEFAULT,
    "cfg_scale": CFG_DEFAULT,
    "cfg_rescale": RESCALE_DEFAULT,
    "var_plus": False,           # VAR+
    "decrisp": False,            # DECRISP
    # 프롬프트
    "prefix": DEFAULT_PREFIX,
    "postfix": DEFAULT_POSTFIX,
    "negative": DEFAULT_NEGATIVE,
}


def custom_resolution_candidates() -> tuple[tuple[int, int], ...]:
    """직접 선택에서 고를 수 있는 칸 — 640~1024 의 64 배수 조합.

    ⚠️ 64 배수만 낸다. NAI 가 그 밖의 치수를 받아도 결과가 어긋난다(앱의 다른 경로도
       전부 64 로 스냅한다).
    """
    edges = tuple(range(CUSTOM_EDGE_MIN, CUSTOM_EDGE_MAX + 1, 64))
    return tuple((w, h) for w in edges for h in edges)


def _clamp_float(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _clamp_int(value: Any, low: int, high: int, default: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _snap_edge(value: Any, default: int) -> int:
    """64 배수로 스냅한 뒤 640~1024 로 가둔다."""
    number = _clamp_int(value, CUSTOM_EDGE_MIN, CUSTOM_EDGE_MAX, default)
    snapped = int(round(number / 64.0)) * 64
    return max(CUSTOM_EDGE_MIN, min(CUSTOM_EDGE_MAX, snapped))


def normalize(raw: Any) -> dict[str, Any]:
    """어떤 입력이 와도 **무료 범위 안의** 온전한 설정으로 만든다.

    ⚠️ 모르는 값은 기본값으로 눕는다. 사용자가 손으로 파일을 고쳐 steps 를 50 으로
       적어도 28 로 잘린다 - 그래야 돈이 안 나간다.
    """
    data = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULTS)

    for key in ("on_random", "send_character", "alt_p_hotkey", "var_plus", "decrisp"):
        if key in data:
            out[key] = _coerce_bool(data.get(key))

    mode = str(data.get("resolution_mode") or "").strip().lower()
    if mode in RESOLUTION_MODES:
        out["resolution_mode"] = mode
    out["custom_width"] = _snap_edge(data.get("custom_width"), DEFAULTS["custom_width"])
    out["custom_height"] = _snap_edge(data.get("custom_height"), DEFAULTS["custom_height"])

    sampler = str(data.get("sampler") or "").strip()
    if sampler in SAMPLERS:
        out["sampler"] = sampler
    scheduler = str(data.get("scheduler") or "").strip().lower()
    if scheduler in SCHEDULERS:
        out["scheduler"] = scheduler

    out["steps"] = _clamp_int(data.get("steps"), STEPS_MIN, STEPS_MAX, STEPS_DEFAULT)
    out["cfg_scale"] = round(_clamp_float(data.get("cfg_scale"), CFG_MIN, CFG_MAX, CFG_DEFAULT), 2)
    out["cfg_rescale"] = round(
        _clamp_float(data.get("cfg_rescale"), RESCALE_MIN, RESCALE_MAX, RESCALE_DEFAULT), 2)

    for key in ("prefix", "postfix", "negative"):
        if key in data:
            out[key] = str(data.get(key) or "").strip()
    return out


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def load(save_root: str | Path | None = None) -> dict[str, Any]:
    from core.prompt_engineering_settings import _existing_save_file

    path = _existing_save_file(PREVIEW_SETTINGS_FILE, save_root)
    try:
        return normalize(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return dict(DEFAULTS)


def save(settings: dict[str, Any], save_root: str | Path | None = None) -> dict[str, Any]:
    from core.prompt_engineering_settings import _coerce_save_root

    normalized = normalize(settings)
    path = _coerce_save_root(save_root) / PREVIEW_SETTINGS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized
