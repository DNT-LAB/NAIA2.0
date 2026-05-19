# Round 41 desktop dependency inventory

Generated: 2026-05-19

## Purpose

This document is the guardrail for Desktop App decommission. It records the current Desktop App dependency surface and assigns an initial decision to each area before any destructive removal starts.

## Inventory Commands

```powershell
rg -l "PyQt6" core modules tabs ui tools tests interfaces NAIA_cold_v4.py NAIA_web_headless.py
rg -n "NAIA_cold_v4.py|NAIA_web_headless|run_NAIA|run_NAIA_web|PyQt6" AGENTS.md docs refactor_docs refactor_plans
Get-Content core\tab_controller.py -TotalCount 130
Get-Content core\middle_section_controller.py -TotalCount 45
```

## Launch and Entrypoint Inventory

| Surface | Current role | Decision | Round | Blocker |
| --- | --- | --- | --- | --- |
| `NAIA_web_headless.py` | PyQt-free Remote Web entrypoint | keep as supported runtime | 42 | Must become the normal Web launch path. |
| `core.web_session_app` | Headless FastAPI app factory | keep | 42-51 | Must absorb remaining supported Remote Web APIs. |
| `NAIA_cold_v4.py` | PyQt Desktop App and desktop-backed WebShell | legacy, then archive/remove | 42, 49 | Optional workflows still need decisions. |
| `run_NAIA_web.bat` | Currently launches `NAIA_cold_v4.py --web-session` | migrate to `NAIA_web_headless.py` | 42 | Needs CDP startup validation. |
| `run_NAIA_web.command` | Currently launches `NAIA_cold_v4.py --web-session` | migrate to `NAIA_web_headless.py` | 42 | Needs command update and docs. |
| `run_NAIA.bat` | Desktop App launcher | mark explicit legacy | 42 | Keep until Round 49 archive/remove. |
| `run_NAIA.command` | Desktop App launcher | mark explicit legacy | 42 | Keep until Round 49 archive/remove. |
| `AGENTS.md` startup snippet | Mentions `python NAIA_cold_v4.py` when remote server is not running | update after default cutover | 50 | Round 42 should change launch reality first. |

## Requirement Inventory

| Dependency | Current reason | Decision | Round |
| --- | --- | --- | --- |
| `PyQt6`, `PyQt6-Qt6`, `PyQt6_sip` | Desktop widgets, signals, QApplication | move to legacy desktop requirements, then remove from supported Web install | 43 |
| `PyQt6-WebEngine`, `PyQt6-WebEngine-Qt6` | Embedded desktop web shell and browser tabs | move to legacy desktop requirements | 43 |
| `PyQt6-QScintilla` | Desktop editing/widgets | move to legacy desktop requirements | 43 |
| `pywinpty` | Desktop terminal tooling | move to legacy/optional if terminal stays desktop-only | 43 |
| `pypiwin32`, `pywin32`, `pywin32-ctypes`, `win10toast` | Windows desktop integration | split or keep only if headless services require them | 43 |
| `fastapi`, `uvicorn[standard]`, `requests`, `pillow`, `pandas`, `pyarrow`, `numpy`, `scipy`, `keyring`, `cryptography`, `tiktoken` | Headless/server/core functionality | keep in supported headless requirements if import validation confirms use | 43 |
| `ultralytics`, `googletrans`, `websocket-client` | Optional services/tools | decide per workflow, do not treat as Desktop-only solely by name | 43 |

## PyQt Import Inventory

`rg -l "PyQt6"` currently finds PyQt references in these buckets:

| Bucket | File count | Decision |
| --- | ---: | --- |
| `NAIA_cold_v4.py` | 1 | legacy/archive/remove after supported workflows migrate. |
| `interfaces/` | 2 | split Qt base classes from service interfaces; supported headless interfaces must be PyQt-free. |
| `core/` | 14 | split Qt controllers/workers from shared services in Round 48. |
| `modules/` | 12 | migrate useful behavior to services or retire wrappers in Round 46. |
| `tabs/` | 45 | migrate, retire, or archive tab surfaces in Round 47. |
| `ui/` | 81 | migrate only web-needed behavior; otherwise archive as desktop UI in Round 49. |
| `tools/` | 1 | keep measurement tooling but ensure default supported path audits headless. |
| `tests/` | 6 | split legacy desktop tests from supported headless regression tests. |

Critical headless blockers in `core/`:

- `core.remote_api_server.py`: desktop-backed RemoteBridge compatibility adapter.
- `core.middle_section_controller.py`: dynamic PyQt middle module loader.
- `core.tab_controller.py`: dynamic PyQt tab loader.
- `core.main_controller.py`: desktop generation and result orchestration.
- `core.generation_controller.py`: Qt worker/signal generation path still used by desktop.
- `core.prompt_generation_controller.py`, `core.search_controller.py`, `core.api_validator.py`: Qt signal/controller wrappers.
- `core.autocomplete_manager.py`, `core.ui_state_manager.py`, `core.temp_window_manager.py`: desktop-widget helpers.

