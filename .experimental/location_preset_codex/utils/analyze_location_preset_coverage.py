from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
LOCATION_TAGLIST_PATH = ROOT_DIR / "data" / "taglist" / "location_tags.json"
TAG_COUNT_PATH = ROOT_DIR / "data" / "ezmode" / "output.json"
LOCATION_CATALOG_PATH = ROOT_DIR / "data" / "location_preset_catalog.json"
EFFECT_CATALOG_PATH = ROOT_DIR / "data" / "location_state_effect_catalog.json"
ANALYSIS_PATH = ROOT_DIR / "data" / "location_preset_coverage_analysis.json"

PRIORITY_BUCKETS = {
    "global_effect_candidates": [
        "sky",
        "cloud",
        "blurry",
        "sparkle",
        "petals",
        "moon",
        "star (sky)",
        "light particles",
        "cherry blossoms",
        "wind",
        "full moon",
        "starry sky",
        "blurry foreground",
        "falling petals",
        "glint",
        "snowing",
        "chromatic aberration",
        "water drop",
        "motion blur",
        "floral background",
        "horizon",
        "sun",
        "film grain",
        "autumn leaves",
        "snowflakes",
        "fireworks",
        "winter",
        "crescent moon",
        "summer",
        "dappled sunlight",
        "sunbeam",
        "evening",
        "city lights",
        "dusk",
    ],
    "structure_state_candidates": [
        "bed sheet",
        "fire",
        "lantern",
        "fence",
        "palm tree",
        "candle",
        "tatami",
        "bench",
        "vines",
        "house",
        "brick wall",
        "sliding doors",
        "bamboo",
        "power lines",
        "lamppost",
        "chalkboard",
        "pillar",
        "futon",
        "chain-link fence",
        "paper lantern",
        "waves",
        "locker",
        "open door",
        "armchair",
        "throne",
        "doorway",
        "ceiling",
        "toilet",
        "floor",
        "ceiling light",
        "flower pot",
    ],
    "place_anchor_candidates": [
        "pool",
        "onsen",
        "space",
        "poolside",
        "train interior",
        "school",
        "shop",
        "path",
        "hill",
    ],
    "broad_scene_descriptors": [
        "scenery",
        "nature",
        "architecture",
        "east asian architecture",
        "crowd",
        "abstract background",
        "photo background",
    ],
}

THRESHOLDS = [100, 500, 1000, 5000, 10000, 50000, 100000]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_used_tag_set(location_catalog: dict, effect_catalog: dict) -> set[str]:
    return (
        {group["environment"] for group in location_catalog["groups"]}
        | {group["place"] for group in location_catalog["groups"]}
        | {state["tag"] for group in location_catalog["groups"] for state in group["states"]}
        | {effect["tag"] for group in effect_catalog["effect_groups"] for effect in group["effects"]}
    )


def summarize_bucket(tags: list[str], location_tags: set[str], used_tags: set[str], counts: dict[str, int]) -> dict:
    present = [tag for tag in tags if tag in location_tags]
    covered = [tag for tag in present if tag in used_tags]
    missing = [tag for tag in present if tag not in used_tags]
    missing_sorted = sorted(missing, key=lambda tag: (-int(counts.get(tag, 0)), tag))
    return {
        "tag_count": len(present),
        "covered_count": len(covered),
        "missing_count": len(missing),
        "coverage_pct": round((len(covered) / len(present) * 100), 2) if present else 0.0,
        "missing_tags": [
            {"tag": tag, "count": int(counts.get(tag, 0))}
            for tag in missing_sorted
        ],
    }


def summarize_thresholds(
    thresholds: list[int],
    location_tags: set[str],
    used_tags: set[str],
    counts: dict[str, int],
    expansion_candidates: set[str],
) -> list[dict]:
    rows = []
    for threshold in thresholds:
        tags = [tag for tag in location_tags if int(counts.get(tag, 0)) >= threshold]
        covered = [tag for tag in tags if tag in used_tags]
        expanded = [tag for tag in tags if tag in used_tags or tag in expansion_candidates]
        total_weight = sum(int(counts.get(tag, 0)) for tag in tags)
        covered_weight = sum(int(counts.get(tag, 0)) for tag in covered)
        expanded_weight = sum(int(counts.get(tag, 0)) for tag in expanded)
        rows.append(
            {
                "min_count": threshold,
                "tag_total": len(tags),
                "covered_count": len(covered),
                "coverage_pct": round((len(covered) / len(tags) * 100), 2) if tags else 0.0,
                "weighted_coverage_pct": round((covered_weight / total_weight * 100), 2) if total_weight else 0.0,
                "expanded_covered_count": len(expanded),
                "expanded_coverage_pct": round((len(expanded) / len(tags) * 100), 2) if tags else 0.0,
                "expanded_weighted_coverage_pct": round((expanded_weight / total_weight * 100), 2) if total_weight else 0.0,
            }
        )
    return rows


def main() -> None:
    location_tags = set(load_json(LOCATION_TAGLIST_PATH)["tags"])
    tag_counts = {key: int(value) for key, value in load_json(TAG_COUNT_PATH).items()}
    location_catalog = load_json(LOCATION_CATALOG_PATH)
    effect_catalog = load_json(EFFECT_CATALOG_PATH)

    used_tags = build_used_tag_set(location_catalog, effect_catalog)
    covered_tags = sorted(location_tags & used_tags)
    uncovered_tags = sorted(location_tags - used_tags, key=lambda tag: (-int(tag_counts.get(tag, 0)), tag))
    expansion_candidates = set(sum(PRIORITY_BUCKETS.values(), []))

    analysis = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "location_tags": "data/taglist/location_tags.json",
            "tag_counts": "data/ezmode/output.json",
            "location_catalog": "data/location_preset_catalog.json",
            "effect_catalog": "data/location_state_effect_catalog.json",
        },
        "summary": {
            "location_tag_total": len(location_tags),
            "used_tag_total": len(used_tags),
            "covered_tag_total": len(covered_tags),
            "uncovered_tag_total": len(uncovered_tags),
            "raw_coverage_pct": round((len(covered_tags) / len(location_tags) * 100), 2),
        },
        "coverage_by_threshold": summarize_thresholds(
            THRESHOLDS,
            location_tags,
            used_tags,
            tag_counts,
            expansion_candidates,
        ),
        "priority_buckets": {
            name: summarize_bucket(tags, location_tags, used_tags, tag_counts)
            for name, tags in PRIORITY_BUCKETS.items()
        },
        "top_uncovered_tags": [
            {"tag": tag, "count": int(tag_counts.get(tag, 0))}
            for tag in uncovered_tags[:150]
        ],
        "notes": [
            "raw unique-tag coverage is low because location_tags.json mixes place anchors, structural props, sky/weather overlays, background FX, and long-tail decorative tags in one bucket",
            "the current preset data covers the core place anchors and a subset of high-value structures/effects, but it still misses many global overlay tags",
            "expanded coverage columns simulate adding the priority bucket candidates without changing the current catalogs",
        ],
    }

    ANALYSIS_PATH.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(analysis["summary"], ensure_ascii=False, indent=2))
    print(json.dumps(analysis["coverage_by_threshold"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
