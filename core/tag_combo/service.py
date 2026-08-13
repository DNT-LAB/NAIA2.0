# -*- coding: utf-8 -*-
"""조합 추천 서비스 - 모델 LRU 와 질의 파사드.

## 메모리

인원 그룹 13개를 전부 상주시키면 실측 1.5GB 다(역인덱스 포함). 사용자가 인원
설정을 바꿀 때만 모델이 바뀌므로 **바이트 예산 LRU** 로 두세 개만 들고 있는다.

⚠️ 엔트리 수가 아니라 **바이트**로 센다. 개수로 세면 161MB 짜리 두 개가 겹쳐
올라간다. 그리고 새 모델의 역인덱스를 만들기 **전에** 옛 모델을 버린다.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterable

from .model import ComboModel
from .person import PERSON_GROUPS, person_group_of
from .query import ComboQuery, Policy

DEFAULT_BUDGET = 400 * 1024 * 1024      # 상주 모델 합계 상한


class ComboService:
    def __init__(self, data_dir: Path, *, budget: int = DEFAULT_BUDGET,
                 policy: Policy | None = None):
        self.dir = Path(data_dir)
        self.budget = int(budget)
        self.policy = policy or Policy()
        self._lru: "OrderedDict[str, tuple[ComboModel, ComboQuery]]" = OrderedDict()
        self._lock = threading.Lock()

    # ---- 모델 --------------------------------------------------------
    def available(self) -> list[str]:
        return [g for g in PERSON_GROUPS if (self.dir / f"{g}.ncsr").exists()]

    def _resident_bytes(self) -> int:
        return sum(m.nbytes for m, _ in self._lru.values())

    def _get(self, group: str) -> tuple[ComboModel, ComboQuery] | None:
        with self._lock:
            hit = self._lru.get(group)
            if hit is not None:
                self._lru.move_to_end(group)
                return hit
            path = self.dir / f"{group}.ncsr"
            if not path.exists():
                return None
            # **적재 전에** 예산을 비운다. 역인덱스를 만든 뒤에 버리면 두 모델이
            # 잠깐 겹쳐 올라간다.
            while self._lru and self._resident_bytes() > self.budget * 0.6:
                self._lru.popitem(last=False)
            model = ComboModel(path)
            model.ensure_inverted()
            entry = (model, ComboQuery(model, self.policy))
            self._lru[group] = entry
            while len(self._lru) > 1 and self._resident_bytes() > self.budget:
                self._lru.popitem(last=False)
            return entry

    # ---- 질의 --------------------------------------------------------
    def recommend(self, tags: Iterable[str], *, group: str = "") -> dict[str, Any]:
        want = [str(t).strip() for t in tags if str(t).strip()]
        grp = group or person_group_of(set(want))
        if grp not in PERSON_GROUPS:
            return {"error": f"unknown person group: {grp}", "group": grp,
                    "combos": []}
        entry = self._get(grp)
        if entry is None:
            return {"error": "model not built", "group": grp, "combos": [],
                    "available": self.available()}
        model, q = entry
        # 인원 태그는 그룹을 정의하므로 그룹 안에서 확률이 1.0 이다 - 조건부 정보가
        # 없다. 질의에서 빼야 나머지 태그로 좁혀진다.
        person_tags = {"1girl", "1boy", "solo", "2girls", "2boys",
                       "multiple girls", "multiple boys"}
        probe = [t for t in want if t not in person_tags] or want
        r = q.recommend(probe)
        return {
            "group": grp,
            "matched": r.matched,
            "bundleSize": r.bundle_size,
            "usedPrompt": r.used_prompt,
            "backedOff": r.backed_off,
            "weak": r.weak,
            "combos": [{"tags": c.tags, "support": c.support,
                        "bits": round(c.surprisal, 1)} for c in r.combos],
            "modelPosts": model.header.posts,
        }
