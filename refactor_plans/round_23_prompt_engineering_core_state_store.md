# Round 23 - Prompt Engineering core state store

## 1. 이번 라운드의 계획 확인

- 대상: `PromptEngineeringModule` full lazy 전환의 선행 조건인 PyQt-free state reader/writer를 만든다.
- 이유: Round 22 이후에도 hidden WebSession startup은 `PromptEngineeringModule` import/instance를 유지한다. 바로 lazy flag를 켜면 Remote Web initial state와 prompt hooks가 깨질 수 있으므로, 먼저 서버가 module 없이 state payload를 만들 수 있어야 한다.
- 제외 범위:
  - 이번 라운드에서는 `PromptEngineeringModule`을 `web_session_lazy`로 바꾸지 않는다.
  - post-processing hook과 after-wildcard hooks의 core 이관은 다음 라운드 후보로 남긴다.

## 2. 작업 수행

- `core.prompt_engineering_settings`를 추가했다.
- 새 core store는 PyQt 없이 다음 상태를 관리한다:
  - mode-aware module settings
  - preset list and preset module settings
  - last-used preset
  - randomized preset pool
  - e621 and Danbooru settings files
- `RemoteBridge._read_prompt_engineering()`은 이제 loaded module을 우선 사용하고, loaded module이 없으면 core store로 동일한 `module_state` payload를 만든다.
- `RemoteBridge._set_prompt_engineering()`은 loaded module이 없을 때도 prefix/postfix/auto-hide/preprocessing/randomized/preset/e621/Danbooru state를 core store로 처리한다.
- Artist Thumbnail random Prompt Engineering override는 loaded module이 없으면 core store settings를 사용한다.

## 3. 테스트 및 정적 리뷰 수행

- `python -m py_compile core\prompt_engineering_settings.py core\remote_api_server.py`
- `python -m pytest tests\test_remote_api_status.py tests\test_prompt_engineering_preset_schema.py -k "prompt_engineering" -q`
- `python -m pytest tests\test_middle_section_controller_static_registry.py tests\test_tab_controller_removed_tabs.py tests\test_remote_api_status.py tests\test_automation_settings.py tests\test_character_settings.py tests\test_conditional_prompt_restore.py tests\test_instant_wildcard_service.py tests\test_wildcard_status_settings.py tests\test_reference_inset_service.py tests\test_prompt_generation_service.py tests\test_result_image_payload_service.py tests\test_prompt_engineering_preset_schema.py -q`
- `git diff --check -- . ':!logs'`
- WebShell runtime: `python NAIA_cold_v4.py --web-shell --web-shell-port 7265`
- CDP runtime:
  - `http://127.0.0.1:7265/` 로드
  - Random 버튼 경로로 `promptEdit` 변경 확인
  - Generate 버튼 활성 상태 확인
  - Prompt Engineering module panel 렌더링 확인
  - Runtime exception, console error, non-favicon network error 없음

## 4. 보완

- `_read_prompt_engineering()`의 module lookup을 wake-up 가능한 `_find_module()`에서 loaded-only 조회로 바꿔, 향후 lazy flag 전환 시 initial Remote Web handshake가 PyQt module을 깨우지 않도록 했다.
- 현재는 module이 still eager라 runtime behavior는 동일하지만, no-loaded-module 테스트로 fallback 계약을 고정했다.

## 5. 커밋

- 예정 메시지: `Add prompt engineering core state store`

## 남은 작업

- `PromptEngineeringModule`의 `post_processing` hook과 4개 `after_wildcard` hooks를 PyQt-free runtime/service로 분리해야 full lazy 전환이 가능하다.
- `*randomized` random-prompt side effect도 module subscriber 대신 core runtime subscriber로 옮겨야 startup import를 제거할 수 있다.
