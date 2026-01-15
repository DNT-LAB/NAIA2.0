"""
Thumbnail Grid Widget

2x5 썸네일 그리드 위젯 (비동기 이미지 로딩)
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame,
    QLabel, QPushButton, QScrollArea, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject, QSize
from PyQt6.QtGui import QPixmap, QPainter, QColor, QImage, QMouseEvent
from pathlib import Path
from typing import List, Dict, Optional
from PIL import Image
import io

from ui.theme import DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size


class ThumbnailLoaderWorker(QObject):
    """썸네일 로딩 워커 (백그라운드 스레드)"""

    # 시그널
    thumbnail_loaded = pyqtSignal(int, object)  # parent_id, QPixmap
    batch_finished = pyqtSignal()

    def __init__(self, image_paths: List[tuple], thumbnail_size: int = 140):
        """
        Args:
            image_paths: [(parent_id, file_path), ...]
            thumbnail_size: 썸네일 크기 (정사각형)
        """
        super().__init__()
        self.image_paths = image_paths
        self.thumbnail_size = thumbnail_size
        self._cancelled = False

    def cancel(self):
        """로딩 취소"""
        self._cancelled = True

    def run(self):
        """썸네일 로딩 실행"""
        for parent_id, file_path in self.image_paths:
            if self._cancelled:
                break

            try:
                # PIL로 이미지 로드
                img = Image.open(file_path)
                img.load()

                # 썸네일 크기로 리사이즈 (정사각형 크롭)
                # 원본 비율 유지하면서 중앙 크롭
                w, h = img.size
                min_dim = min(w, h)

                # 중앙 크롭
                left = (w - min_dim) // 2
                top = (h - min_dim) // 2
                right = left + min_dim
                bottom = top + min_dim

                img = img.crop((left, top, right, bottom))
                img = img.resize((self.thumbnail_size, self.thumbnail_size), Image.Resampling.LANCZOS)

                # RGBA 변환
                if img.mode != 'RGBA':
                    img = img.convert('RGBA')

                # PNG 버퍼로 변환
                png_buffer = io.BytesIO()
                img.save(png_buffer, format='PNG')
                png_buffer.seek(0)

                # QPixmap으로 변환
                qimage = QImage()
                qimage.loadFromData(png_buffer.getvalue())
                pixmap = QPixmap.fromImage(qimage)

                png_buffer.close()

                # 시그널 발생
                self.thumbnail_loaded.emit(parent_id, pixmap)

            except Exception as e:
                print(f"[ThumbnailLoader] Failed to load {parent_id}: {e}")
                # 에러 시 None 전달
                self.thumbnail_loaded.emit(parent_id, None)

        self.batch_finished.emit()


class ThumbnailItem(QFrame):
    """썸네일 아이템 위젯 (이미지 + 하단 ID 라벨)"""

    clicked = pyqtSignal(int)  # parent_id

    def __init__(self, parent_id: int, size: int = 140, parent=None):
        """
        Args:
            parent_id: 이벤트 ID
            size: 썸네일 크기
        """
        super().__init__(parent)
        self.parent_id = parent_id
        self.size = size
        self._pixmap: Optional[QPixmap] = None
        self._selected = False

        # 전체 높이: 이미지 + ID 라벨
        self.id_label_height = get_scaled_size(18)
        self.setFixedSize(size, size + self.id_label_height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_style()

    def _update_style(self):
        """스타일 업데이트"""
        if self._selected:
            border_color = DARK_COLORS['accent_blue']
            border_width = 3
        else:
            border_color = DARK_COLORS['border']
            border_width = 1

        self.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: {border_width}px solid {border_color};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)

    def set_pixmap(self, pixmap: QPixmap):
        """썸네일 이미지 설정"""
        self._pixmap = pixmap
        self.update()

    def set_selected(self, selected: bool):
        """선택 상태 설정"""
        self._selected = selected
        self._update_style()

    def paintEvent(self, event):
        """페인트 이벤트"""
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # 이미지 영역 (ID 라벨 높이 제외)
        image_rect = self.rect().adjusted(0, 0, 0, -self.id_label_height)

        if self._pixmap and not self._pixmap.isNull():
            # 이미지 그리기 (패딩 적용)
            padding = 4
            target_rect = image_rect.adjusted(padding, padding, -padding, -padding)

            scaled_pixmap = self._pixmap.scaled(
                target_rect.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

            x = target_rect.x() + (target_rect.width() - scaled_pixmap.width()) // 2
            y = target_rect.y() + (target_rect.height() - scaled_pixmap.height()) // 2

            painter.drawPixmap(x, y, scaled_pixmap)
        else:
            # 로딩 중 표시
            painter.setPen(QColor(DARK_COLORS['text_secondary']))
            font = painter.font()
            font.setPointSize(get_scaled_font_size(15))
            painter.setFont(font)
            painter.drawText(image_rect, Qt.AlignmentFlag.AlignCenter, "...")

        # ID 표시 (이미지 아래 별도 영역)
        id_rect = self.rect().adjusted(2, self.size, -2, 0)
        painter.setPen(QColor(DARK_COLORS['text_secondary']))
        font = painter.font()
        font.setPointSize(get_scaled_font_size(10))  # 2px 감소
        painter.setFont(font)

        id_text = str(self.parent_id)
        if len(id_text) > 8:
            id_text = id_text[:4] + ".." + id_text[-2:]

        painter.drawText(
            id_rect,
            Qt.AlignmentFlag.AlignCenter,
            id_text
        )

        painter.end()

    def mousePressEvent(self, event: QMouseEvent):
        """마우스 클릭"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.parent_id)
        super().mousePressEvent(event)

        # 부모 다이얼로그로 포커스 이동 (키보드 네비게이션 활성화)
        parent = self.parent()
        while parent is not None:
            if parent.inherits("QDialog"):
                parent.setFocus()
                break
            parent = parent.parent()


