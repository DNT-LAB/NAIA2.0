"""Color-only tag exclusion for the event map.

Ported verbatim in intent from the handoff harness
(`coverage_expansion_v1/harness/tag_harness/event_map_policy.py`, 2026-09-11).
The user's rule: horns, wings, hairstyles and clothing lead somewhere -- an
event can come out of them. A color cannot. So colors are dropped from both the
map's anchors and its suggested companions, while shapes and patterns stay.

This module is deliberately free of data-file and DB imports: the same function
decides the artifact contents at build time and filters candidates at query
time, so the two can never drift apart.
"""
from __future__ import annotations

import re


POLICY_VERSION = "event-map-no-color-v1"

# Match whole tag structures, not arbitrary words. The bundled color.txt also
# carries patterns (plaid, striped, camouflage) which are deliberately not
# colors here.
COLOR_PREFIX = re.compile(
    r"^(?:(?:light|dark|pale|deep|bright|pastel|neon) )?"
    r"(?:sky blue|light green|strawberry blonde|platinum blonde|"
    r"grey|gray|beige|aqua|white|brown|blonde|blond|red|pink|orange|yellow|"
    r"gold|golden|green|blue|purple|black|silver|teal|cyan|magenta|violet|"
    r"navy|lavender|maroon|burgundy|cream|ivory|tan|peach|amber|"
    r"rainbow|two-tone|split-color|multicolored|multi-colored|gradient|colored) (.+)$"
)

# A reviewed set of color-bearing features, garments and scene objects. Objects,
# species and titles such as colored pencil, red panda, black hole and game boy
# color must not be caught by lexical matching.
COLOR_TARGETS = frozenset("""
hair|eyes|eye|skin|fur|wings|horns|horn|tail|nails|lips|eyelashes|sclera|
pubic hair|armpit hair|tongue|anus|inner hair|tips|inner animal ears|
animal ears|ears|tears|nipples|areolae|penis|pussy|
dress|skirt|bikini|serafuku|shirt|jacket|coat|pants|
bodysuit|apron|leotard|swimsuit|cape|capelet|cloak|kimono|sweater|shorts|
hoodie|vest|bandeau|bra|panties|clothes|clothing|gloves|handwear|legwear|
thighhighs|pantyhose|socks|footwear|shoes|boots|headwear|hat|hairband|
ribbon|bow|necktie|bowtie|neckerchief|neckwear|scarf|choker|eyepatch|
hair bobbles|scrunchie|buttons|sleeves|shoe soles|shoe interior|
flower|rose|butterfly|umbrella|background|sky|theme|outline|border|
fire|smoke|shadow|lights|stripes|polka dots|hair ornament|hat ornament|ornament
""".replace("\n", "").split("|"))

COLOR_ONLY_TAGS = frozenset({
    "alternate hair color", "official alternate hair color",
    "hair color connection", "colored inner hair", "streaked hair",
    "alternate skin color", "dark skin", "deep skin", "pale skin",
    "dark-skinned female", "dark-skinned male",
    "heterochromia", "no heterochromia", "heterochromatic eyewear",
    "mismatched animal ear colors", "alternate color school swimsuit",
    # `dark` 는 COLOR_PREFIX 에서 수식어 자리라(뒤에 색 단어가 와야 한다) 피부색 변형을 못 잡는다.
    "dark nipples", "dark areolae", "dark penis", "dark pussy", "dark anus",
})

# Shape, pattern, physical state, object, or a meaningful scene/action that
# merely happens to carry a color word.
PRESERVE_TAGS = frozenset({
    "peach ornament", "peach hair ornament", "peach hat ornament",
    "spotted hair", "striped hair", "tan", "tan lines", "albino",
    "rainbow", "rainbow flag", "rainbow print", "color drain", "color switch",
    "colored pencil", "color wheel", "color timer", "star color pen",
    "game boy color", "blue rose sword", "red panda", "red fox",
    "black hole", "white mage", "golden apple", "golden egg",
})


def normalize(text: str) -> str:
    return " ".join(str(text or "").replace("_", " ").casefold().split())


