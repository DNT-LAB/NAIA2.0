# -*- coding: utf-8 -*-
"""⚠ 이 빌더는 **그냥 돌리면 안 된다.**

축 .txt 는 더 이상 이 스크립트의 출력이 아니다. 오분류를 손으로 고쳐 온 결과가
쌓여 있어 **.txt 가 SSOT** 다. 지금 이대로 실행하면 커밋된 분류에서 태그 141개가
사라진다(2026-08-03 실측, `tools/check_axis_drift.py`).

돌려야 한다면:

    python tools/check_axis_drift.py --only thumb_clothing_build   # 무엇이 사라지는지 먼저 본다
    # 사라질 태그를 이 파일의 명시 배정에 옮긴 뒤에 실행하고,
    python tools/snapshot_axis_classification.py --check   # 분류가 안 어긋났는지 확인

되돌릴 근거는 `data/interactive_axis_snapshot.json` 에 있다.

이 스크립트를 남겨 두는 이유는 하나다 — 태그 사전에 새로 생긴 태그를 축으로
끌어오는 일은 아직 이것만 할 수 있다. 그때도 위 절차를 거쳐라.
"""

"""의상 슬롯 축 분류 — wildcards/thumb/cloth_*.txt 를 생성한다.

특징 슬롯(thumb_axes_build.py)과 분리한 이유: 의상 풀이 4,017개로 특징 전체보다 크고
축 성격도 다르다(부위별 착용물 + 상태/디테일/스타일).

## 규모 결정
freq>=2000 + 제외군 -> 1,052개. 특징 슬롯 실적(1,480장)과 같은 자릿수라 현실적이다.
freq>=60 까지 열면 3,774개로 2.5배가 되어 하루 단위 작업이 불가능하다.

## catch-all 금지
body_expose 에서 '나머지 전부' 버킷을 만들었다가 176개 중 131개가 오분류였다.
여기서는 모든 태그를 명시 배정하거나 명시 제외하고, 남는 것은 '미분류'로 보고한다.
"""
import json
import re
from collections import Counter
from pathlib import Path

from core.kr_tag_loader import load_kr_tag_records
import core.interactive_browse_index as ib

# 절단선. 2000 으로 시작해 864장을 만든 뒤 500 으로 내렸다(사용자 승인, 2026-07-26).
#
# 처음에 "희귀 태그는 렌더가 불안정하다"를 근거로 들었는데 **틀렸다** — 특징 슬롯은
# freq>=60 까지 열어서 잘 나왔다(`harvin` 같은 저빈도 종족도 렌더됐다).
# 실제 제약은 품질이 아니라 분량과 그리드 크기다.
#
# 절단선별 생성 장수(실측): 2000->864 / 1000->1195 / 500->1536 / 200->2068 / 60->2955.
# 200 까지 열면 액세서리 318·제복 203·모자 193 으로 세 축이 그리드 한도(150)를 넘어
# 축 재분할이 선행돼야 한다. 500 은 액세서리 하나만 한도 근처라 그대로 감당된다.
# 절단선 500 -> 149 (사용자 지시 2026-07-27). 이 아래는 한글 설명이 거의 없어
# 그림이 유일한 설명 수단이 된다 — 썸네일의 값이 오히려 큰 구간이다.
CUT = 149
OUT = Path("wildcards/thumb")
NSFW_OUT = Path("wildcards/nsfw")

def _axis_out(key: str) -> Path:
    """성인 축은 썸네일 축 폴더에 두지 않는다 — 거기 있으면 도구가 생성 대상으로 읽는다.
    실제로 문신·피어싱 축을 돌릴 때 성인 태그 4장이 딸려 들어가 팩에 남았다.
    폴더가 곧 정책이다(사용자 결정: 성인은 와일드카드만)."""
    return NSFW_OUT if "nsfw" in key else OUT


raw = load_kr_tag_records().raw
idx = ib.InteractiveBrowseIndex(raw)
F = lambda t: int((raw.get(t) or {}).get("freq", 0) or 0)
D = lambda t: str((raw.get(t) or {}).get("description") or "")

POOL: dict[str, int] = {}
SUB: dict[str, str] = {}
for _s in idx.subgroups("clothing"):
    for _it in idx.tags_in("clothing", _s["id"], 0, 5000)["items"]:
        POOL[_it["tag"]] = _it["count"]
        SUB[_it["tag"]] = _s["id"]

# ── 1. 다른 슬롯으로 내보내는 것 ────────────────────────────────────────────
# 의상 슬롯에 있으나 보이는 것이 옷이 아닌 것들. 목적지 축은 이미 존재한다.
TO_SKIN = [   # 옷이 만든 자국이지만 화면에 보이는 것은 피부색 경계다 -> 신체>피부
    "tanlines", "one-piece tan", "bikini tan", "shorts tan", "shirt tan",
    "revealing tanlines", "tanline peek", "accessory tan",
]
TO_MARKING = [   # 얼굴·손에 칠하는 것. facepaint 를 표식으로 옮긴 것과 같은 논리.
    "makeup", "lipstick", "eyeshadow", "eyeliner", "mascara", "nail polish",
    "black nails", "red nails", "pink nails", "blue nails", "purple nails",
    "green nails", "yellow nails", "orange nails", "white nails", "gold nails",
    "toenail polish", "colored nails", "multicolored nails", "french manicure",
    "sparkle nails", "star nails", "heart nails",
]
TO_CONDITION = [   # 붕대는 부상의 표현이다. 5개는 이미 부상·오염 축에 있어 중복이었다.
    "bandaged arm", "bandaged leg", "bandaged head", "bandaged neck",
    "bandaged wrist", "bandaged chest", "bandaged foot", "bandaged hand",
    "bandaged ankle", "bandaged knees", "bandaged ear", "bandaged tail",
    "bandaged horn", "bandage on leg", "bandages", "bandaid", "bandaid on knee",
    "bandaid on arm", "bandaid on neck", "bandaid on head", "bandaid on shoulder",
    "bandaid on face", "bandaid on cheek", "bandaid on nose", "bandaid on leg",
    "bandages over eyes", "bandage over one eye", "blood on clothes",
]
TO_SPECIES = [   # 초보자는 뿔을 찾으러 뿔 축에 간다. 가짜라도 화면에는 뿔이 보인다.
    "fake horns", "fake wings", "fake antlers", "fake antennae",
    "fake tail", "fake animal ears",
]
# `drawn ears` / `drawn tail` 은 소품이 아니라 몸에 **그린** 표시다(Codex 지적).
# 입체 부속이 아니므로 종족 축이 아니라 문신·표식 축이 맞다.
TO_MARKING_DRAWN = ["drawn ears", "drawn tail", "drawn whiskers"]
MOVED_OUT = {t: dest for dest, lst in (
    ("skin", TO_SKIN), ("marking", TO_MARKING + TO_MARKING_DRAWN),
    ("body_condition", TO_CONDITION), ("species_axes", TO_SPECIES),
) for t in lst}

