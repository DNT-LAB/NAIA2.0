import json

import pytest

from core.vibe_cluster_resolver import (
    VibeClusterPromptError,
    apply_vibe_cluster_prompt_override,
    search_vibe_clusters,
)
from core.nai_vibe_limits import MAX_NAI_VIBE_REFERENCES


def _write_cluster(root, name, *, cluster_id="cluster1", enabled=True):
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{cluster_id}.json"
    path.write_text(
        json.dumps({
            "id": cluster_id,
            "name": name,
            "description": "sample cluster",
            "model": "NAID4.5F",
            "normalize_strength": True,
            "frames": [
                {
                    "encodings": {"0.5": "encoded-half", "1.0": "encoded-full"},
                    "reference_strength": 0.8,
                    "information_extracted": 0.6,
                    "is_enabled": enabled,
                    "target_model": "NAID4.5F",
                },
                {
                    "encodings": {"1.0": "encoded-b"},
                    "reference_strength": 0.4,
                    "information_extracted": 1.0,
                    "is_enabled": True,
                    "target_model": "NAID4.5F",
                },
            ],
        }),
        encoding="utf-8",
    )
    return path


def test_apply_vibe_cluster_prompt_override_injects_request_params(tmp_path):
    root = tmp_path / "save" / "vibe_transfer_clusters"
    _write_cluster(root, "MyVibe")
    params = {
        "api_mode": "NAI",
        "model": "NAID4.5F",
        "input": "1girl, vibe:MyVibe, best quality",
    }

    result = apply_vibe_cluster_prompt_override(params, root=root)

    assert result.applied is True
    assert params["input"] == "1girl, best quality"
    assert params["_vibe_cluster_override"]["name"] == "MyVibe"
    assert params["reference_image_multiple"] == ["encoded-half", "encoded-b"]
    assert params["reference_strength_multiple"] == [0.8, 0.4]
    assert params["normalize_reference_strength_multiple"] is True
    assert "reference_information_extracted_multiple" not in params


def test_apply_vibe_cluster_prompt_override_adds_naid3_ie_values(tmp_path):
    root = tmp_path / "save" / "vibe_transfer_clusters"
    _write_cluster(root, "Nai3Vibe")
    params = {
        "api_mode": "NAI",
        "model": "NAID3",
        "input": "vibe:Nai3Vibe, solo",
    }

    apply_vibe_cluster_prompt_override(params, root=root)

    assert params["input"] == "solo"
    assert params["reference_information_extracted_multiple"] == [0.5, 1.0]


def test_apply_vibe_cluster_prompt_override_accepts_korean_name(tmp_path):
    root = tmp_path / "save" / "vibe_transfer_clusters"
    _write_cluster(root, "테스트Vibe1")
    params = {
        "api_mode": "NAI",
        "model": "NAID4.5F",
        "input": "solo, vibe:테스트Vibe1",
    }

    apply_vibe_cluster_prompt_override(params, root=root)

    assert params["input"] == "solo"
    assert params["_vibe_cluster_override"]["name"] == "테스트Vibe1"


def test_apply_vibe_cluster_prompt_override_rejects_unknown_cluster(tmp_path):
    params = {
        "api_mode": "NAI",
        "model": "NAID4.5F",
        "input": "1girl, vibe:Missing",
    }

    with pytest.raises(VibeClusterPromptError, match="not found"):
        apply_vibe_cluster_prompt_override(params, root=tmp_path / "save" / "vibe_transfer_clusters")


def test_apply_vibe_cluster_prompt_override_rejects_clusters_above_vibe_limit(tmp_path):
    root = tmp_path / "save" / "vibe_transfer_clusters"
    root.mkdir(parents=True, exist_ok=True)
    frames = [
        {
            "encodings": {"1.0": f"encoded-{index}"},
            "reference_strength": 0.05,
            "information_extracted": 1.0,
            "is_enabled": True,
            "target_model": "NAID4.5F",
        }
        for index in range(MAX_NAI_VIBE_REFERENCES + 1)
    ]
    (root / "too-many.json").write_text(
        json.dumps({
            "id": "too-many",
            "name": "TooMany",
            "model": "NAID4.5F",
            "frames": frames,
        }),
        encoding="utf-8",
    )
    params = {
        "api_mode": "NAI",
        "model": "NAID4.5F",
        "input": "vibe:TooMany",
    }

    with pytest.raises(VibeClusterPromptError, match="too many enabled frames"):
        apply_vibe_cluster_prompt_override(params, root=root)


def test_search_vibe_clusters_returns_prompt_completion_shape(tmp_path):
    root = tmp_path / "save" / "vibe_transfer_clusters"
    _write_cluster(root, "AlphaVibe")
    _write_cluster(root, "Bad Vibe", cluster_id="legacy-invalid")

    results = search_vibe_clusters("alpha", root=root)

    assert len(results) == 1
    assert results[0]["tag"] == "AlphaVibe"
    assert results[0]["value"] == "vibe:AlphaVibe"
    assert results[0]["_wc_type"] == "vibe_cluster"
