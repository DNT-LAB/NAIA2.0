"""Assist v2 구성(compose) — 여러 줄 요청을 메인·캐릭터 프롬프트 + 설명으로 (순수 로직, 입출력 없음).

    main: 오토노세 카나데가 나토리 사나를 공주안기 하고 있는 구도.
    c1 오토노세 카나데 - 나토리 사나를 공주안기 한 채로 도야가오 표정
    c2 나토리 사나 - 오토노세 카나데에게 안긴채로 휴대폰을 보고 있음, 살짝 짜증난듯한 (귀찮은) 표정, …

사용자 지정(2026-09-24): Claude 같은 답을 E2B 로 — "Tool Calling 으로 최대한 제한". E2B 는 두 번, 좁게만 쓴다.
  1) 절마다 영문 추측 1~3개(문법: 문자열 배열) — 한국어 사전이 모르는 말의 다리(양말 높낮이가 다름 -> uneven socks)
  2) 한국어 근거와 영문 근거가 **엇갈리거나 둘 다 약한** 절만 후보 중 하나 고르기(문법: 후보 태그 이름만)
나머지는 도구(코드)다: 절 가르기(Kiwi) · 인물·방향(한국어 층) · 후보 찾기(한국어 키워드 부분 일치 · 사전 구 · 영문 낱말
색인) · 존재·게시물 수 · 공출현(이벤트 맵) · 외모(character_analysis) · 배치(메인/캐릭터) · 설명 문장(틀).
설명 문장은 모델에 쓰게 하지 않는다 — 자연어 작성기가 없는 태그·실명을 지어냈다(실측 09-23).
실측과 함정: docs/ASSIST_V2_DESIGN_2026_09_23.md 15절.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from core.assist_korean import clean_text, compact

MAX_CHARACTERS = 6
MAX_CLAUSES = 16
MAX_GUESSES = 3
TOP_K = 5
MIN_ASK_SCORE = 2.0          # 이보다 약한 후보만 있으면 모델에 묻지 않는다(헛것 목록을 보여 주지 않는다)
RARE_POSTS = 3000            # 이보다 드문 태그는 '안 나오면 강조' 팁
MAX_NOTES = 3

# ── 여러 줄 요청 ───────────────────────────────────────────────────────────

_CHAR_LINE = re.compile(r"^\s*(?:c|캐릭터|char(?:acter)?)\s*(\d{1,2})\s*[:.)\]]?\s*(.*)$", re.I)
# ⚠️ 머리표 뒤 가르개(: -)가 **있어야** 머리표다 — 없으면 '장면 설명' 의 '장면' 까지 먹었다(시험이 잡음)
_MAIN_LINE = re.compile(r"^\s*(?:main|메인|장면)\s*[:：\-–—]\s*(.*)$", re.I)
_NAME_SEP = re.compile(r"\s+[-–—]\s+|\s*[:：]\s*|\s+[-–—]|[-–—]\s+")


@dataclass
class Segment:
    index: int          # 0 = 장면(main), 1.. = 캐릭터 줄 차례
    name: str           # 캐릭터 줄에 적힌 이름(없으면 "")
    body: str


def parse_segments(text: Any) -> list[Segment]:
    """``main: …`` / ``c1 이름 - 설명`` 줄을 가른다. 캐릭터 줄이 **하나도 없으면 []** — 구성 요청이 아니다.

    이름과 설명은 ' - ' · ':' 로 가른다. 가르개가 없으면 이름 칸이 비고(서비스가 줄에서 이름을 찾는다),
    머리표 없는 줄은 장면으로 본다."""
    scene: list[str] = []
    chars: list[Segment] = []
    for line in str(text or "").splitlines():
        if not line.strip():
            continue
        m = _CHAR_LINE.match(line)
        if m:
            rest = clean_text(m.group(2)).strip()
            parts = _NAME_SEP.split(rest, maxsplit=1)
            name, body = (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else ("", rest)
            if len(name) > 30:                      # 가르개로 본 것이 문장 속 기호였다
                name, body = "", rest
            chars.append(Segment(len(chars) + 1, name, body))
            continue
        m = _MAIN_LINE.match(line)
        scene.append(clean_text(m.group(1) if m else line).strip())
    if not chars:
        return []
    return [Segment(0, "", " ".join(s for s in scene if s))] + chars[:MAX_CHARACTERS]


def strip_subject(clause: str, names: Iterable[str]) -> str:
    """'하츠네 미쿠가 혼자 …' -> '혼자 …' — 주어 이름은 캐릭터 칸이 말한다."""
    out = clean_text(clause)
    for n in sorted((n for n in names if n), key=len, reverse=True):
        out = re.sub(rf"^\s*{re.escape(n)}\s*(?:이|가|은|는|께서|도)?\s*", "", out)
    return out.strip()


def josa(word: str, with_final: str, without_final: str) -> str:
    """받침 따라 조사 고르기(을/를 · 이/가 · 은/는). 한글이 아니면 받침 없는 쪽."""
    ch = str(word or "").strip()[-1:]
    if "가" <= ch <= "힣":
        return with_final if (ord(ch) - 0xAC00) % 28 else without_final
    return without_final


def subject_prefix(name: str) -> str:
    """캐릭터 줄을 방향 분석에 넣을 때 주인을 주어로 세운다(나토리 사나 + 가)."""
    return f"{name}{josa(name, '이', '가')} "


# ── E2B 1: 영문 추측 ───────────────────────────────────────────────────────

GUESS_SYSTEM = """You translate short Korean descriptions of an anime picture into Danbooru tags. Do not chat.
For every numbered line give 1 to 3 short English Danbooru-style tags (lowercase, 1-4 words).
If the line has two or more things (a place and an action, a held item and a pose), give one tag for each.
Keep the list order.