# ── 2. 제외군 ───────────────────────────────────────────────────────────────
# (a) 규칙 제외 — 이유가 태그 이름/설명에 드러난다.
RE_FRANCHISE = re.compile(r"\(")                     # 작품/캐릭터 한정 의상
# 괄호가 작품명이 아니라 동명이의 구분자인 경우가 있다 — `pom pom (clothes)`(28,680),
# `shrug (clothing)`(16,737), `charm (object)` 등 10개를 통째로 버리고 있었다(Codex 지적).
RE_DISAMBIG = re.compile(
    r"\((clothes|clothing|object|medium|weapon|item|garment|footwear|legwear"
    r"|headwear|accessory|food|animal|plant|vehicle|style)\)$")
RE_COSPLAY = re.compile(r"\bcosplay\b")
RE_UNWORN = re.compile(r"^(unworn|removed) ")        # 아무도 착용하지 않은 옷 = 소품
RE_ALTERNATE = re.compile(r"^(alternate|official alternate|costume switch)")
# "를 사용한다" 형태의 리다이렉트를 빠뜨려 `highleg swimsuit` 가 살아남았다(Codex 지적).
RE_DEPRECATED = re.compile(
    r"(폐기|사용하지|대신 사용|로 대체|모호한 태그|를 사용한다|을 사용한다|를 쓴다)")
# (b) 1인 썸네일에서 렌더 불가 — 상대·비교 대상·원본 디자인이 필요하다.
EXCLUDE_EXPLICIT = {
    "clothes swap", "cosplay", "crossdressing", "gender swap",   # 원본 비교 필요
    "casual", "contemporary",            # "평소와 다른" 의미 — 기준이 없다
    "clothes theft", "undressing another",                       # 2인 필요
    "adjusting clothes", "adjusting headwear", "adjusting hair",  # 손동작 = 액션 슬롯
    "clothes pull", "clothes lift", "skirt lift", "shirt lift",   # 행위 = 액션 슬롯
    "dress lift", "clothes down", "clothing aside",
    # 옷이 없는 상태는 의상 그리드에 둘 것이 아니다(Codex 지적). 태그는 탐색기에 남는다.
    "nude", "completely nude", "nude cover",
    "unbuttoned shirt",                  # open shirt 와 같은 그림
    "reverse outfit",                    # 원래 의상과 비교해야 성립
}
# `multiple belts` / `multiple bracelets` / `multiple rings` 는 '개수 = 구도성'이라고
# 판단해 제외했는데 틀렸다(Codex 지적) — 한 캐릭터가 팔찌를 여러 개 차면 그대로 보인다.

# (c) 색상 조합 — 썸네일을 낭비할 필요가 없다.
# `white shirt` / `black skirt` / `red bow` 는 이름만으로 100% 짐작 가능한데도 각각
# 이미지를 한 장씩 먹는다. 머리/눈/피부 색을 팔레트로 처리한 것과 같은 문제다.
# 여기서는 '본체 태그 + 색 팔레트'로 조합해 emit 하도록 따로 모아둔다(썸네일 생성 제외).
CLOTH_COLORS = [
    "red", "blue", "green", "yellow", "black", "white", "pink", "purple", "orange",
    "brown", "grey", "gray", "silver", "gold", "beige", "aqua", "navy", "teal",
    "light blue", "dark blue", "light green", "dark green", "light brown",
    "dark brown", "light purple", "purple", "two-tone", "multicolored",
]

# 무늬 조합도 같은 성질이다. Codex 1차가 `striped shirt`/`checkered skirt`/`ribbed dress`
# 를 cloth_pattern 으로 옮기라고 했는데, 그러면 무늬 축이 '무늬 달린 옷' 목록이 된다.
# 색 조합과 똑같이 **본체 + 수식어**로 보는 것이 맞다 — `striped` 자체는 이미 무늬 축에 있다.
CLOTH_PATTERNS = [
    "striped", "vertical-striped", "horizontal-striped", "diagonal-striped",
    "plaid", "checkered", "polka dot", "floral print", "camouflage", "argyle",
    "ribbed", "lace-trimmed", "fur-trimmed", "ribbon-trimmed", "frilled",
    "leopard print", "zebra print", "tiger print", "cow print", "star print",
    "heart print", "food print", "print", "patterned",
]


def modifier_combo(t: str) -> tuple[str, str]:
    """`white shirt` -> ('white', 'shirt'). 본체가 풀 안에 있을 때만 조합으로 본다."""
    for c in sorted(CLOTH_COLORS + CLOTH_PATTERNS, key=len, reverse=True):
        if t.startswith(c + " "):
            head = t[len(c) + 1:]
            if head in POOL:
                return c, head
    return "", ""


def excluded(t: str) -> str:
    if t in EXCLUDE_EXPLICIT:
        return "렌더 불가/액션"
    if RE_FRANCHISE.search(t) and not RE_DISAMBIG.search(t):
        return "작품·캐릭터 한정"
    if RE_COSPLAY.search(t):
        return "cosplay"
    if RE_UNWORN.search(t):
        return "미착용(소품)"
    if RE_ALTERNATE.search(t):
        return "원본 비교 필요"
    if RE_DEPRECATED.search(D(t)):
        return "폐기·모호"
    return ""

# 절단선을 149 로 낮추자 `attire` 에서 43개가 미분류로 떨어졌다(500 에서는 0이었다).
# catch-all 을 만들지 않는다는 원칙대로 하나씩 배정한다 — 설명을 읽고 정했다.
CUT149_ATTIRE = {
    # 한 벌 의상·제복·코스튬
    "roman clothes": "cloth_traditional", "chiton": "cloth_traditional",
    "peplos": "cloth_traditional", "changpao": "cloth_traditional",
    "kataginu": "cloth_traditional", "jinbaori": "cloth_traditional",
    "chihaya (clothing)": "cloth_traditional", "shiromuku": "cloth_traditional",
    "russian clothes": "cloth_traditional", "telnyashka": "cloth_traditional",
    "haramaki": "cloth_traditional",
    "aristocratic clothes": "cloth_uniform", "racing suit": "cloth_uniform",
    "fortified suit": "cloth_uniform", "test plugsuit": "cloth_uniform",
    "gantz suit": "cloth_uniform", "hazmat suit": "cloth_uniform",
    "scuba gear": "cloth_uniform", "diamond clan outfit": "cloth_uniform",
    "vocaloid append": "cloth_uniform", "anna miller": "cloth_uniform",
    "smock": "cloth_uniform", "workout clothes": "cloth_uniform",
    "striped suit": "cloth_uniform",
    "catsuit": "cloth_swim", "kittysuit": "cloth_swim",
    "bodycon": "cloth_dress", "sheet ghost": "cloth_dress",
    "rags": "cloth_state", "folded clothes": "cloth_state",
    "food on clothes": "cloth_state", "liquid clothes": "cloth_state",
    "expressive clothes": "cloth_state",
    "undersized breast cup": "cloth_state", "whale tail (clothing)": "cloth_state",
    # 실루엣·디테일
    "square neckline": "cloth_detail", "empire waist": "cloth_detail",
    "racerback": "cloth_detail", "lace-up": "cloth_detail",
    "crinoline": "cloth_detail", "sleeveless duster": "cloth_outer",
    "bell-bottoms": "cloth_bottom",
    # `khakis` 는 설명이 "대신 다음 중 하나를 사용하세요" — 리다이렉트 태그다.
    "khakis": "",
}

