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


# 앞이 스킴 글자가 아닌 자리에서만 시작하고 스킴 길이를 묶는다 - 긴 영문 덩어리에서 시작점마다 다시 훑으면
# 길이의 제곱이 든다(Codex 재리뷰 11-06 NEW-2).
_URL_RE = re.compile(r"(?<![A-Za-z0-9+.-])[A-Za-z][A-Za-z0-9+.-]{0,31}://[^\s'\"<>]+")
_SECRET_PARAM_WORDS = frozenset({
    "token", "key", "apikey", "auth", "authorization", "secret", "pass", "passwd", "password", "pwd",
    "sig", "signature", "session", "sessionid", "sid", "cred", "credential", "credentials", "jwt", "bearer",
})
# 주소에서 모은 조각을 응답 전체에서 바꿀 때의 최소 길이 - `?x_key=1` 의 "1" 을 전역으로 바꾸면 IP · 호출 ID 가 깨진다
# (NEW-1). 주소 안의 자리는 길이와 상관없이 제자리에서 가린다.
_MIN_GLOBAL_SECRET = 6


def _secret_param(name):
    from urllib.parse import unquote_plus

    name = unquote_plus(name).lower()
    return (any(word in _SECRET_PARAM_WORDS for word in re.split(r"[^a-z0-9]+", name))
            or name.endswith(("token", "secret", "password", "apikey")))


def _mask_params(text):
    pieces = []
    for piece in text.split("&"):
        name, eq, value = piece.partition("=")
        pieces.append(f"{name}=[REDACTED]" if eq and value and _secret_param(name) else piece)
    return "&".join(pieces)


def _split_url(url):
    """(scheme://, userinfo or None, rest-of-authority, path, query or None, fragment or None) - raw, never decoded."""
    scheme, sep, rest = url.partition("://")
    authority = re.match(r"[^/?#]*", rest).group(0)
    tail = rest[len(authority):]
    userinfo, at, host = authority.rpartition("@")
    tail, hash_sep, fragment = tail.partition("#")
    path, q_sep, query = tail.partition("?")
    return (scheme + sep, userinfo if at else None, host, path,
            query if q_sep else None, fragment if hash_sep else None)


def _mask_url(url):
    prefix, userinfo, host, path, query, fragment = _split_url(url)
    out = prefix + ("[REDACTED]@" if userinfo is not None else "") + host + path
    if query is not None:
        out += "?" + _mask_params(query)
    if fragment is not None:
        out += "#" + (_mask_params(fragment) if "=" in fragment else fragment)
    return out


def url_credentials(text):
    """Credential parts of URLs inside a string (raw and decoded forms), for replacing echoes elsewhere.

    WebUI/ComfyUI addresses may carry `user:pass@` or `?token=` (Codex review 2026-11-06 H1). The
    verifiers echo the address in their error text, so these parts are secrets, the host is not.
    Short parts are left out: the URL itself is masked in place by `mask_url_credentials`.
    """
    from urllib.parse import unquote, unquote_plus

    text = str(text or "")
    if "://" not in text:
        return []
    found = []
    for match in _URL_RE.finditer(text):
        _, userinfo, _, _, query, fragment = _split_url(match.group(0))
        raw = []
        if userinfo:
            raw.append(userinfo)
            raw.append(userinfo.partition(":")[2])
        for params in (query, fragment):
            for piece in (params or "").split("&"):
                name, eq, value = piece.partition("=")
                if eq and value and _secret_param(name):
                    raw.append(value)
        for value in raw:
            found.extend(form for form in {value, unquote(value), unquote_plus(value)}
                         if len(form) >= _MIN_GLOBAL_SECRET)
    return found


def mask_url_credentials(text):
    """Mask URL userinfo and sensitive query/fragment values in place (raw text, encoded or not)."""
    if "://" not in text:
        return text
    return _URL_RE.sub(lambda match: _mask_url(match.group(0)), text)


def sanitize(value, secrets=()):
    if isinstance(value, dict):
        # 상관 ID 는 프로토콜 필드다 - 비밀값 치환이 건드리면 짝을 못 찾는다(NEW-1).
        return {key: item if key == CALL_ID_KEY else "[REDACTED]" if sensitive_key(key) else sanitize(item, secrets)
                for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [sanitize(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in sorted((s for s in secrets if isinstance(s, str) and len(s) >= 4), key=len, reverse=True):
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
