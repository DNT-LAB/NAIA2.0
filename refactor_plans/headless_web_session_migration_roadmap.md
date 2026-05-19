# Headless Web Session migration roadmap

## Assessment

The current refactor has reduced some PyQt module wakeups, but the Web Session still starts through the desktop application:

- `NAIA_cold_v4.py --web-shell` creates `QApplication`.
- `ModernMainWindow()` is still constructed.
- Settings, ImageWindow, tab controllers, middle controllers, PyQt signals, and `RemoteBridge` are still part of the startup path.
- The Web UI can generate images, but it does so by driving a hidden desktop runtime.

The practical goal is therefore not more small lazy-loading, but a separate headless server runtime where Remote Web talks directly to core services.

## Current Completion State

Round 30 is complete: the desktop-backed WebShell now has a repeatable timing, memory, CDP, generation-dispatch, and dependency-audit baseline.

Round 31 is complete: a PyQt-free `WebSessionContext` skeleton now owns headless Remote Web startup state, event publication, API status payloads, queue state payloads, and initial websocket message assembly.

Round 32 is complete: `NAIA_web_headless.py` can start a PyQt-free FastAPI app, serve the Remote Web shell, return `/api/status`, and complete a CDP first-paint check with Random/Generate controls visible.

The full Headless Web Session migration is not complete yet. The new headless entrypoint intentionally does not wire Random prompt execution, Generate dispatch, results, history, API setup persistence, or optional modules. Rounds 33-39 remain the concrete cutover work needed before the roadmap can be marked complete.

## Final Target

Remote Web must be able to start and perform its core workflow without creating desktop UI objects.

Required baseline:

- No `QApplication` in the headless web entrypoint.
- No `ModernMainWindow()` in the headless web entrypoint.
- No `ImageWindow` in the headless web entrypoint.
- No Settings tab, TabController, MiddleSectionController, or desktop module widget construction in the headless web entrypoint.
- FastAPI, websocket, prompt generation, generation request dispatch, result/history, and API setup work through core services.

## Round Rules

Every implementation round must follow this order:

1. Confirm the current round plan.
2. Perform the scoped work.
3. Run tests and static review.
4. Patch any issues found by tests/review.
5. Commit only the scoped files when the round is complete.
6. Run browser/CDP validation whenever the round changes visible Remote Web behavior or server startup behavior.

Do not judge the next rounds by subjective startup feel. Each round must either improve a measured number, remove a concrete PyQt dependency from the headless path, or prove that a dependency cannot yet be removed.

## Round 30 - Measurement Harness and Dependency Contract

### TODO Checklist

- [x] Add a repeatable startup measurement command or script.
- [x] Measure `process start -> FastAPI listen`.
- [x] Measure `process start -> /api/status first 200`.
- [x] Measure `process start -> Remote Web first paint`.
- [x] Measure Random button click -> prompt update latency.
- [x] Measure Generate button click -> generation request dispatch latency.
- [x] Record process RSS after startup and after first generation.
- [x] Add import/dependency audit output for `PyQt6`, `ModernMainWindow`, `ImageWindow`, `RemoteBridge`, and middle modules.
- [x] Save the baseline summary under `refactor_docs/`.

### When Done

- One documented command can produce comparable timing and dependency output.
- The output identifies whether `QApplication`, `ModernMainWindow`, `ImageWindow`, `MiddleSectionController`, and `RemoteBridge` were created/imported.
- Future rounds can compare against this baseline instead of relying on subjective speed.

### Round 30 Result

Baseline command:

```powershell
python tools/measure_web_session_startup.py --port 7276 --cdp-port 9376 --include-generate --output-json logs\round30_web_session_baseline.json --write-summary refactor_docs\round_30_headless_web_baseline.md
```

Measured desktop-backed WebShell baseline:

- `process start -> FastAPI listen`: 11.11 seconds
- `process start -> /api/status 200`: 12.797 seconds
- `process start -> Remote Web first paint`: 13.485 seconds
- `Random click -> prompt update`: 3.641 seconds
- `Generate click -> dispatch marker`: 0.093 seconds
- RSS after action-ready: 1797.31 MB
- RSS after random: 1890.16 MB
- RSS after generate dispatch: 1890.62 MB

Dependency audit result:

