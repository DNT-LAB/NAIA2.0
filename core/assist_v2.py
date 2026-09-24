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

from core.assist_korean import KoreanAnalysis, NameHit, clean_text, compact

TASKS = ("scene", "tag", "character", "artist", "wildcard", "preset", "other")
GOALS = ("find", "how", "generate")
RATINGS = ("g", "s", "q", "e")
MAX_TEXT = 300
MAX_INCLUDE = 10

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
List every concept of the request (up to 10).
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
_SYNONYMS = {"photo": "picture", "photos": "pictures"}


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


def user_message(text: str, recap: dict[str, Any] | None = None) -> str:
    """모델 입력. 기억은 직전 검색 하나(서버가 만든 recap)뿐 — 초기 원문은 다시 넣지 않는다(지운 것이 되살아난다)."""
    lines = []
    if recap:
        lines.append("Current search: " + json.dumps(_recap_for_model(recap), ensure_ascii=False))
    lines.append(f"Request: {clean_text(text).strip()}")
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


def en_variants(term: str) -> list[str]:
    """모델 영문의 흔한 어긋남: 복수·붙여쓰기·-ing·-y·wearing·photo. 순서가 우선순위다."""
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
    elif len(words) == 1 and not t.endswith("ing"):
        out.append(t + "ing")                                        # laugh -> laughing
    if len(words) == 1 and t.endswith("y") and len(t) > 4:
        out.append(t[:-1])                                           # rainy -> rain
    return list(dict.fromkeys(out))


def resolve_english(term: str, vocab: TagVocab) -> list[str]:
    for v in en_variants(term):
        name = vocab.canonical(v)
        if name:
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
            name = next((n for n in (vocab.canonical(v) for v in en_variants(piece)) if n), None)
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
          name_lookup: Callable[[str], NameHit | None] | None = None,
          not_names: Iterable[str] = (), poses: Iterable[str] = (),
          roles_for: Callable[[set[str]], tuple[str, str] | None] | None = None) -> Merged:
    generic = set(generic)
    poses = set(poses)
    similes = tuple(simile_particles)
    blocked, covers = set(ka.blocked), set(ka.covers)
    req_lemmas = ka.lemmas()
    req_compact = compact(clean_text(text))
    log: list[str] = []
    t1: list[str] = [t for t in ka.specific if t not in blocked]
    t2: list[str] = []
    t3: list[str] = []

    def place(tag: str, *, first: bool = False) -> None:
        if not tag or tag in blocked or tag in covers or vocab.role(tag) == "population":
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
        return bool(stems & req_lemmas) or any(len(s) >= 2 and s in req_compact for s in stems)

    def item_tags(item: dict[str, Any], kind: str) -> list[str]:
        en = str(item.get("en") or "").strip().lower()
        ko = str(item.get("ko") or "").strip()
        if _PEOPLE_EN.match(en):
            return []
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
        phrase = next((tag for key, tag in ka.phrases.items() if ko_c and (ko_c in key or key in ko_c)), None)
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
        found = resolve_english(en, vocab)
        if found and len(found) == 1:
            return found
        if len(ko_c) >= 2:
            hit = vocab.keyword(ko)
            if hit:
                return hit[:1]
        if found:
            return found
        en_words = {w[:4] for w in re.findall(r"[a-z]+", en) if len(w) >= 3}
        for cand in vocab.fuzzy(ko) if ko else []:
            words = {w[:4] for w in re.findall(r"[a-z]+", cand.lower()) if len(w) >= 3}
            if en_words & words and vocab.canonical(cand):
                return [vocab.canonical(cand)]
        log.append(f"unresolved:{en}|{ko}")
        return []

    # 인물: 모델이 적은 이름(요청에 있고 일반 명사 아님) + Kiwi 고유명사
    not_names = set(not_names)
    names: list[NameHit] = []
    model_chars = route.get("characters") or []
    order: list[str] = []
    for c in model_chars:
        ko = clean_text(c.get("ko") or "").strip()
        if ko and ko not in not_names and ko in clean_text(text) and ko not in order:
            order.append(ko)
    for hit in ka.names:
        if hit.form not in order:
            order.append(hit.form)
    # 전체 이름과 그 조각이 함께 있으면(나토리 사나 · 나토리) 조각은 같은 사람이다 — 인물을 둘로 세지 않는다
    # (사용자 제보 09-24: 캐릭터 3 이 생겼다). 한국어 층이 토막을 합치지만, 모델이 적은 이름과 어긋날 때의 그물.
    packed = {form: compact(form) for form in order}
    order = [form for form in order
             if not any(other != form and len(packed[other]) > len(packed[form]) and packed[form] in packed[other]
                        for other in order)]
    by_form = {h.form: h for h in ka.names}
    for form in order:
        hit = by_form.get(form) or (name_lookup(form) if name_lookup else None)
        if hit and hit.candidates:
            names.append(hit)
    characters = [Character(h.form, h.tag, [t for t, _n in h.candidates[1:3]], h.gender) for h in names]
    model_index = {clean_text(c.get("ko") or "").strip(): i + 1 for i, c in enumerate(model_chars)}

    for item in route.get("actions") or []:
        for tag in item_tags(item, "action"):
            place(tag)
    for item in route.get("include") or []:
        tags = item_tags(item, "include")
        who = int(item.get("who") or 0)
        owner = next((ch for ch in characters if model_index.get(ch.ko) == who), None) if who else None
        for tag in tags:
            if owner is not None and tag not in owner.attrs:
                owner.attrs.append(tag)
            place(tag)
    exclude: list[str] = []
    for item in route.get("exclude") or []:
        for tag in item_tags(item, "exclude"):
            if tag not in exclude:
                exclude.append(tag)
    for item in route.get("include") or []:                         # 'no towel' -> 제외
        m = _NEGATION.match(str(item.get("en") or "").strip().lower())
        if m:
            for tag in resolve_english(m.group(1) or m.group(2), vocab):
                if tag not in exclude:
                    exclude.append(tag)
    for tier in (t1, t2, t3):
        tier[:] = [t for t in tier if t not in exclude]

    # 인물 사이 동작: 둘 이상 + Kiwi 가 방향을 잡았을 때. 동작은 사전 구 > 모델 동작.
    relations: list[tuple[str, str, str]] = []
    roles = roles_for({c.ko for c in characters}) if roles_for else ka.roles
    if len(characters) >= 2 and roles:
        src = next((c for c in characters if c.ko == roles[0]), None)
        dst = next((c for c in characters if c.ko == roles[1]), None)
        # 동사에서 나온 구만(공주 안기·볼 꼬집기·안기) — 명사 복합어(비치볼)는 동작이 아니다.
        # 자세·흔한 것(sleeping·smile)은 한 사람의 상태라 관계로 쓰지 않는다(안겨서 자는 -> sleeping 관계, 실측).
        def interaction(tags: Iterable[str]) -> str | None:
            tags = [t for t in tags if t not in generic and t not in poses]
            return next((t for t in tags if vocab.role(t) == "event_core"), None) or next(iter(tags), None)

        act = interaction(ka.verb_phrases)
        if act is None:
            act = next((t for t in ka.verb_tags if t not in generic and t not in poses
                        and vocab.role(t) == "event_core"), None)
        if act is None:
            for item in route.get("actions") or []:
                act = interaction(item_tags(item, "action"))
                if act:
                    break
        if src and dst and act:
            relations.append((src.tag, act, dst.tag))
    # 요청에 동사가 있으면(서서 밖을 보는) 행동이 있는 것 — 랜덤 행동을 덧붙이지 않는다
    has_action = any(vocab.role(t) == "event_core" for t in t1 + t2) or bool(relations) or bool(ka.verb_tags)
    return Merged(task=route.get("task", "other"), goal=route.get("goal", "find"), tiers=(t1, t2, t3),
                  exclude=exclude, characters=characters, relations=relations, has_action=has_action,
                  name=route.get("name", ""), name_ko=route.get("name_ko", ""), log=log)


