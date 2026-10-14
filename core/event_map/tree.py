# -*- coding: utf-8 -*-
"""이벤트 맵 3단 지도(갈래 › 그룹 › 절 › 태그) - Danbooru 위키 tag_groups 를 다듬은 것.

자료는 `core/event_map/tree_3depth.json` 하나다(`tools/export_event_map_tree.py` 가 굽는다 - 원재료와
정리 이력은 `docs/EVENT_MAP_DANBOORU_TAG_GROUPS_2026_10_14.md`). 이 모듈은 그 파일을 읽어

  * 화면이 그릴 **골격**(id · 한국어 이름 · 태그 수)을 주고,
  * 맵 색인에 **묶어**(태그 이름 -> 색인 id) 절 · 그룹 · 갈래마다 태그 마스크를 만든다.

색인은 없을 수 있다(선택 다운로드) - 골격은 색인 없이도 준다. 이 모듈은 아무것도 쓰지 않는다.

id 규칙
  갈래(d1)  `Body` 처럼 위키 갈래 이름(영어) - 화면은 `ko` 를 보인다.
  그룹(d2)  `tag_group:posture` · `naia:everyday_objects` - 지도 전체에서 하나뿐이다.
  절(d3)    그룹 안에서만 하나뿐이다(`Arms` 는 여러 그룹에 있다). 그래서 절은 늘 (그룹, 절) 쌍으로 가리킨다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np

SCHEMA = "naia-event-map-tree-v1"
TREE_PATH = Path(__file__).with_name("tree_3depth.json")


class TreeError(ValueError):
    """지도 파일이 계약과 다르다."""


class EventMapTree:
    """지도 파일 하나. 색인과 무관한 골격만 쥔다."""

    def __init__(self, data: dict[str, Any]) -> None:
        if not isinstance(data, dict) or data.get("schema") != SCHEMA:
            raise TreeError("지도 스키마가 다르다: %r" % (data.get("schema") if isinstance(data, dict) else data))
        self.version = str(data.get("version") or "")
        self.d1: list[dict] = []
        self.d2: dict[str, dict] = {}
        # 절 목록. 순번이 곧 내부 번호다. (d1 id, d2 id, d3 id, 태그 이름 목록)
        self.slots: list[tuple[str, str, str, list[str]]] = []
        self.slot_of: dict[tuple[str, str], int] = {}
        self.labels: dict[str, str] = {}
        for d1 in data.get("d1") or []:
            o1 = {"id": d1["id"], "ko": d1["ko"], "d2": []}
            self.labels["d1:" + d1["id"]] = d1["ko"]
            for d2 in d1.get("d2") or []:
                if d2["id"] in self.d2:
                    raise TreeError("그룹 id 가 겹친다: %s" % d2["id"])
                o2 = {"id": d2["id"], "ko": d2["ko"], "d1": d1["id"], "d3": []}
                for d3 in d2.get("d3") or []:
                    key = (d2["id"], d3["id"])
                    if key in self.slot_of:
                        raise TreeError("한 그룹 안에서 절 id 가 겹친다: %s / %s" % key)
                    tags = [str(t) for t in d3.get("tags") or []]
                    if not tags:
                        raise TreeError("빈 절: %s / %s" % key)
                    self.slot_of[key] = len(self.slots)
                    self.slots.append((d1["id"], d2["id"], d3["id"], tags))
                    o2["d3"].append({"id": d3["id"], "ko": d3["ko"], "slot": self.slot_of[key]})
                o1["d2"].append(o2)
                self.d2[d2["id"]] = o2
            self.d1.append(o1)
        if not self.slots:
            raise TreeError("지도가 비었다")
        self.d1_ids = [d["id"] for d in self.d1]

    @classmethod
    def load(cls, path: Path | None = None) -> "EventMapTree":
        p = Path(path) if path else TREE_PATH
        return cls(json.loads(p.read_text(encoding="utf-8")))

    # -- 이름 ----------------------------------------------------------------
    def d1_ko(self, d1: str) -> str:
        return self.labels.get("d1:" + d1, d1)

    def d3_ko(self, d2: str, d3: str) -> str:
        for row in self.d2[d2]["d3"]:
            if row["id"] == d3:
                return row["ko"]
        return d3

    def path_ko(self, slot: int) -> list[str]:
        d1, d2, d3, _ = self.slots[slot]
        return [self.d1_ko(d1), self.d2[d2]["ko"], self.d3_ko(d2, d3)]

    # -- 고르기 --------------------------------------------------------------
    def select(self, d1: str = "", d2: str = "", d3: str = "") -> list[int]:
        """(갈래 | 그룹 | 그룹+절) -> 절 번호 목록. 모르는 id 는 KeyError(서비스가 오류 code 로 바꾼다)."""
        d1, d2, d3 = (str(x or "").strip() for x in (d1, d2, d3))
        if d3:
            if not d2:
                raise KeyError("절은 그룹과 함께 지정해야 한다")
            return [self.slot_of[(d2, d3)]]
        if d2:
            if d2 not in self.d2:
                raise KeyError(d2)
            return [row["slot"] for row in self.d2[d2]["d3"]]
        if d1:
            if d1 not in self.d1_ids:
                raise KeyError(d1)
            return [i for i, s in enumerate(self.slots) if s[0] == d1]
        return list(range(len(self.slots)))

    def bind(self, resolve, n_tags: int) -> "BoundTree":
        return BoundTree(self, resolve, n_tags)


class BoundTree:
    """색인에 묶인 지도. 절마다 색인 태그 id 배열을 쥔다(마스크는 필요할 때 만든다)."""

    def __init__(self, tree: EventMapTree, resolve, n_tags: int) -> None:
        self.tree = tree
        self.n_tags = int(n_tags)
        self.slot_tids: list[np.ndarray] = []
        self.unresolved = 0
        home: dict[int, list[int]] = {}
        for i, (_d1, _d2, _d3, tags) in enumerate(tree.slots):
            tids = []
            for name in tags:
                tid = resolve(name)
                if tid is None:
                    self.unresolved += 1
                    continue
                tids.append(int(tid))
                home.setdefault(int(tid), []).append(i)
            self.slot_tids.append(np.unique(np.array(tids, dtype=np.int64)))
        self.home = home   # 색인 id -> 그 태그가 사는 절 번호들(지도 순서)
        self.universe = np.zeros(self.n_tags, dtype=bool)
        if home:
            self.universe[np.fromiter(home.keys(), dtype=np.int64)] = True
        self.d1_masks = {d1: self.mask(tree.select(d1=d1)) for d1 in tree.d1_ids}
        # 그룹(d2)마다 태그 id(절끼리 겹치는 태그는 한 번) - 핀 결과의 그룹별 후보 수를 셀 때 쓴다.
        self.group_tids = {d2: np.unique(np.concatenate([self.slot_tids[r["slot"]] for r in g["d3"]]))
                           for d2, g in tree.d2.items()}

    def mask(self, slots: Iterable[int]) -> np.ndarray:
        out = np.zeros(self.n_tags, dtype=bool)
        for s in slots:
            tids = self.slot_tids[s]
            if tids.size:
                out[tids] = True
        return out

    def slot_size(self, slot: int) -> int:
        return int(self.slot_tids[slot].size)

    def paths(self, tid: int, limit: int = 3) -> list[list[str]]:
        return [self.tree.path_ko(s) for s in self.home.get(int(tid), [])[:limit]]

    def first_path(self, tid: int) -> dict[str, str] | None:
        slots = self.home.get(int(tid))
        if not slots:
            return None
        d1, d2, d3, _ = self.tree.slots[slots[0]]
        return {"d1": d1, "d2": d2, "d3": d3, "ko": " › ".join(self.tree.path_ko(slots[0]))}
