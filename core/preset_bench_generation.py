"""Saved bases and request-local generation inputs for the preset bench."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone

from core.prompt_engineering_settings import (
    get_prompt_engineering_store, is_synthetic_preset_name, sanitize_preset_name,
)


_PARAM_KEYS = ("model", "width", "height", "steps", "cfg_scale", "cfg_rescale", "sampler", "scheduler")
_LIMITS = {"width": (64, 2048), "height": (64, 2048), "steps": (1, 50),
           "cfg_scale": (0, 30), "cfg_rescale": (0, 1)}
_DIRECT_LOCK = threading.Lock()
# 캐릭터 레퍼런스 - NAI 한 요청의 상한(Interactive 레퍼런스와 같은 4). 그림 한 장 전체에 걸린다(캐릭터별이 아니다).
MAX_REFERENCES = 4
_REFERENCE_SOURCES = ("storage", "asset")
# REF 창(Character Reference 모듈)과 같은 셋 - 보관함 설정의 종류를 그대로 싣는다.
_REFERENCE_TYPES = ("character&style", "character", "style")
# 벤치 해상도 = 1024² 묶음만(사용자 11-20). 기반 프리셋 · 직접 설정의 크기 대신 늘 이것으로 그린다.
BENCH_SIZES = ("1024 x 1024", "960 x 1088", "896 x 1152", "832 x 1216", "1088 x 960", "1152 x 896", "1216 x 832")


def _split_tags(text):
    return [tag.strip() for tag in str(text or "").split(",") if tag.strip()]


def person_first_prompt(prefix, main, postfix):
    """prefix + 가운데 몫 + postfix 를 잇되 인원 태그(1girl · 1boy …)는 맨 앞에 둔다(사용자 11-20).

    NAIA 메인 생성의 규칙(prompt_processor 최종 포맷 단계)과 같다 - 가운데 몫(main_tags)의 인원 태그를 꺼내
    boys -> girls -> others 로 세워 prefix 보다 앞에 두고, 같은 인원 태그는 처음 것만 남긴다.
    prefix · postfix 글은 인원 태그가 겹칠 때만 태그 단위로 다시 짠다(아니면 쓴 그대로 - 줄바꿈 · 주석을 지킨다).
    """
    from core.prompt_processor import ALL_PERSON_TAGS, PERSON_TAG_SETS
    middle = _split_tags(main)
    rank = lambda tag: 0 if tag in PERSON_TAG_SETS["boys"] else 1 if tag in PERSON_TAG_SETS["girls"] else 2
    people = []
    for tag in sorted((tag for tag in middle if tag in ALL_PERSON_TAGS), key=rank):
        if tag not in people:
            people.append(tag)
    if not people:
        return ", ".join(filter(None, (prefix, main, postfix)))
    rest = ", ".join(tag for tag in middle if tag not in ALL_PERSON_TAGS)

    def without_people(text):
        tags = _split_tags(text)
        if not any(tag in people for tag in tags):
            return text
        return ", ".join(tag for tag in tags if tag not in people)

    return ", ".join(filter(None, (", ".join(people), without_people(prefix), rest, without_people(postfix))))


def _text(source, key):
    value = source.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value.strip()


def _saved_names(store):
    return [name for name in store.list_preset_names("NAI")
            if not is_synthetic_preset_name(name) and not name.endswith(".hires")]


def preset_bench_base_from_preset(context, name, *, names=None) -> dict:
    store = get_prompt_engineering_store(context)
    if name not in (names if names is not None else _saved_names(store)):
        raise KeyError(name)
    data = store.read_preset_data(name, "NAI")
    if not data:
        raise KeyError(name)
    module = data.get("module_settings") if isinstance(data.get("module_settings"), dict) else {}
    main = data.get("main_settings") if isinstance(data.get("main_settings"), dict) else {}
    params = context._character_asset_service()._profile_generation_params(main)
    params.update({key: main[key] for key in ("width", "height") if key in main})
    # SMEA · DYN 은 V3 사양이라 싣지 않는다(사용자 지시 2026-11-19).
    for key in ("SMEA", "DYN"):
        params.pop(key, None)
    return {"name": name, "prefix": str(module.get("pre_prompt") or "").strip(),
            "postfix": str(module.get("post_prompt") or "").strip(),
            "negative_prompt": str(main.get("negative") or main.get("negative_prompt") or "").strip(),
            "params": params}


def preset_bench_bases(context):
    store = get_prompt_engineering_store(context)
    current = store.state("NAI").get("current_preset") or ""
    names = set(_saved_names(store))
    presets = []
    for name in sorted(names):
        try:
            base = preset_bench_base_from_preset(context, name, names=names)
        except KeyError:
            continue  # A preset can disappear between listing and reading its file.
        presets.append(dict(base, is_current=name == current))
    return {"current": current, "presets": presets}


def direct_base(payload):
    params = payload.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    result = {}
    for key in _PARAM_KEYS:
        if key not in params:
            continue
        value = params[key]
        if key in _LIMITS:
            low, high = _LIMITS[key]
            if type(value) not in (int, float) or not low <= value <= high:
                raise ValueError(f"{key} must be between {low} and {high}")
            if key in ("width", "height", "steps") and not isinstance(value, int):
                raise ValueError(f"{key} must be an integer")
            if key in ("width", "height") and value % 64:
                raise ValueError(f"{key} must be a multiple of 64")
        elif not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        result[key] = value
    return {"prefix": _text(payload, "prefix"), "postfix": _text(payload, "postfix"),
            "negative_prompt": _text(payload, "negative_prompt"), "params": result}


def _direct_name(name):
    name = name.strip()
    if not 1 <= len(name) <= 60 or sanitize_preset_name(name) != name:
        raise ValueError("Invalid direct settings name")
    return name


class DirectSettingsStore:
    def __init__(self, runtime_paths):
        self.path = runtime_paths.save_dir / "preset_bench" / "direct_settings.json"

    def _read(self):
        try:
            data = json.loads(self.path.read_bytes())
        except FileNotFoundError:
            return {}
        if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("items"), dict):
            raise ValueError("Invalid direct settings file")
        return data["items"]

    def _write(self, items):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False)
        try:
            with tmp:
                json.dump({"schema": 1, "items": items}, tmp, ensure_ascii=False)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp.name, self.path)
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)

    def list_items(self):
        with _DIRECT_LOCK:
            return {"items": [dict(item, name=name) for name, item in sorted(self._read().items())]}

    def put(self, name, payload):
        name = _direct_name(name)
        item = direct_base(payload)
        with _DIRECT_LOCK:
            items = self._read()
            if name not in items and len(items) >= 200:
                raise ValueError("At most 200 direct settings may be saved")
            item["updated_at"] = datetime.now(timezone.utc).isoformat()
            items[name] = item
            self._write(items)
        return dict(item, name=name)

    def delete(self, name):
        name = _direct_name(name)
        with _DIRECT_LOCK:
            items = self._read()
            del items[name]
            self._write(items)
        return {"ok": True, "name": name}


def export_direct_base(context, payload):
    from core.headless_random_prompt_service import pipeline_swap_lock

    name = _text(payload, "preset")
    if is_synthetic_preset_name(name):
        return False, "Cannot export to a snapshot or randomized preset"
    if not name or sanitize_preset_name(name) != name:
        raise ValueError("Invalid preset name")
    overwrite = payload.get("overwrite", False)
    if not isinstance(overwrite, bool):
        raise ValueError("overwrite must be a boolean")
    base = direct_base(payload)
    store = get_prompt_engineering_store(context)
    with pipeline_swap_lock(context):
        existing = {os.path.normcase(n): n for n in store.list_preset_names("NAI")}
        target = existing.get(os.path.normcase(name))
        if target is not None:
            name = target
            data = store.read_preset_data(name, "NAI")
        else:
            main = context._prompt_engineering_service()._capture_main_settings()
            main.pop("prompt", None)
            data = {"module_settings": store.collect_settings("NAI"), "main_settings": main}
        data.setdefault("module_settings", {}).update(pre_prompt=base["prefix"], post_prompt=base["postfix"])
        main = data.setdefault("main_settings", {})
        main.pop("negative_prompt", None)
        main.update(negative=base["negative_prompt"], **base["params"])
        if "width" in base["params"] and "height" in base["params"]:
            main["resolution"] = f'{base["params"]["width"]} x {base["params"]["height"]}'
        return store.export_preset(name, "NAI", data, overwrite=overwrite)


def bench_reference_params(context, references, params):
    """벤치 생성 한 번에만 싣는 Character Reference(세션 프레임 · REF 창 목록은 건드리지 않는다).

    references = [{source: storage, file_hash} | {source: asset, id, variation}, + reference_type · strength · fidelity].
    storage = REF 창 보관함 그림, asset = 캐릭터 에셋 그림(대표 또는 변형). 계약은 core/.claude/NAI_CHARACTER_CLAUDE.md §3:
    image_data() 로 NAI 캔버스에 맞추고 · fidelity 는 반전(1 - x) · 0.05 양자화 · 지원 안 하는 모델은 조용히 빼지 않고 거부.
    """
    if references in (None, []):
        return {}
    if not isinstance(references, list) or not all(isinstance(ref, dict) for ref in references):
        raise ValueError("references must be a list of objects")
    if len(references) > MAX_REFERENCES:
        raise ValueError(f"Character Reference is limited to {MAX_REFERENCES} images per request")
    from PIL import Image

    from core.nai_model_contract import resolve_nai_model_for_context

    assets = context._character_asset_service()
    model_key = assets._effective_model_key({"params": params})
    spec = resolve_nai_model_for_context(context, model_key) if model_key else None
    if spec is not None and not spec.supports_character_reference:
        raise ValueError(f"Character Reference is not supported by the base model ({model_key})")
    encoder = context._character_reference_service()
    cache = assets._bench_reference_cache
    out = {key: [] for key in (
        "director_reference_descriptions", "director_reference_images", "director_reference_information_extracted",
        "director_reference_strength_values", "director_reference_secondary_strength_values")}
    for ref in references:
        source = _text(ref, "source")
        if source not in _REFERENCE_SOURCES:
            raise ValueError(f"unknown reference source: {source}")
        reference_type = (_text(ref, "reference_type") or "character&style").lower()
        if reference_type not in _REFERENCE_TYPES:
            raise ValueError(f"unknown Character Reference type: {reference_type}")
        strength = assets._bench_reference_scale(ref.get("strength"), 1.0, "strength")
        fidelity = assets._bench_reference_scale(ref.get("fidelity"), 0.8, "fidelity")
        if source == "storage":
            path = assets.reference_storage_path(_text(ref, "file_hash"))
            if path is None:
                raise FileNotFoundError("reference image not found in storage")
        else:
            path = assets.resolve_image_path(_text(ref, "id"), _text(ref, "variation"))
        key = (str(path), path.stat().st_mtime_ns)
        encoded = cache.get(key)
        if encoded is None:
            with Image.open(path) as opened:
                opened.load()
                encoded = encoder.image_data(opened)
            if len(cache) > 8:
                cache.clear()
            cache[key] = encoded
        out["director_reference_descriptions"].append(
            {"caption": {"base_caption": reference_type, "char_captions": []}, "legacy_uc": False})
        out["director_reference_images"].append(encoded)
        out["director_reference_information_extracted"].append(1)
        out["director_reference_strength_values"].append(strength)
        out["director_reference_secondary_strength_values"].append(round((1.0 - fidelity) * 20) / 20.0)
    return {**out, "controlnet_strength": 1, "inpaintImg2ImgStrength": 1, "normalize_reference_strength_multiple": True}


def db_character_prompt(viewer, group, character, variant=""):
    """캐릭터 DB 한 명을 벤치 캐릭터 칸 글로 - Characters 창과 같은 build_prompt 에서 옷 태그만 뺀다(의상 칸이 따로 있다).
    코스프레 · 추가 프롬프트(Characters 창 설정)는 싣지 않는다."""
    if not group or not character:
        raise ValueError("group and character are required")
    built = viewer.build_prompt(group, character, variant, {"cosplay_enabled": False, "character_extra": ""})
    data = viewer._get_character(group, character)
    _pc, _ch, attire = viewer._variant_items(data, viewer._resolve_variant(data, variant))
    attire_tags = {viewer.TAG_REPLACE.get(entry.get("tag", ""), entry.get("tag", "")) for entry in attire or []}
    tags = [tag.strip() for tag in str(built.get("character_prompt") or "").split(",")]
    return {"prompt": ", ".join(tag for tag in tags if tag and tag not in attire_tags),
            "gender": viewer.prompt_head(data), "removed": sorted(tag for tag in attire_tags if tag)}


def generation_commands(context, payload):
    request_id = _text(payload, "request_id")
    items = payload.get("items")
    if not request_id:
        raise ValueError("request_id is required")
    if not isinstance(items, list) or not 1 <= len(items) <= 20:
        raise ValueError("Expected 1 to 20 items")
    base = payload.get("base")
    if not isinstance(base, dict):
        raise ValueError("base must be an object")
    if base.get("mode") == "preset":
        base = preset_bench_base_from_preset(context, _text(base, "name"))
    elif base.get("mode") == "direct":
        base = direct_base(base)
    else:
        raise ValueError("Invalid base mode")
    size = payload.get("size")
    if size is not None:
        if size not in BENCH_SIZES:
            raise ValueError(f"size must be one of {', '.join(BENCH_SIZES)}")
        width, height = (int(side) for side in size.split(" x "))
        base = {**base, "params": {**base["params"], "width": width, "height": height}}
    references = bench_reference_params(context, payload.get("references"), base["params"])

    commands = []
    for candidate, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError("item must be an object")
        characters = item.get("characters", [])
        if not isinstance(characters, list) or len(characters) > 5 or not all(isinstance(c, dict) for c in characters):
            raise ValueError("Expected up to 5 character objects")
        label = _text(item, "label")
        prompt = person_first_prompt(base["prefix"], _text(item, "main"), base["postfix"])
        overrides = {
            **base["params"], "input": prompt, "_raw_input": prompt, "negative_prompt": base["negative_prompt"],
            "characters": [_text(c, "prompt") for c in characters], "uc": [_text(c, "uc") for c in characters],
            "random_resolution": False, "wildcard_standalone": True,
            "_skip_character_late_binding": True, "_skip_vibe_transfer_late_binding": True,
            "_skip_character_reference_late_binding": True, "transparent_background": False,
            "use_custom_api_params": False,  # Live custom JSON can replace the entire caption block.
            "seed": -1, "seed_fixed": False, "auto_generate": False,
            "_remote_queue_source": "Preset Bench", "_remote_queue_label": label,
            "preset_bench_request": True, "preset_bench_request_id": request_id,
            "preset_bench_candidate": candidate, "preset_bench_label": label,
            # 레퍼런스가 있으면 director_* 가 실려 세션 CR 늦은 바인딩은 저절로 비켜난다(위 skip 표식은 없을 때의 격리).
            **references,
        }
        commands.append({"type": "generate", "api_mode": "NAI", "overrides": overrides})
    return request_id, commands
