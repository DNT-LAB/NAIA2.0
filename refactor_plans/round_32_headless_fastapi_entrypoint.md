# Round 32 Headless FastAPI Entrypoint

## Goal

Start the Remote Web shell from a PyQt-free FastAPI/core-service runtime without constructing the desktop application.

This is the first runnable headless entrypoint. It proves startup, static asset serving, `/api/status`, websocket initialization, and CDP first paint. It does not yet perform Random prompt generation or image generation dispatch.

## TODO Checklist

- [x] Confirm the Round 32 plan against the roadmap.
- [x] Inspect the existing static serving and websocket startup contract.
- [x] Add a PyQt-free FastAPI app factory.
- [x] Add a PyQt-free launcher entrypoint.
- [x] Serve `ui/remote_web` static assets.
- [x] Wire `/api/status` from `WebSessionContext`.
- [x] Wire websocket startup messages from `WebSessionContext`.
- [x] Send `lazy_indices_ready` so the Remote Web boot indicator can finalize.
- [x] Preserve the existing desktop-backed `NAIA_cold_v4.py --web-shell` path.
- [x] Add tests proving the app factory and entrypoint import without `PyQt6`.
- [x] Add tests for root HTML, `/api/status`, and websocket initial state.
- [x] Run static validation and focused tests.
- [x] Run CDP validation against the live headless server.

## When Done

- [x] `python NAIA_web_headless.py --port <port>` starts a FastAPI Remote Web server.
- [x] `/api/status` returns 200 from the headless process.
- [x] Websocket startup sends the initial Remote Web state without `RemoteBridge`.
- [x] CDP opens the Remote Web root and sees Random/Generate controls.
- [x] Focused tests show no `PyQt6` import in the headless app/entrypoint path.

## Result

Added:

- `core/web_session_app.py`
- `NAIA_web_headless.py`
- `tests/test_web_session_app.py`

Validation:

```powershell
python -m py_compile core\web_session_context.py core\web_session_app.py NAIA_web_headless.py tests\test_web_session_app.py tests\test_web_session_context.py
python -m pytest tests\test_web_session_context.py tests\test_web_session_app.py -q
python NAIA_web_headless.py --help
```

Focused test result:

```text
8 passed
```

Live validation:

```powershell
python NAIA_web_headless.py --host 127.0.0.1 --port 7281
```

- `/api/status` returned 200 with `api_mode: NAI`.
- Chrome CDP first paint returned title `NAIA Remote`, `readyState: complete`, `hasRandom: true`, `hasGenerate: true`, `bootHidden: true`, `mode: NAI`.
- Screenshot captured at `logs/round32_headless_cdp.png` and left ignored with the other runtime logs.

## Boundary

Random prompt execution and Generate dispatch are intentionally not wired in this headless app yet. They return a headless "not wired yet" toast. Round 34 and Round 35 must move those contracts out of `RemoteBridge` and desktop widgets.
