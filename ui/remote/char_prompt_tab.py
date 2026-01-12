# ui/remote/char_prompt_tab.py
"""
캐릭터 프롬프트 탭 Mixin - RemoteWindow용

CharacterPromptFavoriteItemWidget: 캐릭터 프롬프트 즐겨찾기 아이템 위젯
CharPromptTabMixin: 캐릭터 프롬프트 탭 관련 메서드 모음
"""

import json
from pathlib import Path
import pandas as pd
from PIL import Image
from PIL.ImageQt import ImageQt

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTabWidget, QLabel, QComboBox, QTextEdit, QPushButton,
    QScrollArea, QFrame, QMessageBox, QApplication,
    QCheckBox, QLineEdit, QDialog, QInputDialog,
    QRadioButton, QButtonGroup
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QImage

from ui.theme import DARK_COLORS, DARK_STYLES
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from modules.character_module import CharacterSearchDialog


# 캐릭터 프롬프트 즐겨찾기 상수
CHAR_PROMPT_FAVORITES_DIR = Path("save/character_prompt_favorites")
CHAR_PROMPT_FAVORITES_JSON = Path("save/character_prompt_favorites/favorites.json")
CHAR_PROMPT_FOLDERS_JSON = Path("save/character_prompt_favorites/folders.json")

# 즐겨찾기 그리드 썸네일 - 한 줄에 4개 배치
CHAR_PROMPT_THUMB_WIDTH = 144
CHAR_PROMPT_THUMB_HEIGHT = 200  # 368:512 비율 유지

# 즐겨찾기 관리 탭용 더 큰 썸네일
CHAR_PROMPT_MANAGE_THUMB_WIDTH = 150
CHAR_PROMPT_MANAGE_THUMB_HEIGHT = 208


class CharacterPromptFavoriteItemWidget(QFrame):
    """캐릭터 프롬프트 즐겨찾기 아이템 위젯 (상단 썸네일 + 하단 텍스트)"""

    clicked = pyqtSignal(dict)  # favorite_data

    def __init__(self, favorite_data: dict, thumbnail_path: Path = None,
                 thumb_width: int = None, thumb_height: int = None,
                 is_selected: bool = False, parent=None):
        super().__init__(parent)
        self.favorite_data = favorite_data
        self.thumbnail_path = thumbnail_path
        self._is_selected = is_selected

        # 동적 크기 설정 (기본값 사용 가능)
        self.thumb_width = thumb_width or CHAR_PROMPT_THUMB_WIDTH
        self.thumb_height = thumb_height or CHAR_PROMPT_THUMB_HEIGHT

        self.setFixedSize(self.thumb_width + 10, self.thumb_height + 35)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_style()

        self._init_ui()

    def _update_style(self):
        """선택 상태에 따른 스타일 업데이트"""
        if self._is_selected:
            self.setStyleSheet(f"""
                QFrame {{
                    background-color: {DARK_COLORS['bg_tertiary']};
                    border: 2px solid {DARK_COLORS['success']};
                    border-radius: 6px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QFrame {{
                    background-color: {DARK_COLORS['bg_tertiary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: 6px;
                }}
                QFrame:hover {{
                    border: 2px solid {DARK_COLORS['accent_blue']};
                    background-color: {DARK_COLORS['bg_secondary']};
                }}
            """)

    def set_selected(self, selected: bool):
        """선택 상태 변경"""
        self._is_selected = selected
        self._update_style()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)

        # 썸네일 이미지
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(self.thumb_width, self.thumb_height)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_primary']};
                border-radius: 4px;
            }}
        """)

        if self.thumbnail_path and self.thumbnail_path.exists():
            pixmap = QPixmap(str(self.thumbnail_path))
            scaled = pixmap.scaled(
                self.thumb_width, self.thumb_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.thumb_label.setPixmap(scaled)
        else:
            self.thumb_label.setText("👤")
            self.thumb_label.setStyleSheet(f"""
                QLabel {{
                    background-color: {DARK_COLORS['bg_primary']};
                    border-radius: 4px;
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(24)}px;
                }}
            """)

        layout.addWidget(self.thumb_label)

        # 캐릭터 이름 (하단 텍스트)
        char_name = self.favorite_data.get("name", "이름 없음")
        name_label = QLabel(char_name)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setWordWrap(True)
        name_label.setMaximumHeight(28)
        name_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(12)}px;
                background-color: transparent;
                border: none;
            }}
        """)
        layout.addWidget(name_label)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.favorite_data)
        super().mousePressEvent(event)


