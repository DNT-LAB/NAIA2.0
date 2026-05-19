# Desktop App decommission roadmap

## Goal

Remove the PyQt Desktop App from the supported NAIA Remote Web runtime.

The previous Headless Web Session roadmap proved that the core Remote Web workflow can run through `NAIA_web_headless.py` without constructing the desktop UI. This roadmap covers the remaining work required before the project can say that the Desktop App has been removed rather than merely bypassed.

## Completion Definition

Desktop App decommission is complete only when all of these are true:

- Supported launch scripts start the headless Remote Web runtime by default.
- Supported runtime dependencies do not include `PyQt6`, `PyQt6-WebEngine`, `PyQt6-QScintilla`, or Qt-only helper packages.
- `NAIA_cold_v4.py` is removed, archived, or explicitly moved to an unsupported legacy package.
- `core.remote_api_server.RemoteBridge`, `core.middle_section_controller.MiddleSectionController`, `core.tab_controller.TabController`, `core.main_controller.MainController`, and PyQt tab/module wrappers are not part of the supported runtime import graph.
- Every current Desktop-only workflow is explicitly classified as migrated, retired, archived, or kept in a separate optional desktop package.
- CDP validates Remote Web startup, API setup, Random, Generate, result display, history, and every supported optional workflow without Desktop App fallback.

## Rules

- Do not delete a Desktop surface until its user-visible workflow has a decision: migrate, retire, archive, or split.
- Do not remove generated dictionaries or core data files just because they are large.
- Each round must keep `NAIA_web_headless.py` runnable.
- Each round that changes visible Remote Web behavior must include CDP validation.
- Each round that changes launch/runtime boundaries must include a fresh-process import audit for `PyQt6` and desktop modules.
- Commits should stay round-scoped.

## Round 41 - Desktop Dependency Inventory and Decision Matrix

### Purpose

Build the authoritative inventory of Desktop App dependencies and assign an owner decision to every PyQt surface before deletion starts.

### TODO Checklist

- [x] List all supported entrypoints and launch scripts:
  - `NAIA_cold_v4.py`
  - `NAIA_web_headless.py`
  - `run_NAIA.bat`
  - `run_NAIA_web.bat`
  - `.command` launchers
- [x] List all runtime requirements that exist only for Desktop App support.
- [x] Generate a PyQt import inventory for `core/`, `modules/`, `tabs/`, `ui/`, `tools/`, and `tests/`.
- [x] Build a workflow matrix with columns: workflow, current owner, Remote Web replacement, decision, blocker, validation.
- [x] Classify every tab in `TAB_MODULE_SPECS`.
- [x] Classify every middle module in `MIDDLE_MODULE_SPECS`.
- [x] Classify every RemoteBridge websocket/API feature as headless-owned, migrate, retire, or legacy-only.
- [x] Save the inventory under `refactor_docs/`.

### Round 41 Result

- Inventory: `refactor_docs/round_41_desktop_dependency_inventory.md`.
- Decision: Round 42 should make `NAIA_web_headless.py` the default Web launch path and mark `NAIA_cold_v4.py` as explicit legacy.
- Decision: deletion/archive waits until RemoteBridge, generation/result, module, tab, and shared-core Qt surfaces are migrated or retired.

### When Done

- A single document lists every remaining Desktop App dependency and its decision.
- No Desktop file can be removed later without a matching inventory row.
- The next round can change launcher behavior without guessing which workflows still need Desktop fallback.

## Round 42 - Default Launch Contract Cutover

### Purpose

Make the supported Web Session launch path headless by default while keeping Desktop launch explicit and legacy.

### TODO Checklist

