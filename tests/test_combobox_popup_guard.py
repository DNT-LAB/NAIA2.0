import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QAbstractItemView, QComboBox

from ui.combobox_popup_guard import ComboBoxPopupListView, install_combobox_popup_guard


def test_combobox_popup_guard_is_idempotent_and_configures_existing_combo():
    app = QApplication.instance() or QApplication([])
    combo = QComboBox()
    combo.addItems(["one", "two"])

    guard = install_combobox_popup_guard(app)
    assert install_combobox_popup_guard(app) is guard

    view = combo.view()
    assert combo.property("_naia_combo_popup_guard_configured") is True
    assert isinstance(view, ComboBoxPopupListView)
    assert view.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection
    assert view.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows
    assert view.hasMouseTracking() is True
    assert view.viewport().hasMouseTracking() is True


def test_combobox_popup_guard_configures_new_combo_on_rescan():
    app = QApplication.instance() or QApplication([])
    guard = install_combobox_popup_guard(app)

    combo = QComboBox()
    combo.addItems(["alpha", "beta"])
    guard.configure_existing_widgets()

    assert combo.property("_naia_combo_popup_guard_configured") is True
    assert isinstance(combo.view(), ComboBoxPopupListView)
