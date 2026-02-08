from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QSpinBox, QSlider, QCheckBox, QFrame, QGridLayout, QDoubleSpinBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from ui.theme import DARK_COLORS
from ui.interactive.interactive_theme import FONT_FAMILY, COMMON_STYLES, get_scaled_size, get_scaled_font_size

class ParameterPanel(QFrame):
    """
    이미지 생성 파라미터 설정 패널
    FloatingControlBar의 '파라미터' 버튼 클릭 시 토글됨
    """
    
    # 파라미터 변경 시그널
    params_changed = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("parameter_panel")

        # 윈도우 스타일 설정 (팝업처럼 동작하지만 메인 윈도우 내부)
        self.setWindowFlags(Qt.WindowType.SubWindow | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAutoFillBackground(True)  # 배경색 강제 적용
        
        # 스타일 (검은색 배경)
        self.setStyleSheet(f"""
            QFrame#parameter_panel {{
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
            QCheckBox {{
                color: #FFFFFF;
                font-family: {FONT_FAMILY};
                spacing: 6px;
                background-color: transparent;
            }}
            QFrame {{
                background-color: transparent;
            }}
        """)


        self._init_ui()

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
        
        # 1. 헤더 (Generation Settings)
        header_layout = QHBoxLayout()
        header_lbl = QLabel("Generation Settings")
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
        self.model_combo.addItems(["NAID4.5F", "NAID4.5C"])
        self.model_combo.setFixedHeight(get_scaled_size(32))
        model_layout.addWidget(self.model_combo)
        layout.addLayout(model_layout)
        
        # 구분선
        self._add_divider(layout)
        
        # 3. 그리드 레이아웃 (Steps, CFG, Rescale, Sampler, Schedule, VAR+)
        grid = QGridLayout()
        grid.setHorizontalSpacing(get_scaled_size(20))
        grid.setVerticalSpacing(get_scaled_size(16))
        
        # --- (0,0) Steps ---
        self.steps_spin = self.disable_wheel_event(QSpinBox())
        self.steps_spin.setRange(1, 150)
        self.steps_spin.setValue(28)
        self.steps_slider = QSlider(Qt.Orientation.Horizontal)
        self.steps_slider.setRange(1, 50) # 슬라이더는 정밀 조작용 (주로 쓰이는 범위)
        self.steps_slider.setValue(28)
        
        # 슬라이더-스핀박스 동기화
        self.steps_slider.valueChanged.connect(self.steps_spin.setValue)
        self.steps_spin.valueChanged.connect(self.steps_slider.setValue)
        
        grid.addLayout(self._create_slider_control("Steps", self.steps_spin, self.steps_slider), 0, 0)
        
        # --- (0,1) CFG Scale ---
        self.cfg_spin = self.disable_wheel_event(QDoubleSpinBox())
        self.cfg_spin.setRange(0.0, 30.0)
        self.cfg_spin.setSingleStep(0.1)
        self.cfg_spin.setValue(5.0)
        self.cfg_spin.setDecimals(1)
        
        self.cfg_slider = QSlider(Qt.Orientation.Horizontal)
        self.cfg_slider.setRange(0, 100) # 0.0 ~ 10.0 (x10)
        self.cfg_slider.setValue(50)
        
        # 동기화
        self.cfg_slider.valueChanged.connect(lambda v: self.cfg_spin.setValue(v / 10.0))
        self.cfg_spin.valueChanged.connect(lambda v: self.cfg_slider.setValue(int(v * 10)))
        
        grid.addLayout(self._create_slider_control("CFG Scale", self.cfg_spin, self.cfg_slider), 0, 1)
        
        # --- (1,0) CFG Rescale ---
        self.rescale_spin = self.disable_wheel_event(QDoubleSpinBox())
        self.rescale_spin.setRange(0.0, 1.0)
        self.rescale_spin.setSingleStep(0.05)
        self.rescale_spin.setValue(0.25)
        self.rescale_spin.setDecimals(2)

        self.rescale_slider = QSlider(Qt.Orientation.Horizontal)
        self.rescale_slider.setRange(0, 100) # 0.00 ~ 1.00 (x100)
        self.rescale_slider.setValue(25)
        
        # 동기화
        self.rescale_slider.valueChanged.connect(lambda v: self.rescale_spin.setValue(v / 100.0))
        self.rescale_spin.valueChanged.connect(lambda v: self.rescale_slider.setValue(int(v * 100)))
        
        grid.addLayout(self._create_slider_control("CFG Rescale", self.rescale_spin, self.rescale_slider), 1, 0)
        
        # --- (1,1) Sampler ---
        sampler_layout = QVBoxLayout()
        sampler_lbl = QLabel("Sampler")
        sampler_lbl.setStyleSheet(f"color: {DARK_COLORS['text_secondary']};")
        self.sampler_combo = self.disable_wheel_event(QComboBox())
        self.sampler_combo.addItems([
            "k_euler", "k_euler_ancestral", "k_dpmpp_2m",
            "k_dpmpp_2s_ancestral", "k_dpmpp_sde", "k_dpmpp_2m_sde", "ddim_v3"
        ])
        self.sampler_combo.setFixedHeight(get_scaled_size(30))
        
        sampler_layout.addWidget(sampler_lbl)
        sampler_layout.addWidget(self.sampler_combo)
        grid.addLayout(sampler_layout, 1, 1)
        
        # --- (2,0) Noise Schedule ---
        schedule_layout = QVBoxLayout()
        schedule_lbl = QLabel("Noise Schedule")
        schedule_lbl.setStyleSheet(f"color: {DARK_COLORS['text_secondary']};")
        self.schedule_combo = self.disable_wheel_event(QComboBox())
        self.schedule_combo.addItems(["karras", "native", "exponential", "polyexponential"])
        self.schedule_combo.setFixedHeight(get_scaled_size(30))
        
        schedule_layout.addWidget(schedule_lbl)
        schedule_layout.addWidget(self.schedule_combo)
        grid.addLayout(schedule_layout, 2, 0)
        
        # --- (2,1) VAR+ ---
        var_layout = QVBoxLayout()
        var_layout.setContentsMargins(0, get_scaled_size(20), 0, 0) # 상단 여백으로 줄 맞춤
        self.var_check = QCheckBox("VAR+")
        var_layout.addWidget(self.var_check)
        grid.addLayout(var_layout, 2, 1)
        
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

    def get_params(self):
        """현재 설정된 파라미터 반환"""
        return {
            "model": self.model_combo.currentText(),
            "scheduler": self.schedule_combo.currentText(),
            "sampler": self.sampler_combo.currentText(),
            "steps": self.steps_spin.value(),
            "cfg_scale": self.cfg_spin.value(),
            "cfg_rescale": self.rescale_spin.value(),
            "VAR+": self.var_check.isChecked()
        }

    def set_params(self, params):
        """외부에서 파라미터 설정"""
        if not params: return
        
        if "model" in params:
            self.model_combo.setCurrentText(params["model"])
        if "scheduler" in params:
            self.schedule_combo.setCurrentText(params["scheduler"])
        if "sampler" in params:
            self.sampler_combo.setCurrentText(params["sampler"])
        if "steps" in params:
            self.steps_spin.setValue(params["steps"])
        if "cfg_scale" in params:
            self.cfg_spin.setValue(params["cfg_scale"])
        if "cfg_rescale" in params:
            self.rescale_spin.setValue(params["cfg_rescale"])
        if "VAR+" in params:
            self.var_check.setChecked(params["VAR+"])
