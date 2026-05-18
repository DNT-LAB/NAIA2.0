from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict


DEFAULT_INSTANT_WILDCARD_SAVE_PATH = Path("save") / "instant_wildcard"
INSTANT_WILDCARD_METADATA_FILE = "wc_metadata.json"
DEFAULT_INSTANT_WILDCARD_TEMPLATES = {
    "default.json": {
        "quality": "masterpiece, best quality",
        "negative": "lowres, bad anatomy, bad hands",
        "style": "anime style, digital art",
    },
    "캐릭터.json": {
        "girl": "1girl, solo",
        "boy": "1boy, solo",
        "multiple": "multiple girls",
    },
    "의상.json": {
        "school": "school uniform, skirt",
        "casual": "casual clothes, jeans",
        "formal": "formal wear, suit",
    },
    "장소.json": {
        "outdoor": "outdoors, sky, clouds",
        "indoor": "indoors, room",
        "city": "city, street, buildings",
    },
}


def normalize_instant_wildcard_filename(name: str) -> str:
    filename = Path(str(name or "").strip()).name
    if not filename:
        return ""
    if not filename.endswith(".json"):
        filename += ".json"
    return filename


def instant_wildcard_group_name(filename: str) -> str:
    return filename[:-5] if filename.endswith(".json") else filename


def ensure_instant_wildcard_defaults(
    save_path: Path | str = DEFAULT_INSTANT_WILDCARD_SAVE_PATH,
    templates: Dict[str, Dict[str, str]] | None = None,
) -> None:
    root = Path(save_path)
    root.mkdir(parents=True, exist_ok=True)
    if (root / "default.json").exists():
        return

    for filename, content in (templates or DEFAULT_INSTANT_WILDCARD_TEMPLATES).items():
        path = root / filename
        if path.exists():
            continue
        try:
            with path.open("w", encoding="utf-8") as handle:
                json.dump(content, handle, ensure_ascii=False, indent=2)
            print(f"[OK] Initial instant wildcard file created: {filename}")
        except Exception as exc:
            print(f"[ERROR] Failed to create instant wildcard file {filename}: {exc}")


def instant_wildcard_file_signature(save_path: Path | str = DEFAULT_INSTANT_WILDCARD_SAVE_PATH) -> tuple:
    root = Path(save_path)
    try:
        root.mkdir(parents=True, exist_ok=True)
        entries = []
        for item in sorted(root.glob("*.json"), key=lambda path: path.name):
            if item.name == INSTANT_WILDCARD_METADATA_FILE:
                continue
            stat = item.stat()
            entries.append((item.name, stat.st_mtime_ns, stat.st_size))
        return tuple(entries)
    except Exception:
        return ()


def load_instant_wildcards(
    save_path: Path | str = DEFAULT_INSTANT_WILDCARD_SAVE_PATH,
    *,
    create_defaults: bool = True,
) -> dict:
    root = Path(save_path)
    if create_defaults:
        ensure_instant_wildcard_defaults(root)
    else:
        root.mkdir(parents=True, exist_ok=True)

    json_data: dict[str, dict] = {}
    flat_dict: dict[str, Any] = {}
    tree: dict[str, dict] = {}

    json_files = sorted(
        item.name for item in root.glob("*.json") if item.name != INSTANT_WILDCARD_METADATA_FILE
    )
    if "default.json" in json_files:
        json_files.remove("default.json")
        json_files.insert(0, "default.json")

    for filename in json_files:
        path = root / filename
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:
            print(f"[ERROR] Failed to load instant wildcard file {filename}: {exc}")
            continue

        if not isinstance(data, dict):
            data = {}
        json_data[filename] = data
        group = instant_wildcard_group_name(filename)
        tree[group] = copy.deepcopy(data)
        for key, value in data.items():
            flat_key = str(key)
            if flat_key in flat_dict and group != "default":
                flat_key = f"{flat_key} ({group})"
            flat_dict[flat_key] = value

    return {
        "json_data": json_data,
        "instant_wildcard_dict": flat_dict,
        "instant_wildcard_tree": tree,
        "signature": instant_wildcard_file_signature(root),
        "save_path": str(root),
    }


def select_instant_wildcard_item(
    json_data: dict,
    current_file: str | None = None,
    current_key: str | None = None,
) -> tuple[str | None, str | None]:
    if not json_data:
        return None, None

    selected_file = current_file if current_file in json_data else next(iter(json_data.keys()))
    current_items = json_data.get(selected_file, {})
    if isinstance(current_items, dict) and current_items:
        selected_key = current_key if current_key in current_items else next(iter(sorted(current_items.keys())))
    else:
        selected_key = None
    return selected_file, selected_key


def write_instant_wildcard_file(
    json_data: dict,
    filename: str,
    save_path: Path | str = DEFAULT_INSTANT_WILDCARD_SAVE_PATH,
) -> bool:
    normalized = normalize_instant_wildcard_filename(filename)
    if not normalized:
        return False
    root = Path(save_path)
    root.mkdir(parents=True, exist_ok=True)
    data = json_data.get(normalized, {})
    try:
        with (root / normalized).open("w", encoding="utf-8") as handle:
            json.dump(data if isinstance(data, dict) else {}, handle, ensure_ascii=False, indent=2)
        return True
    except Exception as exc:
        print(f"[ERROR] Failed to save instant wildcard file {normalized}: {exc}")
        return False


def apply_instant_wildcards_to_context(app_context, save_path: Path | str = DEFAULT_INSTANT_WILDCARD_SAVE_PATH) -> dict:
    store = load_instant_wildcards(save_path)
    try:
        app_context.instant_wildcard_store = store
        wildcard_manager = getattr(app_context, "wildcard_manager", None)
        if wildcard_manager:
            wildcard_manager.update_instant_wildcards(
                store["instant_wildcard_dict"],
                store["instant_wildcard_tree"],
            )
    except Exception as exc:
        print(f"[ERROR] Failed to apply instant wildcard store: {exc}")
    return store
