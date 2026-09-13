"""Public intent/search contract, independent of the shared search dictionaries.

The model declares requirements, not private reasoning. Structural evidence can
detect omissions from that declaration; it cannot certify its completeness or
the meaning of arbitrary tags, relationships, or generated sentences.
"""
from __future__ import annotations

import copy
import re
from core.ollama_chat_semantics import norm

VERSION = 'intent-search-v1'


def obj(properties, required):
    return {'type': 'object', 'properties': properties, 'required': required,
            'additionalProperties': False}


def strings(limit=16):
    return {'type': 'array', 'items': {'type': 'string'}, 'maxItems': limit}


PLAN_SCHEMA = obj({
    'mode': {'type': 'string', 'enum': ['lookup', 'compose']},
    'output': obj({'format': {'type': 'string', 'enum': ['tags', 'sentence']},
                   'language': {'type': 'string'}}, ['format', 'language']),
    'actors': {'type': 'array', 'maxItems': 6, 'items': obj({
        'id': {'type': 'string'}, 'name': {'type': 'string'},
        'identity': {'type': 'string', 'enum': ['original', 'named']}}, ['id', 'name', 'identity'])},
    'requirements': {'type': 'array', 'minItems': 1, 'maxItems': 16, 'items': obj({
        'id': {'type': 'string'},
        'source': {'type': 'string', 'description': 'Exact substring of the current user request; no paraphrase'},
        'kind': {'type': 'string', 'enum': ['entity', 'attribute', 'action', 'comparison',
                                          'reaction', 'cause', 'composition', 'exclusion']},
        'actors': strings(6),
        'depends_on': strings(16),
    }, ['id', 'source', 'kind', 'actors', 'depends_on'])},
    'searches': {'type': 'array', 'minItems': 1, 'maxItems': 8, 'items': obj({
        'requirement_ids': {**strings(16), 'minItems': 1},
        'tool': {'type': 'string', 'enum': ['search_tags', 'search_characters', 'search_events']},
        'query': {'type': 'string'},
        'rating': {'type': 'string', 'description': 'ONLY for search_events: g/s/q/e. OMIT for other tools.'},
        'person_id': {'type': 'string', 'description': 'ONLY for search_events: population such as 2girls; never an actor id. OMIT for other tools.'},
        'detail': {'type': 'string', 'enum': ['basic', 'deep'],
                   'description': 'ONLY for search_events. OMIT this field entirely for search_tags and search_characters.'},
    }, ['requirement_ids', 'tool', 'query'])},
}, ['mode', 'output', 'actors', 'requirements', 'searches'])

SELECTIONS_SCHEMA = {'type': 'array', 'maxItems': 16, 'items': obj({
    'requirement_id': {'type': 'string'}, 'tags': strings(32),
    'state': {'type': 'string', 'enum': ['selected', 'missing', 'ambiguous', 'unrepresentable']},
}, ['requirement_id', 'tags', 'state'])}

PLAN_INSTRUCTIONS = """
For tag lookup or prompt composition, first call plan_search. It records your
intent plan AND executes its initial searches in this same turn; no extra turn
is needed to acknowledge a plan. Use mode=lookup for vocabulary, compose for a
scene. For compose the output is ALWAYS format=sentence and language=en: the
user receives a finished image prompt, never only a tag audit. finish.prompt
must be the selected English tags comma-separated, followed by one or two short
English natural-language sentences describing the scene (mood, light,
composition). Use format=tags only for lookup, or when the user explicitly asks
for tags only. The Korean summary is separate from finish.prompt.
For a word lookup use actors=[] and requirement.actors=[]. Actors are depicted
people, never words, objects, or abstract concepts. Use short queries: the
concept name itself, without filler words such as "object", "tag", or "scene".
Keep this plan small, but cover all explicit conditions: actors and their own
attributes, action direction, comparison, reaction owner, its cause, and any
exclusions. Each requirement.source must be an exact substring of this user
message. Use stable a/b/c actor IDs. Original characters with described traits
use identity=original; search_characters is for existing named identities only.
Link a reaction to its cause with depends_on; keep comparison participants and
specified direction in its source. Never invent an unspecified direction.
Requirements are immutable after the first accepted plan. Search queries may
change after reading evidence, but later searches must name requirement_ids.
Searches are independent; event partition choices require a later follow-up.
For search_tags and search_characters OMIT rating, person_id and detail entirely.
Event population filters are not named actors; do not invent actor names for them.
Select only relevant returned tags in their original actor/common scopes.
finish.selections maps EVERY requirement_id to selected tags and state:
selected, missing, ambiguous, or unrepresentable. Exclusions must not become
positive tags. A complex relationship/cause is not proven by a matching word.
Keep missing requirements visible; do not relabel a failed scene as chat.
Use separate queries for independent concepts; keep compound concepts intact.
Do not combine a character name, age and expression into one query. The server
also tries the original requirement text and routes named identities to the
character catalog. Source lookup can miss Korean verb forms or match category
labels; translate the missing concept, not the whole scene, to English.
Returned requirement_ids indicate candidate linkage, not meaning certification.
"""


