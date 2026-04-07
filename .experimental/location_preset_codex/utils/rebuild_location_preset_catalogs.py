from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKGROUND_WILDCARD_PATH = ROOT_DIR / "wildcards" / "danbooru_location_background.txt"
STATE_ROOT_DIR = ROOT_DIR / "wildcards" / "location_state"
EFFECT_WILDCARD_DIR = ROOT_DIR / "wildcards" / "location_effect_state"
TAG_PARTITION_DIR = ROOT_DIR / "data" / "tags"
LOCATION_TAGLIST_PATH = ROOT_DIR / "data" / "taglist" / "location_tags.json"
LOCATION_CATALOG_PATH = ROOT_DIR / "data" / "location_preset_catalog.json"
EFFECT_CATALOG_PATH = ROOT_DIR / "data" / "location_state_effect_catalog.json"
VALIDATION_REPORT_PATH = ROOT_DIR / "data" / "location_preset_validation_report.json"

BACKGROUND_COMBO_MIN_SUPPORT = 1
STRUCTURE_INFERENCE_MIN_SUPPORT = 5
ULTRA_SPARSE_PLACE_CUTOFF = 20
ULTRA_SPARSE_STRUCTURE_MIN_SUPPORT = 1
ULTRA_SPARSE_EFFECT_MIN_SUPPORT = 1
SPARSE_PLACE_CUTOFF = 100
SPARSE_EFFECT_MIN_SUPPORT = 3
DENSE_EFFECT_MIN_SUPPORT = 5
MAX_EFFECTS_PER_PLACE = 12

GLOBAL_STRUCTURE_CANDIDATES = [
    "bed sheet",
    "fire",
    "ice",
    "lantern",
    "fence",
    "palm tree",
    "candle",
    "tatami",
    "bench",
    "bush",
    "vines",
    "house",
    "bare tree",
    "brick wall",
    "sliding doors",
    "bamboo",
    "power lines",
    "lamppost",
    "utility pole",
    "pole",
    "chalkboard",
    "pillar",
    "futon",
    "chain-link fence",
    "paper lantern",
    "waves",
    "locker",
    "steering wheel",
    "car seat",
    "dashboard",
    "mirror",
    "open door",
    "armchair",
    "throne",
    "doorway",
    "ceiling",
    "toilet",
    "shower head",
    "floor",
    "flower pot",
    "ceiling light",
    "tombstone",
    "skyscraper",
    "carpet",
    "graffiti",
    "moss",
    "debris",
    "crack",
    "wooden table",
    "cabinet",
    "arch",
    "chandelier",
    "beach chair",
    "pool ladder",
]

SPECIAL_STRUCTURE_CANDIDATES = {
    ("indoors", "aquarium tunnel"): [
        "water",
        "tunnel",
        "coral",
        "bubble",
        "air bubble",
        "coral reef",
    ],
    ("indoors", "cave interior"): [
        "water",
        "rock",
        "stalactite",
        "stalagmite",
        "plant",
    ],
}


def load_location_taglist() -> set[str]:
    payload = json.loads(LOCATION_TAGLIST_PATH.read_text(encoding="utf-8"))
    return {str(tag).strip() for tag in payload.get("tags", []) if str(tag).strip()}


def load_effect_groups() -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for path in sorted(EFFECT_WILDCARD_DIR.glob("*.txt")):
        tags = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if tags:
            groups[path.stem] = tags
    return groups


