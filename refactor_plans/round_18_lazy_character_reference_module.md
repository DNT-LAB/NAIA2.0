# Round 18 - Character Reference On-Demand Widget

## 1. 이번 라운드의 계획 확인

- Round 17 이후 hidden WebSession startup에서 `AutomationModule`도 headless state로 초기 로드를 피한다.
- 남은 eager image module 중 `CharacterReferenceModule`은 Remote Web 초기 badge state 요청 때문에 startup-visible했다.
- 생성 파라미터는 loaded module의 `get_parameters()`에서만 수집되므로, 사용자가 Remote Web Character Reference 패널을 실제로 열거나 이미지를 적용하는 시점에 기존 PyQt wrapper를 on-demand로 준비하는 방식이 안전하다.

## 2. 작업 수행

- `MIDDLE_MODULE_SPECS`에서 `CharacterReferenceModule`을 hidden WebSession lazy 대상으로 표시했다.
- WebSocket 초기 연결의 badge refresh에서 `character_reference` 요청을 제거해, 접속만으로 deferred module이 깨지 않게 했다.
- `RemoteBridge._ensure_module_widget()`를 추가해 deferred module을 실제로 읽거나 조작할 때 숨김 widget을 준비하고 `on_initialize()`를 다시 호출한다.
- `_read_character_reference()`와 `_set_character_reference()`는 기존 PyQt module 동작을 보존하되, explicit panel open/action 시에만 module widget을 만든다.
- Character Reference/Vibe 상호 배타 비활성화는 loaded-only module만 대상으로 바꿔, 반대쪽 module이 deferred 상태일 때 불필요하게 깨우지 않는다.

## 3. 테스트 및 정적 리뷰 수행

- `python -m py_compile core\middle_section_controller.py core\remote_api_server.py`
- `python -m pytest tests\test_middle_section_controller_static_registry.py tests\test_remote_api_status.py -k "character_reference or middle_module" -q`
- `git diff --check` (line-ending warning only)
- Web Shell runtime: `NAIA_cold_v4.py --web-shell --web-shell-port 7259`
- Startup log confirmed `Web Session middle 모듈 지연 로드: character_reference_module -> CharacterReferenceModule` and total middle modules dropped to 4 loaded modules.
- Initial WebSocket messages did not include `character_reference`; explicit `get_module_state:character_reference` returned an empty module-state payload.
- CDP runtime: Chrome debug port `9350`, Remote Web loaded, Random button changed `#promptEdit`, Generate button stayed enabled, and `openModule('character_reference')` rendered the Character Reference panel. Browser log only had `/favicon.ico` 404.

## 4. 보완

- This round does not replace the Character Reference frame implementation with a pure core model. Image upload/apply still uses the existing PyQt wrapper on demand.
- `VibeTransferModule` remains eager and is still the next image-module candidate, but its late-binding generation path and mode settings restoration need separate handling.

## 5. 커밋

- 커밋 메시지: `Lazy load character reference module for web session`
