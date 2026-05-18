# Round 22 - Prompt Engineering headless widget skip

## 1. 이번 라운드의 계획 확인

- 대상: hidden WebSession startup에서 `PromptEngineeringModule`의 PyQt widget tree 생성을 생략한다.
- 보존해야 할 동작:
  - Remote Web `prompt_engineering` module-state read/write
  - random prompt trigger 시 `*randomized` preset side effect
  - PromptProcessor `post_processing` hook
  - PromptProcessor `after_wildcard` hooks: Closed Eyes Sync, e621 Auto-Boost, Danbooru Auto-Weight, Outfit Context Resolver
- 제외 범위:
  - `PromptEngineeringModule` full lazy 전환은 이번 라운드에서 하지 않는다.
  - full lazy는 별도 PyQt-free prompt-engineering service, randomized preset subscriber, hook owner 분리가 선행되어야 한다.

## 2. 작업 수행

- `MIDDLE_MODULE_SPECS`에서 `PromptEngineeringModule`에 `web_session_headless_widget`을 지정했다.
- `MiddleSectionController.build_ui()`는 headless widget module에 대해 `register_headless_hooks()`와 pipeline hook 등록만 수행하고 `create_widget()`을 생략한다.
- `PromptEngineeringModule`에 `_headless_settings`를 추가해 text edit/checkbox widget 없이도 settings collect/apply/get_parameters가 동작하도록 했다.
- 기존 `after_wildcard` hook registration을 `register_headless_hooks()`로 분리하고 desktop `create_widget()`과 hidden WebSession headless path가 같은 hook registration을 공유하게 했다.
- Remote Web `_read_prompt_engineering()`과 `_set_prompt_engineering()`은 widget 직접 접근 대신 `collect_current_settings()`/`apply_settings()`를 우선 사용한다.
- headless path에서도 preset list discovery, `*randomized` random preset application, preprocessing toggle update가 유지되도록 guarded widget access를 추가했다.

## 3. 테스트 및 정적 리뷰 수행

- `python -m py_compile core\middle_section_controller.py core\remote_api_server.py modules\prompt_engineering_module.py`
- `python -m pytest tests\test_remote_api_status.py tests\test_prompt_engineering_preset_schema.py tests\test_middle_section_controller_static_registry.py -k "prompt_engineering or middle_module" -q`
- `python -m pytest tests\test_middle_section_controller_static_registry.py tests\test_tab_controller_removed_tabs.py tests\test_remote_api_status.py tests\test_automation_settings.py tests\test_character_settings.py tests\test_conditional_prompt_restore.py tests\test_instant_wildcard_service.py tests\test_wildcard_status_settings.py tests\test_reference_inset_service.py tests\test_prompt_generation_service.py tests\test_result_image_payload_service.py tests\test_prompt_engineering_preset_schema.py -q`
- `git diff --check -- . ':!logs'`
- WebShell runtime: `python NAIA_cold_v4.py --web-shell --web-shell-port 7264`
- CDP runtime:
  - `http://127.0.0.1:7264/` 로드
  - Random 버튼 경로로 `promptEdit` 변경 확인
  - Generate 버튼 활성 상태 확인
  - `openModule('prompt_engineering')`로 Remote Web Prompt Engineering panel 렌더링 확인
  - Runtime exception, console error, non-favicon network error 없음

## 4. 보완

- headless `collect_current_settings()`가 빈 dict를 반환하던 문제를 `_headless_settings` 반환으로 바꿔 Remote Web state와 generation parameter read가 widget 생성 여부에 의존하지 않게 했다.
- `load_preset_list()`는 combo widget 유무와 무관하게 `preset_list`와 randomized pool을 갱신하도록 조정했다.
- `load_preset_random()`은 widget이 없을 때도 headless pre/post prompt를 갱신하도록 조정했다.

## 5. 커밋

- 예정 메시지: `Skip prompt engineering widget in web session`

## 남은 작업

- `PromptEngineeringModule`은 아직 hidden WebSession startup에서 import/instance 생성이 필요하다.
- 완전한 lazy 전환을 위해서는 `core.prompt_engineering_settings/service`로 preset state, randomized preset application, post/after-wildcard hooks를 옮기고, module instance 없이도 `PromptProcessor`가 동일하게 동작하는지 검증해야 한다.
