# ui/right_view.py (ImageWindow 분리 지원 버전)

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QPushButton, QTabBar, 
    QMenu, QLabel, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint
from PyQt6.QtGui import QAction, QCursor
import os
from ui.theme import DARK_STYLES, DARK_COLORS
from ui.image_window import ImageWindow, ImageHistoryWindow
from ui.api_management_window import APIManagementWindow
from ui.depth_search_window import DepthSearchWindow
from ui.web_view import BrowserTab
from ui.detached_window import DetachedWindow
from core.search_result_model import SearchResultModel
from ui.png_info_tab import PngInfoTab
import pandas as pd

class EnhancedTabWidget(QTabWidget):
    """우클릭 컨텍스트 메뉴가 있는 향상된 탭 위젯 (ImageWindow 분리 지원)"""
    
    # 탭을 외부 창으로 분리 요청 시그널
    tab_detach_requested = pyqtSignal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        
        # 분리 불가능한 탭들을 추적 (필요시 추가 가능)
        self.non_detachable_tabs = set()  # 현재는 모든 탭이 분리 가능
        
    def set_tab_detachable(self, tab_index: int, detachable: bool):
        """특정 탭의 분리 가능 여부 설정"""
        if detachable:
            self.non_detachable_tabs.discard(tab_index)
        else:
            self.non_detachable_tabs.add(tab_index)
        
    def show_context_menu(self, position: QPoint):
        """탭 바에서 우클릭 시 컨텍스트 메뉴 표시"""
        # 클릭된 위치의 탭 인덱스 찾기
        tab_index = self.tabBar().tabAt(position)
        
        if tab_index == -1:
            return  # 탭이 아닌 곳을 클릭한 경우
            
        # ✅ 변경: 모든 탭이 분리 가능하도록 수정 (기존 제한 제거)
        # 특정 탭이 분리 불가능으로 설정된 경우에만 제외
        if tab_index in self.non_detachable_tabs:
            return
            
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
        detach_action.triggered.connect(lambda: self.tab_detach_requested.emit(tab_index))
        menu.addAction(detach_action)
        
        # 메뉴 표시
        global_pos = self.tabBar().mapToGlobal(position)
        menu.exec(global_pos)

