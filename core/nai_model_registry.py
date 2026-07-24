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
REGISTRY_VERSION = 1
MAX_CUSTOM_NAI_MODELS = 32

_MODEL_KEY_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,39}$")
_API_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_FAMILY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")


class NaiModelValidationError(ValueError):
    """A custom model entry is unsafe or incomplete."""


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
        return NaiModelSpec(
            key=key,
            label=cls._clean_label(raw.get("label"), fallback=key),
            api_model=str(api_model),
            payload_profile=profile,
            inpainting_api_model=inpainting,
            family=family,
            source="user",
            selectable=True,
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
        raise NaiModelValidationError(f"등록되지 않은 NAI 모델 키입니다: {key}")

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
                "default_payload_profile": "passthrough",
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
