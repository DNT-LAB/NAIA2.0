"""ComfyUI 워크플로우 호환성 / 모델 잠금 (Task 179.5) 헤드리스 검증.

테스트 대상:
- validate_and_map_workflow  : CheckpointLoaderSimple / UNETLoader+CLIPLoader / 커스텀 로더
- apply_params_to_workflow   : LOCKED 워크플로우에서 모델 치환이 스킵되는지
- analyze_workflow_for_ui    : import 팝업용 locked_loader_class / locked_model_display 전달
- 이벤트 발행                : load / clear 시 comfyui_workflow_changed payload

fixtures/anima_int8_metadata.json 은 실제 ANIMA INT8 PNG 의 tEXt 청크(prompt + workflow)를
dump 한 것. 레포에 포함하여 Downloads 경로 의존성을 제거.

실행: `python tests/comfyui/test_workflow_compat.py`
"""

import json
import os
import sys
import traceback

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.comfyui_workflow_manager import ComfyUIWorkflowManager  # noqa: E402
from core.comfyui_service import ComfyUIService  # noqa: E402
from utils.comfyui_png_metadata import extract_comfyui_workflow_metadata_from_upload_bytes  # noqa: E402


FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
ANIMA_INT8_FIXTURE = os.path.join(FIXTURES_DIR, "anima_int8_metadata.json")


def load_anima_int8_metadata():
    with open(ANIMA_INT8_FIXTURE, "r", encoding="utf-8") as f:
        return json.load(f)


class MockAppContext:
    """publish 만 기록하는 최소 AppContext 대체."""

    def __init__(self):
        self.events = []

    def publish(self, event_name, data=None):
        self.events.append((event_name, data))


# ---------------------------------------------------------------------------
# 1. Native CheckpointLoaderSimple
# ---------------------------------------------------------------------------

def test_native_checkpoint():
    mgr = ComfyUIWorkflowManager()
    ok, nm = mgr.validate_and_map_workflow(mgr.base_workflow)
    assert ok, f"validate should pass for base_workflow: {nm}"
    assert nm["model_compat"] == "native_checkpoint"
    assert nm["workflow_type"] == "checkpoint"
    assert nm["checkpoint_loader"] == "1"
    assert "locked_loader_class" not in nm
    assert "locked_model_display" not in nm


# ---------------------------------------------------------------------------
# 2. Native UNETLoader + CLIPLoader
# ---------------------------------------------------------------------------

def test_native_unet():
    mgr = ComfyUIWorkflowManager()
    ok, nm = mgr.validate_and_map_workflow(mgr.anima_workflow)
    assert ok, f"validate should pass for anima_workflow: {nm}"
    assert nm["model_compat"] == "native_unet"
    assert nm["workflow_type"] == "unet"
    assert nm["unet_loader"] == "44"
    assert nm["clip_loader"] == "45"
    assert nm["vae_loader"] == "15"
    assert nm["rescale_cfg"] == "46"


# ---------------------------------------------------------------------------
# 3. LOCKED UNKNOWN — ANIMA INT8 커스텀 로더 체인
# ---------------------------------------------------------------------------

def test_locked_unknown_anima_int8_identifies_terminal_loader():
    """샘플러 역추적이 패치 노드 체인(RescaleCFG → TorchCompile → SageAttention)을
    뚫고 terminal 인 OTUNetLoaderW8A8(노드 766)까지 도달하는지 확인.
    """
    mgr = ComfyUIWorkflowManager()
    meta = load_anima_int8_metadata()
    ok = mgr.load_workflow_from_metadata(meta)
    assert ok, "load_workflow_from_metadata should succeed for ANIMA INT8"

    nm = mgr.user_workflow_node_map
    assert nm["model_compat"] == "locked_unknown"
    assert nm["workflow_type"] == "locked"
    assert nm["locked_loader_class"] == "OTUNetLoaderW8A8"
    assert nm["locked_loader_node_id"] == "766"
    assert nm["locked_model_display"] == "anima-preview3-base-int8rowwise.safetensors"

    # 나머지 매핑도 정상이어야 함
    assert nm["sampler"] == "770"
    assert nm["positive_prompt"] == "15"
    assert nm["negative_prompt"] == "14"
    assert nm["latent_image"] == "16"
    assert nm["clip_loader"] == "11"
    assert nm["vae_loader"] == "10"
    assert nm["rescale_cfg"] == "772"


# ---------------------------------------------------------------------------
# 4. LOCKED 워크플로우: apply_params_to_workflow 라운드트립
#    — 모델(unet_name) 원본 유지 + 나머지 파라미터 치환
# ---------------------------------------------------------------------------

