# Legacy Desktop Archive

This directory contains unsupported Desktop App code retained only as a rollback/reference package while the supported Remote Web runtime migrates to `NAIA_web_headless.py`.

Current archive contents:

- `NAIA_cold_v4.py`: legacy PyQt Desktop App entrypoint.
- `core/remote_api_server.py`: legacy Desktop-backed RemoteBridge/FastAPI bridge.
- `core/*_controller.py`, `core/api_validator.py`, `core/comfyui_utils.py`, `core/ollama_service.py`: PyQt Desktop controllers and helper services that are no longer part of the supported `core/` runtime.
- `modules/`: PyQt middle module wrappers and conditional editor UI. Supported headless module behavior lives in PyQt-free `core/*_settings.py`, `core/*_runtime.py`, and `WebSessionContext` instead.
- `tabs/`: PyQt tab modules. Supported Remote Web tab behavior is served by headless FastAPI services and `ui/remote_web`.
- `ui/`: PyQt UI wrappers and desktop-only UI assets. The supported root `ui/` tree is reserved for `ui/remote_web` static assets.
- Event Preset data/engine helpers have been extracted to supported `core/event_preset/`; legacy PyQt windows should import those helpers instead of owning server-side logic.
- Clothes and Expression Preset server assets have been extracted to supported `core/clothes_preset/` and `core/expression_preset/`.

Supported Remote Web code must not import this package. Keep new headless behavior in `core/web_session_app.py`, `core/web_session_context.py`, and PyQt-free services under `core/`.
