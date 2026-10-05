"""E621 태그의 인원 분포 - 그 태그가 붙은 게시물 가운데 solo · duo · trio · group 이 함께 붙은 수.

관계 팩(e621_relations.pack)으로는 이것을 알 수 없다. 팩은 '평소의 2배 이상 자주 붙는 짝' 만 태그당 16개 담는데,
solo 는 전체 게시물의 절반에 붙어 있어 원리상 2배가 될 수 없고(실측 2026-10-05: 팩 전체에서 0건) duo 도 그 태그의
71% 이상에 붙을 때만 담긴다. 그래서 게시물 스냅숏에서 직접 센 표를 따로 싣는다(tools/build_e621_count_profile.py).

쓰는 곳은 연구모듈의 테스트 생성 하나다 - 고른 태그가 '혼자서는 거의 안 나오는 태그' 일 때만 인원 태그를 넣는다
(사용자 지정 2026-10-05: "특이점이 없는 경우에는 1girl 만 넣고 인원 태그를 사용하지 않습니다").
"""
from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

SCHEMA = "naia.e621-count-profile.v1"
FILE_NAME = "e621_count_profile.parquet"
METADATA_KEY = b"naia"
COUNT_TAGS = ("solo", "duo", "trio", "group")

# 인원 태그를 붙이는 기준. 표에는 센 수만 있고 기준은 여기 있다 - 기준을 고쳐도 표를 다시 만들지 않는다.
#   · 혼자 나오는 게시물이 15% 이하이고, 둘 이상(duo + group)이 75% 이상일 때만 붙인다.
#     (실측: from_behind_position solo 1% · kissing 2% · fellatio 2% 는 붙고, all_fours 29% · sleeping 34% ·
#      masturbation 65% · looking_at_viewer 81% 는 안 붙는다. 게시물 1,000 이상 태그 7,484개 중 938개가 붙는다.)
#   · e621 의 group 은 셋 이상이고 trio 는 group 에 든다. 셋 이상 쪽이 더 많을 때, trio 가 60% 이상이면 trio.
SOLO_MAX = 0.15
MULTI_MIN = 0.75
TRIO_MIN = 0.6


def pick_count_tag(total: int, solo: int, duo: int, trio: int, group: int) -> str:
    """붙일 인원 태그. 특이점이 없으면 빈 문자열."""
    if total <= 0 or solo / total > SOLO_MAX or (duo + group) / total < MULTI_MIN:
        return ""
    if duo >= group:
        return "duo"
    return "trio" if trio / total >= TRIO_MIN else "group"


class E621CountProfile:
    """만들 때는 읽지 않는다. 처음 물을 때 한 번 읽는다. 파일이 없거나 깨졌으면 '모름' 으로 떨어진다(앱은 산다)."""

    def __init__(self, repo_root: Path, *, data_roots: list[Path] | None = None):
        self.repo_root = Path(repo_root)
        self.data_roots = list(dict.fromkeys([self.repo_root / "data", *[
            root if root.is_absolute() else self.repo_root / root
            for root in map(Path, data_roots or [])]]))
        self.loaded = False
        self.last_error: str | None = None
        self.source_path: Path | None = None
        self.meta: dict[str, Any] = {}
        # 줄마다 파이썬 값으로 풀지 않는다 - 태그 → 줄 번호와 열 배열만 둔다(물을 때 그 줄만 읽는다).
        self._index: dict[str, int] = {}
        self._columns: list[Any] = []
        self._attempted = False
        self._lock = Lock()

    def load(self) -> bool:
        with self._lock:
            if self._attempted:
                return self.loaded
            self._attempted = True
            for root in self.data_roots:
                source = root / FILE_NAME
                if not source.exists():
                    continue
                self.source_path = source
                try:
                    import pyarrow.parquet as pq

                    table = pq.read_table(source)
                    meta = json.loads((table.schema.metadata or {}).get(METADATA_KEY) or b"{}")
                    if meta.get("schema") != SCHEMA:
                        raise ValueError("unexpected count profile schema")
                    self._columns = [table.column(name).to_numpy() for name in ("total", *COUNT_TAGS)]
                    self._index = {tag: row for row, tag in enumerate(table.column("tag").to_pylist()) if tag}
                    self.meta = meta
                    self.loaded = True
                    return True
                except Exception as exc:  # 읽을 수 없는 표는 '없음' 과 같다 - 인원 태그를 안 붙일 뿐이다
                    self.last_error = type(exc).__name__ + ": " + str(exc)
                    self._index, self._columns = {}, []
                    return False
            return False

    def __len__(self) -> int:
        self.load()
        return len(self._index)

    def counts(self, exact_tag: str) -> tuple[int, int, int, int, int] | None:
        """(이 태그의 게시물 수, solo, duo, trio, group). 표에 없는 태그는 None('모름' 이지 '혼자' 가 아니다)."""
        self.load()
        row = self._index.get(exact_tag)
        if row is None:
            return None
        counts = tuple(int(column[row]) for column in self._columns)
        return counts if counts[0] > 0 else None

    def describe(self, exact_tag: str) -> dict[str, Any] | None:
        """화면용: 붙일 인원 태그와 비율. 표에 없으면 None."""
        row = self.counts(exact_tag)
        if row is None:
            return None
        total = row[0]
        # 인원 태그 자신에게는 붙이지 않는다(duo 를 고르면 duo, duo 가 되지 않게).
        tag = "" if exact_tag in COUNT_TAGS else pick_count_tag(*row)
        return {"tag": tag, "total": total,
                "shares": {name: row[index + 1] / total for index, name in enumerate(COUNT_TAGS)}}
