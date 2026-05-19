# Round 31 Headless Service Container

## Goal

Create the first PyQt-free server-side container for Remote Web so later rounds can move FastAPI startup, websocket state, random prompt, generation dispatch, results, and history off the hidden desktop runtime.

## TODO Checklist

- [x] Confirm the Round 31 plan against the roadmap.
- [x] Inspect current `AppContext`, `RemoteBridge`, `/api/status`, and websocket initial-state contracts.
- [x] Add a PyQt-free `WebSessionContext`.
- [x] Add a PyQt-free event bus compatible with the `subscribe` / `unsubscribe` / `publish` pattern.
- [x] Expose API mode state and `api_mode_changed` publication.
- [x] Expose shared Remote Web option state.
- [x] Expose API setup/status payloads using a token-store boundary.
- [x] Expose autocomplete warmup/cache status.
- [x] Expose queue state using the existing queue manager without desktop widgets.
- [x] Expose initial websocket message assembly for session/mode/options/params/queue/api status.
- [x] Define desktop adapter boundaries by keeping desktop-only objects absent from the headless container.
- [x] Add focused tests proving import/construction does not import `PyQt6`.
- [x] Run static and focused test validation.

## When Done

- [x] `WebSessionContext` can be imported without importing `PyQt6`.
- [x] `WebSessionContext` can be constructed in a fresh Python process without importing `PyQt6`.
- [x] The container returns a `/api/status`-compatible payload.
- [x] The container returns the initial websocket state needed by the Remote Web shell.
- [x] Desktop `AppContext` remains unchanged for the current desktop-backed WebShell path.

## Result

Added:

- `core/web_session_context.py`
- `tests/test_web_session_context.py`

Validation:

```powershell
python -m py_compile core\web_session_context.py tests\test_web_session_context.py
python -m pytest tests\test_web_session_context.py -q
```

Focused test result:

```text
4 passed
```

## Boundary

This round does not start a headless FastAPI process yet. It creates the state owner that Round 32 can mount behind a PyQt-free FastAPI app.
