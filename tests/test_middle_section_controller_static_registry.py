from pathlib import Path
from types import SimpleNamespace

from core import middle_section_controller as middle_controller
from core.middle_section_controller import MiddleSectionController


class _AppContext:
    def __init__(self):
        self.mode_manager = SimpleNamespace(register_module=lambda _module: None)
        self.hooks = []
        self.subscribers = []

    def subscribe(self, *args, **_kwargs):
        self.subscribers.append(args)

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

    assert specs["CharacterModule"]["web_session_lazy"] is True
    assert specs["E621EventModuleV2"]["web_session_lazy"] is True
    assert specs["WildcardStatusModule"]["web_session_lazy"] is True
    assert specs["OllamaModule"]["web_session_lazy"] is True
    assert specs["ReferenceInsetAutoInjectModule"]["web_session_lazy"] is True
    assert specs["ReferenceInsetAutoInjectModule"]["web_session_headless_hook"] == "reference_inset"
    assert specs["InstantWildcardModule"]["web_session_lazy"] is True
    assert specs["AutomationModule"]["web_session_lazy"] is True
    assert specs["CharacterReferenceModule"]["web_session_lazy"] is True
    assert specs["VibeTransferModule"]["web_session_lazy"] is True
    assert specs["PromptListModifierModule"]["web_session_lazy"] is True
    assert specs["PromptListModifierModule"]["web_session_headless_hook"] == "conditional_prompt"
    assert specs["PromptEngineeringModule"]["web_session_lazy"] is True
    assert specs["PromptEngineeringModule"]["web_session_headless_hook"] == "prompt_engineering"


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


def test_web_session_reference_inset_registers_headless_hook_without_import(tmp_path, monkeypatch):
    marker_path = tmp_path / "reference_inset_imported.txt"
    (tmp_path / "reference_inset_module.py").write_text(
        f"""
from pathlib import Path
Path({str(marker_path)!r}).write_text('imported', encoding='utf-8')
raise RuntimeError('reference inset module should stay deferred')
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        middle_controller,
        "MIDDLE_MODULE_SPECS",
        (
            {
                "file": "reference_inset_module",
                "class": "ReferenceInsetAutoInjectModule",
                "web_session_lazy": True,
                "web_session_headless_hook": "reference_inset",
            },
        ),
    )
    monkeypatch.setenv("NAIA_CLI_WEB_SESSION_HIDE_MAIN_WINDOW", "1")
    ctx = _AppContext()
    controller = MiddleSectionController(str(tmp_path), ctx)

    controller.load_modules()

    assert controller.module_classes == []
    assert controller.module_instances == []
    assert not marker_path.exists()
    assert len(ctx.hooks) == 1

    hook_info, hook = ctx.hooks[0]
    assert hook_info == {
        "target_pipeline": "PromptProcessor",
        "hook_point": "final_hookpoint",
        "priority": 90,
    }

    context = SimpleNamespace(
        settings={"reference_inset_tag_required": True},
        metadata={},
        prefix_tags=[],
        main_tags=["1girl", "solo"],
        postfix_tags=[],
    )
    hook.execute_pipeline_hook(context)

    assert context.main_tags == ["1girl", "reference inset", "solo"]


def test_web_session_prompt_engineering_registers_headless_runtime_without_import(tmp_path, monkeypatch):
    marker_path = tmp_path / "prompt_engineering_imported.txt"
    (tmp_path / "prompt_engineering_module.py").write_text(
        f"""
from pathlib import Path
Path({str(marker_path)!r}).write_text('imported', encoding='utf-8')
raise RuntimeError('prompt engineering module should stay deferred')
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        middle_controller,
        "MIDDLE_MODULE_SPECS",
        (
            {
                "file": "prompt_engineering_module",
                "class": "PromptEngineeringModule",
                "web_session_lazy": True,
                "web_session_headless_hook": "prompt_engineering",
            },
        ),
    )
    monkeypatch.setenv("NAIA_CLI_WEB_SESSION_HIDE_MAIN_WINDOW", "1")
    ctx = _AppContext()
    controller = MiddleSectionController(str(tmp_path), ctx)

    controller.load_modules()

    assert controller.module_classes == []
    assert controller.module_instances == []
    assert not marker_path.exists()
    assert len(ctx.hooks) == 5
    assert [hook_info["hook_point"] for hook_info, _hook in ctx.hooks] == [
        "post_processing",
        "after_wildcard",
        "after_wildcard",
        "after_wildcard",
        "after_wildcard",
    ]
    assert [args[0] for args in ctx.subscribers if args[0].startswith("random_prompt_triggered")] == [
        "random_prompt_triggered",
        "random_prompt_triggered_preset_randomizer",
    ]


