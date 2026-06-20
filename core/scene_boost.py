# -*- coding: utf-8 -*-
"""Scene Boost — 이미 작성된 프롬프트(주로 danbooru 태그)를 **원샷**으로 배경/구도/분위기
자연어 + 검증된 구도 태그로 보강한다. 주체/의상/행위/인원수/저작권은 절대 바꾸지 않는다.

설계(=Codex 검수 반영): **구조는 코드가 소유**하고 소형 모델(Gemma E2B)은 스키마로
제약된 JSON 텍스트만 낸다. 등급/구도태그/톤은 코드가 결정하고, LLM은 (a) 자연어 묘사,
(b) 코드가 준 enum 안에서 구도 태그 *선택*만 한다.

파이프라인::

    parse(코드) → rating 집계(코드) → 구도후보·톤 준비(코드)
      → _chat 1회(스키마 제약) → 후필터(코드) → 조립

이 모듈은 **순수**하다(외부 의존 callable 주입): tag_rating / is_sexual / is_hardcore /
validate_tag / tag_allowed / has_hangul / chat. → 서비스 없이 단위 테스트 가능.
GUI 미연결 — 백엔드 로직만(요청대로 "적용 없이 코드 준비").
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

# 축 이름 상수(분류기는 서비스가 주입; 여기선 IO 없는 상수만 import → 순수성 유지).
from core.scene_axis import (
    ACTION, AXIS_PRIORITY, BODY, CLOTHING, COLOR, EXPRESSION, OBJECT, SETTING,
    is_central_act,
)


# ---------------------------------------------------------------------------
# 강도 레벨 — 문장 수·길이·구도태그 수·temperature를 한 손잡이로(_LEVELS 미러). 기본=rich.
# 풍부함은 "cinematic하게" 같은 모호한 지시가 아니라 개수/길이 캡으로 통제(Codex D).
# ---------------------------------------------------------------------------
# num_predict: 출력 토큰 상한(속도 backstop). 스키마 강제라 모델은 보통 알아서 멈추지만,
# 폭주 시 오버랩 창을 넘기지 않도록 레벨별 넉넉한 천장을 둔다(정상 출력은 절대 안 잘림).
SCENE_BOOST_LEVELS: dict[str, dict[str, Any]] = {
    "concise":  {"phrases": (1, 2), "words": (6, 12),  "comp_max": 1, "temperature": 0.25, "num_predict": 160},
    "standard": {"phrases": (2, 3), "words": (8, 16),  "comp_max": 2, "temperature": 0.30, "num_predict": 224},
    "rich":     {"phrases": (3, 4), "words": (10, 18), "comp_max": 3, "temperature": 0.32, "num_predict": 320},
    "max":      {"phrases": (4, 6), "words": (12, 22), "comp_max": 4, "temperature": 0.35, "num_predict": 448},
}
DEFAULT_LEVEL = "rich"

# 코드 큐레이션 구도/조명 태그 풀 — 전부 실제 danbooru 태그(런타임에 validate_tag로 재확인).
# lean: any(언제나) / bright(밝고 화사 — g·s 선호) / moody(어둡고 농밀 — q·e 선호).
# 등급은 톤 선택에만 쓰고, 태그 자체는 대부분 g등급이라 하드 게이트가 아니다.
_COMPOSITION_POOL: tuple[tuple[str, str], ...] = (
    # 앵글/샷 (any)
    ("from below", "any"), ("from above", "any"), ("from side", "any"),
    ("from behind", "any"), ("dutch angle", "any"), ("close-up", "any"),
    ("portrait", "any"), ("upper body", "any"), ("cowboy shot", "any"),
    ("wide shot", "any"), ("scenery", "any"),
    # 심도/포커스 (any)
    ("depth of field", "any"), ("blurry background", "any"), ("bokeh", "any"),
    ("motion blur", "any"),
    # 밝은 조명 (bright)
    ("sunlight", "bright"), ("dappled sunlight", "bright"), ("god rays", "bright"),
    ("lens flare", "bright"), ("backlighting", "bright"), ("light rays", "bright"),
    ("sunbeam", "bright"), ("soft lighting", "bright"),
    # 무드 조명 (moody)
    ("dim lighting", "moody"), ("dramatic shadow", "moody"), ("rim lighting", "moody"),
    ("chiaroscuro", "moody"), ("spotlight", "moody"), ("candlelight", "moody"),
    ("moonlight", "moody"), ("backlit", "moody"), ("silhouette", "moody"),
    ("neon lights", "moody"),
)

# 모순 구도 쌍 — 한쪽이 이미 있으면 반대쪽을 제안하지 않는다(Codex 카메라 가드).
_CAMERA_CONTRADICTIONS: dict[str, str] = {
    "from below": "from above", "from above": "from below",
    "close-up": "wide shot", "wide shot": "close-up",
    "portrait": "wide shot",
}

# 샷 거리(프레임에 피사체가 얼마나 담기나) — 상호 배타 그룹. 하나의 컷이 close-up이면서
# 동시에 upper body·portrait일 수 없다. 광원 차단 후 소형 모델이 close-up+upper body+
# portrait를 한꺼번에 적층하던 단조로움을 차단하기 위해 결과에 최대 1개만 허용한다(angle/
# depth 축과는 별개라 from below·depth of field 등과는 함께 쓸 수 있다).
_SHOT_DISTANCE_TAGS = frozenset({
    "close-up", "upper body", "portrait", "cowboy shot", "wide shot",
})

# 톤 팔레트 — *사실이 아닌 단어 힌트*(Codex E). LLM 묘사의 어조만 끌고, 명사/행위는 안 만든다.
_TONE_PALETTE: dict[str, tuple[str, ...]] = {
    "g": ("serene", "wholesome", "gentle", "bright", "innocent", "airy"),
    "s": ("warm", "inviting", "soft", "tender", "dreamy", "sun-kissed"),
    "q": ("sultry", "charged", "intimate", "flushed", "yearning", "hazy"),
    "e": ("intense", "feverish", "low-key", "raw", "breathless", "smouldering"),
}

# 등급별 포커스(사용자 스펙) — 톤(어조)만 바꾸던 것을 넘어, 보강 *방향*을 등급에 맞춰
# 강제한다. 어디까지나 **기존 태그가 이미 담은 것**을 강조/프레이밍할 뿐, 새 인물·소품·
# 행위는 만들지 않는다(코드의 _tag_allowed 등급 상한이 안전선). NAIA=성인 일러스트 툴.
_RATING_FOCUS: dict[str, str] = {
    "g": ("Keep it wholesome: only lighting, weather, time of day and background scenery. "
          "No exposure, no intimacy, no suggestive framing."),
    "s": ("Suggestive, inviting atmosphere centered on the existing subject(s): soft warm tone "
          "with gentle emphasis on the figure and the setting. No explicit anatomy or acts."),
    "q": ("Sensual focus: directly frame the exposure the tags already show — the bared skin, "
          "the pose, and the heated tension. You MAY reference the "
          "existing exposed pose/body to frame it concretely (that is NOT 'repeating tags'); only "
          "invent no new people, body parts, or sexual acts. Avoid vague shadow/mist filler."),
    "e": ("Explicit focus: directly and boldly frame the exposed, intimate scene the tags already "
          "depict — the bared body, the act, and the raw "
          "physical heat and tension. You MAY reference the existing exposure/pose/act to frame it "
          "concretely (NOT vague shadows or mist); only invent no new people, body parts, props, "
          "or acts. At least half the phrases must be about the body, pose, and act, not weather."),
}

# NAI/A1111 가중치·강조 래퍼 — bare 태그 추출용.
_WEIGHT_PREFIX_RE = re.compile(r"^\s*\d*\.?\d+\s*::")        # "1.2::"
_WEIGHT_SUFFIX_RE = re.compile(r"::\s*$")                     # 끝의 "::"
_A1111_WEIGHT_RE = re.compile(r":\s*-?\d*\.?\d+\s*$")        # "tag:1.2"
_NAMESPACE_RE = re.compile(r"^(artist|copyright|character|series|meta|general|studio):", re.I)
_PERSON_COUNT_RE = re.compile(r"^\d+\s*\+?(girl|boy|other)s?$|^(solo|multiple girls|multiple boys)$", re.I)
# 새 인물 도입(드리프트) 탐지 — 묘사가 새 사람을 등장시키면 거부.
_SUBJECT_INTRO_RE = re.compile(
    r"\b(another|a second|a third|two|three|four|\d+)\s+"
    r"(girl|boy|woman|man|person|people|child|figure|character|lady|guy)s?\b", re.I)

_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "with", "her",
    "his", "its", "their", "into", "over", "under", "as", "by", "for", "from",
    "is", "are", "be", "this", "that", "soft", "warm",
})

_COLOR_ALIASES = {
    "blond": "blonde",
    "golden": "gold",
    "grey": "gray",
}
_COLOR_WORDS = frozenset({
    "amber", "aqua", "beige", "black", "blond", "blonde", "blue", "brown", "crimson",
    "cyan", "gold", "golden", "gray", "grey", "green", "indigo", "ivory", "lavender",
    "magenta", "maroon", "navy", "orange", "peach", "pink", "purple", "red", "rose",
    "ruby", "scarlet", "silver", "teal", "turquoise", "violet", "white", "yellow",
})
_EYE_COLOR_TARGET_RE = re.compile(
    r"\b(?P<color>amber|aqua|black|blue|brown|crimson|cyan|gold|golden|gray|grey|green|"
    r"pink|purple|red|silver|teal|turquoise|violet|white|yellow)\s+"
    r"(eyes?|gaze|irises?|pupils?)\b|\b(?P<hyphen>amber|aqua|black|blue|brown|crimson|cyan|"
    r"gold|golden|gray|grey|green|pink|purple|red|silver|teal|turquoise|violet|white|yellow)-eyed\b",
    re.I,
)
# 스타일 감지 정규식 — 입력 소스 탐지(_contains_style_source)와 설명문 필터(filter_descriptions)
# 양쪽에 쓰인다. \b…\b 단어 매칭이라 형태 변화형(scented/silky/glowing/hazy…)이 새던 것을
# 명시 변형으로 보강한다(불명확한 stem은 피하고 확실한 스타일 단어만 — 오탐 최소화).
_SCENT_RE = re.compile(
    r"\b(scent|scented|smell|smells|smelling|aroma|aromatic|fragrance|fragrant|perfume|perfumed|"
    r"musk|musky|jasmine|incense)\b",
    re.I,
)
_MATERIAL_RE = re.compile(
    r"\b(fabric|cloth|leather|leathery|silk|silky|satin|satiny|velvet|velvety|lace|lacy|latex|"
    r"metal|metals|metallic|denim|gloss|glossy|sheen|texture|textures|textured)\b",
    re.I,
)
_LIGHT_STYLE_RE = re.compile(
    r"\b(light|lighting|glow|glowing|glows|haze|hazy|sunlight|sunlit|moonlight|moonlit|daylight|"
    r"backlight|backlit|backlighting|rim light|lamplight|candlelit|sunbeam|sunbeams|dappled|dimly|"
    r"rays?|flares?|illumination|spotlight|shadow|shadowy|golden hour)\b",
    re.I,
)
_LIGHT_COLOR_CONTEXT_RE = re.compile(
    r"\b(amber|gold|golden|blue|white|pink|red|purple|violet|orange|silver)\s+"
    r"(light|lighting|glow|haze|rays?|flare|illumination|sunlight|moonlight|daylight|hour)\b|"
    r"\b(light|lighting|glow|haze|rays?|flare|illumination|sunlight|moonlight|daylight)\s+"
    r"(amber|gold|golden|blue|white|pink|red|purple|violet|orange|silver)\b",
    re.I,
)


# ---------------------------------------------------------------------------
# 1) 파싱(코드) — 원문 보존 + bare 서술 태그 추출 + 보호 토큰 분리.
# ---------------------------------------------------------------------------
def _bare_tag(token: str) -> str:
    """NAI/A1111 가중치·강조 래퍼를 벗겨 순수 태그를 만든다."""
    t = str(token or "").strip()
    if not t:
        return ""
    t = _WEIGHT_PREFIX_RE.sub("", t)
    t = _WEIGHT_SUFFIX_RE.sub("", t)
    # 둘러싼 강조 괄호/중괄호/대괄호를 반복 제거.
    for _ in range(6):
        s = t.strip()
        if len(s) >= 2 and ((s[0] == "(" and s[-1] == ")") or (s[0] == "{" and s[-1] == "}") or (s[0] == "[" and s[-1] == "]")):
            t = s[1:-1]
        else:
            break
    t = _A1111_WEIGHT_RE.sub("", t).strip()  # "tag:1.2" → "tag"
    return t.lower().replace("_", " ").strip()


def format_nl_weight(text: str, weight: float, is_nai: bool) -> str:
    """자연어 보강분에 가중치 부여(설정 [기능1]). NAI: '{w}::text ::', 로컬(A1111/Comfy):
    '(text:w)'. weight≈1.0이면 그대로(가중치 없음). 범위는 호출부가 0.75~3로 보장."""
    s = str(text or "").strip().strip(",").strip()
    if not s:
        return ""
    try:
        w = float(weight)
    except Exception:
        return s
    if abs(w - 1.0) < 1e-3:
        return s
    w = max(0.75, min(3.0, w))
    return f"{w:g}::{s} ::" if is_nai else f"({s}:{w:g})"


def strip_weight_syntax(prompt: str) -> str:
    """가중치 구문({n}::, ::, (text:n))을 제거해 순수 태그 나열로(설정 [기능3] Ollama 입력용).
    주석(#)·개행·빈 토큰 제거. 각 토큰을 _bare_tag로 벗긴다."""
    out: list[str] = []
    for raw in str(prompt or "").replace("\n", ",").split(","):
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        bare = _bare_tag(raw)
        if bare:
            out.append(bare)
    return ", ".join(out)


def parse_prompt(prompt: str) -> dict[str, Any]:
    """프롬프트를 파싱. 원문은 verbatim 보존하고 분석용 메타만 뽑는다.

    반환::
        {original, descriptive:[bare 서술태그], protected:[원래토큰], subject_count:[...],
         existing_camera:[풀에 있는 기존 구도태그], all_words:set(에코 판정용)}
    """
    original = str(prompt or "").strip()
    pool_tags = {tag for tag, _ in _COMPOSITION_POOL}
    descriptive: list[str] = []
    protected: list[str] = []
    subject_count: list[str] = []
    existing_camera: list[str] = []
    all_words: set[str] = set()
    seen: set[str] = set()
    for raw in original.split(","):
        raw = raw.strip()
        if not raw:
            continue
        bare = _bare_tag(raw)
        if not bare:
            continue
        for w in bare.split():
            all_words.add(w)
        if _NAMESPACE_RE.match(raw.strip()) or _NAMESPACE_RE.match(bare):
            protected.append(raw)
            continue
        if _PERSON_COUNT_RE.match(bare):
            subject_count.append(bare)
        if bare in pool_tags:
            existing_camera.append(bare)
        if bare not in seen:
            seen.add(bare)
            descriptive.append(bare)
    return {
        "original": original,
        "descriptive": descriptive,
        "protected": protected,
        "subject_count": subject_count,
        "existing_camera": existing_camera,
        "all_words": all_words,
    }


def _norm_color(color: str) -> str:
    c = str(color or "").strip().lower()
    return _COLOR_ALIASES.get(c, c)


def _input_colors(tags: list[str]) -> set[str]:
    colors: set[str] = set()
    for tag in tags or []:
        for word in re.findall(r"[a-zA-Z]+", str(tag or "").lower()):
            if word in _COLOR_WORDS:
                colors.add(_norm_color(word))
    return colors


def _input_eye_colors(tags: list[str]) -> set[str]:
    colors: set[str] = set()
    for tag in tags or []:
        text = str(tag or "").lower()
        for match in _EYE_COLOR_TARGET_RE.finditer(text):
            color = match.group("color") or match.group("hyphen")
            if color:
                colors.add(_norm_color(color))
    return colors


def _contains_style_source(tags: list[str], pattern: re.Pattern[str]) -> bool:
    return any(pattern.search(str(tag or "")) for tag in tags or [])


def _description_has_uninput_color(text: str, allowed_colors: set[str], *, allow_light_style: bool) -> bool:
    low = str(text or "").lower()
    for m in re.finditer(r"[a-zA-Z]+", low):
        word = m.group(0)
        if word not in _COLOR_WORDS:
            continue
        color = _norm_color(word)
        if color in allowed_colors:
            continue
        if allow_light_style:
            # 이 색 단어의 *국소* 이웃(±16자)만 검사 — 'golden glow' 같은 조명색만 면제하고,
            # 같은 구절 다른 위치의 조명색이 객체색('blue dress')까지 면제하던 버그를 막는다.
            a = max(0, m.start() - 16)
            b = min(len(low), m.end() + 16)
            if _LIGHT_COLOR_CONTEXT_RE.search(low[a:b]):
                continue
        return True
    return False


def _description_has_uninput_eye_color(text: str, allowed_eye_colors: set[str]) -> bool:
    for match in _EYE_COLOR_TARGET_RE.finditer(str(text or "")):
        color = _norm_color(match.group("color") or match.group("hyphen") or "")
        if color and color not in allowed_eye_colors:
            return True
    return False


def _style_options(options: dict[str, Any] | None) -> dict[str, bool]:
    source = options if isinstance(options, dict) else {}
    return {
        "allow_scent_style": bool(source.get("allow_scent_style", True)),
        "allow_material_style": bool(source.get("allow_material_style", True)),
        "allow_light_style": bool(source.get("allow_light_style", True)),
    }


# 미입력 OBJECT/SETTING 명사 도입(환각) 가드의 면제 어휘 — 지시문이 허용하는 분위기/조명/
# 시간/날씨/구도 + 인물 프레이밍 generic. 이들은 태그가 없어도 자연어 분위기로 허용한다.
# (실측: sky/clouds/sunset/moon/light/shadow는 SETTING으로 분류되지만 분위기 어휘라 면제;
#  bird/duck/flower/bed/window/classroom/desk/animal/chick은 그대로 환각으로 걸린다.)
_AMBIENT_ALLOW = frozenset({
    "light", "lights", "lighting", "lit", "sunlight", "moonlight", "daylight", "backlight",
    "backlit", "backlighting", "glow", "glowing", "haze", "hazy", "shadow", "shadows", "shade",
    "ray", "rays", "sunbeam", "sunbeams", "beam", "beams", "flare", "bokeh", "spotlight",
    "candlelight", "chiaroscuro", "rim", "silhouette", "neon", "illumination", "highlight",
    "highlights", "gleam", "shine", "shimmer", "reflection", "reflections", "luminous",
    "sky", "skies", "cloud", "clouds", "sun", "sunrise", "sunset", "dawn", "dusk", "twilight",
    "moon", "moonlit", "star", "stars", "starlight", "night", "evening", "morning", "noon",
    "afternoon", "midday", "horizon", "mist", "fog", "rain", "snow", "breeze", "wind", "air",
    "atmosphere", "ambience", "dust", "weather", "golden", "depth", "field", "focus", "blur",
    "angle", "frame", "framing", "perspective", "view", "scene", "scenery", "background",
    "backdrop", "foreground", "distance", "surroundings", "figure", "figures", "form", "pose",
    "composition", "scale", "space", "setting", "ground",
})


def _introduces_object(
    text: str, input_words: set[str], classify_axes: Callable[[str], frozenset[str]]
) -> bool:
    """미입력 OBJECT/SETTING 태그(prop/장소/동물)를 새로 도입하면 True(환각). 분위기/프레이밍
    어휘(_AMBIENT_ALLOW)와 입력 태그 단어, body/clothing 류는 면제 — 'duck'/'bed'/'flower'는
    잡고 'skin'/'hand'/'shadow'/'sky'는 통과시킨다(가드 후필터, classify_axes 주입 시만 작동)."""
    for w in re.findall(r"[a-z']{3,}", str(text or "").lower()):
        if w in _STOPWORDS or w in _AMBIENT_ALLOW or w in input_words:
            continue
        axes = classify_axes(w)
        if OBJECT in axes or SETTING in axes:
            return True
    return False


# ---------------------------------------------------------------------------
# 2) 등급 집계(코드) — 한 스트레이 태그가 좌우하지 않게, 그러나 실제 explicit는 explicit로.
# ---------------------------------------------------------------------------
def aggregate_rating(
    tags: list[str],
    *,
    tag_rating: Callable[[str], str],
    is_sexual: Optional[Callable[[str], bool]] = None,
    is_hardcore: Optional[Callable[[str], bool]] = None,
) -> str:
    """서술 태그들의 per-tag 등급을 하나의 장면 등급(g/s/q/e)으로 집계(Codex A).

    규칙: ① 하드코어 키워드 또는 *성적* e-태그 1개라도 → e. ② e+q ≥ 2이고 e≥1 → e.
    ③ e+q ≥ 2 또는 q ≥ 1 → q. ④ s+q+e ≥ 2 또는 s ≥ 1 → s. ⑤ 그 외 g.
    """
    if not tags:
        return "g"
    joined = " ".join(tags).lower()
    if is_hardcore and is_hardcore(joined):
        return "e"
    tiers = [tag_rating(t) for t in tags]
    if is_sexual is not None:
        if any(tiers[i] == "e" and is_sexual(t) for i, t in enumerate(tags)):
            return "e"
    e = tiers.count("e")
    q = tiers.count("q")
    s = tiers.count("s")
    if e >= 2 and (e + q) >= 2:
        return "e"
    if (e + q) >= 2 or q >= 1:
        return "q"
    if (s + q + e) >= 2 or s >= 1:
        return "s"
    return "g"


# ---------------------------------------------------------------------------
# 3) 구도 후보(코드) — 등급으로 톤(밝음/무드) 선택, 모순 제외, validate_tag로 실재 확인.
#    태그 실재성은 안 변하므로 모듈 캐시(반복 호출 시 재검색 비용 0).
# ---------------------------------------------------------------------------
_VALIDATE_CACHE: dict[str, bool] = {}


def composition_candidates(
    rating: str,
    existing_camera: list[str],
    level_cfg: dict[str, Any],
    *,
    validate_tag: Optional[Callable[[str], Optional[dict]]] = None,
    tag_allowed: Optional[Callable[[str, str], bool]] = None,
    allow_lighting: bool = True,
    variety_seed: int = 0,
) -> list[str]:
    """등급에 맞는 코드 큐레이션 구도/조명 태그 후보. LLM은 이 enum 안에서만 고른다.

    allow_lighting=False면 조명/톤 태그(bright·moody 풀: sunlight·chiaroscuro·dim
    lighting 등)를 후보에서 제외하고 앵글/샷/심도(any 풀)만 제안한다. '광원·색조 허용'
    (allow_light_style) OFF 시 조명 태그가 *구도 태그*로 계속 추가되던 버그 수정 —
    설명문 경로는 filter_descriptions가 이미 차단하지만, 구도 후보는 게이트가 없었다.

    variety_seed!=0이면 'any'(앵글/샷/심도) 풀을 그만큼 회전시켜 매 장면 후보 enum의 선두가
    달라지게 한다. 캡(cap)이 풀보다 작아 일부 장면은 close-up이 enum에서 빠지므로, 광원
    차단 후 모델이 close-up만 반복하던 고착을 결정론적으로 분산한다(같은 입력→같은 회전,
    테스트 가능). run_scene_boost가 장면 태그에서 안정 해시를 만들어 전달한다."""
    prefer = "moody" if rating in ("q", "e") else "bright"
    existing = set(existing_camera or [])
    blocked = {_CAMERA_CONTRADICTIONS.get(t) for t in existing}
    blocked.discard(None)

    def _eligible(tag: str) -> bool:
        if tag in existing or tag in blocked:
            return False                   # 이미 있음/모순 → 제외
        if tag_allowed is not None and not tag_allowed(tag, "e"):
            return False
        if validate_tag is not None:
            ok = _VALIDATE_CACHE.get(tag)
            if ok is None:
                try:
                    ok = bool(validate_tag(tag))
                except Exception:
                    ok = False
                _VALIDATE_CACHE[tag] = ok
            if not ok:
                return False               # 인덱스에 없는 태그 → 드롭
        return True

    # bright/moody 풀은 전부 조명 태그 — allow_lighting=False면 통째로 비운다(앵글/심도
    # 'any' 풀만 남는다). 후보 enum에서 빠지면 LLM이 고를 수도, filter_composition이
    # 통과시킬 수도 없으므로 조명 태그가 구도로 새지 않는다.
    prefer_list = (
        [t for t, l in _COMPOSITION_POOL if l == prefer and _eligible(t)]
        if allow_lighting else []
    )
    any_list = [t for t, l in _COMPOSITION_POOL if l == "any" and _eligible(t)]
    if variety_seed and len(any_list) > 1:
        off = variety_seed % len(any_list)
        any_list = any_list[off:] + any_list[:off]
    # LLM 선택지는 넉넉히(캡의 약 3배)만 — 너무 길면 소형 모델이 흔들린다. 등급별 톤(prefer)을
    # 범용(any)과 *교차*로 채워, 캡에 잘려도 톤 태그가 반드시 후보에 들어가게 한다.
    cap = max(6, int(level_cfg.get("comp_max", 2)) * 3)
    out: list[str] = []
    pi = ai = 0
    while len(out) < cap and (pi < len(prefer_list) or ai < len(any_list)):
        if pi < len(prefer_list):
            out.append(prefer_list[pi]); pi += 1
        if len(out) < cap and ai < len(any_list):
            out.append(any_list[ai]); ai += 1
    return out


# ---------------------------------------------------------------------------
# 4) 후필터(코드) — 드리프트/에코/한글/길이/모순 제거.
# ---------------------------------------------------------------------------
def filter_descriptions(
    descs: list[str],
    input_words: set[str],
    level_cfg: dict[str, Any],
    *,
    input_tags: Optional[list[str]] = None,
    style_options: Optional[dict[str, bool]] = None,
    has_hangul: Optional[Callable[[str], bool]] = None,
    classify_axes: Optional[Callable[[str], frozenset[str]]] = None,
) -> list[str]:
    """LLM 자연어 묘사를 검열: 한글/길이초과/새 인물도입/미입력 객체·색/태그에코/중복 제거."""
    _, word_hi = level_cfg.get("words", (6, 18))
    max_words = int(word_hi) + 4            # slack
    phrase_hi = int(level_cfg.get("phrases", (1, 3))[1])
    input_tags = input_tags or []
    style = _style_options(style_options)
    allowed_colors = _input_colors(input_tags)
    allowed_eye_colors = _input_eye_colors(input_tags)
    has_scent_source = _contains_style_source(input_tags, _SCENT_RE)
    has_material_source = _contains_style_source(input_tags, _MATERIAL_RE)
    has_light_source = _contains_style_source(input_tags, _LIGHT_STYLE_RE)
    out: list[str] = []
    seen: set[str] = set()
    # echo만 걸린(다른 모든 가드는 통과한) 후보 — 전부 echo로 잘려 빈 출력이 되는 것을 막는
    # 최후 폴백용. 신체 위주(q/e) 프롬프트는 본문이 노출/신체를 *참조*해야 하므로(등급 focus의
    # 의도) echo가 잦다 — 이때 통째 빈 출력 대신 겹침이 가장 적은 하나를 되살린다.
    echo_only: list[tuple[float, str]] = []
    for d in descs or []:
        s = str(d or "").strip().strip(".,").strip()
        if not s:
            continue
        if has_hangul is not None and has_hangul(s):
            continue                        # 영어 전용
        words = s.split()
        if len(words) > max_words:
            continue                        # 너무 김 → 태그 프롬프트 희석
        if _SUBJECT_INTRO_RE.search(s):
            continue                        # 새 인물 도입(드리프트)
        if _description_has_uninput_eye_color(s, allowed_eye_colors):
            continue                        # 미입력 눈색 hallucination
        if _description_has_uninput_color(s, allowed_colors, allow_light_style=style["allow_light_style"]):
            continue                        # 미입력 색상 hallucination
        if classify_axes is not None and _introduces_object(s, input_words, classify_axes):
            continue                        # 미입력 OBJECT/SETTING 명사 도입(환각 prop/장소/동물)
        if not style["allow_scent_style"] and not has_scent_source and _SCENT_RE.search(s):
            continue
        if not style["allow_material_style"] and not has_material_source and _MATERIAL_RE.search(s):
            continue
        if not style["allow_light_style"] and not has_light_source and _LIGHT_STYLE_RE.search(s):
            continue
        # 에코: 묘사의 내용어가 거의 다 입력 태그 단어면(순수 재진술) 버린다.
        content = [w.lower() for w in re.findall(r"[a-zA-Z']+", s) if w.lower() not in _STOPWORDS]
        if content:
            overlap = sum(1 for w in content if w in input_words)
            if overlap / len(content) >= 0.7:   # 거의 입력 태그의 재진술 → 분위기 0
                echo_only.append((overlap / len(content), s))
                continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= phrase_hi:
            break
    # 최후 폴백: echo로만 전부 잘려 빈 출력이면, 겹침이 가장 적은(=가장 덜 재진술) 후보 하나를
    # 되살린다 — 다른 환각 가드는 이미 통과했으므로 안전. (q/e 신체 위주 프롬프트가 통째로
    # 자연어 0이 되던 문제 수정.)
    if not out and echo_only:
        out.append(min(echo_only, key=lambda x: x[0])[1])
    return out


def filter_composition(
    picks: list[str],
    candidates: list[str],
    existing_camera: list[str],
    level_cfg: dict[str, Any],
) -> list[str]:
    """LLM이 고른 구도 태그를 검증: 후보 enum 내 + 기존/상호 모순 제거 + 캡."""
    allowed = set(candidates or [])
    existing = set(existing_camera or [])
    cap = int(level_cfg.get("comp_max", 2))
    out: list[str] = []
    used = set(existing)
    # 샷 거리 태그는 결과(+기존 카메라)를 통틀어 1개만 — close-up+upper body+portrait 적층 방지.
    shot_used = any(t in _SHOT_DISTANCE_TAGS for t in existing)
    for p in picks or []:
        t = str(p or "").strip().lower().replace("_", " ")
        if t not in allowed or t in used:
            continue
        if _CAMERA_CONTRADICTIONS.get(t) in used:
            continue                        # 이미 고른 것과 모순
        if t in _SHOT_DISTANCE_TAGS:
            if shot_used:
                continue                    # 샷 거리 중복 → 스킵
            shot_used = True
        used.add(t)
        out.append(t)
        if len(out) >= cap:
            break
    return out


# ---------------------------------------------------------------------------
# 4.5) 접지(코드) — 입력 태그를 축 버킷 + Priority anchors로 정리(라벨만, prose 없음).
#   classify_axes(서비스 주입)로 결정론 분류 → LLM에 "무엇을 프레이밍할지" 근거를 준다.
#   prose 요약을 만들지 않는다(2-stage 환각통로 차단, Claude+Codex 협의 2026-06-13).
# ---------------------------------------------------------------------------
# 너무 흔해 앵커로서 변별력 없는 태그 — Priority/other에서 다운랭크(버킷엔 남는다).
_BLAND_ANCHORS = frozenset({
    "solo", "smile", "blush", "looking at viewer", "closed mouth", "open mouth", "grin",
    "simple background", "white background", "standing", "bangs", "parted lips", "teeth",
    "looking away", "long hair", "short hair",
})
# 버킷 표시 순서/라벨.
_BUCKET_ORDER: tuple[tuple[str, str], ...] = (
    (ACTION, "Action/pose"), (OBJECT, "Objects"), (SETTING, "Setting"),
    (CLOTHING, "Clothing"), (BODY, "Body"), (EXPRESSION, "Expression"),
)
# Priority anchor salience(낮을수록 우선): 미분류 명물(None) 최상 → object/action → setting → 의류 → 신체/표정.
_AXIS_SALIENCE = {None: 0, OBJECT: 1, ACTION: 1, SETTING: 2, CLOTHING: 3, BODY: 4, EXPRESSION: 4, COLOR: 9}

# 메타/상태/POV 태그 — 프레이밍 대상이 아님("the in-universe location"처럼 어색해진다).
# 버킷·priority에서 제외(immutable 태그줄엔 남아 모델이 보긴 한다). 부재(no~)·미착용·POV·in-universe.
_META_NOISE_ANCHORS = frozenset({"in-universe location", "pov peephole", "unworn eyewear"})
_META_NOISE_RE = re.compile(r"^(no|unworn|partially)\b|^pov\b|in-universe", re.I)


def _is_meta_noise(tag: str) -> bool:
    t = str(tag or "")
    return t in _META_NOISE_ANCHORS or bool(_META_NOISE_RE.search(t))


def build_grounding(
    descriptive: list[str],
    *,
    classify_axes: Optional[Callable[[str], frozenset[str]]] = None,
    existing_camera: Optional[list[str]] = None,
    subject_count: Optional[list[str]] = None,
) -> dict[str, Any]:
    """입력 태그를 축 버킷 + other-notable(미분류 명물) + priority anchors로 묶는다.

    카메라/인원수 태그는 앵커가 아니라 제외. 색 태그는 버킷 제외(가드 담당). classify_axes
    없으면(목/폴백) 전부 미분류 → buckets 비고 other/priority만 채워진다(degrade-safe)."""
    skip = set(existing_camera or []) | set(subject_count or [])
    buckets: dict[str, list[str]] = {axis: [] for axis, _ in _BUCKET_ORDER}
    other: list[str] = []
    prim_of: dict[str, Optional[str]] = {}
    for t in descriptive:
        if t in skip or _is_meta_noise(t):
            prim_of[t] = "skip"
            continue
        axes = classify_axes(t) if classify_axes else frozenset()
        prim = next((a for a in AXIS_PRIORITY if a in axes and a in buckets), None)
        if prim is None and COLOR in axes:
            prim_of[t] = COLOR
            continue
        prim_of[t] = prim
        if prim is None:
            if t not in _BLAND_ANCHORS:
                other.append(t)
        else:
            buckets[prim].append(t)
    # 핵심 행위(named interaction)는 q/e 부스트가 반드시 프레이밍해야 하는 대상 — priority
    # 최상단으로(salience -1). non-act distinctive(other/object 등)는 그 뒤에 보존(Codex:
    # act가 슬롯 독점 금지). central_acts는 별도로도 반환해 instruction "Central act" 라인에 쓴다.
    central_acts = [t for t in descriptive if t not in skip and is_central_act(t)]
    cand = [
        t for t in descriptive
        if prim_of.get(t) not in ("skip", COLOR) and t not in _BLAND_ANCHORS
    ]
    cand.sort(key=lambda t: -1 if is_central_act(t) else _AXIS_SALIENCE.get(prim_of.get(t), 5))
    priority: list[str] = []
    for t in cand:
        if t not in priority:
            priority.append(t)
        if len(priority) >= 6:
            break
    return {"buckets": buckets, "other": other, "priority": priority, "central_acts": central_acts}


def _format_grounding(grounding: dict[str, Any]) -> str:
    """접지 dict → LLM 프롬프트용 compact 라벨 블록(prose 아님, 라벨:값 나열)."""
    lines: list[str] = []
    buckets = grounding.get("buckets") or {}
    for axis, label in _BUCKET_ORDER:
        vals = buckets.get(axis) or []
        if vals:
            lines.append(f"- {label}: {', '.join(vals[:12])}")
    other = grounding.get("other") or []
    if other:
        lines.append(f"- Other notable: {', '.join(other[:8])}")
    return "\n".join(lines)


def _drop_if_all_generic(descs: list[str], grounding: dict[str, Any]) -> list[str]:
    """앵커가 있는데(priority 존재) 살아남은 묘사가 *전부* 앵커-free generic이면 통째 드롭.
    한 구절이라도 입력 앵커 단어를 참조하면 전부 유지(Codex: ALL generic일 때만 drop)."""
    if not descs or not grounding or not grounding.get("priority"):
        return descs
    sources = list(grounding.get("priority") or []) + list(grounding.get("other") or [])
    for vals in (grounding.get("buckets") or {}).values():
        sources.extend(vals)
    anchor_words: set[str] = set()
    for t in sources:
        for w in str(t).split():
            if len(w) >= 3 and w not in _STOPWORDS:
                anchor_words.add(w)
    if not anchor_words:
        return descs
    for d in descs:
        if set(re.findall(r"[a-z']+", str(d).lower())) & anchor_words:
            return descs           # 최소 한 구절이 앵커 참조 → 전부 유지
    return []                       # 전부 generic → 드롭


# ---------------------------------------------------------------------------
# 5) LLM 호출 — 지시문 + 스키마. 단일 few-shot, enum 제약, minItems 0(빈 출력 허용).
# ---------------------------------------------------------------------------
# few-shot 예시 뱅크 — 단일 고정 예시는 소형 모델이 그 표현(예: "a low angle …")을 매 장면
# 그대로 복붙해 다양성을 죽인다. variety_seed로 회전해 장면마다 다른 예시를 보여준다. 설명문은
# 카메라-샷 단어("close-up"/"low angle"/"from below")를 쓰지 않고 앵커·무드만 프레이밍하고,
# 카메라/앵글은 composition_tags가 담당한다(설명문 단어 복붙 고착 차단). 위 "Example anchors"
# (sitting/looking out window/school uniform/classroom)와 일치하게 구성.
_EXAMPLE_BANK_NOLIGHT = (
    '{"descriptions": ["her school uniform settling as she sits by the window", "a quiet, unhurried air about her at the desk"], "composition_tags": ["depth of field", "from side"]}',
    '{"descriptions": ["the loose drape of her uniform across one shoulder", "her attention drifting toward the window"], "composition_tags": ["from behind", "bokeh"]}',
    '{"descriptions": ["her hands resting on the desk as she turns slightly", "the hushed stillness of the classroom around her"], "composition_tags": ["dutch angle", "depth of field"]}',
    '{"descriptions": ["her posture relaxed as she gazes through the window", "the school uniform draping over her seated frame"], "composition_tags": ["from above", "depth of field"]}',
    '{"descriptions": ["a calm poise to her shoulders as she sits", "her uniform skirt fanning lightly over the chair"], "composition_tags": ["from side", "motion blur"]}',
)
_EXAMPLE_BANK_LIGHT = (
    '{"descriptions": ["late afternoon light washing across the quiet classroom", "a soft glow tracing the collar of her school uniform"], "composition_tags": ["depth of field", "backlighting"]}',
    '{"descriptions": ["warm window light pooling on the desk beside her", "her uniform catching the soft afternoon glow"], "composition_tags": ["from side", "dappled sunlight"]}',
    '{"descriptions": ["a hazy backlight outlining her as she gazes outside", "soft shadows settling across the quiet classroom"], "composition_tags": ["rim lighting", "depth of field"]}',
    '{"descriptions": ["a gentle sidelight grazing her school uniform", "the classroom bathed in calm diffused daylight"], "composition_tags": ["from above", "soft lighting"]}',
    '{"descriptions": ["dappled light scattering over the desk beside her", "her uniform softly lit as she sits by the window"], "composition_tags": ["from side", "dappled sunlight"]}',
)
# close-up 강화(emphasize_framing) 전용 — 본문이 카메라 샷/앵글을 명명하는 기존 사양 스타일.
_EXAMPLE_BANK_FRAMING = (
    '{"descriptions": ["a tight close-up framing her bared chest and pose", "a low angle accentuating the lifted shirt"], "composition_tags": ["close-up", "from below"]}',
    '{"descriptions": ["a low angle emphasizing her exposed body", "a close shot centered on her squeezed cleavage"], "composition_tags": ["from below", "close-up"]}',
    '{"descriptions": ["an intimate close framing of her bared skin", "a steep low angle over her pose"], "composition_tags": ["close-up", "dutch angle"]}',
)


def build_instruction(
    descriptive: list[str],
    rating: str,
    level_cfg: dict[str, Any],
    candidates: list[str],
    *,
    style_options: Optional[dict[str, bool]] = None,
    grounding: Optional[dict[str, Any]] = None,
    variety_seed: int = 0,
    emphasize_framing: bool = False,
) -> str:
    lo, hi = level_cfg.get("phrases", (2, 3))
    wlo, whi = level_cfg.get("words", (8, 16))
    tone = ", ".join(_TONE_PALETTE.get(rating, _TONE_PALETTE["s"]))
    focus = _RATING_FOCUS.get(rating, _RATING_FOCUS["s"])
    tags_line = ", ".join(descriptive[:60])
    style = _style_options(style_options)
    # '광원·색조 허용'(allow_light_style) OFF면 지시문 자체가 조명/톤을 권하지 않도록 한다
    # (긍정 지시·few-shot 예시가 부정 지시를 무력화하던 모순 제거). 입력에 이미 조명 태그가
    # 있으면 면제 — 구도 후보 게이트·설명문 필터와 동일 기준.
    light_ok = bool(style["allow_light_style"]) or _contains_style_source(descriptive, _LIGHT_STYLE_RE)

    # 접지 블록(코드가 만든 라벨:값) — 지시문 선두에 둬서 모델이 일반 분위기로 도망가지
    # 않고 *이* 장면의 구체 앵커를 프레이밍하게 한다. Priority는 명물(역할/소품/포즈) 우선.
    anchor_block = ""
    priority_line = ""
    central_act_line = ""
    if grounding:
        gtext = _format_grounding(grounding)
        if gtext:
            anchor_block = (
                "Concrete anchors to frame (build every phrase from these — introduce no nouns that "
                "are not listed here):\n" + gtext + "\n"
            )
        prio = grounding.get("priority") or []
        if prio:
            priority_line = "Priority anchors (frame these first): " + ", ".join(prio[:6]) + "\n"
        # 핵심 행위(q/e): 모델이 shirt lift/curve 같은 주변 앵커로 도망가지 않고 *무엇을 하는
        # 장면인지*를 반드시 명명·프레이밍하게 한다(Codex: 핵심 행위 단어를 1회 이상 그대로 포함).
        cacts = grounding.get("central_acts") or []
        if cacts and rating in ("q", "e"):
            central_act_line = (
                "Central act to frame: " + ", ".join(cacts[:4]) + "\n"
                "At least ONE phrase must include one of those central-act words verbatim and frame "
                "how the bodies and pose present that interaction — not only isolated "
                "body parts, clothing, or lighting.\n"
            )
        # q/s/e 공통: 모델이 'full body / her figure / curves of her body / smiling face' 같은
        # generic·표정-only로 도망가는 것을 막고, 위 priority의 *구체* distinctive 앵커(노출/의상/
        # 신체부위/포즈/각도)를 프레이밍하도록 강제한다. 앵커 선택은 priority(salience 자동)에
        # 위임 — 케이스별 손튜닝 불요(사용자: 앵커 주는 방식 자동화).
        if prio and rating in ("s", "q", "e"):
            central_act_line += (
                "Do NOT center any phrase on generic whole-body wording ('full body', 'her figure', "
                "'her form', 'her curves', 'her body', 'silhouette') or on an expression alone "
                "('smiling face', 'her smile'); every phrase must frame a SPECIFIC anchor listed above "
                "— a garment, a bared/exposed body part, or the pose (NOT a camera shot/angle).\n"
            )

    comp_clause = ""
    if candidates:
        cmax = int(level_cfg.get("comp_max", 2))
        comp_clause = (
            f"Composition: choose {min(1, cmax)}-{cmax} tags from THIS enum that strengthen the "
            f"framing/angle/shot for THIS exact scene (only from the list, invent none): "
            f"{', '.join(candidates)}. Use AT MOST ONE shot-distance tag (close-up, upper body, "
            f"portrait, cowboy shot, wide shot), and vary the camera angle/shot from scene to scene "
            f"— do not settle on one default framing.\n"
        )

    may_clause = (
        "You MAY add lighting, time-of-day, weather, shadow, or depth atmosphere even when untagged, "
        if light_ok else
        "You MAY add time-of-day, weather, or depth-of-field atmosphere even when untagged (but NOT "
        "lighting, glow, shadow, sunlight, or color/tone wording), "
    )
    style_clause = (
        "Grounding rules: every phrase must frame at least one concrete anchor above (its object, "
        "clothing, pose, role, body, or setting) — the nouns you write must come from the anchors. "
        + may_clause +
        "but add NO named concrete location or prop that is not listed above (no 'classroom', 'bed', "
        "'flower', 'window' unless it appears in the anchors). Never invent colors or eye colors: a "
        "color word is allowed only when that color appears in Existing tags, eye color only when an "
        "eye-color tag exists. "
    )
    if not style["allow_scent_style"]:
        style_clause += "Do not add scent, aroma, perfume, musk, jasmine, or incense unless tagged. "
    if not style["allow_material_style"]:
        style_clause += "Do not add new material or texture words unless tagged. "
    if not style["allow_light_style"]:
        style_clause += "Do not add new light, glow, haze, ray, flare, spotlight, or shadow details unless tagged. "
    style_clause += "\n"

    # close-up 강화 ON → 카메라 샷/앵글을 본문에서 명명 허용(기존 사양 스타일). OFF → 관심사
    # 분리(본문=신체/포즈/무드, 카메라=구도 태그). 단일 카메라 정책 라인으로 모순 없이 전환.
    framing_clause = (
        "Framing emphasis: you MAY name the camera shot or angle in the phrases (e.g. a close-up "
        "or a low angle) when it strengthens how the exposure is presented.\n"
        if emphasize_framing else
        "Do NOT name camera shots or angles in the phrases — the composition tags handle the camera.\n"
    )
    if emphasize_framing:
        example_bank = _EXAMPLE_BANK_FRAMING
    else:
        example_bank = _EXAMPLE_BANK_LIGHT if light_ok else _EXAMPLE_BANK_NOLIGHT
    # 예시 선택은 구도 회전과 *다른* 시드(상수 XOR)로 — 같은 variety_seed를 둘 다 쓰면
    # (후보 회전, 예시) 쌍이 매 장면 고정 정렬돼 같은 태그를 이중 prime할 수 있다(Codex B1).
    example_out = example_bank[(variety_seed ^ 0xA5A5) % len(example_bank)] if example_bank else "{}"

    return (
        "Task: add only atmosphere and composition (no new facts) to an existing anime image prompt.\n"
        + anchor_block
        + priority_line
        + central_act_line
        + f"Rating focus [{rating}]: {focus}\n"
        + f"Write {max(1, lo)}-{hi} short English phrases ({wlo}-{whi} words each): frame the anchors "
        + ("above with concrete lighting, mood and atmosphere, as the Rating focus directs.\n"
           if light_ok else
           "above with concrete pose, body detail and mood, as the Rating focus directs "
           "(no lighting/glow/shadow/color-tone).\n")
        + framing_clause
        + "Rules: (1) never add or change subjects, count, outfit, location, props, named series, "
        "artist, or style; (2) do not merely re-list the tags verbatim — frame and present what they "
        "depict; (3) if nothing fitting can be added, return empty arrays — never invent. English only.\n"
        + style_clause
        + f"Tone (secondary — atmosphere only, must never replace the anchors): {tone}.\n"
        + comp_clause +
        "Bad — never do: \"another girl walks in\", \"a bed in the background\" (unless a bed anchor "
        "exists), introducing any new character, prop, or location.\n"
        "Example anchors — Action/pose: sitting, looking out window | Clothing: school uniform | Setting: classroom, desk\n"
        + "Example output: " + example_out + "\n\n"
        + f"Existing tags (IMMUTABLE — never change, add to, or contradict): {tags_line}\n"
        "Output JSON:"
    )


def boost_schema(level_cfg: dict[str, Any], candidates: list[str]) -> dict[str, Any]:
    props: dict[str, Any] = {
        "descriptions": {
            "type": "array", "minItems": 0,
            "maxItems": int(level_cfg.get("phrases", (1, 3))[1]),
            "items": {"type": "string"},
        },
    }
    if candidates:
        props["composition_tags"] = {
            "type": "array", "minItems": 0,
            "maxItems": int(level_cfg.get("comp_max", 2)),
            "items": {"type": "string", "enum": list(candidates)},
        }
    return {"type": "object", "properties": props, "required": ["descriptions"]}


def normalize_level(level: Any) -> str:
    lv = str(level or "").strip().lower()
    return lv if lv in SCENE_BOOST_LEVELS else DEFAULT_LEVEL


# ---------------------------------------------------------------------------
# 6) 오케스트레이션 — 전 과정. 실패 시 원문 그대로 반환(원샷 계약: 재시도 없음).
# ---------------------------------------------------------------------------
def run_scene_boost(
    prompt: str,
    options: dict[str, Any],
    *,
    chat: Callable[..., dict[str, Any]],
    default_model: str,
    tag_rating: Callable[[str], str],
    validate_tag: Optional[Callable[[str], Optional[dict]]] = None,
    tag_allowed: Optional[Callable[[str, str], bool]] = None,
    is_sexual: Optional[Callable[[str], bool]] = None,
    is_hardcore: Optional[Callable[[str], bool]] = None,
    has_hangul: Optional[Callable[[str], bool]] = None,
    classify_axes: Optional[Callable[[str], frozenset[str]]] = None,
) -> dict[str, Any]:
    """Scene Boost 1회 실행. 원문은 verbatim 보존, 검증된 구도태그 + 필터링된 자연어만 덧붙인다."""
    options = options or {}
    original = str(prompt or "").strip()
    level = normalize_level(options.get("level"))
    lvl_cfg = SCENE_BOOST_LEVELS[level]

    if not original:
        return {"ok": False, "stage": "input", "error": "프롬프트가 비어 있습니다.",
                "prompt": "", "rating": "g", "level": level,
                "additions": {"composition_tags": [], "descriptions": []}}

    parsed = parse_prompt(original)
    descriptive = parsed["descriptive"]
    empty_add = {"composition_tags": [], "descriptions": []}
    if not descriptive:
        # 서술 태그 없음(저작권/가중치만) → 지어내지 않는다.
        return {"ok": True, "stage": "skip", "prompt": original, "rating": "g",
                "level": level, "additions": empty_add, "note": "no descriptive tags to boost"}

    rating = aggregate_rating(
        descriptive, tag_rating=tag_rating, is_sexual=is_sexual, is_hardcore=is_hardcore)
    # 톤/구도용 *유효* 등급: q/e인데 성적 신호(노출/행위)가 전혀 없으면(lying·on back 같은 자세
    # 태그만으로 올라간 SFW) s로 강등 — sultry/feverish 톤·moody 조명이 SFW에 새는 것 차단.
    # explicit(노출/행위 태그 존재)은 그대로 유지된다(tone drift 가드, Codex 검토).
    sexual_present = bool(
        (is_sexual and any(is_sexual(t) for t in descriptive))
        or (is_hardcore and is_hardcore(" ".join(descriptive).lower()))
    )
    tone_rating = "s" if (rating in ("q", "e") and not sexual_present) else rating
    style = _style_options(options)
    # '광원·색조 허용'(allow_light_style) OFF면 조명 구도 태그도 후보에서 제외한다.
    # 단, 입력 태그에 이미 조명 소스가 있으면 설명문 가드와 동일하게 면제(이미 그 장면의
    # 사실이므로 강조해도 환각 아님).
    allow_lighting = bool(style["allow_light_style"]) or _contains_style_source(
        descriptive, _LIGHT_STYLE_RE
    )
    # 장면 태그에서 안정 해시(PYTHONHASHSEED 무관) → 후보 enum 회전 시드. 장면마다 제시되는
    # 카메라 후보 선두/구성이 달라져, 광원 차단 후 close-up만 반복하던 고착을 분산한다.
    variety_seed = sum(ord(c) for c in "".join(descriptive))
    candidates = composition_candidates(
        tone_rating, parsed["existing_camera"], lvl_cfg,
        validate_tag=validate_tag, tag_allowed=tag_allowed,
        allow_lighting=allow_lighting, variety_seed=variety_seed)
    grounding = build_grounding(
        descriptive, classify_axes=classify_axes,
        existing_camera=parsed["existing_camera"], subject_count=parsed["subject_count"])

    instruction = build_instruction(
        descriptive, tone_rating, lvl_cfg, candidates, style_options=style, grounding=grounding,
        variety_seed=variety_seed, emphasize_framing=bool(options.get("emphasize_framing")))
    schema = boost_schema(lvl_cfg, candidates)
    try:
        out = chat(instruction, schema, model=default_model,
                   temperature=lvl_cfg["temperature"], num_predict=lvl_cfg.get("num_predict"))
    except Exception as exc:  # 원샷 계약 — 재시도 없이 원문 보존.
        return {"ok": False, "stage": "chat", "error": str(exc) or "scene boost 생성 실패",
                "prompt": original, "rating": rating, "level": level, "additions": empty_add}

    if not isinstance(out, dict):
        out = {}
    descs = filter_descriptions(
        out.get("descriptions") or [], parsed["all_words"], lvl_cfg,
        input_tags=descriptive, style_options=style, has_hangul=has_hangul,
        classify_axes=classify_axes)
    descs = _drop_if_all_generic(descs, grounding)
    comp = filter_composition(
        out.get("composition_tags") or [], candidates, parsed["existing_camera"], lvl_cfg)

    additions = comp + descs
    boosted = original
    if additions:
        boosted = original.rstrip(" ,") + ", " + ", ".join(additions)
    return {
        "ok": True, "stage": "done", "prompt": boosted, "rating": rating, "level": level,
        "additions": {"composition_tags": comp, "descriptions": descs},
        "grounding": grounding,
    }


__all__ = [
    "SCENE_BOOST_LEVELS", "DEFAULT_LEVEL", "normalize_level",
    "parse_prompt", "aggregate_rating", "composition_candidates",
    "build_grounding", "filter_descriptions", "filter_composition",
    "build_instruction", "boost_schema", "run_scene_boost",
]
