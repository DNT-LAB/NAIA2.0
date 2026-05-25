"""Server-owned Random prompt service for the headless Remote Web path."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from threading import RLock
from typing import Any
import weakref

import pandas as pd

from core.prompt_generation_service import PromptGenerationService
from core.safe_console import safe_print
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
    prompt_run_id: str = ""
    source: str = "random"
    detected_resolution: tuple[int, int] | None = None
    reset_resolution_detected: bool = False
    extra_messages: list[dict[str, Any]] = field(default_factory=list)

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
            "source": self.source or "random",
            "rating_counts": self.rating_counts or {rating: 0 for rating in DEFAULT_RATINGS},
        }
        if self.random_request_id:
            payload["random_request_id"] = self.random_request_id
            payload["requestId"] = self.random_request_id
        if self.prompt_run_id:
            payload["prompt_run_id"] = self.prompt_run_id
            payload["promptRunId"] = self.prompt_run_id
        if self.detected_resolution:
            width, height = self.detected_resolution
            payload["detected_resolution"] = {"width": width, "height": height}
            payload["resolution"] = f"{width} x {height}"
        context_metadata = getattr(self.context, "metadata", None) if self.context is not None else None
        if isinstance(context_metadata, dict):
            from core.headless_prompt_engineering_service import HeadlessPromptEngineeringService

            payload["debug_snapshot"] = HeadlessPromptEngineeringService._debug_snapshot_from_metadata(context_metadata)
        return payload


class HeadlessRandomPromptService:
    """Generate Remote Web random prompts without RemoteBridge or Qt widgets."""

    def __init__(self, context: WebSessionContext):
        self.context = context
        self._runtime_registered = False
        self._runtime_lock = RLock()

    def warmup(self) -> bool:
        """Preload the expensive headless prompt runtime without generating."""

        self._ensure_headless_runtime()
        ready = self._ensure_search_results({})
        if ready and self.context.search_results is not None:
            prime = getattr(self.context.search_results, "prime_random_cache", None)
            if callable(prime):
                prime([
                    set(DEFAULT_RATINGS),
                    {"s"},
                    {"g"},
                    {"q"},
                    {"e"},
                ])
        return ready

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

        source_row_override = None
        skip_random_events = False
        event_stream = getattr(self.context, "event_stream_runtime", None)
        if event_stream is not None and getattr(event_stream, "is_active", False):
            request = event_stream.prepare_random_prompt_request(
                self.context.search_results,
                settings,
                active_ratings=ratings,
            )
            if request.error_message:
                return HeadlessRandomPromptResult(
                    success=False,
                    error=request.error_message,
                    random_request_id=random_request_id,
                    remaining=self.context.search_results.get_count(),
                    rating_counts=self._rating_counts(),
                )
            settings = request.settings
            ratings = request.active_ratings
            source_row_override = request.source_row_override
            skip_random_events = request.skip_random_prompt_events

        tag_filter_update = None
        if source_row_override is None:
            source_row_override, tag_filter_update, tag_filter_error = self._pop_active_tag_filter_source_row(ratings)
            if tag_filter_error:
                return HeadlessRandomPromptResult(
                    success=False,
                    error=tag_filter_error,
                    random_request_id=random_request_id,
                    remaining=self.context.search_results.get_count(),
                    rating_counts=self._rating_counts(),
                )

        publish = getattr(self.context, "publish", None)
        if callable(publish) and not skip_random_events:
            publish("random_prompt_triggered")

        service = self._prompt_generation_service()
        preparation = service.prepare_next_source(
            self.context.search_results,
            settings,
            active_ratings=ratings,
            source_row_override=source_row_override,
        )
        if preparation.error:
            return HeadlessRandomPromptResult(
                success=False,
                error=preparation.error,
                random_request_id=random_request_id,
                remaining=self.context.search_results.get_count(),
                rating_counts=self._rating_counts(),
            )

        service.set_current_context(
            preparation.source_row,
            settings,
            source="random",
            request_id=random_request_id,
            metadata={"active_ratings": sorted(ratings)},
        )
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
        self.context.save_remote_ui_state()
        if result.context is not None and callable(publish):
            publish("prompt_generated", result.context)
        safe_print("Headless Remote: random prompt generated", flush=True)
        prompt_run_id = str(getattr(result.context, "metadata", {}).get("prompt_run_id") or "")

        return HeadlessRandomPromptResult(
            success=True,
            prompt=result.final_prompt or "",
            remaining=preparation.remaining_count or self.context.search_results.get_count(),
            rating_counts=self._rating_counts(),
            context=result.context,
            random_request_id=random_request_id,
            prompt_run_id=prompt_run_id,
            detected_resolution=result.detected_resolution,
            reset_resolution_detected=result.reset_resolution_detected,
            extra_messages=[tag_filter_update] if tag_filter_update else [],
        )

    def generate_from_source_row(
        self,
        source_row: Any,
        *,
        active_ratings: set[str] | None = None,
        overrides: dict[str, Any] | None = None,
        random_request_id: str = "",
        source: str = "result_reroll",
        update_context: bool = True,
    ) -> HeadlessRandomPromptResult:
        settings = self._random_settings(overrides)
        ratings = self._normalize_ratings(active_ratings)
        self._ensure_headless_runtime()
        self._apply_character_settings(settings)

        normalized_source = self._normalize_source_row(source_row)
        if normalized_source is None:
            return HeadlessRandomPromptResult(
                success=False,
                error="Reroll source is unavailable",
                random_request_id=random_request_id,
                source=source,
                rating_counts=self._rating_counts(),
            )

        saved_source = getattr(self.context, "current_source_row", None)
        saved_context = getattr(self.context, "current_prompt_context", None)
        saved_prompt = str(getattr(self.context, "prompt_text", "") or "")
        saved_negative = str(getattr(self.context, "negative_prompt_text", "") or "")

        service = self._prompt_generation_service()
        service.set_current_context(
            normalized_source,
            settings,
            source=source,
            request_id=random_request_id,
            metadata={"active_ratings": sorted(ratings), source: True},
        )
        try:
            result = service.process_current_context()
        except Exception as exc:
            if not update_context:
                self.context.current_source_row = saved_source
                self.context.current_prompt_context = saved_context
                self.context.prompt_text = saved_prompt
                self.context.negative_prompt_text = saved_negative
            return HeadlessRandomPromptResult(
                success=False,
                error=str(exc),
                random_request_id=random_request_id,
                source=source,
                rating_counts=self._rating_counts(),
            )
        if result.error:
            if not update_context:
                self.context.current_source_row = saved_source
                self.context.current_prompt_context = saved_context
                self.context.prompt_text = saved_prompt
                self.context.negative_prompt_text = saved_negative
            return HeadlessRandomPromptResult(
                success=False,
                error=result.error,
                random_request_id=random_request_id,
                source=source,
                rating_counts=self._rating_counts(),
            )

        if update_context:
            self.context.prompt_text = result.final_prompt or ""
            self.context.negative_prompt_text = str(settings.get("negative_prompt") or self.context.negative_prompt_text or "")
            self.context.save_remote_ui_state()
            publish = getattr(self.context, "publish", None)
            if result.context is not None and callable(publish):
                publish("prompt_generated", result.context)
        else:
            self.context.current_source_row = saved_source
            self.context.current_prompt_context = saved_context
            self.context.prompt_text = saved_prompt
            self.context.negative_prompt_text = saved_negative

        safe_print(f"Headless Remote: prompt regenerated from {source}", flush=True)
        prompt_run_id = str(getattr(result.context, "metadata", {}).get("prompt_run_id") or "")
        search_results = getattr(self.context, "search_results", None)
        remaining = search_results.get_count() if search_results is not None else 0
        return HeadlessRandomPromptResult(
            success=True,
            prompt=result.final_prompt or "",
            remaining=remaining,
            rating_counts=self._rating_counts(),
            context=result.context,
            random_request_id=random_request_id,
            prompt_run_id=prompt_run_id,
            source=source,
            detected_resolution=result.detected_resolution,
            reset_resolution_detected=result.reset_resolution_detected,
        )

    def _active_tag_filter_state(self) -> dict[str, Any] | None:
        tag_filter = getattr(self.context, "active_tag_filter", None)
        if isinstance(tag_filter, dict):
            return tag_filter
        ids = getattr(self.context, "active_tag_filter_ids", None)
        if ids is None:
            return None
        tag_filter = {
            "ids": set(ids),
            "count": len(ids),
            "tags": [],
            "rating_counts": {},
        }
        self.context.active_tag_filter = tag_filter
        return tag_filter

    @staticmethod
    def _normalize_tag_filter_row_id(value: Any):
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        try:
            return int(value)
        except (TypeError, ValueError):
            text = str(value or "").strip()
            return text or None

    def _pick_active_tag_filter_snapshot_row(
        self,
        active_ratings: set[str],
        ids: set[Any],
    ) -> pd.Series | None:
        snapshot = getattr(self.context, "search_results_snapshot", None)
        if snapshot is None or getattr(snapshot, "empty", True):
            snapshot = getattr(self.context, "search_results_master_base_snapshot", None)
        if snapshot is None or getattr(snapshot, "empty", True) or "id" not in snapshot.columns:
            return None

        normalized_ids = {
            normalized
            for normalized in (self._normalize_tag_filter_row_id(value) for value in ids)
            if normalized is not None
        }
        if not normalized_ids:
            return None
        frame = snapshot[
            snapshot["id"].map(self._normalize_tag_filter_row_id).isin(normalized_ids)
        ]
        if active_ratings and "rating" in frame.columns:
            frame = frame[frame["rating"].astype(str).str.strip().str.lower().isin(active_ratings)]
        if frame.empty:
            return None
        return frame.sample(n=1).iloc[0].copy()

    def _consume_active_tag_filter_row(self, tag_filter: dict[str, Any], row: pd.Series) -> bool:
        try:
            ids = tag_filter.get("ids")
            row_id = self._normalize_tag_filter_row_id(row.get("id"))
            if isinstance(ids, set):
                matched_id = None
                for candidate_id in ids:
                    if self._normalize_tag_filter_row_id(candidate_id) == row_id:
                        matched_id = candidate_id
                        break
                if matched_id is None:
                    return False
                ids.discard(matched_id)
                self.context.active_tag_filter_ids = set(ids)

            tag_filter["count"] = max(0, int(tag_filter.get("count") or 0) - 1)
            rating_counts = tag_filter.get("rating_counts")
            if isinstance(rating_counts, dict):
                rating = str(row.get("rating") or "").strip().lower()
                if rating in rating_counts:
                    rating_counts[rating] = max(0, int(rating_counts.get(rating) or 0) - 1)
            return True
        except Exception as exc:
            safe_print(f"Headless Remote: tag filter consume update failed - {exc}", flush=True)
            return False

    @staticmethod
    def _tag_filter_update_payload(tag_filter: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "type": "tag_filter_update",
            "count": int(tag_filter.get("count") or 0),
            "tags": tag_filter.get("tags") or [],
        }
        rating_counts = tag_filter.get("rating_counts")
        if isinstance(rating_counts, dict):
            payload["rating_counts"] = {
                rating: int(rating_counts.get(rating, 0) or 0)
                for rating in DEFAULT_RATINGS
            }
        return payload

    def _pop_active_tag_filter_source_row(
        self,
        active_ratings: set[str],
    ) -> tuple[pd.Series | None, dict[str, Any] | None, str]:
        tag_filter = self._active_tag_filter_state()
        if not tag_filter:
            return None, None, ""

        ids = tag_filter.get("ids")
        if not isinstance(ids, set) or not ids or int(tag_filter.get("count") or 0) <= 0:
            return None, None, "Tag filter: no matching rows"

        row = None
        search_results = getattr(self.context, "search_results", None)
        if search_results is not None and not search_results.is_empty():
            pop_with_id_filter = getattr(search_results, "pop_random_row_with_id_filter", None)
            if callable(pop_with_id_filter):
                row = pop_with_id_filter(active_ratings, ids)

        if row is None:
            row = self._pick_active_tag_filter_snapshot_row(active_ratings, ids)

        if row is None:
            return None, None, "Tag filter: no matching rows"
        if not self._consume_active_tag_filter_row(tag_filter, row):
            return None, None, "Tag filter: no matching rows"
        return row, self._tag_filter_update_payload(tag_filter), ""

    def _random_settings(self, overrides: dict[str, Any] | None) -> dict[str, Any]:
        request_overrides = overrides if isinstance(overrides, dict) else {}
        option_state = self.context.get_options()
        remote_params = self.context.generation_param_schema_payload()
        auto_generate = request_overrides.get("auto_generate", option_state.get("auto_generate", False))
        workflow_type = (
            request_overrides.get("workflow_type")
            or remote_params.get("workflow_type")
            or remote_params.get("comfyui_workflow_type")
            or ""
        )
        comfyui_sampling_mode = (
            request_overrides.get("comfyui_sampling_mode")
            or request_overrides.get("sampling_mode")
            or remote_params.get("comfyui_sampling_mode")
            or remote_params.get("sampling_mode")
            or ("bypass" if str(workflow_type).strip().lower() in {"bypass", "free"} else "eps")
        )

        settings: dict[str, Any] = {
            "prompt_fixed": bool(option_state.get("prompt_fixed", False)),
            "auto_generate": self._coerce_bool(auto_generate),
            "turbo_mode": False,
            "wildcard_standalone": bool(option_state.get("wildcard_standalone", False)),
            "auto_fit_resolution": self._coerce_bool(remote_params.get("auto_fit_resolution", False)),
            "resolution_preset_enabled": self._coerce_bool(remote_params.get("resolution_preset_enabled", False)),
            "resolution_preset": remote_params.get("resolution_preset"),
            "api_mode": self.context.get_api_mode(),
            "comfyui_sampling_mode": str(comfyui_sampling_mode),
            "workflow_type": str(workflow_type),
        }
        settings.update(request_overrides)
        for key in (
            "prompt_fixed",
            "auto_generate",
            "wildcard_standalone",
            "auto_fit_resolution",
            "resolution_preset_enabled",
        ):
            settings[key] = self._coerce_bool(settings.get(key, False))
        settings["api_mode"] = self.context.get_api_mode()
        return settings

    @staticmethod
    def _normalize_source_row(source_row: Any) -> pd.Series | None:
        if isinstance(source_row, pd.Series):
            return source_row
        if isinstance(source_row, dict):
            return pd.Series(source_row)
        to_dict = getattr(source_row, "to_dict", None)
        if callable(to_dict):
            try:
                data = to_dict()
            except Exception:
                return None
            if isinstance(data, dict):
                return pd.Series(data)
        return None

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
        with self._runtime_lock:
            if self._runtime_registered:
                return
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
            self._runtime_registered = True

    def _ensure_wildcard_manager(self) -> None:
        if getattr(self.context, "wildcard_manager", None) is not None:
            return
        from core.wildcard_manager import WildcardManager

        runtime_paths = getattr(self.context, "runtime_paths", None)
        use_runtime_wildcards = bool(os.environ.get("NAIA_USER_DATA_DIR") or os.environ.get("NAIA_PORTABLE"))
        wildcards_dir = (
            getattr(runtime_paths, "wildcards_dir", None)
            if runtime_paths is not None and use_runtime_wildcards
            else None
        )
        manager = WildcardManager(wildcards_dir=wildcards_dir)
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
        data_root = root / "data"
        fallback_data_roots: list[str] = []
        runtime_paths = getattr(self.context, "runtime_paths", None)
        if runtime_paths is not None:
            data_root = runtime_paths.data_dir
            for candidate in (runtime_paths.resource_path("data"), root / "data"):
                if candidate.exists() and candidate.resolve() != data_root.resolve():
                    fallback_data_roots.append(str(candidate))
        self.context.filter_data_manager = FilterDataManager(
            str(data_root),
            fallback_data_dirs=fallback_data_roots,
        )

    def _ensure_search_results(self, settings: dict[str, Any]) -> bool:
        if settings.get("wildcard_standalone", False):
            return True

        if self.context.search_results is not None and not self.context.search_results.is_empty():
            return True

        snapshot = getattr(self.context, "search_results_snapshot", None)
        if snapshot is not None and not getattr(snapshot, "empty", True):
            self.context.search_results = SearchResultModel(snapshot.copy())
            safe_print(f"🌐 Headless Remote: search_results restored from memory snapshot ({self.context.search_results.get_count()} rows)")
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
                safe_print(f"🌐 Headless Remote: search_results restored from {label} ({self.context.search_results.get_count()} rows)")
                return True
            except Exception as exc:
                safe_print(f"🌐 Headless Remote: search_results restore failed from {path} — {exc}")
        return False

    def _fallback_sources(self) -> list[tuple[Path, str]]:
        sources = getattr(self.context, "runner_parquet_sources", None)
        if callable(sources):
            return sources()
        root = Path(getattr(self.context, "repo_root", Path.cwd()))
        return [
            (root / "data" / "naia_temp_rows.parquet", "legacy data parquet"),
            (root / "naia_temp_rows.parquet", "legacy temp parquet"),
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
