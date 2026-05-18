# Remote Web Session PyQt6 의존성 지도

## 현재 기동 구조

`NAIA_cold_v4.py`는 프로세스 시작 시점에 PyQt6, UI 모듈, 데이터 처리 모듈을 대부분 상단 import로 로드한다. 이후 `QApplication`을 만들고 `ModernMainWindow`를 생성한 뒤, 웹셸 모드에서는 메인 데스크톱 창을 숨긴 상태로 `ui.web_wrapper.WebWrapperWindow`가 `core.remote_api_server.start_remote_server()`를 호출한다.

현재 Remote Web의 핵심 서버는 서버 전용 프로세스가 아니다. `core.remote_api_server.RemoteBridge`가 `QObject`/`pyqtSignal` 기반으로 FastAPI 스레드와 Qt 메인 스레드를 연결하고, 랜덤 프롬프트와 이미지 생성은 기존 `ModernMainWindow`, `GenerationController`, `PromptGenerationController`, `ImageWindow` 상태를 재사용한다.

## WebSession 필수 연결면

- FastAPI/WS 진입점: `core/remote_api_server.py:create_app`, `/ws`, `/api/status`, `/api/random`, `/api/generate`, `/api/latest-image`, `/api/result/image/png`
- Qt 브리지: `core/remote_api_server.py:RemoteBridge`
- 서버 시작: `core/remote_api_server.py:start_remote_server`
- 웹셸 호스트: `ui/web_wrapper.py:WebWrapperWindow`
- 랜덤 프롬프트: `NAIA_cold_v4.py:trigger_random_prompt`, `core/prompt_generation_controller.py`, `core/generation_controller.py`
- 이미지 결과: `core/api_service.py`, `tabs/image_window.py`, `RemoteBridge.on_generation_result`

현재 별도의 `WebSession` 백엔드 클래스는 없다. 실제 WebSession은 `start_remote_server()`, `RemoteBridge`, `WebSocketManager.sessions`, `ui/remote_web/app.js`가 이룬 조합이다.

### 랜덤 프롬프트 경로

1. Remote Web 클라이언트는 `/ws`로 `type: "random"` 메시지와 `_collectCurrentParams()` 기반 overrides를 보낸다.
2. `core.remote_api_server.websocket_endpoint()`가 요청을 `RemoteBridge._pending_random_requests`에 넣고 `request_random`을 emit한다.
3. `RemoteBridge._do_random()`이 Qt 메인 스레드에서 요청을 소비하고, 아직은 `ModernMainWindow.trigger_random_prompt()`로 기존 데스크톱 경로를 호출한다.
4. `PromptGenerationController.generate_next_prompt()`가 프롬프트를 만들고 `prompt_generated`를 publish한다.
5. `RemoteBridge.on_prompt_generated()`가 웹소켓으로 `prompt_generated`를 broadcast하고, pending auto-generate가 있으면 생성까지 이어간다.

### 이미지 생성/결과 경로

1. Remote Web 클라이언트는 `/ws`로 `type: "generate"`와 prompt/negative/overrides를 보낸다.
2. 서버는 `RemoteBridge._pending_generate_requests`에 넣고 `request_generate`를 emit한다.
3. `RemoteBridge._do_generate()`가 `GenerationController.execute_generation_pipeline()`을 호출한다.
4. `GenerationController`는 여전히 `ModernMainWindow.get_main_parameters()` 및 Qt 위젯 상태를 바탕으로 params를 만들고, overrides를 병합한 뒤 `QThread` 기반 worker를 시작한다.
5. `APIService.call_generation_api()`가 NAI/WEBUI/COMFYUI 호출을 수행한다.
6. 결과는 `generation_result_available` 이벤트를 거쳐 `RemoteBridge.on_generation_result()`에서 WebP로 인코딩되어 `image_meta` JSON과 binary frame으로 `/ws`에 push된다.
7. HTTP fallback은 `/api/latest-image`(WebP), `/api/result/image/png`(PNG 변환), `/api/result/metadata`가 담당한다.

## 확인된 PyQt6 결합

