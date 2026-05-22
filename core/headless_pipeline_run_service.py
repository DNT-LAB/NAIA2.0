"""Prompt/generation pipeline run wrappers for the headless context."""

from __future__ import annotations

from typing import Any

from core.pipeline_run_registry import PromptPipelineRun


class HeadlessPipelineRunService:
    def __init__(self, context: Any):
        self.context = context

    def start_prompt_run(
        self,
        *,
        source: str,
        source_row: Any = None,
        settings: dict[str, Any] | None = None,
        external_request_id: str = "",
        metadata: dict[str, Any] | None = None,
        prompt_run_id: str = "",
    ) -> PromptPipelineRun:
        return self.context.pipeline_run_registry.start_prompt_run(
            source=source,
            source_row=source_row,
            settings=settings,
            external_request_id=external_request_id,
            metadata=metadata,
            prompt_run_id=prompt_run_id,
        )

    def complete_prompt_run(
        self,
        prompt_run_id: str,
        *,
        context: Any = None,
        final_prompt: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> PromptPipelineRun | None:
        context_metadata = getattr(context, "metadata", {}) if context is not None else {}
        merged_metadata = {}
        if isinstance(context_metadata, dict):
            merged_metadata.update(context_metadata)
        if isinstance(metadata, dict):
            merged_metadata.update(metadata)
        prompt = final_prompt or str(getattr(context, "final_prompt", "") or "")
        return self.context.pipeline_run_registry.complete_prompt_run(
            prompt_run_id,
            final_prompt=prompt,
            metadata=merged_metadata,
        )

    def fail_prompt_run(
        self,
        prompt_run_id: str,
        error: str,
        *,
        context: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> PromptPipelineRun | None:
        context_metadata = getattr(context, "metadata", {}) if context is not None else {}
        merged_metadata = {}
        if isinstance(context_metadata, dict):
            merged_metadata.update(context_metadata)
        if isinstance(metadata, dict):
            merged_metadata.update(metadata)
        return self.context.pipeline_run_registry.fail_prompt_run(
            prompt_run_id,
            error,
            metadata=merged_metadata,
        )

    def record_prompt_run_hook(
        self,
        prompt_run_id: str,
        *,
        hook_point: str,
        module: str,
        status: str,
        error: str = "",
    ) -> PromptPipelineRun | None:
        return self.context.pipeline_run_registry.record_hook(
            prompt_run_id,
            hook_point=hook_point,
            module=module,
            status=status,
            error=error,
        )

    def record_prompt_run_warning(
        self,
        prompt_run_id: str,
        warning: str,
    ) -> PromptPipelineRun | None:
        return self.context.pipeline_run_registry.record_warning(prompt_run_id, warning)

    def record_prompt_run_derived(
        self,
        prompt_run_id: str,
        derived: dict[str, Any] | None,
    ) -> PromptPipelineRun | None:
        return self.context.pipeline_run_registry.record_derived(prompt_run_id, derived)

    def link_generation_to_prompt_run(
        self,
        prompt_run_id: str,
        generation_request_id: str,
    ) -> PromptPipelineRun | None:
        return self.context.pipeline_run_registry.link_generation_request(
            prompt_run_id,
            generation_request_id,
        )

    def get_prompt_run_payload(
        self,
        prompt_run_id: str,
        *,
        include_source_row: bool = False,
    ) -> dict[str, Any] | None:
        run = self.context.pipeline_run_registry.get_prompt_run(prompt_run_id)
        if run is None:
            return None
        return run.to_payload(include_source_row=include_source_row)

    def prompt_runs_payload(self, limit: int = 50) -> dict[str, Any]:
        return {
            "type": "pipeline_runs",
            "prompt_runs": self.context.pipeline_run_registry.list_prompt_runs(limit),
        }