- `PyQt6` imported: yes
- `ModernMainWindow` constructed: yes
- `ImageWindow` constructed: yes
- `MiddleSectionController` constructed/imported: yes
- `RemoteBridge` constructed: yes
- Middle module imports observed: `modules.character_module`, `modules.character_module.CharacterSearchDialog`

This proves that the current WebShell is still desktop-backed. It is a valid baseline for later comparison, not the final headless target.

## Round 31 - Headless Service Container Skeleton

### TODO Checklist

- [x] Define a `WebSessionContext` or equivalent server-side service container.
- [x] Move the minimum shared event bus needed by Remote Web into a PyQt-free service.
- [x] Provide PyQt-free access to settings, API backend status, prompt settings, queue state, result state, and history state.
- [x] Define adapter boundaries for desktop-only objects that still exist.
- [x] Add tests that import the service container without importing `PyQt6`.

### When Done

- A unit test can construct the headless service container without `QApplication`.
- The service container exposes enough state for `/api/status` and initial websocket state.
- Desktop code can still use the existing `AppContext` path.

### Round 31 Result

- Added `core.web_session_context.WebSessionContext`.
- Added `WebSessionEventBus` as the minimum AppContext-compatible event bus for headless Remote Web services.
- Added API status, HTTP status, desktop-window state, queue state, generation param schema, and initial websocket message payload builders.
- Added pipeline hook registration compatibility so prompt/generation services can migrate without depending on `AppContext`.
- Kept desktop-only objects behind explicit adapter boundaries: `main_window`, `middle_section_controller`, and `remote_bridge` are `None` in the headless container.
- Added focused tests that construct the container in a fresh Python process and assert `PyQt6` is not imported.

## Round 32 - Headless FastAPI Entrypoint

### TODO Checklist

- [x] Add a headless entrypoint such as `NAIA_web_headless.py` or `core/web_session_app.py`.
- [x] Start FastAPI/uvicorn from the headless service container.
- [x] Serve `ui/remote_web` static assets from the headless entrypoint.
- [x] Wire `/api/status` and websocket connection without `ModernMainWindow`.
- [x] Keep the existing desktop/web-shell entrypoint working during transition.

### When Done

- `python NAIA_web_headless.py --port <port>` starts Remote Web without `QApplication`.
- `/api/status` returns 200 from the headless process.
- CDP opens the Remote Web root and sees Random/Generate controls.
- Dependency audit shows no `ModernMainWindow()` or `ImageWindow` construction.

### Round 32 Result

- Added `core.web_session_app.create_headless_app()`.
- Added `NAIA_web_headless.py`.
- The headless app serves `/`, `/style.css`, `/app.js`, `/js/*`, `/guides/*`, `/api/status`, `/api/queue/state`, `/api/prompt-highlight-index`, `/api/latest-image`, and `/ws`.
- Websocket startup sends session, desktop-window state, mode, options, params, queue state, api status, `init_complete`, and `lazy_indices_ready`.
- Focused tests import the app factory and entrypoint in a fresh process and assert `PyQt6` is not imported.
- CDP validation on `http://127.0.0.1:7281/` confirmed:
  - title: `NAIA Remote`
  - readyState: `complete`
  - `#btnRnd` present
  - `#btnGen` present
  - boot indicator hidden
  - active mode: `NAI`

This is a startup/first-paint cutover point only. Random and Generate intentionally return a headless "not wired yet" toast until Rounds 34-35 move those contracts out of the desktop bridge.

## Round 33 - API Setup and Cloudflared Server Ownership

### TODO Checklist

- [ ] Move NAI/WebUI/ComfyUI credential read/write into PyQt-free services.
- [ ] Move API status check, disconnect, and verify-and-save behavior behind server APIs.
- [ ] Move cloudflared start/stop/status behind a PyQt-free service.
- [ ] Keep the Remote Web API settings modal server-authoritative.
- [ ] Make desktop Settings tab consume the same service or stay as a separate desktop adapter.

### When Done

- The API settings modal works in the headless entrypoint.
- NAI/WebUI/ComfyUI status is persisted and broadcast without Settings tab objects.
- Cloudflared status can be queried and changed without desktop UI.
- Desktop mode still preserves existing API setup behavior.

## Round 34 - Server-Owned Random Prompt

### TODO Checklist

