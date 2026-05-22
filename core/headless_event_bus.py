"""Minimal AppContext-compatible event bus for headless services."""

from __future__ import annotations

from collections import defaultdict
from threading import RLock
from typing import Any, Callable


class WebSessionEventBus:
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
