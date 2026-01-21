"""
E621 Event Module V2 - 계층형 탐색 + 프롬프트 테스트벤치

구조:
[Categories 버튼] | [Level 2 리스트] | [Level 3 리스트] | [Wiki 정보]
[e621 프롬프트 테스트벤치] | [다음/생성 버튼]
"""

import json
import urllib.request
import urllib.error
import ssl
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QTextEdit, QLineEdit,
    QButtonGroup, QMessageBox, QSplitter, QRadioButton,
    QDialog, QDialogButtonBox, QAbstractItemView, QApplication,
    QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer, QThread
from PyQt6.QtGui import QFont, QColor, QBrush, QKeyEvent

from interfaces.base_module import BaseMiddleModule
from ui.theme import DARK_COLORS, get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.modern_menu import setModernStyle
from utils.translator import english_to_korean

# SSL 인증서 검증
try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CONTEXT = ssl.create_default_context()

# HuggingFace 데이터 URL
E621_DATA_URL = "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/e621_data"


class E621TagListWidget(QListWidget):
    """태그 리스트 위젯 - Ctrl+C 복사 시 카운트 제거"""

    def keyPressEvent(self, event: QKeyEvent):
        """키 입력 이벤트 처리"""
        # Ctrl+C 감지
        if event.key() == Qt.Key.Key_C and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self._copy_selected_tags()
            event.accept()
        else:
            super().keyPressEvent(event)

    def _copy_selected_tags(self):
        """선택된 태그를 클립보드에 복사 (카운트 제거)"""
        selected_items = self.selectedItems()
        if not selected_items:
            return

        tags = []
        for item in selected_items:
            # 표시 텍스트에서 태그명만 추출
            text = item.text()

            # ⭐ 제거
            if text.startswith("⭐ "):
                text = text[2:]

            # (카운트) 제거 - 마지막 괄호와 내용 제거
            if " (" in text:
                text = text.rsplit(" (", 1)[0]

            # 언더바를 공백으로 변환한 상태이므로 다시 언더바로 변환
            text = text.replace(" ", "_")

            tags.append(text)

        # 클립보드에 복사
        if tags:
            clipboard = QApplication.clipboard()
            clipboard.setText(", ".join(tags))
            print(f"[Clipboard] {len(tags)}개 태그 복사: {', '.join(tags)}")


class WikiTranslationWorker(QThread):
    """Wiki 텍스트 번역을 백그라운드에서 수행하는 워커"""
    translation_completed = pyqtSignal(str, str, str)  # request_hash, 원문, 번역문
    translation_failed = pyqtSignal(str)  # request_hash

    def __init__(self, request_hash: str):
        super().__init__()
        self.request_hash = request_hash
        self.english_text = ""

    def set_text(self, text):
        """번역할 텍스트 설정"""
        self.english_text = text

    def run(self):
        """번역 수행"""
        if self.english_text:
            try:
                translated = english_to_korean(self.english_text)
                if translated:
                    self.translation_completed.emit(self.request_hash, self.english_text, translated)
                else:
                    self.translation_failed.emit(self.request_hash)
            except Exception as e:
                print(f"Wiki 번역 오류: {e}")
                self.translation_failed.emit(self.request_hash)


class E621EventSignals(QObject):
    """E621 이벤트 시그널 클래스"""
    event_selected = pyqtSignal(str, str, str)  # key, value0, value1
    generation_requested = pyqtSignal(dict)  # generation parameters


