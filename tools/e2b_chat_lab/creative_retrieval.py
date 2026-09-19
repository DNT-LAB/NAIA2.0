"""Bounded discovery candidates; proposals are options, never locked user facts."""
from tools.e2b_chat_lab.retrieval import (canonical_present, english_words, keyword_bridge,
    keyword_supported, negative_requirement, negative_source_text, normalize, positive_text, stem)


def creative_catalog(trace, candidates, intent, original, limit):
    core = positive_text(intent)
    proposal = intent.get('scene_proposal_en', '')
    negative = ' '.join(r['en'] for r in intent.get('must_keep', []) if negative_requirement(r))
    excluded = negative_source_text(original) + ' ' + negative_source_text(intent.get('goal', ''))
    allowed = {tag: row for tag, row in candidates.items()
               if not (canonical_present(tag, negative) or canonical_present(tag, excluded)
                       or keyword_supported(row, excluded))}

    def kind(tag):
        if canonical_present(tag, core) or keyword_bridge(tag, allowed[tag], allowed, original, intent):
            return 'core_candidate'
        if canonical_present(tag, proposal):
            return 'proposal_candidate'
        return 'discovery_candidate'

    def rank(tag):
        row = allowed[tag]
        return (kind(tag) == 'proposal_candidate', row.get('match_kind') == 'exact',
                bool(row.get('desc') or row.get('description_en')))

    # Reserve discovery space. A large group of exact core hits must not hide
    # a lighting/background query; each successful query gets a turn.
    selected = [tag for tag in allowed if kind(tag) == 'core_candidate'][:min(6, max(0, limit - 4))]
    lanes = []
    for event in trace:
        if event.get('status') != 'ok' or event.get('name') not in {'search_tags', 'event_map'}:
            continue
        result = event.get('result', {})
        if result.get('error') or result.get('ok') is False:
            continue
        tags = list(dict.fromkeys(r.get('tag') for r in result.get('items', []) if r.get('tag') in allowed))
        lanes.append(sorted(tags, key=rank, reverse=True))
    # The fallback also supports an already collected catalog without traces.
    if not lanes:
        lanes = [sorted(allowed, key=rank, reverse=True)]
    while len(selected) < limit:
        progress = False
        for lane in lanes:
            while lane and lane[0] in selected:
                lane.pop(0)
            if lane:
                selected.append(lane.pop(0))
                progress = True
                if len(selected) == limit:
                    break
        if not progress:
            break
    rows = []
    for tag in selected:
        row = allowed[tag]
        rows.append({'tag': tag, 'use': kind(tag),
                     'matched_user_keywords': [k for k in row.get('unambiguous_keywords', [])
                                               if keyword_supported({'matched_keywords':[k]}, original)],
                     'meaning_en': row.get('description_en', '')[:180],
                     'meaning_ko': '' if row.get('description_en') and row.get('translation_status') == 'translated' else row.get('desc', '')[:100],
                     'group': row.get('group', ''), 'subgroup': row.get('subgroup', ''),
                     'origin': row.get('origin', 'TagSearchIndex'),
                     'translation_status': row.get('translation_status', 'unavailable')})
    events = [t for t in trace if t.get('name') == 'event_map']
    return {'items': rows, 'event_queries': [
        {'pins': t['arguments']['pins'], 'status': t['status'],
         'observed_posts': t.get('result', {}).get('observed_posts'),
         'error': t.get('result', {}).get('error', '')} for t in events],
        'excluded_candidates': len(candidates) - len(allowed),
        'omitted_for_budget': max(0, len(allowed) - len(rows)),
        'note': 'Core, proposal and discovery candidates are options, not new user requirements. '
                'Read meanings and choose details that enrich the scene without changing fixed facts. '
                'Co-occurrence and taxonomy links do not prove suitability.'}


def event_query_plan(pins, candidates):
    """Prefer action/object and location/content to two generic action verbs."""
    actions = [tag for tag in pins if any(stem(w) in {
        'carry','struggle','hold','walk','sit','fire','kneel','hug','run','ride','stand'
    } for w in english_words(tag))]
    def group(tag):
        return normalize(candidates[tag].get('group', ''))
    props = [tag for tag in pins if tag not in actions and (
        candidates[tag].get('axis') == 'object' or group(tag) in {'food object','food_object','물체'}
        or group(tag).startswith(('사물', '오브젝트')))]
    props.sort(key=lambda tag: candidates[tag].get('subgroup') in {'containers','weapons'}, reverse=True)
    locations = [tag for tag in pins if candidates[tag].get('axis') == 'location'
                 or group(tag) in {'location background','location_background','장소'}]
    first = [actions[0], props[0]] if actions and props else pins[:2]
    plan = [first] if first else []
    if locations and props:
        content = next((t for t in props if candidates[t].get('subgroup') == 'food_tags'), props[0])
        themed = list(dict.fromkeys([locations[0], content]))
        if not any(set(themed) == set(p) for p in plan):
            plan.append(themed)
    return plan[:2]
