"""NAI 모델 키 -> API 모델 문자열 · 페이로드 프로필 (경량 계약).

NAID5.0F / NAID5.0C 를 붙이면서 드러난 문제: 모델 판정이 코드 곳곳에
`"NAID4" in model_combo.currentText()` 같은 **부분문자열 검사**로 흩어져 있다.
`NAID5.0F` 에는 `NAID4` 가 없으므로 V5 는 그 검사를 전부 조용히 통과하지
못한다 - 캐릭터 프롬프트(char_captions)가 꺼진 채로 생성되는 식이다.

V5 실측(2026-08-19 웹 프론트 가로채기, future02 브랜치에서 라이브 4/4 검증):

  * `v5_prompt` 는 **없다**. V5 도 `v4_prompt` / `v4_negative_prompt` 를 그대로
    쓰고 `params_version` 도 그대로다. -> 캐릭터 프롬프트는 **켜야 한다**.
  * 전송이 바뀐다. V4 이하는 JSON 을 그대로 POST 하지만 V5 는
    `multipart/form-data` 의 `request` 파트 하나에 JSON Blob 으로 감싼다.
  * `skip_cfg_above_sigma` 는 웹 페이로드에 **키 자체가 없다**(기본값도 null).
  * Anlas 대신 별도 사용량 한도(0.5%/h 회복)를 쓴다. 무료 경계는 steps <= 28
    이고 1MP 이하. 잔량은 생성 응답이 아니라 구독 응답의 `usage` 로만 온다.

Vibe Transfer / Character Reference 는 스키마상 V5 에서도 열려 있지만
**NAIA 는 V5 요청에서 보내지 않는다**(사용자 지정). 라이브 검증이 없는 경로라
유료 요청이 조용히 실패하거나 무시되는 것보다 끄는 편이 낫다는 판단이다.

판정을 여기 한곳에 모아 호출부는 이름 있는 함수만 쓴다.
"""

from __future__ import annotations

from typing import Any


# 모르는 키가 들어왔을 때 되돌아갈 자리. **V5 로 두지 않는다** - V5 는 Anlas 가
# 아닌 별도 사용량 한도를 태우므로, 옛 프리셋의 오타 하나가 사용자가 고르지 않은
# 과금 풀로 새는 일이 없어야 한다.
DEFAULT_NAI_MODEL_KEY = "NAID4.5F"
DEFAULT_NAI_API_MODEL = "nai-diffusion-4-5-full"

# 콤보 박스에 뜨는 순서 그대로. 새 모델이 위로 온다.
NAI_MODEL_KEYS: tuple[str, ...] = (
    "NAID5.0F",
    "NAID5.0C",
    "NAID4.5F",
    "NAID4.5C",
    "NAID4.0F",
    "NAID4.0C",
    "NAID3",
)

NAI_MODEL_API_MAP: dict[str, str] = {
    "NAID5.0F": "nai-diffusion-5-full",
    "NAID5.0C": "nai-diffusion-5-curated",
    "NAID4.5F": "nai-diffusion-4-5-full",
    "NAID4.5C": "nai-diffusion-4-5-curated",
    "NAID4.0F": "nai-diffusion-4-full",
    "NAID4.0C": "nai-diffusion-4-curated-preview",
    "NAID3": "nai-diffusion-3",
}

# 인페인팅 wire 이름의 **예외표**. 규칙(`base + "-inpainting"`)으로 안 떨어지는 것만 적는다.
#
# ⚠️ `nai-diffusion-5-curated-inpainting` 은 **서버에 없다** - future02 라이브 실측에서
#    400(모델 없음)이 떴다. V5 Curated 인페인트는 Full 인페인팅을 **빌려 쓴다**
#    (사용자 결정: 세대(V5)를 지키고 Curated 성격을 포기). i2i 는 `nai-diffusion-5-curated`
#    로 정상이라 건드리지 않는다 - 여기 걸리는 것은 인페인트 액션뿐이다.
NAI_INPAINTING_API_MAP: dict[str, str] = {
    "nai-diffusion-5-curated": "nai-diffusion-5-full-inpainting",
    # NAID4.0C 는 베이스에만 `-preview` 가 붙는다. 규칙대로 이으면
    # `nai-diffusion-4-curated-preview-inpainting` 이 되는데 **그런 모델은 없다** -
    # 인페인팅 쪽 이름은 `-preview` 가 빠진 `nai-diffusion-4-curated-inpainting` 이다.
    # 옛 하드코딩 목록에도 후자가 적혀 있었지만 실제로 만들어 보내는 이름과 달라
    # 아무것도 못 잡고 있었다(선재 결함, ES2 에서 교정).
    "nai-diffusion-4-curated-preview": "nai-diffusion-4-curated-inpainting",
}

# `resolve_api_model()` 의 폴백. 모르는 키를 기본 모델로 되돌리는 기존 동작 유지.
_V5_API_PREFIX = "nai-diffusion-5"
_V4_API_PREFIXES = ("nai-diffusion-4", _V5_API_PREFIX)
_V45_API_PREFIX = "nai-diffusion-4-5"


