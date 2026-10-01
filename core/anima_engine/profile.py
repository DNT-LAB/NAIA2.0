"""Pure, closed-world compiler for the managed SPD graph."""
from __future__ import annotations

import copy
import json
import math
import os
import random
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .manifest import GRAPH_TEMPLATE, OUTPUT_NODE_ID, PROFILE_ID, PROFILE_REVISION, RUNTIME_ID
from core.resolution_utils import ANIMA_MAX_PIXELS, nearest_anima_resolution


class ProfileError(ValueError):
    def __init__(self, code: str, *, field: str | None = None):
        self.code, self.field = code, field
        super().__init__(f"[{code}] ANIMA 설정을 확인해 주세요: {field or 'workflow'}")


@dataclass(frozen=True)
class CompiledGraph:
    workflow: dict[str, dict]
    output_node_id: str
    seed: int
    meta: dict[str, Any]


# 모델은 고를 수 있다(09-28) — 노드 44 의 unet_name. 고르지 않으면 설치한 기본 모델.
DEFAULT_UNET = GRAPH_TEMPLATE["44"]["inputs"]["unet_name"]

SLOTS = {"input": ("11", "text", ""), "negative_prompt": ("12", "text", ""),
         "seed": ("48", "seed", -1), "steps": ("48", "steps", 27),
         "cfg_scale": ("48", "cfg", 4.8), "width": ("28", "width", 960),
         "height": ("28", "height", 1408), "rescale_cfg": ("52", "multiplier", 0.5)}

# 샘플러 · 스케줄러는 고를 수 있다(사용자 지정 2026-10-01 핫픽스: "ANIMA 모드의 Params 에서 Sampler / Scheduler 는 사용자가
# 자유롭게 선택"). 목록은 엔진 고정판 ComfyUI v0.22.0 의 comfy/samplers.py KSampler.SAMPLERS / SCHEDULERS 그대로다(설치본에서
# AST 로 뽑음) - SpectrumSPDKSampler 의 sampler_name · scheduler 입력이 이 목록이다(노드 _KSAMPLER_INPUTS).
SAMPLERS = (
    "euler", "euler_cfg_pp", "euler_ancestral", "euler_ancestral_cfg_pp", "heun", "heunpp2", "exp_heun_2_x0",
    "exp_heun_2_x0_sde", "dpm_2", "dpm_2_ancestral", "lms", "dpm_fast", "dpm_adaptive", "dpmpp_2s_ancestral",
    "dpmpp_2s_ancestral_cfg_pp", "dpmpp_sde", "dpmpp_sde_gpu", "dpmpp_2m", "dpmpp_2m_cfg_pp", "dpmpp_2m_sde",
    "dpmpp_2m_sde_gpu", "dpmpp_2m_sde_heun", "dpmpp_2m_sde_heun_gpu", "dpmpp_3m_sde", "dpmpp_3m_sde_gpu",
    "ddpm", "lcm", "ipndm", "ipndm_v", "deis", "res_multistep", "res_multistep_cfg_pp",
    "res_multistep_ancestral", "res_multistep_ancestral_cfg_pp", "gradient_estimation",
    "gradient_estimation_cfg_pp", "er_sde", "seeds_2", "seeds_3", "sa_solver", "sa_solver_pece", "ddim",
    "uni_pc", "uni_pc_bh2",
)
SCHEDULERS = (
    "simple", "sgm_uniform", "karras", "exponential", "ddim_uniform", "beta", "normal", "linear_quadratic",
    "kl_optimal",
)
DEFAULT_SAMPLER = GRAPH_TEMPLATE["48"]["inputs"]["sampler_name"]      # euler
DEFAULT_SCHEDULER = GRAPH_TEMPLATE["48"]["inputs"]["scheduler"]       # simple
# SPD(저해상도로 앞 구간을 돌리다 σ=spd_sigma 에서 원해상도로 넘어가는 노드의 SPEED 경로)는 **Euler 전용**이다 - 노드는 SPD 중에
# 다른 샘플러를 조용히 Euler 로 바꾼다(spectrum.py "ignoring requested sampler ... using Euler"). 그래서 Euler 밖의 샘플러면 그
# 생성만 SPD 를 끈다: spd_scale 1.0 = 노드 설명의 "1.0 disables SPD (vanilla Spectrum)" - 고른 샘플러가 실제로 돌고 Spectrum
# 가속은 남는다. 스케줄러는 SPD 와 함께 쓰인다(SPD 도 고른 스케줄러로 σ 표를 만든다).
SPD_SAMPLER = "euler"
SPD_SCALE = GRAPH_TEMPLATE["48"]["inputs"]["spd_scale"]               # 0.5
SPD_OFF_SCALE = 1.0