## Dynamic Tab Registry Decision Matrix

| Tab module | File | Current web status | Decision | Round | Notes |
| --- | --- | --- | --- | --- | --- |
| `ImageViewerModule` | `tabs/image_window.py` | replaced for headless core by `HeadlessResultStore` | archive/remove after result actions migrate | 45, 47 | Result preview/history core already headless; desktop-specific actions remain. |
| `BrowserTabModule` | `tabs/web_view.py` | unsupported in headless | retire/archive | 47 | QWebEngine desktop browser tab. |
| `PngInfoTabModule` | `tabs/png_info_tab.py` | partially replaced by metadata endpoints | migrate useful metadata endpoints, retire UI | 47 | Keep PNG metadata service-level behavior only. |
| `ThumbnailsTabModule` | `tabs/thumbnails_tab.py` | unsupported in headless | retire or migrate to result history service | 47 | Needs product decision. |
| `ArtistThumbModule` | `tabs/artist_thumb_tab.py` | Remote Web has service/UI overlap | migrate remaining bundle/state logic, archive desktop tab | 47 | Existing memory says server and desktop both carry mode/path logic; consolidate server-side. |
| `StudioTab` | `tabs/studio_tab.py` | Remote Web placeholder/optional | migrate or retire | 47 | Requires separate web-native storyboard/sequence service if kept. |
| `SettingsTabModule` | `tabs/setting_tabs.py` | API setup mostly replaced by `ApiConfigService` | archive after remaining settings migrate | 42, 47 | Save dir and non-API settings need inventory. |
| `APIManagementTabModule` | `tabs/api_management_window.py` | replaced by setup modal/service for core API setup | retire/archive | 47 | Keep service, not PyQt tab. |
| `DepthSearchTabModule` | `tabs/depth_search_window.py` | unsupported | retire or migrate to web tag/search service | 47 | Must not block core decommission. |
| `Img2ImgTabModule` | `tabs/img2img_tab.py` | unsupported | retire or migrate to result image input service | 45, 47 | Tied to desktop windows/result actions. |
| `SimpleWebViewTabModule` | `tabs/simple_web_view.py` | unsupported | retire/archive | 47 | QWebEngine surface. |
| `TurboEventSequenceTabModule` | `tabs/turbo_event_sequence_tab.py` | blocked in hidden WebSession | retire or migrate to Event Stream | 47 | Event Stream direction exists; do not keep PyQt tab as supported runtime. |
| Removed guards | `Hooker`, `Storyteller`, `Assets` | already blocked | keep retired | 47 | Do not reintroduce without web-native contract. |

## Middle Module Decision Matrix

| Module | Current headless replacement | Decision | Round | Notes |
| --- | --- | --- | --- | --- |
| `AutomationModule` | `core.automation_settings` partial | migrate or retire panel | 46 | Server-side scheduling/state needs product decision. |
| `CharacterModule` | `core.character_settings` | migrate saved-state/runtime only; archive desktop editor | 46 | Avoid loading PyQt character widget for prompt generation. |
| `CharacterReferenceModule` | partial request params/services | migrate storage/state or retire controls | 46 | Clipboard/UI paths are desktop-only. |
| `PromptListModifierModule` | `core.conditional_prompt_runtime`, `core.conditional_prompt_settings` | keep runtime, migrate/retire editor | 46 | Rule execution already headless; editor remains PyQt. |
| `E621EventModuleV2` | Remote Web panels and tag services partial | migrate or retire | 46 | Needs exact feature parity decision. |
| `InstantWildcardModule` | `core.instant_wildcard_service` | keep service, archive wrapper | 46 | Headless wildcard data should stay service-owned. |
| `OllamaModule` | `core.ollama_service` partial | migrate or retire | 46 | Optional AI helper, not core. |
| `PromptEngineeringModule` | `core.prompt_engineering_runtime`, settings | keep runtime, migrate/retire editor/actions | 46 | Runtime hooks already headless. |
| `ReferenceInsetAutoInjectModule` | `core.reference_inset_service` | keep service, archive wrapper | 46 | Hook path already headless. |
| `VibeTransferModule` | request param normalization partial | migrate or retire | 46 | Clipboard/image UI is desktop-only. |
| `WildcardStatusModule` | `core.wildcard_status_settings` | keep settings service, archive wrapper | 46 | Runtime must remain PyQt-free. |

## RemoteBridge Feature Decision Matrix

