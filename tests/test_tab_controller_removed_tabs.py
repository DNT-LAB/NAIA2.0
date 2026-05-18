from PyQt6.QtWidgets import QTabWidget

from core.tab_controller import REMOVED_TAB_MODULES, WEB_SESSION_UNSUPPORTED_TAB_MODULES, TabController


def test_removed_tab_files_are_not_imported(tmp_path, qtbot):
    removed_file = tmp_path / "assets_tab.py"
    removed_file.write_text("raise RuntimeError('removed tab imported')\n", encoding="utf-8")

    active_file = tmp_path / "dummy_tab.py"
    active_file.write_text(
        """
from PyQt6.QtWidgets import QLabel
from interfaces.base_tab_module import BaseTabModule

class DummyTabModule(BaseTabModule):
    def get_tab_title(self):
        return "Dummy"

    def get_tab_type(self):
        return "closable"

    def create_widget(self, parent):
        return QLabel("dummy", parent)
""",
        encoding="utf-8",
    )

    tab_widget = QTabWidget()
    qtbot.addWidget(tab_widget)
    controller = TabController(str(tmp_path), app_context=None, tab_widget=tab_widget)
    qtbot.addWidget(controller)

    controller._load_tab_modules()

    assert [cls.__name__ for cls in controller.module_classes] == ["DummyTabModule"]


def test_prototype_tab_files_are_not_imported_on_startup(tmp_path, qtbot):
    prototype_file = tmp_path / "comic_generator_tab.py"
    prototype_file.write_text(
        "raise RuntimeError('prototype tab imported during startup')\n",
        encoding="utf-8",
    )

    tab_widget = QTabWidget()
    qtbot.addWidget(tab_widget)
    controller = TabController(str(tmp_path), app_context=None, tab_widget=tab_widget)
    qtbot.addWidget(controller)

    controller.initialize_tabs()

    assert tab_widget.count() == 0
    assert controller.module_classes == []


def test_removed_tab_modules_cannot_be_added(qtbot):
    tab_widget = QTabWidget()
    qtbot.addWidget(tab_widget)
    controller = TabController("tabs", app_context=None, tab_widget=tab_widget)
    qtbot.addWidget(controller)

    for module_name in REMOVED_TAB_MODULES:
        controller.add_tab_by_name(module_name)

    assert tab_widget.count() == 0


def test_lazy_core_tab_files_are_not_imported_on_startup(tmp_path, qtbot):
    lazy_file = tmp_path / "web_view.py"
    lazy_file.write_text("raise RuntimeError('lazy tab imported during startup')\n", encoding="utf-8")

    tab_widget = QTabWidget()
    qtbot.addWidget(tab_widget)
    controller = TabController(str(tmp_path), app_context=None, tab_widget=tab_widget)
    qtbot.addWidget(controller)

    controller.initialize_tabs()

    assert "BrowserTabModule" in controller.lazy_tab_specs
    assert tab_widget.count() == 1
    assert tab_widget.tabText(0) == "📦 Danbooru"


def test_dynamic_tab_file_is_imported_only_when_requested(tmp_path, qtbot):
    dynamic_file = tmp_path / "img2img_tab.py"
    dynamic_file.write_text(
        """
from PyQt6.QtWidgets import QLabel
from interfaces.base_tab_module import BaseTabModule

class Img2ImgTabModule(BaseTabModule):
    def get_tab_title(self):
        return "Img2Img Test"

    def get_tab_type(self):
        return "closable"

    def create_widget(self, parent):
        return QLabel("loaded", parent)
""",
        encoding="utf-8",
    )

    tab_widget = QTabWidget()
    qtbot.addWidget(tab_widget)
    controller = TabController(str(tmp_path), app_context=None, tab_widget=tab_widget)
    qtbot.addWidget(controller)

    controller.initialize_tabs()
    assert tab_widget.count() == 0

    controller.add_tab_by_name("Img2ImgTabModule")

    assert tab_widget.count() == 1
    assert "Img2ImgTabModule" in controller.module_instances


