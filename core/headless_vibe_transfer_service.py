"""Headless Vibe Transfer module state service."""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from core.headless_image_utils import data_url_payload, image_hash, image_to_png_bytes, thumbnail_b64
from core.nai_vibe_limits import MAX_NAI_VIBE_REFERENCES, NAI_VIBE_INCLUDED_REFERENCES


class HeadlessVibeTransferService:
    def __init__(self, context: Any):
        self.context = context

    @staticmethod
    def _is_float_like(value: Any) -> bool:
        try:
            float(value)
            return True
        except Exception:
            return False

    def disable_all_frames(self) -> None:
        for frame in self.context.vibe_transfer_frames:
            frame["is_enabled"] = False

    def frame_from_bytes(
        self,
        image_bytes: bytes,
        *,
        file_name: str = "vibe.png",
        file_path: str = "",
        enabled: bool = True,
    ) -> dict[str, Any]:
        from PIL import Image

        context = self.context
        with Image.open(io.BytesIO(image_bytes)) as opened:
            image = opened.convert("RGBA")
            png_bytes = image_to_png_bytes(image)
            file_hash = image_hash(png_bytes)
            image_data = base64.b64encode(png_bytes).decode("ascii")
            encodings: dict[str, str] = {}
            storage_json = context._existing_save_path(
                "vibe_transfer",
                context._current_model_key(),
                f"{file_hash}.json",
            )
            if storage_json.exists():
                try:
                    data = json.loads(storage_json.read_text(encoding="utf-8"))
                    raw_encodings = data.get("encodings") if isinstance(data, dict) else {}
                    if isinstance(raw_encodings, dict):
                        encodings = {str(k): str(v) for k, v in raw_encodings.items() if v}
                except Exception:
                    encodings = {}
            if context._is_naid3_model() and not encodings:
                encodings = {"1.0": image_data}
            return {
                "file_hash": file_hash,
                "file_name": file_name or f"{file_hash}.png",
                "file_path": file_path,
                "image_bytes": png_bytes,
                "image_data": image_data,
                "thumbnail": thumbnail_b64(image),
                "is_enabled": bool(enabled),
                "is_no_image": False,
                "is_naid3": context._is_naid3_model(),
                "reference_strength": 0.6,
                "information_extracted": 1.0,
                "vibe_encodings": encodings,
                "storage_type": "",
            }

    def module_state(self) -> dict[str, Any]:
        context = self.context
        frames = []
        enabled_count = 0
        strength_total = 0.0
        for index, frame in enumerate(context.vibe_transfer_frames):
            encodings = frame.get("vibe_encodings") if isinstance(frame.get("vibe_encodings"), dict) else {}
            encoding_keys = sorted(float(key) for key in encodings.keys() if self._is_float_like(key))
            information_extracted = float(frame.get("information_extracted", 1.0) or 1.0)
            active_encoding = min(encoding_keys, key=lambda key: abs(key - information_extracted)) if encoding_keys else None
            has_encoding = active_encoding is not None and abs(active_encoding - information_extracted) < 1e-9
            if frame.get("is_enabled") and encodings:
                enabled_count += 1
                strength_total += float(frame.get("reference_strength", 0.6) or 0.6)
            frames.append({
                "index": index,
                "file_hash": frame.get("file_hash", ""),
                "file_name": frame.get("file_name", ""),
                "is_enabled": bool(frame.get("is_enabled")),
                "is_no_image": bool(frame.get("is_no_image")),
                "is_naid3": context._is_naid3_model(),
                "reference_strength": float(frame.get("reference_strength", 0.6) or 0.6),
                "information_extracted": information_extracted,
                "has_encoding": has_encoding,
                "active_encoding": active_encoding,
                "encoding_in_progress": False,
                "encoding_keys": encoding_keys,
                "thumbnail": frame.get("thumbnail", ""),
            })
        return context._module_state_payload("vibe_transfer", {
            "normalize": bool(context.vibe_transfer_normalize),
            "enabled_count": enabled_count,
            "frame_count": len(context.vibe_transfer_frames),
            "max_frames": MAX_NAI_VIBE_REFERENCES,
            "included_frames": NAI_VIBE_INCLUDED_REFERENCES,
            "extra_cost_count": max(0, enabled_count - NAI_VIBE_INCLUDED_REFERENCES),
            "strength_total": round(strength_total, 3),
            "strength_warning": enabled_count > 1 and strength_total > 1.0 and not context.vibe_transfer_normalize,
            "frames": frames,
        })

    def set_param(self, key: str, value: Any) -> dict[str, Any] | None:
        context = self.context
        if key == "upload_image":
            if len(context.vibe_transfer_frames) >= MAX_NAI_VIBE_REFERENCES:
                return context._toast(f"Maximum {MAX_NAI_VIBE_REFERENCES} Vibe Transfer frames allowed", level="error")
            image_bytes = base64.b64decode(data_url_payload(str(value or "")))
            context.vibe_transfer_frames.append(self.frame_from_bytes(image_bytes, file_name="remote_vibe.png"))
            context._disable_all_character_reference_frames()
        elif key.startswith("remove_frame_"):
            index = context._index_from_key(key, "remove_frame_")
            if index is not None and 0 <= index < len(context.vibe_transfer_frames):
                context.vibe_transfer_frames.pop(index)
        elif key.startswith("enable_"):
            index = context._index_from_key(key, "enable_")
            if index is not None and 0 <= index < len(context.vibe_transfer_frames):
                enabling = context._coerce_bool(value)
                context.vibe_transfer_frames[index]["is_enabled"] = enabling
                if enabling:
                    context._disable_all_character_reference_frames()
        elif key.startswith("ref_strength_"):
            index = context._index_from_key(key, "ref_strength_")
            if index is not None and 0 <= index < len(context.vibe_transfer_frames):
                context.vibe_transfer_frames[index]["reference_strength"] = max(-1.0, min(1.0, float(value)))
        elif key.startswith("info_extracted_"):
            index = context._index_from_key(key, "info_extracted_")
            if index is not None and 0 <= index < len(context.vibe_transfer_frames):
                context.vibe_transfer_frames[index]["information_extracted"] = max(0.01, min(1.0, round(float(value), 2)))
        elif key == "normalize":
            context.vibe_transfer_normalize = context._coerce_bool(value)
        elif key.startswith("encode_"):
            return context._toast("Headless Vibe encoding is not available yet; use stored encoded Vibe entries.", level="error")
        elif key == "get_storage":
            return self.scan_storage()
        elif key == "apply_storage":
            applied = self.apply_storage(str(value or ""))
            if isinstance(applied, dict):
                return applied
        elif key == "cluster_list":
            return self.scan_clusters()
        elif key == "cluster_load":
            loaded = self.load_cluster(str(value or ""))
            if isinstance(loaded, dict):
                return loaded
        elif key in {"cluster_save", "cluster_delete", "cluster_rename", "cluster_thumbnail", "restore_metadata"}:
            return context._toast(f"Vibe Transfer action is not available in headless yet: {key}", level="info")
        else:
            return None
        return self.module_state()

    def scan_storage(self) -> dict[str, Any]:
        models: dict[str, list[dict[str, Any]]] = {}
        context = self.context
        for vibe_folder in context._existing_save_dirs("vibe_transfer"):
            for model_dir in sorted(path for path in vibe_folder.iterdir() if path.is_dir()):
                images_folder = model_dir / "images"
                items = []
                for json_file in sorted(model_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)[:50]:
                    try:
                        data = json.loads(json_file.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    if not isinstance(data, dict) or data.get("volatile"):
                        continue
                    raw_encodings = data.get("encodings") if isinstance(data.get("encodings"), dict) else {}
                    encoding_keys = sorted(float(key) for key in raw_encodings.keys() if self._is_float_like(key))
                    if not encoding_keys:
                        continue
                    file_hash = str(data.get("file_hash") or json_file.stem)
                    image_path = images_folder / f"{file_hash}.png"
                    if data.get("is_no_image") or data.get("storage_type") == "metadata_vibe" or not image_path.exists():
                        continue
                    items.append({
                        "file_hash": file_hash,
                        "file_name": str(data.get("file_name") or image_path.name),
                        "encoding_keys": encoding_keys,
                        "thumbnail": "",
                        "thumbnail_url": (
                            "/api/module-storage/vibe/thumb"
                            f"?model={quote(model_dir.name, safe='')}"
                            f"&file_hash={quote(file_hash, safe='')}"
                        ),
                    })
                if items:
                    models[model_dir.name] = items
        return {
            "type": "storage_list",
            "module_id": "vibe_transfer",
            "models": models,
            "current_model": context._current_model_key(),
        }

    def apply_storage(self, value: str) -> dict[str, Any] | None:
        context = self.context
        if len(context.vibe_transfer_frames) >= MAX_NAI_VIBE_REFERENCES:
            return context._toast(f"Maximum {MAX_NAI_VIBE_REFERENCES} Vibe Transfer frames allowed", level="error")
        parts = str(value or "").split("|")
        if len(parts) < 3:
            return context._toast("Invalid Vibe storage request", level="error")
        model, file_hash, ie_text = parts[0], Path(parts[1]).name, parts[2]
        json_path = context._existing_save_path("vibe_transfer", model, f"{file_hash}.json")
        if not json_path.exists():
            return context._toast("Vibe storage item not found", level="error")
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            raw_encodings = data.get("encodings") if isinstance(data.get("encodings"), dict) else {}
            encodings = {str(k): str(v) for k, v in raw_encodings.items() if v}
            if not encodings:
                return context._toast("Stored Vibe encoding not found", level="error")
            selected_ie = float(ie_text)
            closest_ie = min((float(key) for key in encodings.keys()), key=lambda key: abs(key - selected_ie))
            image_path = context._existing_save_path("vibe_transfer", model, "images", f"{file_hash}.png")
            thumb = ""
            image_bytes = b""
            image_data = ""
            if image_path.exists():
                image_bytes = image_path.read_bytes()
                try:
                    from PIL import Image

                    with Image.open(image_path) as image:
                        thumb = thumbnail_b64(image)
                        image_data = base64.b64encode(
                            image_to_png_bytes(image.convert("RGBA"))
                        ).decode("ascii")
                except Exception:
                    pass
            frame = {
                "file_hash": file_hash,
                "file_name": str(data.get("file_name") or image_path.name or f"{file_hash}.png"),
                "file_path": str(data.get("file_path") or image_path),
                "image_bytes": image_bytes,
                "image_data": image_data,
                "thumbnail": thumb,
                "is_enabled": True,
                "is_no_image": bool(data.get("is_no_image")) or data.get("storage_type") == "metadata_vibe",
                "is_naid3": "NAID3" in model,
                "reference_strength": float(data.get("reference_strength", 0.6) or 0.6),
                "information_extracted": closest_ie,
                "vibe_encodings": encodings,
                "storage_type": str(data.get("storage_type") or ""),
                "source_model": model,
            }
            context.vibe_transfer_frames.append(frame)
            context._disable_all_character_reference_frames()
            return None
        except Exception as exc:
            return context._toast(f"Failed to load Vibe storage: {exc}", level="error")

    def scan_clusters(self) -> dict[str, Any]:
        from core.vibe_cluster_resolver import list_vibe_clusters

        context = self.context
        root = context._existing_save_path("vibe_transfer_clusters")
        items = []
        thumb_root = root / "thumbnails"
        for data in list_vibe_clusters(root):
            cluster_id = str(data.get("_cluster_id") or data.get("id") or "")
            thumb = ""
            thumb_path = thumb_root / f"{cluster_id}.jpg"
            if thumb_path.exists():
                try:
                    thumb = base64.b64encode(thumb_path.read_bytes()).decode("ascii")
                except Exception:
                    thumb = ""
            frames = data.get("frames") if isinstance(data.get("frames"), list) else []
            enabled = sum(1 for frame in frames if isinstance(frame, dict) and frame.get("is_enabled", True))
            items.append({
                "id": cluster_id,
                "name": str(data.get("_cluster_name") or data.get("name") or cluster_id),
                "description": str(data.get("description") or ""),
                "model": str(data.get("model") or ""),
                "frame_count": len(frames),
                "enabled_count": enabled,
                "thumbnail": thumb,
            })
        return {
            "type": "storage_list",
            "module_id": "vibe_cluster",
            "items": items,
            "current_frame_count": len(context.vibe_transfer_frames),
            "max_frames": MAX_NAI_VIBE_REFERENCES,
        }

    def load_cluster(self, value: str) -> dict[str, Any] | None:
        from core.vibe_cluster_resolver import resolve_vibe_cluster

        context = self.context
        try:
            payload = json.loads(value or "{}")
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        cluster_id = str(payload.get("id") or "")
        mode = str(payload.get("mode") or "append")
        root = context._existing_save_path("vibe_transfer_clusters")
        try:
            data = resolve_vibe_cluster(cluster_id, root)
        except Exception as exc:
            return context._toast(str(exc), level="error")
        if mode == "clean":
            context.vibe_transfer_frames.clear()
        frames = data.get("frames") if isinstance(data.get("frames"), list) else []
        for frame_data in frames:
            if len(context.vibe_transfer_frames) >= MAX_NAI_VIBE_REFERENCES:
                break
            encodings = frame_data.get("encodings") if isinstance(frame_data.get("encodings"), dict) else {}
            if not encodings:
                continue
            context.vibe_transfer_frames.append({
                "file_hash": str(
                    frame_data.get("file_hash")
                    or hashlib.sha256(json.dumps(frame_data, sort_keys=True).encode("utf-8")).hexdigest()[:16]
                ),
                "file_name": str(frame_data.get("file_name") or "cluster_vibe"),
                "file_path": str(frame_data.get("file_path") or ""),
                "image_bytes": b"",
                "image_data": "",
                "thumbnail": "",
                "is_enabled": bool(frame_data.get("is_enabled", True)),
                "is_no_image": True,
                "is_naid3": context._is_naid3_model(),
                "reference_strength": float(frame_data.get("reference_strength", 0.6) or 0.6),
                "information_extracted": float(frame_data.get("information_extracted", 1.0) or 1.0),
                "vibe_encodings": {str(k): str(v) for k, v in encodings.items() if v},
                "storage_type": "cluster_vibe",
                "source_model": str(data.get("model") or ""),
            })
        context._disable_all_character_reference_frames()
        return None

    def active_params(self) -> dict[str, Any]:
        context = self.context
        reference_images = []
        reference_strengths = []
        reference_info = []
        for frame in context.vibe_transfer_frames:
            encodings = frame.get("vibe_encodings") if isinstance(frame.get("vibe_encodings"), dict) else {}
            if not frame.get("is_enabled") or not encodings:
                continue
            try:
                target_ie = float(frame.get("information_extracted", 1.0) or 1.0)
                closest_key = min((float(key) for key in encodings.keys()), key=lambda key: abs(key - target_ie))
            except Exception:
                continue
            encoded = encodings.get(str(closest_key)) or encodings.get(f"{closest_key:g}") or encodings.get(f"{closest_key:.1f}")
            if not encoded:
                for key, value in encodings.items():
                    try:
                        if abs(float(key) - closest_key) < 1e-9:
                            encoded = value
                            break
                    except Exception:
                        continue
            if not encoded:
                continue
            reference_images.append(encoded)
            reference_strengths.append(float(frame.get("reference_strength", 0.6) or 0.6))
            reference_info.append(closest_key)
        if not reference_images:
            return {}
        params = {
            "normalize_reference_strength_multiple": bool(context.vibe_transfer_normalize),
            "reference_image_multiple": reference_images,
            "reference_strength_multiple": reference_strengths,
        }
        if context._is_naid3_model():
            params["reference_information_extracted_multiple"] = reference_info
        return params
