# Round 44 RemoteBridge feature migration

Generated: 2026-05-19

## Objective

Move still-supported Remote Web websocket behavior out of the desktop-backed `RemoteBridge` contract and into the PyQt-free `WebSessionContext` / `core.web_session_app` headless server.

## TODO Checklist

- [x] Compare the Round 37 RemoteBridge contract with current headless websocket commands.
- [x] Migrate `set_param` from desktop bridge state into `WebSessionContext.remote_params`.
- [x] Migrate `set_active_ratings` and `get_search_state` into server-owned headless state.
- [x] Make headless Random use the server-owned active rating state when the request omits explicit ratings.
- [x] Add explicit headless responses for retired desktop/module commands instead of silent reliance on `RemoteBridge`.
- [x] Add tests for migrated websocket contracts and retired command responses.
- [x] Run fresh-process headless import tests without importing `core.remote_api_server`.
- [x] Run CDP validation against the migrated headless feature set.

## Migrated

- `set_param`: updates `WebSessionContext.remote_params` and returns a fresh `params` payload.
- `set_active_ratings`: updates `WebSessionContext.remote_active_ratings` and returns `search_state`.
- `get_search_state`: reports real `SearchResultModel` counts and rating counts from `WebSessionContext`.
- `random`: falls back to `WebSessionContext.remote_active_ratings` when no command-local ratings are supplied.

## Retired Or Deferred

- `read_hires_preset_overlay`: returns a headless `hires_preset_overlay` payload with `available: false`.
- `write_hires_preset_overlay`: returns an informational headless retired-command toast.
- `set_module_param`: returns an informational headless retired-command toast until module panels are migrated in Round 46.

## Validation

- `python -m py_compile core\web_session_app.py core\web_session_context.py`
- `python -m pytest tests\test_web_session_app.py::test_headless_websocket_set_param_updates_server_owned_params tests\test_web_session_app.py::test_headless_websocket_active_ratings_update_search_state_and_random -q`
- `python -m pytest tests\test_web_session_app.py::test_headless_websocket_retired_desktop_commands_are_explicit tests\test_web_session_app.py::test_headless_websocket_set_param_updates_server_owned_params tests\test_web_session_app.py::test_headless_websocket_active_ratings_update_search_state_and_random -q`
- `python -m pytest tests\test_web_session_app.py::test_headless_app_import_and_factory_do_not_import_pyqt_in_fresh_process tests\test_web_session_app.py::test_headless_websocket_generate_does_not_import_pyqt_in_fresh_process tests\test_web_session_app.py::test_headless_startup_random_and_generate_do_not_import_desktop_tabs_or_modules_in_fresh_process tests\test_requirements_split.py -q`
- `python tools\measure_web_session_startup.py --entrypoint headless --port 7297 --cdp-port 9397 --include-generate --action-timeout 60 --output-json logs\round44_headless_remote_bridge_migration_validation.json --write-summary refactor_docs\round_44_headless_remote_bridge_migration_validation.md`

## Result

- Supported headless startup, API setup, Random, Generate dispatch, params, and active rating state no longer need `RemoteBridge`.
- CDP validation output: `refactor_docs/round_44_headless_remote_bridge_migration_validation.md`.
