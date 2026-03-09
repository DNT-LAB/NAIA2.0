import os
import json
import math
import time
from dataclasses import dataclass, field
from typing import Dict, Any
from io import BytesIO
from pathlib import Path
import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTextEdit, QSplitter, QPushButton,
    QHBoxLayout, QCheckBox, QScrollArea, QMenu, QDialog, QFileDialog, QMessageBox, QApplication,
    QSpinBox, QRadioButton, QButtonGroup, QFrame, QSlider
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QObject, QThread, QTimer, QMimeData, QUrl
from PyQt6.QtGui import QPixmap, QMouseEvent, QPainter, QColor, QAction, QKeyEvent, QDragEnterEvent, QDropEvent, QCursor
from PyQt6.QtWidgets import QWidgetAction
from PIL import Image, ImageQt
from ui.theme import DARK_STYLES, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from interfaces.base_tab_module import BaseTabModule
from ui.img2img_popup import Img2ImgPopup
from ui.metadata_viewer import MetadataViewerWindow
from utils.image_info import ImageMetadataExtractor
import piexif, io
import requests
import tempfile

class ImageViewerModule(BaseTabModule):
    """'생성 결과' 탭을 위한 모듈"""

    def __init__(self):
        super().__init__()
        self.image_window_widget: ImageWindow = None

    def get_tab_title(self) -> str:
        return "🖼️ 생성 결과"
        
    def get_tab_order(self) -> int:
        # 가장 먼저 보여야 하므로 낮은 숫자를 부여
        return 1

    def create_widget(self, parent: QWidget) -> QWidget:
        if self.image_window_widget is None:
            self.image_window_widget = ImageWindow(self.app_context, parent)
            
            # ImageWindow의 시그널들을 BaseTabModule의 시그널이나 RightView로 전달
            # 이 로직은 추후 RightView 리팩토링 시 TabController로 이동될 수 있습니다.
            self.image_window_widget.load_prompt_to_main_ui.connect(
                self.app_context.main_window.set_positive_prompt
            )
            self.image_window_widget.instant_generation_requested.connect(
                self.app_context.main_window.on_instant_generation_requested
            )
            
        return self.image_window_widget

class AllImagesDownloader(QObject):
    """[리팩토링] ImageCrudController를 사용하는 일괄 저장 워커"""
    # 진행률 시그널: (현재 순번, 전체 개수, 파일명/메시지)
    progress_updated = pyqtSignal(int, int, str)
    # 완료 시그널: (실제로 저장된 파일 개수)
    finished = pyqtSignal(int)

    def __init__(self, image_crud_controller):
        super().__init__()
        self.image_crud = image_crud_controller

    def run(self, history_items, save_as_webp):
        """
        백그라운드 스레드에서 실행될 이미지 저장 로직

        Parameters:
            history_items (list): 저장할 HistoryItem 리스트
            save_as_webp (bool): WEBP 형식으로 저장 여부
        """
        saved_count = 0
        total_items = len(history_items)

        for i, item in enumerate(history_items):
            try:
                # 1. 이미 저장되었는지 파일 경로와 실제 파일 존재 여부로 확인
                if item.filepath and os.path.exists(item.filepath):
                    self.progress_updated.emit(i + 1, total_items, f"[건너뜀] {os.path.basename(item.filepath)}")
                    continue

                # 2. 저장할 원본 데이터가 없으면 건너뜀
                if not item.raw_bytes:
                    self.progress_updated.emit(i + 1, total_items, "[건너뜀] 원본 데이터 없음")
                    continue

                # 3. 🆕 분류 정보 생성
                classification_info = {
                    "method": self.image_crud.get_classification_method(),
                    "prompt": item.info_text,
                    "image_size": item.image.size if item.image else (0, 0),
                    "tags": item.prompt_context.get("main_tags", []) if isinstance(item.prompt_context, dict) else [],
                    "backend_type": item.backend_type,
                }

                # 4. ✅ ImageCrudController를 통한 저장 (분류 정보 포함)
                success, filepath, error = self.image_crud.save_image(
                    image_bytes=item.raw_bytes,
                    as_webp=save_as_webp,
                    classification_info=classification_info
                )

                if success:
                    # HistoryItem 객체에 저장 경로 업데이트 (중복 저장 방지용)
                    item.filepath = filepath
                    saved_count += 1
                    self.progress_updated.emit(i + 1, total_items, f"[저장됨] {os.path.basename(filepath)}")
                else:
                    self.progress_updated.emit(i + 1, total_items, f"[오류] {error}")

            except Exception as e:
                self.progress_updated.emit(i + 1, total_items, f"[오류] {e}")

        self.finished.emit(saved_count)


