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


# ---------------------------------------------------------------------------
# 강도 레벨 — 문장 수·길이·구도태그 수·temperature를 한 손잡이로(_LEVELS 미러). 기본=rich.
# 풍부함은 "cinematic하게" 같은 모호한 지시가 아니라 개수/길이 캡으로 통제(Codex D).
# ---------------------------------------------------------------------------
SCENE_BOOST_LEVELS: dict[str, dict[str, Any]] = {
    "concise":  {"phrases": (1, 2), "words": (6, 12),  "comp_max": 1, "temperature": 0.25},
    "standard": {"phrases": (2, 3), "words": (8, 16),  "comp_max": 2, "temperature": 0.30},
    "rich":     {"phrases": (3, 4), "words": (10, 18), "comp_max": 3, "temperature": 0.32},
    "max":      {"phrases": (4, 6), "words": (12, 22), "comp_max": 4, "temperature": 0.35},
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

# 톤 팔레트 — *사실이 아닌 단어 힌트*(Codex E). LLM 묘사의 어조만 끌고, 명사/행위는 안 만든다.
_TONE_PALETTE: dict[str, tuple[str, ...]] = {
    "g": ("serene", "wholesome", "gentle", "bright", "innocent", "airy"),
    "s": ("warm", "inviting", "soft", "tender", "dreamy", "sun-kissed"),
    "q": ("sultry", "charged", "intimate", "flushed", "yearning", "hazy"),
    "e": ("intense", "feverish", "low-key", "raw", "breathless", "smouldering"),
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
) -> list[str]:
    """등급에 맞는 코드 큐레이션 구도/조명 태그 후보. LLM은 이 enum 안에서만 고른다."""
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

    prefer_list = [t for t, l in _COMPOSITION_POOL if l == prefer and _eligible(t)]
    any_list = [t for t, l in _COMPOSITION_POOL if l == "any" and _eligible(t)]
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
    has_hangul: Optional[Callable[[str], bool]] = None,
) -> list[str]:
    """LLM 자연어 묘사를 검열: 한글/길이초과/새 인물도입/태그에코/중복 제거."""
    _, word_hi = level_cfg.get("words", (6, 18))
    max_words = int(word_hi) + 4            # slack
    phrase_hi = int(level_cfg.get("phrases", (1, 3))[1])
    out: list[str] = []
    seen: set[str] = set()
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
        # 에코: 묘사의 내용어가 거의 다 입력 태그 단어면(순수 재진술) 버린다.
        content = [w.lower() for w in re.findall(r"[a-zA-Z']+", s) if w.lower() not in _STOPWORDS]
        if content:
            overlap = sum(1 for w in content if w in input_words)
            if overlap / len(content) >= 0.7:   # 거의 입력 태그의 재진술 → 분위기 0
                continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= phrase_hi:
            break
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
    for p in picks or []:
        t = str(p or "").strip().lower().replace("_", " ")
        if t not in allowed or t in used:
            continue
        if _CAMERA_CONTRADICTIONS.get(t) in used:
            continue                        # 이미 고른 것과 모순
        used.add(t)
        out.append(t)
        if len(out) >= cap:
            break
    return out


# ---------------------------------------------------------------------------
# 5) LLM 호출 — 지시문 + 스키마. 단일 few-shot, enum 제약, minItems 0(빈 출력 허용).
# ---------------------------------------------------------------------------
def build_instruction(
    descriptive: list[str],
    rating: str,
    level_cfg: dict[str, Any],
    candidates: list[str],
) -> str:
    lo, hi = level_cfg.get("phrases", (2, 3))
    wlo, whi = level_cfg.get("words", (8, 16))
    tone = ", ".join(_TONE_PALETTE.get(rating, _TONE_PALETTE["s"]))
    tags_line = ", ".join(descriptive[:60])
    comp_clause = ""
    if candidates:
        comp_clause = (
            f"Also pick {0}-{level_cfg.get('comp_max', 2)} camera/lighting tags from THIS list "
            f"that best fit the scene (choose only from the list, invent none): "
            f"{', '.join(candidates)}.\n"
        )
    return (
        "Task: enrich an existing anime image prompt by adding ATMOSPHERE ONLY. "
        "You are given the existing tags and a target mood. Do NOT change, repeat, or "
        "contradict the subjects, their count, outfit, pose, or action; invent no new "
        "characters, locations, props, or named series/artists.\n"
        f"Write {max(1, lo)}-{hi} short English scene-description phrases ({wlo}-{whi} words "
        f"each) evoking background, lighting and a {tone} mood — vivid and {tone}, but only "
        "what the existing tags already imply. English only. Do not introduce a new person. "
        "For explicit moods, keep it suggestive in TONE (intimate, low-key) — add no new "
        "sexual act or body part.\n"
        + comp_clause +
        "Example tags: 1girl, school uniform, classroom, sitting, looking out window\n"
        'Example output: {"descriptions": ["late afternoon light pooling across empty desks", '
        '"a hush of chalk dust drifting in the golden quiet"], "composition_tags": '
        '["depth of field", "backlighting"]}\n\n'
        f"Existing tags: {tags_line}\n"
        f"Target mood: {tone}\n"
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
    candidates = composition_candidates(
        rating, parsed["existing_camera"], lvl_cfg,
        validate_tag=validate_tag, tag_allowed=tag_allowed)

    instruction = build_instruction(descriptive, rating, lvl_cfg, candidates)
    schema = boost_schema(lvl_cfg, candidates)
    try:
        out = chat(instruction, schema, model=default_model, temperature=lvl_cfg["temperature"])
    except Exception as exc:  # 원샷 계약 — 재시도 없이 원문 보존.
        return {"ok": False, "stage": "chat", "error": str(exc) or "scene boost 생성 실패",
                "prompt": original, "rating": rating, "level": level, "additions": empty_add}

    if not isinstance(out, dict):
        out = {}
    descs = filter_descriptions(
        out.get("descriptions") or [], parsed["all_words"], lvl_cfg, has_hangul=has_hangul)
    comp = filter_composition(
        out.get("composition_tags") or [], candidates, parsed["existing_camera"], lvl_cfg)

    additions = comp + descs
    boosted = original
    if additions:
        boosted = original.rstrip(" ,") + ", " + ", ".join(additions)
    return {
        "ok": True, "stage": "done", "prompt": boosted, "rating": rating, "level": level,
        "additions": {"composition_tags": comp, "descriptions": descs},
    }


__all__ = [
    "SCENE_BOOST_LEVELS", "DEFAULT_LEVEL", "normalize_level",
    "parse_prompt", "aggregate_rating", "composition_candidates",
    "filter_descriptions", "filter_composition",
    "build_instruction", "boost_schema", "run_scene_boost",
]
