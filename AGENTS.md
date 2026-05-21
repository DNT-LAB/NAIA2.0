# Codex workspace guidance

## Project Docs

- Additional planning and handoff material can live under `docs/`.
- Markdown documents are intentionally ignored by the default git flow for distributable builds, so treat `docs/` materials as local reference unless the user explicitly asks to include them.
- For preset-axis, composer, or desktop/web parity work, check `docs/` for supporting contracts before changing UI/API behavior.

## App Packaging

- For Electron/App build work, check `release_package/` first.
- `release_package/` is a gitignored local packaging workspace for reusable packaging code snapshots, build manifests, and release validation references.
- Do not assume files under `release_package/` are tracked. If a packaging change must become part of the source contract, mirror it back to the tracked source paths under `app/electron/`, `tools/`, `tests/`, or `release_assets/`.
- Keep normal git-clone web execution separate from Electron packaging. Electron/App release work should not make npm installation mandatory for users who only run the headless web session.
- Treat `PROJECT_LAYOUT_POLICY.md` as the source of truth for runtime/layout ownership. The default product path is Python Headless Web; Electron is an optional shell only.
- Keep canonical Remote Web source changes under `app/web/remote`. Do not recreate `ui/remote_web`; it is an old source path kept only as a documented legacy/fallback reference.
- For layout/runtime boundary work, run `python tools/check_project_layout_policy.py` before finishing.
- For refactor-plan driven work, keep `python tools/check_refactor_plan_execution_contract.py` passing so gate setup, implementation, modification, deletion, verification, post-work evaluation, and commit handling stay explicit.

## Remote Web UI

- UI-related work should use Chrome for inspection and validation.
- For remote-web tasks, first check whether `http://127.0.0.1:7243/` is reachable.
- Chrome DevTools Protocol is the default browser validation path for local Remote Web UI work.
- CDP outline:
  - Launch Chrome with a temporary profile and a debug port, for example `--headless=new --remote-debugging-port=9334 --user-data-dir=%TEMP%\codex-naia-cdp --no-first-run --no-default-browser-check --disable-sync --window-size=1100,900 http://127.0.0.1:7243/`.
  - Query `http://127.0.0.1:<port>/json/list` to find the page target and connect to `webSocketDebuggerUrl`.
  - Use DevTools methods such as `Runtime.evaluate`, `Page.reload`, and `Page.captureScreenshot` to open popups, simulate hover/focus/click states, inspect computed styles, and save screenshots.
  - Prefer temporary profiles and close the launched browser process after validation.
- If the remote server is not running, start it from the repository root with:

```bat
call venv\Scripts\activate.bat
python NAIA_web_headless.py
```
