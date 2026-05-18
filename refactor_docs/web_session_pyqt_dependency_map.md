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

### Round 02 격리 결정

- `tabs/comic_generator_tab.py`는 ignored local prototype root proxy이므로 `PROTOTYPE_TAB_FILES`로 startup import를 차단한다.
- ignored prototype 파일은 사용자 작업물일 수 있어 삭제/이동하지 않고, tracked loader guard로만 startup-visible 표면을 줄인다.
- `TurboEventSequenceTabModule`은 `NAIA_cold_v4.py`의 명시적 `add_tab_by_name("TurboEventSequenceTabModule")` 호출과 `turbo_sequence_request` generation path가 남아 있으므로 이번 라운드에서는 유지한다.
- 이 결정은 Remote Web 기능 보존을 우선하고, WebSession에 없는 prototype 탭이 숨김 웹셸 startup에서 PyQt6 위젯/의존성을 끌어오는 문제만 제거한다.

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

### Round 03 상태 축소 결정

- `get_generation_params()`는 여전히 데스크톱 full snapshot reader로 유지한다. 이 함수는 mode 변경과 preset load에서 desktop-authoritative reset payload를 만드는 계약에 쓰인다.
- `get_options()`는 server-owned `_remote_option_state`를 반환하도록 변경한다. 실제 Qt checkbox 읽기는 `_read_desktop_options()`로 분리하고, desktop-origin toggle slot에서만 state로 adopt한다.
- Web-origin `set_param`은 `_remote_param_values`를 먼저 갱신하고 타입을 보존한 full params payload를 broadcast한다. 특히 bool 값은 `"false"` 문자열이 아니라 `False`로 유지한다.
- `_cached_params`는 schema-only cache로 유지해 WebSocket init의 선택지/schema 경로와 full selected-state 경로를 분리한다.
- 이 라운드는 `RemoteBridge(QObject)` 자체를 제거하지 않고, FastAPI/WS thread가 반복적으로 Qt widget을 읽는 표면을 줄이는 중간 단계다.

### Round 04 상태 축소 결정

- 생성 status payload는 `_generation_status_payload()`와 `_send_generation_status()`로 중앙화한다.
- `_remote_is_generating`을 RemoteBridge의 server-owned state로 두고, status 송신 시마다 갱신한다.
- 큐 실행 조건, 이미지 결과 WebP broadcast, `generation_error` scoped payload는 그대로 유지한다.

### Round 05 prompt core 분리 결정

- `PromptGenerationController(QObject)`는 데스크톱 UI signal wrapper로 남기되, 실제 PromptContext 생성, source row 정규화, silent prompt 생성, next-source 준비는 `core.prompt_generation_service.PromptGenerationService`로 이동한다.
- `PromptGenerationService`는 PyQt6를 import하지 않고, `PromptProcessor`도 실제 processing 호출 시점에 lazy 생성한다. 따라서 Remote Web 경로가 service 객체를 준비하는 것만으로 `main_window.wildcard_manager`를 즉시 요구하지 않는다.
- `RemoteBridge`의 Danbooru prompt preview와 result queue reopen prompt는 더 이상 `app_context.main_window.prompt_gen_controller.generate_instant_source_silent()`를 직접 호출하지 않고, `app_context.prompt_generation_service`를 통해 처리한다.
- WEBUI Hires preset swap도 `main_window.prompt_gen_controller` 직접 접근 대신 `prompt_generation_service`를 사용한다.
- `_do_random()`은 아직 `ModernMainWindow.trigger_random_prompt()`를 유지한다. 이 호출을 바로 제거하면 snapshot restore, Event Stream prepare, UI 버튼 상태, auto-generation 연결을 동시에 재구현해야 하므로 별도 라운드로 분리한다.

### Round 06 random auto-generate 판정 축소

- Remote Web random 요청의 auto-generate 판정은 요청 overrides의 `auto_generate`를 최우선으로 사용한다.
- request override가 없으면 server-owned `_remote_option_state["auto_generate"]`와 `_remote_auto_generate_enabled`를 사용하고, 마지막 fallback으로만 데스크톱 option snapshot을 읽는다.
- `_do_random()`은 더 이상 pending override의 `auto_generate` 결정을 위해 `main_window.generation_checkboxes["자동 생성"]`을 직접 읽지 않는다.
- `ModernMainWindow.trigger_random_prompt()` 호출은 여전히 남아 있으므로, 다음 단계에서는 snapshot/event-stream/UI side effect를 core runner와 UI wrapper로 나눠야 한다.

### Round 07 prepared-source random 직접 실행

