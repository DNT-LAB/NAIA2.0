# Round 28 Headless Character Generate Fix

## Plan Check

- User-reported runtime failure showed `CharacterModule.on_random_prompt_triggered` crashing with `NoneType.isChecked` after a Remote Web client loaded `CharacterModule` without creating its widget.
- The same unsafe assumption existed in Generate-time reroll and late-binding character paths.
- Target: keep CharacterModule lazy/headless behavior, but treat a loaded module without widget state as inactive and fall back to saved headless settings.

## Work

- Added PyQt-free helpers in `core.character_settings` for loaded CharacterModule widget-state checks.
- Guarded `CharacterModule.on_random_prompt_triggered()`, `process_and_update_view()`, and `get_parameters()` against widget-less/headless module instances.
- Updated Generate-time character reroll checks in `core.generation_controller`.
- Updated NAI late-binding character checks in `core.api_service` and RemoteBridge prompt-reopen character params.
- Updated the desktop auto-generation character refresh guard in `NAIA_cold_v4.py`.

## Verification

- `python -m py_compile core\character_settings.py modules\character_module.py core\generation_controller.py core\api_service.py core\remote_api_server.py NAIA_cold_v4.py`
- `python -m pytest tests\test_character_settings.py -q`
- `python -m pytest tests\test_remote_api_status.py tests\test_middle_section_controller_static_registry.py -q`
- WebShell/CDP on port 7243:
  - Clicked Generate through `#btnGen`.
  - Log reached NAI API call, `generation_result_available`, thumbnail generation, and PNG save.
  - Clicked Random through `#btnRnd`; log emitted `random_prompt_triggered` and `prompt_generated`.
  - No `NoneType`, `isChecked`, traceback, or stderr error remained. Browser log only showed `/favicon.ico` 404.
