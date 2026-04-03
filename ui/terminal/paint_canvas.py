"""768x768 프리핸드 드로잉 캔버스 — 둥근 브러시 + Undo/Redo + Auto-save."""
import os
import math
from PyQt6.QtCore import Qt, QPointF, pyqtSignal
from PyQt6.QtGui import QPixmap, QPainter, QColor, QBrush, QPen
from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem

CANVAS_SIZE = 768
MAX_UNDO = 50
CLI_DIR = os.path.join(os.path.dirname(__file__), ".cli")
SAVE_FILENAME = "stickman_canvas.png"


class StickmanCanvas(QGraphicsView):
    """768x768 흰 배경 둥근 브러시 드로잉 캔버스."""

    stroke_completed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(0, 0, CANVAS_SIZE, CANVAS_SIZE, self)
        self.setScene(self._scene)

        # 흰 배경 픽스맵
        self._pixmap = QPixmap(CANVAS_SIZE, CANVAS_SIZE)
        self._pixmap.fill(Qt.GlobalColor.white)
        self._pixmap_item = QGraphicsPixmapItem(self._pixmap)
        self._scene.addItem(self._pixmap_item)

        # 브러시 설정
        self._brush_color = QColor(Qt.GlobalColor.black)
        self._brush_radius = 4
        self._drawing = False
        self._last_point = QPointF()

        # Undo / Redo
        self._undo_stack: list[QPixmap] = []
        self._redo_stack: list[QPixmap] = []

        # 뷰 설정
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setStyleSheet("border: none; background: #1a1a1a;")

        # 기존 이미지 복원 또는 초기 저장
        self._load_or_init()

    # ── 브러시 설정 ──

    def set_brush_color(self, color: QColor):
        self._brush_color = color

    def set_brush_radius(self, radius: int):
        self._brush_radius = max(1, radius)

    # ── 둥근 브러시 스탬프 ──

    def _stamp_circle(self, painter: QPainter, center: QPointF):
        """하나의 둥근 브러시 스탬프 찍기."""
        painter.drawEllipse(center, self._brush_radius, self._brush_radius)

    def _interpolate_and_stamp(self, painter: QPainter, p1: QPointF, p2: QPointF):
        """두 점 사이를 보간하며 브러시 스탬프를 연속 찍기."""
        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()
        dist = math.hypot(dx, dy)
        step = max(1.0, self._brush_radius * 0.3)
        if dist < step:
            self._stamp_circle(painter, p2)
            return
        steps = int(dist / step)
        for i in range(steps + 1):
            t = i / max(steps, 1)
            x = p1.x() + dx * t
            y = p1.y() + dy * t
            self._stamp_circle(painter, QPointF(x, y))

    # ── 마우스 이벤트 ──

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._push_undo()
            self._drawing = True
            pos = self.mapToScene(event.pos())
            self._last_point = pos
            painter = QPainter(self._pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(self._brush_color))
            self._stamp_circle(painter, pos)
            painter.end()
            self._pixmap_item.setPixmap(self._pixmap)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drawing:
            current = self.mapToScene(event.pos())
            painter = QPainter(self._pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(self._brush_color))
            self._interpolate_and_stamp(painter, self._last_point, current)
            painter.end()
            self._pixmap_item.setPixmap(self._pixmap)
            self._last_point = current
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drawing:
            self._drawing = False
            self._auto_save()
            self.stroke_completed.emit()
        super().mouseReleaseEvent(event)

    # ── Undo / Redo ──

    def undo(self):
        if not self._undo_stack:
            return
        self._redo_stack.append(self._pixmap.copy())
        self._pixmap = self._undo_stack.pop()
        self._pixmap_item.setPixmap(self._pixmap)
        self._auto_save()

    def redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(self._pixmap.copy())
        self._pixmap = self._redo_stack.pop()
        self._pixmap_item.setPixmap(self._pixmap)
        self._auto_save()

    def clear_canvas(self):
        self._push_undo()
        self._pixmap.fill(Qt.GlobalColor.white)
        self._pixmap_item.setPixmap(self._pixmap)
        self._auto_save()

    def _push_undo(self):
        self._undo_stack.append(self._pixmap.copy())
        if len(self._undo_stack) > MAX_UNDO:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    # ── Auto-save / Load ──

    def _load_or_init(self):
        """이전 저장 이미지가 있으면 복원, 없으면 흰 배경으로 초기화."""
        path = os.path.join(CLI_DIR, SAVE_FILENAME)
        if os.path.isfile(path):
            loaded = QPixmap(path)
            if not loaded.isNull() and loaded.size().width() == CANVAS_SIZE:
                self._pixmap = loaded
                self._pixmap_item.setPixmap(self._pixmap)
                return
        self._auto_save()

    def _auto_save(self):
        os.makedirs(CLI_DIR, exist_ok=True)
        self._pixmap.save(os.path.join(CLI_DIR, SAVE_FILENAME), "PNG")

    def get_image_path(self) -> str:
        return os.path.join(CLI_DIR, SAVE_FILENAME)

    # ── 뷰포트 맞춤 ──

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
