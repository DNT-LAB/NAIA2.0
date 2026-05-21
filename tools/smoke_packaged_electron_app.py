"""Smoke-test a packaged NAIA Electron app folder."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path
import sys
from typing import Any

try:
    from tools.release_manifest_audit import audit_payload
    from tools.smoke_staged_backend import smoke_staged_backend
except ModuleNotFoundError:  # pragma: no cover - used when executed as a script.
    from release_manifest_audit import audit_payload
    from smoke_staged_backend import smoke_staged_backend


def _is_user_data_empty(path: Path) -> bool:
    return path.is_dir() and not any(path.iterdir())


def _electron_app_payload_exists(resources_root: Path) -> bool:
    return (
        (resources_root / "app.asar").is_file()
        or (resources_root / "app" / "main" / "main.cjs").is_file()
    )


def smoke_packaged_electron_app(
    package_root: str | Path,
    *,
    exe_name: str = "NAIA.exe",
    require_bundled_python: bool = False,
    skip_backend_smoke: bool = False,
) -> dict[str, Any]:
    root = Path(package_root).resolve()
    resources = root / "resources"
    backend = resources / "naia-backend"
    user_data = root / "user-data"
    python_runtime = resources / "python"
    violations: list[dict[str, str]] = []

    if not root.is_dir():
        return {
            "ok": False,
            "package_root": str(root),
            "violations": [{"path": str(root), "reason": "package root is not a directory"}],
        }

    exe = root / exe_name
    if not exe.is_file():
        violations.append({"path": exe_name, "reason": "Electron executable is missing"})
    if not resources.is_dir():
        violations.append({"path": "resources", "reason": "Electron resources directory is missing"})
    elif not _electron_app_payload_exists(resources):
        violations.append({"path": "resources", "reason": "Electron app payload app.asar or resources/app/main/main.cjs is missing"})
    if not backend.is_dir():
        violations.append({"path": "resources/naia-backend", "reason": "packaged backend resource directory is missing"})
    if not _is_user_data_empty(user_data):
        violations.append({"path": "user-data", "reason": "portable user-data folder must exist and be empty in a fresh package"})

    bundled_python = (
        (python_runtime / "python.exe").is_file()
        or (python_runtime / "bin" / "python").is_file()
    )
    if require_bundled_python and not bundled_python:
        violations.append({"path": "resources/python", "reason": "bundled Python runtime is required but missing"})

    audit = audit_payload(root)
    for violation in audit.get("violations", []):
        violations.append({
            "path": str(violation.get("path", "")),
            "reason": f"release manifest audit: {violation.get('reason', '')}",
        })

    backend_smoke: dict[str, Any] | None = None
    if not violations and not skip_backend_smoke:
        backend_smoke = smoke_staged_backend(backend, user_data_root=user_data)
        if not backend_smoke.get("ok"):
            violations.append({"path": "resources/naia-backend", "reason": "packaged backend smoke failed"})

    return {
        "ok": not violations,
        "package_root": str(root),
        "exe": str(exe),
        "resources": str(resources),
        "backend_root": str(backend),
        "user_data_root": str(user_data),
        "bundled_python": bundled_python,
        "backend_smoke": backend_smoke,
        "violations": violations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test a packaged NAIA Electron app folder.")
    parser.add_argument("package_root", help="Packaged Electron app folder, e.g. app/electron/dist/win-unpacked.")
    parser.add_argument("--exe-name", default="NAIA.exe", help="Expected Electron executable name.")
    parser.add_argument("--require-bundled-python", action="store_true", help="Fail when resources/python is missing.")
    parser.add_argument("--skip-backend-smoke", action="store_true", help="Only check packaged folder structure.")
    args = parser.parse_args(argv)

    log_buffer = io.StringIO()
    with contextlib.redirect_stdout(log_buffer):
        payload = smoke_packaged_electron_app(
            args.package_root,
            exe_name=args.exe_name,
            require_bundled_python=args.require_bundled_python,
            skip_backend_smoke=args.skip_backend_smoke,
        )
    captured_logs = log_buffer.getvalue()
    if captured_logs:
        sys.stderr.write(captured_logs.encode("ascii", "replace").decode("ascii"))
        if not captured_logs.endswith("\n"):
            sys.stderr.write("\n")
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
