# Round 13 - Lazy Wildcard Status Module

## 1. 이번 라운드의 계획 확인

- 이전 라운드까지 Remote Web의 핵심 random/generation/result-image path와 static middle module registry, `OllamaModule` lazy loading은 완료되어 있다.
- 남은 병목은 hidden WebSession startup에서 PyQt middle module을 계속 import/instance/widget 생성하는 표면이다.
- 이번 라운드 후보는 `WildcardStatusModule`이다. 단, 이 모듈은 UI 표시뿐 아니라 `prompt_squeeze_enabled`와 `scoped_wildcard` 설정을 `AppContext`에 적용하므로 단순 지연 로드는 금지한다.

## 2. 작업 수행

- `core.wildcard_status_settings`를 추가해 wildcard status 설정 로드/저장/적용을 PyQt 없는 core helper로 분리했다.
- `AppContext` 생성 시 `apply_wildcard_status_settings()`를 호출해 hidden WebSession에서도 생성 경로가 기존 설정을 보존하게 했다.
- `MIDDLE_MODULE_SPECS`에서 `WildcardStatusModule`을 `web_session_lazy=True`로 표시했다.
- `RemoteBridge._read_wildcard()`를 AppContext/WildcardManager 기반으로 바꿔 wildcard module-state 조회가 PyQt module import를 유발하지 않게 했다.
- `RemoteBridge._set_wildcard()`에서 `prompt_squeeze`, `reload`, `reset_sequential`, wildcard file manager 액션을 headless server path로 처리하게 했다.
- `WildcardStatusModule.reset_sequential_wildcards()`는 widget 없는 lazy instance에서도 실패 로그를 내지 않도록 textbox 접근을 guard했다.

## 3. 테스트 및 정적 리뷰 수행

- `python -m py_compile core\wildcard_status_settings.py core\context.py core\middle_section_controller.py core\remote_api_server.py modules\wildcard_status_module.py`
- `python -m pytest tests\test_wildcard_status_settings.py tests\test_middle_section_controller_static_registry.py -q`
- `python -m pytest tests\test_remote_api_status.py -k "wildcard_prompt_squeeze_set_is_headless_and_persisted or wildcard_reset_sequential_is_headless or find_module_uses_controller_lookup" -q`
- `python -m pytest tests\test_middle_section_controller_static_registry.py tests\test_tab_controller_removed_tabs.py tests\test_remote_api_status.py -q`
- `python -m pytest tests\test_result_image_payload_service.py tests\test_prompt_generation_service.py tests\test_wildcard_status_settings.py -q`
- `git diff --check`
- Web Shell runtime: `NAIA_cold_v4.py --web-shell --web-shell-port 7254`
- WebSocket runtime: `get_module_state:wildcard`, `set_module_param:wildcard.prompt_squeeze`, `set_module_param:wildcard.reset_sequential`
- CDP runtime: Chrome debug port `9344`, Remote Web load, Random button prompt update, Generate button enabled, wildcard launcher and params tab present.

## 4. 보완

- Static review에서 hidden lazy mode의 `prompt_squeeze` 토글이 checkbox 없는 module instance에서는 no-op이 될 수 있다는 문제가 발견되었다.
- 보완 후 `prompt_squeeze`는 `app_context.prompt_squeeze_enabled`와 `save/wildcard_status_settings.json`을 직접 갱신하고, 이미 로드된 desktop widget이 있을 때만 checkbox를 mirror한다.
- `reset_sequential`은 `current_prompt_context.sequential_counters`와 `wildcard_state`를 직접 clear하고 상태를 broadcast한다.

## 5. 커밋

- 커밋 메시지: `Lazy load wildcard status for web session`
