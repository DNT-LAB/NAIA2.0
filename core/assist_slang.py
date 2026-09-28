"""Assist — 속어 · 비속어 풀이(영어). [NAIA 추론 파이프라인 미사용] 의 상황 단계가 요청에 그 낱말이 있을 때만 'Words:' 줄로
모델에 준다(core/assist_direct). E2B 는 '모가지를 비틀다' 를 머리카락 · 병을 비트는 것으로, '교배' 를 약혼으로 읽었다(09-28).

풀이는 두 갈래다:
- 손으로 쓴 것: ``data/assist/korean_rules.json`` 의 ``slang_glossary`` — 글자 그대로 맞춘다(짧게 고른 것이라).
- 위키낱말사전(English Wiktionary)에서 고른 것: ``data/assist/slang_glossary_wiktionary.json`` — ``tools/build_slang_glossary.py``
  가 kaikki.org 원본에서 한국어 표제어 중 속된 뜻(vulgar · slang · derogatory · offensive · Internet · 성 주제)이 있는 것만
  고른다. **CC BY-SA 4.0**(옆의 ``.LICENSE.txt``) — 손으로 쓴 것과 한 파일로 합치지 않는다.

위키낱말사전 풀이는 조심해서 쓴다:
- 낱말의 뜻을 차례대로 함께 준다(속된 뜻엔 표시) — 따먹다의 첫 뜻은 '따서 먹다' 다. 속된 뜻만 주면 '사과를 따먹는' 이 틀어진다.
- 성적인 뜻은 Q · E 에서만 — G · S 에선 그 뜻을 빼고(남는 뜻이 없으면 낱말째) 준다. 등급이 사용자의 뜻이다.
- 맞추기: 세 음절 이상 · 두 음절 동사 줄기는 글자 그대로, 나머지는 Kiwi 토막이 그 꼴 · 품사(명사 · 용언)와 같을 때만 —
  '씹'(명사) 이 '껌을 씹는'(동사) 에, '보지' 가 '보지 않는' 에 걸리지 않게. 토막이 없으면(Kiwi 없음) 그런 낱말은 쓰지 않는다.
"""
from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from core.assist_korean import clean_text

GLOSSARY_PATH = Path(__file__).resolve().parents[1] / "data" / "assist" / "slang_glossary_wiktionary.json"
MAX_HINTS = 8                 # 한 요청에 줄 풀이 수 상한 — 입력이 길어지면 E2B 가 흐려진다
MAX_SENSES = 3
_NOUN_TAGS = ("NNG", "NNP", "NNB", "XR")
_VERB_TAGS = ("VV", "VA")
_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {}


def load_glossary(path: Path | None = None) -> dict[str, Any]:
    """위키낱말사전 풀이 파일 -> entries(낱말 -> {key, kind, senses}). 없거나 깨졌으면 빈 dict(손으로 쓴 것만 쓴다)."""
    target = Path(path or GLOSSARY_PATH)
    with _LOCK:
        key = str(target)
        if key not in _CACHE:
            try:
                data = json.loads(target.read_text(encoding="utf-8"))
                ok = data.get("kind") == "assist_slang_glossary" and data.get("schema_version") == 1
                _CACHE[key] = (data.get("entries") or {}) if ok else {}
            except (OSError, ValueError):
                _CACHE[key] = {}
        return _CACHE[key]


def _sense_text(senses: Iterable[dict[str, Any]], sexual_ok: bool) -> str:
    """보일 뜻 — 속된 뜻(표시)이 먼저, 평범한 뜻은 뒤에. 원래 차례대로 줬더니 '개같이 따먹히는 메이드'(E) 의 상황이
    'The maid is picked.' 가 됐다(따먹다 = 따서 먹다 · … · 성관계 — E2B 가 첫 뜻을 골랐다, 09-28 견주기). 풀이는 E2B 가 모르는
    속된 뜻을 알리려는 것이다. 보일 뜻에 속된 뜻 · 성적 뜻이 하나도 없으면 "" — G · S 에서 성적 뜻을 빼고 나면 평범한 뜻만
    남는 낱말(자다 = to sleep)은 풀이가 소음이다."""
    senses = list(senses)
    senses = ([s for s in senses if s.get("tags") or s.get("sexual")]
              + [s for s in senses if not (s.get("tags") or s.get("sexual"))])
    out = []
    marked = False
    for sense in senses:
        if sense.get("sexual") and not sexual_ok:
            continue
        en = str(sense.get("en") or "").strip()
        if not en:
            continue
        tags = sense.get("tags") or ()
        mark = "vulgar" if "vulgar" in tags else "slang" if tags else ""
        marked = marked or bool(tags) or bool(sense.get("sexual"))
        out.append(f"({mark}) {en}" if mark else en)
    return "; ".join(out[:MAX_SENSES]) if marked else ""