# ── 조립 ───────────────────────────────────────────────────────────────────

PERSON_TAGS = {
    "1girl_solo": ["1girl", "solo"], "1girl": ["1girl"], "1girl_1boy": ["1girl", "1boy"],
    "1girl_multiple_boys": ["1girl", "multiple boys"], "2girls": ["2girls"], "multiple_girls": ["multiple girls"],
    "1boy_solo": ["1boy", "solo"], "1boy": ["1boy"], "1boy_multiple_girls": ["1boy", "multiple girls"],
    "2boys": ["2boys"], "multiple_boys": ["multiple boys"],
    "multiple_girls_multiple_boys": ["multiple girls", "multiple boys"],
}


def compose(merged: Merged, *, pins: list[str], leftovers: list[str], actions: list[str], partition: str,
            api_mode: str) -> dict[str, Any]:
    """최종 프롬프트. NAI 는 메인 + 캐릭터 칸(이름·그 인물 속성·source#/target#), 그 밖은 한 줄."""
    people = PERSON_TAGS.get(partition, [])
    char_attrs = {a for c in merged.characters for a in c.attrs}
    scene = [t for t in dict.fromkeys(pins + actions + leftovers) if t not in char_attrs]
    if str(api_mode or "").upper() == "NAI" and merged.characters:
        chars = []
        for c in merged.characters:
            parts = [c.tag] + c.attrs
            for src, act, dst in merged.relations:
                if c.tag == src:
                    parts.append(f"source#{act}")
                if c.tag == dst:
                    parts.append(f"target#{act}")
            chars.append({"prompt": ", ".join(dict.fromkeys(parts)), "ko": c.ko, "alts": c.alts})
        return {"main": ", ".join(people + scene), "characters": chars}
    names = [c.tag for c in merged.characters]
    attrs = [a for c in merged.characters for a in c.attrs]
    rel = [act for _s, act, _d in merged.relations]
    line = list(dict.fromkeys(people + names + scene + attrs + rel))
    return {"main": ", ".join(line), "characters": []}


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
