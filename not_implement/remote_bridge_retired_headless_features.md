# RemoteBridge features retired or deferred for headless Web Session

Generated: 2026-05-19

These features remain desktop-backed in `core.remote_api_server.RemoteBridge` and are not part of the supported headless Remote Web runtime unless a later round extracts a PyQt-free service.

## Deferred To Later Migration

- Module panel mutations through `set_module_param`.
- Prompt Engineering Hires preset overlay read/write sidecars.
- Search execution, autocomplete, tag lookup/filter, and depth search.
- Result enhance/upscale and desktop image-action surfaces.
- Desktop folder/browser/clipboard actions.

## Current Headless Behavior

- `read_hires_preset_overlay` returns `available: false`.
- `write_hires_preset_overlay` returns an informational retired-command toast.
- `set_module_param` returns an informational retired-command toast.