- [x] Update `run_NAIA_web.bat` and `run_NAIA_web.command` to launch `NAIA_web_headless.py`.
- [x] Keep `run_NAIA.bat` as explicit legacy desktop launch or rename/document it as legacy.
- [x] Update `core.web_shell_config` tests so default Web Session means headless, not desktop-backed shell.
- [x] Add a smoke command for `python NAIA_web_headless.py --port <port>`.
- [x] Add a guard that `--web-session` through `NAIA_cold_v4.py` is legacy-only or disabled.
- [x] Update docs that still instruct users to start Remote Web via `NAIA_cold_v4.py --web-session`.

### Round 42 Result

- Web launchers now start `NAIA_web_headless.py`.
- Legacy desktop launchers call `NAIA_cold_v4.py --desktop`.
- `NAIA_cold_v4.py --web-session` requires `--allow-legacy-web-session` and points users to `NAIA_web_headless.py`.
- CDP validation passed on port `7295`: first paint `2.344s`, Random prompt update `5.25s`, Generate dispatch `0.11s`.
- Import audit for the supported Web launch reported no `PyQt6`, `core.remote_api_server`, desktop window, image window, middle controller, or module imports.
- Validation doc: `refactor_docs/round_42_headless_launch_validation.md`.

### When Done

- Fresh users running the Web launch script start the headless server.
- Desktop launch is still possible only through an explicit legacy path.
- CDP can open the default Web launch URL and pass startup/API setup/Random/Generate dispatch checks.
- Import audit for the default Web launch shows no `PyQt6`, `core.remote_api_server`, `ModernMainWindow`, `ImageWindow`, `MiddleSectionController`, or `TabController`.

## Round 43 - Requirements and Packaging Split

### Purpose

Separate headless runtime dependencies from Desktop-only dependencies so PyQt is no longer required for supported Remote Web installs.

### TODO Checklist

- [x] Create a headless requirements file or split the existing `requirements.txt`.
- [x] Move `PyQt6`, `PyQt6-Qt6`, `PyQt6-WebEngine`, `PyQt6-WebEngine-Qt6`, `PyQt6_sip`, `PyQt6-QScintilla`, `pywinpty`, and desktop-only packages into an optional legacy requirements file if still needed.
- [x] Verify `NAIA_web_headless.py` starts in an environment conceptually limited to headless requirements.
- [x] Update launcher/install scripts to install headless requirements for Web Session.
- [x] Update test instructions to distinguish headless tests from legacy desktop tests.
- [x] Add a dependency audit test that fails if a supported headless import path requires PyQt.

### Round 43 Result

- `requirements-headless.txt` is now the supported Remote Web install set.
- `requirements.txt`, `requirements_mac.txt`, and `requirements_linux.txt` now delegate to `requirements-headless.txt`.
- Desktop-only dependencies moved to `requirements-desktop-legacy.txt`, `requirements-desktop-legacy-mac.txt`, and `requirements-desktop-legacy-linux.txt`.
- Web launchers install `requirements-headless.txt`; desktop launchers install legacy desktop requirements.
- Tests assert the headless requirements files do not include PyQt/WebEngine/QScintilla/pywinpty/desktop Windows integration/Turbo-only `ultralytics`.
- CDP validation passed on port `7296`: first paint `1.797s`, Random prompt update `6.438s`, Generate dispatch `0.094s`.
- Import audit again reported no PyQt, RemoteBridge, desktop window, image window, middle controller, or middle module imports.
- Validation doc: `refactor_docs/round_43_headless_requirements_validation.md`.

### When Done

- Headless Remote Web has its own install contract.
- Main Web Session setup does not install PyQt by default.
- Tests prove `core.web_session_app`, `NAIA_web_headless.py`, and core Remote Web services import without PyQt installed.
- Desktop-only dependency installation is explicitly legacy or optional.

## Round 44 - RemoteBridge Feature Migration

### Purpose

Remove remaining supported Web Session behavior from `core.remote_api_server.RemoteBridge` and move it into PyQt-free services or retire it.

### TODO Checklist