Example
1: 부드럽게 미소
2: 한 손에 책을 쥐고 창가에 앉아
3: 리본이 풀려서 바닥에 떨어져 있음
4: 해질녘 교실에서 창밖을 보는 장면
[["gentle smile"],["holding book","sitting","window"],["untied ribbon","ribbon on floor"],["sunset","classroom","looking outside"]]"""

_STR = '"\\"" [^"\\\\\\x7F\\x00-\\x1F]{1,40} "\\""'


def guess_message(clauses: list[str]) -> str:
    return "\n".join(f"{i}: {c}" for i, c in enumerate(clauses, 1))


def guess_grammar(n: int) -> str:
    """정확히 n 줄 · 줄마다 1~3개 · 공백 없음."""
    if n < 1:
        raise ValueError("추측할 절이 없다")
    return ('root ::= "[" ' + ' "," '.join(["l"] * n) + ' "]"\n'
            f'l ::= "[" s ("," s){{0,{MAX_GUESSES - 1}}} "]"\n' f"s ::= {_STR}")


def parse_guesses(text: str, n: int) -> list[list[str]]:
    """모델 출력 -> 절마다 추측(소문자 · 빈 것 버림). 모양이 어긋나면 모두 빈 목록(한국어 근거만으로 간다)."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return [[] for _ in range(n)]
    if not isinstance(data, list) or len(data) != n:
        return [[] for _ in range(n)]
    out = []
    for line in data:
        items = line if isinstance(line, list) else []
        out.append(list(dict.fromkeys(" ".join(str(x).lower().replace("_", " ").split())
                                      for x in items if str(x).strip()))[:MAX_GUESSES])
    return out


# ── E2B 2: 후보 중 하나 ─────────────────────────────────────────────────────

CHOOSE_SYSTEM = """You match Korean descriptions to Danbooru tags. For each detail, read the Korean meaning of every
candidate and write the ONE candidate tag that means the same thing as the detail.
Write "none" if no candidate shows it."""


def choose_message(items: list[tuple[str, list[tuple[str, str]]]]) -> str:
    """[(설명 줄, [(태그, 한국어 뜻)])] -> 모델 입력."""
    lines = []
    for i, (detail, cands) in enumerate(items, 1):
        lines.append(f"Detail {i}: {detail}")
        lines += [f"  - {tag}: {desc}" for tag, desc in cands]
    return "\n".join(lines)


def choose_grammar(cands: list[list[str]]) -> str:
    """디테일마다 그 후보 이름 또는 "none" 만 — 목록 밖 태그를 쓸 수 없다."""
    if not cands:
        raise ValueError("고를 것이 없다")
    rules, parts = [], []
    for i, names in enumerate(cands):
        alts = " | ".join(json.dumps(json.dumps(t, ensure_ascii=False), ensure_ascii=False) for t in [*names, "none"])
        rules.append(f"t{i} ::= {alts}")
        parts.append(f"t{i}")
    return 'root ::= "[" ' + ' "," '.join(parts) + ' "]"\n' + "\n".join(rules)


def parse_choice(text: str, cands: list[list[str]]) -> list[str | None]:
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return [None] * len(cands)
    if not isinstance(data, list) or len(data) != len(cands):
        return [None] * len(cands)
    return [x if isinstance(x, str) and x in names else None for x, names in zip(data, cands)]


# ── 후보 찾기 ──────────────────────────────────────────────────────────────

# 영문 추측의 옷·소지품 낱말 -> Danbooru 의 묶음 낱말(socks -> legwear: uneven socks = uneven legwear)
EN_SYNONYMS = {"sock": "legwear", "stocking": "legwear", "tights": "legwear", "pantyhose": "legwear",
               "shoe": "footwear", "boot": "footwear", "sneaker": "footwear", "glasses": "eyewear",
               "spectacles": "eyewear", "hat": "headwear", "cap": "headwear", "glove": "handwear",
               "cellphone": "phone", "smartphone": "phone", "mobile": "phone",
               # 동작 꼴 -> Danbooru 가 쓰는 낱말(leg raised -> leg up · 실측 09-24: legs 가 골라졌다)
               "raise": "up", "raised": "up", "raising": "up", "lift": "up", "lifted": "up", "lifting": "up",
               "lowered": "down", "lowering": "down", "grab": "holding", "grabbing": "holding",
               "grip": "holding", "gripping": "holding", "clutching": "holding"}
