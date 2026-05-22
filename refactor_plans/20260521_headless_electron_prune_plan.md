# Plan - Headless/Electron Prune and Legacy Freeze

## Goal

NAIA2의 기준 실행 모델을 Headless Remote Web plus Electron release shell로 고정하고, PyQt Desktop 코드를 reference/quarantine 상태로 낮춘 뒤, 검증 가능한 단위로 기존 코드를 제거한다.

이 계획은 삭제를 즉시 수행하지 않는다. 먼저 contract와 owner를 고정하고, 그 뒤 round별로 이동/분리/삭제를 진행한다.

## Principles

- 일반 clone 사용자는 Electron/npm 없이 `NAIA_web_headless.py` 또는 launcher bat/command로 실행할 수 있어야 한다.
- Electron은 packaged release shell이며 backend lifecycle, maintenance view, logs, first-run setup, app window를 소유한다.
- Remote Web UI는 user interaction owner다.
- FastAPI/headless backend는 shared state, route contract, storage, download, generation dispatch를 소유한다.
- Prompt generation, pipeline hook, image generation, generation queue는 id-scoped shared pipeline으로 관리한다.
- PyQt Desktop은 더 이상 product baseline이 아니다.
- Desktop behavior가 필요한 경우 먼저 web/headless contract로 옮긴 뒤 legacy를 삭제한다.
- Large/runtime/user data는 source tree가 아니라 runtime roots에 있어야 한다.

## Execution Protocol

Each round follows the current executable refactor-plan pattern:

- Plan review: identify the current round, evidence already present, and remaining gap before editing.
- Gate setup: add or reuse manifest-backed checks before declaring work complete.
- Implementation: change only the round owner surface.
- Modification: fix failing checks in the same round before broadening scope.
- Deletion: delete only from an approved candidate group and only after required gates pass.
- Verification: run focused tests, the round checker, static review, and `git diff --check`.
- Post-work evaluation: compare the result against When Done and record deferred work.
- Commit: stage only intended files and create a round-scoped commit when commit-level completion is requested.

## Post-Work Evaluation

After each round:

- Confirm the When Done conditions are satisfied or blocked by a named gate.
- Confirm whether product behavior, release policy, layout policy, deletion candidates, or only docs/checks changed.
- Confirm deletion work was candidate-scoped and approval-gated.
- Confirm runtime/generated artifacts are not staged.
- Record validation commands and remaining migration risks.

## Round 0 - Contract Refresh Before More Deletion

### Checklist

- [x] `release_assets/manifests/remote_web_feature_contract.json`에 install-manager routes 추가.
- [x] first-run setup/download feature group을 Remote Web contract에 명시.
- [x] `refactor_plans/final_headless_electron_release_reorganization_plan.md`의 stale release artifact shape를 검토하고 최신 asset policy와 충돌이 없음을 확인한다.
- [x] `resources/wildcards/` 같은 bundled wildcard 표현을 runtime `user-data/wildcards` 정책으로 교체한다.
- [x] `core/api_verification.py` 등 stale comment에서 `core/remote_api_server.py` 기준 설명을 headless `core/web_session_app.py` 기준으로 갱신한다.
- [x] `npm run check:feature-contract` 또는 `python tools/check_remote_web_feature_contract.py`를 통과시킨다.

### When Done

- Remote Web feature contract가 실제 `core/web_session_app.py` route surface와 일치한다.
- first-run install manager가 release/Electron smoke 대상 기능으로 문서화된다.
- runtime asset policy와 final plan이 서로 충돌하지 않는다.

### Completion Evidence - 2026-05-22

- `release_assets/manifests/remote_web_feature_contract.json` includes `install_manager` with `/api/install-manager`, `/api/install-manager/initialize`, `/api/install-manager/tag-archive/download`, and cancel routes.
- `release_assets/manifests/runtime_asset_classification.json` and `release_include_exclude_draft.json` keep runtime wildcards under `user-data/wildcards` policy and exclude local `wildcards/**` from release source staging.
- `refactor_plans/final_headless_electron_release_reorganization_plan.md` has no remaining `resources/wildcards/`, bundled wildcard, or `core/remote_api_server.py` wording that conflicts with the current runtime asset policy.
- `core/api_verification.py` now references `core/web_session_app.py` for the headless Web setup/API path.
- Required validation: `python tools/check_remote_web_feature_contract.py`.

