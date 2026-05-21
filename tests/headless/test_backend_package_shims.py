from app.backend.runtime import RuntimePaths, USER_DATA_DIR_ENV, resolve_runtime_paths
from app.backend.server import WebSessionContext, create_headless_app
from core import runtime_paths as legacy_runtime_paths


def test_backend_package_exposes_current_headless_server_contract():
    assert WebSessionContext.__name__ == "WebSessionContext"
    assert callable(create_headless_app)


def test_backend_package_exposes_runtime_path_resolver(tmp_path):
    paths = resolve_runtime_paths(project_root=tmp_path, portable=True)

    assert isinstance(paths, RuntimePaths)
    assert paths.user_root == tmp_path / "user-data"


def test_core_runtime_paths_remains_compatibility_import():
    assert legacy_runtime_paths.RuntimePaths is RuntimePaths
    assert legacy_runtime_paths.resolve_runtime_paths is resolve_runtime_paths
    assert legacy_runtime_paths.USER_DATA_DIR_ENV == USER_DATA_DIR_ENV
