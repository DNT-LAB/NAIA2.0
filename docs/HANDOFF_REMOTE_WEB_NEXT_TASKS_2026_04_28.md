# HANDOFF — Remote Web Next Tasks (2026-04-28)

## Current Snapshot

- Branch: `future01`
- Implementation snapshot base: `3d1f88a Preserve parenthetical tags in web lookup`
- This document is a handoff checkpoint on top of that implementation snapshot.
- Worktree: dirty, mostly Remote Web / module bridge work.
- Recent committed direction: remote tag lookup, metadata viewer, result image context actions, Korean tag metadata, and Remote Web UX refinements.

## Uncommitted Work Observed

Changed files:

- `core/remote_api_server.py`: large bridge expansion for `e621_event`, `ollama`, and `instant_wildcard`.
- `ui/remote_web/app.js`: imports/wrappers for E621 and Ollama panels, boot indicator, auxiliary popup coordination, chunk panel additions.
- `ui/remote_web/js/features/e621EventPanel.mjs`: new E621 event browser/editor panel.
- `ui/remote_web/js/features/ollamaPanel.mjs`: new Ollama remote control panel.
- `ui/remote_web/js/features/instantWildcardPanel.mjs`: new instant wildcard editor panel, currently not wired from `app.js`/`index.html`.
- `ui/remote_web/js/features/chunkPanel.mjs`: standalone positioning, add-chunk form, use-selection flow.
- `ui/remote_web/index.html`, `ui/remote_web/style.css`: E621/Ollama buttons, boot indicator, E621/Ollama/chunk styles.
- `modules/prompt_engineering_module.py`: web-facing preset helpers, debug snapshot, mode/preset initialization adjustments.
- `modules/ollama_module.py`: lazy TagDB/resource loading.
- `NAIA_cold_v4.py`, `core/dll_fix.py`, `core/middle_section_controller.py`, `interfaces/base_module.py`, `tabs/setting_tabs.py`, `ui/interactive/image_tagger_block.py`: startup/deferred init, DLL loading, module initialization compatibility.

## Validation Already Run

Passed:

- `node --check ui/remote_web/app.js`
- `node --check` for changed Remote Web feature modules
- `python -m py_compile` for changed Python files

Previously failed:

- `git diff --check`
  - Main blocker: massive trailing whitespace in `modules/prompt_engineering_module.py`.
  - Also note line-ending warnings on `core/dll_fix.py` and several Remote Web `.mjs` files.

## P0 Stabilization Update

Completed in the current P0 round:

- Normalized the `modules/prompt_engineering_module.py` diff so only the actual double-initialize guard remains.
- Wired `ui/remote_web/js/features/instantWildcardPanel.mjs` into the existing WC panel through an `Instant Editor` action instead of adding another top-level launcher button.
- Added minimal Instant Wildcard editor CSS.
- Re-ran static validation:
  - `node --check ui/remote_web/app.js`
  - `node --check` for changed Remote Web feature modules
  - `python -m py_compile` for changed Python files
  - `git diff --check`
  - FastAPI static smoke for `/js/features/e621EventPanel.mjs`, `/js/features/ollamaPanel.mjs`, `/js/features/instantWildcardPanel.mjs`

## Recent Tracking Update

Completed after the P0 stabilization pass:

- Chunk UX stabilization:
  - standalone/anchored placement no longer covers the prompt editor;
  - add-chunk writes through instant wildcard upsert and refreshes Chunk state;
  - selected prompt text uses a custom context menu that keeps normal text-edit actions and adds `Add to Chunk`.
- `Tools & Assistants` IA compression:
  - `프롬프트 엔지니어링` is kept as the fixed primary button;
  - the remaining launchers are grouped into three categories: `프롬프트 도구`, `NAI 전용 도구`, and `자동화 / 고급 기능`;
  - module metadata and category state are centralized in `ui/remote_web/js/features/moduleLauncher.mjs`;
  - category buttons mirror child active, disabled, and badge/status state.
- `Tools & Assistants` follow-up:
  - `NAI 전용 도구` no longer collapses `Character`, `Char Ref`, and `Vibe` counts into one total; it shows per-module `C/R/V` badge chips.
  - launcher text was enlarged slightly, and the fixed `프롬프트 엔지니어링` button is left-aligned.
  - Vibe upload/storage activation now also disables all Character Reference frames, matching the existing Char Ref → Vibe exclusion path.
- Vibe Transfer Remote Web follow-up:
  - Reference Strength now has a direct numeric input (`-1.00` to `1.00`, step `0.01`) synced with the slider.
  - The Vibe Reference Strength slider hit area and thumb are larger for easier dragging.
- Result context menu follow-up:
  - `프롬프트 불러오기`, `프롬프트 다시개봉`, `생성 설정 복원`, `파일 위치 열기`, `이미지 저장`, `PNG로 클립보드 복사`, and `WEBP로 클립보드 복사` are now wired from the Remote Web context menu.
  - Current-result reroll uses the existing random prompt pipeline with the current history item's `source_row`; saved thumbnails remain reroll-disabled.
  - Saved-result prompt/settings actions load image metadata directly; current-result prompt/settings actions prefer `/api/result/metadata`.

