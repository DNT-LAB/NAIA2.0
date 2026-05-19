from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QSpinBox, QSlider, QCheckBox, QFrame, QGridLayout, QDoubleSpinBox,
    QRadioButton, QButtonGroup
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from legacy_desktop.ui.theme import DARK_COLORS
from legacy_desktop.ui.interactive.interactive_theme import FONT_FAMILY, COMMON_STYLES, get_scaled_size, get_scaled_font_size

class ComfyUIParameterPanel(QFrame):
    """
    ComfyUI 이미지 생성 파라미터 설정 패널
    FloatingControlBar의 '파라미터' 버튼 클릭 시 토글됨
    """

    # 파라미터 변경 시그널
    params_changed = pyqtSignal(dict)

    def __init__(self, parent=None, app_context=None):
        super().__init__(parent)
        self.setObjectName("comfyui_parameter_panel")
        self.app_context = app_context

        # 윈도우 스타일 설정 (팝업처럼 동작하지만 메인 윈도우 내부)
        self.setWindowFlags(Qt.WindowType.SubWindow | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAutoFillBackground(True)

        # 스타일 (검은색 배경)
        self.setStyleSheet(f"""
            QFrame#comfyui_parameter_panel {{
                background-color: rgb(13, 13, 13);
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(8)}px;
            }}
            QLabel {{
                color: #FFFFFF;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(13)}px;
                background-color: transparent;
            }}
            QComboBox {{
                background-color: rgb(26, 26, 26);
                color: #FFFFFF;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 4px;
                font-family: {FONT_FAMILY};
            }}
            QComboBox:hover {{
                border: 1px solid {DARK_COLORS['border_light']};
                background-color: rgb(36, 36, 36);
            }}
            QComboBox QAbstractItemView {{
                background-color: rgb(26, 26, 26);
                color: #FFFFFF;
                border: 1px solid {DARK_COLORS['border']};
                selection-background-color: {DARK_COLORS['accent_blue']};
                selection-color: #FFFFFF;
            }}
            QComboBox QAbstractItemView::item {{
                color: #FFFFFF;
                padding: 4px;
            }}
            QComboBox QAbstractItemView::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
                color: #FFFFFF;
            }}
            QSpinBox, QDoubleSpinBox {{
                background-color: rgb(26, 26, 26);
                color: #FFFFFF;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 4px;
                font-family: {FONT_FAMILY};
            }}
            QSpinBox:hover, QDoubleSpinBox:hover {{
                border: 1px solid {DARK_COLORS['border_light']};
                background-color: rgb(36, 36, 36);
            }}
            QSlider::groove:horizontal {{
                border: 1px solid {DARK_COLORS['border']};
                height: 6px;
                background: rgb(26, 26, 26);
                margin: 0px 0;
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {DARK_COLORS['accent_blue']};
                border: 1px solid {DARK_COLORS['accent_blue']};
                width: 14px;
                height: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }}
            QRadioButton {{
                color: #FFFFFF;
                font-family: {FONT_FAMILY};
                spacing: 6px;
                background-color: transparent;
            }}
            QRadioButton::indicator {{
                width: 16px;
                height: 16px;
            }}
            QRadioButton::indicator:unchecked {{
                border: 2px solid {DARK_COLORS['border']};
                border-radius: 8px;
                background-color: rgb(26, 26, 26);
            }}
            QRadioButton::indicator:checked {{
                border: 2px solid {DARK_COLORS['accent_blue']};
                border-radius: 8px;
                background-color: {DARK_COLORS['accent_blue']};
            }}
            QFrame {{
                background-color: transparent;
            }}
        """)

        # [179.5] 모델 잠금 상태 — locked_unknown 워크플로우에서 치환/조회 차단
        self._model_locked = False
        self._model_original_items = []
        self._gen_workflow_subscribed = False

        self._init_ui()
        self._subscribe_workflow_changes()
        self._refresh_initial_workflow_state()

    def disable_wheel_event(self, widget):
        """위젯의 마우스 휠 이벤트를 비활성화"""
        def wheelEvent(event):
            event.ignore()
        widget.wheelEvent = wheelEvent
        return widget

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(get_scaled_size(16), get_scaled_size(16), get_scaled_size(16), get_scaled_size(16))
        layout.setSpacing(get_scaled_size(12))

        # 1. 헤더 (ComfyUI Settings)
        header_layout = QHBoxLayout()
        header_lbl = QLabel("ComfyUI Settings")
        header_lbl.setStyleSheet(f"font-weight: bold; font-size: {get_scaled_font_size(14)}px;")
        header_layout.addWidget(header_lbl)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # 구분선
        self._add_divider(layout)

        # 2. 모델 선택 (Model)
        model_layout = QVBoxLayout()
        model_lbl = QLabel("Model")
        model_lbl.setStyleSheet(f"color: {DARK_COLORS['text_secondary']};")
        model_layout.addWidget(model_lbl)

        self.model_combo = self.disable_wheel_event(QComboBox())
        self.model_combo.setEditable(True)  # 직접 입력 가능
        # ComfyUI 모델 예시 (사용자가 직접 입력 가능)
        self.model_combo.addItems([
            "anima-preview.safetensors",
            "ponyDiffusionV6XL_v6StartWithThisOne.safetensors",
            "illustriousXL_v10.safetensors"
        ])
        self.model_combo.setFixedHeight(get_scaled_size(32))
        model_layout.addWidget(self.model_combo)
        layout.addLayout(model_layout)

        # 구분선
        self._add_divider(layout)

        # 3. 샘플링 모드 (EPS, V-Pred, ANIMA)
        sampling_mode_layout = QVBoxLayout()
        sampling_mode_lbl = QLabel("Sampling Mode")
        sampling_mode_lbl.setStyleSheet(f"color: {DARK_COLORS['text_secondary']};")
        sampling_mode_layout.addWidget(sampling_mode_lbl)

        # 라디오 버튼 그룹
        radio_layout = QHBoxLayout()
        self.sampling_mode_group = QButtonGroup(self)

        self.eps_radio = QRadioButton("EPS")
        self.v_pred_radio = QRadioButton("V-Pred")
        self.anima_radio = QRadioButton("ANIMA")

        self.sampling_mode_group.addButton(self.eps_radio, 0)
        self.sampling_mode_group.addButton(self.v_pred_radio, 1)
        self.sampling_mode_group.addButton(self.anima_radio, 2)

        # 기본값: EPS
        self.eps_radio.setChecked(True)

        radio_layout.addWidget(self.eps_radio)
        radio_layout.addWidget(self.v_pred_radio)
        radio_layout.addWidget(self.anima_radio)
        radio_layout.addStretch()

        sampling_mode_layout.addLayout(radio_layout)
        layout.addLayout(sampling_mode_layout)

        # 구분선
        self._add_divider(layout)

        # 4. 그리드 레이아웃 (Steps, CFG, Sampler, Scheduler)
        grid = QGridLayout()
        grid.setHorizontalSpacing(get_scaled_size(20))
        grid.setVerticalSpacing(get_scaled_size(16))

        # --- (0,0) Steps ---
        self.steps_spin = self.disable_wheel_event(QSpinBox())
        self.steps_spin.setRange(1, 150)
        self.steps_spin.setValue(30)  # ComfyUI 기본값
        self.steps_slider = QSlider(Qt.Orientation.Horizontal)
        self.steps_slider.setRange(1, 50)
        self.steps_slider.setValue(30)

        # 슬라이더-스핀박스 동기화
        self.steps_slider.valueChanged.connect(self.steps_spin.setValue)
        self.steps_spin.valueChanged.connect(self.steps_slider.setValue)

        grid.addLayout(self._create_slider_control("Steps", self.steps_spin, self.steps_slider), 0, 0)

        # --- (0,1) CFG Scale ---
        self.cfg_spin = self.disable_wheel_event(QDoubleSpinBox())
        self.cfg_spin.setRange(0.0, 30.0)
        self.cfg_spin.setSingleStep(0.1)
        self.cfg_spin.setValue(4.0)  # ComfyUI 기본값
        self.cfg_spin.setDecimals(1)

        self.cfg_slider = QSlider(Qt.Orientation.Horizontal)
        self.cfg_slider.setRange(0, 100)
        self.cfg_slider.setValue(40)

        # 동기화
        self.cfg_slider.valueChanged.connect(lambda v: self.cfg_spin.setValue(v / 10.0))
        self.cfg_spin.valueChanged.connect(lambda v: self.cfg_slider.setValue(int(v * 10)))

        grid.addLayout(self._create_slider_control("CFG Scale", self.cfg_spin, self.cfg_slider), 0, 1)

        # --- (0,2) Rescale CFG (ANIMA 전용) ---
        self.rescale_cfg_spin = self.disable_wheel_event(QDoubleSpinBox())
        self.rescale_cfg_spin.setRange(0.0, 1.0)
        self.rescale_cfg_spin.setSingleStep(0.01)
        self.rescale_cfg_spin.setValue(0.70)
        self.rescale_cfg_spin.setDecimals(2)

        self.rescale_cfg_slider = QSlider(Qt.Orientation.Horizontal)
        self.rescale_cfg_slider.setRange(0, 100)
        self.rescale_cfg_slider.setValue(70)

        # 동기화
        self.rescale_cfg_slider.valueChanged.connect(lambda v: self.rescale_cfg_spin.setValue(v / 100.0))
        self.rescale_cfg_spin.valueChanged.connect(lambda v: self.rescale_cfg_slider.setValue(int(v * 100)))

        self.rescale_cfg_layout = self._create_slider_control("Rescale CFG", self.rescale_cfg_spin, self.rescale_cfg_slider)
        self.rescale_cfg_container = QWidget()
        self.rescale_cfg_container.setLayout(self.rescale_cfg_layout)
        grid.addWidget(self.rescale_cfg_container, 0, 2)

        # 초기 숨김 (ANIMA 선택 시만 표시)
        self.rescale_cfg_container.setVisible(False)

        # 샘플링 모드 변경 시 Rescale CFG 가시성 제어
        self.sampling_mode_group.buttonClicked.connect(self._on_sampling_mode_changed)

        # --- (1,0) Sampler ---
        sampler_layout = QVBoxLayout()
        sampler_lbl = QLabel("Sampler")
        sampler_lbl.setStyleSheet(f"color: {DARK_COLORS['text_secondary']};")
        self.sampler_combo = self.disable_wheel_event(QComboBox())
        self.sampler_combo.addItems([
            "euler", "euler_ancestral", "heun", "heunpp2", "dpm_2", "dpm_2_ancestral",
            "lms", "dpm_fast", "dpm_adaptive", "dpmpp_2s_ancestral", "dpmpp_sde",
            "dpmpp_2m", "dpmpp_2m_sde", "ddim", "uni_pc", "uni_pc_bh2"
        ])
        # 기본값: euler_ancestral (인덱스 1)
        self.sampler_combo.setCurrentIndex(1)
        self.sampler_combo.setFixedHeight(get_scaled_size(30))

        sampler_layout.addWidget(sampler_lbl)
        sampler_layout.addWidget(self.sampler_combo)
        grid.addLayout(sampler_layout, 1, 0)

        # --- (1,1) Scheduler ---
        schedule_layout = QVBoxLayout()
        schedule_lbl = QLabel("Scheduler")
        schedule_lbl.setStyleSheet(f"color: {DARK_COLORS['text_secondary']};")
        self.schedule_combo = self.disable_wheel_event(QComboBox())
        self.schedule_combo.addItems([
            "normal", "karras", "exponential", "sgm_uniform", "simple", "ddim_uniform"
        ])
        # 기본값: simple (인덱스 4)
        self.schedule_combo.setCurrentIndex(4)
        self.schedule_combo.setFixedHeight(get_scaled_size(30))

        schedule_layout.addWidget(schedule_lbl)
        schedule_layout.addWidget(self.schedule_combo)
        grid.addLayout(schedule_layout, 1, 1)

        layout.addLayout(grid)

    def _create_slider_control(self, title, spin_widget, slider_widget):
        """슬라이더 컨트롤 그룹 생성 (Header[Title+Spin] + Slider)"""
        container = QVBoxLayout()
        container.setSpacing(get_scaled_size(6))

        # Header Row
        header = QHBoxLayout()
        lbl = QLabel(title)
        lbl.setStyleSheet(f"color: {DARK_COLORS['text_secondary']};")

        header.addWidget(lbl)
        header.addStretch()
        header.addWidget(spin_widget)

        container.addLayout(header)
        container.addWidget(slider_widget)

        return container

    def _add_divider(self, layout):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet(f"background-color: {COMMON_STYLES['input_border']}; height: 1px;")
        layout.addWidget(line)

    # ------------------------------------------------------------------
    # [179.5] 커스텀 워크플로우 잠금 — comfyui_workflow_changed 이벤트 연동
    # ------------------------------------------------------------------
    def _subscribe_workflow_changes(self):
        """AppContext의 comfyui_workflow_changed 이벤트를 구독 (idempotent)."""
        if self._gen_workflow_subscribed:
            return
        if self.app_context is None or not hasattr(self.app_context, 'subscribe'):
            return
        try:
            self.app_context.subscribe(
                "comfyui_workflow_changed",
                self._on_comfyui_workflow_changed,
            )
            self._gen_workflow_subscribed = True
        except Exception as e:
            print(f"⚠️ comfyui_workflow_changed 구독 실패: {e}")

    def _refresh_initial_workflow_state(self):
        """패널 생성 시점에 이미 사용자 워크플로우가 로드돼 있으면 잠금 상태를 동기화."""
        if self.app_context is None:
            return
        mgr = getattr(self.app_context, 'comfyui_workflow_manager', None)
        if mgr is None:
            return
        node_map = getattr(mgr, 'user_workflow_node_map', None) or {}
        has_custom = getattr(mgr, 'user_workflow', None) is not None
        self._on_comfyui_workflow_changed({
            "has_custom": has_custom,
            "model_compat": node_map.get("model_compat") if has_custom else None,
            "locked_loader_class": node_map.get("locked_loader_class"),
            "locked_model_display": node_map.get("locked_model_display"),
        })

    def _on_comfyui_workflow_changed(self, data):
        """이벤트 핸들러 — model_compat 값에 따라 model_combo 잠금 토글."""
        if not isinstance(data, dict):
            return
        if data.get("model_compat") == "locked_unknown":
            self._apply_model_lock(
                display=data.get("locked_model_display"),
                loader_class=data.get("locked_loader_class"),
            )
        else:
            self._release_model_lock()

    def _apply_model_lock(self, display=None, loader_class=None):
        """model_combo를 '[UNKNOWN]' 표시로 고정하고 편집/조회를 차단.

        [H1] locked → locked 전환 시에도 display/loader_class 가 갱신되도록
             early return 대신 '스냅샷은 최초 1회' + '표시는 매번 갱신' 구조.
        [L1] setEditable 토글 대신 lineEdit().setReadOnly 로 — setEditable(True↔False)
             반복은 내부 lineEdit 을 새로 만들어 validator/completer/eventFilter 를 잃게 됨.
        """
        display = display or "UNKNOWN"
        loader_class = loader_class or "Custom Loader"

        # 스냅샷은 최초 잠금 시에만 캡처 (locked → locked 전환에서 A 의 원본 보존)
        if not self._model_locked:
            self._model_original_items = [
                self.model_combo.itemText(i) for i in range(self.model_combo.count())
            ]

        self.model_combo.blockSignals(True)
        try:
            line_edit = self.model_combo.lineEdit()
            if line_edit is not None:
                line_edit.setReadOnly(True)
            self.model_combo.clear()
            self.model_combo.addItem(f"[UNKNOWN] {display}")
            self.model_combo.setCurrentIndex(0)
        finally:
            self.model_combo.blockSignals(False)
        self.model_combo.setEnabled(False)
        self.model_combo.setToolTip(
            f"이 워크플로우는 커스텀 로더({loader_class})를 사용합니다.\n"
            "체크포인트 변경 및 조회가 비활성화되어 있습니다.\n"
            "기본 워크플로우로 되돌리면 다시 활성화됩니다."
        )
        self._model_locked = True

    def _release_model_lock(self):
        """잠금 해제 — 원래 콤보 항목을 복원하고 편집 가능 상태로 되돌림."""
        if not self._model_locked:
            return
        self.model_combo.blockSignals(True)
        try:
            line_edit = self.model_combo.lineEdit()
            if line_edit is not None:
                line_edit.setReadOnly(False)
            self.model_combo.clear()
            if self._model_original_items:
                self.model_combo.addItems(self._model_original_items)
            if self.model_combo.count() > 0:
                self.model_combo.setCurrentIndex(0)
        finally:
            self.model_combo.blockSignals(False)
        self.model_combo.setEnabled(True)
        self.model_combo.setToolTip("")
        self._model_locked = False
        self._model_original_items = []

    def get_params(self):
        """현재 설정된 파라미터 반환"""
        # 샘플링 모드 확인
        if self.eps_radio.isChecked():
            sampling_mode = "eps"
            workflow_type = "checkpoint"
        elif self.v_pred_radio.isChecked():
            sampling_mode = "v_prediction"
            workflow_type = "checkpoint"
        elif self.anima_radio.isChecked():
            sampling_mode = "anima"
            workflow_type = "unet"
        else:
            sampling_mode = "eps"
            workflow_type = "checkpoint"

        result = {
            "model": self.model_combo.currentText(),
            "scheduler": self.schedule_combo.currentText(),
            "sampler": self.sampler_combo.currentText(),
            "steps": self.steps_spin.value(),
            "cfg_scale": self.cfg_spin.value(),
            "sampling_mode": sampling_mode,
            "workflow_type": workflow_type
        }

        # ANIMA 모드: Rescale CFG 값 추가
        if workflow_type == "unet":
            result["rescale_cfg"] = self.rescale_cfg_spin.value()

        return result

    def _on_sampling_mode_changed(self, button):
        """샘플링 모드 변경 시 Rescale CFG 가시성 제어"""
        is_anima = (button == self.anima_radio)
        self.rescale_cfg_container.setVisible(is_anima)

    def set_params(self, params):
        """외부에서 파라미터 설정"""
        if not params:
            return

        if "model" in params:
            # 콤보박스에 항목이 없으면 추가
            index = self.model_combo.findText(params["model"])
            if index == -1:
                self.model_combo.addItem(params["model"])
                self.model_combo.setCurrentText(params["model"])
            else:
                self.model_combo.setCurrentIndex(index)

        if "scheduler" in params:
            self.schedule_combo.setCurrentText(params["scheduler"])

        if "sampler" in params:
            self.sampler_combo.setCurrentText(params["sampler"])

        if "steps" in params:
            self.steps_spin.setValue(params["steps"])

        if "cfg_scale" in params:
            self.cfg_spin.setValue(params["cfg_scale"])

        # 샘플링 모드 설정
        if "sampling_mode" in params:
            sampling_mode = params["sampling_mode"]
            if sampling_mode == "eps":
                self.eps_radio.setChecked(True)
            elif sampling_mode == "v_prediction":
                self.v_pred_radio.setChecked(True)
            elif sampling_mode == "anima":
                self.anima_radio.setChecked(True)
            else:
                self.eps_radio.setChecked(True)

            # setChecked()는 buttonClicked 시그널을 발생시키지 않으므로 수동 가시성 업데이트
            is_anima = (sampling_mode == "anima")
            self.rescale_cfg_container.setVisible(is_anima)

        # Rescale CFG 값 복원
        if "rescale_cfg" in params:
            self.rescale_cfg_spin.setValue(params["rescale_cfg"])
