"""
Inpaint functionality for Sketchbook module
"""

from PyQt6.QtWidgets import QGraphicsPixmapItem
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPen, QBrush, QColor, QPainter, QPixmap, QCursor, QBitmap
from typing import Optional, Tuple
from enum import Enum
import uuid

class DrawMode(Enum):
    """Drawing modes for inpaint layer"""
    SQUARE_BRUSH = "square_brush"
    CIRCLE_BRUSH = "circle_brush"
    RECTANGLE = "rectangle"
    MOVE = "move"

class InpaintLayerItem(QGraphicsPixmapItem):
    """Layer for drawing inpaint masks with NAI 1/8 grid system"""
    
    def __init__(self, canvas_size: Tuple[int, int]):
        super().__init__()
        self.canvas_w, self.canvas_h = canvas_size
        
        # Layer data for compatibility
        self.layer_data = {
            'id': str(uuid.uuid4()),
            'name': "Inpaint Layer",
            'z_order': 999  # Always on top
        }
        
        # Create transparent pixmap for drawing
        self.mask_pixmap = QPixmap(self.canvas_w, self.canvas_h)
        self.mask_pixmap.fill(Qt.GlobalColor.transparent)
        self.setPixmap(self.mask_pixmap)
        
        # Drawing mode (default to square brush)
        self.draw_mode = DrawMode.SQUARE_BRUSH
        
        # Brush settings
        self.brush_size = 50
        self.brush_color = QColor(255, 0, 0, 128)  # Semi-transparent red
        self.eraser_mode = False
        self.last_paint_pos = None
        
        # Rectangle/Circle drawing
        self.shape_start_pos = None
        self.temp_shape_pixmap = None
        
        # NAI Grid system (8x8 blocks)
        self.grid_width = self.canvas_w // 8
        self.grid_height = self.canvas_h // 8
        self.mask_grid = [[0 for _ in range(self.grid_height)] for _ in range(self.grid_width)]
        
        # Set z-value and mouse handling
        self.setZValue(999)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton)
        
        # Disable default movement in move mode
        self.setFlag(QGraphicsPixmapItem.GraphicsItemFlag.ItemIsMovable, False)
        
        # Enable hover events for cursor updates
        self.setAcceptHoverEvents(True)
        
        # Initialize cursor
        self._update_cursor()
    
    def set_draw_mode(self, mode: DrawMode):
        """Set the drawing mode"""
        self.draw_mode = mode
        
        # Enable/disable movement based on mode
        if mode == DrawMode.MOVE:
            # In move mode, don't handle mouse events (let layers below handle them)
            self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton)
            self._update_cursor()
    
    def set_brush_size(self, size: int):
        """Set brush size (aligned to 8px grid)"""
        self.brush_size = max(8, (size // 8) * 8)
        self._update_cursor()
    
    def adjust_brush_size(self, delta: int):
        """Adjust brush size by delta (for mouse wheel)"""
        new_size = self.brush_size + (delta // 8) * 8
        self.set_brush_size(new_size)
        return self.brush_size
    
    def _update_cursor(self):
        """Update cursor based on current mode and brush size"""
        if self.draw_mode == DrawMode.MOVE:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif self.draw_mode == DrawMode.RECTANGLE:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        elif self.draw_mode in [DrawMode.SQUARE_BRUSH, DrawMode.CIRCLE_BRUSH]:
            # Create custom cursor based on brush size
            cursor_size = min(self.brush_size, 128)  # Limit cursor size for performance
            
            # Create transparent pixmap
            cursor_pixmap = QPixmap(cursor_size + 2, cursor_size + 2)
            cursor_pixmap.fill(Qt.GlobalColor.transparent)
            
            # Draw cursor shape
            painter = QPainter(cursor_pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            
            # Create dashed pattern with alternating black and white
            # First draw black dashed outline
            black_pen = QPen(QColor(0, 0, 0, 255), 2)
            black_pen.setStyle(Qt.PenStyle.DashLine)
            black_pen.setDashPattern([4, 4])  # 4 pixels on, 4 pixels off
            
            # Draw black dashed shape
            painter.setPen(black_pen)
            if self.draw_mode == DrawMode.SQUARE_BRUSH:
                painter.drawRect(1, 1, cursor_size - 2, cursor_size - 2)
            elif self.draw_mode == DrawMode.CIRCLE_BRUSH:
                painter.drawEllipse(1, 1, cursor_size - 2, cursor_size - 2)
            
            # Now draw white dashed outline with offset pattern
            white_pen = QPen(QColor(255, 255, 255, 255), 2)
            white_pen.setStyle(Qt.PenStyle.DashLine)
            white_pen.setDashPattern([4, 4])  # Same pattern
            white_pen.setDashOffset(4)  # Offset by 4 to fill the gaps
            
            # Draw white dashed shape (same coordinates)
            painter.setPen(white_pen)
            if self.draw_mode == DrawMode.SQUARE_BRUSH:
                painter.drawRect(1, 1, cursor_size - 2, cursor_size - 2)
            elif self.draw_mode == DrawMode.CIRCLE_BRUSH:
                painter.drawEllipse(1, 1, cursor_size - 2, cursor_size - 2)
            
            # Add center crosshair for better visibility
            painter.setPen(QPen(QColor(255, 0, 0, 200), 1))  # Red center
            center = cursor_size // 2 + 1
            # Draw small cross
            painter.drawLine(center - 3, center, center + 3, center)
            painter.drawLine(center, center - 3, center, center + 3)
            
            painter.end()
            
            # Create cursor with hotspot at center
            cursor = QCursor(cursor_pixmap, center, center)
            self.setCursor(cursor)
    
    def clear_mask(self):
        """Clear the entire mask"""
        self.mask_grid = [[0 for _ in range(self.grid_height)] for _ in range(self.grid_width)]
        self.update_display()
    
    def mousePressEvent(self, event):
        """Handle mouse press based on current mode"""
        if self.draw_mode == DrawMode.MOVE:
            # In move mode, don't handle events
            event.ignore()
            return
        
        pos = event.pos()
        
        # Right click always means erase
        if event.button() == Qt.MouseButton.RightButton:
            self.eraser_mode = True
        elif event.button() == Qt.MouseButton.LeftButton:
            self.eraser_mode = False
        
        if self.draw_mode in [DrawMode.SQUARE_BRUSH, DrawMode.CIRCLE_BRUSH]:
            self.last_paint_pos = pos
            self.paint_at(pos)
        elif self.draw_mode == DrawMode.RECTANGLE:
            self.shape_start_pos = pos
            # Create temporary pixmap for preview
            self.temp_shape_pixmap = QPixmap(self.canvas_w, self.canvas_h)
            self.temp_shape_pixmap.fill(Qt.GlobalColor.transparent)
        
        event.accept()
    
    def mouseMoveEvent(self, event):
        """Handle mouse move based on current mode"""
        if self.draw_mode == DrawMode.MOVE:
            event.ignore()
            return
        
        if not (event.buttons() & (Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton)):
            return
        
        pos = event.pos()
        
        if self.draw_mode in [DrawMode.SQUARE_BRUSH, DrawMode.CIRCLE_BRUSH]:
            if self.last_paint_pos:
                self.paint_line(self.last_paint_pos, pos)
            self.last_paint_pos = pos
        elif self.draw_mode == DrawMode.RECTANGLE and self.shape_start_pos:
            # Draw preview shape
            self.draw_preview_shape(self.shape_start_pos, pos)
        
        event.accept()
    
    def mouseReleaseEvent(self, event):
        """Handle mouse release"""
        if self.draw_mode == DrawMode.MOVE:
            event.ignore()
            return
        
        if self.draw_mode == DrawMode.RECTANGLE and self.shape_start_pos:
            # Apply the shape to the grid
            pos = event.pos()
            self.apply_shape(self.shape_start_pos, pos)
            self.shape_start_pos = None
            self.temp_shape_pixmap = None
        
        self.last_paint_pos = None
        self.eraser_mode = False
        event.accept()
    
    def hoverEnterEvent(self, event):
        """Update cursor when mouse enters"""
        self._update_cursor()
        super().hoverEnterEvent(event)
    
    def hoverLeaveEvent(self, event):
        """Reset cursor when mouse leaves"""
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().hoverLeaveEvent(event)
    
    def paint_at(self, pos: QPointF):
        """Paint at a specific position (brush mode)"""
        grid_x = int(pos.x()) // 8
        grid_y = int(pos.y()) // 8
        radius = self.brush_size // 16  # Grid radius
        
        for gx in range(max(0, grid_x - radius), min(self.grid_width, grid_x + radius + 1)):
            for gy in range(max(0, grid_y - radius), min(self.grid_height, grid_y + radius + 1)):
                # Check brush shape
                if self.draw_mode == DrawMode.CIRCLE_BRUSH:
                    # Circular brush - check distance
                    dist_sq = (gx - grid_x)**2 + (gy - grid_y)**2
                    if dist_sq > radius**2:
                        continue
                # Square brush - all cells within radius are painted
                
                if self.eraser_mode:
                    self.mask_grid[gx][gy] = 0
                else:
                    # Only paint if not already painted (NAI rule)
                    if self.mask_grid[gx][gy] == 0:
                        self.mask_grid[gx][gy] = 1
        
        self.update_display()
    
    def paint_line(self, start: QPointF, end: QPointF):
        """Paint a line between two points"""
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        distance = (dx**2 + dy**2)**0.5
        steps = max(1, int(distance / 4))
        
        for i in range(steps + 1):
            t = i / steps if steps > 0 else 0
            x = start.x() + dx * t
            y = start.y() + dy * t
            self.paint_at(QPointF(x, y))
    
    def draw_preview_shape(self, start: QPointF, end: QPointF):
        """Draw preview of rectangle or circle"""
        if not self.temp_shape_pixmap:
            return
        
        self.temp_shape_pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self.temp_shape_pixmap)
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        
        preview_color = QColor(255, 0, 0, 64) if not self.eraser_mode else QColor(0, 0, 255, 64)
        painter.setBrush(QBrush(preview_color))
        
        if self.draw_mode == DrawMode.RECTANGLE:
            rect = QRectF(start, end).normalized()
            painter.drawRect(rect)
        
        painter.end()
        
        # Show preview
        combined = self.mask_pixmap.copy()
        painter = QPainter(combined)
        painter.drawPixmap(0, 0, self.temp_shape_pixmap)
        painter.end()
        self.setPixmap(combined)
    
    def apply_shape(self, start: QPointF, end: QPointF):
        """Apply rectangle or circle to the grid"""
        if self.draw_mode == DrawMode.RECTANGLE:
            # Get rectangle bounds in grid coordinates
            x1, x2 = sorted([int(start.x()) // 8, int(end.x()) // 8])
            y1, y2 = sorted([int(start.y()) // 8, int(end.y()) // 8])
            
            x1 = max(0, x1)
            x2 = min(self.grid_width - 1, x2)
            y1 = max(0, y1)
            y2 = min(self.grid_height - 1, y2)
            
            for gx in range(x1, x2 + 1):
                for gy in range(y1, y2 + 1):
                    if self.eraser_mode:
                        self.mask_grid[gx][gy] = 0
                    else:
                        if self.mask_grid[gx][gy] == 0:  # NAI rule
                            self.mask_grid[gx][gy] = 1
        
        
        self.update_display()
    
    def update_display(self):
        """Update visual representation from grid data"""
        self.mask_pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self.mask_pixmap)
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        
        # Draw filled grid cells
        for gx in range(self.grid_width):
            for gy in range(self.grid_height):
                if self.mask_grid[gx][gy] > 0:
                    painter.setBrush(QBrush(self.brush_color))
                    painter.drawRect(gx * 8, gy * 8, 8, 8)
        
        painter.end()
        self.setPixmap(self.mask_pixmap)
    
    def has_mask_content(self) -> bool:
        """Check if the mask has any painted areas"""
        for row in self.mask_grid:
            if any(cell > 0 for cell in row):
                return True
        return False
    
    def get_mask(self) -> QPixmap:
        """Get the binary mask for API"""
        # Return None if mask is empty
        if not self.has_mask_content():
            return None
            
        mask = QPixmap(self.canvas_w, self.canvas_h)
        mask.fill(Qt.GlobalColor.black)
        
        painter = QPainter(mask)
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        painter.setBrush(QBrush(Qt.GlobalColor.white))
        
        # Draw white rectangles for masked areas
        for gx in range(self.grid_width):
            for gy in range(self.grid_height):
                if self.mask_grid[gx][gy] > 0:
                    painter.drawRect(gx * 8, gy * 8, 8, 8)
        
        painter.end()
        return mask
    
    def get_small_mask(self) -> QPixmap:
        """Get the 1/8 size mask for NAI API"""
        # Return None if mask is empty
        if not self.has_mask_content():
            return None
            
        mask = QPixmap(self.grid_width, self.grid_height)
        mask.fill(Qt.GlobalColor.black)
        
        painter = QPainter(mask)
        painter.setPen(QPen(Qt.GlobalColor.white, 1))
        painter.setBrush(QBrush(Qt.GlobalColor.white))
        
        for gx in range(self.grid_width):
            for gy in range(self.grid_height):
                if self.mask_grid[gx][gy] > 0:
                    painter.drawPoint(gx, gy)
        
        painter.end()
        return mask