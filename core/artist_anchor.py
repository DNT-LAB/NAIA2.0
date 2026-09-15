# -*- coding: utf-8 -*-
"""Artist anchors — `<anchor:ID>` placeholders inside prefix/postfix.

The mix queue can pin groups of artist tags to places the user picks instead of
dumping them all in front of the prefix. The user drops a marker into the prefix or
postfix text::

    <anchor:1>, 1girl, masterpiece, <anchor:2>

and each group's composed artist tags are substituted where its marker sits. Blocks
that live before the first anchor keep the old behaviour (prepended to the prefix).

⚠️ **This module is the only definition of the grammar.** The frontend mirrors the
   pattern in `js/features/artistAnchors.mjs`; a contract test compares the two
   literals. Two spellings of "what counts as an anchor" would mean the panel says
   the marker is fine while the server drops it (or the reverse).

⚠️ **An unresolved anchor must never reach the model.** `expand_tags` is called on
   every generation, groups or not — with no groups it degrades to a scrubber. Left
   in, `<anchor:1>` is just a weird tag the model tries to draw.

Strict parsing is deliberate. `< anchor:1 >` and `<anchor: 1>` are NOT anchors, so a
typo shows up as a broken marker (the panel turns that group red) instead of being
silently accepted in one half of the app and rejected in the other.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

# 프론트(`artistAnchors.mjs`)와 **같은 글자**여야 한다 - 계약 시험이 대조한다.
ANCHOR_PATTERN_SOURCE = r"<anchor:([A-Za-z0-9_-]{1,32})>"
ANCHOR_PATTERN = re.compile(ANCHOR_PATTERN_SOURCE)

# 아이디 자체의 규칙(만들 때 쓴다). 위 패턴의 캡처와 같은 집합이어야 한다.
ANCHOR_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def anchor_token(anchor_id: Any) -> str:
    """`1` -> `<anchor:1>`. 규칙에 안 맞는 아이디는 거절한다."""
    text = str(anchor_id or "").strip()
    if not ANCHOR_ID_PATTERN.match(text):
        raise ValueError(f"invalid anchor id: {text!r}")
    return f"<anchor:{text}>"


def find_anchor_ids(text: Any) -> list[str]:
    """글 안에 나온 순서대로. 같은 아이디가 두 번 나오면 두 번 들어 있다 -
    중복은 오류가 아니라 '두 자리에 같은 그룹' 이다(둘 다 펼쳐진다)."""
    return ANCHOR_PATTERN.findall(str(text or ""))


def has_anchor(text: Any) -> bool:
    return bool(ANCHOR_PATTERN.search(str(text or "")))


def strip_anchors(text: Any) -> str:
    """표식만 걷어낸다. 주변에 남는 빈 자리·쉼표는 정리하지 않는다 -
    태그 단위 정리는 `expand_tags` 가 한다(거기서는 목록이라 정확히 셀 수 있다)."""
    return ANCHOR_PATTERN.sub("", str(text or ""))


def normalize_groups(groups: Any) -> dict[str, str]:
    """`{아이디: 합쳐진 태그 글}`. 아이디 규칙을 안 지키거나 빈 값은 버린다.

    값은 프론트가 이미 모드별 서식(NAI `::`/SD 괄호)으로 합쳐 보낸 것이다 -
    여기서 다시 만들지 않는다. 서식을 두 곳에서 만들면 반드시 어긋난다.
    """
    if not isinstance(groups, dict):
        return {}
    clean: dict[str, str] = {}
    for key, value in groups.items():
        anchor_id = str(key or "").strip()
        if not ANCHOR_ID_PATTERN.match(anchor_id):
            continue
        text = str(value or "").strip().strip(",").strip()
        if text:
            clean[anchor_id] = text
    return clean


def _split_expansion(text: str) -> list[str]:
    """합쳐진 글을 태그 목록으로. 쉼표로만 가른다 - 여기 들어오는 것은 이미
    `formatArtistToken` 이 만든 아티스트 토큰들이라 중첩 구문이 없다."""
    return [part.strip() for part in str(text or "").split(",") if part.strip()]


def expand_tags(tags: Iterable[str], groups: Any = None) -> list[str]:
    """태그 목록 안의 앵커 표식을 그룹의 태그로 바꾼다.

    두 가지 모양을 다 받는다:
      - 태그 하나가 통째로 표식(`<anchor:1>`)    -> 그 자리에 그룹 태그들을 펼친다
      - 태그 안에 표식이 섞여 있음(`1girl <anchor:2>`) -> 글자 자리에 끼워 넣는다

    ⚠️ 짝을 못 찾은 표식은 **지운다**. 지우고 나서 빈 껍데기가 된 태그도 버린다 -
       안 그러면 `, , ` 가 남아 프롬프트에 빈 태그가 생긴다.
    """
    resolved = normalize_groups(groups)
    out: list[str] = []
    for raw in tags or []:
        tag = str(raw or "")
        if not ANCHOR_PATTERN.search(tag):
            if tag.strip():
                out.append(tag)
            continue
        whole = ANCHOR_PATTERN.fullmatch(tag.strip())
        if whole:
            # 태그 하나가 곧 표식 - 그룹이 있으면 그 태그들로 갈아 끼우고, 없으면 사라진다.
            out.extend(_split_expansion(resolved.get(whole.group(1), "")))
            continue
        inlined = ANCHOR_PATTERN.sub(lambda m: resolved.get(m.group(1), ""), tag).strip()
        if inlined:
            out.append(inlined)
    return out


def expand_text(text: Any, groups: Any = None) -> str:
    """글 단위 버전. 표식이 사라진 자리에 쉼표가 겹치면 정리한다."""
    resolved = normalize_groups(groups)
    filled = ANCHOR_PATTERN.sub(lambda m: resolved.get(m.group(1), ""), str(text or ""))
    filled = re.sub(r",\s*(?=,)", "", filled)          # `, ,` -> `,`
    return filled.strip().strip(",").strip()
