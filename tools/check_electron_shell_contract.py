"""Validate the Electron shell contract for the headless NAIA app."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any


DEFAULT_CONTRACT = Path("release_assets/manifests/electron_shell_contract.json")
DEFAULT_ELECTRON_ROOT = Path("app/electron")
DEFAULT_WEB_ROOT = Path("app/web/remote")


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _max_number_after_key(source: str, key: str) -> int | None:
    matches = re.findall(rf"\b{re.escape(key)}\s*:\s*(\d+)", source)
    if not matches:
        return None
    return max(int(value) for value in matches)


def check_electron_shell_contract(
    contract_path: str | Path = DEFAULT_CONTRACT,
    *,
    electron_root: str | Path = DEFAULT_ELECTRON_ROOT,
    web_root: str | Path = DEFAULT_WEB_ROOT,
) -> dict[str, Any]:
    contract_file = Path(contract_path)
    electron_dir = Path(electron_root)
    web_dir = Path(web_root)
    contract = _read_json(contract_file)
    main_path = electron_dir / "main" / "main.cjs"
    preload_path = electron_dir / "preload" / "preload.cjs"
    package_path = electron_dir / "package.json"
    web_index_path = web_dir / "index.html"
    violations: list[dict[str, str]] = []

    for path in (main_path, preload_path, package_path, web_index_path):
        if not path.is_file():
            violations.append({"path": str(path), "reason": "required contract source is missing"})

    if violations:
        return {
            "ok": False,
            "contract": str(contract_file),
            "electron_root": str(electron_dir),
            "web_root": str(web_dir),
            "violations": violations,
        }

    main = _read_text(main_path)
    preload = _read_text(preload_path)
    package = _read_json(package_path)
    web_index = _read_text(web_index_path)
    primary = contract.get("primary_window", {})
    min_size = primary.get("minimum_size", {})
    maintenance_path = electron_dir / "renderer" / "maintenance.html"
    maintenance = _read_text(maintenance_path) if maintenance_path.is_file() else ""
    checks: dict[str, Any] = {
        "primary_window": {},
        "backend_lifecycle": {},
        "browser_fallback": {},
        "maintenance_logs": {},
    }

    if not maintenance_path.is_file():
        violations.append({"path": str(maintenance_path), "reason": "maintenance view is missing"})

    expected_query = str(primary.get("entry_url_query") or "")
    checks["primary_window"]["entry_url_query"] = bool(expected_query and expected_query in main)
    if expected_query and not checks["primary_window"]["entry_url_query"]:
        violations.append({"path": str(main_path), "reason": f"missing entry URL query: {expected_query}"})

    min_width = int(min_size.get("width") or 0)
    min_height = int(min_size.get("height") or 0)
    actual_min_width = _max_number_after_key(main, "minWidth")
    actual_min_height = _max_number_after_key(main, "minHeight")
    checks["primary_window"]["minimum_size"] = (
        actual_min_width is not None
        and actual_min_height is not None
        and actual_min_width >= min_width
        and actual_min_height >= min_height
    )
    if actual_min_width is None or actual_min_width < min_width:
        violations.append({"path": str(main_path), "reason": "main window minWidth does not satisfy contract"})
    if actual_min_height is None or actual_min_height < min_height:
        violations.append({"path": str(main_path), "reason": "main window minHeight does not satisfy contract"})

    checks["primary_window"]["context_isolation"] = (
        primary.get("context_isolation") is not True or "contextIsolation: true" in main
    )
    checks["primary_window"]["node_integration"] = (
        primary.get("node_integration") is not False or "nodeIntegration: false" in main
    )
    if not checks["primary_window"]["context_isolation"]:
        violations.append({"path": str(main_path), "reason": "contextIsolation must be enabled"})
    if not checks["primary_window"]["node_integration"]:
        violations.append({"path": str(main_path), "reason": "nodeIntegration must be disabled"})

    required_main_terms = {
        "websocket": ["loadURL", "ENTRY_QUERY", "remoteEntryUrl"],
        "local_storage": ["session.defaultSession", "user-data"],
        "downloads": ["will-download", "ensureRuntimeSubfolder(\"downloads\")", "item.setSavePath"],
        "popups": ["setWindowOpenHandler", "openInternalPopup", "parent: mainWindow"],
        "browser_fallback": ["openBrowserFallbackUrl", "naia-open-browser:", "shell.openExternal"],
        "backend_lifecycle": ["spawn(", "stopBackend", "restart-backend"],
        "runtime_data": ["NAIA_USER_DATA_DIR", "runtimeDataRoot()", "portableUserDataRoot"],
        "portable_user_data": ["path.dirname(app.getPath(\"exe\"))", "fs.existsSync(packagedUserData)"],
        "cdp_smoke": ["NAIA_ELECTRON_REMOTE_DEBUGGING_PORT", "app.commandLine.appendSwitch", "remote-debugging-port"],
        "maintenance_logs": [
            "LOG_LIMIT",
            "backendLogs",
            "appendBackendLog",
            "logs: backendLogs.slice",
            "loadMaintenance(\"error\"",
            "ipcMain.handle(\"naia:open-logs\"",
            "openRuntimeSubfolder(\"logs\")",
        ],
    }
    for feature, terms in required_main_terms.items():
        checks.setdefault(feature, {})
        checks[feature]["main_terms"] = all(term in main for term in terms)
        for term in terms:
            if term not in main:
                violations.append({"path": str(main_path), "reason": f"{feature} contract term missing: {term}"})

    required_preload_terms = ["naiaShell", "restartBackend", "openBrowser", "openDataFolder", "openLogs"]
    checks["maintenance_logs"]["preload_open_logs"] = all(term in preload for term in ("naiaShell", "openLogs"))
    for term in required_preload_terms:
        if term not in preload:
            violations.append({"path": str(preload_path), "reason": f"preload shell API missing: {term}"})

    checks["browser_fallback"]["web_scheme"] = "naia-open-browser://open" in web_index
    checks["browser_fallback"]["http_https_only"] = (
        "parsed.protocol !== \"naia-open-browser:\"" in main
        and "isHttpLikeUrl(target)" in main
    )
    checks["browser_fallback"]["manual_open_browser_api"] = (
        "ipcMain.handle(\"naia:open-browser\"" in main
        and "openBrowser" in preload
    )
    if not checks["browser_fallback"]["web_scheme"]:
        violations.append({"path": str(web_index_path), "reason": "Remote Web browser fallback scheme is missing"})

    required_maintenance_controls = list((contract.get("maintenance_view") or {}).get("required_controls") or [])
    checks["maintenance_logs"]["required_controls"] = all(control in maintenance for control in required_maintenance_controls)
    for control in required_maintenance_controls:
        if control not in maintenance:
            violations.append({"path": str(maintenance_path), "reason": f"maintenance control missing: {control}"})
    maintenance_log_terms = [
        "id=\"logs\"",
        "state.logs",
        "window.naiaShell.getState",
        "window.naiaShell.openLogs()",
        "window.naiaShell.onStateChanged",
    ]
    checks["maintenance_logs"]["view_renders_shell_logs"] = all(term in maintenance for term in maintenance_log_terms)
    for term in maintenance_log_terms:
        if term not in maintenance:
            violations.append({"path": str(maintenance_path), "reason": f"maintenance log term missing: {term}"})
    checks["maintenance_logs"]["logs_accessible"] = all(
        bool(checks["maintenance_logs"].get(key))
        for key in ("main_terms", "preload_open_logs", "required_controls", "view_renders_shell_logs")
    )
    checks["browser_fallback"]["fallback_only"] = all(
        bool(checks["browser_fallback"].get(key))
        for key in ("main_terms", "web_scheme", "http_https_only", "manual_open_browser_api")
    )
    checks["backend_lifecycle"]["owned_by_shell"] = bool(checks["backend_lifecycle"].get("main_terms"))

    if package.get("main") != "main/main.cjs":
        violations.append({"path": str(package_path), "reason": "Electron package main entry is not main/main.cjs"})
    if "electron" not in package.get("devDependencies", {}):
        violations.append({"path": str(package_path), "reason": "Electron dependency is not pinned"})
    if "electron-builder" not in package.get("devDependencies", {}):
        violations.append({"path": str(package_path), "reason": "electron-builder dependency is not pinned"})

    return {
        "ok": not violations,
        "contract": str(contract_file),
        "electron_root": str(electron_dir),
        "web_root": str(web_dir),
        "checks": checks,
        "violations": violations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the NAIA Electron shell contract.")
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT), help="Electron shell contract manifest.")
    parser.add_argument("--electron-root", default=str(DEFAULT_ELECTRON_ROOT), help="Electron shell root.")
    parser.add_argument("--web-root", default=str(DEFAULT_WEB_ROOT), help="Remote Web root.")
    args = parser.parse_args(argv)

    payload = check_electron_shell_contract(
        args.contract,
        electron_root=args.electron_root,
        web_root=args.web_root,
    )
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
