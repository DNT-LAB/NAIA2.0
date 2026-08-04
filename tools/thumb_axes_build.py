# -*- coding: utf-8 -*-
"""전 축 와일드카드 재생성 — freq >= THRESHOLD 전수 커버리지.

이전에는 축마다 손으로 골라 88/12/12/10 처럼 잘렸다(귀 105->12, 꼬리 98->12).
여기서는 축을 'subgroup 집합 + 규칙'으로 정의하고 임계값 이상 전부 담는다.
--dry 로 규모만 먼저 본다.
"""
import argparse, re
from pathlib import Path
from core.kr_tag_loader import load_kr_tag_records
import core.interactive_browse_index as ib

ap = argparse.ArgumentParser()
ap.add_argument("--threshold", type=int, default=60)
ap.add_argument("--dry", action="store_true")
args = ap.parse_args()
TH = args.threshold

raw = load_kr_tag_records().raw
idx = ib.InteractiveBrowseIndex(raw)
F = lambda t: int((raw.get(t) or {}).get('freq', 0) or 0)
SGL = lambda t: str((raw.get(t) or {}).get('subgroup', '')).lower()
G = lambda t: idx._group_lookup.get(t)

def pool(subgroups, groups=('Person_Body', 'Creatures')):
    return [t for t, m in raw.items() if isinstance(m, dict) and G(t) in groups
            and SGL(t) in subgroups and F(t) >= TH]

# 슬라이더/팔레트가 담당하므로 썸네일에서 빼는 것들
LENGTH = {"very short hair", "short hair", "medium hair", "long hair", "very long hair", "bald"}
BREAST_SIZE = {"flat chest", "small breasts", "medium breasts", "large breasts", "huge breasts"}
HAIR_COLOR = {t for t in raw if SGL(t) == 'hair_color'}
EYE_COLOR = {t for t in raw if SGL(t) == 'eyes'}
PATTERN = {"multicolored hair", "streaked hair", "two-tone hair", "gradient hair",
           "colored inner hair", "split-color hair", "colored tips"}
EYE_PATTERN = {"multicolored eyes", "heterochromia", "two-tone eyes", "gradient eyes"}

BANGS = re.compile(r'bangs|hair between eyes|curtained hair', re.I)
NSFW = re.compile(r'nipple|areola|pubic|anus|penis|vagina|clitoris|labia|crotch|groin'
                  r'|bulge|flaccid|erection|cum\b|censor|breasts out|breasts apart'
                  # `hanging`·`bursting`·`sagging`·`veiny breasts` 를 뺐다 —
                  # safebooru 에 그대로 노출되는 SFW 태그다(사용자 확인). 이름만 보고
                  # 성인으로 몰면 `body_nsfw` 로 가는데 그 축은 UI 에서 통째로 빠져
                  # 있어 그림을 만들 기회조차 사라진다. 배정은 RECLASSIFIED 가 한다.
                  r'|spread (ass|anus)|oppai|naked'
                  r'|breast slip|nude', re.I)
FEATURE = re.compile(r'horn|antler|claw|talon|pawpad|paw\b|fin\b|fins|antenna|scale'
                     r'|scar|cut\b|cuts\b|burn|bite mark|wound|bruise|injury|stitch'
                     r'|mole|freckle|birthmark|marking|tattoo|nail|fang|tusk|hoof|hooves'
                     r'|skeleton|\bbone\b|skull|eyeball|joint|suction|thorn|veins?\b'
                     r'|hair\b|hairy|amputee|prosthe|piercing|animal (hands|feet|legs)'
                     r'|bird legs|digitigrade|dirty|blood|hickey|slap mark|bump', re.I)

# ── 신체 축 정리 (Codex 리뷰) — 데이터 설명이 뒷받침하는 무손실 이동만 ──────
# `oppai loli` 는 `oppai` 정규식에 걸려 성인 축으로 갔지만, 실사용은 **외모 서술**이다
# (Blue Archive 카에데 류 — safebooru 에 그대로 노출되는 그림에 붙는다). 사용자 판정.
# 체형 축의 다른 항목(`loli`/`child`/`petite`/`shortstack`)과 같은 성격이다.
BODY_TO_TYPE = ["belly",          # "다소 통통한 복부" = 체형
                "oppai loli"]
BODY_TO_FEATURE = ["covered abs"]  # "옷 위로 윤곽" = 노출이 아니다
BODY_TO_CONDITION = ["blood on feet"]  # 다른 blood on X 는 모두 부상 축에 있다
BODY_TO_HAIR = ["bald girl"]      # "대머리 여성" = 머리카락 특징

AXES = {}
# 머리
hair = [t for t in pool(('hair_styles', 'hair'))
        if t not in LENGTH and t not in PATTERN and not BANGS.search(t)]
# ── 머리 축 정리 (Codex 리뷰 REQUEST-CHANGES 34건) ──────────────────────────
# 이미지가 이미 있으므로 '이동'만 한다(--prune 이 팩 키를 옮겨 무손실).
#   수염 6개는 hair_style 과 face(표식·수염) 로 흩어져 있었다 -> face 로 통합.
#   색상·패턴 5개는 hair_pattern 축이 맞다(머리 '모양'이 아니다).
#   장식 3개(hair tubes 36k 포함)는 머리카락이 아니라 착용물이다 -> 의상 성격.
#   japari bun 은 케모노프렌즈 '식품', mane 은 동물 갈기다.
HAIR_TO_FACE = ["beard stubble", "long beard", "full beard", "thick beard",
                "tied beard", "pencil mustache"]
HAIR_TO_PATTERN = ["roots (hair)", "dyed ahoge", "patterned hair", "hair blush"]
HAIR_MOVED_OUT = {
    "hair tubes", "single hair tube", "flower braid",   # 장식(착용물)
    "japari bun",        # 케모노프렌즈 식품 — 사물
    "mane",              # 동물 갈기 — 이형
    "hair on horn", "food on hair", "hair behind eyewear",  # 다른 요소와의 위치 관계
    "cowlick",           # 데이터: '바보털' = ahoge 와 동일어
}
hair = [t for t in hair if t not in HAIR_TO_FACE + HAIR_TO_PATTERN
        and t not in HAIR_MOVED_OUT]
AXES["hair_style"] = hair + [t for t in BODY_TO_HAIR if t in raw]
AXES["bangs"] = [t for t in pool(('hair_styles', 'hair'))
                 if BANGS.search(t) and t != "dyed bangs"]
AXES["hair_pattern"] = ([t for t in PATTERN if t in raw]
                        + [t for t in HAIR_TO_PATTERN + ["dyed bangs"] if t in raw])
# 눈 색 패턴
AXES["eye_pattern"] = [t for t in EYE_PATTERN if t in raw]
# 얼굴(전량 유지)
# eye_pattern 축이 따로 담당하는 태그(multicolored eyes 등)는 face 에서 뺀다 —
# 양쪽에 있으면 같은 태그를 두 번 생성하게 되고 팩 키도 갈린다.
AXES["face"] = [t for t in pool(('face_tags', 'eyes_tags', 'face_meta', 'face'))
                if t not in EYE_PATTERN] + [t for t in HAIR_TO_FACE if t in raw]
# 종족 = 캐릭터형(-girl/-boy) + 환상종/케모미미. 일반 동물(rabbit, bat)은 캐릭터 특징이 아니라 제외.
crea = pool(('legendary_creatures', 'kemonomimi', 'cats', 'dogs', 'other_animals',
             'fish', 'birds', 'insects', 'reptiles', 'technology', 'archetype', 'furry'))
AXES["species"] = [t for t in crea
                   if re.search(r'\b(girl|boy)$', t) or SGL(t) in ('legendary_creatures', 'kemonomimi', 'archetype')]
# 종족 축 정리 — "사용자가 만들려는 캐릭터의 종족"만 남긴다.
# 기준: (1) X girl / X boy 조합형은 전부 유지(설명이 필요 없고 썸네일이 곧 설명이다),
#       (2) 고유명사는 freq >= 300,
#       (3) 그 아래라도 널리 알려진 신화·판타지 원형은 되살린다(RESCUE).
# 걸러지는 것은 작품을 모르면 의미 없는 고유 종족과, 종족이 아닌 것(부위/행위/사물)이다.
# harvin(1923) / draph(8231) / erune(7904) / miqo'te(6685) 처럼 인기 있는 작품 종족은
# 빈도로 자동 통과한다 — 작품 소속 여부가 아니라 실사용량이 기준이다.
SPECIES_MIN_FREQ = 300
SPECIES_RESCUE = {
    "yuki onna", "golem", "ogre", "griffin", "western dragon", "tiefling", "halfling",
    "genie", "satyr", "sphinx", "dryad", "gargoyle", "lich", "cerberus", "doppelganger",
    "gnome", "mindflayer", "chupacabra", "futakuchi-onna",
}
_KEMO_FORM = re.compile(r'\b(girl|boy)$')
_species_keep = [t for t in AXES["species"]
                 if _KEMO_FORM.search(t) or F(t) >= SPECIES_MIN_FREQ
                 or t in SPECIES_RESCUE]