## Round 1 - Legacy Reference Freeze

### Checklist

- [x] PyQt Desktop entrypoint를 reference-only로 명시한다.
- [x] `run_NAIA.bat`, `run_NAIA_web.bat`, `NAIA_web_headless.py`, Electron main process의 역할을 문서화한다.
- [x] 신규 기능 수정은 headless/web/electron path에만 적용한다는 rule을 AGENTS 또는 refactor plan에 반영한다.
- [x] `legacy_desktop/**` 아래 코드는 migration reference로만 사용하고 product smoke 대상에서 제외한다.
- [x] Desktop-only tests는 `tests/legacy_desktop/`로 이동하거나 manifest에 명시된 legacy tests로 유지한다.

### When Done

- 개발자가 새 작업을 시작할 때 기준 구현이 PyQt인지 Web/Headless인지 혼동하지 않는다.
- Desktop path는 feature parity source가 아니라 historical reference로 취급된다.
- Legacy test는 의도적으로만 실행된다.

### Completion Evidence - 2026-05-22

- `PROJECT_LAYOUT_POLICY.md` defines `legacy_desktop/NAIA_cold_v4.py` as an explicit reference-only entrypoint and blocks default launchers from using legacy desktop terms.
- `release_assets/manifests/project_layout_policy.json` records the `legacy_desktop` reference boundary and links `release_assets/manifests/legacy_pyqt_surface_classification.json` as evidence for explicit desktop tests.
- `tools/check_project_layout_policy.py` now verifies the legacy desktop reference boundary, launcher ban, and classification manifest link.
- Required validation: `python tools/check_project_layout_policy.py`.

## Round 2 - Shared Pipeline and ID-Scoped Runs

### Checklist

- [x] `prompt_run_id`, `generation_request_id`, `requestId` naming and payload contract를 정리한다.
- [x] `WebSessionContext` 또는 별도 service에 bounded in-memory pipeline run registry를 추가한다.
- [x] Random prompt, preset composer, prompt tools preview, direct prompt submit이 prompt run record를 생성하게 한다.
- [x] `PromptProcessor` hook execution이 run-scoped metadata를 받을 수 있게 하고 기존 hook point와 priority를 유지한다.
- [x] Hook trace, warning, derived prompt/params를 prompt run에 기록할 수 있게 한다.
- [x] `HeadlessGenerationService` generation request가 source prompt run id를 참조하게 한다.
- [x] Queue snapshot, generation result, history event, websocket payload가 id link를 보존하게 한다.
- [x] `current_prompt_context`, `current_source_row`, `last_generation_request`, `last_generation_params`는 compatibility mirror로만 쓰이도록 호출부를 분류한다.
- [x] Multi-tab Remote Web에서 같은 prompt run/generation request 상태를 id로 조회 또는 재수신할 수 있게 한다.
- [x] Existing hook modules: Prompt Engineering, Conditional Prompt, Reference Inset의 behavior를 focused tests로 고정한다.

### When Done

- Prompt generation과 image generation이 latest singleton이 아니라 id 기준으로 추적된다.
- WebSession 기능은 prompt run id와 generation request id를 통해 상태를 공유한다.
- Pipeline hook은 유지되며, 추가 기능이 중간에 개입할 수 있는 공식 확장점으로 문서화된다.
- Random Prompt, Generate, Preset, Prompt Tools, Queue, Result/History smoke가 id link를 잃지 않는다.

### Slice Evidence - 2026-05-22

