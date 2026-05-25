"""Headless Instant Wildcard and Chunk module state service."""

from __future__ import annotations

import json
from typing import Any


class HeadlessInstantWildcardService:
    def __init__(self, context: Any):
        self.context = context

    def store(self, *, force: bool = False) -> dict[str, Any]:
        from core.instant_wildcard_service import load_instant_wildcards

        signature = None
        if not force:
            cached = getattr(self.context, "instant_wildcard_store", None)
            signature = getattr(self.context, "instant_wildcard_signature", None)
            if isinstance(cached, dict) and signature == cached.get("signature"):
                return cached
        root = self.context._existing_save_path("instant_wildcard")
        store = load_instant_wildcards(root)
        self.context.instant_wildcard_store = store
        self.context.instant_wildcard_signature = store.get("signature")
        self.apply_to_manager(store)
        return store

    def apply_to_manager(self, store: dict[str, Any]) -> None:
        manager = self.context.wildcard_manager
        if manager is not None and hasattr(manager, "update_instant_wildcards"):
            try:
                manager.update_instant_wildcards(
                    store.get("instant_wildcard_dict", {}),
                    store.get("instant_wildcard_tree", {}),
                )
                return
            except Exception:
                pass
        self.context.instant_wildcard_dict = store.get("instant_wildcard_dict", {})
        self.context.instant_wildcard_tree = store.get("instant_wildcard_tree", {})

    def state(self) -> dict[str, Any]:
        from core.instant_wildcard_service import instant_wildcard_group_name, select_instant_wildcard_item

        store = self.store()
        json_data = store.get("json_data", {}) if isinstance(store, dict) else {}
        current_file = getattr(self.context, "instant_wildcard_current_file", None)
        current_key = getattr(self.context, "instant_wildcard_current_key", None)
        selected_file, selected_key = select_instant_wildcard_item(json_data, current_file, current_key)
        self.context.instant_wildcard_current_file = selected_file
        self.context.instant_wildcard_current_key = selected_key
        current_items = json_data.get(selected_file or "", {}) if isinstance(json_data, dict) else {}
        current_items = current_items if isinstance(current_items, dict) else {}
        files = []
        for filename, data in json_data.items():
            data = data if isinstance(data, dict) else {}
            files.append({
                "name": filename,
                "group": instant_wildcard_group_name(filename),
                "count": len(data),
                "selected": filename == selected_file,
            })
        items = [
            {
                "key": key,
                "value": str(current_items.get(key) or ""),
                "selected": key == selected_key,
            }
            for key in sorted(current_items.keys())
        ]
        current_value = str(current_items.get(selected_key, "") or "") if selected_key else ""
        return self.context._module_state_payload("instant_wildcard", {
            "files": files,
            "items": items,
            "current_file": selected_file or "",
            "current_group": instant_wildcard_group_name(selected_file or "") if selected_file else "",
            "current_key": selected_key or "",
            "current_value": current_value,
            "flat_count": len(store.get("instant_wildcard_dict", {}) or {}),
            "save_path": str(store.get("save_path") or ""),
        })

    def chunk_state(self) -> dict[str, Any]:
        from core.instant_wildcard_service import instant_wildcard_group_name

        store = self.store()
        json_data = store.get("json_data", {}) if isinstance(store, dict) else {}
        groups = []
        for filename, items in json_data.items():
            if not isinstance(items, dict):
                continue
            groups.append({
                "name": instant_wildcard_group_name(filename),
                "items": [
                    {"key": str(key), "value": str(value)}
                    for key, value in sorted(items.items(), key=lambda item: str(item[0]))
                ],
            })
        return {"type": "module_state", "module_id": "chunk", "available": True, "runtime": "web", "groups": groups}

    def set_param(self, key: str, value: Any) -> dict[str, Any] | None:
        from core.instant_wildcard_service import (
            instant_wildcard_group_name,
            normalize_instant_wildcard_filename,
            write_instant_wildcard_file,
        )

        context = self.context
        store = self.store(force=key == "reload")
        json_data = store.get("json_data", {}) if isinstance(store, dict) else {}
        if key == "reload":
            return self.state()
        if key == "select_file":
            filename = normalize_instant_wildcard_filename(str(value or ""))
            if filename in json_data:
                context.instant_wildcard_current_file = filename
                items = json_data.get(filename, {})
                context.instant_wildcard_current_key = next(iter(sorted(items.keys()))) if isinstance(items, dict) and items else None
            return self.state()
        if key == "select_key":
            item_key = str(value or "").strip()
            filename = getattr(context, "instant_wildcard_current_file", None)
            if filename in json_data and item_key in json_data.get(filename, {}):
                context.instant_wildcard_current_key = item_key
            return self.state()
        if key == "add_group":
            filename = normalize_instant_wildcard_filename(str(value or ""))
            if not filename:
                return context._toast("Instant wildcard group is required", level="error")
            json_data.setdefault(filename, {})
            write_instant_wildcard_file(json_data, filename, store.get("save_path") or "")
            context.instant_wildcard_current_file = filename
            context.instant_wildcard_current_key = None
            self.store(force=True)
            return self.state()
        if key == "value":
            filename = getattr(context, "instant_wildcard_current_file", None)
            item_key = getattr(context, "instant_wildcard_current_key", None)
            if filename and item_key:
                json_data.setdefault(filename, {})[item_key] = str(value or "")
                write_instant_wildcard_file(json_data, filename, store.get("save_path") or "")
                self.store(force=True)
            return self.state()
        if key in {"upsert", "delete", "rename"}:
            try:
                payload = json.loads(str(value or "{}"))
            except json.JSONDecodeError:
                return context._toast("Invalid instant wildcard payload", level="error")
            filename = normalize_instant_wildcard_filename(
                str(payload.get("file") or getattr(context, "instant_wildcard_current_file", "") or "")
            )
            if not filename:
                return context._toast("Instant wildcard file is required", level="error")
            if key == "upsert":
                item_key = str(payload.get("key") or "").strip()
                if not item_key:
                    return context._toast("Instant wildcard key is required", level="error")
                json_data.setdefault(filename, {})[item_key] = str(payload.get("value") or "")
                context.instant_wildcard_current_file = filename
                context.instant_wildcard_current_key = item_key
            elif key == "delete":
                item_key = str(payload.get("key") or "").strip()
                if filename in json_data and item_key in json_data[filename]:
                    del json_data[filename][item_key]
                    image_path = context._existing_save_path(
                        "instant_wildcard",
                        "images",
                        instant_wildcard_group_name(filename),
                        f"{item_key}.png",
                    )
                    if image_path.exists():
                        try:
                            image_path.unlink()
                        except Exception:
                            pass
                if getattr(context, "instant_wildcard_current_key", None) == item_key:
                    remaining = json_data.get(filename, {})
                    context.instant_wildcard_current_key = next(iter(sorted(remaining.keys()))) if remaining else None
            elif key == "rename":
                old_key = str(payload.get("old_key") or "").strip()
                new_key = str(payload.get("new_key") or "").strip()
                if filename in json_data and old_key in json_data[filename] and new_key:
                    json_data[filename][new_key] = json_data[filename].pop(old_key)
                    context.instant_wildcard_current_file = filename
                    context.instant_wildcard_current_key = new_key
            write_instant_wildcard_file(json_data, filename, store.get("save_path") or "")
            self.store(force=True)
            return self.state()
        return context._toast(f"Instant wildcard action is not supported in this runtime: {key}", level="info")
