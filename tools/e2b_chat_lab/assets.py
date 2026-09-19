"""Read-only reuse of canonical NAIA search code; no WebSessionContext startup."""
from pathlib import Path
from types import SimpleNamespace
import threading
import re
from tools.e2b_chat_lab.retrieval import query_variants, normalize


class Assets:
    def __init__(self, repo_root: Path, user_data: Path | None = None, event_map: Path | None = None, glossary: Path | None = None):
        from core.event_map.service import EventMapService
        root = Path(repo_root)
        data = Path(user_data) if user_data else root / 'NAIA-Portable' / 'user-data'
        if not data.is_dir():
            data = root
        self.context = SimpleNamespace(
            repo_root=root, runtime_paths=SimpleNamespace(data_dir=data / 'data', save_dir=data / 'save'),
            autocomplete_state=SimpleNamespace(kr_tags_loaded=False),
            get_api_mode=lambda: 'NAI', _wildcard_base_dir=lambda: data / 'wildcards',
        )
        roots = [data / 'data', root / 'data']
        self.context.event_map_service = EventMapService(roots, kr_tags_path=root / 'data/KR_tags.parquet')
        if event_map:
            # Only this instance is overridden; never set the production process environment.
            self.context.event_map_service._candidates = lambda: [Path(event_map)]
        self.lock = threading.RLock()
        from tools.e2b_chat_lab.glossary import Glossary
        self.glossary = Glossary(glossary or root.parent / 'NAIA-Event-Map-Handoff-20260911/coverage_expansion_v1/harness/translation_work/general_extension/output/combined_english_descriptions.jsonl')

    def state(self):
        from app.backend.server.autocomplete_commands import ensure_tag_search_index
        with self.lock:
            try:
                index = ensure_tag_search_index(self.context)
                tags = {'ready': bool(index._entries), 'count': len(index._entries), 'owner': 'TagSearchIndex'}
            except Exception as exc:
                tags = {'ready': False, 'error': str(exc)}
            try:
                service = self.context.event_map_service
                idx = service.index()
                event = {'ready': True, 'tags': idx.n_tags, 'path': str(service._path), 'owner': 'EventMapService / quick_search'}
            except Exception as exc:
                event = {'ready': False, 'error': str(exc)}
        return {'tag_index': tags, 'fast_search': {'sources': ['tag', 'artist', 'character', 'wildcard', 'preset', 'event']}, 'event_map': event,
                'english_glossary': self.glossary.state()}

    def call(self, name, args):
        from app.backend.server.autocomplete_commands import ensure_tag_search_index, _autocomplete_row
        from app.backend.server.fast_search_routes import SEARCHERS
        from app.backend.server.event_map_routes import _kr_lookup
        with self.lock:
            if name == 'search_tags':
                index = ensure_tag_search_index(self.context)
                limit = args.get('limit', 6)
                en, ko = query_variants(args['query'], args.get('query_ko', ''), index.entry_for)
                found_rows = {}
                def keep(entry, term, score, kind):
                    if entry.cat in {'artist', 'character', 'copyright', 'e621'}:
                        return
                    tag = entry.tag
                    if tag in found_rows:
                        old = found_rows[tag]
                        old['matched_queries'] = list(dict.fromkeys([*old['matched_queries'], term]))[:6]
                        if score > old['_score']:
                            old.update(_score=score, match_kind=kind)
                        return
                    row = self.glossary.describe(_autocomplete_row(SimpleNamespace(tag=tag, entry=entry)))
                    raw = getattr(self.context, 'kr_tags_raw', {}).get(tag, {})
                    row['subgroup'] = raw.get('subgroup', '')
                    found_rows[tag] = row | {'matched_queries': [term], 'match_kind': kind,
                                             'origin': 'TagSearchIndex', '_score': score}
                for term in [*en, *ko]:
                    exact = index.entry_for(term)
                    if exact:
                        keep(exact, term, 100, 'exact')
                    found = index.search_semantic(term, limit=limit * 2)
                    for rank, row in enumerate(found):
                        keywords = {normalize(k) for k in getattr(row.entry, 'keywords', ()) if k}
                        keyword_exact = normalize(term) in keywords
                        keep(row.entry, term, 90 if keyword_exact else 40 - rank,
                             'keyword_exact' if keyword_exact else 'semantic')
                        if keyword_exact and row.tag in found_rows:
                            matched = found_rows[row.tag].setdefault('matched_keywords', [])
                            if term not in matched:
                                matched.append(term)
                for tag in self.glossary.search(args['query']):
                    entry = index.entry_for(tag)
                    if entry:
                        keep(entry, args['query'], 45, 'english_description')
                rows = sorted(found_rows.values(), key=lambda row: -row['_score'])[:limit]
                for row in rows:
                    row.pop('_score')
                    # Use the full canonical keyword index, not the truncated
                    # result list, to distinguish a name from a broad category.
                    unique = []
                    for keyword in row.get('matched_keywords', []):
                        aliases = getattr(index, '_term_to_tags', {}).get(normalize(keyword), ())
                        exact_tags = {tag for tag in aliases if (entry := index.entry_for(tag))
                                      and normalize(keyword) in {normalize(k) for k in entry.keywords}}
                        if exact_tags == {row['tag']}:
                            unique.append(keyword)
                    if unique:
                        row['unambiguous_keywords'] = unique
                return {'source': 'TagSearchIndex.search_semantic', 'query': args['query'],
                        'items': rows, 'queries_executed': {'en': en, 'ko': ko},
                        'fallback_queries': [term for term in en if term != normalize(args['query'])],
                        'note': 'Candidates; read meanings, not proof of semantic equivalence.'}
            if name == 'fast_search':
                source = args.get('source', 'tag')
                opts = {'rating': args.get('rating', ''), 'person': args.get('person', ''),
                        'mode': 'NAI', 'event_detail': 'basic', 'event_offset': args.get('offset', 0)}
                if source == 'event':
                    from core.event_map.quick_search import search, combinations_with_total
                    service = self.context.event_map_service
                    idx = service.index()
                    terms = [t.strip() for t in args['query'].split(',') if t.strip()]
                    tids = [idx.resolve(t) for t in terms]
                    if terms and all(tid is not None for tid in tids):
                        # Fast Search's UI suggests prefixes (hug -> huge ...).
                        # An exact model query must pin that tag before limiting.
                        pins = [idx.by_id[tid] for tid in tids]
                        rows, total = combinations_with_total(service, pins, opts['rating'], opts['person'])
                        offset = args.get('offset', 0)
                        result = (rows[offset:offset+args.get('limit', 5)],
                                  'Exact pins; sampled observation counts, not global probabilities.',
                                  {'data_source': 'naiamap', 'pins': pins, 'matching_posts': total,
                                   'exhausted': offset+args.get('limit', 5) >= len(rows)})
                    else:
                        result = search(self.context, args['query'], args.get('limit', 5), opts, _kr_lookup(self.context))
                else:
                    result = SEARCHERS[source](self.context, args['query'], args.get('limit', 5), opts)
                return {'source': f'Fast Search / {source}', 'items': result[0], 'note': result[1],
                        **(result[2] if len(result) > 2 else {})}
            if name == 'event_map':
                result = self.context.event_map_service.explore(
                    pins=args['pins'], exclude=args.get('exclude', []), ratings=args.get('rating', ''),
                    persons=args.get('person', ''), limit=args.get('limit', 6), sort='mix')
                index = ensure_tag_search_index(self.context)
                rows = []
                for candidate in result.get('candidates', []):
                    entry = index.entry_for(candidate['tag'])
                    if not entry or entry.cat in {'artist', 'character', 'copyright', 'e621'}:
                        continue
                    row = self.glossary.describe(_autocomplete_row(SimpleNamespace(tag=entry.tag, entry=entry)))
                    rows.append(row | {'origin': 'Event Map / TagSearchIndex',
                                       **{k:candidate[k] for k in ('observed','lift','role') if k in candidate}})
                return {'source': 'EventMapService', 'pins': result.get('pins', args['pins']),
                        'exclude': result.get('exclude', args.get('exclude', [])),
                        'observed_posts': result.get('observed_posts', 0), 'items': rows,
                        **{k:result[k] for k in ('status','ok','error','unknown_pins','relaxed','sampled') if k in result},
                        'note': 'Observed co-occurrence only; not semantic equivalence or proof of actor direction. Every returned tag checked in TagSearchIndex.'}
            raise ValueError('Unknown asset tool')

    def event_pins(self, candidates):
        """Resolve verified lexical candidates without performing a broad map query."""
        with self.lock:
            index = self.context.event_map_service.index()
            return [index.by_id[tid] for tag in candidates if (tid := index.resolve(tag)) is not None]
