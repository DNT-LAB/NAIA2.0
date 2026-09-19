"""Bounded lexical retrieval helpers; candidates never redefine user intent."""
import re

STOP = set('a an the on in at to of for with and or is are be being by from into through while it its'.split())


def normalize(text):
    return ' '.join(text.casefold().replace('_', ' ').split())


def english_words(text):
    return [w for w in re.findall(r'[a-z0-9]+', normalize(text)) if w not in STOP]


def stem(word):
    # Inflections only, not semantic synonyms (escape != struggling).
    irregular = {'carried':'carry', 'carrying':'carry', 'carries':'carry', 'kneeling':'kneel',
                 'kneels':'kneel', 'struggling':'struggle', 'struggles':'struggle',
                 'firing':'fire', 'fires':'fire', 'walking':'walk', 'walks':'walk',
                 'holding':'hold', 'holds':'hold', 'sitting':'sit', 'sits':'sit'}
    return irregular.get(word, word[:-1] if len(word) > 3 and word.endswith('s') and not word.endswith('ss') else word)


def korean_terms(text):
    terms = []
    for word in re.findall(r'[가-힣]+', text):
        stripped = re.sub(r'(?:에서는|으로는|에게서|에서|에게|으로|에는|까지|부터|처럼|보다|은|는|이|가|을|를|에|의|와|과|도)$', '', word)
        # Don't turn 소녀 into a fabricated translation; these are lookup keys.
        if len(stripped) >= 2 and stripped not in terms:
            terms.append(stripped)
    return terms[:8]


def query_variants(query, query_ko, entry_for):
    primary = normalize(query)
    en, ko = [], []
    def add(target, term):
        if term and len(term) <= 240 and term not in target and len(target) < 8:
            target.append(term)
    if re.search('[가-힣]', primary):
        add(ko, primary)
    else:
        add(en, primary)
    words = re.findall(r'[a-z0-9]+', primary)
    # Exact compounds before exact atoms. Do not query ambiguous prefixes such
    # as giant -> giantess merely because a longer phrase had no hits.
    for width in range(min(3, len(words)), 0, -1):
        for start in range(len(words) - width + 1):
            term = ' '.join(words[start:start + width])
            if term not in STOP and entry_for(term):
                add(en, term)
    aliases = {'girl':'1girl', 'a girl':'1girl', 'boy':'1boy', 'a boy':'1boy'}
    if primary in aliases and entry_for(aliases[primary]):
        add(en, aliases[primary])
    for text in (query_ko, query if re.search('[가-힣]', query) else ''):
        add(ko, text.strip())
        for term in korean_terms(text):
            add(ko, term)
    return en, ko


def negative_requirement(item):
    return bool(re.search(r'\b(?:no|without|exclude|excluding|not|avoid)\b', item.get('en', ''), re.I)
                or re.search(r'제외|말고|금지|하지\s*마|빼\s*줘', item.get('quote', '')))


def sourced_retrieval_intent(intent, sources):
    """Salvage independently sourced concepts, never a failed full scene plan."""
    return {'must_keep': [dict(en=r['en'], quote=r['quote']) for r in intent.get('must_keep', [])
                          if r['en'].strip() and r['quote'].strip() and any(r['quote'] in s['user'] for s in sources)],
            'searches': []}


def negative_source_text(original):
    # Conservative literal exclusions, also used when no parsed intent survived.
    parts = re.findall(r'\b(?:without|exclude|excluding|avoid|no)\s+([^,.!?;]+)', original, re.I)
    parts += re.findall(r'([가-힣A-Za-z0-9_-]+)\s*(?:제외|말고|금지|빼\s*줘)', original)
    parts += re.findall(r'([가-힣A-Za-z0-9_-]+(?:\s+[가-힣A-Za-z0-9_-]+)?)\s*하지\s*마', original)
    return ' '.join(parts)


def keyword_supported(row, source):
    """A dictionary keyword bridge is retrieval evidence, not a locked fact."""
    source = normalize(source)
    return any(normalize(k) in source for k in row.get('matched_keywords', []) if normalize(k))


