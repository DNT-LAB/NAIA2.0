# -*- coding: utf-8 -*-
"""KR_tags 의 대분류(자유 텍스트)를 이벤트 맵의 12갈래로 접는다.

표는 `kr_category_fold.json` 이 SSOT 다(사용자 확정 2026-09-12). 여기서는 읽고 찾기만 한다.

왜 접나: `data/KR_tags.parquet` 의 `category` 는 `대분류 > 소분류` 꼴의 자유 텍스트라 대분류가
**296개**다(2026-09-12 실측 - 그중 100개는 태그 하나짜리, 작품 이름을 분류로 쓴 것이 대부분).
같은 뜻이 패션·의상·복장·복식·의류로 갈라져 있어 그대로는 첫 화면이 될 수 없다.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

FOLD_PATH = Path(__file__).with_name("kr_category_fold.json")
UNSORTED = "unsorted"


@lru_cache(maxsize=1)
def _table() -> dict:
    data = json.loads(FOLD_PATH.read_text(encoding="utf-8"))
    lookup: dict[str, str] = {}
    for group, labels in data["map"].items():
        for label in labels:
            key = _norm(label)
            if key in lookup and lookup[key] != group:
                raise ValueError("대분류 %r 이 두 갈래에 있다: %s / %s" % (label, lookup[key], group))
            lookup[key] = group
    return {"groups": data["groups"], "lookup": lookup}


def _norm(label: str) -> str:
    return " ".join(str(label or "").strip().split()).casefold()


def groups() -> list[dict]:
    """갈래 목록(순서대로). 각 항목: id · label · order · depth1(첫 화면 축인가)."""
    return [dict(g) for g in _table()["groups"]]


def split_category(category: str) -> tuple[str, str]:
    """`대분류 > 소분류` -> (대분류, 소분류). 소분류가 없으면 빈 문자열."""
    text = str(category or "").strip()
    if ">" in text:
        top, sub = text.split(">", 1)
        return top.strip(), sub.strip()
    return text, ""


def fold_top(top: str) -> str:
    """대분류 원문 -> 갈래 id. 표에 없으면 `unsorted` (조용히 다른 곳에 넣지 않는다)."""
    return _table()["lookup"].get(_norm(top), UNSORTED)


def fold_category(category: str) -> tuple[str, str]:
    """`대분류 > 소분류` 원문 -> (갈래 id, 소분류 원문)."""
    top, sub = split_category(category)
    return fold_top(top), sub
