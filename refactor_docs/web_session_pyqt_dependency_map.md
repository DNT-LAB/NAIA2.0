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
- `InstantWildcardModule`은 `$...` chunk expansion에 필요한 instant wildcard dictionary/tree를 제공하므로 이 라운드에서는 eager 상태로 유지한다. Round 16에서 해당 JSON store가 PyQt-free service로 분리되면서 lazy 대상이 되었다.
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

### Round 16 Instant Wildcard headless store

- `InstantWildcardModule`은 Remote Web 초기 badge 대상이 아니고 `get_parameters()`도 빈 dict지만, `$group`/`$key` chunk expansion은 `WildcardManager.instant_wildcard_dict/tree`를 읽는다.
- `core.instant_wildcard_service`를 추가해 `save/instant_wildcard/*.json` 로드, default template 생성, duplicate key suffix 처리, file write, AppContext 적용을 PyQt 없이 수행한다.
- `AppContext` 생성 시 instant wildcard store를 `WildcardManager`에 먼저 반영하므로, hidden WebSession에서 PyQt module을 깨우지 않아도 최초 생성 전 `$...` expansion 데이터가 준비된다.
- `RemoteBridge`의 instant wildcard state/edit, chunk state, `$` autocomplete search는 server-owned headless store를 사용하고 더 이상 `_find_module("instant_wildcard")`를 호출하지 않는다.
- `AutoCompleteManager`는 먼저 `WildcardManager` 캐시를 사용하고, 비어 있을 때만 desktop PyQt module fallback을 호출한다.
- hidden WebSession startup에서는 `InstantWildcardModule` import/constructor/widget 생성을 지연한다. Desktop 런타임은 기존 UI wrapper를 유지하며 JSON 로딩만 core service에 위임한다.

### Round 17 Automation headless state

- `AutomationModule`은 Remote Web 초기 handshake와 `start_remote_server()` signal wiring이 `_find_module("automation")`을 호출해 hidden WebSession startup에서 즉시 로드되던 마지막 lazy blocker였다.
- `core.automation_settings`를 추가해 `save/AutomationModule.json`의 default/normalize/load/save와 Remote Web module-state 변환을 PyQt 없이 처리한다.
- `RemoteBridge`는 `_remote_automation_state`를 서버 소유 상태로 보유하고, `_read_automation()`은 이미 로드된 `AutomationModule`만 읽는다. 초기 WebSocket `get_module_state:automation`은 module을 깨우지 않는다.
- Remote Web의 delay/random/repeat/type/timer/count/notify 변경은 headless state와 JSON 설정에 저장되며, `AutomationModule` import/constructor/widget 생성 없이 broadcast된다.
- Remote Web `start`/`stop`은 기존 automation controller와 main window callback 계약을 보존하기 위해서만 `AutomationModule`을 on-demand 로드하고 숨김 widget을 만든다.
- hidden WebSession startup에서는 `AutomationModule` import/constructor/widget 생성을 지연한다. Desktop 런타임은 기존 자동화 UI와 설정 동작을 유지한다.

### Round 18 Character Reference on-demand widget

- `CharacterReferenceModule`은 Remote Web 초기 badge 요청이 `_find_module("character_reference")`를 호출해 hidden WebSession startup에서 module import/widget 생성을 유발하던 image module이었다.
- WebSocket 초기 badge refresh에서 `character_reference` 요청을 제거하고, hidden WebSession에서는 `CharacterReferenceModule`을 lazy 대상으로 표시했다.
- `RemoteBridge._read_character_reference()`와 `_set_character_reference()`는 사용자가 Character Reference 패널을 열거나 이미지를 조작할 때만 deferred module을 로드하고 숨김 widget을 준비한다.
- Character Reference/Vibe Transfer 상호 배타 비활성화는 loaded-only module만 대상으로 바꿔 deferred module을 반대쪽 액션 때문에 깨우지 않는다.
- 이 라운드는 Character Reference의 PyQt frame implementation을 제거하지 않는다. Remote Web에서 실제 업로드, storage 적용, frame 조정이 필요할 때 기존 wrapper를 on-demand로 사용하는 중간 단계다.

### Round 19 Vibe Transfer loaded-only late binding

