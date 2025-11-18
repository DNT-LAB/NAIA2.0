# 탭 개발 실전 예제

> **참조**: 이 문서는 [tabs/CLAUDE.md](../CLAUDE.md)의 상세 예제 레퍼런스입니다.

---

## 목차

1. [예제 1: 간단한 메모 탭](#예제-1-간단한-메모-탭-15분)
2. [예제 2: 이미지 정보 표시 탭](#예제-2-이미지-정보-표시-탭-30분)
3. [예제 3: WebEngine 브라우저 탭](#예제-3-webengine-브라우저-탭-45분)

---

## 예제 1: 간단한 메모 탭 (15분)

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

---

## 예제 2: 이미지 정보 표시 탭 (30분)

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

---

## 예제 3: WebEngine 브라우저 탭 (45분)

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

*문서 버전: 1.0*
*생성일: 2025-01-18*
