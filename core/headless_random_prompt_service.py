"""Server-owned Random prompt service for the headless Remote Web path."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import weakref

import pandas as pd

from core.prompt_generation_service import PromptGenerationService
from core.search_result_model import SearchResultModel
from core.web_session_context import WebSessionContext


DEFAULT_RATINGS = ("g", "s", "q", "e")


@dataclass
class HeadlessRandomPromptResult:
    success: bool
    prompt: str = ""
    error: str = ""
    remaining: int = 0
    rating_counts: dict[str, int] | None = None
    context: Any = None
    random_request_id: str = ""
    detected_resolution: tuple[int, int] | None = None
    reset_resolution_detected: bool = False

    def websocket_payload(self) -> dict[str, Any]:
        if not self.success:
            return {
                "type": "random_failed",
                "message": self.error or "Random prompt failed",
                "level": "error",
            }

        payload: dict[str, Any] = {
            "type": "prompt_generated",
            "prompt": self.prompt,
            "remaining": int(self.remaining or 0),
            "source": "random",
            "rating_counts": self.rating_counts or {rating: 0 for rating in DEFAULT_RATINGS},
        }
        if self.random_request_id:
            payload["random_request_id"] = self.random_request_id
            payload["requestId"] = self.random_request_id
        if self.detected_resolution:
            width, height = self.detected_resolution
            payload["detected_resolution"] = {"width": width, "height": height}
            payload["resolution"] = f"{width} x {height}"
        return payload


class HeadlessRandomPromptService:
    """Generate Remote Web random prompts without RemoteBridge or Qt widgets."""

    def __init__(self, context: WebSessionContext):
        self.context = context
        self._runtime_registered = False

    def generate(
        self,
        *,
        active_ratings: set[str] | None = None,
        overrides: dict[str, Any] | None = None,
        random_request_id: str = "",
    ) -> HeadlessRandomPromptResult:
        settings = self._random_settings(overrides)
        ratings = self._normalize_ratings(active_ratings)
        self._ensure_headless_runtime()
        self._apply_character_settings(settings)

        if not self._ensure_search_results(settings):
            return HeadlessRandomPromptResult(
                success=False,
                error="Random prompt source is empty",
                random_request_id=random_request_id,
                rating_counts=self._rating_counts(),
            )

        publish = getattr(self.context, "publish", None)
        if callable(publish):
            publish("random_prompt_triggered")

        service = self._prompt_generation_service()
        preparation = service.prepare_next_source(
            self.context.search_results,
            settings,
            active_ratings=ratings,
        )
        if preparation.error:
            return HeadlessRandomPromptResult(
                success=False,
                error=preparation.error,
                random_request_id=random_request_id,
                remaining=self.context.search_results.get_count(),
                rating_counts=self._rating_counts(),
            )

        service.set_current_context(preparation.source_row, settings)
        result = service.process_current_context()
        if result.error:
            return HeadlessRandomPromptResult(
                success=False,
                error=result.error,
                random_request_id=random_request_id,
                remaining=preparation.remaining_count or 0,
                rating_counts=self._rating_counts(),
            )

        self.context.prompt_text = result.final_prompt or ""
        self.context.negative_prompt_text = str(settings.get("negative_prompt") or self.context.negative_prompt_text or "")
        if result.context is not None and callable(publish):
            publish("prompt_generated", result.context)

        return HeadlessRandomPromptResult(
            success=True,
            prompt=result.final_prompt or "",
            remaining=preparation.remaining_count or self.context.search_results.get_count(),
            rating_counts=self._rating_counts(),
            context=result.context,
            random_request_id=random_request_id,
            detected_resolution=result.detected_resolution,
            reset_resolution_detected=result.reset_resolution_detected,
        )

    def _random_settings(self, overrides: dict[str, Any] | None) -> dict[str, Any]:
        request_overrides = overrides if isinstance(overrides, dict) else {}
        option_state = self.context.get_options()
        remote_params = self.context.generation_param_schema_payload()
        auto_generate = request_overrides.get("auto_generate", option_state.get("auto_generate", False))

        settings: dict[str, Any] = {
            "prompt_fixed": bool(option_state.get("prompt_fixed", False)),
            "auto_generate": self._coerce_bool(auto_generate),
            "turbo_mode": False,
            "wildcard_standalone": bool(option_state.get("wildcard_standalone", False)),
            "auto_fit_resolution": self._coerce_bool(remote_params.get("auto_fit_resolution", False)),
            "api_mode": self.context.get_api_mode(),
            "comfyui_sampling_mode": str(
                request_overrides.get("comfyui_sampling_mode")
                or request_overrides.get("sampling_mode")
                or remote_params.get("comfyui_sampling_mode")
                or "eps"
            ),
        }
        settings.update(request_overrides)
        for key in ("prompt_fixed", "auto_generate", "wildcard_standalone", "auto_fit_resolution"):
            settings[key] = self._coerce_bool(settings.get(key, False))
        settings["api_mode"] = self.context.get_api_mode()
        return settings

    def _apply_character_settings(self, settings: dict[str, Any]) -> None:
        from core.character_settings import character_params_from_settings

        params = character_params_from_settings(
            self.context,
            mode=self.context.get_api_mode(),
            reuse_current_context=True,
        )
        if params.get("characters"):
            settings["characters"] = params["characters"]
            settings["uc"] = params.get("uc", [])

    def _prompt_generation_service(self) -> PromptGenerationService:
        service = getattr(self.context, "prompt_generation_service", None)
        if service is None:
            service = PromptGenerationService(self.context)
            self.context.prompt_generation_service = service
        return service

    def _ensure_headless_runtime(self) -> None:
        if self._runtime_registered:
            return
        self._runtime_registered = True
        self._ensure_wildcard_manager()
        self._ensure_filter_data_manager()

        from core.conditional_prompt_runtime import register_conditional_prompt_headless_runtime
        from core.prompt_engineering_runtime import register_prompt_engineering_headless_runtime
        from core.reference_inset_service import ReferenceInsetAutoInjectHook

        register_conditional_prompt_headless_runtime(self.context)
        register_prompt_engineering_headless_runtime(self.context)
        if getattr(self.context, "reference_inset_headless_hook", None) is None:
            hook = ReferenceInsetAutoInjectHook(self.context)
            self.context.register_pipeline_hook(hook.get_pipeline_hook_info(), hook)
            self.context.reference_inset_headless_hook = hook

    def _ensure_wildcard_manager(self) -> None:
        if getattr(self.context, "wildcard_manager", None) is not None:
            return
        from core.wildcard_manager import WildcardManager

        manager = WildcardManager()
        try:
            manager._app_context_ref = weakref.ref(self.context)
        except TypeError:
            pass
        self.context.wildcard_manager = manager

    def _ensure_filter_data_manager(self) -> None:
        if getattr(self.context, "filter_data_manager", None) is not None:
            return
        from core.filter_data_manager import FilterDataManager

        root = Path(getattr(self.context, "repo_root", Path.cwd()))
        self.context.filter_data_manager = FilterDataManager(str(root / "data"))

    def _ensure_search_results(self, settings: dict[str, Any]) -> bool:
        if settings.get("wildcard_standalone", False):
            return True

        if self.context.search_results is not None and not self.context.search_results.is_empty():
            return True

        snapshot = getattr(self.context, "search_results_snapshot", None)
        if snapshot is not None and not getattr(snapshot, "empty", True):
            self.context.search_results = SearchResultModel(snapshot.copy())
            print(f"🌐 Headless Remote: search_results restored from memory snapshot ({self.context.search_results.get_count()} rows)")
            return True

        for path, label in self._fallback_sources():
            if not path.exists():
                continue
            try:
                frame = pd.read_parquet(path)
                if "rating" in frame.columns and label == "fallback parquet":
                    frame = frame[frame["rating"] == "s"]
                if frame.empty:
                    continue
                frame = frame.reset_index(drop=True)
                self.context.search_results = SearchResultModel(frame)
                self.context.search_results_snapshot = frame.copy()
                print(f"🌐 Headless Remote: search_results restored from {label} ({self.context.search_results.get_count()} rows)")
                return True
            except Exception as exc:
                print(f"🌐 Headless Remote: search_results restore failed from {path} — {exc}")
        return False

    def _fallback_sources(self) -> list[tuple[Path, str]]:
        root = Path(getattr(self.context, "repo_root", Path.cwd()))
        return [
            (root / "data" / "naia_temp_rows.parquet", "temp parquet"),
            (root / "naia_temp_rows.parquet", "legacy temp parquet"),
            (root / "data" / "tags" / "tags_129.parquet", "fallback parquet"),
        ]

    def _rating_counts(self) -> dict[str, int]:
        if self.context.search_results is None:
            return {rating: 0 for rating in DEFAULT_RATINGS}
        return self.context.search_results.get_count_by_rating()

    @staticmethod
    def _normalize_ratings(ratings: set[str] | None) -> set[str]:
        try:
            values = {str(rating).strip().lower() for rating in (ratings or DEFAULT_RATINGS)}
        except TypeError:
            values = set(DEFAULT_RATINGS)
        picked = {rating for rating in DEFAULT_RATINGS if rating in values}
        return picked or set(DEFAULT_RATINGS)

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)


__all__ = ["HeadlessRandomPromptResult", "HeadlessRandomPromptService"]
