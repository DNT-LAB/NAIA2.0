# -*- coding: utf-8 -*-
"""성인 '행위' 도감 — wildcards/nsfw/nsfw_{act}.txt.

**이미지를 만들지 않는다.** 목록만 정리한다(기존 build_nsfw_catalog.py 와 같은 방침).

## 왜 이게 따로 필요한가

`SLOT_GROUPS` 는 여섯 그룹(Person_Body / Clothing_Wear / Expression_Action /
Composition_Meta / Location_Background / Food_Object)만 읽는다. **`NSFW` 그룹은
어느 슬롯에도 매핑돼 있지 않아** 분류 파이프라인이 한 번도 읽은 적이 없다.
그래서 `sex`(149,518) · `vaginal`(108,348) · `fellatio`(35,024) 같은 것이
어디에도 없었다. 기존 도감 245개는 SFW 그룹에 섞여 있던 것을 정규식으로 걸러낸
전혀 다른 경로의 결과물이다.

## 어디까지 담는가

  · `source == KR_tags` 만. NSFW 그룹 4,020개 중 760개다. 나머지 3,260개는
    e621 계열 어휘(`anthro penetrated` · `equine genitalia` · `gynomorph`)로,
    Danbooru 학습 모델이 제대로 그리지 못한다.
  · freq >= 149 (다른 축과 같은 절단선)
  · 기존 도감 245개와 겹치는 것은 뺀다 — 팩 키는 `<축>/<태그>` 하나뿐이라
    두 축에 같은 태그가 있으면 뒤쪽 축이 영영 안 찬다(실측 `bandages`).

## 무엇을 빼는가

  · 서브그룹 `taboo` / `gore` / `dark_content` (사용자 지시)
    - taboo   강간 · 아동 · 근친 · 구로 · 료나 · 자해 · vore
    - gore    유혈 · 신체 훼손
    - dark_content 자살 · 살인 · 고문 · 학대
  · 위 서브그룹을 피해 남은 것 중 이름으로 걸리는 11개
    (rape / shota / onee-shota / incest / sleep molestation / forced* / ryona / urine meter)
    서브그룹 분류가 완전하지 않아 이름 규칙이 한 겹 더 필요하다.
"""
import json
import re
from pathlib import Path

OUT = Path("wildcards/nsfw")
CUT = 149

# 서브그룹 단위 제외.
SKIP_SUBGROUP = {"taboo", "gore", "dark_content"}

# 이 빌더의 풀 밖에 있는데 행위로 분류해야 하는 태그. `interracial`(explicit 89.6%)은
# 서브그룹이 `focus_tags`(구도)라 여기 안 들어오고, 레거시 빌더의 분류에도 갈 곳이
# 없어 `_nsfw_unrouted.txt` 에 갇혀 있었다. 행위로 보낸다(사용자 지시 2026-08-01).
ACT_PULL = ("interracial",)

# 금기와 평상 사이는 `wildcards/nsfw/nsfw_heavy.txt` 가 담당한다 — 사용자가 직접
# 큐레이션하는 파일이고 도구는 쓰지 않는다. 그 파일이 리포에 있으므로 아래 `taken`
# 이 읽어 도감에서 자동으로 빠진다.
#
# 처음엔 여기 `TO_HEAVY = {"inseki"}` 라는 두 번째 목록을 뒀는데, 포터블에만 있던
# 파일을 리포로 가져오면서 필요가 없어졌다. 목록이 두 벌이면 반드시 갈라진다.
# (`inseki` = 의붓 친척 간 관계. `incest` 는 이름 규칙이 잡았으나 일본어 표기라
#  그물을 통과했다 — 같은 계열은 nsfw_heavy.txt 에 한 줄 추가하면 된다.)
# 서브그룹을 빠져나온 것 중 이름으로 거르는 것. 서브그룹 분류가 완전하지 않다.
# 뒤쪽 `\b` 때문에 접미가 붙은 형태를 놓쳤다 — `molest`+`ation`, `bestial`+`ity`.
# 앞 경계만 두고 뒤는 연다. 이 목록은 정확도보다 누락이 위험하다.
BLOCK_NAME = re.compile(
    r"\b(rape|shota|loli|child|kid|toddler|baby|teen|incest|cest"
    r"|noncon|non-con|forced|molest|unconscious|drugged|guro|ryona|vore"
    r"|scat|feces|urine|piss|torture|abuse|snuff|bestial|zoo|pokephilia"
    r"|chikan|harassment|mind control|hypnosis|hypnotiz)", re.I)

