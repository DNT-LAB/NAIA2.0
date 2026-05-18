# Round 27 Conditional Prompt Lazy Runtime

## Plan Check

- `PromptListModifierModule` remained the last eager middle module in hidden WebSession startup.
- The full conditional rule engine is still PyQt-module-owned, so this round avoids a risky rule-engine rewrite.
- Target: keep startup PyQt import out of WebSession, register a PyQt-free hook, and lazy-load the module only when conditional rules or explicit advanced actions need it.

## Work

- Added `core.conditional_prompt_runtime.ConditionalPromptHeadlessHook`.
- Changed the middle module registry so `PromptListModifierModule` is `web_session_lazy=True` with `web_session_headless_hook="conditional_prompt"`.
- The headless hook reads `core.conditional_prompt_settings` first. Disabled or blank rules return without importing the PyQt module.
- Enabled rules lazy-load `PromptListModifierModule` and delegate to the existing rule engine, preserving current generation behavior.
- RemoteBridge store-backed actions remain PyQt-free; unsupported advanced actions now load the deferred module on demand instead of failing immediately.

## Verification

- `python -m py_compile core\conditional_prompt_runtime.py core\conditional_prompt_settings.py core\middle_section_controller.py core\remote_api_server.py`
- `python -m pytest tests\test_middle_section_controller_static_registry.py tests\test_remote_api_status.py -q`
- `python -m pytest tests\test_remote_api_status.py tests\test_middle_section_controller_static_registry.py tests\test_conditional_prompt_restore.py tests\test_prompt_engineering_runtime.py tests\test_character_settings.py tests\test_event_stream_runtime.py tests\test_prompt_engineering_preset_schema.py -q`
- `git diff --check -- . ':!logs'`
- WebShell/CDP on port 7268:
  - Startup registered `Conditional Prompt Headless` and deferred `conditional_prompt_module -> PromptListModifierModule`.
  - Startup/module visibility checks stayed at 0 module instances before Remote API server startup.
  - Opening the Remote Web conditional prompt panel did not load `PromptListModifierModule`.
  - CDP page check passed: `#promptEdit` present, Generate enabled, conditional popup rendered. Browser log only showed `/favicon.ico` 404.

## Residual Work

- A future round can move the conditional rule engine itself into a pure core runtime to avoid PyQt import even for enabled conditional generations.
- Legacy `test_rules()` still depends on a desktop widget; v2 simulation remains the Remote Web path for headless validation.