def color_exclusion_reason(name: str) -> str | None:
    """Return why a tag is color-only, or None when it means something else."""
    name = normalize(name)
    if name in PRESERVE_TAGS:
        return None
    if name in COLOR_ONLY_TAGS:
        return "color_only_attribute"
    match = COLOR_PREFIX.fullmatch(name)
    if match and match.group(1) in COLOR_TARGETS:
        return "color_variant"
    return None


def is_color_only(name: str) -> bool:
    return color_exclusion_reason(name) is not None


# ── 성인(Q/E) 배선 ─────────────────────────────────────────────────────────
#
# 원본 관측 DB 는 E/Q 게시물을 받아 두고도 **그 게시물을 E/Q 로 만드는 태그**
# (`sex` `penis` `fellatio` `girl on top` ...)를 전부 `outside_general_prompt_projection`
# 으로 빼서 postings 를 만들지 않았다. 그래서 E 로 걸러도 행위 태그가 한 번도 안
# 나왔다(실측 2026-09-11: E 게시물 태그의 30.9% 가 후보 밖, G 는 12.4%).
# 태그는 records 안에 전부 들어 있으므로 원본 Parquet 없이 다시 배선한다.
#
# 원본의 게시물 거르개(연령 위험어 · rape/guro/scat/incest/bestiality 등)는 그대로 두고,
# **그 범주에서 정규식 구멍으로 새어 나온 것**만 같은 범주로 막는다. 새 기준을 세우지 않는다.
#   - `\brape\b` 는 `raped` 를 못 잡았다   -> `you gonna get raped` 2,086건이 수용됐다
#   - `incest` 는 `selfcest`/`twincest` 를 못 잡았다
#   - `scat|feces` 는 `poop` 을 못 잡았다
#   - 연령 정규식에 `aged down` 이 없다    -> E/Q 에 1,291건
#
# ⚠️ 성인 태그를 여는 순간 **미성년 조합의 위험이 커진다.** 연령 거르개는 그 전에 실측으로
#    확인했다: 거르개 어휘가 수용 게시물에 남은 것은 의도된 옷 이름 예외
#    (`lolita fashion`·`babydoll`)뿐이었다. `flat chest`·`petite`·`school swimsuit` 는
#    성인 체형·의상 태그라 막지 않는다.

POLICY_ADULT_VERSION = "event-map-adult-v1"

# 정책 모드. 빌더의 `--policy` 가 고른다.
#   full : 아래 규칙을 전부 건다(기본).
#   none : 이 파일의 **정책**을 전부 끈다 - 색상 제외(질의 시점) · 게시물 거르개 확장 ·
#          후보 제외 갈래. 성인 갈래 배선(E/Q 태그의 postings)은 정책이 아니라 결함 수정이라 남는다.
# ⚠️ 모드 스위치의 범위 밖인 것: 원본 DB 의 수용 거르개(연령 위험어 · rape/guro/scat/incest ...).
#    그 게시물은 관측 DB 의 records 에 애초에 없다. Full 코퍼스를 원본으로 주고 빌더의
#    `--guard` 로 열어야 한다(`tools/event_map_sources.py`).
POLICY_MODES = ("full", "none")

# Q/E 게시물을 버린다. **켜고 끌 수 있다**(빌더의 `--age-floor`, 기본 on).
#
# ⚠️ 2026-09-12 테스터 이의: `aged down` 은 Danbooru 의 메타계열 태그로 Safebooru 에서도
#    추적된다. 정의는 "평소보다 어리게 그려진 경우"이고, **성인 캐릭터의 십대판**이나
#    **노인 캐릭터의 청년판**도 포함한다. 즉 미성년 묘사와 동의어가 아니다.
#    이 하한은 원본 관측 DB 의 거르개에 없었고 내가 더한 것이라(연령 정규식에 `aged down`
#    이 없어 Q/E 에 1,291건이 남은 것을 보고 막았다), 이의의 대상은 이 줄이다.
#    사용자 결정(2026-09-12): **Full 판은 끄고**, 검증을 거친 뒤 **상용 판에서만 재심**한다.
#    끄더라도 원본 거르개의 연령 어휘(`loli`·`child`·`teen`... - tools/thumb_age_guard.py)는
#    그대로다. 그것이 실제 법적 하한이고, `--guard` 와 이 스위치는 별개다.
AGE_FLOOR_RE = re.compile(r"\baged down\b", re.I)

