# Round 26 Conditional Prompt Headless Store

## Plan Check

- `PromptListModifierModule` is still the last eager middle module in hidden WebSession startup.
- A direct `web_session_lazy=True` registry change would remove the generation-time conditional prompt hook, so this round only splits Remote Web state read/write away from the PyQt module instance.
- The generation hook remains module-backed until a separate `core.conditional_prompt_runtime` owner exists.

## Work

- Added `core.conditional_prompt_settings` as a PyQt-free, mode-aware settings store for enabled state, legacy rules, v2 DSL, editor mode, engine options, and active preset.
- Changed `RemoteBridge._read_conditional_prompt()` to prefer an already-loaded `PromptListModifierModule`, then fall back to the store without calling `get_module_instance()`.
- Added a headless `_set_conditional_prompt()` fallback for Remote Web state edits that can be represented in persisted settings.

## Verification

- `python -m py_compile core\conditional_prompt_settings.py core\remote_api_server.py`
- `python -m pytest tests\test_remote_api_status.py -q`
- `python -m pytest tests\test_remote_api_status.py tests\test_middle_section_controller_static_registry.py tests\test_conditional_prompt_restore.py tests\test_prompt_engineering_runtime.py tests\test_character_settings.py tests\test_event_stream_runtime.py tests\test_prompt_engineering_preset_schema.py -q`
- `git diff --check -- . ':!logs'`

## Residual Work

- Full lazy startup for `PromptListModifierModule` still requires `core.conditional_prompt_runtime` to own the `PromptProcessor/after_wildcard` hook.
- Instance-only actions such as preview simulation and desktop editor behavior remain module-backed.
