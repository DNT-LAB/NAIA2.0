"""Small reviewed Chat vocabulary, independent of shared Search/autocomplete.

Origins are local dictionary records reviewed on 2026-09-05. These are lexical
senses, not inferred co-occurrence rules or an exhaustive Korean parser.
"""
from __future__ import annotations

import copy
import re

VERSION = "chat-senses-20260905-v1"


def _sense(key, tags, aliases, meaning, *, source="merged_tag_record", scope="general", support=()):
    return {"id": key, "tags": list(tags), "aliases": list(aliases), "meaning": meaning,
            "source": source, "scope": scope, "support": list(support)}


# A lexical alias is reviewed here; raw keywords_kr labels are never promoted
# into this list automatically. Source excerpts/hashes live in the audit report.
SENSES = (
    _sense("anatomy.knot", ["knot"], ["매듭 성기", "개과 성기", "bulbus glandis"],
           "해부학적 매듭 구조", source="e621_data:General/NSFW/knot", scope="anatomy"),
    _sense("object.flower_knot", ["flower knot"], ["꽃매듭", "꽃 모양 매듭", "flower knot", "floral knot"], "꽃 모양으로 묶은 끈·리본"),
    _sense("anatomy.sheath", ["sheath"], ["해부학적 쉬스", "anatomical sheath"],
           "일부 포유류의 성기를 보호하는 피부 구조", source="e621_data:General/NSFW/sheath", scope="anatomy"),
    _sense("object.scabbard", ["scabbard", "sheath"], ["칼집", "검집", "scabbard", "sword sheath"], "칼을 넣어 보관하는 덮개", scope="weapon"),
    _sense("state.covered_bulge", ["bulge"], ["꼬툭튀", "bulge", "clothed bulge"], "의복 아래에서 드러나는 돌출 형태"),
    _sense("state.exposed_penis", ["penis out"], ["페니스 노출", "의복 밖 노출", "penis out"], "의복 밖으로 노출된 신체 부위"),
    _sense("action.oral", ["oral", "fellatio"], ["구강성교", "오랄섹스", "펠라치오", "oral sex", "fellatio"], "구강 행위 분류"),
    _sense("action.intercourse", ["sex"], ["삽입성교", "섹스", "sex", "intercourse"], "질·항문 성교 분류"),
    _sense("action.masturbation", ["masturbation", "male masturbation", "female masturbation", "penile masturbation"],
           ["자위", "딸딸이", "마스터베이션", "masturbation"], "자위 행위 분류"),
    _sense("body.breasts", ["breasts"], ["가슴", "유방", "슴가", "breasts"], "가슴 부위; 크기·행동은 별도"),
    _sense("body.penis", ["penis"], ["음경", "페니스", "쥬지", "penis"], "신체 부위; 발기·노출·행위는 별도"),
    _sense("state.topless", ["topless", "topless male", "topless female"],
           ["상의 없음", "상반신만 탈의", "상반신 탈의", "상의 탈의", "탑리스", "topless"],
           "상의를 착용하지 않은 상태; 하의 여부와 별개", support=["human", "upper body", "lower body"]),
    _sense("state.nude", ["nude", "completely nude"], ["나체", "누드", "nude", "naked"], "가슴과 사타구니에 옷이 없는 상태"),
    _sense("state.erection", ["erection"], ["발기", "erection"], "발기 상태"),
    _sense("detail.large_breasts", ["large breasts"], ["큰 가슴", "거유", "large breasts"], "큰 가슴 크기"),
    _sense("detail.huge_breasts", ["huge breasts"], ["거대한 가슴", "huge breasts"], "매우 큰 가슴 크기"),
    _sense("action.breast_grab", ["breast grab", "breast fondling"], ["가슴 잡기", "유방 쥐기", "breast grab", "breast fondling"], "가슴을 손으로 잡는 행위"),
    _sense("person.male", ["male"], ["남성", "남자", "male"], "남성 분류"),
    _sense("person.female", ["female"], ["여성", "여자", "female"], "여성 분류"),
    _sense("object.gift", ["gift"], ["선물", "선물상자", "gift", "present object"], "건네는 선물 물건"),
    _sense("meta.gift_art", ["gift art"], ["선물 그림", "gift art"], "선물로 제작한 그림의 메타 분류"),
)
BY_ID = {s["id"]: s for s in SENSES}
REFINEMENTS = {'fellatio': 'person.male', 'male masturbation': 'person.male',
               'penile masturbation': 'person.male', 'female masturbation': 'person.female',
               'topless male': 'person.male', 'topless female': 'person.female'}
AMBIGUOUS = {"매듭": ("anatomy.knot", "object.flower_knot"),
             "knot": ("anatomy.knot", "object.flower_knot"),
             "쉬스": ("anatomy.sheath", "object.scabbard"),
             "sheath": ("anatomy.sheath", "object.scabbard")}


