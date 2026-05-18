# Round 11 - Middle module static registry 전환

## 라운드 10 이후 남은 문제

WebSession 미지원 PyQt 탭은 숨김 런타임에서 차단되었지만, middle section은 여전히 `modules/*_module.py`를 glob discovery로 스캔하고, 발견한 `BaseMiddleModule` subclass를 모두 import 대상으로 삼았다. 이 구조에서는 ignored/local prototype이나 새 실험 모듈 파일이 WebSession startup-visible 해질 수 있다.

## 이번 라운드 범위

1. 지원 middle module 목록을 명시 registry로 고정한다.
2. 임의 `modules/*_module.py` discovery/class scan을 중단한다.
3. 기존 지원 모듈 11개와 WebSession module-state API 계약은 유지한다.
4. 모듈 위젯 생성/초기화 자체는 이번 라운드에서 제거하지 않는다. 생성 hooks와 Remote Web module-state가 아직 module instances에 의존하기 때문이다.

## 변경 계획

- `core.middle_section_controller.MIDDLE_MODULE_SPECS`를 추가한다.
- `load_modules()`가 registry의 `{file, class}`만 import하게 변경한다.
- 등록되지 않은 `*_module.py`는 startup import 대상에서 제외한다.
- registry class name만 선택해 같은 파일 안의 다른 `BaseMiddleModule` subclass를 자동 로드하지 않는다.
- 회귀 테스트로 unregistered module import 차단, registered class 선택, checked-in registry 파일 존재를 검증한다.

## 검증 게이트

- `python -m py_compile core/middle_section_controller.py NAIA_cold_v4.py core/remote_api_server.py`
- `python -m pytest tests/test_middle_section_controller_static_registry.py -q`
- `python -m pytest tests/test_middle_section_controller_static_registry.py tests/test_tab_controller_removed_tabs.py tests/test_remote_api_status.py -q`
- `python -m pytest tests/test_result_image_payload_service.py tests/test_prompt_generation_service.py -q`
- `git diff --check`
- WebSession 재시작 후 `/api/status` 확인
- Chrome CDP로 Remote Web 루트 로드 확인

## Static Review

- registry에는 기존 checked-in middle modules 11개를 모두 포함한다.
- instance sorting은 기존 `get_order()` 기반이므로 UI 순서 계약은 유지된다.
- `PromptEngineeringModule`, `CharacterModule`, `VibeTransferModule` 등 Remote Web이 읽는 모듈 인스턴스는 계속 생성된다.
- 이 변경은 arbitrary discovery를 제거하는 것이며, PyQt widget creation 제거는 다음 라운드의 별도 작업이다.

## 수행 결과

- `MIDDLE_MODULE_SPECS`를 도입하고 `glob("*_module.py")` 기반 discovery를 제거했다.
- registry에 없는 local/prototype `*_module.py`는 startup import되지 않는다.
- registered class name만 로드해 파일 내부 보조 subclass가 자동 노출되지 않는다.
- `tests/test_middle_section_controller_static_registry.py`를 추가했다.

## 검증 결과

- `python -m py_compile core/middle_section_controller.py NAIA_cold_v4.py core/remote_api_server.py` 통과.
- `python -m pytest tests/test_middle_section_controller_static_registry.py -q` 통과: 3 passed.
- `python -m pytest tests/test_middle_section_controller_static_registry.py tests/test_tab_controller_removed_tabs.py tests/test_remote_api_status.py -q` 통과: 142 passed.
- `python -m pytest tests/test_result_image_payload_service.py tests/test_prompt_generation_service.py -q` 통과: 10 passed.
- `git diff --check` 통과.
- `--web-shell --web-shell-port 7251` 재시작 후 `/api/status` 정상 응답: `api_mode` NAI, `is_generating` false.
- startup log에서 `지원 middle 모듈 registry`와 registry 11개 모듈 로드 확인. 기존 `발견된 모듈 파일` glob discovery 로그는 나타나지 않음.
- Chrome CDP `9341`에서 `http://127.0.0.1:7251/` 로드 확인: title `NAIA Remote`, readyState `complete`, Generate/생성 관련 UI 텍스트 확인.
