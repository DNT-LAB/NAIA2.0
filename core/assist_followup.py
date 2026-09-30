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
from collections.abc import Callable, Iterable
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


@dataclass
class Followup:
    remove: list[str] = field(default_factory=list)
    add: list[str] = field(default_factory=list)
    sentence: str = ""


def split_main(main: str, sentence: str = "", is_tag: Callable[[str], bool] | None = None) -> tuple[list[str], str]:
    """메인 프롬프트 -> (태그들, 끝의 문장). 줄바꿈은 쉼표로 본다(결과 칸에서 고친 글).
    - sentence = 받은 결과의 문장(다듬기 · 고치기 · 직접) — 메인이 그것으로 끝나면 그대로 가른다(문장 안의 쉼표도 문장).
    - 아니면(문장을 고쳤다) 대문자로 시작하고 두 낱말 이상 · 사전 태그가 아닌 조각부터 끝까지를 문장으로 본다 — 끝이 문장부호면
      그 자리를, 없으면 네 낱말 이상인 자리를. 대문자 · 낱말 수만 보면 'Looking at viewer' 를 문장으로, 'Kanade smiles, …' 를
      태그로 읽었다(Codex 리뷰 09-28 F4)."""
    text = ", ".join(p.strip() for p in str(main or "").split("\n") if p.strip())
    known = " ".join(str(sentence or "").split())
    pieces = lambda s: [p.strip() for p in s.split(",") if p.strip()]   # noqa: E731
    if known and known in text:
        # 받은 문장이 그대로 있다 — 그 앞뒤가 태그다(문장 뒤에 덧붙인 TV, monochrome 을 문장으로 삼켜 태그 필터를 비켜 갔다 —
        # Codex H1 ①)
        at = text.rfind(known)
        return pieces(text[:at]) + pieces(text[at + len(known):]), known
    parts = pieces(text)
    ended = lambda i: bool(re.search(r"[.!?]$", parts[i]))        # noqa: E731

    def run_from(i: int) -> tuple[list[str], str]:
        """i 부터 첫 끝 문장부호까지가 문장 — 그 뒤 조각은 태그다(없으면 끝까지)."""
        j = next((k for k in range(i, len(parts)) if ended(k)), len(parts) - 1)
        return parts[:i] + parts[j + 1:], ", ".join(parts[i:j + 1])
    # 받은 문장의 뒤쪽만 고쳤으면(마침표를 지웠다) 그 문장의 첫 조각이 그대로 남아 있다 — 거기서 가른다(Codex 9차 F4)
    first = known.split(",")[0].strip() if known else ""
    if first and len(first.split()) >= 2 and first in parts:
        return run_from(len(parts) - 1 - parts[::-1].index(first))

    def starts(i: int, min_words: int) -> bool:
        part = parts[i]
        return bool(re.match(r"^[A-Z]", part)) and len(part.split()) >= min_words and not (is_tag and is_tag(part))
    ends = any(ended(i) for i in range(len(parts)))
    for i in range(len(parts)):
        if starts(i, 2 if ends else 4):
            return run_from(i)
    # 소문자로 고친 문장(a girl sleeps peacefully.) — 대문자 규칙에 안 걸려 태그로 실렸다(저빈도 필터가 지웠다, Codex H1 ①).
    # 태그 사전이 있을 때만: 끝 문장부호가 있는 세 낱말 이상 조각에서 거슬러, 사전 태그가 아닌 두 낱말 이상 조각까지
    if is_tag is not None:
        for j in range(len(parts)):
            if ended(j) and len(parts[j].split()) >= 3 and not is_tag(parts[j]):
                i = j
                while i > 0 and len(parts[i - 1].split()) >= 2 and not ended(i - 1) and not is_tag(parts[i - 1]):
                    i -= 1
                return parts[:i] + parts[j + 1:], ", ".join(parts[i:j + 1])
    return parts, ""


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
