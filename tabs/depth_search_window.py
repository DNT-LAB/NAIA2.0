import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QTableView, QHeaderView, QAbstractItemView,
    QFileDialog, QMessageBox, QSplitter, QFrame, QTextEdit, QMenu, QScrollArea
)
from PyQt6.QtGui import QCursor, QAction, QIntValidator
from PyQt6.QtCore import QAbstractTableModel, Qt, pyqtSignal, QObject, QThread
from core.search_result_model import SearchResultModel
from core.search_engine import SearchEngine
from ui.theme import DARK_COLORS
from interfaces.base_tab_module import BaseTabModule

class TagsStringBuildThread(QThread):
    """tags_string 컬럼을 백그라운드에서 빌드하는 스레드"""
    build_finished = pyqtSignal(object)

    def __init__(self, df: pd.DataFrame, parent=None):
        super().__init__(parent)
        self.df = df
        self.is_cancelled = False

    def run(self):
        engine = SearchEngine()
        result_df = self.df.copy()
        if not result_df.empty:
            result_df['tags_string'] = engine._build_tags_string(result_df)
        if not self.is_cancelled:
            self.build_finished.emit(result_df)


class DepthSearchTabModule(BaseTabModule):
    """'심층 검색' 탭을 동적으로 로드하기 위한 모듈"""

    def __init__(self):
        super().__init__()
        self.widget: DepthSearchWindow = None
        # 생성 시 필요한 데이터를 임시 저장할 변수
        self.initial_data = {}

    def setup(self, **kwargs):
        """탭 생성에 필요한 동적 데이터를 전달받는 메서드"""
        self.initial_data = kwargs

    def get_tab_title(self) -> str:
        return "🔬 심층 검색"
    
    def get_tab_type(self) -> str:
        return 'closable' # 이 탭은 요청 시에만 로드됩니다.

    def can_close_tab(self) -> bool:
        return True

    def create_widget(self, parent: QWidget) -> QWidget:
        if self.widget is None:
            search_results = self.initial_data.get('search_results')
            main_window = self.initial_data.get('main_window')
            
            if not isinstance(search_results, SearchResultModel) or not main_window:
                raise ValueError("심층 검색 탭 생성에 필요한 데이터가 없습니다.")

            self.widget = DepthSearchWindow(search_results, main_window)
            # 메인 윈도우와 시그널 연결
            self.widget.results_assigned.connect(main_window.on_depth_search_results_assigned)
        return self.widget

class PandasModel(QAbstractTableModel):
    """Pandas DataFrame을 QTableView에 표시하기 위한 모델"""
    def __init__(self, df=pd.DataFrame()):
        super().__init__()
        self._df = df

    def rowCount(self, parent=None):
        return self._df.shape[0]

    def columnCount(self, parent=None):
        return self._df.shape[1]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role == Qt.ItemDataRole.DisplayRole:
            value = self._df.iloc[index.row(), index.column()]
            
            # 1. 값이 NaN인지 먼저 확인
            if pd.isna(value):
                return ""  # NaN이면 빈 문자열 반환
            
            # 2. 숫자 타입이면 정수로 변환하여 소수점 제거
            if isinstance(value, (int, float)):
                return str(int(value))
            
            # 3. 그 외의 경우 문자열로 변환
            return str(value)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                # 컬럼 인덱스 범위 검사 추가
                if 0 <= section < len(self._df.columns):
                    return str(self._df.columns[section])
                else:
                    return ""
            if orientation == Qt.Orientation.Vertical:
                # 행 인덱스 범위 검사 추가
                if 0 <= section < len(self._df.index):
                    return str(self._df.index[section] + 1) # 1부터 시작하도록
                else:
                    return ""
        return None

    def sort(self, column, order):
        try:
            # Check if dataframe is empty or has no columns
            df = self.dataframe()
            if df is None or df.empty or len(df.columns) == 0 or column >= len(df.columns):
                return

            self.layoutAboutToBeChanged.emit()
            col_name = df.columns[column]
            self._df = df.sort_values(
                col_name, ascending=(order == Qt.SortOrder.AscendingOrder), kind='mergesort'
            )
            self.layoutChanged.emit()
        except Exception as e:
            print(f"Warning: Sort failed - {e}")
            pass

    def dataframe(self):
        return self._df


