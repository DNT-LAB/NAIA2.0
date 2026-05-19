"""
Event Viewer Widget

생성된 이벤트 탐색 및 선택을 위한 메인 위젯
- 썸네일 그리드 (2x5)
- 미리보기 패널
- 검색/필터링 UI
"""

from PyQt6.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QLineEdit, QPushButton, QCheckBox, QProgressBar
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QKeyEvent, QWheelEvent
from pathlib import Path
from typing import Optional, Set
import pandas as pd

from legacy_desktop.ui.theme import DARK_STYLES, DARK_COLORS
from legacy_desktop.ui.scaling_manager import get_scaled_font_size, get_scaled_size

from .event_index_manager import EventIndexManager
from .thumbnail_grid import ThumbnailGrid
from .event_preview_panel import EventPreviewPanel


class EventViewerWidget(QDialog):
    """이벤트 뷰어 다이얼로그"""

    # 시그널
    event_selected = pyqtSignal(int, object)  # parent_id, sequence_df
    quick_generation_requested = pyqtSignal(int)  # parent_id

    def __init__(self, data_dir: Path, events_dir: Path, parent=None):
        """
        Args:
            data_dir: Parquet 파일이 있는 data 폴더 경로
            events_dir: 생성된 이벤트 이미지가 있는 save/turbo_events 폴더 경로
        """
        super().__init__(parent)
        self.data_dir = Path(data_dir)
        self.events_dir = Path(events_dir)

        # 인덱스 매니저
        self.index_manager = EventIndexManager(data_dir, events_dir)

        # 검색 상태
        self.active_page_filters: Set[int] = set()
        self.filtered_events = []

        self._init_ui()
        self._apply_dark_theme()
        self._load_data()

    def _init_ui(self):
        """UI 초기화"""
        self.setWindowTitle("📂 Event Viewer")
        self.setMinimumSize(1100, 960)
        self.resize(1200, 1000)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 헤더 (타이틀 + 닫기)
        header = self._create_header()
        layout.addWidget(header)

        # 검색 영역
        search_frame = self._create_search_frame()
        layout.addWidget(search_frame)

        # 메인 컨텐츠 (썸네일 그리드 + 미리보기)
        content = self._create_content()
        layout.addWidget(content, stretch=1)

        # 진행률 표시 (인덱스 동기화용)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(get_scaled_size(8))
        self.progress_bar.setTextVisible(False)
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
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

    def _apply_dark_theme(self):
        """다크 테마 적용"""
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_secondary']};
            }}
        """)

    def _create_header(self) -> QFrame:
        """헤더 생성"""
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 8, 12, 8)

        title = QLabel("📂 Event Viewer")
        title.setStyleSheet(f"""
            font-size: {get_scaled_font_size(20)}px;
            font-weight: bold;
            color: {DARK_COLORS['text_primary']};
        """)
        layout.addWidget(title)

        self.status_label = QLabel("로딩 중...")
        self.status_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(16)}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        layout.addWidget(self.status_label)

        layout.addStretch()

        close_btn = QPushButton("✕ 닫기")
        close_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        return frame

    def _create_search_frame(self) -> QFrame:
        """검색 프레임 생성"""
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Parent 검색 행
        parent_row = QHBoxLayout()
        parent_row.setSpacing(6)

        parent_label = QLabel("Parent:")
        parent_label.setFixedWidth(get_scaled_size(55))
        parent_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(16)}px;
            color: {DARK_COLORS['text_primary']};
            font-weight: bold;
        """)
        parent_row.addWidget(parent_label)

        self.parent_include_input = QLineEdit()
        self.parent_include_input.setPlaceholderText("Include 태그 (쉼표 구분)")
        self.parent_include_input.setStyleSheet(self._get_input_style())
        self.parent_include_input.returnPressed.connect(self._on_search)
        parent_row.addWidget(self.parent_include_input, stretch=1)

        self.parent_exclude_input = QLineEdit()
        self.parent_exclude_input.setPlaceholderText("Exclude 태그")
        self.parent_exclude_input.setStyleSheet(self._get_input_style())
        self.parent_exclude_input.returnPressed.connect(self._on_search)
        parent_row.addWidget(self.parent_exclude_input, stretch=1)

        # 검색 버튼
        search_btn = QPushButton("🔍 검색")
        search_btn.setStyleSheet(DARK_STYLES['primary_button'])
        search_btn.clicked.connect(self._on_search)
        parent_row.addWidget(search_btn)

        # 클리어 버튼
        clear_btn = QPushButton("🗑️ 클리어")
        clear_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        clear_btn.clicked.connect(self._on_clear_search)
        parent_row.addWidget(clear_btn)

        layout.addLayout(parent_row)

        # Child 검색 행
        child_row = QHBoxLayout()
        child_row.setSpacing(6)

        child_label = QLabel("Child:")
        child_label.setFixedWidth(get_scaled_size(55))
        child_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(16)}px;
            color: {DARK_COLORS['text_primary']};
            font-weight: bold;
        """)
        child_row.addWidget(child_label)

        self.child_include_input = QLineEdit()
        self.child_include_input.setPlaceholderText("Include 태그 (쉼표 구분)")
        self.child_include_input.setStyleSheet(self._get_input_style())
        self.child_include_input.returnPressed.connect(self._on_search)
        child_row.addWidget(self.child_include_input, stretch=1)

        self.child_exclude_input = QLineEdit()
        self.child_exclude_input.setPlaceholderText("Exclude 태그")
        self.child_exclude_input.setStyleSheet(self._get_input_style())
        self.child_exclude_input.returnPressed.connect(self._on_search)
        child_row.addWidget(self.child_exclude_input, stretch=1)

        # 버튼 영역 스페이서 (Parent 행과 정렬)
        button_spacer = QWidget()
        button_spacer.setFixedWidth(get_scaled_size(180))  # 검색+클리어 버튼 너비
        child_row.addWidget(button_spacer)

        layout.addLayout(child_row)

        # 페이지 필터 행
        filter_row = QHBoxLayout()
        filter_row.setSpacing(4)

        filter_label = QLabel("Pages:")
        filter_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(15)}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        filter_row.addWidget(filter_label)

        self.page_buttons = {}
        for page_count in [2, 3, 4, 5, 6]:
            btn = QPushButton(f"{page_count}p")
            btn.setCheckable(True)
            btn.setFixedWidth(get_scaled_size(48))
            btn.setStyleSheet(self._get_toggle_button_style())
            btn.clicked.connect(lambda checked, p=page_count: self._on_page_filter_toggled(p, checked))
            filter_row.addWidget(btn)
            self.page_buttons[page_count] = btn

        filter_row.addStretch()

        # 새로고침 버튼
        refresh_btn = QPushButton("🔄 새로고침")
        refresh_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        refresh_btn.clicked.connect(self._on_refresh)
        refresh_btn.setToolTip("폴더와 인덱스를 동기화합니다")
        filter_row.addWidget(refresh_btn)

        layout.addLayout(filter_row)

        return frame

    def _create_content(self) -> QWidget:
        """메인 컨텐츠 생성"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 왼쪽: 썸네일 그리드
        self.thumbnail_grid = ThumbnailGrid(self.events_dir, self)
        self.thumbnail_grid.setFixedWidth(get_scaled_size(320))
        self.thumbnail_grid.item_clicked.connect(self._on_thumbnail_clicked)
        layout.addWidget(self.thumbnail_grid)

        # 오른쪽: 미리보기 패널
        self.preview_panel = EventPreviewPanel(self.events_dir, self)
        self.preview_panel.select_sequence_requested.connect(self._on_select_sequence)
        self.preview_panel.quick_generate_requested.connect(self._on_quick_generate)
        layout.addWidget(self.preview_panel, stretch=1)

        return widget

    def _get_input_style(self) -> str:
        """입력 필드 스타일"""
        return f"""
            QLineEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(8)}px {get_scaled_size(10)}px;
                font-size: {get_scaled_font_size(16)}px;
            }}
            QLineEdit:focus {{
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QLineEdit::placeholder {{
                color: {DARK_COLORS['text_secondary']};
            }}
        """

    def _get_toggle_button_style(self) -> str:
        """토글 버튼 스타일"""
        return f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px;
                font-size: {get_scaled_font_size(15)}px;
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

    def _load_data(self):
        """데이터 로드"""
        # 인덱스 로드
        self.index_manager.load_index()

        # 🔄 항상 폴더와 동기화 (새로 생성된 이벤트 감지)
        self._sync_index()

    def _sync_index(self):
        """인덱스 동기화"""
        self.status_label.setText("인덱스 동기화 중...")
        self.progress_bar.setValue(0)
        self.progress_bar.show()

        # 🆕 썸네일 캐시 클리어 (이미지 새로고침)
        self.thumbnail_grid.clear_cache()

        # 진행률 콜백
        def on_progress(current, total, message):
            if total > 0:
                percent = int((current / total) * 100)
                self.progress_bar.setValue(percent)
            self.status_label.setText(message)

        # 동기화 실행 (TODO: 백그라운드 스레드로 이동)
        result = self.index_manager.sync_with_folder(on_progress)

        self.progress_bar.hide()
        self._update_display()

    def _update_display(self):
        """표시 업데이트"""
        # 검색 적용
        self._apply_search()

        # 상태 업데이트
        total = self.index_manager.get_count()
        filtered = len(self.filtered_events)
        self.status_label.setText(f"✅ {filtered}/{total}개 이벤트")

    def _apply_search(self):
        """검색 적용"""
        parent_include = self.parent_include_input.text().strip() or None
        parent_exclude = self.parent_exclude_input.text().strip() or None
        child_include = self.child_include_input.text().strip() or None
        child_exclude = self.child_exclude_input.text().strip() or None

        # 페이지 필터
        page_filters = self.active_page_filters if self.active_page_filters else None

        # 검색 실행
        self.filtered_events = self.index_manager.search(
            parent_include=parent_include,
            parent_exclude=parent_exclude,
            child_include=child_include,
            child_exclude=child_exclude,
            page_filters=page_filters
        )

        # 그리드 업데이트
        self.thumbnail_grid.set_events(self.filtered_events)

        # 미리보기 클리어
        self.preview_panel.clear()

    def _on_search(self):
        """검색 실행"""
        self._update_display()

    def _on_clear_search(self):
        """검색 클리어"""
        self.parent_include_input.clear()
        self.parent_exclude_input.clear()
        self.child_include_input.clear()
        self.child_exclude_input.clear()

        # 페이지 필터 초기화
        for btn in self.page_buttons.values():
            btn.setChecked(False)
        self.active_page_filters.clear()

        self._update_display()

    def _on_page_filter_toggled(self, page_count: int, checked: bool):
        """페이지 필터 토글"""
        if checked:
            self.active_page_filters.add(page_count)
        else:
            self.active_page_filters.discard(page_count)

        self._update_display()

    def _on_refresh(self):
        """새로고침"""
        self._sync_index()

    def _on_thumbnail_clicked(self, parent_id: int):
        """썸네일 클릭"""
        event = self.index_manager.get_event(parent_id)
        if event:
            self.preview_panel.set_event(event)

        # 포커스를 다이얼로그로 되돌림 (키보드 네비게이션 활성화)
        self.setFocus()

    def _on_select_sequence(self, parent_id: int):
        """시퀀스 선택"""
        sequence_df = self.index_manager.get_sequence_df(parent_id)
        if sequence_df is not None:
            self.event_selected.emit(parent_id, sequence_df)
            self.close()
        else:
            self.status_label.setText(f"❌ 시퀀스 로드 실패: {parent_id}")

    def _on_quick_generate(self, parent_id: int):
        """바로 생성 (다이얼로그 유지)"""
        sequence_df = self.index_manager.get_sequence_df(parent_id)
        if sequence_df is not None:
            self.quick_generation_requested.emit(parent_id)
            self.status_label.setText(f"✅ 생성 시작: {parent_id}")
            # 다이얼로그는 닫지 않음 - 연속 작업 가능
        else:
            self.status_label.setText(f"❌ 시퀀스 로드 실패: {parent_id}")

    def add_event(self, parent_id: int):
        """새 이벤트 추가 (외부에서 호출)

        Args:
            parent_id: 추가할 이벤트 ID
        """
        if self.index_manager.add_event(parent_id):
            self._update_display()

    def closeEvent(self, event):
        """닫기 이벤트"""
        # 리소스 정리
        self.thumbnail_grid.cleanup()
        super().closeEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        """키보드 이벤트 처리

        - Left/Right: 썸네일 좌우 이동
        - Up/Down: 썸네일 상하 이동
        - Page Up/Down: 페이지 넘김
        - Enter: 시퀀스 선택
        - Shift+Enter: 바로 생성
        - Escape: 닫기
        """
        key = event.key()

        # 검색 입력 필드에 포커스가 있으면 기본 동작 유지
        # (단, Escape와 Page Up/Down은 항상 처리)
        focused_widget = self.focusWidget()
        is_input_focused = isinstance(focused_widget, QLineEdit)

        # Escape: 항상 닫기
        if key == Qt.Key.Key_Escape:
            self.close()
            return

        # 페이지 넘김 (항상 처리)
        if key == Qt.Key.Key_PageUp:
            self.thumbnail_grid._on_prev_clicked()
            return
        elif key == Qt.Key.Key_PageDown:
            self.thumbnail_grid._on_next_clicked()
            return

        # 검색 입력 필드에 포커스가 있으면 방향키/엔터는 기본 동작
        if is_input_focused:
            super().keyPressEvent(event)
            return

        # 썸네일 선택 이동 (좌우: ±1, 상하: ±2)
        if key == Qt.Key.Key_Left:
            self._move_selection(-1)  # 왼쪽
            return
        elif key == Qt.Key.Key_Right:
            self._move_selection(1)  # 오른쪽
            return
        elif key == Qt.Key.Key_Up:
            self._move_selection(-2)  # 위 (2열이므로 -2)
            return
        elif key == Qt.Key.Key_Down:
            self._move_selection(2)  # 아래 (2열이므로 +2)
            return

        # Enter: 시퀀스 선택 또는 바로 생성
        elif key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            if self.preview_panel.current_parent_id is not None:
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    # Shift+Enter: 바로 생성
                    self._on_quick_generate(self.preview_panel.current_parent_id)
                else:
                    # Enter: 시퀀스 선택
                    self._on_select_sequence(self.preview_panel.current_parent_id)
            return

        super().keyPressEvent(event)

    def _move_selection(self, delta: int):
        """썸네일 선택 이동

        Args:
            delta: 이동할 인덱스 차이 (-1: 왼쪽, +1: 오른쪽, -2: 위, +2: 아래)
        """
        if not self.filtered_events:
            return

        current_id = self.thumbnail_grid.selected_id
        if current_id is None:
            # 선택된 것이 없으면 현재 페이지 첫 번째 선택
            page_start = self.thumbnail_grid.current_page * self.thumbnail_grid.ITEMS_PER_PAGE
            if page_start < len(self.filtered_events):
                first_event = self.filtered_events[page_start]
                self.thumbnail_grid.select_item(first_event['id'])
                self._on_thumbnail_clicked(first_event['id'])
            return

        # 현재 선택된 인덱스 찾기
        current_idx = -1
        for i, event in enumerate(self.filtered_events):
            if event['id'] == current_id:
                current_idx = i
                break

        if current_idx == -1:
            return

        # 새 인덱스 계산
        new_idx = current_idx + delta
        if 0 <= new_idx < len(self.filtered_events):
            new_event = self.filtered_events[new_idx]
            self.thumbnail_grid.select_item(new_event['id'])
            self._on_thumbnail_clicked(new_event['id'])

    def wheelEvent(self, event: QWheelEvent):
        """마우스 휠 이벤트 처리

        - 썸네일 그리드 영역: 페이지 스크롤
        - 이미지 영역 (preview_panel): 아이템 스크롤
        """
        # 휠 방향 (위로: 양수, 아래로: 음수)
        delta = event.angleDelta().y()

        # 마우스 위치 확인
        mouse_pos = event.position().toPoint()

        # 썸네일 그리드 영역 체크
        grid_rect = self.thumbnail_grid.geometry()
        preview_rect = self.preview_panel.geometry()

        if grid_rect.contains(mouse_pos):
            # 썸네일 그리드 영역: 페이지 스크롤
            if delta > 0:
                self.thumbnail_grid._on_prev_clicked()
            else:
                self.thumbnail_grid._on_next_clicked()
            event.accept()
        elif preview_rect.contains(mouse_pos):
            # 이미지 영역: Z형 아이템 스크롤 (좌→우→다음줄)
            if delta > 0:
                self._move_selection(-1)  # 이전 아이템
            else:
                self._move_selection(1)  # 다음 아이템
            event.accept()
        else:
            super().wheelEvent(event)

    def select_and_generate(self, parent_id: int):
        """외부에서 ID로 즉시 시퀀스 선택 및 생성

        Args:
            parent_id: 생성할 이벤트의 parent_id
        """
        sequence_df = self.index_manager.get_sequence_df(parent_id)
        if sequence_df is None:
            print(f"❌ 이벤트를 찾을 수 없습니다: {parent_id}")
            return False

        self.quick_generation_requested.emit(parent_id)
        return True
