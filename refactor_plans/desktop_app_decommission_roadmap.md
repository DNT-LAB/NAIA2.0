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

- [ ] List all supported entrypoints and launch scripts:
  - `NAIA_cold_v4.py`
  - `NAIA_web_headless.py`
  - `run_NAIA.bat`
  - `run_NAIA_web.bat`
  - `.command` launchers
- [ ] List all runtime requirements that exist only for Desktop App support.
- [ ] Generate a PyQt import inventory for `core/`, `modules/`, `tabs/`, `ui/`, `tools/`, and `tests/`.
- [ ] Build a workflow matrix with columns: workflow, current owner, Remote Web replacement, decision, blocker, validation.
- [ ] Classify every tab in `TAB_MODULE_SPECS`.
- [ ] Classify every middle module in `MIDDLE_MODULE_SPECS`.
- [ ] Classify every RemoteBridge websocket/API feature as headless-owned, migrate, retire, or legacy-only.
- [ ] Save the inventory under `refactor_docs/`.

### When Done

- A single document lists every remaining Desktop App dependency and its decision.
- No Desktop file can be removed later without a matching inventory row.
- The next round can change launcher behavior without guessing which workflows still need Desktop fallback.

## Round 42 - Default Launch Contract Cutover

### Purpose

Make the supported Web Session launch path headless by default while keeping Desktop launch explicit and legacy.

### TODO Checklist

- [ ] Update `run_NAIA_web.bat` and `run_NAIA_web.command` to launch `NAIA_web_headless.py`.
- [ ] Keep `run_NAIA.bat` as explicit legacy desktop launch or rename/document it as legacy.
- [ ] Update `core.web_shell_config` tests so default Web Session means headless, not desktop-backed shell.
- [ ] Add a smoke command for `python NAIA_web_headless.py --port <port>`.
- [ ] Add a guard that `--web-session` through `NAIA_cold_v4.py` is legacy-only or disabled.
- [ ] Update docs that still instruct users to start Remote Web via `NAIA_cold_v4.py --web-session`.

### When Done

- Fresh users running the Web launch script start the headless server.
- Desktop launch is still possible only through an explicit legacy path.
- CDP can open the default Web launch URL and pass startup/API setup/Random/Generate dispatch checks.
- Import audit for the default Web launch shows no `PyQt6`, `core.remote_api_server`, `ModernMainWindow`, `ImageWindow`, `MiddleSectionController`, or `TabController`.

## Round 43 - Requirements and Packaging Split

### Purpose

Separate headless runtime dependencies from Desktop-only dependencies so PyQt is no longer required for supported Remote Web installs.

### TODO Checklist

- [ ] Create a headless requirements file or split the existing `requirements.txt`.
- [ ] Move `PyQt6`, `PyQt6-Qt6`, `PyQt6-WebEngine`, `PyQt6-WebEngine-Qt6`, `PyQt6_sip`, `PyQt6-QScintilla`, `pywinpty`, and desktop-only packages into an optional legacy requirements file if still needed.
- [ ] Verify `NAIA_web_headless.py` starts in an environment conceptually limited to headless requirements.
- [ ] Update launcher/install scripts to install headless requirements for Web Session.
- [ ] Update test instructions to distinguish headless tests from legacy desktop tests.
- [ ] Add a dependency audit test that fails if a supported headless import path requires PyQt.

### When Done

- Headless Remote Web has its own install contract.
- Main Web Session setup does not install PyQt by default.
- Tests prove `core.web_session_app`, `NAIA_web_headless.py`, and core Remote Web services import without PyQt installed.
- Desktop-only dependency installation is explicitly legacy or optional.

## Round 44 - RemoteBridge Feature Migration

### Purpose

Remove remaining supported Web Session behavior from `core.remote_api_server.RemoteBridge` and move it into PyQt-free services or retire it.

### TODO Checklist

- [ ] Compare `refactor_docs/round_37_remote_bridge_event_contract.md` with the current Remote Web UI feature set.
- [ ] For each still-supported RemoteBridge endpoint/event, create or reuse a PyQt-free service.
- [ ] Move server-owned state into `WebSessionContext` or dedicated service objects.
- [ ] Remove direct Remote Web reliance on desktop widgets, desktop signals, and `_find_loaded_module_instance`.
- [ ] Add tests for migrated websocket and REST contracts.
- [ ] Mark retired RemoteBridge features as unsupported in `not_implement/` or decommission docs.

### When Done

- Supported Remote Web behavior no longer needs `RemoteBridge`.
- Fresh-process tests cover startup, Random, Generate, result/history, API setup, and migrated optional contracts without importing `core.remote_api_server`.
- Any remaining `RemoteBridge` code is legacy-only and unreachable from supported headless launch.
- CDP validates the migrated Remote Web feature set.

## Round 45 - Generation and Result Parity Without Desktop Controllers

### Purpose

Finish all supported generation/result workflows without `MainController`, `GenerationController` Qt workers, `ImageWindow`, or desktop result tabs.

### TODO Checklist

- [ ] Decide whether WEBUI and COMFYUI are supported in headless runtime or retired for this branch.
- [ ] If supported, validate full WEBUI generation execution, not only request normalization.
- [ ] If supported, validate full COMFYUI generation execution, including workflow loading and result extraction.
- [ ] Migrate save-directory state, auto-save, unsaved history, and result download endpoints to headless services.
- [ ] Migrate or retire result enhance/upscale actions.
- [ ] Migrate or retire img2img/inpaint/result-action flows that currently open desktop windows.
- [ ] Add tests for each supported backend mode.

### When Done

