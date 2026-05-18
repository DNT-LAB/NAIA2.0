# Round 17 - Automation Headless State

## 1. 이번 라운드의 계획 확인

- Round 16 이후 hidden WebSession startup에서 `OllamaModule`, `WildcardStatusModule`, `E621EventModuleV2`, `ReferenceInsetAutoInjectModule`, `InstantWildcardModule`이 지연 로드된다.
- `AutomationModule`은 이전 라운드에서 보류됐다. Remote Web 초기 handshake와 server startup signal wiring이 `_find_module("automation")`을 통해 모듈을 즉시 깨우기 때문이다.
- 따라서 이번 라운드는 단순 lazy flag가 아니라, Remote Web 자동화 상태와 설정 저장을 PyQt widget 없이 유지하는 headless state를 먼저 만든다.

## 2. 작업 수행

- `core.automation_settings`를 추가해 `save/AutomationModule.json`의 기본값, 정규화, 저장/로드, Remote Web module-state 변환을 PyQt 없이 처리한다.
- `AutomationModule`의 JSON 저장/로드는 새 core helper에 위임하고, desktop UI wrapper와 기존 timer/controller 동작은 유지한다.
- `RemoteBridge`는 `_remote_automation_state`를 서버 소유 상태로 들고, `_read_automation()`에서 이미 로드된 `AutomationModule`만 읽는다. hidden WebSession 초기 handshake는 더 이상 `_find_module("automation")`을 호출하지 않는다.
- Remote Web의 `delay`, `random_delay`, `repeat`, `auto_type`, `timer_minutes`, `count_limit`, `notify` 변경은 module을 깨우지 않고 headless state와 JSON 설정에 반영한다.
- Remote Web의 `start`/`stop`만 기존 `AutomationModule`을 on-demand 로드하고 숨김 widget을 만든 뒤, main window callback과 automation signal을 연결한다.
- `start_remote_server()`의 자동화 signal wiring은 이미 로드된 desktop module만 연결하도록 바꿔 hidden WebSession startup에서 module wake를 제거했다.
- `MIDDLE_MODULE_SPECS`에서 `AutomationModule`을 hidden WebSession lazy 대상으로 표시했다.

## 3. 테스트 및 정적 리뷰 수행

- `python -m py_compile core\automation_settings.py core\middle_section_controller.py core\remote_api_server.py modules\automation_module.py`
- `python -m pytest tests\test_automation_settings.py tests\test_middle_section_controller_static_registry.py tests\test_remote_api_status.py -k "automation or middle_module" -q`
- `python -m pytest tests\test_middle_section_controller_static_registry.py tests\test_tab_controller_removed_tabs.py tests\test_remote_api_status.py tests\test_automation_settings.py tests\test_instant_wildcard_service.py tests\test_wildcard_status_settings.py tests\test_reference_inset_service.py tests\test_prompt_generation_service.py tests\test_result_image_payload_service.py -q`
- `git diff --check` (line-ending warning only)
- Web Shell runtime: `NAIA_cold_v4.py --web-shell --web-shell-port 7258`
- Startup log confirmed `Web Session middle 모듈 지연 로드: automation_module -> AutomationModule`.
- Initial WebSocket `get_module_state:automation` and `delay` update returned module-state without server log evidence of `지연 middle 모듈 로드 완료: AutomationModule`.
- WebSocket `start` and `stop` returned `is_running=true` then `is_running=false`; delay was restored to `1.0` after validation.
- CDP runtime: Chrome debug port `9349`, Remote Web loaded, Random button changed `#promptEdit`, Generate button stayed enabled. Browser log only had `/favicon.ico` 404.

## 4. 보완

- `AutomationModule` still imports PyQt when the user starts/stops automation from Remote Web, because this round preserves the existing controller and callback contract.
- A future deeper cut can replace the on-demand hidden widget with a pure automation runtime, but this would need separate coverage for timer/count completion, generation delay callbacks, and desktop/web status sync.
- Remaining eager middle candidates include `PromptListModifierModule`, `CharacterModule`, `VibeTransferModule`, and `CharacterReferenceModule`; each has generation hooks or parameter surfaces that need a headless contract before lazy conversion.

## 5. 커밋

- 커밋 메시지: `Lazy load automation module for web session`
