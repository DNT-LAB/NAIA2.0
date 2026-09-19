"""Bounded English retrieval vocabulary for the 2026-09 Korean keyword update.

Each row records a source keyword for traceability, NOT a rule that translates
all Korean aliases. English phrases were checked against the canonical visual
concept. Bad/broader Korean aliases (e.g. socks/구두밑창, gloves/손가위,
white background/백그라운드) are deliberately not translated here.

Whole-query lookup only: no substring, stemming, modifier deletion, automatic
composition, or promotion into Chat's scene/role semantic certification.
"""
from __future__ import annotations

import re

VERSION = "english-keywords-20260918-v1"
SOURCE = "korean_keyword_supplement.json"

# canonical tag, motivating added Korean keyword, reviewed English queries.
KEYWORDS = (
    ("1girl", "여자애", ("one girl", "single girl", "one female character")),
    ("1boy", "남자애", ("one boy", "single boy", "one male character")),
    ("2girls", "여자 둘", ("two girls", "two female characters")),
    ("2boys", "두 명의 소년", ("two boys", "two male characters")),
    ("multiple girls", "다수 여캐", ("several girls", "multiple female characters", "many female characters", "many girls")),
    ("multiple boys", "남캐 여럿", ("several boys", "multiple male characters", "several male characters")),
    ("solo", "단독", ("one character", "single character")),
    ("looking at viewer", "카메라 시선", ("looking at camera", "looking into camera", "looking at the camera", "looking directly at viewer")),
    ("blush", "볼 빨개짐", ("flushed cheeks", "reddened cheeks", "blushing cheeks", "red cheeks")),
    ("open mouth", "입 벌림", ("mouth open", "opened mouth")),
    ("closed mouth", "입 다묾", ("shut mouth",)),
    ("closed eyes", "눈 감음", ("shut eyes",)),
    ("one eye closed", "한쪽 눈 감음", ("one closed eye", "one eye shut")),
    ("parted lips", "반개한 입", ("slightly parted lips", "half open mouth")),
    ("grin", "이를 드러내고 웃음", ("grinning",)),
    ("thighhighs", "허벅지 스타킹", ("thigh high stockings", "thigh-high stockings", "thigh high socks", "thigh-high socks")),
    ("collarbone", "빗장뼈", ("clavicle", "clavicles")),
    ("jewelry", "쥬얼리", ("jewellery",)),
    ("twintails", "양갈래", ("twin ponytails", "two ponytails", "double ponytail", "double ponytails")),
    ("full body", "전신샷", ("full body shot", "full-body shot", "whole body shot")),
    ("upper body", "바스트샷", ("upper body shot", "bust shot")),
    ("cowboy shot", "니샷", ("knee up shot", "knees up shot", "knee-up shot")),
    ("yellow eyes", "금안", ("gold eyes",)),
    ("grey hair", "회발", ("gray hair",)),
    ("grey eyes", "그레이안", ("gray eyes",)),
    ("grey background", "잿빛 배경", ("gray background", "ashen background")),
    ("braid", "댕기 머리", ("plaited hair",)),
    ("ponytail", "말총머리", ("pony tail",)),
    ("swimsuit", "미즈기", ("bathing suit", "swimming suit")),
    ("bikini", "2피스 수영복", ("two piece bathing suit",)),
    ("outdoors", "실외 배경", ("outdoor setting",)),
    ("indoors", "방 안", ("indoor setting", "indoor background")),
    ("sleeveless", "노스리브", ("without sleeves", "no sleeves")),
    ("collared shirt", "깃 있는 셔츠", ("shirt with collar", "shirt with a collar")),
    ("alternate costume", "다른 복장", ("alternative outfit", "alternate outfit", "different outfit")),
    ("necktie", "타이", ("neck tie",)),
    ("detached sleeves", "소매만", ("separate sleeves", "unattached sleeves")),
    ("greyscale", "무채색", ("grayscale", "grayscale image")),
    ("puffy sleeves", "벌룬 슬리브", ("puff sleeves", "puffed sleeves", "balloon sleeves", "balloon sleeve")),
    ("hairclip", "바레트", ("barrette", "hair clip")),
    ("barefoot", "나족", ("bare feet", "bare foot", "unshod")),
    ("bowtie", "보우타이", ("bow tie",)),
    ("elbow gloves", "긴 장갑", ("elbow length gloves", "elbow-length gloves")),
    ("sailor collar", "해군 깃", ("sailor style collar", "naval collar")),
    ("see-through clothes", "투명한 옷", ("transparent clothing", "sheer clothing", "see through clothing", "see-through clothing", "transparent clothes")),
    ("holding weapon", "무기를 든", ("holding a weapon", "wielding a weapon")),
    ("off shoulder", "어깨내림", ("off the shoulder", "off-the-shoulder", "off shoulder clothing")),
    ("on back", "앙와위", ("supine", "lying on back", "lying on one's back", "lying face up")),
    ("armpits", "겨드랑이노출", ("underarms", "underarm", "axilla", "underarm exposure")),
    ("spread legs", "가랑이벌리기", ("legs spread",)),
    ("nail polish", "네일폴리시", ("nail varnish",)),
    ("looking at another", "타인을 바라봄", ("looking at another person", "looking at someone else", "looking at others")),
    ("streaked hair", "브릿지 머리", ("hair streaks", "streaks in hair")),
    ("fingerless gloves", "손가락 없는 장갑", ("gloves without fingers",)),
    ("plaid clothes", "플래드", ("tartan clothing",)),
    ("hair bun", "경단머리", ("bun hairstyle", "hair in a bun")),
    ("two-tone hair", "이색 모발", ("two colored hair", "two-coloured hair", "two color hair")),
    ("from behind", "후면구도", ("back view", "view from behind")),
    ("from side", "옆면", ("view from the side",)),
    ("animal ear fluff", "귀안쪽털", ("inner ear fur", "fluffy inner ears")),
    ("rabbit ears", "바니귀", ("bunny ears",)),
    ("fluffy tail", "푹신한 꼬리", ("fluffy animal tail",)),
    ("sweatdrop", "당황땀", ("sweat drop",)),
    ("official art", "공식 일러", ("official illustration", "official artwork")),
    ("simple background", "심플 배경", ("minimal background", "plain background")),
    ("white background", "화이트 배경", ("white backdrop",)),
    ("hair between eyes", "가운데 앞머리", ("bangs between eyes", "bangs between the eyes")),
)


def normalize_english_keyword(value: str) -> str:
    return " ".join(str(value or "").lower().replace("_", " ").split())


def _build_aliases():
    aliases = {}
    for tag, _source_keyword, phrases in KEYWORDS:
        for phrase in phrases:
            key = normalize_english_keyword(phrase)
            if not re.fullmatch(r"[a-z0-9 '\-]+", key):
                raise ValueError(f"Invalid English keyword: {phrase}")
            if key in aliases and aliases[key] != tag:
                raise ValueError(f"Ambiguous English keyword: {phrase}")
            aliases[key] = tag
    return aliases


_ALIASES = _build_aliases()


def english_keyword_target(query: str) -> str | None:
    """An explicit whole phrase, not a fuzzy translation or a validation alias."""
    return _ALIASES.get(normalize_english_keyword(query))


def is_english_keyword_match(query: str, tag: str) -> bool:
    return english_keyword_target(query) == normalize_english_keyword(tag)
