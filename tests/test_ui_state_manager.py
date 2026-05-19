import base64
import json

from legacy_desktop.core.ui_state_manager import UIStateManager


class FakeMainWindow:
    def __init__(self, *, visible=False, hidden=True, maximized=False):
        self._visible = visible
        self._hidden = hidden
        self._maximized = maximized
        self.maximized_calls = 0
        self.restored_geometry = None

    def saveGeometry(self):
        return b"geometry"

    def restoreGeometry(self, geometry):
        self.restored_geometry = geometry

    def showMaximized(self):
        self.maximized_calls += 1

    def isMaximized(self):
        return self._maximized

    def isVisible(self):
        return self._visible

    def isHidden(self):
        return self._hidden


def write_ui_state(path, *, maximized=True):
    path.write_text(
        json.dumps({
            "window_geometry": base64.b64encode(b"geometry").decode("ascii"),
            "window_maximized": maximized,
        }),
        encoding="utf-8",
    )


def make_manager(tmp_path):
    manager = UIStateManager()
    manager.STATE_FILE = tmp_path / "ui_state.json"
    return manager


def test_hidden_web_startup_defers_maximized_restore(monkeypatch, tmp_path):
    monkeypatch.setenv("NAIA_CLI_WEB_SESSION_HIDE_MAIN_WINDOW", "1")
    monkeypatch.delenv("NAIA_CLI_DESKTOP", raising=False)
    manager = make_manager(tmp_path)
    write_ui_state(manager.STATE_FILE, maximized=True)
    window = FakeMainWindow(visible=False, hidden=True)

    manager.restore_state(window)

    assert window.restored_geometry is not None
    assert window.maximized_calls == 0
    assert window._pending_ui_state_show_maximized is True


def test_visible_window_restores_maximized_immediately(monkeypatch, tmp_path):
    monkeypatch.setenv("NAIA_CLI_WEB_SESSION_HIDE_MAIN_WINDOW", "1")
    manager = make_manager(tmp_path)
    write_ui_state(manager.STATE_FILE, maximized=True)
    window = FakeMainWindow(visible=True, hidden=False)

    manager.restore_state(window)

    assert window.maximized_calls == 1
    assert not hasattr(window, "_pending_ui_state_show_maximized")


def test_desktop_cli_restores_maximized_immediately(monkeypatch, tmp_path):
    monkeypatch.setenv("NAIA_CLI_WEB_SESSION_HIDE_MAIN_WINDOW", "1")
    monkeypatch.setenv("NAIA_CLI_DESKTOP", "1")
    manager = make_manager(tmp_path)
    write_ui_state(manager.STATE_FILE, maximized=True)
    window = FakeMainWindow(visible=False, hidden=True)

    manager.restore_state(window)

    assert window.maximized_calls == 1
    assert not hasattr(window, "_pending_ui_state_show_maximized")


def test_save_state_preserves_deferred_maximized_restore(tmp_path):
    manager = make_manager(tmp_path)
    window = FakeMainWindow(maximized=False)
    window._pending_ui_state_show_maximized = True

    manager.save_state(window)

    state = json.loads(manager.STATE_FILE.read_text(encoding="utf-8"))
    assert state["window_maximized"] is True