# 규칙으로 일반화되지 않는 단건. 규칙에 태그 이름을 박는 것과 다르다 — 여기 있는 것은
# "규칙이 놓치는 예외"임을 이름으로 밝힌다(의상 빌더의 `POST_EXPLICIT` 과 같은 자리).
# 규칙에 이름을 숨기면 `breast pocket` 처럼 왜 거기 있는지 알 수 없게 된다.
TAG_OVERRIDE = {
    # 이름 규칙으로는 어느 분류에도 안 맞는다(인종 조합이라 행위 어휘가 없다).
    # 레거시 빌더의 분류에도 갈 곳이 없어 _nsfw_unrouted.txt 에 갇혀 있었다.
    # 행위로 보낸다(사용자 지시 2026-08-01). ACT_PULL 로 풀에 끌어온다.
    "interracial": "nsfw_act",
    # 발바닥을 맞대어 질 입구를 흉내 내는 발. 해부가 아니라 **흉내**다 —
    # `phallic symbol`("무해한 물건이 페니스 모양")이 정확한 짝이고 그쪽에 있다.
    # 사용자 지적 2026-07-30: "자세에 가깝다, sexually suggestive 같은".
    "foot pussy": "nsfw_fetish",
    # 보는 쪽의 **반응**이다 — 손으로 하는 것도, 부위 자체도 아니다.
    # 서브그룹 폴백은 `sexual_activity` -> 행위로 보내는데, 그림에 남는 것은
    # 표정이라 상태·표정이 맞다(`ahegao` · `torogao` 와 같은 자리).
    "penis awe": "nsfw_state",
    "looking at penis": "nsfw_state",
    # 행위다. 해부 규칙을 맨 뒤로 보냈어도 그것 역시 **이름 규칙**이라 서브그룹
    # 폴백보다 먼저 돌고, `\bpenis` 가 이 셋을 다시 삼킨다. `nsfw_act` 는 폴백 전용
    # 키라 정규식이 없으므로 여기서 명시한다.
    "penis measuring": "nsfw_act",
    "smelling penis": "nsfw_act",
    "penises touching": "nsfw_act",
}

