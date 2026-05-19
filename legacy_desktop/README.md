# Legacy Desktop Archive

This directory contains unsupported Desktop App code retained only as a rollback/reference package while the supported Remote Web runtime migrates to `NAIA_web_headless.py`.

Current archive contents:

- `NAIA_cold_v4.py`: legacy PyQt Desktop App entrypoint.
- `core/remote_api_server.py`: legacy Desktop-backed RemoteBridge/FastAPI bridge.

Supported Remote Web code must not import this package. Keep new headless behavior in `core/web_session_app.py`, `core/web_session_context.py`, and PyQt-free services under `core/`.
