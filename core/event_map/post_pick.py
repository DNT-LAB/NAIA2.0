# -*- coding: utf-8 -*-
"""실제 게시물 하나에서 한 갈래(의상 · 행동 · 자세 …)의 태그만 - Wire-Flow '이벤트 맵 쿼리' 의 몸통.

이벤트 맵 색인에서 조건 태그가 전부 달린 게시물 하나를 무작위로 골라, 그 게시물에 **실제로 함께 달린** 태그 중
고른 갈래만 남긴다(이어 붙인 조합이 아니다). 사용자 2026-11-01: 1차 = 개인용 무작위 의상 · "행동만 받는다던지".

갈래 = 3단 지도(`tree_3depth.json`)의 그룹(D2) 묶음. 의상만 따로 분류기(`attire.AttireClassifier`)를 쓴다 -
지도는 색을 버려서 `white shirt` 를 모르고, 의상은 앞 낱말 떼기 · 들고 다니는 것 빼기가 필요하다.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable

from core.event_map.attire import attire_classifier, drop_covered
from core.event_map.tree import TREE_PATH

# id -> (한국어 이름, 지도 그룹 D2 묶음(None = 의상 분류기), 한 벌로 치는 최소 태그 수)
CATEGORIES: dict[str, tuple[str, tuple[str, ...] | None, int]] = {
    "attire": ("의상", None, 3),
    "action": ("행동", ("tag_group:verbs_and_gerunds", "tag_group:holding_tags", "tag_group:gestures",
                        "tag_group:dances"), 1),
    "pose": ("자세", ("tag_group:posture", "on", "tag_group:hands"), 1),
    "expression": ("표정", ("tag_group:face_tags",), 1),
    "place": ("장소", ("tag_group:locations",), 1),
    "composition": ("구도 · 조명", ("tag_group:image_composition", "tag_group:focus_tags", "tag_group:lighting"), 1),
    "sex": ("성행위", ("tag_group:sex_acts", "tag_group:sexual_positions", "tag_group:bdsm_and_torture"), 1),
}
# 한 번에 집어 보는 게시물 수 - 이 안에서 처음 '충분한' 것을 쓴다. 표본은 교집합 전체에서 고르게 뽑힌다.
PICK_TRIES = 24
# 1인 게시물 분면(이벤트 맵 인원 그룹). 남녀는 조건 태그(`1girl` · `1boy`)가 가른다.
SOLO_PERSONS = ("1girl_solo", "1boy_solo")

_MEMBERS: dict[str, frozenset[str]] = {}


def _norm(tag: str) -> str:
    return " ".join(str(tag or "").replace("_", " ").lower().split())


def category_members(kind: str) -> frozenset[str]:
    """지도 그룹 묶음의 태그 이름(정규화). 의상은 쓰지 않는다(분류기)."""
    if kind not in _MEMBERS:
        groups = set(CATEGORIES[kind][1] or ())
        tree = json.loads(TREE_PATH.read_text(encoding="utf-8"))
        names = {_norm(tag) for d1 in tree.get("d1") or [] for d2 in d1.get("d2") or [] if d2.get("id") in groups
                 for d3 in d2.get("d3") or [] for tag in d3.get("tags") or []}
        _MEMBERS[kind] = frozenset(names)
    return _MEMBERS[kind]


def category_test(kind: str) -> Callable[[str], bool]:
    if kind not in CATEGORIES:
        raise ValueError("모르는 갈래: %s" % kind)
    if CATEGORIES[kind][1] is None:
        return attire_classifier().is_attire
    members = category_members(kind)
    return lambda tag: _norm(tag) in members


def pick_from_post(index: Any, *, kind: str = "attire", persons: list[str] | None, pins: list[str] | None = None,
                   exclude: list[str] | None = None, ratings: list[str] | None = None, seed: int | None = None,
                   min_tags: int | None = None, tries: int = PICK_TRIES, keep_series: bool = False,
                   block: Any = None) -> dict[str, Any]:
    """게시물 하나에서 고른 갈래의 태그. 색은 남긴다(`white shirt`) · 의상은 더 자세한 태그가 덮는 포괄 태그를 뺀다.

    persons = 인원 분면(None = 인원 무관) · pins = 조건 태그(전부 달린 게시물만) · exclude = 빼기 태그.
    조건 태그 중 그 갈래인 것(`maid`)은 결과에도 남는다 - 그 게시물에 달린 태그다.
    keep_series=False 면 작품 고유 물건(`vision (genshin impact)` - 괄호 달린 태그)을 뺀다.
    `min_tags`(기본 = 갈래마다)를 채우는 게시물이 `tries` 장 안에 없으면 가장 많은 것을 쓴다(status thin).
    맵에 없는 조건 태그가 있으면 뽑지 않는다(status unknown_tag · `unknown`).
    """
    started = time.perf_counter()
    test = category_test(kind)
    need = CATEGORIES[kind][2] if min_tags is None else min_tags
    res = index.sample(list(pins or []), exclude=list(exclude or []), persons=persons or None,
                       ratings=ratings or None, n=tries, include_color=True, seed=seed, block=block)
    best: dict[str, Any] | None = None
    for sample in res.get("samples") or []:
        tags = [t for t in sample["tags"] if test(t) and (keep_series or "(" not in t)]
        if kind == "attire":            # `white shirt` 가 `shirt` 를 덮는 것은 옷 이름뿐 - `hand on back` ≠ `on back`(리뷰)
            tags = drop_covered(tags)
        if best is None or len(tags) > len(best["tags"]):
            best = {"tags": tags, "partition": sample.get("partition")}
        if len(tags) >= need:
            best = {"tags": tags, "partition": sample.get("partition")}
            break
    out = {"kind": kind, "observed_posts": int(res.get("observed_posts") or 0), "tags": [], "partition": None,
           "status": "unknown_tag" if res.get("status") == "unknown_tag" else "no_match",
           "unknown": [*(res.get("unknown_pins") or []), *(res.get("unknown_exclude") or [])]}
    if best and best["tags"]:
        out.update(best, status="matched" if len(best["tags"]) >= need else "thin")
    out["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return out