def retrieval_plan(intent, original, *, include_source_terms=False):
    """Pair each sourced English concept with Korean; reserve two event slots."""
    plan, seen = [], set()
    if intent.get('interpretation_kind') == 'creative_scene_v9' and original.strip():
        # Independently search the original before translated/proposed details.
        # A bad translation must not erase the original object's dictionary hit.
        plan.append({'query': original[:160], 'query_ko': original[:240], 'limit': 6})
        seen.add(normalize(original[:160]))
        goal = intent.get('goal', '').strip()[:160]
        if goal and normalize(goal) not in seen:
            # A followup's original may say only "change that pose". Keep an
            # English core lookup even when the model routes all hints elsewhere.
            plan.append({'query':goal, 'query_ko':original[:240], 'limit':6})
            seen.add(normalize(goal))
    if intent.get('interpretation_kind') in {'sentence_relations_v8', 'creative_scene_v9'}:
        # The model interprets the sentence first; lookup hints no longer depend
        # on recreating Korean substrings or splitting every constraint apart.
        for search in intent.get('searches', []):
            if search['source'] == 'tag' and normalize(search['query']) not in seen:
                plan.append({'query': search['query'], 'query_ko': search.get('query_ko', ''), 'limit': 6})
                seen.add(normalize(search['query']))
        if plan:
            return plan[:6 if intent.get('interpretation_kind') == 'creative_scene_v9' else 4]
    for item in intent.get('must_keep', []):
        if negative_requirement(item):
            continue
        en = item['en'][:160]
        ko = item.get('quote', '')[:240] or (original[:160] if intent.get('interpretation_kind') and re.search('[가-힣]', original) else '')
        key = normalize(en)
        if key not in seen:
            plan.append({'query': en, 'query_ko': ko, 'limit': 6})
            seen.add(key)
    for search in intent.get('searches', []):
        if search['source'] == 'tag' and normalize(search['query']) not in seen:
            plan.append({'query': search['query'], 'limit': 6})
            seen.add(normalize(search['query']))
    if not plan or include_source_terms:
        # Broken extraction can still perform lexical lookup from the user's
        # literal words. This is retrieval, not a guessed translation/intent.
        terms = korean_terms(original)
        plan += [{'query': term, 'limit': 6} for term in terms[:6] if normalize(term) not in seen]
        if not plan and original.strip():
            plan = [{'query': original[:160], 'limit': 6}]
    return plan[:6]


def phrase_present(tag, text):
    words = [stem(w) for w in re.findall(r'[a-z0-9]+', normalize(text))]
    phrase = [stem(w) for w in re.findall(r'[a-z0-9]+', normalize(tag))]
    return bool(phrase) and any(words[i:i + len(phrase)] == phrase for i in range(len(words)))


def canonical_present(tag, text):
    if phrase_present(tag, text):
        return True
    word = {'1girl':'girl', '1boy':'boy'}.get(normalize(tag))
    return bool(word and re.search(r'\b' + word + r'\b', normalize(text)))


def event_pin_candidates(candidates, intent, original=''):
    positive = positive_text(intent)
    negative = ' '.join(item['en'] for item in intent.get('must_keep', []) if negative_requirement(item))
    source = ' '.join(item.get('quote', '') for item in intent.get('must_keep', []) if not negative_requirement(item)) + ' ' + original
    excluded_source = negative_source_text(original) + ' ' + negative_source_text(intent.get('goal', '')) + ' ' + ' '.join(item.get('quote', '') for item in intent.get('must_keep', []) if negative_requirement(item))
    ranked = []
    for tag, row in candidates.items():
        if canonical_present(tag, negative) or canonical_present(tag, excluded_source) or keyword_supported(row, excluded_source):
            continue
        direct = canonical_present(tag, positive)
        # Failed extraction: only exact lexical hits, never a loose neighbour.
        keyword_match = keyword_bridge(tag, row, candidates, source, intent)
        if not direct and not keyword_match and not (not positive and row.get('match_kind') == 'exact'):
            continue
        action = any(stem(w) in {'carry','struggle','hold','walk','sit','fire','kneel','hug','run','ride','stand'} for w in english_words(tag))
        generic = normalize(tag) in {'1girl','1boy','girl','boy','solo','male','female'}
        ranked.append((action, not generic, row.get('match_kind') == 'exact', tag))
    ranked.sort(key=lambda item: item[:3], reverse=True)
    return [item[3] for item in ranked]


