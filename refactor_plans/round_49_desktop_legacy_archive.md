# Round 49 - Desktop Legacy Archive

## Objective

Physically move the first Desktop App entrypoints out of the supported runtime tree without breaking the headless Remote Web launch path.

## TODO Checklist

- [x] Choose non-destructive archive strategy: `legacy_desktop/`.
- [x] Move `NAIA_cold_v4.py` to `legacy_desktop/NAIA_cold_v4.py`.
- [x] Move legacy Desktop-backed `core.remote_api_server` to `legacy_desktop/core/remote_api_server.py`.
- [x] Update Desktop legacy launchers to point at the archived entrypoint.
- [x] Update startup measurement tooling to use the archived path for legacy desktop comparison.
- [x] Add headless import guards for the new `legacy_desktop` package.
- [x] Run focused tests and static checks.
- [x] Move or retire remaining PyQt controllers from `core/`.
- [ ] Move or retire remaining PyQt tab/module wrappers from `tabs/`, `modules/`, and `ui/`.

## When Done

- The repository root no longer exposes `NAIA_cold_v4.py` as a supported entrypoint.
- The supported `core/` package no longer contains `remote_api_server.py`.
- Headless launch, Random, and Generate dispatch still work through CDP.
- Fresh-process import guards fail if supported headless imports `legacy_desktop`, `PyQt6`, or Desktop controller modules.
- Remaining Desktop App code is either archived here or explicitly listed for the next archive round.

## Round 49B Core Archive

Moved these desktop-only core modules to `legacy_desktop/core/`:

- `api_validator.py`
- `autocomplete_manager.py`
- `comfyui_utils.py`
- `generation_controller.py`
- `main_controller.py`
- `middle_section_controller.py`
- `ollama_service.py`
- `prompt_generation_controller.py`
- `search_controller.py`
- `tab_controller.py`
- `temp_window_manager.py`
- `ui_state_manager.py`

Validation:

- `python -m py_compile` for archived controllers and affected import surfaces.
- `python -m pytest tests\test_web_session_app.py tests\test_requirements_split.py tests\test_web_shell_config.py -q`
- `python -m pytest tests\test_auto_resolution_hiresfix_defaults.py tests\test_conditional_prompt_restore.py tests\test_generation_preset_tokens.py tests\test_middle_section_controller_static_registry.py tests\test_tab_controller_removed_tabs.py tests\test_ui_state_manager.py -q`
- `python -m pytest tests\test_remote_api_status.py -k "generation_worker" -q`
- CDP validation: `refactor_docs/round_49_core_controller_archive_validation.md`
