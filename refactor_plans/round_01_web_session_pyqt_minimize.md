# Round 01 - Remote Web PyQt6 최소화

## 목표

Remote Web Session이 현재 기능을 유지하는 조건에서, PyQt6 데스크톱 UI에만 필요한 기동 비용을 웹셸/웹세션 경로에서 지연하거나 분리한다.

## 이번 라운드 범위

1. `NAIA_cold_v4.py` 엔트리포인트와 `ModernMainWindow` 초기화 순서를 기준으로 병목을 확인한다.
2. `core/remote_api_server.py`의 FastAPI와 `RemoteBridge(QObject)`가 실제로 어떤 PyQt6 객체에 연결되는지 문서화한다.
3. 기능 위험이 낮은 데스크톱 전용 후처리부터 웹세션 경로에서 지연한다.
4. 정적 검사, 제한 재시작 검사, CDP 기반 Remote Web 확인을 수행한다.
5. 범위가 확인된 변경만 커밋한다.

## 이번 라운드에서 제외

- `RemoteBridge(QObject)` 제거
- `ModernMainWindow` 없는 서버 전용 런타임 도입
- Turbo Sequence, Storyteller, Studio 등 레거시/데스크톱 기능의 파일 이동
- 이미지 히스토리 저장 모델 교체

위 항목들은 직접 기능 회귀 위험이 크므로 의존성 지도를 확정한 뒤 별도 라운드에서 처리한다.

## 1차 변경

- 숨김 Web Session 런타임(`NAIA_CLI_WEB_SESSION_HIDE_MAIN_WINDOW=1`)에서는 AutoCompleteManager, Git 업데이트 확인, 멀티 계정 알림을 즉시 실행하지 않는다.
- 데스크톱 창이 실제로 표시될 때 해당 후처리를 한 번만 실행한다.

## 검증 게이트

- `python -m py_compile NAIA_cold_v4.py core/remote_api_server.py ui/web_wrapper.py`
- 별도 포트로 `NAIA_cold_v4.py --web-session --web-shell-port <port>` 재기동 후 `/api/status` 확인
- Chrome CDP로 Remote Web 루트 로드 및 콘솔 에러 확인

## 수행 결과

- `NAIA_cold_v4.py`에서 숨김 WebSession 런타임의 데스크톱 전용 후처리를 지연했다.
- 별도 포트 재기동에서 `/api/status`가 준비되는 것을 확인했다.
- unbuffered 재기동 로그에서 `Remote API server starting` 전에 데스크톱 전용 후처리 지연 로그가 찍히고, `AutoCompleteManager`는 초기화 완료가 아니라 지연 상태로 남는 것을 확인했다.
- Chrome CDP에서 Remote Web 루트가 `NAIA Remote`로 로드되는 것을 확인했다.

## Static Review

- 변경은 `ModernMainWindow` 내부의 타이머/후처리 scheduling에 한정된다.
- 데스크톱 모드는 기존과 동일하게 생성 직후 timers와 post-show initialization을 예약한다.
- 숨김 WebSession 모드는 데스크톱 창이 실제로 표시될 때 한 번만 AutoCompleteManager/update-check/account-notice를 예약한다.
- Remote API, WebSocket, prompt/generation 계약은 이번 라운드에서 변경하지 않았다.

## 다음 라운드 계획

1. `RemoteBridge`에 `RemoteGenerationState`를 추가하고, Remote Web params/options를 서버 상태 우선으로 전환한다.
2. `tabs/comic_generator_tab.py`처럼 Remote Web에 없는 startup-visible prototype을 `not_implement/` 또는 explicit skip으로 격리한다.
3. `GenerationController` early reject가 WebSocket status에 명확히 반영되도록 결과 contract를 정리한다.
