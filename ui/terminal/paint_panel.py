"""SketchWindow — 독립 윈도우 스틱맨 드로잉 도구."""
import os
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QColor, QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QButtonGroup,
    QApplication, QFrame, QTextEdit, QColorDialog,
)
from ui.terminal.paint_canvas import StickmanCanvas
from ui.theme import DARK_COLORS
from ui.scaling_manager import get_scaled_size, get_scaled_font_size

GUIDE_PATH = os.path.join(os.path.dirname(__file__), ".cli", "stickman_prompt_guide.md")
CLI_DIR = os.path.join(os.path.dirname(__file__), ".cli")
DESC_FILENAME = "stickman_desc.txt"

# 브러시 색상
BRUSH_COLORS = [
    ("Black", QColor("#000000")),
    ("Blue", QColor("#1976D2")),
    ("Red", QColor("#D32F2F")),
    ("Green", QColor("#2E7D32")),
]

# 공용 스타일
_RADIUS = None
_FONT = None
_BTN_H = None


def _init_sizes():
    global _RADIUS, _FONT, _BTN_H
    if _RADIUS is None:
        _RADIUS = get_scaled_size(6)
        _FONT = get_scaled_font_size(13)
        _BTN_H = get_scaled_size(34)


def _tool_button_style() -> str:
    _init_sizes()
    return f"""
        QPushButton {{
            background-color: {DARK_COLORS['bg_tertiary']};
            color: {DARK_COLORS['text_primary']};
            border: 1px solid {DARK_COLORS['border']};
            border-radius: {_RADIUS}px;
            font-size: {_FONT}px;
            padding: 0 {get_scaled_size(10)}px;
        }}
        QPushButton:hover {{
            background-color: {DARK_COLORS['bg_hover']};
        }}
        QPushButton:pressed {{
            background-color: {DARK_COLORS['bg_pressed']};
        }}
    """


def _clear_button_style() -> str:
    _init_sizes()
    return f"""
        QPushButton {{
            background-color: #C62828;
            color: #FFFFFF;
            border: none;
            border-radius: {_RADIUS}px;
            font-size: {_FONT}px;
            font-weight: bold;
            padding: 0 {get_scaled_size(10)}px;
        }}
        QPushButton:hover {{
            background-color: #E53935;
        }}
        QPushButton:pressed {{
            background-color: #B71C1C;
        }}
    """


def _action_button_style() -> str:
    _init_sizes()
    return f"""
        QPushButton {{
            background-color: #2E7D32;
            color: #FFFFFF;
            border: none;
            border-radius: {_RADIUS}px;
            font-size: {_FONT}px;
            font-weight: bold;
            padding: 0 {get_scaled_size(14)}px;
        }}
        QPushButton:hover {{
            background-color: #388E3C;
        }}
        QPushButton:pressed {{
            background-color: #1B5E20;
        }}
    """


