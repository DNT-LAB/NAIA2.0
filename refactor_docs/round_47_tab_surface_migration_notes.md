# Round 47 tab surface migration notes

## What Changed

- Added `core.style_thumbnail_service.StyleThumbnailService` for the Remote Web Thumb tab.
- Added headless `/api/thumb/*` endpoints to `core.web_session_app`.
- Wired `core.character_viewer_service.CharacterViewerService` into headless `/api/character-viewer/*` endpoints.
- Added `/api/headless/capabilities` so the browser can hide tabs that are not supported in the headless runtime.
- Updated the right-tab controller so tab availability can be changed dynamically without affecting the legacy desktop-backed RemoteBridge path.

## Supported Headless Tabs

- `result`: current image, latest image, history, thumbnails, PNG export, unsaved download/save-all.
- `pngInfo`: result metadata viewer using headless result metadata endpoints.
- `thumb`: style thumbnail category/list/image endpoints.
- `characters`: Character Viewer state, groups, list, detail, prompt, options, thumbnail, and generation queue dispatch.
- `studio`: web-native frame state and headless generation queue dispatch.

## Deferred Or Retired Tabs

- `artists` is hidden in headless through `/api/headless/capabilities` because Artist Thumbnail remains heavily RemoteBridge-backed.
- `tabs.artist_thumb_tab.py` remains desktop legacy until an Artist Thumbnail service is extracted.
- `tabs.web_view.py`, `tabs.simple_web_view.py`, and desktop Danbooru browser windows are retired for headless.
- `tabs.img2img_tab.py`, `tabs.depth_search_window.py`, `tabs.turbo_event_sequence_tab.py`, and `tabs.comic_generator_tab.py` are not part of the supported headless runtime.
- `tabs.setting_tabs.py` is replaced by Remote Web API setup and server-owned module state where supported.

## Import Boundary

CDP validation used an import audit while opening Thumb and Characters. It reported no imports for:

- `PyQt6`
- `core.remote_api_server`
- `core.tab_controller`
- `tabs`

The supported headless server still serves the static Remote Web assets, but it does not scan or instantiate PyQt tab modules.