def norm(text):
    return re.sub(r"\s+", " ", str(text or "").replace("_", " ").strip().casefold())


def korean_spacing_key(normalized_text):
    """Whole-keyword spacing only; callers normalize with Search's contract.

    English/mixed text, punctuation and separated numbers are not eligible.
    Equal keys are spelling evidence, never a certification of shared meaning.
    """
    text = str(normalized_text or "")
    if (not re.fullmatch(r"[가-힣0-9 ]+", text) or not re.search(r"[가-힣]", text)
            or re.search(r"[0-9] +[0-9]", text)):
        return ""
    return text.replace(" ", "")


def alias_senses(query):
    query = norm(query)
    ids = set(AMBIGUOUS.get(query, ()))
    ids.update(s["id"] for s in SENSES if query in map(norm, s["aliases"]))
    return [copy.deepcopy(BY_ID[key]) for key in sorted(ids)]


def tag_senses(tag):
    return [{k: copy.deepcopy(s[k]) for k in ("id", "meaning", "source", "scope")}
            for s in SENSES if norm(tag) in s["tags"]]


def annotate(row, query):
    return {**row, "search_query": query, "semantic_senses": tag_senses(row["tag"]),
            "semantic_version": VERSION}


def _matches(text):
    hits = []
    aliases = {alias for s in SENSES for alias in s["aliases"]} | set(AMBIGUOUS)
    for alias in aliases:
        # Korean particles can adjoin a term; English words cannot be substrings.
        pattern = re.escape(norm(alias)).replace(r"\ ", r"\s+")
        if re.search(r"[a-z]", alias):
            pattern = r"(?<![a-z0-9])" + pattern + r"(?![a-z0-9])"
        for match in re.finditer(pattern, text):
            hits.append((match.start(), match.end(), norm(alias)))
    chosen = []
    for hit in sorted(hits, key=lambda h: (-(h[1]-h[0]), h[0], h[2])):
        if not any(hit[0] < h[1] and hit[1] > h[0] for h in chosen):
            chosen.append(hit)
    return sorted(chosen)


def request_requirements(source):
    """Conservative clause/longest-term matching; no model-generated evidence."""
    text = "\n".join(norm(line) for line in str(source or '').splitlines())
    clauses = re.split(r"[.!?\n,;]+|(?<=아니고)|(?<=말고)|(?<=대신)", text)
    positive, negative, ambiguous = {}, {}, []
    parsed = []
    for clause in clauses:
        hits = _matches(clause)
        # Negation contained in an alias (상의 없음) is part of that concept.
        remainder = clause
        for start, end, _ in reversed(hits):
            remainder = remainder[:start] + " "*(end-start) + remainder[end:]
        denied = bool(re.search(r"아니|않|말고|대신|제외|단정하지|추정하지|생략|\b(?:not|without|exclude|excluding|no)\b", remainder))
        parsed.append((clause, hits, denied))
    affirmations = " ".join(c for c, _, denied in parsed if not denied)
    anatomy = bool(re.search(r"해부학|신체|anatom|\bbody\b", affirmations))
    weapon = bool(re.search(r"칼집|검집|무기|\bsword\b|\bweapon\b|scabbard", affirmations))
    floral = bool(re.search(r"꽃매듭|꽃 모양|flower|floral", affirmations))
    for clause, hits, denied in parsed:
        for _, _, alias in hits:
            senses = alias_senses(alias)
            if alias in AMBIGUOUS:
                if denied:
                    # A denied ambiguous word cannot exclude a sense inferred
                    # from a different affirmative clause.
                    continue
                if anatomy and not weapon:
                    senses = [s for s in senses if s['scope'] == 'anatomy']
                elif weapon and not anatomy:
                    senses = [s for s in senses if s['scope'] == 'weapon']
                elif floral and not anatomy:
                    senses = [s for s in senses if s['id'] == 'object.flower_knot']
                elif 'e621' in affirmations and not weapon and not floral:
                    senses = [s for s in senses if s['scope'] == 'anatomy']
                elif not denied:
                    ambiguous.append(alias)
                    continue
                else:
                    # A denied ambiguous word cannot exclude all of its senses.
                    continue
            for sense in senses:
                (negative if denied else positive)[sense['id']] = alias
    return {"positive": positive, "negative": negative, "ambiguous": sorted(set(ambiguous)),
            "version": VERSION}


def request_hint(requirements):
    return {"scope": "Reviewed lexical meanings only, not a complete scene parser",
            "requested": [{"id": key, "term": term, "meaning": BY_ID[key]['meaning'],
                           "search": BY_ID[key]['tags']} for key, term in requirements['positive'].items()],
            "excluded": list(requirements['negative']), "ambiguous": requirements['ambiguous']}


