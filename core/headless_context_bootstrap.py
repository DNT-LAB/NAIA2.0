"""Startup helpers for constructing a headless WebSessionContext."""

from __future__ import annotations

import os
import weakref
from datetime import datetime
from pathlib import Path
from typing import Any

from app.backend.runtime import resolve_runtime_paths
from core.api_config_service import ApiConfigService, CloudflaredService
from core.headless_search_state_service import DEFAULT_ACTIVE_RATINGS
from core.headless_remote_ui_state_service import apply_remote_ui_state
from core.web_shell_config import DEFAULT_WEB_SHELL_PORT


def default_token_manager():
    from core.secure_token_manager import SecureTokenManager

    return SecureTokenManager()


def create_queue_manager(context: Any):
    from core.generation_queue_manager import GenerationQueueManager

    return GenerationQueueManager(context)


def initialize_web_session_context(context: Any) -> None:
    if context.token_manager is None:
        context.token_manager = default_token_manager()
    context.secure_token_manager = context.token_manager

    explicit_repo_root = context.repo_root is not None
    context.repo_root = Path(context.repo_root) if explicit_repo_root else Path(__file__).resolve().parent.parent
    if context.runtime_paths is None:
        context.runtime_paths = resolve_runtime_paths(context.repo_root, portable=explicit_repo_root)
    context.runtime_paths.ensure_writable_dirs()

    initialize_desktop_compatibility(context)
    initialize_runtime_state(context)
    apply_remote_ui_state(context)
    ensure_first_run_recommended_preset(context)
    attach_wildcard_manager_context(context)

    if context.api_config_service is None:
        context.api_config_service = create_api_config_service(context)
    context.generation_queue_manager = create_queue_manager(context)
    context.last_api_payloads = {}
    context.event_stream_runtime = None


def initialize_desktop_compatibility(context: Any) -> None:
    context.main_window = None
    context.middle_section_controller = None
    context.remote_bridge = None
    context.api_service = None
    context.temp_window_mode = False
    context.temp_window_character_tab = None
    context.session_p_eng_override = None
    context.scoped_wildcard = None


def initialize_runtime_state(context: Any) -> None:
    context.search_filter_state = context._load_search_filter_state()
    context.remote_active_ratings = set(context.search_filter_state.get("ratings") or DEFAULT_ACTIVE_RATINGS)
    context.search_query_ratings = set(context.search_filter_state.get("search_ratings") or DEFAULT_ACTIVE_RATINGS)
    context.active_tag_filter_ids = None
    context.pending_tag_filter = None
    context.depth_state = None
    context.wildcard_override = {}
    if os.environ.get("NAIA_HEADLESS_DISABLE_GENERATION_EXECUTION") == "1":
        context.headless_generation_execute_enabled = False
    context.prompt_squeeze_enabled = False
    context.pipeline_hooks = {}
    context.session_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    context.subscribers = context.event_bus.subscribers


def ensure_first_run_recommended_preset(context: Any) -> None:
    try:
        context._prompt_engineering_service().ensure_first_run_recommended_preset()
    except Exception as exc:
        print(f"Remote Web: first-run recommended preset skipped: {exc}", flush=True)


def attach_wildcard_manager_context(context: Any) -> None:
    manager = context.wildcard_manager
    if manager is None or getattr(manager, "_app_context_ref", None) is not None:
        return
    try:
        manager._app_context_ref = weakref.ref(context)
    except TypeError:
        pass


def create_api_config_service(context: Any) -> ApiConfigService:
    cloudflared_bin_dir = (
        context.runtime_paths.downloads_dir / "cloudflared"
        if context.runtime_paths is not None else None
    )
    cloudflared = CloudflaredService(
        port=context.remote_params.get("web_session_port", DEFAULT_WEB_SHELL_PORT),
        bin_dir=cloudflared_bin_dir,
    )
    cloudflared.set_status(
        active=context.cloudflared_active,
        url=context.cloudflared_tunnel_url,
        status_text=context.cloudflared_status_text,
    )
    timestamp_path = (
        context.runtime_paths.config_dir / "NAIA_api_timestamps.json"
        if context.runtime_paths is not None else None
    )
    return ApiConfigService(
        context.secure_token_manager,
        cloudflared=cloudflared,
        # 진입점(NAIA_web_headless)이 기록한 실제 바인드 호스트. 키가 없으면
        # 패키지/포터블 기본(0.0.0.0)으로 간주해 LAN 링크를 노출한다.
        bind_host=str(context.remote_params.get("web_session_bind_host") or "0.0.0.0"),
        **({"timestamp_path": timestamp_path} if timestamp_path is not None else {}),
    )
