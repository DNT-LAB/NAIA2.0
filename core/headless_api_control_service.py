"""Headless API setup and Cloudflared command wrappers."""

from __future__ import annotations

from typing import Any


class HeadlessApiControlService:
    def __init__(self, context: Any):
        self.context = context

    def setup_gate(self, client_host: str) -> tuple[bool, str]:
        return self.context.api_config_service.setup_gate(client_host)

    def cloudflared_gate(self, client_host: str) -> tuple[bool, str]:
        return self.context.api_config_service.cloudflared_gate(client_host)

    def verify_api(self, mode: str, value: str) -> dict[str, Any]:
        result = self.context.api_config_service.verify(mode, value)
        self.context.publish("api_status_changed", self.context.api_status_payload())
        return result

    def clear_api(self, mode: str) -> dict[str, Any]:
        result = self.context.api_config_service.clear(mode)
        self.context.publish("api_status_changed", self.context.api_status_payload())
        return result

    def probe_api(self) -> dict[str, bool | None]:
        return self.context.api_config_service.probe()

    def set_cloudflared_enabled(self, enabled: bool) -> dict[str, Any]:
        result = self.context.api_config_service.cloudflared.set_enabled(enabled)
        status = self.context.api_config_service.cloudflared.status()
        self.context.cloudflared_active = bool(status.get("active"))
        self.context.cloudflared_tunnel_url = str(status.get("url") or "")
        self.context.cloudflared_status_text = str(status.get("status_text") or "")
        self.context.publish("cloudflared_status_changed", status)
        return result

    def store_api_payload(self, payload: dict, mode: str) -> None:
        self.context.last_api_payloads[str(mode or "").upper()] = payload
