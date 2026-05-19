# Round 44 RemoteBridge migration notes

Generated: 2026-05-19

## Summary

Round 44 keeps `core.remote_api_server.RemoteBridge` as a legacy desktop-backed compatibility adapter only. The supported headless Remote Web server now owns parameter updates and active rating state directly through `WebSessionContext`.

## Headless-Owned Commands After This Round

- `sync`
- `set_option`
- `set_mode`
- `set_prompt`
- `set_param`
- `set_active_ratings`
- `probe_api`
- `verify_nai`
- `verify_webui`
- `verify_comfyui`
- `clear_api`
- `set_cloudflared_enabled`
- `get_search_state`
- `get_module_state`
- `random`
- `generate`

## Explicitly Retired Or Deferred In Headless

- `set_module_param`: deferred to Round 46 module-panel migration.
- `read_hires_preset_overlay` / `write_hires_preset_overlay`: desktop prompt-engineering sidecar behavior; headless now returns an explicit unavailable/retired response instead of depending on `RemoteBridge`.
- Search execution, autocomplete, tag lookup/filter, depth search, result enhance, and result image actions remain outside this round. They require dedicated service extraction or explicit retirement in later rounds.

## Evidence

- Fresh-process tests keep `core.remote_api_server`, `PyQt6`, desktop tab/module controllers, and desktop windows out of the supported headless path.
- CDP validation on port `7297` passed startup, Random, Generate dispatch, and import audit.
