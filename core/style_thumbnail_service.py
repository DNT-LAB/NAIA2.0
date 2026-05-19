"""PyQt-free style thumbnail data service for the Remote Web Thumb tab."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote


class StyleThumbnailService:
    META_PATH = Path("data/taglist/style_meta_tags.json")
    THUMBNAILS_PATH = Path("data/taglist/style_thumbnails.json")

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.meta_path = self.root / self.META_PATH
        self.thumbnails_path = self.root / self.THUMBNAILS_PATH
        self._meta_cache: dict[str, Any] | None = None
        self._thumbnail_cache: dict[str, str] | None = None

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(str(path))
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError(f"Invalid JSON object: {path}")
        return data

    def metadata(self) -> dict[str, Any]:
        if self._meta_cache is None:
            data = self._load_json(self.meta_path)
            if not isinstance(data.get("categories"), dict):
                data["categories"] = {}
            self._meta_cache = data
        return self._meta_cache

    def thumbnails(self) -> dict[str, str]:
        if self._thumbnail_cache is None:
            data = self._load_json(self.thumbnails_path)
            self._thumbnail_cache = {
                str(key): str(value)
                for key, value in data.items()
                if isinstance(value, str) and value.strip()
            }
        return self._thumbnail_cache

    def categories(self) -> dict[str, Any]:
        categories = self.metadata().get("categories", {})
        return categories if isinstance(categories, dict) else {}

    def state(self) -> dict[str, Any]:
        categories = self.categories()
        thumbnail_keys = set(self.thumbnails().keys())
        category_payload = []
        for key, info in categories.items():
            if not isinstance(info, dict):
                continue
            tags = [str(tag) for tag in info.get("tags", []) if str(tag or "").strip()]
            available = [tag for tag in tags if tag in thumbnail_keys]
            category_payload.append({
                "key": str(key),
                "name": str(info.get("name") or key),
                "description": str(info.get("description") or ""),
                "total": len(tags),
                "available": len(available),
            })

        selected = ""
        for category in category_payload:
            if category["available"]:
                selected = category["key"]
                break
        if not selected and category_payload:
            selected = category_payload[0]["key"]

        return {
            "categories": category_payload,
            "selected": selected,
            "total_available": sum(category["available"] for category in category_payload),
        }

    def category_payload(self, category_key: str) -> dict[str, Any]:
        key = str(category_key or "").strip()
        categories = self.categories()
        if key not in categories:
            raise KeyError("Unknown style thumbnail category")
        info = categories[key]
        if not isinstance(info, dict):
            raise KeyError("Unknown style thumbnail category")
        thumbnail_data = self.thumbnails()
        tags = [
            str(tag)
            for tag in info.get("tags", [])
            if str(tag or "").strip() and str(tag) in thumbnail_data
        ]
        return {
            "key": key,
            "name": str(info.get("name") or key),
            "description": str(info.get("description") or ""),
            "tags": [
                {
                    "tag": tag,
                    "image_url": f"/api/thumb/image?tag={quote(tag, safe='')}",
                }
                for tag in tags
            ],
        }

    @staticmethod
    def media_type(image_bytes: bytes) -> str:
        if image_bytes.startswith(b"\xff\xd8"):
            return "image/jpeg"
        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
            return "image/webp"
        return "application/octet-stream"

    def image_payload(self, tag: str) -> tuple[bytes, str]:
        tag_name = str(tag or "").strip()
        if not tag_name:
            raise ValueError("tag is required")
        encoded = self.thumbnails().get(tag_name)
        if not encoded:
            raise FileNotFoundError(f"Style thumbnail not found: {tag_name}")
        if encoded.startswith("data:") and "," in encoded:
            encoded = encoded.split(",", 1)[1]
        image_bytes = base64.b64decode(encoded)
        return image_bytes, self.media_type(image_bytes)
