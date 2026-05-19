# Web Session Measurement (desktop)

Generated: 2026-05-19T12:50:53+09:00

Commit: `ea58887`

Command:

```powershell
python tools/measure_web_session_startup.py --entrypoint desktop --port 7292 --cdp-port 9392 --include-generate
```

## Timings

| Metric | Seconds |
| --- | --- |
| `fastapi_listen` | 11.438 |
| `api_status_200` | 11.469 |
| `remote_web_first_paint` | 14.188 |
| `random_click_to_prompt_update` | 3.641 |
| `generate_click_to_dispatch` | 0.204 |

## Memory

| Checkpoint | RSS MB |
| --- | --- |
| `after_listen` | 1459.41 |
| `after_status` | 1479.35 |
| `after_first_paint` | 1772.54 |
| `after_action_ready` | 1802.22 |
| `after_random` | 1895.82 |
| `after_generate_dispatch` | 1896.27 |
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
        "ready": false,
        "live_path_allows_build": false
      },
      "translation_cache_size": 0,
      "result_cache_size": 0
    }
  },
  "remote_web_first_paint": {
    "title": "NAIA Remote",
    "readyState": "complete",
    "bodyChars": 412,
    "hasRandom": true,
    "hasGenerate": true,
    "promptLength": 0,
    "randomDisabled": false,
    "generateDisabled": false
  },
  "remote_web_action_ready": {
    "title": "NAIA Remote",
    "readyState": "complete",
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
      "value": "1girl, 1.15::artist:totomono ::, 0.85::artist:nns (sobchan) ::, 0.65::artist:daram (shappydude), artist:jon (pixiv31559095), ::, 0.45::artist:tianliang duohe fangdongye ::, 0.55::artist:utatanecocoa ::, 0.6::artist:moromoro 0p0 ::, 0.65::artist:healthyman ::, 0.65::artist:kedama milk ::, 0.45::artist:mikozin ::, -0.5::artist collaboration ::, 2::loli, young female ::, \n\n, \n#랜덤프롬프트\n, bikini, bracer, breasts, collar, hair flower, muscular, muscular female, ocean, robe, sand, solo, swimsuit, thick thighs, thighs, tree, \n\n, 0.8::blender (medium), airbrush (medium), shiny skin ::, 0.1::light particles ::, 0.4::realistic, cel shading, hatching (texture), graphite (medium), muted color ::, 0.5::depth of field, simple background, mosaic censoring, dynamic expressions ::, 1=2, dutch angle, low-angle view, perspective, -0.6:: thick outlines, absurdly detailed composition, detailed background ::, best quality, masterpiece, very absurdres, year 2024, year 2025",
      "length": 962,
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
| `stdout` | C:\VNR\NAIA2.0\logs\round30_web_session_7292_20260519_125053.out.log |
| `stderr` | C:\VNR\NAIA2.0\logs\round30_web_session_7292_20260519_125053.err.log |
| `import_audit` | C:\VNR\NAIA2.0\logs\round30_import_audit_7292_20260519_125053.jsonl |

## Interpretation

For the desktop-backed WebShell, PyQt, `ModernMainWindow`, `ImageWindow`,
`MiddleSectionController`, and `RemoteBridge` are expected to appear. For the
headless entrypoint, those signals should be absent while Remote Web startup,
Random, and Generate dispatch remain functional.
