"""Dynamic API option loading for the headless Remote Web runtime."""

from __future__ import annotations

from typing import Any

import requests

from core.webui_utils import WebuiAPIUtils


API_OPTION_KEYS = ("options_model", "options_sampler", "options_scheduler", "options_hr_upscaler")


class HeadlessApiOptionService:
    def __init__(self, context: Any):
        self.context = context

    def refresh(self, mode: str) -> dict[str, Any]:
        normalized_mode = str(mode or "").strip().upper()
        if normalized_mode == "WEBUI":
            url = self._token("webui_url")
            options = self._fetch_webui_options(url)
        elif normalized_mode == "COMFYUI":
            url = self._token("comfyui_url")
            options = self._fetch_comfyui_options(url)
        else:
            return {"type": "api_options", "mode": normalized_mode, "success": False, "options": {}}

        if options:
            cache = getattr(self.context, "remote_option_cache", None)
            if cache is None:
                self.context.remote_option_cache = {}
                cache = self.context.remote_option_cache
            cache[normalized_mode] = options
            self._apply_selected_defaults(normalized_mode, options)

        return {
            "type": "api_options",
            "mode": normalized_mode,
            "success": bool(options),
            "options": options,
        }

    def clear(self, mode: str) -> None:
        normalized_mode = str(mode or "").strip().upper()
        cache = getattr(self.context, "remote_option_cache", None)
        if isinstance(cache, dict):
            cache.pop(normalized_mode, None)

    def _fetch_webui_options(self, url: str) -> dict[str, list[str]]:
        normalized_url = _normalize_url(url)
        if not normalized_url:
            return {}

        options = {
            "options_model": _dedupe(WebuiAPIUtils.get_model_list(normalized_url)),
            "options_sampler": _dedupe(WebuiAPIUtils.get_sampler_list(normalized_url)),
            "options_scheduler": _dedupe(WebuiAPIUtils.get_schedulers_list(normalized_url)),
            "options_hr_upscaler": _dedupe(WebuiAPIUtils.get_upscaler_list(normalized_url)),
        }
        current_model = str(WebuiAPIUtils.get_current_model(normalized_url) or "").strip()
        if current_model and options["options_model"]:
            options["model"] = [_choose_option(current_model, options["options_model"], current_model)]
        return _non_empty_options(options)

    def _fetch_comfyui_options(self, url: str) -> dict[str, list[str]]:
        normalized_url = _normalize_url(url)
        if not normalized_url:
            return {}
        try:
            response = requests.get(f"{normalized_url}/object_info", timeout=10)
            response.raise_for_status()
            object_info = response.json() or {}
        except Exception:
            return {}
        return extract_comfyui_options(object_info)

    def _apply_selected_defaults(self, mode: str, options: dict[str, list[str]]) -> None:
        params = self.context.remote_params
        default_model = ""
        if mode == "COMFYUI":
            default_model = self._token("comfyui_default_model")

        fallback_model = (default_model or "ComfyUI Workflow") if mode == "COMFYUI" else "Stable Diffusion"
        model_options = options.get("options_model") or []
        sampler_options = options.get("options_sampler") or []
        scheduler_options = options.get("options_scheduler") or []
        upscaler_options = options.get("options_hr_upscaler") or []

        if model_options:
            current_model = params.get("model") or ((options.get("model") or [""])[0])
            options["model"] = [_choose_option(current_model, model_options, fallback_model)]
        if sampler_options:
            options["sampler"] = [_choose_option(params.get("sampler"), sampler_options, sampler_options[0])]
        if scheduler_options:
            options["scheduler"] = [_choose_option(params.get("scheduler"), scheduler_options, scheduler_options[0])]
        if upscaler_options:
            options["hr_upscaler"] = [_choose_option(params.get("hr_upscaler"), upscaler_options, upscaler_options[0])]

    def _token(self, key: str) -> str:
        return str(self.context.secure_token_manager.get_token(key) or "").strip()


def extract_comfyui_options(object_info: dict[str, Any]) -> dict[str, list[str]]:
    models: list[str] = []
    samplers: list[str] = []
    schedulers: list[str] = []

    for node_info in (object_info or {}).values():
        required = ((node_info or {}).get("input") or {}).get("required") or {}
        for key in ("ckpt_name", "unet_name"):
            models.extend(_extract_option_list(required.get(key)))
        samplers.extend(_extract_option_list(required.get("sampler_name")))
        schedulers.extend(_extract_option_list(required.get("scheduler")))

    return _non_empty_options({
        "options_model": _dedupe(models),
        "options_sampler": _dedupe(samplers),
        "options_scheduler": _dedupe(schedulers),
    })


def _extract_option_list(spec: Any) -> list[str]:
    if not isinstance(spec, list) or not spec:
        return []
    first = spec[0]
    values = first if isinstance(first, list) else spec
    if not isinstance(values, list):
        return []
    return [
        str(value).strip()
        for value in values
        if not isinstance(value, (dict, list)) and str(value or "").strip()
    ]


def _normalize_url(url: str) -> str:
    clean = str(url or "").strip().rstrip("/")
    if not clean:
        return ""
    if clean.startswith(("http://", "https://")):
        return clean
    return f"http://{clean}"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def _non_empty_options(options: dict[str, list[str]]) -> dict[str, list[str]]:
    return {key: values for key, values in options.items() if values}


def _choose_option(current: Any, options: list[str], fallback: str) -> str:
    clean_current = str(current or "").strip()
    if clean_current in options:
        return clean_current

    folded_current = clean_current.casefold()
    if folded_current:
        for option in options:
            if option.casefold() == folded_current:
                return option

    clean_fallback = str(fallback or "").strip()
    if clean_fallback in options:
        return clean_fallback

    folded_fallback = clean_fallback.casefold()
    if folded_fallback:
        for option in options:
            if option.casefold() == folded_fallback:
                return option

    return options[0] if options else clean_current
