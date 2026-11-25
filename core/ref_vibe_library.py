"""Shared, atomic metadata index for stored Vibe and Character References.

Storage files remain authoritative for availability; the index owns annotations
and single category membership. All public operations serialize through one instance lock.
"""
from __future__ import annotations

from core.nai_character_reference_spec import REFERENCE_TYPES, STRENGTH_STORE_MAX

import copy
import json
import math
import os
import shutil
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


# ── Character Reference 보관함의 상위 분류(사용자 지시 2026-11-25) ──
#  캐릭터는 한 번 쓰고 마는 일이 많고, 의상 · 스타일은 거듭 쓴다 - 따로 모아 폴더(카테고리)로 묶고
#  프롬프트의 `ref:폴더:이름` · `ref:__폴더__` 로 부른다(core/ref_prompt_resolver.py).
#  - 분류는 그림의 **자기 필드**(`group`)다. 활성 칸 드롭다운의 종류(settings.reference_type)와 따로 -
#    활성 칸에서 종류를 바꿔도 보관 그림이 다른 분류로 옮겨지지 않는다(활성 칸과 보관함은 따로).
#  - 폴더(카테고리)도 분류를 가진다. 이름은 **세 분류를 통틀어** 겹치지 않는다(`ref:이름` 이 어느 쪽인지 알아야 한다).
CR_GROUPS = ("character", "outfit", "style")
GROUP_DEFAULT_TYPE = {"outfit": "costume", "style": "style"}
CALL_NAME_FORBIDDEN = (":", ",", "__")


def item_group(meta: Any) -> str:
    """보관 그림의 분류. 아직 분류가 적히지 않은 그림은 저장된 종류에서 한 번 미룬다(Outfit -> 의상 · Style -> 스타일)."""
    meta = meta if isinstance(meta, dict) else {}
    group = meta.get("group")
    if group in CR_GROUPS:
        return group
    ref_type = (meta.get("settings") or {}).get("reference_type") if isinstance(meta.get("settings"), dict) else None
    return "outfit" if ref_type == "costume" else ("style" if ref_type == "style" else "character")


def category_group(category: Any) -> str:
    group = category.get("group") if isinstance(category, dict) else None
    return group if group in CR_GROUPS else "character"


def regroup_item(meta: dict, group: str, categories: list) -> None:
    """보관 그림을 다른 분류로 - 다른 분류의 폴더엔 남지 않고(미분류로), [적용] 할 때의 종류도 그 분류의 것으로
    (의상 = Outfit · 스타일 = Style · 캐릭터 = 캐릭터 종류 그대로, 의상/스타일에서 오면 기본 Char&Style)."""
    if group == item_group(meta) and meta.get("group") == group:
        return
    meta["group"] = group
    category = next((c for c in categories if c["id"] == meta.get("category")), None)
    if category is not None and category_group(category) != group:
        meta["category"] = ""
    settings = reference_settings(meta.get("settings"))
    if group in GROUP_DEFAULT_TYPE:
        settings["reference_type"] = GROUP_DEFAULT_TYPE[group]
    elif settings["reference_type"] in ("costume", "style"):
        settings["reference_type"] = DEFAULT_SETTINGS["reference_type"]
    meta["settings"] = settings


# 호출 프롬프트(사용자 지시 2026-11-25) - 의상 · 스타일 그림을 `ref:` 로 부르면 부른 자리에 넣는 글.
#  캐릭터 그림은 따로 두지 않는다 - 이미 있는 캐릭터 프롬프트(character_prompt · character_uc)가 그 슬롯을 대치한다.
#  켜기(`call_prompt_on`)는 두 경우 모두에 걸린다. 적지 않았으면 켜짐(글이 있으면 켜짐 · 사용자 결정).
CALL_PROMPT_MAX = 2000


