"""NovelAI UI model keys, outbound API names, and payload compatibility.

NovelAI의 새 모델은 UI용 짧은 키와 실제 API ``model`` 문자열이 서로 다르다.
또한 wire 이름만 보고 ``"nai-diffusion-4" in model``처럼 payload 기능을
추측하면, 이름이 달라질 NAID5를 V3 경로로 오분류할 수 있다. 모델 식별과
payload 호환 프로필을 한 계약으로 묶어 모든 NAI 호출 경로가 공유한다.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Mapping


DEFAULT_NAI_MODEL_KEY = "NAID4.5F"
DEFAULT_NAI_API_MODEL = "nai-diffusion-4-5-full"

NAI_PAYLOAD_PROFILES = frozenset({"v3", "v4", "v4.5", "v5", "passthrough"})


@dataclass(frozen=True)
class NaiModelSpec:
    """A selectable NAI model and the compatibility rules NAIA must apply."""

    key: str
    label: str
    api_model: str
    payload_profile: str
    inpainting_api_model: str | None = None
    # 위 인페인팅 모델이 **이 모델 자신의 것이 아니라 빌려 쓰는 것**인가.
    #
    # ⚠️ 메타데이터 -> 모델 되찾기(`nai_key_from_metadata`)가 인페인팅 wire 이름도
    #    보고 모델을 고른다. 빌려 쓰는 이름까지 자기 것처럼 등록하면 **두 스펙이
    #    같은 이름을 들어** 먼저 걸린 쪽으로 잘못 귀속된다(실측: V5 인페인트로 만든
    #    그림이 Curated 로 되찾아졌다). 그래서 빌린 것은 되찾기에서 뺀다.
    inpainting_is_substitute: bool = False
    family: str = ""
    source: str = "builtin"
    selectable: bool = True
    api_parameter_overrides: Mapping[str, Any] = field(default_factory=dict)
    api_parameter_removals: tuple[str, ...] = ()

    @property
    def uses_v4_payload(self) -> bool:
        # V5도 `v4_prompt`/`v4_negative_prompt` 를 **그대로** 쓴다 — 웹 번들에
        # `v5_prompt` 는 존재하지 않고 `params_version` 도 4 그대로다(2026-08-19 실측).
        return self.payload_profile in {"v4", "v4.5", "v5"}

    @property
    def supports_vibe(self) -> bool:
        """Vibe Transfer 를 쓸 수 있는 모델인가.

        ⚠️ **V5 는 뺀다**(사용자 지시 2026-08-21, v2.0.34 최초 설치 테스트 후).
        페이로드 구조가 같아 스키마상 필드는 남아 있지만 **V5 가 실제로 받는지
        확인된 바가 없다**. 열어 두면 사용자가 Vibe 를 켜고 생성 -> Anlas 를 태우고
        실패한다. 게다가 Vibe **인코딩**은 그 자체로 Anlas 를 쓴다(2 Anlas).

        `uses_v4_payload` 에서 파생시키면 안 된다 - V5 는 `v4_prompt` 를 그대로 쓰므로
        그 property 는 V5 에서도 True 다. 둘은 다른 질문이다.
        """
        return self.payload_profile in {"v4", "v4.5"}

    @property
    def supports_character_reference(self) -> bool:
        """Character Reference 를 쓸 수 있는 모델인가.

        ⚠️ V5 는 뺀다 - 위 `supports_vibe` 와 같은 이유(스키마엔 있으나 라이브 미검증).
        """
        return self.payload_profile == "v4.5"

    @property
    def uses_legacy_smea(self) -> bool:
        return self.payload_profile == "v3"

    @property
    def uses_multipart_request(self) -> bool:
        """V5는 JSON 을 그대로 POST 하지 않는다.

        `multipart/form-data` 의 **`request` 파트에 JSON Blob** 으로 감싸 보낸다
        (2026-08-19 웹 프론트 실측). 이 래핑을 안 맞추면 요청 자체가 성립하지 않는다.
        """
        return self.payload_profile == "v5"

    @property
    def uses_opus_usage_limit(self) -> bool:
        """Anlas 가 아닌 **별도 사용량 한도**(0.5%/h 회복)를 쓰는 모델인가.

        잔량은 `GET /user/subscription` 의 `usage` 로만 오고 생성 응답에는 없다.
        """
        return self.payload_profile == "v5"

    @property
    def skip_cfg_above_sigma(self) -> int | None:
        if self.payload_profile == "v4.5":
            return 58
        if self.payload_profile in {"v3", "v4"}:
            return 19
        # V5: 웹이 보내는 페이로드에 이 키가 아예 없다(기본값도 null) — 넣지 않는다.
        return None

    def to_payload(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "api_model": self.api_model,
            "payload_profile": self.payload_profile,
            "inpainting_api_model": self.inpainting_api_model,
            "family": self.family,
            "source": self.source,
            "selectable": self.selectable,
            "api_parameter_overrides": copy.deepcopy(dict(self.api_parameter_overrides)),
            "api_parameter_removals": list(self.api_parameter_removals),
            "capabilities": {
                "v4_payload": self.uses_v4_payload,
                "vibe": self.supports_vibe,
                "character_reference": self.supports_character_reference,
                "legacy_smea": self.uses_legacy_smea,
                "inpainting": bool(self.inpainting_api_model),
            },
        }


def _builtin(
    key: str,
    label: str,
    api_model: str,
    payload_profile: str,
    *,
    inpainting_api_model: str | None,
    family: str,
    selectable: bool = True,
    inpainting_is_substitute: bool = False,
) -> NaiModelSpec:
    return NaiModelSpec(
        key=key,
        label=label,
        api_model=api_model,
        payload_profile=payload_profile,
        inpainting_api_model=inpainting_api_model,
        inpainting_is_substitute=inpainting_is_substitute,
        family=family,
        source="builtin",
        selectable=selectable,
    )


# 숨은 F/C canonical key도 메타데이터/프리셋 복원에서 사용하므로 resolver에는 유지한다.
BUILTIN_NAI_MODEL_SPECS: dict[str, NaiModelSpec] = {
    # V5 (2026-08 출시). 키에 점을 쓰지 않는다 — 마이너 버전이 없다(사용자 지정).
    # 모델 문자열은 **웹 번들에서만** 얻을 수 있다: OpenAPI 의 `model` 은 enum 이
    # 아니라 자유 문자열이라 문서에는 목록이 없다.
    "NAID5F": _builtin(
        "NAID5F",
        "NovelAI Diffusion V5 Full",
        "nai-diffusion-5-full",
        "v5",
        inpainting_api_model="nai-diffusion-5-full-inpainting",
        family="v5",
    ),
    "NAID5C": _builtin(
        "NAID5C",
        "NovelAI Diffusion V5 Curated",
        "nai-diffusion-5-curated",
        "v5",
        # ⚠️ **Curated 전용 인페인팅 모델은 없다**(라이브 실측 2026-08-23:
        # `nai-diffusion-5-curated-inpainting` -> 400 "model doesn't exist").
        # Full 쪽 인페인팅으로 보낸다 - 세대(V5)를 지키고 Curated 성격만 포기하는
        # 쪽을 사용자가 골랐다. i2i 는 `nai-diffusion-5-curated` 로 정상 동작한다
        # (200 확인) - 그래서 여기만 갈아 끼우면 된다.
        #
        # ⚠️ **이건 결함이 아니라 결정이다. 되돌리지 마라.**(사용자 재확인 2026-08-25)
        # 정적 리뷰가 "사용자가 안 고른 모델로 유료 호출된다" 며 주기적으로 이 자리를
        # 올린다. 근거는 이렇다: **공식 홈페이지는 이 경우 V4.5 로 리다이렉트한다.**
        # 즉 선택지는 '세대를 지키고 Curated 성격을 포기'(지금) 대 '세대까지 포기'
        # 둘뿐이고, 사용자는 앞을 골랐다. 다음에 이 자리를 다시 의심하게 되면
        # 고치기 전에 이 줄부터 읽어라.
        inpainting_api_model="nai-diffusion-5-full-inpainting",
        inpainting_is_substitute=True,      # 빌려 쓴다 - 되찾기에서는 뺀다
        family="v5",
    ),
    "NAID4.5F": _builtin(
        "NAID4.5F",
        "NovelAI Diffusion V4.5 Full",
        "nai-diffusion-4-5-full",
        "v4.5",
        inpainting_api_model="nai-diffusion-4-5-full-inpainting",
        family="v4.5",
    ),
    "NAID4.5C": _builtin(
        "NAID4.5C",
        "NovelAI Diffusion V4.5 Curated",
        "nai-diffusion-4-5-curated",
        "v4.5",
        inpainting_api_model="nai-diffusion-4-5-curated-inpainting",
        family="v4.5",
        selectable=False,
    ),
    "NAID4.5": _builtin(
        "NAID4.5",
        "NovelAI Diffusion V4.5",
        "nai-diffusion-4-5-full",
        "v4.5",
        inpainting_api_model="nai-diffusion-4-5-full-inpainting",
        family="v4.5",
    ),
    "NAID4.0F": _builtin(
        "NAID4.0F",
        "NovelAI Diffusion V4 Full",
        "nai-diffusion-4-full",
        "v4",
        inpainting_api_model="nai-diffusion-4-full-inpainting",
        family="v4.0",
        selectable=False,
    ),
    "NAID4.0C": _builtin(
        "NAID4.0C",
        "NovelAI Diffusion V4 Curated",
        "nai-diffusion-4-curated-preview",
        "v4",
        inpainting_api_model="nai-diffusion-4-curated-inpainting",
        family="v4.0",
        selectable=False,
    ),
    "NAID4": _builtin(
        "NAID4",
        "NovelAI Diffusion V4",
        "nai-diffusion-4-full",
        "v4",
        inpainting_api_model="nai-diffusion-4-full-inpainting",
        family="v4.0",
    ),
    "NAID3": _builtin(
        "NAID3",
        "NovelAI Diffusion V3",
        "nai-diffusion-3",
        "v3",
        inpainting_api_model="nai-diffusion-3-inpainting",
        family="v3",
    ),
}

DEFAULT_NAI_MODEL_SPEC = BUILTIN_NAI_MODEL_SPECS[DEFAULT_NAI_MODEL_KEY]
NAI_REMOTE_MODEL_KEYS = tuple(
    spec.key for spec in BUILTIN_NAI_MODEL_SPECS.values() if spec.selectable
)

# Backward-compatible public mapping used by existing tests and callers.
NAI_API_MODEL_BY_KEY = {
    key: spec.api_model for key, spec in BUILTIN_NAI_MODEL_SPECS.items()
}


# ---- img2img 계열 대체 모델 --------------------------------------------------
#
# **지금은 비어 있다.** 2026-08-21 에는 "V5 가 인페인트/img2img 를 아직 제공하지
# 않는다" 는 전제로 V5 -> V4.5 대체를 넣었는데, **그 전제가 뒤집혔다**(사용자 확인
# 2026-08-23: V5 전용 인페인팅 모델이 따로 있고 공식 사이트는 i2i 도 된다고 한다).
# 대체를 걷어내면 V5 를 고른 사용자가 인페인트/i2i 에서도 V5 를 그대로 쓴다.
#
# 표를 지우지 않고 비워 두는 이유: 앞으로도 "이 모델은 이 액션을 못 한다" 는 경우가
# 생길 수 있고, 그때 다시 배선하는 것보다 여기 한 줄을 더하는 편이 안전하다.
#
# ⚠️ 대체가 일어나도 **파라미터 규칙은 사용자가 고른 모델 것을 쓴다**(의도된 계약,
# `test_custom_model_without_inpaint_wire_falls_back_to_naid45_full`). 대체 후 스펙을
# 따르는 것은 payload capability 와 전송 방식(`uses_multipart_request`)뿐이다 -
# 그건 서버가 받아들이는 모양의 문제라 실제로 나갈 모델을 따라야 한다.
#
# Upscale 은 여기 없다 - `/ai/upscale` 은 모델을 안 받는다(그래서 V5 에서도 그냥 된다).
NAI_IMG2IMG_FALLBACK_KEYS: dict[str, str] = {}


def nai_img2img_fallback_key(model_key: Any) -> str:
    """img2img/인페인트/Enhance 에서 대신 쓸 모델 키. 대체가 필요 없으면 빈 문자열."""
    return NAI_IMG2IMG_FALLBACK_KEYS.get(normalize_nai_model_key(model_key), "")


# ---- 샘플러 -----------------------------------------------------------------
#
# NAI 공식 UI 가 내놓는 순서 그대로다(2026-08-21 사용자 제보 화면 기준):
#     Euler Ancestral(권장) · Euler · DPM++ 2S Ancestral · DPM++ 2M SDE ·
#     DPM++ 2M · DPM++ SDE
# 여기에 NAIA 가 예전부터 제공하던 `ddim`(V3 계열)을 뒤에 붙인다.
#
# ⚠️ **목록이 세 곳에 복제돼 있었다** - 여기(백엔드) 말고 프런트의
# `characterCreationBench.mjs` / `characterAssetTab.mjs` 에도 같은 배열이 있다.
# 그래서 넷만 있는 채로 오래 방치됐다(사용자: "2M SDE 는 빠져있네요?").
# `tests/test_nai_sampler_options.py` 가 세 목록이 어긋나면 잡는다.
#
# ⚠️ Swagger 로는 확인이 안 된다 - NAI OpenAPI 는 스키마가 3개뿐이고 샘플러를
# 열거하지 않는다(실측: `euler` 문자열조차 없음). 이름의 근거는 공식 UI 와
# `api_service` 가 예전부터 갖고 있던 검증 목록이다.
NAI_SAMPLER_OPTIONS: tuple[str, ...] = (
    "k_euler_ancestral",
    "k_euler",
    "k_dpmpp_2s_ancestral",
    "k_dpmpp_2m_sde",
    "k_dpmpp_2m",
    "k_dpmpp_sde",
    "ddim",
)

# 메타데이터/자동수정 경로가 받아들이는 값. UI 가 낼 수 있는 것 전부 + V3 의 옛 이름.
NAI_VALID_SAMPLERS: frozenset[str] = frozenset(NAI_SAMPLER_OPTIONS) | {"ddim_v3"}


# ---- 프리셋 목록에 붙는 모델 배지 -------------------------------------------
#
# Quick Preset 목록에서 프리셋 이름 앞에 `[NAI4.5C]` 처럼 붙는 짧은 라벨과, 그 위
# 필터 바(ALL / NAI5 / NAI4.5 / ETC)가 쓰는 분류. **키 문자열을 잘라 만들지 않는다** -
# `NAID4.5` 처럼 접미사가 없는 키가 있어 규칙이 한 줄로 안 떨어진다.
NAI_MODEL_SHORT_LABELS: dict[str, str] = {
    "NAID5F": "NAI5.0F",
    "NAID5C": "NAI5.0C",
    "NAID4.5F": "NAI4.5F",
    "NAID4.5C": "NAI4.5C",
    "NAID4.5": "NAI4.5",
    "NAID4.0F": "NAI4.0F",
    "NAID4.0C": "NAI4.0C",
    "NAID4": "NAI4.0",
    "NAID3": "NAI3.0",
}

# 필터 바의 갈래. 4.0 과 3.0 은 ETC 로 묶는다(사용자 지정 2026-08-21).
NAI_PRESET_FILTER_GROUPS: tuple[tuple[str, str], ...] = (
    ("all", "ALL"),
    ("v5", "NAI5"),
    ("v4.5", "NAI4.5"),
    ("etc", "ETC"),
)


def nai_model_badge(model_key: Any, context: Any = None) -> dict[str, str]:
    """프리셋 배지 정보. 모델을 모르면 라벨 없이 ETC 로 보낸다.

    반환: `{"key", "label", "family", "group"}`.
    `family` 는 색을 정하고(v5=루비 / v4.5=연노랑 / v4.0=연두 / v3=하늘),
    `group` 은 필터 바가 쓴다.
    """
    key = normalize_nai_model_key(model_key)
    if not key:
        # 모델을 안 적고 저장된 옛 프리셋. 숨기면 ALL 에만 보이고 다른 갈래에서
        # 사라져 "프리셋이 없어졌다" 가 된다 - ETC 에 넣어 어디서든 닿게 한다.
        return {"key": "", "label": "", "family": "", "group": "etc", "variant": ""}
    # ⚠️ **여기서는 `resolve_*` 의 폴백을 쓰면 안 된다.** 모르는 키를 기본 모델
    # (NAID4.5F)로 되돌려 주므로, 옛 프리셋의 오타 하나가 화면에 `NAI4.5` 배지로
    # 둔갑한다 - 배지는 "저장된 것"을 보여야지 "대신 쓸 것"을 보이면 안 된다.
    spec = BUILTIN_NAI_MODEL_SPECS.get(key)
    if spec is None and context is not None:
        getter = getattr(context, "_nai_model_registry", None)
        if callable(getter):
            try:
                custom = getter().resolve(key)
                # 레지스트리도 모르는 키는 기본값을 줄 수 있다 - 키가 같을 때만 믿는다.
                if normalize_nai_model_key(getattr(custom, "key", "")) == key:
                    spec = custom
            except Exception:
                spec = None
    if spec is None:
        return {"key": key, "label": key, "family": "", "group": "etc", "variant": ""}
    family = str(spec.family or "")
    group = family if family in {"v5", "v4.5"} else "etc"
    # 사용자 등록 모델은 짧은 라벨이 없다 - 키를 그대로 쓴다.
    label = NAI_MODEL_SHORT_LABELS.get(key, key)
    return {"key": key, "label": label, "family": family, "group": group,
            "variant": nai_model_variant(spec)}


def nai_model_variant(spec: Any) -> str:
    """Full / Curated 판정. 화면이 같은 세대 안에서 둘을 색으로 가른다.

    ⚠️ **키나 짧은 라벨의 끝 글자로 자르지 않는다.** `NAID4.5` 처럼 접미사가 없는
    키가 있고, 사용자 등록 모델은 이름을 마음대로 짓는다. 실제 구분은 API 모델
    이름에 있다(`nai-diffusion-5-full` / `nai-diffusion-5-curated`).
    """
    api_model = str(getattr(spec, "api_model", "") or "").lower()
    if "curated" in api_model:
        return "curated"
    if "full" in api_model:
        return "full"
    return ""


def normalize_nai_model_key(value: Any) -> str:
    return str(value or "").strip().upper()


def resolve_nai_model_spec(
    model_key: Any,
    custom_models: Mapping[str, NaiModelSpec] | None = None,
) -> NaiModelSpec:
    """Resolve a model spec, preserving the established unknown-key fallback."""

    normalized = normalize_nai_model_key(model_key)
    if custom_models:
        custom = custom_models.get(normalized)
        if isinstance(custom, NaiModelSpec):
            return custom
    return BUILTIN_NAI_MODEL_SPECS.get(normalized, DEFAULT_NAI_MODEL_SPEC)


def resolve_nai_model_for_context(context: Any, model_key: Any) -> NaiModelSpec:
    """Resolve through the runtime custom registry when the context provides it."""

    getter = getattr(context, "_nai_model_registry", None)
    if callable(getter):
        # The runtime registry resolves strictly. A stale/deleted/typoed custom key
        # must stop before a paid request rather than silently spending on 4.5 Full.
        return getter().resolve(model_key)
    return resolve_nai_model_spec(model_key)


# NAI 가 PNG `Source`/`Comment.model_hash` 에 남기는 모델 해시 -> 키.
# ⚠️ V4 는 Full/Curated 의 **표시 라벨이 같다**(`NovelAI Diffusion V4`) - 해시가
# 유일한 구분자다. 실측으로 확인된 것만 넣는다.
NAI_SOURCE_HASHES: dict[str, str] = {
    "0ADF9AB7": "NAID5F",      # 실측 2026-08-22 (사용자 V5 Full 생성물)
    "4BDE2A90": "NAID4.5F",
    "C02D4F98": "NAID4.5C",
    "7ABFFA2A": "NAID4.0C",
    "37442FCA": "NAID4.0F",
}

# 맨 계열 이름만 있을 때의 기본값. NAI 는 `Comment.model_name` 에 Full/Curated 를
# 안 붙인다(실측: `"NovelAI Diffusion V5"`). 긴 이름부터 봐야 V4 가 V4.5 를 안 삼킨다.
NAI_FAMILY_DEFAULT_KEYS: dict[str, str] = {
    "novelai diffusion v5": "NAID5F",
    "novelai diffusion v4.5": "NAID4.5F",
    "novelai diffusion v4": "NAID4.0F",
    "novelai diffusion v3": "NAID3",
}


def nai_key_from_display_name(value: Any) -> str:
    """**사람에게 보이는 이름**일 때만 canonical 키로 되돌린다. 아니면 "".

    맞춰 보는 것은 canonical 키 · 표시 라벨 · 계열 이름뿐이다. **wire 이름은 뺀다.**

    ⚠️ 그 구분이 이 함수의 존재 이유다. 커스텀 모델 키 문법은
       `^[A-Z0-9][A-Z0-9._-]{0,39}$` 라 **공백을 못 쓴다.** 라벨(`NovelAI Diffusion
       V5 Full`)과 계열 이름(`novelai diffusion v5`)은 공백이 있으니 커스텀 키가
       **될 수 없고**, 그래서 이 번역은 남의 키를 삼킬 수가 없다. 반면 wire 이름
       (`nai-diffusion-5-full`)은 공백이 없어 **그대로 커스텀 키가 된다** - 사용자가
       고른 자기 모델이 빌트인으로 둔갑해 다른 모델에 돈이 나간다(Codex 리뷰 BLOCK).

    그래서 사용자 **선택**을 다루는 자리(파라미터 목·시작 시 치유)는 이 함수를 쓰고,
    메타데이터에서 온 값을 다루는 자리만 `nai_key_from_exact_name` 을 쓴다.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    upper = text.upper()
    if upper in BUILTIN_NAI_MODEL_SPECS:
        return upper
    lowered = text.lower()
    for spec in BUILTIN_NAI_MODEL_SPECS.values():
        if spec.label and spec.label.lower() == lowered:
            return spec.key
    return NAI_FAMILY_DEFAULT_KEYS.get(lowered, "")


