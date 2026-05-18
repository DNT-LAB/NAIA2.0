# Round 19 - Vibe Transfer Loaded-Only Late Binding

## 1. 이번 라운드의 계획 확인

- Round 18 이후 hidden WebSession startup에서 `CharacterReferenceModule`은 지연 로드된다.
- `VibeTransferModule`은 Remote Web 초기 badge 요청과 NAI generation late-binding의 `_find_module("vibe_transfer")`/`get_module_instance("VibeTransferModule")` 호출 때문에 단순 lazy 전환만으로는 충분하지 않다.
- 사용자가 Remote Web Vibe 패널을 열거나 Vibe 데이터를 조작한 뒤에는 기존 module state를 보존해야 하지만, 열지 않은 WebSession startup/generation에서 Vibe module을 깨울 필요는 없다.

## 2. 작업 수행

- `MIDDLE_MODULE_SPECS`에서 `VibeTransferModule`을 hidden WebSession lazy 대상으로 표시했다.
- `MiddleSectionController.get_loaded_module_instance()`를 추가해 deferred module을 깨우지 않고 이미 로드된 module만 조회할 수 있게 했다.
- `RemoteBridge._find_loaded_module_instance()`는 controller의 loaded-only helper를 우선 사용한다.
- WebSocket 초기 연결의 badge refresh에서 `vibe_transfer` 요청을 제거했다.
- `RemoteBridge._read_vibe_transfer()`와 `_set_vibe_transfer()`는 explicit panel open/action 시에만 deferred module을 로드하고 숨김 widget을 준비한다.
- Prompt Engineering thumbnail generation의 active vibe count와 NAI generation late-binding은 loaded-only 조회로 바꿔, 열지 않은 Vibe module을 generation 직전에 깨우지 않는다.

## 3. 테스트 및 정적 리뷰 수행

- `python -m py_compile core\middle_section_controller.py core\remote_api_server.py core\api_service.py`
- `python -m pytest tests\test_middle_section_controller_static_registry.py tests\test_remote_api_status.py -k "vibe_transfer or middle_module" -q`
- `git diff --check` (line-ending warning only)
- Web Shell runtime: `NAIA_cold_v4.py --web-shell --web-shell-port 7260`
- Startup log confirmed `Web Session middle 모듈 지연 로드: vibe_transfer_module -> VibeTransferModule` and total middle modules dropped to 3 loaded modules.
- CDP runtime: Chrome debug port `9351`, Remote Web loaded, Random button changed `#promptEdit`, Generate button stayed enabled, and `openModule('vibe_transfer')` rendered the Vibe panel. Browser log only had `/favicon.ico` 404 plus Chrome background GCM warnings.

## 4. 보완

- This round keeps the existing Vibe frame/encoding PyQt implementation for explicit Remote Web use.
- Because Vibe generation data is now loaded-only, a hidden WebSession that never opens Vibe will not pay the module import/widget cost during startup or plain generation.
- `CharacterModule`, `PromptListModifierModule`, and `PromptEngineeringModule` remain eager because they own active prompt/generation hooks or initial Remote Web prompt-engineering state.

## 5. 커밋

- 커밋 메시지: `Lazy load vibe transfer module for web session`
