import zipfile

from app.backend.runtime import RESOURCE_ROOT_ENV, USER_DATA_DIR_ENV, resolve_runtime_paths
from core.runtime_install_manager import RuntimeInstallManager


def test_runtime_install_manager_initializes_runtime_data_dirs(tmp_path):
    paths = resolve_runtime_paths(tmp_path, portable=True)
    manager = RuntimeInstallManager(paths, expected_tag_files=2)

    snapshot = manager.initialize()

    assert snapshot["ok"] is True
    assert snapshot["runtime"]["data_initialized"] is True
    assert paths.data_dir.is_dir()
    assert (paths.data_dir / "tags").is_dir()
    assert snapshot["tag_archive"]["ready"] is False


def test_runtime_install_manager_copies_bootstrap_filter_data(tmp_path):
    project_root = tmp_path / "project"
    resource_root = tmp_path / "resource"
    user_root = tmp_path / "user-data"
    (resource_root / "data" / "taglist").mkdir(parents=True)
    (resource_root / "data" / "clothes_list.txt").write_text("dress\n", encoding="utf-8")
    (resource_root / "data" / "color.txt").write_text("red\n", encoding="utf-8")
    (resource_root / "data" / "characteristic_list.txt").write_text("shiny\n", encoding="utf-8")
    (resource_root / "data" / "taglist" / "expression_tags.json").write_text('{"tags":["smile"]}', encoding="utf-8")
    (resource_root / "data" / "KR_tags.parquet").write_text("large data should not be copied", encoding="utf-8")
    (user_root / "data").mkdir(parents=True)
    (user_root / "data" / "color.txt").write_text("custom color\n", encoding="utf-8")

    paths = resolve_runtime_paths(
        project_root,
        env={
            RESOURCE_ROOT_ENV: str(resource_root),
            USER_DATA_DIR_ENV: str(user_root),
        },
    )
    snapshot = RuntimeInstallManager(paths, expected_tag_files=2).initialize()

    assert (user_root / "data" / "clothes_list.txt").read_text(encoding="utf-8") == "dress\n"
    assert (user_root / "data" / "color.txt").read_text(encoding="utf-8") == "custom color\n"
    assert (user_root / "data" / "characteristic_list.txt").read_text(encoding="utf-8") == "shiny\n"
    assert (user_root / "data" / "taglist" / "expression_tags.json").exists()
    assert (user_root / "data" / "KR_tags.parquet").exists() is False
    assert snapshot["bootstrap_data"]["copied"] == 3
    assert snapshot["bootstrap_data"]["present"] == 1


def test_runtime_install_manager_downloads_and_extracts_tag_archive(tmp_path):
    archive_path = tmp_path / "naia_tags.zip"
    payload = b"not a real parquet, only installer payload test" * 64
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("nested/tags_000.parquet", payload)
        archive.writestr("tags_001.parquet", payload)

    paths = resolve_runtime_paths(tmp_path / "project", portable=True)
    completed = []
    manager = RuntimeInstallManager(
        paths,
        tag_archive_url=archive_path.as_uri(),
        expected_tag_files=2,
        on_tag_archive_complete=lambda: completed.append(True),
    )

    state = manager.start_tag_archive_download(blocking=True)
    snapshot = manager.snapshot()

    assert state["done"] is True
    assert state["active"] is False
    assert snapshot["tag_archive"]["ready"] is True
    assert snapshot["tag_archive"]["file_count"] == 2
    assert (paths.data_dir / "tags" / "tags_000.parquet").read_bytes() == payload
    assert (paths.data_dir / "tags" / "tags_001.parquet").read_bytes() == payload
    assert completed == [True]
