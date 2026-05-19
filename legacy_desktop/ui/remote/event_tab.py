# ui/remote/event_tab.py
"""
이벤트 탭 관련 위젯 및 핸들러 - RemoteWindow에서 분리

구성요소:
- EventItemWidget: 이벤트 아이템 위젯 (썸네일 + 태그 + 버튼)
- EventTabMixin: 이벤트 탭 관련 메서드들을 모은 Mixin 클래스
"""

import json
import time
import uuid
from pathlib import Path

from PIL import Image

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QFrame, QTabWidget, QCheckBox,
    QTextEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QImage

from legacy_desktop.ui.theme import DARK_COLORS, DARK_STYLES
from legacy_desktop.ui.scaling_manager import get_scaled_font_size


# === 상수 정의 ===
REMOTE_EVENTS_DIR = Path("save/remote_events")
REMOTE_EVENTS_JSON = Path("save/remote_events/events.json")
REMOTE_EVENTS_THUMBS_DIR = Path("save/remote_events/thumbnails")

# 썸네일 크기 (FAVORITE_THUMB와 동일)
EVENT_THUMB_WIDTH = 120
EVENT_THUMB_HEIGHT = 167


class EventItemWidget(QFrame):
    """이벤트 아이템 위젯 - 1줄 전체 레이아웃"""

    # 시그널 정의
    instant_generate_requested = pyqtSignal(str)  # event_id
    add_to_queue_requested = pyqtSignal(str)  # event_id
    delete_requested = pyqtSignal(str)  # event_id
    edit_requested = pyqtSignal(str)  # event_id
    heart_changed = pyqtSignal(str, int)  # event_id, new_value
    rating_changed = pyqtSignal(str, str)  # event_id, new_rating

    def __init__(self, event_data: dict, parent=None):
        super().__init__(parent)
        self.event_data = event_data
        self.event_id = event_data.get("id", "")
        self.is_editing = False

        self._init_ui()

    def _init_ui(self):
        # 전체 프레임 스타일
        self.setStyleSheet(f"""
            EventItemWidget {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 6px;
            }}
            EventItemWidget:hover {{
                border: 1px solid {DARK_COLORS['accent_blue']};
            }}
        """)
        self.setMinimumHeight(EVENT_THUMB_HEIGHT + 20)
        self.setMaximumHeight(EVENT_THUMB_HEIGHT + 20)

        # 메인 레이아웃 (수평)
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(10)

        # === 좌측: 썸네일 ===
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(EVENT_THUMB_WIDTH, EVENT_THUMB_HEIGHT)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_primary']};
                border-radius: 4px;
            }}
        """)
        self._load_thumbnail()
        main_layout.addWidget(self.thumb_label)

        # === 우측: 정보 영역 (4:1 비율) ===
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        # --- 상단 4: General 태그 표시/편집 ---
        self.general_edit = QTextEdit()
        general_text = self.event_data.get("source_row", {}).get("general", "")
        self.general_edit.setPlainText(general_text)
        self.general_edit.setReadOnly(True)
        self.general_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                font-size: {get_scaled_font_size(16)}px;
                padding: 4px;
            }}
            QTextEdit:focus {{
                border: 1px solid {DARK_COLORS['accent_blue']};
            }}
        """)
        right_layout.addWidget(self.general_edit, 4)  # 4 비율

        # --- 하단 1: 버튼 행 ---
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(4)

        # 버튼 스타일
        small_btn_style = f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                padding: 3px 8px;
                font-size: {get_scaled_font_size(13)}px;
                min-width: 35px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
            QPushButton:pressed {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
        """

        # Rating 버튼
        current_rating = self.event_data.get("source_row", {}).get("rating", "g")
        self.rating_btn = QPushButton(f"R:{current_rating.upper()}")
        self.rating_btn.setStyleSheet(small_btn_style)
        self.rating_btn.setToolTip("등급 변경")
        self.rating_btn.clicked.connect(self._on_rating_clicked)
        btn_layout.addWidget(self.rating_btn)

        # 수정 버튼
        self.edit_btn = QPushButton("✏️")
        self.edit_btn.setStyleSheet(small_btn_style)
        self.edit_btn.setToolTip("General 태그 수정")
        self.edit_btn.clicked.connect(self._on_edit_clicked)
        btn_layout.addWidget(self.edit_btn)

        # 삭제 버튼
        delete_btn = QPushButton("🗑️")
        delete_btn.setStyleSheet(small_btn_style)
        delete_btn.setToolTip("삭제")
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.event_id))
        btn_layout.addWidget(delete_btn)

        btn_layout.addStretch()

        # 즉시 생성 버튼
        instant_btn = QPushButton("⚡ 즉시")
        instant_btn.setStyleSheet(small_btn_style)
        instant_btn.setToolTip("즉시 생성")
        instant_btn.clicked.connect(lambda: self.instant_generate_requested.emit(self.event_id))
        btn_layout.addWidget(instant_btn)

        # 대기열 추가 버튼
        queue_btn = QPushButton("📋 대기열")
        queue_btn.setStyleSheet(small_btn_style)
        queue_btn.setToolTip("대기열에 추가")
        queue_btn.clicked.connect(lambda: self.add_to_queue_requested.emit(self.event_id))
        btn_layout.addWidget(queue_btn)

        btn_layout.addStretch()

        # 하트 버튼들
        heart_minus_btn = QPushButton("♥-")
        heart_minus_btn.setStyleSheet(small_btn_style)
        heart_minus_btn.setToolTip("우선순위 감소")
        heart_minus_btn.clicked.connect(lambda: self._change_heart(-1))
        btn_layout.addWidget(heart_minus_btn)

        # 하트 값 표시
        current_heart = self.event_data.get("heart", 0)
        self.heart_label = QLabel(f"♥{current_heart}")
        self.heart_label.setStyleSheet(f"""
            QLabel {{
                color: {'#FF6B9D' if current_heart > 0 else DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
                min-width: 30px;
            }}
        """)
        self.heart_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_layout.addWidget(self.heart_label)

        heart_plus_btn = QPushButton("♥+")
        heart_plus_btn.setStyleSheet(small_btn_style)
        heart_plus_btn.setToolTip("우선순위 증가")
        heart_plus_btn.clicked.connect(lambda: self._change_heart(1))
        btn_layout.addWidget(heart_plus_btn)

        right_layout.addLayout(btn_layout, 1)  # 1 비율

        main_layout.addLayout(right_layout, 1)

    def _load_thumbnail(self):
        """썸네일 로드 - 중앙 크롭하여 영역을 꽉 채움"""
        thumb_filename = self.event_data.get("thumbnail", "")
        thumb_path = REMOTE_EVENTS_THUMBS_DIR / thumb_filename

        if thumb_path.exists():
            pixmap = QPixmap(str(thumb_path))
            # KeepAspectRatioByExpanding으로 확대하여 빈 공간 없이 채움
            scaled = pixmap.scaled(
                EVENT_THUMB_WIDTH, EVENT_THUMB_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            # 중앙 크롭: 확대된 이미지에서 중앙 부분만 추출
            if scaled.width() > EVENT_THUMB_WIDTH or scaled.height() > EVENT_THUMB_HEIGHT:
                x = (scaled.width() - EVENT_THUMB_WIDTH) // 2
                y = (scaled.height() - EVENT_THUMB_HEIGHT) // 2
                cropped = scaled.copy(x, y, EVENT_THUMB_WIDTH, EVENT_THUMB_HEIGHT)
                self.thumb_label.setPixmap(cropped)
            else:
                self.thumb_label.setPixmap(scaled)
        else:
            self.thumb_label.setText("📷")
            self.thumb_label.setStyleSheet(f"""
                QLabel {{
                    background-color: {DARK_COLORS['bg_primary']};
                    border-radius: 4px;
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(24)}px;
                }}
            """)

    def _on_rating_clicked(self):
        """Rating 변경 클릭"""
        ratings = ["g", "s", "q", "e"]
        current = self.event_data.get("source_row", {}).get("rating", "g")
        try:
            next_idx = (ratings.index(current) + 1) % len(ratings)
        except ValueError:
            next_idx = 0
        new_rating = ratings[next_idx]

        self.rating_btn.setText(f"R:{new_rating.upper()}")
        self.rating_changed.emit(self.event_id, new_rating)

    def _on_edit_clicked(self):
        """수정 버튼 클릭"""
        if self.is_editing:
            # 수정 완료 - 저장
            self.general_edit.setReadOnly(True)
            self.edit_btn.setText("✏️")
            self.is_editing = False
            self.edit_requested.emit(self.event_id)
        else:
            # 수정 시작
            self.general_edit.setReadOnly(False)
            self.general_edit.setFocus()
            self.edit_btn.setText("💾")
            self.is_editing = True

    def get_general_text(self) -> str:
        """현재 General 텍스트 반환"""
        return self.general_edit.toPlainText()

    def _change_heart(self, delta: int):
        """하트 값 변경"""
        current = self.event_data.get("heart", 0)
        new_value = max(0, current + delta)  # 최소 0
        self.event_data["heart"] = new_value

        self.heart_label.setText(f"♥{new_value}")
        self.heart_label.setStyleSheet(f"""
            QLabel {{
                color: {'#FF6B9D' if new_value > 0 else DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
                min-width: 30px;
            }}
        """)
        self.heart_changed.emit(self.event_id, new_value)


class EventTabMixin:
    """이벤트 탭 관련 메서드들을 모은 Mixin 클래스

    RemoteWindow에서 다중 상속하여 사용합니다.

    필요한 속성 (RemoteWindow에서 제공):
    - self.remote_events: list
    - self.parent_app: 부모 앱 참조
    - self._event_auto_generate_pending: bool
    - self._show_warning: 메서드
    """

    def _init_event_tab_data(self):
        """이벤트 탭 관련 데이터 초기화"""
        self.event_queue = []
        self.event_filtered_ids = set()
        self.event_depth_filters = []

    def _load_remote_events(self):
        """저장된 이벤트 목록 로드"""
        if REMOTE_EVENTS_JSON.exists():
            try:
                with open(REMOTE_EVENTS_JSON, 'r', encoding='utf-8') as f:
                    self.remote_events = json.load(f)
                print(f"✅ 리모트 이벤트 {len(self.remote_events)}개 로드")
            except Exception as e:
                print(f"⚠️ 리모트 이벤트 로드 실패: {e}")
                self.remote_events = []
        else:
            self.remote_events = []

    def _save_remote_events(self):
        """이벤트 목록 저장"""
        try:
            with open(REMOTE_EVENTS_JSON, 'w', encoding='utf-8') as f:
                json.dump(self.remote_events, f, ensure_ascii=False, indent=2)
            print(f"✅ 리모트 이벤트 {len(self.remote_events)}개 저장")
        except Exception as e:
            print(f"⚠️ 리모트 이벤트 저장 실패: {e}")

    def _create_event_list_subtab(self, parent_tabs: QTabWidget):
        """이벤트 저장 목록 서브탭 - 개선된 UI"""
        evt_widget = QWidget()
        evt_layout = QVBoxLayout(evt_widget)
        evt_layout.setContentsMargins(8, 8, 8, 8)
        evt_layout.setSpacing(6)

        # === 상단 Row 1: 제목 및 개수 ===
        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        evt_info = QLabel("📌 저장된 이벤트")
        evt_info.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['accent_blue']};
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
            }}
        """)
        title_row.addWidget(evt_info)
        title_row.addStretch()

        evt_layout.addLayout(title_row)

        # === 상단 Row 2: Rating 필터 버튼 ===
        rating_row = QHBoxLayout()
        rating_row.setSpacing(6)

        rating_label = QLabel("등급:")
        rating_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(12)}px;")
        rating_row.addWidget(rating_label)

        # Rating 체크박스 버튼들
        self.event_rating_checks = {}
        rating_btn_style = f"""
            QCheckBox {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
                spacing: 4px;
            }}
            QCheckBox::indicator {{
                width: 14px;
                height: 14px;
            }}
        """
        for rating in ["g", "s", "q", "e"]:
            cb = QCheckBox(f"rating:{rating}")
            cb.setChecked(True)
            cb.setStyleSheet(rating_btn_style)
            cb.stateChanged.connect(self._on_event_filter_changed)
            self.event_rating_checks[rating] = cb
            rating_row.addWidget(cb)

        rating_row.addStretch()
        evt_layout.addLayout(rating_row)

        # === 상단 Row 3: 태그 검색 ===
        search_row = QHBoxLayout()
        search_row.setSpacing(6)

        search_label = QLabel("🔍")
        search_label.setStyleSheet(f"font-size: {get_scaled_font_size(14)}px;")
        search_row.addWidget(search_label)

        self.event_search_edit = QLineEdit()
        self.event_search_edit.setPlaceholderText("General 태그 검색 (쉼표로 구분, ~제외)")
        self.event_search_edit.setStyleSheet(f"""
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
        self.event_search_edit.returnPressed.connect(self._on_event_filter_changed)
        search_row.addWidget(self.event_search_edit, 1)

        search_btn = QPushButton("🔍 검색")
        search_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        search_btn.setFixedWidth(130)
        search_btn.clicked.connect(self._on_event_filter_changed)
        search_row.addWidget(search_btn)

        evt_layout.addLayout(search_row)

        # === 상단 Row 4: 심층 검색 ===
        depth_row = QHBoxLayout()
        depth_row.setSpacing(6)

        self.event_depth_search_edit = QLineEdit()
        self.event_depth_search_edit.setPlaceholderText("심층 검색 (현재 필터 결과에서 추가 검색)")
        self.event_depth_search_edit.setStyleSheet(f"""
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
        self.event_depth_search_edit.returnPressed.connect(self._on_event_depth_search)
        depth_row.addWidget(self.event_depth_search_edit, 1)

        depth_search_btn = QPushButton("🔎 심층 검색")
        depth_search_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        depth_search_btn.setFixedWidth(130)
        depth_search_btn.clicked.connect(self._on_event_depth_search)
        depth_row.addWidget(depth_search_btn)

        evt_layout.addLayout(depth_row)

        # === 상단 Row 5: 전체/현재 개수 라벨 + 초기화 버튼들 ===
        info_row = QHBoxLayout()
        info_row.setSpacing(8)

        # 전체 row 라벨
        self.event_total_label = QLabel(f"[전체: {len(self.remote_events)}]")
        self.event_total_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(12)}px;
            }}
        """)
        info_row.addWidget(self.event_total_label)

        # 현재 row 라벨
        self.event_current_label = QLabel("[현재: 0]")
        self.event_current_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['success']};
                font-size: {get_scaled_font_size(12)}px;
            }}
        """)
        info_row.addWidget(self.event_current_label)

        info_row.addStretch()

        depth_reset_btn = QPushButton("↩️ 심층검색 초기화")
        depth_reset_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        depth_reset_btn.clicked.connect(self._on_event_depth_reset)
        info_row.addWidget(depth_reset_btn)

        search_reset_btn = QPushButton("🔄 전체검색 초기화")
        search_reset_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        search_reset_btn.clicked.connect(self._on_event_search_reset)
        info_row.addWidget(search_reset_btn)

        evt_layout.addLayout(info_row)

        # === 중간: 이벤트 리스트 (스크롤 영역) ===
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

        self.events_list_widget = QWidget()
        self.events_list_layout = QVBoxLayout(self.events_list_widget)
        self.events_list_layout.setSpacing(6)
        self.events_list_layout.setContentsMargins(8, 8, 8, 8)
        self.events_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll_area.setWidget(self.events_list_widget)
        evt_layout.addWidget(scroll_area, 1)

        # === 하단: 대기열 관리 ===
        # 구분선
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        separator.setFixedHeight(1)
        evt_layout.addWidget(separator)

        # 대기열 전체 추가 버튼
        queue_all_btn = QPushButton("📋 현재 검색 결과 모두 대기열로 보내기")
        queue_all_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        queue_all_btn.clicked.connect(self._on_event_queue_all)
        evt_layout.addWidget(queue_all_btn)

        # 또 다른 구분선
        separator2 = QFrame()
        separator2.setFrameShape(QFrame.Shape.HLine)
        separator2.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        separator2.setFixedHeight(1)
        evt_layout.addWidget(separator2)

        # 대기열 상태 및 자동 생성
        queue_row = QHBoxLayout()
        queue_row.setSpacing(8)

        self.event_queue_count_label = QLabel("남은 대기열: 0")
        self.event_queue_count_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(12)}px;
            }}
        """)
        queue_row.addWidget(self.event_queue_count_label)

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
        queue_clear_btn.clicked.connect(self._on_event_queue_clear)
        queue_row.addWidget(queue_clear_btn)

        # 대���열 Parquet 내보내기 버튼
        queue_export_btn = QPushButton("💾 내보내기")
        queue_export_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['success']};
                border: 1px solid {DARK_COLORS['success']};
                border-radius: 4px;
                padding: 4px 12px;
                font-size: {get_scaled_font_size(12)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['success']};
                color: {DARK_COLORS['bg_primary']};
            }}
        """)
        queue_export_btn.setToolTip("대기열(또는 필터 결과)을 Parquet 파일로 내보내기")
        queue_export_btn.clicked.connect(self._on_event_export_parquet)
        queue_row.addWidget(queue_export_btn)

        queue_row.addStretch()

        self.event_auto_generate_check = QCheckBox("자동 생성")
        self.event_auto_generate_check.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.event_auto_generate_check.stateChanged.connect(self._on_event_auto_generate_changed)
        queue_row.addWidget(self.event_auto_generate_check)

        self.event_generate_btn = QPushButton("▶️ 생성 시작")
        self.event_generate_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.event_generate_btn.setFixedWidth(150)
        self.event_generate_btn.clicked.connect(self._on_event_generate_start)
        queue_row.addWidget(self.event_generate_btn)

        evt_layout.addLayout(queue_row)

        parent_tabs.addTab(evt_widget, "🎉 이벤트")

        # 데이터 초기화
        self._init_event_tab_data()

        # 초기 리스트 업데이트
        self._update_events_list()

    def add_remote_event(self, history_item):
        """HistoryItem을 이벤트로 추가

        Args:
            history_item: HistoryItem 객체 (source_row, thumbnail 등 포함)
        """
        # source_row가 없으면 무시
        if history_item.source_row is None or history_item.source_row.empty:
            self._show_warning("알림", "source_row가 없는 이미지는 이벤트로 저장할 수 없습니다.")
            return

        # 고유 ID 생성
        event_id = str(uuid.uuid4())[:8]
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

        # source_row를 딕셔너리로 변환 (JSON 저장 가능하도록)
        source_row_dict = history_item.source_row.to_dict()

        # 썸네일 저장
        thumb_filename = f"{event_id}.png"
        thumb_path = REMOTE_EVENTS_THUMBS_DIR / thumb_filename

        try:
            # QPixmap을 PIL Image로 변환하여 저장
            if history_item.thumbnail and not history_item.thumbnail.isNull():
                qimage = history_item.thumbnail.toImage()
                buffer = qimage.bits().asstring(qimage.sizeInBytes())

                # QImage 포맷에 따라 PIL 모드 결정
                if qimage.format() == QImage.Format.Format_RGBA8888:
                    pil_mode = "RGBA"
                    raw_mode = "RGBA"
                elif qimage.format() == QImage.Format.Format_RGB32:
                    pil_mode = "RGBA"
                    raw_mode = "BGRA"
                else:
                    # 안전하게 RGB32로 변환
                    qimage = qimage.convertToFormat(QImage.Format.Format_RGB32)
                    buffer = qimage.bits().asstring(qimage.sizeInBytes())
                    pil_mode = "RGBA"
                    raw_mode = "BGRA"

                pil_image = Image.frombytes(
                    pil_mode,
                    (qimage.width(), qimage.height()),
                    buffer,
                    "raw",
                    raw_mode
                )
                # 썸네일 크기로 리사이즈
                pil_image.thumbnail((EVENT_THUMB_WIDTH, EVENT_THUMB_HEIGHT), Image.Resampling.LANCZOS)
                pil_image.save(str(thumb_path), "PNG")
        except Exception as e:
            print(f"⚠️ 썸네일 저장 실패: {e}")
            thumb_filename = ""

        # 이벤트 이름 생성 (general 태그의 앞부분 사용)
        general_tags = source_row_dict.get('general', '')
        if isinstance(general_tags, str) and general_tags:
            # 첫 3개 태그만 사용
            tags_list = [t.strip() for t in general_tags.split(',')[:3]]
            event_name = ', '.join(tags_list)
            if len(event_name) > 30:
                event_name = event_name[:27] + "..."
        else:
            event_name = f"이벤트 {event_id}"

        # 중복 체크: 동일한 general 값을 가진 이벤트가 있는지 확인
        new_general = source_row_dict.get('general', '')
        for existing_evt in self.remote_events:
            existing_general = existing_evt.get("source_row", {}).get("general", "")
            if existing_general == new_general and new_general:
                self._show_warning("알림", "동일한 General 태그를 가진 이벤트가 이미 존재합니다.")
                return

        # 이벤트 데이터 생성
        event_data = {
            "id": event_id,
            "name": event_name,
            "source_row": source_row_dict,
            "thumbnail": thumb_filename,
            "created_at": timestamp,
            "heart": 0
        }

        # 목록에 추가 (최신이 위로)
        self.remote_events.insert(0, event_data)

        # 저장
        self._save_remote_events()

        # UI 업데이트
        self._update_events_list()

        print(f"✅ 리모트 이벤트 추가: {event_name}")

    def _update_events_list(self):
        """이벤트 리스트 업데이트 (필터링 및 정렬 적용)"""
        # 기존 위젯 제거
        while self.events_list_layout.count():
            item = self.events_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 개수 라벨 업데이트
        if hasattr(self, 'event_total_label'):
            self.event_total_label.setText(f"[전체: {len(self.remote_events)}]")

        if not self.remote_events:
            empty_label = QLabel("저장된 이벤트가 없습니다.\n이미지 우클릭 → '리모트에 이벤트 저장'으로 추가하세요.")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(12)}px;
                    padding: 40px;
                }}
            """)
            self.events_list_layout.addWidget(empty_label)
            if hasattr(self, 'event_current_label'):
                self.event_current_label.setText("[현재: 0]")
            self.event_filtered_ids = set()
            return

        # 필터링: rating
        enabled_ratings = set()
        if hasattr(self, 'event_rating_checks'):
            for rating, cb in self.event_rating_checks.items():
                if cb.isChecked():
                    enabled_ratings.add(rating)
        else:
            enabled_ratings = {"g", "s", "q", "e"}

        # 필터링: 태그 검색
        search_query = ""
        if hasattr(self, 'event_search_edit'):
            search_query = self.event_search_edit.text().strip()

        # 필터 적용
        filtered_events = []
        for evt in self.remote_events:
            # Rating 필터
            evt_rating = evt.get("source_row", {}).get("rating", "g")
            if evt_rating not in enabled_ratings:
                continue

            # 태그 검색 필터
            if search_query:
                general_text = evt.get("source_row", {}).get("general", "").lower()
                keywords = [k.strip().lower() for k in search_query.split(',') if k.strip()]

                match = True
                for kw in keywords:
                    if kw.startswith('~'):
                        # 제외 키워드
                        exclude_kw = kw[1:]
                        if exclude_kw and exclude_kw in general_text:
                            match = False
                            break
                    else:
                        # 포함 키워드
                        if kw not in general_text:
                            match = False
                            break

                if not match:
                    continue

            # 심층 검색 필터 적용
            if hasattr(self, 'event_depth_filters') and self.event_depth_filters:
                general_text = evt.get("source_row", {}).get("general", "").lower()
                depth_match = True
                for depth_query in self.event_depth_filters:
                    depth_keywords = [k.strip().lower() for k in depth_query.split(',') if k.strip()]
                    for kw in depth_keywords:
                        if kw.startswith('~'):
                            exclude_kw = kw[1:]
                            if exclude_kw and exclude_kw in general_text:
                                depth_match = False
                                break
                        else:
                            if kw not in general_text:
                                depth_match = False
                                break
                    if not depth_match:
                        break
                if not depth_match:
                    continue

            filtered_events.append(evt)

        # 정렬: heart(우선순위) 기준 내림차순
        filtered_events.sort(key=lambda x: x.get("heart", 0), reverse=True)

        # 필터된 ID 저장
        self.event_filtered_ids = {evt.get("id") for evt in filtered_events}

        # 필터 결과 표시
        if hasattr(self, 'event_current_label'):
            self.event_current_label.setText(f"[현재: {len(filtered_events)}]")

        if not filtered_events:
            empty_label = QLabel("필터 조건에 맞는 이벤트가 없습니다.")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(12)}px;
                    padding: 20px;
                }}
            """)
            self.events_list_layout.addWidget(empty_label)
            return

        # 리스트에 아이템 추가
        for evt in filtered_events:
            item_widget = EventItemWidget(evt, parent=self.events_list_widget)

            # 시그널 연결
            item_widget.instant_generate_requested.connect(self._on_event_instant_generate)
            item_widget.add_to_queue_requested.connect(self._on_event_add_to_queue)
            item_widget.delete_requested.connect(self._delete_event)
            item_widget.edit_requested.connect(self._on_event_edit_save)
            item_widget.heart_changed.connect(self._on_event_heart_changed)
            item_widget.rating_changed.connect(self._on_event_rating_changed)

            self.events_list_layout.addWidget(item_widget)

        # 하단에 spacer 추가
        self.events_list_layout.addStretch()

    def _on_event_filter_changed(self):
        """필터 변경 시 리스트 업데이트"""
        self._update_events_list()

    def _on_event_depth_search(self):
        """심층 검색 실행"""
        if not hasattr(self, 'event_depth_search_edit'):
            return

        depth_query = self.event_depth_search_edit.text().strip()
        if not depth_query:
            return

        if not hasattr(self, 'event_depth_filters'):
            self.event_depth_filters = []

        self.event_depth_filters.append(depth_query)
        self.event_depth_search_edit.clear()
        self._update_events_list()
        print(f"✅ 심층 검색 추가: {depth_query}")

    def _on_event_depth_reset(self):
        """심층 검색 초기화"""
        if hasattr(self, 'event_depth_filters'):
            self.event_depth_filters = []
        self._update_events_list()
        print("✅ 심층 검색 초기화")

    def _on_event_search_reset(self):
        """전체 검색 초기화"""
        if hasattr(self, 'event_search_edit'):
            self.event_search_edit.clear()
        if hasattr(self, 'event_depth_search_edit'):
            self.event_depth_search_edit.clear()
        if hasattr(self, 'event_depth_filters'):
            self.event_depth_filters = []
        if hasattr(self, 'event_rating_checks'):
            for cb in self.event_rating_checks.values():
                cb.setChecked(True)
        self._update_events_list()
        print("✅ 전체 검색 초기화")

    def _on_event_instant_generate(self, event_id: str):
        """이벤트 즉시 생성"""
        import pandas as pd

        target_event = None
        for evt in self.remote_events:
            if evt.get("id") == event_id:
                target_event = evt
                break

        if not target_event:
            return

        source_row_dict = target_event.get("source_row", {})

        if self.parent_app and hasattr(self.parent_app, 'on_generate_with_image_requested'):
            # on_generate_with_image_requested 사용
            self.parent_app.on_generate_with_image_requested(source_row_dict)
            print(f"✅ 이벤트 즉시 생성: {target_event.get('name', event_id)}")
        elif self.parent_app and hasattr(self.parent_app, 'on_instant_generation_requested'):
            source_row = pd.Series(source_row_dict)
            self.parent_app.on_instant_generation_requested(source_row)
            print(f"✅ 이벤트 즉시 생성: {target_event.get('name', event_id)}")

    def _on_event_add_to_queue(self, event_id: str):
        """이벤트를 대기열에 추가"""
        if not hasattr(self, 'event_queue'):
            self.event_queue = []

        # 중복 방지
        if event_id not in self.event_queue:
            self.event_queue.append(event_id)
            self._update_event_queue_label()
            print(f"✅ 대기열에 추가: {event_id}")

    def _on_event_edit_save(self, event_id: str):
        """이벤트 수정 저장"""
        # EventItemWidget에서 수정된 general 텍스트 가져오기
        for i in range(self.events_list_layout.count()):
            item = self.events_list_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if isinstance(widget, EventItemWidget) and widget.event_id == event_id:
                    new_general = widget.get_general_text()

                    # 이벤트 데이터 업데이트
                    for evt in self.remote_events:
                        if evt.get("id") == event_id:
                            evt["source_row"]["general"] = new_general
                            break

                    self._save_remote_events()
                    print(f"✅ 이벤트 수정 저장: {event_id}")
                    break

    def _on_event_heart_changed(self, event_id: str, new_value: int):
        """하트(우선순위) 변경"""
        for evt in self.remote_events:
            if evt.get("id") == event_id:
                evt["heart"] = new_value
                break

        self._save_remote_events()
        # 정렬이 바뀔 수 있으므로 리스트 업데이트
        QTimer.singleShot(100, self._update_events_list)

    def _on_event_rating_changed(self, event_id: str, new_rating: str):
        """Rating 변경"""
        for evt in self.remote_events:
            if evt.get("id") == event_id:
                evt["source_row"]["rating"] = new_rating
                break

        self._save_remote_events()

    def _on_event_queue_all(self):
        """현재 필터된 모든 이벤트를 대기열에 추가"""
        if not hasattr(self, 'event_filtered_ids') or not self.event_filtered_ids:
            self._show_warning("알림", "추가할 이벤트가 없습니다.")
            return

        if not hasattr(self, 'event_queue'):
            self.event_queue = []

        added_count = 0
        for event_id in self.event_filtered_ids:
            if event_id not in self.event_queue:
                self.event_queue.append(event_id)
                added_count += 1

        self._update_event_queue_label()
        print(f"✅ {added_count}개 이벤트를 대기열에 추가")

    def _update_event_queue_label(self):
        """대기열 개수 라벨 업데이트"""
        if hasattr(self, 'event_queue_count_label') and hasattr(self, 'event_queue'):
            self.event_queue_count_label.setText(f"남은 대기열: {len(self.event_queue)}")

    def _on_event_auto_generate_changed(self, state):
        """자동 생성 체크박스 변경"""
        if state == Qt.CheckState.Checked.value:
            print("✅ 자동 생성 활성화")
        else:
            print("✅ 자동 생성 비활성화")

    def _on_event_queue_clear(self):
        """대기열 비우기"""
        if not hasattr(self, 'event_queue') or not self.event_queue:
            return

        self.event_queue.clear()
        self._update_event_queue_label()

    def _on_event_generate_start(self):
        """생성 시작 버튼 클릭"""
        if not hasattr(self, 'event_queue') or not self.event_queue:
            self._show_warning("알림", "대기열이 비어 있습니다.")
            return

        # 자동 생성이 활성화되어 있으면 플래그 설정
        if (hasattr(self, 'event_auto_generate_check') and
            self.event_auto_generate_check.isChecked()):
            self._event_auto_generate_pending = True

        # 첫 번째 이벤트 실행
        event_id = self.event_queue.pop(0)
        self._update_event_queue_label()
        self._on_event_instant_generate(event_id)

    def _delete_event(self, event_id: str):
        """이벤트 삭제"""
        # 이벤트 찾기 및 삭제
        for i, evt in enumerate(self.remote_events):
            if evt.get("id") == event_id:
                # 썸네일 파일 삭제
                thumb_path = REMOTE_EVENTS_THUMBS_DIR / evt.get("thumbnail", "")
                if thumb_path.exists():
                    try:
                        thumb_path.unlink()
                    except:
                        pass

                # 목록에서 제거
                del self.remote_events[i]
                break

        # 대기열에서도 제거
        if hasattr(self, 'event_queue') and event_id in self.event_queue:
            self.event_queue.remove(event_id)
            self._update_event_queue_label()

        # 저장 및 UI 업데이트
        self._save_remote_events()
        self._update_events_list()
        print(f"✅ 이벤트 삭제: {event_id}")

    def _on_event_export_parquet(self):
        """대기열(또는 필터 결과) 이벤트를 Parquet 파일로 내보내기"""
        import pandas as pd
        from PyQt6.QtWidgets import QFileDialog

        # 대기열이 있으면 대기열 기준, 없으면 현재 필터 결과 기준
        if hasattr(self, 'event_queue') and self.event_queue:
            target_ids = set(self.event_queue)
            source_label = "대기열"
        elif hasattr(self, 'event_filtered_ids') and self.event_filtered_ids:
            target_ids = self.event_filtered_ids
            source_label = "필터 결과"
        else:
            self._show_warning("알림", "내보낼 이벤트가 없습니다.\n대기열에 추가하거나 필터 결과가 있어야 합니다.")
            return

        # source_row dict 수집
        rows = []
        for evt in self.remote_events:
            if evt.get("id") in target_ids:
                source_row = evt.get("source_row", {})
                if source_row:
                    rows.append(source_row)

        if not rows:
            self._show_warning("알림", "내보낼 유효한 이벤트 데이터가 없습니다.")
            return

        df = pd.DataFrame(rows)

        # 저장 경로
        save_dir = Path("save/custom_tags")
        save_dir.mkdir(parents=True, exist_ok=True)

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "이벤트 Parquet 내보내기",
            str(save_dir / "remote_events_export.parquet"),
            "Parquet Files (*.parquet)"
        )

        if file_path:
            try:
                df.to_parquet(file_path, index=False)
                self._show_info(
                    "내보내기 완료",
                    f"{source_label}에서 {len(rows)}개 이벤트를 내보냈습니다.\n\n"
                    f"메인 윈도우 복원 메뉴 → 📂 불러오기로 로드하세요."
                )
                print(f"✅ 이벤트 Parquet 내보내기: {len(rows)}개 → {file_path}")
            except Exception as e:
                self._show_warning("내보내기 실패", f"파일 저장 중 오류:\n{e}")
