"""Run an end-to-end packaged Electron verification for NAIA.

This intentionally drives the packaged ``NAIA.exe`` through CDP instead of
calling backend internals directly. It verifies first-run runtime bootstrap,
runtime-owned tag data installation, random prompt generation, and a real
Generate request.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

try:
    from tools.smoke_electron_cdp import CdpClient, _terminate, _wait_for_target
except ModuleNotFoundError:  # pragma: no cover - used when executed as a script.
    from smoke_electron_cdp import CdpClient, _terminate, _wait_for_target


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def _write_payload(payload: dict[str, Any], output: Path | None) -> None:
    if output is None:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _evaluate(client: CdpClient, expression: str) -> Any:
    return client.evaluate(expression)


def _state_expression() -> str:
    return """
(async () => {
  const shell = window.naiaShell ? await window.naiaShell.getState() : null;
  return {
    href: location.href,
    title: document.title,
    readyState: document.readyState,
    hasShell: !!window.naiaShell,
    hasPromptEdit: !!document.getElementById("promptEdit"),
    wsOpen: (() => {
      try { return !!(ws && ws.readyState === WebSocket.OPEN); }
      catch (_) { return false; }
    })(),
    shell,
  };
})()
"""


def _wait_for_app_ready(client: CdpClient, *, debug_port: int, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_state: dict[str, Any] | None = None
    last_log_line = ""
    while time.monotonic() < deadline:
        try:
            state = _evaluate(client, _state_expression()) or {}
        except Exception:
            time.sleep(0.5)
            try:
                client.reconnect()
            except Exception:
                target = _wait_for_target(debug_port, min(10.0, timeout))
                client.close()
                client = CdpClient(target["webSocketDebuggerUrl"], timeout=timeout, debug_port=debug_port)
            continue
        last_state = state
        shell = state.get("shell") if isinstance(state.get("shell"), dict) else {}
        logs = shell.get("logs") if isinstance(shell.get("logs"), list) else []
        if logs:
            line = str(logs[-1].get("line") or "")
            if line and line != last_log_line:
                print(f"[shell] {line}", flush=True)
                last_log_line = line
        if (
            state.get("hasShell")
            and state.get("hasPromptEdit")
            and state.get("wsOpen")
            and shell.get("backendState") == "ready"
        ):
            return state
        time.sleep(2.0)
    raise TimeoutError(f"Electron app did not become ready; last_state={last_state}")


def _fetch_json(client: CdpClient, path: str, *, method: str = "GET") -> dict[str, Any]:
    return _evaluate(client, f"""
(async () => {{
  const response = await fetch({json.dumps(path)}, {{
    method: {json.dumps(method)},
    cache: "no-store",
  }});
  const payload = await response.json().catch(() => ({{}}));
  return {{
    ok: response.ok,
    status: response.status,
    payload,
  }};
}})()
""") or {}


def _initialize_and_download_data(client: CdpClient, *, timeout: float) -> dict[str, Any]:
    initialize = _fetch_json(client, "/api/install-manager/initialize", method="POST")
    before = _fetch_json(client, "/api/install-manager")
    start = _fetch_json(client, "/api/install-manager/tag-archive/download", method="POST")
    snapshots: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout
    last_message = ""
    final_state: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        current = _fetch_json(client, "/api/install-manager")
        payload = current.get("payload") if isinstance(current.get("payload"), dict) else {}
        archive = payload.get("tag_archive") if isinstance(payload.get("tag_archive"), dict) else {}
        download = archive.get("download") if isinstance(archive.get("download"), dict) else {}
        snapshots.append({
            "ready": bool(archive.get("ready")),
            "file_count": int(archive.get("file_count") or 0),
            "expected_count": int(archive.get("expected_count") or 0),
            "download": {
                "active": bool(download.get("active")),
                "phase": str(download.get("phase") or ""),
                "percent": int(download.get("percent") or 0),
                "message": str(download.get("message") or ""),
                "error": str(download.get("error") or ""),
                "done": bool(download.get("done")),
            },
        })
        message = snapshots[-1]["download"]["message"]
        if message and message != last_message:
            print(f"[data] {message}", flush=True)
            last_message = message
        if archive.get("ready"):
            final_state = current
            break
        if download.get("error") and not download.get("active"):
            final_state = current
            break
        time.sleep(2.0)
    if final_state is None:
        final_state = _fetch_json(client, "/api/install-manager")
    payload = final_state.get("payload") if isinstance(final_state.get("payload"), dict) else {}
    archive = payload.get("tag_archive") if isinstance(payload.get("tag_archive"), dict) else {}
    return {
        "ok": bool(archive.get("ready")),
        "initialize": initialize,
        "before": before,
        "start": start,
        "final": final_state,
        "snapshots_tail": snapshots[-10:],
    }


def _random_prompt(client: CdpClient, *, timeout: float) -> dict[str, Any]:
    timeout_ms = max(1000, int(timeout * 1000))
    return _evaluate(client, f"""
