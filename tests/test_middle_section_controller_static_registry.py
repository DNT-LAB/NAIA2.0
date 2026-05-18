from pathlib import Path
from types import SimpleNamespace

from core import middle_section_controller as middle_controller
from core.middle_section_controller import MiddleSectionController


class _AppContext:
    def __init__(self):
        self.mode_manager = SimpleNamespace(register_module=lambda _module: None)
        self.hooks = []

    def subscribe(self, *_args, **_kwargs):
        pass

    def get_api_mode(self):
        return "NAI"

    def register_pipeline_hook(self, hook_info, module):
        self.hooks.append((hook_info, module))


def test_middle_module_loader_uses_static_registry_and_skips_unregistered_files(tmp_path, monkeypatch):
    marker_path = tmp_path / "rogue_imported.txt"
    (tmp_path / "rogue_module.py").write_text(
        f"""
from pathlib import Path
Path({str(marker_path)!r}).write_text('imported', encoding='utf-8')
raise RuntimeError('rogue module imported')
""",
        encoding="utf-8",
    )
    (tmp_path / "registered_module.py").write_text(
        """
from PyQt6.QtWidgets import QLabel
from interfaces.base_module import BaseMiddleModule

class RegisteredModule(BaseMiddleModule):
    def get_title(self):
        return "Registered"

    def create_widget(self, parent):
        return QLabel("registered", parent)
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        middle_controller,
        "MIDDLE_MODULE_SPECS",
        ({"file": "registered_module", "class": "RegisteredModule"},),
    )

    controller = MiddleSectionController(str(tmp_path), _AppContext())

    controller.load_modules()

    assert [cls.__name__ for cls in controller.module_classes] == ["RegisteredModule"]
    assert not marker_path.exists()


def test_middle_module_loader_selects_registered_class_only(tmp_path, monkeypatch):
    (tmp_path / "multi_module.py").write_text(
        """
from PyQt6.QtWidgets import QLabel
from interfaces.base_module import BaseMiddleModule

class ExtraModule(BaseMiddleModule):
    def get_title(self):
        return "Extra"

    def create_widget(self, parent):
        return QLabel("extra", parent)

class TargetModule(BaseMiddleModule):
    def get_title(self):
        return "Target"

    def create_widget(self, parent):
        return QLabel("target", parent)
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        middle_controller,
        "MIDDLE_MODULE_SPECS",
        ({"file": "multi_module", "class": "TargetModule"},),
    )

    controller = MiddleSectionController(str(tmp_path), _AppContext())

    controller.load_modules()

    assert [cls.__name__ for cls in controller.module_classes] == ["TargetModule"]


def test_checked_in_middle_module_registry_files_exist():
    for spec in middle_controller.MIDDLE_MODULE_SPECS:
        assert (Path("modules") / f"{spec['file']}.py").is_file()


def test_web_session_lazy_registry_keeps_generation_modules_eager():
    specs = {spec["class"]: spec for spec in middle_controller.MIDDLE_MODULE_SPECS}

    assert specs["WildcardStatusModule"]["web_session_lazy"] is True
    assert specs["OllamaModule"]["web_session_lazy"] is True
    assert specs["InstantWildcardModule"].get("web_session_lazy") is not True


def test_web_session_lazy_middle_module_defers_import_until_requested(tmp_path, monkeypatch):
    marker_path = tmp_path / "lazy_imported.txt"
    (tmp_path / "lazy_module.py").write_text(
        f"""
from pathlib import Path
Path({str(marker_path)!r}).write_text('imported', encoding='utf-8')
from PyQt6.QtWidgets import QLabel
from interfaces.base_module import BaseMiddleModule

class LazyModule(BaseMiddleModule):
    def __init__(self):
        super().__init__()
        self.initialized = False

    def get_title(self):
        return "Lazy"

    def create_widget(self, parent):
        return QLabel("lazy", parent)

    def on_initialize(self):
        self.initialized = True

    def get_pipeline_hook_info(self):
        return {{"target_pipeline": "PromptProcessor", "hook_point": "final_hookpoint"}}
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        middle_controller,
        "MIDDLE_MODULE_SPECS",
        ({"file": "lazy_module", "class": "LazyModule", "web_session_lazy": True},),
    )
    monkeypatch.setenv("NAIA_CLI_WEB_SESSION_HIDE_MAIN_WINDOW", "1")
    ctx = _AppContext()
    controller = MiddleSectionController(str(tmp_path), ctx)

    controller.load_modules()

    assert controller.module_classes == []
    assert controller.module_instances == []
    assert not marker_path.exists()

    module = controller.get_module_instance("LazyModule")

    assert marker_path.exists()
    assert module.__class__.__name__ == "LazyModule"
    assert module.initialized is True
    assert controller.module_instances == [module]
    assert ctx.hooks == [({"target_pipeline": "PromptProcessor", "hook_point": "final_hookpoint"}, module)]


def test_web_session_lazy_middle_module_loads_immediately_on_desktop(tmp_path, monkeypatch):
    marker_path = tmp_path / "desktop_imported.txt"
    (tmp_path / "lazy_module.py").write_text(
        f"""
from pathlib import Path
Path({str(marker_path)!r}).write_text('imported', encoding='utf-8')
from PyQt6.QtWidgets import QLabel
from interfaces.base_module import BaseMiddleModule

class LazyModule(BaseMiddleModule):
    def get_title(self):
        return "Lazy"

    def create_widget(self, parent):
        return QLabel("lazy", parent)
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        middle_controller,
        "MIDDLE_MODULE_SPECS",
        ({"file": "lazy_module", "class": "LazyModule", "web_session_lazy": True},),
    )
    monkeypatch.delenv("NAIA_CLI_WEB_SESSION_HIDE_MAIN_WINDOW", raising=False)
    controller = MiddleSectionController(str(tmp_path), _AppContext())

    controller.load_modules()

    assert marker_path.exists()
    assert [cls.__name__ for cls in controller.module_classes] == ["LazyModule"]
