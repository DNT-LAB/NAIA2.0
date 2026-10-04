"""Create-only, offline 832x1216 subset sensitivity of the 4054-image analysis."""
from __future__ import annotations

import argparse
import hashlib
from collections import Counter
from pathlib import Path

import research_tone_tuner_20261004 as r


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=r.ROOT / "docs/tone_tuner_2026_10_04")
    args = parser.parse_args()
    out = args.out.resolve()
    allowed = (r.ROOT / "docs/tone_tuner_2026_10_04").resolve()
    if out != allowed and allowed not in out.parents:
        raise ValueError("output must stay under docs/tone_tuner_2026_10_04")
    paths = [out / "size_sensitivity_effects.csv", out / "size_sensitivity_summary.json"]
    if any(p.exists() for p in paths):
        raise FileExistsError("create-only: choose a fresh --out directory")
    prompts, measurements = r.load_pairs()
    counts, snap, aliases = r.lexicon()
    items, _, _ = r.base_catalog(counts, snap, aliases)
    keep = [i for i, p in enumerate(prompts) if (p["width"], p["height"]) == (832, 1216)]
    rows, _, summary = r.observe(items, [prompts[i] for i in keep], [measurements[i] for i in keep], aliases)
    numeric_artist_tail = sum(bool(__import__("re").search(r"artist:[^,]*\d\s*::", p["prompt"])) for p in prompts)
    summary.update(
        scope="size_sensitivity_4025_of_4054_not_a_new_measurement_or_intervention",
        full_sample_dimensions={f"{w}x{h}": n for (w, h), n in Counter((p["width"], p["height"]) for p in prompts).items()},
        numeric_artist_tail_close_records=numeric_artist_tail,
        source_sha256={rel: hashlib.sha256((r.ROOT / rel).read_bytes()).hexdigest() for rel in [r.PROMPTS, r.MEASUREMENTS]},
    )
    out.mkdir(parents=True, exist_ok=True)
    r.write_csv(paths[0], rows)
    r.write_json(paths[1], summary)
    print(f"full={len(prompts)}, standard_size={len(keep)}, excluded_other_size={len(prompts)-len(keep)}, numeric_artist_tails={numeric_artist_tail}")
    print("CREATED", *[str(p.relative_to(r.ROOT)) for p in paths], sep="\n")


if __name__ == "__main__":
    main()
