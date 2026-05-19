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
import os
import re

from core import result_image_payload_service as result_images
from core.api_config_service import ApiConfigService, CloudflaredService
from core.headless_result_service import HeadlessResultStore
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
    "resolution_preset_enabled",
    "webui_hiresfix_assist_enabled",
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
    result_store: HeadlessResultStore = field(default_factory=HeadlessResultStore)
    headless_generation_execute_enabled: bool = True
    auto_save_state: dict[str, Any] = field(default_factory=dict)
    save_directory_state: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.token_manager is None:
            self.token_manager = self._default_token_manager()
        self.secure_token_manager = self.token_manager
        self.repo_root = Path(self.repo_root) if self.repo_root is not None else Path(__file__).resolve().parent.parent
        self.main_window = None
        self.middle_section_controller = None
        self.remote_bridge = None
        self.api_service = None
        self.temp_window_mode = False
        self.temp_window_character_tab = None
        self.session_p_eng_override = None
        self.scoped_wildcard = None
        self.remote_active_ratings = None
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
            cloudflared = CloudflaredService(port=self.remote_params.get("web_session_port", 7243))
            cloudflared.set_status(
                active=self.cloudflared_active,
                url=self.cloudflared_tunnel_url,
                status_text=self.cloudflared_status_text,
            )
            self.api_config_service = ApiConfigService(self.secure_token_manager, cloudflared=cloudflared)
        self.generation_queue_manager = self._create_queue_manager()
        self.last_api_payloads: dict[str, Any] = {}

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

    def search_state_payload(self) -> dict[str, Any]:
        active_ratings = self.get_active_ratings()
        rating_counts = self.search_results.get_count_by_rating()
        count = self.search_results.get_filtered_count(active_ratings) if active_ratings else self.search_results.get_count()
        return {
            "type": "search_state",
            "count": int(count or 0),
            "active_ratings": [rating for rating in SUPPORTED_RATINGS if rating in active_ratings],
            "rating_counts": rating_counts,
            "filter_preferences": {},
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
            allowed = self._is_loopback_host(client_host)
            payload["control_allowed"] = allowed
            payload["control_block_reason"] = "" if allowed else "Desktop control is local-only."
        return payload

    def queue_state_payload(self) -> dict[str, Any]:
        stats = self.generation_queue_manager.get_queue_stats()
        return {
            "type": "queue_state",
            "is_generating": bool(self.is_generating),
            "paused": bool(stats.get("is_paused", False)),
            "total": int(stats.get("total", 0) or 0),
            "has_urgent": bool(stats.get("has_urgent", False)),
            "priority_counts": stats.get("priority_counts", {}),
            "active": None,
            "items": [],
        }

    def generation_param_schema_payload(self) -> dict[str, Any]:
        payload = {
            "type": "params",
            "api_mode": self.get_api_mode(),
            "schema_only": False,
            "model": "NAID4.5F",
            "sampler": "k_euler_ancestral",
            "scheduler": "karras",
            "resolution": "832 x 1216",
            "steps": 28,
            "cfg_scale": 5.0,
            "cfg_rescale": 0.0,
            "seed": "",
            "seed_fixed": False,
            "random_resolution": False,
            "auto_fit_resolution": False,
            "options_model": ["NAID4.5F"],
            "options_sampler": ["k_euler_ancestral"],
            "options_scheduler": ["karras"],
            "options_resolution": ["832 x 1216", "1216 x 832", "1024 x 1024"],
            "steps_range": [1, 50],
            "nai_flags_enabled": {},
        }
        payload.update(self.remote_params)
        return payload

    @staticmethod
    def _coerce_remote_param(key: str, value: Any) -> Any:
        if key in REMOTE_BOOLEAN_PARAMS:
            return WebSessionContext._coerce_bool(value)
        return value

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
        base = Path(str(base_path or self.save_directory_state.get("base_path") or "output")).expanduser()
        if not base.is_absolute():
            base = Path(self.repo_root) / base
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
