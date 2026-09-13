"""User-owned saved Event Map selections. Independent of the optional index."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.event_map.service import MapQueryError
from core.tag_combo.person import PERSON_GROUPS, normalize_tag

_LOCK = threading.RLock()
SCHEMA = "naia-event-map-library-v1"
MAX_ENTRIES = 2000


def _text(value, label, limit, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise MapQueryError("bad_request", f"{label} 내용을 확인해주세요. (최대 {limit}자)")
    return value.strip()


def selection(value):
    if not isinstance(value, dict):
        raise MapQueryError("bad_request", "저장할 조합이 없습니다.")
    result = {}
    for key, cap in (("pins", 16), ("exclude", 32), ("ratings", 4), ("persons", 13)):
        items = value.get(key)
        if not isinstance(items, list) or len(items) > cap:
            raise MapQueryError("bad_request", f"{key} 목록을 확인해주세요.")
        result[key] = list(dict.fromkeys(_text(v, key, 160, True) for v in items))
    if not result["ratings"] or set(result["ratings"]) - set("gsqe"):
        raise MapQueryError("bad_request", "등급을 하나 이상 선택해주세요.")
    if not result["persons"] or set(result["persons"]) - set(PERSON_GROUPS):
        raise MapQueryError("bad_request", "인원을 하나 이상 선택해주세요.")
    if set(result["pins"]) & set(result["exclude"]):
        raise MapQueryError("bad_request", "같은 태그를 포함과 제외에 함께 저장할 수 없습니다.")
    return result


class EventMapLibrary:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _read(self):
        self._categories = []
        if not self.path.exists():
            return []
        try:
            if self.path.stat().st_size > 20_000_000:
                raise ValueError("file too large")
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("schema") != SCHEMA or not isinstance(data.get("items"), list):
                raise ValueError("schema")
            items = data["items"]
            if len(items) > MAX_ENTRIES:
                raise ValueError("too many entries")
            ids = set()
            for row in items:
                uuid.UUID(row["id"])
                if row["id"] in ids:
                    raise ValueError("duplicate id")
                ids.add(row["id"])
                _text(row["name"], "이름", 100, True)
                _text(row["category"], "분류", 60)
                _text(row["created_at"], "생성 시각", 80, True)
                selection(row["selection"])
            categories = data.get("categories", [])
            if not isinstance(categories, list) or len(categories) > 500:
                raise ValueError("categories")
            self._categories = list(dict.fromkeys(
                [_text(c, "분류", 60, True) for c in categories] + [r["category"] for r in items if r["category"]]))
            return items
        except (OSError, ValueError, KeyError, TypeError, AttributeError, MapQueryError) as exc:
            raise MapQueryError("library_error", "저장된 조합 파일을 읽을 수 없습니다. 원본 파일은 보존됩니다.") from exc

    def list(self):
        with _LOCK:
            items = self._read()
            return {"ok": True, "items": items, "categories": self._categories}

    def save(self, payload):
        try:
            item_id = str(uuid.UUID(payload.get("id", "")))
        except (ValueError, TypeError, AttributeError) as exc:
            raise MapQueryError("bad_request", "저장 요청 ID가 잘못되었습니다.") from exc
        selected = selection(payload.get("selection"))
        if not selected["pins"]:
            raise MapQueryError("bad_request", "태그를 하나 이상 선택한 뒤 저장해주세요.")
        row = {"id": item_id,
               "name": _text(payload.get("name", ", ".join(selected["pins"])[:100]), "이름", 100, True),
               "category": _text(payload.get("category", ""), "분류", 60),
               "selection": selected}
        with _LOCK:
            items = self._read()
            for old in items:
                if old["id"] == item_id:
                    if all(old[k] == v for k, v in row.items()):
                        return {"ok": True, "item": old}
                    raise MapQueryError("bad_request", "저장 요청이 중복되었습니다. 저장 창을 다시 열어주세요.")
                if self._fingerprint(old["selection"]) == self._fingerprint(selected):
                    raise MapQueryError("duplicate", "이미 저장된 조합입니다.")
            if len(items) >= MAX_ENTRIES:
                raise MapQueryError("bad_request", "조합은 최대 2,000개까지 저장할 수 있습니다.")
            row["created_at"] = datetime.now(timezone.utc).isoformat()
            items.insert(0, row)
            self._write(items)
            return {"ok": True, "item": row}

    @staticmethod
    def _fingerprint(selected):
        return tuple(tuple(sorted({normalize_tag(v) if k in ("pins", "exclude") else v for v in selected[k]}))
                     for k in ("pins", "exclude", "ratings", "persons"))

    def _write(self, items):
        encoded = json.dumps({"schema": SCHEMA, "items": items, "categories": self._categories}, ensure_ascii=False, indent=2)
        if len(encoded.encode("utf-8")) > 20_000_000:
            raise MapQueryError("bad_request", "저장된 조합 목록이 최대 용량에 도달했습니다.")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".event-map-", suffix=".tmp", delete=False) as file:
                file.write(encoded)
                file.flush()
                os.fsync(file.fileno())
                temporary = file.name
            os.replace(temporary, self.path)
        except OSError as exc:
            raise MapQueryError("library_error", "조합을 저장하지 못했습니다. 폴더의 쓰기 권한을 확인해주세요.") from exc

    def mutate(self, payload):
        action = payload.get("action")
        with _LOCK:
            items = self._read()
            if action == "add_category":
                category = _text(payload.get("category"), "분류", 60, True)
                if category == "미분류":
                    raise MapQueryError("bad_request", "미분류는 기본 분류입니다.")
                if category not in self._categories:
                    if len(self._categories) >= 500:
                        raise MapQueryError("bad_request", "분류는 500개까지 추가할 수 있습니다.")
                    self._categories.append(category)
            elif action in ("move", "delete"):
                row = next((r for r in items if r["id"] == payload.get("id")), None)
                if row is None:
                    raise MapQueryError("not_found", "이미 삭제되었거나 존재하지 않는 조합입니다.")
                if action == "delete":
                    items.remove(row)
                else:
                    category = _text(payload.get("category", ""), "분류", 60)
                    if category and category not in self._categories:
                        raise MapQueryError("bad_request", "분류를 먼저 추가해주세요.")
                    previous = row["category"]
                    row["category"] = category
            else:
                raise MapQueryError("bad_request", "지원하지 않는 목록 작업입니다.")
            self._write(items)
            result = {"ok": True, "items": items, "categories": self._categories}
            if action == "move":
                result.update(previous_category=previous, category=category)
            return result