_TAGS_ONLY_RE = re.compile(r'태그\s*만|tags?\s+only|only\s+tags?', re.I)


def tags_only_requested(source):
    """사용자가 "태그만" 을 명시했을 때만 tags 형식을 허용한다."""
    return bool(_TAGS_ONLY_RE.search(str(source or '')))


def scene_flat_tags(scene):
    seen = []
    for tag in list(scene.get('common_tags', [])) + [t for a in scene.get('actors', []) for t in a.get('tags', [])]:
        tag = str(tag or '').strip()
        if tag and tag not in seen:
            seen.append(tag)
    return seen


def compose_scene_prompt(scene, prompt):
    """모델의 finish.prompt 를 완성 프롬프트로 다듬는다: 선택 태그가 앞에 없으면 서버가 붙인다.
    (모델이 자연어 문장만 쓰고 태그를 빼먹는 경우 — 사용자는 태그 + 자연어를 한 덩어리로 받아야 한다.)"""
    text = ' '.join(str(prompt or '').split()).strip()
    tags = scene_flat_tags(scene)
    if not tags:
        return text
    low = text.lower()
    present = sum(1 for t in tags if t.lower() in low)
    if text and present * 10 >= len(tags) * 6:
        return text
    head = ', '.join(tags)
    return f'{head}, {text}' if text else head


def _unique_ids(items, name):
    ids = [item['id'] for item in items]
    if any(not i.strip() for i in ids) or len(set(ids)) != len(ids):
        raise ValueError(f'{name} ids must be nonempty and unique')
    return set(ids)


def validate_plan(plan, source, reference_names=()):
    """Called after JSON schema validation, before *any* planned provider call."""
    actors = _unique_ids(plan['actors'], 'Actor')
    requirements = _unique_ids(plan['requirements'], 'Requirement')
    if not plan['output']['language'].strip():
        raise ValueError('Output language is required')
    # 장면 구성(compose)은 늘 "완성 프롬프트"가 결과다(사용자 제보 2026-09-13: 모델이 tags 를 고르면
    # 감사 장부만 돌아왔다). 태그만 달라는 명시가 없으면 서버가 sentence/en 으로 못 박는다.
    if plan['mode'] == 'compose' and not tags_only_requested(source):
        plan['output']['format'] = 'sentence'
        plan['output']['language'] = 'en'
    if any(not a['name'].strip() for a in plan['actors']):
        raise ValueError('Actor name is required')
    if any(a['name'] not in source and a['name'] not in reference_names for a in plan['actors']):
        raise ValueError('Actor names must come from the user request or its referenced scene; '
                         'word lookups have actors=[] and requirement.actors=[]')
    if plan['mode'] == 'lookup' and any(a['identity'] == 'original' for a in plan['actors']):
        raise ValueError('Vocabulary lookup has no original actors; use actors=[]')
    edges = {}
    for req in plan['requirements']:
        if not req['source'].strip() or req['source'] not in source:
            raise ValueError(f"{req['id']}: source must be an exact substring of the current request")
        if not set(req['actors']).issubset(actors):
            raise ValueError('Requirement references an unknown actor')
        if not set(req['depends_on']).issubset(requirements):
            raise ValueError('Requirement references an unknown dependency')
        edges[req['id']] = req['depends_on']
    visited, active = set(), set()
    def visit(key):
        if key in active:
            raise ValueError('Requirement dependencies must not form a cycle')
        if key in visited:
            return
        active.add(key)
        for parent in edges[key]:
            visit(parent)
        active.remove(key)
        visited.add(key)
    for key in edges:
        visit(key)
    for search in plan['searches']:
        validate_search(plan, search['tool'], search)
        if len(search['query']) > 160 or (not search['query'].strip() and search['tool'] != 'search_events'):
            raise ValueError('Search queries must be 1-160 characters (event partition lookup may be empty)')
        if search['tool'] != 'search_events' and (search.get('rating') or search.get('person_id') or search.get('detail')):
            raise ValueError('Only event searches accept rating/person_id/detail. Remove these fields entirely '
                             'from search_tags and search_characters entries (including detail=basic). '
                             'Actor ownership belongs in requirement.actors, not search.person_id.')
    return copy.deepcopy(plan)


def validate_search(plan, tool, args):
    ids = args.get('requirement_ids', [])
    by_id = {r['id']: r for r in plan['requirements']}
    if not ids or len(ids) != len(set(ids)) or not set(ids).issubset(by_id):
        raise ValueError('Search must reference existing unique requirement_ids')
    if tool == 'search_characters':
        named = {a['id'] for a in plan['actors'] if a['identity'] == 'named'}
        if not any(by_id[i]['kind'] == 'entity' and set(by_id[i]['actors']) & named for i in ids):
            raise ValueError('Character search needs an entity requirement for an existing named actor')


