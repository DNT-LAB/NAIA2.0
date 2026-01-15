"""
E621 이벤트 모듈
e621_sample.parquet 파일을 핸들링하여 태그 이벤트를 관리하는 모듈
"""

import os
import json
import random
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QAbstractItemView, QLineEdit, QCheckBox,
    QDialog, QDialogButtonBox, QListWidget, QListWidgetItem,
    QRadioButton, QButtonGroup
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QFont

from interfaces.base_module import BaseMiddleModule
from ui.theme import DARK_STYLES, DARK_COLORS, get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.modern_menu import setModernStyle


class E621EventSignals(QObject):
    """E621 이벤트 시그널 클래스"""
    event_selected = pyqtSignal(str, str, str)  # key, value0, value1 (모두 str)
    generation_requested = pyqtSignal(dict)  # generation parameters


class E621EventModule(BaseMiddleModule):
    """E621 이벤트 관리 모듈"""
    
    def __init__(self):
        super().__init__()
        self.signals = E621EventSignals()
        self.widget = None
        self.app_context = None
        
        # 데이터 관련
        self.parquet_path = Path("data/e621_sample.parquet")
        self.deleted_path = Path("save/e621_event/deleted.json")
        self.starred_path = Path("save/e621_event/starred.json")  # 즐겨찾기 파일 경로
        self.settings_path = Path("save/e621_module.json")  # 설정 파일 경로
        self.event_dict = {}  # {key: (value0, value1)} - 튜플로 저장
        self.deleted_keys = set()  # 삭제된 키 목록
        self.starred_keys = set()  # 즐겨찾기 키 목록
        self.current_keys = []  # 전체 키 목록 (원본 순서 유지)
        self.filtered_keys = []  # 검색 결과 키 목록
        self.is_searching = False  # 검색 상태 플래그
        self.visible_rows = 7  # 한번에 보이는 행 수
        
        # UI 컴포넌트
        self.table_widget = None
        self.value1_edit = None
        self.auto_hide_edit = None
        self.disable_auto_emphasis_checkbox = None  # 자동 강조처리 해제 체크박스
        self.next_button = None
        self.generate_button = None
        self.star_button = None
        self.manage_button = None
        self.hide_button = None
        self.search_input = None
        self.search_button = None
        self.reset_button = None
        self.view_mode_group = None  # 라디오버튼 그룹
        self.radio_default = None  # 기본 보기
        self.radio_starred = None  # 즐겨찾기 보기
        
        # 파일 로드 상태
        self.is_loaded = False
        
        # 자동 분리 설정 (일단 비활성화)
        self.auto_detach = False  # 펼칠 때 자동으로 외부 창으로 분리
        self.is_first_toggle = True  # 첫 번째 토글 여부
        
    def get_title(self) -> str:
        return "🎯 E621 연구용 모듈"
    
    def get_order(self) -> int:
        return 82  # 인스턴트 와일드카드 근처
    
    def initialize_with_context(self, context):
        """AppContext 주입"""
        self.app_context = context
    
    def on_initialize(self):
        """모듈 초기화 시 호출되는 메서드"""
        super().on_initialize()
        
        # 초기화 시점에는 controller가 없을 수 있으므로 나중에 시도
        QTimer.singleShot(1000, self.delayed_setup)
    
    def create_widget(self, parent=None) -> QWidget:
        if self.widget:
            return self.widget
        
        self.widget = QWidget(parent)
        content_layout = QVBoxLayout(self.widget)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(get_scaled_size(8))
        
        # 파일 로드 (자동 분리되지 않은 경우를 위해)
        if not self.is_loaded:
            QTimer.singleShot(100, self.load_parquet_file)
        
        # Line1: 이벤트 리스트 라벨 + 라디오버튼
        header_layout = QHBoxLayout()
        header_layout.setSpacing(get_scaled_size(16))

        event_label = QLabel("이벤트 리스트:")
        event_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(18)}px;
            font-weight: bold;
            color: {DARK_COLORS['text_primary']};
        """)
        header_layout.addWidget(event_label)

        # 라디오버튼 스타일
        radio_style = f"""
            QRadioButton {{
                font-size: {get_scaled_font_size(14)}px;
                color: {DARK_COLORS['text_primary']};
                spacing: {get_scaled_size(4)}px;
            }}
            QRadioButton::indicator {{
                width: {get_scaled_size(16)}px;
                height: {get_scaled_size(16)}px;
            }}
        """

        # 라디오버튼 그룹
        self.view_mode_group = QButtonGroup(self.widget)

        # 기본 보기 라디오버튼
        self.radio_default = QRadioButton("기본 보기")
        self.radio_default.setStyleSheet(radio_style)
        self.radio_default.setChecked(True)
        self.radio_default.toggled.connect(self.on_view_mode_changed)
        self.view_mode_group.addButton(self.radio_default, 0)
        header_layout.addWidget(self.radio_default)

        # 즐겨찾기 보기 라디오버튼
        self.radio_starred = QRadioButton("즐겨찾기 보기")
        self.radio_starred.setStyleSheet(radio_style)
        self.radio_starred.toggled.connect(self.on_view_mode_changed)
        self.view_mode_group.addButton(self.radio_starred, 1)
        header_layout.addWidget(self.radio_starred)

        header_layout.addStretch()
        content_layout.addLayout(header_layout)
        
        # Line2: 검색 영역
        search_layout = QHBoxLayout()
        search_layout.setSpacing(get_scaled_size(8))
        
        # 검색 입력 필드
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("검색어 입력 (key → value[0] → value[1] 순서로 검색)")
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                padding: {get_scaled_size(5)}px;
                font-size: {get_scaled_font_size(16)}px;
            }}
        """)
        self.search_input.returnPressed.connect(self.on_search_clicked)
        self.search_input.setProperty("autocomplete_ignore", True)
        search_layout.addWidget(self.search_input)
        
        # 검색 버튼
        self.search_button = QPushButton("검색")
        self.search_button.setFixedWidth(get_scaled_size(80))
        self.search_button.setStyleSheet(get_dynamic_styles()['secondary_button'])
        self.search_button.clicked.connect(self.on_search_clicked)
        search_layout.addWidget(self.search_button)
        
        # 초기화 버튼
        self.reset_button = QPushButton("초기화")
        self.reset_button.setFixedWidth(get_scaled_size(100))
        self.reset_button.setStyleSheet(get_dynamic_styles()['secondary_button'])
        self.reset_button.clicked.connect(self.on_reset_clicked)
        search_layout.addWidget(self.reset_button)
        
        content_layout.addLayout(search_layout)
        
        # Line3: 테이블과 버튼 영역을 담을 수평 레이아웃
        table_button_layout = QHBoxLayout()
        table_button_layout.setSpacing(get_scaled_size(8))
        
        # Line3_left: Table (가로 2컬럼)
        self.table_widget = QTableWidget()
        self.table_widget.setColumnCount(2)
        self.table_widget.setHorizontalHeaderLabels(["Key", "Value"])
        self.table_widget.setAlternatingRowColors(True)
        self.table_widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        
        # 마우스 추적 비활성화 (호버 이벤트 제거)
        self.table_widget.setMouseTracking(False)
        
        # 스크롤 모드 설정
        self.table_widget.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        
        # 스크롤바 정책 명시적 설정
        self.table_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.table_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        # 행 높이 설정
        self.table_widget.verticalHeader().setDefaultSectionSize(get_scaled_size(30))
        
        # 테이블 높이를 정확히 7개 행이 보이도록 설정
        row_height = get_scaled_size(30)  # 각 행의 높이
        header_height = get_scaled_size(40)  # 헤더 높이 (여유있게)
        # 7개 행 + 헤더 + 스크롤바 공간
        total_height = header_height + (row_height * self.visible_rows) + get_scaled_size(25)
        
        # 테이블 전체 높이 고정
        self.table_widget.setMinimumHeight(total_height)
        self.table_widget.setMaximumHeight(total_height)
        
        # 테이블 크기 정책 설정
        from PyQt6.QtWidgets import QSizePolicy
        self.table_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        # 테이블 스타일 설정
        dynamic_styles = get_dynamic_styles()
        self.table_widget.setStyleSheet(f"""
            QTableWidget {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                font-size: {get_scaled_font_size(18)}px;
            }}
            QTableWidget::item {{
                padding: {get_scaled_size(4)}px;
            }}
            QTableWidget::item:selected {{
                background-color: {DARK_COLORS['highlight']};
            }}
            QTableWidget::item:hover {{
                background-color: transparent;
            }}
            QHeaderView::section {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                padding: {get_scaled_size(5)}px;
                border: 1px solid {DARK_COLORS['border']};
                font-size: {get_scaled_font_size(18)}px;
                font-weight: bold;
            }}
            QScrollBar:vertical {{
                background-color: {DARK_COLORS['bg_tertiary']};
                width: {get_scaled_size(14)}px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background-color: #CCCCCC;
                min-height: {get_scaled_size(30)}px;
                border-radius: {get_scaled_size(4)}px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: #FFFFFF;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """)
        
        # 컬럼 너비 조정 - 가로 스크롤 방지
        header = self.table_widget.horizontalHeader()
        header.setStretchLastSection(True)  # Value 컬럼이 남은 공간 차지
        self.table_widget.setColumnWidth(0, get_scaled_size(150))  # Key 컬럼 고정 너비
        
        # 세로 헤더 숨기기 (행 번호 표시 제거)
        self.table_widget.verticalHeader().setVisible(False)
        
        # 테이블 선택 이벤트 연결
        self.table_widget.itemSelectionChanged.connect(self.on_table_selection_changed)
        
        # 테이블을 레이아웃에 추가
        table_button_layout.addWidget(self.table_widget)
        
        # Line3_right: 버튼 배치 영역 (고정 너비)
        button_widget = QWidget()
        button_widget.setFixedWidth(get_scaled_size(110))  # 버튼 영역 고정 너비 (100 + 여백)
        button_layout = QVBoxLayout(button_widget)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(get_scaled_size(8))
        
        # 다음 버튼
        self.next_button = QPushButton("다음")
        self.next_button.setFixedHeight(get_scaled_size(100))
        self.next_button.setStyleSheet(dynamic_styles['secondary_button'])
        self.next_button.clicked.connect(self.on_next_clicked)
        button_layout.addWidget(self.next_button)
        
        # 생성 버튼
        self.generate_button = QPushButton("생성")
        self.generate_button.setFixedHeight(get_scaled_size(100))
        self.generate_button.setStyleSheet(dynamic_styles['primary_button'])
        self.generate_button.clicked.connect(self.on_generate_clicked)
        button_layout.addWidget(self.generate_button)

        # 스타(즐겨찾기) 버튼
        self.star_button = QPushButton("☆")
        self.star_button.setFixedHeight(get_scaled_size(40))
        self.star_button.setStyleSheet(dynamic_styles['secondary_button'])
        self.star_button.clicked.connect(self.on_star_clicked)
        self.star_button.setToolTip("선택한 항목을 즐겨찾기에 추가/해제")
        button_layout.addWidget(self.star_button)

        # 생성 버튼과 숨김 버튼 사이에 stretch 추가 (실수로 숨김 버튼 누르는 것 방지)
        button_layout.addStretch()

        # 관리 버튼 (숨긴 항목 복원)
        self.manage_button = QPushButton("관리")
        self.manage_button.setFixedHeight(get_scaled_size(40))
        self.manage_button.setStyleSheet(dynamic_styles['secondary_button'])
        self.manage_button.clicked.connect(self.on_manage_clicked)
        button_layout.addWidget(self.manage_button)

        # 숨김 버튼
        self.hide_button = QPushButton("숨김")
        self.hide_button.setFixedHeight(get_scaled_size(40))
        self.hide_button.setStyleSheet(dynamic_styles['secondary_button'])
        self.hide_button.clicked.connect(self.on_hide_clicked)
        button_layout.addWidget(self.hide_button)
        
        # 버튼 위젯을 레이아웃에 추가
        table_button_layout.addWidget(button_widget)
        
        # 전체 레이아웃에 추가
        content_layout.addLayout(table_button_layout)
        
        # Line4: value[1] 편집 가능한 텍스트박스
        value1_label = QLabel("태그 값:")
        value1_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(16)}px;
            color: {DARK_COLORS['text_primary']};
        """)
        content_layout.addWidget(value1_label)
        
        self.value1_edit = QTextEdit()
        self.value1_edit.setAcceptRichText(False)  # 서식 붙여넣기 차단
        self.value1_edit.setMinimumHeight(get_scaled_size(100))
        self.value1_edit.setMaximumHeight(get_scaled_size(150))
        self.value1_edit.setStyleSheet(dynamic_styles['compact_textedit'])
        self.value1_edit.setPlaceholderText("선택된 이벤트의 태그가 여기에 표시됩니다...")
        setModernStyle(self.value1_edit)  # 모던 컨텍스트 메뉴 스타일 적용
        content_layout.addWidget(self.value1_edit)
        
        # Line5: 자동 숨김처리 태그 라벨
        auto_hide_label = QLabel("자동 숨김처리 태그:")
        auto_hide_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(16)}px;
            color: {DARK_COLORS['text_primary']};
        """)
        content_layout.addWidget(auto_hide_label)
        
        # Line6: 자동 숨김처리 태그 텍스트박스
        self.auto_hide_edit = QTextEdit()
        self.auto_hide_edit.setAcceptRichText(False)  # 서식 붙여넣기 차단
        self.auto_hide_edit.setMinimumHeight(get_scaled_size(60))
        self.auto_hide_edit.setMaximumHeight(get_scaled_size(100))
        self.auto_hide_edit.setStyleSheet(dynamic_styles['compact_textedit'])
        self.auto_hide_edit.setPlaceholderText("자동으로 숨김 처리할 태그를 입력하세요...")
        setModernStyle(self.auto_hide_edit)  # 모던 컨텍스트 메뉴 스타일 적용
        content_layout.addWidget(self.auto_hide_edit)
        
        # Line7: 자동 강조처리 적용 해제 체크박스
        self.disable_auto_emphasis_checkbox = QCheckBox("자동 강조처리 적용 해제")
        self.disable_auto_emphasis_checkbox.setStyleSheet(f"""
            QCheckBox {{
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_primary']};
                spacing: 5px;
            }}
            QCheckBox::indicator {{
                width: {get_scaled_size(20)}px;
                height: {get_scaled_size(20)}px;
            }}
        """)
        content_layout.addWidget(self.disable_auto_emphasis_checkbox)
        
        # 설정 로드 (자동 숨김 태그, 체크박스 상태)
        self.load_settings()
        
        return self.widget
    
    def load_parquet_file(self):
        """Parquet 파일 로드 및 딕셔너리 생성"""
        if self.is_loaded:
            return
        
        try:
            # pandas import (필요시에만)
            import pandas as pd
            
            # 삭제된 키 목록 로드
            self.load_deleted_keys()

            # 즐겨찾기 키 목록 로드
            self.load_starred_keys()

            # Parquet 파일 읽기
            if not self.parquet_path.exists():
                QMessageBox.warning(
                    self.widget,
                    "경고",
                    f"파일을 찾을 수 없습니다: {self.parquet_path}"
                )
                return
            
            df = pd.read_parquet(self.parquet_path)
            
            # 딕셔너리 생성 (column 0: key, column 1,2: value)
            self.event_dict.clear()
            self.current_keys.clear()
            
            for idx, row in df.iterrows():
                key = str(row.iloc[0])  # column 0 - 영어 태그
                value0 = str(row.iloc[1])  # column 1 - 한국어 번역
                value1 = str(row.iloc[2])  # column 2 - 관련 태그들
                
                # 삭제된 키는 제외
                if key not in self.deleted_keys:
                    self.event_dict[key] = (value0, value1)  # 튜플로 저장
                    self.current_keys.append(key)  # 원본 순서 유지
            
            # 테이블 업데이트
            self.update_table()
            
            self.is_loaded = True
            print(f"[OK] E621 이벤트 로드 완료: {len(self.event_dict)}개 항목")
            
        except ImportError:
            QMessageBox.critical(
                self.widget,
                "오류",
                "pandas 라이브러리가 필요합니다.\npip install pandas pyarrow"
            )
        except Exception as e:
            QMessageBox.critical(
                self.widget,
                "오류",
                f"파일 로드 중 오류 발생:\n{str(e)}"
            )
    
    def load_deleted_keys(self):
        """삭제된 키 목록 로드"""
        self.deleted_keys.clear()
        
        if self.deleted_path.exists():
            try:
                with open(self.deleted_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.deleted_keys = set(data.get('deleted_keys', []))
                    print(f"[OK] 삭제된 키 {len(self.deleted_keys)}개 로드")
            except Exception as e:
                print(f"[ERROR] 삭제 목록 로드 실패: {e}")
    
    def save_deleted_keys(self):
        """삭제된 키 목록 저장"""
        try:
            # 디렉토리 생성
            self.deleted_path.parent.mkdir(parents=True, exist_ok=True)

            # JSON 파일로 저장
            with open(self.deleted_path, 'w', encoding='utf-8') as f:
                json.dump({'deleted_keys': list(self.deleted_keys)}, f, ensure_ascii=False, indent=2)
            print(f"[OK] 삭제 목록 저장: {len(self.deleted_keys)}개")
        except Exception as e:
            print(f"[ERROR] 삭제 목록 저장 실패: {e}")

    def load_starred_keys(self):
        """즐겨찾기 키 목록 로드"""
        self.starred_keys.clear()

        if self.starred_path.exists():
            try:
                with open(self.starred_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.starred_keys = set(data.get('starred_keys', []))
                    print(f"[OK] 즐겨찾기 키 {len(self.starred_keys)}개 로드")
            except Exception as e:
                print(f"[ERROR] 즐겨찾기 목록 로드 실패: {e}")

    def save_starred_keys(self):
        """즐겨찾기 키 목록 저장"""
        try:
            # 디렉토리 생성
            self.starred_path.parent.mkdir(parents=True, exist_ok=True)

            # JSON 파일로 저장
            with open(self.starred_path, 'w', encoding='utf-8') as f:
                json.dump({'starred_keys': list(self.starred_keys)}, f, ensure_ascii=False, indent=2)
            print(f"[OK] 즐겨찾기 목록 저장: {len(self.starred_keys)}개")
        except Exception as e:
            print(f"[ERROR] 즐겨찾기 목록 저장 실패: {e}")
    
    def save_settings(self):
        """모듈 설정 저장 (자동 숨김 태그, 자동 강조처리 해제 여부)"""
        try:
            settings = {
                'auto_hide_tags': self.auto_hide_edit.toPlainText() if self.auto_hide_edit else '',
                'disable_auto_emphasis': self.disable_auto_emphasis_checkbox.isChecked() if self.disable_auto_emphasis_checkbox else False
            }
            
            # save 디렉토리 생성
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            
            # JSON 파일로 저장
            with open(self.settings_path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
            print(f"[OK] E621 모듈 설정 저장: {self.settings_path}")
        except Exception as e:
            print(f"[ERROR] E621 모듈 설정 저장 실패: {e}")
    
    def load_settings(self):
        """모듈 설정 로드"""
        try:
            if self.settings_path.exists():
                with open(self.settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                
                # 자동 숨김 태그 설정
                if self.auto_hide_edit and 'auto_hide_tags' in settings:
                    self.auto_hide_edit.setPlainText(settings['auto_hide_tags'])
                
                # 자동 강조처리 해제 체크박스 설정
                if self.disable_auto_emphasis_checkbox and 'disable_auto_emphasis' in settings:
                    self.disable_auto_emphasis_checkbox.setChecked(settings['disable_auto_emphasis'])
                
                print(f"[OK] E621 모듈 설정 로드: {self.settings_path}")
        except Exception as e:
            print(f"[ERROR] E621 모듈 설정 로드 실패: {e}")
    
    def update_table(self):
        """테이블 위젯 업데이트 - 검색 상태 및 보기 모드에 따라 표시"""
        # 표시할 키 목록 결정
        if self.is_searching:
            display_keys = self.filtered_keys
        else:
            display_keys = self.current_keys

        # 즐겨찾기 보기 모드인 경우 필터링
        if self.radio_starred and self.radio_starred.isChecked():
            display_keys = [key for key in display_keys if key in self.starred_keys]

        if not display_keys:
            self.table_widget.setRowCount(0)
            return
        
        # 전체 행 수만큼 테이블 설정
        total_rows = len(display_keys)
        self.table_widget.setRowCount(total_rows)
        
        # 즐겨찾기 항목 색상 (노랑색)
        from PyQt6.QtGui import QColor, QBrush
        starred_color = QBrush(QColor("#FFD700"))  # Gold - 노랑색

        # 모든 아이템 채우기
        for i, key in enumerate(display_keys):
            # 키가 딕셔너리에 없으면 건너뛰기 (삭제된 경우)
            if key not in self.event_dict:
                continue
            value0, value1 = self.event_dict[key]  # 튜플 언패킹

            # 즐겨찾기 여부 확인
            is_starred = key in self.starred_keys

            # Key 컬럼
            key_item = QTableWidgetItem(key)
            key_item.setFlags(key_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if is_starred:
                key_item.setForeground(starred_color)
            self.table_widget.setItem(i, 0, key_item)

            # Value 컬럼 (value0 - 한국어 번역)
            value_item = QTableWidgetItem(value0)
            value_item.setFlags(value_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if is_starred:
                value_item.setForeground(starred_color)
            self.table_widget.setItem(i, 1, value_item)
        
        # 테이블 업데이트 강제 적용
        self.table_widget.update()
        self.table_widget.viewport().update()
        
        # 스크롤바 강제 표시 및 디버깅
        from PyQt6.QtWidgets import QScrollBar
        scrollbar = self.table_widget.verticalScrollBar()
        if scrollbar:
            scrollbar.setVisible(True)
            print(f"[DEBUG] 스크롤바 범위: 0-{scrollbar.maximum()}, 현재: {scrollbar.value()}, 표시여부: {scrollbar.isVisible()}")
        
        # 버튼 상태 업데이트 - 다음 버튼은 항상 활성화
        self.next_button.setEnabled(True)
        
        print(f"[DEBUG] 테이블 업데이트: {total_rows}개 행, 테이블 높이: {self.table_widget.height()}")
        print(f"[DEBUG] 뷰포트 높이: {self.table_widget.viewport().height()}")
        print(f"[DEBUG] 스크롤바 표시 정책: {self.table_widget.verticalScrollBarPolicy()}")
    
    def process_tags(self, tags_text: str, auto_hide_text: str) -> str:
        """태그 처리 로직
        1. auto_hide_tags와 매칭되는 태그 제거
        2. 자동 강조처리 적용 (체크박스 상태에 따라)
        3. NAI가 아닌 모드에서 괄호 이스케이프 및 강조 구문 변환
        """
        # 태그들을 쉼표로 분리하고 strip
        tags = [tag.strip() for tag in tags_text.split(',') if tag.strip()]
        auto_hide_tags = [tag.strip() for tag in auto_hide_text.split(',') if tag.strip()]
        
        # auto_hide_tags와 매칭되는 태그들을 제거
        filtered_tags = [tag for tag in tags if tag not in auto_hide_tags]
        
        # 다시 join
        result = ', '.join(filtered_tags)
        
        # 자동 강조처리 적용 해제가 체크되어 있으면
        if self.disable_auto_emphasis_checkbox.isChecked():
            # 순서 중요: 2:: 먼저 처리, 그 다음 :: 처리
            result = result.replace("2::", "")
            result = result.replace("::", "")
        
        # NAI 모드가 아닌 경우 추가 처리
        current_mode = getattr(self.app_context, 'current_api_mode', 'NAI')
        if current_mode != 'NAI':
            # 괄호 이스케이프
            result = result.replace("(", r"\(")
            result = result.replace(")", r"\)")
            
            # 자동 강조처리가 해제되지 않았으면 강조 구문 변환
            if not self.disable_auto_emphasis_checkbox.isChecked():
                # 2::를 (로, ::를 :1.3)으로 변환
                result = result.replace("2::", "(")
                result = result.replace("::", ":1.3)")
        
        return result
    
    def on_table_selection_changed(self):
        """테이블 선택이 변경되었을 때"""
        selected_items = self.table_widget.selectedItems()
        if not selected_items:
            return
        
        # 선택된 행의 인덱스
        row = selected_items[0].row()

        # 표시 중인 키 목록 결정
        display_keys = self.get_display_keys()

        # 행 인덱스가 유효한지 확인
        if row >= len(display_keys):
            return

        # 선택된 키와 값 가져오기
        key = display_keys[row]
        value0, value1 = self.event_dict[key]  # 튜플 언패킹
        
        # 자동 강조처리 적용 해제가 체크되어 있으면 처리
        if self.disable_auto_emphasis_checkbox.isChecked():
            # 순서 중요: 2:: 먼저 처리, 그 다음 :: 처리
            value1 = value1.replace("2::", "")
            value1 = value1.replace("::", "")
        
        # value1 (관련 태그들)을 텍스트박스에 표시
        self.value1_edit.setPlainText(value1)

        # 스타 버튼 상태 업데이트
        self.update_star_button_state(key)

        # 시그널 발송
        self.signals.event_selected.emit(key, value0, value1)
    
    def on_next_clicked(self):
        """다음 버튼 클릭 - 현재 선택된 항목으로 instant generation 후 다음 행으로 이동"""
        # 현재 선택된 항목 확인
        selected_items = self.table_widget.selectedItems()
        if not selected_items:
            QMessageBox.information(
                self.widget,
                "알림",
                "생성할 이벤트를 선택해주세요."
            )
            return
        
        # 현재 행 번호 저장
        row = selected_items[0].row()
        display_keys = self.get_display_keys()
        
        # 편집된 value1 가져오기 (현재 텍스트박스의 내용)
        edited_value1 = self.value1_edit.toPlainText()
        
        # 자동 숨김 태그 처리
        auto_hide_tags = self.auto_hide_edit.toPlainText()
        
        # value1 태그 처리
        processed_tags = self.process_tags(edited_value1, auto_hide_tags)
        
        # 생성 파라미터 구성 (web_view.py의 tags_data 구조 사용)
        tags_data = {
            'id': 10000000,  # 항상 고정
            'artist': [],
            'copyright': [],
            'character': [],
            'general': processed_tags.split(', ') if processed_tags else [],  # 처리된 태그들을 general에 넣음
            'meta': []
        }
        
        # instant generation 호출 (있는 경우)
        if hasattr(self.app_context, 'main_window') and hasattr(self.app_context.main_window, 'on_instant_generation_requested'):
            self.app_context.main_window.on_instant_generation_requested(tags_data)
        
        # 한 칸 아래로 이동
        next_row = row + 1
        if next_row < len(display_keys):
            # 다음 행이 있으면 선택하고 스크롤
            self.table_widget.selectRow(next_row)
            self.table_widget.scrollToItem(
                self.table_widget.item(next_row, 0),
                QAbstractItemView.ScrollHint.EnsureVisible
            )
    
    def on_generate_clicked(self):
        """생성 버튼 클릭 - generate with image"""
        selected_items = self.table_widget.selectedItems()
        if not selected_items:
            QMessageBox.information(
                self.widget,
                "알림",
                "생성할 이벤트를 선택해주세요."
            )
            return
        
        # 선택된 항목의 데이터 가져오기
        row = selected_items[0].row()

        # 표시 중인 키 목록 결정
        display_keys = self.get_display_keys()

        if row >= len(display_keys):
            return

        key = display_keys[row]
        value0, value1 = self.event_dict[key]  # 튜플 언패킹

        # 편집된 value1 가져오기
        edited_value1 = self.value1_edit.toPlainText()
        
        # 자동 숨김 태그 처리
        auto_hide_tags = self.auto_hide_edit.toPlainText()
        
        # value1 태그 처리
        processed_tags = self.process_tags(edited_value1, auto_hide_tags)
        
        # 생성 파라미터 구성 (web_view.py의 tags_data 구조 사용)
        tags_data = {
            'id': 10000000,  # 항상 고정
            'artist': [],
            'copyright': [],
            'character': [],
            'general': processed_tags.split(', ') if processed_tags else [],  # 처리된 태그들을 general에 넣음
            'meta': []
        }
        
        # 시그널 발송 (main_controller에서 on_generate_with_image_requested에 연결됨)
        self.signals.generation_requested.emit(tags_data)
        
        # 설정 저장 (자동 숨김 태그, 자동 강조처리 해제 상태)
        self.save_settings()
    
    def on_hide_clicked(self):
        """숨김 버튼 클릭 - 선택된 항목 삭제"""
        selected_items = self.table_widget.selectedItems()
        if not selected_items:
            QMessageBox.information(
                self.widget,
                "알림",
                "숨김 처리할 이벤트를 선택해주세요."
            )
            return
        
        # 선택된 항목의 키 가져오기
        row = selected_items[0].row()

        # 표시 중인 키 목록 결정
        display_keys = self.get_display_keys()

        if row >= len(display_keys):
            return

        key = display_keys[row]

        # 삭제 목록에 추가
        self.deleted_keys.add(key)
        self.save_deleted_keys()
        
        # 딕셔너리에서 제거
        if key in self.event_dict:
            del self.event_dict[key]
        
        # 키 목록에서 제거
        if key in self.current_keys:
            self.current_keys.remove(key)
        
        # 검색 결과 목록에서도 제거
        if key in self.filtered_keys:
            self.filtered_keys.remove(key)
        
        # 테이블 업데이트
        self.update_table()

    def on_star_clicked(self):
        """스타(즐겨찾기) 버튼 클릭 - 선택된 항목 즐겨찾기 토글"""
        selected_items = self.table_widget.selectedItems()
        if not selected_items:
            QMessageBox.information(
                self.widget,
                "알림",
                "즐겨찾기할 이벤트를 선택해주세요."
            )
            return

        # 선택된 항목의 키 가져오기
        row = selected_items[0].row()

        # 표시 중인 키 목록 결정
        display_keys = self.get_display_keys()

        if row >= len(display_keys):
            return

        key = display_keys[row]

        # 즐겨찾기 토글
        if key in self.starred_keys:
            self.starred_keys.discard(key)
            print(f"[OK] 즐겨찾기 해제: {key}")
        else:
            self.starred_keys.add(key)
            print(f"[OK] 즐겨찾기 추가: {key}")

        # 즐겨찾기 저장
        self.save_starred_keys()

        # 스타 버튼 텍스트 업데이트
        self.update_star_button_state(key)

        # 테이블 업데이트 (색상 반영)
        self.update_table()

    def update_star_button_state(self, key: str = None):
        """스타 버튼 상태 업데이트"""
        if key is None:
            # 현재 선택된 항목 확인
            selected_items = self.table_widget.selectedItems()
            if selected_items:
                row = selected_items[0].row()
                display_keys = self.get_display_keys()
                if row < len(display_keys):
                    key = display_keys[row]

        if key and key in self.starred_keys:
            self.star_button.setText("★")
        else:
            self.star_button.setText("☆")

    def on_view_mode_changed(self, checked: bool):
        """보기 모드 라디오버튼 변경 시 호출"""
        # toggled 시그널은 체크된 버튼과 해제된 버튼 모두에서 발생하므로
        # checked가 True인 경우에만 처리
        if checked:
            self.update_table()

    def get_display_keys(self) -> list:
        """현재 보기 모드에 따른 표시 키 목록 반환"""
        if self.is_searching:
            display_keys = self.filtered_keys
        else:
            display_keys = self.current_keys

        # 즐겨찾기 보기 모드인 경우 필터링
        if self.radio_starred and self.radio_starred.isChecked():
            display_keys = [key for key in display_keys if key in self.starred_keys]

        return display_keys

    def delayed_setup(self):
        """지연된 초기화 - MiddleSectionController 찾기"""
        try:
            # app_context에서 직접 가져오기
            if hasattr(self.app_context, 'middle_section_controller'):
                self.middle_controller = self.app_context.middle_section_controller
                print(f"[OK] E621EventModule: app_context에서 middle_controller 찾음")
            else:
                print("[WARNING] E621EventModule: app_context에 middle_section_controller 없음")
                self.middle_controller = None
                    
            if self.middle_controller:
                # 이 모듈의 CollapsibleBox 찾기
                self.setup_auto_detach()
            else:
                print("[WARNING] E621EventModule: MiddleSectionController를 찾을 수 없음")
        except Exception as e:
            print(f"[ERROR] E621EventModule delayed_setup 중 오류: {e}")
            self.middle_controller = None
    
    def setup_auto_detach(self):
        """CollapsibleBox의 토글 이벤트를 가로채서 자동 분리 설정"""
        if not hasattr(self, 'middle_controller') or self.middle_controller is None:
            print("[WARNING] E621EventModule: middle_controller가 없어서 자동 분리 설정 실패")
            return
            
        # module_boxes가 있는지 확인
        if not hasattr(self.middle_controller, 'module_boxes'):
            print("[WARNING] E621EventModule: module_boxes 속성이 없음")
            return
            
        # 이 모듈의 CollapsibleBox 찾기
        module_title = self.get_title()
        if module_title in self.middle_controller.module_boxes:
            box = self.middle_controller.module_boxes[module_title]
            
            # 원래 토글 함수 백업
            original_toggled = box.on_toggled
            
            def auto_detach_toggled(checked):
                """토글 시 자동으로 외부 창으로 분리"""
                if checked and self.is_first_toggle and self.auto_detach:
                    self.is_first_toggle = False
                    # 데이터 로드
                    if not self.is_loaded:
                        QTimer.singleShot(100, self.load_parquet_file)
                    # 외부 창으로 분리 요청
                    QTimer.singleShot(200, lambda: box.request_detach())
                else:
                    # 원래 토글 동작 수행
                    original_toggled(checked)
            
            # 토글 함수 교체
            try:
                box.toggle_button.toggled.disconnect()
            except:
                pass  # 연결된 시그널이 없을 수 있음
            box.toggle_button.toggled.connect(auto_detach_toggled)
            
            print(f"[OK] E621EventModule: 자동 분리 설정 완료")
        else:
            print(f"[WARNING] E621EventModule: '{module_title}' 박스를 찾을 수 없음")
    
    def on_search_clicked(self):
        """검색 버튼 클릭 또는 엔터 키 처리"""
        search_text = self.search_input.text().strip().lower()
        
        if not search_text:
            # 검색어가 없으면 초기화
            self.on_reset_clicked()
            return
        
        # 검색 수행
        self.filtered_keys = []
        
        for key in self.current_keys:
            value0, value1 = self.event_dict[key]
            
            # 우선순위에 따라 검색: key → value[0] → value[1]
            # 1. key에서 검색
            if search_text in key.lower():
                self.filtered_keys.append(key)
                continue
            
            # 2. value[0] (한국어 번역)에서 검색
            if search_text in value0.lower():
                self.filtered_keys.append(key)
                continue
            
            # 3. value[1] (관련 태그)에서 검색
            if search_text in value1.lower():
                self.filtered_keys.append(key)
        
        # 검색 상태 설정
        self.is_searching = True
        
        # 테이블 업데이트
        self.update_table()
        
        # 결과 메시지
        if self.filtered_keys:
            print(f"[OK] 검색 완료: '{search_text}' - {len(self.filtered_keys)}개 항목 발견")
        # else:
        #     QMessageBox.information(
        #         self.widget,
        #         "검색 결과",
        #         f"'{search_text}'에 대한 검색 결과가 없습니다."
        #     )
    
    def on_reset_clicked(self):
        """초기화 버튼 클릭 처리"""
        # 검색 입력 필드 초기화
        self.search_input.clear()
        
        # 검색 상태 해제
        self.is_searching = False
        self.filtered_keys = []
        
        # 테이블 업데이트 (전체 목록 표시)
        self.update_table()
        
        print(f"[OK] 검색 초기화: 전체 {len(self.current_keys)}개 항목 표시")
    
    def get_parameters(self) -> dict:
        """모듈 파라미터 반환"""
        return {
            'loaded_events': len(self.event_dict),
            'hidden_events': len(self.deleted_keys)
        }

    def on_manage_clicked(self):
        """관리 버튼 클릭 - 숨긴 항목 관리 윈도우 열기"""
        if not self.deleted_keys:
            QMessageBox.information(
                self.widget,
                "알림",
                "숨긴 항목이 없습니다."
            )
            return

        # 숨긴 항목 관리 다이얼로그 생성 및 표시
        dialog = HiddenItemsDialog(self.deleted_keys, self.parquet_path, self.widget)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # 복원할 키 목록 가져오기
            restored_keys = dialog.get_restored_keys()
            if restored_keys:
                self.restore_hidden_items(restored_keys)

    def restore_hidden_items(self, keys_to_restore: List[str]):
        """숨긴 항목 복원 - parquet 원본 순서 유지"""
        try:
            import pandas as pd

            print(f"[DEBUG] 복원 요청된 키: {keys_to_restore}")

            # Parquet 파일에서 복원할 데이터 로드
            if not self.parquet_path.exists():
                print(f"[ERROR] Parquet 파일이 존재하지 않음: {self.parquet_path}")
                return

            df = pd.read_parquet(self.parquet_path)
            print(f"[DEBUG] Parquet 로드 완료, 총 {len(df)}행")

            restored_count = 0
            for _, row in df.iterrows():
                key = str(row.iloc[0])
                if key in keys_to_restore:
                    value0 = str(row.iloc[1])
                    value1 = str(row.iloc[2])

                    print(f"[DEBUG] 복원 중: {key}")

                    # 딕셔너리에 추가
                    self.event_dict[key] = (value0, value1)

                    # 삭제 목록에서 제거
                    self.deleted_keys.discard(key)
                    restored_count += 1

            # 삭제 목록 저장
            self.save_deleted_keys()

            # current_keys를 parquet 원본 순서대로 재구성
            self.current_keys = []
            for _, row in df.iterrows():
                key = str(row.iloc[0])
                if key in self.event_dict:
                    self.current_keys.append(key)

            # 검색 상태 초기화 후 테이블 업데이트 (복원된 항목이 보이도록)
            if self.is_searching:
                self.is_searching = False
                self.filtered_keys = []
                if self.search_input:
                    self.search_input.clear()

            print(f"[DEBUG] 복원 후 current_keys 수: {len(self.current_keys)}, event_dict 수: {len(self.event_dict)}")

            # 테이블 업데이트
            self.update_table()

            print(f"[OK] {restored_count}개 항목 복원 완료")

        except Exception as e:
            print(f"[ERROR] 항목 복원 실패: {e}")


class HiddenItemsDialog(QDialog):
    """숨긴 항목 관리 다이얼로그 - 단일 선택 리스트"""

    def __init__(self, deleted_keys: set, parquet_path: Path, parent=None):
        super().__init__(parent)
        self.deleted_keys = deleted_keys
        self.parquet_path = parquet_path
        self.restored_keys = []
        self.items_data = {}  # {key: (value0, value1)}

        self.setWindowTitle("숨긴 항목 관리")
        self.setMinimumSize(get_scaled_size(500), get_scaled_size(400))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)  # 닫힐 때 자동 삭제

        self.setup_ui()
        self.load_hidden_items()

    def setup_ui(self):
        """UI 설정"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            get_scaled_size(16), get_scaled_size(16),
            get_scaled_size(16), get_scaled_size(16)
        )
        layout.setSpacing(get_scaled_size(12))

        # 안내 라벨
        info_label = QLabel("복원할 항목을 선택하고 복원 버튼을 누르세요:")
        info_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(16)}px;
            color: {DARK_COLORS['text_primary']};
        """)
        layout.addWidget(info_label)

        # 리스트 위젯 (단일 선택)
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                font-size: {get_scaled_font_size(16)}px;
            }}
            QListWidget::item {{
                padding: {get_scaled_size(8)}px;
                border-bottom: 1px solid {DARK_COLORS['border']};
            }}
            QListWidget::item:selected {{
                background-color: {DARK_COLORS['highlight']};
            }}
            QListWidget::item:hover {{
                background-color: {DARK_COLORS['bg_tertiary']};
            }}
        """)
        layout.addWidget(self.list_widget)

        # 버튼 박스
        button_box = QDialogButtonBox()

        restore_btn = QPushButton("선택 항목 복원")
        restore_btn.setStyleSheet(get_dynamic_styles()['primary_button'])
        button_box.addButton(restore_btn, QDialogButtonBox.ButtonRole.AcceptRole)

        cancel_btn = QPushButton("취소")
        cancel_btn.setStyleSheet(get_dynamic_styles()['secondary_button'])
        button_box.addButton(cancel_btn, QDialogButtonBox.ButtonRole.RejectRole)

        button_box.accepted.connect(self.on_restore)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        # 다이얼로그 스타일
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)

    def load_hidden_items(self):
        """숨긴 항목 데이터 로드"""
        try:
            import pandas as pd

            if not self.parquet_path.exists():
                return

            df = pd.read_parquet(self.parquet_path)

            for _, row in df.iterrows():
                key = str(row.iloc[0])
                if key in self.deleted_keys:
                    value0 = str(row.iloc[1])
                    value1 = str(row.iloc[2])
                    self.items_data[key] = (value0, value1)

                    # 리스트에 추가 (key - value0 형식)
                    item = QListWidgetItem(f"{key} - {value0}")
                    item.setData(Qt.ItemDataRole.UserRole, key)
                    self.list_widget.addItem(item)

        except Exception as e:
            print(f"[ERROR] 숨긴 항목 로드 실패: {e}")

    def on_restore(self):
        """복원 버튼 클릭"""
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            QMessageBox.information(
                self,
                "알림",
                "복원할 항목을 선택해주세요."
            )
            return

        # 단일 선택이므로 하나만 복원
        self.restored_keys = [selected_items[0].data(Qt.ItemDataRole.UserRole)]
        self.accept()

    def get_restored_keys(self) -> List[str]:
        """복원할 키 목록 반환"""
        return self.restored_keys