import __init__
import sys
import os
import json
import pandas as pd
import random
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QTextEdit, QCheckBox, QComboBox, QFrame,
    QScrollArea, QSplitter, QStatusBar, QTabWidget, QMessageBox
)
from core.middle_section_controller import MiddleSectionController
from core.context import AppContext
from core.generation_controller import GenerationController
from ui.theme import DARK_COLORS, DARK_STYLES, CUSTOM
from ui.collapsible import CollapsibleBox
from ui.right_view import RightView
from ui.resolution_manager_dialog import ResolutionManagerDialog
from PyQt6.QtGui import QFont, QFontDatabase, QIntValidator, QDoubleValidator
from PyQt6.QtCore import Qt, QThread, QObject, pyqtSignal, QTimer
from core.search_controller import SearchController
from core.search_result_model import SearchResultModel
from core.autocomplete_manager import AutoCompleteManager
from core.tag_data_manager import TagDataManager
from core.wildcard_manager import WildcardManager
from core.prompt_generation_controller import PromptGenerationController
from utils.load_generation_params import GenerationParamsManager

cfg_validator = QDoubleValidator(1.0, 10.0, 1)
step_validator = QIntValidator(1, 50)
cfg_rescale_validator = QDoubleValidator(-1.0, 1.0, 2)
_autocomplete_manager = None

# 웹엔진 관련 설정 (QApplication 생성 전에 필요)
def setup_webengine():  
    """WebEngine 설정"""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    
    # QApplication 생성 전 필수 설정
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    os.environ["QTWEBENGINE_REMOTE_DEBUGGING"] = "8888"
    
    # WebEngine 모듈 사전 로드
    try:
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        from PyQt6.QtWebEngineCore import QWebEngineProfile
        print("✅ WebEngine 모듈 사전 로드 완료")
    except ImportError:
        print("❌ PyQt6-WebEngine이 설치되지 않았습니다")


class ParquetLoader(QObject):
    finished = pyqtSignal(SearchResultModel)
    def run(self, file_path):
        df = pd.read_parquet(file_path)
        self.finished.emit(SearchResultModel(df))

def load_custom_fonts():
    """Pretendard 폰트 로드"""
    # 실행 경로에서 폰트 파일 찾기
    current_dir = os.path.dirname(os.path.abspath(__file__))
    regular_font_path = os.path.join(current_dir, "Pretendard-Regular.otf")
    bold_font_path = os.path.join(current_dir, "Pretendard-Bold.otf")
    
    fonts_loaded = []
    
    if os.path.exists(regular_font_path):
        font_id = QFontDatabase.addApplicationFont(regular_font_path)
        if font_id != -1:
            fonts_loaded.extend(QFontDatabase.applicationFontFamilies(font_id))
            print(f"Pretendard-Regular 폰트 로드 성공: {regular_font_path}")
    else:
        print(f"Pretendard-Regular.otf 파일을 찾을 수 없습니다: {regular_font_path}")
    
    if os.path.exists(bold_font_path):
        font_id = QFontDatabase.addApplicationFont(bold_font_path)
        if font_id != -1:
            fonts_loaded.extend(QFontDatabase.applicationFontFamilies(font_id))
            print(f"Pretendard-Bold 폰트 로드 성공: {bold_font_path}")
    else:
        print(f"Pretendard-Bold.otf 파일을 찾을 수 없습니다: {bold_font_path}")
    
    return fonts_loaded


def get_autocomplete_manager(app_context=None):
    global _autocomplete_manager
    if _autocomplete_manager is None:
        _autocomplete_manager = AutoCompleteManager(app_context)  # 1회만 생성
    return _autocomplete_manager

class ModernMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NAIA v2.0.0 Dev")
        self.setGeometry(100, 100, 1900, 1000)
        
        # 어두운 테마 적용
        self.setStyleSheet(CUSTOM["main"])
        
        # 새로 추가: 파라미터 확장 상태 추적
        self.params_expanded = False

        # 🆕 모듈 시스템 관련 변수 추가
        self.middle_section_controller = None
        self.automation_module = None
        # [신규] 자동 생성 중복 방지를 위한 플래그
        self.auto_generation_in_progress = False
        self.last_auto_generation_time = 0
        self.last_image_generation_time = 0

        #  검색 결과를 저장할 변수 및 컨트롤러 초기화
        self.search_results = SearchResultModel()
        self.search_controller = SearchController()
        self.search_controller.search_progress.connect(self.update_search_progress)
        self.search_controller.partial_search_result.connect(self.on_partial_search_result) # 이 줄 추가
        self.search_controller.search_complete.connect(self.on_search_complete)
        self.search_controller.search_error.connect(self.on_search_error)

        self.image_window = None 
        # [신규] 데이터 및 와일드카드 관리자 초기화
        self.tag_data_manager = TagDataManager()
        self.wildcard_manager = WildcardManager()
        self.app_context = AppContext(self, self.wildcard_manager, self.tag_data_manager)

        self.init_ui()
        
        # MiddleSectionController가 모듈 인스턴스들을 가지고 있음
        self.middle_section_controller.initialize_modules_with_context(self.app_context)
        self.generation_controller = GenerationController(
            self.app_context,
            self.middle_section_controller.module_instances
        )
        self.app_context.middle_section_controller = self.middle_section_controller

        self.prompt_gen_controller = PromptGenerationController(self.app_context)

        self.connect_signals()
        # 🆕 메인 생성 파라미터 모드 관리자 추가
        self.generation_params_manager = GenerationParamsManager(self)
        
        # AppContext에 모드 변경 이벤트 구독
        self.app_context.subscribe_mode_swap(self.generation_params_manager.on_mode_changed)
        
        # 초기 설정 로드 (NAI 모드)
        self.generation_params_manager.load_mode_settings("NAI")

        # [신규] 앱 시작 시 마지막 상태 로드
        # self.load_generation_parameters()
        self.load_last_search_state()

        # ✅ 2. AutoCompleteManager 초기화 방식 변경
        print("🔍 AutoCompleteManager 전역 인스턴스 요청 중...")
        # 새로운 getter 패턴 사용
        self.autocomplete_manager = get_autocomplete_manager(app_context=self.app_context)

    # 자동완성 기능 사용 가능 여부를 확인하는 헬퍼 메서드
    def is_autocomplete_available(self) -> bool:
        """자동완성 기능이 사용 가능한지 확인합니다."""
        return (self.autocomplete_manager is not None and 
                hasattr(self.autocomplete_manager, '_initialized') and
                self.autocomplete_manager._initialized)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("1단계 구현 완료: 메인 스플리터 통합")
        self.status_bar.setStyleSheet(CUSTOM["status_bar"])

        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        left_panel = self.create_left_panel()
        self.image_window = self.create_right_panel()

        # 최소 너비 설정 (완전히 숨기기 전 최소 크기)
        left_panel.setMinimumWidth(720)   # 좌측 패널 최소 너비
        self.image_window.setMinimumWidth(400)  # 우측 패널 최소 너비
        
        # 선호 크기 설정 (초기 크기)
        left_panel.setMinimumSize(720, 400)   # 초기 크기 힌트
        self.image_window.setMinimumSize(800, 400)

        splitter.addWidget(left_panel)
        splitter.addWidget(self.image_window)
        splitter.setStretchFactor(0, 40)
        splitter.setStretchFactor(1, 60)

        main_layout.addWidget(splitter)

    def create_middle_section(self):
        """중간 섹션: 동적 모듈 로드 및 EnhancedCollapsibleBox 하위로 배치"""
        
        # 스크롤 영역 설정 (기존과 동일)
        middle_scroll_area = QScrollArea()
        middle_scroll_area.setWidgetResizable(True)
        middle_scroll_area.setStyleSheet(CUSTOM["middle_scroll_area"])

        # 모듈 컨테이너
        middle_container = QWidget()
        middle_layout = QVBoxLayout(middle_container)
        middle_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        middle_layout.setContentsMargins(6, 6, 6, 6)
        middle_layout.setSpacing(6)

        try:
            # 모듈 디렉토리 경로
            modules_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'modules')

            # 컨트롤러 생성 및 모듈 로드
            self.middle_section_controller = MiddleSectionController(modules_dir, self.app_context, parent=self)
            self.middle_section_controller.build_ui(middle_layout)

            # [신규] 모듈 로드 완료 후 자동화 시그널 연결
            self.connect_automation_signals()

            # 상태 메시지 업데이트
            loaded_count = len(self.middle_section_controller.module_instances)
            self.status_bar.showMessage(f"✅ 모듈 시스템 활성화: {loaded_count}개 모듈 로드 완료 (분리 기능 포함)")
            
            print(f"🎉 모듈 시스템 성공적으로 활성화! {loaded_count}개 모듈 로드됨 (분리 기능 활성화)")
            
        except Exception as e:
            print(f"❌ 모듈 시스템 오류: {e}")
            self.status_bar.showMessage(f"⚠️ 모듈 시스템 오류 - 기본 모드로 동작")
            
            # 폴백: 기본 레이블 표시
            fallback_label = QLabel("모듈 로드 중 오류가 발생했습니다.")
            fallback_label.setStyleSheet(DARK_STYLES['label_style'])
            middle_layout.addWidget(fallback_label)

        middle_scroll_area.setWidget(middle_container)
        return middle_scroll_area

    def create_left_panel(self):
        # 메인 컨테이너 위젯
        main_container = QWidget()
        main_container.setStyleSheet(DARK_STYLES['main_container'])
        
        main_layout = QVBoxLayout(main_container)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # 🚀 핵심 수정: 단일 수직 스플리터로 통합
        main_splitter = QSplitter(Qt.Orientation.Vertical)
        main_splitter.setStyleSheet(CUSTOM["main_splitter"])

        # === 상단 영역: 검색 + 프롬프트 ===
        top_container = self.create_top_section()
        main_splitter.addWidget(top_container)

        # === 중간 영역: 자동화 설정들 ===  
        middle_container = self.create_middle_section()
        main_splitter.addWidget(middle_container)

        # 스플리터 비율 설정 (상단 40%, 중간 60%)
        main_splitter.setStretchFactor(0, 40)
        main_splitter.setStretchFactor(1, 60)
        
        # 메인 레이아웃에 스플리터 추가
        main_layout.addWidget(main_splitter)

        # === 하단 영역: 확장 가능한 생성 제어 영역 ===
        bottom_area = self.create_enhanced_generation_area()
        main_layout.addWidget(bottom_area)

        return main_container

    def create_top_section(self):
        """상단 섹션: 검색 및 프롬프트 입력"""
        top_scroll_area = QScrollArea()
        top_scroll_area.setWidgetResizable(True)
        top_scroll_area.setStyleSheet(CUSTOM["top_scroll_area"])
        
        top_container = QWidget()
        top_layout = QVBoxLayout(top_container)
        top_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(6)

        # 검색 및 필터링 섹션
        search_box = CollapsibleBox("프롬프트 검색 / 필터링 / API 관리")

        # 전체 검색 레이아웃
        search_main_layout = QVBoxLayout()
        search_main_layout.setSpacing(8)
        
        # === API 관리 레이아웃 (상단) ===
        api_layout = QHBoxLayout()
        api_layout.setSpacing(6)
        
        # NAI 토글 버튼
        self.nai_toggle_btn = QPushButton("NAI")
        self.nai_toggle_btn.setCheckable(True)
        self.nai_toggle_btn.setChecked(True)  # 기본값: NAI 선택
        self.nai_toggle_btn.setFixedHeight(38)  # 32 → 38로 증가
        self.nai_toggle_btn.clicked.connect(lambda: self.toggle_search_mode("NAI"))
        
        # WEBUI 토글 버튼
        self.webui_toggle_btn = QPushButton("WEBUI")
        self.webui_toggle_btn.setCheckable(True)
        self.webui_toggle_btn.setChecked(False)
        self.webui_toggle_btn.setFixedHeight(38)  # 32 → 38로 증가
        self.webui_toggle_btn.clicked.connect(lambda: self.toggle_search_mode("WEBUI"))
        
        # API 관리 버튼
        api_manage_btn = QPushButton("API 관리")
        api_manage_btn.setFixedHeight(38)  # 32 → 38로 증가
        api_manage_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        api_manage_btn.clicked.connect(self.open_search_management)
        
        # 토글 버튼 스타일 정의 (폰트 크기 증가)
        toggle_active_style = CUSTOM["toggle_active_style"]
        toggle_inactive_style = CUSTOM["toggle_inactive_style"]
        
        # 초기 스타일 적용
        self.nai_toggle_btn.setStyleSheet(toggle_active_style)
        self.webui_toggle_btn.setStyleSheet(toggle_inactive_style)
        
        # 스타일을 나중에 사용하기 위해 저장
        self.toggle_active_style = toggle_active_style
        self.toggle_inactive_style = toggle_inactive_style
        
        # 균일한 column 사이즈로 배치
        api_layout.addWidget(self.nai_toggle_btn, 1)  # 동일한 stretch factor
        api_layout.addWidget(self.webui_toggle_btn, 1)  # 동일한 stretch factor
        api_layout.addWidget(api_manage_btn, 1)  # 동일한 stretch factor
        
        search_main_layout.addLayout(api_layout)
        
        # === 기존 검색 레이아웃 (하단) ===
        search_layout = QVBoxLayout()
        search_layout.setSpacing(6)
        
        search_label = QLabel("검색 키워드:")
        search_label.setStyleSheet(DARK_STYLES['label_style'])
        search_layout.addWidget(search_label)
        self.search_input = QLineEdit()
        self.search_input.setStyleSheet(DARK_STYLES['compact_lineedit'])
        search_layout.addWidget(self.search_input)
        
        exclude_label = QLabel("제외 키워드:")
        exclude_label.setStyleSheet(DARK_STYLES['label_style'])
        search_layout.addWidget(exclude_label)
        self.exclude_input = QLineEdit()
        self.exclude_input.setStyleSheet(DARK_STYLES['compact_lineedit'])
        search_layout.addWidget(self.exclude_input)
        
        rating_layout = QHBoxLayout()
        rating_layout.setSpacing(8)
        
        # [수정] 체크박스들을 딕셔너리로 관리
        self.rating_checkboxes = {}
        checkboxes_map = {"Explicit": "e", "NSFW": "q", "Sensitive": "s", "General": "g"}
        for text, key in checkboxes_map.items():
            cb = QCheckBox(text)
            cb.setStyleSheet(DARK_STYLES['dark_checkbox'])
            cb.setChecked(True) # 기본적으로 모두 체크
            rating_layout.addWidget(cb)
            self.rating_checkboxes[key] = cb
        
        rating_layout.addStretch(1)

        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: 16px; margin-right: 10px;")
        rating_layout.addWidget(self.progress_label)
        
        self.search_btn = QPushButton("검색")
        self.search_btn.setStyleSheet(DARK_STYLES['primary_button'])
        rating_layout.addWidget(self.search_btn)
        search_layout.addLayout(rating_layout)
        
        # 메인 레이아웃에 검색 레이아웃 추가
        search_main_layout.addLayout(search_layout)
        
        # CollapsibleBox에 전체 레이아웃 설정
        search_box.setContentLayout(search_main_layout)
        top_layout.addWidget(search_box)

        # 검색 결과 표시 프레임
        search_result_frame = QFrame()
        search_result_frame.setStyleSheet(DARK_STYLES['compact_card'])
        search_result_layout = QHBoxLayout(search_result_frame)
        search_result_layout.setContentsMargins(10, 6, 10, 6)
        
        # [수정] 결과 레이블을 self 변수로 저장
        self.result_label1 = QLabel("검색 프롬프트 행: 0")
        self.result_label1.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-family: 'Pretendard'; font-size: 18px;")
        self.result_label2 = QLabel("남은 프롬프트 행: 0")
        self.result_label2.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-family: 'Pretendard'; font-size: 18px;")
        
        search_result_layout.addWidget(self.result_label1)
        search_result_layout.addWidget(self.result_label2)
        search_result_layout.addStretch(1)
        
        self.restore_btn = QPushButton("복원")
        self.restore_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.deep_search_btn = QPushButton("심층검색")
        self.deep_search_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        
        search_result_layout.addWidget(self.restore_btn)
        search_result_layout.addWidget(self.deep_search_btn)
        top_layout.addWidget(search_result_frame)
        
        # 메인 프롬프트 창
        prompt_tabs = QTabWidget()
        prompt_tabs.setStyleSheet(DARK_STYLES['dark_tabs'])
        prompt_tabs.setMinimumHeight(100)
        
        main_prompt_widget = QWidget()
        negative_prompt_widget = QWidget()
        
        main_prompt_layout = QVBoxLayout(main_prompt_widget)
        negative_prompt_layout = QVBoxLayout(negative_prompt_widget)
        
        main_prompt_layout.setContentsMargins(4, 4, 4, 4)
        negative_prompt_layout.setContentsMargins(4, 4, 4, 4)
        
        # [수정] 메인 프롬프트 텍스트 위젯을 self 변수로 저장
        self.main_prompt_textedit = QTextEdit()
        self.main_prompt_textedit.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.main_prompt_textedit.setPlaceholderText("메인 프롬프트를 입력하세요...")
        self.main_prompt_textedit.setMinimumHeight(100)
        main_prompt_layout.addWidget(self.main_prompt_textedit)
        
        self.negative_prompt_textedit = QTextEdit()
        self.negative_prompt_textedit.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.negative_prompt_textedit.setPlaceholderText("네거티브 프롬프트를 입력하세요...")
        self.negative_prompt_textedit.setMinimumHeight(100)
        negative_prompt_layout.addWidget(self.negative_prompt_textedit)
        
        prompt_tabs.addTab(main_prompt_widget, "메인 프롬프트")
        prompt_tabs.addTab(negative_prompt_widget, "네거티브 프롬프트 (UC)")
        top_layout.addWidget(prompt_tabs)

        top_scroll_area.setWidget(top_container)
        return top_scroll_area

    def create_enhanced_generation_area(self):
        """확장 가능한 생성 제어 영역 생성"""
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        
        # 1. 투명 배경의 확장 버튼 프레임
        self.expand_button_frame = QFrame(container)
        self.expand_button_frame.setStyleSheet(DARK_STYLES['transparent_frame'])
        expand_button_layout = QHBoxLayout(self.expand_button_frame)
        expand_button_layout.setContentsMargins(8, 4, 8, 4)
        
        # 왼쪽 스페이서
        expand_button_layout.addStretch(1)
        
        # 확장/축소 토글 버튼
        self.params_toggle_button = QPushButton("▲ 생성 파라미터 열기")
        self.params_toggle_button.setStyleSheet(DARK_STYLES['expand_toggle_button'])
        self.params_toggle_button.clicked.connect(self.toggle_params_panel)
        expand_button_layout.addWidget(self.params_toggle_button)
        
        # 오른쪽 스페이서
        expand_button_layout.addStretch(1)
        
        container_layout.addWidget(self.expand_button_frame)
        
        # 2. 확장 가능한 생성 파라미터 영역
        self.params_area = QWidget(container)
        self.params_area.setVisible(False)  # 기본적으로 숨김
        self.params_area.setStyleSheet(DARK_STYLES['compact_card'])
        
        params_layout = QVBoxLayout(self.params_area)
        params_layout.setContentsMargins(12, 12, 12, 12)
        params_layout.setSpacing(8)
        
        # 생성 파라미터 내용 - 강화된 버전
        params_title = QLabel("🎛️ 생성 파라미터")
        params_title.setStyleSheet(CUSTOM["params_title"])
        params_layout.addWidget(params_title)
        
        params_grid = QGridLayout()
        params_grid.setSpacing(8)
        
        # 생성 파라미터 라벨들을 위한 공통 스타일
        param_label_style = CUSTOM["param_label_style"]
        
        # === 첫 번째 행: 모델 선택 + 스케줄러 ===
        model_label = QLabel("모델 선택:")
        model_label.setStyleSheet(param_label_style)
        params_grid.addWidget(model_label, 0, 0)
        
        self.model_combo = QComboBox() # QComboBox -> self.model_combo
        self.model_combo.addItems(["NAID4.5F", "NAID4.5C", "NAID4.0F","NAID4.0C", "NAID3"])
        self.model_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        params_grid.addWidget(self.model_combo, 0, 1)
        
        scheduler_label = QLabel("스케줄러:")
        scheduler_label.setStyleSheet(param_label_style)
        params_grid.addWidget(scheduler_label, 0, 2)
        
        self.scheduler_combo = QComboBox()
        self.scheduler_combo.addItems(["karras","native", "exponential", "polyexponential"])
        self.scheduler_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        params_grid.addWidget(self.scheduler_combo, 0, 3)
        
        # === 두 번째 행: 해상도 + 랜덤 해상도 + 관리 ===
        resolution_label = QLabel("해상도:")
        resolution_label.setStyleSheet(param_label_style)
        params_grid.addWidget(resolution_label, 1, 0)
        
        self.resolution_combo = QComboBox() # QComboBox -> self.resolution_combo
        self.resolutions = ["1024 x 1024", "960 x 1088", "896 x 1152", "832 x 1216", "1088 x 960", "1152 x 896", "1216 x 832"]
        self.resolution_combo.addItems(self.resolutions)
        self.resolution_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.resolution_combo.setEditable(True)
        params_grid.addWidget(self.resolution_combo, 1, 1)
        
        # 해상도 관련 컨트롤들
        resolution_controls_layout = QHBoxLayout()
        resolution_controls_layout.setSpacing(6)
        
        self.random_resolution_checkbox = QCheckBox("랜덤 해상도")
        self.random_resolution_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        resolution_controls_layout.addWidget(self.random_resolution_checkbox)
        
        manage_resolution_btn = QPushButton("관리")
        manage_resolution_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        manage_resolution_btn.setFixedHeight(36)  # 30 → 36으로 증가
        manage_resolution_btn.clicked.connect(self.open_resolution_manager)
        resolution_controls_layout.addWidget(manage_resolution_btn)
        
        resolution_controls_widget = QWidget()
        resolution_controls_widget.setLayout(resolution_controls_layout)
        params_grid.addWidget(resolution_controls_widget, 1, 2, 1, 2)  # 2칸 차지
        
        # === 세 번째 행: 스텝 수 + 샘플러 ===
        steps_label = QLabel("스텝 수:")
        steps_label.setStyleSheet(param_label_style)
        params_grid.addWidget(steps_label, 2, 0)
        
        self.steps_input = QLineEdit("28") # QLineEdit -> self.steps_input
        self.steps_input.setStyleSheet(DARK_STYLES['compact_lineedit'])
        self.steps_input.setValidator(step_validator)
        self.steps_input.setProperty("autocomplete_ignore", True) # 자동완성 무시 속성 설정
        params_grid.addWidget(self.steps_input, 2, 1)
        
        sampler_label = QLabel("샘플러:")
        sampler_label.setStyleSheet(param_label_style)
        params_grid.addWidget(sampler_label, 2, 2)
        
        self.sampler_combo = QComboBox() # QComboBox -> self.sampler_combo
        self.sampler_combo.addItems(["k_euler_ancestral","k_euler", "k_dpmpp_2s_ancestral", "k_dpmpp_2m_sde", "k_dpmpp_2m",  "k_dpmpp_sde"])
        self.sampler_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        params_grid.addWidget(self.sampler_combo, 2, 3)
        
        # === 네 번째 행: CFG Scale + CFG Rescale ===
        cfg_label = QLabel("CFG Scale:")
        cfg_label.setStyleSheet(param_label_style)
        params_grid.addWidget(cfg_label, 3, 0)
        
        self.cfg_input = QLineEdit("5.0") # QLineEdit -> self.cfg_input
        self.cfg_input.setStyleSheet(DARK_STYLES['compact_lineedit'])
        self.cfg_input.setValidator(cfg_validator)
        self.cfg_input.setProperty("autocomplete_ignore", True) # 자동완성 무시 속성 설정
        params_grid.addWidget(self.cfg_input, 3, 1)
        
        cfg_rescale_label = QLabel("CFG Rescale:")
        cfg_rescale_label.setStyleSheet(param_label_style)
        params_grid.addWidget(cfg_rescale_label, 3, 2)
        
        self.cfg_rescale_input = QLineEdit("0.4") # QLineEdit -> self.cfg_rescale_input
        self.cfg_rescale_input.setStyleSheet(DARK_STYLES['compact_lineedit'])
        self.cfg_rescale_input.setValidator(cfg_rescale_validator)
        self.cfg_rescale_input.setProperty("autocomplete_ignore", True) # 자동완성 무시 속성 설정
        params_grid.addWidget(self.cfg_rescale_input, 3, 3)

        # [신규] === 다섯 번째 행: 시드 + 시드 고정 ===
        seed_label = QLabel("시드:")
        seed_label.setStyleSheet(param_label_style)
        params_grid.addWidget(seed_label, 4, 0)
        
        self.seed_input = QLineEdit("-1")
        self.seed_input.setStyleSheet(DARK_STYLES['compact_lineedit'])
        self.seed_input.setProperty("autocomplete_ignore", True)
        params_grid.addWidget(self.seed_input, 4, 1)
        
        # 시드 관련 컨트롤들을 담을 QHBoxLayout
        seed_controls_layout = QHBoxLayout()
        seed_controls_layout.setContentsMargins(0, 0, 0, 0)
        seed_controls_layout.setSpacing(10)

        self.seed_fix_checkbox = QCheckBox("시드 고정")
        self.seed_fix_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        
        # "해상도 자동 맞춤" 체크박스 추가
        self.auto_fit_resolution_checkbox = QCheckBox("해상도 자동 맞춤")
        self.auto_fit_resolution_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])

        seed_controls_layout.addWidget(self.seed_fix_checkbox)
        seed_controls_layout.addWidget(self.auto_fit_resolution_checkbox)
        seed_controls_layout.addStretch()

        params_grid.addLayout(seed_controls_layout, 4, 2, 1, 2) # 2칸 차지
        
        params_layout.addLayout(params_grid)
        
        # === NAID Option 라인 ===
        naid_options_layout = QHBoxLayout()
        naid_options_layout.setSpacing(12)
        
        # NAID Option 라벨
        naid_options_label = QLabel("NAID Option:")
        naid_options_label.setStyleSheet(CUSTOM["naid_options_label"])
        naid_options_layout.addWidget(naid_options_label)
        
        # 4개의 NAID 옵션 체크박스
        naid_options = ["SMEA", "DYN", "VAR+", "DECRISP"]
        self.advanced_checkboxes = {}
        
        for option in naid_options:
            checkbox = QCheckBox(option)
            checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
            naid_options_layout.addWidget(checkbox)
            self.advanced_checkboxes[option] = checkbox
        
        naid_options_layout.addStretch()  # 오른쪽 여백
        params_layout.addLayout(naid_options_layout)
        
        # === Custom API 파라미터 섹션 ===
        self.custom_api_checkbox = QCheckBox("Add custom/override api parameters")
        self.custom_api_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.custom_api_checkbox.toggled.connect(self.toggle_custom_api_params)
        params_layout.addWidget(self.custom_api_checkbox)
        
        # Custom Script 텍스트박스 (기본적으로 숨김)
        self.custom_script_textbox = QTextEdit()
        self.custom_script_textbox.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.custom_script_textbox.setPlaceholderText("Custom API parameters (JSON format)...")
        self.custom_script_textbox.setFixedHeight(80)
        self.custom_script_textbox.setVisible(False)  # 기본적으로 숨김
        self.custom_script_textbox.setProperty("autocomplete_ignore", True)
        params_layout.addWidget(self.custom_script_textbox)
        
        container_layout.addWidget(self.params_area)
        
        # 3. 기존 생성 제어 프레임
        generation_control_frame = QFrame(container)
        generation_control_frame.setStyleSheet(DARK_STYLES['compact_card'])
        gen_control_layout = QVBoxLayout(generation_control_frame)
        gen_control_layout.setContentsMargins(12, 12, 12, 12)
        gen_control_layout.setSpacing(8)
        
        gen_button_layout = QHBoxLayout()
        gen_button_layout.setSpacing(6)
        
        self.random_prompt_btn = QPushButton("랜덤/다음 프롬프트")
        self.random_prompt_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        gen_button_layout.addWidget(self.random_prompt_btn)
        
        self.generate_button_main = QPushButton("🎨 이미지 생성 요청")
        self.generate_button_main.setStyleSheet(DARK_STYLES['primary_button'])
        gen_button_layout.addWidget(self.generate_button_main)
        
        gen_control_layout.addLayout(gen_button_layout)
        gen_control_layout.addSpacing(12)
        
        gen_checkbox_layout = QHBoxLayout()
        gen_checkbox_layout.setSpacing(12)
        
        self.generation_checkboxes = {}
        checkbox_texts = ["프롬프트 고정", "자동 생성", "터보 옵션", "와일드카드 단독 모드"]
        for cb_text in checkbox_texts:
            cb = QCheckBox(cb_text)
            cb.setStyleSheet(DARK_STYLES['dark_checkbox'])
            gen_checkbox_layout.addWidget(cb)
            self.generation_checkboxes[cb_text] = cb

        gen_checkbox_layout.addStretch()
        gen_control_layout.addLayout(gen_checkbox_layout)
        
        container_layout.addWidget(generation_control_frame)
        
        return container
    
    def toggle_params_panel(self):
        """생성 파라미터 패널 토글"""
        if self.params_expanded:
            # 축소
            self.params_area.setVisible(False)
            self.params_toggle_button.setText("▲ 생성 파라미터 열기")
            self.params_expanded = False
            self.status_bar.showMessage("생성 파라미터 패널이 축소되었습니다.")
        else:
            # 확장
            self.params_area.setVisible(True)
            self.params_toggle_button.setText("▼ 생성 파라미터 닫기")
            self.params_expanded = True
            self.status_bar.showMessage("생성 파라미터 패널이 확장되었습니다.")
    
    def toggle_custom_api_params(self, checked):
        """Custom API 파라미터 텍스트박스 토글"""
        self.custom_script_textbox.setVisible(checked)
        if checked:
            self.status_bar.showMessage("Custom API 파라미터 입력이 활성화되었습니다.")
        else:
            self.status_bar.showMessage("Custom API 파라미터 입력이 비활성화되었습니다.")
    
    def toggle_search_mode(self, mode):
        """NAI/WEBUI 검색 모드 토글 (수정된 버전)"""
        if mode == "NAI":
            self.nai_toggle_btn.setChecked(True)
            self.webui_toggle_btn.setChecked(False)
            self.nai_toggle_btn.setStyleSheet(self.toggle_active_style)
            self.webui_toggle_btn.setStyleSheet(self.toggle_inactive_style)
            self.status_bar.showMessage("NAI 모드로 전환되었습니다.")
            self.app_context.set_api_mode(mode)
        elif mode == "WEBUI":
            # WEBUI 모드 선택 시 연결 테스트 수행
            try:
                api_management = None
                tab_was_open = False
                
                if hasattr(self, 'image_window') and self.image_window:
                    # 이미 열린 API 관리 탭 찾기
                    for i in range(self.image_window.tab_widget.count()):
                        widget = self.image_window.tab_widget.widget(i)
                        if hasattr(widget, '__class__') and 'APIManagementWindow' in widget.__class__.__name__:
                            api_management = widget
                            tab_was_open = True
                            break
                    
                    # 🔒 스텔스 모드: API 관리 탭이 없으면 임시로 생성 (UI에 표시하지 않음)
                    if not api_management:
                        from ui.api_management_window import APIManagementWindow
                        api_management = APIManagementWindow(self.app_context, self)
                    
                    if api_management and hasattr(api_management, 'webui_url_input'):
                        # 저장된 WEBUI URL 가져오기 (스텔스 모드에서는 키링에서 직접 로드)
                        if not tab_was_open:
                            # 탭이 열려있지 않은 경우 키링에서 직접 가져오기
                            webui_url = self.app_context.secure_token_manager.get_token('webui_url')
                        else:
                            # 탭이 열려있는 경우 UI에서 가져오기
                            webui_url = api_management.webui_url_input.text().strip()
                        
                        if not webui_url:
                            # URL이 없는 경우에만 API 관리 창으로 이동
                            self.status_bar.showMessage("⚠️ WEBUI URL을 먼저 설정해주세요.", 5000)
                            self.open_search_management()
                            return
                        
                        # WebUI 연결 테스트
                        self.status_bar.showMessage("🔄 WEBUI 연결을 확인하는 중...", 3000)
                        validated_url = self.test_webui(webui_url)
                        
                        if validated_url:
                            # ✅ 연결 성공 시 WEBUI 모드로 전환
                            self.nai_toggle_btn.setChecked(False)
                            self.webui_toggle_btn.setChecked(True)
                            self.nai_toggle_btn.setStyleSheet(self.toggle_inactive_style)
                            self.webui_toggle_btn.setStyleSheet(self.toggle_active_style)
                            self.status_bar.showMessage(f"✅ WEBUI 모드로 전환되었습니다. ({validated_url})", 5000)
                            
                            # 검증된 URL을 키링에 저장
                            clean_url = validated_url.replace('https://', '').replace('http://', '')
                            self.app_context.secure_token_manager.save_token('webui_url', clean_url)
                            
                            # 🔒 연결 성공 시: 스텔스 모드로 생성된 경우 탭을 닫지 않음 (원래 없었으므로)
                            # 기존에 열려있던 탭인 경우에만 선택적으로 닫기 가능 (여기서는 유지)
                            
                        else:
                            # ❌ 연결 실패 시에만 API 관리 창으로 이동
                            self.status_bar.showMessage(f"❌ WEBUI 연결 실패: {webui_url}", 5000)
                            
                            # 스텔스 모드로 생성된 경우에만 탭 열기
                            if not tab_was_open:
                                self.open_search_management()
                            
                            # 오류 메시지 표시
                            QMessageBox.critical(
                                self, 
                                "WEBUI 연결 실패", 
                                f"WebUI 서버에 연결할 수 없습니다.\n\n"
                                f"확인할 사항:\n"
                                f"• WebUI가 실행 중인지 확인\n"
                                f"• 주소가 올바른지 확인: {webui_url}\n"
                                f"• API 접근이 활성화되어 있는지 확인\n\n"
                                f"API 관리 탭에서 올바른 주소를 입력해주세요."
                            )
                    else:
                        # API 관리 기능을 사용할 수 없는 경우
                        self.status_bar.showMessage("⚠️ API 관리 기능을 사용할 수 없습니다.", 5000)
                        self.open_search_management()
                self.app_context.set_api_mode(mode)
            except Exception as e:
                print(f"❌ WEBUI 모드 전환 중 오류: {e}")
                self.status_bar.showMessage(f"❌ WEBUI 모드 전환 실패: {str(e)}", 5000)
                self.open_search_management()

    def open_search_management(self):
        if self.image_window and hasattr(self.image_window, 'add_api_management_tab'):
            self.image_window.add_api_management_tab()
            self.status_bar.showMessage("⚙️ API 관리 탭으로 이동했습니다.", 3000)
        else:
            self.status_bar.showMessage("⚠️ API 관리 탭을 열 수 없습니다.", 5000)

    def create_right_panel(self):
       # [수정] 생성자에 main_window 참조를 전달합니다.
       right_view_instance = RightView(self.app_context)
       return right_view_instance

    def get_dark_style(self, style_key: str) -> str:
        return DARK_STYLES.get(style_key, '')
    
    def get_dark_color(self, color_key: str) -> str:
        return DARK_COLORS.get(color_key, '#FFFFFF')

    def connect_signals(self):
        self.search_btn.clicked.connect(self.trigger_search)
        self.restore_btn.clicked.connect(self.restore_search_results)
        self.deep_search_btn.clicked.connect(self.open_depth_search_tab)
        self.random_prompt_btn.clicked.connect(self.trigger_random_prompt)
        self.image_window.instant_generation_requested.connect(self.on_instant_generation_requested)
        self.generate_button_main.clicked.connect(
            self.generation_controller.execute_generation_pipeline
        )
        self.prompt_gen_controller.prompt_generated.connect(self.on_prompt_generated)
        self.prompt_gen_controller.generation_error.connect(self.on_generation_error)
        self.prompt_gen_controller.prompt_popped.connect(self.on_prompt_popped)
        self.prompt_gen_controller.resolution_detected.connect(self.on_resolution_detected)
        self.image_window.load_prompt_to_main_ui.connect(self.set_positive_prompt)
        self.image_window.instant_generation_requested.connect(self.on_instant_generation_requested)

    def set_positive_prompt(self, prompt: str):
        """전달받은 프롬프트를 메인 UI의 프롬프트 입력창에 설정합니다."""
        self.main_prompt_textedit.setPlainText(prompt)
        print(f"📋 프롬프트 불러오기 완료.")
        self.status_bar.showMessage("프롬프트가 성공적으로 로드되었습니다.", 3000)

    # [수정] get_main_parameters 메서드 완성
    def get_main_parameters(self) -> dict:
        """메인 UI의 파라미터들을 수집하여 딕셔너리로 반환합니다."""
        params = {}
        try:
            width, height = map(int, self.resolution_combo.currentText().split('x'))
            if self.seed_fix_checkbox.isChecked():
                try:
                    seed_value = int(self.seed_input.text())
                except ValueError:
                    seed_value = -1
            else:
                seed_value = random.randint(0, 9999999999)
                self.seed_input.setText(str(seed_value))

            processed_input = ', '.join([item.strip() for item in self.main_prompt_textedit.toPlainText().split(',') if item.strip()])
            processed_negative_prompt = ', '.join([item.strip() for item in self.negative_prompt_textedit.toPlainText().split(',') if item.strip()])

            params = {
                "action" : "generate",
                "access_token" : "",
                "input" : processed_input,
                "negative_prompt" : processed_negative_prompt,
                "model": self.model_combo.currentText(),
                "scheduler": self.scheduler_combo.currentText(),
                "sampler": self.sampler_combo.currentText(),
                "resolution": self.resolution_combo.currentText(), # UI 표시용
                "width": width,
                "height": height,
                "seed": seed_value,
                "random_resolution": self.random_resolution_checkbox.isChecked(),
                "steps": int(self.steps_input.text()),
                "cfg_scale": float(self.cfg_input.text()),
                "cfg_rescale": float(self.cfg_rescale_input.text()),
                "SMEA": self.advanced_checkboxes["SMEA"].isChecked(),
                "DYN": self.advanced_checkboxes["DYN"].isChecked(),
                "VAR+": self.advanced_checkboxes["VAR+"].isChecked(),
                "DECRISP": self.advanced_checkboxes["DECRISP"].isChecked(),
                "use_custom_api_params": self.custom_api_checkbox.isChecked(),
                "custom_api_params": self.custom_script_textbox.toPlainText()
            }
        except (ValueError, KeyError) as e:
            print(f"❌ 파라미터 수집 오류: {e}")
            # 오류 발생 시 사용자에게 알림
            self.status_bar.showMessage(f"⚠️ 생성 파라미터 값에 오류가 있습니다: {e}", 5000)
            return {} # 빈 딕셔너리 반환

        return params

    # update_ui_with_result 메서드 수정
    def update_ui_with_result(self, result: dict):
        """APIService의 결과를 받아 UI에 업데이트하고 히스토리에 추가"""
        if self.image_window:
            image_object = result.get("image")
            info_text = result.get("info", "")
            source_row = result.get("source_row")
            raw_bytes = result.get("raw_bytes")

            if image_object is None:
                return

            # 현재 결과 업데이트
            self.image_window.update_image(image_object)
            self.image_window.update_info(info_text)
            
            # 히스토리에 추가
            self.image_window.add_to_history(image_object, raw_bytes, info_text, source_row)
            
        self.status_bar.showMessage("🎉 생성 완료!")
        
        # [수정] 자동화 모듈에서 반복 생성 처리
        if self.automation_module:
            # 반복 생성 처리 후 다음 프롬프트 진행 여부 확인
            should_proceed_to_next = self.automation_module.notify_generation_completed()
            
            # 반복이 완료되지 않았으면 자동 생성 사이클 중단
            if should_proceed_to_next is False:
                return  # 동일 프롬프트 반복 중이므로 다음 프롬프트로 진행하지 않음
        
        # [신규] 자동화 지연 시간 적용 후 자동 생성 체크 (반복 완료 시에만)
        if self.automation_module and self.automation_module.automation_controller.is_running:
            delay = self.automation_module.get_generation_delay()
            if delay > 0:
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(int(delay * 1000), self._check_and_trigger_auto_generation)
            else:
                self._check_and_trigger_auto_generation()
        else:
            # 기존 자동 생성 사이클 체크
            self._check_and_trigger_auto_generation()

    def _check_and_trigger_auto_generation(self):
        """자동 생성 조건을 확인하고 조건이 만족되면 다음 사이클을 시작합니다."""
        try:
            # [신규] 반복 생성 중인지 확인 - 반복 중이면 자동 생성 건너뛰기
            if (self.automation_module and 
                hasattr(self.automation_module, 'current_repeat_count') and 
                self.automation_module.current_repeat_count > 0):
                print(f"🔁 반복 생성 중이므로 자동 생성 건너뜀 (현재 반복: {self.automation_module.current_repeat_count})")
                return
            
            # [신규] 중복 실행 방지 - 시간 기반 체크
            import time
            current_time = time.time()
            if self.auto_generation_in_progress or (current_time - self.last_auto_generation_time) < 1.0:
                print(f"⚠️ 자동 생성 중복 방지: in_progress={self.auto_generation_in_progress}, time_diff={current_time - self.last_auto_generation_time:.2f}s")
                return
            
            # 조건 확인: "자동 생성"이 체크되어 있고 "프롬프트 고정"이 체크되어 있지 않음
            auto_generate_checkbox = self.generation_checkboxes.get("자동 생성")
            prompt_fixed_checkbox = self.generation_checkboxes.get("프롬프트 고정")
            
            if not auto_generate_checkbox:
                return  # 자동 생성 체크박스가 없으면 종료
                
            if auto_generate_checkbox.isChecked() and not prompt_fixed_checkbox.isChecked():
                # 검색 결과가 있는지 확인
                if self.search_results.is_empty():
                    self.status_bar.showMessage("⚠️ 검색 결과가 없어 자동 생성을 중단합니다.")
                    # 자동화 중단 (자동화가 활성화되어 있는 경우만)
                    if self.automation_module and self.automation_module.automation_controller.is_running:
                        self.automation_module.stop_automation()
                    return
                
                # [신규] 자동 생성 플래그 설정
                self.auto_generation_in_progress = True
                self.last_auto_generation_time = current_time
                
                self.status_bar.showMessage("🔄 자동 생성: 다음 프롬프트 생성 중...")
                
                # 다음 프롬프트 생성 요청
                settings = {
                    'prompt_fixed': False,  # 자동 생성 시에는 항상 False
                    'auto_generate': True,
                    'turbo_mode': self.generation_checkboxes["터보 옵션"].isChecked(),
                    'wildcard_standalone': self.generation_checkboxes["와일드카드 단독 모드"].isChecked(),
                    "auto_fit_resolution": self.auto_fit_resolution_checkbox.isChecked()
                }
                
                # 프롬프트 생성 컨트롤러에 자동 생성 플래그 설정
                self.prompt_gen_controller.auto_generation_requested = True
                self.prompt_gen_controller.generate_next_prompt(self.search_results, settings)
                
        except Exception as e:
            # [신규] 오류 시 플래그 해제
            self.auto_generation_in_progress = False
            self.status_bar.showMessage(f"❌ 자동 생성 체크 오류: {e}")
            print(f"자동 생성 체크 오류: {e}")

    # [신규] 자동화 활성 상태 확인 메서드 추가
    def get_automation_active_status(self) -> bool:
        """현재 자동화가 활성화되어 있는지 확인"""
        try:
            if self.automation_module and self.automation_module.automation_controller:
                return self.automation_module.automation_controller.is_running
            return False
        except Exception as e:
            print(f"⚠️ 자동화 활성 상태 확인 실패: {e}")
            return False


    def trigger_search(self):
        """'검색' 버튼 클릭 시 컨트롤러를 통해 검색을 시작하는 슬롯"""
        self.search_btn.setEnabled(False)
        self.search_btn.setText("검색 중...")
        
        # [수정] 새 검색 시작 시 진행률 레이블을 다시 표시
        self.progress_label.setText("0/0") # 초기 텍스트 설정
        self.progress_label.setVisible(True)
        
        # [신규] 새 검색 시작 시 기존 결과 초기화
        self.search_results = SearchResultModel()
        self.result_label1.setText("검색 프롬프트 행: 0")

        # UI에서 검색 파라미터 수집
        search_params = {
            'query': self.search_input.text(),
            'exclude_query': self.exclude_input.text(),
            'rating_e': self.rating_checkboxes['e'].isChecked(),
            'rating_q': self.rating_checkboxes['q'].isChecked(),
            'rating_s': self.rating_checkboxes['s'].isChecked(),
            'rating_g': self.rating_checkboxes['g'].isChecked(),
        }
        
        try:
            save_dir = 'save'
            os.makedirs(save_dir, exist_ok=True)
            with open(os.path.join(save_dir, 'search_tags.json'), 'w', encoding='utf-8') as f:
                json.dump(search_params, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.status_bar.showMessage(f"⚠️ 검색어 저장 실패: {e}", 5000)

        self.search_controller.start_search(search_params)

    def update_search_progress(self, completed: int, total: int):
        """검색 진행률에 따라 UI 업데이트"""
        percentage = int((completed / total) * 100) if total > 0 else 0
        self.progress_label.setText(f"{completed}/{total}")
        self.search_btn.setText(f"검색 중 ({percentage}%)")

    def on_partial_search_result(self, partial_df: pd.DataFrame):
        """부분 검색 결과를 받아 UI에 즉시 반영"""
        self.search_results.append_dataframe(partial_df)
        self.result_label1.setText(f"검색 프롬프트 행: {self.search_results.get_count()}")
        self.result_label2.setText(f"남은 프롬프트 행: {self.search_results.get_count()}")

    def on_search_complete(self, total_count: int):
        """검색 완료 시 호출되는 슬롯, 결과 파일 저장"""
        self.search_btn.setEnabled(True)
        self.search_btn.setText("검색")
        self.progress_label.setVisible(False)
        self.status_bar.showMessage(f"✅ 검색 완료! {total_count}개의 결과를 찾았습니다.", 5000)

        # [신규] 검색 결과 Parquet 파일로 저장
        if not self.search_results.is_empty():
            try:
                self.search_results.get_dataframe().to_parquet('naia_temp_rows.parquet')
            except Exception as e:
                self.status_bar.showMessage(f"⚠️ 결과 파일 저장 실패: {e}", 5000)

    def on_search_error(self, error_message: str):
        """검색 오류 발생 시 호출되는 슬롯"""
        self.search_btn.setEnabled(True)
        self.search_btn.setText("검색")
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.critical(self, "검색 오류", error_message)
        self.status_bar.showMessage(f"❌ 검색 중 오류 발생", 5000)

    # [신규] 앱 시작 시 상태를 로드하는 메서드
    def load_last_search_state(self):
        """앱 시작 시 search_tags.json과 naia_temp_rows.parquet을 로드합니다."""
        # 1. 검색어 로드
        query_file = os.path.join('save', 'search_tags.json')
        if os.path.exists(query_file):
            try:
                with open(query_file, 'r', encoding='utf-8') as f:
                    params = json.load(f)
                self.search_input.setText(params.get('query', ''))
                self.exclude_input.setText(params.get('exclude_query', ''))
                self.rating_checkboxes['e'].setChecked(params.get('rating_e', True))
                self.rating_checkboxes['q'].setChecked(params.get('rating_q', True))
                self.rating_checkboxes['s'].setChecked(params.get('rating_s', True))
                self.rating_checkboxes['g'].setChecked(params.get('rating_g', True))
            except Exception as e:
                self.status_bar.showMessage(f"⚠️ 이전 검색어 로드 실패: {e}", 5000)
                
        # 2. 결과 Parquet 파일 비동기 로드
        result_file = 'naia_temp_rows.parquet'
        if os.path.exists(result_file):
            self.status_bar.showMessage("이전 검색 결과를 불러오는 중...", 3000)
            self.load_thread = QThread()
            self.loader = ParquetLoader()
            self.loader.moveToThread(self.load_thread)
            self.load_thread.started.connect(lambda: self.loader.run(result_file))
            self.loader.finished.connect(self.on_previous_results_loaded)
            self.load_thread.finished.connect(self.load_thread.deleteLater)
            self.load_thread.start()

    def restore_search_results(self):
        """'naia_temp_rows.parquet' 파일이 있으면 비동기로 로드합니다."""
        result_file = 'naia_temp_rows.parquet'
        if os.path.exists(result_file):
            self.status_bar.showMessage("이전 검색 결과를 복원하는 중...", 3000)
            
            # 기존 앱 시작 시 사용했던 비동기 로더 재활용
            self.load_thread = QThread()
            self.loader = ParquetLoader()
            self.loader.moveToThread(self.load_thread)
            self.load_thread.started.connect(lambda: self.loader.run(result_file))
            self.loader.finished.connect(self.on_previous_results_loaded)
            self.load_thread.finished.connect(self.load_thread.deleteLater)
            self.load_thread.start()
        else:
            self.status_bar.showMessage("⚠️ 복원할 검색 결과 파일(naia_temp_rows.parquet)이 없습니다.", 5000)


    def on_previous_results_loaded(self, result_model: SearchResultModel):
        """비동기로 로드된 이전 검색 결과를 UI에 적용"""
        self.search_results.append_dataframe(result_model.get_dataframe())
        self.search_results.deduplicate()
        count = self.search_results.get_count()
        self.result_label1.setText(f"검색 프롬프트 행: {count}")
        self.result_label2.setText(f"남은 프롬프트 행: {count}")
        self.status_bar.showMessage(f"✅ 이전 검색 결과 {count}개를 불러왔습니다.", 5000)
        self.load_thread.quit()         

    def open_depth_search_tab(self):
        """심층 검색 탭을 열거나, 이미 열려있으면 해당 탭으로 전환"""
        if self.search_results.is_empty():
            return
            
        # RightView에 심층 검색 탭 추가 요청
        if self.image_window and hasattr(self.image_window, 'add_depth_search_tab'):
            self.image_window.add_depth_search_tab(self.search_results, self)

    def on_depth_search_results_assigned(self, new_search_result: SearchResultModel):
        """심층 검색 탭에서 할당된 결과를 메인 UI에 반영"""
        self.search_results = new_search_result
        count = self.search_results.get_count()
        self.result_label1.setText(f"검색 프롬프트 행: {count}")
        self.result_label2.setText(f"남은 프롬프트 행: {count}")
        self.status_bar.showMessage(f"✅ 심층 검색 결과 {count}개가 메인에 할당되었습니다.", 5000)

    # --- [신규] 프롬프트 생성 관련 메서드들 ---
    def on_instant_generation_requested(self, tags_dict: dict | pd.Series):
        """WebView에서 추출된 태그로 즉시 프롬프트를 생성합니다."""
        self.status_bar.showMessage("추출된 태그로 프롬프트 생성 중...")

        # 현재 UI의 생성 설정값들을 가져옴
        settings = {
            'prompt_fixed': self.generation_checkboxes["프롬프트 고정"].isChecked(),
            'auto_generate': self.generation_checkboxes["자동 생성"].isChecked(),
            'turbo_mode': self.generation_checkboxes["터보 옵션"].isChecked(),
            'wildcard_standalone': self.generation_checkboxes["와일드카드 단독 모드"].isChecked()
        }

        # 컨트롤러에 즉시 생성을 요청
        self.prompt_gen_controller.generate_instant_source(tags_dict, settings)

    def trigger_random_prompt(self):
        """[랜덤/다음 프롬프트] 버튼 클릭 시 컨트롤러를 통해 프롬프트 생성을 시작"""
        self.random_prompt_btn.setEnabled(False)
        self.status_bar.showMessage("다음 프롬프트를 생성 중...")

        # UI에서 생성 관련 설정값들을 수집
        settings = {
            'prompt_fixed': self.generation_checkboxes["프롬프트 고정"].isChecked(),
            'auto_generate': self.generation_checkboxes["자동 생성"].isChecked(),
            'turbo_mode': self.generation_checkboxes["터보 옵션"].isChecked(),
            'wildcard_standalone': self.generation_checkboxes["와일드카드 단독 모드"].isChecked(),
            "auto_fit_resolution": self.auto_fit_resolution_checkbox.isChecked()
        }
        self.app_context.publish("random_prompt_triggered")

        # [수정] 수동 생성 시에는 자동 생성 플래그를 False로 설정
        self.prompt_gen_controller.auto_generation_requested = False
        self.prompt_gen_controller.generate_next_prompt(self.search_results, settings)

    def _trigger_auto_image_generation(self):
        """자동 생성 모드에서 이미지 생성을 트리거합니다."""
        try:
            # [수정] is_generating 체크 제거 - 프롬프트 생성 완료 후 호출되므로 생성 가능한 상태
            # 대신 간단한 시간 기반 중복 방지만 적용
            import time
            current_time = time.time()
            
            # 마지막 이미지 생성 시간 체크 (0.5초 이내 중복 방지)
            if not hasattr(self, 'last_image_generation_time'):
                self.last_image_generation_time = 0
                
            if (current_time - self.last_image_generation_time) < 0.5:
                print(f"⚠️ 이미지 생성 중복 방지: time_diff={current_time - self.last_image_generation_time:.2f}s")
                return
                
            self.last_image_generation_time = current_time
            
            # 이미지 생성 실행
            self.generation_controller.execute_generation_pipeline()
            
        except Exception as e:
            self.status_bar.showMessage(f"❌ 자동 이미지 생성 오류: {e}")
            print(f"자동 이미지 생성 오류: {e}")
        
    # on_prompt_generated 메서드에 플래그 해제 추가
    def on_prompt_generated(self, prompt_text: str):
        """컨트롤러로부터 생성된 프롬프트를 받아 UI에 업데이트"""
        self.main_prompt_textedit.setText(prompt_text)
        
        # [신규] 새 프롬프트 생성 시 반복 카운터 리셋
        if self.automation_module:
            self.automation_module.reset_repeat_counter()
        
        # [신규] 자동 생성 플래그 해제
        self.auto_generation_in_progress = False
        
        # [수정] 자동 생성 모드인지 확인하고 처리
        if hasattr(self.prompt_gen_controller, 'auto_generation_requested') and self.prompt_gen_controller.auto_generation_requested:
            # 자동 생성 플래그 해제
            self.prompt_gen_controller.auto_generation_requested = False
            
            self.status_bar.showMessage("🔄 자동 생성: 프롬프트 생성 완료, 이미지 생성 시작...")
            
            # 자동으로 이미지 생성 실행 (약간의 지연을 두어 UI 업데이트 완료 후 실행)
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(100, self._trigger_auto_image_generation)
        else:
            # 수동 생성인 경우
            self.status_bar.showMessage("✅ 다음 프롬프트 생성 완료!", 3000)
            self.random_prompt_btn.setEnabled(True)

    def on_generation_error(self, error_message: str):
        """프롬프트 생성 중 오류 발생 시 호출"""
        # [신규] 오류 시 플래그 해제
        self.auto_generation_in_progress = False

        self.status_bar.showMessage(f"❌ 생성 오류: {error_message}", 5000)
        self.random_prompt_btn.setEnabled(True)

    def load_generation_parameters(self):
        # 기존 방식 대신 모드별 로드
        current_mode = self.app_context.get_api_mode()
        self.generation_params_manager.load_mode_settings(current_mode)
    
    def save_generation_parameters(self):
        # 기존 방식 대신 모드별 저장
        current_mode = self.app_context.get_api_mode()
        self.generation_params_manager.save_mode_settings(current_mode)
    
    def closeEvent(self, event):
        # 프로그램 종료 시 현재 모드 설정 저장
        try:
            # [추가] 분리된 모든 모듈 창 닫기 요청
            if self.middle_section_controller:
                self.middle_section_controller.close_all_detached_modules()

            current_mode = self.app_context.get_api_mode()
            self.generation_params_manager.save_mode_settings(current_mode)
            
            # 모든 모드 대응 모듈들 설정 저장
            self.app_context.mode_manager.save_all_current_mode()
            
            print(f"💾 프로그램 종료 시 {current_mode} 모드 설정 저장 완료")
            
        except Exception as e:
            print(f"❌ 설정 저장 중 오류: {e}")
        
        event.accept()

    def on_resolution_detected(self, width: int, height: int):
        """컨트롤러로부터 받은 해상도를 콤보박스에 적용합니다."""
        resolution_str = f"{width} x {height}"
        self.resolution_combo.setCurrentText(resolution_str)
        self.status_bar.showMessage(f"✅ 해상도 자동 맞춤: {resolution_str}", 3000)

    def open_resolution_manager(self):
        """해상도 관리 다이얼로그를 열고, 결과를 반영합니다."""
        dialog = ResolutionManagerDialog(self.resolutions, self)
        
        if dialog.exec():
            new_resolutions = dialog.get_updated_resolutions()
            if new_resolutions:
                self.resolutions = new_resolutions
                
                # [수정-1] 메인 UI의 콤보박스 구성 업데이트
                current_selection = self.resolution_combo.currentText()
                self.resolution_combo.clear()
                self.resolution_combo.addItems(self.resolutions)
                
                # 기존 선택 항목이 새 목록에도 있으면 유지, 없으면 첫 항목 선택
                if current_selection in self.resolutions:
                    self.resolution_combo.setCurrentText(current_selection)
                else:
                    self.resolution_combo.setCurrentIndex(0) # 첫 번째 항목을 기본값으로 설정
                
                self.status_bar.showMessage("✅ 해상도 목록이 업데이트되었습니다.", 3000)
            else:
                QMessageBox.warning(self, "경고", "해상도 목록이 비어있을 수 없습니다. 변경사항이 적용되지 않았습니다.")

    # [신규] prompt_popped 시그널을 처리할 슬롯
    def on_prompt_popped(self, remaining_count: int):
        """프롬프트가 하나 사용된 후 남은 행 개수를 UI에 업데이트합니다."""
        self.result_label2.setText(f"남은 프롬프트 행: {remaining_count}")

    # [신규] 현재 활성화된 API 모드를 반환하는 메서드
    def get_current_api_mode(self) -> str:
        """
        현재 선택된 토글 버튼에 따라 'NAI' 또는 'WEBUI' 문자열을 반환합니다.
        """
        if self.nai_toggle_btn.isChecked():
            return "NAI"
        else:
            return "WEBUI"
        
    def connect_automation_signals(self):
        """자동화 모듈과의 시그널 연결"""
        # 자동화 모듈 찾기
        if self.middle_section_controller:
            for module in self.middle_section_controller.module_instances:
                if hasattr(module, 'automation_controller'):
                    self.automation_module = module
                    break
        
        if self.automation_module:
            try:
                # 콜백 함수 등록 (시그널 대신)
                self.automation_module.set_automation_status_callback(
                    self.update_automation_status
                )
                
                self.automation_module.set_generation_delay_callback(
                    self.on_generation_delay_changed
                )
                
                # [신규] 자동 생성 상태 확인 콜백 등록
                self.automation_module.set_auto_generate_status_callback(
                    self.get_auto_generate_status
                )

                # [신규] 자동화 활성 상태 확인 콜백 등록 (누락된 부분)
                self.automation_module.set_automation_active_status_callback(
                    self.get_automation_active_status
                )
                
                print("✅ 자동화 모듈 콜백 연결 완료")
            except Exception as e:
                print(f"⚠️ 자동화 모듈 콜백 연결 실패: {e}")
        else:
            print("⚠️ 자동화 모듈을 찾을 수 없습니다.")

    # [신규] 자동 생성 상태 확인 메서드 추가
    def get_auto_generate_status(self) -> bool:
        """현재 자동 생성 체크박스 상태를 반환"""
        try:
            auto_generate_checkbox = self.generation_checkboxes.get("자동 생성")
            if auto_generate_checkbox:
                return auto_generate_checkbox.isChecked()
            return False
        except Exception as e:
            print(f"⚠️ 자동 생성 상태 확인 실패: {e}")
            return False

    def update_automation_status(self, text: str):
        """자동화 상태 텍스트 업데이트"""
        # 상태바에 자동화 진행 상황 표시
        self.status_bar.showMessage(text)

    def on_generation_delay_changed(self, delay: float):
        """생성 지연 시간 변경 시 처리"""
        print(f"생성 지연 시간 변경: {delay}초")
        # 필요시 추가 처리 로직

    def test_webui(self, url):
        """WebUI 연결 테스트 함수"""
        import requests
        # ignore http or https, check both.
        url = url.replace('http://', '').replace('https://', '').rstrip('/')
        # just checking connection, so any api is okay.
        try:
            res = requests.get(f"https://{url}/sdapi/v1/progress?skip_current_image=true", timeout=1)
            if res.status_code == 200 and 'progress' in res.json():
                return f'https://{url}'
            else:
                raise Exception('invalid status')
        except Exception:
            try:
                res = requests.get(f"http://{url}/sdapi/v1/progress?skip_current_image=true", timeout=1)
                if res.status_code == 200 and 'progress' in res.json():
                    return f'http://{url}'
                else:
                    raise Exception('invalid status')
            except Exception:
                pass
        return None


if __name__ == "__main__":
    # 기존 환경 설정들...
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "RoundPreferFloor"
    
    setup_webengine()
    app = QApplication(sys.argv)
    
    # 기존 DPI 및 폰트 설정들...
    loaded_fonts = load_custom_fonts()
    
    # 기본 폰트 설정
    if loaded_fonts:
        default_font = QFont("Pretendard", 12)
        try:
            default_font.setHintingPreference(QFont.HintingPreference.PreferDefaultHinting)
            default_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        except AttributeError:
            pass
        app.setFont(default_font)
        print(f"Pretendard 폰트가 기본 폰트로 설정되었습니다.")
    else:
        default_font = QFont("Segoe UI", 12)
        try:
            default_font.setHintingPreference(QFont.HintingPreference.PreferDefaultHinting)
            default_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        except AttributeError:
            pass
        app.setFont(default_font)
        print("Pretendard 폰트를 찾을 수 없어 시스템 기본 폰트를 사용합니다.")
    
    # 메인 윈도우 생성
    window = ModernMainWindow()

    window.show()
    sys.exit(app.exec())

## 생성형 AI 개발 가이드라인
"""
이 문서는 생성형 AI가 NAIA 프로젝트의 코드를 수정하거나 새로운 기능을 추가할 때
따라야 할 가이드라인을 정의합니다.

1.  아키텍처 존중 (Respect the Architecture)
    -   코드를 수정하기 전에, 반드시 현재의 아키텍처(AppContext, Controller, Pipeline Hook)를
        먼저 이해해야 합니다.
    -   핵심 로직을 직접 수정하기보다는, 가급적 모듈과 훅 시스템을 통해 기능을 확장하십시오.

2.  모듈성 및 단일 책임 원칙 (Modularity and Single Responsibility)
    -   새로운 기능은 독립적인 모듈 또는 클래스로 구현하는 것을 지향합니다.
    -   하나의 클래스나 메서드는 하나의 명확한 책임만 갖도록 작성하십시오.

3.  비동기 처리 (Asynchronous Processing)
    -   파일 I/O, 네트워크 요청, 무거운 연산 등 0.1초 이상 소요될 수 있는 모든 작업은
        반드시 QThread와 Worker를 사용한 비동기 방식으로 구현하여 UI 멈춤 현상을 방지해야 합니다.

4.  코드 품질 및 명확성 (Code Quality and Clarity)
    -   모든 새로운 코드에는 그 목적과 작동 방식을 설명하는 주석을 명확하게 작성해야 합니다.
    -   변수와 메서드의 이름은 그 기능을 명확히 알 수 있도록 직관적으로 작성하십시오.

5.  사용자 경험 (User Experience)
    -   모든 기능 추가 및 변경은 최종 사용자의 경험을 최우선으로 고려해야 합니다.
    -   UI는 일관된 디자인을 유지해야 하며, 사용자의 작업을 방해하지 않는 직관적인
        인터페이스를 제공해야 합니다.
"""