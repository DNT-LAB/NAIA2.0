"""Build the shared, ranked list of preset thumbnail prompts."""

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / ".experimental" / "preset_thumb_src" / "20261118"
TEMPLATE_PATH = ROOT / "tools" / "presets_data" / "preset_thumb_templates.json"
KIND_ORDER = ("event", "outfit", "expression", "link", "scene")

if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))


def load_templates() -> dict:
    return json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))


def completed_keys(out_dir: Path) -> set[str]:
    return {p.stem for p in out_dir.glob("*.png") if p.is_file()}


@dataclass
class _Preset:
    id: str
    kind: str
    head: str
    tags: list[str]
    seed: str
    rank: int
    ratings: dict


def _group_presets(data_dir: Path) -> dict[str, list[_Preset]]:
    # The generation client has its own core package. Only the builder needs this one.
    from core.preset_thumb_key import head_for, preset_thumb_key

    groups = defaultdict(list)
    for family in ("outfit", "event", "expression", "scene"):
        pack = json.loads((data_dir / f"{family}_presets.json").read_text(encoding="utf-8"))
        for row in pack["sets"]:
            kind = "outfit" if family == "outfit" else row["family"]
            head = head_for(kind, row["pool"])
            key = preset_thumb_key(kind, head, row["tags"])
            groups[key].append(_Preset(row["id"], kind, head, row["tags"], row["seed"],
                                       min(row["rank"].values()), row.get("support_by_rating", {})))
    return groups


def _top_rating(presets: list[_Preset]) -> str:
    """Most common rating over every set behind the key. A tie goes to the more explicit rating."""
    total = Counter()
    for preset in presets:
        total.update(preset.ratings)
    if not total:
        return ""
    return max("gsqe", key=lambda r: (total[r], "gsqe".index(r)))


def _post_counts(tags: set[str], source: Path) -> dict[str, int]:
    import pandas as pd

    # 팩에는 같은 태그가 두 표기로 있다('^_^' 와 '^ ^' · '>_<' 와 '> <') - 둘 다 같은 Danbooru 이름을 본다.
    wanted = defaultdict(list)
    for tag in tags:
        wanted[tag.replace(" ", "_")].append(tag)
    frame = pd.read_parquet(source, columns=["name", "post_count"])
    frame = frame[frame["name"].isin(wanted)]
    counts: dict[str, int] = {}
    for name, posts in zip(frame["name"], frame["post_count"]):
        for tag in wanted[name]:
            counts[tag] = max(counts.get(tag, 0), int(posts))
    return counts


def _weighted(tags: list[str], counts: dict[str, int], rule: dict) -> list[str]:
    # 흔한 태그는 낮추고 드문 태그는 올린다(사용자 11-18) - 0.7::common ::, 1.3::rare ::
    common = [t for t in tags if counts.get(t, 0) >= rule["common_min_posts"]]
    rare = [t for t in tags if counts.get(t, 0) < rule["common_min_posts"]]
    return [f"{weight}::{', '.join(group)} ::"
            for weight, group in ((rule["common_weight"], common), (rule["rare_weight"], rare)) if group]


def _render(template: dict, preset: _Preset, counts: dict[str, int],
            explicit: bool = False) -> tuple[list[str], list[str], str]:
    head = preset.head
    if explicit:
        rule = template["explicit"]
        head = ", ".join(part for part in (head, rule["prefix"], rule["adult_cue"][head]) if part)
    fields = {**template["fragments"], "{head}": head}
    parts = [fields.get(token, token) for token in template["templates"][preset.kind].split(", ")]
    # Strip weight delimiters for comparison only. The original fragment bytes go in the prompt.
    fixed = {
        tag.strip().removesuffix("::").rsplit("::", 1)[-1].strip()
        for part in parts if part != "{tags}"
        for tag in part.split(",")
    }
    kept = [tag for tag in preset.tags if tag not in fixed]
    dropped = [tag for tag in preset.tags if tag in fixed]
    slot = parts.index("{tags}")
    parts[slot:slot + 1] = _weighted(kept, counts, template["weighting"])
    return kept, dropped, ", ".join(parts)


def build_targets(out_dir: Path = DEFAULT_OUT_DIR, *, data_dir: Path = ROOT / "data",
                  post_counts: dict[str, int] | None = None) -> dict:
    """post_counts: tag -> Danbooru posts. None reads the snapshot named in the templates."""
    template = load_templates()
    done = completed_keys(out_dir)
    groups = _group_presets(data_dir)
    if post_counts is None:
        every_tag = {tag for presets in groups.values() for preset in presets for tag in preset.tags}
        post_counts = _post_counts(every_tag, ROOT / template["weighting"]["source"])
    targets = []
    for key, presets in groups.items():
        best = min(presets, key=lambda p: (p.rank, p.id))
        rating = _top_rating(presets)
        tags, dropped, prompt = _render(template, best, post_counts, rating == template["explicit"]["rating"])
        width, height = template["resolutions"][best.kind]
        target = {
            "order": 0,
            "key": key,
            "kind": best.kind,
            "head": best.head,
            "tags": tags,
            "dropped": dropped,
            "prompt": prompt,
            "width": width,
            "height": height,
            "sets": sorted(p.id for p in presets),
            "seed_tag": best.seed,
            "rank": best.rank,
            "rating": rating,
        }
        if key in done:
            target["done"] = True
        targets.append(target)

    targets.sort(key=lambda t: (t["rank"], KIND_ORDER.index(t["kind"]), t["seed_tag"], t["key"]))
    for order, target in enumerate(targets, start=1):
        target["order"] = order
    document = {
        "note": "One thumbnail per key, ordered by rank, kind, seed tag and key.",
        "template_version": template["template_version"],
        "count": len(targets),
        "targets": targets,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = NamedTemporaryFile(mode="w", dir=out_dir, suffix=".tmp", encoding="utf-8",
                             newline="\n", delete=False)
    tmp_path = Path(tmp.name)
    try:
        with tmp:
            json.dump(document, tmp, ensure_ascii=False, indent=1)
            tmp.write("\n")
        tmp_path.replace(out_dir / "_targets.json")
    finally:
        tmp_path.unlink(missing_ok=True)
    counts = Counter(t["kind"] for t in targets)
    explicit = Counter(t["kind"] for t in targets if t["rating"] == template["explicit"]["rating"])
    print(f"count={len(targets)}", *(f"{kind}={counts[kind]}" for kind in KIND_ORDER),
          "explicit:", *(f"{kind}={explicit[kind]}" for kind in KIND_ORDER))
    return document


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    build_targets(parser.parse_args().out_dir)