(async () => {{
  const result = {{
    accepted: false,
    promptUpdated: false,
    latencyMs: null,
    promptLength: 0,
    reason: "",
  }};
  const prompt = document.getElementById("promptEdit");
  let socket = null;
  try {{ socket = ws; }} catch (_) {{ socket = null; }}
  if (!prompt || !socket || socket.readyState !== WebSocket.OPEN || typeof send !== "function") {{
    result.reason = "prompt editor, websocket, or send() is unavailable";
    return result;
  }}
  const sentinel = `__naia_verify_random_${{Math.round(performance.now())}}__`;
  prompt.value = sentinel;
  prompt.dispatchEvent(new Event("input", {{bubbles: true}}));
  await new Promise(resolve => setTimeout(resolve, 50));
  const started = performance.now();
  try {{
    send("random");
    result.accepted = true;
  }} catch (error) {{
    result.reason = error && error.message ? error.message : String(error);
    return result;
  }}
  while (performance.now() - started < {timeout_ms}) {{
    await new Promise(resolve => setTimeout(resolve, 100));
    const value = String(prompt.value || "");
    if (value && value !== sentinel && !value.includes(sentinel)) {{
      result.promptUpdated = true;
      result.latencyMs = Math.round((performance.now() - started) * 1000) / 1000;
      result.promptLength = value.length;
      result.promptPreview = value.slice(0, 240);
      break;
    }}
  }}
  if (!result.promptUpdated && !result.reason) {{
    result.reason = "timed out waiting for random prompt";
  }}
  if (window._randomTimeout) {{
    window.clearTimeout(window._randomTimeout);
    window._randomTimeout = null;
  }}
  if (typeof unlockRandomButton === "function") {{
    unlockRandomButton({{clearRequest: true}});
  }}
  return result;
}})()
""") or {}


def _generate_image(client: CdpClient, *, timeout: float) -> dict[str, Any]:
    timeout_ms = max(1000, int(timeout * 1000))
    return _evaluate(client, f"""
