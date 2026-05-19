"""
Turbo Event Sequence Tab

Sliding Window Inpaint 기반 연속 이미지 시퀀스 생성 탭
"""

import copy
import random

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QFrame, QPushButton, QProgressBar, QCheckBox, QMenu
)
from PyQt6.QtCore import pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap

from interfaces.base_tab_module import BaseTabModule
from legacy_desktop.ui.theme import DARK_STYLES, DARK_COLORS
from legacy_desktop.ui.scaling_manager import get_scaled_font_size, get_scaled_size

from .widgets.event_search_widget import EventSearchWidget
from .widgets.sequence_tab_container import SequenceTabContainer
from .widgets.image_viewer_widget import ImageViewerWidget
from .widgets.history_panel import HistoryPanel
from .widgets.custom_event_dialog import CustomEventDialog


class TurboEventSequenceTabModule(BaseTabModule):
    """Turbo Event Sequence 탭 모듈 - 동적 로드용"""

    def __init__(self):
        super().__init__()
        self.widget: TurboEventSequenceTab = None
        self.NAI_compatibility = True
        self.WEBUI_compatibility = False
        self.COMFYUI_compatibility = False
        # 동적 생성 시 필요한 데이터
        self.initial_data = {}

    def setup(self, **kwargs):
        """탭 생성에 필요한 동적 데이터를 전달받는 메서드"""
        self.initial_data = kwargs

    def get_tab_title(self) -> str:
        return "🚀 Turbo Sequence"

    def get_tab_order(self) -> int:
        return 15

    def get_tab_type(self) -> str:
        return 'closable'  # 동적 생성용 - 요청 시에만 로드

    def can_close_tab(self) -> bool:
        return True

    def create_widget(self, parent: QWidget) -> QWidget:
        if self.widget is None:
            self.widget = TurboEventSequenceTab(self.app_context, parent)
        return self.widget