# 아래 EXCLUDE 에 넣어야 유니온(기존 목록 합집합)이 되돌려 넣지 않는다 — 세 번째로 겪는 함정.
SPECIES_CUT = {t for t in AXES["species"] if t not in _species_keep}
AXES["species"] = _species_keep
# 남성형 종족(`cat boy` 등)은 **팩 복원 뒤에** 갈라낸다 — 아래 `_MALE_FORM` 참조.

AXES["ears"] = pool(('ears_tags',))
AXES["tail"] = pool(('tail',))
AXES["wings"] = pool(('wings',)) + [t for t in ["mechanical wings"] if t in raw]
# ── 표식(문신/피어싱) 축 ────────────────────────────────────────────────────
# 표식·기타 슬롯은 browse 전용이었고 성격이 뒤섞여 있었다. 실측(index 직접 질의)으로
# 133개가 오는데, 그 중 문신/피어싱/표식 계열만 코히런트하다. 나머지는 재배치한다.
#   개조(prosthetic/mechanical) -> 이형 부위 (prosthetic hand 가 이미 거기 있다)
#   이형 해부(extra arms/legs/horns, multiple heads, detached arm/legs) -> 이형 부위
#   초현실(object head, hollow body, conjoined) -> 이형 부위
#   캐릭터 메타(otoko no ko, mature male/female, faceless, minigirl ...) -> 제외.
#     성별·연령은 캐릭터 헤더의 성별 토글이 담당하고, faceless/*focus 는 구도다.
MARKING_SUBS = ('tattoo', 'piercings', 'skin_markings', 'cosmetics',
                'body_marks', 'body_modification')
# subgroup 이 gesture 로 잘못 붙은 표식들(실측)
MARKING_EXTRA = ["hand tattoo", "scar on hand", "fingerprint"]
# NSFW 누출 — piercings subgroup 을 통째로 가져오면서 성기·유두 피어싱을 걸러내지
# 않았다. 표식 축은 초보자에게 기본 노출되므로 노출(성인) 축(블러+보류)으로 옮긴다.
# Codex 가 3건을 잡았고 전수 재검사로 2건(mole on areola, slave tattoo)을 더 찾았다.
MARKING_TO_NSFW = ["nipple chain", "clitoris ring", "mole on areola", "frenulum piercing"]
# 데이터가 다른 태그를 쓰라고 지시하거나, nude 베이스에서 표현 불가한 것
MARKING_DROP = {
    "slave tattoo",      # "노예 낙인을 사용하세요" + 정신 파괴·부패 맥락
    "ear bar",           # "industrial piercing 을 사용한다"
    "covered piercing",  # "옷 위로 피어싱의 자국" — nude 베이스에서 불가
    "fingerprint",       # "지문이 표면에 찍힌" — 캐릭터 표식이 아니다
}
AXES["marking"] = [t for t in pool(MARKING_SUBS) + [x for x in MARKING_EXTRA if x in raw]
                   if t not in MARKING_TO_NSFW and t not in MARKING_DROP]

AXES["skin"] = pool(('skin_color',))
AXES["body_type"] = ([t for t in pool(('body_type',))
                      if t not in BREAST_SIZE and t not in BODY_TO_HAIR]
                     + [t for t in BODY_TO_TYPE if t in raw])
