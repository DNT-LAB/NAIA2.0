# Round 16 - Instant Wildcard Headless Store

## 1. 이번 라운드의 계획 확인

- Round 15 이후 hidden WebSession startup에서 `ReferenceInsetAutoInjectModule`도 PyQt import/widget 없이 headless hook으로 동작한다.
- 다음 후보는 `InstantWildcardModule`이다. 이 모듈은 Remote Web 초기 badge 대상도 아니고 `get_parameters()`도 빈 dict지만, `$...` chunk 확장은 `WildcardManager.instant_wildcard_dict/tree`에 의존한다.
- 따라서 단순 lazy 전환은 최초 생성 전 instant wildcard 데이터가 비는 회귀를 만들 수 있어, JSON store를 PyQt 없이 먼저 로드해야 한다.

## 2. 작업 수행

- `core.instant_wildcard_service`를 추가해 `save/instant_wildcard/*.json` 로드, default template 생성, duplicate key suffix, file write, AppContext 적용을 PyQt 없이 처리한다.
- `AppContext` 생성 시 `apply_instant_wildcards_to_context()`를 실행해 `WildcardManager.instant_wildcard_dict/tree`를 WebSession startup에서 먼저 채운다.
- `InstantWildcardModule`은 desktop UI wrapper로 유지하고, JSON 로드/default 생성은 core service에 위임한다.
- `RemoteBridge._read_instant_wildcard()`, `_set_instant_wildcard()`, `_search_chunks()`, `_read_chunk()`는 더 이상 `_find_module("instant_wildcard")`를 호출하지 않고 server-owned headless store를 사용한다.
- `AutoCompleteManager._get_instant_wildcards()`는 먼저 `WildcardManager` 캐시를 읽고, 비어 있을 때만 기존 PyQt module fallback을 사용한다.
- `MIDDLE_MODULE_SPECS`에서 `InstantWildcardModule`을 hidden WebSession lazy 대상으로 표시했다.

## 3. 테스트 및 정적 리뷰 수행

- `python -m py_compile core\instant_wildcard_service.py core\context.py core\middle_section_controller.py core\remote_api_server.py core\autocomplete_manager.py modules\instant_wildcard_module.py`
- `python -m pytest tests\test_instant_wildcard_service.py tests\test_middle_section_controller_static_registry.py tests\test_remote_api_status.py -k "instant_wildcard or middle_module" -q`
- `python -m pytest tests\test_middle_section_controller_static_registry.py tests\test_tab_controller_removed_tabs.py tests\test_remote_api_status.py tests\test_instant_wildcard_service.py tests\test_wildcard_status_settings.py tests\test_reference_inset_service.py tests\test_prompt_generation_service.py tests\test_result_image_payload_service.py -q`
- `git diff --check` (line-ending warning only)
- Web Shell runtime: `NAIA_cold_v4.py --web-shell --web-shell-port 7257`
- Startup log confirmed `[OK] 인스턴트 와일드카드 업데이트: 20개 항목, 5개 그룹` before middle module UI load, and `Web Session middle 모듈 지연 로드: instant_wildcard_module -> InstantWildcardModule`.
- WebSocket runtime: `get_module_state:instant_wildcard` returned `flat_count=20`, `file_count=5`, `current_file=default.json`; `get_module_state:chunk` returned 5 groups.
- CDP runtime: Chrome debug port `9348`, Remote Web loaded, Random button changed `#promptEdit`, Generate button stayed enabled. Browser log only had `/favicon.ico` 404.
- Post-WebSocket/CDP server log did not contain `지연 middle 모듈 로드 완료: InstantWildcardModule`.

## 4. 보완

- `PromptListModifierModule` remains eager because it owns a real PromptProcessor hook and generation-finished restoration subscriptions.
- `AutomationModule` remains eager because initial Remote Web badge/status and startup signal wiring still wake it immediately.

## 5. 커밋

- 커밋 메시지: `Lazy load instant wildcard module for web session`