class EnhanceSettingsDialog(QDialog):
    """Enhance 설정 다이얼로그 — Upscale Amount, Strength, Magnitude 프리셋"""

    def __init__(self, current_upscale: float, current_strength: float, current_noise: float = 0.0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Enhance Settings")
        self.setModal(True)
        self.setFixedWidth(get_scaled_size(340))

        self._upscale = current_upscale
        self._strength = current_strength
        self._noise = current_noise

        self._build_ui()
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)

    # ── UI 구성 ──────────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(get_scaled_size(10))

        label_style = f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(13)}px; font-weight: bold;"

        # ── Upscale Amount ──
        layout.addWidget(self._make_label("Upscale Amount", label_style))

        upscale_row = QHBoxLayout()
        self._btn_1x = QPushButton("1x")
        self._btn_15x = QPushButton("1.5x")
        for btn, val in [(self._btn_1x, 1.0), (self._btn_15x, 1.5)]:
            btn.setCheckable(True)
            btn.setChecked(self._upscale == val)
            btn.clicked.connect(lambda checked, v=val: self._set_upscale(v))
            btn.setStyleSheet(self._toggle_style(self._upscale == val))
            upscale_row.addWidget(btn)
        layout.addLayout(upscale_row)

        # ── Strength ──
        strength_header = QHBoxLayout()
        strength_header.addWidget(self._make_label("Strength", label_style))
        self._strength_value_label = QLabel(f"{self._strength:.1f}")
        self._strength_value_label.setStyleSheet(f"color: {DARK_COLORS['accent_purple_light']}; font-size: {get_scaled_font_size(13)}px; font-weight: bold;")
        self._strength_value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        strength_header.addWidget(self._strength_value_label)
        layout.addLayout(strength_header)

        self._strength_slider = QSlider(Qt.Orientation.Horizontal)
        self._strength_slider.setRange(1, 9)
        self._strength_slider.setValue(int(self._strength * 10))
        self._strength_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._strength_slider.setTickInterval(1)
        self._strength_slider.setStyleSheet(DARK_STYLES.get('compact_slider', ''))
        self._strength_slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self._strength_slider)

        # ── Magnitude Presets ──
        layout.addWidget(self._make_label("Magnitude Presets", label_style))

        mag_row = QHBoxLayout()
        presets = [(1, 0.2, 0.0), (2, 0.3, 0.0), (3, 0.4, 0.0), (4, 0.5, 0.0), (5, 0.7, 0.1)]
        for num, strength, noise in presets:
            btn = QPushButton(str(num))
            btn.setFixedSize(get_scaled_size(42), get_scaled_size(32))
            btn.setStyleSheet(self._magnitude_style())
            btn.clicked.connect(lambda checked, s=strength, n=noise: self._apply_preset(s, n))
            mag_row.addWidget(btn)
        layout.addLayout(mag_row)

        # ── OK / Cancel ──
        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_purple']};
                color: white; border: none; border-radius: 4px;
                padding: {get_scaled_size(6)}px {get_scaled_size(16)}px;
                font-size: {get_scaled_font_size(13)}px;
            }}
            QPushButton:hover {{ background-color: {DARK_COLORS['accent_purple_hover']}; }}
        """)
        ok_btn.clicked.connect(self.accept)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        cancel_btn.clicked.connect(self.reject)

        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

    # ── 헬퍼 ────────────────────────────────────────────────
    @staticmethod
    def _make_label(text: str, style: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(style)
        return lbl

    def _toggle_style(self, selected: bool) -> str:
        if selected:
            return f"""
                QPushButton {{
                    background-color: {DARK_COLORS['accent_purple']};
                    color: white; border: none; border-radius: 4px;
                    padding: {get_scaled_size(6)}px {get_scaled_size(14)}px;
                    font-size: {get_scaled_font_size(13)}px; font-weight: bold;
                }}
                QPushButton:hover {{ background-color: {DARK_COLORS['accent_purple_hover']}; }}
            """
        return f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_secondary']}; border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px; padding: {get_scaled_size(6)}px {get_scaled_size(14)}px;
                font-size: {get_scaled_font_size(13)}px;
            }}
            QPushButton:hover {{ background-color: {DARK_COLORS['bg_hover']}; }}
        """

    @staticmethod
    def _magnitude_style() -> str:
        return f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']}; border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px; font-size: {get_scaled_font_size(13)}px; font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_purple']};
                color: white; border: 1px solid {DARK_COLORS['accent_purple']};
            }}
        """

    # ── 슬롯 ────────────────────────────────────────────────
    def _set_upscale(self, value: float):
        self._upscale = value
        self._btn_1x.setChecked(value == 1.0)
        self._btn_15x.setChecked(value == 1.5)
        self._btn_1x.setStyleSheet(self._toggle_style(value == 1.0))
        self._btn_15x.setStyleSheet(self._toggle_style(value == 1.5))

    def _on_slider_changed(self, val: int):
        self._strength = val / 10.0
        self._strength_value_label.setText(f"{self._strength:.1f}")

    def _apply_preset(self, strength: float, noise: float = 0.0):
        self._strength = strength
        self._noise = noise
        self._strength_slider.setValue(int(strength * 10))

    # ── 결과 ────────────────────────────────────────────────
    def get_settings(self) -> tuple:
        """(upscale, strength, noise) 튜플 반환"""
        return self._upscale, self._strength, self._noise


# --- 1. ImageLabel 클래스: 오직 이미지 표시와 리사이징만 담당 ---
class ImageLabel(QLabel):
    # 드래그&드롭으로 이미지를 받았을 때 발생하는 시그널
    image_dropped = pyqtSignal(Image.Image)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(1, 1)
        self.full_pixmap = None
        # 드래그&드롭 활성화
        self.setAcceptDrops(True)

    def setFullPixmap(self, pixmap: QPixmap | None):
        """원본 QPixmap을 저장하고, 첫 리사이징을 트리거합니다."""
        self.full_pixmap = pixmap
        # 위젯의 현재 크기에 맞춰 이미지 업데이트
        self.resizeEvent(None) 
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        """드래그가 들어왔을 때 이벤트 처리"""
        mime_data = event.mimeData()
        
        # 이미지 파일이나 URL을 받을 수 있는지 확인
        if mime_data.hasImage() or mime_data.hasUrls():
            # URL이 있는 경우 이미지 파일인지 확인
            if mime_data.hasUrls():
                for url in mime_data.urls():
                    file_path = url.toLocalFile()
                    if file_path and file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp')):
                        event.acceptProposedAction()
                        return
                    # 웹 URL인 경우도 처리
                    if url.scheme() in ['http', 'https']:
                        event.acceptProposedAction()
                        return
            # 직접 이미지 데이터가 있는 경우
            elif mime_data.hasImage():
                event.acceptProposedAction()
    
    def dropEvent(self, event: QDropEvent):
        """드롭 이벤트 처리"""
        mime_data = event.mimeData()
        pil_image = None
        
        try:
            # URL 처리 (파일 경로 또는 웹 URL)
            if mime_data.hasUrls():
                for url in mime_data.urls():
                    file_path = url.toLocalFile()
                    
                    # 로컬 파일인 경우
                    if file_path and os.path.exists(file_path):
                        pil_image = Image.open(file_path)
                        break
                    
                    # 웹 URL인 경우
                    elif url.scheme() in ['http', 'https']:
                        # URL에서 이미지 다운로드
                        response = requests.get(url.toString(), timeout=10)
                        if response.status_code == 200:
                            pil_image = Image.open(BytesIO(response.content))
                        break
            
            # 직접 이미지 데이터가 있는 경우
            elif mime_data.hasImage():
                qimage = mime_data.imageData()
                if qimage:
                    # QImage를 PIL Image로 변환
                    buffer = BytesIO()
                    qimage.save(buffer, "PNG")
                    buffer.seek(0)
                    pil_image = Image.open(buffer)
            
            # 이미지를 성공적으로 로드했으면 시그널 발생
            if pil_image:
                self.image_dropped.emit(pil_image)
                event.acceptProposedAction()
            
        except Exception as e:
            print(f"Failed to process dropped image: {e}")
            event.ignore()

    def resizeEvent(self, event):
        """위젯의 크기가 변경될 때마다 호출되는 이벤트 핸들러"""
        if self.full_pixmap is None:
            # Pixmap이 없으면, 초기 텍스트를 다시 설정
            self.setText("Generated Image")
            return

        scaled_pixmap = self.full_pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.setPixmap(scaled_pixmap)

@dataclass
class HistoryItem:
    image: Image.Image
    thumbnail: QPixmap
    info_text: str
    source_row: pd.Series
    raw_bytes: bytes | None = None
    filepath: str | None = None 
    metadata: Dict[str, Any] = field(default_factory=dict)
    comfyui_workflow: Dict[str, Any] = field(default_factory=dict)  # 🆕 ComfyUI 워크플로우 정보
    
    # 🆕 확장된 메타데이터 필드들
    generation_params: Dict[str, Any] = field(default_factory=dict)  # UI에서 수집된 모든 파라미터
    prompt_context: Dict[str, Any] = field(default_factory=dict)      # 프롬프트 처리 과정 정보
    api_metadata: Dict[str, Any] = field(default_factory=dict)        # API 응답 메타데이터
    creation_timestamp: str = field(default='')                       # 생성 시각
    backend_type: str = field(default='NAI')                          # NAI/WEBUI/COMFYUI

class ImageHistoryWindow(QWidget):
    """이미지 히스토리 패널"""
    history_item_selected = pyqtSignal(HistoryItem)
    load_prompt_requested = pyqtSignal(str)
    reroll_requested = pyqtSignal(pd.Series)
    history_cleared = pyqtSignal()
    save_to_remote_event_requested = pyqtSignal(HistoryItem)  # 🆕 리모트 이벤트 저장 시그널

    def __init__(self, parent=None):
        super().__init__(parent)
        self.history_widgets: list[HistoryItemWidget] = []
        self.current_selected_widget: HistoryItemWidget | None = None
        self.init_ui()

    def init_ui(self):
        # [수정] 메인 레이아웃 및 제목 추가
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 0, 0, 4)
        main_layout.setSpacing(4)

        # [신규] 히스토리 제목 레이블
        title_label = QLabel("📜 히스토리")
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
                padding: 4px;
            }}
        """)
        main_layout.addWidget(title_label)
        
        # [수정] 스크롤 영역 스타일 개선
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: #212121;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
            QScrollBar:vertical {{
                background-color: {DARK_COLORS['bg_secondary']};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {DARK_COLORS['border_light']};
                border-radius: 4px;
                min-height: 20px;
            }}
        """)
        
        container = QWidget()
        # [수정] 컨테이너 배경을 투명하게 하여 스크롤 영역의 배경색이 보이도록 함
        container.setStyleSheet("background-color: transparent;")
        
        self.history_layout = QVBoxLayout(container)
        self.history_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.history_layout.setContentsMargins(4, 4, 4, 4)
        self.history_layout.setSpacing(4)
        
        scroll_area.setWidget(container)
        main_layout.addWidget(scroll_area)

    def add_history_item(self, history_item: HistoryItem):
        """새로운 히스토리 아이템을 받아 위젯을 생성하고 목록 최상단에 추가"""
        # app_context를 찾기 위해 부모 체인을 탐색
        app_context = None
        parent_widget = self.parent()
        while parent_widget:
            if hasattr(parent_widget, 'app_context'):
                app_context = parent_widget.app_context
                break
            parent_widget = parent_widget.parent()
        
        item_widget = HistoryItemWidget(history_item, parent=None, app_context=app_context)
        item_widget.item_selected.connect(self.on_item_selected)
        item_widget.delete_requested.connect(self.on_item_delete_requested)

        item_widget.select_previous_requested.connect(self.select_previous_item)
        item_widget.select_next_requested.connect(self.select_next_item)
        # [추가] HistoryItemWidget의 시그널을 ImageHistoryWindow의 시그널에 연결
        item_widget.load_prompt_requested.connect(self.load_prompt_requested)
        item_widget.reroll_requested.connect(self.reroll_requested)
        item_widget.save_to_remote_event_requested.connect(self.save_to_remote_event_requested)  # 🆕

        # 새 아이템을 레이아웃의 맨 위에 추가
        self.history_layout.insertWidget(0, item_widget)
        self.history_widgets.insert(0, item_widget)
        
        # 새로 추가된 아이템을 선택 상태로 만듦
        self.on_item_selected(history_item, "generated")

    def on_item_selected(self, history_item: HistoryItem, _message = None):
        """히스토리 아이템이 선택되었을 때 처리"""
        # 이전에 선택된 위젯의 선택 상태 해제
        if self.current_selected_widget:
            self.current_selected_widget.set_selected(False)

        # 새로 선택된 위젯 찾아서 선택 상태로 변경
        for widget in self.history_widgets:
            if widget.history_item == history_item:
                widget.set_selected(True)
                self.current_selected_widget = widget
                if _message != "generated": widget.setFocus()
                break
        
        # 상위 위젯(ImageWindow)으로 선택된 아이템 정보 전달
        self.history_item_selected.emit(history_item)

    def remove_current_item(self):
        if not self.current_selected_widget:
            return False
        idx = self.history_widgets.index(self.current_selected_widget)
        widget_to_remove = self.current_selected_widget

        self.history_widgets.remove(widget_to_remove)
        self.history_layout.removeWidget(widget_to_remove)
        widget_to_remove.deleteLater()
        self.current_selected_widget = None

        # ↓ 삭제 후 아래(또는 위) 자동 선택
        if self.history_widgets:
            next_idx = min(idx, len(self.history_widgets)-1)
            self.select_item_by_idx(next_idx)
        else:
            self.history_cleared.emit()
        return True

    def select_item_by_idx(self, idx):
        if 0 <= idx < len(self.history_widgets):
            self.on_item_selected(self.history_widgets[idx].history_item)

    def on_item_delete_requested(self, widget_to_remove):
        """히스토리 컨텍스트 메뉴의 삭제 요청을 처리합니다."""
        if widget_to_remove not in self.history_widgets:
            return

        is_current = (self.current_selected_widget == widget_to_remove)
        
        try:
            idx = self.history_widgets.index(widget_to_remove)
        except ValueError:
            return

        self.history_widgets.pop(idx)
        self.history_layout.removeWidget(widget_to_remove)
        widget_to_remove.deleteLater()

        # 삭제된 아이템이 현재 선택된 아이템이었을 경우 후처리
        if is_current:
            self.current_selected_widget = None
            if self.history_widgets:
                # 다음 아이템 자동 선택
                next_idx = min(idx, len(self.history_widgets) - 1)
                self.select_item_by_idx(next_idx)
            else:
                # 히스토리가 비었음을 알림
                self.history_cleared.emit()

    # [추가] 키보드 네비게이션을 처리하는 슬롯 메서드들
    def get_current_index(self) -> int:
        """현재 선택된 위젯의 인덱스를 반환합니다."""
        if self.current_selected_widget and self.current_selected_widget in self.history_widgets:
            return self.history_widgets.index(self.current_selected_widget)
        return -1

    def select_previous_item(self):
        """이전 아이템을 선택합니다."""
        current_idx = self.get_current_index()
        if current_idx > 0:  # 첫 번째 아이템이 아닐 경우에만
            self.select_item_by_idx(current_idx - 1)

    def select_next_item(self):
        """다음 아이템을 선택합니다."""
        current_idx = self.get_current_index()
        # 마지막 아이템이 아닐 경우에만
        if current_idx != -1 and current_idx < len(self.history_widgets) - 1:
            self.select_item_by_idx(current_idx + 1)

    # [신규] 메인 뷰를 업데이트하지 않고 모든 히스토리를 정리하는 메서드
    def clear_all_items(self):
        """UI 갱신 없이 모든 히스토리 아이템을 제거합니다."""
        for widget in self.history_widgets[:]: # 리스트 복사본으로 순회
            self.history_layout.removeWidget(widget)
            widget.deleteLater()
        
        self.history_widgets.clear()
        self.current_selected_widget = None
        self.history_cleared.emit() # 마지막에 한 번만 신호를 보내 메인 뷰 정리

# [신규] 히스토리 목록의 개별 항목을 표시하는 위젯
class HistoryItemWidget(QWidget):
    # 위젯이 클릭되었을 때 HistoryItem 객체를 전달하는 시그널
    load_prompt_requested = pyqtSignal(str)
    reroll_requested = pyqtSignal(pd.Series)
    item_selected = pyqtSignal(HistoryItem)
    delete_requested = pyqtSignal(object)
    select_previous_requested = pyqtSignal()
    select_next_requested = pyqtSignal()
    save_to_remote_event_requested = pyqtSignal(HistoryItem)  # 🆕 리모트 이벤트 저장 시그널

    def __init__(self, history_item: HistoryItem, parent=None, app_context=None):
        super().__init__(parent)
        self.history_item = history_item
        self.app_context = app_context
        self.is_selected = False
        self.init_ui()
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setPixmap(self.history_item.thumbnail)
        self.thumbnail_label.setScaledContents(True)
        self.thumbnail_label.setFixedSize(128, 128) # 썸네일 크기 고정
        
        layout.addWidget(self.thumbnail_label)
        self.update_selection_style()

    def keyPressEvent(self, event: QKeyEvent):
        """키보드 방향키 입력을 감지하여 시그널을 발생시킵니다."""
        if event.key() == Qt.Key.Key_Up:
            self.select_previous_requested.emit()
            event.accept()
        elif event.key() == Qt.Key.Key_Down:
            self.select_next_requested.emit()
            event.accept()
        elif event.key() == Qt.Key.Key_Delete:  # [추가] Delete 키 감지
            self.delete_requested.emit(self)    # [추가] 기존 삭제 시그널 호출
            event.accept()
        else:
            # 다른 키 입력은 기본 이벤트 핸들러에 전달
            super().keyPressEvent(event)

    def show_context_menu(self, pos):
        """우클릭 시 컨텍스트 메뉴를 표시합니다."""
        menu = QMenu(self)
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
            QMenu::separator {{
                height: 1px;
                background-color: {DARK_COLORS['border']};
                margin: 5px 0px;
            }}
        """
        menu.setStyleSheet(menu_style)
        
        # "프롬프트 불러오기" 액션
        load_action = QAction("프롬프트 불러오기", self)
        load_action.triggered.connect(self.emit_load_prompt)
        menu.addAction(load_action)
        
        # "프롬프트 다시개봉" 액션
        reroll_action = QAction("프롬프트 다시개봉", self)
        # source_row가 없는 경우 비활성화
        if self.history_item.source_row is None or self.history_item.source_row.empty:
            reroll_action.setEnabled(False)
        reroll_action.triggered.connect(self.emit_reroll_prompt)
        menu.addAction(reroll_action)

        # 🆕 큐 추가 서브메뉴
        menu.addSeparator()
        has_gen_params = hasattr(self.history_item, 'generation_params') and self.history_item.generation_params

        enqueue_front_menu = QMenu("⬆️ 큐 앞에 추가", self)
        enqueue_front_menu.setStyleSheet(menu_style)
        front_original = QAction("원본 프롬프트 유지", self)
        front_original.triggered.connect(lambda: self._enqueue_history_item(priority=100, use_current_ui=False))
        front_current = QAction("현재 UI 프롬프트 반영", self)
        front_current.triggered.connect(lambda: self._enqueue_history_item(priority=100, use_current_ui=True))
        enqueue_front_menu.addAction(front_original)
        enqueue_front_menu.addAction(front_current)
        if not has_gen_params:
            enqueue_front_menu.setEnabled(False)
        menu.addMenu(enqueue_front_menu)

        enqueue_back_menu = QMenu("⬇️ 큐 뒤에 추가", self)
        enqueue_back_menu.setStyleSheet(menu_style)
        back_original = QAction("원본 프롬프트 유지", self)
        back_original.triggered.connect(lambda: self._enqueue_history_item(priority=0, use_current_ui=False))
        back_current = QAction("현재 UI 프롬프트 반영", self)
        back_current.triggered.connect(lambda: self._enqueue_history_item(priority=0, use_current_ui=True))
        enqueue_back_menu.addAction(back_original)
        enqueue_back_menu.addAction(back_current)
        if not has_gen_params:
            enqueue_back_menu.setEnabled(False)
        menu.addMenu(enqueue_back_menu)

        # 🆕 메타데이터 복원 메뉴 추가
        menu.addSeparator()
        restore_params_action = QAction("⚙️ 생성 설정 복원", self)
        # 생성 파라미터가 있는 경우에만 활성화
        if (hasattr(self.history_item, 'generation_params') and 
            self.history_item.generation_params):
            restore_params_action.triggered.connect(self.restore_generation_params)
        else:
            restore_params_action.setEnabled(False)
        menu.addAction(restore_params_action)
        
        show_metadata_action = QAction("🔍 전체 메타데이터 보기", self)
        show_metadata_action.triggered.connect(self.show_full_metadata)
        menu.addAction(show_metadata_action)
        
        copy_png_action = QAction("PNG로 클립보드 복사", self)
        copy_webp_action = QAction("WEBP로 클립보드 복사", self)
        copy_png_action.triggered.connect(lambda: self.copy_image_to_clipboard('PNG'))
        copy_webp_action.triggered.connect(lambda: self.copy_image_to_clipboard('WEBP'))
        menu.addAction(copy_png_action)
        menu.addAction(copy_webp_action)
        
        # NAI Upscale 메뉴 추가
        menu.addSeparator()
        upscale_action = QAction("🔍 NAI 2x 업스케일", self)
        upscale_action.triggered.connect(self.upscale_image_nai)
        # NAI 모드가 아니면 비활성화
        if hasattr(self, 'app_context'):
            current_mode = self.app_context.get_api_mode() if self.app_context else None
            if current_mode != "NAI":
                upscale_action.setEnabled(False)
                upscale_action.setToolTip("NAI 모드에서만 사용 가능합니다")
        menu.addAction(upscale_action)
        
        # 🆕 리모트에 이벤트 저장 메뉴
        menu.addSeparator()
        save_to_remote_action = QAction("📌 리모트에 이벤트 저장", self)
        # source_row가 없는 경우 비활성화
        if self.history_item.source_row is None or self.history_item.source_row.empty:
            save_to_remote_action.setEnabled(False)
        save_to_remote_action.triggered.connect(self._emit_save_to_remote_event)
        menu.addAction(save_to_remote_action)

        menu.addSeparator()
        delete_action = QAction("🗑️ 이미지 삭제", self)
        delete_action.triggered.connect(lambda: self.delete_requested.emit(self))
        menu.addAction(delete_action)
        menu.exec(self.mapToGlobal(pos))

    def emit_load_prompt(self):
        """🆕 '프롬프트 불러오기' 시그널을 발생시킵니다 - main_prompt 우선 사용"""
        # 🆕 prompt_context의 main_prompt를 우선적으로 사용 (\n\n 포함 원본)
        if (hasattr(self.history_item, 'prompt_context') and 
            self.history_item.prompt_context and 
            'main_prompt' in self.history_item.prompt_context and
            self.history_item.prompt_context['main_prompt']):
            
            prompt_to_load = self.history_item.prompt_context['main_prompt']
            print(f"✅ 원본 프롬프트 불러오기 (main_prompt): {prompt_to_load[:50]}...")
            self.load_prompt_requested.emit(prompt_to_load)
            
        else:
            # 🔄 폴백: main_prompt가 없으면 기존 방식 사용
            info = self.history_item.info_text
            # Negative prompt 이전 부분만 추출
            positive_prompt = info.split('Negative prompt:')[0].strip()
            print(f"✅ 프롬프트 불러오기 (info_text 폴백): {positive_prompt[:50]}...")
            self.load_prompt_requested.emit(positive_prompt)

    def emit_reroll_prompt(self):
        """'프롬프트 다시개봉' 시그널을 발생시킵니다."""
        self.reroll_requested.emit(self.history_item.source_row)

    def _emit_save_to_remote_event(self):
        """🆕 '리모트에 이벤트 저장' 시그널을 발생시킵니다."""
        self.save_to_remote_event_requested.emit(self.history_item)

    def _enqueue_history_item(self, priority: int = 0, use_current_ui: bool = False):
        """히스토리 아이템을 생성 큐에 추가

        Args:
            priority: 0=일반(뒤), 100=긴급(앞)
            use_current_ui: True면 현재 UI의 프롬프트/캐릭터 반영, False면 원본 유지
        """
        try:
            if not self.app_context:
                return

            from core.generation_request import GenerationRequest
            import random
            import pandas as pd

            main_window = self.app_context.main_window

            if use_current_ui:
                # 현재 UI 상태로 파라미터 수집 (해상도/모델 등은 원본 유지, 프롬프트/캐릭터만 갱신)
                params = self.history_item.generation_params.copy()
                current_params = main_window.get_main_parameters()
                params['input'] = current_params.get('input', params.get('input', ''))
                params['negative_prompt'] = current_params.get('negative_prompt', params.get('negative_prompt', ''))
                # 캐릭터: 현재 UI 모듈에서 가져오기
                char_module = self.app_context.middle_section_controller.get_module_instance("CharacterModule")
                if char_module and hasattr(char_module, 'activate_checkbox') and char_module.activate_checkbox.isChecked():
                    char_params = char_module.get_parameters()
                    if char_params and char_params.get("characters"):
                        params['characters'] = char_params['characters']
                        params['uc'] = char_params['uc']
                        params['character_positions'] = char_params.get('character_positions', [])
                    else:
                        params.pop('characters', None)
                        params.pop('uc', None)
                        params.pop('character_positions', None)
                else:
                    params.pop('characters', None)
                    params.pop('uc', None)
                    params.pop('character_positions', None)
                mode_label = "현재 UI"
            else:
                # 원본 파라미터 그대로 사용
                params = self.history_item.generation_params.copy()
                mode_label = "원본"

            # 랜덤 해상도 체크
            if hasattr(main_window, 'random_resolution_checkbox') and main_window.random_resolution_checkbox:
                if main_window.random_resolution_checkbox.isChecked():
                    random_index = random.randint(0, main_window.resolution_combo.count() - 1)
                    selected_value = main_window.resolution_combo.itemText(random_index)
                    width, height = map(int, selected_value.split(' x '))
                    params['width'] = width
                    params['height'] = height

            # 시드 고정 체크 (체크되어 있지 않으면 무작위 시드 생성)
            if hasattr(main_window, 'seed_fix_checkbox') and main_window.seed_fix_checkbox:
                if not main_window.seed_fix_checkbox.isChecked():
                    random_seed = random.randint(0, 9999999999)
                    params['seed'] = random_seed
                    params['extra_noise_seed'] = random_seed

            # source_row 가져오기 (없으면 빈 Series)
            source_row = self.history_item.source_row if hasattr(self.history_item, 'source_row') and self.history_item.source_row is not None else pd.Series()

            request = GenerationRequest(
                params=params,
                source_row=source_row,
                priority=priority,
                max_retries=0
            )

            queue_manager = self.app_context.generation_queue_manager
            position_label = "앞" if priority > 0 else "뒤"

            if priority > 0:
                queue_manager.enqueue_with_priority(request)
            else:
                queue_manager.enqueue_request(request)

            queue_size = queue_manager.get_queue_size()
            if hasattr(main_window, 'status_bar'):
                main_window.status_bar.showMessage(
                    f"✅ 큐 {position_label}에 추가됨 [{mode_label}] (대기 중: {queue_size})", 3000
                )

        except Exception as e:
            pass

    def show_comfyui_workflow(self):
        """🆕 ComfyUI 워크플로우 정보를 보여주는 다이얼로그"""
        try:
            dialog = QDialog(self)
            dialog.setWindowTitle("ComfyUI 워크플로우 정보")
            dialog.setModal(True)
            dialog.resize(600, 400)
            
            layout = QVBoxLayout(dialog)
            
            # 워크플로우 정보 표시
            text_edit = QTextEdit()
            text_edit.setReadOnly(True)
            text_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
            
            # JSON을 보기 좋게 포맷
            formatted_text = ""
            for key, value in self.history_item.comfyui_workflow.items():
                formatted_text += f"=== {key} ===\n"
                if isinstance(value, dict):
                    formatted_text += json.dumps(value, indent=2, ensure_ascii=False)
                else:
                    formatted_text += str(value)
                formatted_text += " "
            
            text_edit.setPlainText(formatted_text)
            layout.addWidget(text_edit)
            
            # 버튼
            button_layout = QHBoxLayout()
            
            # 워크플로우 저장 버튼
            save_btn = QPushButton("워크플로우 저장")
            save_btn.setStyleSheet(DARK_STYLES['secondary_button'])
            save_btn.clicked.connect(lambda: self.save_comfyui_workflow())
            button_layout.addWidget(save_btn)
            
            # 닫기 버튼
            close_btn = QPushButton("닫기")
            close_btn.setStyleSheet(DARK_STYLES['secondary_button'])
            close_btn.clicked.connect(dialog.accept)
            button_layout.addWidget(close_btn)
            
            layout.addLayout(button_layout)
            
            dialog.exec()
            
        except Exception as e:
            print(f"❌ 워크플로우 다이얼로그 표시 실패: {e}")

    def save_comfyui_workflow(self):
        """🆕 ComfyUI 워크플로우를 파일로 저장"""
        try:
            if 'workflow' in self.history_item.comfyui_workflow:
                # 파일 저장 다이얼로그
                file_path, _ = QFileDialog.getSaveFileName(
                    self,
                    "ComfyUI 워크플로우 저장",
                    f"comfyui_workflow_{int(time.time())}.json",
                    "JSON Files (*.json)"
                )
                
                if file_path:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(self.history_item.comfyui_workflow['workflow'], f, indent=2, ensure_ascii=False)
                    
                    print(f"✅ 워크플로우 저장 완료: {file_path}")
            else:
                print("⚠️ 저장할 워크플로우 정보가 없습니다.")
                
        except Exception as e:
            print(f"❌ 워크플로우 저장 실패: {e}")
        
    def mousePressEvent(self, event: QMouseEvent):
        """위젯 클릭 시 item_selected 시그널 발생"""
        # [수정] 좌클릭 시에만 선택 시그널 발생
        if event.button() == Qt.MouseButton.LeftButton:
            self.item_selected.emit(self.history_item)
        super().mousePressEvent(event)

    def set_selected(self, selected: bool):
        """선택 상태 업데이트 및 스타일 변경"""
        self.is_selected = selected
        self.update_selection_style()

    def update_selection_style(self):
        """선택 상태에 따라 테두리 스타일 변경"""
        if self.is_selected:
            self.thumbnail_label.setStyleSheet(f"""
                QLabel {{ 
                    border: 2px solid {DARK_COLORS['accent_blue']}; 
                    border-radius: 4px;
                }}
            """)
        else:
            self.thumbnail_label.setStyleSheet("border: none;")

    def copy_image_to_clipboard(self, fmt='PNG'):
        from PyQt6.QtWidgets import QApplication
        import io
        pil_img = self.history_item.image
        buf = io.BytesIO()
        if fmt == 'PNG':
            pil_img.save(buf, format='PNG')
        else:
            pil_img.save(buf, format='WEBP', quality=90, method=6)
        buf.seek(0)
        qimg = QPixmap()
        qimg.loadFromData(buf.getvalue())
        QApplication.clipboard().setPixmap(qimg)
        print(f"✅ 이미지가 클립보드에 복사되었습니다. ({fmt})")
    
    def _show_styled_message(self, title, message, msg_type='warning'):
        """다크 테마 스타일이 적용된 QMessageBox를 표시합니다."""
        from PyQt6.QtWidgets import QMessageBox
        
        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(message)
        
        if msg_type == 'warning':
            msg.setIcon(QMessageBox.Icon.Warning)
        elif msg_type == 'critical':
            msg.setIcon(QMessageBox.Icon.Critical)
        elif msg_type == 'information':
            msg.setIcon(QMessageBox.Icon.Information)
        
        # 다크 테마 스타일 적용
        msg.setStyleSheet(f"""
            QMessageBox {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
            }}
            QMessageBox QLabel {{
                color: {DARK_COLORS['text_primary']};
                background-color: transparent;
            }}
            QMessageBox QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                padding: 6px 20px;
                border-radius: 4px;
                min-width: 80px;
            }}
            QMessageBox QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border: 1px solid {DARK_COLORS['accent_blue']};
            }}
            QMessageBox QPushButton:pressed {{
                background-color: {DARK_COLORS['bg_pressed']};
            }}
        """)
        
        msg.exec()
    
    def upscale_image_nai(self):
        """NAI API를 사용하여 이미지를 2배 업스케일합니다."""
        from PyQt6.QtWidgets import QProgressDialog
        from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
        from PyQt6.QtGui import QPixmap
        import io
        
        # AppContext 가져오기 (self.app_context가 있으면 직접 사용)
        if hasattr(self, 'app_context') and self.app_context:
            app_context = self.app_context
        else:
            # 없으면 부모 체인에서 찾기
            parent_widget = self.parent()
            while parent_widget and not hasattr(parent_widget, 'app_context'):
                parent_widget = parent_widget.parent()
            
            if not parent_widget or not hasattr(parent_widget, 'app_context'):
                self._show_styled_message("오류", "AppContext를 찾을 수 없습니다.", 'warning')
                return
            
            app_context = parent_widget.app_context
        
        # 현재 이미지를 QPixmap으로 변환
        pil_img = self.history_item.image
        buf = io.BytesIO()
        pil_img.save(buf, format='PNG')
        buf.seek(0)
        current_pixmap = QPixmap()
        current_pixmap.loadFromData(buf.getvalue())
        
        # 진행 상황 다이얼로그 생성
        progress = QProgressDialog("이미지 업스케일 중...", None, 0, 0, self)
        progress.setWindowTitle("NAI 업스케일")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setCancelButton(None)
        progress.show()
        
        # Worker 클래스 정의 (메서드 내부에 정의)
        class UpscaleWorker(QObject):
            finished = pyqtSignal(dict)
            
            def __init__(self, api_service, pixmap):
                super().__init__()
                self.api_service = api_service
                self.pixmap = pixmap
            
            def run(self):
                result = self.api_service.upscale_NAI(self.pixmap)
                self.finished.emit(result)
        
        # Worker 스레드 설정
        self.upscale_thread = QThread()
        self.upscale_worker = UpscaleWorker(app_context.api_service, current_pixmap)
        self.upscale_worker.moveToThread(self.upscale_thread)
        
        # 시그널 연결
        self.upscale_thread.started.connect(self.upscale_worker.run)
        self.upscale_worker.finished.connect(
            lambda result: self._handle_upscale_result(result, progress, app_context)
        )
        self.upscale_worker.finished.connect(self.upscale_thread.quit)
        self.upscale_worker.finished.connect(self.upscale_worker.deleteLater)
        self.upscale_thread.finished.connect(self.upscale_thread.deleteLater)
        
        # 스레드 시작
        self.upscale_thread.start()
    
    def _handle_upscale_result(self, result, progress, app_context):
        """업스케일 결과를 처리합니다."""
        from PyQt6.QtWidgets import QMessageBox
        from PyQt6.QtCore import QBuffer, QIODevice
        from PIL import Image
        import io
        
        progress.close()
        
        if result['status'] == 'success':
            # QPixmap을 PIL Image로 변환
            upscaled_pixmap = result['image']
            
            # raw_bytes가 있으면 그대로 사용, 없으면 QPixmap에서 변환
            if 'raw_bytes' in result and result['raw_bytes']:
                image_data = result['raw_bytes']
            else:
                # QBuffer를 사용하여 QPixmap을 bytes로 변환
                qbuffer = QBuffer()
                qbuffer.open(QIODevice.OpenModeFlag.WriteOnly)
                upscaled_pixmap.save(qbuffer, "PNG")
                image_data = qbuffer.data().data()
                qbuffer.close()
            
            # bytes를 PIL Image로 변환
            buffer = io.BytesIO(image_data)
            upscaled_image = Image.open(buffer)
            
            # 기존 메타데이터 복사
            info_text = self.history_item.info_text + f"\nUpscaled: 2x ({upscaled_pixmap.width()}x{upscaled_pixmap.height()})"
            metadata = self.history_item.metadata.copy() if hasattr(self.history_item, 'metadata') else {}
            metadata['upscaled'] = True
            metadata['upscale_factor'] = 2
            
            # source_row 가져오기 (원본 이미지의 생성 정보)
            source_row = self.history_item.source_row if hasattr(self.history_item, 'source_row') else None
            
            # 히스토리에 추가
            if hasattr(app_context, 'add_to_history'):
                app_context.add_to_history(
                    upscaled_image,
                    image_data,  # raw_bytes 파라미터
                    info_text,
                    metadata,
                    source_row
                )
                # 성공 메시지 제거 - 사용자 요청에 따라 성공시 메시지 표시 안함
                print(f"✅ 업스케일 성공: {upscaled_pixmap.width()}x{upscaled_pixmap.height()}")
            else:
                # 폴백: 직접 ImageWindow에 추가 시도
                parent_widget = self.parent()
                while parent_widget:
                    if hasattr(parent_widget, 'add_to_history'):
                        parent_widget.add_to_history(upscaled_image, image_data, info_text, metadata, source_row)
                        # 성공 메시지 제거
                        print(f"✅ 업스케일 성공: {upscaled_pixmap.width()}x{upscaled_pixmap.height()}")
                        return
                    parent_widget = parent_widget.parent()
                
                # 히스토리에 추가할 방법이 없는 경우
                self._show_styled_message("경고", 
                    f"{result['message']}\n\n업스케일은 성공했지만 히스토리에 추가할 수 없습니다.", 'warning')
        else:
            self._show_styled_message("업스케일 실패", result['message'], 'critical')

    def restore_generation_params(self):
        """🆕 생성 파라미터를 UI에 복원"""
        if not hasattr(self.history_item, 'generation_params') or not self.history_item.generation_params:
            print("⚠️ 복원할 생성 파라미터가 없습니다.")
            return
            
        try:
            params = self.history_item.generation_params
            
            # AppContext를 통해 메인 윈도우에 접근
            # HistoryItemWidget -> ImageHistoryWindow -> ImageWindow -> app_context -> main_window
            parent_widget = self.parent()
            while parent_widget and not hasattr(parent_widget, 'app_context'):
                parent_widget = parent_widget.parent()
            
            if not parent_widget or not hasattr(parent_widget, 'app_context'):
                print("❌ AppContext를 찾을 수 없습니다.")
                return
                
            app_context = parent_widget.app_context
            main_window = app_context.main_window
            
            # 🆕 프롬프트 복원 (main_prompt 우선, 없으면 input 사용)
            prompt_context = self.history_item.prompt_context if hasattr(self.history_item, 'prompt_context') else {}
            
            if 'main_prompt' in prompt_context and prompt_context['main_prompt']:
                # main_prompt가 있으면 이를 사용 (\n\n 포함하여 원본 형태로 복원)
                main_window.main_prompt_textedit.setPlainText(prompt_context['main_prompt'])
                print(f"✅ 원본 프롬프트 복원 (main_prompt): {prompt_context['main_prompt'][:50]}...")
            elif 'input' in params:
                # main_prompt가 없으면 기존 방식대로 input 사용
                main_window.main_prompt_textedit.setPlainText(params['input'])
                print(f"✅ 프롬프트 복원 (input): {params['input'][:50]}...")
            
            if 'negative_prompt' in params:
                main_window.negative_prompt_textedit.setPlainText(params['negative_prompt'])
                print(f"✅ 네거티브 프롬프트 복원: {params['negative_prompt'][:30]}...")
            
            # 모델/샘플러 복원
            if 'model' in params:
                index = main_window.model_combo.findText(params['model'])
                if index >= 0:
                    main_window.model_combo.setCurrentIndex(index)
                    print(f"✅ 모델 복원: {params['model']}")
            
            if 'sampler' in params:
                index = main_window.sampler_combo.findText(params['sampler'])
                if index >= 0:
                    main_window.sampler_combo.setCurrentIndex(index)
                    print(f"✅ 샘플러 복원: {params['sampler']}")
            
            # 🆕 스케줄러 복원 (scheduler 또는 scheduler 관련 키 확인)
            scheduler_keys = ['scheduler', 'noise_schedule']  # NAI에서 사용할 수 있는 키들
            for key in scheduler_keys:
                if key in params and hasattr(main_window, 'scheduler_combo'):
                    scheduler_value = params[key]
                    index = main_window.scheduler_combo.findText(scheduler_value)
                    if index >= 0:
                        main_window.scheduler_combo.setCurrentIndex(index)
                        print(f"✅ 스케줄러 복원: {scheduler_value}")
                        break  # 첫 번째로 찾은 키 사용
            
            # 해상도 복원
            if 'width' in params and 'height' in params:
                resolution_text = f"{params['width']} x {params['height']}"
                index = main_window.resolution_combo.findText(resolution_text)
                if index >= 0:
                    main_window.resolution_combo.setCurrentIndex(index)
                    print(f"✅ 해상도 복원: {resolution_text}")
            
            # 수치 파라미터 복원
            if 'steps' in params:
                main_window.steps_spinbox.setValue(params['steps'])
                print(f"✅ 스텝 복원: {params['steps']}")
            
            if 'cfg_scale' in params:
                main_window.cfg_scale_slider.setValue(int(params['cfg_scale'] * 10))
                print(f"✅ CFG Scale 복원: {params['cfg_scale']}")
            
            if 'cfg_rescale' in params:
                main_window.cfg_rescale_slider.setValue(int(params['cfg_rescale'] * 100))
                print(f"✅ CFG Rescale 복원: {params['cfg_rescale']}")
            
            # 시드 복원
            if 'seed' in params:
                main_window.seed_input.setText(str(params['seed']))
                main_window.seed_fix_checkbox.setChecked(True)  # 시드 고정 체크
                print(f"✅ 시드 복원: {params['seed']}")
            
            # 고급 옵션 복원
            advanced_options = ['SMEA', 'DYN', 'VAR+', 'DECRISP']
            for option in advanced_options:
                if option in params and hasattr(main_window, 'advanced_checkboxes') and option in main_window.advanced_checkboxes:
                    main_window.advanced_checkboxes[option].setChecked(params[option])
                    print(f"✅ {option} 복원: {params[option]}")
            
            # 🆕 추가 옵션들 복원
            # 랜덤 해상도 옵션
            if 'random_resolution' in params and hasattr(main_window, 'random_resolution_checkbox'):
                main_window.random_resolution_checkbox.setChecked(params['random_resolution'])
                print(f"✅ 랜덤 해상도 복원: {params['random_resolution']}")
            
            # 커스텀 API 파라미터 옵션들
            if 'use_custom_api_params' in params and hasattr(main_window, 'custom_api_checkbox'):
                main_window.custom_api_checkbox.setChecked(params['use_custom_api_params'])
                print(f"✅ 커스텀 API 사용 복원: {params['use_custom_api_params']}")
                
            if 'custom_api_params' in params and hasattr(main_window, 'custom_script_textbox'):
                main_window.custom_script_textbox.setPlainText(params['custom_api_params'])
                print(f"✅ 커스텀 API 파라미터 복원: {len(params['custom_api_params'])} chars")
            
            # WEBUI 전용 옵션들 (해당 위젯이 있을 때만)
            webui_options = {
                'enable_hr': 'enable_hr_checkbox',
                'hr_scale': 'hr_scale_spinbox', 
                'denoising_strength': 'denoising_strength_slider'
            }
            
            for param_key, widget_name in webui_options.items():
                if param_key in params and hasattr(main_window, widget_name):
                    widget = getattr(main_window, widget_name)
                    if 'checkbox' in widget_name:
                        widget.setChecked(params[param_key])
                    elif 'spinbox' in widget_name:
                        widget.setValue(params[param_key])
                    elif 'slider' in widget_name and param_key == 'denoising_strength':
                        widget.setValue(int(params[param_key] * 100))  # 0.0~1.0 → 0~100
                    print(f"✅ {param_key} 복원: {params[param_key]}")
            
            print("✅ 생성 설정이 성공적으로 복원되었습니다.")
            
            # 상태바 메시지 표시
            if hasattr(main_window, 'status_bar'):
                backend = self.history_item.backend_type
                timestamp = self.history_item.creation_timestamp
                main_window.status_bar.showMessage(
                    f"✅ 생성 설정 복원 완료 ({backend}, {timestamp})", 3000
                )
            
        except Exception as e:
            print(f"❌ 생성 파라미터 복원 실패: {e}")
            import traceback
            traceback.print_exc()

    def show_full_metadata(self):
        """메타데이터 뷰어 윈도우를 엽니다 (Img2ImgPopup 방식 참고)"""
        try:
            # 1. 이미지에서 메타데이터 추출
            if not self.history_item.image:
                QMessageBox.warning(self, "경고", "이미지 데이터가 없습니다.")
                return

            # ImageMetadataExtractor를 사용하여 메타데이터 추출
            has_metadata = ImageMetadataExtractor.has_metadata(self.history_item.image)

            if not has_metadata:
                QMessageBox.information(
                    self,
                    "메타데이터 없음",
                    "이 이미지에는 추출 가능한 메타데이터가 없습니다."
                )
                return

            metadata = ImageMetadataExtractor.extract_metadata(self.history_item.image)

            if not metadata:
                QMessageBox.warning(self, "경고", "메타데이터를 읽을 수 없습니다.")
                return

            # 2. MetadataViewerWindow 열기 (non-modal)
            # app_context.main_window를 parent로 설정하여 시그널 연결
            parent_window = None
            if self.app_context and hasattr(self.app_context, 'main_window'):
                parent_window = self.app_context.main_window

            self.metadata_viewer = MetadataViewerWindow(
                self.history_item.image,
                metadata,
                self.app_context,
                parent_window
            )

            # 3. 시그널 연결 (MainWindow에서 처리하도록)
            if parent_window:
                # 프롬프트 적용 시그널 연결
                if hasattr(parent_window, 'apply_prompt_from_metadata'):
                    self.metadata_viewer.apply_prompt.connect(
                        parent_window.apply_prompt_from_metadata
                    )

                # 설정 적용 시그널 연결
                if hasattr(parent_window, 'apply_settings_from_metadata'):
                    self.metadata_viewer.apply_all_settings.connect(
                        parent_window.apply_settings_from_metadata
                    )

            # 4. 윈도우 표시
            self.metadata_viewer.show()

            print(f"✅ MetadataViewerWindow 열림 - {self.history_item.backend_type}")

        except Exception as e:
            print(f"❌ 메타데이터 뷰어 표시 실패: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self,
                "오류",
                f"메타데이터 뷰어를 열 수 없습니다:\n{str(e)}"
            )

    def _format_metadata_for_display(self) -> str:
        """🆕 메타데이터를 보기 좋게 포맷팅"""
        lines = []
        
        # 기본 정보
        lines.append("=== 기본 정보 ===")
        lines.append(f"생성 시각: {getattr(self.history_item, 'creation_timestamp', 'N/A')}")
        lines.append(f"백엔드: {getattr(self.history_item, 'backend_type', 'N/A')}")
        lines.append(f"파일 경로: {self.history_item.filepath or 'N/A'}")
        lines.append("")
        
        # 생성 파라미터
        if hasattr(self.history_item, 'generation_params') and self.history_item.generation_params:
            lines.append("=== 생성 파라미터 ===")
            for key, value in self.history_item.generation_params.items():
                if key != 'credential':  # 민감한 정보 제외
                    lines.append(f"{key}: {value}")
            lines.append("")
        
        # 프롬프트 컨텍스트
        if hasattr(self.history_item, 'prompt_context') and self.history_item.prompt_context:
            lines.append("=== 프롬프트 정보 ===")
            for key, value in self.history_item.prompt_context.items():
                if key == 'source_tags' and isinstance(value, dict):
                    lines.append(f"{key}: {len(value)} 태그")
                    for tag_key, tag_value in value.items():
                        if tag_value:
                            lines.append(f"  - {tag_key}: {str(tag_value)[:100]}...")
                elif key == 'main_prompt' and value:
                    # 🆕 main_prompt는 줄바꿈을 포함한 원본 형태로 표시
                    lines.append(f"{key} (원본, \\n\\n 포함):")
                    lines.append(f"  {repr(value)[:200]}..." if len(repr(value)) > 200 else f"  {repr(value)}")
                else:
                    # 다른 필드들은 기존 방식으로 표시
                    display_value = str(value)[:100] + "..." if len(str(value)) > 100 else str(value)
                    lines.append(f"{key}: {display_value}")
            lines.append("")
        
        # API 메타데이터
        if hasattr(self.history_item, 'api_metadata') and self.history_item.api_metadata:
            lines.append("=== API 정보 ===")
            for key, value in self.history_item.api_metadata.items():
                lines.append(f"{key}: {value}")
            lines.append("")
        
        # 이미지 정보
        lines.append("=== 이미지 정보 ===")
        lines.append(f"크기: {self.history_item.image.size}")
        lines.append(f"모드: {self.history_item.image.mode}")
        lines.append(f"포맷: {getattr(self.history_item.image, 'format', 'N/A')}")
        
        if hasattr(self.history_item.image, 'info') and self.history_item.image.info:
            lines.append(f"메타데이터 키: {list(self.history_item.image.info.keys())}")
        
        return "\n".join(lines)

