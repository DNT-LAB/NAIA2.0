# Round 46 module workflow migration notes

## What Changed

- `WebSessionContext` now answers supported module state requests directly for:
  - `prompt_engineering`
  - `conditional_prompt`
  - `character`
  - `automation`
  - `webui_hiresfix_assist`
  - `wildcard`
- The supported module mutations above now use PyQt-free settings/runtime stores instead of `modules/*_module.py`.
- `character_reference`, `vibe_transfer`, `instant_wildcard`, `wildcard_status`, `e621_event`, and `ollama` now return explicit retired/deferred headless module state.

## Supported Headless Module Contracts

- `prompt_engineering`: pre prompt, post prompt, auto-hide, preprocessing toggles, preset selection/create/save/delete, randomized preset list, e621 settings, and Danbooru settings.
- `conditional_prompt`: enabled flag, editor mode, rule text, engine options, max passes, and stop-on-match.
- `character`: activation, reroll-on-generate, add/remove slot, prompt, UC, active state, cold/restore slot state, and slot display name.
- `automation`: delay, random delay, termination type, timer minutes, count limit, and notification setting.
- `webui_hiresfix_assist`: enabled flag and target size.
- `wildcard`: prompt squeeze and read-only wildcard count.

## Retired Or Deferred Contracts

- Automation `start` and `stop` are not supported because the old execution path depends on `AutomationModule` callbacks and desktop generation state.
- Conditional Prompt V2 book/test actions are not supported until they have a PyQt-free service owner.
- Wildcard file browser/editor actions are not supported in the headless runtime.
- Character Reference and Vibe Transfer are deferred because they need PyQt-free image storage, upload, and request-state services.
- E621 Event and Ollama desktop controls are retired from the supported headless runtime.

## Import Boundary

The fresh-process module-state test interacts with supported module states and retired module states, then asserts none of these are loaded:

- `PyQt6`
- `core.remote_api_server`
- `core.middle_section_controller`
- `modules.prompt_engineering_module`
- `modules.conditional_prompt_module`
- `modules.character_module`
- `modules.automation_module`

CDP validation also used an import audit hook while interacting with the browser panels. It recorded zero tracked imports for PyQt, desktop bridge/controller modules, and middle module wrappers.