- `core/pipeline_run_registry.py` provides bounded server-owned prompt run records.
- Random prompt websocket payloads, preset generation payloads, and direct generation dispatches carry `prompt_run_id`/`promptRunId`.
- Event preset and composite preset prompt-preview routes now record preview prompt runs before generation.
- `/api/pipeline/prompt-runs` and `/api/pipeline/prompt-runs/{prompt_run_id}` expose prompt runs for multi-tab lookup.
- Headless result image metadata, history list items, history metadata, and `viewer_new_image` websocket events preserve `prompt_run_id` and `generation_request_id`.
- Prompt run payloads now expose explicit `warnings` and sanitized `derived` data; completion records derived final prompt and generation dispatch records selected public generation params.
- `PromptProcessor` integration coverage now verifies a real headless `ReferenceInsetAutoInjectHook` execution is recorded in prompt-run `hook_trace`.
- Existing focused tests cover Prompt Engineering and Conditional Prompt hook behavior; the new processor-level test closes the Reference Inset gap.
- `release_assets/manifests/remote_web_feature_contract.json` documents the pipeline lookup routes.
- Required validation: `python tools/check_remote_web_feature_contract.py`.

### Compatibility Mirror Audit - 2026-05-22

- `current_source_row` and `current_prompt_context` remain AppContext compatibility mirrors for the active prompt-processing call path. `PromptGenerationService` and `PromptProcessor` still need them during a single in-flight prompt run, and legacy-adjacent helpers such as character settings and event-stream runtime still read them. Cross-tab Remote Web state must use `PipelineRunRegistry` through `prompt_run_id` instead.
- `last_generation_request` and `last_generation_params` remain test/debug and legacy RemoteBridge compatibility mirrors after `HeadlessGenerationService.enqueue_remote_request`. The authoritative queue state is `GenerationQueueManager`/`GenerationRequest.request_id`, and result/history state is owned by `HeadlessResultStore` plus id-bearing websocket/API payloads.
- New feature work must not add fresh singleton consumers for these four fields. If a route needs durable state, add an id-scoped registry/store lookup first and leave the mirror as a temporary bridge only.

## Round 3 - Non-Legacy Legacy Import Cleanup

### Checklist

- [x] `core/api_service.py`, `core/prompt_processor.py`, `core/prompt_generation_service.py`의 `core.context.AppContext` type hint를 Protocol 또는 `Any` 기반 headless contract로 교체한다.
- [x] `interfaces/base_module.py`, `interfaces/base_tab_module.py`를 legacy module protocol과 headless protocol로 분리한다.
- [x] `utils/clipboard_image.py`를 Qt clipboard adapter와 pure image byte helper로 분리한다.
- [x] `utils/load_generation_params.py`를 legacy desktop utility로 격리하거나 headless settings service와 분리한다.
- [x] `tabs/comic_generator_tab.py` root compatibility entry를 archive/delete 후보로 분류한다.
- [x] `core/kr_tag_loader.py`의 legacy interactive fallback을 source mode migration fallback으로 제한한다.

### When Done

- Headless-supported import path에서 `legacy_desktop`, `NAIA_cold_v4`, direct PyQt runtime import가 발생하지 않는다.
- `tools/smoke_staged_backend.py`와 `tests/test_requirements_split.py`가 통과한다.
- Qt가 필요한 helper는 이름과 위치만 봐도 legacy adapter임을 알 수 있다.

### Slice Evidence - 2026-05-22

