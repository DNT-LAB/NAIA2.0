# future01 GUI Migration Audit

Date: 2026-04-26

## Decision

NAIA Desktop is moving toward a hybrid Web Shell direction: PyQt remains the backend host for AppContext, generation, token, file, and API services while the modern UI surface moves to HTML/CSS/JS.

The first cleanup target on `future01` is removal of legacy desktop features that increase maintenance cost during the migration:

- Hooker
- Storyteller
- Assets / Sketchbook
- User-facing UI Scaling settings

## Removal Round 1

Implemented in this round:

- Blocked removed core tabs at `core/tab_controller.py`.
- Removed active Assets image propagation from `NAIA_cold_v4.py` and `ui/right_view.py`.
- Removed Sketchbook handoff references from `tabs/image_window.py`.
- Removed removed tabs from Settings tab visibility management.
- Removed Settings UI for manual UI Scaling.
- Replaced `ui/scaling_manager.py` with a fixed 1.0 compatibility shim so existing widget calls keep working without DPI/user scaling behavior.
- Deleted removed feature source trees:
  - `tabs/hooker*`
  - `ui/hooker*`
  - `tabs/storyteller*`
  - `tabs/assets*`
  - `ui/scaling_settings_dialog.py`
  - `UI_SCALING_GUIDE.md`

## Kept Compatibility

`ui/scaling_manager.py` remains only as an API compatibility utility because most PyQt widgets still call `get_scaled_size()` and `get_scaled_font_size()`. It no longer reads or writes scaling settings and always returns the original size at a fixed `1.0` factor.

The `sketchbook_character_prompts` generation parameter remains because it is also used by non-Assets flows such as character asset variation and img2img/inpaint overrides.

## Follow-Up Audit Items

- Map remaining core desktop tabs to the Web Shell information architecture.
- Define the Web bridge contract for prompt, params, generation, image viewer, history, and settings.
- Decide whether existing NAIA-REMOTE code is shared directly or forked into a Desktop Web Shell package.
