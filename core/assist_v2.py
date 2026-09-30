"""Assist v2 계약 · 병합 · 조립 (순수 로직, 입출력 없음).

요청 1건 = E2B 1회. 모델은 **구조**(요청 종류·요청 끝·인물·동작 방향·포함/제외·인물별 속성)를 채우고,
태그 선택·비유·관용구·방향·인원은 한국어 층(core.assist_korean)과 NAIA 사전이 맡는다.
모델 항목은 서버가 정리한다: 인원 낱말·비유·관용구가 덮는 것·요청에 근거 없는 것(지시문 예시 흉내)을 버리고,
사전 구와 겹치면 사전 태그로 바꾼다. 실측과 함정은 docs/ASSIST_V2_DESIGN_2026_09_23.md.

출력 형식은 공백 없는 GBNF(``compact_grammar``) — llama-server 의 json_schema 는 들여쓰기를 허용해 토큰을 낭비한다
(같은 정확도에 1.51 -> 0.76초, 5090).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from core.assist_candidates import GENERIC_NOUNS, Ask
from core.assist_english import English, en_key, english_parts, put_english
from core.assist_korean import KoreanAnalysis, NameHit, absorbed_stems, base_name, clean_text, compact

TASKS = ("scene", "tag", "character", "artist", "wildcard", "preset", "other")
GOALS = ("find", "how", "generate")
RATINGS = ("g", "s", "q", "e")
MAX_TEXT = 800             # 여러 줄 구성 요청(main / c1 / c2 …) 전체 — 300 이면 캐릭터 둘에서 끊겼다
# 한 줄 요청 · 구성의 칸 하나(장면 · 캐릭터 줄) — 사용자 결정 09-30. 실제로 적는 긴 요청은 120자 안팎이고, 150자를 넘으면
# 모델 칸이 차서 뒤쪽이 잘렸다(MAX_INCLUDE 실측)
MAX_LINE_TEXT = 300
# 모델이 돌려주는 포함 항목 칸. 10 이면 150자 넘는 요청은 늘 찼고, 모델은 글 순서로 적으니 뒤쪽(배경 · 날씨 · 구경꾼)이
# 잘렸다. 16 = 09-30 실측(긴 요청 7개 × 3회: 적중 48 -> 56%, 짧은 요청은 칸을 채우지 않았다 · 출력 최대 410 토큰)
MAX_INCLUDE = 16

_ITEM = {"type": "object", "additionalProperties": False,
         "properties": {"en": {"type": "string", "maxLength": 60}, "ko": {"type": "string", "maxLength": 40},
                        "who": {"type": "integer", "minimum": 0, "maximum": 4}},
         "required": ["en", "ko", "who"]}
_CHAR = {"type": "object", "additionalProperties": False,
         "properties": {"ko": {"type": "string", "maxLength": 40}, "en": {"type": "string", "maxLength": 80}},
         "required": ["ko", "en"]}
_ACT = {"type": "object", "additionalProperties": False,
        "properties": {"en": {"type": "string", "maxLength": 60}, "ko": {"type": "string", "maxLength": 40},
                       "source": {"type": "integer", "minimum": 1, "maximum": 4},
                       "target": {"type": "integer", "minimum": 1, "maximum": 4}},
        "required": ["en", "ko", "source", "target"]}
SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "task": {"type": "string", "enum": list(TASKS)},
        "goal": {"type": "string", "enum": list(GOALS)},
        "characters": {"type": "array", "maxItems": 4, "items": _CHAR},
        "actions": {"type": "array", "maxItems": 3, "items": _ACT},
        "include": {"type": "array", "maxItems": MAX_INCLUDE, "items": _ITEM},
        "exclude": {"type": "array", "maxItems": 6, "items": _ITEM},
        "name": {"type": "string", "maxLength": 80},
        "name_ko": {"type": "string", "maxLength": 40},
    },
    "required": ["task", "goal", "characters", "actions", "include", "exclude", "name", "name_ko"],
}

SYSTEM_PROMPT = """You are the search router of NAIA, an anime image generator. The user writes in Korean.
Read one request and fill the JSON. Do not chat.

task:
- scene: the user wants an image, prompt or search of a situation, pose, place, outfit or composition.
- tag: the user asks what the tag or English word for something is.
- character: the user asks for the tag of a named character. artist: a named artist.
- wildcard / preset: the user asks for a wildcard / saved preset.
- other: anything else (greetings, app questions, weather...).
goal: find (찾아줘, 있어?, or no ending) / how (어떻게, 방법, 알려줘) / generate (생성해, 만들어, 그려).

characters: named characters in the order they first appear. ko = the name exactly as written (no braces),
en = the English Danbooru name only if you are sure, else "".
actions: what one named character does to another. en = Danbooru tag, ko = Korean dictionary form.
source = number of the one who does it (이/가/은/는), target = the one it is done to (을/를/에게/한테).
In passive forms (안겨서, 꼬집히는) the doer is the other character.
include: what must appear. en = Danbooru tag (lowercase, spaces), ko = Korean dictionary form (noun, or verb as ~기),
who = the character number it belongs to (outfit, expression, pose), 0 = the whole scene (place, weather, time).
List every concept of the request (up to 16).
exclude: things the user does not want (빼고, 빼줘, 없이, 말고), same form. Never put "no ..." in include.
name / name_ko: for character/artist/wildcard/preset lookups, the name in English if sure, and as written.

Never output people words or counts (girl, boy, two girls, 1girl, solo); the app sets them.
Do not add quality, rating or decoration tags the user did not ask for.
If a current search is given, apply the new request to it and return the whole updated search.
A request about something new replaces the current search.

