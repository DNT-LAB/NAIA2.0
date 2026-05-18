# Round 02 - Startup Tab Surface 축소

## 라운드 1 검토

라운드 1은 숨김 WebSession 런타임에서 데스크톱 전용 후처리를 지연해 초기화 비용 일부를 줄였다. 그러나 원 요구사항의 다음 항목은 아직 불완전하다.

- `tabs/*.py` 동적 discovery가 ignored prototype 파일까지 import할 수 있다.
- Remote Web에 없는 PyQt6 탭의 격리 규칙이 `Storyteller/Hooker/Assets`에만 한정되어 있다.
- `RemoteBridge`의 options/params 상태는 아직 Qt 위젯 상태를 주 저장소로 읽는다.
- 랜덤 프롬프트와 이미지 생성 결과 처리는 여전히 `ModernMainWindow`/`ImageWindow` 경로에 강하게 결합되어 있다.

## 이번 라운드 범위

1. startup-visible root tab proxy 중 Remote Web 기능이 아니고 제품 탭으로 등록되지 않은 prototype을 명시적으로 startup import 대상에서 제외한다.
2. `TurboEventSequenceTabModule`은 현재 데스크톱 명시 호출과 generation parameter 경로가 남아 있으므로 이번 라운드에서 제거하지 않는다.
3. 변경 범위는 tracked code에서 loader guard와 회귀 테스트로 제한한다. ignored prototype 파일은 삭제하거나 이동하지 않는다.

## 변경 계획

- `core/tab_controller.py`에 `PROTOTYPE_TAB_FILES`를 추가한다.
- `STARTUP_SKIPPED_TAB_FILES`가 removed, prototype, lazy/dynamic specs를 모두 포함하게 한다.
- `tests/test_tab_controller_removed_tabs.py`에 prototype root tab proxy가 startup import되지 않는 회귀 테스트를 추가한다.

## 검증 게이트

- `python -m py_compile core/tab_controller.py`
- `python -m pytest tests/test_tab_controller_removed_tabs.py`
- 별도 포트 WebSession 재기동 후 log에서 `comic_generator_tab`/`Comic Generator` startup import 흔적이 없는지 확인
- Chrome CDP로 Remote Web 루트 로드 확인

## 수행 결과

- `core/tab_controller.py`에 `PROTOTYPE_TAB_FILES`를 추가하고, `comic_generator_tab.py`가 startup import 대상에서 제외되도록 했다.
- ignored local prototype 파일은 삭제/이동하지 않았다. startup loader의 tracked guard만 갱신했다.
- 회귀 테스트로 `comic_generator_tab.py`가 존재해도 `initialize_tabs()` 중 import되지 않는 것을 고정했다.
- WebSession 재기동 로그에서 `comic_generator_tab.py`가 `시작 시 탭 파일 import 건너뜀`으로 처리되는 것을 확인했다.
- 같은 재기동 로그에서 `Remote API server starting` 이후 Remote Web이 `NAIA Remote`로 로드되는 것을 CDP로 확인했다.
- CLI 인자에는 `--web-shell-port 7258`을 전달했지만 실제 remote server log는 기본 `7243`을 보고했다. 이번 패치 범위와 직접 관련은 없으나, 다음 라운드에서 Web Shell port 전달 경로를 별도 확인할 필요가 있다.

## Static Review

- `TurboEventSequenceTabModule`은 그대로 유지된다. 현재 `NAIA_cold_v4.py`에 명시적 desktop 호출과 `turbo_sequence_request` generation path가 남아 있어 제거하면 기능 회귀 위험이 있다.
- `PROTOTYPE_TAB_FILES`는 startup scan만 줄이며, 정식 `TAB_MODULE_SPECS`의 lazy/dynamic 탭 로딩 계약은 바꾸지 않는다.
- Remote Web API, WebSocket, random/generate payload 계약은 이번 라운드에서 변경하지 않았다.

## 다음 라운드 후보

1. `RemoteBridge` options/params를 서버 소유 state 우선으로 전환한다.
2. random/generate early reject와 `generation_error` WebSocket status contract를 정리한다.
3. 중간 모듈 discovery를 hook registration과 widget creation으로 나눠 숨김 WebSession의 PyQt widget 생성면을 더 줄인다.
