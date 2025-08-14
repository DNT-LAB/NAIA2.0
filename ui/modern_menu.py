"""
Modern styled QMenu helper for NAIA 2.0
Provides a simple way to apply modern menu styling to TextEdit widgets.
"""

from PyQt6.QtWidgets import QTextEdit, QPlainTextEdit
from PyQt6.QtCore import Qt
from ui.scaling_manager import get_scaled_font_size, get_scaled_size


def setModernStyle(text_edit_widget):
    """
    Apply modern context menu styling to a QTextEdit or QPlainTextEdit widget.
    Creates a white background menu with black text and rounded corners.
    
    Usage:
        from ui.modern_menu import setModernStyle
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
        # Create standard context menu
        menu = text_edit_widget.createStandardContextMenu()
        if not menu:
            return
        
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
        from ui.modern_menu import setDarkStyle
        setDarkStyle(self.my_textedit)
    
    Args:
        text_edit_widget: QTextEdit or QPlainTextEdit instance
    """
    if not isinstance(text_edit_widget, (QTextEdit, QPlainTextEdit)):
        print(f"⚠️ ModernMenu: {type(text_edit_widget)} is not a TextEdit widget")
        return
    
    from ui.theme import DARK_COLORS
    
    # Set custom context menu policy
    text_edit_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    
    # Connect to custom menu handler
    def show_dark_context_menu(pos):
        # Create standard context menu
        menu = text_edit_widget.createStandardContextMenu()
        if not menu:
            return
        
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
        
        from ui.theme import DARK_COLORS
        
        # Set custom context menu policy
        text_edit_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        
        # Connect to custom menu handler
        def show_dark_context_menu(pos):
            # Create standard context menu
            menu = text_edit_widget.createStandardContextMenu()
            if not menu:
                return
            
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