# ── 3. subgroup -> 축 (attire 를 뺀 나머지는 subgroup 이 충분히 동질적이다) ──
SUB_AXIS = {
    "headwear": "cloth_headwear",
    "hair_accessories": "cloth_hairacc",
    "neck_and_neckwear": "cloth_neck",
    "footwear": "cloth_footwear",
    "legwear": "cloth_legwear",
    "handwear": "cloth_handwear",
    "eyewear": "cloth_eyewear",
    "mask": "cloth_eyewear",
    "face_accessories": "cloth_eyewear",
    "accessories": "cloth_accessory",
    "armor": "cloth_armor",
    "sleeves": "cloth_sleeve",
    "patterns": "cloth_pattern",
    "prints": "cloth_pattern",
    "design_elements": "cloth_detail",
    "panties": "cloth_under",
    "bra": "cloth_under",
    "underwear": "cloth_under",
    "fashion_style": "cloth_style",
    "clothing_state": "cloth_state",
    "states": "cloth_state",
    "covering": "cloth_state",
    "sexual_attire": "cloth_nsfw",
    "clothes": "cloth_state",
    "other_animals": "cloth_headwear",   # rabbit hood / reindeer hood 등
    "cats": "cloth_headwear",            # cat hood
    "objects": "cloth_accessory",        # sign around neck / head flag
    "animal_interaction": "cloth_accessory",   # animal around neck
    "weather": "cloth_headwear",         # snow on headwear
    "interaction": "cloth_state",        # wings through clothes
}

# ── 4. attire(가장 큰 subgroup) 4분할 ───────────────────────────────────────
# 옷 종류 / 착의 상태 / 디테일·실루엣 / 스타일·용도. 순서대로 검사한다.
#   ⚠️ 첫 판에서 `(clothes|clothing|outfit|dress|shirt|skirt|top|bottom)$` 를 썼다가
#   shirt / pleated skirt / t-shirt / tank top 까지 '착의 상태'로 삼켰다(158개 중 121개
#   오분류). body_expose 의 catch-all 과 같은 병을 정규식으로 재발시킨 것이다.
#   상태는 '옷의 조건'을 나타내는 수식어로만 판정한다 — 의류 명사로는 판정하지 않는다.
A_STATE = re.compile(
    r"^(open|torn|ripped|wet|dirty|burnt|loose|undone|untied|unbuttoned|unzipped"
    r"|partially|half-|tied|taut)\b"
    r"|^(hood up|hood down|topless|bottomless|nude|naked|no pants|no bra"
    r"|no panties|no shirt|no shoes|clothes removed|underwear only)\b"
    r"|^(covered|exposed)\b"
    # 접미 형태의 상태 — 첫 판이 전부 놓쳤다(Codex 18건 적발). 조건 수식어가 뒤에 온다:
    # `bikini under clothes` / `bra peek` / `bra visible through clothes` / `overskirt`
    # / `coat on shoulders` / `crop top overhang`. 이것들은 '입을 수 있는 옷'이 아니라
    # 겹쳐 입기·비침 상태다.
    r"|\b(under clothes|under skirt|under pantyhose|peek|visible through clothes"
    r"|on shoulders|overhang|through clothes)$"
    r"|^(overskirt|panty straps|bra strap)$"
)
A_DETAIL = re.compile(
    r"(cutout|slit|halter|strapless|off shoulder|spaghetti strap|underbust"
    r"|highleg|pelvic curtain|backless|frill|ruffle|lace trim|fur trim|fur-trimmed"
    r"|double-breasted|pocket|zipper|button|collar|hem|waistband|drawstring"
    r"|sash|belt|buckle|cape$|train$|slitted|cleavage|side-tie|criss-cross"
    r"|skin tight|tight|taut|oversized|cropped|layered|asymmetric)"
)
A_STYLE = re.compile(
    r"(formal|casual|sportswear|winter clothes|summer|pajamas|sleepwear|loungewear"
    r"|magical girl|gothic|lolita|punk|streetwear|business|office|athletic|gym"
    r"|japanese clothes|chinese clothes|korean clothes|western|traditional"
    r"|revealing clothes|erotic|fashion|wedding|funeral|mourning)"
)
A_TRAD = re.compile(
    r"(japanese clothes|chinese clothes|korean clothes|indian clothes|arabian clothes"
    r"|kimono|yukata|hakama|haori|happi|jinbei|miko|kariginu|hanbok|qipao"
    r"|cheongsam|tangzhuang|hanfu|sari|salwar|kebaya|ao dai|dirndl|lederhosen"
    r"|kilt|toga|sarong|thawb|abaya|obi|geta|tabi|zori|sarashi|fundoshi)"
)
A_UNIFORM = re.compile(
    r"(uniform|serafuku|school|military|nurse|maid|police|firefighter|waitress"
    r"|stewardess|cheerleader|scout|sailor|band|marching|judo|karate|kendo"
    r"|santa|witch|nun|habit|priest|cassock|monk|shrine|track suit|gym uniform"
    r"|playboy bunny|bunnysuit|kigurumi|mascot|costume|armor$)"
)
A_SWIM = re.compile(r"(swimsuit|bikini|swim briefs|swim trunks|rash guard|wetsuit)")
A_UNDER = re.compile(
    r"(underwear|panties|panty|\bbra\b|lingerie|chemise|corset|bustier|girdle"
    r"|garter|thong|briefs|boxers|camisole|slip|petticoat|bloomers|buruma|bandeau)"
)
# `dress shirt` 는 셔츠다 — 첫 판에서 `dress` 만 보고 원피스로 보냈다(Codex 지적).
A_DRESS = re.compile(
    r"\bdress\b(?! shirt| pants| shoes| socks)|(gown|robe|leotard|bodysuit|unitard"
    r"|jumpsuit|overalls|romper|onesie|coverall|sundress|microdress)"
)
# 원피스와 겉옷은 성격이 다르다 — 케이프/망토/앞치마는 다른 옷 위에 걸치는 것이다.
# 첫 판에서 한 축(cloth_onepiece)에 몰아 드레스·정장·앞치마·망토가 섞였다.
A_OUTER = re.compile(r"(apron|tabard|poncho|cloak|cape|capelet|shawl|stole|mantle)")
A_BOTTOM = re.compile(
    r"(skirt|shorts|pants|trousers|jeans|slacks|culottes|leggings|chaps|breeches)"
)
A_TOP = re.compile(
    r"(shirt|blouse|sweater|hoodie|cardigan|vest|jacket|coat|jersey|tunic"
    r"|tank top|turtleneck|blazer|parka|windbreaker|pullover|sweatshirt"
    r"|crop top|tube top|top)"
)