def resolve_sampling(params):
    """요청의 샘플러 · 스케줄러 -> 엔진이 받는 값. 목록에 없으면(외부 ComfyUI · WebUI 에서 남은 이름 · 빈 값) 기본값 - PARAMS
    칸이 보여 주는 것(integration.apply_managed_schema)과 같다(모델의 resolve_model 과 같은 규칙)."""
    sampler = str(params.get("sampler") or "").strip()
    scheduler = str(params.get("scheduler") or "").strip()
    return (sampler if sampler in SAMPLERS else DEFAULT_SAMPLER,
            scheduler if scheduler in SCHEDULERS else DEFAULT_SCHEDULER)


def spd_scale_for(sampler):
    return SPD_SCALE if sampler == SPD_SAMPLER else SPD_OFF_SCALE


def integer_value(value, field):
    # Never pass a seed through float: even a Python int can lose uint64 bits.
    if isinstance(value, str) and re.fullmatch(r"[+-]?[0-9]{1,20}", value.strip()):
        value = int(value.strip())
    if type(value) is not int:
        raise ProfileError("PARAM_OUT_OF_RANGE", field=field)
    return value


def normalize_resolution(width, height):
    width = integer_value(width, "width") // 8 * 8
    height = integer_value(height, "height") // 8 * 8
    if not (256 <= width <= 2048 and 256 <= height <= 2048 and width * height <= ANIMA_MAX_PIXELS):
        return nearest_anima_resolution(width, height)
    return width, height


def clean_prompt(value):
    if not isinstance(value, str):
        raise ProfileError("PARAM_OUT_OF_RANGE", field="prompt")
    parts = (part.replace("\n", "").strip() for part in value.split(","))
    return ", ".join(part for part in parts if part and not part.startswith("#"))


def request_values(params):
    """Strict request parsing, shared by queue validation and graph compilation."""
    values = {key: params.get(key, slot[2]) for key, slot in SLOTS.items()}
    if values["seed"] is None or values["seed"] == "":
        values["seed"] = -1
    for key in ("seed", "steps"):
        values[key] = integer_value(values[key], key)
    for key in ("cfg_scale", "rescale_cfg"):
        value = values[key]
        if key == "rescale_cfg" and (value is None or value == ""):
            value = 0.5
        if isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                raise ProfileError("PARAM_OUT_OF_RANGE", field=key) from None
        values[key] = value
    values["width"], values["height"] = normalize_resolution(values["width"], values["height"])
    for key in ("input", "negative_prompt"):
        values[key] = clean_prompt(values[key])
    validate_params({**values, "seed": 0 if values["seed"] == -1 else values["seed"]})
    return values