# ── 신체 부위 분할 ─────────────────────────────────────────────────────────
# 이전 규칙은 'NSFW 정규식 -> nsfw, FEATURE 정규식 -> feature, 나머지 전부 -> expose'
# 였다. 이 catch-all 이 '미분류 0'을 보장한 대가로, 규칙에 안 걸린 모든 것을 노출·강조에
# 쏟아부었다 — 176개 안에 행위(hands on own ass) / 물리효과(ass ripple) / 내장(intestines)
# / 이형(gills) / 폐기태그(hands) / 의상(back bow) 이 뒤섞였다.
# 이제 명시 목록이 최우선이고, 어느 목록에도 없으면 '미분류'로 드러낸다(조용히 삼키지 않는다).
BODY_EXPOSE = [   # "그 부위가 보인다/강조된다"
    "breasts", "navel", "cleavage", "bare shoulders", "collarbone", "thighs", "ass",
    "barefoot", "stomach", "midriff", "armpits", "feet", "bare arms", "toes",
    "bare legs", "legs", "sideboob", "ass visible through thighs", "soles",
    "underboob", "back", "thigh gap", "forehead", "butt crack", "kneepits",
    "armpit crease", "bare back", "shoulder blades", "single bare shoulder",
    "pectoral cleavage", "backboob", "nape", "neck", "sidepec", "underpec",
    "underbutt", "ass peek", "single bare leg", "single bare arm", "bare hips",
    "toe cleavage", "covered armpit", "palms",
]
# ── 신체 축 정리 (Codex 리뷰) — 데이터 설명이 뒷받침하는 무손실 이동만 ──────
#   belly="다소 통통한 복부" -> 체형 / covered abs="옷 위로 윤곽" -> 노출이 아니다
#   blood on feet -> 부상(다른 blood on X 는 모두 거기 있는데 이것만 남아 있었다)
#   bald girl="대머리 여성" -> 머리카락 특징 / box body="표현 스타일" -> 제외
#   very long fingernails: 데이터 정의가 long fingernails 와 똑같이 "1cm 이상" -> 중복
# Codex 가 legs/forehead 등을 '구도'라며 뺄 것을 제안했지만 받지 않았다 —
# 노출·강조 축의 정의 자체가 '그 부위가 보인다/강조된다'이므로 구도성이 곧 성격이다.
# loli/teenage/three sizes 제외 제안도 받지 않았다(사용자가 명시적으로 유지 결정).
BODY_FEATURE_ADD = [   # "몸에 그 특징이 있다" — FEATURE 정규식에 안 걸리는 것들
    "huge ass", "flat ass", "biceps", "navel hair", "ribs", "knees", "linea alba",
    "median furrow", "dimples of venus", "obliques", "thick arms", "hip bones",
    "spine", "veiny arms", "large hands", "curled fingers", "long neck", "greek toe",
    "perky breasts", "pointy breasts", "manboobs", "puffy chest", "outie navel",
    "x navel", "no navel", "broad shoulders", "slim legs", "long fingers", "long arms",
    "asymmetrical arms", "asymmetrical breasts", "oversized forearms", "veiny hands",
    "veiny thighs", "deltoids", "triceps", "forearms", "long toes", "large feet",
    "adam's apple", "jaw", "armpit stubble", "shaved body", "thick neck",
    "unaligned breasts", "small hands",
    *BODY_TO_FEATURE,
]
BODY_NONHUMAN = [   # 이형·수인 해부 -> 종족·수인 슬롯의 새 축
    "arthropod limbs", "gills", "blowhole", "spines", "core", "pincers",
    "webbed hands", "webbed feet", "tiger paws", "bear paws", "dog paws", "cat feet",
    "multiple legs", "multiple hands", "extra hands", "extra breasts",
    "dragon (arms)", "prehensile ribbon", "mechanical hands", "neck fur",
    "chest tuft", "fluff", "third eye on chest", "no feet", "male with breasts",
    # body_feature 감사(205개)에서 합류 — claws 27k 가 이형 축에 없는 게 오히려 이상했다.
    "claws", "fins", "head fins", "dorsal fin", "shark fin", "talons", "pawpads",
    "hooves", "animal hands", "animal feet", "bird legs", "digitigrade",
    "reverse-jointed legs", "suction cups", "thorns", "antennae", "moth antennae",
    "crab claw", "prosthetic hand", "sharp toenails",
    # 표식·기타 슬롯 재정렬에서 합류 — 기계·의체·이형 해부는 이형 부위가 맞다.
    "prosthesis", "prosthetic arm", "prosthetic leg", "hook hand", "peg leg", "automail",
    "mechanical arms", "mechanical legs", "mechanical spine",
    # mechanical wings -> 날개 축, mechanical horns -> 뿔 축 (Codex 지적).
    # mechanical 5개를 통째로 이형에 넣은 것이 내 실수였다.
    "extra arms", "extra legs", "extra horns", "multiple heads",
    "detached arm", "detached legs",
    "object head", "hollow body", "conjoined",
]
BODY_NSFW_ADD = ["pussy juice on fingers", "glands of montgomery"]
# 썸네일 축에서 빼는 것들 — 다른 슬롯(액션/효과/의상)이 browse 로 담당한다.
MOVED_OUT = {
    # 행위·자세 -> 액션
    "between fingers", "hands on own ass", "ass support", "hands on own breasts",
    "hands on ass", "ass-to-ass", "between toes", "between buttocks",
    "hands on own leg", "ass on glass", "v legs", "full stomach",
    # 물리·시각 효과 -> 효과
    "ass ripple", "bouncing ass", "floating breasts", "wheel o feet",
    "glowing hands", "glowing lines", "ghost hands", "giant hand",
    "inconvenient breasts", "convenient breasts",
    # 의상·장식 -> 의상 / 표식
    "back bow", "bandaid on ass", "bandaged fingers", "tramp stamp",
    "paint on body", "paint on fingers", "bursting ass",
}
# 고어·부상 — 사용자 판단: 초보자 용도에 부적합하므로 축에서 완전 제외(블러도 안 쓴다).
GORE = {
    "intestines", "brain", "organs", "exposed brain", "entrails", "heart (organ)",
    "heart out of chest", "stomach (organ)", "flesh", "exposed muscle", "slit throat",
    "hole on body", "hole in chest", "hole in head", "skeletal arm", "skeletal hand",
    "whip marks", "broken arm", "broken leg", "sprain", "bug bite",
    # body_feature 감사에서 추가 발견 — '하드 고어'만 뺀다.
    # 경상(ryona) 계열은 수요가 있다는 사용자 판단에 따라 STATE 축으로 살린다.
    "deep wound", "burnt", "exposed bone", "skeleton", "skull", "bone", "eyeball",
    "self-harm scar", "armless amputee",
    # 봉합: 상처 실밥(stitches)은 경상이라 STATE 로 살리고, 프랑켄슈타인식 접합만 뺀다.
    "stitched arm", "stitched torso", "stitched leg", "stitched neck",
    "stitched hand", "stitched eye", "stitched fingers", "stitching",
}
# ── 상태(STATE) 축 ─────────────────────────────────────────────────────────
# 상태 태그는 데이터상 6곳에 흩어져 있다 — sweat(316k) 은 pose, wet 은 effects,
# injury 는 body_parts, panting 은 Actions, tired 는 Expressions, steaming body 는
# body_functions. Expression_Action > state 서브그룹이 존재하지만 very sweaty 하나뿐이다.
# 그래서 한 축으로 모은다. 경상(ryona)도 여기 포함 — 하드 고어와 분리되는 지점이다.
# 프레이밍은 upper: 얼굴(홍조/눈물/침)과 몸통(땀/멍/붕대)이 함께 보여야 한다.
STATE = [
    # 땀
    "sweat", "very sweaty", "sweating profusely", "sweaty armpits", "steaming body",
    "sweatdrop", "flying sweatdrops", "nervous sweat",
    # 눈물·침
    "tears", "tearing up", "saliva", "saliva string", "drooling", "saliva trail",
    # 홍조
    "blush", "light blush", "full-face blush", "blushing profusely", "nose blush",
    "ear blush", "blush stickers",
    # 호흡·피로
    "heavy breathing", "panting", "trembling", "shivering", "tired", "unconscious",
    # 젖음·김
    "wet", "wet hair", "wet clothes", "steam", "soaking feet",
    # 경상(ryona) — 사용자 판단으로 살린 것들. 인기 태그 위주.
    # blood(제네릭)는 제외 — NAI 가 코피 분수를 그리고(실측), blood on face/arm/leg/
    # chest/hands 로 이미 세분화돼 중복이다.
    "injury", "bruise", "blood on face", "blood on hands", "blood on arm",
    "blood on leg", "blood on chest", "bleeding", "scratches", "cuts", "stitches",
    "bite mark", "slap mark", "hickey", "whip marks", "broken arm", "broken leg",
    # 붕대
    "bandages", "bandaged arm", "bandaged leg", "bandaged head", "bandaged hand",
    "bandage over one eye",
    # 더러움
    "dirty", "dirty feet", "dirty hands", "messy hair",
]
# STATE 가 최우선이다 — whip marks / broken arm / broken leg 처럼 앞선 집합에도 든 것이 있다.
GORE -= set(STATE)
MOVED_OUT -= set(STATE)
# 뿔 — 귀/꼬리/날개와 같은 층위의 선택이다. 32개가 '신체 특징'에 묻혀 있어 독립 축으로 뺀다.
# 목록이 아니라 정규식으로 잡아 새 뿔 태그가 누락되지 않게 한다(제외 목록이 우선).
HORN_RE = re.compile(r'horn|antler', re.I)
# 점/흉터/체모의 '위치 변형' — 192px 에서 서로 구분되지 않는다(코·귀·이마의 점은
# head out of frame 레시피에서 아예 프레임 밖이다). 대표만 남기고 나머지는 자동완성으로.
NEAR_DUP = {
    "mole on neck", "mole on ass", "mole on stomach", "mole on arm", "mole on armpit",
    "mole on collarbone", "mole on shoulder", "mole on leg", "mole on back",
    "mole on chest", "mole on nose", "mole on ear", "mole on forehead", "ass freckles",
    "scar on neck", "scar on stomach", "scar on leg", "scar on back", "scar on shoulder",
    "anal hair", "ass hair", "back hair", "knuckle hair", "hand hair",
    "sparse chest hair", "sparse navel hair", "shaved body",
}
# 의상·장식·화장 -> 의상 / 표식·개조 슬롯이 담당.
WEAR2 = {
    "toenail polish", "multicolored nails", "fake nails", "navel piercing",
    "ass tattoo", "crown of thorns", "horns through hood", "antlers through hood",
    "markings", "body markings",
}
# '원래 있어야 할 게 없다' — 원작 대비 비교가 필요해 단독 썸네일로 성립하지 않는다.
NEGATIVE = {"no mole", "no scar", "no navel", "no horns", "alternate body hair"}

body = pool(('body_parts', 'hands', 'ass', 'shoulders'))
body += [t for t in pool(('breasts_tags',)) if t not in BREAST_SIZE]
_assign = {t: "body_expose" for t in BODY_EXPOSE}
_assign.update({t: "body_feature" for t in BODY_FEATURE_ADD})
_assign.update({t: "body_nonhuman" for t in BODY_NONHUMAN})
_assign.update({t: "body_nsfw" for t in BODY_NSFW_ADD})
# `oppai loli` 는 `oppai` 정규식에 걸려 성인 축으로 갔지만, 실사용은 **외모 서술**이다
# (Blue Archive 카에데 류 — safebooru 에 그대로 노출되는 그림에 붙는다). 사용자 판정.
# 체형 축의 다른 항목(`loli`/`child`/`petite`/`shortstack`)과 같은 성격이라 그쪽으로 보낸다.
# belly 는 BODY_EXPOSE 에서 빼 체형으로 보냈다 — pool 루프에 명시 배정을 남겨
# '미분류'로 보고되지 않게 한다(체형 축에는 위에서 이미 넣었다).
_assign.update({t: None for t in BODY_TO_TYPE})
for _s in (MOVED_OUT, GORE, NEAR_DUP, WEAR2, NEGATIVE):
    _assign.update({t: None for t in _s})
exp, feat, nonhuman, nsfw, horns, unclassified = [], [], [], [], [], []
_dest = {"body_expose": exp, "body_feature": feat, "body_nonhuman": nonhuman,
         "body_nsfw": nsfw, "horns": horns}
for t in body:
    if t in _assign:                      # 명시 배정이 최우선
        d = _assign[t]
        if d: _dest[d].append(t)
        continue
    # EXCLUDE 는 아래 축별 루프에서 일괄 제거되므로 여기서 따로 걸러내지 않는다.
    if HORN_RE.search(t): horns.append(t)  # 뿔은 독립 축
    elif NSFW.search(t): nsfw.append(t)
    elif FEATURE.search(t): feat.append(t)
    else: unclassified.append(t)          # catch-all 금지 — 드러내서 손으로 배정한다
