"""Read-only adapters for the thinking Chat agent; no downloads or mutations."""
from __future__ import annotations
import re


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
                if item not in evidence:
                    evidence.append(item)
    kinds = {item['kind'] for item in evidence}
    origin = ('both' if kinds == {'label', 'alias'} else
              next(iter(kinds)) if len(kinds) == 1 else 'unknown')
    return {'keyword_origin': origin, 'keyword_evidence': evidence}


def _search_chat_keywords(context, query: str, limit: int = 6) -> list[dict]:
    """Chat search lane: exact Korean keywords, existing English retrieval.

    Autocomplete ranks partial/description matches for typing assistance. They
    must not become selected concepts just because a native tool used Korean.
    Read its structured entries without changing the shared index or ranking.
    """
    from core.tag_knowledge import has_hangul
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
    rows = []
    # Filter before limiting: a popular partial match must not crowd an exact
    # low-frequency keyword out of the candidate window.
    for result in index.search_semantic(q, limit=None):
        keyword = next((kw for kw in result.entry.keywords
                        if normalize_search_query(kw) == q), None)
        if keyword is None:
            continue
        # Keep the same named-entity, parenthesis and frequency boundary as the
        # English general vocabulary; characters have their own search tool.
        canonical = next((row for row in general.search(result.tag, 1)
                          if normalize_search_query(row['tag']) == normalize_search_query(result.tag)), None)
        if canonical is None:
            continue
        rows.append({**canonical, 'match_kind': 'keyword_exact',
                     'matched_query': q, 'matched_keyword': keyword,
                     **_keyword_evidence(context, index, result.tag, q)})
        if len(rows) >= min(limit, 12):
            break
    return rows


def search_chat_tags(context, query: str, limit: int = 6) -> list[dict]:
    """Overlay reviewed Chat aliases without changing shared Search data."""
    from core.ollama_chat_semantics import alias_senses, annotate, norm
    from app.backend.server.ollama_routes import ensure_llm_search_index

    if not str(query).strip() or len(query) > 160 or limit <= 0:
        return []
    rows = _search_chat_keywords(context, query, limit)
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


def search_events(context, query: str, rating: str, person_id: str) -> dict:
    from app.backend.server.preset_services import event_preset_service
    from core.event_preset.engines import PERSON_PARTITION_ORDER

    svc = event_preset_service(context)
    if svc.status().get("dataAvailability", {}).get("main") != "ready":
        return {"status": "unavailable", "tags": [], "events": [],
                "note": "Event Preset data is not installed. No download was started."}
    # Native models commonly return the label rather than its one-letter id.
    # Normalize exact rating names only; unknown ratings still require a choice.
    rating = rating.strip().casefold()
    rating = {"general": "g", "sensitive": "s", "questionable": "q", "explicit": "e"}.get(rating, rating)
    if rating not in {"g", "s", "q", "e"} or person_id not in PERSON_PARTITION_ORDER:
        return {"status": "choose_partition", "ratings": ["g", "s", "q", "e"],
                "persons": PERSON_PARTITION_ORDER, "tags": []}
    if len(query) > 160:
        return {"status": "invalid_query", "tags": []}
    boot = svc.bootstrap(rating_id=rating, person_id=person_id, search=query, limit=4)
    selected = boot.get("selected", {})
    if selected.get("ratingId") != rating or selected.get("personId") != person_id:
        return {"status": "partition_unavailable", "tags": [], "requested": {
            "rating": rating, "person_id": person_id}, "persons": boot.get("persons", [])}
    def has_events(payload):
        return any(sub.get("events") for category in payload.get("categories", [])
                   for sub in category.get("subcategories", []))

    matched_query = query
    # Event labels describe interactions, while model queries may also include
    # the object (giving flower). Offer explicitly broader prefix candidates,
    # at most twice, instead of mistaking an exact-label miss for no event data.
    parts = query.split()
    for remove in range(1, min(3, len(parts))):
        if has_events(boot):
            break
        shorter = " ".join(parts[:-remove])
        candidate = svc.bootstrap(rating_id=rating, person_id=person_id, search=shorter, limit=4)
        selection = candidate.get("selected", {})
        if selection.get("ratingId") == rating and selection.get("personId") == person_id and has_events(candidate):
            boot, matched_query = candidate, shorter
    events, tags = [], {}
    for category in boot.get("categories", []):
        for sub in category.get("subcategories", []):
            for event in sub.get("events", []):
                if len(events) >= 4:
                    break
                eid = event["id"]
                detail = svc.observed_combos({"ratingId": rating, "personId": person_id, "eventId": eid})
                combos = (detail.get("event") or {}).get("observedCombos", [])[:3]
                compact = [{"tags": c.get("tags", [])[:16], "count": c.get("count", 0)} for c in combos]
                events.append({"id": eid, "label": event.get("label", eid), "combos": compact})
                tags[eid] = {"tag": eid}
                for combo in compact:
                    for tag in combo["tags"]:
                        tags[tag] = {"tag": tag}
    return {"status": "ok" if events else "no_match", "events": events, "tags": list(tags.values()),
            "rating": rating, "person_id": person_id, "query": query, "matched_query": matched_query,
            "note": (("Broader event-label candidates; check relevance to the original request. " if matched_query != query else "") +
                     "Observed co-occurrence does not assign actions or clothing to a specific character."
                     if events else "No matching event label. Try a shorter interaction query without object/adjective words.")}
