# Round 46 - Prompt and Module Workflow Migration

## Plan Check

Round 46 follows Round 45 generation/result parity. The goal is to remove supported Remote Web dependence on PyQt middle modules, without deleting desktop files before their workflows are classified.

## TODO Checklist

- [x] Move Prompt Engineering panel state and edits to `WebSessionContext` and `core.prompt_engineering_settings`.
- [x] Move Conditional Prompt panel state and edits to `WebSessionContext` and `core.conditional_prompt_settings`.
- [x] Move Character panel state and edits to `WebSessionContext` and `core.character_settings`.
- [x] Move Automation settings state to `WebSessionContext` and `core.automation_settings`.
- [x] Move WEBUI Hiresfix Assist state to server-owned headless state.
- [x] Keep Wildcard headless support limited to prompt squeeze and read-only count.
- [x] Mark image-backed or desktop-process-backed module surfaces as retired/deferred in headless.
- [x] Add a fresh-process import audit test for supported module state interactions.
- [x] Validate supported module panel interactions through CDP.

## Migration Decisions

| Module ID | Decision | Headless Owner | Notes |
| --- | --- | --- | --- |
| `prompt_engineering` | migrated | `WebSessionContext` + prompt engineering store | Pre/post/auto-hide, preprocessing, presets, randomized list, e621 and Danbooru settings are service-owned. |
| `conditional_prompt` | migrated | `WebSessionContext` + conditional prompt store | Enable, mode, rules, and engine options are service-owned. V2 book/test actions are retired for headless. |
| `character` | migrated | `WebSessionContext` + character settings | Add/remove/toggle/prompt/UC/slot-name/slot-state are service-owned. Desktop character editor windows remain legacy. |
| `automation` | partial migration | `WebSessionContext` + automation settings | Settings are service-owned. Start/stop execution is retired until a PyQt-free scheduler exists. |
| `webui_hiresfix_assist` | migrated | `WebSessionContext` | Enabled/target state also updates generation params. |
| `wildcard` | partial migration | `WebSessionContext` | Prompt squeeze and count are supported. File browser/editor actions are retired. |
| `character_reference` | deferred | retired module state | Requires PyQt-free image storage/upload service before support. |
| `vibe_transfer` | deferred | retired module state | Requires PyQt-free image storage/upload service before support. |
| `instant_wildcard` | deferred | retired module state | Editing is not part of supported headless runtime this round. |
| `wildcard_status` | retired | retired module state | Desktop wrapper is no longer supported. |
| `e621_event` | retired | retired module state | Desktop event browser module is not supported in headless. |
| `ollama` | retired | retired module state | Desktop assistant controls are not supported in headless. |

## Validation

- `python -m py_compile core\web_session_context.py core\web_session_app.py tests\test_web_session_app.py`
- `python -m pytest tests\test_web_session_app.py tests\test_requirements_split.py tests\test_web_shell_config.py -q`
- `git diff --check`
- CDP module-panel scenario on `http://127.0.0.1:7303/`

## When Done

- Supported module panels can be opened and changed in the browser without importing `modules/*_module.py`.
- Retired/deferred module panels return explicit unavailable state instead of waking desktop loaders.
- Fresh-process tests fail if supported module state interactions import PyQt, `RemoteBridge`, middle controllers, or desktop middle modules.
- CDP proves Prompt Engineering, Conditional Prompt, Character, Automation settings, and WEBUI Hiresfix Assist work through the headless browser path.
