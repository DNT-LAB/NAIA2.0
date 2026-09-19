"""Source-backed scene plans and constrained rendering, independent of the model API."""
import re


def wants_composition(text):
    """Conservative routing floor for explicit requests to build/change a prompt."""
    noun = re.search(r'프롬프트|구도|장면|\bprompt\b|\bscene\b', text, re.I)
    task = re.search(r'구성|만들|작성|짜\s*줘|추천|바꿔|수정|그려|묘사|\b(?:compose|create|write|build|change)\b', text, re.I)
    theory = re.search(r'무엇|뭐야|뜻|정의|차이|\bwhat is\b|\bdefinition\b', text, re.I)
    return bool(noun and task and not theory)


def check_scene(scene, sources):
    """Reject broken provenance/relations; return lexical hints, never token errors.

    Leftover Korean tokens cannot establish missing meaning: request framing,
    grammatical endings and particles also remain after substring subtraction.
    """
    if not scene or not (scene['relations'] or scene['details']):
        raise ValueError('Scene plan has no relation or scene detail')
    for slot in [p for r in scene['relations'] for p in r.values()] + scene['details'] + scene['exclusions']:
        if bool(slot['en'].strip()) != bool(slot['quote'].strip()):
            raise ValueError('Every translated scene field needs an exact source quote; invalid field: ' + repr(slot))
        if slot['quote'] and not any(slot['quote'] in s for s in sources):
            raise ValueError('Scene evidence is not an exact user quote: ' + slot['quote'])
        if re.search(r'[가-힣]|--(?:ar|v|style)\b|[\n`]', slot['en']):
            raise ValueError('Scene fields must be plain English without provider switches')
    for r in scene['relations']:
        if not r['subject']['en'] or not r['action']['en']:
            raise ValueError('Each relation needs an actor and action')
        if re.fullmatch(r'(?:the |a )?(?:rain|snow|street|background|sky|forest)', r['subject']['en'], re.I):
            raise ValueError('Put weather and setting in scene.details, not actor relations: ' + r['subject']['en'])
        if re.fullmatch(r'[a-z]+ing', r['action']['en'], re.I):
            raise ValueError('Use a finite action with its target preposition, e.g. walks along, not ' + r['action']['en'])
        # Target and subject particles catch the reported reversal and its inverse.
        # Restrict the check to the action's source sentence, not unrelated memory.
        sentences = [part for s in sources for part in re.split(r'[\n.!?]', s)
                     if r['action']['quote'] in part and r['subject']['quote'] in part]
        for part in sentences[:1]:
            viewer = r'(?:viewer|관찰자|카메라)'
            if re.search(viewer + r'(?:을|를)\s*(?:조준|겨누|바라|쳐다)', part, re.I):
                if not re.search(r'viewer|camera|observer', r['target']['en'], re.I):
                    raise ValueError('The original explicitly makes viewer the target')
            if re.search(viewer + r'(?:가|는)\s+.*(?:조준|겨누)', part, re.I):
                if not re.search(r'viewer|camera|observer', r['subject']['en'], re.I):
                    raise ValueError('The original explicitly makes viewer the actor')
    # A small, explicit bilingual guard for high-impact modifiers. This is not
    # advertised as proof of arbitrary translation fidelity.
    slots = [p for r in scene['relations'] for p in r.values()] + scene['details'] + scene['exclusions']
    for slot in slots:
        for korean, english in [(r'대물\s*(?:저격총|소총)', r'anti[- ]materiel'),
                                (r'거대한', r'giant|huge|massive|colossal|enormous')]:
            if re.search(korean, slot['quote']) and not re.search(english, slot['en'], re.I):
                raise ValueError('Missing precise translation of ' + slot['quote'] + ': expected ' + english)
    # These weak hints can prompt one optional review, not rejection/retry loops.
    remaining = sources[0]
    remaining = re.sub(r'[^,.!?]*(?:그대로)\s*유지하고[, ]*', '', remaining)
    for slot in slots:
        if slot['quote']:
            remaining = remaining.replace(slot['quote'], ' ')
    if any(p['quote'] == '비' and re.search(r'\brain', p['en'], re.I) for p in slots) and '비 오는' in sources[0]:
        remaining = re.sub(r'\b오는\b', ' ', remaining)
    meta = r'프롬프트\w*|구도\w*|장면\w*|만들\w*|구성\w*|작성\w*|추천\w*|어떻게|할까요|해줘\w*|해주\w*|바꿔\w*|수정\w*|주세요|제외\w*|추가\w*|이전|조건\w*|유지\w*'
    remaining = re.sub(meta, ' ', remaining)
    particles = {'이','가','을','를','은','는','의','에','에게','에서','으로','로','와','과','하고','하는','있는','고','좀','만','도'}
    missing = [t for t in re.findall(r'[가-힣]+', remaining) if t not in particles]
    return list(dict.fromkeys(missing))[:10]


