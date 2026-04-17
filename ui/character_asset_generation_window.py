"""Dedicated window for generating and saving character assets."""

from __future__ import annotations

import uuid

from PIL import Image
from PIL.ImageQt import ImageQt
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.theme import DARK_COLORS, DARK_STYLES
from utils.character_asset_storage import save_character_asset


class CharacterAssetResultCard(QFrame):
    """Simple selectable tile for generated character assets."""

    clicked = pyqtSignal(object)

    def __init__(self, result_data: dict, index: int, parent=None):
        super().__init__(parent)
        self.result_data = result_data
        self.index = index
        self._selected = False
        self._build_ui()

    def _build_ui(self):
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedSize(get_scaled_size(180), get_scaled_size(290))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(get_scaled_size(8), get_scaled_size(8), get_scaled_size(8), get_scaled_size(8))
        layout.setSpacing(get_scaled_size(8))

        title = QLabel(f"Asset #{self.index}")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: white; font-size: {get_scaled_font_size(13)}px; font-weight: 600;")
        layout.addWidget(title)

        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setFixedSize(get_scaled_size(160), get_scaled_size(240))
        image_label.setStyleSheet("QLabel { background-color: #101010; border: 1px solid #333; }")

        image = self.result_data.get("image")
        if image is not None:
            preview = image.copy()
            if preview.mode != "RGBA":
                preview = preview.convert("RGBA")
            preview.thumbnail((get_scaled_size(160), get_scaled_size(240)))
            pixmap = QPixmap.fromImage(ImageQt(preview))
            image_label.setPixmap(pixmap)

        layout.addWidget(image_label)
        self._apply_selected_style(False)

    def _apply_selected_style(self, selected: bool):
        border = DARK_COLORS['accent_blue'] if selected else "#333333"
        bg = "#1f2a36" if selected else "#1a1a1a"
        self.setStyleSheet(
            f"QFrame {{ border: 2px solid {border}; border-radius: 6px; background-color: {bg}; }}"
        )

    def set_selected(self, selected: bool):
        self._selected = selected
        self._apply_selected_style(selected)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self)
        super().mousePressEvent(event)


