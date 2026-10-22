"""Immutable character records and postings, with a bounded query-result LRU.

IDs are catalog-version-local. Alias binding uses the shared named-entity loader;
one alias can resolve to every matching character, including cross-work homonyms.
"""
from __future__ import annotations
from array import array
from bisect import bisect_left
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
import re
import threading
from sys import intern

from core.named_entity_aliases import apply_named_entity_aliases
from core.tag_knowledge import normalize_tag_key as normalize

INITIALS = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ'


def initials(text):
    return ''.join(INITIALS[(ord(c)-0xAC00)//588] if '가' <= c <= '힣' else c
                   for c in text if not c.isspace())


def prefix_ids(keys, mapping, query):
    start = bisect_left(keys, query)
    for position in range(start, len(keys)):
        key = keys[position]
        if not key.startswith(query):
            break
        yield from mapping[key]


@dataclass(frozen=True, slots=True)
class Record:
    group: str
    name: str
    normalized: str
    group_id: int
    gender: str
    debut: str
    posts: int | None
    search: str
    aliases: str
    key: str
    data: dict


class CharacterSearchIndex:
    def __init__(self, service, source_version):
        self.records = []
        self.names = defaultdict(list)
        self.aliases = defaultdict(list)
        self.initials = defaultdict(list)
        self.features = defaultdict(lambda: array('I'))
        self.works = defaultdict(lambda: array('I'))
        self.groups = defaultdict(lambda: array('I'))
        self.feature_vocab = {}
        self.group_names = list(dict.fromkeys(g for g, _, _ in service._iter_all_chars()))
        group_ids = {g: i for i, g in enumerate(self.group_names)}
        raw = {name: {'_tag': name, '_cat': 'character'} for _, name, _ in service._iter_all_chars()}
        self.alias_stats = apply_named_entity_aliases(raw, service.aliases_path)
        debut = service.debut_index()
        for group, name, data in service._iter_all_chars():
            rid = len(self.records)
            norm = normalize(name)
            self.names[norm].append(rid)
            aliases = {normalize(a) for a in raw[name].get('_named_entity_aliases', [])}
            # Parentheses may be escaped or written as plain word separators.
            paren_words = normalize(norm.replace('(', ' ').replace(')', ' '))
            if paren_words != norm:
                aliases.add(paren_words)
            for alias in tuple(aliases):
                if re.search('[가-힣]', alias):
                    aliases.add(alias.replace(' ', ''))
            # A spaced Korean name also has searchable first/last components:
            # 하츠네 미쿠 -> 미쿠 / ㅁㅋ. This is retrieval evidence only; all
            # homonyms/variants retain their full canonical identity.
            search_aliases = aliases | {part for a in aliases if ' ' in a
                for part in (a.split(' ', 1)[0], a.rsplit(' ', 1)[-1])
                if re.fullmatch('[가-힣]{2,}', part)}
            for alias in search_aliases:
                self.aliases[alias].append(rid)
                if re.search('[가-힣]', alias):
                    self.initials[initials(alias)].append(rid)
            own = set()
            for kind, entries in (('color', data.get('personal_color')), ('feature', data.get('characteristics'))):
                for entry in entries or []:
                    tag = normalize(entry.get('tag') or '') if isinstance(entry, dict) else ''
                    if tag:
                        own.add(tag)
                        self.feature_vocab.setdefault(tag, {'kind': kind, 'count': 0})
            breast = service._top_breast(data)
            if breast:
                own.add(breast)
                self.feature_vocab.setdefault(breast, {'kind': 'breast', 'count': 0})
            for tag in own:
                self.features[tag].append(rid)
                self.feature_vocab[tag]['count'] += 1
            works = {intern(normalize(group)), *(intern(normalize(w)) for w in data.get('parent_works') or [])}
            copyright = str(data.get('copyright') or '').strip()
            if copyright and copyright != service.ORIGINAL_GROUP:
                works.add(intern(normalize(copyright)))
            works.discard('')
            for work in works:
                self.works[work].append(rid)
            tags = normalize(service._tag_search_str(data))
            self.groups[group].append(rid)
            self.records.append(Record(group, name, norm, group_ids[group], service.prompt_head(data),
                debut.get(name, ''), data.get('danbooru_posts'), norm + ', ' + tags,
                '\n'.join(sorted(aliases)), f'{group}::{name}', data))
        del raw
        self.names = {k: tuple(v) for k, v in self.names.items()}
        self.aliases = {k: tuple(v) for k, v in self.aliases.items()}
        self.initials = {k: tuple(set(v)) for k, v in self.initials.items()}
        self.features = dict(self.features)
        self.works = dict(self.works)
        self.groups = dict(self.groups)
        self.name_keys = sorted(self.names)
        self.alias_keys = sorted(self.aliases)
        self.initial_keys = sorted(self.initials)
        self.order = tuple(sorted(range(len(self.records)), key=lambda i: (
            -int(self.records[i].data.get('total_rows', 0) or 0), self.records[i].name.lower())))
        self.thumb_order = self.order
        self.thumb_version = None
        self.results = OrderedDict()
        self.lock = threading.RLock()
        self.source_version = source_version
        table = [[r.group_id, r.name] for r in self.records]
        digest = hashlib.sha256(json.dumps([source_version, self.group_names, table],
            ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()[:24]
        self.catalog = {'version': digest, 'groups': self.group_names, 'table': table}

    def clear_results(self):
        with self.lock:
            self.results.clear()

    def invalidate(self, kind):
        with self.lock:
            # Unfiltered queries do not depend on favorites for membership/order.
            # Page metadata is always serialized from current state.
            if kind == 'favorites':
                for key in list(self.results):
                    if key[5]:
                        del self.results[key]
            else:
                self.results.clear()
            if kind == 'thumbs':
                self.thumb_version = None

    def query_matches(self, query):
        exact = query.startswith('*')
        text = query[1:].strip() if exact else query
        terms, works = [], []
        for term in text.split(','):
            term = term.strip()
            if exact:
                term = term.lstrip('*').strip()
            if term.startswith('work:'):
                if term[5:].strip():
                    works.append('work:' + term[5:].strip())
            elif term:
                terms.append(term)
        ranks = None
        for term in terms:
            found = {}
            def add(ids, rank):
                for rid in ids:
                    found.setdefault(rid, rank)
            add(self.names.get(term, ()), 0)
            if not exact:
                add(prefix_ids(self.name_keys, self.names, term), 1)
            add(self.aliases.get(term, ()), 2)
            if not exact:
                add(prefix_ids(self.alias_keys, self.aliases, term), 3)
                if all(c in INITIALS for c in term.replace(' ', '')):
                    add(prefix_ids(self.initial_keys, self.initials, term.replace(' ', '')), 4)
            pattern = re.compile(r'\b' + re.escape(term) + r'\b') if exact else None
            for rid, record in enumerate(self.records):
                if rid in found:
                    continue
                if (pattern.search(record.normalized) if exact else term in record.normalized or term in record.aliases):
                    found[rid] = 5
                elif not exact and term in record.search:
                    found[rid] = 6
            add(self.features.get(term, ()), 6)
            ranks = found if ranks is None else {rid: max(rank, found[rid]) for rid, rank in ranks.items() if rid in found}
            if not ranks:
                break
        return ranks, works

    def select(self, service, group, query, thumb_first, recent, favorite, include, exclude, include_hidden, genders):
        query = normalize(query)
        include = tuple(sorted({normalize(x) for x in include or [] if normalize(x)}))
        exclude = tuple(sorted({normalize(x) for x in exclude or [] if normalize(x)}))
        wanted = tuple(sorted({normalize(g) for g in genders or []} & {'girl', 'boy', 'other'}))
        v = service._search_versions
        versions = (self.catalog['version'], v['favorites'] if favorite else None,
                    v['hidden'] if not include_hidden else None, v['thumbs'], v['pack'])
        key = (group, query, bool(thumb_first), bool(recent), bool(include_hidden), bool(favorite), include, exclude, wanted, versions)
        with self.lock:
            cached = self.results.get(key)
            if cached is not None:
                self.results.move_to_end(key)
                return cached, wanted
        ranks, query_works = self.query_matches(query)
        candidates = set(ranks) if ranks is not None else set(range(len(self.records)))
        if group != service.GROUP_ALL:
            candidates.intersection_update(self.groups.get(group, ()))
        def filter_values(values, excluding=False):
            work_ids = set()
            has_work = False
            for value in values:
                if value.startswith('work:'):
                    work = value[5:].strip()
                    if work:
                        has_work = True
                        work_ids.update(self.works.get(work, ()))
                elif excluding:
                    candidates.difference_update(self.features.get(value, ()))
                else:
                    candidates.intersection_update(self.features.get(value, ()))
            if has_work:
                if excluding:
                    candidates.difference_update(work_ids)
                else:
                    candidates.intersection_update(work_ids)
        filter_values((*include, *query_works))
        filter_values(exclude, True)
        hidden = set() if include_hidden else service.hidden()
        favorites = service.favorites()
        since = service.recent_since()
        if hidden or recent or favorite:
            candidates = {i for i in candidates if self.records[i].key not in hidden
                and (not recent or bool(self.records[i].debut) and self.records[i].debut >= since)
                and (not favorite or self.records[i].key in favorites)}
        counts = Counter(self.records[i].gender for i in candidates)
        gender_counts = {g: counts[g] for g in ('girl', 'boy', 'other')}
        if wanted:
            candidates = {i for i in candidates if self.records[i].gender in wanted}
        scope = []
        if group == service.GROUP_ALL:
            works = Counter(self.records[i].group for i in candidates)
            scope = [{'key': k, 'count': c} for k, c in sorted(works.items(), key=lambda kv: (-kv[1], kv[0]))[:service.SCOPE_CHIP_LIMIT]]
        with self.lock:
            if thumb_first and self.thumb_version != v['thumbs']:
                thumbs = service.thumb_index()
                self.thumb_order = tuple(i for i in self.order if self.records[i].key in thumbs) + tuple(i for i in self.order if self.records[i].key not in thumbs)
                self.thumb_version = v['thumbs']
            order = self.thumb_order if thumb_first else self.order
            ids = [i for i in order if i in candidates]
            if ranks:
                # Stable bucket sort keeps the precomputed legacy order within a tier.
                buckets = [[] for _ in range(7)]
                for i in ids:
                    buckets[ranks[i]].append(i)
                ids = [i for bucket in buckets for i in bucket]
            result = (array('H' if len(self.records) <= 65536 else 'I', ids), gender_counts, scope)
            self.results[key] = result
            self.results.move_to_end(key)
            while len(self.results) > 64:
                self.results.popitem(last=False)
        return result, wanted

    def build_list(self, service, group_key, query, page, per_page, thumb_first, include_all,
                   recent_only, favorites_only, include, exclude, include_hidden, genders,
                   compact=False, offset=None, limit=None):
        (ids, counts, scope), wanted = self.select(service, group_key, query, thumb_first,
            recent_only, favorites_only, include, exclude, include_hidden, genders)
        total = len(ids)
        per_page = max(9, min(96, int(per_page or 48)))
        total_pages = max(1, math.ceil(total / per_page))
        page = min(max(0, int(page or 0)), total_pages - 1)
        start = page * per_page if offset is None else max(0, int(offset))
        size = per_page if limit is None else max(0, min(1000, int(limit)))
        thumbs = service.thumb_index()
        def item(position, rid, page_item=False):
            r = self.records[rid]
            return service._serialize_list_item(position, r.group, r.name, r.data, thumbs,
                include_thumbnail_url=page_item, thumbnail_size='grid' if page_item else '')
        result = {'group': group_key, 'query': query, 'page': page, 'per_page': per_page,
            'total': total, 'total_pages': total_pages, 'thumb_first': bool(thumb_first),
            'recent_only': bool(recent_only), 'recent_since': service.recent_since(),
            'favorites_only': bool(favorites_only), 'favorite_count': len(service.favorites()),
            'genders': list(wanted), 'gender_counts': dict(counts), 'scope': [dict(x) for x in scope],
            'items': [item(pos, rid, True) for pos, rid in enumerate(ids[start:start+size], start)]}
        if compact:
            result.update(ids=list(ids), catalog_version=self.catalog['version'],
                          catalog_url='/api/character-viewer/catalog')
        else:
            result['all_items'] = [item(pos, rid) for pos, rid in enumerate(ids)] if include_all else None
        if offset is not None or limit is not None:
            result.update(offset=start, limit=size)
        return result
