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

from core.api_config_service import ApiConfigService, CloudflaredService


SUPPORTED_API_MODES = ("NAI", "WEBUI", "COMFYUI")
REMOTE_OPTION_DEFAULTS = {
    "prompt_fixed": False,
    "auto_generate": False,
    "wildcard_standalone": False,
    "auto_save": False,
}


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

    def __post_init__(self) -> None:
        if self.token_manager is None:
            self.token_manager = self._default_token_manager()
        self.secure_token_manager = self.token_manager
        self.repo_root = Path(self.repo_root) if self.repo_root is not None else Path(__file__).resolve().parent.parent
        self.main_window = None
        self.middle_section_controller = None
        self.remote_bridge = None
        self.remote_active_ratings = None
        self.pipeline_hooks: dict[str, dict[str, list[tuple[int, Any]]]] = {}
        self.session_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.subscribers = self.event_bus.subscribers
        if self.api_config_service is None:
            cloudflared = CloudflaredService(port=self.remote_params.get("web_session_port", 7243))
            cloudflared.set_status(
                active=self.cloudflared_active,
                url=self.cloudflared_tunnel_url,
                status_text=self.cloudflared_status_text,
            )
            self.api_config_service = ApiConfigService(self.secure_token_manager, cloudflared=cloudflared)
        self.generation_queue_manager = self._create_queue_manager()

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
        self.publish("remote_options_changed", self.get_options())

    def get_options(self) -> dict[str, bool]:
        options = dict(REMOTE_OPTION_DEFAULTS)
        options.update({key: bool(value) for key, value in self.remote_options.items() if key in options})
        return options

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
