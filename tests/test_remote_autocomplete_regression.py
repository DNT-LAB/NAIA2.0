import subprocess
from pathlib import Path

from tools.evaluate_autocomplete_regression import (
    evaluate_fixture,
    load_fixture,
    validate_fixture_shape,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "autocomplete_eval_samples.json"
JS_POLICY_TEST = ROOT / "tests" / "js" / "tag_assist_policy_test.mjs"


def test_autocomplete_eval_fixture_shape_and_filters():
    data = load_fixture(FIXTURE_PATH)

    validate_fixture_shape(data)

    assert sum(len(bundle["samples"]) for bundle in data["bundles"]) == 500
    assert [bundle["bundleId"] for bundle in data["bundles"]] == [
        "b01_identity_composition",
        "b02_hair_face_expression",
        "b03_clothing_general",
        "b04_accessory_species_body",
        "b05_pose_action",
        "b06_nsfw_body_exposure",
        "b07_nsfw_act_fluid",
        "b08_background_object",
        "b09_meta_style_text",
        "b10_phrase_normalizer_combo",
    ]


def test_autocomplete_eval_representative_candidates_and_timing_budget():
    data = load_fixture(FIXTURE_PATH)

    summary = evaluate_fixture(data, per_bundle=5)

    assert summary["checked"] == 50
    assert summary["failed"] == 0
    assert summary["p95_ms"] <= 250.0


def test_tag_assist_enter_selection_policy_skips_manual_translation_hints():
    result = subprocess.run(
        ["node", str(JS_POLICY_TEST)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
