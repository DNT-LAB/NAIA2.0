"""PyQt-free service container for the Remote Web runtime.

This module is the Round 31 skeleton for the Web Session migration.
It intentionally does not import the removed desktop application, RemoteBridge,
or Qt-backed controllers. Later rounds can continue moving FastAPI and
generation behavior onto this container without restoring the old WebShell path.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from core.api_config_service import ApiConfigService, CloudflaredService
from core.headless_autocomplete_state import AutocompleteRuntimeState
from core.headless_event_bus import WebSessionEventBus
from core.seam_observer import seam_observer  # 관측 전용(기본 OFF) 이벤트 버스 계측
from core.headless_remote_state_service import REMOTE_OPTION_DEFAULTS, SUPPORTED_API_MODES
from core.headless_result_service import HeadlessResultStore
from core.headless_search_state_service import DEFAULT_ACTIVE_RATINGS
from core.headless_token_store import InMemoryTokenManager, TokenStore
from core.pipeline_run_registry import PipelineRunRegistry, PromptPipelineRun
from app.backend.runtime import RuntimePaths
from core.search_result_model import SearchResultModel


@dataclass
class WebSessionContext:
    """State owner for Remote Web startup and shared status.

    The container deliberately exposes several AppContext-shaped attributes and
    methods so core services can migrate one by one without depending on a
    GUI window instance.
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
    # Per-mode main/negative prompt memory. Mirrors remote_param_planes: each mode
    # keeps its own prompt so switching API mode never shows another mode's prompt
    # (e.g. a NAI random prompt leaking into COMFYUI). prompt_text/negative_prompt_text
    # always reflect the ACTIVE mode's plane; set_api_mode stashes/activates here.
    prompt_planes: dict[str, dict[str, str]] = field(default_factory=dict)
    # Ollama Auto Boost — 세션 전용 토글(비영속). 항상 OFF로 시작하고 save/preset에 절대
    # 기록하지 않는다. 사용자가 직접 켜야만 ON이며 Ollama가 준비됐을 때만 enable 가능.
    ollama_auto_boost: bool = False
    remote_options: dict[str, bool] = field(default_factory=lambda: dict(REMOTE_OPTION_DEFAULTS))
    remote_params: dict[str, Any] = field(default_factory=dict)
    remote_param_planes: dict[str, dict[str, Any]] = field(default_factory=dict)
    remote_option_cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    autocomplete_state: AutocompleteRuntimeState = field(default_factory=AutocompleteRuntimeState)
    desktop_adapter: Any = None
    api_config_service: ApiConfigService | None = None
    wildcard_manager: Any = None
    tag_data_manager: Any = None
    filter_data_manager: Any = None
    search_results: SearchResultModel = field(default_factory=SearchResultModel)
    search_results_snapshot: Any = None
    search_results_master_base_snapshot: Any = None
    search_query_ratings: set[str] = field(default_factory=lambda: set(DEFAULT_ACTIVE_RATINGS))
    active_tag_filter_ids: set[Any] | None = None
    pending_tag_filter: dict[str, Any] | None = None
    pending_tag_filters: dict[str, dict[str, Any]] = field(default_factory=dict)
    active_tag_filter: dict[str, Any] | None = None
    current_source_row: Any = None
    current_prompt_context: Any = None
    pipeline_run_registry: PipelineRunRegistry = field(default_factory=PipelineRunRegistry)
    result_store: HeadlessResultStore = field(default_factory=HeadlessResultStore)
    headless_generation_execute_enabled: bool = True
    auto_save_state: dict[str, Any] = field(default_factory=dict)
    save_directory_state: dict[str, Any] = field(default_factory=dict)
    webui_hiresfix_assist_state: dict[str, Any] = field(default_factory=dict)
    character_reference_frames: list[dict[str, Any]] = field(default_factory=list)
    # Interactive 전용. 위 목록과 **섞이지 않는다** — 상태를 공유하면 NAI 쪽에서
    # 켜 둔 프레임이 Interactive 생성에 몰래 섞인다(2026-08-04 사용자 지적).
    interactive_reference_frames: list[dict[str, Any]] = field(default_factory=list)
    vibe_transfer_frames: list[dict[str, Any]] = field(default_factory=list)
    vibe_transfer_normalize: bool = False
    img2img_session: dict[str, Any] = field(default_factory=dict)
    result_enhance_config: dict[str, Any] = field(default_factory=lambda: {
        "upscale": 1.5,
        "strength": 0.2,
        "noise": 0.0,
    })
    _img2img_window_counter: int = 0
    _service_cache: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        from core.headless_context_bootstrap import initialize_web_session_context

        # Interactive 스냅샷 훅이 세션을 찾을 수 있게 역참조를 심는다. 결과 저장소는
        # 컨텍스트 필드라 순환이 아니고, 훅은 이것이 없으면 조용히 아무것도 안 한다.
        self.result_store._context = self

        # Authoritative search-pool ownership. A tag-filter search may run in a
        # worker while another websocket replaces the active parquet/search
        # snapshot. The generation token + lock let the result/assign path prove
        # that it still belongs to the same pool before committing it.
        self._search_pool_state_lock = threading.RLock()
        self._search_pool_generation = 0
        # Monotonic ordering token for every authoritative tag-filter mutation.
        # Pool generation proves dataset ownership; this independent revision
        # lets each browser reject an older websocket payload that arrives after
        # a newer assignment/clear/consume transition from another tab.
        self._tag_filter_revision = 0
        initialize_web_session_context(self)
        # Pool-loading ownership (Tag/Tag-Filter lock + Random gate + toast). Both
        # the chunked parquet loader (LOAD phase) and the tag-filter index build /
        # matching (FILTER phase) announce through the SAME depth counter so one
        # phase's end can't clear the other's still-active flag, and so a concurrent
        # get_search_state keeps short-circuiting until the LAST operation ends.
        self._pool_loading_lock = threading.Lock()
        self._pool_loading_depth = 0
        self._search_pool_loading = {"active": False, "loaded": 0, "total": 0, "phase": None}

    def _create_event_stream_runtime(self):
        return self._event_stream_service().runtime(create=True)

    def _lazy_service(self, service_name: str):
        service = self._service_cache.get(service_name)
        if service is None:
            from core.headless_service_registry import get_headless_service_spec

            service = get_headless_service_spec(service_name).create(self)
            self._service_cache[service_name] = service
        return service

    def _img2img_service(self):
        return self._lazy_service("img2img")

    def _character_reference_service(self):
        return self._lazy_service("character_reference")

    def _interactive_reference_service(self):
        return self._lazy_service("interactive_reference")

    def _character_asset_service(self):
        return self._lazy_service("character_asset")

    def _vibe_transfer_service(self):
        return self._lazy_service("vibe_transfer")

    def _viewer_binding_service(self):
        return self._lazy_service("viewer_binding")

    def _nai_model_registry(self):
        return self._lazy_service("nai_model_registry")

    def _image_module_param_service(self):
        return self._lazy_service("image_module_param")

    def _automation_service(self):
        return self._lazy_service("automation")

    def _webui_hiresfix_assist_service(self):
        return self._lazy_service("webui_hiresfix_assist")

    def _event_stream_service(self):
        return self._lazy_service("event_stream")

    def _prompt_engineering_service(self):
        return self._lazy_service("prompt_engineering")

    def _conditional_prompt_service(self):
        return self._lazy_service("conditional_prompt")

    def _character_service(self):
        return self._lazy_service("character")

    def _memo_service(self):
        return self._lazy_service("memo")

    def _memo_module_state(self):
        return self._memo_service().state()

    def _set_memo_param(self, key, value):
        return self._memo_service().set_param(key, value)

    def _v5_scene_service(self):
        return self._lazy_service("v5_scene")

    def _v5_scene_module_state(self):
        return self._v5_scene_service().state()

    def _set_v5_scene_param(self, key, value):
        return self._v5_scene_service().set_param(key, value)

    def _wildcard_service(self):
        return self._lazy_service("wildcard")

    def _instant_wildcard_service(self):
        return self._lazy_service("instant_wildcard")

    def _save_service(self):
        return self._lazy_service("save")

    def _search_state_service(self):
        return self._lazy_service("search_state")

    def _session_state_service(self):
        return self._lazy_service("session_state")

    def _runtime_path_service(self):
        return self._lazy_service("runtime_path")

    def _pipeline_run_service(self):
        return self._lazy_service("pipeline_run")

    def _pipeline_hook_service(self):
        return self._lazy_service("pipeline_hook")

    def _api_control_service(self):
        return self._lazy_service("api_control")

    def _api_option_service(self):
        return self._lazy_service("api_options")

    def _remote_state_service(self):
        return self._lazy_service("remote_state")

    def _module_dispatch_service(self):
        return self._lazy_service("module_dispatch")

    def subscribe(self, event_name: str, callback: Callable[..., Any]) -> None:
        self.event_bus.subscribe(event_name, callback)
        if seam_observer.enabled:
            seam_observer.observe_subscribe(event_name, callback)

    def unsubscribe(self, event_name: str, callback: Callable[..., Any]) -> None:
        self.event_bus.unsubscribe(event_name, callback)

    def publish(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        if seam_observer.enabled:
            seam_observer.observe_publish(event_name)
        self.event_bus.publish(event_name, *args, **kwargs)

    # ── Search-pool snapshot ownership ──────────────────────────────────────
    def search_pool_state_guard(self):
        """Return the re-entrant lock guarding pool replacement/filter commit."""
        return self._search_pool_state_lock

    def search_pool_generation(self) -> int:
        return int(getattr(self, "_search_pool_generation", 0) or 0)

    def mark_search_pool_replaced(self) -> int:
        """Advance the identity token after installing a new authoritative pool.

        Callers that already hold ``search_pool_state_guard`` may call this safely;
        the lock is re-entrant because replacement and generation publication are
        one state transition.
        """
        with self._search_pool_state_lock:
            self._search_pool_generation = self.search_pool_generation() + 1
            return self._search_pool_generation

    def tag_filter_revision(self) -> int:
        return int(getattr(self, "_tag_filter_revision", 0) or 0)

    def mark_tag_filter_changed(self) -> int:
        """Advance the authoritative tag-filter ordering token.

        State mutations call this while holding ``search_pool_state_guard``.
        The re-entrant fallback here also keeps direct/legacy callers atomic.
        """
        with self._search_pool_state_lock:
            self._tag_filter_revision = self.tag_filter_revision() + 1
            return self._tag_filter_revision

    # ── Pool-loading ownership ────────────────────────────────────────────────
    # Depth-counted so overlapping LOAD (parquet chunk read) and FILTER (tag-filter
    # index build/match) operations don't clear each other's loading flag. The WS
    # event is published WHILE the lock is held so its observable order matches the
    # state transition — a progress tick that loses the race to a final ``end`` sees
    # depth 0 under the same lock and skips, so the frontend never gets a stale
    # ``loading:true`` after ``loading:false`` (which would strand the lock). Only
    # the non-blocking headless bridge subscribes to this event, so publishing under
    # the lock cannot deadlock; a subscriber must not re-enter these methods.
    def _pool_loading_publish(self, payload: dict) -> None:
        try:
            self.publish("search_pool_broadcast", payload)
        except Exception:
            pass

    def pool_loading_begin(self, phase: str | None = None) -> None:
        lock = getattr(self, "_pool_loading_lock", None)
        if lock is None:  # defensive: pre-__post_init__ / test doubles
            return
        with lock:
            self._pool_loading_depth = int(getattr(self, "_pool_loading_depth", 0) or 0) + 1
            self._search_pool_loading = {"active": True, "loaded": 0, "total": 0, "phase": phase}
            if self._pool_loading_depth == 1:  # 0 -> 1 edge only
                payload = {"type": "search_loading", "loading": True, "loaded": 0, "total": 0}
                if phase:
                    payload["phase"] = phase
                self._pool_loading_publish(payload)

    def pool_loading_end(self) -> None:
        lock = getattr(self, "_pool_loading_lock", None)
        if lock is None:
            return
        with lock:
            depth = int(getattr(self, "_pool_loading_depth", 0) or 0)
            if depth <= 0:  # unbalanced end -> no publish (never a spurious 0->0 false)
                self._pool_loading_depth = 0
                return
            depth -= 1
            self._pool_loading_depth = depth
            if depth == 0:  # 1 -> 0 edge only
                self._search_pool_loading = {"active": False, "loaded": 0, "total": 0, "phase": None}
                self._pool_loading_publish({"type": "search_loading", "loading": False})

    def pool_loading_progress(self, phase: str | None, loaded: int, total: int) -> None:
        lock = getattr(self, "_pool_loading_lock", None)
        if lock is None:
            return
        with lock:
            if int(getattr(self, "_pool_loading_depth", 0) or 0) <= 0:
                return  # not owned -> ignore stray tick (and never publish after end)
            self._search_pool_loading = {
                "active": True, "loaded": int(loaded or 0), "total": int(total or 0), "phase": phase,
            }
            payload = {"type": "search_loading", "loading": True, "loaded": int(loaded or 0), "total": int(total or 0)}
            if phase:
                payload["phase"] = phase
            self._pool_loading_publish(payload)

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

    def save_remote_ui_state(self) -> dict[str, Any]:
        from core.headless_remote_ui_state_service import save_remote_ui_state

        return save_remote_ui_state(self)

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

    def last_search_parquet_path(self) -> Path:
        return self._search_state_service().last_search_parquet_path()

    def persist_last_search(self):
        return self._search_state_service().persist_last_search()

    def restore_last_search(self, progress=None) -> bool:
        return self._search_state_service().restore_last_search(progress=progress)

    def runner_parquet_sources(self) -> list[tuple[Path, str]]:
        return self._search_state_service().runner_parquet_sources()

    def tag_archive_parquet_sources(self) -> list[tuple[Path, str]]:
        return self._search_state_service().tag_archive_parquet_sources()

    def custom_parquet_names(self) -> list[str]:
        return self._search_state_service().custom_parquet_names()

    def search_state_payload(self) -> dict[str, Any]:
        # Keep the tag-filter fields and their revision from one atomic view.
        # This lock is re-entrant because assignment/clear paths build the state
        # while already holding the same ownership guard.
        with self._search_pool_state_lock:
            return self._search_state_service().search_state_payload()

    def get_filter_presets(self) -> list:
        return self._search_state_service().get_filter_presets()

    def save_filter_preset(self, name: Any, include: Any = None, exclude: Any = None) -> list:
        return self._search_state_service().save_filter_preset(name, include, exclude)

    def delete_filter_preset(self, name: Any) -> list:
        return self._search_state_service().delete_filter_preset(name)

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
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        return self._module_dispatch_service().set_module_param(
            module_id,
            key,
            value,
            client_host=client_host,
        )

    def save_unsaved_history(self) -> dict[str, Any]:
        return self._save_service().save_unsaved_history()

    def save_history_item(self, item: Any) -> dict[str, Any]:
        return self._save_service().save_history_item(item)

    def save_history_items(
        self,
        items: list[Any],
        *,
        save_as_webp: bool = True,
        same_directory: bool = True,
    ) -> dict[str, Any]:
        return self._save_service().save_history_items(
            items,
            save_as_webp=save_as_webp,
            same_directory=same_directory,
        )

    def _prompt_engineering_module_state(self) -> dict[str, Any]:
        return self._prompt_engineering_service().state()

    def persist_prompt_engineering_settings(self) -> tuple[bool, str]:
        return self._prompt_engineering_service().persist_active_settings()

    def _set_prompt_engineering_param(self, key: str, value: Any) -> dict[str, Any] | None:
        return self._prompt_engineering_service().set_param(key, value)

    def sync_param_into_current_preset(self, key: str) -> str:
        return self._prompt_engineering_service().sync_param_into_current_preset(key)

    def sync_negative_into_current_preset(self) -> str:
        return self._prompt_engineering_service().sync_negative_into_current_preset()

    def sync_prompt_into_current_preset(self, stamp: str = "") -> str:
        return self._prompt_engineering_service().sync_prompt_into_current_preset(stamp)

    def stale_prompt_edit(self, origin: str, stamp: str) -> bool:
        return self._prompt_engineering_service().stale_prompt_edit(origin, stamp)

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

    def _is_naid5_model(self) -> bool:
        return self._remote_state_service().is_naid5_model()

    def _nai_model_supports_vibe(self) -> bool:
        return self._remote_state_service().nai_model_supports_vibe()

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

    def _vibe_transfer_begin_encode(self, key: str) -> list[dict[str, Any]]:
        return self._vibe_transfer_service().begin_encode(key)

    def _vibe_transfer_perform_encode(self, key: str, value: Any = None) -> list[dict[str, Any]]:
        return self._vibe_transfer_service().perform_encode(key, value)

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
        resize_1mp: bool = True,
    ) -> dict[str, Any]:
        return self._img2img_service().open_session_from_bytes(
            image_bytes,
            label=label,
            mode=mode,
            generation_params=generation_params,
            prompt_context=prompt_context,
            resize_1mp=resize_1mp,
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

    def _storyteller_service(self):
        return self._lazy_service("storyteller")

    def _storyteller_module_state(self) -> dict[str, Any]:
        return self._storyteller_service().state()

    def _set_storyteller_param(self, key: str, value: Any) -> dict[str, Any] | None:
        return self._storyteller_service().set_param(key, value)

    def _sequence_run_service(self):
        return self._lazy_service("sequence_run")

    def _sequence_run_module_state(self) -> dict[str, Any]:
        return self._sequence_run_service().state()

    def _set_sequence_run_param(self, key: str, value: Any) -> dict[str, Any] | None:
        return self._sequence_run_service().set_param(key, value)

    # I.Sequence(Inpaint Sequence) — Sequence 의 복제본이며 런 상태만 따로 가진다.
    # 이벤트 그룹 검색(`sequence_preset_service`)은 공유한다.
    def _inpaint_sequence_run_service(self):
        return self._lazy_service("inpaint_sequence_run")

    def _inpaint_sequence_run_module_state(self) -> dict[str, Any]:
        return self._inpaint_sequence_run_service().state()

    def _set_inpaint_sequence_run_param(self, key: str, value: Any) -> dict[str, Any] | None:
        return self._inpaint_sequence_run_service().set_param(key, value)

    def _e621_event_service(self):
        return self._lazy_service("e621_event")

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

    def _retired_module_state(self, module_id: str, *, action: str | None = None) -> dict[str, Any]:
        return self._module_dispatch_service().retired_module_state(module_id, action=action)

    def autocomplete_status_payload(self) -> dict[str, Any]:
        return self._session_state_service().autocomplete_status_payload()

    def api_status_payload(self, client_host: str | None = None) -> dict[str, Any]:
        return self._session_state_service().api_status_payload(client_host)

    def http_status_payload(self) -> dict[str, Any]:
        return self._session_state_service().http_status_payload()

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

    def resolution_options_for_mode(self, mode: str | None = None) -> list[str]:
        return self._session_state_service().resolution_options_for_mode(mode)

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

    def account_gate(self, client_host: str) -> tuple[bool, str]:
        return self.api_config_service.account_gate(client_host)

    def verify_api(self, mode: str, value: str) -> dict[str, Any]:
        return self._api_control_service().verify_api(mode, value)

    def clear_api(self, mode: str) -> dict[str, Any]:
        return self._api_control_service().clear_api(mode)

    def probe_api(self) -> dict[str, bool | None]:
        return self._api_control_service().probe_api()

    def refresh_api_options(self, mode: str) -> dict[str, Any]:
        return self._api_option_service().refresh(mode)

    def clear_api_options(self, mode: str) -> None:
        self._api_option_service().clear(mode)

    def begin_cloudflared_connect(self) -> dict[str, Any]:
        return self._api_control_service().begin_cloudflared_connect()

    def set_cloudflared_enabled(self, enabled: bool) -> dict[str, Any]:
        return self._api_control_service().set_cloudflared_enabled(enabled)

    def store_api_payload(self, payload: dict, mode: str) -> None:
        self._api_control_service().store_api_payload(payload, mode)


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