(async () => {{
  const result = {{
    accepted: false,
    dispatched: false,
    completed: false,
    errored: false,
    error: "",
    imageBlob: false,
    imageBytes: 0,
    imageMeta: null,
    latencyMs: null,
    promptLength: 0,
    statusMessages: [],
  }};
  const promptEditEl = document.getElementById("promptEdit");
  const negativeEl = document.getElementById("negEdit");
  let socket = null;
  try {{ socket = ws; }} catch (_) {{ socket = null; }}
  if (!promptEditEl || !socket || socket.readyState !== WebSocket.OPEN || typeof requestGenerate !== "function") {{
    result.error = "prompt editor, websocket, or requestGenerate() is unavailable";
    return result;
  }}
  const currentPrompt = String(promptEditEl.value || "").trim();
  const prompt = currentPrompt || "1girl, solo, looking at viewer, best quality";
  promptEditEl.value = prompt;
  promptEditEl.dispatchEvent(new Event("input", {{bubbles: true}}));
  result.promptLength = prompt.length;
  const started = performance.now();
  const handler = event => {{
    if (event.data instanceof Blob) {{
      result.imageBlob = true;
      result.imageBytes = event.data.size || 0;
      result.completed = true;
      if (result.latencyMs == null) {{
        result.latencyMs = Math.round((performance.now() - started) * 1000) / 1000;
      }}
      return;
    }}
    try {{
      const msg = JSON.parse(String(event.data || ""));
      if (msg.type === "generation_dispatched") {{
        result.dispatched = !!msg.ok;
        result.dispatchPayload = msg;
      }} else if (msg.type === "generation_error") {{
        result.errored = true;
        result.error = msg.message || "generation_error";
      }} else if (msg.type === "image_meta") {{
        result.imageMeta = msg;
      }} else if (msg.type === "status") {{
        result.statusMessages.push(msg.message || "");
      }}
    }} catch (_) {{}}
  }};
  socket.addEventListener("message", handler);
  try {{
    result.accepted = requestGenerate({{
      prompt,
      negative_prompt: negativeEl ? String(negativeEl.value || "") : "",
      overrides: {{
        width: 512,
        height: 512,
        resolution: "512 x 512",
        steps: 8,
        cfg_scale: 4.5,
        random_resolution: false,
        auto_fit_resolution: false,
        enable_hr: false,
        auto_save: false,
      }},
    }});
  }} catch (error) {{
    result.error = error && error.message ? error.message : String(error);
    socket.removeEventListener("message", handler);
    return result;
  }}
  while (performance.now() - started < {timeout_ms}) {{
    await new Promise(resolve => setTimeout(resolve, 250));
    if (result.completed || result.errored) break;
  }}
  socket.removeEventListener("message", handler);
  if (!result.completed && !result.errored && !result.error) {{
    result.error = "timed out waiting for generation result";
  }}
  if (latestResultBlob instanceof Blob && !result.imageBlob) {{
    result.imageBlob = true;
    result.imageBytes = latestResultBlob.size || 0;
    result.completed = true;
  }}
  if (!result.imageMeta && typeof latestImageMeta === "object" && latestImageMeta) {{
    result.imageMeta = latestImageMeta;
  }}
  return result;
}})()
""") or {}


def _capture_screenshot(client: CdpClient, output: Path) -> str:
    result = client.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
    data = result.get("data")
    if not data:
        return ""
    import base64

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(base64.b64decode(data))
    return str(output)


def verify_packaged_electron_e2e(
    *,
    package_root: Path,
    output: Path | None,
    debug_port: int,
    backend_port: int,
    ready_timeout: float,
    data_timeout: float,
    random_timeout: float,
    generation_timeout: float,
) -> dict[str, Any]:
    package_root = package_root.resolve()
    exe = package_root / "NAIA.exe"
    user_data = package_root / "user-data"
    logs_dir = user_data / "verification-logs"
    stdout_log = logs_dir / "electron_stdout.log"
    stderr_log = logs_dir / "electron_stderr.log"
    screenshot_path = logs_dir / "verification_result.png"
    payload: dict[str, Any] = {
        "ok": False,
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "package_root": str(package_root),
        "exe": str(exe),
        "user_data": str(user_data),
        "debug_port": debug_port,
        "backend_port": backend_port,
        "checks": {},
        "violations": [],
    }
    if not exe.is_file():
        payload["violations"].append({"path": str(exe), "reason": "NAIA.exe is missing"})
        _write_payload(payload, output)
        return payload
    user_data.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "NAIA_ELECTRON_REMOTE_DEBUGGING_PORT": str(debug_port),
        "NAIA_BACKEND_PORT": str(backend_port),
        "NAIA_HEADLESS_OPEN_BROWSER": "0",
        "NAIA_USER_DATA_DIR": str(user_data),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    proc: subprocess.Popen | None = None
    client: CdpClient | None = None
    stdout_handle = stdout_log.open("w", encoding="utf-8", errors="replace")
    stderr_handle = stderr_log.open("w", encoding="utf-8", errors="replace")
    try:
        print(f"[launch] {exe}", flush=True)
        proc = subprocess.Popen(
            [str(exe)],
            cwd=package_root,
            env=env,
            stdout=stdout_handle,
            stderr=stderr_handle,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        target = _wait_for_target(debug_port, ready_timeout)
        client = CdpClient(target["webSocketDebuggerUrl"], timeout=ready_timeout, debug_port=debug_port)
        ready_started = time.monotonic()
        ready_state = _wait_for_app_ready(client, debug_port=debug_port, timeout=ready_timeout)
        payload["checks"]["startup"] = {
            "ok": True,
            "elapsed_s": round(time.monotonic() - ready_started, 3),
            "state": ready_state,
        }

        data = _initialize_and_download_data(client, timeout=data_timeout)
        payload["checks"]["data"] = data

        random_prompt = _random_prompt(client, timeout=random_timeout)
        payload["checks"]["random_prompt"] = random_prompt

        generation = _generate_image(client, timeout=generation_timeout)
        payload["checks"]["generation"] = generation

        screenshot = _capture_screenshot(client, screenshot_path)
        payload["screenshot"] = screenshot

        shell_state = _evaluate(client, _state_expression()) or {}
        payload["final_state"] = shell_state
        shell = shell_state.get("shell") if isinstance(shell_state.get("shell"), dict) else {}
        payload["shell_logs_tail"] = shell.get("logs", [])[-80:] if isinstance(shell.get("logs"), list) else []

        runtime_env_python = user_data / "runtime-env" / "Scripts" / "python.exe"
        tag_dir = user_data / "data" / "tags"
        payload["filesystem"] = {
            "runtime_env_python": str(runtime_env_python),
            "runtime_env_python_exists": runtime_env_python.is_file(),
            "data_dir": str(user_data / "data"),
            "data_dir_exists": (user_data / "data").is_dir(),
            "tag_dir": str(tag_dir),
            "tag_file_count": len(list(tag_dir.glob("tags_*.parquet"))) if tag_dir.is_dir() else 0,
        }

        if not payload["checks"]["startup"].get("ok"):
            payload["violations"].append({"path": "startup", "reason": "Electron app did not reach ready state"})
        if not payload["filesystem"]["runtime_env_python_exists"]:
            payload["violations"].append({"path": "user-data/runtime-env", "reason": "managed runtime env Python is missing"})
        if not payload["filesystem"]["data_dir_exists"]:
            payload["violations"].append({"path": "user-data/data", "reason": "runtime data directory is missing"})
        if not data.get("ok"):
            payload["violations"].append({"path": "api/install-manager", "reason": "tag archive download/init did not complete"})
        if not random_prompt.get("promptUpdated"):
            payload["violations"].append({"path": "random_prompt", "reason": str(random_prompt.get("reason") or "random prompt did not update")})
        if not generation.get("completed") or not generation.get("imageBlob"):
            payload["violations"].append({"path": "generation", "reason": str(generation.get("error") or "generation image blob was not observed")})

        payload["ok"] = not payload["violations"]
        return payload
    except Exception as exc:
        payload["violations"].append({"path": "verification", "reason": f"{type(exc).__name__}: {exc}"})
        return payload
    finally:
        try:
            if client is not None:
                client.close()
        finally:
            if proc is not None:
                _terminate(proc)
            stdout_handle.close()
            stderr_handle.close()
            payload["logs"] = {
                "stdout": str(stdout_log),
                "stderr": str(stderr_log),
            }
            _write_payload(payload, output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a packaged NAIA Electron app end-to-end.")
    parser.add_argument("package_root", help="Packaged Electron win-unpacked directory.")
    parser.add_argument("--output", default="", help="Optional JSON output path.")
    parser.add_argument("--debug-port", type=int, default=9347)
    parser.add_argument("--backend-port", type=int, default=7357)
    parser.add_argument("--ready-timeout", type=float, default=900.0)
    parser.add_argument("--data-timeout", type=float, default=600.0)
    parser.add_argument("--random-timeout", type=float, default=60.0)
    parser.add_argument("--generation-timeout", type=float, default=240.0)
    args = parser.parse_args(argv)

    payload = verify_packaged_electron_e2e(
        package_root=Path(args.package_root),
        output=Path(args.output) if args.output else None,
        debug_port=args.debug_port,
        backend_port=args.backend_port,
        ready_timeout=args.ready_timeout,
        data_timeout=args.data_timeout,
        random_timeout=args.random_timeout,
        generation_timeout=args.generation_timeout,
    )
    json.dump(_json_safe(payload), sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
