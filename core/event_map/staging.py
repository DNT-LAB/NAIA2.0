"""스테이징 — 동결한 이벤트 맵 조합의 랜덤 풀(사용자 지시 2026-10-14).

사용자가 여러 조합을 무작위로 쓰고 싶을 때, 조합(핀 · 제외 · 등급 · 인원)을 **그 순간 그대로** 얼려서 풀에 넣는다.
이벤트 맵에서 핀을 바꿔도 얼린 조합은 바뀌지 않는다. [ST Random](랜덤 버튼 연결의 스테이징 갈래)은 풀에서 조합 하나를
고르게(같은 확률로) 고른 뒤, 그 조합의 실제 게시물 하나를 뽑는다(`headless_random_prompt_service`).

저장 = `save/event_map/staging.json`(재시작해도 남는다 - 사용자 데이터). 저장된 조합(library)과 같은 선택 규칙을 쓴다.

추가 프롬프트(사용자 지시 2026-10-19 - `extra_prompt`): 파일 맨 위 `extra` = 공통 `{on, text, mode}`, 줄마다 `extra` =
`{on, text}`. 지문(같은 조합 검사)에는 넣지 않는다 - 글이 달라도 같은 조합이다. [비우기] 는 조합만 비운다(공통은 설정이다).
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

from core.event_map.extra_prompt import clean_mode, clean_text, common_of, extra_of
from core.event_map.library import EventMapLibrary, selection
from core.event_map.service import MapQueryError

_LOCK = threading.RLock()
SCHEMA = "naia-event-map-staging-v1"
MAX_ITEMS = 200


class EventMapStaging:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._common = common_of(None)

    def _load(self) -> tuple[list[dict], int]:
        """(조합들, 판 번호). 판 번호(`rev`)는 쓸 때마다 1씩 오른다 - 화면이 늦게 온 응답을 버리는 데 쓴다(옛 파일 = 0).

        `gen`(세대)은 파일이 새로 생기거나 깨진 파일을 비우기로 되살릴 때 바뀐다 - 그때 판 번호가 다시 낮아지므로 화면은
        세대가 다르면 번호와 상관없이 받는다(재리뷰 2026-10-15). `self._gen` 에 읽은 세대를 둔다.
        """
        self._gen = ""
        self._common = common_of(None)   # 공통 추가 프롬프트(옛 파일 = 꺼짐)
        if not self.path.exists():
            return [], 0
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("schema") != SCHEMA or not isinstance(data.get("items"), list):
                raise ValueError("schema")
            # 공통은 줄 검증 **앞에서** 읽는다 - 줄 하나가 깨져 [비우기]로 되살릴 때 멀쩡한 공통까지 지우지 않게(Codex 7차)
            self._common = common_of(data.get("extra"))
            items = data["items"][:MAX_ITEMS]
            for row in items:
                uuid.UUID(row["id"])
                row["selection"] = selection(row["selection"])
                row["enabled"] = row.get("enabled") is not False   # 옛 줄 = 켜짐
                row["extra"] = extra_of(row.get("extra"))           # 옛 줄 = 추가 프롬프트 꺼짐
            rev = data.get("rev", 0)
            self._gen = str(data.get("gen") or "")
            return items, rev if isinstance(rev, int) and rev >= 0 else 0
        except (OSError, ValueError, KeyError, TypeError, AttributeError, MapQueryError) as exc:
            raise MapQueryError("staging_error", "스테이징 파일을 읽을 수 없습니다. 원본 파일은 보존됩니다.") from exc

    def _read(self) -> list[dict]:
        return self._load()[0]

    def _write(self, items: list[dict], rev: int, gen: str | None = None) -> None:
        self._gen = gen or getattr(self, "_gen", "") or uuid.uuid4().hex
        encoded = json.dumps({"schema": SCHEMA, "gen": self._gen, "rev": rev, "extra": self._common, "items": items},
                             ensure_ascii=False, indent=2)
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

    def _reply(self, items: list[dict], rev: int, **more) -> dict:
        return {"ok": True, "items": items, "rev": rev, "gen": self._gen, "extra": dict(self._common), **more}

    def list(self) -> dict:
        with _LOCK:
            items, rev = self._load()
            return self._reply(items, rev)

    def add_many(self, selections: list, enabled: list | None = None, extras: list | None = None,
                 common: dict | None = None) -> dict:
        """얼려 넣는다. 이미 있는 조합(같은 지문)은 건너뛴다 - `added` 가 실제로 들어간 수.

        `enabled` = 조합마다 켜짐(묶음을 다시 스테이징할 때 저장해 둔 상태). 없으면 전부 켜짐.
        `extras` = 조합마다 추가 프롬프트(묶음에 저장해 둔 것). 건너뛴 조합의 글은 버린다 - 이미 있는 줄의 글을 덮지 않는다.
        `common` = 묶음의 공통 추가 프롬프트. **지금 공통 칸이 비어 있을 때만** 가져온다(쓰던 글을 몰래 덮지 않는다) -
        `common_adopted` 로 알린다.
        """
        clean = [selection(s) for s in selections]
        enabled = enabled if isinstance(enabled, list) else None
        flags = [bool(enabled[i]) if enabled and i < len(enabled) else True for i in range(len(clean))]
        extras = extras if isinstance(extras, list) else []
        texts = [extra_of(extras[i]) if i < len(extras) else extra_of(None) for i in range(len(clean))]
        if any(not s["pins"] for s in clean):
            raise MapQueryError("bad_request", "태그를 하나 이상 꽂은 조합만 스테이징할 수 있습니다.")
        with _LOCK:
            items, rev = self._load()
            seen = {EventMapLibrary._fingerprint(r["selection"]) for r in items}
            added = 0
            for s, on, extra in zip(clean, flags, texts):
                key = EventMapLibrary._fingerprint(s)
                if key in seen:
                    continue
                if len(items) >= MAX_ITEMS:
                    raise MapQueryError("bad_request", f"스테이징은 {MAX_ITEMS}개까지입니다.")
                items.append({"id": str(uuid.uuid4()), "selection": s, "enabled": on, "extra": extra,
                              "added_at": datetime.now(timezone.utc).isoformat()})
                seen.add(key)
                added += 1
            adopted = False
            if isinstance(common, dict) and not self._common["text"]:
                incoming = common_of(common)
                if incoming["text"]:
                    self._common = incoming
                    adopted = True
            if added or adopted:
                rev += 1
                self._write(items, rev)
            return self._reply(items, rev, added=added, common_adopted=adopted)

    def remove(self, item_id: str) -> dict:
        with _LOCK:
            items, rev = self._load()
            kept = [r for r in items if r["id"] != item_id]
            if len(kept) == len(items):
                raise MapQueryError("not_found", "이미 빠졌거나 없는 조합입니다.")
            self._write(kept, rev + 1)
            return self._reply(kept, rev + 1)

    def toggle(self, item_id: str, enabled: bool) -> dict:
        """줄 켜기 · 끄기 - 꺼진 조합은 ST Random 후보 · 전체 수에서 빠진다(사용자 지시 2026-10-15)."""
        with _LOCK:
            items, rev = self._load()
            row = next((r for r in items if r["id"] == item_id), None)
            if row is None:
                raise MapQueryError("not_found", "이미 빠졌거나 없는 조합입니다.")
            if row["enabled"] == bool(enabled):
                return self._reply(items, rev)
            row["enabled"] = bool(enabled)
            self._write(items, rev + 1)
            return self._reply(items, rev + 1)

    def set_extra(self, item_id: str, on, text) -> dict:
        """줄의 추가 프롬프트 - 켜기 · 글. 끈 채로도 글은 남는다(다시 켜면 그대로)."""
        patch = {"on": on is True, "text": clean_text(text)}
        with _LOCK:
            items, rev = self._load()
            row = next((r for r in items if r["id"] == item_id), None)
            if row is None:
                raise MapQueryError("not_found", "이미 빠졌거나 없는 조합입니다.")
            if row["extra"] == patch:
                return self._reply(items, rev)
            row["extra"] = patch
            self._write(items, rev + 1)
            return self._reply(items, rev + 1)

    def set_common(self, on=None, text=None, mode=None) -> dict:
        """공통 추가 프롬프트 · 방식. 준 것만 바꾼다(None = 그대로)."""
        patch = {}
        if on is not None:
            patch["on"] = on is True
        if text is not None:
            patch["text"] = clean_text(text)
        if mode is not None:
            patch["mode"] = clean_mode(mode)
        with _LOCK:
            items, rev = self._load()
            merged = {**self._common, **patch}
            if merged == self._common:
                return self._reply(items, rev)
            self._common = merged
            self._write(items, rev + 1)
            return self._reply(items, rev + 1)

    def clear(self) -> dict:
        with _LOCK:
            try:
                rev, gen = self._load()[1], None
            except MapQueryError:   # 깨진 파일도 비우기로는 덮을 수 있어야 한다(복구 길) - 새 세대
                rev, gen = 0, uuid.uuid4().hex
            self._write([], rev + 1, gen)
            return self._reply([], rev + 1)

    def pick(self, rng: random.Random | None = None) -> dict | None:
        """[ST Random] - 켜진 조합 하나를 같은 확률로."""
        items = [r for r in self.list()["items"] if r["enabled"]]
        if not items:
            return None
        return (rng or random).choice(items)
