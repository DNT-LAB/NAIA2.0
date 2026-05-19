# Web Session Measurement (headless)

Generated: 2026-05-19T15:57:16+09:00

Commit: `5f18a13`

Command:

```powershell
python tools/measure_web_session_startup.py --entrypoint headless --port 7306 --cdp-port 9406
```

## Timings

| Metric | Seconds |
| --- | --- |
| `fastapi_listen` | 1.453 |
| `api_status_200` | 1.5 |
| `remote_web_first_paint` | 2.359 |
| `random_click_to_prompt_update` | 6.563 |
| `generate_click_to_dispatch` | None |

## Memory

| Checkpoint | RSS MB |
| --- | --- |
| `after_listen` | 119.14 |
| `after_status` | 119.51 |
| `after_first_paint` | 124.07 |
| `after_action_ready` | 124.86 |
| `after_random` | 1338.25 |
| `after_shutdown` | None |

## Runtime Dependency Audit

| Signal | Value |
| --- | --- |
| `pyqt6_imported` | False |
| `remote_api_server_imported` | False |
| `middle_section_controller_imported` | False |
| `modern_main_window_constructed` | False |
| `image_window_constructed` | False |
| `middle_section_controller_constructed` | False |
| `remote_bridge_constructed` | False |
| `middle_module_imports_count` | 0 |
| `tracked_imports_count` | 0 |

Middle module import sample:

```text

```

## Checks

```json
{
  "api_status": {
    "is_generating": false,
    "api_mode": "NAI",
    "autocomplete": {
      "kr_tags_loaded": false,
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
    "bodyChars": 450,
    "hasRandom": true,
    "hasGenerate": true,
    "promptLength": 0,
    "randomDisabled": false,
    "generateDisabled": false
  },
  "remote_web_action_ready": {
    "title": "NAIA Remote",
    "readyState": "complete",
    "bodyChars": 452,
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
      "bodyChars": 446,
      "hasRandom": true,
      "hasGenerate": true,
      "promptLength": 0,
      "randomDisabled": false,
      "generateDisabled": false
    },
    "after": {
      "value": "1girl, 1.15::artist:totomono ::, 0.85::artist:nns (sobchan) ::, 0.65::artist:daram (shappydude), artist:jon (pixiv31559095), ::, 0.45::artist:tianliang duohe fangdongye ::, 0.55::artist:utatanecocoa ::, 0.6::artist:moromoro 0p0 ::, 0.65::artist:healthyman ::, 0.65::artist:kedama milk ::, 0.45::artist:mikozin ::, -0.5::artist collaboration ::, 2::loli, young female ::, \n\n, \n#랜덤프롬프트\n, ass, bare back, bare shoulders, blush, breasts, chromatic aberration, cowboy shot, dress, from behind, hand up, median furrow, parted lips, profile, shoulder blades, solo, wet, \n\n, 0.8::blender (medium), airbrush (medium), shiny skin ::, 0.1::light particles ::, 0.4::realistic, cel shading, hatching (texture), graphite (medium), muted color ::, 0.5::depth of field, simple background, mosaic censoring, dynamic expressions ::, 1=2, dutch angle, low-angle view, perspective, -0.6:: thick outlines, absurdly detailed composition, detailed background ::, best quality, masterpiece, very absurdres, year 2024, year 2025",
      "length": 1003,
      "randomDisabled": false
    },
    "random_log_marker": "Headless Remote: random prompt generated"
  },
  "generate_dispatch_marker": "skipped"
}
```

## Logs

| Log | Path |
| --- | --- |
| `stdout` | C:\VNR\NAIA2.0\logs\round30_web_session_7306_20260519_155716.out.log |
| `stderr` | C:\VNR\NAIA2.0\logs\round30_web_session_7306_20260519_155716.err.log |
| `import_audit` | C:\VNR\NAIA2.0\logs\round30_import_audit_7306_20260519_155716.jsonl |

## Interpretation

For the desktop-backed WebShell, PyQt, `ModernMainWindow`, `ImageWindow`,
`MiddleSectionController`, and `RemoteBridge` are expected to appear. For the
headless entrypoint, those signals should be absent while Remote Web startup,
Random, and Generate dispatch remain functional.
