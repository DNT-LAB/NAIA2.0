# Round 21 - Conditional Prompt Headless Widget Skip

## 1. 이번 라운드의 계획 확인

- Round 20 이후 hidden WebSession startup에서 `PromptEngineeringModule`과 `PromptListModifierModule`이 남은 eager middle module이다.
- `PromptEngineeringModule`은 initial Remote Web state, random preset side effects, post/after-wildcard hooks가 넓게 묶여 있어 별도 PyQt-free service가 선행되어야 한다.
- `PromptListModifierModule`은 generation hook 자체는 유지해야 하지만, hidden WebSession startup에서 PyQt widget tree를 만들 필요는 없다.

## 2. 작업 수행

- `PromptListModifierModule` registry에 `web_session_headless_widget` 플래그를 추가했다.
- hidden WebSession의 `MiddleSectionController.build_ui()`에서 해당 플래그가 있는 module은 instance/context/hook은 유지하되 `create_widget()`과 `CollapsibleBox` 생성을 생략한다.
- `PromptListModifierModule`에 `_headless_settings`를 추가해 UI widget 없이도 mode settings, enabled 상태, legacy/v2 DSL, engine options, active preset을 보존한다.
- `execute_pipeline_hook()`과 `get_parameters()`는 checkbox/textedit 대신 headless settings fallback을 사용한다.
- `RemoteBridge` conditional state/setter는 widget-backed field가 없을 때 `collect_current_settings()`/`apply_settings()` 기반으로 읽고 쓴다.

## 3. 테스트 및 정적 리뷰 수행

- `python -m py_compile core\middle_section_controller.py modules\conditional_prompt_module.py core\remote_api_server.py`
- `python -m pytest tests\test_conditional_prompt_restore.py tests\test_remote_api_status.py tests\test_middle_section_controller_static_registry.py -k "conditional or middle_module" -q`
- `python -m pytest tests\test_middle_section_controller_static_registry.py tests\test_tab_controller_removed_tabs.py tests\test_remote_api_status.py tests\test_automation_settings.py tests\test_character_settings.py tests\test_conditional_prompt_restore.py tests\test_instant_wildcard_service.py tests\test_wildcard_status_settings.py tests\test_reference_inset_service.py tests\test_prompt_generation_service.py tests\test_result_image_payload_service.py -q`
- `git diff --check` (line-ending warning only)
- Web Shell runtime: `NAIA_cold_v4.py --web-shell --web-shell-port 7263`
- Startup log confirmed `Web Session middle 모듈 UI 생성 생략: PromptListModifierModule` and no Conditional `content setup complete` log.
- CDP runtime: Chrome debug port `9354`, Remote Web loaded, Random changed `#promptEdit`, Generate stayed enabled, and Conditional panel rendered from headless server state. No non-favicon network errors or JS exceptions were reported.

## 4. 보완

- This round intentionally does not mark `PromptListModifierModule` as fully lazy. The hook must remain registered before generation so saved conditional rules still apply even when the panel is never opened.
- Character rule actions remain lazy-on-demand: non-character rules do not wake `CharacterModule`, while char/uc rules can still load the legacy character surface when explicitly needed.
- `PromptEngineeringModule` remains the next major blocker and needs a dedicated `core.prompt_engineering_service`/headless hook split before its lazy flag is safe.

## 5. 커밋

- 커밋 메시지: `Skip conditional prompt widget in web session`
