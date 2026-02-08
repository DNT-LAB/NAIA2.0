"""
Event Preview Panel

선택한 이벤트의 미리보기 및 정보 표시 패널
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QPushButton, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QPainter, QColor, QMouseEvent
from pathlib import Path
from typing import Optional, Dict
from PIL import Image
import io

from ui.theme import DARK_STYLES, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size


class LargeImageViewer(QWidget):
    """큰 이미지 뷰어 (세로로 긴 비율)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: Optional[QPixmap] = None
        self._placeholder_text = "이벤트를 선택하세요"

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(get_scaled_size(300))

    def set_pixmap(self, pixmap: QPixmap):
        """QPixmap 설정"""
        if pixmap and not pixmap.isNull():
            self._pixmap = pixmap
        else:
            self._pixmap = None
        self.update()

    def set_image(self, image):
        """PIL Image 또는 QPixmap 설정"""
        if image is None:
            self._pixmap = None
        elif isinstance(image, QPixmap):
            self._pixmap = image
        elif isinstance(image, Image.Image):
            try:
                if hasattr(image, 'load'):
                    image.load()

                png_buffer = io.BytesIO()
                image.save(png_buffer, format='PNG')
                png_buffer.seek(0)

                from PyQt6.QtGui import QImage
                qimage = QImage()
                qimage.loadFromData(png_buffer.getvalue())
                self._pixmap = QPixmap.fromImage(qimage)
                png_buffer.close()
            except Exception as e:
                print(f"[LargeImageViewer] Image conversion error: {e}")
                self._pixmap = None
        else:
            self._pixmap = None

        self.update()

    def clear(self):
        """이미지 클리어"""
        self._pixmap = None
        self.update()

    def set_placeholder_text(self, text: str):
        """플레이스홀더 텍스트 설정"""
        self._placeholder_text = text
        self.update()

    def paintEvent(self, event):
        """페인트 이벤트"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # 배경
        bg_color = QColor(DARK_COLORS['bg_primary'])
        painter.fillRect(self.rect(), bg_color)

        # 테두리
        border_color = QColor(DARK_COLORS['border'])
        painter.setPen(border_color)
        painter.drawRoundedRect(
            self.rect().adjusted(1, 1, -1, -1),
            get_scaled_size(8),
            get_scaled_size(8)
        )

        if not self._pixmap or self._pixmap.isNull():
            # 플레이스홀더
            painter.setPen(QColor(DARK_COLORS['text_secondary']))
            font = painter.font()
            font.setPointSize(get_scaled_font_size(18))
            painter.setFont(font)
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                self._placeholder_text
            )
        else:
            # 이미지 그리기
            widget_rect = self.rect().adjusted(
                get_scaled_size(8),
                get_scaled_size(8),
                -get_scaled_size(8),
                -get_scaled_size(8)
            )

            scaled_pixmap = self._pixmap.scaled(
                widget_rect.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

            x = widget_rect.x() + (widget_rect.width() - scaled_pixmap.width()) // 2
            y = widget_rect.y() + (widget_rect.height() - scaled_pixmap.height()) // 2

            painter.drawPixmap(x, y, scaled_pixmap)

        painter.end()

    def mousePressEvent(self, event: QMouseEvent):
        """마우스 클릭 시 부모 다이얼로그로 포커스 이동"""
        super().mousePressEvent(event)
        # 부모 다이얼로그로 포커스 이동 (키보드 네비게이션 활성화)
        parent = self.parent()
        while parent is not None:
            if parent.inherits("QDialog"):
                parent.setFocus()
                break
            parent = parent.parent()


class EventPreviewPanel(QFrame):
    """이벤트 미리보기 패널"""

    # 시그널
    select_sequence_requested = pyqtSignal(int)  # parent_id
    quick_generate_requested = pyqtSignal(int)  # parent_id

    def __init__(self, events_dir: Path, parent=None):
        """
        Args:
            events_dir: 이벤트 이미지 폴더 경로
        """
        super().__init__(parent)
        self.events_dir = Path(events_dir)
        self.current_event: Optional[Dict] = None
        self.current_parent_id: Optional[int] = None

        self._init_ui()

    def _init_ui(self):
        """UI 초기화"""
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 이미지 뷰어 (상단, 확장)
        self.image_viewer = LargeImageViewer(self)
        layout.addWidget(self.image_viewer, stretch=1)

        # 이벤트 정보 카드
        info_card = QFrame()
        info_card.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)

        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(8, 6, 8, 6)
        info_layout.setSpacing(4)

        # ID 및 Pages 행
        id_row = QHBoxLayout()

        self.id_label = QLabel("ID: -")
        self.id_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(17)}px;
            font-weight: bold;
            color: {DARK_COLORS['text_primary']};
        """)
        id_row.addWidget(self.id_label)

        id_row.addStretch()

        self.pages_label = QLabel("Pages: -")
        self.pages_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(16)}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        id_row.addWidget(self.pages_label)

        info_layout.addLayout(id_row)

        # Rating 행
        self.rating_label = QLabel("Rating: -")
        self.rating_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(16)}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        info_layout.addWidget(self.rating_label)

        # Tags 행
        self.tags_label = QLabel("Tags: -")
        self.tags_label.setWordWrap(True)
        self.tags_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(15)}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        self.tags_label.setMaximumHeight(get_scaled_size(80))
        info_layout.addWidget(self.tags_label)

        layout.addWidget(info_card)

        # 액션 버튼
        button_layout = QHBoxLayout()
        button_layout.setSpacing(6)

        self.select_btn = QPushButton("▶ 시퀀스 선택")
        self.select_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.select_btn.clicked.connect(self._on_select_clicked)
        self.select_btn.setEnabled(False)
        button_layout.addWidget(self.select_btn)

        self.quick_btn = QPushButton("⏭ 바로 생성")
        self.quick_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.quick_btn.clicked.connect(self._on_quick_clicked)
        self.quick_btn.setEnabled(False)
        button_layout.addWidget(self.quick_btn)

        layout.addLayout(button_layout)

    def set_event(self, event: Dict):
        """이벤트 설정

        Args:
            event: 이벤트 정보 {id, general, ratings, pages, created_at}
        """
        self.current_event = event
        self.current_parent_id = event.get('id')

        # 정보 업데이트
        self.id_label.setText(f"ID: {event.get('id', '-')}")
        self.pages_label.setText(f"Pages: {event.get('pages', '-')}")

        # Rating 표시 (색상 적용)
        ratings = event.get('ratings', [])
        if ratings:
            ratings_text = "-".join(ratings)
            # 가장 심한 rating 기준으로 색상 결정
            rating_priority = {'e': 3, 'q': 2, 's': 1, 'g': 0}
            max_rating = max(ratings, key=lambda r: rating_priority.get(r, -1))

            if max_rating == 'e':
                color = '#ff6b6b'
            elif max_rating == 'q':
                color = '#ffa94d'
            elif max_rating == 's':
                color = '#69db7c'
            else:
                color = '#74c0fc'

            self.rating_label.setText(f"Rating: {ratings_text}")
            self.rating_label.setStyleSheet(f"""
                font-size: {get_scaled_font_size(16)}px;
                color: {color};
            """)
        else:
            self.rating_label.setText("Rating: -")
            self.rating_label.setStyleSheet(f"""
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_secondary']};
            """)

        # Tags 표시 (축약)
        general = event.get('general', '')
        if len(general) > 100:
            general = general[:100] + "..."
        self.tags_label.setText(f"Tags: {general if general else '-'}")

        # 이미지 로드
        self._load_image(self.current_parent_id)

        # 버튼 활성화
        self.select_btn.setEnabled(True)
        self.quick_btn.setEnabled(True)

    def clear(self):
        """클리어"""
        self.current_event = None
        self.current_parent_id = None

        self.id_label.setText("ID: -")
        self.pages_label.setText("Pages: -")
        self.rating_label.setText("Rating: -")
        self.rating_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(16)}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        self.tags_label.setText("Tags: -")

        self.image_viewer.clear()
        self.image_viewer.set_placeholder_text("이벤트를 선택하세요")

        self.select_btn.setEnabled(False)
        self.quick_btn.setEnabled(False)

    def _load_image(self, parent_id: int):
        """이미지 로드"""
        if parent_id is None:
            self.image_viewer.clear()
            return

        file_path = self.events_dir / str(parent_id)
        if file_path.exists():
            try:
                img = Image.open(str(file_path))
                img.load()
                self.image_viewer.set_image(img)
            except Exception as e:
                print(f"[EventPreviewPanel] Failed to load image: {e}")
                self.image_viewer.clear()
                self.image_viewer.set_placeholder_text("이미지 로드 실패")
        else:
            self.image_viewer.clear()
            self.image_viewer.set_placeholder_text("이미지 파일 없음")

    def _on_select_clicked(self):
        """시퀀스 선택 버튼 클릭"""
        if self.current_parent_id is not None:
            self.select_sequence_requested.emit(self.current_parent_id)

    def _on_quick_clicked(self):
        """바로 생성 버튼 클릭"""
        if self.current_parent_id is not None:
            self.quick_generate_requested.emit(self.current_parent_id)

    def mousePressEvent(self, event: QMouseEvent):
        """마우스 클릭 시 부모 다이얼로그로 포커스 이동"""
        super().mousePressEvent(event)
        # 부모 다이얼로그로 포커스 이동 (키보드 네비게이션 활성화)
        parent = self.parent()
        while parent is not None:
            if parent.inherits("QDialog"):
                parent.setFocus()
                break
            parent = parent.parent()
