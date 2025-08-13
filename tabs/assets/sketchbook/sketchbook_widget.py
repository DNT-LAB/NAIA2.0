"""
Main widget for Sketchbook module - integrates all components
"""

import os
import io
import tempfile
import datetime
from typing import Optional, List, Tuple
from dataclasses import dataclass

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                            QComboBox, QLabel, QFileDialog, QMessageBox,
                            QSplitter, QProgressDialog, QApplication, QDialog)
from PyQt6.QtCore import Qt, QPointF, pyqtSignal, QThread, QBuffer
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
        # progress_dialog removed - no longer using blocking dialog
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
        
        # Initialize results manager (single instance)
        self.results_manager = None
        
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
        
        # Crop button
        self.crop_button = QPushButton("✂️ 자르기")
        self.crop_button.setCheckable(True)
        self.crop_button.toggled.connect(self._on_crop_mode_toggled)
        layout.addWidget(self.crop_button)
        
        # Crop apply button (initially hidden)
        self.apply_crop_button = QPushButton("✅ 자르기 적용")
        self.apply_crop_button.clicked.connect(self._apply_crop)
        self.apply_crop_button.setVisible(False)
        layout.addWidget(self.apply_crop_button)
        
        # Crop cancel button (initially hidden)
        self.cancel_crop_button = QPushButton("❌ 자르기 취소")
        self.cancel_crop_button.clicked.connect(self._cancel_crop)
        self.cancel_crop_button.setVisible(False)
        layout.addWidget(self.cancel_crop_button)
        
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
        for button in [self.add_button, self.export_button, self.clear_button, 
                      self.crop_button, self.apply_crop_button, self.cancel_crop_button]:
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
        self.layer_panel.layers_merge_requested.connect(self._on_merge_layers)
        self.layer_panel.layer_remove_bg_requested.connect(self._on_remove_background)
        self.layer_panel.layer_save_variation_requested.connect(self._on_save_variation)
        self.layer_panel.layer_set_background_color.connect(self._on_set_background_color)
        self.layer_panel.layer_remove_background_color.connect(self._on_remove_background_color)

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
    
    def _on_merge_layers(self, target_layer_id: str, source_layer_ids: list):
        """Merge multiple layers into a single layer"""
        try:
            from PIL import Image
            import tempfile
            
            # Get target layer
            if target_layer_id not in self.canvas.layers:
                print(f"⚠️ Target layer {target_layer_id} not found")
                return
            
            target_layer = self.canvas.layers[target_layer_id]
            
            # Collect all layers to merge (target + sources)
            all_layer_ids = [target_layer_id] + source_layer_ids
            layers_to_merge = []
            
            for lid in all_layer_ids:
                if lid in self.canvas.layers:
                    layers_to_merge.append(self.canvas.layers[lid])
            
            if len(layers_to_merge) < 2:
                print("⚠️ Not enough layers to merge")
                return
            
            # Sort layers by z-order (lowest first for proper compositing)
            layers_to_merge.sort(key=lambda l: l.layer_data.z_order)
            
            # Create composite image at canvas size with white background
            canvas_w, canvas_h = self.canvas.current_canvas_size
            # Start with white background to avoid transparency issues
            composite = Image.new('RGBA', (canvas_w, canvas_h), (255, 255, 255, 255))
            
            # Composite each layer
            for layer in layers_to_merge:
                if not layer.layer_data.visible:
                    continue
                
                # Get layer's pixmap as PIL Image
                pixmap = layer.pixmap()
                
                # Convert QPixmap to PIL Image
                buffer = QBuffer()
                buffer.open(QBuffer.OpenModeFlag.WriteOnly)
                pixmap.save(buffer, "PNG")
                buffer.close()
                
                img_bytes = buffer.data().data()
                layer_img = Image.open(io.BytesIO(img_bytes))
                
                # Get layer position in scene coordinates
                pos = layer.pos()
                x = int(pos.x())
                y = int(pos.y())
                
                # Apply layer's transform (scale)
                if layer.layer_data.scale != 1.0:
                    new_w = int(layer_img.width * layer.layer_data.scale)
                    new_h = int(layer_img.height * layer.layer_data.scale)
                    layer_img = layer_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                
                # Paste layer onto composite using alpha_composite for proper blending
                # This ensures transparent areas blend properly with white background
                if layer_img.mode == 'RGBA':
                    # Create a temporary image at the same size as composite
                    temp = Image.new('RGBA', composite.size, (0, 0, 0, 0))
                    temp.paste(layer_img, (x, y))
                    # Use alpha_composite to properly blend with background
                    composite = Image.alpha_composite(composite, temp)
                else:
                    # For non-RGBA images, just paste normally
                    composite.paste(layer_img, (x, y))
            
            # Save composite to temporary file
            temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            temp_path = temp_file.name
            temp_file.close()
            composite.save(temp_path, 'PNG')
            
            # Store undo data for all layers
            undo_data = []
            for lid in all_layer_ids:
                if lid in self.canvas.layers:
                    undo_data.append(('delete_layer', self.canvas.layers[lid].layer_data))
            self.undo_stack.append(('merge_layers', undo_data))
            self.redo_stack.clear()
            
            # Remove all source layers
            for lid in source_layer_ids:
                self.canvas.remove_layer(lid)
                self.layer_panel.remove_layer(lid)
            
            # Update target layer with merged image
            target_layer.layer_data.image_path = temp_path
            target_layer.layer_data.position = (0, 0)
            target_layer.layer_data.scale = 1.0
            target_layer.layer_data.rotation = 0.0
            target_layer.layer_data.original_size = (canvas_w, canvas_h)
            
            # Reload the merged image
            pixmap = QPixmap(temp_path)
            target_layer.layer_data.pixmap = pixmap
            target_layer.setPixmap(pixmap)
            target_layer.setPos(0, 0)
            target_layer.resetTransform()  # Use Qt's built-in resetTransform method
            
            # Update layer name
            target_layer.layer_data.name = f"Merged_{target_layer.layer_data.name[:20]}"
            self.layer_panel.update_layer_name(target_layer.layer_data.id, target_layer.layer_data.name)
            
            # No need to clear checkbox states since we use visibility for merging
            
            print(f"✅ Successfully merged {len(source_layer_ids) + 1} layers")
            
        except Exception as e:
            print(f"❌ Error merging layers: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_remove_background(self, layer_id: str):
        """Remove background from a layer using assets_tab's rembg functionality"""
        try:
            # Check if layer exists
            if layer_id not in self.canvas.layers:
                print(f"⚠️ Layer {layer_id} not found")
                return
            
            layer = self.canvas.layers[layer_id]
            layer_data = layer.layer_data
            
            # Check if the parent widget (AssetsTab) has the background removal functionality
            parent_tab = self.parent()
            while parent_tab and not hasattr(parent_tab, '_run_rembg_process'):
                parent_tab = parent_tab.parent()
            
            if not parent_tab or not hasattr(parent_tab, '_run_rembg_process'):
                QMessageBox.warning(self, "기능 없음", 
                    "배경 제거 기능을 사용할 수 없습니다.\n"
                    "Assets Workshop 탭에서 rembg 패키지를 먼저 설치해주세요.")
                return
            
            # Save layer image to temporary file
            import tempfile
            temp_input = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            temp_output = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            
            # Get the layer's pixmap and save it
            pixmap = layer.pixmap()
            pixmap.save(temp_input.name, 'PNG')
            temp_input.close()
            
            # Show progress dialog
            progress = QProgressDialog("배경을 제거하는 중...", None, 0, 0, self)
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.show()
            QApplication.processEvents()
            
            try:
                # Run background removal using parent's method
                success = parent_tab._run_rembg_process(temp_input.name, temp_output.name)
                
                if success and os.path.exists(temp_output.name):
                    # Load the result
                    result_pixmap = QPixmap(temp_output.name)
                    
                    if not result_pixmap.isNull():
                        # Update layer with result
                        layer_data.pixmap = result_pixmap
                        layer_data.image_path = temp_output.name
                        layer.setPixmap(result_pixmap)
                        
                        # Update layer name to indicate background removed
                        layer_data.name = f"BG_Removed_{layer_data.name[:15]}"
                        self.layer_panel.update_layer_name(layer_id, layer_data.name)
                        
                        print(f"✅ Background removed successfully for layer: {layer_id}")
                        QMessageBox.information(self, "성공", "배경이 성공적으로 제거되었습니다.")
                    else:
                        QMessageBox.warning(self, "오류", "결과 이미지를 로드할 수 없습니다.")
                else:
                    QMessageBox.warning(self, "실패", "배경 제거에 실패했습니다.")
                    
            finally:
                progress.close()
                # Clean up temp files (but keep the output if successful)
                try:
                    os.unlink(temp_input.name)
                except:
                    pass
                
        except Exception as e:
            print(f"❌ Error removing background: {e}")
            QMessageBox.critical(self, "오류", f"배경 제거 중 오류 발생:\n{str(e)}")
            import traceback
            traceback.print_exc()
    
    def _on_set_background_color(self, layer_id: str, color_hex: str):
        """Set background color for a layer"""
        try:
            from PIL import Image, ImageDraw
            import tempfile
            
            # Check if layer exists
            if layer_id not in self.canvas.layers:
                print(f"⚠️ Layer {layer_id} not found")
                return
            
            layer = self.canvas.layers[layer_id]
            layer_data = layer.layer_data
            
            # Store original image path before applying background (if not already stored)
            if not hasattr(layer_data, 'original_image_path_before_bg') or not layer_data.original_image_path_before_bg:
                # Save current image as original if this is the first background application
                original_file = tempfile.NamedTemporaryFile(suffix='_original.png', delete=False)
                original_filename = original_file.name
                original_file.close()
                
                current_pixmap = layer.pixmap()
                current_pixmap.save(original_filename, 'PNG')
                layer_data.original_image_path_before_bg = original_filename
                print(f"📁 Saved original image to: {original_filename}")
            
            # Load the original image (not the current one with potential background)
            from PyQt6.QtGui import QPixmap
            original_pixmap = QPixmap(layer_data.original_image_path_before_bg)
            if original_pixmap.isNull():
                print(f"⚠️ Could not load original image")
                return
            
            # Get layer dimensions
            layer_width = original_pixmap.width()
            layer_height = original_pixmap.height()
            
            # Create a new image with background color
            # Parse the hex color (supports alpha)
            from PyQt6.QtGui import QColor
            qcolor = QColor(color_hex)
            
            # Create PIL image with background
            background = Image.new('RGBA', (layer_width, layer_height), 
                                  (qcolor.red(), qcolor.green(), qcolor.blue(), qcolor.alpha()))
            
            # Convert original pixmap to PIL Image
            temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            temp_filename = temp_file.name
            temp_file.close()
            
            original_pixmap.save(temp_filename, 'PNG')
            foreground = Image.open(temp_filename)
            
            # Composite the foreground over the background
            if foreground.mode != 'RGBA':
                foreground = foreground.convert('RGBA')
            
            # Use alpha_composite to properly blend with transparency
            result = Image.alpha_composite(background, foreground)
            
            # Save the result to a new temp file
            result_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            result_filename = result_file.name
            result_file.close()
            result.save(result_filename, 'PNG')
            
            # Update the layer with new image
            new_pixmap = QPixmap(result_filename)
            
            if not new_pixmap.isNull():
                # Update the layer's pixmap
                layer.setPixmap(new_pixmap)
                
                # Store the background color in layer data for future reference
                layer_data.background_color = color_hex
                
                # Update the layer's image path to the new temp file (but keep original)
                layer_data.image_path = result_filename
                
                print(f"✅ Background color {color_hex} applied to layer: {layer_id}")
            else:
                print(f"❌ Failed to apply background color to layer: {layer_id}")
            
            # Clean up original temp file
            try:
                import os
                os.unlink(temp_filename)
                foreground.close()
                result.close()
            except:
                pass
                
        except Exception as e:
            print(f"❌ Error setting background color: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_remove_background_color(self, layer_id: str):
        """Remove background color from a layer (restore original transparency)"""
        try:
            # Check if layer exists
            if layer_id not in self.canvas.layers:
                print(f"⚠️ Layer {layer_id} not found")
                return
            
            layer = self.canvas.layers[layer_id]
            layer_data = layer.layer_data
            
            # Check if layer has a background color set
            if not hasattr(layer_data, 'background_color') or not layer_data.background_color:
                print(f"⚠️ Layer {layer_id} has no background color to remove")
                return
            
            print(f"🔍 Attempting to restore original image for layer: {layer_id}")
            print(f"   Background color was: {layer_data.background_color}")
            
            # Check if we have the original image path (before background was applied)
            if hasattr(layer_data, 'original_image_path_before_bg') and layer_data.original_image_path_before_bg:
                # Restore from original image
                original_path = layer_data.original_image_path_before_bg
                print(f"   Original image path: {original_path}")
                
                from PyQt6.QtGui import QPixmap
                import os
                
                # Verify file exists
                if not os.path.exists(original_path):
                    print(f"❌ Original file not found: {original_path}")
                    layer_data.background_color = None
                    layer_data.original_image_path_before_bg = None
                    return
                
                original_pixmap = QPixmap(original_path)
                
                if not original_pixmap.isNull():
                    # Update the layer with original image
                    layer.setPixmap(original_pixmap)
                    
                    # Save original to a new temp file for current image_path
                    import tempfile
                    restored_file = tempfile.NamedTemporaryFile(suffix='_restored.png', delete=False)
                    restored_filename = restored_file.name
                    restored_file.close()
                    original_pixmap.save(restored_filename, 'PNG')
                    
                    # Update layer data
                    layer_data.image_path = restored_filename
                    layer_data.background_color = None
                    # Keep original_image_path_before_bg for future use
                    
                    # Force canvas update
                    layer.update()
                    if hasattr(self.canvas, 'update'):
                        self.canvas.update()
                    
                    print(f"✅ Background color removed from layer: {layer_id}")
                    print(f"   Restored image saved to: {restored_filename}")
                else:
                    print(f"❌ Failed to load original pixmap from: {original_path}")
                    layer_data.background_color = None
            else:
                # No original path stored
                print(f"⚠️ No original image path stored for layer: {layer_id}")
                layer_data.background_color = None
                print(f"✅ Background color flag cleared for layer: {layer_id}")
            
        except Exception as e:
            print(f"❌ Error removing background color: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_save_variation(self, layer_id: str):
        """Save layer as character variation"""
        try:
            # Check if layer exists
            if layer_id not in self.canvas.layers:
                print(f"⚠️ Layer {layer_id} not found")
                return
            
            layer = self.canvas.layers[layer_id]
            layer_data = layer.layer_data
            
            # Check if layer has character prompt data
            if not (hasattr(layer_data, 'character_prompt') and layer_data.character_prompt and
                   hasattr(layer_data, 'prompt_activated') and layer_data.prompt_activated):
                QMessageBox.warning(self, "캐릭터 정보 없음", 
                    "이 레이어에는 활성화된 캐릭터 프롬프트 정보가 없습니다.")
                return
            
            # Get layer's current pixmap
            layer_pixmap = layer.pixmap()
            if layer_pixmap.isNull():
                QMessageBox.warning(self, "이미지 없음", 
                    "레이어에서 이미지를 가져올 수 없습니다.")
                return
            
            # Import and show the save variation dialog
            try:
                from tabs.assets.save_variation_dialog import SaveAsVariationDialog
                
                dialog = SaveAsVariationDialog(layer_data, layer_pixmap, self)
                result = dialog.exec()
                
                if result == QDialog.DialogCode.Accepted:
                    print(f"✅ Variation saved successfully for layer: {layer_id}")
                    
            except ImportError as e:
                print(f"❌ Could not import SaveAsVariationDialog: {e}")
                QMessageBox.critical(self, "모듈 오류", 
                    "Variation 저장 다이얼로그를 로드할 수 없습니다.")
                
        except Exception as e:
            print(f"❌ Error saving variation: {e}")
            QMessageBox.critical(self, "오류", f"Variation 저장 중 오류 발생:\n{str(e)}")
            import traceback
            traceback.print_exc()

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
            
            # Hide control window if exists (just hide, don't destroy)
            if self.inpaint_control_window:
                self.inpaint_control_window.hide()
    
    def _on_crop_mode_toggled(self, checked: bool):
        """Handle crop mode toggle"""
        if checked:
            # Disable inpaint mode if active
            if self.inpaint_button.isChecked():
                self.inpaint_button.setChecked(False)
            
            # Get selected layer
            selected_layer = self.canvas.get_selected_layer()
            if not selected_layer:
                QMessageBox.information(self, "알림", "자르기할 레이어를 먼저 선택하세요.")
                self.crop_button.setChecked(False)
                return
            
            # Enable crop mode for selected layer
            selected_layer.set_crop_mode(True)
            
            # Show crop control buttons
            self.apply_crop_button.setVisible(True)
            self.cancel_crop_button.setVisible(True)
            
            # Disable other controls during crop
            self.add_button.setEnabled(False)
            self.export_button.setEnabled(False)
            self.inpaint_button.setEnabled(False)
            self.canvas_combo.setEnabled(False)
            self.clear_button.setEnabled(False)
        else:
            self._cancel_crop()
    
    def _apply_crop(self):
        """Apply crop to selected layer"""
        selected_layer = self.canvas.get_selected_layer()
        if selected_layer and selected_layer._crop_mode:
            success = selected_layer.apply_crop()
            if success:
                # Exit crop mode
                self.crop_button.setChecked(False)
                self._hide_crop_controls()
                
                # Record for undo (add to undo stack)
                self.undo_stack.append(('crop_layer', selected_layer.layer_data.id))
                print(f"✂️ Layer cropped: {selected_layer.layer_data.name}")
            else:
                QMessageBox.warning(self, "오류", "자르기를 적용할 수 없습니다.")
    
    def _cancel_crop(self):
        """Cancel crop operation"""
        selected_layer = self.canvas.get_selected_layer()
        if selected_layer:
            selected_layer.cancel_crop()
        
        self.crop_button.setChecked(False)
        self._hide_crop_controls()
    
    def _hide_crop_controls(self):
        """Hide crop control buttons and re-enable other controls"""
        self.apply_crop_button.setVisible(False)
        self.cancel_crop_button.setVisible(False)
        
        # Re-enable other controls
        self.add_button.setEnabled(True)
        self.export_button.setEnabled(True)
        self.inpaint_button.setEnabled(True)
        self.canvas_combo.setEnabled(True)
        self.clear_button.setEnabled(True)

    def _show_inpaint_controls(self):
        """Show inpaint control window"""
        # Import here to avoid circular imports
        from .sketchbook_inpaint_control import InpaintControlWindow
        
        if not self.inpaint_control_window:
            self.inpaint_control_window = InpaintControlWindow(self)
            
            # Connect seed fix sync
            if hasattr(self.app_context, 'main_window'):
                main_window = self.app_context.main_window
                if hasattr(main_window, 'seed_fix_checkbox'):
                    # Sync initial state
                    self.inpaint_control_window.sync_seed_fix_from_main(
                        main_window.seed_fix_checkbox.isChecked()
                    )
                    # Connect for future changes
                    main_window.seed_fix_checkbox.toggled.connect(
                        self.inpaint_control_window.sync_seed_fix_from_main
                    )
            
            # Set stored prompts if available
            if self.stored_main_prompt or self.stored_negative_prompt:
                self.inpaint_control_window.set_prompts(
                    self.stored_main_prompt, 
                    self.stored_negative_prompt
                )
        
        # Use the show_window method to properly show the window
        self.inpaint_control_window.show_window()
    
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
        
        # Mask check is now done early in control window, so this shouldn't happen
        # But keep as safety check
        if not mask:
            print("⚠️ Mask is empty - this should have been caught earlier")
            if self.inpaint_control_window:
                self.inpaint_control_window.set_generating(False)
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
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "오류", "캔버스가 비어있습니다.")
            print("⚠️ Canvas is empty")
            if self.canvas.inpaint_layer:
                self.canvas.inpaint_layer.setVisible(True)
            # Reset generation state
            if self.inpaint_control_window:
                self.inpaint_control_window.set_generating(False)
            return
        
        # Restore inpaint layer visibility
        if self.canvas.inpaint_layer:
            self.canvas.inpaint_layer.setVisible(True)
        
        # Convert QPixmap to PIL Image
        composite_img = self._qpixmap_to_pil(composite)
        mask_img = self._qpixmap_to_pil(mask)
        small_mask_img = self._qpixmap_to_pil(small_mask) if small_mask else None
        
        # No progress dialog - just update control window state
        # The control window will show "생성중..." on its button
        
        # Note: Control window stays visible but with prompts hidden (already done in generate_inpaint)
        
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
        """Update progress status message"""
        # Just log the progress, no dialog to update
        print(f"🔄 {message}")
    
    def _on_inpaint_generation_error(self, error_msg: str):
        """Handle generation error"""
        # Show error message without blocking dialog
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.critical(self, "생성 오류", f"인페인트 생성 실패:\n{error_msg}")
        print(f"❌ Inpaint generation error: {error_msg}")
        
        # Notify control window of failure
        if self.inpaint_control_window:
            self.inpaint_control_window.on_generation_complete(success=False)
        
        # Clean up worker
        if self.inpaint_worker:
            self.inpaint_worker.deleteLater()
            self.inpaint_worker = None
    
    def _on_inpaint_generation_finished(self, result_img: Image, server_original: Image, bbox: tuple):
        """Handle successful generation - show in separate window"""
        # Check if we should update virtual layer
        should_update_virtual = False
        if self.inpaint_control_window:
            # ONLY update virtual layer during sequential generation
            # Check if this is a sequential generation AND virtual layer update is enabled
            if hasattr(self.inpaint_control_window, 'is_sequential_generating'):
                if self.inpaint_control_window.is_sequential_generating:
                    # During sequential generation, check current generation data
                    if hasattr(self.inpaint_control_window, 'current_generation_data'):
                        data = self.inpaint_control_window.current_generation_data
                        if data and data.update_virtual_layer:
                            should_update_virtual = True
        
        # Keep mask visible for potential additional generations
        # Users can manually clear it if they want
        
        # Collect generation parameters for retry feature
        generation_params = {}
        if self.inpaint_control_window:
            if hasattr(self.inpaint_control_window, 'current_generation_data'):
                data = self.inpaint_control_window.current_generation_data
                if data:
                    generation_params = {
                        'main_prompt': data.main_prompt,
                        'negative_prompt': data.negative_prompt,
                        'strength': data.strength
                    }
        
        # Add result to unified manager window
        try:
            from .inpaint_results_manager import InpaintResultsManager
            
            # Create manager if it doesn't exist
            if not self.results_manager:
                self.results_manager = InpaintResultsManager(self)
                self.results_manager.result_added.connect(self._add_result_to_canvas)
            
            # Debug: Check parameter types before calling add_result
            print(f"Debug: result_img type: {type(result_img)}")
            print(f"Debug: bbox type: {type(bbox)}, value: {bbox}")
            print(f"Debug: generation_params type: {type(generation_params)}")
            print(f"Debug: server_original type: {type(server_original)}")
            
            # Add new result with generation parameters and server original
            self.results_manager.add_result(result_img, bbox, generation_params, server_original)
            
            print(f"✅ Inpaint result added to results manager")
            
            # Auto-update virtual layer if checkbox was checked
            # This happens synchronously before notifying completion
            if should_update_virtual:
                # Create temporary file for the result
                import tempfile
                temp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                result_img.save(temp.name, 'PNG')
                temp.close()
                
                # Add to canvas as virtual layer (this will delete existing virtual layers first)
                self._add_virtual_layer_to_canvas(temp.name, bbox)
                print(f"✅ Auto-updated virtual layer")
            
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "오류", f"결과 표시 중 오류:\n{str(e)}")
            print(f"❌ Error showing result: {e}")
        
        # Notify control window of completion AFTER virtual layer update
        if self.inpaint_control_window:
            self.inpaint_control_window.on_generation_complete(success=True)
        
        # Clean up worker
        if self.inpaint_worker:
            self.inpaint_worker.deleteLater()
            self.inpaint_worker = None
    
    def _delete_virtual_layers(self):
        """Delete all virtual inpaint layers from canvas"""
        try:
            # Find and remove ONLY virtual layers (starting with "Virtual_Inpaint_")
            # Regular inpaint results start with just "Inpaint_"
            layers_to_remove = []
            for layer_id, layer_item in self.canvas.layers.items():
                if hasattr(layer_item, 'layer_data') and layer_item.layer_data:
                    # Only delete virtual layers, not regular inpaint results
                    if layer_item.layer_data.name.startswith("Virtual_Inpaint_"):
                        layers_to_remove.append(layer_id)
            
            # Remove found layers
            for layer_id in layers_to_remove:
                self.canvas.remove_layer(layer_id)
                # Also remove from layer panel
                self.layer_panel.remove_layer(layer_id)
                print(f"🗑️ Removed virtual layer: {layer_id}")
            
            if layers_to_remove:
                print(f"✅ Deleted {len(layers_to_remove)} virtual layer(s)")
            
        except Exception as e:
            print(f"⚠️ Error deleting virtual layers: {e}")
    
    def _add_virtual_layer_to_canvas(self, image_path: str, bbox: tuple):
        """Add virtual inpaint layer to canvas (used during sequential generation)"""
        try:
            import datetime
            from .sketchbook_types import LayerData
            
            # Delete existing virtual layers first
            self._delete_virtual_layers()
            
            # Position based on bounding box
            x_pos = bbox[0] if bbox else 0
            y_pos = bbox[1] if bbox else 0
            
            timestamp = datetime.datetime.now().strftime("%H%M%S")
            
            # Use Virtual_Inpaint_ prefix for virtual layers
            layer_data = LayerData(
                name=f"Virtual_Inpaint_{timestamp}",
                image_path=image_path,
                position=(float(x_pos), float(y_pos)),
                z_order=self.canvas.get_max_z_order() + 1,
            )
            
            # Add layer to canvas
            layer_id = self.canvas.add_layer(layer_data)
            self.layer_panel.add_layer(layer_data)
            
            print(f"✅ Virtual inpaint layer added to canvas at ({x_pos}, {y_pos})")
            
        except Exception as e:
            print(f"❌ Error adding virtual layer to canvas: {e}")
            import traceback
            traceback.print_exc()
    
    def _add_result_to_canvas(self, image_path: str, bbox: tuple):
        """Add inpaint result to canvas from result window"""
        try:
            import datetime
            from .sketchbook_types import LayerData
            
            # DON'T delete virtual layers when adding regular results
            # Only position based on bounding box
            x_pos = bbox[0] if bbox else 0
            y_pos = bbox[1] if bbox else 0
            
            timestamp = datetime.datetime.now().strftime("%H%M%S")
            
            # Regular inpaint results use Inpaint_ prefix (not Virtual_)
            layer_data = LayerData(
                name=f"Inpaint_{timestamp}",
                image_path=image_path,
                position=(float(x_pos), float(y_pos)),
                z_order=self.canvas.get_max_z_order() + 1,
            )
            
            # Add layer to canvas
            layer_id = self.canvas.add_layer(layer_data)
            self.layer_panel.add_layer(layer_data)
            
            print(f"✅ Inpaint result added to canvas at ({x_pos}, {y_pos})")
            
        except Exception as e:
            QMessageBox.critical(self, "오류", f"레이어 추가 중 오류:\n{str(e)}")
            print(f"❌ Error adding result to canvas: {e}")
    
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
                                        character_prompt: Optional[dict] = None,
                                        selected_property: Optional[str] = None) -> Optional[str]:
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
        
        # If a specific property is selected, mark it as active
        if selected_property and character_prompt:
            properties = character_prompt.get('properties', {})
            if selected_property in properties:
                # Initialize active_properties with the selected property checked
                layer_data.active_properties = {selected_property: True}
                print(f"   ✓ Auto-checked property: {selected_property}")
        
        layer_id = self.canvas.add_layer(layer_data)
        self.layer_panel.add_layer(layer_data)
        
        # Record for undo/redo
        self.undo_stack.append(('add_layer', layer_data))
        self.redo_stack.clear()
        
        print(f"✅ Added layer: {layer_name} (ID: {layer_id}, Z: {layer_data.z_order})")
        if character_prompt:
            print(f"   📝 With character prompt")
            if selected_property:
                print(f"   📌 Selected variation: {selected_property}")
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
    
    def retry_inpaint_generation(self, frame):
        """Retry generation for a specific result frame"""
        if not frame.generation_params:
            print("⚠️ No generation parameters for retry")
            return
        
        # Check if retry is already running
        if hasattr(self, 'retry_worker') and self.retry_worker and self.retry_worker.isRunning():
            print("⚠️ Retry generation already in progress")
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "재시도 중", "이미 재시도가 진행 중입니다.")
            return
        
        # Check if normal generation is running
        if hasattr(self, 'inpaint_worker') and self.inpaint_worker and self.inpaint_worker.isRunning():
            print("⚠️ Normal generation in progress")
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "생성 중", "인페인트 생성이 진행 중입니다.")
            return
        
        # Get current mask and composite
        if not self.canvas.inpaint_layer:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "오류", "인페인트 레이어가 없습니다.")
            return
        
        # Get mask
        mask = self.canvas.get_inpaint_mask()
        small_mask = self.canvas.get_small_inpaint_mask()
        
        if not mask:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "오류", "마스크가 비어있습니다.")
            return
        
        # Temporarily hide inpaint layer for composite generation
        self.canvas.inpaint_layer.setVisible(False)
        
        # Get composite image
        composite = self.canvas.export_composite()
        if not composite:
            self.canvas.inpaint_layer.setVisible(True)
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "오류", "캔버스가 비어있습니다.")
            return
        
        # Restore inpaint layer visibility
        self.canvas.inpaint_layer.setVisible(True)
        
        # Convert to PIL
        composite_img = self._qpixmap_to_pil(composite)
        mask_img = self._qpixmap_to_pil(mask)
        small_mask_img = self._qpixmap_to_pil(small_mask) if small_mask else None
        
        # Get character prompts
        character_prompts = self.get_active_character_prompts()
        
        # Create worker with overridden parameters
        from .sketchbook_inpaint_worker import InpaintGenerationWorker
        
        self.retry_worker = InpaintGenerationWorker(
            self.app_context, composite_img, mask_img,
            frame.generation_params['main_prompt'],
            frame.generation_params['negative_prompt'],
            frame.generation_params['strength'],
            small_mask_img,
            character_prompts
        )
        
        # Connect to special handler for retry
        self.retry_worker.generation_finished.connect(
            lambda img, server_orig, bbox: self._on_retry_finished(img, server_orig, bbox, frame)
        )
        self.retry_worker.generation_error.connect(self._on_retry_error)
        
        # Start generation
        self.retry_worker.start()
        print(f"🔄 Retry generation started for frame #{frame.index + 1}")
    
    def _on_retry_finished(self, result_img: Image, server_original: Image, bbox: tuple, frame):
        """Handle retry generation completion"""
        # Update the frame with new result and server original
        frame.update_result(result_img, server_original)
        print(f"✅ Retry completed for frame #{frame.index + 1}")
        
        # Clean up worker
        if hasattr(self, 'retry_worker'):
            if self.retry_worker.isRunning():
                self.retry_worker.quit()
                self.retry_worker.wait(100)  # Wait up to 100ms for thread to finish
            self.retry_worker.deleteLater()
            self.retry_worker = None
    
    def _on_retry_error(self, error_msg: str):
        """Handle retry generation error"""
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.critical(self, "재시도 실패", f"재시도 생성 실패:\n{error_msg}")
        print(f"❌ Retry generation error: {error_msg}")
        
        # Reset retry button state for all frames (find the one that was retrying)
        if self.results_manager:
            for frame in self.results_manager.result_frames:
                if hasattr(frame, 'retry_btn') and not frame.retry_btn.isEnabled():
                    frame.set_retry_state(False)
        
        # Clean up worker
        if hasattr(self, 'retry_worker'):
            if self.retry_worker.isRunning():
                self.retry_worker.quit()
                self.retry_worker.wait(100)  # Wait up to 100ms for thread to finish
            self.retry_worker.deleteLater()
            self.retry_worker = None
    
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