# NAIA2 Project Layout Policy

## Product Runtime Boundary

The default NAIA2 product is Python Headless Web:

- Backend: `NAIA_web_headless.py` and FastAPI services under `core/`.
- Web UI: Remote Web served by the headless backend.
- User setup: Python plus `pip install -r requirements-headless.txt`.
- Launchers: `run_NAIA_web.bat`, `run_NAIA_web.command`, and compatibility launchers that call the same headless web entrypoint.

Electron is optional. It is a desktop shell and release/portable packaging path around the same Python backend and the same Remote Web UI. Electron must not make npm, Node, Electron, or Docker mandatory for normal git-clone web execution.

Legacy PyQt6/QWebApplication Desktop has been removed from source ownership. Historical behavior may be recovered from git history when needed, but it is not an active reference tree or product baseline for new work.

## Legacy Desktop Removal Rule

Legacy Desktop source must stay removed from the active tree:

- Removed root: `legacy_desktop/`.
- Removed entrypoint: `legacy_desktop/NAIA_cold_v4.py`.
- Valid use: historical inspection through git history only.
- Invalid use: default launchers, normal clone-user setup, release shell behavior, new feature ownership, or active tests.
- Any remaining desktop-only PyQt surfaces must be classified as release-excluded rebuild/delete candidates, not as active legacy desktop code.

Default launchers must not reference `legacy_desktop`, `NAIA_cold_v4.py`, or `requirements-desktop-legacy*`.

## Canonical Source Owners

```text
NAIA2.0/
  core/                  # Python domain/service core for headless runtime
  app/
    backend/             # optional shell/launcher backend adapters
    web/remote/          # canonical Remote Web UI source
    electron/            # optional Electron shell only
  release_package/       # reusable packaging workspace, gitignored by default
  release_assets/        # manifests, contracts, release gates
  tests/
    headless/
    electron_shell/
```

The canonical Remote Web source is `app/web/remote`. The older `ui/remote_web` path has been removed from source ownership and must not receive new feature work. Compatibility fallback code may still recognize that path only for old checkouts or explicit local overrides, not as an active source directory.

## Default Execution Rules

- Default launch scripts must call `NAIA_web_headless.py`.
- Default launch scripts must install or reference `requirements-headless.txt`.
- Default launch scripts must not require npm, Node, Electron, or Docker.
- `NAIA_web_headless.py` must remain importable without PyQt6 and without `legacy_desktop`.
- Remote Web static serving should resolve `app/web/remote` before any compatibility fallback.

## Two Track Boundary

NAIA2 has two runtime/distribution tracks, not two application codebases.

Track A is the clone-user source web track:

- Entry: `NAIA_web_headless.py` through `run_NAIA_web.*` or compatibility launchers.
- Dependency boundary: Python plus `requirements-headless.txt`.
- Forbidden requirements: npm, Node, Electron, Docker, bundled Python, Electron packaging.
- UI source: `app/web/remote`.

Track B is the Electron release shell track:

- Entry: `app/electron/package.json` and `app/electron/main/main.cjs`.
- Dependency boundary: maintainer/release tooling only.
- Responsibility: shell lifecycle, maintenance view, backend launch, logs/data-folder shortcuts, packaged runtime bootstrap.
- Forbidden responsibility: prompt processing, generation dispatch, queue semantics, and Remote Web feature forks.

Both tracks share `core/web_session_app.py`, `core/runtime_paths.py`, and `app/web/remote`. A feature that cannot work in the source web track is not considered supported merely because the Electron shell can hide or wrap it.

## Electron Boundary

Allowed Electron source and release-maintainer paths:

- `app/electron/`
- `release_package/`
- `release_assets/`
- `tools/`
- `tests/electron_shell/`

Electron may own:

- Desktop shell lifecycle.
- Backend process launch and restart from a packaged release.
- Maintenance window.
- App-window menu, icon, logs, data folder, and browser fallback controls.

Electron must not own:

- Prompt processing.
- Generation dispatch.
- Generation queue semantics.
- Runtime data ownership.
- Core feature behavior.
- Normal clone-user setup.

Docker is optional release infrastructure only. It must not appear in the normal user execution path.

## Runtime And Generated Data

Runtime, user, cache, build, and generated roots must not become source owners. These paths are runtime/build outputs:

- `logs/`
- `output/`
- `save/`
- `temp/`
- `tmp/`
- `app/electron/dist/`
- `app/electron/node_modules/`
- `release_package/`
- `wildcards/` in packaged/runtime user mode

Downloaded data belongs under runtime/user-data roots or reviewed bootstrap/sample paths, not arbitrary source directories.

## Move-Only Rule

Filesystem reorganization must be split from behavior changes.

Move-only rounds may:

- Move one ownership group at a time.
- Add temporary compatibility imports.
- Update tests, manifests, and docs for the moved path.

Move-only rounds must not:

- Change prompt generation behavior.
- Change generation dispatch behavior.
- Change queue semantics.
- Add new user-visible features.
- Reintroduce deleted legacy desktop code instead of rebuilding against headless/web contracts.

## Cleanup Candidate Rule

Cleanup and deletion are separate from layout policy enforcement. Candidate lists must be recorded before any destructive cleanup, and candidate manifests must require explicit approval for every delete-capable group.

Cleanup candidate manifests must identify:

- Owner.
- Current status.
- Replacement or migration target.
- Candidate paths or globs.
- Required gates before deletion.
- Explicit delete-approval requirement.

Round 9 cleanup may be marked complete only when delete candidates and their gates are recorded. Actual deletion remains deferred until a focused candidate group receives explicit user approval.

## Refactor Plan Execution Protocol

Active refactor plans must be executable, not only descriptive. A plan that is used to drive implementation must state how the round handles:

- Plan review.
- Gate setup or gate reuse.
- Implementation.
- Modification and rework after failed verification.
- Deletion through approved candidate groups only.
- Verification and static review.
- Post-work evaluation against When Done conditions.
- Targeted staging and commit handling.

The tracked execution contract is `release_assets/manifests/refactor_plan_execution_contract.json`; the checker is `python tools/check_refactor_plan_execution_contract.py`.

## Validation Gates

Layout and runtime-boundary changes should keep these checks passing:

- `python tools/check_project_layout_policy.py`
- `python tools/check_refactor_plan_execution_contract.py`
- `python tools/check_runtime_distribution_tracks.py`
- `python tools/check_project_layout_round_completion.py`
- `python tools/check_project_cleanup_candidates.py`
- `python tools/check_source_layout_contract.py`
- `python tools/check_headless_core_boundary.py`
- `python tools/check_runtime_asset_classification.py`
- `python tools/check_runtime_write_policy.py`
- `python tools/check_remote_web_feature_contract.py`

Electron-specific gates are release-maintainer checks, not normal clone-user startup requirements.
