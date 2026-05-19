# WebSession Unsupported PyQt Tabs

These desktop PyQt surfaces are outside the Remote Web Session contract and must stay out of WebSession startup/import paths.

## Runtime blocked

- `TurboEventSequenceTabModule`
  - Desktop entrypoint remains for now.
  - Hidden WebSession runtime blocks dynamic import/creation through `TabController`.
  - Direct Turbo dialog selection also no-ops in hidden WebSession runtime.
- `StudioTab`
  - Desktop tab remains available in the PyQt app.
  - Headless Remote Web does not import the tab; future Studio parity requires a separate web-native queue/storyboard service.
- `DepthSearchTabModule`, `Img2ImgTabModule`, `SimpleWebViewTabModule`, `APIManagementTabModule`
  - These are desktop/dynamic PyQt surfaces in the current app.
  - Headless Remote Web exposes only the core server contracts that replaced them where available: API setup, latest result, PNG export, and in-memory history.

## Removed guards

- `HookerTabModule`
- `StorytellerTabModule`
- `AssetsTabModule`

These modules are treated as not implemented for the current Remote Web Session surface unless a future web-native feature contract is added.

## Module classification for headless migration

### web-core

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

### web-optional behind service boundaries

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

These modules must not be imported during headless startup. Only extracted core runtimes or explicit lazy service calls may participate in Remote Web.

### desktop-only until extracted

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

The headless entrypoint must not scan or import these files.