- [x] Compare `refactor_docs/round_37_remote_bridge_event_contract.md` with the current Remote Web UI feature set.
- [x] For each still-supported RemoteBridge endpoint/event, create or reuse a PyQt-free service.
- [x] Move server-owned state into `WebSessionContext` or dedicated service objects.
- [x] Remove direct Remote Web reliance on desktop widgets, desktop signals, and `_find_loaded_module_instance`.
- [x] Add tests for migrated websocket and REST contracts.
- [x] Mark retired RemoteBridge features as unsupported in `not_implement/` or decommission docs.

### Round 44 Result

- Migrated `set_param`, `set_active_ratings`, and `get_search_state` into `WebSessionContext`.
- Headless Random now uses server-owned active rating state if the browser command omits explicit ratings.
- Added explicit headless unavailable/retired responses for Hires overlay and module mutation commands.
- Documented deferred RemoteBridge features in `refactor_docs/round_44_remote_bridge_migration_notes.md` and `not_implement/remote_bridge_retired_headless_features.md`.
- CDP validation passed on port `7297`: first paint `2.188s`, Random prompt update `6.047s`, Generate dispatch `0.109s`.
- Import audit again reported no PyQt, RemoteBridge, desktop window, image window, middle controller, or middle module imports.
- Validation doc: `refactor_docs/round_44_headless_remote_bridge_migration_validation.md`.

### When Done

- Supported Remote Web behavior no longer needs `RemoteBridge`.
- Fresh-process tests cover startup, Random, Generate, result/history, API setup, and migrated optional contracts without importing `core.remote_api_server`.
- Any remaining `RemoteBridge` code is legacy-only and unreachable from supported headless launch.
- CDP validates the migrated Remote Web feature set.

## Round 45 - Generation and Result Parity Without Desktop Controllers

### Purpose

Finish all supported generation/result workflows without `MainController`, `GenerationController` Qt workers, `ImageWindow`, or desktop result tabs.

### TODO Checklist

- [x] Decide whether WEBUI and COMFYUI are supported in headless runtime or retired for this branch.
- [x] Validate WEBUI generation execution through the PyQt-free `APIService` boundary, not only request normalization.
- [x] Validate COMFYUI generation execution through the PyQt-free `APIService` boundary, not only request normalization.
- [x] Migrate save-directory state, auto-save, unsaved history, and result download endpoints to headless services.
- [x] Migrate or retire result enhance/upscale actions.
- [x] Migrate or retire img2img/inpaint/result-action flows that currently open desktop windows.
- [x] Add tests for each supported backend mode.

### Round 45 Result

- NAI, WEBUI, and COMFYUI remain supported headless backend modes.
- Headless generation execution now covers all three modes through the queue and `APIService` boundary without desktop controllers.
- `auto_save` and `save_directory` module state moved into `WebSessionContext`.
- Unsaved history ZIP download and save-all are now served by the headless FastAPI app.
- Saved headless history items now retain `file_path` after save-all.
- Result enhance/upscale, desktop img2img/inpaint handoff, open-location, reroll/queue replay, and desktop save/delete action endpoints now fail explicitly in headless mode.
- CDP validation passed on port `7298`: first paint `2.031s`, Random prompt update `6.641s`, Generate dispatch `0.094s`.
- Import audit reported no PyQt, RemoteBridge, desktop window, image window, middle controller, or middle module imports.
- Validation docs: `refactor_docs/round_45_generation_result_parity_validation.md`, `refactor_docs/round_45_generation_result_migration_notes.md`.

### When Done

- Every supported generation backend works through the headless server or is explicitly retired.
- Result preview, PNG export, history, save actions, and error recovery are server-owned.
- No supported generation/result path imports `core.main_controller`, `core.generation_controller` Qt worker objects, `tabs.image_window`, or desktop dialogs.
- CDP validates actual Generate button behavior for the supported headless server path; live WEBUI/COMFYUI external server validation remains an environment acceptance gate when those servers are available.

