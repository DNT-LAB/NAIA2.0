# RemoteBridge features retired or deferred for headless Web Session

Generated: 2026-05-19

These features remain desktop-backed in `core.remote_api_server.RemoteBridge` or PyQt middle modules and are not part of the supported headless Remote Web runtime unless a later round extracts a PyQt-free service.

## Deferred To Later Migration

- Prompt Engineering Hires preset overlay read/write sidecars.
- Search execution, autocomplete, tag lookup/filter, and depth search.
- Character Reference and Vibe Transfer image module controls.
- Instant Wildcard editing and Wildcard Status desktop wrapper.
- Conditional Prompt V2 book/test actions.
- Automation start/stop execution.
- Result enhance/upscale and desktop image-action surfaces.
- Desktop folder/browser/clipboard actions.

## Current Headless Behavior

- `read_hires_preset_overlay` returns `available: false`.
- `write_hires_preset_overlay` returns an informational retired-command toast.
- `set_module_param:auto_save` and `set_module_param:save_directory` are supported by `WebSessionContext`.
- `set_module_param:prompt_engineering`, `conditional_prompt`, `character`, `automation` settings, `webui_hiresfix_assist`, and limited `wildcard` state are supported by `WebSessionContext`.
- `get_module_state` for `character_reference`, `vibe_transfer`, `instant_wildcard`, `wildcard_status`, `e621_event`, and `ollama` returns explicit `available: false` retired/deferred headless state.
- Unsupported `set_module_param` targets return an informational retired-command toast or retired module state.
- `result_upscale`, `result_enhance`, and `result_image_action` return explicit headless retired/unavailable responses.
