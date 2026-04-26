import ast
from pathlib import Path


BLOCKED_QT_DPI_ENV_KEYS = {
    "QT_AUTO_SCREEN_SCALE_FACTOR",
    "QT_ENABLE_HIGHDPI_SCALING",
    "QT_SCALE_FACTOR_ROUNDING_POLICY",
}

BLOCKED_QT_DPI_APIS = {
    "setHighDpiScaleFactorRoundingPolicy",
    "AA_EnableHighDpiScaling",
    "AA_UseHighDpiPixmaps",
}


def _assigned_os_environ_key(target):
    if not isinstance(target, ast.Subscript):
        return None

    value = target.value
    if not (
        isinstance(value, ast.Attribute)
        and value.attr == "environ"
        and isinstance(value.value, ast.Name)
        and value.value.id == "os"
    ):
        return None

    slice_node = target.slice
    if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
        return slice_node.value
    return None


def test_desktop_host_does_not_force_qt_dpi_environment():
    source = Path("NAIA_cold_v4.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    forced_keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                key = _assigned_os_environ_key(target)
                if key in BLOCKED_QT_DPI_ENV_KEYS:
                    forced_keys.add(key)

    assert forced_keys == set()


def test_desktop_host_does_not_call_legacy_high_dpi_apis():
    source = Path("NAIA_cold_v4.py").read_text(encoding="utf-8")

    for api_name in BLOCKED_QT_DPI_APIS:
        assert api_name not in source
