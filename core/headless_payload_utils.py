"""Shared payload helpers for headless Remote Web services."""

from __future__ import annotations

import ipaddress
from typing import Any


def coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def module_state_payload(module_id: str, state: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "type": "module_state",
        "module_id": module_id,
        "available": True,
        "headless": True,
        **state,
    }
    payload["state"] = dict(state)
    return payload


def toast(message: str, *, level: str = "info") -> dict[str, Any]:
    return {
        "type": "toast",
        "level": level,
        "message": str(message or ""),
        "headless": True,
    }


def index_from_key(key: str, prefix: str) -> int | None:
    try:
        return int(str(key)[len(prefix):])
    except (TypeError, ValueError):
        return None


def is_loopback_host(host: str) -> bool:
    clean_host = str(host or "").strip()
    if clean_host in {"127.0.0.1", "::1", "localhost"}:
        return True
    try:
        return ipaddress.ip_address(clean_host).is_loopback
    except Exception:
        return False