# ── 판정 기준: "이 태그 하나로 '무엇을 입었나'에 답할 수 있는가" ──────────────
# Codex 1차 리뷰가 `pleated skirt`/`frilled skirt`/`long skirt`/`miniskirt`/`pencil skirt`
# 를 전부 cloth_detail 로 옮기라고 했다(수식어가 핵심이라는 논리). 받지 않았다.
# 그대로 하면 하의 축에 `skirt`/`shorts`/`pants` 6개만 남고 디테일 축이 '모든 치마 변형'
# 150개 잡동사니가 된다 — body_expose 에서 겪은 catch-all 이 이름만 바꿔 재발한다.
# 초보자가 의상>하의를 열었을 때 봐야 하는 것은 실제 선택지(`pleated skirt`,
# `miniskirt`, `pencil skirt`)다.
#
# 그래서 기준을 뒤집는 대신 명문화한다:
#   - 태그 하나로 착용 가능한 옷이면 -> 그 옷의 부위 축   (`pleated skirt` = 치마)
#   - 혼자서는 입을 수 없는 부분·구조면 -> cloth_detail   (`side slit`, `v-neck`,
#     `cleavage cutout`, `hip vent`, `plunging neckline`, `lapels`, `strap gap`)
# Codex 지적 중 이 기준으로도 옳은 것(정체성 오판·상태·수영복 순서·NSFW)만 반영했다.
#
# 검사 순서가 분류를 결정한다. **의류 정체성이 수식어보다 앞선다** —
# 첫 판에서 디테일(A_DETAIL)을 앞에 두어 `frilled skirt` 가 하의가 아니라 디테일로
# 갔다. 프릴 달린 치마는 여전히 치마다. 그래서 디테일·스타일을 맨 뒤로 옮겼고,
# 그 결과 A_DETAIL 에는 머리 명사 자체가 디테일인 것(cleavage cutout, side slit,
# halterneck)만 남는다.
_ATTIRE_ORDER = (
    (A_STATE, "cloth_state"),            # 조건 수식어(접두/접미)
    (A_TRAD, "cloth_traditional"),
    # 수영복이 제복보다 앞선다 — `school swimsuit` / `maid bikini` / `sailor bikini` 가
    # 제복으로 갔다(Codex 5건). 학교 지급이든 메이드 테마든 수영복은 수영복이다.
    (A_SWIM, "cloth_swim"),
    (A_UNIFORM, "cloth_uniform"),
    (A_UNDER, "cloth_under"),
    (A_OUTER, "cloth_outer"),
    (A_DRESS, "cloth_dress"),
    (A_BOTTOM, "cloth_bottom"),
    (A_TOP, "cloth_top"),
    (A_DETAIL, "cloth_detail"),
    (A_STYLE, "cloth_style"),
)

# `naked shirt` / `naked apron` / `naked towel` = "그것만 걸치고 나머지는 나체".
# covering subgroup 에 있어 착의 상태로 갔는데 실제로는 명시적 성인 표현이다(Codex 7건).
# 개별 나열 대신 규칙으로 둔다 — 앞으로 추가되는 `naked *` 도 자동으로 격리된다.
A_NAKED = re.compile(r"^naked \w|^untied (bikini|swimsuit)$")
# 소스의 `patterns` subgroup 은 이름이 틀렸다 — 트림·재질·여밈 부품이 섞여 있다.
# 무늬가 아닌 것은 디테일이다(Codex 14건).
A_MATERIAL = re.compile(
    r"\b(trim|frills?|zipper|latex|denim|leather|satin|velvet|fabric)$"
    r"|^(shiny clothes|cross-laced clothes|center frills|two-sided fabric)$"
    r"|cutout$"
)


def attire_axis(t: str) -> str:
    for pat, axis in _ATTIRE_ORDER:
        if pat.search(t):
            return axis
    return ""

# ── 5. 규칙이 놓치는 것 손배정 ──────────────────────────────────────────────
# 규칙 통과 후 남은 것을 전수 확인해 하나씩 넣는다(catch-all 버킷을 만들지 않는다).
EXPLICIT = {
    # 정장 — 상하 세트라 상의/하의 어디에도 안 맞는다 -> 원피스·한벌 축
    "suit": "cloth_dress",
    # 넥라인·컷아웃 = 디테일
    "hip vent": "cloth_detail", "strap gap": "cloth_detail",
    "v-neck": "cloth_detail", "plunging neckline": "cloth_detail",
    "lapels": "cloth_detail",
    # 제복
    "gakuran": "cloth_uniform", "dougi": "cloth_uniform",
    # 전통
    "furisode": "cloth_traditional", "hagoromo": "cloth_traditional",
    "loincloth": "cloth_traditional",
    # 하의
    "cutoffs": "cloth_bottom",
    # 속옷·잠옷
    "babydoll": "cloth_under",
    # 수영복
    "male swimwear": "cloth_swim",
    # 2차 잔여 8개 — 전통/제복/디테일/상태로 갈린다.
    "egyptian clothes": "cloth_traditional", "ainu clothes": "cloth_traditional",
    "idol clothes": "cloth_uniform", "tactical clothes": "cloth_uniform",
    "reverse outfit": "cloth_detail", "sideless outfit": "cloth_detail",
    "undersized clothes": "cloth_state",

    # ── Codex 1차 리뷰 반영 ──────────────────────────────────────────────
    # (1) 옷의 정체성을 규칙이 잘못 읽은 것
    "dress shirt": "cloth_top",          # `dress` 에 걸려 원피스로 갔다
    "military jacket": "cloth_top",      # 군복 전체가 아니라 재킷 단품
    "sailor shirt": "cloth_top",         # 세일러 칼라가 달린 셔츠
    "sailor dress": "cloth_dress",
    "china dress": "cloth_traditional",  # 옆트임 중국식 드레스
    "meiji schoolgirl uniform": "cloth_traditional",   # 메이지 기모노·하카마 복식
    "lab coat": "cloth_uniform",         # 직업복
    "pilot suit": "cloth_uniform", "plugsuit": "cloth_uniform",
    "spacesuit": "cloth_uniform",        # 전부 직업·특수복이다
    "harem outfit": "cloth_uniform",     # 국가 전통복이 아니라 공연 코스튬
    "buruma": "cloth_uniform",           # 체육복 하의 = 교복 계열
    "skirt set": "cloth_dress", "skirt suit": "cloth_dress",   # 상하 한벌
    "sarong": "cloth_bottom",            # 허리에 둘러 입는 하의
    "undershirt": "cloth_under",
    # 전통 속옷은 기능이 속옷이다. 전통 축은 겉옷을 담는다.
    "sarashi": "cloth_under", "chest sarashi": "cloth_under",
    "fundoshi": "cloth_under", "loincloth": "cloth_under",
    "hagoromo": "cloth_outer",           # 몸에 두르는 얇은 숄
    "waist cape": "cloth_outer",

    # (2) 노출(성인) 축으로 격리 — 초보자가 기본으로 보는 그리드에 둘 것이 아니다.
    #     태그는 지우지 않는다(필요한 사용자가 있다). 축 전체가 블러 + 보류다.
    "micro bikini": "cloth_nsfw", "thong bikini": "cloth_nsfw",
    "eyepatch bikini": "cloth_nsfw", "bikini top only": "cloth_nsfw",
    "bikini bottom only": "cloth_nsfw", "microskirt": "cloth_nsfw",
    "micro shorts": "cloth_nsfw", "microdress": "cloth_nsfw",
    "showgirl skirt": "cloth_nsfw", "reverse bunnysuit": "cloth_nsfw",
    "no bra": "cloth_nsfw", "no panties": "cloth_nsfw", "wet panties": "cloth_nsfw",
    "impossible shirt": "cloth_nsfw", "impossible bodysuit": "cloth_nsfw",
    "see-through shirt": "cloth_nsfw", "see-through dress": "cloth_nsfw",
    "see-through leotard": "cloth_nsfw",
    # `playboy bunny`(62,919) 는 판단이 갈린다 — 잘 알려진 코스튬이지만 성적 맥락이
    # 기본이다. 격리해도 태그는 그대로 제공되므로 안전한 쪽을 택했다. 되돌리기 쉽다.
    "playboy bunny": "cloth_nsfw",

    # ── 절단선 500 으로 내리며 들어온 500~2000 대역의 손배정 ──────────────
    # 규칙이 freq>=2000 인구에 맞춰져 있어 41개가 샜다. 전량 확인해 배정했다.
    "notched lapels": "cloth_detail", "low neckline": "cloth_detail",
    "single strap": "cloth_detail", "multiple straps": "cloth_detail",
    "low-cut armhole": "cloth_detail", "scoop neck": "cloth_detail",
    "baggy clothes": "cloth_detail",
    "bodice": "cloth_top", "sukajan": "cloth_top",
    "tutu": "cloth_bottom",                    # 발레 스커트
    "tuxedo": "cloth_dress", "pant suit": "cloth_dress",
    "pinstripe suit": "cloth_dress",
    "tankini": "cloth_swim",
    "elbow sleeve": "cloth_sleeve",
    "bib": "cloth_neck",                       # 목에 두른다
    "dudou": "cloth_under",                    # 중국 전통 속옷 상의 (sarashi 와 같은 처리)
    "stained clothes": "cloth_state", "paint on clothes": "cloth_state",
    "biker clothes": "cloth_style",
    "wrestling outfit": "cloth_uniform", "diving suit": "cloth_uniform",
    "bikesuit": "cloth_uniform", "prison clothes": "cloth_uniform",
    "singlet": "cloth_uniform",
    "kappougi": "cloth_traditional", "german clothes": "cloth_traditional",
    "greco-roman clothes": "cloth_traditional",
    "ancient greek clothes": "cloth_traditional",
    "uchikake": "cloth_traditional", "kesa": "cloth_traditional",
    # 노출이 요지인 것 -> 격리
    "virgin killer outfit": "cloth_nsfw",
    # 유아복이지만 이 데이터셋에서는 페티시 태그로 쓰인다. 지우지 않고 격리한다.
    "diaper": "cloth_nsfw",

    # ── Codex 2차 리뷰 반영 ──────────────────────────────────────────────
    # (1) 노출(성인)로 격리 — 노출 상태 자체가 태그의 요지다.
    "covered nipples": "cloth_nsfw", "topless": "cloth_nsfw",
    "bottomless": "cloth_nsfw", "no pants": "cloth_nsfw",
    "topless male": "cloth_nsfw", "see-through cleavage": "cloth_nsfw",
    "underboob cutout": "cloth_nsfw", "framed breasts": "cloth_nsfw",
    "revealing clothes": "cloth_nsfw",
    # 밀착 원단이 가슴 형태를 그대로 드러내는 계열. 하위(impossible shirt/bodysuit)를
    # 이미 격리했으므로 상위도 같이 옮긴다.
    "impossible clothes": "cloth_nsfw",
    # (2) 구조·실루엣 -> 디테일
    "covered navel": "cloth_detail", "button gap": "cloth_detail",
    "undersized clothes": "cloth_detail",
    "tail through clothes": "cloth_detail", "hair through headwear": "cloth_detail",
    "wings through clothes": "cloth_detail",
    # (3) 개수는 렌더된다 — 제외를 철회했다
    "multiple belts": "cloth_accessory", "multiple bracelets": "cloth_accessory",
    "multiple rings": "cloth_accessory",
    # (4) 괄호가 구분자인 것들
    "shrug (clothing)": "cloth_top", "pom pom (clothes)": "cloth_detail",
    "charm (object)": "cloth_accessory", "hanten (clothes)": "cloth_traditional",
    "train (clothing)": "cloth_detail",
}

