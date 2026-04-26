from PyQt6.QtWidgets import QTabWidget

from ui.gui_helpers import (
    configure_dense_tab_widget,
    create_flat_action_button,
    dark_menu_stylesheet,
)


def test_dark_menu_stylesheet_contains_menu_selectors():
    style = dark_menu_stylesheet()

    assert "QMenu" in style
    assert "QMenu::item:selected" in style


def test_create_flat_action_button_sets_size_and_tooltip(qtbot):
    button = create_flat_action_button("T", "tooltip", width=32, height=24)
    qtbot.addWidget(button)

    assert button.text() == "T"
    assert button.toolTip() == "tooltip"
    assert button.width() == button.minimumWidth()
    assert button.height() == button.minimumHeight()


def test_configure_dense_tab_widget(qtbot):
    tab_widget = QTabWidget()
    qtbot.addWidget(tab_widget)

    configure_dense_tab_widget(tab_widget)

    assert tab_widget.documentMode() is True
    assert tab_widget.tabBar().expanding() is False
