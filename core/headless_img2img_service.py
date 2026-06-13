"""Headless Img2Img/Inpaint module state service.

This keeps Remote Web image-input behavior outside the WebSessionContext
container while preserving the existing context-facing API.
"""

from __future__ import annotations

import base64
import io
from typing import Any

from core.headless_image_utils import data_url_payload, image_to_png_bytes
from core.resolution_utils import MAX_1MP_PIXELS, snap_resolution_to_multiple


class HeadlessImg2ImgService:
    def __init__(self, context: Any):
        self.context = context

    @staticmethod
    def _image_to_png_bytes(image) -> bytes:
        return image_to_png_bytes(image)

    @staticmethod
    def _image_preview_data_url(image, max_side: int = 640) -> tuple[str, int, int]:
        from PIL import Image

        preview = image.copy()
        preview.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        if preview.mode not in ("RGB", "RGBA"):
            preview = preview.convert("RGBA")
        buffer = io.BytesIO()
        preview.save(buffer, format="PNG", optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}", int(preview.width), int(preview.height)

    @staticmethod
    def _best_resolution(width: int, height: int, max_pixels: int = MAX_1MP_PIXELS) -> tuple[int, int]:
        ratio = max(1, int(width)) / max(1, int(height))
        best_w = int((max_pixels * ratio) ** 0.5)
        best_h = int((max_pixels / ratio) ** 0.5)
        best_w = (best_w // 64) * 64
        best_h = (best_h // 64) * 64
        while best_w * best_h > max_pixels:
            best_w -= 64
            best_h = int(best_w / ratio)
            best_h = (best_h // 64) * 64
        best_w = max(best_w, 64)
        best_h = max(best_h, 64)
        # 극단 종횡비(예: 1x300)에서는 위 64px 하한 클램프가 곱을 max_pixels 너머로
        # 되밀 수 있다. 긴 변을 64배수로 다시 줄여 곱<=max_pixels 계약을 지킨다.
        if best_w * best_h > max_pixels:
            if best_w >= best_h:
                best_w = max(64, ((max_pixels // best_h) // 64) * 64)
            else:
                best_h = max(64, ((max_pixels // best_w) // 64) * 64)
        return best_w, best_h

    @staticmethod
    def _provider_safe_original_resolution(
        width: int,
        height: int,
        max_pixels: int = MAX_1MP_PIXELS,
    ) -> tuple[int, int]:
        """Keep original size as closely as NAI allows without filling to 1MP."""
        width = max(1, int(width))
        height = max(1, int(height))
        snapped_w, snapped_h = snap_resolution_to_multiple(width, height, 64)
        if snapped_w * snapped_h <= max_pixels:
            return snapped_w, snapped_h

        scale = min(1.0, (max_pixels / max(1, width * height)) ** 0.5)
        target_w = max(64, (max(1, int(width * scale)) // 64) * 64)
        target_h = max(64, (max(1, int(height * scale)) // 64) * 64)
        if target_w * target_h > max_pixels:
            if target_w >= target_h:
                target_w = max(64, ((max_pixels // target_h) // 64) * 64)
            else:
                target_h = max(64, ((max_pixels // target_w) // 64) * 64)
        return target_w, target_h

    def _normalize_source_image(self, image):
        from PIL import Image

        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA")
        width, height = image.size
        if width % 64 == 0 and height % 64 == 0 and width * height <= MAX_1MP_PIXELS:
            return image
        new_w, new_h = self._provider_safe_original_resolution(width, height)
        if (new_w, new_h) == (width, height):
            return image
        return image.resize((new_w, new_h), Image.Resampling.LANCZOS)

    def _resize_to_1mp(self, image):
        """이미지와 가장 가까운 비율의 64배수 ~1MP 해상도로 맞춘다 (업스케일 포함)."""
        from PIL import Image

        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA")
        target = self._best_resolution(image.width, image.height)
        if target == image.size:
            return image
        return image.resize(target, Image.Resampling.LANCZOS)

    def _session_image_from_bytes(self, source_bytes: bytes, *, resize_1mp: bool):
        from PIL import Image

        with Image.open(io.BytesIO(source_bytes)) as opened:
            image = opened.convert("RGBA")
        return self._resize_to_1mp(image) if resize_1mp else self._normalize_source_image(image)

    def open_session_from_bytes(
        self,
        image_bytes: bytes,
        *,
        label: str = "Result Image",
        mode: str = "img2img",
        generation_params: dict[str, Any] | None = None,
        prompt_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = self.context
        if not image_bytes:
            raise ValueError("Image data is unavailable")
        image = self._session_image_from_bytes(bytes(image_bytes), resize_1mp=True)
        png_bytes = self._image_to_png_bytes(image)
        preview, preview_width, preview_height = self._image_preview_data_url(image)
        context._img2img_window_counter += 1
        params = dict(generation_params or {})
        prompt_ctx = dict(prompt_context or {})
        main_prompt = str(
            prompt_ctx.get("main_prompt")
            or prompt_ctx.get("final_prompt")
            or params.get("input")
            or params.get("_raw_input")
            or context.prompt_text
            or ""
        )
        negative_prompt = str(params.get("negative_prompt") or params.get("uc") or context.negative_prompt_text or "")
        clean_mode = "inpaint" if str(mode or "").lower() == "inpaint" else "img2img"
        context.img2img_session = {
            "active": True,
            "window_id": context._img2img_window_counter,
            "mode": clean_mode,
            "source_label": str(label or "Result Image"),
            "source_bytes": bytes(image_bytes),
            "resize_1mp": True,
            "image_bytes": png_bytes,
            "width": int(image.width),
            "height": int(image.height),
            "preview": preview,
            "preview_width": preview_width,
            "preview_height": preview_height,
            "has_mask": False,
            "mask_bytes": b"",
            "mask_preview": "",
            "strength": 99 if clean_mode == "inpaint" else 70,
            "noise": 0,
            "repeat": 1,
            "main_prompt": main_prompt,
            "negative_prompt": negative_prompt,
            "characters": [],
        }
        return self.module_state()

    @staticmethod
    def strength_value(raw: Any) -> float:
        try:
            value = int(raw)
        except Exception:
            value = 70
        return 1.0 if value == 99 else max(1, min(99, value)) / 100.0

    def module_state(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        context = self.context
        state = context.img2img_session if isinstance(context.img2img_session, dict) else {}
        if not state.get("active"):
            payload = context._module_state_payload("img2img", {"active": False})
            if extra:
                payload.update(extra)
            return payload
        characters = [
            {
                "id": index + 1,
                "active": bool(character.get("active", True)),
                "prompt": str(character.get("prompt") or ""),
                "uc": str(character.get("uc") or ""),
            }
            for index, character in enumerate(state.get("characters") or [])
        ]
        mode = str(state.get("mode") or "img2img")
        payload = context._module_state_payload("img2img", {
            "active": True,
            "window_id": int(state.get("window_id", 0) or 0),
            "mode": mode,
            "source_label": str(state.get("source_label") or "Result Image"),
            "width": int(state.get("width", 0) or 0),
            "height": int(state.get("height", 0) or 0),
            "preview": str(state.get("preview") or ""),
            "preview_width": int(state.get("preview_width", 0) or 0),
            "preview_height": int(state.get("preview_height", 0) or 0),
            "has_mask": bool(state.get("has_mask")),
            "mask_preview": str(state.get("mask_preview") or ""),
            "strength": int(state.get("strength", 70) or 70),
            "strength_value": self.strength_value(state.get("strength", 70)),
            "noise": int(state.get("noise", 0) or 0),
            "noise_value": max(0, min(99, int(state.get("noise", 0) or 0))) / 100.0,
            "repeat": int(state.get("repeat", 1) or 1),
            "resize_1mp": bool(state.get("resize_1mp", True)),
            "main_prompt": str(state.get("main_prompt") or ""),
            "negative_prompt": str(state.get("negative_prompt") or ""),
            "characters": characters,
            "requires_mask": mode == "inpaint" and not bool(state.get("has_mask")),
            "can_generate": bool(state.get("image_bytes")) and (mode != "inpaint" or bool(state.get("has_mask"))),
        })
        if extra:
            payload.update(extra)
        return payload

    def _decode_mask(self, value: str) -> tuple[bytes, str, int]:
        from PIL import Image

        context = self.context
        if not context.img2img_session.get("active"):
            raise RuntimeError("No active Img2Img session")
        target_size = (
            int(context.img2img_session.get("width") or 1),
            int(context.img2img_session.get("height") or 1),
        )
        mask_bytes = base64.b64decode(data_url_payload(value))
        with Image.open(io.BytesIO(mask_bytes)) as opened:
            full_mask = opened.convert("L").resize(target_size)
        threshold = [0 if i <= 127 else 255 for i in range(256)]
        full_mask = full_mask.point(threshold, "L")
        white_pixels = int(full_mask.histogram()[255])
        small_size = (max(1, target_size[0] // 8), max(1, target_size[1] // 8))
        small_mask = full_mask.resize(small_size).point(threshold, "L")
        painted_blocks = int(small_mask.histogram()[255])
        if white_pixels <= 0 or painted_blocks < 8:
            raise RuntimeError("Inpaint mask is too small" if white_pixels > 0 else "Inpaint mask is empty")
        preview_bytes = self._image_to_png_bytes(full_mask)
        preview = "data:image/png;base64," + base64.b64encode(preview_bytes).decode("ascii")
        return self._image_to_png_bytes(small_mask), preview, painted_blocks

    def set_param(self, key: str, value: Any) -> dict[str, Any] | None:
        context = self.context
        if key == "close":
            context.img2img_session = {}
            return self.module_state()
        if not context.img2img_session.get("active"):
            return context._toast("No active Img2Img session", level="error")
        if key == "main_prompt":
            context.img2img_session["main_prompt"] = str(value or "")
        elif key == "negative_prompt":
            context.img2img_session["negative_prompt"] = str(value or "")
        elif key == "strength":
            context.img2img_session["strength"] = max(1, min(99, int(float(value))))
        elif key == "noise":
            context.img2img_session["noise"] = max(0, min(99, int(float(value))))
        elif key == "repeat":
            context.img2img_session["repeat"] = max(1, min(99, int(float(value))))
        elif key == "resize_1mp":
            return self._set_resize_1mp(context._coerce_bool(value))
        elif key == "mask_png":
            mask_bytes, preview, _ = self._decode_mask(str(value or ""))
            context.img2img_session["mode"] = "inpaint"
            context.img2img_session["mask_bytes"] = mask_bytes
            context.img2img_session["mask_preview"] = preview
            context.img2img_session["has_mask"] = True
        elif key == "clear_mask":
            context.img2img_session["mask_bytes"] = b""
            context.img2img_session["mask_preview"] = ""
            context.img2img_session["has_mask"] = False
        elif key == "add_character":
            context.img2img_session.setdefault("characters", []).append({"active": True, "prompt": "", "uc": ""})
        elif key.startswith("remove_character_"):
            index = context._index_from_key(key, "remove_character_")
            chars = context.img2img_session.setdefault("characters", [])
            if index is not None and 0 <= index < len(chars):
                chars.pop(index)
        elif key.startswith("char_active_"):
            index = context._index_from_key(key, "char_active_")
            chars = context.img2img_session.setdefault("characters", [])
            if index is not None and 0 <= index < len(chars):
                chars[index]["active"] = context._coerce_bool(value)
        elif key.startswith("char_prompt_"):
            index = context._index_from_key(key, "char_prompt_")
            chars = context.img2img_session.setdefault("characters", [])
            if index is not None and 0 <= index < len(chars):
                chars[index]["prompt"] = str(value or "")
        elif key.startswith("char_uc_"):
            index = context._index_from_key(key, "char_uc_")
            chars = context.img2img_session.setdefault("characters", [])
            if index is not None and 0 <= index < len(chars):
                chars[index]["uc"] = str(value or "")
        elif key == "generate":
            commands = self.generation_commands()
            return self.module_state({"_headless_generation_commands": commands})
        else:
            return None
        return self.module_state()

    def _set_resize_1mp(self, enabled: bool) -> dict[str, Any]:
        """1MP 리사이즈 토글: 보관해 둔 원본 바이트에서 세션 이미지를 재파생한다."""
        context = self.context
        session = context.img2img_session
        if bool(session.get("resize_1mp", True)) == enabled:
            session["resize_1mp"] = enabled
            return self.module_state()
        source_bytes = session.get("source_bytes") or session.get("image_bytes") or b""
        try:
            image = self._session_image_from_bytes(bytes(source_bytes), resize_1mp=enabled)
        except Exception:
            return context._toast("이미지 리사이즈에 실패했습니다", level="error")
        size_changed = (int(session.get("width") or 0), int(session.get("height") or 0)) != image.size
        preview, preview_width, preview_height = self._image_preview_data_url(image)
        session["resize_1mp"] = enabled
        session["image_bytes"] = self._image_to_png_bytes(image)
        session["width"] = int(image.width)
        session["height"] = int(image.height)
        session["preview"] = preview
        session["preview_width"] = preview_width
        session["preview_height"] = preview_height
        if size_changed and (session.get("has_mask") or session.get("mask_bytes")):
            # 마스크는 세션 해상도 기준 좌표라 크기가 바뀌면 더 이상 유효하지 않다.
            session["mask_bytes"] = b""
            session["mask_preview"] = ""
            session["has_mask"] = False
        return self.module_state()

    def generation_commands(self) -> list[dict[str, Any]]:
        state = self.context.img2img_session
        if not state.get("image_bytes"):
            raise RuntimeError("Img2Img source image is unavailable")
        mode = str(state.get("mode") or "img2img")
        if mode == "inpaint" and not state.get("mask_bytes"):
            raise RuntimeError("Inpaint mask is required")
        overrides: dict[str, Any] = {
            "input": str(state.get("main_prompt") or ""),
            "_raw_input": str(state.get("main_prompt") or ""),
            "negative_prompt": str(state.get("negative_prompt") or ""),
            "strength": self.strength_value(state.get("strength", 70)),
            "noise": max(0, min(99, int(state.get("noise", 0) or 0))) / 100.0,
            "image_bytes": state["image_bytes"],
            "width": int(state.get("width") or 832),
            "height": int(state.get("height") or 1216),
            "type": "inpaint" if mode == "inpaint" else "img2img",
            "_remote_queue_source": "Inpaint" if mode == "inpaint" else "Img2Img",
            "_remote_queue_label": str(state.get("source_label") or "Result Image"),
        }
        if mode == "inpaint":
            overrides["mask_bytes"] = state.get("mask_bytes")
        char_data = []
        for character in state.get("characters") or []:
            if not character.get("active", True):
                continue
            prompt = str(character.get("prompt") or "").strip()
            if prompt:
                char_data.append((prompt, str(character.get("uc") or "").strip()))
        if char_data:
            overrides["sketchbook_character_prompts"] = char_data
        repeat = max(1, min(99, int(state.get("repeat", 1) or 1)))
        if repeat > 1:
            overrides["img2img_batch_request"] = True
            overrides["img2img_batch_total"] = repeat
        overrides["img2img_batch_window_id"] = int(state.get("window_id", 0) or 0)
        return [
            {
                "type": "generate",
                "api_mode": "NAI",
                "overrides": dict(overrides),
            }
            for _ in range(repeat)
        ]
