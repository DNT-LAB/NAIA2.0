# Round 25 Character token count loaded-only path

## Plan check

- Target: remove one confirmed hidden WebSession startup wake-up path for `CharacterModule`.
- Evidence from Round 24 logs:
  - hidden startup initially deferred `CharacterModule`.
  - `ModernMainWindow.update_token_count()` later called `get_module_instance("CharacterModule")`.
  - this loaded the deferred module and subscribed `CharacterModule.on_random_prompt_triggered`, which then errored in widget-less state during random prompt events.

## Work performed

- Changed `ModernMainWindow.update_token_count()` so hidden WebSession uses `get_loaded_module_instance("CharacterModule")`.
- If the module is not loaded, token count uses `core.character_settings.character_params_from_settings()` instead of waking the PyQt module.
- Desktop behavior remains unchanged: desktop still uses `get_module_instance("CharacterModule")`.

## Validation

- `python -m py_compile NAIA_cold_v4.py`
- `python -m pytest tests\test_character_settings.py tests\test_middle_section_controller_static_registry.py -q`
- `python -m pytest tests\test_middle_section_controller_static_registry.py tests\test_tab_controller_removed_tabs.py tests\test_remote_api_status.py tests\test_automation_settings.py tests\test_character_settings.py tests\test_conditional_prompt_restore.py tests\test_instant_wildcard_service.py tests\test_wildcard_status_settings.py tests\test_reference_inset_service.py tests\test_prompt_generation_service.py tests\test_result_image_payload_service.py tests\test_prompt_engineering_preset_schema.py tests\test_prompt_engineering_runtime.py tests\test_event_stream_runtime.py -q`
- `git diff --check -- . ':!logs'`
- WebShell log on `http://127.0.0.1:7267/`:
  - startup module system reports `1개 모듈 로드됨`.
  - settings retries report `모듈 인스턴스 수: 1`.
  - `CharacterModule` no longer loads before the Remote API server starts.
  - later `지연 middle 모듈 로드 완료: CharacterModule` occurred only after a Remote Web client connected and requested character state, which is the allowed on-demand path.

## Remaining work

- `PromptListModifierModule` full lazy remains the next large blocker.
- Subagent analysis confirms full lazy requires a PyQt-free conditional settings store and runtime hook before the registry can safely become `web_session_lazy=True`.
- A future round should create `core.conditional_prompt_settings` and `core.conditional_prompt_runtime`, then move RemoteBridge conditional read/write paths to the store first.
