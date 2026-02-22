# ui/img2img_window.py
"""
독립 Img2Img/Inpaint 윈도우

메인 UI의 프롬프트/네거티브 프롬프트/캐릭터 프롬프트를 매번 스크롤할 필요 없이,
이미지 프리뷰 + 프롬프트 편집 + 슬라이더 + 생성 버튼을 한 곳에서 사용할 수 있는 독립 창.

레이아웃: 좌(이미지+슬라이더) | 중앙(메인프롬프트) | 우(탭뷰: [Character] [Undesired Content])
"""

import io
import numpy as np
from PIL import Image
from PIL.ImageQt import ImageQt
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QPushButton, QScrollArea, QSlider, QTabWidget, QCheckBox,
    QSpinBox, QProgressBar
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QCloseEvent
from ui.theme import DARK_COLORS, DARK_STYLES
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

# 윈도우 전용 배경색 (메인 테마보다 어두운 계열)
_BG_WINDOW = '#181818'
_BG_PANEL = '#1e1e1e'


class Img2ImgWindow(QMainWindow):
    """독립 Img2Img/Inpaint 윈도우 - 프롬프트 편집 + 이미지 프리뷰 + 생성"""

    # 시그널 정의
    generate_requested = pyqtSignal(int, dict)  # (window_id, overrides)
    window_closing = pyqtSignal(int)            # (window_id)
    cancel_batch_requested = pyqtSignal(int)    # (window_id)

    def __init__(self, window_id: int, app_context, parent=None):
        super().__init__(parent=parent)

        self.window_id = window_id
        self.app_context = app_context

        # 이미지/마스크 상태
        self.pil_image = None
        self.mode = 'img2img'  # 'img2img' | 'inpaint' | 'auto_outpainting'
        self.full_mask_pil = None
        self.small_mask_pil = None
        self._outpaint_data = None

        # ImageQt 참조 유지 (GC 크래시 방지)
        self._preview_qimage = None

        # 캐릭터 프롬프트 위젯 리스트
        self.character_rows = []

        # 버튼 피드백 스타일
        self.FEEDBACK_STYLE = f"""
            QPushButton {{
                background-color: {DARK_COLORS['text_disabled']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 8px;
                font-size: {get_scaled_font_size(18)}px;
                font-weight: 500;
            }}
        """

        self.init_ui()
        print(f"✅ [Img2ImgWindow] 창 #{self.window_id} 생성됨")

    def init_ui(self):
        """UI 초기화 - 3컬럼 수평 레이아웃"""
        self.setWindowTitle("Img2Img")
        self.setMinimumSize(1000, 550)
        self.resize(1200, 700)

        # 독립 창 플래그
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowTitleHint
        )

        # 어두운 배경 테마
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {_BG_WINDOW};
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(
            get_scaled_size(12), get_scaled_size(12),
            get_scaled_size(12), get_scaled_size(12)
        )
        main_layout.setSpacing(get_scaled_size(10))

        # === 3컬럼 수평 레이아웃 ===
        content_layout = QHBoxLayout()
        content_layout.setSpacing(get_scaled_size(12))

        # 좌측: 이미지 + 슬라이더 + 버튼
        left_panel = self._create_left_panel()
        # 중앙: 메인 프롬프트 (전체 높이)
        center_panel = self._create_center_panel()
        # 우측: 탭뷰 (캐릭터 + 네거티브)
        right_panel = self._create_right_panel()

        content_layout.addWidget(left_panel, stretch=30)
        content_layout.addWidget(center_panel, stretch=35)
        content_layout.addWidget(right_panel, stretch=35)

        main_layout.addLayout(content_layout)

        # === 하단: 횟수 + Generate + Cancel + Progress ===
        bottom_layout = QVBoxLayout()
        bottom_layout.setSpacing(get_scaled_size(4))

        # Row 1: [횟수: SpinBox] [Generate] [Cancel(hidden)]
        row1 = QHBoxLayout()
        row1.setSpacing(get_scaled_size(6))

        repeat_label = QLabel("횟수:")
        repeat_label.setStyleSheet(
            f"font-size: {get_scaled_font_size(14)}px; color: {DARK_COLORS['text_primary']};"
        )
        row1.addWidget(repeat_label)

        self.repeat_spin = QSpinBox()
        self.repeat_spin.setRange(1, 99)
        self.repeat_spin.setValue(1)
        self.repeat_spin.setFixedWidth(get_scaled_size(60))
        self.repeat_spin.setStyleSheet(DARK_STYLES['compact_spinbox'])
        row1.addWidget(self.repeat_spin)

        self.generate_btn = QPushButton("🎨 Generate")
        self.generate_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.generate_btn.setMinimumHeight(get_scaled_size(42))
        self.generate_btn.clicked.connect(self.on_generate_clicked)
        row1.addWidget(self.generate_btn, stretch=1)

        self.cancel_btn = QPushButton("■ 중지")
        self.cancel_btn.setMinimumHeight(get_scaled_size(42))
        self.cancel_btn.setFixedWidth(get_scaled_size(80))
        self.cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #8B0000;
                color: {DARK_COLORS['text_primary']};
                border: 1px solid #B22222;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: {get_scaled_font_size(14)}px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: #A52A2A;
                border: 1px solid #CD5C5C;
            }}
            QPushButton:pressed {{
                background-color: #660000;
            }}
        """)
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        self.cancel_btn.setVisible(False)
        row1.addWidget(self.cancel_btn)

        bottom_layout.addLayout(row1)

        # Row 2: Progress Bar (hidden until batch)
        self.batch_progress = QProgressBar()
        self.batch_progress.setFixedHeight(get_scaled_size(20))
        self.batch_progress.setTextVisible(True)
        self.batch_progress.setFormat("")
        self.batch_progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                text-align: center;
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(13)}px;
            }}
            QProgressBar::chunk {{
                background-color: {DARK_COLORS['accent_blue']};
                border-radius: {get_scaled_size(3)}px;
            }}
        """)
        self.batch_progress.setVisible(False)
        bottom_layout.addWidget(self.batch_progress)

        main_layout.addLayout(bottom_layout)

    # ─── 좌측 패널 ───────────────────────────────────────────

    def _create_left_panel(self) -> QWidget:
        """좌측 패널: 이미지 프리뷰 + Strength/Noise 슬라이더 + 버튼"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(8))

        # 이미지 프리뷰
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(get_scaled_size(250), get_scaled_size(250))
        self.preview_label.setStyleSheet(f"""
            QLabel {{
                background-color: {_BG_PANEL};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        layout.addWidget(self.preview_label, stretch=1)

        # 슬라이더 스타일 (img2img_panel.py와 동일)
        slider_style = f"""
            QSlider::groove:horizontal {{
                background: #22253F;
                height: 12px;
                border-radius: 4px;
            }}
            QSlider::handle:horizontal {{
                background: #F5F3C2;
                width: 18px;
                height: 18px;
                margin: -4px 0;
                border-radius: 2px;
            }}
            QSlider::handle:horizontal:hover {{
                background: {DARK_COLORS['accent_blue_hover']};
            }}
            QSlider::sub-page:horizontal {{
                background: #525252;
                border-radius: 4px;
            }}
        """
        label_style = f"font-size: {get_scaled_font_size(13)}px; color: {DARK_COLORS['text_primary']};"
        value_style = f"font-size: {get_scaled_font_size(13)}px; color: #AAA; min-width: 35px;"

        # Strength 슬라이더
        strength_row = QHBoxLayout()
        strength_label = QLabel("Strength:")
        strength_label.setStyleSheet(label_style)
        self.strength_value_label = QLabel("0.50")
        self.strength_value_label.setStyleSheet(value_style)
        self.strength_slider = QSlider(Qt.Orientation.Horizontal)
        self.strength_slider.setRange(1, 99)
        self.strength_slider.setValue(50)
        self.strength_slider.setStyleSheet(slider_style)
        self.strength_slider.valueChanged.connect(
            lambda v: self.strength_value_label.setText(f"{v / 100.0:.2f}")
        )
        strength_row.addWidget(strength_label)
        strength_row.addWidget(self.strength_slider)
        strength_row.addWidget(self.strength_value_label)
        layout.addLayout(strength_row)

        # Noise 슬라이더
        noise_row = QHBoxLayout()
        noise_label = QLabel("Noise:")
        noise_label.setStyleSheet(label_style)
        self.noise_value_label = QLabel("0.00")
        self.noise_value_label.setStyleSheet(value_style)
        self.noise_slider = QSlider(Qt.Orientation.Horizontal)
        self.noise_slider.setRange(0, 99)
        self.noise_slider.setValue(0)
        self.noise_slider.setStyleSheet(slider_style)
        self.noise_slider.valueChanged.connect(
            lambda v: self.noise_value_label.setText(f"{v / 100.0:.2f}")
        )
        noise_row.addWidget(noise_label)
        noise_row.addWidget(self.noise_slider)
        noise_row.addWidget(self.noise_value_label)
        layout.addLayout(noise_row)

        # 버튼 행 (Edit Mask / Outpaint)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(get_scaled_size(6))

        self.edit_mask_btn = QPushButton("Edit Mask")
        self.edit_mask_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.edit_mask_btn.clicked.connect(self._on_edit_mask_clicked)
        btn_row.addWidget(self.edit_mask_btn)

        self.outpaint_btn = QPushButton("Outpaint")
        self.outpaint_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.outpaint_btn.clicked.connect(self._on_outpaint_clicked)
        btn_row.addWidget(self.outpaint_btn)

        layout.addLayout(btn_row)

        return panel

    # ─── 중앙 패널 ───────────────────────────────────────────

    def _create_center_panel(self) -> QWidget:
        """중앙 패널: 메인 프롬프트 (전체 높이 차지)"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(4))

        main_label = QLabel("Main Prompt:")
        main_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(14)}px;
                color: {DARK_COLORS['text_primary']};
                font-weight: 600;
            }}
        """)
        layout.addWidget(main_label)

        self.main_prompt_edit = QTextEdit()
        self.main_prompt_edit.setAcceptRichText(False)
        self.main_prompt_edit.setPlaceholderText("Main prompt...")
        self.main_prompt_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {_BG_PANEL};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px;
                font-size: {get_scaled_font_size(18)}px;
            }}
        """)
        layout.addWidget(self.main_prompt_edit, stretch=1)

        return panel

    # ─── 우측 패널 (탭뷰) ────────────────────────────────────

    def _create_right_panel(self) -> QWidget:
        """우측 패널: 탭뷰 — [Character] / [Undesired Content] 탭"""
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(DARK_STYLES['dark_tabs'])

        # 공통 스타일 저장
        self._textedit_style = f"""
            QTextEdit {{
                background-color: {_BG_PANEL};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(3)}px;
                padding: {get_scaled_size(4)}px;
                font-size: {get_scaled_font_size(17)}px;
            }}
        """
        self._scroll_style = f"""
            QScrollArea {{
                border: none;
                background-color: transparent;
            }}
        """

        # === 탭 1: Character ===
        char_tab = self._create_character_tab()
        self.tab_widget.addTab(char_tab, "Character")

        # === 탭 2: Undesired Content ===
        uc_tab = self._create_uc_tab()
        self.tab_widget.addTab(uc_tab, "Undesired Content")

        return self.tab_widget

    def _create_character_tab(self) -> QWidget:
        """Character 탭: 캐릭터 목록 + 추가 버튼"""
        tab_widget = QWidget()
        tab_widget.setStyleSheet(f"QWidget {{ background-color: {_BG_WINDOW}; }}")
        tab_layout = QVBoxLayout(tab_widget)
        tab_layout.setContentsMargins(
            get_scaled_size(8), get_scaled_size(8),
            get_scaled_size(8), get_scaled_size(8)
        )
        tab_layout.setSpacing(get_scaled_size(6))

        # 캐릭터 행을 담을 스크롤 영역
        self.character_scroll = QScrollArea()
        self.character_scroll.setWidgetResizable(True)
        self.character_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.character_scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background-color: {_BG_WINDOW}; }}
            QScrollArea > QWidget > QWidget {{ background-color: {_BG_WINDOW}; }}
        """)

        self.character_container = QWidget()
        self.character_container.setStyleSheet(f"background-color: {_BG_WINDOW};")
        self.character_layout = QVBoxLayout(self.character_container)
        self.character_layout.setContentsMargins(0, 0, 0, 0)
        self.character_layout.setSpacing(get_scaled_size(6))
        self.character_layout.addStretch(1)  # 하단 여백

        self.character_scroll.setWidget(self.character_container)
        tab_layout.addWidget(self.character_scroll, stretch=1)

        # + Add Character 버튼
        self.add_char_btn = QPushButton("+ Add Character")
        self.add_char_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.add_char_btn.clicked.connect(self._add_character_row)
        tab_layout.addWidget(self.add_char_btn)

        return tab_widget

    def _create_uc_tab(self) -> QWidget:
        """Undesired Content 탭: 네거티브 프롬프트"""
        tab_widget = QWidget()
        tab_widget.setStyleSheet(f"QWidget {{ background-color: {_BG_WINDOW}; }}")
        tab_layout = QVBoxLayout(tab_widget)
        tab_layout.setContentsMargins(
            get_scaled_size(8), get_scaled_size(8),
            get_scaled_size(8), get_scaled_size(8)
        )
        tab_layout.setSpacing(get_scaled_size(4))

        neg_label = QLabel("Undesired Content:")
        neg_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(13)}px;
                color: {DARK_COLORS['text_secondary']};
                font-weight: 600;
            }}
        """)
        tab_layout.addWidget(neg_label)

        self.negative_prompt_edit = QTextEdit()
        self.negative_prompt_edit.setAcceptRichText(False)
        self.negative_prompt_edit.setPlaceholderText("Undesired content...")
        self.negative_prompt_edit.setStyleSheet(self._textedit_style)
        tab_layout.addWidget(self.negative_prompt_edit, stretch=1)

        return tab_widget

    # ─── 이미지/모드 설정 ─────────────────────────────────────

    def set_image(self, pil_image, mode='img2img', mask_data=None, outpaint_data=None):
        """이미지/모드/마스크/아웃페인트 데이터 설정 및 프리뷰 업데이트"""
        self.pil_image = pil_image
        self.mode = mode
        self._outpaint_data = outpaint_data

        if mask_data:
            self.full_mask_pil = mask_data.get('full_mask_image')
            self.small_mask_pil = mask_data.get('small_mask_image')
        else:
            self.full_mask_pil = None
            self.small_mask_pil = None

        self._update_preview()
        self._update_title()

    def _update_title(self):
        """모드와 이미지 크기에 따라 타이틀 업데이트"""
        if not self.pil_image:
            self.setWindowTitle("Img2Img")
            return

        w, h = self.pil_image.size
        if self.mode == 'inpaint':
            self.setWindowTitle(f"Inpaint - {w}x{h}")
        elif self.mode == 'auto_outpainting' and self._outpaint_data:
            cw = self._outpaint_data.get('canvas_width', w)
            ch = self._outpaint_data.get('canvas_height', h)
            self.setWindowTitle(f"Outpaint - {cw}x{ch}")
        else:
            self.setWindowTitle(f"Img2Img - {w}x{h}")

    def _update_preview(self):
        """이미지 프리뷰 업데이트 (마스크 오버레이 포함)"""
        if not self.pil_image:
            self.preview_label.clear()
            return

        preview_image = self.pil_image.copy().convert("RGBA")

        # 인페인트 모드: 마스크 영역에 파란 오버레이
        if self.mode == 'inpaint' and self.full_mask_pil:
            img_array = np.array(preview_image)
            mask_array = np.array(self.full_mask_pil.resize(preview_image.size, Image.Resampling.NEAREST))
            if len(mask_array.shape) > 2:
                mask_array = mask_array[:, :, 0]
            mask_indices = mask_array > 127
            img_array[mask_indices] = [100, 100, 255, 160]
            preview_image = Image.fromarray(img_array, 'RGBA')

        # 아웃페인팅 모드: 캔버스 + 마스크 오버레이
        if self.mode == 'auto_outpainting' and self._outpaint_data:
            canvas = self._outpaint_data.get('canvas_image')
            full_mask = self._outpaint_data.get('full_mask_image')
            if canvas and full_mask:
                canvas_rgba = canvas.convert("RGBA")
                canvas_array = np.array(canvas_rgba)
                mask_array = np.array(full_mask)
                if len(mask_array.shape) > 2:
                    mask_array = mask_array[:, :, 0]
                mask_indices = mask_array == 255
                canvas_array[mask_indices] = [100, 100, 255, 160]
                preview_image = Image.fromarray(canvas_array, 'RGBA')

        # QPixmap으로 변환하여 표시 (ImageQt 참조 유지)
        self._preview_qimage = ImageQt(preview_image)
        pixmap = QPixmap.fromImage(self._preview_qimage)

        # 프리뷰 라벨 크기에 맞게 스케일링
        label_size = self.preview_label.size()
        scaled_pixmap = pixmap.scaled(
            label_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.preview_label.setPixmap(scaled_pixmap)

    def resizeEvent(self, event):
        """윈도우 리사이즈 시 프리뷰 업데이트 (디바운스)"""
        super().resizeEvent(event)
        if self.pil_image:
            if not hasattr(self, '_resize_timer'):
                self._resize_timer = QTimer()
                self._resize_timer.setSingleShot(True)
                self._resize_timer.timeout.connect(self._update_preview)
            self._resize_timer.start(100)

    # ─── 프롬프트 초기화 ──────────────────────────────────────

    def initialize_from_history_item(self, history_item):
        """HistoryItem의 prompt_context에서 프롬프트 추출하여 설정"""
        prompt_context = getattr(history_item, 'prompt_context', None)

        if prompt_context:
            # Main prompt
            main_prompt = prompt_context.get('main_prompt', '')
            if not main_prompt:
                main_prompt = prompt_context.get('original_input', '')
            self.main_prompt_edit.setPlainText(main_prompt)

            # Negative prompt
            negative_prompt = prompt_context.get('negative_prompt', '')
            self.negative_prompt_edit.setPlainText(negative_prompt)

            # Character prompts
            char_prompts = prompt_context.get('character_prompts', [])
            if char_prompts:
                self._create_character_rows(char_prompts)
        else:
            # Fallback: generation_params에서 추출
            gen_params = getattr(history_item, 'generation_params', {})
            if gen_params:
                self.main_prompt_edit.setPlainText(gen_params.get('input', ''))
                self.negative_prompt_edit.setPlainText(gen_params.get('negative_prompt', ''))

    def initialize_from_main_ui(self, main_window):
        """메인 UI에서 현재 프롬프트와 캐릭터 설정을 캡처"""
        # Main prompt
        if hasattr(main_window, 'main_prompt_textedit'):
            self.main_prompt_edit.setPlainText(
                main_window.main_prompt_textedit.toPlainText()
            )

        # Negative prompt
        if hasattr(main_window, 'negative_prompt_textedit'):
            self.negative_prompt_edit.setPlainText(
                main_window.negative_prompt_textedit.toPlainText()
            )

        # Character prompts (NAI 모드) — 활성/비활성 모두 캡처
        try:
            if (hasattr(main_window, 'middle_section_controller') and
                    main_window.middle_section_controller):
                char_module = main_window.middle_section_controller.get_module_instance("CharacterModule")
                if char_module and hasattr(char_module, 'character_widgets'):
                    char_data = []
                    for w in char_module.character_widgets:
                        char_data.append({
                            'prompt': w.prompt_textbox.toPlainText(),
                            'uc': w.uc_textbox.toPlainText(),
                            'active': w.active_checkbox.isChecked(),
                        })
                    if char_data:
                        self._create_character_rows(char_data)
        except Exception as e:
            print(f"⚠️ [Img2ImgWindow] 캐릭터 프롬프트 캡처 실패: {e}")

    def _create_character_rows(self, character_prompts):
        """캐릭터 프롬프트 행 생성 (초기화용)"""
        # 기존 행 제거
        for row in self.character_rows:
            row['widget'].deleteLater()
        self.character_rows.clear()

        if not character_prompts:
            return

        for char_data in character_prompts:
            prompt_text = char_data.get('prompt', '') if isinstance(char_data, dict) else ''
            uc_text = char_data.get('uc', '') if isinstance(char_data, dict) else ''
            is_active = char_data.get('active', True) if isinstance(char_data, dict) else True
            self._insert_character_row(prompt_text, uc_text, is_active)

    def _add_character_row(self):
        """+ Add Character 버튼 → 빈 캐릭터 행 추가"""
        self._insert_character_row("", "", True)

    def _insert_character_row(self, prompt_text: str = "", uc_text: str = "", is_active: bool = True):
        """캐릭터 행 하나를 삽입"""
        idx = len(self.character_rows)

        row_widget = QWidget()
        row_widget.setObjectName("charRow")
        row_widget.setStyleSheet(f"""
            QWidget#charRow {{
                background-color: {_BG_PANEL};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        row_layout = QVBoxLayout(row_widget)
        row_layout.setContentsMargins(
            get_scaled_size(6), get_scaled_size(4),
            get_scaled_size(6), get_scaled_size(4)
        )
        row_layout.setSpacing(get_scaled_size(3))

        # 상단 행: 체크박스 + 라벨 + 제거 버튼
        header_row = QHBoxLayout()
        header_row.setSpacing(get_scaled_size(4))

        active_checkbox = QCheckBox(f"C{idx + 1}")
        active_checkbox.setChecked(is_active)
        active_checkbox.setStyleSheet(f"""
            QCheckBox {{
                font-size: {get_scaled_font_size(13)}px;
                color: {DARK_COLORS['text_primary']};
                font-weight: 600;
                spacing: {get_scaled_size(4)}px;
            }}
            QCheckBox::indicator {{
                width: {get_scaled_size(16)}px;
                height: {get_scaled_size(16)}px;
            }}
        """)
        header_row.addWidget(active_checkbox)
        header_row.addStretch(1)

        remove_btn = QPushButton("✕")
        remove_btn.setFixedSize(get_scaled_size(24), get_scaled_size(24))
        remove_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {DARK_COLORS['text_secondary']};
                border: none;
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                color: #FF6666;
            }}
        """)
        header_row.addWidget(remove_btn)
        row_layout.addLayout(header_row)

        # Prompt 입력
        prompt_edit = QTextEdit()
        prompt_edit.setAcceptRichText(False)
        prompt_edit.setPlaceholderText(f"Character {idx + 1} prompt")
        prompt_edit.setStyleSheet(self._textedit_style)
        prompt_edit.setMaximumHeight(get_scaled_size(65))
        prompt_edit.setPlainText(prompt_text)
        row_layout.addWidget(prompt_edit)

        # UC 입력
        uc_edit = QTextEdit()
        uc_edit.setAcceptRichText(False)
        uc_edit.setPlaceholderText(f"Character {idx + 1} UC")
        uc_edit.setStyleSheet(self._textedit_style)
        uc_edit.setMaximumHeight(get_scaled_size(45))
        uc_edit.setPlainText(uc_text)
        row_layout.addWidget(uc_edit)

        # stretch 앞에 삽입 (character_layout의 마지막 아이템은 stretch)
        insert_pos = self.character_layout.count() - 1
        if insert_pos < 0:
            insert_pos = 0
        self.character_layout.insertWidget(insert_pos, row_widget)

        row_data = {
            'widget': row_widget,
            'active_checkbox': active_checkbox,
            'prompt_edit': prompt_edit,
            'uc_edit': uc_edit,
            'remove_btn': remove_btn,
        }
        self.character_rows.append(row_data)

        # 제거 버튼 연결
        remove_btn.clicked.connect(lambda checked, rd=row_data: self._remove_character_row(rd))

    def _remove_character_row(self, row_data: dict):
        """캐릭터 행 제거 (최소 0개까지 허용)"""
        if row_data not in self.character_rows:
            return
        self.character_rows.remove(row_data)
        row_data['widget'].deleteLater()
        self._update_character_ids()

    def _update_character_ids(self):
        """캐릭터 번호 갱신 (C1, C2, ...)"""
        for i, row in enumerate(self.character_rows):
            row['active_checkbox'].setText(f"C{i + 1}")
            row['prompt_edit'].setPlaceholderText(f"Character {i + 1} prompt")
            row['uc_edit'].setPlaceholderText(f"Character {i + 1} UC")

    # ─── 생성 ────────────────────────────────────────────────

    def on_generate_clicked(self):
        """Generate 버튼 클릭 → overrides 수집 → 시그널 발행"""
        if not self.pil_image:
            return

        # 버튼 피드백
        self.generate_btn.setText("요청 전달됨")
        self.generate_btn.setStyleSheet(self.FEEDBACK_STYLE)
        self.generate_btn.setEnabled(False)

        params = self._collect_generation_params()

        # 배치 메타데이터 추가
        repeat_count = self.repeat_spin.value()
        if repeat_count > 1:
            params['img2img_batch_request'] = True
            params['img2img_batch_total'] = repeat_count
        params['img2img_batch_window_id'] = self.window_id

        print(f"[Img2ImgWindow #{self.window_id}] 생성 요청: mode={self.mode}, repeat={repeat_count}")
        self.generate_requested.emit(self.window_id, params)

        # 1초 후 버튼 복원
        QTimer.singleShot(1000, self._restore_button)

    def _restore_button(self):
        """Generate 버튼 상태 복원"""
        self.generate_btn.setText("🎨 Generate")
        self.generate_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.generate_btn.setEnabled(True)

    # ─── 배치 UI 제어 ──────────────────────────────────────

    def start_batch_ui(self, total: int):
        """배치 시작 시 UI 전환 (WindowManager가 호출)"""
        self.batch_progress.setMaximum(total)
        self.batch_progress.setValue(0)
        self.batch_progress.setFormat(f"0 / {total}")
        self.batch_progress.setVisible(True)
        self.cancel_btn.setVisible(True)
        self.repeat_spin.setEnabled(False)
        self.generate_btn.setEnabled(False)

    def update_batch_progress(self, current: int, total: int):
        """배치 진행률 업데이트 (WindowManager가 호출)"""
        self.batch_progress.setValue(current)
        self.batch_progress.setFormat(f"{current} / {total}")

    def finish_batch_ui(self):
        """배치 완료/취소 시 UI 복원 (WindowManager가 호출)"""
        self.batch_progress.setVisible(False)
        self.cancel_btn.setVisible(False)
        self.repeat_spin.setEnabled(True)
        self._restore_button()

    def _on_cancel_clicked(self):
        """중지 버튼 클릭 → 배치 취소 시그널"""
        print(f"[Img2ImgWindow #{self.window_id}] 배치 중지 요청")
        self.cancel_batch_requested.emit(self.window_id)

    def _collect_generation_params(self) -> dict:
        """현재 윈도우 상태에서 생성 파라미터 수집"""
        overrides = {
            'input': self.main_prompt_edit.toPlainText(),
            'negative_prompt': self.negative_prompt_edit.toPlainText(),
            'strength': self.strength_slider.value() / 100.0,
            'noise': self.noise_slider.value() / 100.0,
        }

        # 이미지 바이트
        if self.pil_image:
            byte_arr = io.BytesIO()
            self.pil_image.save(byte_arr, format='PNG')
            overrides['image_bytes'] = byte_arr.getvalue()
            overrides['width'] = self.pil_image.width
            overrides['height'] = self.pil_image.height

        # 모드별 처리
        if self.mode == 'inpaint' and (self.full_mask_pil or self.small_mask_pil):
            overrides['type'] = 'inpaint'
            # API 모드에 따라 적절한 마스크 선택
            api_mode = self.app_context.get_api_mode() if hasattr(self.app_context, 'get_api_mode') else 'NAI'
            mask_to_use = self.small_mask_pil if api_mode == 'NAI' else self.full_mask_pil
            if mask_to_use:
                # 이진 마스크 정리 (img2img_panel.py와 동일한 처리)
                if mask_to_use.mode != 'L':
                    mask_to_use = mask_to_use.convert('L')
                mask_array = np.array(mask_to_use)
                if len(mask_array.shape) > 2:
                    mask_array = mask_array[:, :, 0]
                mask_array = np.where(mask_array > 127, 255, 0).astype(np.uint8)
                mask_image_clean = Image.fromarray(mask_array, mode='L')
                mask_byte_arr = io.BytesIO()
                mask_image_clean.save(mask_byte_arr, format='PNG', compress_level=0, optimize=False)
                overrides['mask_bytes'] = mask_byte_arr.getvalue()

        elif self.mode == 'auto_outpainting' and self._outpaint_data:
            overrides['type'] = 'auto_outpainting'
            data = self._outpaint_data
            # 캔버스 바이트
            canvas_bytes = io.BytesIO()
            data['canvas_image'].save(canvas_bytes, format='PNG')
            overrides['outpaint_canvas_bytes'] = canvas_bytes.getvalue()
            # 마스크 바이트
            mask_bytes = io.BytesIO()
            data['small_mask_image'].save(mask_bytes, format='PNG', compress_level=0, optimize=False)
            overrides['outpaint_mask_bytes'] = mask_bytes.getvalue()
            overrides['outpaint_canvas_width'] = data['canvas_width']
            overrides['outpaint_canvas_height'] = data['canvas_height']
        else:
            overrides['type'] = 'img2img'

        # NAI 캐릭터 프롬프트 (sketchbook_character_prompts 키 사용)
        # 활성 상태인 캐릭터만 포함
        if self.character_rows:
            char_data = []
            for row in self.character_rows:
                if not row['active_checkbox'].isChecked():
                    continue
                prompt = row['prompt_edit'].toPlainText().strip()
                uc = row['uc_edit'].toPlainText().strip()
                if prompt:
                    char_data.append((prompt, uc))
            if char_data:
                overrides['sketchbook_character_prompts'] = char_data

        return overrides

    # ─── 마스크/아웃페인트 편집 ───────────────────────────────

    def _on_edit_mask_clicked(self):
        """Edit Mask 버튼 → InpaintWindow로 마스크 편집"""
        if not self.pil_image:
            return

        from ui.inpaint_window import InpaintWindow
        result = InpaintWindow.get_inpaint_data(self.pil_image, self.full_mask_pil, self)

        if result is None:
            return

        if 'full_mask_image' in result:
            self.mode = 'inpaint'
            self.full_mask_pil = result['full_mask_image']
            self.small_mask_pil = result['small_mask_image']
            self._outpaint_data = None
            self._update_preview()
            self._update_title()

    def _on_outpaint_clicked(self):
        """Outpaint 버튼 → OutpaintWindow → Accept 시 즉시 생성"""
        if not self.pil_image:
            return

        from ui.outpaint_window import OutpaintWindow
        result = OutpaintWindow.get_outpaint_data(self.pil_image, self)

        if result is None:
            return

        self.mode = 'auto_outpainting'
        self._outpaint_data = result
        self.full_mask_pil = None
        self.small_mask_pil = None
        self._update_preview()
        self._update_title()

        # Accept 후 즉시 생성
        self.on_generate_clicked()

    # ─── 창 닫기 ─────────────────────────────────────────────

    def closeEvent(self, event: QCloseEvent):
        """창 닫기 → 배치 취소 + 리소스 해제 + window_closing 시그널 발행"""
        print(f"🔄 [Img2ImgWindow] 창 #{self.window_id} 닫기")
        self.cancel_batch_requested.emit(self.window_id)
        self.window_closing.emit(self.window_id)
        # 이미지 리소스 해제
        self.pil_image = None
        self.full_mask_pil = None
        self.small_mask_pil = None
        self._outpaint_data = None
        self._preview_qimage = None
        self.preview_label.clear()
        self.deleteLater()
        event.accept()
