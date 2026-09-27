"""Small hooks shared by every managed COMFYUI entry point."""
from __future__ import annotations

import copy
from pathlib import Path

from .manifest import MANAGED_CREDENTIAL, MODELS
from .profile import SLOTS, compile_graph, validate_request_slots
from .runtime import INSTALLING, REGISTRY_LOCK, ManagedEngineError, get_runtime
from .settings import load_settings, lora_catalog, quick_receipt, verified_hash


def save_root_of(context):
    paths = getattr(context, "runtime_paths", None)
    if paths is not None and getattr(paths, "save_dir", None) is not None:
        return Path(paths.save_dir)
    return Path(getattr(context, "repo_root", None) or Path(__file__).resolve().parents[2]) / "save"


def token_manager_of(context):
    return getattr(context, "secure_token_manager", None) or getattr(context, "token_manager", None) or context


def managed_selected(context_or_token_manager):
    manager = token_manager_of(context_or_token_manager)
    return callable(getattr(manager, "get_token", None)) and manager.get_token("comfyui_engine") == "managed"


def managed_anima(context):
    """The selected engine owns ANIMA formatting; external session flags do not."""
    return managed_selected(context)


def managed_ready(context):
    settings = load_settings(save_root_of(context))
    if settings.engine_root:
        with REGISTRY_LOCK:
            if str(Path(settings.engine_root).resolve()) in INSTALLING:
                return False
    return bool(quick_receipt(settings))


def managed_configured(context, mode="COMFYUI"):
    return mode == "COMFYUI" and managed_selected(context) and managed_ready(context)


def is_managed_credential(value):
    return value == MANAGED_CREDENTIAL


def snapshot_request(context, params):
    params.update(sampling_mode="anima", comfyui_sampling_mode="anima", workflow_type="unet")
    params.update(validate_request_slots(params))
    params["resolution"] = f'{params["width"]} x {params["height"]}'
    params["_anima_lora_chain"] = copy.deepcopy(load_settings(save_root_of(context)).lora_chain)
    params.pop("_anima_submission_attempted", None)


def prepare_managed_request(context, params):
    if params.get("_anima_submission_attempted"):
        raise ManagedEngineError("SUBMISSION_UNKNOWN", "요청을 자동 재제출하지 않습니다. 엔진 결과를 확인해 주세요.")
    if not managed_ready(context):
        raise ManagedEngineError("ENGINE_NOT_READY", "ANIMA 엔진 준비를 먼저 완료해 주세요.")
    settings = load_settings(save_root_of(context))
    catalog = {x["name"]: x for x in lora_catalog(settings)}
    chain = copy.deepcopy(params.get("_anima_lora_chain", settings.lora_chain))
    for item in chain:
        if not item.get("enabled", True):
            continue
        entry = catalog.get(item.get("name"))
        if entry is None:
            raise ManagedEngineError("LORA_NOT_FOUND", "LoRA 파일을 찾지 못했습니다.", item.get("name", ""))
        if entry["conflict"]:
            raise ManagedEngineError("LORA_NAME_CONFLICT", "LoRA 이름이 겹칩니다.", item["name"])
        digest = verified_hash(entry["path"], settings.engine_root)
        if item.get("sha256") and digest != item["sha256"]:
            raise ManagedEngineError("LORA_INVALID", "대기 중 LoRA 파일이 변경되었습니다.", item["name"])
        item["sha256"] = digest
    compiled = compile_graph(params, chain, available_loras={k for k, v in catalog.items() if not v["conflict"]})
    runtime = get_runtime(context)
    if runtime is None:
        raise ManagedEngineError("ENGINE_NOT_READY")
    url = runtime.ensure_running()
    params.update(workflow=compiled.workflow, _comfyui_output_node_id=compiled.output_node_id,
                  _comfyui_workflow_mode="managed", _anima_meta=compiled.meta, seed=compiled.seed,
                  width=compiled.meta["width"], height=compiled.meta["height"])
    params["resolution"] = f'{params["width"]} x {params["height"]}'
    # Do not embed stale external UI graphs as if they represented the managed request.
    params.pop("_comfyui_workflow_ui", None)
    runtime.touch()
    params["_anima_submission_attempted"] = True
    return url


def fixed_api_options():
    return {"options_model": [MODELS[0]["filename"]], "options_sampler": ["euler"], "options_scheduler": ["simple"]}


def apply_managed_schema(context, payload):
    """Project fixed engine options without changing the external COMFYUI plane."""
    if payload.get("api_mode") != "COMFYUI" or not managed_anima(context):
        return
    options = fixed_api_options()
    payload.update(options, steps_range=[1, 150])
    for key in ("model", "sampler", "scheduler"):
        payload[key] = options["options_" + key][0]
    stored = context.remote_params
    for key in ("steps", "cfg_scale", "rescale_cfg"):
        if key not in stored or (key == "rescale_cfg" and stored[key] in (None, "")):
            payload[key] = SLOTS[key][2]