- [ ] Route Remote Web random prompt requests directly to a core prompt generation service.
- [ ] Ensure prompt engineering, conditional prompt, reference inset, wildcard, character, and filter logic run through core/headless hooks.
- [ ] Remove `RemoteBridge._find_module()` or middle-module wakeups from the random prompt path.
- [ ] Confirm loaded widget-less modules do not affect random prompt generation.
- [ ] Add tests for random prompt generation with no PyQt widgets.

### When Done

- Random button updates the Remote Web prompt in the headless entrypoint.
- Logs show no `MiddleSectionController.get_module_instance()` dependency for normal random prompt generation.
- Random prompt behavior matches the current desktop-backed Web Session for the supported options.

## Round 35 - Widget-Free Generation Request Contract

### TODO Checklist

- [ ] Define a normalized `GenerationRequest` schema for Remote Web.
- [ ] Make Remote Web request payload plus saved settings the source of generation parameters.
- [ ] Remove reads from `generation_checkboxes`, combo boxes, text edits, and `MainController` from the Remote Web generation path.
- [ ] Preserve per-mode NAI/WEBUI/COMFYUI parameter behavior.
- [ ] Add contract tests for request normalization and backend dispatch payloads.

### When Done

- Generate dispatches through the headless entrypoint without reading desktop widgets.
- NAI generation request dispatch is visible in logs from the headless process.
- Existing desktop generation still works through a desktop adapter path.
- Regression tests cover at least NAI mode and one non-NAI mode contract.

## Round 36 - Result, History, and Image Pipeline Services

### TODO Checklist

- [ ] Add or isolate a PyQt-free `ResultStore`.
- [ ] Add or isolate a PyQt-free `GenerationHistoryStore`.
- [ ] Add or isolate image save and PNG-to-WEBP conversion services.
- [ ] Broadcast generation result, save result, and history changes from server state.
- [ ] Make `ImageWindow` a desktop consumer of result/history state instead of the owner.

### When Done

- Headless Remote Web receives and renders generation results.
- Image save and PNG-to-WEBP return paths work without `ImageWindow`.
- History updates appear in Remote Web after generation.
- Desktop result tab behavior remains compatible.

## Round 37 - RemoteBridge Decomposition

### TODO Checklist

- [ ] List every websocket event currently emitted by `RemoteBridge`.
- [ ] Move server-owned events to the headless event bus.
- [ ] Restrict desktop signal relay to desktop mode.
- [ ] Remove or replace `QObject` requirements from the headless server path.
- [ ] Add tests for websocket state broadcasts without desktop signals.

### When Done

- Headless Remote Web can run without constructing `RemoteBridge(QObject)`.
- Websocket startup state, generation status, queue state, prompt updates, and result updates are emitted from server services.
- Desktop mode still receives equivalent updates through its adapter.

## Round 38 - Desktop-Only Feature Isolation

### TODO Checklist

- [ ] Classify all tabs/modules into `web-core`, `web-optional`, and `desktop-only`.
- [ ] Move or document unsupported desktop-only surfaces in `not_implement/`.
- [ ] Ensure the headless entrypoint does not scan/import desktop-only tabs/modules.
- [ ] Keep optional web features behind explicit service boundaries.
- [ ] Add an import audit test for the headless entrypoint.

### When Done

- Headless startup does not import Storyteller, Turbo Sequence, Studio, desktop-only tab files, or desktop module widgets.
- Unsupported surfaces have explicit documentation and do not appear as hidden startup work.
- The visible Remote Web feature set remains intact.

## Round 39 - Cutover Gate and Performance Review

### TODO Checklist

- [ ] Re-run the Round 30 measurement harness on the old desktop-backed web shell.
- [ ] Re-run the same measurement harness on the headless web entrypoint.
- [ ] Compare startup time, first status, first paint, first random prompt, first generate dispatch, and RSS.
- [ ] Run focused Remote Web regression tests.
- [ ] Run CDP validation for API setup, Random, Generate, result display, and history.
- [ ] Decide whether the default Web Session should switch to the headless entrypoint.

### When Done

- The headless path preserves the current Remote Web core feature set.
- The measured startup and first-action numbers show a meaningful gain or the remaining bottlenecks are explicitly listed.
- The desktop-backed WebShell is either deprecated, kept as compatibility mode, or removed by a separate approved cleanup round.
