"""Smoke-test the NAIA Electron shell through Chromium DevTools Protocol.

This script is intentionally optional at the current migration stage: it only
runs when Electron is installed or a packaged app folder exists. The dry-run
path is testable without installing Electron and keeps the eventual runtime
smoke command stable.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ELECTRON_ROOT = ROOT / "app" / "electron"
DEFAULT_PACKAGE_ROOT = DEFAULT_ELECTRON_ROOT / "dist" / "win-unpacked"
DEFAULT_DEBUG_PORT = 9336
DEFAULT_BACKEND_PORT = 7243
SMOKE_IMAGE_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/"
    "l6B5xQAAAABJRU5ErkJggg=="
)


class CdpClient:
    def __init__(self, websocket_url: str, *, timeout: float = 60.0, debug_port: int | None = None):
        self.websocket_url = websocket_url
        self.timeout = timeout
        self.debug_port = debug_port
        self.ws = self._connect(websocket_url)
        self._next_id = 0

    def _connect(self, websocket_url: str):
        import websocket  # Imported lazily so --dry-run has no runtime dependency.

        return websocket.create_connection(websocket_url, timeout=max(10.0, self.timeout + 5.0))

    def reconnect(self) -> None:
        if self.debug_port is None:
            raise RuntimeError("CDP reconnect requires debug_port")
        self.close()
        target = _wait_for_target(self.debug_port, self.timeout)
        self.websocket_url = str(target["webSocketDebuggerUrl"])
        self.ws = self._connect(self.websocket_url)

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass

    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        self.ws.send(json.dumps({
            "id": request_id,
            "method": method,
            "params": params or {},
        }))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(f"CDP {method} failed: {message['error']}")
            return message.get("result") or {}

    def evaluate(self, expression: str) -> Any:
        result = self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        })
        remote_result = result.get("result") or {}
        return remote_result.get("value")

    def reload(self) -> None:
        self.send("Page.reload", {"ignoreCache": True})


def _find_source_electron(electron_root: Path) -> str | None:
    candidates = [
        electron_root / "node_modules" / "electron" / "dist" / "electron.exe",
        electron_root / "node_modules" / ".bin" / "electron.cmd",
        electron_root / "node_modules" / ".bin" / "electron",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which("electron")


def _packaged_exe(package_root: Path, exe_name: str) -> Path:
    return package_root / exe_name


def build_launch_config(
    *,
    mode: str,
    electron_root: str | Path = DEFAULT_ELECTRON_ROOT,
    package_root: str | Path = DEFAULT_PACKAGE_ROOT,
    electron_command: str | None = None,
    exe_name: str = "NAIA.exe",
    debug_port: int = DEFAULT_DEBUG_PORT,
    backend_port: int = DEFAULT_BACKEND_PORT,
    user_data: str | Path | None = None,
) -> dict[str, Any]:
    electron_dir = Path(electron_root).resolve()
    package_dir = Path(package_root).resolve()
    env = {
        "NAIA_ELECTRON_REMOTE_DEBUGGING_PORT": str(debug_port),
        "NAIA_BACKEND_PORT": str(backend_port),
        "NAIA_HEADLESS_OPEN_BROWSER": "0",
        # The first-run tag-data gate now parks on a user choice (download vs
        # import) instead of auto-downloading. There is no human to click in an
        # automated CDP smoke, so skip the gate here — this smoke validates the
        # packaged shell + Remote Web feature surfaces, not tag provisioning
        # (the gate's logic is covered by app/electron/test/main_contract.test.cjs).
        "NAIA_ELECTRON_SKIP_RUNTIME_INSTALL": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    if user_data:
        user_data_root = Path(user_data).resolve()
        env["NAIA_USER_DATA_DIR"] = str(user_data_root)
        env["PYTHONPYCACHEPREFIX"] = str(user_data_root / "cache" / "python-bytecode")

    if mode == "source":
        command = electron_command or _find_source_electron(electron_dir)
        if not command:
            return {
                "ok": False,
                "mode": mode,
                "reason": "Electron command not found; install app/electron dependencies or pass --electron-command.",
                "command": None,
                "args": [],
                "cwd": str(electron_dir),
                "env": env,
            }
        env["NAIA_REPO_ROOT"] = str(ROOT)
        return {
            "ok": True,
            "mode": mode,
            "command": command,
            "args": [str(electron_dir)],
            "cwd": str(electron_dir),
            "env": env,
        }

    if mode == "packaged":
        exe = _packaged_exe(package_dir, exe_name)
        if not exe.is_file():
            return {
                "ok": False,
                "mode": mode,
                "reason": f"Packaged Electron executable not found: {exe}",
                "command": str(exe),
                "args": [],
                "cwd": str(package_dir),
                "env": env,
            }
        return {
            "ok": True,
            "mode": mode,
            "command": str(exe),
            "args": [],
            "cwd": str(package_dir),
            "env": env,
        }

    return {
        "ok": False,
        "mode": mode,
        "reason": f"Unsupported mode: {mode}",
        "command": None,
        "args": [],
        "cwd": str(electron_dir),
        "env": env,
    }


def _url_json(url: str, timeout: float = 2.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait_for_target(debug_port: int, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            targets = _url_json(f"http://127.0.0.1:{debug_port}/json/list")
            for target in targets:
                if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                    return target
        except Exception as exc:
            last_error = exc
        time.sleep(0.25)
    if last_error:
        raise TimeoutError(f"CDP target not available: {last_error}")
    raise TimeoutError("CDP target not available")


def _wait_for_shell_state(client: CdpClient, timeout: float) -> dict[str, Any]:
    expression = """
