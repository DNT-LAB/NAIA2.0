# Round 40 dead-code audit

## Method

This pass used three checks:

1. Git tracking check with `git ls-files`.
2. Text/reference search with `rg` and `git grep`.
3. Pytest collection check with `pytest --collect-only -q`.

The static import graph was treated as advisory only because this project still has dynamic module and tab registries. Files referenced by `MIDDLE_MODULE_SPECS`, `TAB_MODULE_SPECS`, current app entrypoints, or active tests were not removed.

## Removed Files

| File | Reason |
| --- | --- |
| `not_implement/turbo_module.py` | Unused PyQt placeholder outside the app loading path. |
| `test_instant_wildcard.py` | Root-level manual Qt smoke script; not active pytest coverage. |
| `test_temp_params.py` | Root-level manual import smoke script with top-level side effects. |
| `test_temp_params_simple.py` | Duplicate root-level manual import smoke script. |
| `test_sequence_parser.py` | Root-level custom runner, not active pytest coverage; generated collection warning. |
| `test_sequence_integration.py` | Root-level custom runner, not active pytest coverage; generated collection warning. |

## Deferred Candidates

These appeared in advisory static scans but are not deleted in this round:

- `core/sequence_parser.py`: still used by `core.generation_controller`.
- `tools/*.py`: operational utilities, including the startup measurement harness.
- `ui/event_preset/*`, `ui/remote/*`, `ui/interactive/*`: desktop/optional surfaces need separate feature ownership review before removal.
- `NAIA_generation_old.py`, `artist_tab_old.py`: ignored local legacy files, not tracked by git.

## Follow-Up

- Add proper pytest coverage for `core.sequence_parser` before deleting or rewriting sequence-generation paths.
- Run a second pass focused on optional desktop-only UI packages after deciding whether desktop compatibility mode remains in scope.
- Do not delete large generated dictionary files without replacing the import sites in tag, artist, and character services.