- `VibeTransferModule`은 Remote Web 초기 badge 요청뿐 아니라 NAI generation late-binding에서도 `get_module_instance("VibeTransferModule")`로 deferred module을 깨울 수 있었다.
- `MiddleSectionController.get_loaded_module_instance()`를 추가해 이미 로드된 module만 조회하는 경로를 만들었다.
- WebSocket 초기 badge refresh에서 `vibe_transfer` 요청을 제거하고, hidden WebSession에서는 `VibeTransferModule`을 lazy 대상으로 표시했다.
- `RemoteBridge._read_vibe_transfer()`와 `_set_vibe_transfer()`는 explicit panel open/action 시에만 deferred module을 로드하고 숨김 widget을 준비한다.
- `APIService`의 Vibe late-binding과 Prompt Engineering thumbnail의 active vibe count는 loaded-only 조회로 바뀌어, Vibe 패널을 열지 않은 plain WebSession generation에서는 module import/widget 비용을 내지 않는다.
- 이 라운드는 Vibe frame/encoding implementation을 core로 대체하지 않는다. 실제 Vibe 사용 시에는 기존 PyQt wrapper를 on-demand로 사용한다.

### Round 20 Character headless settings

- `CharacterModule`은 saved active state가 NAI generation params에 직접 들어가므로 단순 lazy 처리만 하면 WebSession 생성 결과가 바뀔 수 있었다.
- `core.character_settings`를 추가해 `save/CharacterModule_<MODE>.json`에서 mode-aware 설정을 PyQt 없이 읽고, active/cold slot count와 `characters`/`uc` generation params를 만든다.
- hidden WebSession startup에서는 `CharacterModule` import/constructor/widget 생성을 지연한다. 초기 WebSocket `module_state:character`는 headless settings payload로 응답하고 module을 깨우지 않는다.
- `GenerationController`와 `APIService`의 Character late-binding은 loaded-only module 조회 후 headless settings fallback을 사용한다. 따라서 Character 패널을 열지 않은 WebSession generation도 저장된 active character params를 유지한다.
- 상태 미리보기는 별도 `PromptContext`로 계산해 Remote Web state refresh가 기존 sequential wildcard context를 전진시키지 않게 했다.
- `PromptListModifierModule`의 cycle-start character snapshot은 loaded-only 조회로 바꿔, char/uc 규칙이 아닌 일반 조건부 프롬프트 규칙이 CharacterModule을 깨우지 않는다.
- Remote Web Character 편집/preview 액션은 기존 PyQt widget behavior가 필요하므로 `_set_character()`에서만 deferred module을 on-demand 로드하고 숨김 widget을 준비한다.
- 남은 eager middle module은 `PromptEngineeringModule`과 `PromptListModifierModule`이다. 두 모듈은 active prompt hooks, random prompt side effects, initial Remote Web prompt-engineering state를 분리한 뒤 lazy/headless 전환해야 한다.

### Round 21 Conditional prompt headless widget skip

- `PromptListModifierModule`은 saved conditional rules를 generation `after_wildcard` hook에서 적용하므로, module instance와 hook registration은 hidden WebSession startup에서도 유지해야 한다.
- 하지만 Remote Web startup에서 PyQt `QTextEdit`, radio controls, syntax highlighter, log widget, collapsible box를 만들 필요는 없으므로 `web_session_headless_widget` registry flag를 추가했다.
- hidden WebSession `MiddleSectionController.build_ui()`는 해당 flag가 있는 module에 대해 context injection, `on_initialize()`, pipeline hook registration만 수행하고 `create_widget()`을 생략한다.
- `PromptListModifierModule`은 `_headless_settings`를 통해 checkbox/textedit 없이도 enabled, legacy/v2 DSL, editor mode, engine options, active preset을 유지한다.
- `RemoteBridge._read_conditional_prompt()`와 `_set_conditional_prompt()`는 widget-backed state가 없을 때 `collect_current_settings()`/`apply_settings()`를 사용해 Remote Web panel state와 edits를 유지한다.
- 이 라운드는 full lazy 전환이 아니다. full lazy는 saved conditional rules가 generation에서 사라지지 않도록 별도 headless conditional hook/service가 먼저 필요하다.
- 남은 큰 PyQt blocker는 `PromptEngineeringModule`이다. initial Remote Web state, `*randomized` random-prompt side effect, post/after-wildcard hooks를 PyQt-free service로 분리한 뒤에만 lazy 전환이 안전하다.

### Round 22 Prompt Engineering headless widget skip

