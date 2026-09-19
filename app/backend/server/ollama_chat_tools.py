"""Read-only adapters for the thinking Chat agent; no downloads or mutations."""
from __future__ import annotations
import hashlib
import json
import re


def _spacing_keywords(context, index):
    """Cache cross-spelling conflicts for this raw/index version, Chat only.

    Include all indexed tags before general-vocabulary filtering. Otherwise an
    excluded entity could hide a conflicting spelling. A shared category label
    with several targets is not itself a spacing conflict; differing target SETS
    across existing spellings are. Unseen semantic ambiguity remains unreviewed.
    """
    from core.ollama_chat_semantics import korean_spacing_key
    from core.tag_search_index import normalize_search_query

    raw = getattr(context, 'kr_tags_raw', None)
    cached = getattr(context, '_chat_spacing_keywords', None)
    if cached is not None and cached[0] is raw and cached[1] is index:
        return cached[2]
    forms = {}
    for tag, entry in index._entries.items():
        for keyword in entry.keywords:
            form = normalize_search_query(keyword)
            # Ineligible query spellings (e.g. separated numbers) can still
            # reveal a collision; do not hide them from the exclusion set.
            key = korean_spacing_key(form.replace(' ', ''))
            if key:
                forms.setdefault(key, {}).setdefault(form, set()).add(tag)
    unsafe = frozenset(key for key, spellings in forms.items()
                       if len({frozenset(tags) for tags in spellings.values()}) > 1)
    context._chat_spacing_keywords = (raw, index, unsafe)
    return unsafe


def _keyword_evidence(context, index, tag: str, query: str) -> dict:
    """Recover syntactic origins from raw fields, never flattened index order.

    Keep references, not another copy of the vocabulary. Rebuild on either raw
    replacement or shared-index invalidation (the data provisioning contract).
    """
    from core.tag_axis_registry import normalize_tag
    from core.tag_search_index import normalize_search_query

    raw = getattr(context, 'kr_tags_raw', None)
    cached = getattr(context, '_chat_keyword_records', None)
    if cached is None or cached[0] is not raw or cached[1] is not index:
        by_tag = {}
        for record in (raw or {}).values():
            canonical = normalize_tag(str(record.get('_tag', '') or record.get('tag', '')))
            if canonical:
                by_tag.setdefault(canonical, []).append(record)
        cached = (raw, index, by_tag)
        context._chat_keyword_records = cached
    evidence = []
    for record in cached[2].get(normalize_tag(tag), []):
        for field in ('keywords_kr', 'keywords'):
            parts = [part.strip() for part in str(record.get(field, '') or '').split(',') if part.strip()]
            for position, part in enumerate(parts):
                if normalize_search_query(part.replace('<', '').replace('>', '')) != query:
                    continue
                if position == 0 and re.fullmatch(r'<[^<>]+>', part):
                    kind = 'label'
                elif '<' in part or '>' in part:
                    kind = 'unknown'
                else:
                    kind = 'alias'
                item = {'field': field, 'kind': kind}
                source = record.get('_korean_alias_sources', {}).get(query)
                if source and kind == 'alias':
                    item.update(source)
                if item not in evidence:
                    evidence.append(item)
    kinds = {item['kind'] for item in evidence}
    origin = ('both' if kinds == {'label', 'alias'} else
              next(iter(kinds)) if len(kinds) == 1 else 'unknown')
    return {'keyword_origin': origin, 'keyword_evidence': evidence}


