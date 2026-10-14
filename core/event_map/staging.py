"""스테이징 — 동결한 이벤트 맵 조합의 랜덤 풀(사용자 지시 2026-10-14).

사용자가 여러 조합을 무작위로 쓰고 싶을 때, 조합(핀 · 제외 · 등급 · 인원)을 **그 순간 그대로** 얼려서 풀에 넣는다.
이벤트 맵에서 핀을 바꿔도 얼린 조합은 바뀌지 않는다. [ST Random](랜덤 버튼 연결의 스테이징 갈래)은 풀에서 조합 하나를
고르게(같은 확률로) 고른 뒤, 그 조합의 실제 게시물 하나를 뽑는다(`headless_random_prompt_service`).

저장 = `save/event_map/staging.json`(재시작해도 남는다 - 사용자 데이터). 저장된 조합(library)과 같은 선택 규칙을 쓴다.
"""
from __future__ import annotations

import json
import os
import random
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.event_map.library import EventMapLibrary, selection
from core.event_map.service import MapQueryError

_LOCK = threading.RLock()
SCHEMA = "naia-event-map-staging-v1"
MAX_ITEMS = 200


class EventMapStaging:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _read(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("schema") != SCHEMA or not isinstance(data.get("items"), list):
                raise ValueError("schema")
            items = data["items"][:MAX_ITEMS]
            for row in items:
                uuid.UUID(row["id"])
                row["selection"] = selection(row["selection"])
            return items
        except (OSError, ValueError, KeyError, TypeError, AttributeError, MapQueryError) as exc:
            raise MapQueryError("staging_error", "스테이징 파일을 읽을 수 없습니다. 원본 파일은 보존됩니다.") from exc

    def _write(self, items: list[dict]) -> None:
        encoded = json.dumps({"schema": SCHEMA, "items": items}, ensure_ascii=False, indent=2)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".event-map-staging-", suffix=".tmp", delete=False) as file:
                file.write(encoded)
                file.flush()
                os.fsync(file.fileno())
                temporary = file.name
            os.replace(temporary, self.path)
        except OSError as exc:
            raise MapQueryError("staging_error", "스테이징을 저장하지 못했습니다. 폴더의 쓰기 권한을 확인해주세요.") from exc

    def list(self) -> dict:
        with _LOCK:
            return {"ok": True, "items": self._read()}

    def add_many(self, selections: list) -> dict:
        """얼려 넣는다. 이미 있는 조합(같은 지문)은 건너뛴다 - `added` 가 실제로 들어간 수."""
        clean = [selection(s) for s in selections]
        if any(not s["pins"] for s in clean):
            raise MapQueryError("bad_request", "태그를 하나 이상 꽂은 조합만 스테이징할 수 있습니다.")
        with _LOCK:
            items = self._read()
            seen = {EventMapLibrary._fingerprint(r["selection"]) for r in items}
            added = 0
            for s in clean:
                key = EventMapLibrary._fingerprint(s)
                if key in seen:
                    continue
                if len(items) >= MAX_ITEMS:
                    raise MapQueryError("bad_request", f"스테이징은 {MAX_ITEMS}개까지입니다.")
                items.append({"id": str(uuid.uuid4()), "selection": s,
                              "added_at": datetime.now(timezone.utc).isoformat()})
                seen.add(key)
                added += 1
            if added:
                self._write(items)
            return {"ok": True, "items": items, "added": added}

    def remove(self, item_id: str) -> dict:
        with _LOCK:
            items = self._read()
            kept = [r for r in items if r["id"] != item_id]
            if len(kept) == len(items):
                raise MapQueryError("not_found", "이미 빠졌거나 없는 조합입니다.")
            self._write(kept)
            return {"ok": True, "items": kept}

    def clear(self) -> dict:
        with _LOCK:
            self._write([])
            return {"ok": True, "items": []}

    def pick(self, rng: random.Random | None = None) -> dict | None:
        """[ST Random] - 조합 하나를 같은 확률로."""
        items = self.list()["items"]
        if not items:
            return None
        return (rng or random).choice(items)
