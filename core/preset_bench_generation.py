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

    commands = []
    for candidate, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError("item must be an object")
        characters = item.get("characters", [])
        if not isinstance(characters, list) or len(characters) > 5 or not all(isinstance(c, dict) for c in characters):
            raise ValueError("Expected up to 5 character objects")
        label = _text(item, "label")
        prompt = ", ".join(filter(None, (base["prefix"], _text(item, "main"), base["postfix"])))
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
        }
        commands.append({"type": "generate", "api_mode": "NAI", "overrides": overrides})
    return request_id, commands