# --- 2. ImageWindow 클래스: 위젯들을 담는 컨테이너이자, 외부와의 소통 창구 ---
class ImageWindow(QWidget):
    instant_generation_requested = pyqtSignal(object)
    load_prompt_to_main_ui = pyqtSignal(str)
    send_to_inpaint_requested = pyqtSignal(object)
    send_to_img2img_requested = pyqtSignal(object)
    instant_outpaint_requested = pyqtSignal(object)
    send_to_outpaint_requested = pyqtSignal(object)
    save_to_remote_event_requested = pyqtSignal(HistoryItem)  # 🆕 리모트 이벤트 저장 시그널

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        # 모든 멤버 변수를 먼저 선언합니다.
        self.main_image_label: ImageLabel = None
        self.info_textbox: QTextEdit = None
        self.info_panel: QWidget = None
        self.auto_save_checkbox: QCheckBox = None
        self.image_history_window: ImageHistoryWindow = None
        self.info_visible = True
        self.app_context = app_context
        self.history_visible = True
        self.toggle_history_button: QPushButton = None
        # ✅ ImageCrudController 사용 (save_counter 제거)
        self.image_crud = app_context.image_crud_controller
        self.current_history_item = None
        # 🆕 ComfyUI 워크플로우 캐시
        self.comfyui_workflow_cache: Dict[int, Dict] = {}

        # Enhance 설정
        self._enhance_upscale = 1.5    # 1.0 or 1.5
        self._enhance_strength = 0.2   # 0.1 ~ 0.9
        self._enhance_noise = 0.0      # 0.0 ~ 0.1

        self.init_ui()
        self.load_settings()

    def init_ui(self):
        # 1. ImageWindow 자체의 메인 레이아웃 (수평)
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 2. 전체를 좌우로 나눌 메인 수평 스플리터
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- 3. 왼쪽 패널 구성 ---
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 0, 4, 0)
        left_layout.setSpacing(4)

        # 3-1. 컨트롤 버튼 영역 (상단) 
        control_layout = QHBoxLayout()
        self.auto_save_checkbox = QCheckBox("자동 저장")
        self.auto_save_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.auto_save_checkbox.toggled.connect(self.save_settings)

        self.toggle_history_button = QPushButton("📜 히스토리 숨기기")
        self.toggle_history_button.setCheckable(True)
        self.toggle_history_button.setChecked(True)
        self.toggle_history_button.setStyleSheet(DARK_STYLES['secondary_button'])
        self.toggle_history_button.clicked.connect(self.toggle_history_panel)

        self.save_button = QPushButton("💾 이미지 저장")
        self.save_button.setStyleSheet(DARK_STYLES['secondary_button'])
        self.save_button.setToolTip("현재 보고 있는 이미지를 EXIF 정보와 함께 저장합니다.")
        self.save_button.clicked.connect(self.save_current_image)

        self.advanced_button = QPushButton("⚙️ 고급")
        self.advanced_button.setStyleSheet(DARK_STYLES['secondary_button'])
        self.advanced_menu = QMenu(self)
        menu_style = f"""
            QMenu {{ background-color: {DARK_COLORS['bg_tertiary']}; color: {DARK_COLORS['text_primary']}; border: 1px solid {DARK_COLORS['border']}; border-radius: 4px; padding: 5px; }}
            QMenu::item {{ padding: 8px 20px; border-radius: 4px; }}
            QMenu::item:selected {{ background-color: {DARK_COLORS['accent_blue']}; }}
        """
        self.advanced_menu.setStyleSheet(menu_style)

        download_all_action = QAction("💾 전체 이미지 다운로드", self)
        download_all_action.triggered.connect(lambda: self.start_download_all(clear_after=False))
        self.advanced_menu.addAction(download_all_action)

        download_clear_action = QAction("🗑️ 다운로드 + 히스토리 정리", self)
        download_clear_action.triggered.connect(lambda: self.start_download_all(clear_after=True))
        self.advanced_menu.addAction(download_clear_action)

        clear_action = QAction("🧹 히스토리 정리 (다운로드 X)", self)
        clear_action.triggered.connect(lambda: self.clear_history_only())
        self.advanced_menu.addAction(clear_action)

        # 구분선 추가
        self.advanced_menu.addSeparator()
        
        # 메모리 관리 섹션 추가
        self.create_memory_management_section()

        # 버튼에 메뉴를 영구적으로 할당합니다.
        self.advanced_button.setMenu(self.advanced_menu)

        # [핵심] 메뉴가 표시되기 직전에 상태를 업데이트하도록 aboutToShow 신호를 연결합니다.
        self.advanced_menu.aboutToShow.connect(self.update_advanced_menu_state)
        
        self.save_as_webp_checkbox = QCheckBox("WEBP로 저장")
        self.save_as_webp_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.save_as_webp_checkbox.toggled.connect(self.save_settings)

        # 초기화 버튼
        clear_button = QPushButton(" 🗑️ ")
        clear_button.setStyleSheet(f"""
            QPushButton {{
                background-color: #d32f2f;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: {get_scaled_font_size(18)}px;
            }}
            QPushButton:hover {{
                background-color: #f44336;
            }}
        """)
        clear_button.clicked.connect(self.clear_all)
        control_layout.addWidget(self.auto_save_checkbox)
        control_layout.addStretch()
        control_layout.addWidget(clear_button)
        control_layout.addWidget(self.save_button)
        control_layout.addWidget(self.advanced_button)
        control_layout.addWidget(self.save_as_webp_checkbox)

        self.open_folder_button = QPushButton("폴더 열기")
        self.open_folder_button.setStyleSheet(DARK_STYLES['secondary_button'])
        self.open_folder_button.clicked.connect(self.open_folder)
        control_layout.addWidget(self.open_folder_button)

        left_layout.addLayout(control_layout)

        # 수직 스플리터 생성
        image_info_splitter = QSplitter(Qt.Orientation.Vertical)
        image_info_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #555555;
                border: 1px solid #777777;
                height: 1px;
                margin: 0px 1px;
                border-radius: 1px;
            }
            QSplitter::handle:hover {
                background-color: #666666;
            }
        """)

        # 3-2-a. 이미지 표시 영역
        self.main_image_label = ImageLabel()
        self.main_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_image_label.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 8px;
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)
        self.main_image_label.setText("Generated Image")
        
        # 드래그&드롭 시그널 연결
        self.main_image_label.image_dropped.connect(self.show_img2img_popup)
        
        # 3-2-b. 정보 패널 (제목 + 텍스트박스)
        self.info_panel = QWidget()
        info_panel_layout = QVBoxLayout(self.info_panel)
        info_panel_layout.setContentsMargins(0, 4, 0, 0)
        info_panel_layout.setSpacing(4)
        
        # ── 생성 정보 타이틀 + Enhance 버튼 (한 줄) ──
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(get_scaled_size(4))

        info_title = QLabel("📝 생성 정보")
        info_title.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-weight: bold;
                font-size: {get_scaled_font_size(12)}px;
                padding: 2px 4px;
            }}
        """)
        title_row.addWidget(info_title)
        title_row.addStretch()

        btn_h = get_scaled_size(24)
        self.enhance_button = QPushButton(f"✨Enhance x{self._enhance_upscale:g} | {self._enhance_strength:.1f}")
        self.enhance_button.setFixedHeight(btn_h)
        self.enhance_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_purple']};
                color: white; border: none; border-radius: {get_scaled_size(3)}px;
                padding: 0px {get_scaled_size(8)}px;
                font-size: {get_scaled_font_size(11)}px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {DARK_COLORS['accent_purple_hover']}; }}
            QPushButton:disabled {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_disabled']};
            }}
        """)
        self.enhance_button.setEnabled(False)
        self.enhance_button.clicked.connect(self._execute_enhance)

        self.enhance_settings_button = QPushButton("⚙️")
        self.enhance_settings_button.setFixedSize(btn_h, btn_h)
        self.enhance_settings_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']}; border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(3)}px; font-size: {get_scaled_font_size(11)}px;
            }}
            QPushButton:hover {{ background-color: {DARK_COLORS['bg_hover']}; }}
        """)
        self.enhance_settings_button.clicked.connect(self._show_enhance_settings)

        title_row.addWidget(self.enhance_button)
        title_row.addWidget(self.enhance_settings_button)
        info_panel_layout.addLayout(title_row)

        self.info_textbox = QTextEdit()
        self.info_textbox.setReadOnly(True)
        self.info_textbox.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.info_textbox.setPlaceholderText("생성 정보가 여기에 표시됩니다...")
        info_panel_layout.addWidget(self.info_textbox)

        # 수직 스플리터에 이미지와 정보 패널 추가
        image_info_splitter.addWidget(self.main_image_label)
        image_info_splitter.addWidget(self.info_panel)
        image_info_splitter.setStretchFactor(0, 50)
        image_info_splitter.setStretchFactor(1, 3)
        
        # 왼쪽 패널 레이아웃에 수직 스플리터 추가
        left_layout.addWidget(image_info_splitter)

        # --- 4. 오른쪽 패널 구성 (이미지 히스토리) ---
        self.image_history_window = ImageHistoryWindow(self)
        self.image_history_window.history_item_selected.connect(self.display_history_item)
        self.image_history_window.setFixedWidth(140)

        # --- 5. 최종 조립 ---
        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(self.image_history_window)
        main_splitter.setStretchFactor(0, 70)
        main_splitter.setStretchFactor(1, 30)
        main_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #555555;
                border: 2px solid #777777;
                width: 2px; /* 수평 스플리터는 width로 두께 조절 */
                margin: 1px 0px;
                border-radius: 1px;
            }
            QSplitter::handle:hover {
                background-color: #666666;
            }
        """)
        main_layout.addWidget(main_splitter)

        # [추가] 히스토리 창에서 오는 시그널들을 메인 윈도우로 전달할 슬롯에 연결
        self.image_history_window.load_prompt_requested.connect(self.load_prompt_to_main_ui)
        self.image_history_window.reroll_requested.connect(self.instant_generation_requested)
        self.image_history_window.save_to_remote_event_requested.connect(self.save_to_remote_event_requested)  # 🆕

        # [추가] 메인 이미지 레이블에 컨텍스트 메뉴 설정
        self.main_image_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.main_image_label.customContextMenuRequested.connect(self.show_main_image_context_menu)

        # Enhance 버튼 상태 — 모드 변경 시 업데이트
        if self.app_context:
            self.app_context.subscribe("api_mode_changed", lambda _: self._update_enhance_button_state())

    def save_settings(self):
        """체크박스 설정을 JSON 파일에 저장합니다."""
        settings = {
            "auto_save": self.auto_save_checkbox.isChecked(),
            "save_as_webp": self.save_as_webp_checkbox.isChecked(),
            "enhance_upscale": self._enhance_upscale,
            "enhance_strength": self._enhance_strength,
            "enhance_noise": self._enhance_noise,
        }
        
        settings_path = Path("save/image_window.json")
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(settings_path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Failed to save image_window settings: {e}")
    
    def load_settings(self):
        """JSON 파일에서 체크박스 설정을 불러옵니다."""
        settings_path = Path("save/image_window.json")
        
        if settings_path.exists():
            try:
                with open(settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                
                # 설정 적용 (toggled 시그널 임시 차단)
                self.auto_save_checkbox.blockSignals(True)
                self.save_as_webp_checkbox.blockSignals(True)
                
                self.auto_save_checkbox.setChecked(settings.get("auto_save", False))
                self.save_as_webp_checkbox.setChecked(settings.get("save_as_webp", False))

                self.auto_save_checkbox.blockSignals(False)
                self.save_as_webp_checkbox.blockSignals(False)

                # Enhance 설정 복원
                self._enhance_upscale = settings.get("enhance_upscale", 1.5)
                self._enhance_strength = settings.get("enhance_strength", 0.2)
                self._enhance_noise = settings.get("enhance_noise", 0.0)
                self._update_enhance_button_text()
                
            except Exception as e:
                print(f"Failed to load image_window settings: {e}")
                # 로드 실패시 기본값 사용
                self.auto_save_checkbox.setChecked(False)
                self.save_as_webp_checkbox.setChecked(False)
        else:
            # 파일이 없으면 기본값으로 설정하고 저장
            self.auto_save_checkbox.setChecked(False)
            self.save_as_webp_checkbox.setChecked(False)
            self.save_settings()

    def show_main_image_context_menu(self, pos):
        """메인 이미지 우클릭 시 컨텍스트 메뉴를 표시합니다."""
        if not self.current_history_item:
            return
            
        menu = QMenu(self)
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
            QMenu::separator {{
                height: 1px;
                background-color: {DARK_COLORS['border']};
                margin: 5px 0px;
            }}
        """
        menu.setStyleSheet(menu_style)
        load_action = QAction("프롬프트 불러오기", self)
        load_action.triggered.connect(self._load_current_prompt)
        menu.addAction(load_action)
        
        reroll_action = QAction("프롬프트 다시개봉", self)
        if self.current_history_item.source_row is None or self.current_history_item.source_row.empty:
            reroll_action.setEnabled(False)
        reroll_action.triggered.connect(self._reroll_current_prompt)
        menu.addAction(reroll_action)

        # 🆕 메타데이터 관련 메뉴 추가
        menu.addSeparator()
        restore_params_action = QAction("⚙️ 생성 설정 복원", self)
        # 생성 파라미터가 있는 경우에만 활성화
        if (hasattr(self.current_history_item, 'generation_params') and 
            self.current_history_item.generation_params):
            restore_params_action.triggered.connect(self._restore_current_generation_params)
        else:
            restore_params_action.setEnabled(False)
        menu.addAction(restore_params_action)
        
        show_metadata_action = QAction("🔍 전체 메타데이터 보기", self)
        show_metadata_action.triggered.connect(self._show_current_metadata)
        menu.addAction(show_metadata_action)
        
        # 이미지 붙여넣기 메뉴 추가
        menu.addSeparator()
        paste_image_action = QAction("📋 이미지 붙여넣기", self)
        paste_image_action.triggered.connect(self._paste_image_from_clipboard)
        menu.addAction(paste_image_action)

        # [수정] 파일 경로가 있을 때만 '파일 위치 열기' 옵션을 추가합니다.
        filepath = self.current_history_item.filepath
        if filepath and os.path.exists(filepath):
            menu.addSeparator()
            reveal_action = QAction("📁 파일 위치 열기", self)
            reveal_action.triggered.connect(lambda: self._open_file_in_explorer(filepath))
            menu.addAction(reveal_action)
        else:
            # 파일이 저장되지 않은 경우 저장 버튼 추가
            menu.addSeparator()
            save_action = QAction("💾 이미지 저장", self)
            save_action.triggered.connect(self.save_image_manually)
            menu.addAction(save_action)
        
        copy_png_action = QAction("PNG로 클립보드 복사", self)
        copy_webp_action = QAction("WEBP로 클립보드 복사", self)
        copy_png_action.triggered.connect(lambda: self.copy_image_to_clipboard('PNG'))
        copy_webp_action.triggered.connect(lambda: self.copy_image_to_clipboard('WEBP'))
        menu.addAction(copy_png_action)
        menu.addAction(copy_webp_action)
        
        # NAI Upscale 메뉴 추가
        menu.addSeparator()
        upscale_action = QAction("🔍 NAI 2x 업스케일", self)
        upscale_action.triggered.connect(self.upscale_current_image_nai)
        # NAI 모드가 아니면 비활성화
        current_mode = self.app_context.get_api_mode() if self.app_context else None
        if current_mode != "NAI":
            upscale_action.setEnabled(False)
            upscale_action.setToolTip("NAI 모드에서만 사용 가능합니다")
        menu.addAction(upscale_action)

        menu.addSeparator()
        nai_inpaint_menu = QMenu("🎨 NAI 인페인트 메뉴", menu)
        nai_inpaint_menu.setStyleSheet(menu.styleSheet())

        send_img2img = QAction("Send to img2img", nai_inpaint_menu)
        send_img2img.triggered.connect(self._emit_send_to_img2img)
        nai_inpaint_menu.addAction(send_img2img)

        send_inpaint = QAction("Send to Inpaint", nai_inpaint_menu)
        send_inpaint.triggered.connect(self._emit_send_to_inpaint)
        nai_inpaint_menu.addAction(send_inpaint)

        nai_inpaint_menu.addSeparator()

        instant_outpaint = QAction("Instant Outpaint Request", nai_inpaint_menu)
        instant_outpaint.triggered.connect(self._emit_instant_outpaint)
        nai_inpaint_menu.addAction(instant_outpaint)

        send_outpaint = QAction("Send to Outpainting", nai_inpaint_menu)
        send_outpaint.triggered.connect(self._emit_send_to_outpaint)
        nai_inpaint_menu.addAction(send_outpaint)

        menu.addMenu(nai_inpaint_menu)
        
        # Add Send to Sketchbook action
        send_to_sketchbook_action = QAction("🖌️ Send to Sketchbook (NAI)", self)
        send_to_sketchbook_action.triggered.connect(self._send_to_sketchbook)
        # menu.addAction(send_to_sketchbook_action)
        
        # Add Send to Character Reference action
        send_to_character_ref_action = QAction("📸 Send to Character Reference", self)
        send_to_character_ref_action.triggered.connect(self._send_to_character_reference)
        menu.addAction(send_to_character_ref_action)

        # 🆕 리모트에 이벤트 저장 메뉴
        menu.addSeparator()
        save_to_remote_action = QAction("📌 리모트에 이벤트 저장", self)
        # source_row가 없는 경우 비활성화
        if self.current_history_item.source_row is None or self.current_history_item.source_row.empty:
            save_to_remote_action.setEnabled(False)
        save_to_remote_action.triggered.connect(self._emit_save_to_remote_event)
        menu.addAction(save_to_remote_action)

        menu.exec(self.main_image_label.mapToGlobal(pos))

    def save_image_manually(self):
        """현재 표시된 이미지를 수동으로 저장합니다 - save_current_image와 동일한 기능."""
        # 기존의 save_current_image 메소드를 호출
        self.save_current_image()
    
    def _emit_send_to_img2img(self):
        """'Send to img2img' 요청 시그널을 발생시킵니다."""
        if self.current_history_item:
            self.send_to_img2img_requested.emit(self.current_history_item)

    def _emit_send_to_inpaint(self):
        """'Send to Inpaint' 요청 시그널을 발생시킵니다."""
        if self.current_history_item:
            self.send_to_inpaint_requested.emit(self.current_history_item)

    def _emit_instant_outpaint(self):
        """'Instant Outpaint Request' 시그널을 발생시킵니다."""
        if self.current_history_item:
            self.instant_outpaint_requested.emit(self.current_history_item)

    def _emit_send_to_outpaint(self):
        """'Send to Outpainting' 시그널을 발생시킵니다."""
        if self.current_history_item:
            self.send_to_outpaint_requested.emit(self.current_history_item)

    def _emit_save_to_remote_event(self):
        """🆕 '리모트에 이벤트 저장' 시그널을 발생시킵니다."""
        if self.current_history_item:
            self.save_to_remote_event_requested.emit(self.current_history_item)

    def _paste_image_from_clipboard(self):
        """클립보드에서 이미지를 가져와 img2img 팝업을 표시합니다."""
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        
        pil_image = None
        
        try:
            # URL이 있는 경우 (파일 경로)
            if mime_data.hasUrls():
                for url in mime_data.urls():
                    file_path = url.toLocalFile()
                    if file_path and os.path.exists(file_path):
                        pil_image = Image.open(file_path)
                        break
            
            # 직접 이미지 데이터가 있는 경우
            elif mime_data.hasImage():
                qimage = clipboard.image()
                if not qimage.isNull():
                    # QImage를 PIL Image로 변환
                    buffer = BytesIO()
                    qimage.save(buffer, "PNG")
                    buffer.seek(0)
                    pil_image = Image.open(buffer)
            
            # 이미지를 찾았으면 팝업 표시
            if pil_image:
                self.show_img2img_popup(pil_image)
            else:
                QMessageBox.information(self, "알림", "클립보드에 이미지가 없습니다.")
                
        except Exception as e:
            print(f"Failed to paste image from clipboard: {e}")
            QMessageBox.warning(self, "오류", f"클립보드에서 이미지를 가져올 수 없습니다.\n{str(e)}")
    
    def show_img2img_popup(self, pil_image: Image.Image):
        """이미지에 대한 작업 선택 팝업을 표시합니다."""
        print(f"🔍 ImageWindow.show_img2img_popup: 이미지 모드 = {pil_image.mode}, 크기 = {pil_image.size}")
        main_window = self.window()
        popup = Img2ImgPopup(pil_image=pil_image, app_context=self.app_context, parent=main_window)
        
        # 팝업의 신호를 메인 윈도우의 슬롯에 연결
        # history_item이 있으면 캐릭터 프롬프트 등 컨텍스트를 함께 전달
        history_item = self.current_history_item if hasattr(self, 'current_history_item') else None
        if hasattr(main_window, 'activate_img2img_panel'):
            if history_item and hasattr(main_window, 'img2img_window_manager'):
                popup.img2img_requested.connect(
                    lambda img, hi=history_item: main_window.img2img_window_manager.create_window(
                        img, mode='img2img', history_item=hi
                    )
                )
            else:
                popup.img2img_requested.connect(main_window.activate_img2img_panel)
        if hasattr(main_window, 'activate_inpaint_mode'):
            if history_item and hasattr(main_window, 'img2img_window_manager'):
                popup.inpaint_requested.connect(
                    lambda img, hi=history_item: self._open_inpaint_with_history(
                        main_window, img, hi
                    )
                )
            else:
                popup.inpaint_requested.connect(main_window.activate_inpaint_mode)
        if hasattr(main_window, 'activate_vibe_transfer'):
            popup.import_vibe_transfer_requested.connect(main_window.activate_vibe_transfer)
        if hasattr(main_window, 'on_tag_interrogation_requested'):
            popup.tag_interrogation_requested.connect(main_window.on_tag_interrogation_requested)

        # 팝업 위치 조정 및 실행
        cursor_pos = QCursor.pos()
        popup_rect = popup.geometry()
        
        # 팝업의 좌상단 위치 계산
        new_x = cursor_pos.x() - popup_rect.width() // 2
        new_y = cursor_pos.y() - popup_rect.height()
        
        # 화면 경계 처리
        screen = main_window.screen()
        screen_rect = screen.availableGeometry()
        new_x = max(screen_rect.left() + 5, min(new_x, screen_rect.right() - popup_rect.width() - 5))
        new_y = max(screen_rect.top() + 5, min(new_y, screen_rect.bottom() - popup_rect.height() - 5))
        
        popup.move(new_x, new_y)
        popup.exec()
    
    def _open_inpaint_with_history(self, main_window, pil_image, history_item):
        """history_item의 캐릭터 프롬프트를 유지하며 Inpaint 윈도우를 엽니다."""
        from ui.inpaint_window import InpaintWindow
        result = InpaintWindow.get_inpaint_data(pil_image, None, main_window)
        if result:
            mask_data = {
                'full_mask_image': result.get('full_mask_image'),
                'small_mask_image': result.get('small_mask_image'),
            }
            main_window.img2img_window_manager.create_window(
                pil_image, mode='inpaint', mask_data=mask_data,
                history_item=history_item
            )

    def _send_to_sketchbook(self):
        """Send current image to Sketchbook with prompts for inpaint mode."""
        if not self.current_history_item:
            return
        
        # Get prompts from the current item
        main_prompt = ""
        negative_prompt = ""
        
        if (hasattr(self.current_history_item, 'prompt_context') and 
            self.current_history_item.prompt_context):
            # Get main_prompt and negative_prompt from context
            main_prompt = self.current_history_item.prompt_context.get('main_prompt', '')
            negative_prompt = self.current_history_item.prompt_context.get('negative_prompt', '')
        
        # If main_prompt is empty, try to extract from info_text
        if not main_prompt and self.current_history_item.info_text:
            info_parts = self.current_history_item.info_text.split('Negative prompt:')
            if len(info_parts) > 0:
                main_prompt = info_parts[0].strip()
            if len(info_parts) > 1:
                # Extract negative prompt (up to Steps: or end)
                neg_part = info_parts[1].split('Steps:')[0].strip()
                negative_prompt = neg_part
        
        # Save image to temp file
        import tempfile
        import os
        
        temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        temp_path = temp_file.name
        temp_file.close()
        
        # Save PIL Image to temp file
        if self.current_history_item.image:
            self.current_history_item.image.save(temp_path, 'PNG')
            
            # Access Sketchbook through Assets tab via RightView
            if hasattr(self.app_context, 'main_window') and hasattr(self.app_context.main_window, 'image_window'):
                right_view = self.app_context.main_window.image_window
                if hasattr(right_view, 'tab_controller'):
                    # Get Assets tab
                    assets_tab = right_view.tab_controller.get_tab_instance('AssetsTabModule')
                    if assets_tab and hasattr(assets_tab, 'widget') and hasattr(assets_tab.widget, 'sketchbook_widget'):
                        sketchbook = assets_tab.widget.sketchbook_widget
                        
                        # Check if Sketchbook has layers
                        # if hasattr(sketchbook, 'canvas') and sketchbook.canvas.layers:
                        #     QMessageBox.warning(self, "전송 실패", 
                        #                       "Sketchbook에 레이어가 이미 존재합니다.\n"
                        #                       "인페인트 모드를 사용하려면 Sketchbook을 비워주세요.")
                        #     try:
                        #         os.unlink(temp_path)
                        #     except:
                        #         pass
                        #     return
                        
                        # Add image to Sketchbook
                        image_name = f"Inpaint_{os.path.basename(temp_path)}"
                        sketchbook.add_image_from_path(temp_path, image_name)
                        
                        # Store prompts (will be applied when user manually enables inpaint mode)
                        sketchbook.set_inpaint_prompts(main_prompt, negative_prompt)
                        
                        # Switch to Assets tab and show Sketchbook
                        right_view.tab_controller.switch_to_tab('AssetsTabModule')
                        
                        # If Assets tab has tab widget, switch to Sketchbook tab
                        if hasattr(assets_tab.widget, 'tab_widget'):
                            # Find Sketchbook tab index
                            for i in range(assets_tab.widget.tab_widget.count()):
                                if assets_tab.widget.tab_widget.tabText(i) == "✏️ Sketchbook":
                                    assets_tab.widget.tab_widget.setCurrentIndex(i)
                                    break
                        
                        print(f"✅ Image sent to Sketchbook with prompts")
                        print(f"   Main prompt: {main_prompt[:50]}...")
                        print(f"   Negative prompt: {negative_prompt[:50]}...")
                    else:
                        QMessageBox.warning(self, "오류", "Sketchbook 탭을 찾을 수 없습니다.")
            
            # Clean up temp file after a delay
            QTimer.singleShot(1000, lambda: self._cleanup_temp_file(temp_path))
    
    def _cleanup_temp_file(self, path):
        """Clean up temporary file."""
        try:
            if os.path.exists(path):
                os.unlink(path)
        except:
            pass

    def _send_to_character_reference(self):
        """Send current image to Character Reference module."""
        if not self.current_history_item:
            return
        
        # Save image to temp file
        import tempfile
        import time
        from pathlib import Path
        
        # Create character_reference/temp folder
        temp_folder = Path("save/character_reference/temp")
        temp_folder.mkdir(parents=True, exist_ok=True)
        
        # Generate temp file name with timestamp
        temp_file = temp_folder / f"from_history_{int(time.time())}.png"
        
        # Save PIL Image to temp file
        if self.current_history_item.image:
            self.current_history_item.image.save(temp_file, 'PNG')
            
            # Get CharacterReferenceModule from app context
            try:
                if hasattr(self.app_context, 'middle_section_controller'):
                    char_ref_module = self.app_context.middle_section_controller.get_module_instance("CharacterReferenceModule")
                    if char_ref_module:
                        # Add the image to character reference module
                        frame = char_ref_module._add_character_frame(str(temp_file))
                        if frame:
                            print(f"✅ Image sent to Character Reference: {temp_file}")
                            # Show success message
                            from PyQt6.QtWidgets import QMessageBox
                            msg_box = QMessageBox()
                            msg_box.setIcon(QMessageBox.Icon.Information)
                            msg_box.setWindowTitle("성공")
                            msg_box.setText("이미지가 Character Reference 모듈에 추가되었습니다.")
                            msg_box.setStyleSheet("""
                                QMessageBox {
                                    background-color: #1a1a1a;
                                    color: white;
                                }
                                QMessageBox QLabel {
                                    color: white;
                                }
                                QMessageBox QPushButton {
                                    background-color: #3a3a3a;
                                    color: white;
                                    border: 1px solid #555;
                                    padding: 5px 15px;
                                    min-width: 60px;
                                }
                                QMessageBox QPushButton:hover {
                                    background-color: #4a4a4a;
                                }
                            """)
                            msg_box.exec()
                        else:
                            # Show error message if frame creation failed
                            from PyQt6.QtWidgets import QMessageBox
                            QMessageBox.warning(self, "오류", "Character Reference 모듈에 이미지를 추가하지 못했습니다.")
                    else:
                        # Show error if module not found
                        from PyQt6.QtWidgets import QMessageBox
                        QMessageBox.warning(self, "오류", "Character Reference 모듈을 찾을 수 없습니다.")
                else:
                    # Show error if context not available
                    from PyQt6.QtWidgets import QMessageBox
                    QMessageBox.warning(self, "오류", "앱 컨텍스트를 사용할 수 없습니다.")
                    
            except Exception as e:
                print(f"❌ Error sending image to Character Reference: {e}")
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.critical(self, "오류", f"Character Reference로 이미지를 전송하는 중 오류가 발생했습니다: {str(e)}")

    def _load_current_prompt(self):
        """🆕 현재 표시 중인 이미지의 프롬프트를 불러옵니다 - main_prompt 우선 사용"""
        if self.current_history_item:
            # 🆕 prompt_context의 main_prompt를 우선적으로 사용 (\n\n 포함 원본)
            if (hasattr(self.current_history_item, 'prompt_context') and 
                self.current_history_item.prompt_context and 
                'main_prompt' in self.current_history_item.prompt_context and
                self.current_history_item.prompt_context['main_prompt']):
                
                prompt_to_load = self.current_history_item.prompt_context['main_prompt']
                print(f"✅ 원본 프롬프트 불러오기 (main_prompt): {prompt_to_load[:50]}...")
                self.load_prompt_to_main_ui.emit(prompt_to_load)
                
            else:
                # 🔄 폴백: main_prompt가 없으면 기존 방식 사용
                info = self.current_history_item.info_text
                positive_prompt = info.split('Negative prompt:')[0].strip()
                print(f"✅ 프롬프트 불러오기 (info_text 폴백): {positive_prompt[:50]}...")
                self.load_prompt_to_main_ui.emit(positive_prompt)

    def _reroll_current_prompt(self):
        """현재 표시 중인 이미지의 프롬프트로 다시 생성을 요청합니다."""
        if self.current_history_item and self.current_history_item.source_row is not None:
            self.instant_generation_requested.emit(self.current_history_item.source_row)

    def _show_current_comfyui_workflow(self):
        """🆕 현재 이미지의 ComfyUI 워크플로우를 표시합니다."""
        if self.current_history_item and self.current_history_item.comfyui_workflow:
            # HistoryItemWidget의 show_comfyui_workflow 메소드를 재사용
            temp_widget = HistoryItemWidget(self.current_history_item, self, self.app_context)
            temp_widget.show_comfyui_workflow()

    def _save_current_comfyui_workflow(self):
        """🆕 현재 이미지의 ComfyUI 워크플로우를 저장합니다."""
        if self.current_history_item and self.current_history_item.comfyui_workflow:
            # HistoryItemWidget의 save_comfyui_workflow 메소드를 재사용
            temp_widget = HistoryItemWidget(self.current_history_item, self, self.app_context)
            temp_widget.save_comfyui_workflow()

    def _restore_current_generation_params(self):
        """🆕 현재 이미지의 생성 파라미터를 복원합니다."""
        if self.current_history_item:
            # HistoryItemWidget의 restore_generation_params 메소드를 재사용
            temp_widget = HistoryItemWidget(self.current_history_item, self, self.app_context)
            temp_widget.restore_generation_params()

    def _show_current_metadata(self):
        """🆕 현재 이미지의 전체 메타데이터를 표시합니다."""
        if self.current_history_item:
            # HistoryItemWidget의 show_full_metadata 메소드를 재사용
            temp_widget = HistoryItemWidget(self.current_history_item, self, self.app_context)
            temp_widget.show_full_metadata()

    # 🆕 ComfyUI 메타데이터 처리 메소드들
    def strip_comfyui_metadata(self, image_object):
        """ComfyUI 메타데이터를 제거한 깨끗한 이미지 반환"""
        try:
            print("🧹 ComfyUI 이미지 메타데이터 정리 시작")
            
            # ComfyUI 메타데이터 추출 및 저장
            comfyui_metadata = {}
            if hasattr(image_object, 'info') and image_object.info:
                print(f"메타데이터 키: {list(image_object.info.keys())}")
                
                # ComfyUI가 사용하는 주요 메타데이터 키들
                comfyui_keys = ['workflow', 'prompt', 'parameters', 'ComfyUI']
                
                for key in image_object.info:
                    if any(comfyui_key.lower() in key.lower() for comfyui_key in comfyui_keys):
                        comfyui_metadata[key] = image_object.info[key]
                        print(f"  - ComfyUI 메타데이터 발견: {key} ({len(str(image_object.info[key]))} chars)")
            
            # 새로운 이미지 생성 (메타데이터 없음)
            clean_image = Image.new(image_object.mode, image_object.size)
            clean_image.paste(image_object)
            
            # 기본 정보만 유지 (Qt 호환성 확보)
            clean_info = {}
            safe_keys = ['dpi', 'aspect']  # Qt가 안전하게 처리할 수 있는 키들
            
            for key in safe_keys:
                if hasattr(image_object, 'info') and image_object.info and key in image_object.info:
                    clean_info[key] = image_object.info[key]
            
            clean_image.info = clean_info
            
            print(f"✅ ComfyUI 메타데이터 제거 완료: {image_object.size}")
            print(f"  - 제거된 ComfyUI 메타데이터: {len(comfyui_metadata)}개")
            print(f"  - 유지된 안전한 메타데이터: {len(clean_info)}개")
            
            return clean_image, comfyui_metadata
            
        except Exception as e:
            print(f"⚠️ 메타데이터 제거 실패, 원본 사용: {e}")
            return image_object, {}

    def extract_comfyui_workflow_info(self, comfyui_metadata):
        """ComfyUI 메타데이터에서 유용한 정보 추출"""
        try:
            workflow_info = {}
            
            for key, value in comfyui_metadata.items():
                if 'workflow' in key.lower():
                    try:
                        if isinstance(value, str):
                            workflow_data = json.loads(value)
                            workflow_info['workflow'] = workflow_data
                            print(f"✅ 워크플로우 데이터 파싱 성공: {len(workflow_data)} 노드")
                    except json.JSONDecodeError:
                        print(f"⚠️ 워크플로우 JSON 파싱 실패: {key}")
                        
                elif 'prompt' in key.lower():
                    try:
                        if isinstance(value, str):
                            prompt_data = json.loads(value)
                            workflow_info['prompt'] = prompt_data
                            print(f"✅ 프롬프트 데이터 파싱 성공")
                    except json.JSONDecodeError:
                        print(f"⚠️ 프롬프트 JSON 파싱 실패: {key}")
            
            return workflow_info
            
        except Exception as e:
            print(f"❌ ComfyUI 정보 추출 실패: {e}")
            return {}

    def create_safe_thumbnail_for_comfyui(self, image_object, target_size=128):
        """ComfyUI 이미지 전용 안전한 썸네일 생성"""
        try:
            print("🎨 ComfyUI 이미지 썸네일 생성 시작")
            
            # 1. ComfyUI 메타데이터 정리
            clean_image, comfyui_metadata = self.strip_comfyui_metadata(image_object)
            
            # 2. ComfyUI 워크플로우 정보 추출 (나중에 사용할 수 있도록)
            workflow_info = self.extract_comfyui_workflow_info(comfyui_metadata)
            
            # 3. 컬러 모드 정규화
            if clean_image.mode in ('RGBA', 'LA', 'P'):
                # 투명도 처리
                background = Image.new('RGB', clean_image.size, (255, 255, 255))
                if clean_image.mode == 'P':
                    clean_image = clean_image.convert('RGBA')
                
                if clean_image.mode in ('RGBA', 'LA'):
                    background.paste(clean_image, mask=clean_image.split()[-1])
                else:
                    background.paste(clean_image)
                clean_image = background
            elif clean_image.mode not in ('RGB', 'L'):
                clean_image = clean_image.convert('RGB')
            
            # 4. PIL에서 먼저 리사이즈 (더 효율적이고 안전)
            original_size = clean_image.size
            
            # 비율 유지하면서 리사이즈
            if original_size[0] > original_size[1]:
                new_width = target_size
                new_height = int((target_size * original_size[1]) / original_size[0])
            else:
                new_height = target_size
                new_width = int((target_size * original_size[0]) / original_size[1])
            
            # 고품질 리샘플링으로 리사이즈
            resized_image = clean_image.resize(
                (new_width, new_height), 
                Image.Resampling.LANCZOS
            )
            
            # 5. 완전히 깨끗한 PNG로 변환
            img_buffer = BytesIO()
            resized_image.save(
                img_buffer, 
                format='PNG', 
                optimize=True,
                # PNG 메타데이터 완전 제거
                pnginfo=None
            )
            img_buffer.seek(0)
            
            # 6. QPixmap으로 안전하게 로드
            pixmap = QPixmap()
            success = pixmap.loadFromData(img_buffer.getvalue(), 'PNG')
            
            if not success:
                print("❌ QPixmap 로드 실패")
                return None, workflow_info
            
            print(f"✅ ComfyUI 썸네일 생성 성공: {pixmap.size()}")
            
            # 7. 메모리 정리
            img_buffer.close()
            del clean_image, resized_image, img_buffer
            
            return pixmap, workflow_info
            
        except Exception as e:
            print(f"❌ ComfyUI 썸네일 생성 실패: {e}")
            import traceback
            traceback.print_exc()
            return None, {}

    def save_image_with_metadata(self, filename: str, image_bytes: bytes, info_text: str, as_webp=False):
        """
        [DEPRECATED] 하위 호환성을 위한 래퍼 메서드

        ⚠️ 이 메서드는 더 이상 사용되지 않습니다.
        새 코드는 app_context.image_crud_controller.save_image()를 직접 사용하세요.

        info_text 매개변수는 무시됩니다 (ImageCrudController가 메타데이터를 자동 처리).
        """
        print(f"⚠️ [DEPRECATED] save_image_with_metadata 호출됨. ImageCrudController 사용 권장.")

        # ✅ ImageCrudController로 위임 (파일명 무시, 컨트롤러가 자동 생성)
        success, filepath, error = self.image_crud.save_image(
            image_bytes=image_bytes,
            as_webp=as_webp
        )

        if success:
            return True
        else:
            print(f"❌ 저장 실패: {error}")
            return False

    def toggle_history_panel(self):
        self.history_visible = not self.history_visible
        self.image_history_window.setVisible(self.history_visible)
        self.toggle_history_button.setText("📜 히스토리 숨기기" if self.history_visible else "📜 히스토리 보이기")
        self.toggle_history_button.setChecked(self.history_visible)

    def update_image(self, image: Image.Image):
        """
        WebP 등 다양한 형식을 지원하는 안전한 이미지 업데이트 (ComfyUI 메타데이터 처리 포함)
        """
        if not isinstance(image, Image.Image):
            self.main_image_label.setFullPixmap(None)
            return
            
        try:
            # 🆕 ComfyUI 이미지인지 확인
            has_comfyui_metadata = False
            if hasattr(image, 'info') and image.info:
                comfyui_keys = ['workflow', 'prompt', 'parameters', 'ComfyUI']
                has_comfyui_metadata = any(
                    any(comfyui_key.lower() in str(key).lower() for comfyui_key in comfyui_keys)
                    for key in image.info.keys()
                )
            
            # 🎨 [수정된 부분] ComfyUI 이미지를 감지하면 메타데이터를 제거하는 대신,
            # WebP와 동일하게 메모리 내에서 PNG로 재처리하여 완벽하게 정제합니다.
            # 이 방식은 Qt와 충돌을 일으키는 모든 비표준 데이터를 제거하는 가장 안전한 방법입니다.
            if (hasattr(image, 'format') and image.format == 'WEBP') or has_comfyui_metadata:
                if has_comfyui_metadata:
                    print("🎨 ComfyUI 이미지 감지됨 - 안전한 PNG 변환 처리 시작")
                else:
                    print("🔄 WebP 이미지를 PNG로 변환 중...")

                import io
                png_buffer = io.BytesIO()
                
                # RGBA 모드로 변환하여 투명도 정보 보존
                if image.mode != 'RGBA':
                    image = image.convert('RGBA')
                
                # PNG로 저장하며 모든 비표준 메타데이터를 제거
                image.save(png_buffer, format='PNG')
                png_buffer.seek(0)
                
                # 정제된 PNG 데이터로부터 새로운 PIL Image 객체 생성
                image = Image.open(png_buffer)

                redirect_event = "generation_completed_for_redirect"
                if redirect_event in self.app_context.subscribers and self.app_context.subscribers[redirect_event]:
                    self.app_context.publish(redirect_event, image)

                # ImageQt.ImageQt를 통해 QImage로 변환
                q_image = ImageQt.ImageQt(image)
                png_buffer.close()
            else:
                redirect_event = "generation_completed_for_redirect"
                if redirect_event in self.app_context.subscribers and self.app_context.subscribers[redirect_event]:
                    self.app_context.publish(redirect_event, image)
                q_image = ImageQt.ImageQt(image)
            
            pixmap = QPixmap.fromImage(q_image)
            
            if pixmap.isNull():
                print("❌ QPixmap 변환 실패")
                self.main_image_label.setText("이미지를 표시할 수 없습니다.")
                return
                
            self.main_image_label.setFullPixmap(pixmap)
            print("✅ 이미지 업데이트 완료")
            
        except Exception as e:
            print(f"❌ 이미지 표시 오류: {e}")
            import traceback
            traceback.print_exc()
            self.main_image_label.setText("이미지를 표시할 수 없습니다.")

    def update_info(self, text: str):
        """정보 텍스트 업데이트"""
        self.info_textbox.setText(text)

    def clear_all(self):
        deleted = self.image_history_window.remove_current_item()
        # ↓ 삭제 후 남은 항목 있으면 갱신, 없으면 초기화
        if self.image_history_window.current_selected_widget:
            self.display_history_item(self.image_history_window.current_selected_widget.history_item)
        else:
            self.update_image(None)
            self.update_info("")

    def create_thumbnail_with_background(self, source_image: Image.Image) -> QPixmap:
        """
        WebP 등 다양한 형식을 지원하는 안전한 썸네일 생성 (ComfyUI 메타데이터 처리 포함)
        """
        try:
            # 🆕 ComfyUI 이미지인지 확인
            has_comfyui_metadata = False
            if hasattr(source_image, 'info') and source_image.info:
                comfyui_keys = ['workflow', 'prompt', 'parameters', 'ComfyUI']
                has_comfyui_metadata = any(
                    any(comfyui_key.lower() in str(key).lower() for comfyui_key in comfyui_keys)
                    for key in source_image.info.keys()
                )
            
            # ComfyUI 이미지의 경우 전용 함수 사용
            if has_comfyui_metadata:
                print("🎨 ComfyUI 썸네일 생성 모드")
                pixmap, workflow_info = self.create_safe_thumbnail_for_comfyui(source_image, 128)
                if pixmap and not pixmap.isNull():
                    # 128x128 배경에 중앙 정렬
                    canvas = QPixmap(128, 128)
                    canvas.fill(QColor("black"))
                    
                    x = (128 - pixmap.width()) // 2
                    y = (128 - pixmap.height()) // 2
                    
                    painter = QPainter(canvas)
                    painter.drawPixmap(x, y, pixmap)
                    painter.end()
                    
                    return canvas
            
            # 기존 로직 (NAI, WebUI 등)
            # WebP 형식인 경우 PNG로 변환
            if hasattr(source_image, 'format') and source_image.format == 'WEBP':
                print("🔄 WebP 이미지를 PNG로 변환 중...")
                # 메모리 내에서 PNG로 변환
                import io
                png_buffer = io.BytesIO()
                # RGBA 모드로 변환하여 투명도 처리
                if source_image.mode != 'RGBA':
                    source_image = source_image.convert('RGBA')
                source_image.save(png_buffer, format='PNG')
                png_buffer.seek(0)
                
                # PNG로 변환된 이미지 다시 열기
                converted_image = Image.open(png_buffer)
                source_pixmap = QPixmap.fromImage(ImageQt.ImageQt(converted_image))
                png_buffer.close()
            else:
                # PNG나 기타 형식은 기존 방식 사용
                source_pixmap = QPixmap.fromImage(ImageQt.ImageQt(source_image))
            
            # 썸네일이 제대로 생성되었는지 확인
            if source_pixmap.isNull():
                print("❌ 썸네일 생성 실패: QPixmap이 null입니다.")
                # 기본 플레이스홀더 이미지 생성
                placeholder = QPixmap(128, 128)
                placeholder.fill(QColor("gray"))
                return placeholder
            
            # 1. 원본 비율을 유지하며 가장 긴 쪽이 128px이 되도록 리사이즈
            scaled_pixmap = source_pixmap.scaled(
                QSize(128, 128),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            
            # 2. 128x128 크기의 검은색 배경 QPixmap 생성
            canvas = QPixmap(128, 128)
            canvas.fill(QColor("black"))
            
            # 3. 배경의 중앙에 리사이즈된 이미지를 그릴 위치 계산
            x = (128 - scaled_pixmap.width()) // 2
            y = (128 - scaled_pixmap.height()) // 2
            
            # 4. QPainter를 사용하여 배경 위에 이미지 그리기
            painter = QPainter(canvas)
            painter.drawPixmap(x, y, scaled_pixmap)
            painter.end()
            
            print("✅ 썸네일 생성 완료")
            return canvas
            
        except Exception as e:
            print(f"❌ 썸네일 생성 실패: {e}")
            import traceback
            traceback.print_exc()
            # 기본 플레이스홀더 이미지 생성
            placeholder = QPixmap(128, 128)
            placeholder.fill(QColor("gray"))
            return placeholder

    def add_to_history(self, image: Image.Image, raw_bytes: bytes, info: str, source_row: pd.Series, generation_result: dict = None):
        if not isinstance(image, Image.Image):
            return

        # ⬇️ [핵심 수정] 외부에서 받은 info 대신, 이미지에서 직접 정보를 추출합니다.
        info_text = self.extract_info_from_image(image, info)
        # ⬆️ 이 한 줄로 모든 정보 추출 로직이 처리됩니다.

        # ComfyUI 워크플로우 정보는 별도로 관리 (컨텍스트 메뉴용)
        comfyui_workflow = {}
        if 'prompt' in image.info:
            try:
                workflow_data = json.loads(image.info['prompt'])
                comfyui_workflow['workflow'] = workflow_data
            except Exception:
                pass
        
        # 썸네일 생성
        thumbnail_pixmap = self.create_thumbnail_with_background(image)
        
        # 자동 저장 로직
        filepath = None
        is_webp = self.save_as_webp_checkbox.isChecked()
        if self.auto_save_checkbox.isChecked():
            # 🆕 분류 정보 생성 (자동 저장용)
            prompt_context = generation_result.get('prompt_context', {}) if generation_result else {}
            main_tags = prompt_context.get('main_tags', [])

            # 🔍 디버깅 (필요시 주석 해제)
            # print(f"[DEBUG] generation_result keys: {list(generation_result.keys()) if generation_result else 'None'}")
            # print(f"[DEBUG] prompt_context keys: {list(prompt_context.keys()) if prompt_context else 'None'}")
            # print(f"[DEBUG] main_tags from prompt_context: {main_tags[:10] if main_tags else '(empty)'}")

            # 🆕 Fallback: main_tags가 비어있으면 프롬프트에서 직접 추출
            if not main_tags and info_text:
                # generation_result에서 최종 프롬프트 추출
                final_prompt = generation_result.get('generation_params', {}).get('input', '') if generation_result else ''
                if final_prompt:
                    import re

                    # 1. 먼저 쉼표로 분리
                    raw_tags = final_prompt.split(',')

                    # 2. 각 태그에서 NAI 가중치 제거
                    cleaned_tags = []
                    for tag in raw_tags:
                        tag = tag.strip()
                        if not tag:
                            continue

                        # NAI 가중치 패턴 제거: "1.25::tag::" → "tag" 또는 "-1.15::tag::" → "tag"
                        # 패턴: 숫자(선택적 음수, 소수점) + :: + 내용 + :: (끝 ::는 선택적)
                        tag = re.sub(r'^-?\d+\.?\d*::', '', tag)  # 앞쪽 가중치 제거
                        tag = re.sub(r'::$', '', tag)  # 뒤쪽 :: 제거
                        tag = tag.strip()

                        if tag:
                            cleaned_tags.append(tag)

                    main_tags = cleaned_tags
                    # print(f"[DEBUG] 🔧 Fallback: 프롬프트에서 추출한 tags ({len(main_tags)}개)")
                    # print(f"[DEBUG]   처음 10개: {main_tags[:10]}")
                    # print(f"[DEBUG]   'solo' in tags: {'solo' in main_tags}")
                    # print(f"[DEBUG]   'holding' in tags: {'holding' in main_tags}")
                    # print(f"[DEBUG]   'standing' in tags: {'standing' in main_tags}")

            classification_info = {
                "method": self.app_context.image_crud_controller.get_classification_method(),
                "prompt": info_text,
                "image_size": image.size if image else (0, 0),
                "tags": main_tags,
                "backend_type": generation_result.get('backend_type', 'NAI') if generation_result else 'NAI',
            }

            # ✅ ImageCrudController를 통한 저장 (분류 정보 포함)
            success, saved_filepath, error = self.image_crud.save_image(
                image_bytes=raw_bytes,
                as_webp=is_webp,
                classification_info=classification_info
            )

            if success:
                filepath = saved_filepath
            else:
                print(f"❌ 자동 저장 실패: {error}")
                filepath = None

        # 🆕 확장된 메타데이터 수집
        enhanced_metadata = {}
        if generation_result:
            import time
            enhanced_metadata = {
                'generation_params': generation_result.get('generation_params', {}),
                'prompt_context': generation_result.get('prompt_context', {}),
                'api_metadata': generation_result.get('api_metadata', {}),
                'creation_timestamp': generation_result.get('creation_timestamp', time.strftime('%Y-%m-%d %H:%M:%S')),
                'backend_type': generation_result.get('backend_type', 'NAI')
            }
        else:
            # 기본값 설정 (이전 버전과의 호환성)
            import time
            enhanced_metadata = {
                'generation_params': {},
                'prompt_context': {},
                'api_metadata': {},
                'creation_timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
                'backend_type': 'NAI'
            }

        history_item = HistoryItem(
            image=image, 
            thumbnail=thumbnail_pixmap,
            raw_bytes=raw_bytes, 
            info_text=info_text,  # 새로 추출한 텍스트로 저장
            source_row=source_row, 
            filepath=str(filepath) if filepath else None,
            comfyui_workflow=comfyui_workflow,
            # 🆕 확장된 메타데이터 필드들
            **enhanced_metadata
        )

        if self.image_history_window:
            self.image_history_window.add_history_item(history_item)
            
            # 🧠 히스토리 큐 제한 체크
            self.check_and_apply_history_limit()
        
        # NAI 모드에서 히스토리 아이템 추가 시 Anlas 업데이트
        if self.app_context.current_api_mode == "NAI":
            if hasattr(self.app_context, 'main_window') and hasattr(self.app_context.main_window, 'update_anlas_display'):
                self.app_context.main_window.update_anlas_display()

    def display_history_item(self, item: HistoryItem):
        """[수정] 선택된 히스토리 아이템의 내용을 메인 뷰어에 표시"""
        self.current_history_item = item # 현재 아이템 추적
        self.update_image(item.image)
        self.update_info(item.info_text) # 저장된 생성 정보로 업데이트
        self._update_enhance_button_state()

    def _create_classification_info(self, item: HistoryItem) -> dict:
        """
        [신규] HistoryItem에서 classification_info를 생성합니다.

        Parameters:
            item (HistoryItem): 히스토리 아이템

        Returns:
            dict: classification_info
        """
        tags = item.prompt_context.get("main_tags", []) if isinstance(item.prompt_context, dict) else []

        # 🔍 디버깅 (필요시 주석 해제)
        # print(f"[DEBUG] _create_classification_info - tags: {tags[:10] if tags else '(empty)'}")
        # print(f"[DEBUG] prompt_context type: {type(item.prompt_context)}")
        # if isinstance(item.prompt_context, dict):
        #     print(f"[DEBUG] prompt_context keys: {list(item.prompt_context.keys())}")

        return {
            "method": self.app_context.image_crud_controller.get_classification_method(),
            "prompt": item.info_text,
            "image_size": item.image.size if item.image else (0, 0),
            "tags": tags,
            "backend_type": item.backend_type,
        }

    def save_current_image(self):
        """[리팩토링] '이미지 저장' 버튼 클릭 시, 대화상자 없이 바로 저장"""
        is_webp = self.save_as_webp_checkbox.isChecked()

        if not hasattr(self, 'current_history_item') or not self.current_history_item:
            # status_bar 접근 방법 수정
            if hasattr(self.app_context, 'main_window') and hasattr(self.app_context.main_window, 'status_bar'):
                self.app_context.main_window.status_bar.showMessage("⚠️ 저장할 이미지를 목록에서 선택해주세요.", 3000)
            return

        item = self.current_history_item
        # [수정] 파일 경로가 있고, 실제 파일도 존재하면 저장 건너뛰기
        if item.filepath and os.path.exists(item.filepath):
            self.app_context.main_window.status_bar.showMessage(f"✅ 이미 저장된 파일입니다: {os.path.basename(item.filepath)}", 3000)
            return

        if not item.raw_bytes:
            if hasattr(self.app_context, 'main_window') and hasattr(self.app_context.main_window, 'status_bar'):
                self.app_context.main_window.status_bar.showMessage("⚠️ 저장할 이미지의 원본 데이터가 없습니다.", 3000)
            return

        # 🆕 분류 정보 생성
        classification_info = self._create_classification_info(item)

        # ✅ ImageCrudController를 통한 저장 (에러 메시지 및 분류 정보 포함)
        success, filepath, error = self.image_crud.save_image(
            image_bytes=item.raw_bytes,
            as_webp=is_webp,
            classification_info=classification_info
        )

        if success:
            item.filepath = filepath  # [핵심] 저장 성공 시 HistoryItem에 파일 경로 주입
            self.app_context.main_window.status_bar.showMessage(
                f"✅ 이미지 저장 완료: {os.path.basename(filepath)}", 3000
            )
        else:
            self.app_context.main_window.status_bar.showMessage(
                f"❌ 저장 실패: {error}", 5000
            )

    
    def extract_info_from_image(self, image: Image.Image, _info):
        """
        [신규] PIL 이미지 객체에서 다양한 소스(ComfyUI, WebUI 등)의 생성 정보를 추출합니다.
        가장 구체적인 형식부터 확인하여 정확도를 높입니다.
        """
        if not hasattr(image, 'info'):
            return "이미지에 메타데이터가 없습니다."

        info = image.info
        source_info = ""

        # 1. ComfyUI 확인 ('prompt' 키, JSON 형식)
        if 'prompt' in info and isinstance(info.get('prompt'), str):
            try:
                # ComfyUI 워크플로우는 JSON 형식이므로 파싱 시도
                prompt_data = json.loads(info['prompt'])
                if isinstance(prompt_data, dict): # 유효한 JSON 객체인지 확인
                    source_info = "[ComfyUI] "
                    # 주요 정보 추출 (예시)
                    positive_prompt = next((node['inputs']['text'] for node in prompt_data.values() if node.get('class_type') == 'CLIPTextEncode'), "N/A")
                    negative_prompt = "N/A" # 필요시 네거티브 노드 파싱 로직 추가
                    ksampler_node = next((node['inputs'] for node in prompt_data.values() if node.get('class_type') == 'KSampler'), None)

                    source_info += f"Prompt: {positive_prompt}\n"
                    if ksampler_node:
                        source_info += f"Steps: {ksampler_node.get('steps')}, Sampler: {ksampler_node.get('sampler_name')}, CFG: {ksampler_node.get('cfg')}, Seed: {ksampler_node.get('seed')}"
                    return source_info
            except (json.JSONDecodeError, TypeError):
                # JSON이 아니면 다음 단계로
                pass

        # 2. A1111 WebUI 확인 ('parameters' 키, 텍스트 형식)
        if 'parameters' in info and isinstance(info.get('parameters'), str):
            return f"[WebUI] {info['parameters']}"

        # 3. Novel AI 확인 ('Comment' 키, 텍스트 형식)
        if 'Comment' in info and isinstance(info.get('Comment'), str):
             return f"[Novel AI] {info['Comment']}"

        # 4. 표준 EXIF 확인 (위에서 정보를 못 찾았을 경우의 최후 수단)
        try:
            return f"Source: EXIF (UserComment) {_info}"
        except Exception:
            pass

        return "추출할 수 있는 생성 정보가 없습니다."
    
    def open_folder(self):
        import sys, subprocess
        folder = str(self.app_context.session_save_path)
        
        # 폴더가 존재하지 않으면 생성
        if not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)
        
        if sys.platform.startswith('darwin'):
            subprocess.run(['open', folder])
        elif os.name == 'nt':
            os.startfile(folder)
        elif os.name == 'posix':
            subprocess.run(['xdg-open', folder])

    def copy_image_to_clipboard(self, fmt='PNG'):
        from PyQt6.QtWidgets import QApplication
        import io
        pil_img = self.current_history_item.image
        buf = io.BytesIO()
        if fmt == 'PNG':
            pil_img.save(buf, format='PNG')
        else:
            pil_img.save(buf, format='WEBP', quality=90, method=6)
        buf.seek(0)
        qimg = QPixmap()
        qimg.loadFromData(buf.getvalue())
        QApplication.clipboard().setPixmap(qimg)
        print(f"✅ 이미지가 클립보드에 복사되었습니다. ({fmt})")
    
    def _show_styled_message_main(self, title, message, msg_type='warning'):
        """메인 이미지용 다크 테마 스타일이 적용된 QMessageBox를 표시합니다."""
        from PyQt6.QtWidgets import QMessageBox
        
        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(message)
        
        if msg_type == 'warning':
            msg.setIcon(QMessageBox.Icon.Warning)
        elif msg_type == 'critical':
            msg.setIcon(QMessageBox.Icon.Critical)
        elif msg_type == 'information':
            msg.setIcon(QMessageBox.Icon.Information)
        
        # 다크 테마 스타일 적용
        msg.setStyleSheet(f"""
            QMessageBox {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
            }}
            QMessageBox QLabel {{
                color: {DARK_COLORS['text_primary']};
                background-color: transparent;
            }}
            QMessageBox QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                padding: 6px 20px;
                border-radius: 4px;
                min-width: 80px;
            }}
            QMessageBox QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border: 1px solid {DARK_COLORS['accent_blue']};
            }}
            QMessageBox QPushButton:pressed {{
                background-color: {DARK_COLORS['bg_pressed']};
            }}
        """)
        
        msg.exec()
    
    # ═══════════════════════════════════════════════════════════
    #  Enhance (img2img 고해상도 보강)
    # ═══════════════════════════════════════════════════════════

    def _update_enhance_button_text(self):
        """Enhance 버튼 라벨을 현재 설정에 맞게 갱신"""
        if hasattr(self, 'enhance_button'):
            self.enhance_button.setText(
                f"✨Enhance x{self._enhance_upscale:g} | {self._enhance_strength:.1f}"
            )

    def _update_enhance_button_state(self):
        """조건에 따라 Enhance 버튼 활성/비활성"""
        if not hasattr(self, 'enhance_button'):
            return
        enabled = (
            self.current_history_item is not None
            and self.current_history_item.image is not None
            and getattr(self.app_context, 'current_api_mode', '') == 'NAI'
            and bool(getattr(self.current_history_item, 'generation_params', None))
        )
        self.enhance_button.setEnabled(enabled)

    @staticmethod
    def _round_to_64(value: float) -> int:
        return math.ceil(value / 64) * 64

    def _show_enhance_settings(self):
        """Enhance 설정 다이얼로그 열기"""
        dialog = EnhanceSettingsDialog(self._enhance_upscale, self._enhance_strength, self._enhance_noise, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._enhance_upscale, self._enhance_strength, self._enhance_noise = dialog.get_settings()
            self._update_enhance_button_text()
            self.save_settings()

    def _execute_enhance(self):
        """Enhance 실행 — img2img API 호출"""
        from PyQt6.QtWidgets import QProgressDialog
        import io, copy

        item = self.current_history_item
        if not item or not item.image:
            self._show_styled_message_main("오류", "Enhance 할 이미지가 없습니다.", 'warning')
            return
        if getattr(self.app_context, 'current_api_mode', '') != 'NAI':
            self._show_styled_message_main("오류", "Enhance는 NAI 모드에서만 사용할 수 있습니다.", 'warning')
            return
        if not getattr(item, 'generation_params', None):
            self._show_styled_message_main("오류", "생성 파라미터가 없는 이미지입니다.", 'warning')
            return

        # x1 Enhance는 동일 해상도 img2img → 생성 중이면 API 충돌 방지
        if self._enhance_upscale == 1.0:
            gen_ctrl = getattr(self.app_context, 'generation_controller', None)
            if gen_ctrl and getattr(gen_ctrl, 'is_generating', False):
                self._show_styled_message_main(
                    "Enhance 대기", "이미지 생성 중에는 x1 Enhance를 사용할 수 없습니다.\n생성 완료 후 다시 시도해주세요.", 'warning')
                return

        # 이미지 → PNG bytes
        buf = io.BytesIO()
        item.image.save(buf, format='PNG')
        image_bytes = buf.getvalue()

        # 해상도 계산
        orig_w, orig_h = item.image.size
        if self._enhance_upscale == 1.5:
            new_w = self._round_to_64(orig_w * 1.5)
            new_h = self._round_to_64(orig_h * 1.5)
        else:
            new_w, new_h = orig_w, orig_h

        # 파라미터 구성
        params = copy.deepcopy(item.generation_params)
        params['image_bytes'] = image_bytes
        params['strength'] = self._enhance_strength
        params['noise'] = self._enhance_noise
        params['width'] = new_w
        params['height'] = new_h
        params['api_mode'] = 'NAI'
        # inpaint 관련 키 제거 — 반드시 img2img로 실행
        params.pop('type', None)
        params.pop('mask_bytes', None)

        # 진행 다이얼로그
        progress = QProgressDialog("Enhance 처리 중...", None, 0, 0, self)
        progress.setWindowTitle("Enhance")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setCancelButton(None)
        progress.show()

        self.enhance_button.setEnabled(False)

        # Worker (inline)
        class EnhanceWorker(QObject):
            finished = pyqtSignal(dict)

            def __init__(self, api_service, params):
                super().__init__()
                self.api_service = api_service
                self.params = params

            def run(self):
                result = self.api_service.call_generation_api(self.params)
                self.finished.emit(result)

        self._enhance_thread = QThread()
        self._enhance_worker = EnhanceWorker(self.app_context.api_service, params)
        self._enhance_worker.moveToThread(self._enhance_thread)

        self._enhance_thread.started.connect(self._enhance_worker.run)
        self._enhance_worker.finished.connect(
            lambda result: self._handle_enhance_result(result, progress, orig_w, orig_h, new_w, new_h)
        )
        self._enhance_worker.finished.connect(self._enhance_thread.quit)
        self._enhance_worker.finished.connect(self._enhance_worker.deleteLater)
        self._enhance_thread.finished.connect(self._enhance_thread.deleteLater)

        self._enhance_thread.start()

    def _handle_enhance_result(self, result: dict, progress, orig_w, orig_h, new_w, new_h):
        """Enhance API 결과 처리"""
        import io as _io
        progress.close()
        self._update_enhance_button_state()

        if result.get('status') == 'success':
            pil_image = result.get('image')
            raw_bytes = result.get('raw_bytes')

            if pil_image is None and raw_bytes:
                pil_image = Image.open(_io.BytesIO(raw_bytes))
            if pil_image is None:
                self._show_styled_message_main("Enhance 실패", "결과 이미지를 처리할 수 없습니다.", 'critical')
                return

            info_text = self.current_history_item.info_text
            info_text += (
                f"\nEnhanced: x{self._enhance_upscale:g}, strength={self._enhance_strength:.1f}, noise={self._enhance_noise:.1f}"
                f" ({new_w}x{new_h})"
            )

            source_row = getattr(self.current_history_item, 'source_row', None)
            self.add_to_history(pil_image, raw_bytes, info_text, source_row)
            print(f"✅ Enhance 성공: {orig_w}x{orig_h} → {new_w}x{new_h}")
        else:
            error_msg = result.get('message', '알 수 없는 오류')
            self._show_styled_message_main("Enhance 실패", error_msg, 'critical')

    def upscale_current_image_nai(self):
        """메인 이미지를 NAI API를 사용하여 2배 업스케일합니다."""
        from PyQt6.QtWidgets import QProgressDialog
        from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QBuffer, QIODevice
        from PyQt6.QtGui import QPixmap
        from PIL import Image
        import io
        
        if not self.current_history_item:
            self._show_styled_message_main("오류", "업스케일할 이미지가 없습니다.", 'warning')
            return
        
        # 현재 이미지를 QPixmap으로 변환
        pil_img = self.current_history_item.image
        buf = io.BytesIO()
        pil_img.save(buf, format='PNG')
        buf.seek(0)
        current_pixmap = QPixmap()
        current_pixmap.loadFromData(buf.getvalue())
        
        # 진행 상황 다이얼로그 생성
        progress = QProgressDialog("이미지 업스케일 중...", None, 0, 0, self)
        progress.setWindowTitle("NAI 업스케일")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setCancelButton(None)
        progress.show()
        
        # Worker 클래스 정의 (메서드 내부에 정의)
        class UpscaleWorker(QObject):
            finished = pyqtSignal(dict)
            
            def __init__(self, api_service, pixmap):
                super().__init__()
                self.api_service = api_service
                self.pixmap = pixmap
            
            def run(self):
                result = self.api_service.upscale_NAI(self.pixmap)
                self.finished.emit(result)
        
        # Worker 스레드 설정
        self.upscale_thread = QThread()
        self.upscale_worker = UpscaleWorker(self.app_context.api_service, current_pixmap)
        self.upscale_worker.moveToThread(self.upscale_thread)
        
        # 시그널 연결
        self.upscale_thread.started.connect(self.upscale_worker.run)
        self.upscale_worker.finished.connect(
            lambda result: self._handle_main_upscale_result(result, progress)
        )
        self.upscale_worker.finished.connect(self.upscale_thread.quit)
        self.upscale_worker.finished.connect(self.upscale_worker.deleteLater)
        self.upscale_thread.finished.connect(self.upscale_thread.deleteLater)
        
        # 스레드 시작
        self.upscale_thread.start()
    
    def _handle_main_upscale_result(self, result, progress):
        """메인 이미지 업스케일 결과를 처리합니다."""
        from PyQt6.QtCore import QBuffer, QIODevice
        from PIL import Image
        import io
        
        progress.close()
        
        if result['status'] == 'success':
            # QPixmap을 PIL Image로 변환
            upscaled_pixmap = result['image']
            
            # raw_bytes가 있으면 그대로 사용, 없으면 QPixmap에서 변환
            if 'raw_bytes' in result and result['raw_bytes']:
                image_data = result['raw_bytes']
            else:
                # QBuffer를 사용하여 QPixmap을 bytes로 변환
                qbuffer = QBuffer()
                qbuffer.open(QIODevice.OpenModeFlag.WriteOnly)
                upscaled_pixmap.save(qbuffer, "PNG")
                image_data = qbuffer.data().data()
                qbuffer.close()
            
            # bytes를 PIL Image로 변환
            buffer = io.BytesIO(image_data)
            upscaled_image = Image.open(buffer)
            
            # 기존 메타데이터 복사
            info_text = self.current_history_item.info_text + f"\nUpscaled: 2x ({upscaled_pixmap.width()}x{upscaled_pixmap.height()})"
            metadata = self.current_history_item.metadata.copy() if hasattr(self.current_history_item, 'metadata') else {}
            metadata['upscaled'] = True
            metadata['upscale_factor'] = 2
            
            # source_row 가져오기 (원본 이미지의 생성 정보)
            source_row = self.current_history_item.source_row if hasattr(self.current_history_item, 'source_row') else None
            
            # 히스토리에 추가 (raw_bytes 포함)
            self.add_to_history(upscaled_image, image_data, info_text, source_row)
            # 성공 메시지 제거 - 콘솔에만 출력
            print(f"✅ 업스케일 성공: {upscaled_pixmap.width()}x{upscaled_pixmap.height()}")
        else:
            self._show_styled_message_main("업스케일 실패", result['message'], 'critical')

    # [신규] 전체 다운로드 작업을 시작하는 메서드
    def start_download_all(self, clear_after=False):
        if not self.image_history_window.history_widgets:
            self.app_context.main_window.status_bar.showMessage("⚠️ 저장할 이미지가 없습니다.", 3000)
            return

        items_to_save = [w.history_item for w in self.image_history_window.history_widgets]
        items_to_save.reverse() # 오래된 이미지부터 순서대로 저장

        self.worker_thread = QThread()
        # ✅ ImageCrudController 전달
        self.downloader = AllImagesDownloader(self.image_crud)
        self.downloader.moveToThread(self.worker_thread)

        self.downloader.progress_updated.connect(self.on_download_progress)

        # 완료 후 동작 결정
        if clear_after:
            self.downloader.finished.connect(self.on_download_finished_and_clear)
        else:
            self.downloader.finished.connect(self.on_download_finished)

        # ✅ 간소화된 run() 시그니처 (save_path, save_counter 제거)
        self.worker_thread.started.connect(lambda: self.downloader.run(
            items_to_save,
            self.save_as_webp_checkbox.isChecked()
        ))

        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.advanced_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.worker_thread.start()

    # [신규] 워커 진행률 및 완료 신호를 처리할 슬롯들
    def on_download_progress(self, current, total, message):
        self.app_context.main_window.status_bar.showMessage(f"다운로드 중 ({current}/{total}): {message}")

    def on_download_finished(self, saved_count):
        self.app_context.main_window.status_bar.showMessage(f"✅ 전체 다운로드 완료. {saved_count}개 파일 저장됨.", 5000)
        # ✅ 카운터 증가 제거 (ImageCrudController가 자동 처리)
        self.advanced_button.setEnabled(True)
        self.save_button.setEnabled(True)
        if self.worker_thread: self.worker_thread.quit()

    def on_download_finished_and_clear(self, saved_count):
        self.on_download_finished(saved_count)
        self.image_history_window.clear_all_items()

    def clear_history_only(self):
        """다운로드 없이 히스토리만 정리하고 가비지 콜렉션을 수행합니다."""
        import gc
        
        if not self.image_history_window.history_widgets:
            self.app_context.main_window.status_bar.showMessage("⚠️ 정리할 히스토리가 없습니다.", 3000)
            return
        
        # 히스토리 정리
        self.image_history_window.clear_all_items()
        
        # 가비지 콜렉션 수행
        gc.collect()
        
        # 상태 메시지 표시
        self.app_context.main_window.status_bar.showMessage("🧹 히스토리 정리 완료", 3000)

    def create_memory_management_section(self):
        """메모리 관리 섹션을 메뉴에 추가합니다."""
        # 메모리 관리 위젯 컨테이너
        memory_widget = QWidget()
        memory_layout = QVBoxLayout(memory_widget)
        memory_layout.setContentsMargins(10, 5, 10, 5)
        memory_layout.setSpacing(5)
        
        # 섹션 제목
        title_label = QLabel("🧠 메모리 관리")
        title_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(16)}px;
            font-weight: bold;
            color: {DARK_COLORS['text_primary']};
            padding: 3px 0px;
        """)
        memory_layout.addWidget(title_label)
        
        # 히스토리 큐 제한 활성화 체크박스
        self.history_limit_enabled = QCheckBox("히스토리 큐 제한 활성화")
        self.history_limit_enabled.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.history_limit_enabled.toggled.connect(self.on_history_limit_toggled)
        memory_layout.addWidget(self.history_limit_enabled)
        
        # 최대 히스토리 길이 설정
        history_length_layout = QHBoxLayout()
        history_length_label = QLabel("최대 히스토리 길이:")
        history_length_label.setStyleSheet(f"""
            color: {DARK_COLORS['text_primary']};
            font-size: {get_scaled_font_size(14)}px;
        """)
        
        self.max_history_length = QSpinBox()
        self.max_history_length.setRange(100, 10000)
        self.max_history_length.setSingleStep(100)
        self.max_history_length.setValue(2000)
        self.max_history_length.setStyleSheet(f"""
            QSpinBox {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 4px;
                font-size: {get_scaled_font_size(14)}px;
                min-width: 80px;
            }}
            QSpinBox::up-button, QSpinBox::down-button {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
            }}
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        self.max_history_length.valueChanged.connect(self.save_memory_settings)
        
        history_length_layout.addWidget(history_length_label)
        history_length_layout.addWidget(self.max_history_length)
        history_length_layout.addStretch()
        memory_layout.addLayout(history_length_layout)
        
        # 최대 히스토리 길이 도달시 동작 설정
        action_label = QLabel("최대 히스토리 길이 도달시:")
        action_label.setStyleSheet(f"""
            color: {DARK_COLORS['text_primary']};
            font-size: {get_scaled_font_size(14)}px;
            font-weight: bold;
            margin-top: 5px;
        """)
        memory_layout.addWidget(action_label)
        
        # 라디오 버튼 그룹
        self.memory_action_group = QButtonGroup()
        
        self.auto_save_radio = QRadioButton("[1] 1장씩 자동저장+정리")
        self.auto_delete_radio = QRadioButton("[2] 1장씩 저장없이 삭제")
        self.stop_generation_radio = QRadioButton("[3] 자동생성 중단")
        
        # 기본값 설정
        self.auto_save_radio.setChecked(True)
        
        radio_style = f"""
            QRadioButton {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(13)}px;
                padding: 2px;
            }}
            QRadioButton::indicator {{
                width: 16px;
                height: 16px;
            }}
            QRadioButton::indicator::unchecked {{
                border: 2px solid {DARK_COLORS['border']};
                border-radius: 8px;
                background-color: {DARK_COLORS['bg_secondary']};
            }}
            QRadioButton::indicator::checked {{
                border: 2px solid {DARK_COLORS['accent_blue']};
                border-radius: 8px;
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """
        
        self.auto_save_radio.setStyleSheet(radio_style)
        self.auto_delete_radio.setStyleSheet(radio_style)
        self.stop_generation_radio.setStyleSheet(radio_style)
        
        self.memory_action_group.addButton(self.auto_save_radio, 1)
        self.memory_action_group.addButton(self.auto_delete_radio, 2)
        self.memory_action_group.addButton(self.stop_generation_radio, 3)
        self.memory_action_group.buttonClicked.connect(self.save_memory_settings)
        
        memory_layout.addWidget(self.auto_save_radio)
        memory_layout.addWidget(self.auto_delete_radio)
        memory_layout.addWidget(self.stop_generation_radio)
        
        # 초기 설정 비활성화
        self.update_memory_controls_state(False)
        
        # 위젯을 메뉴에 추가
        memory_action = QWidgetAction(self)
        memory_action.setDefaultWidget(memory_widget)
        self.advanced_menu.addAction(memory_action)
        
        # 설정 로드
        self.load_memory_settings()

    def on_history_limit_toggled(self, checked):
        """히스토리 제한 체크박스 상태 변경 처리"""
        self.update_memory_controls_state(checked)
        self.save_memory_settings()
    
    def update_memory_controls_state(self, enabled):
        """메모리 관리 컨트롤들의 활성화 상태 업데이트"""
        self.max_history_length.setEnabled(enabled)
        self.auto_save_radio.setEnabled(enabled)
        self.auto_delete_radio.setEnabled(enabled)
        self.stop_generation_radio.setEnabled(enabled)
    
    def save_memory_settings(self):
        """메모리 관리 설정 저장"""
        settings = {
            'history_limit_enabled': self.history_limit_enabled.isChecked(),
            'max_history_length': self.max_history_length.value(),
            'memory_action': self.memory_action_group.checkedId()
        }
        
        # 설정 파일에 저장
        settings_path = Path("save/memory_management.json")
        settings_path.parent.mkdir(exist_ok=True)
        
        try:
            with open(settings_path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"메모리 설정 저장 실패: {e}")
    
    def load_memory_settings(self):
        """메모리 관리 설정 로드"""
        settings_path = Path("save/memory_management.json")
        
        if not settings_path.exists():
            return
        
        try:
            with open(settings_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)
            
            # 설정 적용
            self.history_limit_enabled.setChecked(settings.get('history_limit_enabled', False))
            self.max_history_length.setValue(settings.get('max_history_length', 2000))
            
            action_id = settings.get('memory_action', 1)
            button = self.memory_action_group.button(action_id)
            if button:
                button.setChecked(True)
            
            # 컨트롤 상태 업데이트
            self.update_memory_controls_state(self.history_limit_enabled.isChecked())
            
        except Exception as e:
            print(f"메모리 설정 로드 실패: {e}")

    def check_and_apply_history_limit(self):
        """히스토리 큐 제한을 체크하고 필요시 동작을 수행합니다."""
        # 히스토리 제한이 비활성화되어 있으면 아무것도 하지 않음
        if not hasattr(self, 'history_limit_enabled') or not self.history_limit_enabled.isChecked():
            return
        
        # 현재 히스토리 개수가 제한을 초과하는지 확인
        current_count = len(self.image_history_window.history_widgets)
        max_limit = self.max_history_length.value()
        
        if current_count <= max_limit:
            return  # 제한 내에 있으면 아무것도 하지 않음
        
        # 제한을 초과했을 때의 동작 결정
        action_id = self.memory_action_group.checkedId()
        
        if action_id == 1:  # [1] 1장씩 자동저장+정리
            self.handle_auto_save_and_clear()
        elif action_id == 2:  # [2] 1장씩 저장없이 삭제
            self.handle_auto_delete_only()
        elif action_id == 3:  # [3] 자동생성 중단
            self.handle_stop_generation()
        
        # 상태 메시지 표시
        self.app_context.main_window.status_bar.showMessage(
            f"🧠 히스토리 제한 도달 ({current_count}/{max_limit}) - 동작 수행됨", 3000
        )

    def handle_auto_save_and_clear(self):
        """[1] 1장씩 자동저장+정리 동작"""
        # 가장 오래된 히스토리 아이템 (맨 앞)을 가져옴
        if not self.image_history_window.history_widgets:
            return

        oldest_widget = self.image_history_window.history_widgets[-1]
        oldest_item = oldest_widget.history_item

        # 해당 이미지를 저장 (중복 체크 추가)
        if oldest_item.raw_bytes:
            # 파일 경로가 있고, 실제 파일도 존재하면 저장 건너뛰기
            if oldest_item.filepath and os.path.exists(oldest_item.filepath):
                print(f"🧠 자동저장 건너뛰기: 이미 저장된 파일입니다 - {os.path.basename(oldest_item.filepath)}")
            else:
                is_webp = self.save_as_webp_checkbox.isChecked()

                # 🆕 분류 정보 생성
                classification_info = self._create_classification_info(oldest_item)

                # ✅ ImageCrudController를 통한 저장 (분류 정보 포함)
                success, filepath, error = self.image_crud.save_image(
                    image_bytes=oldest_item.raw_bytes,
                    as_webp=is_webp,
                    classification_info=classification_info
                )

                if success:
                    oldest_item.filepath = filepath  # 저장 성공 시 HistoryItem에 파일 경로 업데이트
                    print(f"🧠 자동저장 완료: {os.path.basename(filepath)}")
                else:
                    print(f"🧠 자동저장 실패: {error}")

        # 해당 아이템 삭제
        self.image_history_window.on_item_delete_requested(oldest_widget)

        # 가비지 콜렉션 수행
        import gc
        gc.collect()

    def handle_auto_delete_only(self):
        """[2] 1장씩 저장없이 삭제 동작"""
        # 가장 오래된 히스토리 아이템 삭제
        if not self.image_history_window.history_widgets:
            return
        
        oldest_widget = self.image_history_window.history_widgets[-1]
        self.image_history_window.on_item_delete_requested(oldest_widget)
        
        # 가비지 콜렉션 수행
        import gc
        gc.collect()
        print("🧠 자동삭제 완료: 가장 오래된 히스토리 아이템 제거됨")

    def handle_stop_generation(self):
        """[3] 자동생성 중단 동작"""
        # 생성 컨트롤러에 중단 신호 전송
        if hasattr(self.app_context, 'generation_controller'):
            generation_controller = self.app_context.generation_controller
            if hasattr(generation_controller, 'stop_generation'):
                generation_controller.stop_generation()
                print("🧠 자동생성 중단: 히스토리 제한 도달로 인한 중단")
        
        # 자동 생성 체크박스 비활성화
        if hasattr(self.app_context, 'main_window') and hasattr(self.app_context.main_window, 'generation_checkboxes'):
            auto_generate_checkbox = self.app_context.main_window.generation_checkboxes.get("자동 생성")
            if auto_generate_checkbox and auto_generate_checkbox.isChecked():
                auto_generate_checkbox.setChecked(False)
        
        # 메인 윈도우에 경고 메시지 표시
        if hasattr(self.app_context, 'main_window'):
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self.app_context.main_window, 
                "히스토리 제한 도달", 
                f"히스토리가 최대 길이({self.max_history_length.value()})에 도달하여 자동생성을 중단합니다.\n\n"
                "히스토리를 정리하거나 제한 설정을 조정해주세요."
            )

    def update_advanced_menu_state(self):
        """[신규] 고급 메뉴가 표시되기 직전에 호출되어 메뉴 항목의 활성화 상태를 결정합니다."""
        is_history_not_empty = bool(self.image_history_window.history_widgets)
        
        # 메뉴에 포함된 액션들의 활성화 상태를 설정
        # 히스토리 관련 액션들만 히스토리 상태에 따라 활성화/비활성화
        for action in self.advanced_menu.actions():
            if isinstance(action, QWidgetAction):
                # 메모리 관리 섹션(QWidgetAction)은 항상 활성화
                action.setEnabled(True)
            elif action.isSeparator():
                # 구분선은 건드리지 않음
                continue
            else:
                # 일반 액션들(다운로드, 정리 등)은 히스토리 상태에 따라 활성화
                action.setEnabled(is_history_not_empty)

    def _open_file_in_explorer(self, filepath: str):
        """지정된 파일 경로를 각 운영체제에 맞는 파일 탐색기에서 엽니다."""
        import subprocess
        import platform

        if not filepath or not os.path.exists(filepath):
            # 파일 경로가 유효하지 않으면 상태바에 메시지를 표시합니다.
            if hasattr(self.app_context, 'main_window'):
                self.app_context.main_window.status_bar.showMessage("⚠️ 파일 경로를 찾을 수 없습니다.", 3000)
            return

        system = platform.system()
        if system == "Windows":
            # Windows: explorer를 사용하여 파일을 선택한 상태로 폴더를 엽니다.
            subprocess.run(['explorer', '/select,', os.path.normpath(filepath)])
        elif system == "Darwin":  # macOS
            # macOS: open -R 옵션으로 파일을 선택한 상태로 Finder를 엽니다.
            subprocess.run(['open', '-R', filepath])
        else:  # Linux
            # Linux: xdg-open으로 파일이 포함된 디렉터리를 엽니다.
            subprocess.run(['xdg-open', os.path.dirname(filepath)])
