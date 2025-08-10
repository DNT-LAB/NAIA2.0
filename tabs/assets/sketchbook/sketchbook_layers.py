"""
Layer-related classes for Sketchbook module
"""

from PyQt6.QtWidgets import QGraphicsRectItem, QGraphicsPixmapItem, QGraphicsItem
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal, QObject
from PyQt6.QtGui import QPen, QBrush, QPixmap, QPainter, QColor, QVector2D
from typing import Optional, Tuple
from .sketchbook_types import LayerData

class ImageLayerItem(QGraphicsPixmapItem):
    """Individual image layer with transform and selection support"""
    
    def __init__(self, layer_data: LayerData, parent: Optional[QGraphicsItem] = None):
        super().__init__(parent)
        self.layer_data = layer_data
        
        # Initialize selection state first (before setting flags)
        self._selected = False
        self.handles = []
        
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        # Don't set default cursor, let hover events handle it
        self.setTransformOriginPoint(0, 0)
        
        # Load and set pixmap
        if layer_data.pixmap:
            self.setPixmap(layer_data.pixmap)
        else:
            pixmap = QPixmap(layer_data.image_path)
            if not pixmap.isNull():
                self.setPixmap(pixmap)
                layer_data.pixmap = pixmap
                layer_data.original_size = (pixmap.width(), pixmap.height())
        
        # Apply transforms
        self.setPos(*layer_data.position)
        self.set_scale_about_center(layer_data.scale)
        self.setRotation(layer_data.rotation)
        self.setZValue(layer_data.z_order)
        self.setVisible(layer_data.visible)
        self.setOpacity(layer_data.opacity)
        
        # Create selection handles
        self._create_handles()

    def _create_handles(self):
        """Create resize handles (initially hidden)"""
        positions = ['tl', 'tm', 'tr', 'ml', 'mr', 'bl', 'bm', 'br']
        for pos in positions:
            handle = ResizeHandle(self, pos)
            handle.setVisible(False)
            self.handles.append(handle)

    def set_selected(self, selected: bool):
        """Set selection state and show/hide handles"""
        self._selected = selected
        self.setSelected(selected)
        for handle in self.handles:
            handle.setVisible(selected)
            if selected:
                handle.update_position()

    def set_scale_about_center(self, scale: float):
        """Scale while keeping center position"""
        old_center = self.sceneBoundingRect().center()
        self.setScale(scale)
        new_center = self.sceneBoundingRect().center()
        shift = old_center - new_center
        self.setPos(self.pos() + shift)
        self.layer_data.scale = scale

    def set_scale_from_handle(self, new_scale: float, handle_pos: str):
        """Scale from a specific handle position with opposite anchor"""
        old_rect = self.sceneBoundingRect()
        
        # Determine anchor point (opposite of handle)
        anchor_map = {
            'tl': old_rect.bottomRight(), 'tm': old_rect.bottomLeft(), 'tr': old_rect.bottomLeft(),
            'ml': old_rect.topRight(), 'mr': old_rect.topLeft(),
            'bl': old_rect.topRight(), 'bm': old_rect.topLeft(), 'br': old_rect.topLeft()
        }
        anchor = anchor_map.get(handle_pos, old_rect.center())
        
        # Apply scale
        self.set_scale_about_center(new_scale)
        
        # Adjust position to keep anchor fixed
        new_rect = self.sceneBoundingRect()
        new_anchor_map = {
            'tl': new_rect.bottomRight(), 'tm': new_rect.bottomLeft(), 'tr': new_rect.bottomLeft(),
            'ml': new_rect.topRight(), 'mr': new_rect.topLeft(),
            'bl': new_rect.topRight(), 'bm': new_rect.topLeft(), 'br': new_rect.topLeft()
        }
        new_anchor = new_anchor_map.get(handle_pos, new_rect.center())
        
        shift = anchor - new_anchor
        self.setPos(self.pos() + shift)

    def itemChange(self, change, value):
        """Track position changes"""
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            new_pos = value
            self.layer_data.position = (new_pos.x(), new_pos.y())
            # Update handles when moving
            if self._selected:
                for handle in self.handles:
                    handle.update_position()
        return super().itemChange(change, value)
    
    def hoverEnterEvent(self, event):
        """Show open hand cursor when hovering over layer"""
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().hoverEnterEvent(event)
    
    def hoverLeaveEvent(self, event):
        """Reset cursor when not hovering"""
        self.unsetCursor()  # This will let the parent handle the cursor
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        """Handle mouse press for selection"""
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        
        # Emit selection through parent scene
        if self.scene() and hasattr(self.scene().parent(), 'layer_selected'):
            self.scene().parent().layer_selected.emit(self.layer_data.id)
        
        # Store position for move recording
        self._press_pos = self.pos()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        """Handle mouse release"""
        # If still hovering, show open hand, otherwise reset
        if self.isUnderMouse():
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()
        
        # Record move if position changed
        if hasattr(self, '_press_pos') and self._press_pos != self.pos():
            if self.scene() and hasattr(self.scene().parent(), 'layer_moved'):
                self.scene().parent().layer_moved.emit(
                    self.layer_data.id, 
                    self._press_pos, 
                    self.pos()
                )
        
        super().mouseReleaseEvent(event)