(async () => {
  const state = window.naiaShell && await window.naiaShell.getState();
  localStorage.setItem("__naia_cdp_smoke", "ok");
  sessionStorage.setItem("__naia_cdp_smoke", "ok");
  return {
    href: location.href,
    title: document.title,
    readyState: document.readyState,
    innerWidth: window.innerWidth,
    innerHeight: window.innerHeight,
    hasShell: !!window.naiaShell,
    hasWebSocket: typeof WebSocket === "function",
    hasClipboard: !!navigator.clipboard,
    hasFileInput: !!document.querySelector('input[type="file"]'),
    localStorageWorks: localStorage.getItem("__naia_cdp_smoke") === "ok",
    sessionStorageWorks: sessionStorage.getItem("__naia_cdp_smoke") === "ok",
    backendState: state && state.backendState,
    backendUrl: state && state.backendUrl,
    runtimeDataRoot: state && state.runtimeDataRoot,
  };
})()
"""
    deadline = time.monotonic() + timeout
    last_state: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        try:
            state = client.evaluate(expression) or {}
        except RuntimeError as exc:
            message = str(exc)
            if (
                "Execution context was destroyed" not in message
                and "Cannot find context with specified id" not in message
                and "Inspected target navigated or closed" not in message
            ):
                raise
            try:
                client.reconnect()
            except Exception:
                pass
            time.sleep(0.5)
            continue
        last_state = state
        if (
            state.get("hasShell")
            and state.get("backendState") == "ready"
            and "desktop_shell=1&electron_shell=1" in str(state.get("href", ""))
        ):
            return state
        time.sleep(0.5)
    raise TimeoutError(f"Electron shell did not become ready; last state={last_state}")


def _wait_for_download(downloads_dir: Path, start_time: float, timeout: float) -> Path:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if downloads_dir.is_dir():
            candidates = [
                path for path in downloads_dir.iterdir()
                if path.is_file() and path.stat().st_mtime >= start_time
            ]
            if candidates:
                return max(candidates, key=lambda path: path.stat().st_mtime)
        time.sleep(0.25)
    raise TimeoutError(f"download did not appear in {downloads_dir}")


def _trigger_synthetic_download(client: CdpClient, runtime_data_root: str, timeout: float) -> dict[str, Any]:
    downloads_dir = Path(runtime_data_root) / "downloads"
    start_time = time.time()
    filename = f"naia-electron-smoke-{int(start_time)}.txt"
    expression = f"""
(() => {{
  const blob = new Blob(["NAIA Electron smoke download"], {{ type: "text/plain" }});
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = {json.dumps(filename)};
  document.body.appendChild(anchor);
  anchor.click();
  setTimeout(() => {{
    URL.revokeObjectURL(url);
    anchor.remove();
  }}, 1000);
  return anchor.download;
}})()
"""
    requested_name = client.evaluate(expression)
    downloaded = _wait_for_download(downloads_dir, start_time, timeout)
    return {
        "requested_name": requested_name,
        "path": str(downloaded),
        "exists": downloaded.is_file(),
        "size": downloaded.stat().st_size,
        "under_runtime_downloads": downloaded.parent.resolve() == downloads_dir.resolve(),
    }


def _verify_storage_persistence(client: CdpClient, timeout: float) -> dict[str, Any]:
    marker = f"ok-{int(time.time())}"
    client.evaluate(f"""
(() => {{
  localStorage.setItem("__naia_cdp_persist", {json.dumps(marker)});
  sessionStorage.setItem("__naia_cdp_persist", {json.dumps(marker)});
  return true;
}})()
""")
    try:
        client.reload()
    except RuntimeError as exc:
        if "navigated or closed" not in str(exc):
            raise
    time.sleep(0.5)
    client.reconnect()
    deadline = time.monotonic() + timeout
    last_state: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        state = client.evaluate(f"""
(() => {{
  return {{
    readyState: document.readyState,
    localStorageValue: localStorage.getItem("__naia_cdp_persist"),
    sessionStorageValue: sessionStorage.getItem("__naia_cdp_persist"),
  }};
}})()
""") or {}
        last_state = state
        if state.get("readyState") == "complete" and state.get("localStorageValue") == marker:
            return {
                "localStoragePersistsAfterReload": True,
                "sessionStoragePersistsAfterReload": state.get("sessionStorageValue") == marker,
            }
        time.sleep(0.25)
    raise TimeoutError(f"storage persistence check failed; last state={last_state}")


def _wait_for_active_websocket(client: CdpClient, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_state: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        state = client.evaluate("""
(() => {
  let readyState = -1;
  let hasSocket = false;
  try {
    hasSocket = typeof ws !== "undefined" && !!ws;
    readyState = hasSocket && typeof WebSocket === "function" ? ws.readyState : -1;
  } catch (_) {
    hasSocket = false;
  }
  return {
    hasSocket,
    readyState,
    open: typeof WebSocket === "function" && readyState === WebSocket.OPEN,
  };
})()
""") or {}
        last_state = state
        if state.get("open"):
            return state
        time.sleep(0.25)
    raise TimeoutError(f"active websocket did not become open; last state={last_state}")


def _wait_for_result_image_input_surface(client: CdpClient, timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    deadline = time.monotonic() + timeout
    reload_after = started + min(5.0, max(1.0, timeout / 3.0))
    reloaded = False
    last_state: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        state = client.evaluate("""
(() => {
  /* __naia_cdp_input_surface_probe */
  const input = document.querySelector('input[type="file"]');
  const viewer = document.querySelector(".viewer");
  return {
    fileInputPresent: !!input,
    fileInputAccept: input ? String(input.getAttribute("accept") || "") : "",
    viewerPresent: !!viewer,
  };
})()
""") or {}
        last_state = state
        if state.get("fileInputPresent") and state.get("viewerPresent"):
            return state
        if not reloaded and time.monotonic() >= reload_after:
            reloaded = True
            try:
                client.reload()
            except RuntimeError as exc:
                if "navigated or closed" not in str(exc):
                    raise
            time.sleep(0.5)
            client.reconnect()
        time.sleep(0.25)
    raise TimeoutError(f"result image input surface did not become ready; last state={last_state}")


def _verify_file_picker_surface(client: CdpClient) -> dict[str, Any]:
    return client.evaluate("""
(() => {
  /* __naia_cdp_file_picker_probe */
  const inputs = Array.from(document.querySelectorAll('input[type="file"]'));
  return {
    present: inputs.length > 0,
    count: inputs.length,
    accept: inputs.map(input => String(input.getAttribute('accept') || '')),
    showPickerAvailable: typeof HTMLInputElement !== "undefined"
      && typeof HTMLInputElement.prototype.showPicker === "function",
    disabledCount: inputs.filter(input => input.disabled).length,
  };
})()
""") or {}


def _verify_clipboard_and_paste_surface(client: CdpClient) -> dict[str, Any]:
    image_url = json.dumps(SMOKE_IMAGE_DATA_URL)
    return client.evaluate(f"""
