"""Measure the Remote WebSession startup path.

This migration tool measures the supported headless Remote Web path by default.
The old `legacy_desktop/NAIA_cold_v4.py --web-shell` path remains available through
`--entrypoint desktop` for legacy comparison only.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil
import websocket


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_DIR = ROOT / "logs"
DEFAULT_DOC_PATH = ROOT / "refactor_docs" / "round_30_headless_web_baseline.md"
DEFAULT_JSON_PATH = DEFAULT_LOG_DIR / "round30_web_session_baseline.json"
GENERATE_DISPATCH_MARKERS = (
    "🌐 Remote: 생성 트리거됨",
    "🌐 Remote: 생성 요청을 큐에 추가",
    "Headless Remote: generation request queued",
)
RANDOM_COMPLETE_MARKERS = (
    "🌐 Remote: core 랜덤 프롬프트 생성됨",
    "🌐 Remote: core search 랜덤 프롬프트 생성됨",
    "🌐 Remote: 랜덤 프롬프트 생성됨",
    "Headless Remote: random prompt generated",
)


@dataclass
class Measurement:
    command: list[str]
    port: int
    cdp_port: int
    started_at: str
    commit: str
    timings: dict[str, float | None] = field(default_factory=dict)
    rss_mb: dict[str, float | None] = field(default_factory=dict)
    checks: dict[str, Any] = field(default_factory=dict)
    dependency_audit: dict[str, Any] = field(default_factory=dict)
    log_paths: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    entrypoint: str = "headless"


class CdpClient:
    def __init__(self, websocket_url: str):
        self.ws = websocket.create_connection(websocket_url, timeout=10)
        self._next_id = 0

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
            "awaitPromise": False,
        })
        remote_result = result.get("result") or {}
        return remote_result.get("value")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def run_git(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        return completed.stdout.strip() or completed.stderr.strip()
    except Exception as exc:
        return f"unavailable: {exc}"


def write_sitecustomize(temp_dir: Path, audit_path: Path) -> None:
    prefixes = [
        "PyQt6",
        "NAIA_cold_v4",
        "legacy_desktop",
        "NAIA_web_headless",
        "core.remote_api_server",
        "core.middle_section_controller",
        "core.main_controller",
        "tabs.image_window",
        "ui.image_window",
        "modules",
        "legacy_desktop.modules",
    ]
    code = f"""
import builtins
import json
import os
import time

_audit_log = {str(audit_path)!r}
_prefixes = tuple({prefixes!r})
_seen = set()
_orig_import = builtins.__import__

def _record_import(name, fromlist):
    candidates = [name]
    if fromlist:
        for item in fromlist:
            if isinstance(item, str) and item != "*":
                candidates.append(name + "." + item)
    for candidate in candidates:
        if not candidate.startswith(_prefixes):
            continue
        if candidate in _seen:
            continue
        _seen.add(candidate)
        try:
            with open(_audit_log, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({{
                    "time": time.time(),
                    "module": candidate,
                    "fromlist": list(fromlist or ()),
                }}, ensure_ascii=False) + "\\n")
        except Exception:
            pass

def _audited_import(name, globals=None, locals=None, fromlist=(), level=0):
    module = _orig_import(name, globals, locals, fromlist, level)
    _record_import(name, fromlist)
    return module

