# Round 10 - WebSession 미지원 PyQt 탭 런타임 격리

## 라운드 9 이후 남은 문제

결과 이미지 payload helper는 PyQt-free core로 분리되었지만, WebSession에 없는 PyQt 탭 진입점은 아직 일부 남아 있었다. 특히 `TurboEventSequenceTabModule`은 startup import는 lazy spec으로 대부분 막혀 있으나, 숨김 WebSession 런타임에서도 `add_tab_by_name()` 명시 호출이 들어오면 PyQt 탭을 import/생성할 수 있었다.

## 이번 라운드 범위

1. Desktop Turbo Sequence 기능 자체를 삭제하지 않는다.
2. 숨김 WebSession 런타임에서 `TurboEventSequenceTabModule` import/생성을 차단한다.
3. 기존 removed tab guard와 prototype startup skip은 유지한다.
4. WebSession 미지원 탭 목록을 `not_implement/`에 문서화한다.

## 변경 계획

- `core.tab_controller`에 `WEB_SESSION_UNSUPPORTED_TAB_MODULES`를 추가한다.
- `NAIA_CLI_WEB_SESSION_HIDE_MAIN_WINDOW=1` 런타임에서는 해당 탭의 placeholder/import/dynamic add를 차단한다.
- `ModernMainWindow._on_turbo_mode_selected()`도 숨김 WebSession 런타임에서 no-op 처리한다.
- desktop 런타임에서는 Turbo dynamic tab이 계속 load 가능한지 테스트한다.

## 검증 게이트

- `python -m py_compile core/tab_controller.py NAIA_cold_v4.py`
- `python -m pytest tests/test_tab_controller_removed_tabs.py -q`
- Remote API/Remote Web 회귀 테스트
- `git diff --check`
- WebSession 재시작 후 `/api/status` 확인
- Chrome CDP로 Remote Web 루트 로드 확인

## Static Review

- `WEB_SESSION_UNSUPPORTED_TAB_MODULES`는 hidden WebSession 환경 변수에만 반응한다.
- Desktop runtime에서는 `TurboEventSequenceTabModule` 동적 add 경로를 유지한다.
- 차단은 `_get_module_class()` 앞단에서 수행되므로 숨김 WebSession에서는 해당 파일 import 자체가 발생하지 않는다.
- `HookerTabModule`, `StorytellerTabModule`, `AssetsTabModule`의 기존 removed guard는 변경하지 않는다.

## 수행 결과

- 숨김 WebSession 런타임에서 Turbo Sequence 동적 탭 import/생성을 차단했다.
- Turbo mode direct callback도 숨김 WebSession에서 no-op 처리했다.
- `not_implement/web_session_unsupported_tabs.md`에 WebSession 미지원 PyQt 탭 목록과 현재 차단 정책을 기록했다.

## 검증 결과

- `python -m py_compile core/tab_controller.py NAIA_cold_v4.py` 통과.
- `python -m pytest tests/test_tab_controller_removed_tabs.py -q` 통과: 8 passed.
- `python -m py_compile core/tab_controller.py NAIA_cold_v4.py core/remote_api_server.py` 통과.
- `python -m pytest tests/test_tab_controller_removed_tabs.py tests/test_remote_api_status.py -q` 통과: 139 passed.
- `python -m pytest tests/test_result_image_payload_service.py tests/test_prompt_generation_service.py -q` 통과: 10 passed.
- `git diff --check` 통과.
- `--web-shell --web-shell-port 7250` 재시작 후 `/api/status` 정상 응답: `api_mode` NAI, `is_generating` false.
- startup log에서 `turbo_event_sequence_tab.py` startup import skip 및 `Web Session 미지원 탭 placeholder 생략: TurboEventSequenceTabModule` 확인.
- Chrome CDP `9340`에서 `http://127.0.0.1:7250/` 로드 확인: title `NAIA Remote`, readyState `complete`, Generate/생성 관련 UI 텍스트 확인, Turbo 텍스트 미노출.
