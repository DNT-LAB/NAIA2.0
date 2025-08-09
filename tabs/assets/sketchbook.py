
from __future__ import annotations
"""
Sketchbook Module - Multi-layer image editing system
Final patched version (PyQt6-safe, fit-to-width, fixed mask)
- Canvas-root child clipping (no drawItems override)
- Rotation-proof resize (outward/inward via vector projection)
- Handle positions locked to visual corners
- Resolution switching via centerOn() only
- Fit canvas to view WIDTH automatically (no infinite panning)
- Foreground mask drawn in VIEWPORT coordinates (no stray bars)
- PyQt6 enums fixed (QPainter.RenderHint.*)
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict
from uuid import uuid4
import os
import tempfile

# PyQt6
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal, QEvent, QThread
from PyQt6.QtGui import (
    QPainterPath, QPen, QColor, QTransform, QPixmap, QVector2D, QPainter, QBrush, QImage
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QGraphicsView, QGraphicsScene,
    QGraphicsItem, QGraphicsRectItem, QGraphicsPixmapItem,
    QGraphicsEllipseItem, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QFileDialog, QMessageBox, QComboBox,
    QListWidget, QListWidgetItem, QAbstractItemView, QCheckBox, QSplitter,
    QSlider, QTextEdit, QDialog, QProgressDialog
)
from PIL import Image, ImageDraw, ImageFilter
import numpy as np
import io
import base64

# Optional theme/scaling helpers (fallbacks provided if not present)
try:
    from ui.theme import get_dynamic_styles  # type: ignore
except Exception:
    def get_dynamic_styles():
        return {
            'primary_button': '',
            'secondary_button': '',
            'compact_combobox': '',
            'list_widget': '',
        }

try:
    from ui.scaling_manager import get_scaled_font_size, get_scaled_size  # type: ignore
except Exception:
    def get_scaled_font_size(px: int) -> int:
        return px
    def get_scaled_size(px: int) -> int:
        return px


# ---------------------------
# Data model
# ---------------------------

@dataclass
class LayerData:
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    image_path: str = ""
    position: Tuple[float, float] = (0.0, 0.0)
    scale: float = 1.0
    rotation: float = 0.0
    z_order: int = 0
    visible: bool = True
    opacity: float = 1.0
    # caches (optional)
    pixmap: Optional[QPixmap] = field(default=None, repr=False)
    original_size: Tuple[int, int] = (0, 0)


# ---------------------------
# Graphics items
# ---------------------------

class CanvasRootItem(QGraphicsRectItem):
    """Logical canvas container that clips its children to its rect."""
    def __init__(self, rect: QRectF):
        super().__init__(rect)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape, True)
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))


class ImageLayerItem(QGraphicsPixmapItem):
    def __init__(self, layer_data: LayerData):
        super().__init__()
        self.layer_data = layer_data
        # Load pixmap (lazy cache)
        pm = layer_data.pixmap or QPixmap(layer_data.image_path)
        self.setPixmap(pm)
        if layer_data.pixmap is None:
            self.layer_data.pixmap = pm
            self.layer_data.original_size = (pm.width(), pm.height())

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        )
        # Initial state
        self.setPos(QPointF(*layer_data.position))
        self.setOpacity(layer_data.opacity)
        self.setZValue(layer_data.z_order)
        self.setVisible(layer_data.visible)

        self._handles: list[ResizeHandle] = []
        self.update_transform()

    # --- transforms / state ---
    def update_transform(self):
        t = QTransform()
        br = self.boundingRect(); c = br.center()
        t.translate(c.x(), c.y())
        t.rotate(self.layer_data.rotation)
        t.scale(self.layer_data.scale, self.layer_data.scale)
        t.translate(-c.x(), -c.y())
        self.setTransform(t)
        self._update_handles()

    def set_scale_about_center(self, s: float):
        self.layer_data.scale = s
        self.update_transform()

    def set_scale_from_handle(self, new_scale: float, handle_pos: str):
        # Keep the opposite edge/corner anchored in scene space
        old_srect = self.sceneBoundingRect()

        def anchor_of(rect: QRectF, pos: str) -> QPointF:
            m = {
                'e':  QPointF(rect.left(), rect.center().y()),
                'w':  QPointF(rect.right(), rect.center().y()),
                'n':  QPointF(rect.center().x(), rect.bottom()),
                's':  QPointF(rect.center().x(), rect.top()),
                'ne': QPointF(rect.left(), rect.bottom()),
                'nw': QPointF(rect.right(), rect.bottom()),
                'se': QPointF(rect.left(), rect.top()),
                'sw': QPointF(rect.right(), rect.top()),
            }
            return m.get(pos, rect.center())

        anchor = anchor_of(old_srect, handle_pos)
        self.set_scale_about_center(new_scale)
        new_srect = self.sceneBoundingRect()
        new_anchor = anchor_of(new_srect, handle_pos)
        shift = anchor - new_anchor
        self.setPos(self.pos() + shift)
        self._update_handles()

    def set_selected(self, selected: bool):
        self.setSelected(selected)
        if selected:
            self._create_handles()
        else:
            self._remove_handles()

    # --- handles ---
    def _create_handles(self):
        self._remove_handles()
        for pos in ['nw','n','ne','e','se','s','sw','w']:
            h = ResizeHandle(pos, self)
            h.setParentItem(self)
            self._handles.append(h)
        self._update_handles()

    def _remove_handles(self):
        for h in self._handles:
            if h.scene():
                h.scene().removeItem(h)
        self._handles.clear()

    def _update_handles(self):
        if not self._handles:
            return
        srect = self.sceneBoundingRect()
        irect = self.mapFromScene(srect).boundingRect()
        pos_map: dict[str, QPointF] = {
            'nw': QPointF(irect.left(),  irect.top()),
            'n' : QPointF(irect.center().x(), irect.top()),
            'ne': QPointF(irect.right(), irect.top()),
            'e' : QPointF(irect.right(), irect.center().y()),
            'se': QPointF(irect.right(), irect.bottom()),
            's' : QPointF(irect.center().x(), irect.bottom()),
            'sw': QPointF(irect.left(),  irect.bottom()),
            'w' : QPointF(irect.left(),  irect.center().y()),
        }
        for h in self._handles:
            p = pos_map.get(h.position)
            if p is not None:
                h.setPos(p)

    # Relay selection to canvas when clicked on the item itself
    def mousePressEvent(self, event):
        self._move_start_pos = self.pos()  # Record start position for undo
        super().mousePressEvent(event)
        scene = self.scene()
        if scene is not None:
            views = scene.views()
            if views:
                view = views[0]
                if hasattr(view, 'select_layer'):
                    try:
                        view.select_layer(self.layer_data.id)
                    except Exception:
                        pass
    
    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        # Record move if position changed
        if hasattr(self, '_move_start_pos'):
            end_pos = self.pos()
            if self._move_start_pos != end_pos:
                # Update layer data
                self.layer_data.position = (end_pos.x(), end_pos.y())
                # Notify main widget to record undo
                scene = self.scene()
                if scene:
                    views = scene.views()
                    if views:
                        view = views[0]
                        if hasattr(view, 'parent') and hasattr(view.parent(), 'record_layer_move'):
                            old_pos = (self._move_start_pos.x(), self._move_start_pos.y())
                            new_pos = (end_pos.x(), end_pos.y())
                            view.parent().record_layer_move(self.layer_data.id, old_pos, new_pos)


class InpaintLayerItem(QGraphicsPixmapItem):
    """Special layer for inpainting with brush support"""
    def __init__(self, canvas_size: Tuple[int, int]):
        super().__init__()
        self.canvas_w, self.canvas_h = canvas_size
        self.layer_data = LayerData(
            id=str(uuid4()),
            name="Inpaint Layer",
            image_path="",
            position=(0.0, 0.0),
            scale=1.0,
            z_order=999  # Always on top
        )
        
        # Create transparent pixmap for drawing
        self.mask_pixmap = QPixmap(self.canvas_w, self.canvas_h)
        self.mask_pixmap.fill(Qt.GlobalColor.transparent)
        self.setPixmap(self.mask_pixmap)
        
        # Brush settings
        self.brush_size = 50
        self.brush_color = QColor(255, 0, 0, 128)  # Semi-transparent red
        self.eraser_mode = False
        self.last_paint_pos = None
        
        # Grid system for mask (8x8 blocks like inpaint_window.py)
        self.grid_width = self.canvas_w // 8
        self.grid_height = self.canvas_h // 8
        self.mask_grid = [[0 for _ in range(self.grid_height)] for _ in range(self.grid_width)]
        
        self.setZValue(999)  # Always on top
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton)
    
    def set_brush_size(self, size: int):
        self.brush_size = (size // 8) * 8  # Align to 8px grid
        if self.brush_size < 8:
            self.brush_size = 8
    
    def set_eraser_mode(self, enabled: bool):
        self.eraser_mode = enabled
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos()
            self.last_paint_pos = pos
            self.paint_at(pos)
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            # Right click = temporary eraser
            self.eraser_mode = True
            pos = event.pos()
            self.last_paint_pos = pos
            self.paint_at(pos)
            event.accept()
    
    def mouseMoveEvent(self, event):
        if event.buttons() & (Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton):
            pos = event.pos()
            if self.last_paint_pos:
                self.paint_line(self.last_paint_pos, pos)
            self.last_paint_pos = pos
            event.accept()
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.eraser_mode = False  # Reset eraser mode
        self.last_paint_pos = None
        event.accept()
    
    def paint_at(self, pos: QPointF):
        # Update grid
        grid_x = int(pos.x()) // 8
        grid_y = int(pos.y()) // 8
        radius = self.brush_size // 16  # Grid radius
        
        for gx in range(max(0, grid_x - radius), min(self.grid_width, grid_x + radius + 1)):
            for gy in range(max(0, grid_y - radius), min(self.grid_height, grid_y + radius + 1)):
                if self.eraser_mode:
                    self.mask_grid[gx][gy] = 0
                else:
                    self.mask_grid[gx][gy] = 1
        
        self.update_display()
    
    def paint_line(self, start: QPointF, end: QPointF):
        # Interpolate points for smooth line
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        distance = (dx**2 + dy**2)**0.5
        steps = max(1, int(distance / 4))
        
        for i in range(steps + 1):
            t = i / steps if steps > 0 else 0
            x = start.x() + dx * t
            y = start.y() + dy * t
            self.paint_at(QPointF(x, y))
    
    def update_display(self):
        """Update visual representation from grid data"""
        self.mask_pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self.mask_pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        
        # Draw grid blocks
        for gx in range(self.grid_width):
            for gy in range(self.grid_height):
                if self.mask_grid[gx][gy] > 0:
                    x = gx * 8
                    y = gy * 8
                    painter.fillRect(x, y, 8, 8, self.brush_color)
        
        painter.end()
        self.setPixmap(self.mask_pixmap)
    
    def get_mask_image(self) -> Image.Image:
        """Get PIL Image mask from grid data"""
        mask_array = np.zeros((self.canvas_h, self.canvas_w), dtype=np.uint8)
        
        for gx in range(self.grid_width):
            for gy in range(self.grid_height):
                if self.mask_grid[gx][gy] > 0:
                    y1, y2 = gy * 8, min((gy + 1) * 8, self.canvas_h)
                    x1, x2 = gx * 8, min((gx + 1) * 8, self.canvas_w)
                    mask_array[y1:y2, x1:x2] = 255
        
        return Image.fromarray(mask_array, mode='L')
    
    def clear_mask(self):
        """Clear all mask data"""
        self.mask_grid = [[0 for _ in range(self.grid_height)] for _ in range(self.grid_width)]
        self.update_display()


class ResizeHandle(QGraphicsEllipseItem):
    def __init__(self, position: str, owner: ImageLayerItem):
        super().__init__(-5, -5, 10, 10)
        self.position = position
        self.owner = owner
        self.setBrush(QColor(255, 255, 255))
        self.setPen(QPen(QColor(0, 0, 0)))
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self._press_scene_pos: Optional[QPointF] = None
        self._press_scale: float = 1.0
        self._dir_scene: Optional[QVector2D] = None

    def mousePressEvent(self, event):
        self._press_scene_pos = event.scenePos()
        self._press_scale = self.owner.layer_data.scale
        # Outward direction (layer center -> handle), in scene coords
        center_scene = self.owner.mapToScene(self.owner.boundingRect().center())
        handle_scene = self.mapToScene(self.boundingRect().center())
        v = QVector2D(handle_scene - center_scene)
        self._dir_scene = v.normalized() if v.length() > 0 else QVector2D(1, 0)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_scene_pos is None or self._dir_scene is None:
            return super().mouseMoveEvent(event)
        m = QVector2D(event.scenePos() - self._press_scene_pos)
        # Signed projection: outward > 0, inward < 0 (rotation-independent)
        signed = QVector2D.dotProduct(m, self._dir_scene)
        # Normalize by visual size for stable feel
        srect = self.owner.sceneBoundingRect()
        base = max(srect.width(), srect.height(), 1.0)
        scale_delta = signed / base  # ~1.0 when dragged by ~item size
        new_scale = max(0.05, min(16.0, self._press_scale * (1.0 + scale_delta)))
        if abs(new_scale - self.owner.layer_data.scale) > 1e-6:
            self.owner.set_scale_from_handle(new_scale, self.position)
        super().mouseMoveEvent(event)


# ---------------------------
# Canvas / View
# ---------------------------

class SketchbookCanvas(QGraphicsView):
    layer_selected = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.current_canvas_size = (1024, 1024)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)

        # No infinite panning: disable scroll bars & anchor to center
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

        self.dim_outside: bool = True
        self.canvas_root: Optional[CanvasRootItem] = None
        self.canvas_bounds = QRectF(0, 0, 0, 0)
        self.layers: Dict[str, ImageLayerItem] = {}
        self.selected_layer_id: Optional[str] = None
        
        # Inpaint mode
        self.inpaint_mode = False
        self.inpaint_layer: Optional[InpaintLayerItem] = None
        
        self.setup_canvas()

    # ---- fitting ----
    def _fit_width(self):
        if self.canvas_bounds.isEmpty():
            return
        vw = max(1, self.viewport().width())
        cw = max(1.0, self.canvas_bounds.width())
        scale = vw / cw
        # guard: avoid NaN/inf or crazy values
        scale = max(0.01, min(100.0, scale))
        self.resetTransform()
        self.scale(scale, scale)
        self.centerOn(self.canvas_bounds.center())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_width()

    def setup_canvas(self):
        w, h = self.current_canvas_size
        self.scene.clear()
        self.layers.clear()

        # No infinite area: scene rect == canvas rect
        self.canvas_bounds = QRectF(0, 0, w, h)
        self.scene.setSceneRect(self.canvas_bounds)

        # Logical clip container
        self.canvas_root = CanvasRootItem(self.canvas_bounds)
        self.canvas_root.setZValue(0)
        self.scene.addItem(self.canvas_root)

        # Fit to width & center
        self._fit_width()

    def change_canvas_size(self, w: int, h: int):
        self.current_canvas_size = (w, h)
        self.canvas_bounds = QRectF(0, 0, w, h)
        if self.canvas_root:
            self.canvas_root.setRect(self.canvas_bounds)
        self.scene.setSceneRect(self.canvas_bounds)
        self.viewport().update()
        self._fit_width()

    # --- layer management ---
    def add_layer(self, ld: LayerData) -> str:
        item = ImageLayerItem(ld)
        item.setParentItem(self.canvas_root)
        self.layers[ld.id] = item
        # Ensure proper Z-order by setting it based on actual layer count
        item.setZValue(ld.z_order)
        self.select_layer(ld.id)
        return ld.id
    
    def get_max_z_order(self) -> int:
        """Get the highest Z-order value among existing layers"""
        if not self.layers:
            return 0
        return max(item.layer_data.z_order for item in self.layers.values())

    def remove_layer(self, layer_id: str):
        if layer_id in self.layers:
            item = self.layers.pop(layer_id)
            if item.scene():
                self.scene.removeItem(item)
            if self.selected_layer_id == layer_id:
                self.selected_layer_id = None
                self.layer_selected.emit("")

    def select_layer(self, layer_id: Optional[str]):
        if self.selected_layer_id and self.selected_layer_id in self.layers:
            self.layers[self.selected_layer_id].set_selected(False)
        self.selected_layer_id = layer_id
        if layer_id and layer_id in self.layers:
            self.layers[layer_id].set_selected(True)
            self.layer_selected.emit(layer_id)
        else:
            self.layer_selected.emit("")

    def update_layer_visibility(self, layer_id: str, visible: bool):
        item = self.layers.get(layer_id)
        if item is not None:
            item.setVisible(visible)
            item.layer_data.visible = visible

    def update_layer_order(self, layer_id: str, z: int):
        item = self.layers.get(layer_id)
        if item is not None:
            item.setZValue(z)
            item.layer_data.z_order = z

    # Visual only (optional): border + outside dim
    def drawForeground(self, painter, rect):
        painter.save()
        # 1) Border in SCENE coordinates
        painter.setPen(QPen(QColor(120, 120, 120), 2))
        painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        painter.drawRect(self.canvas_bounds)

        if self.dim_outside:
            # 2) Mask in VIEWPORT coordinates (reset transform first)
            painter.setWorldTransform(QTransform())  # or painter.resetTransform()
            view_rect = QRectF(self.viewport().rect())
            canvas_view = QRectF(self.mapFromScene(self.canvas_bounds).boundingRect())

            outer = QPainterPath(); outer.addRect(view_rect)
            inner = QPainterPath(); inner.addRect(canvas_view)

            painter.setPen(QPen(Qt.PenStyle.NoPen))
            painter.setBrush(QColor(0, 0, 0, 90))
            painter.drawPath(outer.subtracted(inner))
        painter.restore()

    # Export just renders the canvas rect
    def export_composite(self) -> Optional[QPixmap]:
        if self.canvas_bounds.isEmpty():
            return None
        w = int(self.canvas_bounds.width()); h = int(self.canvas_bounds.height())
        if w <= 0 or h <= 0:
            return None
        pm = QPixmap(w, h); pm.fill(QColor(255, 255, 255))
        p = QPainter(pm)
        self.scene.render(p, target=QRectF(0, 0, w, h), source=self.canvas_bounds)
        p.end()
        return pm
    
    def toggle_inpaint_mode(self, enabled: bool):
        """Toggle inpaint mode on/off"""
        self.inpaint_mode = enabled
        
        if enabled:
            # Create inpaint layer if not exists
            if not self.inpaint_layer:
                self.inpaint_layer = InpaintLayerItem(self.current_canvas_size)
                self.inpaint_layer.setParentItem(self.canvas_root)
                self.inpaint_layer.setPos(0, 0)
            # Disable normal interaction
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            # Deselect all layers
            self.select_layer(None)
        else:
            # Remove inpaint layer
            if self.inpaint_layer:
                if self.inpaint_layer.scene():
                    self.scene.removeItem(self.inpaint_layer)
                self.inpaint_layer = None
            # Re-enable normal interaction
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
    
    def get_inpaint_mask(self) -> Optional[Image.Image]:
        """Get the current inpaint mask as PIL Image"""
        if self.inpaint_layer:
            return self.inpaint_layer.get_mask_image()
        return None


# ---------------------------
# Layer panel (minimal, with fallbacks)
# ---------------------------

class LayerPanel(QWidget):
    layer_selected = pyqtSignal(str)
    layer_visibility_changed = pyqtSignal(str, bool)
    layer_order_changed = pyqtSignal(str, int)
    layer_delete_requested = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.layers_data: Dict[str, LayerData] = {}
        self._updating = False
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        header_label = QLabel("레이어")
        header_label.setStyleSheet(f"font-size: {get_scaled_font_size(16)}px; font-weight: bold; color: #000000;")
        layout.addWidget(header_label)

        self.layer_list = QListWidget()
        self.layer_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.layer_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.layer_list.model().rowsMoved.connect(self._on_rows_moved)
        # Enhanced styling for layer list
        self.layer_list.setStyleSheet(f"""
            QListWidget {{
                background-color: #1e1e1e;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
            }}
            QListWidget::item {{
                padding: 2px;
                border-bottom: 1px solid #2a2a2a;
            }}
            QListWidget::item:selected {{
                background-color: #3a5a8a;
            }}
            QListWidget::item:hover {{
                background-color: #2a3a4a;
            }}
        """)
        layout.addWidget(self.layer_list)

        controls_layout = QHBoxLayout()
        self.delete_button = QPushButton("🗑️ 삭제")
        self.delete_button.clicked.connect(self._on_delete_clicked)
        controls_layout.addWidget(self.delete_button)
        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        # Theme
        ds = get_dynamic_styles()
        self.layer_list.setStyleSheet(ds.get('list_widget', ''))
        self.delete_button.setStyleSheet(ds.get('secondary_button', ''))

    def add_layer(self, layer_data: LayerData):
        self.layers_data[layer_data.id] = layer_data
        item = QListWidgetItem()

        widget = QWidget()
        h = QHBoxLayout(widget)
        h.setContentsMargins(4, 4, 4, 4)
        h.setSpacing(8)

        # Visibility checkbox
        checkbox = QCheckBox()
        checkbox.setChecked(layer_data.visible)
        checkbox.toggled.connect(lambda checked, lid=layer_data.id: self.layer_visibility_changed.emit(lid, checked))
        h.addWidget(checkbox)

        # Thumbnail
        thumbnail_label = QLabel()
        thumb_size = get_scaled_size(40)
        thumbnail_label.setFixedSize(thumb_size, thumb_size)
        thumbnail_label.setStyleSheet(f"""
            QLabel {{
                border: 1px solid #555;
                background: #2b2b2b;
            }}
        """)
        thumbnail_label.setScaledContents(True)
        
        # Generate thumbnail from pixmap if available
        if layer_data.pixmap:
            thumbnail = layer_data.pixmap.scaled(
                thumb_size, thumb_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            thumbnail_label.setPixmap(thumbnail)
        elif os.path.exists(layer_data.image_path):
            # Load thumbnail directly
            thumbnail = QPixmap(layer_data.image_path).scaled(
                thumb_size, thumb_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            thumbnail_label.setPixmap(thumbnail)
        
        h.addWidget(thumbnail_label)

        # Layer name
        name_label = QLabel(layer_data.name)
        name_label.setStyleSheet(f"font-size: {get_scaled_font_size(14)}px; color: #000000;")
        # Truncate long names with ellipsis
        max_width = get_scaled_size(150)
        name_label.setMaximumWidth(max_width)
        name_label.setWordWrap(False)
        fm = name_label.fontMetrics()
        elided_text = fm.elidedText(layer_data.name, Qt.TextElideMode.ElideRight, max_width)
        name_label.setText(elided_text)
        name_label.setToolTip(layer_data.name)  # Show full name on hover
        h.addWidget(name_label)
        h.addStretch()

        item.setData(Qt.ItemDataRole.UserRole, layer_data.id)
        # Set a fixed height for consistency
        widget.setFixedHeight(get_scaled_size(48))
        item.setSizeHint(widget.sizeHint())

        # Insert at the top of the list (newest layers on top)
        self.layer_list.insertItem(0, item)
        self.layer_list.setItemWidget(item, widget)
        item.setSelected(True)
        
        # Update Z-order for all layers after insertion
        self._update_layer_z_order()

    def remove_layer(self, layer_id: str):
        if layer_id in self.layers_data:
            del self.layers_data[layer_id]
        for i in range(self.layer_list.count()):
            it = self.layer_list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == layer_id:
                self.layer_list.takeItem(i)
                break

    def select_layer(self, layer_id: str):
        if self._updating:
            return
        self._updating = True
        try:
            for i in range(self.layer_list.count()):
                it = self.layer_list.item(i)
                it.setSelected(it.data(Qt.ItemDataRole.UserRole) == layer_id)
        finally:
            self._updating = False

    def _on_selection_changed(self):
        if self._updating:
            return
        items = self.layer_list.selectedItems()
        if items:
            lid = items[0].data(Qt.ItemDataRole.UserRole)
            self.layer_selected.emit(lid)

    def _on_rows_moved(self, parent, start, end, destination, row):
        self._update_layer_z_order()
    
    def _update_layer_z_order(self):
        """Update Z-order for all layers based on their position in the list"""
        # Higher in the list => higher z
        total = self.layer_list.count()
        for i in range(total):
            it = self.layer_list.item(i)
            if it:
                lid = it.data(Qt.ItemDataRole.UserRole)
                z = total - i
                self.layer_order_changed.emit(lid, z)
                # Also update the stored layer data
                if lid in self.layers_data:
                    self.layers_data[lid].z_order = z

    def _on_delete_clicked(self):
        items = self.layer_list.selectedItems()
        if items:
            lid = items[0].data(Qt.ItemDataRole.UserRole)
            self.layer_delete_requested.emit(lid)


# ---------------------------
# Generation worker for API calls
# ---------------------------

class InpaintGenerationWorker(QThread):
    """Worker thread for inpaint image generation"""
    generation_finished = pyqtSignal(Image.Image, tuple)  # image, bounding_box
    generation_error = pyqtSignal(str)
    progress_update = pyqtSignal(str)
    
    def __init__(self, app_context, composite_img: Image.Image, mask_img: Image.Image, 
                 main_prompt: str, negative_prompt: str, strength: float = 0.7):
        super().__init__()
        self.app_context = app_context
        self.composite_img = composite_img
        self.mask_img = mask_img
        self.main_prompt = main_prompt
        self.negative_prompt = negative_prompt
        self.strength = strength
    
    def run(self):
        try:
            self.progress_update.emit("Preparing images...")
            
            # Convert images to bytes for API
            composite_bytes = io.BytesIO()
            self.composite_img.save(composite_bytes, format='PNG')
            composite_bytes.seek(0)
            
            # Create small mask for NAI (1/8 size)
            mask_bytes = io.BytesIO()
            if self.app_context and hasattr(self.app_context, 'main_window'):
                api_mode = self.app_context.main_window.get_current_api_mode() if hasattr(self.app_context.main_window, 'get_current_api_mode') else "NAI"
                if api_mode == "NAI":
                    # NAI requires 1/8 size mask
                    small_mask = self.create_small_mask(self.mask_img)
                    small_mask.save(mask_bytes, format='PNG')
                else:
                    # WebUI/ComfyUI use full size mask
                    self.mask_img.save(mask_bytes, format='PNG')
            else:
                self.mask_img.save(mask_bytes, format='PNG')
            mask_bytes.seek(0)
            
            self.progress_update.emit("Collecting parameters...")
            
            # Get parameters from main window if available
            params = {}
            if hasattr(self.app_context, 'main_window'):
                main_window = self.app_context.main_window
                
                # Get API mode and credentials
                api_mode = main_window.get_current_api_mode() if hasattr(main_window, 'get_current_api_mode') else "NAI"
                
                # Get token/credential
                credential = None
                if hasattr(self.app_context, 'secure_token_manager'):
                    if api_mode == "NAI":
                        credential = self.app_context.secure_token_manager.get_token('nai_token')
                    elif api_mode == "COMFYUI":
                        credential = self.app_context.secure_token_manager.get_token('comfyui_url')
                    else:
                        credential = self.app_context.secure_token_manager.get_token('webui_url')
                
                # Get main parameters from main window
                if hasattr(main_window, 'get_main_parameters'):
                    params = main_window.get_main_parameters()
                    params['api_mode'] = api_mode
                    params['credential'] = credential
                    
                    # Collect module parameters
                    if hasattr(self.app_context, 'middle_section_controller'):
                        controller = self.app_context.middle_section_controller
                        if hasattr(controller, 'module_instances'):
                            for module in controller.module_instances:
                                if hasattr(module, 'get_parameters'):
                                    module_params = module.get_parameters()
                                    if module_params:
                                        params.update(module_params)
                    
                    # Override with inpaint-specific settings
                    params['input'] = self.main_prompt if self.main_prompt else params.get('prompt', '')
                    params['prompt'] = params['input']  # Alias for compatibility
                    params['negative_prompt'] = self.negative_prompt if self.negative_prompt else params.get('negative_prompt', '')
                    params['type'] = 'inpaint'
                    params['image_bytes'] = composite_bytes.getvalue()  # Use image_bytes for NAI
                    params['mask_bytes'] = mask_bytes.getvalue()       # Use mask_bytes for NAI
                    params['width'] = self.composite_img.width
                    params['height'] = self.composite_img.height
                    
                    # Use provided strength value
                    params['strength'] = self.strength
                    params['noise'] = 0.0
                else:
                    # Fallback: minimal parameters
                    params = {
                        "input": self.main_prompt,
                        "prompt": self.main_prompt,
                        "negative_prompt": self.negative_prompt,
                        "image_bytes": composite_bytes.getvalue(),
                        "mask_bytes": mask_bytes.getvalue(),
                        "width": self.composite_img.width,
                        "height": self.composite_img.height,
                        "type": "inpaint",
                        "strength": 0.7,
                        "noise": 0.0,
                        "api_mode": api_mode,
                        "credential": credential
                    }
            
            self.progress_update.emit("Sending to API...")
            
            # Call API through context
            if hasattr(self.app_context, 'api_service'):
                result = self.app_context.api_service.call_generation_api(params)
                
                if result:
                    self.progress_update.emit("Processing result...")
                    
                    # Handle different result formats
                    result_img = None
                    
                    # Check various possible result formats
                    if isinstance(result, Image.Image):
                        # Direct PIL Image
                        result_img = result
                    elif isinstance(result, dict):
                        # Dictionary with image key
                        if 'image' in result:
                            if isinstance(result['image'], Image.Image):
                                result_img = result['image']
                            elif isinstance(result['image'], str):
                                # Base64 string
                                img_data = base64.b64decode(result['image'])
                                result_img = Image.open(io.BytesIO(img_data))
                            elif isinstance(result['image'], bytes):
                                # Binary data
                                result_img = Image.open(io.BytesIO(result['image']))
                        elif 'images' in result and result['images']:
                            # List of images (take first)
                            first_img = result['images'][0]
                            if isinstance(first_img, Image.Image):
                                result_img = first_img
                            elif isinstance(first_img, bytes):
                                result_img = Image.open(io.BytesIO(first_img))
                    elif isinstance(result, bytes):
                        # Direct binary data
                        result_img = Image.open(io.BytesIO(result))
                    
                    if result_img:
                        # Calculate bounding box of mask
                        bbox = self.calculate_mask_bbox(self.mask_img)
                        
                        # Apply mask with feathering and crop to bounding box
                        final_img = self.apply_mask_with_feathering_and_crop(result_img, self.mask_img, bbox)
                        
                        self.generation_finished.emit(final_img, bbox)
                    else:
                        self.generation_error.emit("Could not extract image from API response")
                else:
                    self.generation_error.emit("Empty API response")
            else:
                # Fallback: just show test result
                self.progress_update.emit("Demo mode - no API connection")
                # Create a test image with mask applied
                test_img = self.composite_img.copy()
                test_img = self.apply_mask_with_feathering(test_img, self.mask_img)
                self.generation_finished.emit(test_img)
                
        except Exception as e:
            self.generation_error.emit(str(e))
    
    def create_small_mask(self, mask_img: Image.Image) -> Image.Image:
        """Create 1/8 size mask for NAI API"""
        width, height = mask_img.size
        small_width = width // 8
        small_height = height // 8
        
        # Convert mask to numpy array
        mask_array = np.array(mask_img.convert('L'))
        
        # Create small mask array
        small_mask_array = np.zeros((small_height, small_width), dtype=np.uint8)
        
        # Process each 8x8 block
        for y in range(small_height):
            for x in range(small_width):
                # Get 8x8 block from original mask
                block_y1 = y * 8
                block_y2 = min((y + 1) * 8, height)
                block_x1 = x * 8
                block_x2 = min((x + 1) * 8, width)
                
                # If any pixel in the block is masked, mark the small mask pixel
                block = mask_array[block_y1:block_y2, block_x1:block_x2]
                if np.any(block > 128):
                    small_mask_array[y, x] = 255
        
        # Convert back to PIL Image
        small_mask = Image.fromarray(small_mask_array, mode='L')
        
        print(f"✅ Small mask created: {width}x{height} → {small_width}x{small_height}")
        return small_mask
    
    def calculate_mask_bbox(self, mask_img: Image.Image) -> tuple:
        """Calculate bounding box of non-zero mask pixels"""
        mask_array = np.array(mask_img.convert('L'))
        
        # Find non-zero pixels
        non_zero = np.where(mask_array > 128)
        
        if len(non_zero[0]) == 0:
            # No mask, return full image bounds
            return (0, 0, mask_img.width, mask_img.height)
        
        # Calculate bounding box
        min_y = int(np.min(non_zero[0]))
        max_y = int(np.max(non_zero[0]))
        min_x = int(np.min(non_zero[1]))
        max_x = int(np.max(non_zero[1]))
        
        # Add small padding (but stay within image bounds)
        padding = 16
        min_x = max(0, min_x - padding)
        min_y = max(0, min_y - padding)
        max_x = min(mask_img.width - 1, max_x + padding)
        max_y = min(mask_img.height - 1, max_y + padding)
        
        bbox = (min_x, min_y, max_x + 1, max_y + 1)
        print(f"📦 Mask bounding box: {bbox}")
        return bbox
    
    def apply_mask_with_feathering_and_crop(self, generated_img: Image.Image, mask_img: Image.Image, 
                                           bbox: tuple, feather_pixels: int = 6) -> Image.Image:
        """Apply mask with feathering and crop to bounding box"""
        # First apply mask to full image
        full_result = self.apply_mask_with_feathering(generated_img, mask_img, feather_pixels)
        
        # Crop to bounding box
        cropped = full_result.crop(bbox)
        
        return cropped
    
    def apply_mask_with_feathering(self, generated_img: Image.Image, mask_img: Image.Image, 
                                   feather_pixels: int = 6) -> Image.Image:
        """Apply mask to generated image with edge feathering"""
        # Ensure RGBA mode
        if generated_img.mode != 'RGBA':
            generated_img = generated_img.convert('RGBA')
        
        # Create feathered mask
        mask = mask_img.convert('L')
        
        # Apply Gaussian blur for feathering
        if feather_pixels > 0:
            mask = mask.filter(ImageFilter.GaussianBlur(radius=feather_pixels))
        
        # Create transparent image
        result = Image.new('RGBA', generated_img.size, (0, 0, 0, 0))
        
        # Composite using feathered mask
        result.paste(generated_img, (0, 0))
        
        # Apply mask as alpha channel
        result.putalpha(mask)
        
        return result


# ---------------------------
# Inpaint control window
# ---------------------------

class InpaintControlWindow(QDialog):
    """Floating window for inpaint controls"""
    generate_clicked = pyqtSignal(str, str, float)  # main_prompt, negative_prompt, strength
    result_accepted = pyqtSignal()
    result_cancelled = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Inpaint Controls")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setFixedSize(1080, 380)
        
        self.brush_size = 50
        self.strength_value = 1.0
        self.setup_ui()
    
    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Left: Brush controls
        brush_widget = QWidget()
        brush_layout = QVBoxLayout(brush_widget)
        brush_layout.setContentsMargins(0, 0, 0, 0)
        
        brush_label = QLabel("브러시 크기:")
        brush_label.setStyleSheet(f"font-size: {get_scaled_font_size(14)}px;")
        brush_layout.addWidget(brush_label)
        
        self.brush_slider = QSlider(Qt.Orientation.Horizontal)
        self.brush_slider.setRange(8, 160)
        self.brush_slider.setValue(self.brush_size)
        self.brush_slider.valueChanged.connect(self._on_brush_size_changed)
        brush_layout.addWidget(self.brush_slider)
        
        self.brush_size_label = QLabel(f"{self.brush_size}px")
        self.brush_size_label.setStyleSheet(f"font-size: {get_scaled_font_size(12)}px;")
        brush_layout.addWidget(self.brush_size_label)
        
        self.generate_button = QPushButton("🎨 Generate")
        self.generate_button.setStyleSheet(get_dynamic_styles().get('primary_button', ''))
        self.generate_button.clicked.connect(self._on_generate)
        brush_layout.addWidget(self.generate_button)
        
        brush_layout.addWidget(QLabel(" "))  # Spacer
        
        # Strength slider
        strength_label = QLabel("Strength:")
        strength_label.setStyleSheet(f"font-size: {get_scaled_font_size(14)}px;")
        brush_layout.addWidget(strength_label)
        
        self.strength_slider = QSlider(Qt.Orientation.Horizontal)
        self.strength_slider.setRange(1, 100)  # 0.01 to 1.0 (multiply by 0.01)
        self.strength_slider.setValue(100)  # Default 1.0
        self.strength_slider.valueChanged.connect(self._on_strength_changed)
        brush_layout.addWidget(self.strength_slider)
        
        self.strength_value_label = QLabel("1.00")
        self.strength_value_label.setStyleSheet(f"font-size: {get_scaled_font_size(12)}px;")
        brush_layout.addWidget(self.strength_value_label)
        
        # Accept/Cancel buttons (initially hidden)
        self.accept_button = QPushButton("✅ 승인")
        self.accept_button.setStyleSheet(get_dynamic_styles().get('primary_button', ''))
        self.accept_button.clicked.connect(self._on_accept_result)
        self.accept_button.setVisible(False)
        brush_layout.addWidget(self.accept_button)
        
        self.cancel_button = QPushButton("❌ 취소")
        self.cancel_button.setStyleSheet(get_dynamic_styles().get('secondary_button', ''))
        self.cancel_button.clicked.connect(self._on_cancel_result)
        self.cancel_button.setVisible(False)
        brush_layout.addWidget(self.cancel_button)
        
        brush_layout.addStretch()
        brush_widget.setFixedWidth(200)
        layout.addWidget(brush_widget)
        
        # Center: Main prompt
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(5, 0, 5, 0)
        
        main_label = QLabel("Main Prompt:")
        main_label.setStyleSheet(f"font-size: {get_scaled_font_size(14)}px;")
        main_layout.addWidget(main_label)
        
        self.main_prompt = QTextEdit()
        self.main_prompt.setPlaceholderText("Enter main prompt...")
        self.main_prompt.setStyleSheet(f"font-size: {get_scaled_font_size(12)}px;")
        main_layout.addWidget(self.main_prompt)
        
        layout.addWidget(main_widget)
        
        # Right: Negative prompt
        neg_widget = QWidget()
        neg_layout = QVBoxLayout(neg_widget)
        neg_layout.setContentsMargins(5, 0, 5, 0)
        
        neg_label = QLabel("Negative Prompt:")
        neg_label.setStyleSheet(f"font-size: {get_scaled_font_size(14)}px;")
        neg_layout.addWidget(neg_label)
        
        self.negative_prompt = QTextEdit()
        self.negative_prompt.setPlaceholderText("Enter negative prompt...")
        self.negative_prompt.setStyleSheet(f"font-size: {get_scaled_font_size(12)}px;")
        neg_layout.addWidget(self.negative_prompt)
        
        layout.addWidget(neg_widget)
    
    def _on_brush_size_changed(self, value):
        aligned_value = (value // 8) * 8
        if aligned_value < 8:
            aligned_value = 8
        self.brush_size = aligned_value
        self.brush_size_label.setText(f"{aligned_value}px")
        
        # Update the canvas brush size
        if self.parent() and hasattr(self.parent(), 'canvas'):
            if self.parent().canvas.inpaint_layer:
                self.parent().canvas.inpaint_layer.set_brush_size(aligned_value)
    
    def _on_strength_changed(self, value):
        self.strength_value = value / 100.0
        self.strength_value_label.setText(f"{self.strength_value:.2f}")
    
    def _on_generate(self):
        main_text = self.main_prompt.toPlainText()
        neg_text = self.negative_prompt.toPlainText()
        self.generate_clicked.emit(main_text, neg_text, self.strength_value)
    
    def show_result_buttons(self, show: bool):
        """Show or hide accept/cancel buttons"""
        self.accept_button.setVisible(show)
        self.cancel_button.setVisible(show)
        self.generate_button.setEnabled(not show)
    
    def _on_accept_result(self):
        self.result_accepted.emit()
        self.show_result_buttons(False)
    
    def _on_cancel_result(self):
        self.result_cancelled.emit()
        self.show_result_buttons(False)


# ---------------------------
# Main widget
# ---------------------------

class SketchbookWidget(QWidget):
    def __init__(self, app_context=None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_context = app_context
        self.inpaint_control_window = None
        self.inpaint_worker = None
        self.inpaint_result_count = 0
        self.progress_dialog = None
        self.pending_result = None  # Store pending result
        self.pending_bbox = None    # Store pending bounding box
        self.undo_stack = []        # Undo history
        self.redo_stack = []        # Redo history
        self.setup_ui()
        self.connect_signals()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        toolbar = QHBoxLayout(); toolbar.setContentsMargins(5, 5, 5, 5)

        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(["832 x 1216", "1024 x 1024", "1216 x 832"])
        self.resolution_combo.setCurrentIndex(1)
        self.resolution_combo.currentTextChanged.connect(self._on_resolution_changed)
        toolbar.addWidget(QLabel("캔버스 크기:"))
        toolbar.addWidget(self.resolution_combo)
        
        # Inpaint mode button
        self.inpaint_button = QPushButton("🖌️ 인페인트 모드")
        self.inpaint_button.setCheckable(True)
        self.inpaint_button.toggled.connect(self._on_inpaint_mode_toggled)
        toolbar.addWidget(self.inpaint_button)
        
        toolbar.addStretch()

        self.add_image_button = QPushButton("➕ 이미지 추가")
        self.add_image_button.clicked.connect(self._on_add_image)
        toolbar.addWidget(self.add_image_button)

        self.export_button = QPushButton("💾 내보내기")
        self.export_button.clicked.connect(self._on_export)
        toolbar.addWidget(self.export_button)

        layout.addLayout(toolbar)

        # Splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.canvas = SketchbookCanvas()
        self.splitter.addWidget(self.canvas)
        self.layer_panel = LayerPanel()
        self.splitter.addWidget(self.layer_panel)
        self.splitter.setSizes([800, 300])
        layout.addWidget(self.splitter)

        # Theme
        ds = get_dynamic_styles()
        self.add_image_button.setStyleSheet(ds.get('primary_button', ''))
        self.export_button.setStyleSheet(ds.get('secondary_button', ''))
        self.resolution_combo.setStyleSheet(ds.get('compact_combobox', ''))
        self.inpaint_button.setStyleSheet(ds.get('primary_button', ''))

    def connect_signals(self):
        # Canvas <-> Panel synchronization
        self.canvas.layer_selected.connect(self._on_canvas_layer_selected)
        self.layer_panel.layer_selected.connect(self._on_panel_layer_selected)
        # Layer ops
        self.layer_panel.layer_visibility_changed.connect(self.canvas.update_layer_visibility)
        self.layer_panel.layer_order_changed.connect(self.canvas.update_layer_order)
        self.layer_panel.layer_delete_requested.connect(self._on_delete_layer)

    # --- signal handlers ---
    def _on_canvas_layer_selected(self, layer_id: str):
        self.layer_panel.select_layer(layer_id)

    def _on_panel_layer_selected(self, layer_id: str):
        self.canvas.select_layer(layer_id)

    def _on_resolution_changed(self, text: str):
        try:
            w, h = [int(x.strip()) for x in text.lower().split('x')]
        except Exception:
            return
        self.canvas.change_canvas_size(w, h)

    def _on_add_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "이미지 선택", "", "Image Files (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if file_path:
            self.add_image_from_path(file_path)

    def _on_delete_layer(self, layer_id: str):
        self.canvas.remove_layer(layer_id)
        self.layer_panel.remove_layer(layer_id)

    def _on_export(self):
        pm = self.canvas.export_composite()
        if pm is None:
            QMessageBox.warning(self, "내보내기", "캔버스가 비어있습니다.")
            return
        save_path, _ = QFileDialog.getSaveFileName(self, "내보내기", "composite.png", "PNG (*.png)")
        if save_path:
            pm.save(save_path, "PNG")
            QMessageBox.information(self, "내보내기", f"저장됨: {save_path}")

    # --- API ---
    def add_image_from_path(self, image_path: str, layer_name: Optional[str] = None):
        if not os.path.exists(image_path):
            QMessageBox.warning(self, "오류", f"이미지 파일을 찾을 수 없습니다: {image_path}")
            return
        if not layer_name:
            layer_name = os.path.basename(image_path)
        
        # Get the highest Z-order and add 1 for the new layer
        max_z = self.canvas.get_max_z_order()
        
        layer_data = LayerData(
            name=layer_name,
            image_path=image_path,
            position=(100.0, 100.0),
            z_order=max_z + 1,
        )
        layer_id = self.canvas.add_layer(layer_data)
        self.layer_panel.add_layer(layer_data)
        print(f"✅ Added layer: {layer_name} (ID: {layer_id}, Z: {layer_data.z_order})")

    def export_composite(self) -> Optional[QPixmap]:
        return self.canvas.export_composite()
    
    def keyPressEvent(self, event):
        """Handle keyboard shortcuts"""
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Z:
                self.undo()
            elif event.key() == Qt.Key.Key_Y:
                self.redo()
        super().keyPressEvent(event)
    
    def undo(self):
        """Undo last action"""
        if not self.undo_stack:
            return
        
        action = self.undo_stack.pop()
        action_type, data = action
        
        if action_type == 'add_layer':
            # Remove the layer
            layer_id = data.id
            self.canvas.remove_layer(layer_id)
            self.layer_panel.remove_layer(layer_id)
            self.redo_stack.append(action)
            print(f"↩️ Undo: Removed layer {data.name}")
            
        elif action_type == 'move_layer':
            # Restore previous position
            layer_id, old_pos, new_pos = data
            if layer_id in self.canvas.layers:
                item = self.canvas.layers[layer_id]
                item.setPos(QPointF(*old_pos))
                item.layer_data.position = old_pos
                self.redo_stack.append(('move_layer', (layer_id, new_pos, old_pos)))
                print(f"↩️ Undo: Moved layer back to {old_pos}")
    
    def redo(self):
        """Redo last undone action"""
        if not self.redo_stack:
            return
        
        action = self.redo_stack.pop()
        action_type, data = action
        
        if action_type == 'add_layer':
            # Re-add the layer
            layer_id = self.canvas.add_layer(data)
            self.layer_panel.add_layer(data)
            self.undo_stack.append(action)
            print(f"↪️ Redo: Re-added layer {data.name}")
            
        elif action_type == 'move_layer':
            # Apply the move again
            layer_id, old_pos, new_pos = data
            if layer_id in self.canvas.layers:
                item = self.canvas.layers[layer_id]
                item.setPos(QPointF(*new_pos))
                item.layer_data.position = new_pos
                self.undo_stack.append(('move_layer', (layer_id, old_pos, new_pos)))
                print(f"↪️ Redo: Moved layer to {new_pos}")
    
    def record_layer_move(self, layer_id: str, old_pos: tuple, new_pos: tuple):
        """Record layer movement for undo/redo"""
        self.undo_stack.append(('move_layer', (layer_id, old_pos, new_pos)))
        self.redo_stack.clear()
        print(f"📝 Recorded move: {old_pos} → {new_pos}")
    
    def _on_inpaint_progress_update(self, message: str):
        """Update progress dialog with status message"""
        if self.progress_dialog:
            self.progress_dialog.setLabelText(message)
    
    def _on_inpaint_generation_error(self, error_msg: str):
        """Handle generation error"""
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
        
        QMessageBox.critical(self, "생성 오류", f"인페인트 생성 실패:\n{error_msg}")
        print(f"❌ Inpaint generation error: {error_msg}")
    
    def _on_inpaint_generation_finished(self, result_img: Image.Image, bbox: tuple):
        """Handle successful generation - show preview and wait for user decision"""
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
        
        # Store pending result
        self.pending_result = result_img
        self.pending_bbox = bbox
        
        # Hide inpaint mask temporarily
        if self.canvas.inpaint_layer:
            self.canvas.inpaint_layer.setVisible(False)
        
        # Create preview layer
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
            result_img.save(tmp_file.name, 'PNG')
            temp_path = tmp_file.name
        
        # Position based on bounding box
        x_pos = bbox[0] if bbox else 0
        y_pos = bbox[1] if bbox else 0
        
        preview_data = LayerData(
            id="preview_layer",
            name="Preview",
            image_path=temp_path,
            position=(float(x_pos), float(y_pos)),
            z_order=999,  # Always on top
        )
        
        # Add preview layer
        self.preview_layer_id = self.canvas.add_layer(preview_data)
        
        # Show accept/cancel buttons
        if self.inpaint_control_window:
            self.inpaint_control_window.show_result_buttons(True)
        
        print(f"🔍 Preview shown at position ({x_pos}, {y_pos})")
    
    def _on_inpaint_result_accepted(self):
        """User accepted the result - finalize it"""
        if not self.pending_result:
            return
        
        # Remove preview layer
        if hasattr(self, 'preview_layer_id'):
            self.canvas.remove_layer(self.preview_layer_id)
        
        # Create final layer
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
            self.pending_result.save(tmp_file.name, 'PNG')
            temp_path = tmp_file.name
        
        self.inpaint_result_count += 1
        layer_name = f"inpaint_result_{self.inpaint_result_count}"
        
        # Position based on bounding box
        x_pos = self.pending_bbox[0] if self.pending_bbox else 0
        y_pos = self.pending_bbox[1] if self.pending_bbox else 0
        
        max_z = self.canvas.get_max_z_order()
        
        layer_data = LayerData(
            name=layer_name,
            image_path=temp_path,
            position=(float(x_pos), float(y_pos)),
            z_order=max_z + 1,
        )
        
        # Add to undo stack
        self.undo_stack.append(('add_layer', layer_data))
        self.redo_stack.clear()
        
        # Add final layer
        layer_id = self.canvas.add_layer(layer_data)
        self.layer_panel.add_layer(layer_data)
        
        print(f"✅ Inpaint result accepted: {layer_name} (ID: {layer_id})")
        
        # Clear pending
        self.pending_result = None
        self.pending_bbox = None
        
        # Clear inpaint mask
        if self.canvas.inpaint_layer:
            self.canvas.inpaint_layer.clear_mask()
            self.canvas.inpaint_layer.setVisible(True)
    
    def _on_inpaint_result_cancelled(self):
        """User cancelled the result - discard it"""
        # Remove preview layer
        if hasattr(self, 'preview_layer_id'):
            self.canvas.remove_layer(self.preview_layer_id)
        
        # Show inpaint mask again
        if self.canvas.inpaint_layer:
            self.canvas.inpaint_layer.setVisible(True)
        
        # Clear pending
        self.pending_result = None
        self.pending_bbox = None
        
        print("❌ Inpaint result cancelled")
    
    def _on_inpaint_mode_toggled(self, checked: bool):
        """Handle inpaint mode toggle"""
        self.canvas.toggle_inpaint_mode(checked)
        
        if checked:
            # Show inpaint control window
            if not self.inpaint_control_window:
                self.inpaint_control_window = InpaintControlWindow(self)
                self.inpaint_control_window.generate_clicked.connect(self._on_inpaint_generate)
                self.inpaint_control_window.result_accepted.connect(self._on_inpaint_result_accepted)
                self.inpaint_control_window.result_cancelled.connect(self._on_inpaint_result_cancelled)
            
            # Position window at bottom of canvas
            canvas_geom = self.canvas.geometry()
            window_x = canvas_geom.x() + (canvas_geom.width() - 1080) // 2
            window_y = canvas_geom.y() + canvas_geom.height() - 180
            self.inpaint_control_window.move(self.mapToGlobal(QPointF(window_x, window_y)).toPoint())
            self.inpaint_control_window.show()
            
            # Disable other buttons
            self.add_image_button.setEnabled(False)
            self.export_button.setEnabled(False)
        else:
            # Hide control window
            if self.inpaint_control_window:
                self.inpaint_control_window.hide()
            
            # Re-enable buttons
            self.add_image_button.setEnabled(True)
            self.export_button.setEnabled(True)
    
    def _on_inpaint_generate(self, main_prompt: str, negative_prompt: str, strength: float):
        """Handle generate button from inpaint control window"""
        # Get mask image first
        mask = self.canvas.get_inpaint_mask()
        if not mask:
            QMessageBox.warning(self, "오류", "마스크가 비어있습니다. 인페인트 영역을 그려주세요.")
            return
        
        # Temporarily hide inpaint layer for composite generation
        if self.canvas.inpaint_layer:
            self.canvas.inpaint_layer.setVisible(False)
        
        # Get composite image without inpaint layer
        composite = self.canvas.export_composite()
        if not composite:
            QMessageBox.warning(self, "오류", "캔버스가 비어있습니다.")
            return
        
        # Restore inpaint layer visibility
        if self.canvas.inpaint_layer:
            self.canvas.inpaint_layer.setVisible(True)
        
        # Convert QPixmap to PIL Image
        composite_img = self._qpixmap_to_pil(composite)
        
        # Show progress dialog
        self.progress_dialog = QProgressDialog("인페인트 이미지 생성 중...", "취소", 0, 0, self)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setCancelButton(None)  # Disable cancel for now
        self.progress_dialog.show()
        
        # Create and start worker thread
        self.inpaint_worker = InpaintGenerationWorker(
            self.app_context, composite_img, mask, main_prompt, negative_prompt, strength
        )
        
        # Connect signals
        self.inpaint_worker.generation_finished.connect(self._on_inpaint_generation_finished)
        self.inpaint_worker.generation_error.connect(self._on_inpaint_generation_error)
        self.inpaint_worker.progress_update.connect(self._on_inpaint_progress_update)
        
        # Start generation
        self.inpaint_worker.start()
        
        print(f"🎨 Starting inpaint generation...")
        print(f"   Main prompt: {main_prompt}")
        print(f"   Negative prompt: {negative_prompt}")
    
    def _qpixmap_to_pil(self, pixmap: QPixmap) -> Image.Image:
        """Convert QPixmap to PIL Image"""
        # Save to temp file and load as PIL (safer method)
        tmp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        tmp_filename = tmp_file.name
        tmp_file.close()  # Close file handle immediately
        
        pixmap.save(tmp_filename, 'PNG')
        img = Image.open(tmp_filename)
        # Convert to RGBA to maintain consistency
        img_copy = img.convert('RGBA').copy()
        img.close()  # Close the image file handle
        
        # Try to delete the temp file, but don't fail if it's still in use
        try:
            os.unlink(tmp_filename)
        except PermissionError:
            # File might still be in use by image viewer, ignore
            pass
        
        return img_copy
