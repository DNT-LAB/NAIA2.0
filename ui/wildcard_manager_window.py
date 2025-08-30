import os
import platform
import subprocess
from pathlib import Path
from typing import Dict, List, Optional
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator, QTextEdit, QPushButton,
    QLabel, QLineEdit, QMessageBox, QGroupBox, QComboBox,
    QSpinBox, QCheckBox, QStatusBar, QTabWidget
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QTextCursor
from ui.theme import DARK_STYLES, get_dynamic_styles, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.modern_menu import setModernStyle


class WildcardManagerWindow(QMainWindow):
    """
    와일드카드를 검색, 편집, 관리할 수 있는 독립적인 윈도우
    """
    
    wildcards_updated = pyqtSignal()
    
    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.wildcard_manager = app_context.wildcard_manager
        self.current_file_path = None
        self.is_modified = False
        self.is_edit_mode = False  # 편집 모드 상태 추가
        self.original_content = ""
        self.last_selected_dependent_input = None  # 종속 탭의 마지막 선택된 입력 필드
        
        self.init_ui()
        self.load_wildcard_tree()
        
    def init_ui(self):
        """UI 초기화"""
        self.setWindowTitle("📝 와일드카드 관리자")
        self.setGeometry(100, 100, get_scaled_size(1200), get_scaled_size(800))
        
        # 다크 테마 적용
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {DARK_COLORS['background']};
            }}
        """)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(get_scaled_size(10))
        main_layout.setContentsMargins(
            get_scaled_size(10), get_scaled_size(10),
            get_scaled_size(10), get_scaled_size(10)
        )
        
        # 동적 스타일 가져오기
        dynamic_styles = get_dynamic_styles()
        
        # 상단 툴바
        toolbar_layout = QHBoxLayout()
        
        # 검색 필드
        search_label = QLabel("🔍 검색:")
        search_label.setStyleSheet(dynamic_styles['label_style'])
        toolbar_layout.addWidget(search_label)
        
        self.search_input = QLineEdit()
        self.search_input.setStyleSheet(dynamic_styles['compact_lineedit'])
        self.search_input.setPlaceholderText("와일드카드 이름 또는 내용 검색...")
        self.search_input.textChanged.connect(self.filter_tree)
        self.search_input.setMinimumWidth(get_scaled_size(300))
        self.search_input.setProperty("autocomplete_ignore", True)
        toolbar_layout.addWidget(self.search_input)
        
        # 검색 초기화 버튼
        self.clear_search_btn = QPushButton("🔄 초기화")
        self.clear_search_btn.setStyleSheet(dynamic_styles['compact_button'])
        self.clear_search_btn.setFixedHeight(get_scaled_font_size(28))
        self.clear_search_btn.clicked.connect(self.clear_search)
        self.clear_search_btn.setToolTip("검색어를 초기화하고 모든 항목을 표시합니다")
        toolbar_layout.addWidget(self.clear_search_btn)
        
        toolbar_layout.addStretch()
        
        # 폴더 열기 버튼
        self.open_folder_btn = QPushButton("📁 폴더 열기")
        self.open_folder_btn.setStyleSheet(dynamic_styles['secondary_button'])
        self.open_folder_btn.setFixedHeight(get_scaled_font_size(28))
        self.open_folder_btn.clicked.connect(self.open_wildcards_folder)
        self.open_folder_btn.setToolTip("wildcards 폴더를 파일 탐색기에서 엽니다")
        toolbar_layout.addWidget(self.open_folder_btn)
        
        # 새 파일 버튼
        self.new_file_btn = QPushButton("➕ 새 파일")
        self.new_file_btn.setStyleSheet(dynamic_styles['primary_button'])
        self.new_file_btn.setFixedHeight(get_scaled_font_size(28))
        self.new_file_btn.clicked.connect(self.create_new_file)
        toolbar_layout.addWidget(self.new_file_btn)
        
        # 새로고침 버튼
        self.refresh_btn = QPushButton("🔄 새로고침")
        self.refresh_btn.setStyleSheet(dynamic_styles['secondary_button'])
        self.refresh_btn.setFixedHeight(get_scaled_font_size(28))
        self.refresh_btn.clicked.connect(self.reload_wildcards)
        toolbar_layout.addWidget(self.refresh_btn)
        
        main_layout.addLayout(toolbar_layout)
        
        # 메인 컨텐츠 레이아웃 (QHBoxLayout으로 변경)
        main_content_layout = QHBoxLayout()
        main_content_layout.setSpacing(get_scaled_size(10))
        
        # 왼쪽: TreeView
        left_widget = QWidget()
        left_widget.setFixedWidth(get_scaled_size(400))  # 고정 너비 설정
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # 와일드카드 파일 라벨과 그룹 추가 버튼
        tree_header_layout = QHBoxLayout()
        tree_header_layout.setContentsMargins(0, 0, 0, 0)
        
        tree_label = QLabel("📁 와일드카드 파일")
        tree_label.setStyleSheet(dynamic_styles['label_style'])
        tree_header_layout.addWidget(tree_label)
        
        tree_header_layout.addStretch()
        
        # 그룹 추가 버튼
        self.add_group_btn = QPushButton("📂 그룹 추가")
        self.add_group_btn.setStyleSheet(dynamic_styles['compact_button'])
        self.add_group_btn.setFixedHeight(get_scaled_font_size(24))
        self.add_group_btn.clicked.connect(self.create_new_group)
        self.add_group_btn.setToolTip("새 그룹(폴더)를 생성합니다")
        tree_header_layout.addWidget(self.add_group_btn)
        
        left_layout.addLayout(tree_header_layout)
        
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderHidden(True)
        self.tree_widget.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(5)}px;
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_primary']};
            }}
            QTreeWidget::item {{
                padding: {get_scaled_size(4)}px;
                min-height: {get_scaled_size(24)}px;
            }}
            QTreeWidget::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
            QTreeWidget::item:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        self.tree_widget.itemClicked.connect(self.on_tree_item_clicked)
        left_layout.addWidget(self.tree_widget)
        
        main_content_layout.addWidget(left_widget)
        
        # 중간: 편집 영역 (너비를 2/3로 축소)
        middle_widget = QWidget()
        middle_widget.setMinimumWidth(get_scaled_size(500))  # 최소 너비 설정
        middle_layout = QVBoxLayout(middle_widget)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(get_scaled_size(10))
        
        # 컨텐츠 뷰어/편집기
        content_group = QGroupBox("📝 와일드카드 내용")
        content_group.setStyleSheet(f"""
            QGroupBox {{
                font-size: {get_scaled_font_size(18)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(5)}px;
                padding-top: {get_scaled_size(25)}px;
                margin-top: {get_scaled_size(10)}px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {get_scaled_size(10)}px;
                padding: 0 {get_scaled_size(5)}px;
            }}
        """)
        content_layout = QVBoxLayout(content_group)
        
        # 파일 경로 표시
        self.file_path_label = QLabel("선택된 파일 없음")
        self.file_path_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(14)}px;
            color: #B0B0B0;
            padding: {get_scaled_size(5)}px;
        """)
        content_layout.addWidget(self.file_path_label)
        
        # 텍스트 에디터 (처음에는 읽기 전용)
        self.content_edit = QTextEdit()
        self.content_edit.setStyleSheet(dynamic_styles['compact_textedit'])
        self.content_edit.setMinimumHeight(get_scaled_size(300))
        self.content_edit.setProperty("autocomplete_ignore", True)
        self.content_edit.setReadOnly(True)  # 처음에는 읽기 전용
        setModernStyle(self.content_edit)
        self.content_edit.textChanged.connect(self.on_content_changed)
        content_layout.addWidget(self.content_edit)
        
        # 편집 버튼들
        edit_button_layout = QHBoxLayout()
        edit_button_layout.addStretch()
        
        self.save_btn = QPushButton("💾 저장")
        self.save_btn.setStyleSheet(dynamic_styles['primary_button'])
        self.save_btn.setFixedHeight(get_scaled_font_size(28))
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self.save_current_file)
        edit_button_layout.addWidget(self.save_btn)
        
        # 수정/취소 토글 버튼
        self.edit_toggle_btn = QPushButton("✏️ 수정")
        self.edit_toggle_btn.setStyleSheet(dynamic_styles['secondary_button'])
        self.edit_toggle_btn.setFixedHeight(get_scaled_font_size(28))
        self.edit_toggle_btn.setEnabled(False)
        self.edit_toggle_btn.clicked.connect(self.toggle_edit_mode)
        edit_button_layout.addWidget(self.edit_toggle_btn)
        
        self.delete_btn = QPushButton("🗑️ 삭제")
        self.delete_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #8B0000;
                color: white;
                border: none;
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px {get_scaled_size(12)}px;
                font-size: {get_scaled_font_size(16)}px;
            }}
            QPushButton:hover {{
                background-color: #A52A2A;
            }}
            QPushButton:pressed {{
                background-color: #CD5C5C;
            }}
            QPushButton:disabled {{
                background-color: #4A4A4A;
                color: #888888;
            }}
        """)
        self.delete_btn.setFixedHeight(get_scaled_font_size(28))
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self.delete_current_file)
        edit_button_layout.addWidget(self.delete_btn)
        
        content_layout.addLayout(edit_button_layout)
        
        middle_layout.addWidget(content_group)
        
        # 중간 위젯의 너비 비율을 2로, 빈 공간을 1로 설정하여 2/3 크기를 차지하도록 함
        main_content_layout.addWidget(middle_widget, 2)
        main_content_layout.addStretch(1)
        
        # 오른쪽: 와일드카드 생성 도구 (1/2 크기로 축소)
        right_widget = QWidget()
        right_widget.setFixedWidth(get_scaled_size(450))  # 고정 너비 설정
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # 와일드카드 생성 도구 그룹
        generator_group = QGroupBox("🎲 와일드카드 생성 도구")
        generator_group.setStyleSheet(f"""
            QGroupBox {{
                font-size: {get_scaled_font_size(18)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(5)}px;
                padding-top: {get_scaled_size(25)}px;
                margin-top: {get_scaled_size(10)}px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {get_scaled_size(10)}px;
                padding: 0 {get_scaled_size(5)}px;
            }}
        """)
        generator_layout = QVBoxLayout(generator_group)
        
        # 탭 위젯 생성
        self.generator_tabs = QTabWidget()
        self.generator_tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {DARK_COLORS['border']};
                background: {DARK_COLORS['bg_tertiary']};
                border-radius: {get_scaled_size(5)}px;
                margin-top: -1px;
            }}
            QTabBar::tab {{
                background: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_secondary']};
                padding: {get_scaled_size(8)}px {get_scaled_size(16)}px;
                margin-right: {get_scaled_size(2)}px;
                border: 1px solid transparent;
                border-bottom: none;
                border-top-left-radius: {get_scaled_size(5)}px;
                border-top-right-radius: {get_scaled_size(5)}px;
                font-size: {get_scaled_font_size(14)}px;
            }}
            QTabBar::tab:selected {{
                background: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                font-weight: bold;
                border-color: {DARK_COLORS['border']};
                border-bottom-color: {DARK_COLORS['bg_tertiary']};
            }}
            QTabBar::tab:!selected:hover {{
                background: {DARK_COLORS['bg_hover']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        
        # 일반 탭
        normal_tab = self.create_normal_tab()
        self.generator_tabs.addTab(normal_tab, "일반")
        
        # 순차 탭
        sequential_tab = self.create_sequential_tab()
        self.generator_tabs.addTab(sequential_tab, "*순차")
        
        # 종속 탭
        dependent_tab = self.create_dependent_tab()
        self.generator_tabs.addTab(dependent_tab, "*순차:$종속")
        
        generator_layout.addWidget(self.generator_tabs)

        # 현재 탭 전용 미리보기 갱신을 위해 인덱스 매핑 및 탭 변경 핸들러 연결
        self._gen_tab_index = {'normal': 0, 'sequential': 1, 'dependent': 2}
        self.generator_tabs.currentChanged.connect(self.refresh_current_preview)
        
        # 공통 미리보기 (모든 탭에서 공유)
        # 위젯을 세로로 배치하기 위해 QVBoxLayout 사용
        preview_v_layout = QVBoxLayout()

        # 1. 미리보기 라벨
        preview_label = QLabel("미리보기:")
        preview_label.setStyleSheet(dynamic_styles['label_style'])
        preview_v_layout.addWidget(preview_label)

        # 2. 미리보기 텍스트 에디터
        self.preview_edit = QTextEdit()
        self.preview_edit.setStyleSheet(dynamic_styles['compact_textedit'])
        self.preview_edit.setReadOnly(True)
        self.preview_edit.setFixedHeight(get_scaled_size(80)) # 3-4줄 높이
        preview_v_layout.addWidget(self.preview_edit)

        # 3. 복사 버튼 (오른쪽 정렬)
        copy_btn_layout = QHBoxLayout()
        copy_btn_layout.addStretch() # 왼쪽에 빈 공간을 추가하여 버튼을 오른쪽으로 밀어냄
        
        self.copy_btn = QPushButton("📋 클립보드에 복사 ")
        self.copy_btn.setStyleSheet(dynamic_styles['compact_button'])
        self.copy_btn.setFixedSize(get_scaled_font_size(160), get_scaled_font_size(32))
        self.copy_btn.clicked.connect(self.copy_preview)
        self.copy_btn.setToolTip("클립보드에 복사")
        copy_btn_layout.addWidget(self.copy_btn)
        
        preview_v_layout.addLayout(copy_btn_layout)
        
        generator_layout.addLayout(preview_v_layout)
        
        right_layout.addWidget(generator_group)
        
        # 검색 결과 표시 영역 추가
        search_results_group = QGroupBox("🔍 검색 결과")
        search_results_group.setStyleSheet(f"""
            QGroupBox {{
                font-size: {get_scaled_font_size(18)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(5)}px;
                padding-top: {get_scaled_size(25)}px;
                margin-top: {get_scaled_size(10)}px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {get_scaled_size(10)}px;
                padding: 0 {get_scaled_size(5)}px;
            }}
        """)
        search_results_layout = QVBoxLayout(search_results_group)
        
        # 검색 결과 텍스트 에디터 (읽기 전용)
        self.search_results_edit = QTextEdit()
        self.search_results_edit.setStyleSheet(dynamic_styles['compact_textedit'])
        self.search_results_edit.setReadOnly(True)
        self.search_results_edit.setMinimumHeight(get_scaled_size(150))
        self.search_results_edit.setMaximumHeight(get_scaled_size(250))
        self.search_results_edit.setPlaceholderText("검색어를 입력하면 현재 파일에서 매칭되는 라인들이 표시됩니다")
        setModernStyle(self.search_results_edit)
        search_results_layout.addWidget(self.search_results_edit)
        
        right_layout.addWidget(search_results_group)
        right_layout.addStretch()
        
        main_content_layout.addWidget(right_widget)
        
        main_layout.addLayout(main_content_layout)
        
        # 메인 윈도우 하단에 상태바 추가 - 최소 공간만 차지
        self.setStatusBar(QStatusBar())
        self.statusBar().setStyleSheet(f"""
            QStatusBar {{
                color: {DARK_COLORS['text_secondary']};
                background: {DARK_COLORS['bg_secondary']};
                border-top: 1px solid {DARK_COLORS['border']};
                font-size: {get_scaled_font_size(13)}px;
                max-height: {get_scaled_font_size(22)}px;
            }}
            QStatusBar::item {{
                border: none;
            }}
        """)
        self.statusBar().showMessage("준비")
        
    def load_wildcard_tree(self):
        """와일드카드 트리 로드"""
        self.tree_widget.clear()
        
        # 루트 아이템 생성
        root_item = QTreeWidgetItem(self.tree_widget, ["📂 wildcards"])
        root_item.setExpanded(True)
        
        # 와일드카드 디렉토리 탐색
        wildcards_dir = self.wildcard_manager.wildcards_dir
        if not os.path.exists(wildcards_dir):
            os.makedirs(wildcards_dir)
            
        # 파일 및 폴더 구조 생성
        self._add_directory_to_tree(wildcards_dir, root_item)
        
        # 총 와일드카드 수 표시
        total_count = len(self.wildcard_manager.wildcard_dict_tree)
        self.statusBar().showMessage(f"총 {total_count}개의 와일드카드 로드됨")
        
    def _add_directory_to_tree(self, dir_path: str, parent_item: QTreeWidgetItem):
        """디렉토리를 트리에 추가"""
        try:
            items = []
            
            # 파일과 폴더 분리
            for item_name in os.listdir(dir_path):
                item_path = os.path.join(dir_path, item_name)
                
                if os.path.isdir(item_path):
                    # 폴더
                    folder_item = QTreeWidgetItem(parent_item, [f"📁 {item_name}"])
                    folder_item.setData(0, Qt.ItemDataRole.UserRole, item_path)
                    self._add_directory_to_tree(item_path, folder_item)
                    
                elif item_name.endswith('.txt'):
                    # 텍스트 파일
                    file_item = QTreeWidgetItem(parent_item, [f"📄 {item_name}"])
                    file_item.setData(0, Qt.ItemDataRole.UserRole, item_path)
                    
                    # 파일 내 라인 수 표시
                    try:
                        with open(item_path, 'r', encoding='utf-8', errors='ignore') as f:
                            line_count = sum(1 for line in f if line.strip())
                        file_item.setText(0, f"📄 {item_name} ({line_count})")
                    except:
                        pass
                        
        except Exception as e:
            print(f"디렉토리 로드 오류: {e}")
            
    def filter_tree(self, search_text: str):
        """트리 필터링"""
        search_text = search_text.lower()
        
        # 현재 열린 파일이 있으면 검색 결과도 업데이트
        if self.current_file_path and search_text:
            self.highlight_search_in_content(search_text)
        elif not search_text:
            # 검색어가 비어있으면 검색 결과 초기화
            self.search_results_edit.clear()
            self.search_results_edit.setPlaceholderText("검색어를 입력하면 현재 파일에서 매칭되는 라인들이 표시됩니다")
        
        # 모든 아이템 순회
        iterator = QTreeWidgetItemIterator(self.tree_widget)
        while iterator.value():
            item = iterator.value()
            
            # 루트는 항상 표시
            if item.parent() is None:
                item.setHidden(False)
            else:
                # 검색어가 비어있으면 모두 표시
                if not search_text:
                    item.setHidden(False)
                else:
                    # 아이템 이름이나 내용에 검색어가 포함되어 있는지 확인
                    item_text = item.text(0).lower()
                    file_path = item.data(0, Qt.ItemDataRole.UserRole)
                    
                    matches = search_text in item_text
                    
                    # 파일 내용도 검색
                    if not matches and file_path and os.path.isfile(file_path):
                        try:
                            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read().lower()
                                matches = search_text in content
                        except:
                            pass
                    
                    item.setHidden(not matches)
                    
                    # 매치되는 아이템의 부모는 표시
                    if matches:
                        parent = item.parent()
                        while parent:
                            parent.setHidden(False)
                            parent = parent.parent()
            
            iterator += 1
            
    def on_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        """트리 아이템 클릭 처리"""
        # 편집 모드에서는 다른 파일 선택 불가
        if self.is_edit_mode:
            QMessageBox.warning(self, "경고", "편집 모드에서는 다른 파일을 선택할 수 없습니다.\n먼저 현재 편집을 완료하거나 취소해주세요.")
            return
            
        file_path = item.data(0, Qt.ItemDataRole.UserRole)
        
        # 와일드카드 생성 도구에 아이템명 적용
        item_text = item.text(0)
        # 아이콘 제거 (📄, 📁 등)
        if item_text.startswith('📄'):
            item_name = item_text[2:].strip()
            # 파일 개수 정보 제거 (예: "file.txt (10)")
            if '(' in item_name:
                item_name = item_name.split('(')[0].strip()
            # .txt 확장자 제거
            if item_name.endswith('.txt'):
                item_name = item_name[:-4]
            
            # 서브폴더 경로 포함 여부 확인
            if file_path:
                # wildcards 디렉토리로부터의 상대 경로 계산
                relative_path = os.path.relpath(file_path, self.wildcard_manager.wildcards_dir)
                # 경로 구분자를 '/'로 통일
                relative_path = relative_path.replace('\\', '/')
                
                # 서브디렉토리가 있는 경우 디렉토리 경로 포함
                if '/' in relative_path:
                    # 예: "subfolder/item.txt" -> "subfolder/item"
                    dir_parts = relative_path.rsplit('/', 1)[0]
                    item_name = f"{dir_parts}/{item_name}"
            
            # 각 탭의 입력 필드 업데이트 (필드가 존재하는지 먼저 확인)
            if hasattr(self, 'normal_name_input'):
                self.normal_name_input.setText(item_name)
            if hasattr(self, 'sequential_name_input'):
                self.sequential_name_input.setText(item_name)
            
            # 종속 탭: 마지막으로 선택한 입력 필드에 적용
            if hasattr(self, 'last_selected_dependent_input') and self.last_selected_dependent_input:
                self.last_selected_dependent_input.setText(item_name)
        
        if file_path and os.path.isfile(file_path):
            # 수정사항이 있으면 저장 여부 확인
            if self.is_modified:
                reply = QMessageBox.question(
                    self, "저장 확인",
                    "수정사항이 있습니다. 저장하시겠습니까?",
                    QMessageBox.StandardButton.Yes |
                    QMessageBox.StandardButton.No |
                    QMessageBox.StandardButton.Cancel
                )
                
                if reply == QMessageBox.StandardButton.Yes:
                    self.save_current_file()
                elif reply == QMessageBox.StandardButton.Cancel:
                    return
                    
            self.load_file(file_path)
            
            # 검색어가 있으면 파일 내용에서 자동으로 찾아서 하이라이트
            search_text = self.search_input.text().strip()
            if search_text:
                self.highlight_search_in_content(search_text)
            
    def load_file(self, file_path: str):
        """파일 로드"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                
            self.current_file_path = file_path
            self.original_content = content
            self.content_edit.setText(content)
            self.is_modified = False
            self.is_edit_mode = False  # 편집 모드 해제
            
            # 파일 경로 표시
            relative_path = os.path.relpath(file_path, self.wildcard_manager.wildcards_dir)
            self.file_path_label.setText(f"📄 {relative_path}")
            
            # 텍스트 에디터를 읽기 전용으로 설정
            self.content_edit.setReadOnly(True)
            
            # 버튼 상태 업데이트
            self.save_btn.setEnabled(False)
            self.edit_toggle_btn.setEnabled(True)  # 수정 버튼 활성화
            self.edit_toggle_btn.setText("✏️ 수정")
            self.delete_btn.setEnabled(True)
            
            # 상태 표시
            line_count = len([line for line in content.split('\n') if line.strip()])
            self.statusBar().showMessage(f"파일 로드됨: {line_count}개 항목")
            
        except Exception as e:
            QMessageBox.critical(self, "오류", f"파일 로드 실패: {e}")
            
    def on_content_changed(self):
        """내용 변경 감지"""
        # 편집 모드일 때만 변경사항 체크
        if self.is_edit_mode and self.current_file_path and self.content_edit.toPlainText() != self.original_content:
            self.is_modified = True
            self.save_btn.setEnabled(True)
        elif self.is_edit_mode:
            self.is_modified = False
            self.save_btn.setEnabled(False)
            
    def toggle_edit_mode(self):
        """편집 모드 토글"""
        if not self.current_file_path:
            return
            
        if not self.is_edit_mode:
            # 편집 모드 진입
            self.is_edit_mode = True
            self.content_edit.setReadOnly(False)
            self.edit_toggle_btn.setText("❌ 취소")
            self.edit_toggle_btn.setStyleSheet(get_dynamic_styles()['secondary_button'])
            self.statusBar().showMessage("📝 편집 모드")
            
            # 다른 버튼들 비활성화
            self.delete_btn.setEnabled(False)
            
        else:
            # 편집 모드 종료 (취소)
            if self.is_modified:
                reply = QMessageBox.question(
                    self, "변경사항 취소",
                    "수정사항을 취소하시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                
                if reply == QMessageBox.StandardButton.No:
                    return
                    
            # 원본 내용으로 복원
            self.content_edit.setText(self.original_content)
            self.is_modified = False
            self.is_edit_mode = False
            
            # UI 상태 복원
            self.content_edit.setReadOnly(True)
            self.edit_toggle_btn.setText("✏️ 수정")
            self.save_btn.setEnabled(False)
            self.delete_btn.setEnabled(True)
            self.statusBar().showMessage("편집 취소됨")
    
    def save_current_file(self):
        """현재 파일 저장"""
        if not self.current_file_path:
            return
            
        try:
            content = self.content_edit.toPlainText()
            
            with open(self.current_file_path, 'w', encoding='utf-8') as f:
                f.write(content)
                
            self.original_content = content
            self.is_modified = False
            self.is_edit_mode = False  # 편집 모드 종료
            
            # 편집기를 읽기 전용으로 변경
            self.content_edit.setReadOnly(True)
            
            # 버튼 상태 업데이트
            self.save_btn.setEnabled(False)
            self.edit_toggle_btn.setText("✏️ 수정")
            self.delete_btn.setEnabled(True)
            
            # 와일드카드 리로드
            self.wildcard_manager.reload_wildcards()
            self.wildcards_updated.emit()
            
            # 트리 업데이트
            self.load_wildcard_tree()
            
            self.statusBar().showMessage("✅ 저장 완료", 3000)
            
        except Exception as e:
            QMessageBox.critical(self, "오류", f"저장 실패: {e}")
            
    def delete_current_file(self):
        """현재 파일 삭제"""
        if not self.current_file_path:
            return
            
        reply = QMessageBox.question(
            self, "삭제 확인",
            f"정말로 이 파일을 삭제하시겠습니까?\n{os.path.basename(self.current_file_path)}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                os.remove(self.current_file_path)
                
                # UI 초기화
                self.current_file_path = None
                self.content_edit.clear()
                self.file_path_label.setText("선택된 파일 없음")
                self.delete_btn.setEnabled(False)
                
                # 와일드카드 리로드
                self.wildcard_manager.reload_wildcards()
                self.wildcards_updated.emit()
                
                # 트리 업데이트
                self.load_wildcard_tree()
                
                self.statusBar().showMessage("✅ 파일 삭제됨", 3000)
                
            except Exception as e:
                QMessageBox.critical(self, "오류", f"삭제 실패: {e}")
                
    def create_new_file(self):
        """새 파일 생성"""
        # 간단한 입력 다이얼로그 (실제로는 더 복잡한 다이얼로그 필요)
        from PyQt6.QtWidgets import QInputDialog, QLineEdit
        
        dialog = QInputDialog(self)
        dialog.setProperty("autocomplete_ignore", True)
        dialog.setWindowTitle("새 파일")
        dialog.setLabelText("파일 이름 (확장자 없이):")
        dialog.setTextValue("")
        
        # QInputDialog 내부의 QLineEdit를 찾아서 속성 설정
        line_edit = dialog.findChild(QLineEdit)
        if line_edit:
            line_edit.setProperty("autocomplete_ignore", True)
        
        if dialog.exec() == QInputDialog.DialogCode.Accepted:
            file_name = dialog.textValue()
            ok = True
        else:
            file_name = ""
            ok = False
        
        if ok and file_name:
            file_path = os.path.join(self.wildcard_manager.wildcards_dir, f"{file_name}.txt")
            
            if os.path.exists(file_path):
                QMessageBox.warning(self, "경고", "이미 존재하는 파일입니다.")
                return
                
            try:
                # 빈 파일 생성
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write("")
                    
                # 트리 업데이트 및 파일 로드
                self.load_wildcard_tree()
                self.load_file(file_path)
                
                self.statusBar().showMessage(f"✅ 새 파일 생성: {file_name}.txt", 3000)
                
            except Exception as e:
                QMessageBox.critical(self, "오류", f"파일 생성 실패: {e}")
                
    def reload_wildcards(self):
        """와일드카드 새로고침"""
        self.wildcard_manager.reload_wildcards()
        self.load_wildcard_tree()
        self.wildcards_updated.emit()
        self.statusBar().showMessage("✅ 새로고침 완료", 2000)
    
    def create_new_group(self):
        """새 그룹(폴더) 생성"""
        from PyQt6.QtWidgets import QInputDialog, QLineEdit
        
        dialog = QInputDialog(self)
        dialog.setProperty("autocomplete_ignore", True)
        dialog.setWindowTitle("새 그룹")
        dialog.setLabelText("그룹 이름:")
        dialog.setTextValue("")
        
        # QInputDialog 내부의 QLineEdit를 찾아서 속성 설정
        line_edit = dialog.findChild(QLineEdit)
        if line_edit:
            line_edit.setProperty("autocomplete_ignore", True)
        
        if dialog.exec() == QInputDialog.DialogCode.Accepted:
            group_name = dialog.textValue()
            ok = True
        else:
            group_name = ""
            ok = False
        
        if ok and group_name:
            # 유효한 폴더 이름인지 확인
            invalid_chars = '<>:"|?*'
            if any(char in group_name for char in invalid_chars):
                QMessageBox.warning(self, "경고", f"폴더 이름에 사용할 수 없는 문자가 포함되어 있습니다: {invalid_chars}")
                return
            
            group_path = os.path.join(self.wildcard_manager.wildcards_dir, group_name)
            
            if os.path.exists(group_path):
                QMessageBox.warning(self, "경고", "이미 존재하는 그룹입니다.")
                return
                
            try:
                # 폴더 생성
                os.makedirs(group_path)
                
                # 트리 업데이트
                self.load_wildcard_tree()
                
                self.statusBar().showMessage(f"✅ 새 그룹 생성: {group_name}", 3000)
                
            except Exception as e:
                QMessageBox.critical(self, "오류", f"그룹 생성 실패: {e}")
    
    def open_wildcards_folder(self):
        """wildcards 폴더를 파일 탐색기에서 엽니다"""
        try:
            wildcards_dir = self.wildcard_manager.wildcards_dir
            
            # 폴더가 존재하지 않으면 생성
            if not os.path.exists(wildcards_dir):
                os.makedirs(wildcards_dir)
            
            # 운영체제별로 폴더 열기 명령어 실행
            system = platform.system()
            if system == "Windows":
                os.startfile(wildcards_dir)
            elif system == "Darwin":  # macOS
                subprocess.run(["open", wildcards_dir])
            else:  # Linux
                subprocess.run(["xdg-open", wildcards_dir])
                
            self.statusBar().showMessage("📁 wildcards 폴더를 열었습니다", 2000)
                
        except Exception as e:
            QMessageBox.critical(self, "오류", f"폴더 열기 실패: {e}")
        
        
    def create_normal_tab(self) -> QWidget:
        """일반 탭 생성"""
        tab_widget = QWidget()
        layout = QVBoxLayout(tab_widget)
        layout.setSpacing(get_scaled_size(10))
        
        # 동적 스타일 한 번만 가져오기
        dynamic_styles = get_dynamic_styles()
        
        # 이름 입력
        name_layout = QHBoxLayout()
        name_label = QLabel("이름:")
        name_label.setStyleSheet(dynamic_styles['label_style'])
        name_label.setFixedWidth(get_scaled_size(50))
        name_layout.addWidget(name_label)
        
        self.normal_name_input = QLineEdit()
        self.normal_name_input.setStyleSheet(dynamic_styles['compact_lineedit'])
        self.normal_name_input.setPlaceholderText("선택된 항목 없음")
        # 현재 탭에 따라 프리뷰만 갱신되도록 단일 가드 핸들러로 연결
        self.normal_name_input.textChanged.connect(self.update_preview_guarded)
        name_layout.addWidget(self.normal_name_input)
        
        layout.addLayout(name_layout)
        layout.addStretch()
        
        return tab_widget
    
    def create_sequential_tab(self) -> QWidget:
        """순차 탭 생성"""
        tab_widget = QWidget()
        layout = QVBoxLayout(tab_widget)
        layout.setSpacing(get_scaled_size(10))
        
        # 동적 스타일 한 번만 가져오기
        dynamic_styles = get_dynamic_styles()
        
        # 이름 입력
        name_layout = QHBoxLayout()
        name_label = QLabel("이름:")
        name_label.setStyleSheet(dynamic_styles['label_style'])
        name_label.setFixedWidth(get_scaled_size(50))
        name_layout.addWidget(name_label)
        
        self.sequential_name_input = QLineEdit()
        self.sequential_name_input.setStyleSheet(dynamic_styles['compact_lineedit'])
        self.sequential_name_input.setPlaceholderText("선택된 항목 없음")
        # 현재 탭에 따라 프리뷰만 갱신되도록 단일 가드 핸들러로 연결
        self.sequential_name_input.textChanged.connect(self.update_preview_guarded)
        name_layout.addWidget(self.sequential_name_input)
        
        layout.addLayout(name_layout)
        layout.addStretch()
        
        return tab_widget
    
    def create_dependent_tab(self) -> QWidget:
        """종속 탭 생성"""
        tab_widget = QWidget()
        layout = QVBoxLayout(tab_widget)
        layout.setSpacing(get_scaled_size(10))
        
        # 동적 스타일 한 번만 가져오기
        dynamic_styles = get_dynamic_styles()
        
        # Master 입력
        master_layout = QHBoxLayout()
        master_label = QLabel("Master:")
        master_label.setStyleSheet(dynamic_styles['label_style'])
        master_label.setFixedWidth(get_scaled_size(50))
        master_layout.addWidget(master_label)
        
        self.master_name_input = QLineEdit()
        self.master_name_input.setStyleSheet(dynamic_styles['compact_lineedit'])
        self.master_name_input.setPlaceholderText("Master 와일드카드")
        # 현재 탭에 따라 프리뷰만 갱신되도록 단일 가드 핸들러로 연결
        self.master_name_input.textChanged.connect(self.update_preview_guarded)
        master_layout.addWidget(self.master_name_input)
        
        layout.addLayout(master_layout)
        
        # Slave 입력
        slave_layout = QHBoxLayout()
        slave_label = QLabel("Slave:")
        slave_label.setStyleSheet(dynamic_styles['label_style'])
        slave_label.setFixedWidth(get_scaled_size(50))
        slave_layout.addWidget(slave_label)
        
        self.slave_name_input = QLineEdit()
        self.slave_name_input.setStyleSheet(dynamic_styles['compact_lineedit'])
        self.slave_name_input.setPlaceholderText("Slave 와일드카드")
        # 현재 탭에 따라 프리뷰만 갱신되도록 단일 가드 핸들러로 연결
        self.slave_name_input.textChanged.connect(self.update_preview_guarded)
        slave_layout.addWidget(self.slave_name_input)
        
        layout.addLayout(slave_layout)
        
        # 마지막 선택 입력필드 추적을 위한 변수 (이미 __init__에서 초기화됨)
        if not self.last_selected_dependent_input:
            self.last_selected_dependent_input = self.master_name_input
        
        # 포커스 이벤트 연결
        self.master_name_input.focusInEvent = lambda e: self._on_dependent_focus(self.master_name_input, e)
        self.slave_name_input.focusInEvent = lambda e: self._on_dependent_focus(self.slave_name_input, e)
        
        layout.addStretch()
        
        return tab_widget
    
    def _on_dependent_focus(self, widget: QLineEdit, event):
        """종속 탭 입력 필드 포커스 이벤트"""
        self.last_selected_dependent_input = widget
        QLineEdit.focusInEvent(widget, event)
    
    def update_normal_preview(self):
        """일반 탭 미리보기 업데이트"""
        name = self.normal_name_input.text().strip()
        if name:
            self.preview_edit.setText(f"__{name}__")
        else:
            self.preview_edit.clear()
    
    def update_sequential_preview(self):
        """순차 탭 미리보기 업데이트"""
        name = self.sequential_name_input.text().strip()
        if name:
            self.preview_edit.setText(f"__*{name}__")
        else:
            self.preview_edit.clear()
    
    def update_dependent_preview(self):
        """종속 탭 미리보기 업데이트"""
        master = self.master_name_input.text().strip()
        slave = self.slave_name_input.text().strip()
        
        if master and slave:
            self.preview_edit.setText(f"__*{master}__, __${master}:{slave}__")
        elif master:
            self.preview_edit.setText(f"__*{master}__")
        else:
            self.preview_edit.clear()
    
    def copy_preview(self):
        """미리보기 복사"""
        preview_text = self.preview_edit.toPlainText()
        if preview_text:
            from PyQt6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            clipboard.setText(preview_text)
            self.statusBar().showMessage("✅ 클립보드에 복사됨", 2000)
            
    def clear_search(self):
        """검색어 초기화"""
        self.search_input.clear()
        self.filter_tree("")  # 모든 항목 표시
        self.search_results_edit.clear()  # 검색 결과도 초기화
        self.search_results_edit.setPlaceholderText("검색어를 입력하면 현재 파일에서 매칭되는 라인들이 표시됩니다")
        self.statusBar().showMessage("검색어가 초기화되었습니다", 2000)
    
    def highlight_search_in_content(self, search_text: str):
        """컨텐츠 에디터에서 검색어를 찾아 하이라이트하고 검색 결과 표시"""
        if not search_text or not self.content_edit.toPlainText():
            # 검색어가 없으면 검색 결과 초기화
            if not search_text:
                self.search_results_edit.clear()
                self.search_results_edit.setPlaceholderText("검색어를 입력하면 현재 파일에서 매칭되는 라인들이 표시됩니다")
            return
            
        # 먼저 모든 선택 해제
        cursor = self.content_edit.textCursor()
        cursor.clearSelection()
        self.content_edit.setTextCursor(cursor)
        
        # 텍스트에서 검색어 찾기 (대소문자 구분 없이)
        content = self.content_edit.toPlainText()
        search_lower = search_text.lower()
        content_lower = content.lower()
        
        # 첫 번째 매치 찾기 (컨텐츠 에디터 하이라이트용)
        start_pos = content_lower.find(search_lower)
        
        if start_pos != -1:
            # 커서를 찾은 위치로 이동
            cursor = self.content_edit.textCursor()
            cursor.setPosition(start_pos)
            cursor.setPosition(start_pos + len(search_text), QTextCursor.MoveMode.KeepAnchor)
            
            # 선택된 텍스트 하이라이트
            self.content_edit.setTextCursor(cursor)
            
            # 선택된 텍스트가 보이도록 스크롤
            self.content_edit.ensureCursorVisible()
        
        # 모든 매칭 라인 찾기 (검색 결과 표시용)
        lines = content.split('\n')
        matching_lines = []
        match_count = 0
        
        for line in lines:
            line_stripped = line.strip()
            if line_stripped and search_lower in line_stripped.lower():
                matching_lines.append(line_stripped)
                match_count += line_stripped.lower().count(search_lower)
        
        # 검색 결과 표시
        if matching_lines:
            self.search_results_edit.clear()
            self.search_results_edit.setText('\n'.join(matching_lines))
            
            # 상태바에 메시지 표시
            if len(matching_lines) > 1:
                self.statusBar().showMessage(f"'{search_text}' 찾음 (총 {len(matching_lines)}개 라인, {match_count}회 등장)", 3000)
            else:
                self.statusBar().showMessage(f"'{search_text}' 찾음 (1개 라인)", 3000)
        else:
            self.search_results_edit.clear()
            self.search_results_edit.setPlaceholderText(f"'{search_text}'와 일치하는 라인이 없습니다")
            self.statusBar().showMessage(f"'{search_text}' 찾을 수 없음", 3000)
    
    def update_preview_guarded(self, *args):
        """현재 선택된 탭의 규칙에 맞는 미리보기 함수만 실행"""
        try:
            idx = self.generator_tabs.currentIndex()
        except Exception:
            idx = 0
        if idx == getattr(self, '_gen_tab_index', {'normal': 0}).get('normal', 0):
            self.update_normal_preview()
        elif idx == getattr(self, '_gen_tab_index', {'sequential': 1}).get('sequential', 1):
            self.update_sequential_preview()
        elif idx == getattr(self, '_gen_tab_index', {'dependent': 2}).get('dependent', 2):
            self.update_dependent_preview()

    def refresh_current_preview(self, *args):
        """탭 변경 시 현재 탭의 입력값으로 미리보기 재생성"""
        self.update_preview_guarded()

    def closeEvent(self, event):
        """창 닫기 이벤트"""
        # 편집 모드에서 창을 닫으려 할 때
        if self.is_edit_mode and self.is_modified:
            reply = QMessageBox.question(
                self, "저장 확인",
                "편집 중인 내용이 있습니다. 저장하시겠습니까?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No |
                QMessageBox.StandardButton.Cancel
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.save_current_file()
                event.accept()
            elif reply == QMessageBox.StandardButton.No:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