# 분류. 위에서부터 먼저 맞는 것을 쓴다(순서가 곧 우선순위).
# 이름 규칙만 쓴다 — 눈으로 검수하지 않으므로 근거가 이름에 있어야 한다.
CATEGORIES = (
    ("nsfw_censor", "검열 처리", re.compile(
        r"censor|mosaic|bar censor|convenient|steam\b|light censor|tape gag")),
    ("nsfw_group", "다인원", re.compile(
        r"group sex|threesome|foursome|orgy|gangbang|\bmmf\b|\bffm\b|\bmmm\b|\bfff\b"
        r"|double penetration|triple penetration|spitroast|multiple (boys|girls|penises)"
        r"|shared|netorare|cuckold|voyeur")),
    ("nsfw_position", "체위", re.compile(
        r"position|missionary|cowgirl|doggystyle|from behind|girl on top|straddling"
        r"|suspended|standing sex|reverse |sitting sex|lap\b|prone bone|piledriver"
        r"|leg lift|carrying sex|face-to-face")),
    ("nsfw_oral", "구강", re.compile(
        # `oral` 은 단어 경계가 필요하다 — 없으면 `pect-oral-s` · `clit-oral` 을 삼킨다
        # (`butt` 가 butterfly·button 을 삼켰던 것과 같은 실수, 두 번째다).
        r"fellatio|\boral\b|cunnilingus|irrumatio|deepthroat|licking|sucking|blowjob"
        r"|mouth|tongue|kiss|swallow|gokkun|throat")),
    ("nsfw_penetration", "삽입", re.compile(
        r"penetrat|vaginal|\banal\b|insertion|inside\b|\bin (pussy|vagina|ass|anus|mouth)"
        r"|impale|stuck|hilt|deep\b|cervix|womb")),
    # 손이 아닌 **부위**로 하는 자극. `-job` 접미가 곧 부위다(paizuri=가슴).
    # 손 규칙보다 앞에 있어야 한다 — 뒤에 두면 `handjob` 계열 패턴이 먼저 먹는다.
    # `nsfw_fetish` 보다도 앞이다: `docking`(가슴 맞대기) · `thigh sex`(스마타) ·
    # `buttjob` · `pecjob` 이 페티시로 갔던 것을 여기로 가져온다(전수 조사 2026-07-30).
    ("nsfw_bodyjob", "가슴·발·기타 부위", re.compile(
        r"paizuri|footjob|thighjob|axillajob|hairjob|buttjob|pecjob|scissoring"
        r"|tribadism|frottage|grinding|thigh sex|docking|to breast$"
        r"|bulge press|breast contest|face to pecs")),
    ("nsfw_hand", "손·손가락", re.compile(
        # 손·손가락으로 하는 것만. `paizuri` · `footjob` · `hairjob` · 마찰 계열은
        # `nsfw_bodyjob` 으로 나갔다(사용자 지적 2026-07-30: "가슴으로 하는 행위이지
        # 손으로 하는 action 은 아니다"). 그쪽 규칙이 이 위에 있어 먼저 잡는다.
        r"handjob|masturbat|fingering|rubbing|stroking|fingers? in"
        r"|grabbing|groping|squeez|fondl|pinching|tweaking"
        # 부위 이름이 든 **행위**들. 해부 규칙이 이름으로 먼저 삼켜서 여기 못 왔다
        # (`spread pussy` 15,252 · `clitoral stimulation` 2,163 — 사용자 지적 2026-07-30).
        # **손·자극만 여기다.** 처음엔 해부에서 꺼낸 것을 전부 여기로 밀어 넣었는데
        # `looking at penis`(시선) · `penis awe`(반응) · `penis measuring` ·
        # `smelling penis` · `penises touching` · `presenting pussy` 는 손으로 하는
        # 자극이 아니다(전수 조사 2026-07-30). 패턴을 좁혀 제 축으로 떨어지게 한다.
        r"|spread pussy|clitoral stimulation|\bgrab$|caressing|glansjob"
        r"|foreskin pull")),
    ("nsfw_toy", "기구·도구", re.compile(
        r"sex toy|dildo|vibrator|anal beads|butt plug|onahole|fleshlight|toy\b"
        r"|rope|shibari|bound|bondage|restrain|handcuff|collar|leash|blindfold|spreader"
        # 구속구가 `nsfw_act`(행위 폴백)로 샜다 — `shackles` 6,015 · `chained` 2,440 ·
        # `suspension` 1,839 · `immobilization` 324. 보이는 것은 행위가 아니라 도구다.
        r"|chastity|cock ring|strap-on|strapon|machine"
        r"|shackle|chained|suspension|immobiliz")),
    ("nsfw_cum", "사정", re.compile(
        r"\bcum\b|cumdrip|cumshot|ejaculat|semen|precum|creampie|bukkake|facial"
        r"|pussy juice|vaginal fluid|saliva|drool|squirt|lactation|milk\b|sweat")),
    ("nsfw_pairing", "관계·장르", re.compile(
        # `futanari` 만 적었더니 `futa with female`(7,464) 등 6개가 행위 폴백으로 샜다.
        # `\bfuta` 로 열면 `futa *` · `futasub` · `futanari` 를 한 번에 잡는다.
        # (`intravaginal futanari` · `futanari masturbation` 은 삽입·손 규칙이 먼저
        #  잡는다 — 그쪽은 관계가 아니라 행위라 순서가 맞다.)
        r"hetero|\byuri\b|\byaoi\b|\bbara\b|\bfuta|newhalf|otokonoko|monster girl"
        r"|furry|interspecies|tentacle|size difference|age difference|dominant"
        # `\bpov\b` 는 여기 있으면 안 된다 — 시점이지 관계가 아니다. `pov crotch`(7,340) ·
        # `futanari pov` 가 관계·장르로 갔다(사용자 지적 2026-07-29). 엿보임으로 옮긴다.
        r"|submissive|femdom|maledom|imminent")),
    # 시점 기반 노출. `\bpov\b` 를 관계에서 여기로 가져왔다 — 어디서 보느냐가 축의 성격이다.
    # **태그 이름을 통째로 박지 말 것.** `breast pocket`(셔츠 가슴 주머니)을 여기 적어놔서
    # 의류 디테일이 성인 도감에 이름으로 끌려 들어갔다. 규칙은 규칙이어야 한다.
    ("nsfw_peek", "엿보임·노출 사고", re.compile(
        r"pantyshot|pantylines|upskirt|upshorts|upshirt|downblouse|slip\b|peek\b"
        r"|clothing aside|cutout|nippleless|accidental|zenra|flashing"
        # `breast curtain`(단수)만 행위 쪽에 떨어져 복수형 `breast curtains` 와
        # 갈라져 있었다. `up sleeve` 는 소매 안 엿보기라 정의상 여기다.
        r"|public nudity|see-through|\bpov\b|breast curtain|up sleeve")),
    ("nsfw_fetish", "페티시·상황", re.compile(
        r"inflation|expansion|enema|human toilet|exhibitionism|indecency|prostitut"
        r"|instant loss|defloration|impregnat|fertiliz|in heat|virgin|sex ed"
        r"|contest|pornography|docking|thigh sex|buttjob|pecjob")),
    # 성기·유두에 **붙이는 것**. 피어싱·보석·문신·마에바리는 해부가 아니라 장식이다.
    # SFW `marking` 축이 `tattoo` · `piercing` · `chest tattoo` 를 이미 갖고 있는데,
    # 성적 부위 쪽만 도감에 남아 해부 규칙에 이름으로 끌려갔다.
    ("nsfw_adorn", "장신구·문신·가리개", re.compile(
        r"piercing|jewelry|\brings\b|tattoo|bandaid|ofuda|tape on|\bribbon\b"
        r"|lipstick mark|body writing")),
    ("nsfw_state", "상태·표정", re.compile(
        r"erection|flaccid|aroused|arousal|blush|ahegao|orgasm|climax|trembling"
        r"|spread|presenting|exposed|nude|naked|undress|strip|lifted|raised"
        # `zettai ryouiki` 를 여기 박아놨었다 — 스커트와 사이하이 사이의 허벅지 구간이라
        # 성인 태그가 아니다. `cloth_legwear` 로 이관(2026-07-29). 죽은 줄이라 지운다.
        r"|cameltoe|clothed |partially|after ")),
    # **해부는 반드시 맨 뒤다.** 이것만 '부위 이름' 규칙이고 나머지는 '무엇을
    # 하는가' 규칙이다. 앞에 두면 이름이 든 모든 것을 삼킨다 — `spread pussy`(행위) ·
    # `pussy jewelry`(장신구) · `pussy peek`(엿보임) · `condom on penis`(기구)가
    # 전부 해부로 갔다. 이름 규칙은 다른 규칙이 전부 놓친 뒤에 마지막으로 본다.
    ("nsfw_anatomy", "해부·부위", re.compile(
        r"\bpenis|\bpussy|\banus\b|testicl|clitor|vulva|urethra|uterus|cervix|ovum"
        r"|perineum|foreskin|scrotum|hymen|labia|glans|smegma|sperm cell")),
)