AXES["body_expose"], AXES["body_feature"] = exp, feat
# BODY_NONHUMAN 에는 pool(body_parts/hands/ass/shoulders) 밖의 태그도 있다 —
# prosthetic/mechanical/body_meta/surreal subgroup 은 그 pool 에 안 잡힌다.
# STATE 와 같게 목록을 직접 합치고 데이터 존재만 확인한다(EXCLUDE 는 뒤에서 걸린다).
nonhuman = nonhuman + [t for t in BODY_NONHUMAN if t in raw and t not in nonhuman]
AXES["body_nonhuman"], AXES["body_nsfw"], AXES["horns"] = nonhuman, nsfw, horns
# STATE 는 Person_Body 뿐 아니라 Expression_Action / Composition_Meta / Clothing_Wear 에도
# 흩어져 있어 pool() 로는 못 모은다. 목록 그대로 쓰고 데이터 존재만 확인한다.
# ── 상태 축 해체 (사용자 판단) ──────────────────────────────────────────────
# 조사 결과 상태 59개는 4개 개념의 묶음이었고, 누적 빈도의 78%가 실제로는 표정이었다.
# 데이터도 그렇게 말한다 — tears/blush/saliva/sweatdrop 의 subgroup 은 expression 이고
# blush 설명은 "부끄러움 등으로", sweatdrop 은 "긴장이나 당혹감을 나타내는" 이다.
# 그래서 슬롯을 없애고 성격대로 분배한다. 이미 생성한 이미지는 --prune 이 축만 옮긴다.
#   감정의 부수 현상 + 생리 상태 -> 표정 슬롯의 썸네일 축
#   부상·오염 -> 신체 슬롯의 별도 섹션(신체 특징에 섞으면 영구 특징과 일시 부상이 뒤섞인다)
#   머리 상태 -> 머리 모양 축
#   wet / steam -> 효과, wet clothes -> 의상 (각 그룹의 browse 가 자동으로 담당)
EXPRESSION_STATE = [
    # 감정의 시각적 표현
    "blush", "nose blush", "light blush", "full-face blush", "ear blush",
    "blushing profusely", "blush stickers", "tears", "tearing up",
    "saliva", "saliva string", "saliva trail", "drooling",
    "sweatdrop", "flying sweatdrops", "nervous sweat",
    "heavy breathing", "panting", "tired",
    # 생리 상태 — 감정과 같은 화면(얼굴)에 나타난다
    "sweat", "very sweaty", "sweating profusely", "sweaty armpits",
    "steaming body", "trembling", "shivering", "unconscious",
]
# ── 표정 축 (Codex 리뷰 REQUEST-CHANGES 15/18/7 반영) ───────────────────────
# 표정 후보 254개를 전수 손배정했다. 핵심 교정 두 가지는 내가 놓친 것이다.
#   1) 2인 이상이 필요한 태그 9개(cheek-to-cheek, licking another's face,
#      forehead-to-forehead ...)를 액션에 두고 있었다. Interactive 는 캐릭터 1명
#      기준이라 상대가 없으면 렌더될 수 없다 -> 제외.
#   2) 눈썹 4개(raised eyebrows/furrowed brow/raised eyebrow/cocked eyebrow)는
#      감정이 아니라 구조다 -> 눈·입 형태 축.
# 그 밖에 teardrop("희화적으로 묘사")·head steam 은 기호로, drunk/tipsy 는 상태로,
# facepaint 는 표식으로 옮겼고, ara ara 는 NSFW 에서 뺐다(성적 함의가 명시적이지 않다).
EXPRESSION_EMOTION = [
    'smile', 'grin', 'expressionless', 'frown', 'embarrassed', 'happy',
    'crying', 'light smile', 'surprised', 'crying with eyes open', 'angry',
    'serious', 'pout', 'smirk', 'smug', 'light frown', 'laughing',
    'scared', 'evil smile', 'nervous', 'annoyed', 'sad', 'sleepy', 'wince',
    'shy', 'streaming tears', 'nervous smile', 'evil grin',
    'gloom (expression)', 'scowl', 'thinking', 'grimace', 'confused',
    'worried', 'false smile', 'jealous', 'doyagao', 'happy tears',
    'crazy smile', 'disgust', 'unamused', 'excited', 'exhausted',
    'blank stare', 'gesugao', 'determined', 'panicking', 'hungry',
    'unhappy', 'forced smile', 'sobbing', 'depressed', 'single tear',
    'sad smile', 'curious', 'furious', 'clueless', 'horrified', 'tantrum',
    'despair', 'traumatized', 'giggling', 'disdain', 'disappointed',
    'lonely', 'sneer', 'distress', 'awestruck', 'grumpy', 'crazy grin',
    'mourning', 'peaceful', 'envy', 'deadpan',
]
EXPRESSION_SYMBOL = [
    ':d', ':o', ':3', '^_^', ';d', '>_<', '...', '^^^', 'anger vein', ':p',
    '@_@', ':q', ':<', '+_+', ';)', ':t', '!?', '=_=', '>:)', 'o_o', '|_|',
    ':>', ':/', '=3', ';o', 'zzz', ':|', '3:', '0_0', 'd:', 'teardrop',
    'spoken blush', ';p', 'xd', '>:(', ';q', ':i', '>_o', ';3', 'u_u',
    '^o^', 'o3o', 'x_x', '._.', 'c:', '>o<', ':x', '<o>_<o>', '...?',
    '<|>_<|>', ';(', 'x3', 'head steam', ':c', ';<', '...!', 'd;', ';t',
    ';>', 'uwu', 'dx', 't t', ';|', '3_3', '>3<', '+_-', '6_9',
]
FACE_SHAPE = [
    'open mouth', 'closed mouth', 'closed eyes', 'one eye closed',
    'half-closed eyes', 'wavy mouth', 'raised eyebrows', 'furrowed brow',
    'chestnut mouth', 'triangle mouth', 'raised eyebrow', 'sideways mouth',
    'dot mouth', 'cheek squash', 'cheek bulge', 'puffy cheeks',
    'rectangular mouth', 'square mouth', 'diamond mouth',
    'heart-shaped mouth', 'cocked eyebrow',
]
FACE_CONDITION = [
    'food on face', 'drunk', 'nosebleed', 'mouth drool', 'turn pale',
    'blood from mouth', 'dirty face', 'snot', 'nose bubble',
    'bruise on face', 'pain', 'paint splatter on face', 'saliva drip',
    'rice on face', 'wet face', 'runny nose', 'chocolate on face',
    'full mouth', 'bruised eye', 'fever', 'foaming at the mouth',
    'snot trail', 'dizzy', 'dazed', 'bleeding from forehead',
    'steam from mouth', 'slap mark on face', 'veiny face',
    'blood on mouth', 'tipsy', 'headache', 'mouth submerged', 'hangover',
]
# ⚠️ 이 7개를 `body_nsfw` 로 보낸 것은 **내 오분류였다**(2026-07-28 정정).
# 성적 함의가 있다고 판단했지만 화면에 보이는 것은 **표정과 홍조**다 — 노출이 아니다.
# `naughty face`(14,948)·`seductive smile`(6,925) 는 표정이고, `body blush` 계열은
# 홍조 범위다. 성인 축에 두면 그 축은 보류라 영영 안 나온다.
FACE_EXPR_MISFILED = [
    'naughty face', 'seductive smile', 'moaning',
    # 서브그룹이 `image_composition` 이라 구도 축으로 잡혀 있었다. 실제로는 "혐오스러운
    # 것을 보거나 절망적일 때 당황하는 표정"이다(사용자 확인 2026-08-01).
    'shaded face',
]
BLUSH_MISFILED = [
    'body blush', 'shoulder blush', 'knee blush', 'full-body blush',
]
FACE_NSFW = []

# ── 그룹 이름이 갈려 빠진 것을 끌어온다 ──────────────────────────────────────
# 태그 사전 대조에서 `Expressions` 그룹 28개가 통째로 빠진 것을 찾았다(2026-08-02).
# 축 빌더는 `Expression_Action` 만 훑는데 같은 개념이 다른 이름으로도 있다.
# 목록을 적지 말고 그룹으로 끌어온다 — 이름이 또 갈려도 규칙만 고치면 된다.
from tools.nsfw_explicit_vocab import is_explicit_vocab as _is_explicit_vocab

_PULL_CUT = 3000


def _other_axis_tags():
    """다른 빌더가 이미 가져간 태그. 안 빼면 한 태그가 두 축에 들어가고,
    팩 키가 `<축>/<태그>` 하나뿐이라 뒤쪽 축이 영영 안 찬다(실측: looking pleasured
    가 pose_gaze 와 expression 양쪽에 들어갔다)."""
    own = set()
    for _p in list(Path("wildcards/thumb").glob("*.txt")) + list(Path("wildcards/nsfw").glob("*.txt")):
        if _p.stem.startswith("_") or _p.stem.startswith("expression"):
            continue          # 자기 축은 빼면 두 번째 실행에서 비어 버린다
        for _l in _p.read_text(encoding="utf-8").splitlines():
            if _l.strip() and not _l.startswith("#"):
                own.add(_l.strip())
    return own


_OTHER_AXIS = _other_axis_tags()


