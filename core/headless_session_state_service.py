"""Headless Remote Web status, queue, and parameter schema payloads."""

from __future__ import annotations

import json
from typing import Any
import re

from core.headless_remote_state_service import HeadlessRemoteStateService
from core.nai_anlas_cost import cost_params_for_context, estimate_anlas_cost
from core.nai_free_usage import FREE_PIXELS_MAX, FREE_STEPS_MAX
from core.resolution_utils import (
    NAI_RESOLUTION_PRESET_DISPLAY,
    NAI_RESOLUTION_PRESET_LABELS,
    nai_resolution_preset_labels,
    normalize_nai_resolution_preset_id,
)
from core.nai_model_contract import NAI_REMOTE_MODEL_KEYS, NAI_SAMPLER_OPTIONS

# 해상도 매니저가 저장하는 모드 키 (params_workflow_routes.REMOTE_RESOLUTION_MODES와 동일).
_RESOLUTION_MODES = ("NAI", "WEBUI", "COMFYUI")


def _normalized_resolution_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


class HeadlessSessionStateService:
    def __init__(self, context: Any):
        self.context = context

    def resolution_options_for_mode(self, mode: str | None = None) -> list[str]:
        """해상도 매니저가 저장한 모드별 해상도 목록 (없으면 표준 1MP 폴백).

        ``save/resolutions.json``은 params_workflow_routes의 해상도 매니저가
        쓰는 파일과 동일하다. 스키마 페이로드·Auto Gen 랜덤 해상도 reroll이
        모두 이 함수를 모집단으로 쓰므로, 사용자가 목록을 줄이면 재시작 후에도
        Rnd Res가 그 목록 안에서만 추첨된다.
        """
        from core.resolution_utils import STANDARD_1MP_RESOLUTION_LABELS

        normalized_mode = str(mode or self.context.get_api_mode() or "NAI").strip().upper()
        if normalized_mode not in _RESOLUTION_MODES:
            normalized_mode = "NAI"
        defaults = list(STANDARD_1MP_RESOLUTION_LABELS)
        try:
            path = self.context._existing_save_path("resolutions.json")
            if not path.exists():
                return defaults
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return defaults
        items: list[str] = []
        if isinstance(loaded, list):
            # 레거시 포맷: 모드 구분 없는 단일 목록 → 모든 모드에 적용.
            items = _normalized_resolution_list(loaded)
        elif isinstance(loaded, dict):
            # 모드별 키가 우선, 없으면 레거시 "resolutions" 키.
            items = (
                _normalized_resolution_list(loaded.get(normalized_mode))
                or _normalized_resolution_list(loaded.get("resolutions"))
            )
        return items or defaults

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
        # COMFYUI/ANIMA shares the 1MP band default; larger ANIMA resolutions are opt-in
        # via the Res Preset bands, so the resolution dropdown isn't flooded with the full
        # 512..1536 ANIMA range by default (user request: default to the 1024 band).
        context = self.context
        mode = context.get_api_mode()
        # 해상도 매니저가 저장한 모드별 목록을 매번 재해석한다 — 재시작/모드 전환
        # 후에도 드롭다운(=Rnd Res 추첨 모집단)이 사용자 목록을 유지한다.
        resolution_options = self.resolution_options_for_mode(mode)
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
            # Anlas 를 물기 시작하는 문턱. 화면이 상단 Anlas 알약을 점멸시키는 데
            # 쓴다(사용자 지정 2026-08-28). **여기를 SSOT 로 삼는다** - 프론트가
            # 숫자를 따로 들면 한쪽만 고쳤을 때 경고가 거짓말을 한다.
            # 경계는 `초과`다: 28스텝·1024x1024 까지는 무료(`nai_free_usage` 참조).
            "nai_free_limits": {
                "steps": FREE_STEPS_MAX,
                "pixels": FREE_PIXELS_MAX,
            },
            # Generate 버튼 옆에 띄울 **추정** Anlas. NAI 웹 UI 의 계산식을 옮긴
            # 것이라 공식 계약이 아니다 - 표시용이고 집계엔 안 쓴다. 무료 판정은
            # `is_free_generation` 을 그대로 재사용하므로 상단 알약의 유료 점멸과
            # 항상 같은 말을 한다. NAI 가 아니면 뜻이 없으니 0.
            "nai_anlas_cost": (
                estimate_anlas_cost(context, cost_params_for_context(context))
                if mode == "NAI" else 0),
            # 무료 풀이 마른 뒤의 가격. 화면은 사용량 소진 신호(`nai_usage_update`
            # 의 `quota_exhausted`)를 보고 둘 중 하나를 고른다 - 계산식을 프론트에
            # 복제하지 않으려고 **둘 다 내려 준다**.
            "nai_anlas_cost_if_paid": (
                estimate_anlas_cost(context, cost_params_for_context(context), ignore_free=True)
                if mode == "NAI" else 0),
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
                # NAI 전용 해상도 밴드(Small/Normal/Large/Wallpaper). ANIMA 쪽
                # `resolution_preset` 과 **키를 나눠 뒀다** - id 공간이 달라서
                # 섞이면 `normal` 이 `standard` 로 뭉개진다.
                "nai_resolution_preset_enabled": bool(
                    context.remote_params.get("nai_resolution_preset_enabled", False)),
                "nai_resolution_preset": normalize_nai_resolution_preset_id(
                    context.remote_params.get("nai_resolution_preset")),
                # 표를 **백엔드가 내려 준다.** 화면이 같은 숫자를 따로 들면 한쪽만
                # 고쳤을 때 드롭다운이 거짓말을 한다(ANIMA 표가 이미 그렇게 복제돼
                # 있어 드리프트 위험을 안고 있다).
                "options_nai_resolution_preset": [
                    {
                        "id": key,
                        "label": NAI_RESOLUTION_PRESET_DISPLAY.get(key, key),
                        "resolutions": list(labels),
                    }
                    for key, labels in NAI_RESOLUTION_PRESET_LABELS.items()
                ],
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
        # remote_params에 남아 있을 수 있는 (다른 모드에서 저장된) 스테일
        # options_resolution이 위 update로 덮어쓰지 못하게, 파일 기반 모드별
        # 목록을 최종 확정한다.
        payload["options_resolution"] = list(resolution_options)
        # 밴드를 켰으면 드롭다운(= Rnd Res 의 프런트 추첨 모집단)을 그 밴드로 좁힌다.
        # ⚠️ `resolution_options_for_mode` 안에서 좁히면 **해상도 관리자**까지 좁아져
        #    사용자가 저장해 둔 목록이 화면에서 사라진다 - 여기서만 갈아 끼운다.
        if mode == "NAI" and context._coerce_bool(
                context.remote_params.get("nai_resolution_preset_enabled", False)):
            band = list(nai_resolution_preset_labels(
                context.remote_params.get("nai_resolution_preset")))
            current = str(context.remote_params.get("resolution") or "")
            if current and current not in band:
                band.append(current)      # 지금 값이 사라지면 콤보가 비어 보인다
            payload["options_resolution"] = band
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
        if mode == "NAI":
            # 사용자 모델 레지스트리가 NAI 모델 선택지의 최종 권위다. 기존
            # remote_option_cache가 서버 재시작 전 목록을 들고 있어도 새 모델을
            # 가리지 않으며, 프런트 관리 화면 없이도 기존 모델 select에 즉시 노출된다.
            registry = context._nai_model_registry()
            model_options = registry.option_keys()
            selected_model = str(payload.get("model") or "").strip().upper()
            if registry.has_key(selected_model) and selected_model not in model_options:
                model_options.append(selected_model)
            payload["options_model"] = model_options
            payload["options_model_meta"] = registry.option_metadata(
                include_keys=[selected_model] if selected_model else None
            )
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
        # V5 인페인트 가상 캔버스는 모듈 팝업이 아니라 Result 안에 산다. 아무도 안
        # 물어보면 새로고침/재접속 뒤에 화면에서 사라진다 - 세션은 서버에 멀쩡히
        # 살아 있는데 편집 수단만 없어진다.
        #
        # ⚠️ **세션이 있을 때만** 싣는다. 웹 스모크 계약은 초기 메시지 **타입을 순서대로**
        #    세므로, 조건 없이 한 줄 더하면 그 뒤가 전부 밀려 계약이 깨진다(실측).
        try:
            session = getattr(context, "img2img_session", None)
            if isinstance(session, dict) and session.get("canvas_supported"):
                messages.append(context.module_state_payload("img2img", client_host))
        except Exception:   # noqa: BLE001 - 복구용 한 줄 때문에 접속이 막히면 안 된다
            pass
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
        return list(NAI_REMOTE_MODEL_KEYS)

    @staticmethod
    def sampler_options_for_mode(mode: str) -> list[str]:
        if mode == "WEBUI":
            return ["Euler a", "Euler", "DPM++ 2M", "DPM++ 2M Karras"]
        if mode == "COMFYUI":
            return ["euler", "euler_ancestral", "dpmpp_2m", "dpmpp_sde"]
        return list(NAI_SAMPLER_OPTIONS)

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
