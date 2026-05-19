"""PyQt-free result and history state for the headless Remote Web runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import io
import uuid
from typing import Any

from PIL import Image

from core import result_image_payload_service as result_images


HISTORY_ITEM_PREFIX = "__history_item__/"


@dataclass
class HeadlessHistoryItem:
    image: Image.Image
    raw_bytes: bytes
    webp_bytes: bytes
    generation_params: dict[str, Any]
    prompt_context: dict[str, Any]
    source_row: Any = None
    api_metadata: dict[str, Any] = field(default_factory=dict)
    filepath: str = ""
    history_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def rel_path(self) -> str:
        return f"{HISTORY_ITEM_PREFIX}{self.history_id}"

    @property
    def filename(self) -> str:
        timestamp = self.created_at.strftime("%Y%m%d_%H%M%S")
        return f"naia_headless_{timestamp}_{self.history_id[:8]}.png"


@dataclass
class HeadlessStoredResult:
    item: HeadlessHistoryItem
    image_meta: dict[str, Any]
    metadata_payload: dict[str, Any]


class HeadlessResultStore:
    """Stores latest result, history entries, and image export payloads."""

    def __init__(self, max_items: int = 200):
        self.max_items = max(1, int(max_items))
        self._items: list[HeadlessHistoryItem] = []
        self.latest_item: HeadlessHistoryItem | None = None
        self.latest_webp: bytes | None = None
        self.latest_metadata_payload: dict[str, Any] | None = None

    def add_api_result(self, api_result: dict[str, Any], request) -> HeadlessStoredResult:
        image = self._coerce_image(api_result)
        raw_bytes = self._coerce_raw_bytes(api_result, image)
        webp_bytes = self._image_to_webp(image)
        params = dict(getattr(request, "params", {}) or {})
        params.pop("credential", None)
        prompt_context = {
            "main_prompt": params.get("input", ""),
            "final_prompt": params.get("input", ""),
            "negative_prompt": params.get("negative_prompt", ""),
        }
        item = HeadlessHistoryItem(
            image=image,
            raw_bytes=raw_bytes,
            webp_bytes=webp_bytes,
            generation_params=params,
            prompt_context=prompt_context,
            source_row=getattr(request, "source_row", None),
            api_metadata=dict(api_result.get("api_metadata", {}) or {}),
        )
        image_meta = self._build_image_meta(item)
        metadata_payload = self._build_metadata_payload(item, image_meta)
        self._items.insert(0, item)
        del self._items[self.max_items:]
        self.latest_item = item
        self.latest_webp = webp_bytes
        self.latest_metadata_payload = metadata_payload
        return HeadlessStoredResult(item=item, image_meta=image_meta, metadata_payload=metadata_payload)

    def get_item(self, history_id: str) -> HeadlessHistoryItem | None:
        history_id = str(history_id or "")
        for item in self._items:
            if item.history_id == history_id:
                return item
        return None

    def history_total(self) -> int:
        return len(self._items)

    def history_summary(self, item: HeadlessHistoryItem, index: int = 0) -> dict[str, Any]:
        mtime = item.created_at.timestamp()
        return {
            "rel_path": item.rel_path,
            "history_id": item.history_id,
            "filename": item.filename,
            "file_path": "",
            "source": "memory",
            "size_bytes": len(item.raw_bytes or item.webp_bytes or b""),
            "mtime": mtime,
            "mtime_iso": item.created_at.isoformat(),
            "index": index,
            "thumb_url": f"/api/history/thumb/{item.history_id}",
            "image_url": f"/api/history/image/{item.history_id}",
            "metadata_url": f"/api/history/meta/{item.history_id}",
        }

    def history_list(self, page: int = 0, per_page: int = 30) -> dict[str, Any]:
        page = max(0, int(page or 0))
        per_page = min(100, max(1, int(per_page or 30)))
        start = page * per_page
        selected = self._items[start:start + per_page]
        return {
            "images": [
                self.history_summary(item, index=start + offset)
                for offset, item in enumerate(selected)
            ],
            "total": len(self._items),
            "page": page,
            "per_page": per_page,
        }

    def latest_image_payload(self) -> tuple[bytes, str]:
        if not self.latest_webp:
            raise FileNotFoundError("No image generated yet")
        return self.latest_webp, "image/webp"

    def current_png_payload(self) -> tuple[bytes, str]:
        if not self.latest_item:
            raise FileNotFoundError("No image generated yet")
        return result_images.history_item_png_payload(self.latest_item, label=self.latest_item.filename)

    def history_image_payload(self, history_id: str) -> tuple[bytes, str]:
        item = self.get_item(history_id)
        if item is None:
            raise FileNotFoundError("History item not found")
        return result_images.history_item_image_payload(item)

    def history_thumb_payload(self, history_id: str, max_side: int = 0) -> bytes:
        item = self.get_item(history_id)
        if item is None:
            raise FileNotFoundError("History item not found")
        return result_images.memory_history_thumbnail_payload(item, max_side)

    def history_meta_payload(self, history_id: str, include_full: bool = False) -> dict[str, Any]:
        item = self.get_item(history_id)
        if item is None:
            raise FileNotFoundError("History item not found")
        return result_images.history_item_meta_payload(item, include_full=include_full)

    def viewer_new_image_payload(self, item: HeadlessHistoryItem) -> dict[str, Any]:
        payload = self.history_summary(item, index=0)
        payload.update({"type": "viewer_new_image", "total": len(self._items)})
        return payload

    def _build_image_meta(self, item: HeadlessHistoryItem) -> dict[str, Any]:
        params = item.generation_params
        return {
            "width": item.image.width,
            "height": item.image.height,
            "size_kb": len(item.webp_bytes) // 1024,
            "timestamp": item.created_at.isoformat(),
            "can_enhance": bool(params),
            "prompt": params.get("input", ""),
            "negative_prompt": params.get("negative_prompt", ""),
            "seed": params.get("seed", ""),
            "steps": params.get("steps", ""),
            "cfg_scale": params.get("cfg_scale", ""),
            "sampler": params.get("sampler", ""),
            "model": params.get("model", ""),
            "remote_queue_source": str(params.get("_remote_queue_source") or ""),
        }

    def _build_metadata_payload(self, item: HeadlessHistoryItem, image_meta: dict[str, Any]) -> dict[str, Any]:
        summary = {
            "width": item.image.width,
            "height": item.image.height,
            "mode": item.image.mode,
            "size_kb": len(item.webp_bytes) // 1024,
            "prompt": item.generation_params.get("input", ""),
            "negative": item.generation_params.get("negative_prompt", ""),
            "seed": item.generation_params.get("seed", ""),
            "steps": item.generation_params.get("steps", ""),
            "sampler": item.generation_params.get("sampler", ""),
            "cfg_scale": item.generation_params.get("cfg_scale", ""),
            "model": item.generation_params.get("model", ""),
        }
        return {
            "source": "current",
            "label": "Current Result",
            "summary": {key: value for key, value in summary.items() if value not in ("", None)},
            "raw": {
                "image": {
                    "width": item.image.width,
                    "height": item.image.height,
                    "mode": item.image.mode,
                    "format": item.image.format,
                    "size_kb": len(item.webp_bytes) // 1024,
                },
                "generation_params": item.generation_params,
                "prompt_context": item.prompt_context,
                "api_metadata": item.api_metadata,
                "image_meta": image_meta,
            },
            "has_metadata": True,
        }

    @staticmethod
    def _coerce_image(api_result: dict[str, Any]) -> Image.Image:
        image = api_result.get("image")
        if image is not None:
            image.load()
            return image.copy()
        raw_bytes = api_result.get("raw_bytes")
        if raw_bytes:
            with Image.open(io.BytesIO(raw_bytes)) as opened:
                opened.load()
                return opened.copy()
        raise ValueError("API result does not include an image")

    @staticmethod
    def _coerce_raw_bytes(api_result: dict[str, Any], image: Image.Image) -> bytes:
        raw_bytes = api_result.get("raw_bytes")
        if isinstance(raw_bytes, bytes):
            return raw_bytes
        if isinstance(raw_bytes, bytearray):
            return bytes(raw_bytes)
        return result_images.pil_image_to_png_bytes(image)

    @staticmethod
    def _image_to_webp(image: Image.Image) -> bytes:
        buffer = io.BytesIO()
        image.save(buffer, format="WEBP", quality=85, method=0)
        return buffer.getvalue()


__all__ = [
    "HISTORY_ITEM_PREFIX",
    "HeadlessHistoryItem",
    "HeadlessResultStore",
    "HeadlessStoredResult",
]