## Round 46 - Prompt and Module Workflow Migration

### Purpose

Remove supported Remote Web dependence on PyQt middle modules by replacing module wrappers with core services or retiring their web surfaces.

### TODO Checklist

- [x] For `PromptEngineeringModule`, keep runtime hooks in `core.prompt_engineering_runtime` and migrate/retire remaining editor actions.
- [x] For `PromptListModifierModule`, keep rule execution in `core.conditional_prompt_runtime` and migrate/retire editor/preset UI.
- [x] For `CharacterModule`, keep saved settings/headless params and migrate/retire desktop character editor actions.
- [x] For `CharacterReferenceModule`, migrate reference image storage/state to a PyQt-free service or retire the web controls.
- [x] For `VibeTransferModule`, migrate image storage/clipboard-independent request state or retire the web controls.
- [x] For `InstantWildcardModule` and `WildcardStatusModule`, keep PyQt-free services and retire desktop wrappers from supported web runtime.
- [x] For `AutomationModule`, `E621EventModuleV2`, and `OllamaModule`, decide migrate or retire.
- [x] Update Remote Web module panels to call services, not desktop module loaders.

### Round 46 Result

- `WebSessionContext` now owns supported headless module state for Prompt Engineering, Conditional Prompt, Character, Automation settings, WEBUI Hiresfix Assist, and limited Wildcard state.
- Supported module panel mutations use PyQt-free stores/services instead of `modules/*_module.py`.
- `character_reference`, `vibe_transfer`, `instant_wildcard`, `wildcard_status`, `e621_event`, and `ollama` return explicit retired/deferred headless module states.
- Automation settings are migrated, but Automation `start`/`stop` execution is retired until a PyQt-free scheduler exists.
- CDP validation passed on port `7303`: Prompt Engineering preprocessing toggle, Conditional Prompt enabled toggle, Character add slot, Automation timer setting, and WEBUI Hiresfix Assist state all updated through the browser.
- Import audit during CDP module-panel interaction reported no PyQt, RemoteBridge, desktop controller, image window, or middle module wrapper imports.
- Validation docs: `refactor_docs/round_46_module_panel_validation.md`, `refactor_docs/round_46_module_workflow_migration_notes.md`.

### When Done

- Supported Remote Web module panels do not instantiate `modules/*_module.py`.
- Headless import audit after module-panel interaction still shows no PyQt middle module imports.
- Each module has a documented decision and validation path.
- CDP validates all remaining supported module panels.

## Round 47 - Tab Surface Migration, Retirement, or Archive

### Purpose

Remove Desktop App tab surfaces from the supported runtime by moving useful behavior to web-native services and archiving or retiring the rest.

### TODO Checklist

- [x] Classify `tabs/studio*` and `ui/remote_web/js/features/studioTab.mjs` as migrate or retire.
- [x] Classify `tabs/turbo_event_sequence*` as migrate or retire.
- [x] Classify `tabs/artist_thumb_tab.py` against current Remote Web artist thumb services.
- [x] Classify `tabs/png_info_tab.py`, `tabs/thumbnails_tab.py`, and image metadata viewers.
- [x] Classify `tabs/img2img_tab.py`, `tabs/simple_web_view.py`, `tabs/web_view.py`, `tabs/depth_search_window.py`, and `tabs/comic_generator_tab.py`.
- [ ] Move retired desktop-only files to an archive/not-supported area or delete them if they are already replaced.
- [ ] Remove dynamic tab registry entries for retired surfaces.
- [x] Update tests that assert removed/unsupported tabs are not imported.

### Round 47 Result

