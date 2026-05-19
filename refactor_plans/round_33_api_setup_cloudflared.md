# Round 33 API Setup and Cloudflared Ownership

## Goal

Move the Remote Web API setup surface onto PyQt-free server services so the headless entrypoint can read, verify, save, clear, and broadcast API configuration without constructing Settings tab objects.

## TODO Checklist

- [x] Confirm the Round 33 plan against the roadmap.
- [x] Inspect the existing websocket setup command contract.
- [x] Add a PyQt-free API setup service.
- [x] Add a PyQt-free Cloudflared service boundary.
- [x] Move API status payload assembly behind the service.
- [x] Support NAI token verify/save.
- [x] Support WebUI URL verify/save.
- [x] Support ComfyUI URL verify/save.
- [x] Support API clear/disconnect by mode.
- [x] Support saved backend probe.
- [x] Support Cloudflared status and enable/disable from the headless websocket path.
- [x] Keep the existing desktop-backed Settings tab path intact.
- [x] Add focused service and websocket tests.
- [x] Run static validation and focused tests.
- [x] Run CDP validation against the live headless API modal.

## When Done

- [x] The headless API modal receives server-owned `api_status`.
- [x] Verify/save commands work through a PyQt-free service.
- [x] Clear/disconnect commands work through a PyQt-free service.
- [x] Probe commands work through a PyQt-free service.
- [x] Cloudflared status/control has a PyQt-free service boundary.
- [x] The desktop-backed WebShell remains compatible.

## Result

Added:

- `core/api_config_service.py`
- `tests/test_api_config_service.py`

Updated:

- `core/web_session_context.py`
- `core/web_session_app.py`
- `tests/test_web_session_app.py`

Validation:

```powershell
python -m py_compile core\api_config_service.py core\web_session_context.py core\web_session_app.py tests\test_api_config_service.py tests\test_web_session_context.py tests\test_web_session_app.py
python -m pytest tests\test_api_config_service.py tests\test_web_session_context.py tests\test_web_session_app.py -q
python NAIA_web_headless.py --help
```

Focused test result:

```text
14 passed
```

Live CDP validation:

```powershell
python NAIA_web_headless.py --host 127.0.0.1 --port 7282
```

CDP opened `http://127.0.0.1:7282/`, clicked the API launcher, and confirmed:

- API modal open: true
- title: `API 설정`
- NAI/WebUI/ComfyUI saved status rendered from server state
- clear buttons enabled for configured backends
- Cloudflared controls visible
- Cloudflared status: `연결 안 됨`

The CDP pass did not write tokens or start Cloudflared; verify/save, clear, probe, and Cloudflared state transitions are covered by focused tests with in-memory services.

## Boundary

This round does not move Random prompt or Generate dispatch. Round 34 should move Random prompt execution onto server-owned core prompt services. Round 35 should move Generate dispatch onto a widget-free request contract.