class E621EventModuleV2(BaseMiddleModule):
    """E621 이벤트 관리 모듈 V2 - 계층형 탐색 + 프롬프트 테스트벤치"""

    def __init__(self):
        super().__init__()
        # 호환성
        self.NAI_compatibility = True
        self.WEBUI_compatibility = True
        self.COMFYUI_compatibility = True

        # 자동 분리 강제 설정
        self.auto_detach = True
        self.is_first_toggle = True

        # 데이터 경로
        self.data_path = Path(__file__).parent.parent / "data" / "e621_data"
        self.settings_path = Path(__file__).parent.parent / "save" / "e621_module_v2_settings.json"
        self.starred_path = Path(__file__).parent.parent / "save" / "e621_starred_v2.json"
        self.deleted_path = Path(__file__).parent.parent / "save" / "e621_deleted_v2.json"

        # 데이터
        self.data = None  # JSON 데이터
        self.current_category = None
        self.current_level2 = None
        self.current_level3 = None

        # 즐겨찾기 및 삭제된 태그
        self.starred_keys = set()
        self.deleted_keys = set()

        # 검색 상태
        self.is_searching = False
        self.filtered_level2 = []
        self.filtered_level3 = []
        self.searched_tree = {}  # {category: {folder: [tag_dicts]}}

        # UI 위젯
        self.widget = None
        self.category_buttons = {}
        self.level2_list = None
        self.level3_list = None
        self.related_tags_edit = None  # e621 프롬프트 테스트벤치
        self.wiki_body_edit = None  # Wiki 정보 (번역)
        self.search_input = None

        # 보기 모드 라디오버튼
        self.radio_default = None
        self.radio_starred = None

        # 버튼들
        self.generate_button = None
        self.star_button = None
        self.hide_button = None
        self.manage_button = None

        # 시그널
        self.signals = E621EventSignals()

        # 로드 상태
        self.is_loaded = False

        # 번역 관련
        self.translation_worker = None
        self.original_wiki_text = ""
        self.is_translating = False
        self.current_translation_hash = None  # 현재 번역 요청 해시
        self.current_wiki_text = ""  # 현재 표시된 wiki 원문
        self.current_display_tag_name = ""  # 현재 표시된 태그명 (언더바 제거)
        self.current_tag_count = ""  # 현재 표시된 태그 카운트
        self.disable_translation = False  # 자동 번역 비활성화 플래그
        self.disable_translation_checkbox = None  # 번역 비활성화 체크박스
        self.disable_wiki_search = False  # 원문 검색 비활성화 플래그 (기본값: 활성화)
        self.disable_wiki_search_checkbox = None  # 원문 검색 비활성화 체크박스

        # 프로그램 시작 시 데이터 파일 체크 및 자동 다운로드
        self._check_and_download_data()

    def _check_and_download_data(self):
        """데이터 파일 체크 및 자동 다운로드 (동기 방식)"""
        if not self.data_path.exists():
            print("[E621 V2] 데이터 파일 없음 - 다운로드 시작...")
            try:
                # 헤더 설정
                headers = {
                    'User-Agent': 'NAIA/2.0.0 E621 Module'
                }

                request = urllib.request.Request(E621_DATA_URL, headers=headers)

                # 타겟 디렉터리 생성
                self.data_path.parent.mkdir(parents=True, exist_ok=True)

                # 다운로드 (동기 방식)
                print("[E621 V2] HuggingFace에서 다운로드 중...")
                with urllib.request.urlopen(request, context=SSL_CONTEXT, timeout=30) as response:
                    total_size = int(response.headers.get('content-length', 0))
                    total_mb = total_size / (1024 * 1024)
                    print(f"[E621 V2] 파일 크기: {total_mb:.2f} MB")

                    block_size = 8192
                    downloaded = 0

                    with open(self.data_path, 'wb') as out_file:
                        while True:
                            block = response.read(block_size)
                            if not block:
                                break
                            downloaded += len(block)
                            out_file.write(block)

                            # 진행률 표시 (10% 단위)
                            if total_size > 0:
                                percent = (downloaded * 100) // total_size
                                if percent % 10 == 0 and downloaded > 0:
                                    downloaded_mb = downloaded / (1024 * 1024)
                                    print(f"[E621 V2] 다운로드 중... {percent}% ({downloaded_mb:.1f}/{total_mb:.1f} MB)")

                print("[E621 V2] ✓ 다운로드 완료!")

            except urllib.error.HTTPError as e:
                print(f"[E621 V2] ✗ HTTP 오류 {e.code}: {e.reason}")
                print("[E621 V2] 모듈을 사용할 수 없습니다.")
            except urllib.error.URLError as e:
                print(f"[E621 V2] ✗ 네트워크 오류: {e.reason}")
                print("[E621 V2] 모듈을 사용할 수 없습니다.")
            except Exception as e:
                print(f"[E621 V2] ✗ 다운로드 실패: {str(e)}")
                print("[E621 V2] 모듈을 사용할 수 없습니다.")
        else:
            print("[E621 V2] 데이터 파일 확인 완료")

    def get_title(self) -> str:
        return "🎯 E621 연구용 모듈 V2"

    def get_order(self) -> int:
        return 5

    def initialize_with_context(self, context):
        """AppContext 주입"""
        self.app_context = context

    def create_widget(self, parent=None) -> QWidget:
        """UI 위젯 생성"""
        if self.widget:
            return self.widget

        self.widget = QWidget(parent)
        self.widget.setMinimumHeight(get_scaled_size(800))
        main_layout = QVBoxLayout(self.widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(get_scaled_size(8))

        # 데이터 로드
        QTimer.singleShot(100, self.load_data)

        # === 상단: 검색 + 제어 버튼 영역 ===
        control_layout = self.create_control_layout()
        main_layout.addLayout(control_layout)

        # === 메인 영역: 4단 분할 (Categories | L2 | L3 | 태그정보+Wiki) ===
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(get_scaled_size(3))

        # 1. Categories 버튼 패널
        categories_widget = self.create_categories_panel()
        splitter.addWidget(categories_widget)

        # 2. Level 2 리스트
        level2_widget = self.create_level2_panel()
        splitter.addWidget(level2_widget)

        # 3. Level 3 리스트
        level3_widget = self.create_level3_panel()
        splitter.addWidget(level3_widget)

        # 4. 태그 정보 + Wiki 패널
        info_widget = self.create_info_panel()
        splitter.addWidget(info_widget)

        # 초기 크기 비율 설정
        splitter.setSizes([
            get_scaled_size(150),  # Categories
            get_scaled_size(200),  # Level 2
            get_scaled_size(300),  # Level 3
            get_scaled_size(450),  # Info+Wiki
        ])

        main_layout.addWidget(splitter, 1)

        # === 하단: 설정 영역 ===
        settings_layout = self.create_settings_panel()
        main_layout.addLayout(settings_layout)

        # 설정 로드
        self.load_settings()

        return self.widget

    def create_control_layout(self) -> QHBoxLayout:
        """상단 검색 + 제어 버튼 영역"""
        layout = QHBoxLayout()
        layout.setSpacing(get_scaled_size(8))

        # 검색 입력
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("태그 검색 - 꼭 정확한 단어로 검색하세요")
        self.search_input.setStyleSheet(get_dynamic_styles()['compact_lineedit'])
        self.search_input.returnPressed.connect(self.on_search)
        self.search_input.setProperty("autocomplete_ignore", True)
        layout.addWidget(self.search_input, 1)

        # 검색 버튼
        search_button = QPushButton("검색")
        search_button.setStyleSheet(get_dynamic_styles()['primary_button'])
        search_button.clicked.connect(self.on_search)
        layout.addWidget(search_button)

        # 초기화 버튼
        reset_button = QPushButton("초기화")
        reset_button.setStyleSheet(get_dynamic_styles()['secondary_button'])
        reset_button.clicked.connect(self.on_reset)
        layout.addWidget(reset_button)

        # 구분선
        separator = QLabel("|")
        separator.setStyleSheet(f"color: {DARK_COLORS['border']}; font-size: {get_scaled_font_size(16)}px;")
        layout.addWidget(separator)

        # 보기 모드 라디오버튼
        radio_style = f"""
            QRadioButton {{
                font-size: {get_scaled_font_size(14)}px;
                color: {DARK_COLORS['text_primary']};
                spacing: {get_scaled_size(4)}px;
            }}
        """

        self.radio_default = QRadioButton("기본")
        self.radio_default.setStyleSheet(radio_style)
        self.radio_default.setChecked(True)
        self.radio_default.toggled.connect(self.on_view_mode_changed)
        layout.addWidget(self.radio_default)

        self.radio_starred = QRadioButton("즐겨찾기")
        self.radio_starred.setStyleSheet(radio_style)
        self.radio_starred.toggled.connect(self.on_view_mode_changed)
        layout.addWidget(self.radio_starred)

        # 즐겨찾기 버튼
        self.star_button = QPushButton("☆")
        self.star_button.setStyleSheet(get_dynamic_styles()['secondary_button'])
        self.star_button.clicked.connect(self.on_star_clicked)
        self.star_button.setToolTip("즐겨찾기 추가/해제")
        layout.addWidget(self.star_button)

        # 숨김 버튼
        self.hide_button = QPushButton("숨김")
        self.hide_button.setStyleSheet(get_dynamic_styles()['secondary_button'])
        self.hide_button.clicked.connect(self.on_hide_clicked)
        layout.addWidget(self.hide_button)

        # 관리 버튼
        self.manage_button = QPushButton("관리")
        self.manage_button.setStyleSheet(get_dynamic_styles()['secondary_button'])
        self.manage_button.clicked.connect(self.on_manage_clicked)
        self.manage_button.setToolTip("숨긴 항목 복원")
        layout.addWidget(self.manage_button)

        return layout

    def create_categories_panel(self) -> QWidget:
        """카테고리 버튼 패널 생성"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(4))

        # 라벨
        label = QLabel("Categories")
        label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(18)}px;
            font-weight: bold;
            color: {DARK_COLORS['text_primary']};
        """)
        layout.addWidget(label)

        # 버튼 그룹
        self.category_button_group = QButtonGroup(self.widget)
        self.category_button_group.setExclusive(True)

        # General 카테고리 버튼들
        general_categories = [
            "Body", "Attire", "Objects_Items", "Locations", "Effects",
            "Actions", "Basic", "Meta", "NSFW", "Danger", "Safe_Other"
        ]

        # Species 카테고리 버튼들 (파란색)
        species_categories = ["Real", "Fantasy_IP", "Unknown"]

        # General 버튼 스타일 (기본)
        general_button_style = f"""
            QPushButton {{
                font-size: {get_scaled_font_size(18)}px;
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 2px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(5)}px;
                padding: {get_scaled_size(8)}px;
                text-align: left;
                min-height: {get_scaled_size(35)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QPushButton:checked {{
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
                border-color: {DARK_COLORS['accent_blue']};
                font-weight: bold;
            }}
        """

        # Species 버튼 스타일 (파란색 테두리, 흰색 텍스트)
        species_button_style = f"""
            QPushButton {{
                font-size: {get_scaled_font_size(18)}px;
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 2px solid {DARK_COLORS['accent_blue']};
                border-radius: {get_scaled_size(5)}px;
                padding: {get_scaled_size(8)}px;
                text-align: left;
                min-height: {get_scaled_size(35)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QPushButton:checked {{
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
                border-color: {DARK_COLORS['accent_blue']};
                font-weight: bold;
            }}
        """

        # General 카테고리 버튼 생성
        for category in general_categories:
            button = QPushButton(category)
            button.setCheckable(True)
            button.setStyleSheet(general_button_style)
            button.clicked.connect(lambda checked, cat=category: self.on_category_clicked(cat))
            self.category_button_group.addButton(button)
            self.category_buttons[category] = button
            layout.addWidget(button)

        # Species 카테고리 버튼 생성 (파란색)
        for category in species_categories:
            button = QPushButton(category)
            button.setCheckable(True)
            button.setStyleSheet(species_button_style)
            button.clicked.connect(lambda checked, cat=category: self.on_category_clicked(cat))
            self.category_button_group.addButton(button)
            self.category_buttons[category] = button
            layout.addWidget(button)

        layout.addStretch()
        return panel

    def create_level2_panel(self) -> QWidget:
        """Level 2 리스트 패널"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(4))

        label = QLabel("Level 2 Folders")
        label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(18)}px;
            font-weight: bold;
            color: {DARK_COLORS['text_primary']};
        """)
        layout.addWidget(label)

        self.level2_list = QListWidget()
        self.level2_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                font-size: {get_scaled_font_size(18)}px;
            }}
            QListWidget::item {{
                padding: {get_scaled_size(8)}px;
                min-height: {get_scaled_size(30)}px;
            }}
            QListWidget::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
            QListWidget::item:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        self.level2_list.itemClicked.connect(self.on_level2_clicked)
        # 키보드로 선택 변경 시에도 클릭 처리
        self.level2_list.currentItemChanged.connect(lambda current, _: self.on_level2_clicked(current) if current else None)
        layout.addWidget(self.level2_list)

        return panel

    def create_level3_panel(self) -> QWidget:
        """Level 3 태그 리스트 패널"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(4))

        label = QLabel("Tags (All Items)")
        label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(18)}px;
            font-weight: bold;
            color: {DARK_COLORS['text_primary']};
        """)
        layout.addWidget(label)

        self.level3_list = E621TagListWidget()  # 커스텀 리스트 위젯 사용
        # 다중 선택 허용 (Ctrl+클릭, Shift+클릭)
        self.level3_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.level3_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                font-size: {get_scaled_font_size(18)}px;
            }}
            QListWidget::item {{
                padding: {get_scaled_size(8)}px;
                min-height: {get_scaled_size(30)}px;
            }}
            QListWidget::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
            QListWidget::item:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        self.level3_list.itemClicked.connect(self.on_level3_clicked)
        # 키보드로 선택 변경 시에도 클릭 처리
        self.level3_list.currentItemChanged.connect(lambda current, _: self.on_level3_clicked(current) if current else None)
        layout.addWidget(self.level3_list)

        return panel

    def create_info_panel(self) -> QWidget:
        """태그 정보 + Wiki 패널"""
        panel = QWidget()
        panel.setMinimumWidth(get_scaled_size(300))
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(4))

        # Wiki 설명 (자동 번역)
        wiki_label = QLabel("Wiki 설명 (자동 번역)")
        wiki_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(16)}px;
            font-weight: bold;
            color: {DARK_COLORS['text_primary']};
        """)
        layout.addWidget(wiki_label)

        self.wiki_body_edit = QTextEdit()
        self.wiki_body_edit.setAcceptRichText(False)
        self.wiki_body_edit.setStyleSheet(get_dynamic_styles()['compact_textedit'])
        self.wiki_body_edit.setPlaceholderText("Wiki 설명...")
        self.wiki_body_edit.setReadOnly(True)  # Wiki는 읽기 전용
        setModernStyle(self.wiki_body_edit)
        layout.addWidget(self.wiki_body_edit, 1)

        return panel

    # ===== UI 생성 =====

    def create_settings_panel(self) -> QVBoxLayout:
        """하단 패널: e621 프롬프트 테스트벤치 + 버튼들 + 번역 설정"""
        main_layout = QVBoxLayout()
        main_layout.setSpacing(get_scaled_size(8))

        # 상단: 프롬프트 테스트벤치 + 버튼
        top_layout = QHBoxLayout()
        top_layout.setSpacing(get_scaled_size(8))

        # 좌측: 프롬프트 테스트벤치 영역
        related_layout = QVBoxLayout()
        related_label = QLabel("e621 프롬프트 테스트벤치")
        related_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(16)}px;
            font-weight: bold;
            color: {DARK_COLORS['text_primary']};
        """)
        related_layout.addWidget(related_label)

        self.related_tags_edit = QTextEdit()
        self.related_tags_edit.setAcceptRichText(False)
        self.related_tags_edit.setMinimumHeight(get_scaled_size(80))
        self.related_tags_edit.setMaximumHeight(get_scaled_size(120))
        self.related_tags_edit.setStyleSheet(get_dynamic_styles()['compact_textedit'])
        setModernStyle(self.related_tags_edit)

        # 기본 프롬프트 텍스트 설정
        default_prompt = "1girl, 1boy, 2:: e621태그는_강조하여_입력하세요 ::, duo, male/female, nsfw, rating:explicit"
        self.related_tags_edit.setPlainText(default_prompt)

        related_layout.addWidget(self.related_tags_edit)
        top_layout.addLayout(related_layout, 1)

        # 우측: 버튼 영역
        button_layout = QVBoxLayout()
        button_layout.setSpacing(get_scaled_size(8))

        # 생성 버튼
        self.generate_button = QPushButton("생성")
        self.generate_button.setStyleSheet(get_dynamic_styles()['primary_button'])
        self.generate_button.clicked.connect(self.on_generate_clicked)
        self.generate_button.setToolTip("프롬프트 테스트벤치의 태그로 이미지 생성")
        button_layout.addWidget(self.generate_button)

        button_layout.addStretch()
        top_layout.addLayout(button_layout)

        main_layout.addLayout(top_layout)

        # 하단: 체크박스들 (번역 + 원문 검색)
        checkbox_layout = QHBoxLayout()
        checkbox_layout.setSpacing(get_scaled_size(16))

        # 번역 비활성화 체크박스
        self.disable_translation_checkbox = QCheckBox("자동 번역을 사용하지 않습니다")
        self.disable_translation_checkbox.setStyleSheet(get_dynamic_styles()['dark_checkbox'])
        self.disable_translation_checkbox.setChecked(self.disable_translation)
        self.disable_translation_checkbox.stateChanged.connect(self._on_translation_checkbox_changed)
        checkbox_layout.addWidget(self.disable_translation_checkbox)

        # 원문 검색 비활성화 체크박스
        self.disable_wiki_search_checkbox = QCheckBox("원문 검색을 사용하지 않습니다")
        self.disable_wiki_search_checkbox.setStyleSheet(get_dynamic_styles()['dark_checkbox'])
        self.disable_wiki_search_checkbox.setChecked(self.disable_wiki_search)
        self.disable_wiki_search_checkbox.stateChanged.connect(self._on_wiki_search_checkbox_changed)
        checkbox_layout.addWidget(self.disable_wiki_search_checkbox)

        checkbox_layout.addStretch()
        main_layout.addLayout(checkbox_layout)

        return main_layout

    # ===== 데이터 로딩 =====

    def load_data(self):
        """JSON 데이터 로드"""
        if self.is_loaded:
            return

        try:
            # JSON 데이터 로드
            with open(self.data_path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)

            # 삭제/즐겨찾기 목록 로드
            self.load_deleted_keys()
            self.load_starred_keys()

            self.is_loaded = True
            print(f"[OK] E621 V2 데이터 로드 완료")

            # 카테고리 버튼에 즐겨찾기 표시 업데이트
            self.update_category_starred_labels()

        except FileNotFoundError as e:
            QMessageBox.critical(
                self.widget,
                "오류",
                f"파일을 찾을 수 없습니다: {e}"
            )
        except Exception as e:
            QMessageBox.critical(
                self.widget,
                "오류",
                f"파일 로드 중 오류: {str(e)}"
            )

    def load_deleted_keys(self):
        """삭제된 키 목록 로드 (V1 파일 자동 마이그레이션)"""
        self.deleted_keys.clear()

        # V1 파일 경로 (기존 파일)
        v1_deleted_path = Path(__file__).parent.parent / "save" / "e621_event" / "deleted.json"

        # V1 파일이 있고 V2 파일이 없으면 마이그레이션
        if v1_deleted_path.exists() and not self.deleted_path.exists():
            try:
                with open(v1_deleted_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.deleted_keys = set(data.get('deleted_keys', []))
                print(f"[Migration] V1 삭제 목록 {len(self.deleted_keys)}개 마이그레이션")
                # V2 형식으로 저장
                self.save_deleted_keys()
                return
            except Exception as e:
                print(f"[WARNING] V1 삭제 목록 마이그레이션 실패: {e}")

        # V2 파일 로드
        if self.deleted_path.exists():
            try:
                with open(self.deleted_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.deleted_keys = set(data.get('deleted_keys', []))
                    print(f"[OK] 삭제된 키 {len(self.deleted_keys)}개 로드")
            except Exception as e:
                print(f"[ERROR] 삭제된 키 로드 실패: {e}")

    def save_deleted_keys(self):
        """삭제된 키 목록 저장"""
        try:
            self.deleted_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.deleted_path, 'w', encoding='utf-8') as f:
                json.dump({'deleted_keys': list(self.deleted_keys)}, f, ensure_ascii=False, indent=2)
            print(f"[OK] 삭제 목록 저장: {len(self.deleted_keys)}개")
        except Exception as e:
            print(f"[ERROR] 삭제 목록 저장 실패: {e}")

    def load_starred_keys(self):
        """즐겨찾기 키 목록 로드 (V1 파일 자동 마이그레이션)"""
        self.starred_keys.clear()

        # V1 파일 경로 (기존 파일)
        v1_starred_path = Path(__file__).parent.parent / "save" / "e621_event" / "starred.json"

        # V1 파일이 있고 V2 파일이 없으면 마이그레이션
        if v1_starred_path.exists() and not self.starred_path.exists():
            try:
                with open(v1_starred_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.starred_keys = set(data.get('starred_keys', []))
                print(f"[Migration] V1 즐겨찾기 {len(self.starred_keys)}개 마이그레이션")
                # V2 형식으로 저장
                self.save_starred_keys()
                return
            except Exception as e:
                print(f"[WARNING] V1 즐겨찾기 마이그레이션 실패: {e}")

        # V2 파일 로드
        if self.starred_path.exists():
            try:
                with open(self.starred_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.starred_keys = set(data.get('starred_keys', []))
                    print(f"[OK] 즐겨찾기 키 {len(self.starred_keys)}개 로드")
            except Exception as e:
                print(f"[ERROR] 즐겨찾기 키 로드 실패: {e}")

    def save_starred_keys(self):
        """즐겨찾기 키 목록 저장"""
        try:
            self.starred_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.starred_path, 'w', encoding='utf-8') as f:
                json.dump({'starred_keys': list(self.starred_keys)}, f, ensure_ascii=False, indent=2)
            print(f"[OK] 즐겨찾기 목록 저장: {len(self.starred_keys)}개")
        except Exception as e:
            print(f"[ERROR] 즐겨찾기 목록 저장 실패: {e}")

    def load_settings(self):
        """설정 로드"""
        try:
            if self.settings_path.exists():
                with open(self.settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    self.disable_translation = settings.get('disable_translation', False)
                    self.disable_wiki_search = settings.get('disable_wiki_search', False)

                    # 체크박스 상태 업데이트
                    if hasattr(self, 'disable_translation_checkbox'):
                        self.disable_translation_checkbox.setChecked(self.disable_translation)
                    if hasattr(self, 'disable_wiki_search_checkbox'):
                        self.disable_wiki_search_checkbox.setChecked(self.disable_wiki_search)

                    print(f"[OK] E621 모듈 설정 로드 (번역: {not self.disable_translation}, 원문검색: {not self.disable_wiki_search})")
        except Exception as e:
            print(f"[ERROR] E621 모듈 설정 로드 실패: {e}")

    def save_settings(self):
        """설정 저장"""
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings = {
                'disable_translation': self.disable_translation,
                'disable_wiki_search': self.disable_wiki_search
            }
            with open(self.settings_path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
            print(f"[OK] E621 모듈 설정 저장")
        except Exception as e:
            print(f"[ERROR] E621 모듈 설정 저장 실패: {e}")

    # ===== 이벤트 핸들러 =====

    def on_category_clicked(self, category: str):
        """카테고리 버튼 클릭"""
        print(f"[Category] {category} 선택")
        self.current_category = category
        self.current_level2 = None
        self.current_level3 = None

        # 검색 모드일 때는 검색 상태를 유지
        # (검색 상태 초기화하지 않음)

        # Level 2 리스트 업데이트
        self.update_level2_list()

        # Level 3에 카테고리의 모든 태그 표시
        self._show_all_category_tags()

        # 정보 패널 초기화
        self.wiki_body_edit.clear()

    def update_level2_list(self):
        """Level 2 리스트 업데이트"""
        self.level2_list.clear()

        if not self.data or not self.current_category:
            return

        # General 또는 Species 카테고리에서 현재 카테고리 데이터 찾기
        category_data = None
        if "General" in self.data and self.current_category in self.data["General"]:
            category_data = self.data["General"][self.current_category]
        elif "Species" in self.data and self.current_category in self.data["Species"]:
            category_data = self.data["Species"][self.current_category]

        if not category_data:
            print(f"[Level 2] 카테고리 데이터를 찾을 수 없음: {self.current_category}")
            return

        # 검색 모드일 때는 searched_tree 사용
        if self.is_searching and self.searched_tree:
            # searched_tree에서 현재 카테고리의 폴더 목록 가져오기
            category_folders = self.searched_tree.get(self.current_category, {})
            display_folders = sorted(category_folders.keys())
        else:
            # 일반 모드: 전체 데이터 사용
            # 빈 폴더가 아닌 폴더만 표시
            display_folders = []
            for folder_name in sorted(category_data.keys()):
                folder_data = category_data[folder_name]
                temp_tags = []
                self._collect_all_tags(folder_data, temp_tags)
                if len(temp_tags) > 0:
                    display_folders.append(folder_name)

        # 즐겨찾기 모드인 경우 추가 필터링: 즐겨찾기 태그가 있는 폴더만 표시
        if self.radio_starred and self.radio_starred.isChecked():
            if self.is_searching and self.searched_tree:
                # 검색 모드: searched_tree에서 즐겨찾기 필터링
                category_folders = self.searched_tree.get(self.current_category, {})
                filtered_by_starred = []
                for folder_name in display_folders:
                    folder_tags = category_folders.get(folder_name, [])
                    has_starred = any(t.get("tag", "") in self.starred_keys for t in folder_tags)
                    if has_starred:
                        filtered_by_starred.append(folder_name)
                display_folders = filtered_by_starred
            else:
                # 일반 모드: 전체 데이터에서 즐겨찾기 필터링
                filtered_by_starred = []
                for folder_name in display_folders:
                    folder_data = category_data[folder_name]
                    temp_tags = []
                    self._collect_all_tags(folder_data, temp_tags)
                    has_starred = any(t.get("tag", "") in self.starred_keys for t in temp_tags)
                    if has_starred:
                        filtered_by_starred.append(folder_name)
                display_folders = filtered_by_starred

        # 리스트에 추가
        for folder_name in display_folders:
            display_name = folder_name.replace("_", " ")
            item = QListWidgetItem(display_name)
            item.setData(Qt.ItemDataRole.UserRole, folder_name)
            self.level2_list.addItem(item)

        print(f"[Level 2] {len(display_folders)} 폴더 표시")

    def on_level2_clicked(self, item: QListWidgetItem):
        """Level 2 리스트 클릭"""
        self.current_level2 = item.data(Qt.ItemDataRole.UserRole)
        self.current_level3 = None
        print(f"[Level 2] {self.current_level2} 선택")

        # Level 3 리스트 업데이트
        self.update_level3_list()

        # 정보 패널 초기화
        self.wiki_body_edit.clear()

    def update_level3_list(self):
        """Level 3 리스트 업데이트"""
        self.level3_list.clear()

        if not self.data or not self.current_category or not self.current_level2:
            return

        # 검색 모드일 때는 searched_tree 사용
        if self.is_searching and self.searched_tree:
            category_folders = self.searched_tree.get(self.current_category, {})
            display_tags = category_folders.get(self.current_level2, [])
        else:
            # 일반 모드: General 또는 Species에서 데이터 찾기
            category_data = None
            if "General" in self.data and self.current_category in self.data["General"]:
                category_data = self.data["General"][self.current_category]
            elif "Species" in self.data and self.current_category in self.data["Species"]:
                category_data = self.data["Species"][self.current_category]

            if not category_data:
                print(f"[Level 3] 카테고리 데이터를 찾을 수 없음: {self.current_category}")
                return

            level2_data = category_data.get(self.current_level2, {})

            # 모든 태그 수집
            display_tags = []
            self._collect_all_tags(level2_data, display_tags)

        # 즐겨찾기 모드인 경우 필터링
        if self.radio_starred and self.radio_starred.isChecked():
            display_tags = [t for t in display_tags if t.get("tag", "") in self.starred_keys]

        # count 기준 정렬
        display_tags.sort(key=lambda x: x.get("count", 0), reverse=True)

        # 리스트에 추가
        for tag_dict in display_tags:
            tag_name = tag_dict.get("tag", "")
            if tag_name and tag_name not in self.deleted_keys:
                count = tag_dict.get("count", 0)
                count_str = self._format_count(count)
                matched_in_wiki = tag_dict.get("matched_in_wiki", False)

                display_tag_name = tag_name.replace("_", " ")
                display_text = f"{display_tag_name} ({count_str})"

                item = QListWidgetItem(display_text)
                item.setData(Qt.ItemDataRole.UserRole, tag_dict)

                # 색상 설정 (우선순위: 즐겨찾기 > 원문 검색)
                if tag_name in self.starred_keys:
                    item.setForeground(QBrush(QColor("#FFD700")))
                elif matched_in_wiki:
                    # 원문 검색으로 찾은 태그: 연회색
                    item.setForeground(QBrush(QColor(160, 160, 160)))

                self.level3_list.addItem(item)

        print(f"[Level 3] {len(display_tags)} 태그 표시")

    def _format_count(self, count: int) -> str:
        """카운트 포맷팅"""
        if count >= 1000:
            return f"{count / 1000:.1f}k"
        return str(count)

    def _show_all_category_tags(self):
        """카테고리의 모든 태그를 Level 3에 표시"""
        self.level3_list.clear()

        if not self.data or not self.current_category:
            return

        # 검색 모드일 때는 searched_tree 사용
        if self.is_searching and self.searched_tree:
            # searched_tree에서 현재 카테고리의 모든 태그 수집
            category_folders = self.searched_tree.get(self.current_category, {})
            all_tags = []
            for folder_tags in category_folders.values():
                all_tags.extend(folder_tags)
        else:
            # 일반 모드: General 또는 Species에서 카테고리 데이터 찾기
            category_data = None
            if "General" in self.data and self.current_category in self.data["General"]:
                category_data = self.data["General"][self.current_category]
            elif "Species" in self.data and self.current_category in self.data["Species"]:
                category_data = self.data["Species"][self.current_category]

            if not category_data:
                print(f"[Category Tags] 카테고리 데이터를 찾을 수 없음: {self.current_category}")
                return

            # 카테고리 내 모든 태그 수집
            all_tags = []
            for _, folder_data in category_data.items():
                self._collect_all_tags(folder_data, all_tags)

        # 즐겨찾기 모드인 경우 필터링
        if self.radio_starred and self.radio_starred.isChecked():
            all_tags = [t for t in all_tags if t.get("tag", "") in self.starred_keys]

        # count 기준 정렬
        all_tags.sort(key=lambda x: x.get("count", 0), reverse=True)

        # 리스트에 추가
        for tag_dict in all_tags:
            tag_name = tag_dict.get("tag", "")
            if tag_name and tag_name not in self.deleted_keys:
                count = tag_dict.get("count", 0)
                count_str = self._format_count(count)
                matched_in_wiki = tag_dict.get("matched_in_wiki", False)

                display_tag_name = tag_name.replace("_", " ")
                display_text = f"{display_tag_name} ({count_str})"

                item = QListWidgetItem(display_text)
                item.setData(Qt.ItemDataRole.UserRole, tag_dict)

                # 색상 설정 (우선순위: 즐겨찾기 > 원문 검색)
                if tag_name in self.starred_keys:
                    item.setForeground(QBrush(QColor("#FFD700")))
                elif matched_in_wiki:
                    # 원문 검색으로 찾은 태그: 연회색
                    item.setForeground(QBrush(QColor(160, 160, 160)))

                self.level3_list.addItem(item)

        print(f"[Category Tags] {self.current_category}: {len(all_tags)}개 태그 표시")

    def _collect_all_tags(self, data, tag_list: list):
        """재귀적으로 모든 태그 수집"""
        if isinstance(data, list):
            for tag_dict in data:
                if isinstance(tag_dict, dict):
                    tag_list.append(tag_dict)
            return

        if not isinstance(data, dict):
            return

        for key, value in data.items():
            if isinstance(value, list):
                for tag_dict in value:
                    if isinstance(tag_dict, dict):
                        tag_list.append(tag_dict)
            elif isinstance(value, dict):
                self._collect_all_tags(value, tag_list)

    def on_level3_clicked(self, item: QListWidgetItem):
        """Level 3 태그 클릭"""
        tag_data = item.data(Qt.ItemDataRole.UserRole)

        if not tag_data:
            return

        tag_name = tag_data.get("tag", "")
        print(f"[Tag] {tag_name} 선택")

        # Wiki 정보 표시
        self._display_wiki(tag_data)

        # 스타 버튼 상태 업데이트
        self.update_star_button_state(tag_name)

    def _display_wiki(self, tag_data: dict):
        """Wiki 정보 표시 및 번역"""
        if not tag_data:
            self.wiki_body_edit.clear()
            return

        tag_name = tag_data.get("tag", "")
        tag_count = tag_data.get("count", "")
        wiki_body = tag_data.get("wiki_body", "")
        wiki_preview = tag_data.get("wiki_preview", "")

        # Wiki 텍스트 구성 (언더바 제거)
        display_tag_name = tag_name.replace("_", " ")
        wiki_text = f"Tag: {display_tag_name}\n"
        wiki_text += f"Count: {self._format_count(tag_count)}\n"
        wiki_text += f"\n{'='*50}\n\n"

        if wiki_body:
            wiki_text += self._clean_wiki_text(wiki_body)
        elif wiki_preview:
            wiki_text += self._clean_wiki_text(wiki_preview)
        else:
            wiki_text += "위키 정보 없음"

        # 원문 먼저 표시
        self.wiki_body_edit.setPlainText(wiki_text)
        self.original_wiki_text = wiki_text

        # 현재 wiki 정보 저장 (재번역용)
        self.current_wiki_text = wiki_text
        self.current_display_tag_name = display_tag_name
        self.current_tag_count = tag_count

        # 번역 요청 해시 생성 (태그 변경 시점에 생성하여 경쟁 조건 방지)
        import hashlib
        request_hash = hashlib.md5(f"{tag_name}_{tag_count}".encode()).hexdigest()
        self.current_translation_hash = request_hash

        # 지연 번역 시작 (display_tag_name 전달)
        QTimer.singleShot(300, lambda: self._start_wiki_translation(wiki_text, display_tag_name, tag_count, request_hash))

    def _clean_wiki_text(self, text: str) -> str:
        """Wiki 텍스트 정제"""
        import re

        text = re.sub(r'thumb\s+#\d+', '', text)
        text = re.sub(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]', r'\1', text)
        text = re.sub(r'"([^"]+)":https?://[^\s]+', r'\1', text)
        text = re.sub(r'\[b\](.*?)\[/b\]', r'\1', text)
        text = re.sub(r'\[i\](.*?)\[/i\]', r'\1', text)
        text = re.sub(r'\[u\](.*?)\[/u\]', r'\1', text)
        text = re.sub(r'\[s\](.*?)\[/s\]', r'\1', text)
        text = re.sub(r'\[section=([^\]]+)\]', r'【\1】', text)
        text = re.sub(r'\[/section\]', '', text)
        text = re.sub(r'\[expand\]', '', text)
        text = re.sub(r'\[/expand\]', '', text)
        text = re.sub(r'h(\d+)\.\s*', r'\n\1. ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = text.strip()

        return text

    def _start_wiki_translation(self, wiki_text: str, display_tag_name: str, tag_count, request_hash: str):
        """Wiki 텍스트 번역 시작"""
        # 번역 비활성화 체크
        if self.disable_translation:
            return

        # 해시 검증: 이미 다른 태그가 선택되었으면 취소
        if request_hash != self.current_translation_hash:
            print(f"[Wiki Translation] 번역 시작 취소 (태그 이미 변경됨)")
            return

        if self.is_translating:
            return

        header = f"Tag: {display_tag_name}\nCount: {self._format_count(tag_count)}\n\n{'='*50}\n\n"

        body_start = wiki_text.find('='*50) + 52
        if body_start < 52:
            return

        body_text = wiki_text[body_start:]
        translatable_text = self._extract_translatable_text(body_text)

        if not translatable_text or translatable_text == "위키 정보 없음":
            return

        self.is_translating = True

        # 이미 실행 중인 번역 워커가 있으면 종료
        if self.translation_worker and self.translation_worker.isRunning():
            self.translation_worker.quit()
            self.translation_worker.wait()

        self.translation_worker = WikiTranslationWorker(request_hash)
        self.translation_worker.translation_completed.connect(
            lambda req_hash, orig, trans: self._on_translation_completed(req_hash, orig, trans, header)
        )
        self.translation_worker.translation_failed.connect(self._on_translation_failed)
        self.translation_worker.set_text(translatable_text)
        self.translation_worker.start()

    def _extract_translatable_text(self, text: str) -> str:
        """번역 가능한 텍스트 추출"""
        import re

        patterns = [
            r'\r?\n\r?\nh[1-6]\.?\s',
            r'\r?\n\*\s',
            r'\r?\n-\s',
            r'\r?\n\d+\.\s',
            r'<[^>]+>',
            r'\[.*?\]\(.*?\)',
        ]

        earliest_pos = len(text)
        for pattern in patterns:
            match = re.search(pattern, text)
            if match and match.start() < earliest_pos:
                earliest_pos = match.start()

        if earliest_pos < len(text):
            return text[:earliest_pos].strip()

        return text.strip()

    def _on_translation_completed(self, request_hash: str, original_text: str, translated_text: str, header: str):
        """번역 완료"""
        self.is_translating = False

        # 해시 검증: 현재 선택된 태그의 번역 요청이 아니면 무시하고 현재 페이지 재번역
        if request_hash != self.current_translation_hash:
            print(f"[Wiki Translation] 이전 번역 결과 무시 (hash mismatch) - 현재 페이지 재번역 시작")
            if self.translation_worker:
                self.translation_worker.deleteLater()
                self.translation_worker = None

            # 현재 선택된 태그 재번역 (지연 없이 즉시 시작)
            if self.current_wiki_text and self.current_translation_hash:
                self._start_wiki_translation(
                    self.current_wiki_text,
                    self.current_display_tag_name,
                    self.current_tag_count,
                    self.current_translation_hash
                )
            return

        body_start = self.original_wiki_text.find('='*50) + 52
        if body_start < 52:
            return

        body_text = self.original_wiki_text[body_start:]
        remaining_text = body_text[len(original_text):].strip() if len(original_text) < len(body_text) else ""

        translated_wiki = header + translated_text
        if remaining_text:
            translated_wiki += f"\n\n{remaining_text}"

        self.wiki_body_edit.setPlainText(translated_wiki)

        if self.translation_worker:
            self.translation_worker.deleteLater()
            self.translation_worker = None

    def _on_translation_failed(self, request_hash: str):
        """번역 실패"""
        self.is_translating = False

        # 해시 검증: 현재 선택된 태그의 번역 요청이 아니면 무시하고 현재 페이지 재번역
        if request_hash != self.current_translation_hash:
            print(f"[Wiki Translation] 이전 번역 실패 무시 (hash mismatch) - 현재 페이지 재번역 시작")
            if self.translation_worker:
                self.translation_worker.deleteLater()
                self.translation_worker = None

            # 현재 선택된 태그 재번역 (지연 없이 즉시 시작)
            if self.current_wiki_text and self.current_translation_hash:
                self._start_wiki_translation(
                    self.current_wiki_text,
                    self.current_display_tag_name,
                    self.current_tag_count,
                    self.current_translation_hash
                )
            return

        print("[Wiki Translation] 번역 실패 - 원문 유지")

        if self.translation_worker:
            self.translation_worker.deleteLater()
            self.translation_worker = None

    # ===== 검색 기능 =====

    def on_search(self):
        """검색 (전체 카테고리 검색, 매칭된 태그를 Level 3에 나열)"""
        search_text = self.search_input.text().strip().lower()

        if not search_text:
            self.on_reset()
            return

        if not self.data:
            print("[Search] 데이터가 로드되지 않았습니다")
            return

        print(f"[Search] '{search_text}' 전체 검색 중...")

        # searched_tree 구축: {category: {folder: [tag_dicts]}}
        self.searched_tree = {}
        matched_categories = {}  # {category_name: [tag_dicts]}
        all_matched_tags = []  # 모든 매칭된 태그 (중복 제거용)
        seen_tags = set()

        # General과 Species 카테고리 모두 검색
        all_categories = {}
        if "General" in self.data:
            all_categories.update(self.data["General"])
        if "Species" in self.data:
            all_categories.update(self.data["Species"])

        for category_name, category_data in all_categories.items():
            if not isinstance(category_data, dict):
                continue

            category_folders = {}  # {folder_name: [tag_dicts]}
            category_matched_tags = []

            # 카테고리 내 모든 폴더 검색
            for folder_name, folder_data in category_data.items():
                all_tags = []
                self._collect_all_tags(folder_data, all_tags)

                folder_matched_tags = []
                for tag_dict in all_tags:
                    tag_name = tag_dict.get("tag", "")
                    matched_in_tag = search_text in tag_name.lower()
                    matched_in_wiki = False

                    # 원문 검색이 활성화되어 있으면 wiki에서도 검색
                    if not self.disable_wiki_search and not matched_in_tag:
                        wiki_body = tag_dict.get("wiki_body", "").lower()
                        wiki_preview = tag_dict.get("wiki_preview", "").lower()
                        if search_text in wiki_body or search_text in wiki_preview:
                            matched_in_wiki = True

                    # 태그명 또는 원문에서 매칭된 경우
                    if matched_in_tag or matched_in_wiki:
                        # 매칭 정보를 태그에 추가
                        tag_with_match_info = tag_dict.copy()
                        tag_with_match_info['matched_in_wiki'] = matched_in_wiki
                        folder_matched_tags.append(tag_with_match_info)

                        # 전체 결과용 (중복 제거)
                        if tag_name not in seen_tags:
                            category_matched_tags.append(tag_with_match_info)
                            all_matched_tags.append(tag_with_match_info)
                            seen_tags.add(tag_name)

                # 이 폴더에 매칭된 태그가 있으면 추가
                if folder_matched_tags:
                    category_folders[folder_name] = folder_matched_tags

            # 이 카테고리에 매칭된 태그가 있으면 추가
            if category_folders:
                self.searched_tree[category_name] = category_folders
                matched_categories[category_name] = category_matched_tags

        # 검색 결과가 있으면
        if matched_categories:
            self.is_searching = True

            # 카테고리 버튼 강조 (연두색)
            self._highlight_matched_categories(matched_categories.keys())

            # Level 2 리스트는 비우기
            self.level2_list.clear()
            self.current_level2 = None

            # Level 3 리스트에 모든 매칭된 태그 표시 (최초 검색 시)
            self.level3_list.clear()
            for tag_dict in all_matched_tags:
                tag_name = tag_dict.get("tag", "")
                count = tag_dict.get("count", 0)
                matched_in_wiki = tag_dict.get("matched_in_wiki", False)

                # 즐겨찾기/삭제 체크
                is_starred = tag_name in self.starred_keys
                is_deleted = tag_name in self.deleted_keys

                display_text = f"{tag_name} ({self._format_count(count)})"
                if is_starred:
                    display_text = "⭐ " + display_text

                item = QListWidgetItem(display_text)

                # 색상 설정
                if is_deleted:
                    item.setForeground(QBrush(QColor(100, 100, 100)))
                elif is_starred:
                    item.setForeground(QBrush(QColor(255, 215, 0)))
                elif matched_in_wiki:
                    # 원문 검색으로 찾은 태그: 연회색
                    item.setForeground(QBrush(QColor(160, 160, 160)))

                item.setData(Qt.ItemDataRole.UserRole, tag_dict)
                self.level3_list.addItem(item)

            print(f"[Search] 완료: {len(matched_categories)}개 카테고리, {len(self.searched_tree)}개 카테고리, {len(all_matched_tags)}개 태그")

        else:
            print(f"[Search] 결과 없음")
            self.searched_tree = {}
            self.level3_list.clear()

    def _highlight_matched_categories(self, matched_category_names):
        """매칭된 카테고리 버튼을 연두색으로 강조"""
        highlight_color = "#90EE90"  # 연두색 (Light Green)

        for category_name, button in self.category_buttons.items():
            if category_name in matched_category_names:
                # 매칭된 카테고리: 연두색 배경 (원래 스타일 유지)
                button.setStyleSheet(f"""
                    QPushButton {{
                        font-size: {get_scaled_font_size(18)}px;
                        background-color: {highlight_color};
                        color: #000000;
                        border: 2px solid {highlight_color};
                        border-radius: {get_scaled_size(5)}px;
                        padding: {get_scaled_size(8)}px;
                        text-align: left;
                        min-height: {get_scaled_size(35)}px;
                    }}
                    QPushButton:hover {{
                        background-color: #7CFC00;
                        border-color: #7CFC00;
                    }}
                    QPushButton:checked {{
                        background-color: #32CD32;
                        border-color: #32CD32;
                        color: #FFFFFF;
                        font-weight: bold;
                    }}
                """)
            else:
                # 매칭되지 않은 카테고리: 원래 기본 스타일
                button.setStyleSheet(f"""
                    QPushButton {{
                        font-size: {get_scaled_font_size(18)}px;
                        background-color: {DARK_COLORS['bg_tertiary']};
                        color: {DARK_COLORS['text_primary']};
                        border: 2px solid {DARK_COLORS['border']};
                        border-radius: {get_scaled_size(5)}px;
                        padding: {get_scaled_size(8)}px;
                        text-align: left;
                        min-height: {get_scaled_size(35)}px;
                    }}
                    QPushButton:hover {{
                        background-color: {DARK_COLORS['bg_hover']};
                        border-color: {DARK_COLORS['accent_blue']};
                    }}
                    QPushButton:checked {{
                        background-color: {DARK_COLORS['accent_blue']};
                        color: white;
                        border-color: {DARK_COLORS['accent_blue']};
                        font-weight: bold;
                    }}
                """)

    def _reset_category_button_styles(self):
        """카테고리 버튼 스타일을 기본으로 복원"""
        for button in self.category_buttons.values():
            button.setStyleSheet(f"""
                QPushButton {{
                    font-size: {get_scaled_font_size(18)}px;
                    background-color: {DARK_COLORS['bg_tertiary']};
                    color: {DARK_COLORS['text_primary']};
                    border: 2px solid {DARK_COLORS['border']};
                    border-radius: {get_scaled_size(5)}px;
                    padding: {get_scaled_size(8)}px;
                    text-align: left;
                    min-height: {get_scaled_size(35)}px;
                }}
                QPushButton:hover {{
                    background-color: {DARK_COLORS['bg_hover']};
                    border-color: {DARK_COLORS['accent_blue']};
                }}
                QPushButton:checked {{
                    background-color: {DARK_COLORS['accent_blue']};
                    color: white;
                    border-color: {DARK_COLORS['accent_blue']};
                    font-weight: bold;
                }}
            """)

    def on_reset(self):
        """초기화"""
        self.current_category = None
        self.current_level2 = None
        self.current_level3 = None
        self.is_searching = False
        self.filtered_level2 = []
        self.filtered_level3 = []
        self.searched_tree = {}  # 검색 트리 초기화

        # 카테고리 버튼 스타일 복원
        self._reset_category_button_styles()

        # UI 초기화
        if self.category_button_group.checkedButton():
            self.category_button_group.setExclusive(False)
            self.category_button_group.checkedButton().setChecked(False)
            self.category_button_group.setExclusive(True)

        self.level2_list.clear()
        self.level3_list.clear()
        self.wiki_body_edit.clear()
        self.search_input.clear()

        print("[Reset] 초기화 완료")

    # ===== 생성/관리 기능 =====

    # ===== 미사용 함수 (V1 호환용) =====

    # def process_tags(self, tags_text: str, auto_hide_text: str) -> str:
    #     """태그 처리 로직 (V1과 동일) - 현재 미사용"""
    #     pass

    def on_next_clicked(self):
        """다음 버튼: Level 3 리스트에서 다음 아이템 선택"""
        selected_items = self.level3_list.selectedItems()
        if not selected_items:
            # 선택된 항목이 없으면 첫 번째 항목 선택
            if self.level3_list.count() > 0:
                self.level3_list.setCurrentRow(0)
                first_item = self.level3_list.item(0)
                if first_item:
                    self.on_level3_clicked(first_item)
            else:
                QMessageBox.information(self.widget, "알림", "표시된 태그가 없습니다.")
            return

        # 현재 선택된 항목의 row 찾기
        current_item = selected_items[0]
        current_row = self.level3_list.row(current_item)

        # 다음 항목으로 이동
        next_row = current_row + 1
        if next_row < self.level3_list.count():
            self.level3_list.setCurrentRow(next_row)
            next_item = self.level3_list.item(next_row)
            if next_item:
                self.on_level3_clicked(next_item)
        else:
            # 마지막 항목이면 첫 번째로 순환
            self.level3_list.setCurrentRow(0)
            first_item = self.level3_list.item(0)
            if first_item:
                self.on_level3_clicked(first_item)

    def _on_translation_checkbox_changed(self, state):
        """번역 비활성화 체크박스 상태 변경"""
        self.disable_translation = (state == Qt.CheckState.Checked.value)
        print(f"[Translation] 자동 번역: {'비활성화' if self.disable_translation else '활성화'}")
        self.save_settings()

    def _on_wiki_search_checkbox_changed(self, state):
        """원문 검색 비활성화 체크박스 상태 변경"""
        self.disable_wiki_search = (state == Qt.CheckState.Checked.value)
        print(f"[Wiki Search] 원문 검색: {'비활성화' if self.disable_wiki_search else '활성화'}")
        self.save_settings()

    def on_generate_clicked(self):
        """생성 버튼: 관련 태그로 이미지 생성"""
        # 관련 태그 텍스트 가져오기
        related_tags_text = self.related_tags_edit.toPlainText().strip()

        if not related_tags_text:
            QMessageBox.information(self.widget, "알림", "관련 태그를 입력해주세요.")
            return

        # 태그 처리 (쉼표로 분리)
        tags = [tag.strip() for tag in related_tags_text.split(',') if tag.strip()]

        # 생성 파라미터 구성
        tags_data = {
            'id': 10000000,
            'artist': [],
            'copyright': [],
            'character': [],
            'general': tags,
            'meta': []
        }

        # 시그널 발송
        self.signals.generation_requested.emit(tags_data)

        print(f"[Generate] 이미지 생성 요청: {len(tags)}개 태그")

    def on_star_clicked(self):
        """즐겨찾기 토글"""
        selected_items = self.level3_list.selectedItems()
        if not selected_items:
            QMessageBox.information(self.widget, "알림", "태그를 선택해주세요.")
            return

        tag_data = selected_items[0].data(Qt.ItemDataRole.UserRole)
        tag_name = tag_data.get("tag", "")

        if tag_name in self.starred_keys:
            self.starred_keys.discard(tag_name)
            print(f"[OK] 즐겨찾기 해제: {tag_name}")
        else:
            self.starred_keys.add(tag_name)
            print(f"[OK] 즐겨찾기 추가: {tag_name}")

        self.save_starred_keys()
        self.update_star_button_state(tag_name)
        self.update_level3_list()

        # 카테고리 라벨 업데이트 (즐겨찾기 표시 반영)
        self.update_category_starred_labels()

    def update_star_button_state(self, tag_name: str = None):
        """스타 버튼 상태 업데이트"""
        if tag_name is None:
            selected_items = self.level3_list.selectedItems()
            if selected_items:
                tag_data = selected_items[0].data(Qt.ItemDataRole.UserRole)
                tag_name = tag_data.get("tag", "")

        if tag_name and tag_name in self.starred_keys:
            self.star_button.setText("★")
        else:
            self.star_button.setText("☆")

    def on_hide_clicked(self):
        """숨김 처리"""
        selected_items = self.level3_list.selectedItems()
        if not selected_items:
            QMessageBox.information(self.widget, "알림", "태그를 선택해주세요.")
            return

        tag_data = selected_items[0].data(Qt.ItemDataRole.UserRole)
        tag_name = tag_data.get("tag", "")

        self.deleted_keys.add(tag_name)
        self.save_deleted_keys()

        self.update_level3_list()
        print(f"[OK] 숨김 처리: {tag_name}")

    def on_manage_clicked(self):
        """숨긴 항목 관리"""
        if not self.deleted_keys:
            QMessageBox.information(self.widget, "알림", "숨긴 항목이 없습니다.")
            return

        dialog = HiddenItemsDialog(self.deleted_keys, self.widget)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            restored_keys = dialog.get_restored_keys()
            if restored_keys:
                self.restore_hidden_items(restored_keys)

    def restore_hidden_items(self, keys_to_restore: List[str]):
        """숨긴 항목 복원"""
        for key in keys_to_restore:
            self.deleted_keys.discard(key)

        self.save_deleted_keys()

        # 검색 상태 초기화
        if self.is_searching:
            self.is_searching = False
            self.filtered_level2 = []
            self.filtered_level3 = []
            self.search_input.clear()

        self.update_level3_list()
        print(f"[OK] {len(keys_to_restore)}개 항목 복원 완료")

    def on_view_mode_changed(self, checked: bool):
        """보기 모드 변경"""
        if checked:
            # 카테고리 버튼 상태 업데이트 (즐겨찾기가 없는 카테고리는 비활성화)
            if self.radio_starred.isChecked():
                self.update_category_buttons_for_starred_mode()
            else:
                self.enable_all_category_buttons()

            # Level 2 업데이트 (현재 카테고리가 선택되어 있으면)
            if self.current_category:
                self.update_level2_list()

            # Level 3 업데이트 (현재 Level 2가 선택되어 있으면)
            if self.current_level2:
                self.update_level3_list()

    def update_category_buttons_for_starred_mode(self):
        """즐겨찾기 모드: 즐겨찾기가 없는 카테고리 버튼 비활성화"""
        if not self.data or not self.category_button_group:
            return

        general_data = self.data.get("General", {})

        for button in self.category_button_group.buttons():
            # 버튼 텍스트에서 ⭐ 제거하여 원래 카테고리 이름 가져오기
            category_name = button.text().replace(" ⭐", "")
            category_data = general_data.get(category_name, {})

            # 이 카테고리에 즐겨찾기 태그가 있는지 확인
            has_starred = self._category_has_starred_tags(category_data)
            button.setEnabled(has_starred)

            # 현재 선택된 카테고리가 비활성화되면 선택 해제
            if button.isChecked() and not has_starred:
                button.setChecked(False)
                self.current_category = None
                self.current_level2 = None
                self.current_level3 = None
                self.level2_list.clear()
                self.level3_list.clear()
                self.wiki_body_edit.clear()

    def enable_all_category_buttons(self):
        """기본 모드: 모든 카테고리 버튼 활성화"""
        if not self.category_button_group:
            return

        for button in self.category_button_group.buttons():
            button.setEnabled(True)

    def _category_has_starred_tags(self, category_data: dict) -> bool:
        """카테고리에 즐겨찾기 태그가 있는지 확인"""
        if not isinstance(category_data, dict):
            return False

        for _, folder_data in category_data.items():
            temp_tags = []
            self._collect_all_tags(folder_data, temp_tags)
            if any(t.get("tag", "") in self.starred_keys for t in temp_tags):
                return True

        return False

    def update_category_starred_labels(self):
        """카테고리 버튼에 즐겨찾기 표시 업데이트"""
        if not self.data or not self.category_button_group:
            return

        general_data = self.data.get("General", {})

        for button in self.category_button_group.buttons():
            # 현재 버튼 텍스트에서 ⭐ 제거하여 원래 카테고리 이름 가져오기
            category_name = button.text().replace(" ⭐", "")
            category_data = general_data.get(category_name, {})

            # 이 카테고리에 즐겨찾기 태그가 있는지 확인
            has_starred = self._category_has_starred_tags(category_data)

            # 버튼 텍스트 업데이트 (즐겨찾기가 있으면 ⭐ 추가)
            if has_starred:
                new_text = f"{category_name} ⭐"
            else:
                new_text = category_name

            # 텍스트가 변경되었을 때만 업데이트
            if button.text() != new_text:
                button.setText(new_text)

    def cleanup(self):
        """모듈 종료 시 리소스 정리"""
        print("[E621EventModuleV2] 리소스 정리 중...")

        if self.translation_worker and self.translation_worker.isRunning():
            self.translation_worker.quit()
            self.translation_worker.wait(1000)
            self.translation_worker.deleteLater()

        self.save_settings()


class HiddenItemsDialog(QDialog):
    """숨긴 항목 관리 다이얼로그"""

    def __init__(self, deleted_keys: set, parent=None):
        super().__init__(parent)
        self.deleted_keys = deleted_keys
        self.restored_keys = []

        self.setWindowTitle("숨긴 항목 관리")
        self.setMinimumSize(get_scaled_size(500), get_scaled_size(400))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

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

        # 리스트 위젯
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                font-size: {get_scaled_font_size(16)}px;
            }}
            QListWidget::item {{
                padding: {get_scaled_size(8)}px;
            }}
            QListWidget::item:selected {{
                background-color: {DARK_COLORS['highlight']};
            }}
        """)
        layout.addWidget(self.list_widget)

        # 버튼
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

        self.setStyleSheet(f"QDialog {{ background-color: {DARK_COLORS['bg_primary']}; }}")

    def load_hidden_items(self):
        """숨긴 항목 목록 표시"""
        try:
            # 삭제된 키 목록을 정렬하여 표시
            for key in sorted(self.deleted_keys):
                item = QListWidgetItem(key)
                item.setData(Qt.ItemDataRole.UserRole, key)
                self.list_widget.addItem(item)

        except Exception as e:
            print(f"[ERROR] 숨긴 항목 로드 실패: {e}")

    def on_restore(self):
        """복원 버튼 클릭"""
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "알림", "복원할 항목을 선택해주세요.")
            return

        self.restored_keys = [selected_items[0].data(Qt.ItemDataRole.UserRole)]
        self.accept()

    def get_restored_keys(self) -> List[str]:
        """복원할 키 목록 반환"""
        return self.restored_keys