- Added `core.style_thumbnail_service` and headless `/api/thumb/*` endpoints for the Remote Web Thumb tab.
- Wired `core.character_viewer_service` into headless `/api/character-viewer/*` endpoints.
- Added `/api/headless/capabilities` and dynamic right-tab availability handling so unsupported headless tabs can be hidden without changing legacy desktop-backed RemoteBridge.
- Artist Thumbnail remains deferred and hidden in headless because it is still RemoteBridge-backed.
- Studio remains web-native JS plus headless generation queue dispatch; the PyQt `tabs/studio_tab.py` surface remains legacy-only.
- Physical tab file moves/deletes and `core.tab_controller` registry removal are deferred to Round 49 because they are destructive legacy desktop-tree operations.
- CDP validation passed on port `7305`: `Artists` hidden, `Thumb` visible and loaded 9 cards, `Characters` visible and loaded 9 cards.
- Import audit during CDP reported no PyQt, RemoteBridge, TabController, or `tabs/*` imports.
- Validation docs: `refactor_docs/round_47_tab_surface_validation.md`, `refactor_docs/round_47_tab_surface_migration_notes.md`.

### When Done

- Supported headless runtime does not include any `tabs/*` PyQt surface.
- Retired tabs are documented and no longer advertised in Remote Web.
- Migrated tab behavior has service/API tests and CDP coverage.
- `core.tab_controller` is legacy-only or removed from the supported tree.

## Round 48 - Core Qt Import Decoupling

### Purpose

Remove Qt imports from shared `core/` modules that remain in the supported headless runtime.

### TODO Checklist

- [x] Audit every `core/*.py` `PyQt6` import.
- [ ] Split Qt worker/signal code from shared services:
  - `core.generation_controller`
  - `core.prompt_generation_controller`
  - `core.api_validator`
  - `core.search_controller`
  - `core.ui_state_manager`
  - `core.autocomplete_manager`
  - `core.temp_window_manager`
- [ ] Replace Qt signals with service events for supported headless paths.
- [ ] Keep any remaining Qt classes inside legacy desktop-only modules.
- [x] Add fresh-process import tests for all supported `core` services.

### Round 48 Result

- Documented supported headless core imports and legacy desktop core imports in `refactor_docs/round_48_core_qt_import_inventory.md`.
- Added a fresh-process import guard that blocks `PyQt6`, `core.remote_api_server`, `core.middle_section_controller`, `core.tab_controller`, `core.main_controller`, `core.generation_controller`, `core.prompt_generation_controller`, `core.search_controller`, `core.autocomplete_manager`, `core.ui_state_manager`, `core.temp_window_manager`, and `NAIA_cold_v4` while importing supported headless core services.
- CDP startup/random validation passed on port `7306`; import audit again reported no PyQt, RemoteBridge, middle controller, or middle module imports.
- Physical split/archive of Qt worker/signal modules remains deferred to Round 49 because it is a destructive desktop-tree operation.
- Validation docs: `refactor_docs/round_48_core_import_contract_validation.md`, `refactor_docs/round_48_core_qt_import_inventory.md`.

### When Done

- Supported `core` service imports do not import `PyQt6`.
- Qt-dependent controllers are either deleted, archived, or marked legacy desktop-only.
- Headless tests fail if shared core services regress by importing Qt.
- Generation, prompt, API setup, search, result, and history services remain functional.

## Round 49 - Desktop Legacy Package or Archive

### Purpose

Physically remove Desktop App files from the supported runtime tree, or move them into a clearly unsupported legacy package.

### TODO Checklist

- [x] Choose one strategy: delete, `legacy_desktop/`, or `not_implement/desktop_archive/`.
- [x] Move or delete `NAIA_cold_v4.py`.
- [x] Move or delete `core.remote_api_server.py` if all supported features are migrated.
- [x] Move or delete `core.middle_section_controller.py`, `core.tab_controller.py`, `core.main_controller.py`, and desktop-only controllers.
- [x] Move or delete PyQt-only `tabs/` and `modules/` files that are not part of a separate package.
- [x] Extract headless Event Preset helpers out of `ui/` before the UI wrapper archive.
- [x] Extract headless Clothes/Expression Preset assets out of `ui/` before the UI wrapper archive.
- [x] Move or delete remaining PyQt-only `ui/` files that are not part of a separate package.
- [x] Update imports and tests after the move.
- [x] Update docs so Desktop App is no longer presented as supported.

