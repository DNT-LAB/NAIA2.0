# Round 37 RemoteBridge event contract

## Scope

`RemoteBridge(QObject)` remains the compatibility adapter for the desktop-backed WebShell. The headless FastAPI path must not construct it. Server-owned Remote Web state now comes from `WebSessionContext`, `ApiConfigService`, `HeadlessRandomPromptService`, `HeadlessGenerationService`, `HeadlessResultStore`, and `core.web_session_app`.

## Event inventory from `core/remote_api_server.py`

Unique websocket `type` values found in the desktop bridge:

`anlas_update`, `api_config_result`, `api_status`, `api_test_result`, `autocomplete_result`, `character_viewer_error`, `clear_api_result`, `comfyui_workflow_state`, `depth_state`, `desktop_window_state`, `event_preset_generation_error`, `file`, `filter_reset`, `folder`, `hires_preset_overlay`, `image_meta`, `init_complete`, `lazy_indices_ready`, `mode`, `mode_result`, `module_state`, `options`, `params`, `preset_generation_error`, `probe_result`, `prompt_engineering_preset_thumbnail_updated`, `prompt_generated`, `prompt_sync`, `prompt_tokens`, `queue_state`, `random_failed`, `rating_update`, `result_enhance_config`, `result_enhance_state`, `result_upscale_state`, `search_progress`, `search_state`, `session`, `setup_blocked`, `status`, `storage_list`, `tag_filter_ac_result`, `tag_filter_assigned`, `tag_filter_result`, `tag_lookup_result`, `tag_search_result`, `toast`, `verify_result`, `viewer_history_cleared`, `viewer_history_removed`, `viewer_new_image`, `wildcard_manager`.

## Headless-owned now

- Startup/session: `session`, `desktop_window_state`, `mode`, `options`, `params`, `queue_state`, `api_status`, `init_complete`, `lazy_indices_ready`.
- API setup: `verify_result`, `clear_api_result`, `probe_result`, `setup_blocked`, `api_status`, `toast`.
- Random prompt: `prompt_generated`, `random_failed`.
- Generate/result: `generation_dispatched`, `status`, `queue_state`, `image_meta`, binary WebP frame, `viewer_new_image`.
- Result endpoints: `/api/latest-image`, `/api/result/image/png`, `/api/result/metadata`, `/api/history/list`, `/api/history/image/{history_id}`, `/api/history/thumb/{history_id}`, `/api/history/meta/{history_id}`.
- Placeholder-but-explicit: `search_state`, `module_state`, `lazy_indices_ready`.

## Desktop adapter only for now

These still depend on desktop modules, tabs, clipboard, filesystem viewers, or specialized UI adapters and should remain desktop-only until extracted behind dedicated services:

- Search and tag tools: `search_progress`, `rating_update`, `filter_reset`, `tag_search_result`, `tag_lookup_result`, `autocomplete_result`, `tag_filter_result`, `tag_filter_assigned`, `tag_filter_ac_result`, `wildcard_manager`.
- Optional modules: `depth_state`, `hires_preset_overlay`, `prompt_engineering_preset_thumbnail_updated`, `character_viewer_error`, `comfyui_workflow_state`, `storage_list`, `file`, `folder`.
- Result tools not yet moved: `result_enhance_state`, `result_enhance_config`, `result_upscale_state`, `viewer_history_removed`, `viewer_history_cleared`.
- Preset generation errors: `event_preset_generation_error`, `preset_generation_error`.
- Legacy aliases: `api_config_result`, `api_test_result`, `mode_result`, `prompt_tokens`.

## Boundary

The headless path now covers the core Remote Web workflow: API setup, Random, Generate, latest result, PNG export, and in-memory history. `RemoteBridge` should not be imported or constructed by `NAIA_web_headless.py`; desktop signal relay stays in the existing desktop WebShell path until each optional module is extracted.
