"""Runtime path resolution for headless and packaged NAIA runs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import sys


APP_NAME = "NAIA"
RESOURCE_ROOT_ENV = "NAIA_RESOURCE_ROOT"
USER_DATA_DIR_ENV = "NAIA_USER_DATA_DIR"
PORTABLE_ENV = "NAIA_PORTABLE"

WRITABLE_DIR_NAMES = (
    "config",
    "data",
    "ui_assets",
    "save",
    "downloads",
    "bundles",
    "cache",
    "logs",
    "output",
    "wildcards",
    "extensions",
)

SOURCE_BOOTSTRAP_PATHS = (
    "data/source",
    "app_data_template",
    "release_assets/samples",
    "app/web/remote",
    "workflows",
    "data/clothes_list.txt",
    "data/color.txt",
    "data/characteristic_list.txt",
    "data/taglist",
)


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _coerce_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def _normalize_path(value: str | Path, *, base: Path | None = None) -> Path:
    expanded = Path(os.path.expandvars(os.path.expanduser(str(value))))
    if not expanded.is_absolute() and base is not None:
        expanded = base / expanded
    return expanded.resolve()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _resource_root(project_root: Path, env: Mapping[str, str]) -> Path:
    configured = env.get(RESOURCE_ROOT_ENV)
    if configured:
        return _normalize_path(configured, base=project_root)
    frozen_root = getattr(sys, "_MEIPASS", "")
    if getattr(sys, "frozen", False) and frozen_root:
        return _normalize_path(str(frozen_root), base=project_root)
    return project_root


def _installed_user_root(env: Mapping[str, str]) -> Path:
    appdata = env.get("APPDATA")
    if appdata:
        return _normalize_path(appdata) / APP_NAME
    xdg_data_home = env.get("XDG_DATA_HOME")
    if xdg_data_home:
        return _normalize_path(xdg_data_home) / APP_NAME
    return Path.home().joinpath(".local", "share", APP_NAME).resolve()


@dataclass(frozen=True)
class RuntimePaths:
    project_root: Path
    resource_root: Path
    user_root: Path
    portable: bool

    def source_path(self, relative: str | Path = ".") -> Path:
        return (self.project_root / relative).resolve()

    def resource_path(self, relative: str | Path = ".") -> Path:
        return (self.resource_root / relative).resolve()

    def writable_dir(self, name: str) -> Path:
        clean = str(name or "").strip()
        if clean not in WRITABLE_DIR_NAMES:
            allowed = ", ".join(WRITABLE_DIR_NAMES)
            raise KeyError(f"Unknown NAIA writable directory: {clean!r}. Allowed: {allowed}")
        return (self.user_root / clean).resolve()

    @property
    def config_dir(self) -> Path:
        return self.writable_dir("config")

    @property
    def data_dir(self) -> Path:
        return self.writable_dir("data")

    @property
    def ui_assets_dir(self) -> Path:
        return self.writable_dir("ui_assets")

    @property
    def save_dir(self) -> Path:
        return self.writable_dir("save")

    @property
    def downloads_dir(self) -> Path:
        return self.writable_dir("downloads")

    @property
    def bundles_dir(self) -> Path:
        return self.writable_dir("bundles")

    @property
    def cache_dir(self) -> Path:
        return self.writable_dir("cache")

    @property
    def logs_dir(self) -> Path:
        return self.writable_dir("logs")

    @property
    def output_dir(self) -> Path:
        return self.writable_dir("output")

    @property
    def wildcards_dir(self) -> Path:
        return self.writable_dir("wildcards")

    @property
    def extensions_dir(self) -> Path:
        return self.writable_dir("extensions")

    def ensure_writable_dirs(self, names: Iterable[str] | None = None) -> None:
        for name in names or WRITABLE_DIR_NAMES:
            self.writable_dir(name).mkdir(parents=True, exist_ok=True)

    def is_source_tree_write(self, path: str | Path) -> bool:
        resolved = _normalize_path(path, base=self.project_root)
        if _is_relative_to(resolved, self.user_root):
            return False
        return _is_relative_to(resolved, self.project_root)

    def manifest(self) -> dict[str, object]:
        return {
            "project_root": str(self.project_root),
            "resource_root": str(self.resource_root),
            "user_root": str(self.user_root),
            "portable": self.portable,
            "writable_dirs": {
                name: str(self.writable_dir(name)) for name in WRITABLE_DIR_NAMES
            },
            "source_bootstrap_paths": [
                str(self.source_path(path)) for path in SOURCE_BOOTSTRAP_PATHS
            ],
        }


def resolve_runtime_paths(
    project_root: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    portable: bool | None = None,
) -> RuntimePaths:
    environ = env if env is not None else os.environ
    root = _normalize_path(project_root or _default_project_root())
    resource_root = _resource_root(root, environ)
    explicit_user_root = environ.get(USER_DATA_DIR_ENV)
    if portable is None:
        portable = _coerce_bool(environ.get(PORTABLE_ENV), default=False)
    if explicit_user_root:
        user_root = _normalize_path(explicit_user_root, base=root)
    elif portable:
        user_root = root / "user-data"
    else:
        user_root = _installed_user_root(environ)
    return RuntimePaths(
        project_root=root,
        resource_root=resource_root,
        user_root=user_root.resolve(),
        portable=bool(portable),
    )


__all__ = [
    "APP_NAME",
    "PORTABLE_ENV",
    "RESOURCE_ROOT_ENV",
    "RuntimePaths",
    "SOURCE_BOOTSTRAP_PATHS",
    "USER_DATA_DIR_ENV",
    "WRITABLE_DIR_NAMES",
    "resolve_runtime_paths",
]
