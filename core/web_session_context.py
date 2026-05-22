"""PyQt-free service container for the Remote Web headless runtime.

This module is the Round 31 skeleton for the headless Web Session migration.
It intentionally does not import the desktop application, RemoteBridge, or
Qt-backed controllers. Later rounds can move FastAPI and generation behavior
onto this container incrementally while the desktop-backed WebShell remains
available as a compatibility path.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Protocol
import weakref
import base64
import hashlib
import io
import os
import re
import json

from core import result_image_payload_service as result_images
from core.api_config_service import ApiConfigService, CloudflaredService
from core.headless_result_service import HeadlessResultStore
from core.pipeline_run_registry import PipelineRunRegistry, PromptPipelineRun
from app.backend.runtime import RuntimePaths, resolve_runtime_paths
from core.search_result_model import SearchResultModel


SUPPORTED_API_MODES = ("NAI", "WEBUI", "COMFYUI")
REMOTE_OPTION_DEFAULTS = {
    "prompt_fixed": False,
    "auto_generate": False,
    "wildcard_standalone": False,
    "auto_save": False,
}
SUPPORTED_RATINGS = ("g", "s", "q", "e")
REMOTE_BOOLEAN_PARAMS = {
    "seed_fixed",
    "random_resolution",
    "auto_fit_resolution",
    "enable_hr",
    "resolution_preset_enabled",
    "webui_hiresfix_assist",
    "webui_hiresfix_assist_enabled",
    "SMEA",
    "DYN",
    "VAR+",
    "DECRISP",
}
REMOTE_INT_PARAMS = {
    "steps",
    "hires_steps",
    "width",
    "height",
    "webui_hiresfix_assist_target",
}
REMOTE_FLOAT_PARAMS = {
    "cfg_scale",
    "cfg_rescale",
    "hr_scale",
    "denoising_strength",
    "hr_cfg",
    "rescale_cfg",
}
AUTO_SAVE_DEFAULTS = {
    "auto_save": False,
    "save_as_webp": False,
    "history_limit_enabled": False,
    "max_history_length": 2000,
    "memory_action": 1,
}
AUTO_SAVE_MEMORY_ACTION_OPTIONS = [
    {"value": 1, "label": "[1] 1장씩 자동저장+정리"},
    {"value": 2, "label": "[2] 1장씩 저장없이 삭제"},
    {"value": 3, "label": "[3] 자동생성 중단"},
]
SAVE_DIRECTORY_FILENAME_OPTIONS = [
    {"value": "number_only", "label": "번호만 (00001.png)"},
    {"value": "time_number", "label": "시간_번호 (143052_00001.png)"},
    {"value": "datetime", "label": "날짜_시간 (20250108_143052.png)"},
    {"value": "prompt", "label": "프롬프트 (prompt.png)"},
    {"value": "wildcard", "label": "와일드카드 (wildcard.png)"},
]
SAVE_DIRECTORY_CLASSIFICATION_OPTIONS = [
    {"value": "none", "label": "분류 없음"},
    {"value": "prompt_recognition", "label": "프롬프트 인식"},
]
HEADLESS_RETIRED_MODULES = {
    "wildcard_status": "Wildcard Status desktop wrapper is retired in the supported headless runtime.",
    "ollama": "Ollama desktop assistant controls are retired in the supported headless runtime.",
}
HIRES_OVERLAY_DISALLOWED_NAMES = {"", "*randomized", "(프리셋 없음)"}


class TokenStore(Protocol):
    def get_token(self, service_key: str) -> str:
        ...

    def save_token(self, service_key: str, token: str) -> None:
        ...

    def delete_token(self, service_key: str) -> bool:
        ...


class InMemoryTokenManager:
    """Small token store for tests and non-persistent headless scaffolding."""

    def __init__(self, values: dict[str, str] | None = None):
        self._values = dict(values or {})

    def get_token(self, service_key: str) -> str:
        return str(self._values.get(service_key) or "")

    def save_token(self, service_key: str, token: str) -> None:
        if token:
            self._values[service_key] = str(token)

    def delete_token(self, service_key: str) -> bool:
        self._values.pop(service_key, None)
        return True


class WebSessionEventBus:
    """Minimal AppContext-compatible event bus without Qt signal objects."""

    def __init__(self):
        self._subscribers: dict[str, list[Callable[..., Any]]] = defaultdict(list)
        self._lock = RLock()

    @property
    def subscribers(self) -> dict[str, list[Callable[..., Any]]]:
        return self._subscribers

    def subscribe(self, event_name: str, callback: Callable[..., Any]) -> None:
        with self._lock:
            if callback not in self._subscribers[event_name]:
                self._subscribers[event_name].append(callback)

    def unsubscribe(self, event_name: str, callback: Callable[..., Any]) -> None:
        with self._lock:
            callbacks = self._subscribers.get(event_name)
            if not callbacks:
                return
            self._subscribers[event_name] = [cb for cb in callbacks if cb is not callback]
            if not self._subscribers[event_name]:
                self._subscribers.pop(event_name, None)

    def publish(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        with self._lock:
            callbacks = list(self._subscribers.get(event_name, ()))
        for callback in callbacks:
            callback(*args, **kwargs)


@dataclass
class AutocompleteRuntimeState:
    kr_tags_loaded: bool = False
    metadata_fallback_ready: bool = False
    translation_cache_size: int = 0
    result_cache_size: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "kr_tags_loaded": bool(self.kr_tags_loaded),
            "metadata_fallback": {
                "ready": bool(self.metadata_fallback_ready),
                "live_path_allows_build": False,
            },
            "translation_cache_size": int(self.translation_cache_size),
            "result_cache_size": int(self.result_cache_size),
        }


@dataclass
class WebSessionContext:
    """Headless state owner for Remote Web startup and shared status.

    The container deliberately exposes several AppContext-shaped attributes and
    methods so core services can migrate one by one without depending on a
    ``ModernMainWindow`` instance.
    """

    token_manager: TokenStore | None = None
    repo_root: Path | str | None = None
    runtime_paths: RuntimePaths | None = None
    event_bus: WebSessionEventBus = field(default_factory=WebSessionEventBus)
    current_api_mode: str = "NAI"
    is_generating: bool = False
    cloudflared_active: bool = False
    cloudflared_tunnel_url: str = ""
    cloudflared_status_text: str = ""
    prompt_text: str = ""
    negative_prompt_text: str = ""
    remote_options: dict[str, bool] = field(default_factory=lambda: dict(REMOTE_OPTION_DEFAULTS))
    remote_params: dict[str, Any] = field(default_factory=dict)
    autocomplete_state: AutocompleteRuntimeState = field(default_factory=AutocompleteRuntimeState)
    desktop_adapter: Any = None
    api_config_service: ApiConfigService | None = None
    wildcard_manager: Any = None
    tag_data_manager: Any = None
    filter_data_manager: Any = None
    search_results: SearchResultModel = field(default_factory=SearchResultModel)
    search_results_snapshot: Any = None
    current_source_row: Any = None
    current_prompt_context: Any = None
    pipeline_run_registry: PipelineRunRegistry = field(default_factory=PipelineRunRegistry)
    result_store: HeadlessResultStore = field(default_factory=HeadlessResultStore)
    headless_generation_execute_enabled: bool = True
    auto_save_state: dict[str, Any] = field(default_factory=dict)
    save_directory_state: dict[str, Any] = field(default_factory=dict)
    webui_hiresfix_assist_state: dict[str, Any] = field(default_factory=dict)
    character_reference_frames: list[dict[str, Any]] = field(default_factory=list)
    vibe_transfer_frames: list[dict[str, Any]] = field(default_factory=list)
    vibe_transfer_normalize: bool = False
    img2img_session: dict[str, Any] = field(default_factory=dict)
    result_enhance_config: dict[str, Any] = field(default_factory=lambda: {
        "upscale": 1.5,
        "strength": 0.2,
        "noise": 0.0,
    })
    _img2img_window_counter: int = 0
    _headless_img2img_service: Any = field(default=None, init=False, repr=False)
    _headless_character_reference_service: Any = field(default=None, init=False, repr=False)
    _headless_vibe_transfer_service: Any = field(default=None, init=False, repr=False)
    _headless_automation_service: Any = field(default=None, init=False, repr=False)
    _headless_webui_hiresfix_assist_service: Any = field(default=None, init=False, repr=False)
    _headless_event_stream_service: Any = field(default=None, init=False, repr=False)
    _headless_prompt_engineering_service: Any = field(default=None, init=False, repr=False)
    _headless_conditional_prompt_service: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.token_manager is None:
            self.token_manager = self._default_token_manager()
        self.secure_token_manager = self.token_manager
        explicit_repo_root = self.repo_root is not None
        self.repo_root = Path(self.repo_root) if explicit_repo_root else Path(__file__).resolve().parent.parent
        if self.runtime_paths is None:
            self.runtime_paths = resolve_runtime_paths(self.repo_root, portable=explicit_repo_root)
        self.runtime_paths.ensure_writable_dirs()
        self.main_window = None
        self.middle_section_controller = None
        self.remote_bridge = None
        self.api_service = None
        self.temp_window_mode = False
        self.temp_window_character_tab = None
        self.session_p_eng_override = None
        self.scoped_wildcard = None
        self.search_filter_state = self._load_search_filter_state()
        self.remote_active_ratings = set(self.search_filter_state.get("ratings") or SUPPORTED_RATINGS)
        self.active_tag_filter_ids: set[Any] | None = None
        self.pending_tag_filter: dict[str, Any] | None = None
        self.depth_state: dict[str, Any] | None = None
        self.wildcard_override: dict[str, Any] = {}
        if os.environ.get("NAIA_HEADLESS_DISABLE_GENERATION_EXECUTION") == "1":
            self.headless_generation_execute_enabled = False
        self.prompt_squeeze_enabled = False
        self.pipeline_hooks: dict[str, dict[str, list[tuple[int, Any]]]] = {}
        self.session_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.subscribers = self.event_bus.subscribers
        if self.wildcard_manager is not None and getattr(self.wildcard_manager, "_app_context_ref", None) is None:
            try:
                self.wildcard_manager._app_context_ref = weakref.ref(self)
            except TypeError:
                pass
        if self.api_config_service is None:
            cloudflared_bin_dir = (
                self.runtime_paths.downloads_dir / "cloudflared"
                if self.runtime_paths is not None else None
            )
            cloudflared = CloudflaredService(
                port=self.remote_params.get("web_session_port", 7243),
                bin_dir=cloudflared_bin_dir,
            )
            cloudflared.set_status(
                active=self.cloudflared_active,
                url=self.cloudflared_tunnel_url,
                status_text=self.cloudflared_status_text,
            )
            timestamp_path = (
                self.runtime_paths.config_dir / "NAIA_api_timestamps.json"
                if self.runtime_paths is not None else None
            )
            self.api_config_service = ApiConfigService(
                self.secure_token_manager,
                cloudflared=cloudflared,
                **({"timestamp_path": timestamp_path} if timestamp_path is not None else {}),
            )
        self.generation_queue_manager = self._create_queue_manager()
        self.last_api_payloads: dict[str, Any] = {}
        self.event_stream_runtime = self._create_event_stream_runtime()

    def _create_event_stream_runtime(self):
        try:
            from core.event_tree import EventStreamRuntime

            return EventStreamRuntime(self)
        except Exception:
            return None

    def _img2img_service(self):
        service = self._headless_img2img_service
        if service is None:
            from core.headless_img2img_service import HeadlessImg2ImgService

            service = HeadlessImg2ImgService(self)
            self._headless_img2img_service = service
        return service

    def _character_reference_service(self):
        service = self._headless_character_reference_service
        if service is None:
            from core.headless_character_reference_service import HeadlessCharacterReferenceService

            service = HeadlessCharacterReferenceService(self)
            self._headless_character_reference_service = service
        return service

    def _vibe_transfer_service(self):
        service = self._headless_vibe_transfer_service
        if service is None:
            from core.headless_vibe_transfer_service import HeadlessVibeTransferService

            service = HeadlessVibeTransferService(self)
            self._headless_vibe_transfer_service = service
        return service

    def _automation_service(self):
        service = self._headless_automation_service
        if service is None:
            from core.headless_automation_service import HeadlessAutomationService

            service = HeadlessAutomationService(self)
            self._headless_automation_service = service
        return service

    def _webui_hiresfix_assist_service(self):
        service = self._headless_webui_hiresfix_assist_service
        if service is None:
            from core.headless_webui_hiresfix_assist_service import HeadlessWebuiHiresfixAssistService

            service = HeadlessWebuiHiresfixAssistService(self)
            self._headless_webui_hiresfix_assist_service = service
        return service

    def _event_stream_service(self):
        service = self._headless_event_stream_service
        if service is None:
            from core.headless_event_stream_service import HeadlessEventStreamService

            service = HeadlessEventStreamService(self)
            self._headless_event_stream_service = service
        return service

    def _prompt_engineering_service(self):
        service = self._headless_prompt_engineering_service
        if service is None:
            from core.headless_prompt_engineering_service import HeadlessPromptEngineeringService

            service = HeadlessPromptEngineeringService(self)
            self._headless_prompt_engineering_service = service
        return service

    def _conditional_prompt_service(self):
        service = self._headless_conditional_prompt_service
        if service is None:
            from core.headless_conditional_prompt_service import HeadlessConditionalPromptService

            service = HeadlessConditionalPromptService(self)
            self._headless_conditional_prompt_service = service
        return service

    def _default_token_manager(self) -> TokenStore:
        from core.secure_token_manager import SecureTokenManager

        return SecureTokenManager()

    def _create_queue_manager(self):
        from core.generation_queue_manager import GenerationQueueManager

        return GenerationQueueManager(self)

    def subscribe(self, event_name: str, callback: Callable[..., Any]) -> None:
        self.event_bus.subscribe(event_name, callback)

    def unsubscribe(self, event_name: str, callback: Callable[..., Any]) -> None:
        self.event_bus.unsubscribe(event_name, callback)

    def publish(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        self.event_bus.publish(event_name, *args, **kwargs)

    def register_pipeline_hook(self, hook_info: dict, module_instance: Any) -> None:
        pipeline_name = hook_info.get("target_pipeline")
        hook_point = hook_info.get("hook_point")
        if not pipeline_name or not hook_point:
            return
        priority = int(hook_info.get("priority", 999) or 999)
        hooks = self.pipeline_hooks.setdefault(pipeline_name, {}).setdefault(hook_point, [])
        hooks.append((priority, module_instance))
        hooks.sort(key=lambda item: item[0])

    def get_pipeline_hooks(self, pipeline_name: str, hook_point: str) -> list[Any]:
        hooks = self.pipeline_hooks.get(pipeline_name, {}).get(hook_point, [])
        return [module_instance for _, module_instance in hooks]

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
        return self.pipeline_run_registry.start_prompt_run(
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
        return self.pipeline_run_registry.complete_prompt_run(
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
        return self.pipeline_run_registry.fail_prompt_run(
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
        return self.pipeline_run_registry.record_hook(
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
        return self.pipeline_run_registry.record_warning(prompt_run_id, warning)

    def record_prompt_run_derived(
        self,
        prompt_run_id: str,
        derived: dict[str, Any] | None,
    ) -> PromptPipelineRun | None:
        return self.pipeline_run_registry.record_derived(prompt_run_id, derived)

    def link_generation_to_prompt_run(
        self,
        prompt_run_id: str,
        generation_request_id: str,
    ) -> PromptPipelineRun | None:
        return self.pipeline_run_registry.link_generation_request(
            prompt_run_id,
            generation_request_id,
        )

    def get_prompt_run_payload(self, prompt_run_id: str, *, include_source_row: bool = False) -> dict[str, Any] | None:
        run = self.pipeline_run_registry.get_prompt_run(prompt_run_id)
        if run is None:
            return None
        return run.to_payload(include_source_row=include_source_row)

    def prompt_runs_payload(self, limit: int = 50) -> dict[str, Any]:
        return {
            "type": "pipeline_runs",
            "prompt_runs": self.pipeline_run_registry.list_prompt_runs(limit),
        }

    def get_api_mode(self) -> str:
        return self.current_api_mode

    def set_api_mode(self, mode: str) -> None:
        normalized = str(mode or "").strip().upper()
        if normalized not in SUPPORTED_API_MODES:
            return
        if normalized == self.current_api_mode:
            return
        old_mode = self.current_api_mode
        self.current_api_mode = normalized
        self.publish("api_mode_changed", {"old_mode": old_mode, "new_mode": normalized})

    def set_option(self, key: str, value: Any) -> None:
        if key not in REMOTE_OPTION_DEFAULTS:
            return
        self.remote_options[key] = bool(value)
        if key == "auto_save":
            self.auto_save_state["auto_save"] = bool(value)
        self.publish("remote_options_changed", self.get_options())

    def get_options(self) -> dict[str, bool]:
        options = dict(REMOTE_OPTION_DEFAULTS)
        options.update({key: bool(value) for key, value in self.remote_options.items() if key in options})
        return options

    def set_param(self, key: str, value: Any) -> None:
        clean_key = str(key or "").strip()
        if not clean_key:
            return
        self.remote_params[clean_key] = self._coerce_remote_param(clean_key, value)
        self.publish("remote_params_changed", self.generation_param_schema_payload())

    def set_active_ratings(self, ratings: Any) -> set[str]:
        if isinstance(ratings, str):
            ratings = list(ratings)
        if not isinstance(ratings, (list, tuple, set)):
            normalized = set(SUPPORTED_RATINGS)
        else:
            normalized = {
                str(item).strip().lower()
                for item in ratings
                if str(item).strip().lower() in SUPPORTED_RATINGS
            }
            if not normalized:
                normalized = set(SUPPORTED_RATINGS)
        self.remote_active_ratings = normalized
        self.publish("remote_active_ratings_changed", self.search_state_payload())
        return normalized

    def get_active_ratings(self) -> set[str]:
        ratings = self.remote_active_ratings
        if not ratings:
            return set(SUPPORTED_RATINGS)
        return {rating for rating in SUPPORTED_RATINGS if rating in ratings} or set(SUPPORTED_RATINGS)

    def _save_root(self) -> Path:
        return self.runtime_paths.save_dir if self.runtime_paths is not None else Path(self.repo_root) / "save"

    def _output_root(self) -> Path:
        return self.runtime_paths.output_dir if self.runtime_paths is not None else Path(self.repo_root) / "output"

    def _legacy_save_root(self) -> Path:
        return Path(self.repo_root) / "save"

    def _legacy_save_fallback_enabled(self) -> bool:
        if os.environ.get("NAIA_DISABLE_LEGACY_SAVE_FALLBACK") == "1":
            return False
        if os.environ.get("NAIA_ELECTRON") == "1":
            return False
        return True

    def _save_path(self, *parts: str | Path) -> Path:
        path = self._save_root()
        for part in parts:
            path = path / part
        return path

    def _legacy_save_path(self, *parts: str | Path) -> Path:
        path = self._legacy_save_root()
        for part in parts:
            path = path / part
        return path

    def _existing_save_path(self, *parts: str | Path) -> Path:
        primary = self._save_path(*parts)
        if primary.exists():
            return primary
        if not self._legacy_save_fallback_enabled():
            return primary
        legacy = self._legacy_save_path(*parts)
        if legacy.exists():
            return legacy
        return primary

    def _existing_save_dirs(self, *parts: str | Path) -> list[Path]:
        dirs: list[Path] = []
        seen: set[Path] = set()
        paths = [self._save_path(*parts)]
        if self._legacy_save_fallback_enabled():
            paths.append(self._legacy_save_path(*parts))
        for path in paths:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if path.exists() and path.is_dir():
                dirs.append(path)
        return dirs

    def _search_filter_state_path(self) -> Path:
        return self._save_path("remote_web_filter_state.json")

    def default_search_filter_state(self) -> dict[str, Any]:
        return {
            "version": 1,
            "query": "",
            "exclude": "",
            "ratings": list(SUPPORTED_RATINGS),
            "tag_filter": [],
            "tag_filter_exclude": [],
            "tag_filter_active": False,
            "updated_at": None,
        }

    def normalize_rating_list(self, ratings: Any) -> list[str]:
        if isinstance(ratings, str):
            ratings = list(ratings)
        if not isinstance(ratings, (list, tuple, set)):
            return list(SUPPORTED_RATINGS)
        normalized = [
            rating
            for rating in SUPPORTED_RATINGS
            if rating in {
                str(item).strip().lower()
                for item in ratings
                if str(item).strip().lower() in SUPPORTED_RATINGS
            }
        ]
        return normalized or list(SUPPORTED_RATINGS)

    @staticmethod
    def normalize_filter_tags(tags: Any) -> list[str]:
        if tags is None:
            return []
        if isinstance(tags, str):
            raw_items = re.split(r"[,\n]", tags)
        elif isinstance(tags, (list, tuple, set)):
            raw_items = list(tags)
        else:
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            text = str(item or "").strip().replace("_", " ")
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(text)
        return normalized

    def normalize_search_filter_state(self, raw: Any) -> dict[str, Any]:
        state = self.default_search_filter_state()
        if isinstance(raw, dict):
            state["query"] = str(raw.get("query", state["query"]) or "")
            state["exclude"] = str(raw.get("exclude", state["exclude"]) or "")
            state["ratings"] = self.normalize_rating_list(raw.get("ratings", state["ratings"]))
            state["tag_filter"] = [
                tag.lstrip("-") for tag in self.normalize_filter_tags(
                    raw.get("tag_filter") or raw.get("include") or raw.get("include_tags")
                )
            ]
            state["tag_filter_exclude"] = [
                tag.lstrip("-") for tag in self.normalize_filter_tags(
                    raw.get("tag_filter_exclude") or raw.get("exclude_tags")
                )
            ]
            state["tag_filter_active"] = bool(raw.get("tag_filter_active")) and (
                bool(state["tag_filter"]) or bool(state["tag_filter_exclude"])
            )
            state["updated_at"] = raw.get("updated_at")
        return state

    def _load_search_filter_state(self) -> dict[str, Any]:
        paths = [self._search_filter_state_path()]
        if self._legacy_save_fallback_enabled():
            paths.append(self._legacy_save_path("remote_web_filter_state.json"))
        for path in paths:
            try:
                if path.exists():
                    with path.open("r", encoding="utf-8") as f:
                        return self.normalize_search_filter_state(json.load(f))
            except Exception as exc:
                print(f"Headless Remote: filter state load failed - {exc}", flush=True)
        return self.default_search_filter_state()

    def save_search_filter_state(self, **updates: Any) -> dict[str, Any]:
        state = dict(getattr(self, "search_filter_state", None) or self.default_search_filter_state())
        for key in ("query", "exclude"):
            if key in updates and updates[key] is not None:
                state[key] = str(updates[key] or "")
        if "ratings" in updates and updates["ratings"] is not None:
            state["ratings"] = self.normalize_rating_list(updates["ratings"])
        if "tag_filter" in updates and updates["tag_filter"] is not None:
            state["tag_filter"] = [
                tag.lstrip("-") for tag in self.normalize_filter_tags(updates["tag_filter"])
            ]
        if "tag_filter_exclude" in updates and updates["tag_filter_exclude"] is not None:
            state["tag_filter_exclude"] = [
                tag.lstrip("-") for tag in self.normalize_filter_tags(updates["tag_filter_exclude"])
            ]
        if "tag_filter_active" in updates and updates["tag_filter_active"] is not None:
            state["tag_filter_active"] = bool(updates["tag_filter_active"])
        state = self.normalize_search_filter_state(state)
        state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.search_filter_state = state
        self.remote_active_ratings = set(state["ratings"])
        try:
            path = self._search_filter_state_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_suffix(path.suffix + ".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
                f.write("\n")
            tmp_path.replace(path)
        except Exception as exc:
            print(f"Headless Remote: filter state save failed - {exc}", flush=True)
        return state

    def save_search_filter_state_from_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return self.normalize_search_filter_state(getattr(self, "search_filter_state", None))
        return self.save_search_filter_state(
            query=payload.get("query") if "query" in payload else None,
            exclude=payload.get("exclude") if "exclude" in payload else None,
            ratings=payload.get("ratings") if "ratings" in payload else None,
            tag_filter=payload.get("tag_filter") if "tag_filter" in payload else None,
            tag_filter_exclude=payload.get("tag_filter_exclude") if "tag_filter_exclude" in payload else None,
            tag_filter_active=payload.get("tag_filter_active") if "tag_filter_active" in payload else None,
        )

    def custom_parquet_dir(self) -> Path:
        return self._existing_save_path("custom_tags")

    def runner_parquet_path(self) -> Path:
        if self.runtime_paths is not None:
            return self.runtime_paths.cache_dir / "naia_temp_rows.parquet"
        return Path(self.repo_root) / "naia_temp_rows.parquet"

    def runner_parquet_sources(self) -> list[tuple[Path, str]]:
        root = Path(self.repo_root)
        candidates: list[tuple[Path, str]] = [(self.runner_parquet_path(), "runtime cache parquet")]
        if self.runtime_paths is not None:
            candidates.append((self.runtime_paths.data_dir / "naia_temp_rows.parquet", "runtime data parquet"))
            candidates.append((self.runtime_paths.data_dir / "tags" / "tags_129.parquet", "runtime tag archive parquet"))
        candidates.extend([
            (root / "data" / "naia_temp_rows.parquet", "legacy data parquet"),
            (root / "naia_temp_rows.parquet", "legacy temp parquet"),
        ])

        seen: set[Path] = set()
        unique_candidates: list[tuple[Path, str]] = []
        for path, label in candidates:
            resolved = Path(path).resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            unique_candidates.append((path, label))
        return unique_candidates

    def custom_parquet_names(self) -> list[str]:
        custom_dir = self.custom_parquet_dir()
        if not custom_dir.exists():
            return []
        return sorted(path.name for path in custom_dir.glob("*.parquet") if path.is_file())

    def search_state_payload(self) -> dict[str, Any]:
        active_ratings = self.get_active_ratings()
        snapshot = getattr(self, "search_results_snapshot", None)
        if snapshot is not None and not getattr(snapshot, "empty", True) and "rating" in snapshot.columns:
            rating_counts = {
                rating: int((snapshot["rating"] == rating).sum())
                for rating in SUPPORTED_RATINGS
            }
        else:
            rating_counts = self.search_results.get_count_by_rating()
        count = self.search_results.get_filtered_count(active_ratings) if active_ratings else self.search_results.get_count()
        filter_preferences = self.normalize_search_filter_state(
            getattr(self, "search_filter_state", None)
        )
        return {
            "type": "search_state",
            "count": int(count or 0),
            "total_count": int(self.search_results.get_count() if self.search_results else 0),
            "active_ratings": [rating for rating in SUPPORTED_RATINGS if rating in active_ratings],
            "rating_counts": rating_counts,
            "query": filter_preferences.get("query", ""),
            "exclude": filter_preferences.get("exclude", ""),
            "ratings": {rating: rating in active_ratings for rating in SUPPORTED_RATINGS},
            "filter_preferences": filter_preferences,
            "parquets": self.custom_parquet_names(),
        }

    def auto_save_state_payload(self) -> dict[str, Any]:
        state = dict(AUTO_SAVE_DEFAULTS)
        state.update({key: self.auto_save_state.get(key) for key in AUTO_SAVE_DEFAULTS if key in self.auto_save_state})
        state["auto_save"] = bool(state["auto_save"])
        state["save_as_webp"] = bool(state["save_as_webp"])
        state["history_limit_enabled"] = bool(state["history_limit_enabled"])
        state["max_history_length"] = int(state["max_history_length"] or 2000)
        state["memory_action"] = int(state["memory_action"] or 1)
        state["unsaved_history_count"] = self.result_store.unsaved_history_count()
        state["memory_action_options"] = list(AUTO_SAVE_MEMORY_ACTION_OPTIONS)
        return self._module_state_payload("auto_save", state)

    def save_directory_state_payload(self, client_host: str | None = None) -> dict[str, Any]:
        base_path = str(self.save_directory_state.get("base_path") or "output")
        use_timestamp_folder = self._coerce_bool(
            self.save_directory_state.get("use_timestamp_folder", True)
        )
        control_allowed = True if client_host is None else self._is_loopback_host(client_host)
        control_reason = "" if control_allowed else "Save directory control is local-only."
        state = {
            "base_path": base_path,
            "current_save_directory": str(self._current_save_directory(base_path, use_timestamp_folder)),
            "session_timestamp": self.session_timestamp,
            "use_timestamp_folder": use_timestamp_folder,
            "save_counter": int(self.save_directory_state.get("save_counter", 1) or 1),
            "filename_format": str(self.save_directory_state.get("filename_format") or "number_only"),
            "filename_format_options": list(SAVE_DIRECTORY_FILENAME_OPTIONS),
            "classification_method": str(self.save_directory_state.get("classification_method") or "none"),
            "classification_method_options": list(SAVE_DIRECTORY_CLASSIFICATION_OPTIONS),
            "classification_rules": str(self.save_directory_state.get("classification_rules") or ""),
            "control_allowed": control_allowed,
            "control_block_reason": control_reason,
            "browse_allowed": control_allowed,
            "browse_block_reason": control_reason,
        }
        return self._module_state_payload("save_directory", state)

    def module_state_payload(self, module_id: str, client_host: str | None = None) -> dict[str, Any]:
        clean_id = str(module_id or "").strip()
        if clean_id == "auto_save":
            return self.auto_save_state_payload()
        if clean_id == "save_directory":
            return self.save_directory_state_payload(client_host)
        if clean_id == "prompt_engineering":
            return self._prompt_engineering_module_state()
        if clean_id == "conditional_prompt":
            return self._conditional_prompt_module_state()
        if clean_id == "character":
            return self._character_module_state()
        if clean_id == "character_reference":
            return self._character_reference_module_state()
        if clean_id == "vibe_transfer":
            return self._vibe_transfer_module_state()
        if clean_id == "img2img":
            return self._img2img_module_state()
        if clean_id == "automation":
            return self._automation_module_state()
        if clean_id == "webui_hiresfix_assist":
            return self._webui_hiresfix_assist_module_state()
        if clean_id == "event_stream":
            return self._event_stream_module_state()
        if clean_id == "wildcard":
            return self._wildcard_module_state()
        if clean_id == "instant_wildcard":
            return self._instant_wildcard_module_state()
        if clean_id == "chunk":
            return self._chunk_module_state()
        if clean_id == "e621_event":
            return self._e621_event_module_state()
        if clean_id in HEADLESS_RETIRED_MODULES:
            return self._retired_module_state(clean_id)
        return {
            "type": "module_state",
            "module_id": clean_id,
            "available": False,
            "headless": True,
            "state": {},
        }

    def set_module_param(
        self,
        module_id: str,
        key: str,
        value: Any,
        *,
        client_host: str | None = None,
    ) -> dict[str, Any] | None:
        clean_id = str(module_id or "").strip()
        clean_key = str(key or "").strip()
        if clean_id == "auto_save":
            if clean_key in {"auto_save", "save_as_webp", "history_limit_enabled"}:
                self.auto_save_state[clean_key] = self._coerce_bool(value)
                if clean_key == "auto_save":
                    self.remote_options["auto_save"] = bool(self.auto_save_state[clean_key])
            elif clean_key == "max_history_length":
                self.auto_save_state[clean_key] = self._coerce_int(value, default=2000, minimum=100, maximum=10000)
            elif clean_key == "memory_action":
                self.auto_save_state[clean_key] = self._coerce_int(value, default=1, minimum=1, maximum=3)
            else:
                return None
            return self.auto_save_state_payload()
        if clean_id == "save_directory":
            if client_host is not None and not self._is_loopback_host(client_host):
                return self.save_directory_state_payload(client_host)
            if clean_key == "base_path":
                path_value = str(value or "").strip()
                if path_value:
                    self.save_directory_state[clean_key] = path_value
            elif clean_key == "use_timestamp_folder":
                self.save_directory_state[clean_key] = self._coerce_bool(value)
            elif clean_key == "filename_format":
                allowed = {item["value"] for item in SAVE_DIRECTORY_FILENAME_OPTIONS}
                if str(value or "") in allowed:
                    self.save_directory_state[clean_key] = str(value)
            elif clean_key == "classification_method":
                allowed = {item["value"] for item in SAVE_DIRECTORY_CLASSIFICATION_OPTIONS}
                if str(value or "") in allowed:
                    self.save_directory_state[clean_key] = str(value)
            elif clean_key == "classification_rules":
                self.save_directory_state[clean_key] = str(value or "")
            else:
                return None
            return self.save_directory_state_payload(client_host)
        if clean_id == "prompt_engineering":
            return self._set_prompt_engineering_param(clean_key, value)
        if clean_id == "conditional_prompt":
            return self._set_conditional_prompt_param(clean_key, value)
        if clean_id == "character":
            return self._set_character_param(clean_key, value)
        if clean_id == "character_reference":
            return self._set_character_reference_param(clean_key, value)
        if clean_id == "vibe_transfer":
            return self._set_vibe_transfer_param(clean_key, value)
        if clean_id == "img2img":
            return self._set_img2img_param(clean_key, value)
        if clean_id == "automation":
            return self._set_automation_param(clean_key, value)
        if clean_id == "webui_hiresfix_assist":
            return self._set_webui_hiresfix_assist_param(clean_key, value)
        if clean_id == "event_stream":
            return self._set_event_stream_param(clean_key, value)
        if clean_id == "wildcard":
            return self._set_wildcard_param(clean_key, value)
        if clean_id == "instant_wildcard":
            return self._set_instant_wildcard_param(clean_key, value)
        if clean_id == "e621_event":
            return self._set_e621_event_param(clean_key, value)
        if clean_id in HEADLESS_RETIRED_MODULES:
            return self._retired_module_state(clean_id, action=clean_key)
        return None

    def save_unsaved_history(self) -> dict[str, Any]:
        items = self.result_store.unsaved_items()
        if not items:
            return {"saved": 0, "remaining": 0, "paths": []}
        save_as_webp = self._coerce_bool(self.auto_save_state_payload().get("save_as_webp"))
        directory = self._current_save_directory()
        directory.mkdir(parents=True, exist_ok=True)
        saved_paths: list[str] = []
        for item in list(items):
            extension = "webp" if save_as_webp else "png"
            filename = self._next_save_filename(item, extension)
            target = self._unique_output_path(directory / filename)
            if save_as_webp:
                target.write_bytes(item.webp_bytes)
            else:
                png_bytes, _ = result_images.history_item_png_payload(item, label=item.filename)
                target.write_bytes(png_bytes)
            self.result_store.mark_saved(item, target)
            saved_paths.append(str(target))
        return {
            "saved": len(saved_paths),
            "remaining": self.result_store.unsaved_history_count(),
            "paths": saved_paths,
            "current_save_directory": str(directory),
        }

    def _prompt_engineering_module_state(self) -> dict[str, Any]:
        return self._prompt_engineering_service().state()

    def _set_prompt_engineering_param(self, key: str, value: Any) -> dict[str, Any] | None:
        return self._prompt_engineering_service().set_param(key, value)

    def _conditional_prompt_module_state(self) -> dict[str, Any]:
        return self._conditional_prompt_service().state()

    def _set_conditional_prompt_param(self, key: str, value: Any) -> dict[str, Any] | None:
        return self._conditional_prompt_service().set_param(key, value)

    def _character_module_state(self) -> dict[str, Any]:
        from core.character_settings import character_state_from_settings, load_character_settings

        mode = self.get_api_mode()
        settings = self._character_settings_cache()
        if settings is None:
            settings = load_character_settings(
                mode,
                path=self._existing_save_path(f"CharacterModule_{str(mode or 'NAI').upper()}.json"),
            )
            self._character_settings_by_mode()[mode] = settings
        state = character_state_from_settings(settings, app_context=self, mode=mode)
        state["available"] = True
        state["headless"] = True
        return state

    def _set_character_param(self, key: str, value: Any) -> dict[str, Any] | None:
        mode = self.get_api_mode()
        settings = self._character_settings_cache()
        frames = settings.setdefault("character_frames", [])
        if key == "activated":
            settings["is_active"] = self._coerce_bool(value)
        elif key == "reroll_on_generate":
            settings["reroll_on_generate"] = self._coerce_bool(value)
        elif key == "add_character":
            frames.append({"prompt": "", "uc": "", "is_enabled": True, "slot_state": "active", "custom_name": ""})
        elif key == "preview_refresh":
            pass
        elif key.startswith("remove_character_"):
            index = self._index_from_key(key, "remove_character_")
            if index is not None and 0 <= index < len(frames) and len(frames) > 1:
                frames.pop(index)
        elif key.startswith("char_prompt_"):
            index = self._index_from_key(key, "char_prompt_")
            if index is not None:
                self._ensure_character_frame(frames, index)["prompt"] = str(value or "")
        elif key.startswith("char_uc_"):
            index = self._index_from_key(key, "char_uc_")
            if index is not None:
                self._ensure_character_frame(frames, index)["uc"] = str(value or "")
        elif key.startswith("char_active_"):
            index = self._index_from_key(key, "char_active_")
            if index is not None:
                frame = self._ensure_character_frame(frames, index)
                active = self._coerce_bool(value)
                frame["is_enabled"] = active
                frame["slot_state"] = "active" if active else "inactive"
        elif key.startswith("char_slot_state_"):
            index = self._index_from_key(key, "char_slot_state_")
            if index is not None:
                frame = self._ensure_character_frame(frames, index)
                requested = str(value or "").strip().lower()
                if requested == "restore":
                    requested = str(frame.get("return_slot_state") or "inactive")
                if requested in {"active", "inactive", "cold"}:
                    if requested == "cold":
                        frame["return_slot_state"] = str(frame.get("slot_state") or "inactive")
                    frame["slot_state"] = requested
                    frame["is_enabled"] = requested == "active"
        elif key.startswith("char_slot_name_"):
            index = self._index_from_key(key, "char_slot_name_")
            if index is not None:
                self._ensure_character_frame(frames, index)["custom_name"] = str(value or "")
        else:
            return None
        self._save_character_settings(mode, settings)
        return self._character_module_state()

    def _current_model_key(self) -> str:
        model = str(self.remote_params.get("model") or "NAID4.5F").strip()
        return model or "NAID4.5F"

    def _is_naid45_model(self) -> bool:
        model = self._current_model_key()
        return "NAID4.5F" in model or "NAID4.5C" in model

    def _is_naid3_model(self) -> bool:
        return "NAID3" in self._current_model_key()

    @staticmethod
    def _image_hash(image_bytes: bytes) -> str:
        return hashlib.sha256(image_bytes).hexdigest()[:16]

    @staticmethod
    def _data_url_payload(value: str) -> str:
        text = str(value or "").strip()
        if "," in text and text.lower().startswith("data:"):
            return text.split(",", 1)[1]
        return text

    @staticmethod
    def _image_to_png_bytes(image) -> bytes:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=False)
        return buffer.getvalue()

    @staticmethod
    def _thumbnail_b64(image, max_side: int = 128) -> str:
        from PIL import Image

        thumb = image.copy()
        thumb.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        if thumb.mode == "RGBA":
            thumb = thumb.convert("RGB")
        buffer = io.BytesIO()
        thumb.save(buffer, format="JPEG", quality=70)
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def _character_reference_image_data(self, image) -> str:
        return self._character_reference_service().image_data(image)

    def _save_character_reference_storage(self, frame: dict[str, Any]) -> None:
        self._character_reference_service().save_storage(frame)

    def _character_reference_frame_from_bytes(
        self,
        image_bytes: bytes,
        *,
        file_name: str = "reference.png",
        file_path: str = "",
        enabled: bool = False,
    ) -> dict[str, Any]:
        return self._character_reference_service().frame_from_bytes(
            image_bytes,
            file_name=file_name,
            file_path=file_path,
            enabled=enabled,
        )

    def _character_reference_module_state(self) -> dict[str, Any]:
        return self._character_reference_service().module_state()

    def _set_character_reference_param(self, key: str, value: Any) -> dict[str, Any] | None:
        return self._character_reference_service().set_param(key, value)

    def _scan_character_reference_storage(self) -> dict[str, Any]:
        return self._character_reference_service().scan_storage()

    def _disable_all_vibe_frames(self) -> None:
        self._vibe_transfer_service().disable_all_frames()

    def _disable_all_character_reference_frames(self) -> None:
        self._character_reference_service().disable_all_frames()

    def _vibe_frame_from_bytes(
        self,
        image_bytes: bytes,
        *,
        file_name: str = "vibe.png",
        file_path: str = "",
        enabled: bool = True,
    ) -> dict[str, Any]:
        return self._vibe_transfer_service().frame_from_bytes(
            image_bytes,
            file_name=file_name,
            file_path=file_path,
            enabled=enabled,
        )

    def _vibe_transfer_module_state(self) -> dict[str, Any]:
        return self._vibe_transfer_service().module_state()

    def _set_vibe_transfer_param(self, key: str, value: Any) -> dict[str, Any] | None:
        return self._vibe_transfer_service().set_param(key, value)

    def _scan_vibe_storage(self) -> dict[str, Any]:
        return self._vibe_transfer_service().scan_storage()

    def _apply_vibe_storage(self, value: str) -> dict[str, Any] | None:
        return self._vibe_transfer_service().apply_storage(value)

    def _scan_vibe_clusters(self) -> dict[str, Any]:
        return self._vibe_transfer_service().scan_clusters()

    def _load_vibe_cluster(self, value: str) -> dict[str, Any] | None:
        return self._vibe_transfer_service().load_cluster(value)

    def active_character_reference_params(self) -> dict[str, Any]:
        return self._character_reference_service().active_params()

    def active_vibe_transfer_params(self) -> dict[str, Any]:
        return self._vibe_transfer_service().active_params()

    def apply_headless_image_module_params(self, params: dict[str, Any], api_mode: str) -> None:
        if str(api_mode or "").upper() != "NAI":
            return
        if not params.get("director_reference_descriptions"):
            params.update(self.active_character_reference_params())
        if params.get("_skip_vibe_transfer_late_binding"):
            return
        if not params.get("reference_image_multiple"):
            params.update(self.active_vibe_transfer_params())

    def open_img2img_session_from_bytes(
        self,
        image_bytes: bytes,
        *,
        label: str = "Result Image",
        mode: str = "img2img",
        generation_params: dict[str, Any] | None = None,
        prompt_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._img2img_service().open_session_from_bytes(
            image_bytes,
            label=label,
            mode=mode,
            generation_params=generation_params,
            prompt_context=prompt_context,
        )

    def _img2img_strength_value(self, raw: Any) -> float:
        return self._img2img_service().strength_value(raw)

    def _img2img_module_state(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._img2img_service().module_state(extra)

    def _decode_img2img_mask(self, value: str) -> tuple[bytes, str, int]:
        return self._img2img_service()._decode_mask(value)

    def _set_img2img_param(self, key: str, value: Any) -> dict[str, Any] | None:
        return self._img2img_service().set_param(key, value)

    def _img2img_generation_commands(self) -> list[dict[str, Any]]:
        return self._img2img_service().generation_commands()

    def _automation_module_state(self) -> dict[str, Any]:
        return self._automation_service().state()

    def _set_automation_param(self, key: str, value: Any) -> dict[str, Any] | None:
        return self._automation_service().set_param(key, value)

    def _webui_hiresfix_assist_module_state(self) -> dict[str, Any]:
        return self._webui_hiresfix_assist_service().state()

    def _set_webui_hiresfix_assist_param(self, key: str, value: Any) -> dict[str, Any] | None:
        return self._webui_hiresfix_assist_service().set_param(key, value)

    def _event_stream_module_state(self) -> dict[str, Any]:
        return self._event_stream_service().state()

    def _set_event_stream_param(self, key: str, value: Any) -> dict[str, Any] | None:
        return self._event_stream_service().set_param(key, value)

    def _e621_event_service(self):
        service = getattr(self, "e621_event_service", None)
        if service is None:
            from core.e621_event_service import E621EventService

            service = E621EventService(self)
            self.e621_event_service = service
        return service

    def _e621_event_module_state(self) -> dict[str, Any]:
        return self._e621_event_service().state()

    def _set_e621_event_param(self, key: str, value: Any) -> dict[str, Any] | list[dict[str, Any]] | None:
        return self._e621_event_service().set_param(key, value)

    def _wildcard_module_state(self) -> dict[str, Any]:
        wildcard_count = 0
        manager = self.wildcard_manager
        for attr in ("wildcard_dict_tree", "wildcard_dict", "instant_wildcard_dict"):
            value = getattr(manager, attr, None) if manager is not None else None
            if isinstance(value, dict):
                wildcard_count += len(value)
        return self._module_state_payload("wildcard", {
            "history": [],
            "state": [],
            "prompt_squeeze": bool(self.prompt_squeeze_enabled),
            "wildcard_count": wildcard_count,
            "file_browser_available": True,
        })

    def _set_wildcard_param(self, key: str, value: Any) -> dict[str, Any] | None:
        if key == "prompt_squeeze":
            self.prompt_squeeze_enabled = self._coerce_bool(value)
            return self._wildcard_module_state()
        if key in {"reset_sequential", "reload"}:
            self._reload_wildcard_manager()
            return self._wildcard_module_state()
        if key == "get_file_tree":
            return {"type": "wildcard_manager", "action": "file_tree", "tree": self._scan_wildcard_tree()}
        if key == "read_file":
            content = self._read_wildcard_file(str(value or ""))
            if content is None:
                return self._toast("Wildcard file not found", level="error")
            return {
                "type": "wildcard_manager",
                "action": "file_content",
                "path": str(value or ""),
                "content": content,
            }
        if key == "save_file":
            try:
                payload = json.loads(str(value or "{}"))
            except json.JSONDecodeError:
                return self._toast("Invalid wildcard save payload", level="error")
            return self._save_wildcard_file(
                str(payload.get("path") or ""),
                str(payload.get("content") or ""),
            )
        if key == "delete_file":
            return self._delete_wildcard_file(str(value or ""))
        if key == "create_file":
            return self._create_wildcard_file(str(value or ""))
        if key == "preview_wildcard":
            return {
                "type": "wildcard_manager",
                "action": "preview_result",
                "name": str(value or ""),
                "result": self._preview_wildcard(str(value or "")),
            }
        return self._toast(f"Wildcard action is not supported in headless: {key}", level="info")

    def _instant_wildcard_store(self, *, force: bool = False) -> dict[str, Any]:
        from core.instant_wildcard_service import load_instant_wildcards

        signature = None
        if not force:
            cached = getattr(self, "instant_wildcard_store", None)
            signature = getattr(self, "instant_wildcard_signature", None)
            if isinstance(cached, dict) and signature == cached.get("signature"):
                return cached
        root = self._existing_save_path("instant_wildcard")
        store = load_instant_wildcards(root)
        self.instant_wildcard_store = store
        self.instant_wildcard_signature = store.get("signature")
        self._apply_instant_wildcard_to_manager(store)
        return store

    def _apply_instant_wildcard_to_manager(self, store: dict[str, Any]) -> None:
        manager = self.wildcard_manager
        if manager is not None and hasattr(manager, "update_instant_wildcards"):
            try:
                manager.update_instant_wildcards(
                    store.get("instant_wildcard_dict", {}),
                    store.get("instant_wildcard_tree", {}),
                )
                return
            except Exception:
                pass
        self.instant_wildcard_dict = store.get("instant_wildcard_dict", {})
        self.instant_wildcard_tree = store.get("instant_wildcard_tree", {})

    def _instant_wildcard_module_state(self) -> dict[str, Any]:
        from core.instant_wildcard_service import instant_wildcard_group_name, select_instant_wildcard_item

        store = self._instant_wildcard_store()
        json_data = store.get("json_data", {}) if isinstance(store, dict) else {}
        current_file = getattr(self, "instant_wildcard_current_file", None)
        current_key = getattr(self, "instant_wildcard_current_key", None)
        selected_file, selected_key = select_instant_wildcard_item(json_data, current_file, current_key)
        self.instant_wildcard_current_file = selected_file
        self.instant_wildcard_current_key = selected_key
        current_items = json_data.get(selected_file or "", {}) if isinstance(json_data, dict) else {}
        current_items = current_items if isinstance(current_items, dict) else {}
        files = []
        for filename, data in json_data.items():
            data = data if isinstance(data, dict) else {}
            files.append({
                "name": filename,
                "group": instant_wildcard_group_name(filename),
                "count": len(data),
                "selected": filename == selected_file,
            })
        items = [
            {
                "key": key,
                "value": str(current_items.get(key) or ""),
                "selected": key == selected_key,
            }
            for key in sorted(current_items.keys())
        ]
        current_value = str(current_items.get(selected_key, "") or "") if selected_key else ""
        return self._module_state_payload("instant_wildcard", {
            "files": files,
            "items": items,
            "current_file": selected_file or "",
            "current_group": instant_wildcard_group_name(selected_file or "") if selected_file else "",
            "current_key": selected_key or "",
            "current_value": current_value,
            "flat_count": len(store.get("instant_wildcard_dict", {}) or {}),
            "save_path": str(store.get("save_path") or ""),
        })

    def _chunk_module_state(self) -> dict[str, Any]:
        from core.instant_wildcard_service import instant_wildcard_group_name

        store = self._instant_wildcard_store()
        json_data = store.get("json_data", {}) if isinstance(store, dict) else {}
        groups = []
        for filename, items in json_data.items():
            if not isinstance(items, dict):
                continue
            groups.append({
                "name": instant_wildcard_group_name(filename),
                "items": [
                    {"key": str(key), "value": str(value)}
                    for key, value in sorted(items.items(), key=lambda item: str(item[0]))
                ],
            })
        return {"type": "module_state", "module_id": "chunk", "available": True, "headless": True, "groups": groups}

    def _set_instant_wildcard_param(self, key: str, value: Any) -> dict[str, Any] | None:
        from core.instant_wildcard_service import (
            instant_wildcard_group_name,
            normalize_instant_wildcard_filename,
            write_instant_wildcard_file,
        )

        store = self._instant_wildcard_store(force=key == "reload")
        json_data = store.get("json_data", {}) if isinstance(store, dict) else {}
        if key == "reload":
            return self._instant_wildcard_module_state()
        if key == "select_file":
            filename = normalize_instant_wildcard_filename(str(value or ""))
            if filename in json_data:
                self.instant_wildcard_current_file = filename
                items = json_data.get(filename, {})
                self.instant_wildcard_current_key = next(iter(sorted(items.keys()))) if isinstance(items, dict) and items else None
            return self._instant_wildcard_module_state()
        if key == "select_key":
            item_key = str(value or "").strip()
            filename = getattr(self, "instant_wildcard_current_file", None)
            if filename in json_data and item_key in json_data.get(filename, {}):
                self.instant_wildcard_current_key = item_key
            return self._instant_wildcard_module_state()
        if key == "add_group":
            filename = normalize_instant_wildcard_filename(str(value or ""))
            if not filename:
                return self._toast("Instant wildcard group is required", level="error")
            json_data.setdefault(filename, {})
            write_instant_wildcard_file(json_data, filename, store.get("save_path") or "")
            self.instant_wildcard_current_file = filename
            self.instant_wildcard_current_key = None
            self._instant_wildcard_store(force=True)
            return self._instant_wildcard_module_state()
        if key == "value":
            filename = getattr(self, "instant_wildcard_current_file", None)
            item_key = getattr(self, "instant_wildcard_current_key", None)
            if filename and item_key:
                json_data.setdefault(filename, {})[item_key] = str(value or "")
                write_instant_wildcard_file(json_data, filename, store.get("save_path") or "")
                self._instant_wildcard_store(force=True)
            return self._instant_wildcard_module_state()
        if key in {"upsert", "delete", "rename"}:
            try:
                payload = json.loads(str(value or "{}"))
            except json.JSONDecodeError:
                return self._toast("Invalid instant wildcard payload", level="error")
            filename = normalize_instant_wildcard_filename(
                str(payload.get("file") or getattr(self, "instant_wildcard_current_file", "") or "")
            )
            if not filename:
                return self._toast("Instant wildcard file is required", level="error")
            if key == "upsert":
                item_key = str(payload.get("key") or "").strip()
                if not item_key:
                    return self._toast("Instant wildcard key is required", level="error")
                json_data.setdefault(filename, {})[item_key] = str(payload.get("value") or "")
                self.instant_wildcard_current_file = filename
                self.instant_wildcard_current_key = item_key
            elif key == "delete":
                item_key = str(payload.get("key") or "").strip()
                if filename in json_data and item_key in json_data[filename]:
                    del json_data[filename][item_key]
                    image_path = self._existing_save_path(
                        "instant_wildcard",
                        "images",
                        instant_wildcard_group_name(filename),
                        f"{item_key}.png",
                    )
                    if image_path.exists():
                        try:
                            image_path.unlink()
                        except Exception:
                            pass
                if getattr(self, "instant_wildcard_current_key", None) == item_key:
                    remaining = json_data.get(filename, {})
                    self.instant_wildcard_current_key = next(iter(sorted(remaining.keys()))) if remaining else None
            elif key == "rename":
                old_key = str(payload.get("old_key") or "").strip()
                new_key = str(payload.get("new_key") or "").strip()
                if filename in json_data and old_key in json_data[filename] and new_key:
                    json_data[filename][new_key] = json_data[filename].pop(old_key)
                    self.instant_wildcard_current_file = filename
                    self.instant_wildcard_current_key = new_key
            write_instant_wildcard_file(json_data, filename, store.get("save_path") or "")
            self._instant_wildcard_store(force=True)
            return self._instant_wildcard_module_state()
        return self._toast(f"Instant wildcard action is not supported in headless: {key}", level="info")

    def _wildcard_base_dir(self) -> Path:
        manager = self.wildcard_manager
        base = getattr(manager, "wildcards_dir", None) if manager is not None else None
        if base:
            return Path(base)
        if os.environ.get("NAIA_USER_DATA_DIR") or os.environ.get("NAIA_PORTABLE"):
            runtime_paths = getattr(self, "runtime_paths", None)
            runtime_base = getattr(runtime_paths, "wildcards_dir", None) if runtime_paths is not None else None
            if runtime_base:
                return Path(runtime_base)
        return Path(self.repo_root) / "wildcards"

    def _validate_wildcard_path(self, rel_path: str) -> Path | None:
        clean = str(rel_path or "").replace("\\", "/").strip().lstrip("/")
        if not clean:
            return None
        base = self._wildcard_base_dir().resolve()
        target = (base / clean).resolve()
        try:
            target.relative_to(base)
        except ValueError:
            return None
        return target

    def _scan_wildcard_tree(self) -> list[dict[str, Any]]:
        base = self._wildcard_base_dir()
        if not base.exists():
            return []
        tree: list[dict[str, Any]] = []
        for item in sorted(base.iterdir(), key=lambda path: path.name.lower()):
            if item.name.startswith("."):
                continue
            if item.is_dir():
                folder = {"name": item.name, "type": "folder", "files": []}
                for path in sorted(item.rglob("*.txt"), key=lambda path: str(path).lower()):
                    try:
                        lines = len(path.read_text(encoding="utf-8").splitlines())
                    except Exception:
                        lines = 0
                    folder["files"].append({
                        "name": path.name,
                        "path": str(path.relative_to(base)).replace("\\", "/"),
                        "lines": lines,
                    })
                if folder["files"]:
                    tree.append(folder)
            elif item.suffix.lower() == ".txt":
                try:
                    lines = len(item.read_text(encoding="utf-8").splitlines())
                except Exception:
                    lines = 0
                tree.append({"name": item.name, "type": "file", "path": item.name, "lines": lines})
        return tree

    def _read_wildcard_file(self, rel_path: str) -> str | None:
        target = self._validate_wildcard_path(rel_path)
        if target is None or not target.is_file() or target.suffix.lower() != ".txt":
            return None
        return target.read_text(encoding="utf-8")

    def _save_wildcard_file(self, rel_path: str, content: str) -> dict[str, Any]:
        if not str(rel_path or "").endswith(".txt"):
            return self._toast("Wildcard filename must end with .txt", level="error")
        target = self._validate_wildcard_path(rel_path)
        if target is None:
            return self._toast("Invalid wildcard path", level="error")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self._reload_wildcard_manager()
        return {
            "type": "wildcard_manager",
            "action": "file_content",
            "path": str(rel_path).replace("\\", "/"),
            "content": content,
        }

    def _delete_wildcard_file(self, rel_path: str) -> dict[str, Any]:
        target = self._validate_wildcard_path(rel_path)
        if target is None or not target.is_file() or target.suffix.lower() != ".txt":
            return self._toast("Wildcard file not found", level="error")
        target.unlink()
        self._reload_wildcard_manager()
        return {
            "type": "wildcard_manager",
            "action": "file_deleted",
            "path": str(rel_path).replace("\\", "/"),
        }

    def _create_wildcard_file(self, rel_path: str) -> dict[str, Any]:
        clean = str(rel_path or "").strip()
        if not clean.endswith(".txt"):
            clean += ".txt"
        target = self._validate_wildcard_path(clean)
        if target is None:
            return self._toast("Invalid wildcard path", level="error")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text("", encoding="utf-8")
        self._reload_wildcard_manager()
        return {
            "type": "wildcard_manager",
            "action": "file_content",
            "path": clean.replace("\\", "/"),
            "content": "",
        }

    def _preview_wildcard(self, name: str) -> str:
        import random

        clean = str(name or "").strip().replace("\\", "/")
        if clean.endswith(".txt"):
            clean = clean[:-4]
        entries = []
        manager = self.wildcard_manager
        tree = getattr(manager, "wildcard_dict_tree", {}) if manager is not None else {}
        if isinstance(tree, dict):
            entries = list(tree.get(clean, []))
        if not entries:
            file_content = self._read_wildcard_file(f"{clean}.txt")
            if file_content is None:
                file_content = self._read_wildcard_file(f"{clean.replace('/', '-')}.txt")
            entries = [(1, line.strip()) for line in str(file_content or "").splitlines() if line.strip()]
        if not entries:
            return f"Wildcard '{clean}' not found"
        weights = []
        texts = []
        for entry in entries:
            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                weights.append(float(entry[0]) if str(entry[0]).replace(".", "", 1).isdigit() else 1.0)
                texts.append(str(entry[1]))
            else:
                weights.append(1.0)
                texts.append(str(entry))
        return "\n".join(f"#{index + 1}: {random.choices(texts, weights=weights, k=1)[0]}" for index in range(5))

    def _reload_wildcard_manager(self) -> None:
        manager = self.wildcard_manager
        if manager is not None and hasattr(manager, "reload_wildcards"):
            try:
                manager.reload_wildcards()
            except Exception:
                pass

    def hires_overlay_response(self, preset_name: str) -> dict[str, Any]:
        name = str(preset_name or "").strip()
        response = {
            "type": "hires_preset_overlay",
            "preset_name": name,
            "original": {"prefix_prompt": "", "postfix_prompt": "", "negative_prompt": ""},
            "overlay": None,
            "editable": False,
            "available": False,
            "headless": True,
        }
        path = self._hires_overlay_path(name)
        if path is None:
            return response
        response["editable"] = True
        response["available"] = True
        preset_path = self._existing_save_path("presets", "WEBUI", f"{name}.json")
        if preset_path.exists():
            try:
                preset_data = json.loads(preset_path.read_text(encoding="utf-8"))
                module_settings = preset_data.get("module_settings", {}) if isinstance(preset_data, dict) else {}
                main_settings = preset_data.get("main_settings", {}) if isinstance(preset_data, dict) else {}
                module_settings = module_settings if isinstance(module_settings, dict) else {}
                main_settings = main_settings if isinstance(main_settings, dict) else {}
                response["original"] = {
                    "prefix_prompt": str(module_settings.get("pre_prompt", "") or ""),
                    "postfix_prompt": str(module_settings.get("post_prompt", "") or ""),
                    "negative_prompt": str(
                        main_settings.get("negative") or main_settings.get("negative_prompt") or ""
                    ),
                }
            except Exception:
                pass
        overlay_path = self._existing_save_path("presets", "WEBUI", f"{name}.hires.json")
        if overlay_path.exists():
            try:
                overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
                if isinstance(overlay, dict):
                    response["overlay"] = {
                        "prefix_prompt": str(overlay.get("prefix_prompt", "") or ""),
                        "postfix_prompt": str(overlay.get("postfix_prompt", "") or ""),
                        "negative_prompt": str(overlay.get("negative_prompt", "") or ""),
                    }
            except Exception:
                pass
        return response

    def write_hires_overlay(self, preset_name: str, body: dict[str, Any] | None) -> tuple[bool, str]:
        path = self._hires_overlay_path(preset_name)
        if path is None:
            return False, "WEBUI 모드의 일반 프리셋만 편집할 수 있습니다."
        source = body if isinstance(body, dict) else {}
        payload = {
            "schema_version": 1,
            "prefix_prompt": str(source.get("prefix_prompt", "") or ""),
            "postfix_prompt": str(source.get("postfix_prompt", "") or ""),
            "negative_prompt": str(source.get("negative_prompt", "") or ""),
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return True, f"Overlay saved: {path.name}"
        except Exception as exc:
            return False, f"저장 실패: {exc}"

    def reset_hires_overlay(self, preset_name: str) -> tuple[bool, str]:
        path = self._hires_overlay_path(preset_name)
        if path is None:
            return False, "WEBUI 모드의 일반 프리셋만 편집할 수 있습니다."
        try:
            if path.exists():
                path.unlink()
                return True, f"Overlay removed: {path.name}"
            return True, "Overlay already absent."
        except Exception as exc:
            return False, f"삭제 실패: {exc}"

    def _hires_overlay_path(self, preset_name: str) -> Path | None:
        name = str(preset_name or "").strip()
        if name in HIRES_OVERLAY_DISALLOWED_NAMES:
            return None
        safe_name = Path(name).name
        if safe_name != name:
            return None
        if self.get_api_mode() != "WEBUI":
            return None
        return self._save_path("presets", "WEBUI", f"{safe_name}.hires.json")

    def _retired_module_state(self, module_id: str, *, action: str | None = None) -> dict[str, Any]:
        message = HEADLESS_RETIRED_MODULES.get(
            module_id,
            "Module is retired in the supported headless runtime.",
        )
        state = {
            "available": False,
            "retired": True,
            "message": message,
        }
        if action:
            state["last_action"] = action
        return self._module_state_payload(module_id, state)

    def autocomplete_status_payload(self) -> dict[str, Any]:
        return self.autocomplete_state.to_payload()

    def api_status_payload(self, client_host: str | None = None) -> dict[str, Any]:
        return self.api_config_service.status_payload(
            active_mode=self.get_api_mode(),
            autocomplete=self.autocomplete_status_payload(),
            client_host=client_host,
        )

    def http_status_payload(self) -> dict[str, Any]:
        return {
            "is_generating": bool(self.is_generating),
            "api_mode": self.get_api_mode(),
            "autocomplete": self.autocomplete_status_payload(),
        }

    def desktop_window_state_payload(self, client_host: str | None = None) -> dict[str, Any]:
        payload = {"type": "desktop_window_state", "visible": False}
        if client_host is not None:
            payload["control_allowed"] = False
            payload["control_block_reason"] = "Desktop runtime is not available in headless mode."
        return payload

    def queue_state_payload(self) -> dict[str, Any]:
        stats = self.generation_queue_manager.get_queue_stats()
        queued = [
            self._serialize_queue_request(request, position=index + 1)
            for index, request in enumerate(self.generation_queue_manager.get_all_requests())
        ]
        return {
            "type": "queue_state",
            "is_generating": bool(self.is_generating),
            "paused": bool(stats.get("is_paused", False)),
            "total": int(stats.get("total", len(queued)) or 0),
            "has_urgent": bool(stats.get("has_urgent", False)),
            "priority_counts": stats.get("priority_counts", {}),
            "active": None,
            "items": queued,
        }

    @staticmethod
    def _queue_preview(value: Any, limit: int = 140) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        return text if len(text) <= limit else text[:limit - 1].rstrip() + "..."

    def _queue_param_summary(self, params: dict[str, Any] | None = None, request: Any = None) -> dict[str, Any]:
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
            "prompt_preview": self._queue_preview(prompt),
            "negative_preview": self._queue_preview(negative, 100),
            "mode": str(params.get("api_mode") or self.get_api_mode() or ""),
            "resolution": resolution,
            "seed": str(params.get("seed") or ""),
            "source": str(params.get("_remote_queue_source") or "queue"),
            "label": str(params.get("_remote_queue_label") or ""),
            "character_count": character_count,
            "vibe_count": vibe_count,
            "char_ref_count": char_ref_count,
        }

    def _serialize_queue_request(self, request: Any, position: int | None = None) -> dict[str, Any]:
        params = getattr(request, "params", {}) if request else {}
        summary = self._queue_param_summary(params, request=request)
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
            "label": self._queue_preview(label, 80),
        }

    def generation_param_schema_payload(self) -> dict[str, Any]:
        from core.resolution_utils import ANIMA_RESOLUTION_LABELS, STANDARD_1MP_RESOLUTION_LABELS

        mode = self.get_api_mode()
        resolution_options = list(ANIMA_RESOLUTION_LABELS if mode == "COMFYUI" else STANDARD_1MP_RESOLUTION_LABELS)
        resolution = str(self.remote_params.get("resolution") or "832 x 1216")
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
            "options_model": self._model_options_for_mode(mode),
            "options_sampler": self._sampler_options_for_mode(mode),
            "options_scheduler": self._scheduler_options_for_mode(mode),
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
            hires_state = self._normalized_webui_hiresfix_assist_state(self.webui_hiresfix_assist_state)
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
                "hires_preset_swap": str(self.remote_params.get("hires_preset_swap") or ""),
                "resolution_preset_enabled": bool(self.remote_params.get("resolution_preset_enabled", False)),
                "resolution_preset": str(self.remote_params.get("resolution_preset") or "standard"),
                "anima_weight": str(self.remote_params.get("anima_weight") or self.remote_params.get("random_prompt_weight") or ""),
            })
        elif mode == "COMFYUI":
            payload.update({
                "sampling_mode": str(self.remote_params.get("sampling_mode") or "eps"),
                "rescale_cfg": self.remote_params.get("rescale_cfg", 0.0),
                "anima_weight": str(self.remote_params.get("anima_weight") or self.remote_params.get("random_prompt_weight") or ""),
                "resolution_preset_enabled": bool(self.remote_params.get("resolution_preset_enabled", False)),
                "resolution_preset": str(self.remote_params.get("resolution_preset") or "standard"),
                "comfyui_workflow": dict(self.remote_params.get("comfyui_workflow") or {}),
                "comfyui_workflow_has_custom": bool(self.remote_params.get("comfyui_workflow_has_custom", False)),
                "comfyui_workflow_label": str(self.remote_params.get("comfyui_workflow_label") or "Default workflow"),
            })
        payload.update(self.remote_params)
        return payload

    @staticmethod
    def _coerce_remote_param(key: str, value: Any) -> Any:
        if key in REMOTE_BOOLEAN_PARAMS:
            return WebSessionContext._coerce_bool(value)
        if key in REMOTE_INT_PARAMS:
            try:
                if value is None or value == "":
                    return ""
                return int(float(value))
            except (TypeError, ValueError):
                return value
        if key in REMOTE_FLOAT_PARAMS:
            try:
                if value is None or value == "":
                    return ""
                return float(value)
            except (TypeError, ValueError):
                return value
        return value

    @staticmethod
    def _model_options_for_mode(mode: str) -> list[str]:
        if mode == "WEBUI":
            return ["Stable Diffusion"]
        if mode == "COMFYUI":
            return ["ComfyUI Workflow"]
        return ["NAID4.5F", "NAID4.5", "NAID4", "NAID3"]

    @staticmethod
    def _sampler_options_for_mode(mode: str) -> list[str]:
        if mode == "WEBUI":
            return ["Euler a", "Euler", "DPM++ 2M", "DPM++ 2M Karras"]
        if mode == "COMFYUI":
            return ["euler", "euler_ancestral", "dpmpp_2m", "dpmpp_sde"]
        return ["k_euler_ancestral", "k_euler", "k_dpmpp_2m", "ddim"]

    @staticmethod
    def _scheduler_options_for_mode(mode: str) -> list[str]:
        if mode == "WEBUI":
            return ["Automatic", "Karras", "Exponential", "SGM Uniform"]
        if mode == "COMFYUI":
            return ["normal", "karras", "exponential", "sgm_uniform"]
        return ["karras", "native", "exponential", "polyexponential"]

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))

    def _module_state_payload(self, module_id: str, state: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "type": "module_state",
            "module_id": module_id,
            "available": True,
            "headless": True,
            **state,
        }
        payload["state"] = dict(state)
        return payload

    def _current_save_directory(
        self,
        base_path: str | None = None,
        use_timestamp_folder: bool | None = None,
    ) -> Path:
        raw_base = str(base_path or self.save_directory_state.get("base_path") or "output")
        base = Path(raw_base).expanduser()
        if not base.is_absolute():
            if raw_base.strip() in {"", "output"}:
                base = self._output_root()
            else:
                base = self._output_root() / base
        if use_timestamp_folder is None:
            use_timestamp_folder = self._coerce_bool(self.save_directory_state.get("use_timestamp_folder", True))
        return base / self.session_timestamp if use_timestamp_folder else base

    def _next_save_filename(self, item: Any, extension: str) -> str:
        counter = int(self.save_directory_state.get("save_counter", 1) or 1)
        filename_format = str(self.save_directory_state.get("filename_format") or "number_only")
        if filename_format == "time_number":
            stem = f"{datetime.now().strftime('%H%M%S')}_{counter:05d}"
        elif filename_format == "datetime":
            stem = datetime.now().strftime("%Y%m%d_%H%M%S")
        elif filename_format == "prompt":
            prompt = ""
            params = getattr(item, "generation_params", {}) or {}
            if isinstance(params, dict):
                prompt = str(params.get("input") or params.get("prompt") or "")
            stem = self._safe_filename_stem(prompt or "prompt")
        elif filename_format == "wildcard":
            stem = self._safe_filename_stem(Path(getattr(item, "filename", "") or "wildcard").stem)
        else:
            stem = f"{counter:05d}"
        self.save_directory_state["save_counter"] = counter + 1
        return f"{stem}.{extension}"

    @staticmethod
    def _safe_filename_stem(value: str, *, max_length: int = 120) -> str:
        clean = re.sub(r'[<>:"/\\|?*\x00-\x1F]+', "_", str(value or "")).strip(" ._")
        clean = re.sub(r"\s+", " ", clean)
        return (clean[:max_length].strip(" ._") or "naia-result")

    @staticmethod
    def _unique_output_path(path: Path) -> Path:
        if not path.exists():
            return path
        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        index = 1
        while True:
            candidate = parent / f"{stem} ({index}){suffix}"
            if not candidate.exists():
                return candidate
            index += 1

    @staticmethod
    def _toast(message: str, *, level: str = "info") -> dict[str, Any]:
        return {
            "type": "toast",
            "level": level,
            "message": str(message or ""),
            "headless": True,
        }

    def _character_settings_by_mode(self) -> dict[str, dict[str, Any]]:
        cache = getattr(self, "_character_settings_state", None)
        if not isinstance(cache, dict):
            cache = {}
            self._character_settings_state = cache
        return cache

    def _character_settings_cache(self) -> dict[str, Any]:
        from core.character_settings import load_character_settings

        mode = self.get_api_mode()
        cache = self._character_settings_by_mode()
        if mode not in cache:
            cache[mode] = load_character_settings(
                mode,
                path=self._existing_save_path(f"CharacterModule_{str(mode or 'NAI').upper()}.json"),
            )
        return cache[mode]

    def _save_character_settings(self, mode: str, settings: dict[str, Any]) -> None:
        from core.character_settings import normalize_character_settings

        mode_key = str(mode or "NAI").upper()
        normalized = normalize_character_settings(settings)
        self._character_settings_by_mode()[mode_key] = normalized
        path = self._save_path(f"CharacterModule_{mode_key}.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({mode_key: normalized}, ensure_ascii=False, indent=4),
            encoding="utf-8",
        )

    @staticmethod
    def _index_from_key(key: str, prefix: str) -> int | None:
        try:
            return int(str(key)[len(prefix):])
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _ensure_character_frame(frames: list[dict[str, Any]], index: int) -> dict[str, Any]:
        while len(frames) <= index:
            frames.append({"prompt": "", "uc": "", "is_enabled": False, "slot_state": "inactive", "custom_name": ""})
        frame = frames[index]
        if not isinstance(frame, dict):
            frame = {"prompt": "", "uc": "", "is_enabled": False, "slot_state": "inactive", "custom_name": ""}
            frames[index] = frame
        return frame

    @staticmethod
    def _normalized_webui_hiresfix_assist_state(raw: dict[str, Any] | None = None) -> dict[str, Any]:
        from core.headless_webui_hiresfix_assist_service import HeadlessWebuiHiresfixAssistService

        return HeadlessWebuiHiresfixAssistService.normalized_state(raw)

    def initial_websocket_messages(
        self,
        *,
        session_id: str | None = None,
        client_host: str | None = None,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if session_id:
            messages.append({"type": "session", "session_id": session_id})
        messages.extend([
            self.desktop_window_state_payload(client_host),
            {"type": "mode", "mode": self.get_api_mode()},
            {"type": "options", **self.get_options()},
            self.generation_param_schema_payload(),
            self.queue_state_payload(),
            self.api_status_payload(client_host),
            {"type": "init_complete"},
        ])
        return messages

    def setup_gate(self, client_host: str) -> tuple[bool, str]:
        return self.api_config_service.setup_gate(client_host)

    def cloudflared_gate(self, client_host: str) -> tuple[bool, str]:
        return self.api_config_service.cloudflared_gate(client_host)

    def verify_api(self, mode: str, value: str) -> dict[str, Any]:
        result = self.api_config_service.verify(mode, value)
        self.publish("api_status_changed", self.api_status_payload())
        return result

    def clear_api(self, mode: str) -> dict[str, Any]:
        result = self.api_config_service.clear(mode)
        self.publish("api_status_changed", self.api_status_payload())
        return result

    def probe_api(self) -> dict[str, bool | None]:
        return self.api_config_service.probe()

    def set_cloudflared_enabled(self, enabled: bool) -> dict[str, Any]:
        result = self.api_config_service.cloudflared.set_enabled(enabled)
        status = self.api_config_service.cloudflared.status()
        self.cloudflared_active = bool(status.get("active"))
        self.cloudflared_tunnel_url = str(status.get("url") or "")
        self.cloudflared_status_text = str(status.get("status_text") or "")
        self.publish("cloudflared_status_changed", status)
        return result

    def store_api_payload(self, payload: dict, mode: str) -> None:
        self.last_api_payloads[str(mode or "").upper()] = payload

    @staticmethod
    def _is_loopback_host(host: str) -> bool:
        clean_host = str(host or "").strip()
        if clean_host in {"127.0.0.1", "::1", "localhost"}:
            return True
        try:
            import ipaddress

            return ipaddress.ip_address(clean_host).is_loopback
        except Exception:
            return False


__all__ = [
    "AutocompleteRuntimeState",
    "ApiConfigService",
    "CloudflaredService",
    "InMemoryTokenManager",
    "REMOTE_OPTION_DEFAULTS",
    "SUPPORTED_API_MODES",
    "TokenStore",
    "WebSessionContext",
    "WebSessionEventBus",
]
