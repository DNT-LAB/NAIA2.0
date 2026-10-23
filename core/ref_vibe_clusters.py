"""File-backed Vibe bundles, independent of library categories."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import threading
import time
from urllib.parse import urlencode
import uuid

from core.ref_vibe_library import LibraryError, clean_encodings, finite, get_ref_vibe_library, safe_component
from core.vibe_cluster_resolver import is_valid_vibe_cluster_name, list_vibe_clusters


def get_ref_vibe_clusters(context):
    cached = context.__dict__.get("_ref_vibe_clusters_instance")
    if cached is None:
        cached = context.__dict__.setdefault("_ref_vibe_clusters_instance", RefVibeClusters(context))
    return cached


class RefVibeClusters:
    def __init__(self, context):
        self.context = context
        self.library = get_ref_vibe_library(context)
        self._lock = threading.Lock()
        # Model -> (folder/file signatures, encoding digest -> hash, hash -> name).
        # Never retain base64 encoding bodies here.
        self._encoding_cache = {}

    def _records(self):
        records = []
        seen = set()
        for root in self.library._roots("vibe_transfer_clusters"):
            for data in list_vibe_clusters(root):
                cluster_id = data["_cluster_id"]
                if cluster_id not in seen:
                    records.append(data)
                    seen.add(cluster_id)
        return records

    def _find(self, identifier, *, by_name=False):
        identifier = safe_component(identifier)
        # Filenames and content IDs both precede the legacy name lookup.
        for root in self.library._roots("vibe_transfer_clusters"):
            path = root / (identifier + ".json")
            if path.is_file():
                data = self.library._json(path)
                if isinstance(data.get("frames"), list):
                    return path, data
        for root in self.library._roots("vibe_transfer_clusters"):
            for path in sorted(root.glob("*.json")):
                data = self.library._json(path)
                if str(data.get("id") or path.stem) == identifier and isinstance(data.get("frames"), list):
                    return path, data
        if by_name and is_valid_vibe_cluster_name(identifier):
            matches = [d for d in self._records() if d["_cluster_name"].casefold() == identifier.casefold()]
            if len(matches) > 1:
                raise LibraryError("Cluster name is duplicated", 409)
            if matches:
                return self._find(matches[0]["_cluster_id"])
        raise LibraryError("Cluster not found", 404)

    def _storage_index(self, model):
        model = safe_component(model)
        folders = self.library._roots("vibe_transfer", model)
        paths = [p for folder in folders for p in sorted(folder.glob("*.json"))]
        signature = tuple(self.library._signature(p) for p in [*folders, *paths])
        cached = self._encoding_cache.get(model)
        if cached and cached[0] == signature:
            return cached[1], cached[2]
        encodings, names = {}, {}
        for path in paths:
            if path.stem in names:
                continue
            data = self.library._json(path)
            values = clean_encodings(data.get("encodings"))
            if not values or data.get("volatile") or data.get("storage_type") == "metadata_vibe":
                continue
            names[path.stem] = str(data.get("file_name") or "")
            for value in values.values():
                encodings.setdefault(hashlib.sha256(value.encode("utf-8")).digest(), path.stem)
        self._encoding_cache[model] = (signature, encodings, names)
        return encodings, names

    def _member_source(self, frame, model, index):
        encodings, names = index
        file_hash = str(frame.get("file_hash") or "")
        if file_hash:
            try:
                file_hash = safe_component(file_hash)
            except LibraryError:
                file_hash = ""
        if not file_hash:
            for value in clean_encodings(frame.get("encodings")).values():
                file_hash = encodings.get(hashlib.sha256(value.encode("utf-8")).digest(), "")
                if file_hash:
                    break
        image_path = self.library._existing_path("vibe_transfer", model, "images", file_hash + ".png") if file_hash else None
        if image_path is not None and not image_path.is_file():
            image_path = None
        return file_hash, names.get(file_hash, ""), image_path

    def _summary(self, data):
        model = safe_component(data.get("model"))
        index = self._storage_index(model)
        members = []
        for n, frame in enumerate(data.get("frames", [])):
            if not isinstance(frame, dict):
                continue
            file_hash, file_name, image_path = self._member_source(frame, model, index)
            members.append({"index": n, "file_hash": file_hash,
                "display_name": (Path(file_name).stem if file_name else "") or str(frame.get("file_name") or f"#{n + 1}"),
                "ie": finite(frame.get("information_extracted"), 1.0),
                "encoding_keys": sorted(set(map(float, clean_encodings(frame.get("encodings"))))),
                "rs": finite(frame.get("reference_strength"), 0.6),
                "enabled": bool(frame.get("is_enabled", True)), "has_image": image_path is not None,
                "thumbnail_url": ("/api/module-storage/vibe/thumb?" + urlencode({"model": model, "file_hash": file_hash})) if image_path else ""})
        names = self.library.display_names("vibe", [m["file_hash"] for m in members])
        for member in members:
            member["display_name"] = names.get(member["file_hash"]) or member["display_name"]
        return {"id": str(data.get("id") or data.get("_cluster_id") or ""),
            "name": str(data.get("name") or ""), "description": str(data.get("description") or ""),
            "model": model, "normalize": bool(data.get("normalize_strength", False)),
            "created_at": data.get("created_at", 0), "updated_at": data.get("updated_at", 0),
            "frame_count": len(members), "enabled_count": sum(m["enabled"] for m in members), "members": members}

    def list_clusters(self):
        with self._lock:
            return {"clusters": [self._summary(d) for d in sorted(self._records(), key=lambda d: d["_cluster_name"].casefold())]}

    def load(self, identifier):
        with self._lock:
            _, data = self._find(identifier, by_name=True)
            model = safe_component(data.get("model"))
            index = self._storage_index(model)
            frames = []
            for frame in data["frames"]:
                if not isinstance(frame, dict):
                    continue
                frame = copy.deepcopy(frame)
                file_hash, stored_name, image_path = self._member_source(frame, model, index)
                # 옛 클러스터 프레임엔 file_hash · file_name 이 없다 - 맞춘 보관 항목의 이름을 실어 활성 줄에 'cluster_vibe' 가 안 보이게.
                if not frame.get("file_name") and stored_name:
                    frame["file_name"] = stored_name
                # Active frames need a stable identity for snapshot validation;
                # this does not create a library item or change the REST summary.
                frame["_fallback_hash"] = hashlib.sha256(json.dumps(frame, sort_keys=True).encode("utf-8")).hexdigest()[:16]
                frame["file_hash"] = file_hash
                frame["_image_path"] = image_path
                frames.append(frame)
            return {**data, "frames": frames}

    def _check_name(self, name, current_id=""):
        if not isinstance(name, str) or not is_valid_vibe_cluster_name(name):
            raise LibraryError("Cluster name must use letters, numbers, and Korean only")
        if any(d["_cluster_id"] != current_id and d["_cluster_name"].casefold() == name.casefold() for d in self._records()):
            raise LibraryError("Cluster name already exists", 409)
        return name

    @staticmethod
    def _number(body, key, default):
        if key not in body:
            return default
        value = finite(body[key])
        if value is None or isinstance(body[key], bool):
            raise LibraryError(key + " must be finite")
        return value

    @staticmethod
    def _nearest(encodings, ie):
        keys = sorted(map(float, clean_encodings(encodings)))
        if not keys:
            raise LibraryError("Member has no encodings")
        return min(keys, key=lambda key: abs(key - ie))

    def change_cluster(self, body):
        op = body.get("op")
        if op not in ("create", "add", "remove", "update", "rename", "delete"):
            raise LibraryError("Invalid cluster operation")
        with self._lock:
            if op == "create":
                name = self._check_name(body.get("name"))
                getter = getattr(self.context, "_vibe_transfer_service", None)
                service = getter() if callable(getter) else getattr(self.context, "_service_cache", {}).get("vibe_transfer")
                if service is not None:
                    service._ensure_loaded()
                model = safe_component(self.context._current_model_key())
                frames = []
                for frame in list(self.context.vibe_transfer_frames):
                    encodings = clean_encodings(frame.get("vibe_encodings"))
                    if not encodings:
                        continue
                    frames.append({"file_hash": str(frame.get("file_hash") or ""),
                        "file_name": str(frame.get("file_name") or ""), "encodings": encodings,
                        "reference_strength": finite(frame.get("reference_strength"), 0.6),
                        "information_extracted": finite(frame.get("information_extracted"), max(map(float, encodings))),
                        "is_enabled": bool(frame.get("is_enabled", True)),
                        "target_model": str(frame.get("source_model") or model)})
                if not frames:
                    raise LibraryError("No encoded Vibe frames")
                cluster_id = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
                path = self.context._save_path("vibe_transfer_clusters", cluster_id + ".json")
                data = {"id": cluster_id, "name": name, "description": str(body.get("description") or ""),
                    "created_at": time.time(), "model": model,
                    "normalize_strength": bool(self.context.vibe_transfer_normalize), "frames": frames}
            else:
                path, data = self._find(body.get("id"))
                data.setdefault("id", path.stem)
                cluster_id = data["id"]
                if op == "delete":
                    path.unlink()
                    return {"deleted": cluster_id}
                if op == "rename":
                    data["name"] = self._check_name(body.get("name"), cluster_id)
                elif op == "add":
                    model = safe_component(body.get("model"))
                    if model != data.get("model"):
                        raise LibraryError("Model must match the cluster model")
                    file_hash = safe_component(body.get("file_hash"))
                    index = self._storage_index(model)
                    if any(self._member_source(f, model, index)[0] == file_hash for f in data["frames"] if isinstance(f, dict)):
                        return self._summary(data)
                    source = self.library._existing_path("vibe_transfer", model, file_hash + ".json")
                    stored = self.library._json(source)
                    encodings = clean_encodings(stored.get("encodings"))
                    if not encodings or stored.get("volatile") or stored.get("storage_type") == "metadata_vibe":
                        raise LibraryError("Stored Vibe not found", 404)
                    meta = self.library.metadata("vibe", file_hash)
                    ie = self._nearest(encodings, self._number(body, "ie", finite(meta.get("last_ie"), max(map(float, encodings)))))
                    rs = self._number(body, "rs", finite(meta.get("last_rs"), finite(stored.get("reference_strength"), 0.6)))
                    data["frames"].append({"file_hash": file_hash, "file_name": str(stored.get("file_name") or ""),
                        "encodings": encodings, "information_extracted": ie, "reference_strength": rs,
                        "is_enabled": True, "target_model": model})
                elif op == "update" and "description" in body and "index" not in body:
                    if not isinstance(body["description"], str) or len(body["description"]) > 200:
                        raise LibraryError("description must be at most 200 characters")
                    data["description"] = body["description"].strip()
                else:
                    index = body.get("index")
                    if type(index) is not int or not 0 <= index < len(data["frames"]):
                        raise LibraryError("Invalid member index")
                    if op == "remove":
                        data["frames"].pop(index)
                    else:
                        frame = data["frames"][index]
                        if "ie" in body:
                            frame["information_extracted"] = self._nearest(frame.get("encodings"), self._number(body, "ie", 1.0))
                        if "rs" in body:
                            frame["reference_strength"] = self._number(body, "rs", 0.6)
                        if "enabled" in body:
                            if not isinstance(body["enabled"], bool):
                                raise LibraryError("enabled must be boolean")
                            frame["is_enabled"] = body["enabled"]
            data["updated_at"] = time.time()
            self.library._atomic_write(path, data)
            return self._summary(data)