- `core/api_service.py`, `core/prompt_processor.py`, `core/prompt_generation_service.py`, and the adjacent `core/mode_ware_manager.py` now type the shared context as `Any` instead of importing `core.context.AppContext` for annotations.
- `rg 'from core\.context import AppContext|app_context: .AppContext|core\.context' core/api_service.py core/prompt_processor.py core/prompt_generation_service.py core/mode_ware_manager.py core -g '*.py'` returns no remaining matches in the targeted headless core files.
- `utils/image_bytes.py` now owns pure PNG/PIL byte conversion without importing Qt; `utils/clipboard_image.py` remains the Qt clipboard adapter and reuses that helper.
- `interfaces/headless_module_protocol.py` and `interfaces/legacy_module_protocol.py` now separate headless hook/module contracts from legacy widget module contracts; `base_module.py` and `base_tab_module.py` are documented as legacy widget adapters and no longer type against `core.context.AppContext`.
- `GenerationParamsManager` moved to `legacy_desktop/utils/load_generation_params.py`; the root `utils/load_generation_params.py` is now a lazy compatibility shim that does not import `legacy_desktop` during module import.
- `tabs/comic_generator_tab.py` is now explicitly classified as the root compatibility entry for the legacy Comic Generator surface and is excluded alongside `tabs/comic_generator/**`.
- `core/kr_tag_loader.py` no longer reads `legacy_desktop/ui/interactive/interactive` by default; callers must opt into `allow_legacy_interactive_fallback=True` for source-mode migration reads.
- Required validation for this slice: `python -m py_compile core\api_service.py core\prompt_processor.py core\prompt_generation_service.py core\mode_ware_manager.py core\kr_tag_loader.py utils\image_bytes.py utils\clipboard_image.py utils\load_generation_params.py legacy_desktop\utils\load_generation_params.py interfaces\base_module.py interfaces\base_tab_module.py interfaces\headless_module_protocol.py interfaces\legacy_module_protocol.py`, focused prompt/headless tests, `tests\test_requirements_split.py`, `tests\test_kr_tag_loader.py`, `tests\test_image_bytes.py`, `tests\test_vibe_transfer_clipboard.py`, and legacy surface classification gates.

## Round 4 - Split the Headless Monolith by Feature Owner

### Checklist

- [ ] `core/web_session_app.py` route groups를 owner별 target module로 나눈다.
- [ ] `core/web_session_context.py`의 module-state logic을 feature service로 분리한다.
- [ ] 우선순위: install manager, result/history/image action, prompt tools, presets, artist/thumb/character viewer.
- [ ] 각 분리는 route behavior를 바꾸지 않는 mechanical move로 수행한다.
- [ ] 기존 import compatibility shim을 한 round 유지한다.
- [ ] route별 focused tests를 feature group별로 이동한다.

### When Done

- `core/web_session_app.py`는 app factory/router composition에 가까워진다.
- `core/web_session_context.py`는 모든 feature storage와 image logic을 직접 소유하지 않는다.
- feature owner를 보고 해당 기능의 route, state, storage, tests를 찾을 수 있다.

### Slice Evidence - 2026-05-22