### Round 49A Result

- Selected the non-destructive `legacy_desktop/` archive strategy.
- Moved the root Desktop entrypoint to `legacy_desktop/NAIA_cold_v4.py`.
- Moved the legacy Desktop-backed RemoteBridge server to `legacy_desktop/core/remote_api_server.py`.
- Updated legacy desktop launchers and desktop comparison tooling to point at the archived path.
- Added headless import guards for the `legacy_desktop` package.
- Notes: `refactor_docs/round_49_desktop_legacy_archive_notes.md`.
- Plan: `refactor_plans/round_49_desktop_legacy_archive.md`.
- Deferred: remaining PyQt tab/module wrappers need a broader package move or explicit retirement of the legacy desktop launcher.

### Round 49B Result

- Moved desktop-only `core` controllers and helpers to `legacy_desktop/core/`.
- Updated legacy desktop imports, PyQt wrapper imports, and legacy tests to point at archived controller paths.
- Headless import guards still block `legacy_desktop`, `PyQt6`, and old Desktop controller names.
- CDP validation passed on port `7309`: first paint `1.86s`, Random prompt update `6.547s`, Generate dispatch `0.109s`; import audit reported `pyqt6_imported=False`, `legacy_desktop_imported=False`, and `remote_api_server_imported=False`.
- Validation doc: `refactor_docs/round_49_core_controller_archive_validation.md`.

### Round 49C Result

- Moved tracked PyQt middle module wrappers from `modules/` to `legacy_desktop/modules/`.
- Updated legacy imports and tests from `modules.*` to `legacy_desktop.modules.*`.
- Root `modules/` has no tracked Python files remaining.
- CDP validation passed on port `7310`: first paint `2.11s`, Random prompt update `6.36s`, Generate dispatch `0.094s`; import audit reported `pyqt6_imported=False`, `legacy_desktop_imported=False`, `remote_api_server_imported=False`, and `middle_module_imports_count=0`.
- Validation doc: `refactor_docs/round_49_modules_archive_validation.md`.

### Round 49D Result

- Moved tracked PyQt tab wrappers from `tabs/` to `legacy_desktop/tabs/`.
- Updated legacy imports from `tabs.*` to `legacy_desktop.tabs.*`.
- Root `tabs/` has no tracked files remaining.
- CDP validation passed on port `7311`: first paint `2.218s`, Random prompt update `7.578s`, Generate dispatch `0.094s`; import audit reported `pyqt6_imported=False`, `legacy_desktop_imported=False`, `remote_api_server_imported=False`, and `middle_module_imports_count=0`.
- Validation doc: `refactor_docs/round_49_tabs_archive_validation.md`.

### Round 49E Result

- Moved server-used Event Preset data/engine code from `ui/` into `core/event_preset/`.
- Updated `core.event_preset_service`, `core.preset_composer_service`, and remaining PyQt UI callers to import the extracted core helpers.
- Preserved compatibility with the existing local `ui/event_preset/naia_prompt_preset` ZIP while preferring the future `data/event_preset/naia_prompt_preset` data location.
- Deferred: archive the remaining PyQt `ui/` wrappers after this dependency split is validated.

### Round 49F Result

- Moved server-used Clothes Preset data/engine code and bundled package into `core/clothes_preset/`.
- Moved the Expression Preset JSON catalog into `core/expression_preset/`.
- Updated Clothes and Expression server services to read from `core/` instead of `ui/`.
- Updated the remaining PyQt Clothes window/widget imports to use the extracted core helpers.
- Deferred: archive remaining PyQt-only `ui/` wrappers while preserving `ui/remote_web` static assets.

