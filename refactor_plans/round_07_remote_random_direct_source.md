# Round 07 - Prepared-source Remote Random 직접 실행

## 라운드 6 이후 남은 문제

Remote random 요청의 auto-generate 판정은 서버 상태로 이동했지만, 실제 prompt generation 실행은 여전히 `ModernMainWindow.trigger_random_prompt()`에 위임된다. 이 wrapper는 버튼, status bar, desktop widget settings, snapshot restore, Event Stream side effect를 모두 포함한다.

## 이번 라운드 범위

1. 모든 random 요청을 한 번에 직접 실행으로 바꾸지 않는다.
2. 이미 `source_row`가 준비된 plain WebSocket random 요청만 core service로 직접 실행한다.
3. ComfyUI random, Event Preset, Remote Preset, Event Stream 활성 경로는 기존 wrapper로 유지한다.
4. normal random의 desktop `search_results` pop/snapshot restore 경로는 아직 유지한다.

## 변경 계획

- `_remote_random_settings()`를 추가해 request overrides와 server-owned option/param state에서 prompt settings를 구성한다.
- `_try_generate_remote_random_direct()`를 추가한다.
- direct path는 `PromptGenerationService.set_current_context()`와 `process_current_context()`를 사용한다.
- `random_prompt_triggered`와 `prompt_generated` publish 계약은 유지한다.
- source row가 없는 요청은 기존 `trigger_random_prompt()` fallback으로 유지한다.

## 검증 게이트

- `python -m py_compile core/remote_api_server.py`
- source row direct random 회귀 테스트
- 전체 `tests/test_remote_api_status.py`
- `tests/test_prompt_generation_service.py tests/test_remote_api_status.py`
- `git diff --check`
- WebSession 재시작 후 `/api/status` 확인
- Chrome CDP로 Remote Web 루트 로드 확인

## Static Review

- 직접 실행은 plain WebSocket random + prepared source row에만 한정했다.
- Event Stream 활성 상태는 desktop wrapper로 fallback한다.
- 직접 실행 실패는 기존 `random_failed` payload로 반환한다.
- pending override shape은 유지한다.
