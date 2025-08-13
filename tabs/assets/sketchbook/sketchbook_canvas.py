"""
Canvas implementation for Sketchbook module
"""

from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene
from PyQt6.QtCore import Qt, QRectF, pyqtSignal, QPointF
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QPixmap, QTransform
from typing import Dict, Optional
from .sketchbook_types import LayerData
from .sketchbook_layers import ImageLayerItem, CanvasRootItem
from .sketchbook_inpaint import InpaintLayerItem, DrawMode

class SketchbookCanvas(QGraphicsView):
    """Main canvas view for the sketchbook"""
    
    layer_selected = pyqtSignal(str)
    layer_moved = pyqtSignal(str, QPointF, QPointF)  # layer_id, old_pos, new_pos
    layer_scaled = pyqtSignal(str, float, float)  # layer_id, old_scale, new_scale

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_canvas_size = (1024, 1024)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # Don't set drag mode to avoid unwanted cursor behavior
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

        # Disable scrollbars for fixed canvas
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

        self.dim_outside = True
        self.canvas_root: Optional[CanvasRootItem] = None
        self.canvas_bounds = QRectF(0, 0, 0, 0)
        self.layers: Dict[str, ImageLayerItem] = {}
        self.selected_layer_id: Optional[str] = None
        
        # Inpaint mode
        self.inpaint_mode = False
        self.inpaint_layer: Optional[InpaintLayerItem] = None
        
        self.setup_canvas()

    def setup_canvas(self, size: tuple = None):
        """Initialize or resize canvas"""
        if size:
            self.current_canvas_size = size
        
        w, h = self.current_canvas_size
        self.canvas_bounds = QRectF(0, 0, w, h)
        
        # Store references to existing items before removing root
        existing_layers = list(self.layers.values()) if self.canvas_root else []
        existing_inpaint = self.inpaint_layer
        
        # Remove items from old root before deleting it
        if self.canvas_root:
            # Unparent all items first
            for layer_item in existing_layers:
                layer_item.setParentItem(None)
            if existing_inpaint:
                existing_inpaint.setParentItem(None)
            
            # Now safe to remove old root
            self.scene.removeItem(self.canvas_root)
        
        # Create new canvas root
        self.canvas_root = CanvasRootItem(self.canvas_bounds)
        self.scene.addItem(self.canvas_root)
        
        # Add white background rectangle
        self.background_rect = self.scene.addRect(self.canvas_bounds, 
                                                  QPen(Qt.PenStyle.NoPen), 
                                                  QBrush(Qt.GlobalColor.white))
        self.background_rect.setParentItem(self.canvas_root)
        self.background_rect.setZValue(-1000)  # Ensure it's always at the bottom
        
        # Re-add existing layers to new root
        for layer_item in existing_layers:
            layer_item.setParentItem(self.canvas_root)
        
        # Re-add inpaint layer if exists
        if existing_inpaint:
            existing_inpaint.setParentItem(self.canvas_root)
            existing_inpaint.setZValue(9999)
        
        # Update scene rect and fit
        margin = 100
        self.scene.setSceneRect(-margin, -margin, w + 2*margin, h + 2*margin)
        self._fit_canvas()

    def _fit_canvas(self):
        """Fit canvas to viewport, considering both width and height"""
        if self.canvas_bounds.isEmpty():
            return
        
        vw = max(1, self.viewport().width())
        vh = max(1, self.viewport().height())
        cw = max(1.0, self.canvas_bounds.width())
        ch = max(1.0, self.canvas_bounds.height())
        
        # Use smaller scale to fit both dimensions
        scale = min(vw / cw, vh / ch)
        
        transform = QTransform()
        transform.scale(scale, scale)
        self.setTransform(transform)
        self.centerOn(self.canvas_bounds.center())

    def resizeEvent(self, event):
        """Handle view resize"""
        super().resizeEvent(event)
        self._fit_canvas()
    
    def wheelEvent(self, event):
        """Handle mouse wheel for brush size adjustment in inpaint mode"""
        if self.inpaint_mode and self.inpaint_layer:
            # Adjust brush size with mouse wheel
            delta = event.angleDelta().y()
            new_size = self.inpaint_layer.adjust_brush_size(delta // 10)
            
            # Notify parent widget if it has a method to update UI
            parent = self.parent()
            while parent:
                if hasattr(parent, 'update_brush_size_display'):
                    parent.update_brush_size_display(new_size)
                    break
                parent = parent.parent()
            
            event.accept()
        else:
            # Default wheel behavior
            super().wheelEvent(event)

    def drawForeground(self, painter, rect):
        """Draw canvas border and dimming mask"""
        super().drawForeground(painter, rect)
        
        # Draw canvas border
        painter.setPen(QPen(QColor(100, 100, 100), 2))
        painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        painter.drawRect(self.canvas_bounds)
        
        if self.dim_outside:
            # Draw dimming mask in viewport coordinates
            painter.setWorldTransform(QTransform())
            viewport_rect = self.viewport().rect()
            canvas_view = QRectF(self.mapFromScene(self.canvas_bounds).boundingRect())
            
            # Create dimming regions (convert float values to int)
            dim_color = QColor(0, 0, 0, 100)
            
            # Top dimming area
            painter.fillRect(QRectF(0, 0, viewport_rect.width(), canvas_view.top()), dim_color)
            
            # Bottom dimming area
            painter.fillRect(QRectF(0, canvas_view.bottom(), viewport_rect.width(), 
                           viewport_rect.height() - canvas_view.bottom()), dim_color)
            
            # Left dimming area
            painter.fillRect(QRectF(0, canvas_view.top(), canvas_view.left(), 
                           canvas_view.height()), dim_color)
            
            # Right dimming area
            painter.fillRect(QRectF(canvas_view.right(), canvas_view.top(), 
                           viewport_rect.width() - canvas_view.right(), 
                           canvas_view.height()), dim_color)

    def add_layer(self, layer_data: LayerData) -> str:
        """Add a new image layer"""
        if not self.canvas_root:
            self.setup_canvas()
        
        item = ImageLayerItem(layer_data, self.canvas_root)
        self.layers[layer_data.id] = item
        
        # Connect signals
        item.layer_data = layer_data
        
        return layer_data.id

    def remove_layer(self, layer_id: str):
        """Remove a layer"""
        if layer_id in self.layers:
            item = self.layers[layer_id]
            self.scene.removeItem(item)
            del self.layers[layer_id]
            
            if self.selected_layer_id == layer_id:
                self.selected_layer_id = None

    def select_layer(self, layer_id: str):
        """Select a specific layer"""
        if self.selected_layer_id and self.selected_layer_id in self.layers:
            self.layers[self.selected_layer_id].set_selected(False)
        
        if layer_id in self.layers:
            self.layers[layer_id].set_selected(True)
            self.selected_layer_id = layer_id
    
    def get_selected_layer(self):
        """Get the currently selected layer"""
        if self.selected_layer_id and self.selected_layer_id in self.layers:
            return self.layers[self.selected_layer_id]
        return None

    def update_layer_visibility(self, layer_id: str, visible: bool):
        """Update layer visibility"""
        if layer_id in self.layers:
            self.layers[layer_id].setVisible(visible)
            self.layers[layer_id].layer_data.visible = visible

    def update_layer_order(self, layer_id: str, z_order: int):
        """Update layer z-order"""
        if layer_id in self.layers:
            self.layers[layer_id].setZValue(z_order)
            self.layers[layer_id].layer_data.z_order = z_order

    def get_max_z_order(self) -> int:
        """Get the highest z-order value"""
        if not self.layers:
            return 0
        return max(layer.layer_data.z_order for layer in self.layers.values())
    
    def get_layers_by_z_order(self) -> list:
        """Get all layers sorted by z-order (lowest to highest)"""
        if not self.layers:
            return []
        
        # Sort layers by z_order
        sorted_layers = sorted(
            self.layers.values(), 
            key=lambda layer: layer.layer_data.z_order
        )
        
        return [layer.layer_data for layer in sorted_layers]

    def export_composite(self) -> Optional[QPixmap]:
        """Export the canvas as a composite image (excluding handles)"""
        if not self.canvas_root:
            return None
        
        # Temporarily hide all handles before rendering
        handles_visibility = []
        crop_handles_visibility = []
        for layer_id, layer_item in self.layers.items():
            # Hide resize handles
            for handle in layer_item.handles:
                handles_visibility.append((handle, handle.isVisible()))
                handle.setVisible(False)
            # Hide crop handles
            for handle in layer_item.crop_handles:
                crop_handles_visibility.append((handle, handle.isVisible()))
                handle.setVisible(False)
        
        # Also hide the inpaint layer temporarily if it exists
        inpaint_visibility = None
        if self.inpaint_layer:
            inpaint_visibility = self.inpaint_layer.isVisible()
            # Don't hide inpaint layer, it might be intentional to include it
        
        w, h = int(self.canvas_bounds.width()), int(self.canvas_bounds.height())
        pixmap = QPixmap(w, h)
        pixmap.fill(Qt.GlobalColor.white)  # Changed from transparent to white background
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        self.scene.render(painter, 
                         target=QRectF(0, 0, w, h),
                         source=self.canvas_bounds)
        
        painter.end()
        
        # Restore handle visibility
        for handle, was_visible in handles_visibility:
            handle.setVisible(was_visible)
        
        # Restore crop handle visibility
        for handle, was_visible in crop_handles_visibility:
            handle.setVisible(was_visible)
        
        return pixmap

    def enable_inpaint_mode(self, enable: bool):
        """Enable or disable inpaint mode"""
        self.inpaint_mode = enable
        
        if enable and not self.inpaint_layer:
            # Create inpaint layer with canvas size
            self.inpaint_layer = InpaintLayerItem((int(self.canvas_bounds.width()), 
                                                  int(self.canvas_bounds.height())))
            self.inpaint_layer.setParentItem(self.canvas_root)
            self.inpaint_layer.setZValue(9999)
        elif not enable and self.inpaint_layer:
            # Remove inpaint layer
            self.scene.removeItem(self.inpaint_layer)
            self.inpaint_layer = None

    def get_inpaint_mask(self) -> Optional[QPixmap]:
        """Get the current inpaint mask"""
        if not self.inpaint_layer:
            return None
        return self.inpaint_layer.get_mask()
    
    def get_small_inpaint_mask(self) -> Optional[QPixmap]:
        """Get the 1/8 size inpaint mask for NAI API"""
        if not self.inpaint_layer:
            return None
        return self.inpaint_layer.get_small_mask()

    def clear_inpaint_mask(self):
        """Clear the inpaint mask"""
        if self.inpaint_layer:
            self.inpaint_layer.clear_mask()

    def apply_inpaint_result(self, result_pixmap: QPixmap, bbox: tuple):
        """Apply inpaint result to canvas"""
        # Implementation depends on how you want to handle the result
        # This is a placeholder
        pass