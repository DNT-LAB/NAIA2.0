# UI 실전 예제 레퍼런스

> **레퍼런스 문서**: 실전 예제 코드 모음입니다. 메인 문서에서 링크로 참조됩니다.

---

## 예제 1: 테마를 사용한 기본 위젯 (5분)

**목표**: DARK_STYLES로 일관된 UI 만들기

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLineEdit, QTextEdit
from ui.theme import DARK_STYLES, DARK_COLORS

class MyWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        # 메인 배경
        self.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")

        layout = QVBoxLayout(self)

        # 입력 필드
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("검색...")
        self.input_field.setStyleSheet(DARK_STYLES['compact_lineedit'])

        # 텍스트 에디터
        self.text_edit = QTextEdit()
        self.text_edit.setAcceptRichText(False)  # 필수!
        self.text_edit.setStyleSheet(DARK_STYLES['compact_textedit'])

        # 주요 버튼
        self.save_btn = QPushButton("저장")
        self.save_btn.setStyleSheet(DARK_STYLES['primary_button'])

        # 보조 버튼
        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.setStyleSheet(DARK_STYLES['secondary_button'])

        layout.addWidget(self.input_field)
        layout.addWidget(self.text_edit)
        layout.addWidget(self.save_btn)
        layout.addWidget(self.cancel_btn)
```

---

## 예제 2: 스케일링을 사용한 반응형 UI (10분)

**목표**: 모든 해상도에서 잘 보이는 UI

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from ui.theme import DARK_STYLES, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

class ResponsiveWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # ✅ 스케일링 적용된 여백
        layout.setContentsMargins(
            get_scaled_size(16),
            get_scaled_size(16),
            get_scaled_size(16),
            get_scaled_size(16)
        )
        layout.setSpacing(get_scaled_size(8))

        # ✅ 스케일링 적용된 폰트
        title = QLabel("제목")
        title.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(24)}px;
                font-weight: 600;
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        subtitle = QLabel("부제목")
        subtitle.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_secondary']};
            }}
        """)

        # ✅ 스케일링 적용된 버튼 크기
        button = QPushButton("확인")
        button.setStyleSheet(f"""
            {DARK_STYLES['primary_button']}
            QPushButton {{
                min-height: {get_scaled_size(40)}px;
                padding: {get_scaled_size(8)}px {get_scaled_size(24)}px;
            }}
        """)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(button)
```

---

## 예제 3: CollapsibleBox 활용 (15분)

**목표**: 모듈처럼 접고 펼칠 수 있는 섹션 생성

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QCheckBox, QSpinBox
from ui.collapsible import EnhancedCollapsibleBox
from ui.theme import DARK_STYLES

class SettingsPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        # 첫 번째 섹션
        general_box = EnhancedCollapsibleBox(title="일반 설정", detachable=False)
        general_content = QVBoxLayout()

        self.auto_save_cb = QCheckBox("자동 저장")
        self.auto_save_cb.setStyleSheet(DARK_STYLES['dark_checkbox'])

        self.interval_spin = QSpinBox()
        self.interval_spin.setStyleSheet(DARK_STYLES['compact_spinbox'])
        self.interval_spin.setRange(1, 60)
        self.interval_spin.setValue(5)

        general_content.addWidget(self.auto_save_cb)
        general_content.addWidget(QLabel("저장 간격 (분):"))
        general_content.addWidget(self.interval_spin)

        general_box.setContentLayout(general_content)

        # 두 번째 섹션
        advanced_box = EnhancedCollapsibleBox(title="고급 설정", detachable=True)
        advanced_content = QVBoxLayout()

        self.debug_cb = QCheckBox("디버그 모드")
        self.debug_cb.setStyleSheet(DARK_STYLES['dark_checkbox'])

        advanced_content.addWidget(self.debug_cb)

        advanced_box.setContentLayout(advanced_content)

        # 분리 시그널 연결
        advanced_box.module_detach_requested.connect(self._on_detach_requested)

        main_layout.addWidget(general_box)
        main_layout.addWidget(advanced_box)

    def _on_detach_requested(self, title, widget):
        print(f"분리 요청: {title}")
        # DetachedWindow로 열기 (생략)
```

---

## 예제 4: ModernMenu 통합 (10분)

**목표**: 컨텍스트 메뉴에 태그 정보 표시

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit
from ui.modern_menu import setModernStyle
from ui.theme import DARK_STYLES

class PromptEditor(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # QTextEdit 생성
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setAcceptRichText(False)  # 필수!
        self.prompt_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.prompt_edit.setPlaceholderText("태그를 입력하세요 (예: 1girl, smile)")

        # ✅ ModernMenu 적용 (태그 정보 + 인스턴트 와일드카드)
        setModernStyle(self.prompt_edit)

        layout.addWidget(self.prompt_edit)

    # 사용자가 태그 위에서 우클릭하면:
    # → data/KR_tags.parquet에서 태그 정보 로드
    # → 태그 이름, 사용 횟수, Category, Description 표시
    # → 텍스트 선택 시 "인스턴트 와일드카드 추가" 액션 제공
```

---

## 예제 5: 완전한 분리 가능 패널 (30분)

**목표**: 분리할 수 있는 모듈 패널 구현

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from ui.collapsible import EnhancedCollapsibleBox
from ui.detached_window import DetachedWindow
from ui.theme import DARK_STYLES, DARK_COLORS

class DetachablePanel(QWidget):
    def __init__(self):
        super().__init__()
        self.detached_windows = {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 분리 가능한 모듈 박스
        self.box = EnhancedCollapsibleBox(title="내 모듈", detachable=True)

        # 콘텐츠
        content_layout = QVBoxLayout()

        content_layout.addWidget(QLabel("모듈 콘텐츠"))

        btn = QPushButton("액션")
        btn.setStyleSheet(DARK_STYLES['primary_button'])
        content_layout.addWidget(btn)

        self.box.setContentLayout(content_layout)

        # 분리 시그널 연결
        self.box.module_detach_requested.connect(self._on_detach)

        layout.addWidget(self.box)

    def _on_detach(self, title, content_widget):
        """모듈 분리 요청"""
        print(f"분리 요청: {title}")

        # DetachedWindow 생성
        detached_window = DetachedWindow(
            widget=content_widget,
            title=title,
            tab_index=0,  # 모듈은 탭이 아니므로 더미 인덱스
            parent_container=self
        )

        # 닫기 시그널
        detached_window.window_closed.connect(self._on_window_closed)

        # 분리 상태 설정
        self.box.set_detached_state(True)

        # 창 추적
        self.detached_windows[title] = detached_window

        # 창 표시
        detached_window.show()
        detached_window.raise_()
        detached_window.activateWindow()

    def _on_window_closed(self, tab_index, widget):
        """분리 창 닫힘 → 복귀"""
        print("창 닫힘, 위젯 복귀")

        # 위젯을 원래 위치로 복원
        if self.box.content_area:
            widget.setParent(self.box.content_area)
            self.box.content_area.setWidget(widget)

        # 분리 상태 해제
        self.box.set_detached_state(False)

        # 추적 제거
        for title, window in list(self.detached_windows.items()):
            if window.original_widget == widget:
                del self.detached_windows[title]
                break
```

---

*레퍼런스 문서 버전: 1.0*
*최종 업데이트: 2025-01-17*