def test_locked_apply_params_preserves_model_and_applies_rest():
    mgr = ComfyUIWorkflowManager()
    meta = load_anima_int8_metadata()
    assert mgr.load_workflow_from_metadata(meta)

    params = {
        "model": "should-be-ignored.safetensors",  # 잠겨서 무시돼야 함
        "input": "a cat",
        "negative_prompt": "blurry",
        "seed": 42,
        "steps": 25,
        "cfg_scale": 5.5,
        "sampler": "dpmpp_2m",
        "scheduler": "karras",
        "width": 1024,
        "height": 1024,
        "rescale_cfg": 0.5,
        "filename_prefix": "test_locked",
    }
    result = mgr.apply_params_to_workflow(params)
    assert result is not None, "apply_params returned None"

    # 1) 모델은 원본 유지
    loader = result["766"]
    assert loader["inputs"]["unet_name"] == "anima-preview3-base-int8rowwise.safetensors", (
        "LOCKED 위반: params['model']이 치환됐다"
    )

    # 2) 프롬프트 치환
    assert result["15"]["inputs"]["text"] == "a cat"
    assert result["14"]["inputs"]["text"] == "blurry"

    # 3) KSampler 치환
    ks = result["770"]["inputs"]
    assert ks["seed"] == 42
    assert ks["steps"] == 25
    assert abs(ks["cfg"] - 5.5) < 1e-9
    assert ks["sampler_name"] == "dpmpp_2m"
    assert ks["scheduler"] == "karras"

    # 4) 해상도 치환
    lat = result["16"]["inputs"]
    assert lat["width"] == 1024 and lat["height"] == 1024

    # 5) RescaleCFG 치환
    assert abs(result["772"]["inputs"]["multiplier"] - 0.5) < 1e-9

    # 6) 중간 패치 노드는 그대로 — 원본 설정 보존
    assert result["21"]["inputs"].get("sage_attention") == "auto"
    assert result["760"]["inputs"].get("mode") == "max-autotune-no-cudagraphs"


# ---------------------------------------------------------------------------
# 5. analyze_workflow_for_ui — import 팝업용 locked_loader_class / display 전달
# ---------------------------------------------------------------------------

def test_analyze_includes_locked_loader_info():
    mgr = ComfyUIWorkflowManager()
    meta = load_anima_int8_metadata()
    ana = mgr.analyze_workflow_for_ui(meta)

    assert ana["success"] is True
    assert ana["model_compat"] == "locked_unknown"
    assert ana["locked_loader_class"] == "OTUNetLoaderW8A8"
    assert ana["locked_model_display"] == "anima-preview3-base-int8rowwise.safetensors"
    # 커스텀 노드 목록에 로더/패치/캐시 전부 포함
    assert "OTUNetLoaderW8A8" in ana["custom"]
    assert "PathchSageAttentionKJ" in ana["custom"]
    assert "TorchCompileModelAdvanced" in ana["custom"]


def test_analyze_native_checkpoint_has_no_locked_info():
    mgr = ComfyUIWorkflowManager()
    fake_meta = {"prompt": json.dumps(mgr.base_workflow)}
    ana = mgr.analyze_workflow_for_ui(fake_meta)

    assert ana["success"] is True
    assert ana["model_compat"] == "native_checkpoint"
    assert ana.get("locked_loader_class") is None
    assert ana.get("locked_model_display") is None


# ---------------------------------------------------------------------------
# 6. 이벤트 발행 — load / clear 시 comfyui_workflow_changed
# ---------------------------------------------------------------------------

def test_event_publish_on_load_and_clear():
    mgr = ComfyUIWorkflowManager()
    ctx = MockAppContext()
    mgr.set_app_context(ctx)

    meta = load_anima_int8_metadata()
    assert mgr.load_workflow_from_metadata(meta)
    mgr.clear_user_workflow()

    assert len(ctx.events) == 2, f"expected 2 events, got {len(ctx.events)}"

    name1, data1 = ctx.events[0]
    assert name1 == "comfyui_workflow_changed"
    assert data1 == {
        "has_custom": True,
        "model_compat": "locked_unknown",
        "workflow_type": "locked",
        "workflow_label": "Custom Workflow",
        "locked_loader_class": "OTUNetLoaderW8A8",
        "locked_model_display": "anima-preview3-base-int8rowwise.safetensors",
    }

    name2, data2 = ctx.events[1]
    assert name2 == "comfyui_workflow_changed"
    assert data2 == {
        "has_custom": False,
        "model_compat": None,
        "workflow_type": None,
        "workflow_label": "Basic Workflow",
        "locked_loader_class": None,
        "locked_model_display": None,
    }


def test_event_no_publish_without_app_context():
    """set_app_context 안 한 매니저에서는 load/clear 해도 예외 없이 no-op."""
    mgr = ComfyUIWorkflowManager()
    meta = load_anima_int8_metadata()
    mgr.load_workflow_from_metadata(meta)  # 예외 없어야
    mgr.clear_user_workflow()


# ---------------------------------------------------------------------------
# 7. Native 워크플로우에서 apply_params 는 기존 동작 유지 (regression)
# ---------------------------------------------------------------------------

def test_native_checkpoint_apply_params_still_swaps_model():
    mgr = ComfyUIWorkflowManager()
    params = {
        "model": "new-checkpoint.safetensors",
        "input": "prompt",
        "negative_prompt": "neg",
        "seed": 1,
        "steps": 20,
        "cfg_scale": 7.0,
        "sampler": "euler",
        "scheduler": "normal",
        "width": 512,
        "height": 512,
        "workflow_type": "checkpoint",
        "sampling_mode": "eps",
    }
    result = mgr.apply_params_to_workflow(params)
    assert result is not None
    # base_workflow 의 CheckpointLoaderSimple 은 노드 "1"
    assert result["1"]["inputs"]["ckpt_name"] == "new-checkpoint.safetensors"


