# CLAUDE.md — tabs/

> **목적**: NAIA 2.0의 우측 탭 모듈 개발 가이드. TabController를 통한 동적 로딩, RightView 통합, core/closable 타입, 통신 패턴을 다룹니다.

---

## 목차

1. [개요](#개요)
2. [주요 파일 및 역할](#주요-파일-및-역할)
3. [탭 개발 기초](#탭-개발-기초)
4. [탭 타입: core vs closable](#탭-타입-core-vs-closable)
5. [탭 통신 패턴](#탭-통신-패턴)
6. [실전 예제](#실전-예제)
7. [단계별 튜토리얼](#단계별-튜토리얼)
8. [고급 패턴](#고급-패턴)
9. [문제 해결](#문제-해결)
10. [체크리스트](#체크리스트)
11. [참고 자료](#참고-자료)
12. [요약](#요약)

---

## 개요

### tabs/ 디렉터리의 역할

tabs/는 NAIA 2.0의 **우측 패널 탭 모듈**을 담당합니다:

- 📝 **메타데이터 뷰어**: PNG Info 탭으로 이미지 정보 추출
- 🖼️ **생성 결과 표시**: Image Viewer 탭으로 생성 이미지 관리
- 📦 **브라우저 통합**: Danbooru 등 웹 리소스 탐색
- ⚙️ **설정 관리**: 애플리케이션 설정 UI
- 🎨 **에셋 도구**: 배경 제거 등 이미지 처리

### 아키텍처

```
RightView (ui/right_view.py)
    ↓ owns
EnhancedTabWidget (QTabWidget)
    ↓ managed by
TabController (core/tab_controller.py)
    ↓ loads
tabs/*.py (BaseTabModule subclasses)
```

**로딩 흐름**:
```
1. TabController._load_tab_modules()
   → glob "tabs/*.py"
   → BaseTabModule 서브클래스 발견

2. TabController.initialize_tabs()
   → get_tab_type() == 'core'인 것만 자동 로드
   → get_tab_order() 순서로 정렬
   → create_widget(parent) 호출
   → QTabWidget.addTab()

3. RightView 시그널 브리징
   → ImageViewer.instant_generation_requested
   → Browser.generate_with_image_requested
   → MainWindow로 전달
```

### 다른 디렉터리와의 관계

```
tabs/
  ├── interfaces/base_tab_module.py를 상속
  ├── core/tab_controller.py에 의해 관리
  ├── ui/right_view.py에 표시
  ├── ui/theme.py, ui/scaling_manager.py 스타일 사용
  └── core/context.py (AppContext) 주입받음
```

### 언제 tabs/를 수정하는가?

| 작업 | 수정 파일 |
|------|----------|
| **새 탭 추가** | `tabs/my_new_tab.py` (새 파일 생성) |
| **기존 탭 수정** | 해당 `tabs/*.py` 파일 |
| **탭 계약 변경** | `interfaces/base_tab_module.py` ⚠️ |
| **탭 로딩 로직 수정** | `core/tab_controller.py` ⚠️ |
| **탭 컨테이너 수정** | `ui/right_view.py` ⚠️ |

⚠️ = 전체 시스템 영향, 신중히 진행

---

## 주요 파일 및 역할

### 탭 모듈 파일 (tabs/)

| 파일 | 크기 | 역할 | 타입 | 주요 기능 |
|------|------|------|------|----------|
| **image_window.py** | 42K | 생성 이미지 표시 및 관리 | core | 이미지 뷰어, 히스토리, 일괄 저장, ImageCrudController 통합, 🆕 큐 추가 기능 (랜덤 옵션 지원) |
| **png_info_tab.py** | 47K | 이미지 메타데이터 추출 | core | PNG/JPEG/WebP 정보 파싱, Stealth PNG 지원 |
| **setting_tabs.py** | 28K | 애플리케이션 설정 | core | 자동완성, 저장 경로, 타임스탬프 폴더 토글, 이미지 카운터, 파일명 형식, 분류 규칙, 🆕 2차 분류 시스템, 모듈/탭 가시성 (시작 시 자동 적용), UI 스케일 |
| **assets_tab.py** | 35K | 배경 제거 등 도구 | closable | rembg 통합, 패키지 설치, 이미지 처리 |
| **web_view.py** | 19K | Danbooru 브라우저 | closable | 태그 추출, WebEngine, 세션 저장 |
| **img2img_tab.py** | 2.8K | Img2Img/Inpaint | closable | 스켈레톤 구현 (TODO) |
| **simple_web_view.py** | 소형 | 단순 웹뷰 | closable | 기본 브라우저 |
| **api_management_window.py** | 중형 | API 관리 | closable | 토큰/엔드포인트 설정 |
| **hooker_view.py** | 중형 | 훅 뷰어 | closable | 파이프라인 훅 디버깅 |
| **storyteller_tab.py** | 중형 | 스토리텔러 | closable | (기능 명세 미상) |
| **character_prompt_editor.py** | 중형 | 캐릭터 에디터 | closable | 캐릭터별 프롬프트 관리 |
| **artist_thumb_tab.py** | 중형 | 아티스트 썸네일 | closable | 아티스트 갤러리 |
| **depth_search_window.py** | 중형 | 심화 검색 | closable | 고급 태그 검색 |

### 관련 시스템 파일

| 파일 | 역할 |
|------|------|
| `interfaces/base_tab_module.py` | 탭 계약 정의 (ABC) |
| `core/tab_controller.py` | 탭 로딩 및 생명주기 관리 |
| `ui/right_view.py` | 탭 컨테이너 및 이벤트 브리지 |
| `ui/detached_window.py` | 탭 분리 창 관리 |

---

## 탭 개발 기초

### 최소 구현 (30초)

**파일**: `tabs/my_simple_tab.py`

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from interfaces.base_tab_module import BaseTabModule

class MySimpleTabModule(BaseTabModule):
    """'My Simple Tab' 탭 모듈"""

    def __init__(self):
        super().__init__()

    def get_tab_title(self) -> str:
        return "🌟 My Simple Tab"

    def create_widget(self, parent: QWidget) -> QWidget:
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel("Hello from My Simple Tab!"))
        return widget
```

**저장 후 재시작** → 탭이 자동으로 로드됩니다!

### BaseTabModule 계약

**파일**: `interfaces/base_tab_module.py:12-78`

#### 필수 메서드

```python
@abstractmethod
def get_tab_title(self) -> str:
    """탭 제목 (이모지 포함 가능)"""
    pass

@abstractmethod
def create_widget(self, parent: QWidget) -> QWidget:
    """탭 UI 위젯 생성"""
    pass
```

#### 선택 메서드

```python
def get_tab_order(self) -> int:
    """탭 순서 (낮을수록 왼쪽)"""
    return 999  # 기본값

def get_tab_type(self) -> str:
    """'core' | 'closable' | 'permanent'"""
    return 'core'  # 기본값

def can_close_tab(self) -> bool:
    """닫기 가능 여부"""
    return self.get_tab_type() in ['closable']
```

#### 생명주기 훅

```python
def on_initialize(self):
    """탭 초기화 완료 시 호출"""
    pass

def on_tab_activated(self):
    """탭이 활성화될 때 호출"""
    pass

def on_tab_deactivated(self):
    """탭이 비활성화될 때 호출"""
    pass

def on_tab_closing(self) -> bool:
    """탭 닫기 전 호출. False 반환 시 닫기 취소"""
    return True

def cleanup(self):
    """탭 제거 시 리소스 정리"""
    pass
```

### 공통 시그널

`interfaces/base_tab_module.py:15-18`

```python
class BaseTabModule(QObject, ABC):
    # 탭 간 통신용 공통 시그널
    parameters_extracted = pyqtSignal(dict)
    instant_generation_requested = pyqtSignal(dict)
    tab_status_changed = pyqtSignal(str, str)  # tab_id, status_message
```

**사용 예시**:
```python
# PNG Info 탭에서 파라미터 추출 완료 시
self.parameters_extracted.emit({
    'prompt': '1girl, ...',
    'negative_prompt': 'lowres, ...',
    'steps': 28,
    'seed': 123456
})

# Browser 탭에서 즉시 생성 요청
self.instant_generation_requested.emit({
    'character': ['character_name'],
    'general': ['tag1', 'tag2']
})
```

### AppContext 주입

`interfaces/base_tab_module.py:25-27`

```python
def initialize_with_context(self, app_context: 'AppContext'):
    """TabController가 자동 호출"""
    self.app_context = app_context
```

**탭 모듈에서 사용**:
```python
class MyTabModule(BaseTabModule):
    def on_initialize(self):
        # AppContext를 통해 공유 서비스 접근
        self.api_service = self.app_context.api_service
        self.wildcard_manager = self.app_context.wildcard_manager

        # 이벤트 구독
        self.app_context.subscribe("prompt_generated", self._on_prompt_generated)

    def _on_prompt_generated(self, context):
        print(f"프롬프트 생성됨: {context.final_prompt}")
```

---

## 탭 타입: core vs closable

### core 탭

**특징**:
- 애플리케이션 시작 시 자동 로드
- 닫기 버튼 없음
- 항상 표시됨

**예시**:
```python
class ImageViewerModule(BaseTabModule):
    def get_tab_title(self) -> str:
        return "🖼️ 생성 결과"

    def get_tab_order(self) -> int:
        return 1  # 가장 왼쪽

    def get_tab_type(self) -> str:
        return 'core'  # ✅ 시작 시 자동 로드

    def can_close_tab(self) -> bool:
        return False  # ✅ 닫기 버튼 없음
```

**기본 core 탭**:
- `🖼️ 생성 결과` (image_window.py) - order: 1
- `📦 Danbooru` (web_view.py) - order: 2
- `📝 PNG Info` (png_info_tab.py) - order: 3
- `⚙️ Settings` (setting_tabs.py) - order: 999

### closable 탭

**특징**:
- 사용자 요청 시에만 로드
- 닫기 버튼 있음
- MainWindow 메서드로 동적 추가

**예시**:
```python
class Img2ImgTabModule(BaseTabModule):
    def get_tab_title(self) -> str:
        return "🖼️ Img2Img"

    def get_tab_type(self) -> str:
        return 'closable'  # ✅ 동적 로드

    def can_close_tab(self) -> bool:
        return True  # ✅ 닫기 버튼 표시
```

**동적 추가 방법**:
```python
# MainWindow에서
def send_to_img2img(self, image_data: dict):
    """Img2Img 탭 열고 이미지 전달"""

    # 1. 탭 추가 (이미 열려있으면 전환만)
    self.image_window.tab_controller.add_tab_by_name('Img2ImgTabModule')

    # 2. 탭 인스턴스 가져오기
    img2img_tab = self.image_window.tab_controller.get_tab_instance('Img2ImgTabModule')

    # 3. 데이터 전달
    if img2img_tab and hasattr(img2img_tab.widget, 'load_image_data'):
        img2img_tab.widget.load_image_data(image_data)
```

### 탭 타입 비교

| 특성 | core | closable |
|------|------|----------|
| **로딩 시점** | 시작 시 자동 | 사용자 요청 시 |
| **닫기 버튼** | 없음 | 있음 |
| **사용 예** | 항상 필요한 기능 | 선택적 기능 |
| **메모리** | 항상 점유 | 필요 시만 점유 |
| **구현 난이도** | 간단 | 중간 (동적 로드 고려) |

---

## 탭 통신 패턴

### 패턴 1: 시그널을 통한 직접 통신

**시나리오**: PNG Info 탭에서 추출한 파라미터를 MainWindow로 전달

**PNG Info 탭**:
```python
class PngInfoTabModule(BaseTabModule):
    # ✅ BaseTabModule의 공통 시그널 사용
    # parameters_extracted = pyqtSignal(dict)

    def load_image_from_path(self, file_path):
        # 메타데이터 추출
        params = self.parse_generation_parameters(geninfo)

        # ✅ 시그널 발행
        self.parameters_extracted.emit(params)
```

**RightView 브리징**:
```python
# ui/right_view.py:85-96
png_info_module = self.tab_controller.get_tab_instance('PngInfoTabModule')
if png_info_module:
    # 탭 → RightView 연결
    png_info_module.parameters_extracted.connect(self._relay_parameters)

def _relay_parameters(self, params):
    # RightView → MainWindow 연결 (여기서는 단순 출력)
    print(f"파라미터 수신: {params}")
```

**MainWindow 최종 수신**:
```python
# NAIA_cold_v4.py 또는 main_window.py
self.image_window.png_info_tab_signal.connect(self.apply_parameters)

def apply_parameters(self, params):
    # UI에 파라미터 적용
    self.positive_prompt_edit.setPlainText(params.get('prompt', ''))
    self.negative_prompt_edit.setPlainText(params.get('negative_prompt', ''))
    # ...
```

### 패턴 2: AppContext 이벤트 버스

**시나리오**: 설정 변경을 모든 컴포넌트에 알림

**Settings 탭**:
```python
class SettingsTabModule(BaseTabModule):
    def _on_autocomplete_toggled(self, checked: bool):
        # 설정 저장
        self.settings_module.set_setting('autocomplete.enabled', checked)

        # ✅ AppContext 이벤트 발행
        if self.app_context:
            self.app_context.publish("autocomplete_toggled", {
                "enabled": checked
            })
```

**다른 컴포넌트에서 구독**:
```python
class SomeOtherTab(BaseTabModule):
    def initialize_with_context(self, app_context):
        self.app_context = app_context

        # ✅ 이벤트 구독
        app_context.subscribe("autocomplete_toggled", self._on_autocomplete_changed)

    def _on_autocomplete_changed(self, data: dict):
        enabled = data["enabled"]
        print(f"자동완성 {'활성화' if enabled else '비활성화'}")
        # UI 업데이트
```

**실제 예제: 이미지 카운터 업데이트** (`tabs/setting_tabs.py`):
```python
class SettingsWidget(QWidget):
    def __init__(self, app_context, settings_module):
        super().__init__()
        self.app_context = app_context

        # UI에 카운터 레이블 생성
        self.counter_value_label = QLabel("1")

        # ✅ 이벤트 구독
        if app_context:
            app_context.subscribe("image_counter_changed", self._on_counter_changed)

            # 초기값 표시
            initial_counter = app_context.image_crud_controller.get_counter()
            self.counter_value_label.setText(str(initial_counter))

    def _on_counter_changed(self, data: dict):
        """카운터 변경 이벤트 핸들러"""
        new_counter = data.get("new_counter", 1)
        self.counter_value_label.setText(str(new_counter))
        print(f"✅ Settings 탭: 카운터 업데이트 → {new_counter}")
```

### 패턴 3: MainWindow 직접 참조 (레거시)

⚠️ **권장하지 않음** - RightView 브리징 또는 AppContext 사용 권장

```python
class MyTab(BaseTabModule):
    def on_some_action(self):
        # ❌ 피해야 할 패턴
        if self.app_context and hasattr(self.app_context, 'main_window'):
            main_window = self.app_context.main_window
            main_window.some_method()

        # ✅ 대신 이렇게
        self.app_context.publish("some_event", {"data": "value"})
```

### 통신 패턴 비교

| 패턴 | 장점 | 단점 | 사용 시기 |
|------|------|------|----------|
| **시그널 직접 연결** | 타입 안전, 명확한 흐름 | 브리징 코드 필요 | 특정 탭 ↔ MainWindow |
| **AppContext 이벤트** | 느슨한 결합, 확장 용이 | 디버깅 어려움 | 전역 알림, 다대다 통신 |
| **MainWindow 직접** | 간단함 | 강한 결합, 테스트 어려움 | ❌ 사용 금지 |

---

## 실전 예제

**개요**: 간단한 탭부터 복잡한 기능까지 단계별 예제를 제공합니다.

### 예제 목록

1. **간단한 메모 탭 (15분)** - 텍스트 입력/저장 기능
2. **이미지 정보 표시 탭 (30분)** - 드래그&드롭 + 메타데이터 표시
3. **WebEngine 브라우저 탭 (45분)** - 웹 탐색 기능

### 주요 학습 포인트

- **예제 1**: 기본 UI 구성, 파일 저장/로드
- **예제 2**: Drag & Drop, QSplitter, PIL 통합
- **예제 3**: WebEngine 설정, 네비게이션 UI

📖 **상세 코드 및 설명**: [.claude/examples_CLAUDE.md](.claude/examples_CLAUDE.md)

---

## 단계별 튜토리얼

**개요**: 난이도별로 구성된 실습 튜토리얼입니다.

### 튜토리얼 목록

1. **최소 뷰어 탭 (30분)** - 기본 구조 → 이미지 로드 → 이벤트 구독
2. **대화형 도구 탭 (2시간)** - UI 레이아웃 → 분석 로직 → AppContext 통합
3. **복잡한 WebEngine 탭 (1일)** - WebEngine 설정 → JavaScript 통신 → HTML 파싱
4. **완전한 애플리케이션 탭 (1주)** - Settings 탭 수준의 복합 기능

### 주요 학습 목표

- **튜토리얼 1**: 기본 탭 생명주기, 이벤트 시스템
- **튜토리얼 2**: UI 통합, 데이터 처리, 시그널
- **튜토리얼 3**: WebEngine, JavaScript 브릿지
- **튜토리얼 4**: 설정 영속성, 가시성 관리, 복잡한 UI

📖 **상세 단계별 코드**: [.claude/tutorials_CLAUDE.md](.claude/tutorials_CLAUDE.md)

---

## 고급 패턴

**개요**: 실전 프로젝트에서 자주 사용되는 고급 패턴입니다.

### 패턴 목록

1. **QThread 비동기 작업** - UI 블로킹 없이 네트워크/파일 작업
2. **Drag & Drop 통합** - 파일/URL 드래그 앤 드롭 처리
3. **WebEngine JavaScript 통신** - 웹페이지와 데이터 교환
4. **설정 영속성** - JSON 기반 설정 저장/로드 시스템

### 주요 활용 사례

- **패턴 1**: 이미지 다운로드, API 호출 (PNG Info 탭 참조)
- **패턴 2**: 이미지/파일 드롭 영역 (PNG Info, Image Viewer 참조)
- **패턴 3**: Danbooru 태그 추출 (Web View 탭 참조)
- **패턴 4**: 앱 설정 관리 (Settings 탭 참조)

📖 **상세 구현 코드**: [.claude/advanced_patterns_CLAUDE.md](.claude/advanced_patterns_CLAUDE.md)

---

## 문제 해결

### Q1: 탭이 로드되지 않아요

**증상**:
```
탭 파일을 만들었는데 NAIA에서 보이지 않음
```

**원인**:
1. 파일 이름이 `*_module.py` 패턴이 아님
2. 클래스가 `BaseTabModule`을 상속하지 않음
3. `get_tab_type()`이 'closable'인데 수동으로 추가하지 않음
4. Python 문법 오류

**해결**:

1. **파일 이름 확인**:
```python
# ✅ 올바름
tabs/my_tab_module.py

# ❌ 잘못됨
tabs/my_tab.py
tabs/MyTab.py
```

2. **클래스 상속 확인**:
```python
from interfaces.base_tab_module import BaseTabModule

class MyTabModule(BaseTabModule):  # ✅
    pass

class MyTab(QWidget):  # ❌ BaseTabModule 상속 안 함
    pass
```

3. **타입 확인**:
```python
def get_tab_type(self) -> str:
    return 'core'  # ✅ 자동 로드

def get_tab_type(self) -> str:
    return 'closable'  # ⚠️ 수동 추가 필요
```

4. **문법 오류 확인**:
```bash
python -m py_compile tabs/my_tab_module.py
```

### Q2: 시그널이 연결되지 않아요

**증상**:
```python
# 탭에서
self.parameters_extracted.emit(params)

# MainWindow에서 (수신 안 됨)
def on_parameters_extracted(self, params):
    print("Never called!")
```

**원인**:
1. RightView 브리징 누락
2. 시그널 이름 불일치
3. 탭 인스턴스를 찾지 못함

**해결**:

1. **RightView 브리징 추가** (`ui/right_view.py`):
```python
def __init__(self, app_context, parent=None):
    # ... 기존 코드 ...

    # ✅ 탭 시그널 브리징 추가
    my_tab_module = self.tab_controller.get_tab_instance('MyTabModule')
    if my_tab_module:
        my_tab_module.my_signal.connect(self.relay_my_signal)

def relay_my_signal(self, data):
    """MainWindow로 전달"""
    # MainWindow에서 연결 필요
    pass
```

2. **MainWindow 연결**:
```python
# NAIA_cold_v4.py 또는 main_window.py
self.image_window.relay_my_signal.connect(self.on_my_signal)

def on_my_signal(self, data):
    print(f"시그널 수신: {data}")
```

3. **디버깅**:
```python
# 탭에서
def emit_signal(self):
    print("[DEBUG] 시그널 발행 전")
    self.my_signal.emit({"data": "value"})
    print("[DEBUG] 시그널 발행 완료")

# 수신자에서
def on_my_signal(self, data):
    print(f"[DEBUG] 시그널 수신: {data}")
```

### Q3: AppContext가 None이에요

**증상**:
```python
AttributeError: 'NoneType' object has no attribute 'api_service'
```

**원인**:
- `initialize_with_context()` 호출 전에 `app_context` 접근

**해결**:

```python
class MyTabModule(BaseTabModule):
    def __init__(self):
        super().__init__()
        # ❌ 여기서 app_context 접근 불가
        # self.api_service = self.app_context.api_service

    def initialize_with_context(self, app_context):
        self.app_context = app_context

        # ✅ 여기서 접근
        self.api_service = app_context.api_service

    def on_initialize(self):
        # ✅ 또는 여기서 접근
        if self.app_context:
            self.api_service = self.app_context.api_service
```

### Q4: WebEngine 페이지가 로드되지 않아요

**증상**:
```
QWebEngineView가 흰 화면만 표시
```

**원인**:
1. WebEngine 프로필 설정 누락
2. JavaScript 비활성화
3. 순서 문제 (프로필 → 페이지 → 뷰)

**해결**:

```python
# ✅ 올바른 순서
def setup_webengine(self):
    # 1. 프로필 생성
    self.profile = QWebEngineProfile("MyProfile")

    # 2. 페이지 생성 (프로필 연결)
    self.page = QWebEnginePage(self.profile)

    # 3. 설정 활성화
    settings = self.page.settings()
    settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)

    # 4. 뷰 생성 후 페이지 설정
    self.browser = QWebEngineView()
    self.browser.setPage(self.page)

    # 5. URL 로드 (약간 지연)
    QTimer.singleShot(100, lambda: self.browser.setUrl(QUrl("https://example.com")))
```

### Q5: 모듈/탭 가시성이 프로그램 시작 시 적용되지 않아요

**증상**:
```
Settings 탭에서 모듈을 False로 설정했는데, 재시작 후 계속 보임
```

**원인**:
1. `_apply_saved_module_visibility`가 호출되지 않음
2. 타이밍 문제 (컨트롤러가 아직 준비되지 않음)
3. `update_ui_from_settings`에서 가시성 적용 누락

**해결**:

**1. update_ui_from_settings에 가시성 적용 추가**:
```python
def update_ui_from_settings(self):
    """저장된 설정으로 UI 업데이트"""
    # ... 기존 설정 ...

    # ✅ 저장된 가시성 설정 적용 (프로그램 시작 시)
    QTimer.singleShot(200, self._apply_saved_module_visibility)
    QTimer.singleShot(250, self._apply_saved_tab_visibility)
```

**2. 재시도 메커니즘 구현**:
```python
def _apply_saved_module_visibility(self, retry_count=0):
    """저장된 모듈 가시성 설정을 실제 UI에 적용"""
    max_retries = 3
    print(f"🔍 [SETTINGS] _apply_saved_module_visibility 호출됨 (시도 {retry_count + 1}/{max_retries + 1})")

    # ✅ 컨트롤러 존재 확인
    if not hasattr(self.app_context, 'middle_section_controller'):
        print("⚠️ [SETTINGS] middle_section_controller가 없습니다.")
        if retry_count < max_retries:
            print(f"  → 500ms 후 재시도...")
            QTimer.singleShot(500, lambda: self._apply_saved_module_visibility(retry_count + 1))
        return

    controller = self.app_context.middle_section_controller

    # ✅ module_boxes 준비 확인
    if not controller.module_boxes:
        print("⚠️ [SETTINGS] module_boxes가 비어있습니다. 모듈이 아직 생성되지 않았을 수 있습니다.")
        if retry_count < max_retries:
            print(f"  → 500ms 후 재시도...")
            QTimer.singleShot(500, lambda: self._apply_saved_module_visibility(retry_count + 1))
        return

    # ✅ 가시성 적용
    applied_count = 0
    for module in controller.module_instances:
        module_id = module.__class__.__name__
        is_visible = self.settings_module.get_setting(f'module_visibility.{module_id}', True)

        module_title = module.get_title()
        print(f"  - 모듈 '{module_title}' ({module_id}): 설정 가시성={is_visible}")

        if not is_visible:
            if module_title in controller.module_boxes:
                box = controller.module_boxes[module_title]
                box.setVisible(False)
                print(f"    ✅ Module '{module_title}' hidden on startup")
                applied_count += 1

    print(f"✅ [SETTINGS] 모듈 가시성 적용 완료 ({applied_count}개 숨김)")
```

**3. 디버깅**:
```bash
# 콘솔에서 다음 메시지 확인
🔍 [SETTINGS] _apply_saved_module_visibility 호출됨 (시도 1/4)
📊 [SETTINGS] 모듈 인스턴스 수: 8
📊 [SETTINGS] 모듈 박스 수: 8
  - 모듈 '🎭 Character' (CharacterModule): 설정 가시성=False
    ✅ Module '🎭 Character' hidden on startup
✅ [SETTINGS] 모듈 가시성 적용 완료 (1개 숨김)
```

### Q6: 탭 분리 후 메모리 누수가 있어요

**증상**:
- 탭을 분리하고 닫아도 메모리가 해제되지 않음

**원인**:
- `cleanup()` 미구현
- 타이머/스레드 미정리
- 순환 참조

**해결**:

```python
class MyTabModule(BaseTabModule):
    def __init__(self):
        super().__init__()
        self.timer = None
        self.worker_thread = None

    def cleanup(self):
        """리소스 정리"""

        # ✅ 타이머 정지
        if self.timer and self.timer.isActive():
            self.timer.stop()
            self.timer.deleteLater()
            self.timer = None

        # ✅ 스레드 정리
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.quit()
            self.worker_thread.wait()
            self.worker_thread.deleteLater()
            self.worker_thread = None

        # ✅ 시그널 연결 해제
        if self.app_context:
            # 구독 해제 (만약 AppContext에 unsubscribe 메서드가 있다면)
            pass

        # ✅ 위젯 정리
        if self.widget:
            self.widget.deleteLater()
            self.widget = None

### Q7: 분류 방법 변경 시 프로그램이 강제 종료돼요 (Settings 탭)

**증상**:
```
저장 디렉토리 설정에서 분류 방법을 "프롬프트 인식"으로 변경했다가
"분류 없음"으로 되돌리면 프로그램이 강제 종료됨
```

**원인**:
- `_on_classification_method_changed()` 메서드에서 잘못된 속성명 참조 (`AttributeError`)
- Line 1015: `self.secondary_classification_method_label.setVisible(False)`
- 실제 속성명: `self.secondary_classification_label` (Line 416에서 정의됨)

**해결** (2025-01-21 수정 완료):

```python
# ❌ 수정 전 (tabs/setting_tabs.py:1015)
if not is_prompt_recognition:
    self.secondary_classification_method_label.setVisible(False)  # AttributeError!
    self.secondary_classification_method_combo.setVisible(False)
    # ...

# ✅ 수정 후
if not is_prompt_recognition:
    self.secondary_classification_label.setVisible(False)  # 올바른 속성명
    self.secondary_classification_method_combo.setVisible(False)
    # ...
```

**근본 원인**:
- 변수명 불일치 (타이포):
  - Line 416: `self.secondary_classification_label = secondary_classification_label` (정의)
  - Line 1015: `self.secondary_classification_method_label` (잘못된 참조)

**재현 방법**:
1. Settings 탭 → 저장 디렉토리 설정
2. 분류 방법을 "프롬프트 인식"으로 변경
3. 분류 방법을 "분류 없음"으로 되돌림
4. ❌ **프로그램 강제 종료** (수정 전)
5. ✅ **정상 동작** (수정 후)

**디버깅 팁**:
```python
# 속성명 확인
print(dir(self))  # 모든 속성 출력
print(hasattr(self, 'secondary_classification_label'))  # True
print(hasattr(self, 'secondary_classification_method_label'))  # False

# 예외 처리 추가 (임시 방편)
if hasattr(self, 'secondary_classification_label'):
    self.secondary_classification_label.setVisible(False)
```

**관련 파일**:
- [setting_tabs.py:1015](../tabs/setting_tabs.py#L1015) - 수정 완료
- [setting_tabs.py:416](../tabs/setting_tabs.py#L416) - 속성 정의 위치
- [setting_tabs.py:637](../tabs/setting_tabs.py#L637) - 올바른 사용 예시

        print(f"✅ {self.get_tab_title()} 정리 완료")
```

---

## 체크리스트

### 새 탭 추가 시

```
[ ] 파일 이름: tabs/*_module.py
[ ] BaseTabModule 상속
[ ] get_tab_title() 구현
[ ] create_widget() 구현
[ ] get_tab_type() 명시 (core/closable)
[ ] get_tab_order() 설정 (순서)
[ ] self.widget 참조 저장 (컨트롤러가 사용)
[ ] UI 스타일: DARK_STYLES, DARK_COLORS 사용
[ ] 폰트/크기: get_scaled_font_size() 사용
[ ] cleanup() 구현 (리소스 정리)
[ ] 문서화 (간단한 주석)
```

### 비동기 작업 추가 시

```
[ ] QObject 워커 클래스 생성
[ ] moveToThread() 호출
[ ] 시그널 정의 (started, progress, finished, error)
[ ] 시그널 연결 (워커 → 메인 탭)
[ ] started.connect(worker.run) 연결
[ ] finished.connect(thread.deleteLater) 연결
[ ] UI 차단 방지 확인
[ ] 에러 처리 및 시그널 발행
[ ] 스레드 정리 (quit, wait, deleteLater)
```

### WebEngine 탭 추가 시

```
[ ] QWebEngineProfile 설정
[ ] QWebEnginePage 생성
[ ] JavaScript 활성화
[ ] 쿠키/캐시 정책 설정
[ ] QWebEngineView 생성 및 페이지 설정
[ ] URL 로드 지연 (QTimer.singleShot)
[ ] JavaScript 실행 및 결과 수신 (runJavaScript)
[ ] HTML 파싱 또는 데이터 추출
[ ] 에러 필터링 (선택사항)
```

### 시그널 통신 추가 시

```
[ ] BaseTabModule 공통 시그널 사용 (있으면)
[ ] 커스텀 시그널 정의 (없으면)
[ ] RightView 브리징 코드 추가
[ ] MainWindow 연결 코드 추가
[ ] 시그널 데이터 구조 문서화
[ ] 디버깅 출력 추가 (개발 중)
[ ] 디버깅 출력 제거 (배포 전)
```

### 설정 영속성 추가 시

```
[ ] JSON 파일 경로 정의
[ ] load_settings() 구현
[ ] save_settings() 구현
[ ] _get_default_settings() 구현
[ ] get_setting(key_path, default) 구현
[ ] set_setting(key_path, value) 구현
[ ] on_initialize()에서 load_settings() 호출
[ ] 설정 변경 시 save_settings() 호출
[ ] 예외 처리 (파일 읽기/쓰기 실패)
```

---

## 참고 자료

### 관련 문서

- **[최상위 CLAUDE.md](../CLAUDE.md)**: 전체 프로젝트 개요
- **[core/CLAUDE.md](../core/CLAUDE.md)**: TabController, AppContext
- **[ui/CLAUDE.md](../ui/CLAUDE.md)**: RightView, EnhancedTabWidget, 테마, 스케일링
- **[interfaces/CLAUDE.md](../interfaces/CLAUDE.md)**: BaseTabModule 계약
- **[modules/CLAUDE.md](../modules/CLAUDE.md)**: 모듈 개발 (유사 패턴)

### 주요 의존성

**tabs/가 의존하는 디렉터리**:
- `interfaces/base_tab_module.py` - 탭 계약
- `core/tab_controller.py` - 탭 로딩 및 관리
- `core/context.py` - AppContext
- `ui/right_view.py` - 탭 컨테이너
- `ui/theme.py`, `ui/scaling_manager.py` - 스타일
- `ui/modern_menu.py` - TextEdit 컨텍스트 메뉴
- `utils/image_info.py` - 이미지 메타데이터

**tabs/를 의존하는 디렉터리**:
- `ui/right_view.py` - RightView가 TabController로 탭 로딩
- `NAIA_cold_v4.py` - MainWindow가 탭 시그널 구독

### 예제 코드 위치

| 예제 | 파일 | 라인 |
|------|------|------|
| **최소 탭 구현** | `tabs/img2img_tab.py` | 8-24 |
| **QThread 워커** | `tabs/png_info_tab.py` | 49-106 |
| **Drag & Drop** | `tabs/png_info_tab.py` | 1159-1284 |
| **WebEngine 설정** | `tabs/web_view.py` | 132-165 |
| **JavaScript 통신** | `tabs/web_view.py` | 219-241 |
| **HTML 파싱** | `tabs/web_view.py` | 276-318 |
| **설정 영속성** | `tabs/setting_tabs.py` | 54-117 |
| **이벤트 발행** | `tabs/setting_tabs.py` | 373-431 |
| **이벤트 구독 (카운터)** | `tabs/setting_tabs.py` | 129-136, 588-618 |
| **ImageCrudController 사용** | `tabs/image_window.py` | 2272-2307 |
| **🆕 큐 추가 기능** | `tabs/image_window.py` | 591-663 |

### 유용한 PyQt6 클래스

| 클래스 | 용도 | 예제 |
|--------|------|------|
| `QWebEngineView` | 웹 브라우저 | `tabs/web_view.py` |
| `QThread` | 비동기 작업 | `tabs/png_info_tab.py` |
| `QSplitter` | 크기 조절 가능한 패널 | `tabs/png_info_tab.py:226-242` |
| `QTabWidget` | 탭 컨테이너 | `ui/right_view.py:138-142` |
| `QTextEdit` | 멀티라인 텍스트 편집 | 대부분의 탭 |
| `QFileDialog` | 파일 선택 다이얼로그 | `tabs/setting_tabs.py:408-412` |
| `QMessageBox` | 메시지 박스 | 모든 탭 |
| `QTimer` | 지연 실행 | `tabs/setting_tabs.py:549-560` |

### 🆕 히스토리에서 큐에 추가 기능 (image_window.py)

**위치**: `tabs/image_window.py:591-663`

히스토리 이미지를 우클릭하여 생성 큐에 추가할 수 있는 기능입니다.

#### 주요 메서드

```python
def enqueue_to_front(self):
    """히스토리 아이템을 큐 앞에 추가 (우선순위 100)"""
    self._enqueue_history_item(priority=100)

def enqueue_to_back(self):
    """히스토리 아이템을 큐 뒤에 추가 (우선순위 0)"""
    self._enqueue_history_item(priority=0)

def _enqueue_history_item(self, priority: int = 0):
    """히스토리 아이템을 생성 큐에 추가"""
    # 1. generation_params 복사
    params = self.history_item.generation_params.copy()

    # 2. 랜덤 해상도 옵션 적용 (체크 시)
    if main_window.random_resolution_checkbox.isChecked():
        random_index = random.randint(0, main_window.resolution_combo.count() - 1)
        selected_value = main_window.resolution_combo.itemText(random_index)
        width, height = map(int, selected_value.split(' x '))
        params['width'] = width
        params['height'] = height

    # 3. 시드 고정 옵션 적용 (OFF 시 무작위 시드 생성)
    if not main_window.seed_fix_checkbox.isChecked():
        random_seed = random.randint(0, 9999999999)
        params['seed'] = random_seed
        params['extra_noise_seed'] = random_seed

    # 4. GenerationRequest 생성 및 큐에 추가
    request = GenerationRequest(params=params, source_row=source_row, priority=priority)
    queue_manager.enqueue_with_priority(request)

    # 5. 피드백 (상태바 + 콘솔)
    main_window.status_bar.showMessage(f"✅ 큐 뒤에 추가됨 (대기 중: {queue_size})")
```

#### 컨텍스트 메뉴 통합

**위치**: `tabs/image_window.py:510-525`

```python
# 큐 추가 메뉴
menu.addSeparator()

enqueue_front_action = QAction("⬆️ 큐 앞에 추가", self)
enqueue_front_action.triggered.connect(self.enqueue_to_front)
if not (hasattr(self.history_item, 'generation_params') and self.history_item.generation_params):
    enqueue_front_action.setEnabled(False)
menu.addAction(enqueue_front_action)

enqueue_back_action = QAction("⬇️ 큐 뒤에 추가", self)
enqueue_back_action.triggered.connect(self.enqueue_to_back)
if not (hasattr(self.history_item, 'generation_params') and self.history_item.generation_params):
    enqueue_back_action.setEnabled(False)
menu.addAction(enqueue_back_action)
```

#### 주요 특징

1. **UI 설정 반영**: 현재 "랜덤 해상도", "시드 고정" 체크박스 상태를 반영
2. **파라미터 덮어쓰기**: `generation_params`의 값을 직접 덮어써 충돌 방지
3. **양수 시드 생성**: NovelAI API는 음수 시드를 받지 않으므로 0~9999999999 범위로 생성
4. **자동 비활성화**: `generation_params`가 없는 이미지는 메뉴 항목 자동 비활성화
5. **버튼 텍스트 업데이트**: 큐 이벤트 발행으로 자동 업데이트 ("🎨 이미지 생성 요청 (1)")

#### 주의사항

**❌ 잘못된 방법**:
```python
# seed = -1은 NovelAI API에서 오류 발생!
params['seed'] = -1  # HTTP 400: Error decoding request body

# random_resolution 플래그 추가는 중복 처리 발생!
params['random_resolution'] = True  # generation_controller.py에서 다시 처리
```

**✅ 올바른 방법**:
```python
# 실제 무작위 시드 생성
random_seed = random.randint(0, 9999999999)
params['seed'] = random_seed
params['extra_noise_seed'] = random_seed

# 해상도 직접 덮어쓰기
width, height = get_random_resolution()
params['width'] = width
params['height'] = height
```

### 디버깅 팁

1. **탭 로딩 확인**:
```python
# core/tab_controller.py:83-104에 로그 추가
print(f"[DEBUG] 로드된 탭 클래스: {[c.__name__ for c in self.module_classes]}")
```

2. **시그널 추적**:
```python
# 탭에서
original_emit = self.my_signal.emit
def debug_emit(*args, **kwargs):
    print(f"[SIGNAL] {self.get_tab_title()} → my_signal: {args}, {kwargs}")
    return original_emit(*args, **kwargs)
self.my_signal.emit = debug_emit
```

3. **WebEngine 콘솔 출력 확인**:
```python
# JavaScript에서
console.log("Debug message");

# Python에서 (개발자 도구 열기 - 현재 NAIA에는 미구현)
# self.browser.page().setDevToolsPage(...)
```

---

## 요약

**tabs/의 핵심**:
- ✅ **BaseTabModule 계약** 준수
- ✅ **TabController**가 자동 로딩
- ✅ **core/closable** 타입 구분
- ✅ **RightView 브리징**으로 통신
- ✅ **AppContext** 주입받아 공유 서비스 사용
- ✅ **cleanup()** 필수

**다음 단계**:
1. 최소 탭 예제로 시작 (30초)
2. Drag & Drop 또는 QThread 추가 (30분)
3. 실제 기능 구현 (2-8시간)
4. 시그널 통신 및 AppContext 통합 (1-2시간)
5. 설정 영속성 추가 (선택사항)

**막힐 때**:
- 탭 로딩 문제 → [Q1](#q1-탭이-로드되지-않아요)
- 시그널 문제 → [Q2](#q2-시그널이-연결되지-않아요)
- AppContext 문제 → [Q3](#q3-appcontext가-none이에요)
- WebEngine 문제 → [Q4](#q4-webengine-페이지가-로드되지-않아요)
- 모듈/탭 가시성 문제 → [Q5](#q5-모듈탭-가시성이-프로그램-시작-시-적용되지-않아요)
- 메모리 누수 → [Q6](#q6-탭-분리-후-메모리-누수가-있어요)
- 분류 방법 변경 시 크래시 → [Q7](#q7-분류-방법-변경-시-프로그램이-강제-종료돼요-settings-탭)

---

*문서 버전: 1.5*
*최종 업데이트: 2025-01-21*
*담당 영역: tabs/ 디렉터리*
*변경사항:*
- *ImageCrudController 통합 (image_window.py, setting_tabs.py 업데이트)*
- *🆕 타임스탬프 폴더 토글 기능 추가 (setting_tabs.py:263-267, 556-562, 693-696)*
- *🆕 프롬프트 기반 분류 규칙 UI 추가 (setting_tabs.py:343-382)*
- *🆕 2차 분류 시스템 UI 구현 (setting_tabs.py:393-462)*
  - *2차 분류 활성화 체크박스 및 방법 선택*
  - *규칙 선택 콤보박스 (1차 규칙에서 자동 생성)*
  - *선택된 규칙별 2차 분류 규칙 입력 필드*
  - *ImageCrudController 동기화 로직*
- *카운터 재시작 시 1로 초기화 정책 적용*
- *🆕 모듈/탭 가시성 프로그램 시작 시 자동 적용 (setting_tabs.py:950-956, 1067-1160)*
  - *`update_ui_from_settings`에서 가시성 적용 함수 호출 추가*
  - *재시도 메커니즘 구현 (컨트롤러 준비 대기, 최대 3회 재시도)*
  - *디버깅 로그 추가 (상태 추적 및 문제 진단)*
  - *타이밍 문제 해결 (QTimer 지연 실행)*
- *문제 해결 섹션에 Q5 추가: 모듈/탭 가시성 프로그램 시작 시 미적용 문제*
- *🐛 **버그 수정** (2025-01-21): 분류 방법 변경 시 크래시 문제 해결 (setting_tabs.py:1015)*
  - *잘못된 속성명 참조로 인한 AttributeError 수정*
  - *`secondary_classification_method_label` → `secondary_classification_label`*
  - *문제 해결 섹션에 Q7 추가: 재현 방법, 근본 원인, 디버깅 팁 포함*