def repair_explicit_direction(scene, text):
    """Correct only an unambiguous particle-marked swap of the two existing roles."""
    notes = []
    if not scene:
        return notes
    for r in scene['relations']:
        is_viewer = lambda p: bool(re.fullmatch(r'(?:the )?(?:viewer|camera|observer)', p['en'].strip(), re.I))
        target_marked = re.search(r'(?:viewer|관찰자|카메라)(?:을|를)\s*(?:조준|겨누|바라|쳐다)', text, re.I)
        other = re.escape(r['subject']['quote'])
        subject_marked = r['subject']['quote'] and re.search(r'(?:viewer|관찰자|카메라)(?:가|는)\s+' + other + r'(?:을|를)\s*(?:조준|겨누)', text, re.I)
        if ((target_marked and is_viewer(r['subject']) and r['target']['en']) or
                (subject_marked and is_viewer(r['target']) and not is_viewer(r['subject']))):
            r['subject'], r['target'] = r['target'], r['subject']
            notes.append('Corrected swapped actor/target using explicit original Korean particles')
    return notes


def repair_source_terms(scene):
    """Small explicit terminology table; modify only the quoted instrument."""
    notes = []
    for r in (scene or {}).get('relations', []):
        slot = r['instrument']
        if re.search(r'대물\s*(?:저격총|소총)', slot['quote']) and re.search(r'\brifle\b', slot['en'], re.I):
            if not re.search(r'anti[- ]materiel', slot['en'], re.I):
                slot['en'] = re.sub(r'\b(?:sniper )?rifle\b', 'anti-materiel sniper rifle', slot['en'], flags=re.I)
                notes.append('Preserved 대물 저격총 as anti-materiel sniper rifle on the instrument')
        if '거대한' in slot['quote'] and slot['en'] and not re.search(r'giant|huge|massive|colossal|enormous', slot['en'], re.I):
            slot['en'] = 'giant ' + re.sub(r'^(?:a|an|the)\s+', '', slot['en'], flags=re.I)
            notes.append('Restored the explicitly quoted instrument size')
    return notes


def complete_searches(scene, searches):
    """Keep model searches and cover explicitly supplied actors/objects/details."""
    queries = [s['query'] for s in searches if s['source'] == 'tag']
    for r in scene['relations']:
        subject = re.sub(r'^(?:a|an|the)\s+', '', r['subject']['en'], flags=re.I)
        queries.append({'girl':'1girl', 'boy':'1boy'}.get(subject.lower(), subject))
        queries.append(r['instrument']['en'])
    queries.extend(d['en'] for d in scene['details'])
    unique = []
    for query in queries:
        query = re.sub(r'^(?:a|an|the)\s+', '', query, flags=re.I).strip()
        if query and query.lower() not in {s['query'].lower() for s in unique}:
            unique.append({'source': 'tag', 'query': query[:160]})
    return unique[:6]


