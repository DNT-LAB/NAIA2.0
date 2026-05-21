from pathlib import Path
import sys

import pytest

from core.runtime_paths import (
    USER_DATA_DIR_ENV,
    WRITABLE_DIR_NAMES,
    resolve_runtime_paths,
)


def test_installed_mode_uses_appdata_root(tmp_path):
    repo = tmp_path / "repo"
    appdata = tmp_path / "AppData" / "Roaming"

    paths = resolve_runtime_paths(
        repo,
        env={"APPDATA": str(appdata)},
        portable=False,
    )

    assert paths.project_root == repo.resolve()
    assert paths.user_root == (appdata / "NAIA").resolve()
    assert paths.data_dir == (appdata / "NAIA" / "data").resolve()
    assert paths.ui_assets_dir == (appdata / "NAIA" / "ui_assets").resolve()


def test_portable_mode_uses_project_user_data(tmp_path):
    repo = tmp_path / "repo"

    paths = resolve_runtime_paths(repo, env={}, portable=True)

    assert paths.portable is True
    assert paths.user_root == (repo / "user-data").resolve()
    assert paths.output_dir == (repo / "user-data" / "output").resolve()


def test_explicit_user_data_dir_overrides_portability(tmp_path):
    repo = tmp_path / "repo"
    explicit = tmp_path / "custom-user-data"

    paths = resolve_runtime_paths(
        repo,
        env={USER_DATA_DIR_ENV: str(explicit)},
        portable=True,
    )

    assert paths.portable is True
    assert paths.user_root == explicit.resolve()
    assert paths.cache_dir == (explicit / "cache").resolve()


def test_resource_root_uses_frozen_meipass(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    frozen_root = tmp_path / "bundle-root"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(frozen_root), raising=False)

    paths = resolve_runtime_paths(repo, env={}, portable=True)

    assert paths.resource_root == frozen_root.resolve()
    assert paths.resource_path("app/web/remote") == (frozen_root / "app" / "web" / "remote").resolve()


def test_ensure_writable_dirs_creates_expected_runtime_roots(tmp_path):
    paths = resolve_runtime_paths(tmp_path / "repo", env={}, portable=True)

    paths.ensure_writable_dirs(["config", "data", "ui_assets"])

    assert paths.config_dir.is_dir()
    assert paths.data_dir.is_dir()
    assert paths.ui_assets_dir.is_dir()
    assert not paths.logs_dir.exists()


def test_unknown_writable_dir_is_rejected(tmp_path):
    paths = resolve_runtime_paths(tmp_path / "repo", env={}, portable=True)

    with pytest.raises(KeyError):
        paths.writable_dir("repo-data")


def test_source_tree_write_detection_allows_portable_user_data(tmp_path):
    repo = tmp_path / "repo"
    paths = resolve_runtime_paths(repo, env={}, portable=True)

    assert paths.is_source_tree_write(repo / "data" / "downloaded.json") is True
    assert paths.is_source_tree_write(repo / "ui" / "downloaded_asset.json") is True
    assert paths.is_source_tree_write(paths.data_dir / "downloaded.json") is False
    assert paths.is_source_tree_write(paths.ui_assets_dir / "bundle.json") is False


def test_manifest_contains_all_writable_dirs(tmp_path):
    paths = resolve_runtime_paths(tmp_path / "repo", env={}, portable=True)

    manifest = paths.manifest()
    source_paths = {Path(path) for path in manifest["source_bootstrap_paths"]}

    assert set(manifest["writable_dirs"]) == set(WRITABLE_DIR_NAMES)
    assert paths.source_path("data/source") in source_paths
    assert paths.source_path("app/web/remote") in source_paths
    assert paths.source_path("ui/remote_web") not in source_paths
