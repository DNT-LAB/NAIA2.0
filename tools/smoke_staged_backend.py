"""Smoke-test a staged NAIA headless backend resource directory."""

from __future__ import annotations

import argparse
import contextlib
import importlib.abc
import io
import json
import os
from pathlib import Path
import sys
from typing import Any

from fastapi.testclient import TestClient


BLOCKED_IMPORT_ROOTS = {
    "PyQt6",
    "legacy_desktop",
    "NAIA_cold_v4",
}


class BlockDesktopImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path=None, target=None):  # noqa: D401
        root = fullname.split(".", 1)[0]
        if root in BLOCKED_IMPORT_ROOTS or fullname in BLOCKED_IMPORT_ROOTS:
            raise ImportError(f"blocked desktop import: {fullname}")
        return None


def _infer_user_data_root(backend_root: Path) -> Path:
    if backend_root.name == "naia-backend" and backend_root.parent.name == "resources":
        return backend_root.parent.parent / "user-data"
    return backend_root / "user-data"


def _prepare_import_environment(backend_root: Path, user_data_root: Path) -> None:
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(backend_root))
    sys.meta_path.insert(0, BlockDesktopImports())
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["NAIA_RESOURCE_ROOT"] = str(backend_root)
    os.environ["NAIA_REMOTE_WEB_DIR"] = str(backend_root / "app" / "web" / "remote")
    os.environ["NAIA_USER_DATA_DIR"] = str(user_data_root)
    os.environ["NAIA_HEADLESS_OPEN_BROWSER"] = "0"
    os.chdir(backend_root)


def smoke_staged_backend(
    backend_root: str | Path,
    *,
    user_data_root: str | Path | None = None,
) -> dict[str, Any]:
    backend = Path(backend_root).resolve()
    user_data = Path(user_data_root).resolve() if user_data_root is not None else _infer_user_data_root(backend).resolve()
    if not backend.is_dir():
        return {"ok": False, "error": f"backend root is not a directory: {backend}"}
    if not (backend / "NAIA_web_headless.py").is_file():
        return {"ok": False, "error": f"NAIA_web_headless.py not found under: {backend}"}

    _prepare_import_environment(backend, user_data)

    from app.web import resolve_remote_web_dir
    from core.web_session_app import create_headless_app
    from core.web_session_context import InMemoryTokenManager, WebSessionContext

    context = WebSessionContext(repo_root=backend, token_manager=InMemoryTokenManager())
    app = create_headless_app(context)
    client = TestClient(app)

    root_response = client.get("/")
    app_js_response = client.get("/app.js")
    status_response = client.get("/api/status")
    capabilities_response = client.get("/api/headless/capabilities")
    web_dir = resolve_remote_web_dir(backend)
    save_dir = context.runtime_paths.save_dir if context.runtime_paths is not None else backend / "save"
    output_dir = context.runtime_paths.output_dir if context.runtime_paths is not None else backend / "output"

    checks = {
        "root_status": root_response.status_code,
        "app_js_status": app_js_response.status_code,
        "status_status": status_response.status_code,
        "capabilities_status": capabilities_response.status_code,
        "web_dir": str(web_dir),
        "web_dir_is_app_path": web_dir == (backend / "app" / "web" / "remote").resolve(),
        "user_data_root": str(user_data),
        "save_dir": str(save_dir),
        "output_dir": str(output_dir),
        "save_outside_backend": not context.runtime_paths.is_source_tree_write(save_dir) if context.runtime_paths else False,
        "output_outside_backend": not context.runtime_paths.is_source_tree_write(output_dir) if context.runtime_paths else False,
        "pyqt_imported": "PyQt6" in sys.modules,
        "legacy_imported": any(name == "legacy_desktop" or name.startswith("legacy_desktop.") for name in sys.modules),
    }
    ok = (
        checks["root_status"] == 200
        and checks["app_js_status"] == 200
        and checks["status_status"] == 200
        and checks["capabilities_status"] == 200
        and checks["web_dir_is_app_path"]
        and checks["save_outside_backend"]
        and checks["output_outside_backend"]
        and not checks["pyqt_imported"]
        and not checks["legacy_imported"]
    )
    return {
        "ok": ok,
        "backend_root": str(backend),
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test a staged NAIA backend resource directory.")
    parser.add_argument("backend_root", help="Path to resources/naia-backend or an equivalent backend root.")
    parser.add_argument("--user-data", default=None, help="Writable user-data root to inject through NAIA_USER_DATA_DIR.")
    args = parser.parse_args(argv)

    log_buffer = io.StringIO()
    with contextlib.redirect_stdout(log_buffer):
        payload = smoke_staged_backend(args.backend_root, user_data_root=args.user_data)
    captured_logs = log_buffer.getvalue()
    if captured_logs:
        sys.stderr.write(captured_logs.encode("ascii", "replace").decode("ascii"))
        if not captured_logs.endswith("\n"):
            sys.stderr.write("\n")
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
