# Round 51 - Decommission Gate Validation

## Objective

Prove that Desktop App removal is real for the supported Remote Web runtime.

## TODO Checklist

- [x] Run fresh-process import audit for supported launch and supported service imports.
- [x] Run focused pytest for headless app, API setup, prompt generation, generation request, result/history, and supported optional workflows.
- [x] Run CDP against the supported launch path.
- [x] Click Random and Generate in the browser.
- [x] Validate actual image result display for the NAI backend.
- [x] Validate history, WEBP latest-image, PNG export, metadata, and API setup modal.
- [x] Verify no process logs mention `NAIA_cold_v4`, `QApplication`, `ModernMainWindow`, `ImageWindow`, `RemoteBridge`, `MiddleSectionController`, or `TabController`.
- [x] Re-run startup measurement and compare against the Round 39 headless baseline.
- [x] Patch the final PyQt lazy import regression found during actual generation.
- [x] Add regression coverage for the patched API service paths.

## When Done

- `python NAIA_web_headless.py` is the supported launch path and works through the browser.
- CDP proves Random, Generate, result preview, history, image export, metadata, and API setup are functional.
- Runtime import audit reports no `PyQt6`, `legacy_desktop`, `core.remote_api_server`, Desktop controllers, or PyQt middle modules.
- Focused tests pass without relying on Desktop App imports.
- The roadmap can mark Desktop App decommission complete for the supported runtime.

## Result

- Patched `core.api_service.APIService` so headless cleanup and NAI image-byte helper paths no longer import PyQt.
- Added a fresh-process regression test that blocks `PyQt6`, calls the patched helper paths, and verifies a PIL image result.
- Focused validation: `156 passed in 18.39s`.
- Startup measurement on port `7319`: first paint `1.813s`, Generate dispatch `0.110s`, PyQt import audit `false`.
- Actual browser generation on port `7318`: Random prompt generated, Generate completed, preview image displayed at `832 x 1216`, `/api/latest-image` returned `image/webp`, `/api/result/image/png` returned `image/png`, metadata returned generation params, and API setup modal rendered saved backend statuses.
- Actual generation import audit: `pyqt6_imported=false`, `legacy_desktop_imported=false`, `middle_module_imports_count=0`, tracked imports `0`.

Desktop App decommission is complete for the supported Remote Web runtime. The archived Desktop App package remains only under `legacy_desktop/` as unsupported legacy code.
