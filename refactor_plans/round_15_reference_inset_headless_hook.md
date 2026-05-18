# Round 15 - Reference Inset Headless Hook

## 1. 이번 라운드의 계획 확인

- Round 14 이후 hidden WebSession startup에서 `OllamaModule`, `WildcardStatusModule`, `E621EventModuleV2`가 지연 로드된다.
- 남은 eager 후보 중 `AutomationModule`은 Remote Web 초기 badge와 signal sync가 `_find_module("automation")`을 통해 즉시 깨우고, `get_parameters()` 기본값도 모듈 인스턴스에만 있어 이번 라운드 lazy 후보에서 제외한다.
- `ReferenceInsetAutoInjectModule`은 Remote Web 초기 state 요청 대상이 아니며, 핵심 동작은 `final_hookpoint`에서 `reference inset` 태그를 삽입하는 pure prompt mutation이다.

## 2. 작업 수행

- `core.reference_inset_service`를 추가해 `reference inset` 삽입 판단, prompt 문자열 삽입, PromptContext hook을 PyQt 없이 실행할 수 있게 했다.
- `ReferenceInsetAutoInjectModule`은 desktop UI wrapper로 유지하고, 기존 hook 동작은 core service에 위임한다.
- `MIDDLE_MODULE_SPECS`에서 `ReferenceInsetAutoInjectModule`을 hidden WebSession lazy 대상으로 표시했다.
- hidden WebSession에서 해당 모듈을 defer할 때는 PyQt 모듈을 import하지 않고 `ReferenceInsetAutoInjectHook` headless hook만 `AppContext.pipeline_hooks`에 등록한다.
- deferred module이 나중에 on-demand load되더라도 같은 hook이 중복 등록되지 않도록 headless hook 등록 class를 추적한다.

## 3. 테스트 및 정적 리뷰 수행

- `python -m py_compile core\middle_section_controller.py core\reference_inset_service.py core\api_service.py modules\reference_inset_module.py`
- `python -m pytest tests\test_middle_section_controller_static_registry.py tests\test_reference_inset_service.py -q`
- `python -m pytest tests\test_middle_section_controller_static_registry.py tests\test_tab_controller_removed_tabs.py tests\test_remote_api_status.py tests\test_reference_inset_service.py tests\test_result_image_payload_service.py tests\test_prompt_generation_service.py tests\test_wildcard_status_settings.py -q`
- `git diff --check` (line-ending warning only)
- Web Shell runtime: `NAIA_cold_v4.py --web-shell --web-shell-port 7256`
- Startup log confirmed `Web Session headless middle hook 등록: ReferenceInsetAutoInjectModule` and `Web Session middle 모듈 지연 로드: reference_inset_module -> ReferenceInsetAutoInjectModule`.
- CDP runtime: Chrome debug port `9347`, Remote Web loaded, Random button changed `#promptEdit`, Generate button stayed enabled. Browser log only had `/favicon.ico` 404.
- Post-CDP server log did not contain `지연 middle 모듈 로드 완료: ReferenceInsetAutoInjectModule`.

## 4. 보완

- `core.api_service`의 생성 시점 안전망도 같은 core service를 사용하도록 정리했다.
- `AutomationModule`은 이번 라운드에서 유지한다. lazy 전환 전에는 headless automation state/default parameter/service 분리가 먼저 필요하다.

## 5. 커밋

- 커밋 메시지: `Lazy load reference inset hook for web session`