class CharPromptTabMixin:
    """캐릭터 프롬프트 탭 Mixin - RemoteWindow와 함께 상속

    필요한 속성 (RemoteWindow에서 정의):
    - self.character_module: 캐릭터 모듈 참조
    - self.parent_app: 부모 앱 참조
    - self._show_warning(title, message): 경고 메시지 표시
    - self._show_question(title, message): 질문 다이얼로그
    - self._get_text_input(title, prompt): 텍스트 입력 다이얼로그
    - self._style_dialog(dialog): 다이얼로그 스타일 적용
    """

    def _init_char_prompt_data(self):
        """캐릭터 프롬프트 데이터 초기화 - RemoteWindow.__init__에서 호출"""
        # 캐릭터 프롬프트 탭 데이터
        self.char_prompt_favorites = []
        self.char_prompt_folders = ["기본"]
        self.char_prompt_current_folder = "기본"
        self.char_prompt_person_count = 1
        self.char_prompt_selected_slot = 1  # 1-based
        self._char_prompt_selected_fav = None
        self._pending_thumb_image = None

        # 즐겨찾기 로드
        self._load_char_prompt_favorites()

    def _create_char_prompt_subtab(self, parent_tabs: QTabWidget):
        """캐릭터 프롬프트 서브탭 - 인원 수 설정 + 캐릭터 슬롯 + 즐겨찾기"""
        prompt_widget = QWidget()
        prompt_layout = QVBoxLayout(prompt_widget)
        prompt_layout.setContentsMargins(8, 8, 8, 8)
        prompt_layout.setSpacing(8)

        if not self.character_module:
            placeholder = QLabel("캐릭터 모듈을 찾을 수 없습니다.")
            placeholder.setStyleSheet(f"color: {DARK_COLORS['text_disabled']};")
            prompt_layout.addWidget(placeholder)
            parent_tabs.addTab(prompt_widget, "👤 프롬프트")
            return

        # === 상단: activate/reroll 체크박스 미러 버튼 ===
        options_frame = QFrame()
        options_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 6px;
            }}
        """)
        options_layout = QHBoxLayout(options_frame)
        options_layout.setContentsMargins(8, 6, 8, 6)
        options_layout.setSpacing(12)

        # 활성화 체크박스
        self.char_prompt_activate_check = QCheckBox("캐릭터 프롬프트 활성화")
        self.char_prompt_activate_check.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.char_prompt_activate_check.stateChanged.connect(self._on_char_prompt_activate_changed)
        options_layout.addWidget(self.char_prompt_activate_check)

        # 생성 시 리롤 체크박스
        self.char_prompt_reroll_check = QCheckBox("생성 시 와일드카드 개봉")
        self.char_prompt_reroll_check.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.char_prompt_reroll_check.stateChanged.connect(self._on_char_prompt_reroll_changed)
        options_layout.addWidget(self.char_prompt_reroll_check)

        options_layout.addStretch()
        prompt_layout.addWidget(options_frame)

        # === 인원 수 설정 섹션 ===
        person_frame = QFrame()
        person_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 6px;
            }}
        """)
        person_layout = QHBoxLayout(person_frame)
        person_layout.setContentsMargins(8, 6, 8, 6)
        person_layout.setSpacing(8)

        person_label = QLabel("인원 수 설정:")
        person_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(15)}px;
            }}
        """)
        person_layout.addWidget(person_label)

        # 라디오 버튼 그룹 (1-6)
        self.char_prompt_person_group = QButtonGroup(self)
        self.char_prompt_person_radios = []

        for i in range(1, 7):
            radio = QRadioButton(str(i))
            radio.setStyleSheet(f"""
                QRadioButton {{
                    color: {DARK_COLORS['text_primary']};
                    font-size: {get_scaled_font_size(15)}px;
                    spacing: 4px;
                }}
                QRadioButton::indicator {{
                    width: 16px;
                    height: 16px;
                }}
            """)
            if i == 1:
                radio.setChecked(True)
            self.char_prompt_person_group.addButton(radio, i)
            self.char_prompt_person_radios.append(radio)
            person_layout.addWidget(radio)

        self.char_prompt_person_group.idClicked.connect(self._on_char_prompt_person_changed)
        person_layout.addStretch()
        prompt_layout.addWidget(person_frame)

        # === 구분선 ===
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        separator.setFixedHeight(1)
        prompt_layout.addWidget(separator)

        # === 활성 캐릭터 프롬프트 섹션 ===
        slots_label = QLabel("활성 캐릭터 프롬프트 (선택 후 즐겨찾기 클릭)")
        slots_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(12)}px;
            }}
        """)
        prompt_layout.addWidget(slots_label)

        # 캐릭터 슬롯 프레임들 (C1-C6)
        self.char_prompt_slot_frames = []
        self.char_prompt_slot_edits = []

        for i in range(6):
            slot_frame = QFrame()
            slot_frame.setProperty("slot_index", i)
            slot_frame.setCursor(Qt.CursorShape.PointingHandCursor)
            slot_frame.mousePressEvent = lambda event, idx=i: self._on_char_prompt_slot_clicked(idx)
            self._update_slot_frame_style(slot_frame, i == 0)  # 첫 번째 선택

            slot_layout = QHBoxLayout(slot_frame)
            slot_layout.setContentsMargins(8, 4, 8, 4)
            slot_layout.setSpacing(8)

            # C 라벨
            c_label = QLabel(f"C{i+1}")
            c_label.setFixedWidth(30)
            c_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_primary']};
                    font-size: {get_scaled_font_size(16)}px;
                    font-weight: bold;
                    background: transparent;
                    border: none;
                }}
            """)
            slot_layout.addWidget(c_label)

            # 프롬프트 표시 (읽기 전용)
            slot_edit = QLineEdit()
            slot_edit.setReadOnly(True)
            slot_edit.setPlaceholderText("(비어 있음)")
            slot_edit.setCursor(Qt.CursorShape.PointingHandCursor)
            slot_edit.setStyleSheet(f"""
                QLineEdit {{
                    background-color: {DARK_COLORS['bg_primary']};
                    color: {DARK_COLORS['text_primary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: 4px;
                    padding: 4px 8px;
                    font-size: {get_scaled_font_size(16)}px;
                }}
            """)
            # QLineEdit 클릭 시 슬롯 선택
            slot_edit.mousePressEvent = lambda event, idx=i: self._on_char_prompt_slot_clicked(idx)
            slot_layout.addWidget(slot_edit, 1)

            # 수정 버튼
            edit_btn = QPushButton("수정")
            edit_btn.setFixedWidth(80)
            edit_btn.setStyleSheet(DARK_STYLES['secondary_button'])
            edit_btn.clicked.connect(lambda checked, idx=i: self._on_char_prompt_slot_edit(idx))
            slot_layout.addWidget(edit_btn)

            self.char_prompt_slot_frames.append(slot_frame)
            self.char_prompt_slot_edits.append(slot_edit)
            prompt_layout.addWidget(slot_frame)

            # 초기에는 첫 번째만 표시
            if i > 0:
                slot_frame.setVisible(False)

        # === 하단: 즐겨찾기 탭뷰 ===
        favorites_tabs = QTabWidget()
        favorites_tabs.setStyleSheet(DARK_STYLES['dark_tabs'])

        # 즐겨찾기 탭
        fav_widget = self._create_char_prompt_favorites_tab()
        favorites_tabs.addTab(fav_widget, "⭐ 즐겨찾기")

        # 즐겨찾기 관리 탭
        manage_widget = self._create_char_prompt_manage_tab()
        favorites_tabs.addTab(manage_widget, "⚙️ 즐겨찾기 관리")

        prompt_layout.addWidget(favorites_tabs, 1)

        parent_tabs.addTab(prompt_widget, "👤 프롬프트")

        # 초기 동기화
        QTimer.singleShot(100, self._sync_char_prompt_from_module)

    def _update_slot_frame_style(self, frame: QFrame, is_selected: bool):
        """슬롯 프레임 스타일 업데이트"""
        if is_selected:
            frame.setStyleSheet(f"""
                QFrame {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    border: 2px solid {DARK_COLORS['accent_blue']};
                    border-radius: 6px;
                }}
            """)
        else:
            frame.setStyleSheet(f"""
                QFrame {{
                    background-color: {DARK_COLORS['bg_tertiary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: 6px;
                }}
                QFrame:hover {{
                    border-color: {DARK_COLORS['border_light']};
                }}
            """)

    def _create_char_prompt_favorites_tab(self) -> QWidget:
        """캐릭터 프롬프트 즐겨찾기 탭"""
        fav_widget = QWidget()
        fav_layout = QVBoxLayout(fav_widget)
        fav_layout.setContentsMargins(4, 4, 4, 4)
        fav_layout.setSpacing(4)

        # 폴더 선택 + 추가/관리 버튼
        folder_row = QHBoxLayout()
        folder_row.setSpacing(6)

        folder_label = QLabel("폴더:")
        folder_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']};")
        folder_row.addWidget(folder_label)

        self.char_prompt_folder_combo = QComboBox()
        self.char_prompt_folder_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.char_prompt_folder_combo.addItems(self.char_prompt_folders)
        self.char_prompt_folder_combo.currentTextChanged.connect(self._on_char_prompt_folder_changed)
        folder_row.addWidget(self.char_prompt_folder_combo, 1)

        add_folder_btn = QPushButton("폴더 추가")
        add_folder_btn.setFixedWidth(100)
        add_folder_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        add_folder_btn.setToolTip("새 폴더 추가")
        add_folder_btn.clicked.connect(self._on_char_prompt_add_folder)
        folder_row.addWidget(add_folder_btn)

        delete_char_btn = QPushButton("캐릭터 삭제")
        delete_char_btn.setFixedWidth(100)
        delete_char_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        delete_char_btn.setToolTip("선택된 캐릭터 삭제")
        delete_char_btn.clicked.connect(self._on_char_prompt_delete_character)
        folder_row.addWidget(delete_char_btn)

        fav_layout.addLayout(folder_row)

        # 즐겨찾기 그리드 (스크롤 영역)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)

        self.char_prompt_favorites_container = QWidget()
        self.char_prompt_favorites_container.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")
        self.char_prompt_favorites_grid = QGridLayout(self.char_prompt_favorites_container)
        self.char_prompt_favorites_grid.setContentsMargins(4, 4, 4, 4)
        self.char_prompt_favorites_grid.setSpacing(6)
        scroll.setWidget(self.char_prompt_favorites_container)

        fav_layout.addWidget(scroll, 1)

        return fav_widget

    def _create_char_prompt_manage_tab(self) -> QWidget:
        """캐릭터 프롬프트 즐겨찾기 관리 탭"""
        manage_widget = QWidget()
        manage_layout = QVBoxLayout(manage_widget)
        manage_layout.setContentsMargins(8, 8, 8, 8)
        manage_layout.setSpacing(8)

        # === 상단 섹션: 썸네일 + 폴더/아이템 선택 ===
        top_section = QHBoxLayout()
        top_section.setSpacing(12)

        # 좌측: 큰 썸네일 영역
        self.char_prompt_manage_thumb = QLabel()
        self.char_prompt_manage_thumb.setFixedSize(
            CHAR_PROMPT_MANAGE_THUMB_WIDTH, CHAR_PROMPT_MANAGE_THUMB_HEIGHT
        )
        self.char_prompt_manage_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.char_prompt_manage_thumb.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 6px;
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(12)}px;
            }}
        """)
        self.char_prompt_manage_thumb.setText("썸네일 없음")
        top_section.addWidget(self.char_prompt_manage_thumb)

        # 우측: 폴더/아이템 선택 영역
        right_top = QVBoxLayout()
        right_top.setSpacing(4)

        # 라벨 스타일 (폰트 15px)
        label_style = f"""
            color: {DARK_COLORS['text_primary']};
            font-size: {get_scaled_font_size(15)}px;
        """

        # 캐릭터 폴더 그룹 라벨
        folder_label = QLabel("캐릭터 폴더 그룹")
        folder_label.setStyleSheet(label_style)
        right_top.addWidget(folder_label)

        # 폴더 콤보박스 + 추가 버튼 행
        folder_row = QHBoxLayout()
        folder_row.setSpacing(6)
        self.char_prompt_manage_folder_combo = QComboBox()
        self.char_prompt_manage_folder_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.char_prompt_manage_folder_combo.currentTextChanged.connect(
            self._on_manage_folder_changed
        )
        folder_row.addWidget(self.char_prompt_manage_folder_combo, 1)

        # 폴더 추가 버튼
        add_folder_btn = QPushButton("추가")
        add_folder_btn.setFixedWidth(50)
        add_folder_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        add_folder_btn.clicked.connect(self._on_manage_add_folder)
        folder_row.addWidget(add_folder_btn)
        right_top.addLayout(folder_row)

        # 캐릭터 선택 라벨
        item_label = QLabel("캐릭터 선택 (신규 등록시 무시)")
        item_label.setStyleSheet(label_style)
        right_top.addWidget(item_label)

        # 아이템 콤보박스
        self.char_prompt_manage_item_combo = QComboBox()
        self.char_prompt_manage_item_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.char_prompt_manage_item_combo.currentIndexChanged.connect(
            self._on_manage_item_changed
        )
        right_top.addWidget(self.char_prompt_manage_item_combo)

        # 수정/삭제 버튼 행
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.char_prompt_manage_edit_btn = QPushButton("수정")
        self.char_prompt_manage_edit_btn.setFixedWidth(80)
        self.char_prompt_manage_edit_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.char_prompt_manage_edit_btn.clicked.connect(self._on_manage_edit_clicked)

        self.char_prompt_manage_delete_btn = QPushButton("삭제")
        self.char_prompt_manage_delete_btn.setFixedWidth(80)
        self.char_prompt_manage_delete_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.char_prompt_manage_delete_btn.clicked.connect(self._on_manage_delete_clicked)

        btn_row.addWidget(self.char_prompt_manage_edit_btn)
        btn_row.addWidget(self.char_prompt_manage_delete_btn)
        btn_row.addStretch()
        right_top.addLayout(btn_row)

        # 신규 등록 버튼 (별도 행)
        register_btn = QPushButton("신규 등록")
        register_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-size: {get_scaled_font_size(15)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
        """)
        register_btn.clicked.connect(self._on_manage_register_clicked)
        right_top.addWidget(register_btn)

        right_top.addStretch()
        top_section.addLayout(right_top, 1)
        manage_layout.addLayout(top_section)

        # === 중간 섹션: 프롬프트 편집 ===
        prompt_section = QVBoxLayout()
        prompt_section.setSpacing(2)
        prompt_section.setContentsMargins(0, 4, 0, 0)

        # 캐릭터 프롬프트
        prompt_label = QLabel("캐릭터 프롬프트")
        prompt_label.setStyleSheet(f"""
            color: {DARK_COLORS['text_primary']};
            font-size: {get_scaled_font_size(15)}px;
            margin-bottom: 2px;
        """)
        prompt_section.addWidget(prompt_label)

        self.char_prompt_manage_prompt_edit = QTextEdit()
        self.char_prompt_manage_prompt_edit.setPlaceholderText("캐릭터 프롬프트를 입력하세요...")
        self.char_prompt_manage_prompt_edit.setMinimumHeight(120)
        self.char_prompt_manage_prompt_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
        prompt_section.addWidget(self.char_prompt_manage_prompt_edit)

        # 네거티브 프롬프트
        uc_label = QLabel("네거티브 프롬프트")
        uc_label.setStyleSheet(f"""
            color: {DARK_COLORS['text_primary']};
            font-size: {get_scaled_font_size(15)}px;
            margin-bottom: 2px;
        """)
        prompt_section.addWidget(uc_label)

        self.char_prompt_manage_uc_edit = QTextEdit()
        self.char_prompt_manage_uc_edit.setPlaceholderText("네거티브 프롬프트를 입력하세요...")
        self.char_prompt_manage_uc_edit.setMaximumHeight(80)
        self.char_prompt_manage_uc_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
        prompt_section.addWidget(self.char_prompt_manage_uc_edit)

        manage_layout.addLayout(prompt_section)

        # === 하단 섹션: 액션 버튼들 ===
        bottom_section = QHBoxLayout()
        bottom_section.setSpacing(6)

        # 캐릭터 검색 버튼 (보라색 배경)
        search_btn = QPushButton("캐릭터 검색")
        search_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #7C4DFF;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-size: {get_scaled_font_size(15)}px;
            }}
            QPushButton:hover {{
                background-color: #651FFF;
            }}
        """)
        search_btn.clicked.connect(self._on_manage_search_clicked)
        bottom_section.addWidget(search_btn)

        # 썸네일 이미지 생성 버튼
        gen_thumb_btn = QPushButton("썸네일 생성")
        gen_thumb_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        gen_thumb_btn.clicked.connect(self._on_manage_gen_thumb_clicked)
        bottom_section.addWidget(gen_thumb_btn)

        # 썸네일 붙여넣기 버튼
        paste_thumb_btn = QPushButton("썸네일 붙여넣기")
        paste_thumb_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        paste_thumb_btn.clicked.connect(self._on_manage_paste_thumb_clicked)
        bottom_section.addWidget(paste_thumb_btn)

        manage_layout.addLayout(bottom_section)

        # 콤보박스 데이터 초기화
        self._refresh_manage_folder_combo()

        return manage_widget

    # === 캐릭터 프롬프트 탭 이벤트 핸들러 ===

    def _on_char_prompt_activate_changed(self, state: int):
        """활성화 체크박스 변경 → 모듈에 반영"""
        if not self.character_module or not hasattr(self.character_module, 'activate_checkbox'):
            return
        is_checked = state == Qt.CheckState.Checked.value
        self.character_module.activate_checkbox.setChecked(is_checked)

    def _on_char_prompt_reroll_changed(self, state: int):
        """생성 시 리롤 체크박스 변경 → 모듈에 반영"""
        if not self.character_module or not hasattr(self.character_module, 'reroll_on_generate_checkbox'):
            return
        is_checked = state == Qt.CheckState.Checked.value
        self.character_module.reroll_on_generate_checkbox.setChecked(is_checked)

    def _on_char_prompt_person_changed(self, person_id: int):
        """인원 수 라디오 버튼 변경"""
        self.char_prompt_person_count = person_id

        # 슬롯 프레임 표시/숨김
        for i, frame in enumerate(self.char_prompt_slot_frames):
            frame.setVisible(i < person_id)

        # character_module의 캐릭터 위젯 관리
        self._adjust_character_widgets(person_id)

        # 슬롯 내용 업데이트
        self._update_char_prompt_slots()

    def _adjust_character_widgets(self, target_count: int):
        """character_module의 캐릭터 위젯 수 조정"""
        if not self.character_module or not hasattr(self.character_module, 'character_widgets'):
            return

        current_count = len(self.character_module.character_widgets)

        # 위젯 수가 부족하면 추가
        while current_count < target_count:
            if hasattr(self.character_module, 'add_character_widget'):
                self.character_module.add_character_widget()
            current_count = len(self.character_module.character_widgets)

        # 위젯 수가 초과하면: 빈 프레임 삭제 또는 비활성화
        for i, widget in enumerate(self.character_module.character_widgets):
            if i < target_count:
                # 필요한 범위: 활성화
                if hasattr(widget, 'active_checkbox'):
                    widget.active_checkbox.setChecked(True)
                widget.setEnabled(True)
            else:
                # 초과 범위
                is_empty = self._is_character_widget_empty(widget)
                if is_empty:
                    # 빈 프레임은 비활성화 (삭제는 안전하지 않을 수 있음)
                    if hasattr(widget, 'active_checkbox'):
                        widget.active_checkbox.setChecked(False)
                    widget.setEnabled(False)
                else:
                    # 비어있지 않은 프레임은 비활성화만
                    if hasattr(widget, 'active_checkbox'):
                        widget.active_checkbox.setChecked(False)
                    widget.setEnabled(False)

    def _is_character_widget_empty(self, widget) -> bool:
        """캐릭터 위젯이 비어있는지 확인"""
        prompt_text = ""
        uc_text = ""

        if hasattr(widget, 'prompt_textbox'):
            prompt_text = widget.prompt_textbox.toPlainText().strip()
        if hasattr(widget, 'uc_textbox'):
            uc_text = widget.uc_textbox.toPlainText().strip()

        return not prompt_text and not uc_text

    def _on_char_prompt_slot_clicked(self, slot_index: int):
        """캐릭터 슬롯 클릭 → 선택"""
        old_index = self.char_prompt_selected_slot
        self.char_prompt_selected_slot = slot_index

        # 스타일 업데이트
        if old_index < len(self.char_prompt_slot_frames):
            self._update_slot_frame_style(self.char_prompt_slot_frames[old_index], False)
        if slot_index < len(self.char_prompt_slot_frames):
            self._update_slot_frame_style(self.char_prompt_slot_frames[slot_index], True)

    def _on_char_prompt_slot_edit(self, slot_index: int):
        """캐릭터 슬롯 수정 버튼 클릭"""
        if not self.character_module or not hasattr(self.character_module, 'character_widgets'):
            return

        widgets = self.character_module.character_widgets
        if slot_index >= len(widgets):
            self._show_warning("경고", f"C{slot_index+1} 캐릭터가 존재하지 않습니다.")
            return

        widget = widgets[slot_index]

        # 현재 값 가져오기
        current_prompt = ""
        current_uc = ""
        if hasattr(widget, 'prompt_textbox'):
            current_prompt = widget.prompt_textbox.toPlainText()
        if hasattr(widget, 'uc_textbox'):
            current_uc = widget.uc_textbox.toPlainText()

        # 편집 다이얼로그 열기
        self._open_char_prompt_edit_dialog(slot_index, current_prompt, current_uc)

    def _open_char_prompt_edit_dialog(self, slot_index: int, current_prompt: str, current_uc: str):
        """캐릭터 프롬프트 편집 다이얼로그"""
        dialog = QDialog(self)
        dialog.setWindowTitle(f"C{slot_index+1} 캐릭터 프롬프트 편집")
        dialog.setMinimumSize(500, 400)
        self._style_dialog(dialog)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(12)

        # 프롬프트
        prompt_label = QLabel("캐릭터 프롬프트:")
        prompt_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-weight: bold;")
        layout.addWidget(prompt_label)

        prompt_edit = QTextEdit()
        prompt_edit.setAcceptRichText(False)
        prompt_edit.setPlainText(current_prompt)
        prompt_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                font-size: {get_scaled_font_size(16)}px;
            }}
        """)
        layout.addWidget(prompt_edit, 1)

        # UC
        uc_label = QLabel("부정 프롬프트 (UC):")
        uc_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-weight: bold;")
        layout.addWidget(uc_label)

        uc_edit = QTextEdit()
        uc_edit.setAcceptRichText(False)
        uc_edit.setPlainText(current_uc)
        uc_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                font-size: {get_scaled_font_size(16)}px;
            }}
        """)
        layout.addWidget(uc_edit, 1)

        # 버튼
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        save_btn = QPushButton("저장")
        save_btn.setStyleSheet(DARK_STYLES['primary_button'])
        save_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(save_btn)

        cancel_btn = QPushButton("취소")
        cancel_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_prompt = prompt_edit.toPlainText()
            new_uc = uc_edit.toPlainText()
            self._apply_char_prompt_to_module(slot_index, new_prompt, new_uc)

    def _apply_char_prompt_to_module(self, slot_index: int, prompt: str, uc: str):
        """캐릭터 프롬프트를 모듈에 적용"""
        if not self.character_module or not hasattr(self.character_module, 'character_widgets'):
            return

        widgets = self.character_module.character_widgets
        if slot_index >= len(widgets):
            return

        widget = widgets[slot_index]
        if hasattr(widget, 'prompt_textbox'):
            widget.prompt_textbox.setPlainText(prompt)
        if hasattr(widget, 'uc_textbox'):
            widget.uc_textbox.setPlainText(uc)

        # 슬롯 표시 업데이트
        self._update_char_prompt_slots()

    def _on_char_prompt_folder_changed(self, folder_name: str):
        """즐겨찾기 폴더 변경"""
        self.char_prompt_current_folder = folder_name
        self._update_char_prompt_favorites_grid()

    def _on_char_prompt_add_folder(self):
        """새 즐겨찾기 폴더 추가"""
        name, ok = self._get_text_input("새 폴더", "폴더 이름을 입력하세요:")
        if ok and name:
            if name not in self.char_prompt_folders:
                self.char_prompt_folders.append(name)
                self.char_prompt_folder_combo.addItem(name)
                self._save_char_prompt_folders()
            else:
                self._show_warning("경고", "이미 존재하는 폴더 이름입니다.")

    def _on_char_prompt_delete_folder(self):
        """선택된 즐겨찾기 폴더 삭제"""
        current_folder = self.char_prompt_folder_combo.currentText()

        if current_folder == "기본":
            self._show_warning("경고", "기본 폴더는 삭제할 수 없습니다.")
            return

        # 해당 폴더의 즐겨찾기 개수 확인
        folder_favorites = [f for f in self.char_prompt_favorites
                           if f.get("folder", "기본") == current_folder]

        confirm_msg = f"'{current_folder}' 폴더를 삭제하시겠습니까?"
        if folder_favorites:
            confirm_msg += f"\n\n이 폴더에 {len(folder_favorites)}개의 즐겨찾기가 있습니다.\n즐겨찾기도 함께 삭제됩니다."

        if not self._show_question("폴더 삭제", confirm_msg):
            return

        # 폴더 내 즐겨찾기 삭제
        self.char_prompt_favorites = [f for f in self.char_prompt_favorites
                                      if f.get("folder", "기본") != current_folder]
        self._save_char_prompt_favorites()

        # 폴더 목록에서 제거
        self.char_prompt_folders.remove(current_folder)
        self._save_char_prompt_folders()

        # 콤보박스 업데이트
        idx = self.char_prompt_folder_combo.findText(current_folder)
        if idx >= 0:
            self.char_prompt_folder_combo.removeItem(idx)

        # 기본 폴더로 이동
        self.char_prompt_folder_combo.setCurrentText("기본")

    def _sync_char_prompt_from_module(self):
        """character_module에서 현재 상태 동기화"""
        if not self.character_module:
            return

        # 체크박스 동기화
        if hasattr(self.character_module, 'activate_checkbox') and self.character_module.activate_checkbox:
            self.char_prompt_activate_check.blockSignals(True)
            self.char_prompt_activate_check.setChecked(self.character_module.activate_checkbox.isChecked())
            self.char_prompt_activate_check.blockSignals(False)

        if hasattr(self.character_module, 'reroll_on_generate_checkbox') and self.character_module.reroll_on_generate_checkbox:
            self.char_prompt_reroll_check.blockSignals(True)
            self.char_prompt_reroll_check.setChecked(self.character_module.reroll_on_generate_checkbox.isChecked())
            self.char_prompt_reroll_check.blockSignals(False)

        # 슬롯 내용 업데이트
        self._update_char_prompt_slots()

        # 즐겨찾기 그리드 업데이트
        self._load_char_prompt_favorites()
        self._update_char_prompt_favorites_grid()

    def _update_char_prompt_slots(self):
        """캐릭터 슬롯 표시 업데이트 (모듈에서 데이터 읽기)"""
        if not self.character_module or not hasattr(self.character_module, 'character_widgets'):
            return

        widgets = self.character_module.character_widgets

        for i, slot_edit in enumerate(self.char_prompt_slot_edits):
            if i < len(widgets):
                widget = widgets[i]
                prompt_text = ""
                if hasattr(widget, 'prompt_textbox'):
                    prompt_text = widget.prompt_textbox.toPlainText().strip()

                # 첫 줄만 표시 (너무 길면 생략)
                if prompt_text:
                    first_line = prompt_text.split('\n')[0]
                    if len(first_line) > 50:
                        first_line = first_line[:47] + "..."
                    slot_edit.setText(first_line)
                else:
                    slot_edit.setText("")
            else:
                slot_edit.setText("")

    def _update_char_prompt_favorites_grid(self):
        """캐릭터 프롬프트 즐겨찾기 그리드 업데이트"""
        # 기존 위젯 제거
        while self.char_prompt_favorites_grid.count():
            item = self.char_prompt_favorites_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 현재 폴더의 즐겨찾기 필터링
        folder_favorites = [f for f in self.char_prompt_favorites
                           if f.get("folder", "기본") == self.char_prompt_current_folder]

        if not folder_favorites:
            empty_label = QLabel("즐겨찾기가 없습니다.")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet(f"color: {DARK_COLORS['text_disabled']}; background-color: transparent;")
            self.char_prompt_favorites_grid.addWidget(empty_label, 0, 0)
            return

        # 4열 그리드로 배치
        cols = 4
        for idx, fav_data in enumerate(folder_favorites):
            row = idx // cols
            col = idx % cols

            # 썸네일 경로: thumbnail 필드에서 파일명 가져오기
            thumb_filename = fav_data.get("thumbnail", "")
            if thumb_filename:
                thumb_path = CHAR_PROMPT_FAVORITES_DIR / thumb_filename
            else:
                thumb_path = None

            # 선택 상태 확인
            is_selected = (hasattr(self, '_char_prompt_selected_fav') and
                          self._char_prompt_selected_fav and
                          self._char_prompt_selected_fav.get("name") == fav_data.get("name") and
                          self._char_prompt_selected_fav.get("folder") == fav_data.get("folder"))

            item_widget = CharacterPromptFavoriteItemWidget(
                fav_data, thumb_path,
                CHAR_PROMPT_THUMB_WIDTH, CHAR_PROMPT_THUMB_HEIGHT,
                is_selected=is_selected
            )
            item_widget.clicked.connect(self._on_char_prompt_favorite_clicked)
            self.char_prompt_favorites_grid.addWidget(item_widget, row, col)

        # 좌측 상단 정렬을 위한 스페이서 추가
        last_row = (len(folder_favorites) - 1) // cols + 1
        # 우측 스페이서
        self.char_prompt_favorites_grid.setColumnStretch(cols, 1)
        # 하단 스페이서
        self.char_prompt_favorites_grid.setRowStretch(last_row, 1)

    def _on_char_prompt_favorite_clicked(self, fav_data: dict):
        """즐겨찾기 아이템 클릭 → 선택된 슬롯에 적용"""
        prompt = fav_data.get("prompt", "")
        uc = fav_data.get("uc", "")

        # 선택 상태 저장
        self._char_prompt_selected_fav = fav_data

        # 인원 수가 1명이면 무조건 C1(슬롯 0)에 적용
        target_slot = self.char_prompt_selected_slot
        if self.char_prompt_person_count == 1:
            target_slot = 0

        # 모듈에 적용
        self._apply_char_prompt_to_module(target_slot, prompt, uc)

        # 슬롯 프레임의 프롬프트 표시 업데이트
        if hasattr(self, 'char_prompt_slot_edits') and 0 <= target_slot < len(self.char_prompt_slot_edits):
            self.char_prompt_slot_edits[target_slot].setText(prompt)

        # 그리드 업데이트하여 선택 표시
        self._update_char_prompt_favorites_grid()

    def _on_char_prompt_delete_character(self):
        """선택된 캐릭터 삭제"""
        if not hasattr(self, '_char_prompt_selected_fav') or not self._char_prompt_selected_fav:
            QMessageBox.warning(self, "알림", "삭제할 캐릭터를 먼저 선택해주세요.")
            return

        fav_data = self._char_prompt_selected_fav
        name = fav_data.get("name", "")
        folder = fav_data.get("folder", "기본")

        # 삭제 확인
        reply = QMessageBox.question(
            self, "캐릭터 삭제",
            f"'{name}' 캐릭터를 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # 썸네일 파일 삭제
        thumb_filename = fav_data.get("thumbnail", "")
        if thumb_filename:
            thumb_path = CHAR_PROMPT_FAVORITES_DIR / thumb_filename
            if thumb_path.exists():
                try:
                    thumb_path.unlink()
                except Exception as e:
                    print(f"썸네일 삭제 실패: {e}")

        # 즐겨찾기 목록에서 제거
        self.char_prompt_favorites = [
            f for f in self.char_prompt_favorites
            if not (f.get("name") == name and f.get("folder") == folder)
        ]

        # 선택 상태 초기화
        self._char_prompt_selected_fav = None

        # 저장 및 UI 업데이트
        self._save_char_prompt_favorites()
        self._update_char_prompt_favorites_grid()
        self._refresh_manage_folder_combo()

        QMessageBox.information(self, "완료", f"'{name}' 캐릭터가 삭제되었습니다.")

    def _load_char_prompt_favorites(self):
        """캐릭터 프롬프트 즐겨찾기 로드"""
        if CHAR_PROMPT_FAVORITES_JSON.exists():
            try:
                with open(CHAR_PROMPT_FAVORITES_JSON, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.char_prompt_favorites = data.get("favorites", [])
            except Exception as e:
                print(f"캐릭터 프롬프트 즐겨찾기 로드 실패: {e}")
                self.char_prompt_favorites = []

        if CHAR_PROMPT_FOLDERS_JSON.exists():
            try:
                with open(CHAR_PROMPT_FOLDERS_JSON, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.char_prompt_folders = data.get("folders", ["기본"])
            except Exception as e:
                print(f"캐릭터 프롬프트 폴더 로드 실패: {e}")
                self.char_prompt_folders = ["기본"]

    def _save_char_prompt_favorites(self):
        """캐릭터 프롬프트 즐겨찾기 저장"""
        try:
            CHAR_PROMPT_FAVORITES_DIR.mkdir(parents=True, exist_ok=True)
            with open(CHAR_PROMPT_FAVORITES_JSON, 'w', encoding='utf-8') as f:
                json.dump({"favorites": self.char_prompt_favorites}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"캐릭터 프롬프트 즐겨찾기 저장 실패: {e}")

    def _save_char_prompt_folders(self):
        """캐릭터 프롬프트 폴더 저장"""
        try:
            CHAR_PROMPT_FAVORITES_DIR.mkdir(parents=True, exist_ok=True)
            with open(CHAR_PROMPT_FOLDERS_JSON, 'w', encoding='utf-8') as f:
                json.dump({"folders": self.char_prompt_folders}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"캐릭터 프롬프트 폴더 저장 실패: {e}")

    # === 캐릭터 프롬프트 즐겨찾기 관리 탭 핸들러 ===

    def _refresh_manage_folder_combo(self):
        """관리 탭 폴더 콤보박스 새로고침"""
        if not hasattr(self, 'char_prompt_manage_folder_combo'):
            return

        self.char_prompt_manage_folder_combo.blockSignals(True)
        self.char_prompt_manage_folder_combo.clear()
        self.char_prompt_manage_folder_combo.addItems(self.char_prompt_folders)
        self.char_prompt_manage_folder_combo.blockSignals(False)

        # 첫 폴더 선택
        if self.char_prompt_folders:
            self._on_manage_folder_changed(self.char_prompt_folders[0])

    def _refresh_char_prompt_folder_combo(self):
        """즐겨찾기 탭 폴더 콤보박스 새로고침"""
        if not hasattr(self, 'char_prompt_folder_combo'):
            return

        current_folder = self.char_prompt_folder_combo.currentText()

        self.char_prompt_folder_combo.blockSignals(True)
        self.char_prompt_folder_combo.clear()
        self.char_prompt_folder_combo.addItems(self.char_prompt_folders)

        # 기존 선택 복원
        idx = self.char_prompt_folder_combo.findText(current_folder)
        if idx >= 0:
            self.char_prompt_folder_combo.setCurrentIndex(idx)

        self.char_prompt_folder_combo.blockSignals(False)

    def _on_manage_folder_changed(self, folder_name: str):
        """관리 탭 폴더 변경 → 아이템 콤보 업데이트"""
        if not folder_name or not hasattr(self, 'char_prompt_manage_item_combo'):
            return

        self.char_prompt_manage_item_combo.blockSignals(True)
        self.char_prompt_manage_item_combo.clear()

        # 해당 폴더의 즐겨찾기 필터링
        folder_items = [
            fav for fav in self.char_prompt_favorites
            if fav.get("folder", "기본") == folder_name
        ]

        for fav in folder_items:
            name = fav.get("name", "이름없음")
            self.char_prompt_manage_item_combo.addItem(name, fav)

        self.char_prompt_manage_item_combo.blockSignals(False)

        # 첫 아이템 선택
        if folder_items:
            self._on_manage_item_changed(0)
        else:
            self._clear_manage_display()

    def _on_manage_item_changed(self, index: int):
        """관리 탭 아이템 변경 → 상세 정보 표시"""
        if index < 0:
            self._clear_manage_display()
            return

        fav_data = self.char_prompt_manage_item_combo.itemData(index)
        if not fav_data:
            self._clear_manage_display()
            return

        # 썸네일 표시
        thumb_filename = fav_data.get("thumbnail", "")
        if thumb_filename:
            thumb_path = CHAR_PROMPT_FAVORITES_DIR / thumb_filename
            if thumb_path.exists():
                pixmap = QPixmap(str(thumb_path))
                scaled = pixmap.scaled(
                    CHAR_PROMPT_MANAGE_THUMB_WIDTH, CHAR_PROMPT_MANAGE_THUMB_HEIGHT,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.char_prompt_manage_thumb.setPixmap(scaled)
            else:
                self.char_prompt_manage_thumb.setText("썸네일 없음")
        else:
            self.char_prompt_manage_thumb.setText("썸네일 없음")

        # 프롬프트 표시
        self.char_prompt_manage_prompt_edit.setPlainText(fav_data.get("prompt", ""))
        self.char_prompt_manage_uc_edit.setPlainText(fav_data.get("uc", ""))

    def _clear_manage_display(self):
        """관리 탭 표시 초기화"""
        if hasattr(self, 'char_prompt_manage_thumb'):
            self.char_prompt_manage_thumb.setText("썸네일 없음")
            self.char_prompt_manage_thumb.setPixmap(QPixmap())
        if hasattr(self, 'char_prompt_manage_prompt_edit'):
            self.char_prompt_manage_prompt_edit.clear()
        if hasattr(self, 'char_prompt_manage_uc_edit'):
            self.char_prompt_manage_uc_edit.clear()

    def _on_manage_edit_clicked(self):
        """수정 버튼 클릭 → 현재 선택된 아이템 수정"""
        index = self.char_prompt_manage_item_combo.currentIndex()
        if index < 0:
            QMessageBox.warning(self, "알림", "수정할 아이템을 선택하세요.")
            return

        fav_data = self.char_prompt_manage_item_combo.itemData(index)
        if not fav_data:
            return

        # 현재 편집된 값으로 업데이트
        new_prompt = self.char_prompt_manage_prompt_edit.toPlainText().strip()
        new_uc = self.char_prompt_manage_uc_edit.toPlainText().strip()

        # 이름 수정 대화상자
        old_name = fav_data.get("name", "")
        new_name, ok = QInputDialog.getText(
            self, "이름 수정", "아이템 이름:", text=old_name
        )
        if not ok:
            return

        if not new_name.strip():
            new_name = old_name

        # 원본 데이터 찾아서 수정
        for fav in self.char_prompt_favorites:
            if fav.get("name") == old_name and fav.get("folder") == fav_data.get("folder"):
                fav["name"] = new_name.strip()
                fav["prompt"] = new_prompt
                fav["uc"] = new_uc
                break

        self._save_char_prompt_favorites()
        self._update_char_prompt_favorites_grid()
        self._refresh_manage_folder_combo()

        QMessageBox.information(self, "완료", "아이템이 수정되었습니다.")

    def _on_manage_delete_clicked(self):
        """삭제 버튼 클릭 → 현재 선택된 아이템 삭제"""
        index = self.char_prompt_manage_item_combo.currentIndex()
        if index < 0:
            QMessageBox.warning(self, "알림", "삭제할 아이템을 선택하세요.")
            return

        fav_data = self.char_prompt_manage_item_combo.itemData(index)
        if not fav_data:
            return

        name = fav_data.get("name", "")
        reply = QMessageBox.question(
            self, "삭제 확인",
            f"'{name}' 아이템을 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # 썸네일 파일 삭제
        thumb_filename = fav_data.get("thumbnail", "")
        if thumb_filename:
            thumb_path = CHAR_PROMPT_FAVORITES_DIR / thumb_filename
            if thumb_path.exists():
                try:
                    thumb_path.unlink()
                except Exception as e:
                    print(f"썸네일 삭제 실패: {e}")

        # 리스트에서 제거
        self.char_prompt_favorites = [
            fav for fav in self.char_prompt_favorites
            if not (fav.get("name") == name and fav.get("folder") == fav_data.get("folder"))
        ]

        self._save_char_prompt_favorites()
        self._update_char_prompt_favorites_grid()
        self._refresh_manage_folder_combo()

        QMessageBox.information(self, "완료", "아이템이 삭제되었습니다.")

    def _on_manage_search_clicked(self):
        """캐릭터 검색 버튼 클릭 → CharacterSearchDialog 사용"""
        # CharacterSearchDialog에 프롬프트/UC TextEdit 전달
        dialog = CharacterSearchDialog(
            parent_prompt_textbox=self.char_prompt_manage_prompt_edit,
            parent_uc_textbox=self.char_prompt_manage_uc_edit,
            parent=self
        )
        dialog.exec()

    def _on_manage_add_folder(self):
        """관리 탭에서 폴더 추가"""
        folder_name, ok = QInputDialog.getText(
            self, "폴더 추가", "새 폴더 이름을 입력하세요:"
        )
        if not ok or not folder_name.strip():
            return

        folder_name = folder_name.strip()
        if folder_name in self.char_prompt_folders:
            QMessageBox.warning(self, "오류", "이미 존재하는 폴더 이름입니다.")
            return

        self.char_prompt_folders.append(folder_name)
        self._save_char_prompt_folders()
        self._refresh_manage_folder_combo()
        self._refresh_char_prompt_folder_combo()

        # 새로 추가된 폴더 선택
        idx = self.char_prompt_manage_folder_combo.findText(folder_name)
        if idx >= 0:
            self.char_prompt_manage_folder_combo.setCurrentIndex(idx)

    def _on_manage_gen_thumb_clicked(self):
        """썸네일 생성 버튼 클릭 → 이미지 생성하여 썸네일 생성"""
        if not self.character_module or not self.parent_app:
            QMessageBox.warning(self, "오류", "캐릭터 모듈 또는 메인 앱을 찾을 수 없습니다.")
            return

        # app_context 확인
        if not hasattr(self.parent_app, 'app_context') or not self.parent_app.app_context:
            QMessageBox.warning(self, "오류", "앱 컨텍스트를 찾을 수 없습니다.")
            return

        app_context = self.parent_app.app_context

        # 현재 입력된 프롬프트 확인
        new_prompt = self.char_prompt_manage_prompt_edit.toPlainText().strip()
        new_uc = self.char_prompt_manage_uc_edit.toPlainText().strip()

        if not new_prompt:
            QMessageBox.warning(self, "알림", "캐릭터 프롬프트를 입력해주세요.")
            return

        # === 1. 현재 상태 백업 ===
        # 인원 수 백업
        original_person_count = self.char_prompt_person_count

        # C1 프롬프트/UC 백업 (prompt_textbox, uc_textbox 사용)
        original_c1_prompt = ""
        original_c1_uc = ""
        if self.character_module and hasattr(self.character_module, 'character_widgets'):
            widgets = self.character_module.character_widgets
            if widgets and len(widgets) > 0:
                c1_widget = widgets[0]
                if hasattr(c1_widget, 'prompt_textbox'):
                    original_c1_prompt = c1_widget.prompt_textbox.toPlainText()
                if hasattr(c1_widget, 'uc_textbox'):
                    original_c1_uc = c1_widget.uc_textbox.toPlainText()

        # === 2. 임시 설정 적용 ===
        # 인원 수를 1로 설정
        if hasattr(self, 'char_prompt_person_radios') and self.char_prompt_person_radios:
            self.char_prompt_person_radios[0].setChecked(True)
            self._on_char_prompt_person_changed(1)

        # C1에 새 프롬프트/UC 적용 (prompt_textbox, uc_textbox 사용)
        if self.character_module and hasattr(self.character_module, 'character_widgets'):
            widgets = self.character_module.character_widgets
            if widgets and len(widgets) > 0:
                c1_widget = widgets[0]
                if hasattr(c1_widget, 'prompt_textbox'):
                    c1_widget.prompt_textbox.setPlainText(new_prompt)
                if hasattr(c1_widget, 'uc_textbox'):
                    c1_widget.uc_textbox.setPlainText(new_uc)

        # === 3. 생성 완료 콜백 정의 ===
        def on_thumb_generation_finished(result):
            """생성 완료 시 썸네일 표시 및 원래 상태 복원"""
            # 구독 즉시 해제 (일회성)
            try:
                if "generation_completed_for_redirect" in app_context.subscribers:
                    app_context.subscribers["generation_completed_for_redirect"].remove(on_thumb_generation_finished)
            except ValueError:
                pass

            # 생성된 이미지를 썸네일로 표시
            if isinstance(result, Image.Image):
                # PIL Image → QImage → QPixmap
                q_image = ImageQt(result)
                pixmap = QPixmap.fromImage(q_image)
                scaled = pixmap.scaled(
                    CHAR_PROMPT_MANAGE_THUMB_WIDTH, CHAR_PROMPT_MANAGE_THUMB_HEIGHT,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.char_prompt_manage_thumb.setPixmap(scaled)

                # 원본 이미지 저장 (등록 시 사용)
                self._pending_thumb_image = q_image

            # === 4. 원래 상태 복원 ===
            # C1 프롬프트/UC 복원
            if self.character_module and hasattr(self.character_module, 'character_widgets'):
                widgets = self.character_module.character_widgets
                if widgets and len(widgets) > 0:
                    c1_widget = widgets[0]
                    if hasattr(c1_widget, 'prompt_textbox'):
                        c1_widget.prompt_textbox.setPlainText(original_c1_prompt)
                    if hasattr(c1_widget, 'uc_textbox'):
                        c1_widget.uc_textbox.setPlainText(original_c1_uc)

            # 인원 수 복원
            if original_person_count != 1:
                if hasattr(self, 'char_prompt_person_radios') and len(self.char_prompt_person_radios) >= original_person_count:
                    self.char_prompt_person_radios[original_person_count - 1].setChecked(True)
                    self._on_char_prompt_person_changed(original_person_count)

        # 생성 완료 이벤트 구독
        app_context.subscribe("generation_completed_for_redirect", on_thumb_generation_finished)

        # === 가상 row 생성 및 생성 요청 ===
        virtual_row = pd.Series({
            'general': 'upper body',
            'character': '',
            'meta': '',
            'copyright': '',
            'artist': '',
            'rating': 'g',
            'id': 0,
            'created_at': '',
            'uploader_id': 0,
            'score': 0,
            'source': 'CharPrompt Thumbnail',
            'md5': '',
            'file_ext': '',
            'file_size': 0,
            'image_width': 0,
            'image_height': 0,
            'parent_id': None,
            'has_children': False,
            'is_deleted': False,
            'is_banned': False,
            'pixiv_id': None,
            'has_active_children': False,
            'bit_flags': 0,
            'has_large': False,
            'has_visible_children': False,
            'is_favorited': False,
            'tag_string': 'upper body',
            'pool_string': '',
            'up_score': 0,
            'down_score': 0,
            'is_pending': False,
            'is_flagged': False,
            'is_note_locked': False,
            'is_rating_locked': False,
            'is_status_locked': False,
        })

        # 생성 요청
        if hasattr(self.parent_app, 'on_generate_with_image_requested'):
            self.parent_app.on_generate_with_image_requested(virtual_row)

    def _on_manage_paste_thumb_clicked(self):
        """썸네일 붙여넣기 → 클립보드에서 이미지 가져오기"""
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()

        if mime_data.hasImage():
            image = clipboard.image()
            if not image.isNull():
                # QImage를 썸네일로 표시
                scaled = image.scaled(
                    CHAR_PROMPT_MANAGE_THUMB_WIDTH, CHAR_PROMPT_MANAGE_THUMB_HEIGHT,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                pixmap = QPixmap.fromImage(scaled)
                self.char_prompt_manage_thumb.setPixmap(pixmap)

                # 임시 썸네일 경로 저장 (등록 시 사용)
                self._pending_thumb_image = image
                return

        QMessageBox.warning(self, "알림", "클립보드에 이미지가 없습니다.")

    def _set_manage_thumbnail_from_path(self, file_path: str):
        """파일 경로에서 썸네일 설정"""
        try:
            pixmap = QPixmap(file_path)
            if pixmap.isNull():
                QMessageBox.warning(self, "오류", "이미지를 로드할 수 없습니다.")
                return

            scaled = pixmap.scaled(
                CHAR_PROMPT_MANAGE_THUMB_WIDTH, CHAR_PROMPT_MANAGE_THUMB_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.char_prompt_manage_thumb.setPixmap(scaled)

            # 원본 이미지 저장 (등록 시 사용)
            image = QImage(file_path)
            self._pending_thumb_image = image

        except Exception as e:
            QMessageBox.warning(self, "오류", f"이미지 로드 실패: {e}")

    def _on_manage_register_clicked(self):
        """신규 즐겨찾기 등록"""
        # 이름 입력
        name, ok = QInputDialog.getText(
            self, "신규 등록", "아이템 이름을 입력하세요:"
        )
        if not ok or not name.strip():
            return

        name = name.strip()

        # 현재 폴더
        folder = self.char_prompt_manage_folder_combo.currentText()
        if not folder:
            folder = "기본"

        # 중복 확인
        for fav in self.char_prompt_favorites:
            if fav.get("name") == name and fav.get("folder") == folder:
                QMessageBox.warning(self, "오류", "같은 이름의 아이템이 이미 있습니다.")
                return

        # 프롬프트 데이터
        prompt = self.char_prompt_manage_prompt_edit.toPlainText().strip()
        uc = self.char_prompt_manage_uc_edit.toPlainText().strip()

        # 썸네일 저장
        thumb_filename = ""
        if hasattr(self, '_pending_thumb_image') and self._pending_thumb_image:
            CHAR_PROMPT_FAVORITES_DIR.mkdir(parents=True, exist_ok=True)
            thumb_filename = f"thumb_{name.replace(' ', '_')}_{len(self.char_prompt_favorites)}.png"
            thumb_path = CHAR_PROMPT_FAVORITES_DIR / thumb_filename

            # QImage를 파일로 저장
            self._pending_thumb_image.save(str(thumb_path), "PNG")
            self._pending_thumb_image = None

        # 즐겨찾기 추가
        new_fav = {
            "name": name,
            "folder": folder,
            "prompt": prompt,
            "uc": uc,
            "thumbnail": thumb_filename
        }
        self.char_prompt_favorites.append(new_fav)

        self._save_char_prompt_favorites()
        self._update_char_prompt_favorites_grid()
        self._refresh_manage_folder_combo()

        QMessageBox.information(self, "완료", f"'{name}' 아이템이 등록되었습니다.")