def validate_finish(plan, args):
    if args['kind'] == 'clarification':
        return
    if args['kind'] != 'scene':
        raise ValueError('An accepted lookup/compose plan must finish as scene or clarification')
    if [(a['id'], a['name']) for a in args['actors']] != [(a['id'], a['name']) for a in plan['actors']]:
        raise ValueError('Keep the planned actors, names, ids, and order; tags=[] is allowed')
    ids = [s['requirement_id'] for s in args.get('selections', [])]
    if len(ids) != len(set(ids)) or not set(ids).issubset({r['id'] for r in plan['requirements']}):
        raise ValueError('Selection references duplicate or unknown requirement ids')
    # sentence 인데 finish.prompt 가 비어도 거부하지 않는다 — 거부는 모델 턴을 태워 stopped 로 떨어뜨린다.
    # attach_coverage 가 선택 태그만으로 합성하고 'missing_sentence' 확인 항목을 단다.


def attach_coverage(result, plan, args, ledger, grounding=None):
    """Compare model selection claims with actual scoped, searched, safe output."""
    result['intent_plan'] = copy.deepcopy(plan) if plan else None
    if result.get('type') != 'scene_agent':
        return result
    review = result['semantic_review']
    if plan is None:
        review['issues'].append({'code': 'intent_plan_missing',
            'message': '검색 전에 작성한 요구 목록이 없어 조건별 누락을 확인할 수 없습니다.'})
        result['completion'] = review['status'] = 'partial'
        result['message'] = '검색 전 요구 목록이 없어 조건별 의미 확인이 필요합니다.'
        result['coverage'] = {'version': VERSION, 'requirements': [], 'plan_present': False}
        return result
    scene = result['scene']
    claims = {s['requirement_id']: s for s in args.get('selections', [])}
    scoped = {'common': {norm(t) for t in scene['common_tags']}}
    # _finish normalizes actor ids; match by the validated original order.
    scoped.update({planned['id']: {norm(t) for t in actual['tags']}
                   for planned, actual in zip(plan['actors'], scene['actors'])})
    rows = []
    for req in plan['requirements']:
        rid = req['id']
        candidates = {key for key, entry in ledger.items() if any(
            rid in e.get('requirement_ids', []) for e in entry.get('evidence', []))}
        claim = claims.get(rid, {})
        chosen = {norm(t) for t in claim.get('tags', [])}
        owners = req['actors'] or ['common']
        # Attributes/reactions/entities must be present on EVERY named owner;
        # relationship candidates can live in common, but aren't certified.
        local_scope = (req['kind'] in {'attribute', 'reaction', 'entity'}
                       or (req['kind'] == 'action' and len(req['actors']) == 1))
        allowed = (set.intersection(*(scoped.get(owner, set()) for owner in owners))
                   if local_scope else set().union(*scoped.values()))
        evidence_ok = bool(chosen) and chosen.issubset(candidates & allowed)
        state = claim.get('state', 'missing')
        if state == 'selected' and not evidence_ok:
            state = 'missing'
        if req['kind'] == 'exclusion':
            state = 'unrepresentable'  # No arbitrary negative semantics from positive vocabulary.
        row = {'id': rid, 'source': req['source'], 'kind': req['kind'], 'actors': req['actors'],
               'depends_on': req['depends_on'], 'state': state, 'candidate_tags': sorted(candidates),
               'selected_tags': sorted(chosen & candidates & allowed), 'semantic_certified': False}
        if grounding:
            row['meaning_review'] = grounding.review(rid, row['selected_tags'])
        rows.append(row)
        if state != 'selected':
            review['issues'].append({'code': 'requirement_' + state, 'requirement_id': rid,
                'message': f"요구 확인 필요 ({state}): {req['source']}"})
        if req['kind'] in {'action', 'comparison', 'reaction', 'cause', 'exclusion'} or req['depends_on']:
            review['issues'].append({'code': 'unreviewed_requirement_relation', 'requirement_id': rid,
                'message': f"태그만으로 관계·원인을 검증할 수 없음: {req['source']}"})
    result['coverage'] = {'version': VERSION, 'plan_present': True,
        'scope': 'model-declared requirements; retrieval evidence is not semantic or exhaustive coverage',
        'requirements': rows}
    result['output'] = dict(plan['output'])
    if plan['output']['format'] == 'sentence':
        model_prompt = str(args.get('prompt', '') or '').strip()
        result['output']['prompt'] = compose_scene_prompt(scene, model_prompt)
        if model_prompt:
            review['issues'].append({'code': 'unreviewed_sentence',
                'message': '문장형 프롬프트의 추가·누락 의미는 직접 확인해 주세요.'})
        else:
            review['issues'].append({'code': 'missing_sentence',
                'message': '모델이 자연어 문장을 쓰지 않아 선택 태그만 담았습니다.'})
    if review['issues']:
        result['completion'] = review['status'] = 'partial'
        result['message'] = '요구별 검색 결과와 확인이 필요한 내용을 표시했습니다.'
    return result
