import io
import json
import os
import sys

from PIL import Image

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.comfyui_service import ComfyUIService  # noqa: E402
from core.comfyui_workflow_manager import ComfyUIWorkflowManager  # noqa: E402
from utils.comfyui_png_metadata import (  # noqa: E402
    enrich_comfyui_png_bytes,
    extract_comfyui_workflow_metadata_from_image_bytes,
)
from utils.image_info import ImageMetadataExtractor  # noqa: E402


def _png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _comfyui_workflow_webp_bytes(workflow_api, workflow_ui):
    image = Image.new("RGB", (4, 4), "white")
    exif = image.getexif()
    exif[0x0110] = "prompt:" + json.dumps(workflow_api, ensure_ascii=False, separators=(",", ":"))
    exif[0x010F] = "workflow:" + json.dumps(workflow_ui, ensure_ascii=False, separators=(",", ":"))
    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", exif=exif)
    return buffer.getvalue()


def test_comfyui_result_selection_prefers_save_image_output(monkeypatch):
    service = ComfyUIService("http://127.0.0.1:8188")

    class Response:
        status_code = 200

        def json(self):
            return {
                "prompt-1": {
                    "outputs": {
                        "9": {"images": [{"filename": "preview.png", "subfolder": "", "type": "temp"}]},
                        "7": {"images": [{"filename": "saved.png", "subfolder": "", "type": "output"}]},
                    }
                }
            }

    def fake_get(url, timeout=10):
        assert url.endswith("/history/prompt-1")
        return Response()

    workflow = {
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0]}},
        "9": {"class_type": "PreviewImage", "inputs": {"images": ["6", 0]}},
    }
    monkeypatch.setattr("core.comfyui_service.requests.get", fake_get)

    result = service.get_generation_result("prompt-1", workflow=workflow)

    assert result[0]["filename"] == "saved.png"
    assert result[0]["source_node_type"] == "SaveImage"


def test_comfyui_result_selection_prefers_webp_save_output(monkeypatch):
    service = ComfyUIService("http://127.0.0.1:8188")

    class Response:
        status_code = 200

        def json(self):
            return {
                "prompt-1": {
                    "outputs": {
                        "9": {"images": [{"filename": "preview.png", "subfolder": "", "type": "temp"}]},
                        "57": {"images": [{"filename": "saved.webp", "subfolder": "", "type": "output"}]},
                    }
                }
            }

    def fake_get(url, timeout=10):
        assert url.endswith("/history/prompt-1")
        return Response()

    workflow = {
        "57": {"class_type": "SaveAnimatedWEBP", "inputs": {"images": ["8", 0]}},
        "9": {"class_type": "PreviewImage", "inputs": {"images": ["8", 0]}},
    }
    monkeypatch.setattr("core.comfyui_service.requests.get", fake_get)

    result = service.get_generation_result("prompt-1", workflow=workflow)

    assert result[0]["filename"] == "saved.webp"
    assert result[0]["source_node_type"] == "SaveAnimatedWEBP"


def test_comfyui_png_enrichment_adds_standard_and_naia_chunks():
    workflow_api = {
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "current prompt"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "current negative"}},
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 123,
                "steps": 22,
                "cfg": 6.5,
                "sampler_name": "euler",
                "scheduler": "normal",
                "positive": ["1", 0],
                "negative": ["2", 0],
            },
        },
    }
    workflow_ui = {"nodes": [{"id": 1, "type": "CLIPTextEncode", "widgets_values": ["current prompt"]}], "links": []}
    generation_params = {
        "api_mode": "COMFYUI",
        "input": "current prompt",
        "negative_prompt": "current negative",
        "steps": 22,
        "seed": 123,
        "cfg_scale": 6.5,
        "sampler": "euler",
        "workflow": workflow_api,
        "credential": "http://secret.local",
    }

    enriched, image, changed = enrich_comfyui_png_bytes(
        _png_bytes(),
        workflow_api=workflow_api,
        workflow_ui=workflow_ui,
        generation_params=generation_params,
        prompt_context={"main_prompt": "main prompt"},
        api_metadata={"backend": "COMFYUI"},
    )

    assert changed is True
    assert image.info["prompt"] == json.dumps(workflow_api, ensure_ascii=False, separators=(",", ":"))
    assert image.info["workflow"] == json.dumps(workflow_ui, ensure_ascii=False, separators=(",", ":"))
    assert image.info["workflow_api"] == image.info["prompt"]
    assert "credential" not in image.info["naia_generation_params"]
    assert "workflow" not in image.info["naia_generation_params"]

    extracted = ImageMetadataExtractor.extract_metadata(Image.open(io.BytesIO(enriched)))
    assert extracted["type"] == "comfyui"
    assert extracted["prompt"] == "main prompt"
    assert extracted["parameters"]["steps"] == 22
    assert extracted["parameters"]["seed"] == 123


def test_enriched_native_result_can_reload_as_custom_workflow():
    source_mgr = ComfyUIWorkflowManager()
    params = {
        "model": "new-checkpoint.safetensors",
        "input": "reload prompt",
        "negative_prompt": "reload negative",
        "seed": 321,
        "steps": 24,
        "cfg_scale": 7.0,
        "sampler": "euler",
        "scheduler": "normal",
        "width": 640,
        "height": 768,
        "workflow_type": "checkpoint",
        "sampling_mode": "eps",
    }
    workflow_api = source_mgr.apply_params_to_workflow(params)
    workflow_ui = source_mgr.get_last_applied_workflow_ui()

    enriched, image, changed = enrich_comfyui_png_bytes(
        _png_bytes(),
        workflow_api=workflow_api,
        workflow_ui=workflow_ui,
        generation_params={"api_mode": "COMFYUI", "input": "reload prompt"},
    )

    assert changed is True
    assert "workflow" in image.info
    assert "prompt" in image.info
    assert "workflow_api" in image.info

    metadata = extract_comfyui_workflow_metadata_from_image_bytes(enriched)

    target_mgr = ComfyUIWorkflowManager()
    assert target_mgr.load_workflow_from_metadata(metadata) is True
    assert target_mgr.user_workflow is not None


def test_webp_workflow_image_metadata_can_reload_as_custom_workflow():
    source_mgr = ComfyUIWorkflowManager()
    params = {
        "model": "new-checkpoint.safetensors",
        "input": "webp reload prompt",
        "negative_prompt": "webp reload negative",
        "seed": 321,
        "steps": 24,
        "cfg_scale": 7.0,
        "sampler": "euler",
        "scheduler": "normal",
        "width": 640,
        "height": 768,
        "workflow_type": "checkpoint",
        "sampling_mode": "eps",
    }
    workflow_api = source_mgr.apply_params_to_workflow(params)
    workflow_ui = source_mgr.get_last_applied_workflow_ui()
    webp_bytes = _comfyui_workflow_webp_bytes(workflow_api, workflow_ui)

    metadata = extract_comfyui_workflow_metadata_from_image_bytes(webp_bytes)

    assert json.loads(metadata["prompt"]) == workflow_api
    assert json.loads(metadata["workflow"]) == workflow_ui
    target_mgr = ComfyUIWorkflowManager()
    assert target_mgr.load_workflow_from_metadata(metadata) is True
    assert target_mgr.user_workflow is not None