def _search_chat_keywords(context, query: str, limit: int = 6) -> list[dict]:
    """Exact Korean keywords, collision-checked spacing, existing English retrieval.

    Autocomplete ranks partial/description matches for typing assistance. They
    must not become selected concepts just because a native tool used Korean.
    Read its structured entries without changing the shared index or ranking.
    """
    from core.tag_knowledge import has_hangul
    from core.ollama_chat_semantics import korean_spacing_key
    from core.tag_search_index import normalize_search_query
    from app.backend.server.ollama_routes import ensure_llm_search_index, search_llm_tags

    if not has_hangul(query):
        return search_llm_tags(context, query, limit=limit)
    q = normalize_search_query(query)
    if not q or len(query) > 160 or limit <= 0:
        return []
    from app.backend.server.autocomplete_commands import ensure_tag_search_index

    index = ensure_tag_search_index(context)
    general = ensure_llm_search_index(context)
    compact = korean_spacing_key(q)
    allow_spacing = bool(compact) and compact not in _spacing_keywords(context, index)
    matches = []
    rows = []
    # Filter before limiting: a popular partial match must not crowd an exact
    # low-frequency keyword out of the candidate window.
    for result in index.search_semantic(q, limit=None):
        keyword = next((kw for kw in result.entry.keywords
                        if normalize_search_query(kw) == q), None)
        kind = 'keyword_exact'
        if keyword is None and allow_spacing:
            keyword = next((kw for kw in result.entry.keywords
                            if korean_spacing_key(normalize_search_query(kw)) == compact), None)
            kind = 'keyword_spacing_variant'
        if keyword is not None:
            matches.append((kind, result.tag, keyword))
    # Weak variants cannot displace an existing exact result at the limit.
    matches.sort(key=lambda match: match[0] != 'keyword_exact')
    for kind, tag, keyword in matches:
        # Keep the same named-entity, parenthesis and frequency boundary as the
        # English general vocabulary; characters have their own search tool.
        canonical = next((row for row in general.search(tag, 1)
                          if normalize_search_query(row['tag']) == normalize_search_query(tag)), None)
        if canonical is None:
            continue
        rows.append({**canonical, 'match_kind': kind,
                     'matched_query': q, 'matched_keyword': keyword,
                     **({'spacing_collision_free': True} if kind == 'keyword_spacing_variant' else {}),
                     **_keyword_evidence(context, index, tag, normalize_search_query(keyword))})
        if len(rows) >= min(limit, 12):
            break
    return rows


def search_chat_tags(context, query: str, limit: int = 6) -> list[dict]:
    """Overlay reviewed Chat aliases without changing shared Search data."""
    from core.ollama_chat_semantics import alias_senses, annotate, norm
    from app.backend.server.ollama_routes import ensure_llm_search_index

    if not str(query).strip() or len(query) > 160 or limit <= 0:
        return []
    from core.named_entity_aliases import ensure_named_entity_index

    named = ensure_named_entity_index(context).search(query, limit=limit)
    if named:
        # Names can also be ordinary words (샴푸, 유리). Keep exact general
        # lexical candidates as alternatives, not an implicit identity choice.
        from core.tag_knowledge import normalize_tag_key

        general_rows = _search_chat_keywords(context, query, limit)
        general_rows = [r for r in general_rows if r.get('match_kind') in
                        {'keyword_exact', 'keyword_spacing_variant'}
                        and normalize_tag_key(r.get('matched_query', '')) == normalize_tag_key(query)]
        if general_rows:
            named = [{**r, 'ambiguous': True} for r in named]
        return [annotate(row, query) for row in [*named, *general_rows][:min(limit, 12)]]
    rows = _search_chat_keywords(context, query, limit)
    # Retrieval synonyms are evidence of a whole English phrase only. They
    # do not extend the scene/role-certified vocabulary in alias_senses.
    from core.english_tag_keywords import VERSION, is_english_keyword_match

    for row in rows:
        if (is_english_keyword_match(query, row['tag'])
                and ensure_llm_search_index(context).resolve_english_keyword(query) == row['tag']):
            row.update(match_kind='english_keyword_exact', matched_query=query,
                       matched_keyword=query, keyword_origin='english_keyword',
                       keyword_evidence=[{'source': VERSION}])
    senses = alias_senses(query)
    general = None
    existing = {norm(row['tag']) for row in rows}
    for sense in senses:
        for tag in sense['tags']:
            if norm(tag) in existing:
                continue
            if general is None:
                general = ensure_llm_search_index(context)
            canonical = next((r for r in general.search(tag, 1) if norm(r['tag']) == norm(tag)), None)
            if canonical is not None:
                rows.append({**canonical, 'match_kind': 'reviewed_alias_exact',
                             'matched_query': query, 'matched_keyword': query,
                             'keyword_origin': 'reviewed_alias', 'keyword_evidence': [],
                             'reviewed_sense_id': sense['id']})
                existing.add(norm(tag))
    reviewed_tags = {norm(tag) for sense in senses for tag in sense['tags']}
    rows.sort(key=lambda row: norm(row['tag']) not in reviewed_tags)
    return [annotate(row, query) for row in rows[:min(limit, 12)]]


