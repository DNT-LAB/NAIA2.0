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

- `core.middle_section_controller`
- `core.tab_controller`
- `core.main_controller`
- `core.generation_controller`
- `core.prompt_generation_controller`
- `core.search_controller`
- `core.autocomplete_manager`
- `core.ui_state_manager`
- `core.temp_window_manager`
- PyQt tab/module wrappers under `tabs/`, `modules/`, and `ui/`

They were not moved in this pass because several legacy PyQt files import each other through the current `core.*` and `ui.*` names. Moving them safely requires either a broader package move or explicit retirement of the legacy desktop launcher.
