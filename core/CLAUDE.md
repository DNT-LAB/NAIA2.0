# CLAUDE.md — core/

> **목적**: NAIA 2.0의 핵심 시스템 계층. AppContext, 컨트롤러, 파이프라인, API 브릿지 등 애플리케이션의 중추를 담당합니다.

---

## 목차

1. [개요](#개요)
2. [주요 파일 및 역할](#주요-파일-및-역할)
3. [AppContext: 중앙 상태 관리자](#appcontext-중앙-상태-관리자)
4. [컨트롤러 시스템](#컨트롤러-시스템)
5. [프롬프트 파이프라인](#프롬프트-파이프라인)
6. [API 서비스](#api-서비스)
7. [데이터 매니저](#데이터-매니저)
8. [실전 예제](#실전-예제)
9. [개발 워크플로우](#개발-워크플로우)
10. [문제 해결](#문제-해결)
11. [체크리스트](#체크리스트)
12. [참고 자료](#참고-자료)

---

## 개요

### core/ 디렉터리의 역할

core/는 NAIA 2.0의 **핵심 시스템 계층**으로, 다음을 담당합니다:

- 🎯 **중앙 상태 관리**: AppContext를 통한 공유 자원 관리
- 🔄 **이벤트 버스**: 컴포넌트 간 느슨한 결합 통신
- 🎨 **파이프라인 훅**: 모듈이 프롬프트 생성 과정에 개입
- 🌐 **API 브릿지**: 다중 백엔드 (NAI/WEBUI/COMFYUI) 지원
- 🧩 **컨트롤러**: UI/모듈/탭 생명주기 관리
- 📊 **데이터 관리**: 태그, 와일드카드, 필터 등

### 다른 디렉터리와의 관계

```
core/
  ├── interfaces/를 통해 ← modules/, tabs/와 계약 정의
  ├── ui/를 통해 → UI 컴포넌트 관리
  ├── utils/를 통해 → 유틸리티 함수 사용
  └── data/를 통해 → 데이터 파일 로드
```

**의존성 흐름**:
```
NAIA_cold_v4.py (메인)
    ↓
core/main_controller.py
    ↓
core/context.py (AppContext 생성)
    ↓
core/middle_section_controller.py ← modules/ 로드
core/tab_controller.py ← tabs/ 로드
core/prompt_generation_controller.py
core/generation_controller.py
```

### 언제 core/를 수정하는가?

| 작업 | 수정 파일 |
|------|----------|
| **새 공유 서비스 추가** | `context.py` |
| **새 이벤트 추가** | `context.py` (이벤트 이름만, 코드 변경 불필요) |
| **파이프라인 단계 추가** | `prompt_processor.py` |
| **새 API 백엔드 추가** | `api_service.py` |
| **컨트롤러 동작 수정** | `*_controller.py` |
| **와일드카드 로직 수정** | `wildcard_manager.py`, `wildcard_processor.py` |

---

## 주요 파일 및 역할

| 파일 | 크기 | 역할 | 주요 클래스/함수 |
|------|------|------|-----------------|
| **context.py** | 9.1K | 중앙 상태 관리, 이벤트 버스 | `AppContext` |
| **api_service.py** | 74K | API 호출 (NAI/WEBUI/COMFYUI) | `APIService` |
| **generation_controller.py** | 33K | 이미지 생성 워커, **시퀀스 생성** | `GenerationController`, `GenerationWorker` |
| **sequence_parser.py** | 🆕 8.9K | 시퀀스 프롬프트 파싱 및 검증 | `SequenceParser` |
| **generation_queue_manager.py** | 12K | 생성 큐 관리 (우선순위, 일시정지) | `GenerationQueueManager` |
| **autocomplete_manager.py** | 68K | 태그 자동완성 | `AutocompleteManager` |
| **comfyui_workflow_manager.py** | 30K | ComfyUI 워크플로우 관리 | `ComfyUIWorkflowManager` |
| **middle_section_controller.py** | 19K | 모듈 로딩 및 관리 | `MiddleSectionController` |
| **comfyui_service.py** | 16K | ComfyUI HTTP/WS 통신 | `ComfyUIService` |
| **wildcard_processor.py** | 14K | 와일드카드 치환 | `WildcardProcessor` |
| **image_crud_controller.py** | 17K | 이미지 파일 CRUD 관리 | `ImageCrudController` |
| **tab_controller.py** | 9.4K | 탭 로딩 및 관리 | `TabController` |
| **main_controller.py** | 28K | 메인 컨트롤러 (검색/생성 통합) | `MainController` |
| **search_engine.py** | 6.7K | 태그 검색 엔진 | `SearchEngine` |
| **prompt_processor.py** | 6.4K | 프롬프트 파이프라인 | `PromptProcessor` |
| **wildcard_manager.py** | 6.5K | 와일드카드 파일 로딩 | `WildcardManager` |
| **webui_utils.py** | 5.9K | WebUI 유틸리티 | 헬퍼 함수들 |
| **prompt_generation_controller.py** | 5.8K | 프롬프트 생성 컨트롤러 | `PromptGenerationController` |
| **search_controller.py** | 4.5K | 검색 컨트롤러 | `SearchController` |
| **mode_ware_manager.py** | 4.0K | 모드 인식 모듈 관리 | `ModeAwareModuleManager` |
| **search_result_model.py** | 3.2K | 검색 결과 모델 | `SearchResultModel` |
| **tag_data_manager.py** | 2.8K | 태그 데이터 관리 | `TagDataManager` |
| **prompt_context.py** | 1.9K | 프롬프트 컨텍스트 데이터 클래스 | `PromptContext` |
| **filter_data_manager.py** | 1.8K | 필터 데이터 관리 | `FilterDataManager` |
| **secure_token_manager.py** | 1.7K | 토큰 암호화 저장 | `SecureTokenManager` |
| **generation_request.py** | 5.0K | 생성 요청 데이터 클래스 | `GenerationRequest` |
| **api_validator.py** | 9.2K | API 검증 | 검증 함수들 |
| **comfyui_utils.py** | 11K | ComfyUI 유틸리티 | 헬퍼 함수들 |

---

## AppContext: 중앙 상태 관리자

### 위치 및 역할

**파일**: `core/context.py:20-191`

`AppContext`는 NAIA 2.0의 **중앙 허브**로, 다음을 제공합니다:

1. **공유 서비스 등록**: API, 데이터 매니저, 토큰 매니저 등
2. **이벤트 버스**: subscribe/publish를 통한 컴포넌트 간 통신
3. **파이프라인 훅 레지스트리**: 모듈이 프롬프트 생성 과정에 개입
4. **API 모드 관리**: NAI/WEBUI/COMFYUI 전환
5. **세션 관리**: 저장 경로, 현재 컨텍스트 등

### 초기화

`core/context.py:22-54`

```python
class AppContext:
    def __init__(self, main_window, wildcard_manager, tag_data_manager):
        # 핵심 참조
        self.main_window = main_window
        self.wildcard_manager = wildcard_manager
        self.tag_data_manager = tag_data_manager

        # 서비스
        self.api_service = APIService(self)
        self.comfyui_workflow_manager = ComfyUIWorkflowManager()
        self.secure_token_manager = SecureTokenManager()
        self.filter_data_manager = FilterDataManager()

        # 🆕 이미지 파일 관리 (2025-01-08)
        self.image_crud_controller = ImageCrudController(self)

        # 모드 관리
        self.current_api_mode = "NAI"
        self.mode_swap_subscribers = []
        self.mode_manager = ModeAwareModuleManager(self)

        # 파이프라인 훅 레지스트리
        self.pipeline_hooks = {}

        # 이벤트 버스
        self.subscribers = {}

        # 세션 상태
        self.current_source_row = None
        self.current_prompt_context = None
        self.session_save_path = Path("output") / datetime.now().strftime('%Y%m%d_%H%M%S')
```

### 이벤트 버스 사용법

#### 이벤트 구독

`core/context.py:110-118`

```python
# 기본 사용법
def my_callback(data: dict):
    print(f"이벤트 수신: {data}")

app_context.subscribe("event_name", my_callback)
```

**실제 예시** (모듈에서):
```python
class MyModule(BaseMiddleModule):
    def initialize_with_context(self, app_context):
        self.app_context = app_context

        # 모드 변경 이벤트 구독
        app_context.subscribe("api_mode_changed", self._on_mode_changed)

        # 프롬프트 생성 완료 이벤트 구독
        app_context.subscribe("prompt_generated", self._on_prompt_generated)

    def _on_mode_changed(self, data: dict):
        old_mode = data["old_mode"]
        new_mode = data["new_mode"]
        print(f"모드 변경 감지: {old_mode} → {new_mode}")

    def _on_prompt_generated(self, context):
        final_prompt = context.final_prompt
        print(f"생성된 프롬프트: {final_prompt[:100]}...")
```

#### 이벤트 발행

`core/context.py:120-129`

```python
# 기본 사용법
app_context.publish("event_name", {"key": "value"})
```

**실제 예시** (컨트롤러에서):
```python
# 프롬프트 생성 완료 알림
self.app_context.publish("prompt_generated", context)

# 저장 경로 변경 알림
self.app_context.publish("save_directory_changed", {"new_path": str(new_path)})
```

### 주요 이벤트 목록

| 이벤트 이름 | 발행자 | 데이터 구조 | 용도 |
|------------|--------|------------|------|
| `api_mode_changed` | `AppContext.set_api_mode()` | `{"old_mode": str, "new_mode": str}` | 모드 전환 알림 |
| `prompt_generated` | `PromptGenerationController` | `PromptContext` | 프롬프트 생성 완료 |
| `save_directory_changed` | `ImageCrudController.set_base_save_directory()` | `{"new_path": str}` | 저장 경로 변경 |
| `image_counter_changed` | `ImageCrudController.increment_counter()` | `{"new_counter": int}` | 이미지 저장 카운터 변경 |
| `hello_world_clicked` | 예시 | `{"message": str}` | 커스텀 이벤트 |

### 파이프라인 훅 시스템

#### 훅 등록

`core/context.py:131-148`

```python
def register_pipeline_hook(self, hook_info: dict, module_instance):
    """파이프라인 훅 레지스트리에 모듈 등록"""
    pipeline_name = hook_info['target_pipeline']  # 예: 'PromptProcessor'
    hook_point = hook_info['hook_point']  # 예: 'post_processing'
    priority = hook_info.get('priority', 999)

    # 우선순위순 정렬하여 저장
    self.pipeline_hooks.setdefault(pipeline_name, {}).setdefault(hook_point, [])
    self.pipeline_hooks[pipeline_name][hook_point].append((priority, module_instance))
    self.pipeline_hooks[pipeline_name][hook_point].sort(key=lambda x: x[0])
```

**사용 예시** (모듈에서):
```python
class MyModule(BaseMiddleModule):
    def get_pipeline_hook_info(self) -> dict:
        return {
            'target_pipeline': 'PromptProcessor',
            'hook_point': 'post_processing',
            'priority': 10  # 낮을수록 먼저 실행
        }

    def execute_pipeline_hook(self, context):
        # 프롬프트 수정
        context.main_tags.append("custom_tag")
        return context
```

#### 훅 실행

`core/context.py:150-154`

```python
def get_pipeline_hooks(self, pipeline_name: str, hook_point: str):
    """특정 훅 포인트에 등록된 모듈 목록 반환 (우선순위순)"""
    hooks = self.pipeline_hooks.get(pipeline_name, {}).get(hook_point, [])
    return [module_instance for priority, module_instance in hooks]
```

### API 모드 관리

#### 모드 변경

`core/context.py:56-72`

```python
def set_api_mode(self, mode: str):
    """API 모드 변경 및 구독자 알림"""
    if mode in ["NAI", "WEBUI", "COMFYUI"] and mode != self.current_api_mode:
        old_mode = self.current_api_mode
        self.current_api_mode = mode

        # 레거시 구독자 알림
        for callback in self.mode_swap_subscribers:
            callback(old_mode, mode)

        # 이벤트 시스템 알림
        self.publish("api_mode_changed", {"old_mode": old_mode, "new_mode": mode})
```

**사용 예시**:
```python
# 모드 변경
app_context.set_api_mode("WEBUI")

# 현재 모드 확인
current_mode = app_context.get_api_mode()  # "WEBUI"
```

### API Payload 안전 저장

`core/context.py:161-191`

```python
def store_api_payload(self, payload: dict, api_type: str = "Unknown"):
    """API 요청 데이터를 안전하게 저장 (디버깅용)"""
    # Thread-safe 저장

def get_api_payload(self) -> dict:
    """저장된 API 요청 데이터 반환"""
```

---

## 컨트롤러 시스템

NAIA 2.0는 **컨트롤러 패턴**을 사용하여 각 영역의 생명주기를 관리합니다.

### MiddleSectionController: 모듈 관리자

**파일**: `core/middle_section_controller.py:16-200+`

#### 역할

- `modules/` 디렉터리 스캔 및 동적 로딩
- 모듈 인스턴스 생성 및 UI 배치
- AppContext 주입
- 모드 변경 시 가시성 제어
- 모듈 분리/복귀 기능
- 🆕 **모듈 상태 추적** (펼침/접힘/분리/스크롤 위치)
- 🆕 **아코디언 동작** (하나만 펼치기)
- 🆕 **자동 스크롤** (모듈로 이동)
- 🆕 **상태 영속성** (`save/module_states.json`)

#### 초기화 및 로딩

`core/middle_section_controller.py:22-37`

```python
class MiddleSectionController:
    def __init__(self, modules_dir: str, app_context: AppContext, parent: QWidget = None):
        self.modules_dir = modules_dir
        self.app_context = app_context
        self.module_classes = []
        self.module_instances = []
        self.detached_modules = {}  # 분리된 모듈 추적
        self.module_boxes = {}  # CollapsibleBox 추적

        # 🆕 모듈 상태 추적
        self.module_states = {
            'expanded': set(),      # 현재 펼쳐진 모듈들 (title)
            'detached': set(),      # 현재 분리된 모듈들 (title)
            'scroll_positions': {}  # {title: scroll_position}
        }

        # 🆕 아코디언 모드 (하나만 펼치기)
        self.accordion_mode = True

        # API 모드 변경 이벤트 구독
        app_context.subscribe("api_mode_changed", self.on_api_mode_changed)
```

#### 모듈 로딩 프로세스

`core/middle_section_controller.py:59-101`

```python
def load_modules(self):
    """modules/*_module.py 파일 동적 로드"""
    pattern = os.path.join(self.modules_dir, "*_module.py")
    module_files = glob.glob(pattern)

    for path in module_files:
        name = Path(path).stem
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # BaseMiddleModule 상속 클래스 찾기
        for attr in dir(module):
            obj = getattr(module, attr)
            if isinstance(obj, type) and issubclass(obj, BaseMiddleModule):
                self.module_classes.append(obj)
```

#### 컨텍스트 주입

`core/middle_section_controller.py:103-143`

```python
def initialize_modules_with_context(self, app_context):
    """모듈에 AppContext 주입 및 ModeAware 등록"""
    for module_instance in self.module_instances:
        module_instance.app_context = app_context

        # ModeAwareModule 자동 등록
        if isinstance(module_instance, ModeAwareModule):
            app_context.mode_manager.register_module(module_instance)
            module_instance.current_mode = app_context.get_api_mode()
```

#### 모드 변경 처리

`core/middle_section_controller.py:39-57`

```python
def on_api_mode_changed(self, data: dict):
    """API 모드 변경 시 모듈 가시성 업데이트"""
    new_mode = data.get("new_mode")

    for title, box in self.module_boxes.items():
        module_instance = next((inst for inst in self.module_instances
                                if inst.get_title() == title), None)
        if module_instance:
            is_compatible = module_instance.is_compatible_with_mode(new_mode)
            box.setVisible(is_compatible)
```

#### 🆕 모듈 상태 추적 및 아코디언 동작

`core/middle_section_controller.py:421-564`

**주요 메서드**:

```python
# 모듈 토글 이벤트 처리
def on_module_toggled(self, module_title: str, is_expanded: bool):
    """모듈 펼침/접힘 상태 변경 이벤트"""
    if is_expanded:
        self.module_states['expanded'].add(module_title)

        # 아코디언 모드: 다른 모듈 접기
        if self.accordion_mode:
            self._collapse_other_modules(module_title)

        # 자동 스크롤
        self._scroll_to_module(module_title)
    else:
        self.module_states['expanded'].discard(module_title)

    self.save_module_states()

# 아코디언 모드 설정
def set_accordion_mode(self, enabled: bool):
    """아코디언 모드 활성화/비활성화"""
    self.accordion_mode = enabled

# 상태 가져오기
def get_module_states(self) -> dict:
    """현재 모듈 상태 반환"""
    return {
        'expanded': list(self.module_states['expanded']),
        'detached': list(self.module_states['detached']),
        'scroll_positions': self.module_states['scroll_positions'].copy(),
        'accordion_mode': self.accordion_mode
    }

# 상태 저장/로드
def save_module_states(self):
    """모듈 상태를 save/module_states.json에 저장"""

def load_module_states(self):
    """저장된 상태 로드 및 UI 복원"""
```

**아코디언 동작**:
- 하나의 모듈이 펼쳐지면 다른 모듈들 자동으로 접힘
- 분리된 모듈은 영향 받지 않음
- `accordion_mode` 플래그로 제어 가능

**자동 스크롤**:
- 모듈 펼칠 때 해당 모듈로 자동 스크롤
- 부모 QScrollArea 자동 탐색
- 100ms 지연으로 UI 업데이트 대기

**상태 파일 구조** (`save/module_states.json`):
```json
{
  "expanded": ["👤 NAID4 캐릭터"],
  "detached": [],
  "scroll_positions": {
    "👤 NAID4 캐릭터": 350,
    "⚙️ 자동 생성": 0
  },
  "accordion_mode": true
}
```

**사용 예시**:
```python
# 아코디언 모드 비활성화 (여러 모듈 동시 펼치기)
controller.set_accordion_mode(False)

# 현재 상태 확인
states = controller.get_module_states()
print(f"펼쳐진 모듈: {states['expanded']}")
print(f"분리된 모듈: {states['detached']}")

# 상태 수동 저장
controller.save_module_states()
```

### TabController: 탭 관리자

**파일**: `core/tab_controller.py:15-150+`

#### 역할

- `tabs/` 디렉터리 스캔 및 동적 로딩
- 탭 인스턴스 생성 및 QTabWidget에 추가
- core/closable 타입별 처리
- 동적 탭 추가/제거
- 닫기 버튼 관리

#### 초기화

`core/tab_controller.py:25-37`

```python
class TabController(QWidget):
    tab_added = pyqtSignal(str, object)
    tab_removed = pyqtSignal(str)

    def __init__(self, tabs_dir: str, app_context: AppContext,
                 tab_widget: QTabWidget, parent: QWidget = None):
        self.tabs_dir = tabs_dir
        self.app_context = app_context
        self.tab_widget = tab_widget
        self.module_classes = []
        self.module_instances = {}
        self.tab_index_map = {}
```

#### 탭 로딩 및 초기화

`core/tab_controller.py:39-81`

```python
def initialize_tabs(self):
    """탭 모듈 로드 및 UI 구성"""
    self._load_tab_modules()

    # order 순서로 정렬
    sorted_classes = sorted(self.module_classes, key=lambda c: c().get_tab_order())

    for cls in sorted_classes:
        temp_instance = cls()

        # core 타입만 시작 시 로드
        if temp_instance.get_tab_type() != 'core':
            continue

        instance = cls()
        instance.initialize_with_context(self.app_context)
        widget = instance.create_widget(parent=self.tab_widget)

        tab_index = self.tab_widget.addTab(widget, instance.get_tab_title())
        self.module_instances[instance.tab_id] = instance
        self.tab_index_map[instance.tab_id] = tab_index

        # 닫기 버튼 추가 (closable 탭만)
        if instance.can_close_tab():
            self._add_close_button_to_tab(tab_index, instance.tab_id)
```

### PromptGenerationController: 프롬프트 생성 컨트롤러

**파일**: `core/prompt_generation_controller.py:8-116`

#### 역할

- UI와 PromptProcessor 중재
- PromptContext 생성 및 초기화
- 파이프라인 실행
- 결과 시그널 발행

#### 주요 시그널

```python
class PromptGenerationController(QObject):
    prompt_generated = pyqtSignal(str)  # 최종 프롬프트
    generation_error = pyqtSignal(str)  # 에러 메시지
    prompt_popped = pyqtSignal(int)  # 남은 프롬프트 수
    resolution_detected = pyqtSignal(int, int)  # 자동 맞춤 해상도
```

#### PromptContext 생성

`core/prompt_generation_controller.py:21-41`

```python
def _create_initial_context(self, source_row: pd.Series, settings: dict) -> PromptContext:
    """PromptContext 생성 및 초기 태그 설정"""

    # 기존 순차 카운터 보존
    existing_sequential_counters = {}
    existing_wildcard_state = {}
    if self.app_context.current_prompt_context:
        existing_sequential_counters = self.app_context.current_prompt_context.sequential_counters.copy()
        existing_wildcard_state = self.app_context.current_prompt_context.wildcard_state.copy()

    context = PromptContext(source_row=source_row, settings=settings)
    context.sequential_counters = existing_sequential_counters
    context.wildcard_state = existing_wildcard_state

    # 초기 태그 설정
    general_str = source_row.get('general', '')
    if pd.notna(general_str) and isinstance(general_str, str):
        context.main_tags = [tag.strip() for tag in general_str.split(',')]

    return context
```

#### 프롬프트 생성 실행

`core/prompt_generation_controller.py:85-115`

```python
def generate_next_prompt(self, search_results: SearchResultModel, settings: dict):
    """다음 프롬프트 생성"""

    # 와일드카드 단독 모드 확인
    if settings.get('wildcard_standalone', False):
        source_row = pd.Series({'general': None, ...}, name="wildcard_standalone")
    else:
        source_row = search_results.pop_random_row()

    # AppContext에 저장
    self.app_context.current_source_row = source_row
    self.app_context.current_prompt_context = self._create_initial_context(source_row, settings)

    # 파이프라인 실행
    final_context = self.processor.process()

    # 시그널 발행
    if 'detected_resolution' in final_context.metadata:
        width, height = final_context.metadata['detected_resolution']
        self.resolution_detected.emit(width, height)

    self.prompt_generated.emit(final_context.final_prompt)
    self.app_context.publish("prompt_generated", final_context)
```

### GenerationController: 이미지 생성 컨트롤러

**파일**: `core/generation_controller.py:1-400+`

#### 역할

- QThread 워커로 비동기 이미지 생성
- API 호출 및 결과 후처리
- 메타데이터 추출
- 스레드 정리 및 메모리 관리
- 🆕 **시퀀스 생성 지원** (`:begin`, `:seq`, `:end` 구문)

#### QThread 워커 패턴

`core/generation_controller.py:55-111`

```python
class GenerationWorker(QObject):
    generation_started = pyqtSignal()
    generation_progress = pyqtSignal(str)
    generation_finished = pyqtSignal(dict)
    generation_error = pyqtSignal(str)

    def run_generation(self):
        """별도 스레드에서 실행되는 생성 작업"""
        try:
            self.generation_started.emit()
            self.generation_progress.emit("API 호출 중...")

            # 시간이 오래 걸리는 API 호출
            api_result = self.context.api_service.call_generation_api(self.params)

            # 에러 확인
            if api_result.get('status') == 'error':
                self.generation_error.emit(api_result.get('message'))
                return

            # 후처리
            processed_result = self._post_process(api_result)

            # 메타데이터 추출
            if processed_result.get('image'):
                info_text = self._extract_info_from_image(processed_result['image'])
                processed_result['info'] = info_text

            self.generation_finished.emit(processed_result)

        except Exception as e:
            self.generation_error.emit(str(e))
```

#### 스레드 정리

`core/generation_controller.py:12-53`

```python
def _force_cleanup_all_threads():
    """모든 스레드 풀 및 연결 정리 (메모리 누수 방지)"""
    # urllib3 연결 풀 정리
    # requests 세션 정리
    # Qt 스레드 풀 정리
    # 가비지 컬렉션
    # Qt 이벤트 루프 처리
```

**중요**: 모든 API 호출 후 반드시 `_force_cleanup_all_threads()` 호출!

#### 임시 창 Virtual Module 훅 수동 실행

**파일**: `core/generation_controller.py:375-411`

임시 생성 창(Temporary Generation Window) 시스템에서는 AppContext 파이프라인을 우회하고 Virtual Module의 훅을 **수동으로 실행**합니다.

**배경**: 임시 창은 메인 UI와 독립적으로 동작하며, 메인 UI 모듈의 훅을 실행하지 않고 자체 Virtual Module의 훅을 실행해야 합니다.

**구현**:

```python
# 🆕 임시 창 프롬프트 엔지니어링 훅 수동 실행
if 'temp_window_prompt_engineering_tab' in params:
    prompt_eng_tab = params['temp_window_prompt_engineering_tab']
    print(f"[TempWindow] 프롬프트 엔지니어링 훅 수동 실행 중...")

    # PromptContext 생성
    from core.prompt_context import PromptContext
    import pandas as pd

    source_row = self.context.current_source_row
    if source_row is None:
        source_row = pd.Series({'general': None}, name="temp_window")

    # tags 파싱 (쉼표로 분리)
    input_tags = [tag.strip() for tag in params['input'].split(',') if tag.strip()]

    # PromptContext 초기화
    temp_context = PromptContext(
        source_row=source_row,
        settings=params,
        prefix_tags=[],
        main_tags=input_tags,
        postfix_tags=[]
    )

    # 수동 훅 실행
    try:
        modified_context = prompt_eng_tab.execute_manual_hook(temp_context)

        # 수정된 태그를 다시 문자열로 결합
        all_tags = modified_context.prefix_tags + modified_context.main_tags + modified_context.postfix_tags
        params['input'] = ', '.join(all_tags)

        print(f"✅ [TempWindow] 프롬프트 엔지니어링 적용 완료: '{params['input'][:50]}...'")
    except Exception as e:
        print(f"⚠️ [TempWindow] 프롬프트 엔지니어링 훅 실행 오류: {e}")
```

**실행 위치**: 와일드카드 확장 이후, API 호출 이전 (일반 파이프라인의 `post_processing` 훅 포인트와 동일한 위치)

**파라미터 전달 방법**:

임시 창에서 생성 요청 시, Virtual Module 참조를 파라미터에 포함:

```python
# ui/temp_generation_window.py:277-283
def generate_single_image(self):
    params = self._collect_generation_params()

    # Virtual Module 참조 전달
    if hasattr(self, 'prompt_engineering_tab'):
        params['temp_window_prompt_engineering_tab'] = self.prompt_engineering_tab

    # 생성 요청
    self.app_context.generation_controller.generate_image(params)
```

**Virtual Module 구조**:

- **파일**: `ui/virtual_prompt_engineering_tab.py`
- **클래스**: `VirtualPromptEngineeringTab(QWidget)`
- **메서드**: `execute_manual_hook(context: PromptContext) -> PromptContext`
- **특징**: AppContext 파이프라인에 등록되지 않음, 메인 모듈 로직 복제

**관련 패턴**:

- **Virtual Module 패턴**: `ui/CLAUDE.md` → "임시 생성 창 시스템" 섹션
- **Skip Flag 패턴**: `modules/CLAUDE.md` → "고급 패턴" → "Skip Flag 패턴"

#### 와일드카드 단독 모드 (Wildcard Standalone Mode)

**위치**: `core/generation_controller.py:384-399`

**목적**: 임시 창에서 데이터베이스 태그 없이 와일드카드만으로 프롬프트를 생성할 수 있도록 지원합니다.

**동작 원리**:

임시 창에서 `wildcard_standalone` 파라미터가 `True`로 전달되면, `source_row`를 빈 데이터(`pd.Series` with all `None` values)로 생성하여 데이터베이스 태그가 프롬프트에 추가되지 않도록 합니다.

**구현**:

```python
# core/generation_controller.py:384-399
# source_row 준비 (와일드카드 단독 모드 지원)
if params.get('wildcard_standalone', False):
    # 와일드카드 단독 모드: 빈 데이터로 source_row 생성
    empty_data = {
        'general': None,
        'character': None,
        'copyright': None,
        'artist': None,
        'meta': None
    }
    source_row = pd.Series(empty_data, name="wildcard_standalone")
    print(f"[TempWindow] 와일드카드 단독 모드: 빈 source_row 생성")
else:
    source_row = self.context.current_source_row
    if source_row is None:
        source_row = pd.Series({'general': None}, name="temp_window")
```

**파라미터 전달 방법**:

임시 창에서 와일드카드 단독 모드 체크박스 상태를 파라미터에 포함:

```python
# ui/temp_generation_window.py:286-287
def _collect_generation_params(self) -> dict:
    params = {
        'input': self.main_prompt_input.toPlainText(),
        'negative_prompt': self.negative_prompt_input.toPlainText(),
        # ...
    }

    # 와일드카드 단독 모드 플래그
    if hasattr(self, 'wildcard_standalone_checkbox'):
        params['wildcard_standalone'] = self.wildcard_standalone_checkbox.isChecked()

    return params
```

**Random Prompt 처리**:

임시 창의 Random/Next Prompt 버튼에서도 와일드카드 단독 모드를 지원합니다:

```python
# NAIA_cold_v4.py:547-562 (TempWindowManager.handle_random_prompt_request)
# source_row 준비 (와일드카드 단독 모드 지원)
if hasattr(temp_window, 'wildcard_standalone_checkbox') and temp_window.wildcard_standalone_checkbox.isChecked():
    empty_data = {
        'general': None,
        'character': None,
        'copyright': None,
        'artist': None,
        'meta': None
    }
    source_row = pd.Series(empty_data, name="wildcard_standalone")
    print(f"[DEBUG] 와일드카드 단독 모드: 빈 source_row 생성")
else:
    source_row = self.app_context.current_source_row
```

**사용 시나리오**:

1. **와일드카드만 사용**: 데이터베이스의 랜덤 태그 없이 와일드카드만으로 프롬프트 구성
2. **프롬프트 엔지니어링 테스트**: Virtual Module의 프리픽스/포스트픽스/Auto Hide 기능만 테스트
3. **커스텀 프롬프트 생성**: 사용자가 직접 입력한 태그만 사용

**관련 문서**:

- **UI 구현**: `ui/CLAUDE.md` → "임시 생성 창 시스템" → "TempGenerationWindow 추가 기능" → "2. 와일드카드 단독 모드"

### ImageCrudController: 이미지 파일 관리 컨트롤러

**파일**: `core/image_crud_controller.py:1-700+`

#### 역할

- 이미지 저장 로직 중앙화
- Thread-safe 카운터 관리
- 파일 중복 방지
- 카운터 영속성 (app_settings.json) - **재시작 시 항상 1로 초기화**
- 이벤트 기반 카운터 업데이트
- 🆕 **파일명 형식 지원** (number_only, time_number, datetime)
- 🆕 **프롬프트 기반 분류 시스템** (prompt_recognition)
- 🆕 **타임스탬프 폴더 토글** (선택적 날짜_시간 폴더 사용)
- 🆕 **2차 분류 시스템** (계층적 폴더 구조 지원)

#### 주요 속성

`core/image_crud_controller.py:26-67`

```python
class ImageCrudController:
    def __init__(self, app_context):
        self.app_context = app_context
        self._save_counter: int = 1
        self._base_save_path: Path = Path("output")
        self._counter_lock = Lock()  # Thread-safe

        # 🆕 파일명 형식: "number_only", "time_number", "datetime"
        self._filename_format: str = "number_only"

        # 🆕 분류 방법: "none", "prompt_recognition"
        self._classification_method: str = "none"

        # 🆕 분류 규칙: 쉼표로 구분된 조건 문자열
        self._classification_rules: str = ""

        # 🆕 타임스탬프 폴더 사용 여부
        self._use_timestamp_folder: bool = True

        # 🆕 2차 분류 설정
        self._secondary_classification_enabled: bool = False
        self._secondary_classification_method: str = "none"  # "none", "prompt_recognition"
        self._secondary_classification_rules: dict = {}  # {primary_folder: secondary_rules_text}

        # ✅ 카운터는 항상 1로 초기화 (재시작 시)
        self._load_counter_from_settings()
```

#### 저장 경로 관리

`core/image_crud_controller.py:68-103`

```python
def get_save_directory(self, classification_subfolder: Optional[str] = None) -> Path:
    """
    현재 저장에 사용될 최종 디렉토리 경로를 반환합니다.

    타임스탬프 폴더 사용 여부에 따라:
    - True: base_path / session_timestamp / [classification]
    - False: base_path / [classification]

    Parameters:
        classification_subfolder (str, optional): 분류 하위 폴더명 (예: "1girl", "landscape")

    Returns:
        Path: 저장할 디렉토리 경로
    """
    # 타임스탬프 폴더 사용 여부에 따라 경로 결정
    if self._use_timestamp_folder:
        # 타임스탬프 폴더 사용: base_path/20250109_143520/[classification]
        session_timestamp = self.app_context.session_timestamp
        save_dir = self._base_save_path / session_timestamp

        if classification_subfolder:
            save_dir = save_dir / classification_subfolder
    else:
        # 타임스탬프 폴더 미사용: base_path/[classification]
        save_dir = self._base_save_path

        if classification_subfolder:
            save_dir = save_dir / classification_subfolder

    return save_dir
```

**경로 예시**:

| 타임스탬프 폴더 | 분류 폴더 | 2차 분류 | 결과 경로 |
|----------------|----------|---------|----------|
| ✅ True | None | - | `output/20250109_143520/00001.png` |
| ✅ True | "1girl" | None | `output/20250109_143520/1girl/00001.png` |
| ✅ True | "1girl" | "solo" | `output/20250109_143520/1girl/solo/00001.png` |
| ❌ False | None | - | `output/00001.png` |
| ❌ False | "1girl" | None | `output/1girl/00001.png` |
| ❌ False | "1girl" | "solo" | `output/1girl/solo/00001.png` |

#### 파일 저장 (3-tuple 반환)

`core/image_crud_controller.py:222-330`

```python
def save_image(self, image_bytes: bytes, as_webp: bool = False,
               metadata: Optional[dict] = None,
               classification_subfolder: Optional[str] = None) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    이미지를 저장하고 3-tuple 반환
    Returns: (success, filepath, error_message)
    """
    try:
        # 저장 디렉토리 생성 (분류 폴더 포함)
        save_dir = self.get_save_directory(classification_subfolder=classification_subfolder)
        save_dir.mkdir(parents=True, exist_ok=True)

        # 파일명 생성 (중복 방지)
        filename = self.generate_filename(extension="webp" if as_webp else "png")
        filepath = str(save_dir / filename)

        # 이미지 저장 (메타데이터 포함)
        # ...

        # 카운터 증가 및 이벤트 발행
        self.increment_counter()

        return True, filepath, None
    except Exception as e:
        return False, None, str(e)
```

#### 카운터 관리

`core/image_crud_controller.py:158-167`

```python
def increment_counter(self):
    """카운터 증가 및 이벤트 발행"""
    with self._counter_lock:
        self._save_counter += 1
        self._persist_counter()
        self.app_context.publish("image_counter_changed", {
            "new_counter": self._save_counter
        })
```

#### 파일명 생성 (중복 방지)

`core/image_crud_controller.py:122-152`

```python
def generate_filename(self, extension: str = "png", use_counter: bool = True) -> str:
    """파일명 생성 (중복 시 카운터 자동 증가)"""
    save_dir = self.get_save_directory()
    if use_counter:
        with self._counter_lock:
            while True:
                filename = f"{self._save_counter:05d}.{extension}"
                if not (save_dir / filename).exists():
                    break
                print(f"⚠️ 파일 중복 방지: {filename} 건너뜀")
                self._save_counter += 1
    return filename
```

#### 프롬프트 기반 분류 시스템

`core/image_crud_controller.py:407-678`

ImageCrudController는 프롬프트를 기반으로 이미지를 자동 분류하는 시스템을 제공합니다.

**분류 규칙 형식**:
```
*1girl,
(*solo&*1girl),
(landscape|scenery),
nsfw
```

**규칙 구문**:
- `*tag`: 퍼펙트 매칭 (쉼표로 분리된 태그 리스트에서 정확히 일치)
- `tag`: 포함 검사 (부분 문자열 일치)
- `&`: AND 연산자 (모두 만족)
- `|`: OR 연산자 (하나라도 만족)
- `()`: 그룹핑
- `,`: 규칙 구분 (작성 순서대로 우선순위)

**동작 방식**:
```python
def _classify_by_prompt(self, classification_info: dict) -> str:
    """
    프롬프트 규칙에 따라 분류 폴더명을 반환

    1. classification_rules를 쉼표로 분리
    2. 각 규칙을 순서대로 평가
    3. 첫 번째 만족하는 규칙의 폴더명 반환
    4. 모두 만족하지 않으면 "misc" 반환
    """
    tags = classification_info.get("tags", [])
    rules = self._split_classification_rules(self._classification_rules)

    for rule in rules:
        if self._evaluate_classification_condition(rule, tags):
            folder_name = self._condition_to_folder_name(rule)
            return folder_name

    return "misc"
```

**폴더명 변환 규칙**:
- `&` → `_and_`
- `|` → `_or_`
- `*` → 제거
- `()` → 제거
- 공백 → `_`

**예시**:
```python
규칙: "(*solo&*1girl)"  → 폴더명: "solo_and_1girl"
규칙: "(landscape|scenery)" → 폴더명: "landscape_or_scenery"
규칙: "*1girl" → 폴더명: "1girl"
```

#### 2차 분류 시스템 (계층적 폴더 구조)

`core/image_crud_controller.py:776-813`

2차 분류 시스템은 1차 분류된 폴더 내에 추가로 하위 분류를 적용합니다.

**동작 방식**:
1. 1차 분류 규칙을 평가하여 primary 폴더 결정
2. 2차 분류가 활성화되어 있고, 해당 primary 폴더에 대한 2차 규칙이 있으면
3. 2차 규칙을 평가하여 secondary 폴더 결정
4. 최종 경로: `primary_folder/secondary_folder`

**예시**:
```
1차 규칙: *solo, arm, (hold|phone), *standing, feet
2차 규칙 (solo 폴더): *sitting, *standing, lying

이미지 태그: ["solo", "1girl", "sitting", "indoors"]
→ 1차 매칭: "solo" (퍼펙트 매칭)
→ 2차 매칭: "sitting" (퍼펙트 매칭)
→ 최종 경로: output/20250109_143520/solo/sitting/00001.png
```

**2차 분류 메서드**:
```python
def _apply_secondary_classification(self, secondary_rules_text: str, tags: List[str]) -> Optional[str]:
    """
    2차 분류 규칙을 적용하여 서브폴더명을 반환

    Returns:
        str or None: 2차 분류 서브폴더명, 또는 None (분류 실패 시 1차 폴더만 사용)
    """
```

#### 설정 및 제어 메서드

```python
# 파일명 형식 설정
controller.set_filename_format("time_number")  # "number_only", "time_number", "datetime"
current_format = controller.get_filename_format()

# 분류 방법 설정
controller.set_classification_method("prompt_recognition")  # "none", "prompt_recognition"
current_method = controller.get_classification_method()

# 분류 규칙 설정
controller.set_classification_rules("*1girl, (*solo&*1girl), nsfw")
current_rules = controller.get_classification_rules()

# 타임스탬프 폴더 사용 여부
controller.set_use_timestamp_folder(False)  # True/False
use_timestamp = controller.get_use_timestamp_folder()

# 🆕 2차 분류 설정
controller.set_secondary_classification_enabled(True)
controller.set_secondary_classification_method("prompt_recognition")
controller.set_secondary_classification_rules({
    "solo": "*sitting, *standing, lying",
    "1girl": "*uniform, *casual, *swimsuit"
})
```

#### 사용 예시

```python
# ImageWindow에서
success, filepath, error = self.app_context.image_crud_controller.save_image(
    image_bytes=raw_bytes,
    as_webp=True,
    classification_subfolder="1girl"  # 분류 폴더 지정
)

if success:
    print(f"✅ 저장 완료: {filepath}")
else:
    print(f"❌ 저장 실패: {error}")

# 2차 분류가 활성화된 경우
# classification_subfolder는 "primary/secondary" 형식으로 자동 생성됨
# 예: "solo/sitting" → output/20250109_143520/solo/sitting/00001.png
```

---

## 생성 큐 시스템 (Generation Queue System)

**파일**:
- `core/generation_request.py:1-135`
- `core/generation_queue_manager.py:1-288`
- `core/generation_controller.py:233-773`

### 개요

생성 큐 시스템은 이미지 생성 중에도 추가 요청을 큐에 저장하고, 순차적으로 처리할 수 있게 합니다.

**주요 특징**:
- 🚀 **비동기 큐잉**: 생성 중에도 버튼 활성 상태 유지, 클릭 시 큐에 추가
- 📊 **우선순위 지원**: 긴급 요청 (priority 100) vs 일반 요청 (priority 0)
- 🔒 **스레드 안전**: `threading.Lock`을 사용한 동기화
- ⏸️ **일시정지/재개**: 큐 처리를 일시적으로 중단 가능

**상세 레퍼런스**: [Generation Queue 가이드](.claude/GENERATION_QUEUE_CLAUDE.md)
- GenerationRequest 데이터 클래스
- GenerationQueueManager API
- GenerationController 통합
- MainController UI 통합 (키보드 단축키, 컨텍스트 메뉴)
- 큐 이벤트 시스템
- 사용 시나리오
- 문제 해결

---

## 자동생성-큐 핸드오프 시스템

**참조**: `docs/AUTOGEN_QUEUE_HANDOFF_PLAN.md`

### 개요

자동생성 모드와 수동 큐 시스템이 동시에 동작할 때, **큐 우선 처리** 원칙으로 핸드오프를 수행합니다.

**핵심 원칙**:
1. **큐가 비어있지 않으면** → 큐 우선 처리, 자동생성 대기
2. **큐가 비면** → 자동생성 재개, 보류된 재시도 실행
3. **UI 피드백** → 버튼 상태로 현재 상태 표시

**조정 플래그**:
- `queue_hold_auto_gen`: 큐가 있는 동안 자동생성 보류
- `auto_retry_pending`: 큐 때문에 보류된 자동재시도

**상세 레퍼런스**: [자동생성-큐 핸드오프 가이드](.claude/AUTO_GENERATION_HANDOFF_CLAUDE.md)
- NAIA_cold_v4.py: 자동생성 트리거
- GenerationController: 큐-자동생성 조정
- 전체 흐름도
- 검증 시나리오
- 문제 해결

---

## 프롬프트 파이프라인

**파일**: `core/prompt_processor.py:7-144`

### 파이프라인 실행 순서

`core/prompt_processor.py:14-33`

```python
def process(self) -> PromptContext:
    """프롬프트 파이프라인 실행"""
    context = self.app_context.current_prompt_context

    # 단계별 실행
    context = self._run_hooks('pre_processing', context)
    context = self._step_2_fit_resolution(context)
    context = self._run_hooks('post_processing', context)
    context = self._step_3_expand_wildcards(context)
    context = self._run_hooks('after_wildcard', context)
    context = self._run_hooks('final_hookpoint', context)
    context.final_prompt = self._step_final_format(context)

    return context
```

**실행 순서**:
```
1. pre_processing 훅       ← 모듈 개입
2. 해상도 자동 맞춤         (내부 처리)
3. post_processing 훅      ← 모듈 개입
4. 와일드카드 확장         (내부 처리)
5. after_wildcard 훅       ← 모듈 개입
6. final_hookpoint 훅      ← 모듈 개입
7. 최종 포맷팅             (내부 처리)
```

### 훅 실행

`core/prompt_processor.py:35-46`

```python
def _run_hooks(self, hook_point: str, context: PromptContext) -> PromptContext:
    """등록된 훅 순서대로 실행"""
    hooks_to_run = self.app_context.get_pipeline_hooks(self.PIPELINE_NAME, hook_point)

    for module_hook in hooks_to_run:
        try:
            context = module_hook.execute_pipeline_hook(context)
        except Exception as e:
            print(f"파이프라인 훅 실행 오류 ({module_hook.get_title()}): {e}")

    return context
```

### 와일드카드 확장

`core/prompt_processor.py:70-74`

```python
def _step_3_expand_wildcards(self, context: PromptContext) -> PromptContext:
    """와일드카드를 실제 태그로 치환"""
    context.prefix_tags = self.wildcard_processor.expand_tags(context.prefix_tags, context)
    context.postfix_tags = self.wildcard_processor.expand_tags(context.postfix_tags, context)
    return context
```

### 최종 포맷팅

`core/prompt_processor.py:76-144`

- 인물 태그 정렬 (boys → girls → others)
- 태그 자동 변환 (`v` → `peace sign`)
- 중복 제거
- 주석 포맷팅 (`#...`)

---

## API 서비스

**파일**: `core/api_service.py:18-600+`

### 다중 백엔드 지원

#### API 호출 분기

`core/api_service.py:69-155`

```python
def call_generation_api(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """API 모드에 따라 적절한 메서드 호출"""

    # 입력 정리: 주석 제거, 개행 제거
    if 'input' in parameters:
        original_prompt = parameters['input']
        cleaned_tags = []
        for tag in original_prompt.split(','):
            processed_tag = tag.replace('\n', '').strip()
            if processed_tag and not processed_tag.startswith('#'):
                cleaned_tags.append(processed_tag)
        parameters['input'] = ', '.join(cleaned_tags)

    # seed:, resolution: 파라미터 파싱
    # ... (파라미터 처리 로직)

    api_mode = parameters.get('api_mode', 'NAI')

    # 재시도 로직
    for attempt in range(1, max_retries + 1):
        try:
            if api_mode == "NAI":
                result = self._call_nai_api(parameters)
            elif api_mode == "WEBUI":
                result = self._call_webui_api(parameters)
            elif api_mode == "COMFYUI":
                result = self._call_comfyui_api(parameters)

            if result and result.get('status') == 'success':
                return result
        except Exception as e:
            last_exception = e

    return {'status': 'error', 'message': str(last_exception)}
```

#### HTTP 스레드 정리

`core/api_service.py:31-67`

```python
def _cleanup_http_threads(self):
    """HTTP 연결 스레드 정리 (메모리 누수 방지)"""
    # urllib3 연결 풀 정리
    # requests 세션 정리
    # Qt 스레드 풀 정리
    # 가비지 컬렉션
```

**중요**: 모든 API 메서드 마지막에 반드시 호출!

### 캐릭터 위치 동적 좌표 처리 🆕

**파일**: `core/api_service.py:424-452`

**목적**: character_module에서 전달된 동적 위치 좌표를 NovelAI API의 `centers` 파라미터로 전달합니다.

#### 배경

NAID4 모델은 `v4_prompt.caption.char_captions`에서 각 캐릭터의 화면 위치를 지정할 수 있습니다:
- `centers`: 배열 형태, 각 요소는 `{"x": float, "y": float}` (0.0~1.0 범위)
- 기본값: `[{"x": 0.5, "y": 0.5}]` (화면 중앙)

#### 구현

```python
# core/api_service.py:424-452
if char_params and char_params.get("characters"):
    characters = char_params["characters"]
    ucs = char_params["uc"]
    # 🆕 캐릭터 위치 좌표 가져오기 (없으면 빈 리스트)
    character_positions = char_params.get("character_positions", [])

    print(f"[DEBUG] character_positions: {character_positions}")

    # 캐릭터 프롬프트를 v4_prompt에 추가
    for i, prompt in enumerate(characters):
        # 🆕 동적 좌표 사용 (위치가 지정되어 있으면 사용, 없으면 기본값 0.5)
        if i < len(character_positions):
            centers = [character_positions[i]]
        else:
            centers = [{"x": 0.5, "y": 0.5}]

        api_parameters['v4_prompt']['caption']['char_captions'].append({
            'char_caption': prompt,
            'centers': centers  # 동적 좌표 적용
        })
        api_parameters['v4_negative_prompt']['caption']['char_captions'].append({
            'char_caption': ucs[i] if i < len(ucs) else "",
            'centers': centers  # negative도 동일 좌표 사용
        })
```

#### 좌표 매핑

`character_module.py`에서 생성되는 `character_positions` 파라미터 구조:

```python
# 예시: 2명의 캐릭터
character_positions = [
    {'x': 0.1, 'y': 0.1},  # 캐릭터 1: A1 위치 (좌상단)
    {'x': 0.9, 'y': 0.9}   # 캐릭터 2: E5 위치 (우하단)
]
```

**좌표 변환 규칙** (character_module.py에서):
- **A-E (열)** → x: 0.1, 0.3, 0.5, 0.7, 0.9
- **1-5 (행)** → y: 0.1, 0.3, 0.5, 0.7, 0.9

| 위치 | x | y | 설명 |
|------|---|---|------|
| A1 | 0.1 | 0.1 | 좌상단 |
| C3 | 0.5 | 0.5 | 중앙 (기본값) |
| E5 | 0.9 | 0.9 | 우하단 |
| B2 | 0.3 | 0.3 | 좌상단 근처 |
| D4 | 0.7 | 0.7 | 우하단 근처 |

#### Fallback 동작

1. **위치 기능 비활성화 시**: `character_positions` 파라미터 자체가 전달되지 않음
   → 모든 캐릭터에 `{"x": 0.5, "y": 0.5}` 기본값 사용

2. **위치 개수 부족 시**: `character_positions` 배열 길이 < 캐릭터 개수
   → 부족한 캐릭터는 `{"x": 0.5, "y": 0.5}` 기본값 사용

3. **Sketchbook 모드**: 현재 Sketchbook은 위치 기능 미지원
   → 항상 `{"x": 0.5, "y": 0.5}` 사용

#### 디버깅

**콘솔 출력 확인**:
```
[DEBUG] character_positions: [{'x': 0.1, 'y': 0.1}, {'x': 0.9, 'y': 0.9}]
📍 캐릭터 위치 좌표: [{'x': 0.1, 'y': 0.1}, {'x': 0.9, 'y': 0.9}]
```

**문제 해결**:

**Q: 좌표가 항상 0.5로 나와요**
- **원인 1**: `character_module.py`의 `enable_position_checkbox`가 체크되지 않음
- **원인 2**: `get_parameters()`에서 `character_positions` 생성 로직 누락
- **해결**: 위치 체크박스 활성화 후 `get_parameters()` 반환값 확인

**Q: API에서 좌표를 인식하지 못해요**
- **원인**: `character_positions` 파라미터 형식 오류
- **해결**: `{'x': float, 'y': float}` 딕셔너리 형태 확인, 리스트로 감싸기 (`[coord_dict]`)

#### 관련 코드

- **좌표 생성**: `modules/character_module.py:1329-1365` (`get_parameters()`)
- **시각화**: `modules/character_module.py:1460-1510` (`_update_position_viewer()`)
- **API 전달**: `core/api_service.py:424-452`
- **좌표 검증 문서**: `docs/character_position_coordinate_verification.md`

---

## 데이터 매니저

### WildcardManager: 와일드카드 관리

**파일**: `core/wildcard_manager.py:6-150+`

#### 역할

- `wildcards/` 디렉터리 스캔 및 로드
- Instant Wildcard 관리
- 리로드 콜백

#### 와일드카드 로딩

`core/wildcard_manager.py:15-75`

```python
def activate_wildcards(self):
    """wildcards/ 디렉터리 재귀 탐색 및 로드"""
    for root, dirs, files in os.walk(self.wildcards_dir):
        for file in files:
            if file.endswith('.txt'):
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, self.wildcards_dir)
                wildcard_name = Path(relative_path).with_suffix('').as_posix()

                with open(file_path, 'r', encoding='utf-8') as f:
                    lines = [line.strip() for line in f if line.strip()]

                if lines:
                    self.wildcard_dict_tree[wildcard_name] = lines
```

**와일드카드 구조**:
```
wildcards/
  ├── characters/
  │   ├── outfit.txt  → 'characters/outfit'
  │   └── pose.txt    → 'characters/pose'
  └── effects/
      └── weather.txt → 'effects/weather'
```

### TagDataManager: 태그 데이터 관리

**파일**: `core/tag_data_manager.py:1-53`

#### 역할

- 태그 딕셔너리 로딩 (general, artist, copyright, character)
- 태그 검색 및 매칭

### ModeAwareModuleManager: 모드 인식 모듈 관리

**파일**: `core/mode_ware_manager.py:7-82`

#### 역할

- ModeAware 모듈 등록/해제
- 모드별 설정 일괄 저장/로드

#### 설정 저장

`core/mode_ware_manager.py:32-54`

```python
def save_all_current_mode(self):
    """현재 모드 설정 일괄 저장"""
    current_mode = self.app_context.get_api_mode()

    for module in self.registered_modules:
        if getattr(module, 'ignore_save_load', False):
            continue

        if module.is_compatible_with_mode(current_mode):
            module.save_mode_settings(current_mode)
```

---

## 실전 예제

### 예제 1: 새 공유 서비스 추가

**시나리오**: 애플리케이션 전역에서 사용할 `ImageCacheService`를 추가하고 싶습니다.

**단계**:

1. **서비스 클래스 작성** (`core/image_cache_service.py`)

```python
# core/image_cache_service.py
from typing import Dict
from PIL import Image

class ImageCacheService:
    def __init__(self):
        self._cache: Dict[str, Image.Image] = {}
        self._max_size = 100

    def add(self, key: str, image: Image.Image):
        """이미지 캐시에 추가"""
        if len(self._cache) >= self._max_size:
            # 가장 오래된 항목 제거
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
        self._cache[key] = image

    def get(self, key: str) -> Image.Image:
        """캐시에서 이미지 반환"""
        return self._cache.get(key)

    def clear(self):
        """캐시 클리어"""
        self._cache.clear()
```

2. **AppContext에 등록** (`core/context.py`)

```python
# core/context.py
from core.image_cache_service import ImageCacheService

class AppContext:
    def __init__(self, main_window, wildcard_manager, tag_data_manager):
        # ... 기존 코드 ...

        # 🆕 이미지 캐시 서비스 추가
        self.image_cache_service = ImageCacheService()
```

3. **다른 컴포넌트에서 사용**

```python
# 모듈 또는 탭에서
class MyModule(BaseMiddleModule):
    def initialize_with_context(self, app_context):
        self.app_context = app_context

        # 이미지 캐시 서비스 사용
        cached_image = app_context.image_cache_service.get("my_key")
        if cached_image:
            print("캐시 히트!")
        else:
            # 이미지 로드 후 캐시에 추가
            new_image = Image.open("path/to/image.png")
            app_context.image_cache_service.add("my_key", new_image)
```

### 예제 2: 커스텀 이벤트 생성 및 사용

**시나리오**: 모듈 A가 데이터를 처리하면, 모듈 B가 자동으로 업데이트되어야 합니다.

**모듈 A (발행자)**:

```python
class DataProcessorModule(BaseMiddleModule):
    def initialize_with_context(self, app_context):
        self.app_context = app_context

    def process_data(self, data):
        # 데이터 처리
        result = self._do_heavy_processing(data)

        # 이벤트 발행
        self.app_context.publish("data_processed", {
            "result": result,
            "timestamp": datetime.now()
        })
```

**모듈 B (구독자)**:

```python
class DataViewerModule(BaseMiddleModule):
    def initialize_with_context(self, app_context):
        self.app_context = app_context

        # 이벤트 구독
        app_context.subscribe("data_processed", self._on_data_processed)

    def _on_data_processed(self, data: dict):
        result = data["result"]
        timestamp = data["timestamp"]

        # UI 업데이트
        self.label.setText(f"최신 데이터: {result} (처리 시간: {timestamp})")
```

### 예제 3: 파이프라인 훅으로 프롬프트 수정

**시나리오**: 모든 프롬프트에 특정 품질 태그를 자동으로 추가하고 싶습니다.

```python
class QualityBoosterModule(BaseMiddleModule):
    def __init__(self):
        super().__init__()
        self.NAI_compatibility = True
        self.WEBUI_compatibility = True
        self.COMFYUI_compatibility = False

        self.enabled = True

    def get_title(self) -> str:
        return "🌟 Quality Booster"

    def create_widget(self, parent):
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)

        self.checkbox = QCheckBox("자동 품질 태그 추가")
        self.checkbox.setChecked(True)
        self.checkbox.stateChanged.connect(self._on_checkbox_changed)

        layout.addWidget(self.checkbox)

        self.widget = widget
        return widget

    def _on_checkbox_changed(self, state):
        self.enabled = (state == Qt.CheckState.Checked.value)

    def get_pipeline_hook_info(self) -> dict:
        return {
            'target_pipeline': 'PromptProcessor',
            'hook_point': 'post_processing',  # 와일드카드 확장 전에 실행
            'priority': 5  # 다른 모듈보다 먼저 실행
        }

    def execute_pipeline_hook(self, context):
        if not self.enabled:
            return context

        # 품질 태그 추가
        quality_tags = ["masterpiece", "best quality", "highly detailed"]

        # prefix_tags 앞에 추가
        context.prefix_tags = quality_tags + context.prefix_tags

        print(f"✅ Quality Booster: {len(quality_tags)}개 태그 추가")

        return context
```

---

## 개발 워크플로우

### 새 컨트롤러 추가

1. **계획**
   ```
   [ ] 컨트롤러가 관리할 영역 정의
   [ ] 필요한 시그널 정의
   [ ] AppContext와의 상호작용 설계
   ```

2. **파일 생성** (`core/my_controller.py`)
   ```python
   from PyQt6.QtCore import QObject, pyqtSignal
   from core.context import AppContext

   class MyController(QObject):
       data_loaded = pyqtSignal(dict)

       def __init__(self, app_context: AppContext):
           super().__init__()
           self.app_context = app_context
   ```

3. **AppContext 통합**
   - 필요 시 `AppContext`에 인스턴스 등록
   - 이벤트 구독/발행

4. **테스트**
   ```
   [ ] 독립 실행 테스트
   [ ] 다른 컴포넌트와 통합 테스트
   [ ] 메모리 누수 확인
   ```

### 파이프라인 단계 추가

⚠️ **주의**: 파이프라인 변경은 모든 모듈에 영향을 미칩니다!

1. **새 훅 포인트 정의** (`core/prompt_processor.py`)
   ```python
   def process(self):
       context = self.app_context.current_prompt_context

       context = self._run_hooks('pre_processing', context)
       context = self._step_2_fit_resolution(context)
       context = self._run_hooks('post_processing', context)

       # 🆕 새 훅 포인트 추가
       context = self._run_hooks('my_new_hook', context)

       context = self._step_3_expand_wildcards(context)
       # ...
   ```

2. **문서화**
   - 최상위 `CLAUDE.md` 업데이트
   - 훅 포인트 실행 순서 명시
   - 예제 추가

3. **기존 모듈 영향 확인**
   - 모든 파이프라인 훅 사용 모듈 검토
   - 충돌 가능성 확인

---

## 문제 해결

### Q1: 이벤트가 전달되지 않아요

**증상**:
```python
# 모듈 A에서
app_context.publish("my_event", {"data": "value"})

# 모듈 B에서 (아무 일도 일어나지 않음)
def _on_my_event(self, data):
    print("이벤트 수신!")  # 출력되지 않음
```

**원인**:
1. 구독이 안 됨
2. 이벤트 이름 오타
3. 콜백 함수 시그니처 불일치
4. `initialize_with_context()` 호출 전 구독 시도

**해결**:

1. **구독 확인**:
```python
def initialize_with_context(self, app_context):
    self.app_context = app_context

    # ✅ 올바른 위치
    app_context.subscribe("my_event", self._on_my_event)
```

2. **이벤트 이름 일치 확인**:
```python
# 발행
app_context.publish("my_event", ...)  # ✅

# 구독
app_context.subscribe("my_event", ...)  # ✅
app_context.subscribe("my_Event", ...)  # ❌ 대소문자 불일치
```

3. **콜백 시그니처 확인**:
```python
# 발행
app_context.publish("my_event", {"key": "value"})

# 구독 (올바름)
def _on_my_event(self, data: dict):  # ✅ 1개 인자
    print(data["key"])

# 구독 (잘못됨)
def _on_my_event(self):  # ❌ 인자 없음
    pass
```

4. **디버깅**:
```python
# 발행 시
print(f"[DEBUG] 이벤트 발행: my_event")
app_context.publish("my_event", {"data": "value"})

# 구독 시
def _on_my_event(self, data):
    print(f"[DEBUG] 이벤트 수신: {data}")
```

### Q2: 파이프라인 훅이 실행되지 않아요

**증상**:
```python
def execute_pipeline_hook(self, context):
    print("이 메시지가 출력되지 않음!")
    # ...
```

**원인**:
1. `get_pipeline_hook_info()` 미구현 또는 잘못된 반환
2. 컨텍스트 반환 누락
3. 모듈이 로드되지 않음
4. `initialize_with_context()` 호출 전

**해결**:

1. **훅 정보 확인**:
```python
def get_pipeline_hook_info(self) -> dict:
    return {
        'target_pipeline': 'PromptProcessor',  # ✅ 정확한 이름
        'hook_point': 'post_processing',  # ✅ 유효한 훅 포인트
        'priority': 10  # ✅ 숫자
    }
```

2. **컨텍스트 반환 필수**:
```python
def execute_pipeline_hook(self, context):
    # 작업 수행
    context.main_tags.append("my_tag")

    # ✅ 반드시 context 반환
    return context
```

3. **훅 등록 확인**:
```python
# MiddleSectionController에서 자동 등록됨
# 수동 확인:
hooks = app_context.get_pipeline_hooks('PromptProcessor', 'post_processing')
print(f"등록된 훅: {[h.get_title() for h in hooks]}")
```

### Q3: 모드 변경 시 모듈이 숨겨지지 않아요

**증상**:
- NAI 전용 모듈이 WEBUI 모드에서도 보임

**원인**:
1. 호환성 플래그 설정 안 됨
2. `widget` 참조 저장 안 됨

**해결**:

```python
class MyModule(BaseMiddleModule):
    def __init__(self):
        super().__init__()

        # ✅ 호환성 플래그 명시
        self.NAI_compatibility = True
        self.WEBUI_compatibility = False
        self.COMFYUI_compatibility = False

    def create_widget(self, parent):
        widget = QWidget(parent)
        # ... UI 구성 ...

        # ✅ 위젯 참조 저장 (필수)
        self.widget = widget
        return widget
```

### Q4: HTTP "Dummy" 스레드가 계속 쌓여요

**증상**:
- 이미지 생성 후 스레드 개수 증가
- 메모리 사용량 증가

**원인**:
- API 호출 후 스레드 정리 안 함

**해결**:

```python
def my_api_call(self):
    try:
        with requests.Session() as session:
            response = session.post(url, ...)
            session.close()

            # 어댑터 정리
            if hasattr(session, 'adapters'):
                for adapter in session.adapters.values():
                    if hasattr(adapter, 'poolmanager'):
                        adapter.poolmanager.clear()

        # ✅ 필수: HTTP 스레드 정리
        self._cleanup_http_threads()

    except Exception as e:
        print(f"API 호출 실패: {e}")
```

### Q5: AppContext에서 서비스를 찾을 수 없어요

**증상**:
```python
AttributeError: 'AppContext' object has no attribute 'my_service'
```

**원인**:
- 서비스가 `AppContext.__init__()`에 등록되지 않음

**해결**:

```python
# core/context.py
class AppContext:
    def __init__(self, main_window, wildcard_manager, tag_data_manager):
        # ... 기존 코드 ...

        # ✅ 서비스 등록
        self.my_service = MyService(self)
```

또는 동적 등록:

```python
# 어디서든
app_context.my_service = MyService(app_context)
```

---

## 체크리스트

### 새 컨트롤러 추가 시

```
[ ] AppContext 주입받음
[ ] 필요한 시그널 정의
[ ] 리소스 정리 메서드 구현 (cleanup 등)
[ ] 메모리 누수 확인 (QThread deleteLater)
[ ] 에러 처리 및 시그널 발행
[ ] 문서화 (CLAUDE.md 업데이트)
```

### API 호출 추가/수정 시

```
[ ] 재시도 로직 포함 (최소 3회)
[ ] 타임아웃 설정
[ ] 에러 메시지 명확히
[ ] HTTP 스레드 정리 (_cleanup_http_threads)
[ ] 결과 딕셔너리에 'status' 포함
[ ] API 키/토큰 하드코딩 금지 (SecureTokenManager 사용)
```

### 파이프라인 수정 시

```
[ ] 기존 훅 포인트 순서 유지
[ ] 새 훅 포인트는 명확한 위치에 삽입
[ ] 모든 훅에서 context 반환 확인
[ ] 부작용 최소화 (context만 수정)
[ ] 최상위 CLAUDE.md 업데이트
[ ] 예제 추가
```

### 이벤트 추가 시

```
[ ] 이벤트 이름 명확히 (snake_case)
[ ] 데이터 구조 문서화
[ ] 발행 위치 명확히
[ ] 예제 코드 작성
[ ] 최상위 CLAUDE.md의 이벤트 목록에 추가
```

---

## 참고 자료

### 관련 문서

- **[최상위 CLAUDE.md](../CLAUDE.md)**: 전체 프로젝트 개요 및 빠른 시작
- **[AGENTS.md](../AGENTS.md)**: AI 협업을 위한 상세 기술 레퍼런스
- **[modules/CLAUDE.md](../modules/CLAUDE.md)**: 모듈 개발 가이드
- **[tabs/CLAUDE.md](../tabs/CLAUDE.md)**: 탭 개발 가이드
- **[interfaces/CLAUDE.md](../interfaces/CLAUDE.md)**: 계약 정의

### 주요 의존성

**core/가 의존하는 디렉터리**:
- `interfaces/` - BaseMiddleModule, BaseTabModule, ModeAwareModule
- `ui/` - collapsible, detached_window, theme, scaling_manager
- `utils/` - token_calculator, image_info
- `data/` - KR_tags.parquet, 딕셔너리 파일들

**core/를 의존하는 디렉터리**:
- `modules/` - AppContext, 컨트롤러 접근
- `tabs/` - AppContext, 컨트롤러 접근
- `NAIA_cold_v4.py` - 메인 진입점

### 예제 코드 위치

| 예제 | 파일 | 라인 |
|------|------|------|
| **AppContext 초기화** | `NAIA_cold_v4.py` | 200-250 |
| **이벤트 구독** | `modules/character_module.py` | 50-70 |
| **파이프라인 훅** | `modules/conditional_prompt_module.py` | 100-150 |
| **QThread 워커** | `core/generation_controller.py` | 55-111 |
| **API 호출** | `core/api_service.py` | 69-155 |
| **ImageCrudController 사용** | `tabs/image_window.py` | 2272-2307 |
| **카운터 이벤트 구독** | `tabs/setting_tabs.py` | 129-136, 588-618 |

### 디버깅 팁

1. **이벤트 추적**:
```python
# AppContext에 로깅 추가
original_publish = app_context.publish
def debug_publish(event_name, *args, **kwargs):
    print(f"[EVENT] {event_name}: {args}, {kwargs}")
    return original_publish(event_name, *args, **kwargs)
app_context.publish = debug_publish
```

2. **훅 실행 추적**:
```python
# PromptProcessor에 로깅 추가
def execute_pipeline_hook(self, context):
    print(f"[HOOK] {self.get_title()} 실행 시작")
    # ... 로직 ...
    print(f"[HOOK] {self.get_title()} 실행 완료")
    return context
```

3. **메모리 누수 확인**:
```python
import threading
print(f"활성 스레드 수: {threading.active_count()}")
print(f"스레드 목록: {[t.name for t in threading.enumerate()]}")
```

---

## 요약

**core/의 핵심**:
- ✅ **AppContext**가 모든 것의 중심
- ✅ **컨트롤러**가 생명주기 관리
  - 🆕 **MiddleSectionController**: 모듈 상태 추적, 아코디언 동작, 자동 스크롤
- ✅ **이벤트 버스**로 느슨한 결합
- ✅ **파이프라인 훅**으로 확장성 제공
- ✅ **스레드 정리** 필수
- 🆕 **상태 영속성**: 모듈 펼침/접힘 상태, 스크롤 위치 자동 저장

**다음 단계**:
1. [modules/CLAUDE.md](../modules/CLAUDE.md)에서 모듈 개발 학습
2. [tabs/CLAUDE.md](../tabs/CLAUDE.md)에서 탭 개발 학습
3. 실제 코드 예제 분석

**막힐 때**:
- AppContext 사용법 → 이 문서의 [AppContext 섹션](#appcontext-중앙-상태-관리자)
- 파이프라인 훅 → 이 문서의 [프롬프트 파이프라인 섹션](#프롬프트-파이프라인)
- 문제 해결 → 이 문서의 [문제 해결 섹션](#문제-해결)

---

*문서 버전: 1.7*
*최종 업데이트: 2025-01-18*
*담당 영역: core/ 디렉터리*

**변경사항**: [상세 변경 로그](.claude/CHANGELOG_CLAUDE.md) 참조
