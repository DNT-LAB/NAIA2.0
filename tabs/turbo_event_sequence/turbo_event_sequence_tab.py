"""
Turbo Event Sequence Tab

Sliding Window Inpaint 기반 연속 이미지 시퀀스 생성 탭
"""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QFrame, QPushButton, QProgressBar, QCheckBox
)
from PyQt6.QtCore import pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap

from interfaces.base_tab_module import BaseTabModule
from ui.theme import DARK_STYLES, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

from .widgets.event_search_widget import EventSearchWidget
from .widgets.sequence_tab_container import SequenceTabContainer
from .widgets.image_viewer_widget import ImageViewerWidget
from .widgets.history_panel import HistoryPanel


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
        self.current_state = self.STATE_IDLE
        self.selected_direction = None  # 'horizontal' or 'vertical'
        self.current_generation_index = 0  # 현재 생성 중인 인덱스
        self._index_mapping = None  # 스킵 기능용 인덱스 매핑 (Worker 인덱스 → 원본 인덱스)
        self.current_parent_id = None  # 현재 선택된 Parent ID (그리드 저장용)

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
        layout.addWidget(self.search_widget, stretch=3)

        # 시퀀스 탭 컨테이너 (미리보기 + 수정 탭)
        self.sequence_tab_container = SequenceTabContainer(app_context=self.app_context, parent=self)
        self.sequence_tab_container.sequence_confirmed.connect(self._on_sequence_confirmed)
        self.sequence_tab_container.prompts_updated.connect(self._on_prompts_updated)
        self.sequence_tab_container.prompt_engineering_toggled.connect(self._on_prompt_engineering_toggled)
        # 🆕 Skip 상태 변경 시 그리드 업데이트
        self.sequence_tab_container.edit_widget.disable_state_changed.connect(self._on_disable_state_changed)
        layout.addWidget(self.sequence_tab_container, stretch=2)

        # 🆕 Favorite 및 연속 생성 컨트롤 패널 (시퀀스 미리보기 아래)
        favorite_panel = self._create_favorite_control_panel()
        layout.addWidget(favorite_panel)

        return panel

    def _create_favorite_control_panel(self) -> QFrame:
        """Favorite 및 연속 생성 컨트롤 패널 생성"""
        panel = QFrame()
        panel.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)

        layout = QHBoxLayout(panel)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        # Favorite 저장 버튼
        self.save_favorite_btn = QPushButton("💖 Favorite에 저장")
        self.save_favorite_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: #ff6b9d;
                border: 1px solid #ff6b9d;
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px {get_scaled_size(12)}px;
                font-size: {get_scaled_font_size(12) + 5}px;
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
        self.save_favorite_btn.setToolTip("현재 시퀀스를 Favorites에 저장합니다")
        layout.addWidget(self.save_favorite_btn)

        # 연속 생성 체크박스
        self.continuous_checkbox = QCheckBox("🔄 다음 이벤트 연속 생성")
        self.continuous_checkbox.setStyleSheet(self._get_favorite_checkbox_style())
        self.continuous_checkbox.toggled.connect(self._on_continuous_toggled)
        self.continuous_checkbox.setToolTip("그리드 저장 완료 후 5초 뒤 다음 이벤트 자동 생성")
        layout.addWidget(self.continuous_checkbox)

        # 이미 생성한 이벤트 건너뛰기 체크박스
        self.skip_generated_checkbox = QCheckBox("⏭️ 이미 생성한 이벤트 스킵")
        self.skip_generated_checkbox.setStyleSheet(self._get_favorite_checkbox_style())
        self.skip_generated_checkbox.setToolTip("저장된 그리드 이미지가 있는 이벤트 건너뛰기")
        self.skip_generated_checkbox.setEnabled(False)  # 연속 생성 활성화 시만 사용 가능
        layout.addWidget(self.skip_generated_checkbox)

        # 카운트다운 라벨 (숨김)
        self.countdown_label = QLabel("")
        self.countdown_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(14) + 2}px;
            color: {DARK_COLORS['accent_blue']};
            font-weight: bold;
        """)
        self.countdown_label.hide()
        layout.addWidget(self.countdown_label)

        layout.addStretch()

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
        self.skip_generated_checkbox.setEnabled(checked)

        if checked:
            print(f"🔄 연속 생성: 활성화 (그리드 자동 저장이 강제 활성화됩니다)")
        else:
            print(f"🔄 연속 생성: 비활성화")

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
        self.after_first_frame = QFrame()
        after_first_layout = QHBoxLayout(self.after_first_frame)
        after_first_layout.setContentsMargins(0, 0, 0, 0)
        after_first_layout.setSpacing(4)

        self.regenerate_btn = QPushButton("🔄 재생성")
        self.regenerate_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.regenerate_btn.clicked.connect(self._on_regenerate_clicked)
        after_first_layout.addWidget(self.regenerate_btn)

        self.next_page_btn = QPushButton("➡️ 다음 페이지")
        self.next_page_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.next_page_btn.clicked.connect(self._on_next_page_clicked)
        after_first_layout.addWidget(self.next_page_btn)

        self.continue_all_btn = QPushButton("▶ 나머지 전체 생성")
        self.continue_all_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.continue_all_btn.clicked.connect(self._on_continue_all_clicked)
        after_first_layout.addWidget(self.continue_all_btn)

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
            self.after_first_frame.show()
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

    # ===== 이벤트 핸들러 =====

    def _on_parent_selected(self, parent_id: int, sequence_df):
        """Parent 선택 시 시퀀스 미리보기 업데이트"""
        print(f"🎯 Parent selected: {parent_id}")
        self.current_sequence = sequence_df
        self.current_parent_id = parent_id  # 🆕 Parent ID 저장 (그리드 저장용)
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
        self.generated_images = []
        self.current_generation_index = 0
        # 히스토리 클리어
        self.history_panel.clear()
        self.image_viewer.clear()
        # 🆕 자동으로 가로 해상도 선택
        self._on_direction_selected('horizontal')

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
        """해상도 변경 경고 다이얼로그 표시

        Returns:
            True: 사용자가 확인 → 이미지 초기화 진행
            False: 사용자가 취소 → 기존 방향 유지
        """
        from PyQt6.QtWidgets import QMessageBox

        # 커스텀 스타일 다이얼로그
        msg = QMessageBox(self)
        msg.setWindowTitle("⚠️ 해상도 변경 경고")
        msg.setText("해상도를 변경하면 생성된 이미지가 모두 삭제됩니다.")
        msg.setInformativeText("계속하시겠습니까?")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)

        # 다크 테마 스타일 적용
        msg.setStyleSheet(f"""
            QMessageBox {{
                background-color: {DARK_COLORS['bg_secondary']};
            }}
            QMessageBox QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
            }}
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px {get_scaled_size(16)}px;
                font-size: {get_scaled_font_size(13)}px;
                min-width: {get_scaled_size(60)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
        """)

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
        """재생성 버튼 클릭 - 현재 인덱스 재생성"""
        if not self.confirmed_prompts or not self.selected_direction:
            return
        # 현재 표시 중인 이미지의 인덱스 찾기
        current_index = len(self.generated_images) - 1
        if current_index < 0:
            current_index = 0
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
        start_index = len(self.generated_images)
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

    def _on_favorite_saved(self, parent_id: int):
        """Favorite 저장 완료"""
        print(f"💖 Favorite saved for parent {parent_id}")
        # Favorites 모드인 경우 데이터셋 새로고침
        self.search_widget.refresh_favorites()

    def _on_grid_auto_saved(self, save_path: str):
        """그리드 자동 저장 완료 (history_panel의 별도 저장)

        Note: 연속 생성 카운트다운은 탭의 _save_grid_image에서 처리합니다.
        """
        print(f"💾 Grid auto saved (history_panel): {save_path}")

    def _on_continuous_generation_requested(self, parent_id: int):
        """연속 생성 요청 - 자동으로 전체 시퀀스 생성 시작"""
        print(f"🔄 Continuous generation requested for parent {parent_id}")
        # 연속 생성 시 그리드 자동 저장 강제 활성화
        if not self.history_panel.auto_save_enabled:
            self.history_panel.auto_save_checkbox.setChecked(True)
        # 자동으로 전체 시퀀스 생성 시작
        self._on_full_sequence_clicked()

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
            strength=0.7,
            negative_prompt=self._get_negative_prompt(),
            prev_images=prev_images,
            start_index=index
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
        if start_index == 0:
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
            strength=0.7,
            negative_prompt=self._get_negative_prompt(),
            prev_images=prev_images,
            start_index=0  # Worker 내부 인덱스는 0부터 시작
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
        self.history_panel.add_image(worker_index, image)  # 히스토리는 순차적 인덱스 사용

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

        # 히스토리 패널에 그리드 이미지 업데이트
        self.history_panel.update_grid_image(grid_image)

        # 🆕 그리드 이미지 자동 저장 (시퀀스 완료 시에만)
        if is_sequence_complete:
            self._save_grid_image(grid_image)

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

            # 🆕 연속 생성 모드면 카운트다운 시작
            if self.search_widget.is_continuous_generation_enabled():
                print(f"🔄 연속 생성 모드 - 카운트다운 시작")
                self.search_widget.start_countdown_to_next()

        except Exception as e:
            print(f"❌ Grid save error: {e}")
