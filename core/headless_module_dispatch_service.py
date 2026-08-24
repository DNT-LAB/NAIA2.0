"""Headless module state and action dispatch."""

from __future__ import annotations

from typing import Any


HEADLESS_RETIRED_MODULES = {
    "wildcard_status": "Wildcard Status is not available in this runtime.",
    "ollama": "Ollama assistant controls are not available in this runtime.",
}


class HeadlessModuleDispatchService:
    def __init__(self, context: Any):
        self.context = context

    def module_state_payload(self, module_id: str, client_host: str | None = None) -> dict[str, Any]:
        context = self.context
        clean_id = str(module_id or "").strip()
        if clean_id == "auto_save":
            return context.auto_save_state_payload()
        if clean_id == "save_directory":
            return context.save_directory_state_payload(client_host)
        if clean_id == "prompt_engineering":
            return context._prompt_engineering_module_state()
        if clean_id == "conditional_prompt":
            return context._conditional_prompt_module_state()
        if clean_id == "character":
            return context._character_module_state()
        if clean_id == "character_reference":
            return context._character_reference_module_state()
        if clean_id == "vibe_transfer":
            return context._vibe_transfer_module_state()
        if clean_id == "img2img":
            return context._img2img_module_state()
        if clean_id == "automation":
            return context._automation_module_state()
        if clean_id == "webui_hiresfix_assist":
            return context._webui_hiresfix_assist_module_state()
        if clean_id == "event_stream":
            return context._event_stream_module_state()
        if clean_id == "storyteller":
            return context._storyteller_module_state()
        if clean_id == "v5_scene":
            return context._v5_scene_module_state()
        if clean_id == "wildcard":
            return context._wildcard_module_state()
        if clean_id == "instant_wildcard":
            return context._instant_wildcard_module_state()
        if clean_id == "chunk":
            return context._chunk_module_state()
        if clean_id == "e621_event":
            return context._e621_event_module_state()
        if clean_id == "extensions":
            from core.extension_runtime import load_extensions

            return context._module_state_payload(
                "extensions", load_extensions(context).panel_state()
            )
        if clean_id in HEADLESS_RETIRED_MODULES:
            return self.retired_module_state(clean_id)
        return {
            "type": "module_state",
            "module_id": clean_id,
            "available": False,
            "runtime": "web",
            "state": {},
        }

    def set_module_param(
        self,
        module_id: str,
        key: str,
        value: Any,
        *,
        client_host: str | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        context = self.context
        clean_id = str(module_id or "").strip()
        clean_key = str(key or "").strip()
        if clean_id == "auto_save":
            # quicksave_dir 이 임의 경로를 받으므로 save_directory 와 같은 경계가 필요하다.
            return context._save_service().set_auto_save_param(
                clean_key, value, client_host=client_host)
        if clean_id == "save_directory":
            return context._save_service().set_save_directory_param(clean_key, value, client_host=client_host)
        if clean_id == "prompt_engineering":
            return context._set_prompt_engineering_param(clean_key, value)
        if clean_id == "conditional_prompt":
            return context._set_conditional_prompt_param(clean_key, value)
        if clean_id == "character":
            return context._set_character_param(clean_key, value)
        if clean_id == "character_reference":
            return context._set_character_reference_param(clean_key, value)
        if clean_id == "vibe_transfer":
            return context._set_vibe_transfer_param(clean_key, value)
        if clean_id == "img2img":
            return context._set_img2img_param(clean_key, value)
        if clean_id == "automation":
            return context._set_automation_param(clean_key, value)
        if clean_id == "webui_hiresfix_assist":
            return context._set_webui_hiresfix_assist_param(clean_key, value)
        if clean_id == "event_stream":
            return context._set_event_stream_param(clean_key, value)
        if clean_id == "storyteller":
            return context._set_storyteller_param(clean_key, value)
        if clean_id == "v5_scene":
            return context._set_v5_scene_param(clean_key, value)
        if clean_id == "wildcard":
            return context._set_wildcard_param(clean_key, value)
        if clean_id == "instant_wildcard":
            return context._set_instant_wildcard_param(clean_key, value)
        if clean_id == "e621_event":
            return context._set_e621_event_param(clean_key, value)
        if clean_id == "extensions":
            # 즉시 발효 키(enabled/blocked/setting)만 여기로 온다 — approve/retry는
            # import가 수반되므로 module_commands가 백그라운드 태스크로 처리.
            from core.extension_runtime import load_extensions

            manager = load_extensions(context)
            manager.apply_panel_param(clean_key, value)
            return context._module_state_payload("extensions", manager.panel_state())
        if clean_id in HEADLESS_RETIRED_MODULES:
            return self.retired_module_state(clean_id, action=clean_key)
        return None

    def retired_module_state(self, module_id: str, *, action: str | None = None) -> dict[str, Any]:
        message = HEADLESS_RETIRED_MODULES.get(
            str(module_id or ""),
            "Module is not available in this runtime.",
        )
        state = {
            "available": False,
            "retired": True,
            "message": message,
        }
        if action:
            state["last_action"] = action
        return self.context._module_state_payload(module_id, state)