def nai_key_from_exact_name(value: Any) -> str:
    """전체 문자열이 **정확히** 아는 이름일 때만 canonical 키로 되돌린다. 아니면 "".

    ⚠️ **이 자리에 `nai_key_from_metadata` 를 쓰면 안 된다.** 그건 PNG 메타데이터
       한 덩이 안에서 모델 이름을 **찾아내는** 함수라 부분 문자열로 맞춘다. 그래서
       사용자가 등록할 수 있는 커스텀 키 `MY-NAI-DIFFUSION-5-FULL` 이 `NAID5F` 로
       둔갑했다 - 그 모델을 지운 뒤에도 생성이 막히지 않고 **다른 모델로 돈이 나간다**
       (Codex 리뷰 BLOCK, 재현됨). 사용자가 고른 모델을 바꾸는 판단은 **정확히 아는
       이름일 때만** 해야 한다.

    맞춰 보는 것: canonical 키 · wire 이름(제 인페인팅 이름 포함) · 표시 라벨 ·
    계열 이름(`NovelAI Diffusion V5` - NAI 가 PNG 에 실제로 쓰는 형태다).
    """
    text = str(value or "").strip()
    if not text:
        return ""
    upper = text.upper()
    if upper in BUILTIN_NAI_MODEL_SPECS:
        return upper
    lowered = text.lower()
    for spec in BUILTIN_NAI_MODEL_SPECS.values():
        names = [spec.api_model, spec.label]
        # ⚠️ 빌려 쓰는 인페인팅 이름은 뺀다 - 두 스펙이 같은 이름을 들어 먼저 걸린
        #    쪽으로 잘못 귀속된다(`nai_key_from_metadata` 와 같은 이유).
        if spec.inpainting_api_model and not spec.inpainting_is_substitute:
            names.append(spec.inpainting_api_model)
        if any(name and name.lower() == lowered for name in names):
            return spec.key
    return NAI_FAMILY_DEFAULT_KEYS.get(lowered, "")