class RightView(QWidget):
    """
    오른쪽 패널의 탭 컨테이너 클래스 (ImageWindow 분리 지원 버전)
    """
    instant_generation_requested = pyqtSignal(object)
    load_prompt_to_main_ui = pyqtSignal(str)

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.main_window = self.app_context
        
        # 분리된 창들을 추적하기 위한 딕셔너리
        self.detached_windows = {}  # {tab_index: DetachedWindow}
        self.detached_widgets = {}  # {tab_index: (widget, title)}
        
        self.init_ui()
        self.setup_tabs()

    def init_ui(self):
        """기본 UI 구조 초기화"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(0)

        # 향상된 탭 위젯 사용
        self.tab_widget = EnhancedTabWidget()
        self.tab_widget.setStyleSheet(DARK_STYLES['dark_tabs'])
        
        # 탭 분리 요청 시그널 연결
        self.tab_widget.tab_detach_requested.connect(self.detach_tab)
        
        main_layout.addWidget(self.tab_widget)

    def setup_tabs(self):
        """기본 탭들 설정 (ImageWindow 분리 지원 포함)"""
        # ✅ 변경: 이미지 생성 결과 탭도 분리 가능하도록 수정
        self.image_window = ImageWindow(self.app_context, self)
        self.image_window_tab_index = self.tab_widget.addTab(self.image_window, "🖼️ 생성 결과")
        
        # ImageWindow 시그널 연결
        self.image_window.load_prompt_to_main_ui.connect(self.load_prompt_to_main_ui)
        self.image_window.instant_generation_requested.connect(self.instant_generation_requested)
        
        # 웹브라우저 탭
        self.browser_tab = BrowserTab(self)
        self.browser_tab.load_url("https://danbooru.donmai.us/")
        self.browser_tab_index = self.tab_widget.addTab(self.browser_tab, "📦 Danbooru")
        self.browser_tab.tags_extracted.connect(self.instant_generation_requested)

        # PNG Info 탭
        self.png_info_tab = PngInfoTab(self)
        self.png_info_tab.parameters_extracted.connect(self.on_png_parameters_extracted)
        self.png_info_tab_index = self.tab_widget.addTab(self.png_info_tab, "📝 PNG Info")
        
        print("✅ 모든 탭(ImageWindow 포함) 분리 기능 활성화")

    def detach_tab(self, tab_index: int):
        """탭을 외부 창으로 분리 (완전 독립 창)"""
        if tab_index in self.detached_windows:
            # 이미 분리된 탭인 경우 기존 창을 활성화
            self.detached_windows[tab_index].raise_()
            self.detached_windows[tab_index].activateWindow()
            return
            
        # 현재 탭의 위젯과 제목 가져오기
        widget = self.tab_widget.widget(tab_index)
        tab_title = self.tab_widget.tabText(tab_index)
        
        if not widget:
            print(f"❌ 탭 분리 실패: 위젯을 찾을 수 없습니다 (index: {tab_index})")
            return
            
        print(f"🔧 독립 탭 분리 시작: '{tab_title}' (index: {tab_index})")
        print(f"   - 위젯 타입: {type(widget).__name__}")
        
        try:
            # 플레이스홀더 위젯 생성
            placeholder = self.create_placeholder_widget(tab_title)
            
            # 탭에서 원본 위젯 제거하고 플레이스홀더로 교체
            self.tab_widget.removeTab(tab_index)
            self.tab_widget.insertTab(tab_index, placeholder, f"🔗 {tab_title}")
            
            # 원본 정보 저장
            self.detached_widgets[tab_index] = (widget, tab_title)
            
            # ✅ 완전히 독립적인 창 생성 (parent 관계 제거)
            detached_window = DetachedWindow(
                widget, 
                tab_title, 
                tab_index, 
                parent_container=self  # 부모가 아닌 참조만 전달
            )
            detached_window.window_closed.connect(self.reattach_tab)
            
            # 창 추적 딕셔너리에 추가
            self.detached_windows[tab_index] = detached_window
            
            # 독립 창 표시
            detached_window.show()
            detached_window.raise_()
            detached_window.activateWindow()
            
            print(f"✅ 독립 탭 '{tab_title}' 분리 완료 (메인 UI와 완전 분리)")
            
            # ImageWindow인 경우 추가 설정
            if isinstance(widget, ImageWindow):
                print("   - ImageWindow 독립 창 시그널 연결 확인 완료")
                
        except Exception as e:
            print(f"❌ 탭 '{tab_title}' 분리 실패: {e}")
            import traceback
            traceback.print_exc()

    def reattach_tab(self, tab_index: int, widget: QWidget):
        """외부 창에서 탭으로 복귀 (ImageWindow 지원 강화)"""
        if tab_index not in self.detached_widgets:
            print(f"❌ 복귀 실패: 탭 인덱스 {tab_index}를 찾을 수 없습니다")
            return
            
        # 저장된 원본 정보 복구
        original_widget, original_title = self.detached_widgets[tab_index]
        
        print(f"🔄 탭 복귀 시작: '{original_title}' (index: {tab_index})")
        print(f"   - 위젯 타입: {type(widget).__name__}")
        
        try:
            # 플레이스홀더 제거
            placeholder = self.tab_widget.widget(tab_index)
            self.tab_widget.removeTab(tab_index)
            if placeholder:
                placeholder.deleteLater()
                
            # 원본 위젯을 탭으로 복귀
            widget.setParent(self)
            self.tab_widget.insertTab(tab_index, widget, original_title)
            
            # 복귀된 탭을 활성화
            self.tab_widget.setCurrentIndex(tab_index)
            
            # 추적 딕셔너리에서 제거
            del self.detached_widgets[tab_index]
            if tab_index in self.detached_windows:
                del self.detached_windows[tab_index]
                
            print(f"✅ 탭 '{original_title}' 복귀 완료")
            
            # ✅ ImageWindow인 경우 추가 처리
            if isinstance(widget, ImageWindow):
                print("   - ImageWindow 복귀 후 시그널 연결 확인 완료")
                # 필요시 시그널 재연결이나 상태 복원 로직 추가 가능
                
        except Exception as e:
            print(f"❌ 탭 '{original_title}' 복귀 실패: {e}")
            import traceback
            traceback.print_exc()

    def create_placeholder_widget(self, tab_title: str) -> QWidget:
        """분리된 탭 자리에 표시할 플레이스홀더 위젯 생성"""
        placeholder = QFrame()
        placeholder.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 2px dashed {DARK_COLORS['border_light']};
                border-radius: 8px;
            }}
        """)
        
        layout = QVBoxLayout(placeholder)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(16)
        
        # 아이콘
        icon_label = QLabel("🔗")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet(f"""
            QLabel {{
                font-size: 48px;
                color: {DARK_COLORS['text_secondary']};
            }}
        """)
        
        # 메시지
        message_label = QLabel(f"'{tab_title}'이(가)\n외부 창에서 열려있습니다")
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setStyleSheet(f"""
            QLabel {{
                font-size: 16px;
                color: {DARK_COLORS['text_secondary']};
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
            }}
        """)
        
        # 복귀 버튼
        return_button = QPushButton("창 닫고 여기로 복귀")
        return_button.setStyleSheet(DARK_STYLES['secondary_button'])
        return_button.clicked.connect(lambda: self.force_reattach_tab(tab_title))
        
        layout.addWidget(icon_label)
        layout.addWidget(message_label)
        layout.addWidget(return_button)
        layout.addStretch()
        
        return placeholder

    def force_reattach_tab(self, tab_title: str):
        """플레이스홀더의 버튼을 통한 강제 복귀"""
        # 해당 제목의 분리된 창 찾기
        for tab_index, window in self.detached_windows.items():
            if window.tab_title == tab_title:
                window.close()  # 창을 닫으면 자동으로 reattach_tab이 호출됨
                break

    # === ImageWindow 관련 메서드들 (기존 유지) ===
    def update_image(self, image):
        """이미지 업데이트 (분리 상태 고려)"""
        if hasattr(self, 'image_window'):
            self.image_window.update_image(image)

    def update_info(self, text: str):
        """정보 업데이트 (분리 상태 고려)"""
        if hasattr(self, 'image_window'):
            self.image_window.update_info(text)

    def add_to_history(self, image, raw_bytes: bytes, info: str, source_row: pd.Series):
        """히스토리 추가 (분리 상태 고려)"""
        if hasattr(self, 'image_window'):
            self.image_window.add_to_history(image, raw_bytes, info, source_row)

    # === 기타 기존 메서드들 ===
    def on_png_parameters_extracted(self, parameters):
        """PNG Info 탭에서 파라미터 추출 시 처리"""
        # 기존 구현 유지
        pass

    def add_api_management_tab(self):
        """API 관리 탭 추가"""
        # 기존 구현 유지
        for i in range(self.tab_widget.count()):
            if isinstance(self.tab_widget.widget(i), APIManagementWindow):
                self.tab_widget.setCurrentIndex(i)
                return

        api_window = APIManagementWindow(self.app_context, self)
        tab_index = self.tab_widget.addTab(api_window, "⚙️ API 관리")
        
        # 닫기 버튼 추가 로직 등은 기존 구현 유지
        self.tab_widget.setCurrentIndex(tab_index)