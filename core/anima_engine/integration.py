"""Small hooks shared by every managed COMFYUI entry point."""
from __future__ import annotations

import copy
from pathlib import Path

from .manifest import MANAGED_CREDENTIAL, MODELS
from .profile import SLOTS, compile_graph, validate_request_slots
from .runtime import INSTALLING, REGISTRY_LOCK, ManagedEngineError, get_runtime
from .prompt_loras import PromptLoraError, extract_prompt_loras, merge_prompt_loras
from .settings import load_settings, lora_catalog, lora_keyword_map, quick_receipt, unet_catalog, verified_hash


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


def managed_models(context):
    """관리형 엔진이 고를 수 있는 ANIMA 모델 이름 — 기본 모델이 맨 앞(설치 전에도 기본 모델 하나는 보인다)."""
    names = [x["name"] for x in unet_catalog(load_settings(save_root_of(context)))["available"]]
    default = MODELS[0]["filename"]
    return names if default in names else [default] + names


def resolve_model(context, requested):
    """요청의 모델 -> 관리형 목록의 이름. 목록에 없으면(외부 ComfyUI 에서 남은 체크포인트 이름 · 빈 값) 기본 모델 —
    Model 칸이 보여 주는 것(apply_managed_schema)과 같다. Model 칸을 거치지 않는 생성(작가 썸네일 등)도 이 길이다."""
    requested = str(requested or "").strip()
    return requested if requested and requested in managed_models(context) else MODELS[0]["filename"]


def snapshot_request(context, params):
    params.update(sampling_mode="anima", comfyui_sampling_mode="anima", workflow_type="unet")
    params.update(validate_request_slots(params))
    params["resolution"] = f'{params["width"]} x {params["height"]}'
    settings = load_settings(save_root_of(context))
    params["_anima_lora_chain"] = copy.deepcopy(settings.lora_chain)
    # 예약어 표도 큐에 넣는 순간의 것 - 기다리는 동안 예약어를 다른 LoRA 로 옮겨도 이 생성은 그대로다(Codex 09-30).
    # 표 **전체**다: 입력창의 와일드카드는 실행 직전에 풀려(_expand_input_wildcards) 지금은 어떤 예약어가 나올지 모른다.
    params["_anima_lora_keywords"] = lora_keyword_map(settings)
    # 모델도 큐에 넣는 순간의 것 — 그 뒤 파일이 사라지면 몰래 기본 모델로 바꾸지 않고 거절한다(LoRA 와 같은 규칙)
    params["model"] = params["_anima_model"] = resolve_model(context, params.get("model"))
    params.pop("_anima_submission_attempted", None)


def prepare_managed_request(context, params):
    if params.get("_anima_submission_attempted"):
        raise ManagedEngineError("SUBMISSION_UNKNOWN", "요청을 자동 재제출하지 않습니다. 엔진 결과를 확인해 주세요.")
    if not managed_ready(context):
        raise ManagedEngineError("ENGINE_NOT_READY", "ANIMA 엔진 준비를 먼저 완료해 주세요.")
    settings = load_settings(save_root_of(context))
    catalog = {x["name"]: x for x in lora_catalog(settings)}
    chain = copy.deepcopy(params.get("_anima_lora_chain", settings.lora_chain))
    # 프롬프트의 lora:예약어:강도(09-30) - 와일드카드가 다 풀린 글에서. 원문(input)은 그대로 두고 엔진 글에서만 뺀다.
    try:
        queued = params.get("_anima_lora_keywords")
        keywords = queued if isinstance(queued, dict) else lora_keyword_map(settings)
        text, prompt_loras = extract_prompt_loras(params.get("input"), keywords)
    except PromptLoraError as exc:
        raise ManagedEngineError(exc.code, exc.message, exc.token) from None
    chain = merge_prompt_loras(chain, prompt_loras)
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
    models = {x["name"] for x in unet_catalog(settings)["available"]}
    model = params.get("_anima_model") or resolve_model(context, params.get("model"))
    if model not in models:
        raise ManagedEngineError("MODEL_NOT_FOUND", "ANIMA 모델 파일을 찾지 못했습니다.", model)
    compiled = compile_graph({**params, "input": text}, chain,
                             available_loras={k for k, v in catalog.items() if not v["conflict"]},
                             model=model, available_models=models)
    runtime = get_runtime(context)
    if runtime is None:
        raise ManagedEngineError("ENGINE_NOT_READY")
    url = runtime.ensure_running()
    params.update(workflow=compiled.workflow, _comfyui_output_node_id=compiled.output_node_id, model=model,
                  _comfyui_workflow_mode="managed", _anima_meta=compiled.meta, seed=compiled.seed,
                  width=compiled.meta["width"], height=compiled.meta["height"])
    params["resolution"] = f'{params["width"]} x {params["height"]}'
    # Do not embed stale external UI graphs as if they represented the managed request.
    params.pop("_comfyui_workflow_ui", None)
    runtime.touch()
    # 큐 시점 예약어 표는 여기까지만 쓴다(이 뒤로는 다시 내지 않는다) - 그대로 두면 PNG 메타(naia_generation_params) ·
    # 히스토리에 LoRA 서재 전체가 남는다. 이 그림에 실제로 켠 것은 _anima_meta.loras 에 있다.
    params.pop("_anima_lora_keywords", None)
    params["_anima_submission_attempted"] = True
    return url


def managed_api_options(context):
    # 샘플러 · 스케줄러는 SPD 그래프 고정, 모델은 목록에서 고른다
    return {"options_model": managed_models(context), "options_sampler": ["euler"], "options_scheduler": ["simple"]}


def apply_managed_schema(context, payload):
    """Project fixed engine options without changing the external COMFYUI plane."""
    if payload.get("api_mode") != "COMFYUI" or not managed_anima(context):
        return
    options = managed_api_options(context)
    payload.update(options, steps_range=[1, 150])
    for key in ("sampler", "scheduler"):
        payload[key] = options["options_" + key][0]
    # 세션에 남은 모델이 목록에 있으면 그것, 아니면 기본 모델(resolve_model 과 같은 규칙) — remote_params 는 그대로 둔다
    chosen = str(context.remote_params.get("model") or "").strip()
    payload["model"] = chosen if chosen in options["options_model"] else options["options_model"][0]
    stored = context.remote_params
    for key in ("steps", "cfg_scale", "rescale_cfg"):
        if key not in stored or (key == "rescale_cfg" and stored[key] in (None, "")):
            payload[key] = SLOTS[key][2]