# 명시 제외 + 사유. EXPLICIT 에 빈 문자열로 넣으면 사유가 뭉개져 여기로 분리했다.
EXCLUDE_REASON = {
    "matching outfits": "2인 필요",
    "adapted costume": "원본 비교 필요",   # 캐릭터의 평상시 설정과 비교해야 성립
    "enmaided": "원본 비교 필요",
    "traditional nun": "근접 중복(habit)",
    "casual one-piece swimsuit": "근접 중복(one-piece swimsuit)",
    "sleeveless sweater": "근접 중복(sweater vest)",

    # 500 대역에서 나온 제외분.
    "borrowed clothes": "원본 비교 필요",        # 다른 캐릭터의 옷을 빌린 모습
    # 괄호가 없어 '작품·캐릭터 한정' 규칙이 못 잡는 것들.
    "zero suit": "작품 고유 아이템",              # 메트로이드 사무스
    "normal suit": "작품 고유 아이템",            # 건담 파일럿 슈트
    "taimanin suit": "작품 고유 아이템",          # 대마인 시리즈
    "okamisty": "작품 고유 아이템",               # 동방 미스티아 로렐라이
    "clothes": "너무 넓은 총칭",                  # 설명이 "의복의 총칭"이다
    "living clothes": "렌더 불가",                # "스스로 움직이고 말하는 옷"
    # 데이터 오류: 태그명이 숫자 39 인데 설명은 훈도시다. NAI 에 39 를 넣어봐야 의미가 없다.
    "39": "데이터 오류(태그명 손상)",
}
# `g-string`/`thong` 과 `turtleneck sweater`/`turtleneck` 도 근접 중복으로 지적됐지만
# 남겼다 — 둘 다 고빈도 상용 태그이고 초보자가 속옷·상의를 고를 때 실제로 구분해서 찾는다.

