from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFrame, QCheckBox, QLabel, QMenu, QWidgetAction
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QEvent, QPoint
from legacy_desktop.ui.theme import DARK_COLORS
from legacy_desktop.ui.interactive.interactive_theme import COMMON_STYLES, FONT_FAMILY
from legacy_desktop.ui.scaling_manager import get_scaled_size, get_scaled_font_size

class FloatingControlBar(QWidget):
    # 해상도 목록
    RESOLUTIONS = [
        "1024 x 1024", "960 x 1088", "896 x 1152", "832 x 1216",
        "1088 x 960", "1152 x 896", "1216 x 832"
    ]

    # 시그널 정의
    random_clicked = pyqtSignal()
    random_generate_clicked = pyqtSignal()
    random_clicked = pyqtSignal()
    random_generate_clicked = pyqtSignal()
    generate_clicked = pyqtSignal()
    sidebar_toggled = pyqtSignal(bool) # 패널 토글 시그널
    float_pin_toggled = pyqtSignal(bool) # 플로팅 고정 토글 시그널
    tags_clicked = pyqtSignal() # 태그 뷰어 버튼 시그널
    
    def __init__(self, parent=None, app_context=None):
        super().__init__(parent)
        self.app_context = app_context
        self.current_mode = app_context.current_api_mode if app_context else "NAI"
        self._init_ui()
        
    def _init_ui(self):
        # 메인 컨테이너
        self.container = QFrame(self)
        self.container.setObjectName("control_bar")
        self.container.setStyleSheet(f"""
            #control_bar {{
                background-color: rgba(30, 30, 30, 0.95);
                border: 1px solid {COMMON_STYLES['input_border']};
                border-radius: {get_scaled_size(12)}px;
            }}
            QPushButton {{
                background-color: {COMMON_STYLES['input_bg']};
                color: {COMMON_STYLES['text_primary']};
                border: 1px solid {COMMON_STYLES['input_border']};
                border-radius: 6px;
                padding: {get_scaled_size(8)}px {get_scaled_size(12)}px;
                font-family: {FONT_FAMILY};
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
            QCheckBox {{
                color: {COMMON_STYLES['text_primary']};
                font-family: {FONT_FAMILY};
                spacing: 6px;
            }}
        """)
        
        layout = QHBoxLayout(self.container)
        layout.setContentsMargins(
            get_scaled_size(16), get_scaled_size(10), 
            get_scaled_size(16), get_scaled_size(10)
        )
        layout.setSpacing(get_scaled_size(12))
        
        # 0. [ 패널 숨기기 ] (좌측 패널 토글)
        self.chk_sidebar = QCheckBox("패널 숨기기")
        self.chk_sidebar.setToolTip("좌측 설정 패널을 숨깁니다.")
        self.chk_sidebar.toggled.connect(self.sidebar_toggled.emit)
        self.chk_sidebar.toggled.connect(self.sidebar_toggled.emit)
        layout.addWidget(self.chk_sidebar)

        # 0-1. [ 플로팅 고정 ] (토글)
        self.chk_float_pin = QCheckBox("플로팅 고정")
        self.chk_float_pin.setToolTip("플로팅 패널 위치를 자동으로 정렬합니다.")
        self.chk_float_pin.setChecked(True) # 기본값: 체크됨
        self.chk_float_pin.toggled.connect(self.float_pin_toggled.emit)
        layout.addWidget(self.chk_float_pin)

        # 구분선
        line0 = QFrame()
        line0.setFrameShape(QFrame.Shape.VLine)
        line0.setFrameShadow(QFrame.Shadow.Sunken)
        line0.setStyleSheet(f"background-color: {COMMON_STYLES['input_border']}; width: 1px;")
        layout.addWidget(line0)
        
        # 0-2. [ 태그 뷰어 ] - 제거됨 (초기화 시 자동 배치)
        # self.btn_tag_viewer = QPushButton(" 🏷️ 태그 뷰어 ")
        # self.btn_tag_viewer.clicked.connect(self.tag_viewer_clicked.emit)
        # layout.addWidget(self.btn_tag_viewer)

        # 1. [ 랜덤 ]
        self.btn_random = QPushButton(" 🎲 랜덤 ")
        self.btn_random.clicked.connect(self.random_clicked.emit)
        layout.addWidget(self.btn_random)
        
        # 2. [ 랜덤+생성 ]
        self.btn_random_gen = QPushButton(" 🎲+🎨 랜덤+생성 ")
        self.btn_random_gen.clicked.connect(self.random_generate_clicked.emit)
        layout.addWidget(self.btn_random_gen)
        
        # 3. [ 이미지 생성 ] (강조)
        self.btn_generate = QPushButton("   🎨 이미지 생성   ")
        # 생성 버튼 스타일 오버라이드
        self.btn_generate.setStyleSheet(f"""
            QPushButton {{
                background-color: {COMMON_STYLES['input_focus']};
                color: white;
                border: none;
                border-radius: 6px;
                padding: {get_scaled_size(8)}px {get_scaled_size(12)}px;
                font-family: {FONT_FAMILY};
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #5A4D80; /* 약간 밝게 */
            }}
            QPushButton:pressed {{
                background-color: #3E3459;
            }}
        """)
        self.btn_generate.clicked.connect(self.generate_clicked.emit)
        layout.addWidget(self.btn_generate)
        
        # 구분선 (Spacer 역할)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet(f"background-color: {COMMON_STYLES['input_border']}; width: 1px;")
        layout.addWidget(line)

        # 4. [ 해상도 ] (버튼처럼 보이게 하여 클릭 시 팝업 유도)
        self.current_resolution = "1024 x 1024" # 기본값
        self.btn_resolution = QPushButton(f" {self.current_resolution} ▼ ")
        self.btn_resolution.clicked.connect(self._show_resolution_menu)
        layout.addWidget(self.btn_resolution)
        
        # 5. [ 랜덤 해상도 ] 체크박스
        self.chk_random_res = QCheckBox("랜덤 해상도")
        self.chk_random_res.setLayoutDirection(Qt.LayoutDirection.RightToLeft) # 텍스트 왼쪽, 체크 오른쪽? 아니면 기본
        layout.addWidget(self.chk_random_res)
        
        # 6. [ 파라미터 ] (버튼)
        self.btn_params = QPushButton(" ⚙ 파라미터 ▼ ")
        self.btn_params.clicked.connect(self._toggle_parameter_panel)
        layout.addWidget(self.btn_params)

        # 파라미터 패널 생성 (모드별)
        self._create_parameter_panel()
        self.param_panel.hide()

        # 7. [ Tags ] (버튼) - 독립 윈도우 태그 뷰어
        self.btn_tags = QPushButton(" 🏷️ Tags ")
        self.btn_tags.setToolTip("태그 뷰어를 독립 윈도우로 엽니다.")
        self.btn_tags.clicked.connect(self.tags_clicked.emit)
        layout.addWidget(self.btn_tags)

        # 최상위 레이아웃
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.container)

    def _create_parameter_panel(self):
        """현재 모드에 맞는 파라미터 패널 생성"""
        if self.current_mode == "COMFYUI":
            from legacy_desktop.ui.interactive.comfyui_parameter_panel import ComfyUIParameterPanel
            self.param_panel = ComfyUIParameterPanel(None, self.app_context)
        else:
            # NAI, WEBUI 등은 NAI 파라미터 패널 사용
            from legacy_desktop.ui.interactive.parameter_panel import ParameterPanel
            self.param_panel = ParameterPanel(None)

    def switch_parameter_panel(self, new_mode: str):
        """
        모드 변경 시 파라미터 패널 교체

        Args:
            new_mode: 새로운 API 모드 (NAI, WEBUI, COMFYUI)
        """
        # 기존 패널 숨기고 제거
        if hasattr(self, 'param_panel') and self.param_panel:
            was_visible = self.param_panel.isVisible()
            self.param_panel.hide()
            self.param_panel.deleteLater()
        else:
            was_visible = False

        # 모드 업데이트
        self.current_mode = new_mode

        # 새 패널 생성
        self._create_parameter_panel()

        # 이전에 열려있었다면 다시 열기
        if was_visible:
            self._toggle_parameter_panel()

        print(f"[FloatingControlBar] 파라미터 패널 전환: {new_mode}")

    def _toggle_parameter_panel(self):
        """파라미터 패널 토글"""
        if self.param_panel.isVisible():
            self.param_panel.hide()
        else:
            # 버튼 바로 위에 위치
            btn_geo = self.btn_params.geometry()
            global_pos = self.btn_params.mapToGlobal(QPoint(0, 0))

            w = get_scaled_size(400)
            h = self.param_panel.sizeHint().height()
            self.param_panel.resize(w, h)

            x = global_pos.x() - (w - self.btn_params.width()) // 2 # 중앙 정렬 (약간 왼쪽으로 치우칠 수 있음)
            # 화면 오른쪽 넘어가는 것 방지
            screen_geo = self.screen().geometry() if self.screen() else None
            if screen_geo and x + w > screen_geo.right():
                x = screen_geo.right() - w - 10

            y = global_pos.y() - h - get_scaled_size(10)

            self.param_panel.move(x, y)
            self.param_panel.show()
            self.param_panel.raise_()
        
    def sizeHint(self):
        return self.container.sizeHint()

    def _show_resolution_menu(self):
        """해상도 선택 메뉴 표시"""
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {COMMON_STYLES['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
            }}
            QMenu::item {{
                padding: 5px 20px;
            }}
            QMenu::item:selected {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        
        for res in self.RESOLUTIONS:
            action = menu.addAction(res)
            # Lambda issue fix: capture res
            action.triggered.connect(lambda checked, r=res: self.set_resolution(r))
            
        # 버튼 위쪽에 메뉴 표시 (FloatingBar가 하단에 있으므로)
        # 메뉴 크기 예측
        menu_height = menu.sizeHint().height()
        btn_pos = self.btn_resolution.mapToGlobal(QPoint(0, 0))
        
        # 버튼 바로 위 (Y - 메뉴높이)
        # 약간의 여백(5px)을 두어 UI가 겹치지 않게 함
        menu.exec(QPoint(btn_pos.x(), btn_pos.y() - menu_height - 5))

    def set_resolution(self, res_str):
        self.current_resolution = res_str
        self.btn_resolution.setText(f" {res_str} ▼ ")

    def get_resolution(self):
        """
        현재 설정된 해상도 반환 (Width, Height)
        랜덤 해상도 체크 시, 랜덤 선택 후 버튼 텍스트 업데이트 및 반환
        """
        if self.chk_random_res.isChecked():
            import random
            selected = random.choice(self.RESOLUTIONS)
            self.set_resolution(selected)
            res_str = selected
        else:
            res_str = self.current_resolution
            
        # 파싱 "1024 x 1024" -> (1024, 1024)
        try:
            w_str, h_str = res_str.split('x')
            return int(w_str.strip()), int(h_str.strip())
        except:
            return 1024, 1024 # Fallback