### Round 49G Result

- Moved all tracked PyQt UI wrappers and desktop UI assets from `ui/` into `legacy_desktop/ui/`.
- Preserved `ui/remote_web/**` at the root as the supported headless static web client.
- Updated legacy desktop, legacy modules, legacy tabs, and the desktop theme cache test to import `legacy_desktop.ui.*`.
- Root `ui/` tracked files now consist only of `ui/remote_web` assets.

### When Done

- Supported runtime tree no longer exposes Desktop App entrypoints.
- `python NAIA_web_headless.py` still starts and passes core workflows.
- Import audit confirms supported runtime imports no Desktop App package.
- Any retained desktop code is clearly outside supported runtime and not imported by default.

## Round 50 - Final Requirements, Launcher, and Documentation Cleanup

### Purpose

Make the repository's install and launch story match the decommissioned runtime.

### TODO Checklist

- [x] Remove Desktop App instructions from primary README/docs or move them to legacy notes.
- [x] Remove PyQt dependencies from default requirements.
- [x] Update launch scripts and command docs.
- [x] Update `AGENTS.md` if validation/startup instructions still mention desktop-backed launch as default.
- [x] Update measurement tooling so `headless` is the default and `desktop` is legacy-only if retained.
- [x] Remove stale docs that claim desktop compatibility is part of the main path.

### When Done

- A fresh setup path installs and starts the headless Remote Web runtime without PyQt.
- Docs and scripts no longer point normal users at Desktop App.
- Legacy desktop instructions, if retained, are isolated and clearly unsupported.
- Static docs review finds no contradictory launch instructions.

### Round 50 Result

- `run_NAIA.bat`, `run_NAIA.command`, and `run_NAIA_test_only.bat` now install `requirements-headless.txt` and launch `NAIA_web_headless.py`.
- Default/platform requirement files still delegate to `requirements-headless.txt`; PyQt and desktop integration dependencies remain only in `requirements-desktop-legacy*.txt`.
- `legacy_desktop/README.md` now states the archive is manual and unsupported, not part of the setup path.
- Startup measurement tooling presents headless Remote Web as the supported default; `--entrypoint desktop` is legacy comparison only.
- CDP validation passed on port `7315`: first paint `2.391s`, Random prompt update `6.25s`, Generate dispatch `0.094s`; import audit reported no PyQt or `legacy_desktop` imports.

## Round 51 - Decommission Gate Validation

### Purpose

Prove Desktop App removal is real and not only documented.

### TODO Checklist

- [ ] Run fresh-process import audit for supported launch and supported service imports.
- [ ] Run focused pytest for headless app, API setup, prompt generation, generation request, result/history, and all supported optional workflows.
- [ ] Run CDP against the supported launch path.
- [ ] Click Random and Generate in the browser.
- [ ] Validate actual image result display for supported generation backend.
- [ ] Validate history, PNG export, and API setup modal.
- [ ] Verify no process logs mention `NAIA_cold_v4`, `QApplication`, `ModernMainWindow`, `ImageWindow`, `RemoteBridge`, `MiddleSectionController`, or `TabController`.
- [ ] Re-run startup measurement and compare against Round 39 headless baseline.

### When Done

- Desktop App decommission completion can be claimed with evidence.
- The repository has no supported PyQt runtime dependency.
- Browser/CDP validation proves the supported Remote Web app works after Desktop fallback removal.
- Remaining limitations are documented as retired or legacy, not hidden compatibility requirements.

## Preferred Execution Order

1. Rounds 41-43 establish inventory, default launch, and dependency boundaries.
2. Rounds 44-48 migrate or retire the remaining Desktop-backed behavior.
3. Rounds 49-50 physically remove/archive Desktop code and align installation/docs.
4. Round 51 is the final evidence gate.

The first destructive round should not happen before Round 41 inventory is complete.
