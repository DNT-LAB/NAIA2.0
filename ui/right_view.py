from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTabWidget, QPushButton, QTabBar
from PyQt6.QtCore import Qt, pyqtSignal
import os
from ui.theme import DARK_STYLES
from ui.image_window import ImageWindow, ImageHistoryWindow
from ui.api_management_window import APIManagementWindow
from ui.depth_search_window import DepthSearchWindow
from ui.web_view import BrowserTab
from core.search_result_model import SearchResultModel
from ui.png_info_tab import PngInfoTab
import pandas as pd

class RightView(QWidget):
    """
    오른쪽 패널의 탭 컨테이너 클래스
    다양한 기능 탭들을 관리하는 상위 뷰
    """
    instant_generation_requested = pyqtSignal(object)
    load_prompt_to_main_ui = pyqtSignal(str)

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.main_window = self.app_context
        self.init_ui()
        self.setup_tabs()

    def init_ui(self):
        """기본 UI 구조 초기화"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(0)

        # 탭 위젯 생성
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(DARK_STYLES['dark_tabs'])
        main_layout.addWidget(self.tab_widget)

    def setup_tabs(self):
        """기본 탭들 설정"""
        # 이미지 생성 결과 탭
        self.image_window = ImageWindow(self.app_context,self)  # ✅ ImageWindow 사용
        self.tab_widget.addTab(self.image_window, "🖼️ 생성 결과")
        
        self.image_window.load_prompt_to_main_ui.connect(self.load_prompt_to_main_ui)
        self.image_window.instant_generation_requested.connect(self.instant_generation_requested)
        
        # 웹브라우저 탭
        self.browser_tab = BrowserTab(self)
        self.browser_tab.load_url("https://danbooru.donmai.us/")
        self.browser_tab_index = self.tab_widget.addTab(self.browser_tab, "📦Danbooru")
        self.browser_tab.tags_extracted.connect(self.instant_generation_requested)

        # PNG Info 탭 추가
        self.png_info_tab = PngInfoTab(self)
        self.png_info_tab.parameters_extracted.connect(self.on_png_parameters_extracted)
        self.tab_widget.addTab(self.png_info_tab, "📝 PNG Info")

    def add_tab(self, widget: QWidget, title: str, icon: str = ""):
        """
        새로운 탭 추가
        
        Args:
            widget: 탭에 표시할 위젯
            title: 탭 제목
            icon: 탭 아이콘 (선택사항)
        """
        tab_title = f"{icon} {title}" if icon else title
        self.tab_widget.addTab(widget, tab_title)

    def remove_tab(self, index: int):
        """탭 제거"""
        if 0 <= index < self.tab_widget.count():
            self.tab_widget.removeTab(index)

    def get_current_tab(self) -> QWidget:
        """현재 활성 탭 위젯 반환"""
        return self.tab_widget.currentWidget()

    def set_current_tab(self, index: int):
        """특정 탭을 활성화"""
        if 0 <= index < self.tab_widget.count():
            self.tab_widget.setCurrentIndex(index)

    # === 이미지 관련 기능들 (ImageWindow로 위임) ===
    def update_image(self, image): # 타입 힌트 수정
        """생성된 이미지 업데이트 - ImageWindow로 위임"""
        if hasattr(self, 'image_window'):
            self.image_window.update_image(image)

    def update_info(self, text: str):
        """생성 정보 업데이트 - ImageWindow로 위임"""
        if hasattr(self, 'image_window'):
            self.image_window.update_info(text)

    # [수정] 이 메서드는 이제 ImageWindow의 메서드를 직접 호출합니다.
    def add_to_history(self, image, raw_bytes: bytes, info: str, source_row: pd.Series):
        """히스토리에 추가 - ImageWindow의 책임으로 위임"""
        if hasattr(self, 'image_window'):
            # ImageWindow의 add_to_history를 호출합니다.
            self.image_window.add_to_history(image, raw_bytes, info, source_row)

    def add_api_management_tab(self):
        """API 관리 탭을 추가하고, 해당 탭에만 닫기 버튼을 생성합니다."""
        for i in range(self.tab_widget.count()):
            if isinstance(self.tab_widget.widget(i), APIManagementWindow):
                self.tab_widget.setCurrentIndex(i)
                return

        # ✅ [수정] APIManagementWindow 생성 시 app_context를 전달합니다.
        api_window = APIManagementWindow(self.app_context, self)
        
        tab_index = self.tab_widget.addTab(api_window, "⚙️ API 관리")
        
        # [신규] 해당 탭에만 표시될 닫기 버튼 생성
        close_button = QPushButton("✕")
        close_button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 9px;
                font-family: Arial, sans-serif;
                font-weight: bold;
                font-size: 14px;
                color: #B0B0B0;
                padding: 0px 4px;
            }
            QPushButton:hover {
                background-color: #F44336;
                color: white;
            }
        """)
        close_button.setFixedSize(18, 18)
        close_button.setToolTip("탭 닫기")
        
        # [신규] 탭 바의 오른쪽에 닫기 버튼 추가
        self.tab_widget.tabBar().setTabButton(tab_index, QTabBar.ButtonPosition.RightSide, close_button)
        
        # [신규] 버튼 클릭 시 close_tab 메서드를 호출하도록 연결 (람다 함수 사용)
        close_button.clicked.connect(lambda: self.close_tab(tab_index))
        
        self.tab_widget.setCurrentIndex(tab_index)

    def on_png_parameters_extracted(self, parameters):
        """PNG에서 파라미터 추출 시 호출"""
        print(f"🎯 PNG 파라미터 추출됨: {parameters}")

    def add_depth_search_tab(self, search_result: SearchResultModel, main_window):
        """심층 검색 탭을 추가하거나, 이미 있으면 해당 탭으로 전환합니다."""
        for i in range(self.tab_widget.count()):
            if isinstance(self.tab_widget.widget(i), DepthSearchWindow):
                self.tab_widget.setCurrentIndex(i)
                return

        depth_search_window = DepthSearchWindow(search_result, main_window)
        # DepthSearchWindow의 시그널을 MainWindow의 슬롯에 연결
        depth_search_window.results_assigned.connect(main_window.on_depth_search_results_assigned)

        tab_index = self.tab_widget.addTab(depth_search_window, "🔬 심층 검색")
        
        # [신규] 해당 탭에만 표시될 닫기 버튼 생성
        close_button = QPushButton("✕")
        close_button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 9px;
                font-family: Arial, sans-serif;
                font-weight: bold;
                font-size: 14px;
                color: #B0B0B0;
                padding: 0px 4px;
            }
            QPushButton:hover {
                background-color: #F44336;
                color: white;
            }
        """)
        close_button.setFixedSize(18, 18)
        close_button.setToolTip("탭 닫기")
        
        # [신규] 탭 바의 오른쪽에 닫기 버튼 추가
        self.tab_widget.tabBar().setTabButton(tab_index, QTabBar.ButtonPosition.RightSide, close_button)
        
        # [신규] 버튼 클릭 시 close_tab 메서드를 호출하도록 연결 (람다 함수 사용)
        close_button.clicked.connect(lambda: self.close_tab(tab_index))

        self.tab_widget.setCurrentIndex(tab_index)
    
    def close_tab(self, index: int):
        """탭 닫기 요청을 처리합니다."""
        widget_to_close = self.tab_widget.widget(index)
        
        # API 관리 또는 심층 검색 탭만 닫기 허용
        if isinstance(widget_to_close, (APIManagementWindow, DepthSearchWindow)):
            self.tab_widget.removeTab(index)
            widget_to_close.deleteLater()