def _pull_by_group(groups, subgroups=None, skip=()):
    """지정 그룹(과 서브그룹)에서 빈도 컷 이상인 태그. 이미 다른 축이 가진 것은 뺀다."""
    out = []
    for _t, _d in raw.items():
        if int(_d.get("freq", 0) or 0) < _PULL_CUT:
            continue
        _g = str(_d.get("group", "") or "")
        if not any(_g == _x or _g.startswith(_x) for _x in groups):
            continue
        if subgroups is not None and str(_d.get("subgroup", "") or "") not in subgroups:
            continue
        if _t in skip or _t in _OTHER_AXIS:
            continue
        if _is_explicit_vocab(_t):
            continue          # 성인 어휘는 도감 소관(실측: vulva blush 가 표정으로 샜다)
        out.append(_t)
    return sorted(out, key=lambda x: -int((raw.get(x) or {}).get("freq", 0) or 0))

AXES["expression"] = ([t for t in EXPRESSION_EMOTION if t in raw]
                      + [t for t in FACE_EXPR_MISFILED if t in raw])
# 자세 분류에서 넘어온 눈 태그(rubbing eyes, averting eyes ...). 전신 축으로 갈 뻔한
# 것을 build_pose_axes 가 얼굴 스케일로 돌려 `expression_from_pose.txt` 에 적어 둔다.
# 여기서 합치지 않으면 파일만 있고 어느 축에도 안 속해 팩에서 통째로 빠진다.
_FROM_POSE = Path("wildcards/thumb/expression_from_pose.txt")
if _FROM_POSE.exists():
    _extra = [l.strip() for l in _FROM_POSE.read_text(encoding="utf-8").splitlines() if l.strip()]
    _seen = set(AXES["expression"])
    AXES["expression"] += [t for t in _extra if t in raw and t not in _seen]
# `Expressions` 그룹(영문 복수형)을 한 번 끌어왔다가 **되돌렸다**(2026-08-02).
# 33개 전부가 Danbooru 풀(140만 건)에 없다 — e621 어휘다. `source` 필드는 판별에
# 못 쓴다(패션 그룹도 비어 있는데 100% Danbooru 다). **Danbooru 풀 존재 여부**가
# 정확한 판별자다. 사용자 지시로 e621 은 제외한다.
#   AXES["expression"] += _pull_by_group(("Expressions",), skip=...)

AXES["expression_symbol"] = [t for t in EXPRESSION_SYMBOL if t in raw]
# 홍조는 `홍조·눈물·땀` 축이 이미 담당한다.
AXES["expression_state"] = (AXES.get("expression_state", [])
                            + [t for t in BLUSH_MISFILED if t in raw])

# ── 성격·유형(persona) ──────────────────────────────────────────────────────
# 태그 DB 가 이미 `Expression_Action/personality` 로 분류해 둔 것을 그대로 쓴다.
# 원래 자세 fallback 이 이것들을 `pose_display` 로 쓸어넣었는데, 성격은 자세가 아니다.
#
# ⚠️ "렌더가 안 된다"는 첫 판정은 틀렸다 — 192px 컨택트 시트로 봐서 그렇게 보였을 뿐,
# 원본은 제대로 나온다(`jimiko` = 검은 뿔테+단발+홍조+뒷짐, `mesugaki` = 내려보는
# 눈+도발적 웃음+트윈테일). 축소본으로 판정하지 말 것.
#
# 성격은 머리·의상·표정을 한꺼번에 바꾸므로 **의상을 고정하지 않는** 벤치를 쓴다
# (`_bench.json` 의 `persona` 배치). 자세 템플릿의 `white shirt, pleated skirt` 가
# 표현 통로 하나를 막고 있었다.
_PERSONA_DROP = {
    "ptsd",              # 정신질환이지 시각 원형이 아니다
    "muscular uke",      # BL 전용. 이미 pose_drop 에 있다
    "female pervert",    # 성적 함의
    "height conscious",  # 관계 서술(상대와 비교) — 성격이 아니다
    "age conscious",     # 위와 같음
    "unaware",           # 장면 상태
}
_PERSONA_ADD = ["yandere"]   # personality subgroup 에 없는데 같은 부류다(freq 3,500)
_persona_src = list(idx._tree.get("Expression_Action", {}).get("personality", []))
AXES["persona"] = [t for t in _persona_src + _PERSONA_ADD
                   if t in raw and t not in _PERSONA_DROP]

AXES["face_shape"] = [t for t in FACE_SHAPE if t in raw]
# facepaint 는 의도적 얼굴 무늬라 표식 축이 맞다(Codex 지적).
AXES["marking"] = AXES["marking"] + [t for t in ["facepaint"] if t in raw]
# 성적 함의가 명시된 7개는 노출(성인) 축으로. 그 축은 보류라 생성하지 않는다.
AXES["body_nsfw"] = (AXES["body_nsfw"]
                     + [t for t in FACE_NSFW if t in raw]
                     # MARKING_TO_NSFW 는 piercings/skin_markings subgroup 이라
                     # body pool 루프에 안 잡힌다 -> 여기서 직접 합친다.
                     + [t for t in MARKING_TO_NSFW if t in raw])
# 얼굴 오염·부상은 아래 BODY_CONDITION 정의에 FACE_CONDITION 으로 합류한다.
BODY_CONDITION = [
    # 부상(ryona) — 일시적 상태라 '신체 특징'(영구)과 섞지 않고 별도 축으로 둔다
    "injury", "bruise", "cuts", "scratches", "bleeding", "stitches",
    "blood on face", "blood on hands", "blood on arm", "blood on leg", "blood on chest",
    "slap mark", "whip marks", "broken arm", "broken leg", "bite mark", "hickey",
    "bandages", "bandaged arm", "bandaged leg", "bandaged head", "bandaged hand",
    "bandage over one eye",
    # 오염
    "dirty", "dirty feet", "dirty hands", "soaking feet",
    # 얼굴 오염·부상(Codex 리뷰 분류) 합류 — 같은 성격이다.
    *FACE_CONDITION,
    *BODY_TO_CONDITION,
]
HAIR_STATE = ["wet hair", "messy hair"]
AXES["expression_state"] = [t for t in EXPRESSION_STATE if t in raw]
AXES["body_condition"] = [t for t in BODY_CONDITION if t in raw]
AXES["hair_style"] = AXES["hair_style"] + [t for t in HAIR_STATE
                                           if t in raw and t not in AXES["hair_style"]]
STATE = EXPRESSION_STATE + BODY_CONDITION + HAIR_STATE
_missing_state = [t for t in STATE if t not in raw]
# 상태 축은 해체됐다 — 아래 dedup/보고에서 쓰던 이름만 유지한다.
# body_* 축에 STATE 태그가 남아 있으면 중복이므로 뺀다.
_state_set = set(AXES["expression_state"]) | set(AXES["body_condition"])
# state 는 머리(messy hair / wet hair)와도 겹친다. 같은 태그가 두 축에 있으면 두 번
# 생성되고 팩 키도 갈린다(빌더는 먼저 읽은 축으로 배정한다) -> 여기서 한쪽만 남긴다.
for _k in ("body_expose", "body_feature", "body_nonhuman", "body_nsfw", "horns",
           "hair_style", "bangs", "ears", "tail", "wings", "skin", "species"):
    AXES[_k] = [t for t in AXES[_k] if t not in _state_set]

