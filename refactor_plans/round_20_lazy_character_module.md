# Round 20 - Character Headless Settings and Lazy Module

## 1. 이번 라운드의 계획 확인

- Round 19 이후 hidden WebSession startup에서 eager middle module은 `CharacterModule`, `PromptListModifierModule`, `PromptEngineeringModule`만 남았다.
- `CharacterModule`은 saved active slot이 generation params에 영향을 줄 수 있어 단순 lazy 처리만 하면 WebSession 생성 결과가 바뀔 수 있다.
- 이번 라운드는 Character 저장 설정을 PyQt 없이 읽고, Remote Web 초기 상태와 NAI generation late-binding에서 기존 character params를 유지하는 것을 목표로 한다.

## 2. 작업 수행

- `core.character_settings`를 추가해 `save/CharacterModule_<MODE>.json`의 mode-aware 설정을 normalize/load하고, active/cold count와 headless generation params를 생성한다.
- `CharacterModule`을 hidden WebSession lazy 대상으로 표시했다.
- `RemoteBridge._read_character()`는 이미 로드된 module만 읽고, 초기 WebSocket state는 headless settings payload로 응답한다.
- `RemoteBridge._set_character()`는 실제 Character 액션이 들어올 때만 deferred module을 로드하고 숨김 widget을 준비한다.
- `GenerationController`와 `APIService`의 Character late-binding은 loaded-only 조회를 사용하고, module이 열리지 않은 WebSession에서는 headless settings params를 fallback으로 적용한다.
- 상태 미리보기 계산은 별도 `PromptContext`로 수행해 초기 state 조회가 기존 sequential wildcard context를 전진시키지 않도록 했다.
- `PromptListModifierModule`의 cycle-start character snapshot은 loaded-only 조회로 바꿔, char/uc 규칙이 아닌 일반 조건부 프롬프트 규칙이 CharacterModule을 깨우지 않게 했다.

## 3. 테스트 및 정적 리뷰 수행

- `python -m py_compile core\character_settings.py core\middle_section_controller.py core\remote_api_server.py core\generation_controller.py core\api_service.py modules\character_module.py modules\conditional_prompt_module.py`
- `python -m pytest tests\test_character_settings.py tests\test_middle_section_controller_static_registry.py tests\test_remote_api_status.py -k "character or middle_module" -q`
- `python -m pytest tests\test_middle_section_controller_static_registry.py tests\test_tab_controller_removed_tabs.py tests\test_remote_api_status.py tests\test_automation_settings.py tests\test_character_settings.py tests\test_instant_wildcard_service.py tests\test_wildcard_status_settings.py tests\test_reference_inset_service.py tests\test_prompt_generation_service.py tests\test_result_image_payload_service.py -q`
- `git diff --check` (line-ending warning only)
- Web Shell runtime: `NAIA_cold_v4.py --web-shell --web-shell-port 7261`
- Startup log confirmed `Web Session middle 모듈 지연 로드: character_module -> CharacterModule` and total middle modules stayed at 2 loaded modules.
- WebSocket initial state reached `init_complete` and returned `module_state:character` without loading `CharacterModule`.
- CDP runtime: Chrome debug port `9352`, Remote Web loaded, Random button changed `#promptEdit`, Generate button stayed enabled, Character panel rendered, and `preview_refresh` returned processed Character preview through the server path. Actual NovelAI generation was not triggered in this round.
- After the conditional snapshot fix, a second Web Shell/CDP pass used port `7262` and Chrome debug port `9353`; startup still loaded only 2 middle modules, Random changed `#promptEdit`, Generate stayed enabled, and no non-favicon network errors or JS exceptions were reported.

## 4. 보완

- Initial state preview expansion no longer mutates the active prompt context, preventing state refresh from consuming sequential wildcard counters.
- Conditional prompt cycle snapshots now use loaded-only Character lookup; actual char/uc conditions and actions still load the module only when those rules need the legacy character surface.
- Explicit Remote Web Character actions still use the existing PyQt module on demand, preserving the current editing and preview behavior.
- `PromptListModifierModule` and `PromptEngineeringModule` remain eager because they own active prompt hooks and initial Remote Web prompt-engineering state.

## 5. 커밋

- 커밋 메시지: `Lazy load character module for web session`
