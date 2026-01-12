# ui/remote_window.py
"""
리모트 컨트롤 창 - 모듈 통합 제어 UI

리팩토링 구조:
- QuickSearchTabMixin: 퀵 서치 탭 관련 (ui/remote/quick_search_tab.py)
- EventTabMixin: 이벤트 탭 관련 (ui/remote/event_tab.py)
- InstantWcTabMixin: 인스턴트 와일드카드 탭 관련 (ui/remote/instant_wc_tab.py)
- CharPromptTabMixin: 캐릭터 프롬프트 탭 관련 (ui/remote/char_prompt_tab.py)
- CharRefTabMixin: 캐릭터 레퍼런스 탭 관련 (ui/remote/char_ref_tab.py)
- PresetTabMixin: 프리셋 탭 관련 (ui/remote/preset_tab.py)
"""

from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTabWidget, QLabel, QComboBox, QTextEdit, QPushButton,
    QScrollArea, QFrame, QMessageBox, QApplication, QSizePolicy,
    QCheckBox, QSlider, QFileDialog, QInputDialog, QLineEdit, QDialog,
    QRadioButton, QButtonGroup
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QAction, QPixmap, QImage

from ui.theme import DARK_COLORS, DARK_STYLES
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

# 🆕 퀵 서치 탭 Mixin import
from ui.remote.quick_search_tab import QuickSearchTabMixin

# 🆕 이벤트 탭 Mixin import
from ui.remote.event_tab import (
    EventTabMixin, EventItemWidget,
    REMOTE_EVENTS_DIR, REMOTE_EVENTS_JSON, REMOTE_EVENTS_THUMBS_DIR,
    EVENT_THUMB_WIDTH, EVENT_THUMB_HEIGHT
)

# 🆕 인스턴트 와일드카드 탭 Mixin import
from ui.remote.instant_wc_tab import (
    InstantWcTabMixin, WildcardItemWidget,
    WC_THUMB_WIDTH, WC_THUMB_HEIGHT
)

# 🆕 캐릭터 프롬프트 탭 Mixin import
from ui.remote.char_prompt_tab import (
    CharPromptTabMixin, CharacterPromptFavoriteItemWidget,
    CHAR_PROMPT_FAVORITES_DIR, CHAR_PROMPT_FAVORITES_JSON, CHAR_PROMPT_FOLDERS_JSON,
    CHAR_PROMPT_THUMB_WIDTH, CHAR_PROMPT_THUMB_HEIGHT,
    CHAR_PROMPT_MANAGE_THUMB_WIDTH, CHAR_PROMPT_MANAGE_THUMB_HEIGHT
)

# 🆕 캐릭터 레퍼런스 탭 Mixin import
from ui.remote.char_ref_tab import (
    CharRefTabMixin, CharRefFavoriteItemWidget,
    CHAR_REF_FAVORITES_DIR, CHAR_REF_FAVORITES_JSON, CHAR_REF_FOLDERS_JSON
)

# 🆕 프리셋 탭 Mixin import
from ui.remote.preset_tab import (
    PresetTabMixin,
    PRESET_FAVORITES_DIR
)


# EventItemWidget은 ui/remote/event_tab.py로 이동됨
# WildcardItemWidget은 ui/remote/instant_wc_tab.py로 이동됨
# CharacterPromptFavoriteItemWidget은 ui/remote/char_prompt_tab.py로 이동됨
# CharRefFavoriteItemWidget은 ui/remote/char_ref_tab.py로 이동됨
# PresetFavoriteItemWidget은 ui/remote/preset_tab.py로 이동됨