# 축에서 제외 — 단독 썸네일로 성립하지 않거나, 초보자 원클릭 칩으로 부적합한 것들.
# body_type 63장 실측(20260725_103742/body types)에서 드러난 목록이다.
# 연령·성적 함의 태그(loli/baby/toddler/muscular child)는 제외하지 않는다 —
# 사용자 판단: 필요한 고객이 있다.
# three sizes 는 도표 태그로 보였지만 이미 생성·승인된 이미지가 있어 남긴다.
EXCLUDE = {
    # 단독 이미지로 표현 불가 — 원작 대비 비교가 필요
    "alternate pectoral size",
    # 데이터가 스스로 "모호한 태그"라고 명시 — 다른 태그로 유도된다
    "tall",                      # -> height chart / tall female
    "no arms",                   # -> double amputee / cropped arms
    # 체형이 아니라 다른 축의 성격
    "flexible",                  # 자세/가동성 -> 액션
    "mutant",                    # 이형 -> 종족
    "sway back",                 # 자세 -> 액션 (arched back / leaning back 과 같은 개념)
    # NAI 재현 실패(실측) — 여러 시도에도 태그가 그림에 반영되지 않았다.
    "no legs",                   # freq 106
    "small head",                # freq 68
    # 데이터가 스스로 폐기/모호라고 명시한 것 + 신체 부위가 아닌 것 + 중복
    "hands",                     # "폐기된 태그" -> hand focus
    "bad hands",                 # 잘못 그려진 손 — 네거티브용
    "head",                      # portrait / disembodied head 를 쓰라고 명시
    "torso", "innerboob",        # "모호한 태그"로 명시
    "mute",                      # 말을 못하는 캐릭터 — 신체 부위가 아님
    "gigantic breasts",          # 가슴 슬라이더 6단에 이미 있다(중복)
    "single barefoot",           # barefoot 과 썸네일로 구분 불가
    "nose",                      # 얼굴 축(face)이 dot nose / animal nose 로 담당
    # body_feature 감사 — 데이터가 스스로 폐기/모호라고 명시하거나 다른 축이 담당
    "too many scars",            # 데이터: "scars_all_over 로 이동되었습니다"
    "oni horns",                 # 데이터: "모호한 태그" -> cone horns / skin-covered horns
    "veins",                     # veiny arms/hands/thighs 로 이미 세분화 — 중복
    "mole on body",              # 데이터: 더 구체적인 위치 태그를 쓰라고 명시
    "large horns",               # 설명이 비어 있음 — huge/long horns 와 구분 불가
    "cat paw",                   # 데이터: 손 대신 발이면 cat paws(이형 축)
    "hair between horns",        # 머리카락 배치 -> 머리 축
    "head bump",                 # 코믹 효과 -> 효과 슬롯
    # 라이브 실측 재현 실패 — 피부 축(사용자가 생성 후 제거)
    "deep skin",                 # 8138. '피부를 깊게 잡아 손가락이 파묻히는' = 행위, 피부색 아님
    "alternate skin color",      # 1496. "공식 설정과 다른" — 원작 대비 비교 필요
    "asian",                     # 665. 인종 묘사 — 피부 썸네일로 구분 불가
    # 라이브 실측 재현 실패 — 노출·강조 축
    "single bare leg", "single bare arm",   # 한쪽만 노출 — 썸네일에서 좌우 구분 불가
    "covered armpit",            # 옷 너머 윤곽 — 판별 불가
    # ── 노출(성인) 축 정리: 자세/행위는 신체 특징이 아니다 ──────────────────
    "spread ass", "spread anus",       # 데이터: "벌려 노출시키는 행위"
    "hands on own crotch",             # 데이터: "손을 올리는 자세"
    "cum on hands", "pussy juice on fingers",   # 행위의 결과
    "stomach bulge",                   # "내부에서 무언가가 밀어내어" — 행위 의존
    # (`hanging breasts`·`bursting breasts` 는 EXCLUDE 에서 뺐다. 판정은 옳았다 —
    #  각각 자세 의존·의상 맞음새 의존이다. 그런데 그건 '버릴 것'이 아니라 '신체
    #  특징이 아닌 것'이라는 뜻이었다. `breasts apart`·`breast press` 가 있는
    #  `body_suggestive` 로 보낸다. 추천에서 글자 칩으로만 뜨던 원인이 이 이중
    #  제외였다 — 이름 규칙과 EXCLUDE 양쪽에 걸려 어느 축에도 못 들어갔다.)
    "areolae",                         # 데이터: "폐기된 태그"
    "no nipples", "no anus",            # 원작 대비 비교가 필요한 부정 태그
    "stray pubic hair",                # 떨어진 털 한 가닥 — 썸네일 판별 불가
    "mole on crotch",                  # 점 위치 변형 — 앞서 제거한 mole on X 와 같은 논리
    "heart-shaped pubic hair",         # shaped pubic hair 의 하위 — 중복
    # ── 신체 특징 축 라이브 실측(68/72) 후 재현 실패분 ────────────────────
    "multiple moles",            # 2147. 점 여러 개 — 192px 에서 mole 과 구분 불가
    "armpit stubble",            # 122. 면도 후 그루터기 — 판별 불가
    "small hands",               # 94. 손 크기 비율 — cowboy shot 에서 판별 불가
    "jaw",                       # 62. 턱 — 얼굴이 프레임 밖
    # ── 생성 전 검수(남은 축 703개) — 데이터가 명시한 것만 뺀다 ─────────────
    # 판단 기준은 내 취향이 아니라 태그 설명이다. niche/저빈도라고 빼지 않는다
    # (사용자 지적: ">60이면 다 유의미한 태그들입니다").
    # 머리 모양의 '폐기/모호' 지적 8건(french braid, tied hair, hair strand,
    # low tied hair, twisted hair, hair dye, folded hair, tall hair)은 제외하지
    # 않는다. Danbooru 의 폐기는 '태깅 규범'이고 NAI 렌더 가능성과 무관하다 —
    # 실제로 8개 전부 이미 생성된 이미지가 있다. 규범 때문에 뽑아둔 걸 버리지 않는다.
    "no animal ears", "alternate animal ears", "alternate ears",   # 부정/원작대비
    "no wings", "no tail",       # 부정 태그
    "laevatein (tail)",          # 210. "악마 꼬리를 참고하세요" — demon tail 중복
    "extra tails",               # 120. multiple_tails 를 쓰라고 명시
    "hybrid",                    # 198. "애매한 태그" — fusion/chimera 사용
    "mini dragon",               # 152. "small_dragon 으로 이동되었습니다"
    "beast",                     # 78. "모호한 태그" — monster 사용
    *SPECIES_CUT,                # 종족 정리(위 SPECIES_MIN_FREQ / RESCUE 규칙)
    # ── Vision 검수 2차: NAI 가 태그를 렌더하지 않은 것들(실측) ──────────
    "fins",                      # "물고기 인형을 든 소녀" — dorsal/shark fin 과 중복
    "crab claw",                 # "손 위에 게 한 마리" — 집게손이 안 된다
    "dragon (arms)",             # 노란 인형을 든 소녀
    "prehensile ribbon",         # 아무것도 렌더되지 않는다
    "blowhole", "extra breasts", "fluff",   # 아무것도 렌더되지 않는다
    "no bangs",                  # 앞머리가 그대로 남는다(부정 태그)
    # ── 종족·수인 슬롯 (Codex 리뷰 9/2) ───────────────────────────────────
    "male with breasts",         # 성별 특성 — 이형 종족 특징이 아니다
    "conjoined",                 # "두 명 이상의 사람이 이어져" — 단일 캐릭터 불가
    "extra horns",               # 원작 비교 필요 + 데이터가 multiple horns 안내
    "hedgehog ears", "hedgehog tail",   # 데이터가 성별별 태그를 "참고하세요"
    "ear down",                  # ears down(3757)과 동일 — 빈도 높은 쪽만 남긴다
    "ox horns",                  # 데이터가 cow horns(12038)와 똑같이 "소나 황소의 뿔"
    # ── 얼굴·종족 슬롯 (Codex 리뷰 27/3) ─────────────────────────────────
    "pouty lips", "chin", "big eyes", "cat nose",   # 데이터가 다른 태그를 쓰라고 명시
    "lipstick mark",             # "단단한 표면에 남긴" — 캐릭터가 아니다
    "snow on head",              # 머리 위 환경 효과 — 얼굴 특징이 아니다
    "alternate facial hair", "no heterochromia", "alternate eyebrows", "no freckles",
    "doppelganger",              # 원작·원본과의 비교가 필요하다
    "angel and devil",           # "천사와 악마가 함께" — 2인 필요
    "familiar",                  # "특정 인물에 의해 소환되는" — 관계 필요
    "kaijuu",                    # "도쿠사츠 엔터테인먼트 장르" — 종족이 아니다
    "octarian",                  # 데이터가 이 태그를 쓰지 말라고 안내
    "box body",                  # 데이터: "표현 스타일" — 체형이 아니다
    "very long fingernails",     # long fingernails 와 정의가 동일("1cm 이상")
    "stand (jojo)",              # 초록 배경만 나온다. 종족이 아니라 초능력 개념
    "duel monster",              # 특징 없이 그냥 소녀. 카드 게임 몬스터 분류라 종족이 아니다
    # ── 표식·기타 재정렬에서 제외 ──────────────────────────────────────
    # 성별·연령 메타: 캐릭터 헤더의 성별 토글이 담당한다
    "otoko no ko", "mature male", "mature female", "bishounen", "girly boy",
    # 구도 메타: 얼굴이 안 보이는 것은 특징이 아니다
    "faceless", "faceless male",
    # 환경 대비 크기 — 단독 썸네일로 표현 불가
    "mini person", "minigirl",
    "alternate breast size",     # 원작 대비 비교가 필요
    "left-handed",               # 왼손잡이는 시각으로 판별되지 않는다
    "disembodied limb",          # 데이터: "분리된 손/발을 참고하세요"
    "disembodied head", "headless",   # 머리 없음 = 고어/구도
    "impossible hair",           # 머리 축이 담당
    # ── 재검수(시드 변경 + 가중치 3.0)에서도 두 번 실패한 것들 ──────────
    "alpaca tail", "giraffe tail",   # 두 번 모두 동물을 통째로 그렸다
    "bandaged head",             # 머리 붕대가 머리띠로만 나온다
    "thorns",                    # 옷만 나오고 가시가 렌더되지 않는다
    "bite mark", "hickey",       # 목/피부 자국이 cowboy 프레이밍에서 옷에 가린다

    # dirty / dirty feet / dirty hands 는 STATE 축으로 살렸다(아래에서 EXCLUDE 에서 뺀다).
}
EXCLUDE -= set(STATE)   # STATE 로 살린 태그는 제외하지 않는다
# 배정 지도 — 유니온(기존 목록 합집합)이 이걸 무시하고 되돌려 넣으면 재분류가 무력화된다.
#   예1: huge ass 를 body_feature 로 옮겨도 기존 body_expose.txt 에 있어 expose 로 되돌아온다.
#   예2: 뿔 32개를 horns 축으로 빼도 기존 body_feature.txt 에 있어 feature 로 되돌아온다.
# 명시 목록(_assign)만으로는 예2를 못 막는다 — 뿔은 정규식으로 배정하기 때문이다.
# 그래서 '이번 계산 결과' 전체를 지도에 넣는다. 임계값 미달로 아예 계산에 없는 태그는
# 지도에 없으므로 그대로 합집합에 들어온다(= 이미 생성한 썸네일 보존이라는 원래 목적).
EXPLICIT = dict(_assign)
EXPLICIT.update({t: None for t in EXCLUDE})
for _ax, _lst in AXES.items():
    for _t in _lst:
        EXPLICIT.setdefault(_t, _ax)