def test_native_unet_apply_params_still_swaps_model():
    mgr = ComfyUIWorkflowManager()
    params = {
        "model": "new-unet.safetensors",
        "input": "prompt",
        "negative_prompt": "neg",
        "seed": 1,
        "steps": 20,
        "cfg_scale": 4.0,
        "sampler": "euler_ancestral",
        "scheduler": "simple",
        "width": 832,
        "height": 1216,
        "rescale_cfg": 0.7,
        "workflow_type": "unet",
        "sampling_mode": "anima",
    }
    result = mgr.apply_params_to_workflow(params)
    assert result is not None
    # anima_workflow 의 UNETLoader 는 노드 "44"
    assert result["44"]["inputs"]["unet_name"] == "new-unet.safetensors"


def _make_spectrum_spd_ksampler_workflow():
    return {
        "1": {"class_type": "PreviewImage", "inputs": {"images": ["8", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["48", 0], "vae": ["15", 0]}},
        "11": {"class_type": "CLIPTextEncode", "inputs": {"text": "old prompt", "clip": ["45", 0]}},
        "12": {"class_type": "CLIPTextEncode", "inputs": {"text": "old neg", "clip": ["45", 0]}},
        "15": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "28": {"class_type": "EmptyLatentImage", "inputs": {"width": 1536, "height": 1536, "batch_size": 1}},
        "44": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": "Anima/anima-base-v1.0.safetensors", "weight_dtype": "default"},
        },
        "45": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": "qwen_3_06b_base.safetensors", "type": "stable_diffusion", "device": "default"},
        },
        "48": {
            "class_type": "SpectrumSPDKSampler",
            "_meta": {"title": "KSampler (Spectrum + SPD / SPEED)"},
            "inputs": {
                "seed": 485341741675919,
                "steps": 27,
                "cfg": 4.6,
                "sampler_name": "er_sde",
                "scheduler": "simple",
                "denoise": 1,
                "split_mode": "single",
                "spd_scale": 0.5,
                "spd_sigma": 0.7,
                "adaptive_smc_alpha": 0,
                "model": ["52", 0],
                "positive": ["11", 0],
                "negative": ["12", 0],
                "latent_image": ["28", 0],
            },
        },
        "52": {"class_type": "RescaleCFG", "inputs": {"multiplier": 0.6, "model": ["44", 0]}},
        "53": {"class_type": "SaveImage", "inputs": {"filename_prefix": "NAIA_ComfyUI", "images": ["8", 0]}},
    }


def test_ksampler_compatible_custom_sampler_is_supported():
    mgr = ComfyUIWorkflowManager()
    wf = _make_spectrum_spd_ksampler_workflow()

    ok, node_map = mgr.validate_and_map_workflow(wf)
    assert ok, f"SpectrumSPDKSampler workflow should validate: {node_map}"
    assert node_map["sampler"] == "48"
    assert node_map["model_compat"] == "native_unet"
    assert node_map["unet_loader"] == "44"
    assert node_map["positive_prompt"] == "11"
    assert node_map["negative_prompt"] == "12"

    meta = {"prompt": json.dumps(wf), "workflow": json.dumps(wf)}
    analysis = mgr.analyze_workflow_for_ui(meta)
    assert analysis["success"] is True
    assert ("PASS", "SpectrumSPDKSampler") in analysis["required"]
    assert "SpectrumSPDKSampler" not in analysis["custom"]

    assert mgr.load_workflow_from_metadata(meta)
    params = {
        "model": "new-unet.safetensors",
        "input": "new prompt",
        "negative_prompt": "new neg",
        "seed": 123,
        "steps": 20,
        "cfg_scale": 3.5,
        "sampler": "euler",
        "scheduler": "normal",
        "width": 768,
        "height": 1024,
        "rescale_cfg": 0.2,
        "filename_prefix": "NAIA_Test",
    }
    result = mgr.apply_params_to_workflow(params)
    assert result is not None
    sampler_inputs = result["48"]["inputs"]
    assert sampler_inputs["seed"] == 123
    assert sampler_inputs["steps"] == 20
    assert sampler_inputs["cfg"] == 3.5
    assert sampler_inputs["sampler_name"] == "euler"
    assert sampler_inputs["scheduler"] == "normal"
    assert sampler_inputs["split_mode"] == "single"
    assert sampler_inputs["spd_scale"] == 0.5
    assert sampler_inputs["spd_sigma"] == 0.7
    assert sampler_inputs["adaptive_smc_alpha"] == 0
    assert result["44"]["inputs"]["unet_name"] == "new-unet.safetensors"
    assert result["11"]["inputs"]["text"] == "new prompt"
    assert result["12"]["inputs"]["text"] == "new neg"
    assert result["28"]["inputs"]["width"] == 768
    assert result["28"]["inputs"]["height"] == 1024
    workflow_ui = mgr.get_last_applied_workflow_ui()
    sampler_ui = next(node for node in workflow_ui["nodes"] if str(node["id"]) == "48")
    assert sampler_ui["outputs"][0]["type"] == "LATENT"
    assert sampler_ui["widgets_values"][:6] == [123, "randomize", 20, 3.5, "euler", "normal"]