def nai_key_from_metadata(model_value: Any = "", source_value: Any = "") -> str:
    """NAI 생성물의 메타데이터에서 **모델 키**를 되찾는다. 못 찾으면 빈 문자열.

    NAI 가 PNG 에 남기는 것(실측, V5 생성물 2026-08-22):
        Source              "NovelAI Diffusion V5 0ADF9AB7"     (라벨 + 해시)
        Comment.model_name  "NovelAI Diffusion V5"              (라벨만)
        Comment.model_hash  "0ADF9AB7"
    그리고 요청 페이로드의 `model` 은 와이어 이름("nai-diffusion-5-full")이다.
    셋 다 여기서 받는다.

    ⚠️ **표를 손으로 유지하지 않는다.** 예전에는 `_NAI_SOURCE_MODELS` 와 `wire_map`
    두 개를 하드코딩해 뒀는데 V5 를 추가할 때 **둘 다 안 고쳤다.** 그래서 V5 이미지의
    메타데이터를 읽으면 라벨이 그대로 키 자리로 흘러가
    `등록되지 않은 NAI 모델 키입니다: NOVELAI DIFFUSION V5` 로 생성이 막혔다
    (사용자 제보 2026-08-22). `BUILTIN_NAI_MODEL_SPECS` 에서 파생하면 새 모델이
    생겨도 저절로 따라온다.

    ⚠️ **못 찾으면 원문을 돌려주지 마라.** 라벨을 키인 척 돌려주면 그게 그대로
    resolver 로 들어가 터진다. 빈 문자열이면 호출부가 "모델 정보 없음" 으로 다루고
    지금 고른 모델을 유지한다.

    라벨은 **긴 것부터** 본다 - `"NovelAI Diffusion V4"` 는 `"NovelAI Diffusion V4.5
    Full"` 의 접두사라, 짧은 것을 먼저 대면 4.5 가 4 로 떨어진다.
    """
    haystack = f"{source_value or ''} {model_value or ''}".strip()
    if not haystack:
        return ""

    raw = str(model_value or "").strip()
    if raw.upper() in BUILTIN_NAI_MODEL_SPECS:
        return raw.upper()

    lowered = haystack.lower()

    # 1) 모델 해시가 가장 정확하다. V4 는 Full/Curated 의 **표시 라벨이 같아**
    #    해시로만 갈린다(`NovelAI Diffusion V4 7ABFFA2A` vs `... 37442FCA`).
    for digest, key in NAI_SOURCE_HASHES.items():
        if digest.lower() in lowered:
            return key

    # 2) 와이어 이름(인페인트 변형 포함). 긴 것부터 - 짧은 이름이 긴 이름의
    #    접두사다(`nai-diffusion-4-full` ⊂ `nai-diffusion-4-full-inpainting`).
    for spec in sorted(BUILTIN_NAI_MODEL_SPECS.values(),
                       key=lambda s: len(s.api_model), reverse=True):
        names = [spec.api_model]
        # ⚠️ **빌려 쓰는 인페인팅 이름은 넣지 않는다.** 넣으면 두 스펙이 같은 이름을
        #    들어 먼저 걸린 쪽으로 잘못 귀속된다(V5 인페인트 -> Curated 로 되찾힘).
        if spec.inpainting_api_model and not spec.inpainting_is_substitute:
            names.append(spec.inpainting_api_model)
        if any(n and n.lower() in lowered for n in names):
            return spec.key

    # 3) 표시 라벨. 긴 라벨부터 - `NovelAI Diffusion V4` 는
    #    `NovelAI Diffusion V4.5 Full` 의 접두사라 짧은 것을 먼저 대면 4.5 가 4 로 떨어진다.
    for spec in sorted(BUILTIN_NAI_MODEL_SPECS.values(),
                       key=lambda s: len(s.label), reverse=True):
        if spec.label and spec.label.lower() in lowered:
            return spec.key

    # 4) **맨 계열 이름**. NAI 는 PNG 에 Full/Curated 를 안 붙이고 쓴다 -
    #    실측(2026-08-22): `Comment.model_name = "NovelAI Diffusion V5"`.
    #    여기까지 왔다는 건 해시로도 못 갈랐다는 뜻이라 Full 로 본다(다수 경우).
    #    ⚠️ 이 추정이 싫으면 해시를 `NAI_SOURCE_HASHES` 에 추가하는 것이 정답이다.
    for family, key in NAI_FAMILY_DEFAULT_KEYS.items():
        if family.lower() in lowered:
            return key
    return ""