builtins.__import__ = _audited_import
"""
    (temp_dir / "sitecustomize.py").write_text(code, encoding="utf-8")


def url_json(url: str, timeout: float = 2.0) -> Any:
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read()
    return json.loads(data.decode("utf-8"))


def socket_listens(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def wait_for(predicate, timeout: float, interval: float = 0.1):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except Exception as exc:
            last_error = exc
        time.sleep(interval)
    if last_error:
        raise TimeoutError(str(last_error))
    raise TimeoutError("condition timed out")


def wait_for_process_condition(
    proc: subprocess.Popen,
    predicate,
    timeout: float,
    stderr_path: Path,
    interval: float = 0.1,
):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            stderr_tail = "\n".join(read_text(stderr_path).splitlines()[-20:])
            raise RuntimeError(
                f"child process exited with code {proc.returncode} before condition was met\n{stderr_tail}"
            )
        try:
            result = predicate()
            if result:
                return result
        except Exception as exc:
            last_error = exc
        time.sleep(interval)
    if last_error:
        raise TimeoutError(str(last_error))
    raise TimeoutError("condition timed out")


def find_chrome() -> str | None:
    candidates = [
        os.environ.get("CHROME_PATH"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        str(Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def default_python_executable() -> str:
    venv_python = ROOT / "venv" / "Scripts" / "python.exe"
    if venv_python.is_file():
        return str(venv_python)
    return sys.executable


def process_tree(root_pid: int) -> list[psutil.Process]:
    try:
        root = psutil.Process(root_pid)
    except psutil.Error:
        return []
    processes = [root]
    try:
        processes.extend(root.children(recursive=True))
    except psutil.Error:
        pass
    return processes


def rss_mb(root_pid: int) -> float | None:
    total = 0
    found = False
    for proc in process_tree(root_pid):
        try:
            total += proc.memory_info().rss
            found = True
        except psutil.Error:
            continue
    if not found:
        return None
    return round(total / (1024 * 1024), 2)


def stop_process_tree(root_pid: int) -> None:
    processes = process_tree(root_pid)
    children = processes[1:]
    for proc in children:
        try:
            proc.terminate()
        except psutil.Error:
            pass
    if processes:
        try:
            processes[0].terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(processes, timeout=5)
    for proc in alive:
        try:
            proc.kill()
        except psutil.Error:
            pass


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def wait_log_marker(path: Path, markers: tuple[str, ...], start_offset: int, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = read_text(path)
        tail = text[start_offset:]
        for marker in markers:
            if marker in tail:
                return marker
        time.sleep(0.1)
    raise TimeoutError(f"log marker not found: {markers}")


def launch_chrome(chrome_path: str, url: str, cdp_port: int, profile_dir: Path) -> subprocess.Popen:
    args = [
        chrome_path,
        "--headless=new",
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-extensions",
        "--remote-allow-origins=*",
        "--window-size=1100,900",
        url,
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)


def get_page_target(cdp_port: int, url: str) -> dict[str, Any]:
    targets = url_json(f"http://127.0.0.1:{cdp_port}/json/list", timeout=2)
    for target in targets:
        if target.get("type") == "page" and target.get("url", "").startswith(url):
            return target
    for target in targets:
        if target.get("type") == "page":
            return target
    raise RuntimeError("CDP page target not found")


def page_ready_state(client: CdpClient) -> dict[str, Any]:
    expression = """
(() => {
  const text = document.body ? document.body.innerText : '';
  const prompt = document.getElementById('promptEdit');
  const btnRnd = document.getElementById('btnRnd');
  const btnGen = document.getElementById('btnGen');
  return {
    title: document.title,
    readyState: document.readyState,
    bodyChars: text.length,
    hasRandom: !!btnRnd && /Random|랜덤/.test(text),
    hasGenerate: !!btnGen && /Generate|생성/.test(text),
    sendReady: typeof send === 'function',
    wsReadyState: typeof ws !== 'undefined' && ws ? ws.readyState : null,
    promptLength: prompt ? prompt.value.length : null,
    randomDisabled: btnRnd ? !!btnRnd.disabled : null,
    generateDisabled: btnGen ? !!btnGen.disabled : null
  };
})()
"""
    return client.evaluate(expression)


def wait_for_action_idle(client: CdpClient, timeout: float) -> dict[str, Any]:
    """Wait until initial websocket replay/preset restore has settled enough for actions."""
    def ready_state():
        state = page_ready_state(client) or {}
        if (
            state.get("hasRandom")
            and state.get("hasGenerate")
            and state.get("sendReady")
            and state.get("wsReadyState") == 1
        ):
            return state
        return None

    state = wait_for(
        ready_state,
        timeout=timeout,
        interval=0.25,
    )
    quiet_until = time.monotonic() + 1.5
    last_value = client.evaluate("(document.getElementById('promptEdit') || {}).value || ''") or ""
    while time.monotonic() < quiet_until:
        time.sleep(0.25)
        current = client.evaluate("(document.getElementById('promptEdit') || {}).value || ''") or ""
        if current != last_value:
            last_value = current
            quiet_until = time.monotonic() + 1.5
    return state


def force_remote_options_for_measurement(client: CdpClient) -> dict[str, Any]:
    return client.evaluate("""
