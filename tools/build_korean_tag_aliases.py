"""Build additive Korean lexical aliases from bounded, explicit local rules.

No network/model calls. The unresolved queue is part of the output: this tool
does not fabricate a translation for every English word to meet a percentage.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.tag_knowledge import has_hangul, normalize_tag_key as norm
from core.kr_tag_loader import load_kr_tag_records
from core.llm_search_index import LLMSearchIndex


def keyword_forms(record):
    for field in ("keywords_kr", "keywords"):
        for part in str(record.get(field) or "").split(","):
            value = norm(part.replace("<", "").replace(">", ""))
            if has_hangul(value):
                yield value


def compact(value):
    return norm(value).replace(" ", "")


def corpus(raw):
    records = defaultdict(list)
    for key, row in raw.items():
        records[norm(row.get("_tag") or key)].append(row)
    return records


def candidates(tag, rules):
    nouns = rules["nouns"]
    excluded = set(rules["excluded_nouns"])
    groups = rules["groups"]
    for alias in rules["direct"].get(tag, []):
        yield alias, "direct:" + tag
    if tag in nouns and tag not in excluded and tag not in rules.get("excluded_bare_nouns", []):
        yield nouns[tag], "noun:" + tag
    for kind in ("colors", "patterns", "materials", "states", "appearance", "size"):
        for prefix, translations in rules[kind].items():
            if not tag.startswith(prefix + " "):
                continue
            noun = tag[len(prefix) + 1:]
            if noun not in groups[kind] or noun in excluded:
                continue
            for modifier in translations if isinstance(translations, list) else [translations]:
                yield modifier + " " + nouns[noun], f"{kind}:{prefix}+noun:{noun}"
    for animal in groups["animals"]:
        # These are whole canonical tag names, not relation-role inference.
        for suffix, korean in {"humanoid": "형 인간", "ears": " 귀", "tail": " 꼬리",
                               "costume": " 의상", "print": " 그림 무늬", "plushie": " 봉제 인형"}.items():
            if tag == animal + " " + suffix:
                yield nouns[animal] + korean, f"animal:{animal}+suffix:{suffix}"
    if tag.startswith("holding "):
        noun = tag[len("holding "):]
        if noun in groups["objects"] and noun not in excluded:
            yield nouns[noun] + " 들고 있기", "holding+noun:" + noun
    for part in groups["body_parts"]:
        for suffix, korean in rules["body_suffixes"].items():
            if tag == part + " " + suffix:
                yield nouns[part] + " " + korean, f"body:{part}+suffix:{suffix}"
    match = re.fullmatch(r"([2-9]|1[0-9]) (.+)", tag)
    if match and match[2] in groups["counts"]:
        yield match[1] + "개의 " + nouns[match[2]], "count:" + match[1] + "+noun:" + match[2]


_UNUSABLE = re.compile(r"더 이상 사용|사용하지 (?:말|마)|모호한 태그|애매한 태그|태그는 .{0,80}(?:이동|폐기)|deprecated|ambiguous tag", re.I)


def build(raw, rules):
    records = corpus(raw)
    eligible = {row.tag for row in LLMSearchIndex.from_raw_tag_records(raw)._recs}
    covered = {tag for tag, rows in records.items() if any(list(keyword_forms(r)) for r in rows)}
    existing = defaultdict(set)
    for tag, rows in records.items():
        for row in rows:
            for kw in keyword_forms(row):
                existing[compact(kw)].add(tag)
    proposed = defaultdict(dict)
    excluded = []
    for tag in sorted(eligible):
        if tag in covered and tag not in rules["direct"]:
            continue
        if any(_UNUSABLE.search(str(row.get("description") or "")) for row in records[tag]):
            excluded.append({"tag": tag, "reason": "unusable_description"})
            continue
        for alias, basis in candidates(tag, rules):
            if not has_hangul(alias):
                raise ValueError(f"Non-Korean rule for {tag}: {alias}")
            proposed[tag].setdefault(norm(alias), []).append(basis)
    owners = defaultdict(set)
    for tag, aliases in proposed.items():
        for alias in aliases:
            owners[compact(alias)].add(tag)
    accepted = {}
    for tag, aliases in proposed.items():
        rows = []
        previous = {k for r in records[tag] for k in keyword_forms(r)}
        for alias, basis in aliases.items():
            conflicts = (existing[compact(alias)] | owners[compact(alias)]) - {tag}
            if conflicts:
                excluded.append({"tag": tag, "alias": alias, "reason": "target_collision",
                                 "conflicts": sorted(conflicts)})
            elif alias not in previous:
                rows.append({"text": alias, "basis": sorted(set(basis))})
        if rows:
            accepted[tag] = {"aliases": rows}
    newly_covered = set(accepted) - covered
    remaining = sorted(eligible - covered - newly_covered,
                       key=lambda t: (-max(int(r.get("freq") or 0) for r in records[t]), t))
    report = {"general_tags": len(eligible), "before_korean_tags": len(eligible & covered),
              "after_korean_tags": len(eligible & (covered | newly_covered)),
              "new_korean_tags": len(newly_covered), "alias_tags": len(accepted),
              "aliases": sum(len(r["aliases"]) for r in accepted.values()),
              "exclusions": dict(Counter(r["reason"] for r in excluded)),
              "remaining_tags": len(remaining), "remaining": [{"tag": t,
                  "count": max(int(r.get("freq") or 0) for r in records[t]),
                  "sources": sorted({str(r.get("_src", "")) for r in records[t]}),
                  "descriptions": list(dict.fromkeys(str(r.get("description") or "") for r in records[t]))}
                  for t in remaining], "excluded": excluded,
              "limits": ["Coverage counts canonical tags with Korean keywords, not user-query recall",
                         "Rules and resulting lexical candidates are Codex-authored, not independent semantic review",
                         "No unbounded morphology, description-token, category-label or word-by-word fallback",
                         "Existing corpus errors and undeclared ambiguity may remain",
                         "Frequency is a mixed-source prioritization weight, not image coverage"]}
    return accepted, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules", type=Path, default=ROOT / "tools/korean_alias_rules.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.report.exists():
        parser.error("Use new output paths; existing evidence/data is never overwritten")
    raw = load_kr_tag_records(include_korean_supplement=False).raw
    rules = json.loads(args.rules.read_text(encoding="utf-8"))
    accepted, report = build(raw, rules)
    payload = {"schema_version": 1, "version": rules["version"],
               "kind": "korean_lexical_alias_supplement",
               "source": {"rules": args.rules.name, "rules_sha256": hashlib.sha256(args.rules.read_bytes()).hexdigest(),
                          "builder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                          "corpus_sha256": hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()},
               "semantic_certified": False, "translations": accepted}
    for path, value in ((args.output, payload), (args.report, report)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("remaining", "excluded", "limits")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
