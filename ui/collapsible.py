# ui/collapsible.py (수정된 버전)

from ui.theme import DARK_STYLES, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QSizePolicy, QToolButton, QMenu, QFrame, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint
from PyQt6.QtGui import QAction, QCursor

class EnhancedCollapsibleBox(QWidget):
    """우클릭 컨텍스트 메뉴가 있는 향상된 접고 펼 수 있는 위젯"""

    # 모듈을 외부 창으로 분리 요청 시그널 (title, content_widget)
    module_detach_requested = pyqtSignal(str, object)

    # 🆕 펼침/접힘 상태 변경 시그널 (title, is_expanded)
    toggled = pyqtSignal(str, bool)

    def __init__(self, title="", parent=None, detachable=True):
        super().__init__(parent)
        self.title = title
        self.detachable = detachable
        self.content_widget = None
        self.is_detached = False

        # 🆕 스크롤 위치 저장
        self._saved_scroll_position = 0

        self.setStyleSheet(DARK_STYLES['collapsible_box'])
        self.init_ui()

    def init_ui(self):
        """UI 초기화"""
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(0)
        self.main_layout.setContentsMargins(8, 6, 8, 8)
        
        # 제목 버튼 생성
        self.toggle_button = QToolButton(text=f" {self.title}", checkable=True, checked=False)
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle_button.toggled.connect(self.on_toggled)
        
        # Anlas 표시용 레이블 (NAI 모드 전용)
        self.anlas_label = QLabel("")
        self.anlas_label.setStyleSheet(f"color: #FFFF97; font-size: {get_scaled_font_size(19)}px; font-weight: bold; padding: 0 10px;")
        self.anlas_label.setVisible(False)
        
        # 테마에서 이미 동적 스케일링이 적용되므로 추가 스타일링 불필요
        # DARK_STYLES['collapsible_box']에서 QToolButton 스타일을 사용
        
        # 우클릭 컨텍스트 메뉴 설정 (분리 가능한 경우에만)
        if self.detachable:
            self.toggle_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.toggle_button.customContextMenuRequested.connect(self.show_context_menu)
        
        # 콘텐츠 영역
        self.content_area = QScrollArea()
        self.content_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.content_area.setMaximumHeight(0)
        self.content_area.setMinimumHeight(0)
        self.content_area.setWidgetResizable(True)
        self.content_area.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
        """)
        
        # 헤더 레이아웃 (제목 버튼과 Anlas 레이블을 담을 수평 레이아웃)
        header_layout = QHBoxLayout()
        header_layout.setSpacing(0)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(self.toggle_button)
        header_layout.addWidget(self.anlas_label)
        header_layout.addStretch()
        
        self.main_layout.addLayout(header_layout)
        self.main_layout.addWidget(self.content_area)

    def show_context_menu(self, position: QPoint):
        """제목 버튼에서 우클릭 시 컨텍스트 메뉴 표시"""
        if self.is_detached:
            return  # 이미 분리된 상태면 메뉴 표시 안함
            
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 5px;
            }}
            QMenu::item {{
                padding: 8px 20px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        
        # "외부 창에서 열기" 액션
        detach_action = QAction("🔗 외부 창에서 열기", self)
        detach_action.triggered.connect(self.request_detach)
        menu.addAction(detach_action)
        
        # 메뉴 표시
        global_pos = self.toggle_button.mapToGlobal(position)
        menu.exec(global_pos)

    def request_detach(self):
        """모듈 분리 요청"""
        if self.content_widget and not self.is_detached:
            # content_widget이 유효한지 확인
            try:
                # 위젯이 여전히 유효한지 테스트
                _ = self.content_widget.isVisible()
                # 분리 요청 시그널 발송
                self.module_detach_requested.emit(self.title, self.content_widget)
            except RuntimeError:
                print(f"❌ 모듈 '{self.title}'의 위젯이 이미 삭제되었습니다.")
        else:
            print(f"[WARNING] Module '{self.title}': content_widget is None or already detached")

    def on_toggled(self, checked):
        """접기/펼치기 토글"""
        if self.is_detached:
            return  # 분리된 상태에서는 토글 비활성화

        self.toggle_button.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        if checked:
            self.content_area.setMaximumHeight(16777215)
            # 🆕 스크롤 위치 복원
            self._restore_scroll_position()
        else:
            # 🆕 스크롤 위치 저장
            self._save_scroll_position()
            self.content_area.setMaximumHeight(0)

        # 🆕 펼침/접힘 상태 변경 시그널 발행
        self.toggled.emit(self.title, checked)
    
    def update_anlas(self, anlas_value):
        """Anlas 값을 업데이트합니다."""
        if anlas_value is not None:
            self.anlas_label.setText(f"[Anlas: {anlas_value}]")
            self.anlas_label.setVisible(True)
        else:
            self.anlas_label.setVisible(False)


    def setContentLayout(self, layout):
        """콘텐츠 레이아웃 설정 (디버깅 강화 버전)"""
        if layout is None:
            print(f"⚠️ 모듈 '{self.title}': 레이아웃이 None입니다.")
            return
            
        print(f"[CONFIG] Setting content for '{self.title}'...")
        print(f"   - 입력 레이아웃: {layout}")
        print(f"   - 레이아웃 타입: {type(layout).__name__}")
        
        # 콘텐츠 위젯 생성
        content_widget = QWidget()
        content_widget.setStyleSheet("background-color: transparent;")
        content_widget.setLayout(layout)
        
        # 위젯 크기 정책 설정
        content_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, 
            QSizePolicy.Policy.Preferred
        )
        
        self.content_widget = content_widget
        self.content_area.setWidget(content_widget)
        
        print(f"   - 생성된 content_widget: {content_widget}")
        print(f"   - content_widget 크기: {content_widget.size()}")
        print(f"   - content_widget 레이아웃: {content_widget.layout()}")
        print(f"[OK] Module '{self.title}': Content widget setup complete")

    def request_detach(self):
        """모듈 분리 요청 (디버깅 강화 버전)"""
        print(f"[DETACH] Module detach request: {self.title}")
        print(f"   - content_widget: {self.content_widget}")
        print(f"   - is_detached: {self.is_detached}")
        
        if self.content_widget and not self.is_detached:
            # content_widget이 유효한지 확인
            try:
                # 위젯이 여전히 유효한지 테스트
                visible = self.content_widget.isVisible()
                print(f"   - 위젯 가시성 테스트 통과: {visible}")
                
                # 분리 요청 시그널 발송
                print(f"   - 분리 시그널 발송: title={self.title}, widget={self.content_widget}")
                self.module_detach_requested.emit(self.title, self.content_widget)
                
            except RuntimeError as e:
                print(f"[ERROR] Module '{self.title}' widget already deleted: {e}")
        else:
            print(f"[WARNING] Module '{self.title}': content_widget is None or already detached")
            print(f"   - content_widget is None: {self.content_widget is None}")
            print(f"   - is_detached: {self.is_detached}")

    def set_detached_state(self, is_detached: bool):
        """분리 상태 설정 (디버깅 강화 버전)"""
        print(f"[CONFIG] Detach state change for '{self.title}': {self.is_detached} -> {is_detached}")
        
        self.is_detached = is_detached
        
        if is_detached:
            # 분리된 상태: 플레이스홀더만 표시
            print(f"   - 플레이스홀더 생성 및 설정")
            placeholder = self.create_placeholder()
            self.content_area.setWidget(placeholder)
            
            self.toggle_button.setText(f" 🔗 {self.title} (외부 창)")
            # 분리 상태 색상만 변경 (폰트는 테마에서 관리)
            self.toggle_button.setStyleSheet(f"""
                QToolButton {{
                    color: {DARK_COLORS['accent_blue']};
                }}
            """)
            self.toggle_button.setChecked(True)  # 펼쳐진 상태로 고정
            self.toggle_button.setEnabled(False)  # 토글 비활성화
            self.content_area.setMaximumHeight(150)  # 플레이스홀더 높이
        else:
            # 복귀된 상태: 원본 콘텐츠 복원
            print(f"   - 정상 상태로 복원")
            self.toggle_button.setText(f" {self.title}")
            # 기본 테마 스타일로 복원 (스타일시트 제거)
            self.toggle_button.setStyleSheet("")
            self.toggle_button.setEnabled(True)  # 토글 활성화
            self.toggle_button.setChecked(False)  # 접힌 상태로 복원
            self.content_area.setMaximumHeight(0)
            
        print(f"✅ '{self.title}' 상태 변경 완료")

    def create_placeholder(self) -> QWidget:
        """분리된 모듈 자리에 표시할 플레이스홀더 생성"""
        placeholder = QFrame()
        placeholder.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 2px dashed {DARK_COLORS['border_light']};
                border-radius: 8px;
                margin: 4px;
            }}
        """)
        
        layout = QVBoxLayout(placeholder)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)
        layout.setContentsMargins(16, 16, 16, 16)
        
        # 아이콘
        icon_label = QLabel("🔗")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(24)}px;
                color: {DARK_COLORS['text_secondary']};
            }}
        """)
        
        # 메시지
        message_label = QLabel(f"'{self.title}' 모듈이\n외부 창에서 열려있습니다")
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(12)}px;
                color: {DARK_COLORS['text_secondary']};
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
            }}
        """)
        
        layout.addWidget(icon_label)
        layout.addWidget(message_label)
        
        return placeholder

    def get_content_widget(self):
        """콘텐츠 위젯 반환"""
        return self.content_widget

    # 🆕 상태 추적 및 제어 메서드

    def is_expanded(self) -> bool:
        """현재 펼쳐진 상태인지 확인"""
        return self.toggle_button.isChecked() and not self.is_detached

    def set_expanded(self, expanded: bool, emit_signal: bool = True):
        """프로그래밍 방식으로 펼치기/접기 (시그널 발행 여부 선택 가능)"""
        if self.is_detached:
            return

        # 시그널 발행 방지를 위해 임시로 차단
        if not emit_signal:
            self.toggle_button.blockSignals(True)

        self.toggle_button.setChecked(expanded)

        if not emit_signal:
            self.toggle_button.blockSignals(False)
            # 수동으로 UI만 업데이트 (시그널 없이)
            self.toggle_button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
            if expanded:
                self.content_area.setMaximumHeight(16777215)
                self._restore_scroll_position()
            else:
                self._save_scroll_position()
                self.content_area.setMaximumHeight(0)

    def collapse(self, emit_signal: bool = True):
        """접기 (편의 메서드)"""
        self.set_expanded(False, emit_signal)

    def expand(self, emit_signal: bool = True):
        """펼치기 (편의 메서드)"""
        self.set_expanded(True, emit_signal)

    def _save_scroll_position(self):
        """스크롤 위치 저장"""
        if self.content_area and self.content_area.verticalScrollBar():
            self._saved_scroll_position = self.content_area.verticalScrollBar().value()
            print(f"[SCROLL] '{self.title}' 스크롤 위치 저장: {self._saved_scroll_position}")

    def _restore_scroll_position(self):
        """스크롤 위치 복원"""
        if self.content_area and self.content_area.verticalScrollBar():
            self.content_area.verticalScrollBar().setValue(self._saved_scroll_position)
            print(f"[SCROLL] '{self.title}' 스크롤 위치 복원: {self._saved_scroll_position}")

    def get_scroll_position(self) -> int:
        """현재 스크롤 위치 반환"""
        if self.content_area and self.content_area.verticalScrollBar():
            return self.content_area.verticalScrollBar().value()
        return 0

    def set_scroll_position(self, position: int):
        """스크롤 위치 설정"""
        if self.content_area and self.content_area.verticalScrollBar():
            self.content_area.verticalScrollBar().setValue(position)
            self._saved_scroll_position = position

# 기존 CollapsibleBox는 호환성을 위해 유지
class CollapsibleBox(EnhancedCollapsibleBox):
    """기존 CollapsibleBox (호환성 유지)"""
    def __init__(self, title="", parent=None):
        super().__init__(title, parent, detachable=False)