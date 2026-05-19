# Round 45 generation/result migration notes

Generated: 2026-05-19

## Summary

Round 45 removes another Remote Web dependency on the desktop result surface. The supported headless server now owns auto-save state, save-directory state, unsaved result counts, ZIP export, disk save-all, and headless history file paths.

## Server-Owned Result State

- `HeadlessResultStore` tracks unsaved history items and can produce an unsaved-history ZIP payload.
- `WebSessionContext` owns `auto_save` module state without reading desktop checkboxes.
- `WebSessionContext` owns `save_directory` module state without reading `ImageCrudController`.
- Save-all writes unsaved result images to the configured server-side save directory and marks each history item with its saved filepath.

## Supported Backend Modes

The headless runtime keeps NAI, WEBUI, and COMFYUI as supported generation modes. Tests cover request execution through the PyQt-free `APIService` boundary for all three modes using fake API services. Live WEBUI/COMFYUI server validation still needs a local external backend, but it no longer requires desktop controllers.

## Explicit Retirements

The following surfaces are desktop-only in this branch and now return explicit headless errors or retired-command messages:

- NAI result upscale
- Result enhance
- Desktop img2img/inpaint result action handoff
- Open result location
- Saved result reroll/queue replay
- Desktop result save/delete action endpoints
- Generic image-action endpoint used to open desktop module windows

## Evidence

- `tests/test_web_session_app.py` covers NAI, WEBUI, COMFYUI execution through headless queue/result storage.
- `tests/test_web_session_app.py` covers unsaved-history ZIP and save-all.
- `tests/test_web_session_app.py` covers auto-save/save-directory module state without desktop modules.
- CDP validation on port `7298` passed startup, Random, Generate dispatch, and import audit.
