"""PyQt-free style thumbnail data service for the Remote Web Thumb tab."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import quote

from core.style_variants import STYLE_VARIANTS_APPROX_MB, open_variants


class StyleThumbnailService:
    META_PATH = Path("data/taglist/style_meta_tags.json")
    THUMBNAILS_PATH = Path("data/taglist/style_thumbnails.json")

    def __init__(self, root: Path | str, variants_path: Path | None = None):
        self.root = Path(root)
        self.meta_path = self.root / self.META_PATH
        self.thumbnails_path = self.root / self.THUMBNAILS_PATH
        self._meta_cache: dict[str, Any] | None = None
        self._thumbnail_cache: dict[str, str] | None = None
        self.variants_path = Path(variants_path) if variants_path is not None else None
        self.variants_lock = RLock()
        self._variants_signature = None
        self._variants_cache = None

    def _variants(self):
        """Called under variants_lock; keep only metadata and byte offsets resident."""
        path = self.variants_path
        if path is None or not path.is_file() or path.with_suffix(".corrupt").exists():
            self._variants_signature = self._variants_cache = None
            return None
        stat = path.stat()
        signature = (stat.st_size, stat.st_mtime_ns)
        if signature != self._variants_signature:
            self._variants_signature = self._variants_cache = None
            try:
                loaded = open_variants(path)
            except (ValueError, KeyError, TypeError):
                path.with_suffix(".corrupt").write_text(
                    "verification failed\n", encoding="utf-8", newline="\n")
                return None
            self._variants_cache = loaded
            self._variants_signature = signature
        return self._variants_cache

    @staticmethod
    def _variant_label(variant: dict) -> str:
        place, weight = variant["place"], variant["weight"]
        if place == "front":
            return "단일"
        return f"UC {weight:g}" if place == "uc" else f"POS {weight:+g}"

    def variants_payload(self, tag: str) -> dict:
        with self.variants_lock:
            loaded = self._variants()
            payload = {"ready": False, "tag": tag, "base": "", "gt_url": "",
                       "variants": [], "download": {"approx_mb": STYLE_VARIANTS_APPROX_MB}}
            if loaded is None:
                return payload
            metadata, _ = loaded
            if tag not in metadata["index"]:
                raise KeyError("Unknown style variants tag")
            info = metadata["index"][tag]
            payload.update(
                ready=True, base=info["base"],
                gt_url=f"/api/thumb/variant-image?gt={quote(info['base'], safe='')}",
                variants=[{
                    "col": v["col"], "place": v["place"], "weight": v["weight"],
                    "label": self._variant_label(v),
                    "url": f"/api/thumb/variant-image?tag={quote(tag, safe='')}&col={quote(v['col'], safe='')}",
                } for v in info["variants"]],
            )
            return payload

    def variant_image(self, tag: str, col: str) -> tuple[bytes, str]:
        with self.variants_lock:
            loaded = self._variants()
            if loaded is not None:
                metadata, index = loaded
                info = metadata["index"].get(tag, {})
                for variant in info.get("variants", []):
                    if variant["col"] == col:
                        return self._variant_bytes(index, variant["key"])
            raise FileNotFoundError("Style variant image not found")

    def variant_gt(self, base: str) -> tuple[bytes, str]:
        with self.variants_lock:
            loaded = self._variants()
            if loaded is not None:
                metadata, index = loaded
                if base in metadata["bases"]:
                    return self._variant_bytes(index, metadata["bases"][base]["gt"])
            raise FileNotFoundError("Style variant GT not found")

    def _variant_bytes(self, index, key: str) -> tuple[bytes, str]:
        try:
            return base64.b64decode(index[key], validate=True), "image/webp"
        except (KeyError, ValueError, OSError):
            self._variants_signature = self._variants_cache = None
            raise FileNotFoundError("Style variant image not found") from None

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
            "bases": self._bases_payload(thumbnail_keys),
        }

    def _bases_payload(self, thumbnail_keys: set[str]) -> dict[str, Any]:
        """생성 기준(version 3) - 이름 · 설정 메모 · GT 이미지 주소. GT 는 썸네일 파일에 `__gt__:<기준>` 키로 들어 있다."""
        bases = self.metadata().get("bases", {})
        payload = {}
        for key, info in (bases.items() if isinstance(bases, dict) else []):
            if not isinstance(info, dict):
                continue
            gt_key = str(info.get("gt") or "")
            payload[str(key)] = {
                "name": str(info.get("name") or key),
                "note": str(info.get("note") or ""),
                "gt_url": f"/api/thumb/image?tag={quote(gt_key, safe='')}" if gt_key in thumbnail_keys else "",
            }
        return payload

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
        # 소제목(version 3 · Novel AI 공식): 썸네일이 있는 태그만 남긴다. single = 가중치 없이 한 장만 뽑은 묶음.
        sections = []
        for section in info.get("sections", []) if isinstance(info.get("sections"), list) else []:
            if not isinstance(section, dict):
                continue
            section_tags = [str(tag) for tag in section.get("tags", []) if str(tag) in thumbnail_data]
            if section_tags:
                sections.append({"name": str(section.get("name") or ""), "tags": section_tags,
                                 "single": bool(section.get("single"))})
        return {
            "key": key,
            "name": str(info.get("name") or key),
            "description": str(info.get("description") or ""),
            "base": str(info.get("base") or ""),
            "sections": sections,
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
