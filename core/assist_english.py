"""Assist v2 — 요청에 섞어 쓴 영문은 적힌 그대로 프롬프트에 싣는다(bypass, 사용자 지정 2026-09-26).

'감옥에 갇혀있는 소녀, crying, 기둥에 손이 묶여져있음' 에서 crying 이 조용히 사라졌다. 모델이 영문 낱말의 ko 를 한국어로
옮겨 적어(crying -> 울기 · full body -> 전신) 병합의 '요청에 없음' 검사에 걸렸고, masterpiece · best quality 처럼
단보루 태그가 아닌 것은 항목조차 되지 않았다. 사용자: "영단어는 bypass 로 모델에게 전달되도록".

- 가르기: 쉼표 · 줄바꿈 · 세미콜론 · 마침표 뒤에서 조각을 나누고, 조각 안의 한글 아닌 줄을 영문 하나로 본다
  (영문 글자가 있고 글자·숫자가 둘 이상 — 8k · 3d 는 되고 x 는 안 된다. 손동작 태그 v · w 는 한 글자도).
- 한글에 바로 붙은 영문(UTX교복 · V사인 · cat귀)은 한국어 낱말의 일부다 — 조사 · 하다 꼴이 붙은 것(smile을 ·
  crying하는)만 영문 낱말로 본다. 붙은 것은 예전처럼 한국어 층 · 모델이 맡는다.
- 뒤에 빼고 · 없이 · 말고가 오면 제외(hat 빼고). 인원 태그(1girl · 2girls · solo)는 인원 칸이 정한다.
- 가중치 문법(1.2::tag:: · (tag:1.2) · [tag]) · 대소문자 · 밑줄은 적힌 그대로 싣고 비교할 때만 뗀다(en_key).
- 중괄호는 예전처럼 이름 표시다(clean_text 가 뗀다) — {crying} 은 crying 으로 싣는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from core.assist_korean import clean_text

_HANGUL = "ᄀ-ᇿ㄰-㆏ꥠ-꥿가-힣ힰ-퟿"
_CJK = "぀-ヿ㐀-䶿一-鿿豈-﫿"
_PIECES = re.compile(r"[,，、;；\n\r]+|\.(?=\s|$)")        # 1.2::tag:: 의 마침표는 가르지 않는다
_NOT_KOREAN = re.compile(rf"[^{_HANGUL}{_CJK}]+")
_KOREAN_RUN = re.compile(rf"[{_HANGUL}]+")
_HAS_KOREAN = re.compile(rf"[{_HANGUL}]")
_LETTER = re.compile(r"[A-Za-z]")
_ALNUM = re.compile(r"[A-Za-z0-9]")
# 영문 바로 뒤에 붙어도 영문을 낱말로 보는 한글 — 조사(을 · 에서는 · 으로도) · 하다/되다 꼴 · 풍 · 느낌 · 제외 말(없이 · 빼고).
# 그 밖(교복 · 사인 · 셔츠 · 귀)이 붙으면 한국어 낱말의 일부다(UTX교복 · V사인 · T셔츠 · cat귀)
_PARTICLES = ("이랑", "에서", "에게", "한테", "으로", "처럼", "같이", "까지", "부터", "보다", "이나", "이든", "라도",
              "은", "는", "이", "가", "을", "를", "의", "에", "로", "와", "과", "랑", "도", "만", "나", "요")
_GLUED_WORD = re.compile(r"(?:%s)+|(?:하|했|해|한|할|함|되|됐|돼|된|될|스러|스럽|적|중|같|풍|느낌|없|빼|말|제외)[가-힣]{0,4}"
                         % "|".join(_PARTICLES))
_EXCLUDE_AFTER = re.compile(r"\s*(?:(?:은|는|을|를|이|가|도|만)\s*)?(?:빼|없이|없는|말고|제외|금지)")
_PEOPLE = re.compile(r"\d+\+?\s*(?:girl|boy)s?|multiple (?:girls|boys)|solo")
_EDGE = " \t'\"`‘’“”.·~*?-–—「」『』《》〈〉"
_NAI_WEIGHT = re.compile(r"-?\d+(?:\.\d+)?\s*::(.*?)(?:::)?")
_SD_WEIGHT = re.compile(r"\((.*?)(?::\s*-?\d+(?:\.\d+)?)?\)")
_ONE_LETTER = frozenset({"v", "w"})         # 손동작 태그(V 사인 · W 사인) — core.assist_v2.SHORT_TAGS 와 같다
_STOP = frozenset({"a", "an", "the", "of", "on", "in", "at", "to", "for", "with", "and", "by", "from", "her", "his",
                   "their", "own", "is", "are", "while"})


def en_key(text: object) -> str:
    """영문 태그 비교 열쇠 — 가중치 문법(1.2::x:: · (x:1.2) · [x]) · 대소문자 · 밑줄 · 겹친 공백을 뗀 것.
    싣는 것은 적힌 그대로다. 이 열쇠로는 '같은 태그인가' 만 가린다."""
    s = str(text or "").strip()
    for _ in range(4):
        m = _NAI_WEIGHT.fullmatch(s) or _SD_WEIGHT.fullmatch(s)
        if m:
            s = m.group(1).strip()
        elif len(s) > 1 and s[0] == "[" and s[-1] == "]":
            s = s[1:-1].strip()
        else:
            break
    return " ".join(s.lower().replace("_", " ").split())


def english_only(text: object) -> bool:
    """영문은 있고 한글은 없는 글(구성의 절 'masterpiece') — 통째로 적힌 그대로 실린다."""
    s = str(text or "")
    return bool(_LETTER.search(s)) and not _HAS_KOREAN.search(s)


def _trim(part: str) -> str:
    """조각 가장자리의 따옴표 · 마침표 · 짝 없는 괄호를 뗀다 — 'crying (슬픈 표정)' 은 한글 앞에서 끊겨 'crying (' 이 된다."""
    s = part.strip(_EDGE)
    while s and s[-1] in "([":
        s = s[:-1].rstrip(_EDGE)
    while s and s[0] in ")]":
        s = s[1:].lstrip(_EDGE)
    if s.startswith("(") and s.count("(") > s.count(")"):
        s = s[1:].lstrip(_EDGE)
    if s.endswith(")") and s.count(")") > s.count("("):
        s = s[:-1].rstrip(_EDGE)
    return s


@dataclass
class English:
    keep: list[str] = field(default_factory=list)      # 적힌 그대로 싣는다
    exclude: list[str] = field(default_factory=list)   # 뒤에 빼고 · 없이 · 말고 — 풀에서 뺀다(싣지 않는다)
    people: list[str] = field(default_factory=list)    # 1girl · 2girls · solo — 인원 칸이 정한다

    def keys(self) -> set[str]:
        return {en_key(p) for p in self.keep + self.exclude + self.people}

    def typed(self, en: object) -> bool:
        """모델 항목의 영문이 사용자가 영문으로 적은 말인가 — 같은 태그이거나, 적은 영문 한 조각의 낱말로만 된 것
        ('a girl sitting by the window' 의 sitting · window). 모델은 이런 항목의 ko 를 한국어로 옮겨 적는다."""
        key = en_key(en)
        if not key:
            return False
        if key in self.keys():
            return True
        words = set(key.split()) - _STOP
        return bool(words) and any(words <= set(en_key(p).split()) for p in self.keep + self.exclude)


def english_parts(text: object) -> English:
    """요청(clean_text 한 글)에서 영문 조각을 가른다. 같은 태그(en_key)는 한 번 — 처음 적힌 표기로."""
    out = English()
    for piece in _PIECES.split(clean_text(text)):
        for m in _NOT_KOREAN.finditer(piece):
            run = m.group()
            part = _trim(run)
            key = en_key(part)
            if not _LETTER.search(part) or (len(_ALNUM.findall(part)) < 2 and key not in _ONE_LETTER):
                continue
            # 글자가 한글에 바로 닿을 때만 붙은 것이다 — 'crying (슬픈 표정)' 은 괄호가 닿는다(붙은 것이 아니다)
            if m.end() < len(piece) and _ALNUM.match(run[-1]):
                word = _KOREAN_RUN.match(piece, m.end())
                if word and not _GLUED_WORD.fullmatch(word.group()):
                    continue                          # UTX교복 · V사인 — 한국어 낱말의 일부
            if _PEOPLE.fullmatch(key):
                bag = out.people
            elif _EXCLUDE_AFTER.match(piece, m.end()):
                bag = out.exclude
            else:
                bag = out.keep
            if key not in {en_key(p) for p in bag}:
                bag.append(part)
    dropped = {en_key(p) for p in out.exclude}           # 한 번은 싣고 한 번은 빼라고 적었으면 빼기가 이긴다
    out.keep = [p for p in out.keep if en_key(p) not in dropped]
    return out


def people_count(tags: Iterable[str]) -> tuple[int, int, bool]:
    """영문 인원 태그 -> (여성 수, 남성 수, solo). 6+girls 는 여섯, multiple girls 는 셋(이벤트 맵 multiple 의 문턱).
    같은 성별을 둘 적었으면 큰 쪽."""
    girls = boys = 0
    solo = False
    for tag in tags:
        key = en_key(tag)
        m = re.fullmatch(r"(\d+)\+?\s*(girl|boy)s?", key)
        if m:
            if m.group(2) == "girl":
                girls = max(girls, int(m.group(1)))
            else:
                boys = max(boys, int(m.group(1)))
        elif key == "multiple girls":
            girls = max(girls, 3)
        elif key == "multiple boys":
            boys = max(boys, 3)
        elif key == "solo":
            solo = True
    return girls, boys, solo


def put_english(parts: Iterable[str], bags: list[list[str]], *, taken: Iterable[str] = ()) -> list[str]:
    """적힌 그대로 싣기. 같은 태그가 칸(bags)에 이미 있으면 **그 자리**를 사용자 표기로 바꾸고(1.2::crying:: ·
    Looking_at_viewer — bags 를 고친다), 없으면 돌려준다(부르는 쪽이 인원 · 이름 뒤에 싣는다).
    taken = 인원 · 캐릭터 이름처럼 다른 칸이 이미 말한 것 — 건너뛴다."""
    skip = {en_key(t) for t in taken}
    rest: list[str] = []
    for part in parts:
        key = en_key(part)
        if not key or key in skip:
            continue
        skip.add(key)
        found = False
        for bag in bags:
            for i, tag in enumerate(bag):
                if en_key(tag) == key:
                    bag[i] = part
                    found = True
        if not found:
            rest.append(part)
    return rest
