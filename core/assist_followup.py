"""Assist v2 — 이어 고치기(사용자 지정 2026-09-28: 기본은 새 검색, 이어 고치기는 따로 켠다).

받은 결과(메인 = 태그들, 문장 · 캐릭터 칸)에 한국어로 한 가지를 더 바라면 E2B 한 번으로 **뺄 태그 · 더할 태그 · 다시 쓴 문장**을
받는다. 인원 · 등급 정보는 주지 않는다(사용자 제안) — 인원 태그 · 캐릭터 이름은 그대로 둔다.

- 빼기는 문법으로 **이전 태그 안에서만** 고른다. 그래도 모델은 넘치게 뺀다(시도 8회 중 4회 — '비는 그치고 노을로' 에서 우산 ·
  신호등까지) — 부르는 쪽이 요청 낱말이 가리키는 태그만 받는다.
- 더하기는 사전 이름 그대로인 것만 — 부르는 쪽이 맞춘다.
- 관계성 지도의 '바꾸기' 는 쓰지 않는다(사용자: 관계성 지도는 메인 프롬프트 전용 · 쓰면 제어가 어려워진다).
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from core.assist_korean import clean_text

FOLLOWUP_SYSTEM = """You edit the Danbooru tags and the English sentence of an image prompt the user already has.
The user sends one more wish in Korean. Keep every previous tag unless the wish changes or cancels it.
- remove: only previous tags the wish changes or cancels. Usually none. Tags on a Character line can be removed too.
- add: Danbooru tags for what the wish asks and the tags miss (up to 6).
- sentence: the previous Sentence rewritten so it also says the wish. Keep what it already says.
  Do not copy the Character lines into the sentence.
Never add people counts (1girl, solo), quality or rating tags. Answer JSON only."""

MAX_ADD = 6
MAX_REMOVE = 6
MAX_SENTENCE = 260
# 메인의 문장 = 대문자로 시작하고 낱말이 셋 이상인 조각부터 끝까지(태그는 소문자다 — 문장 안의 쉼표도 문장이다)
_SENTENCE_START = re.compile(r"^[A-Z][^,]*\s\S+\s\S+")


@dataclass
class Followup:
    remove: list[str] = field(default_factory=list)
    add: list[str] = field(default_factory=list)
    sentence: str = ""


def split_main(main: str) -> tuple[list[str], str]:
    """메인 프롬프트 -> (태그들, 끝의 문장). 줄바꿈은 쉼표로 본다(결과 칸에서 고친 글)."""
    parts = [p.strip() for p in re.split(r"[,\n]", str(main or ""))]
    for i, part in enumerate(parts):
        if _SENTENCE_START.match(part):
            return [p for p in parts[:i] if p], ", ".join(p for p in parts[i:] if p)
    return [p for p in parts if p], ""


def followup_message(tags: Iterable[str], sentence: str, wish: str,
                     characters: Iterable[tuple[str, list[str]]] = ()) -> str:
    """characters = (캐릭터 이름 태그, 그 칸의 나머지 태그) — 빼기는 캐릭터 칸의 태그도 고를 수 있다."""
    lines = ["Previous answer:", f"Tags: {', '.join(tags)}"]
    for name, attrs in characters:
        if attrs:
            lines.append(f"Character tags ({name}): {', '.join(attrs)}")
    if sentence:
        lines.append(f"Sentence: {sentence}")
    lines.append(f"User message: {clean_text(wish).strip()}")
    return "\n".join(lines)


def _gbnf(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def followup_grammar(removable: Iterable[str]) -> str:
    """빼기 = 이전 태그 목록에서만(문법이 강제). 목록이 비면 빼기는 [] 뿐."""
    names = [t for t in dict.fromkeys(removable) if t and '"' not in t and "\\" not in t]
    rlist = ('"[]"' if not names else
             '"[]" | "[" rtag ("," rtag){0,%d} "]"' % (MAX_REMOVE - 1))
    lines = [
        'root ::= "{\\"remove\\":" rlist ",\\"add\\":" alist ",\\"sentence\\":\\"" ch{10,%d} "\\"}"' % MAX_SENTENCE,
        f"rlist ::= {rlist}",
        'alist ::= "[]" | "[" atag ("," atag){0,%d} "]"' % (MAX_ADD - 1),
        'atag ::= "\\"" [a-z0-9 ()\'.:_-]{1,40} "\\""',
        "ch ::= [A-Za-z0-9 ,.'!?-]",
    ]
    if names:
        lines.insert(2, "rtag ::= " + " | ".join(f'"\\"{_gbnf(t)}\\""' for t in names))
    return "\n".join(lines)


def parse_followup(reply: str | None, removable: Iterable[str]) -> Followup | None:
    """모델 답 -> Followup(빼기는 이전 태그 안의 것만 · 더하기 정리 · 문장 공백 정리). 모양이 깨졌으면 None."""
    try:
        data = json.loads(reply or "")
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    allowed = {tag_key(t): t for t in removable}           # 빼기는 이전 태그의 적힌 꼴 그대로 돌려준다(Long_Hair)

    def tags(value: object) -> list[str]:
        return list(dict.fromkeys(tag_key(t) for t in (value if isinstance(value, list) else []) if str(t).strip()))
    sentence = " ".join(str(data.get("sentence") or "").split()).lstrip(" .,!?'-")     # '. A girl …' (실측)
    return Followup(remove=[allowed[t] for t in tags(data.get("remove")) if t in allowed][:MAX_REMOVE],
                    add=tags(data.get("add"))[:MAX_ADD],
                    sentence=sentence if re.search(r"[A-Za-z]{2}", sentence) else "")


def tag_key(tag: object) -> str:
    """태그 견주기 열쇠 — 소문자 · 밑줄은 공백 · 공백 하나로."""
    return " ".join(str(tag).replace("_", " ").split()).lower()