class TurboEventSequenceTab(QWidget):
    """Turbo Event Sequence 메인 위젯"""

    # 시그널 정의
    generation_started = pyqtSignal()
    generation_stopped = pyqtSignal()

    # 생성 상태 상수
    STATE_IDLE = 0           # 대기 중 (시퀀스 미선택)
    STATE_CONFIRMED = 1      # 시퀀스 확정됨, 해상도 선택 필요
    STATE_READY = 2          # 해상도 선택됨, 생성 가능
    STATE_FIRST_DONE = 3     # 첫 페이지 생성 완료
    STATE_GENERATING = 4     # 생성 중

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context

        # 상태 변수
        self.current_sequence = None
        self.generated_images = []
        self.is_generating = False
        self.worker = None
        self.confirmed_prompts = []
        self.original_prompts = []  # 🆕 원본 프롬프트 (수정 감지용)
        self.current_state = self.STATE_IDLE
        self.selected_direction = None  # 'horizontal' or 'vertical'
        self.current_generation_index = 0  # 현재 생성 중인 인덱스
        self._index_mapping = None  # 스킵 기능용 인덱스 매핑 (Worker 인덱스 → 원본 인덱스)
        self.current_parent_id = None  # 현재 선택된 Parent ID (그리드 저장용)
        self._waiting_continuous_after_grid_save = False  # continuous: wait for grid auto-save
        self.current_viewing_index = -1  # 현재 보고 있는 이미지 인덱스 (재생성용)
        self._grid_saved_for_current_sequence = False  # 현재 시퀀스에 대해 그리드가 저장되었는지

        self._init_ui()
        self._setup_ui_controls()

    def _init_ui(self):
        """UI 초기화"""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # Left Panel (검색 및 선택) - 고정 너비
        self.left_panel = self._create_left_panel()
        self.left_panel.setFixedWidth(get_scaled_size(610))
        main_layout.addWidget(self.left_panel)

        # Right Panel (뷰어 및 히스토리) - 나머지 공간 사용
        self.right_panel = self._create_right_panel()
        main_layout.addWidget(self.right_panel, stretch=1)

    def _setup_ui_controls(self):
        """UI 컨트롤 참조 설정 - search_widget에 외부 컨트롤 전달"""
        self.search_widget.set_ui_controls(
            save_btn=self.save_favorite_btn,
            countdown_label=self.countdown_label,
            skip_checkbox_getter=lambda: self.skip_generated_checkbox.isChecked()
        )

    def _create_left_panel(self) -> QWidget:
        """좌측 패널 생성 (검색 + 시퀀스 탭 컨테이너 + Favorite 컨트롤)"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 검색 위젯
        self.search_widget = EventSearchWidget(self.app_context, self)
        self.search_widget.parent_selected.connect(self._on_parent_selected)
        self.search_widget.preview_image_ready.connect(self._on_preview_image_ready)
        self.search_widget.favorite_saved.connect(self._on_favorite_saved)
        self.search_widget.continuous_generation_requested.connect(self._on_continuous_generation_requested)
        # 🆕 Event Viewer 버튼 연결
        self.search_widget.event_viewer_btn.clicked.connect(self._on_open_event_viewer)
        # 🆕 Custom Event 버튼 연결
        self.search_widget.custom_event_btn.clicked.connect(self._on_open_custom_event_dialog)
        layout.addWidget(self.search_widget, stretch=3)

        # 시퀀스 탭 컨테이너 (미리보기 + 수정 탭)
        self.sequence_tab_container = SequenceTabContainer(app_context=self.app_context, parent=self)
        self.sequence_tab_container.sequence_confirmed.connect(self._on_sequence_confirmed)
        self.sequence_tab_container.prompts_updated.connect(self._on_prompts_updated)
        self.sequence_tab_container.prompt_engineering_toggled.connect(self._on_prompt_engineering_toggled)
        self.sequence_tab_container.quick_first_page_requested.connect(self._on_quick_first_page)
        self.sequence_tab_container.quick_all_pages_requested.connect(self._on_quick_all_pages)
        # 🆕 Skip 상태 변경 시 그리드 업데이트
        self.sequence_tab_container.edit_widget.disable_state_changed.connect(self._on_disable_state_changed)
        # 🆕 편집 모드 종료 요청 시 UI 복원
        self.sequence_tab_container.close_editing_requested.connect(self._restore_ui_layout)
        layout.addWidget(self.sequence_tab_container, stretch=2)

        # 🆕 Favorite 및 연속 생성 컨트롤 패널 (시퀀스 미리보기 아래)
        favorite_panel = self._create_favorite_control_panel()
        layout.addWidget(favorite_panel)

        return panel

    def _create_favorite_control_panel(self) -> QFrame:
        """Favorite 및 연속 생성 컨트롤 패널 생성 (2줄 레이아웃)"""
        panel = QFrame()
        panel.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)

        main_layout = QVBoxLayout(panel)
        main_layout.setContentsMargins(8, 4, 8, 4)
        main_layout.setSpacing(2)

        # === 첫 번째 줄: Favorite 버튼 + 다음 이벤트 연속 생성 + 스킵 + 카운트다운 ===
        row1_layout = QHBoxLayout()
        row1_layout.setSpacing(8)

        # Favorite 저장 버튼
        self.save_favorite_btn = QPushButton("💖 Favorite에 저장")
        self.save_favorite_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: #ff6b9d;
                border: 1px solid #ff6b9d;
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px {get_scaled_size(10)}px;
                font-size: {get_scaled_font_size(12) + 4}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #ff6b9d;
                color: {DARK_COLORS['text_primary']};
            }}
            QPushButton:pressed {{
                background-color: #ff4081;
            }}
            QPushButton:disabled {{
                color: {DARK_COLORS['text_secondary']};
                background-color: {DARK_COLORS['bg_primary']};
                border-color: {DARK_COLORS['border']};
            }}
        """)
        self.save_favorite_btn.clicked.connect(self._on_save_favorite_btn_clicked)
        self.save_favorite_btn.setEnabled(False)
        self.save_favorite_btn.setToolTip("클릭하여 저장 옵션 선택 (원본 Favorite / Custom)")
        row1_layout.addWidget(self.save_favorite_btn)

        # 🆕 Favorite 저장 메뉴 생성
        self.save_menu = QMenu(self)
        menu_style = f"""
            QMenu {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 5px;
            }}
            QMenu::item {{
                padding: 8px 20px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """
        self.save_menu.setStyleSheet(menu_style)

        # 메뉴 액션 추가
        self.action_save_original = self.save_menu.addAction("💖 원본 Favorite 저장")
        self.action_save_original.triggered.connect(self._on_save_original_favorite)

        self.action_save_custom = self.save_menu.addAction("📝 Custom으로 저장")
        self.action_save_custom.triggered.connect(self._on_save_custom_clicked)

        # 연속 생성 체크박스
        self.continuous_checkbox = QCheckBox("🔄 다음 이벤트 연속 생성")
        self.continuous_checkbox.setStyleSheet(self._get_favorite_checkbox_style())
        self.continuous_checkbox.toggled.connect(self._on_continuous_toggled)
        self.continuous_checkbox.setToolTip("그리드 저장 완료 후 5초 뒤 다음 이벤트 자동 생성")
        row1_layout.addWidget(self.continuous_checkbox)

        # 이미 생성한 이벤트 건너뛰기 체크박스
        self.skip_generated_checkbox = QCheckBox("⏭️ 이미 생성한 이벤트 스킵")
        self.skip_generated_checkbox.setStyleSheet(self._get_favorite_checkbox_style())
        self.skip_generated_checkbox.setToolTip("저장된 그리드 이미지가 있는 이벤트 건너뛰기")
        self.skip_generated_checkbox.setEnabled(False)  # 연속 생성 활성화 시만 사용 가능
        row1_layout.addWidget(self.skip_generated_checkbox)

        row1_layout.addStretch()
        main_layout.addLayout(row1_layout)

        # === 두 번째 줄: 랜덤 연속 생성 + 카운트다운 ===
        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(8)

        # 🆕 랜덤 연속 생성 체크박스
        self.random_continuous_checkbox = QCheckBox("🎲 랜덤 이벤트 연속 생성")
        self.random_continuous_checkbox.setStyleSheet(self._get_favorite_checkbox_style())
        self.random_continuous_checkbox.toggled.connect(self._on_random_continuous_toggled)
        self.random_continuous_checkbox.setToolTip("그리드 저장 완료 후 5초 뒤 랜덤 이벤트 자동 생성 (전체 검색 결과에서)")
        row2_layout.addWidget(self.random_continuous_checkbox)

        # 카운트다운 라벨 (숨김)
        self.countdown_label = QLabel("")
        self.countdown_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(14) + 2}px;
            color: {DARK_COLORS['accent_blue']};
            font-weight: bold;
        """)
        self.countdown_label.hide()
        row2_layout.addWidget(self.countdown_label)

        row2_layout.addStretch()
        main_layout.addLayout(row2_layout)

        return panel

    def _get_favorite_checkbox_style(self) -> str:
        """Favorite 컨트롤용 체크박스 스타일 (폰트 +2px)"""
        return f"""
            QCheckBox {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(12) + 5}px;
                spacing: {get_scaled_size(4)}px;
            }}
            QCheckBox::indicator {{
                width: {get_scaled_size(14)}px;
                height: {get_scaled_size(14)}px;
            }}
            QCheckBox::indicator:unchecked {{
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(2)}px;
                background-color: {DARK_COLORS['bg_primary']};
            }}
            QCheckBox::indicator:checked {{
                border: 1px solid {DARK_COLORS['accent_blue']};
                border-radius: {get_scaled_size(2)}px;
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """

    def _on_save_favorite_btn_clicked(self):
        """Favorite 저장 버튼 클릭 - search_widget의 메서드 호출"""
        self.search_widget._on_save_favorite_clicked()

    def _on_continuous_toggled(self, checked: bool):
        """연속 생성 체크박스 토글"""
        self.search_widget._continuous_generation = checked
        # 두 체크박스 중 하나라도 활성화되면 스킵 체크박스 활성화
        self.skip_generated_checkbox.setEnabled(checked or self.random_continuous_checkbox.isChecked())

        if checked:
            # 🆕 랜덤 연속 생성과 상호 배타적
            if self.random_continuous_checkbox.isChecked():
                self.random_continuous_checkbox.setChecked(False)
            # 연속 생성 활성화 시 그리드 자동 저장 강제
            if not self.history_panel.auto_save_enabled:
                self.history_panel.auto_save_checkbox.setChecked(True)
            print(f"🔄 연속 생성: 활성화 (그리드 자동 저장이 강제 활성화됩니다)")
        else:
            print(f"🔄 연속 생성: 비활성화")

    def _on_random_continuous_toggled(self, checked: bool):
        """🆕 랜덤 연속 생성 체크박스 토글"""
        self.search_widget._random_continuous_generation = checked
        # 두 체크박스 중 하나라도 활성화되면 스킵 체크박스 활성화
        self.skip_generated_checkbox.setEnabled(checked or self.continuous_checkbox.isChecked())

        if checked:
            # 일반 연속 생성과 상호 배타적
            if self.continuous_checkbox.isChecked():
                self.continuous_checkbox.setChecked(False)
            # 연속 생성 활성화 시 그리드 자동 저장 강제
            if not self.history_panel.auto_save_enabled:
                self.history_panel.auto_save_checkbox.setChecked(True)
            print(f"🎲 랜덤 연속 생성: 활성화 (그리드 자동 저장이 강제 활성화됩니다)")
        else:
            print(f"🎲 랜덤 연속 생성: 비활성화")

    def _create_right_panel(self) -> QWidget:
        """우측 패널 생성 (이미지 뷰어 + 히스토리)"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 이미지 뷰어
        self.image_viewer = ImageViewerWidget(self)
        layout.addWidget(self.image_viewer, stretch=3)

        # 컨트롤 패널 (진행률 + 버튼)
        control_panel = self._create_control_panel()
        layout.addWidget(control_panel)

        # 히스토리 패널
        self.history_panel = HistoryPanel(app_context=self.app_context, parent=self)
        self.history_panel.image_selected.connect(self._on_history_image_selected)
        self.history_panel.skip_toggled.connect(self._on_history_skip_toggled)
        # 🆕 시퀀스 완료 시 그리드 저장 시그널
        self.history_panel.grid_auto_saved.connect(self._on_grid_auto_saved)
        # 🆕 순서 변경 시 재생성 버튼 비활성화
        self.history_panel.order_changed.connect(self._on_history_order_changed)
        # 🆕 클리어 후 시퀀스 재확정 요청 연결
        self.history_panel.clear_and_reconfirm.connect(self._on_clear_and_reconfirm)
        # 🆕 순서 변경 후 그리드 업데이트 요청 연결
        self.history_panel.request_grid_update.connect(self._on_request_grid_update)
        # 🆕 인페인트 요청 연결
        self.history_panel.inpaint_requested.connect(self._on_inpaint_requested)
        # 🆕 수동 그리드 저장/복사 시 turbo_events 업데이트
        self.history_panel.grid_manually_saved.connect(self._on_grid_manually_saved)
        # 🆕 외부 API 전송 요청 연결
        self.history_panel.export_requested.connect(self._on_export_requested)
        layout.addWidget(self.history_panel, stretch=1)

        return panel

    def _create_control_panel(self) -> QFrame:
        """컨트롤 패널 생성 - 단계별 워크플로우"""
        panel = QFrame()
        panel.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        # 상단: 진행률 표시
        progress_layout = QVBoxLayout()
        progress_layout.setSpacing(2)

        self.progress_label = QLabel("시퀀스를 확정해주세요")
        self.progress_label.setStyleSheet(f"""
            color: {DARK_COLORS['text_secondary']};
            font-size: {get_scaled_font_size(14) + 3}px;
        """)
        progress_layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(get_scaled_size(8))
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {DARK_COLORS['bg_primary']};
                border: none;
                border-radius: {get_scaled_size(4)}px;
            }}
            QProgressBar::chunk {{
                background-color: {DARK_COLORS['accent_blue']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        progress_layout.addWidget(self.progress_bar)
        layout.addLayout(progress_layout)

        # 하단: 버튼 영역
        button_layout = QHBoxLayout()
        button_layout.setSpacing(6)

        # === 1단계: 해상도 선택 버튼 (시퀀스 확정 후 표시) ===
        self.direction_frame = QFrame()
        direction_layout = QHBoxLayout(self.direction_frame)
        direction_layout.setContentsMargins(0, 0, 0, 0)
        direction_layout.setSpacing(4)

        direction_label = QLabel("해상도:")
        direction_label.setStyleSheet(f"""
            color: {DARK_COLORS['text_secondary']};
            font-size: {get_scaled_font_size(12) + 3}px;
        """)
        direction_layout.addWidget(direction_label)

        self.horizontal_btn = QPushButton("가로모드")
        self.horizontal_btn.setCheckable(True)
        self.horizontal_btn.setStyleSheet(self._get_direction_button_style())
        self.horizontal_btn.clicked.connect(lambda: self._on_direction_selected('horizontal'))
        direction_layout.addWidget(self.horizontal_btn)

        self.vertical_btn = QPushButton("세로모드")
        self.vertical_btn.setCheckable(True)
        self.vertical_btn.setStyleSheet(self._get_direction_button_style())
        self.vertical_btn.clicked.connect(lambda: self._on_direction_selected('vertical'))
        direction_layout.addWidget(self.vertical_btn)

        # 🆕 Line당 이미지 수 선택
        direction_layout.addWidget(QLabel(" │ "))  # 구분선

        line_label = QLabel("Line 당:")
        line_label.setStyleSheet(f"""
            color: {DARK_COLORS['text_secondary']};
            font-size: {get_scaled_font_size(12) + 3}px;
        """)
        direction_layout.addWidget(line_label)

        self.images_per_line = 1  # 기본값
        self.line_buttons = []

        for num in [1, 2, 3]:
            btn = QPushButton(str(num))
            btn.setCheckable(True)
            btn.setFixedSize(get_scaled_size(36), get_scaled_size(32))
            btn.setStyleSheet(self._get_line_button_style())
            btn.clicked.connect(lambda checked, n=num: self._on_images_per_line_selected(n))
            if num == 1:  # 기본값 선택
                btn.setChecked(True)
            self.line_buttons.append(btn)
            direction_layout.addWidget(btn)

        self.direction_frame.hide()
        button_layout.addWidget(self.direction_frame)

        button_layout.addStretch()

        # === 2단계: 첫 페이지/전체 생성 버튼 (해상도 선택 후 표시) ===
        self.initial_buttons_frame = QFrame()
        initial_layout = QHBoxLayout(self.initial_buttons_frame)
        initial_layout.setContentsMargins(0, 0, 0, 0)
        initial_layout.setSpacing(4)

        self.first_page_btn = QPushButton("🎨 첫 페이지 생성")
        self.first_page_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.first_page_btn.clicked.connect(self._on_first_page_clicked)
        initial_layout.addWidget(self.first_page_btn)

        self.full_sequence_btn = QPushButton("▶ 전체 시퀀스 생성")
        self.full_sequence_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.full_sequence_btn.clicked.connect(self._on_full_sequence_clicked)
        initial_layout.addWidget(self.full_sequence_btn)

        self.initial_buttons_frame.hide()
        button_layout.addWidget(self.initial_buttons_frame)

        # === 3단계: 첫 페이지 완료 후 버튼 (첫 페이지 생성 후 표시) ===
        # 2중 레이아웃: 상단에 버튼들, 하단에 배경 유지 체크박스
        self.after_first_frame = QFrame()
        after_first_main_layout = QVBoxLayout(self.after_first_frame)
        after_first_main_layout.setContentsMargins(0, 0, 0, 0)
        after_first_main_layout.setSpacing(get_scaled_size(4))

        # 상단: 버튼 행
        after_first_buttons_layout = QHBoxLayout()
        after_first_buttons_layout.setContentsMargins(0, 0, 0, 0)
        after_first_buttons_layout.setSpacing(4)

        self.regenerate_btn = QPushButton("🔄 재생성")
        self.regenerate_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.regenerate_btn.clicked.connect(self._on_regenerate_clicked)
        after_first_buttons_layout.addWidget(self.regenerate_btn)

        self.next_page_btn = QPushButton("➡️ 다음 페이지")
        self.next_page_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.next_page_btn.clicked.connect(self._on_next_page_clicked)
        after_first_buttons_layout.addWidget(self.next_page_btn)

        self.continue_all_btn = QPushButton("▶ 나머지 전체 생성")
        self.continue_all_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.continue_all_btn.clicked.connect(self._on_continue_all_clicked)
        after_first_buttons_layout.addWidget(self.continue_all_btn)

        after_first_main_layout.addLayout(after_first_buttons_layout)

        # 하단: 배경 유지 체크박스 행
        after_first_options_layout = QHBoxLayout()
        after_first_options_layout.setContentsMargins(0, 0, 0, 0)
        after_first_options_layout.setSpacing(get_scaled_size(8))

        self.keep_background_checkbox = QCheckBox("🎭 배경 정보 유지")
        self.keep_background_checkbox.setStyleSheet(f"""
            QCheckBox {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(12)}px;
            }}
            QCheckBox::indicator {{
                width: {get_scaled_size(16)}px;
                height: {get_scaled_size(16)}px;
            }}
            QCheckBox::indicator:unchecked {{
                border: 1px solid {DARK_COLORS['border']};
                background-color: {DARK_COLORS['bg_secondary']};
                border-radius: {get_scaled_size(3)}px;
            }}
            QCheckBox::indicator:checked {{
                border: 1px solid {DARK_COLORS['accent_blue']};
                background-color: {DARK_COLORS['accent_blue']};
                border-radius: {get_scaled_size(3)}px;
            }}
        """)
        self.keep_background_checkbox.setToolTip(
            "활성화 시 인물 영역만 Inpaint하여 배경을 유지합니다.\n"
            "YOLO 모델로 인물을 감지합니다."
        )
        self.keep_background_checkbox.clicked.connect(self._on_keep_background_clicked)
        self._ultralytics_checked = False  # ultralytics 설치 확인 플래그
        after_first_options_layout.addWidget(self.keep_background_checkbox)
        after_first_options_layout.addStretch()

        after_first_main_layout.addLayout(after_first_options_layout)

        self.after_first_frame.hide()
        button_layout.addWidget(self.after_first_frame)

        # === 취소 버튼 (생성 중에만 표시) ===
        self.cancel_btn = QPushButton("⏹ 취소")
        self.cancel_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.cancel_btn.setFixedWidth(get_scaled_size(130))
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        self.cancel_btn.hide()
        button_layout.addWidget(self.cancel_btn)

        layout.addLayout(button_layout)

        return panel

    def _get_direction_button_style(self) -> str:
        """해상도 선택 버튼 스타일"""
        return f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px {get_scaled_size(12)}px;
                font-size: {get_scaled_font_size(12) + 3}px;
            }}
            QPushButton:hover {{
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QPushButton:checked {{
                background-color: {DARK_COLORS['accent_blue']};
                color: {DARK_COLORS['text_primary']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
        """

    def _get_line_button_style(self) -> str:
        """Line당 이미지 수 버튼 스타일"""
        # 녹색 계열 색상 (DARK_COLORS에 없어서 직접 정의)
        accent_green = '#4CAF50'
        accent_green_dark = '#388E3C'

        return f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                font-size: {get_scaled_font_size(12) + 3}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                border-color: {accent_green};
            }}
            QPushButton:checked {{
                background-color: {accent_green};
                color: {DARK_COLORS['text_primary']};
                border-color: {accent_green_dark};
            }}
        """

    def _on_images_per_line_selected(self, num: int):
        """Line당 이미지 수 선택"""
        self.images_per_line = num

        # 버튼 상태 업데이트 (배타적 선택)
        for i, btn in enumerate(self.line_buttons):
            btn.setChecked(i + 1 == num)

        print(f"🔢 Line당 이미지 수: {num}")

        # 이미지가 있으면 그리드 업데이트 및 이미지 뷰어 반영
        if len(self.generated_images) > 0:
            grid_image = self._update_grid_image()
            if grid_image:
                self.image_viewer.set_image(grid_image)

    def _update_ui_state(self):
        """현재 상태에 따라 UI 업데이트"""
        # 모든 프레임 숨기기
        self.direction_frame.hide()
        self.initial_buttons_frame.hide()
        self.after_first_frame.hide()
        self.cancel_btn.hide()

        if self.current_state == self.STATE_IDLE:
            self.progress_label.setText("시퀀스를 확정해주세요")

        elif self.current_state == self.STATE_CONFIRMED:
            self.direction_frame.show()
            self.progress_label.setText("해상도를 선택해주세요")

        elif self.current_state == self.STATE_READY:
            self.direction_frame.show()
            self.initial_buttons_frame.show()
            direction_text = "가로" if self.selected_direction == 'horizontal' else "세로"
            self.progress_label.setText(f"📐 {direction_text} 모드 - 생성 준비 완료")

        elif self.current_state == self.STATE_FIRST_DONE:
            self.direction_frame.show()
            self.after_first_frame.show()  # 배경 유지 체크박스도 함께 표시됨
            remaining = len(self.confirmed_prompts) - len(self.generated_images)
            self.progress_label.setText(f"✅ 첫 페이지 완료 - 남은 페이지: {remaining}개")
            # 마지막 페이지면 다음/나머지 버튼 비활성화
            if remaining <= 0:
                self.next_page_btn.setEnabled(False)
                self.continue_all_btn.setEnabled(False)
            else:
                self.next_page_btn.setEnabled(True)
                self.continue_all_btn.setEnabled(True)

        elif self.current_state == self.STATE_GENERATING:
            self.cancel_btn.show()

    def _rearrange_ui_for_editing(self):
        """시퀀스 확정 후 UI 재배치 (편집 모드)

        - 검색 위젯 숨김
        - 시퀀스 컨테이너 확대 (전체 좌측 패널 공간 사용)
        - 프롬프트 입력 폰트/높이 증가
        """
        print("[UI] 편집 모드로 전환 - 검색 위젯 숨김, 프롬프트 영역 확대")

        # 업데이트 일시 정지 (깜빡임 방지)
        self.left_panel.setUpdatesEnabled(False)

        try:
            # 1. 검색 위젯 숨김
            self.search_widget.setVisible(False)

            # 2. 레이아웃에서 위젯 제거 후 재추가 (stretch 변경)
            left_layout = self.left_panel.layout()

            # favorite_panel을 동적으로 찾기 (3번째 위젯)
            favorite_panel = None
            if left_layout.count() >= 3:
                favorite_panel = left_layout.itemAt(2).widget()

            left_layout.removeWidget(self.search_widget)
            left_layout.removeWidget(self.sequence_tab_container)
            if favorite_panel:
                left_layout.removeWidget(favorite_panel)

            # 재추가 (search_widget는 숨김 상태이므로 공간 차지 안 함)
            left_layout.addWidget(self.search_widget, stretch=0)  # 숨김
            left_layout.addWidget(self.sequence_tab_container, stretch=1)  # 전체 공간
            if favorite_panel:
                left_layout.addWidget(favorite_panel)  # 고정 높이

            # 3. 시퀀스 컨테이너의 프롬프트 입력 확대
            self.sequence_tab_container.expand_prompt_editors()

        finally:
            # 업데이트 재개
            self.left_panel.setUpdatesEnabled(True)

    def _restore_ui_layout(self):
        """UI 레이아웃 복원 (검색 모드)

        - 검색 위젯 표시
        - 원래 stretch 비율 복원 (3:2)
        - 프롬프트 입력 원래 크기로
        """
        print("[UI] 검색 모드로 복원 - 검색 위젯 표시, 원래 비율 복원")

        # 업데이트 일시 정지
        self.left_panel.setUpdatesEnabled(False)

        try:
            # 1. 검색 위젯 표시
            self.search_widget.setVisible(True)

            # 2. stretch 복원
            left_layout = self.left_panel.layout()

            # favorite_panel을 동적으로 찾기 (3번째 위젯)
            favorite_panel = None
            if left_layout.count() >= 3:
                favorite_panel = left_layout.itemAt(2).widget()

            left_layout.removeWidget(self.search_widget)
            left_layout.removeWidget(self.sequence_tab_container)
            if favorite_panel:
                left_layout.removeWidget(favorite_panel)

            left_layout.addWidget(self.search_widget, stretch=3)
            left_layout.addWidget(self.sequence_tab_container, stretch=2)
            if favorite_panel:
                left_layout.addWidget(favorite_panel)

            # 3. 프롬프트 입력 축소
            self.sequence_tab_container.restore_prompt_editors()

        finally:
            # 업데이트 재개
            self.left_panel.setUpdatesEnabled(True)

    def _is_prompts_modified(self) -> bool:
        """프롬프트가 수정되었는지 확인

        Returns:
            True: 프롬프트가 수정됨
            False: 수정 없음 또는 비교 불가
        """
        if not self.original_prompts or not self.confirmed_prompts:
            return False

        if len(self.original_prompts) != len(self.confirmed_prompts):
            return True

        for original, current in zip(self.original_prompts, self.confirmed_prompts):
            # general 태그 비교
            if original.get('general', '') != current.get('general', ''):
                return True
            # rating 비교
            if str(original.get('rating', '')) != str(current.get('rating', '')):
                return True

        return False

    def _update_save_menu(self):
        """저장 메뉴 액션 활성화 조건 확인"""
        # Custom 저장: 프롬프트가 확정되었으면 항상 가능 (다이얼로그에서 추가 편집 가능)
        has_prompts = len(self.confirmed_prompts) > 0
        is_modified = self._is_prompts_modified()

        # Custom 액션은 프롬프트가 있으면 항상 활성화
        self.action_save_custom.setEnabled(has_prompts)

        # 버튼 색상: 수정 여부에 따라 변경 (주황 = 수정됨, 핑크 = 수정 안 됨)
        if has_prompts and is_modified:
            print("[Menu] 버튼 색상 변경 - 프롬프트 수정 감지 (주황)")
            # 버튼 색상을 주황색으로 변경 (수정됨 표시)
            self.save_favorite_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {DARK_COLORS['bg_tertiary']};
                    color: #ffa726;
                    border: 1px solid #ffa726;
                    border-radius: {get_scaled_size(4)}px;
                    padding: {get_scaled_size(4)}px {get_scaled_size(10)}px;
                    font-size: {get_scaled_font_size(12) + 4}px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: #ffa726;
                    color: {DARK_COLORS['text_primary']};
                }}
                QPushButton:pressed {{
                    background-color: #ff9800;
                }}
                QPushButton:disabled {{
                    color: {DARK_COLORS['text_secondary']};
                    background-color: {DARK_COLORS['bg_primary']};
                    border-color: {DARK_COLORS['border']};
                }}
            """)
        else:
            print("[Menu] 버튼 색상 변경 - 수정 없음 (핑크)")
            # 버튼 색상을 원래대로 (핑크)
            self.save_favorite_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {DARK_COLORS['bg_tertiary']};
                    color: #ff6b9d;
                    border: 1px solid #ff6b9d;
                    border-radius: {get_scaled_size(4)}px;
                    padding: {get_scaled_size(4)}px {get_scaled_size(10)}px;
                    font-size: {get_scaled_font_size(12) + 4}px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: #ff6b9d;
                    color: {DARK_COLORS['text_primary']};
                }}
                QPushButton:pressed {{
                    background-color: #ff4081;
                }}
                QPushButton:disabled {{
                    color: {DARK_COLORS['text_secondary']};
                    background-color: {DARK_COLORS['bg_primary']};
                    border-color: {DARK_COLORS['border']};
                }}
            """)

    def _generate_custom_event_id(self) -> int:
        """Custom 이벤트 ID 생성 (음수 ID 사용하여 NAI 데이터와 구분)"""
        return -random.randint(100000000, 999999999)

    def _on_save_favorite_btn_clicked(self):
        """Favorite 저장 버튼 클릭 - 메뉴 표시"""
        # 버튼 위치에서 메뉴 표시
        self.save_menu.exec(self.save_favorite_btn.mapToGlobal(self.save_favorite_btn.rect().bottomLeft()))

    def _on_save_original_favorite(self):
        """원본 Favorite 저장 (기존 동작)"""
        # EventSearchWidget의 내부 저장 메서드 호출
        self.search_widget._on_save_favorite_clicked()

    def _on_save_custom_clicked(self):
        """Custom 이벤트 저장 - CustomEventDialog 열기"""
        if not self.confirmed_prompts:
            print("[Custom] 저장 불가: 확정된 프롬프트 없음")
            return

        try:
            from pathlib import Path

            # CustomEventDialog 생성
            data_dir = Path("data")
            dialog = CustomEventDialog(
                data_dir=data_dir,
                app_context=self.app_context,
                parent=self
            )

            # 현재 프롬프트를 다이얼로그에 설정
            # Parent 프롬프트 설정
            parent_prompt = self.confirmed_prompts[0]
            dialog.parent_widget.set_prompt(parent_prompt.get('general', ''))
            dialog.parent_widget.set_rating(parent_prompt.get('rating', 's'))

            # Child 프롬프트 설정
            # 필요한 Child 수 계산
            num_children_needed = len(self.confirmed_prompts) - 1  # Parent 제외

            # 부족하면 추가
            while len(dialog.child_widgets) < num_children_needed:
                dialog._add_child_widget()

            # 많으면 삭제 (역순으로 삭제)
            while len(dialog.child_widgets) > num_children_needed:
                widget = dialog.child_widgets.pop()
                dialog.prompts_layout.removeWidget(widget)
                widget.setParent(None)
                widget.deleteLater()

            # 기존 Child 위젯에 프롬프트 설정 (인덱스 재정렬 포함)
            for i, prompt in enumerate(self.confirmed_prompts[1:], start=0):
                if i < len(dialog.child_widgets):
                    child = dialog.child_widgets[i]
                    child.set_prompt(prompt.get('general', ''))
                    child.set_rating(prompt.get('rating', 's'))
                    # 인덱스 재정렬 (i+1이 Child 번호)
                    child.update_index(i + 1)

            # 생성된 이미지가 있으면 썸네일로 설정
            if self.generated_images:
                print(f"[Custom] 생성된 이미지 {len(self.generated_images)}개를 썸네일로 설정")

                # Parent 이미지 설정 (인덱스 0)
                if len(self.generated_images) > 0 and self.generated_images[0] is not None:
                    parent_img = self.generated_images[0]
                    dialog.parent_widget.set_image(parent_img)
                    print("[Custom] Parent 썸네일 설정 완료")

                # Child 이미지 설정 (인덱스 1부터)
                for i in range(1, len(self.generated_images)):
                    img = self.generated_images[i]
                    child_index = i - 1  # Child 위젯 인덱스는 0부터 시작

                    if img is not None and child_index < len(dialog.child_widgets):
                        dialog.child_widgets[child_index].set_image(img)
                        print(f"[Custom] Child #{i} 썸네일 설정 완료")

                # 그리드 버튼 상태 업데이트
                dialog._update_grid_button_state()

            # diff 재계산
            dialog._recalculate_all_diffs()

            # TODO(web-dialog): 원래 CustomEventDialog.exec() — Web Shell 패널로 재구현 필요.
            print("[Dialog/SKIPPED] CustomEventDialog 차단 — Web Shell 재구현 예정")

        except Exception as e:
            print(f"❌ [Custom] CustomEventDialog 열기 실패: {e}")
            import traceback
            traceback.print_exc()

    # ===== 이벤트 핸들러 =====

    def _on_parent_selected(self, parent_id: int, sequence_df):
        """Parent 선택 시 시퀀스 미리보기 업데이트"""
        print(f"🎯 Parent selected: {parent_id}")
        self.current_sequence = sequence_df
        self.current_parent_id = parent_id  # 🆕 Parent ID 저장 (그리드 저장용)
        self._grid_saved_for_current_sequence = False  # 🆕 그리드 저장 플래그 리셋
        # set_sequence 호출하여 프롬프트 엔지니어링 적용
        self.sequence_tab_container.set_sequence(sequence_df)
        # 미리보기의 프롬프트를 수정 탭에 직접 반영 (프롬프트 엔지니어링 적용된 상태)
        preview_prompts = self.sequence_tab_container.get_preview_prompts()
        processed_prompts = self.sequence_tab_container._preprocess_prompts(preview_prompts)
        self.sequence_tab_container.edit_widget.set_prompts(processed_prompts)
        self.confirmed_prompts = processed_prompts
        # 🆕 검색 위젯에 시퀀스 데이터 전달 (Favorite 저장용)
        self.search_widget.set_current_sequence(parent_id, sequence_df)
        # 상태 초기화
        self.current_state = self.STATE_IDLE
        self.selected_direction = None
        self.horizontal_btn.setChecked(False)
        self.vertical_btn.setChecked(False)
        self._update_ui_state()

    def _on_prompts_updated(self, prompts: list):
        """프롬프트 수정 시 (수정 탭에서)"""
        print(f"📝 Prompts updated: {len(prompts)} items")
        self.confirmed_prompts = prompts
        # 🆕 Custom 저장 버튼 활성화 조건 확인
        self._update_save_menu()

    def _on_prompt_engineering_toggled(self, checked: bool):
        """프롬프트 엔지니어링 토글 시 - 시퀀스 재생성 (수정 탭 유지)"""
        print(f"🔧 Prompt engineering toggled: {checked}")
        # 현재 시퀀스가 있으면 재생성
        if self.current_sequence is not None:
            print("🔄 Regenerating sequence due to prompt engineering toggle...")
            # set_sequence 호출하여 프롬프트 엔지니어링 적용
            self.sequence_tab_container.set_sequence(self.current_sequence)
            # 미리보기의 프롬프트를 수정 탭에 직접 반영
            preview_prompts = self.sequence_tab_container.get_preview_prompts()
            processed_prompts = self.sequence_tab_container._preprocess_prompts(preview_prompts)
            self.sequence_tab_container.edit_widget.set_prompts(processed_prompts)
            self.confirmed_prompts = processed_prompts
            # 수정 탭으로 전환
            self.sequence_tab_container.switch_to_edit()

    def _on_disable_state_changed(self, index: int, disabled: bool):
        """Skip 상태 변경 시 그리드 업데이트"""
        print(f"🔇 #{index} Skip state changed: {'disabled' if disabled else 'enabled'}")
        # 이미지가 있으면 그리드 업데이트
        if len(self.generated_images) > 0:
            self._update_grid_image()

    def _on_sequence_confirmed(self, prompts: list):
        """시퀀스 확정 시"""
        print(f"✅ Sequence confirmed: {len(prompts)} prompts")
        self.confirmed_prompts = prompts
        self.original_prompts = copy.deepcopy(prompts)  # 🆕 원본 프롬프트 저장 (수정 감지용)
        self.generated_images = []
        self.current_generation_index = 0
        self.current_viewing_index = -1  # 🆕 초기화
        # 히스토리 클리어
        self.history_panel.clear()
        self.image_viewer.clear()
        # 🆕 재생성 버튼 재활성화 (새 시퀀스이므로 순서 변경 상태 초기화)
        self.regenerate_btn.setEnabled(True)
        self.regenerate_btn.setToolTip("재생성할 이미지를 선택해주세요")
        # 🆕 UI 재배치 (편집 모드)
        self._rearrange_ui_for_editing()
        # 🆕 Custom 저장 버튼 초기화 (수정 없음 상태)
        self._update_save_menu()
        # 🆕 자동으로 가로 해상도 선택
        self._on_direction_selected('horizontal')

    def _on_quick_first_page(self, prompts: list):
        """🆕 ⏩ 빠른 결정 + 첫 페이지 생성"""
        print(f"⏩ Quick first page: {len(prompts)} prompts")
        # 시퀀스 확정 로직 실행
        self.confirmed_prompts = prompts
        self.original_prompts = copy.deepcopy(prompts)  # 🆕 원본 프롬프트 저장 (수정 감지용)
        self.generated_images = []
        self.current_generation_index = 0
        self.current_viewing_index = -1
        self.history_panel.clear()
        self.image_viewer.clear()
        self.regenerate_btn.setEnabled(True)
        self.regenerate_btn.setToolTip("재생성할 이미지를 선택해주세요")
        # 🆕 UI 재배치 (편집 모드)
        self._rearrange_ui_for_editing()
        # 🆕 Custom 저장 버튼 초기화 (수정 없음 상태)
        self._update_save_menu()
        # 자동으로 가로 해상도 선택 후 첫 페이지 생성
        self._on_direction_selected('horizontal')
        # 바로 첫 페이지 생성 시작
        self._start_single_generation(0)

    def _on_quick_all_pages(self, prompts: list):
        """🆕 ⏭ 빠른 결정 + 전체 시퀀스 생성"""
        print(f"⏭ Quick all pages: {len(prompts)} prompts")
        # 시퀀스 확정 로직 실행
        self.confirmed_prompts = prompts
        self.original_prompts = copy.deepcopy(prompts)  # 🆕 원본 프롬프트 저장 (수정 감지용)
        self.generated_images = []
        self.current_generation_index = 0
        self.current_viewing_index = -1
        self.history_panel.clear()
        self.image_viewer.clear()
        self.regenerate_btn.setEnabled(True)
        self.regenerate_btn.setToolTip("재생성할 이미지를 선택해주세요")
        # 🆕 UI 재배치 (편집 모드)
        self._rearrange_ui_for_editing()
        # 🆕 Custom 저장 버튼 초기화 (수정 없음 상태)
        self._update_save_menu()
        # 자동으로 가로 해상도 선택 후 전체 생성
        self._on_direction_selected('horizontal')
        # 바로 전체 시퀀스 생성 시작
        self._start_full_generation(start_index=0)

    def _on_direction_selected(self, direction: str):
        """해상도 선택"""
        # 기존에 생성된 이미지가 있고, 방향이 변경되는 경우 경고
        if (len(self.generated_images) > 0 and
            self.selected_direction is not None and
            self.selected_direction != direction):
            # 경고 다이얼로그 표시
            if not self._show_direction_change_warning():
                # 취소 시 기존 방향 유지
                return

        self.selected_direction = direction
        # 버튼 상태 업데이트 (배타적 선택)
        if direction == 'horizontal':
            self.horizontal_btn.setChecked(True)
            self.vertical_btn.setChecked(False)
        else:
            self.horizontal_btn.setChecked(False)
            self.vertical_btn.setChecked(True)
        # 생성 준비 완료 상태로 전환
        self.current_state = self.STATE_READY
        self._update_ui_state()

    def _show_direction_change_warning(self) -> bool:
        """해상도 변경 경고 다이얼로그.
        TODO(web-dialog): 원래 QMessageBox(Yes/No) destructive confirm — Web Shell 모달로 재구현 필요.
        안전 기본값: 변경 차단 (False) → 기존 방향 유지."""
        print("[Dialog/CONFIRM(skipped→No)] 해상도 변경 경고 차단 — Web Shell 재구현 예정")
        return False
        # 아래 원본 흐름:
        from PyQt6.QtWidgets import QMessageBox
        msg = QMessageBox(self)
        msg.setWindowTitle("⚠️ 해상도 변경 경고")
        msg.setText("해상도를 변경하면 생성된 이미지가 모두 삭제됩니다.")
        msg.setInformativeText("계속하시겠습니까?")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        result = msg.exec()
        if result == QMessageBox.StandardButton.Yes:
            # 이미지 초기화
            self.generated_images = []
            self.history_panel.clear()
            self.image_viewer.clear()
            print("🗑️ 해상도 변경으로 이미지 초기화됨")
            return True
        else:
            print("❌ 해상도 변경 취소")
            return False

    def _on_first_page_clicked(self):
        """첫 페이지 생성 버튼 클릭"""
        if not self.confirmed_prompts or not self.selected_direction:
            return
        print(f"🎨 Generating first page...")
        self._start_single_generation(0)

    def _on_full_sequence_clicked(self):
        """전체 시퀀스 생성 버튼 클릭"""
        if not self.confirmed_prompts or not self.selected_direction:
            return
        print(f"🚀 Starting full sequence generation with {len(self.confirmed_prompts)} prompts")
        self._start_full_generation(start_index=0)

    def _on_regenerate_clicked(self):
        """재생성 버튼 클릭 - 현재 보고 있는 인덱스 재생성"""
        if not self.confirmed_prompts or not self.selected_direction:
            return

        # 🆕 현재 보고 있는 인덱스 사용
        current_index = self.current_viewing_index

        # 유효성 검사
        if current_index < 0:
            print("⚠️ 재생성 불가: 그리드가 선택되었거나 유효하지 않은 인덱스입니다.")
            # 툴팁 등으로 사용자에게 알림을 주면 더 좋음
            return

        # 인덱스 범위 확인
        if current_index >= len(self.confirmed_prompts):
            print(f"⚠️ 재생성 불가: 인덱스 범위 초과 ({current_index})")
            return

        print(f"🔄 Regenerating page {current_index}...")
        # 해당 인덱스의 이미지 교체
        self._start_single_generation(current_index, is_regenerate=True)

    def _on_next_page_clicked(self):
        """다음 페이지 생성 버튼 클릭"""
        if not self.confirmed_prompts or not self.selected_direction:
            return
        next_index = len(self.generated_images)
        if next_index >= len(self.confirmed_prompts):
            return
        print(f"➡️ Generating next page ({next_index + 1}/{len(self.confirmed_prompts)})...")
        self._start_single_generation(next_index)

    def _on_continue_all_clicked(self):
        """나머지 전체 생성 버튼 클릭"""
        if not self.confirmed_prompts or not self.selected_direction:
            return
        # 이미 생성된 이미지 수(빈 슬롯 제외)를 기준으로 이어서 생성
        start_index = sum(1 for img in self.generated_images if img is not None)
        if start_index >= len(self.confirmed_prompts):
            return
        print(f"▶ Continuing from page {start_index + 1}...")
        self._start_full_generation(start_index=start_index)

    def _on_cancel_clicked(self):
        """취소 버튼 클릭"""
        if self.worker:
            self.worker.cancel()
            self.progress_label.setText("취소 중...")

    def _on_history_image_selected(self, index: int, image):
        """히스토리에서 이미지 선택"""
        self.image_viewer.set_image(image)

        # 🆕 현재 보고 있는 인덱스 업데이트 (히스토리 인덱스 -> 원본 인덱스)
        # 히스토리 0번은 그리드 -> -1 (재생성 불가)
        # 히스토리 1번은 첫번째 이미지(인덱스 0) -> 0
        self.current_viewing_index = index - 1

        # 재생성 버튼 툴팁 업데이트
        if self.current_viewing_index >= 0:
            self.regenerate_btn.setToolTip(f"현재 선택된 이미지 (#{self.current_viewing_index}) 재생성")
        else:
            self.regenerate_btn.setToolTip("재생성할 이미지를 선택해주세요")

    def _on_favorite_saved(self, parent_id: int):
        """Favorite 저장 완료"""
        print(f"💖 Favorite saved for parent {parent_id}")
        # Favorites 모드인 경우 데이터셋 새로고침
        self.search_widget.refresh_favorites()

    def _on_grid_auto_saved(self, save_path: str):
        """그리드 자동 저장 완료 (HistoryPanel에서 호출)

        Note: 연속 생성 모드일 경우 다음 생성 카운트다운을 시작합니다.
        """
        print(f"💾 Grid auto saved (history_panel): {save_path}")

        if self._waiting_continuous_after_grid_save:
            self._waiting_continuous_after_grid_save = False
            if self.search_widget.is_continuous_generation_enabled():
                print("[continuous] countdown start after grid auto-save")
                self.search_widget.start_countdown_to_next()

    def _on_continuous_generation_requested(self, parent_id: int):
        """연속 생성 요청 - 자동으로 전체 시퀀스 생성 시작"""
        print(f"🔄 Continuous generation requested for parent {parent_id}")
        # 현재 시퀀스 데이터 확정
        if not self.sequence_tab_container.confirm_current_sequence():
            print("❌ 시퀀스 확정 실패: 데이터가 유효하지 않음")
            return
        # 연속 생성 시 그리드 자동 저장 강제 활성화
        if not self.history_panel.auto_save_enabled:
            self.history_panel.auto_save_checkbox.setChecked(True)
        # 자동으로 전체 시퀀스 생성 시작
        self._on_full_sequence_clicked()

    def _on_history_order_changed(self):
        """히스토리 패널에서 위젯 순서 변경 시 - 재생성 버튼 비활성화

        순서가 변경되면 원본 프롬프트 인덱스와 히스토리 인덱스가 불일치하므로
        재생성 기능을 비활성화합니다.
        """
        print("⚠️ 히스토리 순서 변경됨 - 재생성 버튼 비활성화")
        self.regenerate_btn.setEnabled(False)
        self.regenerate_btn.setToolTip("순서가 변경되어 재생성을 사용할 수 없습니다")

    def _on_clear_and_reconfirm(self):
        """클리어 후 시퀀스 재확정 - 현재 이벤트의 시퀀스를 다시 확정"""
        print("🔄 클리어 후 시퀀스 재확정 요청")

        # 현재 시퀀스가 있는 경우에만 재확정
        if self.current_sequence is not None:
            # 상태 초기화
            self.generated_images = []
            self.current_generation_index = 0
            self.current_viewing_index = -1
            self.image_viewer.clear()

            # 시퀀스 재확정 (sequence_tab_container의 confirm 호출)
            if self.sequence_tab_container.confirm_current_sequence():
                print("✅ 시퀀스 재확정 완료")
            else:
                print("⚠️ 시퀀스 재확정 실패 (데이터 없음)")
        else:
            print("⚠️ 재확정할 시퀀스가 없습니다")

    def _on_request_grid_update(self):
        """순서 변경 후 그리드 업데이트 요청"""
        print("🖼️ 순서 변경 후 그리드 업데이트 요청")
        if len(self.generated_images) > 0:
            grid_image = self._update_grid_image()
            if grid_image:
                # 그리드 이미지를 이미지 뷰어에도 표시
                self.image_viewer.set_image(grid_image)

    def _on_history_skip_toggled(self, history_index: int, is_skipped: bool):
        """히스토리 패널에서 Skip 토글 - sequence_edit_widget과 동기화

        Args:
            history_index: 히스토리 인덱스 (1부터 시작, 0은 그리드)
            is_skipped: Skip 상태
        """
        # 히스토리 인덱스를 원본 인덱스로 변환 (1→0, 2→1, ...)
        original_index = history_index - 1
        if original_index >= 0:
            # sequence_edit_widget의 Skip 상태 업데이트
            self.sequence_tab_container.edit_widget.set_disabled(original_index, is_skipped)
            print(f"🔇 History → Edit: #{original_index} Skip = {is_skipped}")

    def _on_preview_image_ready(self, image):
        """미리보기 이미지 준비 완료 - 이미지 뷰어에 표시"""
        if image is not None:
            self.image_viewer.set_image(image)
        else:
            # 미리보기 해제 시 이미지 뷰어 클리어
            self.image_viewer.clear()

    # ===== 생성 로직 =====

    def _start_single_generation(self, index: int, is_regenerate: bool = False):
        """단일 이미지 생성 시작"""
        self.is_generating = True
        self.current_generation_index = index
        self._is_regenerate = is_regenerate

        # UI 상태 업데이트
        self.current_state = self.STATE_GENERATING
        self._update_ui_state()
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(1)
        page_type = "Parent" if index == 0 else f"Child {index}"
        self.progress_label.setText(f"🎨 {page_type} 생성 중...")

        # 🆕 현재 생성 중인 인덱스 하이라이트
        self.sequence_tab_container.set_highlight_index(index)

        # Worker 생성 및 연결
        from .workers import SequenceGenerationWorker

        # 단일 생성: 해당 인덱스만 포함하는 프롬프트 리스트
        single_prompt = [self.confirmed_prompts[index]]

        # 이전 이미지가 있는 경우 전달 (inpaint용)
        prev_images = self.generated_images[:index] if index > 0 else []

        self.worker = SequenceGenerationWorker(
            app_context=self.app_context,
            prompts=single_prompt,
            direction=self.selected_direction,
            strength=1.0,
            negative_prompt=self._get_negative_prompt(),
            prev_images=prev_images,
            start_index=index,
            keep_background=self.keep_background_checkbox.isChecked()
        )

        # 시그널 연결
        self.worker.image_generated.connect(self._on_single_image_generated_wrapper)
        self.worker.progress_updated.connect(self._on_progress_updated)
        self.worker.generation_finished.connect(self._on_single_generation_finished_wrapper)
        self.worker.generation_error.connect(self._on_generation_error)
        self.worker.generation_cancelled.connect(self._on_generation_cancelled)

        # 시작 (QObject 기반이므로 start_generation 호출)
        self.worker.start_generation()
        self.generation_started.emit()

    def _start_full_generation(self, start_index: int = 0):
        """전체 시퀀스 생성 시작"""
        self.is_generating = True
        self._is_regenerate = False
        self.current_generation_index = start_index  # 🆕 현재 생성 인덱스 추적

        # 🆕 스킵된 인덱스 가져오기
        disabled_indices = self.sequence_tab_container.edit_widget.get_disabled_indices()

        # 🆕 스킵되지 않은 프롬프트만 필터링 (start_index 이후)
        # 원본 인덱스와 프롬프트 매핑 유지
        prompts_with_indices = []
        for i, prompt in enumerate(self.confirmed_prompts):
            if i >= start_index and i not in disabled_indices:
                prompts_with_indices.append((i, prompt))

        if not prompts_with_indices:
            print("⚠️ 생성할 프롬프트가 없습니다 (모두 스킵됨)")
            self.is_generating = False
            return

        # 원본 인덱스 매핑 저장 (Worker 인덱스 → 원본 인덱스)
        self._index_mapping = [idx for idx, _ in prompts_with_indices]
        prompts_to_generate = [prompt for _, prompt in prompts_with_indices]

        # UI 상태 업데이트
        self.current_state = self.STATE_GENERATING
        self._update_ui_state()
        remaining = len(prompts_to_generate)
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(remaining)
        self.progress_label.setText(f"🚀 시퀀스 생성 시작... (0/{remaining})")

        # 🆕 히스토리 패널에 플레이스홀더 생성 (스킵되지 않은 것만)
        if start_index == 0 and not any(img is not None for img in self.generated_images):
            # 새로운 생성: 스킵되지 않은 프롬프트 수만큼 플레이스홀더 생성
            non_skipped_count = len([i for i in range(len(self.confirmed_prompts)) if i not in disabled_indices])
            self.history_panel.prepare_placeholders(non_skipped_count)

        # 🆕 첫 번째 생성할 인덱스로 하이라이트
        first_index = self._index_mapping[0] if self._index_mapping else start_index
        self.sequence_tab_container.set_highlight_index(first_index)

        # 이전 이미지들 (inpaint용)
        prev_images = self.generated_images[:start_index] if start_index > 0 else []

        # Worker 생성 및 연결
        from .workers import SequenceGenerationWorker

        self.worker = SequenceGenerationWorker(
            app_context=self.app_context,
            prompts=prompts_to_generate,
            direction=self.selected_direction,
            strength=1.0,
            negative_prompt=self._get_negative_prompt(),
            prev_images=prev_images,
            start_index=0,  # Worker 내부 인덱스는 0부터 시작
            keep_background=self.keep_background_checkbox.isChecked()
        )

        # 시그널 연결
        self.worker.image_generated.connect(self._on_image_generated)
        self.worker.progress_updated.connect(self._on_progress_updated)
        self.worker.generation_finished.connect(self._on_full_generation_finished)
        self.worker.generation_error.connect(self._on_generation_error)
        self.worker.generation_cancelled.connect(self._on_generation_cancelled)

        # 시작 (QObject 기반이므로 start_generation 호출)
        self.worker.start_generation()
        self.generation_started.emit()

    def _on_single_image_generated_wrapper(self, index: int, image):
        """단일 이미지 생성 완료 wrapper"""
        is_regenerate = getattr(self, '_is_regenerate', False)
        self._on_single_image_generated(index, image, is_regenerate)

    def _on_single_image_generated(self, index: int, image, is_regenerate: bool):
        """단일 이미지 생성 완료"""
        if is_regenerate and index < len(self.generated_images):
            # 재생성: 기존 이미지 교체
            self.generated_images[index] = image
        else:
            # 새 이미지: 리스트에 추가
            while len(self.generated_images) <= index:
                self.generated_images.append(None)
            self.generated_images[index] = image

        self.image_viewer.set_image(image)
        self.history_panel.add_image(index, image)

        # 🆕 현재 보고 있는 인덱스 업데이트 (방금 생성된 이미지 보기)
        self.current_viewing_index = index

        # 🆕 그리드 이미지 업데이트
        self._update_grid_image()

    def _on_single_generation_finished_wrapper(self, images: list):
        """단일 생성 완료 wrapper"""
        is_regenerate = getattr(self, '_is_regenerate', False)
        index = self.current_generation_index
        self._on_single_generation_finished(index, images, is_regenerate)

    def _on_single_generation_finished(self, index: int, images: list, is_regenerate: bool):
        """단일 생성 완료"""
        self.is_generating = False
        self.progress_bar.setValue(1)
        self._cleanup_worker()

        # 🆕 하이라이트 제거
        self.sequence_tab_container.clear_highlight()

        # 첫 페이지 완료 상태로 전환
        self.current_state = self.STATE_FIRST_DONE
        self._update_ui_state()

    def _on_image_generated(self, worker_index: int, image):
        """개별 이미지 생성 완료 (전체 생성 시)"""
        # 🆕 Worker 인덱스를 원본 인덱스로 변환
        index_mapping = getattr(self, '_index_mapping', None)
        if index_mapping and worker_index < len(index_mapping):
            actual_index = index_mapping[worker_index]
        else:
            actual_index = worker_index

        # generated_images 리스트 확장 및 이미지 저장
        while len(self.generated_images) <= actual_index:
            self.generated_images.append(None)
        self.generated_images[actual_index] = image

        self.image_viewer.set_image(image)
        # 실제 인덱스에 맞춰 히스토리 갱신 (이어 생성 시 기존 슬롯 유지)
        self.history_panel.add_image(actual_index, image)

        # 🆕 현재 보고 있는 인덱스 업데이트 (방금 생성된 이미지 보기)
        self.current_viewing_index = actual_index

        # 🆕 현재 생성 인덱스 업데이트 (다음 Worker 인덱스로)
        next_worker_index = worker_index + 1
        if index_mapping and next_worker_index < len(index_mapping):
            # 다음 원본 인덱스로 하이라이트
            next_actual_index = index_mapping[next_worker_index]
            self.current_generation_index = next_actual_index
            self.sequence_tab_container.set_highlight_index(next_actual_index)
        else:
            self.current_generation_index = actual_index + 1

        # 🆕 그리드 이미지 업데이트
        self._update_grid_image()

    def _on_progress_updated(self, current: int, total: int, message: str):
        """진행률 업데이트"""
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

        # 🆕 원본 인덱스로 변환하여 메시지 업데이트
        index_mapping = getattr(self, '_index_mapping', None)
        if index_mapping and current < len(index_mapping):
            actual_index = index_mapping[current]
            page_type = "Parent" if actual_index == 0 else f"Child {actual_index}"
            self.progress_label.setText(f"{page_type} 생성 중... ({current + 1}/{total})")
        else:
            self.progress_label.setText(message)

        # 🆕 현재 생성 중인 인덱스 하이라이트
        if index_mapping and current < len(index_mapping):
            highlight_index = index_mapping[current]
            self.sequence_tab_container.set_highlight_index(highlight_index)

    def _on_full_generation_finished(self, images: list):
        """전체 생성 완료"""
        self.is_generating = False
        self._cleanup_worker()

        # 🆕 인덱스 매핑 정리
        self._index_mapping = None

        # 실제 생성된 이미지 수 (None 제외)
        valid_count = sum(1 for img in self.generated_images if img is not None)
        self.progress_label.setText(f"✅ 완료: {valid_count}개 이미지 생성")

        # 🆕 하이라이트 제거
        self.sequence_tab_container.clear_highlight()

        # 🆕 최종 그리드 이미지 생성 및 표시 (시퀀스 완료 - 자동 저장)
        # continuous: start next event after grid auto-save completes
        self._waiting_continuous_after_grid_save = True
        grid_image = self._update_grid_image(is_sequence_complete=True)
        if grid_image:
            # 그리드 이미지를 이미지 뷰어에 표시
            self.image_viewer.set_image(grid_image)

        # 첫 페이지 완료 상태로 전환 (더 이상 생성할 것 없음)
        self.current_state = self.STATE_FIRST_DONE
        self._update_ui_state()

    def _on_generation_error(self, index: int, error_msg: str):
        """생성 에러"""
        self.is_generating = False
        self._cleanup_worker()

        # 🆕 인덱스 매핑 정리
        self._index_mapping = None

        self.progress_label.setText(f"❌ 에러 (#{index}): {error_msg}")

        # 🆕 하이라이트 제거
        self.sequence_tab_container.clear_highlight()

        # 이전 상태로 복귀
        if len(self.generated_images) > 0:
            self.current_state = self.STATE_FIRST_DONE
        else:
            self.current_state = self.STATE_READY
        self._update_ui_state()

    def _on_generation_cancelled(self):
        """생성 취소됨"""
        self.is_generating = False
        self._cleanup_worker()

        # 🆕 인덱스 매핑 정리
        self._index_mapping = None

        self.progress_label.setText("⏹ 취소됨")

        # 🆕 하이라이트 제거
        self.sequence_tab_container.clear_highlight()

        # 이전 상태로 복귀
        if len(self.generated_images) > 0:
            self.current_state = self.STATE_FIRST_DONE
        else:
            self.current_state = self.STATE_READY
        self._update_ui_state()

    def _get_negative_prompt(self) -> str:
        """네거티브 프롬프트 가져오기"""
        try:
            return self.app_context.main_window.negative_prompt_textedit.toPlainText().strip()
        except:
            return ""

    def _cleanup_worker(self):
        """Worker 정리 - QObject 기반 worker의 리소스 정리"""
        if self.worker:
            try:
                # 이벤트 구독 해제 (worker 내부에서도 처리하지만 안전하게)
                self.worker._unsubscribe_generation_events()
            except:
                pass
            self.worker.deleteLater()
            self.worker = None
        self.generation_stopped.emit()

    def _update_grid_image(self, is_sequence_complete: bool = False):
        """그리드 이미지 생성 및 히스토리 업데이트

        그리드 배치 규칙:
        - Line당 이미지 수 (images_per_line)에 따라 배치
        - 가로 방향 (horizontal): 세로로 쌓기 (기본 1열)
        - 세로 방향 (vertical): 사용자 지정 열 수
        - 🆕 히스토리 패널의 드래그 순서 반영

        Args:
            is_sequence_complete: 시퀀스가 완료되었는지 여부 (True면 자동 저장)

        Returns:
            PIL.Image: 생성된 그리드 이미지 (이미지가 2개 이상인 경우)
            None: 이미지가 1개 이하인 경우
        """
        from PIL import Image

        # 🆕 히스토리 패널의 순서대로 이미지 가져오기 (Skip 제외)
        valid_images = self.history_panel.get_ordered_images()

        if len(valid_images) < 2:
            return None

        # 첫 번째 이미지 크기 기준
        img_w, img_h = valid_images[0].size
        count = len(valid_images)

        # 🆕 Line당 이미지 수 사용
        cols = getattr(self, 'images_per_line', 2)

        # 방향에 따른 그리드 레이아웃
        if self.selected_direction == 'horizontal':
            # 가로 방향: 세로로 쌓기 (Line당 이미지 수 적용)
            rows = (count + cols - 1) // cols  # 올림 처리
            grid_w = img_w * cols
            grid_h = img_h * rows
        else:
            # 세로 방향: Line당 이미지 수 적용
            rows = (count + cols - 1) // cols  # 올림 처리
            grid_w = img_w * cols
            grid_h = img_h * rows

        # 그리드 생성 (다크 배경)
        grid_image = Image.new('RGB', (grid_w, grid_h), (30, 30, 30))

        for i, img in enumerate(valid_images):
            # 이미지 데이터 로드
            if hasattr(img, 'load'):
                img.load()

            # 크기 맞추기
            if img.size != (img_w, img_h):
                img = img.resize((img_w, img_h), Image.Resampling.LANCZOS)

            # Line당 이미지 수에 따라 배치
            col = i % cols
            row = i // cols
            x = col * img_w
            y = row * img_h

            grid_image.paste(img, (x, y))

        # 🔧 디버깅용: 그리드 이미지 표시
        layout_type = f"{cols} per line ({rows} rows)"
        print(f"🖼️ Grid image created: {grid_w}x{grid_h} ({count} images, {layout_type})")

        # 히스토리 패널에 그리드 이미지 업데이트 (시퀀스 완료 시에만 자동 저장 트리거)
        self.history_panel.update_grid_image(grid_image, trigger_auto_save=is_sequence_complete)

        # 🆕 시퀀스 완료 여부 자동 감지 (모든 슬롯이 채워졌는지 확인)
        # is_sequence_complete가 명시적으로 True이거나, 모든 슬롯이 채워진 경우 저장
        all_slots_filled = False
        if self.confirmed_prompts:
            total_slots = len(self.confirmed_prompts)
            # 히스토리 패널의 모든 슬롯에 이미지가 있는지 확인
            all_slots_filled = self.history_panel.are_all_slots_filled(total_slots)
            if all_slots_filled and not is_sequence_complete and not self._grid_saved_for_current_sequence:
                print(f"✨ 모든 슬롯 채워짐: {total_slots}개 - 미리보기용 저장 트리거")

        # 🆕 시퀀스 완료 시 검색 위젯 미리보기용 저장 (save/turbo_events)
        # (자동 저장 on/off와 관계없이 항상 저장, 중복 저장 방지)
        should_save = (is_sequence_complete or all_slots_filled) and not self._grid_saved_for_current_sequence
        if should_save:
            self._save_grid_image(grid_image)
            self._grid_saved_for_current_sequence = True

        return grid_image

    def _save_grid_image(self, grid_image):
        """그리드 이미지를 save/turbo_events 폴더에 저장 (절반 해상도)

        파일명: {parent_id} (확장자 없음 - NSFW 이미지 보호)
        """
        from pathlib import Path
        from PIL import Image

        if grid_image is None or self.current_parent_id is None:
            return

        try:
            # 저장 폴더 경로
            save_dir = Path("save/turbo_events")
            save_dir.mkdir(parents=True, exist_ok=True)

            # 파일 경로 (확장자 없음 - 기본 뷰어로 열리지 않도록)
            save_path = save_dir / f"{self.current_parent_id}"

            # 절반 해상도로 리사이즈
            half_w = grid_image.width // 2
            half_h = grid_image.height // 2
            resized = grid_image.resize((half_w, half_h), Image.Resampling.LANCZOS)

            # RGB 변환 (RGBA인 경우)
            if resized.mode == 'RGBA':
                resized = resized.convert('RGB')

            # JPEG 포맷으로 저장 (확장자는 없지만 내부 포맷은 JPEG)
            resized.save(save_path, 'JPEG', quality=85)
            print(f"💾 Grid saved: {save_path} ({half_w}x{half_h})")

            # 🆕 검색 위젯에 저장 완료 알림 (미리보기 업데이트용)
            self.search_widget.on_grid_saved(self.current_parent_id, str(save_path))

            # 🆕 Event Viewer 인덱스에 추가
            if hasattr(self, '_event_viewer') and self._event_viewer:
                self._event_viewer.add_event(self.current_parent_id)

        except Exception as e:
            print(f"❌ Grid save error: {e}")

    def _on_grid_manually_saved(self, grid_image):
        """수동 그리드 저장/복사 시 turbo_events 업데이트

        Args:
            grid_image: PIL Image - 히스토리 패널에서 전달받은 그리드 이미지
        """
        if grid_image is None or self.current_parent_id is None:
            return

        print(f"🔄 수동 그리드 저장 감지 - turbo_events 업데이트: {self.current_parent_id}")
        self._save_grid_image(grid_image)

    # ===== Custom Event 관련 메서드 =====

    def _on_open_custom_event_dialog(self):
        """Custom Event 생성 다이얼로그 열기"""
        from pathlib import Path
        from .widgets.custom_event_dialog import CustomEventDialog

        # data 폴더 경로
        data_dir = Path(__file__).parent.parent.parent / 'data'

        # 다이얼로그 생성 (모달리스 - 테스트 생성 시 백그라운드에서 이미지 확인 가능)
        # 🆕 app_context 전달하여 SequenceGenerationWorker 사용 가능
        self._custom_event_dialog = CustomEventDialog(data_dir, app_context=self.app_context, parent=self)
        self._custom_event_dialog.event_created.connect(self._on_custom_event_created)
        self._custom_event_dialog.show()

    def _on_custom_event_created(self, parent_id: int):
        """커스텀 이벤트 생성 완료"""
        print(f"✅ Custom event created: {parent_id}")

        # Favorites 모드로 전환하고 새로고침
        if self.search_widget.current_mode != 'Favorites':
            self.search_widget.mode_combo.setCurrentText('Favorites')

        # 검색 새로고침
        self.search_widget._check_and_load_dataset()

    # ===== Event Viewer 관련 메서드 =====

    def _on_open_event_viewer(self):
        """Event Viewer 열기 (모달리스)"""
        from pathlib import Path
        from .widgets.event_viewer_widget import EventViewerWidget

        # 이미 열려있으면 포커스만 이동
        if hasattr(self, '_event_viewer') and self._event_viewer and self._event_viewer.isVisible():
            self._event_viewer.raise_()
            self._event_viewer.activateWindow()
            return

        # data 폴더 경로
        data_dir = Path(__file__).parent.parent.parent / 'data'
        # 이벤트 이미지 폴더 경로
        events_dir = Path("save/turbo_events")

        # Event Viewer 다이얼로그 생성 (모달리스)
        self._event_viewer = EventViewerWidget(data_dir, events_dir, None)
        self._event_viewer.event_selected.connect(self._on_event_viewer_selected)
        self._event_viewer.quick_generation_requested.connect(self._on_event_viewer_quick_generate)
        self._event_viewer.show()  # exec() 대신 show() 사용

    def _on_event_viewer_selected(self, parent_id: int, sequence_df):
        """Event Viewer에서 이벤트 선택"""
        print(f"📂 Event Viewer: 시퀀스 선택 - {parent_id}")
        # 기존 parent_selected 핸들러 재사용
        self._on_parent_selected(parent_id, sequence_df)

    def _on_event_viewer_quick_generate(self, parent_id: int):
        """Event Viewer에서 바로 생성 요청"""
        print(f"📂 Event Viewer: 바로 생성 - {parent_id}")

        # 시퀀스 조회
        if hasattr(self, '_event_viewer') and self._event_viewer:
            sequence_df = self._event_viewer.index_manager.get_sequence_df(parent_id)
        else:
            # 대체 방법: search_widget의 searcher 사용
            if self.search_widget.searcher:
                sequence_df = self.search_widget.searcher.get_sequence(parent_id)
            else:
                print(f"❌ 시퀀스를 조회할 수 없습니다: {parent_id}")
                return

        if sequence_df is None:
            print(f"❌ 시퀀스를 찾을 수 없습니다: {parent_id}")
            return

        # Parent 선택 처리
        self._on_parent_selected(parent_id, sequence_df)

        # 시퀀스 확정
        self.sequence_tab_container.confirm_current_sequence()

        # 전체 시퀀스 생성 시작
        self._on_full_sequence_clicked()

    # ===== 배경 정보 유지 (ultralytics) 관련 메서드 =====

    def _on_keep_background_clicked(self, checked: bool):
        """배경 정보 유지 체크박스 클릭 핸들러"""
        if not checked:
            return

        # 이미 확인했으면 스킵
        if self._ultralytics_checked:
            return

        # ultralytics 설치 확인
        if not self._check_ultralytics_installed():
            # 설치되지 않음 - 체크 해제하고 설치 안내
            self.keep_background_checkbox.setChecked(False)
            self._show_ultralytics_install_dialog()
        else:
            # 설치됨 - 플래그 설정
            self._ultralytics_checked = True
            print("[TurboSequence] ultralytics 확인 완료")

    def _check_ultralytics_installed(self) -> bool:
        """ultralytics 패키지 설치 여부 확인"""
        try:
            import importlib.util
            spec = importlib.util.find_spec('ultralytics')
            return spec is not None
        except Exception:
            return False

    def _show_ultralytics_install_dialog(self):
        """ultralytics 설치 안내 다이얼로그"""
        from PyQt6.QtWidgets import QMessageBox

        # TODO(web-dialog): 원래 QMessageBox(Information) "패키지 설치 필요" — Web Shell confirm 모달로 재구현 필요.
        # 안전 기본값: 자동 설치 차단. 사용자가 직접 터미널에서 `pip install ultralytics` 실행.
        print("[Dialog/CONFIRM(skipped→Cancel)] 패키지 설치 필요: '배경 정보 유지' 기능에는 ultralytics 가 필요합니다. "
              "터미널에서 `pip install ultralytics` 직접 실행해주세요.")

    def _install_ultralytics(self):
        """ultralytics 패키지 설치"""
        import sys
        import subprocess
        from PyQt6.QtWidgets import QProgressDialog, QApplication
        from PyQt6.QtCore import Qt

        # 가상환경 확인
        venv_active = hasattr(sys, 'real_prefix') or (
            hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix
        )
        if not venv_active:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "설치 불가",
                "가상환경에서만 패키지를 설치할 수 있습니다."
            )
            return

        # 진행 다이얼로그
        progress = QProgressDialog("ultralytics 설치 중...", "취소", 0, 0, self)
        progress.setWindowTitle("패키지 설치")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()
        QApplication.processEvents()

        try:
            # pip install 실행
            pip_cmd = [sys.executable, '-m', 'pip', 'install', 'ultralytics==8.3.252']
            print(f"🔧 실행: {' '.join(pip_cmd)}")

            result = subprocess.run(
                pip_cmd,
                capture_output=True,
                text=True,
                timeout=600,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )

            progress.close()

            if result.returncode == 0:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self, "설치 완료",
                    "ultralytics가 성공적으로 설치되었습니다.\n"
                    "'배경 정보 유지' 기능을 사용할 수 있습니다."
                )
                self._ultralytics_checked = True
                self.keep_background_checkbox.setChecked(True)
                print("✅ ultralytics 설치 완료")
            else:
                from PyQt6.QtWidgets import QMessageBox
                error_msg = result.stderr[:500] if result.stderr else "알 수 없는 오류"
                QMessageBox.critical(
                    self, "설치 실패",
                    f"ultralytics 설치에 실패했습니다.\n\n{error_msg}"
                )
                print(f"❌ ultralytics 설치 실패: {result.stderr}")

        except subprocess.TimeoutExpired:
            progress.close()
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "설치 실패", "설치 시간이 초과되었습니다.")
        except Exception as e:
            progress.close()
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "설치 실패", f"설치 중 오류 발생:\n{str(e)}")

    # ===== 인페인트 다이얼로그 =====

    def _on_inpaint_requested(self, history_index: int, image, direction: str, is_parent: bool, prev_image=None):
        """🆕 인페인트 요청 핸들러 - 다이얼로그 열기"""
        from .widgets.sequence_inpaint_dialog import SequenceInpaintDialog

        # 🐛 수정: 이미 열려있으면 닫고 새로 생성 (다른 이미지 인페인트 시 이전 이미지가 남는 문제 해결)
        if hasattr(self, '_inpaint_dialog') and self._inpaint_dialog and self._inpaint_dialog.isVisible():
            self._inpaint_dialog.close()
            self._inpaint_dialog = None

        # 프롬프트 정보 가져오기
        prompt = ""
        negative_prompt = ""

        if self.confirmed_prompts and history_index > 0:
            # history_index 1 = confirmed_prompts[0] (index 0)
            prompt_index = history_index - 1
            if prompt_index < len(self.confirmed_prompts):
                prompt_data = self.confirmed_prompts[prompt_index]
                prompt = prompt_data.get('general', '')

        # 네거티브 프롬프트 가져오기 (공용 모듈에서)
        if self.app_context and hasattr(self.app_context, 'main_window'):
            main_window = self.app_context.main_window
            # PromptInputModule에서 네거티브 프롬프트 가져오기
            if hasattr(main_window, 'middle_section') and main_window.middle_section:
                for module in main_window.middle_section.modules:
                    if hasattr(module, 'get_parameters'):
                        params = module.get_parameters()
                        if 'negative_prompt' in params:
                            negative_prompt = params.get('negative_prompt', '')
                            break

        print(f"🎨 인페인트 다이얼로그 열기: #{history_index}")
        print(f"   - prompt: {prompt[:50]}..." if len(prompt) > 50 else f"   - prompt: {prompt}")
        print(f"   - negative: {negative_prompt[:30]}..." if len(negative_prompt) > 30 else f"   - negative: {negative_prompt}")
        print(f"   - prev_image: {'있음' if prev_image else '없음'}")

        # 다이얼로그 생성
        self._inpaint_dialog = SequenceInpaintDialog(
            image=image,
            history_index=history_index,
            direction=direction,
            is_parent=is_parent,
            prompt=prompt,
            negative_prompt=negative_prompt,
            app_context=self.app_context,
            prev_image=prev_image,  # 🆕 이전 이미지 전달
            parent=None  # 모달리스
        )
        self._inpaint_dialog.image_confirmed.connect(self._on_inpaint_confirmed)
        self._inpaint_dialog.show()

    def _on_inpaint_confirmed(self, index: int, new_image):
        """🆕 인페인트 결과 적용"""
        # HistoryPanel의 핸들러 호출
        self.history_panel._on_inpaint_confirmed(index, new_image)

    # ===== 외부 API 전송 다이얼로그 =====

    def _on_export_requested(self):
        """🆕 외부 API 전송 요청 핸들러 - SequenceExportDialog 열기"""
        from .widgets.sequence_export_dialog import SequenceExportDialog

        # 이미지 및 프롬프트 데이터 수집
        images = self.history_panel.get_ordered_images()  # Skip 제외한 순서대로 이미지
        prompts = self.confirmed_prompts if self.confirmed_prompts else []

        if not images or not prompts:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                "데이터 없음",
                "내보낼 이미지 또는 프롬프트가 없습니다.\n시퀀스를 먼저 생성해주세요."
            )
            return

        print(f"[TurboEventSequenceTab] 외부 API 전송: {len(images)}개 이미지, {len(prompts)}개 프롬프트")

        # SequenceExportDialog 열기 (여러 윈도우 지원)
        dialog = SequenceExportDialog(
            images=images,
            prompts=prompts,
            app_context=self.app_context,
            parent=self
        )

        # 시그널 연결 (TODO: 필요 시)
        # dialog.video_generated.connect(self._on_video_generated)

        # 다이얼로그 추적 리스트에 추가 (가비지 컬렉션 방지)
        if not hasattr(self, '_export_dialogs'):
            self._export_dialogs = []
        self._export_dialogs.append(dialog)

        # 닫힐 때 리스트에서 제거
        def on_dialog_finished():
            if dialog in self._export_dialogs:
                self._export_dialogs.remove(dialog)

        dialog.finished.connect(on_dialog_finished)

        # show() 사용 (여러 윈도우 동시 열기 가능)
        dialog.show()