def context_uses_opus_usage_limit(context: Any) -> bool:
    """지금 고른 모델이 Opus 무료 사용량 풀을 쓰는가(= V5 계열).

    ⚠️ 모델 키는 `context._current_model_key()` 로 읽는다. 처음엔 있지도 않은
    `get_generation_params()` 를 불렀는데, `except` 가 그 AttributeError 를 삼켜
    **항상 False** 가 됐다 - 배지가 영영 안 뜨는데 오류도 안 보였다(실측 2026-08-21).

    이 판정을 보는 곳이 셋(배지 페이로드 · 부하 분산 정책 목록 · 무료 집계)이라
    여기 하나만 둔다. 복사본이 생기면 한쪽만 고쳐져 화면이 서로 다른 말을 한다.
    """
    try:
        key = context._current_model_key()
        return bool(resolve_nai_model_for_context(context, key).uses_opus_usage_limit)
    except Exception as exc:  # pragma: no cover - 조회 실패가 생성 흐름을 막으면 안 됨
        print(f"[warn] NAI usage-limit model check failed: {exc}", flush=True)
        return False


def resolve_nai_api_model(
    model_key: Any,
    custom_models: Mapping[str, NaiModelSpec] | None = None,
) -> str:
    """Resolve a NAIA/UI model key to the outbound API model string."""

    return resolve_nai_model_spec(model_key, custom_models).api_model
