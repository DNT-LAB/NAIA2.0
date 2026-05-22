"""Run the Remote Web smoke contract against a staged backend resource root."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import time
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


def _make_test_client(backend_root: Path, user_data_root: Path, contract: dict[str, Any]) -> TestClient:
    _prepare_environment(backend_root, user_data_root)

    from core.web_session_app import create_headless_app
    from core.web_session_context import InMemoryTokenManager, WebSessionContext

    test_tokens = contract.get("test_tokens") if isinstance(contract.get("test_tokens"), dict) else {}
    context = WebSessionContext(repo_root=backend_root, token_manager=InMemoryTokenManager(test_tokens))
    context.headless_generation_execute_enabled = False
    _seed_test_context(context, contract.get("seed_context") if isinstance(contract.get("seed_context"), dict) else {})
    app = create_headless_app(context)
    return TestClient(app)


def _seed_test_context(context: Any, seed: dict[str, Any]) -> None:
    rows = seed.get("search_results")
    if isinstance(rows, list) and rows:
        import pandas as pd
        from core.search_result_model import SearchResultModel

        frame = pd.DataFrame([row for row in rows if isinstance(row, dict)])
        if not frame.empty:
            context.search_results = SearchResultModel(frame)
            context.search_results_snapshot = frame.copy()
            context.search_results_master_base_snapshot = frame.copy()

    if "prompt" in seed:
        context.prompt_text = str(seed.get("prompt") or "")
    if "negative_prompt" in seed:
        context.negative_prompt_text = str(seed.get("negative_prompt") or "")
    if seed.get("warmup_random"):
        from core.headless_random_prompt_service import HeadlessRandomPromptService

        service = HeadlessRandomPromptService(context)
        context.headless_random_prompt_service = service
        service.warmup()

    _seed_module_storage_fixtures(context, seed.get("module_storage"))


def _seed_module_storage_fixtures(context: Any, module_storage: Any) -> None:
    if not isinstance(module_storage, dict):
        return

    char_items = module_storage.get("character_reference")
    if isinstance(char_items, list):
        for item in char_items:
            if not isinstance(item, dict):
                continue
            file_hash = str(item.get("file_hash") or "").strip()
            if not file_hash:
                continue
            _write_png_fixture(
                context.runtime_paths.save_dir / "character_reference" / "images" / f"{file_hash}.png",
                item,
            )

    vibe_items = module_storage.get("vibe_transfer")
    if isinstance(vibe_items, list):
        for item in vibe_items:
            if not isinstance(item, dict):
                continue
            model = str(item.get("model") or "").strip()
            file_hash = str(item.get("file_hash") or "").strip()
            if not model or not file_hash:
                continue
            _write_png_fixture(
                context.runtime_paths.save_dir / "vibe_transfer" / model / "images" / f"{file_hash}.png",
                item,
            )


def _write_png_fixture(path: Path, spec: dict[str, Any]) -> None:
    from PIL import Image

    size = spec.get("size") if isinstance(spec.get("size"), list) else [32, 24]
    width = _coerce_fixture_int(size[0] if len(size) > 0 else 32, default=32, minimum=1, maximum=512)
    height = _coerce_fixture_int(size[1] if len(size) > 1 else 24, default=24, minimum=1, maximum=512)
    color = spec.get("color") if isinstance(spec.get("color"), list) else [120, 30, 200]
    rgb = tuple(
        _coerce_fixture_int(color[index] if len(color) > index else 0, default=0, minimum=0, maximum=255)
        for index in range(3)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), rgb).save(path)


def _coerce_fixture_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


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
        content_error = ""
        if ok and "expected_headers" in check:
            expected_headers = check.get("expected_headers")
            if isinstance(expected_headers, dict):
                for header, expected_value in expected_headers.items():
                    observed_value = response.headers.get(str(header))
                    if observed_value != str(expected_value):
                        ok = False
                        content_error = (
                            f"header {header!r} expected {expected_value!r}, got {observed_value!r}"
                        )
                        break
        if ok and "expected_content_prefix" in check:
            expected_prefix = str(check.get("expected_content_prefix") or "").encode("utf-8")
            if not response.content.startswith(expected_prefix):
                ok = False
                content_error = f"content did not start with {expected_prefix!r}"
        if ok and "expected_content_contains" in check:
            expected_parts = [
                str(part).encode("utf-8")
                for part in check.get("expected_content_contains", [])
            ]
            missing_parts = [part for part in expected_parts if part not in response.content]
            if missing_parts:
                ok = False
                content_error = f"content missing expected bytes: {missing_parts!r}"
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
        if content_error:
            result["error"] = content_error
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
            command_results = [
                _run_websocket_command(ws, command)
                for command in check.get("commands", [])
                if isinstance(command, dict)
            ]
        observed = [message.get("type") for message in messages]
        expected_sync_type = check.get("expected_sync_type")
        sync_ok = expected_sync_type is None or (isinstance(sync_payload, dict) and sync_payload.get("type") == expected_sync_type)
        commands_ok = all(result.get("ok") for result in command_results)
        return {
            "feature": check.get("feature", path),
            "path": path,
            "expected_initial_types": expected,
            "observed_initial_types": observed,
            "sync_type": sync_payload.get("type") if isinstance(sync_payload, dict) else None,
            "commands": command_results,
            "ok": observed == expected and sync_ok and commands_ok,
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


def _run_websocket_command(ws: Any, command: dict[str, Any]) -> dict[str, Any]:
    name = str(command.get("name") or command.get("feature") or "command")
    expected_messages = [
        item for item in command.get("expected_messages", [])
        if isinstance(item, dict)
    ]
    start = time.perf_counter()
    try:
        if "send_json" in command:
            ws.send_text(json.dumps(command.get("send_json"), ensure_ascii=False))
        else:
            ws.send_text(str(command.get("send_text") or ""))
        observed_messages = [ws.receive_json() for _ in expected_messages]
    except Exception as exc:
        return {
            "name": name,
            "ok": False,
            "error": str(exc),
        }

    latency_ms = round((time.perf_counter() - start) * 1000, 3)
    message_results = [
        _validate_expected_websocket_message(observed, expected)
        for observed, expected in zip(observed_messages, expected_messages)
    ]
    ok = all(result.get("ok") for result in message_results)
    max_latency_ms = command.get("max_latency_ms")
    if isinstance(max_latency_ms, (int, float)) and latency_ms > float(max_latency_ms):
        ok = False
        message_results.append({
            "ok": False,
            "error": f"latency {latency_ms}ms exceeded {float(max_latency_ms)}ms",
        })
    return {
        "name": name,
        "latency_ms": latency_ms,
        "messages": message_results,
        "ok": ok,
    }


def _validate_expected_websocket_message(observed: Any, expected: dict[str, Any]) -> dict[str, Any]:
    expected_type = expected.get("type")
    observed_type = observed.get("type") if isinstance(observed, dict) else None
    ok = expected_type is None or observed_type == expected_type
    error = "" if ok else f"expected type {expected_type!r}, got {observed_type!r}"
    if ok and "expected_json_subset" in expected:
        ok, error = _json_contains(observed, expected.get("expected_json_subset"))
    if ok and "expected_json_keys" in expected:
        keys = expected.get("expected_json_keys") or []
        missing = [
            str(key)
            for key in keys
            if not isinstance(observed, dict) or key not in observed
        ]
        if missing:
            ok = False
            error = f"missing JSON keys: {', '.join(missing)}"
    return {
        "expected_type": expected_type,
        "observed_type": observed_type,
        "ok": ok,
        **({"error": error} if error else {}),
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
    client = _make_test_client(backend, user_data, contract)
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
