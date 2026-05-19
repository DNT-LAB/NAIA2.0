# Round 43 requirements and packaging split

Generated: 2026-05-19

## Objective

Separate the supported headless Remote Web install contract from legacy Desktop App dependencies so PyQt is not installed for normal Web Session use.

## TODO Checklist

- [x] Create `requirements-headless.txt` for the supported Remote Web runtime.
- [x] Make `requirements.txt`, `requirements_mac.txt`, and `requirements_linux.txt` delegate to the headless requirements file.
- [x] Move PyQt, WebEngine, QScintilla, pywinpty, Windows desktop integration packages, and Turbo-only `ultralytics` into legacy desktop requirements.
- [x] Add platform-specific legacy desktop requirements files.
- [x] Update Web Session launchers to install `requirements-headless.txt`.
- [x] Update legacy desktop launchers to install legacy desktop requirements.
- [x] Add dependency split regression tests.
- [x] Run fresh-process headless import tests with desktop modules blocked.
- [x] Run CDP validation against the headless launch path after the split.

## When Done

- Supported Remote Web setup installs no PyQt or Desktop App packages by default.
- Desktop-only dependency installation is explicitly legacy.
- A regression test fails if default/headless requirement files regain PyQt, WebEngine, QScintilla, pywinpty, Windows desktop integration, or Turbo-only `ultralytics`.
- Headless app imports still work while desktop imports are blocked.
- CDP validates startup, Random, Generate dispatch, and import audit on the headless launch path.

## Validation

- `python -m pytest tests\test_requirements_split.py tests\test_web_shell_config.py -q`
- `python -m pytest tests\test_web_session_app.py::test_headless_app_import_and_factory_do_not_import_pyqt_in_fresh_process tests\test_web_session_app.py::test_headless_startup_random_and_generate_do_not_import_desktop_tabs_or_modules_in_fresh_process -q`
- `python -m py_compile tests\test_requirements_split.py`
- `python tools\measure_web_session_startup.py --entrypoint headless --port 7296 --cdp-port 9396 --include-generate --action-timeout 60 --output-json logs\round43_headless_requirements_validation.json --write-summary refactor_docs\round_43_headless_requirements_validation.md`

## Result

- `requirements-headless.txt` is the supported Remote Web dependency set.
- `requirements.txt`, `requirements_mac.txt`, and `requirements_linux.txt` now install only the headless set.
- Legacy files:
  - `requirements-desktop-legacy.txt`
  - `requirements-desktop-legacy-mac.txt`
  - `requirements-desktop-legacy-linux.txt`
- CDP validation output: `refactor_docs/round_43_headless_requirements_validation.md`.