(() => {
  if (typeof setOption === 'function') {
    setOption('prompt_fixed', false);
    setOption('auto_generate', false);
  }
  if (typeof _collectCurrentParams === 'function' && !window.__naiaMeasureCollectPatched) {
    const originalCollectCurrentParams = _collectCurrentParams;
    window.__naiaMeasureCollectPatched = true;
    _collectCurrentParams = function() {
      const params = originalCollectCurrentParams();
      params.prompt_fixed = false;
      params.auto_generate = false;
      return params;
    };
  }
  for (const [id, value] of [['optPromptFixed', false], ['optAutoGen', false]]) {
    const control = document.getElementById(id);
    if (!control) continue;
    control.dataset.checked = value ? 'true' : 'false';
    control.classList.toggle('is-on', !!value);
    control.setAttribute('aria-pressed', value ? 'true' : 'false');
  }
  const prompt = document.getElementById('promptEdit');
  if (prompt) {
    prompt.value = '';
    if (typeof promptSendTimer !== 'undefined' && promptSendTimer) {
      clearTimeout(promptSendTimer);
      promptSendTimer = null;
    }
    if (typeof _localPromptDirty !== 'undefined') _localPromptDirty = false;
  }
  return {
    promptFixed: document.getElementById('optPromptFixed')?.dataset?.checked || null,
    autoGenerate: document.getElementById('optAutoGen')?.dataset?.checked || null,
    promptLength: prompt ? prompt.value.length : null
  };
})()
""")


def click_and_wait_random(
    client: CdpClient,
    stdout_path: Path,
    timeout: float,
) -> tuple[float, dict[str, Any]]:
    forced = force_remote_options_for_measurement(client)
    client.evaluate("""
(() => {
  window.__naiaMeasureWsMessages = [];
  window.__naiaMeasureErrors = [];
  if (!window.__naiaMeasureErrorPatched) {
    window.__naiaMeasureErrorPatched = true;
    window.addEventListener('error', event => {
      window.__naiaMeasureErrors.push({
        type: 'error',
        message: String(event.message || ''),
        filename: String(event.filename || ''),
        lineno: event.lineno || 0,
        colno: event.colno || 0,
      });
    });
    window.addEventListener('unhandledrejection', event => {
      window.__naiaMeasureErrors.push({
        type: 'unhandledrejection',
        message: String(event.reason?.message || event.reason || ''),
      });
    });
  }
  try {
    if (typeof ws !== 'undefined' && ws && !ws.__naiaMeasurePatched) {
      const original = ws.onmessage;
      ws.__naiaMeasurePatched = true;
      ws.onmessage = function(event) {
        if (typeof event.data === 'string') {
          window.__naiaMeasureWsMessages.push(event.data.slice(0, 500));
          if (window.__naiaMeasureWsMessages.length > 20) {
            window.__naiaMeasureWsMessages.shift();
          }
        }
        return original ? original.call(this, event) : undefined;
      };
    }
  } catch (error) {
    window.__naiaMeasureErrors.push({type: 'patch', message: String(error?.message || error)});
  }
  return true;
})()
""")
    before = page_ready_state(client)
    before_value = client.evaluate("(document.getElementById('promptEdit') || {}).value || ''") or ""
    log_offset = len(read_text(stdout_path))
    start = time.monotonic()
    click_result = client.evaluate("""
(() => {
  const btn = document.getElementById('btnRnd');
  if (!btn) return {ok: false, reason: 'btnRnd missing'};
  if (btn.disabled) return {ok: false, reason: 'btnRnd disabled'};
  btn.click();
  return {ok: true};
})()
""")
    if not click_result or not click_result.get("ok"):
        raise RuntimeError(f"Random click failed: {click_result}")
    marker = wait_log_marker(stdout_path, RANDOM_COMPLETE_MARKERS, log_offset, timeout=timeout)

    def changed():
        state = client.evaluate("""
(() => {
  const prompt = document.getElementById('promptEdit');
  const btn = document.getElementById('btnRnd');
  return {
    value: prompt ? prompt.value : '',
    length: prompt ? prompt.value.length : 0,
    randomDisabled: btn ? !!btn.disabled : null
  };
})()
""")
        if state and state.get("length", 0) > 0:
            return state
        return None

    try:
        state = wait_for(changed, timeout=timeout, interval=0.2)
    except TimeoutError as exc:
        diagnostics = client.evaluate("""