# 정규식이 놓친 것의 행선지. 태그 DB 의 subgroup -> 분류.
SUBGROUP_TO = {
    "sex_acts": "nsfw_act", "sex_act": "nsfw_act", "sexual_activity": "nsfw_act",
    "simulated_sex_acts": "nsfw_act", "activity": "nsfw_act", "implied": "nsfw_act",
    "sexual_positions": "nsfw_position", "sex_position": "nsfw_position",
    "pose": "nsfw_position",
    "genitals": "nsfw_anatomy", "anatomy": "nsfw_anatomy", "body": "nsfw_anatomy",
    # 문신·피어싱은 장식이다(`pubic tattoo` · `nipple rings`).
    "body_modification": "nsfw_adorn", "body_writing": "nsfw_adorn",
    "piercings": "nsfw_adorn", "pasties": "nsfw_adorn",
    "nudity": "nsfw_peek", "exposure": "nsfw_peek",
    "sexual_attire": "nsfw_peek",
    "sex_objects": "nsfw_toy", "toys": "nsfw_toy", "object": "nsfw_toy",
    "fluids": "nsfw_cum",
    "groping": "nsfw_hand", "self_touch": "nsfw_hand",
    "censorship": "nsfw_censor",
    "expression": "nsfw_state", "state": "nsfw_state", "reaction": "nsfw_state",
    "anticipation": "nsfw_state", "meter": "nsfw_state",
    "fetish": "nsfw_fetish", "situation": "nsfw_fetish",
    "sexual_situation": "nsfw_fetish", "genre": "nsfw_fetish",
    "media": "nsfw_fetish", "meme": "nsfw_fetish",
    # `symbol` 도 여기다. 기호(`:>=` · `phallic symbol`)는 검열 **방식**이 아니라
    # 성적 암시의 표현이다 — `censorship` 과 한 통에 두면 모자이크와 이모티콘이 섞인다.
    "symbol": "nsfw_fetish",
    # **잡동사니 서랍 금지.** `pov`/`focus`/`visual` 을 전부 `nsfw_pairing` 으로 보내
    # `bouncing breasts`(10,094)가 관계·장르에 들어갔다(사용자 지적). 관계와 무관한
    # 서브그룹은 관계로 보내지 않는다 — `pov` 는 이름 규칙이 엿보임으로 가져간다.
    "visual": "nsfw_anatomy", "focus": "nsfw_anatomy",
    "insertion": "nsfw_penetration",
}
# `nsfw_act` 는 폴백 전용 키다 — 이름 규칙으로는 안 잡히는 '행위 일반'(sex 등).
_FALLBACK_LABEL = {"nsfw_act": "행위"}


