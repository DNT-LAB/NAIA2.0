# -*- coding: utf-8 -*-
"""캐릭터 '즉시 생성' — 히스토리의 캐릭터 하나를 그 자리에서 시험 삼아 뽑는다.

사용자 지정 2026-09-02:
    "girl, boy에 따라 메인 프롬프트에 1girl 또는 1boy를 넣고 사용자의 프롬프트
     엔지니어링 모듈 설정값과 파라미터를 읽어 즉시 생성합니다.
     생성 결과는 프롬프트 창에 띄우는데, 어떻게 띄우는지는 아티스트 탭의
     Generate 사양을 참고합니다."

## 무엇이 어디서 오는가

    메인 프롬프트   PE 모듈의 pre_prompt + **1girl|1boy** + post_prompt
    캐릭터          그 프레임의 prompt/uc 를 `characters`/`uc` 로 **직접** 싣는다
    파라미터        사용자의 현재 값 그대로 (모델·해상도·스텝·샘플러…)
    결과            **Results** (평소 생성과 같다 - 디스크·히스토리·Result 탭)
                    만든 메인 프롬프트는 **메인 프롬프트 창**에 적는다

## 왜 슬롯을 안 거치는가

예전 구현은 그 캐릭터를 **슬롯으로 복원한 뒤** 평소의 Generate 를 눌렀다. 그러면
(1) 메인 프롬프트가 화면에 있던 것 그대로 나가고, (2) 시험 삼아 눌렀을 뿐인데
캐릭터가 슬롯에 남는다. `characters` 를 직접 실으면 둘 다 없다 — Interactive 세션이
쓰는 길과 같다(`app.js applyInteractiveCharacterOverrides`).

⚠️ `_skip_character_late_binding` 이 **반드시** 함께 가야 한다. 없으면 캐릭터 모듈이
   자기 슬롯을 나중에 덮어써, 내가 실은 캐릭터 대신 사용자의 활성 슬롯이 나간다.

## 돈

사용자 파라미터로 나가므로 **무료가 아닐 수 있다**(무료 조건 = 28스텝 이하 · 1MP 이하).
그 판단은 사용자 것이다 - 여기서 모델이나 스텝을 낮추지 않는다. 다만 Vibe 는 끈다:
인코딩만으로 2 Anlas 인데다, 캐릭터 하나를 보려는 시험에 뜻이 없다.
"""

from __future__ import annotations

from typing import Any

INSTANT_REQUEST_FLAG = "character_instant_request"

# 주어 태그. 사용자 지정: "girl, boy에 따라".
SUBJECT_GIRL = "1girl"
SUBJECT_BOY = "1boy"

# ⚠️ **태그 전체**로 본다. 부분 문자열로 보면 `cowboy shot`(카메라 구도)이 boy 로,
#    `girl on top` 이 girl 로 잡혀 주어가 뒤집힌다 - 둘 다 흔한 태그다.
_BOY_TAGS = frozenset({
    "1boy", "boy", "male", "male focus", "solo focus male", "shota", "man",
})
_GIRL_TAGS = frozenset({
    "1girl", "girl", "female", "female focus", "woman",
})


def _tags(text: Any) -> list[str]:
    return [tag.strip().lower() for tag in str(text or "").split(",") if tag.strip()]


def detect_subject(prompt: Any) -> str:
    """캐릭터 프롬프트를 보고 `1girl` / `1boy` 중 하나를 고른다.

    ⚠️ 둘 다 있으면 **girl** 이다. 근거를 못 대는 추측 대신 기존 기본값을 지킨다 -
       NAIA 의 다른 자리들도 여자를 기본으로 둔다.
    """
    from core.character_settings import strip_connect_markers

    tags = set(_tags(strip_connect_markers(str(prompt or ''))))
    if tags & _BOY_TAGS and not (tags & _GIRL_TAGS):
        return SUBJECT_BOY
    return SUBJECT_GIRL


def _pe_settings(context: Any) -> dict[str, Any]:
    from core.prompt_engineering_settings import get_prompt_engineering_store

    store = get_prompt_engineering_store(context)
    state = store.state(context.get_api_mode())
    settings = state.get("settings") if isinstance(state, dict) else None
    return settings if isinstance(settings, dict) else {}


def build_instant_prompt(context: Any, frame: dict[str, Any]) -> str:
    """메인 프롬프트. PE 모듈의 선행/후행 사이에 주어 하나만 둔다.

    ⚠️ 캐릭터의 프롬프트는 **여기 넣지 않는다** - 캐릭터 칸으로 따로 간다. 메인에도
       넣으면 같은 태그가 두 번 실려 그 캐릭터가 화면을 뒤덮는다.
    """
    settings = _pe_settings(context)
    parts = [
        str(settings.get("pre_prompt") or "").strip(),
        detect_subject(frame.get("prompt")),
        str(settings.get("post_prompt") or "").strip(),
    ]
    return ", ".join(part for part in parts if part)


def build_instant_overrides(request_id: str, frame: dict[str, Any]) -> dict[str, Any]:
    """생성 요청에 얹을 것. **파라미터는 안 건드린다** - 사용자 현재 값 그대로 나간다.

    ⚠️ `uc` 는 `characters` 와 **길이가 같아야** 한다. 어긋나면
       `NAICharacterData` 가 거부한다(이제는 조용히 사라지지 않고 막힌다).
    """
    from core.character_settings import strip_connect_markers

    return {
        # ⚠️ `&connect: … &end` 를 걷는다(사용자 지정 2026-09-02). Connect 원본이면
        #    그 표식이 프롬프트에 **박혀 있다**(`_sync_connect_markers` 가 넣는다).
        #    혼자 나가는 시험 생성에는 물릴 상대가 없어 뜻이 없고, 그대로 실으면
        #    NAI 가 그것을 글자로 받는다.
        "characters": [strip_connect_markers(str(frame.get("prompt") or ""))],
        "uc": [str(frame.get("uc") or "")],
        # 캐릭터 모듈·레퍼런스가 나중에 자기 슬롯으로 덮어쓰지 못하게 막는다.
        "_skip_character_late_binding": True,
        "_skip_character_reference_late_binding": True,
        # Vibe 는 인코딩만으로 2 Anlas 다. 캐릭터 하나를 보려는 시험에 뜻이 없다.
        "_skip_vibe_transfer_late_binding": True,
        # 이 한 장으로 끝난다 - Auto Gen 연쇄를 이어받으면 시키지 않은 그림이 계속 나간다.
        "auto_generate": False,
        # ⚠️ 이 표식은 **결과를 빼돌리지 않는다**(사용자 제보: Results 에 남아야 한다).
        #    Auto Gen 연쇄와 Vibe 주입에서 빠지기 위한 것뿐이다.
        INSTANT_REQUEST_FLAG: True,
        "character_instant_request_id": str(request_id or ""),
    }
