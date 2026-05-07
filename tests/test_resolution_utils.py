from core.resolution_utils import (
    MAX_1MP_PIXELS,
    apply_resolution_to_comfyui_workflow,
    nearest_standard_1mp_resolution,
    normalize_artist_thumbnail_resolution,
)


def test_nearest_standard_1mp_resolution_clamps_large_landscape():
    assert nearest_standard_1mp_resolution(4000, 3000) == (1152, 896)


def test_nearest_standard_1mp_resolution_upscales_small_portrait_to_standard():
    width, height = nearest_standard_1mp_resolution(500, 760)
    assert (width, height) == (832, 1216)
    assert width * height <= MAX_1MP_PIXELS


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
