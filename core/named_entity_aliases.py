"""Typed, offline character/copyright name bindings; never general concepts.

Names are retrieval evidence, not proof of a scene's meaning. Ambiguous aliases
keep every candidate. Do not truncate names or infer identity from descriptions.
"""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import re

from core.tag_knowledge import normalize_tag_key

KINDS = frozenset({'character', 'copyright'})


def apply_named_entity_aliases(raw, path: Path):
    stats = {'records': 0, 'aliases': 0, 'missing': 0, 'conflicts': 0, 'errors': []}
    if not path.is_file():
        return stats
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('schema_version') != 1 or data.get('kind') != 'named_entity_aliases':
            raise ValueError('Unsupported named entity alias schema')
        records = data['entities']
        # Validate before mutating shared records.
        for tag, item in records.items():
            if (tag != normalize_tag_key(tag) or item['category'] not in KINDS
                    or not isinstance(item['aliases'], list) or not 1 <= len(item['aliases']) <= 16
                    or any(not isinstance(a, str) or not a.strip() or len(a) > 120
                           or any(c in a for c in ',<>\n\r') for a in item['aliases'])):
                raise ValueError(f'Invalid name binding: {tag}')
        by_tag = defaultdict(list)
        for key, info in raw.items():
            by_tag[normalize_tag_key(info.get('_tag') or key)].append(info)
        for tag, item in records.items():
            matches = by_tag.get(tag, [])
            if not matches:
                stats['missing'] += 1
                continue
            if any(info.get('_cat') and info['_cat'] != item['category'] for info in matches):
                stats['conflicts'] += 1
                continue
            for info in matches:
                # Keep legacy general-search classification unchanged. This
                # asset owns name bindings, not a global tag reclassification.
                info['_named_entity_category'] = item['category']
                info['_named_entity_aliases'] = list(item['aliases'])
                info['_named_entity_source'] = data.get('source', {}).get('file', '')
                existing = str(info.get('keywords_kr') or '')
                terms = {normalize_tag_key(a) for a in existing.split(',')}
                added = [a for a in item['aliases'] if normalize_tag_key(a) not in terms]
                info['keywords_kr'] = ', '.join(filter(None, [existing, *added]))
                info['_kw_lower'] = info['keywords_kr'].lower()
            stats['records'] += 1
            stats['aliases'] += len(item['aliases'])
    except (ValueError, TypeError, KeyError, OSError) as exc:
        stats['errors'].append(str(exc))
    return stats


class NamedEntityIndex:
    """Identity-local index. Exact full aliases win; no popularity disambiguation."""

    def __init__(self, raw):
        self.built_from = raw
        self.records = {}
        self.exact = defaultdict(set)
        self.compact = defaultdict(set)
        for key, info in raw.items():
            category = info.get('_named_entity_category') or info.get('_cat')
            if category not in KINDS:
                continue
            tag = normalize_tag_key(info.get('_tag') or key)
            try:
                count = int(info.get('freq', info.get('count', 0)) or 0)
            except (ValueError, TypeError):
                count = 0
            if count <= 0:
                continue
            previous = self.records.get(tag)
            names = set(info.get('_named_entity_aliases', [])) | {tag}
            if previous:
                names.update(previous['names'])
            self.records[tag] = {'tag': tag, 'cat': category, 'count': max(count, (previous or {}).get('count', 0)),
                'desc': str(info.get('description') or info.get('desc') or ''),
                'group': str(info.get('group') or ''), 'names': sorted(names)}
        for tag, row in self.records.items():
            for name in row['names']:
                normalized = normalize_tag_key(name)
                self.exact[normalized].add(tag)
                if re.search('[가-힣]', normalized):
                    self.compact[normalized.replace(' ', '')].add(tag)

    def search(self, query, *, categories=KINDS, limit=12, prefix=False):
        q = normalize_tag_key(query)
        if not q or limit <= 0:
            return []
        ids = set(self.exact.get(q, ()))
        kind = 'entity_name_exact'
        if not ids and re.search('[가-힣]', q):
            ids = set(self.compact.get(q.replace(' ', ''), ()))
            kind = 'entity_name_spacing'
        if not ids and prefix and len(q) >= 2:
            ids = {tag for name, tags in self.exact.items() if name.startswith(q) for tag in tags}
            kind = 'entity_name_prefix'
        rows = [self.records[t] for t in ids if self.records[t]['cat'] in categories]
        rows.sort(key=lambda r: (r['tag'] != q, -r['count'], r['tag']))
        return [{**r, 'match_kind': kind, 'matched_query': q, 'entity_candidate_count': len(rows),
                 'ambiguous': len(rows) > 1} for r in rows[:limit]]


def ensure_named_entity_index(context):
    from app.backend.server.autocomplete_commands import _ensure_kr_raw

    raw = getattr(context, 'kr_tags_raw', None)
    if not isinstance(raw, dict) or not raw:
        # Catalog-only/injected tool contexts have no disk-backed corpus owner.
        # Name enrichment must not break their existing search fallback.
        raw = _ensure_kr_raw(context) if getattr(context, 'repo_root', None) is not None else (raw or {})
    cached = getattr(context, 'named_entity_index', None)
    if cached is None or cached.built_from is not raw:
        cached = NamedEntityIndex(raw)
        context.named_entity_index = cached
    return cached


def is_named_entity_result(row, query):
    """Check complete name evidence, not substrings or dropped qualifiers."""
    q = normalize_tag_key(query)
    if (row.get('cat') not in KINDS or row.get('match_kind') not in
            {'entity_name_exact', 'entity_name_spacing'}
            or normalize_tag_key(row.get('matched_query', '')) != q):
        return False
    names = {normalize_tag_key(n) for n in row.get('names', [])}
    if row['match_kind'] == 'entity_name_exact':
        return q in names
    return bool(re.search('[가-힣]', q)) and q.replace(' ', '') in {n.replace(' ', '') for n in names}