# ── 5b. 후처리 규칙 (Codex 3차 리뷰 반영) ───────────────────────────────────
# subgroup 이 부위별로는 맞지만 '착용물 / 착용 상태 / 구성 부품'을 구분하지 않는다.
# 개별 나열 대신 규칙으로 둔다 — 앞으로 추가되는 같은 형태의 태그도 자동으로 잡힌다.
POST_RULES: tuple[tuple[re.Pattern, str], ...] = (
    # 한쪽만 착용 / 위치를 옮겨 착용 / 손상 = 상태다. 착용물 종류가 아니다.
    (re.compile(r"^single \w"), "cloth_state"),
    # `loose` 는 접두 규칙에서 뺐다 — `loose socks`(6,399)는 상태가 아니라 교복과 함께
    # 신는 양말 '종류'다. `loose necktie` 만 단건으로 상태 처리한다.
    (re.compile(r"^(torn|tilted|backwards|popped|open) \w"), "cloth_state"),
    (re.compile(r"(on head|around neck|on headwear|between breasts"
                r"|rolled up|pushed up|over long sleeves)$"), "cloth_state"),
    (re.compile(r"^no (shoes|socks|panties|bra)$"), "cloth_state"),
    # 좌우가 다르다 / 크기가 다르다 = 디자인 특성이다.
    (re.compile(r"^(mismatched|asymmetrical|uneven|large|small) \w"), "cloth_detail"),
    # 머리카락에 붙는 것은 모자가 아니다 — 소스 headwear subgroup 이 둘을 섞고 있다.
    (re.compile(r"^hair (bow|bows|ribbon|tie|bell|stick|beads|tubes|ornament)"
                r"|hairband$|hairpin|kanzashi|scrunchie$|bun cover"
                r"|^multiple hair bows$|^tress ribbon$|^frilled hair tubes$"), "cloth_hairacc"),
    # 목에 거는 것은 액세서리가 아니라 목 축이다(초커가 목에 있는데 목걸이가 딴 데 있었다).
    (re.compile(r"necklace$|^pendant$|^neck (ring|ruff)$|^dog tags$"
                r"|^feather boa$"), "cloth_neck"),
    # 옷깃의 형태는 옷의 부분이다.
    (re.compile(r"^(sailor|wing|frilled shirt|high) collar$"), "cloth_detail"),
    # 여밈·부품·부착 장식 = 혼자 입을 수 없다 -> 디테일 (명문화한 판정 기준 그대로)
    (re.compile(r"^(buttons|o-ring|buckle|belt buckle|drawstring|zipper pull tab"
                r"|epaulettes|fringe trim|strap|diamond button|dress bow|waist bow"
                r"|ofuda on clothes|shoulder spikes|footwear bow)$"), "cloth_detail"),
    # 구속구는 초보자용 그리드에 둘 것이 아니다.
    (re.compile(r"gag(ged)?$|^(ball|bit|improvised|wiffle) gag$"), "cloth_nsfw"),
)
# 규칙으로 일반화되지 않는 단건.
POST_EXPLICIT = {
    "horn ornament": "cloth_accessory",        # 머리가 아니라 뿔에 찬다
    "animal ear headphones": "cloth_accessory", "cat ear headphones": "cloth_accessory",
    "wrist scrunchie": "cloth_accessory", "knee pads": "cloth_accessory",
    "forehead jewel": "cloth_accessory",
    "thigh strap": "cloth_accessory", "thighlet": "cloth_accessory",
    "anklet": "cloth_accessory",                # 의류가 아니라 발찌
    "armored boots": "cloth_armor",
    "tabi": "cloth_legwear",                    # 일본 전통 양말
    "legwear garter": "cloth_legwear",
    "garter straps": "cloth_under",
    "bikini armor": "cloth_nsfw",
    "loose necktie": "cloth_state", "loose bikini": "cloth_state",
}
# 제외 — 평소 착장과 비교해야 성립 / 작품 고유 아이템 / 상대 필요 / 근접 중복.
POST_EXCLUDE = {
    "no headwear": "원본 비교 필요", "no legwear": "원본 비교 필요",
    "bespectacled": "원본 비교 필요",
    "super crown": "작품 고유 아이템", "v-fin": "작품 고유 아이템",
    "interface headset": "작품 고유 아이템", "dynamax band": "작품 고유 아이템",
    "character hair ornament": "작품 고유 아이템",
    "chain leash": "상대·고정점 필요",
    "shoe soles": "발 자세(액션 슬롯)",
    "hair rings": "헤어스타일(머리 슬롯)",
    "sleeves pushed up": "근접 중복(sleeves rolled up)",
    "wristwatch": "근접 중복(watch)",
    "pauldrons": "근접 중복(shoulder armor)",
    "arm guards": "근접 중복(vambraces)",
    "very long sleeves": "근접 중복(sleeves past fingers)",
    "semi-rimless eyewear": "근접 중복(under-rim/over-rim eyewear)",
    "crossed bandaids": "부상·오염 축",          # 장신구가 아니라 반창고
}
# `puffy sleeves`(우산 태그)와 `shawl` 은 Codex 제안을 받지 않았다 —
# 전자는 고빈도이고 하위와 시각적으로 구분되며, 후자는 겉옷 축(신설)이 상의보다 맞다.



# ── 액세서리 축 부위 재분할 ─────────────────────────────────────────────────
# `cloth_accessory` 220개는 착용 부위가 7곳에 흩어져 있어 한 그리드로는 대부분이
# 쓸모없는 썸네일이 된다(귀걸이를 cowboy shot 으로 찍는 것과 같다).
# 의상 프리셋의 region6 매핑(`data/interactive_clothing_harmony.json`)을 근거로 쪼갠다.
#
# ⚠️ region6 를 그대로 믿으면 안 된다. `subgroup_fallback`(confidence 0.7)이
# "accessories 서브그룹이니 일단 HEAD_NECK_FACE" 로 몰아넣어서 `bag`/`sash`/`obi`/
# `backpack` 까지 머리·목·얼굴로 들어가 있었다(154개 중 122개). 근거가 태그 이름이나
# 서브그룹 직결인 것만 쓰고, 나머지는 이름 규칙으로 보완한다.
#
# 끝까지 남는 83개(`bow`/`jewelry`/`ribbon`/`chain`/`gem`/`brooch`)는 매핑 실패가
# 아니라 **부위 무관 장식**이다 — 리본은 머리에도 허리에도 붙는다. 이건 그대로 둔다.
_ACC_REGION_AXIS = {
    "HEAD_NECK_FACE": "cloth_hairacc",   # 귀걸이·헤드폰·머리핀
    "ARMS_HANDS": "cloth_handwear",
    "LEGS": "cloth_legwear",
    "FEET": "cloth_footwear",
    "UPPER_BODY": "cloth_detail",
    "WAIST_HIP": "cloth_waist",          # 신설 — 벨트류가 갈 곳이 없었다
    "CARRIED": "cloth_carried",          # 신설 — 가방은 착용물이 아니라 소지품이다
}
_ACC_NAME_RULES = (
    ("CARRIED", re.compile(r"(bag|backpack|purse|satchel|briefcase|randoseru"
                           r"|fanny pack|lanyard|umbrella)")),
    ("ARMS_HANDS", re.compile(r"(bracelet|wrist|armlet|armband|arm|bangle"
                              r"|^ring$|nail|glove|cuff)")),
    ("WAIST_HIP", re.compile(r"(belt|sash|obi|waist|buckle|suspender|holster"
                             r"|pouch|hip)")),
    ("LEGS", re.compile(r"(anklet|thigh|leg|knee|garter)")),
    ("FEET", re.compile(r"(foot|feet|toe|horseshoe)")),
    ("HEAD_NECK_FACE", re.compile(r"(earring|ear|headphone|hair|head|tiara"
                                  r"|crown|circlet|piercing|earphone)")),
)


