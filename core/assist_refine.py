"""Assist v2 — 다듬기 도구(사용자 제안 2026-09-25): 원문과 태그를 함께 E2B 에 주고, 틀린 태그는 빼고 빠진 것은 더하고,
장면을 그리는 영어 문장 하나를 받는다. 메인은 '태그들, 문장' — Boost v2 의 태그 + 자연어 느낌.

'캠프파이어 앞에서 불멍을 때리며 침을 흘리고 있는 살짝 잠들듯 말듯한 소녀' 가 drooling, fire, sleeping, campfire, staring 이
됐다(불멍 -> staring + fire 로 쪼갬 · 잠들듯 말듯 -> sleeping · 앉은 자세 빠짐). 사용자: "원문과 태그를 함께 줘서 틀린 것을
고치고, 보강할 부분을 보강" · "최종 응답이 메인을 통해 danbooru 태그 + 자연어 결합으로".

- 문법: {"remove":[…],"add":[…],"sentence":"…"} — 태그는 소문자(여섯까지), 문장은 영문 · 기본 문장부호(괄호 없음 — WebUI 는
  괄호를 가중치로 읽는다).
- 모델의 답은 제안일 뿐이다. 빼기는 지금 태그 안에서만, 더하기는 태그 이름 그대로인 것만(검증 · 등급 게이트는 부르는 쪽).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from core.assist_korean import clean_text

REFINE_SYSTEM = """You check the Danbooru tags made for a Korean image request.
- remove: tags that do not fit the request (a wrong meaning, or something the request does not ask for).
- add: up to 4 Danbooru tags for what the request clearly says but the tags miss (pose, expression, place, framing).
- sentence: one English sentence that describes the picture - what the request says, with a light touch of mood. No names.
Never add people counts (1girl, solo), quality or rating tags. Answer JSON only.

Example:
Request: 창가에 앉아 턱을 괴고 비 오는 밖을 바라보는 소녀
Tags: sitting, window, rain, hand on own chin, staring
{"remove":["staring"],"add":["looking outside"],"sentence":"A girl sits by the rainy window with her chin in her hand, gazing outside."}"""

MAX_ADD = 4
MAX_REMOVE = 3
MAX_SENTENCE = 240


@dataclass
class Refine:
    remove: list[str] = field(default_factory=list)
    add: list[str] = field(default_factory=list)
    sentence: str = ""


def refine_message(text: str, tags: list[str], literal: str | None = None) -> str:
    lines = [f"Request: {clean_text(text).strip()}"]
    if literal:
        lines.append(f"Literal English: {literal}")
    lines.append(f"Tags: {', '.join(tags)}")
    return "\n".join(lines)


def refine_grammar() -> str:
    return ('root ::= "{\\"remove\\":" list ",\\"add\\":" list ",\\"sentence\\":\\"" ch{10,%d} "\\"}"\n'
            'list ::= "[]" | "[" tag ("," tag){0,5} "]"\n'
            'tag ::= "\\"" [a-z0-9 ()\'.:-]{1,40} "\\""\n'
            "ch ::= [A-Za-z0-9 ,.'!?-]" % MAX_SENTENCE)


_STOP = {"on", "in", "at", "of", "the", "a", "an", "own", "with", "and", "to", "from", "by", "her", "his", "their"}


def _forms(word: str) -> set[str]:
    out = {word, word + "s", word + "ing"}
    for suffix, repl in (("ing", ""), ("ing", "e"), ("s", ""), ("es", ""), ("ly", ""), ("ed", ""), ("ed", "e")):
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            out.add(word[: -len(suffix)] + repl)
    if word.endswith("ing") and len(word) > 5 and word[-4] == word[-5]:
        out.add(word[:-4])                                            # sitting -> sit · running -> run
    return out


def mentions(tag: str, sentence: str) -> bool:
    """모델 자신의 문장이 그 태그를 말하나 — 태그의 내용어가 전부 문장에 있다(복수 · -ing · -ly · -ed 허용).
    다듬기의 자기 일관성: 문장에서 말한 것은 빼지 않고(밤바다 문장에서 night 를 빼며 'at night' 라 썼다), 더할 것은
    문장에서 말한 것만(벤치 모의: 기대 태그를 잘못 뺀 것 15 -> 3, 09-25)."""
    have: set[str] = set()
    for w in re.findall(r"[a-z]+", sentence.lower()):
        have |= _forms(w)
    words = [w for w in re.findall(r"[a-z]+", tag.lower()) if w not in _STOP]
    return bool(words) and all(_forms(w) & have for w in words)


def parse_refine(reply: str | None) -> Refine | None:
    """모델 답 -> Refine(빼기 셋 · 더하기 넷까지, 문장 공백 정리). 모양이 깨졌으면 None — 부르는 쪽은 다듬지 않고 간다."""
    try:
        data = json.loads(reply or "")
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None

    def tags(value: object) -> list[str]:
        out = [" ".join(str(t).split()).lower() for t in (value if isinstance(value, list) else []) if str(t).strip()]
        return list(dict.fromkeys(out))
    sentence = " ".join(str(data.get("sentence") or "").split())
    return Refine(remove=tags(data.get("remove"))[:MAX_REMOVE], add=tags(data.get("add"))[:MAX_ADD],
                  sentence=sentence if re.search(r"[A-Za-z]{2}", sentence) else "")
