"""
Modern styled QMenu helper for NAIA 2.0
Provides a simple way to apply modern menu styling to TextEdit widgets.
"""

from PyQt6.QtWidgets import QTextEdit, QPlainTextEdit, QMenu, QWidgetAction, QWidget, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QTextCursor
from legacy_desktop.ui.scaling_manager import get_scaled_font_size, get_scaled_size
import pandas as pd
import os
import re

# Global KR_tags DataFrame cache
_kr_tags_df = None

def _load_kr_tags():
    """Load KR_tags.parquet file and cache it globally."""
    global _kr_tags_df
    if _kr_tags_df is not None:
        return _kr_tags_df
    
    filepath = 'data/KR_tags.parquet'
    if os.path.exists(filepath):
        try:
            print(f"🔍 ModernMenu: Loading '{filepath}'...")
            _kr_tags_df = pd.read_parquet(filepath)
            print(f"✅ ModernMenu: '{filepath}' loaded. {len(_kr_tags_df):,} tags.")
            return _kr_tags_df
        except Exception as e:
            print(f"❌ ModernMenu: Failed to load '{filepath}': {e}")
    else:
        print(f"⚠️ ModernMenu: '{filepath}' not found.")
    
    _kr_tags_df = pd.DataFrame()  # Empty DataFrame on failure
    return _kr_tags_df

def _get_tag_at_cursor(text_edit_widget, cursor):
    """Extract the tag at cursor position."""
    text = text_edit_widget.toPlainText()
    pos = cursor.position()
    
    # Find comma boundaries
    start_pos = text.rfind(',', 0, pos)
    start_pos = 0 if start_pos == -1 else start_pos + 1
    
    end_pos = text.find(',', pos)
    if end_pos == -1:
        end_pos = len(text)
    
    # Extract and clean the tag
    tag = text[start_pos:end_pos].strip()
    
    # Remove brackets and weights
    tag = re.sub(r'^[\{\[\(]+', '', tag)
    tag = re.sub(r'[\}\]\)]+$', '', tag)
    tag = re.sub(r':+[\d.]+$', '', tag)  # Remove :weight
    
    return tag, start_pos, end_pos

