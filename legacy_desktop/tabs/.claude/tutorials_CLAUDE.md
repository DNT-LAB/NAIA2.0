# 탭 개발 단계별 튜토리얼

> **참조**: 이 문서는 [tabs/CLAUDE.md](../CLAUDE.md)의 상세 튜토리얼 레퍼런스입니다.

---

## 목차

1. [튜토리얼 1: 최소 뷰어 탭](#튜토리얼-1-최소-뷰어-탭-30분)
2. [튜토리얼 2: 대화형 도구 탭](#튜토리얼-2-대화형-도구-탭-2시간)
3. [튜토리얼 3: 복잡한 WebEngine 탭](#튜토리얼-3-복잡한-webengine-탭-1일)
4. [튜토리얼 4: 완전한 애플리케이션 탭](#튜토리얼-4-완전한-애플리케이션-탭-1주)

---

## 튜토리얼 1: 최소 뷰어 탭 (30분)

**목표**: 생성된 이미지를 표시하는 최소 탭

### 1단계: 기본 구조 작성 (5분)

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

### 2단계: 이미지 로드 기능 추가 (10분)

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

### 3단계: 이벤트 구독으로 자동 업데이트 (15분)

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

---

## 튜토리얼 2: 대화형 도구 탭 (2시간)

**목표**: 프롬프트 분석 및 제안 탭

### 1단계: UI 레이아웃 (30분)

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

### 2단계: 분석 로직 구현 (45분)

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

### 3단계: AppContext 통합 (30분)

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

### 4단계: 고급 기능 추가 (15분)

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

---

## 튜토리얼 3: 복잡한 WebEngine 탭 (1일)

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

---

## 튜토리얼 4: 완전한 애플리케이션 탭 (1주)

**목표**: 설정 관리, 파일 저장/로드, 이벤트 통합을 모두 갖춘 탭

**참고 파일**: `tabs/setting_tabs.py`

### 주요 기능

#### 1. JSON 설정 저장/로드
**위치**: `setting_tabs.py:54-117`

```python
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
```

#### 2. 저장 디렉토리 관리
**위치**: `setting_tabs.py:241-267`

- 기본 저장 경로 설정
- 타임스탬프 폴더 사용 여부 체크박스 (`line 263-267`)

#### 3. 파일명 형식 선택
**위치**: `setting_tabs.py:289-310`

- number_only, time_number, datetime

#### 4. 분류 시스템 설정
**위치**: `setting_tabs.py:312-462`

- 분류 방법 선택 (none, prompt_recognition)
- 프롬프트 인식 분류 규칙 입력 (`line 343-382`)
- 2차 분류 시스템 (`line 393-462`)
  - 2차 분류 활성화 체크박스
  - 2차 분류 방법 선택 (none, prompt_recognition)
  - 규칙 선택 콤보박스 (1차 규칙에서 자동 생성)
  - 선택된 규칙별 2차 분류 규칙 입력

#### 5. 이미지 저장 카운터 표시 및 초기화
**위치**: `setting_tabs.py:269-287`

- 실시간 카운터 표시 (이벤트 구독)
- 카운터 수동 초기화 버튼

#### 6. 모듈/탭 가시성 관리
**위치**: `setting_tabs.py:414-530`

- 체크박스로 모듈/탭 표시/숨김 설정
- 프로그램 시작 시 자동 적용 (`line 950-956`)
- 재시도 메커니즘 (컨트롤러 준비 대기, `line 1067-1160`)
- 디버깅 로그 추가 (상태 추적)

#### 7. AppContext 이벤트 발행/구독
**위치**: `setting_tabs.py:129-136, 588-618`

#### 8. QTimer 지연 초기화
**위치**: `setting_tabs.py:549-560`

### 모듈/탭 가시성 적용 흐름

```python
# 1. 프로그램 시작 시 (on_initialize)
def on_initialize(self):
    self.load_settings()
    if self.settings_widget:
        self.settings_widget.update_ui_from_settings()

# 2. update_ui_from_settings에서 가시성 적용 함수 호출
def update_ui_from_settings(self):
    # ... UI 설정 ...

    # 저장된 가시성 설정 적용 (프로그램 시작 시)
    QTimer.singleShot(200, self._apply_saved_module_visibility)
    QTimer.singleShot(250, self._apply_saved_tab_visibility)

# 3. 재시도 메커니즘으로 안전하게 적용
def _apply_saved_module_visibility(self, retry_count=0):
    max_retries = 3

    # 컨트롤러 준비 확인
    if not hasattr(self.app_context, 'middle_section_controller'):
        if retry_count < max_retries:
            QTimer.singleShot(500, lambda: self._apply_saved_module_visibility(retry_count + 1))
        return

    # 가시성 적용
    for module in controller.module_instances:
        is_visible = self.settings_module.get_setting(f'module_visibility.{module_id}', True)
        if not is_visible:
            box.setVisible(False)
```

---

*문서 버전: 1.0*
*생성일: 2025-01-18*