def search_characters(context, query: str) -> dict:
    from app.backend.server.character_viewer_routes import character_viewer_service

    if not query.strip() or len(query) > 160:
        return {"status": "invalid_query", "characters": [], "tags": []}
    from core.named_entity_aliases import ensure_named_entity_index

    bound = ensure_named_entity_index(context).search(query, categories={'character'}, limit=6, prefix=True)
    if bound:
        rows = [{**row, 'work': row['group'], 'exact': row['match_kind'] != 'entity_name_prefix'} for row in bound]
        return {'status': 'ok', 'characters': rows, 'tags': rows,
                'ambiguous': rows[0]['entity_candidate_count'] > 1,
                'note': 'Name bindings are candidates. Preserve the full canonical name and work. '
                        'If ambiguous, ask for the work or full name; do not choose by popularity.'}
    svc = character_viewer_service(context)
    if not isinstance(getattr(context, "kr_tags_raw", None), dict):
        from app.backend.server.ollama_routes import ensure_llm_search_index
        ensure_llm_search_index(context)
    records = getattr(context, "kr_tags_raw", {}) or {}
    # The general tag index excludes characters; the catalog owns their names.
    needle = query.strip().replace("_", " ").casefold()
    matches = []
    for group, entries in svc.analysis().items():
        for name, data in entries.items():
            record = records.get(name.replace("_", " "), records.get(name, {}))
            # Bracketed entries are category words, not character-name aliases.
            aliases = [x.strip() for x in re.sub(r"<[^>]*>", "", str(record.get("keywords_kr", ""))).split(",") if x.strip()]
            names = [name.replace("_", " "), *aliases]
            if any(needle in n.casefold() for n in names):
                matches.append({"tag": name, "work": group,
                                "names": names, "exact": any(needle == n.casefold() for n in names),
                                "count": int(data.get("total_rows", 0) or 0)})
    matches.sort(key=lambda row: (not row["exact"], -row["count"], row["tag"]))
    rows, seen = [], set()
    for row in matches:
        key = row["tag"].replace("_", " ").casefold()
        if key not in seen:
            rows.append(row)
            seen.add(key)
        if len(rows) == 6:
            break
    return {"status": "ok" if rows else "no_match", "characters": rows, "tags": rows,
            "note": "Match the original full name and work. Never replace the requested character with a different popular match."}


def search_events(context, query: str, rating: str, person_id: str, detail: str = 'basic') -> dict:
    from core.event_preset.fast_search_catalog import PERSON_IDS, RATING_IDS, search_catalog
    # Native models commonly return the label rather than its one-letter id.
    # Normalize exact rating names only; unknown ratings still require a choice.
    rating = rating.strip().casefold()
    rating = {"general": "g", "sensitive": "s", "questionable": "q", "explicit": "e"}.get(rating, rating)
    if not query.strip() or rating not in RATING_IDS or person_id not in PERSON_IDS:
        return {"status": "choose_partition", "ratings": ["g", "s", "q", "e"],
                "persons": list(PERSON_IDS), "tags": [], 'source': 'bundled_event_catalog'}
    if len(query) > 160 or detail not in {'basic', 'deep'}:
        return {"status": "invalid_query", "tags": []}
    matches = search_catalog(query, 4, rating=rating, person=person_id, detail=detail)
    matched_query = query
    # Event labels describe interactions, while model queries may also include
    # the object (giving flower). Offer explicitly broader prefix candidates,
    # at most twice, instead of mistaking an exact-label miss for no event data.
    parts = query.split()
    for remove in range(1, min(3, len(parts)) if ',' not in query else 1):
        if matches:
            break
        shorter = " ".join(parts[:-remove])
        candidate = search_catalog(shorter, 4, rating=rating, person=person_id, detail=detail)
        if candidate:
            matches, matched_query = candidate, shorter
    events, tags = [], {}
    for event, variant in matches:
        # Identity describes a tag set in one partition/detail, independent of
        # query spelling, anchor label, rank and model choices.
        identity = json.dumps([1, rating, person_id, detail, sorted(variant.tags)], ensure_ascii=False)
        bundle_id = 'ev_' + hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]
        events.append({'id': event.tag, 'label': event.label,
                       'combos': [{'bundle_id': bundle_id, 'tags': list(variant.tags), 'count': variant.count}]})
        for tag in variant.tags:
            row = tags.setdefault(tag, {'tag': tag, 'bundle_ids': []})
            if bundle_id not in row['bundle_ids']:
                row['bundle_ids'].append(bundle_id)
    return {"status": "ok" if events else "no_match", "events": events, "tags": list(tags.values()),
            "rating": rating, "person_id": person_id, "query": query, "matched_query": matched_query,
            'source': 'bundled_event_catalog', 'detail': detail,
            "note": (("Broader event-label candidates; check relevance to the original request. " if matched_query != query else "") +
                     "Observed co-occurrence does not assign actions or clothing to a specific character."
                     if events else "No matching event label. Try a shorter interaction query without object/adjective words.")}
