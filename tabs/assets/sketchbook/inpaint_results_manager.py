"""
Unified inpaint results display window with grid layout
"""

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                            QLabel, QScrollArea, QWidget, QApplication, QFrame,
                            QGridLayout, QMessageBox, QSpacerItem, QSizePolicy)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QImage, QResizeEvent
from PIL import Image
from ui.theme import get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
import tempfile
import os
import io

class InpaintResultFrame(QFrame):
    """Individual result frame within the grid"""
    
    # Signals
    add_to_canvas = pyqtSignal(str, tuple)  # image_path, bbox
    frame_closed = pyqtSignal(QFrame)  # Signal when frame is closed
    retry_requested = pyqtSignal(QFrame)  # Signal for retry
    
    def __init__(self, result_img: Image.Image, bbox: tuple, index: int, 
                 generation_params: dict = None, server_original: Image.Image = None, parent=None):
        super().__init__(parent)
        self.result_img = result_img  # Combined image for display
        self.server_original = server_original or result_img  # Server original image for save/copy
        self.bbox = bbox
        self.index = index
        
        # Debug: Check bbox type
        if not isinstance(bbox, tuple):
            print(f"⚠️ Warning: bbox is not a tuple, it's {type(bbox)}: {bbox}")
            # Try to handle if bbox is accidentally an image
            if hasattr(bbox, 'size'):  # PIL Image
                print(f"⚠️ bbox appears to be an image, using default bbox")
                self.bbox = (0, 0, 100, 100)  # Default bbox
        self.temp_file = None
        self.original_pixmap = None
        self.generation_params = generation_params or {}  # Store generation parameters
        
        self.setFrameStyle(QFrame.Shape.Box)
        self.setLineWidth(1)
        
        # Set frame size to fit 2 columns in 1350px window
        self.setMaximumSize(640, 750)
        self.setMinimumSize(620, 730)
        
        # Dark background
        self.setStyleSheet("""
            QFrame {
                background-color: #2b2b2b;
                border: 1px solid #404040;
                border-radius: 5px;
            }
            QLabel {
                color: #e0e0e0;
            }
        """)
        
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the frame UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Title bar with close button
        title_layout = QHBoxLayout()
        self.title_label = QLabel(f"결과 #{self.index + 1}")  # Store as instance variable
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        title_layout.addWidget(self.title_label)
        
        title_layout.addStretch()
        
        # Close button for this frame
        close_btn = QPushButton("X")
        close_btn.setFixedSize(25, 25)
        close_btn.clicked.connect(self.close_frame)
        title_layout.addWidget(close_btn)
        
        layout.addLayout(title_layout)
        
        # Image display
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setFixedSize(600, 600)
        self.image_label.setScaledContents(False)
        self.image_label.setStyleSheet("""
            QLabel {
                background-color: #1e1e1e;
                border: 1px solid #505050;
                border-radius: 3px;
            }
        """)
        
        # Cache and display image
        self.cache_original_pixmap()
        self.update_display()
        
        layout.addWidget(self.image_label, 1)
        
        # Button row
        button_layout = QHBoxLayout()
        button_layout.setSpacing(5)
        
        # Add to canvas button
        add_btn = QPushButton("➕ 캔버스")
        add_btn.setFixedSize(145, 40)
        add_btn.clicked.connect(self.add_to_canvas_clicked)
        button_layout.addWidget(add_btn)
        
        # Copy button
        copy_btn = QPushButton("📋 복사")
        copy_btn.setFixedSize(145, 40)
        copy_btn.clicked.connect(self.copy_to_clipboard)
        button_layout.addWidget(copy_btn)
        
        # Save button
        save_btn = QPushButton("💾 저장")
        save_btn.setFixedSize(145, 40)
        save_btn.clicked.connect(self.save_result)
        button_layout.addWidget(save_btn)
        
        # Retry button
        self.retry_btn = QPushButton("🔄 재시도")  # Store as instance variable for state updates
        self.retry_btn.setFixedSize(145, 40)
        self.retry_btn.clicked.connect(self.retry_generation)
        button_layout.addWidget(self.retry_btn)
        
        layout.addLayout(button_layout)
        
        # Apply styling with dark theme
        button_style = """
            QPushButton {
                background-color: #404040;
                color: #e0e0e0;
                border: 1px solid #505050;
                border-radius: 3px;
                padding: 4px 8px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #505050;
                border: 1px solid #606060;
            }
            QPushButton:pressed {
                background-color: #353535;
            }
        """
        
        add_btn.setStyleSheet(button_style)
        copy_btn.setStyleSheet(button_style)
        save_btn.setStyleSheet(button_style)
        self.retry_btn.setStyleSheet(button_style)
        
        # Special style for close button with visible white text
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #703030;
                color: #ffffff;
                border: 1px solid #804040;
                border-radius: 3px;
                font-weight: bold;
                font-size: 18px;
                text-align: center;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: #904040;
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: #502020;
            }
        """)
        
    def cache_original_pixmap(self):
        """Convert PIL image to QPixmap and cache it"""
        if self.result_img.mode == "RGBA":
            qformat = QImage.Format.Format_RGBA8888
        elif self.result_img.mode == "RGB":
            qformat = QImage.Format.Format_RGB888
        else:
            temp_img = self.result_img.convert("RGB")
            qformat = QImage.Format.Format_RGB888
            img_data = temp_img.tobytes("raw", temp_img.mode)
            qimage = QImage(img_data, temp_img.width, temp_img.height, qformat)
        
        if self.result_img.mode in ["RGBA", "RGB"]:
            img_data = self.result_img.tobytes("raw", self.result_img.mode)
            qimage = QImage(img_data, self.result_img.width, self.result_img.height, qformat)
        
        self.original_pixmap = QPixmap.fromImage(qimage)
    
    def update_display(self):
        """Update the displayed image to fit the label"""
        if not self.original_pixmap:
            return
        
        # Get available size
        available_size = self.image_label.size()
        
        # Scale pixmap to fit
        scaled_pixmap = self.original_pixmap.scaled(
            available_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        
        self.image_label.setPixmap(scaled_pixmap)
    
    def add_to_canvas_clicked(self):
        """Handle add to canvas button click"""
        # Save to temporary file if not already saved
        if not self.temp_file:
            temp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            self.result_img.save(temp.name, 'PNG')
            self.temp_file = temp.name
            temp.close()
        
        # Ensure bbox is a tuple before emitting
        if not isinstance(self.bbox, tuple):
            print(f"⚠️ bbox is not a tuple: {type(self.bbox)}, using default")
            bbox_to_emit = (0, 0, 100, 100)
        else:
            bbox_to_emit = self.bbox
        
        # Emit signal with image path and bbox
        self.add_to_canvas.emit(self.temp_file, bbox_to_emit)
        print(f"✅ Result #{self.index + 1} added to canvas")
    
    def copy_to_clipboard(self):
        """Copy the server original image to clipboard"""
        try:
            # Convert server original PIL image to QPixmap for clipboard
            # First save to bytes
            buffer = io.BytesIO()
            self.server_original.save(buffer, format='PNG')
            buffer.seek(0)
            
            # Load as QPixmap
            pixmap = QPixmap()
            pixmap.loadFromData(buffer.getvalue())
            
            clipboard = QApplication.clipboard()
            clipboard.setPixmap(pixmap)
            print(f"✅ Server original image #{self.index + 1} copied to clipboard")
            QMessageBox.information(self, "복사 완료", "원본 이미지가 클립보드에 복사되었습니다.")
        except Exception as e:
            QMessageBox.critical(self, "복사 실패", f"클립보드 복사 중 오류:\n{str(e)}")
    
    def save_result(self):
        """Save the server original image"""
        from PyQt6.QtWidgets import QFileDialog
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "이미지 저장", f"inpaint_result_{self.index + 1}.png", 
            "PNG Files (*.png);;JPEG Files (*.jpg *.jpeg);;All Files (*.*)"
        )
        
        if file_path:
            try:
                # Save server original instead of combined result
                self.server_original.save(file_path)
                print(f"✅ Server original image saved to: {file_path}")
                QMessageBox.information(self, "저장 완료", f"원본 이미지가 저장되었습니다:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "저장 실패", f"이미지 저장 중 오류:\n{str(e)}")
    
    def retry_generation(self):
        """Request retry of generation with same parameters"""
        print(f"🔄 Retry requested for frame #{self.index + 1}")
        # Update button state
        self.set_retry_state(True)
        # Emit signal to trigger retry
        self.retry_requested.emit(self)
    
    def set_retry_state(self, is_retrying: bool):
        """Update retry button state"""
        if is_retrying:
            self.retry_btn.setText("⏳ 생성중...")
            self.retry_btn.setEnabled(False)
        else:
            self.retry_btn.setText("🔄 재시도")
            self.retry_btn.setEnabled(True)
    
    def update_result(self, new_img: Image.Image, new_server_original: Image.Image = None):
        """Update this frame with new result"""
        self.result_img = new_img
        if new_server_original:
            self.server_original = new_server_original
        else:
            self.server_original = new_img  # Fallback to combined if no original provided
        
        # Clean up old temp file
        if self.temp_file and os.path.exists(self.temp_file):
            try:
                os.remove(self.temp_file)
                self.temp_file = None
            except:
                pass
        
        # Update display
        self.cache_original_pixmap()
        self.update_display()
        
        # Reset retry button state
        self.set_retry_state(False)
        
        print(f"✅ Frame #{self.index + 1} updated with new result")
    
    def close_frame(self):
        """Close this frame"""
        print(f"🗑️ Closing frame #{self.index + 1}")
        
        # Clean up temp file
        if self.temp_file and os.path.exists(self.temp_file):
            try:
                os.remove(self.temp_file)
                print(f"🗑️ Cleaned up temp file for frame #{self.index + 1}")
            except:
                pass
        
        # Emit signal to trigger reorganization
        self.frame_closed.emit(self)
        self.hide()
    
    def cleanup(self):
        """Clean up resources"""
        if self.temp_file and os.path.exists(self.temp_file):
            try:
                os.remove(self.temp_file)
                print(f"🗑️ Cleaned up temp file for result #{self.index + 1}")
            except:
                pass


class InpaintResultsManager(QDialog):
    """Unified window for managing all inpaint results"""
    
    # Signal when user adds result to canvas
    result_added = pyqtSignal(str, tuple)  # image_path, bbox
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.result_frames = []
        self.result_count = 0
        self.grid_columns = 2  # 2 columns per row
        self.sketchbook_widget = parent  # Store reference to SketchbookWidget
        
        self.setWindowTitle("인페인트 결과")
        self.setWindowFlags(Qt.WindowType.Window)
        
        # Fixed window size (1.5x larger)
        self.setFixedSize(1350, 1050)
        
        # Dark theme for main window
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e1e;
            }
            QScrollArea {
                background-color: #252525;
                border: none;
            }
            QWidget {
                background-color: #252525;
            }
        """)
        
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the main UI"""
        main_layout = QVBoxLayout(self)
        
        # Create scroll area for results
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        # Container widget for grid
        self.container = QWidget()
        self.grid_layout = QGridLayout(self.container)
        self.grid_layout.setSpacing(10)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        scroll.setWidget(self.container)
        main_layout.addWidget(scroll)
        
        # Bottom button bar
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        # Save all button
        save_all_btn = QPushButton("💾 일괄 저장")
        save_all_btn.clicked.connect(self.save_all_results)
        button_layout.addWidget(save_all_btn)
        
        # Close all button
        close_all_btn = QPushButton("🚪 모두 닫기")
        close_all_btn.clicked.connect(self.close_all_frames)
        button_layout.addWidget(close_all_btn)
        
        main_layout.addLayout(button_layout)
        
        # Apply styling with dark theme
        button_style = """
            QPushButton {
                background-color: #404040;
                color: #e0e0e0;
                border: 1px solid #505050;
                border-radius: 3px;
                padding: 6px 12px;
                font-size: 15px;
            }
            QPushButton:hover {
                background-color: #505050;
                border: 1px solid #606060;
            }
            QPushButton:pressed {
                background-color: #353535;
            }
        """
        save_all_btn.setStyleSheet(button_style)
        close_all_btn.setStyleSheet(button_style)
        
    def add_result(self, result_img: Image.Image, bbox: tuple, generation_params: dict = None, 
                   server_original: Image.Image = None):
        """Add a new result to the grid with generation parameters and server original"""
        # Debug: Verify parameter types
        print(f"InpaintResultsManager.add_result called with:")
        print(f"  - result_img: {type(result_img)}")
        print(f"  - bbox: {type(bbox)} = {bbox}")
        print(f"  - generation_params: {type(generation_params)}")
        print(f"  - server_original: {type(server_original)}")
        
        # Create new frame with correct index based on current frame count
        frame_index = len(self.result_frames)  # Use actual count, not cumulative
        frame = InpaintResultFrame(result_img, bbox, frame_index, generation_params, server_original, self)
        frame.add_to_canvas.connect(self._on_add_to_canvas)
        frame.frame_closed.connect(self._on_frame_closed)
        frame.retry_requested.connect(self._on_retry_requested)
        
        # Add to frames list
        self.result_frames.append(frame)
        self.result_count += 1
        
        # Reorganize grid to ensure proper placement
        self._reorganize_grid()
        
        print(f"✅ Added result (total: {len(self.result_frames)} frames)")
        
        # Show window if hidden
        if not self.isVisible():
            self.show()
        
        # Bring to front
        self.raise_()
        self.activateWindow()
    
    def _on_add_to_canvas(self, image_path: str, bbox: tuple):
        """Forward add to canvas signal and clear mask"""
        self.result_added.emit(image_path, bbox)
        
        # Clear inpaint mask after adding to canvas
        if self.sketchbook_widget and hasattr(self.sketchbook_widget, 'canvas'):
            canvas = self.sketchbook_widget.canvas
            if hasattr(canvas, 'inpaint_layer') and canvas.inpaint_layer:
                canvas.inpaint_layer.clear_mask()
                print(f"🧹 Cleared inpaint mask after adding to canvas")
    
    def _on_retry_requested(self, frame: InpaintResultFrame):
        """Handle retry request for a frame"""
        print(f"🔄 Processing retry for frame #{frame.index + 1}")
        
        if not self.sketchbook_widget or not frame.generation_params:
            QMessageBox.warning(self, "재시도 불가", "생성 파라미터가 없습니다.")
            return
        
        # Trigger generation with stored parameters
        # This will be handled by sketchbook_widget
        if hasattr(self.sketchbook_widget, 'retry_inpaint_generation'):
            self.sketchbook_widget.retry_inpaint_generation(frame)
        else:
            QMessageBox.warning(self, "재시도 불가", "재시도 기능을 사용할 수 없습니다.")
    
    def _on_frame_closed(self, frame: InpaintResultFrame):
        """Handle frame close"""
        # Remove from list
        if frame in self.result_frames:
            self.result_frames.remove(frame)
            print(f"🗑️ Removed frame #{frame.index + 1}, {len(self.result_frames)} frames remaining")
            
        # Remove from grid
        self.grid_layout.removeWidget(frame)
        frame.deleteLater()
        
        # Reorganize grid to fill empty spaces
        self._reorganize_grid()
    
    def _reorganize_grid(self):
        """Reorganize grid after a frame is removed"""
        # Clear all items from grid layout
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item:
                widget = item.widget()
                if widget and widget in self.result_frames:
                    # Don't delete, just remove from layout
                    pass
        
        # Re-add all remaining frames in order
        for i, frame in enumerate(self.result_frames):
            row = i // self.grid_columns
            col = i % self.grid_columns
            self.grid_layout.addWidget(frame, row, col)
            frame.index = i  # Update index
            frame.show()  # Ensure frame is visible
            
            # Update frame title
            if hasattr(frame, 'title_label'):
                frame.title_label.setText(f"결과 #{i + 1}")
        
        print(f"🔄 Grid reorganized: {len(self.result_frames)} frames in {(len(self.result_frames) + 1) // 2} rows")
    
    def save_all_results(self):
        """Save all results to a selected folder"""
        if not self.result_frames:
            QMessageBox.warning(self, "경고", "저장할 결과가 없습니다.")
            return
        
        from PyQt6.QtWidgets import QFileDialog
        import datetime
        
        # Select folder
        folder_path = QFileDialog.getExistingDirectory(
            self, 
            "일괄 저장할 폴더 선택",
            "",
            QFileDialog.Option.ShowDirsOnly
        )
        
        if not folder_path:
            return
        
        # Save all images
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        saved_count = 0
        failed_count = 0
        
        for i, frame in enumerate(self.result_frames):
            try:
                # Generate filename
                filename = f"inpaint_{timestamp}_{i+1:03d}.png"
                file_path = os.path.join(folder_path, filename)
                
                # Save server original image
                frame.server_original.save(file_path)
                saved_count += 1
                print(f"✅ Saved server original: {filename}")
                
            except Exception as e:
                failed_count += 1
                print(f"❌ Failed to save result #{i+1}: {e}")
        
        # Show result message
        if failed_count == 0:
            QMessageBox.information(
                self, 
                "일괄 저장 완료", 
                f"{saved_count}개의 이미지가 성공적으로 저장되었습니다.\n\n폴더: {folder_path}"
            )
        else:
            QMessageBox.warning(
                self,
                "일괄 저장 부분 실패",
                f"성공: {saved_count}개\n실패: {failed_count}개\n\n폴더: {folder_path}"
            )
    
    def close_all_frames(self):
        """Close all frames individually before closing the window"""
        # Close each frame individually (triggers cleanup)
        frames_to_close = self.result_frames.copy()
        for frame in frames_to_close:
            frame.close_frame()
        
        # Clear the list
        self.result_frames.clear()
        
        # Now close the window
        self.close()
        print("🚪 All frames closed and window closed")
    
    def closeEvent(self, event):
        """Handle window close - clean up all frames"""
        # Close each frame individually (same as "모두 닫기" but without recursive close)
        frames_to_close = self.result_frames.copy()
        for frame in frames_to_close:
            frame.close_frame()
        
        # Clear the list
        self.result_frames.clear()
        
        event.accept()
        print("🚪 Inpaint results manager closed")