def slugify_tag(tag: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", tag.lower())).strip("_")


def parse_wildcard_lines() -> tuple[list[tuple[str, ...]], dict[tuple[str, str], list[str]], list[tuple[str, str]]]:
    combos: list[tuple[str, ...]] = []
    group_order: list[tuple[str, str]] = []
    group_states: dict[tuple[str, str], list[str]] = {}

    for raw_line in BACKGROUND_WILDCARD_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        tags = tuple(part.strip() for part in line.split(",") if part.strip())
        if len(tags) < 2:
            continue
        env, place = tags[0], tags[1]
        key = (env, place)
        if key not in group_states:
            group_order.append(key)
            group_states[key] = []
        if len(tags) > 2:
            state = tags[2]
            if state not in group_states[key]:
                group_states[key].append(state)
        combos.append(tags)

    return combos, group_states, group_order


def parse_tag_blob(value: object) -> set[str]:
    if not isinstance(value, str) or not value:
        return set()
    return {part.strip() for part in value.split(",") if part.strip()}


def collect_counts(
    combos: list[tuple[str, ...]],
    group_states: dict[tuple[str, str], list[str]],
    effect_groups: dict[str, list[str]],
) -> tuple[
    Counter[tuple[str, str]],
    dict[tuple[str, str], Counter[str]],
    dict[tuple[str, str], Counter[str]],
    Counter[tuple[str, ...]],
    Counter[str],
]:
    effect_tags = {tag for tags in effect_groups.values() for tag in tags}
    place_to_envs: dict[str, list[str]] = defaultdict(list)
    all_tags_to_track: set[str] = set(effect_tags) | set(GLOBAL_STRUCTURE_CANDIDATES) | {"indoors", "outdoors"}

    for key, states in SPECIAL_STRUCTURE_CANDIDATES.items():
        existing_states = group_states.setdefault(key, [])
        for state in states:
            if state not in existing_states:
                existing_states.append(state)

    for (env, place), states in group_states.items():
        place_to_envs[place].append(env)
        all_tags_to_track.add(place)
        all_tags_to_track.update(states)

    group_post_counts: Counter[tuple[str, str]] = Counter()
    group_state_counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    group_effect_counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    combo_counts: Counter[tuple[str, ...]] = Counter()
    global_tag_counts: Counter[str] = Counter()

    partition_paths = sorted(TAG_PARTITION_DIR.glob("tags_*.parquet"))
    for index, path in enumerate(partition_paths, start=1):
        df = pd.read_parquet(path, columns=["general", "meta"])
        for general, meta in df.itertuples(index=False, name=None):
            tags = parse_tag_blob(general)
            if meta:
                tags.update(parse_tag_blob(meta))
            if not tags:
                continue

            relevant_tags = tags & all_tags_to_track
            for tag in relevant_tags:
                global_tag_counts[tag] += 1

            present_places = tags & place_to_envs.keys()
            if not present_places:
                continue

            present_effects = list(tags & effect_tags)
            for place in present_places:
                for env in place_to_envs[place]:
                    if env not in tags:
                        continue
                    key = (env, place)
                    group_post_counts[key] += 1
                    combo_counts[(env, place)] += 1

                    for state in group_states.get(key, []):
                        if state in tags:
                            group_state_counts[key][state] += 1
                            combo_counts[(env, place, state)] += 1

                    for candidate in GLOBAL_STRUCTURE_CANDIDATES:
                        if candidate in tags:
                            group_state_counts[key][candidate] += 1

                    for effect_tag in present_effects:
                        group_effect_counts[key][effect_tag] += 1

        if index % 10 == 0 or index == len(partition_paths):
            print(f"[scan] processed {index}/{len(partition_paths)} partitions")

    for key in SPECIAL_STRUCTURE_CANDIDATES:
        min_support = (
            ULTRA_SPARSE_STRUCTURE_MIN_SUPPORT
            if group_post_counts[key] < ULTRA_SPARSE_PLACE_CUTOFF
            else STRUCTURE_INFERENCE_MIN_SUPPORT
        )
        group_states[key] = [
            state
            for state in group_states[key]
            if group_state_counts[key][state] >= min_support
        ]

    for combo in combos:
        combo_counts.setdefault(combo, 0)

    return group_post_counts, group_state_counts, group_effect_counts, combo_counts, global_tag_counts


def write_state_wildcards(group_states: dict[tuple[str, str], list[str]]) -> None:
    STATE_ROOT_DIR.mkdir(parents=True, exist_ok=True)
    for (env, place), states in group_states.items():
        target_dir = STATE_ROOT_DIR / env
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{slugify_tag(place)}.txt"
        content = "\n".join(states).strip()
        if content:
            target_path.write_text(f"{content}\n", encoding="utf-8")
        elif target_path.exists():
            target_path.unlink()


def should_add_global_structure_state(place_frequency: int, cooccurrence_count: int) -> bool:
    if place_frequency <= 0 or cooccurrence_count <= 0:
        return False
    if place_frequency < ULTRA_SPARSE_PLACE_CUTOFF:
        return cooccurrence_count >= 1
    if place_frequency < 100:
        return cooccurrence_count >= 3
    if place_frequency < 500:
        return cooccurrence_count >= 5
    if place_frequency < 2000:
        return cooccurrence_count >= 8
    if place_frequency < 10000:
        return cooccurrence_count >= 15
    return cooccurrence_count >= 25


def build_location_catalog(
    combos: list[tuple[str, ...]],
    group_order: list[tuple[str, str]],
    group_states: dict[tuple[str, str], list[str]],
    group_post_counts: Counter[tuple[str, str]],
    group_state_counts: dict[tuple[str, str], Counter[str]],
    global_tag_counts: Counter[str],
    combo_counts: Counter[tuple[str, ...]],
) -> dict:
    groups = []
    total_structure_states = 0

    for env, place in group_order:
        key = (env, place)
        for candidate in GLOBAL_STRUCTURE_CANDIDATES:
            if candidate in group_states[key]:
                continue
            candidate_count = group_state_counts[key][candidate]
            if should_add_global_structure_state(group_post_counts[key], candidate_count):
                group_states[key].append(candidate)
        wildcard_key = f"location_state/{env}/{slugify_tag(place)}"
        states = []
        for state in group_states[key]:
            state_count = group_state_counts[key][state]
            if state_count <= 0:
                continue
            states.append(
                {
                    "tag": state,
                    "cooccurrence_count": state_count,
                    "global_frequency": global_tag_counts[state],
                }
            )
        total_structure_states += len(states)
        groups.append(
            {
                "environment": env,
                "place": place,
                "place_frequency": group_post_counts[key],
                "wildcard_key": wildcard_key,
                "background_combo_key": "danbooru_location_background",
                "states": states,
                "state_file_exists": bool(states),
            }
        )

    validated_combo_counts = [combo_counts[combo] for combo in combos]
    return {
        "version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "background_wildcard": "wildcards/danbooru_location_background.txt",
            "tag_partitions": "data/tags/tags_*.parquet",
            "structure_inference": "dataset cooccurrence",
        },
        "summary": {
            "background_combo_count": len(combos),
            "validated_combo_count": sum(1 for count in validated_combo_counts if count >= BACKGROUND_COMBO_MIN_SUPPORT),
            "group_count": len(groups),
            "state_wildcard_file_count": sum(1 for group in groups if group["state_file_exists"]),
            "structure_state_count": total_structure_states,
            "background_combo_min_count": min(validated_combo_counts),
            "background_combo_median_count": statistics.median(validated_combo_counts),
        },
        "groups": groups,
    }


