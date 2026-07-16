"""Server-owned Random prompt service for the headless Remote Web path."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
import os
from pathlib import Path
from threading import Lock, RLock
from typing import Any
import weakref

import pandas as pd

from core.headless_search_state_service import DEFAULT_ACTIVE_RATINGS
from core.prompt_generation_service import PromptGenerationService
from core.safe_console import safe_print
from core.search_result_model import SearchResultModel
from core.web_session_context import WebSessionContext


DEFAULT_RATINGS = ("g", "s", "q", "e")

# Guards the lazy creation of the per-context search-pool load lock so a warmup
# thread and an early client thread can't each mint a *different* lock (which
# would defeat the serialization and start duplicate large parquet reads).
_SEARCH_POOL_LOCK_CREATE_GUARD = Lock()


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
        # announce=True: stream chunk progress so a large startup pool shows the
        # Tag/Tag-Filter lock + '풀 로딩 N%' instead of a silent stall.
        ready = self._ensure_search_results({}, announce=True)
        if ready and self.context.search_results is not None:
            prime = getattr(self.context.search_results, "prime_random_cache", None)
            if callable(prime):
                prime([
                    set(DEFAULT_ACTIVE_RATINGS),
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
        source_row_override: Any = None,
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

        # source_row_override(외부 주입 = 프리페치 오버랩이 예약해 둔 행)가 있으면 story/
        # tag-filter 산정과 풀 pop을 건너뛴다 — 프리페치는 일반 Auto Gen 한정이라 story/
        # tag-filter가 없는 경우에만 호출된다. 그 외 모든 부작용(random_prompt_triggered·
        # prepare_next_source[override 분기, pop 없음]·publish prompt_generated)은 그대로 수행.
        skip_random_events = False
        stream_messages: list[dict[str, Any]] = []
        # 1.5 모델: 스트림이 활성인 동안 모든 랜덤(수동 포함)이 시퀀스를 전진시킨다 —
        # 사용자는 마음에 드는 이미지가 나올 때까지 수동으로 라운드를 반복할 수 있다.
        event_stream = getattr(self.context, "event_stream_runtime", None)
        if source_row_override is None and event_stream is not None and getattr(event_stream, "is_active", False):
            request = event_stream.prepare_random_prompt_request(
                self.context.search_results,
                settings,
                active_ratings=ratings,
            )
            # Use Vibe 인코딩 성공/실패 토스트(런타임은 직접 브로드캐스트 불가) — 어느
            # 분기로 끝나든 extra_messages로 실어 보낸다.
            consume_vibe = getattr(event_stream, "consume_vibe_messages", None)
            if callable(consume_vibe):
                stream_messages = list(consume_vibe() or [])
            if request.error_message:
                return HeadlessRandomPromptResult(
                    success=False,
                    error=request.error_message,
                    random_request_id=random_request_id,
                    remaining=self.context.search_results.get_count(),
                    rating_counts=self._rating_counts(),
                    extra_messages=stream_messages,
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
                    extra_messages=stream_messages,
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
                extra_messages=stream_messages,
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
                extra_messages=stream_messages,
            )

        self.context.prompt_text = result.final_prompt or ""
        self.context.negative_prompt_text = self._resolve_negative_prompt(settings)
        self.context.save_remote_ui_state()
        if result.context is not None and callable(publish):
            publish("prompt_generated", result.context)
        safe_print("Headless Remote: random prompt generated", flush=True)
        prompt_run_id = str(getattr(result.context, "metadata", {}).get("prompt_run_id") or "")

        extra_messages = stream_messages + ([tag_filter_update] if tag_filter_update else [])
        skip_message = self._conditional_character_skip_message(result.context)
        if skip_message:
            extra_messages.append(skip_message)

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
            extra_messages=extra_messages,
        )

    @staticmethod
    def _conditional_character_skip_message(prompt_context: Any) -> dict[str, Any] | None:
        """Surface silently-dropped conditional character targets (bug [2] hardening).

        Conditional rules like char:N+=tag / uc:N= aimed at an inactive/cold/missing
        slot are dropped without effect; without this the user sees nothing. Emit a
        warning toast (the 'toast' WS type is already handled in app.js).
        """
        metadata = getattr(prompt_context, "metadata", None)
        if not isinstance(metadata, dict):
            return None
        skips = metadata.get("conditional_character_skips") or []
        targets = [
            str(skip.get("target"))
            for skip in skips
            if isinstance(skip, dict) and skip.get("target")
        ]
        if not targets:
            return None
        joined = ", ".join(dict.fromkeys(targets))
        return {
            "type": "toast",
            "level": "warning",
            "message": f"조건부 규칙이 비활성/없는 캐릭터 슬롯을 대상으로 해 적용되지 않았습니다: {joined}",
        }

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
            self.context.negative_prompt_text = self._resolve_negative_prompt(settings)
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

    def reserve_next_random_row(self, active_ratings: set[str] | None = None) -> Any:
        """프리페치 오버랩용 — 다음 랜덤 행을 풀에서 pop해 반환(부작용: 풀 advance만).

        None이면 풀이 비었거나 준비 안 됨. **폐기(무효화) 시 되돌리지 않고 버린다** —
        대형 풀에서 1행 손실은 무시 가능하며 검색 스냅샷 자동복원이 백스톱이다. 활성
        태그필터에서는 호출하지 않는다(필터 카운트 누수 방지 — 호출부에서 가드).
        """
        try:
            settings = self._random_settings(None)
            if settings.get("wildcard_standalone", False):
                return None
            if not self._ensure_search_results(settings):
                return None
            sr = getattr(self.context, "search_results", None)
            if sr is None:
                return None
            return sr.pop_random_row(self._normalize_ratings(active_ratings))
        except Exception:
            return None

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
            marker = getattr(self.context, "mark_tag_filter_changed", None)
            if callable(marker):
                marker()
            else:
                self.context._tag_filter_revision = int(
                    getattr(self.context, "_tag_filter_revision", 0) or 0
                ) + 1
            return True
        except Exception as exc:
            safe_print(f"Headless Remote: tag filter consume update failed - {exc}", flush=True)
            return False

    def _tag_filter_update_payload(self, tag_filter: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "type": "tag_filter_update",
            "tag_filter_revision": int(getattr(self.context, "_tag_filter_revision", 0) or 0),
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
        guard = getattr(self.context, "search_pool_state_guard", None)
        with guard() if callable(guard) else nullcontext():
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

    def _resolve_negative_prompt(self, settings: dict[str, Any]) -> str:
        """Resolve the session negative after a roll.

        An EXPLICIT negative override in ``settings`` wins even when it is empty:
        the Auto Gen continuation grounds each iteration on the PRISTINE base
        negative (empty for users with no negative box), so a truthiness ``or``
        fallback to ``context.negative_prompt_text`` would re-inject the previous
        iteration's conditionally-merged value and restart the accumulation
        (Codex review BLOCKER). Only fall back to the current session value when
        the caller supplied no ``negative_prompt`` key at all (e.g. a plain manual
        Random that does not carry the field).
        """
        if isinstance(settings, dict) and "negative_prompt" in settings:
            return str(settings.get("negative_prompt") or "")
        return str(self.context.negative_prompt_text or "")

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
        from core.character_settings import (
            read_character_roll_snapshot,
            read_reroll_on_generate,
            roll_character_params,
        )

        # SSOT character roll. There is exactly ONE roll at runtime:
        # context._character_roll_snapshot[MODE]. Random, the Refresh Preview button,
        # and Generate are the only authoritative writers; state reads never re-roll.
        #
        # reroll_on_generate ("Process wildcards on Generate"):
        #   - False (default): RANDOM rolls the character wildcards ONCE here and
        #     stores the snapshot; Generate then reuses the snapshot (no re-roll).
        #   - True: RANDOM does NOT touch the character wildcards (snapshot stays);
        #     Generate re-rolls once and updates the snapshot.
        # Either way we ALWAYS publish the (just-rolled or reused) snapshot into
        # settings["characters"]/["uc"] so the random prompt + Ollama boost ground
        # on exactly the same characters Generate will use. The override-first and
        # active-frame checks live inside character_params_from_settings/roll_*, so a
        # disabled module / active conditional override is honored here too:
        #   - disabled / no active frames → returns no characters → settings left
        #     untouched (no stale characters grounded),
        #   - an active conditional override is returned as-is and not persisted.
        #
        # A NEW prompt run must derive the character base from the PRISTINE character
        # frames, not the previous run's conditional result. Drop the stale conditional
        # override first so a rule like `char:1+=__wc__` does not re-append every run.
        self._clear_conditional_character_override()
        # Drop legacy Ollama freeze field — superseded by the SSOT snapshot.
        self.context._ollama_frozen_character_params = None

        mode = self.context.get_api_mode()
        reroll_on_generate = read_reroll_on_generate(self.context, mode)

        if reroll_on_generate:
            # Roll deferred to Generate — reuse the existing snapshot (if any) for
            # the random prompt / boost grounding; do NOT advance the roll here and
            # do NOT create one if absent (Generate makes the first roll).
            snapshot = read_character_roll_snapshot(self.context, mode)
            if snapshot is not None:
                settings["characters"] = list(snapshot.get("characters") or [])
                settings["uc"] = list(snapshot.get("uc") or [])
                settings["character_ids"] = list(snapshot.get("character_ids") or [])
            return

        # reroll_on_generate is False → Random is the authoritative roll. roll_*
        # short-circuits on an inactive module / active conditional override, rolls
        # once otherwise, and stores the mode-keyed snapshot. reuse_current_context=
        # True keeps character-prompt wildcards sharing the main prompt's sequential/
        # dependent counters (general random wildcards don't advance any counter),
        # expanding from the pristine frame base.
        params = roll_character_params(
            self.context,
            mode=mode,
            reuse_current_context=True,
        )
        if params.get("characters"):
            settings["characters"] = list(params.get("characters") or [])
            settings["uc"] = list(params.get("uc") or [])
            settings["character_ids"] = list(params.get("character_ids") or [])

    def _clear_conditional_character_override(self) -> None:
        context = getattr(self.context, "current_prompt_context", None)
        metadata = getattr(context, "metadata", None)
        if isinstance(metadata, dict):
            metadata.pop("conditional_character_overrides", None)
            metadata.pop("_conditional_character_slots", None)
            metadata.pop("conditional_character_skips", None)

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

    def _search_pool_load_lock(self):
        # Serialize disk restores so the startup warmup and a client's
        # get_search_state don't both read the (large) pool parquet at once.
        # Double-checked creation under a module guard so racing threads share
        # the SAME lock (a plain check-then-set could mint two).
        lock = getattr(self.context, "_search_pool_load_lock_obj", None)
        if lock is None:
            with _SEARCH_POOL_LOCK_CREATE_GUARD:
                lock = getattr(self.context, "_search_pool_load_lock_obj", None)
                if lock is None:
                    lock = Lock()
                    self.context._search_pool_load_lock_obj = lock
        return lock

    def _ensure_search_results(self, settings: dict[str, Any], *, announce: bool = False) -> bool:
        if settings.get("wildcard_standalone", False):
            return True

        if self.context.search_results is not None and not self.context.search_results.is_empty():
            return True

        snapshot = getattr(self.context, "search_results_snapshot", None)
        if snapshot is not None and not getattr(snapshot, "empty", True):
            self.context.search_results = SearchResultModel(snapshot.copy())
            safe_print(f"🌐 Headless Remote: search_results restored from memory snapshot ({self.context.search_results.get_count()} rows)")
            return True

        # Disk restore — serialized. ``announce`` streams chunk progress to the
        # Remote Web clients (Tag/Tag-Filter lock + '풀 로딩 N%') so a large temp
        # pool no longer stalls startup as one opaque wait.
        with self._search_pool_load_lock():
            if self.context.search_results is not None and not self.context.search_results.is_empty():
                return True
            snapshot = getattr(self.context, "search_results_snapshot", None)
            if snapshot is not None and not getattr(snapshot, "empty", True):
                self.context.search_results = SearchResultModel(snapshot.copy())
                safe_print(f"🌐 Headless Remote: search_results restored from memory snapshot ({self.context.search_results.get_count()} rows)")
                return True

            from core.parquet_chunk_loader import read_parquet_chunked

            def _new_progress():
                # A FRESH announce lifecycle per read source: the silent/announced
                # decision is made from each source's own row count, so a tiny
                # invalid last-search file can't suppress the progress/lock for a
                # subsequent large fallback in the same restore attempt.
                if not announce:
                    return None, None
                from core.parquet_chunk_loader import make_search_load_progress

                return make_search_load_progress(self.context)

            # 마지막 검색(작업 데이터셋) 복원 (Part 3) — runner 캐시보다 우선이며, 태그필터가 영속돼
            # 있어도 무조건 복원한다(이건 사용자의 실제 마지막 *원본* 데이터셋이라 _should_skip_fallback
            # 대상이 아님; 풀 등급/태그필터는 복원 위에 재적용된다). 재시작/가져오기 후에도 데이터가
            # 살아 있어 빈 풀/빈 매치 라벨 레이스(Codex 잔여)도 함께 해소된다.
            progress, done = _new_progress()
            try:
                if self.context.restore_last_search(progress=progress):
                    safe_print(f"🌐 Headless Remote: search_results restored from last-search cache ({self.context.search_results.get_count()} rows)")
                    return True
            finally:
                if done is not None:
                    done()

            for path, label in self._fallback_sources():
                if not path.exists():
                    continue
                if self._should_skip_fallback_source(label, None):
                    continue
                progress, done = _new_progress()
                try:
                    frame = read_parquet_chunked(path, progress=progress)
                    if self._should_skip_fallback_source(label, frame):
                        continue
                    if "rating" in frame.columns and label == "fallback parquet":
                        frame = frame[frame["rating"] == "s"]
                    if frame.empty:
                        continue
                    frame = frame.reset_index(drop=True)
                    guard = getattr(self.context, "search_pool_state_guard", None)
                    with guard() if callable(guard) else nullcontext():
                        self.context.search_results = SearchResultModel(frame)
                        self.context.search_results_snapshot = frame.copy()
                        if "tag archive" in label:
                            self.context.search_results_scope = "tag_archive"
                        marker = getattr(self.context, "mark_search_pool_replaced", None)
                        if callable(marker):
                            marker()
                    safe_print(f"🌐 Headless Remote: search_results restored from {label} ({self.context.search_results.get_count()} rows)")
                    return True
                except Exception as exc:
                    safe_print(f"🌐 Headless Remote: search_results restore failed from {path} — {exc}")
                finally:
                    if done is not None:
                        done()
            return False

    def _should_skip_fallback_source(self, label: str, frame: Any | None) -> bool:
        if label not in {
            "runtime cache parquet",
            "runtime data parquet",
            "legacy data parquet",
            "legacy temp parquet",
        }:
            return False
        state = self.context.normalize_search_filter_state(getattr(self.context, "search_filter_state", None))
        if state.get("query") or state.get("exclude") or state.get("tag_filter_active"):
            return True
        if frame is not None and "id" not in getattr(frame, "columns", []):
            sources = getattr(self.context, "tag_archive_parquet_sources", None)
            if callable(sources) and sources():
                return True
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
            values = {str(rating).strip().lower() for rating in (ratings or DEFAULT_ACTIVE_RATINGS)}
        except TypeError:
            values = set(DEFAULT_ACTIVE_RATINGS)
        picked = {rating for rating in DEFAULT_RATINGS if rating in values}
        return picked or set(DEFAULT_ACTIVE_RATINGS)

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
