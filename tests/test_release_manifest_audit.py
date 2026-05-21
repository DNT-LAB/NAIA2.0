from pathlib import Path
import subprocess
import sys

from tools.release_manifest_audit import audit_payload


def test_release_manifest_audit_accepts_minimal_clean_release(tmp_path):
    release = tmp_path / "NAIA-Web"
    (release / "resources" / "naia-backend").mkdir(parents=True)
    (release / "resources" / "ui" / "remote_web").mkdir(parents=True)
    (release / "resources" / "naia-backend" / "data" / "source").mkdir(parents=True)
    (release / "resources" / "naia-backend" / "data" / "taglist").mkdir(parents=True)
    (release / "resources" / "python").mkdir(parents=True)
    (release / "NAIA.exe").write_text("", encoding="utf-8")
    (release / "resources" / "naia-backend" / "NAIA_web_headless.py").write_text("", encoding="utf-8")
    (release / "resources" / "ui" / "remote_web" / "index.html").write_text("", encoding="utf-8")
    (release / "resources" / "naia-backend" / "data" / "source" / "sample.json").write_text("", encoding="utf-8")
    (release / "resources" / "naia-backend" / "data" / "clothes_list.txt").write_text("", encoding="utf-8")
    (release / "resources" / "naia-backend" / "data" / "taglist" / "expression_tags.json").write_text("", encoding="utf-8")
    (release / "resources" / "python" / "python.exe").write_text("", encoding="utf-8")
    (release / "resources" / "python" / "Lib" / "venv").mkdir(parents=True)
    (release / "resources" / "python" / "Lib" / "venv" / "__init__.py").write_text("", encoding="utf-8")

    payload = audit_payload(release)

    assert payload["ok"] is True
    assert payload["violations"] == []


def test_release_manifest_audit_rejects_legacy_desktop_pyqt_and_runtime_state(tmp_path):
    release = tmp_path / "NAIA-Web"
    blocked_files = [
        release / "legacy_desktop" / "main.py",
        release / "resources" / "naia-backend" / "core" / "context.py",
        release / "resources" / "naia-backend" / "core" / "image_crud_controller.py",
        release / "resources" / "naia-backend" / "core" / "tag_data_manager.py",
        release / "resources" / "naia-backend" / "tabs" / "comic_generator" / "comic_generator_tab.py",
        release / "resources" / "naia-backend" / "ui" / "variational" / "variational_generation_window.py",
        release / "resources" / "naia-backend" / "experimental" / "ontology_visualizer" / "ontology_visualizer.py",
        release / "resources" / "naia-backend" / "temp" / "ezmode" / "ezmode_prompt_display.py",
        release / "resources" / "naia-backend" / "PyQt6" / "__init__.py",
        release / "resources" / "python" / "Lib" / "site-packages" / "PyQt6" / "__init__.py",
        release / "resources" / "naia-backend" / "app" / "electron" / "node_modules" / "electron" / "index.js",
        release / "resources" / "naia-backend" / "app" / "electron" / "dist" / "NAIA-Web" / "stale.txt",
        release / "resources" / "data" / "artist_thumbnail.json",
        release / "resources" / "data" / "tags" / "tags.parquet",
        release / "resources" / "naia-backend" / "data" / "tags" / "tags_129.parquet",
        release / "resources" / "data" / "event_preset" / "preset.json",
        release / "resources" / "data" / "event_preset_thumbnail",
        release / "resources" / "naia-backend" / "artist_dictionary.py",
        release / "resources" / "ui" / "assets" / "downloaded" / "bundle.bin",
        release / "resources" / "ui" / "event_preset" / "preset.json",
        release / "resources" / "ui" / "remote_web" / "AGENTS.md",
        release / "core" / ".claude" / "note.md",
        release / "utils" / ".cloudflared_bin" / "cloudflared.exe",
        release / "logs" / "app.log",
        release / "output" / "00001.png",
        release / "user-data" / "config" / "settings.json",
        release / "docs" / "plan.md",
        release / "resources" / "naia-backend" / "note.md",
        release / "resources" / "naia-backend" / "wildcards" / "favorite_artist.txt",
        release / "wildcards" / "artist.xlsx",
        release / "sample.xlsx",
        release / "sample.naiv4vibe",
        release / "00001.png",
        release / "NAIA_cold_v4.py",
    ]
    for path in blocked_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    payload = audit_payload(release)
    reasons = "\n".join(item["reason"] for item in payload["violations"])
    paths = "\n".join(item["path"] for item in payload["violations"])

    assert payload["ok"] is False
    assert "legacy_desktop" in reasons
    assert "core/context.py" in reasons
    assert "core/image_crud_controller.py" in reasons
    assert "core/tag_data_manager.py" in reasons
    assert "tabs/comic_generator" in reasons
    assert "ui/variational" in reasons
    assert "experimental/ontology_visualizer" in reasons
    assert "temp/ezmode" in reasons
    assert "PyQt6" in reasons
    assert "node_modules" in reasons
    assert "app/electron/dist" in reasons
    assert "logs" in reasons
    assert "output" in reasons
    assert "user-data" in reasons
    assert "docs" in reasons
    assert "*.md" in reasons
    assert "wildcards" in reasons
    assert "data/**" in reasons
    assert "artist_dictionary.py" in reasons
    assert "ui/*/downloaded" in reasons
    assert "ui/event_preset" in reasons
    assert "AGENTS.md" in reasons
    assert ".claude" in reasons
    assert ".cloudflared_bin" in reasons
    assert "*.xlsx" in reasons
    assert "*.naiv4vibe" in reasons
    assert "00001.png" in reasons
    assert "NAIA_cold_v4.py" in reasons
    assert "legacy_desktop/main.py" in paths


def test_release_manifest_audit_cli_returns_nonzero_for_violations(tmp_path):
    release = tmp_path / "NAIA-Web"
    (release / "tests").mkdir(parents=True)
    (release / "tests" / "test_smoke.py").write_text("", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "tools/release_manifest_audit.py", str(release)],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert '"ok": false' in result.stdout
    assert "tests" in result.stdout
