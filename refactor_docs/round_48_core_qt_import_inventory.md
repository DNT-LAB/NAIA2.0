# Round 48 core Qt import inventory

Generated: 2026-05-19

## Supported Headless Core Imports

These modules are allowed in the supported headless runtime and are now covered by a fresh-process import guard with `PyQt6` and legacy desktop controllers blocked:

- `core.web_session_app`
- `core.web_session_context`
- `core.api_config_service`
- `core.api_service`
- `core.headless_random_prompt_service`
- `core.headless_generation_service`
- `core.headless_result_service`
- `core.style_thumbnail_service`
- `core.character_viewer_service`
- `core.prompt_generation_service`
- `core.prompt_engineering_runtime`
- `core.conditional_prompt_runtime`
- `core.reference_inset_service`
- `core.wildcard_manager`
- `core.filter_data_manager`

## Legacy Desktop Core Imports

These `core/` modules still import PyQt and must stay outside the supported headless import graph until they are split, archived, or moved to a legacy desktop package:

- `core.api_validator`
- `core.autocomplete_manager`
- `core.comfyui_utils`
- `core.generation_controller`
- `core.main_controller`
- `core.middle_section_controller`
- `core.ollama_service`
- `core.prompt_generation_controller`
- `core.remote_api_server`
- `core.search_controller`
- `core.tab_controller`
- `core.temp_window_manager`
- `core.ui_state_manager`

## Notes

- `core.api_service` has lazy Qt image-conversion fallback imports inside specific methods, but the supported headless import path does not import Qt at module import time.
- `core.prompt_generation_service` is the supported PyQt-free prompt generation service; `core.prompt_generation_controller` remains desktop legacy.
- `core.character_viewer_service` and `core.style_thumbnail_service` were added to the supported import set in Round 47.