def test_custom_workflow_resolution_targets_connected_latent_source():
    mgr = ComfyUIWorkflowManager()
    wf = _make_spectrum_spd_ksampler_workflow()
    wf["27"] = {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": 512, "height": 512, "batch_size": 1},
    }
    wf["28"]["class_type"] = "EmptySD3LatentImage"
    wf["28"]["_meta"] = {"title": "EmptySD3LatentImage"}

    ok, node_map = mgr.validate_and_map_workflow(wf)
    assert ok, f"custom latent workflow should validate: {node_map}"
    assert node_map["latent_image"] == "28"

    meta = {"prompt": json.dumps(wf), "workflow": json.dumps(wf)}
    assert mgr.load_workflow_from_metadata(meta)
    result = mgr.apply_params_to_workflow({
        "model": "new-unet.safetensors",
        "input": "new prompt",
        "negative_prompt": "new neg",
        "seed": 123,
        "steps": 20,
        "cfg_scale": 3.5,
        "sampler": "euler",
        "scheduler": "normal",
        "width": 832,
        "height": 1216,
        "rescale_cfg": 0.2,
        "filename_prefix": "NAIA_Test",
    })

    assert result is not None
    assert result["28"]["inputs"]["width"] == 832
    assert result["28"]["inputs"]["height"] == 1216
    assert result["27"]["inputs"]["width"] == 512
    assert result["27"]["inputs"]["height"] == 512

    ui_mgr = ComfyUIWorkflowManager()
    workflow_ui = ui_mgr.api_workflow_to_ui_workflow(wf)
    ui_meta = {"prompt": json.dumps(wf), "workflow": json.dumps(workflow_ui)}
    assert ui_mgr.load_workflow_from_metadata(ui_meta)
    assert ui_mgr.user_workflow_node_map["latent_image"] == "28"


def _make_webp_output_workflow():
    wf = _make_spectrum_spd_ksampler_workflow()
    wf.pop("1")
    wf["53"] = {
        "class_type": "SaveAnimatedWEBP",
        "inputs": {
            "filename_prefix": "NAIA_ComfyUI",
            "fps": 1,
            "lossless": False,
            "quality": 97,
            "method": "default",
            "images": ["8", 0],
        },
    }
    return wf


def test_webp_save_node_can_be_custom_workflow_output():
    mgr = ComfyUIWorkflowManager()
    wf = _make_webp_output_workflow()

    ok, node_map = mgr.validate_and_map_workflow(wf)
    assert ok, f"SaveAnimatedWEBP workflow should validate: {node_map}"
    assert node_map["save_image"] == "53"

    meta = {"prompt": json.dumps(wf), "workflow": json.dumps(wf)}
    analysis = mgr.analyze_workflow_for_ui(meta)
    assert analysis["success"] is True
    assert ("PASS", "SaveAnimatedWEBP") in analysis["required"]
    assert "SaveAnimatedWEBP" not in analysis["custom"]

    assert mgr.load_workflow_from_metadata(meta)
    result = mgr.apply_params_to_workflow({
        "model": "new-unet.safetensors",
        "input": "new prompt",
        "negative_prompt": "new neg",
        "seed": 123,
        "steps": 20,
        "cfg_scale": 3.5,
        "sampler": "euler",
        "scheduler": "normal",
        "width": 768,
        "height": 1024,
        "rescale_cfg": 0.2,
        "filename_prefix": "NAIA_WebP_Test",
    })
    assert result is not None
    assert result["53"]["class_type"] == "SaveAnimatedWEBP"
    assert result["53"]["inputs"]["filename_prefix"] == "NAIA_WebP_Test"
    assert result["53"]["inputs"]["quality"] == 97
    workflow_ui = mgr.get_last_applied_workflow_ui()
    webp_node = next(node for node in workflow_ui["nodes"] if str(node["id"]) == "53")
    assert webp_node["type"] == "SaveAnimatedWEBP"
    assert webp_node["widgets_values"][:5] == ["NAIA_WebP_Test", 1, False, 97, "default"]


def _make_bypass_primitive_workflow():
    return {
        "10": {
            "class_type": "PrimitiveString",
            "inputs": {"value": "old positive"},
            "_meta": {"title": "naia_prompt"},
        },
        "11": {
            "class_type": "PrimitiveString",
            "inputs": {"value": "old negative"},
            "_meta": {"title": "naia_negative"},
        },
        "12": {
            "class_type": "PrimitiveInt",
            "inputs": {"value": 512},
            "_meta": {"title": "naia_width"},
        },
        "13": {
            "class_type": "PrimitiveInt",
            "inputs": {"value": 768},
            "_meta": {"title": "naia_height"},
        },
        "40": {
            "class_type": "HeavyCustomPipeline",
            "inputs": {
                "positive": ["10", 0],
                "negative": ["11", 0],
                "width": ["12", 0],
                "height": ["13", 0],
                "seed": 0,
                "noise_seed": "0",
                "fixed_seed": 777,
                "seed_fixed": True,
            },
        },
        "90": {
            "class_type": "SaveAnimatedWEBP",
            "inputs": {
                "filename_prefix": "old_bypass",
                "fps": 1,
                "lossless": False,
                "quality": 90,
                "method": "default",
                "images": ["40", 0],
            },
            "_meta": {"title": "Final WEBP"},
        },
    }


