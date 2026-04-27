from __future__ import annotations

import atexit

from PyQt6.QtCore import QModelIndex, QObject, QTimer, Qt, QItemSelectionModel
from PyQt6.QtWidgets import QAbstractItemView, QApplication, QComboBox, QListView, QWidget


class ComboBoxPopupListView(QListView):
    """QComboBox popup view that repaints hover state reliably on Windows."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        viewport = self.viewport()
        if viewport is not None:
            viewport.setMouseTracking(True)
            viewport.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        self._sync_hover_selection(self.indexAt(event.position().toPoint()))

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        QTimer.singleShot(0, self._clear_popup_selection)

    def leaveEvent(self, event):
        self._clear_popup_selection()
        super().leaveEvent(event)

    def hideEvent(self, event):
        self._clear_popup_selection()
        super().hideEvent(event)

    def focusOutEvent(self, event):
        self._clear_popup_selection()
        super().focusOutEvent(event)

    def _sync_hover_selection(self, index: QModelIndex):
        if not index.isValid():
            self._clear_popup_selection()
            return

        selection_model = self.selectionModel()
        if selection_model is not None:
            selection_model.select(
                index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )

        self.setCurrentIndex(index)
        self.viewport().update()

    def _clear_popup_selection(self):
        selection_model = self.selectionModel()
        if selection_model is not None:
            selection_model.clearSelection()

        self.setCurrentIndex(QModelIndex())
        self.viewport().update()


class ComboBoxPopupGuard(QObject):
    """Install hover-safe popup views on every QComboBox in the app."""

    _COMBO_CONFIGURED = "_naia_combo_popup_guard_configured"

    def __init__(self, app: QApplication):
        super().__init__(app)
        self._app = app
        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(700)
        self._scan_timer.timeout.connect(self.configure_existing_widgets)
        self._focus_connected = False

    def start(self):
        self.configure_existing_widgets()
        if not self._scan_timer.isActive():
            self._scan_timer.start()
        if not self._focus_connected:
            self._app.focusChanged.connect(self._on_focus_changed)
            self._focus_connected = True

    def cleanup(self):
        if self._scan_timer.isActive():
            self._scan_timer.stop()
        if self._focus_connected:
            try:
                self._app.focusChanged.disconnect(self._on_focus_changed)
            except (RuntimeError, TypeError):
                pass
            self._focus_connected = False

    def configure_existing_widgets(self):
        for widget in self._app.allWidgets():
            if isinstance(widget, QComboBox):
                try:
                    self.configure_combo(widget)
                except RuntimeError:
                    pass

    def configure_combo(self, combo: QComboBox):
        if combo.property(self._COMBO_CONFIGURED) and isinstance(combo.view(), ComboBoxPopupListView):
            self._configure_view(combo.view())
            return

        current_view = combo.view()
        if isinstance(current_view, ComboBoxPopupListView):
            popup_view = current_view
        else:
            popup_view = ComboBoxPopupListView(combo)
            combo.setView(popup_view)

        combo.setProperty(self._COMBO_CONFIGURED, True)
        combo.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._configure_view(popup_view)

    def _configure_view(self, view: QAbstractItemView):
        view.setMouseTracking(True)
        view.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        viewport = view.viewport()
        if viewport is not None:
            viewport.setMouseTracking(True)
            viewport.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def _on_focus_changed(self, _old: QWidget | None, now: QWidget | None):
        combo = self._combo_for_widget(now)
        if combo is not None:
            self.configure_combo(combo)

    @staticmethod
    def _combo_for_widget(widget: QWidget | None) -> QComboBox | None:
        while widget is not None:
            if isinstance(widget, QComboBox):
                return widget
            parent = widget.parent()
            widget = parent if isinstance(parent, QWidget) else None
        return None


def install_combobox_popup_guard(app: QApplication | None = None) -> ComboBoxPopupGuard | None:
    app = app or QApplication.instance()
    if app is None:
        return None

    existing = getattr(app, "_naia_combobox_popup_guard", None)
    if existing is not None:
        existing.start()
        return existing

    guard = ComboBoxPopupGuard(app)
    app._naia_combobox_popup_guard = guard
    guard.start()
    app.aboutToQuit.connect(guard.cleanup)
    atexit.register(guard.cleanup)
    return guard
