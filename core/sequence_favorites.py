"""Sequence 즐겨찾기 - 그룹 번호 목록을 user-data 의 JSON 한 파일에 둔다(사용자 지시 2026-10-18).

SEQ Random 으로 나온 이야기를 다시 찾을 길이 없었다 - 별을 달아 두면 재시작 뒤에도 남는다.
파일에는 그룹 번호와 단 시각만 둔다. 카드에 그릴 요약(수위 · 컷 · 단계 · 미리보기)은 읽을 때마다
데이터에서 다시 꺼낸다 - 데이터가 바뀌어 빠진 그룹은 `missing` 으로 남겨 사용자가 별을 뗄 수 있게 한다.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
FAVORITES_FILE_NAME = "sequence_favorites.json"
# 별은 사람이 하나씩 다는 것이라 넉넉하게 - 파일이 끝없이 커지지만 않게 막는다.
MAX_FAVORITES = 2000


class SequenceFavoritesStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read(self) -> list[dict[str, int]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError):
            return []          # 상한 파일 - 빈 목록으로 산다(다음 저장이 새로 쓴다)
        rows = data.get("favorites") if isinstance(data, dict) else None
        out: list[dict[str, int]] = []
        seen: set[int] = set()
        for row in rows if isinstance(rows, list) else []:
            try:
                gid = int(row.get("groupId"))
            except (AttributeError, TypeError, ValueError):
                continue       # 한 줄이 상해도 나머지는 산다
            if gid < 0 or gid in seen:
                continue
            seen.add(gid)
            out.append({"groupId": gid, "added": int(row.get("added") or 0)})
        return out

    def _write(self, rows: list[dict[str, int]]) -> None:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": SCHEMA_VERSION, "favorites": rows}, ensure_ascii=False, indent=2) + "\n"
        temp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        temp_path.write_text(payload, encoding="utf-8")
        try:
            os.replace(temp_path, path)
        except PermissionError:
            path.write_text(payload, encoding="utf-8")
            try:
                temp_path.unlink(missing_ok=True)
            except PermissionError:
                pass

    def entries(self) -> list[dict[str, int]]:
        """새로 단 것이 먼저."""
        with self._lock:
            return self._read()

    def mark(self, group_id: int, favorite: bool) -> list[dict[str, int]]:
        gid = int(group_id)
        if gid < 0:
            raise ValueError("groupId is invalid.")
        with self._lock:
            rows = [row for row in self._read() if row["groupId"] != gid]
            if favorite:
                if len(rows) >= MAX_FAVORITES:
                    raise ValueError(f"즐겨찾기는 최대 {MAX_FAVORITES}개입니다.")
                rows.insert(0, {"groupId": gid, "added": int(time.time())})
            self._write(rows)
            return rows
