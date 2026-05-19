# Round 47 - Tab Surface Migration, Retirement, Or Archive

## Plan Check

Round 47 follows the module workflow migration. The target is to remove supported headless dependence on PyQt `tabs/*` surfaces while preserving web-native tab workflows that already have a server contract.

## TODO Checklist

- [x] Classify desktop `TAB_MODULE_SPECS` entries against Remote Web tabs.
- [x] Keep Result and Metadata as headless-owned result/history/metadata services.
- [x] Migrate the Remote Web Thumb tab to a PyQt-free `StyleThumbnailService`.
- [x] Migrate the Remote Web Character Viewer tab to `CharacterViewerService` endpoints.
- [x] Keep Remote Web Studio as web-native JS state plus headless generation queue dispatch.
- [x] Hide Artist Thumbnail in the supported headless runtime until its large RemoteBridge service is extracted.
- [x] Keep desktop-only tabs documented as unsupported for headless import paths.
- [x] Add focused API tests for migrated Thumb and Character Viewer contracts.
- [x] Validate visible tabs through CDP.

## Decisions

| Surface | Decision | Headless Owner |
| --- | --- | --- |
| Result/Image history | migrated | `HeadlessResultStore` and `core.web_session_app` |
| Metadata / PNG Info | migrated | result metadata endpoints and web metadata viewer |
| Thumb | migrated | `core.style_thumbnail_service` |
| Characters | migrated | `core.character_viewer_service` |
| Studio | kept web-native | `ui/remote_web/js/features/studioTab.mjs` + headless generation queue |
| Artists | deferred/hidden | RemoteBridge-backed until Artist Thumbnail service extraction |
| Danbooru PyQt tab / web view | retired | no PyQt webview in headless |
| Img2Img/Inpaint tab | retired | image action endpoints are explicit headless unsupported |
| Depth Search tab | retired for tab surface | search/refine service work is separate from PyQt tab |
| Turbo Sequence | retired for headless | remains desktop legacy only |
| Comic Generator / Simple WebView / API Management / Settings PyQt tabs | retired for headless | replaced by Remote Web API setup or not supported |

## Validation

- `python -m py_compile core\web_session_app.py core\style_thumbnail_service.py tests\test_web_session_app.py`
- `node --check ui\remote_web\app.js`
- `node --check ui\remote_web\js\features\rightTabs.mjs`
- `python -m pytest tests\test_web_session_app.py tests\test_requirements_split.py tests\test_web_shell_config.py -q`
- CDP tab scenario on `http://127.0.0.1:7305/`

## When Done

- Headless Remote Web exposes no supported PyQt tab fallback.
- Supported visible right tabs have PyQt-free server contracts.
- Deferred tabs are hidden or return explicit unsupported behavior instead of 404 or desktop wakeup.
- CDP proves the visible headless tab set works in the browser without importing `core.tab_controller` or `tabs/*`.
