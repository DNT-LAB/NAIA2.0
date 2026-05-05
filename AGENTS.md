# Codex workspace guidance

## Remote Web UI

- UI-related work should use `$Browser Use` as actively as practical for inspection and validation.
- For remote-web tasks, first check whether `http://127.0.0.1:7243/` is reachable.
- If the remote server is not running, start it from the repository root with:

```bat
call venv\Scripts\activate.bat
python NAIA_cold_v4.py
```