(() => {
  const prompt = document.getElementById('promptEdit');
  const btn = document.getElementById('btnRnd');
  return {
    promptLength: prompt ? prompt.value.length : null,
    promptPreview: prompt ? prompt.value.slice(0, 120) : null,
    randomDisabled: btn ? !!btn.disabled : null,
    awaitingMyRandom: typeof awaitingMyRandom !== 'undefined' ? awaitingMyRandom : null,
    pendingRandomRequestId: typeof pendingRandomRequestId !== 'undefined' ? pendingRandomRequestId : null,
    wsReadyState: typeof ws !== 'undefined' && ws ? ws.readyState : null,
    messages: window.__naiaMeasureWsMessages || [],
    errors: window.__naiaMeasureErrors || [],
  };
})()
""")
        raise TimeoutError(f"{exc}; diagnostics={diagnostics}") from exc
    return round(time.monotonic() - start, 3), {
        "forced_options": forced,
        "before": before,
        "after": state,
        "random_log_marker": marker,
    }


def click_generate(client: CdpClient) -> None:
    wait_for(
        lambda: client.evaluate("""
(() => {
  const btn = document.getElementById('btnGen');
  return !!btn && !btn.disabled;
})()
"""),
        timeout=30.0,
        interval=0.2,
    )
    result = client.evaluate("""
(() => {
  const btn = document.getElementById('btnGen');
  if (!btn) return {ok: false, reason: 'btnGen missing'};
  if (btn.disabled) return {ok: false, reason: 'btnGen disabled'};
  btn.click();
  return {ok: true};
})()
""")
    if not result or not result.get("ok"):
        raise RuntimeError(f"Generate click failed: {result}")


def parse_import_audit(path: Path, stdout_text: str) -> dict[str, Any]:
    imports: list[str] = []
    for line in read_text(path).splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        module = payload.get("module")
        if isinstance(module, str):
            imports.append(module)
    unique_imports = sorted(set(imports))
    middle_module_imports = [
        name
        for name in unique_imports
        if name.startswith("modules") or name.startswith("legacy_desktop.modules")
    ]
    return {
        "pyqt6_imported": any(name == "PyQt6" or name.startswith("PyQt6.") for name in unique_imports),
        "legacy_desktop_imported": any(
            name == "legacy_desktop" or name.startswith("legacy_desktop.") for name in unique_imports
        ),
        "remote_api_server_imported": any(
            name.startswith("core.remote_api_server")
            or name.startswith("legacy_desktop.core.remote_api_server")
            for name in unique_imports
        ),
        "middle_section_controller_imported": any(
            name.startswith("core.middle_section_controller")
            or name.startswith("legacy_desktop.core.middle_section_controller")
            for name in unique_imports
        ),
        "middle_module_imports_count": len(middle_module_imports),
        "middle_module_imports_sample": middle_module_imports[:40],
        "modern_main_window_constructed": "🖥️ 동적 창 크기 설정 완료" in stdout_text,
        "image_window_constructed": (
            "생성 결과 탭 초기화 완료" in stdout_text
            or "ImageWindow의 save_to_remote_event_requested" in stdout_text
        ),
        "middle_section_controller_constructed": "🔍 모듈 로드 시작:" in stdout_text,
        "remote_bridge_constructed": "RemoteBridge." in stdout_text,
        "tracked_imports_count": len(unique_imports),
        "tracked_imports_sample": unique_imports[:80],
    }


def write_json(path: Path, measurement: Measurement) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(measurement.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")


def markdown_table(mapping: dict[str, Any], headers: tuple[str, str]) -> str:
    lines = [f"| {headers[0]} | {headers[1]} |", "| --- | --- |"]
    for key, value in mapping.items():
        lines.append(f"| `{key}` | {value} |")
    return "\n".join(lines)


def write_summary(path: Path, measurement: Measurement) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    command = " ".join(measurement.command)
    dep = measurement.dependency_audit
    content = f"""# Web Session Measurement ({measurement.entrypoint})

Generated: {measurement.started_at}

Commit: `{measurement.commit}`

Command:

```powershell
{command}
```

## Timings

{markdown_table(measurement.timings, ("Metric", "Seconds"))}

## Memory

{markdown_table(measurement.rss_mb, ("Checkpoint", "RSS MB"))}

## Runtime Dependency Audit

