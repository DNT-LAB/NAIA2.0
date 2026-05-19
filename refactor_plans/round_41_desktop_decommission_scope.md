# Round 41 - Desktop App Decommission Scope

## Scope

Clarify the next target after Headless Web Session migration. The current codebase still contains a working PyQt Desktop App. That is expected from Rounds 30-40, but it means the larger "Desktop App removal" goal is not complete.

Round 41 is the planning and guardrail round for actual decommission work. It should not delete `NAIA_cold_v4.py` or PyQt surfaces yet; it should identify which workflows still depend on them and define the removal gates.

The concrete multi-round execution plan now lives in `refactor_plans/desktop_app_decommission_roadmap.md`.

## Current Reality

- Remote Web core workflow can run headlessly through `NAIA_web_headless.py`.
- Desktop App can still run through `NAIA_cold_v4.py`.
- Desktop-backed WebShell remains available as compatibility mode.
- Optional surfaces still tied to PyQt include Studio, Turbo Sequence, advanced tab tooling, desktop result actions, and some WEBUI/COMFYUI parity paths.

## TODO Checklist

- [x] Create the Desktop App decommission roadmap.
- [x] Define round-level TODO lists and When Done gates.
- [x] Build a Desktop App dependency inventory from entrypoints, imports, dynamic registries, and packaging requirements.
- [x] Classify PyQt surfaces as `migrate`, `retire`, `archive`, or `keep-as-separate-desktop-package`.
- [x] Decide the default launcher contract: headless Remote Web by default, desktop launcher removed or explicitly legacy.
- [x] Identify all `PyQt6` imports that remain in supported Remote Web runtime paths.
- [x] Identify all user-visible workflows that still require Desktop App fallback.
- [ ] Add tests that fail if supported headless launch imports `PyQt6`.
- [ ] Add a removal checklist for `core.remote_api_server.RemoteBridge`, desktop tab/module controllers, and PyQt wrappers.
- [ ] Run CDP validation after each workflow migration or retirement.

## Round 41 Result

- Added `refactor_docs/round_41_desktop_dependency_inventory.md`.
- Confirmed `NAIA_web_headless.py` should become the default Web Session launch path in Round 42.
- Confirmed `NAIA_cold_v4.py` and the Desktop App should be marked legacy before archive/removal.
- Recorded PyQt import counts by bucket:
  - `core/`: 14
  - `interfaces/`: 2
  - `modules/`: 12
  - `tabs/`: 45
  - `ui/`: 81
  - `tools/`: 1
  - `tests/`: 6
  - `NAIA_cold_v4.py`: 1
- Classified dynamic tabs, middle modules, RemoteBridge feature groups, requirements, and user-visible workflows.

## When Done

- The project has an explicit Desktop App decommission map.
- Every remaining Desktop App dependency has an owner decision: migrate, retire, archive, or separate package.
- No work item can call Desktop App removal complete merely because Remote Web has a headless core path.
- The next implementation round can remove or archive one concrete Desktop-only surface without guessing.

## Non-Goals

- Do not delete the desktop app entrypoint in this round.
- Do not remove generated dictionaries or shared core services.
- Do not remove optional workflows until their web-native replacement or retirement decision is documented.
