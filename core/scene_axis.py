# -*- coding: utf-8 -*-
"""Scene axis classifier — 입력 태그를 curated 축(setting/object/action/expression/
clothing/body/color)으로 **결정론적** 분류한다. scene_boost가 evidence bucket과
Priority anchors를 만들 근거로 쓴다. 코드는 라벨만 붙이고 **prose를 생성하지 않는다**
→ 2-stage(scene_brief)가 환각을 증폭하던 통로를 원천 차단(Claude+Codex 협의 2026-06-13).

설계: **direct curated 리스트가 primary SSOT**. 병합 `group` 필드는 load 순서에 오염돼
(parquet 우선) 80샘플 中 축명 적중 2/80뿐 → group_lookup은 미분류 보조로만(옵션).
stdlib만 의존(순수)·data_root별 1회 캐시.

축 소스(data/):
- setting    ← taglist/location_tags.json
- object     ← taglist/object_tags.json
- action     ← taglist/pose_action_tags.json
- expression ← taglist/expression_tags.json
- clothing   ← taglist/clothing_event.json + clothing_regions.json + clothes_list.txt(괄호항목 제거)
- body       ← characteristic_list.txt
- color      ← color.txt
clothes_list.txt는 franchise/cosplay(괄호형: "2b (nier:automata) (cosplay)")로 오염돼
괄호 포함 항목을 버린다(Codex 지적). clothing_event/regions가 curated 본체.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "AXES", "SETTING", "OBJECT", "ACTION", "EXPRESSION", "CLOTHING", "BODY", "COLOR",
    "AXIS_PRIORITY", "build_axis_classifier", "classify_axes_with", "axis_set_sizes",
]

SETTING = "setting"
OBJECT = "object"
ACTION = "action"
EXPRESSION = "expression"
CLOTHING = "clothing"
BODY = "body"
COLOR = "color"
AXES = (SETTING, OBJECT, ACTION, EXPRESSION, CLOTHING, BODY, COLOR)

# 한 태그가 여러 축이면 primary 하나 고를 때 우선순위(버킷 표시용). 0.5%만 multi-axis.
AXIS_PRIORITY = (ACTION, OBJECT, SETTING, CLOTHING, BODY, EXPRESSION, COLOR)


def _norm(tag: Any) -> str:
    s = str(tag or "").replace("_", " ").replace("\\(", "(").replace("\\)", ")")
    return " ".join(s.strip().lower().split())


def _collect_strings(data: Any) -> list[str]:
    """JSON 구조에서 태그 문자열만 재귀 수집(version/description 메타 키 제외)."""
    out: list[str] = []
    if isinstance(data, list):
        for x in data:
            if isinstance(x, str):
                out.append(x)
            elif isinstance(x, (list, dict)):
                out.extend(_collect_strings(x))
    elif isinstance(data, dict):
        for key, value in data.items():
            if key in ("version", "description"):
                continue
            out.extend(_collect_strings(value))
    return out


def _load_json_tags(path: Path) -> list[str]:
    try:
        return _collect_strings(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return []


def _load_txt_tags(path: Path) -> list[str]:
    try:
        return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except Exception:
        return []


def _resolve_data_dir(data_root: Path) -> Path:
    """repo 루트('<repo>') 또는 데이터 디렉('<repo>/data') 어느 쪽을 받아도 data 디렉을 반환."""
    p = Path(data_root)
    if (p / "taglist").is_dir():
        return p
    if (p / "data" / "taglist").is_dir():
        return p / "data"
    return p


def _build_sets(data_root: Path) -> dict[str, frozenset[str]]:
    data_root = _resolve_data_dir(data_root)
    tl = data_root / "taglist"
    raw: dict[str, list[str]] = {
        SETTING: _load_json_tags(tl / "location_tags.json"),
        OBJECT: _load_json_tags(tl / "object_tags.json"),
        ACTION: _load_json_tags(tl / "pose_action_tags.json"),
        EXPRESSION: _load_json_tags(tl / "expression_tags.json"),
        CLOTHING: (
            _load_json_tags(tl / "clothing_event.json")
            + _load_json_tags(tl / "clothing_regions.json")
            + [t for t in _load_txt_tags(data_root / "clothes_list.txt") if "(" not in t]
        ),
        BODY: _load_txt_tags(data_root / "characteristic_list.txt"),
        COLOR: _load_txt_tags(data_root / "color.txt"),
    }
    return {axis: frozenset(n for t in tags if (n := _norm(t))) for axis, tags in raw.items()}


_CACHE: dict[str, dict[str, frozenset[str]]] = {}


def _sets_for(data_root: str | Path) -> dict[str, frozenset[str]]:
    key = str(Path(data_root).resolve())
    sets = _CACHE.get(key)
    if sets is None:
        sets = _build_sets(Path(data_root))
        _CACHE[key] = sets
    return sets


# KR 병합 group prefix → 축(미분류 보조). "캐릭터 > 직업/유형"은 인물 역할(주체)이라
# 버킷이 아니라 priority-anchor가 처리 → 여기선 None을 돌려 미분류로 남긴다.
_GROUP_PREFIX_AXIS: tuple[tuple[str, str], ...] = (
    ("배경", SETTING), ("사물", OBJECT), ("물체", OBJECT), ("자세", ACTION),
    ("행동", ACTION), ("행위", ACTION), ("표정", EXPRESSION), ("의상", CLOTHING),
    ("패션", CLOTHING), ("신체", BODY), ("특징", BODY), ("색", COLOR),
)


def _axis_from_group(group: Any) -> str | None:
    g = str(group or "").strip().lower()
    if not g or "캐릭터" in g:
        return None
    for marker, axis in _GROUP_PREFIX_AXIS:
        if marker in g:
            return axis
    return None


def classify_axes_with(
    sets: dict[str, frozenset[str]],
    tag: Any,
    *,
    group_lookup: Callable[[str], str] | None = None,
) -> frozenset[str]:
    """태그가 속한 축 집합. direct 리스트 우선, 미분류 시 group_lookup prefix 보조."""
    n = _norm(tag)
    if not n:
        return frozenset()
    axes = {axis for axis, s in sets.items() if n in s}
    if not axes and group_lookup is not None:
        try:
            axis = _axis_from_group(group_lookup(n))
        except Exception:
            axis = None
        if axis:
            axes = {axis}
    return frozenset(axes)


def build_axis_classifier(
    data_root: str | Path,
    *,
    group_lookup: Callable[[str], str] | None = None,
) -> Callable[[str], frozenset[str]]:
    """data_root의 curated 리스트로 classify(tag)->frozenset[axes] 생성(캐시)."""
    sets = _sets_for(data_root)

    def classify(tag: str) -> frozenset[str]:
        return classify_axes_with(sets, tag, group_lookup=group_lookup)

    return classify


def axis_set_sizes(data_root: str | Path) -> dict[str, int]:
    """진단용 — 각 축 세트 크기."""
    return {axis: len(s) for axis, s in _sets_for(data_root).items()}