# 모든 등급에서 게시물째 버린다 - 원본 거르개와 같은 범주의 새어 나온 형태.
ALWAYS_BLOCK_RE = re.compile(
    r"\b(?:rap(?:e|ed|es|ing)|drugged|selfcest|twincest|poop)\b", re.I)

# Q/E 게시물에서만 버린다. G/S 의 피 묘사(다크 판타지)는 살리되, 성적인 맥락과
# 섞이는 것은 막는다.
ADULT_BLOCK_RE = re.compile(
    r"\b(?:self-harm|suicide|wrist cutting|murder|abuse|violence|dismemberment)\b",
    re.I)
ADULT_BLOCK_SUBGROUPS = frozenset({"gore", "dark_content"})

# 후보로는 절대 내지 않는다(게시물은 남는다). 이벤트가 아니라 금기·연출 표시다.
NEVER_CANDIDATE_SUBGROUPS = frozenset({"taboo", "gore", "dark_content", "censorship", "symbol"})

# none 모드에서만 열리는 갈래(full 에서는 후보가 아니다). 시험하는 쪽이 따로 거를 수 있게
# 갈래 이름을 구별해 둔다.
UNPOLICED_ROLE_BY_SUBGROUP = {
    "taboo": "adult_taboo", "gore": "adult_gore", "dark_content": "adult_dark",
    "censorship": "adult_meta", "symbol": "adult_meta",
}

# 원본 소분류 -> 맵의 갈래. 없는 소분류는 `adult` 로 둔다(원본이 분류하지 않은 688개).
ADULT_ROLE_BY_SUBGROUP = {
    "sex_acts": "adult_act", "sex_act": "adult_act", "sexual_positions": "adult_act",
    "sex_position": "adult_act", "groping": "adult_act", "simulated_sex_acts": "adult_act",
    "sexual_situation": "adult_act", "activity": "adult_act", "situation": "adult_act",
    "fetish": "adult_act", "pose": "adult_act", "expression": "adult_act",
    "genitals": "adult_body", "anatomy": "adult_body", "nudity": "adult_body",
    "breasts_tags": "adult_body", "fluids": "adult_body", "exposure": "adult_body",
    "clothing_state": "adult_body", "sexual_activity": "adult_body",
    "sex_objects": "adult_object", "attire": "adult_object", "covering": "adult_object",
}


def post_block_rule(name: str, subgroup: str | None, mode: str = "full",
                    age_floor: bool = True) -> str | None:
    """이 태그를 **왜** 막는지(규칙 이름). 보고서가 규칙별로 셀 때 쓴다. 안 막으면 None."""
    name = normalize(name)
    if age_floor and AGE_FLOOR_RE.search(name):
        return "age_floor"
    if mode == "none":
        return None
    if ALWAYS_BLOCK_RE.search(name):
        return "always_block"
    if ADULT_BLOCK_RE.search(name):
        return "adult_block_name"
    if subgroup in ADULT_BLOCK_SUBGROUPS:
        return "adult_block_subgroup"
    return None


def adult_post_block(name: str, subgroup: str | None, mode: str = "full",
                     age_floor: bool = True) -> str | None:
    """이 태그가 달린 게시물을 버려야 하면 범위를 돌려준다: 'all' / 'adult' / None."""
    rule = post_block_rule(name, subgroup, mode, age_floor)
    if rule == "always_block":
        return "all"
    if rule:
        return "adult"
    return None


def adult_role(name: str, subgroup: str | None, mode: str = "full",
               age_floor: bool = True) -> str | None:
    """성인 갈래로 열 태그면 그 갈래를, 후보로 내지 않을 태그면 None."""
    if adult_post_block(name, subgroup, mode, age_floor):
        return None
    if mode == "none":
        return (UNPOLICED_ROLE_BY_SUBGROUP.get(subgroup or "")
                or ADULT_ROLE_BY_SUBGROUP.get(subgroup or "", "adult"))
    if subgroup in NEVER_CANDIDATE_SUBGROUPS:
        return None
    return ADULT_ROLE_BY_SUBGROUP.get(subgroup or "", "adult")