## Immediate Risks

- `Tools & Assistants` has been compressed into the planned `1 + 3` launcher. Remaining risk is visual/manual smoke across desktop, mobile drawer, NAI/non-NAI mode, and Shared Mode.
- `core/remote_api_server.py` gained about 1k lines; next stabilization should focus on behavior smoke and then adapter extraction, not more feature growth.
- No browser/manual Remote Web smoke was observed in this audit.
- Result context menu clipboard image writes depend on browser Clipboard API support, especially for WEBP.

## Next Task Assignment

### P0 — Stabilize Current Remote Web Round

Owner: backend/frontend integrator

1. Normalize `modules/prompt_engineering_module.py` whitespace and line endings until `git diff --check` passes.
2. Resolve `instantWildcardPanel.mjs` status:
   - preferred: wire it through `app.js`, `index.html`, and module popup state if a standalone editor is intended;
   - otherwise remove/defer the file before commit.
3. Run required static checks:
   - `node --check ui/remote_web/app.js`
   - `node --check ui/remote_web/js/features/*.mjs` for changed files
   - `python -m py_compile` for changed Python files
   - `git diff --check`
4. FastAPI static smoke for new assets:
   - `/js/features/e621EventPanel.mjs`
   - `/js/features/ollamaPanel.mjs`
   - `/js/features/instantWildcardPanel.mjs` only if wired/kept
5. Checkpoint commit once the above passes.

### P1 — Tools & Assistants IA Refactor

Owner: frontend/product flow

Status: implemented; needs manual visual smoke.

Goal: replace the flat module button grid with a `1 + 3` structure so module growth does not make the control area harder to scan.

Required structure:

- Fixed primary button: `프롬프트 엔지니어링`
- Category 1, `프롬프트 도구`: `E621`, `Wildcard`, `Chunk`, `Cond`
- Category 2, `NAI 전용 도구 (다른 모드에서 차단)`: `Character`, `Char Ref`, `Vibe`
- Category 3, `자동화 / 고급 기능`: `Ollama`, `Automation`

Implementation notes:

- Keep `프롬프트 엔지니어링` as a standalone always-visible button because it is mandatory in the generation workflow.
- Replace the remaining flat buttons in `ui/remote_web/index.html` with three category controls that expose leaf modules through a compact popup/dropdown/segmented panel.
- Preserve existing module actions: leaf selection should still call `openModule(moduleId)` or `openChunkPanel(...)` without changing server protocol.
- Bubble status to the category level:
  - active state if any child module is open;
  - badge count if any child has a badge;
  - disabled/NAI-only/shared-mode state if all usable children are blocked, with leaf-level blocked reasons preserved.
- Move module metadata into a single JS registry in `ui/remote_web/app.js` or a new `js/features/moduleLauncher.mjs`:
  - title
  - category
  - action type (`module` vs `chunk`)
  - NAI-only / shared-mode blocked flags
  - badge element id
- After registry extraction, use it for title lookup, active state, mode/shared availability, and category rendering so new modules are registered once.
- Mobile requirement: categories must remain usable in the drawer without horizontal overflow; category popups should close on module open and on outside click.

Validation:

- Desktop and mobile screenshot check for the category launcher.
- NAI vs non-NAI mode: `Character`, `Char Ref`, `Vibe` disabled behavior still correct.
- Shared Mode: blocked modules still blocked and existing toast behavior remains.
- Open/close/toggle behavior remains correct for `프롬프트 엔지니어링`, a normal module, and `Chunk`.

### P2 — Remote Web Behavior Smoke

Owner: QA/product flow

1. E621 panel:
   - load state, switch category/folder/tag, star/unstar, hide/restore, search/reset, wiki-search toggle, generate from testbench.
2. Ollama panel:
   - offline/installed/server-online status, refresh, start/stop, convert, cancel, copy output, progress/stage display.
3. Chunk/Instant Wildcard:
   - open standalone and anchored, insert at cursor, add chunk, use selection, reload, verify prompt text update.
4. Layout:
   - desktop and mobile viewport checks for E621, Ollama, chunk, module popup close/reopen behavior.

### P3 — Bridge Debt Reduction

Owner: backend architect

After P0/P1/P2, extract module-specific bridge logic out of `core/remote_api_server.py`:

- `e621_event` DTO/read/set helpers
- `ollama` DTO/read/set helpers
- `instant_wildcard` file/read/set helpers

Target outcome: `remote_api_server.py` keeps WS routing and thread handoff; module behavior moves into testable adapter/helper units.

### P4 — Web Shell Contract Continuation

Owner: product/architecture

Continue the `future01` Web Shell audit follow-ups:

- prompt/params/generation bridge contract
- image viewer/history contract
- settings/session contract
- decision on whether Remote Web code is shared directly or split into a Desktop Web Shell package

## Recommended Next Concrete Task

P0 is complete. Discuss P1 launcher IA before implementation, then run P2 behavior smoke against the launcher structure users will actually keep using.
