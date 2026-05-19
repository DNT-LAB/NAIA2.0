# Round 40 - Dead Code First Pass

## Scope

Start dead-code cleanup after the Headless Web Session cutover. This round only removes files with strong evidence that they are not part of the app runtime, dynamic registries, or active pytest suite.

## Dead-Code Criteria

- The file is tracked by git.
- The file is not imported by app entrypoints.
- The file is not referenced by `MIDDLE_MODULE_SPECS` or `TAB_MODULE_SPECS`.
- The file is not collected as an active pytest test.
- Removing it does not affect the headless Remote Web core workflow.

## TODO Checklist

- [x] Confirm the current headless/web-core boundary docs.
- [x] Check git status before deletion.
- [x] Run static import/reference checks for candidate files.
- [x] Run `pytest --collect-only` to identify stale root-level test scripts.
- [x] Remove only confirmed stale files.
- [x] Run static validation after deletion.
- [x] Commit the scoped cleanup.

## Removal Candidates

### Remove in this round

- `not_implement/turbo_module.py`
  - Unused PyQt placeholder.
  - Not referenced by app registries.
  - Only referenced by the dependency-map documentation.
- `test_instant_wildcard.py`
  - Root-level manual Qt smoke script.
  - Not collected as an active pytest test.
  - Replaced for headless purposes by `tests/test_instant_wildcard_service.py`.
- `test_temp_params.py`
  - Root-level manual import smoke script with top-level side effects.
  - Not collected as an active pytest test.
- `test_temp_params_simple.py`
  - Duplicate ASCII-only variant of `test_temp_params.py`.
  - Not collected as an active pytest test.
- `test_sequence_parser.py`
  - Root-level custom test runner.
  - Produces pytest collection warning because its class has `__init__`.
- `test_sequence_integration.py`
  - Root-level custom test runner.
  - Produces pytest collection warning because its class has `__init__`.

### Do not remove in this round

- `core/sequence_parser.py`
  - Still imported by `core/generation_controller.py`.
- `artist_dictionary.py`, `danbooru_character.py`, `result_dupl.py`, `result_dict_copyright.py`
  - Large generated dictionaries, still imported by tag/character/artist paths.
- `tools/*.py`
  - CLI/audit utilities are not app entrypoints but remain operational tooling.
- `NAIA_generation_old.py`, `artist_tab_old.py`
  - Ignored local legacy files, not tracked by git. Leave local cleanup separate.

## When Done

- The removed files no longer appear in `git ls-files`.
- `pytest --collect-only -q` no longer reports warnings from removed root scripts.
- Targeted headless/web tests still pass.
- The commit contains only the deletion and supporting refactor docs/plan updates.
