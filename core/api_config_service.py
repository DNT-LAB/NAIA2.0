"""PyQt-free API setup and Cloudflared services for Remote Web."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from core import api_verification
from core.web_shell_config import DEFAULT_WEB_SHELL_PORT


VERIFY_TIMESTAMP_FILE = Path("NAIA_api_timestamps.json")


@dataclass
class CloudflaredStatus:
    active: bool = False
    url: str = ""
    status_text: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "active": bool(self.active),
            "url": self.url or "",
            "status_text": self.url or self.status_text or "",
        }


class CloudflaredService:
    """PyQt-free Cloudflared quick-tunnel controller."""

    def __init__(
        self,
        *,
        port: int = DEFAULT_WEB_SHELL_PORT,
        bin_dir: Path | str | None = None,
        start_tunnel: Callable[..., Any] | None = None,
        stop_tunnel: Callable[[int], Any] | None = None,
    ):
        self.port = int(port or DEFAULT_WEB_SHELL_PORT)
        self.bin_dir = Path(bin_dir) if bin_dir is not None else None
        self._start_tunnel = start_tunnel
        self._stop_tunnel = stop_tunnel
        self._status = CloudflaredStatus()

    def status(self) -> dict[str, Any]:
        return self._status.to_payload()

    def set_status(self, *, active: bool, url: str = "", status_text: str = "") -> dict[str, Any]:
        self._status = CloudflaredStatus(
            active=bool(active),
            url=url or "",
            status_text=status_text or "",
        )
        return self.status()

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        if enabled:
            return self.start()
        return self.stop()

    def start(self) -> dict[str, Any]:
        if self._status.active and self._status.url:
            return {"success": True, **self.status()}

        self.set_status(active=True, status_text="Cloudflared 연결 중...")
        try:
            start_tunnel = self._start_tunnel
            if start_tunnel is None:
                from utils.cloudflared import start_tunnel as start_tunnel
                info = start_tunnel(self.port, on_progress=self._on_progress, bin_dir=self.bin_dir)
            else:
                info = start_tunnel(self.port, on_progress=self._on_progress)
            tunnel_url = str(getattr(info, "tunnel_url", "") or "")
            self.set_status(active=True, url=tunnel_url, status_text=tunnel_url)
            return {"success": True, **self.status()}
        except Exception as exc:
            message = f"Cloudflared 실패: {exc}"
            self.set_status(active=False, url="", status_text=message)
            return {"success": False, "error": str(exc), **self.status()}

    def stop(self) -> dict[str, Any]:
        try:
            stop_tunnel = self._stop_tunnel
            if stop_tunnel is None:
                from utils.cloudflared import stop_tunnel as stop_tunnel
            stop_tunnel(self.port)
        except Exception:
            pass
        self.set_status(active=False, url="", status_text="")
        return {"success": True, **self.status()}

    def _on_progress(self, message: str) -> None:
        self.set_status(active=True, url=self._status.url, status_text=str(message or ""))


class ApiConfigService:
    """Server-owned API setup state and commands without desktop widgets."""

    def __init__(
        self,
        token_manager,
        *,
        timestamp_path: Path | str = VERIFY_TIMESTAMP_FILE,
        cloudflared: CloudflaredService | None = None,
        verify_nai_token: Callable[[str], api_verification.VerifyResult] = api_verification.verify_nai_token,
        verify_webui_url: Callable[[str], api_verification.VerifyResult] = api_verification.verify_webui_url,
        verify_comfyui_url: Callable[[str], api_verification.VerifyResult] = api_verification.verify_comfyui_url,
    ):
        self.token_manager = token_manager
        self.timestamp_path = Path(timestamp_path)
        self.cloudflared = cloudflared or CloudflaredService()
        self._verify_nai_token = verify_nai_token
        self._verify_webui_url = verify_webui_url
        self._verify_comfyui_url = verify_comfyui_url

    def timestamps(self) -> dict[str, str]:
        try:
            if self.timestamp_path.exists():
                with self.timestamp_path.open("r", encoding="utf-8") as handle:
                    loaded = json.load(handle) or {}
                return loaded if isinstance(loaded, dict) else {}
        except Exception:
            pass
        return {}

    def save_timestamp(self, key: str) -> None:
        data = self.timestamps()
        data[f"{key}_last_verified"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.timestamp_path.parent.mkdir(parents=True, exist_ok=True)
            with self.timestamp_path.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def setup_required(self) -> bool:
        return not any((
            (self.token_manager.get_token("nai_token") or "").strip(),
            (self.token_manager.get_token("webui_url") or "").strip(),
            (self.token_manager.get_token("comfyui_url") or "").strip(),
        ))

    def status_payload(
        self,
        *,
        active_mode: str = "NAI",
        autocomplete: dict[str, Any] | None = None,
        client_host: str | None = None,
    ) -> dict[str, Any]:
        timestamps = self.timestamps()
        nai_token = (self.token_manager.get_token("nai_token") or "").strip()
        setup_required = self.setup_required()
        payload = {
            "type": "api_status",
            "nai_configured": bool(nai_token),
            "nai_token_preview": nai_token[:7] if len(nai_token) >= 7 else nai_token,
            "webui_url": self.token_manager.get_token("webui_url") or "",
            "comfyui_url": self.token_manager.get_token("comfyui_url") or "",
            "comfyui_default_model": self.token_manager.get_token("comfyui_default_model") or "",
            "comfyui_sampling_mode": self.token_manager.get_token("comfyui_sampling_mode") or "",
            "active_mode": active_mode or "",
            "setup_required": setup_required,
            "last_verified": {
                "nai": timestamps.get("nai_token_last_verified", ""),
                "webui": timestamps.get("webui_url_last_verified", ""),
                "comfyui": timestamps.get("comfyui_url_last_verified", ""),
            },
            "autocomplete": autocomplete or {},
        }
        cloudflared = self.cloudflared.status()
        payload["cloudflared_active"] = cloudflared["active"]
        payload["cloudflared_url"] = cloudflared["url"]
        payload["cloudflared_status_text"] = cloudflared["status_text"]
        if client_host is not None:
            allowed, reason = self.setup_gate(client_host)
            payload["setup_allowed"] = allowed
            payload["setup_block_reason"] = reason
            payload["setup_required"] = setup_required and allowed
            cf_allowed, cf_reason = self.cloudflared_gate(client_host)
            payload["cloudflared_control_allowed"] = cf_allowed
            payload["cloudflared_control_block_reason"] = cf_reason
        return payload

    def setup_gate(self, client_host: str) -> tuple[bool, str]:
        if not self._is_loopback_host(client_host):
            return False, "초기 설정은 로컬(127.0.0.1) 접속에서만 가능합니다."
        if self.cloudflared.status().get("active"):
            return False, "Cloudflared 터널 활성 중 — 초기 설정이 차단됩니다."
        return True, ""

    def cloudflared_gate(self, client_host: str) -> tuple[bool, str]:
        if not self._is_loopback_host(client_host):
            return False, "Cloudflared 제어는 로컬(127.0.0.1) 접속에서만 가능합니다."
        return True, ""

    def probe(self) -> dict[str, bool | None]:
        checks = (
            ("NAI", "nai_token", self._verify_nai_token),
            ("WEBUI", "webui_url", self._verify_webui_url),
            ("COMFYUI", "comfyui_url", self._verify_comfyui_url),
        )
        results: dict[str, bool | None] = {}
        for mode, token_key, verifier in checks:
            value = (self.token_manager.get_token(token_key) or "").strip()
            if not value:
                results[mode] = None
                continue
            try:
                results[mode] = bool(verifier(value).success)
            except Exception:
                results[mode] = False
        return results

    def verify(self, mode: str, value: str) -> dict[str, Any]:
        normalized_mode = str(mode or "").strip().upper()
        raw_value = str(value or "").strip()
        if normalized_mode == "NAI":
            result = self._verify_nai_token(raw_value)
            token_key = "nai_token"
            save_value = result.value or raw_value
        elif normalized_mode == "WEBUI":
            result = self._verify_webui_url(raw_value)
            token_key = "webui_url"
            protocol = (result.extra or {}).get("protocol", "http")
            save_value = f"{protocol}://{result.value}" if result.value else raw_value
        elif normalized_mode == "COMFYUI":
            result = self._verify_comfyui_url(raw_value)
            token_key = "comfyui_url"
            protocol = (result.extra or {}).get("protocol", "http")
            save_value = f"{protocol}://{result.value}" if result.value else raw_value
        else:
            return {
                "type": "verify_result",
                "mode": normalized_mode,
                "success": False,
                "message": "알 수 없는 API 모드입니다.",
                "message_type": "error",
                "extra": {},
            }

        if result.success:
            self.token_manager.save_token(token_key, save_value)
            self.save_timestamp(token_key)

        return {
            "type": "verify_result",
            "mode": normalized_mode,
            "success": bool(result.success),
            "message": result.message,
            "message_type": result.message_type,
            "extra": result.extra,
        }

    def clear(self, mode: str) -> dict[str, Any]:
        normalized_mode = str(mode or "").strip().upper()
        key_map = {
            "NAI": ("nai_token",),
            "WEBUI": ("webui_url",),
            "COMFYUI": ("comfyui_url", "comfyui_default_model", "comfyui_sampling_mode"),
        }
        keys = key_map.get(normalized_mode)
        if not keys:
            return {
                "type": "clear_api_result",
                "mode": normalized_mode,
                "success": False,
                "message": "알 수 없는 API 모드입니다.",
                "message_type": "error",
            }

        failed = [key for key in keys if not self.token_manager.delete_token(key)]
        if failed:
            return {
                "type": "clear_api_result",
                "mode": normalized_mode,
                "success": False,
                "message": "연결 해제 실패: 저장된 설정을 삭제하지 못했습니다 "
                f"({', '.join(failed)}).",
                "message_type": "error",
            }
        return {
            "type": "clear_api_result",
            "mode": normalized_mode,
            "success": True,
            "message": "연결 해제됨",
            "message_type": "info",
        }

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
    "ApiConfigService",
    "CloudflaredService",
    "CloudflaredStatus",
    "VERIFY_TIMESTAMP_FILE",
]
