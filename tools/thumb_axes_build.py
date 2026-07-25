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
                  r'|spread (ass|anus)|oppai|hanging breasts|sagging breasts|naked'
                  r'|veiny breasts|bursting breasts|breast slip|nude', re.I)
FEATURE = re.compile(r'horn|antler|claw|talon|pawpad|paw\b|fin\b|fins|antenna|scale'
                     r'|scar|cut\b|cuts\b|burn|bite mark|wound|bruise|injury|stitch'
                     r'|mole|freckle|birthmark|marking|tattoo|nail|fang|tusk|hoof|hooves'
                     r'|skeleton|\bbone\b|skull|eyeball|joint|suction|thorn|veins?\b'
                     r'|hair\b|hairy|amputee|prosthe|piercing|animal (hands|feet|legs)'
                     r'|bird legs|digitigrade|dirty|blood|hickey|slap mark|bump', re.I)

AXES = {}
# 머리
hair = [t for t in pool(('hair_styles', 'hair'))
        if t not in LENGTH and t not in PATTERN and not BANGS.search(t)]
AXES["hair_style"] = hair
AXES["bangs"] = [t for t in pool(('hair_styles', 'hair')) if BANGS.search(t)]
AXES["hair_pattern"] = [t for t in PATTERN if t in raw]
# 눈 색 패턴
AXES["eye_pattern"] = [t for t in EYE_PATTERN if t in raw]
# 얼굴(전량 유지)
# eye_pattern 축이 따로 담당하는 태그(multicolored eyes 등)는 face 에서 뺀다 —
# 양쪽에 있으면 같은 태그를 두 번 생성하게 되고 팩 키도 갈린다.
AXES["face"] = [t for t in pool(('face_tags', 'eyes_tags', 'face_meta', 'face'))
                if t not in EYE_PATTERN]
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

AXES["ears"] = pool(('ears_tags',))
AXES["tail"] = pool(('tail',))
AXES["wings"] = pool(('wings',))
AXES["skin"] = pool(('skin_color',))
AXES["body_type"] = [t for t in pool(('body_type',)) if t not in BREAST_SIZE]
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
    "armpit crease", "bare back", "shoulder blades", "single bare shoulder", "belly",
    "pectoral cleavage", "backboob", "nape", "neck", "sidepec", "underpec",
    "underbutt", "ass peek", "single bare leg", "single bare arm", "bare hips",
    "toe cleavage", "covered abs", "covered armpit", "palms",
]
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
AXES["body_nonhuman"], AXES["body_nsfw"], AXES["horns"] = nonhuman, nsfw, horns
# STATE 는 Person_Body 뿐 아니라 Expression_Action / Composition_Meta / Clothing_Wear 에도
# 흩어져 있어 pool() 로는 못 모은다. 목록 그대로 쓰고 데이터 존재만 확인한다.
AXES["state"] = [t for t in STATE if t in raw]
_missing_state = [t for t in STATE if t not in raw]
# body_* 축에 STATE 태그가 남아 있으면 중복이므로 뺀다.
_state_set = set(AXES["state"])
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
    "hanging breasts",                 # "몸을 앞으로 숙였을 때" — 자세 의존
    "bursting breasts",                # "옷이 터질 듯한" — 의상 맞음새
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
MALE_ONLY = {
    "muscular male", "toned male", "old man", "fat man",
    "ugly man", "giant male", "miniboy", "strongman waist",
}

OUT = Path("wildcards/thumb")

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
print(f"상태(STATE) 축 {len(AXES['state'])}개" + (f"  데이터에 없어 제외: {_missing_state}" if _missing_state else ""))
# STATE 는 pool 루프 밖에서 배정하므로 여기서 미분류로 보이는 게 정상이다(중복 보고 방지).
_un = [t for t in unclassified if t not in EXCLUDE and t not in set(STATE)]
if _un:
    print(f"!! 미분류 {len(_un)}개 — 명시 배정이 필요하다:")
    for t in sorted(_un, key=lambda x: -F(x)):
        print(f"     {t} ({F(t)})")
else:
    print("미분류 없음 (전부 명시 배정)")

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
        (OUT / f"{k}.txt").write_text("\n".join(v) + "\n", encoding="utf-8")
    print(f"{len(AXES)}개 파일 저장  (미생성 배치 목록은 make_todo.py 가 만든다)")
