"""QWebEngine host for the NAIA Remote Web UI.

This window is the first Desktop Web Shell path: PyQt keeps the application
backend alive, while QWebEngine renders the existing Remote Web client.
"""

from __future__ import annotations

from PyQt6.QtCore import QTimer, QUrl, Qt
from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

from core.web_shell_config import (
    DEFAULT_WEB_SHELL_HOST,
    DEFAULT_WEB_SHELL_PORT,
    build_web_shell_url,
    normalize_web_shell_port,
)


class _WebShellPage(QWebEnginePage):
    """Filter known Chromium noise without hiding real client errors."""

    _NOISE_FRAGMENTS = (
        "Permissions policy violation",
        "TrustedHTML",
        "TrustedScript",
        "TrustedScriptURL",
        "Form submission canceled",
        "Failed to create WebGPU",
    )

    def __init__(self, parent=None, popup_factory=None):
        super().__init__(parent)
        self._popup_factory = popup_factory

    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        if any(fragment in message for fragment in self._NOISE_FRAGMENTS):
            return
        super().javaScriptConsoleMessage(level, message, line_number, source_id)

    def createWindow(self, _window_type):
        if self._popup_factory is None:
            return super().createWindow(_window_type)
        return self._popup_factory()


class _WebShellPopupWindow(QMainWindow):
    """Detached QWebEngine window opened by Web Shell window.open()."""

    def __init__(self, owner: "WebWrapperWindow"):
        super().__init__(owner)
        self._owner = owner
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("NAIA Web Shell - Detached")
        self.setMinimumSize(720, 520)
        self.resize(1180, 860)

        self._view = QWebEngineView(self)
        self._page = _WebShellPage(self, popup_factory=owner._create_popup_page)
        self._view.setPage(self._page)
        self._configure_settings(self._view.settings())
        self._page.titleChanged.connect(self._on_title_changed)
        self.setCentralWidget(self._view)

    @staticmethod
    def _configure_settings(settings):
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, True)

    def _on_title_changed(self, title: str):
        if title:
            self.setWindowTitle(title)

    def closeEvent(self, event):
        owner = getattr(self, "_owner", None)
        if owner is not None:
            owner._popup_windows.discard(self)
        super().closeEvent(event)


class WebWrapperWindow(QMainWindow):
    """Render the Remote Web Session inside a desktop QWebEngine shell."""

    def __init__(
        self,
        app_context,
        *,
        host: str = DEFAULT_WEB_SHELL_HOST,
        port: int = DEFAULT_WEB_SHELL_PORT,
        stop_server_on_close: bool = True,
        quit_on_close: bool = True,
    ):
        super().__init__()
        self.app_context = app_context
        self.host = host or DEFAULT_WEB_SHELL_HOST
        self.port = normalize_web_shell_port(port)
        self.stop_server_on_close = stop_server_on_close
        self.quit_on_close = quit_on_close
        self._server_started = False
        self._closed = False
        self._popup_windows = set()

        self.setWindowTitle("NAIA Web Shell")
        self.setMinimumSize(1100, 760)
        self.resize(1440, 920)

        self._setup_webview()
        self._start_remote_backend()
        self._load_shell()

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._stop_remote_backend)

    def _setup_webview(self):
        self._view = QWebEngineView(self)
        self._page = _WebShellPage(self, popup_factory=self._create_popup_page)
        self._view.setPage(self._page)

        settings = self._view.settings()
        _WebShellPopupWindow._configure_settings(settings)

        self._view.loadFinished.connect(self._on_load_finished)
        self.setCentralWidget(self._view)

    def _create_popup_page(self):
        popup = _WebShellPopupWindow(self)
        self._popup_windows.add(popup)
        popup.destroyed.connect(lambda _=None, window=popup: self._popup_windows.discard(window))
        popup.show()
        return popup._page

    def _start_remote_backend(self):
        from core import remote_api_server

        server = remote_api_server.start_remote_server(
            self.app_context,
            host=self.host,
            port=self.port,
        )
        config = getattr(server, "config", None)
        actual_port = getattr(config, "port", None)
        if actual_port:
            self.port = normalize_web_shell_port(actual_port)
        self._server_started = True
        print(f"NAIA Web Shell backend: http://{self.host}:{self.port}")

    def _load_shell(self):
        self._view.load(QUrl(build_web_shell_url(self.host, self.port, embedded=True)))

    def _on_load_finished(self, ok: bool):
        if ok:
            self.setWindowTitle(f"NAIA Web Shell - {self.host}:{self.port}")
            return

        self.setWindowTitle("NAIA Web Shell - load failed")
        QTimer.singleShot(1000, self._load_shell)

    def _stop_remote_backend(self):
        if not self._server_started or not self.stop_server_on_close:
            return

        self._server_started = False
        try:
            from core.remote_api_server import stop_remote_server

            stop_remote_server()
        except Exception as exc:
            print(f"NAIA Web Shell backend stop failed: {exc}")

    def closeEvent(self, event):
        if self._closed:
            event.accept()
            return

        self._closed = True
        for popup in list(self._popup_windows):
            popup.close()
        self._popup_windows.clear()
        self._stop_remote_backend()
        event.accept()

        if self.quit_on_close:
            app = QApplication.instance()
            if app is not None:
                QTimer.singleShot(0, app.quit)
