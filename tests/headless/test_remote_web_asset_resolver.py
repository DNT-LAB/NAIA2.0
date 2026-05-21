from pathlib import Path

from fastapi.testclient import TestClient

from app.web import remote_web_dir_is_complete, resolve_remote_web_dir
from core.web_session_app import create_headless_app
from core.web_session_context import WebSessionContext


def _write_remote_web_files(root: Path, marker: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text(marker, encoding="utf-8")
    (root / "style.css").write_text("body { color: white; }", encoding="utf-8")
    (root / "app.js").write_text("console.log('remote');", encoding="utf-8")


def test_remote_web_resolver_prefers_app_web_remote_when_complete(tmp_path):
    app_web = tmp_path / "app" / "web" / "remote"
    legacy_web = tmp_path / "ui" / "remote_web"
    _write_remote_web_files(app_web, "app-web")
    _write_remote_web_files(legacy_web, "legacy-web")

    assert resolve_remote_web_dir(tmp_path) == app_web.resolve()


def test_remote_web_resolver_falls_back_to_legacy_ui_remote_web(tmp_path):
    legacy_web = tmp_path / "ui" / "remote_web"
    _write_remote_web_files(legacy_web, "legacy-web")

    assert resolve_remote_web_dir(tmp_path) == legacy_web.resolve()


def test_remote_web_resolver_accepts_env_override(tmp_path):
    custom_web = tmp_path / "custom-web"
    _write_remote_web_files(custom_web, "custom-web")

    assert resolve_remote_web_dir(
        tmp_path,
        env={"NAIA_REMOTE_WEB_DIR": str(custom_web)},
    ) == custom_web.resolve()


def test_remote_web_dir_is_complete_requires_core_assets(tmp_path):
    root = tmp_path / "app" / "web" / "remote"
    root.mkdir(parents=True)
    (root / "index.html").write_text("", encoding="utf-8")
    (root / "style.css").write_text("", encoding="utf-8")

    assert remote_web_dir_is_complete(root) is False


def test_headless_app_uses_remote_web_resolver(tmp_path):
    legacy_web = tmp_path / "ui" / "remote_web"
    _write_remote_web_files(legacy_web, "legacy-web")
    context = WebSessionContext(repo_root=tmp_path)

    app = create_headless_app(context)

    assert app.state.remote_web_dir == str(legacy_web.resolve())
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert response.text == "legacy-web"


def test_current_checkout_prefers_app_web_remote_source():
    root = Path.cwd()

    assert resolve_remote_web_dir(root) == (root / "app" / "web" / "remote").resolve()