def test_bypass_primitive_workflow_updates_naia_io_and_forces_seed_nodes_random():
    class DeterministicSeedWorkflowManager(ComfyUIWorkflowManager):
        def __init__(self):
            super().__init__()
            self._seed_values = iter([101, 202, 303])

        def _generate_random_seed(self) -> int:
            return next(self._seed_values)

    mgr = DeterministicSeedWorkflowManager()
    wf = _make_bypass_primitive_workflow()

    ok, node_map = mgr.validate_and_map_workflow(wf, allow_free=True)
    assert ok, f"bypass workflow should validate: {node_map}"
    assert node_map["workflow_type"] == "bypass"
    assert node_map["model_compat"] == "bypass"
    assert node_map["positive_prompt"] == "10"
    assert node_map["negative_prompt"] == "11"
    assert node_map["width_primitive"] == "12"
    assert node_map["height_primitive"] == "13"
    assert node_map["save_image"] == "90"
    assert "sampler" not in node_map

    meta = extract_comfyui_workflow_metadata_from_upload_bytes(json.dumps(wf).encode("utf-8"))
    analysis = mgr.analyze_workflow_for_ui(meta, workflow_mode="bypass")
    assert analysis["success"] is True
    assert analysis["model_compat"] == "bypass"
    assert ("PASS", "PrimitiveString title naia_prompt") in analysis["required"]
    assert ("PASS", "SaveAnimatedWEBP single save node") in analysis["required"]
    assert "HeavyCustomPipeline" in analysis["custom"]

    assert mgr.load_workflow_from_metadata(meta, workflow_mode="bypass")
    params = {
        "model": "ignored.safetensors",
        "input": "new positive",
        "negative_prompt": "new negative",
        "seed": 123,
        "steps": 20,
        "cfg_scale": 3.5,
        "sampler": "euler",
        "scheduler": "normal",
        "width": 832,
        "height": 1216,
        "filename_prefix": "NAIA_Bypass_Test",
    }
    result = mgr.apply_params_to_workflow(params)
    assert result is not None
    assert result["10"]["inputs"]["value"] == "new positive"
    assert result["11"]["inputs"]["value"] == "new negative"
    assert result["12"]["inputs"]["value"] == 832
    assert result["13"]["inputs"]["value"] == 1216
    assert result["90"]["inputs"]["filename_prefix"] == "NAIA_Bypass_Test"
    assert result["40"]["inputs"]["positive"] == ["10", 0]
    assert result["40"]["inputs"]["seed"] == 101
    assert result["40"]["inputs"]["noise_seed"] == 202
    assert result["40"]["inputs"]["fixed_seed"] == 303
    assert result["40"]["inputs"]["seed_fixed"] is True
    assert params["_comfyui_output_node_id"] == "90"

    workflow_ui = mgr.get_last_applied_workflow_ui()
    positive_ui = next(node for node in workflow_ui["nodes"] if str(node["id"]) == "10")
    width_ui = next(node for node in workflow_ui["nodes"] if str(node["id"]) == "12")
    assert positive_ui["widgets_values"] == ["new positive"]
    assert width_ui["widgets_values"] == [832]


def test_bypass_workflow_rejects_missing_required_title():
    mgr = ComfyUIWorkflowManager()
    wf = _make_bypass_primitive_workflow()
    wf["12"]["_meta"]["title"] = "width"

    ok, node_map = mgr.validate_and_map_workflow(wf, allow_free=True)
    assert not ok
    assert "naia_width" in node_map["error"]

    meta = extract_comfyui_workflow_metadata_from_upload_bytes(json.dumps(wf).encode("utf-8"))
    analysis = mgr.analyze_workflow_for_ui(meta, workflow_mode="bypass")
    assert analysis["success"] is False
    assert ("FAIL", "PrimitiveInt title naia_width") in analysis["required"]
    assert "naia_width" in analysis["error_message"]


def test_bypass_workflow_title_can_come_from_meta_when_title_exists():
    mgr = ComfyUIWorkflowManager()
    wf = _make_bypass_primitive_workflow()
    wf["10"]["title"] = "문자열"

    ok, node_map = mgr.validate_and_map_workflow(wf, allow_free=True)
    assert ok, f"_meta title should still identify naia_prompt: {node_map}"
    assert node_map["positive_prompt"] == "10"


def test_bypass_workflow_requires_exactly_one_save_node():
    mgr = ComfyUIWorkflowManager()
    wf = _make_bypass_primitive_workflow()
    wf["91"] = {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "extra", "images": ["40", 0]},
    }

    ok, node_map = mgr.validate_and_map_workflow(wf, allow_free=True)
    assert not ok
    assert "multiple SaveImage/SaveAnimatedWEBP nodes" in node_map["error"]


def test_bypass_workflow_does_not_load_through_normal_custom_mode():
    mgr = ComfyUIWorkflowManager()
    wf = _make_bypass_primitive_workflow()
    meta = extract_comfyui_workflow_metadata_from_upload_bytes(json.dumps(wf).encode("utf-8"))

    analysis = mgr.analyze_workflow_for_ui(meta, workflow_mode="custom")
    assert analysis["success"] is False
    assert "Custom Workflow (Bypass)" in analysis["error_message"]
    assert not mgr.load_workflow_from_metadata(meta, workflow_mode="custom")


