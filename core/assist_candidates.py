"""Assist v2 한 줄 경로의 후보 찾기 + 모델이 고르기 (2026-09-25).

영문 추측을 철자로만 태그에 맞추면 바꿔 말한 것(observing) · 맥락(흩날리는 벚꽃) · 두 뜻(칠판에 글씨 쓰기)을 놓친다
(설계 17·18절, 실측: 놓친 것의 70% 가 '영문은 있는데 태그가 안 맞음'). 사용자 결정(09-25): 한국어 사전 전처리 +
도구가 찾은 후보에서 모델이 정답을 고르게 한다.

1) 한국어 사전 전처리 — NAIA 한국어 키워드를 원형(명사·동사 줄기, 품사 갈래 포함)으로 바꿔 두고(약 5만 개, Kiwi 약 3초 ·
   창을 열 때 뒤에서), 요청 조각의 원형과 겹치는 키워드의 태그를 후보로 낸다.
   뒷모습 -> from behind · 흩날리는 -> falling petals(키워드 '흩날리는 꽃잎').
2) 모델 항목이 영문으로 **정확히** 안 풀릴 때 영문 낱말 묶음(classroom window -> classroom + window) 중 한국어가
   **확인해 주는** 것은 그대로 싣고(keep), 남은 뜻이 있으면 후보를 모아 E2B 에게 **한 조각씩 번호로** 고르게 한다 —
   0 = 없음(문법으로 목록 밖을 못 쓴다), 앞 조각의 답을 넘기며 차례로(사용자 제안 09-25). 모델이 아예 안 낸 요청
   명사도 제 이름인 태그가 있으면 묻는다.
지금 잘 풀리는 항목(영문 정확 일치 · 한국어 정확 키워드 · 사전 구)은 그대로 둔다. 고를 것이 없으면 모델을 부르지 않는다.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from core.assist_korean import compact

CONTENT = ("NNG", "NNP", "VV", "VA", "XR")
# 원형으로 함께 세는 조각 — 영문·숫자·한자·관형사. 빼고 셌더니 'UTX교복' · 'DDLC교복' · '어떤교복' 이 '교복' 과 똑같은
# 원형이 되어 흠뻑 젖은 교복에 tsukumihara academy uniform (fate/extra ccc)를 골랐다(holdout2 09-25)
MARKS = ("SL", "SN", "SH", "MM")
MAX_ASKS = 8                 # 한 요청에서 묻는 조각 수(조각마다 모델 한 번, GPU 약 0.1초)
MAX_CANDIDATES = 6
MAX_KEY_LEN = 24             # 붙여 쓴 키워드 길이 — 설명 문장 같은 긴 키워드는 원형 색인에 넣지 않는다

# 고르기 형식(09-25 실측, 같은 후보 152개): 한 번에 모든 조각을 목록으로 받으면 E2B 가 '없음' 을 거의 안 썼다(6번) —
# 쓰다(wearing) -> writing · 사이 -> saiga-12 · 코트(court) -> blue coat 를 그대로 골랐다. 사용자 제안대로 **한 조각씩
# 번호로 단답**(0 = 없음), 앞에서 고른 것을 넘기며 차례로 물었더니 없음 34번 · 엉뚱한 것 102 -> 79 · 호출 시간 합 절반.
# (안긴 목록 [[..],[]] 은 E2B 가 전부 [] 로 답했다.)
CHOOSE_SYSTEM = ("다음 중 이 문장 내에서 가장 맞을 확률이 높은 단어를 고르십시오. 답은 1, 2, 3, 4와 같이 단답하고, "
                 "사유는 설명하지 마십시오. 맞는 것이 없으면 0.")
_EN_STOP = frozenset({"a", "an", "the", "of", "on", "in", "at", "to", "for", "with", "and", "by", "from", "her", "his",
                      "their", "own", "is", "are", "day", "into", "onto", "over", "under", "out", "up", "down",
                      "while"})
# 묻지 않는 틀 명사 — 장면의 틀이지 그림의 것이 아니다(표정 -> expressionless · 사이 -> saiga-12 · 아래 -> under shot 을
# 골랐다, 09-25). 모델이 안 낸 요청 명사와 모델 항목의 남은 뜻 둘 다. 한 음절(위·앞·옆)은 이미 묻지 않는다.
GENERIC_NOUNS = frozenset({"표정", "사이", "모습", "장면", "구도", "느낌", "분위기", "상태", "자세", "동작", "포즈", "얼굴",
                           "주변", "근처", "가운데", "순간", "정도", "부분", "전체", "배경", "시간", "그림", "사진",
                           "아래", "한쪽", "양쪽", "모양", "고정", "방향", "쪽", "위쪽", "아래쪽", "옆쪽", "앞쪽", "뒤쪽",
                           "안쪽", "바깥", "끝", "가장자리", "중간", "손가락", "소매"})


_FUNCTION = ("J", "E", "VX")        # 조사·어미·보조 용언 — 키워드의 나머지가 이것뿐이면 '깨끗' 하다
# 같은 뜻의 보는 동사 — 사전은 '창밖 보기'(looking outside), 요청은 '창밖을 쳐다보는' 이었다(09-25). 원형을 바꾸지 않고
# '보' 를 덧붙인다(빤히 쳐다보기 -> staring 도 그대로 걸리게). 올려다보·내려다보·돌아보는 방향이 뜻이라 넣지 않는다.
_SEE = frozenset({"쳐다보", "바라보", "지켜보"})


def lemma(form: str, tag: str) -> str:
    """원형 + 품사 갈래 — 날(명사, 비 오는 날)과 날(동사, 날기 -> flying)이 같은 원형으로 걸렸다(09-25).
    형용사(A)는 동사와 가른다 — 남은 뜻이 형용사뿐(낮은 천장의 '낮')이면 묻지 않는다."""
    kind = ("N" if tag.startswith("NN") else "V" if tag.startswith("VV") else "A" if tag.startswith("VA")
            else "S" if tag in MARKS else "R")
    return f"{form.lower()}/{kind}"


def lemma_form(lem: str) -> str:
    return lem.rsplit("/", 1)[0]


def neighbours(tokens: Iterable[tuple[str, str]]) -> frozenset[tuple[str, str]]:
    """요청에서 바로 붙은 내용어 쌍(조사·어미는 건너뛴다) — 양손으로 브이 -> (양손, 브이) · (브이, 양손)."""
    words = [f.lower() for f, t in tokens if t.startswith(CONTENT) or t in MARKS]
    return frozenset(p for a, b in zip(words, words[1:]) for p in ((a, b), (b, a)))


def lemmas_of(tokens: Iterable[tuple[str, str]]) -> set[str]:
    out: set[str] = set()
    for f, t in tokens:
        if t.startswith(CONTENT) or t in MARKS:
            out.add(lemma(f, t))
            if f in _SEE and t.startswith("VV"):
                out.add("보/V")
    return out


def clean_key(tokens: list[tuple[str, str]]) -> bool:
    """내용 형태소로 시작하고 나머지는 조사·어미·보조 용언뿐인 키워드(턱괴기 · 창밖보기). 음차 키워드는 대개 여기서
    갈린다(에비 = 에/조사 + 비)."""
    return bool(tokens) and tokens[0][1].startswith(CONTENT) \
        and all(t.startswith(CONTENT) or t.startswith(_FUNCTION) or t in MARKS for _f, t in tokens)


class KeywordLemmaIndex:
    """NAIA 한국어 키워드(일반 태그의 것만) -> 원형 집합, 원형 -> 키워드 역색인.

    ``tokenize`` 는 Kiwi 날것(이름 붙이기 없는 것)이어야 한다 — 이름 붙이기까지 하면 5만 개에 52초가 들었다(실측 09-25).
    """

    def __init__(self, keywords: dict[str, list[tuple[str, int, str]]],
                 tokenize: Callable[[str], list[tuple[str, str]]]):
        self.keywords = keywords
        self.tokenize = tokenize
        self.by_lemma: dict[str, set[str]] = {}
        self.lemmas: dict[str, frozenset[str]] = {}
        self.clean: dict[str, bool] = {}
        self.odd: dict[str, bool] = {}               # 주격·목적격·보조사로 끝나는 키워드 — 음차(사이가 -> saiga-12)
        self.ready = False
        self.seconds = 0.0
        self._lock = threading.Lock()

    def build(self) -> None:
        import time

        with self._lock:
            if self.ready:
                return
            started = time.perf_counter()
            for key, rows in self.keywords.items():
                if len(key) > MAX_KEY_LEN or not any(not cat for _t, _n, cat in rows):
                    continue
                toks = self.tokenize(key)
                lem = frozenset(lemmas_of(toks))
                if not lem:
                    continue
                self.lemmas[key] = lem
                self.clean[key] = clean_key(toks)
                self.odd[key] = toks[-1][1] in ("JKS", "JKO", "JKC", "JX")
                for w in lem:
                    self.by_lemma.setdefault(w, set()).add(key)
            self.seconds = round(time.perf_counter() - started, 2)
            self.ready = True

    def find(self, want: Iterable[str]) -> list[tuple[str, float, float]]:
        """요청 조각의 원형과 겹치는 키워드 -> [(키, 정밀, 재현)]. 정밀 = 키워드 원형 중 조각에 있는 비율,
        재현 = 조각 원형 중 키워드에 있는 비율."""
        want = set(want)
        if not want:
            return []
        if not self.ready:
            self.build()
        keys: set[str] = set()
        for w in want:
            keys |= self.by_lemma.get(w, set())
        out = []
        for key in keys:
            lem = self.lemmas[key]
            hit = len(lem & want)
            out.append((key, hit / len(lem), hit / len(want)))
        return out


@dataclass
class Ask:
    """모델에게 고르게 할 한 조각."""
    ko: str                                  # 요청 조각(모델 항목의 ko, 또는 모델이 안 낸 요청 명사)
    en: str = ""                             # 모델 영문 추측("" = 모델이 안 냈다)
    who: int = 0                             # 인물 번호(0 = 장면)
    fallback: list[str] = field(default_factory=list)       # 고르기가 없을 때(모델 없음·실패) 예전 결과
    keep: list[str] = field(default_factory=list)           # 한국어가 확인한 영문 낱말 묶음 — 고르기와 상관없이 싣는다
    candidates: list[tuple[str, str]] = field(default_factory=list)  # (태그, 한국어 뜻)
    source: str = "item"                     # item(모델 항목) | extra(모델이 안 낸 요청 명사)
    picks: list[str] | None = None           # 모델이 고른 것([] = 없음) · None = 고르기 없음(예전 결과로)

    def chosen(self) -> list[str]:
        """실을 태그 — 고르기가 없으면 예전 결과, 있으면 확인된 묶음 + 고른 것."""
        return list(self.fallback) if self.picks is None else list(dict.fromkeys(self.keep + self.picks))


def korean_matches(index: KeywordLemmaIndex, want: set[str], lookup: Callable[[str], list[tuple[str, int]]], *,
                   strict: bool, nouns: Iterable[str] = (),
                   near: frozenset[tuple[str, str]] = frozenset()) -> list[tuple[str, float, frozenset[str], int]]:
    """원형이 겹치는 키워드의 태그 -> [(태그, 점수, 겹친 원형, 키워드 원형 수)]. strict 면 키워드 원형이 전부 조각 안에 있어야(뒷모습 =
    뒷모습). 아니면 조각이 키워드에 다 들어 있고 키워드가 한 원형만 더 가진 것도 — **동사가 맞고** 그 한 원형이 (맞은 말
    말고) 요청 명사와 음절을 나눌 때(벚꽃이 흩날리는 -> 흩날리는 꽃잎), 또는 더 붙은 말이 요청에서 맞은 말과 **바로 붙어**
    있을 때(near: 양손으로 브이 -> 양손 브이 -> double v). 안 나누는 것까지 받았더니 '나를 쳐다보는' 에 가슴 쳐다보기 ->
    looking at breasts 가, 명사끼리 음절만 보고 받았더니 체육관 코트에 white coat(화이트'트' ~ 코'트') · 창문 덮개에
    canopy (aircraft)(멀리 떨어진 '비행기 좌석' 의 비행기)가 왔다(09-25).

    한 음절 원형만 겹친 키워드는 그 원형 그대로(책 · 비)거나 '원형+기'(읽기 · 눕기)이거나, 원형 둘 이상이 전부 맞고
    깨끗한 키워드(턱괴기)일 때만 받는다 — 음차·동형이의 키워드가 걸렸다: 오지 -> orgy · 에비 -> shrimp · 내비 -> netnavi
    (실측 09-25). 비와 -> biwa lute(비+오)는 여기로 못 막는다 — 영문 묶음(rain)이 먼저 풀려 묻지 않게 된다.
    주격·목적격·보조사로 끝나는 키워드(사이가 -> saiga-12)는 음차라 받지 않는다. 키워드의 둘째 태그는 첫째의 4분의 1
    이상 쓰일 때만(앉기 -> sitting 다음의 sitting on rock 을 모델이 골랐다)."""
    nouns = [n for n in nouns if n]
    out: list[tuple[str, float, frozenset[str], int]] = []
    for key, precision, recall in index.find(want):
        if index.odd.get(key):
            continue
        lem = index.lemmas[key]
        hit = lem & want
        if all(len(lemma_form(h)) == 1 for h in hit):
            if len(lem) == 1:
                only = lemma_form(next(iter(lem)))
                if key not in (only, only + "기"):
                    continue
            elif hit != lem or not index.clean.get(key):
                continue
        extra = lem - want
        if extra:
            others = [n for n in nouns if n not in {lemma_form(h) for h in hit}]
            verb_ok = any(h.endswith("/V") for h in hit) \
                and any(set(lemma_form(e)) & set(n) for e in extra for n in others)
            near_ok = any((lemma_form(h), lemma_form(e)) in near for h in hit for e in extra)
            if strict or recall < 0.999 or len(extra) > 1 or not (verb_ok or near_ok):
                continue
        rows = lookup(key)[:2]
        if len(rows) == 2 and rows[1][1] < rows[0][1] * 0.25:
            rows = rows[:1]
        for rank, (tag, _count) in enumerate(rows):
            out.append((tag, 2.0 * precision + recall - 0.1 * rank, frozenset(hit), len(lem)))
    return out


def korean_candidates(index: KeywordLemmaIndex, want: set[str], lookup: Callable[[str], list[tuple[str, int]]], *,
                      strict: bool, nouns: Iterable[str] = (),
                      near: frozenset[tuple[str, str]] = frozenset()) -> list[tuple[str, float]]:
    """korean_matches 를 태그마다 가장 높은 점수로 -> [(태그, 점수)] 점수순."""
    scored: dict[str, float] = {}
    for tag, score, _hit, _size in korean_matches(index, want, lookup, strict=strict, nouns=nouns, near=near):
        if score > scored.get(tag, 0.0):
            scored[tag] = score
    return sorted(scored.items(), key=lambda kv: -kv[1])


def en_words(en: str) -> list[str]:
    return [w for w in "".join(c if c.isalnum() or c in "-'" else " " for c in str(en or "").lower()).split() if w]


def _en_forms(words: list[str]) -> list[str]:
    """낱말 묶음의 쉬운 꼴 바꾸기 — 마지막 낱말만. 짧은 낱말은 자르지 않는다(busy -> bus · bangs -> banging 이
    태그가 됐다, 09-25). 모델 영문 통째 맞추기(en_variants)의 '+ing' 는 쓰지 않는다(gap -> gaping)."""
    head, last = words[:-1], words[-1]
    forms = [" ".join(words)]
    if last.endswith("s") and len(last) > 3:
        forms.append(" ".join(head + [last[:-1]]))
    elif not last.endswith("s"):
        forms.append(" ".join(head + [last + "s"]))
    if last.endswith("ies") and len(last) > 4:
        forms.append(" ".join(head + [last[:-3] + "y"]))
    if last.endswith("y") and len(last) >= 5:
        forms.append(" ".join(head + [last[:-1]]))                  # rainy -> rain
    if last.endswith("ing") and len(last) > 5:
        forms += [" ".join(head + [last[:-3]]), " ".join(head + [last[:-3] + "e"])]
    if len(words) > 1:
        forms.append("".join(words))                                  # twin tails -> twintails
    return list(dict.fromkeys(forms))


def english_parts(en: str, canonical: Callable[[str], str | None]) -> list[tuple[str, tuple[int, int]]]:
    """영문 추측의 낱말 묶음(세·두·한 낱말) 중 태그 이름 그대로인 것 -> [(태그, (시작, 끝))].
    긴 묶음부터, 이미 잡힌 낱말은 다시 쓰지 않는다. 불용어(on · day)로 끝나는 묶음은 없다 — 시작은 된다(on floor)."""
    words = en_words(en)
    used: set[int] = set()
    out: list[tuple[str, tuple[int, int]]] = []
    for size in (3, 2, 1):
        for i in range(len(words) - size + 1):
            span = set(range(i, i + size))
            if used & span or words[i + size - 1] in _EN_STOP:
                continue
            name = next((n for n in (canonical(f) for f in _en_forms(words[i:i + size])) if n), None)
            if name and name not in (t for t, _s in out):
                out.append((name, (i, i + size)))
                used |= span
    return out


def korean_tags(ko: str, *, want: set[str], keyword_tags: Callable[[str], list[str]], index: KeywordLemmaIndex,
                lookup: Callable[[str], list[tuple[str, int]]],
                canonical: Callable[[str], str | None]) -> dict[str, set[str]]:
    """조각의 한국어가 가리키는 태그 -> 그 태그를 가리킨 조각 원형. 두 글자 이상 부분 문자열의 키워드(소파 -> couch,
    원형은 그 문자열에 든 것) + 원형 정확 일치(턱을 괴고 -> 턱괴기 -> hand on own chin).
    영문 낱말 묶음을 '확인' 하는 데만 쓴다 — 모델 영문과 한국어 사전이 둘 다 가리킬 때만 묻지 않고 싣는다."""
    c = compact(ko)
    out: dict[str, set[str]] = {}
    for n in range(min(len(c), 12), 1, -1):
        for s in range(len(c) - n + 1):
            sub = c[s:s + n]
            names = keyword_tags(sub)[:6]
            if not names:
                continue
            hit = {w for w in want if lemma_form(w) in sub}
            for name in names:
                tag = canonical(name)
                if tag:
                    out.setdefault(tag, set()).update(hit)
    for name, _score, hit, _size in korean_matches(index, want, lookup, strict=True):
        tag = canonical(name)
        if tag:
            out.setdefault(tag, set()).update(hit)
    return out


def word_starts(tokens: list[tuple[str, str]], text: str) -> list[bool]:
    """형태소마다 어절 첫머리인가 — Kiwi 가 '구도로' 를 구 + 도로(road)로 잘랐다(09-25). 명사 묶음은 어절 첫머리에서만 연다.
    표면이 안 보이는 형태소(누워 -> 눕)는 첫머리가 아닌 것으로 본다."""
    out: list[bool] = []
    pos = 0
    for form, _tag in tokens:
        at = text.find(form, pos) if form else -1
        out.append(at >= 0 and (at == 0 or not text[at - 1].isalnum()))
        if at >= 0:
            pos = at + len(form)
    return out


def uncovered_units(tokens: list[tuple[str, str]], covered: set[str], stop: set[str], names: set[str],
                    text: str) -> list[tuple[str, set[str]]]:
    """모델 항목과 한국어 층이 다루지 않은 요청 명사 — 이웃한 명사는 한 묶음(버스 정류장 · 밤하늘). [(표면, 원형 집합)].
    명사만 — 모델 영문 없이 맨 동사를 물으면 보이 -> showing 처럼 엉뚱했다. 한 음절 명사만으로 된 묶음은 버린다(위 · 눈)."""
    units: list[tuple[str, set[str]]] = []
    run: list[tuple[str, str]] = []
    starts = word_starts(tokens, text)

    def flush() -> None:
        if run and any(len(f) >= 2 for f, _t in run):
            units.append((" ".join(f for f, _t in run), {lemma(f, t) for f, t in run}))
        run.clear()

    for (form, tag), start in zip(tokens, starts):
        noun = tag in ("NNG", "NNP") and form not in stop and form not in names \
            and lemma(form, tag) not in covered
        if noun and (run or start):
            run.append((form, tag))
        else:
            flush()
    flush()
    return units


def choose_message(text: str, ask: Ask, done: Iterable[str]) -> str:
    """한 조각의 물음 — 문장 · 이미 고른 태그(앞 조각의 답 + 실은 것) · 조각 · 번호 붙인 후보 · 0. 없음."""
    done = list(dict.fromkeys(done))
    lines = [f"문장: {text}", f"이미 고른 태그: {', '.join(done) if done else '없음'}",
             f"조각: {ask.ko} ({ask.en})" if ask.en else f"조각: {ask.ko}"]
    lines += [f"{i}. {tag} = {desc}" for i, (tag, desc) in enumerate(ask.candidates, 1)]
    lines.append("0. 없음")
    return "\n".join(lines)


def choose_grammar(n: int) -> str:
    """0(없음) ~ n 의 번호 하나만 — 목록 밖을 쓸 수 없다."""
    if n < 1:
        raise ValueError("고를 것이 없다")
    return "root ::= " + " | ".join(f'"{i}"' for i in range(n + 1))


def settle_order(forward: list[str] | None, backward: list[str] | None, names: list[str]) -> list[str] | None:
    """정순 답과 역순 답을 합친다 — 같으면 그 답, 둘 다 고른 것이 다르면 도구 순위가 앞선 것(목록 앞), 한쪽만 '없음' 이면
    없음(자신 없음). 역순 답을 못 읽었으면 정순 답. E2B 는 후보가 둘이면 내용과 상관없이 2번을 고르는 때가 있다
    (창밖을 쳐다보기 · 새벽: 순서를 바꾸자 답이 바뀌었다, 09-25) — 순서를 바꿔도 같은 답만 모델의 뜻으로 본다."""
    if forward is None or backward is None:
        return forward
    if forward == backward:
        return forward
    if forward and backward:
        return [t for t in names if t in forward + backward][:1]
    return []


def parse_choice(reply: str | None, names: list[str]) -> list[str] | None:
    """'2' -> [둘째 후보] · '0' -> [] · 못 읽으면 None(고르기 없음 = 예전 결과로)."""
    try:
        n = int(str(reply or "").strip())
    except ValueError:
        return None
    if n == 0:
        return []
    return [names[n - 1]] if 0 < n <= len(names) else None


def agrees(tag: str, en: str) -> bool:
    """태그 이름과 모델 영문이 낱말(앞 네 글자)을 나누나 — rain ~ rainy · hand on own chin ~ chin resting on hand."""
    tw = {w[:4] for w in en_words(tag) if len(w) >= 3 and w not in _EN_STOP}
    ew = {w[:4] for w in en_words(en) if len(w) >= 3 and w not in _EN_STOP}
    return bool(tw & ew)


def order_candidates(scored: dict[str, float], en: str) -> list[str]:
    """점수순 — 동점은 모델 영문과 맞는 것 먼저, 그다음 이름순. 집합 순서로 두면 실행마다 순서가 바뀌어 모델의 답이
    바뀌었다(창밖을 쳐다보기: [looking outside, staring] / [staring, looking outside] 에서 둘 다 2번을 골랐다, 09-25)."""
    return [t for t, _s in sorted(scored.items(), key=lambda kv: (-round(kv[1], 6), not agrees(kv[0], en), kv[0]))]


def build_asks(asks: list[Ask], *, ka: Any, route_kos: Iterable[str], index: KeywordLemmaIndex,
               tokenize: Callable[[str], list[tuple[str, str]]], lookup: Callable[[str], list[tuple[str, int]]],
               keyword_tags: Callable[[str], list[str]], rank: Callable[[str, str], list[tuple[str, bool, bool]]],
               canonical: Callable[[str], str | None], usable: Callable[[str], bool],
               describe: Callable[[str], str], keep: Callable[[str], bool], stop: set[str],
               layer_lemmas: Iterable[str] = (),
               literal: Callable[[str, str], bool] = lambda _t, _w: True) -> list[Ask]:
    """모델에게 보낼 것 — 모델 항목(asks)마다 한국어가 확인한 영문 묶음을 keep 에 담고, **아직 설명 안 된 한국어 원형**이
    남으면 그 원형의 후보를 채운다. 모델이 안 낸 요청 명사도 한국어 후보가 있으면 붙인다.

    남은 원형이 없으면 보내지 않는다(picks = [] — keep 만 싣는다). 원형을 하나도 못 찾은 항목과 후보가 없는 항목은
    picks 가 None 으로 남아 예전 결과로 간다.

    rank(ko, en)      구성 경로의 TagFinder 순위 [(태그, 영문 근거가 강한가, 한국어 근거가 강한가)] — 강한 것만 쓰고,
                      keep 이 있으면 영문 근거만(스마트폰 보기의 phone 은 이미 실은 smartphone 의 한국어 근거였다)
    canonical(term)   영문이 태그 이름 그대로면 그 태그(잡동사니 태그는 None)
    keyword_tags(key) 한국어 정확 키워드 -> 태그
    usable(tag)       이모티콘·메타·인원·캐릭터 등 싣지 않을 태그 거르기
    keep(tag)         고른 등급에 맞나(등급 게이트)
    layer_lemmas      한국어 층이 이미 태그로 만든 원형 — 동사 규칙(앉 -> sitting) · 시청자 규칙(나를 쳐다보는 ->
                      looking at viewer). 모델 항목이 그 뜻이면 다시 묻지 않는다(나를 쳐다보기 -> staring 을 덧붙였다)
    literal(tag, 말)  그 말이 태그의 제 이름인가 — 모델이 안 낸 명사는 제 이름인 태그만 후보(소파 -> couch). 키워드만
                      걸친 태그를 줬더니 아래 -> under shot · 손가락 -> pointing at another · 한쪽 -> single sleeve past
                      fingers 를 골랐다(holdout 09-25)
    """
    request = lemmas_of(ka.tokens)
    nouns = [f for f, t in ka.tokens if t in ("NNG", "NNP")]
    near = neighbours(ka.tokens)
    layer_lemmas = set(layer_lemmas)

    def ok(tag: str) -> bool:
        return usable(tag) and keep(tag)

    def korean(want: set[str], strict: bool, en: str) -> dict[str, float]:
        scored: dict[str, float] = {}
        for name, score, hit, size in korean_matches(index, want, lookup, strict=strict, nouns=nouns, near=near):
            tag = canonical(name)                                             # 사전 이름 -> 맵 이름(sofa -> couch), 없으면 뺀다
            if not tag:
                continue
            # 한 낱말 키워드와 한 음절 원형은 뜻이 여럿이다 — 모델 영문이 있으면 낱말을 나눌 때만. holdout(09-25)에서
            # 영문과 안 맞는 한 낱말 후보 7개 중 6개가 엉뚱했다: 코트(court) -> blue coat · 꺼내기(take out) ->
            # drawing sword · 이마 대기 -> facepalm · 쓰다(wearing) -> writing. 여러 낱말 키워드(흩날리는 꽃잎 ·
            # 턱괴기 · 창밖 보기)는 그 자체가 뜻을 좁힌다.
            if en and (size == 1 or all(len(lemma_form(h)) == 1 for h in hit)) and not agrees(tag, en):
                continue
            scored[tag] = max(scored.get(tag, 0.0), score + 1.0)
        return scored

    def settle(ask: Ask, scored: dict[str, float]) -> None:
        # 'X and Y' 는 두 사람·두 가지의 구도 태그다 — 학생(student)에 teacher and student 를 골랐다(holdout2 09-25)
        pair = " and " in f" {ask.en} "
        names = [t for t in order_candidates(scored, ask.en)
                 if t not in ask.keep and ok(t) and (pair or " and " not in t)]
        ask.candidates = [(t, describe(t)) for t in names[:MAX_CANDIDATES]]

    out: list[Ask] = []
    item_lemmas: set[str] = set()
    for ask in asks:
        want = lemmas_of(tokenize(ask.ko)) & request                          # 요청에 실제로 있는 원형만
        item_lemmas |= want
        if not want:
            continue                                                          # 한국어 근거 없음 — 예전 결과로
        parts = english_parts(ask.en, canonical)
        confirm = korean_tags(ask.ko, want=want, keyword_tags=keyword_tags, index=index, lookup=lookup,
                              canonical=canonical)

        def confirmed(tag: str) -> set[str] | None:
            # 확인된 태그 그 자체이거나, 불용어만 더 붙은 꼴(on bed = bed)
            if tag in confirm:
                return confirm[tag]
            words = {w for w in en_words(tag) if w not in _EN_STOP}
            return next((lem for other, lem in confirm.items()
                         if words and words == {w for w in en_words(other) if w not in _EN_STOP}), None)

        spans: set[int] = set()
        explained: set[str] = set()
        for tag, (i, j) in parts:
            lem = confirmed(tag)
            if lem is not None and ok(tag):
                ask.keep.append(tag)
                spans |= set(range(i, j))
                explained |= lem
        words = en_words(ask.en)
        left = {i for i, w in enumerate(words) if i not in spans and w not in _EN_STOP}
        # 틀 명사(표정 · 모습)는 묻지 않는다 — 놀란 표정(surprised expression)의 표정에 expressions 를 골랐다(09-25)
        rest = {w for w in want - explained - layer_lemmas if lemma_form(w) not in GENERIC_NOUNS}
        if ask.keep:
            # 실은 것의 꾸밈말만 남았으면(낮은 천장 -> ceiling 뒤의 '낮') 묻지 않는다 — ceiling light 를 골랐다(09-25)
            rest = {w for w in rest if not w.endswith("/A")}
        # 영문이 다 덮였거나 한국어가 다 설명되면 묻지 않는다 — 교실 창가(classroom window seat)의 seat 는 모델이 덧붙인
        # 말이라 물었더니 room 을 골랐다 · 창가에 앉기(window seat)의 앉기는 한국어 층이 sitting 으로 만든다(09-25)
        if (ask.keep and not left) or not rest:
            ask.picks = []
            continue
        scored = korean(rest, False, ask.en)
        for tag, (i, j) in parts:
            # 확인 안 된 영문 묶음은 **남은 영문을 통째로** 덮거나 내용어가 둘 이상일 때만 후보 — 화난 얼굴(angry face)의
            # angry · 흠뻑 젖은 교복(soaked school uniform)의 school uniform 은 되고, 턱을 괴기(chin resting on hand)의
            # 조각 chin · resting 은 안 된다(모델이 chin 을 골랐다)
            content = [w for w in en_words(tag) if w not in _EN_STOP]
            if tag not in ask.keep and (left <= set(range(i, j)) or len(content) >= 2):
                scored[tag] = max(scored.get(tag, 0.0), 3.6)
        strong = [tag for tag, en_ok, ko_ok in rank(ask.ko, ask.en)
                  if en_ok or (ko_ok and not ask.keep and agrees(tag, ask.en))]
        for i, tag in enumerate(strong[:MAX_CANDIDATES]):
            scored[tag] = max(scored.get(tag, 0.0), 2.5 - 0.2 * i)
        settle(ask, scored)
        if ask.candidates:
            out.append(ask)
        elif ask.keep:
            ask.picks = []
    covered = set(item_lemmas) | layer_lemmas
    phrases = getattr(ka, "phrases", {}) or {}
    for ko in route_kos:
        # 사전 구로 바뀐 항목은 덮은 것으로 보지 않는다 — '소파에 기대기' 가 기대기 -> leaning on person 으로 바뀌며
        # 소파(couch)가 사라졌다(09-25). 구의 원형은 아래에서 따로 덮는다.
        if not any(key and key in compact(ko) for key in phrases):
            covered |= lemmas_of(tokenize(ko))
    for key in phrases:
        covered |= lemmas_of(tokenize(key))
    names = {n.form for n in getattr(ka, "names", []) or []}
    text = str(getattr(ka, "source_text", "") or "")
    for surface, want in uncovered_units(ka.tokens, covered, set(stop) | GENERIC_NOUNS, names, text):
        if len(out) >= MAX_ASKS:
            break
        ask = Ask(ko=surface, source="extra")
        word = surface.replace(" ", "")
        scored = korean(want, True, "")
        for name in keyword_tags(word):                                     # 붙여 쓴 꼴(종이 학 -> 종이학)
            tag = canonical(name)
            if tag:
                scored[tag] = max(scored.get(tag, 0.0), 4.0)
        settle(ask, {t: s for t, s in scored.items() if literal(t, word)})
        if ask.candidates:
            out.append(ask)
    return out[:MAX_ASKS]
