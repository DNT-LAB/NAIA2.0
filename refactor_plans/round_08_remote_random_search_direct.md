# Round 08 - Normal Remote Random 직접 실행

## 라운드 7 이후 남은 문제

Prepared source row가 있는 Remote random은 core service로 직접 처리되지만, 일반 Remote random은 여전히 `ModernMainWindow.trigger_random_prompt()`로 fallback했다. 이 fallback은 버튼 상태, status bar, widget settings, snapshot restore를 함께 수행해 WebSession에 불필요한 PyQt side effect를 남긴다.

## 이번 라운드 범위

1. Plain WebSocket random만 대상으로 한다.
2. Event Stream 활성, ComfyUI random, Event Preset, Remote Preset 경로는 유지한다.
3. `search_results` 또는 memory/temp/fallback snapshot에서 source row를 준비할 수 있으면 core service로 직접 생성한다.
4. UI label/status 업데이트는 하지 않고 `SearchResultModel`만 복원한다.

## 변경 계획

- `_ensure_remote_random_search_results()`를 추가한다.
- `_remote_random_search_results()`와 `_try_generate_remote_random_from_search()`를 추가한다.
- source row가 없는 plain random에서 search 결과를 직접 pop하고 `PromptGenerationService`로 처리한다.
- 비정상 context처럼 `main_window.search_results` 표면이 없으면 기존 fallback을 유지한다.
- search 결과 직접 실행과 memory snapshot 복원 회귀 테스트를 추가한다.

## 검증 게이트

- `python -m py_compile core/remote_api_server.py`
- Remote random 관련 좁은 테스트
- `python -m pytest tests/test_remote_api_status.py -q`
- `python -m pytest tests/test_prompt_generation_service.py tests/test_remote_api_status.py -q`
- WEBUI Hires 관련 좁은 테스트
- `git diff --check`
- WebSession 재시작 후 `/api/status` 확인
- Chrome CDP로 Remote Web 루트 로드 확인

## Static Review

- 직접 실행은 plain WebSocket random에만 적용된다.
- Event Stream 활성 시 desktop wrapper로 fallback한다.
- `search_results`가 없는 fake/비정상 context는 disk fallback을 타지 않고 기존 wrapper로 fallback한다.
- direct path의 실패 응답은 기존 `random_failed` payload를 사용한다.

## 수행 결과

- source row가 없는 plain Remote random도 `search_results`가 준비되어 있으면 `PromptGenerationService`가 직접 pop/process 한다.
- `search_results`가 비어 있을 때 memory snapshot, `data/naia_temp_rows.parquet`, `data/tags/tags_129.parquet` 순서로 UI-free restore를 시도한다.
- 기존 desktop `_restore_from_snapshot()`의 label/status bar mutation은 WebSession direct path에서 호출하지 않는다.
- `main_window.search_results` 표면이 없는 context는 disk fallback을 타지 않고 기존 wrapper로 fallback한다.

## 검증 결과

- `python -m py_compile core/remote_api_server.py` 통과.
- Remote random 관련 좁은 테스트 5개 통과.
- `python -m pytest tests/test_remote_api_status.py -q` 통과: 131 passed.
- `python -m pytest tests/test_prompt_generation_service.py tests/test_remote_api_status.py -q` 통과: 134 passed.
- WEBUI Hires 관련 좁은 테스트 통과: 16 passed.
- `git diff --check` 통과.
- `--web-shell --web-shell-port 7248` 재시작 후 `/api/status` 정상 응답.
- Chrome CDP `9338`에서 `http://127.0.0.1:7248/` 로드 확인: title `NAIA Remote`, readyState `complete`, boot `Ready`, mode `NAI`.
