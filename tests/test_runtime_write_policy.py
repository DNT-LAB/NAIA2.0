import json
from pathlib import Path
import subprocess
import sys

from tools.check_runtime_write_policy import check_runtime_write_policy


POLICY_PATH = Path("release_assets/manifests/runtime_write_policy.json")


def test_runtime_write_policy_accepts_current_runtime_download_owners():
    payload = check_runtime_write_policy(POLICY_PATH)

    assert payload["ok"] is True
    assert payload["owner_count"] >= 6
    assert "core/event_preset_download_service.py" in payload["download_api_sources"]
    assert "core/artist_thumbnail_service.py" in payload["download_api_sources"]
    assert "core/web_session_app.py" in payload["download_api_sources"]
    assert "utils/cloudflared.py" in payload["download_api_sources"]
    assert payload["violations"] == []


def test_runtime_write_policy_declares_compatibility_exceptions():
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    exceptions = {item["feature"] for item in policy["known_compatibility_exceptions"]}

    assert "legacy_save_read_fallback" in exceptions
    assert "source_bootstrap_data_reads" in exceptions
    assert "development_tools" in exceptions


def test_runtime_write_policy_cli_outputs_machine_readable_json():
    result = subprocess.run(
        [sys.executable, "tools/check_runtime_write_policy.py"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["ok"] is True
    assert payload["violations"] == []


def test_runtime_write_policy_rejects_unowned_download_api_source(tmp_path):
    root = tmp_path / "repo"
    source = root / "core" / "new_downloader.py"
    source.parent.mkdir(parents=True)
    source.write_text("import urllib.request\nurllib.request.urlopen('https://example.test')\n", encoding="utf-8")
    manifest_dir = root / "release_assets" / "manifests"
    manifest_dir.mkdir(parents=True)
    runtime_policy_path = manifest_dir / "runtime_asset_policy.json"
    runtime_policy_path.write_text(
        json.dumps({"blocked_future_download_targets": ["data/**", "ui/**", "./*"]}),
        encoding="utf-8",
    )
    policy_path = manifest_dir / "runtime_write_policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "required_runtime_download_owners": [],
                "download_api_scan": {
                    "source_roots": ["core"],
                    "patterns": ["urllib.request.urlopen"],
                    "ignored_sources": [],
                },
                "known_compatibility_exceptions": [],
            }
        ),
        encoding="utf-8",
    )

    payload = check_runtime_write_policy(
        policy_path,
        runtime_policy_path=runtime_policy_path,
        repo_root=root,
    )

    assert payload["ok"] is False
    assert payload["violations"] == [
        {
            "path": "core/new_downloader.py",
            "reason": "download API source is not registered in runtime write policy owners",
        }
    ]


def test_runtime_write_policy_ignores_release_output_roots(tmp_path):
    root = tmp_path / "repo"
    generated = root / "app" / "electron" / "dist" / "NAIA-Web" / "resources" / "naia-backend" / "core" / "copied.py"
    generated.parent.mkdir(parents=True)
    generated.write_text("import urllib.request\nurllib.request.urlopen('https://example.test')\n", encoding="utf-8")
    manifest_dir = root / "release_assets" / "manifests"
    manifest_dir.mkdir(parents=True)
    runtime_policy_path = manifest_dir / "runtime_asset_policy.json"
    runtime_policy_path.write_text(
        json.dumps({"blocked_future_download_targets": ["data/**", "ui/**", "./*"]}),
        encoding="utf-8",
    )
    policy_path = manifest_dir / "runtime_write_policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "required_runtime_download_owners": [],
                "download_api_scan": {
                    "source_roots": ["app"],
                    "patterns": ["urllib.request.urlopen"],
                    "ignored_roots": ["app/electron/dist"],
                    "ignored_sources": [],
                },
                "known_compatibility_exceptions": [],
            }
        ),
        encoding="utf-8",
    )

    payload = check_runtime_write_policy(
        policy_path,
        runtime_policy_path=runtime_policy_path,
        repo_root=root,
    )

    assert payload["ok"] is True
    assert payload["download_api_sources"] == []


def test_runtime_write_policy_rejects_missing_required_snippet(tmp_path):
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    owner = policy["required_runtime_download_owners"][0]
    owner["must_contain"] = ["definitely_missing_runtime_snippet"]
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    payload = check_runtime_write_policy(policy_path)

    assert payload["ok"] is False
    assert payload["violations"][0]["reason"] == "required runtime-path snippet missing"
