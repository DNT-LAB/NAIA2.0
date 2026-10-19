"""스테이징 추가 프롬프트 — 뽑힌 조합의 게시물 태그 뒤에 붙이는 글(사용자 지시 2026-10-19).

둘이 있다: 스테이징 공통 하나(`{on, text, mode}`)와 조합마다 하나(`{on, text}`). 무엇을 붙일지는 공통 쪽의
`mode`(S 창 하단 [옵션])가 정한다 - 개별 추가 프롬프트가 있는 조합에서만 갈린다.

  · merge(기본)      개별 + 공통을 합친다
  · common_only      공통만(개별은 무시)
  · item_first       개별이 있으면 개별만, 없으면 공통

합칠 때는 **집합**이다 - 같은 태그는 한 번만(사용자 지정 "set 방식"). 메인 칸에 이미 있는 태그도 다시 붙이지 않는다
(그쪽은 `prompt_processor` 가 붙일 때 거른다). 붙이는 자리 = PE(post_processing) 필터 **뒤**, 와일드카드 전개 **앞** -
사용자가 쓴 글이라 Auto Hide · remove_* 에 지워지지 않고, `__wildcard__` 는 그대로 펼쳐진다(안 B).

스테이징 파일 · 저장된 조합(묶음) 둘 다 이 모양을 쓴다 - 옛 파일 · 이상한 값은 꺼짐 · 빈 글로 읽는다(파일을 거부하지 않는다).
"""
from __future__ import annotations

from core.event_map.service import MapQueryError

MAX_TEXT = 2000
MODES = ("merge", "common_only", "item_first")


def extra_of(value) -> dict:
    """조합 하나의 추가 프롬프트. 읽기용 - 이상한 값은 꺼짐 · 빈 글."""
    if not isinstance(value, dict):
        return {"on": False, "text": ""}
    text = value.get("text")
    return {"on": value.get("on") is True, "text": text.strip()[:MAX_TEXT] if isinstance(text, str) else ""}


def common_of(value) -> dict:
    """공통 추가 프롬프트 + 고르는 방식. 읽기용."""
    base = extra_of(value)
    mode = value.get("mode") if isinstance(value, dict) else None
    base["mode"] = mode if mode in MODES else "merge"
    return base


def is_blank(extra: dict, common: bool = False) -> bool:
    """기본값 그대로인가(저장할 것이 없다)."""
    return not extra.get("on") and not extra.get("text") and (not common or extra.get("mode") == "merge")


def clean_text(value) -> str:
    """쓰기용 - 길이를 넘으면 자르지 않고 거부한다(사용자가 쓴 글을 몰래 줄이지 않는다)."""
    if not isinstance(value, str) or len(value) > MAX_TEXT:
        raise MapQueryError("bad_request", f"추가 프롬프트는 {MAX_TEXT:,}자까지입니다.")
    return value.strip()


def clean_mode(value) -> str:
    if value not in MODES:
        raise MapQueryError("bad_request", "추가 프롬프트 방식을 확인해주세요.")
    return value


_WILDCARD_MARKS = ("__", "<", "$", "{")


def tag_key(tag: str) -> str:
    """같은 태그인지 가르는 키 - 소문자 · 밑줄 = 빈칸. 와일드카드 구문(`__x__` · `<x>` · `$x` · `{a|b}`)은 글 그대로 -
    밑줄을 풀면 `__sweat__` 가 태그 `sweat` 와 같아져 전개 전에 지워진다(Codex 리뷰 2026-10-19).
    `prompt_processor._apply_staging_extra` 가 같은 규칙을 쓴다."""
    text = tag.strip().lower()
    if any(mark in text for mark in _WILDCARD_MARKS):
        return text
    return " ".join(text.replace("_", " ").split())


def resolve(common, item) -> list[str]:
    """뽑힌 조합에 붙일 태그 - 방식에 따라 고르고, 겹치는 태그는 한 번만(앞의 것이 남는다)."""
    from core.wildcard_processor import split_tags_smart

    common, own = common_of(common), extra_of(item)
    mine = split_tags_smart(own["text"]) if own["on"] and own["text"] else []
    shared = split_tags_smart(common["text"]) if common["on"] and common["text"] else []
    if common["mode"] == "common_only":
        parts = shared
    elif common["mode"] == "item_first":
        parts = mine or shared
    else:
        parts = mine + shared
    seen, out = set(), []
    for tag in parts:
        tag = str(tag or "").strip()
        if tag and tag_key(tag) not in seen:
            seen.add(tag_key(tag))
            out.append(tag)
    return out
