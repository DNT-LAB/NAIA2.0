# Round 51 Decommission Gate Validation

Generated: 2026-05-19

## Scope

Round 51 is the final evidence gate for the Desktop App removal roadmap. It checks that the supported Remote Web runtime launches through `NAIA_web_headless.py`, works through the browser, and does not import the archived Desktop App stack.

## Fix Applied During Gate

The first actual generation gate exposed a remaining PyQt lazy import inside `core.api_service.APIService._cleanup_http_threads`. That cleanup path imported `PyQt6.QtCore.QThreadPool` and `QCoreApplication` after a real NovelAI generation completed.

The fix keeps legacy cleanup behavior only when Qt is already loaded:

- `APIService._cleanup_http_threads` now reads `PyQt6.QtCore` from `sys.modules` instead of importing it.
- NAI upscale/background-removal image byte helpers now return PIL images in headless mode and only create `QPixmap` when `PyQt6.QtGui` is already loaded by a legacy desktop process.
- A fresh-process regression test blocks all `PyQt6` imports, calls the cleanup and image-byte helper paths, and verifies `PyQt6` stays absent from `sys.modules`.

## Validation

### Static and Unit Tests

```powershell
python -m py_compile core\api_service.py
```

Result: passed.

```powershell
python -m pytest tests\test_web_session_app.py tests\test_web_session_context.py tests\test_api_config_service.py tests\test_prompt_generation_service.py tests\test_result_image_payload_service.py tests\test_requirements_split.py tests\test_web_shell_config.py tests\test_clothes_preset_service.py tests\test_event_preset_service.py tests\test_expression_preset_service.py tests\test_preset_composer_service.py tests\test_preset_input_bridge.py tests\test_prompt_engineering_runtime.py tests\test_character_settings.py tests\test_automation_settings.py tests\test_api_service_webui_hires.py tests\test_api_service_artist_thumb_resolution.py -q
```

Result: `156 passed in 18.39s`.

### Startup Measurement

Measurement doc: `refactor_docs/round_51_startup_measurement.md`.

```powershell
python tools\measure_web_session_startup.py --entrypoint headless --port 7319 --cdp-port 9419 --include-generate --output-json logs\round51_startup_measurement.json --write-summary refactor_docs\round_51_startup_measurement.md
```

Result:

| Metric | Round 39 Headless | Round 51 |
| --- | ---: | ---: |
| Remote Web first paint | 2.360s | 1.813s |
| Generate dispatch | 0.094s | 0.110s |
| RSS after first paint | 123.48 MB | 121.11 MB |
| Import audit `PyQt6` | false | false |
| Import audit `legacy_desktop` | false | false |
| Middle module imports | 0 | 0 |

The measurement harness disables external generation execution and validates startup, Random, Generate dispatch, and import audit.

### Actual Browser Generation Gate

Command under test:

```powershell
venv\Scripts\python.exe -u NAIA_web_headless.py --host 127.0.0.1 --port 7318
```

CDP port: `9418`.

Result:

| Check | Result |
| --- | --- |
| FastAPI listen | 1.093s |
| Browser action ready | 0.250s |
| Random click to prompt update | 7.563s |
| Generate click to completed result | 2.515s |
| Preview image | 832 x 1216 |
| `/api/latest-image` | `image/webp` |
| `/api/result/image/png` | `image/png` |
| `/api/result/metadata` | width `832`, height `1216`, steps `1`, model `NAID4.5F` |
| API setup modal | opened; NAI/WEBUI/COMFYUI saved statuses rendered |
| Process log completed marker | `Headless Remote: generation completed` |

Runtime dependency audit during the actual generation gate:

| Signal | Value |
| --- | --- |
| `pyqt6_imported` | false |
| `legacy_desktop_imported` | false |
| `remote_api_server_imported` | false |
| `middle_section_controller_imported` | false |
| `middle_module_imports_count` | 0 |
| `modern_main_window_constructed` | false |
| `image_window_constructed` | false |
| `remote_bridge_constructed` | false |
| tracked imports | 0 |

Forbidden terminal-log markers were absent:

- `NAIA_cold_v4`
- `QApplication`
- `ModernMainWindow`
- `ImageWindow`
- `RemoteBridge`
- `MiddleSectionController`
- `TabController`

## Result

The supported Remote Web runtime now passes the Desktop App decommission gate. The repository still keeps archived Desktop App code under `legacy_desktop/`, but it is not imported by the supported launch path, default launchers no longer start it, and the actual browser Generate workflow works without PyQt.
