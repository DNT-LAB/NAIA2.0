# -*- coding: utf-8 -*-
"""Artist groups — named collections of artists (e.g. "realistic", "fully comic").

Stored in their own file, ``artist_groups.json``, next to ``artist_state.json``.

⚠️ **Not inside artist_state.json.** That file's ``_normalize_state`` keeps only
   ``{version, favorites, banned}`` and rewrites the whole record on every favorite
   toggle -- any ``groups`` key would be silently wiped by the next click on 관심.
   A narrow writer that owns a whole record is exactly how this repo has lost data
   before, so groups get a file and a lock of their own.

⚠️ A file we cannot parse is **never overwritten**. Reads raise, the route answers
   500, and the user's original stays on disk for recovery. Rewriting it with an
   empty default would turn a transient read problem into permanent loss.

Groups are shared across API modes (NAI / WebUI / ComfyUI): only the artist name and
an optional default weight are stored. The mode-specific spelling (``0.8::artist:x ::``
vs ``(x:0.8)``) is applied when the queue composes a prompt, never here.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
MAX_GROUPS = 200
MAX_ITEMS_PER_GROUP = 2000
MAX_NAME_LEN = 40
MAX_ARTIST_LEN = 200
WEIGHT_MIN = -5.0
WEIGHT_MAX = 5.0


class ArtistGroupError(ValueError):
    """Bad request against the group store (maps to HTTP 400/404/409)."""

    def __init__(self, message: str, *, status: int = 400):
        super().__init__(message)
        self.status = status


def _clean_name(value: Any) -> str:
    name = " ".join(str(value or "").split())
    if not name:
        raise ArtistGroupError("group name is required")
    if len(name) > MAX_NAME_LEN:
        raise ArtistGroupError(f"group name is longer than {MAX_NAME_LEN} characters")
    return name


def _clean_artist(value: Any) -> str:
    # 작가 이름은 이 앱에서 공백을 쓴다("kanon (kurogane knights)"). 밑줄로 바꾸지 않는다.
    artist = " ".join(str(value or "").split())
    if artist.lower().startswith("artist:"):
        artist = artist[len("artist:"):].strip()
    if not artist or len(artist) > MAX_ARTIST_LEN:
        return ""
    return artist


def _clean_weight(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    number = max(WEIGHT_MIN, min(WEIGHT_MAX, number))
    return round(number, 2)


def _clean_item(raw: Any) -> dict | None:
    if isinstance(raw, str):
        raw = {"artist": raw}
    if not isinstance(raw, dict):
        return None
    artist = _clean_artist(raw.get("artist"))
    if not artist:
        return None
    item: dict[str, Any] = {"artist": artist}
    weight = _clean_weight(raw.get("weight"))
    if weight is not None and weight != 1.0:
        item["weight"] = weight
    return item


def _dedupe_items(items: list[dict]) -> list[dict]:
    """같은 작가는 **처음 자리**에 한 번만 남는다(대소문자 무시)."""
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        key = item["artist"].casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


class ArtistGroupStore:
    """Thread-safe owner of ``artist_groups.json``. Every mutation returns the full list."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self._lock = threading.RLock()

    # ── 디스크 ────────────────────────────────────────────────────────────
    @property
    def path(self) -> Path:
        return self.root / "artist_groups.json"

    def _read(self) -> list[dict]:
        path = self.path
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - 원본을 지키는 것이 우선이다
            raise RuntimeError(f"artist groups file is unreadable: {path}: {exc}") from exc
        groups = data.get("groups") if isinstance(data, dict) else None
        if not isinstance(groups, list):
            raise RuntimeError(f"artist groups file has no 'groups' list: {path}")
        return [g for g in (self._normalize_group(raw) for raw in groups) if g]

    def _write(self, groups: list[dict]) -> None:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": SCHEMA_VERSION, "groups": groups},
                             ensure_ascii=False, indent=2) + "\n"
        temp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        temp_path.write_text(payload, encoding="utf-8")
        try:
            os.replace(temp_path, path)
        except PermissionError:
            # 백신·색인기가 잠깐 쥐고 있는 경우 - 기존 서비스와 같은 퇴로.
            path.write_text(payload, encoding="utf-8")
            try:
                temp_path.unlink(missing_ok=True)
            except PermissionError:
                pass

    @staticmethod
    def _normalize_group(raw: Any) -> dict | None:
        if not isinstance(raw, dict):
            return None
        gid = str(raw.get("id") or "").strip()
        if not gid:
            return None
        try:
            name = _clean_name(raw.get("name"))
        except ArtistGroupError:
            return None
        items = [i for i in (_clean_item(x) for x in (raw.get("items") or [])) if i]
        now = int(time.time())
        return {
            "id": gid,
            "name": name,
            "items": _dedupe_items(items)[:MAX_ITEMS_PER_GROUP],
            "created": int(raw.get("created") or now),
            "updated": int(raw.get("updated") or now),
        }

    # ── 조회 ──────────────────────────────────────────────────────────────
    def list(self) -> list[dict]:
        with self._lock:
            return self._read()

    def _find(self, groups: list[dict], group_id: Any) -> dict:
        gid = str(group_id or "").strip()
        for group in groups:
            if group["id"] == gid:
                return group
        raise ArtistGroupError(f"group not found: {gid}", status=404)

    @staticmethod
    def _name_taken(groups: list[dict], name: str, *, except_id: str = "") -> bool:
        folded = name.casefold()
        return any(g["name"].casefold() == folded and g["id"] != except_id for g in groups)

    # ── 바꾸기 ────────────────────────────────────────────────────────────
    def create(self, name: Any, items: Any = None) -> dict:
        with self._lock:
            groups = self._read()
            clean = _clean_name(name)
            if self._name_taken(groups, clean):
                raise ArtistGroupError(f"a group named '{clean}' already exists", status=409)
            if len(groups) >= MAX_GROUPS:
                raise ArtistGroupError(f"too many groups (max {MAX_GROUPS})")
            now = int(time.time())
            added = [i for i in (_clean_item(x) for x in (items or [])) if i]
            group = {
                "id": f"g_{uuid.uuid4().hex[:12]}",
                "name": clean,
                "items": _dedupe_items(added)[:MAX_ITEMS_PER_GROUP],
                "created": now,
                "updated": now,
            }
            groups.append(group)
            self._write(groups)
            return {"group": group, "groups": groups}

    def rename(self, group_id: Any, name: Any) -> dict:
        with self._lock:
            groups = self._read()
            group = self._find(groups, group_id)
            clean = _clean_name(name)
            if self._name_taken(groups, clean, except_id=group["id"]):
                raise ArtistGroupError(f"a group named '{clean}' already exists", status=409)
            group["name"] = clean
            group["updated"] = int(time.time())
            self._write(groups)
            return {"group": group, "groups": groups}

    def delete(self, group_id: Any) -> dict:
        with self._lock:
            groups = self._read()
            group = self._find(groups, group_id)
            groups = [g for g in groups if g["id"] != group["id"]]
            self._write(groups)
            return {"groups": groups}

    def add(self, group_id: Any, items: Any) -> dict:
        """이미 있는 작가는 **자리를 지키고** 건너뛴다 - 복사해 오는 조작이 순서를
        흔들면 안 된다. 몇 개가 실제로 들어갔는지 `added` 로 알려 준다."""
        with self._lock:
            groups = self._read()
            group = self._find(groups, group_id)
            incoming = [i for i in (_clean_item(x) for x in (items or [])) if i]
            if not incoming:
                raise ArtistGroupError("no valid artist to add")
            have = {i["artist"].casefold() for i in group["items"]}
            fresh = []
            for item in _dedupe_items(incoming):
                if item["artist"].casefold() in have:
                    continue
                fresh.append(item)
                have.add(item["artist"].casefold())
            room = MAX_ITEMS_PER_GROUP - len(group["items"])
            if room <= 0 and fresh:
                raise ArtistGroupError(f"group is full (max {MAX_ITEMS_PER_GROUP})")
            fresh = fresh[:max(room, 0)]
            group["items"].extend(fresh)
            if fresh:
                group["updated"] = int(time.time())
                self._write(groups)
            return {"group": group, "groups": groups, "added": len(fresh),
                    "skipped": len(incoming) - len(fresh)}

    def remove(self, group_id: Any, artists: Any) -> dict:
        with self._lock:
            groups = self._read()
            group = self._find(groups, group_id)
            names = artists if isinstance(artists, list) else [artists]
            drop = {_clean_artist(n).casefold() for n in names if _clean_artist(n)}
            before = len(group["items"])
            group["items"] = [i for i in group["items"] if i["artist"].casefold() not in drop]
            removed = before - len(group["items"])
            if removed:
                group["updated"] = int(time.time())
                self._write(groups)
            return {"group": group, "groups": groups, "removed": removed}

    def reorder(self, group_id: Any, artists: Any) -> dict:
        """보낸 순서대로 앞에 세우고, 보내지 않은 것은 원래 순서로 뒤에 붙인다 -
        목록 일부만 보낸 요청이 나머지를 지우면 안 된다."""
        with self._lock:
            groups = self._read()
            group = self._find(groups, group_id)
            order = [_clean_artist(n).casefold() for n in (artists or []) if _clean_artist(n)]
            by_key = {i["artist"].casefold(): i for i in group["items"]}
            head = []
            for key in order:
                item = by_key.pop(key, None)
                if item is not None:
                    head.append(item)
            tail = [i for i in group["items"] if i["artist"].casefold() in by_key]
            group["items"] = head + tail
            group["updated"] = int(time.time())
            self._write(groups)
            return {"group": group, "groups": groups}

    def set_weight(self, group_id: Any, artist: Any, weight: Any) -> dict:
        with self._lock:
            groups = self._read()
            group = self._find(groups, group_id)
            key = _clean_artist(artist).casefold()
            target = next((i for i in group["items"] if i["artist"].casefold() == key), None)
            if target is None:
                raise ArtistGroupError(f"artist not in group: {artist}", status=404)
            clean = _clean_weight(weight)
            if clean is None or clean == 1.0:
                target.pop("weight", None)
            else:
                target["weight"] = clean
            group["updated"] = int(time.time())
            self._write(groups)
            return {"group": group, "groups": groups}