def test_web_session_unsupported_dynamic_tab_is_not_imported_when_requested(tmp_path, qtbot, monkeypatch):
    marker_path = tmp_path / "turbo_imported.txt"
    dynamic_file = tmp_path / "turbo_event_sequence_tab.py"
    dynamic_file.write_text(
        f"""
from pathlib import Path
Path({str(marker_path)!r}).write_text('imported', encoding='utf-8')
from PyQt6.QtWidgets import QLabel
from interfaces.base_tab_module import BaseTabModule

class TurboEventSequenceTabModule(BaseTabModule):
    def get_tab_title(self):
        return "Turbo Test"

    def get_tab_type(self):
        return "closable"

    def create_widget(self, parent):
        return QLabel("loaded", parent)
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("NAIA_CLI_WEB_SESSION_HIDE_MAIN_WINDOW", "1")
    tab_widget = QTabWidget()
    qtbot.addWidget(tab_widget)
    controller = TabController(str(tmp_path), app_context=None, tab_widget=tab_widget)
    qtbot.addWidget(controller)

    controller.add_tab_by_name("TurboEventSequenceTabModule")

    assert tab_widget.count() == 0
    assert not marker_path.exists()
    assert "TurboEventSequenceTabModule" in WEB_SESSION_UNSUPPORTED_TAB_MODULES


def test_web_session_unsupported_dynamic_tab_stays_desktop_loadable(tmp_path, qtbot, monkeypatch):
    dynamic_file = tmp_path / "turbo_event_sequence_tab.py"
    dynamic_file.write_text(
        """
from PyQt6.QtWidgets import QLabel
from interfaces.base_tab_module import BaseTabModule

class TurboEventSequenceTabModule(BaseTabModule):
    def get_tab_title(self):
        return "Turbo Test"

    def get_tab_type(self):
        return "closable"

    def create_widget(self, parent):
        return QLabel("loaded", parent)
""",
        encoding="utf-8",
    )

    monkeypatch.delenv("NAIA_CLI_WEB_SESSION_HIDE_MAIN_WINDOW", raising=False)
    tab_widget = QTabWidget()
    qtbot.addWidget(tab_widget)
    controller = TabController(str(tmp_path), app_context=None, tab_widget=tab_widget)
    qtbot.addWidget(controller)

    controller.add_tab_by_name("TurboEventSequenceTabModule")

    assert tab_widget.count() == 1
    assert "TurboEventSequenceTabModule" in controller.module_instances


def test_lazy_tab_load_is_not_reentrant_during_tab_replacement(tmp_path, qtbot):
    web_view_file = tmp_path / "web_view.py"
    web_view_file.write_text(
        """
from PyQt6.QtWidgets import QLabel
from interfaces.base_tab_module import BaseTabModule

class BrowserTabModule(BaseTabModule):
    def get_tab_title(self):
        return "Danbooru Test"

    def create_widget(self, parent):
        return QLabel("browser", parent)
""",
        encoding="utf-8",
    )

    png_info_file = tmp_path / "png_info_tab.py"
    png_info_file.write_text(
        """
from PyQt6.QtWidgets import QLabel
from interfaces.base_tab_module import BaseTabModule

class PngInfoTabModule(BaseTabModule):
    def get_tab_title(self):
        return "PNG Info Test"

    def create_widget(self, parent):
        return QLabel("png", parent)
""",
        encoding="utf-8",
    )

    tab_widget = QTabWidget()
    qtbot.addWidget(tab_widget)
    controller = TabController(str(tmp_path), app_context=None, tab_widget=tab_widget)
    qtbot.addWidget(controller)
    controller.initialize_tabs()
    tab_widget.currentChanged.connect(controller.ensure_tab_loaded_by_index)

    controller.ensure_tab_loaded("BrowserTabModule")

    assert tab_widget.count() == 2
    assert [tab_widget.tabText(i) for i in range(tab_widget.count())].count("Danbooru Test") == 1
    assert "BrowserTabModule" in controller.module_instances