def test_bypass_workflow_metadata_is_json_upload_only():
    mgr = ComfyUIWorkflowManager()
    wf = _make_bypass_primitive_workflow()
    image_style_meta = {"prompt": json.dumps(wf), "workflow": json.dumps(wf)}

    analysis = mgr.analyze_workflow_for_ui(image_style_meta, workflow_mode="bypass")
    assert analysis["success"] is False
    assert "JSON workflow uploads only" in analysis["error_message"]
    assert not mgr.load_workflow_from_metadata(image_style_meta, workflow_mode="bypass")


def test_comfyui_service_prefers_requested_output_node():
    import core.comfyui_service as comfyui_service_module

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "prompt-id": {
                    "outputs": {
                        "1": {
                            "images": [
                                {"filename": "preview.png", "subfolder": "", "type": "temp"},
                            ],
                        },
                        "90": {
                            "images": [
                                {"filename": "final.webp", "subfolder": "", "type": "output"},
                            ],
                        },
                    }
                }
            }

    original_get = comfyui_service_module.requests.get
    comfyui_service_module.requests.get = lambda *args, **kwargs: FakeResponse()
    try:
        service = ComfyUIService("http://127.0.0.1:8188")
        workflow = {
            "1": {"class_type": "PreviewImage", "inputs": {}},
            "90": {"class_type": "SaveAnimatedWEBP", "inputs": {}, "_meta": {"title": "NAIA_OUTPUT"}},
        }
        result = service.get_generation_result(
            "prompt-id",
            workflow=workflow,
            preferred_output_node_id="90",
        )
    finally:
        comfyui_service_module.requests.get = original_get

    assert len(result) == 1
    assert result[0]["filename"] == "final.webp"
    assert result[0]["source_node_id"] == "90"


def test_native_workflows_use_save_image_outputs():
    mgr = ComfyUIWorkflowManager()

    assert mgr.base_workflow["7"]["class_type"] == "SaveImage"
    assert mgr.base_workflow["7"]["inputs"]["filename_prefix"] == "NAIA_ComfyUI"
    assert mgr.anima_workflow["1"]["class_type"] == "SaveImage"
    assert mgr.anima_workflow["1"]["inputs"]["filename_prefix"] == "NAIA_ComfyUI"


def test_apply_params_builds_current_ui_workflow_metadata():
    mgr = ComfyUIWorkflowManager()
    params = {
        "model": "new-checkpoint.safetensors",
        "input": "current prompt",
        "negative_prompt": "current negative",
        "seed": 123,
        "steps": 22,
        "cfg_scale": 6.5,
        "sampler": "euler",
        "scheduler": "normal",
        "width": 640,
        "height": 768,
        "workflow_type": "checkpoint",
        "sampling_mode": "eps",
        "filename_prefix": "naia_test",
    }

    result = mgr.apply_params_to_workflow(params)
    workflow_ui = mgr.get_last_applied_workflow_ui()

    assert result["7"]["class_type"] == "SaveImage"
    assert result["7"]["inputs"]["filename_prefix"] == "naia_test"
    assert workflow_ui and "nodes" in workflow_ui
    save_node = next(node for node in workflow_ui["nodes"] if str(node["id"]) == "7")
    prompt_node = next(node for node in workflow_ui["nodes"] if str(node["id"]) == "2")
    assert save_node["type"] == "SaveImage"
    assert "workflow" not in result
    assert prompt_node["widgets_values"][0] == "current prompt"


# ---------------------------------------------------------------------------
# 8. 역추적 견고성 — dangling link / 순환 / max_depth
# ---------------------------------------------------------------------------

def _make_api_workflow_with_dangling_model():
    """KSampler.model 이 존재하지 않는 node_id 를 가리키는 API 형식 워크플로우."""
    return {
        "1": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 0, "steps": 20, "cfg": 7.0,
                "sampler_name": "euler", "scheduler": "normal",
                "denoise": 1.0,
                "model": ["9999", 0],  # 존재하지 않는 노드
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
            },
        },
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["10", 0]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["10", 0]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "5": {"class_type": "VAEDecode", "inputs": {"samples": ["1", 0], "vae": ["11", 0]}},
        "6": {"class_type": "SaveImage", "inputs": {"images": ["5", 0], "filename_prefix": "x"}},
        "10": {"class_type": "CLIPLoader", "inputs": {"clip_name": "c.safetensors", "type": "stable_diffusion", "device": "default"}},
        "11": {"class_type": "VAELoader", "inputs": {"vae_name": "v.safetensors"}},
    }


def _make_api_workflow_with_cycle():
    """모델 체인에 순환이 있는 API 형식 워크플로우 — A.model → B, B.model → A."""
    return {
        "1": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 0, "steps": 20, "cfg": 7.0,
                "sampler_name": "euler", "scheduler": "normal",
                "denoise": 1.0,
                "model": ["A", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
            },
        },
        "A": {"class_type": "SomePatch", "inputs": {"model": ["B", 0]}},
        "B": {"class_type": "SomePatch", "inputs": {"model": ["A", 0]}},  # cycle
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["10", 0]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["10", 0]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "5": {"class_type": "VAEDecode", "inputs": {"samples": ["1", 0], "vae": ["11", 0]}},
        "6": {"class_type": "SaveImage", "inputs": {"images": ["5", 0], "filename_prefix": "x"}},
        "10": {"class_type": "CLIPLoader", "inputs": {"clip_name": "c.safetensors", "type": "stable_diffusion", "device": "default"}},
        "11": {"class_type": "VAELoader", "inputs": {"vae_name": "v.safetensors"}},
    }