def _split_accessory(axes: dict) -> None:
    try:
        harmony = json.loads(
            Path("data/interactive_clothing_harmony.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return                              # 캐시가 없으면 재분할하지 않는다
    region = harmony.get("region", {})
    acc = list(axes.get("cloth_accessory", ()))
    keep, moved = [], {}
    for t in acc:
        r = region.get(t)
        if not r:
            for name, pat in _ACC_NAME_RULES:
                if pat.search(t):
                    r = name
                    break
        dest = _ACC_REGION_AXIS.get(r or "")
        if dest:
            axes.setdefault(dest, []).append(t)
            moved[t] = dest
        else:
            keep.append(t)                  # 부위 무관 장식
    axes["cloth_accessory"] = keep
    _split_accessory.moved = moved


# ── 소형 장신구 — 프레이밍이 달라 축을 가른다 ───────────────────────────────
# 192px 팩 크롭에서 귀걸이는 약 15px 다. cowboy/upper 로 찍으면 화소가 없어 시드로도
# 해결되지 않는다(의상 검수 실측). 파일럿에서 `earrings`/`ring`/`bracelet` 을 portrait
# 로 찍으니 셋 다 또렷하게 읽혔다 — 프레임이 좁으면 모델이 손을 얼굴 쪽으로 올린다.
#
# **발·꼬리·뿔에 붙는 것은 넣지 않는다.** portrait 은 그쪽이 오히려 프레임 밖이다
# (`anklet`·`toe ring`·`tail ring`·`horn ring`). 허리(`belly chain`)도 cowboy 가 맞다.
_RE_SMALL_ACC = re.compile(
    r"(earring|earclip|ear ribbon|ear ornament|bracelet|bangle|nail art"
    r"|\bring\b|\bwatch\b|^jewelry$|^gem$|^chain$|pendant)", re.I)
_RE_SMALL_SKIP = re.compile(
    r"o-ring|nose ring|cock ring|tail ring|horn ring|toe ring|anklet"
    r"|belly chain|chainmail|z-ring|soul gem", re.I)


def _split_small_accessory(axes: dict) -> None:
    moved = {}
    for src in ("cloth_accessory", "cloth_handwear", "cloth_detail"):
        keep = []
        for t in axes.get(src, ()):
            if _RE_SMALL_ACC.search(t) and not _RE_SMALL_SKIP.search(t):
                axes.setdefault("cloth_small", []).append(t)
                moved[t] = src
            else:
                keep.append(t)
        if src in axes:
            axes[src] = keep
    _split_small_accessory.moved = moved


# ── 6. 조립 ────────────────────────────────────────────────────────────────
AXES: dict[str, list[str]] = {}
EXCLUDED: dict[str, str] = {}
COMBO: dict[str, tuple[str, str]] = {}
UNASSIGNED: list[str] = []

# 1단계: 조합 분해를 빼고 전량 배정한다.
for t, f in POOL.items():
    if t in MOVED_OUT:
        continue
    why = excluded(t)
    if why:
        EXCLUDED[t] = why
        continue
    if f < CUT:
        EXCLUDED[t] = f"freq<{CUT}"
        continue
    if t in EXCLUDE_REASON:
        EXCLUDED[t] = EXCLUDE_REASON[t]
        continue
    if t in CUT149_ATTIRE:
        dest = CUT149_ATTIRE[t]
        if dest:
            AXES.setdefault(dest, []).append(t)
        else:
            EXCLUDED[t] = "리다이렉트 태그"
        continue
    if t in EXPLICIT:
        AXES.setdefault(EXPLICIT[t], []).append(t)
        continue
    if A_NAKED.search(t):
        AXES.setdefault("cloth_nsfw", []).append(t)
        continue
    sub = SUB.get(t, "")
    axis = SUB_AXIS.get(sub) or attire_axis(t)
    # patterns/prints subgroup 안의 트림·재질·컷아웃은 무늬가 아니라 디테일이다.
    if axis == "cloth_pattern" and A_MATERIAL.search(t):
        axis = "cloth_detail"
    if not axis:
        UNASSIGNED.append(t)
        continue
    AXES.setdefault(axis, []).append(t)

# 1.5단계: 후처리 규칙으로 재배정한다.
for _axis in list(AXES):
    for t in list(AXES[_axis]):
        if t in POST_EXCLUDE:
            AXES[_axis].remove(t)
            EXCLUDED[t] = POST_EXCLUDE[t]
            continue
        dest = POST_EXPLICIT.get(t)
        if not dest:
            for _pat, _d in POST_RULES:
                if _pat.search(t):
                    dest = _d
                    break
        if dest and dest != _axis:
            AXES[_axis].remove(t)
            AXES.setdefault(dest, []).append(t)

# 2단계: 조합으로 분해한다 — **수식어를 실제로 고를 수 있을 때만**.
# 처음에는 CLOTH_PATTERNS 전체를 수식어로 썼는데, `frilled`/`plaid`/`ribbed`/`fur-trimmed`
# 등 8개는 단독 태그가 없거나 제외돼 있었다. 그대로 분해하면 `frilled skirt` 가
# '고를 수 없는 수식어 + 치마'가 되어 태그 자체에 도달할 수 없다.
# 색은 팔레트(_palette.json)가 항상 제공하므로 무조건 유효하고,
# 무늬는 cloth_pattern 축에 남아 있는 것만 유효하다.
_valid_mods = set(CLOTH_COLORS) | set(AXES.get("cloth_pattern", ()))
_assigned = {t for v in AXES.values() for t in v}
for _axis in list(AXES):
    _keep = []
    for t in AXES[_axis]:
        mod, head = modifier_combo(t)
        if mod and mod in _valid_mods and head in _assigned:
            COMBO[t] = (mod, head)
        else:
            _keep.append(t)
    AXES[_axis] = _keep

_split_accessory(AXES)
_split_small_accessory(AXES)     # 부위 분배 뒤에 소형만 따로 뽑는다

# ── 벗겨진 옷(`unworn *`) 편입 ────────────────────────────────────────────────
# 어느 축에도 없어서 계층 탐색기로만 닿던 것들이다(`unworn headwear` 18,232 ·
# `unworn hat` 13,706 · `unworn panties` 5,380 …).
#
# `no panties` 같은 **부재** 태그와는 다르다. 부재는 그릴 대상이 없어 렌더가 안 되지만
# (의상 검수에서 확인), `unworn X` 는 X 가 존재하되 몸에서 벗겨진 상태라 그려진다.
# 손에 들고 있거나 바닥에 있거나 한쪽 다리에 걸려 있다.
_UNWORN = sorted((t for t in POOL
                  if t.startswith("unworn ") and F(t) >= CUT
                  and not any(t in v for v in AXES.values())),
                 key=lambda t: -F(t))
AXES["cloth_state"].extend(_UNWORN)

# ── 관계형 메타 태그 — 축이 아니라 캐릭터쪽으로 뺀다 ────────────────────────
# `alternate hairstyle`(60,753) · `official alternate costume`(194,610) ·
# `cosplay`(72,527) 류는 "이 캐릭터의 정본과 다르다" 는 뜻이라 **명명된 캐릭터가
# 있어야만** 의미가 성립한다. 실측: 최신 10개 parquet 에서 이것들은 캐릭터 이름과
# **100%** 동반한다(n=5,247 / 29,228 / 6,866). 전체 기준선은 89% 다.
# 반면 `unworn *` 는 76~94% 로 기준선 수준 — 평범한 시각 태그다.
#
# 그래서 썸네일 축에 넣지 않는다. 일반 `1girl` 에는 참조할 정본이 없어 그릴 것이 없다.
# 캐릭터 기능쪽에서 쓸 수 있도록 목록만 남긴다(사용자 지시 2026-07-27).
_RE_RELATIONAL = re.compile(
    r"^(official )?alternate \w|^cosplay$|\bcosplay$|^adapted costume$")
# 의상 POOL 이 아니라 **전체 태그 DB** 에서 모은다 — `alternate hairstyle`(60,753)은
# 머리 서브그룹이라 의상 풀에 없어서 처음에 8개만 잡혔다.
RELATIONAL_META = sorted(
    (t for t in raw if _RE_RELATIONAL.search(t) and F(t) >= 300),
    key=lambda t: -F(t))
for _t in RELATIONAL_META:
    for _v in AXES.values():
        if _t in _v:
            _v.remove(_t)

# ── 다른 그룹에서 들여오는 것 (MOVED_OUT 의 역방향) ─────────────────────────
# POOL 은 `clothing` 그룹만 본다. 소스가 다른 그룹에 넣었지만 화면에 보이는 것이
# 옷의 구성인 태그는 여기로 끌어온다. 지금까지는 반대 방향(의상 -> 다른 슬롯)만
# 있었다 — 이게 첫 사례라 통로를 만든다.
#
# 여기 적으면 `build_nsfw_act_catalog.py` 가 자동으로 성인 도감에서 뺀다
# (그쪽이 `wildcards/thumb/*.txt` 를 전부 `taken` 으로 읽는다). 목록은 한 벌이다.
IMPORTED = {
    # 소스 분류 "성적 > 의상 노출"(142,446). 실제로는 스커트와 사이하이 삭스
    # 사이에 남는 허벅지 구간을 부르는 이름이다 — 노출 행위가 아니라 착장 구성이라
    # 다리 축이 맞다(사용자 지적 2026-07-29).
    "zettai ryouiki": "cloth_legwear",
    # 소스 서브그룹이 `nudity` 다. 설명은 "셔츠나 상의의 가슴 부분에 달린 주머니" —
    # 그냥 의류 디테일이다. 성인 도감 규칙에 이름이 박혀 있어서 끌려갔던 것.
    "breast pocket": "cloth_detail",
    # 성인 도감 `nsfw_act`(행위) 에 떨어져 있던 것들. 둘 다 행위가 아니라 착장이다.
    "painted clothes": "cloth_style",        # 옷을 흉내낸 보디페인팅
    "buruma around one leg": "cloth_state",  # `unworn *` 와 같은 착의 상태
}
for _t, _dest in IMPORTED.items():
    if _t not in raw:
        raise SystemExit(f"IMPORTED: 태그 DB 에 없다 -> {_t!r}")
    # **의상 축에만 넣을 수 있다.** 아래 저장 루프가 `AXES` 의 키마다 파일을 통째로
    # 덮어쓰므로, 여기서 새 키(`body_type` 등)를 만들면 그 축 파일이 이 한 줄로
    # 날아간다. 의상 밖 축으로 옮길 것은 그 축을 만드는 도구에서 처리한다.
    if _dest not in AXES:
        raise SystemExit(f"IMPORTED: 의상 축이 아니다 -> {_dest!r} (파일을 덮어쓴다)")
    if any(_t in _v for _v in AXES.values()):
        continue
    AXES[_dest].append(_t)

for k in AXES:
    AXES[k].sort(key=lambda t: -F(t))


# ── 이관 실제 적용 ──────────────────────────────────────────────────────────
# MOVED_OUT 은 "의상 축에서 뺀다"만 하고 목적지 축 파일에는 쓰지 않고 있었다.
# 그래서 이관 52건 중 47건이 어느 축에도 없는 상태가 됐다 — 장부에는 이관인데
# 실제로는 유실이다. 여기서 목적지 파일에 실제로 붙인다.
#
# `species_axes` 는 목적지가 하나가 아니라 태그별로 갈린다(뿔/날개/꼬리/귀).
_SPECIES_DEST = {
    "fake horns": "horns", "fake antlers": "horns",
    "fake wings": "wings", "fake tail": "tail",
    "fake animal ears": "ears", "fake antennae": "body_nonhuman",
}


def apply_moved_out() -> dict:
    """이관 태그를 목적지 축 파일에 실제로 추가한다. 중복은 넣지 않는다."""
    added = {}
    for tag, dest in sorted(MOVED_OUT.items()):
        if tag not in POOL:
            continue
        target = _SPECIES_DEST.get(tag, dest) if dest == "species_axes" else dest
        f = OUT / (target + ".txt")
        cur = ([l.strip() for l in f.read_text(encoding="utf-8").splitlines()
                if l.strip()] if f.exists() else [])
        if tag in cur:
            continue
        cur.append(tag)
        cur.sort(key=lambda t: -F(t))
        f.write_text("\n".join(cur) + "\n", encoding="utf-8")
        added[target] = added.get(target, 0) + 1
    return added


if __name__ == "__main__":
    print(f"의상 풀 {len(POOL)}개 / 절단선 freq>={CUT}")
    print(f"  다른 슬롯으로: {len(MOVED_OUT)}개 "
          f"{dict(Counter(MOVED_OUT.values()))}")
    print(f"  제외: {len(EXCLUDED)}개 {dict(Counter(EXCLUDED.values()))}")
    print(f"  색 조합(팔레트 후보, 썸네일 제외): {len(COMBO)}개")
    _heads = Counter(h for _, h in COMBO.values())
    print(f"    본체 {len(_heads)}종: "
          + ", ".join(f"{h}×{n}" for h, n in _heads.most_common(12)))
    print(f"  배정: {sum(len(v) for v in AXES.values())}개 / {len(AXES)}축")
    for k, v in sorted(AXES.items(), key=lambda kv: -len(kv[1])):
        print(f"    {k:20s} {len(v):4d}")
    _mv = getattr(_split_accessory, "moved", {})
    if _mv:
        print(f"  액세서리 재분할: {len(_mv)}개 이동, "
              f"{len(AXES['cloth_accessory'])}개는 부위 무관 장식으로 유지")
        print("    ", dict(Counter(_mv.values())))
    # 축을 계산만 하고 파일로 쓰지 않고 있었다. .txt 는 2026-07-26 에 한 번 쓰인 뒤
    # 코드와 갈라져, `unworn *` 27개를 AXES 에 넣어도 파일에는 반영되지 않았다.
    # (자세 쪽 `_todo` 분리와 같은 유형 — 목록이 두 벌이면 반드시 갈라진다.)
    _written = 0
    for _k, _v in sorted(AXES.items()):
        _axis_out(_k).mkdir(parents=True, exist_ok=True)
        (_axis_out(_k) / f"{_k}.txt").write_text("\n".join(_v) + "\n", encoding="utf-8")
        _written += len(_v)
    print(f"  축 파일 {len(AXES)}개 저장 / {_written}개")

    # 관계형 메타는 축이 아니라 목록으로만 남긴다(캐릭터 기능에서 회수).
    # `_` 접두라 thumb 도구들이 축으로 읽지 않는다.
    (OUT / "_relational_meta.txt").write_text(
        "\n".join(RELATIONAL_META) + "\n", encoding="utf-8")
    print(f"  관계형 메타 {len(RELATIONAL_META)}개 -> _relational_meta.txt "
          f"(캐릭터 이름 100% 동반. 축에 넣지 않는다)")

    # apply_moved_out 은 **위 저장 뒤에** 와야 한다. 목적지 축(horns/wings/...)에
    # 덧붙이는 작업인데 먼저 하면 방금 쓴 파일이 덮어써 이관분이 사라진다.
    _added = apply_moved_out()
    if _added:
        print(f"  이관 실제 적용: {sum(_added.values())}개 {_added}")
    print(f"  미분류: {len(UNASSIGNED)}개")
    for t in sorted(UNASSIGNED, key=lambda x: -F(x))[:40]:
        print(f"    {t:34s} f={F(t):>8d} [{SUB.get(t,''):16s}] {D(t)[:34]}")
