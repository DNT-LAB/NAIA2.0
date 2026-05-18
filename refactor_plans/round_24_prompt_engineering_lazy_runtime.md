# Round 24 Prompt Engineering lazy runtime

## Plan check

- Target: remove `PromptEngineeringModule` import/instance creation from hidden WebSession startup.
- Preserve required WebSession behavior:
  - Remote Web Prompt Engineering state read/write.
  - PromptProcessor post-processing hook.
  - Closed Eyes Sync, e621 Auto-Boost, Danbooru Auto-Weight, Outfit Context Resolver after-wildcard hooks.
  - Event Stream prompt-engineering freeze semantics.
  - `*randomized` random-prompt side effects.
- Constraint: advanced PyQt-backed Prompt Engineering behavior may load `PromptEngineeringModule` on demand only when the feature actually requires it.

## Work performed

- Added `core.prompt_engineering_runtime` as the hidden WebSession hook owner.
- Changed `PromptEngineeringModule` registry entry to `web_session_lazy=True` with `web_session_headless_hook="prompt_engineering"`.
- Added shared `get_prompt_engineering_store(app_context)` so RemoteBridge, Event Stream, and the headless runtime use one PyQt-free store.
- Changed Event Stream Prompt Engineering capture to avoid waking `PromptEngineeringModule`; it now uses an already-loaded module first and otherwise captures from the core store.
- Kept loaded-module precedence in the headless post hook:
  1. Event Stream frozen options
  2. per-session override, including empty dict
  3. already-loaded `PromptEngineeringModule`
  4. core store
- Preserved loaded-only CharacterModule closed-eyes clone sync without waking `CharacterModule`.
- Prevented duplicate random-prompt subscriptions when `PromptEngineeringModule` is later lazy-loaded.

## Validation

- `python -m py_compile core\prompt_engineering_runtime.py core\prompt_engineering_settings.py core\middle_section_controller.py core\remote_api_server.py core\event_tree\runtime.py modules\prompt_engineering_module.py`
- `python -m pytest tests\test_prompt_engineering_runtime.py tests\test_middle_section_controller_static_registry.py -q`
- `python -m pytest tests\test_remote_api_status.py tests\test_event_stream_runtime.py tests\test_prompt_engineering_preset_schema.py -k "prompt_engineering or event_stream" -q`
- `python -m pytest tests\test_middle_section_controller_static_registry.py tests\test_tab_controller_removed_tabs.py tests\test_remote_api_status.py tests\test_automation_settings.py tests\test_character_settings.py tests\test_conditional_prompt_restore.py tests\test_instant_wildcard_service.py tests\test_wildcard_status_settings.py tests\test_reference_inset_service.py tests\test_prompt_generation_service.py tests\test_result_image_payload_service.py tests\test_prompt_engineering_preset_schema.py tests\test_prompt_engineering_runtime.py tests\test_event_stream_runtime.py -q`
- `git diff --check -- . ':!logs'`
- CDP on `http://127.0.0.1:7266/`:
  - hidden WebShell startup registered five Prompt Engineering headless hooks.
  - startup log contains `Web Session headless middle hook 등록: PromptEngineeringModule`.
  - startup log does not contain `모듈 로드 성공: prompt_engineering_module -> PromptEngineeringModule`.
  - startup log does not contain `지연 middle 모듈 로드 완료: PromptEngineeringModule` after opening the Remote Web Prompt Engineering panel.
  - Random button changed `#promptEdit`.
  - Generate button remained enabled.
  - Prompt Engineering panel opened with pre/post/auto-hide controls from server state.

## Remaining work

- `PromptListModifierModule` is still an eager hidden WebSession module with `web_session_headless_widget`; full lazy requires a conditional-prompt core hook/service.
- `CharacterModule` can still be loaded by existing NAI mode setup paths after startup. It no longer needs to be imported for Prompt Engineering closed-eyes sync, but a separate startup-path audit is needed.
- The broader hidden WebShell still depends on PyQt/QApplication and selected UI initialization. This round removes one large middle-module import, not the full PyQt backend.