class ResizeHandle(QGraphicsRectItem):
    """Interactive resize handle for layers"""
    
    def __init__(self, layer_item: ImageLayerItem, position: str):
        super().__init__(-5, -5, 10, 10)
        self.layer_item = layer_item
        self.position = position
        self.setParentItem(layer_item)
        
        # Visual style
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setBrush(QBrush(QColor(100, 150, 255)))
        self.setAcceptHoverEvents(True)
        self._set_cursor_for_position()
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setZValue(1000)  # Ensure handles are on top
        
        # For drag tracking
        self._press_pos = None
        self._press_scale = 1.0
        self._press_scene_pos = None
        self._dir_scene = None
    
    def _set_cursor_for_position(self):
        """Set appropriate cursor based on handle position"""
        cursor_map = {
            'tl': Qt.CursorShape.SizeFDiagCursor,
            'tr': Qt.CursorShape.SizeBDiagCursor,
            'bl': Qt.CursorShape.SizeBDiagCursor,
            'br': Qt.CursorShape.SizeFDiagCursor,
            'tm': Qt.CursorShape.SizeVerCursor,
            'bm': Qt.CursorShape.SizeVerCursor,
            'ml': Qt.CursorShape.SizeHorCursor,
            'mr': Qt.CursorShape.SizeHorCursor
        }
        self.setCursor(cursor_map.get(self.position, Qt.CursorShape.CrossCursor))
    
    def hoverEnterEvent(self, event):
        """Change to crosshair cursor on hover"""
        self.setCursor(Qt.CursorShape.CrossCursor)
        # Make handle slightly bigger on hover
        self.setRect(-6, -6, 12, 12)
        self.setBrush(QBrush(QColor(120, 170, 255)))
        super().hoverEnterEvent(event)
    
    def hoverLeaveEvent(self, event):
        """Reset when not hovering"""
        self.unsetCursor()  # Let parent handle cursor
        # Restore original size
        self.setRect(-5, -5, 10, 10)
        self.setBrush(QBrush(QColor(100, 150, 255)))
        super().hoverLeaveEvent(event)

    def update_position(self):
        """Update handle position based on parent bounds"""
        rect = self.layer_item.boundingRect()
        
        positions = {
            'tl': (rect.left(), rect.top()),
            'tm': (rect.center().x(), rect.top()),
            'tr': (rect.right(), rect.top()),
            'ml': (rect.left(), rect.center().y()),
            'mr': (rect.right(), rect.center().y()),
            'bl': (rect.left(), rect.bottom()),
            'bm': (rect.center().x(), rect.bottom()),
            'br': (rect.right(), rect.bottom()),
        }
        
        if self.position in positions:
            x, y = positions[self.position]
            self.setPos(x, y)

    def mousePressEvent(self, event):
        """Start resize operation"""
        self._press_pos = event.pos()
        self._press_scale = self.layer_item.scale()
        self._press_scene_pos = event.scenePos()
        
        # Calculate outward direction vector
        layer_center = self.layer_item.sceneBoundingRect().center()
        handle_scene = self.scenePos()
        direction = QPointF(handle_scene.x() - layer_center.x(), 
                           handle_scene.y() - layer_center.y())
        length = (direction.x()**2 + direction.y()**2)**0.5
        if length > 0:
            self._dir_scene = QVector2D(direction.x()/length, direction.y()/length)
        else:
            self._dir_scene = QVector2D(1, 0)

    def mouseMoveEvent(self, event):
        """Handle resize drag"""
        if self._press_scene_pos and self._dir_scene:
            movement = QVector2D(event.scenePos() - self._press_scene_pos)
            
            # Project movement onto outward direction
            signed_projection = QVector2D.dotProduct(movement, self._dir_scene)
            
            # Calculate scale change with reduced sensitivity
            # Increased base size for much less sensitive scaling
            base_size = 800.0  # Doubled from 400.0 for half the sensitivity
            scale_delta = signed_projection / base_size
            new_scale = max(0.1, self._press_scale * (1.0 + scale_delta))
            
            # Apply minimum size limit based on original image size
            if hasattr(self.layer_item, 'pixmap'):
                pixmap = self.layer_item.pixmap()
                if pixmap:
                    # Minimum size should be at least 50x50 pixels
                    min_width_scale = 50.0 / pixmap.width() if pixmap.width() > 0 else 0.1
                    min_height_scale = 50.0 / pixmap.height() if pixmap.height() > 0 else 0.1
                    min_scale = max(min_width_scale, min_height_scale, 0.1)
                    new_scale = max(min_scale, new_scale)
            else:
                new_scale = max(0.1, new_scale)
            
            # Apply maximum scale limit to prevent oversizing
            new_scale = min(new_scale, 5.0)
            
            # Apply scale with anchoring
            self.layer_item.set_scale_from_handle(new_scale, self.position)
            
            # Update all handles
            for handle in self.layer_item.handles:
                handle.update_position()

    def mouseReleaseEvent(self, event):
        """End resize operation"""
        # Record scale change if it occurred
        if self._press_scale != self.layer_item.scale():
            if self.scene() and hasattr(self.scene().parent(), 'layer_scaled'):
                self.scene().parent().layer_scaled.emit(
                    self.layer_item.layer_data.id,
                    self._press_scale,
                    self.layer_item.scale()
                )
        
        self._press_pos = None
        self._press_scale = 1.0
        self._press_scene_pos = None
        self._dir_scene = None


class CanvasRootItem(QGraphicsRectItem):
    """Logical canvas container that clips all child layers to canvas bounds"""
    
    def __init__(self, rect: QRectF):
        super().__init__(rect)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape, True)
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))