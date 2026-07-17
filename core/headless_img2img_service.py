"""Headless Img2Img/Inpaint module state service.

This keeps Remote Web image-input behavior outside the WebSessionContext
container while preserving the existing context-facing API.
"""

from __future__ import annotations

import base64
import io
from typing import Any

from core.headless_image_utils import image_to_png_bytes
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

    def _session_characters_from_sources(
        self, params: dict[str, Any], prompt_ctx: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """인페인트/img2img 세션 캐릭터 슬롯을 *소스 이미지의* 캐릭터로 채운다.

        future01(ui/img2img_window.py set_from_history_item) 패리티 — future02 헤드리스
        이관 때 누락돼 슬롯이 항상 비어 있던 회귀 복구. 우선순위:
          1) prompt_context['character_prompts']               (이미지 메타 직접 저장분)
          2) generation_params['sketchbook_character_prompts'] (소스가 img2img였던 경우)
          3) generation_params['_executed_characters'(+_uc)]   (NAI 실행 기록 — 일반 생성 이미지)
        세션은 항상 *특정 이미지* 에서 열리므로(외부/임포트 포함) 그 이미지의 캐릭터만 쓴다.
        라이브 메인 UI 캐릭터로 폴백하지 않는다 — 메타 없는 외부 이미지에 무관한 활성
        캐릭터를 silently 주입하는 의외 동작을 방지(Codex). 메타 없으면 빈 슬롯이 정상이며
        future01 set_from_history_item 도 라이브 폴백을 하지 않았다(그건 별개의 fresh-open 경로).
        반환 형식 = 세션/모듈스테이트가 쓰는 [{'prompt','uc','active'}].
        """
        def _norm(prompt, uc, active=True):
            text = str(prompt or "").strip()
            if not text:
                return None
            return {"prompt": text, "uc": str(uc or ""), "active": bool(active)}

        # 1) prompt_context character_prompts
        cps = prompt_ctx.get("character_prompts")
        if isinstance(cps, list) and cps:
            out = [c for c in (
                _norm(item.get("prompt"), item.get("uc"), item.get("active", True))
                for item in cps if isinstance(item, dict)
            ) if c]
            if out:
                return out
        # 2) sketchbook_character_prompts (dict 또는 (prompt, uc) 튜플/리스트)
        skb = params.get("sketchbook_character_prompts")
        if isinstance(skb, (list, tuple)) and skb:
            out = []
            for item in skb:
                if isinstance(item, dict):
                    c = _norm(item.get("prompt"), item.get("uc"), item.get("active", True))
                elif isinstance(item, (list, tuple)) and item:
                    c = _norm(item[0], item[1] if len(item) > 1 else "", True)
                else:
                    c = None
                if c:
                    out.append(c)
            if out:
                return out
        # 3) _executed_characters / _executed_characters_uc (병렬 리스트)
        ec = params.get("_executed_characters")
        if isinstance(ec, list) and ec:
            ucs = params.get("_executed_characters_uc") or []
            out = []
            for i, prompt in enumerate(ec):
                c = _norm(prompt, ucs[i] if i < len(ucs) else "", True)
                if c:
                    out.append(c)
            if out:
                return out
        return []

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
            # 캐릭터 프롬프트 슬롯을 소스 이미지/라이브 메인 UI에서 자동 채움(future01 패리티 복구).
            "characters": self._session_characters_from_sources(params, prompt_ctx),
            # 생성 요청은 팝업 수명과 분리해 추적한다. 세션/마스크는 완료 뒤에도
            # 살아 있어 같은 마스크로 재시도할 수 있고, 다른 Web 클라이언트나 분리창도
            # 동일한 submission 상태를 관찰한다.
            "generation_sequence": 0,
            "generation_submission_id": "",
            "generation_status": "idle",
            "generation_expected_count": 0,
            "generation_dispatch_count": 0,
            "generation_queued_count": 0,
            "generation_started_count": 0,
            "generation_completed_count": 0,
            "generation_failed_count": 0,
            "generation_request_ids": [],
            "generation_dispatch_indices": [],
            "generation_started_request_ids": [],
            "generation_terminal_request_ids": [],
            "generation_error": "",
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
        generation_status = str(state.get("generation_status") or "idle")
        generation_busy = generation_status in {"submitting", "queued", "running"}
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
            "can_generate": (
                bool(state.get("image_bytes"))
                and (mode != "inpaint" or bool(state.get("has_mask")))
                and not generation_busy
            ),
            **self._generation_state_fields(state),
        })
        if extra:
            payload.update(extra)
        return payload

    @staticmethod
    def _generation_state_fields(state: dict[str, Any]) -> dict[str, Any]:
        return {
            "generation_submission_id": str(state.get("generation_submission_id") or ""),
            "generation_status": str(state.get("generation_status") or "idle"),
            "generation_expected_count": int(state.get("generation_expected_count", 0) or 0),
            "generation_queued_count": int(state.get("generation_queued_count", 0) or 0),
            "generation_started_count": int(state.get("generation_started_count", 0) or 0),
            "generation_completed_count": int(state.get("generation_completed_count", 0) or 0),
            "generation_failed_count": int(state.get("generation_failed_count", 0) or 0),
            "generation_request_ids": list(state.get("generation_request_ids") or []),
            "generation_error": str(state.get("generation_error") or ""),
        }

    def generation_event_payload(self) -> dict[str, Any]:
        """Small cross-client lifecycle event; deliberately excludes image/mask bytes."""
        state = self.context.img2img_session if isinstance(self.context.img2img_session, dict) else {}
        if not state.get("active"):
            return {
                "type": "img2img_generation_state",
                "module_id": "img2img",
                "active": False,
                "generation_status": "inactive",
                "can_retry": False,
                "can_generate": False,
            }
        mode = str(state.get("mode") or "img2img")
        fields = self._generation_state_fields(state)
        retryable = bool(state.get("image_bytes")) and (mode != "inpaint" or bool(state.get("has_mask")))
        generation_busy = fields["generation_status"] in {"submitting", "queued", "running"}
        return {
            "type": "img2img_generation_state",
            "module_id": "img2img",
            "active": True,
            "window_id": int(state.get("window_id", 0) or 0),
            "mode": mode,
            "has_mask": bool(state.get("has_mask")),
            "can_retry": retryable,
            "can_generate": retryable and not generation_busy,
            **fields,
        }

    def _matches_generation(self, params: dict[str, Any] | None) -> bool:
        state = self.context.img2img_session if isinstance(self.context.img2img_session, dict) else {}
        params = params if isinstance(params, dict) else {}
        if not state.get("active"):
            return False
        try:
            marker_window = int(params.get("_img2img_window_id", 0) or 0)
        except (TypeError, ValueError):
            return False
        return (
            marker_window == int(state.get("window_id", 0) or 0)
            and str(params.get("_img2img_submission_id") or "")
            == str(state.get("generation_submission_id") or "")
        )

    def record_generation_dispatch(
        self,
        command: dict[str, Any],
        *,
        request_id: str = "",
        error: str = "",
    ) -> bool:
        overrides = command.get("overrides") if isinstance(command, dict) else None
        if not self._matches_generation(overrides):
            return False
        state = self.context.img2img_session
        try:
            index = int(overrides.get("_img2img_submission_index", -1))
        except (TypeError, ValueError):
            index = -1
        seen = state.setdefault("generation_dispatch_indices", [])
        if index in seen:
            return False
        seen.append(index)
        state["generation_dispatch_count"] = int(state.get("generation_dispatch_count", 0) or 0) + 1
        request_id = str(request_id or "")
        if request_id:
            ids = state.setdefault("generation_request_ids", [])
            if request_id not in ids:
                ids.append(request_id)
                state["generation_queued_count"] = int(state.get("generation_queued_count", 0) or 0) + 1
        else:
            state["generation_failed_count"] = int(state.get("generation_failed_count", 0) or 0) + 1
            if error:
                state["generation_error"] = str(error)
        return True

    def finalize_generation_dispatch(self) -> bool:
        state = self.context.img2img_session if isinstance(self.context.img2img_session, dict) else {}
        if not state.get("active") or str(state.get("generation_status") or "") != "submitting":
            return False
        if int(state.get("generation_queued_count", 0) or 0) > 0:
            state["generation_status"] = "queued"
        else:
            state["generation_status"] = "error"
            state["generation_error"] = str(state.get("generation_error") or "Generation enqueue failed")
        return True

    def record_generation_started(self, params: dict[str, Any] | None, request_id: str) -> bool:
        if not self._matches_generation(params):
            return False
        state = self.context.img2img_session
        request_id = str(request_id or "")
        seen = state.setdefault("generation_started_request_ids", [])
        if (
            not request_id
            or request_id in seen
            or request_id in state.setdefault("generation_terminal_request_ids", [])
        ):
            return False
        seen.append(request_id)
        state["generation_started_count"] = int(state.get("generation_started_count", 0) or 0) + 1
        state["generation_status"] = "running"
        return True

    def _record_generation_terminal(
        self,
        params: dict[str, Any] | None,
        request_id: str,
        *,
        error: str = "",
    ) -> bool:
        if not self._matches_generation(params):
            return False
        state = self.context.img2img_session
        request_id = str(request_id or "")
        terminal = state.setdefault("generation_terminal_request_ids", [])
        if not request_id or request_id in terminal:
            return False
        terminal.append(request_id)
        if error:
            state["generation_failed_count"] = int(state.get("generation_failed_count", 0) or 0) + 1
            state["generation_error"] = str(error)
        else:
            state["generation_completed_count"] = int(state.get("generation_completed_count", 0) or 0) + 1
        expected = int(state.get("generation_expected_count", 0) or 0)
        finished = (
            int(state.get("generation_completed_count", 0) or 0)
            + int(state.get("generation_failed_count", 0) or 0)
        )
        if expected > 0 and finished >= expected:
            failed = int(state.get("generation_failed_count", 0) or 0)
            completed = int(state.get("generation_completed_count", 0) or 0)
            if failed and completed:
                state["generation_status"] = "completed_with_errors"
            elif failed:
                state["generation_status"] = "error"
            else:
                state["generation_status"] = "completed"
        else:
            state["generation_status"] = "running"
        return True

    def record_generation_completed(self, params: dict[str, Any] | None, request_id: str) -> bool:
        return self._record_generation_terminal(params, request_id)

    def record_generation_failed(
        self,
        params: dict[str, Any] | None,
        request_id: str,
        error: str,
    ) -> bool:
        return self._record_generation_terminal(params, request_id, error=str(error or "Generation failed"))

    def _decode_mask(self, value: str) -> tuple[bytes, str, int]:
        # 디코드 본체는 utils.inpaint_mask 공유 유틸(캐릭터 벤치와 공용). 여기는
        # 세션 결합(활성 검사 + target_size)과 RuntimeError 계약만 유지한다.
        from utils.inpaint_mask import decode_mask_to_small_png

        context = self.context
        if not context.img2img_session.get("active"):
            raise RuntimeError("No active Img2Img session")
        target_size = (
            int(context.img2img_session.get("width") or 1),
            int(context.img2img_session.get("height") or 1),
        )
        try:
            decoded = decode_mask_to_small_png(str(value or ""), target_size)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        return decoded.small_png, decoded.preview_data_url, decoded.painted_blocks

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
            state = context.img2img_session
            if str(state.get("generation_status") or "idle") in {"submitting", "queued", "running"}:
                return self.module_state({
                    "_headless_extra_messages": [
                        context._toast("Img2Img generation is already queued or running", level="info")
                    ]
                })
            sequence = int(state.get("generation_sequence", 0) or 0) + 1
            submission_id = f"{int(state.get('window_id', 0) or 0)}:{sequence}"
            repeat = max(1, min(99, int(state.get("repeat", 1) or 1)))
            state.update({
                "generation_sequence": sequence,
                "generation_submission_id": submission_id,
                "generation_status": "submitting",
                "generation_expected_count": repeat,
                "generation_dispatch_count": 0,
                "generation_queued_count": 0,
                "generation_started_count": 0,
                "generation_completed_count": 0,
                "generation_failed_count": 0,
                "generation_request_ids": [],
                "generation_dispatch_indices": [],
                "generation_started_request_ids": [],
                "generation_terminal_request_ids": [],
                "generation_error": "",
            })
            try:
                commands = self.generation_commands(submission_id=submission_id)
            except Exception as exc:
                # 직접 WebSocket 호출이나 stale UI에서도 준비 실패가 `submitting`으로
                # 고착되지 않게 한다. 세션/소스는 유지해 전제 보완 후 재시도할 수 있다.
                state["generation_status"] = "error"
                state["generation_error"] = str(exc)
                raise
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

    def generation_commands(self, *, submission_id: str = "") -> list[dict[str, Any]]:
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
        submission_id = str(submission_id or state.get("generation_submission_id") or "")
        commands = []
        for index in range(repeat):
            command_overrides = dict(overrides)
            command_overrides["_img2img_window_id"] = int(state.get("window_id", 0) or 0)
            command_overrides["_img2img_submission_id"] = submission_id
            command_overrides["_img2img_submission_index"] = index
            commands.append({
                "type": "generate",
                "api_mode": "NAI",
                "overrides": command_overrides,
            })
        return commands
