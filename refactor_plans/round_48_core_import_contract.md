# Round 48 - Core Qt Import Contract

## Plan Check

Round 48 is the guard round before physical desktop archive/removal. It does not move destructive legacy files yet. It fixes the supported import contract so later rounds can remove or relocate desktop controllers without guessing what the headless runtime uses.

## TODO Checklist

- [x] Audit every `core/*.py` PyQt import.
- [x] Split the current module list into supported headless imports and legacy desktop imports.
- [x] Add a fresh-process test that blocks PyQt and desktop controllers while importing supported headless core services.
- [ ] Physically split or archive Qt worker/signal modules.
- [ ] Replace remaining lazy Qt fallbacks inside shared services.
- [ ] Move legacy desktop controllers out of the supported tree.

## When Done

- Supported headless core imports are test-guarded against PyQt and desktop controller imports.
- Legacy desktop core modules are documented before Round 49 file moves.
- `NAIA_web_headless.py` still starts and passes CDP startup/random validation.
- Remaining destructive core moves are explicitly deferred to Round 49.

## Validation

- `python -m pytest tests\test_requirements_split.py::test_supported_headless_core_services_import_with_qt_blocked -q`
- `python tools\measure_web_session_startup.py --entrypoint headless --port 7306 --cdp-port 9406 --output-json logs\round48_core_import_contract_cdp.json --write-summary refactor_docs\round_48_core_import_contract_validation.md`
