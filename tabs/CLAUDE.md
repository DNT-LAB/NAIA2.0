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
| **setting_tabs.py** | 27K | 애플리케이션 설정 | core | 자동완성, 저장 경로, 타임스탬프 폴더 토글, 이미지 카운터, 파일명 형식, 분류 규칙, 🆕 2차 분류 시스템, 모듈/탭 가시성, UI 스케일 |
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

### 예제 1: 간단한 메모 탭 (15분)

**목표**: 텍스트 입력/저장 기능을 가진 메모 탭 생성

**파일**: `tabs/memo_tab.py`

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout
from PyQt6.QtCore import pyqtSignal
from interfaces.base_tab_module import BaseTabModule
from ui.theme import DARK_STYLES, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size
import json
from pathlib import Path

class MemoTabModule(BaseTabModule):
    """간단한 메모 탭"""

    def __init__(self):
        super().__init__()
        self.memo_file = Path("save/memo.txt")

    def get_tab_title(self) -> str:
        return "📝 Memo"

    def get_tab_order(self) -> int:
        return 100  # Settings 앞

    def get_tab_type(self) -> str:
        return 'core'  # 항상 로드

    def create_widget(self, parent: QWidget) -> QWidget:
        widget = QWidget(parent)
        widget.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")

        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 텍스트 에디터
        self.text_edit = QTextEdit()
        self.text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 8px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: {get_scaled_font_size(16)}px;
            }}
        """)
        layout.addWidget(self.text_edit)

        # 버튼 레이아웃
        button_layout = QHBoxLayout()

        self.save_btn = QPushButton("💾 Save")
        self.save_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.save_btn.clicked.connect(self._save_memo)

        self.clear_btn = QPushButton("🗑️ Clear")
        self.clear_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.clear_btn.clicked.connect(self._clear_memo)

        button_layout.addStretch()
        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(self.clear_btn)

        layout.addLayout(button_layout)

        self.widget = widget
        return widget

    def on_initialize(self):
        """탭 초기화 시 메모 로드"""
        self._load_memo()

    def _save_memo(self):
        """메모 저장"""
        text = self.text_edit.toPlainText()
        self.memo_file.parent.mkdir(exist_ok=True)
        self.memo_file.write_text(text, encoding='utf-8')
        print(f"✅ 메모 저장 완료: {self.memo_file}")

    def _load_memo(self):
        """메모 로드"""
        if self.memo_file.exists():
            text = self.memo_file.read_text(encoding='utf-8')
            self.text_edit.setPlainText(text)
            print(f"✅ 메모 로드 완료: {self.memo_file}")

    def _clear_memo(self):
        """메모 지우기"""
        self.text_edit.clear()
```

**테스트**:
1. `tabs/memo_tab.py` 저장
2. NAIA 재시작
3. 📝 Memo 탭 확인
4. 텍스트 입력 후 💾 Save 클릭
5. 재시작 후 메모 유지 확인

### 예제 2: 이미지 정보 표시 탭 (30분)

**목표**: 드래그&드롭으로 이미지 정보를 표시하는 탭

**파일**: `tabs/image_info_tab.py`

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTextEdit, QSplitter
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QDragEnterEvent, QDropEvent
from interfaces.base_tab_module import BaseTabModule
from ui.theme import DARK_STYLES, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size
from PIL import Image
from PIL.ImageQt import ImageQt
import os

class ImageInfoTabModule(BaseTabModule):
    """이미지 정보 표시 탭"""

    def __init__(self):
        super().__init__()

    def get_tab_title(self) -> str:
        return "ℹ️ Image Info"

    def get_tab_type(self) -> str:
        return 'closable'  # 선택적 탭

    def create_widget(self, parent: QWidget) -> QWidget:
        widget = ImageInfoWidget(parent)
        self.widget = widget
        return widget


class ImageInfoWidget(QWidget):
    """이미지 드롭 및 정보 표시 위젯"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")
        self.init_ui()
        self.setAcceptDrops(True)

    def init_ui(self):
        """UI 초기화"""
        layout = QHBoxLayout(self)

        # 좌측: 이미지 표시
        self.image_label = QLabel("📷\n\n이미지를 드래그하세요")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(300, 300)
        self.image_label.setStyleSheet(f"""
            QLabel {{
                border: 2px dashed {DARK_COLORS['border_light']};
                border-radius: 8px;
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(18)}px;
            }}
        """)

        # 우측: 정보 표시
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 8px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)

        # 스플리터
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.image_label)
        splitter.addWidget(self.info_text)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)

    def dragEnterEvent(self, event: QDragEnterEvent):
        """드래그 진입"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        """드롭 이벤트"""
        urls = event.mimeData().urls()
        if not urls:
            return

        file_path = urls[0].toLocalFile()
        if not os.path.exists(file_path):
            return

        self.load_image(file_path)

    def load_image(self, file_path: str):
        """이미지 로드 및 정보 표시"""
        try:
            # PIL로 이미지 열기
            pil_image = Image.open(file_path)

            # 이미지 표시
            qimage = ImageQt(pil_image)
            pixmap = QPixmap.fromImage(qimage)
            scaled_pixmap = pixmap.scaled(
                self.image_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.image_label.setPixmap(scaled_pixmap)

            # 정보 추출
            info_text = f"📂 파일: {os.path.basename(file_path)}\n"
            info_text += f"📐 크기: {pil_image.width} x {pil_image.height}\n"
            info_text += f"🎨 모드: {pil_image.mode}\n"
            info_text += f"📦 포맷: {pil_image.format}\n"
            info_text += f"💾 파일 크기: {os.path.getsize(file_path):,} bytes\n"
            info_text += "\n🔍 메타데이터:\n"

            if pil_image.info:
                for key, value in pil_image.info.items():
                    value_str = str(value)
                    if len(value_str) > 100:
                        value_str = value_str[:100] + "..."
                    info_text += f"  {key}: {value_str}\n"
            else:
                info_text += "  (없음)\n"

            self.info_text.setPlainText(info_text)

        except Exception as e:
            self.info_text.setPlainText(f"❌ 오류: {str(e)}")
```

**테스트**:
1. `tabs/image_info_tab.py` 저장
2. NAIA 재시작
3. MainWindow에서 탭 추가 기능으로 "ℹ️ Image Info" 추가 (또는 core로 변경하여 자동 로드)
4. 이미지 파일 드래그&드롭
5. 정보 확인

### 예제 3: WebEngine 브라우저 탭 (45분)

**목표**: 간단한 웹 브라우저 탭 (웹페이지 로드 및 탐색)

**파일**: `tabs/simple_browser_tab.py`

```python
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit
)
from interfaces.base_tab_module import BaseTabModule
from ui.theme import DARK_STYLES, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size

class SimpleBrowserTabModule(BaseTabModule):
    """간단한 웹 브라우저 탭"""

    def __init__(self):
        super().__init__()

    def get_tab_title(self) -> str:
        return "🌐 Browser"

    def get_tab_type(self) -> str:
        return 'closable'

    def create_widget(self, parent: QWidget) -> QWidget:
        widget = SimpleBrowserWidget(parent)
        self.widget = widget
        return widget


class SimpleBrowserWidget(QWidget):
    """웹 브라우저 위젯"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        """UI 초기화"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 주소 표시줄
        address_layout = QHBoxLayout()

        self.back_btn = QPushButton("←")
        self.back_btn.setFixedWidth(40)
        self.back_btn.setStyleSheet(DARK_STYLES['secondary_button'])

        self.forward_btn = QPushButton("→")
        self.forward_btn.setFixedWidth(40)
        self.forward_btn.setStyleSheet(DARK_STYLES['secondary_button'])

        self.refresh_btn = QPushButton("⟳")
        self.refresh_btn.setFixedWidth(40)
        self.refresh_btn.setStyleSheet(DARK_STYLES['secondary_button'])

        self.address_bar = QLineEdit()
        self.address_bar.setPlaceholderText("URL 입력...")
        self.address_bar.setStyleSheet(f"""
            QLineEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 6px 12px;
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)

        self.go_btn = QPushButton("이동")
        self.go_btn.setStyleSheet(DARK_STYLES['primary_button'])

        address_layout.addWidget(self.back_btn)
        address_layout.addWidget(self.forward_btn)
        address_layout.addWidget(self.refresh_btn)
        address_layout.addWidget(self.address_bar)
        address_layout.addWidget(self.go_btn)

        layout.addLayout(address_layout)

        # 웹뷰
        self.browser = QWebEngineView()
        layout.addWidget(self.browser)

        # 시그널 연결
        self.back_btn.clicked.connect(self.browser.back)
        self.forward_btn.clicked.connect(self.browser.forward)
        self.refresh_btn.clicked.connect(self.browser.reload)
        self.go_btn.clicked.connect(self.navigate)
        self.address_bar.returnPressed.connect(self.navigate)
        self.browser.urlChanged.connect(self.update_address_bar)

        # 홈페이지 로드
        self.browser.setUrl(QUrl("https://www.google.com"))

    def navigate(self):
        """주소창 URL로 이동"""
        url = self.address_bar.text().strip()
        if not url:
            return

        # URL 형식 보정
        if not url.startswith(('http://', 'https://')):
            if '.' in url and ' ' not in url:
                url = 'https://' + url
            else:
                url = f'https://www.google.com/search?q={url}'

        self.browser.setUrl(QUrl(url))

    def update_address_bar(self, qurl: QUrl):
        """주소창 업데이트"""
        self.address_bar.setText(qurl.toString())
```

**테스트**:
1. `tabs/simple_browser_tab.py` 저장
2. NAIA 재시작
3. 🌐 Browser 탭 열기
4. URL 입력 및 탐색

---

## 단계별 튜토리얼

### 튜토리얼 1: 최소 뷰어 탭 (30분)

**목표**: 생성된 이미지를 표시하는 최소 탭

**1단계: 기본 구조 작성** (5분)

```python
# tabs/mini_viewer_tab.py
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt
from interfaces.base_tab_module import BaseTabModule
from ui.theme import DARK_COLORS

class MiniViewerTabModule(BaseTabModule):
    def __init__(self):
        super().__init__()

    def get_tab_title(self) -> str:
        return "🖼️ Mini Viewer"

    def get_tab_type(self) -> str:
        return 'core'

    def create_widget(self, parent: QWidget) -> QWidget:
        widget = QWidget(parent)
        widget.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")

        layout = QVBoxLayout(widget)
        self.image_label = QLabel("No Image")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.image_label)

        self.widget = widget
        return widget
```

**2단계: 이미지 로드 기능 추가** (10분)

```python
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt

# create_widget 내부에 추가
def load_image(self, file_path: str):
    """이미지 로드 및 표시"""
    pixmap = QPixmap(file_path)
    if not pixmap.isNull():
        scaled_pixmap = pixmap.scaled(
            self.image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.image_label.setPixmap(scaled_pixmap)
```

**3단계: 이벤트 구독으로 자동 업데이트** (15분)

```python
def initialize_with_context(self, app_context):
    self.app_context = app_context

    # 이미지 생성 완료 이벤트 구독
    app_context.subscribe("image_generated", self._on_image_generated)

def _on_image_generated(self, data: dict):
    """이미지 생성 완료 시 자동 표시"""
    if 'file_path' in data:
        self.load_image(data['file_path'])
```

### 튜토리얼 2: 대화형 도구 탭 (2시간)

**목표**: 프롬프트 분석 및 제안 탭

**1단계: UI 레이아웃** (30분)

```python
# tabs/prompt_analyzer_tab.py
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit,
    QPushButton, QLabel, QSplitter
)
from PyQt6.QtCore import Qt
from interfaces.base_tab_module import BaseTabModule
from ui.theme import DARK_STYLES, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size

class PromptAnalyzerTabModule(BaseTabModule):
    def get_tab_title(self) -> str:
        return "🔍 Prompt Analyzer"

    def create_widget(self, parent: QWidget) -> QWidget:
        widget = QWidget(parent)
        widget.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")

        layout = QVBoxLayout(widget)

        # 입력 영역
        self.input_label = QLabel("프롬프트 입력:")
        self.input_label.setStyleSheet(DARK_STYLES['label_style'])

        self.input_text = QTextEdit()
        self.input_text.setMaximumHeight(150)
        self.input_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 8px;
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)

        # 분석 버튼
        self.analyze_btn = QPushButton("🔍 Analyze")
        self.analyze_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.analyze_btn.clicked.connect(self._analyze_prompt)

        # 결과 영역
        self.result_label = QLabel("분석 결과:")
        self.result_label.setStyleSheet(DARK_STYLES['label_style'])

        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 8px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)

        layout.addWidget(self.input_label)
        layout.addWidget(self.input_text)
        layout.addWidget(self.analyze_btn)
        layout.addWidget(self.result_label)
        layout.addWidget(self.result_text)

        self.widget = widget
        return widget
```

**2단계: 분석 로직 구현** (45분)

```python
import re
from collections import Counter

def _analyze_prompt(self):
    """프롬프트 분석"""
    prompt = self.input_text.toPlainText().strip()
    if not prompt:
        self.result_text.setPlainText("프롬프트를 입력하세요.")
        return

    # 태그 분리
    tags = [tag.strip() for tag in prompt.split(',') if tag.strip()]

    # 분석
    total_tags = len(tags)
    unique_tags = len(set(tags))
    duplicates = total_tags - unique_tags

    # 카테고리 추측 (간단한 휴리스틱)
    character_tags = [t for t in tags if any(keyword in t.lower()
                                              for keyword in ['girl', 'boy', '1girl', '2girls'])]
    quality_tags = [t for t in tags if any(keyword in t.lower()
                                            for keyword in ['masterpiece', 'best', 'quality'])]

    # 결과 포맷팅
    result = f"""📊 프롬프트 분석 결과
{'=' * 50}

📝 총 태그 수: {total_tags}
🔸 고유 태그 수: {unique_tags}
🔁 중복 태그 수: {duplicates}

👤 캐릭터 태그: {len(character_tags)}
  {', '.join(character_tags[:5])}{'...' if len(character_tags) > 5 else ''}

⭐ 품질 태그: {len(quality_tags)}
  {', '.join(quality_tags)}

📋 전체 태그 목록:
"""

    for i, tag in enumerate(tags, 1):
        result += f"  {i}. {tag}\n"

    self.result_text.setPlainText(result)
```

**3단계: AppContext 통합** (30min)

```python
def initialize_with_context(self, app_context):
    self.app_context = app_context

    # 프롬프트 생성 이벤트 구독
    app_context.subscribe("prompt_generated", self._on_prompt_generated)

    # 태그 데이터 매니저 사용
    self.tag_data_manager = app_context.tag_data_manager

def _on_prompt_generated(self, context):
    """프롬프트 생성 시 자동 분석"""
    final_prompt = context.final_prompt
    self.input_text.setPlainText(final_prompt)
    self._analyze_prompt()
```

**4단계: 고급 기능 추가** (15분)

```python
# 태그 제안 기능
def _suggest_tags(self, current_tags: list) -> list:
    """태그 제안"""
    suggestions = []

    # 캐릭터 태그가 없으면 제안
    if not any('girl' in t or 'boy' in t for t in current_tags):
        suggestions.append("캐릭터 태그 추가 권장 (예: 1girl)")

    # 품질 태그가 없으면 제안
    quality_keywords = ['masterpiece', 'best quality', 'highly detailed']
    if not any(keyword in ' '.join(current_tags) for keyword in quality_keywords):
        suggestions.append("품질 태그 추가 권장")

    return suggestions
```

### 튜토리얼 3: 복잡한 WebEngine 탭 (1일)

**시간 분배**:
- 1-2시간: 기본 WebEngine 설정
- 2-3시간: JavaScript 통신 구현
- 2-3시간: 데이터 추출 및 파싱
- 2-3시간: UI 통합 및 테스트

**참고 파일**: `tabs/web_view.py`

**주요 구현 포인트**:

1. **WebEngine 프로필 설정** (`web_view.py:132-165`)
2. **JavaScript 실행 및 결과 수신** (`web_view.py:219-241`)
3. **HTML 파싱** (`web_view.py:276-318`)
4. **시그널 발행** (`web_view.py:368-382`)

### 튜토리얼 4: 완전한 애플리케이션 탭 (1주)

**목표**: 설정 관리, 파일 저장/로드, 이벤트 통합을 모두 갖춘 탭

**참고 파일**: `tabs/setting_tabs.py`

**주요 기능**:
1. **JSON 설정 저장/로드** (`setting_tabs.py:54-117`)
2. **저장 디렉토리 관리** (`setting_tabs.py:241-267`)
   - 기본 저장 경로 설정
   - 🆕 타임스탬프 폴더 사용 여부 체크박스 (`line 263-267`)
3. **파일명 형식 선택** (`setting_tabs.py:289-310`)
   - number_only, time_number, datetime
4. **분류 시스템 설정** (`setting_tabs.py:312-462`)
   - 분류 방법 선택 (none, prompt_recognition)
   - 🆕 프롬프트 인식 분류 규칙 입력 (`line 343-382`)
   - 🆕 2차 분류 시스템 (`line 393-462`)
     - 2차 분류 활성화 체크박스
     - 2차 분류 방법 선택 (none, prompt_recognition)
     - 규칙 선택 콤보박스 (1차 규칙에서 자동 생성)
     - 선택된 규칙별 2차 분류 규칙 입력
5. **이미지 저장 카운터 표시 및 초기화** (`setting_tabs.py:269-287`)
   - 실시간 카운터 표시 (이벤트 구독)
   - 카운터 수동 초기화 버튼
6. **모듈/탭 가시성 관리** (`setting_tabs.py:414-530`)
7. **AppContext 이벤트 발행/구독** (`setting_tabs.py:129-136, 588-618`)
8. **QTimer 지연 초기화** (`setting_tabs.py:549-560`)

---

## 고급 패턴

### 패턴 1: QThread 비동기 작업

**시나리오**: 이미지 다운로드를 UI 스레드를 차단하지 않고 수행

**PNG Info 탭 예시** (`png_info_tab.py:49-106`)

```python
class ImageDownloader(QObject):
    """비동기 이미지 다운로드 워커"""

    download_finished = pyqtSignal(str)  # temp_path
    download_error = pyqtSignal(str)
    download_progress = pyqtSignal(int)  # 0-100

    def run(self, url: str):
        """백그라운드 스레드에서 실행"""
        try:
            # 1. 다운로드
            response = urllib.request.urlopen(url)
            content_type = response.headers.get('Content-Type', '')

            # 2. 진행률 업데이트
            self.download_progress.emit(50)

            # 3. 임시 파일 저장
            temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            temp_file.write(response.read())
            temp_file.close()

            self.download_progress.emit(100)
            self.download_finished.emit(temp_file.name)

        except Exception as e:
            self.download_error.emit(f"다운로드 오류: {str(e)}")
```

**메인 탭에서 사용**:
```python
def download_and_load_image(self, url: str):
    """비동기 다운로드 시작"""

    # 1. UI 상태 변경
    self.progress_bar.setVisible(True)
    self.set_buttons_enabled(False)

    # 2. 워커 및 스레드 생성
    self.download_thread = QThread()
    self.downloader = ImageDownloader()
    self.downloader.moveToThread(self.download_thread)

    # 3. 시그널 연결
    self.downloader.download_finished.connect(self.on_download_finished)
    self.downloader.download_error.connect(self.on_download_error)
    self.downloader.download_progress.connect(self.on_download_progress)

    # 4. 스레드 시작
    self.download_thread.started.connect(lambda: self.downloader.run(url))
    self.download_thread.finished.connect(self.download_thread.deleteLater)
    self.download_thread.start()

def on_download_finished(self, temp_path: str):
    """다운로드 완료"""
    self.progress_bar.setVisible(False)
    self.load_image_from_path(temp_path)
    self.set_buttons_enabled(True)

    # 스레드 정리
    if self.download_thread:
        self.download_thread.quit()
        self.download_thread.wait()

def on_download_error(self, error_msg: str):
    """다운로드 실패"""
    self.progress_bar.setVisible(False)
    QMessageBox.critical(self, "오류", error_msg)
    self.set_buttons_enabled(True)

    if self.download_thread:
        self.download_thread.quit()
```

### 패턴 2: Drag & Drop 통합

**ImageDropArea 패턴** (`png_info_tab.py:1159-1284`)

```python
class ImageDropArea(QLabel):
    """이미지 드래그&드롭 영역"""

    file_dropped = pyqtSignal(str)  # 로컬 파일 경로
    web_url_dropped = pyqtSignal(str)  # 웹 URL

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setText("📷\n\n이미지를 드래그하세요")

    def dragEnterEvent(self, event: QDragEnterEvent):
        """드래그 진입 시 비주얼 피드백"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(f"""
                QLabel {{
                    border: 2px dashed {DARK_COLORS['success']};
                    color: {DARK_COLORS['success']};
                }}
            """)

    def dragLeaveEvent(self, event):
        """드래그 이탈 시 원래 스타일 복원"""
        self.setStyleSheet(f"""
            QLabel {{
                border: 2px dashed {DARK_COLORS['border_light']};
                color: {DARK_COLORS['text_secondary']};
            }}
        """)

    def dropEvent(self, event: QDropEvent):
        """드롭 이벤트 처리"""
        try:
            if event.mimeData().hasUrls():
                url = event.mimeData().urls()[0]

                # 로컬 파일
                if url.isLocalFile():
                    file_path = url.toLocalFile()
                    self.file_dropped.emit(file_path)

                # 웹 URL
                else:
                    url_str = url.toString()
                    self.web_url_dropped.emit(url_str)

        finally:
            self.dragLeaveEvent(event)

    def set_image(self, pixmap: QPixmap):
        """이미지 표시"""
        scaled = pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.setPixmap(scaled)
```

**사용 예시**:
```python
def create_image_panel(self):
    """드롭 영역이 있는 패널"""
    panel = QFrame()
    layout = QVBoxLayout(panel)

    # 드롭 영역
    self.drop_area = ImageDropArea(self)
    self.drop_area.file_dropped.connect(self.load_image_from_path)
    self.drop_area.web_url_dropped.connect(self.download_and_load_image)

    layout.addWidget(self.drop_area)
    return panel
```

### 패턴 3: WebEngine JavaScript 통신

**JavaScript 실행 및 결과 수신** (`web_view.py:219-241`)

```python
def extract_danbooru_tags(self):
    """현재 페이지에서 JavaScript로 데이터 추출"""

    js_code = """
    (function() {
        const result = {
            url: window.location.href,
            html: document.documentElement.outerHTML
        };
        return result;
    })();
    """

    # JavaScript 실행 및 결과를 콜백으로 수신
    self.page.runJavaScript(js_code, self.process_page_data)

def process_page_data(self, page_data):
    """JavaScript 결과 처리"""
    if not page_data:
        return

    url = page_data['url']
    html = page_data['html']

    # HTML 파싱
    tags_data = self.parse_danbooru_tags(html, post_id)

    # 결과 표시
    self.display_extracted_tags(tags_data)
```

**HTML 파싱** (`web_view.py:276-318`)

```python
import re

def parse_danbooru_tags(self, html: str, post_id: int) -> dict:
    """정규식으로 HTML 파싱"""

    tags_data = {
        'id': post_id,
        'artist': [],
        'copyright': [],
        'character': [],
        'general': [],
        'meta': []
    }

    categories = {
        'artist': r'<ul class="artist-tag-list">(.*?)</ul>',
        'copyright': r'<ul class="copyright-tag-list">(.*?)</ul>',
        'character': r'<ul class="character-tag-list">(.*?)</ul>',
        'general': r'<ul class="general-tag-list">(.*?)</ul>',
        'meta': r'<ul class="meta-tag-list">(.*?)</ul>'
    }

    for category, pattern in categories.items():
        ul_match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if ul_match:
            ul_content = ul_match.group(1)

            # data-tag-name 속성 추출
            tag_pattern = r'data-tag-name="([^"]*)"'
            tag_matches = re.findall(tag_pattern, ul_content)

            for tag in tag_matches:
                # HTML 엔티티 디코딩
                tag = tag.replace('&amp;', '&')
                tag = tag.replace('&lt;', '<')
                tag = tag.replace('&gt;', '>')

                if tag and tag not in tags_data[category]:
                    tags_data[category].append(tag)

    return tags_data
```

### 패턴 4: 설정 영속성 (JSON 저장/로드)

**Settings 탭 패턴** (`setting_tabs.py:54-117`)

```python
class SettingsTabModule(BaseTabModule):
    def __init__(self):
        super().__init__()
        self.settings_data = {}
        self.settings_file = "app_settings.json"

    def load_settings(self):
        """설정 파일 로드"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    self.settings_data = json.load(f)
            else:
                self.settings_data = self._get_default_settings()
        except Exception as e:
            print(f"Settings load failed: {e}")
            self.settings_data = self._get_default_settings()

    def save_settings(self):
        """설정 파일 저장"""
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings_data, f, indent=2, ensure_ascii=False)
            print("Settings saved successfully.")
        except Exception as e:
            print(f"Settings save failed: {e}")

    def _get_default_settings(self) -> dict:
        """기본 설정값"""
        return {
            "autocomplete": {"enabled": True},
            "save_directory": {"base_path": "./output"},
            "module_visibility": {},
            "tab_visibility": {},
            "ui": {"theme": "dark", "auto_save": True}
        }

    def get_setting(self, key_path: str, default=None):
        """점 표기법으로 설정 가져오기 (예: 'autocomplete.enabled')"""
        keys = key_path.split('.')
        value = self.settings_data
        try:
            for key in keys:
                if isinstance(value, dict):
                    value = value.get(key)
                    if value is None:
                        return default
                else:
                    return default
            return value
        except (KeyError, TypeError, AttributeError):
            return default

    def set_setting(self, key_path: str, value):
        """점 표기법으로 설정 저장"""
        keys = key_path.split('.')
        data = self.settings_data
        for key in keys[:-1]:
            if key not in data:
                data[key] = {}
            data = data[key]
        data[keys[-1]] = value
        self.save_settings()
```

**사용 예시**:
```python
# 설정 읽기
autocomplete_enabled = settings_module.get_setting('autocomplete.enabled', True)

# 설정 쓰기
settings_module.set_setting('autocomplete.enabled', False)

# 중첩 설정
settings_module.set_setting('module_visibility.MyModule', False)
```

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

### Q5: 탭 분리 후 메모리 누수가 있어요

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
- 메모리 누수 → [Q5](#q5-탭-분리-후-메모리-누수가-있어요)

---

*문서 버전: 1.3*
*최종 업데이트: 2025-01-10*
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
