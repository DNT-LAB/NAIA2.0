# Round 30 Headless Web Baseline

Generated: 2026-05-19T11:19:45+09:00

Commit: `ec56d2b`

Command:

```powershell
python tools/measure_web_session_startup.py --port 7276 --cdp-port 9376 --include-generate
```

## Timings

| Metric | Seconds |
| --- | --- |
| `fastapi_listen` | 11.11 |
| `api_status_200` | 12.797 |
| `remote_web_first_paint` | 13.485 |
| `random_click_to_prompt_update` | 3.641 |
| `generate_click_to_dispatch` | 0.093 |

## Memory

| Checkpoint | RSS MB |
| --- | --- |
| `after_listen` | 1690.68 |
| `after_status` | 1615.74 |
| `after_first_paint` | 1728.85 |
| `after_action_ready` | 1797.31 |
| `after_random` | 1890.16 |
| `after_generate_dispatch` | 1890.62 |
| `after_shutdown` | None |

## Runtime Dependency Audit

| Signal | Value |
| --- | --- |
| `pyqt6_imported` | True |
| `remote_api_server_imported` | True |
| `middle_section_controller_imported` | True |
| `modern_main_window_constructed` | True |
| `image_window_constructed` | True |
| `middle_section_controller_constructed` | True |
| `remote_bridge_constructed` | True |
| `middle_module_imports_count` | 2 |
| `tracked_imports_count` | 113 |

Middle module import sample:

```text
modules.character_module
modules.character_module.CharacterSearchDialog
```

## Checks

```json
{
  "api_status": {
    "is_generating": false,
    "api_mode": "NAI",
    "autocomplete": {
      "kr_tags_loaded": true,
      "metadata_fallback": {
        "ready": true,
        "live_path_allows_build": false
      },
      "translation_cache_size": 0,
      "result_cache_size": 0
    }
  },
  "remote_web_first_paint": {
    "title": "NAIA Remote",
    "readyState": "interactive",
    "bodyChars": 412,
    "hasRandom": true,
    "hasGenerate": true,
    "promptLength": 0,
    "randomDisabled": false,
    "generateDisabled": false
  },
  "remote_web_action_ready": {
    "title": "NAIA Remote",
    "readyState": "interactive",
    "bodyChars": 412,
    "hasRandom": true,
    "hasGenerate": true,
    "promptLength": 0,
    "randomDisabled": false,
    "generateDisabled": false
  },
  "random_prompt": {
    "forced_options": {
      "promptFixed": "false",
      "autoGenerate": "false",
      "promptLength": 0
    },
    "before": {
      "title": "NAIA Remote",
      "readyState": "complete",
      "bodyChars": 466,
      "hasRandom": true,
      "hasGenerate": true,
      "promptLength": 0,
      "randomDisabled": false,
      "generateDisabled": false
    },
    "after": {
      "value": "1girl, 1.15::artist:totomono ::, 0.85::artist:nns (sobchan) ::, 0.65::artist:daram (shappydude), artist:jon (pixiv31559095), ::, 0.45::artist:tianliang duohe fangdongye ::, 0.55::artist:utatanecocoa ::, 0.6::artist:moromoro 0p0 ::, 0.65::artist:healthyman ::, 0.65::artist:kedama milk ::, 0.45::artist:mikozin ::, -0.5::artist collaboration ::, 2::loli, young female ::, \n\n, \n#랜덤프롬프트\n, bare legs, blush, bra, breasts, collarbone, frown, full body, holding, holding can, indoors, long shirt, messy room, nose blush, shirt, short sleeves, socks, solo, striped clothes, striped socks, t-shirt, tears, thick thighs, thighs, underwear, unworn bra, \n\n, 0.8::blender (medium), airbrush (medium), shiny skin ::, 0.1::light particles ::, 0.4::realistic, cel shading, hatching (texture), graphite (medium), muted color ::, 0.5::depth of field, simple background, mosaic censoring, dynamic expressions ::, 1=2, dutch angle, low-angle view, perspective, -0.6:: thick outlines, absurdly detailed composition, detailed background ::, best quality, masterpiece, very absurdres, year 2024, year 2025",
      "length": 1083,
      "randomDisabled": false
    },
    "random_log_marker": "🌐 Remote: core search 랜덤 프롬프트 생성됨"
  },
  "generate_dispatch_marker": "🌐 Remote: 생성 트리거됨"
}
```

## Logs

| Log | Path |
| --- | --- |
| `stdout` | C:\VNR\NAIA2.0\logs\round30_web_session_7276_20260519_111945.out.log |
| `stderr` | C:\VNR\NAIA2.0\logs\round30_web_session_7276_20260519_111945.err.log |
| `import_audit` | C:\VNR\NAIA2.0\logs\round30_import_audit_7276_20260519_111945.jsonl |

## Interpretation

This baseline is expected to show desktop-backed WebShell behavior:

- PyQt is imported.
- `ModernMainWindow` is constructed.
- `ImageWindow` and middle-section startup code are constructed.
- `RemoteBridge` owns the websocket/server bridge.

Later headless rounds must compare against this file and remove these signals from the headless entrypoint one by one.
