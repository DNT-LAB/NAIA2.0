"""Shared, atomic metadata index for stored Vibe and Character References.

Storage files remain authoritative for availability; the index owns annotations
and single category membership. All public operations serialize through one instance lock.
"""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Any
from urllib.parse import urlencode
import uuid

from core.nai_model_contract import resolve_nai_model_for_context


KINDS = ("vibe", "character_reference")
DEFAULT_SETTINGS = {"reference_type": "character&style", "strength": 1.0, "fidelity": 0.8}


class LibraryError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def safe_component(value: Any) -> str:
    value = str(value or "").strip()
    if not value or value in {".", ".."} or any(c in value for c in '/\\:\x00'):
        raise LibraryError("Invalid storage identifier")
    return value


def finite(value: Any, default=None):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (ValueError, TypeError, OverflowError):
        return default


def clean_encodings(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): v for k, v in value.items()
            if finite(k) is not None and isinstance(v, str) and v}


def reference_settings(value: Any) -> dict:
    value = value if isinstance(value, dict) else {}
    ref_type = value.get("reference_type")
    return {
        "reference_type": ref_type if ref_type in ("character&style", "character", "style") else DEFAULT_SETTINGS["reference_type"],
        "strength": max(0.0, min(1.0, finite(value.get("strength"), DEFAULT_SETTINGS["strength"]))),
        "fidelity": max(0.0, min(1.0, finite(value.get("fidelity"), DEFAULT_SETTINGS["fidelity"]))),
    }


def get_ref_vibe_library(context) -> "RefVibeLibrary":
    # setdefault also prevents concurrent lazy callers from publishing two locks.
    cached = context.__dict__.get("_ref_vibe_library_instance")
    if cached is None:
        cached = context.__dict__.setdefault("_ref_vibe_library_instance", RefVibeLibrary(context))
    return cached


