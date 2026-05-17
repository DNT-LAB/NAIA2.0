from core.resolution_utils import (
    ANIMA_MAX_DIMENSION,
    ANIMA_MAX_PIXELS,
    ANIMA_MIN_PIXELS,
    ANIMA_RESOLUTION_LABELS,
    ANIMA_RESOLUTIONS,
    MAX_1MP_PIXELS,
    apply_resolution_to_comfyui_workflow,
    anima_resolution_preset_labels,
    nearest_anima_preset_resolution,
    nearest_anima_resolution,
    nearest_standard_1mp_resolution,
    normalize_artist_thumbnail_resolution,
    parse_resolution_pair,
)


def test_nearest_standard_1mp_resolution_clamps_large_landscape():
    assert nearest_standard_1mp_resolution(4000, 3000) == (1152, 896)


def test_nearest_standard_1mp_resolution_upscales_small_portrait_to_standard():
    width, height = nearest_standard_1mp_resolution(500, 760)
    assert (width, height) == (832, 1216)
    assert width * height <= MAX_1MP_PIXELS


def test_anima_resolution_presets_cover_requested_bounds():
    assert ANIMA_RESOLUTION_LABELS[0] == "512 x 512"
    assert "1536 x 1536" in ANIMA_RESOLUTION_LABELS
    assert len(ANIMA_RESOLUTIONS) == 49
    for width, height in ANIMA_RESOLUTIONS:
        assert width % 64 == 0
        assert height % 64 == 0
        assert width >= 384
        assert height >= 384
        assert width <= ANIMA_MAX_DIMENSION
        assert height <= ANIMA_MAX_DIMENSION
        assert ANIMA_MIN_PIXELS <= width * height <= ANIMA_MAX_PIXELS


def test_nearest_anima_resolution_fits_to_anima_ladder():
    assert nearest_anima_resolution(768, 768) == (768, 768)
    assert nearest_anima_resolution(400, 400) == (512, 512)
    assert nearest_anima_resolution(2496, 3648) == (1216, 1792)


def test_anima_resolution_preset_candidates_stay_within_selected_size():
    assert "640 x 384" in anima_resolution_preset_labels("draft")
    assert "512 x 768" not in anima_resolution_preset_labels("draft")
    assert nearest_anima_preset_resolution(640, 960, "draft") == (448, 640)
    assert anima_resolution_preset_labels("quality")[0] == "1344 x 1344"
    assert "1536 x 1536" not in anima_resolution_preset_labels("quality")
    assert nearest_anima_preset_resolution(2496, 3648, "quality") == (1088, 1600)
    assert nearest_anima_preset_resolution(2496, 3648, "max") == (1216, 1792)


def test_anima_resolution_labels_are_parseable():
    assert parse_resolution_pair(ANIMA_RESOLUTION_LABELS[-1]) == (1792, 1216)


def test_normalize_artist_thumbnail_resolution_updates_params_label():
    params = {"width": 4000, "height": 3000}
    changed, original, normalized = normalize_artist_thumbnail_resolution(params)

    assert changed is True
    assert original == (4000, 3000)
    assert normalized == (1152, 896)
    assert params["width"] == 1152
    assert params["height"] == 896
    assert params["resolution"] == "1152 x 896"


def test_normalize_artist_thumbnail_resolution_recovers_invalid_values():
    params = {"width": "bad", "height": None}
    changed, original, normalized = normalize_artist_thumbnail_resolution(params)

    assert changed is True
    assert original == (0, 0)
    assert normalized == (1024, 1024)
    assert params["width"] == 1024
    assert params["height"] == 1024


def test_apply_resolution_to_comfyui_workflow_patches_latent_only():
    workflow = {
        "1": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 4000, "height": 3000, "batch_size": 1},
        },
        "2": {
            "class_type": "CLIPTextEncodeSDXL",
            "inputs": {"width": 4000, "height": 3000, "text": "prompt"},
        },
    }

    patched = apply_resolution_to_comfyui_workflow(workflow, 1152, 896)

    assert patched == 1
    assert workflow["1"]["inputs"]["width"] == 1152
    assert workflow["1"]["inputs"]["height"] == 896
    assert workflow["2"]["inputs"]["width"] == 4000
    assert workflow["2"]["inputs"]["height"] == 3000