- `PromptEngineeringModule`은 Remote Web initial state, `*randomized` random-prompt side effect, PromptProcessor `post_processing` hook, `after_wildcard` hooks를 모두 소유하므로 단순 lazy 처리하면 WebSession generation 결과가 바뀔 수 있었다.
- hidden WebSession에서는 module import/instance와 hook registration은 유지하되, PyQt widget tree 생성만 `web_session_headless_widget`으로 생략한다.
- `PromptEngineeringModule`은 `_headless_settings`를 통해 `pre_prompt`, `post_prompt`, `auto_hide_prompt`, `preprocessing_options`, e621/Danbooru settings를 widget 없이 보존한다.
- `register_headless_hooks()`를 추가해 Closed Eyes Sync, e621 Auto-Boost, Danbooru Auto-Weight, Outfit Context Resolver `after_wildcard` hooks를 desktop widget creation과 hidden WebSession이 공유한다.
- `RemoteBridge._read_prompt_engineering()`과 `_set_prompt_engineering()`은 textedit/checkbox 직접 접근 대신 `collect_current_settings()`/`apply_settings()` 기반으로 동작한다. 따라서 Remote Web Prompt Engineering panel은 PyQt widget 없이도 서버 state를 읽고 수정할 수 있다.
- `load_preset_list()`와 `load_preset_random()`은 combo/textedit widget이 없는 headless path에서도 preset list와 `*randomized` pre/post prompt application을 유지한다.
- 이 라운드는 full lazy 전환이 아니다. 다음 단계는 Prompt Engineering preset/headless hook owner를 `core` service로 분리해 hidden WebSession startup에서 `modules.prompt_engineering_module` import 자체를 지연하는 것이다.

### Round 23 Prompt Engineering core state store

- `core.prompt_engineering_settings`를 추가해 mode-aware Prompt Engineering settings, preset list, last-used preset, randomized pool, e621/Danbooru settings를 PyQt 없이 읽고 쓸 수 있게 했다.
- `RemoteBridge._read_prompt_engineering()`은 loaded module을 우선 사용하되, loaded `PromptEngineeringModule`이 없으면 core store로 같은 `module_state` payload를 만든다.
- `RemoteBridge._set_prompt_engineering()`은 loaded module이 없을 때도 prefix/postfix/auto-hide/preprocessing toggle, preset save/create/delete, randomized pool, e621/Danbooru settings를 core store로 처리한다.
- Artist Thumbnail random Prompt Engineering override도 loaded module이 없으면 core store settings를 사용한다.
- 이 라운드는 full lazy 전환의 선행 단계다. hidden WebSession startup에서는 아직 `PromptEngineeringModule` instance와 hooks가 남아 있으며, post/after-wildcard hook owner와 `*randomized` subscriber를 core runtime으로 분리해야 import 자체를 지연할 수 있다.

### Round 24 Prompt Engineering lazy runtime

- `core.prompt_engineering_runtime`을 추가해 hidden WebSession의 Prompt Engineering `post_processing` hook, four after-wildcard hooks, `*randomized` subscriber를 PyQt-free owner로 분리했다.
- `PromptEngineeringModule`은 hidden WebSession registry에서 `web_session_lazy=True`가 되었고 startup import/instance/widget 생성 대상에서 빠졌다.
- `MiddleSectionController`는 `web_session_headless_hook="prompt_engineering"`을 만나면 core runtime hooks를 등록하고, 나중에 `PromptEngineeringModule`이 on-demand 로드되더라도 post hook을 중복 등록하지 않는다.
- headless post hook의 option precedence는 Event Stream frozen options, session override, already-loaded module, core store 순서다. 이로써 Event Stream freeze와 Remote Web per-request override는 기존 우선순위를 유지한다.
- advanced e621/Danbooru 처리는 metadata predicate가 있을 때만 module을 on-demand 로드한다. 일반 Prompt Engineering panel open/state refresh/random prompt generation은 module을 깨우지 않는다.
- Closed Eyes Sync는 NAI request characters와 이미 로드된 CharacterModule clone만 동기화한다. CharacterModule이 아직 lazy 상태라면 이 hook 때문에 새로 로드하지 않는다.
- CDP 검증에서 hidden WebShell startup은 `Web Session headless middle hook 등록: PromptEngineeringModule`만 기록했고, `모듈 로드 성공: prompt_engineering_module -> PromptEngineeringModule` 또는 `지연 middle 모듈 로드 완료: PromptEngineeringModule`은 발생하지 않았다.
- 남은 eager middle module은 `PromptListModifierModule`이다. 현재는 saved conditional rules를 generation hook에 적용하기 위해 instance/hook은 유지하고 widget만 생략한다. full lazy 전환은 conditional-prompt core hook/service 분리 후 진행해야 한다.
