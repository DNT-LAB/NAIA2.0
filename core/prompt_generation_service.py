from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pandas as pd

from core.prompt_context import PromptContext
from core.prompt_processor import PromptProcessor
from core.search_result_model import SearchResultModel
from core.wildcard_processor import split_tags_smart

if TYPE_CHECKING:
    from core.context import AppContext


@dataclass
class PromptGenerationResult:
    context: PromptContext | None = None
    final_prompt: str | None = None
    error: str | None = None
    detected_resolution: tuple[int, int] | None = None
    reset_resolution_detected: bool = False


@dataclass
class PromptSourcePreparation:
    source_row: pd.Series | None = None
    remaining_count: int | None = None
    error: str | None = None


class PromptGenerationService:
    """PyQt-free prompt generation core shared by desktop wrappers and Remote Web."""

    def __init__(self, app_context: "AppContext"):
        self.app_context = app_context
        self._processor = None

    @property
    def processor(self) -> PromptProcessor:
        if self._processor is None:
            self._processor = PromptProcessor(self.app_context)
        return self._processor

    @processor.setter
    def processor(self, value) -> None:
        self._processor = value

    def _create_initial_context(self, source_row: pd.Series, settings: dict) -> PromptContext:
        existing_sequential_counters = {}
        existing_wildcard_state = {}
        if (
            hasattr(self.app_context, "current_prompt_context")
            and self.app_context.current_prompt_context
        ):
            existing_sequential_counters = self.app_context.current_prompt_context.sequential_counters.copy()
            existing_wildcard_state = self.app_context.current_prompt_context.wildcard_state.copy()

        context = PromptContext(source_row=source_row, settings=settings)
        context.sequential_counters = existing_sequential_counters
        context.wildcard_state = existing_wildcard_state

        general_str = source_row.get("general", "")
        if pd.notna(general_str) and isinstance(general_str, str):
            context.main_tags = split_tags_smart(general_str)

        event_stream = getattr(self.app_context, "event_stream_runtime", None)
        if event_stream and event_stream.is_active:
            event_stream.apply_context_freeze(context)
        return context

    def set_current_context(
        self,
        source_row: pd.Series,
        settings: dict,
        *,
        source: str = "prompt",
        request_id: str = "",
        prompt_run_id: str = "",
        track_run: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> PromptContext:
        self.app_context.current_source_row = source_row
        context = self._create_initial_context(source_row, settings)
        if track_run:
            starter = getattr(self.app_context, "start_prompt_run", None)
            if callable(starter):
                run = starter(
                    source=source,
                    source_row=source_row,
                    settings=settings,
                    external_request_id=request_id,
                    metadata=metadata,
                    prompt_run_id=prompt_run_id,
                )
                context.metadata["prompt_run_id"] = run.prompt_run_id
                context.metadata["prompt_source"] = source
                if request_id:
                    context.metadata["external_request_id"] = request_id
        self.app_context.current_prompt_context = context
        return self.app_context.current_prompt_context

    def process_current_context(self) -> PromptGenerationResult:
        try:
            final_context = self.processor.process()
        except Exception as exc:
            self._fail_context_run(getattr(self.app_context, "current_prompt_context", None), str(exc))
            raise
        result = self.build_result(final_context)
        self._finalize_context_run(result)
        return result

    def build_result(self, context: PromptContext | None) -> PromptGenerationResult:
        if not context:
            return PromptGenerationResult()

        final_prompt = str(context.final_prompt or "")
        if (
            not final_prompt.strip(" ,\n\r\t")
            and not context.settings.get("wildcard_standalone", False)
        ):
            return PromptGenerationResult(
                context=context,
                error="생성된 프롬프트가 비어 있습니다. 다른 검색 결과를 사용해 주세요.",
            )

        detected_resolution = None
        if "detected_resolution" in context.metadata:
            width, height = context.metadata["detected_resolution"]
            detected_resolution = (width, height)

        event_stream = getattr(self.app_context, "event_stream_runtime", None)
        if event_stream and event_stream.is_active:
            event_stream.record_generated_context(context)

        return PromptGenerationResult(
            context=context,
            final_prompt=final_prompt,
            detected_resolution=detected_resolution,
            reset_resolution_detected=(
                detected_resolution is None
                and bool(context.settings.get("auto_fit_resolution", False))
            ),
        )

    def normalize_instant_source(self, instant_row: dict | pd.Series) -> pd.Series | None:
        if isinstance(instant_row, pd.Series):
            return instant_row
        if not isinstance(instant_row, dict):
            return None

        processed_dict: dict[str, Any] = {}
        for key, value in instant_row.items():
            if isinstance(value, list):
                processed_dict[key] = ", ".join(map(str, value))
            else:
                processed_dict[key] = value
        return pd.Series(processed_dict)

    def generate_instant_source_silent(self, instant_row: dict | pd.Series, settings: dict) -> str | None:
        saved_source = getattr(self.app_context, "current_source_row", None)
        saved_context = getattr(self.app_context, "current_prompt_context", None)
        try:
            source_row = self.normalize_instant_source(instant_row)
            if source_row is None:
                return None
            self.set_current_context(source_row, settings, track_run=False)
            final_context = self.processor.process()
            return final_context.final_prompt if final_context else None
        except Exception as e:
            print(f"[TagInterrogation] Silent generation error: {e}")
            return None
        finally:
            self.app_context.current_source_row = saved_source
            self.app_context.current_prompt_context = saved_context

    def prepare_next_source(
        self,
        search_results: SearchResultModel,
        settings: dict,
        active_ratings: set | None = None,
        source_row_override: pd.Series | None = None,
    ) -> PromptSourcePreparation:
        if settings.get("wildcard_standalone", False):
            source_row = pd.Series(
                {
                    "general": None,
                    "character": None,
                    "copyright": None,
                    "artist": None,
                    "meta": None,
                },
                name="wildcard_standalone",
            )
            return PromptSourcePreparation(source_row=source_row, remaining_count=search_results.get_count())

        if source_row_override is not None:
            return PromptSourcePreparation(
                source_row=source_row_override,
                remaining_count=search_results.get_count(),
            )

        source_row = search_results.pop_random_row(active_ratings)
        if source_row is None:
            return PromptSourcePreparation(error="처리할 프롬프트가 더 이상 없습니다.")
        return PromptSourcePreparation(source_row=source_row, remaining_count=search_results.get_count())

    def _finalize_context_run(self, result: PromptGenerationResult) -> None:
        context = result.context
        if context is None:
            return
        prompt_run_id = str(getattr(context, "metadata", {}).get("prompt_run_id") or "")
        if not prompt_run_id:
            return
        if result.error:
            self._fail_context_run(context, result.error)
            return
        derived_recorder = getattr(self.app_context, "record_prompt_run_derived", None)
        if callable(derived_recorder):
            derived_recorder(
                prompt_run_id,
                {
                    "detected_resolution": result.detected_resolution,
                    "reset_resolution_detected": result.reset_resolution_detected,
                },
            )
        completer = getattr(self.app_context, "complete_prompt_run", None)
        if callable(completer):
            completer(prompt_run_id, context=context, final_prompt=result.final_prompt or "")

    def _fail_context_run(self, context: PromptContext | None, error: str) -> None:
        if context is None:
            return
        prompt_run_id = str(getattr(context, "metadata", {}).get("prompt_run_id") or "")
        if not prompt_run_id:
            return
        marker = getattr(self.app_context, "fail_prompt_run", None)
        if callable(marker):
            marker(prompt_run_id, error, context=context)
