# Web Session Measurement (headless)

Generated: 2026-05-19T17:41:10+09:00

Commit: `1589c55`

Note: the measurement ran with the Round 51 working-tree patch applied before
the final cleanup commit was created, so this commit field is the pre-commit
HEAD used by the measurement harness.

Command:

```powershell
python tools/measure_web_session_startup.py --entrypoint headless --port 7319 --cdp-port 9419 --include-generate
```

## Timings

| Metric | Seconds |
| --- | --- |
| `fastapi_listen` | 1.094 |
| `api_status_200` | 1.141 |
| `remote_web_first_paint` | 1.813 |
| `random_click_to_prompt_update` | 6.25 |
| `generate_click_to_dispatch` | 0.11 |

## Memory

| Checkpoint | RSS MB |
| --- | --- |
| `after_listen` | 118.93 |
| `after_status` | 119.25 |
| `after_first_paint` | 121.11 |
| `after_action_ready` | 125.15 |
| `after_random` | 1366.93 |
| `after_generate_dispatch` | 1366.94 |
| `after_shutdown` | None |

## Runtime Dependency Audit

| Signal | Value |
| --- | --- |
| `pyqt6_imported` | False |
| `legacy_desktop_imported` | False |
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
    "readyState": "interactive",
    "bodyChars": 409,
    "hasRandom": true,
    "hasGenerate": true,
    "promptLength": 0,
    "randomDisabled": false,
    "generateDisabled": false
  },
  "remote_web_action_ready": {
    "title": "NAIA Remote",
    "readyState": "interactive",
    "bodyChars": 439,
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
      "value": "1girl, 1.15::artist:totomono ::, 0.85::artist:nns (sobchan) ::, 0.65::artist:daram (shappydude), artist:jon (pixiv31559095), ::, 0.45::artist:tianliang duohe fangdongye ::, 0.55::artist:utatanecocoa ::, 0.6::artist:moromoro 0p0 ::, 0.65::artist:healthyman ::, 0.65::artist:kedama milk ::, 0.45::artist:mikozin ::, -0.5::artist collaboration ::, 2::loli, young female ::, \n\n, \n#랜덤프롬프트\n, breasts, chinese clothes, crystal earrings, dalachi (headdress), dress, earrings, hat, jewelry, long sleeves, own hands together, solo, tabard, wide sleeves, \n\n, 0.8::blender (medium), airbrush (medium), shiny skin ::, 0.1::light particles ::, 0.4::realistic, cel shading, hatching (texture), graphite (medium), muted color ::, 0.5::depth of field, simple background, mosaic censoring, dynamic expressions ::, 1=2, dutch angle, low-angle view, perspective, -0.6:: thick outlines, absurdly detailed composition, detailed background ::, best quality, masterpiece, very absurdres, year 2024, year 2025",
      "length": 984,
      "randomDisabled": false
    },
    "random_log_marker": "Headless Remote: random prompt generated"
  },
  "generate_dispatch_marker": "Headless Remote: generation request queued"
}
```

## Logs

| Log | Path |
| --- | --- |
| `stdout` | C:\VNR\NAIA2.0\logs\round30_web_session_7319_20260519_174110.out.log |
| `stderr` | C:\VNR\NAIA2.0\logs\round30_web_session_7319_20260519_174110.err.log |
| `import_audit` | C:\VNR\NAIA2.0\logs\round30_import_audit_7319_20260519_174110.jsonl |

## Interpretation

For the supported headless entrypoint, PyQt, `legacy_desktop`, `RemoteBridge`,
`ModernMainWindow`, `ImageWindow`, and Desktop controllers should be absent
while Remote Web startup, Random, and Generate dispatch remain functional.
The optional `--entrypoint desktop` comparison path is legacy-only.