class StagingItemWidget(QFrame):
    """스테이징된 검색 결과 항목 위젯"""
    remove_requested = pyqtSignal(int)

    def __init__(self, index: int, query: str, exclude: str, count: int, parent=None):
        super().__init__(parent)
        self.staging_index = index
        self.setStyleSheet(f"""
            StagingItemWidget {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        count_html = f'<span style="color: #FFFACD; font-weight: bold;">[{count:,}]</span>'
        info_parts = [count_html]
        if query:
            info_parts.append(f"검색: {query}")
        if exclude:
            info_parts.append(f"제외: {exclude}")

        info_label = QLabel(" ".join(info_parts))
        info_label.setTextFormat(Qt.TextFormat.RichText)
        info_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: 14px; border: none;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label, 1)

        remove_btn = QPushButton("X")
        remove_btn.setFixedSize(22, 22)
        remove_btn.setStyleSheet("""
            QPushButton { background: #F44336; color: white; border: none; border-radius: 3px; font-weight: bold; font-size: 11px; }
            QPushButton:hover { background: #E53935; }
        """)
        remove_btn.clicked.connect(lambda: self.remove_requested.emit(self.staging_index))
        layout.addWidget(remove_btn)


class DepthSearchWindow(QWidget):
    """심층 검색 탭 UI 및 기능 클래스"""
    results_assigned = pyqtSignal(SearchResultModel)

    def __init__(self, search_result: SearchResultModel, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")
        self.original_model = search_result
        self.current_model = SearchResultModel(search_result.get_dataframe().copy())
        self.search_engine = SearchEngine()

        # tags_string 사전 빌드 (검색 속도 최적화)
        self._ensure_tags_string(self.current_model.get_dataframe())

        # 스테이징 데이터
        self.staged_items = []  # list of {'query': str, 'exclude': str, 'df': DataFrame}

        # 시그널 연결 추적 플래그
        self._selection_connected = False

        self.init_ui()
        self.update_view()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_splitter = QSplitter(Qt.Orientation.Vertical)
        
        top_container = self._create_viewer_layout()
        
        # [수정] 하단 컨트롤 패널 레이아웃 재구성
        bottom_container = QWidget()
        bottom_layout = QHBoxLayout(bottom_container)
        bottom_layout.setContentsMargins(0, 5, 0, 0)
        bottom_layout.setSpacing(10)

        # 하단 좌측: 검색 필터 + 결과 관리
        left_controls_container = QWidget()
        left_controls_layout = QVBoxLayout(left_controls_container)
        left_controls_layout.setContentsMargins(0,0,0,0)
        left_controls_layout.setSpacing(10)
        left_controls_layout.addWidget(self._create_search_layout())
        left_controls_layout.addWidget(self._create_assignment_layout())
        left_controls_layout.addStretch(1)

        # 하단 우측: 데이터 스태커
        stacker_widget = self._create_stacker_layout()

        bottom_layout.addWidget(left_controls_container, 1)
        bottom_layout.addWidget(stacker_widget, 1)

        main_splitter.addWidget(top_container)
        main_splitter.addWidget(bottom_container)
        main_splitter.setStretchFactor(0, 7)
        main_splitter.setStretchFactor(1, 3)
        
        main_layout.addWidget(main_splitter)

    def _create_viewer_layout(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0,0,0,0)
        
        self.info_label = QLabel()
        self.info_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']};")
        self.table_view = QTableView()
        self.table_view.setModel(PandasModel())
        
        # [신규] 우클릭 컨텍스트 메뉴 정책 설정
        self.table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self.show_table_context_menu)

        # [수정] Qt 기본 정렬 대신 커스텀 정렬 사용 (기본값은 False)
        self.table_view.setSortingEnabled(False)
        self.table_view.horizontalHeader().sectionClicked.connect(self.on_header_clicked)
        self.current_sort_order = {} # {columnIndex: order}
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        # [수정] 테이블 뷰 스타일 변경
        self.table_view.setStyleSheet("""
            QTableView {
                background-color: white;
                color: black;
                border: 1px solid #D3D3D3;
                gridline-color: #E0E0E0;
            }
            QHeaderView::section {
                background-color: #F0F0F0;
                color: black;
                padding: 4px;
                border: 1px solid #D3D3D3;
            }
        """)

        layout.addWidget(self.info_label)
        layout.addWidget(self.table_view)
        return container

    def _create_search_layout(self) -> QWidget:
        # [수정] 커스텀 스타일 적용
        container = QFrame()
        container.setStyleSheet("border: none;")
        layout = QVBoxLayout(container)

        # 위젯 공통 스타일
        label_style = f"color: {DARK_COLORS['text_secondary']};"
        input_style = f"""
            background-color: {DARK_COLORS['bg_secondary']}; border: 1px solid {DARK_COLORS['border']};
            border-radius: 4px; padding: 5px; color: {DARK_COLORS['text_primary']};
        """
        checkbox_style = f"color: {DARK_COLORS['text_primary']};"

        grid = QGridLayout()
        search_header_layout = QHBoxLayout()
        search_header_layout.addWidget(QLabel("검색 키워드:", self, styleSheet=label_style))
        search_header_layout.addStretch(1)
        self.promote_to_origin_btn = QPushButton("현재 검색 결과를 원본 행으로")
        self.promote_to_origin_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent; border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px; padding: 2px 6px; color: {DARK_COLORS['text_secondary']}; font-size: 11px;
            }}
            QPushButton:hover {{ background-color: {DARK_COLORS['bg_hover']}; color: {DARK_COLORS['text_primary']}; }}
        """)
        self.promote_to_origin_btn.clicked.connect(self.promote_current_to_original)
        search_header_layout.addWidget(self.promote_to_origin_btn)
        grid.addLayout(search_header_layout, 0, 0, 1, 4)
        self.d_search_input = QLineEdit(styleSheet=input_style)
        self.d_search_input.returnPressed.connect(self.apply_filters)
        grid.addWidget(self.d_search_input, 1, 0, 1, 4)

        grid.addWidget(QLabel("제외 키워드:", self, styleSheet=label_style), 2, 0, 1, 4)
        self.d_exclude_input = QLineEdit(styleSheet=input_style)
        self.d_exclude_input.returnPressed.connect(self.apply_filters)
        grid.addWidget(self.d_exclude_input, 3, 0, 1, 4)

        rating_layout = QHBoxLayout()
        self.d_rating_checkboxes = {}
        checkboxes_map = {"Explicit": "e", "NSFW": "q", "Sensitive": "s", "General": "g"}
        for text, key in checkboxes_map.items():
            cb = QCheckBox(text, styleSheet=checkbox_style)
            cb.setChecked(True)
            rating_layout.addWidget(cb)
            self.d_rating_checkboxes[key] = cb
        grid.addLayout(rating_layout, 4, 0, 1, 4)

        self.w_min_check = QCheckBox("너비 ≥", styleSheet=checkbox_style)
        self.w_min_input = QLineEdit("0",styleSheet=input_style)
        self.w_max_check = QCheckBox("너비 ≤", styleSheet=checkbox_style)
        self.w_max_input = QLineEdit("9999",styleSheet=input_style)
        grid.addWidget(self.w_min_check, 5, 0)
        grid.addWidget(self.w_min_input, 5, 1)
        grid.addWidget(self.w_max_check, 5, 2)
        grid.addWidget(self.w_max_input, 5, 3)
        self.w_min_input.setProperty("autocomplete_ignore", True)
        self.w_max_input.setProperty("autocomplete_ignore", True)
        int_validator = QIntValidator(0, 99999999)
        self.w_min_input.setValidator(int_validator)
        self.w_max_input.setValidator(int_validator)

        self.h_min_check = QCheckBox("높이 ≥", styleSheet=checkbox_style)
        self.h_min_input = QLineEdit("0",styleSheet=input_style)
        self.h_max_check = QCheckBox("높이 ≤", styleSheet=checkbox_style)
        self.h_max_input = QLineEdit("9999",styleSheet=input_style)
        grid.addWidget(self.h_min_check, 6, 0)
        grid.addWidget(self.h_min_input, 6, 1)
        grid.addWidget(self.h_max_check, 6, 2)
        grid.addWidget(self.h_max_input, 6, 3)
        self.h_min_input.setProperty("autocomplete_ignore", True)
        self.h_max_input.setProperty("autocomplete_ignore", True)
        self.h_min_input.setValidator(int_validator)
        self.h_max_input.setValidator(int_validator)
                

        # ... (토큰/ID 필터 위젯은 동일, row 인덱스만 조정) ...
        self.token_min_check = QCheckBox("토큰 ≥", styleSheet=checkbox_style)
        self.token_min_input = QLineEdit("0",styleSheet=input_style)
        grid.addWidget(self.token_min_check, 7, 0)
        grid.addWidget(self.token_min_input, 7, 1)
        
        self.token_max_check = QCheckBox("토큰 ≤", styleSheet=checkbox_style)
        self.token_max_input = QLineEdit("150",styleSheet=input_style)
        grid.addWidget(self.token_max_check, 7, 2)
        grid.addWidget(self.token_max_input, 7, 3)
        self.token_min_input.setProperty("autocomplete_ignore", True)
        self.token_max_input.setProperty("autocomplete_ignore", True)
        self.token_min_input.setValidator(int_validator)
        self.token_max_input.setValidator(int_validator)


        self.id_min_check = QCheckBox("ID ≥", styleSheet=checkbox_style)
        self.id_min_input = QLineEdit("0", styleSheet=input_style)
        grid.addWidget(self.id_min_check, 8, 0)
        grid.addWidget(self.id_min_input, 8, 1)
        
        self.id_max_check = QCheckBox("ID ≤", styleSheet=checkbox_style)
        self.id_max_input = QLineEdit("99999999", styleSheet=input_style)
        grid.addWidget(self.id_max_check, 8, 2)
        grid.addWidget(self.id_max_input, 8, 3)
        self.id_min_input.setProperty("autocomplete_ignore", True)
        self.id_max_input.setProperty("autocomplete_ignore", True)
        self.id_min_input.setValidator(int_validator)
        self.id_max_input.setValidator(int_validator)

        # [신규] Score 필터 추가 (row 9)
        self.score_min_check = QCheckBox("Score ≥", styleSheet=checkbox_style)
        self.score_min_input = QLineEdit("0", styleSheet=input_style)
        grid.addWidget(self.score_min_check, 9, 0)
        grid.addWidget(self.score_min_input, 9, 1)
        self.score_min_input.setProperty("autocomplete_ignore", True)
        self.score_min_input.setValidator(int_validator)

        # [수정] 캐릭터명 필터의 row 인덱스 조정 (9 -> 10)
        char_filter_layout = QHBoxLayout()
        self.rem_char_check = QCheckBox("캐릭터명 없는 행 제외", styleSheet=checkbox_style)
        self.only_empty_char_check = QCheckBox("캐릭터명 없는 행만 검색", styleSheet=checkbox_style)
        char_filter_layout.addWidget(self.rem_char_check)
        char_filter_layout.addWidget(self.only_empty_char_check)
        char_filter_layout.addStretch(1)
        grid.addLayout(char_filter_layout, 10, 0, 1, 4)

        layout.addLayout(grid)

        self.refilter_btn = QPushButton("결과 내 재검색")
        
        # [수정] 결과 내 재검색 버튼 스타일 변경
        self.refilter_btn.setStyleSheet("""
            QPushButton {
                background-color: white;
                color: black;
                border: 1px solid #B0B0B0;
                border-radius: 4px;
                padding: 8px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #F0F0F0;
            }
        """)
        self.refilter_btn.clicked.connect(self.apply_filters)
        layout.addWidget(self.refilter_btn)
        layout.addStretch(1) # 위젯들이 위로 정렬되도록
        
        return container

    def _create_assignment_layout(self) -> QWidget:
        # [수정] 레이아웃 재배치 및 스타일 적용
        container = QFrame()
        container.setStyleSheet("border: none;")
        layout = QVBoxLayout(container)
        
        button_style = f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']}; border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px; padding: 8px; color: {DARK_COLORS['text_primary']};
            }}
            QPushButton:hover {{ background-color: {DARK_COLORS['bg_hover']}; }}
        """
        self.assign_btn = QPushButton("현재 결과를 메인에 할당", styleSheet=button_style)
        self.assign_btn.clicked.connect(self.assign_results_to_main)
        
        self.restore_btn = QPushButton("초기 상태로 복원", styleSheet=button_style)
        self.restore_btn.clicked.connect(self.restore_to_original)

        layout.addWidget(self.assign_btn)
        layout.addWidget(self.restore_btn)
        return container

    def _create_stacker_layout(self) -> QWidget:
        container = QFrame()
        container.setStyleSheet("border: none;")
        layout = QVBoxLayout(container)

        # --- general 태그 표시 (기본 표시) ---
        self.general_text_edit = QTextEdit()
        self.general_text_edit.setReadOnly(True)
        self.general_text_edit.setStyleSheet(f"""
            background-color: {DARK_COLORS['bg_secondary']}; border: 1px solid {DARK_COLORS['border']};
            border-radius: 4px; padding: 5px; color: {DARK_COLORS['text_primary']};
        """)
        self.general_text_edit.setPlaceholderText("테이블 행을 클릭하여 general 태그 보기...")
        layout.addWidget(self.general_text_edit, 1)

        # --- 스테이징 프레임 (숨김 상태, general_text_edit 자리를 대체) ---
        self.staging_frame = QFrame()
        self.staging_frame.setVisible(False)
        self.staging_frame.setStyleSheet(f"""
            QFrame#stagingFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)
        self.staging_frame.setObjectName("stagingFrame")
        staging_inner = QVBoxLayout(self.staging_frame)
        staging_inner.setContentsMargins(6, 6, 6, 6)
        staging_inner.setSpacing(4)

        staging_header = QLabel("스테이징 목록")
        staging_header.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-weight: bold; font-size: 13px; border: none;")
        staging_inner.addWidget(staging_header)

        self.staging_scroll = QScrollArea()
        self.staging_scroll.setWidgetResizable(True)
        self.staging_scroll.setStyleSheet("border: none; background: transparent;")
        self.staging_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        staging_content = QWidget()
        staging_content.setStyleSheet("background: transparent;")
        self.staging_items_layout = QVBoxLayout(staging_content)
        self.staging_items_layout.setContentsMargins(0, 0, 0, 0)
        self.staging_items_layout.setSpacing(3)
        self.staging_items_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.staging_scroll.setWidget(staging_content)
        staging_inner.addWidget(self.staging_scroll, 1)

        self.staging_summary_label = QLabel("")
        self.staging_summary_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: 12px; border: none;")
        staging_inner.addWidget(self.staging_summary_label)

        layout.addWidget(self.staging_frame, 1)

        # --- 버튼 영역 ---
        button_style = f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']}; border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px; padding: 8px; color: {DARK_COLORS['text_primary']};
            }}
            QPushButton:hover {{ background-color: {DARK_COLORS['bg_hover']}; }}
        """
        staging_add_style = f"""
            QPushButton {{
                background-color: #1565C0; border: none;
                border-radius: 4px; padding: 8px; color: white; font-weight: 600;
            }}
            QPushButton:hover {{ background-color: #1976D2; }}
        """
        staging_merge_style = f"""
            QPushButton {{
                background-color: #2E7D32; border: none;
                border-radius: 4px; padding: 8px; color: white; font-weight: 600;
            }}
            QPushButton:hover {{ background-color: #388E3C; }}
        """

        self.add_staging_btn = QPushButton("+ 스테이징에 추가")
        self.add_staging_btn.setStyleSheet(staging_add_style)
        self.add_staging_btn.clicked.connect(self.add_to_staging)
        layout.addWidget(self.add_staging_btn)

        self.merge_staging_btn = QPushButton("스테이징 병합 -> 현재 뷰")
        self.merge_staging_btn.setStyleSheet(staging_merge_style)
        self.merge_staging_btn.clicked.connect(self.merge_staging)
        self.merge_staging_btn.setVisible(False)
        layout.addWidget(self.merge_staging_btn)

        self.clear_staging_btn = QPushButton("스테이징 초기화")
        self.clear_staging_btn.setStyleSheet(button_style)
        self.clear_staging_btn.clicked.connect(self.clear_staging)
        self.clear_staging_btn.setVisible(False)
        layout.addWidget(self.clear_staging_btn)

        export_btn = QPushButton("현재 뷰 내보내기 (.parquet)", styleSheet=button_style)
        export_btn.clicked.connect(self.export_to_parquet)
        import_btn = QPushButton("Parquet 불러와 합치기", styleSheet=button_style)
        import_btn.clicked.connect(self.import_parquet)
        clear_btn = QPushButton("현재 목록 초기화", styleSheet=button_style)
        clear_btn.clicked.connect(self.clear_current_view)

        layout.addWidget(export_btn)
        layout.addWidget(import_btn)
        layout.addWidget(clear_btn)
        return container
    
    # [신규] 마우스, 키보드 입력을 모두 처리하는 통합 슬롯
    def on_selection_changed(self, selected, deselected):
        """
        선택된 행이 변경될 때마다 호출 (마우스 클릭, 키보드 이동 모두 포함)

        🔧 크래시 방지 개선:
        - 안전한 DataFrame 접근 (모델이 교체되는 중일 수 있음)
        - setFocus() 재귀 루프 방지
        """
        # 선택된 인덱스 목록에서 첫 번째 인덱스를 가져옴
        indexes = selected.indexes()
        if not indexes:
            return

        current_index = indexes[0]
        row = current_index.row()

        # 안전한 모델 및 DataFrame 접근
        model = self.table_view.model()
        if model is None:
            return

        try:
            df = model.dataframe()
            if df is None or df.empty or row >= len(df):
                return

            original_index = df.index[row]
            general_text = df.loc[original_index, 'general']
            self.general_text_edit.setText(str(general_text))
        except (KeyError, IndexError, AttributeError) as e:
            self.general_text_edit.setText(f"'general' 컬럼을 찾을 수 없거나 행이 잘못되었습니다. ({e})")
        except Exception as e:
            # 예상치 못한 오류 방지
            print(f"⚠️ on_selection_changed 오류: {e}")

        # 🔧 setFocus() 제거: 재귀 루프 방지
        # self.table_view.setFocus()  # 제거됨
    
    def update_view(self):
        """
        현재 모델 데이터로 테이블 뷰와 정보 레이블을 업데이트

        🔧 크래시 방지 개선:
        - 이전 모델과 selectionModel의 시그널 안전하게 해제
        - 시그널 중복 연결 방지 (중복 연결 시 스택 오버플로우 발생)
        - Qt 객체 수명 관리 개선
        """
        # 1. 이전 selectionModel의 시그널 연결 해제 (메모리 누수 방지)
        if self._selection_connected:
            try:
                old_selection_model = self.table_view.selectionModel()
                if old_selection_model is not None:
                    old_selection_model.selectionChanged.disconnect(self.on_selection_changed)
            except (RuntimeError, TypeError):
                # 이미 삭제된 객체이거나 연결되지 않은 경우 무시
                pass
            self._selection_connected = False

        # 2. 이전 모델 저장 및 안전한 정리
        old_model = self.table_view.model()

        # 3. 새 모델 생성 및 설정
        df = self.current_model.get_dataframe()
        new_model = PandasModel(df)
        self.table_view.setModel(new_model)

        # 4. 이전 모델 명시적 정리 (Qt 객체 수명 관리)
        if old_model is not None:
            try:
                old_model.deleteLater()
            except RuntimeError:
                pass  # 이미 삭제된 객체

        # 5. 새 selectionModel의 시그널 연결 (한 번만)
        if not self._selection_connected:
            selection_model = self.table_view.selectionModel()
            if selection_model is not None:
                selection_model.selectionChanged.connect(self.on_selection_changed)
                self._selection_connected = True

        self.info_label.setText(f"표시된 행: {len(df)} / 원본 행: {self.original_model.get_count()}")

        if 'tags_string' in df.columns:
            try:
                tags_string_index = df.columns.get_loc('tags_string')
                self.table_view.setColumnHidden(tags_string_index, True)
            except KeyError:
                pass

    def apply_filters(self):
        """최적화된 필터링 순서로 성능 개선"""
        # 현재 결과가 있으면 그 안에서, 없으면 원본에서 검색 시작
        if not self.current_model.is_empty():
            temp_df = self.current_model.get_dataframe().copy()
        else:
            temp_df = self.original_model.get_dataframe().copy()
        
        # === 1단계: 숫자 필터 (가장 빠름) ===
        try:
            # ID 필터 (보통 가장 선택적)
            if self.id_min_check.isChecked():
                temp_df = temp_df[temp_df['id'] >= int(self.id_min_input.text())]
            if self.id_max_check.isChecked():
                temp_df = temp_df[temp_df['id'] <= int(self.id_max_input.text())]
            
            # Score 필터
            if self.score_min_check.isChecked():
                temp_df = temp_df[temp_df['score'] >= int(self.score_min_input.text())]
            
            # 이미지 크기 필터
            if self.w_min_check.isChecked():
                temp_df = temp_df[temp_df['image_width'] >= int(self.w_min_input.text())]
            if self.w_max_check.isChecked():
                temp_df = temp_df[temp_df['image_width'] <= int(self.w_max_input.text())]
            if self.h_min_check.isChecked():
                temp_df = temp_df[temp_df['image_height'] >= int(self.h_min_input.text())]
            if self.h_max_check.isChecked():
                temp_df = temp_df[temp_df['image_height'] <= int(self.h_max_input.text())]
            
            # 토큰 필터
            if self.token_min_check.isChecked():
                temp_df = temp_df[temp_df['tokens'] >= int(self.token_min_input.text())]
            if self.token_max_check.isChecked():
                temp_df = temp_df[temp_df['tokens'] <= int(self.token_max_input.text())]
                
        except (ValueError, KeyError) as e:
            self._show_msg(QMessageBox.Icon.Warning, "입력 오류", f"필터 값에 유효한 숫자를 입력해주세요.\n오류: {e}")
            return
        
        # 빠른 종료: 숫자 필터 후 결과가 없으면 중단
        if temp_df.empty:
            self.current_model = SearchResultModel(temp_df)
            self.update_view()
            return
        
        # === 2단계: 카테고리 필터 ===
        # Rating 필터 (최적화된 방식)
        enabled_ratings = {key for key, cb in self.d_rating_checkboxes.items() if cb.isChecked()}
        if len(enabled_ratings) < 4:  # 모든 등급이 선택되지 않은 경우만 필터링
            temp_df = temp_df[temp_df['rating'].isin(enabled_ratings)]

        # Character 필터
        if self.rem_char_check.isChecked() and self.only_empty_char_check.isChecked():
            # 두 옵션이 모두 체크된 경우, 결과는 0이 되므로 빈 데이터프레임 반환
            temp_df = pd.DataFrame(columns=temp_df.columns)
        elif self.rem_char_check.isChecked():
            temp_df = temp_df[temp_df['character'].notna()]
        elif self.only_empty_char_check.isChecked():
            temp_df = temp_df[temp_df['character'].isna()]
        
        # 빠른 종료: 카테고리 필터 후 결과가 없으면 중단
        if temp_df.empty:
            self.current_model = SearchResultModel(temp_df)
            self.update_view()
            return
        
        # === 3단계: 텍스트 검색 (가장 느림, 마지막에 수행) ===
        # 검색어나 제외어가 있을 때만 수행
        search_text = self.d_search_input.text().strip()
        exclude_text = self.d_exclude_input.text().strip()
        
        if search_text or exclude_text:
            temp_df = self.search_engine._apply_filters(
                temp_df, search_text, exclude_text
            )
        
        self.current_model = SearchResultModel(temp_df)
        self.update_view()

    # [신규] 스태커 기능 메서드
    def import_parquet(self):
        path, _ = QFileDialog.getOpenFileName(self, "Parquet 파일 불러오기", "", "Parquet Files (*.parquet)")
        if not path:
            return
        try:
            import_df = pd.read_parquet(path)
            self.current_model.append_dataframe(import_df)
            self.current_model.deduplicate() # 합친 후 중복 제거
            self.update_view()
            #QMessageBox.information(self, "성공", "데이터를 성공적으로 불러와 합쳤습니다.")
        except Exception as e:
            self._show_msg(QMessageBox.Icon.Critical, "오류", f"파일을 불러오는 중 오류 발생:\n{e}")
            
    def clear_current_view(self):
        self.current_model = SearchResultModel()
        self.update_view()

    def assign_results_to_main(self):
        """현재 필터링된 결과를 메인 윈도우로 보냄"""
        self.results_assigned.emit(self.current_model)
        #QMessageBox.information(self, "완료", f"{self.current_model.get_count()}개의 결과가 메인 UI에 할당되었습니다.")

    def promote_current_to_original(self):
        """현재 필터링된 결과를 원본 행으로 승격"""
        current_count = self.current_model.get_count()
        original_count = self.original_model.get_count()

        if current_count == original_count:
            self._show_msg(QMessageBox.Icon.Warning, "경고", "표시된 행과 원본 행이 동일합니다.")
            return

        df = self.current_model.get_dataframe().copy()
        if 'tags_string' in df.columns:
            df = df.drop(columns=['tags_string'])
        self.original_model = SearchResultModel(df)
        self.current_model = SearchResultModel(df.copy())
        self._ensure_tags_string(self.current_model.get_dataframe())

        # 검색 텍스트 초기화
        self.d_search_input.clear()
        self.d_exclude_input.clear()
        self.update_view()

    def restore_to_original(self):
        """뷰를 초기 데이터 상태로 되돌림"""
        self.current_model = SearchResultModel(self.original_model.get_dataframe().copy())
        self._ensure_tags_string(self.current_model.get_dataframe())
        self.update_view()

    def reset_from_search_result(self, search_result: SearchResultModel):
        """현재 메인 검색 결과를 심층검색의 새 원본으로 다시 로드"""
        if not isinstance(search_result, SearchResultModel) or search_result.is_empty():
            self._show_msg(QMessageBox.Icon.Warning, "경고", "새로 불러올 메인 검색 결과가 없습니다.")
            return

        df = search_result.get_dataframe().copy()
        if 'tags_string' in df.columns:
            df = df.drop(columns=['tags_string'])

        self.original_model = SearchResultModel(df.copy())
        self.current_model = SearchResultModel(df.copy())
        self._ensure_tags_string(self.current_model.get_dataframe())

        self._reset_filter_controls()
        self.staged_items.clear()
        self._update_staging_ui()
        self.general_text_edit.clear()
        self.current_sort_order = {}
        self.update_view()

    def _reset_filter_controls(self):
        """심층검색 필터 입력을 기본 상태로 되돌림"""
        self.d_search_input.clear()
        self.d_exclude_input.clear()

        for checkbox in self.d_rating_checkboxes.values():
            checkbox.setChecked(True)

        defaults = (
            (self.w_min_check, self.w_min_input, "0"),
            (self.w_max_check, self.w_max_input, "9999"),
            (self.h_min_check, self.h_min_input, "0"),
            (self.h_max_check, self.h_max_input, "9999"),
            (self.token_min_check, self.token_min_input, "0"),
            (self.token_max_check, self.token_max_input, "150"),
            (self.id_min_check, self.id_min_input, "0"),
            (self.id_max_check, self.id_max_input, "99999999"),
            (self.score_min_check, self.score_min_input, "0"),
        )
        for checkbox, input_widget, value in defaults:
            checkbox.setChecked(False)
            input_widget.setText(value)

        self.rem_char_check.setChecked(False)
        self.only_empty_char_check.setChecked(False)

    def export_to_parquet(self):
        """현재 뷰의 데이터를 Parquet 파일로 저장"""
        if self.current_model.is_empty():
            self._show_msg(QMessageBox.Icon.Warning, "경고", "내보낼 데이터가 없습니다.")
            return

        path, _ = QFileDialog.getSaveFileName(self, "Parquet 파일로 저장", "", "Parquet Files (*.parquet)")
        if path:
            try:
                self.current_model.get_dataframe().to_parquet(path)
                self._show_msg(QMessageBox.Icon.Information, "성공", f"'{path}'에 성공적으로 저장했습니다.")
            except Exception as e:
                self._show_msg(QMessageBox.Icon.Critical, "오류", f"파일 저장 중 오류 발생:\n{e}")

    # --- 검색 속도 최적화 ---

    def _show_msg(self, icon, title, text):
        """TODO(web-dialog): 원래 QMessageBox — Web Shell 토스트로 재구현 필요. 현재는 콘솔 출력만."""
        print(f"[Dialog] depth_search — {title}: {text}")

    def _ensure_tags_string(self, df):
        """tags_string 컬럼이 없으면 빌드하여 캐싱 (이후 재검색 시 재빌드 불필요)"""
        if not df.empty and 'tags_string' not in df.columns:
            df['tags_string'] = self.search_engine._build_tags_string(df)

    # --- 스테이징 기능 ---

    def add_to_staging(self):
        """현재 뷰의 필터링된 결과를 스테이징에 추가"""
        if self.current_model.is_empty():
            self._show_msg(QMessageBox.Icon.Warning, "경고", "스테이징에 추가할 데이터가 없습니다.")
            return

        if self.current_model.get_count() == self.original_model.get_count():
            self._show_msg(QMessageBox.Icon.Warning, "경고", "표시된 행과 원본 행이 동일합니다. 필터를 적용한 후 추가해주세요.")
            return

        query = self.d_search_input.text().strip()
        exclude = self.d_exclude_input.text().strip()
        df = self.current_model.get_dataframe().copy()

        # tags_string 파생 컬럼은 저장하지 않음 (메모리 절약)
        if 'tags_string' in df.columns:
            df = df.drop(columns=['tags_string'])

        self.staged_items.append({
            'query': query or '(전체)',
            'exclude': exclude,
            'df': df
        })
        self._update_staging_ui()

        # 검색/제외 키워드 초기화 및 원본 행 복원
        self.d_search_input.clear()
        self.d_exclude_input.clear()
        self.restore_to_original()

    def remove_from_staging(self, index):
        """스테이징에서 항목 제거"""
        if 0 <= index < len(self.staged_items):
            self.staged_items.pop(index)
            self._update_staging_ui()

    def merge_staging(self):
        """스테이징된 모든 항목을 병합하여 현재 뷰에 적용"""
        if not self.staged_items:
            return

        dfs = [item['df'] for item in self.staged_items]
        merged = pd.concat(dfs, ignore_index=True)

        # 중복 제거 (general 컬럼 기준)
        if 'general' in merged.columns:
            merged.drop_duplicates(subset=['general'], keep='first', inplace=True)
            merged.reset_index(drop=True, inplace=True)

        self.current_model = SearchResultModel(merged)
        self._ensure_tags_string(self.current_model.get_dataframe())

        self.staged_items.clear()
        self._update_staging_ui()
        self.update_view()

    def clear_staging(self):
        """스테이징 목록 초기화"""
        self.staged_items.clear()
        self._update_staging_ui()

    def _update_staging_ui(self):
        """스테이징 UI 갱신 (프레임 가시성 전환 + 항목 위젯 재구성)"""
        has_items = len(self.staged_items) > 0

        # general_text_edit <-> staging_frame 가시성 전환
        self.general_text_edit.setVisible(not has_items)
        self.staging_frame.setVisible(has_items)
        self.merge_staging_btn.setVisible(has_items)
        self.clear_staging_btn.setVisible(has_items)

        # 기존 위젯 제거
        while self.staging_items_layout.count():
            child = self.staging_items_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # 항목 위젯 추가
        total_rows = 0
        for i, item in enumerate(self.staged_items):
            count = len(item['df'])
            total_rows += count
            widget = StagingItemWidget(i, item['query'], item['exclude'], count)
            widget.remove_requested.connect(self.remove_from_staging)
            self.staging_items_layout.addWidget(widget)

        if has_items:
            self.staging_summary_label.setText(
                f"총 {len(self.staged_items)}개 항목, {total_rows:,}건 (병합 시 중복 제거)"
            )

    def on_header_clicked(self, logicalIndex):
        """헤더 클릭 시 커스텀 정렬 수행 (내림차순 우선)"""
        current_order = self.current_sort_order.get(logicalIndex, Qt.SortOrder.DescendingOrder)
        
        if current_order == Qt.SortOrder.DescendingOrder:
            new_order = Qt.SortOrder.AscendingOrder
        else:
            new_order = Qt.SortOrder.DescendingOrder
            
        self.current_sort_order = {logicalIndex: new_order} # 다른 컬럼 정렬 상태 초기화
        self.table_view.model().sort(logicalIndex, new_order)
        self.table_view.horizontalHeader().setSortIndicator(logicalIndex, new_order)

    def show_table_context_menu(self, position):
        """테이블 위에서 우클릭 시 컨텍스트 메뉴 표시"""
        index = self.table_view.indexAt(position)
        if not index.isValid():
            return

        df = self.table_view.model().dataframe()
        col_name = df.columns[index.column()]
        
        if col_name not in ['copyright', 'character', 'artist']:
            return

        value = df.iloc[index.row(), index.column()]
        if not value or pd.isna(value):
            return

        menu = QMenu()
        action_text = f"'{value}' (으)로 즉시 검색"
        instant_search_action = QAction(action_text, self)
        instant_search_action.triggered.connect(lambda: self.perform_instant_search(value))
        menu.addAction(instant_search_action)
        menu.exec(QCursor.pos())

    def perform_instant_search(self, keyword: str):
        """단일 키워드로 즉시 재검색 수행"""
        self.d_search_input.setText(f'{keyword}') # 정확한 검색을 위해 따옴표 추가
        self.d_exclude_input.clear()
        self.apply_filters()

    def cleanup(self):
        """
        윈도우 종료 시 안전한 정리

        🔧 크래시 방지:
        - 시그널 연결 해제
        - Qt 객체 명시적 정리
        - 메모리 누수 방지
        """
        try:
            # 1. 시그널 연결 해제
            if self._selection_connected:
                selection_model = self.table_view.selectionModel()
                if selection_model is not None:
                    try:
                        selection_model.selectionChanged.disconnect(self.on_selection_changed)
                    except (RuntimeError, TypeError):
                        pass
                self._selection_connected = False

            # 2. 모델 정리
            model = self.table_view.model()
            if model is not None:
                try:
                    self.table_view.setModel(None)
                    model.deleteLater()
                except RuntimeError:
                    pass

            # 3. 스테이징 정리
            if hasattr(self, 'staged_items'):
                self.staged_items.clear()

            # 4. 참조 해제
            self.original_model = None
            self.current_model = None

            print("✅ DepthSearchWindow 정리 완료")

        except Exception as e:
            print(f"⚠️ DepthSearchWindow 정리 중 오류: {e}")

    def closeEvent(self, event):
        """창이 닫힐 때 자동으로 cleanup 호출"""
        self.cleanup()
        super().closeEvent(event)
