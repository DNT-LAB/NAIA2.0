# -*- coding: utf-8 -*-
"""아티스트 매칭 검색 — depth 를 쌓아 작가를 좁힌다.

사용자 사양(2026-09-19): **depth 당 조건 하나**, 각 depth 는 AND, 색인되지 않은 낱말은
검색할 수 없다. depth 는 두 갈래다.

    tag     한 태그를 그린 **횟수**로 거른다      count(작가, 태그) >= min_count
    rating  한 등급 묶음의 **수 또는 비중**으로 거른다

        ┌ genshin impact ─┐ ┌ rating e ─┐ ┌ rating q+e ─┐
        │ count>=10       │ │ count>=10 │ │ 비중>=45%    │
        │ post >=200      │ │ post >=100│ │ post >=100   │
        └─────────────────┘ └───────────┘ └─────────────┘
              39,427  ->        1,159  ->        ...

⚠️ **`min_posts` 는 작가의 총 게시물 수다**(사용자 확정 A안). 태그의 게시물 수도, 직전
   depth 의 게시물 수도 아니다. 그래서 두 번째 depth 부터는 값이 더 작으면 사실상 아무것도
   안 거른다 - 그래도 사용자가 볼 수 있게 `passed` 를 depth 마다 돌려준다.

⚠️ **등급은 전역 필터가 아니라 제 depth 다**(사용자 지정). 그래서 태그 depth 의 분자는
   **전 등급**으로 센다. "genshin 그림 중 e 인 것" 같은 교차 조건은 이 모형에 없다.

⚠️ `share == 0` 은 "안 그린다" 가 아니라 **"모른다"** 다(팩 머리말). 그래서 이 검색에는
   부정 depth(이 태그를 **안** 그리는 작가)가 없다. 넣지 마라.
"""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np

from core.artist_affinity import ALL_RATINGS, RATING_CODE, wilson_lower_bound

MAX_DEPTH = 6
ORDERS = ("wilson", "count", "posts")


class ArtistSearchError(ValueError):
    """사용자에게 그대로 보여 줄 수 있는 요청 오류(HTTP 400)."""