| Feature group | Current owner | Decision | Round |
| --- | --- | --- | --- |
| Startup/session/options/params/API setup | `WebSessionContext`, `ApiConfigService`, `core.web_session_app` | keep headless-owned | 42, 44 |
| Random prompt | `HeadlessRandomPromptService` | keep headless-owned | 44 |
| NAI Generate/result/latest image/history | `HeadlessGenerationService`, `HeadlessResultStore` | keep headless-owned | 45 |
| WEBUI/COMFYUI generation | normalized headless request, execution parity incomplete | validate support or retire | 45 |
| Search/tag/autocomplete/filter tools | mostly `RemoteBridge` plus services | migrate to PyQt-free service or retire | 44, 46 |
| Result enhance/upscale | `RemoteBridge`/desktop-adapter paths | migrate WEBUI-supported subset or retire | 45 |
| File/folder/storage/clipboard viewers | desktop adapter | retire or replace with server-safe file APIs | 44, 45 |
| Preset panels/events/clothes/expression | mixed service and `RemoteBridge` | migrate service-owned panels | 44, 46 |
| Desktop window visibility/control | desktop-backed only | retire from supported headless runtime | 44 |
| Legacy aliases (`api_config_result`, `api_test_result`, `mode_result`, `prompt_tokens`) | `RemoteBridge` compatibility | remove after client no longer expects them | 44 |

## Workflow Matrix

| Workflow | Current owner | Remote Web replacement | Decision | Blocker | Validation |
| --- | --- | --- | --- | --- | --- |
| API setup/status | Settings tab + RemoteBridge + `ApiConfigService` | `ApiConfigService` and setup modal | migrate complete; remove desktop fallback | Launcher/docs still point to desktop | CDP setup modal, tests for `ApiConfigService`. |
| Random prompt | desktop controllers plus headless service | `HeadlessRandomPromptService` | migrate complete for core | First Random memory load remains optimization, not Desktop blocker | CDP Random and no-PyQt import audit. |
| NAI generation | desktop generation controller and headless service | `HeadlessGenerationService` + APIService | migrate complete for core | Save/result actions still mixed | CDP actual Generate, result/history endpoints. |
| WEBUI generation | desktop/APIService/RemoteBridge mixed | headless request exists | validate or retire | Need actual execution parity | CDP actual WEBUI Generate if supported. |
| COMFYUI generation | desktop/APIService/workflow manager mixed | headless request exists | validate or retire | Workflow loading/result extraction parity | CDP/API test if supported. |
| Result preview/history | `ImageWindow` + RemoteBridge | `HeadlessResultStore` | migrate mostly complete | Save all, result actions, enhance/upscale | CDP result display/history/PNG export. |
| Save directory/settings | Settings tab + RemoteBridge | partial server state | migrate | Non-API settings inventory missing | REST/websocket tests and UI check. |
| Prompt Engineering runtime | PyQt module + runtime | `core.prompt_engineering_runtime` | keep runtime, migrate/retire UI actions | Editor/preset management still desktop | Hook tests plus panel CDP if kept. |
| Conditional Prompt runtime | PyQt module + runtime | `core.conditional_prompt_runtime` | keep runtime, migrate/retire editor | Desktop editor/preset UI | Rule execution tests plus editor decision. |
| Character state | PyQt module + settings | `core.character_settings` | keep settings/runtime, retire or migrate editor | Character editor UI not web-native | Random/generation tests. |
| Character reference/vibe | PyQt modules | partial request services | migrate or retire | Clipboard/UI image state | Feature-specific tests if kept. |
| Artist Thumb | desktop tab + RemoteBridge + web feature | server-owned mode/bundle state | migrate remaining desktop mirror | Duplicate registry paths | Remote Web artist thumb tests/CDP. |
| Studio/Turbo Sequence | desktop tabs | no complete web-native service | retire or migrate to Event Stream | Large feature scope | Only validate if explicitly kept. |
| Img2Img/inpaint | desktop tabs/windows | partial web result image input | retire or migrate | Requires backend-safe image input flow | CDP if kept. |
| Depth/simple browser/web view | desktop tabs | none | retire/archive | QWebEngine-only value | Ensure not advertised/imported. |
| Terminal/interactive windows | desktop UI | none | legacy/archive | PyQt terminal widgets | Exclude from supported runtime. |

## Round 41 Decisions

- Default Web Session should move to `NAIA_web_headless.py` in Round 42.
- Desktop App should become explicit legacy immediately, not compatibility-by-default.
- Requirements must split before any claim that Desktop App is removed.
- Deletion should wait until RemoteBridge and module/tab decisions are migrated or retired.
- The first destructive file moves should target already-replaced tabs/wrappers after Round 44-47, not `NAIA_cold_v4.py` first.

## Round 41 Verification

This round is documentation and inventory only. Required checks:

- `git diff --check`
- Confirm the roadmap and this inventory both exist in tracked git state.
- Confirm Round 42 has enough information to cut over launch scripts without deleting the Desktop App.
