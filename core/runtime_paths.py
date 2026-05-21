"""Compatibility import path for runtime filesystem resolution."""

from app.backend.runtime.paths import (
    APP_NAME,
    PORTABLE_ENV,
    RESOURCE_ROOT_ENV,
    RuntimePaths,
    SOURCE_BOOTSTRAP_PATHS,
    USER_DATA_DIR_ENV,
    WRITABLE_DIR_NAMES,
    resolve_runtime_paths,
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
