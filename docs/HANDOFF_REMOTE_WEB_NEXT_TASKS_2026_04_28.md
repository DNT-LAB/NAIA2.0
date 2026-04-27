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

Failed:

- `git diff --check`
  - Main blocker: massive trailing whitespace in `modules/prompt_engineering_module.py`.
  - Also note line-ending warnings on `core/dll_fix.py` and several Remote Web `.mjs` files.

## Immediate Risks

- `modules/prompt_engineering_module.py` appears line-ending/whitespace noisy; it must be normalized before a checkpoint commit.
- `ui/remote_web/js/features/instantWildcardPanel.mjs` is untracked and appears unwired; decide whether to integrate it as a module panel or remove/defer it.
- `core/remote_api_server.py` gained about 1k lines; next stabilization should focus on behavior smoke and then adapter extraction, not more feature growth.
- New `.mjs` files need FastAPI static route smoke checks because `ui/remote_web/CLAUDE.md` requires explicit static serving validation for new JS assets.
- No browser/manual Remote Web smoke was observed in this audit.

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

### P1 — Remote Web Behavior Smoke

Owner: QA/product flow

1. E621 panel:
   - load state, switch category/folder/tag, star/unstar, hide/restore, search/reset, wiki-search toggle, generate from testbench.
2. Ollama panel:
   - offline/installed/server-online status, refresh, start/stop, convert, cancel, copy output, progress/stage display.
3. Chunk/Instant Wildcard:
   - open standalone and anchored, insert at cursor, add chunk, use selection, reload, verify prompt text update.
4. Layout:
   - desktop and mobile viewport checks for E621, Ollama, chunk, module popup close/reopen behavior.

### P2 — Bridge Debt Reduction

Owner: backend architect

After P0/P1, extract module-specific bridge logic out of `core/remote_api_server.py`:

- `e621_event` DTO/read/set helpers
- `ollama` DTO/read/set helpers
- `instant_wildcard` file/read/set helpers

Target outcome: `remote_api_server.py` keeps WS routing and thread handoff; module behavior moves into testable adapter/helper units.

### P3 — Web Shell Contract Continuation

Owner: product/architecture

Continue the `future01` Web Shell audit follow-ups:

- prompt/params/generation bridge contract
- image viewer/history contract
- settings/session contract
- decision on whether Remote Web code is shared directly or split into a Desktop Web Shell package

## Recommended Next Concrete Task

Start with P0. The current work is close to a checkpoint, but committing before `git diff --check` and the unwired `instantWildcardPanel.mjs` decision would leave avoidable cleanup debt.
