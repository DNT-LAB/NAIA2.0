# Round 47 tab surface validation

Generated: 2026-05-19T15:52:30+09:00

## CDP Scenario

- Headless server: `http://127.0.0.1:7305/`
- Chrome CDP port: `9405`
- Loaded the Remote Web UI, waited for WebSocket startup, applied headless tab capabilities, opened Thumb, then opened Characters.

## Checks

```json
{
  "server_listening": true,
  "artists_hidden": true,
  "thumb_visible": true,
  "characters_visible": true,
  "thumb_cards": 9,
  "thumb_status": "시대/연대 스타일 · 9 styles",
  "character_cards": 9,
  "character_status": "9,738 characters",
  "active_tab": "characters"
}
```

## Dependency Audit

```json
{
  "forbidden_loaded": [],
  "tracked_imports_count": 0,
  "tracked_imports_sample": []
}
```

## Logs

- stdout: `C:\VNR\NAIA2.0\logs\round47_web_session_7305.out.log`
- stderr: `C:\VNR\NAIA2.0\logs\round47_web_session_7305.err.log`
- import audit: `C:\VNR\NAIA2.0\logs\round47_import_audit_7305.jsonl`
