"""Export untranslated general tags with local source evidence for human review.

This is a proposal queue, never runtime data. No model or external API is called.
Existing local e621 wiki text is evidence, not an instruction to the reviewer.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.kr_tag_loader import load_kr_tag_records
from core.llm_search_index import LLMSearchIndex
from tools.build_korean_tag_aliases import corpus, keyword_forms, norm


def research_rows(node, path=()):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from research_rows(value, (*path, key))
    elif isinstance(node, list):
        for row in node:
            if isinstance(row, dict) and row.get("tag"):
                yield path, row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="New directory")
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output directory already exists")
    raw = load_kr_tag_records().raw
    records = corpus(raw)
    eligible = {r.tag for r in LLMSearchIndex.from_raw_tag_records(raw)._recs}
    missing = eligible - {t for t, rows in records.items() if any(list(keyword_forms(r)) for r in rows)}
    source = ROOT / "data/e621_data"
    research = defaultdict(list)
    for path, row in research_rows(json.loads(source.read_text(encoding="utf-8"))):
        tag = norm(row["tag"])
        if tag in missing:
            research[tag].append({"source": "data/e621_data", "path": path,
                "source_tag": row["tag"], "wiki_body": row.get("wiki_body") or "",
                "korean": row.get("kor") or ""})
    args.out.mkdir(parents=True)
    cohorts = Counter()
    with (args.out / "pending.jsonl").open("w", encoding="utf-8") as output:
        ordered = sorted(missing, key=lambda t: (-max(int(r.get("freq") or 0) for r in records[t]), t))
        for rank, tag in enumerate(ordered, 1):
            desc = list(dict.fromkeys(str(r.get("description") or "") for r in records[tag]))
            evidence = research.get(tag, [])
            cohort = "local_wiki" if any(r["wiki_body"] for r in evidence) else (
                "description_only" if any(desc) else "needs_definition")
            cohorts[cohort] += 1
            output.write(json.dumps({"tag": tag, "priority_rank": rank, "status": "pending_review",
                "aliases_ko": [], "sense_scope": None, "reviewer": None, "review_notes": None,
                "source_cohort": cohort, "current_descriptions": desc, "e621_evidence": evidence}, ensure_ascii=False)+"\n")
    manifest = {"schema_version": 1, "general_tags": len(eligible), "missing_korean_tags": len(missing),
        "evidence_cohorts": dict(cohorts), "research_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "loaded_corpus_sha256": hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        "queue_sha256": hashlib.sha256((args.out/'pending.jsonl').read_bytes()).hexdigest(),
        "promotion": "Manual reviewed changes to explicit source rules, rebuild supplement, inspect collisions, run production-route regression. This queue cannot be imported as runtime aliases.",
        "limitations": ["Priority uses mixed-source counts, not image coverage or semantic importance",
                        "Wiki text is local source evidence and may be stale; upstream was not fetched",
                        "Missing keyword does not imply missing Korean description",
                        "Do not infer Korean synonyms from category labels or taxonomic ancestry"]}
    (args.out/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