- Remote random 요청에서 `source_row`가 이미 준비된 경우에는 `ModernMainWindow.trigger_random_prompt()`를 거치지 않고 `PromptGenerationService`로 직접 PromptContext를 생성한다.
- 이 직접 실행은 plain WebSocket random 요청에만 적용한다. ComfyUI random, Event Preset, Remote Preset 요청은 기존 scoped pending 계약이 더 넓으므로 유지한다.
- Event Stream이 활성화된 경우에는 기존 desktop wrapper 경로로 fallback한다.
- normal random처럼 desktop `search_results`에서 pop하거나 snapshot restore가 필요한 경로는 아직 fallback으로 남긴다.

### Round 08 normal random 직접 실행

- source row가 없는 plain WebSocket random도 `search_results` 또는 memory snapshot에서 source row를 준비할 수 있으면 `PromptGenerationService`로 직접 실행한다.
- memory snapshot, `data/naia_temp_rows.parquet`, `data/tags/tags_129.parquet` fallback은 UI label/status 변경 없이 `SearchResultModel`만 복원한다.
- `ModernMainWindow.trigger_random_prompt()` fallback은 Event Stream 활성 경로, preset/comfyui scoped 경로, 비정상/테스트 context처럼 `search_results` 표면이 없는 경우에만 남는다.
- 이 라운드 이후 plain Remote Web random의 일반 경로는 더 이상 desktop button/status wrapper를 통과하지 않는다.

### Round 09 result image payload helper 분리

- `/api/result/image/png`, `/api/history/image/*`, `/api/history/thumb/*`, `/api/history/meta/*`가 쓰는 PNG/WEBP/media-type/metadata summary helper를 `core.result_image_payload_service`로 분리했다.
- 새 helper는 PyQt/QObject를 import하지 않고, PIL과 PNG metadata utility는 실제 이미지 변환 시점에만 lazy import한다.
- `RemoteBridge`의 기존 private method 이름은 wrapper로 유지해 FastAPI route와 기존 테스트 계약을 보존한다.
- 저장 경로 검증, history item 탐색, 파일 thumbnail disk cache는 아직 `RemoteBridge`에 남아 있다. 이 부분은 `ImageWindow`/history widget 접근과 연결되어 있어 별도 상태 저장소 분리 후 다음 라운드에서 줄여야 한다.
- 이 라운드 이후 결과 이미지 bytes 변환과 메모리 history thumbnail 생성은 PyQt bridge 밖의 pure service에서 검증할 수 있다.

### Round 10 WebSession 미지원 PyQt 탭 격리

- `TurboEventSequenceTabModule`은 desktop dynamic tab으로는 유지하되, 숨김 WebSession 런타임에서는 `TabController`가 import/생성을 차단한다.
- 차단 기준은 `NAIA_CLI_WEB_SESSION_HIDE_MAIN_WINDOW=1`과 `WEB_SESSION_UNSUPPORTED_TAB_MODULES`이며, desktop 런타임의 `add_tab_by_name()` 경로는 유지된다.
- `ModernMainWindow._on_turbo_mode_selected()`도 숨김 WebSession 런타임에서는 no-op 처리해 직접 호출 경로를 막았다.
- WebSession 미지원 PyQt 탭 목록은 `not_implement/web_session_unsupported_tabs.md`에 기록했다.
- 이 라운드는 `tabs/turbo_event_sequence/` 구현 자체를 이동하지 않는다. 해당 구현은 generation path의 `turbo_sequence_request`와 연결되어 있어 desktop 제거는 별도 제품 결정과 더 넓은 회귀 검증이 필요하다.

### Round 11 middle module static registry 전환

- `core.middle_section_controller`가 더 이상 `modules/*_module.py`를 glob discovery로 전부 import하지 않는다.
- 지원 middle module 목록은 `MIDDLE_MODULE_SPECS`의 `{file, class}` registry로 고정했다.
- registry에 없는 local/prototype `*_module.py`는 startup-visible하지 않으며, 등록된 파일 안에서도 지정 class만 middle module로 노출된다.
- 기존 지원 모듈 11개는 모두 registry에 포함되어 Remote Web module-state API와 generation hook 표면을 보존한다.
- 아직 숨김 WebSession에서도 middle module widget 생성은 남아 있다. 이 부분은 각 모듈의 state/hook headless contract를 분리한 뒤 단계적으로 줄여야 한다.

### Round 12 Ollama middle module WebSession lazy loading