class ThumbnailGrid(QWidget):
    """2x5 썸네일 그리드 위젯"""

    # 시그널
    item_clicked = pyqtSignal(int)  # parent_id
    page_changed = pyqtSignal(int, int)  # current_page, total_pages

    # 상수
    ROWS = 5
    COLS = 2
    ITEMS_PER_PAGE = ROWS * COLS  # 10

    def __init__(self, events_dir: Path, parent=None):
        """
        Args:
            events_dir: 이벤트 이미지 폴더 경로
        """
        super().__init__(parent)
        self.events_dir = Path(events_dir)

        # 상태
        self.events: List[Dict] = []  # 표시할 이벤트 리스트
        self.current_page = 0
        self.selected_id: Optional[int] = None

        # 썸네일 아이템
        self.thumbnail_items: List[ThumbnailItem] = []
        self.thumbnail_cache: Dict[int, QPixmap] = {}  # 캐시

        # 로더 스레드
        self._loader_thread: Optional[QThread] = None
        self._loader_worker: Optional[ThumbnailLoaderWorker] = None

        self._init_ui()

    def _init_ui(self):
        """UI 초기화"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 썸네일 그리드 영역
        grid_frame = QFrame()
        grid_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_primary']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)

        grid_layout = QGridLayout(grid_frame)
        grid_layout.setContentsMargins(4, 4, 4, 4)
        grid_layout.setSpacing(4)

        # 썸네일 아이템 생성
        thumbnail_size = get_scaled_size(140)
        for row in range(self.ROWS):
            for col in range(self.COLS):
                item = ThumbnailItem(0, thumbnail_size)
                item.clicked.connect(self._on_item_clicked)
                item.hide()  # 초기에는 숨김
                grid_layout.addWidget(item, row, col)
                self.thumbnail_items.append(item)

        layout.addWidget(grid_frame, stretch=1)

        # 페이지네이션
        pagination_layout = QHBoxLayout()
        pagination_layout.setSpacing(4)

        self.prev_btn = QPushButton("◀ 이전")
        self.prev_btn.setStyleSheet(self._get_pagination_btn_style())
        self.prev_btn.clicked.connect(self._on_prev_clicked)
        self.prev_btn.setEnabled(False)
        pagination_layout.addWidget(self.prev_btn)

        self.page_label = QLabel("0/0")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(15)}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        pagination_layout.addWidget(self.page_label, stretch=1)

        self.next_btn = QPushButton("다음 ▶")
        self.next_btn.setStyleSheet(self._get_pagination_btn_style())
        self.next_btn.clicked.connect(self._on_next_clicked)
        self.next_btn.setEnabled(False)
        pagination_layout.addWidget(self.next_btn)

        layout.addLayout(pagination_layout)

    def _get_pagination_btn_style(self) -> str:
        """페이지네이션 버튼 스타일"""
        return f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(8)}px {get_scaled_size(14)}px;
                font-size: {get_scaled_font_size(15)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QPushButton:disabled {{
                color: {DARK_COLORS['text_secondary']};
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """

    def set_events(self, events: List[Dict], reset_page: bool = True):
        """이벤트 목록 설정

        Args:
            events: 이벤트 정보 리스트 [{id, general, ratings, pages, created_at}, ...]
            reset_page: 페이지 초기화 여부
        """
        self.events = events

        if reset_page:
            self.current_page = 0

        self._update_grid()

    def _update_grid(self):
        """그리드 업데이트"""
        # 페이지네이션 계산
        total_items = len(self.events)
        total_pages = max(1, (total_items + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE)

        # 페이지 범위 체크
        if self.current_page >= total_pages:
            self.current_page = max(0, total_pages - 1)

        # 현재 페이지 아이템
        start_idx = self.current_page * self.ITEMS_PER_PAGE
        end_idx = start_idx + self.ITEMS_PER_PAGE
        page_events = self.events[start_idx:end_idx]

        # 썸네일 아이템 업데이트
        image_paths_to_load = []

        for i, item in enumerate(self.thumbnail_items):
            if i < len(page_events):
                event = page_events[i]
                parent_id = event['id']

                item.parent_id = parent_id
                item.set_selected(parent_id == self.selected_id)
                item.show()

                # 캐시 확인
                if parent_id in self.thumbnail_cache:
                    item.set_pixmap(self.thumbnail_cache[parent_id])
                else:
                    item.set_pixmap(None)  # 로딩 중 표시
                    file_path = self.events_dir / str(parent_id)
                    if file_path.exists():
                        image_paths_to_load.append((parent_id, str(file_path)))
            else:
                item.hide()

        # 페이지 라벨 업데이트
        current_display = self.current_page + 1 if total_items > 0 else 0
        self.page_label.setText(f"{current_display}/{total_pages}")

        # 버튼 상태 업데이트
        self.prev_btn.setEnabled(self.current_page > 0)
        self.next_btn.setEnabled(self.current_page < total_pages - 1)

        # 페이지 변경 시그널
        self.page_changed.emit(self.current_page, total_pages)

        # 썸네일 로딩 시작
        if image_paths_to_load:
            self._start_loading(image_paths_to_load)

    def _start_loading(self, image_paths: List[tuple]):
        """썸네일 로딩 시작"""
        # 기존 로더 정리
        self._stop_loading()

        # 새 로더 생성
        self._loader_thread = QThread()
        self._loader_worker = ThumbnailLoaderWorker(
            image_paths,
            thumbnail_size=get_scaled_size(140)
        )
        self._loader_worker.moveToThread(self._loader_thread)

        # 시그널 연결
        self._loader_worker.thumbnail_loaded.connect(self._on_thumbnail_loaded)
        self._loader_worker.batch_finished.connect(self._on_loading_finished)
        self._loader_thread.started.connect(self._loader_worker.run)
        self._loader_thread.finished.connect(self._loader_worker.deleteLater)
        self._loader_thread.finished.connect(self._loader_thread.deleteLater)

        # 시작
        self._loader_thread.start()

    def _stop_loading(self):
        """로딩 중지"""
        if self._loader_worker:
            self._loader_worker.cancel()
        if self._loader_thread and self._loader_thread.isRunning():
            self._loader_thread.quit()
            self._loader_thread.wait(1000)
        self._loader_thread = None
        self._loader_worker = None

    def _on_thumbnail_loaded(self, parent_id: int, pixmap: Optional[QPixmap]):
        """썸네일 로드 완료"""
        if pixmap is None:
            return

        # 캐시에 저장
        self.thumbnail_cache[parent_id] = pixmap

        # 캐시 크기 제한 (최대 50개)
        if len(self.thumbnail_cache) > 50:
            oldest_key = next(iter(self.thumbnail_cache))
            del self.thumbnail_cache[oldest_key]

        # 해당 아이템 업데이트
        for item in self.thumbnail_items:
            if item.parent_id == parent_id and item.isVisible():
                item.set_pixmap(pixmap)
                break

    def _on_loading_finished(self):
        """로딩 완료"""
        pass

    def _on_item_clicked(self, parent_id: int):
        """아이템 클릭"""
        # 선택 상태 업데이트
        old_selected = self.selected_id
        self.selected_id = parent_id

        # 이전 선택 해제
        if old_selected is not None:
            for item in self.thumbnail_items:
                if item.parent_id == old_selected:
                    item.set_selected(False)
                    break

        # 새 선택
        for item in self.thumbnail_items:
            if item.parent_id == parent_id:
                item.set_selected(True)
                break

        # 시그널 발생
        self.item_clicked.emit(parent_id)

    def _on_prev_clicked(self):
        """이전 페이지"""
        if self.current_page > 0:
            self.current_page -= 1
            self._update_grid()

    def _on_next_clicked(self):
        """다음 페이지"""
        total_pages = (len(self.events) + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self._update_grid()

    def go_to_page(self, page: int):
        """특정 페이지로 이동

        Args:
            page: 페이지 번호 (0-indexed)
        """
        total_pages = max(1, (len(self.events) + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE)
        if 0 <= page < total_pages:
            self.current_page = page
            self._update_grid()

    def select_item(self, parent_id: int):
        """특정 아이템 선택

        Args:
            parent_id: 선택할 이벤트 ID
        """
        self.selected_id = parent_id

        # 해당 ID가 있는 페이지로 이동
        for i, event in enumerate(self.events):
            if event['id'] == parent_id:
                target_page = i // self.ITEMS_PER_PAGE
                if target_page != self.current_page:
                    self.current_page = target_page
                self._update_grid()
                return

    def clear_selection(self):
        """선택 해제"""
        old_selected = self.selected_id
        self.selected_id = None

        if old_selected is not None:
            for item in self.thumbnail_items:
                if item.parent_id == old_selected:
                    item.set_selected(False)
                    break

    def cleanup(self):
        """리소스 정리"""
        self._stop_loading()
        self.thumbnail_cache.clear()
