import json
from pathlib import Path
import subprocess
import sys

from tools.release_manifest_audit import audit_payload
from tools.stage_release_assets import collect_release_files, stage_release_assets


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_collect_release_files_includes_manifest_sources_and_excludes_runtime_state(tmp_path):
    _write(tmp_path / "NAIA_web_headless.py")
    _write(tmp_path / "requirements-headless.txt")
    _write(tmp_path / "app" / "__init__.py")
    _write(tmp_path / "core" / "service.py")
    _write(tmp_path / "core" / "note.md")
    _write(tmp_path / "core" / ".claude" / "note.md")
    _write(tmp_path / "interfaces" / "base_module.py")
    _write(tmp_path / "utils" / ".cloudflared_bin" / "cloudflared.exe")
    _write(tmp_path / "app" / "backend" / "server" / "headless.py")
    _write(tmp_path / "app" / "web" / "__init__.py")
    _write(tmp_path / "app" / "web" / "assets.py")
    _write(tmp_path / "app" / "electron" / "package.json")
    _write(tmp_path / "app" / "electron" / "node_modules" / "electron" / "index.js")
    _write(tmp_path / "app" / "electron" / "dist" / "NAIA-Web" / "stale.txt")
    _write(tmp_path / "app" / "web" / "remote" / "index.html")
    _write(tmp_path / "app" / "web" / "remote" / "AGENTS.md")
    _write(tmp_path / "app" / "web" / "remote" / "__pycache__" / "assets.pyc")
    _write(tmp_path / "app_data_template" / ".gitkeep")
    _write(tmp_path / "release_assets" / "samples" / ".gitkeep")
    _write(tmp_path / "data" / "KR_tags.parquet")
    _write(tmp_path / "data" / "e621_KR_tags.parquet")
    _write(tmp_path / "data" / "clothes_list.txt")
    _write(tmp_path / "data" / "color.txt")
    _write(tmp_path / "data" / "characteristic_list.txt")
    _write(tmp_path / "data" / "copyright_groups.json")
    _write(tmp_path / "data" / "character_analysis.json")
    _write(tmp_path / "data" / "taglist" / "unique_tags.json")
    _write(tmp_path / "data" / "tags" / "tags_129.parquet")
    _write(tmp_path / "data" / "tags" / "tags_130.parquet")
    _write(tmp_path / "wildcards" / "artist.txt")
    _write(tmp_path / "wildcards" / "artist.xlsx")
    _write(tmp_path / "ui" / "remote_web" / "index.html")
    _write(tmp_path / "legacy_desktop" / "main.py")
    _write(tmp_path / "save" / "state.json")
    _write(tmp_path / "output" / "00001.png")

    files = {path.as_posix() for path in collect_release_files(tmp_path)}

    assert "NAIA_web_headless.py" in files
    assert "app/__init__.py" in files
    assert "core/service.py" in files
    assert "core/note.md" not in files
    assert "core/.claude/note.md" not in files
    assert "interfaces/base_module.py" in files
    assert "utils/.cloudflared_bin/cloudflared.exe" not in files
    assert "app/backend/server/headless.py" in files
    assert "app/web/__init__.py" in files
    assert "app/web/assets.py" in files
    assert "app/electron/package.json" in files
    assert "app/electron/node_modules/electron/index.js" not in files
    assert "app/electron/dist/NAIA-Web/stale.txt" not in files
    assert "app/web/remote/index.html" in files
    assert "app/web/remote/AGENTS.md" not in files
    assert "app/web/remote/__pycache__/assets.pyc" not in files
    assert "app_data_template/.gitkeep" in files
    assert "release_assets/samples/.gitkeep" in files
    assert "data/KR_tags.parquet" not in files
    assert "data/e621_KR_tags.parquet" not in files
    assert "data/clothes_list.txt" in files
    assert "data/color.txt" in files
    assert "data/characteristic_list.txt" in files
    assert "data/copyright_groups.json" not in files
    assert "data/character_analysis.json" not in files
    assert "data/taglist/unique_tags.json" in files
    assert "data/tags/tags_129.parquet" not in files
    assert "data/tags/tags_130.parquet" not in files
    assert "wildcards/artist.txt" not in files
    assert "wildcards/artist.xlsx" not in files
    assert "ui/remote_web/index.html" not in files
    assert "legacy_desktop/main.py" not in files
    assert "save/state.json" not in files
    assert "output/00001.png" not in files


def test_stage_release_assets_copy_outputs_auditable_tree(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "stage"
    _write(source / "NAIA_web_headless.py")
    _write(source / "requirements-headless.txt")
    _write(source / "app" / "__init__.py")
    _write(source / "core" / "service.py")
    _write(source / "interfaces" / "base_module.py")
    _write(source / "app" / "backend" / "server" / "headless.py")
    _write(source / "app" / "web" / "__init__.py")
    _write(source / "app" / "web" / "assets.py")
    _write(source / "app" / "electron" / "package.json")
    _write(source / "app" / "web" / "remote" / "index.html")
    _write(source / "ui" / "remote_web" / "index.html")
    _write(source / "legacy_desktop" / "main.py")

    result = stage_release_assets(source, target, copy=True)
    audit = audit_payload(target)

    assert result.copied is True
    assert (target / "NAIA_web_headless.py").exists()
    assert (target / "legacy_desktop" / "main.py").exists() is False
    assert audit["ok"] is True


def test_stage_release_assets_cli_dry_run(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "stage"
    _write(source / "NAIA_web_headless.py")
    _write(source / "requirements-headless.txt")

    result = subprocess.run(
        [
            sys.executable,
            "tools/stage_release_assets.py",
            "--source",
            str(source),
            "--target",
            str(target),
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["copied"] is False
    assert "NAIA_web_headless.py" in payload["files"]
    assert target.exists() is False
