# Round 30 Measurement Harness

## Goal

Create a repeatable baseline for the current desktop-backed Remote WebSession before introducing the real headless entrypoint.

This round is intentionally diagnostic. It does not remove PyQt. It proves what still loads today and gives later rounds comparable numbers.

## TODO Checklist

- [x] Confirm the current round plan.
- [x] Add a repeatable startup measurement script.
- [x] Launch `NAIA_cold_v4.py --web-shell` from the repo virtualenv.
- [x] Measure process start to FastAPI socket listen.
- [x] Measure process start to `/api/status` first 200.
- [x] Use Chrome/CDP to measure Remote Web first paint.
- [x] Use Chrome/CDP to click Random and measure prompt update latency.
- [x] Use Chrome/CDP to click Generate and measure generation dispatch latency.
- [x] Record process RSS checkpoints.
- [x] Record an import/dependency audit for PyQt, desktop window objects, RemoteBridge, and middle modules.
- [x] Save JSON logs under `logs/`.
- [x] Save the human-readable baseline under `refactor_docs/`.
- [x] Run static validation for the new script.
- [x] Run a real browser/CDP validation pass with Random and Generate.

## When Done

- [x] One command can reproduce the measurement baseline.
- [x] The baseline reports startup, first status, first paint, Random, Generate dispatch, RSS, and dependency signals.
- [x] The measurement confirms whether the current WebShell still constructs desktop PyQt objects.
- [x] The result is documented so later rounds can compare against it.

## Command

```powershell
python tools/measure_web_session_startup.py --port 7276 --cdp-port 9376 --include-generate --output-json logs\round30_web_session_baseline.json --write-summary refactor_docs\round_30_headless_web_baseline.md
```

## Result

- FastAPI listen: 11.11 seconds
- `/api/status` 200: 12.797 seconds
- Remote Web first paint: 13.485 seconds
- Random click to prompt update: 3.641 seconds
- Generate click to dispatch marker: 0.093 seconds
- RSS after action-ready: 1797.31 MB
- RSS after random: 1890.16 MB
- RSS after generate dispatch: 1890.62 MB

Dependency audit:

- `PyQt6` imported: yes
- `ModernMainWindow` constructed: yes
- `ImageWindow` constructed: yes
- `MiddleSectionController` constructed/imported: yes
- `RemoteBridge` constructed: yes
- Middle module imports: `modules.character_module`, `modules.character_module.CharacterSearchDialog`

## Static Review

- The script uses the repo virtualenv by default to avoid measuring a broken system-Python startup.
- The script starts Chrome with a temporary user profile and a CDP debug port, then removes the profile.
- The script disables Remote Web auto-generate during measurement so Random latency is not polluted by an immediate generation request.
- The script terminates both the NAIA process tree and the Chrome process tree during cleanup.
- Logs remain under ignored `logs/`; only the measurement script and documentation are committed.

## Follow-up

Round 31 should not continue with another subjective startup cleanup. It should build a PyQt-free `WebSessionContext` skeleton and prove it can be imported/constructed without `PyQt6`.
