import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_py_module_sizes():
    tree = ast.parse((ROOT / "legacy_desktop" / "ui" / "web_wrapper.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "_WebShellPopupWindow":
            for child in node.body:
                if isinstance(child, ast.Assign):
                    for target in child.targets:
                        if isinstance(target, ast.Name) and target.id == "_MODULE_SIZES":
                            return ast.literal_eval(child.value)
    raise AssertionError("_WebShellPopupWindow._MODULE_SIZES not found")


def _load_js_module_sizes():
    text = (ROOT / "app" / "web" / "remote" / "app.js").read_text(encoding="utf-8")
    match = re.search(r"const DETACHED_MODULE_GEOMETRY = \{(?P<body>.*?)\};", text, re.S)
    if not match:
        raise AssertionError("DETACHED_MODULE_GEOMETRY not found")
    return {
        module_id: (int(width), int(height))
        for module_id, width, height in re.findall(
            r"([a-z0-9_]+):\s*\{width:\s*(\d+),\s*height:\s*(\d+)\}",
            match.group("body"),
        )
    }


def _load_css_module_widths():
    text = (ROOT / "app" / "web" / "remote" / "style.css").read_text(encoding="utf-8")
    widths = {}
    for match in re.finditer(
        r"(?P<selectors>(?:body\.detached-module\.detached-module-[^{,]+,?\s*)+)"
        r"\{\s*--detached-module-width:\s*(?P<width>\d+)px;\s*\}",
        text,
        re.S,
    ):
        width = int(match.group("width"))
        for module_id in re.findall(r"detached-module-([a-z0-9_]+)", match.group("selectors")):
            widths[module_id] = width
    return widths


def test_qt_host_detached_module_sizes_match_js_window_features():
    py_sizes = _load_py_module_sizes()
    js_sizes = _load_js_module_sizes()

    assert set(py_sizes) <= set(js_sizes)
    assert {
        module_id: js_sizes[module_id]
        for module_id in py_sizes
    } == py_sizes


def test_css_detached_module_widths_match_js_window_features():
    js_sizes = _load_js_module_sizes()
    css_widths = _load_css_module_widths()

    assert set(js_sizes) <= set(css_widths)
    assert {
        module_id: css_widths[module_id]
        for module_id in js_sizes
    } == {
        module_id: width
        for module_id, (width, _height) in js_sizes.items()
    }
