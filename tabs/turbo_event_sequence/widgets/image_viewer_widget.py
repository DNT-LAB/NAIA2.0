"""
Image Viewer Widget

생성된 이미지 표시 위젯
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPainter, QColor, QPixmap

from ui.theme import DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

from PIL import Image
from PIL.ImageQt import ImageQt
import io


class ImageViewerWidget(QWidget):
    """이미지 뷰어 위젯"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self._placeholder_text = "생성된 이미지가 여기에 표시됩니다"

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(get_scaled_size(300))

    def setPixmap(self, pixmap: QPixmap):
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
                # 🔥 이미지 데이터 완전 로드 확보 (lazy loading 방지)
                if hasattr(image, 'load'):
                    image.load()

                # PIL Image를 PNG 버퍼로 저장 후 다시 열기 (WEBP 등 비표준 형식 문제 해결)
                png_buffer = io.BytesIO()
                image.save(png_buffer, format='PNG')
                png_buffer.seek(0)
                clean_image = Image.open(png_buffer)
                clean_image.load()  # 이미지 데이터 완전히 로드

                if clean_image.mode != 'RGBA':
                    clean_image = clean_image.convert('RGBA')

                qimage = ImageQt(clean_image)
                self._pixmap = QPixmap.fromImage(qimage)
                png_buffer.close()
            except Exception as e:
                print(f"[ImageViewer] 이미지 변환 오류: {e}")
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
        """페인트 이벤트 - 이미지 또는 플레이스홀더 그리기"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # 배경 채우기
        bg_color = QColor(DARK_COLORS['bg_primary'])
        painter.fillRect(self.rect(), bg_color)

        # 테두리 그리기
        border_color = QColor(DARK_COLORS['border'])
        painter.setPen(border_color)
        painter.drawRoundedRect(
            self.rect().adjusted(1, 1, -1, -1),
            get_scaled_size(8),
            get_scaled_size(8)
        )

        if not self._pixmap or self._pixmap.isNull():
            # 플레이스홀더 텍스트 그리기
            painter.setPen(QColor(DARK_COLORS['text_secondary']))
            font = painter.font()
            font.setPointSize(get_scaled_font_size(14) + 3)
            painter.setFont(font)
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                self._placeholder_text
            )
        else:
            # 이미지 그리기 (비율 유지, 중앙 정렬)
            widget_rect = self.rect().adjusted(
                get_scaled_size(10),
                get_scaled_size(10),
                -get_scaled_size(10),
                -get_scaled_size(10)
            )

            # 가용 공간에 맞게 스케일링
            scaled_pixmap = self._pixmap.scaled(
                widget_rect.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

            # 중앙 위치 계산
            x = widget_rect.x() + (widget_rect.width() - scaled_pixmap.width()) // 2
            y = widget_rect.y() + (widget_rect.height() - scaled_pixmap.height()) // 2

            painter.drawPixmap(x, y, scaled_pixmap)

        painter.end()

    def get_pixmap(self) -> QPixmap:
        """현재 픽스맵 반환"""
        return self._pixmap

    def has_image(self) -> bool:
        """이미지가 있는지 확인"""
        return self._pixmap is not None and not self._pixmap.isNull()
