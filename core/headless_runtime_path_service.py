"""Runtime path helpers for the headless Remote Web context."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import os


class HeadlessRuntimePathService:
    def __init__(self, context: Any):
        self.context = context

    def save_root(self) -> Path:
        context = self.context
        return context.runtime_paths.save_dir if context.runtime_paths is not None else Path(context.repo_root) / "save"

    def output_root(self) -> Path:
        context = self.context
        return context.runtime_paths.output_dir if context.runtime_paths is not None else Path(context.repo_root) / "output"

    def legacy_save_root(self) -> Path:
        return Path(self.context.repo_root) / "save"

    @staticmethod
    def legacy_save_fallback_enabled() -> bool:
        if os.environ.get("NAIA_DISABLE_LEGACY_SAVE_FALLBACK") == "1":
            return False
        if os.environ.get("NAIA_ELECTRON") == "1":
            return False
        return True

    def save_path(self, *parts: str | Path) -> Path:
        path = self.save_root()
        for part in parts:
            path = path / part
        return path

    def legacy_save_path(self, *parts: str | Path) -> Path:
        path = self.legacy_save_root()
        for part in parts:
            path = path / part
        return path

    def existing_save_path(self, *parts: str | Path) -> Path:
        primary = self.save_path(*parts)
        if primary.exists():
            return primary
        if not self.legacy_save_fallback_enabled():
            return primary
        legacy = self.legacy_save_path(*parts)
        if legacy.exists():
            return legacy
        return primary

    def existing_save_dirs(self, *parts: str | Path) -> list[Path]:
        dirs: list[Path] = []
        seen: set[Path] = set()
        paths = [self.save_path(*parts)]
        if self.legacy_save_fallback_enabled():
            paths.append(self.legacy_save_path(*parts))
        for path in paths:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if path.exists() and path.is_dir():
                dirs.append(path)
        return dirs
