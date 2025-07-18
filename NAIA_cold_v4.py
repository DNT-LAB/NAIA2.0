import __init__
import sys
import os
import json
import pandas as pd
import random
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QTextEdit, QCheckBox, QComboBox, QFrame,
    QScrollArea, QSplitter, QStatusBar, QTabWidget, QMessageBox, QSpinBox, QSlider, QDoubleSpinBox
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
        self.params_expanded = False
        
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
        self.nai_toggle_btn.setFixedHeight(38)
        self.nai_toggle_btn.clicked.connect(lambda: self.toggle_search_mode("NAI"))

        # WEBUI 토글 버튼
        self.webui_toggle_btn = QPushButton("WEBUI")
        self.webui_toggle_btn.setCheckable(True)
        self.webui_toggle_btn.setChecked(False)
        self.webui_toggle_btn.setFixedHeight(38)
        self.webui_toggle_btn.clicked.connect(lambda: self.toggle_search_mode("WEBUI"))

        # 🆕 ComfyUI 토글 버튼 추가
        self.comfyui_toggle_btn = QPushButton("COMFYUI")
        self.comfyui_toggle_btn.setCheckable(True)
        self.comfyui_toggle_btn.setChecked(False)
        self.comfyui_toggle_btn.setFixedHeight(38)
        self.comfyui_toggle_btn.clicked.connect(lambda: self.toggle_search_mode("COMFYUI"))

        # API 관리 버튼
        api_manage_btn = QPushButton("API 관리")
        api_manage_btn.setFixedHeight(38)
        api_manage_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        api_manage_btn.clicked.connect(self.open_search_management)

        # 토글 버튼 스타일 정의
        toggle_active_style = CUSTOM["toggle_active_style"]
        toggle_inactive_style = CUSTOM["toggle_inactive_style"]

        # 초기 스타일 적용
        self.nai_toggle_btn.setStyleSheet(toggle_active_style)
        self.webui_toggle_btn.setStyleSheet(toggle_inactive_style)
        self.comfyui_toggle_btn.setStyleSheet(toggle_inactive_style)  # 🆕 추가

        # 스타일을 나중에 사용하기 위해 저장
        self.toggle_active_style = toggle_active_style
        self.toggle_inactive_style = toggle_inactive_style

        # 🔧 수정: 4개 버튼을 균등하게 배치 (API 관리 버튼 포함)
        api_layout.addWidget(self.nai_toggle_btn, 1)
        api_layout.addWidget(self.webui_toggle_btn, 1)
        api_layout.addWidget(self.comfyui_toggle_btn, 1)  # 🆕 추가
        api_layout.addWidget(api_manage_btn, 1)

        search_main_layout.addLayout(api_layout)
        
        # === 기존 검색 레이아웃 (하단) ===
        search_layout = QVBoxLayout()
        search_layout.setSpacing(6)
        
        search_label = QLabel("검색 키워드")
        search_label.setStyleSheet(DARK_STYLES['label_style'])
        search_layout.addWidget(search_label)
        self.search_input = QLineEdit()
        self.search_input.setStyleSheet(DARK_STYLES['compact_lineedit'])
        search_layout.addWidget(self.search_input)
        
        exclude_label = QLabel("제외 키워드")
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
        
        # 생성 파라미터 제목
        params_title = QLabel("🎛️ 생성 파라미터")
        params_title.setStyleSheet(CUSTOM["params_title"])
        params_layout.addWidget(params_title)
        
        # 파라미터 그리드 레이아웃
        params_grid = QGridLayout()
        params_grid.setSpacing(8)
        
        # 생성 파라미터 라벨들을 위한 공통 스타일
        param_label_style = CUSTOM["param_label_style"]
        
        # === 첫 번째 행: 모델 선택 + 스케줄러 ===
        model_label = QLabel("모델 선택")
        model_label.setStyleSheet(param_label_style)
        params_grid.addWidget(model_label, 0, 0)
        
        self.model_combo = QComboBox()
        self.model_combo.addItems(["NAID4.5F", "NAID4.5C", "NAID4.0F", "NAID4.0C", "NAID3"])
        self.model_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        params_grid.addWidget(self.model_combo, 0, 1)
        
        scheduler_label = QLabel("스케줄러")
        scheduler_label.setStyleSheet(param_label_style)
        params_grid.addWidget(scheduler_label, 0, 2)
        
        self.scheduler_combo = QComboBox()
        self.scheduler_combo.addItems(["karras", "native", "exponential", "polyexponential"])
        self.scheduler_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        params_grid.addWidget(self.scheduler_combo, 0, 3)
        
        # === 두 번째 행: 해상도 + 랜덤 해상도 ===
        resolution_label = QLabel("해상도")
        resolution_label.setStyleSheet(param_label_style)
        params_grid.addWidget(resolution_label, 1, 0)
        
        self.resolution_combo = QComboBox()
        self.resolutions = ["1024 x 1024", "960 x 1088", "896 x 1152", "832 x 1216", 
                        "1088 x 960", "1152 x 896", "1216 x 832"]
        self.resolution_combo.addItems(self.resolutions)
        self.resolution_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        params_grid.addWidget(self.resolution_combo, 1, 1)
        
        # 랜덤 해상도 체크박스
        self.random_resolution_checkbox = QCheckBox("랜덤 해상도")
        self.random_resolution_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        params_grid.addWidget(self.random_resolution_checkbox, 1, 2)
        
        # 해상도 관리 버튼
        resolution_manage_btn = QPushButton("해상도 관리")
        resolution_manage_btn.setStyleSheet(DARK_STYLES['compact_button'])
        resolution_manage_btn.setFixedWidth(100)
        resolution_manage_btn.clicked.connect(self.open_resolution_manager) 
        params_grid.addWidget(resolution_manage_btn, 1, 3)
        
        # === 세 번째 행: 샘플러 + Steps ===
        sampler_label = QLabel("샘플러")
        sampler_label.setStyleSheet(param_label_style)
        params_grid.addWidget(sampler_label, 2, 0)
        
        self.sampler_combo = QComboBox()
        # NAI 기본 샘플러들로 시작 (WEBUI 모드 전환 시 동적으로 변경됨)
        self.sampler_combo.addItems(["k_euler_ancestral", "k_euler", "k_dpmpp_2m", 
                                    "k_dpmpp_2s_ancestral", "k_dpmpp_sde", "ddim_v3"])
        self.sampler_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        params_grid.addWidget(self.sampler_combo, 2, 1)
        
        steps_label = QLabel("Steps")
        steps_label.setStyleSheet(param_label_style)
        params_grid.addWidget(steps_label, 2, 2)
        
        self.steps_spinbox = QSpinBox()
        self.steps_spinbox.setRange(1, 150)
        self.steps_spinbox.setValue(28)
        self.steps_spinbox.setStyleSheet(DARK_STYLES['compact_spinbox'])
        params_grid.addWidget(self.steps_spinbox, 2, 3)
        
        # === 네 번째 행: CFG Scale + CFG Rescale ===
        cfg_label = QLabel("CFG Scale")
        cfg_label.setStyleSheet(param_label_style)
        params_grid.addWidget(cfg_label, 3, 0)
        
        # CFG Scale 슬라이더 컨테이너
        cfg_container = QWidget()
        cfg_container_layout = QHBoxLayout(cfg_container)
        cfg_container_layout.setContentsMargins(0, 0, 0, 0)
        cfg_container_layout.setSpacing(5)
        
        self.cfg_scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.cfg_scale_slider.setRange(10, 100)  # 1.0 ~ 30.0을 10 ~ 300으로 표현
        self.cfg_scale_slider.setValue(50)  # 기본값 5.0
        self.cfg_scale_slider.setStyleSheet(DARK_STYLES['compact_slider'])
        cfg_container_layout.addWidget(self.cfg_scale_slider)
        
        # CFG 값 표시 라벨
        self.cfg_value_label = QLabel("5.0")
        self.cfg_value_label.setStyleSheet(param_label_style)
        self.cfg_value_label.setFixedWidth(50)  # 30 → 40으로 증가
        self.cfg_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cfg_container_layout.addWidget(self.cfg_value_label)
        
        # CFG 슬라이더 값 변경 시 라벨 업데이트
        self.cfg_scale_slider.valueChanged.connect(
            lambda value: self.cfg_value_label.setText(f"{value/10:.1f}")
        )
        
        params_grid.addWidget(cfg_container, 3, 1)
        
        # CFG Rescale (NAI 전용) 라벨
        self.cfg_rescale_label = QLabel("CFG Rescale")
        self.cfg_rescale_label.setStyleSheet(param_label_style)
        params_grid.addWidget(self.cfg_rescale_label, 3, 2)
        
        # CFG Rescale 슬라이더 컨테이너
        rescale_container = QWidget()
        rescale_container_layout = QHBoxLayout(rescale_container)
        rescale_container_layout.setContentsMargins(0, 0, 0, 0)
        rescale_container_layout.setSpacing(5)
        
        self.cfg_rescale_slider = QSlider(Qt.Orientation.Horizontal)
        self.cfg_rescale_slider.setRange(-25, 100)  # 0.0 ~ 1.0을 0 ~ 100으로 표현
        self.cfg_rescale_slider.setValue(45)  # 기본값 0.2
        self.cfg_rescale_slider.setStyleSheet(DARK_STYLES['compact_slider'])
        rescale_container_layout.addWidget(self.cfg_rescale_slider)
        
        # CFG Rescale 값 표시 라벨
        self.cfg_rescale_value_label = QLabel("0.40")
        self.cfg_rescale_value_label.setStyleSheet(param_label_style)
        self.cfg_rescale_value_label.setFixedWidth(50)  # 30 → 40으로 증가
        self.cfg_rescale_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rescale_container_layout.addWidget(self.cfg_rescale_value_label)
        
        # CFG Rescale 슬라이더 값 변경 시 라벨 업데이트
        self.cfg_rescale_slider.valueChanged.connect(
            lambda value: self.cfg_rescale_value_label.setText(f"{value/100:.2f}")
        )
        
        params_grid.addWidget(rescale_container, 3, 3)
        self.nai_rescale_ui = [self.cfg_rescale_label, rescale_container]
        
        # === 다섯 번째 행: 시드 입력 + 시드 고정 ===
        seed_label = QLabel("시드")
        seed_label.setStyleSheet(param_label_style)
        params_grid.addWidget(seed_label, 4, 0)
        
        self.seed_input = QLineEdit("0")
        self.seed_input.setStyleSheet(DARK_STYLES['compact_lineedit'])
        self.seed_input.setPlaceholderText("0 = 랜덤")
        self.seed_input.setProperty("autocomplete_ignore", True)
        params_grid.addWidget(self.seed_input, 4, 1)
        
        # 시드 관련 체크박스들
        seed_controls_layout = QHBoxLayout()
        seed_controls_layout.setSpacing(12)
        
        self.seed_fix_checkbox = QCheckBox("시드 고정")
        self.seed_fix_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        seed_controls_layout.addWidget(self.seed_fix_checkbox)
        
        self.auto_fit_resolution_checkbox = QCheckBox("자동 해상도 맞춤")
        self.auto_fit_resolution_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        seed_controls_layout.addWidget(self.auto_fit_resolution_checkbox)
        
        seed_controls_layout.addStretch()
        
        params_grid.addLayout(seed_controls_layout, 4, 2, 1, 2)  # 2칸 차지
        
        params_layout.addLayout(params_grid)
        
        # === NAID Option / Hires Option 라인 (모드별 전환) ===
        # 섹션 라벨 (모드에 따라 텍스트 변경)
        self.option_section_label = QLabel("NAID Option")
        self.option_section_label.setStyleSheet(CUSTOM["naid_options_label"])
        
        # NAI 모드 전용 레이아웃
        self.naid_option_layout = QHBoxLayout()
        self.naid_option_layout.setSpacing(12)
        self.naid_option_layout.addWidget(self.option_section_label)
        
        # 4개의 NAID 옵션 체크박스
        naid_options = ["SMEA", "DYN", "VAR+", "DECRISP"]
        self.advanced_checkboxes = {}
        
        for option in naid_options:
            checkbox = QCheckBox(option)
            checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
            self.naid_option_layout.addWidget(checkbox)
            self.advanced_checkboxes[option] = checkbox
        
        self.naid_option_layout.addStretch()  # 오른쪽 여백
        
        # 🔥 수정: WEBUI 모드 전용 레이아웃을 2행으로 분리
        self.hires_option_widget = QWidget()
        self.hires_option_widget_layout = QVBoxLayout(self.hires_option_widget)
        self.hires_option_widget_layout.setSpacing(8)
        self.hires_option_widget_layout.setContentsMargins(0, 0, 0, 0)
        
        # 첫 번째 행: Hires-fix 활성화 + 배율 + 업스케일러
        self.hires_option_layout_row1 = QHBoxLayout()
        self.hires_option_layout_row1.setSpacing(8)
        
        # Hires-fix 활성화 체크박스
        self.enable_hr_checkbox = QCheckBox("Hires-fix 활성화")
        self.enable_hr_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.hires_option_layout_row1.addWidget(self.enable_hr_checkbox)
        
        # 구분선
        separator1 = QLabel("|")
        separator1.setStyleSheet(param_label_style)
        self.hires_option_layout_row1.addWidget(separator1)
        
        # HR Scale 스핀박스
        hr_scale_label = QLabel("배율")
        hr_scale_label.setStyleSheet(param_label_style)
        self.hires_option_layout_row1.addWidget(hr_scale_label)
        
        self.hr_scale_spinbox = QDoubleSpinBox()
        self.hr_scale_spinbox.setRange(1.0, 4.0)
        self.hr_scale_spinbox.setSingleStep(0.1)
        self.hr_scale_spinbox.setValue(1.5)
        self.hr_scale_spinbox.setStyleSheet(DARK_STYLES['compact_spinbox'])
        self.hr_scale_spinbox.setFixedWidth(80)
        self.hires_option_layout_row1.addWidget(self.hr_scale_spinbox)
        
        # 구분선
        separator2 = QLabel("|")
        separator2.setStyleSheet(param_label_style)
        self.hires_option_layout_row1.addWidget(separator2)
        
        # HR 업스케일러 콤보박스
        hr_upscaler_label = QLabel("업스케일러")
        hr_upscaler_label.setStyleSheet(param_label_style)
        self.hires_option_layout_row1.addWidget(hr_upscaler_label)
        
        self.hr_upscaler_combo = QComboBox()
        self.hr_upscaler_combo.addItems(["Lanczos", "Nearest", "ESRGAN_4x", "LDSR", "SwinIR_4x"])
        self.hr_upscaler_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.hr_upscaler_combo.setMinimumWidth(120)
        self.hires_option_layout_row1.addWidget(self.hr_upscaler_combo)
        
        self.hires_option_layout_row1.addStretch()
        
        # 두 번째 행: Hires Steps + Denoising Strength
        self.hires_option_layout_row2 = QHBoxLayout()
        self.hires_option_layout_row2.setSpacing(8)
        
        # Hires Steps 스핀박스
        hires_steps_label = QLabel("Hires Steps")
        hires_steps_label.setStyleSheet(param_label_style)
        self.hires_option_layout_row2.addWidget(hires_steps_label)
        
        self.hires_steps_spinbox = QSpinBox()
        self.hires_steps_spinbox.setRange(0, 150)
        self.hires_steps_spinbox.setValue(0)  # 기본값 0 (use same as generation)
        self.hires_steps_spinbox.setStyleSheet(DARK_STYLES['compact_spinbox'])
        self.hires_steps_spinbox.setFixedWidth(80)
        self.hires_option_layout_row2.addWidget(self.hires_steps_spinbox)
        
        # 구분선
        separator3 = QLabel("|")
        separator3.setStyleSheet(param_label_style)
        self.hires_option_layout_row2.addWidget(separator3)
        
        # Denoising Strength 슬라이더 (이동)
        denoising_label = QLabel("Denoise")
        denoising_label.setStyleSheet(param_label_style)
        self.hires_option_layout_row2.addWidget(denoising_label)
        
        # Denoising 슬라이더 컨테이너
        denoising_container = QWidget()
        denoising_container_layout = QHBoxLayout(denoising_container)
        denoising_container_layout.setContentsMargins(0, 0, 0, 0)
        denoising_container_layout.setSpacing(5)
        
        self.denoising_strength_slider = QSlider(Qt.Orientation.Horizontal)
        self.denoising_strength_slider.setRange(0, 100)  # 0.0 ~ 1.0을 0~100으로 표현
        self.denoising_strength_slider.setValue(50)  # 기본값 0.5
        self.denoising_strength_slider.setStyleSheet(DARK_STYLES['compact_slider'])
        self.denoising_strength_slider.setMinimumWidth(80)
        denoising_container_layout.addWidget(self.denoising_strength_slider)
        
        # 슬라이더 값 표시 라벨
        self.denoising_value_label = QLabel("0.50")
        self.denoising_value_label.setStyleSheet(param_label_style)
        self.denoising_value_label.setFixedWidth(50)
        self.denoising_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        denoising_container_layout.addWidget(self.denoising_value_label)
        
        # 슬라이더 값 변경 시 라벨 업데이트
        self.denoising_strength_slider.valueChanged.connect(
            lambda value: self.denoising_value_label.setText(f"{value/100:.2f}")
        )
        
        self.hires_option_layout_row2.addWidget(denoising_container)
        self.hires_option_layout_row2.addStretch()
        
        # 위젯에 두 행 추가
        self.hires_option_widget_layout.addLayout(self.hires_option_layout_row1)
        self.hires_option_widget_layout.addLayout(self.hires_option_layout_row2)
        
        # Comfyui
        self.comfyui_option_widget = QWidget()
        self.comfyui_option_widget_layout = QVBoxLayout(self.comfyui_option_widget)
        self.comfyui_option_widget_layout.setContentsMargins(0, 0, 0, 0)
        self.comfyui_option_widget_layout.setSpacing(8)

        # ComfyUI 섹션 제목
        comfyui_section_label = QLabel("🎨 ComfyUI 옵션")
        comfyui_section_label.setStyleSheet(DARK_STYLES['label_style'].replace("font-size: 19px;", "font-size: 18px; font-weight: 600;"))
        self.comfyui_option_widget_layout.addWidget(comfyui_section_label)

        # v-prediction 체크박스
        self.v_prediction_checkbox = QCheckBox("v-prediction")
        self.v_prediction_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.v_prediction_checkbox.setToolTip("v-prediction 샘플링 모드를 사용합니다 (최신 AI 모델 지원)")
        self.comfyui_option_widget_layout.addWidget(self.v_prediction_checkbox)

        # ZSNR 체크박스
        self.zsnr_checkbox = QCheckBox("ZSNR (Zero SNR)")
        self.zsnr_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.zsnr_checkbox.setToolTip("Zero Signal-to-Noise Ratio 옵션을 사용합니다")
        self.comfyui_option_widget_layout.addWidget(self.zsnr_checkbox)

        # 🔧 향후 확장을 위한 업스케일러 섹션 (비활성화 상태)
        comfyui_upscaler_label = QLabel("업스케일러 (미구현)")
        comfyui_upscaler_label.setStyleSheet(DARK_STYLES['label_style'] + "color: #888888;")
        comfyui_upscaler_label.setEnabled(False)
        self.comfyui_option_widget_layout.addWidget(comfyui_upscaler_label)

        self.comfyui_upscaler_section = QWidget()
        self.comfyui_upscaler_section.setEnabled(False)
        comfyui_upscaler_layout = QHBoxLayout(self.comfyui_upscaler_section)
        comfyui_upscaler_layout.setContentsMargins(0, 0, 0, 0)

        comfyui_upscaler_combo = QComboBox()
        #comfyui_upscaler_combo.addItem("향후 업데이트 예정")
        comfyui_upscaler_combo.setStyleSheet(DARK_STYLES['compact_lineedit'] + "color: #888888;")
        comfyui_upscaler_combo.setEnabled(False)
        #comfyui_upscaler_layout.addWidget(comfyui_upscaler_combo)
        comfyui_upscaler_layout.addStretch()

        self.comfyui_option_widget_layout.addWidget(self.comfyui_upscaler_section)

        # 모드별 위젯 그룹 정리 (기존 코드 수정)
        self.naid_option_widgets = [
            self.option_section_label
        ] + list(self.advanced_checkboxes.values())

        self.hires_option_widgets = [
            self.hires_option_widget  # 전체 위젯 컨테이너만 포함
        ]

        # 🆕 ComfyUI 위젯 그룹 추가
        self.comfyui_option_widgets = [
            self.comfyui_option_widget  # 전체 ComfyUI 위젯 컨테이너
        ]

        # 기본적으로 NAI 모드로 시작 (다른 모드 위젯들 숨김)
        self.hires_option_widget.setVisible(False)
        self.comfyui_option_widget.setVisible(False)  # 🆕 ComfyUI 위젯도 기본 숨김

        # 레이아웃에 추가 (기존 코드에 ComfyUI 위젯 추가)
        params_layout.addLayout(self.naid_option_layout)
        params_layout.addWidget(self.hires_option_widget)
        params_layout.addWidget(self.comfyui_option_widget)  # 🆕 ComfyUI 위젯 추가
        
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
        
        # 🔥 수정: 체크박스 레이아웃을 화면 너비에 맞춰 조정
        gen_checkbox_layout = QHBoxLayout()
        gen_checkbox_layout.setSpacing(12)
        
        self.generation_checkboxes = {}
        checkbox_texts = ["프롬프트 고정", "자동 생성", "터보 옵션", "와일드카드 단독 모드"]
        
        # 체크박스들을 균등하게 배치
        for i, cb_text in enumerate(checkbox_texts):
            cb = QCheckBox(cb_text)
            cb.setStyleSheet(DARK_STYLES['dark_checkbox'])
            gen_checkbox_layout.addWidget(cb, 1)  # stretch factor 1로 균등 배치
            self.generation_checkboxes[cb_text] = cb
            #터보모드 미지원 상태이므로 조건문으로 block 처리
            if cb_text == "터보 옵션":
                cb.setEnabled(False)

        # 오른쪽 여백을 위한 stretch (제거하지 않음)
        gen_checkbox_layout.addStretch()
        gen_control_layout.addLayout(gen_checkbox_layout)
        
        container_layout.addWidget(generation_control_frame)
        
        return container

    def get_main_parameters(self) -> dict:
        """메인 UI의 파라미터들을 수집하여 딕셔너리로 반환합니다."""
        params = {}
        try:
            # 해상도 파싱 - 공백 처리 개선
            resolution_text = self.resolution_combo.currentText()
            if " x " in resolution_text:
                width_str, height_str = resolution_text.split(" x ")
                width, height = int(width_str.strip()), int(height_str.strip())
            else:
                # 기본값 설정
                width, height = 1024, 1024
            
            # 시드 처리
            if self.seed_fix_checkbox.isChecked():
                try:
                    seed_value = int(self.seed_input.text())
                except ValueError:
                    seed_value = -1
            else:
                seed_value = random.randint(0, 9999999999)
                self.seed_input.setText(str(seed_value))

            # 프롬프트 처리 (쉼표 기준 정리)
            processed_input = ', '.join([item.strip() for item in self.main_prompt_textedit.toPlainText().split(',') if item.strip()])
            processed_negative_prompt = ', '.join([item.strip() for item in self.negative_prompt_textedit.toPlainText().split(',') if item.strip()])

            # 🔧 수정: 실제 위젯 이름에 맞게 파라미터 수집
            params = {
                "action": "generate",
                "access_token": "",
                "input": processed_input,
                "negative_prompt": processed_negative_prompt,
                "model": self.model_combo.currentText(),
                "scheduler": self.scheduler_combo.currentText(),
                "sampler": self.sampler_combo.currentText(),
                "resolution": self.resolution_combo.currentText(),  # UI 표시용
                "width": width,
                "height": height,
                "seed": seed_value,
                "random_resolution": self.random_resolution_checkbox.isChecked(),
                "steps": self.steps_spinbox.value(),
                "cfg_scale": self.cfg_scale_slider.value() / 10.0,  # 슬라이더 값(10~300) → 실제 값(1.0~30.0)
                "cfg_rescale": self.cfg_rescale_slider.value() / 100.0,  # 슬라이더 값(0~100) → 실제 값(0.0~1.0)
                
                # 고급 체크박스들 (딕셔너리에서 직접 접근)
                "SMEA": self.advanced_checkboxes["SMEA"].isChecked(),
                "DYN": self.advanced_checkboxes["DYN"].isChecked(),
                "VAR+": self.advanced_checkboxes["VAR+"].isChecked(),
                "DECRISP": self.advanced_checkboxes["DECRISP"].isChecked(),
                
                # 커스텀 API 파라미터
                "use_custom_api_params": self.custom_api_checkbox.isChecked(),
                "custom_api_params": self.custom_script_textbox.toPlainText()
            }
            
            # 🆕 추가: WEBUI 전용 파라미터들 (해당 모드일 때만)
            if hasattr(self, 'enable_hr_checkbox'):
                params.update({
                    "enable_hr": self.enable_hr_checkbox.isChecked(),
                    "hr_scale": self.hr_scale_spinbox.value() if hasattr(self, 'hr_scale_spinbox') else 1.5,
                    "hr_upscaler": self.hr_upscaler_combo.currentText() if hasattr(self, 'hr_upscaler_combo') else "Lanczos",
                    "denoising_strength": self.denoising_strength_slider.value() / 100.0 if hasattr(self, 'denoising_strength_slider') else 0.5,
                    "hires_steps": self.hires_steps_spinbox.value() if hasattr(self, 'hires_steps_spinbox') else 0
                })
                
            # 🆕 추가: 자동 해상도 맞춤 옵션
            if hasattr(self, 'auto_fit_resolution_checkbox'):
                params["auto_fit_resolution"] = self.auto_fit_resolution_checkbox.isChecked()
                
        except (ValueError, KeyError, AttributeError) as e:
            print(f"❌ 파라미터 수집 오류: {e}")
            # 오류 발생 시 사용자에게 알림
            self.status_bar.showMessage(f"⚠️ 생성 파라미터 값에 오류가 있습니다: {e}", 5000)
            return {}  # 빈 딕셔너리 반환

        return params
    
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
        """NAI/WEBUI/COMFYUI 검색 모드 토글 (ComfyUI 지원 추가)"""
        if mode == "NAI":
            # NAI 모드 활성화
            self.nai_toggle_btn.setChecked(True)
            self.webui_toggle_btn.setChecked(False)
            self.comfyui_toggle_btn.setChecked(False)  # 🆕 추가
            
            # 스타일 적용
            self.nai_toggle_btn.setStyleSheet(self.toggle_active_style)
            self.webui_toggle_btn.setStyleSheet(self.toggle_inactive_style)
            self.comfyui_toggle_btn.setStyleSheet(self.toggle_inactive_style)  # 🆕 추가
            
            # UI 위젯 표시/숨김
            for widget in self.naid_option_widgets:
                widget.setVisible(True)
            for widget in self.hires_option_widgets:
                widget.setVisible(False)
            for widget in self.comfyui_option_widgets:  # 🆕 추가
                widget.setVisible(False)
            
            self.status_bar.showMessage("NAI 모드로 전환되었습니다.")
            self.app_context.set_api_mode(mode)
            
        elif mode == "WEBUI":
            # WEBUI 모드 선택 시 연결 테스트 수행 (기존 로직 유지)
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
                    
                    # 스텔스 모드: API 관리 탭이 없으면 임시로 생성
                    if not api_management:
                        from ui.api_management_window import APIManagementWindow
                        api_management = APIManagementWindow(self.app_context, self)
                    
                    if api_management and hasattr(api_management, 'webui_url_input'):
                        # 저장된 WEBUI URL 가져오기
                        if not tab_was_open:
                            webui_url = self.app_context.secure_token_manager.get_token('webui_url')
                        else:
                            webui_url = api_management.webui_url_input.text().strip()
                        
                        if not webui_url:
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
                            self.comfyui_toggle_btn.setChecked(False)  # 🆕 추가
                            
                            # 스타일 적용
                            self.nai_toggle_btn.setStyleSheet(self.toggle_inactive_style)
                            self.webui_toggle_btn.setStyleSheet(self.toggle_active_style)
                            self.comfyui_toggle_btn.setStyleSheet(self.toggle_inactive_style)  # 🆕 추가
                            
                            # UI 위젯 표시/숨김
                            for widget in self.naid_option_widgets:
                                widget.setVisible(False)
                            for widget in self.hires_option_widgets:
                                widget.setVisible(True)
                            for widget in self.comfyui_option_widgets:  # 🆕 추가
                                widget.setVisible(False)
                            
                            self.status_bar.showMessage(f"✅ WEBUI 모드로 전환되었습니다. ({validated_url})", 5000)
                            
                            # 검증된 URL을 키링에 저장
                            clean_url = validated_url.replace('https://', '').replace('http://', '')
                            self.app_context.secure_token_manager.save_token('webui_url', clean_url)
                            self.app_context.set_api_mode(mode)
                            
                        else:
                            # ❌ 연결 실패 시에만 API 관리 창으로 이동
                            self.status_bar.showMessage(f"❌ WEBUI 연결 실패: {webui_url}", 5000)
                            if not tab_was_open:
                                self.open_search_management()
                            
                            # 오류 메시지 표시
                            from PyQt6.QtWidgets import QMessageBox
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
                        self.status_bar.showMessage("⚠️ API 관리 기능을 사용할 수 없습니다.", 5000)
                        self.open_search_management()
                        
            except Exception as e:
                print(f"❌ WEBUI 모드 전환 중 오류: {e}")
                self.status_bar.showMessage(f"❌ WEBUI 모드 전환 실패: {str(e)}", 5000)
                self.open_search_management()
        
        elif mode == "COMFYUI":  # 🆕 ComfyUI 모드 - 동적 로딩 추가
            # ComfyUI 모드 선택 시 연결 테스트 및 동적 옵션 로드
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
                    
                    # 스텔스 모드: API 관리 탭이 없으면 임시로 생성
                    if not api_management:
                        from ui.api_management_window import APIManagementWindow
                        api_management = APIManagementWindow(self.app_context, self)
                    
                    if api_management and hasattr(api_management, 'comfyui_url_input'):
                        # 저장된 ComfyUI URL 가져오기
                        if not tab_was_open:
                            comfyui_url = self.app_context.secure_token_manager.get_token('comfyui_url')
                        else:
                            comfyui_url = api_management.comfyui_url_input.text().strip()
                        
                        if not comfyui_url:
                            self.status_bar.showMessage("⚠️ ComfyUI URL을 먼저 설정해주세요.", 5000)
                            self.open_search_management()
                            return
                        
                        # ComfyUI 연결 테스트
                        self.status_bar.showMessage("🔄 ComfyUI 연결을 확인하는 중...", 3000)
                        validated_url = self.test_comfyui(comfyui_url)
                        
                        if validated_url:
                            # ✅ 연결 성공 시 ComfyUI 모드로 전환
                            self.nai_toggle_btn.setChecked(False)
                            self.webui_toggle_btn.setChecked(False)
                            self.comfyui_toggle_btn.setChecked(True)
                            
                            # 스타일 적용
                            self.nai_toggle_btn.setStyleSheet(self.toggle_inactive_style)
                            self.webui_toggle_btn.setStyleSheet(self.toggle_inactive_style)
                            self.comfyui_toggle_btn.setStyleSheet(self.toggle_active_style)
                            
                            # UI 위젯 표시/숨김
                            for widget in self.naid_option_widgets:
                                widget.setVisible(False)
                            for widget in self.hires_option_widgets:
                                widget.setVisible(False)
                            for widget in self.comfyui_option_widgets:
                                widget.setVisible(True)
                            
                            self.status_bar.showMessage(f"✅ ComfyUI 모드로 전환되었습니다. ({comfyui_url})", 5000)
                            
                            # 검증된 URL을 키링에 저장
                            self.app_context.secure_token_manager.save_token('comfyui_url', comfyui_url)
                            self.app_context.set_api_mode(mode)

                        else:
                            # ❌ 연결 실패
                            self.status_bar.showMessage(f"❌ ComfyUI 연결 실패: {comfyui_url}", 5000)
                            if not tab_was_open:
                                self.open_search_management()
                            
                            # 오류 메시지 표시
                            from PyQt6.QtWidgets import QMessageBox
                            QMessageBox.critical(
                                self, 
                                "ComfyUI 연결 실패", 
                                f"ComfyUI 서버에 연결할 수 없습니다.\n\n"
                                f"확인할 사항:\n"
                                f"• ComfyUI가 실행 중인지 확인\n"
                                f"• 주소가 올바른지 확인: {comfyui_url}\n"
                                f"• 포트 번호가 정확한지 확인 (기본: 8188)\n\n"
                                f"API 관리 탭에서 올바른 주소를 입력해주세요."
                            )
                    else:
                        self.status_bar.showMessage("⚠️ API 관리 기능을 사용할 수 없습니다.", 5000)
                        self.open_search_management()
                        
            except Exception as e:
                print(f"❌ ComfyUI 모드 전환 중 오류: {e}")
                self.status_bar.showMessage(f"❌ ComfyUI 모드 전환 실패: {str(e)}", 5000)
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
        self.connect_checkbox_signals()

    def set_positive_prompt(self, prompt: str):
        """전달받은 프롬프트를 메인 UI의 프롬프트 입력창에 설정합니다."""
        self.main_prompt_textedit.setPlainText(prompt)
        print(f"📋 프롬프트 불러오기 완료.")
        self.status_bar.showMessage("프롬프트가 성공적으로 로드되었습니다.", 3000)

    def get_main_parameters(self) -> dict:
        """메인 UI의 파라미터들을 수집하여 딕셔너리로 반환합니다."""
        params = {}
        try:
            # 해상도 파싱 - 공백 처리 개선
            resolution_text = self.resolution_combo.currentText()
            if " x " in resolution_text:
                width_str, height_str = resolution_text.split(" x ")
                width, height = int(width_str.strip()), int(height_str.strip())
            else:
                # 기본값 설정
                width, height = 1024, 1024
            
            # 시드 처리
            if self.seed_fix_checkbox.isChecked():
                try:
                    seed_value = int(self.seed_input.text())
                except ValueError:
                    seed_value = -1
            else:
                seed_value = random.randint(0, 9999999999)
                self.seed_input.setText(str(seed_value))

            # 프롬프트 처리 (쉼표 기준 정리)
            processed_input = ', '.join([item.strip() for item in self.main_prompt_textedit.toPlainText().split(',') if item.strip()])
            processed_negative_prompt = ', '.join([item.strip() for item in self.negative_prompt_textedit.toPlainText().split(',') if item.strip()])

            # 🔧 기존 구조 유지: 실제 위젯 이름에 맞게 파라미터 수집
            params = {
                "action": "generate",
                "access_token": "",
                "input": processed_input,
                "negative_prompt": processed_negative_prompt,
                "model": self.model_combo.currentText(),
                "scheduler": self.scheduler_combo.currentText(),
                "sampler": self.sampler_combo.currentText(),
                "resolution": self.resolution_combo.currentText(),  # UI 표시용
                "width": width,
                "height": height,
                "seed": seed_value,
                "random_resolution": self.random_resolution_checkbox.isChecked(),
                "steps": self.steps_spinbox.value(),
                "cfg_scale": self.cfg_scale_slider.value() / 10.0,  # 슬라이더 값(10~300) → 실제 값(1.0~30.0)
                "cfg_rescale": self.cfg_rescale_slider.value() / 100.0,  # 슬라이더 값(0~100) → 실제 값(0.0~1.0)
                
                # 고급 체크박스들 (딕셔너리에서 직접 접근)
                "SMEA": self.advanced_checkboxes["SMEA"].isChecked(),
                "DYN": self.advanced_checkboxes["DYN"].isChecked(),
                "VAR+": self.advanced_checkboxes["VAR+"].isChecked(),
                "DECRISP": self.advanced_checkboxes["DECRISP"].isChecked(),
                
                # 커스텀 API 파라미터
                "use_custom_api_params": self.custom_api_checkbox.isChecked(),
                "custom_api_params": self.custom_script_textbox.toPlainText()
            }
            
            # 🆕 추가: WEBUI 전용 파라미터들 (해당 모드일 때만)
            if hasattr(self, 'enable_hr_checkbox'):
                params.update({
                    "enable_hr": self.enable_hr_checkbox.isChecked(),
                    "hr_scale": self.hr_scale_spinbox.value() if hasattr(self, 'hr_scale_spinbox') else 1.5,
                    "hr_upscaler": self.hr_upscaler_combo.currentText() if hasattr(self, 'hr_upscaler_combo') else "Lanczos",
                    "denoising_strength": self.denoising_strength_slider.value() / 100.0 if hasattr(self, 'denoising_strength_slider') else 0.5,
                    "hires_steps": self.hires_steps_spinbox.value() if hasattr(self, 'hires_steps_spinbox') else 0
                })
                
            # 🆕 추가: ComfyUI 전용 파라미터들 (현재 모드가 ComfyUI일 때만)
            current_mode = self.get_current_api_mode()
            if current_mode == "COMFYUI":
                if hasattr(self, 'v_prediction_checkbox') and hasattr(self, 'zsnr_checkbox'):
                    params.update({
                        "sampling_mode": "v_prediction" if self.v_prediction_checkbox.isChecked() else "eps",
                        "zsnr": self.zsnr_checkbox.isChecked(),
                        "filename_prefix": "NAIA_ComfyUI"  # 기본 파일명 접두사
                    })
                    
                    # 디버그 정보
                    print(f"🎨 ComfyUI 파라미터 수집 완료:")
                    print(f"   - 샘플링 모드: {params['sampling_mode']}")
                    print(f"   - ZSNR: {params['zsnr']}")
                    print(f"   - 해상도: {params['width']}x{params['height']}")
                    print(f"   - 스텝: {params['steps']}, CFG: {params['cfg_scale']}")
                else:
                    # ComfyUI 위젯이 아직 초기화되지 않은 경우 기본값 사용
                    params.update({
                        "sampling_mode": "eps",
                        "zsnr": False,
                        "filename_prefix": "NAIA_ComfyUI"
                    })
                    print("⚠️ ComfyUI 위젯이 초기화되지 않아 기본값을 사용합니다.")

            # 🆕 추가: 자동 해상도 맞춤 옵션 (모든 모드 공통)
            if hasattr(self, 'auto_fit_resolution_checkbox'):
                params["auto_fit_resolution"] = self.auto_fit_resolution_checkbox.isChecked()
                    
        except (ValueError, KeyError, AttributeError) as e:
            print(f"❌ 파라미터 수집 오류: {e}")
            # 오류 발생 시 사용자에게 알림
            self.status_bar.showMessage(f"⚠️ 생성 파라미터 값에 오류가 있습니다: {e}", 5000)
            return {}  # 빈 딕셔너리 반환

        return params

    # update_ui_with_result 메서드 수정
    def update_ui_with_result(self, result: dict):
        """APIService의 결과를 받아 UI에 업데이트하고 히스토리에 추가"""
        try:
            if not self.image_window:
                print("❌ image_window가 None입니다.")
                return
                
            image_object = result.get("image")
            info_text = result.get("info", "")
            source_row = result.get("source_row")
            raw_bytes = result.get("raw_bytes")

            if image_object is None:
                print("❌ image_object가 None입니다.")
                return
            try:
                self.image_window.update_image(image_object)
            except Exception as e:
                print(f"❌ 이미지 업데이트 실패: {e}")
                return
                
            # 정보 업데이트
            try:
                self.image_window.update_info(info_text)
            except Exception as e:
                print(f"❌ 정보 업데이트 실패: {e}")
                
            # 히스토리 추가
            try:
                print(f"  - image_object type: {type(image_object)}")
                print(f"  - raw_bytes type: {type(raw_bytes)}, length: {len(raw_bytes) if raw_bytes else 'None'}")
                print(f"  - info_text type: {type(info_text)}, length: {len(info_text) if info_text else 'None'}")
                print(f"  - source_row type: {type(source_row)}")
                
                self.image_window.add_to_history(image_object, raw_bytes, info_text, source_row)
            except Exception as e:
                print(f"❌ 히스토리 추가 실패: {e}")
                import traceback
                traceback.print_exc()
            
            self.status_bar.showMessage("🎉 생성 완료!")
            
            # 자동화 모듈 처리 (안전하게)
            if self.automation_module:
                try:
                    should_proceed_to_next = self.automation_module.notify_generation_completed()
                    if should_proceed_to_next is False:
                        return
                except Exception as e:
                    print(f"❌ 자동화 모듈 notify_generation_completed 실패: {e}")
                    return

            # 자동 생성 체크
            try:
                if self.automation_module and self.automation_module.automation_controller.is_running:
                    delay = self.automation_module.get_generation_delay()
                    if delay > 0:
                        from PyQt6.QtCore import QTimer
                        QTimer.singleShot(int(delay * 1000), self._check_and_trigger_auto_generation)
                    else:
                        self._check_and_trigger_auto_generation()
                else:
                    self._check_and_trigger_auto_generation()
            except Exception as e:
                print(f"❌ 자동 생성 체크 실패: {e}")

        except Exception as e:
            print(f"❌ update_ui_with_result 전체 에러: {e}")
            import traceback
            traceback.print_exc()
            self.status_bar.showMessage(f"❌ 결과 처리 오류: {e}")

    def _check_and_trigger_auto_generation(self):
        """자동 생성 조건을 확인하고 조건이 만족되면 다음 사이클을 시작합니다."""
        # 조건 확인: "자동 생성"이 체크되어 있고 "프롬프트 고정"이 체크되어 있지 않음
        auto_generate_checkbox = self.generation_checkboxes.get("자동 생성")
        prompt_fixed_checkbox = self.generation_checkboxes.get("프롬프트 고정")
        
        if not auto_generate_checkbox.isChecked():
            return  # 자동 생성 체크박스가 없으면 종료

        try:
            if (hasattr(self, 'generation_controller') and 
                self.generation_controller.is_generating):
                print("🔄 이미지 생성 중이므로 자동 생성 건너뜀")
                # 약간의 지연 후 다시 시도
                QTimer.singleShot(500, self._check_and_trigger_auto_generation)
                return
                
            # [추가] 스레드 상태 확인
            if (hasattr(self, 'generation_controller') and 
                self.generation_controller.generation_thread and 
                self.generation_controller.generation_thread.isRunning()):
                print("🔄 이전 스레드가 아직 실행 중이므로 잠시 대기...")
                QTimer.singleShot(200, self._check_and_trigger_auto_generation)
                return

            # [신규] 반복 생성 중인지 확인 - 반복 중이면 자동 생성 건너뛰기
            if (self.automation_module and 
                hasattr(self.automation_module, 'current_repeat_count') and 
                self.automation_module.current_repeat_count > 0):
                print(f"🔁 반복 생성 중이므로 자동 생성 건너뜀 (현재 반복: {self.automation_module.current_repeat_count})")
                return
            
            # [신규] 중복 실행 방지 - 시간 기반 체크
            import time
            current_time = time.time()
            # if self.auto_generation_in_progress or (current_time - self.last_auto_generation_time) < 1.0:
            #     print(f"⚠️ 자동 생성 중복 방지: in_progress={self.auto_generation_in_progress}, time_diff={current_time - self.last_auto_generation_time:.2f}s")
            #     return
                
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
                    'prompt_fixed': False, 
                    'auto_generate': True,
                    'turbo_mode': self.generation_checkboxes["터보 옵션"].isChecked(),
                    'wildcard_standalone': self.generation_checkboxes["와일드카드 단독 모드"].isChecked(),
                    "auto_fit_resolution": self.auto_fit_resolution_checkbox.isChecked()
                }
                
                # 프롬프트 생성 컨트롤러에 자동 생성 플래그 설정
                self.prompt_gen_controller.auto_generation_requested = True
                self.prompt_gen_controller.generate_next_prompt(self.search_results, settings)
            elif auto_generate_checkbox.isChecked() and prompt_fixed_checkbox.isChecked():
                self.auto_generation_in_progress = True
                self.last_auto_generation_time = current_time
                self.status_bar.showMessage("🔄 자동 생성: 프롬프트 고정이 체크되어 있어 생성 단계로 넘어갑니다...")
                self._trigger_auto_image_generation()
                
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

            self.image_window.close_all_detached_windows()

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
        현재 선택된 토글 버튼에 따라 'NAI', 'WEBUI', 또는 'COMFYUI' 문자열을 반환합니다.
        """
        if self.nai_toggle_btn.isChecked():
            return "NAI"
        elif self.webui_toggle_btn.isChecked():
            return "WEBUI"
        elif self.comfyui_toggle_btn.isChecked():  # 🆕 ComfyUI 지원 추가
            return "COMFYUI"
        else:
            # 기본값은 NAI (안전장치)
            return "NAI"
        
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
    
    def test_comfyui(self, url):
        """ComfyUI 연결 테스트 함수 (test_webui와 유사한 패턴)"""
        import requests
        
        # URL 정규화 및 프로토콜 테스트
        test_urls = []
        clean_url = url.replace('https://', '').replace('http://', '')
        
        # 포트가 없으면 기본 ComfyUI 포트(8188) 추가
        if ':' not in clean_url:
            clean_url = f"{clean_url}:8188"
        
        # HTTP와 HTTPS 모두 테스트
        test_urls.append(f"http://{clean_url}")
        test_urls.append(f"https://{clean_url}")
        
        for test_url in test_urls:
            try:
                print(f"🔍 ComfyUI 연결 테스트: {test_url}")
                
                # /system_stats 엔드포인트로 연결 테스트
                response = requests.get(f"{test_url}/system_stats", timeout=8)
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        # ComfyUI 응답 구조 확인
                        if 'system' in data or 'devices' in data:
                            print(f"✅ ComfyUI 연결 성공: {test_url}")
                            return test_url
                    except json.JSONDecodeError:
                        continue
                
            except requests.exceptions.ConnectTimeout:
                print(f"⏰ ComfyUI 연결 시간 초과: {test_url}")
                continue
            except requests.exceptions.ConnectionError:
                print(f"❌ ComfyUI 연결 실패: {test_url}")
                continue
            except Exception as e:
                print(f"❌ ComfyUI 테스트 중 예외: {test_url} - {e}")
                continue
        
        print(f"❌ 모든 ComfyUI 연결 시도 실패: {url}")
        return None

    def connect_checkbox_signals(self):
        """체크박스 시그널을 연결하는 메서드 (init에서 호출)"""
        try:
            prompt_fixed_checkbox = self.generation_checkboxes.get("프롬프트 고정")
            if prompt_fixed_checkbox:
                prompt_fixed_checkbox.toggled.connect(self.update_random_prompt_button_state)
                
            # 초기 상태 설정
            self.update_random_prompt_button_state()
            
        except Exception as e:
            print(f"❌ 체크박스 시그널 연결 오류: {e}")

    def update_random_prompt_button_state(self):
        """generation_checkboxes 상태에 따라 random_prompt_btn을 활성화/비활성화"""
        try:
            # "프롬프트 고정" 체크박스가 체크되어 있으면 버튼 비활성화
            prompt_fixed_checkbox = self.generation_checkboxes.get("프롬프트 고정")
            
            if prompt_fixed_checkbox and prompt_fixed_checkbox.isChecked():
                self.random_prompt_btn.setEnabled(False)
                self.random_prompt_btn.setText("프롬프트 고정됨")
            else:
                self.random_prompt_btn.setEnabled(True)
                self.random_prompt_btn.setText("랜덤/다음 프롬프트")
                
        except Exception as e:
            print(f"❌ 버튼 상태 업데이트 오류: {e}")


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