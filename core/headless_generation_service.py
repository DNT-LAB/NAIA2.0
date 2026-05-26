"""Headless Remote Web generation request normalization.

Round 35 keeps generation dispatch PyQt-free by turning the Remote Web payload
into the same queue request shape used by the desktop controller. Actual image
API execution is moved in a later round; this service owns the request contract
and queue handoff only.
"""

from __future__ import annotations

from dataclasses import dataclass
import random
import re
from typing import Any

import pandas as pd

from core.generation_request import (
    GenerationRequest,
    NAICharacterData,
    NAICharacterReferenceData,
    NAIVibeTransferData,
)
from core.headless_result_service import HeadlessStoredResult
from core.web_session_context import WebSessionContext


TOKEN_KEYS = {
    "NAI": "nai_token",
    "WEBUI": "webui_url",
    "COMFYUI": "comfyui_url",
}

SCHEMA_ONLY_KEYS = {
    "type",
    "schema_only",
    "options_model",
    "options_sampler",
    "options_scheduler",
    "options_resolution",
    "steps_range",
    "nai_flags_enabled",
}

DERIVED_GENERATION_PARAM_KEYS = (
    "api_mode",
    "model",
    "sampler",
    "scheduler",
    "steps",
    "width",
    "height",
    "resolution",
    "seed",
    "cfg_scale",
    "cfg_rescale",
    "negative_prompt",
)


@dataclass
class HeadlessGenerationDispatch:
    request: GenerationRequest | None
    api_mode: str
    blocked_reason: str = ""

    @property
    def request_id(self) -> str:
        return self.request.request_id if self.request is not None else ""

    @property
    def ok(self) -> bool:
        return self.request is not None and not self.blocked_reason

    def websocket_payload(self) -> dict[str, Any]:
        if not self.ok:
            return {
                "type": "generation_dispatched",
                "ok": False,
                "api_mode": self.api_mode,
                "message": self.blocked_reason,
            }

        params = self.request.params
        prompt_run_id = str(getattr(self.request, "prompt_run_id", "") or params.get("prompt_run_id") or "")
        return {
            "type": "generation_dispatched",
            "ok": True,
            "request_id": self.request.request_id,
            "generation_request_id": self.request.request_id,
            "prompt_run_id": prompt_run_id,
            "api_mode": self.api_mode,
            "priority": self.request.priority,
            "queued": True,
            "params": {
                "width": params.get("width"),
                "height": params.get("height"),
                "model": params.get("model"),
                "sampler": params.get("sampler"),
                "scheduler": params.get("scheduler"),
                "steps": params.get("steps"),
                "cfg_scale": params.get("cfg_scale"),
                "seed": params.get("seed"),
                "has_prompt": bool(params.get("input")),
                "has_negative_prompt": bool(params.get("negative_prompt")),
                "credential_configured": bool(params.get("credential")),
            },
        }