def core_prompt(scene):
    if scene.get('description_en'):
        return scene['description_en'].strip()
    parts = []
    for r in scene['relations']:
        phrase = ' '.join(r[k]['en'].strip() for k in ('subject', 'action', 'target') if r[k]['en'].strip())
        if r['instrument']['en']:
            direct_object = not r['target']['en'] and r['action']['en'].strip().lower() in {'wears', 'holds', 'carries', 'uses'}
            phrase += (' ' if direct_object else ', using ') + r['instrument']['en'].strip()
        parts.append(phrase[0].upper() + phrase[1:].rstrip('.') + '.')
    parts.extend(p['en'].strip()[0].upper() + p['en'].strip()[1:].rstrip('.') + '.' for p in scene['details'] if p['en'].strip())
    return ' '.join(dict.fromkeys(parts))


def candidates_from(trace):
    candidates = {}
    for event in trace:
        if event['status'] != 'ok' or event['name'] != 'search_tags':
            continue
        for row in event.get('result', {}).get('items', []):
            if row.get('tag'):
                candidates[row['tag']] = row
    return candidates


def relevant_candidates(scene, candidates):
    """Conservative lexical support plus directed-viewer checks, not semantic proof.

    Missing synonyms stay unselected; the complete English source-backed scene
    remains in the answer even when this intentionally narrow tag gate abstains.
    """
    def concepts(text):
        words = re.findall(r'[a-z]+|\d+', text.lower().replace('1girl', 'girl').replace('1boy', 'boy'))
        stop = {'a', 'an', 'the', 'at', 'on', 'in', 'of', 'with', 'using', 'to', 'towards', 'along', 'and'}
        result = set()
        for word in words:
            if word in stop:
                continue
            word = {'rainy':'rain', 'snowy':'snow'}.get(word, word)
            if word.endswith('ing') and len(word) > 5:
                word = word[:-3]
                if len(word) > 2 and word[-1] == word[-2]:
                    word = word[:-1]
            elif word.endswith(('xes', 'ches', 'shes', 'zes')):
                word = word[:-2]
            elif word.endswith('s') and len(word) > 3 and not word.endswith('ss'):
                word = word[:-1]
            result.add(word)
        return result
    positive = concepts(core_prompt(scene))
    actions = set().union(*(concepts(r['action']['en']) | concepts(r['target']['en']) for r in scene['relations']))
    kept = {}
    for tag, row in candidates.items():
        normalized = tag.lower().replace('_', ' ')
        words = concepts(normalized)
        if not words or not words <= positive:
            continue
        if row.get('group') == 'Expression_Action' and not words <= actions:
            continue
        if re.search(r'(?:at|towards) viewer', normalized):
            if not any('viewer' in concepts(r['target']['en']) and
                       (words - {'viewer'}) <= concepts(r['action']['en']) for r in scene['relations']):
                continue
        kept[tag] = row
    return kept


def render_scene(scene, selection, candidates):
    """The model selects supported tags; it cannot rewrite the protected relation."""
    normalize = lambda s: s.lower().replace('_', ' ').strip()
    spelling = {normalize(tag): tag for tag in candidates}
    selected = [spelling.get(normalize(tag), tag) for tag in selection['tags']]
    if len(selected) != len(set(selected)) or any(tag not in candidates for tag in selected):
        raise ValueError('Selected tags must be unique exact spellings from search results')
    # Excluded concepts cannot re-enter as positive tags by exact name.
    excluded = {normalize(p['en']) for p in scene['exclusions']}
    if any(normalize(tag) in excluded for tag in selected):
        raise ValueError('An excluded concept was selected as a positive tag')
    lines = ['**구도 중심 영문 프롬프트**', core_prompt(scene)]
    if selected:
        lines += ['', '**검색에서 확인한 태그 후보**', ', '.join(selected)]
    else:
        lines += ['', '이번 검색에서는 조건에 맞는 태그를 확정하지 못했습니다.']
    if scene['exclusions']:
        lines += ['', '**제외 조건**', ', '.join(p['en'] for p in scene['exclusions'])]
    lines += ['', '영문 문장은 구도 설명이고, 태그 후보는 별도로 조합할 수 있습니다. 태그만으로 방향과 크기가 충분히 표현되는지는 생성 결과에서 확인해야 합니다.']
    return '\n'.join(lines)
