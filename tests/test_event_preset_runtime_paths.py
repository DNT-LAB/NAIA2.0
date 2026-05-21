import zipfile
from pathlib import Path

from core.event_preset_download_service import EventPresetDownloadService
from core.event_preset_service import EventPresetService
from core.web_session_app import create_headless_app
from core.web_session_context import InMemoryTokenManager, WebSessionContext
from fastapi.testclient import TestClient


def _write_minimal_event_zip(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("base/tag_catalog.parquet", b"placeholder")
        archive.writestr("base/event_taxonomy_v2_1.parquet", b"placeholder")


def test_event_preset_service_prefers_runtime_paths_and_keeps_legacy_fallback(tmp_path):
    repo = tmp_path / "repo"
    runtime_data = tmp_path / "runtime" / "data"
    runtime_ui_assets = tmp_path / "runtime" / "ui_assets"
    legacy_zip = repo / "data" / "event_preset" / "naia_prompt_preset"
    runtime_zip = runtime_data / "event_preset" / "naia_prompt_preset"

    _write_minimal_event_zip(legacy_zip)
    fallback_service = EventPresetService(repo, data_root=runtime_data, thumbnail_root=runtime_ui_assets)

    assert fallback_service.data_path == legacy_zip

    _write_minimal_event_zip(runtime_zip)
    runtime_service = EventPresetService(repo, data_root=runtime_data, thumbnail_root=runtime_ui_assets)

    assert runtime_service.data_path == runtime_zip
    assert runtime_service.thumbnail_path == runtime_ui_assets / "event_preset_thumbnail"


def test_event_preset_downloader_writes_to_runtime_roots(tmp_path):
    repo = tmp_path / "repo"
    runtime_data = tmp_path / "runtime" / "data"
    runtime_ui_assets = tmp_path / "runtime" / "ui_assets"
    completed = []
    service = EventPresetDownloadService(
        repo,
        status_provider=lambda: {"dataAvailability": {"main": "missing", "thumbnails": "missing"}},
        data_root=runtime_data,
        thumbnail_root=runtime_ui_assets,
        on_complete=lambda: completed.append(True),
    )

    def fake_download_file(*, phase, target_path, **_kwargs):
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if phase == "main":
            _write_minimal_event_zip(target_path)
        else:
            target_path.write_bytes(b"x" * 1_000_000)

    service._download_file = fake_download_file  # type: ignore[method-assign]

    service._run()

    assert (runtime_data / "event_preset" / "naia_prompt_preset").exists()
    assert (runtime_ui_assets / "event_preset_thumbnail").exists()
    assert not (repo / "data" / "event_preset" / "naia_prompt_preset").exists()
    assert not (repo / "data" / "event_preset_thumbnail").exists()
    assert completed == [True]
    assert service.snapshot()["phase"] == "complete"


def test_headless_event_preset_download_service_uses_context_runtime_paths(tmp_path):
    context = WebSessionContext(
        repo_root=tmp_path,
        token_manager=InMemoryTokenManager(),
        headless_generation_execute_enabled=False,
    )
    client = TestClient(create_headless_app(context))

    status = client.get("/api/event-preset/status")

    assert status.status_code == 200
    assert context.event_preset_service.data_path == context.runtime_paths.data_dir / "event_preset" / "naia_prompt_preset"
    assert context.event_preset_service.thumbnail_path == context.runtime_paths.ui_assets_dir / "event_preset_thumbnail"
    assert context.event_preset_download_service.data_root == context.runtime_paths.data_dir
    assert context.event_preset_download_service.thumbnail_root == context.runtime_paths.ui_assets_dir
