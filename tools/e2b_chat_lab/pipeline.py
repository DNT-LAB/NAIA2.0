"""Small role contracts. User facts, design decisions and conversion stay separate."""
import re
from tools.e2b_chat_lab.retrieval import phrase_present, negative_requirement


def obj(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}


def text(n=240):
    return {'type':'string','maxLength':n}


def items(schema, n=8):
    return {'type':'array','items':schema,'maxItems':n}


SEARCH = obj({'source':{'type':'string','enum':['tag','artist','character','wildcard','preset','event','conversation']}, 'query':text(160)})
INTENT_SCHEMA = obj({
    'route':{'type':'string','enum':['chat','search','recall','compose']},
    'goal':text(400), 'target_model':text(100),
    'must_keep':items(obj({'en':text(200) | {'minLength':1},'quote':text(240) | {'minLength':1}}),10),
    'may_choose':items({'type':'string','enum':['stance','body_orientation','hand_placement','camera','lighting','background','expression']},7),
    'searches':items(SEARCH,4),
})
DESIGN_SCHEMA = obj({
    'stance_en':text(160), 'body_en':text(240),
    'left_hand_en':text(240), 'right_hand_en':text(240),
    'camera_en':text(200), 'action_en':text(240),
    'scene_en':text(1000), 'summary_ko':text(800),
    'preserved_ids':items(text(8),10), 'searches':items(SEARCH,3),
})
CONVERT_SCHEMA = obj({
    'appearance_style_tags':items(text(80),10), 'negative_prompt':text(600),
    'tags':items(text(100),12), 'preserved_ids':items(text(8),10),
    'notes_ko':text(500),
})


def wants_composition(message):
    return bool(re.search(r'프롬프트|구도|장면|이미지|\bprompt\b|\bscene\b',message,re.I)
                and re.search(r'구성|만들|작성|짜\s*줘|추천|제안|바꿔|수정|그려|묘사|\b(?:compose|create|write|build|change|suggest)\b',message,re.I))


def source_intent(intent, sources):
    """Assign stable per-round IDs to exact user evidence, not model assumptions."""
    if intent['route'] == 'compose' and not intent['must_keep']:
        raise ValueError('No user requirements were extracted')
    used = set()
    for index, requirement in enumerate(intent['must_keep'], 1):
        if not requirement['en'].strip() or not requirement['quote'].strip():
            raise ValueError('Empty requirement or source quote')
        match = next((s for s in sources if requirement['quote'] in s['user']),None)
        if not match:
            raise ValueError('Requirement evidence is not an exact user quote')
        requirement.update(id=f'K{index}',source_round=match['round_id'])
        used.add(match['round_id'])
    # A followup belongs to the active scene even when extraction omitted its
    # clauses. Keep its full original available, not only the older matched IDs.
    intent['source_rounds'] = sorted(used | {sources[0]['round_id']})
    intent['may_choose'] = list(dict.fromkeys(intent['may_choose']))


def check_preserved(result, intent):
    expected = {item['id'] for item in intent['must_keep']}
    if set(result['preserved_ids']) != expected:
        raise ValueError('The stage did not acknowledge every locked requirement')


def merged_searches(*groups):
    merged, seen = [], set()
    for group in groups:
        for original in group:
            search = dict(original)
            if search['source'] == 'tag':
                search['query'] = {'girl':'1girl','a girl':'1girl','boy':'1boy','a boy':'1boy'}.get(search['query'].casefold().strip(),search['query'])
            key = (search['source'], search['query'].strip().casefold())
            if key[1] and key not in seen:
                merged.append(search)
                seen.add(key)
    return merged[:6]


def tag_candidates(trace):
    candidates = {}
    for event in trace:
        if event['status'] != 'ok' or event['name'] not in {'search_tags', 'event_map'}:
            continue
        if event.get('result', {}).get('error') or event.get('result', {}).get('ok') is False:
            continue
        for row in event.get('result', {}).get('items', []):
            if row.get('tag'):
                previous = candidates.get(row['tag'], {})
                if not previous or row.get('match_kind') == 'exact':
                    candidates[row['tag']] = row
    return candidates


def render_conversion(intent, design, result, candidates):
    check_preserved(result,intent)
    normalize = lambda tag:tag.lower().replace('_',' ').strip()
    spellings = {normalize(tag):tag for tag in candidates}
    scene = normalize(' '.join(design[k] for k in ('stance_en','body_en','left_hand_en','right_hand_en','camera_en','action_en','scene_en')))
    def supported(tag):
        if any(negative_requirement(r) and phrase_present(tag, r['en']) for r in intent['must_keep']):
            return False
        if re.search(r'\b(?:without|not|no|excluding)\s+(?:any\s+|a\s+|the\s+)?' + re.escape(normalize(tag)) + r'\b', scene):
            return False
        return phrase_present(tag, scene) or (normalize(tag)=='1girl' and bool(re.search(r'\b(?:a |one )?girl\b',scene)))
    requested = ' '.join(r['en'] for r in intent['must_keep'] if not negative_requirement(r))
    direct = [tag for tag, row in candidates.items() if row.get('match_kind') == 'exact' and supported(tag)
              and (phrase_present(tag, requested) or (tag == '1girl' and re.search(r'\bgirl\b', requested))
                   or (tag == '1boy' and re.search(r'\bboy\b', requested)))]
    selected = list(dict.fromkeys([*direct, *(spellings[normalize(tag)] for tag in result['tags']
                                 if normalize(tag) in spellings and supported(tag))]))
    rejected = [tag for tag in result['tags'] if normalize(tag) not in spellings or not supported(tag)]
    # Preserve the decided physical scene verbatim instead of depending on a
    # second translation to retain stance/grip/camera. Conversion supplies style,
    # subject descriptors and target format; these clauses are the design output.
    clauses = [design['scene_en'].rstrip('.'), design['stance_en'], design['body_en'], design['camera_en'], design['action_en']]
    for side in ('left','right'):
        value = design[side+'_hand_en']
        if value.casefold().strip() not in {'not applicable','offscreen','not visible'}:
            clauses.append(side + ' hand: ' + value)
    # Append only clauses absent from the scene sentence to avoid restating each
    # field twice. Hand locations remain explicit even when prose omits them.
    retained = []
    for clause in clauses:
        if clause.casefold() not in ' '.join(retained).casefold():
            retained.append(clause)
    # Conversion may restyle the scene, but a search hit must not change a fixed
    # hairstyle/prop (e.g. short hair -> short hair with long locks).
    styles = {'anime style','anime','anime illustration','masterpiece','best quality','high quality'}
    prefix_parts = [phrase for phrase in result['appearance_style_tags'] if supported(phrase) or normalize(phrase) in styles]
    rejected.extend(phrase for phrase in result['appearance_style_tags'] if phrase not in prefix_parts)
    # Retrieved tags must actually be in the copyable prompt, not only a footer.
    prefix = ', '.join(dict.fromkeys([*selected, *prefix_parts])).strip(' ,.')
    positive = (prefix + '. ' if prefix else '') + '; '.join(retained) + '.'
    lines = ['**유지할 조건**', ' · '.join(r['quote'] for r in intent['must_keep']),
             '', '**선택한 자세·구도**', design['summary_ko'],
             '', '**프롬프트**', positive]
    if result['negative_prompt'].strip():
        lines += ['', '**네거티브 프롬프트**', result['negative_prompt'].strip()]
    if selected:
        lines += ['', '**검색에서 확인한 태그**', ', '.join(selected)]
    if result['notes_ko'].strip():
        lines += ['', result['notes_ko'].strip()]
    return '\n'.join(lines), rejected