- Install Manager routes moved from `core/web_session_app.py` to `app/backend/server/install_manager_routes.py` without changing route paths or response shapes.
- Remote Web shell static file routes and `/js`/`/guides` mounts moved from `core/web_session_app.py` to `app/backend/server/web_shell_routes.py`.
- Status, capabilities, queue snapshot/action, and pipeline prompt-run lookup routes moved from `core/web_session_app.py` to `app/backend/server/state_routes.py`; queue resume keeps generation-runner wakeup through an app-factory callback.
- Prompt highlight index, tag lookup, and Prompt Engineering preset-thumbnail get/upload/generate routes moved from `core/web_session_app.py` to `app/backend/server/prompt_tools_routes.py`; generation-completion thumbnail persistence now reuses the route module's pure thumbnail-save helper.
- Result, history, viewer, metadata, clipboard fallback, and image action routes moved from `core/web_session_app.py` to `app/backend/server/result_display_routes.py`; Result Enhance and websocket img2img reuse the route module's public result-image source resolver.
- Img2Img/Inpaint session state, mask handling, source normalization, and generation-command assembly moved from `core/web_session_context.py` to `core/headless_img2img_service.py`; the context keeps compatibility shim methods for existing callers.
- Resolution manager, custom search parquet upload, and ComfyUI workflow routes moved from `core/web_session_app.py` to `app/backend/server/params_workflow_routes.py`, keeping per-mode resolution storage, search-state broadcast, Comfy workflow state, and server-owned option broadcast behavior unchanged.
- Style thumbnail routes moved from `core/web_session_app.py` to `app/backend/server/style_thumbnail_routes.py`; Character Viewer remains in the app factory until generation dispatch coupling is split.
- Danbooru internal tab routes moved from `core/web_session_app.py` to `app/backend/server/danbooru_routes.py` with URL normalization and prompt-preview helpers owned by that route module.
- Event Preset status/download/bootstrap/select/preview/generate/thumbnail routes plus composite preset preview/generate and clothes/expression preset axis routes moved from `core/web_session_app.py` to `app/backend/server/event_preset_routes.py`; preset service factories live in `app/backend/server/preset_services.py`.
- Character Viewer routes moved from `core/web_session_app.py` to `app/backend/server/character_viewer_routes.py`, including thumbnail cache handling and generation queue dispatch via app-factory callbacks.
- Artist Thumbnail routes moved from `core/web_session_app.py` to `app/backend/server/artist_thumbnail_routes.py`, including random-prompt override handling and generation queue dispatch via app-factory callbacks.
- `app/backend/server/__init__.py` now lazy-exports the compatibility server entrypoints so feature route modules can live under the same package without circular imports.
- `release_assets/manifests/remote_web_feature_contract.json` now supports multiple route source files and lists the web-shell, install-manager, state, params/workflow, prompt-tools, style-thumbnail, Danbooru, Event Preset, Character Viewer, and Artist Thumbnail route owners.
- Character Reference module state, storage scanning, storage apply/upload, enable/disable handling, and NAI director-reference parameter assembly moved from `core/web_session_context.py` to `core/headless_character_reference_service.py`; the context keeps compatibility shim methods for existing callers.
- Vibe Transfer module state, upload/apply storage, cluster load/list, mutual-exclusion handling, and NAI Vibe parameter assembly moved from `core/web_session_context.py` to `core/headless_vibe_transfer_service.py`; the context keeps compatibility shim methods for existing callers.
- Automation settings state and retired execution actions moved from `core/web_session_context.py` to `core/headless_automation_service.py`; the context keeps compatibility shim methods for existing callers.
- WEBUI Hiresfix Assist state/default normalization and Event Stream state/start/stop actions moved from `core/web_session_context.py` to `core/headless_webui_hiresfix_assist_service.py` and `core/headless_event_stream_service.py`; the context keeps compatibility shim methods for existing callers.
- Prompt Engineering and Conditional Prompt module state/actions moved from `core/web_session_context.py` to `core/headless_prompt_engineering_service.py` and `core/headless_conditional_prompt_service.py`; the context keeps compatibility shim methods for existing callers.
- Character module settings state/actions moved from `core/web_session_context.py` to `core/headless_character_service.py`; the context keeps compatibility shim methods for existing callers.
- Required validation for this slice: web-shell static route smoke, install-manager route test, runtime install manager tests, backend package shim tests, remote web feature contract test/checker, prompt highlight route smoke, tag lookup HTTP/WebSocket smoke, Result/History/Viewer route smoke, Img2Img/Inpaint service smoke, Character service smoke, Character Reference service smoke, Vibe Transfer service smoke, Automation service smoke, WEBUI Hiresfix Assist service smoke, Event Stream service smoke, Prompt Engineering service smoke, Conditional Prompt service smoke, Prompt Engineering preset-thumbnail upload/get/generate smoke, resolution route smoke, search parquet upload route smoke, ComfyUI workflow state/default/upload/web smoke, style thumbnail route smoke, Danbooru route smoke, Event/Preset bootstrap/select/preview/generate/thumbnail smoke, clothes/expression preset route smoke, Character Viewer route smoke, Artist Thumbnail route smoke, focused Event/Preset websocket tests, and syntax checks of moved route sources.

## Round 5 - Runtime Data and Migration Boundary

### Checklist

- [ ] Runtime write roots를 다시 검증한다: `config`, `data`, `ui_assets`, `save`, `downloads`, `bundles`, `cache`, `logs`, `output`, `wildcards`.
- [ ] Electron mode에서 legacy source fallback이 꺼지는지 확인한다.
- [ ] Source checkout mode에서 기존 사용자의 repo-local data를 migration/read fallback으로만 유지한다.
- [ ] wildcard, artist thumbnail, event preset, character reference, vibe transfer, custom parquet, generated cache를 각각 runtime owner에 묶는다.
- [ ] 데이터 마이그레이션/import command 또는 UI entry를 별도 계획으로 분리한다.