def _moved_to_sfw() -> set[str]:
    """성인 도감에서 일반 축으로 옮긴 태그. tools/nsfw_reclassify.py 가 만든다.

    **빼기만 하면 안 되고 받을 축이 있어야 한다** — 일반 빌더는 자기 서브그룹에서만
    태그를 뽑으므로 NSFW 그룹 태그를 주워 가지 않는다. 목적지 축은 그 스크립트가
    함께 만든다(cloth_revealing / body_suggestive / pose_suggestive / obj_restraint).
    """
    p = Path("wildcards/nsfw/_moved_to_sfw.txt")
    if not p.exists():
        return set()
    return {l.strip() for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")}


def main() -> int:
    from core.kr_tag_loader import load_kr_tag_records
    raw = load_kr_tag_records().raw
    F = lambda t: int((raw.get(t) or {}).get("freq", 0) or 0)      # noqa: E731
    SG = lambda t: str((raw.get(t) or {}).get("subgroup", "") or "")  # noqa: E731
    SRC = lambda t: str((raw.get(t) or {}).get("source", "") or "")   # noqa: E731

    # 기존 도감(245)과 겹치면 안 된다 — 팩 키가 하나뿐이라 뒤쪽 축이 영영 안 찬다.
    # **자기 출력 파일은 빼야 한다.** 두 번째 실행에서 직전 결과가 전부 `taken` 으로
    # 잡혀 풀이 0이 된다(실측). 이 프로젝트에서 다섯 번째로 겪는 함정이라 규칙으로 막는다.
    # **폴백 전용 키도 넣어야 한다.** `nsfw_act` 를 빠뜨렸더니 두 번째 실행에서
    # 그 101개가 `taken` 으로 잡혀 642 -> 541 이 됐다. 같은 함정 여섯 번째다 —
    # 목록을 손으로 적지 말고 출력 키 전체에서 파생시킨다.
    _own = {k for k, _l, _p in CATEGORIES} | set(_FALLBACK_LABEL) | {"nsfw_etc"}
    taken: set[str] = set()
    for p in OUT.glob("*.txt"):
        if p.stem.startswith("_") or p.stem in _own:
            continue
        taken |= {l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()}
    # **SFW 축도 봐야 한다.** 처음엔 nsfw 폴더만 봤더니 `hand in another's panties` 가
    # `pose_arm_m`(이미 생성됨)과 `nsfw_act` 양쪽에 들어갔다. 팩 키는 `<축>/<태그>`
    # 하나뿐이라 두 축에 같은 태그가 있으면 뒤쪽이 영영 안 찬다(`bandages` 와 같은 건).
    for p in Path("wildcards/thumb").glob("*.txt"):
        if p.stem.startswith("_"):
            continue
        taken |= {l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()}

    # 빠진 것도 따로 남긴다(사용자 지시) — 무엇이 왜 빠졌는지 안 보이면
    # 나중에 "이건 왜 없지" 를 다시 조사하게 된다.
    moved = _moved_to_sfw()
    pool, blocked, tabooed, foreign = [], [], [], []
    for tag, d in raw.items():
        # ACT_PULL 은 그룹이 NSFW 가 아니라 여기서 통과시켜야 한다.
        if str(d.get("group", "")) != "NSFW" and tag not in ACT_PULL:
            continue
        if F(tag) < CUT:
            continue
        if SRC(tag) != "KR_tags":
            foreign.append(tag)          # e621 계열 어휘 — 모델이 못 그린다(정책 아님)
            continue
        if SG(tag) in SKIP_SUBGROUP:
            tabooed.append(tag)          # taboo / gore / dark_content
            continue
        # ACT_PULL 은 `taken` 도 통과한다 — 지금 `meta_nsfw.txt`(다른 빌더의 원본)에
        # 들어 있어서 taken 으로 잡힌다. 여기가 넣고 나면 그쪽 빌더가 taken 으로
        # 보고 자기 원본에서 빼므로 한 바퀴 뒤에 정리된다.
        if tag in moved:
            continue                     # 일반 축으로 옮겼다(tools/nsfw_reclassify.py)
        if tag in taken and tag not in ACT_PULL:
            continue
        (blocked if BLOCK_NAME.search(tag) else pool).append(tag)

    cat: dict[str, list[str]] = {}
    unmatched: list[str] = []
    for tag in pool:
        if tag in TAG_OVERRIDE:
            cat.setdefault(TAG_OVERRIDE[tag], []).append(tag)
            continue
        for key, _label, pat in CATEGORIES:
            if pat.search(tag):
                cat.setdefault(key, []).append(tag)
                break
        else:
            # 정규식이 놓친 것은 **태그 DB 의 서브그룹**으로 떨어뜨린다.
            # 규칙을 계속 늘리는 대신 이미 분류돼 있는 것을 쓴다 — 안 그러면
            # 이름 규칙이 데이터를 못 따라가 기타만 커진다(실측 310/650).
            key = SUBGROUP_TO.get(SG(tag))
            (cat.setdefault(key, []) if key else unmatched).append(tag)

    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    for key, label, _p in CATEGORIES:
        v = sorted(cat.get(key, []), key=lambda t: -F(t))
        if not v:
            continue
        (OUT / f"{key}.txt").write_text("\n".join(v) + "\n", encoding="utf-8")
        total += len(v)
        print(f"  {key:18s} {label:14s} {len(v):4d}  {', '.join(v[:5])}")
    for key, label in _FALLBACK_LABEL.items():
        v = sorted(cat.get(key, []), key=lambda t: -F(t))
        if not v:
            continue
        (OUT / f"{key}.txt").write_text("\n".join(v) + "\n", encoding="utf-8")
        total += len(v)
        print(f"  {key:18s} {label:14s} {len(v):4d}  {', '.join(v[:5])}")
    if unmatched:
        v = sorted(unmatched, key=lambda t: -F(t))
        (OUT / "nsfw_etc.txt").write_text("\n".join(v) + "\n", encoding="utf-8")
        total += len(v)
        print(f"  {'nsfw_etc':18s} {'기타':14s} {len(v):4d}  {', '.join(v[:8])}")
    else:
        # **비면 지운다.** 안 지우면 옛 실행이 남긴 파일이 그대로 살아 축으로 읽힌다
        # (`nsfw_etc` 310개가 그랬다 — 손으로 지웠지만 빌더는 재현하지 못했다.
        #  Codex 리뷰 2026-07-30 지적). 생성기는 자기 산출물을 완전히 소유해야 한다.
        _etc = OUT / "nsfw_etc.txt"
        if _etc.exists():
            _etc.unlink()
            print(f"  {'nsfw_etc':18s} (미분류 0 — 낡은 파일 삭제)")

    # ── 제외 목록 3종 ────────────────────────────────────────────────────
    # 파일명이 `_` 로 시작하므로 팩 빌더·생성기가 축으로 읽지 않는다.
    def _dump(name: str, items: list[str], head: str) -> None:
        if not items:
            return
        v = sorted(items, key=lambda t: -F(t))
        body = "\n".join(f"{t}\t{F(t)}\t{SG(t) or '-'}" for t in v)
        (OUT / name).write_text(f"# {head}\n# 태그\t빈도\t서브그룹\n{body}\n", encoding="utf-8")
        print(f"  {name:24s} {len(v):5d}  {head}")

    print("\n제외 목록:")
    _dump("_excluded_taboo.txt", tabooed,
          "서브그룹 taboo/gore/dark_content — 강간·아동·근친·구로·료나·자해·자살·고문·유혈")
    _dump("_excluded_byname.txt", blocked,
          "위 서브그룹을 빠져나왔지만 이름 규칙에 걸린 것 (서브그룹 분류가 완전하지 않다)")
    _dump("_excluded_foreign.txt", foreign,
          "e621 계열 어휘 — Danbooru 학습 모델이 못 그린다(정책 제외 아님)")

    (OUT / "_nsfw_act_catalog.json").write_text(json.dumps({
        "note": [
            "성인 행위 도감. 이미지를 만들지 않는다 — 목록뿐이다.",
            "NSFW 그룹은 SLOT_GROUPS 에 없어 분류 파이프라인이 읽은 적이 없었다.",
            "source=KR_tags 만 담는다(e621 계열은 Danbooru 모델이 못 그린다).",
            "제외분은 _excluded_*.txt 세 파일에 이유별로 남긴다.",
        ],
        "label": {k: l for k, l, _p in CATEGORIES} | _FALLBACK_LABEL | {"nsfw_etc": "기타"},
        "cut": CUT,
        "count": total,
        "excluded": {"taboo": len(tabooed), "byname": len(blocked), "foreign": len(foreign)},
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n총 {total}개 / {OUT}/  (이미지 생성 없음)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
