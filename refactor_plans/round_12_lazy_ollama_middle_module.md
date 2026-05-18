# Round 12 - Ollama middle module WebSession lazy loading

## 라운드 11 이후 남은 문제

Middle module discovery는 static registry로 고정되었지만, 숨김 WebSession startup에서도 모든 지원 middle module을 즉시 import/create했다. 이 중 `OllamaModule`은 generation pipeline hook이 없고, Remote Web에서는 Ollama 패널을 열거나 `ollama` module state를 요청할 때만 필요하다.

## 이번 라운드 범위

1. Desktop 일반 런타임에서는 `OllamaModule` 즉시 로딩을 유지한다.
2. 숨김 WebSession 런타임에서만 `OllamaModule` import/instance 생성을 지연한다.
3. Remote Web에서 `ollama` module state/action을 요청하면 기존 module API가 lazy instance를 만들고 처리한다.
4. 다른 middle modules는 이번 라운드에서 지연하지 않는다. 생성 hook/Remote Web state 의존성을 모듈별로 더 분리해야 하기 때문이다.

## 변경 계획

- `MIDDLE_MODULE_SPECS`의 `OllamaModule`에 `web_session_lazy` flag를 추가한다.
- `MiddleSectionController.load_modules()`가 hidden WebSession에서 해당 spec을 `_deferred_module_specs`에 보관하고 import를 건너뛴다.
- `get_module_instance()`가 deferred module을 on-demand import/initialize/hook-register 하도록 한다.
- `RemoteBridge._find_module()`이 `MiddleSectionController.get_module_instance()`를 사용해 deferred lookup을 탈 수 있게 한다.
- 테스트로 hidden WebSession import defer, desktop immediate load, RemoteBridge deferred lookup을 검증한다.

## 검증 게이트

- `python -m py_compile core/middle_section_controller.py core/remote_api_server.py`
- `python -m pytest tests/test_middle_section_controller_static_registry.py -q`
- `python -m pytest tests/test_remote_api_status.py -q -k "find_module_uses_controller_lookup or ollama or module_state"`
- `python -m pytest tests/test_middle_section_controller_static_registry.py tests/test_tab_controller_removed_tabs.py tests/test_remote_api_status.py -q`
- `python -m pytest tests/test_result_image_payload_service.py tests/test_prompt_generation_service.py -q`
- `git diff --check`
- WebSession 재시작 후 `/api/status` 확인
- startup log에서 Ollama defer 및 CDP 로드 확인

## Static Review

- `OllamaModule`은 `get_parameters()`나 pipeline hook override가 없으므로 generation loop에서 빠져도 generation params가 바뀌지 않는다.
- `_find_module()`은 controller `get_module_instance()`를 먼저 사용하므로 기존 eager modules와 deferred modules 모두 같은 lookup path를 탄다.
- Deferred instance는 widget 없이 초기화되므로 Remote Web의 `_read_ollama()` / `_set_ollama()`가 이미 갖고 있는 `_remote_*` fallback state를 사용한다.
- Desktop 런타임에서는 `web_session_lazy` flag가 무시되며 기존 UI module load가 유지된다.

## 수행 결과

- 숨김 WebSession에서 `OllamaModule` startup import/instance 생성을 지연했다.
- Remote Web module lookup이 `get_module_instance()`를 통해 deferred module을 on-demand 로드할 수 있게 했다.
- middle controller lazy tests와 RemoteBridge lookup test를 추가했다.

## 검증 결과

- `python -m py_compile core/middle_section_controller.py core/remote_api_server.py` 통과.
- `python -m pytest tests/test_middle_section_controller_static_registry.py -q` 통과: 5 passed.
- `python -m pytest tests/test_remote_api_status.py -q -k "find_module_uses_controller_lookup or ollama or module_state"` 통과: 1 passed, 131 deselected.
- `python -m pytest tests/test_middle_section_controller_static_registry.py tests/test_tab_controller_removed_tabs.py tests/test_remote_api_status.py -q` 통과: 145 passed.
- `python -m pytest tests/test_result_image_payload_service.py tests/test_prompt_generation_service.py -q` 통과: 10 passed.
- `git diff --check` 통과.
- `--web-shell --web-shell-port 7252` 재시작 후 `/api/status` 정상 응답: `api_mode` NAI, `is_generating` false.
- startup log에서 `OllamaModule`은 즉시 로드되지 않고 `Web Session middle 모듈 지연 로드: ollama_module -> OllamaModule`로 기록됨. context injection 대상도 11개에서 10개로 감소.
- WebSocket `get_module_state` 요청으로 `module_id=ollama` 상태 응답 확인: supported model 2개, selected model 기본값, tag DB 미로딩 상태.
- Chrome CDP `9342`에서 `http://127.0.0.1:7252/` 로드 확인: title `NAIA Remote`, readyState `complete`, Generate/생성 관련 UI 텍스트 확인.
