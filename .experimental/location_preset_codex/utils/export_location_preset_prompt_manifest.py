from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
LOCATION_CATALOG_PATH = ROOT_DIR / "data" / "location_preset_catalog.json"
EFFECT_CATALOG_PATH = ROOT_DIR / "data" / "location_state_effect_catalog.json"
OUTPUT_PATH = ROOT_DIR / "data" / "location_preset_prompt_manifest.json"
BACKGROUND_WILDCARD_PATH = ROOT_DIR / "wildcards" / "danbooru_location_background.txt"

DEFAULT_EFFECT_LIMIT = 6

CONFLICT_GROUPS = [
    {"day", "night", "sunset", "twilight", "sunrise", "evening", "dusk"},
    {"sunlight", "moonlight"},
    {"day", "full moon", "moonlight", "starry sky", "star (sky)", "city lights", "full moon", "crescent moon"},
]

CONFLICT_PAIRS = {
    ("night", "sunlight"),
    ("day", "moonlight"),
    ("day", "full moon"),
    ("day", "crescent moon"),
    ("day", "starry sky"),
    ("day", "star (sky)"),
    ("day", "city lights"),
    ("sunlight", "moonlight"),
    ("sunlight", "night"),
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def make_preset_id(environment: str, place: str) -> str:
    return f"{environment}::{place}"


def load_core_state_map() -> dict[tuple[str, str], list[str]]:
    core_map: dict[tuple[str, str], list[str]] = {}
    for raw_line in BACKGROUND_WILDCARD_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(",") if part.strip()]
        if len(parts) < 2:
            continue
        key = (parts[0], parts[1])
        states = core_map.setdefault(key, [])
        if len(parts) >= 3 and parts[2] not in states:
            states.append(parts[2])
    return core_map


def tags_conflict(existing_tags: set[str], candidate: str) -> bool:
    for group in CONFLICT_GROUPS:
        if candidate in group and existing_tags & group:
            return True
    for left, right in CONFLICT_PAIRS:
        if candidate == left and right in existing_tags:
            return True
        if candidate == right and left in existing_tags:
            return True
    if candidate == "day" and "night sky" in existing_tags:
        return True
    if candidate == "night" and "blue sky" in existing_tags:
        return True
    return False


def build_effect_selection(base_tags: list[str], recommended_effects: list[str], limit: int) -> list[str]:
    selected: list[str] = []
    existing = set(base_tags)
    for tag in recommended_effects:
        if tag in existing:
            continue
        if tags_conflict(existing, tag):
            continue
        selected.append(tag)
        existing.add(tag)
        if len(selected) >= limit:
            break
    return selected


def main() -> None:
    location_catalog = load_json(LOCATION_CATALOG_PATH)
    effect_catalog = load_json(EFFECT_CATALOG_PATH)
    core_state_map = load_core_state_map()
    effect_map = {
        (sample["environment"], sample["place"]): sample
        for sample in effect_catalog.get("sample_cases", [])
    }

    presets = []
    for group in location_catalog.get("groups", []):
        environment = group["environment"]
        place = group["place"]
        structure_tags = [state["tag"] for state in group.get("states", [])]
        core_structure_tags = list(core_state_map.get((environment, place), []))
        optional_structure_tags = [tag for tag in structure_tags if tag not in core_structure_tags]
        base_tags = [environment, place]
        default_prompt_tags = base_tags + core_structure_tags

        effect_sample = effect_map.get((environment, place), {})
        recommended_effects = [item["tag"] for item in effect_sample.get("supported_effects", [])]
        default_effect_tags = build_effect_selection(default_prompt_tags, recommended_effects, DEFAULT_EFFECT_LIMIT)
        full_prompt_tags = default_prompt_tags + default_effect_tags

        presets.append(
            {
                "id": make_preset_id(environment, place),
                "environment": environment,
                "place": place,
                "place_frequency": group.get("place_frequency", 0),
                "base_tags": base_tags,
                "structure_tags": structure_tags,
                "core_structure_tags": core_structure_tags,
                "optional_structure_tags": optional_structure_tags,
                "default_prompt_tags": default_prompt_tags,
                "default_prompt": ", ".join(default_prompt_tags),
                "recommended_effect_tags": recommended_effects,
                "default_effect_tags": default_effect_tags,
                "default_effect_prompt": ", ".join(default_effect_tags),
                "full_prompt_tags": full_prompt_tags,
                "full_prompt": ", ".join(full_prompt_tags),
                "support_tier": effect_sample.get("support_tier", "dense"),
                "effect_min_support_used": effect_sample.get("min_support_used", 0),
            }
        )

    payload = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "location_catalog": "data/location_preset_catalog.json",
            "effect_catalog": "data/location_state_effect_catalog.json",
        },
        "summary": {
            "preset_count": len(presets),
            "default_effect_limit": DEFAULT_EFFECT_LIMIT,
        },
        "presets": presets,
    }

    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
