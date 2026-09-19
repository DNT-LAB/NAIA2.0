"""Build a bounded Korean keyword supplement from a classified Danbooru CSV.

The CSV is an offline build input only. Runtime loads the generated JSON
supplement, never the source CSV or the full descriptions. Only the explicit
``키워드:`` tail is considered; free-form description text is not tokenized.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.kr_tag_loader import load_kr_tag_records
from core.tag_knowledge import has_hangul, normalize_tag_key


KEYWORD_MARKER = "키워드:"
MAX_KEYWORD_COMPACT_LENGTH = 32
MAX_ALIASES_PER_TAG = 12

# General/meta are the useful Event Map vocabulary. Named-entity categories
# are admitted only at a higher frequency so a full classification dump does
# not become the autocomplete dictionary.
CATEGORY_MIN_POST_COUNT = {
    0: 500,     # general
    1: 2_000,   # artist
    3: 1_000,   # copyright
    4: 1_000,   # character
    5: 100,     # meta
}

# These words are description boilerplate rather than useful tag aliases.
# Exact matching keeps meaningful compounds such as "단색 배경".
LOW_INFORMATION_TERMS = frozenset({
    "관련",
    "그림",
    "기타",
    "이미지",
    "작품",
    "설명",
    "캐릭터",
    "태그",
})
_HANGUL_OR_JAMO_RE = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")


@dataclass(frozen=True)
class SourceKeyword:
    tag: str
    category: int
    post_count: int
    text: str


def _int(value: Any) -> int:
    try:
        return int(str(value or "").strip() or 0)
    except (TypeError, ValueError):
        return 0


def _keyword_texts(description: str) -> list[str]:
    if KEYWORD_MARKER not in description:
        return []
    # The source occasionally has explanatory text containing punctuation;
    # only the final explicit keyword section is a lexical source.
    tail = description.rsplit(KEYWORD_MARKER, 1)[1]
    found: list[str] = []
    for raw in tail.split(","):
        text = normalize_tag_key(raw.strip().strip("<>"))
        compact = text.replace(" ", "")
        if not text or not _HANGUL_OR_JAMO_RE.search(text):
            continue
        if len(compact) < 2 or len(compact) > MAX_KEYWORD_COMPACT_LENGTH:
            continue
        if text in LOW_INFORMATION_TERMS:
            continue
        if any(char in text for char in "<>\n\r,"):
            continue
        found.append(text)
    return list(dict.fromkeys(found))


def read_source(path: str | Path) -> tuple[list[SourceKeyword], dict[str, int]]:
    """Read CSV rows, tolerating legacy unquoted commas in descriptions."""
    rows: list[SourceKeyword] = []
    stats = Counter(source_rows=0, malformed_rows=0, keyword_rows=0)
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
        if header[:3] != ["name", "category", "post_count"]:
            raise ValueError("classified CSV must start with name,category,post_count")
        for raw in reader:
            stats["source_rows"] += 1
            if len(raw) < 4:
                stats["malformed_rows"] += 1
                continue
            tag = normalize_tag_key(raw[0])
            category = _int(raw[1])
            post_count = _int(raw[2])
            description = ",".join(raw[3:])
            texts = _keyword_texts(description)
            if texts:
                stats["keyword_rows"] += 1
            rows.extend(
                SourceKeyword(tag, category, post_count, text)
                for text in texts
            )
    stats["keyword_terms"] = len(rows)
    return rows, dict(stats)


def _active_records(raw: Mapping[str, Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    active: dict[str, Mapping[str, Any]] = {}
    for key, record in raw.items():
        tag = normalize_tag_key(record.get("_tag") or key)
        if tag:
            active.setdefault(tag, record)
    return active


def _existing_owners(raw: Mapping[str, Mapping[str, Any]]) -> dict[str, set[str]]:
    owners: dict[str, set[str]] = defaultdict(set)
    for key, record in raw.items():
        tag = normalize_tag_key(record.get("_tag") or key)
        for field_name in ("keywords_kr", "keywords"):
            for part in str(record.get(field_name) or "").split(","):
                text = normalize_tag_key(part.strip().strip("<>"))
                if has_hangul(text):
                    owners[text.replace(" ", "")].add(tag)
    return owners


def build(
    raw: Mapping[str, Mapping[str, Any]],
    source_keywords: Iterable[SourceKeyword],
) -> tuple[dict[str, dict[str, list[dict[str, Any]]]], dict[str, Any]]:
    """Select one representative canonical tag for each useful source term."""
    source_keywords = list(source_keywords)
    active = _active_records(raw)
    existing = _existing_owners(raw)
    canonical = set(active)
    candidates: dict[str, list[SourceKeyword]] = defaultdict(list)
    skipped = Counter()

    for item in source_keywords:
        if item.tag not in active:
            skipped["tag_not_in_active_corpus"] += 1
            continue
        minimum = CATEGORY_MIN_POST_COUNT.get(item.category)
        if minimum is None:
            skipped["category_not_selected"] += 1
            continue
        if item.post_count < minimum:
            skipped["below_category_threshold"] += 1
            continue
        compact = item.text.replace(" ", "")
        if compact in existing:
            skipped["already_covered"] += 1
            continue
        if item.text in canonical and item.text != item.tag:
            skipped["canonical_name_collision"] += 1
            continue
        candidates[compact].append(item)

    # One source keyword may describe an entire franchise. Resolving it to the
    # most-used canonical tag gives Event Map a deterministic useful pin and
    # prevents hundreds of near-duplicate autocomplete rows.
    chosen: dict[str, SourceKeyword] = {}
    for compact, values in candidates.items():
        chosen[compact] = min(values, key=lambda item: (-item.post_count, item.category, item.tag))

    by_tag: dict[str, list[SourceKeyword]] = defaultdict(list)
    for item in chosen.values():
        by_tag[item.tag].append(item)

    capped: dict[str, list[SourceKeyword]] = {}
    for tag, values in by_tag.items():
        values.sort(key=lambda item: (-item.post_count, len(item.text), item.text))
        if len(values) > MAX_ALIASES_PER_TAG:
            skipped["per_tag_alias_cap"] += len(values) - MAX_ALIASES_PER_TAG
        capped[tag] = values[:MAX_ALIASES_PER_TAG]

    translations: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for tag in sorted(capped):
        translations[tag] = {
            "aliases": [
                {
                    "text": item.text,
                    "basis": [
                        "danbooru_tags_classified.csv:keyword",
                        f"source_category:{item.category}",
                        f"source_post_count:{item.post_count}",
                    ],
                }
                for item in capped[tag]
            ]
        }

    report = {
        "active_tags": len(active),
        "source_keyword_terms": len(source_keywords),
        "candidate_terms": len(candidates),
        "selected_terms": sum(len(items) for items in capped.values()),
        "selected_tags": len(translations),
        "category_min_post_count": {str(k): v for k, v in CATEGORY_MIN_POST_COUNT.items()},
        "max_keyword_compact_length": MAX_KEYWORD_COMPACT_LENGTH,
        "max_aliases_per_tag": MAX_ALIASES_PER_TAG,
        "low_information_terms": sorted(LOW_INFORMATION_TERMS),
        "skipped": dict(sorted(skipped.items())),
    }
    return translations, report


def _default_source() -> Path:
    candidates = (
        Path(r"C:\VNR\DEV\danbooru\_tags\_classified.csv"),
        Path(r"C:\VNR\DEV\danbooru_tags_classified.csv"),
    )
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError("danbooru classified CSV was not found; pass --source explicitly")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Classified Danbooru CSV.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)

    source = (args.source or _default_source()).resolve()
    if args.output.exists() or args.report.exists():
        parser.error("Refusing to overwrite an existing supplement or report")
    source_keywords, source_stats = read_source(source)
    # Keep the reviewed lexical supplement in the active baseline, but avoid
    # feeding this output back into its own selection pass.
    loaded = load_kr_tag_records(include_korean_keyword_supplement=False)
    translations, report = build(loaded.raw, source_keywords)
    report["source"] = {**source_stats, "file": source.name}
    report["source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    report["builder_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    active_names = sorted(
        normalize_tag_key(record.get("_tag") or key)
        for key, record in loaded.raw.items()
    )
    report["active_tag_names_sha256"] = hashlib.sha256(
        "\n".join(active_names).encode("utf-8")
    ).hexdigest()

    payload = {
        "schema_version": 1,
        "version": "2026-09-17-v1",
        "kind": "korean_keyword_supplement",
        "source": {
            "file": source.name,
            "sha256": report["source_sha256"],
            "builder_sha256": report["builder_sha256"],
            "selection_policy": report,
        },
        "semantic_certified": False,
        "translations": translations,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
