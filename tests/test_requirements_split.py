import json
import os
from pathlib import Path
import subprocess
import sys


HEADLESS_REQUIREMENT_FILES = [
    "requirements.txt",
    "requirements_mac.txt",
    "requirements_linux.txt",
    "requirements-headless.txt",
]

LEGACY_REQUIREMENT_FILES = [
    "requirements-desktop-legacy.txt",
    "requirements-desktop-legacy-mac.txt",
    "requirements-desktop-legacy-linux.txt",
]

HEADLESS_FORBIDDEN_PACKAGES = [
    "pyqt6",
    "pyqt6-qt6",
    "pyqt6-webengine",
    "pyqt6-webengine-qt6",
    "pyqt6_sip",
    "pyqt6-qscintilla",
    "pywinpty",
    "pypiwin32",
    "pywin32",
    "win10toast",
    "ultralytics",
]


def requirement_lines(path: str) -> list[str]:
    lines = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line.lower())
    return lines


def test_headless_requirements_do_not_include_desktop_packages():
    for path in HEADLESS_REQUIREMENT_FILES:
        text = "\n".join(requirement_lines(path))
        for package in HEADLESS_FORBIDDEN_PACKAGES:
            assert package not in text, f"{path} unexpectedly includes {package}"


def test_platform_default_requirements_delegate_to_headless_file():
    for path in ["requirements.txt", "requirements_mac.txt", "requirements_linux.txt"]:
        assert requirement_lines(path) == ["-r requirements-headless.txt"]


def test_legacy_desktop_requirements_extend_headless_and_keep_pyqt():
    for path in LEGACY_REQUIREMENT_FILES:
        lines = requirement_lines(path)
        text = "\n".join(lines)
        assert lines[0] == "-r requirements-headless.txt"
        assert "pyqt6==6.9.1" in text
        assert "pyqt6-webengine==6.9.0" in text
        assert "pyqt6-qscintilla" in text
        assert "ultralytics" in text


def test_launchers_install_matching_requirement_sets():
    assert "requirements-headless.txt" in Path("run_NAIA_web.bat").read_text(encoding="utf-8")
    assert "requirements-headless.txt" in Path("run_NAIA_web.command").read_text(encoding="utf-8")
    assert "requirements-desktop-legacy.txt" in Path("run_NAIA.bat").read_text(encoding="utf-8")
    assert "requirements-desktop-legacy-mac.txt" in Path("run_NAIA.command").read_text(encoding="utf-8")


def test_headless_entrypoint_imports_with_desktop_modules_blocked():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.getcwd()
    code = r"""
import importlib.abc
import json
import sys

blocked = {
    "core.remote_api_server",
    "core.middle_section_controller",
    "core.tab_controller",
    "NAIA_cold_v4",
}

class BlockDesktopImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "PyQt6" or fullname.startswith("PyQt6.") or fullname in blocked:
            raise ImportError(f"blocked desktop import: {fullname}")
        return None

sys.meta_path.insert(0, BlockDesktopImports())

from core.web_session_app import create_headless_app
from core.web_session_context import InMemoryTokenManager, WebSessionContext
import NAIA_web_headless

context = WebSessionContext(token_manager=InMemoryTokenManager())
app = create_headless_app(context)
print(json.dumps({
    "ok": True,
    "title": app.title,
    "entrypoint": NAIA_web_headless.__name__,
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload == {
        "ok": True,
        "title": "NAIA Remote Headless",
        "entrypoint": "NAIA_web_headless",
    }


def test_supported_headless_core_services_import_with_qt_blocked():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.getcwd()
    code = r"""
import importlib
import importlib.abc
import json
import sys

blocked = {
    "core.remote_api_server",
    "core.middle_section_controller",
    "core.tab_controller",
    "core.main_controller",
    "core.generation_controller",
    "core.prompt_generation_controller",
    "core.search_controller",
    "core.autocomplete_manager",
    "core.ui_state_manager",
    "core.temp_window_manager",
    "NAIA_cold_v4",
}
modules = [
    "core.web_session_app",
    "core.web_session_context",
    "core.api_config_service",
    "core.api_service",
    "core.headless_random_prompt_service",
    "core.headless_generation_service",
    "core.headless_result_service",
    "core.style_thumbnail_service",
    "core.character_viewer_service",
    "core.prompt_generation_service",
    "core.prompt_engineering_runtime",
    "core.conditional_prompt_runtime",
    "core.reference_inset_service",
    "core.wildcard_manager",
    "core.filter_data_manager",
]

class BlockDesktopImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "PyQt6" or fullname.startswith("PyQt6.") or fullname in blocked:
            raise ImportError(f"blocked desktop import: {fullname}")
        return None

sys.meta_path.insert(0, BlockDesktopImports())
for name in modules:
    importlib.import_module(name)
print(json.dumps({
    "ok": True,
    "modules": len(modules),
    "pyqt_imported": "PyQt6" in sys.modules,
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload == {
        "ok": True,
        "modules": 15,
        "pyqt_imported": False,
    }