(async () => {{
  /* __naia_cdp_clipboard_probe */
  const result = {{
    clipboardReadApi: !!(navigator.clipboard && typeof navigator.clipboard.read === "function"),
    clipboardWriteApi: !!(navigator.clipboard && typeof navigator.clipboard.write === "function"),
    dataTransferAvailable: typeof DataTransfer === "function",
    clipboardEventAvailable: typeof ClipboardEvent === "function",
    eventAvailable: typeof Event === "function",
    syntheticImagePastePrevented: false,
    syntheticImagePasteDispatched: false,
    reason: "",
  }};
  if (!result.dataTransferAvailable || !result.eventAvailable) {{
    result.reason = "DataTransfer or Event unavailable";
    return result;
  }}
  try {{
    const transfer = new DataTransfer();
    transfer.setData("text/plain", {image_url});
    const event = new Event("paste", {{bubbles: true, cancelable: true}});
    Object.defineProperty(event, "clipboardData", {{value: transfer}});
    result.syntheticImagePasteDispatched = document.dispatchEvent(event);
    result.syntheticImagePastePrevented = event.defaultPrevented;
  }} catch (error) {{
    result.reason = error && error.message ? error.message : String(error);
  }}
  await new Promise(resolve => setTimeout(resolve, 50));
  return result;
}})()
""") or {}


def _verify_drag_drop_surface(client: CdpClient) -> dict[str, Any]:
    image_url = json.dumps(SMOKE_IMAGE_DATA_URL)
    return client.evaluate(f"""
(async () => {{
  /* __naia_cdp_drag_drop_probe */
  const target = document.querySelector(".viewer");
  const result = {{
    targetPresent: !!target,
    dataTransferAvailable: typeof DataTransfer === "function",
    dragEnterPrevented: false,
    dragOverPrevented: false,
    dropPrevented: false,
    dropEffect: "",
    activeClassObserved: false,
    reason: "",
  }};
  if (!target || !result.dataTransferAvailable) {{
    result.reason = !target ? "viewer target missing" : "DataTransfer unavailable";
    return result;
  }}
  try {{
    const transfer = new DataTransfer();
    transfer.setData("text/plain", {image_url});
    const dragEnter = new DragEvent("dragenter", {{bubbles: true, cancelable: true, dataTransfer: transfer}});
    target.dispatchEvent(dragEnter);
    result.dragEnterPrevented = dragEnter.defaultPrevented;
    result.activeClassObserved = target.classList.contains("drag-over");
    const dragOver = new DragEvent("dragover", {{bubbles: true, cancelable: true, dataTransfer: transfer}});
    target.dispatchEvent(dragOver);
    result.dragOverPrevented = dragOver.defaultPrevented;
    result.dropEffect = transfer.dropEffect || "";
    const drop = new DragEvent("drop", {{bubbles: true, cancelable: true, dataTransfer: transfer}});
    target.dispatchEvent(drop);
    result.dropPrevented = drop.defaultPrevented;
  }} catch (error) {{
    result.reason = error && error.message ? error.message : String(error);
  }}
  await new Promise(resolve => setTimeout(resolve, 50));
  return result;
}})()
""") or {}


def _verify_websocket_reconnect(client: CdpClient, timeout: float) -> dict[str, Any]:
    timeout_ms = max(1000, int(timeout * 1000))
    return client.evaluate(f"""
(async () => {{
  /* __naia_cdp_ws_reconnect_probe */
  const result = {{
    activeSocketFound: false,
    closedOriginal: false,
    reconnected: false,
    originalReadyState: -1,
    finalReadyState: -1,
    elapsedMs: 0,
    reason: "",
  }};
  let original = null;
  try {{
    original = typeof ws !== "undefined" ? ws : null;
  }} catch (_) {{
    original = null;
  }}
  if (!original || typeof WebSocket !== "function") {{
    result.reason = "active websocket unavailable";
    return result;
  }}
  result.activeSocketFound = true;
  result.originalReadyState = original.readyState;
  if (original.readyState !== WebSocket.OPEN) {{
    result.reason = "active websocket is not open";
    return result;
  }}
  const started = performance.now();
  try {{
    original.close(1000, "naia-cdp-reconnect-smoke");
    result.closedOriginal = true;
  }} catch (error) {{
    result.reason = error && error.message ? error.message : String(error);
    return result;
  }}
  while (performance.now() - started < {timeout_ms}) {{
    await new Promise(resolve => setTimeout(resolve, 100));
    let current = null;
    try {{
      current = typeof ws !== "undefined" ? ws : null;
    }} catch (_) {{
      current = null;
    }}
    if (current && current !== original) {{
      result.finalReadyState = current.readyState;
      if (current.readyState === WebSocket.OPEN) {{
        result.reconnected = true;
        result.elapsedMs = Math.round(performance.now() - started);
        return result;
      }}
    }}
  }}
  result.elapsedMs = Math.round(performance.now() - started);
  result.reason = "timed out waiting for replacement websocket";
  return result;
}})()
""") or {}


def _measure_action_dispatch(client: CdpClient) -> dict[str, Any]:
    return client.evaluate("""
(() => {
  /* __naia_cdp_action_dispatch_probe */
  const result = {
    available: false,
    activeSocketOpen: false,
    generate: {dispatched: false, latencyMs: null},
    random: {dispatched: false, latencyMs: null},
    payloadTypes: [],
    reason: "",
  };
  let socket = null;
  try {
    socket = typeof ws !== "undefined" ? ws : null;
  } catch (_) {
    socket = null;
  }
  if (!socket || typeof WebSocket !== "function") {
    result.reason = "active websocket unavailable";
    return result;
  }
  result.activeSocketOpen = socket.readyState === WebSocket.OPEN;
  if (!result.activeSocketOpen) {
    result.reason = "active websocket is not open";
    return result;
  }
  const originalSend = socket.send;
  const payloads = [];
  socket.send = payload => {
    payloads.push(String(payload));
  };
  try {
    result.available = true;
    if (typeof requestGenerate === "function") {
      const t0 = performance.now();
      const accepted = requestGenerate({
        prompt: "naia cdp smoke prompt",
        negative_prompt: "",
        overrides: {
          input: "naia cdp smoke prompt",
          _raw_input: "naia cdp smoke prompt",
          negative_prompt: "",
        },
      });
      result.generate.latencyMs = Math.round((performance.now() - t0) * 1000) / 1000;
      result.generate.dispatched = !!accepted && payloads.some(payload => {
        try { return JSON.parse(payload).type === "generate"; }
        catch (_) { return false; }
      });
    } else {
      result.generate.reason = "requestGenerate unavailable";
    }
    if (typeof send === "function") {
      const before = payloads.length;
      const t0 = performance.now();
      send("random");
      result.random.latencyMs = Math.round((performance.now() - t0) * 1000) / 1000;
      result.random.dispatched = payloads.slice(before).some(payload => {
        try { return JSON.parse(payload).type === "random"; }
        catch (_) { return false; }
      });
    } else {
      result.random.reason = "send unavailable";
    }
  } finally {
    socket.send = originalSend;
    if (window._randomTimeout) {
      window.clearTimeout(window._randomTimeout);
      window._randomTimeout = null;
    }
    if (typeof unlockRandomButton === "function") {
      unlockRandomButton({clearRequest: true});
    }
  }
  result.payloadTypes = payloads.map(payload => {
    try { return JSON.parse(payload).type || ""; }
    catch (_) { return ""; }
  }).filter(Boolean);
  return result;
})()
""") or {}


def _verify_feature_workflows_surface(client: CdpClient, timeout: float) -> dict[str, Any]:
    timeout_ms = max(1000, int(timeout * 1000))
    return client.evaluate(f"""
