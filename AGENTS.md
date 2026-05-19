# Codex workspace guidance

## Project Docs

- Additional planning and handoff material can live under `docs/`.
- Markdown documents are intentionally ignored by the default git flow for distributable builds, so treat `docs/` materials as local reference unless the user explicitly asks to include them.
- For preset-axis, composer, or desktop/web parity work, check `docs/` for supporting contracts before changing UI/API behavior.

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