def setModernStyle(text_edit_widget):
    """
    Apply modern context menu styling to a QTextEdit or QPlainTextEdit widget.
    Creates a white background menu with black text and rounded corners.
    
    Usage:
        from legacy_desktop.ui.modern_menu import setModernStyle
        setModernStyle(self.my_textedit)
    
    Args:
        text_edit_widget: QTextEdit or QPlainTextEdit instance
    """
    if not isinstance(text_edit_widget, (QTextEdit, QPlainTextEdit)):
        print(f"⚠️ ModernMenu: {type(text_edit_widget)} is not a TextEdit widget")
        return
    
    # Set custom context menu policy
    text_edit_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    
    # Connect to custom menu handler
    def show_modern_context_menu(pos):
        # Create new menu instead of standard menu for better control
        menu = QMenu(text_edit_widget)
        
        # Helper function to create info action
        def create_info_action(text, font_size, is_bold=False, word_wrap=False):
            widget_action = QWidgetAction(menu)
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(8, 4, 8, 4)
            label = QLabel(str(text))
            style = f"font-size: {font_size}px; color: #000000; border: none; background: transparent;"
            if is_bold: 
                style += " font-weight: 600;"
            label.setStyleSheet(style)
            if word_wrap:
                label.setWordWrap(True)
                label.setMinimumWidth(300)
            layout.addWidget(label)
            widget_action.setDefaultWidget(widget)
            widget_action.setEnabled(False)
            return widget_action
        
        # Check for selected text and InstantWildcardModule
        cursor = text_edit_widget.textCursor()
        selected_text = cursor.selectedText().strip()
        
        if selected_text:
            # Try to find InstantWildcardModule
            instant_wildcard_module = None
            try:
                # Get app context from widget hierarchy
                widget = text_edit_widget
                while widget and not hasattr(widget, 'app_context'):
                    widget = widget.parent()
                
                if widget and hasattr(widget, 'app_context'):
                    app_context = widget.app_context
                    if hasattr(app_context, 'main_window'):
                        mw = app_context.main_window
                        if hasattr(mw, 'middle_section_controller'):
                            instant_wildcard_module = mw.middle_section_controller.get_module_instance("InstantWildcardModule")
            except Exception:
                pass  # Silently fail if module not found
            
            # Add instant wildcard action if module is available
            if instant_wildcard_module:
                add_action = QAction("➕ 인스턴트 와일드카드 추가", menu)
                add_action.triggered.connect(lambda: instant_wildcard_module.add_from_selection(selected_text))
                menu.addAction(add_action)
                menu.addSeparator()
        
        # Get tag at cursor position and load KR_tags data
        cursor_at_pos = text_edit_widget.cursorForPosition(pos)
        tag_under_cursor, start_pos, end_pos = _get_tag_at_cursor(text_edit_widget, cursor_at_pos)
        
        # Load KR_tags DataFrame if needed
        kr_tags_df = _load_kr_tags()
        
        # Add tag information if found
        if not kr_tags_df.empty and tag_under_cursor:
            matching_rows = kr_tags_df[kr_tags_df['tag'] == tag_under_cursor]
            
            if not matching_rows.empty:
                data = matching_rows.iloc[0]
                
                # Title: Tag + Count
                title_action = QWidgetAction(menu)
                title_widget = QWidget()
                title_layout = QHBoxLayout(title_widget)
                title_layout.setContentsMargins(8, 4, 8, 4)
                
                tag_label = QLabel(data.get('tag', ''))
                tag_label.setStyleSheet(f"font-size: {get_scaled_font_size(24)}px; font-weight: 600; color: #000000; border: none; background: transparent;")
                
                count_val = data.get('count', 0)
                count_label = QLabel(f"{count_val:,}" if pd.notna(count_val) else "")
                count_label.setStyleSheet(f"font-size: {get_scaled_font_size(15)}px; color: #111111; border: none; background: transparent;")
                
                title_layout.addWidget(tag_label)
                title_layout.addStretch()
                title_layout.addWidget(count_label)
                title_action.setDefaultWidget(title_widget)
                title_action.setEnabled(False)
                menu.addAction(title_action)
                menu.addSeparator()
                
                # Category
                category_text = data.get('category')
                if pd.notna(category_text) and category_text:
                    menu.addAction(create_info_action(f"Category: {category_text}", get_scaled_font_size(18)))
                
                # Description
                desc_text = data.get('desc')
                if pd.notna(desc_text) and desc_text:
                    menu.addAction(create_info_action(desc_text, get_scaled_font_size(15), word_wrap=True))
                
                # Keywords
                keywords_text = data.get('keywords')
                if pd.notna(keywords_text) and keywords_text:
                    menu.addAction(create_info_action(f"Keywords: {keywords_text}", get_scaled_font_size(15)))
                
                menu.addSeparator()
        
        # Add standard context menu actions
        standard_menu = text_edit_widget.createStandardContextMenu()
        if standard_menu:
            menu.addActions(standard_menu.actions())
        
        # Get scaled sizes for responsive UI
        border_radius = get_scaled_size(8)
        padding = get_scaled_size(6)
        item_padding_v = get_scaled_size(10)
        item_padding_h = get_scaled_size(24)
        font_size = get_scaled_font_size(16)
        separator_margin = get_scaled_size(4)
        
        # Apply modern light style
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: #FFFFFF;
                color: #000000;
                border: 1px solid #D0D0D0;
                border-radius: {border_radius}px;
                padding: {padding}px;
                font-size: {font_size}px;
                font-family: "Segoe UI", "맑은 고딕", "Apple SD Gothic Neo", sans-serif;
            }}
            
            QMenu::item {{
                padding: {item_padding_v}px {item_padding_h}px;
                border-radius: {get_scaled_size(4)}px;
                margin: {get_scaled_size(2)}px {get_scaled_size(4)}px;
                background-color: transparent;
            }}
            
            QMenu::item:selected {{
                background-color: #E8F0FE;
                color: #1A73E8;
            }}
            
            QMenu::item:disabled {{
                color: #999999;
            }}
            
            QMenu::separator {{
                height: 1px;
                background-color: #E0E0E0;
                margin: {separator_margin}px {item_padding_h}px;
            }}
            
            QMenu::indicator {{
                width: {get_scaled_size(18)}px;
                height: {get_scaled_size(18)}px;
            }}
            
            QMenu::indicator:checked {{
                image: none;
                background-color: #1A73E8;
                border-radius: {get_scaled_size(3)}px;
            }}
            
            QMenu::icon {{
                padding-left: {get_scaled_size(8)}px;
            }}
        """)
        
        # Show menu at cursor position
        menu.exec(text_edit_widget.mapToGlobal(pos))
    
    # Connect the custom menu handler
    text_edit_widget.customContextMenuRequested.connect(show_modern_context_menu)
    
    print(f"✅ ModernMenu: Applied modern style to {text_edit_widget.__class__.__name__}")


def setDarkStyle(text_edit_widget):
    """
    Apply dark theme context menu styling to a QTextEdit or QPlainTextEdit widget.
    
    Usage:
        from legacy_desktop.ui.modern_menu import setDarkStyle
        setDarkStyle(self.my_textedit)
    
    Args:
        text_edit_widget: QTextEdit or QPlainTextEdit instance
    """
    if not isinstance(text_edit_widget, (QTextEdit, QPlainTextEdit)):
        print(f"⚠️ ModernMenu: {type(text_edit_widget)} is not a TextEdit widget")
        return
    
    from legacy_desktop.ui.theme import DARK_COLORS
    
    # Set custom context menu policy
    text_edit_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    
    # Connect to custom menu handler
    def show_dark_context_menu(pos):
        # Create new menu instead of standard menu for better control
        menu = QMenu(text_edit_widget)
        
        # Helper function to create info action (dark theme)
        def create_info_action(text, font_size, is_bold=False, word_wrap=False):
            widget_action = QWidgetAction(menu)
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(8, 4, 8, 4)
            label = QLabel(str(text))
            style = f"font-size: {font_size}px; color: #E0E0E0; border: none; background: transparent;"
            if is_bold: 
                style += " font-weight: 600;"
            label.setStyleSheet(style)
            if word_wrap:
                label.setWordWrap(True)
                label.setMinimumWidth(300)
            layout.addWidget(label)
            widget_action.setDefaultWidget(widget)
            widget_action.setEnabled(False)
            return widget_action
        
        # Check for selected text and InstantWildcardModule
        cursor = text_edit_widget.textCursor()
        selected_text = cursor.selectedText().strip()
        
        if selected_text:
            # Try to find InstantWildcardModule
            instant_wildcard_module = None
            try:
                # Get app context from widget hierarchy
                widget = text_edit_widget
                while widget and not hasattr(widget, 'app_context'):
                    widget = widget.parent()
                
                if widget and hasattr(widget, 'app_context'):
                    app_context = widget.app_context
                    if hasattr(app_context, 'main_window'):
                        mw = app_context.main_window
                        if hasattr(mw, 'middle_section_controller'):
                            instant_wildcard_module = mw.middle_section_controller.get_module_instance("InstantWildcardModule")
            except Exception:
                pass  # Silently fail if module not found
            
            # Add instant wildcard action if module is available
            if instant_wildcard_module:
                add_action = QAction("➕ 인스턴트 와일드카드 추가", menu)
                add_action.triggered.connect(lambda: instant_wildcard_module.add_from_selection(selected_text))
                menu.addAction(add_action)
                menu.addSeparator()
        
        # Get tag at cursor position and load KR_tags data
        cursor_at_pos = text_edit_widget.cursorForPosition(pos)
        tag_under_cursor, start_pos, end_pos = _get_tag_at_cursor(text_edit_widget, cursor_at_pos)
        
        # Load KR_tags DataFrame if needed
        kr_tags_df = _load_kr_tags()
        
        # Add tag information if found
        if not kr_tags_df.empty and tag_under_cursor:
            matching_rows = kr_tags_df[kr_tags_df['tag'] == tag_under_cursor]
            
            if not matching_rows.empty:
                data = matching_rows.iloc[0]
                
                # Title: Tag + Count (dark theme colors)
                title_action = QWidgetAction(menu)
                title_widget = QWidget()
                title_layout = QHBoxLayout(title_widget)
                title_layout.setContentsMargins(8, 4, 8, 4)
                
                tag_label = QLabel(data.get('tag', ''))
                tag_label.setStyleSheet(f"font-size: {get_scaled_font_size(24)}px; font-weight: 600; color: #FFFFFF; border: none; background: transparent;")
                
                count_val = data.get('count', 0)
                count_label = QLabel(f"{count_val:,}" if pd.notna(count_val) else "")
                count_label.setStyleSheet(f"font-size: {get_scaled_font_size(15)}px; color: #B0B0B0; border: none; background: transparent;")
                
                title_layout.addWidget(tag_label)
                title_layout.addStretch()
                title_layout.addWidget(count_label)
                title_action.setDefaultWidget(title_widget)
                title_action.setEnabled(False)
                menu.addAction(title_action)
                menu.addSeparator()
                
                # Category
                category_text = data.get('category')
                if pd.notna(category_text) and category_text:
                    menu.addAction(create_info_action(f"Category: {category_text}", get_scaled_font_size(18)))
                
                # Description
                desc_text = data.get('desc')
                if pd.notna(desc_text) and desc_text:
                    menu.addAction(create_info_action(desc_text, get_scaled_font_size(15), word_wrap=True))
                
                # Keywords
                keywords_text = data.get('keywords')
                if pd.notna(keywords_text) and keywords_text:
                    menu.addAction(create_info_action(f"Keywords: {keywords_text}", get_scaled_font_size(15)))
                
                menu.addSeparator()
        
        # Add standard context menu actions
        standard_menu = text_edit_widget.createStandardContextMenu()
        if standard_menu:
            menu.addActions(standard_menu.actions())
        
        # Get scaled sizes for responsive UI
        border_radius = get_scaled_size(8)
        padding = get_scaled_size(6)
        item_padding_v = get_scaled_size(10)
        item_padding_h = get_scaled_size(24)
        font_size = get_scaled_font_size(16)
        separator_margin = get_scaled_size(4)
        
        # Apply dark style
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {border_radius}px;
                padding: {padding}px;
                font-size: {font_size}px;
                font-family: "Segoe UI", "맑은 고딕", "Apple SD Gothic Neo", sans-serif;
            }}
            
            QMenu::item {{
                padding: {item_padding_v}px {item_padding_h}px;
                border-radius: {get_scaled_size(4)}px;
                margin: {get_scaled_size(2)}px {get_scaled_size(4)}px;
                background-color: transparent;
            }}
            
            QMenu::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
                color: {DARK_COLORS['text_primary']};
            }}
            
            QMenu::item:disabled {{
                color: {DARK_COLORS['text_tertiary']};
            }}
            
            QMenu::separator {{
                height: 1px;
                background-color: {DARK_COLORS['border']};
                margin: {separator_margin}px {item_padding_h}px;
            }}
            
            QMenu::indicator {{
                width: {get_scaled_size(18)}px;
                height: {get_scaled_size(18)}px;
            }}
            
            QMenu::indicator:checked {{
                image: none;
                background-color: {DARK_COLORS['accent_blue']};
                border-radius: {get_scaled_size(3)}px;
            }}
            
            QMenu::icon {{
                padding-left: {get_scaled_size(8)}px;
            }}
        """)
        
        # Show menu at cursor position
        menu.exec(text_edit_widget.mapToGlobal(pos))
    
    # Connect the custom menu handler
    text_edit_widget.customContextMenuRequested.connect(show_dark_context_menu)
    
    print(f"✅ ModernMenu: Applied dark style to {text_edit_widget.__class__.__name__}")


