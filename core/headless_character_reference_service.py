"""Headless Character Reference module state service."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from core.headless_image_utils import data_url_payload, image_hash, image_to_png_bytes, thumbnail_b64


class HeadlessCharacterReferenceService:
    def __init__(self, context: Any):
        self.context = context

    def image_data(self, image) -> str:
        from PIL import Image

        source = image.convert("RGBA") if image.mode == "RGBA" else image.convert("RGB")
        width, height = source.size
        aspect_ratio = width / max(1, height)
        ratios = {
            "2:3": (2 / 3, 1024, 1536),
            "3:2": (3 / 2, 1536, 1024),
            "1:1": (1, 1472, 1472),
        }
        _, canvas_width, canvas_height = min(
            ratios.values(),
            key=lambda item: abs(aspect_ratio - item[0]),
        )
        canvas = Image.new("RGB", (canvas_width, canvas_height), (0, 0, 0))
        scale = min(canvas_width / max(1, width), canvas_height / max(1, height))
        new_width = max(1, int(width * scale))
        new_height = max(1, int(height * scale))
        resized = source.resize((new_width, new_height), Image.Resampling.LANCZOS)
        x_offset = (canvas_width - new_width) // 2
        y_offset = (canvas_height - new_height) // 2
        if resized.mode == "RGBA":
            canvas.paste(resized, (x_offset, y_offset), resized)
        else:
            canvas.paste(resized, (x_offset, y_offset))
        return base64.b64encode(image_to_png_bytes(canvas)).decode("ascii")

    def save_storage(self, frame: dict[str, Any]) -> None:
        raw = frame.get("image_bytes")
        file_hash = str(frame.get("file_hash") or "")
        if not raw or not file_hash:
            return
        target = self.context._save_path("character_reference", "images", f"{file_hash}.png")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(raw)

    def frame_from_bytes(
        self,
        image_bytes: bytes,
        *,
        file_name: str = "reference.png",
        file_path: str = "",
        enabled: bool = False,
    ) -> dict[str, Any]:
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as opened:
            image = opened.convert("RGBA")
            png_bytes = image_to_png_bytes(image)
            file_hash = image_hash(png_bytes)
            return {
                "file_hash": file_hash,
                "file_name": file_name or f"{file_hash}.png",
                "file_path": file_path,
                "image_bytes": png_bytes,
                "image_data": self.image_data(image),
                "thumbnail": thumbnail_b64(image),
                "is_enabled": bool(enabled),
                "reference_type": "character&style",
                "strength": 1.0,
                "fidelity": 0.8,
            }

    def module_state(self) -> dict[str, Any]:
        frames = []
        for index, frame in enumerate(self.context.character_reference_frames):
            frames.append({
                "index": index,
                "file_hash": frame.get("file_hash", ""),
                "file_name": frame.get("file_name", ""),
                "is_enabled": bool(frame.get("is_enabled")),
                "reference_type": frame.get("reference_type", "character&style"),
                "strength": float(frame.get("strength", 1.0) or 1.0),
                "fidelity": float(frame.get("fidelity", 0.8) or 0.8),
                "thumbnail": frame.get("thumbnail", ""),
            })
        return self.context._module_state_payload("character_reference", {
            "is_naid45": self.context._is_naid45_model(),
            "frames": frames,
        })

    def set_param(self, key: str, value: Any) -> dict[str, Any] | None:
        context = self.context
        if key == "upload_image":
            image_bytes = base64.b64decode(data_url_payload(str(value or "")))
            context.character_reference_frames.append(
                self.frame_from_bytes(image_bytes, file_name="remote_upload.png")
            )
        elif key.startswith("remove_frame_"):
            index = context._index_from_key(key, "remove_frame_")
            if index is not None and 0 <= index < len(context.character_reference_frames):
                context.character_reference_frames.pop(index)
        elif key.startswith("enable_"):
            index = context._index_from_key(key, "enable_")
            if index is not None and 0 <= index < len(context.character_reference_frames):
                enabling = context._coerce_bool(value)
                context.character_reference_frames[index]["is_enabled"] = enabling
                if enabling:
                    self.save_storage(context.character_reference_frames[index])
                    context._disable_all_vibe_frames()
        elif key.startswith("strength_"):
            index = context._index_from_key(key, "strength_")
            if index is not None and 0 <= index < len(context.character_reference_frames):
                context.character_reference_frames[index]["strength"] = max(0.0, min(1.0, float(value)))
        elif key.startswith("fidelity_"):
            index = context._index_from_key(key, "fidelity_")
            if index is not None and 0 <= index < len(context.character_reference_frames):
                context.character_reference_frames[index]["fidelity"] = max(0.0, min(1.0, float(value)))
        elif key.startswith("ref_type_"):
            index = context._index_from_key(key, "ref_type_")
            ref_type = str(value or "").strip()
            if index is not None and 0 <= index < len(context.character_reference_frames) and ref_type in {"character&style", "character", "style"}:
                context.character_reference_frames[index]["reference_type"] = ref_type
        elif key == "get_storage":
            return self.scan_storage()
        elif key == "apply_storage":
            file_hash = Path(str(value or "")).name
            image_path = context._existing_save_path("character_reference", "images", f"{file_hash}.png")
            if not image_path.exists():
                return context._toast("Character reference storage item not found", level="error")
            image_bytes = image_path.read_bytes()
            frame = self.frame_from_bytes(
                image_bytes,
                file_name=image_path.name,
                file_path=str(image_path),
                enabled=True,
            )
            frame["file_hash"] = file_hash
            context.character_reference_frames.append(frame)
            context._disable_all_vibe_frames()
        else:
            return None
        return self.module_state()

    def scan_storage(self) -> dict[str, Any]:
        items = []
        for images_folder in self.context._existing_save_dirs("character_reference", "images"):
            metadata_folder = images_folder.parent / "metadata"
            for image_path in sorted(images_folder.glob("*.png"), key=lambda path: path.stat().st_mtime, reverse=True)[:50]:
                character_name = ""
                meta_path = metadata_folder / f"{image_path.stem}.json"
                if meta_path.exists():
                    try:
                        meta = json.loads(meta_path.read_text(encoding="utf-8"))
                        if isinstance(meta, dict):
                            character_name = str(meta.get("character_name") or "")
                    except Exception:
                        pass
                file_hash = image_path.stem
                items.append({
                    "file_hash": file_hash,
                    "file_name": image_path.name,
                    "character_name": character_name,
                    "thumbnail": "",
                    "thumbnail_url": (
                        "/api/module-storage/character-reference/thumb"
                        f"?file_hash={quote(file_hash, safe='')}"
                    ),
                })
        return {"type": "storage_list", "module_id": "character_reference", "items": items}

    def disable_all_frames(self) -> None:
        for frame in self.context.character_reference_frames:
            frame["is_enabled"] = False

    def active_params(self) -> dict[str, Any]:
        context = self.context
        if not context._is_naid45_model():
            return {}
        enabled = [frame for frame in context.character_reference_frames if frame.get("is_enabled")]
        if not enabled:
            return {}
        descriptions = []
        images = []
        ie = []
        strengths = []
        fidelities = []
        for frame in enabled:
            image_data = str(frame.get("image_data") or "")
            if not image_data:
                continue
            descriptions.append({
                "caption": {
                    "base_caption": str(frame.get("reference_type") or "character&style"),
                    "char_captions": [],
                },
                "legacy_uc": False,
            })
            images.append(image_data)
            ie.append(1)
            strength = round(max(0.0, min(1.0, float(frame.get("strength", 1.0) or 1.0))) * 20) / 20.0
            fidelity = 1.0 - max(0.0, min(1.0, float(frame.get("fidelity", 0.8) or 0.8)))
            fidelities.append(round(fidelity * 20) / 20.0)
            strengths.append(strength)
        if not descriptions:
            return {}
        return {
            "director_reference_descriptions": descriptions,
            "director_reference_images": images,
            "director_reference_information_extracted": ie,
            "director_reference_strength_values": strengths,
            "director_reference_secondary_strength_values": fidelities,
            "controlnet_strength": 1,
            "inpaintImg2ImgStrength": 1,
            "normalize_reference_strength_multiple": True,
        }