EN_STOP = frozenset({"on", "in", "at", "the", "a", "an", "of", "with", "and", "to", "for", "is", "one", "her", "his",
                     "own", "from", "while", "being", "by", "very", "slightly", "little", "bit", "look",
                     "expression", "face"})
_META = re.compile(r"\((?:animated|medium|meme|artwork|style|cosplay|parody)\)$")
_PEOPLE = re.compile(r"^(?:\d+\+?(?:girl|boy|other)s?|solo(?: focus)?|multiple (?:girls|boys|others)|"
                     r"(?:male|female) focus|everyone|group)$")
_EMOTICON = re.compile(r"^[^a-z]*$|^[^a-z]{1,2}\s?[a-z]?$")


def en_stems(word: str) -> set[str]:
    w = str(word or "").lower()
    out = {w}
    if len(w) > 4 and w.endswith("ies"):
        out.add(w[:-3] + "y")
    elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        out.add(w[:-1])
    if len(w) > 5 and w.endswith("ing"):
        out |= {w[:-3], w[:-3] + "e"}
    if len(w) > 4 and w.endswith("ed"):
        out |= {w[:-2], w[:-1]}
    return out


def _expand(word: str) -> set[str]:
    out = en_stems(word)
    return out | {EN_SYNONYMS[s] for s in out if s in EN_SYNONYMS}


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", str(text or "").lower()) if w not in EN_STOP and len(w) >= 2]


def build_word_index(names: Iterable[str]) -> dict[str, set[str]]:
    """태그 이름의 낱말(어간 포함) -> 태그들. 이벤트 맵 어휘(약 5만 8천)로 한 번 만든다."""
    index: dict[str, set[str]] = {}
    for name in names:
        for w in re.findall(r"[a-z0-9]+", str(name).lower()):
            for s in en_stems(w):
                index.setdefault(s, set()).add(str(name))
    return index


@dataclass
class TagTools:
    """후보 찾기가 묻는 도구. 서비스가 NAIA 사전·이벤트 맵·한국어 층으로 채우고, 시험은 작은 가짜를 넣는다."""

    canonical: Callable[[str], str | None]            # 이벤트 맵 어휘의 정확한 이름
    count: Callable[[str], int]                       # 게시물 수
    info: Callable[[str], dict[str, Any]]             # 태그 사전 항목(description · keywords_kr · _cat · group)
    keyword_tags: Callable[[str], list[str]]          # 붙여 쓴 한국어 키워드 -> 태그(묶음 제외, 게시물 순)
    analyze: Callable[[str], Any]                     # 한국어 층 분석(phrases · specific · verb_tags)
    word_index: dict[str, set[str]] = field(default_factory=dict)
    fuzzy: Callable[[str], list[str]] = lambda _k: []
    nouns: Callable[[str], list[str]] = lambda _k: []
    role: Callable[[str], str | None] = lambda _t: None
    name_claims: Callable[[str], int] = lambda _l: 1       # 이 말을 제 이름([…]·첫 키워드)으로 쓰는 태그 수 — 모르면 '있다'(분류로 본다)
    label_uses: Callable[[str], int] = lambda _l: 2        # 이 말을 <라벨> 로 쓰는 태그 수 — 둘 이상이면 분류(<신발>)


@dataclass
class Candidate:
    tag: str
    score: float = 0.0
    posts: int = 0                                      # 게시물 수(짝 태그 · 팁)
    literal: bool = False                               # 절 속 말이 이 태그의 대표 한국어 이름([…] · <…>)
    ko_strong: bool = False
    en_strong: bool = False
    why: list[str] = field(default_factory=list)       # kw:신발한쪽 · phrase:휴대폰보기 · en= · en~
    strong_keys: list[str] = field(default_factory=list)   # 강한 한국어 근거의 키(같은 키가 가리키는 태그는 짝)


