# ui/remote/char_ref_tab.py
"""
캐릭터 레퍼런스 탭 Mixin - RemoteWindow용

CharRefFavoriteItemWidget: 캐릭터 레퍼런스 즐겨찾기 아이템 위젯
CharRefTabMixin: 캐릭터 레퍼런스 탭 관련 메서드 모음
"""

import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTabWidget, QLabel, QComboBox, QTextEdit, QPushButton,
    QScrollArea, QFrame, QMessageBox, QApplication,
    QCheckBox, QSlider, QFileDialog, QLineEdit, QDialog
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap

from legacy_desktop.ui.theme import DARK_COLORS, DARK_STYLES
from legacy_desktop.ui.scaling_manager import get_scaled_font_size, get_scaled_size
from utils.clipboard_image import clipboard_png_bytes


# 즐겨찾기 썸네일 기본 크기 상수
FAVORITE_THUMB_WIDTH = 120
FAVORITE_THUMB_HEIGHT = 167  # 368:512 비율 유지
PREVIEW_THUMB_WIDTH = 140
PREVIEW_THUMB_HEIGHT = 195
THUMB_ASPECT_RATIO = 368 / 512  # 가로/세로 비율

# 캐릭터 레퍼런스 즐겨찾기 상수
CHAR_REF_FAVORITES_DIR = Path("save/character_reference/favorites")
CHAR_REF_FAVORITES_JSON = Path("save/character_reference/favorites.json")
CHAR_REF_FOLDERS_JSON = Path("save/character_reference/favorite_folders.json")


class CharRefFavoriteItemWidget(QFrame):
    """캐릭터 레퍼런스 즐겨찾기 아이템 위젯 (2줄 라벨: 이름 + Style/Fidelity)"""

    clicked = pyqtSignal(dict)  # favorite_data

    def __init__(self, favorite_data: dict, thumbnail_path: Path = None,
                 thumb_width: int = None, thumb_height: int = None,
                 is_selected: bool = False, parent=None):
        super().__init__(parent)
        self.favorite_data = favorite_data
        self.thumbnail_path = thumbnail_path
        self._is_selected = is_selected

        # 동적 크기 설정 (기본값 사용 가능)
        self.thumb_width = thumb_width or FAVORITE_THUMB_WIDTH
        self.thumb_height = thumb_height or FAVORITE_THUMB_HEIGHT

        # 2줄 라벨을 위해 높이 추가
        self.setFixedSize(self.thumb_width + 10, self.thumb_height + 50)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_style()
        self._init_ui()

    def _update_style(self):
        """선택 상태에 따른 스타일 업데이트"""
        if self._is_selected:
            self.setStyleSheet(f"""
                QFrame {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    border: 2px solid {DARK_COLORS['success']};
                    border-radius: 6px;
                }}
                QFrame:hover {{
                    border-color: {DARK_COLORS['success']};
                    background-color: {DARK_COLORS['bg_hover']};
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
                    border-color: {DARK_COLORS['accent_blue']};
                    background-color: {DARK_COLORS['bg_secondary']};
                }}
            """)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(2)

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
            self.thumb_label.setText("📷")
            self.thumb_label.setStyleSheet(f"""
                QLabel {{
                    background-color: {DARK_COLORS['bg_primary']};
                    border-radius: 4px;
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(24)}px;
                }}
            """)

        layout.addWidget(self.thumb_label)

        # 1줄: 이름 라벨
        name = self.favorite_data.get("name", "Unknown")
        if len(name) > 12:
            name = name[:10] + "..."
        name_label = QLabel(name)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setMaximumHeight(18)
        name_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(12)}px;
                background-color: transparent;
                border: none;
            }}
        """)
        layout.addWidget(name_label)

        # 2줄: Style Aware + Fidelity 정보
        style_aware = self.favorite_data.get("style_aware", False)
        fidelity = self.favorite_data.get("fidelity", 1.0)

        info_layout = QHBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(4)

        if style_aware:
            style_label = QLabel("Style")
            style_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['warning']};
                    font-size: {get_scaled_font_size(10)}px;
                    font-weight: bold;
                    background-color: transparent;
                    border: none;
                }}
            """)
            info_layout.addWidget(style_label)

        fidelity_label = QLabel(f"F:{fidelity:.2f}")
        fidelity_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(10)}px;
                background-color: transparent;
                border: none;
            }}
        """)
        info_layout.addWidget(fidelity_label)

        # 메타데이터 없음 표시
        has_metadata = self.favorite_data.get("has_metadata", False)
        if not has_metadata:
            no_meta_label = QLabel("No metadata")
            no_meta_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_secondary']};
                    font-size: {get_scaled_font_size(10)}px;
                    background-color: transparent;
                    border: none;
                }}
            """)
            info_layout.addWidget(no_meta_label)

        info_layout.addStretch()

        info_widget = QWidget()
        info_widget.setLayout(info_layout)
        info_widget.setMaximumHeight(16)
        layout.addWidget(info_widget)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.favorite_data)
        super().mousePressEvent(event)