def assess_scene(source, scene, ledger):
    req = request_requirements(source)
    selected = list(dict.fromkeys(norm(t) for t in scene['common_tags'] +
                                 [t for a in scene['actors'] for t in a['tags']]))
    requested = set(req['positive'])
    allowed = {t for key in requested for t in BY_ID[key]['tags'] + BY_ID[key]['support']}
    excluded = {t for key in req['negative'] for t in BY_ID[key]['tags']}
    issues, rejected, unreviewed = [], [], []
    for key in sorted(requested.intersection(req['negative'])):
        issues.append({'code': 'contradictory_request', 'concept': key,
                       'message': '같은 뜻의 포함·제외 조건이 겹칩니다. 요청 범위를 확인해주세요.'})
    for tag in selected:
        senses = tag_senses(tag)
        refinement = REFINEMENTS.get(tag)
        # A named subtype is usable when explicitly requested; a broad concept
        # alone does not establish its gender/role refinement.
        explicit_tag = bool(re.search(r'(?<![a-z])' + re.escape(tag) + r'(?![a-z])', norm(source)))
        # A source-dependent token (sheath) can name both a requested sense and
        # an excluded sense. Its reviewed positive sense wins over token overlap.
        if (tag in excluded and tag not in allowed) or (requested and senses and tag not in allowed) or (
                refinement and refinement not in requested and not explicit_tag):
            rejected.append(tag)
            issues.append({"code": "conflicting_tag", "tag": tag,
                           "message": f"요청에 없는 뜻이나 제외한 상태가 포함됨: {tag}"})
        elif not senses and tag not in allowed:
            unreviewed.append(tag)
    for key in sorted(requested):
        if not set(BY_ID[key]['tags']).intersection(set(selected)-set(rejected)):
            issues.append({"code": "missing_concept", "concept": key,
                           "message": f"뜻을 확인할 태그가 필요함: {BY_ID[key]['meaning']}",
                           "search": BY_ID[key]['tags']})
    for alias in req['ambiguous']:
        issues.append({"code": "ambiguous_sense", "term": alias,
                       "message": f"어떤 뜻인지 확인이 필요함: {alias}"})
    # Label-only evidence must not become semantic proof via exact tag lookup.
    for tag in selected:
        evidence = ledger.get(tag, {}).get('evidence', [])
        label_only = evidence and all(e.get('keyword_origin') == 'label' or e.get('origin') == 'validation' for e in evidence)
        if label_only and not tag_senses(tag) and tag not in unreviewed:
            unreviewed.append(tag)
    for tag in unreviewed:
        issues.append({"code": "unreviewed_tag", "tag": tag, "message": f"의미 검토 자료가 없는 태그: {tag}"})
    if not requested:
        issues.append({"code": "unreviewed_request", "message": "이 요청은 아직 의미 검토 범위 밖입니다."})
    # An omitted graph must not turn an unreviewed directed request into a
    # completed lexical result. Keep this conservative, not a role inference.
    if scene['relations'] or re.search(r'(?:에게|한테|더러)(?=\s|$)', str(source)):
        issues.append({"code": "unreviewed_roles", "message": "인물별 행동 역할은 추가 확인이 필요합니다."})
    if re.search(r'분류|정규화|용어|명칭|사전 태그|classification|terminology', norm(source)):
        for actor in scene['actors']:
            name = actor['name'].strip()
            mentioned = name and re.search(re.escape(name) + r'\s*(?:이|가|은|는|에게|한테|을|를)', source)
            identity = any(ledger.get(norm(t), {}).get('source') == 'search_characters' for t in actor['tags'])
            if not mentioned and not identity:
                issues.append({'code': 'unexpected_actor', 'actor_id': actor['id'],
                    'message': '용어 분류에 요청하지 않은 인물이 추가되었습니다. 인물 없이 공통 태그로 정리하세요.'})
    return {"status": "partial" if issues else "complete", "scope": VERSION,
            "requirements": request_hint(req), "issues": issues, "rejected_tags": rejected,
            "repairable": any(i['code'] in {'conflicting_tag', 'missing_concept', 'unexpected_actor'} for i in issues),
            "ambiguous": req['ambiguous']}


def assessed_result(source, scene, ledger):
    review = assess_scene(source, scene, ledger)
    safe = copy.deepcopy(scene)
    rejected = set(review['rejected_tags'])
    safe['common_tags'] = [t for t in safe['common_tags'] if norm(t) not in rejected]
    for actor in safe['actors']:
        actor['tags'] = [t for t in actor['tags'] if norm(t) not in rejected]
    safe['interpretations'] = [{"source": item['term'], "meaning": "요청한 뜻: " + item['meaning']}
                               for item in review['requirements']['requested']]
    labels = [item['meaning'] for item in review['requirements']['requested']]
    message = ("검토한 의미: " + "; ".join(labels)) if review['status'] == 'complete' else "요청의 의미를 모두 확인하지 못했습니다. 확인이 필요한 내용을 표시했습니다."
    return {"ok": True, "type": "scene_agent", "scene": safe, "message": message,
            "completion": review['status'], "semantic_review": review}
