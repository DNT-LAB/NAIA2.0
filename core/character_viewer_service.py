"""Server-side Character Viewer data and prompt helpers."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote


class CharacterViewerService:
    GROUP_ALL = "__ALL__"
    DEFAULT_PREFIX = "1girl, artist:rento (rukeai), solo, cowboy shot, standing"
    DEFAULT_POSTFIX = (
        "simple background, white background, very aesthetic, extremely absurdres, "
        "amazing quality, masterpiece, year 2024"
    )
    TAG_REPLACE = {"loli": "young female"}
    TAG_EXCLUDE = {"mature female"}
    THUMB_MAX_SIZE = (896, 1152)

    def __init__(
        self,
        root: Path | str,
        *,
        data_root: Path | str | None = None,
        save_root: Path | str | None = None,
    ):
        self.root = Path(root)
        self.data_dir = Path(data_root) if data_root is not None else self.root / "data"
        self.save_dir = Path(save_root) if save_root is not None else self.root / "save"
        self.groups_path = self.data_dir / "copyright_groups.json"
        self.analysis_path = self.data_dir / "character_analysis.json"
        self.thumb_dir = self.data_dir / "character_thumbnails"
        self.thumb_index_path = self.thumb_dir / "index.json"
        self.tags_path = self.save_dir / "character_viewer_tags.json"
        self._groups: dict[str, Any] | None = None
        self._analysis: dict[str, Any] | None = None
        self._thumb_index: dict[str, str] | None = None

    def data_available(self) -> bool:
        return self.groups_path.exists() and self.analysis_path.exists()

    def _load_json(self, path: Path, fallback: Any) -> Any:
        if not path.exists():
            return fallback
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def groups(self) -> dict[str, Any]:
        if self._groups is None:
            self._groups = self._load_json(self.groups_path, {})
        return self._groups

    def analysis(self) -> dict[str, Any]:
        if self._analysis is None:
            self._analysis = self._load_json(self.analysis_path, {})
        return self._analysis

    def thumb_index(self) -> dict[str, str]:
        if self._thumb_index is None:
            self._thumb_index = self._load_json(self.thumb_index_path, {})
        return self._thumb_index

    def reload_thumbnails(self) -> None:
        self._thumb_index = None

    def load_options(self) -> dict[str, Any]:
        data = self._load_json(self.tags_path, {})
        return {
            "prefix": data.get("prefix", self.DEFAULT_PREFIX),
            "postfix": data.get("postfix", self.DEFAULT_POSTFIX),
            "cosplay_enabled": bool(data.get("cosplay_enabled", False)),
            "cosplay_name": str(data.get("cosplay_name", "")),
            "auto_copyright": bool(data.get("auto_copyright", False)),
            "auto_characteristics": bool(data.get("auto_characteristics", True)),
            "hide_charname": bool(data.get("hide_charname", False)),
            "no_save": bool(data.get("no_save", False)),
            "thumb_first": bool(data.get("thumb_first", data.get("empty_thumb_only", True))),
            "empty_thumb_only": bool(data.get("empty_thumb_only", True)),
        }

    def save_options(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.load_options()
        for key in (
            "prefix",
            "postfix",
            "cosplay_name",
            "cosplay_enabled",
            "auto_copyright",
            "auto_characteristics",
            "hide_charname",
            "no_save",
            "thumb_first",
            "empty_thumb_only",
        ):
            if key in payload:
                current[key] = payload[key]
        self.save_dir.mkdir(parents=True, exist_ok=True)
        with open(self.tags_path, "w", encoding="utf-8") as handle:
            json.dump(current, handle, ensure_ascii=False, indent=2)
        return current

    def _group_counts(self) -> list[tuple[str, int]]:
        out: list[tuple[str, int]] = []
        for group_key, data in self.groups().items():
            if str(group_key).startswith("_") or not isinstance(data, dict):
                continue
            total = len(data.get("girl", []) or []) + len(data.get("boy", []) or [])
            out.append((group_key, total))
        out.sort(key=lambda item: (-item[1], item[0].lower()))
        return out

    def state(self) -> dict[str, Any]:
        group_counts = self._group_counts()
        character_count = sum(1 for _ in self._iter_all_chars())
        thumbs = self.thumb_index()
        return {
            "available": self.data_available(),
            "group_count": len(group_counts),
            "character_count": character_count,
            "thumbnail_count": len(thumbs),
            "options": self.load_options(),
        }

    def build_groups(self, query: str = "", limit: int = 2000) -> dict[str, Any]:
        query_text = str(query or "").strip().lower()
        groups = [{"key": self.GROUP_ALL, "name": "All", "count": sum(c for _, c in self._group_counts())}]
        for key, count in self._group_counts():
            if query_text and query_text not in key.lower():
                continue
            groups.append({"key": key, "name": key, "count": count})
            if len(groups) >= limit:
                break
        return {"items": groups, "total": len(groups)}

    def _iter_all_chars(self):
        for group_key, chars in self.analysis().items():
            if not isinstance(chars, dict):
                continue
            for name, data in chars.items():
                if isinstance(data, dict):
                    yield group_key, name, data

    @staticmethod
    def _tag_search_str(data: dict[str, Any]) -> str:
        parts: list[str] = []
        for entry in data.get("personal_color", []) or []:
            if entry.get("tag"):
                parts.append(str(entry["tag"]))
        for entry in data.get("characteristics", []) or []:
            if entry.get("tag"):
                parts.append(str(entry["tag"]))
        dist = (data.get("breast_size", {}) or {}).get("distribution", []) or []
        if dist:
            top = max(dist, key=lambda entry: entry.get("count", 0))
            if top.get("tag"):
                parts.append(str(top["tag"]))
        return ", ".join(parts)

    def _matches_query(self, name: str, data: dict[str, Any], query: str) -> bool:
        raw = str(query or "").strip().lower()
        if not raw:
            return True
        exact = raw.startswith("*")
        text = raw[1:].strip() if exact else raw
        if not text:
            return True
        display = name.lower()
        tag_str = self._tag_search_str(data).lower()
        if exact:
            if re.search(r"\b" + re.escape(text) + r"\b", display):
                return True
            tags = {part.strip().lower() for part in tag_str.split(",") if part.strip()}
            return text in tags
        return text in display or text in tag_str

    def _thumb_key(self, group_key: str, name: str, variant_label: str = "") -> str:
        key = f"{group_key}::{name}"
        if variant_label:
            key += f"::{variant_label}"
        return key

    def _thumb_url(self, group_key: str, name: str, variant_label: str = "", size: str = "") -> str:
        if self._thumb_key(group_key, name, variant_label) not in self.thumb_index():
            return ""
        params = f"group={quote(group_key, safe='')}&character={quote(name, safe='')}"
        if variant_label:
            params += f"&variant={quote(variant_label, safe='')}"
        if size:
            params += f"&size={quote(size, safe='')}"
        return f"/api/character-viewer/thumbnail?{params}"

    def _serialize_list_item(
        self,
        index: int,
        group_key: str,
        name: str,
        data: dict[str, Any],
        thumbs: dict[str, str],
        include_thumbnail_url: bool = False,
        include_tags: bool = False,
        thumbnail_size: str = "",
    ) -> dict[str, Any]:
        item = {
            "index": int(index),
            "group": group_key,
            "character": name,
            "count": int(data.get("total_rows", 0) or 0),
            "has_thumbnail": self._thumb_key(group_key, name) in thumbs,
        }
        if include_tags:
            item["tags"] = self._tag_search_str(data)
        if include_thumbnail_url:
            item["thumbnail_url"] = self._thumb_url(group_key, name, size=thumbnail_size)
        return item

    def build_list(
        self,
        group_key: str = GROUP_ALL,
        query: str = "",
        page: int = 0,
        per_page: int = 48,
        thumb_first: bool = True,
        include_all: bool = False,
    ) -> dict[str, Any]:
        if group_key == self.GROUP_ALL:
            chars = list(self._iter_all_chars())
        else:
            chars = [
                (group_key, name, data)
                for name, data in (self.analysis().get(group_key, {}) or {}).items()
                if isinstance(data, dict)
            ]
        chars = [item for item in chars if self._matches_query(item[1], item[2], query)]
        thumbs = self.thumb_index()
        if thumb_first:
            chars.sort(
                key=lambda item: (
                    self._thumb_key(item[0], item[1]) not in thumbs,
                    -int(item[2].get("total_rows", 0) or 0),
                    item[1].lower(),
                )
            )
        else:
            chars.sort(key=lambda item: (-int(item[2].get("total_rows", 0) or 0), item[1].lower()))

        total = len(chars)
        per_page = max(9, min(96, int(per_page or 48)))
        page = max(0, int(page or 0))
        total_pages = max(1, math.ceil(total / per_page))
        if page >= total_pages:
            page = total_pages - 1
        start = page * per_page
        page_items = [
            (index, gk, name, data)
            for index, (gk, name, data) in enumerate(chars[start:start + per_page], start)
        ]
        all_items = [
            self._serialize_list_item(index, gk, name, data, thumbs)
            for index, (gk, name, data) in enumerate(chars)
        ] if include_all else None
        return {
            "group": group_key,
            "query": query,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "thumb_first": bool(thumb_first),
            "items": [
                self._serialize_list_item(
                    index,
                    gk,
                    name,
                    data,
                    thumbs,
                    include_thumbnail_url=True,
                    thumbnail_size="grid",
                )
                for index, gk, name, data in page_items
            ],
            "all_items": all_items,
        }

    def _get_character(self, group_key: str, name: str) -> dict[str, Any]:
        data = (self.analysis().get(group_key, {}) or {}).get(name)
        if not isinstance(data, dict):
            raise KeyError(f"Character not found: {group_key}::{name}")
        return data

    def _resolve_variant(self, data: dict[str, Any], variant_label: str = "") -> dict[str, Any] | None:
        if not variant_label:
            return None
        for variant in data.get("alternates", []) or []:
            if str(variant.get("label") or "") == variant_label:
                return variant
        raise KeyError(f"Variant not found: {variant_label}")

    def _variant_items(self, data: dict[str, Any], variant: dict[str, Any] | None):
        if variant is None:
            pc_items = list(data.get("personal_color", []) or [])
            ch_items = list(data.get("characteristics", []) or [])
            attire_items: list[dict[str, Any]] = []
            dist = (data.get("breast_size", {}) or {}).get("distribution", []) or []
            if dist:
                ch_items.insert(0, max(dist, key=lambda entry: entry.get("pct", 0)))
        else:
            pc_items = list(variant.get("personal_color", []) or [])
            ch_items = list(variant.get("characteristics", []) or [])
            attire_items = [entry for entry in (variant.get("attire", []) or []) if entry.get("pct", 0) >= 60.0]
        return pc_items, ch_items, attire_items

    @staticmethod
    def _format_entry(entry: dict[str, Any]) -> dict[str, Any]:
        return {
            "tag": str(entry.get("tag") or ""),
            "count": int(entry.get("count", 0) or 0),
            "pct": float(entry.get("pct", 0) or 0),
        }

    def build_detail(
        self,
        group_key: str,
        name: str,
        variant_label: str = "",
        options: dict[str, Any] | None = None,
        api_mode: str = "NAI",
    ) -> dict[str, Any]:
        data = self._get_character(group_key, name)
        variant = self._resolve_variant(data, variant_label)
        pc_items, ch_items, attire_items = self._variant_items(data, variant)
        prompt_payload = self.build_prompt(group_key, name, variant_label, options or {}, api_mode)
        variants = [
            {"label": "", "name": "Default", "rows": int(data.get("total_rows", 0) or 0)}
        ]
        variants.extend(
            {
                "label": str(item.get("label") or ""),
                "name": str(item.get("label") or "").replace("_", " "),
                "rows": int(item.get("rows", 0) or 0),
            }
            for item in data.get("alternates", []) or []
        )
        return {
            "group": group_key,
            "character": name,
            "count": int(data.get("total_rows", 0) or 0),
            "gender": data.get("gender", ""),
            "aliases": data.get("aliases", []) or [],
            "variant": variant_label,
            "variants": variants,
            "thumbnail_url": self._thumb_url(group_key, name, variant_label),
            "default_thumbnail_url": self._thumb_url(group_key, name),
            "sections": {
                "alternate": variants,
                "personal_color": [self._format_entry(entry) for entry in pc_items],
                "characteristics": [self._format_entry(entry) for entry in ch_items],
                "attire": [self._format_entry(entry) for entry in attire_items],
            },
            "prompt": prompt_payload,
        }

    @staticmethod
    def _split_tags(value: str) -> list[str]:
        return [part.strip() for part in str(value or "").split(",") if part.strip()]

    @staticmethod
    def _escape_sd_tag(tag: str) -> str:
        return str(tag or "").replace("(", r"\(").replace(")", r"\)")

    def build_prompt(
        self,
        group_key: str,
        name: str,
        variant_label: str = "",
        options: dict[str, Any] | None = None,
        api_mode: str = "NAI",
    ) -> dict[str, Any]:
        data = self._get_character(group_key, name)
        variant = self._resolve_variant(data, variant_label)
        pc_items, ch_items, attire_items = self._variant_items(data, variant)
        current = self.load_options()
        current.update(options or {})

        is_nai = str(api_mode or "NAI").upper() == "NAI"
        cosplay_mode = bool(current.get("cosplay_enabled"))
        cosplay_parts = self._split_tags(current.get("cosplay_name", "")) if cosplay_mode else []
        cosplay_char = cosplay_parts[0] if cosplay_parts else ""
        cosplay_extra = cosplay_parts[1:] if len(cosplay_parts) > 1 else []

        if current.get("hide_charname"):
            char_name = "original"
        elif cosplay_mode and cosplay_char:
            char_name = cosplay_char if is_nai else self._escape_sd_tag(cosplay_char)
        else:
            char_name = name
            if variant_label:
                char_name = f"{char_name} ({variant_label.replace('_', ' ')})"
            if not is_nai:
                char_name = self._escape_sd_tag(char_name)

        tags: list[str] = []
        cosplay_excluded_pc: list[str] = []
        if cosplay_mode:
            dist = (data.get("breast_size", {}) or {}).get("distribution", []) or []
            bs_tag = max(dist, key=lambda item: item.get("pct", 0)).get("tag") if dist else None
            extra = cosplay_extra if is_nai else [self._escape_sd_tag(item) for item in cosplay_extra]
            tags.extend(["alternate costume", "borrowed character"])
            tags.extend(extra)
            original_name = name if is_nai else self._escape_sd_tag(name)
            if original_name:
                cosplay_suffix = "(cosplay)" if is_nai else r"\(cosplay\)"
                tags.append(f"{original_name} {cosplay_suffix}")
            tags.append("borrowed clothes")
            if current.get("auto_characteristics", True):
                for entry in ch_items:
                    tag = entry.get("tag", "")
                    if tag in self.TAG_EXCLUDE or tag == bs_tag:
                        continue
                    tags.append(self.TAG_REPLACE.get(tag, tag))
            for entry in attire_items:
                tag = entry.get("tag", "")
                if tag not in self.TAG_EXCLUDE:
                    tags.append(self.TAG_REPLACE.get(tag, tag))
            for entry in data.get("personal_color", []) or []:
                tag = entry.get("tag", "")
                if tag not in self.TAG_EXCLUDE:
                    cosplay_excluded_pc.append(tag)
        else:
            for entry in pc_items:
                tag = entry.get("tag", "")
                if tag not in self.TAG_EXCLUDE:
                    tags.append(self.TAG_REPLACE.get(tag, tag))
            if current.get("auto_characteristics", True):
                for entry in ch_items:
                    tag = entry.get("tag", "")
                    if tag not in self.TAG_EXCLUDE:
                        tags.append(self.TAG_REPLACE.get(tag, tag))
            for entry in attire_items:
                tag = entry.get("tag", "")
                if tag not in self.TAG_EXCLUDE:
                    tags.append(self.TAG_REPLACE.get(tag, tag))

        prefix_parts: list[str] = []
        if char_name:
            if is_nai:
                prefix_parts.append("girl")
            prefix_parts.append(char_name)
            if current.get("auto_copyright") and group_key:
                prefix_parts.append(group_key if is_nai else self._escape_sd_tag(group_key))
        character_prompt = (", ".join(prefix_parts) + ", " if prefix_parts else "") + ", ".join(tags)
        return {
            "character_prompt": character_prompt.strip().strip(","),
            "prefix": str(current.get("prefix") or ""),
            "postfix": str(current.get("postfix") or ""),
            "cosplay_excluded_pc": cosplay_excluded_pc,
            "options": current,
        }

    def build_generation_overrides(self, payload: dict[str, Any], api_mode: str = "NAI") -> dict[str, Any]:
        group_key = str(payload.get("group") or "")
        name = str(payload.get("character") or "")
        variant_label = str(payload.get("variant") or "")
        if not group_key or not name:
            raise ValueError("group and character are required")
        data = self._get_character(group_key, name)

        char_prompt = str(payload.get("character_prompt") or "").strip()
        prefix_text = str(payload.get("prefix") or "").strip()
        postfix_text = str(payload.get("postfix") or "").strip()
        if not (char_prompt or prefix_text or postfix_text):
            raise ValueError("prompt is empty")

        request_id = str(payload.get("request_id") or "")
        if not request_id:
            raise ValueError("request_id is required")
        is_nai = str(api_mode or "NAI").upper() == "NAI"
        width, height = 896, 1152
        snapshot = {
            "group_key": group_key,
            "char_name": name,
            "variant_label": variant_label,
            "save_blocked": bool(
                payload.get("no_save")
                or payload.get("hide_charname")
                or payload.get("cosplay_enabled")
            ),
        }
        label = name + (f" ({variant_label.replace('_', ' ')})" if variant_label else "")
        common = {
            "character_viewer_request": True,
            "character_viewer_request_id": request_id,
            "_remote_queue_source": "Characters",
            "_remote_queue_label": label,
            "_character_viewer_snapshot": snapshot,
            "width": width,
            "height": height,
            "random_resolution": False,
        }
        if is_nai:
            overrides = {
                **common,
                "input": ", ".join(part for part in (prefix_text, postfix_text) if part),
            }
            if char_prompt:
                overrides["characters"] = [char_prompt]
                overrides["uc"] = [str(payload.get("character_uc") or "")]
            return overrides

        char_tags = [tag for tag in self._split_tags(char_prompt) if tag.lower() != "girl"]
        char_name_tags = char_tags[:1]
        char_trait_tags = char_tags[1:]
        prefix_tags = self._split_tags(prefix_text)
        postfix_tags = self._split_tags(postfix_text)
        insert_idx = 0
        for index, tag in enumerate(prefix_tags):
            if "girl" in tag.lower():
                insert_idx = index + 1
                break
        merged = prefix_tags[:insert_idx] + char_name_tags + prefix_tags[insert_idx:] + char_trait_tags + postfix_tags
        for tag in self._split_tags(payload.get("character_uc") or ""):
            merged.append(f"-{tag}")
        return {**common, "input": ", ".join(merged)}

    def thumbnail_path(self, group_key: str, name: str, variant_label: str = "") -> Path:
        filename = self.thumb_index().get(self._thumb_key(group_key, name, variant_label))
        if not filename:
            raise FileNotFoundError("thumbnail not found")
        path = (self.thumb_dir / filename).resolve()
        if self.thumb_dir.resolve() not in path.parents and path != self.thumb_dir.resolve():
            raise ValueError("invalid thumbnail path")
        if not path.exists():
            raise FileNotFoundError("thumbnail not found")
        return path

    def save_thumbnail(self, pil_image: Any, snapshot: dict[str, Any]) -> dict[str, Any] | None:
        group_key = str(snapshot.get("group_key") or "")
        name = str(snapshot.get("char_name") or "")
        variant_label = str(snapshot.get("variant_label") or "")
        if not group_key or not name:
            return None
        from PIL import Image

        self.thumb_dir.mkdir(parents=True, exist_ok=True)
        key = self._thumb_key(group_key, name, variant_label)
        safe_name = re.sub(r'[<>:"/\\|?*]', "_", key.replace("::", "__")) + ".webp"
        thumb = pil_image.copy()
        thumb.thumbnail(self.THUMB_MAX_SIZE, Image.Resampling.LANCZOS)
        thumb.save(self.thumb_dir / safe_name, "WEBP", quality=82)

        index = dict(self.thumb_index())
        index[key] = safe_name
        with open(self.thumb_index_path, "w", encoding="utf-8") as handle:
            json.dump(index, handle, ensure_ascii=False, indent=2)
        self._thumb_index = index
        return {
            "key": key,
            "filename": safe_name,
            "url": self._thumb_url(group_key, name, variant_label),
        }
