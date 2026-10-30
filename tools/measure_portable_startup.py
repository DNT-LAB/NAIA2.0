"""Probe the shipped NAIA.exe/Python/backend with isolated, selected user data.

No install, generation, source overwrite or real user-data writes. Output must
be a NEW directory. Optional --pool replaces only the isolated last-search copy.
The optional character pack downloader is suppressed by the injected probe.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from measure_web_session_startup import (CdpClient, url_json, socket_listens, stop_process_tree,
                                         rss_mb, find_chrome, launch_chrome, wait_for, get_page_target)


OBSERVER = r"""
(() => {
  if (window.__startupProbe) return;
  const events = window.__startupProbe = [];
  const record = (kind, fields = {}) => events.push({kind, epoch_ms: Date.now(), page_ms: performance.now(), ...fields});
  const Original = window.WebSocket;
  window.WebSocket = class extends Original {
    constructor(...args) {
      super(...args);
      this.addEventListener('open', () => record('ws_open'));
      this.addEventListener('message', e => {
        try { const m = JSON.parse(e.data); record('ws_receive', {type:m.type, module:m.module_id||m.module, loading:m.loading}); } catch {}
      });
    }
    send(data) {
      try { const m = JSON.parse(data); record('ws_send', {type:m.type, module:m.module_id||m.module}); } catch {}
      return super.send(data);
    }
  };
  new PerformanceObserver(list => {
    for (const e of list.getEntries()) record('longtask', {duration_ms:e.duration});
  }).observe({entryTypes:['longtask']});
  let previous = '';
  setInterval(() => {
    const veil = document.getElementById('stateVeil');
    const state = {veil:!!veil && !veil.classList.contains('lifted'),
      apiOverlay:!!document.querySelector('#apiPopupOverlay.open'),
      veilText:document.getElementById('stateVeilText')?.textContent || '',
      selects:Array.from(document.querySelectorAll('select')).filter(e => /preset/i.test(e.id)).map(e => ({id:e.id, count:e.options.length, disabled:e.disabled}))};
    const key = JSON.stringify(state);
    if (key !== previous) { record('ui_state', state); previous = key; }
  }, 100);
})();
"""


def copy_file(source, target, manifest):
    if not source.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    manifest.append({"source": str(source), "target": str(target), "bytes": source.stat().st_size})


def prepare(portable, output, pool, saved_ui=False, reuse_fixture=None):
    if reuse_fixture is not None:
        if pool is not None:
            raise ValueError("--reuse-fixture cannot be combined with --pool")
        previous = reuse_fixture.resolve()
        target = previous / "user-data"
        run = previous / "run.json"
        if run.is_file():
            target = Path(json.loads(run.read_text(encoding="utf-8"))["user_data"]).resolve()
        if not target.is_dir() or not (previous / "fixture.json").is_file():
            raise ValueError("--reuse-fixture requires a previous measurement fixture")
        (output / "fixture.json").write_text(
            json.dumps({"reused_from": str(previous), "user_data": str(target)}), encoding="utf-8")
        return target, prepare_injection(output)
    source, target = portable / "user-data", output / "user-data"
    manifest = []
    # Only selected noncredential state. Extensions, tokens, output, external
    # engine paths and API settings deliberately do not enter the test runtime.
    for name in ("remote_web_filter_state.json", "remote_web_filter_presets.json", "first_run.json"):
        copy_file(source / "save" / name, target / "save" / name, manifest)
    if saved_ui:
        raw = json.loads((source / "save/app_settings.json").read_text(encoding="utf-8")).get("remote_web", {})
        # Explicit allowlist: never copy endpoint settings, credentials, automation,
        # output directories or arbitrary remote parameters into this test.
        state = {key: raw[key] for key in ("version", "api_mode", "prompt", "negative_prompt") if key in raw}
        state["prompt_planes"] = {
            mode: {key: plane[key] for key in ("prompt", "negative_prompt") if key in plane}
            for mode, plane in raw.get("prompt_planes", {}).items() if isinstance(plane, dict)
        }
        (target / "save/app_settings.json").write_text(json.dumps({"remote_web":state}), encoding="utf-8")
    for folder in ("save/presets", "data/tags", "data/tag_index", "data/taglist"):
        root = source / folder
        if root.exists():
            for file in root.rglob("*"):
                if file.is_file():
                    copy_file(file, target / folder / file.relative_to(root), manifest)
    for file in (source / "cache").glob("naia_*"):
        copy_file(file, target / "cache" / file.name, manifest)
    if pool:
        copy_file(pool, target / "cache/naia_last_search.parquet", manifest)
    (output / "fixture.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return target, prepare_injection(output)


def prepare_injection(output):
    inject = output / "inject"
    inject.mkdir()
    shutil.copy2(Path(__file__).with_name("startup_phase_probe.py"), inject / "startup_phase_probe.py")
    (inject / "sitecustomize.py").write_text("import startup_phase_probe\nstartup_phase_probe.install()\n", encoding="utf-8")
    return inject


def chrome_check(output, port, cdp_port):
    chrome = find_chrome()
    if not chrome or "chrome" not in chrome.lower():
        return {"error":"Chrome unavailable"}
    url = f"http://127.0.0.1:{port}/"
    proc = launch_chrome(chrome, "about:blank", cdp_port, output / "chrome-profile")
    client = None
    try:
        page = wait_for(lambda: get_page_target(cdp_port, "about:blank"), timeout=15)
        client = CdpClient(page["webSocketDebuggerUrl"])
        client.send("Page.enable")
        client.send("Page.navigate", {"url":url})
        def click(expression):
            point = client.evaluate("(() => {const e=" + expression + ";if(!e)return null;const r=e.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2;return r.width && e.contains(document.elementFromPoint(x,y)) ? {x,y}:null;})()")
            if not point:
                return False
            for kind in ("mousePressed", "mouseReleased"):
                client.send("Input.dispatchMouseEvent", {"type":kind,"button":"left","clickCount":1,**point})
            return True
        wait_for(lambda: client.evaluate("document.readyState==='complete' && !!document.getElementById('promptEdit')"), timeout=20)
        # Legitimate reference-only setup path; no overlay/CSS bypass.
        for _ in range(30):
            if client.evaluate("!!document.querySelector('#apiPopupOverlay.open')"):
                click("document.getElementById('setupNoApi')")
            if not client.evaluate("!!document.querySelector('#apiPopupOverlay.open') || !!document.querySelector('#stateVeil:not(.lifted)')"):
                break
            time.sleep(0.2)
        wait_for(lambda: click("Array.from(document.querySelectorAll('button')).find(e=>e.textContent.trim()==='프롬프트 엔지니어링')"), timeout=15)
        wait_for(lambda: client.evaluate("!!document.querySelector('#modPreset')"), timeout=15)
        result = client.evaluate("({presetOptions:document.querySelector('#modPreset').options.length, veil:!!document.querySelector('#stateVeil:not(.lifted)'),apiOverlay:!!document.querySelector('#apiPopupOverlay.open')})")
        shot = client.send("Page.captureScreenshot", {"format":"png"})
        (output / "chrome-quick-preset.png").write_bytes(base64.b64decode(shot["data"]))
        return result
    except Exception as exc:
        return {"error":str(exc)}
    finally:
        if client:
            client.close()
        stop_process_tree(proc.pid)


def summarize(output, meta, observations):
    path = output / "phases.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    starts = {row["span"]: row for row in rows if row["event"] == "begin"}
    ends = {row["span"]: row for row in rows if row["event"] == "end"}
    spans = []
    for identity, end in ends.items():
        begin = starts[identity]
        spans.append({"name":end["name"], "start_s":(begin["epoch_ms"]-meta["started_epoch_ms"])/1000,
                      "wall_s":end["wall_ms"]/1000, "cpu_s":end["cpu_ms"]/1000,
                      "thread":begin["thread"], "parent":begin.get("parent"),
                      "command_type":begin.get("command_type"), "rows":begin.get("rows"),
                      "status":end["status"]})
    events = next((item["events"] for item in reversed(observations) if item.get("events")), [])
    milestones = {}
    saw_veil = False
    for event in events:
        elapsed = (event["epoch_ms"] - meta["started_epoch_ms"])/1000
        if event["kind"] == "ws_receive":
            kind = event.get("type")
            if kind in ("init_complete", "search_state"):
                milestones.setdefault(kind, elapsed)
            if kind == "module_state" and event.get("module") == "prompt_engineering":
                milestones.setdefault("preset_state", elapsed)
        if event["kind"] == "ui_state":
            saw_veil = saw_veil or event.get("veil", False)
            if saw_veil and not event.get("veil"):
                milestones.setdefault("veil_lifted", elapsed)
    return {"spans":spans, "milestones_s":milestones,
            "max_loop_lag_ms":max((r["lag_ms"] for r in rows if r["event"]=="loop_lag"),default=None),
            "max_worker_queue_ms":max((r["queue_ms"] for r in rows if r["event"]=="worker_start"),default=None),
            "peak_summed_rss_mb":max((r.get("rss_mb") or 0 for r in observations),default=None),
            "missing_targets":[r["name"] for r in rows if r["event"]=="missing_target"],
            "unfinished_spans":[starts[key]["name"] for key in starts.keys()-ends.keys()],
            "notes":"Inclusive overlapping wall spans; calling-thread CPU; summed RSS includes shared pages. Server/gate spans can remain open at forced test shutdown."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portable", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pool", type=Path)
    parser.add_argument("--reuse-fixture", type=Path,
                        help="Reuse a previous output's user-data in place, without copying")
    parser.add_argument("--duration", type=float, default=90)
    parser.add_argument("--port", type=int, default=7363)
    parser.add_argument("--cdp-port", type=int, default=9343)
    parser.add_argument("--saved-ui-state", action="store_true", help="Copy only saved mode and prompt text; defer NO API selection")
    parser.add_argument("--chrome-check", action="store_true", help="After timing, inspect Quick Preset in isolated Chrome")
    args = parser.parse_args()
    portable, output = args.portable.resolve(), args.output.resolve()
    runtime_python = portable / "user-data/runtime-env/Scripts/python.exe"
    if not runtime_python.is_file():
        raise SystemExit("Existing installed Portable runtime required; this tool never installs dependencies")
    if socket_listens("127.0.0.1", args.port) or socket_listens("127.0.0.1", args.cdp_port):
        raise SystemExit("Measurement ports already occupied")
    output.mkdir(parents=True, exist_ok=False)
    if args.chrome_check and socket_listens("127.0.0.1", args.cdp_port + 1):
        raise SystemExit("Chrome verification port occupied")
    user_data, inject = prepare(portable, output, args.pool, args.saved_ui_state, args.reuse_fixture)
    env = dict(os.environ, NAIA_USER_DATA_DIR=str(user_data), NAIA_BACKEND_PORT=str(args.port),
               NAIA_BACKEND_BIND_HOST="127.0.0.1", NAIA_ELECTRON_REMOTE_DEBUGGING_PORT=str(args.cdp_port),
               NAIA_STARTUP_PROBE_LOG=str(output / "phases.jsonl"), NAIA_STARTUP_PROBE_OFFLINE="1",
               NAIA_CHARACTER_PACK_AUTOSTART_DELAY="86400", PYTHONPATH=str(inject),
               NAIA_PYTHON=str(runtime_python), NAIA_RUNTIME_ENV_SKIP_BOOTSTRAP="1",
               NAIA_DISABLE_EXTENSIONS="1")
    exe = portable / "NAIA.exe"
    started = time.time() * 1000
    meta = {"started_epoch_ms": started, "exe":str(exe), "backend":str(portable / "resources/naia-backend"),
            "user_data":str(user_data), "pool_override":str(args.pool) if args.pool else None,
            "reuse_fixture": str(args.reuse_fixture.resolve()) if args.reuse_fixture else None,
            "isolation":"selected data only; no credentials/extensions; optional pack autostart disabled",
            "saved_mode_and_prompts":args.saved_ui_state,
            "exe_sha256":hashlib.sha256(exe.read_bytes()).hexdigest()}
    client = None
    client_id = None
    no_api_clicked = False
    observations = []
    with (output / "electron.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([str(exe), f"--remote-debugging-port={args.cdp_port}",
                                    "--remote-allow-origins=*"], cwd=portable, env=env,
                                   stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        meta["pid"] = process.pid
        try:
            deadline = time.monotonic() + args.duration
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"Portable exited: {process.returncode}")
                try:
                    pages = url_json(f"http://127.0.0.1:{args.cdp_port}/json/list")
                    available = [p for p in pages if p.get("type") == "page"]
                    page = next((p for p in available if p.get("url", "").startswith(f"http://127.0.0.1:{args.port}/")), available[0] if available else None)
                    if page is None:
                        raise StopIteration()
                    if client is None or client_id != page["id"]:
                        if client:
                            client.close()
                        client = CdpClient(page["webSocketDebuggerUrl"])
                        client_id = page["id"]
                        client.send("Page.enable")
                        client.send("Page.addScriptToEvaluateOnNewDocument", {"source":OBSERVER})
                        client.evaluate(OBSERVER)
                        meta["attached_epoch_ms"] = time.time() * 1000
                        meta["attached_url"] = page.get("url")
                        observations.append({"epoch_ms":time.time()*1000,"attached":page.get("url")})
                    # Some Electron navigations replace the main world without
                    # running the registered new-document hook. Idempotent fallback.
                    client.evaluate(OBSERVER)
                    state = client.evaluate("({url:location.href,events:window.__startupProbe||[],buttons:Array.from(document.querySelectorAll('button')).filter(e=>/NO API/.test(e.textContent)).map(e=>({id:e.id,text:e.textContent.trim()}))})")
                    if state:
                        observations.append({"epoch_ms":time.time()*1000, "rss_mb":rss_mb(process.pid), **state})
                    if not no_api_clicked and not args.saved_ui_state:
                        point = client.evaluate("(() => {const e=document.getElementById('setupNoApi');if(!e)return null;const r=e.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2;return r.width && document.elementFromPoint(x,y)===e ? {x,y}:null;})()")
                        if point:
                            client.send("Input.dispatchMouseEvent", {"type":"mousePressed", "button":"left", "clickCount":1, **point})
                            client.send("Input.dispatchMouseEvent", {"type":"mouseReleased", "button":"left", "clickCount":1, **point})
                            no_api_clicked = True
                            observations.append({"epoch_ms":time.time()*1000,"action":"click_no_api"})
                except (OSError, RuntimeError, StopIteration, ValueError) as exc:
                    observations.append({"epoch_ms":time.time()*1000, "error":type(exc).__name__})
                time.sleep(0.25)
            if client:
                shot = client.send("Page.captureScreenshot", {"format":"png"})
                (output / "portable.png").write_bytes(base64.b64decode(shot["data"]))
            if args.chrome_check:
                meta["chrome_check"] = chrome_check(output, args.port, args.cdp_port + 1)
        finally:
            if client:
                client.close()
            stop_process_tree(process.pid)
            meta["finished_epoch_ms"] = time.time() * 1000
            meta["ports_released"] = not socket_listens("127.0.0.1",args.port) and not socket_listens("127.0.0.1",args.cdp_port)
            (output / "run.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
            (output / "browser.json").write_text(json.dumps(observations, ensure_ascii=False), encoding="utf-8")
            (output / "summary.json").write_text(json.dumps(summarize(output, meta, observations), indent=2), encoding="utf-8")
    print(str(output))


if __name__ == "__main__":
    main()
