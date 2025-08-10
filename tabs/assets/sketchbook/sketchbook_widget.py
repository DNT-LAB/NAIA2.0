"""
Main widget for Sketchbook module - integrates all components
"""

import os
import tempfile
import datetime
from typing import Optional, List, Tuple
from dataclasses import dataclass

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                            QComboBox, QLabel, QFileDialog, QMessageBox,
                            QSplitter, QProgressDialog, QApplication)
from PyQt6.QtCore import Qt, QPointF, pyqtSignal, QThread
from PyQt6.QtGui import QPixmap, QClipboard

from PIL import Image

from .sketchbook_types import LayerData, CANVAS_SIZES
from .sketchbook_canvas import SketchbookCanvas
from .sketchbook_panel import LayerPanel

from ui.theme import get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

class SketchbookWidget(QWidget):
    """Main sketchbook widget that integrates canvas and controls"""
    
    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        
        # Inpaint mode state
        self.inpaint_mode = False
        self.inpaint_control_window = None
        self.stored_main_prompt = ""
        self.stored_negative_prompt = ""
        self.inpaint_worker = None
        self.progress_dialog = None
        self.pending_result = None
        self.pending_bbox = None
        
        # Undo/Redo stacks
        self.undo_stack = []
        self.redo_stack = []
        
        self.setup_ui()
        self.connect_signals()

    def setup_ui(self):
        """Initialize the UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Top toolbar
        toolbar = self.create_toolbar()
        layout.addWidget(toolbar)
        
        # Main content area with canvas and layer panel
        content_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Canvas
        self.canvas = SketchbookCanvas(self)
        content_splitter.addWidget(self.canvas)
        
        # Layer panel
        self.layer_panel = LayerPanel(self)
        self.layer_panel.setMaximumWidth(get_scaled_size(250))
        content_splitter.addWidget(self.layer_panel)
        
        # Set initial splitter sizes (70% canvas, 30% panel)
        content_splitter.setSizes([700, 300])
        
        layout.addWidget(content_splitter)
        
        # Apply styling
        self.apply_styling()

    def create_toolbar(self) -> QWidget:
        """Create the toolbar with controls"""
        toolbar = QWidget()
        toolbar.setMaximumHeight(get_scaled_size(50))
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Add Image button
        self.add_button = QPushButton("➕ 이미지 추가")
        self.add_button.clicked.connect(self.add_image)
        layout.addWidget(self.add_button)
        
        # Canvas size selector
        layout.addWidget(QLabel("캔버스:"))
        self.canvas_combo = QComboBox()
        self.canvas_combo.addItems(CANVAS_SIZES.keys())
        self.canvas_combo.setCurrentText("1024×1024 (1:1)")
        self.canvas_combo.currentTextChanged.connect(self.on_canvas_size_changed)
        layout.addWidget(self.canvas_combo)
        
        # Export button
        self.export_button = QPushButton("💾 내보내기")
        self.export_button.clicked.connect(self.export_image)
        layout.addWidget(self.export_button)
        
        # Inpaint button
        self.inpaint_button = QPushButton("🎨 인페인트")
        self.inpaint_button.setCheckable(True)
        self.inpaint_button.toggled.connect(self._on_inpaint_mode_toggled)
        layout.addWidget(self.inpaint_button)
        
        layout.addStretch()
        
        # Clear button
        self.clear_button = QPushButton("🗑️ 전체 삭제")
        self.clear_button.clicked.connect(self.clear_canvas)
        layout.addWidget(self.clear_button)
        
        return toolbar

    def apply_styling(self):
        """Apply consistent styling"""
        ds = get_dynamic_styles()
        
        # Style buttons
        for button in [self.add_button, self.export_button, self.clear_button]:
            button.setStyleSheet(ds.get('secondary_button', ''))
        
        self.inpaint_button.setStyleSheet(ds.get('primary_button', ''))
        
        # Style combo box
        self.canvas_combo.setStyleSheet(ds.get('compact_combobox', ''))

    def connect_signals(self):
        """Connect all signals between components"""
        # Canvas <-> Panel synchronization
        self.canvas.layer_selected.connect(self._on_canvas_layer_selected)
        self.canvas.layer_moved.connect(self.record_layer_move)
        self.canvas.layer_scaled.connect(self.record_layer_scale)
        
        self.layer_panel.layer_selected.connect(self._on_panel_layer_selected)
        self.layer_panel.layer_visibility_changed.connect(self.canvas.update_layer_visibility)
        self.layer_panel.layer_order_changed.connect(self.canvas.update_layer_order)
        self.layer_panel.layer_delete_requested.connect(self._on_delete_layer)
        self.layer_panel.layer_center_requested.connect(self.center_layer)

    # --- Event Handlers ---
    
    def _on_canvas_layer_selected(self, layer_id: str):
        """Handle layer selection from canvas"""
        self.layer_panel.select_layer(layer_id)
        self.canvas.select_layer(layer_id)

    def _on_panel_layer_selected(self, layer_id: str):
        """Handle layer selection from panel"""
        self.canvas.select_layer(layer_id)

    def _on_delete_layer(self, layer_id: str):
        """Handle layer deletion request"""
        # Store layer data for undo
        if layer_id in self.canvas.layers:
            layer_item = self.canvas.layers[layer_id]
            layer_data = layer_item.layer_data
            self.undo_stack.append(('delete_layer', layer_data))
            self.redo_stack.clear()
        
        # Remove from both canvas and panel
        self.canvas.remove_layer(layer_id)
        self.layer_panel.remove_layer(layer_id)

    def on_canvas_size_changed(self, size_text: str):
        """Handle canvas size change"""
        if size_text in CANVAS_SIZES:
            new_size = CANVAS_SIZES[size_text]
            self.canvas.setup_canvas(new_size)

    def _on_inpaint_mode_toggled(self, checked: bool):
        """Handle inpaint mode toggle"""
        self.inpaint_mode = checked
        
        if checked:
            # Disable resolution combo while in inpaint mode
            self.canvas_combo.setEnabled(False)
            self.canvas_combo.setToolTip("인페인트 모드에서는 해상도 변경이 불가능합니다")
            
            # Enable inpaint mode in canvas
            self.canvas.enable_inpaint_mode(True)
            
            # Show inpaint control window
            self._show_inpaint_controls()
        else:
            # Re-enable resolution combo
            self.canvas_combo.setEnabled(True)
            self.canvas_combo.setToolTip("")
            
            # Disable inpaint mode and remove mask layer
            self.canvas.enable_inpaint_mode(False)
            
            # Hide control window if exists
            if self.inpaint_control_window:
                self.inpaint_control_window.close()
                self.inpaint_control_window = None

    def _show_inpaint_controls(self):
        """Show inpaint control window"""
        # Import here to avoid circular imports
        from .sketchbook_inpaint_control import InpaintControlWindow
        
        if not self.inpaint_control_window:
            self.inpaint_control_window = InpaintControlWindow(self)
            
            # Connect result signals
            self.inpaint_control_window.result_accepted.connect(self._on_inpaint_result_accepted)
            self.inpaint_control_window.result_cancelled.connect(self._on_inpaint_result_cancelled)
            
            # Set stored prompts if available
            if self.stored_main_prompt or self.stored_negative_prompt:
                self.inpaint_control_window.set_prompts(
                    self.stored_main_prompt, 
                    self.stored_negative_prompt
                )
        
        self.inpaint_control_window.show()
    
    def update_brush_size_display(self, size: int):
        """Update brush size display in control window"""
        if self.inpaint_control_window:
            self.inpaint_control_window.update_brush_size(size)
    
    def generate_inpaint(self, main_prompt: str, negative_prompt: str, strength: float):
        """Generate inpaint image using API"""
        # Get mask from canvas
        if not self.canvas.inpaint_layer:
            # QMessageBox.warning(self, "오류", "인페인트 레이어가 없습니다.")
            print("⚠️ No inpaint layer found")
            return
        
        # Get both full and small mask
        mask = self.canvas.get_inpaint_mask()
        small_mask = self.canvas.get_small_inpaint_mask()
        
        if not mask:
            # Issue [3]: If no mask exists, show the control window again
            # QMessageBox.warning(self, "오류", "마스크가 비어있습니다. 인페인트 영역을 그려주세요.")
            print("⚠️ Mask is empty - please draw inpaint area")
            if self.inpaint_control_window:
                self.inpaint_control_window.show()
                # Flash or highlight to draw attention
                self.inpaint_control_window.activateWindow()
                self.inpaint_control_window.raise_()
            return
        
        # Get active character prompts from sketchbook layers
        character_prompts = self.get_active_character_prompts()
        if character_prompts:
            print(f"📝 Found {len(character_prompts)} active character prompts")
        
        # Temporarily hide inpaint layer for composite generation
        if self.canvas.inpaint_layer:
            self.canvas.inpaint_layer.setVisible(False)
        
        # Get composite image without inpaint layer
        composite = self.canvas.export_composite()
        if not composite:
            # QMessageBox.warning(self, "오류", "캔버스가 비어있습니다.")
            print("⚠️ Canvas is empty")
            if self.canvas.inpaint_layer:
                self.canvas.inpaint_layer.setVisible(True)
            return
        
        # Restore inpaint layer visibility
        if self.canvas.inpaint_layer:
            self.canvas.inpaint_layer.setVisible(True)
        
        # Convert QPixmap to PIL Image
        composite_img = self._qpixmap_to_pil(composite)
        mask_img = self._qpixmap_to_pil(mask)
        small_mask_img = self._qpixmap_to_pil(small_mask) if small_mask else None
        
        # Show progress dialog
        self.progress_dialog = QProgressDialog("인페인트 이미지 생성 중...", "취소", 0, 0, self)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setCancelButton(None)
        self.progress_dialog.show()
        
        # Hide inpaint control window during generation
        if self.inpaint_control_window:
            self.inpaint_control_window.hide()
        
        # Import and create worker thread
        from .sketchbook_inpaint_worker import InpaintGenerationWorker
        
        self.inpaint_worker = InpaintGenerationWorker(
            self.app_context, composite_img, mask_img, 
            main_prompt, negative_prompt, strength, small_mask_img,
            character_prompts  # Pass character prompts to worker
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
        print(f"   Strength: {strength}")
    
    def _qpixmap_to_pil(self, pixmap: QPixmap) -> Image:
        """Convert QPixmap to PIL Image"""
        import tempfile
        import os
        from PIL import Image
        
        # Save to temp file and load as PIL
        tmp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        tmp_filename = tmp_file.name
        tmp_file.close()
        
        pixmap.save(tmp_filename, 'PNG')
        img = Image.open(tmp_filename)
        img_copy = img.convert('RGBA').copy()
        img.close()
        
        # Try to delete temp file
        try:
            os.unlink(tmp_filename)
        except:
            pass
        
        return img_copy
    
    def _on_inpaint_progress_update(self, message: str):
        """Update progress dialog with status message"""
        if self.progress_dialog:
            self.progress_dialog.setLabelText(message)
    
    def _on_inpaint_generation_error(self, error_msg: str):
        """Handle generation error"""
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
        
        # QMessageBox.critical(self, "생성 오류", f"인페인트 생성 실패:\n{error_msg}")
        print(f"❌ Inpaint generation error: {error_msg}")
        
        # Clean up worker
        if self.inpaint_worker:
            self.inpaint_worker.deleteLater()
            self.inpaint_worker = None
    
    def _on_inpaint_generation_finished(self, result_img: Image, bbox: tuple):
        """Handle successful generation - add as temporary result layer"""
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
        
        # Store pending result
        self.pending_result = result_img
        self.pending_bbox = bbox
        
        # Issue [1]: Don't clear mask immediately - save it for potential cancellation
        # Store the mask state before clearing
        if self.canvas.inpaint_layer:
            self.stored_mask_grid = [row[:] for row in self.canvas.inpaint_layer.mask_grid]
            self.canvas.clear_inpaint_mask()
        
        # Create temporary result layer
        try:
            import tempfile
            import datetime
            
            temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            result_img.save(temp_file.name, 'PNG')
            temp_path = temp_file.name
            temp_file.close()
            
            # Position based on bounding box
            x_pos = bbox[0] if bbox else 0
            y_pos = bbox[1] if bbox else 0
            
            timestamp = datetime.datetime.now().strftime("%H%M%S")
            
            from .sketchbook_types import LayerData
            temp_data = LayerData(
                name=f"TempResult_{timestamp}",
                image_path=temp_path,
                position=(float(x_pos), float(y_pos)),
                z_order=self.canvas.get_max_z_order() + 1,
            )
            
            # Add temporary result layer (visible and deletable)
            self.preview_layer_id = self.canvas.add_layer(temp_data)
            self.layer_panel.add_layer(temp_data)
            
            # Show accept/cancel buttons
            if self.inpaint_control_window:
                self.inpaint_control_window.show()
                self.inpaint_control_window.show_result_buttons(True)
            
            print(f"✅ Temporary result layer added at position ({x_pos}, {y_pos})")
            # Issue [2]: Don't show completion message
            # QMessageBox.information(self, "인페인트 완료", 
            #                        "임시 결과가 생성되었습니다.\n승인하면 정식 레이어로, 취소하면 삭제됩니다.") - image is already visible
            
        except Exception as e:
            # QMessageBox.critical(self, "오류", f"결과 생성 중 오류:\n{str(e)}")
            print(f"❌ Error creating result: {e}")
        
        # Clean up worker
        if self.inpaint_worker:
            self.inpaint_worker.deleteLater()
            self.inpaint_worker = None
    
    def _add_image_at_position(self, image_path: str, layer_name: str, x: float, y: float) -> Optional[str]:
        """Add an image as a new layer at specific position"""
        if not os.path.exists(image_path):
            return None
        
        # Get the highest Z-order and add 1 for the new layer
        max_z = self.canvas.get_max_z_order()
        
        layer_data = LayerData(
            name=layer_name,
            image_path=image_path,
            position=(x, y),  # Use provided position
            z_order=max_z + 1,
        )
        
        layer_id = self.canvas.add_layer(layer_data)
        self.layer_panel.add_layer(layer_data)
        
        # Record for undo/redo
        self.undo_stack.append(('add_layer', layer_data))
        self.redo_stack.clear()
        
        return layer_id
    
    def _on_inpaint_result_accepted(self):
        """User accepted the result - rename temp layer to final"""
        if not hasattr(self, 'preview_layer_id'):
            return
        
        # Rename temporary layer to final name
        if self.preview_layer_id in self.canvas.layers:
            layer_item = self.canvas.layers[self.preview_layer_id]
            import datetime
            timestamp = datetime.datetime.now().strftime("%H%M%S")
            layer_item.layer_data.name = f"Inpaint_{timestamp}"
            
            # Update in layer panel
            self.layer_panel.update_layer_name(self.preview_layer_id, layer_item.layer_data.name)
            
            print(f"✅ Inpaint result accepted: {layer_item.layer_data.name}")
            # Issue [2]: Don't show completion message
            # QMessageBox.information(self, "완료", "인페인트 결과가 승인되었습니다.")
        
        # Clear pending and stored mask
        self.pending_result = None
        self.pending_bbox = None
        if hasattr(self, 'stored_mask_grid'):
            delattr(self, 'stored_mask_grid')
        delattr(self, 'preview_layer_id')
    
    def _on_inpaint_result_cancelled(self):
        """User cancelled the result - remove temp layer and restore mask"""
        # Remove preview layer
        if hasattr(self, 'preview_layer_id'):
            if self.preview_layer_id in self.canvas.layers:
                self.canvas.remove_layer(self.preview_layer_id)
                self.layer_panel.remove_layer(self.preview_layer_id)
            delattr(self, 'preview_layer_id')
        
        # Issue [1]: Restore the mask when user cancels
        if hasattr(self, 'stored_mask_grid') and self.canvas.inpaint_layer:
            self.canvas.inpaint_layer.mask_grid = [row[:] for row in self.stored_mask_grid]
            self.canvas.inpaint_layer.update_display()
            delattr(self, 'stored_mask_grid')
        
        # Clear pending
        self.pending_result = None
        self.pending_bbox = None
        
        print("❌ Inpaint result cancelled - temporary layer removed and mask restored")
        # QMessageBox.information(self, "취소", "인페인트 결과가 취소되었습니다.")

    # --- Layer Management ---
    
    def add_image(self):
        """Add an image from file dialog"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "이미지 선택", "", 
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        
        if file_path:
            layer_name = os.path.basename(file_path)
            self.add_image_from_path(file_path, layer_name)

    def add_image_from_path(self, image_path: str, layer_name: Optional[str] = None) -> Optional[str]:
        """Add an image as a new layer"""
        if not os.path.exists(image_path):
            # QMessageBox.warning(self, "오류", f"이미지 파일을 찾을 수 없습니다: {image_path}")
            print(f"⚠️ Image file not found: {image_path}")
            return None
            
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
        
        # Record for undo/redo
        self.undo_stack.append(('add_layer', layer_data))
        self.redo_stack.clear()
        
        print(f"✅ Added layer: {layer_name} (ID: {layer_id}, Z: {layer_data.z_order})")
        return layer_id
    
    def add_image_from_path_with_prompt(self, image_path: str, layer_name: Optional[str] = None, 
                                        character_prompt: Optional[dict] = None) -> Optional[str]:
        """Add an image as a new layer with character prompt data"""
        if not os.path.exists(image_path):
            print(f"⚠️ Image file not found: {image_path}")
            return None
            
        if not layer_name:
            layer_name = os.path.basename(image_path)
        
        # Get the highest Z-order and add 1 for the new layer
        max_z = self.canvas.get_max_z_order()
        
        layer_data = LayerData(
            name=layer_name,
            image_path=image_path,
            position=(100.0, 100.0),
            z_order=max_z + 1,
            character_prompt=character_prompt,
            prompt_activated=True if character_prompt else False
        )
        
        layer_id = self.canvas.add_layer(layer_data)
        self.layer_panel.add_layer(layer_data)
        
        # Record for undo/redo
        self.undo_stack.append(('add_layer', layer_data))
        self.redo_stack.clear()
        
        print(f"✅ Added layer: {layer_name} (ID: {layer_id}, Z: {layer_data.z_order})")
        if character_prompt:
            print(f"   📝 With character prompt")
        return layer_id

    def clear_canvas(self):
        """Clear all layers"""
        # Since we can't use QMessageBox with topmost window, always confirm deletion
        # reply = QMessageBox.question(
        #     self, "확인", "모든 레이어를 삭제하시겠습니까?",
        #     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        # )
        # if reply == QMessageBox.StandardButton.Yes:
        
        # Just proceed with clearing (user can undo with Ctrl+Z)
        if True:
            # Store all layers for undo
            layers_backup = []
            for layer_id in list(self.canvas.layers.keys()):
                layer_item = self.canvas.layers[layer_id]
                layers_backup.append(layer_item.layer_data)
                self.canvas.remove_layer(layer_id)
                self.layer_panel.remove_layer(layer_id)
            
            if layers_backup:
                self.undo_stack.append(('clear_all', layers_backup))
                self.redo_stack.clear()

    def export_image(self):
        """Export the composite image"""
        pixmap = self.canvas.export_composite()
        if not pixmap:
            # QMessageBox.warning(self, "경고", "내보낼 이미지가 없습니다.")
            print("⚠️ No image to export")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "이미지 저장", "", "PNG Files (*.png)"
        )
        
        if file_path:
            pixmap.save(file_path, "PNG")
            # QMessageBox.information(self, "내보내기", f"저장됨: {file_path}")
            print(f"✅ Exported to: {file_path}")

    def is_empty(self) -> bool:
        """Check if canvas has any layers"""
        return len(self.canvas.layers) == 0

    def export_composite(self) -> Optional[QPixmap]:
        """Export the composite image"""
        return self.canvas.export_composite()
    
    def get_active_character_prompts(self) -> List[Tuple[str, str]]:
        """Get all active character prompts ordered by z-order
        Returns list of (prompt, uc) tuples"""
        prompts = []
        
        # Get layers sorted by z-order
        layers = self.canvas.get_layers_by_z_order()
        
        for layer_data in layers:
            # Check if layer has active character prompt
            if (hasattr(layer_data, 'character_prompt') and 
                layer_data.character_prompt and
                hasattr(layer_data, 'prompt_activated') and 
                layer_data.prompt_activated):
                
                # Get combined prompt with active properties
                prompt, uc = layer_data.get_character_prompt()
                if prompt:  # Only add if there's actual prompt content
                    prompts.append((prompt, uc))
        
        return prompts

    def set_inpaint_prompts(self, main_prompt: str, negative_prompt: str):
        """Set prompts for inpaint mode (without automatically enabling it)"""
        # Store prompts for later use
        self.stored_main_prompt = main_prompt
        self.stored_negative_prompt = negative_prompt
        
        # If inpaint control window already exists, set the prompts
        if self.inpaint_control_window:
            self.inpaint_control_window.set_prompts(main_prompt, negative_prompt)
        
        print(f"✅ Inpaint prompts stored (will be used when inpaint mode is enabled):")
        print(f"   Main: {main_prompt[:50]}...")
        print(f"   Negative: {negative_prompt[:50]}...")

    # --- Keyboard Shortcuts ---
    
    def keyPressEvent(self, event):
        """Handle keyboard shortcuts"""
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Z:
                self.undo()
            elif event.key() == Qt.Key.Key_Y:
                self.redo()
            elif event.key() == Qt.Key.Key_V:
                self.paste_from_clipboard()
        elif event.key() == Qt.Key.Key_Delete:
            # Delete selected layer
            if self.canvas.selected_layer_id:
                self._on_delete_layer(self.canvas.selected_layer_id)
        super().keyPressEvent(event)

    def paste_from_clipboard(self):
        """Paste image from clipboard as a new layer"""
        clipboard = QApplication.clipboard()
        mimeData = clipboard.mimeData()
        
        if mimeData.hasImage():
            # Get image from clipboard
            image = clipboard.image()
            if image.isNull():
                print("⚠️ Clipboard image is null")
                return
            
            # Convert QImage to QPixmap
            pixmap = QPixmap.fromImage(image)
            
            # Save to temporary file
            temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            temp_path = temp_file.name
            temp_file.close()
            
            # Save pixmap to temp file
            if pixmap.save(temp_path, 'PNG'):
                # Generate layer name
                timestamp = datetime.datetime.now().strftime("%H%M%S")
                layer_name = f"Clipboard_{timestamp}"
                
                # Add as new layer
                layer_id = self.add_image_from_path(temp_path, layer_name)
                
                if layer_id:
                    print(f"✅ Pasted image from clipboard as layer: {layer_name}")
                    # Center the new layer
                    self.center_layer(layer_id)
                    
                    # Clean up temp file after successful add
                    try:
                        os.unlink(temp_path)
                    except:
                        pass
                else:
                    print("⚠️ Failed to add clipboard image as layer")
                    # Clean up temp file on failure
                    try:
                        os.unlink(temp_path)
                    except:
                        pass
            else:
                print("⚠️ Failed to save clipboard image to temp file")
        else:
            print("⚠️ No image found in clipboard")

    # --- Undo/Redo System ---
    
    def record_layer_move(self, layer_id: str, old_pos: QPointF, new_pos: QPointF):
        """Record layer position change for undo/redo"""
        self.undo_stack.append(('move_layer', (layer_id, old_pos, new_pos)))
        self.redo_stack.clear()
        print(f"📝 Recorded move: {old_pos} → {new_pos}")
    
    def record_layer_scale(self, layer_id: str, old_scale: float, new_scale: float):
        """Record layer scale change for undo/redo"""
        self.undo_stack.append(('scale_layer', (layer_id, old_scale, new_scale)))
        self.redo_stack.clear()
        print(f"📝 Recorded scale: {old_scale:.2f} → {new_scale:.2f}")

    def center_layer(self, layer_id: str):
        """Center a layer on the canvas"""
        if layer_id not in self.canvas.layers:
            print(f"⚠️ Layer {layer_id} not found")
            return
        
        layer_item = self.canvas.layers[layer_id]
        
        # Get canvas center
        canvas_rect = self.canvas.canvas_bounds
        canvas_center_x = canvas_rect.width() / 2
        canvas_center_y = canvas_rect.height() / 2
        
        # Get layer bounds
        layer_bounds = layer_item.boundingRect()
        layer_width = layer_bounds.width()
        layer_height = layer_bounds.height()
        
        # Calculate position to center the layer
        new_x = canvas_center_x - layer_width / 2
        new_y = canvas_center_y - layer_height / 2
        
        # Record current position for undo
        old_pos = layer_item.pos()
        new_pos = QPointF(new_x, new_y)
        
        # Move the layer
        layer_item.setPos(new_pos)
        
        # Record for undo/redo
        self.record_layer_move(layer_id, old_pos, new_pos)
        
        # Update layer data in layer panel
        if layer_id in self.layer_panel.layers_data:
            self.layer_panel.layers_data[layer_id].position = (new_x, new_y)
        
        print(f"🎯 Centered layer {layer_id} at ({new_x:.1f}, {new_y:.1f})")

    def undo(self):
        """Undo last action"""
        if not self.undo_stack:
            return
        
        action = self.undo_stack.pop()
        action_type, data = action
        
        if action_type == 'add_layer':
            # Remove the layer
            layer_data = data
            self.canvas.remove_layer(layer_data.id)
            self.layer_panel.remove_layer(layer_data.id)
            self.redo_stack.append(action)
            
        elif action_type == 'delete_layer':
            # Restore the layer
            layer_data = data
            self.canvas.add_layer(layer_data)
            self.layer_panel.add_layer(layer_data)
            self.redo_stack.append(action)
            
        elif action_type == 'move_layer':
            # Revert position
            layer_id, old_pos, new_pos = data
            if layer_id in self.canvas.layers:
                self.canvas.layers[layer_id].setPos(old_pos)
                self.redo_stack.append(action)
                
        elif action_type == 'scale_layer':
            # Revert scale
            layer_id, old_scale, new_scale = data
            if layer_id in self.canvas.layers:
                self.canvas.layers[layer_id].set_scale_about_center(old_scale)
                self.redo_stack.append(action)
                
        elif action_type == 'clear_all':
            # Restore all layers
            layers_backup = data
            for layer_data in layers_backup:
                self.canvas.add_layer(layer_data)
                self.layer_panel.add_layer(layer_data)
            self.redo_stack.append(action)

    def redo(self):
        """Redo last undone action"""
        if not self.redo_stack:
            return
        
        action = self.redo_stack.pop()
        action_type, data = action
        
        if action_type == 'add_layer':
            # Re-add the layer
            layer_data = data
            self.canvas.add_layer(layer_data)
            self.layer_panel.add_layer(layer_data)
            self.undo_stack.append(action)
            
        elif action_type == 'delete_layer':
            # Re-delete the layer
            layer_data = data
            self.canvas.remove_layer(layer_data.id)
            self.layer_panel.remove_layer(layer_data.id)
            self.undo_stack.append(action)
            
        elif action_type == 'move_layer':
            # Re-apply position
            layer_id, old_pos, new_pos = data
            if layer_id in self.canvas.layers:
                self.canvas.layers[layer_id].setPos(new_pos)
                self.undo_stack.append(action)
                
        elif action_type == 'scale_layer':
            # Re-apply scale
            layer_id, old_scale, new_scale = data
            if layer_id in self.canvas.layers:
                self.canvas.layers[layer_id].set_scale_about_center(new_scale)
                self.undo_stack.append(action)
                
        elif action_type == 'clear_all':
            # Re-clear all layers
            layers_backup = data
            for layer_data in layers_backup:
                self.canvas.remove_layer(layer_data.id)
                self.layer_panel.remove_layer(layer_data.id)
            self.undo_stack.append(action)