class TagFinder:
    """절(한국어) + 영문 추측 -> 후보(점수순). 근거가 **강한지**도 적는다 — 고르기는 그것으로 가른다.

    강한 한국어: 절 전체가 키워드 · 4글자 이상 키워드 · 4글자 이상 사전 구 · 규칙표(관용구·명사).
    강한 영문: 추측이 곧 태그(변형 포함) · 태그 낱말과 추측 낱말이 서로를 다 덮는다(IDF 가중).
    ⚠️ 한국어 부분 구(머리 위 -> on head)가 절 전체를 덮는 영문(glasses on head -> eyewear on head)을 점수로
       이겼다(실측 09-24) — 점수 합이 아니라 '강한 근거' 로 가르는 까닭이다.
    """

    def __init__(self, tools: TagTools):
        self.tools = tools
        n = max(1, len({t for tags in tools.word_index.values() for t in tags}))
        self._n_tags = n

    def usable(self, tag: str) -> bool:
        if not tag or len(tag) <= 2 or not re.search(r"[a-z]{2}", tag) or _EMOTICON.match(tag) or _META.search(tag) or _PEOPLE.match(tag):
            return False
        info = self.tools.info(tag) or {}
        if str(info.get("_named_entity_category") or info.get("_cat") or "") in ("artist", "character",
                                                                                 "copyright", "e621"):
            return False
        if self.tools.role(tag) == "population" or int(self.tools.count(tag) or 0) < 50:
            return False
        return bool(str(info.get("description") or "").strip())

    def _idf(self, word: str) -> float:
        return math.log((self._n_tags + 1) / (len(self.tools.word_index.get(word, ())) + 1))

    def en_cover(self, en: str, tag: str) -> float:
        """영문 추측과 태그 이름이 서로를 얼마나 덮나(0~1, IDF 가중). 1 = 서로 완전히 설명한다."""
        q = [_expand(w) for w in _words(en)]
        t = _words(tag)
        if not q or not t:
            return 0.0
        t_sets = [en_stems(w) for w in t]
        t_total = sum(self._idf(w) for w in t) or 1.0
        t_cov = sum(self._idf(w) for w, ts in zip(t, t_sets) if any(ts & qs for qs in q)) / t_total
        q_w = [max(self._idf(s) for s in qs) for qs in q]
        q_cov = sum(w for w, qs in zip(q_w, q) if any(qs & ts for ts in t_sets)) / (sum(q_w) or 1.0)
        return t_cov * math.sqrt(q_cov)

    def rank(self, ko: str, en: str, limit: int = TOP_K) -> list[Candidate]:
        found: dict[str, Candidate] = {}

        def add(tag: str | None, score: float, why: str, *, ko_key: str | None = None, en_strong: bool = False) -> None:
            name = self.tools.canonical(tag) if tag else None
            if not name or score <= 0 or not self.usable(name):
                return
            c = found.setdefault(name, Candidate(name, posts=int(self.tools.count(name) or 0)))
            src = why.split(":")[0]
            c.score += score * (0.3 if any(w.split(":")[0] == src for w in c.why) else 1.0)
            c.why.append(why)
            if ko_key is not None:
                c.ko_strong = True
                c.strong_keys.append(ko_key)
            c.en_strong = c.en_strong or en_strong

        ka = self.tools.analyze(ko) if ko else None
        if ka is not None:
            for key, tag in (getattr(ka, "phrases", {}) or {}).items():
                add(tag, 6, f"phrase:{key}", ko_key=key if len(key) >= 4 else None)
            viewer = getattr(ka, "viewer", []) or []
            for tag in getattr(ka, "specific", []) or []:
                # 시청자 규칙(나를 째려봄 -> looking at viewer)은 절의 뜻(glaring)과 자리를 다투지 않는다 — add_viewer 가 덧붙인다
                if tag not in (getattr(ka, "phrases", {}) or {}).values() and tag not in viewer:
                    add(tag, 5, "rule", ko_key="rule")
            for tag in getattr(ka, "verb_tags", []) or []:
                add(tag, 4, "verb")
        c = compact(ko)
        literal_hits: set[str] = set()
        for n in range(min(len(c), 14), 1, -1):
            for s in range(0, len(c) - n + 1):
                key = c[s:s + n]
                tags = self.tools.keyword_tags(key)
                if not tags:
                    continue
                whole = n == len(c)
                weight = 7 if whole else (5 if n >= 4 else (3 if n == 3 else 1.5))
                for tag in tags[:3]:
                    add(tag, weight, f"kw:{key}", ko_key=key if (whole or n >= 4) else None)
                    if (whole or n >= 4) and key in own_names(self.tools.info(tag) or {}, self.tools.name_claims,
                                                              self.tools.label_uses):
                        literal_hits.add(tag)
        if en:
            for v in _en_variants(en):
                name = self.tools.canonical(v)
                if name:
                    add(name, 7, "en=", en_strong=True)
                    break
            pool: set[str] = set()
            for w in _words(en):
                for s in _expand(w):
                    pool |= self.tools.word_index.get(s, set())
            scored = sorted(((self.en_cover(en, t), t) for t in pool),
                            key=lambda x: (-x[0], -int(self.tools.count(x[1]) or 0)))
            for cover, tag in scored[:12]:
                add(tag, 6 * cover, "en~", en_strong=cover >= 0.999)
        if ko:
            nouns = self.tools.nouns(ko)
            for tag in self.tools.fuzzy(ko):
                kw = compact((self.tools.info(tag) or {}).get("keywords_kr") or "")
                if any(n in kw for n in nouns):          # '오는' -> incoming 같은 헛것을 막는다
                    add(tag, 1, "fuzzy")
        for name, cand in found.items():
            cand.literal = name in literal_hits
        ranked = sorted(found.values(), key=lambda x: (-x.score, -int(self.tools.count(x.tag) or 0)))
        return ranked[:limit]


