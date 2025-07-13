import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QTableView, QHeaderView, QAbstractItemView,
    QFileDialog, QMessageBox, QSplitter, QFrame, QTextEdit, QMenu
)
from PyQt6.QtGui import QCursor, QAction, QIntValidator
from PyQt6.QtCore import QAbstractTableModel, Qt, pyqtSignal
from core.search_result_model import SearchResultModel
from core.search_engine import SearchEngine
from ui.theme import DARK_COLORS

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
            self.layoutAboutToBeChanged.emit()
            col_name = self.dataframe().columns[column]
            self._df = self.dataframe().sort_values(
                col_name, ascending=(order == Qt.SortOrder.AscendingOrder), kind='mergesort'
            )
            self.layoutChanged.emit()
        except: pass

    def dataframe(self):
        return self._df

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
        
        self.table_view.setSortingEnabled(True)
        # [수정] Qt 기본 정렬 대신 커스텀 정렬 사용
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
        grid.addWidget(QLabel("검색 키워드:", self, styleSheet=label_style), 0, 0, 1, 4)
        self.d_search_input = QLineEdit(styleSheet=input_style)
        grid.addWidget(self.d_search_input, 1, 0, 1, 4)
        
        grid.addWidget(QLabel("제외 키워드:", self, styleSheet=label_style), 2, 0, 1, 4)
        self.d_exclude_input = QLineEdit(styleSheet=input_style)
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
        # [수정] 스타일 적용
        container = QFrame()
        container.setStyleSheet("border: none;")
        layout = QVBoxLayout(container)
        # title = QLabel("데이터 스태커")
        # title.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: 16px; font-weight: 600; margin-bottom: 5px;")
        # layout.addWidget(title)
        
        self.general_text_edit = QTextEdit()
        self.general_text_edit.setReadOnly(True)
        self.general_text_edit.setStyleSheet(f"""
            background-color: {DARK_COLORS['bg_secondary']}; border: 1px solid {DARK_COLORS['border']};
            border-radius: 4px; padding: 5px; color: {DARK_COLORS['text_primary']};
        """)
        self.general_text_edit.setPlaceholderText("테이블 행을 클릭하여 general 태그 보기...")
        layout.addWidget(self.general_text_edit, 1) # Stretch factor 1
        
        button_style = f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']}; border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px; padding: 8px; color: {DARK_COLORS['text_primary']};
            }}
            QPushButton:hover {{ background-color: {DARK_COLORS['bg_hover']}; }}
        """
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
        """선택된 행이 변경될 때마다 호출 (마우스 클릭, 키보드 이동 모두 포함)"""
        # 선택된 인덱스 목록에서 첫 번째 인덱스를 가져옴
        indexes = selected.indexes()
        if not indexes:
            return

        current_index = indexes[0]
        row = current_index.row()
        df = self.table_view.model().dataframe()
        
        try:
            original_index = df.index[row]
            general_text = df.loc[original_index, 'general']
            self.general_text_edit.setText(general_text)
        except (KeyError, IndexError):
            self.general_text_edit.setText("'general' 컬럼을 찾을 수 없거나 행이 잘못되었습니다.")
            
        # [핵심] 이벤트를 처리한 후, 테이블 뷰에 다시 키보드 포커스를 줌
        self.table_view.setFocus()
    
    def update_view(self):
        """현재 모델 데이터로 테이블 뷰와 정보 레이블을 업데이트"""
        df = self.current_model.get_dataframe()
        model = PandasModel(df)
        self.table_view.setModel(model) # 모델 설정
        
        # [핵심 수정] 모델이 설정된 직후에 selectionModel의 시그널을 연결합니다.
        self.table_view.selectionModel().selectionChanged.connect(self.on_selection_changed)

        self.info_label.setText(f"표시된 행: {len(df)} / 원본 행: {self.original_model.get_count()}")

        if 'tags_string' in df.columns:
            try:
                tags_string_index = df.columns.get_loc('tags_string')
                self.table_view.setColumnHidden(tags_string_index, True)
            except KeyError:
                pass

    def apply_filters(self):
        """입력된 모든 필터 조건에 따라 필터링하고 뷰 업데이트"""
        # [수정] 현재 결과가 있으면 그 안에서, 없으면 원본에서 검색 시작
        if not self.current_model.is_empty():
            temp_df = self.current_model.get_dataframe().copy()
        else:
            temp_df = self.original_model.get_dataframe().copy()
        
        # [신규] 등급 필터링 로직 추가
        enabled_ratings = {key for key, cb in self.d_rating_checkboxes.items() if cb.isChecked()}
        temp_df = temp_df[temp_df['rating'].isin(enabled_ratings)]
        temp_df = self.search_engine._apply_filters(
            temp_df, self.d_search_input.text(), self.d_exclude_input.text()
        )

        # [신규] 추가 필터 로직
        try:
            if self.w_min_check.isChecked(): temp_df = temp_df[temp_df['image_width'] >= int(self.w_min_input.text())]
            if self.w_max_check.isChecked(): temp_df = temp_df[temp_df['image_width'] <= int(self.w_max_input.text())]
            if self.h_min_check.isChecked(): temp_df = temp_df[temp_df['image_height'] >= int(self.h_min_input.text())]
            if self.h_max_check.isChecked(): temp_df = temp_df[temp_df['image_height'] <= int(self.h_max_input.text())]
            
            if self.token_min_check.isChecked(): temp_df = temp_df[temp_df['tokens'] >= int(self.token_min_input.text())]
            if self.token_max_check.isChecked(): temp_df = temp_df[temp_df['tokens'] <= int(self.token_max_input.text())]
            if self.id_min_check.isChecked(): temp_df = temp_df[temp_df['id'] >= int(self.id_min_input.text())]
            if self.id_max_check.isChecked(): temp_df = temp_df[temp_df['id'] <= int(self.id_max_input.text())]
            if self.score_min_check.isChecked(): temp_df = temp_df[temp_df['score'] >= int(self.score_min_input.text())]
            if self.rem_char_check.isChecked() and self.only_empty_char_check.isChecked():
                # 두 옵션이 모두 체크된 경우, 결과는 0이 되므로 빈 데이터프레임 반환
                temp_df = pd.DataFrame(columns=temp_df.columns)
            elif self.rem_char_check.isChecked():
                temp_df = temp_df[temp_df['character'].notna()]
            elif self.only_empty_char_check.isChecked():
                temp_df = temp_df[temp_df['character'].isna()]
                
        except (ValueError, KeyError) as e:
            QMessageBox.warning(self, "입력 오류", f"필터 값에 유효한 숫자를 입력해주세요.\n오류: {e}")
            return

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
            QMessageBox.critical(self, "오류", f"파일을 불러오는 중 오류 발생:\n{e}")
            
    def clear_current_view(self):
        self.current_model = SearchResultModel()
        self.update_view()

    def assign_results_to_main(self):
        """현재 필터링된 결과를 메인 윈도우로 보냄"""
        self.results_assigned.emit(self.current_model)
        #QMessageBox.information(self, "완료", f"{self.current_model.get_count()}개의 결과가 메인 UI에 할당되었습니다.")

    def restore_to_original(self):
        """뷰를 초기 데이터 상태로 되돌림"""
        self.current_model = SearchResultModel(self.original_model.get_dataframe().copy())
        self.update_view()

    def export_to_parquet(self):
        """현재 뷰의 데이터를 Parquet 파일로 저장"""
        if self.current_model.is_empty():
            QMessageBox.warning(self, "경고", "내보낼 데이터가 없습니다.")
            return

        path, _ = QFileDialog.getSaveFileName(self, "Parquet 파일로 저장", "", "Parquet Files (*.parquet)")
        if path:
            try:
                self.current_model.get_dataframe().to_parquet(path)
                QMessageBox.information(self, "성공", f"'{path}'에 성공적으로 저장했습니다.")
            except Exception as e:
                QMessageBox.critical(self, "오류", f"파일 저장 중 오류 발생:\n{e}")

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
