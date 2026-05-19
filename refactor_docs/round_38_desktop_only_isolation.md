# Round 38 desktop-only isolation

## Goal

Headless Remote Web startup must not scan or import PyQt desktop tabs/modules. Desktop-only surfaces remain available through the desktop app, but they are outside the headless server contract until a web-native service boundary exists.

## Classification

### web-core

These are allowed in the headless entrypoint and are import-tested without `PyQt6`:

- `core.web_session_app`
- `core.web_session_context`
- `core.api_config_service`
- `core.headless_random_prompt_service`
- `core.headless_generation_service`
- `core.headless_result_service`
- `core.prompt_generation_service`
- `core.prompt_engineering_runtime`
- `core.conditional_prompt_runtime`
- `core.reference_inset_service`
- `core.wildcard_manager`
- `core.filter_data_manager`

### web-optional

These are only allowed through extracted core/headless runtimes or explicit lazy service boundaries. They are not allowed during headless startup:

- `modules.prompt_engineering_module`
- `modules.conditional_prompt_module`
- `modules.reference_inset_module`
- `modules.instant_wildcard_module`
- `modules.character_module`
- `modules.character_reference_module`
- `modules.vibe_transfer_module`
- `modules.e621_event_module`
- `modules.wildcard_status_module`
- `modules.automation_module`
- `modules.ollama_module`

### desktop-only

These remain in the desktop app and are documented under `not_implement/` for Web Session:

- `tabs.turbo_event_sequence_tab`
- `tabs.studio_tab`
- `tabs.comic_generator_tab`
- `tabs.depth_search_window`
- `tabs.img2img_tab`
- `tabs.simple_web_view`
- `tabs.web_view`
- `tabs.image_window`
- `tabs.setting_tabs`
- `tabs.thumbnails_tab`
- `tabs.artist_thumb_tab`
- `tabs.png_info_tab`
- `tabs.api_management_window`

## Conditional Prompt follow-up

The headless conditional hook now uses `core.conditional_prompt_runtime` and `core.conditional_prompt_settings`. This covers enabled rule execution from saved settings without importing `modules.conditional_prompt_module` in the headless startup path. The desktop editor actions and preset management remain desktop-adapter/optional until their parser/serializer calls are fully service-owned.

## Verification contract

Round 38 adds an import audit that starts the headless app, performs websocket startup, Random, and fake Generate result broadcast, and asserts these modules are absent from `sys.modules`:

- `PyQt6`
- `core.remote_api_server`
- `core.middle_section_controller`
- `core.tab_controller`
- `modules.character_module`
- `modules.prompt_engineering_module`
- `modules.conditional_prompt_module`
- `tabs.turbo_event_sequence_tab`
- `tabs.studio_tab`
- `tabs.image_window`
- `tabs.setting_tabs`