class RefVibeLibrary:
    def __init__(self, context):
        self.context = context
        self._lock = threading.Lock()
        self._index_cache = None
        self._index_signature = None
        self._names_cache: dict[str, dict[str, str]] | None = None
        # Per-path compact summaries only: never keep base64 encoding bodies.
        self._cache: dict[str, tuple[tuple[int, int], dict | None]] = {}

    @staticmethod
    def _empty():
        return {"version": 2, **{kind: {"items": {}, "categories": []} for kind in KINDS}}

    @staticmethod
    def _kind(kind):
        if kind not in KINDS:
            raise LibraryError("kind must be vibe or character_reference")
        return kind

    @staticmethod
    def _atomic_write(path, data):
        payload = json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temp = Path(stream.name)
            try:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            except BaseException:
                stream.close()
                temp.unlink(missing_ok=True)
                raise
        try:
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    @staticmethod
    def _signature(path):
        try:
            stat = path.stat()
            return (str(path), stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            return (str(path), None, None)

    def _cache_index(self, path, data):
        self._index_cache = copy.deepcopy(data)
        self._index_signature = self._signature(path)
        self._names_cache = None

    def _write(self, data):
        path = self.context._save_path("ref_vibe_library.json")
        self._atomic_write(path, data)
        self._cache_index(path, data)

    def _existing_path(self, *parts):
        getter = getattr(self.context, "_existing_save_path", self.context._save_path)
        return getter(*parts)

    @staticmethod
    def _convert_v1(data):
        result = RefVibeLibrary._empty()
        for kind in KINDS:
            mapping = {}
            for group in sorted(data[kind]["groups"], key=lambda g: g.get("order", 0)):
                if "source_cluster" in group:
                    continue
                category_id = "c_" + uuid.uuid4().hex[:12]
                mapping[group["id"]] = category_id
                categories = result[kind]["categories"]
                categories.append({"id": category_id, "name": group["name"], "order": len(categories)})
            for file_hash, item in data[kind]["items"].items():
                item = copy.deepcopy(item)
                memberships = item.pop("groups", [])
                item["category"] = next((mapping[g] for g in memberships if g in mapping), "")
                result[kind]["items"][file_hash] = item
        return result

    def _read(self):
        path = self._existing_path("ref_vibe_library.json")
        if self._index_cache is not None and self._index_signature == self._signature(path):
            # A failed write must not mutate the last successfully cached index.
            return copy.deepcopy(self._index_cache)
        data = self._empty()
        if path.exists():
            try:
                def reject_constant(value):
                    raise ValueError("Non-finite JSON value: " + value)

                data = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
                version = data.get("version", 1) if isinstance(data, dict) else None
                collection = "groups" if version == 1 else "categories"
                if version not in (1, 2) or any(
                    not isinstance(data.get(k), dict)
                    or not isinstance(data[k].get("items"), dict)
                    or not all(isinstance(v, dict) for v in data[k]["items"].values())
                    or not isinstance(data[k].get(collection), list) for k in KINDS
                ):
                    raise ValueError("Invalid library structure")
                if version == 1:
                    data = self._convert_v1(data)
                    self._write(data)
                    return copy.deepcopy(data)
            except (ValueError, UnicodeError, KeyError, TypeError, AttributeError):
                os.replace(path, path.with_name(path.name + f".broken-{time.time():.9f}"))
                data = self._empty()
                self._write(data)
                return copy.deepcopy(data)
        self._cache_index(path, data)
        return copy.deepcopy(data)

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._read())

    def _roots(self, *parts):
        getter = getattr(self.context, "_existing_save_dirs", None)
        if callable(getter):
            roots = list(getter(*parts))
        else:
            path = self._existing_path(*parts)
            roots = [path] if path.is_dir() else []
        primary = self.context._save_path(*parts)
        return sorted(roots, key=lambda p: p != primary)

    @staticmethod
    def _json(path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _vibes(self):
        models = {}
        live_paths = set()
        for root in self._roots("vibe_transfer"):
            for folder in sorted(p for p in root.iterdir() if p.is_dir()):
                items = models.setdefault(folder.name, {})
                for path in sorted(folder.glob("*.json")):
                    key = str(path)
                    live_paths.add(key)
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    signature = (stat.st_mtime_ns, stat.st_size)
                    cached = self._cache.get(key)
                    if cached and cached[0] == signature:
                        summary = cached[1]
                    else:
                        raw = self._json(path)
                        encodings = clean_encodings(raw.get("encodings"))
                        summary = None
                        if encodings and not raw.get("volatile") and raw.get("storage_type") != "metadata_vibe":
                            summary = {"file_hash": path.stem, "file_name": str(raw.get("file_name") or path.stem + ".png"),
                                "encoding_keys": sorted(set(map(float, encodings))),
                                "no_source": bool(raw.get("no_source")), "is_no_image": bool(raw.get("is_no_image")),
                                "mtime": stat.st_mtime}
                        self._cache[key] = (signature, summary)
                    if summary and path.stem not in items:
                        item = dict(summary)
                        item["has_image"] = (not item.pop("is_no_image") and not item["no_source"]
                                             and (folder / "images" / (path.stem + ".png")).is_file())
                        items[path.stem] = item
        self._cache = {k: v for k, v in self._cache.items() if k in live_paths}
        return {model: items for model, items in models.items() if items}

    def _characters(self):
        items = {}
        for folder in self._roots("character_reference", "images"):
            for path in sorted(folder.glob("*.png")):
                if path.stem in items:
                    continue
                meta = self._json(folder.parent / "metadata" / (path.stem + ".json"))
                items[path.stem] = {"file_hash": path.stem, "file_name": path.name, "mtime": path.stat().st_mtime,
                                    "character_name": str(meta.get("character_name") or ""), "has_image": True}
        return items

    def _listing(self, data, kind, model="", filter="all", category_id="", q="", sort="recent", offset=0, limit=60, _file_hash=""):
        self._kind(kind)
        if filter not in {"all", "favorite", "uncategorized", "category"} or sort not in {"recent", "name", "used"}:
            raise LibraryError("Invalid filter or sort")
        try:
            offset, limit = max(0, int(offset)), max(1, min(200, int(limit)))
        except (ValueError, TypeError):
            raise LibraryError("Invalid pagination") from None
        current = self.context._current_model_key()
        model = safe_component(model or current) if kind == "vibe" else ""
        models = self._vibes() if kind == "vibe" else {}
        storage = models.get(model, {}) if kind == "vibe" else self._characters()
        categories = sorted(data[kind]["categories"], key=lambda g: g.get("order", 0))
        counts = {"all": len(storage), "favorite": 0, "uncategorized": 0, "categories": {g["id"]: 0 for g in categories}}
        items = []
        service = getattr(self.context, "_service_cache", {}).get("vibe_transfer")
        session_new = getattr(service, "_session_imported", set())
        for file_hash, stored in storage.items():
            meta = data[kind]["items"].get(file_hash, {})
            category = meta.get("category", "")
            category = category if category in counts["categories"] else ""
            name = str(meta.get("name") or "")
            item = {"file_hash": file_hash, "file_name": stored["file_name"], "name": name,
                    "display_name": name or stored.get("character_name") or Path(stored["file_name"]).stem,
                    "favorite": bool(meta.get("favorite")), "category": category,
                    "created_at": finite(meta.get("created_at"), stored["mtime"]),
                    "last_used_at": finite(meta.get("last_used_at"), 0.0), "has_image": stored["has_image"]}
            if kind == "vibe":
                item.update(encoding_keys=stored["encoding_keys"], last_ie=finite(meta.get("last_ie")),
                            last_rs=finite(meta.get("last_rs")), no_source=stored["no_source"],
                            session_new=f"{model}|{file_hash}" in session_new)
                url = "/api/module-storage/vibe/thumb?" + urlencode({"model": model, "file_hash": file_hash})
            else:
                item["settings"] = reference_settings(meta.get("settings"))
                url = "/api/module-storage/character-reference/thumb?" + urlencode({"file_hash": file_hash})
            item["thumbnail_url"] = url if item["has_image"] else ""
            counts["favorite"] += item["favorite"]
            counts["uncategorized"] += not category
            if category:
                counts["categories"][category] += 1
            if _file_hash and file_hash != _file_hash:
                continue
            if filter == "favorite" and not item["favorite"] or filter == "uncategorized" and category:
                continue
            if filter == "category" and category_id != category:
                continue
            if q and not any(str(q).casefold() in item[k].casefold() for k in ("name", "display_name", "file_name", "file_hash")):
                continue
            items.append(item)
        items.sort(key=lambda i: (-i["created_at"], i["file_hash"]))
        if sort == "name":
            items.sort(key=lambda i: i["display_name"].casefold())
        elif sort == "used":
            items.sort(key=lambda i: -i["last_used_at"])
        try:
            spec = resolve_nai_model_for_context(self.context, model or current)
            supported = bool(spec.supports_vibe if kind == "vibe" else spec.supports_character_reference)
        except (ValueError, KeyError):
            supported = False
        return {"kind": kind, "model": model, "current_model": current,
                "models": [{"key": k, "count": len(v)} for k, v in sorted(models.items())],
                "model_supported": supported, "total": len(items), "offset": offset, "limit": limit,
                "counts": counts, "categories": [{"id": g["id"], "name": g["name"], "order": g.get("order", 0),
                    "count": counts["categories"][g["id"]]} for g in categories], "items": items[offset:offset + limit]}

    def list_items(self, kind, **query):
        with self._lock:
            return self._listing(self._read(), kind, **query)

    def _item(self, data, kind, file_hash, model=""):
        # Exact hash lookup must not be bounded by the public page size.
        listing = self._listing(data, kind, model=model, _file_hash=file_hash)
        item = next((i for i in listing["items"] if i["file_hash"] == file_hash), None)
        if item is None:
            raise LibraryError("Storage item not found", 404)
        return item

    def edit_item(self, kind, file_hash, model="", **updates):
        self._kind(kind)
        file_hash = safe_component(file_hash)
        if "name" in updates:
            if not isinstance(updates["name"], str) or len(updates["name"].strip()) > 80:
                raise LibraryError("name must be at most 80 characters")
            updates["name"] = updates["name"].strip()
        if "favorite" in updates and not isinstance(updates["favorite"], bool):
            raise LibraryError("favorite must be boolean")
        with self._lock:
            data = self._read()
            old = self._item(data, kind, file_hash, model)
            meta = data[kind]["items"].setdefault(file_hash, {"created_at": old["created_at"], "category": ""})
            meta.update({k: updates[k] for k in ("name", "favorite") if k in updates})
            self._write(data)
            return self._item(data, kind, file_hash, model)

    def change_category(self, kind, op, category_id="", name="", order=None, model=""):
        self._kind(kind)
        if op not in ("create", "rename", "delete", "reorder"):
            raise LibraryError("Invalid category operation")
        with self._lock:
            data = self._read()
            categories = data[kind]["categories"]
            category = next((g for g in categories if g["id"] == category_id), None) if op != "create" else None
            if op in {"rename", "delete"} and category is None:
                raise LibraryError("Category not found", 404)
            if op in {"create", "rename"}:
                if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40:
                    raise LibraryError("Category name must be 1 to 40 characters")
                name = name.strip()
                if any(g["name"] == name and g is not category for g in categories):
                    raise LibraryError("Category name already exists", 409)
                if op == "create":
                    category = {"id": "c_" + uuid.uuid4().hex[:12], "order": len(categories), "name": name}
                    categories.append(category)
                else:
                    category["name"] = name
            elif op == "delete":
                categories.remove(category)
                for item in data[kind]["items"].values():
                    if item.get("category") == category_id:
                        item["category"] = ""
            else:
                if (not isinstance(order, list) or not all(isinstance(g, str) for g in order)
                        or len(order) != len(categories) or set(order) != {g["id"] for g in categories}):
                    raise LibraryError("order must contain each category exactly once")
                categories.sort(key=lambda g: order.index(g["id"]))
            for n, g in enumerate(categories):
                g["order"] = n
            self._write(data)
            result = self._listing(data, kind, model=model)
            return {k: result[k] for k in ("categories", "counts")}

    def move_items(self, kind, file_hashes, category_id="", model=""):
        self._kind(kind)
        if not isinstance(file_hashes, list) or not isinstance(category_id, str):
            raise LibraryError("Invalid category move")
        hashes = list(dict.fromkeys(safe_component(h) for h in file_hashes))
        with self._lock:
            data = self._read()
            if category_id and not any(c["id"] == category_id for c in data[kind]["categories"]):
                raise LibraryError("Category not found", 404)
            items = [self._item(data, kind, h, model) for h in hashes]
            for item in items:
                meta = data[kind]["items"].setdefault(item["file_hash"], {"created_at": item["created_at"]})
                meta["category"] = category_id
            self._write(data)
            return {"items": [self._item(data, kind, h, model) for h in hashes],
                    "counts": self._listing(data, kind, model=model)["counts"]}

    def display_names(self, kind, file_hashes):
        """Batch frame labels from the shared index, cached until a write or external file change."""
        self._kind(kind)
        with self._lock:
            if (self._names_cache is None
                    or self._index_signature != self._signature(self._existing_path("ref_vibe_library.json"))):
                data = self._read()
                self._names_cache = {
                    k: {h: str(meta.get("name") or "") for h, meta in data[k]["items"].items()}
                    for k in KINDS
                }
            names = self._names_cache[kind]
            return {h: names.get(h, "") for h in file_hashes}

    def metadata(self, kind, file_hash):
        self._kind(kind)
        with self._lock:
            return copy.deepcopy(self._read()[kind]["items"].get(file_hash, {}))

    def record_stored_vibes(self, frames):
        candidates = [f for f in frames if f.get("file_hash") and f.get("vibe_encodings")
                      and f.get("storage_type") != "metadata_vibe"]
        if not candidates:
            return
        with self._lock:
            data = self._read()
            changed = False
            for frame in candidates:
                try:
                    file_hash = safe_component(frame["file_hash"])
                    model = safe_component(self.context._current_model_key())
                    source = safe_component(frame.get("source_model") or model)
                except LibraryError:
                    continue
                for key in dict.fromkeys((model, source)):
                    path = self._existing_path("vibe_transfer", key, file_hash + ".json")
                    if path.is_file():
                        meta = data["vibe"]["items"].setdefault(file_hash, {"category": ""})
                        if "created_at" not in meta:
                            meta["created_at"] = path.stat().st_mtime
                            changed = True
            if changed:
                self._write(data)

    def record(self, kind, file_hash, *, used=False, created_at=None, settings=None, ie=None, rs=None):
        self._kind(kind)
        file_hash = safe_component(file_hash)
        with self._lock:
            data = self._read()
            item = data[kind]["items"].setdefault(file_hash, {"category": ""})
            before = dict(item)
            if created_at is not None:
                item.setdefault("created_at", finite(created_at, time.time()))
            if used:
                item["last_used_at"] = time.time()
            if settings is not None:
                item["settings"] = reference_settings(settings)
            if ie is not None:
                item["last_ie"] = finite(ie)
            if rs is not None:
                item["last_rs"] = finite(rs)
            if before != item:
                self._write(data)

    def cleanup_vibe(self, model, file_hash):
        with self._lock:
            data = self._read()
            remaining = {folder.name for root in self._roots("vibe_transfer")
                         for folder in root.iterdir() if folder.is_dir() and (folder / (file_hash + ".json")).exists()}
            if not remaining:
                data["vibe"]["items"].pop(file_hash, None)
            self._write(data)

    def delete_character(self, file_hash):
        file_hash = safe_component(file_hash)
        with self._lock:
            data = self._read()
            targets = []
            for root in self._roots("character_reference"):
                for sub, suffix in (("images", ".png"), ("metadata", ".json")):
                    target = root / sub / (file_hash + suffix)
                    if root.resolve() not in target.resolve().parents:
                        raise LibraryError("Storage path escapes its root")
                    targets.append(target)
            for target in targets:
                target.unlink(missing_ok=True)
            data["character_reference"]["items"].pop(file_hash, None)
            self._write(data)
            return {"deleted": file_hash}