def angle_label(info: dict[str, Any]) -> str:
    """keywords_kr 의 <…>(붙여 쓴 꼴). 흔히 윗분류(<신발> · <헤어스타일>), 가끔 그 태그의 이름(<도야가오>)."""
    items = [x.strip() for x in str(info.get("keywords_kr") or "").split(",") if x.strip()]
    angle = next((x for x in items if x.startswith("<") and x.endswith(">")), None)
    return compact(angle.strip("<>")) if angle else ""


def declared_names(info: dict[str, Any]) -> set[str]:
    """태그가 **밝힌** 제 이름 — [이름] · '<primary>:이름' · 첫 일반 키워드(붙여 쓴 꼴). <라벨> 은 뺀다(흔히 윗분류)."""
    items = [x.strip() for x in str(info.get("keywords_kr") or "").split(",") if x.strip()]
    out: set[str] = set()
    for x in items:
        m = re.match(r"<primary>\s*:\s*(.+)$", x)
        if m:
            out.add(compact(m.group(1)))
        elif x.startswith("[") and x.endswith("]"):
            out.add(compact(x.strip("[]")))
    plain = next((x for x in items if not x.startswith(("<", "[")) and ":" not in x), None)
    if plain:
        out.add(compact(plain))
    return {x for x in out if x}


def own_names(info: dict[str, Any], name_claims: Callable[[str], int] = lambda _l: 1,
              label_uses: Callable[[str], int] = lambda _l: 2) -> set[str]:
    """태그의 제 이름 — 밝힌 이름 + <라벨>(단 **그 태그만** 그 라벨을 쓰고, **다른 태그가 그 말을 이름으로 밝히지 않았을 때**).
    ⚠️ <…> 를 곧 이름으로 보면 quad tails(<트윈테일>)가 '트윈테일' 의 제 이름이 되어 골라졌다(실측 09-24) —
       트윈테일은 twintails 가 밝힌 이름이다. <신발> 은 여러 태그가 쓰는 분류다. doyagao 의 <도야가오> 만 제 이름이다."""
    out = declared_names(info)
    label = angle_label(info)
    if label and label not in out and int(name_claims(label) or 0) == 0 and int(label_uses(label) or 0) <= 1:
        out.add(label)
    return out


def _en_variants(term: str) -> list[str]:
    from core.assist_v2 import en_variants

    return en_variants(term)


# ── 고르기 ─────────────────────────────────────────────────────────────────


@dataclass
class Detail:
    owner: int                  # 0 = 장면, k = k번째 캐릭터
    ko: str                     # 절(요청의 한국어)
    en: str                     # 영문 추측("" = 없음)
    candidates: list[Candidate] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    via: str = ""               # both | korean | english | model | none
    dup: list[str] = field(default_factory=list)          # 이미 들어간 태그(외모 · 관계 동작 · 같은 칸)
    ask: list[Candidate] = field(default_factory=list)   # 모델에 보일 후보(엇갈리거나 둘 다 약할 때)


def decide(detail: Detail, taken: Iterable[str] = ()) -> Detail:
    """강한 근거로 가른다. 한국어·영문이 같은 태그면 그것 · 한쪽만 강하면 그쪽 · 엇갈리거나 둘 다 약하면 모델에 묻는다.
    같은 한국어 키워드가 함께 가리키는 태그(도야가오 -> doyagao · smug)는 둘 다 넣는다 — 사전이 같은 말로 묶은 것."""
    taken = set(taken)
    cands = detail.candidates
    if taken and any(c.ko_strong and c.tag in taken for c in cands):
        # 같은 절의 다른 추측이 한국어 근거로 이미 골랐다 — 이 추측은 제 영문 근거로만(트윈테일이 휘날림 -> floating hair)
        eng = next((c for c in cands if c.en_strong and c.tag not in taken), None)
        detail.tags, detail.via = ([eng.tag], "english") if eng is not None else ([], "none")
        return detail
    kos = [c for c in cands if c.ko_strong]
    ens = [c for c in cands if c.en_strong]
    both = [c for c in cands if c.ko_strong and c.en_strong]
    literal = [c for c in kos if c.literal]
    if literal:                                  # 사용자가 쓴 말이 그 태그의 이름(도야가오 -> doyagao, smug 가 아니라)
        primary = literal[0]
        detail.via = "both" if primary.en_strong else "korean"
    elif both:
        primary, detail.via = both[0], "both"
    elif kos and ens and set(_words(kos[0].tag)) < set(_words(ens[0].tag)):
        # 영문 쪽이 한국어 쪽을 품은 더 구체적인 태그(on head ⊂ eyewear on head) — 묻지 않고 구체적인 것
        primary, detail.via = ens[0], "english"
    elif kos and ens:
        order = [ens[0], kos[0]] + [c for c in cands if c.tag not in (ens[0].tag, kos[0].tag)]
        detail.ask, detail.via = order[:TOP_K], "ask"
        return detail
    elif kos:
        primary, detail.via = kos[0], "korean"
    elif ens:
        primary, detail.via = ens[0], "english"
    else:
        ask = [c for c in cands if c.score >= MIN_ASK_SCORE][:TOP_K]
        detail.ask, detail.via = ask, ("ask" if ask else "none")
        return detail
    spec = next((c for c in ens if c.tag != primary.tag and set(_words(primary.tag)) < set(_words(c.tag))), None)
    if spec is not None:
        # 한국어가 제 이름으로 준 태그라도, 영문이 그것을 품은 더 구체적인 태그면 그쪽(머리 위에 = on head ⊂ eyewear on head)
        primary, detail.via = spec, "english"
    detail.tags = [primary.tag]
    if primary.ko_strong:
        # 같은 한국어 키워드가 함께 가리키는 짝(도야가오 -> smug) — 영문도 그렇다고 하거나 드문 태그를 받칠 때만.
        # ⚠️ 무조건 붙이면 흔한 twintails 에 tied hair 가 붙었다(실측 09-24)
        mate = next((c for c in kos if c.tag != primary.tag and set(c.strong_keys) & set(primary.strong_keys)
                     and (c.en_strong or 0 < rare_count(primary) < RARE_POSTS)), None)
        if mate is not None:
            detail.tags.append(mate.tag)
    return detail


