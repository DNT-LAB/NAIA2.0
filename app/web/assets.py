"""Resolve the supported Remote Web source directory.

``app/web/remote`` is the source-owned path. Older checkouts or explicit local
overrides may still provide the previous web files under ``ui/remote_web``.
This resolver keeps that fallback explicit without treating the old path as an
active source owner.
"""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path


REMOTE_WEB_DIR_ENV = "NAIA_REMOTE_WEB_DIR"
REQUIRED_REMOTE_WEB_FILES = ("index.html", "style.css", "app.js")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalize_path(value: str | Path, *, base: Path) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(str(value))))
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def remote_web_dir_is_complete(path: str | Path) -> bool:
    root = Path(path)
    return all((root / filename).is_file() for filename in REQUIRED_REMOTE_WEB_FILES)


def resolve_remote_web_dir(
    project_root: str | Path | None = None,
    *,
    explicit_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    root = _normalize_path(project_root or _project_root(), base=_project_root())
    environ = env if env is not None else os.environ

    configured = explicit_dir or environ.get(REMOTE_WEB_DIR_ENV)
    if configured:
        return _normalize_path(configured, base=root)

    app_web_dir = root / "app" / "web" / "remote"
    legacy_web_dir = root / "ui" / "remote_web"
    for candidate in (app_web_dir, legacy_web_dir):
        if remote_web_dir_is_complete(candidate):
            return candidate.resolve()
    return app_web_dir.resolve()
