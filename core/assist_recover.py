"""Assist v2 — 미번역 낱말 되살리기(S9d, 사용자 지정 2026-09-26 · 첫 마일스톤).

'거구의 주인에게 강제로 교배당하는 메이드' 가 `1girl, 1boy, maid, forced` 로 끝났다 — 거구 · 주인 · 교배 를 설명하는 태그가
없었다. 요청의 내용 형태소 중 **결과 태그가 설명하지 못한 것**을 찾아(find_units) 태그를 되찾는다:

1. 한국어 사전(NAIA keywords_kr + 설명, Kiwi 원형 일치 · IDF 맞춤 0.5+)에서 후보 — 거구 -> giant male('거구 남성').
   사람 낱말(주인 · 엄마 …)은 **키워드에서만**(설명문의 "주인에게 소유되는" -> slave 를 막는다).
2. 사전이 비었거나 맞춤이 **불완전**하면(낱말의 내용 형태소를 다 덮는 태그가 없음) E2B 뜻 키워드(두 번 합집합)가 이름에
   든 이벤트 맵 태그를 뒤에 붙인다 — 잠들듯 말듯 -> sleepy.
3. 후보는 이벤트 맵 공출현 순(부르는 쪽) · 두 사람 태그(mother and child)는 요청에 사람이 둘 이상일 때만.
4. 고르기는 제품의 번호 고르기(정순 · 역순) — 부르는 쪽. 두 답이 같을 때만 싣고, 서술 덩어리의 후보 하나는 묻지 않는다
   (09-29 E4B 창작 문장 채점 — 서비스 _recover).

평가: docs/assist_vocab_handoff/untranslated/ — 세트 v2(요청 26 · 낱말 44) 8회 적중 S9d 61.9% · S8 56.9% · S2 40.9%.
사전 색인 · 맞춤 규칙은 거기서 잰 그대로 옮겼다(run_untranslated.py 의 KoIndex · ko_match_kw_only · ko_completeness).
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable

# 내용 형태소 = 명사 · 어근 · 외국어(N), 동사 · 형용사 줄기(P — Kiwi 가 싸다(동/형)를 오가서 한 갈래), 부사(M, 둥둥 같은 흉내말)
KO_CONTENT = ("NNG", "NNP", "XR", "SL", "SH", "VV", "VA", "MAG")
KO_STOP = frozenset({"말/P", "하/P", "되/P", "있/P", "없/P", "주/P", "지/P", "않/P", "이/P"})
KO_MIN_SCORE = 0.5            # 맞춤 점수 문턱 — 희귀한 원형이 맞아야 통과(몸 · 눈 같은 흔한 원형 하나로는 못 들어온다)
MAX_UNITS = 4                 # 한 요청에서 되살릴 덩어리 수(덩어리마다 고르기 E2B 두 번)
MAX_CANDIDATES = 6
MAX_UNIT_WORDS = 5            # 서술 덩어리의 어절 수 상한

# 인원이 이미 말하는 사람 낱말 — 되살리지 않는다(소녀 -> 1girl 로 끝). 역할 · 친족 · 직업 낱말(주인 · 엄마 · 여고생)은 되살린다
BASIC_PEOPLE = frozenset({"소녀", "여자", "여성", "여자애", "미소녀", "소년", "남자", "남성", "남자애", "미소년", "사람",
                          "아이", "인물", "누군가", "친구"})
# 호칭 · 친족 낱말 — 누구인지(관계)만 말하고 그림에 그릴 것이 없다. 인원 칸이 맡는다. 되살리면 사전 키워드로 엉뚱한 태그가
# 붙었다(누나 -> siscon '누나 집착' · 언니 -> onee-loli · sisters · 누나/언니 -> brother and sister · 아가씨 -> ojou-sama pose —
# 09-29 E4B 창작 문장 78개에서 30건 넘게)
ADDRESS_PEOPLE = frozenset({"누나", "언니", "오빠", "형", "누님", "형님", "오라버니", "동생", "여동생", "남동생", "여친", "남친",
                            "여자친구", "남자친구", "여사친", "남사친", "아가씨"})
# 규칙표(people · groups)에 없는 친족 · 호칭 · 직업 — 평가 러너의 PERSON_EXTRA 그대로
PERSON_EXTRA = frozenset({"누님", "형님", "오라버니", "남편", "아내", "부인", "신랑", "신부", "새댁", "이모", "삼촌", "동생",
                          "선배", "후배", "손님", "승객", "서퍼", "점원", "경찰", "의사", "간호사", "군인", "기사", "주인공"})
# 키워드 구절의 가벼운 머리 — 요청에 없어도 그 구절의 뜻을 바꾸지 않는다('거구 남성' 의 남성 · '엿보는 행위' 의 행위).
# 이것 말고 구절에 딸린 명사(유두비틀기의 유두)가 요청에 없으면 그 구절은 근거가 아니다(KoDictIndex.grounded)
LIGHT_HEADS = BASIC_PEOPLE | frozenset({"행위", "행동", "동작", "모습", "상태", "자세", "표정", "장면", "캐릭터", "상황",
                                        "경우", "느낌", "분위기", "포즈"})


def ko_key(form: str, tag: str, *, stop: bool = True) -> str | None:
    """형태소 -> 원형 열쇠('거구/N' · '잠들/P' · '둥둥/M'). stop 이면 가벼운 용언(하 · 되 · 있 …)은 None."""
    if not tag.startswith(KO_CONTENT):
        return None
    kind = "P" if tag.startswith(("VV", "VA")) else "M" if tag == "MAG" else "N"
    key = f"{form.lower()}/{kind}"
    return None if stop and key in KO_STOP else key


def clean_keywords(text: object) -> str:
    return re.sub(r"<primary>:?|[<>\[\]]", " ", str(text or ""))


def _whole(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


# ── 한국어 사전 원형 색인 ─────────────────────────────────────────────────────────


class KoDictIndex:
    """쓸 수 있는 태그의 한국어 키워드 + 설명 -> Kiwi 원형 역색인. 세션에 한 번(약 2만 태그, 수 초).

    entries        (태그, keywords_kr, description) — 태그는 이벤트 맵 이름
    tokenize_many  글 목록 -> [(꼴, 품사)] 목록(Kiwi 날것, 한꺼번에)
    tokenize       글 하나 -> [(꼴, 품사)] — 물음 낱말용
    """

    def __init__(self, entries: Iterable[tuple[str, str, str]],
                 tokenize_many: Callable[[list[str]], list[list[tuple[str, str]]]],
                 tokenize: Callable[[str], list[tuple[str, str]]]) -> None:
        self.tokenize = tokenize
        names: list[str] = []
        kw_texts: list[str] = []
        desc_texts: list[str] = []
        self.kw_tokens: dict[str, frozenset[str]] = {}
        self.by_kw_token: dict[str, set[str]] = {}
        for tag, keywords, description in entries:
            kw = clean_keywords(keywords)
            # 키워드 = 쉼표로 가른 구절 통째(공백 뺀 것). 공백으로도 쪼갰더니 '실종 포스터' 의 실종 · '더치 앵글' 의 앵글 · '성인
            # 기구' 의 성인이 그 태그의 키워드 그대로가 돼 근거 검사(grounded)를 건너뛰었다 — 하의실종 -> missing poster · 앵글 ->
            # dutch angle · 성인 -> cock ring(09-29 E4B 창작 문장 채점: 이 길로 들어온 것이 틀림 36 · 맞음 14)
            toks = frozenset(_whole(p) for p in kw.split(",") if _whole(p))
            self.kw_tokens[tag] = toks
            for t in toks:
                self.by_kw_token.setdefault(t, set()).add(tag)
            names.append(tag)
            kw_texts.append(kw)
            desc_texts.append(str(description or ""))
        self.lemmas: dict[str, frozenset[str]] = {}
        self.kw_lemmas: dict[str, frozenset[str]] = {}
        self.kw_phrases: dict[str, tuple[frozenset[str], ...]] = {}      # 쉼표로 가른 키워드 구절마다의 원형
        self.by_lemma: dict[str, set[str]] = {}
        self.kw_by_lemma: dict[str, set[str]] = {}
        for name, kw_toks, desc_toks in zip(names, tokenize_many(kw_texts), tokenize_many(desc_texts)):
            kw_lem = frozenset(k for k in (ko_key(f, t) for f, t in kw_toks) if k)
            lem = kw_lem | frozenset(k for k in (ko_key(f, t) for f, t in desc_toks) if k)
            self.kw_lemmas[name], self.lemmas[name] = kw_lem, lem
            self.kw_phrases[name] = _phrases(kw_toks)
            for k in lem:
                self.by_lemma.setdefault(k, set()).add(name)
            for k in kw_lem:
                self.kw_by_lemma.setdefault(k, set()).add(name)
        self.n = len(names)
        self._cache: dict[tuple[str, bool], dict[str, float]] = {}

    def query(self, text: str) -> list[str]:
        return list(dict.fromkeys(k for k in (ko_key(f, t) for f, t in self.tokenize(text)) if k))

    def match(self, text: str, *, keywords_only: bool = False) -> dict[str, float]:
        """낱말에 맞는 태그 -> 맞춤 점수(0.5~1). 키워드 토막이 낱말(공백 뺀 것, 2글자 이상) 그대로면 1 — 앞부분 일치는
        '주인공' 이 '주인' 에 걸려서 쓰지 않는다. keywords_only = 설명문은 보지 않는다(사람 낱말)."""
        cache_key = (text, keywords_only)
        if cache_key in self._cache:
            return self._cache[cache_key]
        by_lemma = self.kw_by_lemma if keywords_only else self.by_lemma
        idf = {k: math.log(self.n / len(by_lemma[k])) for k in self.query(text) if by_lemma.get(k)}
        total = sum(idf.values())
        scores: dict[str, float] = {}
        for k, w in idf.items():
            for name in by_lemma[k]:
                scores[name] = scores.get(name, 0.0) + w
        out = {n: round(s / total, 3) for n, s in scores.items() if total > 0 and s / total >= KO_MIN_SCORE}
        whole = _whole(text)
        if len(whole) >= 2:
            for name in self.by_kw_token.get(whole, ()):
                out[name] = 1.0
        self._cache[cache_key] = out
        return out

    def completeness(self, text: str, matched: Iterable[str], *, keywords_only: bool = False) -> float:
        """맞춤의 완전도 — 맞춘 태그 하나가 낱말의 내용 형태소를 덮는 가장 큰 비율(가벼운 용언 · 사전에 없는 원형도 센다 —
        잠들듯 말듯 의 '말' 이 빠지면 1.0 이 나와 못 잡았다). 키워드 토막이 낱말 그대로면 1."""
        whole = _whole(text)
        content = {k for k in (ko_key(f, t, stop=False) for f, t in self.tokenize(text)) if k}
        if not content:
            return 1.0
        lemmas = self.kw_lemmas if keywords_only else self.lemmas
        best = 0.0
        for name in matched:
            if len(whole) >= 2 and whole in self.kw_tokens.get(name, ()):
                return 1.0
            best = max(best, len(content & lemmas.get(name, frozenset())) / len(content))
        return round(best, 3)

    def keyword_lemmas(self, tag: str) -> frozenset[str]:
        """그 태그의 한국어 키워드 원형 — 요청의 어느 말을 이미 설명했나(find_units 의 explained)."""
        return self.kw_lemmas.get(tag, frozenset())

    def grounded(self, tag: str, text: str, request: Iterable[str]) -> bool:
        """맞춘 태그가 이 요청에 **정말** 이어지나 — 낱말의 원형 하나가 맞았다고 그 태그의 뜻이 되지 않는다(09-28 제보).
        - 키워드 구절(쉼표로 가른 것) 중 낱말의 원형을 품은 것이 있으면: 그 구절의 다른 **명사**가 전부 요청에 있거나
          가벼운 머리(LIGHT_HEADS)여야 한다 — '닭의 목을 비틀고' 의 비틀이 유두비틀기 -> nipple tweak · 허리 비틀기 ->
          twisted torso 를 데려왔다(젖꼭지 · 허리 는 요청에 없다). '거구 남성' 의 남성은 가벼운 머리라 거구 -> giant male 은 산다.
        - 설명문으로만 맞았으면: 낱말의 내용 원형이 **둘 이상이고 다** 덮여야 — '건너편에서 들으며' 가 설명의 '호수
          건너편' 으로 misty lake(동방 호수)가 됐고, 원형 하나(비틀)는 설명문 어디에나 있어 nipple tweak through clothes
          (설명 '옷 위로 유두를 비트는')가 됐다.
        request = 요청 전체의 원형(query) · 키워드 토막이 낱말 그대로면 언제나 이어진다."""
        whole = _whole(text)
        if len(whole) >= 2 and whole in self.kw_tokens.get(tag, ()):
            return True
        unit = set(self.query(text))
        have = set(request) | unit
        hits = [p for p in self.kw_phrases.get(tag, ()) if p & unit]
        if hits:
            return any(not {k for k in p - have if k.endswith("/N") and k[:-2] not in LIGHT_HEADS} for p in hits)
        return len(unit) >= 2 and unit <= self.lemmas.get(tag, frozenset())


def _phrases(toks: list[tuple[str, str]]) -> tuple[frozenset[str], ...]:
    """키워드 토막 -> 쉼표(Kiwi SP)로 가른 구절마다의 원형 묶음(빈 구절은 뺀다). 접속 조사(와 · 과 — JC)에서도 가른다:
    '주인과 하인' 은 한쪽(주인)만으로도 그 관계의 뜻이다 — 하인이 요청에 없다고 master and servant 를 버렸다(시험).
    한 명사 + 조사 · 서술격 · 어미뿐인 구절은 뺀다 — 외래어 음역(오후로 = ofuro)을 Kiwi 가 오후 + 로 로 읽어 '오후' 가
    ofuro 가 됐다(09-29). 그런 키워드는 구절 통째가 같을 때만 맞는다(kw_tokens)."""
    out: list[frozenset[str]] = []
    cur: set[str] = set()
    shape: list[str] = []

    def close() -> None:
        nouns = [t for t in shape if t.startswith(("NN", "XR"))]
        tail = [t for t in shape if t.startswith(("J", "VCP", "E"))]
        if cur and not (len(nouns) == 1 and tail and len(nouns) + len(tail) == len(shape)):
            out.append(frozenset(cur))

    for form, tag in toks:
        if tag in ("SP", "JC") or form == ",":
            close()
            cur, shape = set(), []
            continue
        shape.append(tag)
        key = ko_key(form, tag)
        if key:
            cur.add(key)
    close()
    return tuple(out)


# ── 미번역 덩어리 찾기 ─────────────────────────────────────────────────────────


@dataclass
class Unit:
    text: str                                   # 요청에서 뗀 글(거구 · 둥둥 떠 있는 · 눈을 동그랗게 뜬)
    lemmas: list[str] = field(default_factory=list)
    kind: str = "noun"                          # noun | predicate
    start: int = 0
    end: int = 0
    person: bool = False


_NOUN = ("NNG", "NNP")
_PRED = ("VV", "VA", "XR")
# 덩어리로 세우지 않는 명사 — 틀 · 정도 · 때(차림 · 반쯤). 공간 낱말(앞 · 위)은 규칙표 spatial_words 를 부르는 쪽이 넣는다
FRAME_NOUNS = frozenset({"차림", "반쯤", "절반", "정도", "쪽", "때", "중", "후", "전", "채", "뿐", "만큼"})
# 덩어리로 세우지 않는 가벼운 용언 — 입다 · 짓다(표정을 짓는) · 쓰다 · 당하다 … 요청 동사(그려 · 만들어 · 찾아)는 규칙표
# filler_stems 를 부르는 쪽이 넣는다
LIGHT_VERBS = frozenset({"입", "짓", "쓰", "신", "걸치", "당하", "두", "놓", "보이", "가지",
                         "띄우",        # 물음표를 · 미소를 띄우다 — 뜻은 목적어가 맡는다(띄우고 -> fruit on liquid, 09-26)
                         "나"})         # 냄새가 · 소리가 · 발정이 나다 — 뜻은 앞 명사가 맡는다('냄새가 나는듯' 의 나는듯이
#                                         따로 덩어리가 돼 cat girl 을 골랐다, 사용자 제보 09-28)
# 뜻 키워드에서 버리는 사람 낱말 — 사람 수는 인원 칸이 맡는다. 'girl' 이 이름에 든 태그(fox girl · demon girl · cat girl …)를
# 통째로 후보로 끌어와 '나는듯..' 에 cat girl 을 골랐다(사용자 제보 09-28)
KW_PEOPLE = frozenset({"girl", "girls", "boy", "boys", "woman", "women", "man", "men", "person", "people", "female",
                       "male", "human", "humans", "lady", "guy", "kid", "kids", "child", "children"})


def person_words(rules: dict) -> frozenset[str]:
    """사람 낱말 — 규칙표 people(female · male · neutral) + groups 이름 + PERSON_EXTRA. 사전 검색을 키워드에서만 한다."""
    people = rules.get("people") or {}
    words = {w for key in ("female", "male", "neutral") for w in people.get(key) or []}
    return frozenset(words | set(rules.get("groups") or {}) | PERSON_EXTRA)


# 뺀 것 · 부정된 것 — 명사 뒤 (조사 +) 없이 · 없는 · 빼고 · 말고 · 제외 · 금지 · 안/못 + 용언 · 용언 + 지 않/못/말. 되살리면
# 반대 뜻이 붙었다(말풍선 없이 -> thought bubble · 속옷 없이 -> underwear · 팬티는 안 보이게 -> panty peek — 09-29 E4B 창작
# 문장). 모자를 쓰지 않은 의 쓰다는 가벼운 용언이라 덩어리가 안 되고 모자만 남는다. 제외는 경로가 맡는다
_NEGATED_HEADS = ("빼", "빼놓", "제외", "금지")


def _negated_after(per: list[list[tuple[str, str, int, int]]], i: int, end: int) -> bool:
    """명사(어절 i, end 에서 끝) 뒤가 부정 · 제외인가 — 형태소로 본다(조사 · 기호는 건넌다): 없이 · 없는 · 빼고 · 말고 · 제외 ·
    금지 · 부사 안/못 · 용언 + 지 않/못/말. 글자로 보니 '말풍선 안 글자'(안 = 안쪽) · '책장 빼곡한' 의 빼 에 걸렸다(Codex 16차 F6)."""
    toks = [(f, t) for f, t, s, _e in per[i] if s >= end]
    toks += [(f, t) for j in (i + 1, i + 2) if j < len(per) for f, t, _s, _e in per[j]]
    cut = next((k for k, (_f, t) in enumerate(toks) if t.startswith("S")), len(toks))
    toks = [(f, t) for f, t in toks[:cut] if not t.startswith("J")]   # 쉼표 · 기호에서 멈춘다 — '안경, 안 웃는'(17차 R5)
    if not toks:
        return False
    form, tag = toks[0]
    if form.startswith("없") and tag.startswith(("VA", "VV", "MAG")):
        return True
    if (form in _NEGATED_HEADS and tag.startswith(("VV", "NNG"))) or (form == "말" and tag.startswith(("VV", "VX"))):
        return True
    if form in ("안", "못") and tag == "MAG":
        return True
    # 용언 + 지 않 — 명사 + 하다(화장하지 않은 = 화장 + 하/XSV + 지 + 않)도(17차 R6)
    return tag.startswith(("VV", "VA", "XSV", "XSA")) and len(toks) >= 3 and toks[1][0] == "지" \
        and toks[2][0] in ("않", "못하", "말")


def find_units(spans: list[tuple[str, str, int, int]], text: str, *, explained: set[str],
               skip: set[str], people: Iterable[str] = (), stop_verbs: Iterable[str] = (),
               max_units: int = MAX_UNITS) -> list[Unit]:
    """요청(clean_text 한 글)의 토큰(spans, 위치 포함)에서 **아직 아무 태그도 설명하지 않은** 덩어리를 찾는다.

    - 명사 덩어리: 어절 안에서 이어진 미번역 명사(거구 · 여고생) — 바로 붙은 영문 · 숫자도 함께(V사인). 사람 낱말이면 person.
      한 음절 명사만으로 된 것은 세우지 않는다(날 · 밤 · 눈 — 뜻이 여럿).
    - 서술 덩어리: 미번역 동사 · 형용사 · 어근(흉내말 + 하다: 발그레해진 · 아슬아슬하게)이 든 어절 + 뒤의 보조 어절(있는 ·
      말듯한) + 앞의 흉내말 어절(둥둥 · 쫙) + 바로 앞 미번역 명사 어절 하나(눈을 · 몸에 — 목적어 · 부사어; 먹은 명사는 따로
      덩어리가 되지 않는다). 서술어가 이어지면 앞 어절이 '-게' 로 끝날 때만 하나로(아슬아슬하게 가린) — 물고 달려가는 은 둘.
      '-게' 로 끝난 채 멈춘 덩어리(꾸미는 서술어가 이미 설명됐다: 동그랗게 + 뜬)는 세우지 않는다.
    explained = 이미 설명된 원형(ko_key) · skip = 낱말로 보지 않을 꼴(이름 · 틀 명사 · 공간 낱말 · 그냥 사람 낱말) ·
    stop_verbs = 덩어리로 세우지 않을 용언 줄기(가벼운 용언 · 요청 동사)."""
    people = set(people)
    stop_keys = {f"{v}/P" for v in set(stop_verbs) | LIGHT_VERBS}
    skip = set(skip) | FRAME_NOUNS
    words = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    per: list[list[tuple[str, str, int, int]]] = [[] for _ in words]
    for form, tag, s, e in spans:
        for i, (ws, we) in enumerate(words):
            if ws <= s < we:
                per[i].append((form, tag, s, e))
                break

    def open_key(form: str, tag: str) -> str | None:
        key = ko_key(form, tag)
        return key if key and key not in explained and key not in stop_keys and form not in skip else None

    def ends_with_ge(i: int) -> bool:
        return bool(per[i]) and per[i][-1][0] == "게" and per[i][-1][1].startswith("EC")

    nouns: dict[int, list[tuple[int, int, list[str]]]] = {}
    preds: set[int] = set()
    for i, toks in enumerate(per):
        runs: list[tuple[int, int, list[str]]] = []
        for j, (form, tag, s, e) in enumerate(toks):
            key = open_key(form, tag)
            nxt = toks[j + 1][1] if j + 1 < len(toks) else ""
            if key and tag in _NOUN:
                prev = toks[j - 1] if j else None
                if runs and runs[-1][1] == s:                     # 붙어 있는 명사는 하나(여고 + 생)
                    runs[-1] = (runs[-1][0], e, runs[-1][2] + [key])
                elif prev and prev[1] in ("SL", "SN", "SH") and prev[3] == s:
                    runs.append((prev[2], e, [key]))              # V사인 — 붙은 영문 · 숫자까지
                else:
                    runs.append((s, e, [key]))
            elif key and (tag.startswith(_PRED) or (tag == "MAG" and nxt.startswith(("XSA", "XSV")))):
                preds.add(i)                                      # 발그레 + 하 — 흉내말 용언
        if runs:
            nouns[i] = runs

    def contentless(i: int) -> bool:
        return all(ko_key(f, t) is None or ko_key(f, t) in stop_keys for f, t, _s, _e in per[i])

    def adverb_only(i: int) -> bool:
        keys = [ko_key(f, t) for f, t, _s, _e in per[i]]
        return bool(keys) and any(k for k in keys) and all(k is None or k.endswith("/M") for k in keys) \
            and i not in preds

    units: list[Unit] = []
    absorbed: set[int] = set()
    taken: set[int] = set()
    for i in sorted(preds):
        if i in taken:
            continue
        lo = hi = i
        while hi + 1 < len(per) and hi - lo + 1 < MAX_UNIT_WORDS:
            if hi + 1 in preds and ends_with_ge(hi):             # 아슬아슬하게 가린 · 동그랗게 뜬
                hi += 1
            elif contentless(hi + 1) and hi + 1 not in nouns:    # 있는 · 말듯한 — 보조 어절
                hi += 1
            else:
                break
        while lo - 1 >= 0 and lo - 1 not in taken and hi - lo + 1 < MAX_UNIT_WORDS and adverb_only(lo - 1):
            lo -= 1
        prev = lo - 1
        if (prev >= 0 and prev not in taken and prev in nouns and len(nouns[prev]) == 1 and per[prev]
                and per[prev][-1][1].startswith("J") and hi - lo + 1 < MAX_UNIT_WORDS):
            lo = prev                                             # 눈을 · 몸에 — 서술어의 목적어 · 부사어
            absorbed.add(prev)
        taken |= set(range(lo, hi + 1))
        if ends_with_ge(hi) and hi + 1 < len(per):
            continue            # '-게' 로 끝난 채 멈췄다 = 꾸미는 서술어(뜬)는 이미 태그가 설명했다 — 동그랗게만 따로 찾으면
            #                     눈을 크게 뜬(unusually open eyes) 옆에 solid circle pupils 가 붙었다(라이브 09-26)
        lemmas = [k for j in range(lo, hi + 1) for k in (open_key(f, t) for f, t, _s, _e in per[j]) if k]
        near = [(f, t) for j in range(lo, hi + 1) for f, t, _s, _e in per[j]]
        # 바로 앞 어절은 부사 안/못 하나일 때만 이 서술의 부정이다 — '웃지않고 찡그리는' 의 앞 절 부정이 찡그리는 까지
        # 버렸다(Codex 16차 F7)
        before = [(f, t) for f, t, _s, _e in per[lo - 1]] if lo >= 1 and lo - 1 not in taken - set(range(lo, hi + 1)) else []
        if len(before) == 1 and before[0][1] == "MAG" and before[0][0] in ("안", "못"):
            near = before + near
        if any(t == "MAG" and f in ("안", "못") for f, t in near) or any(
                f == "지" and t.startswith("EC") and k + 1 < len(near) and near[k + 1][0] in ("않", "못하", "말")
                for k, (f, t) in enumerate(near)):
            continue            # 안 보이게 · 보이지 않게 — 부정된 서술(09-29). 부사 안(MAG)만 — 방 안(NNG)은 아니다
        units.append(Unit(text[words[lo][0]:words[hi][1]].strip(), lemmas, "predicate", words[lo][0], words[hi][1]))
    for i, runs in nouns.items():
        if i in absorbed or i in taken:
            continue
        for s, e, keys in runs:
            if all(len(k.split("/")[0]) < 2 for k in keys):
                continue        # 한 음절 명사만 — 뜻이 여럿이다(비 오는 날 -> 칼날 -> scabbard, 라이브 09-26). 고르기의
                #                 요청 명사(uncovered_units)와 같은 규칙
            surface = text[s:e]
            if _negated_after(per, i, e):
                continue        # 말풍선 없이 · 속옷 없이 · 팬티는 안 보이게 — 뺀 것(09-29)
            units.append(Unit(surface, keys, "noun", s, e, person=_whole(surface) in people))
    units.sort(key=lambda u: u.start)
    return units[:max_units]


def pair_ok(tag: str, persons: int) -> bool:
    """'X and Y' 는 두 사람 · 두 가지의 태그다 — 요청에 사람이 둘 이상일 때만(엄마 한 사람 -> mother and child 를 막는다)."""
    return " and " not in f" {tag} " or persons >= 2


# ── E2B 뜻 키워드(사전이 비었거나 불완전할 때) ──────────────────────────────────────────

# 예시 낱말은 평가 세트의 답과 겹치면 안 된다(겹치는 예시로 잰 수치가 부풀었다, 09-26)
KW_SYSTEM = """You explain words that an anime image app could not turn into Danbooru tags.
For each untranslated word, infer what the user means by it in this request - read the whole request and the tags
already found - and write 3 to 6 English keywords for that meaning: single lowercase words of the kind used in
Danbooru tag names (for example: umbrella, kneeling, cloudy, braid). Answer only the listed lines, in order."""


def kw_message(text: str, found: Iterable[str], units: list[str]) -> str:
    """사용자 제안 형식(09-26) — USER INPUT · 식별된 TAGS · 미번역. 식별된 TAGS 는 요청에서 나온 것만(표본 채움을 넣으면
    거구가 giant 로 끌려갔다 — 닻 효과)."""
    return f"USER INPUT : {text}\n식별된 TAGS : {', '.join(found)}\n미번역 : {', '.join(units)}"


def kw_grammar(units: list[str]) -> str:
    heads = " ".join(json.dumps(("" if i == 0 else "\n") + f"{u} : ", ensure_ascii=False) + " kws"
                     for i, u in enumerate(units))
    return "\n".join([f"root ::= {heads}", 'kws ::= kw (", " kw){2,5}', "kw ::= [a-z] [a-z]{0,14}"])


def parse_keywords(reply: str | None, units: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in str(reply or "").splitlines():
        head, _, rest = line.partition(" : ")
        if head in units:
            out[head] = [w.strip() for w in rest.split(",") if w.strip() and w.strip() not in KW_PEOPLE]
    return out


def keyword_forms(word: str) -> set[str]:
    """이름 맞추기는 낱말 그대로 + 복수형만 — 어간을 자르면 mating -> mat -> on mat · staring -> star 가 났다."""
    w = word.lower()
    return {w, w + "s", w[:-1] if len(w) > 3 and w.endswith("s") else w}


def word_index(names: Iterable[str]) -> dict[str, set[str]]:
    """이벤트 맵 태그 이름의 낱말(그대로) -> 태그들."""
    index: dict[str, set[str]] = {}
    for name in names:
        for w in str(name).replace("(", " ").replace(")", " ").replace("-", " ").split():
            index.setdefault(w.lower(), set()).add(str(name))
    return index