def rare_count(c: Candidate) -> int:
    return int(c.posts or 0)


def apply_choice(detail: Detail, choice: str | None) -> Detail:
    if choice:
        detail.tags, detail.via = [choice], "model"
    else:
        detail.tags, detail.via = [], "none"
    detail.ask = []
    return detail


def add_companions(detail: Detail, companions: Iterable[dict[str, Any]]) -> Detail:
    """규칙표의 짝(single shoe + 바닥·떨어 -> unworn shoes) — 절이 그 말을 품을 때만."""
    for rule in companions or ():
        tag, add = rule.get("tag"), rule.get("add")
        if tag in detail.tags and add and add not in detail.tags \
                and any(w in detail.ko for w in rule.get("when") or ()):
            detail.tags.append(add)
    return detail


def add_viewer(detail: Detail, tags: Iterable[str]) -> Detail:
    """1인칭 목적어(나를 째려봄)는 그림을 보는 사람 쪽 태그(looking at viewer)를 **덧붙인다** — 한 절 한 태그 자리를 두고
    절의 뜻(glaring)과 다투면 표정이 밀려났다(09-24 실측). 절마다 한 번만 부른다(같은 절의 다른 영문 추측에는 안 붙인다)."""
    tags = [t for t in tags or () if t and t not in detail.tags]
    if tags and not detail.tags:
        detail.via = "korean"
    detail.tags.extend(tags)
    return detail


def interaction_tag(ka: Any, role: Callable[[str], str | None], generic: Iterable[str] = (),
                    poses: Iterable[str] = ()) -> str | None:
    """인물 사이 동작 태그 — 동사에서 나온 사전 구(공주안기) 중 event_core 먼저, 없으면 동사 사전의 event_core.
    자세·흔한 것(sleeping·smile)은 한 사람의 상태라 관계로 쓰지 않는다(assist_v2.merge 와 같은 규칙)."""
    generic, poses = set(generic), set(poses)
    tags = [t for t in getattr(ka, "verb_phrases", None) or [] if t not in generic and t not in poses]
    act = next((t for t in tags if role(t) == "event_core"), None) or next(iter(tags), None)
    if act is None:
        act = next((t for t in getattr(ka, "verb_tags", None) or []
                    if t not in generic and t not in poses and role(t) == "event_core"), None)
    return act


def dedupe(details: list[Detail], relation: Relation | None, characters: list[ComposeCharacter],
           info: Callable[[str], dict[str, Any]] = lambda _t: {}) -> list[Detail]:
    """같은 칸에 같은 태그는 한 번 · 관계 동작(메인에 이미 있다)과 그 캐릭터의 이름·작품·외모는 다시 넣지 않는다."""
    skip = {relation.action} if relation is not None else set()
    own = {k: {c.tag, c.work or "", *c.appearance} for k, c in enumerate(characters, 1)}
    seen: set[tuple[int, str]] = set()
    for d in details:
        keep = []
        for tag in d.tags:
            key = (place_of(tag, d.owner, info(tag)), tag)
            if tag in skip or key in seen or tag in own.get(d.owner, ()):
                d.dup.append(tag)
                continue
            seen.add(key)
            keep.append(tag)
        if not keep and d.dup:
            # 고른 것이 이미 들어가 있으면(트윈테일 = 외모) 그 절의 영문 근거로 한 번 더(휘날림 -> floating hair)
            alt = next((c.tag for c in d.candidates if c.en_strong and c.tag not in d.dup and c.tag not in skip
                        and c.tag not in own.get(d.owner, ())
                        and (place_of(c.tag, d.owner, info(c.tag)), c.tag) not in seen), None)
            if alt is not None:
                seen.add((place_of(alt, d.owner, info(alt)), alt))
                keep.append(alt)
        d.tags = keep
    return details


