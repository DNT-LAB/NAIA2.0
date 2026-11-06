"""Correlated agent replies on the existing WebSocket scheduling/dispatch path."""
from __future__ import annotations

import json
import re

PROTOCOL_VERSION = 1
CALL_ID_KEY = "_agent_call_id"
ACK_TYPE = "agent_dispatch_complete"


def clean_call_id(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value) else ""


def sensitive_key(key):
    key = str(key).lower().replace("-", "_")
    return (key in {"credential", "password", "authorization", "proxy_authorization", "api_key", "secret", "_key", "token"}
            or key.endswith(("_token", "_password", "_secret", "_api_key")))


_URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"<>]+")
_URL_SECRET_PARAM = re.compile(r"token|key|auth|secret|pass|sig|session|cred|api", re.I)


def url_credentials(text):
    """Credential parts of URLs inside a string: userinfo and sensitive-looking query values.

    WebUI/ComfyUI addresses may carry `user:pass@` or `?token=` (Codex review 2026-11-06 H1). The
    verifiers echo the address in their error text, so these parts are secrets, the host is not.
    """
    from urllib.parse import parse_qsl, urlsplit

    found = []
    for match in _URL_RE.finditer(str(text or "")):
        try:
            parts = urlsplit(match.group(0))
        except ValueError:
            continue
        if "@" in parts.netloc:
            found.append(parts.netloc.rsplit("@", 1)[0])
        found.extend(value for key, value in parse_qsl(parts.query, keep_blank_values=False)
                     if value and _URL_SECRET_PARAM.search(key))
    return found


def mask_url_credentials(text):
    """Replace URL userinfo and sensitive query values in a string with [REDACTED]."""
    for secret in sorted(set(url_credentials(text)), key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return text


def sanitize(value, secrets=()):
    if isinstance(value, dict):
        return {key: "[REDACTED]" if sensitive_key(key) else sanitize(item, secrets)
                for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [sanitize(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in sorted((s for s in secrets if isinstance(s, str) and s), key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
        value = mask_url_credentials(value)
    return value


def secret_values(value):
    values = []
    if isinstance(value, dict):
        selector = str(value.get("key") or "") + " " + str(value.get("type") or "")
        if (isinstance(value.get("value"), str) and value["value"]
                and re.search(r"token|credential|password|auth|verify_api|api_verify", selector, re.I)):
            values.append(value["value"])
        for key, item in value.items():
            if sensitive_key(key) and isinstance(item, str) and item:
                values.append(item)
            else:
                values.extend(secret_values(item))
    elif isinstance(value, str):
        # 입력한 주소의 userinfo · 인증 쿼리 값 - 서버가 주소 모양을 바꿔 되돌려 줘도 조각으로 가린다.
        values.extend(url_credentials(value))
    elif isinstance(value, list):
        for item in value:
            values.extend(secret_values(item))
    return values


class AgentReplySocket:
    """Wrap directed replies only; shared broadcasts are never mislabeled.

    The underlying real socket remains in the broadcast client set. Background
    operations holding this wrapper keep their call ID, while the shared generation
    runner continues using its own request IDs and ordinary result events.
    """
    def __init__(self, socket, call_id, context, command):
        self.socket = socket
        self.call_id = call_id
        self.secrets = secret_values(command)
        manager = getattr(context, "secure_token_manager", None)
        if manager is not None:
            for key in ("nai_token", "webui_url", "comfyui_url"):
                try:
                    value = manager.get_token(key)
                    if value:
                        self.secrets.append(value)
                except Exception:
                    pass

    def __getattr__(self, key):
        return getattr(self.socket, key)

    async def send_json(self, payload):
        if isinstance(payload, dict):
            payload = {**sanitize(payload, self.secrets), CALL_ID_KEY: self.call_id}
        await self.socket.send_text(json.dumps(payload, ensure_ascii=False))

    async def send_text(self, text):
        try:
            payload = json.loads(text)
        except (ValueError, TypeError):
            payload = {"type": "agent_text", "text": str(text)}
        await self.send_json(payload)

    async def acknowledge(self, *, error=None):
        await self.send_json({"type": ACK_TYPE, "protocol_version": PROTOCOL_VERSION,
                              "dispatch_complete": True, "operation_complete": False,
                              "error": str(error) if error is not None else None})