class CharRefTabMixin:
    """캐릭터 레퍼런스 탭 Mixin - RemoteWindow와 함께 상속

    필요한 속성 (RemoteWindow에서 정의):
    - self.character_ref_module: 캐릭터 레퍼런스 모듈 참조
    - self.character_module: 캐릭터 모듈 참조
    - self._show_warning(title, message): 경고 메시지 표시
    - self._show_info(title, message): 정보 메시지 표시
    - self._show_question(title, message): 질문 다이얼로그
    - self._get_text_input(title, prompt): 텍스트 입력 다이얼로그
    - self._get_item_input(title, prompt, items): 아이템 선택 다이얼로그
    """

    def _init_char_ref_data(self):
        """캐릭터 레퍼런스 데이터 초기화 - RemoteWindow.__init__에서 호출"""
        # 캐릭터 레퍼런스 탭 데이터
        self.char_ref_favorites = []
        self.char_ref_folders = ["기본"]
        self.char_ref_current_folder = "기본"
        self.char_ref_auto_assign_c1 = True

        # 즐겨찾기 로드
        self._load_char_ref_favorites()
        self._load_char_ref_folders()

    def _create_char_ref_subtab(self, parent_tabs: QTabWidget):
        """캐릭터 레퍼런스 서브탭 - Storage 즐겨찾기 시스템"""
        ref_widget = QWidget()
        ref_layout = QVBoxLayout(ref_widget)
        ref_layout.setContentsMargins(8, 8, 8, 8)
        ref_layout.setSpacing(8)

        if not self.character_ref_module:
            placeholder = QLabel("레퍼런스 모듈을 찾을 수 없습니다.")
            placeholder.setStyleSheet(f"color: {DARK_COLORS['text_disabled']};")
            ref_layout.addWidget(placeholder)
            parent_tabs.addTab(ref_widget, "📸 레퍼런스")
            return

        # === 상단 섹션: 현재 레퍼런스 제어 ===
        top_section = QFrame()
        top_section.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 8px;
            }}
        """)
        top_layout = QHBoxLayout(top_section)
        top_layout.setContentsMargins(10, 10, 10, 10)
        top_layout.setSpacing(12)

        # 왼쪽: 썸네일 영역
        self.char_ref_current_thumb = QLabel()
        self.char_ref_current_thumb.setFixedSize(PREVIEW_THUMB_WIDTH, PREVIEW_THUMB_HEIGHT)
        self.char_ref_current_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.char_ref_current_thumb.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 2px dashed {DARK_COLORS['border']};
                border-radius: 6px;
                color: {DARK_COLORS['text_disabled']};
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)
        self.char_ref_current_thumb.setText("썸네일\n없음")
        top_layout.addWidget(self.char_ref_current_thumb)

        # 오른쪽: 컨트롤 영역 (세로 배치)
        right_section = QVBoxLayout()
        right_section.setSpacing(6)

        # 1) "캐릭터 레퍼런스" 라벨
        ref_label = QLabel("캐릭터 레퍼런스")
        ref_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-weight: bold;
                font-size: {get_scaled_font_size(15)}px;
            }}
        """)
        right_section.addWidget(ref_label)

        # 2) [Storage 아이템 콤보박스][관리] 가로 배치
        combo_row = QHBoxLayout()
        combo_row.setSpacing(6)

        self.char_ref_storage_combo = QComboBox()
        self.char_ref_storage_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.char_ref_storage_combo.setMinimumWidth(150)
        self._sync_char_ref_storage_combo()
        self.char_ref_storage_combo.currentTextChanged.connect(self._on_char_ref_storage_changed)
        combo_row.addWidget(self.char_ref_storage_combo, 1)

        self.char_ref_manage_btn = QPushButton("📂 관리")
        self.char_ref_manage_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.char_ref_manage_btn.setFixedWidth(100)
        self.char_ref_manage_btn.clicked.connect(self._open_char_ref_storage_folder)
        combo_row.addWidget(self.char_ref_manage_btn)

        right_section.addLayout(combo_row)

        # 3) Upload Image / From Clipboard 버튼 (가로 배치)
        upload_row = QHBoxLayout()
        upload_row.setSpacing(6)

        self.char_ref_upload_btn = QPushButton("📁 직접 업로드")
        self.char_ref_upload_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.char_ref_upload_btn.clicked.connect(self._on_char_ref_upload_image)
        upload_row.addWidget(self.char_ref_upload_btn)

        self.char_ref_clipboard_btn = QPushButton("📋클립보드 붙이기")
        self.char_ref_clipboard_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px {get_scaled_size(12)}px;
                font-size: {get_scaled_font_size(16)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        self.char_ref_clipboard_btn.clicked.connect(self._on_char_ref_clipboard_image)
        upload_row.addWidget(self.char_ref_clipboard_btn)

        self.char_ref_edit_meta_btn = QPushButton("📝메타데이터")
        self.char_ref_edit_meta_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.char_ref_edit_meta_btn.clicked.connect(self._on_char_ref_edit_metadata)
        upload_row.addWidget(self.char_ref_edit_meta_btn)

        right_section.addLayout(upload_row)

        # 4) Style Aware 체크박스 + Fidelity 슬라이더 (한 줄, 상하 마진 추가)
        style_fidelity_container = QWidget()
        style_fidelity_container.setContentsMargins(0, 6, 0, 6)
        style_fidelity_row = QHBoxLayout(style_fidelity_container)
        style_fidelity_row.setContentsMargins(0, 0, 0, 0)
        style_fidelity_row.setSpacing(8)

        self.char_ref_style_aware_check = QCheckBox("Style Aware")
        self.char_ref_style_aware_check.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.char_ref_style_aware_check.setChecked(True)
        self.char_ref_style_aware_check.toggled.connect(self._on_char_ref_style_aware_changed)
        style_fidelity_row.addWidget(self.char_ref_style_aware_check)

        fidelity_label = QLabel("Fidelity:")
        fidelity_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(15)}px;")
        style_fidelity_row.addWidget(fidelity_label)

        self.char_ref_fidelity_slider = QSlider(Qt.Orientation.Horizontal)
        self.char_ref_fidelity_slider.setMinimum(0)
        self.char_ref_fidelity_slider.setMaximum(20)
        self.char_ref_fidelity_slider.setValue(20)  # 1.0
        self.char_ref_fidelity_slider.setFixedWidth(160)
        self.char_ref_fidelity_slider.setFixedHeight(20)
        self.char_ref_fidelity_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                border: 1px solid {DARK_COLORS['border']};
                height: 8px;
                background: {DARK_COLORS['bg_primary']};
                border-radius: 4px;
            }}
            QSlider::handle:horizontal {{
                background: {DARK_COLORS['accent_blue']};
                border: 1px solid {DARK_COLORS['accent_blue']};
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }}
            QSlider::handle:horizontal:hover {{
                background: {DARK_COLORS['accent_blue_hover']};
            }}
            QSlider::sub-page:horizontal {{
                background: {DARK_COLORS['accent_blue']};
                border-radius: 4px;
            }}
        """)
        self.char_ref_fidelity_slider.valueChanged.connect(self._on_char_ref_fidelity_changed)
        style_fidelity_row.addWidget(self.char_ref_fidelity_slider)

        self.char_ref_fidelity_value = QLabel("1.00")
        self.char_ref_fidelity_value.setStyleSheet(f"""
            color: {DARK_COLORS['text_primary']};
            font-size: {get_scaled_font_size(15)}px;
            font-weight: bold;
            min-width: 40px;
        """)
        style_fidelity_row.addWidget(self.char_ref_fidelity_value)

        style_fidelity_row.addStretch()
        right_section.addWidget(style_fidelity_container)

        # 5) 즐겨찾기에 등록 버튼
        self.char_ref_favorite_btn = QPushButton("⭐ 즐겨찾기에 등록")
        self.char_ref_favorite_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.char_ref_favorite_btn.clicked.connect(self._on_char_ref_toggle_favorite)
        right_section.addWidget(self.char_ref_favorite_btn)

        right_section.addStretch()
        top_layout.addLayout(right_section, 1)
        ref_layout.addWidget(top_section)

        # === 중간 섹션: C1 자동 할당 체크박스 + 폴더 선택 ===
        middle_section = QFrame()
        middle_section.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 6px;
            }}
        """)
        middle_layout = QVBoxLayout(middle_section)
        middle_layout.setContentsMargins(10, 8, 10, 8)
        middle_layout.setSpacing(6)

        # C1 자동 할당 체크박스 + 캐릭터 레퍼런스 해제 버튼 행
        c1_row = QHBoxLayout()
        c1_row.setSpacing(10)

        self.char_ref_auto_c1_check = QCheckBox("C1 캐릭터 프롬프트에 메타데이터 자동 할당")
        self.char_ref_auto_c1_check.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.char_ref_auto_c1_check.setChecked(self.char_ref_auto_assign_c1)
        self.char_ref_auto_c1_check.toggled.connect(self._on_char_ref_auto_c1_changed)
        c1_row.addWidget(self.char_ref_auto_c1_check)

        c1_row.addStretch()

        # 캐릭터 레퍼런스 해제 버튼
        self.char_ref_clear_btn = QPushButton("캐릭터 레퍼런스 해제")
        self.char_ref_clear_btn.setFixedWidth(160)
        self.char_ref_clear_btn.clicked.connect(self._on_char_ref_clear_all)
        self._update_char_ref_clear_btn_state()  # 초기 상태 설정
        c1_row.addWidget(self.char_ref_clear_btn)

        middle_layout.addLayout(c1_row)

        # 폴더 선택 행
        folder_row = QHBoxLayout()
        folder_row.setSpacing(6)

        folder_label = QLabel("즐겨찾기 폴더:")
        folder_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(12)}px;")
        folder_row.addWidget(folder_label)

        self.char_ref_folder_combo = QComboBox()
        self.char_ref_folder_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.char_ref_folder_combo.setMinimumWidth(100)
        for folder in self.char_ref_folders:
            self.char_ref_folder_combo.addItem(folder)
        self.char_ref_folder_combo.setCurrentText(self.char_ref_current_folder)
        self.char_ref_folder_combo.currentTextChanged.connect(self._on_char_ref_folder_changed)
        folder_row.addWidget(self.char_ref_folder_combo, 1)

        self.char_ref_add_folder_btn = QPushButton("➕ 추가")
        self.char_ref_add_folder_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.char_ref_add_folder_btn.setFixedWidth(100)
        self.char_ref_add_folder_btn.clicked.connect(self._on_char_ref_add_folder)
        folder_row.addWidget(self.char_ref_add_folder_btn)

        self.char_ref_manage_folder_btn = QPushButton("📂 관리")
        self.char_ref_manage_folder_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.char_ref_manage_folder_btn.setFixedWidth(100)
        self.char_ref_manage_folder_btn.clicked.connect(self._on_char_ref_manage_folders)
        folder_row.addWidget(self.char_ref_manage_folder_btn)

        middle_layout.addLayout(folder_row)
        ref_layout.addWidget(middle_section)

        # === 하단 섹션: 즐겨찾기 그리드 ===
        bottom_section = QFrame()
        bottom_section.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 8px;
            }}
        """)
        bottom_layout = QVBoxLayout(bottom_section)
        bottom_layout.setContentsMargins(8, 8, 8, 8)

        # 스크롤 영역
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: transparent;
            }}
        """)

        # 그리드 컨테이너
        self.char_ref_favorites_grid_widget = QWidget()
        self.char_ref_favorites_grid_layout = QGridLayout(self.char_ref_favorites_grid_widget)
        self.char_ref_favorites_grid_layout.setSpacing(10)
        self.char_ref_favorites_grid_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area.setWidget(self.char_ref_favorites_grid_widget)
        bottom_layout.addWidget(scroll_area, 1)

        ref_layout.addWidget(bottom_section, 1)

        parent_tabs.addTab(ref_widget, "📸 레퍼런스")

        # 초기 UI 업데이트
        self._update_char_ref_current_ui()
        self._update_char_ref_favorites_grid()

    # === 캐릭터 레퍼런스 헬퍼 메서드들 ===

    def _sync_char_ref_storage_combo(self):
        """Storage 아이템 콤보박스 동기화"""
        self.char_ref_storage_combo.blockSignals(True)
        self.char_ref_storage_combo.clear()

        # Storage 이미지 목록 가져오기
        images_folder = Path("save/character_reference/images")
        if images_folder.exists():
            image_files = []
            for ext in ['*.png', '*.jpg', '*.jpeg', '*.webp']:
                image_files.extend(images_folder.glob(ext))

            # 수정 시간 기준 내림차순 정렬
            for img_file in sorted(image_files, key=lambda x: x.stat().st_mtime, reverse=True):
                file_hash = img_file.stem
                # 메타데이터에서 이름 가져오기
                name = self._get_char_ref_name_from_metadata(file_hash)
                display_name = name if name else file_hash[:12]
                self.char_ref_storage_combo.addItem(display_name, file_hash)

        # 현재 활성화된 레퍼런스 선택
        if self.character_ref_module and hasattr(self.character_ref_module, 'character_frames'):
            for frame in self.character_ref_module.character_frames:
                if hasattr(frame, 'is_enabled') and frame.is_enabled:
                    file_hash = getattr(frame, 'file_hash', '')
                    for i in range(self.char_ref_storage_combo.count()):
                        if self.char_ref_storage_combo.itemData(i) == file_hash:
                            self.char_ref_storage_combo.setCurrentIndex(i)
                            break
                    break

        self.char_ref_storage_combo.blockSignals(False)

    def _get_char_ref_name_from_metadata(self, file_hash: str) -> str:
        """메타데이터에서 캐릭터 이름 가져오기"""
        metadata_path = Path(f"save/character_reference/metadata/{file_hash}.json")
        if metadata_path.exists():
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get("character_name", "")
            except:
                pass
        return ""

    def _get_char_ref_metadata(self, file_hash: str) -> dict:
        """메타데이터 전체 가져오기"""
        metadata_path = Path(f"save/character_reference/metadata/{file_hash}.json")
        if metadata_path.exists():
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {}

    def _update_char_ref_current_ui(self):
        """현재 선택된 레퍼런스 UI 업데이트 - 콤보박스 선택 기준"""
        # 콤보박스에서 현재 선택된 아이템의 file_hash 가져오기
        idx = self.char_ref_storage_combo.currentIndex()
        if idx >= 0:
            file_hash = self.char_ref_storage_combo.itemData(idx)
        else:
            file_hash = None

        # 모듈에 활성 프레임이 있고 해시가 콤보박스와 일치하는지 확인
        active_frame = None
        style_aware = self.char_ref_style_aware_check.isChecked()  # 현재 UI 값 유지
        fidelity = self.char_ref_fidelity_slider.value() / 20.0

        if self.character_ref_module and hasattr(self.character_ref_module, 'character_frames'):
            for frame in self.character_ref_module.character_frames:
                if hasattr(frame, 'is_enabled') and frame.is_enabled:
                    frame_hash = getattr(frame, 'file_hash', '')
                    if frame_hash == file_hash:
                        active_frame = frame
                        # 활성 프레임의 값으로 동기화
                        style_aware = getattr(frame, 'style_aware', True)
                        fidelity = getattr(frame, 'fidelity', 1.0)
                    break

        if file_hash:
            # 썸네일 업데이트
            image_path = Path(f"save/character_reference/images/{file_hash}.png")
            if not image_path.exists():
                # 다른 확장자 시도
                for ext in ['.jpg', '.jpeg', '.webp']:
                    alt_path = image_path.with_suffix(ext)
                    if alt_path.exists():
                        image_path = alt_path
                        break

            if image_path.exists():
                pixmap = QPixmap(str(image_path))
                scaled = pixmap.scaled(
                    PREVIEW_THUMB_WIDTH, PREVIEW_THUMB_HEIGHT,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.char_ref_current_thumb.setPixmap(scaled)
                border_color = DARK_COLORS['accent_blue'] if active_frame else DARK_COLORS['border']
                self.char_ref_current_thumb.setStyleSheet(f"""
                    QLabel {{
                        background-color: {DARK_COLORS['bg_primary']};
                        border: 2px solid {border_color};
                        border-radius: 6px;
                    }}
                """)
            else:
                self.char_ref_current_thumb.setText("썸네일\n없음")
                self.char_ref_current_thumb.setStyleSheet(f"""
                    QLabel {{
                        background-color: {DARK_COLORS['bg_primary']};
                        border: 2px dashed {DARK_COLORS['border']};
                        border-radius: 6px;
                        color: {DARK_COLORS['text_disabled']};
                        font-size: {get_scaled_font_size(12)}px;
                    }}
                """)

            # Style Aware, Fidelity 동기화
            self.char_ref_style_aware_check.blockSignals(True)
            self.char_ref_style_aware_check.setChecked(style_aware)
            self.char_ref_style_aware_check.blockSignals(False)

            self.char_ref_fidelity_slider.blockSignals(True)
            self.char_ref_fidelity_slider.setValue(int(fidelity * 20))
            self.char_ref_fidelity_value.setText(f"{fidelity:.2f}")
            self.char_ref_fidelity_slider.blockSignals(False)

            # 즐겨찾기 버튼 상태 업데이트
            is_favorite = any(
                f.get("file_hash") == file_hash and f.get("folder") == self.char_ref_current_folder
                for f in self.char_ref_favorites
            )
            if is_favorite:
                self.char_ref_favorite_btn.setText("💔 즐겨찾기에서 제거")
                self.char_ref_favorite_btn.setStyleSheet(DARK_STYLES['secondary_button'])
            else:
                self.char_ref_favorite_btn.setText("⭐ 즐겨찾기에 등록")
                self.char_ref_favorite_btn.setStyleSheet(DARK_STYLES['primary_button'])
        else:
            self.char_ref_current_thumb.setText("선택된\n레퍼런스\n없음")
            self.char_ref_current_thumb.setStyleSheet(f"""
                QLabel {{
                    background-color: {DARK_COLORS['bg_primary']};
                    border: 2px dashed {DARK_COLORS['border']};
                    border-radius: 6px;
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(12)}px;
                }}
            """)

        # 캐릭터 레퍼런스 해제 버튼 상태 업데이트
        self._update_char_ref_clear_btn_state()

    def _calculate_char_ref_thumbnail_size(self) -> tuple:
        """현재 UI 크기를 기반으로 썸네일 크기 계산 (3열 기준)"""
        available_width = self.char_ref_favorites_grid_widget.width()
        if available_width < 100:
            available_width = 450

        cols = 3
        spacing = 10
        item_padding = 10
        item_width = (available_width - (cols - 1) * spacing) // cols - item_padding
        item_width = max(80, min(180, item_width))
        item_height = int(item_width / THUMB_ASPECT_RATIO)

        return item_width, item_height

    def _update_char_ref_favorites_grid(self):
        """캐릭터 레퍼런스 즐겨찾기 그리드 업데이트"""
        # 기존 위젯 제거
        while self.char_ref_favorites_grid_layout.count():
            item = self.char_ref_favorites_grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 현재 폴더의 즐겨찾기만 필터링
        folder_favorites = [
            f for f in self.char_ref_favorites
            if f.get("folder", "기본") == self.char_ref_current_folder
        ]

        if not folder_favorites:
            empty_label = QLabel("즐겨찾기가 없습니다.\n캐릭터 레퍼런스를 추가하고\n⭐ 버튼을 눌러 등록하세요.")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(12)}px;
                    padding: 40px;
                }}
            """)
            self.char_ref_favorites_grid_layout.addWidget(empty_label, 0, 0, 1, 3)
            return

        # 동적 썸네일 크기 계산
        thumb_width, thumb_height = self._calculate_char_ref_thumbnail_size()

        # 현재 선택된 file_hash 가져오기 (콤보박스 기준)
        current_idx = self.char_ref_storage_combo.currentIndex()
        current_file_hash = self.char_ref_storage_combo.itemData(current_idx) if current_idx >= 0 else None

        # 그리드에 아이템 추가 (3열, 좌측 정렬)
        cols = 3
        for idx, fav in enumerate(folder_favorites):
            file_hash = fav.get("file_hash", "")
            thumb_path = Path(f"save/character_reference/images/{file_hash}.png")
            if not thumb_path.exists():
                for ext in ['.jpg', '.jpeg', '.webp']:
                    alt_path = thumb_path.with_suffix(ext)
                    if alt_path.exists():
                        thumb_path = alt_path
                        break

            # 현재 선택된 아이템인지 확인
            is_selected = (file_hash == current_file_hash)

            item_widget = CharRefFavoriteItemWidget(
                fav, thumb_path,
                thumb_width=thumb_width,
                thumb_height=thumb_height,
                is_selected=is_selected
            )
            item_widget.clicked.connect(self._on_char_ref_favorite_clicked)

            row = idx // cols
            col = idx % cols
            self.char_ref_favorites_grid_layout.addWidget(
                item_widget, row, col,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
            )

    def _on_char_ref_storage_changed(self, text: str):
        """Storage 콤보박스 변경 시 - UI 업데이트만 수행 (모듈에 프레임 추가하지 않음)"""
        # 썸네일 및 UI 업데이트만 수행
        self._update_char_ref_current_ui()

    def _clear_char_ref_frames(self):
        """캐릭터 레퍼런스 모듈의 모든 프레임 제거"""
        if not self.character_ref_module:
            return

        if hasattr(self.character_ref_module, 'character_frames'):
            # 프레임 리스트 복사 후 순회 (순회 중 삭제 방지)
            frames_to_remove = list(self.character_ref_module.character_frames)
            for frame in frames_to_remove:
                if hasattr(self.character_ref_module, '_remove_frame'):
                    self.character_ref_module._remove_frame(frame)

    def _apply_char_ref_from_storage(self, file_hash: str, style_aware: bool = None, fidelity: float = None,
                                      clear_existing: bool = True, auto_assign_c1: bool = False):
        """Storage에서 캐릭터 레퍼런스 적용

        Args:
            file_hash: 이미지 해시
            style_aware: Style Aware 설정 (None이면 기본값 True)
            fidelity: Fidelity 값 (None이면 기본값 1.0)
            clear_existing: 기존 프레임들 삭제 여부
            auto_assign_c1: C1 캐릭터 프롬프트에 메타데이터 자동 할당 여부
        """
        if not self.character_ref_module:
            return

        # 이미지 경로 찾기
        image_path = None
        for ext in ['.png', '.jpg', '.jpeg', '.webp']:
            path = Path(f"save/character_reference/images/{file_hash}{ext}")
            if path.exists():
                image_path = path
                break

        if not image_path:
            self._show_warning("오류", f"이미지를 찾을 수 없습니다: {file_hash}")
            return

        # 기존 프레임들 제거
        if clear_existing:
            self._clear_char_ref_frames()

        # 새 프레임 추가 및 활성화
        if hasattr(self.character_ref_module, '_add_character_frame'):
            frame = self.character_ref_module._add_character_frame(str(image_path))
            if frame:
                frame.enable_check.setChecked(True)

                # Style Aware 설정 (기본값 True)
                if hasattr(frame, 'style_aware_check'):
                    frame.style_aware_check.setChecked(style_aware if style_aware is not None else True)

                # Fidelity 설정 (기본값 1.0)
                if hasattr(frame, 'fidelity_slider'):
                    fidelity_value = fidelity if fidelity is not None else 1.0
                    frame.fidelity_slider.setValue(int(fidelity_value * 20))

        # C1 자동 할당
        if auto_assign_c1:
            self._assign_c1_from_metadata(file_hash)

        # UI 업데이트
        QTimer.singleShot(100, self._update_char_ref_current_ui)

    def _assign_c1_from_metadata(self, file_hash: str):
        """메타데이터에서 C1 캐릭터 프롬프트 할당"""
        metadata_path = Path(f"save/character_reference/metadata/{file_hash}.json")
        if not metadata_path.exists():
            return

        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            character_prompt = metadata.get("character_prompt", "").strip()
            character_uc = metadata.get("character_uc", "").strip()

            if not character_prompt:
                return

            # CharacterModule에서 C1 할당
            if self.character_module and hasattr(self.character_module, 'assign_c1'):
                self.character_module.assign_c1(character_prompt, character_uc)
                print(f"✅ C1 자동 할당 완료: {metadata.get('character_name', file_hash[:8])}")

            # RemoteWindow의 인원 수를 1명으로 설정
            if hasattr(self, 'char_prompt_person_radios') and self.char_prompt_person_radios:
                self.char_prompt_person_radios[0].setChecked(True)  # 1명 라디오 선택
                self.char_prompt_person_count = 1
                self._on_char_prompt_person_changed(1)  # UI 업데이트

            # RemoteWindow의 슬롯 프레임 UI도 업데이트 (C1 = index 0)
            if hasattr(self, 'char_prompt_slot_edits') and len(self.char_prompt_slot_edits) > 0:
                self.char_prompt_slot_edits[0].setText(character_prompt)

        except Exception as e:
            print(f"⚠️ C1 자동 할당 실패: {e}")

    def _on_char_ref_upload_image(self):
        """이미지 업로드 및 임시 프리셋 생성"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "이미지 선택",
            "",
            "Image Files (*.png *.jpg *.jpeg *.webp *.bmp *.gif)"
        )

        if file_path and self.character_ref_module:
            # 기존 프레임 모두 제거
            self._clear_char_ref_frames()

            if hasattr(self.character_ref_module, '_add_character_frame'):
                frame = self.character_ref_module._add_character_frame(file_path)
                if frame:
                    frame.enable_check.setChecked(True)

                    # Style Aware, Fidelity 설정 (UI 값 적용)
                    if hasattr(frame, 'style_aware_check'):
                        frame.style_aware_check.setChecked(self.char_ref_style_aware_check.isChecked())
                    if hasattr(frame, 'fidelity_slider'):
                        frame.fidelity_slider.setValue(self.char_ref_fidelity_slider.value())

                    # 새 file_hash 가져오기
                    new_file_hash = getattr(frame, 'file_hash', None)

                    # Storage 콤보박스 동기화 후 해당 아이템 선택
                    self._sync_char_ref_storage_combo()

                    if new_file_hash:
                        self._select_char_ref_in_combo_by_hash(new_file_hash)

                    QTimer.singleShot(100, self._update_char_ref_current_ui)
                    print(f"✅ 이미지 업로드: {new_file_hash[:8] if new_file_hash else 'unknown'}")

    def _on_char_ref_clipboard_image(self):
        """클립보드에서 이미지 가져오기 및 임시 프리셋 생성"""
        if not self.character_ref_module:
            return

        # 클립보드 확인
        clipboard = QApplication.clipboard()
        png_bytes = clipboard_png_bytes(clipboard)

        if not png_bytes:
            self._show_warning("오류", "클립보드에 이미지가 없습니다.\n이미지를 복사한 후 다시 시도하세요.")
            return

        # 기존 프레임 모두 제거
        self._clear_char_ref_frames()

        # 클립보드 이미지를 임시 파일로 저장
        import time
        temp_folder = Path("save/character_reference/temp")
        temp_folder.mkdir(parents=True, exist_ok=True)
        temp_file = temp_folder / f"clipboard_{int(time.time())}.png"
        temp_file.write_bytes(png_bytes)

        # 프레임 추가
        if hasattr(self.character_ref_module, '_add_character_frame'):
            frame = self.character_ref_module._add_character_frame(str(temp_file))
            if frame:
                frame.enable_check.setChecked(True)

                # Style Aware, Fidelity 설정 (UI 값 적용)
                if hasattr(frame, 'style_aware_check'):
                    frame.style_aware_check.setChecked(self.char_ref_style_aware_check.isChecked())
                if hasattr(frame, 'fidelity_slider'):
                    frame.fidelity_slider.setValue(self.char_ref_fidelity_slider.value())

                # 새 file_hash 가져오기
                new_file_hash = getattr(frame, 'file_hash', None)

                # Storage 콤보박스 동기화 후 해당 아이템 선택
                self._sync_char_ref_storage_combo()

                if new_file_hash:
                    self._select_char_ref_in_combo_by_hash(new_file_hash)

                QTimer.singleShot(100, self._update_char_ref_current_ui)
                print(f"✅ 클립보드 이미지 추가: {new_file_hash[:8] if new_file_hash else 'unknown'}")

    def _select_latest_char_ref_in_combo(self):
        """가장 최근 추가된 캐릭터 레퍼런스를 콤보박스에서 선택"""
        if self.char_ref_storage_combo.count() > 0:
            # Storage는 최신순 정렬이므로 첫 번째 아이템 선택
            self.char_ref_storage_combo.setCurrentIndex(0)

    def _select_char_ref_in_combo_by_hash(self, file_hash: str):
        """해시값으로 콤보박스에서 해당 아이템 선택"""
        if not file_hash:
            return False

        for i in range(self.char_ref_storage_combo.count()):
            if self.char_ref_storage_combo.itemData(i) == file_hash:
                self.char_ref_storage_combo.blockSignals(True)
                self.char_ref_storage_combo.setCurrentIndex(i)
                self.char_ref_storage_combo.blockSignals(False)
                return True

        return False

    def _on_char_ref_edit_metadata(self):
        """메타데이터 편집 - Storage 콤보박스에서 선택한 아이템 기준"""
        # 콤보박스에서 선택한 아이템의 file_hash 가져오기
        idx = self.char_ref_storage_combo.currentIndex()
        if idx < 0:
            self._show_info("알림", "먼저 캐릭터 레퍼런스를 선택하세요.")
            return

        file_hash = self.char_ref_storage_combo.itemData(idx)
        file_name = self.char_ref_storage_combo.currentText()

        if not file_hash:
            self._show_info("알림", "먼저 캐릭터 레퍼런스를 선택하세요.")
            return

        # 메타데이터 편집 다이얼로그 열기
        self._open_metadata_edit_dialog(file_hash, file_name)

    def _open_metadata_edit_dialog(self, file_hash: str, file_name: str):
        """메타데이터 편집 다이얼로그 열기 (Storage와 동일한 UI)"""
        # 기존 메타데이터 로드
        metadata = self._get_char_ref_metadata(file_hash) or {}

        # 다이얼로그 생성
        dialog = QDialog(self)
        dialog.setWindowTitle(f"📝 메타데이터 편집 - {file_name}")
        dialog.setMinimumSize(500, 400)
        dialog.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(15)}px;
            }}
            QLineEdit {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 6px;
                font-size: {get_scaled_font_size(15)}px;
            }}
            QTextEdit {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 6px;
                font-size: {get_scaled_font_size(16)}px;
            }}
            QLineEdit:focus, QTextEdit:focus {{
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 8px 16px;
                font-size: {get_scaled_font_size(15)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
        """)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Character Name
        name_label = QLabel("Character Name:")
        layout.addWidget(name_label)

        name_edit = QLineEdit()
        name_edit.setText(metadata.get("character_name", ""))
        name_edit.setPlaceholderText("캐릭터 이름을 입력하세요")
        layout.addWidget(name_edit)

        # Character Prompt
        prompt_label = QLabel("Character Prompt:")
        layout.addWidget(prompt_label)

        prompt_edit = QTextEdit()
        prompt_edit.setPlainText(metadata.get("character_prompt", ""))
        prompt_edit.setPlaceholderText("캐릭터 프롬프트를 입력하세요")
        prompt_edit.setAcceptRichText(False)
        prompt_edit.setMinimumHeight(100)
        layout.addWidget(prompt_edit)

        # Undesired Content (Negative)
        uc_label = QLabel("Undesired Content (Negative):")
        layout.addWidget(uc_label)

        uc_edit = QTextEdit()
        uc_edit.setPlainText(metadata.get("character_uc", ""))
        uc_edit.setPlaceholderText("네거티브 프롬프트를 입력하세요")
        uc_edit.setAcceptRichText(False)
        uc_edit.setMinimumHeight(80)
        layout.addWidget(uc_edit)

        # 버튼 영역
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        save_btn = QPushButton("💾 저장")
        cancel_btn = QPushButton("취소")

        def on_save():
            updated_metadata = {
                "character_name": name_edit.text().strip(),
                "character_prompt": prompt_edit.toPlainText().strip(),
                "character_uc": uc_edit.toPlainText().strip(),
                "file_name": file_name,
                "file_hash": file_hash
            }
            self._save_char_ref_metadata(file_hash, updated_metadata)

            # 콤보박스 텍스트 업데이트 (현재 선택 해시 유지)
            self._sync_char_ref_storage_combo()
            self._select_char_ref_in_combo_by_hash(file_hash)

            # 즐겨찾기 그리드 업데이트
            self._update_char_ref_favorites_grid()

            # 썸네일 영역 UI 업데이트
            self._update_char_ref_current_ui()

            dialog.accept()
            print(f"✅ 메타데이터 저장: {updated_metadata.get('character_name', file_hash[:8])}")

        save_btn.clicked.connect(on_save)
        cancel_btn.clicked.connect(dialog.reject)

        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

        # TODO(web-dialog): 원래 char_ref 메타데이터 편집 dialog.exec() — Web Shell 패널로 재구현 필요.
        print("[Dialog/SKIPPED] char_ref 메타데이터 dialog 차단 — Web Shell 재구현 예정")
        dialog.deleteLater()

    def _save_char_ref_metadata(self, file_hash: str, metadata: dict):
        """캐릭터 레퍼런스 메타데이터 저장"""
        metadata_dir = Path("save/character_reference/metadata")
        metadata_dir.mkdir(parents=True, exist_ok=True)

        metadata_path = metadata_dir / f"{file_hash}.json"
        try:
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 메타데이터 저장 실패: {e}")

    def _on_char_ref_style_aware_changed(self, checked: bool):
        """Style Aware 체크박스 변경"""
        if not self.character_ref_module:
            return

        if hasattr(self.character_ref_module, 'character_frames'):
            for frame in self.character_ref_module.character_frames:
                if hasattr(frame, 'is_enabled') and frame.is_enabled:
                    if hasattr(frame, 'style_aware_check'):
                        frame.style_aware_check.setChecked(checked)
                    break

    def _on_char_ref_fidelity_changed(self, value: int):
        """Fidelity 슬라이더 변경"""
        fidelity = value / 20.0
        self.char_ref_fidelity_value.setText(f"{fidelity:.2f}")

        if not self.character_ref_module:
            return

        if hasattr(self.character_ref_module, 'character_frames'):
            for frame in self.character_ref_module.character_frames:
                if hasattr(frame, 'is_enabled') and frame.is_enabled:
                    if hasattr(frame, 'fidelity_slider'):
                        frame.fidelity_slider.setValue(value)
                    break

    def _on_char_ref_toggle_favorite(self):
        """즐겨찾기 등록/제거 토글 - Storage 콤보박스 기준"""
        # Storage 콤보박스에서 선택된 아이템 확인
        idx = self.char_ref_storage_combo.currentIndex()
        if idx < 0:
            self._show_info("알림", "먼저 캐릭터 레퍼런스를 선택하세요.")
            return

        file_hash = self.char_ref_storage_combo.itemData(idx)
        if not file_hash:
            self._show_info("알림", "먼저 캐릭터 레퍼런스를 선택하세요.")
            return

        # UI에서 Style Aware, Fidelity 값 가져오기
        style_aware = self.char_ref_style_aware_check.isChecked()
        fidelity = self.char_ref_fidelity_slider.value() / 20.0

        # 이름 가져오기
        name = self._get_char_ref_name_from_metadata(file_hash)
        if not name:
            name = file_hash[:12]

        # 현재 즐겨찾기 상태 확인
        is_favorite = any(
            f.get("file_hash") == file_hash and f.get("folder") == self.char_ref_current_folder
            for f in self.char_ref_favorites
        )

        if is_favorite:
            # 즐겨찾기 제거
            self.char_ref_favorites = [
                f for f in self.char_ref_favorites
                if not (f.get("file_hash") == file_hash and f.get("folder") == self.char_ref_current_folder)
            ]
            self._save_char_ref_favorites()
            print(f"💔 캐릭터 레퍼런스 즐겨찾기 제거: {name}")
        else:
            # 메타데이터 유무 확인
            metadata = self._get_char_ref_metadata(file_hash)
            has_metadata = bool(metadata and metadata.get("character_prompt", "").strip())

            # 즐겨찾기 등록
            self.char_ref_favorites.append({
                "file_hash": file_hash,
                "name": name,
                "style_aware": style_aware,
                "fidelity": fidelity,
                "folder": self.char_ref_current_folder,
                "has_metadata": has_metadata
            })
            self._save_char_ref_favorites()
            print(f"⭐ 캐릭터 레퍼런스 즐겨찾기 등록: {name}")

        self._update_char_ref_current_ui()
        self._update_char_ref_favorites_grid()

    def _on_char_ref_auto_c1_changed(self, checked: bool):
        """C1 자동 할당 체크박스 변경"""
        self.char_ref_auto_assign_c1 = checked
        self._save_char_ref_folders()

    def _on_char_ref_folder_changed(self, folder: str):
        """즐겨찾기 폴더 변경"""
        self.char_ref_current_folder = folder
        self._save_char_ref_folders()
        self._update_char_ref_favorites_grid()
        self._update_char_ref_current_ui()

    def _on_char_ref_add_folder(self):
        """새 즐겨찾기 폴더 추가"""
        name, ok = self._get_text_input("폴더 추가", "새 폴더 이름:")
        if ok and name:
            name = name.strip()
            if name and name not in self.char_ref_folders:
                self.char_ref_folders.append(name)
                self.char_ref_folder_combo.addItem(name)
                self.char_ref_folder_combo.setCurrentText(name)
                self._save_char_ref_folders()
                print(f"📁 새 폴더 추가: {name}")
            elif name in self.char_ref_folders:
                self._show_warning("알림", f"'{name}' 폴더가 이미 존재합니다.")

    def _on_char_ref_manage_folders(self):
        """즐겨찾기 폴더 관리"""
        # 폴더 목록 표시 및 삭제 기능
        if len(self.char_ref_folders) <= 1:
            self._show_info("알림", "삭제할 수 있는 폴더가 없습니다.\n'기본' 폴더는 삭제할 수 없습니다.")
            return

        folders_to_delete = [f for f in self.char_ref_folders if f != "기본"]
        folder, ok = self._get_item_input("폴더 삭제", "삭제할 폴더 선택:", folders_to_delete)

        if ok and folder:
            if self._show_question(
                "폴더 삭제 확인",
                f"'{folder}' 폴더와 해당 폴더의 즐겨찾기를 삭제하시겠습니까?"
            ):
                # 폴더와 해당 즐겨찾기 삭제
                self.char_ref_folders.remove(folder)
                self.char_ref_favorites = [
                    f for f in self.char_ref_favorites
                    if f.get("folder") != folder
                ]

                # 콤보박스 업데이트
                idx = self.char_ref_folder_combo.findText(folder)
                if idx >= 0:
                    self.char_ref_folder_combo.removeItem(idx)

                # 현재 폴더가 삭제된 폴더면 기본으로 변경
                if self.char_ref_current_folder == folder:
                    self.char_ref_current_folder = "기본"
                    self.char_ref_folder_combo.setCurrentText("기본")

                self._save_char_ref_folders()
                self._save_char_ref_favorites()
                self._update_char_ref_favorites_grid()
                print(f"🗑️ 폴더 삭제: {folder}")

    def _on_char_ref_favorite_clicked(self, favorite_data: dict):
        """즐겨찾기 아이템 클릭 시 캐릭터 레퍼런스 적용 (기존 프레임 clear 후 새로 할당)"""
        file_hash = favorite_data.get("file_hash", "")
        style_aware = favorite_data.get("style_aware", True)
        fidelity = favorite_data.get("fidelity", 1.0)

        if not file_hash:
            return

        # Storage 콤보박스에서 해당 해시 찾아서 선택
        combo_idx = -1
        for i in range(self.char_ref_storage_combo.count()):
            if self.char_ref_storage_combo.itemData(i) == file_hash:
                combo_idx = i
                break

        if combo_idx < 0:
            # Storage에 없는 이미지 (삭제됨)
            self._show_warning("오류", f"원본 이미지를 찾을 수 없습니다.\nStorage에서 삭제되었을 수 있습니다.")
            return

        # 콤보박스 선택 변경 (시그널 일시 차단)
        self.char_ref_storage_combo.blockSignals(True)
        self.char_ref_storage_combo.setCurrentIndex(combo_idx)
        self.char_ref_storage_combo.blockSignals(False)

        # 캐릭터 레퍼런스 적용 (기존 프레임 clear, C1 자동 할당 옵션 적용)
        self._apply_char_ref_from_storage(
            file_hash,
            style_aware=style_aware,
            fidelity=fidelity,
            clear_existing=True,
            auto_assign_c1=self.char_ref_auto_assign_c1
        )

        # Style Aware, Fidelity UI 업데이트
        self.char_ref_style_aware_check.setChecked(style_aware)
        self.char_ref_fidelity_slider.setValue(int(fidelity * 20))

        # 즐겨찾기 그리드 업데이트 (선택 상태 표시)
        self._update_char_ref_favorites_grid()

        print(f"✅ 즐겨찾기 적용: {favorite_data.get('name', file_hash[:8])}")

    def _open_char_ref_storage_folder(self):
        """캐릭터 레퍼런스 Storage 폴더 열기"""
        import subprocess
        import os

        storage_dir = Path("save/character_reference/images")
        if not storage_dir.exists():
            storage_dir.mkdir(parents=True, exist_ok=True)

        if os.name == 'nt':
            subprocess.Popen(['explorer', str(storage_dir.resolve())])
        else:
            subprocess.Popen(['open' if os.uname().sysname == 'Darwin' else 'xdg-open', str(storage_dir.resolve())])

    # === 저장/로드 메서드 ===

    def _load_char_ref_favorites(self):
        """캐릭터 레퍼런스 즐겨찾기 로드"""
        if CHAR_REF_FAVORITES_JSON.exists():
            try:
                with open(CHAR_REF_FAVORITES_JSON, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 기존 호환성: 직접 리스트 또는 {"favorites": [...]} 구조 모두 지원
                    if isinstance(data, list):
                        self.char_ref_favorites = data
                    else:
                        self.char_ref_favorites = data.get("favorites", [])
            except Exception as e:
                print(f"캐릭터 레퍼런스 즐겨찾기 로드 실패: {e}")
                self.char_ref_favorites = []

    def _save_char_ref_favorites(self):
        """캐릭터 레퍼런스 즐겨찾기 저장"""
        try:
            CHAR_REF_FAVORITES_DIR.mkdir(parents=True, exist_ok=True)
            # 기존 호환성: 직접 리스트로 저장
            with open(CHAR_REF_FAVORITES_JSON, 'w', encoding='utf-8') as f:
                json.dump(self.char_ref_favorites, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"캐릭터 레퍼런스 즐겨찾기 저장 실패: {e}")

    def _load_char_ref_folders(self):
        """캐릭터 레퍼런스 폴더 설정 로드"""
        if CHAR_REF_FOLDERS_JSON.exists():
            try:
                with open(CHAR_REF_FOLDERS_JSON, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.char_ref_folders = data.get("folders", ["기본"])
                    self.char_ref_current_folder = data.get("current_folder", "기본")
                    self.char_ref_auto_assign_c1 = data.get("auto_assign_c1", True)
            except Exception as e:
                print(f"캐릭터 레퍼런스 폴더 설정 로드 실패: {e}")
                self.char_ref_folders = ["기본"]
                self.char_ref_current_folder = "기본"
                self.char_ref_auto_assign_c1 = True

    def _save_char_ref_folders(self):
        """캐릭터 레퍼런스 폴더 설정 저장"""
        try:
            CHAR_REF_FAVORITES_DIR.mkdir(parents=True, exist_ok=True)
            with open(CHAR_REF_FOLDERS_JSON, 'w', encoding='utf-8') as f:
                json.dump({
                    "folders": self.char_ref_folders,
                    "current_folder": self.char_ref_current_folder,
                    "auto_assign_c1": self.char_ref_auto_assign_c1
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"캐릭터 레퍼런스 폴더 설정 저장 실패: {e}")

    # === 캐릭터 레퍼런스 해제 ===

    def _has_enabled_char_ref(self) -> bool:
        """캐릭터 레퍼런스 모듈에 Enable된 프레임이 있는지 확인"""
        if not self.character_ref_module:
            return False

        if not hasattr(self.character_ref_module, 'character_frames'):
            return False

        # 프레임이 1개 이상 있으면 Enable 된 것으로 간주
        return len(self.character_ref_module.character_frames) > 0

    def _update_char_ref_clear_btn_state(self):
        """캐릭터 레퍼런스 해제 버튼 상태 업데이트"""
        if not hasattr(self, 'char_ref_clear_btn'):
            return

        has_ref = self._has_enabled_char_ref()

        if has_ref:
            # 활성화 상태 - 밝은 주황색 배경
            self.char_ref_clear_btn.setEnabled(True)
            self.char_ref_clear_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #E67E22;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-size: {get_scaled_font_size(13)}px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: #D35400;
                }}
                QPushButton:pressed {{
                    background-color: #BA4A00;
                }}
            """)
        else:
            # 비활성화 상태 - 진한 회색 배경
            self.char_ref_clear_btn.setEnabled(False)
            self.char_ref_clear_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #4a4a4a;
                    color: #888888;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-size: {get_scaled_font_size(13)}px;
                }}
            """)

    def _on_char_ref_clear_all(self):
        """캐릭터 레퍼런스 모두 해제"""
        if not self._has_enabled_char_ref():
            return

        # 모든 캐릭터 레퍼런스 프레임 제거
        self._clear_char_ref_frames()

        # 버튼 상태 업데이트
        self._update_char_ref_clear_btn_state()

        # UI 업데이트
        self._update_char_ref_current_ui()

        print("✅ 캐릭터 레퍼런스 해제 완료")
