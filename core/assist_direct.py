"""Assist v2 — 'NAIA 추론 파이프라인 미사용' 모드(사용자 지정 2026-09-28).

한국어 층 · 경로 모델 · 고르기 · 되살리기 · 이벤트 맵 · 다듬기를 거치지 않고, 요청을 E2B 에 한 번 주어 **태그 + 영어 문장**을
받는다. 복잡한 장면(문 너머로 들으며 · 닭의 목을 비틀고)에서 태그 검색이 뜻을 잘게 부숴 엉뚱한 태그를 데려올 때 쓴다.

- 문법: {"tags":[…],"sentence":"…"} — 태그는 소문자 · 스물넷까지, 문장은 영문 · 기본 문장부호(괄호 없음 — WebUI 는 괄호를
  가중치로 읽는다).
- 모델의 태그는 사전 이름으로만 맞춘다(smiling -> smile) — 사전에 없는 것은 싣지 않고 알린다. 인원(수동) · 고른 캐릭터는
  부르는 쪽이 앞에 붙인다.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from core.assist_korean import clean_text

DIRECT_SYSTEM = """You write an image prompt from a Korean request: Danbooru tags and one English sentence.
- tags: the Danbooru tags the picture needs - people counts first (1girl, 1boy, 2girls) when people are in the picture,
  then what they do, their look, the place and the framing. Real Danbooru tag names, lowercase.
  Only what the request says - no pose, mood or look it does not ask for.
  Only what is seen in the picture: something only heard or happening elsewhere gets a tag for that (offscreen sex,
  eavesdropping), not the act itself.
- sentence: one English sentence that says the scene as the request does - who does what, to whom, and where.
  Call a character by the English name in Names. Never make up a name.
- Follow the Rating. Never add quality or rating tags. Answer JSON only.

Example:
Request: 창가에 앉아 턱을 괴고 비 오는 밖을 바라보는 소녀
Rating: general
{"tags":["1girl","sitting","window","rain","hand on own chin","looking outside","indoors"],"sentence":"A girl sits by the rainy window with her chin in her hand, gazing outside."}"""

MAX_TAGS = 24
MAX_SENTENCE = 260
# 등급 낱말 — 'sensitive' 를 E2B 가 관능(sensual pose)으로 읽었다(닭의 목을 비트는 카나데, S · 시도 09-28)
RATING_WORDS = {"g": "general (no nudity)", "s": "general (mild fanservice is fine)",
                "q": "suggestive (partial nudity is fine)", "e": "explicit (sexual content is fine)"}


@dataclass
class Direct:
    tags: list[str] = field(default_factory=list)
    sentence: str = ""


def direct_message(text: str, rating: str, names: Iterable[tuple[str, str]] = (), people: str = "") -> str:
    """names = 고른 캐릭터(원문의 이름, 문장에 쓸 영어 이름) · people = 수동 인원(정해졌으면 모델은 인원 태그를 안 쓴다)."""
    lines = [f"Request: {clean_text(text).strip()}"]
    known = [f"{clean_text(ko).strip()} = {en}" for ko, en in names if en]
    if known:
        lines.append(f"Names: {'; '.join(known)}")
    if people:
        lines.append(f"People (already set, do not write counts): {people}")
    lines.append(f"Rating: {RATING_WORDS.get(rating, 'general')}")
    return "\n".join(lines)


def direct_grammar() -> str:
    return ('root ::= "{\\"tags\\":[" tag ("," tag){0,%d} "],\\"sentence\\":\\"" ch{10,%d} "\\"}"\n'
            'tag ::= "\\"" [a-z0-9 ()\'.:_-]{1,40} "\\""\n'
            "ch ::= [A-Za-z0-9 ,.'!?-]" % (MAX_TAGS - 1, MAX_SENTENCE))


def parse_direct(reply: str | None) -> Direct | None:
    """모델 답 -> Direct(태그 정리 · 중복 제거, 문장 공백 정리). 모양이 깨졌으면 None."""
    try:
        data = json.loads(reply or "")
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    tags = [" ".join(str(t).replace("_", " ").split()).lower() for t in data.get("tags") or [] if str(t).strip()]
    sentence = " ".join(str(data.get("sentence") or "").split()).lstrip(" .,!?'-")     # '. A girl …' (실측)
    return Direct(tags=list(dict.fromkeys(tags))[:MAX_TAGS],
                  sentence=sentence if re.search(r"[A-Za-z]{2}", sentence) else "")
