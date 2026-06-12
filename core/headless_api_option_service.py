"""Dynamic API option loading for the headless Remote Web runtime."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import re
from typing import Any, Callable

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
            # 확장 등 구독자에게 라이브 옵션 갱신을 알린다(예: 샘플러 선택지를
            # 실제 백엔드 목록으로 재구성 — ctx.get_sampler_options 소비자).
            try:
                self.context.publish(
                    "api_options_refreshed",
                    {"mode": normalized_mode, "keys": sorted(options.keys())},
                )
            except Exception:
                pass

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

        fetched = _fetch_concurrently({
            "options_model": lambda: WebuiAPIUtils.get_model_list(normalized_url),
            "options_sampler": lambda: WebuiAPIUtils.get_sampler_list(normalized_url),
            "options_scheduler": lambda: WebuiAPIUtils.get_schedulers_list(normalized_url),
            "options_hr_upscaler": lambda: WebuiAPIUtils.get_upscaler_list(normalized_url),
            "current_model": lambda: WebuiAPIUtils.get_current_model(normalized_url),
        })
        options = {
            "options_model": _dedupe(fetched.get("options_model") or []),
            "options_sampler": _dedupe(fetched.get("options_sampler") or []),
            "options_scheduler": _dedupe(fetched.get("options_scheduler") or []),
            "options_hr_upscaler": _dedupe(fetched.get("options_hr_upscaler") or []),
        }
        current_model = str(fetched.get("current_model") or "").strip()
        if current_model and options["options_model"]:
            options["model"] = [_choose_model_option(current_model, options["options_model"], current_model)]
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
            current_model = _find_model_option(params.get("model"), model_options)
            if not current_model:
                current_model = (options.get("model") or [""])[0]
            options["model"] = [_choose_model_option(current_model, model_options, fallback_model)]
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


def _fetch_concurrently(fetchers: dict[str, Callable[[], Any]]) -> dict[str, Any]:
    if not fetchers:
        return {}
    results: dict[str, Any] = {}
    max_workers = min(len(fetchers), 5)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_key = {
            executor.submit(fetcher): key
            for key, fetcher in fetchers.items()
        }
        for future in as_completed(future_to_key):
            key = future_to_key[future]
            try:
                results[key] = future.result()
            except Exception:
                results[key] = [] if key != "current_model" else ""
    return results


def _non_empty_options(options: dict[str, list[str]]) -> dict[str, list[str]]:
    return {key: values for key, values in options.items() if values}


def _choose_model_option(current: Any, options: list[str], fallback: str) -> str:
    clean_current = str(current or "").strip()
    selected = _find_model_option(current, options)
    if selected:
        return selected

    clean_fallback = str(fallback or "").strip()
    direct = _choose_exact_option(clean_fallback, options)
    if direct:
        return direct

    fallback_alias = _model_alias(clean_fallback)
    if fallback_alias:
        for option in options:
            if _model_alias(option) == fallback_alias:
                return option

    return options[0] if options else clean_current


def _find_model_option(current: Any, options: list[str]) -> str:
    clean_current = str(current or "").strip()
    direct = _choose_exact_option(clean_current, options)
    if direct:
        return direct

    current_alias = _model_alias(clean_current)
    if current_alias:
        for option in options:
            if _model_alias(option) == current_alias:
                return option
    return ""


def _choose_exact_option(current: str, options: list[str]) -> str:
    if not current:
        return ""
    if current in options:
        return current
    folded_current = current.casefold()
    for option in options:
        if option.casefold() == folded_current:
            return option
    return ""


def _model_alias(value: Any) -> str:
    clean = str(value or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    clean = re.sub(r"\s+\[[0-9a-fA-F]{6,}\]$", "", clean).strip()
    return clean.casefold()


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
