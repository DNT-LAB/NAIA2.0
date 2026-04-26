"""Small reusable helpers for dense PyQt GUI surfaces."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPushButton, QTabWidget

from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.theme import DARK_COLORS


def dark_menu_stylesheet() -> str:
    """Shared dark popup menu stylesheet."""
    radius = get_scaled_size(4)
    padding_y = get_scaled_size(8)
    padding_x = get_scaled_size(20)
    return f"""
        QMenu {{
            background-color: {DARK_COLORS['bg_tertiary']};
            color: {DARK_COLORS['text_primary']};
            border: 1px solid {DARK_COLORS['border']};
            border-radius: {radius}px;
            padding: {get_scaled_size(5)}px;
        }}
        QMenu::item {{
            padding: {padding_y}px {padding_x}px;
            border-radius: {radius}px;
        }}
        QMenu::item:selected {{
            background-color: {DARK_COLORS['accent_blue']};
        }}
    """


def flat_action_button_stylesheet(font_size: int = 16) -> str:
    """Transparent toolbar-style button used in tab corner widgets."""
    radius = get_scaled_size(4)
    return f"""
        QPushButton {{
            background-color: transparent;
            border: none;
            color: {DARK_COLORS['text_primary']};
            font-size: {get_scaled_font_size(font_size)}px;
            padding: 0px;
        }}
        QPushButton:hover {{
            background-color: {DARK_COLORS['bg_tertiary']};
            border-radius: {radius}px;
        }}
        QPushButton::menu-indicator {{
            width: 0px;
        }}
    """


def create_flat_action_button(
    text: str,
    tooltip: str,
    *,
    width: int = 45,
    height: int = 55,
    font_size: int = 16,
    parent=None,
) -> QPushButton:
    """Create a fixed-size flat button for dense toolbar/corner areas."""
    button = QPushButton(text, parent)
    button.setFixedSize(get_scaled_size(width), get_scaled_size(height))
    button.setToolTip(tooltip)
    button.setStyleSheet(flat_action_button_stylesheet(font_size))
    return button


def configure_dense_tab_widget(tab_widget: QTabWidget) -> None:
    """Configure tab widgets to keep crowded tab bars usable."""
    tab_widget.setDocumentMode(True)
    if hasattr(tab_widget, "setUsesScrollButtons"):
        tab_widget.setUsesScrollButtons(True)
    if hasattr(tab_widget, "setElideMode"):
        tab_widget.setElideMode(Qt.TextElideMode.ElideRight)

    tab_bar = tab_widget.tabBar()
    tab_bar.setExpanding(False)
    if hasattr(tab_bar, "setUsesScrollButtons"):
        tab_bar.setUsesScrollButtons(True)
