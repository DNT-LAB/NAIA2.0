"""Sentence-level interpretation and bounded review; originals stay in the harness."""
from tools.e2b_chat_lab.pipeline import obj, text, items, SEARCH


RELATION_SCHEMA = obj({
    'route': {'type': 'string', 'enum': ['chat', 'search', 'recall', 'compose']},
    'continuation': {'type': 'string', 'enum': ['new', 'followup']},
    'goal': text(1200),
    'target_model': text(100),
    'must_keep': items(obj({'en': text(350) | {'minLength': 1}}), 8),
    'may_choose': items({'type': 'string', 'enum': [
        'stance', 'body_orientation', 'hand_placement', 'camera', 'lighting', 'background', 'expression']}, 7),
    'scene_proposal_en': text(1100),
    'searches': items(obj({**SEARCH['properties'], 'query_ko': text(160)}), 6),
})

REVIEW_SCHEMA = obj({
    'issues': items(obj({'source_quote': text(80), 'problem': text(450)}), 3),
})


def bind_sources(route, sources):
    """Track original rounds, without treating translated facts as verified quotes."""
    if route['route'] == 'compose' and (not route['goal'].strip() or not route['must_keep']):
        raise ValueError('The scene interpretation is empty')
    route['interpretation_kind'] = 'creative_scene_v9'
    route['source_rounds'] = sorted({s['round_id'] for s in
                                   (sources if route['continuation'] == 'followup' else sources[:1])})
    route['may_choose'] = list(dict.fromkeys(route['may_choose']))