# Keep the class for backward compatibility


class ModernMenu:
    """
    Helper class to apply modern menu styling to TextEdit widgets.
    
    Usage:
        ModernMenu.setModernStyle(self.my_textedit)
    """
    
    @staticmethod
    def setModernStyle(text_edit_widget):
        """
        Apply modern context menu styling to a QTextEdit or QPlainTextEdit widget.
        Creates a white background menu with black text and rounded corners.
        
        Args:
            text_edit_widget: QTextEdit or QPlainTextEdit instance
        """
        if not isinstance(text_edit_widget, (QTextEdit, QPlainTextEdit)):
            print(f"⚠️ ModernMenu: {type(text_edit_widget)} is not a TextEdit widget")
            return
        
        # Set custom context menu policy
        text_edit_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        
        # Connect to custom menu handler
        def show_modern_context_menu(pos):
            # Create standard context menu
            menu = text_edit_widget.createStandardContextMenu()
            if not menu:
                return
            
            # Check for selected text and InstantWildcardModule
            cursor = text_edit_widget.textCursor()
            selected_text = cursor.selectedText().strip()
            
            if selected_text:
                # Try to find InstantWildcardModule
                instant_wildcard_module = None
                try:
                    # Get app context from widget hierarchy
                    widget = text_edit_widget
                    while widget and not hasattr(widget, 'app_context'):
                        widget = widget.parent()
                    
                    if widget and hasattr(widget, 'app_context'):
                        app_context = widget.app_context
                        if hasattr(app_context, 'main_window'):
                            mw = app_context.main_window
                            if hasattr(mw, 'middle_section_controller'):
                                instant_wildcard_module = mw.middle_section_controller.get_module_instance("InstantWildcardModule")
                except Exception:
                    pass  # Silently fail if module not found
                
                # Add instant wildcard action if module is available
                if instant_wildcard_module:
                    # Insert at the beginning of menu
                    actions = menu.actions()
                    add_action = QAction("➕ 인스턴트 와일드카드 추가", menu)
                    add_action.triggered.connect(lambda: instant_wildcard_module.add_from_selection(selected_text))
                    
                    if actions:
                        menu.insertAction(actions[0], add_action)
                        menu.insertSeparator(actions[0])
                    else:
                        menu.addAction(add_action)
                        menu.addSeparator()
            
            # Get scaled sizes for responsive UI
            border_radius = get_scaled_size(8)
            padding = get_scaled_size(6)
            item_padding_v = get_scaled_size(10)
            item_padding_h = get_scaled_size(24)
            font_size = get_scaled_font_size(16)
            separator_margin = get_scaled_size(4)
            
            # Apply modern light style
            menu.setStyleSheet(f"""
                QMenu {{
                    background-color: #FFFFFF;
                    color: #000000;
                    border: 1px solid #D0D0D0;
                    border-radius: {border_radius}px;
                    padding: {padding}px;
                    font-size: {font_size}px;
                    font-family: "Segoe UI", "맑은 고딕", "Apple SD Gothic Neo", sans-serif;
                }}
                
                QMenu::item {{
                    padding: {item_padding_v}px {item_padding_h}px;
                    border-radius: {get_scaled_size(4)}px;
                    margin: {get_scaled_size(2)}px {get_scaled_size(4)}px;
                    background-color: transparent;
                }}
                
                QMenu::item:selected {{
                    background-color: #E8F0FE;
                    color: #1A73E8;
                }}
                
                QMenu::item:disabled {{
                    color: #999999;
                }}
                
                QMenu::separator {{
                    height: 1px;
                    background-color: #E0E0E0;
                    margin: {separator_margin}px {item_padding_h}px;
                }}
                
                QMenu::indicator {{
                    width: {get_scaled_size(18)}px;
                    height: {get_scaled_size(18)}px;
                }}
                
                QMenu::indicator:checked {{
                    image: none;
                    background-color: #1A73E8;
                    border-radius: {get_scaled_size(3)}px;
                }}
                
                QMenu::icon {{
                    padding-left: {get_scaled_size(8)}px;
                }}
            """)
            
            # Show menu at cursor position
            menu.exec(text_edit_widget.mapToGlobal(pos))
        
        # Connect the custom menu handler
        text_edit_widget.customContextMenuRequested.connect(show_modern_context_menu)
        
        print(f"✅ ModernMenu: Applied modern style to {text_edit_widget.__class__.__name__}")
    
    @staticmethod
    def setDarkStyle(text_edit_widget):
        """
        Apply dark theme context menu styling to a QTextEdit or QPlainTextEdit widget.
        
        Args:
            text_edit_widget: QTextEdit or QPlainTextEdit instance
        """
        if not isinstance(text_edit_widget, (QTextEdit, QPlainTextEdit)):
            print(f"⚠️ ModernMenu: {type(text_edit_widget)} is not a TextEdit widget")
            return
        
        from legacy_desktop.ui.theme import DARK_COLORS
        
        # Set custom context menu policy
        text_edit_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        
        # Connect to custom menu handler
        def show_dark_context_menu(pos):
            # Create standard context menu
            menu = text_edit_widget.createStandardContextMenu()
            if not menu:
                return
            
            # Check for selected text and InstantWildcardModule
            cursor = text_edit_widget.textCursor()
            selected_text = cursor.selectedText().strip()
            
            if selected_text:
                # Try to find InstantWildcardModule
                instant_wildcard_module = None
                try:
                    # Get app context from widget hierarchy
                    widget = text_edit_widget
                    while widget and not hasattr(widget, 'app_context'):
                        widget = widget.parent()
                    
                    if widget and hasattr(widget, 'app_context'):
                        app_context = widget.app_context
                        if hasattr(app_context, 'main_window'):
                            mw = app_context.main_window
                            if hasattr(mw, 'middle_section_controller'):
                                instant_wildcard_module = mw.middle_section_controller.get_module_instance("InstantWildcardModule")
                except Exception:
                    pass  # Silently fail if module not found
                
                # Add instant wildcard action if module is available
                if instant_wildcard_module:
                    # Insert at the beginning of menu
                    actions = menu.actions()
                    add_action = QAction("➕ 인스턴트 와일드카드 추가", menu)
                    add_action.triggered.connect(lambda: instant_wildcard_module.add_from_selection(selected_text))
                    
                    if actions:
                        menu.insertAction(actions[0], add_action)
                        menu.insertSeparator(actions[0])
                    else:
                        menu.addAction(add_action)
                        menu.addSeparator()
            
            # Get scaled sizes for responsive UI
            border_radius = get_scaled_size(8)
            padding = get_scaled_size(6)
            item_padding_v = get_scaled_size(10)
            item_padding_h = get_scaled_size(24)
            font_size = get_scaled_font_size(16)
            separator_margin = get_scaled_size(4)
            
            # Apply dark style
            menu.setStyleSheet(f"""
                QMenu {{
                    background-color: {DARK_COLORS['bg_tertiary']};
                    color: {DARK_COLORS['text_primary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: {border_radius}px;
                    padding: {padding}px;
                    font-size: {font_size}px;
                    font-family: "Segoe UI", "맑은 고딕", "Apple SD Gothic Neo", sans-serif;
                }}
                
                QMenu::item {{
                    padding: {item_padding_v}px {item_padding_h}px;
                    border-radius: {get_scaled_size(4)}px;
                    margin: {get_scaled_size(2)}px {get_scaled_size(4)}px;
                    background-color: transparent;
                }}
                
                QMenu::item:selected {{
                    background-color: {DARK_COLORS['accent_blue']};
                    color: {DARK_COLORS['text_primary']};
                }}
                
                QMenu::item:disabled {{
                    color: {DARK_COLORS['text_tertiary']};
                }}
                
                QMenu::separator {{
                    height: 1px;
                    background-color: {DARK_COLORS['border']};
                    margin: {separator_margin}px {item_padding_h}px;
                }}
                
                QMenu::indicator {{
                    width: {get_scaled_size(18)}px;
                    height: {get_scaled_size(18)}px;
                }}
                
                QMenu::indicator:checked {{
                    image: none;
                    background-color: {DARK_COLORS['accent_blue']};
                    border-radius: {get_scaled_size(3)}px;
                }}
                
                QMenu::icon {{
                    padding-left: {get_scaled_size(8)}px;
                }}
            """)
            
            # Show menu at cursor position
            menu.exec(text_edit_widget.mapToGlobal(pos))
        
        # Connect the custom menu handler
        text_edit_widget.customContextMenuRequested.connect(show_dark_context_menu)
        
        print(f"✅ ModernMenu: Applied dark style to {text_edit_widget.__class__.__name__}")