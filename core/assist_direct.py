"""Assist v2 — 'NAIA 추론 파이프라인 미사용' 모드(사용자 지정 2026-09-28).

한국어 층 · 경로 모델 · 고르기 · 되살리기 · 이벤트 맵 · 다듬기를 거치지 않고, 요청을 E2B 에 한 번 주어 **태그 + 영어 문장**을
받는다. 복잡한 장면(문 너머로 들으며 · 닭의 목을 비틀고)에서 태그 검색이 뜻을 잘게 부숴 엉뚱한 태그를 데려올 때 쓴다.

- 두 번 부른다(사용자 실험 09-28에서): ① 상황 — 요청을 쉬운 영어 문장으로(사용자 문구 그대로 · Q/E 는 등급 표시 · 속어
  풀이). ② 그 문장을 'Situation' 으로 곁들여 태그 + 문장. 한 번만 부르면 '닭의 목을 비틀고' 가 '소녀의 목을 부러뜨린다',
  엿듣기가 'listening to music', '거구의 주인' 이 huge breasts 가 됐다(E2B HauhauCS, 2회씩). ②를 영어만 보고 태그를
  뽑게 하면 구를 베껴 써서(window seat · girl hugged from behind) 한국어 요청도 함께 준다.
- 문법: {"tags":[…],"sentence":"…"} — 태그는 소문자 · 스물넷까지, 문장은 영문 · 기본 문장부호(괄호 없음 — WebUI 는 괄호를
  가중치로 읽는다).
- 모델의 태그는 사전 이름으로만 맞춘다(smiling -> smile) — 사전에 없는 것은 그대로 싣고 알린다. 인원(수동) · 고른 캐릭터는
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
- A Situation, if given, is how the request reads in English - follow it for who does what to whom.
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


# ① 상황 — 모양은 system 이 잡고, 물음은 사용자가 E2B 에 직접 해 본 문구 그대로(09-28). 피동 줄: 넣기 전 '가슴을
# 주물러지는 소녀' 가 'The girl rubs the chest' 가 됐다(넣은 뒤 3회 중 2회 'Someone rubs the girl's chest')
SITUATION_SYSTEM = """You read a Korean image request and say what happens in it as simple English sentences.
Who does what, to whom, where - and what is only heard or happens elsewhere. Slang and idioms in their real meaning.
Keep the passive: a Korean passive (~당하는, ~지는, ~기는, ~히는) means someone else does it to that person.
Only the sentences: no numbers, no lists, no explanations."""
MAX_SITUATION = 300
# 사용자가 붙인 등급 표시 그대로 — Q/E 에서만(explicit 표시를 주니 속어 '따먹히다' 를 바로 풀었다)
NSFW_FLAGS = {"q": "*user flagged nsfw (rating:questionable)", "e": "*user flagged nsfw (rating:explicit)"}


def glossary_hints(text: str, glossary: dict[str, str]) -> list[tuple[str, str]]:
    """요청에 글자 그대로 든 속어 · 드문 낱말의 풀이(규칙표 slang_glossary) — 형태소 분석 없이(파이프라인 미사용)."""
    source = clean_text(text)
    return [(ko, str(en)) for ko, en in (glossary or {}).items() if ko and ko in source and en]


def situation_message(text: str, rating: str, names: Iterable[tuple[str, str]] = (),
                      words: Iterable[tuple[str, str]] = ()) -> str:
    lines = [f'Split this korean prompt to set of situations: "{clean_text(text).strip()}" '
             "return only 1 option, listing simple sentence only, no explains."]
    known = [f"{clean_text(ko).strip()} = {en}" for ko, en in names if en]
    if known:
        lines.append(f"Names: {'; '.join(known)}")
    hints = [f"{ko} = {en}" for ko, en in words]
    if hints:
        lines.append(f"Words: {'; '.join(hints)}")
    if rating in NSFW_FLAGS:
        lines.append(NSFW_FLAGS[rating])
    return "\n".join(lines)


def situation_grammar() -> str:
    return "root ::= [A-Z] ch{8,%d}\nch ::= [A-Za-z0-9 ,.'!?-]" % (MAX_SITUATION - 1)


def parse_situation(reply: str | None) -> str:
    """상황 답 -> 한 줄(목록 번호 '1. ' 을 떼고 공백 정리). 못 읽으면 "".
    번호는 맨 앞이나 문장 끝 뒤에서 공백이 따르는 것만 — 문장 안 숫자(1.5 liter · number 1.)를 망가뜨렸다(Codex 9차 N2)."""
    text = " ".join(re.sub(r"(?:^|(?<=[.!?]\s))\d+\.\s+", "", " ".join(str(reply or "").split())).split())
    return text if re.search(r"[A-Za-z]{2}", text) else ""


def direct_message(text: str, rating: str, names: Iterable[tuple[str, str]] = (), people: str = "",
                   situation: str = "") -> str:
    """names = 고른 캐릭터(원문의 이름, 문장에 쓸 영어 이름) · people = 수동 인원(정해졌으면 모델은 인원 태그를 안 쓴다) ·
    situation = ① 상황 단계가 옮긴 영어(없으면 요청만)."""
    lines = [f"Request: {clean_text(text).strip()}"]
    known = [f"{clean_text(ko).strip()} = {en}" for ko, en in names if en]
    if known:
        lines.append(f"Names: {'; '.join(known)}")
    if people:
        lines.append(f"People (already set, do not write counts): {people}")
    if situation:
        lines.append(f"Situation: {situation}")
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
