"""의상 태그 하나를 고르면 '다른 의상' 을 찾아 주는 조회기.

데이터 두 개를 함께 읽는다:
  data/outfit_presets.json    세트(태그 · 칸 · 순위)
  data/outfit_tag_index.json  태그 관계(tools/build_outfit_tag_index.py 가 굽는다)

관계 세 갈래(화면은 이 순서로 보여 주면 된다):
  swap      그 자리만 바꾼 의상 - 고른 의상(context)의 나머지는 두고 같은 칸의 태그 하나만 다른 세트
  contains  이 태그를 쓴 다른 의상 - context 와 많이 겹치는 것부터
  kind      같은 종류 다른 모양 - pleated skirt 를 고르면 plaid skirt · miniskirt … 를 쓴 세트
그리고 다음에 누를 태그 칩(hops): broader · narrower · siblings · swaps.

순수 파이썬 · 네트워크 없음. 처음 부를 때 한 번 읽고(수 ms), 세트 역색인을 메모리에 둔다.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path

from core.preset_thumb_key import preset_thumb_key


ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "data" / "outfit_presets.json"
INDEX_PATH = ROOT / "data" / "outfit_tag_index.json"
POOLS = ("female", "male")
GROUP_LABELS = {
    "swap": "이 자리만 바꾼 의상",
    "contains": "이 태그를 쓴 다른 의상",
    "kind": "같은 종류 다른 모양",
}


class OutfitTagSemantics:
    def __init__(self, pack_path: Path = PACK_PATH, index_path: Path = INDEX_PATH, *,
                 pack_source: Callable[[], tuple[dict, str]] | None = None):
        self._pack_source = pack_source
        self.pack_path = Path(pack_path)
        self.index_path = Path(index_path)
        self._lock = threading.Lock()
        self._loaded = False

    # ── 읽기 ─────────────────────────────────────────────────────────
    def _load(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            if self._pack_source is None:
                raw = self.pack_path.read_bytes()
                pack, digest = json.loads(raw), hashlib.sha256(raw).hexdigest()
            else:
                pack, digest = self._pack_source()
            index = json.loads(self.index_path.read_text(encoding="utf-8"))
            built_for = index.get("build", {}).get("inputs", {}).get("outfit_presets", {}).get("sha256")
            self.stale = built_for != digest
            self.slot = pack["tag_slot"]
            self.tags = index["tags"]
            self.accessory_slots = set(index.get("rules", {}).get("accessory_slots", ()))
            self.adornment_groups = set(index.get("rules", {}).get("adornment_groups", ()))
            self.sets = {}
            self.by_tag = {pool: defaultdict(list) for pool in POOLS}
            for row in pack["sets"]:
                summary = {
                    "id": row["id"],
                    "pool": row["pool"],
                    "seed": row["seed"],
                    "tags": list(row["tags"]),
                    "rank": min(row["rank"].values()),
                    "score": max(row["score"].values()),
                    "key": preset_thumb_key("outfit", "1girl", row["tags"]),
                }
                self.sets[row["id"]] = summary
                for tag in row["tags"]:
                    self.by_tag[row["pool"]][tag].append(summary)
            for pool in POOLS:
                for rows in self.by_tag[pool].values():
                    rows.sort(key=self._order)
            self._loaded = True

    @staticmethod
    def _order(row: dict) -> tuple:
        return (row["rank"], -row["score"], row["id"])

    @classmethod
    def _near(cls, row: dict, rest: set[str]) -> tuple:
        """보고 있는 의상(rest)에 가까운 것부터: 겹침 많이 → 덧붙은 것 적게 → 팩 순위."""
        tags = set(row["tags"])
        return (-len(rest & tags), len(tags - rest)) + cls._order(row)

    # ── 조회 ─────────────────────────────────────────────────────────
    def tag_info(self, tag: str) -> dict | None:
        self._load()
        entry = self.tags.get(tag)
        return dict(entry, tag=tag) if entry else None

    def set_info(self, set_id: str) -> dict | None:
        self._load()
        return self.sets.get(set_id)

    def related(self, tag: str, *, pool: str = "female", context: Iterable[str] | None = None,
                limit: int = 24, hop_limit: int = 12) -> dict | None:
        """tag 와 이어진 의상들. context = 지금 보고 있는 의상의 태그(그 의상의 다른 태그는 두고 tag 만 바꾼 것을 찾는다)."""
        self._load()
        entry = self.tags.get(tag)
        if entry is None:
            return None
        if pool not in POOLS:
            raise ValueError(f"pool must be one of {POOLS}")
        context_set = set(context or ()) | {tag}
        rest = context_set - {tag}
        rows = self.by_tag[pool]
        seen = {preset_thumb_key("outfit", "1girl", context_set)} if context else set()

        def take(candidates: Iterable[dict], out: list) -> None:
            for row in candidates:
                if len(out) >= limit:
                    return
                if row["key"] in seen:
                    continue
                seen.add(row["key"])
                out.append(row)

        swap_tags = [other for other, _ in entry["swaps"].get(pool, [])]
        groups = []

        # 1) 그 자리만 바꾼 의상
        swap = []
        if rest:
            variants = []
            for other in self._same_slot_candidates(tag, swap_tags):
                for row in rows.get(other, ()):
                    tags = set(row["tags"])
                    if tag in tags:
                        continue
                    kept = len(rest & tags)
                    extra = len(tags - rest - {other})
                    if kept and len(rest - tags) <= 1 and extra <= 1:
                        variants.append(((-kept, extra, swap_tags.index(other) if other in swap_tags else 99)
                                         + self._order(row), row, other))
            variants.sort(key=lambda item: item[0])
            take((row for _, row, _ in variants), swap)
        take(self._round_robin(rows, swap_tags, rest), swap)
        groups.append(("swap", swap))

        # 2) 이 태그를 쓴 다른 의상
        contains = []
        take(sorted(rows.get(tag, ()), key=lambda row: self._near(row, rest)), contains)
        groups.append(("contains", contains))

        # 3) 같은 종류 다른 모양
        kind = []
        take(self._round_robin(rows, entry["narrower"] + entry["siblings"], rest), kind)
        groups.append(("kind", kind))

        def hops(names: list[str]) -> list[str]:
            return [name for name in names if rows.get(name)][:hop_limit]

        return {
            "tag": tag,
            "pool": pool,
            "slot": entry["slot"],
            "kind": entry["kind"],
            "count": entry["count"].get(pool, 0),
            "stale": self.stale,
            "hops": {
                "broader": hops(entry["broader"]),
                "narrower": hops(entry["narrower"]),
                "siblings": hops(entry["siblings"]),
                "swaps": hops(swap_tags),
            },
            "groups": [{"relation": name, "label": GROUP_LABELS[name], "sets": sets}
                       for name, sets in groups],
        }

    # ── 도우미 ───────────────────────────────────────────────────────
    def _same_slot_candidates(self, tag: str, swap_tags: list[str]) -> list[str]:
        """대체 후보 = 같은 칸의 태그. 대체 점수가 있는 것부터, 나머지는 이름 순(결정적).

        장신구 칸(HEAD · NECK · ARMS)은 물건 갈래가 겹치는 것만 - 모자를 안경으로 바꾼 것은 '바꿔 입기' 가 아니다.
        """
        slot = self.slot.get(tag)
        groups = set(self.tags[tag].get("group", ()))

        def fits(other: str) -> bool:  # 빌더의 swappable 과 같은 규칙
            if self.slot.get(other) != slot or other == tag:
                return False
            theirs = set(self.tags.get(other, {}).get("group", ()))
            if slot in self.accessory_slots or (groups | theirs) & self.adornment_groups:
                return bool(groups & theirs)
            return True

        others = sorted(t for t in self.slot if t not in swap_tags and fits(t))
        return [t for t in swap_tags if fits(t)] + others

    def _round_robin(self, rows: dict, names: list[str], rest: set[str]) -> Iterable[dict]:
        """태그 여러 개의 세트를 한 줄씩 번갈아 - 첫 태그가 자리를 다 차지하지 않게. 각 태그 안에서는 context 에 가까운 것부터."""
        queues = []
        for name in names:
            found = rows.get(name)
            if found:
                queues.append(sorted(found, key=lambda row: self._near(row, rest)))
        depth = 0
        while queues:
            alive = []
            for queue in queues:
                if depth < len(queue):
                    yield queue[depth]
                    alive.append(queue)
            queues = alive
            depth += 1


_DEFAULT: OutfitTagSemantics | None = None


def default_semantics() -> OutfitTagSemantics:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = OutfitTagSemantics()
    return _DEFAULT
