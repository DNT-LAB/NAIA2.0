"""Persistent user-defined NovelAI model registry.

The public NAID5 wire identifier and payload schema are not known yet.  Users
therefore register the exact API model string together with an explicit payload
compatibility profile instead of NAIA guessing from the model name.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from core.nai_model_contract import (
    BUILTIN_NAI_MODEL_SPECS,
    DEFAULT_NAI_MODEL_KEY,
    NAI_PAYLOAD_PROFILES,
    NAI_REMOTE_MODEL_KEYS,
    NaiModelSpec,
    normalize_nai_model_key,
)


REGISTRY_FILENAME = "nai_models.json"
REGISTRY_VERSION = 2
MAX_CUSTOM_NAI_MODELS = 32
MAX_MODEL_PARAMETER_RULES = 64

_MODEL_KEY_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,39}$")
_API_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_FAMILY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")


def _collides_with_builtin_wire(key: str) -> bool:
    """이 키가 빌트인 모델의 API(wire) 이름과 같은 글자인가."""
    lowered = str(key or "").lower()
    if not lowered:
        return False
    for spec in BUILTIN_NAI_MODEL_SPECS.values():
        for wire in (spec.api_model, spec.inpainting_api_model):
            if wire and wire.lower() == lowered:
                return True
    return False


class NaiModelValidationError(ValueError):
    """A custom model entry is unsafe or incomplete."""


class UnknownNaiModelError(NaiModelValidationError):
    """레지스트리가 모르는 모델 키로 생성이 막혔다.

    ⚠️ 이 하나만 **화면이 알아볼 수 있어야 한다.** 나머지 검증 실패(라벨 길이 등)는
       사용자가 등록 창에서 고칠 일이지만, 이건 "고른 모델을 알 수 없다" 는 뜻이라
       화면이 PARAMS 를 열고 다시 고르게 안내해야 한다(사용자 지정 2026-08-25).
       `NaiModelValidationError` 를 물려받으므로 기존 `except` 는 그대로 잡는다.
    """

    def __init__(self, key: str):
        self.model_key = str(key or "")
        super().__init__(f"등록되지 않은 NAI 모델 키입니다: {self.model_key}")


class NaiModelRegistry:
    """Runtime SSOT for built-in and user-defined NAI model specifications."""

    def __init__(self, context: Any):
        runtime_paths = getattr(context, "runtime_paths", None)
        if runtime_paths is None or getattr(runtime_paths, "save_dir", None) is None:
            raise RuntimeError("runtime_paths.save_dir is required for the NAI model registry")
        self.context = context
        self.path = Path(runtime_paths.save_dir) / REGISTRY_FILENAME
        self._lock = threading.RLock()
        self._custom: dict[str, NaiModelSpec] = {}
        self._load_warnings: list[str] = []
        self._load()

    @staticmethod
    def _clean_label(value: Any, *, fallback: str) -> str:
        label = " ".join(str(value or "").split()).strip()
        if not label:
            label = fallback
        if len(label) > 80 or any(ord(char) < 32 for char in label):
            raise NaiModelValidationError("label은 제어문자 없이 80자 이하여야 합니다.")
        return label

    @staticmethod
    def _clean_api_model(value: Any, *, field: str, required: bool) -> str | None:
        text = str(value or "").strip()
        if not text and not required:
            return None
        if not text or not _API_MODEL_RE.fullmatch(text):
            raise NaiModelValidationError(
                f"{field}은 영문/숫자로 시작하는 128자 이하 API 모델 식별자여야 합니다."
            )
        return text

    @staticmethod
    def _clean_parameter_name(value: Any, *, field: str) -> str:
        if not isinstance(value, str):
            raise NaiModelValidationError(f"{field}의 파라미터 이름은 문자열이어야 합니다.")
        name = value.strip()
        if not name or len(name) > 128 or any(ord(char) < 32 for char in name):
            raise NaiModelValidationError(
                f"{field}의 파라미터 이름은 제어문자 없이 128자 이하여야 합니다."
            )
        return name

    @classmethod
    def _clean_parameter_overrides(cls, value: Any) -> dict[str, Any]:
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise NaiModelValidationError("api_parameter_overrides는 JSON 객체여야 합니다.")
        if len(value) > MAX_MODEL_PARAMETER_RULES:
            raise NaiModelValidationError(
                f"API 파라미터 덮어쓰기는 최대 {MAX_MODEL_PARAMETER_RULES}개까지 가능합니다."
            )
        cleaned: dict[str, Any] = {}
        for raw_name, raw_value in value.items():
            name = cls._clean_parameter_name(raw_name, field="api_parameter_overrides")
            try:
                serialized = json.dumps(raw_value, ensure_ascii=False, allow_nan=False)
                cleaned[name] = json.loads(serialized)
            except (TypeError, ValueError) as exc:
                raise NaiModelValidationError(
                    f"api_parameter_overrides.{name} 값은 유효한 JSON 값이어야 합니다."
                ) from exc
        return cleaned

    @classmethod
    def _clean_parameter_removals(cls, value: Any) -> tuple[str, ...]:
        if value in (None, ""):
            return ()
        if isinstance(value, str):
            values = re.split(r"[\r\n,]+", value)
        elif isinstance(value, (list, tuple)):
            values = list(value)
        else:
            raise NaiModelValidationError(
                "api_parameter_removals는 파라미터 이름 배열이어야 합니다."
            )
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw_name in values:
            if isinstance(raw_name, str) and not raw_name.strip():
                continue
            name = cls._clean_parameter_name(raw_name, field="api_parameter_removals")
            if name not in seen:
                seen.add(name)
                cleaned.append(name)
        if len(cleaned) > MAX_MODEL_PARAMETER_RULES:
            raise NaiModelValidationError(
                f"API 파라미터 강제 제거는 최대 {MAX_MODEL_PARAMETER_RULES}개까지 가능합니다."
            )
        return tuple(cleaned)

    @classmethod
    def normalize_entry(cls, raw: Any) -> NaiModelSpec:
        if not isinstance(raw, dict):
            raise NaiModelValidationError("모델 항목은 JSON 객체여야 합니다.")
        key = normalize_nai_model_key(raw.get("key"))
        if not _MODEL_KEY_RE.fullmatch(key):
            raise NaiModelValidationError(
                "key는 영문 대문자/숫자로 시작하고 . _ - 만 사용하는 40자 이하여야 합니다."
            )
        if key in BUILTIN_NAI_MODEL_SPECS:
            raise NaiModelValidationError(f"기본 모델 키는 덮어쓸 수 없습니다: {key}")
        # ⚠️ **wire 이름과 같은 키를 새로 만들지 못하게 한다.** 키 문법이 공백을 안 써서
        #    `NAI-DIFFUSION-5-FULL` 같은 이름이 그대로 통과하는데, 그러면 메타데이터
        #    복원 경로가 이 키를 빌트인 wire 로 읽어 **다른 모델에 돈을 태운다**
        #    (Codex 리뷰 BLOCK). 이미 만들어 둔 것은 `_load` 에서 막지 않는다 -
        #    쓰던 모델을 말없이 없애는 쪽이 더 나쁘고, 등록돼 있는 동안은 위
        #    `_nai_registry_knows` 가 먼저 잡아 준다.
        if _collides_with_builtin_wire(key):
            raise NaiModelValidationError(
                f"기본 모델의 API 이름과 같은 키는 쓸 수 없습니다: {key}"
            )
        api_model = cls._clean_api_model(raw.get("api_model"), field="api_model", required=True)
        profile = str(raw.get("payload_profile") or "passthrough").strip().lower()
        if profile not in NAI_PAYLOAD_PROFILES:
            allowed = ", ".join(sorted(NAI_PAYLOAD_PROFILES))
            raise NaiModelValidationError(f"payload_profile은 다음 중 하나여야 합니다: {allowed}")
        inpainting = cls._clean_api_model(
            raw.get("inpainting_api_model"),
            field="inpainting_api_model",
            required=False,
        )
        family = str(raw.get("family") or profile).strip().lower()
        if not _FAMILY_RE.fullmatch(family):
            raise NaiModelValidationError(
                "family는 영문/숫자로 시작하고 . _ - 만 사용하는 32자 이하여야 합니다."
            )
        parameter_overrides = cls._clean_parameter_overrides(
            raw.get("api_parameter_overrides")
        )
        parameter_removals = cls._clean_parameter_removals(
            raw.get("api_parameter_removals")
        )
        return NaiModelSpec(
            key=key,
            label=cls._clean_label(raw.get("label"), fallback=key),
            api_model=str(api_model),
            payload_profile=profile,
            inpainting_api_model=inpainting,
            family=family,
            source="user",
            selectable=True,
            api_parameter_overrides=parameter_overrides,
            api_parameter_removals=parameter_removals,
        )

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._load_warnings.append(f"레지스트리 JSON을 읽지 못했습니다: {exc}")
            return
        items = raw.get("models") if isinstance(raw, dict) else None
        if not isinstance(items, list):
            self._load_warnings.append("레지스트리의 models가 배열이 아닙니다.")
            return
        for index, item in enumerate(items[:MAX_CUSTOM_NAI_MODELS]):
            try:
                spec = self.normalize_entry(item)
            except NaiModelValidationError as exc:
                self._load_warnings.append(f"models[{index}] 무시: {exc}")
                continue
            self._custom[spec.key] = spec
        if len(items) > MAX_CUSTOM_NAI_MODELS:
            self._load_warnings.append(
                f"최대 {MAX_CUSTOM_NAI_MODELS}개를 초과한 모델은 무시했습니다."
            )

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": REGISTRY_VERSION,
            "models": [
                {
                    "key": spec.key,
                    "label": spec.label,
                    "api_model": spec.api_model,
                    "payload_profile": spec.payload_profile,
                    "inpainting_api_model": spec.inpainting_api_model,
                    "family": spec.family,
                    "api_parameter_overrides": dict(spec.api_parameter_overrides),
                    "api_parameter_removals": list(spec.api_parameter_removals),
                }
                for spec in self._custom.values()
            ],
        }
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp.replace(self.path)

    def custom_specs(self) -> dict[str, NaiModelSpec]:
        with self._lock:
            return dict(self._custom)

    def resolve(self, model_key: Any) -> NaiModelSpec:
        key = normalize_nai_model_key(model_key) or DEFAULT_NAI_MODEL_KEY
        with self._lock:
            custom = self._custom.get(key)
            if custom is not None:
                return custom
            builtin = BUILTIN_NAI_MODEL_SPECS.get(key)
            if builtin is not None:
                return builtin
        raise UnknownNaiModelError(key)

    def has_key(self, model_key: Any) -> bool:
        key = normalize_nai_model_key(model_key)
        with self._lock:
            return key in BUILTIN_NAI_MODEL_SPECS or key in self._custom

    def key_for_api_model(self, api_model: Any) -> str:
        wire_name = str(api_model or "").strip().lower()
        if not wire_name:
            return ""
        with self._lock:
            for spec in self._custom.values():
                if wire_name in {
                    spec.api_model.lower(),
                    str(spec.inpainting_api_model or "").lower(),
                }:
                    return spec.key
        return ""

    def option_keys(self) -> list[str]:
        with self._lock:
            return [*NAI_REMOTE_MODEL_KEYS, *self._custom.keys()]

    def option_metadata(self, *, include_keys: list[str] | None = None) -> list[dict[str, Any]]:
        with self._lock:
            keys = self.option_keys()
            for raw_key in include_keys or []:
                key = normalize_nai_model_key(raw_key)
                if self.has_key(key) and key not in keys:
                    keys.append(key)
            return [self.resolve(key).to_payload() for key in keys]

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ok": True,
                "version": REGISTRY_VERSION,
                "default_model": DEFAULT_NAI_MODEL_KEY,
                "payload_profiles": sorted(NAI_PAYLOAD_PROFILES),
                "max_custom_models": MAX_CUSTOM_NAI_MODELS,
                # UI의 Auto 프로필이 미지 모델을 기본으로 태우는 파이프라인과 일치시킨다.
                "default_payload_profile": "v4.5",
                "built_in": [
                    spec.to_payload() for spec in BUILTIN_NAI_MODEL_SPECS.values()
                ],
                "custom": [spec.to_payload() for spec in self._custom.values()],
                "options": self.option_keys(),
                "warnings": list(self._load_warnings),
            }

    def upsert(self, raw: Any) -> dict[str, Any]:
        spec = self.normalize_entry(raw)
        with self._lock:
            if spec.key not in self._custom and len(self._custom) >= MAX_CUSTOM_NAI_MODELS:
                raise NaiModelValidationError(
                    f"사용자 모델은 최대 {MAX_CUSTOM_NAI_MODELS}개까지 추가할 수 있습니다."
                )
            previous = dict(self._custom)
            self._custom[spec.key] = spec
            try:
                self._save_locked()
            except Exception:
                self._custom = previous
                raise
            return spec.to_payload()

    def delete(self, model_key: Any) -> dict[str, Any]:
        key = normalize_nai_model_key(model_key)
        if key in BUILTIN_NAI_MODEL_SPECS:
            raise NaiModelValidationError(f"기본 모델은 삭제할 수 없습니다: {key}")
        with self._lock:
            previous = dict(self._custom)
            removed = self._custom.pop(key, None)
            if removed is None:
                raise KeyError(key)
            try:
                self._save_locked()
            except Exception:
                self._custom = previous
                raise
            return removed.to_payload()
