"""Shared, atomic metadata index for stored Vibe and Character References.

Storage files remain authoritative for availability; the index owns annotations
and group membership. All public operations serialize through one instance lock.
"""
from __future__ import annotations

import copy
import hashlib
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
        self._names_cache: dict[str, dict[str, str]] | None = None
        # Per-path compact summaries only: never keep base64 encoding bodies.
        self._cache: dict[str, tuple[tuple[int, int], dict | None]] = {}

    @staticmethod
    def _empty():
        return {"version": 1, "migrated_clusters": [],
                **{kind: {"items": {}, "groups": []} for kind in KINDS}}

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

    def _write(self, data):
        self._atomic_write(self.context._save_path("ref_vibe_library.json"), data)
        self._names_cache = None

    def _existing_path(self, *parts):
        getter = getattr(self.context, "_existing_save_path", self.context._save_path)
        return getter(*parts)

    def _read(self):
        path = self._existing_path("ref_vibe_library.json")
        data = self._empty()
        if path.exists():
            try:
                def reject_constant(value):
                    raise ValueError("Non-finite JSON value: " + value)

                data = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
                if not isinstance(data, dict) or any(
                    not isinstance(data.get(k), dict)
                    or not isinstance(data[k].get("items"), dict)
                    or not isinstance(data[k].get("groups"), list) for k in KINDS
                ):
                    raise ValueError("Invalid library structure")
                if not isinstance(data.get("migrated_clusters", []), list):
                    raise ValueError("Invalid migration record")
                data.setdefault("migrated_clusters", [])
            except (ValueError, UnicodeError):
                os.replace(path, path.with_name(path.name + f".broken-{time.time():.9f}"))
                data = self._empty()
                self._write(data)
        if self._migrate(data):
            self._write(data)
        return data

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

    def _migrate(self, data):
        changed = False
        indexes = {}
        for root in self._roots("vibe_transfer_clusters"):
            for path in sorted(root.glob("*.json")):
                # Cluster IDs are normally the file stem. Already migrated
                # clusters must not reparse their large encoding bodies.
                if path.stem in data["migrated_clusters"]:
                    continue
                cluster = self._json(path)
                if not cluster or not isinstance(cluster.get("frames"), list):
                    continue
                cluster_id = str(cluster.get("id") or path.stem)
                if cluster_id in data["migrated_clusters"]:
                    continue
                try:
                    model = safe_component(cluster.get("model"))
                except LibraryError:
                    continue
                if model not in indexes:
                    index = indexes[model] = {}
                    for folder in self._roots("vibe_transfer", model):
                        for stored in sorted(folder.glob("*.json")):
                            raw = self._json(stored)
                            if raw.get("volatile") or raw.get("storage_type") == "metadata_vibe":
                                continue
                            for key, encoding in clean_encodings(raw.get("encodings")).items():
                                index.setdefault(encoding, (stored.stem, float(key)))
                index = indexes[model]
                groups = data["vibe"]["groups"]
                name = str(cluster.get("name") or path.stem)
                group = next((g for g in groups if g["name"] == name), None)
                if group is None:
                    group = {"id": "g_" + uuid.uuid4().hex[:12], "name": name, "order": len(groups),
                             "members": [], "normalize": bool(cluster.get("normalize_strength")),
                             "source_cluster": cluster_id}
                    groups.append(group)
                for n, frame in enumerate(cluster["frames"], 1):
                    if not isinstance(frame, dict):
                        continue
                    encodings = clean_encodings(frame.get("encodings"))
                    if not encodings:
                        continue
                    match = next((index[e] for e in encodings.values() if e in index), None)
                    if match:
                        file_hash = match[0]
                    else:
                        file_hash = hashlib.sha256(json.dumps(encodings, sort_keys=True).encode("utf-8")).hexdigest()[:16]
                        target = self.context._save_path("vibe_transfer", model, file_hash + ".json")
                        if not target.exists():
                            self._atomic_write(target, {"file_hash": file_hash,
                                "file_name": f"cluster_{name}_{n}", "encodings": encodings,
                                "no_source": True, "is_no_image": True})
                        for key, encoding in encodings.items():
                            index.setdefault(encoding, (file_hash, float(key)))
                    member = {"file_hash": file_hash, "model": model,
                              "ie": finite(frame.get("information_extracted"), max(map(float, encodings))),
                              "rs": finite(frame.get("reference_strength"), 0.6),
                              "enabled": bool(frame.get("is_enabled", True))}
                    group.setdefault("members", []).append(member)
                    item = data["vibe"]["items"].setdefault(file_hash, {})
                    if group["id"] not in item.setdefault("groups", []):
                        item["groups"].append(group["id"])
                data["migrated_clusters"].append(cluster_id)
                changed = True
        return changed

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

    def _listing(self, data, kind, model="", filter="all", group_id="", q="", sort="recent", offset=0, limit=60, _file_hash=""):
        self._kind(kind)
        if filter not in {"all", "favorite", "ungrouped", "group"} or sort not in {"recent", "name", "used"}:
            raise LibraryError("Invalid filter or sort")
        try:
            offset, limit = max(0, int(offset)), max(1, min(200, int(limit)))
        except (ValueError, TypeError):
            raise LibraryError("Invalid pagination") from None
        current = self.context._current_model_key()
        model = safe_component(model or current) if kind == "vibe" else ""
        models = self._vibes() if kind == "vibe" else {}
        storage = models.get(model, {}) if kind == "vibe" else self._characters()
        groups = sorted(data[kind]["groups"], key=lambda g: g.get("order", 0))
        counts = {"all": len(storage), "favorite": 0, "ungrouped": 0, "groups": {g["id"]: 0 for g in groups}}
        items = []
        service = getattr(self.context, "_service_cache", {}).get("vibe_transfer")
        session_new = getattr(service, "_session_imported", set())
        for file_hash, stored in storage.items():
            meta = data[kind]["items"].get(file_hash, {})
            memberships = [g for g in meta.get("groups", []) if g in counts["groups"]]
            name = str(meta.get("name") or "")
            item = {"file_hash": file_hash, "file_name": stored["file_name"], "name": name,
                    "display_name": name or stored.get("character_name") or Path(stored["file_name"]).stem,
                    "favorite": bool(meta.get("favorite")), "groups": memberships,
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
            counts["ungrouped"] += not memberships
            for gid in memberships:
                counts["groups"][gid] += 1
            if _file_hash and file_hash != _file_hash:
                continue
            if filter == "favorite" and not item["favorite"] or filter == "ungrouped" and memberships:
                continue
            if filter == "group" and group_id not in memberships:
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
                "counts": counts, "groups": [{"id": g["id"], "name": g["name"], "order": g.get("order", 0),
                    "count": counts["groups"][g["id"]]} for g in groups], "items": items[offset:offset + limit]}

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
            meta = data[kind]["items"].setdefault(file_hash, {"created_at": old["created_at"]})
            meta.update({k: updates[k] for k in ("name", "favorite") if k in updates})
            self._write(data)
            return self._item(data, kind, file_hash, model)

    def change_group(self, kind, op, group_id="", name="", order=None, model=""):
        self._kind(kind)
        if op not in ("create", "rename", "delete", "reorder"):
            raise LibraryError("Invalid group operation")
        with self._lock:
            data = self._read()
            groups = data[kind]["groups"]
            group = next((g for g in groups if g["id"] == group_id), None) if op != "create" else None
            if op in {"rename", "delete"} and group is None:
                raise LibraryError("Group not found", 404)
            if op in {"create", "rename"}:
                if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40:
                    raise LibraryError("Group name must be 1 to 40 characters")
                name = name.strip()
                if any(g["name"] == name and g is not group for g in groups):
                    raise LibraryError("Group name already exists", 409)
                if op == "create":
                    group = {"id": "g_" + uuid.uuid4().hex[:12], "order": len(groups), "name": name}
                    if kind == "vibe":
                        group.update(members=[], normalize=False)
                    groups.append(group)
                else:
                    group["name"] = name
            elif op == "delete":
                groups.remove(group)
                for item in data[kind]["items"].values():
                    item["groups"] = [g for g in item.get("groups", []) if g != group_id]
            else:
                if (not isinstance(order, list) or not all(isinstance(g, str) for g in order)
                        or len(order) != len(groups) or set(order) != {g["id"] for g in groups}):
                    raise LibraryError("order must contain each group exactly once")
                groups.sort(key=lambda g: order.index(g["id"]))
            for n, g in enumerate(groups):
                g["order"] = n
            self._write(data)
            result = self._listing(data, kind, model=model)
            return {k: result[k] for k in ("groups", "counts")}

    def change_members(self, kind, group_id, op, file_hashes, model=""):
        self._kind(kind)
        if op not in ("add", "remove") or not isinstance(file_hashes, list):
            raise LibraryError("Invalid membership operation")
        if kind == "vibe" and op == "add":
            model = safe_component(model)
        hashes = list(dict.fromkeys(safe_component(h) for h in file_hashes))
        with self._lock:
            data = self._read()
            group = next((g for g in data[kind]["groups"] if g["id"] == group_id), None)
            if group is None:
                raise LibraryError("Group not found", 404)
            items = [self._item(data, kind, h, model) for h in hashes]
            for item in items:
                h = item["file_hash"]
                meta = data[kind]["items"].setdefault(h, {"created_at": item["created_at"]})
                memberships = meta.setdefault("groups", [])
                if op == "add":
                    if group_id not in memberships:
                        memberships.append(group_id)
                    if kind == "vibe" and not any(m["file_hash"] == h and m["model"] == model for m in group["members"]):
                        group["members"].append({"file_hash": h, "model": model,
                            "ie": item["last_ie"] if item["last_ie"] is not None else max(item["encoding_keys"]),
                            "rs": item["last_rs"] if item["last_rs"] is not None else 0.6, "enabled": True})
                else:
                    meta["groups"] = [g for g in memberships if g != group_id]
                    if kind == "vibe":
                        group["members"] = [m for m in group["members"] if m["file_hash"] != h]
            self._write(data)
            return {"items": [self._item(data, kind, h, model) for h in hashes],
                    "counts": self._listing(data, kind, model=model)["counts"]}

    def display_names(self, kind, file_hashes):
        """Batch frame labels from the shared index, cached until a successful write."""
        self._kind(kind)
        with self._lock:
            if self._names_cache is None:
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
                        meta = data["vibe"]["items"].setdefault(file_hash, {})
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
            item = data[kind]["items"].setdefault(file_hash, {})
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

    def group(self, group_id):
        with self._lock:
            data = self._read()
            group = next((g for g in data["vibe"]["groups"] if g["id"] == group_id), None)
            if group is None:
                raise LibraryError("Group not found", 404)
            result = copy.deepcopy(group)
            result["members"] = [m for m in result.get("members", [])
                if group_id in data["vibe"]["items"].get(m["file_hash"], {}).get("groups", [])]
            return result

    def cleanup_vibe(self, model, file_hash):
        with self._lock:
            data = self._read()
            remaining = {folder.name for root in self._roots("vibe_transfer")
                         for folder in root.iterdir() if folder.is_dir() and (folder / (file_hash + ".json")).exists()}
            for group in data["vibe"]["groups"]:
                group["members"] = [m for m in group.get("members", []) if m["file_hash"] != file_hash
                    or (remaining and (m["model"] != model or model in remaining))]
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