def _int(value: Any, name: str, *, default: int = 0, low: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ArtistSearchError(f"{name} 는 정수여야 합니다: {value!r}") from None
    return max(number, low)


def _ratings(value: Any) -> frozenset:
    """`q+e` · `qe` · `["q","e"]` 를 다 받는다.

    ⚠️ 문자열을 따로 쪼개는 가지는 **필요 없다** - 파이썬이 문자열을 글자 단위로
       순회하고 `+` 는 등급 글자가 아니라 아래 필터가 버린다. 한때 그 가지가
       있었는데 돌연변이 시험이 "지워도 아무도 안 운다" 고 알려 줬다.
    """
    wanted = frozenset(str(r).strip().lower() for r in (value or []))
    wanted = frozenset(r for r in wanted if r in RATING_CODE)
    if not wanted:
        raise ArtistSearchError("등급을 하나 이상 골라야 합니다 (g/s/q/e)")
    return wanted


def normalize_stack(stack: Any) -> list[dict[str, Any]]:
    """요청의 depth 목록을 다듬는다. 화면 값이 그대로 들어오므로 여기서 다 막는다."""
    if not isinstance(stack, list) or not stack:
        raise ArtistSearchError("검색 조건이 비어 있습니다")
    if len(stack) > MAX_DEPTH:
        raise ArtistSearchError(f"depth 는 {MAX_DEPTH} 단계까지입니다")
    out: list[dict[str, Any]] = []
    for i, raw in enumerate(stack):
        if not isinstance(raw, dict):
            raise ArtistSearchError(f"{i + 1}단계가 올바르지 않습니다")
        kind = str(raw.get("kind") or "tag").strip().lower()
        common = {"kind": kind, "min_posts": _int(raw.get("min_posts"), "min_posts")}
        if kind == "tag":
            tag = str(raw.get("tag") or "").strip()
            if not tag:
                raise ArtistSearchError(f"{i + 1}단계: 태그가 비어 있습니다")
            axis = str(raw.get("axis") or "").strip().lower() or None
            # ⚠️ 축을 안 주면 팩이 추정한다(posting 이 큰 쪽). 자동완성은 분류를 아니
            #    화면이 축을 실어 보내는 편이 낫다.
            out.append({**common, "tag": tag, "axis": axis,
                        "min_count": _int(raw.get("min_count"), "min_count")})
        elif kind == "rating":
            mode = str(raw.get("mode") or "count").strip().lower()
            if mode not in ("count", "ratio"):
                raise ArtistSearchError(f"{i + 1}단계: mode 는 count 또는 ratio 입니다")
            entry = {**common, "ratings": sorted(_ratings(raw.get("ratings"))), "mode": mode}
            if mode == "count":
                entry["min_count"] = _int(raw.get("min_count"), "min_count")
            else:
                try:
                    ratio = float(raw.get("min_ratio") or 0)
                except (TypeError, ValueError):
                    raise ArtistSearchError("min_ratio 는 0~1 의 수여야 합니다") from None
                if not 0 <= ratio <= 1:
                    raise ArtistSearchError("min_ratio 는 0~1 사이여야 합니다")
                entry["min_ratio"] = ratio
            out.append(entry)
        else:
            raise ArtistSearchError(f"{i + 1}단계: 모르는 kind 입니다: {kind!r}")
    return out


def search(pack, stack: Any, *, order: str = "wilson",
           limit: int = 300, offset: int = 0) -> dict[str, Any]:
    """depth 를 차례로 적용해 살아남은 작가를 돌려준다.

    돌려주는 `rows[].hits` 는 depth 순서와 같은 길이다 - 화면이 "1단계 305장 /
    2단계 41장" 을 그대로 읽는다.
    """
    steps = normalize_stack(stack)
    if not pack.available():
        state = pack.state()
        return {"state": state.get("state", "missing"), "reason": state.get("reason"),
                "steps": [], "rows": [], "total": 0}

    names = pack.artist_names
    total_posts = pack.denominator(ALL_RATINGS)
    # 0 번은 '작가 없음' 자리다 - 처음부터 죽여 둔다.
    alive = np.zeros(len(names), dtype=bool)
    alive[1:] = True

    hits: list[np.ndarray] = []
    report: list[dict[str, Any]] = []

    for step in steps:
        if step["kind"] == "tag":
            counted = pack.tally(step["tag"], axis=step["axis"])
            if counted["state"] != "ready":
                return {"state": counted["state"], "tag": step["tag"],
                        "axes": counted.get("axes", []), "steps": report,
                        "rows": [], "total": 0}
            hit = counted["numerator"]
            keep = (hit >= max(step["min_count"], 1)) & (total_posts >= step["min_posts"])
            info = {"kind": "tag", "tag": counted["tag"], "axis": counted["axis"],
                    "posts": counted["posts"], "min_count": step["min_count"],
                    "min_posts": step["min_posts"]}
        else:
            wanted = frozenset(step["ratings"])
            hit = pack.denominator(wanted)
            if step["mode"] == "count":
                keep = (hit >= max(step["min_count"], 1)) & (total_posts >= step["min_posts"])
                info = {"kind": "rating", "ratings": step["ratings"], "mode": "count",
                        "min_count": step["min_count"], "min_posts": step["min_posts"]}
            else:
                # ⚠️ 비중의 분모는 **작가의 총 게시물**이다. 0 으로 나누지 않게 눌러 둔다.
                ratio = hit / np.maximum(total_posts, 1)
                keep = (ratio >= step["min_ratio"]) & (total_posts >= step["min_posts"])
                info = {"kind": "rating", "ratings": step["ratings"], "mode": "ratio",
                        "min_ratio": step["min_ratio"], "min_posts": step["min_posts"]}
        alive &= keep
        hits.append(hit)
        info["passed"] = int(alive.sum())
        report.append(info)
        if not info["passed"]:
            break

    survivors = np.flatnonzero(alive)
    if survivors.size == 0:
        return {"state": "ready", "steps": report, "rows": [], "total": 0,
                "order": order, "limit": limit, "offset": offset}

    last = hits[len(report) - 1][survivors]
    total = total_posts[survivors]
    wilson = wilson_lower_bound(last, total)
    if order == "posts":
        key = total.astype(np.float64)
    elif order == "count":
        key = last.astype(np.float64)
    else:
        order = "wilson"
        key = wilson
    rank = np.argsort(-key, kind="stable")

    start = max(int(offset), 0)
    window = rank[start:start + max(int(limit), 1)]
    rows = []
    for i in window:
        idx = int(survivors[i])
        rows.append({
            "artist": names[idx],
            "hits": [int(h[idx]) for h in hits[:len(report)]],
            "hit": int(last[i]),
            "total": int(total[i]),
            "share": round(float(last[i] / max(int(total[i]), 1)), 4),
            "wilson": round(float(wilson[i]), 4),
        })
    return {"state": "ready", "steps": report, "rows": rows,
            "total": int(survivors.size), "order": order,
            "limit": int(limit), "offset": start}


def suggest(pack, prefix: str, *, axis: str | None = None, limit: int = 20) -> dict[str, Any]:
    """검색칸 자동완성. **색인에 있는 낱말만** 고를 수 있다(사용자 지정)."""
    if not pack.available():
        return {"state": "missing", "rows": []}
    return {"state": "ready", "rows": pack.suggest(prefix, axis=axis, limit=limit)}