def test_web_session_conditional_prompt_registers_headless_hook_without_import(tmp_path, monkeypatch):
    marker_path = tmp_path / "conditional_prompt_imported.txt"
    (tmp_path / "conditional_prompt_module.py").write_text(
        f"""
from pathlib import Path
Path({str(marker_path)!r}).write_text('imported', encoding='utf-8')
from interfaces.base_module import BaseMiddleModule

class PromptListModifierModule(BaseMiddleModule):
    def __init__(self):
        super().__init__()
        self.initialized = False
        self.settings = {{}}

    def initialize_with_context(self, app_context):
        self.app_context = app_context

    def on_initialize(self):
        self.initialized = True

    def get_title(self):
        return "Conditional"

    def create_widget(self, parent):
        return None

    def apply_settings(self, settings):
        self.settings = dict(settings)

    def execute_pipeline_hook(self, context):
        context.main_tags.append("conditional-loaded")
        return context

    def get_pipeline_hook_info(self):
        return {{"target_pipeline": "PromptProcessor", "hook_point": "after_wildcard", "priority": 2}}
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        middle_controller,
        "MIDDLE_MODULE_SPECS",
        (
            {
                "file": "conditional_prompt_module",
                "class": "PromptListModifierModule",
                "web_session_lazy": True,
                "web_session_headless_hook": "conditional_prompt",
            },
        ),
    )
    monkeypatch.setenv("NAIA_CLI_WEB_SESSION_HIDE_MAIN_WINDOW", "1")
    monkeypatch.chdir(tmp_path)
    ctx = _AppContext()
    controller = MiddleSectionController(str(tmp_path), ctx)
    ctx.middle_section_controller = controller

    controller.load_modules()

    assert controller.module_classes == []
    assert controller.module_instances == []
    assert not marker_path.exists()
    assert len(ctx.hooks) == 1
    hook_info, hook = ctx.hooks[0]
    assert hook.get_title() == "Conditional Prompt Headless"
    assert hook_info == {
        "target_pipeline": "PromptProcessor",
        "hook_point": "after_wildcard",
        "priority": 2,
    }

    context = SimpleNamespace(settings={}, prefix_tags=[], main_tags=[], postfix_tags=[])
    hook.execute_pipeline_hook(context)

    assert not marker_path.exists()
    assert controller.module_instances == []
    assert context.main_tags == []

    from core.conditional_prompt_settings import get_conditional_prompt_store

    get_conditional_prompt_store(ctx).apply_settings({
        "enabled": True,
        "rules": "(e):main+=dramatic lighting",
        "editor_mode": "legacy",
    })
    hook.execute_pipeline_hook(context)

    assert marker_path.exists()
    assert len(controller.module_instances) == 1
    assert controller.module_instances[0].initialized is True
    assert context.main_tags == ["conditional-loaded"]
    assert len(ctx.hooks) == 1


def test_web_session_prompt_engineering_lazy_load_does_not_double_register_post_hook(tmp_path, monkeypatch):
    (tmp_path / "prompt_engineering_module.py").write_text(
        """
from interfaces.base_module import BaseMiddleModule

class PromptEngineeringModule(BaseMiddleModule):
    def __init__(self):
        super().__init__()
        self.initialized = False

    def get_title(self):
        return "Prompt Engineering"

    def create_widget(self, parent):
        return None

    def on_initialize(self):
        self.initialized = True

    def get_pipeline_hook_info(self):
        return {"target_pipeline": "PromptProcessor", "hook_point": "post_processing", "priority": 10}
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        middle_controller,
        "MIDDLE_MODULE_SPECS",
        (
            {
                "file": "prompt_engineering_module",
                "class": "PromptEngineeringModule",
                "web_session_lazy": True,
                "web_session_headless_hook": "prompt_engineering",
            },
        ),
    )
    monkeypatch.setenv("NAIA_CLI_WEB_SESSION_HIDE_MAIN_WINDOW", "1")
    ctx = _AppContext()
    controller = MiddleSectionController(str(tmp_path), ctx)
    controller.load_modules()

    module = controller.get_module_instance("PromptEngineeringModule")

    assert module.initialized is True
    assert len(ctx.hooks) == 5
    assert [hook.__class__.__name__ for _hook_info, hook in ctx.hooks].count("PromptEngineeringHeadlessPostHook") == 1
