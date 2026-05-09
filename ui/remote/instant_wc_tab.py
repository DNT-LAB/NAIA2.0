# ui/remote/instant_wc_tab.py
"""
인스턴트 와일드카드 탭 관련 위젯 및 핸들러 - RemoteWindow에서 분리

구성요소:
- WildcardItemWidget: 와일드카드 아이템 위젯 (썸네일 + 태그 + 버튼)
- InstantWcTabMixin: 인스턴트 와일드카드 탭 관련 메서드들을 모은 Mixin 클래스
"""

import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QFrame, QTabWidget, QCheckBox,
    QTextEdit, QComboBox, QApplication, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap

from ui.theme import DARK_COLORS, DARK_STYLES
from ui.scaling_manager import get_scaled_font_size
from utils.clipboard_image import qimage_from_clipboard


# === 상수 정의 ===
WC_THUMB_WIDTH = 120
WC_THUMB_HEIGHT = 167  # 368:512 비율 유지


class WildcardItemWidget(QFrame):
    """인스턴트 와일드카드 아이템 위젯 - 1줄 전체 레이아웃"""

    # 시그널 정의
    instant_generate_requested = pyqtSignal(str, str)  # file_key, item_key
    add_to_queue_requested = pyqtSignal(str, str)  # file_key, item_key
    delete_requested = pyqtSignal(str, str)  # file_key, item_key
    edit_requested = pyqtSignal(str, str, str)  # file_key, item_key, new_value
    heart_changed = pyqtSignal(str, str, int)  # file_key, item_key, new_value
    clip_requested = pyqtSignal(str, str)  # file_key, item_key (클립보드 이미지 할당)

    def __init__(self, file_key: str, item_key: str, item_data: dict, parent=None):
        super().__init__(parent)
        self.file_key = file_key  # JSON 파일명 (확장자 제외)
        self.item_key = item_key  # 와일드카드 키
        self.item_data = item_data  # {"value": "...", "heart": 0}
        self._setup_ui()

    def _setup_ui(self):
        self.setFrameStyle(QFrame.Shape.StyledPanel)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 6px;
            }}
        """)
        # 위젯 최소 높이 설정 (이벤트보다 조금 더 높게)
        self.setMinimumHeight(200)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(12)

        # 썸네일 (120x167, 중앙 크롭)
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(WC_THUMB_WIDTH, WC_THUMB_HEIGHT)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_primary']};
                border-radius: 4px;
            }}
        """)
        self._load_thumbnail()
        main_layout.addWidget(self.thumb_label)

        # 오른쪽 영역 (항목명 + 태그 + 버튼)
        right_layout = QVBoxLayout()
        right_layout.setSpacing(6)

        # 상단: 항목명 라벨 (file_key::item_key 형식)
        name_label = QLabel(f"📌 {self.file_key}::{self.item_key}")
        name_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['accent_blue']};
                font-size: {get_scaled_font_size(13)}px;
                font-weight: bold;
                background-color: transparent;
            }}
        """)
        right_layout.addWidget(name_label)

        # 중단: 와일드카드 값 (TextEdit) - 4:1 비율 중 상단
        self.value_edit = QTextEdit()
        self.value_edit.setAcceptRichText(False)
        # value가 dict인 경우 문자열로 변환
        value = self.item_data.get("value", "")
        if isinstance(value, dict):
            value = str(value)
        self.value_edit.setPlainText(value)
        self.value_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 4px;
                font-size: {get_scaled_font_size(16)}px;
            }}
            QTextEdit:focus {{
                border: 1px solid {DARK_COLORS['accent_blue']};
            }}
        """)
        right_layout.addWidget(self.value_edit, 4)  # 4 비율

        # 하단: 버튼 행 - 1 비율
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(4)

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
                background-color: {DARK_COLORS['bg_hover']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
        """

        # Clip 버튼 (클립보드 이미지 할당)
        self.clip_btn = QPushButton("📋Clip")
        self.clip_btn.setStyleSheet(small_btn_style)
        self.clip_btn.setToolTip("클립보드 이미지를 썸네일로 할당")
        self.clip_btn.clicked.connect(self._on_clip_clicked)
        btn_layout.addWidget(self.clip_btn)

        # 수정 버튼
        edit_btn = QPushButton("✏️수정")
        edit_btn.setStyleSheet(small_btn_style)
        edit_btn.setToolTip("와일드카드 값 수정")
        edit_btn.clicked.connect(self._on_edit_clicked)
        btn_layout.addWidget(edit_btn)

        # 삭제 버튼
        delete_btn = QPushButton("🗑️삭제")
        delete_btn.setStyleSheet(small_btn_style)
        delete_btn.setToolTip("와일드카드 삭제")
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.file_key, self.item_key))
        btn_layout.addWidget(delete_btn)

        # 즉시 생성 버튼
        instant_btn = QPushButton("⚡즉시")
        instant_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['success']};
                color: white;
                border: none;
                border-radius: 3px;
                padding: 3px 8px;
                font-size: {get_scaled_font_size(13)}px;
                min-width: 35px;
            }}
            QPushButton:hover {{
                background-color: #5CBF60;
            }}
        """)
        instant_btn.setToolTip("즉시 생성")
        instant_btn.clicked.connect(lambda: self.instant_generate_requested.emit(self.file_key, self.item_key))
        btn_layout.addWidget(instant_btn)

        # 대기열 추가 버튼
        queue_btn = QPushButton("📋대기열")
        queue_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
                border: none;
                border-radius: 3px;
                padding: 3px 8px;
                font-size: {get_scaled_font_size(13)}px;
                min-width: 35px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
        """)
        queue_btn.setToolTip("대기열에 추가")
        queue_btn.clicked.connect(lambda: self.add_to_queue_requested.emit(self.file_key, self.item_key))
        btn_layout.addWidget(queue_btn)

        btn_layout.addStretch()

        # 하트 버튼들
        heart_minus_btn = QPushButton("♥-")
        heart_minus_btn.setStyleSheet(small_btn_style)
        heart_minus_btn.setToolTip("우선순위 감소")
        heart_minus_btn.clicked.connect(lambda: self._change_heart(-1))
        btn_layout.addWidget(heart_minus_btn)

        self.heart_label = QLabel(str(self.item_data.get("heart", 0)))
        self.heart_label.setFixedWidth(30)
        self.heart_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.heart_label.setStyleSheet(f"""
            QLabel {{
                color: #FF6B9D;
                font-size: {get_scaled_font_size(15)}px;
                font-weight: bold;
            }}
        """)
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
        image_path = Path("save") / "instant_wildcard" / "images" / self.file_key / f"{self.item_key}.png"

        if image_path.exists():
            pixmap = QPixmap(str(image_path))
            # KeepAspectRatioByExpanding으로 확대하여 빈 공간 없이 채움
            scaled = pixmap.scaled(
                WC_THUMB_WIDTH, WC_THUMB_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            # 중앙 크롭
            if scaled.width() > WC_THUMB_WIDTH or scaled.height() > WC_THUMB_HEIGHT:
                x = (scaled.width() - WC_THUMB_WIDTH) // 2
                y = (scaled.height() - WC_THUMB_HEIGHT) // 2
                cropped = scaled.copy(x, y, WC_THUMB_WIDTH, WC_THUMB_HEIGHT)
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

    def _on_clip_clicked(self):
        """Clip 버튼 클릭 - 클립보드 이미지 할당"""
        self.clip_requested.emit(self.file_key, self.item_key)

    def _on_edit_clicked(self):
        """수정 버튼 클릭"""
        new_value = self.value_edit.toPlainText()
        self.edit_requested.emit(self.file_key, self.item_key, new_value)

    def _change_heart(self, delta: int):
        """하트 값 변경"""
        current = self.item_data.get("heart", 0)
        new_value = max(0, current + delta)
        self.item_data["heart"] = new_value
        self.heart_label.setText(str(new_value))
        self.heart_changed.emit(self.file_key, self.item_key, new_value)

    def has_thumbnail(self) -> bool:
        """썸네일 존재 여부"""
        image_path = Path("save") / "instant_wildcard" / "images" / self.file_key / f"{self.item_key}.png"
        return image_path.exists()

    def refresh_thumbnail(self):
        """썸네일 새로고침"""
        self._load_thumbnail()


class InstantWcTabMixin:
    """인스턴트 와일드카드 탭 관련 메서드들을 모은 Mixin 클래스

    RemoteWindow에서 다중 상속하여 사용합니다.

    필요한 속성 (RemoteWindow에서 제공):
    - self.instant_wc_module: 와일드카드 모듈 참조
    - self.parent_app: 부모 앱 참조
    - self._wc_auto_generate_pending: bool
    - self._show_warning: 메서드
    """

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

    def _get_wc_module(self):
        """instant_wildcard_module 가져오기"""
        return self.instant_wc_module

    def _update_wc_list(self):
        """와일드카드 리스트 업데이트"""
        # 기존 위젯 제거
        while self.wc_list_layout.count():
            item = self.wc_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 와일드카드 모듈에서 데이터 가져오기
        wc_module = self._get_wc_module()
        if not wc_module:
            empty_label = QLabel("와일드카드 모듈을 찾을 수 없습니다.")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(12)}px;
                    padding: 40px;
                }}
            """)
            self.wc_list_layout.addWidget(empty_label)
            return

        wc_tree = wc_module.instant_wildcard_tree

        # 전체 개수 라벨 업데이트
        total_items = sum(len(items) for items in wc_tree.values())
        if hasattr(self, 'wc_total_label'):
            self.wc_total_label.setText(f"[전체: {total_items}]")

        if not wc_tree:
            empty_label = QLabel("저장된 와일드카드가 없습니다.\n텍스트 선택 후 우클릭 → '와일드카드 추가'로 추가하세요.")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(12)}px;
                    padding: 40px;
                }}
            """)
            self.wc_list_layout.addWidget(empty_label)
            if hasattr(self, 'wc_current_label'):
                self.wc_current_label.setText("[현재: 0]")
            return

        # 파일 콤보 선택 확인
        selected_file = None
        if hasattr(self, 'wc_file_combo'):
            selected_text = self.wc_file_combo.currentText()
            if selected_text and selected_text != "(전체)":
                selected_file = selected_text

        # 제목 검색 쿼리
        title_query = ""
        if hasattr(self, 'wc_search_input'):
            title_query = self.wc_search_input.text().strip().lower()

        # 필터링된 아이템 수집
        filtered_items = []  # [(file_key, item_key, value, heart), ...]

        for file_key, items in wc_tree.items():
            # 파일 필터
            if selected_file and file_key != selected_file:
                continue

            for item_key, value in items.items():
                # 제목(키) 검색 필터
                if title_query:
                    keywords = [k.strip() for k in title_query.split(',') if k.strip()]
                    match = True
                    for kw in keywords:
                        if kw.startswith('~'):
                            exclude_kw = kw[1:].lower()
                            if exclude_kw and exclude_kw in item_key.lower():
                                match = False
                                break
                        else:
                            if kw.lower() not in item_key.lower():
                                match = False
                                break
                    if not match:
                        continue

                # 심층 검색(태그) 필터 적용
                if hasattr(self, 'wc_depth_filters') and self.wc_depth_filters:
                    depth_match = True
                    for depth_query in self.wc_depth_filters:
                        depth_keywords = [k.strip() for k in depth_query.split(',') if k.strip()]
                        for kw in depth_keywords:
                            if kw.startswith('~'):
                                exclude_kw = kw[1:].lower()
                                if exclude_kw and exclude_kw in value.lower():
                                    depth_match = False
                                    break
                            else:
                                if kw.lower() not in value.lower():
                                    depth_match = False
                                    break
                        if not depth_match:
                            break
                    if not depth_match:
                        continue

                # 하트 값 가져오기
                heart = self._get_wc_heart(file_key, item_key)
                filtered_items.append((file_key, item_key, value, heart))

        # 정렬: heart 기준 내림차순
        filtered_items.sort(key=lambda x: x[3], reverse=True)

        # 현재 개수 라벨 업데이트
        if hasattr(self, 'wc_current_label'):
            self.wc_current_label.setText(f"[현재: {len(filtered_items)}]")

        if not filtered_items:
            empty_label = QLabel("필터 조건에 맞는 와일드카드가 없습니다.")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(12)}px;
                    padding: 20px;
                }}
            """)
            self.wc_list_layout.addWidget(empty_label)
            return

        # 리스트에 아이템 추가
        for file_key, item_key, value, heart in filtered_items:
            item_data = {"value": value, "heart": heart}
            item_widget = WildcardItemWidget(file_key, item_key, item_data, parent=self.wc_list_widget)

            # 시그널 연결
            item_widget.instant_generate_requested.connect(self._on_wc_instant_generate)
            item_widget.add_to_queue_requested.connect(self._on_wc_add_to_queue)
            item_widget.delete_requested.connect(self._on_wc_delete)
            item_widget.edit_requested.connect(self._on_wc_edit_save)
            item_widget.heart_changed.connect(self._on_wc_heart_changed)
            item_widget.clip_requested.connect(self._on_wc_clip_image)

            self.wc_list_layout.addWidget(item_widget)

        # 하단에 spacer 추가
        self.wc_list_layout.addStretch()

    def _load_wc_metadata(self):
        """와일드카드 메타데이터 로드 (하트 등)"""
        metadata_path = Path("save") / "instant_wildcard" / "wc_metadata.json"
        if metadata_path.exists():
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    self.wc_metadata = json.load(f)
            except Exception as e:
                print(f"⚠️ WC 메타데이터 로드 실패: {e}")
                self.wc_metadata = {}
        else:
            self.wc_metadata = {}

    def _save_wc_metadata(self):
        """와일드카드 메타데이터 저장"""
        metadata_path = Path("save") / "instant_wildcard" / "wc_metadata.json"
        try:
            metadata_path.parent.mkdir(parents=True, exist_ok=True)
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(self.wc_metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ WC 메타데이터 저장 실패: {e}")

    def _get_wc_heart(self, file_key: str, item_key: str) -> int:
        """와일드카드 아이템의 하트 값 가져오기"""
        if not hasattr(self, 'wc_metadata'):
            self._load_wc_metadata()
        key = f"{file_key}::{item_key}"
        return self.wc_metadata.get(key, {}).get("heart", 0)

    def _set_wc_heart(self, file_key: str, item_key: str, value: int):
        """와일드카드 아이템의 하트 값 설정"""
        if not hasattr(self, 'wc_metadata'):
            self._load_wc_metadata()
        key = f"{file_key}::{item_key}"
        if key not in self.wc_metadata:
            self.wc_metadata[key] = {}
        self.wc_metadata[key]["heart"] = value
        self._save_wc_metadata()

    def _update_wc_file_combo(self):
        """파일 콤보박스 업데이트"""
        if not hasattr(self, 'wc_file_combo'):
            return

        wc_module = self._get_wc_module()
        if not wc_module:
            return

        current_text = self.wc_file_combo.currentText()

        self.wc_file_combo.blockSignals(True)
        self.wc_file_combo.clear()
        self.wc_file_combo.addItem("(전체)")

        for file_key in sorted(wc_module.instant_wildcard_tree.keys()):
            self.wc_file_combo.addItem(file_key)

        # 이전 선택 복원
        idx = self.wc_file_combo.findText(current_text)
        if idx >= 0:
            self.wc_file_combo.setCurrentIndex(idx)

        self.wc_file_combo.blockSignals(False)

    def _on_wc_file_changed(self, text: str):
        """파일 선택 변경 시"""
        self._update_wc_list()

    def _on_wc_search(self):
        """제목 검색 실행"""
        self._update_wc_list()

    def _on_wc_depth_search(self):
        """심층 검색(태그 검색) 실행"""
        if not hasattr(self, 'wc_depth_input'):
            return

        depth_query = self.wc_depth_input.text().strip()
        if not depth_query:
            return

        if not hasattr(self, 'wc_depth_filters'):
            self.wc_depth_filters = []

        self.wc_depth_filters.append(depth_query)
        self.wc_depth_input.clear()
        self._update_wc_list()
        print(f"✅ WC 심층 검색 추가: {depth_query}")

    def _on_wc_depth_reset(self):
        """심층 검색 한단계 되돌리기"""
        if hasattr(self, 'wc_depth_filters') and self.wc_depth_filters:
            removed = self.wc_depth_filters.pop()
            self._update_wc_list()
            print(f"✅ WC 심층 검색 제거: {removed}")

    def _on_wc_search_reset(self):
        """전체검색 초기화"""
        if hasattr(self, 'wc_search_input'):
            self.wc_search_input.clear()
        if hasattr(self, 'wc_depth_input'):
            self.wc_depth_input.clear()
        if hasattr(self, 'wc_depth_filters'):
            self.wc_depth_filters.clear()
        if hasattr(self, 'wc_file_combo'):
            self.wc_file_combo.setCurrentIndex(0)  # (전체)
        self._update_wc_list()
        print("✅ WC 전체 검색 초기화")

    def _on_wc_queue_all(self):
        """현재 필터된 모든 와일드카드를 대기열에 추가"""
        # 현재 표시된 아이템들 수집
        wc_module = self._get_wc_module()
        if not wc_module:
            return

        wc_tree = wc_module.instant_wildcard_tree

        # 파일 필터
        selected_file = None
        if hasattr(self, 'wc_file_combo'):
            selected_text = self.wc_file_combo.currentText()
            if selected_text and selected_text != "(전체)":
                selected_file = selected_text

        # 제목 검색 쿼리
        title_query = ""
        if hasattr(self, 'wc_search_input'):
            title_query = self.wc_search_input.text().strip().lower()

        added_count = 0
        for file_key, items in wc_tree.items():
            if selected_file and file_key != selected_file:
                continue

            for item_key, value in items.items():
                # 제목 검색 필터
                if title_query:
                    keywords = [k.strip() for k in title_query.split(',') if k.strip()]
                    match = True
                    for kw in keywords:
                        if kw.startswith('~'):
                            exclude_kw = kw[1:].lower()
                            if exclude_kw and exclude_kw in item_key.lower():
                                match = False
                                break
                        else:
                            if kw.lower() not in item_key.lower():
                                match = False
                                break
                    if not match:
                        continue

                # 심층 검색 필터
                if hasattr(self, 'wc_depth_filters') and self.wc_depth_filters:
                    depth_match = True
                    for depth_query in self.wc_depth_filters:
                        depth_keywords = [k.strip() for k in depth_query.split(',') if k.strip()]
                        for kw in depth_keywords:
                            if kw.startswith('~'):
                                exclude_kw = kw[1:].lower()
                                if exclude_kw and exclude_kw in value.lower():
                                    depth_match = False
                                    break
                            else:
                                if kw.lower() not in value.lower():
                                    depth_match = False
                                    break
                        if not depth_match:
                            break
                    if not depth_match:
                        continue

                # 대기열에 추가
                queue_item = (file_key, item_key)
                if queue_item not in self.wc_queue:
                    self.wc_queue.append(queue_item)
                    added_count += 1

        self._update_wc_queue_label()
        print(f"✅ {added_count}개 와일드카드를 대기열에 추가")

    def _update_wc_queue_label(self):
        """대기열 개수 라벨 업데이트"""
        if hasattr(self, 'wc_queue_count_label') and hasattr(self, 'wc_queue'):
            self.wc_queue_count_label.setText(f"남은 대기열: {len(self.wc_queue)}")

    def _on_wc_queue_clear(self):
        """대기열 비우기"""
        if hasattr(self, 'wc_queue'):
            self.wc_queue.clear()
            self._update_wc_queue_label()
            print("✅ WC 대기열 비움")

    def _on_wc_auto_generate_changed(self, state):
        """자동 생성 체크박스 변경"""
        if state == Qt.CheckState.Checked.value:
            print("✅ WC 자동 생성 활성화")
        else:
            print("✅ WC 자동 생성 비활성화")

    def _on_wc_generate_start(self):
        """생성 시작 버튼 클릭"""
        if not hasattr(self, 'wc_queue') or not self.wc_queue:
            self._show_warning("알림", "대기열이 비어 있습니다.")
            return

        # 자동 생성이 활성화되어 있으면 플래그 설정
        if (hasattr(self, 'wc_auto_generate_check') and
            self.wc_auto_generate_check.isChecked()):
            self._wc_auto_generate_pending = True

        # 첫 번째 아이템 실행
        file_key, item_key = self.wc_queue.pop(0)
        self._update_wc_queue_label()
        self._on_wc_instant_generate(file_key, item_key)

    def _on_wc_instant_generate(self, file_key: str, item_key: str):
        """와일드카드 즉시 생성"""
        wc_module = self._get_wc_module()
        if not wc_module:
            self._show_warning("오류", "와일드카드 모듈을 찾을 수 없습니다.")
            return

        # 와일드카드 값 가져오기
        wc_tree = wc_module.instant_wildcard_tree
        if file_key not in wc_tree or item_key not in wc_tree[file_key]:
            self._show_warning("오류", f"와일드카드를 찾을 수 없습니다: {file_key}::{item_key}")
            return

        value = wc_tree[file_key][item_key]

        # 가상 row 생성 (이벤트 탭과 동일한 방식)
        source_row_dict = {
            'general': value,
            'character': '',
            'copyright': '',
            'artist': '',
            'meta': '',
            'rating': 'g',
            'score': 0,
            'id': f"wc_{file_key}_{item_key}"
        }

        # parent_app을 통해 생성 요청 (이벤트 탭과 동일한 방식)
        if self.parent_app and hasattr(self.parent_app, 'on_generate_with_image_requested'):
            self.parent_app.on_generate_with_image_requested(source_row_dict)
            print(f"✅ WC 즉시 생성: {file_key}::{item_key}")

            # 썸네일이 없으면 생성 완료 후 저장하도록 플래그 설정
            thumb_path = Path("save") / "instant_wildcard" / "images" / file_key / f"{item_key}.png"
            if not thumb_path.exists():
                self._pending_wc_thumbnail = {
                    'file_key': file_key,
                    'item_key': item_key
                }
        elif self.parent_app and hasattr(self.parent_app, 'on_instant_generation_requested'):
            import pandas as pd
            source_row = pd.Series(source_row_dict)
            self.parent_app.on_instant_generation_requested(source_row)
            print(f"✅ WC 즉시 생성: {file_key}::{item_key}")

    def _on_wc_add_to_queue(self, file_key: str, item_key: str):
        """대기열에 추가"""
        if not hasattr(self, 'wc_queue'):
            self.wc_queue = []

        queue_item = (file_key, item_key)
        if queue_item not in self.wc_queue:
            self.wc_queue.append(queue_item)
            self._update_wc_queue_label()
            print(f"✅ WC 대기열 추가: {file_key}::{item_key}")
        else:
            print(f"⚠️ 이미 대기열에 있음: {file_key}::{item_key}")

    def _on_wc_delete(self, file_key: str, item_key: str):
        """와일드카드 삭제"""
        wc_module = self._get_wc_module()
        if not wc_module:
            return

        # 와일드카드 모듈에서 삭제
        if hasattr(wc_module, 'delete_wildcard'):
            wc_module.delete_wildcard(file_key, item_key)

        # 썸네일 삭제
        thumb_path = Path("save") / "instant_wildcard" / "images" / file_key / f"{item_key}.png"
        if thumb_path.exists():
            try:
                thumb_path.unlink()
            except:
                pass

        # 메타데이터에서 삭제
        if hasattr(self, 'wc_metadata'):
            key = f"{file_key}::{item_key}"
            if key in self.wc_metadata:
                del self.wc_metadata[key]
                self._save_wc_metadata()

        # 대기열에서도 제거
        if hasattr(self, 'wc_queue'):
            queue_item = (file_key, item_key)
            if queue_item in self.wc_queue:
                self.wc_queue.remove(queue_item)
                self._update_wc_queue_label()

        # UI 업데이트
        self._update_wc_file_combo()
        self._update_wc_list()
        print(f"✅ 와일드카드 삭제: {file_key}::{item_key}")

    def _on_wc_edit_save(self, file_key: str, item_key: str, new_value: str):
        """와일드카드 값 수정"""
        wc_module = self._get_wc_module()
        if not wc_module:
            return

        # 와일드카드 모듈에서 업데이트
        if hasattr(wc_module, 'update_wildcard_value'):
            wc_module.update_wildcard_value(file_key, item_key, new_value)
            print(f"✅ 와일드카드 수정: {file_key}::{item_key}")

    def _on_wc_heart_changed(self, file_key: str, item_key: str, new_value: int):
        """하트 값 변경"""
        self._set_wc_heart(file_key, item_key, new_value)
        print(f"✅ WC 하트 변경: {file_key}::{item_key} = {new_value}")

    def _on_wc_clip_image(self, file_key: str, item_key: str):
        """클립보드 이미지를 썸네일로 할당"""
        clipboard = QApplication.clipboard()
        image = qimage_from_clipboard(clipboard)
        if image.isNull():
            self._show_warning("알림", "클립보드 이미지를 읽을 수 없습니다.")
            return

        # 저장 경로
        thumb_dir = Path("save") / "instant_wildcard" / "images" / file_key
        thumb_path = thumb_dir / f"{item_key}.png"

        # 기존 파일이 있으면 덮어쓰기 확인
        if thumb_path.exists():
            reply = QMessageBox.question(
                self,
                "확인",
                f"'{item_key}'의 썸네일이 이미 존재합니다.\n덮어쓰시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # 디렉토리 생성
        thumb_dir.mkdir(parents=True, exist_ok=True)

        # QImage를 QPixmap으로 변환 후 크기 조정
        pixmap = QPixmap.fromImage(image)

        # 512px로 리사이즈 (가로/세로 중 큰 쪽 기준)
        max_size = 512
        if pixmap.width() > max_size or pixmap.height() > max_size:
            pixmap = pixmap.scaled(
                max_size, max_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

        # 저장
        if pixmap.save(str(thumb_path), "PNG"):
            print(f"✅ WC 썸네일 저장: {thumb_path}")
            # 리스트 업데이트
            self._update_wc_list()
        else:
            self._show_warning("오류", "썸네일 저장에 실패했습니다.")
