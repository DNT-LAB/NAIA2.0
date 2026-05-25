"""Server-owned Remote Web mode, options, and parameter state."""

from __future__ import annotations

from typing import Any


SUPPORTED_API_MODES = ("NAI", "WEBUI", "COMFYUI")
REMOTE_OPTION_DEFAULTS = {
    "prompt_fixed": False,
    "auto_generate": False,
    "wildcard_standalone": False,
    "auto_save": True,
}
REMOTE_BOOLEAN_PARAMS = {
    "seed_fixed",
    "random_resolution",
    "auto_fit_resolution",
    "enable_hr",
    "resolution_preset_enabled",
    "webui_hiresfix_assist",
    "webui_hiresfix_assist_enabled",
    "SMEA",
    "DYN",
    "VAR+",
    "DECRISP",
}
REMOTE_INT_PARAMS = {
    "steps",
    "hires_steps",
    "width",
    "height",
    "webui_hiresfix_assist_target",
}
REMOTE_FLOAT_PARAMS = {
    "cfg_scale",
    "cfg_rescale",
    "hr_scale",
    "denoising_strength",
    "hr_cfg",
    "rescale_cfg",
}


class HeadlessRemoteStateService:
    def __init__(self, context: Any):
        self.context = context

    def get_api_mode(self) -> str:
        return self.context.current_api_mode

    def set_api_mode(self, mode: str) -> None:
        normalized = str(mode or "").strip().upper()
        if normalized not in SUPPORTED_API_MODES:
            return
        if normalized == self.context.current_api_mode:
            return
        old_mode = self.context.current_api_mode
        self.context.current_api_mode = normalized
        self.context.save_remote_ui_state()
        self.context.publish("api_mode_changed", {"old_mode": old_mode, "new_mode": normalized})

    def set_option(self, key: str, value: Any) -> None:
        if key not in REMOTE_OPTION_DEFAULTS:
            return
        self.context.remote_options[key] = bool(value)
        if key == "auto_save":
            self.context.auto_save_state["auto_save"] = bool(value)
        self.context.save_remote_ui_state()
        self.context.publish("remote_options_changed", self.get_options())

    def get_options(self) -> dict[str, bool]:
        options = dict(REMOTE_OPTION_DEFAULTS)
        options.update({
            key: bool(value)
            for key, value in self.context.remote_options.items()
            if key in options
        })
        return options

    def set_param(self, key: str, value: Any) -> None:
        clean_key = str(key or "").strip()
        if not clean_key:
            return
        self.context.remote_params[clean_key] = self.coerce_remote_param(clean_key, value)
        self._sync_cached_selection(clean_key, self.context.remote_params[clean_key])
        self.context.save_remote_ui_state()
        self.context.publish("remote_params_changed", self.context.generation_param_schema_payload())

    def _sync_cached_selection(self, key: str, value: Any) -> None:
        if key not in {"model", "sampler", "scheduler", "hr_upscaler"}:
            return
        mode = self.get_api_mode()
        option_cache = getattr(self.context, "remote_option_cache", None)
        if not isinstance(option_cache, dict):
            return
        cached_options = option_cache.get(mode)
        if not isinstance(cached_options, dict):
            return
        cached_options[key] = [value]

    def current_model_key(self) -> str:
        model = str(self.context.remote_params.get("model") or "NAID4.5F").strip()
        return model or "NAID4.5F"

    def is_naid45_model(self) -> bool:
        model = self.current_model_key()
        return "NAID4.5F" in model or "NAID4.5C" in model

    def is_naid3_model(self) -> bool:
        return "NAID3" in self.current_model_key()

    @staticmethod
    def coerce_remote_param(key: str, value: Any) -> Any:
        if key in REMOTE_BOOLEAN_PARAMS:
            return HeadlessRemoteStateService.coerce_bool(value)
        if key in REMOTE_INT_PARAMS:
            try:
                if value is None or value == "":
                    return ""
                return int(float(value))
            except (TypeError, ValueError):
                return value
        if key in REMOTE_FLOAT_PARAMS:
            try:
                if value is None or value == "":
                    return ""
                return float(value)
            except (TypeError, ValueError):
                return value
        return value

    @staticmethod
    def coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
