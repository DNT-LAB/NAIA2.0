"""Assist v2 — 직역 도구(사용자 제안 2026-09-25): 한국어 요청을 과장 없이 영어 한 문장으로 옮긴다(E2B 1회 · 문법으로 잠금).

'손가락으로 브이 표시를 하고 있는 소녀' 가 1girl, solo, sign 이 됐다 — 경로(E2B)가 항목마다 영문을 지어내며 v sign ·
finger 가 나왔다. 사용자: "먼저 사용자의 입력을 최대한 과장 없이 번역하라고 1회 지시합니다(스키마로 강하게 억제) … tool 로".

- 문법: {"en":"…"} — 영문 · 숫자 · 기본 문장부호만. 한국어 · 따옴표 · 줄바꿈이 끼지 않고, 길이는 요청 길이에 묶인다.
- 태그로 바꾸지 않는다(그건 뒤 단계의 일) — 적힌 것을 적힌 차례대로, 덧붙이지 않고.
- 부르는 쪽(서비스)이 온도 0 으로 부르고 같은 글은 다시 묻지 않는다.
"""
from __future__ import annotations

import json
import re

from core.assist_korean import clean_text

LITERAL_SYSTEM = """Translate the Korean request into English, literally.
- Keep every detail the user wrote, in the same order. Add nothing: no adjectives, no guesses, no mood, no style, no explanation.
- Use plain everyday words. Do not turn words into Danbooru tags.
- Write names as they sound, in English letters.
Answer with one sentence.

Examples:
Request: 창가에 앉아 책을 읽는 소녀
{"en":"a girl sitting by the window reading a book"}
Request: 우산을 쓰고 눈 오는 거리를 걷는다
{"en":"walking on a snowy street under an umbrella"}"""

_CHAR = "[A-Za-z0-9 ,.'?!()-]"


def literal_message(text: str) -> str:
    return f"Request: {clean_text(text).strip()}"


def literal_limit(text: str) -> int:
    """직역 길이 상한(글자) — 요청의 세 배 남짓. 덧붙일 자리를 주지 않는다."""
    return max(40, min(300, 3 * len(clean_text(text).strip()) + 20))


def literal_grammar(text: str) -> str:
    return 'root ::= "{\\"en\\":\\"" ch{1,%d} "\\"}"\nch ::= %s' % (literal_limit(text), _CHAR)


def parse_literal(reply: str | None) -> str | None:
    """모델 답 -> 직역 한 문장(공백 정리). 모양이 깨졌거나 글자가 없으면 None — 부르는 쪽은 직역 없이 간다."""
    try:
        data = json.loads(reply or "")
    except ValueError:
        return None
    en = " ".join(str(data.get("en") or "").split()) if isinstance(data, dict) else ""
    return en if re.search(r"[A-Za-z]{2}", en) else None