def normalize_model_key(value: Any) -> str:
    """콤보 텍스트/파라미터 값에서 알려진 NAI 모델 키를 뽑는다.

    모듈들이 `currentText()` 를 파일명용으로 소독해 넘기기도 하므로 정확히
    같은지 대신 **포함** 으로 본다. 키끼리 서로의 부분문자열이 아니라 안전하다.
    모르는 값이면 빈 문자열 - 기본 모델로 되돌리지 **않는다**(잘못된 키가
    화면/판정에서 4.5 로 둔갑하는 것을 막는다).
    """
    text = str(value or "")
    if not text:
        return ""
    for key in NAI_MODEL_KEYS:
        if key in text:
            return key
    return ""


_API_MODEL_TO_KEY: dict[str, str] = {v: k for k, v in NAI_MODEL_API_MAP.items()}
_INPAINTING_SUFFIX = "-inpainting"


def resolve_api_model(model_key: Any) -> str:
    """UI 모델 키 -> 아웃바운드 API `model` 문자열. 모르면 기본 모델.

    ⚠️ **wire 이름이 그대로 들어오는 경로가 있다.** 화면에서 온 요청은 키(`NAID5.0F`)를
    싣지만, 메타데이터에서 되살린 파라미터(Enhance · 리플레이 · 외부 이미지 가져오기)는
    실제 API 이름(`nai-diffusion-5-full`)을 실을 수 있다. 그때 "아는 키가 아니다" 로
    기본값(V4.5 Full)에 떨어뜨리면 **V5 로 만든 그림을 Enhance 했는데 4.5 가 나오고
    아무도 그걸 알려주지 않는다** - 모델이 틀리면 전송 방식(multipart)까지 틀어진다.
    그래서 아는 wire 이름이면 그대로 인정한다(인페인팅 접미사가 붙어 있어도 벗겨서 본다).
    """
    text = str(model_key or "").strip()
    if text in NAI_MODEL_API_MAP:
        return NAI_MODEL_API_MAP[text]
    base = text[: -len(_INPAINTING_SUFFIX)] if text.endswith(_INPAINTING_SUFFIX) else text
    if base in _API_MODEL_TO_KEY:
        return base
    return DEFAULT_NAI_API_MODEL


def inpainting_api_model(value: Any) -> str:
    """인페인트 액션에 쓸 wire 이름. 기본 규칙은 `base + "-inpainting"`.

    예외는 `NAI_INPAINTING_API_MAP` 이 가진다 - V5 Curated 는 전용 인페인팅 모델이
    없어 Full 인페인팅을 빌려 쓴다.
    """
    base = _api_model_of(value)
    if not base:
        return ""
    if base.endswith(_INPAINTING_SUFFIX):
        return base
    return NAI_INPAINTING_API_MAP.get(base, base + _INPAINTING_SUFFIX)


def _api_model_of(value: Any) -> str:
    """키든 API 문자열이든 받아서 API 문자열로 맞춘다."""
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("nai-diffusion-"):
        return text
    key = normalize_model_key(text)
    return NAI_MODEL_API_MAP.get(key, "")


def is_v5_model(value: Any) -> bool:
    """NAI Diffusion V5 인가. 인페인팅 접미사가 붙은 이름도 함께 잡는다."""
    return _api_model_of(value).startswith(_V5_API_PREFIX)


def uses_v4_prompt_payload(value: Any) -> bool:
    """`v4_prompt` / `v4_negative_prompt` 구조를 쓰는가.

    V4 · V4.5 · **V5** 가 여기 해당한다. 캐릭터 프롬프트(char_captions)를
    켜는 판정도 이것을 쓴다 - `"NAID4" in text` 로는 V5 가 빠진다.
    """
    return _api_model_of(value).startswith(_V4_API_PREFIXES)


def uses_multipart_request(value: Any) -> bool:
    """V5 는 JSON 을 그대로 POST 하지 않는다.

    `multipart/form-data` 의 `request` 파트에 JSON Blob 으로 감싸 보낸다.
    이때 `Content-Type` 을 직접 넣으면 안 된다 - boundary 는 requests 가
    만들어야 하고, 직접 넣은 헤더가 이기면 서버가 파싱에 실패한다.
    """
    return is_v5_model(value)


def uses_opus_usage_limit(value: Any) -> bool:
    """Anlas 가 아닌 별도 사용량 한도를 쓰는 모델인가."""
    return is_v5_model(value)


def skip_cfg_above_sigma_for(value: Any) -> int | None:
    """VAR+ 켰을 때 넣을 `skip_cfg_above_sigma`. V5 는 넣지 않는다(None)."""
    api_model = _api_model_of(value)
    if not api_model or api_model.startswith(_V5_API_PREFIX):
        return None
    if api_model.startswith(_V45_API_PREFIX):
        return 58
    return 19


def supports_vibe_transfer(value: Any) -> bool:
    """Vibe Transfer 를 요청에 실을 수 있는 모델인가.

    V5 는 **끈다**(사용자 지정). 그 외 NAI 모델은 기존대로 허용 - NAID3 은
    `reference_information_extracted_multiple` 까지 함께 쓴다.
    """
    return not is_v5_model(value)


def supports_character_reference(value: Any) -> bool:
    """Character Reference(Director Tool)를 실을 수 있는 모델인가.

    기존대로 V4.5 전용이고, V5 는 **끈다**(사용자 지정).
    """
    return _api_model_of(value).startswith(_V45_API_PREFIX)