{markdown_table({
    "pyqt6_imported": dep.get("pyqt6_imported"),
    "legacy_desktop_imported": dep.get("legacy_desktop_imported"),
    "remote_api_server_imported": dep.get("remote_api_server_imported"),
    "middle_section_controller_imported": dep.get("middle_section_controller_imported"),
    "modern_main_window_constructed": dep.get("modern_main_window_constructed"),
    "image_window_constructed": dep.get("image_window_constructed"),
    "middle_section_controller_constructed": dep.get("middle_section_controller_constructed"),
    "remote_bridge_constructed": dep.get("remote_bridge_constructed"),
    "middle_module_imports_count": dep.get("middle_module_imports_count"),
    "tracked_imports_count": dep.get("tracked_imports_count"),
}, ("Signal", "Value"))}

Middle module import sample:

```text
{chr(10).join(dep.get("middle_module_imports_sample") or [])}
```

## Checks

```json
{json.dumps(measurement.checks, ensure_ascii=False, indent=2)}
```

## Logs

{markdown_table(measurement.log_paths, ("Log", "Path"))}

## Interpretation

For the supported headless entrypoint, PyQt, `legacy_desktop`, `RemoteBridge`,
`ModernMainWindow`, `ImageWindow`, and Desktop controllers should be absent
while Remote Web startup, Random, and Generate dispatch remain functional.
The optional `--entrypoint desktop` comparison path is legacy-only.
"""
    if measurement.errors:
        content += "\n## Errors\n\n" + "\n".join(f"- {error}" for error in measurement.errors) + "\n"
    path.write_text(content, encoding="utf-8")


def measure(args: argparse.Namespace) -> Measurement:
    DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    started_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stdout_path = DEFAULT_LOG_DIR / f"round30_web_session_{args.port}_{started_stamp}.out.log"
    stderr_path = DEFAULT_LOG_DIR / f"round30_web_session_{args.port}_{started_stamp}.err.log"
    import_audit_path = DEFAULT_LOG_DIR / f"round30_import_audit_{args.port}_{started_stamp}.jsonl"
    temp_import_dir = Path(tempfile.mkdtemp(prefix="naia-round30-import-"))
    chrome_profile_dir = Path(tempfile.mkdtemp(prefix="naia-round30-cdp-"))
    write_sitecustomize(temp_import_dir, import_audit_path)

    python_exe = args.python or default_python_executable()
    if args.entrypoint == "headless":
        command = [
            python_exe,
            "-u",
            "NAIA_web_headless.py",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.port),
        ]
    else:
        command = [
            python_exe,
            "-u",
            "legacy_desktop/NAIA_cold_v4.py",
            "--web-shell",
            "--web-shell-port",
            str(args.port),
        ]
    measurement = Measurement(
        command=[
            "python",
            "tools/measure_web_session_startup.py",
            "--entrypoint",
            args.entrypoint,
            "--port",
            str(args.port),
            "--cdp-port",
            str(args.cdp_port),
            *(["--include-generate"] if args.include_generate else []),
        ],
        port=args.port,
        cdp_port=args.cdp_port,
        started_at=now_iso(),
        commit=run_git(["rev-parse", "--short", "HEAD"]),
        log_paths={
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
            "import_audit": str(import_audit_path),
        },
        entrypoint=args.entrypoint,
    )

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    if args.entrypoint == "headless" and args.include_generate:
        env["NAIA_HEADLESS_DISABLE_GENERATION_EXECUTION"] = "1"
    env["PYTHONPATH"] = str(temp_import_dir) + os.pathsep + env.get("PYTHONPATH", "")

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    chrome_proc: subprocess.Popen | None = None
    cdp_client: CdpClient | None = None
    proc: subprocess.Popen | None = None
    start = time.monotonic()

    try:
        with stdout_path.open("w", encoding="utf-8", errors="replace") as stdout, stderr_path.open(
            "w", encoding="utf-8", errors="replace"
        ) as stderr:
            proc = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=stdout,
                stderr=stderr,
                env=env,
                creationflags=creationflags,
            )

            wait_for_process_condition(
                proc,
                lambda: socket_listens("127.0.0.1", args.port),
                timeout=args.startup_timeout,
                stderr_path=stderr_path,
            )
            measurement.timings["fastapi_listen"] = round(time.monotonic() - start, 3)
            measurement.rss_mb["after_listen"] = rss_mb(proc.pid)

            status_payload = wait_for(
                lambda: url_json(f"http://127.0.0.1:{args.port}/api/status", timeout=2),
                timeout=args.startup_timeout,
                interval=0.25,
            )
            measurement.timings["api_status_200"] = round(time.monotonic() - start, 3)
            measurement.checks["api_status"] = status_payload
            measurement.rss_mb["after_status"] = rss_mb(proc.pid)

            chrome_path = args.chrome or find_chrome()
            if not chrome_path:
                raise RuntimeError("Chrome or Edge executable not found")
            url = f"http://127.0.0.1:{args.port}/"
            chrome_proc = launch_chrome(chrome_path, url, args.cdp_port, chrome_profile_dir)
            target = wait_for(lambda: get_page_target(args.cdp_port, url), timeout=args.browser_timeout, interval=0.25)
            cdp_client = CdpClient(target["webSocketDebuggerUrl"])
            cdp_client.send("Runtime.enable")

            def page_ready():
                state = page_ready_state(cdp_client)
                if (
                    state
                    and state.get("title") == "NAIA Remote"
                    and state.get("readyState") in {"interactive", "complete"}
                    and state.get("hasRandom")
                    and state.get("hasGenerate")
                ):
                    return state
                return None

            page_state = wait_for(page_ready, timeout=args.browser_timeout, interval=0.2)
            measurement.timings["remote_web_first_paint"] = round(time.monotonic() - start, 3)
            measurement.checks["remote_web_first_paint"] = page_state
            measurement.rss_mb["after_first_paint"] = rss_mb(proc.pid)

            action_ready_state = wait_for_action_idle(cdp_client, timeout=args.browser_timeout)
            measurement.checks["remote_web_action_ready"] = action_ready_state
            measurement.rss_mb["after_action_ready"] = rss_mb(proc.pid)

            random_latency, random_state = click_and_wait_random(
                cdp_client,
                stdout_path,
                timeout=args.action_timeout,
            )
            measurement.timings["random_click_to_prompt_update"] = random_latency
            measurement.checks["random_prompt"] = random_state
            measurement.rss_mb["after_random"] = rss_mb(proc.pid)

            if args.include_generate:
                stdout.flush()
                generate_log_offset = len(read_text(stdout_path))
                generate_start = time.monotonic()
                click_generate(cdp_client)
                marker = wait_log_marker(
                    stdout_path,
                    GENERATE_DISPATCH_MARKERS,
                    generate_log_offset,
                    timeout=args.action_timeout,
                )
                measurement.timings["generate_click_to_dispatch"] = round(time.monotonic() - generate_start, 3)
                measurement.checks["generate_dispatch_marker"] = marker
                measurement.rss_mb["after_generate_dispatch"] = rss_mb(proc.pid)
            else:
                measurement.timings["generate_click_to_dispatch"] = None
                measurement.checks["generate_dispatch_marker"] = "skipped"

            stdout.flush()
            stderr.flush()
    finally:
        if cdp_client:
            cdp_client.close()
        if chrome_proc and chrome_proc.poll() is None:
            stop_process_tree(chrome_proc.pid)
        if proc and proc.poll() is None:
            stop_process_tree(proc.pid)
        shutil.rmtree(temp_import_dir, ignore_errors=True)
        shutil.rmtree(chrome_profile_dir, ignore_errors=True)

    stdout_text = read_text(stdout_path)
    measurement.dependency_audit = parse_import_audit(import_audit_path, stdout_text)
    measurement.rss_mb["after_shutdown"] = rss_mb(proc.pid) if proc else None
    return measurement


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure supported headless NAIA Remote WebSession startup.")
    parser.add_argument("--entrypoint", choices=["desktop", "headless"], default="headless")
    parser.add_argument("--port", type=int, default=7270, help="Remote WebShell port to launch.")
    parser.add_argument("--cdp-port", type=int, default=9370, help="Chrome DevTools Protocol port.")
    parser.add_argument("--python", default=None, help="Python executable. Defaults to venv\\Scripts\\python.exe when present.")
    parser.add_argument("--chrome", default=None, help="Chrome/Edge executable path.")
    parser.add_argument("--startup-timeout", type=float, default=180.0)
    parser.add_argument("--browser-timeout", type=float, default=60.0)
    parser.add_argument("--action-timeout", type=float, default=120.0)
    parser.add_argument("--include-generate", action="store_true", help="Click Generate and measure dispatch latency.")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--write-summary", type=Path, default=DEFAULT_DOC_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    args = parse_args(argv or sys.argv[1:])
    measurement = measure(args)
    write_json(args.output_json, measurement)
    write_summary(args.write_summary, measurement)
    print(json.dumps(measurement.__dict__, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
