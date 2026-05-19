# ui/tag_result_window.py
"""
태그 분석 결과 윈도우

WD14 태그 분석 결과를 편집 가능한 프롬프트로 표시하고,
메인 프롬프트 적용 / 즉시 생성 / img2img / Inpaint / 닫기 액션 제공.

레이아웃: [이미지 프리뷰 | 프롬프트 TextEdit] + 하단 버튼 바
"""

from PIL import Image
from PIL.ImageQt import ImageQt
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QPushButton
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QCloseEvent
from legacy_desktop.ui.theme import DARK_COLORS, DARK_STYLES
from legacy_desktop.ui.scaling_manager import get_scaled_font_size, get_scaled_size

_BG_WINDOW = '#181818'
_BG_PANEL = '#1e1e1e'


class TagResultWindow(QMainWindow):
    """태그 분석 결과 윈도우 — 프롬프트 편집 + 액션 버튼"""

    apply_to_main_prompt = pyqtSignal(str)
    instant_generate_requested = pyqtSignal(str)
    img2img_requested = pyqtSignal(object, str)
    inpaint_requested = pyqtSignal(object, str)

    def __init__(self, pil_image: Image.Image, prompt_text: str, parent=None):
        super().__init__(parent=parent)
        self.pil_image = pil_image
        self._preview_qimage = None  # ImageQt 참조 유지 (GC 크래시 방지)

        self._init_ui(prompt_text)

    def _init_ui(self, prompt_text: str):
        self.setWindowTitle("Tag Analysis Result")
        self.setMinimumSize(800, 450)
        self.resize(950, 550)

        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowTitleHint
        )

        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {_BG_WINDOW};
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        central = QWidget()
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(
            get_scaled_size(14), get_scaled_size(14),
            get_scaled_size(14), get_scaled_size(14)
        )
        root_layout.setSpacing(get_scaled_size(12))

        # === 상단: 이미지 + 프롬프트 ===
        content = QHBoxLayout()
        content.setSpacing(get_scaled_size(12))

        # 좌: 이미지 프리뷰
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(get_scaled_size(300), get_scaled_size(300))
        self.preview_label.setStyleSheet(f"""
            QLabel {{
                background-color: {_BG_PANEL};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        content.addWidget(self.preview_label, stretch=35)

        # 우: 프롬프트 편집
        prompt_panel = QVBoxLayout()
        prompt_panel.setSpacing(get_scaled_size(4))

        prompt_label = QLabel("Extracted Prompt:")
        prompt_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(14)}px;
                color: {DARK_COLORS['text_primary']};
                font-weight: 600;
            }}
        """)
        prompt_panel.addWidget(prompt_label)

        self.prompt_edit = QTextEdit()
        self.prompt_edit.setAcceptRichText(False)
        self.prompt_edit.setPlaceholderText("Tags will appear here...")
        self.prompt_edit.setPlainText(prompt_text)
        self.prompt_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {_BG_PANEL};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px;
                font-size: {get_scaled_font_size(17)}px;
            }}
        """)
        prompt_panel.addWidget(self.prompt_edit, stretch=1)

        content.addLayout(prompt_panel, stretch=65)
        root_layout.addLayout(content, stretch=1)

        # === 하단: 버튼 바 ===
        btn_row = QHBoxLayout()
        btn_row.setSpacing(get_scaled_size(8))

        font_size = get_scaled_font_size(14)
        btn_h = get_scaled_size(38)

        # 메인 프롬프트 적용
        apply_btn = QPushButton("메인 프롬프트 적용")
        apply_btn.setMinimumHeight(btn_h)
        apply_btn.setStyleSheet(DARK_STYLES['primary_button'])
        apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(apply_btn)

        # 즉시 생성 (주황색)
        generate_btn = QPushButton("즉시 생성")
        generate_btn.setMinimumHeight(btn_h)
        generate_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #5C3D00;
                border: 1px solid #8C6E14;
                color: #FFD580;
                font-size: {font_size}px;
                font-weight: 500;
                border-radius: 4px;
                padding: 6px 16px;
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
            }}
            QPushButton:hover {{
                background-color: #6C4D10;
                border: 1px solid #9C7E24;
            }}
            QPushButton:pressed {{
                background-color: #4C2D00;
            }}
        """)
        generate_btn.clicked.connect(self._on_instant_generate)
        btn_row.addWidget(generate_btn)

        # img2img
        img2img_btn = QPushButton("img2img")
        img2img_btn.setMinimumHeight(btn_h)
        img2img_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        img2img_btn.clicked.connect(self._on_img2img)
        btn_row.addWidget(img2img_btn)

        # Inpaint
        inpaint_btn = QPushButton("Inpaint")
        inpaint_btn.setMinimumHeight(btn_h)
        inpaint_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        inpaint_btn.clicked.connect(self._on_inpaint)
        btn_row.addWidget(inpaint_btn)

        # 닫기
        close_btn = QPushButton("닫기")
        close_btn.setMinimumHeight(btn_h)
        close_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)

        root_layout.addLayout(btn_row)

        # 이미지 프리뷰 업데이트
        self._update_preview()

    def _update_preview(self):
        if not self.pil_image:
            return
        preview = self.pil_image.convert("RGBA")
        self._preview_qimage = ImageQt(preview)
        pixmap = QPixmap.fromImage(self._preview_qimage)
        label_size = self.preview_label.size()
        scaled = pixmap.scaled(
            label_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.preview_label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.pil_image:
            if not hasattr(self, '_resize_timer'):
                self._resize_timer = QTimer()
                self._resize_timer.setSingleShot(True)
                self._resize_timer.timeout.connect(self._update_preview)
            self._resize_timer.start(100)

    # ─── 버튼 핸들러 ──────────────────────────────

    def _on_apply(self):
        self.apply_to_main_prompt.emit(self.prompt_edit.toPlainText())
        self.close()

    def _on_instant_generate(self):
        self.instant_generate_requested.emit(self.prompt_edit.toPlainText())

    def _on_img2img(self):
        self.img2img_requested.emit(self.pil_image, self.prompt_edit.toPlainText())
        self.close()

    def _on_inpaint(self):
        self.inpaint_requested.emit(self.pil_image, self.prompt_edit.toPlainText())
        self.close()

    # ─── 창 닫기 ──────────────────────────────────

    def closeEvent(self, event: QCloseEvent):
        self.pil_image = None
        self._preview_qimage = None
        self.preview_label.clear()
        self.deleteLater()
        event.accept()
