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
        # NAIA의 현재 encode/apply 계약은 V4/V4.5 경로만 검증돼 있다.
        # V5는 페이로드 구조가 같아 함께 열어 두지만 **라이브 검증은 아직 없다**.
        return self.uses_v4_payload

    @property
    def supports_character_reference(self) -> bool:
        # V5도 `director_reference_*` 를 그대로 받는다(스키마 확인). 라이브 미검증.
        return self.payload_profile in {"v4.5", "v5"}

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
) -> NaiModelSpec:
    return NaiModelSpec(
        key=key,
        label=label,
        api_model=api_model,
        payload_profile=payload_profile,
        inpainting_api_model=inpainting_api_model,
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
        inpainting_api_model="nai-diffusion-5-curated-inpainting",
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


def resolve_nai_api_model(
    model_key: Any,
    custom_models: Mapping[str, NaiModelSpec] | None = None,
) -> str:
    """Resolve a NAIA/UI model key to the outbound API model string."""

    return resolve_nai_model_spec(model_key, custom_models).api_model