- `OllamaModule`은 generation parameter/hook surface가 없고 Remote Web에서 Ollama 패널 요청 시에만 필요하므로 hidden WebSession startup에서는 import/instance 생성을 지연한다.
- Desktop 런타임에서는 기존처럼 즉시 로드된다.
- `MiddleSectionController.get_module_instance()`가 deferred module을 on-demand import/initialize/hook-register 할 수 있게 되었고, `RemoteBridge._find_module()`은 이 lookup path를 사용한다.
- Remote Web Ollama 상태/액션은 기존 `_remote_*` fallback state와 worker path를 유지해 widget 없이도 동작 가능한 경로를 사용한다.
- 다음 후보는 `OllamaModule`처럼 pipeline hook이 없거나 Remote Web initial state에 불필요한 모듈을 추가 식별해 같은 lazy flag를 확대하는 것이다.

### Round 13 Wildcard status WebSession lazy loading

- `WildcardStatusModule`은 pipeline hook이 없고 Remote Web 초기 handshake 대상도 아니므로 hidden WebSession startup에서는 import/instance/widget 생성을 지연한다.
- 단순 lazy 처리만 하면 `prompt_squeeze_enabled`와 `scoped_wildcard` 설정 로드가 사라져 생성 동작이 바뀔 수 있으므로, `core.wildcard_status_settings`를 추가해 `AppContext` 생성 시 PyQt 없이 설정을 적용한다.
- `RemoteBridge._read_wildcard()`는 더 이상 `WildcardStatusModule`을 찾거나 깨우지 않고, `AppContext.current_prompt_context`와 `WildcardManager`만 읽어 module-state payload를 만든다.
- Remote Web의 `wildcard.prompt_squeeze`, `reload`, `reset_sequential`, wildcard file-tree/read/save/delete/create/preview 액션은 서버 상태와 `WildcardManager` 기반으로 처리한다. `open_manager`처럼 실제 PyQt 창이 필요한 액션만 deferred module을 on-demand 로드한다.
- `InstantWildcardModule`은 생성 파라미터와 instant wildcard dictionary를 제공하므로 이번 라운드에서 eager 상태로 유지한다.
- 다음 lazy 후보는 `E621EventModuleV2`이다. Remote Web launcher/on-demand 표면이고 초기 state 요청 대상은 아니지만, constructor의 e621 data check/download side effect와 `_read_e621_event()` cache 계약을 별도 라운드에서 먼저 검증해야 한다.

### Round 14 E621 event module WebSession lazy loading

- `E621EventModuleV2`는 Remote Web 초기 handshake 대상이 아니며, 사용자가 E621 연구모듈을 열 때만 필요한 prompt-tool surface이다.
- hidden WebSession startup에서는 `E621EventModuleV2` import/constructor/widget 생성을 지연한다. 이로써 startup 중 `data/e621_data` 존재 확인 및 E621 widget setup을 생략한다.
- Remote Web의 `get_module_state:e621_event` 또는 E621 launcher open 시에는 기존 `RemoteBridge._find_module()` deferred lookup으로 모듈을 on-demand 로드하고, 기존 `_read_e621_event()` state builder를 유지한다.
- lazy 로드된 E621 모듈은 startup 시점의 `MainController.connect_e621_event_signals()` 연결 루프를 지나치므로, Remote Web `e621_event.generate`는 module signal에 의존하지 않고 `main_window.on_instant_generation_requested(tags_data)`를 직접 호출한다. direct callback이 없는 비정상 context에서만 기존 signal fallback을 사용한다.
- Desktop 런타임은 `web_session_lazy` 조건에 걸리지 않으므로 기존 즉시 로드와 signal 연결을 유지한다.

### Round 15 Reference Inset headless hook

- `ReferenceInsetAutoInjectModule`은 Remote Web 초기 badge/status 대상이 아니고, 필수 런타임 동작은 PromptProcessor `final_hookpoint`에서 `reference inset` 태그를 삽입하는 pure PromptContext mutation이다.
- 이 로직을 `core.reference_inset_service`로 분리했다. service는 PyQt를 import하지 않으며, PromptContext hook과 APIService 생성 시점 문자열 안전망이 같은 구현을 공유한다.
- hidden WebSession에서는 `ReferenceInsetAutoInjectModule` import/constructor/widget 생성을 지연하고, 대신 `ReferenceInsetAutoInjectHook`을 headless pipeline hook으로 등록한다.
- Desktop 런타임에서는 기존 PyQt module UI와 checkbox 토글을 유지한다.
- `AutomationModule`은 이번 감사에서 lazy 후보에서 제외했다. Remote Web 초기 handshake와 server startup signal wiring이 `_find_module("automation")`을 통해 모듈을 깨우며, generation parameter 기본값도 모듈 인스턴스에 묶여 있기 때문이다. Automation lazy 전환은 별도 headless state/default parameter service가 선행되어야 한다.