def _make_api_workflow_with_deep_chain(depth):
    """KSampler → patch_0 → patch_1 → ... → patch_{depth-1} (terminal, model 입력 없음)."""
    wf = {
        "sampler": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 0, "steps": 20, "cfg": 7.0,
                "sampler_name": "euler", "scheduler": "normal",
                "denoise": 1.0,
                "model": ["patch_0", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
            },
        },
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["10", 0]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["10", 0]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "5": {"class_type": "VAEDecode", "inputs": {"samples": ["sampler", 0], "vae": ["11", 0]}},
        "6": {"class_type": "SaveImage", "inputs": {"images": ["5", 0], "filename_prefix": "x"}},
        "10": {"class_type": "CLIPLoader", "inputs": {"clip_name": "c.safetensors", "type": "stable_diffusion", "device": "default"}},
        "11": {"class_type": "VAELoader", "inputs": {"vae_name": "v.safetensors"}},
    }
    for i in range(depth - 1):
        wf[f"patch_{i}"] = {
            "class_type": "SomePatch",
            "inputs": {"model": [f"patch_{i + 1}", 0]},
        }
    # 마지막 노드 — model 입력 없는 terminal
    wf[f"patch_{depth - 1}"] = {
        "class_type": "SomePatch",
        "inputs": {},
    }
    return wf


def test_trace_handles_dangling_model_link():
    """dangling link → 현재 노드를 terminal 로 간주 → 그 노드가 커스텀이면 LOCKED 귀결."""
    mgr = ComfyUIWorkflowManager()
    wf = _make_api_workflow_with_dangling_model()
    ok, nm = mgr.validate_and_map_workflow(wf)
    assert ok, "dangling link 는 validate 실패가 아니라 LOCKED 로 귀결돼야 함"
    # sampler.model 이 "9999" 를 가리키지만 해당 노드가 없어서 KSampler 자체가 terminal 로 간주됨.
    # KSampler 는 표준 로더가 아니므로 LOCKED_UNKNOWN.
    assert nm["model_compat"] == "locked_unknown"


def test_trace_handles_cycle_without_infinite_loop():
    """순환 체인 → 역추적 None 반환 → LOCKED 귀결, 예외/무한루프 없음."""
    mgr = ComfyUIWorkflowManager()
    wf = _make_api_workflow_with_cycle()
    ok, nm = mgr.validate_and_map_workflow(wf)
    assert ok, "순환이어도 validate 자체는 LOCKED 로 통과"
    assert nm["model_compat"] == "locked_unknown"
    # 순환이면 terminal 식별 실패 → locked_loader_* 는 기본값
    # (None 반환으로 인해 locked_loader_node_id 는 node_map 에 없고, class 는 "Unknown")
    assert nm.get("locked_loader_class") == "Unknown"
    assert "locked_loader_node_id" not in nm


def test_trace_respects_max_depth():
    """65단 체인 → max_depth(64) 초과 → None 귀결 → LOCKED."""
    mgr = ComfyUIWorkflowManager()
    wf = _make_api_workflow_with_deep_chain(depth=65)
    ok, nm = mgr.validate_and_map_workflow(wf)
    assert ok
    assert nm["model_compat"] == "locked_unknown"
    assert nm.get("locked_loader_class") == "Unknown"


def test_trace_deep_but_within_limit():
    """63단 체인 → max_depth 이내 → 정상 terminal 식별(SomePatch, locked)."""
    mgr = ComfyUIWorkflowManager()
    wf = _make_api_workflow_with_deep_chain(depth=63)
    ok, nm = mgr.validate_and_map_workflow(wf)
    assert ok
    assert nm["model_compat"] == "locked_unknown"
    assert nm.get("locked_loader_class") == "SomePatch"
    assert nm.get("locked_loader_node_id") == "patch_62"


# ---------------------------------------------------------------------------
# 9. H1 회귀 — locked → locked 전환 시 이벤트 payload 가 갱신되는가
#    (UI 측 _apply_model_lock 은 Qt 필요, 매니저 측 발행 paylaod 로 대체 검증)
# ---------------------------------------------------------------------------

def _make_locked_workflow_with(loader_class, model_name):
    """임의의 커스텀 로더 체인을 가진 API 형식 워크플로우."""
    return {
        "1": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 0, "steps": 20, "cfg": 7.0,
                "sampler_name": "euler", "scheduler": "normal",
                "denoise": 1.0,
                "model": ["loader", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
            },
        },
        "loader": {
            "class_type": loader_class,
            "inputs": {"unet_name": model_name},
        },
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["10", 0]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["10", 0]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "5": {"class_type": "VAEDecode", "inputs": {"samples": ["1", 0], "vae": ["11", 0]}},
        "6": {"class_type": "SaveImage", "inputs": {"images": ["5", 0], "filename_prefix": "x"}},
        "10": {"class_type": "CLIPLoader", "inputs": {"clip_name": "c.safetensors", "type": "stable_diffusion", "device": "default"}},
        "11": {"class_type": "VAELoader", "inputs": {"vae_name": "v.safetensors"}},
    }