# 몸에 걸치지 않은 물건(바닥의 신발) — 캐릭터 줄에서 나왔어도 메인(장면)에 둔다
_OFF_BODY = re.compile(r"^unworn\b|\bon (?:the )?(?:floor|ground)\b")
_SCENE_GROUPS = frozenset({"Location_Background", "장소"})


def place_of(tag: str, owner: int, info: dict[str, Any] | None = None) -> int:
    if owner == 0 or _OFF_BODY.search(tag) or str((info or {}).get("group") or "") in _SCENE_GROUPS:
        return 0
    return owner


# ── 외모 ─────────────────────────────────────────────────────────────────


def appearance_tags(entry: dict[str, Any] | None, *, color_min: float = 60.0, feature_min: float = 50.0,
                    max_colors: int = 2, max_features: int = 3) -> list[str]:
    """character_analysis 항목 -> 외모 태그(최빈 머리색·눈색 · 머리 모양 등). 비율이 문턱 넘는 것만."""
    if not isinstance(entry, dict):
        return []
    out: list[str] = []

    def take(rows: Any, minimum: float, limit: int) -> None:
        picked = [str(r.get("tag")) for r in (rows or []) if isinstance(r, dict) and r.get("tag")
                  and float(r.get("pct") or 0) >= minimum]
        out.extend(picked[:limit])

    take(entry.get("personal_color"), color_min, max_colors)
    take(entry.get("characteristics"), feature_min, max_features)
    return list(dict.fromkeys(out))


# ── 조립 ─────────────────────────────────────────────────────────────────


@dataclass
class ComposeCharacter:
    ko: str
    tag: str
    gender: str | None = None
    alts: list[str] = field(default_factory=list)
    work: str | None = None                 # 작품 태그(hololive)
    appearance: list[str] = field(default_factory=list)


@dataclass
class Relation:
    source: int                             # 캐릭터 차례(1..)
    target: int
    action: str                             # 동작 태그(princess carry)
    ko: str = ""                            # 요청의 말(공주안기)


def assemble(*, people: list[str], characters: list[ComposeCharacter], relation: Relation | None,
             details: list[Detail], info: Callable[[str], dict[str, Any]] = lambda _t: {}) -> dict[str, Any]:
    """메인 = 인원 + 동작 + 장면 것(바닥의 신발 포함). 캐릭터 = girl/boy · 이름 · 작품 · 외모 · source#/target# · 그 사람 것."""
    main: list[str] = list(people)
    if relation is not None:
        main.append(relation.action)
    per: dict[int, list[str]] = {k: [] for k in range(1, len(characters) + 1)}
    for d in details:
        for tag in d.tags:
            where = place_of(tag, d.owner, info(tag))
            (main if where == 0 or where not in per else per[where]).append(tag)
    out_chars = []
    for k, ch in enumerate(characters, 1):
        parts = [p for p in ([ch.gender] if ch.gender in ("girl", "boy") else []) + [ch.tag] if p]
        if ch.work:
            parts.append(ch.work)
        parts += ch.appearance
        if relation is not None and ch.tag:
            if relation.source == k:
                parts.append(f"source#{relation.action}")
            if relation.target == k:
                parts.append(f"target#{relation.action}")
        parts += per.get(k, [])
        out_chars.append({"prompt": ", ".join(dict.fromkeys(p for p in parts if p)), "ko": ch.ko,
                          "alts": list(ch.alts)})
    return {"main": ", ".join(dict.fromkeys(t for t in main if t)), "characters": out_chars}


# ── 설명(틀) ─────────────────────────────────────────────────────────────


def near_miss(detail: Detail, info: Callable[[str], dict[str, Any]],
              keyword_tags: Callable[[str], list[str]] = lambda _k: [],
              count: Callable[[str], int] = lambda _t: 0) -> dict[str, str] | None:
    """헷갈리기 쉬운 태그(uneven legwear ↔ mismatched legwear) — '이건 뜻이 달라서 뺐다'.

    헷갈린다 = 한국어 키워드의 **낱말을 나누고**(언밸런스) **세부 분류가 같고**(legwear) 게시물이 고른 것의 10% 넘는
    실제 경쟁자. ⚠️ 후보 목록에서 고르면 영문 낱말만 나누는 것(uneven eyes · phone)·윗말(shoes · holding)이 나왔다(실측 09-24)."""
    if not detail.tags:
        return None
    chosen = detail.tags[0]
    mine = info(chosen) or {}
    sub_group = str(mine.get("subgroup") or "")
    if not sub_group:
        return None
    words: list[str] = []
    for kw in str(mine.get("keywords_kr") or "").split(","):
        for w in kw.strip().strip("<>[] ").split():
            if len(w) >= 2 and w not in words:
                words.append(w)
    floor = 0.1 * int(count(chosen) or 0)
    for tag in dict.fromkeys(t for w in words for t in keyword_tags(compact(w))):
        if tag in detail.tags or tag == chosen:
            continue
        other = info(tag) or {}
        desc = str(other.get("description") or "").strip()
        if desc and str(other.get("subgroup") or "") == sub_group and int(count(tag) or 0) >= floor:
            return {"tag": tag, "desc": _short(desc)}
    return None