class HeadlessGenerationService:
    """Create queue-ready generation requests without desktop widgets."""

    def __init__(self, context: WebSessionContext):
        self.context = context

    def enqueue_remote_request(
        self,
        command: dict[str, Any] | None = None,
        *,
        enqueue: bool = True,
    ) -> HeadlessGenerationDispatch:
        command = command if isinstance(command, dict) else {}
        api_mode = self._normalize_mode(command)
        credential = self._credential_for_mode(api_mode)
        if not credential:
            return HeadlessGenerationDispatch(
                request=None,
                api_mode=api_mode,
                blocked_reason=f"{api_mode} credential is not configured.",
            )

        params = self._normalized_params(command, api_mode, credential)
        source_row = self._source_row(params)
        params.pop("_source_row_data", None)
        params.pop("_source_name", None)
        prompt_run_id = self._prompt_run_id_for_command(command, params)
        if not prompt_run_id:
            prompt_run_id = self._create_direct_prompt_run(command, params, source_row)
        if prompt_run_id:
            params["prompt_run_id"] = prompt_run_id
        priority = self._priority(command)
        nai_characters, nai_vibe_transfer, nai_character_reference = self._extract_nai_data(params, api_mode)
        request = GenerationRequest(
            params=params,
            source_row=source_row,
            priority=priority,
            max_retries=0,
            nai_characters=nai_characters,
            nai_vibe_transfer=nai_vibe_transfer,
            nai_character_reference=nai_character_reference,
            prompt_run_id=prompt_run_id,
        )
        params["generation_request_id"] = request.request_id
        if params.get("result_enhance_request"):
            params["result_enhance_request_id"] = request.request_id

        queue_manager = self.context.generation_queue_manager
        if enqueue:
            if priority > 0:
                queue_manager.enqueue_with_priority(request)
            else:
                queue_manager.enqueue_request(request)

        self.context.last_generation_request = request
        self.context.last_generation_params = params
        if prompt_run_id:
            linker = getattr(self.context, "link_generation_to_prompt_run", None)
            if callable(linker):
                linker(prompt_run_id, request.request_id)
            derived_recorder = getattr(self.context, "record_prompt_run_derived", None)
            if callable(derived_recorder):
                derived_recorder(
                    prompt_run_id,
                    {
                        "generation_request_id": request.request_id,
                        "generation_params": self._derived_generation_params(params),
                    },
                )
        self.context.publish("generation_request_dispatched", {
            "request_id": request.request_id,
            "generation_request_id": request.request_id,
            "prompt_run_id": prompt_run_id,
            "api_mode": api_mode,
            "priority": priority,
        })
        print(
            "Headless Remote: generation request queued "
            f"id={request.request_id[:8]} mode={api_mode} "
            f"size={params.get('width')}x{params.get('height')}",
            flush=True,
        )
        return HeadlessGenerationDispatch(request=request, api_mode=api_mode)

    @staticmethod
    def _derived_generation_params(params: dict[str, Any]) -> dict[str, Any]:
        return {
            key: params.get(key)
            for key in DERIVED_GENERATION_PARAM_KEYS
            if key in params
        }

    def execute_request(self, request: GenerationRequest) -> HeadlessStoredResult:
        """Execute one queued request and store its result in server state."""

        params = dict(request.params or {})
        params["_generation_request"] = request
        request.mark_processing()
        api_service = self._api_service()
        api_result = api_service.call_generation_api(params)
        if api_result.get("status") == "error":
            error_message = str(api_result.get("message") or "Unknown API error")
            request.mark_failed(error_message)
            raise RuntimeError(error_message)
        api_result["generation_params"] = params
        api_result["source_row"] = request.source_row
        stored = self.context.result_store.add_api_result(api_result, request)
        request.mark_completed()
        self.context.publish("generation_result_available", {
            "request_id": request.request_id,
            "generation_request_id": request.request_id,
            "prompt_run_id": str(getattr(request, "prompt_run_id", "") or params.get("prompt_run_id") or ""),
            "api_mode": params.get("api_mode", ""),
        })
        print(
            "Headless Remote: generation completed "
            f"id={request.request_id[:8]} mode={params.get('api_mode', '')} "
            f"size={stored.item.image.width}x{stored.item.image.height}",
            flush=True,
        )
        return stored

    def _api_service(self):
        service = getattr(self.context, "api_service", None)
        if service is None:
            from core.api_service import APIService

            service = APIService(self.context)
            self.context.api_service = service
        return service

    def _normalize_mode(self, command: dict[str, Any]) -> str:
        overrides = command.get("overrides") if isinstance(command.get("overrides"), dict) else {}
        requested = str(command.get("api_mode") or overrides.get("api_mode") or self.context.get_api_mode() or "NAI")
        normalized = requested.strip().upper()
        return normalized if normalized in TOKEN_KEYS else "NAI"

    def _credential_for_mode(self, api_mode: str) -> str:
        token_key = TOKEN_KEYS.get(api_mode, "nai_token")
        return str(self.context.secure_token_manager.get_token(token_key) or "")

    def _normalized_params(self, command: dict[str, Any], api_mode: str, credential: str) -> dict[str, Any]:
        schema = self.context.generation_param_schema_payload()
        params = {
            key: value
            for key, value in schema.items()
            if key not in SCHEMA_ONLY_KEYS and not key.startswith("options_")
        }
        params.update(self.context.get_options())
        params.update(self.context.remote_params)

        overrides = command.get("overrides") if isinstance(command.get("overrides"), dict) else {}
        params.update(overrides)

        prompt = command.get("prompt")
        negative = command.get("negative_prompt")
        if prompt is not None:
            params["input"] = str(prompt)
            params["_raw_input"] = str(prompt)
        elif "input" not in params:
            params["input"] = str(self.context.prompt_text or "")
            params["_raw_input"] = params["input"]
        if negative is not None:
            params["negative_prompt"] = str(negative)
        elif "negative_prompt" not in params:
            params["negative_prompt"] = str(self.context.negative_prompt_text or "")

        params["api_mode"] = api_mode
        params["credential"] = credential
        params["_remote_web_session_params"] = True
        params["_remote_queue_source"] = str(params.get("_remote_queue_source") or "Web")

        self._normalize_booleans(params)
        self._normalize_resolution(params)
        self._normalize_numbers(params, api_mode)
        apply_image_modules = getattr(self.context, "apply_headless_image_module_params", None)
        if callable(apply_image_modules):
            apply_image_modules(params, api_mode)
        return params

    def _normalize_resolution(self, params: dict[str, Any]) -> None:
        width = self._to_int(params.get("width"))
        height = self._to_int(params.get("height"))
        if width is None or height is None:
            parsed = self._parse_resolution(params.get("resolution"))
            if parsed:
                width, height = parsed
        if width is None or height is None or width <= 0 or height <= 0:
            width, height = 832, 1216
        params["width"] = width
        params["height"] = height
        params["resolution"] = f"{width} x {height}"

    def _normalize_numbers(self, params: dict[str, Any], api_mode: str) -> None:
        int_defaults = {
            "steps": 28,
            "width": 832,
            "height": 1216,
        }
        for key, default in int_defaults.items():
            params[key] = self._to_int(params.get(key), default)

        float_defaults = {
            "cfg_scale": 5.0,
            "cfg_rescale": 0.0,
            "hr_scale": 2.0,
            "denoising_strength": 0.5,
            "hr_cfg": 7.0,
        }
        for key, default in float_defaults.items():
            if key in params:
                params[key] = self._to_float(params.get(key), default)

        if params.get("seed_fixed"):
            params["seed"] = self._to_int(params.get("seed"), 0)
        elif api_mode == "NAI":
            params["seed"] = self._to_int(params.get("seed"), None)
            if params["seed"] is None or params["seed"] < 0:
                params["seed"] = random.randint(0, 9_999_999_999)
        elif "seed" in params:
            params["seed"] = self._to_int(params.get("seed"), -1)

    def _normalize_booleans(self, params: dict[str, Any]) -> None:
        for key in (
            "seed_fixed",
            "random_resolution",
            "auto_fit_resolution",
            "prompt_fixed",
            "auto_generate",
            "wildcard_standalone",
            "enable_hr",
            "webui_hiresfix_assist",
        ):
            if key in params:
                params[key] = self._to_bool(params.get(key))

    def _source_row(self, params: dict[str, Any]) -> pd.Series:
        source_row_data = params.get("_source_row_data")
        if isinstance(source_row_data, dict):
            return pd.Series(
                source_row_data,
                name=str(params.get("_source_name") or "web_headless"),
            )
        if params.get("wildcard_standalone"):
            return pd.Series({
                "general": None,
                "character": None,
                "copyright": None,
                "artist": None,
                "meta": None,
            }, name="wildcard_standalone")
        source_row = self.context.current_source_row
        if isinstance(source_row, pd.Series):
            return source_row
        if isinstance(source_row, dict):
            return pd.Series(source_row)
        return pd.Series({
            "general": None,
            "character": None,
            "copyright": None,
            "artist": None,
            "meta": None,
        }, name="web_headless")

    def _prompt_run_id_for_command(self, command: dict[str, Any], params: dict[str, Any]) -> str:
        explicit = (
            command.get("prompt_run_id")
            or command.get("promptRunId")
            or params.get("prompt_run_id")
            or params.get("promptRunId")
        )
        if explicit:
            return str(explicit)

        current_context = getattr(self.context, "current_prompt_context", None)
        metadata = getattr(current_context, "metadata", {}) if current_context is not None else {}
        current_prompt_run_id = str(metadata.get("prompt_run_id") or "") if isinstance(metadata, dict) else ""
        if not current_prompt_run_id:
            return ""

        current_prompt = str(getattr(current_context, "final_prompt", "") or self.context.prompt_text or "")
        request_prompt = str(params.get("input") or params.get("_raw_input") or "")
        if current_prompt.strip() and current_prompt.strip() == request_prompt.strip():
            return current_prompt_run_id
        return ""

    def _create_direct_prompt_run(
        self,
        command: dict[str, Any],
        params: dict[str, Any],
        source_row: pd.Series,
    ) -> str:
        starter = getattr(self.context, "start_prompt_run", None)
        completer = getattr(self.context, "complete_prompt_run", None)
        if not callable(starter) or not callable(completer):
            return ""
        settings = {
            key: value
            for key, value in params.items()
            if key != "credential" and not str(key).startswith("_")
        }
        external_request_id = str(
            command.get("request_id")
            or command.get("requestId")
            or params.get("request_id")
            or params.get("requestId")
            or ""
        )
        run = starter(
            source="direct_generation",
            source_row=source_row,
            settings=settings,
            external_request_id=external_request_id,
            metadata={"direct_generation": True},
        )
        completer(
            run.prompt_run_id,
            final_prompt=str(params.get("input") or ""),
            metadata={
                "prompt_source": "direct_generation",
                "api_mode": params.get("api_mode", ""),
            },
        )
        return run.prompt_run_id

    def _priority(self, command: dict[str, Any]) -> int:
        if self._to_bool(command.get("urgent")):
            return 100
        priority = self._to_int(command.get("priority"), 0)
        return max(0, priority)

    def _extract_nai_data(
        self,
        params: dict[str, Any],
        api_mode: str,
    ) -> tuple[NAICharacterData | None, NAIVibeTransferData | None, NAICharacterReferenceData | None]:
        if api_mode != "NAI":
            return None, None, None
        nai_characters = None
        nai_vibe_transfer = None
        nai_character_reference = None
        try:
            nai_characters = NAICharacterData.from_params(params)
        except Exception:
            nai_characters = None
        try:
            nai_vibe_transfer = NAIVibeTransferData.from_params(params)
        except Exception:
            nai_vibe_transfer = None
        try:
            nai_character_reference = NAICharacterReferenceData.from_params(params)
        except Exception:
            nai_character_reference = None
        return nai_characters, nai_vibe_transfer, nai_character_reference

    @staticmethod
    def _parse_resolution(value: Any) -> tuple[int, int] | None:
        match = re.search(r"(\d+)\s*x\s*(\d+)", str(value or ""), re.IGNORECASE)
        if not match:
            return None
        width = int(match.group(1))
        height = int(match.group(2))
        if width <= 0 or height <= 0:
            return None
        return width, height

    @staticmethod
    def _to_int(value: Any, default: int | None = None) -> int | None:
        try:
            if value is None or value == "":
                return default
            return int(float(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_float(value: Any, default: float) -> float:
        try:
            if value is None or value == "":
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off", ""}:
                return False
        return bool(value)


__all__ = ["HeadlessGenerationDispatch", "HeadlessGenerationService"]