class RemoteWindow(QMainWindow, QuickSearchTabMixin, EventTabMixin, InstantWcTabMixin, CharPromptTabMixin, CharRefTabMixin, PresetTabMixin):
    """리모트 탭에서 열리는 독립 창 - 모듈 통합 제어"""

    window_closed = pyqtSignal()

    def __init__(self, parent_app=None):
        super().__init__(parent=None)  # 완전 독립 창
        self.parent_app = parent_app

        # 모듈 참조 저장
        self.preset_module = None
        self.character_module = None
        self.character_ref_module = None
        self.instant_wc_module = None

        # 🆕 Mixin 데이터 초기화
        self._init_quick_search_data()  # QuickSearchTabMixin
        self._init_char_ref_data()
        self._init_char_prompt_data()
        self._init_preset_data()  # PresetTabMixin

        # 🆕 이벤트 탭 데이터
        self.remote_events = []  # [{"id": "...", "name": "...", "source_row": {...}, "thumbnail": "...", "created_at": "..."}, ...]

        # 🆕 자동 생성 관련 플래그
        self._event_auto_generate_pending = False  # 이벤트 탭 자동 생성 대기 중
        self._wc_auto_generate_pending = False  # INST.WC 탭 자동 생성 대기 중

        # 윈도우 플래그 설정 (항상 위에 기본 활성화)
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowStaysOnTopHint
        )

        self.setWindowTitle("NAIA - 리모트 컨트롤")
        self.setMinimumSize(550, 500)
        self.resize(740, 1020)  # 높이 1.8배 (600 * 1.8)

        # 다크 테마 적용
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        self._ensure_directories()
        self._get_module_references()
        # _load_preset_favorites(), _load_char_ref_favorites(), _load_char_prompt_favorites()는
        # 각 Mixin의 _init_*_data()에서 호출됨
        self._load_remote_events()  # 🆕
        self._setup_menubar()
        self._init_ui()

        # 🆕 생성 완료 이벤트 구독 (자동 생성용)
        self._subscribe_generation_completed()

    def _subscribe_generation_completed(self):
        """생성 완료 이벤트 구독 (자동 생성용)"""
        if self.parent_app and hasattr(self.parent_app, 'app_context'):
            app_context = self.parent_app.app_context
            app_context.subscribe("generation_completed_for_redirect", self._on_generation_completed_for_auto)

    def _on_generation_completed_for_auto(self, data):
        """생성 완료 시 자동 생성 처리"""
        # 이벤트 탭 자동 생성 처리
        if self._event_auto_generate_pending:
            self._event_auto_generate_pending = False
            # 대기열에 남은 항목이 있고, 자동 생성이 활성화되어 있으면 다음 실행
            if (hasattr(self, 'event_queue') and self.event_queue and
                hasattr(self, 'event_auto_generate_check') and
                self.event_auto_generate_check.isChecked()):
                # 약간의 딜레이 후 다음 생성 시작 (UI 업데이트 시간 확보)
                QTimer.singleShot(500, self._on_event_generate_start)

        # INST.WC 탭 자동 생성 처리
        if self._wc_auto_generate_pending:
            self._wc_auto_generate_pending = False
            # 대기열에 남은 항목이 있고, 자동 생성이 활성화되어 있으면 다음 실행
            if (hasattr(self, 'wc_queue') and self.wc_queue and
                hasattr(self, 'wc_auto_generate_check') and
                self.wc_auto_generate_check.isChecked()):
                # 약간의 딜레이 후 다음 생성 시작 (UI 업데이트 시간 확보)
                QTimer.singleShot(500, self._on_wc_generate_start)

        # Quick Search 탭 자동 생성 처리
        if hasattr(self, '_qs_auto_generate_pending') and self._qs_auto_generate_pending:
            self._qs_auto_generate_pending = False
            # 자동 생성이 활성화되어 있으면 다음 생성
            if (hasattr(self, 'qs_auto_generate_check') and
                self.qs_auto_generate_check.isChecked()):
                # 약간의 딜레이 후 다음 생성 시작 (UI 업데이트 시간 확보)
                QTimer.singleShot(500, self._on_qs_generate_start)

    def _style_dialog(self, dialog):
        """다이얼로그에 다크 테마 스타일 적용 (흰색 텍스트)"""
        dialog.setStyleSheet(f"""
            QMessageBox, QInputDialog {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
            QMessageBox QLabel, QInputDialog QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(15)}px;
            }}
            QMessageBox QPushButton, QInputDialog QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 6px 16px;
                min-width: 60px;
            }}
            QMessageBox QPushButton:hover, QInputDialog QPushButton:hover {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QInputDialog QLineEdit, QInputDialog QComboBox {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 4px 8px;
            }}
            QInputDialog QComboBox QAbstractItemView {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                selection-background-color: {DARK_COLORS['accent_blue']};
            }}
        """)

    def _show_warning(self, title: str, message: str):
        """다크 테마가 적용된 경고 다이얼로그"""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle(title)
        msg.setText(message)
        self._style_dialog(msg)
        msg.exec()

    def _show_info(self, title: str, message: str):
        """다크 테마가 적용된 정보 다이얼로그"""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setWindowTitle(title)
        msg.setText(message)
        self._style_dialog(msg)
        msg.exec()

    def _show_question(self, title: str, message: str) -> bool:
        """다크 테마가 적용된 확인 다이얼로그 (Yes/No)"""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setWindowTitle(title)
        msg.setText(message)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        self._style_dialog(msg)
        return msg.exec() == QMessageBox.StandardButton.Yes

    def _get_text_input(self, title: str, label: str) -> tuple:
        """다크 테마가 적용된 텍스트 입력 다이얼로그"""
        from PyQt6.QtWidgets import QInputDialog, QLineEdit
        dialog = QInputDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setInputMode(QInputDialog.InputMode.TextInput)

        self._style_dialog(dialog)

        # ✅ 스타일 적용 후에 line edit를 "다시" 잡기
        line_edit = None
        if hasattr(dialog, "lineEdit"):
            line_edit = dialog.lineEdit()
        if line_edit is None:
            line_edit = dialog.findChild(QLineEdit)

        if line_edit:
            line_edit.setProperty("autocomplete_ignore", True)

        ok = dialog.exec()
        return dialog.textValue(), ok == QInputDialog.DialogCode.Accepted

    def _get_item_input(self, title: str, label: str, items: list) -> tuple:
        """다크 테마가 적용된 항목 선택 다이얼로그"""
        dialog = QInputDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setComboBoxItems(items)
        dialog.setComboBoxEditable(False)
        self._style_dialog(dialog)
        ok = dialog.exec()
        return dialog.textValue(), ok == QInputDialog.DialogCode.Accepted

    def _ensure_directories(self):
        """필요한 디렉토리 생성"""
        PRESET_FAVORITES_DIR.mkdir(parents=True, exist_ok=True)
        CHAR_REF_FAVORITES_DIR.mkdir(parents=True, exist_ok=True)
        CHAR_PROMPT_FAVORITES_DIR.mkdir(parents=True, exist_ok=True)
        (CHAR_PROMPT_FAVORITES_DIR / "thumbnails").mkdir(parents=True, exist_ok=True)
        REMOTE_EVENTS_DIR.mkdir(parents=True, exist_ok=True)  # 🆕
        REMOTE_EVENTS_THUMBS_DIR.mkdir(parents=True, exist_ok=True)  # 🆕

    def _get_module_references(self):
        """모듈 인스턴스 참조 획득"""
        if not self.parent_app or not hasattr(self.parent_app, 'middle_section_controller'):
            return

        controller = self.parent_app.middle_section_controller

        # 모듈 참조 획득
        self.preset_module = controller.get_module_instance("PromptEngineeringModule")
        self.character_module = controller.get_module_instance("CharacterModule")
        self.character_ref_module = controller.get_module_instance("CharacterReferenceModule")
        self.instant_wc_module = controller.get_module_instance("InstantWildcardModule")

    # _load_preset_favorites, _save_preset_favorites, _validate_preset_favorites는
    # PresetTabMixin (ui/remote/preset_tab.py)으로 이동됨
    # _load_char_ref_favorites, _save_char_ref_favorites, _save_char_ref_folders는
    # CharRefTabMixin (ui/remote/char_ref_tab.py)으로 이동됨

    def _setup_menubar(self):
        """메뉴바 설정"""
        menubar = self.menuBar()
        menubar.setStyleSheet(f"""
            QMenuBar {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border-bottom: 1px solid {DARK_COLORS['border']};
                padding: 2px;
            }}
            QMenuBar::item {{
                background-color: transparent;
                padding: 4px 8px;
                border-radius: 4px;
            }}
            QMenuBar::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """)

        # 옵션 메뉴
        option_menu = menubar.addMenu("옵션 (&O)")
        option_menu.setStyleSheet(f"""
            QMenu {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 20px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
            QMenu::indicator {{
                width: 16px;
                height: 16px;
                margin-left: 4px;
            }}
        """)

        # 항상 위에 옵션 (기본 체크됨)
        self.always_on_top_action = QAction("📌 항상 위에 표시", self)
        self.always_on_top_action.setCheckable(True)
        self.always_on_top_action.setChecked(True)
        self.always_on_top_action.triggered.connect(self._toggle_always_on_top)
        option_menu.addAction(self.always_on_top_action)

    def _toggle_always_on_top(self, checked: bool):
        """항상 위에 표시 토글"""
        current_flags = self.windowFlags()

        if checked:
            new_flags = current_flags | Qt.WindowType.WindowStaysOnTopHint
        else:
            new_flags = current_flags & ~Qt.WindowType.WindowStaysOnTopHint

        self.setWindowFlags(new_flags)
        self.show()

    def _init_ui(self):
        """UI 초기화 - 탭 뷰 구조"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # 메인 탭 위젯
        self.main_tabs = QTabWidget()
        self.main_tabs.setStyleSheet(DARK_STYLES['dark_tabs'])
        layout.addWidget(self.main_tabs)

        # 탭1: 프리셋 (이중 탭) - PresetTabMixin
        self._create_preset_tab()

        # 🆕 퀵 서치 탭 (프리셋 앞에 삽입) - QuickSearchTabMixin
        self._create_quick_search_tab()

        # 탭2: 캐릭터 (이중 탭)
        self._create_character_tab()

        # 탭3: 이벤트 (이중 탭)
        self._create_event_tab()

    # _create_preset_tab, _create_preset_favorites_subtab, _create_preset_engineering_subtab 및
    # 양방향 동기화 메서드들은 PresetTabMixin (ui/remote/preset_tab.py)으로 이동됨

    def _create_character_tab(self):
        """탭2: 캐릭터 (이중 탭 - 레퍼런스, 프롬프트)"""
        char_widget = QWidget()
        char_layout = QVBoxLayout(char_widget)
        char_layout.setContentsMargins(4, 4, 4, 4)

        # 이중 탭
        char_sub_tabs = QTabWidget()
        char_sub_tabs.setStyleSheet(DARK_STYLES['dark_tabs'])
        char_layout.addWidget(char_sub_tabs)

        # 서브탭1: 레퍼런스 (새로운 즐겨찾기 시스템)
        self._create_char_ref_subtab(char_sub_tabs)

        # 서브탭2: 프롬프트 (CharacterModule) - 새로운 UI
        self._create_char_prompt_subtab(char_sub_tabs)

        self.main_tabs.addTab(char_widget, "👤 캐릭터")


    # _create_char_prompt_subtab 및 관련 메서드들은 CharPromptTabMixin (ui/remote/char_prompt_tab.py)으로 이동됨
    # _create_char_ref_subtab 및 관련 메서드들은 CharRefTabMixin (ui/remote/char_ref_tab.py)으로 이동됨

    def _create_event_tab(self):
        """탭3: 이벤트 (이중 탭 - 이벤트, INST.WC)"""
        event_widget = QWidget()
        event_layout = QVBoxLayout(event_widget)
        event_layout.setContentsMargins(4, 4, 4, 4)

        # 이중 탭
        event_sub_tabs = QTabWidget()
        event_sub_tabs.setStyleSheet(DARK_STYLES['dark_tabs'])
        event_layout.addWidget(event_sub_tabs)

        # 서브탭1: 이벤트 저장 목록
        self._create_event_list_subtab(event_sub_tabs)

        # 서브탭2: INST.WC (InstantWildcardModule)
        self._create_instant_wc_subtab(event_sub_tabs)

        self.main_tabs.addTab(event_widget, "🎉 이벤트")

    def _create_instant_wc_subtab(self, parent_tabs: QTabWidget):
        """인스턴트 와일드카드 서브탭 - 이벤트 탭과 유사한 구조"""
        wc_widget = QWidget()
        wc_layout = QVBoxLayout(wc_widget)
        wc_layout.setContentsMargins(8, 8, 8, 8)
        wc_layout.setSpacing(8)

        if not self.instant_wc_module:
            placeholder = QLabel("인스턴트 와일드카드 모듈을 찾을 수 없습니다.")
            placeholder.setStyleSheet(f"color: {DARK_COLORS['text_disabled']};")
            wc_layout.addWidget(placeholder)
            parent_tabs.addTab(wc_widget, "☑️ INST.WC")
            return

        # 와일드카드 메타데이터 (하트 값) 로드
        self._load_wc_metadata()

        # === 상단 Row 1: 타이틀 ===
        title_row = QHBoxLayout()
        wc_info = QLabel("☑️ 인스턴트 와일드카드")
        wc_info.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['accent_blue']};
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
            }}
        """)
        title_row.addWidget(wc_info)
        title_row.addStretch()
        wc_layout.addLayout(title_row)

        # === 상단 Row 2: 파일 선택 콤보박스 ===
        file_row = QHBoxLayout()
        file_row.setSpacing(6)

        file_label = QLabel("파일:")
        file_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(12)}px;")
        file_row.addWidget(file_label)

        self.wc_file_combo = QComboBox()
        self.wc_file_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: {get_scaled_font_size(14)}px;
                min-width: 200px;
            }}
            QComboBox:hover {{
                border: 1px solid {DARK_COLORS['accent_blue']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                selection-background-color: {DARK_COLORS['accent_blue']};
                border: 1px solid {DARK_COLORS['border']};
            }}
        """)
        self.wc_file_combo.addItem("(전체)")  # 전체 옵션
        # 파일 목록 추가
        if hasattr(self.instant_wc_module, 'instant_wildcard_tree'):
            for file_key in sorted(self.instant_wc_module.instant_wildcard_tree.keys()):
                self.wc_file_combo.addItem(file_key)
        self.wc_file_combo.currentTextChanged.connect(self._on_wc_file_changed)
        file_row.addWidget(self.wc_file_combo)

        file_row.addStretch()
        wc_layout.addLayout(file_row)

        # === 상단 Row 3: 제목 검색 (General 태그 검색) ===
        search_row = QHBoxLayout()
        search_row.setSpacing(6)

        search_label = QLabel("🔍")
        search_label.setStyleSheet(f"font-size: {get_scaled_font_size(14)}px;")
        search_row.addWidget(search_label)

        self.wc_search_input = QLineEdit()
        self.wc_search_input.setPlaceholderText("와일드카드 키 이름으로 검색...")
        self.wc_search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: {get_scaled_font_size(14)}px;
            }}
            QLineEdit:focus {{
                border: 1px solid {DARK_COLORS['accent_blue']};
            }}
        """)
        self.wc_search_input.returnPressed.connect(self._on_wc_search)
        self.wc_search_input.setProperty("autocomplete_ignore", True)
        search_row.addWidget(self.wc_search_input, 1)

        wc_search_btn = QPushButton("🔍 검색")
        wc_search_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        wc_search_btn.setFixedWidth(130)
        wc_search_btn.clicked.connect(self._on_wc_search)
        search_row.addWidget(wc_search_btn)

        wc_layout.addLayout(search_row)

        # === 상단 Row 4: 심층 검색 (태그에서 검색) ===
        depth_row = QHBoxLayout()
        depth_row.setSpacing(6)

        self.wc_depth_input = QLineEdit()
        self.wc_depth_input.setPlaceholderText("태그 검색 (현재 필터 결과에서 추가 검색)")
        self.wc_depth_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: {get_scaled_font_size(14)}px;
            }}
            QLineEdit:focus {{
                border: 1px solid {DARK_COLORS['warning']};
            }}
        """)
        self.wc_depth_input.setProperty("autocomplete_ignore", True)
        self.wc_depth_input.returnPressed.connect(self._on_wc_depth_search)
        depth_row.addWidget(self.wc_depth_input, 1)

        wc_depth_btn = QPushButton("🔎 태그검색")
        wc_depth_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        wc_depth_btn.setFixedWidth(130)
        wc_depth_btn.clicked.connect(self._on_wc_depth_search)
        depth_row.addWidget(wc_depth_btn)

        wc_layout.addLayout(depth_row)

        # === 상단 Row 5: 정보 표시 및 초기화 버튼 ===
        info_row = QHBoxLayout()
        info_row.setSpacing(8)

        self.wc_total_label = QLabel("전체: 0")
        self.wc_total_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(12)}px;")
        info_row.addWidget(self.wc_total_label)

        self.wc_current_label = QLabel("현재: 0")
        self.wc_current_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(12)}px;")
        info_row.addWidget(self.wc_current_label)

        info_row.addStretch()

        depth_reset_btn = QPushButton("↩️ 태그검색 초기화")
        depth_reset_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        depth_reset_btn.clicked.connect(self._on_wc_depth_reset)
        info_row.addWidget(depth_reset_btn)

        search_reset_btn = QPushButton("🔄 전체검색 초기화")
        search_reset_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        search_reset_btn.clicked.connect(self._on_wc_search_reset)
        info_row.addWidget(search_reset_btn)

        wc_layout.addLayout(info_row)

        # === 중간: 와일드카드 리스트 (스크롤 영역) ===
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: transparent;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 6px;
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: transparent;
            }}
        """)

        self.wc_list_widget = QWidget()
        self.wc_list_widget.setStyleSheet("background-color: transparent;")
        self.wc_list_layout = QVBoxLayout(self.wc_list_widget)
        self.wc_list_layout.setContentsMargins(4, 4, 4, 4)
        self.wc_list_layout.setSpacing(6)
        self.wc_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll_area.setWidget(self.wc_list_widget)
        wc_layout.addWidget(scroll_area, 1)

        # === 하단: 대기열 관리 ===
        # 구분선
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        separator.setFixedHeight(1)
        wc_layout.addWidget(separator)

        # 대기열 전체 추가 버튼
        queue_all_btn = QPushButton("📋 현재 검색 결과 모두 대기열로 보내기")
        queue_all_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        queue_all_btn.clicked.connect(self._on_wc_queue_all)
        wc_layout.addWidget(queue_all_btn)

        # 또 다른 구분선
        separator2 = QFrame()
        separator2.setFrameShape(QFrame.Shape.HLine)
        separator2.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        separator2.setFixedHeight(1)
        wc_layout.addWidget(separator2)

        # 대기열 상태 및 자동 생성
        queue_row = QHBoxLayout()
        queue_row.setSpacing(8)

        self.wc_queue_count_label = QLabel("남은 대기열: 0")
        self.wc_queue_count_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(12)}px;
            }}
        """)
        queue_row.addWidget(self.wc_queue_count_label)

        # 대기열 비우기 버튼
        queue_clear_btn = QPushButton("🗑️ 비우기")
        queue_clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['warning']};
                border: 1px solid {DARK_COLORS['warning']};
                border-radius: 4px;
                padding: 4px 12px;
                font-size: {get_scaled_font_size(12)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['warning']};
                color: {DARK_COLORS['bg_primary']};
            }}
        """)
        queue_clear_btn.setToolTip("대기열 모두 비우기")
        queue_clear_btn.clicked.connect(self._on_wc_queue_clear)
        queue_row.addWidget(queue_clear_btn)

        queue_row.addStretch()

        self.wc_auto_generate_check = QCheckBox("자동 생성")
        self.wc_auto_generate_check.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.wc_auto_generate_check.stateChanged.connect(self._on_wc_auto_generate_changed)
        queue_row.addWidget(self.wc_auto_generate_check)

        self.wc_generate_btn = QPushButton("▶️ 생성 시작")
        self.wc_generate_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.wc_generate_btn.setFixedWidth(150)
        self.wc_generate_btn.clicked.connect(self._on_wc_generate_start)
        queue_row.addWidget(self.wc_generate_btn)

        wc_layout.addLayout(queue_row)

        parent_tabs.addTab(wc_widget, "☑️ INST.WC")

        # 와일드카드 대기열 초기화
        self.wc_queue = []  # [(file_key, item_key), ...]
        self.wc_depth_filters = []  # 심층 검색 필터 스택

        # 초기 리스트 업데이트
        self._update_wc_list()

    # _sync_preset_combo, _on_remote_preset_changed, _update_preset_display는
    # PresetTabMixin (ui/remote/preset_tab.py)으로 이동됨

    def resizeEvent(self, event):
        """창 크기 변경 시 그리드 업데이트"""
        super().resizeEvent(event)
        # 창 크기 변경 시 프리셋 즐겨찾기 그리드 다시 계산 (PresetTabMixin)
        if hasattr(self, 'preset_favorites_grid_layout'):
            QTimer.singleShot(100, self._update_preset_favorites_grid)
        # 창 크기 변경 시 캐릭터 레퍼런스 즐겨찾기 그리드 다시 계산
        if hasattr(self, 'char_ref_favorites_grid_layout'):
            QTimer.singleShot(150, self._update_char_ref_favorites_grid)

    def closeEvent(self, event):
        """창 닫힘 이벤트"""
        self.window_closed.emit()
        event.accept()

    # 인스턴트 와일드카드 관련 메서드들은 InstantWcTabMixin (ui/remote/instant_wc_tab.py)으로 이동됨