# 1girl 베이스로는 렌더되지 않아 남성 베이스 배치로 따로 돌려야 하는 태그.
# 목록은 `tools/thumb_male_tags.py` 가 SSOT 다 — thumb_axes_emit 도 같은 목록으로 UI 를
# 가르므로, 여기에 손으로 적으면 생성 배치와 화면이 갈라진다(이미 다섯 번 난 사고).
from tools.thumb_male_tags import MALE_ONLY   # noqa: E402

OUT = Path("wildcards/thumb")
NSFW_OUT = Path("wildcards/nsfw")

def _axis_out(key: str) -> Path:
    """성인 축은 썸네일 축 폴더에 두지 않는다 — 거기 있으면 도구가 생성 대상으로 읽는다.
    실제로 문신·피어싱 축을 돌릴 때 성인 태그 4장이 딸려 들어가 팩에 남았다.
    폴더가 곧 정책이다(사용자 결정: 성인은 와일드카드만)."""
    return NSFW_OUT if "nsfw" in key else OUT


def existing(name):
    p = OUT / f"{name}.txt"
    if not p.exists(): return []
    return [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]

# 임계값 때문에 '이미 생성한' 태그가 빠지면 뽑아둔 썸네일이 버려진다 -> 되살린다.
# 단 되살리는 기준은 '기존 목록에 있었는가'가 아니라 **팩에 이미지가 있는가**다.
# 목록 기준으로 하면 방금 다른 축으로 옮기거나 제외한 태그가 그대로 되돌아와 재분류가
# 무력화된다(네 번 겪었다: 명시 배정분 / 정규식 배정분 / 종족 정리분 / state 제거분).
# 이미지 유무를 기준으로 하면 그 사고가 구조적으로 불가능하다 — 목적(생성분 보존)은
# 그대로 달성하면서 재분류를 방해하지 않는다.
_pack_path = Path("data/interactive_thumbnails.json")
_have = {}
if _pack_path.exists():
    import json as _json
    for _key in _json.loads(_pack_path.read_text(encoding="utf-8")):
        _ax, _, _tag = _key.partition("/")
        _have.setdefault(_ax, set()).add(_tag)
kept_below = {}
for _k in list(AXES):
    add = [t for t in sorted(_have.get(_k, ()))
           if t in raw and t not in AXES[_k] and EXPLICIT.get(t, _k) == _k]
    if add: kept_below[_k] = add
    AXES[_k] = AXES[_k] + add

# ── 남성형 종족을 갈라낸다 (팩 복원 **뒤에**) ─────────────────────────────
# 한 축에 섞어 두니 여성 템플릿(`1girl, young female`)으로 전부 생성돼 결과가 두
# 갈래로 깨졌다(실측): `wolf/tiger/lion boy` 는 **머리까지 짐승**이 됐고
# `cat/dragon/fish boy` 는 **수염 난 노년 남성**이 됐다. 여성 쪽은 전부 케모미미라
# 같은 축에 성격이 다른 그림이 섞여 보인다(사용자 지적). 성별은 프레이밍이 아니라
# **베이스 인물**이 다른 것이라 축을 갈라야 한다(`_male` 접미는 hair_style/face 방식).
#
# 위치가 중요하다. 남성형 36개는 대부분 임계값 아래라 pool 에 없고 **팩 복원으로만**
# 들어온다 — 복원 앞에서 가르면 species_male 이 0 이 된다(실측).
_MALE_FORM = re.compile(r'(boy|male|man)$')
AXES["species_male"] = [t for t in AXES["species"] if _MALE_FORM.search(t)]
AXES["species"] = [t for t in AXES["species"] if not _MALE_FORM.search(t)]

total = 0
dropped = []
print(f"freq >= {TH}\n{'축':<14}{'개수':>6}  최상위 예시")
for k in sorted(AXES):
    v = sorted(set(AXES[k]), key=lambda t: -F(t))
    dropped += [t for t in v if t in EXCLUDE]
    v = [t for t in v if t not in EXCLUDE]
    AXES[k] = v
    total += len(v)
    print(f"{k:<14}{len(v):>6}  {', '.join(v[:5])}")
print(f"\n총 {total}장" + ("  (dry-run: 파일 안 씀)" if args.dry else ""))
if dropped:
    print(f"EXCLUDE 로 제외 {len(dropped)}개: {', '.join(sorted(dropped))}")
print(f"썸네일 축 밖으로 이동(액션/효과/의상) {len(MOVED_OUT)}개 / 하드 고어 제외 {len(GORE)}개")
print(f"상태 해체: 표정 {len(AXES['expression_state'])} + 부상·오염 {len(AXES['body_condition'])} + 머리 {len(HAIR_STATE)}" + (f"  데이터에 없어 제외: {_missing_state}" if _missing_state else ""))
# STATE 는 pool 루프 밖에서 배정하므로 여기서 미분류로 보이는 게 정상이다(중복 보고 방지).
_un = [t for t in unclassified if t not in EXCLUDE and t not in set(STATE)]
if _un:
    print(f"!! 미분류 {len(_un)}개 — 명시 배정이 필요하다:")
    for t in sorted(_un, key=lambda x: -F(x)):
        print(f"     {t} ({F(t)})")
else:
    print("미분류 없음 (전부 명시 배정)")

# ── 성인 도감에서 들여오는 것 ──────────────────────────────────────────────
# 태그 DB 가 `NSFW` 그룹으로 분류했지만 그림에는 성적 요소가 없는 것들. 소스의
# `sex_acts`(209개, 가장 큰 통)와 `nudity` 두 서브그룹에 캐릭터 유형과 근육이
# 섞여 들어간 게 원인이다 — 의상에서 `attire` 를 4분할해야 했던 것과 같은 구조.
#
# 여기 적으면 `build_nsfw_act_catalog.py` 가 자동으로 도감에서 뺀다(그쪽이
# `wildcards/thumb/*.txt` 를 전부 `taken` 으로 읽는다). 목록은 한 벌이다.
IMPORTED_FROM_NSFW = {
    # 인물 유형 — 소스 서브그룹 `sex_acts`. 행위가 아니라 무엇으로 그려지느냐다.
    "furry": "species", "furry female": "species", "monster girl": "species",
    "monster": "species",
    "furry male": "species_male", "monster boy": "species_male",
    # 여성 거인. 성적 요소가 없고 `monster girl` 과 같은 인외 계열이다(사용자 판단
    # 2026-07-29). 흰 배경에서 크기가 안 읽힐 우려로 보류했었는데, 종족 축은
    # 어차피 무엇으로 그려지느냐를 고르는 곳이라 여기가 맞다.
    "giantess": "species",
    # 동물귀를 붙이는 것 자체. `fake animal ears` 와 같은 계열이라 귀 축이 맞다.
    "kemonomimi mode": "ears",
    # 남성 가슴 근육 — 소스 서브그룹 `nudity`. `abs` · `muscular male` 과 같은 계열인데
    # 10만 태그가 신체 축에 아예 없었다(오분류인 동시에 커버리지 구멍).
    "pectorals": "body_type", "large pectorals": "body_type",
    "huge pectorals": "body_type",
    # `loli` · `child` · `miniboy` 가 이미 체형 축에 있는데 남성 짝만 성인 목록에
    # 남아 있었다. `rating:general` 로 뽑으면 그냥 어린 소년이고 성적 대상이 아니다
    # (사용자 판단 2026-07-30). **성인 배치 가드는 그대로 산다** — `_DANGER_AGE` 가
    # `shota` 를 계속 막으므로, 이 태그는 SFW 체형 템플릿으로만 그려진다.
    "shota": "body_type",
    # 음식 흘린 자국. 형제 태그 `food on face`(12,176)가 이미 이 축에 있다 —
    # 그쪽은 `Expression_A` 그룹인데 이것만 `NSFW` 로 튀었다.
    "cream on face": "body_condition",
}
for _t, _dest in IMPORTED_FROM_NSFW.items():
    if _t not in raw:
        raise SystemExit(f"IMPORTED_FROM_NSFW: 태그 DB 에 없다 -> {_t!r}")
    # **기존 축에만 넣을 수 있다.** 아래 저장 루프가 `AXES` 의 키마다 파일을 통째로
    # 덮어쓰므로, 새 키를 만들면 그 축 파일이 이 한 줄로 날아간다.
    if _dest not in AXES:
        raise SystemExit(f"IMPORTED_FROM_NSFW: 없는 축 -> {_dest!r} (파일을 덮어쓴다)")
    if not any(_t in _v for _v in AXES.values()):
        AXES[_dest].append(_t)

