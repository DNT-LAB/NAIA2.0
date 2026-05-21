# Two Track Runtime Distribution Boundary Round

## Goal

NAIA2를 두 개의 코드베이스로 쪼개지 않고, 두 개의 runtime/distribution track으로 분리한다.

- Track A: normal clone-user Python Headless Web execution.
- Track B: optional Electron release shell packaging.

Both tracks must share the same FastAPI backend, same Remote Web UI source, and same runtime path policy.

## Criteria

Track A is complete when:

- Source launchers run `NAIA_web_headless.py`.
- Source launchers install or reference `requirements-headless.txt`.
- Source launchers do not require npm, Electron, node_modules, Docker, or bundled Python.
- `requirements-headless.txt` does not include PyQt6 or Electron dependencies.
- The served Web UI source is `app/web/remote`.

Track B is complete when:

- Electron source stays under `app/electron`.
- Electron package `main` is `main/main.cjs`.
- Electron owns only shell lifecycle, maintenance view, backend launch, logs/data-folder shortcuts, and packaged runtime bootstrap.
- Electron does not own prompt processing, generation dispatch, queue semantics, or a forked Remote Web feature implementation.
- Electron points the backend to the same `app/web/remote` UI and the same `NAIA_web_headless.py` backend.

Shared boundary is complete when:

- `core/web_session_app.py`, `core/runtime_paths.py`, and `app/web/remote` are the shared product surface.
- `ui/remote_web` remains removed from source ownership.
- Release manifests include `app/web/remote/**` and exclude local runtime/build output.

## Execution Protocol

This round follows the standard refactor-plan execution pattern:

- Plan review: confirm the runtime/distribution boundary and the current repository state before editing.
- Gate setup: add or update manifest-backed validation before declaring the boundary complete.
- Implementation: change only the source Web, optional Electron shell, manifest, tool, and test surfaces required by this round.
- Modification: fix any failing gate inside the same round before broadening scope.
- Deletion: remove only paths covered by an approved cleanup candidate and required gates.
- Verification: run the round checker, focused tests, static review, and `git diff --check`.
- Post-work evaluation: compare the result against the When Done conditions and report deferred work.
- Commit: stage only intended files and create a round-scoped commit when requested.

## Implementation

- Add `release_assets/manifests/runtime_distribution_tracks.json`.
- Add `tools/check_runtime_distribution_tracks.py`.
- Add `tests/test_runtime_distribution_tracks.py`.
- Update `PROJECT_LAYOUT_POLICY.md` with the two-track boundary.
- Link the new manifest from `release_assets/manifests/project_layout_policy.json`.
- Add the new checker to release hard rules.

## Verification

Required checks:

- `python tools/check_runtime_distribution_tracks.py`
- `python tools/check_project_layout_policy.py`
- `python tools/check_release_distribution_strategy.py`
- `python -m pytest tests/test_runtime_distribution_tracks.py tests/test_project_layout_policy.py tests/test_release_asset_manifests.py tests/test_project_cleanup_candidates.py tests/test_project_layout_round_completion.py tests/test_remote_web_feature_contract.py tests/headless/test_remote_web_asset_resolver.py tests/test_web_shell_detached_geometry.py tests/test_stage_release_assets.py tests/test_runtime_paths.py`
- `git diff --check` for this round's touched files.

## Post-Work Evaluation

- Confirm whether the source Web track still runs without npm, Electron, Docker, or bundled Python.
- Confirm whether Electron remains a release shell instead of a second implementation.
- Confirm whether any deletion was candidate-scoped and approval-gated.
- Confirm whether runtime/generated artifacts were excluded from staging.

## When Done

- The repository has a machine-readable two-track contract.
- The source Web path is protected from npm/Electron/Docker leakage.
- The Electron release path is protected from becoming a second application implementation.
- The canonical Remote Web source remains single-owner under `app/web/remote`.
- The round is committed as a focused boundary/gate change.
