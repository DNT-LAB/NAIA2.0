import json
from pathlib import Path
import subprocess
import sys

from tools.check_runtime_asset_classification import (
    REQUIRED_DECISION_IDS,
    validation_payload,
    validate_runtime_asset_classification,
)


def test_runtime_asset_classification_accepts_current_manifest():
    payload = validation_payload()

    assert payload["ok"] is True
    assert payload["decision_count"] >= len(REQUIRED_DECISION_IDS)
    assert payload["violations"] == []


def test_runtime_asset_classification_covers_required_large_asset_groups():
    manifest = json.loads(
        Path("release_assets/manifests/runtime_asset_classification.json").read_text(encoding="utf-8")
    )
    decisions = {item["id"]: item for item in manifest["decisions"]}

    assert set(REQUIRED_DECISION_IDS) <= set(decisions)
    assert decisions["random_prompt_runner_cache"]["runtime_destination"] == "cache/naia_temp_rows.parquet"
    assert decisions["random_prompt_runner_cache"]["release_action"] == "exclude"
    assert decisions["artist_thumbnail_bundles"]["runtime_destination"] == "ui_assets/artist_thumb"
    assert decisions["generated_tag_dictionaries"]["decision"] == "runtime_generated_index"
    assert decisions["root_image_samples"]["decision"] == "local_sample_or_debug"
    assert decisions["user_wildcards"]["decision"] == "runtime_user_state"
    assert decisions["user_wildcards"]["runtime_destination"] == "wildcards"
    assert decisions["user_wildcards"]["release_exclude_patterns"] == ["wildcards/**"]
    assert decisions["bootstrap_source_assets"]["release_action"] == "include"
    assert "wildcards/**" not in decisions["bootstrap_source_assets"]["release_include_patterns"]
    assert "data/clothes_list.txt" in decisions["bootstrap_source_assets"]["release_include_patterns"]
    assert "data/taglist/*.json" in decisions["bootstrap_source_assets"]["release_include_patterns"]
    assert decisions["downloaded_tag_archives"]["release_action"] == "exclude"
    assert decisions["downloaded_tag_archives"]["release_exclude_patterns"] == ["data/tags/**", "data/tagger/**"]
    assert decisions["installer_seed_templates"]["release_action"] == "include"
    assert decisions["installer_seed_templates"]["release_include_patterns"] == [
        "app_data_template/**",
        "release_assets/samples/**",
    ]


def test_runtime_asset_classification_rejects_missing_release_exclude(tmp_path):
    classification = {
        "version": 1,
        "decisions": [
            {
                "id": item_id,
                "patterns": [f"{item_id}.bin"],
                "decision": "runtime_generated_cache",
                "runtime_destination": "cache",
                "release_action": "exclude",
                "release_exclude_patterns": [f"{item_id}.bin"],
            }
            for item_id in REQUIRED_DECISION_IDS
        ],
    }
    release_manifest = {"include": {}, "exclude": {"some_group": []}}
    classification_path = tmp_path / "classification.json"
    release_path = tmp_path / "release.json"
    classification_path.write_text(json.dumps(classification), encoding="utf-8")
    release_path.write_text(json.dumps(release_manifest), encoding="utf-8")

    violations = validate_runtime_asset_classification(classification_path, release_path)

    assert violations
    assert any("missing exclude patterns" in violation.reason for violation in violations)


def test_runtime_asset_classification_cli_outputs_json():
    result = subprocess.run(
        [sys.executable, "tools/check_runtime_asset_classification.py"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["ok"] is True
    assert "random_prompt_runner_cache" in payload["required_decisions"]
