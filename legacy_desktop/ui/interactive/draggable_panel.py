"""
Draggable Panel Wrapper (ui/interactive/draggable_panel.py)

이 모듈은 PyQt6 위젯을 자유롭게 이동 가능한 플로팅 패널로 변환해주는 래퍼 클래스 및 관리 시스템을 제공합니다.
마치 "포스트잇"처럼 화면 곳곳에 배치하거나 가장자리에 붙여둘 수 있는 유연한 UI 컴포넌트입니다.

주요 구성 요소 및 기능:

1. FloatingPanelManager (싱글톤):
   - 모든 플로팅 패널의 Z-Order(레이어 순서)를 중앙 관리합니다.
   - 패널 클릭, 드래그, 또는 내부 입력창(TextEdit) 포커스 시 자동으로 해당 패널을 최상단으로 올립니다.

2. DragHandle (상단 바):
   - 패널 상단에 위치한 드래그 전용 핸들입니다.
   - 심플한 디자인(텍스트 없음)을 유지하며, 패널 이동의 중심점 역할을 합니다.

3. DraggablePanel (메인 컨테이너):
   - 컨텐츠(child_widget)를 감싸는 반투명 둥근 모서리 패널입니다.
   - **다중 드래그 지원**: 상단 핸들뿐만 아니라, 패널의 빈 공간(프레임)을 잡고도 드래그가 가능합니다.
   - **Safe Move (화면 이탈 방지)**: 패널을 화면 밖으로 던져도 최소 30px는 화면 내에 남도록 강제하여, "잃어버림"을 방지하고 "포스트잇"처럼 활용할 수 있게 합니다.
   - **자동 크기 조절**: 내부 컨텐츠(예: 아코디언 블록)가 접히거나 펼쳐질 때 패널 크기도 부드럽게 동기화됩니다.

사용법:
    # 이미지 뷰어 위에 플로팅 패널 생성
    panel = DraggablePanel(parent=image_viewer, child_widget=my_block_widget)
    panel.show()
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QApplication
)
from PyQt6.QtCore import Qt, QPoint, QEvent, QTimer, QObject, pyqtSignal

from legacy_desktop.ui.theme import DARK_COLORS
from legacy_desktop.ui.scaling_manager import get_scaled_size


class FloatingPanelManager(QObject):
    """플로팅 패널들을 관리하는 싱글톤 매니저 (Z-Order 등 관리)"""
    _instance = None
    
    panel_activated = pyqtSignal() # 패널이 활성화(최상위로 이동)될 때 발생하는 시그널

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
        
    def __init__(self):
        super().__init__()
        self.panels = []
        # 포커스 변경 감지 (TextEdit 등 내부 위젯 클릭 시에도 Z-Index 올리기 위해)
        app = QApplication.instance()
        if app:
            app.focusChanged.connect(self._on_focus_changed)
        
    def register(self, panel):
        """패널 등록"""
        if panel not in self.panels:
            self.panels.append(panel)

    def unregister(self, panel):
        """패널 등록 해제"""
        if panel in self.panels:
            self.panels.remove(panel)

    def activate_panel(self, panel):
        """패널을 최상단으로 올림 (Z-Index)"""
        try:
            if panel:
                panel.raise_()
                self.panel_activated.emit() # 알림
        except RuntimeError:
            pass
            
    def _on_focus_changed(self, old, new):
        """포커스 변경 시 해당 위젯이 속한 패널 활성화"""
        if not new: return
        
        # 죽은 패널 정리 및 안전한 접근
        for panel in self.panels[:]: # 복사본 순회
            try:
                if panel == new or panel.isAncestorOf(new):
                    self.activate_panel(panel)
                    break
            except RuntimeError:
                # 이미 삭제된 객체는 리스트에서 제거
                if panel in self.panels:
                    self.panels.remove(panel)
                continue



class DragHandle(QFrame):
    """드래그 전용 핸들 바"""
    def __init__(self, parent=None, opacity: float = 0.66, title: str = None, header_height: int = None, font_size: int = None, borderless: bool = False, click_to_toggle: bool = False):
        super().__init__(parent)
        self.clicked_to_toggle_enabled = click_to_toggle
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        
        # 헤더 높이 설정 (사용자 지정 or 기본값)
        h_height = header_height if header_height is not None else get_scaled_size(22)
        self.setFixedHeight(h_height)
        
        # 폰트 크기 저장 (타이틀용)
        self.custom_font_size = font_size
        
        # Opacity를 hex 문자열(2자리)로 변환
        alpha_val = int(255 * opacity)
        alpha_hex = f"{alpha_val:02X}"
        
        # 테두리 스타일 설정
        border_style = "border: 1px solid rgba(255, 255, 255, 0.3);"
        if borderless:
            border_style = "border: none;"

        self.setStyleSheet(f"""
            background-color: {DARK_COLORS['bg_primary']}{alpha_hex};
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            {border_style}
            border-bottom: none;
        """)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(get_scaled_size(10), 0, get_scaled_size(8), 0)
        
        # 타이틀 라벨 (선택사항)
        if title:
            from PyQt6.QtWidgets import QLabel
            from legacy_desktop.ui.interactive.interactive_theme import FONT_FAMILY, get_scaled_font_size
            
            # --- 토글 버튼 추가 ---
            from PyQt6.QtWidgets import QPushButton
            self.btn_toggle = QPushButton("▼")
            self.btn_toggle.setFixedSize(get_scaled_size(40), get_scaled_size(40)) # 크기 증가 (20 -> 40)
            self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_toggle.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: #FFFFFF;
                    border: none;
                    text-align: center;
                    font-size: {get_scaled_font_size(12)}px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    color: {DARK_COLORS['accent_blue']};
                }}
            """)
            self.btn_toggle.clicked.connect(self._on_toggle_clicked)
            layout.addWidget(self.btn_toggle)
            
            # 타이틀
            label = QLabel(title)
            
            # 폰트 크기 결정
            f_size = self.custom_font_size if self.custom_font_size is not None else get_scaled_font_size(12)
            
            label.setStyleSheet(f"""
                color: #FFFFFF;
                font-family: {FONT_FAMILY};
                font-size: {f_size}px;
                font-weight: bold;
                background-color: transparent;
            """)
            layout.addWidget(label)
            layout.addStretch() 

        self._drag_start_pos = None
        self._initial_press_global_pos = None

    def _on_toggle_clicked(self):
        """토글 버튼 클릭 핸들러"""
        parent = self.parent()
        if hasattr(parent, 'toggle_content'):
            parent.toggle_content()

    def set_arrow(self, is_expanded):
        """화살표 방향 설정"""
        if hasattr(self, 'btn_toggle'):
            self.btn_toggle.setText("▼" if is_expanded else "▶")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Z-Order 업데이트
            FloatingPanelManager.instance().activate_panel(self.parent())

            self._drag_start_pos = event.globalPosition().toPoint() - self.parent().pos()
            
            if self.clicked_to_toggle_enabled:
                 self._initial_press_global_pos = event.globalPosition().toPoint()
                 
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_start_pos is not None:
            new_pos = event.globalPosition().toPoint() - self._drag_start_pos
            # 안전한 이동 (화면 이탈 방지)
            self.parent().move_to_safe_position(new_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if self.clicked_to_toggle_enabled and self._initial_press_global_pos is not None:
            move_dist = (event.globalPosition().toPoint() - self._initial_press_global_pos).manhattanLength()
            if move_dist < 5: # 5px 미만 이동 시 클릭
                self._on_toggle_clicked()

        self._drag_start_pos = None
        self._initial_press_global_pos = None
        event.accept()

    # mouseDoubleClickEvent 제거 (싱글 클릭이 토글하므로 중복 방지)


class DraggablePanel(QWidget):
    def __init__(self, parent=None, child_widget=None, header_opacity: float = 0.66, title: str = None, header_height: int = None, font_size: int = None, borderless: bool = False):
        super().__init__(parent)
        
        # 매니저 등록
        FloatingPanelManager.instance().register(self)
        
        # 기본 설정
        self.setWindowFlags(Qt.WindowType.SubWindow) 
        
        # 스타일 및 레이아웃
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0) # 핸들과 컨텐츠 사이 간격 없음
        layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize) 
        
        # 1. 드래그 핸들 (상단)
        # Whitelist Logic for Click Toggle
        allow_toggle = False
        if child_widget:
            c_name = type(child_widget).__name__
            if c_name in ["TagViewerWidget", "TagViewerBlock"]:
                allow_toggle = True

        self.handle = DragHandle(self, opacity=header_opacity, title=title, header_height=header_height, font_size=font_size, borderless=borderless, click_to_toggle=allow_toggle)
        layout.addWidget(self.handle)
        
        # 2. 컨텐츠 컨테이너 (하단)
        self.container = QFrame()
        self.container.setObjectName("floating_panel")
        # 테두리 스타일 설정
        border_style = "border: 1px solid rgba(255, 255, 255, 0.3);"
        if borderless:
            border_style = "border: none;"

        self.container.setStyleSheet(f"""
            QFrame#floating_panel {{
                background-color: {DARK_COLORS['bg_primary']}AA;
                {border_style}
                border-top: none; /* 상단은 핸들과 연결 */
                border-bottom-left-radius: 8px;
                border-bottom-right-radius: 8px;
            }}
        """)
        
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        
        if child_widget:
            container_layout.addWidget(child_widget)
            # 자식 크기 변경 시 패널 크기 업데이트 연결
            if hasattr(child_widget, 'toggled'):
                child_widget.toggled.connect(self._on_child_resized)
            
            # 자식 위젯 클릭 감지 (Z-Order용)
            child_widget.installEventFilter(self)
            
        layout.addWidget(self.container)
        
        # 컨테이너 자체 이벤트 필터 (드래그 및 클릭 감지)
        self.container.installEventFilter(self)

        # 바디 드래그를 위한 변수
        self._body_drag_start_pos = None

    def closeEvent(self, event):
        """패널 종료 시 매니저에서 제거"""
        FloatingPanelManager.instance().unregister(self)
        super().closeEvent(event)

    def toggle_content(self):
        """컨텐츠 접기/펼치기 토글"""
        if self.container.isVisible():
            self.container.hide()
            self.handle.set_arrow(False)
            self.adjustSize() # 크기 줄이기
        else:
            self.container.show()
            self.handle.set_arrow(True)
            self.adjustSize() # 크기 늘리기

    def set_collapsed(self, collapsed: bool):
        """외부에서 접기/펼치기 상태 강제 설정"""
        if collapsed:
            if self.container.isVisible():
                self.container.hide()
                self.handle.set_arrow(False)
                self.adjustSize()
        else:
            if not self.container.isVisible():
                self.container.show()
                self.handle.set_arrow(True)
                self.adjustSize()
            
    def move_to_safe_position(self, pos: QPoint):
        """부모 위젯 영역 밖으로 완전히 나가지 않도록 좌표 보정"""
        parent = self.parent()
        if not parent:
            self.move(pos)
            return

        parent_rect = parent.rect()
        panel_rect = self.rect()

        # 화면 밖으로 나가더라도 최소 30px는 보이게 하여 다시 잡을 수 있도록 함
        margin = 30

        x = max(-panel_rect.width() + margin, min(pos.x(), parent_rect.width() - margin))

        # 상단(핸들)은 가려지지 않게 최소 y=0 유지 (선택사항, 너무 위로 가면 못 잡으므로)
        y = max(0, min(pos.y(), parent_rect.height() - margin))

        self.move(x, y)

    def eventFilter(self, obj, event):
        """이벤트 필터: 활성화 및 바디 드래그 처리"""
        
        # 1. Z-Order 활성화 (클릭 시)
        if event.type() == QEvent.Type.MouseButtonPress:
            FloatingPanelManager.instance().activate_panel(self)

        # 2. 바디(프레임 빈 공간) 드래그 처리 - obj가 container일 때만
        if obj == self.container:
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    self._body_drag_start_pos = event.globalPosition().toPoint() - self.pos()
                    # 이벤트 수락하지 않고 흘려보냄 (필요 시 자식 처리 가능성 고려)
                    # 하지만 container면 자식이 아님.
            
            elif event.type() == QEvent.Type.MouseMove:
                if self._body_drag_start_pos is not None:
                    new_pos = event.globalPosition().toPoint() - self._body_drag_start_pos
                    self.move_to_safe_position(new_pos)
                    return True # 드래그 이벤트 소비

            elif event.type() == QEvent.Type.MouseButtonRelease:
                self._body_drag_start_pos = None

        return super().eventFilter(obj, event)

    def _on_child_resized(self):
        """자식 크기 변경 시 패널 크기 업데이트 및 화면 이탈 방지"""
        old_h = self.height()
        self.adjustSize()
        # 레이아웃 반영 지연을 고려하여 다음 틱에 경계 체크
        QTimer.singleShot(0, lambda: self._check_boundary(old_h))

    def _check_boundary(self, old_h):
        """크기 변경 후 화면 경계 체크 및 보정"""
        new_h = self.height()
        
        # 높이가 늘어났을 때 (펼쳐짐)
        if new_h > old_h:
            parent = self.parent()
            if parent:
                bottom_y = self.y() + new_h
                limit_y = parent.height() - 20 # 20px 마진
                
                if bottom_y > limit_y:
                    # 화면 아래로 넘어갔다면 위로 끌어올림
                    offset = bottom_y - limit_y
                    new_y = int(self.y() - offset)
                    if new_y < 0: new_y = 0
                    self.move(self.x(), new_y)
