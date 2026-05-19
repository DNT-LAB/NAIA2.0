# Round 45 Generation and result parity

Generated: 2026-05-19

## Objective

Move supported generation result handling away from desktop controllers and make the headless Remote Web server own result history, unsaved result persistence, and explicit retirement of desktop-only result actions.

## TODO Checklist

- [x] Decide backend support scope for headless runtime.
- [x] Keep NAI, WEBUI, and COMFYUI as supported headless request/execution contracts through `HeadlessGenerationService` and `APIService`.
- [x] Validate NAI, WEBUI, and COMFYUI queue execution with PyQt-free fake API services.
- [x] Migrate save-directory state into `WebSessionContext`.
- [x] Migrate auto-save state and unsaved history count into `WebSessionContext`.
- [x] Add headless unsaved history ZIP download endpoint.
- [x] Add headless unsaved history save-all endpoint.
- [x] Preserve saved filepath in headless history summaries after save-all.
- [x] Explicitly retire result enhance/upscale in the headless websocket contract.
- [x] Explicitly retire desktop img2img/inpaint result actions in the headless websocket contract.
- [x] Add tests for supported backend execution, result download, save-all, and retired desktop actions.
- [x] Run CDP validation for startup, Random, Generate dispatch, and import audit.

## Backend Decision

NAI, WEBUI, and COMFYUI remain supported headless backend modes. The headless server normalizes each request, queues it, calls the PyQt-free `APIService` boundary, and stores the returned image in `HeadlessResultStore`.

This round validates the full headless server path with fake API services because the local validation environment does not provide live WEBUI or COMFYUI servers. Live external backend validation remains an environment acceptance gate, not a desktop dependency.

## Migrated

- `get_module_state:auto_save`
- `get_module_state:save_directory`
- `set_module_param:auto_save`
- `set_module_param:save_directory`
- `POST /api/history/unsaved/save-all`
- `GET /api/history/unsaved/download`

## Retired In Headless

- `result_upscale`
- `result_enhance`
- `result_image_action` for desktop img2img/inpaint handoff
- `/api/result/open-location`
- `/api/result/action/reroll`
- `/api/result/action/queue`
- `/api/result/action/save`
- `/api/result/action/delete`
- `/api/image-action/{action}`

## Validation

- `python -m py_compile core\web_session_app.py core\web_session_context.py core\headless_result_service.py tests\test_web_session_app.py`
- `python -m pytest tests\test_web_session_app.py -q`
- `python -m pytest tests\test_requirements_split.py tests\test_web_shell_config.py -q`
- `git diff --check`
- `python tools\measure_web_session_startup.py --entrypoint headless --port 7298 --cdp-port 9398 --include-generate --startup-timeout 90 --browser-timeout 90 --action-timeout 45 --output-json logs\round45_generation_result_validation.json --write-summary refactor_docs\round_45_generation_result_parity_validation.md`

## When Done

- Supported backend generation requests complete without `MainController`, `GenerationController`, `ImageWindow`, or `RemoteBridge`.
- Result preview/history/download/save-all state is owned by the headless server.
- Desktop-only result actions fail explicitly instead of silently depending on removed UI.
- CDP import audit reports no PyQt6, RemoteBridge, desktop window, image window, middle controller, or middle module imports.