# 용언 줄기 바로 뒤에 오는 어미 · 피동 접사의 첫 글자(따먹히는 · 떡치다가) — '하' 는 없다(느끼하다 · 갈구하다 는 다른 낱말)
_ENDING_HEADS = frozenset("고는다며서아어여지게던면기았었겠네요니나냐자라려은을히혀리")


def _verb_in_text(stem: str, source: str) -> bool:
    """두 음절 동사 줄기가 글자로 나오고 바로 뒤가 어미인가(떡치다가 · 따먹는). 뒤가 비었어도 맞다(요청 끝)."""
    start = source.find(stem)
    while start >= 0:
        tail = source[start + len(stem):start + len(stem) + 1]
        if not tail or tail in _ENDING_HEADS or not ("가" <= tail <= "힣"):
            return True
        start = source.find(stem, start + 1)
    return False


def hints(text: str, rating: str, *, hand: dict[str, str] | None = None, tokens: Iterable[tuple[str, str]] | None = None,
          entries: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    """요청에 든 속어 풀이 [(낱말, 영어 풀이)] — 손으로 쓴 것이 먼저(같은 낱말이면 그것만), 합쳐 MAX_HINTS 까지.
    tokens = Kiwi 토막(꼴, 품사) — 짧은 표제어는 토막으로만 맞춘다."""
    source = clean_text(text)
    # 손 풀이는 글자 그대로 — 끝이 '-' 면 용언 줄기라 바로 뒤가 어미 · 피동 접사일 때만('들어서 박-' 이 '들어서 박물관' ·
    # '들고 박-' 이 '들고 박스' 에 걸렸다, 09-28)
    out: list[tuple[str, str]] = []
    for ko, en in (hand or {}).items():
        if not ko or not en:
            continue
        stem = ko[:-1] if ko.endswith("-") else ""
        if (stem and _verb_in_text(stem, source)) or (not stem and ko in source):
            out.append((stem or ko, str(en)))
    taken = {ko for ko, _en in out}
    sexual_ok = rating in ("q", "e")
    toks = list(tokens or [])
    nouns = {form for form, tag in toks if tag.startswith(_NOUN_TAGS)}
    verbs = {form for form, tag in toks if tag.startswith(_VERB_TAGS)}
    # Kiwi 가 모르는 두 음절 속어 명사는 명사 둘로 쪼갠다(눈뽕 -> 눈 + 뽕, 09-28) — 붙은 명사 토막 둘도 그 꼴로 본다.
    # '보지 않는' 은 보(동사) + 지(어미)라 아니다
    pairs = {a + b for (a, ta), (b, tb) in zip(toks, toks[1:])
             if ta.startswith(_NOUN_TAGS) and tb.startswith(_NOUN_TAGS)}
    for word, entry in (load_glossary() if entries is None else entries).items():
        if len(out) >= MAX_HINTS:
            break
        key = str(entry.get("key") or word)
        if word in taken or not key:
            continue
        verb = entry.get("kind") == "verb"
        # 세 음절 이상은 글자 그대로. 두 음절 동사 줄기(떡치 · 따먹 — Kiwi 는 이런 속어 동사를 떡+치 로 쪼갠다)는 토막으로
        # 맞거나, 글자로 맞되 Kiwi 가 그것을 명사로 내지 않았고 바로 뒤가 어미일 때만 — 기차다 가 '기차를' 에, 느끼다 가
        # '느끼하다' 에 걸렸다(검토 09-28). 나머지(한 음절 · 두 음절 명사 — '보지 않는')는 토막의 꼴 · 품사로만
        if len(key) >= 3:
            hit = key in source
        elif verb and len(key) == 2:
            hit = key in verbs or (key not in nouns and _verb_in_text(key, source))
        else:
            hit = key in (verbs if verb else nouns) or (not verb and len(key) == 2 and key in pairs and key in source)
        if not hit:
            continue
        gloss = _sense_text(entry.get("senses") or (), sexual_ok)
        if gloss:
            out.append((word, gloss))
            taken.add(word)
    return out[:MAX_HINTS]