def test_locked_to_locked_transition_emits_fresh_payload():
    """워크플로우 A(locked) → 해제 없이 워크플로우 B(locked) 전환 시
    두 번째 발행 payload 가 B 의 로더 클래스/파일명으로 갱신돼야 한다 (H1)."""
    mgr = ComfyUIWorkflowManager()
    ctx = MockAppContext()
    mgr.set_app_context(ctx)

    wf_a = _make_locked_workflow_with("LoaderA", "model_a.safetensors")
    wf_b = _make_locked_workflow_with("LoaderB", "model_b.safetensors")

    # load_workflow_from_metadata 는 workflow 와 prompt 키 둘 다 요구.
    # 우리 fixture 는 API 형식이므로 두 키에 동일한 JSON 을 넣고, 매니저는
    # 'nodes' 키 부재로 API 형식으로 인식한다.
    meta_a = {"prompt": json.dumps(wf_a), "workflow": json.dumps(wf_a)}
    meta_b = {"prompt": json.dumps(wf_b), "workflow": json.dumps(wf_b)}
    mgr.load_workflow_from_metadata(meta_a)
    mgr.load_workflow_from_metadata(meta_b)

    assert len(ctx.events) == 2
    _, data_a = ctx.events[0]
    _, data_b = ctx.events[1]
    assert data_a["locked_loader_class"] == "LoaderA"
    assert data_a["locked_model_display"] == "model_a.safetensors"
    assert data_b["locked_loader_class"] == "LoaderB"
    assert data_b["locked_model_display"] == "model_b.safetensors"


def test_api_workflow_json_upload_loads_as_custom_workflow():
    mgr = ComfyUIWorkflowManager()
    metadata = extract_comfyui_workflow_metadata_from_upload_bytes(
        json.dumps(mgr.base_workflow).encode("utf-8")
    )

    target = ComfyUIWorkflowManager()
    assert target.load_workflow_from_metadata(metadata)
    assert target.user_workflow is not None
    assert target.user_workflow_ui is None


def test_utf8_bom_workflow_json_upload_loads_as_custom_workflow():
    mgr = ComfyUIWorkflowManager()
    metadata = extract_comfyui_workflow_metadata_from_upload_bytes(
        b"\xef\xbb\xbf" + json.dumps(mgr.base_workflow).encode("utf-8")
    )

    target = ComfyUIWorkflowManager()
    assert target.load_workflow_from_metadata(metadata)
    assert target.user_workflow is not None


def test_ui_workflow_json_upload_loads_with_generated_api_workflow():
    source = ComfyUIWorkflowManager()
    workflow_ui = source.api_workflow_to_ui_workflow(source.base_workflow)
    metadata = extract_comfyui_workflow_metadata_from_upload_bytes(
        json.dumps(workflow_ui).encode("utf-8")
    )

    target = ComfyUIWorkflowManager()
    assert target.load_workflow_from_metadata(metadata)
    assert target.user_workflow is not None
    assert target.user_workflow_ui is not None
    assert target.user_workflow["4"]["inputs"]["steps"] == 20


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_native_checkpoint,
    test_native_unet,
    test_locked_unknown_anima_int8_identifies_terminal_loader,
    test_locked_apply_params_preserves_model_and_applies_rest,
    test_analyze_includes_locked_loader_info,
    test_analyze_native_checkpoint_has_no_locked_info,
    test_event_publish_on_load_and_clear,
    test_event_no_publish_without_app_context,
    test_native_checkpoint_apply_params_still_swaps_model,
    test_native_unet_apply_params_still_swaps_model,
    test_ksampler_compatible_custom_sampler_is_supported,
    test_webp_save_node_can_be_custom_workflow_output,
    test_bypass_primitive_workflow_updates_naia_io_and_forces_seed_nodes_random,
    test_bypass_workflow_rejects_missing_required_title,
    test_bypass_workflow_title_can_come_from_meta_when_title_exists,
    test_bypass_workflow_requires_exactly_one_save_node,
    test_bypass_workflow_does_not_load_through_normal_custom_mode,
    test_bypass_workflow_metadata_is_json_upload_only,
    test_comfyui_service_prefers_requested_output_node,
    test_native_workflows_use_save_image_outputs,
    test_apply_params_builds_current_ui_workflow_metadata,
    test_trace_handles_dangling_model_link,
    test_trace_handles_cycle_without_infinite_loop,
    test_trace_respects_max_depth,
    test_trace_deep_but_within_limit,
    test_locked_to_locked_transition_emits_fresh_payload,
    test_api_workflow_json_upload_loads_as_custom_workflow,
    test_utf8_bom_workflow_json_upload_loads_as_custom_workflow,
    test_ui_workflow_json_upload_loads_with_generated_api_workflow,
]


def main():
    passed = 0
    failed = []
    for fn in ALL_TESTS:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as e:
            traceback.print_exc()
            failed.append((fn.__name__, str(e)))
            print(f"  FAIL  {fn.__name__}: {e}")

    total = len(ALL_TESTS)
    print()
    print(f"=== {passed}/{total} passed ===")
    if failed:
        for name, err in failed:
            print(f"  - {name}: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