def build_effect_catalog(
    location_catalog: dict,
    group_effect_counts: dict[tuple[str, str], Counter[str]],
    global_tag_counts: Counter[str],
    location_taglist: set[str],
    effect_groups: dict[str, list[str]],
) -> dict:
    effect_groups_payload = []
    for group_name, tags in effect_groups.items():
        effect_groups_payload.append(
            {
                "group": group_name,
                "effects": [
                    {
                        "tag": tag,
                        "global_frequency": global_tag_counts[tag],
                        "exists_in_location_tags": tag in location_taglist,
                    }
                    for tag in tags
                ],
            }
        )

    sample_cases = []
    covered_groups = 0
    total_effect_assignments = 0

    tag_to_group = {tag: group for group, tags in effect_groups.items() for tag in tags}
    for group in location_catalog["groups"]:
        key = (group["environment"], group["place"])
        place_frequency = group["place_frequency"]
        if place_frequency < ULTRA_SPARSE_PLACE_CUTOFF:
            min_support = ULTRA_SPARSE_EFFECT_MIN_SUPPORT
            support_tier = "ultra_sparse"
        elif place_frequency < SPARSE_PLACE_CUTOFF:
            min_support = SPARSE_EFFECT_MIN_SUPPORT
            support_tier = "sparse"
        else:
            min_support = DENSE_EFFECT_MIN_SUPPORT
            support_tier = "dense"

        supported_effects = []
        for tag, count in group_effect_counts[key].items():
            if count < min_support:
                continue
            supported_effects.append(
                {
                    "tag": tag,
                    "group": tag_to_group[tag],
                    "cooccurrence_count": count,
                    "global_frequency": global_tag_counts[tag],
                }
            )

        supported_effects.sort(
            key=lambda item: (-item["cooccurrence_count"], -item["global_frequency"], item["tag"])
        )
        supported_effects = supported_effects[:MAX_EFFECTS_PER_PLACE]
        if supported_effects:
            covered_groups += 1
        total_effect_assignments += len(supported_effects)
        sample_cases.append(
            {
                "environment": group["environment"],
                "place": group["place"],
                "place_frequency": place_frequency,
                "support_tier": support_tier,
                "min_support_used": min_support,
                "supported_effects": supported_effects,
            }
        )

    return {
        "version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "location_catalog": "data/location_preset_catalog.json",
            "tag_partitions": "data/tags/tags_*.parquet",
            "effect_wildcards": {
                path.stem: f"wildcards/location_effect_state/{path.name}"
                for path in sorted(EFFECT_WILDCARD_DIR.glob("*.txt"))
            },
        },
        "validation": {
            "group_count": len(location_catalog["groups"]),
            "covered_group_count": covered_groups,
            "effect_tag_count": sum(len(tags) for tags in effect_groups.values()),
            "effect_assignment_count": total_effect_assignments,
            "dense_min_support": DENSE_EFFECT_MIN_SUPPORT,
            "sparse_min_support": SPARSE_EFFECT_MIN_SUPPORT,
            "ultra_sparse_min_support": ULTRA_SPARSE_EFFECT_MIN_SUPPORT,
            "ultra_sparse_place_cutoff": ULTRA_SPARSE_PLACE_CUTOFF,
            "sparse_place_cutoff": SPARSE_PLACE_CUTOFF,
        },
        "effect_groups": effect_groups_payload,
        "sample_cases": sample_cases,
    }


