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
from tools.korean_translation_policy import exclusion, load_policy


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
    for kind in ("colors", "patterns", "materials", "states", "appearance", "size", "garment_states"):
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
    for subject, ko_subject in rules.get('contact_subjects', {}).items():
        for owner, ko_owner in rules['contact_owners'].items():
            prefix = subject + ' on ' + owner
            if tag.startswith(prefix) and (part := tag[len(prefix):]) in rules['contact_nouns']:
                scope = '자기 ' if not owner and tag in rules.get('contact_self_tags', []) else ko_owner
                yield scope + nouns[part] + '에 ' + ko_subject + '을 댐', f'contact:{subject}+{owner}{part}'
    for state, ko_state in rules.get('limb_states', {}).items():
        prefix = state + ' '
        if tag.startswith(prefix) and (part := tag[len(prefix):]) in groups.get('limbs', []):
            plural = part in ('arms', 'legs', 'hands', 'feet', 'knees', 'fingers', 'ears')
            count = '두 개 이상의 ' if plural else '한쪽 '
            yield ko_state + ' ' + count + nouns[part], f'limb_state:{state}+{part}'


def build(raw, rules, reviewed=None, policy=None):
    policy = policy if policy is not None else load_policy()
    reviewed = reviewed or {}
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
        if tag in covered and tag not in rules["direct"] and tag not in reviewed:
            continue
        reason = exclusion(tag, records[tag], policy)
        if reason:
            excluded.append({"tag": tag, **reason})
            continue
        evidence = reviewed.get(tag)
        extras = []
        if evidence:
            if (evidence.get('status') != 'reviewed_lexical' or not evidence.get('definition') or
                    not evidence.get('source') or not evidence.get('aliases')):
                raise ValueError(f'Unreviewed or evidence-free translation: {tag}')
            extras = [(a, 'definition_translation:' + tag) for a in evidence['aliases']]
        # A sense-reviewed full tag overrides generic composition for that tag;
        # e.g. hand on chest allows one OR both hands, unlike many other hand tags.
        for alias, basis in (extras if evidence else candidates(tag, rules)):
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


def removed_aliases(previous, current):
    return {tag: sorted({a['text'] for a in row['aliases']} -
                        {a['text'] for a in current.get(tag, {}).get('aliases', [])})
            for tag, row in previous.items()
            if {a['text'] for a in row['aliases']} -
               {a['text'] for a in current.get(tag, {}).get('aliases', [])}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules", type=Path, default=ROOT / "tools/korean_alias_rules.json")
    parser.add_argument("--reviewed", type=Path, default=ROOT / "tools/korean_alias_reviewed.json")
    parser.add_argument("--previous", type=Path, default=ROOT / "data/tag_index/korean_alias_supplement.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.report.exists():
        parser.error("Use new output paths; existing evidence/data is never overwritten")
    raw = load_kr_tag_records(include_korean_supplement=False).raw
    rules = json.loads(args.rules.read_text(encoding="utf-8"))
    reviewed = json.loads(args.reviewed.read_text(encoding='utf-8')) if args.reviewed.exists() else {'translations': {}}
    accepted, report = build(raw, rules, reviewed['translations'])
    previous = json.loads(args.previous.read_text(encoding='utf-8'))['translations'] if args.previous.exists() else {}
    removed = removed_aliases(previous, accepted)
    if removed:
        raise ValueError(f'Existing aliases would disappear; resolve new rule collisions before promotion: {removed}')
    report['previous_alias_tags'] = len(previous)
    report['additional_alias_tags'] = len(set(accepted) - set(previous))
    report['additional_aliases'] = sum(len(r['aliases']) for r in accepted.values()) - sum(len(r['aliases']) for r in previous.values())
    report['removed_aliases'] = removed
    payload = {"schema_version": 1, "version": rules["version"],
               "kind": "korean_lexical_alias_supplement",
               "source": {"rules": args.rules.name, "rules_sha256": hashlib.sha256(args.rules.read_bytes()).hexdigest(),
                          "builder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                          "reviewed_sha256": hashlib.sha256(args.reviewed.read_bytes()).hexdigest() if args.reviewed.exists() else None,
                          "policy_sha256": hashlib.sha256(Path(__file__).with_name('korean_translation_policy.json').read_bytes()).hexdigest(),
                          "policy_code_sha256": hashlib.sha256(Path(__file__).with_name('korean_translation_policy.py').read_bytes()).hexdigest(),
                          "corpus_sha256": hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()},
               "semantic_certified": False, "translations": accepted}
    for path, value in ((args.output, payload), (args.report, report)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("remaining", "excluded", "limits")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