def _short(text: str, limit: int = 60) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def explain(*, characters: list[ComposeCharacter], relation: Relation | None, details: list[Detail],
            count: Callable[[str], int], info: Callable[[str], dict[str, Any]],
            cooccur: dict[str, int] | None = None, anchor_posts: int = 0,
            keyword_tags: Callable[[str], list[str]] = lambda _k: []) -> dict[str, Any]:
    """사람이 읽는 설명 — 모두 도구가 준 사실(게시물 수 · 뜻 · 공출현)을 틀에 끼운 것이다."""
    cooccur = cooccur or {}
    name = {k: ch.ko for k, ch in enumerate(characters, 1)}
    notes: list[str] = []
    if relation is not None:
        src, dst = name.get(relation.source, ""), name.get(relation.target, "")
        act = f"{relation.ko}({relation.action})" if relation.ko else relation.action
        notes.append(f"{src} → {dst} : {act} — 같은 동작 태그를 두 캐릭터 칸에 source#/target# 짝으로 넣어 "
                     f"누가 하고 누가 받는지를 고정했습니다.")
    moved = [t for d in details for t in d.tags if d.owner and place_of(t, d.owner, info(t)) == 0]
    scene_bits = "인원·동작" + ("·몸에 걸치지 않은 물건(" + ", ".join(moved) + ")" if moved else "")
    notes.append(f"메인에는 장면 전체({scene_bits})를, 캐릭터 칸에는 그 사람에게 붙는 것(표정·손에 든 것·옷차림)을 넣었습니다.")
    if any(ch.appearance for ch in characters):
        why = "인물들을 서로 가르는 데 씁니다" if len(characters) > 1 else "캐릭터를 또렷하게 하는 데 씁니다"
        notes.append(f"외모 태그(머리색·눈색·머리 모양)는 NAIA 캐릭터 분석의 최빈 특징입니다 — {why}.")
    rows: list[dict[str, Any]] = []
    alts: list[dict[str, str]] = []
    missed: list[dict[str, str]] = []
    tagged = {(d.owner, d.ko) for d in details if d.tags or d.dup}   # 한 절의 추측 중 하나라도 태그가 되면 찾은 것
    for d in details:
        owner = name.get(d.owner, "장면") if d.owner else "장면"
        for tag in d.dup:
            if not any(r["tag"] == tag and r["ko"] == d.ko for r in rows):
                rows.append({"who": owner, "ko": d.ko, "tag": tag, "posts": int(count(tag) or 0),
                             "desc": _short((info(tag) or {}).get("description") or ""), "slot": "이미 들어감",
                             "via": d.via, "with": cooccur.get(tag)})
        if not d.tags:
            if (d.owner, d.ko) not in tagged and not any(m["ko"] == d.ko and m["who"] == owner for m in missed):
                missed.append({"who": owner, "ko": d.ko, "guess": d.en})
            continue
        for tag in d.tags:
            where = place_of(tag, d.owner, info(tag))
            rows.append({"who": owner, "ko": d.ko, "tag": tag, "posts": int(count(tag) or 0),
                         "desc": _short((info(tag) or {}).get("description") or ""),
                         "slot": "메인" if where == 0 else name.get(where, owner), "via": d.via,
                         "with": cooccur.get(tag)})
        miss = near_miss(d, info, keyword_tags, count)
        if miss and len(alts) < MAX_NOTES:
            alts.append({"chosen": d.tags[0], **miss})
    tips: list[str] = []
    rare = [r for r in rows if r["posts"] and r["posts"] < RARE_POSTS]
    for r in rare[:2]:
        tips.append(f"{r['tag']} 가 약하게 나오면 1.2::{r['tag']}:: 처럼 강조하세요(게시물 {r['posts']:,}건).")
    if relation is not None:
        tips.append(f"역할이 뒤바뀌면 두 칸의 source#/target# 을 1.2::source#{relation.action}:: 처럼 강조하세요.")
    evidence = None
    if relation is not None and anchor_posts:
        evidence = {"anchor": relation.action, "posts": int(anchor_posts),
                    "with": [{"tag": t, "posts": n} for t, n in cooccur.items() if n is not None]}
    return {"notes": notes, "rows": rows, "alts": alts, "missed": missed, "tips": tips, "evidence": evidence,
            "syntax": "캐릭터 칸의 source#동작 · target#동작 은 앞에 붙이는 표기입니다(#source 가 아님). "
                      "같은 동작을 양쪽에 짝으로 넣어야 방향이 고정됩니다."}
