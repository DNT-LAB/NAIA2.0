"""Explicitly saved staging snapshots; common extra prompts remain settings."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.event_map.extra_prompt import extra_of
from core.event_map.library import EventMapLibrary, has_include, selection
from core.event_map.service import MapQueryError
from core.event_map.staging import MAX_ITEMS

SCHEMA = "naia-event-map-staging-presets-v1"
MAX_PRESETS = 50
MAX_GROUPS = 20
_LOCK = threading.RLock()


def _rows(rows):
    if not isinstance(rows, list) or len(rows) > MAX_ITEMS:
        raise MapQueryError("bad_request", f"스테이징은 {MAX_ITEMS}개까지입니다.")
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise MapQueryError("bad_request", "조합 목록을 확인해주세요.")
        selected = selection(row.get("selection"))
        if not has_include(selected):
            raise MapQueryError("bad_request", "포함 조건이 하나 이상 있어야 합니다.")
        result.append({"selection": selected, "enabled": row.get("enabled") is not False,
                       "extra": extra_of(row.get("extra"))})
    return result


def signature(rows):
    return [(EventMapLibrary._fingerprint(r["selection"]), r["enabled"], r["extra"]["on"], r["extra"]["text"])
            for r in _rows(rows)]


def _name(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 40:
        raise MapQueryError("bad_request", "프리셋 이름은 1~40자입니다.")
    return value.strip()


def _group(value, allow_empty=True):
    """프리셋 그룹(사용자 지시 2026-11-02). '' = 미분류. 옛 파일에는 없다 - 읽을 때 '' 로 본다."""
    if value is None and allow_empty:
        return ""
    if not isinstance(value, str) or len(value.strip()) > 20 or (not value.strip() and not allow_empty):
        raise MapQueryError("bad_request", "그룹 이름은 1~20자입니다.")
    if value.strip() in ("전체", "미분류"):   # 화면이 쓰는 이름 - 칩이 둘로 보인다
        raise MapQueryError("bad_request", "'전체' · '미분류' 는 그룹 이름으로 쓸 수 없습니다.")
    return value.strip()


class EventMapStagingPresets:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _read(self):
        if not self.path.exists():
            return {"schema": SCHEMA, "active": None, "groups": [], "items": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("schema") != SCHEMA or not isinstance(data.get("items"), list):
                raise ValueError("schema")
            if len(data["items"]) > MAX_PRESETS:
                raise ValueError("too many presets")
            groups = data.setdefault("groups", [])
            if not isinstance(groups, list) or len(groups) > MAX_GROUPS:
                raise ValueError("groups")
            data["groups"] = groups = [_group(g, allow_empty=False) for g in groups]
            if len(set(groups)) != len(groups):
                raise ValueError("duplicate group")
            ids, names = set(), set()
            for row in data["items"]:
                uuid.UUID(row["id"])
                name = _name(row["name"])
                if row["id"] in ids or name in names:
                    raise ValueError("duplicate")
                ids.add(row["id"])
                names.add(name)
                row["name"] = name
                for key in ("created_at", "updated_at"):
                    if not isinstance(row[key], str) or not row[key]:
                        raise ValueError("timestamp")
                row["rows"] = _rows(row["rows"])
                row["group"] = _group(row.get("group"))
                if row["group"] and row["group"] not in groups:
                    groups.append(row["group"])   # 목록에서 빠진 그룹은 되살린다(손으로 고친 파일)
            if data.get("active") not in ids:
                data["active"] = None
            return data
        except (OSError, ValueError, KeyError, TypeError, AttributeError, MapQueryError) as exc:
            raise MapQueryError("preset_error", "프리셋 파일을 읽을 수 없습니다. 원본 파일은 보존됩니다.") from exc

    def _write(self, data):
        encoded = json.dumps(data, ensure_ascii=False, indent=2)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".event-map-presets-", suffix=".tmp", delete=False) as file:
                file.write(encoded)
                file.flush()
                os.fsync(file.fileno())
                temporary = file.name
            os.replace(temporary, self.path)
        except OSError as exc:
            raise MapQueryError("preset_error", "프리셋을 저장하지 못했습니다. 폴더의 쓰기 권한을 확인해주세요.") from exc

    @staticmethod
    def _find(data, item_id):
        row = next((r for r in data["items"] if r["id"] == item_id), None)
        if row is None:
            raise MapQueryError("not_found", "이미 삭제되었거나 존재하지 않는 프리셋입니다.")
        return row

    @staticmethod
    def _unique(data, name, item_id=None):
        if any(r["name"] == name and r["id"] != item_id for r in data["items"]):
            raise MapQueryError("duplicate", "이미 같은 이름의 프리셋이 있습니다.")

    @staticmethod
    def _known_group(data, group):
        group = _group(group)
        if group and group not in data["groups"]:
            raise MapQueryError("not_found", "이미 지웠거나 없는 그룹입니다.")
        return group

    def list(self, current_items):
        with _LOCK:
            data = self._read()
            active = next((r for r in data["items"] if r["id"] == data["active"]), None)
            return {"items": [{"id": r["id"], "name": r["name"], "count": len(r["rows"]), "group": r["group"],
                               "updated_at": r["updated_at"]} for r in data["items"]],
                    "groups": list(data["groups"]),
                    "active": data["active"],
                    "dirty": active is not None and signature(active["rows"]) != signature(current_items)}

    def save_new(self, name, current_items, group=""):
        name, rows = _name(name), _rows(current_items)
        with _LOCK:
            data = self._read()
            group = self._known_group(data, group)
            self._unique(data, name)
            if len(data["items"]) >= MAX_PRESETS:
                raise MapQueryError("bad_request", "프리셋은 50개까지입니다.")
            now = datetime.now(timezone.utc).isoformat()
            row = {"id": str(uuid.uuid4()), "name": name, "created_at": now, "updated_at": now, "rows": rows,
                   "group": group}
            data["items"].append(row)
            data["active"] = row["id"]
            self._write(data)
            return row

    def save(self, item_id, current_items):
        rows = _rows(current_items)
        with _LOCK:
            data = self._read()
            row = self._find(data, item_id)
            row.update(rows=rows, updated_at=datetime.now(timezone.utc).isoformat())
            data["active"] = item_id
            self._write(data)
            return row

    def load(self, item_id):
        with _LOCK:
            data = self._read()
            row = self._find(data, item_id)
            data["active"] = item_id
            self._write(data)
            return row["rows"]

    def rename(self, item_id, name):
        name = _name(name)
        with _LOCK:
            data = self._read()
            row = self._find(data, item_id)
            self._unique(data, name, item_id)
            row.update(name=name, updated_at=datetime.now(timezone.utc).isoformat())
            self._write(data)

    def delete(self, item_id):
        with _LOCK:
            data = self._read()
            data["items"].remove(self._find(data, item_id))
            if data["active"] == item_id:
                data["active"] = None
            self._write(data)

    # -- 그룹(사용자 지시 2026-11-02): 프리셋 줄 1열 = 그룹 · 2열 = 그 그룹의 프리셋 ------------------
    def move(self, item_id, group):
        with _LOCK:
            data = self._read()
            row = self._find(data, item_id)
            row["group"] = self._known_group(data, group)
            self._write(data)

    def group_add(self, name):
        name = _group(name, allow_empty=False)
        with _LOCK:
            data = self._read()
            if name in data["groups"]:
                raise MapQueryError("duplicate", "이미 같은 이름의 그룹이 있습니다.")
            if len(data["groups"]) >= MAX_GROUPS:
                raise MapQueryError("bad_request", f"그룹은 {MAX_GROUPS}개까지입니다.")
            data["groups"].append(name)
            self._write(data)

    def group_rename(self, name, to):
        to = _group(to, allow_empty=False)
        with _LOCK:
            data = self._read()
            name = self._known_group(data, name)
            if not name:
                raise MapQueryError("bad_request", "미분류는 이름을 바꿀 수 없습니다.")
            if to != name and to in data["groups"]:
                raise MapQueryError("duplicate", "이미 같은 이름의 그룹이 있습니다.")
            data["groups"][data["groups"].index(name)] = to
            for row in data["items"]:
                if row["group"] == name:
                    row["group"] = to
            self._write(data)

    def group_delete(self, name):
        """그룹만 지운다 - 안의 프리셋은 미분류로 남는다."""
        with _LOCK:
            data = self._read()
            name = self._known_group(data, name)
            if not name:
                raise MapQueryError("bad_request", "미분류는 지울 수 없습니다.")
            data["groups"].remove(name)
            for row in data["items"]:
                if row["group"] == name:
                    row["group"] = ""
            self._write(data)