def build_validation_report(
    combos: list[tuple[str, ...]],
    location_catalog: dict,
    effect_catalog: dict,
    combo_counts: Counter[tuple[str, ...]],
) -> dict:
    combo_values = [combo_counts[combo] for combo in combos]
    structure_ready = [group for group in location_catalog["groups"] if group["states"]]
    effect_ready = [sample for sample in effect_catalog["sample_cases"] if sample["supported_effects"]]

    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "thresholds": {
            "background_combo_min_support": BACKGROUND_COMBO_MIN_SUPPORT,
            "structure_inference_min_support": STRUCTURE_INFERENCE_MIN_SUPPORT,
            "ultra_sparse_structure_min_support": ULTRA_SPARSE_STRUCTURE_MIN_SUPPORT,
            "dense_effect_min_support": DENSE_EFFECT_MIN_SUPPORT,
            "sparse_effect_min_support": SPARSE_EFFECT_MIN_SUPPORT,
            "ultra_sparse_effect_min_support": ULTRA_SPARSE_EFFECT_MIN_SUPPORT,
            "ultra_sparse_place_cutoff": ULTRA_SPARSE_PLACE_CUTOFF,
            "sparse_place_cutoff": SPARSE_PLACE_CUTOFF,
        },
        "coverage": {
            "background_combo_total": len(combos),
            "background_combo_validated": sum(1 for count in combo_values if count >= BACKGROUND_COMBO_MIN_SUPPORT),
            "background_combo_zero_count": sum(1 for count in combo_values if count == 0),
            "background_combo_min_count": min(combo_values),
            "background_combo_median_count": statistics.median(combo_values),
            "background_combo_max_count": max(combo_values),
            "group_total": len(location_catalog["groups"]),
            "group_with_structure_states": len(structure_ready),
            "group_with_effect_states": len(effect_ready),
            "structure_state_total": sum(len(group["states"]) for group in location_catalog["groups"]),
            "effect_assignment_total": sum(len(sample["supported_effects"]) for sample in effect_catalog["sample_cases"]),
        },
        "missing": {
            "structure_state_groups": [
                {"environment": group["environment"], "place": group["place"]}
                for group in location_catalog["groups"]
                if not group["states"]
            ],
            "effect_state_groups": [
                {"environment": sample["environment"], "place": sample["place"]}
                for sample in effect_catalog["sample_cases"]
                if not sample["supported_effects"]
            ],
        },
    }


def main() -> None:
    location_taglist = load_location_taglist()
    effect_groups = load_effect_groups()
    combos, group_states, group_order = parse_wildcard_lines()
    (
        group_post_counts,
        group_state_counts,
        group_effect_counts,
        combo_counts,
        global_tag_counts,
    ) = collect_counts(combos, group_states, effect_groups)

    write_state_wildcards(group_states)
    location_catalog = build_location_catalog(
        combos,
        group_order,
        group_states,
        group_post_counts,
        group_state_counts,
        global_tag_counts,
        combo_counts,
    )
    effect_catalog = build_effect_catalog(
        location_catalog,
        group_effect_counts,
        global_tag_counts,
        location_taglist,
        effect_groups,
    )
    validation_report = build_validation_report(
        combos,
        location_catalog,
        effect_catalog,
        combo_counts,
    )

    LOCATION_CATALOG_PATH.write_text(
        json.dumps(location_catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    EFFECT_CATALOG_PATH.write_text(
        json.dumps(effect_catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    VALIDATION_REPORT_PATH.write_text(
        json.dumps(validation_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "location_summary": location_catalog["summary"],
                "effect_validation": effect_catalog["validation"],
                "coverage": validation_report["coverage"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