def number(value, field, low, high, *, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProfileError("PARAM_OUT_OF_RANGE", field=field)
    if not math.isfinite(value) or not low <= value <= high or (integer and not isinstance(value, int)):
        raise ProfileError("PARAM_OUT_OF_RANGE", field=field)
    return value


def validate_params(params):
    for key in ("input", "negative_prompt"):
        if not isinstance(params[key], str):
            raise ProfileError("PARAM_OUT_OF_RANGE", field=key)
    number(params["seed"], "seed", 0, 2**64 - 1, integer=True)
    number(params["steps"], "steps", 1, 150, integer=True)
    number(params["cfg_scale"], "cfg_scale", 1, 10)
    number(params["rescale_cfg"], "rescale_cfg", 0, 1)
    for key in ("width", "height"):
        number(params[key], key, 256, 2048, integer=True)
        if params[key] % 8:
            raise ProfileError("PARAM_OUT_OF_RANGE", field=key)
    if params["width"] * params["height"] > ANIMA_MAX_PIXELS:
        raise ProfileError("PARAM_OUT_OF_RANGE", field="area")


# ComfyUI 는 lora_name 을 자기 목록 문자열과 **정확히** 대조한다(execution.py value_not_in_list). 그 목록은
# folder_paths.recursive_search 의 os.path.relpath 라 Windows 에서는 하위 폴더가 역슬래시다 - 슬래시로 보내면
# 하위 폴더 LoRA 만 거절됐다(09-30 LoRA 하위 폴더 지원). NAIA 안의 이름(목록 · 체인 · 썸네일 열쇠 · 히스토리)은
# 슬래시 하나로 두고, 그래프에 적을 때만 바꾼다. 관리형 엔진은 NAIA 와 같은 PC 에서 돈다 = 같은 os.sep.
ENGINE_SEP = os.sep


def engine_lora_name(name: str) -> str:
    return name.replace("/", ENGINE_SEP)


def naia_lora_name(name: str) -> str:
    return name.replace(ENGINE_SEP, "/") if isinstance(name, str) else name


def validate_chain(chain, available_loras):
    if not isinstance(chain, (list, tuple)) or len(chain) > 32:
        raise ProfileError("PARAM_OUT_OF_RANGE", field="lora_chain")
    for item in chain:
        if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
            raise ProfileError("LORA_INVALID", field="name")
        if not isinstance(item.get("enabled", True), bool):
            raise ProfileError("LORA_INVALID", field="enabled")
        number(item.get("strength", 1.0), "strength", -2, 2)
        if item.get("enabled", True) and item["name"] not in available_loras:
            raise ProfileError("LORA_NOT_FOUND", field=item["name"])


def compile_graph(params: Mapping[str, Any], lora_chain: Sequence[Mapping[str, Any]], *,
                  available_loras: Collection[str], rng: random.Random | None = None,
                  model: str | None = None, available_models: Collection[str] | None = None) -> CompiledGraph:
    # The existing generation dispatcher calls ordinary text generation "generate".
    if params.get("type") not in (None, "", "generate", "txt2img"):
        raise ProfileError("MANAGED_UNSUPPORTED_REQUEST", field="type")
    if any(params.get(key) for key in ("image", "mask", "image_data", "mask_data", "init_images", "img2img_image", "image_bytes", "mask_bytes")):
        raise ProfileError("MANAGED_UNSUPPORTED_REQUEST", field="image")
    values = request_values(params)
    if values["seed"] == -1:
        values["seed"] = (rng or random.SystemRandom()).randrange(0, 2**32)
    validate_params(values)
    validate_chain(lora_chain, available_loras)
    unet = model or DEFAULT_UNET
    if unet not in (available_models if available_models is not None else {DEFAULT_UNET}):
        raise ProfileError("MODEL_NOT_FOUND", field=unet)
    graph = copy.deepcopy(GRAPH_TEMPLATE)
    graph["44"]["inputs"]["unet_name"] = unet
    for key, (node, field, _) in SLOTS.items():
        graph[node]["inputs"][field] = values[key]
    sampler, scheduler = resolve_sampling(params)
    graph["48"]["inputs"].update(sampler_name=sampler, scheduler=scheduler, spd_scale=spd_scale_for(sampler))
    prev, active = "44", []
    for item in lora_chain:
        if not item.get("enabled", True):
            continue
        node = str(100 + len(active))
        graph[node] = {"class_type": "LoraLoaderModelOnly", "inputs": {
            "lora_name": engine_lora_name(item["name"]), "strength_model": item.get("strength", 1.0), "model": [prev, 0]}}
        prev = node
        active.append({"name": item["name"], "strength": item.get("strength", 1.0), "sha256": item.get("sha256")})
    graph["52"]["inputs"]["model"] = [prev, 0]
    validate_compiled(graph, available_loras=available_loras, available_models=available_models)
    return CompiledGraph(graph, OUTPUT_NODE_ID, values["seed"], {
        "id": PROFILE_ID, "revision": PROFILE_REVISION, "runtime_id": RUNTIME_ID, "model": unet,
        "sampler": sampler, "scheduler": scheduler, "spd": sampler == SPD_SAMPLER, "sampler_actual": sampler,
        "sampler_note": "SPD on (Euler only)" if sampler == SPD_SAMPLER else "SPD off: non-Euler sampler (Spectrum only)",
        "loras": active,
        **{key: values[key] for key in ("seed", "steps", "cfg_scale", "rescale_cfg", "width", "height")}})


def validate_request_slots(params):
    """Validate the final request after image modules, without coercion fallbacks."""
    values = request_values(params)
    if params.get("type") not in (None, "", "generate", "txt2img") or any(
            params.get(key) for key in ("image", "mask", "image_data", "mask_data", "init_images", "img2img_image", "image_bytes", "mask_bytes")):
        raise ProfileError("MANAGED_UNSUPPORTED_REQUEST", field="type")
    return values


def validate_compiled(workflow: Mapping[str, Any], *, available_loras: Collection[str],
                      available_models: Collection[str] | None = None) -> None:
    try:
        extra = set(workflow) - set(GRAPH_TEMPLATE)
        if len(extra) > 32 or extra != {str(100 + i) for i in range(len(extra))}:
            raise ValueError("nodes")
        values = {key: workflow[node]["inputs"][field] for key, (node, field, _) in SLOTS.items()}
        validate_params(values)
        expected = copy.deepcopy(GRAPH_TEMPLATE)
        unet = workflow["44"]["inputs"]["unet_name"]
        if unet not in (available_models if available_models is not None else {DEFAULT_UNET}):
            raise ValueError("model")
        expected["44"]["inputs"]["unet_name"] = unet
        for key, (node, field, _) in SLOTS.items():
            expected[node]["inputs"][field] = values[key]
        sampler, scheduler = workflow["48"]["inputs"]["sampler_name"], workflow["48"]["inputs"]["scheduler"]
        if sampler not in SAMPLERS or scheduler not in SCHEDULERS:
            raise ValueError("sampling")
        # SPD 는 샘플러가 정한다 - Euler 에 SPD 끔 · 다른 샘플러에 SPD 켬은 고친 그래프다
        expected["48"]["inputs"].update(sampler_name=sampler, scheduler=scheduler, spd_scale=spd_scale_for(sampler))
        prev = "44"
        for i in range(len(extra)):
            node = str(100 + i)
            inputs = workflow[node]["inputs"]
            name, strength = naia_lora_name(inputs["lora_name"]), inputs["strength_model"]
            validate_chain([{"name": name, "strength": strength}], available_loras)
            expected[node] = {"class_type": "LoraLoaderModelOnly", "inputs": {
                "lora_name": engine_lora_name(name), "strength_model": strength, "model": [prev, 0]}}
            prev = node
        expected["52"]["inputs"]["model"] = [prev, 0]
        if json.dumps(workflow, sort_keys=True, allow_nan=False) != json.dumps(expected, sort_keys=True, allow_nan=False):
            raise ValueError("graph")
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ProfileError("PROFILE_VIOLATION", field="workflow") from None
