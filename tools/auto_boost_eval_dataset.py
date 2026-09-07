"""Deterministic, screened samples of NAIA archive rows. Never rewrite sources.

Screening is metadata based, not an age/consent certification. Q/E rows are
retained for capture and contract analysis, not explicit prose generation.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import re
import unicodedata

POLICY_VERSION = "boost-eval-screen-v1"
RATINGS = "gsqe"


def normalize(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(text or "")).casefold().replace("_", " ")).strip()


EXCLUSIONS = {
    "minor_or_age_ambiguous": r"\b(loli(?:con|fication)?|shota(?:con)?|underage|minor|child(?:ren|hood)?|childlike|kid|baby|infant|toddler|preteen|teen(?:age|ager)?|adolescent|young (?:girl|boy)|little (?:girl|boy)|aged? (?:up|down)|age regression|kindergarten|elementary school|middle school|high school|school uniform|schoolgirl|schoolboy)\b|로리|쇼타|미성년|아동",
    "nonconsent_or_incapacity": r"\b(rape|raped|raping|rapist|molest(?:ation|ing)?|non ?consensual|noncon|forced|coercion|sexual assault|unconscious|sleeping|asleep|drugged|drunk|mind control|hypnosis)\b|강간|비동의",
    "graphic_violence": r"\b(guro|gore|gory|dismember(?:ment|ed)?|mutilation|decapitation|amputation|disembowelment|snuff|torture|blood|bloody|corpse|necrophilia)\b|고어|절단",
    "other_excluded": r"\b(bestiality|zoophilia|feral|incest)\b",
}
EXCLUSION_PATTERNS = {key: re.compile(value) for key, value in EXCLUSIONS.items()}
ADULT_CUES = {"adult", "adult female", "adult male", "mature female", "mature male", "milf", "dilf"}
# Deliberately conservative live-generation lane; source rating alone is insufficient.
EXPLICIT_OR_SUGGESTIVE = re.compile(
    r"\b(nude|naked|nudity|topless|bottomless|sex|sexual|intercourse|penetration|fuck\w*|"
    r"masturbat\w*|orgasm\w*|ejaculat\w*|cum|semen|penis|vagina|vulva|genitals?|anus|anal|"
    r"nipples?|areolae?|breasts?|cleavage|underboob|sideboob|cameltoe|pubic|erection|"
    r"fellatio|cunnilingus|oral|paizuri|futanari|bondage|bdsm|fetish|tentacles?|"
    r"panties|underwear|lingerie|bra|pantyhose|bikini|swimsuit|upskirt|spread legs|"
    r"ass|buttocks|butt|buttcrack|presenting|aroused|wet dream|saliva|drool|licking)\b"
)


def digest(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def tag_set(row):
    return {normalize(tag) for tag in str(row.get("general") or "").split(",") if normalize(tag)}


def screen_row(row):
    # Every string column is checked before a row can be persisted to the sample.
    text = " | ".join(normalize(v) for v in row.values() if isinstance(v, str))
    reasons = [key for key, pattern in EXCLUSION_PATTERNS.items() if pattern.search(text)]
    rating = normalize(row.get("rating"))
    if rating not in RATINGS or len(rating) != 1:
        reasons.append("unknown_rating")
    if not tag_set(row):
        reasons.append("empty_general")
    if rating in {"q", "e"}:
        if not tag_set(row).intersection(ADULT_CUES):
            reasons.append("no_explicit_adult_metadata")
        if str(row.get("character") or "").strip():
            reasons.append("named_character_age_unverified")
    return reasons


def live_candidate(row):
    return (not screen_row(row) and normalize(row.get("rating")) in {"g", "s"}
            and not str(row.get("character") or "").strip()
            and not EXPLICIT_OR_SUGGESTIVE.search(normalize(row.get("general"))))


def prepare_dataset(source_dir, output, *, per_rating=6, shards=4, seed=20260907,
                    min_tags=8, max_tags=60, review_per_rating=4):
    import pyarrow as pa
    import pyarrow.parquet as pq

    if per_rating < 1 or shards < 1 or min_tags < 1 or max_tags < min_tags or review_per_rating < 0:
        raise ValueError("Invalid sampling bounds")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    files = sorted(Path(source_dir).resolve().glob("tags_*.parquet"))
    if not files:
        raise ValueError("No tags_*.parquet sources found")
    rng = random.Random(seed)
    selected = sorted(rng.sample(files, min(shards, len(files))))
    pools = {r: [] for r in RATINGS}
    review_pools = {r: [] for r in "gs"}
    review_seen = Counter()
    review_rng = random.Random(seed ^ 0xA5A5)
    seen = Counter()
    exclusions = Counter()
    scanned = Counter()
    source_info = []
    for file in selected:
        pf = pq.ParquetFile(file)
        required = {"id", "general", "rating", "character", "copyright", "meta"}
        if not required.issubset(pf.schema_arrow.names):
            raise ValueError(f"Source schema missing fields: {file.name}")
        source_info.append({"path": str(file), "sha256": file_digest(file), "rows": pf.metadata.num_rows})
        offset = 0
        for batch in pf.iter_batches(batch_size=4096):
            for row in batch.to_pylist():
                row_offset = offset
                offset += 1
                rating = normalize(row.get("rating"))
                scanned[rating] += 1
                reasons = screen_row(row)
                if reasons:
                    exclusions.update(reasons)
                    continue
                tags = tag_set(row)
                if not min_tags <= len(tags) <= max_tags:
                    exclusions["tag_count_outside_sample_bounds"] += 1
                    continue
                seen[rating] += 1
                sample = dict(row)
                sample.update(case_id=digest(f"{file.name}:{row_offset}:{row['id']}")[:16],
                              source_file=file.name, source_row_index=row_offset,
                              source_general_sha256=digest(row["general"]),
                              screening_policy=POLICY_VERSION,
                              live_candidate=live_candidate(row))
                if sample["live_candidate"] and review_per_rating:
                    review_seen[rating] += 1
                    review_pool = review_pools[rating]
                    if len(review_pool) < review_per_rating:
                        review_pool.append(sample)
                    else:
                        slot = review_rng.randrange(review_seen[rating])
                        if slot < review_per_rating:
                            review_pool[slot] = sample
                pool = pools[rating]
                if len(pool) < per_rating:
                    pool.append(sample)
                else:
                    slot = rng.randrange(seen[rating])
                    if slot < per_rating:
                        pool[slot] = sample
    sampled = {row["case_id"]: dict(row, sample_cohort="stratified") for rating in RATINGS for row in pools[rating]}
    for pool in review_pools.values():
        for row in pool:
            key = row["case_id"]
            if key in sampled:
                sampled[key]["sample_cohort"] += ",nonexplicit_review"
            else:
                sampled[key] = dict(row, sample_cohort="nonexplicit_review")
    samples = sorted(sampled.values(), key=lambda x: (RATINGS.index(x["rating"]), x["case_id"]))
    if not samples:
        raise ValueError("No eligible rows; do not relax exclusions silently")
    assert all(not screen_row(row) for row in samples)
    dataset = output / "screened.parquet"
    pq.write_table(pa.Table.from_pylist(samples), dataset, compression="zstd")
    summary = {
        "schema_version": 1, "policy": POLICY_VERSION, "seed": seed, "sources": source_info,
        "source_file_count_available": len(files), "scanned_by_rating": dict(scanned),
        "eligible_by_rating": dict(seen), "exclusion_counts_nonexclusive": dict(exclusions),
        "sampled_by_rating": {r: len(pools[r]) for r in RATINGS},
        "nonexplicit_review_pool_by_rating": dict(review_seen),
        "additional_review_cohort": {r: len(review_pools[r]) for r in "gs"},
        "unique_sample_count": len(samples),
        "requested_per_rating": per_rating, "min_tags": min_tags, "max_tags": max_tags,
        "dataset_sha256": file_digest(dataset), "exclusion_patterns": EXCLUSIONS,
        "limits": ["Stratified sample of seeded shards, not complete archive coverage or current user's pool.",
                   "Metadata screening does not certify age, consent or image contents; Q/E require adult metadata and no named character.",
                   "Source rows are excluded whole, never cleaned by deleting disallowed tags.",
                   "Q/E are capture/contract-only; live candidates still require individual review."],
    }
    (output / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
