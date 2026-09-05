"""Read-only adapters for the thinking Chat agent; no downloads or mutations."""
from __future__ import annotations
import re


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