(async () => {{
  /* __naia_cdp_feature_workflows_probe */
  const requiredFeatureIds = [
    "random_prompt",
    "generate",
    "result_display",
    "prompt_tools",
    "params",
    "presets",
    "danbooru",
    "artist_thumbnail",
    "img2img",
    "vibe_transfer_storage",
    "character_reference",
    "automation",
    "enhance",
    "setup_api_settings",
    "history",
    "save_output",
  ];
  const result = {{
    requiredFeatureIds,
    requiredFeatureCount: requiredFeatureIds.length,
    observedFeatureCount: 0,
    allRequiredFeaturesObserved: false,
    mode: document.getElementById("modeSelect")?.value || "",
    uiSurface: {{}},
    functions: {{}},
    websocket: {{}},
    routeChecks: [],
    domChecks: [],
    features: Object.fromEntries(requiredFeatureIds.map(id => [id, {{
      ok: false,
      evidence: [],
      missing: [],
    }}])),
    nonDestructive: true,
    externalLiveNotExercised: [
      "danbooru_post_fetch",
      "artist_thumb_generate",
      "character_viewer_generate",
      "result_enhance_execute",
    ],
  }};
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const deadline = performance.now() + {timeout_ms};
  while (performance.now() < deadline) {{
    const hasLauncher = !!document.querySelector("#moduleLauncher .module-btn[data-module]");
    const hasBaseControls = !!document.querySelector("#btnRnd") && !!document.querySelector("#btnGen");
    const hasRightTabs = !!document.querySelector("#rightTabResult") && !!document.querySelector("#rightTabArtists");
    if (hasLauncher && hasBaseControls && hasRightTabs) break;
    await sleep(100);
  }}

  function statusMatches(status, expected) {{
    return expected.includes(status);
  }}
  async function runRouteCheck(check) {{
    const started = performance.now();
    const entry = {{
      key: check.key,
      feature: check.feature,
      method: check.method || "GET",
      path: check.path,
      expectedStatus: check.expectedStatus,
      status: null,
      ok: false,
      elapsedMs: null,
      error: "",
    }};
    try {{
      const headers = {{"Accept": "application/json"}};
      const options = {{method: entry.method, headers, cache: "no-store"}};
      if (Object.prototype.hasOwnProperty.call(check, "body")) {{
        headers["Content-Type"] = check.contentType || "application/json";
        options.body = check.body;
      }}
      const response = await fetch(check.path, options);
      entry.status = response.status;
      entry.ok = statusMatches(response.status, check.expectedStatus);
      entry.contentType = response.headers.get("content-type") || "";
      await response.arrayBuffer().catch(() => null);
    }} catch (error) {{
      entry.error = error && error.message ? error.message : String(error);
    }} finally {{
      entry.elapsedMs = Math.round((performance.now() - started) * 1000) / 1000;
      result.routeChecks.push(entry);
    }}
    return entry;
  }}
  const routeChecks = [
    {{key: "status", feature: "setup_api_settings", path: "/api/status", expectedStatus: [200]}},
    {{key: "runtime_capabilities", feature: "setup_api_settings", path: "/api/runtime/capabilities", expectedStatus: [200]}},
    {{key: "queue_state", feature: "generate", path: "/api/queue/state", expectedStatus: [200]}},
    {{key: "resolutions", feature: "params", path: "/api/resolutions", expectedStatus: [200]}},
    {{key: "prompt_highlight_index", feature: "prompt_tools", path: "/api/prompt-highlight-index", expectedStatus: [200]}},
    {{key: "tag_lookup", feature: "prompt_tools", path: "/api/tag/lookup?tag=1girl", expectedStatus: [200, 404]}},
    {{key: "event_preset_status", feature: "presets", path: "/api/event-preset/status", expectedStatus: [200]}},
    {{key: "event_preset_bootstrap", feature: "presets", path: "/api/event-preset/bootstrap?ratingId=s&personId=1girl_solo", expectedStatus: [200]}},
    {{key: "clothes_preset_status", feature: "presets", path: "/api/clothes-preset/status", expectedStatus: [200]}},
    {{key: "expression_preset_status", feature: "presets", path: "/api/expression-preset/status", expectedStatus: [200]}},
    {{key: "danbooru_browser_open", feature: "danbooru", method: "POST", path: "/api/danbooru/browser/open", body: JSON.stringify({{query: "rating:g"}}), expectedStatus: [200]}},
    {{key: "artist_thumb_state", feature: "artist_thumbnail", path: "/api/artist-thumb/state", expectedStatus: [200]}},
    {{key: "character_viewer_state", feature: "character_reference", path: "/api/character-viewer/state", expectedStatus: [200]}},
    {{key: "latest_image", feature: "result_display", path: "/api/latest-image", expectedStatus: [200, 404]}},
    {{key: "result_metadata", feature: "result_display", path: "/api/result/metadata", expectedStatus: [200, 404]}},
    {{key: "history_list", feature: "history", path: "/api/history/list", expectedStatus: [200]}},
    {{key: "viewer_list", feature: "history", path: "/api/viewer/list", expectedStatus: [200]}},
    {{key: "unsaved_download", feature: "save_output", path: "/api/history/unsaved/download", expectedStatus: [200, 404]}},
    {{key: "result_save_empty", feature: "save_output", method: "POST", path: "/api/result/action/save", expectedStatus: [400]}},
    {{key: "image_action_img2img_empty", feature: "img2img", method: "POST", path: "/api/image-action/img2img?label=CDP%20Smoke", body: "", contentType: "application/octet-stream", expectedStatus: [400]}},
    {{key: "image_action_vibe_empty", feature: "vibe_transfer_storage", method: "POST", path: "/api/image-action/vibe?label=CDP%20Smoke", body: "", contentType: "application/octet-stream", expectedStatus: [400]}},
  ];
  for (const check of routeChecks) {{
    await runRouteCheck(check);
  }}

  const domChecks = [
    {{key: "random_button", feature: "random_prompt", selector: "#btnRnd"}},
    {{key: "generate_button", feature: "generate", selector: "#btnGen"}},
    {{key: "result_viewer", feature: "result_display", selector: "#resultViewer"}},
    {{key: "prompt_editor", feature: "prompt_tools", selector: "#promptEdit"}},
    {{key: "prompt_engineering_button", feature: "prompt_tools", selector: '#moduleLauncher .module-btn[data-module="prompt_engineering"]'}},
    {{key: "params_tab", feature: "params", selector: "#tabParams"}},
    {{key: "preset_tab", feature: "presets", selector: "#tabPreset"}},
    {{key: "danbooru_button", feature: "danbooru", selector: '#moduleLauncher .module-btn[data-module="danbooru_browser"]'}},
    {{key: "artist_tab", feature: "artist_thumbnail", selector: "#rightTabArtists"}},
    {{key: "artist_grid", feature: "artist_thumbnail", selector: "#artistThumbGrid"}},
    {{key: "character_tab", feature: "character_reference", selector: "#rightTabCharacters"}},
    {{key: "character_reference_button", feature: "character_reference", selector: '#moduleLauncher .module-btn[data-module="character_reference"]'}},
    {{key: "img2img_open_function_surface", feature: "img2img", selector: "#modulePopup"}},
    {{key: "vibe_button", feature: "vibe_transfer_storage", selector: '#moduleLauncher .module-btn[data-module="vibe_transfer"]'}},
    {{key: "automation_button", feature: "automation", selector: '#moduleLauncher .module-btn[data-module="automation"]'}},
    {{key: "enhance_button", feature: "enhance", selector: "#resultEnhanceBtn"}},
    {{key: "enhance_settings_button", feature: "enhance", selector: "#resultEnhanceSettingsBtn"}},
    {{key: "setup_launcher", feature: "setup_api_settings", selector: "#setupLauncher"}},
    {{key: "history_panel", feature: "history", selector: "#viewerPanel"}},
    {{key: "save_toggle", feature: "save_output", selector: "#statsSave"}},
  ];
  for (const check of domChecks) {{
    const present = !!document.querySelector(check.selector);
    result.domChecks.push({{...check, present, ok: present}});
  }}

  let socket = null;
  try {{
    socket = typeof ws !== "undefined" ? ws : null;
  }} catch (_) {{
    socket = null;
  }}
  result.websocket = {{
    activeSocketFound: !!socket,
    activeSocketOpen: !!(socket && typeof WebSocket === "function" && socket.readyState === WebSocket.OPEN),
  }};
  result.functions = {{
    send: typeof send === "function",
    requestGenerate: typeof requestGenerate === "function",
    requestResultEnhance: typeof requestResultEnhance === "function",
    setModuleParam: typeof setModuleParam === "function",
    openModule: typeof openModule === "function",
    img2imgGenerate: typeof img2imgGenerate === "function",
    switchRightTab: typeof switchRightTab === "function",
    openApiPopup: typeof openApiPopup === "function",
  }};

  function routeOk(key) {{
    return result.routeChecks.some(item => item.key === key && item.ok);
  }}
  function domOk(key) {{
    return result.domChecks.some(item => item.key === key && item.ok);
  }}
  function markFeature(id, requirements) {{
    const feature = result.features[id];
    const missing = [];
    const evidence = [];
    for (const req of requirements) {{
      if (req.ok) evidence.push(req.name);
      else missing.push(req.name);
    }}
    feature.ok = missing.length === 0;
    feature.evidence = evidence;
    feature.missing = missing;
  }}

  markFeature("random_prompt", [
    {{name: "dom.random_button", ok: domOk("random_button")}},
    {{name: "function.send", ok: result.functions.send}},
    {{name: "websocket.active", ok: result.websocket.activeSocketOpen}},
  ]);
  markFeature("generate", [
    {{name: "dom.generate_button", ok: domOk("generate_button")}},
    {{name: "function.requestGenerate", ok: result.functions.requestGenerate}},
    {{name: "route.queue_state", ok: routeOk("queue_state")}},
    {{name: "websocket.active", ok: result.websocket.activeSocketOpen}},
  ]);
  markFeature("result_display", [
    {{name: "dom.result_viewer", ok: domOk("result_viewer")}},
    {{name: "route.latest_image", ok: routeOk("latest_image")}},
    {{name: "route.result_metadata", ok: routeOk("result_metadata")}},
  ]);
  markFeature("prompt_tools", [
    {{name: "dom.prompt_editor", ok: domOk("prompt_editor")}},
    {{name: "dom.prompt_engineering_button", ok: domOk("prompt_engineering_button")}},
    {{name: "route.prompt_highlight_index", ok: routeOk("prompt_highlight_index")}},
    {{name: "route.tag_lookup", ok: routeOk("tag_lookup")}},
  ]);
  markFeature("params", [
    {{name: "dom.params_tab", ok: domOk("params_tab")}},
    {{name: "route.resolutions", ok: routeOk("resolutions")}},
  ]);
  markFeature("presets", [
    {{name: "dom.preset_tab", ok: domOk("preset_tab")}},
    {{name: "route.event_preset_status", ok: routeOk("event_preset_status")}},
    {{name: "route.event_preset_bootstrap", ok: routeOk("event_preset_bootstrap")}},
    {{name: "route.clothes_preset_status", ok: routeOk("clothes_preset_status")}},
    {{name: "route.expression_preset_status", ok: routeOk("expression_preset_status")}},
  ]);
  markFeature("danbooru", [
    {{name: "dom.danbooru_button", ok: domOk("danbooru_button")}},
    {{name: "route.danbooru_browser_open", ok: routeOk("danbooru_browser_open")}},
  ]);
  markFeature("artist_thumbnail", [
    {{name: "dom.artist_tab", ok: domOk("artist_tab")}},
    {{name: "dom.artist_grid", ok: domOk("artist_grid")}},
    {{name: "route.artist_thumb_state", ok: routeOk("artist_thumb_state")}},
  ]);
  markFeature("img2img", [
    {{name: "function.openModule", ok: result.functions.openModule}},
    {{name: "function.img2imgGenerate", ok: result.functions.img2imgGenerate}},
    {{name: "route.image_action_img2img_empty", ok: routeOk("image_action_img2img_empty")}},
  ]);
  markFeature("vibe_transfer_storage", [
    {{name: "dom.vibe_button", ok: domOk("vibe_button")}},
    {{name: "function.setModuleParam", ok: result.functions.setModuleParam}},
    {{name: "route.image_action_vibe_empty", ok: routeOk("image_action_vibe_empty")}},
  ]);
  markFeature("character_reference", [
    {{name: "dom.character_tab", ok: domOk("character_tab")}},
    {{name: "dom.character_reference_button", ok: domOk("character_reference_button")}},
    {{name: "route.character_viewer_state", ok: routeOk("character_viewer_state")}},
  ]);
  markFeature("automation", [
    {{name: "dom.automation_button", ok: domOk("automation_button")}},
    {{name: "function.setModuleParam", ok: result.functions.setModuleParam}},
    {{name: "websocket.active", ok: result.websocket.activeSocketOpen}},
  ]);
  markFeature("enhance", [
    {{name: "dom.enhance_button", ok: domOk("enhance_button")}},
    {{name: "dom.enhance_settings_button", ok: domOk("enhance_settings_button")}},
    {{name: "function.requestResultEnhance", ok: result.functions.requestResultEnhance}},
    {{name: "websocket.active", ok: result.websocket.activeSocketOpen}},
  ]);
  markFeature("setup_api_settings", [
    {{name: "dom.setup_launcher", ok: domOk("setup_launcher")}},
    {{name: "function.openApiPopup", ok: result.functions.openApiPopup}},
    {{name: "route.status", ok: routeOk("status")}},
    {{name: "route.runtime_capabilities", ok: routeOk("runtime_capabilities")}},
  ]);
  markFeature("history", [
    {{name: "dom.history_panel", ok: domOk("history_panel")}},
    {{name: "route.history_list", ok: routeOk("history_list")}},
    {{name: "route.viewer_list", ok: routeOk("viewer_list")}},
  ]);
  markFeature("save_output", [
    {{name: "dom.save_toggle", ok: domOk("save_toggle")}},
    {{name: "route.unsaved_download", ok: routeOk("unsaved_download")}},
    {{name: "route.result_save_empty", ok: routeOk("result_save_empty")}},
  ]);

  result.observedFeatureCount = Object.values(result.features).filter(feature => feature.ok).length;
  result.allRequiredFeaturesObserved = result.observedFeatureCount === result.requiredFeatureCount;
  result.uiSurface = {{
    moduleButtons: document.querySelectorAll("#moduleLauncher .module-btn[data-module]").length,
    rightTabs: document.querySelectorAll("[data-right-tab]").length,
    fileInputs: document.querySelectorAll('input[type="file"]').length,
  }};
  return result;
}})()
""") or {}


def _collect_performance_metrics(client: CdpClient) -> dict[str, Any]:
    return client.evaluate("""