# ── 2026-08-03 재분류 (사용자 지시) ────────────────────────────────────────
# 손으로 옮긴 배치를 **여기 남긴다**. 이 스크립트는 아래 저장 루프에서 축 .txt 를
# 통째로 덮어쓰므로, 여기 없으면 다음 실행에 원래 자리로 돌아간다 —
# 실측으로 30개가 소실되는 것을 확인하고 박아 넣었다.
#
# 기준은 하나다: **그 태그가 캐릭터의 무엇을 정하는가.**
RECLASSIFIED = {
    # 이름에 breasts 가 있을 뿐 가슴 '크기'가 아니라 몸의 생김새다.
    # `veiny arms`·`perky breasts` 와 같은 줄에 있어야 한다.
    "sagging breasts": "body_feature",
    "veiny breasts": "body_feature",
    # 2026-08-04 — 추천에서 글자 칩으로만 뜨던 것들(사용자 지적 전수조사분).
    "bandaged fingers": "body_condition",
    "paint on body": "body_condition",
    "paint on fingers": "body_condition",
    "bandaid on ass": "body_condition",
    "torn skin": "body_condition",
    "surgical scar": "body_condition",
    "taped fingers": "body_condition",
    "stomach growling": "body_condition",
    "full stomach": "body_condition",
    "glowing lines": "marking",
    "tramp stamp": "marking",
    "cutie mark": "marking",
    "holographic horns": "horns",
    "drawn horns": "horns",
    "transparent horns": "horns",
    "giant hand": "body_nonhuman",
    "glowing hands": "body_nonhuman",
    "ghost hands": "body_nonhuman",
    "stretched limb": "body_nonhuman",
    "goat legs": "body_nonhuman",

    # 2026-08-04 — `pose_drop`(자세 분류기의 잔여 버킷 82개) 해체분.
    # 자세 빌더가 "자세가 아니다"라고 버렸는데 버린 곳이 화면에 안 나오는 축이라
    # 그대로 사라져 있었다. 실제로는 표정이 대부분이었다.
    "cream on body": "body_condition",   # `cream on face` 옆
    **{_t: "expression" for _t in [
        "glaring", "defeat", "staring", "flustered", "failure", "remembering",
        "crazy", "charisma break", "concentrating", "frustrated", "lovestruck",
        "brain freeze", "awkward", "roaring", "jaw drop", "ara ara", "burp",
        "humming", "stifled laugh", "snort", "spicy", "mutsuki face", "sulking",
        "gasp", "ruined for marriage", "narcissism", "troll face", "gao",
    ]},
    **{_t: "expression_symbol" for _t in [
        ":s", "xo", "3;", ";/", "mg mg", "eye symbol", "eye pop",
    ]},
    **{_t: "expression_state" for _t in ["flying teardrops", "hand blush"]},
    # 사람이 아닌 얼굴 부위. 얼굴 축에 있었지만 `head fins`·`gills`·`hooves` 쪽이 맞다.
    "beak": "body_nonhuman",
    "snout": "body_nonhuman",
    "animal nose": "body_nonhuman",
    "pig nose": "body_nonhuman",
    "tusks": "body_nonhuman",
    "whiskers": "body_nonhuman",
    "forked tongue": "body_nonhuman",
    "prehensile tongue": "body_nonhuman",
    # 부상·오염에 섞여 있던 표정·생리 상태. 근접 중복이 슬롯을 넘어 갈려 있었다 —
    # `mouth drool` <-> `drooling`, `steam from mouth` <-> `steaming body`.
    "mouth drool": "expression_state",
    "saliva drip": "expression_state",
    "steam from mouth": "expression_state",
    "drunk": "expression_state",
    "tipsy": "expression_state",
    "hangover": "expression_state",
    "dizzy": "expression_state",
    "dazed": "expression_state",
    "turn pale": "expression_state",
    "pain": "expression_state",
    "headache": "expression_state",
    "fever": "expression_state",
    "snot": "expression_state",
    "snot trail": "expression_state",
    "runny nose": "expression_state",
    "nose bubble": "expression_state",
    "foaming at the mouth": "expression_state",
    # 피어싱은 얼굴 '부위'가 아니라 표식이다.
    "chin piercing": "marking",
    "tongue piercing": "marking",
    # 얼굴에 있던 것 — 다른 `blood on *` 는 전부 부상 축이다.
    "blood on teeth": "body_condition",
    # 빌더가 species_male 로 보내지만 실사용은 여성 수인 서술이다.
    "furry female": "species",
}
# 이 빌더가 소유하지 않는 축으로 옮긴 것. 여기 두면 두 축에 겹쳐 나온다.
MOVED_TO_FOREIGN_AXIS = {
    "doll joints",        # -> mech (기계·사이보그)
    "subdermal port",     # -> mech
    "fake facial hair",   # -> cloth_accessory (`fake mustache`·`fake beard` 옆)
    # 2026-08-04 — 신체 pool 에 있었지만 자세·구도·의상이다.
    "hanging breasts", "bursting breasts",           # -> body_suggestive (자세)
    "pov hands",                                     # -> view_angle
    "inconvenient breasts", "convenient breasts",    # -> view_layout
    "back bow",                                      # -> cloth_detail
    "between fingers", "twiddling fingers",
    "card between fingers", "clipping nails",        # -> pose_hand
    "face in hands", "fingers to cheek",             # -> pose_face_touch
    "hands on ass", "hands on thighs", "hands on legs",
    "hands on shoulders", "hands on stomach",        # -> pose_body_touch
    # 2026-08-04 — pose_drop 해체분 중 이 빌더 밖으로 간 것.
    "spoken ellipsis",                               # -> fx_symbol (말풍선)
    "crossdressing", "reverse trap",                 # -> cloth_style
    "sitting on desk", "on vehicle", "sitting on tree stump",   # -> pose_posture
    "holding head",                                  # -> pose_face_touch
    "hand on leg", "hand on thigh", "hand on shoulder", "belly poke",
    "brushing hair", "drying hair", "cutting hair", "playing with hair",
    "applying makeup",                               # -> pose_hand
    "licking finger", "holding sheath", "hugging tail",
}


def _strip_from_axes(tag: str) -> None:
    for _v in AXES.values():
        while tag in _v:
            _v.remove(tag)


for _t, _dest in RECLASSIFIED.items():
    if _t not in raw:
        raise SystemExit(f"RECLASSIFIED: 태그 DB 에 없다 -> {_t!r}")
    if _dest not in AXES:
        raise SystemExit(f"RECLASSIFIED: 없는 축 -> {_dest!r} (파일을 덮어쓴다)")
    _strip_from_axes(_t)
    AXES[_dest].append(_t)
for _t in MOVED_TO_FOREIGN_AXIS:
    _strip_from_axes(_t)

# 남성 베이스 배치는 파일을 나눠 내보낸다(1girl 베이스에서는 렌더되지 않는다).
male_split = {}
for k, v in AXES.items():
    m = [t for t in v if t in MALE_ONLY]
    if m:
        male_split[k] = m
if male_split:
    print("남성 베이스 분리 배치:")
    for k, m in male_split.items():
        print(f"  {k}: {len(m)}개 -> _male/{k}.txt  ({', '.join(m)})")

if not args.dry:
    for k, v in AXES.items():
        _axis_out(k).mkdir(parents=True, exist_ok=True)
        (_axis_out(k) / f"{k}.txt").write_text("\n".join(v) + "\n", encoding="utf-8")
    print(f"{len(AXES)}개 파일 저장  (미생성 배치 목록은 make_todo.py 가 만든다)")
