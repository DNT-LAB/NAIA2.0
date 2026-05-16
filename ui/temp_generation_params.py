# ui/temp_generation_params.py
"""
임시 생성 창 파라미터 위젯

메인 윈도우의 생성 파라미터를 복제하여 임시 생성 창에서 사용할 수 있도록 합니다.
모든 위젯은 메인 UI와 완전히 분리된 별도 인스턴스입니다.
"""

import random

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QSpinBox, QDoubleSpinBox, QSlider, QLineEdit, QCheckBox
)
from PyQt6.QtCore import Qt
from ui.theme import DARK_COLORS, DARK_STYLES
from ui.scaling_manager import get_scaled_font_size, get_scaled_size


class TempGenerationParamsWidget(QWidget):
    """
    임시 생성 창용 생성 파라미터 위젯

    메인 윈도우와 독립적인 파라미터 세트를 제공하며,
    API 모드 및 NAI 모델에 따라 호환되는 UI를 표시합니다.
    """

    def __init__(self, app_context, parent=None):
        """
        파라미터 위젯 초기화

        Args:
            app_context: AppContext 인스턴스
            parent: 부모 위젯 (일반적으로 None)
        """
        super().__init__(parent)

        # AppContext 저장
        self.app_context = app_context

        # 현재 모드 추적
        self.current_api_mode = "NAI"
        self.current_nai_model = "NAID4.5F"

        # 위젯 딕셔너리 (나중에 접근 용이)
        self.widgets = {}

        # UI 초기화
        self.init_ui()

        print("[TempGenerationParamsWidget] 초기화 완료")

    def init_ui(self):
        """UI 초기화 - 수직 레이아웃으로 모든 파라미터 배치"""
        # 메인 레이아웃
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(
            get_scaled_size(12),
            get_scaled_size(12),
            get_scaled_size(12),
            get_scaled_size(12)
        )
        main_layout.setSpacing(get_scaled_size(8))

        # 배경색 설정
        self.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")

        # === 1. Model Selection ===
        self.widgets['model_row'] = self._create_model_row()
        main_layout.addWidget(self.widgets['model_row'])

        # === 2. Scheduler ===
        self.widgets['scheduler_row'] = self._create_scheduler_row()
        main_layout.addWidget(self.widgets['scheduler_row'])

        # === 3. Resolution ===
        self.widgets['resolution_row'] = self._create_resolution_row()
        main_layout.addWidget(self.widgets['resolution_row'])

        # === 4. Random Resolution ===
        self.widgets['random_resolution_row'] = self._create_checkbox_row(
            "random_resolution_checkbox",
            "랜덤 해상도"
        )
        main_layout.addWidget(self.widgets['random_resolution_row'])

        # === 5. Sampler ===
        self.widgets['sampler_row'] = self._create_sampler_row()
        main_layout.addWidget(self.widgets['sampler_row'])

        # === 6. Steps ===
        self.widgets['steps_row'] = self._create_steps_row()
        main_layout.addWidget(self.widgets['steps_row'])

        # === 7. CFG Scale ===
        self.widgets['cfg_scale_row'] = self._create_cfg_scale_row()
        main_layout.addWidget(self.widgets['cfg_scale_row'])

        # === 8. CFG Rescale (NAI only) ===
        self.widgets['cfg_rescale_row'] = self._create_cfg_rescale_row()
        main_layout.addWidget(self.widgets['cfg_rescale_row'])

        # === 9. Seed ===
        self.widgets['seed_row'] = self._create_seed_row()
        main_layout.addWidget(self.widgets['seed_row'])

        # === 10. Seed Fix Checkbox ===
        self.widgets['seed_fix_row'] = self._create_checkbox_row(
            "seed_fix_checkbox",
            "시드 고정"
        )
        main_layout.addWidget(self.widgets['seed_fix_row'])

        # === 11. Auto Fit Resolution ===
        self.widgets['auto_fit_resolution_row'] = self._create_checkbox_row(
            "auto_fit_resolution_checkbox",
            "자동 해상도 맞춤"
        )
        main_layout.addWidget(self.widgets['auto_fit_resolution_row'])

        # === 12. NAI Options (NAI only) ===
        self.widgets['nai_options_row'] = self._create_nai_options_row()
        main_layout.addWidget(self.widgets['nai_options_row'])

        # === 13. WEBUI Hires-fix (WEBUI only) ===
        self.widgets['hires_options_widget'] = self._create_hires_options()
        main_layout.addWidget(self.widgets['hires_options_widget'])

        # Temp Label
        label = QLabel("임시 생성은 구현중인 기능입니다. SEQ, PE, CP등 미지원")
        label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(15)}px;
            }}
        """)

        # Stretch at bottom
        main_layout.addStretch()

        # 초기 UI 상태 설정 (NAI 모드 기본값)
        self.update_ui_for_mode(self.current_api_mode, self.current_nai_model)

        print("[TempGenerationParamsWidget] UI 구성 완료")

    # ========================================
    # Row Creation Methods
    # ========================================

    def _create_model_row(self) -> QWidget:
        """모델 선택 행 생성"""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(8))

        # Label
        label = QLabel("모델 선택:")
        label.setFixedWidth(get_scaled_size(120))
        label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        # ComboBox
        self.model_combo = QComboBox()
        self.model_combo.addItems([
            "NAID4.5F",
            "NAID4.5C",
            "NAID4.0F",
            "NAID4.0C",
            "NAID3"
        ])
        self.model_combo.setStyleSheet(DARK_STYLES['compact_combobox'])

        # 모델 변경 시 NAI 체크박스 상태 업데이트
        self.model_combo.currentTextChanged.connect(self._update_nai_checkbox_states)

        layout.addWidget(label)
        layout.addWidget(self.model_combo, stretch=1)

        return row

    def _create_scheduler_row(self) -> QWidget:
        """스케줄러 선택 행 생성"""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(8))

        # Label
        label = QLabel("스케줄러:")
        label.setFixedWidth(get_scaled_size(120))
        label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        # ComboBox
        self.scheduler_combo = QComboBox()
        self.scheduler_combo.addItems([
            "native",
            "karras",
            "exponential",
            "polyexponential"
        ])
        self.scheduler_combo.setStyleSheet(DARK_STYLES['compact_combobox'])

        layout.addWidget(label)
        layout.addWidget(self.scheduler_combo, stretch=1)

        return row

    def _create_resolution_row(self) -> QWidget:
        """해상도 선택 행 생성"""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(8))

        # Label
        label = QLabel("해상도:")
        label.setFixedWidth(get_scaled_size(120))
        label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        # ComboBox
        self.resolution_combo = QComboBox()
        # 기본 해상도 목록 (실제 메인 윈도우와 동기화 필요)
        self.resolution_combo.addItems([
            "832x1216 (Portrait)",
            "1024x1024 (Square)",
            "1216x832 (Landscape)"
        ])
        self.resolution_combo.setStyleSheet(DARK_STYLES['compact_combobox'])

        layout.addWidget(label)
        layout.addWidget(self.resolution_combo, stretch=1)

        return row

    def _create_sampler_row(self) -> QWidget:
        """샘플러 선택 행 생성"""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(8))

        # Label
        label = QLabel("샘플러:")
        label.setFixedWidth(get_scaled_size(120))
        label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        # ComboBox
        self.sampler_combo = QComboBox()
        self.sampler_combo.addItems([
            "k_euler",
            "k_euler_ancestral",
            "k_dpmpp_2s_ancestral",
            "k_dpmpp_sde",
            "k_dpmpp_2m"
        ])
        self.sampler_combo.setStyleSheet(DARK_STYLES['compact_combobox'])

        layout.addWidget(label)
        layout.addWidget(self.sampler_combo, stretch=1)

        return row

    def _create_steps_row(self) -> QWidget:
        """Steps 설정 행 생성"""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(8))

        # Label
        label = QLabel("Steps:")
        label.setFixedWidth(get_scaled_size(120))
        label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        # SpinBox
        self.steps_spinbox = QSpinBox()
        self.steps_spinbox.setRange(1, 150)
        self.steps_spinbox.setValue(28)
        self.steps_spinbox.setStyleSheet(DARK_STYLES['compact_spinbox'])

        layout.addWidget(label)
        layout.addWidget(self.steps_spinbox, stretch=1)

        return row

    def _create_cfg_scale_row(self) -> QWidget:
        """CFG Scale 슬라이더 행 생성"""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(8))

        # Label
        label = QLabel("CFG Scale:")
        label.setFixedWidth(get_scaled_size(120))
        label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        # Slider
        self.cfg_scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.cfg_scale_slider.setRange(10, 100)  # 1.0 ~ 10.0 (scaled by 10)
        self.cfg_scale_slider.setValue(50)  # 5.0
        self.cfg_scale_slider.setStyleSheet(DARK_STYLES['compact_slider'])

        # Value Label
        self.cfg_scale_value_label = QLabel("5.0")
        self.cfg_scale_value_label.setFixedWidth(get_scaled_size(50))
        self.cfg_scale_value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.cfg_scale_value_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_secondary']};
            }}
        """)

        # Connect slider to label
        self.cfg_scale_slider.valueChanged.connect(
            lambda v: self.cfg_scale_value_label.setText(f"{v / 10.0:.1f}")
        )

        layout.addWidget(label)
        layout.addWidget(self.cfg_scale_slider, stretch=1)
        layout.addWidget(self.cfg_scale_value_label)

        return row

    def _create_cfg_rescale_row(self) -> QWidget:
        """CFG Rescale 슬라이더 행 생성 (NAI only)"""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(8))

        # Label
        label = QLabel("CFG Rescale:")
        label.setFixedWidth(get_scaled_size(120))
        label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        # Slider
        self.cfg_rescale_slider = QSlider(Qt.Orientation.Horizontal)
        self.cfg_rescale_slider.setRange(0, 100)  # 0.0 ~ 1.0 (scaled by 100)
        self.cfg_rescale_slider.setValue(0)  # 0.0
        self.cfg_rescale_slider.setStyleSheet(DARK_STYLES['compact_slider'])

        # Value Label
        self.cfg_rescale_value_label = QLabel("0.00")
        self.cfg_rescale_value_label.setFixedWidth(get_scaled_size(50))
        self.cfg_rescale_value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.cfg_rescale_value_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_secondary']};
            }}
        """)

        # Connect slider to label
        self.cfg_rescale_slider.valueChanged.connect(
            lambda v: self.cfg_rescale_value_label.setText(f"{v / 100.0:.2f}")
        )

        layout.addWidget(label)
        layout.addWidget(self.cfg_rescale_slider, stretch=1)
        layout.addWidget(self.cfg_rescale_value_label)

        return row

    def _create_seed_row(self) -> QWidget:
        """Seed 입력 행 생성"""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(8))

        # Label
        label = QLabel("Seed:")
        label.setFixedWidth(get_scaled_size(120))
        label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        # LineEdit
        self.seed_input = QLineEdit()
        self.seed_input.setText("0")
        self.seed_input.setPlaceholderText("0 = 랜덤")
        self.seed_input.setStyleSheet(DARK_STYLES['compact_lineedit'])

        layout.addWidget(label)
        layout.addWidget(self.seed_input, stretch=1)

        return row

    def _create_checkbox_row(self, checkbox_name: str, checkbox_text: str) -> QWidget:
        """체크박스 행 생성 (일반 패턴)"""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(8))

        # Spacer (label width만큼 띄우기)
        spacer = QLabel("")
        spacer.setFixedWidth(get_scaled_size(120))

        # Checkbox
        checkbox = QCheckBox(checkbox_text)
        checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])

        # Store checkbox reference
        setattr(self, checkbox_name, checkbox)

        layout.addWidget(spacer)
        layout.addWidget(checkbox, stretch=1)

        return row

    def _create_nai_options_row(self) -> QWidget:
        """NAI 옵션 체크박스 행 생성 (SMEA, DYN, VAR+, DECRISP)"""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(8))

        # Label
        label = QLabel("NAI 옵션:")
        label.setFixedWidth(get_scaled_size(120))
        label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        # Checkbox container
        checkbox_container = QWidget()
        checkbox_layout = QHBoxLayout(checkbox_container)
        checkbox_layout.setContentsMargins(0, 0, 0, 0)
        checkbox_layout.setSpacing(get_scaled_size(12))

        # Create checkboxes
        self.advanced_checkboxes = {}
        for option in ["SMEA", "DYN", "VAR+", "DECRISP"]:
            checkbox = QCheckBox(option)
            checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
            self.advanced_checkboxes[option] = checkbox
            checkbox_layout.addWidget(checkbox)

        checkbox_layout.addStretch()

        layout.addWidget(label)
        layout.addWidget(checkbox_container, stretch=1)

        return row

    def _create_hires_options(self) -> QWidget:
        """WEBUI Hires-fix 옵션 생성 (여러 행)"""
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(get_scaled_size(8))

        # === Enable Hires-fix ===
        enable_row = QWidget()
        enable_layout = QHBoxLayout(enable_row)
        enable_layout.setContentsMargins(0, 0, 0, 0)

        spacer = QLabel("")
        spacer.setFixedWidth(get_scaled_size(120))

        self.enable_hr_checkbox = QCheckBox("Hires-fix 활성화")
        self.enable_hr_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])

        enable_layout.addWidget(spacer)
        enable_layout.addWidget(self.enable_hr_checkbox, stretch=1)

        container_layout.addWidget(enable_row)

        # === Hires Scale ===
        scale_row = QWidget()
        scale_layout = QHBoxLayout(scale_row)
        scale_layout.setContentsMargins(0, 0, 0, 0)
        scale_layout.setSpacing(get_scaled_size(8))

        scale_label = QLabel("  Scale:")
        scale_label.setFixedWidth(get_scaled_size(120))
        scale_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_secondary']};
            }}
        """)

        self.hr_scale_spinbox = QDoubleSpinBox()
        self.hr_scale_spinbox.setRange(1.0, 4.0)
        self.hr_scale_spinbox.setSingleStep(0.1)
        self.hr_scale_spinbox.setValue(2.0)
        self.hr_scale_spinbox.setStyleSheet(DARK_STYLES['compact_spinbox'])

        scale_layout.addWidget(scale_label)
        scale_layout.addWidget(self.hr_scale_spinbox, stretch=1)

        container_layout.addWidget(scale_row)

        # === Hires Upscaler ===
        upscaler_row = QWidget()
        upscaler_layout = QHBoxLayout(upscaler_row)
        upscaler_layout.setContentsMargins(0, 0, 0, 0)
        upscaler_layout.setSpacing(get_scaled_size(8))

        upscaler_label = QLabel("  Upscaler:")
        upscaler_label.setFixedWidth(get_scaled_size(120))
        upscaler_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_secondary']};
            }}
        """)

        self.hr_upscaler_combo = QComboBox()
        self.hr_upscaler_combo.addItems([
            "Latent",
            "Latent (antialiased)",
            "Latent (bicubic)",
            "Latent (bicubic antialiased)",
            "Latent (nearest)",
            "Latent (nearest-exact)",
            "Lanczos",
            "Nearest",
            "ESRGAN",
        ])
        self.hr_upscaler_combo.setCurrentText("Latent (nearest-exact)")
        self.hr_upscaler_combo.setStyleSheet(DARK_STYLES['compact_combobox'])

        upscaler_layout.addWidget(upscaler_label)
        upscaler_layout.addWidget(self.hr_upscaler_combo, stretch=1)

        container_layout.addWidget(upscaler_row)

        # === Denoising Strength ===
        denoise_row = QWidget()
        denoise_layout = QHBoxLayout(denoise_row)
        denoise_layout.setContentsMargins(0, 0, 0, 0)
        denoise_layout.setSpacing(get_scaled_size(8))

        denoise_label = QLabel("  Denoise:")
        denoise_label.setFixedWidth(get_scaled_size(120))
        denoise_label.setStyleSheet(upscaler_label.styleSheet())

        self.denoising_strength_spinbox = QDoubleSpinBox()
        self.denoising_strength_spinbox.setRange(0.0, 1.0)
        self.denoising_strength_spinbox.setSingleStep(0.01)
        self.denoising_strength_spinbox.setDecimals(2)
        self.denoising_strength_spinbox.setValue(0.5)
        self.denoising_strength_spinbox.setStyleSheet(DARK_STYLES['compact_spinbox'])

        denoise_layout.addWidget(denoise_label)
        denoise_layout.addWidget(self.denoising_strength_spinbox, stretch=1)

        container_layout.addWidget(denoise_row)

        # === Hires Steps ===
        hires_steps_row = QWidget()
        hires_steps_layout = QHBoxLayout(hires_steps_row)
        hires_steps_layout.setContentsMargins(0, 0, 0, 0)
        hires_steps_layout.setSpacing(get_scaled_size(8))

        hires_steps_label = QLabel("  HR Steps:")
        hires_steps_label.setFixedWidth(get_scaled_size(120))
        hires_steps_label.setStyleSheet(upscaler_label.styleSheet())

        self.hires_steps_spinbox = QSpinBox()
        self.hires_steps_spinbox.setRange(0, 150)
        self.hires_steps_spinbox.setValue(10)
        self.hires_steps_spinbox.setStyleSheet(DARK_STYLES['compact_spinbox'])

        hires_steps_layout.addWidget(hires_steps_label)
        hires_steps_layout.addWidget(self.hires_steps_spinbox, stretch=1)

        container_layout.addWidget(hires_steps_row)

        # === Hires CFG ===
        hr_cfg_row = QWidget()
        hr_cfg_layout = QHBoxLayout(hr_cfg_row)
        hr_cfg_layout.setContentsMargins(0, 0, 0, 0)
        hr_cfg_layout.setSpacing(get_scaled_size(8))

        hr_cfg_label = QLabel("  HR CFG:")
        hr_cfg_label.setFixedWidth(get_scaled_size(120))
        hr_cfg_label.setStyleSheet(upscaler_label.styleSheet())

        self.hr_cfg_spinbox = QDoubleSpinBox()
        self.hr_cfg_spinbox.setRange(0.0, 30.0)
        self.hr_cfg_spinbox.setSingleStep(0.1)
        self.hr_cfg_spinbox.setDecimals(1)
        self.hr_cfg_spinbox.setValue(7.0)
        self.hr_cfg_spinbox.setStyleSheet(DARK_STYLES['compact_spinbox'])

        hr_cfg_layout.addWidget(hr_cfg_label)
        hr_cfg_layout.addWidget(self.hr_cfg_spinbox, stretch=1)

        container_layout.addWidget(hr_cfg_row)

        return container

    # ========================================
    # Public Methods
    # ========================================

    def set_initial_values(self, main_window):
        """
        메인 윈도우에서 현재 파라미터 값을 복사

        Args:
            main_window: ModernMainWindow 인스턴스
        """
        print("[TempGenerationParamsWidget] 메인 윈도우에서 초기값 복사 중...")

        try:
            # 🆕 현재 API 모드 가져오기
            if hasattr(main_window, 'app_context'):
                current_mode = main_window.app_context.get_api_mode()
                current_model = main_window.model_combo.currentText()

                # UI 업데이트 (모드별 위젯 표시/숨김)
                self.update_ui_for_mode(current_mode, current_model)
                print(f"[TempGenerationParamsWidget] API 모드: {current_mode}, NAI 모델: {current_model}")
            # Model
            self.model_combo.setCurrentText(main_window.model_combo.currentText())

            # Scheduler
            self.scheduler_combo.setCurrentText(main_window.scheduler_combo.currentText())

            # Resolution
            self.resolution_combo.setCurrentText(main_window.resolution_combo.currentText())

            # Random Resolution
            self.random_resolution_checkbox.setChecked(
                main_window.random_resolution_checkbox.isChecked()
            )

            # Sampler
            self.sampler_combo.setCurrentText(main_window.sampler_combo.currentText())

            # Steps
            self.steps_spinbox.setValue(main_window.steps_spinbox.value())

            # CFG Scale
            self.cfg_scale_slider.setValue(main_window.cfg_scale_slider.value())

            # CFG Rescale
            self.cfg_rescale_slider.setValue(main_window.cfg_rescale_slider.value())

            # Seed
            self.seed_input.setText(main_window.seed_input.text())

            # Seed Fix
            self.seed_fix_checkbox.setChecked(main_window.seed_fix_checkbox.isChecked())

            # Auto Fit Resolution
            self.auto_fit_resolution_checkbox.setChecked(
                main_window.auto_fit_resolution_checkbox.isChecked()
            )

            # NAI Options
            for option, checkbox in self.advanced_checkboxes.items():
                if option in main_window.advanced_checkboxes:
                    checkbox.setChecked(
                        main_window.advanced_checkboxes[option].isChecked()
                    )

            # WEBUI Hires-fix
            if hasattr(main_window, 'enable_hr_checkbox'):
                self.enable_hr_checkbox.setChecked(
                    main_window.enable_hr_checkbox.isChecked()
                )
                self.hr_scale_spinbox.setValue(
                    main_window.hr_scale_spinbox.value()
                )
                if hasattr(main_window, 'hr_upscaler_combo'):
                    upscaler_items = [
                        main_window.hr_upscaler_combo.itemText(i)
                        for i in range(main_window.hr_upscaler_combo.count())
                    ]
                    if upscaler_items:
                        self.hr_upscaler_combo.clear()
                        self.hr_upscaler_combo.addItems(upscaler_items)
                    self.hr_upscaler_combo.setCurrentText(
                        main_window.hr_upscaler_combo.currentText()
                    )
                if hasattr(main_window, 'denoising_strength_spinbox'):
                    self.denoising_strength_spinbox.setValue(
                        main_window.denoising_strength_spinbox.value()
                    )
                if hasattr(main_window, 'hires_steps_spinbox'):
                    self.hires_steps_spinbox.setValue(
                        main_window.hires_steps_spinbox.value()
                    )
                if hasattr(main_window, 'hr_cfg_spinbox'):
                    self.hr_cfg_spinbox.setValue(
                        main_window.hr_cfg_spinbox.value()
                    )

            print("[TempGenerationParamsWidget] 초기값 복사 완료")

        except Exception as e:
            print(f"[TempGenerationParamsWidget] 초기값 복사 중 오류: {e}")

    def collect_parameters(self, roll_random_seed: bool = False) -> dict:
        """
        현재 UI 상태를 파라미터 딕셔너리로 수집

        Returns:
            dict: 생성 파라미터 딕셔너리
        """
        params = {}

        # Model
        params['model'] = self.model_combo.currentText()

        # Scheduler
        params['noise_schedule'] = self.scheduler_combo.currentText()

        # Resolution
        resolution_text = self.resolution_combo.currentText()
        # "832x1216 (Portrait)" → (832, 1216) 파싱 필요
        if 'x' in resolution_text:
            try:
                width_str, height_str = resolution_text.split('x')
                width = int(width_str.strip())
                height = int(height_str.split()[0].strip())  # Remove " (Portrait)"
                params['width'] = width
                params['height'] = height
            except:
                params['width'] = 832
                params['height'] = 1216
        else:
            params['width'] = 832
            params['height'] = 1216

        # Random Resolution
        params['random_resolution'] = self.random_resolution_checkbox.isChecked()

        # Sampler
        params['sampler'] = self.sampler_combo.currentText()

        # Steps
        params['steps'] = self.steps_spinbox.value()

        # CFG Scale (slider value / 10)
        params['scale'] = self.cfg_scale_slider.value() / 10.0

        # CFG Rescale (slider value / 100)
        params['cfg_rescale'] = self.cfg_rescale_slider.value() / 100.0

        # Seed Fix
        params['seed_fix'] = self.seed_fix_checkbox.isChecked()

        # Seed
        if params['seed_fix']:
            try:
                seed_value = int(self.seed_input.text())
                if seed_value < 0:
                    seed_value = 0
            except Exception:
                seed_value = 0
                self.seed_input.setText("0")
        else:
            if roll_random_seed:
                seed_value = random.randint(0, 9999999999)
                self.seed_input.setText(str(seed_value))
            else:
                try:
                    seed_value = int(self.seed_input.text())
                    if seed_value < 0:
                        seed_value = 0
                except Exception:
                    seed_value = 0
        params['seed'] = seed_value

        # Auto Fit Resolution
        params['auto_fit_resolution'] = self.auto_fit_resolution_checkbox.isChecked()

        # NAI Options
        params['sm'] = self.advanced_checkboxes['SMEA'].isChecked()
        params['sm_dyn'] = self.advanced_checkboxes['DYN'].isChecked()
        params['variety_plus'] = self.advanced_checkboxes['VAR+'].isChecked()
        params['decrisper'] = self.advanced_checkboxes['DECRISP'].isChecked()

        # WEBUI Hires-fix
        params['enable_hr'] = self.enable_hr_checkbox.isChecked()
        params['hr_scale'] = self.hr_scale_spinbox.value()
        params['hr_upscaler'] = self.hr_upscaler_combo.currentText()
        params['denoising_strength'] = self.denoising_strength_spinbox.value()
        params['hires_steps'] = self.hires_steps_spinbox.value()
        params['hr_cfg'] = self.hr_cfg_spinbox.value()

        return params

    def update_ui_for_mode(self, api_mode: str, nai_model: str = None):
        """
        API 모드 및 NAI 모델에 따라 UI 표시/숨김

        Args:
            api_mode: "NAI", "WEBUI", "COMFYUI"
            nai_model: NAI 모델 (예: "NAID4.5F", "NAID3")
        """
        self.current_api_mode = api_mode
        if nai_model:
            self.current_nai_model = nai_model

        print(f"[TempGenerationParamsWidget] UI 업데이트: mode={api_mode}, model={nai_model}")

        # NAI-specific widgets
        is_nai = (api_mode == "NAI")
        self.widgets['cfg_rescale_row'].setVisible(is_nai)
        self.widgets['nai_options_row'].setVisible(is_nai)

        # WEBUI-specific widgets
        is_webui = (api_mode == "WEBUI")
        self.widgets['hires_options_widget'].setVisible(is_webui)

        print(f"[TempGenerationParamsWidget] NAI 위젯: {'표시' if is_nai else '숨김'}, "
              f"WEBUI 위젯: {'표시' if is_webui else '숨김'}")

        # NAI 모드일 때 모델에 따른 체크박스 상태 업데이트
        if is_nai and nai_model:
            self._update_nai_checkbox_states(nai_model)

    def _update_nai_checkbox_states(self, model_name: str):
        """
        NAI 모델에 따라 체크박스 활성화/비활성화 및 색상 변경

        NAID3: 모든 옵션 활성화
        NAID4.x: SMEA, DYN, DECRISP 비활성화 및 회색 처리

        Args:
            model_name: NAI 모델명 (예: "NAID3", "NAID4.0F", "NAID4.5F")
        """
        if not hasattr(self, 'advanced_checkboxes'):
            return

        is_naid3 = (model_name == "NAID3")

        # SMEA, DYN, DECRISP는 NAID3에서만 활성화
        restricted_options = ["SMEA", "DYN", "DECRISP"]

        for option_name, checkbox in self.advanced_checkboxes.items():
            if option_name in restricted_options:
                if is_naid3:
                    # NAID3: 활성화, 흰색
                    checkbox.setEnabled(True)
                    checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
                else:
                    # NAID4.x: 비활성화, 회색, 체크 해제
                    checkbox.setEnabled(False)
                    checkbox.setChecked(False)

                    # 회색 스타일 생성
                    gray_style = DARK_STYLES['dark_checkbox'].replace(
                        f"color: {DARK_COLORS['text_primary']}",
                        f"color: {DARK_COLORS['text_disabled']}"
                    )
                    checkbox.setStyleSheet(gray_style)
            else:
                # VAR+는 항상 활성화
                checkbox.setEnabled(True)
                checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])

        print(f"[TempGenerationParamsWidget] NAI 체크박스 상태 업데이트: {model_name} "
              f"(SMEA/DYN/DECRISP {'활성화' if is_naid3 else '비활성화'})")
