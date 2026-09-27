"""Pure, closed-world compiler for the managed SPD graph."""
from __future__ import annotations

import copy
import json
import math
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


SLOTS = {"input": ("11", "text", ""), "negative_prompt": ("12", "text", ""),
         "seed": ("48", "seed", -1), "steps": ("48", "steps", 27),
         "cfg_scale": ("48", "cfg", 4.8), "width": ("28", "width", 960),
         "height": ("28", "height", 1408), "rescale_cfg": ("52", "multiplier", 0.5)}


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
                  available_loras: Collection[str], rng: random.Random | None = None) -> CompiledGraph:
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
    graph = copy.deepcopy(GRAPH_TEMPLATE)
    for key, (node, field, _) in SLOTS.items():
        graph[node]["inputs"][field] = values[key]
    prev, active = "44", []
    for item in lora_chain:
        if not item.get("enabled", True):
            continue
        node = str(100 + len(active))
        graph[node] = {"class_type": "LoraLoaderModelOnly", "inputs": {
            "lora_name": item["name"], "strength_model": item.get("strength", 1.0), "model": [prev, 0]}}
        prev = node
        active.append({"name": item["name"], "strength": item.get("strength", 1.0), "sha256": item.get("sha256")})
    graph["52"]["inputs"]["model"] = [prev, 0]
    validate_compiled(graph, available_loras=available_loras)
    return CompiledGraph(graph, OUTPUT_NODE_ID, values["seed"], {
        "id": PROFILE_ID, "revision": PROFILE_REVISION, "runtime_id": RUNTIME_ID,
        "sampler_actual": "euler", "sampler_note": "SPD forces Euler", "loras": active,
        **{key: values[key] for key in ("seed", "steps", "cfg_scale", "rescale_cfg", "width", "height")}})


def validate_request_slots(params):
    """Validate the final request after image modules, without coercion fallbacks."""
    values = request_values(params)
    if params.get("type") not in (None, "", "generate", "txt2img") or any(
            params.get(key) for key in ("image", "mask", "image_data", "mask_data", "init_images", "img2img_image", "image_bytes", "mask_bytes")):
        raise ProfileError("MANAGED_UNSUPPORTED_REQUEST", field="type")
    return values


def validate_compiled(workflow: Mapping[str, Any], *, available_loras: Collection[str]) -> None:
    try:
        extra = set(workflow) - set(GRAPH_TEMPLATE)
        if len(extra) > 32 or extra != {str(100 + i) for i in range(len(extra))}:
            raise ValueError("nodes")
        values = {key: workflow[node]["inputs"][field] for key, (node, field, _) in SLOTS.items()}
        validate_params(values)
        expected = copy.deepcopy(GRAPH_TEMPLATE)
        for key, (node, field, _) in SLOTS.items():
            expected[node]["inputs"][field] = values[key]
        prev = "44"
        for i in range(len(extra)):
            node = str(100 + i)
            inputs = workflow[node]["inputs"]
            name, strength = inputs["lora_name"], inputs["strength_model"]
            validate_chain([{"name": name, "strength": strength}], available_loras)
            expected[node] = {"class_type": "LoraLoaderModelOnly", "inputs": {
                "lora_name": name, "strength_model": strength, "model": [prev, 0]}}
            prev = node
        expected["52"]["inputs"]["model"] = [prev, 0]
        if json.dumps(workflow, sort_keys=True, allow_nan=False) != json.dumps(expected, sort_keys=True, allow_nan=False):
            raise ValueError("graph")
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ProfileError("PROFILE_VIOLATION", field="workflow") from None