def positive_text(intent):
    intent = intent or {}
    facts = ' '.join(r['en'] for r in intent.get('must_keep', []) if not negative_requirement(r))
    return (facts + ' ' + (intent.get('goal', '') if intent.get('interpretation_kind') else '')).strip()


def unambiguous_keyword(tag, row, candidates, source):
    """A generic Korean alias shared by different meanings is not enough."""
    for keyword in row.get('matched_keywords', []):
        if not keyword_supported({'matched_keywords': [keyword]}, source):
            continue
        matches = [name for name, other in candidates.items()
                   if any(normalize(k) == normalize(keyword) for k in other.get('matched_keywords', []))]
        # A compound such as tissue box must not inherit the broad box keyword.
        if len(matches) == 1 or all(name == tag or phrase_present(tag, name) for name in matches):
            return True
    return False


def keyword_bridge(tag, row, candidates, source, intent):
    if (intent or {}).get('interpretation_kind'):
        return keyword_supported({'matched_keywords': row.get('unambiguous_keywords', [])}, source)
    return row.get('match_kind') == 'keyword_exact' and unambiguous_keyword(tag, row, candidates, source)


def evidence_catalog(trace, candidates, limit=18, intent=None, original=''):
    if (intent or {}).get('interpretation_kind') == 'creative_scene_v9':
        from tools.e2b_chat_lab.creative_retrieval import creative_catalog
        return creative_catalog(trace, candidates, intent, original, limit)
    events = [t for t in trace if t['name'] == 'event_map']
    positive = positive_text(intent)
    # After design, its explicit pose/action can also be converted to tags.
    # Before design only user requirements admit candidates, so a loose search
    # neighbour cannot become a new prop just by appearing in the catalog.
    design = (intent or {}).get('design', {})
    positive += ' ' + ' '.join(design.get(k, '') for k in ('stance_en','body_en','left_hand_en','right_hand_en','camera_en','action_en','scene_en'))
    positive = positive.strip()
    terms = {stem(w) for w in english_words(positive)}
    source = ' '.join(r.get('quote', '') for r in (intent or {}).get('must_keep', []) if not negative_requirement(r)) + ' ' + original
    excluded_source = negative_source_text(original) + ' ' + negative_source_text((intent or {}).get('goal', ''))
    negative = ' '.join(r['en'] for r in (intent or {}).get('must_keep', []) if negative_requirement(r))
    def relevant(tag, row):
        if keyword_supported(row, excluded_source) or canonical_present(tag, excluded_source) or canonical_present(tag, negative):
            return False
        if keyword_bridge(tag, row, candidates, source, intent):
            return True
        if not positive:
            return row.get('match_kind') == 'exact'
        if phrase_present(tag, positive) or (tag == '1girl' and 'girl' in terms) or (tag == '1boy' and 'boy' in terms):
            return True
        # A description bridge can expose e.g. carrying over shoulder. A loose
        # shoulder/bag match or fruit/basket neighbour must not add a new prop.
        return (row.get('match_kind') == 'english_description' and
                len({stem(w) for w in english_words(tag)} & terms) >= 2)
    rows = sorted(((tag, row) for tag, row in candidates.items() if relevant(tag, row)), key=lambda pair: (phrase_present(pair[0], positive),
                  pair[1].get('match_kind') == 'exact', pair[1].get('origin', '').startswith('Event Map')), reverse=True)
    return {'items': [dict(tag=tag, meaning_en=row.get('description_en', '')[:180],
                          meaning_ko=row.get('desc', '')[:120], origin=row.get('origin', 'TagSearchIndex'),
                          matched_user_keywords=[k for k in row.get('unambiguous_keywords', []) if normalize(k) in normalize(source)],
                          translation_status=row.get('translation_status', 'unavailable'))
                      for tag, row in rows[:limit]],
            'event_queries': [{'pins': t['arguments']['pins'], 'status': t['status'],
                               'observed_posts': t.get('result', {}).get('observed_posts'),
                               'error': t.get('result', {}).get('error', '')} for t in events],
            'omitted_unrelated_candidates': len(candidates) - len(rows),
            'note': 'Candidates only. Co-occurrence does not establish meaning, actor direction or consent. Preserve user roles and exclusions.'}