(() => {
  /* __naia_cdp_performance_probe */
  const nav = performance.getEntriesByType("navigation")[0] || {};
  const paints = Object.fromEntries(
    performance.getEntriesByType("paint").map(entry => [entry.name, entry.startTime])
  );
  const firstPaint = Number(paints["first-paint"] || 0);
  const firstContentfulPaint = Number(paints["first-contentful-paint"] || 0);
  const loadEventEnd = Number(nav.loadEventEnd || 0);
  const domContentLoaded = Number(nav.domContentLoadedEventEnd || 0);
  const firstPaintProxy = firstContentfulPaint || firstPaint || loadEventEnd || domContentLoaded || null;
  return {
    timeOrigin: Math.round(performance.timeOrigin || 0),
    domContentLoadedMs: domContentLoaded ? Math.round(domContentLoaded * 1000) / 1000 : null,
    loadEventEndMs: loadEventEnd ? Math.round(loadEventEnd * 1000) / 1000 : null,
    firstPaintMs: firstPaint ? Math.round(firstPaint * 1000) / 1000 : null,
    firstContentfulPaintMs: firstContentfulPaint
      ? Math.round(firstContentfulPaint * 1000) / 1000
      : null,
    firstPaintProxyMs: firstPaintProxy ? Math.round(firstPaintProxy * 1000) / 1000 : null,
    firstPaintProxySource: firstContentfulPaint
      ? "first-contentful-paint"
      : (firstPaint ? "first-paint" : (loadEventEnd ? "loadEventEnd" : (domContentLoaded ? "domContentLoadedEventEnd" : ""))),
    firstPaintReady: !!firstPaintProxy,
  };
})()
""") or {}


def _measure_random_prompt_roundtrip(client: CdpClient, timeout: float) -> dict[str, Any]:
    timeout_ms = max(1000, int(timeout * 1000))
    return client.evaluate(f"""
