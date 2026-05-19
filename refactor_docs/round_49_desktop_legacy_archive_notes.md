# Round 49 Desktop Legacy Archive Notes

## What Moved

- `NAIA_cold_v4.py` -> `legacy_desktop/NAIA_cold_v4.py`
- `core/remote_api_server.py` -> `legacy_desktop/core/remote_api_server.py`

This is the first physical archive step. It removes the primary Desktop App entrypoint and legacy RemoteBridge implementation from the supported root/core runtime surface.

## Compatibility Adjustments

- `legacy_desktop/NAIA_cold_v4.py` now injects the repository root into `sys.path` before loading project modules.
- The archived entrypoint uses the repository root for fonts, `modules/`, and Git metadata instead of `legacy_desktop/`.
- The archived RemoteBridge uses the repository root for `data/`, `ui/remote_web`, and preset services.
- `run_NAIA.bat` and `run_NAIA.command` now call the archived Desktop entrypoint.
- `tools/measure_web_session_startup.py --entrypoint desktop` now points at the archived path.

## Remaining Archive Work

The following Desktop App surfaces remain in the main source tree and should be handled in the next archive rounds:

- PyQt tab/module wrappers under `tabs/`, `modules/`, and `ui/`

Round 49B moved the desktop-only `core` controllers and helpers into `legacy_desktop/core/`. Round 49C moved tracked PyQt middle module wrappers from `modules/` into `legacy_desktop/modules/`. Round 49D moved tracked PyQt tab wrappers from `tabs/` into `legacy_desktop/tabs/`. Round 49E extracted server-used Event Preset helpers from `ui/` into `core/event_preset/`. Round 49F extracted server-used Clothes and Expression Preset assets from `ui/` into `core/clothes_preset/` and `core/expression_preset/`, so the remaining root `ui/` tree can be treated as PyQt UI wrapper code plus supported `ui/remote_web` static assets.

Known follow-up: remaining work is concentrated on PyQt wrappers under `ui/`. Some unarchived PyQt UI wrapper files still contain old `core.*` desktop-controller import names and should be moved as packages in the next UI-wrapper archive round. They are outside the supported headless import graph.
