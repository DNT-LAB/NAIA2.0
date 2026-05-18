# Round 05 - Prompt Generation Core 분리

## 라운드 4 이후 남은 문제

Remote Web의 랜덤 프롬프트/프롬프트 재개봉 경로는 여전히 `ModernMainWindow`와 `PromptGenerationController(QObject)`를 통해 핵심 프롬프트 조립을 실행한다. 특히 `generate_instant_source_silent()`를 쓰는 서버 API도 `main_window.prompt_gen_controller`가 존재해야 하는 구조였다.

## 이번 라운드 범위

1. `_do_random()`의 `ModernMainWindow.trigger_random_prompt()` 호출은 유지한다.
2. PromptContext 생성과 silent prompt generation의 실제 core 로직을 PyQt 없는 service로 분리한다.
3. RemoteBridge의 silent prompt 사용 지점은 `PromptGenerationController` wrapper가 아니라 core service를 사용한다.
4. 기존 signal wire format과 `app_context.publish("prompt_generated", context)` 동작은 유지한다.

## 변경 계획

- `core/prompt_generation_service.py`를 추가한다.
- `PromptGenerationController`는 PyQt signal wrapper로 축소하고 `PromptGenerationService`에 위임한다.
- `RemoteBridge._get_prompt_generation_service()`를 추가해 service를 lazy 준비한다.
- Danbooru prompt preview, result queue reopen, WEBUI Hires preset swap의 prompt generation 의존을 `prompt_generation_service`로 옮긴다.
- service 객체 생성이 startup에서 `PromptProcessor`/wildcard manager를 즉시 요구하지 않도록 processor를 lazy 생성한다.

## 검증 게이트

- `python -m py_compile core/prompt_generation_service.py core/prompt_generation_controller.py core/remote_api_server.py core/generation_controller.py`
- `python -m pytest tests/test_prompt_generation_service.py`
- `python -m pytest tests/test_remote_api_status.py`
- WEBUI Hires 관련 좁은 테스트
- `git diff --check`
- WebSession 재시작 후 `/api/status` 확인
- Chrome CDP로 Remote Web 루트 로드 확인

## Static Review

- `_do_random()` 직접 호출 구조는 유지해 snapshot restore, Event Stream, UI button/status side effect를 건드리지 않았다.
- service는 PyQt6를 import하지 않는다.
- `PromptGenerationController`의 signal 순서와 `prompt_generated` publish 위치는 기존 wrapper에서 유지한다.
- RemoteBridge prompt preview fallback은 유지한다.

## 수행 결과

- `PromptGenerationService`가 PromptContext 생성, instant source 정규화, silent prompt 생성, next-source 준비를 담당한다.
- `PromptGenerationController(QObject)`는 PyQt signal wrapper로 축소됐다.
- service 객체 생성만으로는 `PromptProcessor`를 만들지 않도록 lazy 생성으로 보완했다. WebSession startup에서 service 준비가 곧바로 `main_window.wildcard_manager`를 요구하지 않는다.
- `RemoteBridge` Danbooru prompt preview와 result queue reopen prompt는 `main_window.prompt_gen_controller` 직접 접근을 제거했다.
- WEBUI Hires preset swap도 `prompt_generation_service`를 사용한다.

## 검증 결과

- `python -m py_compile core/prompt_generation_service.py core/prompt_generation_controller.py core/remote_api_server.py core/generation_controller.py` 통과.
- `python -m pytest tests/test_prompt_generation_service.py tests/test_remote_api_status.py -q` 통과: 129 passed.
- `python -m pytest tests/test_api_service_webui_hires.py tests/test_generation_params_hiresfix_persistence.py -q` 통과: 16 passed.
- `git diff --check` 통과.
- `--web-shell --web-shell-port 7245` 재시작 후 `/api/status` 정상 응답.
- Chrome CDP `9335`에서 `http://127.0.0.1:7245/` 로드 확인: title `NAIA Remote`, readyState `complete`, boot `Ready`, mode `NAI`.