### When Done

- Clean packaged first run에서 source-local downloaded data가 자동으로 섞이지 않는다.
- Existing source checkout 사용자의 데이터는 명시적인 fallback 또는 migration path로만 접근된다.
- `tools/check_runtime_write_policy.py`, `tools/check_runtime_asset_classification.py`, release manifest audit가 통과한다.

## Round 6 - Remote Web Feature Parity Smoke Matrix

### Checklist

- [ ] Random Prompt latency and behavior smoke.
- [ ] Generate dispatch smoke with controlled test double or real configured endpoint.
- [ ] Prompt Tools all-module websocket smoke.
- [ ] Params, resolution, WEBUI/COMFYUI workflow state smoke.
- [ ] Event/Clothes/Expression/Preset prompt preview and generate path smoke.
- [ ] Artist Thumbnail list/image/favorite/random/generate smoke.
- [ ] Danbooru internal tab and popup handling smoke.
- [ ] img2img/Inpaint session and mask smoke.
- [ ] Vibe Transfer Storage smoke.
- [ ] Character Reference storage smoke.
- [ ] Enhance smoke for supported modes.
- [ ] History/save/output smoke.
- [ ] Electron packaged CDP smoke for maintenance view, logs, downloads, popups, websocket reconnect.

### When Done

- Desktop code is no longer needed to prove supported user-visible workflows.
- A regression can be assigned to a feature owner and route/UI smoke, not to a vague Desktop/Web mismatch.
- Packaged and source modes both have accepted smoke coverage.

## Round 7 - Legacy Quarantine Hardening

### Checklist

- [ ] Root-level legacy shims that import `legacy_desktop` are either removed or moved under `legacy_desktop/`.
- [ ] Desktop-only tabs/modules that are not product features are archived or deleted after owner review.
- [ ] Desktop-only features that may return later are documented as web rebuild candidates, not kept as active runtime code.
- [ ] Legacy tests are moved under `tests/legacy_desktop/` or excluded from normal headless/electron CI.
- [ ] `requirements-headless.txt` remains PyQt-free.

### When Done

- Normal source and packaged runtime cannot accidentally import Desktop app code.
- Legacy Desktop can still be inspected historically, but it no longer shapes active product architecture.
- The remaining source tree communicates supported runtime boundaries by directory structure.

## Round 8 - Packaging and Release Hardening

### Checklist

- [ ] Clean Python runtime build remains base-only and creates managed dependency env on first launch.
- [ ] Maintenance window appears before long install/download work and shows progress without scrollbars.
- [ ] Release package includes only reviewed bootstrap data and samples.
- [ ] `NAIA-Portable` folder shape is user-friendly.
- [ ] Icon, menu hiding, log access, data folder access, browser fallback are verified.
- [ ] Defender scan and artifact size measurement are recorded for release candidates.

### When Done

- A clean Windows user can run the packaged app without touching `electron-dist/win-unpacked`.
- First-run delay is visible and explainable.
- Packaged release does not bundle local runtime/user data.

## Round 9 - Hard Delete Phase

### Checklist

- [ ] Confirm Round 0 through Round 8 gates pass.
- [ ] Generate a delete candidate list with paths, owners, and replacement status.
- [ ] Delete only one ownership group per commit.
- [ ] Run focused static checks and smoke after each delete group.
- [ ] Keep migration notes for users who had repo-local data.

### When Done

- PyQt Desktop is removed from active product code, not merely hidden.
- Electron/source headless execution still works.
- Release staging remains clean and auditable.
- No user-visible supported WebSession feature regresses.

## First Work Item

Start with Round 0. The immediate concrete task is to update `remote_web_feature_contract.json` for install-manager routes and align stale plan wording around bundled wildcards.