- `RemoteBridge` 자체가 `QObject`이고 요청 처리는 `pyqtSignal(...).connect(..., QueuedConnection)`으로 Qt 이벤트 루프에 의존한다.
- `/api/random`과 `/api/generate`는 서버에서 직접 core 함수를 호출하지 않고 `ModernMainWindow`의 UI/컨트롤러 상태를 통해 실행된다.
- 결과 반환은 `ImageWindow` 히스토리 및 현재 이미지 상태와 강하게 결합되어 있다.
- `core/remote_api_server.py`는 클립보드, 파일 다이얼로그, QTimer, QThread 등 데스크톱 기능도 같은 브리지 안에 함께 포함한다.

## 확인된 기동 병목 후보

- `modules/*_module.py` 전체 동적 import 및 위젯 생성: `core/middle_section_controller.py`
- `tabs/*.py` 동적 import는 일부 지연 로딩이 이미 적용되어 있으나 `ImageViewerModule`, `SettingsTabModule`은 즉시 생성된다.
- 숨김 웹셸에서도 `ModernMainWindow._post_show_initialization()`이 AutoCompleteManager와 마지막 검색 상태를 초기화한다.
- 숨김 웹셸에서도 Git 업데이트 확인과 멀티 NAI 계정 알림 타이머가 예약된다.
- `RemoteBridge` 내부에 서버 상태, 데스크톱 동기화, 이미지 히스토리, 클립보드, Cloudflared, 프리셋, Artist Thumb, Character Viewer가 모두 집중되어 있다.

## 동적 로딩 및 격리 후보

- `core/middle_section_controller.py`는 `modules/*_module.py`를 discovery/import한다. 따라서 `modules/` 아래 새 `*_module.py`는 숨김 WebSession에서도 startup-visible하다.
- `core/tab_controller.py`는 `TAB_MODULE_SPECS`와 root `tabs/*.py` scan을 함께 사용한다. lazy tab은 일부 적용됐지만 root proxy 파일은 여전히 startup import 후보가 된다.
- `ui/remote_web/app.js`는 discovery가 아니라 명시적 JS import와 module registry를 쓴다. 데스크톱 탭 추가는 Remote Web 기능 추가가 아니다.
- `not_implement/`는 이미 자동 로딩 경로 밖에 있으며, `not_implement/turbo_module.py`가 placeholder로 존재한다.
- `StorytellerTabModule`, `HookerTabModule`, `AssetsTabModule`은 `TabController`에서 이미 removed guard로 차단된다.
- `TurboEventSequenceTabModule`은 Remote Web에 없는 PyQt 탭이지만 생성 경로에 `turbo_sequence_request` 처리 흔적이 남아 있어 단순 이동은 위험하다.
- `tabs/comic_generator_tab.py`와 `tabs/comic_generator/`는 gitignored prototype이어도 `tabs/` 아래라 startup import 후보가 된다. 다음 격리 라운드에서 가장 먼저 `not_implement/` 이동 또는 explicit skip 대상이다.

## 1차 분리 원칙

1. WebSession 필수 기능이 사용하는 상태를 먼저 유지한다.
2. 데스크톱 표시, 알림, 업데이트 확인, 자동완성 UI처럼 웹세션에 즉시 필요하지 않은 작업은 표시 시점으로 지연한다.
3. `RemoteBridge(QObject)` 제거는 별도 서버 런타임과 WebSession 상태 저장소가 생긴 뒤 진행한다.
4. Turbo Sequence/Storyteller류는 현재 WebSession 기능이 아니므로 다음 라운드에서 호출면을 막고 `NotImplemented` 격리 대상으로 분류한다.

## 다음 라운드 후보

1. `RemoteGenerationState`를 `RemoteBridge` 옆에 도입해 mode/options/params/prompt/negative/rating을 서버 소유 상태로 만든다.
2. `_do_set_option()`, `_do_set_param()`, `get_generation_params()`가 Qt 위젯 대신 서버 상태를 먼저 읽고, 데스크톱 위젯 sync는 mirror로 격하한다.
3. `PromptGenerationController.generate_next_prompt()`에서 순수 prompt service를 분리해 Remote Web이 `ModernMainWindow` mutation 없이 prompt를 만들 수 있게 한다.
4. `GenerationController.execute_generation_pipeline()`의 early return을 `started/queued/rejected` 결과나 `generation_error` publish로 명시해 웹 status가 잘못 `true`로 남지 않게 한다.
5. 중간 모듈은 hook 등록과 widget creation을 나눠 숨김 WebSession에서는 hook-capable logic만 먼저 로드한다.