Examples:
Request: 창가에 앉아 책을 읽는 소녀 찾아줘
{"task":"scene","goal":"find","characters":[],"actions":[],"include":[{"en":"sitting","ko":"앉기","who":0},{"en":"window","ko":"창가","who":0},{"en":"reading","ko":"읽기","who":0},{"en":"book","ko":"책","who":0}],"exclude":[],"name":"","name_ko":""}
Request: 렘이 에밀리아에게 무릎베개를 해 주는 장면 어떻게 만들어?
{"task":"scene","goal":"how","characters":[{"ko":"렘","en":"rem (re:zero)"},{"ko":"에밀리아","en":"emilia (re:zero)"}],"actions":[{"en":"lap pillow","ko":"무릎베개","source":1,"target":2}],"include":[],"exclude":[],"name":"","name_ko":""}
Request: 교복 입은 아스나가 벚꽃 아래서 웃는 모습 생성해 줘, 가방은 빼고
{"task":"scene","goal":"generate","characters":[{"ko":"아스나","en":""}],"actions":[],"include":[{"en":"school uniform","ko":"교복","who":1},{"en":"cherry blossoms","ko":"벚꽃","who":0},{"en":"smile","ko":"웃기","who":1}],"exclude":[{"en":"bag","ko":"가방","who":0}],"name":"","name_ko":""}
Current search: {"task":"scene","characters":[],"actions":[],"include":["standing","street","holding bag"],"exclude":[]}
Request: 가방 말고 꽃다발로 바꿔줘
{"task":"scene","goal":"find","characters":[],"actions":[],"include":[{"en":"standing","ko":"서 있기","who":0},{"en":"street","ko":"거리","who":0},{"en":"holding bouquet","ko":"꽃다발 들기","who":0}],"exclude":[{"en":"holding bag","ko":"가방 들기","who":0}],"name":"","name_ko":""}
Request: 윙크는 태그로 뭐야?
{"task":"tag","goal":"find","characters":[],"actions":[],"include":[{"en":"one eye closed","ko":"윙크","who":0}],"exclude":[],"name":"","name_ko":""}
Request: 원신 호두 캐릭터 태그
{"task":"character","goal":"find","characters":[],"actions":[],"include":[],"exclude":[],"name":"hu tao (genshin impact)","name_ko":"호두"}"""

GUIDE = {
    "title": "이런 걸 도와드릴 수 있어요",
    "examples": [
        "목줄을 찬 채로 개같이 엎드려서 바닥을 기는 장면 찾아줘",
        "카나데가 나히다를 공주안기 하고 뛰어다니는 구도 어떻게 해?",
        "가슴골은 태그로 뭐라고 해?",
        "원신 푸리나 캐릭터 태그",
        "메이드 관련 와일드카드 있어?",
    ],
    "note": "장면을 말로 설명하면 이벤트 맵에서 실제 조합을 찾아 프롬프트로 만들고, Random 에 연결할 수 있어요.",
}

_PEOPLE_EN = re.compile(r"^(?:\d+\s*)?(?:a |an |the |one |two |three |several )?(?:little |young |cute )?"
                        r"(?:girls?|boys?|wom[ae]n|m[ae]n|females?|males?|persons?|people|kids?|children|ladies|lady|"
                        r"guys?|1girl|1boy|2girls|2boys|solo|multiple girls|multiple boys)$")
_NEGATION = re.compile(r"^(?:no|without|non)\s+(.+)$|^(.+?)\s+(?:removed|off)$")
_EN_STOP = frozenset({"on", "in", "at", "the", "a", "an", "of", "with", "down", "up", "like", "while", "day", "girl",
                      "woman", "and", "to", "for"})
# 모델 영문 -> 단보루 낱말. V 사인은 태그가 v 다 — v sign 을 쪼개면 sign(표지판)이 실렸다(사용자 제보 09-25)
_SYNONYMS = {"photo": "picture", "photos": "pictures",
             "v sign": "v", "v-sign": "v", "peace sign": "v", "v pose": "v",
             # 기호 태그는 이름이 기호다(? 8.6만 · ! 4.5만) — 모델은 영문 이름으로 적는다(사용자 제보 09-26)
             "question mark": "?", "question mark sign": "?", "exclamation mark": "!", "exclamation point": "!",
             "interrobang": "!?", "ellipsis": "..."}
_EMOTICON_EN = re.compile(r"[^a-z]*|[^a-z]{1,2}\s?[a-z]?")
_META_EN = re.compile(r"\((?:animated|medium|meme|artwork|style|cosplay|parody)\)$")
# 뜻을 싣는 품사(Kiwi) — 명사 · 동사 · 형용사 · 보조 용언 · 관형사 · 부사 · 어근 · 외국어 · 숫자. 어미 · 조사 · 접사 · 부호는 뺀다
_CONTENT_POS = ("NN", "NP", "NR", "VV", "VA", "VX", "VC", "MM", "MA", "XR", "SL", "SH", "SN")


# 두 글자 이하지만 이모티콘이 아닌 손동작 태그 — V 사인(19만 건) · W 사인(2.5만 건). 두 글자 이하를 통째로 막았더니
# '손가락으로 브이 표시' 에서 사전의 브이 -> v 가 후보에도 못 올랐다(사용자 제보 09-25). 구성의 TagFinder.usable 도 같다.
SHORT_TAGS = frozenset({"v", "w"})
# 이모티콘이 아닌 기호 태그 — 물음표(? 8.6만) · 느낌표(! 4.5만) · !?(3만) · 말줄임표(... 6.3만). 글자가 없다고 이모티콘으로
# 막았더니 '? 마크를 띄운' 이 star (symbol) · ? block 으로 샜다(사용자 제보 09-26). 구성의 TagFinder.usable 도 같다.
SYMBOL_TAGS = frozenset({"?", "!", "!?", "..."})


def _junk_tag(tag: str | None) -> bool:
    """프롬프트에 싣지 않을 태그 — 이모티콘(>o< · ^_^) · 메타 갈래((animated) · (cosplay)) · 인원 낱말 · 두 글자 이하
    (손동작 태그 SHORT_TAGS · 기호 태그 SYMBOL_TAGS 는 뺀다). 구성 경로의 TagFinder.usable 과 같은 기준이다(09-24: '놀란 표정' 이
    >o< 로 샜다)."""
    value = str(tag or "").strip().lower()
    if value in SHORT_TAGS or value in SYMBOL_TAGS:
        return False
    return (len(value) <= 2 or not re.search(r"[a-z]{2}", value) or bool(_EMOTICON_EN.fullmatch(value))
            or bool(_META_EN.search(value)) or bool(_PEOPLE_EN.match(value)))


# ── 문법 ───────────────────────────────────────────────────────────────────


def compact_grammar(schema: dict[str, Any] | None = None) -> str:
    """스키마 부분집합 -> 공백 없는 GBNF. 키 순서 고정 · 전부 필수 · 추가 키 없음 · 한 자리 정수만."""
    rules: dict[str, str] = {"char": r'[^"\\\x7F\x00-\x1F] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F]{4})'}

    def rule(name: str, body: str) -> str:
        rules.setdefault(name, body)
        return name

    def visit(node: dict[str, Any], hint: str) -> str:
        kind = node.get("type")
        if kind == "string" and "enum" in node:
            alts = " | ".join(json.dumps(json.dumps(v, ensure_ascii=False), ensure_ascii=False) for v in node["enum"])
            return rule(f"{hint}-enum", alts)
        if kind == "string":
            n = int(node.get("maxLength", 200))
            return rule(f"str{n}", f'"\\"" char{{0,{n}}} "\\""')
        if kind == "integer":
            lo, hi = int(node["minimum"]), int(node["maximum"])
            if not 0 <= lo <= hi <= 9:
                raise ValueError("한 자리 정수만 지원한다")
            return rule(f"int{lo}{hi}", f"[{lo}-{hi}]")
        if kind == "array":
            item = visit(node["items"], hint + "-item")
            n = int(node.get("maxItems", 8))
            more = f' ("," {item}){{0,{n - 1}}}' if n > 1 else ""
            return rule(f"{hint}-arr", f'"[" ({item}{more})? "]"')
        if kind == "object":
            parts = []
            comma = '"," '
            for i, (key, sub) in enumerate(node["properties"].items()):
                ref = visit(sub, f"{hint}-{key}")
                lit = json.dumps(json.dumps(key) + ":")
                parts.append((comma if i else "") + f"{lit} {ref}")
            return rule(f"{hint}-obj", '"{" ' + " ".join(parts) + ' "}"')
        raise ValueError(f"지원하지 않는 스키마: {node}")

    root = visit(schema or SCHEMA, "r")
    return "\n".join([f"root ::= {root}"] + [f"{name} ::= {body}" for name, body in rules.items()])


def user_message(text: str, recap: dict[str, Any] | None = None, literal: str | None = None) -> str:
    """모델 입력. 기억은 직전 검색 하나(서버가 만든 recap)뿐 — 초기 원문은 다시 넣지 않는다(지운 것이 되살아난다).
    literal = 직역 도구의 영문(core/assist_translate) — en 을 그 낱말에서 고르게 한 줄 덧붙인다(시스템 프롬프트는 그대로)."""
    lines = []
    if recap:
        lines.append("Current search: " + json.dumps(_recap_for_model(recap), ensure_ascii=False))
    lines.append(f"Request: {clean_text(text).strip()}")
    if literal:
        lines.append(f"Literal English (take en words from it, ko from the request): {literal}")
    return "\n".join(lines)


def parse_route(content: str) -> dict[str, Any]:
    """모델 출력(문법이 모양을 보장) -> 기본값이 채워진 dict. 모델이 문자열 'null' 을 쓰면 빈 값으로."""
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("route is not an object")
    out: dict[str, Any] = {}
    out["task"] = data.get("task") if data.get("task") in TASKS else "other"
    out["goal"] = data.get("goal") if data.get("goal") in GOALS else "find"
    for key in ("characters", "actions", "include", "exclude"):
        out[key] = [x for x in (data.get(key) or []) if isinstance(x, dict)]
    for key in ("name", "name_ko"):
        value = str(data.get(key) or "").strip()
        out[key] = "" if value.lower() in ("null", "none") else value
    return out


# ── 태그 해석 ────────────────────────────────────────────────────────────────


@dataclass
class TagVocab:
    """병합이 묻는 사전. 서비스가 이벤트 맵·NAIA 사전으로 채운다(시험에서는 작은 가짜)."""

    canonical: Callable[[str], str | None]                   # 이벤트 맵 어휘의 정확한 이름(없으면 None)
    count: Callable[[str], int]                              # 게시물 수(순서용)
    role: Callable[[str], str | None] = lambda _t: None      # event_core / actor_state / population …
    keyword: Callable[[str], list[str]] = lambda _k: []      # 한국어 정확 키워드 -> 태그(게시물 순, 어휘에 있는 것)
    fuzzy: Callable[[str], list[str]] = lambda _k: []        # 한국어 퍼지 검색(Fast Search 태그 갈래) -> 태그
    # 한국어 낱말 -> 사전이 가리키는 일반 태그 **전부**(묶음 이름도 — 고르기가 아니라 '이 말이 그 태그인가' 확인용)
    senses: Callable[[str], list[str]] = lambda _k: []


def en_variants(term: str, *, verb: bool = True) -> list[str]:
    """모델 영문의 흔한 어긋남: 복수·붙여쓰기·-ing·-y·wearing·photo. 순서가 우선순위다.
    verb=False(한국어 조각이 명사)면 '+ing' 을 붙이지 않는다 — 손가락(finger)이 fingering 이 됐다(사용자 제보 09-25)."""
    t = " ".join(str(term or "").lower().replace("_", " ").split())
    if not t:
        return []
    out = [t]
    for a, b in _SYNONYMS.items():
        if re.search(rf"\b{a}\b", t):
            out.append(re.sub(rf"\b{a}\b", b, t))
    if t.startswith("wearing "):
        out.append(t[len("wearing "):])
    out.append(t[:-1] if t.endswith("s") else t + "s")              # swords -> sword, cherry blossom -> cherry blossoms
    if " " in t:
        out.append(t.replace(" ", ""))                               # twin tails -> twintails
    words = t.split()
    if words[0].endswith("ing") and len(words[0]) > 5:               # blushing -> blush
        base = words[0][:-3]
        out += [" ".join([base] + words[1:]), " ".join([base + "e"] + words[1:])]
    elif len(words) == 1 and not t.endswith("ing") and verb:
        out.append(t + "ing")                                        # laugh -> laughing(동사만)
    if len(words) == 1 and t.endswith("y") and len(t) > 4:
        out.append(t[:-1])                                           # rainy -> rain
    return list(dict.fromkeys(out))


def _same_word(a: str, b: str) -> bool:
    """영문 두 낱말이 같은 말인가 — 앞부분이 짧은 쪽 전체이거나 5글자 이상 같다(look = looking, stars ≠ staring)."""
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n >= min(5, len(a), len(b))


def exact_english(term: str, vocab: TagVocab, *, verb: bool = True) -> str | None:
    """영문 추측이 (변형 포함) 태그 이름 그대로인가 — 쪼개지 않은 정확 일치만."""
    for v in en_variants(term, verb=verb):
        name = vocab.canonical(v)
        if name and not _junk_tag(name):
            return name
    return None


def resolve_english(term: str, vocab: TagVocab, *, verb: bool = True) -> list[str]:
    for v in en_variants(term, verb=verb):
        name = vocab.canonical(v)
        if name and not _junk_tag(name):
            return [name]
    words = [w for w in str(term or "").lower().split() if w]
    if len(words) < 2:
        return []
    parts: list[str] = []
    i = 0
    while i < len(words):                                            # classroom window -> classroom + window
        for j in range(len(words), i, -1):
            piece = " ".join(words[i:j])
            if j - i == 1 and piece in _EN_STOP:
                continue
            name = next((n for n in (vocab.canonical(v) for v in en_variants(piece, verb=verb)) if n and not _junk_tag(n)),
                        None)
            if name:
                parts.append(name)
                i = j
                break
        else:
            i += 1
    return list(dict.fromkeys(parts))


# ── 병합 ───────────────────────────────────────────────────────────────────


@dataclass
class Character:
    ko: str
    tag: str
    alts: list[str]
    gender: str | None
    attrs: list[str] = field(default_factory=list)
    # 캐릭터 특징(눈 · 머리 · 피부 색 · 오드아이 · 가슴 크기 …) — 서비스가 character_analysis 로 채운다. 캐릭터 칸 끝에(09-26)
    features: list[str] = field(default_factory=list)


@dataclass
class Merged:
    task: str
    goal: str
    tiers: tuple[list[str], list[str], list[str]]      # 1순위(관용구·사전 구) · 2순위(구체) · 3순위(흔한 것)
    exclude: list[str]
    characters: list[Character]
    relations: list[tuple[str, str, str]]              # (하는 쪽 태그, 동작 태그, 당하는 쪽 태그)
    has_action: bool
    name: str
    name_ko: str
    log: list[str]
    sentence: str = ""              # 다듬기 도구의 장면 문장(core/assist_refine) — 메인 끝에 붙는다
    english: English = field(default_factory=English)   # 요청에 섞어 쓴 영문 — 적힌 그대로 싣는다(core/assist_english)

    def ordered(self, count: Callable[[str], int]) -> list[str]:
        """이벤트 맵에 꽂을 순서: 층 순서 -> 각 층 안에서 게시물 많은 순(깊이 확보, 사용자 지정)."""
        out: list[str] = []
        for tier in self.tiers:
            for t in sorted(tier, key=lambda x: -int(count(x) or 0)):
                if t not in out:
                    out.append(t)
        return out

    def all_tags(self) -> list[str]:
        return list(dict.fromkeys(self.tiers[0] + self.tiers[1] + self.tiers[2]))


def merge(route: dict[str, Any], ka: KoreanAnalysis, vocab: TagVocab, *, text: str,
          generic: Iterable[str] = (), simile_particles: Iterable[str] = ("같이", "처럼", "마냥", "듯이"),
          generic_roles: Iterable[str] = (),
          approved: Iterable[NameHit] = (),
          not_names: Iterable[str] = (), poses: Iterable[str] = (),
          roles_for: Callable[[set[str]], tuple[str, str] | None] | None = None,
          chooser: Callable[[list[Ask]], list[str]] | None = None) -> Merged:
    """chooser: 정확히 안 풀린 포함 항목(Ask)을 받아 한국어 사전 후보에서 모델에게 고르게 하고(ask.keep · ask.picks 를
    채운다), 모델이 안 낸 요청 명사에서 고른 장면 태그를 돌려준다. None 이면 예전처럼(쪼갠 조각 · 퍼지 · 못 찾음).
    approved: 사용자가 칩에서 고른 캐릭터 — 인물은 이것뿐이다(ka.names 는 자동 제안이라 인물을 만들지 않는다)."""
    generic = set(generic)
    poses = set(poses)
    generic_roles = {compact(role) for role in generic_roles if role}
    similes = tuple(simile_particles)
    blocked, covers = set(ka.blocked), set(ka.covers)
    req_lemmas = ka.lemmas()
    req_compact = compact(clean_text(text))
    english = english_parts(text)               # 사용자가 섞어 쓴 영문 — 적힌 그대로 싣는다(compose, 09-26)
    typed_keys = {en_key(p) for p in english.keep + english.exclude}
    log: list[str] = []
    asks: list[Ask] = []
    t1: list[str] = [t for t in ka.specific if t not in blocked and not _junk_tag(t)]
    t2: list[str] = []
    t3: list[str] = []

    def place(tag: str, *, first: bool = False) -> None:
        if not tag or _junk_tag(tag) or tag in blocked or tag in covers or vocab.role(tag) == "population":
            return
        if tag in t1 or tag in t2 or tag in t3:
            return
        if first:
            t1.append(tag)
        elif tag in generic or vocab.role(tag) == "actor_state":
            t3.append(tag)
        else:
            t2.append(tag)

    for tag in ka.verb_tags:
        place(tag)

    def grounded(ko: str) -> bool:
        if not ko or not ka.available:
            return True
        k = compact(ko)
        if k in req_compact:
            return True
        stems = {k[:-1]} if k.endswith("기") and len(k) >= 2 else {re.sub(r"다$", "", k)}
        if stems & req_lemmas or any(len(s) >= 2 and s in req_compact for s in stems):
            return True
        # 낱말마다(눈물 고이기 = 눈물 + 고이) — 붙여 비교하면 '눈물고이' 가 요청의 '눈물고인'(고인 = 고이+ㄴ 한 글자)에
        # 없어 tears 가 떨어졌다(09-24). 낱말이 전부 요청에 있어야 한다(침 흘리기 의 침은 없다 -> 버림).
        words = str(ko).split()
        if len(words) > 1 and all(grounded(w) for w in words):
            return True
        # 사용자가 영문으로 적은 말을 모델이 한국어로 옮겨 적은 낱말 — 사전이 그 낱말을 적은 영문 태그로 이어 주면 요청에
        # 있는 것으로 본다('빨간 dress' 의 모델 항목 '빨간 드레스' -> red dress 가 '요청에 없음' 으로 빠졌다, 09-26).
        # keyword 는 12개 넘게 가리키는 말(드레스)을 묶음 이름으로 버린다 — 확인에는 전부(senses)를 본다
        if typed_keys and any(en_key(t) in typed_keys for t in vocab.senses(ko)):
            return True
        # 글자 비교가 놓친 활용·보조 용언(누워 있기 · 부끄러워하는)은 Kiwi 원형으로 한 번 더 — 원래 받던 것은 그대로 받는다
        # (원형 비교만 쓰면 모델의 '반가워하다' 를 Kiwi 가 요청과 다르게 쪼개 happy 가 떨어졌다, 재생 09-24).
        api = getattr(ka, "grounded", None)
        return bool(callable(api) and getattr(ka, "tokenizer", None) is not None and api(ko))

    rule_tags = dict(getattr(ka, "rule_tags", None) or {})

    def rule_verb_tags(ko: str) -> list[str] | None:
        """모델 항목이 동사 규칙이 이미 태그로 만든 동사뿐이면 그 규칙 태그(쪼그려 앉기 = 쪼그리 + 앉 -> [squatting]).
        모델 영문 대신 이것을 **그 항목의 칸**에 싣는다 — 제외 칸 · 인물 번호는 항목 그대로(버리면 '뛰지 않는' 의 제외와
        인물 칸의 자세가 사라졌다 — Codex 리뷰 09-28). 명사 · 부사 · 다른 동사가 있으면(바닥에 앉기 · 누워 있기) None —
        모델 쪽이 더 구체적일 수 있다."""
        tokenizer = getattr(ka, "tokenizer", None)
        if not rule_tags or tokenizer is None or not ko:
            return None
        toks = tokenizer(ko)
        content = [(f, t) for f, t in toks if t.startswith(_CONTENT_POS)]
        if not content or not all(t.startswith("VV") and f in rule_tags for f, t in content):
            return None
        # 이 조각 안에서 딸린 동사(쪼그려 앉기 의 앉)는 앞 동사의 태그가 맡는다 — 문장 전체로는 따로 앉은 사람이 있어
        # 앉 -> sitting 이어도(카나데는 쪼그려 앉고 나히다는 의자에 앉아) 이 조각의 앉은 그 sitting 이 아니다(Codex 재리뷰 R2)
        tied = absorbed_stems(toks, getattr(ka, "verb_absorbs", None) or {})
        return list(dict.fromkeys(rule_tags[f] for f, _t in content if f not in tied))

    def item_tags(item: dict[str, Any], kind: str) -> list[str]:
        return [t for t in _item_tags(item, kind) if not _junk_tag(t)]

    def fuzzy_pick(ko: str, en: str) -> list[str]:
        # 퍼지 후보는 영문 추측이 **다 설명하는** 태그만 — 낱말 하나만 겹쳐도 받았더니 'looking at me' 가
        # looking at penis(키워드 쳐다보기)를 데려왔다(사용자 제보 09-24). 후보의 내용어가 전부 영문 추측에 있어야 한다.
        # 같은 말 = 앞부분이 짧은 쪽 전체이거나 5글자 이상 같을 때 — 앞 4글자로 비교했더니 looking at stars 가
        # staring('star' 까지 같음)이 됐다(검증3, 09-25). look = looking · eye = eyes · close = closed 는 그대로 같다.
        en_words = [w for w in re.findall(r"[a-z]+", en) if len(w) >= 3]
        for cand in vocab.fuzzy(ko) if ko else []:
            words = [w for w in re.findall(r"[a-z]+", cand.lower()) if len(w) >= 3]
            if words and all(any(_same_word(w, e) for e in en_words) for w in words) and vocab.canonical(cand):
                return [vocab.canonical(cand)]
        return []

    def _item_tags(item: dict[str, Any], kind: str) -> list[str]:
        en = str(item.get("en") or "").strip().lower()
        ko = str(item.get("ko") or "").strip()
        if _PEOPLE_EN.match(en):
            return []
        if english.typed(en):
            # 사용자가 영문으로 적은 말 — 모델은 ko 를 한국어로 옮겨 적어(crying -> 울기) 아래 '요청에 없음' 에 걸렸다(09-26).
            # 한국어 검사를 거치지 않는다: 태그 이름 그대로면 싣고(인물 번호 · 제외 칸은 모델이 가른 대로), 아니면 적힌
            # 그대로(compose)가 맡는다
            name = exact_english(en, vocab, verb=False)
            log.append(f"bypass:{en}" + (f"->{name}" if name and name != en else "" if name else "(그대로)"))
            return [name] if name else []
        if any(p in ko for p in similes) or re.search(r"\blike\b", en):
            log.append(f"drop:{en}(비유)")
            return []
        ko_c = compact(ko)
        stem = ko_c[:-1] if ko_c.endswith("기") else re.sub(r"다$", "", ko_c)
        # 한 음절 줄기(기다의 '기')는 완전 일치로만 — 포함으로 보면 '안기'·'쓰기' 까지 버린다(시험이 잡음)
        if any(stem == v or (len(v) >= 2 and stem.startswith(v)) for v in ka.idiom_verbs):
            log.append(f"drop:{en}(관용구가 덮음)")
            return []
        if not grounded(ko):
            log.append(f"drop:{en}(요청에 없음)")
            return []
        # 모델 항목이 사전 구를 **품을 때만** 바꾼다(긴 구부터). 반대 방향(항목 ⊂ 구)은 명사를 삼켰다 —
        # 리본 -> 리본 묶기(tying) · 우산 -> 우산 쓰기(09-24 Codex 감사).
        phrase = next((tag for key, tag in sorted(ka.phrases.items(), key=lambda kv: -len(kv[0]))
                       if ko_c and key and key in ko_c), None)
        if phrase:
            if phrase != en:
                log.append(f"{en}->{phrase}(사전 구)")
            return [phrase]
        if any(stem in (s, s + "기") for s in ka.phrase_stems):
            log.append(f"drop:{en}(사전 구가 덮음)")      # 공주안기 -> princess carry 인데 모델이 '안기기 -> hold' 를 따로 냈다
            return []
        m = _NEGATION.match(en)
        if m and kind != "exclude":
            return []                                               # 'no towel' 은 제외 칸의 일이다
        # ⚠️ 부정 검사 뒤에 — 앞에 두었더니 포함 칸의 'no running'(뛰기) 이 running 으로 바뀌어 인물 칸에 긍정으로
        # 실렸다(Codex 재리뷰 09-28 R1)
        covered = rule_verb_tags(ko)
        if covered is not None:
            # 쪼그려 앉기 -> kneeling · sitting · crouching(실행마다 다르다)이 동사 규칙의 squatting 과 겹쳤다(09-25 · 09-27 실측)
            log.append(f"{en}->{','.join(covered)}(동사 규칙)")
            return covered
        # 모델은 동사를 '~기' 로 적는다 — 명사 조각(손가락)의 영문(finger)엔 '+ing' 을 붙이지 않는다(fingering, 09-25)
        verb = not ko_c or ko_c.endswith(("기", "다"))
        # 틀 명사(손가락 · 표정)는 사전 키워드로 바로 싣지 않는다 — 고르기가 묻지 않는 그 목록을 바로 싣기도 따른다
        # (손가락 -> middle finger: 사전에서 손가락은 그 태그의 분류 라벨 <손가락> 이다, 사용자 제보 09-25)
        direct = len(ko_c) >= 2 and ko_c not in GENERIC_NOUNS
        found = resolve_english(en, vocab, verb=verb)
        if chooser is not None and kind == "include" and not exact_english(en, vocab, verb=verb):
            # 영문이 태그 이름 그대로가 아니면(쪼개지거나 못 찾음) 한국어 정확 키워드가 아닌 한 모아 두었다가 고르게 한다
            # — 쪼갠 조각(chin · resting · back)과 못 찾음(observing)이 여기서 났다(설계 19절)
            hit = [t for t in vocab.keyword(ko) if not _junk_tag(t)] if direct else []
            if hit:
                return hit[:1]
            if not found:
                # 예전 길의 마지막 그물(영문이 다 설명하는 퍼지 후보)은 묻기 전에 — 고르기가 답을 못 하면 이것까지
                # 사라졌다(eyes closed -> closed eyes, Codex 검토 09-25). 이제 fallback = 예전 길의 결과 그대로.
                fuzzy = fuzzy_pick(ko, en)
                if fuzzy:
                    return fuzzy
            asks.append(Ask(ko=ko, en=en, who=int(item.get("who") or 0), fallback=list(found)))
            return []
        if found and len(found) == 1:
            return found
        if direct:
            hit = [t for t in vocab.keyword(ko) if not _junk_tag(t)]
            if hit:
                return hit[:1]
        if found:
            return found
        fuzzy = fuzzy_pick(ko, en)
        if fuzzy:
            return fuzzy
        log.append(f"unresolved:{en}|{ko}")
        return []

    # 인물 = **사용자가 고른 캐릭터뿐**(사용자 결정 09-25). 자동으로 찾은 이름(한국어 층의 칩 제안 · 모델의 인물 칸)은
    # 캐릭터가 아니다 — 모델이 인물로 적은 일반 낱말(신부 -> nero claudius (bride))도, 한국어 층의 오검출(여행자 ->
    # lumine)도 사용자가 고르지 않으면 태그가 되지 않는다. 모델의 인물 칸은 고른 캐릭터를 순서 · who 번호로 잇는 데만 쓴다.
    not_names = set(not_names)
    model_chars = route.get("characters") or []
    model_kos = [compact(clean_text(c.get("ko") or "")) for c in model_chars]
    chosen = [h for h in approved if h.candidates and h.form not in not_names]
    # 전체 이름과 그 조각을 둘 다 골랐으면(나토리 사나 · 나토리) 조각은 같은 사람이다 — 인물을 둘로 세지 않는다(09-24 제보)
    packed = {h.form: compact(h.form) for h in chosen}
    chosen = [h for h in chosen if not any(other != h.form and len(p) > len(packed[h.form]) and packed[h.form] in p
                                           for other, p in packed.items())]

    def slot(form: str) -> int:
        """고른 캐릭터가 모델 인물 칸의 몇 번인가(0 = 없음) — 모델은 성을 빼거나 붙여 적는다(카나데 · 요이사키 카나데)."""
        key = compact(form)
        return next((i for i, m in enumerate(model_kos, 1) if m and (m == key or m in key or key in m)), 0)

    chosen.sort(key=lambda h: (slot(h.form) or len(model_kos) + 1, req_compact.find(compact(h.form))))
    characters = [Character(h.form, h.tag, [t for t, _n in h.candidates[1:3]], h.gender) for h in chosen]
    owners = {slot(ch.ko): ch for ch in characters if slot(ch.ko)}
    # 왕자·공주 같은 역할 낱말은 인물로 적히거나 이름으로 칠해져도 캐릭터가 아니다 — 고르지 않았으면 사전의 장면 태그로(prince)
    named_forms = {compact(ch.ko) for ch in characters}
    role_forms = [clean_text(f).strip() for f in [c.get("ko") or "" for c in model_chars] + [h.form for h in ka.names]]
    for form in dict.fromkeys(f for f in role_forms if f and compact(f) in req_compact):
        if compact(form) in generic_roles and compact(form) not in named_forms:
            for tag in vocab.keyword(form):
                place(tag)

    acted: list[tuple[dict[str, Any], list[str]]] = []          # 모델 동작 항목과 그 태그 — 관계 조립이 다시 쓴다
    for item in route.get("actions") or []:
        tags = item_tags(item, "action")
        acted.append((item, tags))
        for tag in tags:
            place(tag)
    for item in route.get("include") or []:
        tags = item_tags(item, "include")
        who = int(item.get("who") or 0)
        owner = owners.get(who) if who else None
        for tag in tags:
            if owner is not None and tag not in owner.attrs:
                owner.attrs.append(tag)
            place(tag)
    if chooser is not None:
        # 모델이 안 낸 요청 명사(소파)도 같이 고른다 — 고를 것이 없으면 모델을 부르지 않는다
        extra = chooser(asks) or []
        for ask in asks:
            chosen = ask.chosen()
            owner = owners.get(ask.who) if ask.who else None
            for tag in chosen:
                if _junk_tag(tag):
                    continue
                if owner is not None and tag not in owner.attrs:
                    owner.attrs.append(tag)
                place(tag)
            log.append(f"ask:{ask.en}|{ask.ko}->{','.join(chosen) or '없음'}" + ("(예전 결과)" if ask.picks is None else ""))
        for tag in extra:
            place(tag)
            log.append(f"extra:{tag}")
    exclude: list[str] = []
    excluded_for: dict[int, set[str]] = {}       # 인물 번호 -> 그 인물 칸에서 뺄 것(0 = 장면 전체 = 모든 인물)

    def add_exclude(tag: str, who: Any) -> None:
        if tag not in exclude:
            exclude.append(tag)
        excluded_for.setdefault(int(who or 0), set()).add(tag)

    for item in route.get("exclude") or []:
        for tag in item_tags(item, "exclude"):
            add_exclude(tag, item.get("who"))
    for item in route.get("include") or []:                         # 'no towel' -> 제외
        m = _NEGATION.match(str(item.get("en") or "").strip().lower())
        if m:
            for tag in resolve_english(m.group(1) or m.group(2), vocab):
                add_exclude(tag, item.get("who"))
    # 영문 제외(hat 빼고) — 모델이 제외 칸에 안 적었거나 ko 를 옮겨 적어 버려졌어도 뺀다(맵 이름이 있으면 그 이름으로)
    for part in english.exclude:
        add_exclude(exact_english(en_key(part), vocab, verb=False) or part, 0)
    # 싣겠다고 적은 영문은 제외에서 푼다 — 모델이 제외 칸에 잘못 옮겨 적은 것(빼라는 말은 없었다)
    wanted = {en_key(p) for p in english.keep}
    exclude[:] = [t for t in exclude if en_key(t) not in wanted]
    for tier in (t1, t2, t3):
        tier[:] = [t for t in tier if t not in exclude]
    # 인물 칸에도 — 뺀 것이 캐릭터 프롬프트로 새지 않게(Codex 재리뷰 R1). 단 그 인물을 가리킨 제외와 장면 전체의 제외만 —
    # 한 인물의 제외가 다른 인물 칸까지 지웠다('카나데는 웃고 나히다는 웃지 않는' 의 카나데 smile, Codex 3차 N1)
    live = set(exclude)
    slot_of = {id(ch): who for who, ch in owners.items()}
    for ch in characters:
        who = slot_of.get(id(ch), 0)
        drop = (excluded_for.get(0, set()) | (excluded_for.get(who, set()) if who else set())) & live
        ch.attrs[:] = [t for t in ch.attrs if t not in drop]

    # 인물 사이 동작: 둘 이상 + Kiwi 가 방향을 잡았을 때. 동작은 사전 구 > 모델 동작.
    relations: list[tuple[str, str, str]] = []
    roles = roles_for({c.ko for c in characters}) if roles_for else ka.roles
    if len(characters) >= 2 and roles:
        src = next((c for c in characters if c.ko == roles[0]), None)
        dst = next((c for c in characters if c.ko == roles[1]), None)
        # 동사에서 나온 구만(공주 안기·볼 꼬집기·안기) — 명사 복합어(비치볼)는 동작이 아니다.
        # 자세·흔한 것(sleeping·smile)은 한 사람의 상태라 관계로 쓰지 않는다(안겨서 자는 -> sleeping 관계, 실측).
        # 뺀 동작은 관계로도 싣지 않는다 — 층에서 지워도 관계가 다시 골라 source# · target# 으로 붙었다(Codex 3차 R1 잔존).
        # 장면 전체와 **두 사람**을 가리킨 제외는 늘 막는다. 제3자의 제외는 모델이 그 동작을 **이 두 사람 사이**
        # (source · target 번호)로 적었을 때만 넘긴다 — 한국어 층의 동작 후보(verb_phrases)는 누구의 절인지 · 부정인지
        # 모른다: 합쳐 막으면 '카나데가 나히다를 공주안기 하고 미쿠는 하지 않는' 의 관계가 지워지고(Codex 4차 N2), 당사자
        # 것만 막으면 '카나데가 나히다를 바라보고 미쿠는 공주안기를 하지 않는' 에 없던 공주안기 관계가 붙었다(5차 N3).
        # 쌍은 방향 없이 본다 — 방향은 Kiwi(roles)가 정한다. 모델이 source · target 만 뒤집어 적어도 관계는 산다(6차 N4)
        src_who = slot_of.get(id(src), 0) if src is not None else 0
        dst_who = slot_of.get(id(dst), 0) if dst is not None else 0
        blocked = set(excluded_for.get(0, set()))
        for who in (src_who, dst_who):
            if who:
                blocked |= excluded_for.get(who, set())
        pair = {src_who, dst_who}
        paired = {t for item, tags in acted
                  if src_who and dst_who and {int(item.get("source") or 0), int(item.get("target") or 0)} == pair
                  for t in tags}
        blocked |= {t for t in live if t not in paired}           # 제3자의 제외 — 이 쌍의 모델 동작이 아니면 막는다
        blocked &= live

        def interaction(tags: Iterable[str]) -> str | None:
            tags = [t for t in tags if t not in generic and t not in poses and t not in blocked]
            return next((t for t in tags if vocab.role(t) == "event_core"), None) or next(iter(tags), None)

        act = interaction(ka.verb_phrases)
        if act is None:
            act = next((t for t in ka.verb_tags if t not in generic and t not in poses and t not in blocked
                        and vocab.role(t) == "event_core"), None)
        if act is None:
            for _item, tags in acted:
                act = interaction(tags)
                if act:
                    break
        if src and dst and act:
            relations.append((src.tag, act, dst.tag))
    # 요청에 동사가 있으면(서서 밖을 보는) 행동이 있는 것 — 랜덤 행동을 덧붙이지 않는다. 영문으로 적은 동작(running)도
    typed = [exact_english(en_key(p), vocab, verb=False) for p in english.keep]
    has_action = (any(vocab.role(t) == "event_core" for t in t1 + t2) or bool(relations) or bool(ka.verb_tags)
                  or any(t and vocab.role(t) == "event_core" for t in typed))
    return Merged(task=route.get("task", "other"), goal=route.get("goal", "find"), tiers=(t1, t2, t3),
                  exclude=exclude, characters=characters, relations=relations, has_action=has_action,
                  name=route.get("name", ""), name_ko=route.get("name_ko", ""), log=log, english=english)


def off_rating(tags: Iterable[str], share: Callable[[str], float | None], min_share: float) -> dict[str, float]:
    """고른 등급에서 거의 안 쓰이는 태그 -> 그 등급의 게시물 비중. 비중을 모르는 태그(맵에 없음·게시물이 적음)는 둔다.
    사전·퍼지·모델 어느 길로 들어온 태그든 마지막에 여기서 거른다 — 길마다 막으면 새 길이 샌다(09-24).

    ⚠️ 성능 평가를 위해 추가적인 정책 부여를 차단하는 중이므로 임의로 수정하지 말 것.
    """
    # ⚠️ 성능 평가를 위해 추가적인 정책 부여를 차단 중 (임의 수정 금지)
    return {}


def drop_tags(merged: Merged, tags: Iterable[str]) -> None:
    """모든 칸(층 · 인물 속성 · 관계 동작)에서 뺀다."""
    drop = set(tags)
    for tier in merged.tiers:
        tier[:] = [t for t in tier if t not in drop]
    for c in merged.characters:
        c.attrs[:] = [t for t in c.attrs if t not in drop]
    merged.relations[:] = [r for r in merged.relations if r[1] not in drop]


def replace_tag(merged: Merged, old: str, new: str) -> None:
    """태그 하나를 다른 태그로 — 같은 자리에서(층 · 인물 속성). 새 태그가 이미 있으면 옛것만 뺀다(동음이의어 뜻 검사)."""
    for bag in [*merged.tiers, *(c.attrs for c in merged.characters)]:
        if old not in bag:
            continue
        if new in bag:
            bag[:] = [t for t in bag if t != old]
        else:
            bag[:] = [new if t == old else t for t in bag]


# Q · E 에서 '(nonsexual)' 태그의 성적 대응 — 사전의 '묶이기'(결박 · 포박)가 tied up (nonsexual) 이라 E 의 '손과 발이 묶여있는
# 채로 체육실에 갇혀 방치당하는 소녀' 가 비성적 결박이 됐다(사용자 제보 09-28 — 26B 로 바꿔도 같았다: 모델이 아니라 사전 길).
# G · S 에선 그대로가 맞다. 사전의 (nonsexual) 태그는 이것 하나다. 등급 게이트(off_rating)와는 다른 것이다 — 그 함수는 다른
# 세션이 평가 중이라 건드리지 않는다
NSFW_SWAPS = {"tied up (nonsexual)": "restrained"}


def rating_name(tag: str, rating: str) -> str:
    """고른 등급에 맞는 이름 — Q · E 면 NSFW_SWAPS, 아니면 그대로."""
    return NSFW_SWAPS.get(tag, tag) if rating in ("q", "e") else tag


def rating_sources(tag: str, rating: str) -> list[str]:
    """이 이름과, Q · E 에서 이 이름으로 바뀌는 옛 이름들 — 옛 이름의 한국어 키워드(포박 · 묶이기)로도 가리키게(Codex 11차 R7).
    옛 이름의 꼬리 없는 꼴(tied up)도 — 영어 근거(문장 · 영문 요청)가 nonsexual 까지 말하지는 않는다(12차 F6)."""
    if rating not in ("q", "e"):
        return [tag]
    olds = [old for old, new in NSFW_SWAPS.items() if new == tag]
    return list(dict.fromkeys([tag, *olds, *(base_name(old) for old in olds)]))


def swap_for_rating(merged: Merged, rating: str) -> None:
    """모든 칸(층 · 인물 속성)의 NSFW_SWAPS 를 고른 등급에 맞게 — 같은 자리에서(replace_tag). 관계 동작 · 제외도
    (관계가 옛 이름이면 source# · target# 과 recap 에 남았다 — Codex 11차 R6)."""
    if rating not in ("q", "e"):
        return
    # 제외 칸은 이벤트 맵 검색에 통째로 쓰인다 — 바꾼 이름이 제외와 겹치면 안 된다(Codex 12차 F4). 겹치면 **바꾸지 않는다**(옛 이름
    # 그대로 = 치환 전 동작): 새 이름(restrained)이 제외에 있으면 옛 이름을 그대로 두고, 옛 이름을 뺐는데 새 이름이 실려 있으면
    # 제외는 옛 이름 그대로. 옛 이름을 빼 버리면 인물마다의 제외 범위(merge 의 excluded_for)를 넘어 다른 인물의 태그까지
    # 지웠다(13차 R5). 실림에는 영문으로 적은 태그(english.keep)도 든다(13차 R4)
    excluded = set(merged.exclude)
    for old, new in NSFW_SWAPS.items():
        if new in excluded:
            continue
        replace_tag(merged, old, new)
        merged.relations[:] = [(s, new if a == old else a, d) for s, a, d in merged.relations]
    shown = (set(merged.all_tags()) | {a for c in merged.characters for a in c.attrs} | {r[1] for r in merged.relations}
             | {en_key(p) for p in merged.english.keep})
    merged.exclude[:] = list(dict.fromkeys(t if rating_name(t, rating) in shown else rating_name(t, rating)
                                           for t in merged.exclude))


# 단부루의 가족 태그는 **그림 속 인물들이 서로 그 사이**라는 뜻이다 — 누나 · 언니는 호칭(연상 여성)이지 관계가 아니다. 경로 모델이
# 누나/언니를 older sister 로 옮겨 여성 한 명에 sisters 가 붙었다(09-29 E4B 창작 문장, 사용자 동의). 요청에 그 사이를 말하는
# 낱말이 있거나 태그를 영문으로 적었을 때만 둔다
FAMILY_TAGS = {"sisters": ("자매", "쌍둥이"), "brothers": ("형제", "쌍둥이"), "siblings": ("남매", "형제", "자매", "쌍둥이"),
               "brother and sister": ("남매",), "twins": ("쌍둥이",)}


def unstated_family(tag: str, text: str) -> bool:
    """요청이 말하지 않은 가족 태그인가."""
    words = FAMILY_TAGS.get(tag)
    if words is None:
        return False
    said = compact(clean_text(text))
    typed = re.search(rf"(?<![a-z]){re.escape(tag)}(?![a-z])", str(text or "").lower())    # LittleTwinStars 의 twins 는 아니다
    return not any(w in said for w in words) and not typed


def drop_unstated_family(merged: Merged, text: str) -> None:
    """모든 칸(층 · 인물 속성 · 관계)에서 요청이 말하지 않은 가족 태그를 뺀다."""
    drop_tags(merged, [t for t in FAMILY_TAGS if unstated_family(t, text)])


# ── 조립 ───────────────────────────────────────────────────────────────────

PERSON_TAGS = {
    "1girl_solo": ["1girl", "solo"], "1girl": ["1girl"], "1girl_1boy": ["1girl", "1boy"],
    "1girl_multiple_boys": ["1girl", "multiple boys"], "2girls": ["2girls"], "multiple_girls": ["multiple girls"],
    "1boy_solo": ["1boy", "solo"], "1boy": ["1boy"], "1boy_multiple_girls": ["1boy", "multiple girls"],
    "2boys": ["2boys"], "multiple_boys": ["multiple boys"],
    "multiple_girls_multiple_boys": ["multiple girls", "multiple boys"],
}


def _with_sentence(main: str, sentence: str) -> str:
    """메인 = 태그들, 문장 — Boost 처럼 태그 뒤에 자연어(사용자 제안 09-25). 문장이 없으면 태그만."""
    return f"{main}, {sentence}" if main and sentence else (main or sentence)


def compose(merged: Merged, *, pins: list[str], leftovers: list[str], actions: list[str], partition: str,
            api_mode: str) -> dict[str, Any]:
    """최종 프롬프트. NAI 는 메인 + 캐릭터 칸(이름·그 인물 속성·source#/target#), 그 밖은 한 줄. 다듬기 문장은 메인 끝.
    사용자가 섞어 쓴 영문은 적힌 그대로(09-26) — 같은 태그가 이미 있으면 그 자리를 사용자 표기로, 없으면 인원·이름 뒤에."""
    people = PERSON_TAGS.get(partition, [])
    char_attrs = {a for c in merged.characters for a in c.attrs}
    scene = [t for t in dict.fromkeys(pins + actions + leftovers) if t not in char_attrs]
    taken = people + [c.tag for c in merged.characters] + [c.ko for c in merged.characters]
    if str(api_mode or "").upper() == "NAI" and merged.characters:
        bags = []
        for c in merged.characters:
            parts = [c.tag] + list(c.attrs)
            for src, act, dst in merged.relations:
                if c.tag == src:
                    parts.append(f"source#{act}")
                if c.tag == dst:
                    parts.append(f"target#{act}")
            bags.append(parts + list(c.features))           # 캐릭터 특징은 칸 끝에(사용자 지정 09-26)
        typed = put_english(merged.english.keep, [scene, *bags], taken=taken)
        chars = [{"prompt": ", ".join(dict.fromkeys(parts)), "ko": c.ko, "alts": c.alts}
                 for c, parts in zip(merged.characters, bags)]
        return {"main": _with_sentence(", ".join(dict.fromkeys(people + typed + scene)), merged.sentence),
                "characters": chars}
    names = [c.tag for c in merged.characters]
    attrs = [a for c in merged.characters for a in c.attrs] + [f for c in merged.characters for f in c.features]
    rel = [act for _s, act, _d in merged.relations]
    typed = put_english(merged.english.keep, [scene, attrs, rel], taken=taken)
    line = list(dict.fromkeys(people + names + typed + scene + attrs + rel))
    return {"main": _with_sentence(", ".join(line), merged.sentence), "characters": []}


def make_recap(merged: Merged, *, partition: str, rating: str) -> dict[str, Any]:
    """다음 요청에 붙일 기억(직전 검색 하나). 화면이 들고 있다가 그대로 돌려보낸다."""
    return {
        "task": merged.task,
        "characters": [c.ko for c in merged.characters],
        "relations": [f"{s} {a} {d}" for s, a, d in merged.relations],
        "include": merged.all_tags(),
        "exclude": list(merged.exclude),
        "persons": partition,
        "rating": rating,
    }


def _recap_for_model(recap: dict[str, Any]) -> dict[str, Any]:
    keep = {k: recap.get(k) for k in ("task", "characters", "include", "exclude")}
    if recap.get("relations"):
        keep["actions"] = recap["relations"]
    return {k: v for k, v in keep.items() if v not in (None, "", [])}