- Every supported generation backend works through the headless server or is explicitly retired.
- Result preview, PNG export, history, save actions, and error recovery are server-owned.
- No supported generation/result path imports `core.main_controller`, `core.generation_controller` Qt worker objects, `tabs.image_window`, or desktop dialogs.
- CDP validates actual Generate button behavior for all supported backend modes.

## Round 46 - Prompt and Module Workflow Migration

### Purpose

Remove supported Remote Web dependence on PyQt middle modules by replacing module wrappers with core services or retiring their web surfaces.

### TODO Checklist

- [ ] For `PromptEngineeringModule`, keep runtime hooks in `core.prompt_engineering_runtime` and migrate/retire remaining editor actions.
- [ ] For `PromptListModifierModule`, keep rule execution in `core.conditional_prompt_runtime` and migrate/retire editor/preset UI.
- [ ] For `CharacterModule`, keep saved settings/headless params and migrate/retire desktop character editor actions.
- [ ] For `CharacterReferenceModule`, migrate reference image storage/state to a PyQt-free service or retire the web controls.
- [ ] For `VibeTransferModule`, migrate image storage/clipboard-independent request state or retire the web controls.
- [ ] For `InstantWildcardModule` and `WildcardStatusModule`, keep PyQt-free services and retire desktop wrappers from supported web runtime.
- [ ] For `AutomationModule`, `E621EventModuleV2`, and `OllamaModule`, decide migrate or retire.
- [ ] Update Remote Web module panels to call services, not desktop module loaders.

### When Done

- Supported Remote Web module panels do not instantiate `modules/*_module.py`.
- Headless import audit after module-panel interaction still shows no PyQt middle module imports.
- Each module has a documented decision and validation path.
- CDP validates all remaining supported module panels.

## Round 47 - Tab Surface Migration, Retirement, or Archive

### Purpose

Remove Desktop App tab surfaces from the supported runtime by moving useful behavior to web-native services and archiving or retiring the rest.

### TODO Checklist

- [ ] Classify `tabs/studio*` and `ui/remote_web/js/features/studioTab.mjs` as migrate or retire.
- [ ] Classify `tabs/turbo_event_sequence*` as migrate or retire.
- [ ] Classify `tabs/artist_thumb_tab.py` against current Remote Web artist thumb services.
- [ ] Classify `tabs/png_info_tab.py`, `tabs/thumbnails_tab.py`, and image metadata viewers.
- [ ] Classify `tabs/img2img_tab.py`, `tabs/simple_web_view.py`, `tabs/web_view.py`, `tabs/depth_search_window.py`, and `tabs/comic_generator_tab.py`.
- [ ] Move retired desktop-only files to an archive/not-supported area or delete them if they are already replaced.
- [ ] Remove dynamic tab registry entries for retired surfaces.
- [ ] Update tests that assert removed/unsupported tabs are not imported.

### When Done

- Supported headless runtime does not include any `tabs/*` PyQt surface.
- Retired tabs are documented and no longer advertised in Remote Web.
- Migrated tab behavior has service/API tests and CDP coverage.
- `core.tab_controller` is legacy-only or removed from the supported tree.

## Round 48 - Core Qt Import Decoupling

### Purpose

Remove Qt imports from shared `core/` modules that remain in the supported headless runtime.

### TODO Checklist

- [ ] Audit every `core/*.py` `PyQt6` import.
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
- [ ] Add fresh-process import tests for all supported `core` services.

### When Done

- Supported `core` service imports do not import `PyQt6`.
- Qt-dependent controllers are either deleted, archived, or marked legacy desktop-only.
- Headless tests fail if shared core services regress by importing Qt.
- Generation, prompt, API setup, search, result, and history services remain functional.

## Round 49 - Desktop Legacy Package or Archive

### Purpose

Physically remove Desktop App files from the supported runtime tree, or move them into a clearly unsupported legacy package.

### TODO Checklist

- [ ] Choose one strategy: delete, `legacy_desktop/`, or `not_implement/desktop_archive/`.
- [ ] Move or delete `NAIA_cold_v4.py`.
- [ ] Move or delete `core.remote_api_server.py` if all supported features are migrated.
- [ ] Move or delete `core.middle_section_controller.py`, `core.tab_controller.py`, `core.main_controller.py`, and desktop-only controllers.
- [ ] Move or delete PyQt-only `tabs/`, `modules/`, and `ui/` files that are not part of a separate package.
- [ ] Update imports and tests after the move.
- [ ] Update docs so Desktop App is no longer presented as supported.

### When Done

- Supported runtime tree no longer exposes Desktop App entrypoints.
- `python NAIA_web_headless.py` still starts and passes core workflows.
- Import audit confirms supported runtime imports no Desktop App package.
- Any retained desktop code is clearly outside supported runtime and not imported by default.

## Round 50 - Final Requirements, Launcher, and Documentation Cleanup

### Purpose

Make the repository's install and launch story match the decommissioned runtime.

### TODO Checklist

- [ ] Remove Desktop App instructions from primary README/docs or move them to legacy notes.
- [ ] Remove PyQt dependencies from default requirements.
- [ ] Update launch scripts and command docs.
- [ ] Update `AGENTS.md` if validation/startup instructions still mention desktop-backed launch as default.
- [ ] Update measurement tooling so `headless` is the default and `desktop` is legacy-only if retained.
- [ ] Remove stale docs that claim desktop compatibility is part of the main path.

### When Done

- A fresh setup path installs and starts the headless Remote Web runtime without PyQt.
- Docs and scripts no longer point normal users at Desktop App.
- Legacy desktop instructions, if retained, are isolated and clearly unsupported.
- Static docs review finds no contradictory launch instructions.

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
