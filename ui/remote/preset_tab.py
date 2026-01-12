# ui/remote/preset_tab.py
"""
프리셋 탭 Mixin - RemoteWindow의 프리셋 탭 관련 기능

포함된 클래스:
- PresetFavoriteItemWidget: 프리셋 즐겨찾기 아이템 위젯
- PresetTabMixin: 프리셋 탭 관련 메서드 모음
"""

import json
import subprocess
import os
from pathlib import Path
from PIL import Image

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTabWidget, QLabel, QComboBox, QTextEdit, QPushButton,
    QScrollArea, QFrame, QApplication, QSizePolicy, QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap

from ui.theme import DARK_COLORS, DARK_STYLES
from ui.scaling_manager import get_scaled_font_size, get_scaled_size


# === 상수 정의 ===
PRESET_FAVORITES_DIR = Path("save/presets/favorites")
PRESET_FAVORITES_JSON = Path("save/presets/favorites.json")

# 썸네일 크기 (char_ref_tab.py와 동일한 값 사용)
PRESET_THUMB_WIDTH = 120
PRESET_THUMB_HEIGHT = 167
PRESET_PREVIEW_WIDTH = 140
PRESET_PREVIEW_HEIGHT = 195
PRESET_THUMB_ASPECT_RATIO = 368 / 512  # NAI 기본 이미지 비율