(async () => {{
  /* __naia_cdp_random_prompt_roundtrip_probe */
  const result = {{
    available: false,
    activeSocketOpen: false,
    promptUpdated: false,
    latencyMs: null,
    promptLength: 0,
    reason: "",
  }};
  let socket = null;
  try {{
    socket = typeof ws !== "undefined" ? ws : null;
  }} catch (_) {{
    socket = null;
  }}
  result.available = typeof send === "function" && !!document.getElementById("promptEdit");
  result.activeSocketOpen = !!(socket && typeof WebSocket === "function" && socket.readyState === WebSocket.OPEN);
  if (!result.available) {{
    result.reason = "send function or prompt editor unavailable";
    return result;
  }}
  if (!result.activeSocketOpen) {{
    result.reason = "active websocket is not open";
    return result;
  }}
  const prompt = document.getElementById("promptEdit");
  const sentinel = `__naia_cdp_random_${{Math.round(performance.now())}}__`;
  prompt.value = sentinel;
  prompt.dispatchEvent(new Event("input", {{bubbles: true}}));
  await new Promise(resolve => setTimeout(resolve, 50));
  const started = performance.now();
  try {{
    send("random");
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
      break;
    }}
  }}
  if (!result.promptUpdated && !result.reason) {{
    result.reason = "timed out waiting for prompt update";
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


def _verify_install_manager_surface(client: CdpClient) -> dict[str, Any]:
    return client.evaluate("""
(async () => {
  /* __naia_cdp_install_manager_probe */
  const result = {
    available: false,
    dataRootInitialized: false,
    tagArchiveReady: false,
    tagArchiveDownloadable: false,
    tagArchiveFileCount: 0,
    tagArchiveExpectedCount: 0,
    reason: "",
  };
  try {
    const response = await fetch("/api/install-manager", {cache: "no-store"});
    const payload = await response.json().catch(() => ({}));
    result.available = response.ok && payload && payload.ok !== false;
    result.dataRootInitialized = !!(payload.runtime && payload.runtime.data_initialized);
    result.tagArchiveReady = !!(payload.tag_archive && payload.tag_archive.ready);
    result.tagArchiveDownloadable = !!(payload.tag_archive && payload.tag_archive.downloadable);
    result.tagArchiveFileCount = Number(payload.tag_archive && payload.tag_archive.file_count || 0);
    result.tagArchiveExpectedCount = Number(payload.tag_archive && payload.tag_archive.expected_count || 0);
    if (!result.available) result.reason = payload.error || `HTTP ${response.status}`;
    return result;
  } catch (error) {
    result.reason = error && error.message ? error.message : String(error);
    return result;
  }
})()
""") or {}


def _restart_backend_and_wait(client: CdpClient, timeout: float) -> dict[str, Any]:
    restart_result: dict[str, Any] | None = None
    try:
        restart_result = client.evaluate("""
(async () => {
  if (!window.naiaShell) {
    return { ok: false, reason: "naiaShell missing" };
  }
  const state = await window.naiaShell.restartBackend();
  return {
    ok: true,
    backendState: state && state.backendState,
    backendUrl: state && state.backendUrl,
    runtimeDataRoot: state && state.runtimeDataRoot,
  };
})()
""")
    except RuntimeError as exc:
        if "navigated or closed" not in str(exc):
            raise
        restart_result = {
            "ok": True,
            "reason": "target navigated or closed during backend restart",
        }
        time.sleep(0.5)
        client.reconnect()
    if not restart_result or not restart_result.get("ok"):
        raise RuntimeError(f"backend restart failed: {restart_result}")
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            state = _wait_for_shell_state(client, max(0.5, min(5.0, deadline - time.monotonic())))
            break
        except RuntimeError as exc:
            if "navigated or closed" not in str(exc):
                raise
            last_error = exc
            time.sleep(0.5)
            client.reconnect()
    else:
        if last_error is not None:
            raise last_error
        raise TimeoutError("backend restart did not produce a ready shell state")
    return {
        "restartResult": restart_result,
        "readyAfterRestart": state.get("backendState") == "ready",
        "backendUrl": state.get("backendUrl"),
    }


def _collect_runtime_checks(
    client: CdpClient,
    ready_state: dict[str, Any],
    *,
    timeout: float,
    skip_download: bool,
    skip_restart: bool,
) -> dict[str, Any]:
    def run_check(name: str, callback):
        try:
            checks[name] = callback()
        except Exception as exc:
            checks[name] = {
                "ok": False,
                "reason": f"{type(exc).__name__}: {exc}",
            }
        return checks[name]

    checks: dict[str, Any] = {
        "window": {
            "innerWidth": ready_state.get("innerWidth"),
            "innerHeight": ready_state.get("innerHeight"),
            "meetsMinimum": (ready_state.get("innerWidth") or 0) >= 960
            and (ready_state.get("innerHeight") or 0) >= 640,
        },
        "browserApis": {
            "websocket": bool(ready_state.get("hasWebSocket")),
            "clipboard": bool(ready_state.get("hasClipboard")),
            "fileInputPresent": bool(ready_state.get("hasFileInput")),
        },
        "resultImageInputSurface": None,
        "filePicker": _verify_file_picker_surface(client),
        "clipboard": _verify_clipboard_and_paste_surface(client),
        "dragDrop": _verify_drag_drop_surface(client),
        "performance": None,
        "storage": None,
        "actionDispatch": None,
        "installManager": None,
        "randomPromptRoundTrip": None,
        "websocketReconnect": None,
        "featureWorkflows": None,
        "download": None,
        "backendRestart": None,
    }
    input_surface = run_check("resultImageInputSurface", lambda: _wait_for_result_image_input_surface(client, timeout))
    if input_surface.get("fileInputPresent"):
        checks["browserApis"]["fileInputPresent"] = True
        checks["filePicker"] = _verify_file_picker_surface(client)
        checks["clipboard"] = _verify_clipboard_and_paste_surface(client)
        checks["dragDrop"] = _verify_drag_drop_surface(client)
    run_check("performance", lambda: _collect_performance_metrics(client))
    run_check("storage", lambda: _verify_storage_persistence(client, timeout))
    run_check("shellStateAfterReload", lambda: _wait_for_shell_state(client, timeout))
    run_check("activeWebsocketBeforeActions", lambda: _wait_for_active_websocket(client, timeout))
    run_check("actionDispatch", lambda: _measure_action_dispatch(client))
    run_check("installManager", lambda: _verify_install_manager_surface(client))
    run_check("randomPromptRoundTrip", lambda: _measure_random_prompt_roundtrip(client, timeout))
    run_check("websocketReconnect", lambda: _verify_websocket_reconnect(client, timeout))
    run_check("activeWebsocketAfterReconnect", lambda: _wait_for_active_websocket(client, timeout))
    run_check("featureWorkflows", lambda: _verify_feature_workflows_surface(client, timeout))
    runtime_data_root = str(ready_state.get("runtimeDataRoot") or "")
    if runtime_data_root and not skip_download:
        run_check("download", lambda: _trigger_synthetic_download(client, runtime_data_root, timeout))
    if not skip_restart:
        run_check("backendRestart", lambda: _restart_backend_and_wait(client, timeout))
    return checks


def _runtime_check_violations(checks: dict[str, Any]) -> list[dict[str, str]]:
    expected_true = [
        ("checks.window.meetsMinimum", checks.get("window", {}).get("meetsMinimum")),
        ("checks.browserApis.websocket", checks.get("browserApis", {}).get("websocket")),
        ("checks.browserApis.clipboard", checks.get("browserApis", {}).get("clipboard")),
        ("checks.browserApis.fileInputPresent", checks.get("browserApis", {}).get("fileInputPresent")),
        ("checks.filePicker.present", checks.get("filePicker", {}).get("present")),
        ("checks.clipboard.clipboardReadApi", checks.get("clipboard", {}).get("clipboardReadApi")),
        (
            "checks.clipboard.syntheticImagePastePrevented",
            checks.get("clipboard", {}).get("syntheticImagePastePrevented"),
        ),
        ("checks.dragDrop.targetPresent", checks.get("dragDrop", {}).get("targetPresent")),
        ("checks.dragDrop.dropPrevented", checks.get("dragDrop", {}).get("dropPrevented")),
        (
            "checks.storage.localStoragePersistsAfterReload",
            checks.get("storage", {}).get("localStoragePersistsAfterReload"),
        ),
        (
            "checks.storage.sessionStoragePersistsAfterReload",
            checks.get("storage", {}).get("sessionStoragePersistsAfterReload"),
        ),
        (
            "checks.performance.firstPaintReady",
            checks.get("performance", {}).get("firstPaintReady"),
        ),
        (
            "checks.actionDispatch.generate.dispatched",
            checks.get("actionDispatch", {}).get("generate", {}).get("dispatched"),
        ),
        (
            "checks.actionDispatch.random.dispatched",
            checks.get("actionDispatch", {}).get("random", {}).get("dispatched"),
        ),
        (
            "checks.installManager.available",
            checks.get("installManager", {}).get("available"),
        ),
        (
            "checks.installManager.dataRootInitialized",
            checks.get("installManager", {}).get("dataRootInitialized"),
        ),
        (
            "checks.installManager.tagArchiveDownloadable",
            checks.get("installManager", {}).get("tagArchiveDownloadable"),
        ),
        (
            "checks.websocketReconnect.reconnected",
            checks.get("websocketReconnect", {}).get("reconnected"),
        ),
        (
            "checks.featureWorkflows.allRequiredFeaturesObserved",
            checks.get("featureWorkflows", {}).get("allRequiredFeaturesObserved"),
        ),
    ]
    download = checks.get("download")
    if isinstance(download, dict):
        expected_true.append(("checks.download.under_runtime_downloads", download.get("under_runtime_downloads")))
    backend_restart = checks.get("backendRestart")
    if isinstance(backend_restart, dict):
        expected_true.append(("checks.backendRestart.readyAfterRestart", backend_restart.get("readyAfterRestart")))

    install_manager = checks.get("installManager")
    random_prompt = checks.get("randomPromptRoundTrip")
    if isinstance(install_manager, dict) and install_manager.get("tagArchiveReady"):
        expected_true.append((
            "checks.randomPromptRoundTrip.promptUpdated",
            random_prompt.get("promptUpdated") if isinstance(random_prompt, dict) else False,
        ))

    return [
        {"path": path, "reason": "expected truthy Electron runtime smoke evidence"}
        for path, value in expected_true
        if not value
    ] + [
        {"path": f"checks.{name}", "reason": str(payload.get("reason"))}
        for name, payload in checks.items()
        if isinstance(payload, dict) and payload.get("ok") is False and payload.get("reason")
    ]


def _terminate(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=8)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def smoke_electron_cdp(
    *,
    mode: str,
    electron_root: str | Path = DEFAULT_ELECTRON_ROOT,
    package_root: str | Path = DEFAULT_PACKAGE_ROOT,
    electron_command: str | None = None,
    exe_name: str = "NAIA.exe",
    debug_port: int = DEFAULT_DEBUG_PORT,
    backend_port: int = DEFAULT_BACKEND_PORT,
    timeout: float = 60.0,
    user_data: str | Path | None = None,
    skip_download: bool = False,
    skip_restart: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    temp_user_data: tempfile.TemporaryDirectory[str] | None = None
    if user_data is None:
        temp_user_data = tempfile.TemporaryDirectory(prefix="naia-electron-cdp-")
        user_data = temp_user_data.name

    config = build_launch_config(
        mode=mode,
        electron_root=electron_root,
        package_root=package_root,
        electron_command=electron_command,
        exe_name=exe_name,
        debug_port=debug_port,
        backend_port=backend_port,
        user_data=user_data,
    )
    try:
        if dry_run or not config.get("ok"):
            return {
                "ok": bool(config.get("ok")),
                "dry_run": dry_run,
                "launch": config,
                "violations": [] if dry_run and config.get("ok") else [{"path": "electron", "reason": config.get("reason", "")}] if not config.get("ok") else [],
            }

        timings: dict[str, float] = {}
        started = time.monotonic()
        env = os.environ.copy()
        env.update(config["env"])
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(
            [config["command"], *config["args"]],
            cwd=config["cwd"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        client: CdpClient | None = None
        try:
            target_started = time.monotonic()
            target = _wait_for_target(debug_port, timeout)
            timings["cdp_target_s"] = round(time.monotonic() - target_started, 3)
            client = CdpClient(target["webSocketDebuggerUrl"], timeout=timeout, debug_port=debug_port)
            ready_started = time.monotonic()
            state = _wait_for_shell_state(client, timeout)
            timings["shell_ready_s"] = round(time.monotonic() - ready_started, 3)
            checks_started = time.monotonic()
            try:
                checks = _collect_runtime_checks(
                    client,
                    state,
                    timeout=timeout,
                    skip_download=skip_download,
                    skip_restart=skip_restart,
                )
                timings["runtime_checks_s"] = round(time.monotonic() - checks_started, 3)
                timings["total_s"] = round(time.monotonic() - started, 3)
                violations = _runtime_check_violations(checks)
                return {
                    "ok": not violations,
                    "dry_run": False,
                    "launch": config,
                    "target": {
                        "id": target.get("id"),
                        "type": target.get("type"),
                        "url": target.get("url"),
                        "title": target.get("title"),
                    },
                    "timings": timings,
                    "state": state,
                    "checks": checks,
                    "violations": violations,
                }
            except Exception as exc:
                timings["runtime_checks_s"] = round(time.monotonic() - checks_started, 3)
                timings["total_s"] = round(time.monotonic() - started, 3)
                return {
                    "ok": False,
                    "dry_run": False,
                    "launch": config,
                    "target": {
                        "id": target.get("id"),
                        "type": target.get("type"),
                        "url": target.get("url"),
                        "title": target.get("title"),
                    },
                    "timings": timings,
                    "state": state,
                    "checks": {},
                    "violations": [{"path": "electron_cdp_runtime", "reason": f"{type(exc).__name__}: {exc}"}],
                }
        finally:
            if client:
                client.close()
            _terminate(proc)
    finally:
        if temp_user_data:
            temp_user_data.cleanup()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test NAIA Electron shell via CDP.")
    parser.add_argument("--mode", choices=("source", "packaged"), required=True)
    parser.add_argument("--electron-root", default=str(DEFAULT_ELECTRON_ROOT))
    parser.add_argument("--package-root", default=str(DEFAULT_PACKAGE_ROOT))
    parser.add_argument("--electron-command", default=None)
    parser.add_argument("--exe-name", default="NAIA.exe")
    parser.add_argument("--debug-port", type=int, default=DEFAULT_DEBUG_PORT)
    parser.add_argument("--backend-port", type=int, default=DEFAULT_BACKEND_PORT)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--user-data", default=None)
    parser.add_argument("--skip-download", action="store_true", help="Do not trigger a synthetic browser download.")
    parser.add_argument("--skip-restart", action="store_true", help="Do not restart the backend through the shell API.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    payload = smoke_electron_cdp(
        mode=args.mode,
        electron_root=args.electron_root,
        package_root=args.package_root,
        electron_command=args.electron_command,
        exe_name=args.exe_name,
        debug_port=args.debug_port,
        backend_port=args.backend_port,
        timeout=args.timeout,
        user_data=args.user_data,
        skip_download=args.skip_download,
        skip_restart=args.skip_restart,
        dry_run=args.dry_run,
    )
    json.dump(payload, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
