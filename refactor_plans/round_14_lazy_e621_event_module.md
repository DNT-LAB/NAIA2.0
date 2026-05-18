# Round 14 - Lazy E621 Event Module

## 1. 이번 라운드의 계획 확인

- Round 13 이후 hidden WebSession startup에서 `OllamaModule`과 `WildcardStatusModule`은 지연 로드된다.
- 다음 후보는 `E621EventModuleV2`이다. 이 모듈은 Remote Web 초기 handshake 대상이 아니지만, 생성 요청용 `generation_requested` signal을 갖고 있어 단순 lazy 처리만 하면 Web Remote의 E621 Generate가 미연결 signal에 의존할 수 있다.

## 2. 작업 수행

- `MIDDLE_MODULE_SPECS`에서 `E621EventModuleV2`를 `web_session_lazy=True`로 표시했다.
- `RemoteBridge._set_e621_event("generate", ...)`를 server-owned Remote Web path로 보완했다.
- Remote Web E621 Generate는 `main_window.on_instant_generation_requested(tags_data)`를 직접 호출하고, direct callback이 없을 때만 기존 module signal을 fallback으로 사용한다.
- 이로써 hidden WebSession lazy load 후에도 `MainController.connect_e621_event_signals()`를 다시 실행하지 않아도 Web Remote Generate path가 유지된다.

## 3. 테스트 및 정적 리뷰 수행

- `python -m py_compile core\middle_section_controller.py core\remote_api_server.py`
- `python -m pytest tests\test_middle_section_controller_static_registry.py -q`
- `python -m pytest tests\test_remote_api_status.py -k "e621_generate_uses_main_window_direct_callback_when_signal_unwired or find_module_uses_controller_lookup" -q`
- `python -m pytest tests\test_middle_section_controller_static_registry.py tests\test_tab_controller_removed_tabs.py tests\test_remote_api_status.py -q`
- `python -m pytest tests\test_result_image_payload_service.py tests\test_prompt_generation_service.py tests\test_wildcard_status_settings.py -q`
- `git diff --check`
- Web Shell runtime: `NAIA_cold_v4.py --web-shell --web-shell-port 7255`
- WebSocket runtime: `get_module_state:e621_event` returned `data_loaded=true`, 15 categories.
- CDP runtime: Chrome debug port `9345`, Remote Web load, Random button prompt update, Generate button enabled, E621 launcher popup rendered.

## 4. 보완

- Static review에서 E621 lazy load가 기존 signal wiring을 우회할 수 있음을 확인했다.
- Remote Web generate path를 direct callback으로 변경해 signal 미연결 상태에서도 E621 tags payload가 기존 즉시 생성 진입점으로 전달되도록 했다.

## 5. 커밋

- 커밋 메시지: `Lazy load E621 event module for web session`