class SketchWindow(QWidget):
    """독립 윈도우 스틱맨 드로잉 도구."""

    def __init__(self, parent=None):
        super().__init__(parent)
        _init_sizes()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Stickman Sketch")
        self.setMinimumSize(600, 750)
        self.resize(870, 1080)
        self.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")

        layout = QVBoxLayout(self)
        m = get_scaled_size(10)
        layout.setContentsMargins(m, m, m, m)
        layout.setSpacing(get_scaled_size(8))

        # ── 상단 툴바 ──
        toolbar = QFrame(self)
        toolbar.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-radius: {_RADIUS}px;
            }}
        """)
        tb_layout = QHBoxLayout(toolbar)
        tb_m = get_scaled_size(6)
        tb_layout.setContentsMargins(tb_m, tb_m, tb_m, tb_m)
        tb_layout.setSpacing(get_scaled_size(6))

        # 색상 버튼
        self._color_group = QButtonGroup(self)
        self._color_group.setExclusive(True)
        self._custom_color = QColor("#FF6F00")  # 사용자 지정 색상 기본값

        for i, (label, color) in enumerate(BRUSH_COLORS):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(_BTN_H)
            btn.setMinimumWidth(get_scaled_size(56))
            self._apply_color_btn_style(btn, color)
            self._color_group.addButton(btn, i)
            tb_layout.addWidget(btn)
            if i == 0:
                btn.setChecked(True)

        # 사용자 지정 색상 버튼
        custom_id = len(BRUSH_COLORS)
        self._custom_btn = QPushButton("Custom")
        self._custom_btn.setCheckable(True)
        self._custom_btn.setFixedHeight(_BTN_H)
        self._custom_btn.setMinimumWidth(get_scaled_size(66))
        self._apply_color_btn_style(self._custom_btn, self._custom_color)
        self._color_group.addButton(self._custom_btn, custom_id)
        tb_layout.addWidget(self._custom_btn)

        self._color_group.idClicked.connect(self._on_color_changed)

        # 구분선
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color: {DARK_COLORS['border']};")
        tb_layout.addWidget(sep)

        # Undo / Redo
        tool_style = _tool_button_style()
        for label, slot in [("Undo", self._undo), ("Redo", self._redo)]:
            btn = QPushButton(label)
            btn.setFixedHeight(_BTN_H)
            btn.setStyleSheet(tool_style)
            btn.clicked.connect(slot)
            tb_layout.addWidget(btn)

        # Clear (적색 강조)
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedHeight(_BTN_H)
        clear_btn.setStyleSheet(_clear_button_style())
        clear_btn.clicked.connect(self._clear)
        tb_layout.addWidget(clear_btn)

        tb_layout.addStretch()
        layout.addWidget(toolbar)

        # ── 캔버스 ──
        self._canvas = StickmanCanvas(self)
        layout.addWidget(self._canvas, stretch=1)

        # ── 설명 입력 ──
        desc_font = get_scaled_font_size(19)
        self._desc_edit = QTextEdit(self)
        self._desc_edit.setAcceptRichText(False)
        self._desc_edit.setPlaceholderText("추가 설명 입력 (예: 환자복을 입은 소녀가 손에 링거를 꽂고 이동하고 있음)")
        self._desc_edit.setFixedHeight(get_scaled_size(64))
        self._desc_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {_RADIUS}px;
                font-size: {desc_font}px;
                padding: {get_scaled_size(4)}px;
            }}
            QTextEdit:focus {{
                border-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        layout.addWidget(self._desc_edit)

        # ── 하단 액션 바 ──
        action_frame = QFrame(self)
        action_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-radius: {_RADIUS}px;
            }}
        """)
        action_layout = QHBoxLayout(action_frame)
        af_m = get_scaled_size(6)
        action_layout.setContentsMargins(af_m, af_m, af_m, af_m)
        action_layout.setSpacing(get_scaled_size(8))

        action_style = _action_button_style()

        self._init_btn = QPushButton("Copy Init Request")
        self._init_btn.setFixedHeight(_BTN_H)
        self._init_btn.setStyleSheet(action_style)
        self._init_btn.clicked.connect(self._copy_init_request)
        action_layout.addWidget(self._init_btn)

        self._req_btn = QPushButton("Copy Request")
        self._req_btn.setFixedHeight(_BTN_H)
        self._req_btn.setStyleSheet(action_style)
        self._req_btn.clicked.connect(self._copy_request)
        action_layout.addWidget(self._req_btn)

        layout.addWidget(action_frame)

        # ── 저장된 설명 텍스트 복원 ──
        self._load_desc()

        # ── 키보드 단축키 ──
        QShortcut(QKeySequence("Ctrl+Z"), self).activated.connect(self._undo)
        QShortcut(QKeySequence("Ctrl+Y"), self).activated.connect(self._redo)

    # ── 색상 버튼 스타일 ──

    def _apply_color_btn_style(self, btn: QPushButton, color: QColor):
        hex_c = color.name()
        text_c = "#FFFFFF" if color.lightness() < 128 else "#000000"
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {hex_c};
                color: {text_c};
                border: 2px solid {DARK_COLORS['border']};
                border-radius: {_RADIUS}px;
                font-size: {_FONT}px;
                font-weight: bold;
                padding: 0 {get_scaled_size(8)}px;
            }}
            QPushButton:hover {{
                border-color: {DARK_COLORS['border_light']};
            }}
            QPushButton:checked {{
                border: 3px solid #66BB6A;
            }}
        """)

    # ── 색상 변경 ──

    def _on_color_changed(self, idx: int):
        custom_id = len(BRUSH_COLORS)
        if idx < custom_id:
            self._canvas.set_brush_color(BRUSH_COLORS[idx][1])
        else:
            # Custom 버튼 — 간소화된 색상 선택 다이얼로그
            dlg = QColorDialog(self._custom_color, self)
            dlg.setWindowTitle("브러시 색상 선택")
            dlg.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
            dlg.setOption(QColorDialog.ColorDialogOption.NoButtons, True)
            # HSV/RGB 입력 패널 숨기기, 기본 색상 + 스펙트럼만 표시
            for w in dlg.findChildren(QWidget):
                name = w.objectName() or ""
                cls = type(w).__name__
                # 숫자 입력 스핀박스, 라벨(Hue/Sat/Red 등), HTML 입력 제거
                if cls in ("QSpinBox", "QLineEdit"):
                    w.hide()
                elif cls == "QLabel" and name not in ("", "qt_colorpicker_basic"):
                    w.hide()
            # 다크 테마 스타일
            dlg.setStyleSheet(f"""
                QColorDialog {{
                    background-color: {DARK_COLORS['bg_primary']};
                    color: #FFFFFF;
                }}
                QWidget {{
                    color: #FFFFFF;
                }}
                QLabel {{
                    color: #FFFFFF;
                    font-size: {_FONT}px;
                }}
                QPushButton {{
                    background-color: {DARK_COLORS['bg_tertiary']};
                    color: #FFFFFF;
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: {_RADIUS}px;
                    padding: {get_scaled_size(6)}px {get_scaled_size(16)}px;
                    font-size: {_FONT}px;
                }}
                QPushButton:hover {{
                    background-color: {DARK_COLORS['bg_hover']};
                }}
                QGroupBox {{
                    color: #FFFFFF;
                    font-size: {_FONT}px;
                }}
            """)
            # OK / Cancel 버튼 추가 (하단 우측)
            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            ok_btn = QPushButton("OK")
            ok_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {DARK_COLORS['accent_blue']};
                    color: #FFFFFF;
                    border: none;
                    border-radius: {_RADIUS}px;
                    padding: {get_scaled_size(6)}px {get_scaled_size(20)}px;
                    font-size: {_FONT}px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {DARK_COLORS['accent_blue_hover']};
                }}
            """)
            cancel_btn = QPushButton("Cancel")
            ok_btn.clicked.connect(dlg.accept)
            cancel_btn.clicked.connect(dlg.reject)
            btn_layout.addWidget(ok_btn)
            btn_layout.addWidget(cancel_btn)
            dlg.layout().addLayout(btn_layout)

            # TODO(web-dialog): 원래 QColorDialog.exec() — Web Shell 컬러 피커로 재구현 필요. 현재 차단.
            print("[Dialog/SKIPPED] QColorDialog 차단 — 기존 커스텀 색상 유지. Web Shell 재구현 예정")
            self._canvas.set_brush_color(self._custom_color)

    # ── Undo / Redo / Clear ──

    def _undo(self):
        self._canvas.undo()

    def _redo(self):
        self._canvas.redo()

    def _clear(self):
        self._canvas.clear_canvas()
        self._desc_edit.clear()
        self._save_desc()

    # ── 설명 텍스트 저장/복원 ──

    def _desc_path(self) -> str:
        return os.path.join(CLI_DIR, DESC_FILENAME)

    def _save_desc(self):
        os.makedirs(CLI_DIR, exist_ok=True)
        with open(self._desc_path(), "w", encoding="utf-8") as f:
            f.write(self._desc_edit.toPlainText())

    def _load_desc(self):
        path = self._desc_path()
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                self._desc_edit.setPlainText(f.read())

    # ── 클립보드 복사 ──

    def _get_user_desc(self) -> str:
        """설명 텍스트가 있으면 포맷팅하여 반환."""
        desc = self._desc_edit.toPlainText().strip()
        if desc:
            return f"\n[사용자 설명]: {desc}\n"
        return ""

    def _copy_init_request(self):
        self._save_desc()
        guide = os.path.abspath(GUIDE_PATH)
        image = os.path.abspath(self._canvas.get_image_path())
        desc = self._get_user_desc()
        text = (
            f"아래 마크다운 가이드와 이미지를 참고하세요.\n\n"
            f"[가이드 파일]: {guide}\n"
            f"※ 가이드 파일은 UTF-8로 인코딩되어 있습니다. "
            f"읽기 실패 시 encoding='utf-8' 또는 'cp949'로 재시도하세요.\n"
            f"[스틱맨 이미지]: {image}\n"
            f"{desc}\n"
            f"가이드를 읽고, 이 스틱맨 그림을 분석하여 "
            f"Stable Diffusion SDXL 기반 태그를 제안해주세요."
        )
        QApplication.clipboard().setText(text)

    def _copy_request(self):
        self._save_desc()
        image = os.path.abspath(self._canvas.get_image_path())
        desc = self._get_user_desc()
        text = (
            f"아래 스틱맨 이미지를 분석해주세요.\n\n"
            f"[스틱맨 이미지]: {image}\n"
            f"{desc}\n"
            f"씬 구성, 오브젝트(존재하는 경우), 캐릭터 포즈를 고려하여 "
            f"적절한 SDXL 프롬프트 태그를 제안해주세요."
        )
        QApplication.clipboard().setText(text)