def clean_call_prompt(value: Any, label: str) -> str:
    """한 줄 글로 - 줄바꿈은 쉼표로. `ref:` 는 못 쓴다(부른 글이 또 부르지 않게)."""
    if not isinstance(value, str):
        raise LibraryError(f"{label} must be text")
    pieces = [piece.strip() for line in value.splitlines() for piece in line.split(",")]
    text = ", ".join(piece for piece in pieces if piece)
    if len(text) > CALL_PROMPT_MAX:
        raise LibraryError(f"{label} 는 {CALL_PROMPT_MAX}자까지입니다")
    if any(piece.lower().startswith("ref:") for piece in pieces):
        raise LibraryError(f"{label} 에는 ref: 를 쓸 수 없습니다")
    return text


def callable_name_problem(name: str) -> str:
    """`ref:` 로 부를 수 있는 이름인가 - 안 되면 까닭(빈 글 = 된다)."""
    bad = [mark for mark in CALL_NAME_FORBIDDEN if mark in name]
    return f"이름에 {' '.join(repr(m) for m in bad)} 를 쓸 수 없습니다(ref: 로 부를 때 갈라집니다)" if bad else ""


def reference_settings(value: Any) -> dict:
    value = value if isinstance(value, dict) else {}
    ref_type = value.get("reference_type")
    return {
        "reference_type": ref_type if ref_type in REFERENCE_TYPES else DEFAULT_SETTINGS["reference_type"],
        "strength": max(0.0, min(STRENGTH_STORE_MAX, finite(value.get("strength"), DEFAULT_SETTINGS["strength"]))),
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
        self._extract_lock = threading.Lock()
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
                meta = self._json(self._character_meta_path(path.stem, folder.parent))
                items[path.stem] = {"file_hash": path.stem, "file_name": path.name, "mtime": path.stat().st_mtime,
                                    "character_name": str(meta.get("character_name") or ""),
                                    "character_prompt": str(meta.get("character_prompt") or ""),
                                    "character_uc": str(meta.get("character_uc") or ""), "has_image": True}
        return items

    def _listing(self, data, kind, model="", filter="all", category_id="", q="", sort="recent", offset=0, limit=60,
                 _file_hash="", group=""):
        self._kind(kind)
        if filter not in {"all", "favorite", "uncategorized", "category"} or sort not in {"recent", "name", "used"}:
            raise LibraryError("Invalid filter or sort")
        # 분류(CR 만) - 빈 값이면 전부(ANIMA · 옛 화면). 셈 · 폴더 목록도 그 분류 안에서.
        group = group if (kind == "character_reference" and group in CR_GROUPS) else ""
        try:
            offset, limit = max(0, int(offset)), max(1, min(200, int(limit)))
        except (ValueError, TypeError):
            raise LibraryError("Invalid pagination") from None
        current = self.context._current_model_key()
        model = safe_component(model or current) if kind == "vibe" else ""
        models = self._vibes() if kind == "vibe" else {}
        storage = models.get(model, {}) if kind == "vibe" else self._characters()
        categories = sorted(data[kind]["categories"], key=lambda g: g.get("order", 0))
        group_counts = {g: 0 for g in CR_GROUPS} if kind == "character_reference" else {}
        if group_counts:
            for file_hash in storage:
                group_counts[item_group(data[kind]["items"].get(file_hash, {}))] += 1
        if group:
            storage = {h: s for h, s in storage.items() if item_group(data[kind]["items"].get(h, {})) == group}
            categories = [g for g in categories if category_group(g) == group]
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
                item["group"] = item_group(meta)
                item["character_prompt"] = stored["character_prompt"]
                item["character_uc"] = stored["character_uc"]
                item["call_prompt"] = str(meta.get("call_prompt") or "")
                item["call_uc"] = str(meta.get("call_uc") or "")
                item["call_prompt_on"] = meta.get("call_prompt_on") is not False
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
                "group": group, "group_counts": group_counts,
                "counts": counts, "categories": [{"id": g["id"], "name": g["name"], "order": g.get("order", 0),
                    "group": category_group(g),
                    "count": counts["categories"][g["id"]]} for g in categories], "items": items[offset:offset + limit]}

    def list_items(self, kind, **query):
        with self._lock:
            return self._listing(self._read(), kind, **query)

    def callable_folders(self):
        """`ref:` 로 부를 수 있는 폴더(Character Reference) - [{id, name, group, items}] · 그림은 이름순.
        폴더 밖(미분류) 그림은 부를 수 없다(core/ref_prompt_resolver.py)."""
        kind = "character_reference"
        with self._lock:
            data = self._read()
            first = self._listing(data, kind, sort="name", limit=200)
            items = list(first["items"])
            while len(items) < first["total"]:
                page = self._listing(data, kind, sort="name", offset=len(items), limit=200)["items"]
                if not page:
                    break
                items += page
        return [{"id": c["id"], "name": c["name"], "group": c["group"],
                 "items": [i for i in items if i["category"] == c["id"]]} for c in first["categories"]]

    def character_image_path(self, file_hash):
        """보관 그림 원본(images/<해시>.png) 경로 - 없으면 LibraryError(404)."""
        file_hash = safe_component(file_hash)
        with self._lock:
            return self._character_image(file_hash)[1]

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
        if "call_prompt_on" in updates and not isinstance(updates["call_prompt_on"], bool):
            raise LibraryError("call_prompt_on must be boolean")
        for key, label in (("call_prompt", "호출 프롬프트"), ("call_uc", "호출 네거티브")):
            if key in updates:
                if kind != "character_reference":
                    raise LibraryError(f"{key} is only for Character Reference")
                updates[key] = clean_call_prompt(updates[key], label)
        if kind == "character_reference" and updates.get("name"):
            problem = callable_name_problem(updates["name"])
            if problem:
                raise LibraryError(problem)
        if "group" in updates and (kind != "character_reference" or updates["group"] not in CR_GROUPS):
            raise LibraryError("group must be one of " + ", ".join(CR_GROUPS))
        # 보관 그림의 종류(우클릭 · 2026-11-25) - 다음에 [적용] 할 때 이 종류로 들어간다. CR 만.
        if "reference_type" in updates and (kind != "character_reference"
                                            or updates["reference_type"] not in REFERENCE_TYPES):
            raise LibraryError("reference_type must be one of " + ", ".join(REFERENCE_TYPES))
        with self._lock:
            data = self._read()
            old = self._item(data, kind, file_hash, model)
            meta = data[kind]["items"].setdefault(file_hash, {"created_at": old["created_at"], "category": ""})
            meta.update({k: updates[k] for k in ("name", "favorite", "call_prompt", "call_uc") if k in updates})
            if "call_prompt_on" in updates:
                # 켜짐이 기본이라 꺼짐만 적어 둔다
                if updates["call_prompt_on"]:
                    meta.pop("call_prompt_on", None)
                else:
                    meta["call_prompt_on"] = False
            if "reference_type" in updates:
                meta["settings"] = reference_settings({**(meta.get("settings") or {}),
                                                       "reference_type": updates["reference_type"]})
            if "group" in updates and updates["group"] != item_group(meta):
                regroup_item(meta, updates["group"], data[kind]["categories"])
            self._write(data)
            return self._item(data, kind, file_hash, model)

    def change_category(self, kind, op, category_id="", name="", order=None, model="", group=""):
        self._kind(kind)
        if op not in ("create", "rename", "delete", "reorder", "regroup"):
            raise LibraryError("Invalid category operation")
        group = group if (kind == "character_reference" and group in CR_GROUPS) else ""
        if op == "regroup" and not group:
            raise LibraryError("group must be one of " + ", ".join(CR_GROUPS))
        with self._lock:
            data = self._read()
            categories = data[kind]["categories"]
            category = next((g for g in categories if g["id"] == category_id), None) if op != "create" else None
            if op in {"rename", "delete", "regroup"} and category is None:
                raise LibraryError("Category not found", 404)
            if op in {"create", "rename"}:
                if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40:
                    raise LibraryError("Category name must be 1 to 40 characters")
                name = name.strip()
                if kind == "character_reference":
                    problem = callable_name_problem(name)
                    if problem:
                        raise LibraryError(problem)
                # 세 분류를 통틀어 하나(대소문자 무시) - `ref:폴더` 가 어느 분류인지 이름만으로 안다
                if any(g["name"].casefold() == name.casefold() and g is not category for g in categories):
                    raise LibraryError("Category name already exists", 409)
                if op == "create":
                    category = {"id": "c_" + uuid.uuid4().hex[:12], "order": len(categories), "name": name}
                    if group:
                        category["group"] = group
                    categories.append(category)
                else:
                    category["name"] = name
            elif op == "regroup":
                # 폴더째 다른 분류로 - 안의 그림도 함께(옛 폴더는 분류가 없어 캐릭터로 보인다)
                category["group"] = group
                for item in data[kind]["items"].values():
                    if item.get("category") == category_id:
                        regroup_item(item, group, categories)
            elif op == "delete":
                categories.remove(category)
                for item in data[kind]["items"].values():
                    if item.get("category") == category_id:
                        item["category"] = ""
            else:
                # 분류를 주면 그 분류의 폴더만 차례를 바꾼다 - 다른 분류의 폴더는 제자리
                scope = [g for g in categories if not group or category_group(g) == group]
                if (not isinstance(order, list) or not all(isinstance(g, str) for g in order)
                        or len(order) != len(scope) or set(order) != {g["id"] for g in scope}):
                    raise LibraryError("order must contain each category exactly once")
                ordered = sorted(scope, key=lambda g: order.index(g["id"]))
                slots = [i for i, g in enumerate(categories) if g in scope]
                for slot, g in zip(slots, ordered):
                    categories[slot] = g
            for n, g in enumerate(categories):
                g["order"] = n
            self._write(data)
            result = self._listing(data, kind, model=model, group=group)
            return {k: result[k] for k in ("categories", "counts", "group_counts")}

    def move_items(self, kind, file_hashes, category_id="", model=""):
        self._kind(kind)
        if not isinstance(file_hashes, list) or not isinstance(category_id, str):
            raise LibraryError("Invalid category move")
        hashes = list(dict.fromkeys(safe_component(h) for h in file_hashes))
        with self._lock:
            data = self._read()
            target = next((c for c in data[kind]["categories"] if c["id"] == category_id), None)
            if category_id and target is None:
                raise LibraryError("Category not found", 404)
            items = [self._item(data, kind, h, model) for h in hashes]
            for item in items:
                meta = data[kind]["items"].setdefault(item["file_hash"], {"created_at": item["created_at"]})
                # 폴더는 그 분류의 그림만 받는다(의상 폴더에 캐릭터 그림을 끌어다 놓아도 안 들어간다)
                if kind == "character_reference" and target is not None and category_group(target) != item_group(meta):
                    raise LibraryError("다른 분류의 폴더로는 옮길 수 없습니다 - 먼저 우클릭 > 보내기로 분류를 바꾸세요")
                meta["category"] = category_id
            self._write(data)
            group = category_group(target) if (kind == "character_reference" and target is not None) else ""
            return {"items": [self._item(data, kind, h, model) for h in hashes],
                    "counts": self._listing(data, kind, model=model, group=group)["counts"]}

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
                if kind == "character_reference" and item.get("group") not in CR_GROUPS:
                    # 활성 칸에서 종류를 바꿔도 보관함 분류는 그대로(분류는 보관함에서만 바꾼다)
                    item["group"] = item_group(before)
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

    def _character_image(self, file_hash):
        # Caller holds the library lock; prefer the same root as the listing.
        for root in self._roots("character_reference"):
            target = root / "images" / (file_hash + ".png")
            if root.resolve() not in target.resolve().parents:
                raise LibraryError("Storage path escapes its root")
            if target.is_file():
                return root, target
        raise LibraryError("Storage item not found", 404)

    def _character_meta_path(self, file_hash, image_root):
        """Metadata for this image: its own root first, then any other Character Reference root.

        Turning on a reference stored in a legacy root copies only the image into the primary root, so the legacy
        metadata (name / prompt) stays behind - look it up there too (Codex review 2026-10-23). Missing everywhere ->
        the image root's own path (writes go there).
        """
        roots = [image_root] + [r for r in self._roots("character_reference") if r != image_root]
        for root in roots:
            candidate = root / "metadata" / (file_hash + ".json")
            if candidate.is_file():
                return candidate
        return image_root / "metadata" / (file_hash + ".json")

    def character_prompts(self, file_hashes):
        """활성 칸이 쓸 그림별 캐릭터 프롬프트(ANIMA 참조 줄 · 2026-11-05) - 보관함 전체를 훑지 않고 그 해시만 읽는다."""
        out = {}
        with self._lock:
            for file_hash in dict.fromkeys(file_hashes):
                try:
                    clean = safe_component(file_hash)
                    root, _image = self._character_image(clean)
                except LibraryError:
                    continue
                meta = self._json(self._character_meta_path(clean, root))
                out[clean] = {"character_prompt": str(meta.get("character_prompt") or ""),
                              "character_uc": str(meta.get("character_uc") or "")}
        return out

    def set_character_prompt(self, file_hash, prompt, uc=""):
        file_hash = safe_component(file_hash)
        for name, value in (("prompt", prompt), ("uc", uc)):
            if not isinstance(value, str) or len(value.strip()) > 4000:
                raise LibraryError(f"{name} must be a string of at most 4000 characters")
        prompt, uc = prompt.strip(), uc.strip()
        with self._lock:
            root, image = self._character_image(file_hash)
            path = root / "metadata" / (file_hash + ".json")
            if root.resolve() not in path.resolve().parents:
                raise LibraryError("Storage path escapes its root")
            defaults = {"file_name": image.name, "file_hash": file_hash}
            # Read from wherever the metadata lives (maybe a legacy root), write next to the image - keys carried over.
            source = self._character_meta_path(file_hash, root)
            try:
                metadata = json.loads(source.read_text(encoding="utf-8"))
                if not isinstance(metadata, dict):
                    raise ValueError("Invalid character metadata")
            except FileNotFoundError:
                metadata = dict(defaults)
            except (ValueError, UnicodeError):
                # Keep EVERY corrupt version: a second corruption gets its own name instead of being dropped
                # (Codex review 2026-10-23 - it held recoverable legacy names and prompts).
                backup = source.with_name(source.name + ".broken")
                if backup.exists():
                    backup = source.with_name(f"{source.name}.broken-{time.time():.9f}")
                shutil.copy2(source, backup)
                metadata = dict(defaults)
            if prompt or uc:
                metadata.update(character_prompt=prompt, character_uc=uc)
            else:
                metadata.pop("character_prompt", None)
                metadata.pop("character_uc", None)
            self._atomic_write(path, metadata)
            # _characters reads fresh, including edits to legacy per-image metadata.
            return self._item(self._read(), "character_reference", file_hash)

    def extract_character_features(self, file_hash):
        from core.inset_feature_extract import split_character_features
        from core.wd_tagger_service import tag_image

        file_hash = safe_component(file_hash)
        if not self._extract_lock.acquire(blocking=False):
            raise LibraryError("already running")
        try:
            with self._lock:
                _root, image = self._character_image(file_hash)
                try:
                    data = image.read_bytes()
                except FileNotFoundError:
                    raise LibraryError("Storage item not found", 404) from None
            # External request only from the explicit extraction route; no metadata writes.
            result = tag_image(data)
            split = split_character_features(
                [row["tag"] for row in result.character],
                [row["tag"] for row in result.general],
                getattr(self.context, "filter_data_manager", None),
                getattr(self.context, "repo_root", None),
            )
            return {"ok": True, **split, "elapsed_ms": result.elapsed_ms}
        finally:
            self._extract_lock.release()

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
