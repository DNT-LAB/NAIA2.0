"""PyQt-free service container for the Remote Web headless runtime.

This module is the Round 31 skeleton for the headless Web Session migration.
It intentionally does not import the desktop application, RemoteBridge, or
Qt-backed controllers. Later rounds can move FastAPI and generation behavior
onto this container incrementally while the desktop-backed WebShell remains
available as a compatibility path.
"""

from __future__ import annotations

import importlib
import os
import weakref
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Protocol

from core.api_config_service import ApiConfigService, CloudflaredService
from core.headless_remote_state_service import REMOTE_OPTION_DEFAULTS, SUPPORTED_API_MODES
from core.headless_search_state_service import SUPPORTED_RATINGS
from core.headless_result_service import HeadlessResultStore
from core.pipeline_run_registry import PipelineRunRegistry, PromptPipelineRun
from app.backend.runtime import RuntimePaths, resolve_runtime_paths
from core.search_result_model import SearchResultModel


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
    _headless_character_service: Any = field(default=None, init=False, repr=False)
    _headless_wildcard_service: Any = field(default=None, init=False, repr=False)
    _headless_instant_wildcard_service: Any = field(default=None, init=False, repr=False)
    _headless_save_service: Any = field(default=None, init=False, repr=False)
    _headless_search_state_service: Any = field(default=None, init=False, repr=False)
    _headless_session_state_service: Any = field(default=None, init=False, repr=False)
    _headless_runtime_path_service: Any = field(default=None, init=False, repr=False)
    _headless_pipeline_run_service: Any = field(default=None, init=False, repr=False)
    _headless_pipeline_hook_service: Any = field(default=None, init=False, repr=False)
    _headless_api_control_service: Any = field(default=None, init=False, repr=False)
    _headless_remote_state_service: Any = field(default=None, init=False, repr=False)
    _headless_module_dispatch_service: Any = field(default=None, init=False, repr=False)
    _headless_image_module_param_service: Any = field(default=None, init=False, repr=False)

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
        self.event_stream_runtime = None

    def _create_event_stream_runtime(self):
        return self._event_stream_service().runtime(create=True)

    def _lazy_service(self, attr_name: str, module_name: str, class_name: str):
        service = getattr(self, attr_name)
        if service is None:
            module = importlib.import_module(module_name)
            service = getattr(module, class_name)(self)
            setattr(self, attr_name, service)
        return service

    def _img2img_service(self):
        return self._lazy_service(
            "_headless_img2img_service",
            "core.headless_img2img_service",
            "HeadlessImg2ImgService",
        )

    def _character_reference_service(self):
        return self._lazy_service(
            "_headless_character_reference_service",
            "core.headless_character_reference_service",
            "HeadlessCharacterReferenceService",
        )

    def _vibe_transfer_service(self):
        return self._lazy_service(
            "_headless_vibe_transfer_service",
            "core.headless_vibe_transfer_service",
            "HeadlessVibeTransferService",
        )

    def _image_module_param_service(self):
        return self._lazy_service(
            "_headless_image_module_param_service",
            "core.headless_image_module_param_service",
            "HeadlessImageModuleParamService",
        )

    def _automation_service(self):
        return self._lazy_service(
            "_headless_automation_service",
            "core.headless_automation_service",
            "HeadlessAutomationService",
        )

    def _webui_hiresfix_assist_service(self):
        return self._lazy_service(
            "_headless_webui_hiresfix_assist_service",
            "core.headless_webui_hiresfix_assist_service",
            "HeadlessWebuiHiresfixAssistService",
        )

    def _event_stream_service(self):
        return self._lazy_service(
            "_headless_event_stream_service",
            "core.headless_event_stream_service",
            "HeadlessEventStreamService",
        )

    def _prompt_engineering_service(self):
        return self._lazy_service(
            "_headless_prompt_engineering_service",
            "core.headless_prompt_engineering_service",
            "HeadlessPromptEngineeringService",
        )

    def _conditional_prompt_service(self):
        return self._lazy_service(
            "_headless_conditional_prompt_service",
            "core.headless_conditional_prompt_service",
            "HeadlessConditionalPromptService",
        )

    def _character_service(self):
        return self._lazy_service(
            "_headless_character_service",
            "core.headless_character_service",
            "HeadlessCharacterService",
        )

    def _wildcard_service(self):
        return self._lazy_service(
            "_headless_wildcard_service",
            "core.headless_wildcard_service",
            "HeadlessWildcardService",
        )

    def _instant_wildcard_service(self):
        return self._lazy_service(
            "_headless_instant_wildcard_service",
            "core.headless_instant_wildcard_service",
            "HeadlessInstantWildcardService",
        )

    def _save_service(self):
        return self._lazy_service(
            "_headless_save_service",
            "core.headless_save_service",
            "HeadlessSaveService",
        )

    def _search_state_service(self):
        return self._lazy_service(
            "_headless_search_state_service",
            "core.headless_search_state_service",
            "HeadlessSearchStateService",
        )

    def _session_state_service(self):
        return self._lazy_service(
            "_headless_session_state_service",
            "core.headless_session_state_service",
            "HeadlessSessionStateService",
        )

    def _runtime_path_service(self):
        return self._lazy_service(
            "_headless_runtime_path_service",
            "core.headless_runtime_path_service",
            "HeadlessRuntimePathService",
        )

    def _pipeline_run_service(self):
        return self._lazy_service(
            "_headless_pipeline_run_service",
            "core.headless_pipeline_run_service",
            "HeadlessPipelineRunService",
        )

    def _pipeline_hook_service(self):
        return self._lazy_service(
            "_headless_pipeline_hook_service",
            "core.headless_pipeline_hook_service",
            "HeadlessPipelineHookService",
        )

    def _api_control_service(self):
        return self._lazy_service(
            "_headless_api_control_service",
            "core.headless_api_control_service",
            "HeadlessApiControlService",
        )

    def _remote_state_service(self):
        return self._lazy_service(
            "_headless_remote_state_service",
            "core.headless_remote_state_service",
            "HeadlessRemoteStateService",
        )

    def _module_dispatch_service(self):
        return self._lazy_service(
            "_headless_module_dispatch_service",
            "core.headless_module_dispatch_service",
            "HeadlessModuleDispatchService",
        )

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
        self._pipeline_hook_service().register_pipeline_hook(hook_info, module_instance)

    def get_pipeline_hooks(self, pipeline_name: str, hook_point: str) -> list[Any]:
        return self._pipeline_hook_service().get_pipeline_hooks(pipeline_name, hook_point)

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
        return self._pipeline_run_service().start_prompt_run(
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
        return self._pipeline_run_service().complete_prompt_run(
            prompt_run_id,
            context=context,
            final_prompt=final_prompt,
            metadata=metadata,
        )

    def fail_prompt_run(
        self,
        prompt_run_id: str,
        error: str,
        *,
        context: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> PromptPipelineRun | None:
        return self._pipeline_run_service().fail_prompt_run(
            prompt_run_id,
            error,
            context=context,
            metadata=metadata,
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
        return self._pipeline_run_service().record_prompt_run_hook(
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
        return self._pipeline_run_service().record_prompt_run_warning(prompt_run_id, warning)

    def record_prompt_run_derived(
        self,
        prompt_run_id: str,
        derived: dict[str, Any] | None,
    ) -> PromptPipelineRun | None:
        return self._pipeline_run_service().record_prompt_run_derived(prompt_run_id, derived)

    def link_generation_to_prompt_run(
        self,
        prompt_run_id: str,
        generation_request_id: str,
    ) -> PromptPipelineRun | None:
        return self._pipeline_run_service().link_generation_to_prompt_run(prompt_run_id, generation_request_id)

    def get_prompt_run_payload(self, prompt_run_id: str, *, include_source_row: bool = False) -> dict[str, Any] | None:
        return self._pipeline_run_service().get_prompt_run_payload(
            prompt_run_id,
            include_source_row=include_source_row,
        )

    def prompt_runs_payload(self, limit: int = 50) -> dict[str, Any]:
        return self._pipeline_run_service().prompt_runs_payload(limit)

    def get_api_mode(self) -> str:
        return self._remote_state_service().get_api_mode()

    def set_api_mode(self, mode: str) -> None:
        self._remote_state_service().set_api_mode(mode)

    def set_option(self, key: str, value: Any) -> None:
        self._remote_state_service().set_option(key, value)

    def get_options(self) -> dict[str, bool]:
        return self._remote_state_service().get_options()

    def set_param(self, key: str, value: Any) -> None:
        self._remote_state_service().set_param(key, value)

    def set_active_ratings(self, ratings: Any) -> set[str]:
        return self._search_state_service().set_active_ratings(ratings)

    def get_active_ratings(self) -> set[str]:
        return self._search_state_service().get_active_ratings()

    def _save_root(self) -> Path:
        return self._runtime_path_service().save_root()

    def _output_root(self) -> Path:
        return self._runtime_path_service().output_root()

    def _legacy_save_root(self) -> Path:
        return self._runtime_path_service().legacy_save_root()

    def _legacy_save_fallback_enabled(self) -> bool:
        return self._runtime_path_service().legacy_save_fallback_enabled()

    def _save_path(self, *parts: str | Path) -> Path:
        return self._runtime_path_service().save_path(*parts)

    def _legacy_save_path(self, *parts: str | Path) -> Path:
        return self._runtime_path_service().legacy_save_path(*parts)

    def _existing_save_path(self, *parts: str | Path) -> Path:
        return self._runtime_path_service().existing_save_path(*parts)

    def _existing_save_dirs(self, *parts: str | Path) -> list[Path]:
        return self._runtime_path_service().existing_save_dirs(*parts)

    def _search_filter_state_path(self) -> Path:
        return self._search_state_service().search_filter_state_path()

    def default_search_filter_state(self) -> dict[str, Any]:
        return self._search_state_service().default_search_filter_state()

    def normalize_rating_list(self, ratings: Any) -> list[str]:
        return self._search_state_service().normalize_rating_list(ratings)

    @staticmethod
    def normalize_filter_tags(tags: Any) -> list[str]:
        from core.headless_search_state_service import HeadlessSearchStateService

        return HeadlessSearchStateService.normalize_filter_tags(tags)

    def normalize_search_filter_state(self, raw: Any) -> dict[str, Any]:
        return self._search_state_service().normalize_search_filter_state(raw)

    def _load_search_filter_state(self) -> dict[str, Any]:
        return self._search_state_service().load_search_filter_state()

    def save_search_filter_state(self, **updates: Any) -> dict[str, Any]:
        return self._search_state_service().save_search_filter_state(**updates)

    def save_search_filter_state_from_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._search_state_service().save_search_filter_state_from_payload(payload)

    def custom_parquet_dir(self) -> Path:
        return self._search_state_service().custom_parquet_dir()

    def runner_parquet_path(self) -> Path:
        return self._search_state_service().runner_parquet_path()

    def runner_parquet_sources(self) -> list[tuple[Path, str]]:
        return self._search_state_service().runner_parquet_sources()

    def custom_parquet_names(self) -> list[str]:
        return self._search_state_service().custom_parquet_names()

    def search_state_payload(self) -> dict[str, Any]:
        return self._search_state_service().search_state_payload()

    def auto_save_state_payload(self) -> dict[str, Any]:
        return self._save_service().auto_save_state_payload()

    def save_directory_state_payload(self, client_host: str | None = None) -> dict[str, Any]:
        return self._save_service().save_directory_state_payload(client_host)

    def module_state_payload(self, module_id: str, client_host: str | None = None) -> dict[str, Any]:
        return self._module_dispatch_service().module_state_payload(module_id, client_host)

    def set_module_param(
        self,
        module_id: str,
        key: str,
        value: Any,
        *,
        client_host: str | None = None,
    ) -> dict[str, Any] | None:
        return self._module_dispatch_service().set_module_param(
            module_id,
            key,
            value,
            client_host=client_host,
        )

    def save_unsaved_history(self) -> dict[str, Any]:
        return self._save_service().save_unsaved_history()

    def _prompt_engineering_module_state(self) -> dict[str, Any]:
        return self._prompt_engineering_service().state()

    def _set_prompt_engineering_param(self, key: str, value: Any) -> dict[str, Any] | None:
        return self._prompt_engineering_service().set_param(key, value)

    def _conditional_prompt_module_state(self) -> dict[str, Any]:
        return self._conditional_prompt_service().state()

    def _set_conditional_prompt_param(self, key: str, value: Any) -> dict[str, Any] | None:
        return self._conditional_prompt_service().set_param(key, value)

    def _character_module_state(self) -> dict[str, Any]:
        return self._character_service().state()

    def _set_character_param(self, key: str, value: Any) -> dict[str, Any] | None:
        return self._character_service().set_param(key, value)

    def _current_model_key(self) -> str:
        return self._remote_state_service().current_model_key()

    def _is_naid45_model(self) -> bool:
        return self._remote_state_service().is_naid45_model()

    def _is_naid3_model(self) -> bool:
        return self._remote_state_service().is_naid3_model()

    @staticmethod
    def _image_hash(image_bytes: bytes) -> str:
        from core.headless_image_utils import image_hash

        return image_hash(image_bytes)

    @staticmethod
    def _data_url_payload(value: str) -> str:
        from core.headless_image_utils import data_url_payload

        return data_url_payload(value)

    @staticmethod
    def _image_to_png_bytes(image) -> bytes:
        from core.headless_image_utils import image_to_png_bytes

        return image_to_png_bytes(image)

    @staticmethod
    def _thumbnail_b64(image, max_side: int = 128) -> str:
        from core.headless_image_utils import thumbnail_b64

        return thumbnail_b64(image, max_side=max_side)

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
        return self._image_module_param_service().active_character_reference_params()

    def active_vibe_transfer_params(self) -> dict[str, Any]:
        return self._image_module_param_service().active_vibe_transfer_params()

    def apply_headless_image_module_params(self, params: dict[str, Any], api_mode: str) -> None:
        self._image_module_param_service().apply(params, api_mode)

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
        return self._wildcard_service().state()

    def _set_wildcard_param(self, key: str, value: Any) -> dict[str, Any] | None:
        return self._wildcard_service().set_param(key, value)

    def _instant_wildcard_store(self, *, force: bool = False) -> dict[str, Any]:
        return self._instant_wildcard_service().store(force=force)

    def _apply_instant_wildcard_to_manager(self, store: dict[str, Any]) -> None:
        self._instant_wildcard_service().apply_to_manager(store)

    def _instant_wildcard_module_state(self) -> dict[str, Any]:
        return self._instant_wildcard_service().state()

    def _chunk_module_state(self) -> dict[str, Any]:
        return self._instant_wildcard_service().chunk_state()

    def _set_instant_wildcard_param(self, key: str, value: Any) -> dict[str, Any] | None:
        return self._instant_wildcard_service().set_param(key, value)

    def _wildcard_base_dir(self) -> Path:
        return self._wildcard_service().base_dir()

    def _validate_wildcard_path(self, rel_path: str) -> Path | None:
        return self._wildcard_service().validate_path(rel_path)

    def _scan_wildcard_tree(self) -> list[dict[str, Any]]:
        return self._wildcard_service().scan_tree()

    def _read_wildcard_file(self, rel_path: str) -> str | None:
        return self._wildcard_service().read_file(rel_path)

    def _save_wildcard_file(self, rel_path: str, content: str) -> dict[str, Any]:
        return self._wildcard_service().save_file(rel_path, content)

    def _delete_wildcard_file(self, rel_path: str) -> dict[str, Any]:
        return self._wildcard_service().delete_file(rel_path)

    def _create_wildcard_file(self, rel_path: str) -> dict[str, Any]:
        return self._wildcard_service().create_file(rel_path)

    def _preview_wildcard(self, name: str) -> str:
        return self._wildcard_service().preview(name)

    def _reload_wildcard_manager(self) -> None:
        self._wildcard_service().reload_manager()

    def hires_overlay_response(self, preset_name: str) -> dict[str, Any]:
        return self._prompt_engineering_service().hires_overlay_response(preset_name)

    def write_hires_overlay(self, preset_name: str, body: dict[str, Any] | None) -> tuple[bool, str]:
        return self._prompt_engineering_service().write_hires_overlay(preset_name, body)

    def reset_hires_overlay(self, preset_name: str) -> tuple[bool, str]:
        return self._prompt_engineering_service().reset_hires_overlay(preset_name)

    def _hires_overlay_path(self, preset_name: str) -> Path | None:
        return self._prompt_engineering_service().hires_overlay_path(preset_name)

    def _retired_module_state(self, module_id: str, *, action: str | None = None) -> dict[str, Any]:
        return self._module_dispatch_service().retired_module_state(module_id, action=action)

    def autocomplete_status_payload(self) -> dict[str, Any]:
        return self._session_state_service().autocomplete_status_payload()

    def api_status_payload(self, client_host: str | None = None) -> dict[str, Any]:
        return self._session_state_service().api_status_payload(client_host)

    def http_status_payload(self) -> dict[str, Any]:
        return self._session_state_service().http_status_payload()

    def desktop_window_state_payload(self, client_host: str | None = None) -> dict[str, Any]:
        return self._session_state_service().desktop_window_state_payload(client_host)

    def queue_state_payload(self) -> dict[str, Any]:
        return self._session_state_service().queue_state_payload()

    @staticmethod
    def _queue_preview(value: Any, limit: int = 140) -> str:
        from core.headless_session_state_service import HeadlessSessionStateService

        return HeadlessSessionStateService.queue_preview(value, limit)

    def _queue_param_summary(self, params: dict[str, Any] | None = None, request: Any = None) -> dict[str, Any]:
        return self._session_state_service().queue_param_summary(params, request=request)

    def _serialize_queue_request(self, request: Any, position: int | None = None) -> dict[str, Any]:
        return self._session_state_service().serialize_queue_request(request, position)

    def generation_param_schema_payload(self) -> dict[str, Any]:
        return self._session_state_service().generation_param_schema_payload()

    @staticmethod
    def _coerce_remote_param(key: str, value: Any) -> Any:
        from core.headless_remote_state_service import HeadlessRemoteStateService

        return HeadlessRemoteStateService.coerce_remote_param(key, value)

    @staticmethod
    def _model_options_for_mode(mode: str) -> list[str]:
        from core.headless_session_state_service import HeadlessSessionStateService

        return HeadlessSessionStateService.model_options_for_mode(mode)

    @staticmethod
    def _sampler_options_for_mode(mode: str) -> list[str]:
        from core.headless_session_state_service import HeadlessSessionStateService

        return HeadlessSessionStateService.sampler_options_for_mode(mode)

    @staticmethod
    def _scheduler_options_for_mode(mode: str) -> list[str]:
        from core.headless_session_state_service import HeadlessSessionStateService

        return HeadlessSessionStateService.scheduler_options_for_mode(mode)

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        from core.headless_remote_state_service import HeadlessRemoteStateService

        return HeadlessRemoteStateService.coerce_bool(value)

    @staticmethod
    def _coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
        from core.headless_payload_utils import coerce_int

        return coerce_int(value, default=default, minimum=minimum, maximum=maximum)

    def _module_state_payload(self, module_id: str, state: dict[str, Any]) -> dict[str, Any]:
        from core.headless_payload_utils import module_state_payload

        return module_state_payload(module_id, state)

    def _current_save_directory(
        self,
        base_path: str | None = None,
        use_timestamp_folder: bool | None = None,
    ) -> Path:
        return self._save_service().current_save_directory(base_path, use_timestamp_folder)

    def _next_save_filename(self, item: Any, extension: str) -> str:
        return self._save_service().next_save_filename(item, extension)

    @staticmethod
    def _safe_filename_stem(value: str, *, max_length: int = 120) -> str:
        from core.headless_save_service import HeadlessSaveService

        return HeadlessSaveService.safe_filename_stem(value, max_length=max_length)

    @staticmethod
    def _unique_output_path(path: Path) -> Path:
        from core.headless_save_service import HeadlessSaveService

        return HeadlessSaveService.unique_output_path(path)

    @staticmethod
    def _toast(message: str, *, level: str = "info") -> dict[str, Any]:
        from core.headless_payload_utils import toast

        return toast(message, level=level)

    def _character_settings_by_mode(self) -> dict[str, dict[str, Any]]:
        return self._character_service().settings_by_mode()

    def _character_settings_cache(self) -> dict[str, Any]:
        return self._character_service().settings_cache()

    def _save_character_settings(self, mode: str, settings: dict[str, Any]) -> None:
        self._character_service().save_settings(mode, settings)

    @staticmethod
    def _index_from_key(key: str, prefix: str) -> int | None:
        from core.headless_payload_utils import index_from_key

        return index_from_key(key, prefix)

    @staticmethod
    def _ensure_character_frame(frames: list[dict[str, Any]], index: int) -> dict[str, Any]:
        from core.headless_character_service import HeadlessCharacterService

        return HeadlessCharacterService.ensure_frame(frames, index)

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
        return self._session_state_service().initial_websocket_messages(
            session_id=session_id,
            client_host=client_host,
        )

    def setup_gate(self, client_host: str) -> tuple[bool, str]:
        return self._api_control_service().setup_gate(client_host)

    def cloudflared_gate(self, client_host: str) -> tuple[bool, str]:
        return self._api_control_service().cloudflared_gate(client_host)

    def verify_api(self, mode: str, value: str) -> dict[str, Any]:
        return self._api_control_service().verify_api(mode, value)

    def clear_api(self, mode: str) -> dict[str, Any]:
        return self._api_control_service().clear_api(mode)

    def probe_api(self) -> dict[str, bool | None]:
        return self._api_control_service().probe_api()

    def set_cloudflared_enabled(self, enabled: bool) -> dict[str, Any]:
        return self._api_control_service().set_cloudflared_enabled(enabled)

    def store_api_payload(self, payload: dict, mode: str) -> None:
        self._api_control_service().store_api_payload(payload, mode)

    @staticmethod
    def _is_loopback_host(host: str) -> bool:
        from core.headless_payload_utils import is_loopback_host

        return is_loopback_host(host)


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
