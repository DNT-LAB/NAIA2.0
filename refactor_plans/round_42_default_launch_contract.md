# Round 42 default launch contract

Generated: 2026-05-19

## Objective

Make the supported Web Session launch path start the PyQt-free headless server, and keep the old Desktop App / Desktop Web Shell paths explicit legacy only.

## TODO Checklist

- [x] Update `run_NAIA_web.bat` and `run_NAIA_web.command` to launch `NAIA_web_headless.py`.
- [x] Keep `run_NAIA.bat` and `run_NAIA.command` as explicit legacy desktop launchers.
- [x] Update `core.web_shell_config` so the legacy desktop entrypoint no longer opens QWebEngine by default.
- [x] Guard `NAIA_cold_v4.py --web-session` behind an explicit legacy flag.
- [x] Update primary docs that still point Remote Web users at `NAIA_cold_v4.py --web-session`.
- [x] Add focused tests for launcher text and launch-mode config.
- [x] Run static checks, focused tests, and CDP validation against the headless launch path.

## Result

- Web launchers now start `NAIA_web_headless.py`.
- Desktop launchers now call `NAIA_cold_v4.py --desktop`.
- `NAIA_cold_v4.py --web-session` exits unless `--allow-legacy-web-session` is explicitly supplied.
- `core.web_shell_config.should_launch_web_shell_by_default()` now returns `False`; QWebEngine shell launch is explicit via `--web-shell`.
- Primary docs now identify `NAIA_web_headless.py` as the supported Remote Web entrypoint.
- Measurement tooling now defaults to the headless entrypoint; the desktop-backed path remains available only as `--entrypoint desktop`.
- CDP validation output: `refactor_docs/round_42_headless_launch_validation.md`.

## Validation

- `python -m py_compile NAIA_web_headless.py NAIA_cold_v4.py core\web_shell_config.py tools\measure_web_session_startup.py`
- `python -m pytest tests\test_web_shell_config.py -q`
- `python -m pytest tests\test_web_session_app.py::test_headless_app_import_and_factory_do_not_import_pyqt_in_fresh_process tests\test_web_session_app.py::test_headless_websocket_generate_does_not_import_pyqt_in_fresh_process tests\test_web_session_app.py::test_headless_startup_random_and_generate_do_not_import_desktop_tabs_or_modules_in_fresh_process -q`
- `venv\Scripts\python.exe NAIA_cold_v4.py --web-session` exited `2` with the legacy guard message.
- `python tools\measure_web_session_startup.py --entrypoint headless --port 7295 --cdp-port 9395 --include-generate --action-timeout 60 --output-json logs\round42_headless_launch_validation.json --write-summary refactor_docs\round_42_headless_launch_validation.md`

## When Done

- `run_NAIA_web.*` starts `NAIA_web_headless.py`.
- Desktop launchers call `NAIA_cold_v4.py --desktop`.
- `NAIA_cold_v4.py --web-session` cannot silently start the desktop-backed Web Session.
- `python NAIA_web_headless.py --port <port>` serves Remote Web and passes Random / Generate dispatch checks through CDP.
- Import audit for the supported Web launch shows no `PyQt6`, `core.remote_api_server`, `ModernMainWindow`, `ImageWindow`, `MiddleSectionController`, or `TabController`.
