# Round 50 - Launch, Requirements, and Docs Cleanup

## Goal

Make the supported setup and launch path match the Desktop App decommission:
normal users install headless requirements and start `NAIA_web_headless.py`.

## TODO Checklist

- [x] Change default Windows launcher `run_NAIA.bat` to headless.
- [x] Change default macOS launcher `run_NAIA.command` to headless.
- [x] Change `run_NAIA_test_only.bat` so it no longer starts Legacy Desktop.
- [x] Keep PyQt dependencies out of default/platform requirements.
- [x] Keep Legacy Desktop dependencies isolated in `requirements-desktop-legacy*.txt`.
- [x] Update tests so default launchers cannot regress to `legacy_desktop/NAIA_cold_v4.py`.
- [x] Update measurement tooling wording and defaults so headless is the supported path.
- [x] Record CDP validation for Random and Generate dispatch.

## When Done

- `run_NAIA*` default launchers install `requirements-headless.txt`.
- `run_NAIA*` default launchers start `NAIA_web_headless.py`.
- Default requirement files contain no PyQt, WebEngine, QScintilla, Windows desktop integration packages, or Turbo-only `ultralytics`.
- Legacy Desktop can only be reached by an explicit manual command under `legacy_desktop/`.
- CDP validation confirms headless Remote Web starts, Random works, Generate dispatches, and no PyQt or `legacy_desktop` modules are imported.
