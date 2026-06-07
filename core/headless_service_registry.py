"""Lazy-load registry for WebSessionContext feature services."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HeadlessServiceSpec:
    module_name: str
    class_name: str

    def create(self, context: Any):
        module = importlib.import_module(self.module_name)
        return getattr(module, self.class_name)(context)


HEADLESS_SERVICE_SPECS = {
    "img2img": HeadlessServiceSpec("core.headless_img2img_service", "HeadlessImg2ImgService"),
    "character_reference": HeadlessServiceSpec(
        "core.headless_character_reference_service",
        "HeadlessCharacterReferenceService",
    ),
    "vibe_transfer": HeadlessServiceSpec("core.headless_vibe_transfer_service", "HeadlessVibeTransferService"),
    "image_module_param": HeadlessServiceSpec(
        "core.headless_image_module_param_service",
        "HeadlessImageModuleParamService",
    ),
    "automation": HeadlessServiceSpec("core.headless_automation_service", "HeadlessAutomationService"),
    "webui_hiresfix_assist": HeadlessServiceSpec(
        "core.headless_webui_hiresfix_assist_service",
        "HeadlessWebuiHiresfixAssistService",
    ),
    "event_stream": HeadlessServiceSpec("core.headless_event_stream_service", "HeadlessEventStreamService"),
    "storyteller": HeadlessServiceSpec("core.headless_storyteller_service", "HeadlessStorytellerService"),
    "sequence_run": HeadlessServiceSpec("core.headless_sequence_run_service", "HeadlessSequenceRunService"),
    "prompt_engineering": HeadlessServiceSpec(
        "core.headless_prompt_engineering_service",
        "HeadlessPromptEngineeringService",
    ),
    "conditional_prompt": HeadlessServiceSpec(
        "core.headless_conditional_prompt_service",
        "HeadlessConditionalPromptService",
    ),
    "character": HeadlessServiceSpec("core.headless_character_service", "HeadlessCharacterService"),
    "wildcard": HeadlessServiceSpec("core.headless_wildcard_service", "HeadlessWildcardService"),
    "instant_wildcard": HeadlessServiceSpec(
        "core.headless_instant_wildcard_service",
        "HeadlessInstantWildcardService",
    ),
    "save": HeadlessServiceSpec("core.headless_save_service", "HeadlessSaveService"),
    "search_state": HeadlessServiceSpec("core.headless_search_state_service", "HeadlessSearchStateService"),
    "session_state": HeadlessServiceSpec("core.headless_session_state_service", "HeadlessSessionStateService"),
    "runtime_path": HeadlessServiceSpec("core.headless_runtime_path_service", "HeadlessRuntimePathService"),
    "pipeline_run": HeadlessServiceSpec("core.headless_pipeline_run_service", "HeadlessPipelineRunService"),
    "pipeline_hook": HeadlessServiceSpec("core.headless_pipeline_hook_service", "HeadlessPipelineHookService"),
    "api_control": HeadlessServiceSpec("core.headless_api_control_service", "HeadlessApiControlService"),
    "api_options": HeadlessServiceSpec("core.headless_api_option_service", "HeadlessApiOptionService"),
    "remote_state": HeadlessServiceSpec("core.headless_remote_state_service", "HeadlessRemoteStateService"),
    "module_dispatch": HeadlessServiceSpec(
        "core.headless_module_dispatch_service",
        "HeadlessModuleDispatchService",
    ),
    "e621_event": HeadlessServiceSpec("core.e621_event_service", "E621EventService"),
}


def get_headless_service_spec(service_name: str) -> HeadlessServiceSpec:
    return HEADLESS_SERVICE_SPECS[service_name]
