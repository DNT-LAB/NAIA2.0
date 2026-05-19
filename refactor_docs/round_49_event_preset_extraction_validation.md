# Web Session Measurement (headless)

Generated: 2026-05-19T16:46:21+09:00

Commit: `4b4c36a`

Command:

```powershell
python tools/measure_web_session_startup.py --entrypoint headless --port 7312 --cdp-port 9412 --include-generate
```

## Timings

| Metric | Seconds |
| --- | --- |
| `fastapi_listen` | 1.437 |
| `api_status_200` | 1.484 |
| `remote_web_first_paint` | 2.375 |
| `random_click_to_prompt_update` | 6.344 |
| `generate_click_to_dispatch` | 0.11 |

## Memory

| Checkpoint | RSS MB |
| --- | --- |
| `after_listen` | 119.12 |
| `after_status` | 119.59 |
| `after_first_paint` | 123.47 |
| `after_action_ready` | 124.88 |
| `after_random` | 1348.49 |
| `after_generate_dispatch` | 1348.5 |
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
      "value": "1girl, 1.15::artist:totomono ::, 0.85::artist:nns (sobchan) ::, 0.65::artist:daram (shappydude), artist:jon (pixiv31559095), ::, 0.45::artist:tianliang duohe fangdongye ::, 0.55::artist:utatanecocoa ::, 0.6::artist:moromoro 0p0 ::, 0.65::artist:healthyman ::, 0.65::artist:kedama milk ::, 0.45::artist:mikozin ::, -0.5::artist collaboration ::, 2::loli, young female ::, \n\n, \n#랜덤프롬프트\n, :d, blouse, blush stickers, breasts, brooch, double peace, hat, jewelry, mob cap, open mouth, sash, shirt, smile, solo, upper body, peace sign, wide-eyed, wrist cuffs, \n\n, 0.8::blender (medium), airbrush (medium), shiny skin ::, 0.1::light particles ::, 0.4::realistic, cel shading, hatching (texture), graphite (medium), muted color ::, 0.5::depth of field, simple background, mosaic censoring, dynamic expressions ::, 1=2, dutch angle, low-angle view, perspective, -0.6:: thick outlines, absurdly detailed composition, detailed background ::, best quality, masterpiece, very absurdres, year 2024, year 2025",
      "length": 994,
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
| `stdout` | C:\VNR\NAIA2.0\logs\round30_web_session_7312_20260519_164621.out.log |
| `stderr` | C:\VNR\NAIA2.0\logs\round30_web_session_7312_20260519_164621.err.log |
| `import_audit` | C:\VNR\NAIA2.0\logs\round30_import_audit_7312_20260519_164621.jsonl |

## Interpretation

For the desktop-backed WebShell, PyQt, `ModernMainWindow`, `ImageWindow`,
`MiddleSectionController`, and `RemoteBridge` are expected to appear. For the
headless entrypoint, those signals should be absent while Remote Web startup,
Random, and Generate dispatch remain functional.

## Round 49E Static Checks

- `python -m compileall -q core\event_preset`
- `python -m py_compile core\event_preset_service.py core\preset_composer_service.py ui\event_preset\event_preset_window.py ui\interactive\quick_search_block.py`
- `python -m pytest tests\test_event_preset_service.py tests\test_preset_composer_service.py tests\test_tag_search_index.py -q` -> 25 passed
- `python -m pytest tests\test_web_session_app.py tests\test_requirements_split.py tests\test_web_shell_config.py -q` -> 39 passed
- Fresh-process headless app import audit for `ui`, `PyQt6`, and `legacy_desktop` -> no modules loaded

## Round 49E Result

The supported Event Preset service now imports `core.event_preset.*` helpers instead of `ui.event_preset.*`. The remaining root `ui/` references are PyQt UI wrappers or legacy desktop callers, which makes the next archive round mechanically safer.
