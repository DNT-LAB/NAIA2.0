"""Headless Remote Web status, queue, and parameter schema payloads."""

from __future__ import annotations

from typing import Any
import re

from core.headless_remote_state_service import HeadlessRemoteStateService


class HeadlessSessionStateService:
    def __init__(self, context: Any):
        self.context = context

    def autocomplete_status_payload(self) -> dict[str, Any]:
        return self.context.autocomplete_state.to_payload()

    def api_status_payload(self, client_host: str | None = None) -> dict[str, Any]:
        context = self.context
        return context.api_config_service.status_payload(
            active_mode=context.get_api_mode(),
            autocomplete=self.autocomplete_status_payload(),
            client_host=client_host,
        )

    def http_status_payload(self) -> dict[str, Any]:
        context = self.context
        return {
            "is_generating": bool(context.is_generating),
            "api_mode": context.get_api_mode(),
            "autocomplete": self.autocomplete_status_payload(),
        }

    def queue_state_payload(self) -> dict[str, Any]:
        context = self.context
        stats = context.generation_queue_manager.get_queue_stats()
        queued = [
            self.serialize_queue_request(request, position=index + 1)
            for index, request in enumerate(context.generation_queue_manager.get_all_requests())
        ]
        return {
            "type": "queue_state",
            "is_generating": bool(context.is_generating),
            "paused": bool(stats.get("is_paused", False)),
            "total": int(stats.get("total", len(queued)) or 0),
            "has_urgent": bool(stats.get("has_urgent", False)),
            "priority_counts": stats.get("priority_counts", {}),
            "active": None,
            "items": queued,
        }

    @staticmethod
    def queue_preview(value: Any, limit: int = 140) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        return text if len(text) <= limit else text[:limit - 1].rstrip() + "..."

    def queue_param_summary(self, params: dict[str, Any] | None = None, request: Any = None) -> dict[str, Any]:
        context = self.context
        params = params if isinstance(params, dict) else {}
        prompt = params.get("_raw_input") or params.get("input") or params.get("prompt") or ""
        negative = params.get("negative_prompt") or params.get("uc") or ""
        width = params.get("width")
        height = params.get("height")
        resolution = f"{width}x{height}" if width and height else str(params.get("resolution") or "")

        character_count = 0
        characters = params.get("characters")
        if isinstance(characters, (list, tuple)):
            character_count = len(characters)
        nai_characters = getattr(request, "nai_characters", None) if request else None
        if not character_count and nai_characters:
            character_count = len(getattr(nai_characters, "characters", []) or [])

        vibe_count = 0
        vibes = params.get("reference_image_multiple")
        if isinstance(vibes, (list, tuple)):
            vibe_count = len(vibes)
        nai_vibes = getattr(request, "nai_vibe_transfer", None) if request else None
        if not vibe_count and nai_vibes:
            vibe_count = len(getattr(nai_vibes, "reference_image_multiple", []) or [])

        char_ref_count = 0
        director_images = params.get("director_reference_images")
        if isinstance(director_images, (list, tuple)):
            char_ref_count = len(director_images)
        nai_ref = getattr(request, "nai_character_reference", None) if request else None
        if not char_ref_count and nai_ref:
            char_ref_count = len(getattr(nai_ref, "director_reference_images", []) or [])

        return {
            "prompt_preview": self.queue_preview(prompt),
            "negative_preview": self.queue_preview(negative, 100),
            "mode": str(params.get("api_mode") or context.get_api_mode() or ""),
            "resolution": resolution,
            "seed": str(params.get("seed") or ""),
            "source": str(params.get("_remote_queue_source") or "queue"),
            "label": str(params.get("_remote_queue_label") or ""),
            "character_count": character_count,
            "vibe_count": vibe_count,
            "char_ref_count": char_ref_count,
        }

    def serialize_queue_request(self, request: Any, position: int | None = None) -> dict[str, Any]:
        params = getattr(request, "params", {}) if request else {}
        summary = self.queue_param_summary(params, request=request)
        source_row = getattr(request, "source_row", None) if request else None
        source_name = str(getattr(source_row, "name", "") or "")
        label = summary["label"] or source_name or summary["source"]
        return {
            **summary,
            "id": str(getattr(request, "request_id", "") or ""),
            "generation_request_id": str(getattr(request, "request_id", "") or ""),
            "prompt_run_id": str(getattr(request, "prompt_run_id", "") or params.get("prompt_run_id") or ""),
            "position": position,
            "priority": int(getattr(request, "priority", 0) or 0),
            "status": str(getattr(request, "status", "pending") or "pending"),
            "created_at": getattr(getattr(request, "created_at", None), "isoformat", lambda: None)(),
            "started_at": getattr(getattr(request, "started_at", None), "isoformat", lambda: None)(),
            "completed_at": getattr(getattr(request, "completed_at", None), "isoformat", lambda: None)(),
            "wait_time": request.get_wait_time() if request and hasattr(request, "get_wait_time") else None,
            "elapsed_time": request.get_elapsed_time() if request and hasattr(request, "get_elapsed_time") else None,
            "label": self.queue_preview(label, 80),
        }

    def generation_param_schema_payload(self) -> dict[str, Any]:
        from core.resolution_utils import ANIMA_RESOLUTION_LABELS, STANDARD_1MP_RESOLUTION_LABELS

        context = self.context
        mode = context.get_api_mode()
        resolution_options = list(ANIMA_RESOLUTION_LABELS if mode == "COMFYUI" else STANDARD_1MP_RESOLUTION_LABELS)
        resolution = str(context.remote_params.get("resolution") or "832 x 1216")
        if resolution not in resolution_options:
            resolution_options.append(resolution)
        payload = {
            "type": "params",
            "api_mode": mode,
            "schema_only": False,
            "model": "NAID4.5F",
            "sampler": "k_euler_ancestral",
            "scheduler": "karras",
            "resolution": resolution,
            "steps": 28,
            "cfg_scale": 5.0,
            "cfg_rescale": 0.0,
            "seed": "",
            "seed_fixed": False,
            "random_resolution": False,
            "auto_fit_resolution": False,
            "options_model": self.model_options_for_mode(mode),
            "options_sampler": self.sampler_options_for_mode(mode),
            "options_scheduler": self.scheduler_options_for_mode(mode),
            "options_resolution": resolution_options,
            "steps_range": [1, 50],
            "nai_flags_enabled": {
                "SMEA": mode == "NAI",
                "DYN": mode == "NAI",
                "VAR+": mode == "NAI",
                "DECRISP": mode == "NAI",
            },
        }
        if mode == "NAI":
            payload.update({
                "SMEA": False,
                "DYN": False,
                "VAR+": False,
                "DECRISP": False,
            })
        elif mode == "WEBUI":
            hires_state = context._normalized_webui_hiresfix_assist_state(context.webui_hiresfix_assist_state)
            payload.update({
                "enable_hr": False,
                "hr_scale": 2.0,
                "hr_upscaler": "Latent (nearest-exact)",
                "denoising_strength": 0.5,
                "hires_steps": 0,
                "hr_cfg": 7.0,
                "options_hr_upscaler": [
                    "Latent (nearest-exact)",
                    "Latent",
                    "Lanczos",
                    "Nearest",
                    "ESRGAN_4x",
                    "R-ESRGAN 4x+",
                    "R-ESRGAN 4x+ Anime6B",
                ],
                "webui_hiresfix_assist": bool(hires_state["enabled"]),
                "webui_hiresfix_assist_target": int(hires_state["target"]),
                "hires_preset_swap": str(context.remote_params.get("hires_preset_swap") or ""),
                "resolution_preset_enabled": bool(context.remote_params.get("resolution_preset_enabled", False)),
                "resolution_preset": str(context.remote_params.get("resolution_preset") or "standard"),
                "anima_weight": str(
                    context.remote_params.get("anima_weight")
                    or context.remote_params.get("random_prompt_weight")
                    or ""
                ),
            })
        elif mode == "COMFYUI":
            payload.update({
                "sampling_mode": str(context.remote_params.get("sampling_mode") or "anima"),
                "rescale_cfg": context.remote_params.get("rescale_cfg", 0.0),
                "anima_weight": str(
                    context.remote_params.get("anima_weight")
                    or context.remote_params.get("random_prompt_weight")
                    or ""
                ),
                "resolution_preset_enabled": bool(context.remote_params.get("resolution_preset_enabled", False)),
                "resolution_preset": str(context.remote_params.get("resolution_preset") or "standard"),
                "comfyui_workflow": dict(context.remote_params.get("comfyui_workflow") or {}),
                "comfyui_workflow_has_custom": bool(context.remote_params.get("comfyui_workflow_has_custom", False)),
                "comfyui_workflow_label": str(context.remote_params.get("comfyui_workflow_label") or "Default workflow"),
                "comfyui_workflow_type": context.remote_params.get("comfyui_workflow_type"),
            })
        payload.update(context.remote_params)
        option_cache = getattr(context, "remote_option_cache", {}) or {}
        cached_options = option_cache.get(mode, {}) if isinstance(option_cache, dict) else {}
        for key in ("options_model", "options_sampler", "options_scheduler", "options_hr_upscaler"):
            values = cached_options.get(key)
            if isinstance(values, list) and values:
                payload[key] = list(values)
        for key in ("model", "sampler", "scheduler", "hr_upscaler"):
            values = cached_options.get(key)
            if isinstance(values, list) and values:
                payload[key] = values[0]
        return payload

    def initial_websocket_messages(
        self,
        *,
        session_id: str | None = None,
        client_host: str | None = None,
    ) -> list[dict[str, Any]]:
        context = self.context
        messages: list[dict[str, Any]] = []
        if session_id:
            messages.append({
                "type": "session",
                "session_id": session_id,
                "prompt": context.prompt_text,
                "negative_prompt": context.negative_prompt_text,
            })
        messages.extend([
            {"type": "mode", "mode": context.get_api_mode()},
            {"type": "options", **context.get_options()},
            self.generation_param_schema_payload(),
            self.queue_state_payload(),
            self.api_status_payload(client_host),
            {"type": "init_complete"},
        ])
        return messages

    @staticmethod
    def coerce_remote_param(key: str, value: Any) -> Any:
        return HeadlessRemoteStateService.coerce_remote_param(key, value)

    @staticmethod
    def model_options_for_mode(mode: str) -> list[str]:
        if mode == "WEBUI":
            return ["Stable Diffusion"]
        if mode == "COMFYUI":
            return ["ComfyUI Workflow"]
        return ["NAID4.5F", "NAID4.5", "NAID4", "NAID3"]

    @staticmethod
    def sampler_options_for_mode(mode: str) -> list[str]:
        if mode == "WEBUI":
            return ["Euler a", "Euler", "DPM++ 2M", "DPM++ 2M Karras"]
        if mode == "COMFYUI":
            return ["euler", "euler_ancestral", "dpmpp_2m", "dpmpp_sde"]
        return ["k_euler_ancestral", "k_euler", "k_dpmpp_2m", "ddim"]

    @staticmethod
    def scheduler_options_for_mode(mode: str) -> list[str]:
        if mode == "WEBUI":
            return ["Automatic", "Karras", "Exponential", "SGM Uniform"]
        if mode == "COMFYUI":
            return ["normal", "karras", "exponential", "sgm_uniform"]
        return ["karras", "native", "exponential", "polyexponential"]

    @staticmethod
    def coerce_bool(value: Any) -> bool:
        return HeadlessRemoteStateService.coerce_bool(value)
