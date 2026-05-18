# Round 06 - Remote Random Auto-generate 상태 축소

## 라운드 5 이후 남은 문제

`RemoteBridge._do_random()`은 아직 `ModernMainWindow.trigger_random_prompt()`를 호출한다. 다만 그 전에 WebSession pending 상태를 만들면서 `main_window.generation_checkboxes["자동 생성"]`을 직접 읽어, Remote Web 요청의 auto-generate 여부가 서버 상태가 아니라 PyQt 위젯 상태에 묶여 있었다.

## 이번 라운드 범위

1. `trigger_random_prompt()` 직접 제거는 하지 않는다.
2. Remote random pending의 `auto_generate` 판정만 서버/요청 상태 우선으로 바꾼다.
3. 기존 WebSocket `prompt_generated`와 request id 흐름은 유지한다.

## 변경 계획

- `RemoteBridge._random_request_auto_generate_enabled()`를 추가한다.
- 판정 순서는 request overrides `auto_generate` → `_remote_option_state["auto_generate"]` → `_remote_auto_generate_enabled` → desktop snapshot fallback이다.
- `_do_random()`의 직접 checkbox read를 제거한다.
- request override와 server-owned option state를 검증하는 회귀 테스트를 추가한다.

## 검증 게이트

- `python -m py_compile core/remote_api_server.py`
- Random 관련 좁은 `tests/test_remote_api_status.py` 테스트
- 전체 `tests/test_remote_api_status.py`
- `git diff --check`
- WebSession 재시작 후 `/api/status` 확인
- Chrome CDP로 Remote Web 루트 로드 확인

## Static Review

- `_pending_overrides`의 wire shape은 유지한다.
- `force_naia_skip_generate`와 `respect_naia_autogen` 처리 순서는 유지한다.
- request override가 desktop checkbox보다 우선한다.
- server-owned option state가 있으면 desktop checkbox가 없어도 pending auto-generate 판정이 가능하다.

## 수행 결과

- `_do_random()`에서 `main_window.generation_checkboxes["자동 생성"]` 직접 read를 제거했다.
- request override `auto_generate`가 있으면 desktop widget보다 우선한다.
- server-owned `_remote_option_state["auto_generate"]`가 있으면 desktop checkbox 없이 pending auto-generate를 결정한다.
- 기존 `trigger_random_prompt()` 호출과 pending override shape은 유지했다.

## 검증 결과

- `python -m py_compile core/remote_api_server.py` 통과.
- Random 관련 좁은 `tests/test_remote_api_status.py` 테스트 4개 통과.
- `python -m pytest tests/test_remote_api_status.py -q` 통과: 128 passed.
- `python -m pytest tests/test_prompt_generation_service.py tests/test_remote_api_status.py -q` 통과: 131 passed.
- WEBUI Hires 관련 좁은 테스트 통과: 16 passed.
- `git diff --check` 통과.
- `--web-shell --web-shell-port 7246` 재시작 후 `/api/status` 정상 응답.
- Chrome CDP `9336`에서 `http://127.0.0.1:7246/` 로드 확인: title `NAIA Remote`, readyState `complete`, boot `Ready`, mode `NAI`.
