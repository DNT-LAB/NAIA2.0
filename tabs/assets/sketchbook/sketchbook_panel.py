"""
Layer panel UI for Sketchbook module
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget, 
                            QListWidgetItem, QPushButton, QLabel, QAbstractItemView,
                            QMenu, QCheckBox, QColorDialog)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QPixmap, QColor
from typing import Dict, Optional
from .sketchbook_types import LayerData
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

class LayerPanel(QWidget):
    """Panel for managing layers"""
    
    layer_selected = pyqtSignal(str)
    layer_visibility_changed = pyqtSignal(str, bool)
    layer_order_changed = pyqtSignal(str, int)
    layer_delete_requested = pyqtSignal(str)
    layer_center_requested = pyqtSignal(str)
    layers_merge_requested = pyqtSignal(str, list)  # target_layer_id, source_layer_ids
    layer_remove_bg_requested = pyqtSignal(str)  # layer_id for background removal
    layer_save_variation_requested = pyqtSignal(str)  # layer_id for saving as variation
    layer_set_background_color = pyqtSignal(str, str)  # layer_id, color_hex
    layer_remove_background_color = pyqtSignal(str)  # layer_id for removing background color
    clear_all_requested = pyqtSignal()  # Clear all layers signal

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layers_data: Dict[str, LayerData] = {}
        self._updating = False
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Header with label and clear button
        header_layout = QHBoxLayout()
        
        header_label = QLabel("레이어")
        header_label.setStyleSheet(f"font-size: {get_scaled_font_size(16)}px; font-weight: bold; color: #000000;")
        header_layout.addWidget(header_label)
        
        header_layout.addStretch()
        
        self.clear_button = QPushButton("🗑️ 전체 삭제")
        self.clear_button.setMaximumWidth(get_scaled_size(140))
        self.clear_button.clicked.connect(self.clear_all_requested.emit)
        from ui.theme import get_dynamic_styles
        ds = get_dynamic_styles()
        self.clear_button.setStyleSheet(ds.get('secondary_button', ''))
        header_layout.addWidget(self.clear_button)
        
        layout.addLayout(header_layout)

        self.layer_list = QListWidget()
        self.layer_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.layer_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.layer_list.model().rowsMoved.connect(self._on_rows_moved)
        self.layer_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.layer_list.customContextMenuRequested.connect(self._show_context_menu)
        
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

    def add_layer(self, layer_data: LayerData):
        """Add a layer to the panel with checkbox and thumbnail"""
        self.layers_data[layer_data.id] = layer_data
        item = QListWidgetItem()
        
        # Create custom widget for the item
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)
        
        # Visibility checkbox
        checkbox = QCheckBox()
        checkbox.setChecked(layer_data.visible)
        checkbox.toggled.connect(
            lambda checked, lid=layer_data.id: self.layer_visibility_changed.emit(lid, checked)
        )
        layout.addWidget(checkbox)
        
        # Thumbnail
        thumbnail_label = QLabel()
        thumb_size = get_scaled_size(40)
        thumbnail_label.setFixedSize(thumb_size, thumb_size)
        thumbnail_label.setStyleSheet("""
            QLabel {
                border: 1px solid #555;
                background: #2b2b2b;
            }
        """)
        thumbnail_label.setScaledContents(True)
        
        # Generate thumbnail from pixmap or load from file
        if layer_data.pixmap:
            thumbnail = layer_data.pixmap.scaled(
                thumb_size, thumb_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            thumbnail_label.setPixmap(thumbnail)
        else:
            # Try to load from file
            pixmap = QPixmap(layer_data.image_path)
            if not pixmap.isNull():
                thumbnail = pixmap.scaled(
                    thumb_size, thumb_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                thumbnail_label.setPixmap(thumbnail)
        
        layout.addWidget(thumbnail_label)
        
        # Layer name label (yellow text if has active character prompt)
        name_label = QLabel(layer_data.name)
        
        # Check if layer has active character prompt
        has_active_prompt = (hasattr(layer_data, 'character_prompt') and 
                           layer_data.character_prompt is not None and 
                           hasattr(layer_data, 'prompt_activated') and 
                           layer_data.prompt_activated)
        
        # Set color based on prompt status
        text_color = "#FFD700" if has_active_prompt else "white"  # Gold/yellow for active prompts
        name_label.setStyleSheet(f"color: {text_color}; font-size: {get_scaled_font_size(14)}px;")
        layout.addWidget(name_label)
        layout.addStretch()
        
        # Store references in item data (only store layer_id, not QObjects)
        item.setData(Qt.ItemDataRole.UserRole, layer_data.id)
        # Store widget references in widget itself, not in item data
        widget.checkbox = checkbox
        widget.name_label = name_label
        
        # Set item size hint
        item.setSizeHint(widget.sizeHint())
        
        # Insert at top of list
        self.layer_list.insertItem(0, item)
        self.layer_list.setItemWidget(item, widget)

    def remove_layer(self, layer_id: str):
        """Remove a layer from the panel"""
        for i in range(self.layer_list.count()):
            item = self.layer_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == layer_id:
                self.layer_list.takeItem(i)
                break
        
        if layer_id in self.layers_data:
            del self.layers_data[layer_id]

    def select_layer(self, layer_id: str):
        """Select a layer in the list"""
        if self._updating:
            return
        
        # If layer_id is empty, clear selection
        if not layer_id:
            self._updating = True
            self.layer_list.clearSelection()
            self._updating = False
            return
        
        for i in range(self.layer_list.count()):
            item = self.layer_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == layer_id:
                self._updating = True
                self.layer_list.setCurrentItem(item)
                self._updating = False
                break

    def update_layer_name(self, layer_id: str, new_name: str):
        """Update layer name in the panel"""
        for i in range(self.layer_list.count()):
            item = self.layer_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == layer_id:
                # Update the name in the widget
                widget = self.layer_list.itemWidget(item)
                if widget:
                    # Find the label widget and update its text
                    label = widget.findChild(QLabel)
                    if label and label.objectName() != "thumbnail":
                        label.setText(new_name)
                # Update stored data
                if layer_id in self.layers_data:
                    self.layers_data[layer_id].name = new_name
                break
    
    def update_layer_visibility(self, layer_id: str, visible: bool):
        """Update visibility indicator"""
        for i in range(self.layer_list.count()):
            item = self.layer_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == layer_id:
                # Update checkbox state through widget
                widget = self.layer_list.itemWidget(item)
                if widget and hasattr(widget, 'checkbox'):
                    widget.checkbox.setChecked(visible)
                
                # Update stored data
                if layer_id in self.layers_data:
                    self.layers_data[layer_id].visible = visible
                break

    def _on_selection_changed(self):
        """Handle selection change"""
        if self._updating:
            return
        
        items = self.layer_list.selectedItems()
        if items:
            layer_id = items[0].data(Qt.ItemDataRole.UserRole)
            self.layer_selected.emit(layer_id)

    def _on_rows_moved(self, parent, start, end, destination, row):
        """Handle drag and drop reordering"""
        # Update z-orders based on new positions
        for i in range(self.layer_list.count()):
            item = self.layer_list.item(i)
            lid = item.data(Qt.ItemDataRole.UserRole)
            z = self.layer_list.count() - i
            self.layer_order_changed.emit(lid, z)
            
            if lid in self.layers_data:
                self.layers_data[lid].z_order = z

    def _on_delete_clicked(self):
        """Handle delete button click"""
        items = self.layer_list.selectedItems()
        if items:
            lid = items[0].data(Qt.ItemDataRole.UserRole)
            self.layer_delete_requested.emit(lid)
    
    def _show_context_menu(self, position):
        """Show context menu for layer items"""
        item = self.layer_list.itemAt(position)
        if not item:
            return
        
        # Get layer data
        layer_id = item.data(Qt.ItemDataRole.UserRole)
        layer_data = self.layers_data.get(layer_id)
        
        print(f"🔍 Context menu for layer: {layer_id}")
        print(f"   Visible layers: {sum(1 for lid in self.layers_data.values() if lid.visible)}")
        
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: #2b2b2b;
                color: white;
                border: 1px solid #3a3a3a;
            }}
            QMenu::item:selected {{
                background-color: #3a5a8a;
            }}
            QMenu::indicator {{
                width: {get_scaled_size(18)}px;
                height: {get_scaled_size(18)}px;
            }}
            QMenu::indicator:checked {{
                image: none;
                background-color: #3a5a8a;
                border: 2px solid #42A5F5;
            }}
            QMenu::indicator:checked::after {{
                content: "✓";
                color: white;
            }}
        """)
        
        # Add Center action
        center_action = QAction("🎯 화면 가운데로", menu)
        center_action.triggered.connect(lambda: self._request_center_layer(item))
        menu.addAction(center_action)
        
        # Add Remove Background action
        remove_bg_action = QAction("🗑️ 배경 제거", menu)
        remove_bg_action.triggered.connect(lambda: self._request_remove_background(layer_id))
        menu.addAction(remove_bg_action)
        
        # Add Set Background Color action
        set_bg_color_action = QAction("🎨 배경색 설정", menu)
        set_bg_color_action.triggered.connect(lambda: self._request_set_background_color(layer_id))
        menu.addAction(set_bg_color_action)
        
        # Add Remove Background Color action (only if background color is set)
        if layer_data and hasattr(layer_data, 'background_color') and layer_data.background_color:
            remove_bg_color_action = QAction("🚫 배경색 제거", menu)
            remove_bg_color_action.triggered.connect(lambda: self._request_remove_background_color(layer_id))
            menu.addAction(remove_bg_color_action)
        
        # Add Save as Variation action (only for layers with active character prompts)
        if (layer_data and hasattr(layer_data, 'character_prompt') and 
            layer_data.character_prompt and hasattr(layer_data, 'prompt_activated') and
            layer_data.prompt_activated):
            save_variation_action = QAction("💾 Variation으로 저장", menu)
            save_variation_action.triggered.connect(lambda: self._request_save_variation(layer_id))
            menu.addAction(save_variation_action)
        
        # Add Merge Layers action if there are multiple visible layers
        visible_count = sum(1 for lid in self.layers_data.values() if lid.visible)
        if visible_count > 1:
            merge_action = QAction(f"🔀 표시된 레이어 병합 ({visible_count}개)", menu)
            merge_action.triggered.connect(lambda: self._merge_visible_layers(layer_id))
            menu.addAction(merge_action)
        
        # Add separator
        menu.addSeparator()
        
        # Add Delete action
        delete_action = QAction("🗑️ 삭제", menu)
        delete_action.triggered.connect(lambda: self._on_delete_clicked())
        menu.addAction(delete_action)
        
        # Add Character Prompt submenu if layer has character_prompt
        if layer_data and hasattr(layer_data, 'character_prompt') and layer_data.character_prompt:
            menu.addSeparator()
            
            # Create submenu for character prompt
            prompt_menu = QMenu("📝 캐릭터 프롬프트", menu)
            prompt_menu.setStyleSheet(menu.styleSheet())
            
            # Add activation checkbox
            activate_action = QAction("✓ 캐릭터 프롬프트 활성화", prompt_menu)
            activate_action.setCheckable(True)
            activate_action.setChecked(layer_data.prompt_activated if hasattr(layer_data, 'prompt_activated') else True)
            activate_action.triggered.connect(lambda checked: self._toggle_prompt_activation(layer_id, checked))
            prompt_menu.addAction(activate_action)
            
            # Add separator before properties
            properties = layer_data.character_prompt.get('properties', {})
            if properties:
                prompt_menu.addSeparator()
                
                # Add property checkboxes
                for prop_key in properties.keys():
                    prop_action = QAction(f"  {prop_key}", prompt_menu)
                    prop_action.setCheckable(True)
                    
                    # Check if property is active
                    if hasattr(layer_data, 'active_properties') and layer_data.active_properties:
                        prop_action.setChecked(layer_data.active_properties.get(prop_key, False))
                    else:
                        prop_action.setChecked(False)
                    
                    prop_action.triggered.connect(
                        lambda checked, key=prop_key: self._toggle_property(layer_id, key, checked)
                    )
                    prompt_menu.addAction(prop_action)
            
            menu.addMenu(prompt_menu)
        
        menu.exec(self.layer_list.mapToGlobal(position))
    
    def _request_center_layer(self, item):
        """Request to center the layer"""
        lid = item.data(Qt.ItemDataRole.UserRole)
        self.layer_center_requested.emit(lid)
    
    def _toggle_prompt_activation(self, layer_id: str, activated: bool):
        """Toggle character prompt activation for a layer"""
        if layer_id in self.layers_data:
            layer_data = self.layers_data[layer_id]
            layer_data.prompt_activated = activated
            
            # Update the layer name color
            for i in range(self.layer_list.count()):
                item = self.layer_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == layer_id:
                    # Update name label color through widget
                    widget = self.layer_list.itemWidget(item)
                    if widget and hasattr(widget, 'name_label'):
                        text_color = "#FFD700" if activated else "white"
                        widget.name_label.setStyleSheet(f"color: {text_color}; font-size: {get_scaled_font_size(14)}px;")
                    break
            
            print(f"{'✅' if activated else '❌'} Character prompt {'activated' if activated else 'deactivated'} for layer: {layer_id}")
    
    def _toggle_property(self, layer_id: str, prop_key: str, checked: bool):
        """Toggle a property for a layer"""
        if layer_id in self.layers_data:
            layer_data = self.layers_data[layer_id]
            
            # Initialize active_properties if needed
            if not hasattr(layer_data, 'active_properties') or layer_data.active_properties is None:
                layer_data.active_properties = {}
            
            # Toggle the property
            layer_data.active_properties[prop_key] = checked
            
            print(f"{'✅' if checked else '❌'} Property '{prop_key}' {'enabled' if checked else 'disabled'} for layer: {layer_id}")
    
    def _merge_visible_layers(self, target_layer_id: str):
        """Merge all visible layers into the target layer"""
        # Collect visible layer IDs (excluding the target)
        source_layer_ids = []
        for layer_id, layer_data in self.layers_data.items():
            if layer_data.visible and layer_id != target_layer_id:
                source_layer_ids.append(layer_id)
        
        if source_layer_ids:
            # Emit signal to request merge
            self.layers_merge_requested.emit(target_layer_id, source_layer_ids)
            print(f"🔀 Merging {len(source_layer_ids)} visible layers into layer: {target_layer_id}")
    
    def _request_remove_background(self, layer_id: str):
        """Request background removal for a layer"""
        self.layer_remove_bg_requested.emit(layer_id)
        print(f"🗑️ Background removal requested for layer: {layer_id}")
    
    def _request_save_variation(self, layer_id: str):
        """Request saving layer as character variation"""
        self.layer_save_variation_requested.emit(layer_id)
        print(f"💾 Save as variation requested for layer: {layer_id}")
    
    def _request_set_background_color(self, layer_id: str):
        """Request setting background color for a layer"""
        # Get current color if exists (default to #777777)
        layer_data = self.layers_data.get(layer_id)
        current_color = QColor("#DDDDDD")  # Default color
        
        if layer_data and hasattr(layer_data, 'background_color') and layer_data.background_color:
            current_color = QColor(layer_data.background_color)
        
        # Show color dialog
        color = QColorDialog.getColor(
            current_color, 
            self, 
            "배경색 선택",
            QColorDialog.ColorDialogOption.ShowAlphaChannel
        )
        
        if color.isValid():
            # Emit signal with layer_id and hex color
            color_hex = color.name(QColor.NameFormat.HexArgb)
            self.layer_set_background_color.emit(layer_id, color_hex)
            print(f"🎨 Background color set for layer {layer_id}: {color_hex}")
    
    def _request_remove_background_color(self, layer_id: str):
        """Request removing background color from a layer"""
        self.layer_remove_background_color.emit(layer_id)
        print(f"🚫 Background color removal requested for layer: {layer_id}")