class PresetFavoriteItemWidget(QFrame):
    """즐겨찾기 프리셋 아이템 위젯 (동적 크기 지원)"""

    clicked = pyqtSignal(str)  # preset_name

    def __init__(self, preset_name: str, thumbnail_path: Path = None,
                 thumb_width: int = None, thumb_height: int = None, parent=None):
        super().__init__(parent)
        self.preset_name = preset_name
        self.thumbnail_path = thumbnail_path

        # 동적 크기 설정 (기본값 사용 가능)
        self.thumb_width = thumb_width or PRESET_THUMB_WIDTH
        self.thumb_height = thumb_height or PRESET_THUMB_HEIGHT

        self.setFixedSize(self.thumb_width + 10, self.thumb_height + 35)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
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

        self._init_ui()

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

        # 프리셋 이름 (폰트 크기 +3px)
        name_label = QLabel(self.preset_name)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setWordWrap(True)
        name_label.setMaximumHeight(28)
        name_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
                background-color: transparent;
                border: none;
            }}
        """)
        layout.addWidget(name_label)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.preset_name)
        super().mousePressEvent(event)


class PresetTabMixin:
    """프리셋 탭 Mixin - RemoteWindow와 함께 상속하여 사용"""

    # === 데이터 초기화 ===

    def _init_preset_data(self):
        """프리셋 탭 데이터 초기화 (RemoteWindow.__init__에서 호출)"""
        # 프리셋 즐겨찾기 데이터
        self.preset_favorites = []  # [{"name": "preset_name", "mode": "NAI"}, ...]

        # 동기화 플래그 (무한 루프 방지)
        self._preset_sync_in_progress = False

        # 리모트 체크박스 저장
        self.remote_preprocessing_checkboxes = {}

        # 즐겨찾기 로드
        self._load_preset_favorites()

    # === 데이터 로드/저장 ===

    def _load_preset_favorites(self):
        """프리셋 즐겨찾기 데이터 로드"""
        if PRESET_FAVORITES_JSON.exists():
            try:
                with open(PRESET_FAVORITES_JSON, 'r', encoding='utf-8') as f:
                    self.preset_favorites = json.load(f)
            except Exception as e:
                print(f"⚠️ 프리셋 즐겨찾기 로드 실패: {e}")
                self.preset_favorites = []
        else:
            self.preset_favorites = []

    def _save_preset_favorites(self):
        """프리셋 즐겨찾기 데이터 저장"""
        try:
            PRESET_FAVORITES_DIR.mkdir(parents=True, exist_ok=True)
            with open(PRESET_FAVORITES_JSON, 'w', encoding='utf-8') as f:
                json.dump(self.preset_favorites, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 프리셋 즐겨찾기 저장 실패: {e}")

    def _validate_preset_favorites(self):
        """즐겨찾기 유효성 검사 - 실제 프리셋에 존재하는지 확인"""
        if not self.preset_module:
            return

        valid_favorites = []
        current_mode = self.preset_module.app_context.get_api_mode() if self.preset_module.app_context else "NAI"
        preset_dir = Path("save/presets") / current_mode

        for fav in self.preset_favorites:
            preset_name = fav.get("name", "")
            fav_mode = fav.get("mode", "NAI")

            # 현재 모드의 프리셋만 검사
            if fav_mode == current_mode:
                preset_file = preset_dir / f"{preset_name}.json"
                thumb_file = PRESET_FAVORITES_DIR / f"{preset_name}.png"

                if preset_file.exists():
                    valid_favorites.append(fav)
                else:
                    # 프리셋이 없으면 썸네일도 삭제
                    if thumb_file.exists():
                        thumb_file.unlink()
                    print(f"🗑️ 삭제된 프리셋 즐겨찾기 제거: {preset_name}")
            else:
                # 다른 모드의 즐겨찾기는 유지
                valid_favorites.append(fav)

        if len(valid_favorites) != len(self.preset_favorites):
            self.preset_favorites = valid_favorites
            self._save_preset_favorites()

    # === UI 생성 ===

    def _create_preset_tab(self):
        """탭1: 프리셋 (이중 탭 - 프리셋, P.엔지니어링)"""
        preset_container = QWidget()
        preset_container_layout = QVBoxLayout(preset_container)
        preset_container_layout.setContentsMargins(4, 4, 4, 4)

        # 이중 탭
        preset_sub_tabs = QTabWidget()
        preset_sub_tabs.setStyleSheet(DARK_STYLES['dark_tabs'])
        preset_container_layout.addWidget(preset_sub_tabs)

        # 서브탭1: 프리셋 (즐겨찾기)
        self._create_preset_favorites_subtab(preset_sub_tabs)

        # 서브탭2: P.엔지니어링
        self._create_preset_engineering_subtab(preset_sub_tabs)

        self.main_tabs.addTab(preset_container, "🔧 프리셋")

    def _create_preset_favorites_subtab(self, parent_tabs: QTabWidget):
        """프리셋 즐겨찾기 서브탭"""
        favorites_widget = QWidget()
        favorites_layout = QVBoxLayout(favorites_widget)
        favorites_layout.setContentsMargins(8, 8, 8, 8)
        favorites_layout.setSpacing(8)

        # === 상단 섹션 ===
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
        self.current_preset_thumb = QLabel()
        self.current_preset_thumb.setFixedSize(PRESET_PREVIEW_WIDTH, PRESET_PREVIEW_HEIGHT)
        self.current_preset_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.current_preset_thumb.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 2px dashed {DARK_COLORS['border']};
                border-radius: 6px;
                color: {DARK_COLORS['text_disabled']};
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)
        self.current_preset_thumb.setText("썸네일\n없음")
        top_layout.addWidget(self.current_preset_thumb)

        # 오른쪽: 컨트롤 영역 (세로 배치)
        right_section = QVBoxLayout()
        right_section.setSpacing(6)

        # 1) "현재 프리셋" 라벨
        preset_label = QLabel("현재 프리셋")
        preset_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-weight: bold;
                font-size: {get_scaled_font_size(15)}px;
            }}
        """)
        right_section.addWidget(preset_label)

        # 2) [콤보박스][관리] 가로 배치
        combo_row = QHBoxLayout()
        combo_row.setSpacing(6)

        self.remote_preset_combo = QComboBox()
        self.remote_preset_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.remote_preset_combo.setMinimumWidth(150)
        self._sync_preset_combo()
        self.remote_preset_combo.currentTextChanged.connect(self._on_remote_preset_changed)
        combo_row.addWidget(self.remote_preset_combo, 1)

        self.manage_preset_btn = QPushButton("📂 관리")
        self.manage_preset_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.manage_preset_btn.setFixedWidth(100)
        self.manage_preset_btn.clicked.connect(self._open_preset_folder)
        combo_row.addWidget(self.manage_preset_btn)

        right_section.addLayout(combo_row)

        # 3) 클립보드에서 썸네일 생성 버튼 (진한 회색 배경, primary_button과 동일한 크기)
        self.paste_thumb_btn = QPushButton("📋 클립보드에서 썸네일 생성")
        self.paste_thumb_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(8)}px {get_scaled_size(24)}px;
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-weight: 500;
                font-size: {get_scaled_font_size(15)}px;
                min-height: {get_scaled_size(16)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QPushButton:pressed {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
            QPushButton:disabled {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_disabled']};
                border-color: {DARK_COLORS['bg_tertiary']};
            }}
        """)
        self.paste_thumb_btn.clicked.connect(self._paste_preset_thumbnail_from_clipboard)
        right_section.addWidget(self.paste_thumb_btn)

        # 4) 즐겨찾기에 등록 버튼
        self.preset_favorite_btn = QPushButton("⭐ 즐겨찾기에 등록")
        self.preset_favorite_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.preset_favorite_btn.clicked.connect(self._toggle_preset_favorite)
        right_section.addWidget(self.preset_favorite_btn)

        right_section.addStretch()

        top_layout.addLayout(right_section, 1)
        favorites_layout.addWidget(top_section)

        # === 하단 섹션: 즐겨찾기 목록 ===
        bottom_section = QFrame()
        bottom_section.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 8px;
            }}
        """)
        bottom_layout = QVBoxLayout(bottom_section)
        bottom_layout.setContentsMargins(10, 10, 10, 10)
        bottom_layout.setSpacing(8)

        # 헤더
        header_label = QLabel("⭐ 즐겨찾기")
        header_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['accent_blue']};
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
            }}
        """)
        bottom_layout.addWidget(header_label)

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
        self.preset_favorites_grid_widget = QWidget()
        self.preset_favorites_grid_layout = QGridLayout(self.preset_favorites_grid_widget)
        self.preset_favorites_grid_layout.setSpacing(10)
        self.preset_favorites_grid_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area.setWidget(self.preset_favorites_grid_widget)
        bottom_layout.addWidget(scroll_area, 1)

        favorites_layout.addWidget(bottom_section, 1)

        parent_tabs.addTab(favorites_widget, "⭐ 프리셋")

        # 즐겨찾기 유효성 검사 및 UI 업데이트
        self._validate_preset_favorites()
        self._update_preset_favorites_grid()
        self._update_current_preset_ui()

    def _create_preset_engineering_subtab(self, parent_tabs: QTabWidget):
        """P.엔지니어링 서브탭 - 원본 모듈과 양방향 동기화"""
        eng_widget = QWidget()
        eng_layout = QVBoxLayout(eng_widget)
        eng_layout.setContentsMargins(8, 8, 8, 8)
        eng_layout.setSpacing(8)

        if self.preset_module:
            # === 선행 프롬프트 ===
            if hasattr(self.preset_module, 'pre_textedit') and self.preset_module.pre_textedit:
                pre_label = QLabel("선행 프롬프트:")
                pre_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-weight: bold;")
                eng_layout.addWidget(pre_label)

                self.remote_pre_edit = QTextEdit()
                self.remote_pre_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
                self.remote_pre_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                self.remote_pre_edit.setPlainText(self.preset_module.pre_textedit.toPlainText())
                self.remote_pre_edit.textChanged.connect(self._on_remote_pre_changed)
                eng_layout.addWidget(self.remote_pre_edit, 1)  # stretch factor 1

                # 원본 -> 리모트 동기화 연결
                self.preset_module.pre_textedit.textChanged.connect(self._sync_pre_from_original)

            # === 후행 프롬프트 ===
            if hasattr(self.preset_module, 'post_textedit') and self.preset_module.post_textedit:
                post_label = QLabel("후행 프롬프트:")
                post_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-weight: bold;")
                eng_layout.addWidget(post_label)

                self.remote_post_edit = QTextEdit()
                self.remote_post_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
                self.remote_post_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                self.remote_post_edit.setPlainText(self.preset_module.post_textedit.toPlainText())
                self.remote_post_edit.textChanged.connect(self._on_remote_post_changed)
                eng_layout.addWidget(self.remote_post_edit, 1)  # stretch factor 1

                # 원본 -> 리모트 동기화 연결
                self.preset_module.post_textedit.textChanged.connect(self._sync_post_from_original)

            # === 자동 숨김 프롬프트 ===
            if hasattr(self.preset_module, 'auto_hide_textedit') and self.preset_module.auto_hide_textedit:
                auto_hide_label = QLabel("자동 숨김 프롬프트:")
                auto_hide_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-weight: bold;")
                eng_layout.addWidget(auto_hide_label)

                self.remote_auto_hide_edit = QTextEdit()
                self.remote_auto_hide_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
                self.remote_auto_hide_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                self.remote_auto_hide_edit.setPlainText(self.preset_module.auto_hide_textedit.toPlainText())
                self.remote_auto_hide_edit.textChanged.connect(self._on_remote_auto_hide_changed)
                eng_layout.addWidget(self.remote_auto_hide_edit, 1)  # stretch factor 1

                # 원본 -> 리모트 동기화 연결
                self.preset_module.auto_hide_textedit.textChanged.connect(self._sync_auto_hide_from_original)

            # === 전처리 옵션 체크박스 ===
            if hasattr(self.preset_module, 'option_key_map') and hasattr(self.preset_module, 'preprocessing_checkboxes'):
                options_label = QLabel("전처리 옵션:")
                options_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-weight: bold;")
                eng_layout.addWidget(options_label)

                options_frame = QFrame()
                options_frame.setStyleSheet(f"""
                    QFrame {{
                        background-color: {DARK_COLORS['bg_secondary']};
                        border: 1px solid {DARK_COLORS['border']};
                        border-radius: 6px;
                        padding: 4px;
                    }}
                """)
                options_layout = QVBoxLayout(options_frame)
                options_layout.setContentsMargins(8, 8, 8, 8)
                options_layout.setSpacing(4)

                for text in self.preset_module.option_key_map.keys():
                    cb = QCheckBox(text)
                    cb.setStyleSheet(DARK_STYLES['dark_checkbox'])

                    # 원본 체크박스 상태 복사
                    if text in self.preset_module.preprocessing_checkboxes:
                        cb.setChecked(self.preset_module.preprocessing_checkboxes[text].isChecked())

                    # 양방향 동기화 연결
                    cb.stateChanged.connect(lambda state, t=text: self._on_remote_checkbox_changed(t, state))
                    options_layout.addWidget(cb)
                    self.remote_preprocessing_checkboxes[text] = cb

                    # 원본 -> 리모트 동기화 연결
                    if text in self.preset_module.preprocessing_checkboxes:
                        self.preset_module.preprocessing_checkboxes[text].stateChanged.connect(
                            lambda state, t=text: self._sync_checkbox_from_original(t, state)
                        )

                eng_layout.addWidget(options_frame)

            eng_layout.addStretch()
        else:
            placeholder = QLabel("프리셋 모듈을 찾을 수 없습니다.")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet(f"color: {DARK_COLORS['text_disabled']};")
            eng_layout.addWidget(placeholder)

        parent_tabs.addTab(eng_widget, "🔧 P.엔지니어링")

    # === 양방향 동기화 메서드들 ===

    def _on_remote_pre_changed(self):
        """리모트 선행 프롬프트 변경 -> 원본 반영"""
        if self._preset_sync_in_progress:
            return
        if self.preset_module and hasattr(self.preset_module, 'pre_textedit'):
            self._preset_sync_in_progress = True
            self.preset_module.pre_textedit.setPlainText(self.remote_pre_edit.toPlainText())
            self._preset_sync_in_progress = False

    def _on_remote_post_changed(self):
        """리모트 후행 프롬프트 변경 -> 원본 반영"""
        if self._preset_sync_in_progress:
            return
        if self.preset_module and hasattr(self.preset_module, 'post_textedit'):
            self._preset_sync_in_progress = True
            self.preset_module.post_textedit.setPlainText(self.remote_post_edit.toPlainText())
            self._preset_sync_in_progress = False

    def _on_remote_auto_hide_changed(self):
        """리모트 자동 숨김 프롬프트 변경 -> 원본 반영"""
        if self._preset_sync_in_progress:
            return
        if self.preset_module and hasattr(self.preset_module, 'auto_hide_textedit'):
            self._preset_sync_in_progress = True
            self.preset_module.auto_hide_textedit.setPlainText(self.remote_auto_hide_edit.toPlainText())
            self._preset_sync_in_progress = False

    def _on_remote_checkbox_changed(self, text: str, state: int):
        """리모트 체크박스 변경 -> 원본 반영"""
        if self._preset_sync_in_progress:
            return
        if self.preset_module and hasattr(self.preset_module, 'preprocessing_checkboxes'):
            if text in self.preset_module.preprocessing_checkboxes:
                self._preset_sync_in_progress = True
                self.preset_module.preprocessing_checkboxes[text].setChecked(state == 2)
                self._preset_sync_in_progress = False

    def _sync_pre_from_original(self):
        """원본 선행 프롬프트 변경 -> 리모트 반영"""
        if self._preset_sync_in_progress:
            return
        if hasattr(self, 'remote_pre_edit') and self.preset_module:
            self._preset_sync_in_progress = True
            self.remote_pre_edit.setPlainText(self.preset_module.pre_textedit.toPlainText())
            self._preset_sync_in_progress = False

    def _sync_post_from_original(self):
        """원본 후행 프롬프트 변경 -> 리모트 반영"""
        if self._preset_sync_in_progress:
            return
        if hasattr(self, 'remote_post_edit') and self.preset_module:
            self._preset_sync_in_progress = True
            self.remote_post_edit.setPlainText(self.preset_module.post_textedit.toPlainText())
            self._preset_sync_in_progress = False

    def _sync_auto_hide_from_original(self):
        """원본 자동 숨김 프롬프트 변경 -> 리모트 반영"""
        if self._preset_sync_in_progress:
            return
        if hasattr(self, 'remote_auto_hide_edit') and self.preset_module:
            self._preset_sync_in_progress = True
            self.remote_auto_hide_edit.setPlainText(self.preset_module.auto_hide_textedit.toPlainText())
            self._preset_sync_in_progress = False

    def _sync_checkbox_from_original(self, text: str, state: int):
        """원본 체크박스 변경 -> 리모트 반영"""
        if self._preset_sync_in_progress:
            return
        if text in self.remote_preprocessing_checkboxes:
            self._preset_sync_in_progress = True
            self.remote_preprocessing_checkboxes[text].setChecked(state == 2)
            self._preset_sync_in_progress = False

    # === 콤보박스 동기화 ===

    def _sync_preset_combo(self):
        """프리셋 콤보박스 동기화 (*randomized 제외)"""
        if not self.preset_module or not hasattr(self.preset_module, 'preset_combo'):
            return

        src_combo = self.preset_module.preset_combo
        self.remote_preset_combo.blockSignals(True)
        self.remote_preset_combo.clear()

        for i in range(src_combo.count()):
            item_text = src_combo.itemText(i)
            # *randomized는 즐겨찾기 시스템에서 제외
            if item_text == "*randomized":
                continue
            self.remote_preset_combo.addItem(item_text)

        self.remote_preset_combo.setCurrentText(src_combo.currentText())
        self.remote_preset_combo.blockSignals(False)

    def _on_remote_preset_changed(self, text: str):
        """리모트에서 프리셋 변경 시 원본 모듈에 반영"""
        if not self.preset_module or not hasattr(self.preset_module, 'preset_combo'):
            return

        self.preset_module.preset_combo.setCurrentText(text)

        # 표시 업데이트
        QTimer.singleShot(100, self._update_preset_display)
        QTimer.singleShot(150, self._update_current_preset_ui)

    def _update_preset_display(self):
        """프리셋 내용 표시 업데이트 (프리셋 변경 시 호출)"""
        if not self.preset_module:
            return

        self._preset_sync_in_progress = True

        # 선행 프롬프트 동기화
        if hasattr(self, 'remote_pre_edit') and hasattr(self.preset_module, 'pre_textedit') and self.preset_module.pre_textedit:
            self.remote_pre_edit.setPlainText(self.preset_module.pre_textedit.toPlainText())

        # 후행 프롬프트 동기화
        if hasattr(self, 'remote_post_edit') and hasattr(self.preset_module, 'post_textedit') and self.preset_module.post_textedit:
            self.remote_post_edit.setPlainText(self.preset_module.post_textedit.toPlainText())

        # 자동 숨김 프롬프트 동기화
        if hasattr(self, 'remote_auto_hide_edit') and hasattr(self.preset_module, 'auto_hide_textedit') and self.preset_module.auto_hide_textedit:
            self.remote_auto_hide_edit.setPlainText(self.preset_module.auto_hide_textedit.toPlainText())

        # 체크박스 동기화
        if hasattr(self, 'remote_preprocessing_checkboxes') and hasattr(self.preset_module, 'preprocessing_checkboxes'):
            for text, remote_cb in self.remote_preprocessing_checkboxes.items():
                if text in self.preset_module.preprocessing_checkboxes:
                    remote_cb.setChecked(self.preset_module.preprocessing_checkboxes[text].isChecked())

        self._preset_sync_in_progress = False

    # === 그리드 업데이트 ===

    def _calculate_preset_thumbnail_size(self) -> tuple:
        """현재 UI 크기를 기반으로 썸네일 크기 계산 (3열 기준)"""
        # 그리드 영역의 가용 너비 계산
        available_width = self.preset_favorites_grid_widget.width()

        # 최소 너비 보장
        if available_width < 100:
            available_width = 450  # 기본값

        # 3열 기준으로 각 아이템 너비 계산 (여백 고려)
        cols = 3
        spacing = 10  # 그리드 간격
        item_padding = 10  # 아이템 내부 패딩

        # 아이템 하나의 너비 = (전체 너비 - 간격) / 열 수 - 내부 패딩
        item_width = (available_width - (cols - 1) * spacing) // cols - item_padding

        # 최소/최대 크기 제한
        item_width = max(80, min(180, item_width))

        # 비율에 맞는 높이 계산 (368:512 비율)
        item_height = int(item_width / PRESET_THUMB_ASPECT_RATIO)

        return item_width, item_height

    def _update_preset_favorites_grid(self):
        """즐겨찾기 그리드 업데이트 (UI 크기에 맞게 동적 조절, 좌측 정렬)"""
        # 기존 위젯 제거
        while self.preset_favorites_grid_layout.count():
            item = self.preset_favorites_grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        current_mode = "NAI"
        if self.preset_module and self.preset_module.app_context:
            current_mode = self.preset_module.app_context.get_api_mode() or "NAI"

        # 현재 모드의 즐겨찾기만 필터링
        mode_favorites = [f for f in self.preset_favorites if f.get("mode", "NAI") == current_mode]

        if not mode_favorites:
            empty_label = QLabel("즐겨찾기가 없습니다.\n프리셋을 선택하고 ⭐ 버튼을 눌러 추가하세요.")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(12)}px;
                    padding: 40px;
                }}
            """)
            self.preset_favorites_grid_layout.addWidget(empty_label, 0, 0, 1, 3)
            return

        # 동적 썸네일 크기 계산
        thumb_width, thumb_height = self._calculate_preset_thumbnail_size()

        # 그리드에 아이템 추가 (3열, 좌측 정렬)
        cols = 3
        for idx, fav in enumerate(mode_favorites):
            preset_name = fav.get("name", "")
            thumb_path = PRESET_FAVORITES_DIR / f"{preset_name}.png"

            item_widget = PresetFavoriteItemWidget(
                preset_name, thumb_path,
                thumb_width=thumb_width,
                thumb_height=thumb_height
            )
            item_widget.clicked.connect(self._on_preset_favorite_clicked)

            row = idx // cols
            col = idx % cols
            self.preset_favorites_grid_layout.addWidget(
                item_widget, row, col,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
            )

    def _update_current_preset_ui(self):
        """현재 선택된 프리셋 UI 업데이트"""
        if not self.preset_module:
            return

        current_preset = self.preset_module.current_preset
        current_mode = "NAI"
        if self.preset_module.app_context:
            current_mode = self.preset_module.app_context.get_api_mode() or "NAI"

        # default 프리셋 여부 확인
        is_default = (current_preset == "default")

        # 썸네일 업데이트
        thumb_path = PRESET_FAVORITES_DIR / f"{current_preset}.png"
        if thumb_path.exists():
            pixmap = QPixmap(str(thumb_path))
            scaled = pixmap.scaled(
                PRESET_PREVIEW_WIDTH, PRESET_PREVIEW_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.current_preset_thumb.setPixmap(scaled)
            self.current_preset_thumb.setStyleSheet(f"""
                QLabel {{
                    background-color: {DARK_COLORS['bg_primary']};
                    border: 2px solid {DARK_COLORS['border']};
                    border-radius: 6px;
                }}
            """)
        else:
            self.current_preset_thumb.clear()
            self.current_preset_thumb.setText("썸네일\n없음")
            self.current_preset_thumb.setStyleSheet(f"""
                QLabel {{
                    background-color: {DARK_COLORS['bg_primary']};
                    border: 2px dashed {DARK_COLORS['border']};
                    border-radius: 6px;
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(14)}px;
                }}
            """)

        # default 프리셋일 경우 버튼 비활성화
        self.paste_thumb_btn.setEnabled(not is_default)
        self.preset_favorite_btn.setEnabled(not is_default)

        # 즐겨찾기 버튼 상태 업데이트
        is_favorite = any(
            f.get("name") == current_preset and f.get("mode") == current_mode
            for f in self.preset_favorites
        )

        if is_favorite:
            self.preset_favorite_btn.setText("💔 즐겨찾기에서 제거")
            self.preset_favorite_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        else:
            self.preset_favorite_btn.setText("⭐ 즐겨찾기에 등록")
            self.preset_favorite_btn.setStyleSheet(DARK_STYLES['primary_button'])

    # === 액션 핸들러 ===

    def _open_preset_folder(self):
        """프리셋 폴더 열기"""
        current_mode = "NAI"
        if self.preset_module and self.preset_module.app_context:
            current_mode = self.preset_module.app_context.get_api_mode() or "NAI"

        preset_dir = Path("save/presets") / current_mode

        if not preset_dir.exists():
            preset_dir.mkdir(parents=True, exist_ok=True)

        # Windows 탐색기로 폴더 열기
        if os.name == 'nt':
            subprocess.Popen(['explorer', str(preset_dir.resolve())])
        else:
            # macOS / Linux
            subprocess.Popen(['open' if os.uname().sysname == 'Darwin' else 'xdg-open', str(preset_dir.resolve())])

    def _paste_preset_thumbnail_from_clipboard(self):
        """클립보드에서 썸네일 이미지 붙여넣기"""
        if not self.preset_module:
            return

        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()

        if mime_data.hasImage():
            qimage = clipboard.image()
            if qimage.isNull():
                self._show_warning("오류", "클립보드에 유효한 이미지가 없습니다.")
                return

            # QImage -> PIL Image 변환
            buffer = qimage.bits().asstring(qimage.sizeInBytes())
            pil_image = Image.frombytes(
                "RGBA" if qimage.hasAlphaChannel() else "RGB",
                (qimage.width(), qimage.height()),
                buffer,
                "raw",
                "BGRA" if qimage.hasAlphaChannel() else "BGR"
            )

            # 스마트 크롭 및 리사이즈
            cropped = self._smart_crop_preset_image(pil_image, 368, 512)

            # 저장
            current_preset = self.preset_module.current_preset
            thumb_path = PRESET_FAVORITES_DIR / f"{current_preset}.png"
            PRESET_FAVORITES_DIR.mkdir(parents=True, exist_ok=True)
            cropped.save(str(thumb_path), "PNG")

            print(f"✅ 프리셋 썸네일 저장: {thumb_path}")

            # UI 업데이트
            self._update_current_preset_ui()
            self._update_preset_favorites_grid()

            self._show_info("완료", f"'{current_preset}' 프리셋의 썸네일이 저장되었습니다.")
        else:
            self._show_warning("오류", "클립보드에 이미지가 없습니다.\n이미지를 복사한 후 다시 시도하세요.")

    def _smart_crop_preset_image(self, image: Image.Image, target_width: int, target_height: int) -> Image.Image:
        """이미지를 스마트 크롭하여 목표 비율에 맞춤 (상단 중앙 포커싱)"""
        img_width, img_height = image.size
        target_ratio = target_width / target_height
        img_ratio = img_width / img_height

        # 1단계: 비율 맞춤 크롭
        if img_ratio > target_ratio:
            # 가로로 긴 이미지 -> 중앙 크롭
            new_width = int(img_height * target_ratio)
            left = (img_width - new_width) // 2
            crop_box = (left, 0, left + new_width, img_height)
        else:
            # 세로로 긴 이미지 -> 상단 크롭
            new_height = int(img_width / target_ratio)
            crop_box = (0, 0, img_width, new_height)

        cropped = image.crop(crop_box)

        # 2단계: 상단 중앙 포커싱 크롭 (얼굴 영역)
        # 368:512 비율 유지하면서 상단 중앙 영역 추출
        crop_w, crop_h = cropped.size

        # 포커싱 영역 크기 계산 (원본의 약 50% 크기, 368:512 비율 유지)
        focus_ratio = PRESET_THUMB_ASPECT_RATIO  # 368/512 = 0.71875

        # 세로 기준으로 60% 영역 사용 (상단 포커싱)
        focus_h = int(crop_h * 0.6)
        focus_w = int(focus_h * focus_ratio)

        # 가로가 원본보다 크면 가로 기준으로 재계산
        if focus_w > crop_w * 0.8:
            focus_w = int(crop_w * 0.8)
            focus_h = int(focus_w / focus_ratio)

        # 중앙 정렬 (가로), 상단 정렬 (세로)
        focus_left = (crop_w - focus_w) // 2
        focus_top = 0

        focused = cropped.crop((focus_left, focus_top, focus_left + focus_w, focus_top + focus_h))

        # 최종 리사이즈
        return focused.resize((target_width, target_height), Image.Resampling.LANCZOS)

    def _toggle_preset_favorite(self):
        """즐겨찾기 등록/제거 토글"""
        if not self.preset_module:
            return

        current_preset = self.preset_module.current_preset
        current_mode = "NAI"
        if self.preset_module.app_context:
            current_mode = self.preset_module.app_context.get_api_mode() or "NAI"

        # default는 즐겨찾기 불가
        if current_preset == "default":
            self._show_warning("알림", "default 프리셋은 즐겨찾기에 등록할 수 없습니다.")
            return

        # 현재 즐겨찾기 상태 확인
        is_favorite = any(
            f.get("name") == current_preset and f.get("mode") == current_mode
            for f in self.preset_favorites
        )

        if is_favorite:
            # 즐겨찾기 제거
            self.preset_favorites = [
                f for f in self.preset_favorites
                if not (f.get("name") == current_preset and f.get("mode") == current_mode)
            ]
            self._save_preset_favorites()
            self._update_preset_favorites_grid()
            self._update_current_preset_ui()
            print(f"💔 프리셋 즐겨찾기 제거: {current_preset}")
        else:
            # 즐겨찾기 등록 전 썸네일 확인
            thumb_path = PRESET_FAVORITES_DIR / f"{current_preset}.png"
            if not thumb_path.exists():
                if self._show_question(
                    "썸네일 필요",
                    f"'{current_preset}' 프리셋의 썸네일이 없습니다.\n"
                    "클립보드에서 이미지를 붙여넣으시겠습니까?"
                ):
                    self._paste_preset_thumbnail_from_clipboard()
                    # 썸네일 저장 후 다시 확인
                    if not thumb_path.exists():
                        return
                else:
                    return

            # 즐겨찾기 등록
            self.preset_favorites.append({
                "name": current_preset,
                "mode": current_mode
            })
            self._save_preset_favorites()
            self._update_preset_favorites_grid()
            self._update_current_preset_ui()
            print(f"⭐ 프리셋 즐겨찾기 등록: {current_preset}")

    def _on_preset_favorite_clicked(self, preset_name: str):
        """즐겨찾기 아이템 클릭 시 해당 프리셋 선택"""
        if not self.preset_module:
            return

        # 콤보박스에서 해당 프리셋 선택
        self.remote_preset_combo.setCurrentText(preset_name)