class CharacterAssetGenerationWindow(QDialog):
    """Sequential character-asset generation UI."""

    _TOAST_COLORS = {
        "blue": DARK_COLORS['accent_blue'],
        "green": DARK_COLORS['success'],
        "gray": DARK_COLORS['bg_hover'],
        "red": DARK_COLORS['error'],
    }

    def __init__(self, app_context, temp_window, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.temp_window = temp_window
        self.result_cards: list[CharacterAssetResultCard] = []
        self.selected_card: CharacterAssetResultCard | None = None
        self._preview_source_image = None
        self.pending_count = 0
        self.active_request_id: str | None = None
        self.stop_requested = False
        self.is_generating = False
        self._completed_event_name = "generation_completed_for_character_asset"
        self._error_event_name = "generation_error"
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._build_ui()
        self._load_initial_character_values()
        self.app_context.subscribe(self._completed_event_name, self._on_asset_generation_completed)
        self.app_context.subscribe(self._error_event_name, self._on_asset_generation_error)

    def _build_ui(self):
        self.setWindowTitle("캐릭터 에셋 생성")
        self.setModal(False)
        self.resize(get_scaled_size(1640), get_scaled_size(1160))
        self.setMinimumSize(get_scaled_size(1460), get_scaled_size(980))
        self.setStyleSheet(
            f"QDialog {{ background-color: {DARK_COLORS['bg_primary']}; color: {DARK_COLORS['text_primary']}; }}"
        )

        panel_style = (
            f"QFrame {{ "
            f"background-color: {DARK_COLORS['bg_secondary']}; "
            f"border: 1px solid {DARK_COLORS['border']}; "
            f"border-radius: {get_scaled_size(8)}px; "
            f"}}"
        )
        section_title_style = (
            f"font-size: {get_scaled_font_size(14)}px; "
            f"font-weight: 700; color: {DARK_COLORS['text_primary']};"
        )
        helper_text_style = (
            f"font-size: {get_scaled_font_size(12)}px; "
            f"color: {DARK_COLORS['text_secondary']};"
        )
        editor_style = f"""
            QTextEdit {{
                background-color: #202733;
                border: 1px solid #3A4658;
                border-radius: {get_scaled_size(6)}px;
                padding: {get_scaled_size(10)}px;
                color: {DARK_COLORS['text_primary']};
                selection-background-color: {DARK_COLORS['accent_blue']};
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-size: {get_scaled_font_size(18)}px;
            }}
            QTextEdit:focus {{
                border: 2px solid {DARK_COLORS['accent_blue']};
                background-color: #242D3A;
            }}
        """

        layout = QVBoxLayout(self)
        layout.setContentsMargins(get_scaled_size(18), get_scaled_size(18), get_scaled_size(18), get_scaled_size(18))
        layout.setSpacing(get_scaled_size(14))

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(get_scaled_size(12))

        header = QLabel("캐릭터 에셋 생성")
        header.setStyleSheet(f"font-size: {get_scaled_font_size(24)}px; font-weight: 700; color: white;")
        header_desc = QLabel("체크된 캐릭터를 불러와 수정하고, 연속 생성 결과를 비교 저장합니다.")
        header_desc.setStyleSheet(helper_text_style)

        header_text_layout = QVBoxLayout()
        header_text_layout.setContentsMargins(0, 0, 0, 0)
        header_text_layout.setSpacing(get_scaled_size(2))
        header_text_layout.addWidget(header)
        header_text_layout.addWidget(header_desc)

        header_row.addLayout(header_text_layout)
        header_row.addStretch()
        layout.addLayout(header_row)

        left_panel = QFrame()
        left_panel.setMinimumWidth(get_scaled_size(610))
        left_panel.setStyleSheet(panel_style)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(get_scaled_size(16), get_scaled_size(16), get_scaled_size(16), get_scaled_size(16))
        left_layout.setSpacing(get_scaled_size(12))

        prompt_title = QLabel("Prompt")
        prompt_title.setStyleSheet(section_title_style)
        prompt_hint = QLabel("첫 번째로 체크된 캐릭터를 자동 로드합니다. 여기서 바로 수정해도 됩니다.")
        prompt_hint.setStyleSheet(helper_text_style)

        self.prompt_edit = QTextEdit()
        self.prompt_edit.setAcceptRichText(False)
        self.prompt_edit.setPlaceholderText("캐릭터 프롬프트")
        self.prompt_edit.setStyleSheet(editor_style)
        self.prompt_edit.setFixedHeight(get_scaled_size(160))

        uc_title = QLabel("UC")
        uc_title.setStyleSheet(section_title_style)
        self.uc_edit = QTextEdit()
        self.uc_edit.setAcceptRichText(False)
        self.uc_edit.setPlaceholderText("캐릭터 UC")
        self.uc_edit.setStyleSheet(editor_style)
        self.uc_edit.setFixedHeight(get_scaled_size(84))

        control_frame = QFrame()
        control_frame.setStyleSheet(
            f"QFrame {{ background-color: {DARK_COLORS['bg_primary']}; border: 1px solid {DARK_COLORS['border']}; "
            f"border-radius: {get_scaled_size(6)}px; }}"
        )
        control_layout = QVBoxLayout(control_frame)
        control_layout.setContentsMargins(get_scaled_size(14), get_scaled_size(14), get_scaled_size(14), get_scaled_size(14))
        control_layout.setSpacing(get_scaled_size(12))

        options_row = QHBoxLayout()
        options_row.setContentsMargins(0, 0, 0, 0)
        options_row.setSpacing(get_scaled_size(10))

        count_label = QLabel("연속 생성 횟수")
        count_label.setStyleSheet(section_title_style)
        self.count_spinbox = QSpinBox()
        self.count_spinbox.setRange(1, 999)
        self.count_spinbox.setValue(1)
        self.count_spinbox.setFixedWidth(get_scaled_size(120))
        self.count_spinbox.setStyleSheet(DARK_STYLES['compact_spinbox'])

        self.continue_checkbox = QCheckBox("계속 생성")
        self.continue_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])

        options_row.addWidget(count_label)
        options_row.addWidget(self.count_spinbox)
        options_row.addWidget(self.continue_checkbox)
        options_row.addStretch()

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(get_scaled_size(10))

        self.generate_button = QPushButton("생성 시작")
        self.generate_button.setStyleSheet(DARK_STYLES['primary_button'])
        self.generate_button.clicked.connect(self._start_generation)

        self.stop_button = QPushButton("중지")
        self.stop_button.setStyleSheet(DARK_STYLES['secondary_button'])
        self.stop_button.clicked.connect(self._stop_generation)

        self.save_button = QPushButton("선택 이미지 저장")
        self.save_button.setStyleSheet(DARK_STYLES['secondary_button'])
        self.save_button.clicked.connect(self._save_selected_asset)

        button_row.addWidget(self.generate_button)
        button_row.addWidget(self.stop_button)
        button_row.addWidget(self.save_button)
        button_row.addStretch()

        self.status_label = QLabel("대기 중")
        self.status_label.setStyleSheet(helper_text_style)

        control_layout.addLayout(options_row)
        control_layout.addLayout(button_row)
        control_layout.addWidget(self.status_label)

        left_layout.addWidget(prompt_title)
        left_layout.addWidget(prompt_hint)
        left_layout.addWidget(self.prompt_edit)
        left_layout.addWidget(uc_title)
        left_layout.addWidget(self.uc_edit)
        left_layout.addWidget(control_frame)
        left_layout.addStretch()

        self.preview_frame = QFrame()
        self.preview_frame.setFixedWidth(get_scaled_size(650))
        self.preview_frame.setStyleSheet(panel_style)
        preview_layout = QVBoxLayout(self.preview_frame)
        preview_layout.setContentsMargins(get_scaled_size(4), get_scaled_size(4), get_scaled_size(4), get_scaled_size(4))
        preview_layout.setSpacing(get_scaled_size(2))

        preview_title = QLabel("미리보기")
        preview_title.setStyleSheet(section_title_style)
        preview_hint = QLabel("선택한 결과가 크게 표시됩니다.")
        preview_hint.setStyleSheet(helper_text_style)

        self.preview_image_label = QLabel("생성 결과가 여기 표시됩니다.")
        self.preview_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_stage = QWidget()
        self.preview_stage.setStyleSheet(
            f"QWidget {{ background-color: #141B24; border: 1px solid #334155; border-radius: {get_scaled_size(6)}px; }}"
        )
        preview_stage_layout = QVBoxLayout(self.preview_stage)
        preview_stage_layout.setContentsMargins(get_scaled_size(1), get_scaled_size(1), get_scaled_size(1), get_scaled_size(1))
        preview_stage_layout.setSpacing(0)
        self.preview_image_label.setStyleSheet(
            f"QLabel {{ background-color: transparent; border: none; color: {DARK_COLORS['text_secondary']}; }}"
        )
        preview_stage_layout.addWidget(self.preview_image_label, stretch=1)

        preview_layout.addWidget(self.preview_stage, stretch=1)

        result_frame = QFrame()
        result_frame.setStyleSheet(panel_style)
        result_layout = QVBoxLayout(result_frame)
        result_layout.setContentsMargins(get_scaled_size(16), get_scaled_size(16), get_scaled_size(16), get_scaled_size(16))
        result_layout.setSpacing(get_scaled_size(10))

        result_title = QLabel("생성 결과 목록")
        result_title.setStyleSheet(section_title_style)
        result_hint = QLabel("클릭해서 큰 미리보기로 확인하고 원하는 이미지만 저장합니다.")
        result_hint.setStyleSheet(helper_text_style)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(
            f"QScrollArea {{ border: none; background-color: {DARK_COLORS['bg_primary']}; }}"
        )
        scroll_area.viewport().setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")

        self.grid_container = QWidget()
        self.grid_container.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.grid_layout.setSpacing(get_scaled_size(10))
        scroll_area.setWidget(self.grid_container)

        result_layout.addWidget(result_title)
        result_layout.addWidget(result_hint)
        result_layout.addWidget(scroll_area, stretch=1)

        left_column = QWidget()
        left_column_layout = QVBoxLayout(left_column)
        left_column_layout.setContentsMargins(0, 0, 0, 0)
        left_column_layout.setSpacing(get_scaled_size(14))
        left_column_layout.addWidget(left_panel)
        left_column_layout.addWidget(result_frame, stretch=1)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(get_scaled_size(14))
        content_row.addWidget(left_column, stretch=1)
        content_row.addWidget(self.preview_frame, stretch=0)

        layout.addLayout(content_row, stretch=1)
        self._resize_preview_surface()

    def _iter_character_widgets(self):
        character_tab = getattr(self.temp_window, "character_tab", None)
        if not character_tab:
            return []
        return getattr(character_tab, "character_widgets", [])

    def _load_initial_character_values(self):
        """Load the first checked character prompt/UC from top to bottom."""
        for widget in self._iter_character_widgets():
            checkbox = getattr(widget, "active_checkbox", None)
            if checkbox and checkbox.isChecked():
                self.prompt_edit.setPlainText(widget.prompt_textbox.toPlainText().strip())
                self.uc_edit.setPlainText(widget.uc_textbox.toPlainText().strip())
                return

        for widget in self._iter_character_widgets():
            prompt_text = widget.prompt_textbox.toPlainText().strip()
            uc_text = widget.uc_textbox.toPlainText().strip()
            if prompt_text or uc_text:
                self.prompt_edit.setPlainText(prompt_text)
                self.uc_edit.setPlainText(uc_text)
                return

    def _start_generation(self):
        """Start a new sequential asset generation run."""
        if self.is_generating:
            return

        prompt_text = self.prompt_edit.toPlainText().strip()
        if not prompt_text:
            QMessageBox.warning(self, "프롬프트 비어 있음", "캐릭터 프롬프트를 먼저 입력해주세요.")
            return

        self.pending_count = self.count_spinbox.value()
        self.stop_requested = False
        self.active_request_id = uuid.uuid4().hex
        self.status_label.setText(f"생성 시작: {self.pending_count}회")
        self._dispatch_next_generation()

    def _stop_generation(self):
        """Stop after the current request completes."""
        self.stop_requested = True
        self.pending_count = 0
        self.status_label.setText("중지 요청됨")

    def _dispatch_next_generation(self):
        """Dispatch the next character-asset generation request through the temp window pipeline."""
        if self.stop_requested:
            self.is_generating = False
            return

        try:
            params = self.temp_window.build_c1_asset_generation_params(
                self.active_request_id,
                prompt_override=self.prompt_edit.toPlainText().strip(),
                uc_override=self.uc_edit.toPlainText().strip(),
            )
        except Exception as exc:
            self.is_generating = False
            QMessageBox.warning(self, "에셋 생성 실패", str(exc))
            self.status_label.setText(f"실패: {exc}")
            return

        self.is_generating = True
        self.status_label.setText(f"생성 요청 중... 남은 예약 {self.pending_count}회")
        self.temp_window.generate_requested.emit(self.temp_window.window_id, params)

    def _on_asset_generation_completed(self, result: dict):
        """Receive completed asset results from the main generation pipeline."""
        generation_params = (result or {}).get("generation_params", {})
        request_id = generation_params.get("character_asset_request_id")
        if not self.active_request_id or request_id != self.active_request_id:
            return

        self.is_generating = False
        self._append_result(result)

        if self.pending_count > 0:
            self.pending_count -= 1

        should_continue = self.continue_checkbox.isChecked() or self.pending_count > 0
        if should_continue and not self.stop_requested:
            QTimer.singleShot(0, self._dispatch_next_generation)
        else:
            self.status_label.setText("생성 완료")

    def _on_asset_generation_error(self, error_data: dict):
        """Handle a failed asset-generation request without affecting other pipelines."""
        if not isinstance(error_data, dict):
            return
        if not error_data.get("character_asset_request"):
            return

        request_id = error_data.get("character_asset_request_id")
        if not self.active_request_id or request_id != self.active_request_id:
            return

        error_message = str(error_data.get("message") or "알 수 없는 오류")
        self.is_generating = False
        self.stop_requested = True
        self.pending_count = 0
        self.status_label.setText(f"실패: {error_message}")
        self._show_toast("에셋 생성 실패", "red", duration_ms=2600)

    def _append_result(self, result: dict):
        """Append a new result tile to the internal grid."""
        card = CharacterAssetResultCard(result, len(self.result_cards) + 1, self)
        card.clicked.connect(self._on_card_selected)
        row = len(self.result_cards) // 5
        col = len(self.result_cards) % 5
        self.grid_layout.addWidget(card, row, col)
        self.result_cards.append(card)
        self._on_card_selected(card)
        self.status_label.setText(f"결과 누적: {len(self.result_cards)}개")

    def _update_preview(self, result_data: dict):
        image = (result_data or {}).get("image")
        if image is None:
            self._preview_source_image = None
            self.preview_image_label.setPixmap(QPixmap())
            self.preview_image_label.setText("생성 결과가 여기 표시됩니다.")
            return

        self._preview_source_image = image.copy()
        self._render_preview()

    def _render_preview(self):
        if self._preview_source_image is None:
            return

        preview = self._preview_source_image.copy()
        if preview.mode != "RGBA":
            preview = preview.convert("RGBA")

        max_width = max(self.preview_image_label.width() - get_scaled_size(4), get_scaled_size(260))
        max_height = max(self.preview_image_label.height() - get_scaled_size(4), get_scaled_size(420))
        preview.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        pixmap = QPixmap.fromImage(ImageQt(preview))
        self.preview_image_label.setText("")
        self.preview_image_label.setPixmap(pixmap)

    def _resize_preview_surface(self):
        """Keep the preview surface portrait-shaped to reduce unused letterboxing."""
        if not hasattr(self, "preview_frame") or not hasattr(self, "preview_stage") or not hasattr(self, "preview_image_label"):
            return

        outer_margin = get_scaled_size(4)
        inner_margin = get_scaled_size(1)
        minimum_image_height = get_scaled_size(420)
        minimum_image_width = int(round(minimum_image_height * 768 / 1344))

        available_height = max(
            self.preview_frame.height() - (outer_margin * 2) - (inner_margin * 2),
            minimum_image_height,
        )
        image_height = available_height
        image_width = max(int(round(image_height * 768 / 1344)), minimum_image_width)

        frame_width = image_width + (outer_margin * 2) + (inner_margin * 2)
        self.preview_frame.setFixedWidth(frame_width)
        self.preview_image_label.setFixedSize(image_width, image_height)

    def _sync_preview_layout(self):
        self._resize_preview_surface()
        if self._preview_source_image is not None:
            self._render_preview()

    def _on_card_selected(self, card: CharacterAssetResultCard):
        """Select a result tile."""
        if self.selected_card:
            self.selected_card.set_selected(False)
        self.selected_card = card
        self.selected_card.set_selected(True)
        self._update_preview(card.result_data)

    def _save_selected_asset(self):
        """Save the currently selected result into Character Asset storage."""
        if not self.selected_card:
            QMessageBox.information(self, "저장할 에셋 없음", "먼저 저장할 결과를 선택해주세요.")
            return

        result = self.selected_card.result_data
        raw_bytes = result.get("raw_bytes") or result.get("image_bytes")
        image = result.get("image")

        try:
            image_path, _metadata = save_character_asset(
                raw_bytes=raw_bytes,
                image=image,
            )
        except Exception as exc:
            QMessageBox.critical(self, "저장 실패", str(exc))
            return

        self.status_label.setText(f"저장 완료: {image_path}")
        self._show_toast("에셋을 저장했습니다.", "green", duration_ms=2200)

    def _show_toast(self, message: str, color: str = "blue", duration_ms: int = 1600):
        """Show a styled in-window toast that disappears automatically."""
        if not hasattr(self, '_toast_label'):
            self._toast_label = QLabel(self)
            self._toast_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._toast_label.setWordWrap(True)
            self._toast_label.setVisible(False)

            self._toast_timer = QTimer(self)
            self._toast_timer.setSingleShot(True)
            self._toast_timer.timeout.connect(lambda: self._toast_label.setVisible(False))

        bg = self._TOAST_COLORS.get(color, self._TOAST_COLORS["blue"])
        self._toast_label.setStyleSheet(f"""
            QLabel {{
                background-color: {bg};
                color: white;
                font-size: {get_scaled_font_size(15)}px;
                font-weight: 600;
                padding: {get_scaled_size(10)}px {get_scaled_size(18)}px;
                border-radius: {get_scaled_size(8)}px;
                border: 1px solid rgba(255, 255, 255, 0.08);
            }}
        """)
        self._toast_label.setMaximumWidth(get_scaled_size(360))
        self._toast_label.setText(message)
        self._toast_label.adjustSize()

        x = self.width() - self._toast_label.width() - get_scaled_size(24)
        y = get_scaled_size(24)
        self._toast_label.move(max(get_scaled_size(16), x), y)
        self._toast_label.setVisible(True)
        self._toast_label.raise_()
        self._toast_timer.start(duration_ms)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._sync_preview_layout)
        if hasattr(self, '_toast_label') and self._toast_label.isVisible():
            x = self.width() - self._toast_label.width() - get_scaled_size(24)
            self._toast_label.move(max(get_scaled_size(16), x), get_scaled_size(24))

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._sync_preview_layout)

    def closeEvent(self, event):
        if getattr(self, "app_context", None) and hasattr(self.app_context, "unsubscribe"):
            self.app_context.unsubscribe(self._completed_event_name, self._on_asset_generation_completed)
            self.app_context.unsubscribe(self._error_event_name, self._on_asset_generation_error)
        super().closeEvent(event)
