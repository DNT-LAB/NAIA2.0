"""QWebEngine host for the NAIA Remote Web UI.

This window is the first Desktop Web Shell path: PyQt keeps the application
backend alive, while QWebEngine renders the existing Remote Web client.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from PyQt6.QtCore import QTimer, QUrl, Qt
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWidgets import QApplication, QLabel, QMainWindow, QStackedLayout, QVBoxLayout, QWidget
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

    _EXTERNAL_BROWSER_SCHEME = "naia-open-browser"
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

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        if url.scheme() == self._EXTERNAL_BROWSER_SCHEME:
            self._open_external_browser(url)
            return False
        return super().acceptNavigationRequest(url, navigation_type, is_main_frame)

    @staticmethod
    def _open_external_browser(url: QUrl):
        query = parse_qs(urlparse(url.toString()).query)
        target = (query.get("url") or [""])[0].strip()
        parsed = urlparse(target)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return
        QDesktopServices.openUrl(QUrl(target))


class _WebShellPopupWindow(QMainWindow):
    """Detached QWebEngine window opened by Web Shell window.open()."""

    _DEFAULT_SIZE = (720, 760)
    _METADATA_SIZE = (1040, 820)
    _MODULE_SIZES = {
        "prompt_engineering": (640, 860),
        "character": (760, 860),
        "conditional_prompt": (1560, 900),
        "wildcard": (680, 780),
        "instant_wildcard": (680, 780),
        "chunk": (620, 700),
        "search": (680, 760),
        "auto_save": (620, 680),
        "save_directory": (620, 680),
        "automation": (760, 760),
        "character_reference": (900, 780),
        "vibe_transfer": (900, 780),
        "img2img": (1080, 860),
        "e621_event": (1120, 820),
        "ollama": (760, 780),
    }

    def __init__(self, owner: "WebWrapperWindow"):
        super().__init__(None)
        self._owner = owner
        self._geometry_key = ""
        self._initial_show_timer = QTimer(self)
        self._initial_show_timer.setSingleShot(True)
        self._initial_show_timer.timeout.connect(self._show_after_initial_geometry)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowTitleHint
        )
        self.setWindowTitle("NAIA Web Shell - Detached")
        self.setStyleSheet("background:#0f0f17;")
        self.setMinimumSize(520, 420)
        self.resize(*self._DEFAULT_SIZE)

        self._view = QWebEngineView(self)
        self._page = _WebShellPage(self, popup_factory=owner._create_popup_page)
        self._view.setPage(self._page)
        self._view.setStyleSheet("background:#0f0f17;")
        try:
            self._page.setBackgroundColor(QColor("#0f0f17"))
        except Exception:
            pass
        self._configure_settings(self._view.settings())
        self._page.titleChanged.connect(self._on_title_changed)
        self._page.urlChanged.connect(self._apply_url_geometry)
        self._page.geometryChangeRequested.connect(self._apply_requested_geometry)
        self._page.windowCloseRequested.connect(self.close)
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

    def _apply_requested_geometry(self, rect):
        if not rect.isValid():
            return
        if self._geometry_key:
            return
        width = max(520, rect.width())
        height = max(420, rect.height())
        if self.width() != width or self.height() != height:
            self.resize(width, height)
        if not self._initial_show_timer.isActive():
            self._show_after_initial_geometry()

    def _apply_url_geometry(self, url: QUrl):
        parsed = urlparse(url.toString())
        query = parse_qs(parsed.query)
        mode = (query.get("detached") or [""])[0]
        if mode == "module":
            module_id = (query.get("module") or [""])[0]
            size = self._MODULE_SIZES.get(module_id, self._DEFAULT_SIZE)
            key = f"module:{module_id}:{size[0]}x{size[1]}"
        elif mode == "metadata":
            size = self._METADATA_SIZE
            key = f"metadata:{size[0]}x{size[1]}"
        else:
            return

        if self._geometry_key == key:
            self._show_after_initial_geometry()
            return
        self._geometry_key = key
        if self.width() != size[0] or self.height() != size[1]:
            self.resize(*size)
        self._center_on_owner()
        self._show_after_initial_geometry()

    def defer_initial_show(self, timeout_ms: int = 250):
        """Avoid flashing the default 720px mobile-sized shell before URL sizing."""
        if not self.isVisible():
            self._initial_show_timer.start(timeout_ms)

    def _show_after_initial_geometry(self):
        if self._initial_show_timer.isActive():
            self._initial_show_timer.stop()
        if not self.isVisible():
            self.show()

    def _center_on_owner(self):
        owner = getattr(self, "_owner", None)
        if owner is None:
            return
        owner_geometry = owner.geometry()
        x = owner_geometry.x() + max(0, (owner_geometry.width() - self.width()) // 2)
        y = owner_geometry.y() + max(0, (owner_geometry.height() - self.height()) // 2)
        self.move(x, y)

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
        self._remote_load_started = False
        self._closed = False
        self._popup_windows = set()
        self._boot_overlay = None
        self._boot_label = None

        self.setWindowTitle("NAIA Web Shell")
        self.setMinimumSize(1100, 760)
        self.resize(1440, 920)

        self._setup_webview()
        self._set_boot_status("Preparing desktop session...")
        QTimer.singleShot(80, self._start_backend_and_load_shell)

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._stop_remote_backend)

    def _setup_webview(self):
        self._view = QWebEngineView(self)
        self._page = _WebShellPage(self, popup_factory=self._create_popup_page)
        self._view.setPage(self._page)
        self._view.setStyleSheet("background:#0f0f17;")
        self.setStyleSheet("background:#0f0f17;")
        try:
            self._page.setBackgroundColor(QColor("#0f0f17"))
        except Exception:
            pass

        settings = self._view.settings()
        _WebShellPopupWindow._configure_settings(settings)

        self._view.loadFinished.connect(self._on_load_finished)

        container = QWidget(self)
        stack = QStackedLayout(container)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        stack.addWidget(self._view)
        self._boot_overlay = self._create_boot_overlay(container)
        stack.addWidget(self._boot_overlay)
        self.setCentralWidget(container)

    def _create_boot_overlay(self, parent):
        overlay = QWidget(parent)
        overlay.setObjectName("webShellBootOverlay")
        overlay.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        overlay.setStyleSheet("""
            #webShellBootOverlay {
                background: #0f0f17;
                color: #f6f0ff;
            }
            QLabel#webShellBootLabel {
                color: #f6f0ff;
                font-family: Pretendard, Segoe UI, sans-serif;
            }
        """)
        layout = QVBoxLayout(overlay)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.addStretch(1)
        self._boot_label = QLabel(overlay)
        self._boot_label.setObjectName("webShellBootLabel")
        self._boot_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._boot_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self._boot_label)
        layout.addStretch(1)
        return overlay

    def _set_boot_status(self, status: str):
        if not self._boot_label:
            return
        self._boot_label.setText(f"""
            <div style="font-size:30px;font-weight:800;">NAIA2</div>
            <div style="margin-top:10px;font-size:18px;font-weight:700;color:#b7a8ff;">
                Starting Web Shell
            </div>
            <div style="margin-top:18px;font-size:14px;color:#a8a2bb;">
                {status}
            </div>
        """)
        if self._boot_overlay:
            self._boot_overlay.show()
            self._boot_overlay.raise_()

    def _create_popup_page(self):
        popup = _WebShellPopupWindow(self)
        self._popup_windows.add(popup)
        popup.destroyed.connect(lambda _=None, window=popup: self._popup_windows.discard(window))
        popup.defer_initial_show()
        return popup._page

    def _start_backend_and_load_shell(self):
        if self._closed:
            return
        self._set_boot_status("Starting local backend...")
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        self._start_remote_backend()
        self._load_shell()

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
        self._remote_load_started = True
        self._set_boot_status("Connecting to local session...")
        self._view.load(QUrl(build_web_shell_url(self.host, self.port, embedded=True)))

    def _on_load_finished(self, ok: bool):
        if not self._remote_load_started:
            return
        if ok:
            self.setWindowTitle(f"NAIA Web Shell - {self.host}:{self.port}")
            if self._boot_overlay:
                self._boot_overlay.hide()
            return

        self.setWindowTitle("NAIA Web Shell - load failed")
        self._set_boot_status("Local session is not ready. Retrying...")
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
