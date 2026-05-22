"""Run the Remote Web smoke contract against a staged backend resource root."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sys
from typing import Any

from fastapi.testclient import TestClient

try:
    from tools.smoke_staged_backend import BlockDesktopImports, _infer_user_data_root
except ModuleNotFoundError:  # pragma: no cover - used when executed as a script.
    from smoke_staged_backend import BlockDesktopImports, _infer_user_data_root


DEFAULT_CONTRACT = Path("release_assets/manifests/remote_web_smoke_contract.json")


def load_contract(path: str | Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _prepare_environment(backend_root: Path, user_data_root: Path) -> None:
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(backend_root))
    sys.meta_path.insert(0, BlockDesktopImports())
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["NAIA_RESOURCE_ROOT"] = str(backend_root)
    os.environ["NAIA_REMOTE_WEB_DIR"] = str(backend_root / "app" / "web" / "remote")
    os.environ["NAIA_USER_DATA_DIR"] = str(user_data_root)
    os.environ["NAIA_HEADLESS_OPEN_BROWSER"] = "0"
    os.chdir(backend_root)


def _make_test_client(backend_root: Path, user_data_root: Path) -> TestClient:
    _prepare_environment(backend_root, user_data_root)

    from core.web_session_app import create_headless_app
    from core.web_session_context import InMemoryTokenManager, WebSessionContext

    context = WebSessionContext(repo_root=backend_root, token_manager=InMemoryTokenManager())
    context.headless_generation_execute_enabled = False
    app = create_headless_app(context)
    return TestClient(app)


def _run_http_check(client: TestClient, check: dict[str, Any]) -> dict[str, Any]:
    method = str(check.get("method", "GET")).upper()
    path = str(check.get("path") or "/")
    expected = [int(status) for status in check.get("expected_status", [200])]
    payload = check.get("json")

    try:
        response = client.request(method, path, json=payload)
        status = response.status_code
        ok = status in expected
        json_error = ""
        observed_json = None
        if ok and ("expected_json_subset" in check or "expected_json_keys" in check):
            try:
                observed_json = response.json()
            except Exception as exc:
                ok = False
                json_error = f"response was not JSON: {exc}"
            if ok and "expected_json_subset" in check:
                ok, json_error = _json_contains(observed_json, check.get("expected_json_subset"))
            if ok and "expected_json_keys" in check:
                keys = check.get("expected_json_keys") or []
                missing = [
                    str(key)
                    for key in keys
                    if not isinstance(observed_json, dict) or key not in observed_json
                ]
                if missing:
                    ok = False
                    json_error = f"missing JSON keys: {', '.join(missing)}"
        result = {
            "feature": check.get("feature", path),
            "method": method,
            "path": path,
            "expected_status": expected,
            "status": status,
            "ok": ok,
        }
        if json_error:
            result["error"] = json_error
        return result
    except Exception as exc:
        return {
            "feature": check.get("feature", path),
            "method": method,
            "path": path,
            "expected_status": expected,
            "status": None,
            "ok": False,
            "error": str(exc),
        }


def _json_contains(actual: Any, expected: Any, path: str = "$") -> tuple[bool, str]:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False, f"{path} is not an object"
        for key, expected_value in expected.items():
            if key not in actual:
                return False, f"{path}.{key} missing"
            ok, error = _json_contains(actual.get(key), expected_value, f"{path}.{key}")
            if not ok:
                return ok, error
        return True, ""
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False, f"{path} is not an array"
        if len(actual) < len(expected):
            return False, f"{path} has fewer items than expected"
        for index, expected_value in enumerate(expected):
            ok, error = _json_contains(actual[index], expected_value, f"{path}[{index}]")
            if not ok:
                return ok, error
        return True, ""
    if actual != expected:
        return False, f"{path} expected {expected!r}, got {actual!r}"
    return True, ""


def _run_websocket_check(client: TestClient, check: dict[str, Any]) -> dict[str, Any]:
    path = str(check.get("path") or "/ws")
    expected = list(check.get("expected_initial_types") or [])
    try:
        with client.websocket_connect(path) as ws:
            messages = [ws.receive_json() for _ in expected]
            sync_message = check.get("sync_message")
            sync_payload = None
            if sync_message is not None:
                ws.send_text(str(sync_message))
                sync_payload = ws.receive_json()
        observed = [message.get("type") for message in messages]
        expected_sync_type = check.get("expected_sync_type")
        sync_ok = expected_sync_type is None or (isinstance(sync_payload, dict) and sync_payload.get("type") == expected_sync_type)
        return {
            "feature": check.get("feature", path),
            "path": path,
            "expected_initial_types": expected,
            "observed_initial_types": observed,
            "sync_type": sync_payload.get("type") if isinstance(sync_payload, dict) else None,
            "ok": observed == expected and sync_ok,
        }
    except Exception as exc:
        return {
            "feature": check.get("feature", path),
            "path": path,
            "expected_initial_types": expected,
            "observed_initial_types": [],
            "ok": False,
            "error": str(exc),
        }


def smoke_remote_web_contract(
    backend_root: str | Path,
    *,
    user_data_root: str | Path | None = None,
    contract_path: str | Path = DEFAULT_CONTRACT,
) -> dict[str, Any]:
    backend = Path(backend_root).resolve()
    user_data = Path(user_data_root).resolve() if user_data_root is not None else _infer_user_data_root(backend).resolve()
    if not backend.is_dir():
        return {"ok": False, "error": f"backend root is not a directory: {backend}"}
    if not (backend / "NAIA_web_headless.py").is_file():
        return {"ok": False, "error": f"NAIA_web_headless.py not found under: {backend}"}

    contract = load_contract(contract_path)
    client = _make_test_client(backend, user_data)
    http_results = [_run_http_check(client, check) for check in contract.get("http_checks", [])]
    websocket_results = [_run_websocket_check(client, check) for check in contract.get("websocket_checks", [])]
    failures = [
        result for result in [*http_results, *websocket_results]
        if not result.get("ok")
    ]
    return {
        "ok": not failures,
        "backend_root": str(backend),
        "user_data_root": str(user_data),
        "contract": str(Path(contract_path)),
        "http_checks": http_results,
        "websocket_checks": websocket_results,
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Remote Web smoke contract against staged backend resources.")
    parser.add_argument("backend_root", help="Path to resources/naia-backend or an equivalent backend root.")
    parser.add_argument("--user-data", default=None, help="Writable user-data root to inject through NAIA_USER_DATA_DIR.")
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT), help="Smoke contract JSON path.")
    args = parser.parse_args(argv)

    log_buffer = io.StringIO()
    with contextlib.redirect_stdout(log_buffer):
        payload = smoke_remote_web_contract(
            args.backend_root,
            user_data_root=args.user_data,
            contract_path=args.contract,
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
