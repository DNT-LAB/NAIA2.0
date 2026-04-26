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

## Cleanup Round 2

Implemented in this round:

- Cached `ui.theme` style dictionaries and message-box QSS so repeated `get_dynamic_styles()` calls no longer rebuild large strings.
- Simplified main-window style initialization to use the cached base style instead of constructing a per-startup dynamic QSS block.
- Removed a duplicate prompt editor `setStyleSheet()` call during main UI initialization.
- Removed an unreachable Comic Generator turbo branch and its hidden button setup.

## Cleanup Round 3

Implemented in this round:

- Removed decorative `QGraphicsDropShadowEffect` usage from interactive draggable panels and image planes.
- Removed stale commented shadow setup from the floating control bar.

## Cleanup Round 4

Implemented in this round:

- Changed `TabController` startup discovery so heavy core tabs can be represented by lightweight placeholders and imported only when selected.
- Deferred startup imports for Danbooru WebEngine, PNG Info, Thumb, Artists, Studio, and dynamic/closable tab modules.
- Removed unconditional WebEngine module preloading from startup; WebEngine is now imported by web tabs only when needed.
- Kept Image Viewer and Settings eager because generation display and Web Session autostart depend on them during startup.
- Added regression tests for lazy core tab startup and dynamic tab import-on-request behavior.

## Cleanup Round 5

Implemented in this round:

- Removed forced Qt/Windows HiDPI environment overrides from desktop startup:
  - `QT_AUTO_SCREEN_SCALE_FACTOR`
  - `QT_ENABLE_HIGHDPI_SCALING`
  - `QT_SCALE_FACTOR_ROUNDING_POLICY`
- Kept `ui/scaling_manager.py` only as a legacy fixed-size helper for existing PyQt widgets; it no longer represents a DPI compatibility layer.
- Added a regression test to prevent reintroducing Qt DPI environment overrides or legacy high-DPI API calls in `NAIA_cold_v4.py`.

## IA Round 1

Implemented in this round:

- Added `docs/gui_information_architecture.md` as the baseline Desktop GUI information architecture.
- Documented the current Control Surface / Result Workspace model, state groups, action groups, renderer mapping, and mobile Remote implications.
- Established that PyQt detach behavior, QSS tokens, fixed sizes, and DPI compatibility assumptions are renderer details, not core IA requirements.

## Follow-Up Audit Items

- Map remaining core desktop tabs to the Web Shell information architecture.
- Define the Web bridge contract for prompt, params, generation, image viewer, history, and settings.
- Decide whether existing NAIA-REMOTE code is shared directly or forked into a Desktop Web Shell package.
