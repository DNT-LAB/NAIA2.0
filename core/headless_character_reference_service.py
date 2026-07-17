"""Headless Character Reference module state service."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from core.headless_image_utils import data_url_payload, image_hash, image_to_png_bytes, thumbnail_b64


def _as_float(value: Any, default: float) -> float:
    """0.0 같은 유효한 0 값을 보존하는 float 변환(누락/None/비수치만 default)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class HeadlessCharacterReferenceService:
    def __init__(self, context: Any):
        self.context = context

    # ----- 영속 (재시작 복원): CharacterReferenceModule_{mode}.json -----
    def _settings_mode(self) -> str:
        return str(self.context.get_api_mode() or "NAI").upper()

    def _ensure_loaded(self) -> None:
        """첫 접근/모드 변경 시 디스크에서 활성 프레임을 1회 로드한다. 상호배타
        cross-disable이 미로드 상대를 깨우도록 디스크 enabled 상태까지 복원한다."""
        context = self.context
        mode = self._settings_mode()
        if getattr(context, "_character_reference_frames_loaded_mode", None) == mode:
            return
        context._character_reference_frames_loaded_mode = mode
        context.character_reference_frames = self._load_persisted(mode)

    def _load_persisted(self, mode: str) -> list[dict[str, Any]]:
        try:
            path = self.context._existing_save_path(f"CharacterReferenceModule_{mode}.json")
            if not path.exists():
                return []
            data = json.loads(path.read_text(encoding="utf-8"))
            block = data.get(mode) if isinstance(data, dict) else None
            if not isinstance(block, dict):
                block = data if isinstance(data, dict) else {}
            raw_frames = block.get("frames")
            frames: list[dict[str, Any]] = []
            if isinstance(raw_frames, list):
                for raw in raw_frames:
                    frame = self._frame_from_persisted(raw)
                    if frame is not None:
                        frames.append(frame)
            return frames
        except Exception as exc:
            print(f"[ERROR] Character Reference settings load failed: {exc}")
            return []

    def _frame_from_persisted(self, raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None
        file_hash = str(raw.get("file_hash") or "")
        ref_type = str(raw.get("reference_type") or "character&style")
        if ref_type not in {"character&style", "character", "style"}:
            ref_type = "character&style"
        image_bytes = b""
        image_data = ""
        thumbnail = ""
        # active_params는 image_data가 필수 → enabled 프레임은 enable 시 save_storage로
        # storage png가 있으므로 거기서 복원. 없으면 빈값(active_params가 skip).
        if file_hash:
            try:
                image_path = self.context._existing_save_path(
                    "character_reference", "images", f"{file_hash}.png"
                )
                if image_path.exists():
                    from PIL import Image

                    image_bytes = image_path.read_bytes()
                    with Image.open(image_path) as image:
                        image_data = self.image_data(image)
                        thumbnail = thumbnail_b64(image.convert("RGBA"))
            except Exception:
                image_bytes = b""
                image_data = ""
                thumbnail = ""
        return {
            "file_hash": file_hash,
            "file_name": str(raw.get("file_name") or (f"{file_hash}.png" if file_hash else "reference.png")),
            "file_path": str(raw.get("file_path") or ""),
            "image_bytes": image_bytes,
            "image_data": image_data,
            "thumbnail": thumbnail,
            "is_enabled": bool(raw.get("is_enabled")),
            "reference_type": ref_type,
            "strength": _as_float(raw.get("strength"), 1.0),
            "fidelity": _as_float(raw.get("fidelity"), 0.8),
        }

    @staticmethod
    def _persistable_frame(frame: dict[str, Any]) -> dict[str, Any]:
        return {
            "file_hash": str(frame.get("file_hash") or ""),
            "file_name": str(frame.get("file_name") or ""),
            "file_path": str(frame.get("file_path") or ""),
            "is_enabled": bool(frame.get("is_enabled")),
            "reference_type": str(frame.get("reference_type") or "character&style"),
            "strength": _as_float(frame.get("strength"), 1.0),
            "fidelity": _as_float(frame.get("fidelity"), 0.8),
        }

    def _persist(self) -> None:
        context = self.context
        mode = self._settings_mode()
        try:
            frames = [self._persistable_frame(frame) for frame in context.character_reference_frames]
            payload = {mode: {"frames": frames}}
            path = context._save_path(f"CharacterReferenceModule_{mode}.json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=4), encoding="utf-8")
        except Exception as exc:
            print(f"[ERROR] Character Reference settings save failed: {exc}")
        # 레퍼런스 인셋 강제 종료(사용자 계약): CR이 하나라도 활성화되면 인셋 핀을
        # 해제한다 - 두 기법은 개념이 겹쳐 함께 켜면 안 된다. _persist는 모든 CR
        # 변이(enable/upload/apply_storage/에셋 attach)의 공통 통과점이다.
        try:
            if any(frame.get("is_enabled") for frame in context.character_reference_frames):
                asset_getter = getattr(context, "_character_asset_service", None)
                if callable(asset_getter) and asset_getter().clear_reference_inset_pin():
                    print("[CharacterAsset] reference inset pin released - Character Reference enabled")
        except Exception:
            pass

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
        self._ensure_loaded()
        frames = []
        for index, frame in enumerate(self.context.character_reference_frames):
            frames.append({
                "index": index,
                "file_hash": frame.get("file_hash", ""),
                "file_name": frame.get("file_name", ""),
                "is_enabled": bool(frame.get("is_enabled")),
                "reference_type": frame.get("reference_type", "character&style"),
                "strength": _as_float(frame.get("strength"), 1.0),
                "fidelity": _as_float(frame.get("fidelity"), 0.8),
                "thumbnail": frame.get("thumbnail", ""),
            })
        return self.context._module_state_payload("character_reference", {
            "is_naid45": self.context._is_naid45_model(),
            "frames": frames,
        })

    def set_param(self, key: str, value: Any) -> dict[str, Any] | None:
        context = self.context
        self._ensure_loaded()
        if key == "upload_image":
            image_bytes = base64.b64decode(data_url_payload(str(value or "")))
            context.character_reference_frames.append(
                self.frame_from_bytes(image_bytes, file_name="remote_upload.png")
            )
        elif key.startswith("remove_frame_"):
            index = context._index_from_key(key, "remove_frame_")
            if index is not None and 0 <= index < len(context.character_reference_frames):
                context.character_reference_frames.pop(index)
        elif key == "clear_frames":
            # 프레임만 비운다 - storage(save/character_reference/images)는 보존.
            context.character_reference_frames.clear()
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
        self._persist()
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
        # 상호배타 cross-disable의 영속 진입점(미로드 상대도 깨워 디스크 enabled 차단).
        self._ensure_loaded()
        changed = False
        for frame in self.context.character_reference_frames:
            if frame.get("is_enabled"):
                frame["is_enabled"] = False
                changed = True
        if changed:
            self._persist()

    def active_params(self) -> dict[str, Any]:
        context = self.context
        self._ensure_loaded()
        if not context._is_naid45_model():
            return {}
        enabled = [frame for frame in list(context.character_reference_frames) if frame.get("is_enabled")]
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
            strength = round(max(0.0, min(1.0, _as_float(frame.get("strength"), 1.0))) * 20) / 20.0
            fidelity = 1.0 - max(0.0, min(1.0, _as_float(frame.get("fidelity"), 0.8)))
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
