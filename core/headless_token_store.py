"""Token-store contracts and test double for headless Remote Web services."""

from __future__ import annotations

from typing import Protocol


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
