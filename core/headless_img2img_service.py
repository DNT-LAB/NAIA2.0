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
    def _image_preview_data_url(image, max_side: int = 1152) -> tuple[str, int, int]:
        """화면에 보여 줄 축소본. **JPEG 다.**

        ⚠️ 예전에는 `PNG optimize=True` 였다. 이건 화면용이지 전송본이 아닌데, 실측
           (832x1216 일러스트급 그림, 640px 축소본):
             PNG optimize=True   50.6 ms / base64 216 KB   <- 예전
             PNG optimize=False  11.6 ms / base64 220 KB
             JPEG q=82            0.5 ms / base64  62 KB
           캔버스를 굴릴 때마다 이걸 다시 만들어 WS 로 보낸다. 100배 느리고 3.5배
           무거운 쪽을 고를 이유가 없다.

        ⚠️ 그리고 **640px 은 너무 작았다.** 캔버스는 이 그림을 뷰어 폭(대략 1150px)에
           맞춰 늘려 그린다 - 2배 확대라 흐릿하게 보였다(사용자 제보 2026-08-26).
           1152 로 올리면 대개 원본 그대로라 줄이는 일조차 없어져 **더 빠르다**:
             960x1088 캔버스 기준  max 640: 15.4 ms / 74 KB / 화면 2.04배 확대
                                  max1152:  2.4 ms /113 KB / 원본 그대로
           오늘 아침(PNG 640px)이 50.6ms · 216KB · 흐릿이었으니 모든 면에서 낫다.
        ⚠️ **마스크에는 쓰지 마라.** 흑백 경계에 JPEG 링잉이 생긴다 - 마스크 미리보기는
           따로 PNG 로 만든다.
        ⚠️ 축소는 LANCZOS 를 유지한다. BILINEAR 이 3ms 빠르지만 그건 인코더가 아니라
           리샘플러 쪽이고, 눈에 보이는 계단이 3ms 값을 못 한다.
        """
        from PIL import Image

        preview = image.copy()
        preview.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        if preview.mode != "RGB":
            preview = preview.convert("RGB")
        buffer = io.BytesIO()
        preview.save(buffer, format="JPEG", quality=78)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}", int(preview.width), int(preview.height)

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

    @staticmethod
    def _position_from_ratio(value: Any, width: int, height: int) -> dict[str, float] | None:
        """NAI 가 쓰는 0~1 비율 좌표를 **캔버스 픽셀**로 되돌린다.

        ⚠️ 두 좌표계가 섞여 있다. NAI `centers` 는 비율이고, 캔버스 마커는 픽셀이다.
           `to_canvas_position` 이 픽셀->비율이고 이것이 그 반대다.
        """
        if not isinstance(value, dict) or width <= 0 or height <= 0:
            return None
        try:
            ratio_x = float(value.get("x"))
            ratio_y = float(value.get("y"))
        except (TypeError, ValueError):
            return None
        if ratio_x != ratio_x or ratio_y != ratio_y:      # NaN 방어
            return None
        return {
            "x": round(min(1.0, max(0.0, ratio_x)) * width, 1),
            "y": round(min(1.0, max(0.0, ratio_y)) * height, 1),
        }

    def _session_characters_from_sources(
        self, params: dict[str, Any], prompt_ctx: dict[str, Any],
        width: int = 0, height: int = 0,
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
        반환 형식 = 세션/모듈스테이트가 쓰는 [{'prompt','uc','active','position'}].

        ⚠️ **좌표도 함께 복원한다.** 예전에는 프롬프트만 옮기고 좌표를 버렸다. 그래서
           인페인트 요청은 늘 `use_coords=False` 였고(화면에서 본 배치가 무시된다),
           캔버스 마커는 좌표가 있는 캐릭터만 그리므로 **뜰 수가 없었다** - 마커가
           없으니 끌어서 놓을 수도 없다(닭과 달걀). 사양 "인페인트 이미지에도 캐릭터
           좌표 배정 가능" 이 한 번도 동작하지 않았다(Codex 리뷰 2026-08-26 BLOCK 4).
        """
        def _norm(prompt, uc, active=True, position=None):
            text = str(prompt or "").strip()
            if not text:
                return None
            return {
                "prompt": text,
                "uc": str(uc or ""),
                "active": bool(active),
                "position": self._position_from_ratio(position, width, height),
            }

        # 1) prompt_context character_prompts
        cps = prompt_ctx.get("character_prompts")
        if isinstance(cps, list) and cps:
            out = [c for c in (
                _norm(item.get("prompt"), item.get("uc"), item.get("active", True),
                      item.get("position") or item.get("center"))
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
                    c = _norm(item.get("prompt"), item.get("uc"), item.get("active", True),
                              item.get("position"))
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
            # ⚠️ 일반 생성 이미지에서 좌표를 나르는 것은 **이 키 하나뿐**이다.
            #    NAI PNG 의 Comment 안에도 `centers` 가 있지만 메타 추출기가 `char_caption`
            #    텍스트만 꺼내고 그것을 버린다(utils/image_info.py).
            pos = params.get("_executed_character_positions") or []
            out = []
            for i, prompt in enumerate(ec):
                c = _norm(prompt, ucs[i] if i < len(ucs) else "", True,
                          pos[i] if i < len(pos) else None)
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
        # V5 인가. 가상 캔버스는 V5 인페인트 **전용**이다(사용자 지정 2026-08-26:
        # "V5 모드에서는 별도 팝업이 아니라 Result 안에서 직접 수정").
        # ⚠️ 판정이 실패하면 **예전 길**로 간다. 여기서 예외가 새면 결과 우클릭
        #    인페인트가 통째로 죽는데, 그건 캔버스를 못 쓰는 것보다 훨씬 나쁘다.
        try:
            canvas_supported = bool(context._is_naid5_model()) and clean_mode == "inpaint"
        except Exception:
            canvas_supported = False
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
            # ── V5 가상 캔버스(사용자 지정 2026-08-26) ──────────────────
            # V5 는 인페인트를 별도 팝업으로 빼지 않고 Result 안에서 고친다. 그러려면
            # "이미지 = 캔버스" 라는 전제를 깨야 한다 - 베이스를 캔버스 안에서 옮기고
            # 비게 된 자리를 자동으로 연다.
            # ⚠️ `canvas_active` 가 꺼져 있으면 예전과 **완전히 같은 길**을 탄다.
            #    기존 img2img/인페인트 팝업의 동작을 바꾸지 않기 위해서다.
            # V5 인페인트면 처음부터 켜 둔다 - 이 길에서는 팝업이 열리지 않으므로
            # 꺼진 채로 두면 사용자에게 아무 편집 수단도 남지 않는다.
            "canvas_supported": canvas_supported,
            "canvas_active": canvas_supported,
            "canvas_width": int(image.width),
            "canvas_height": int(image.height),
            "base_offset_x": 0,
            "base_offset_y": 0,
            "base_width": int(image.width),
            "base_height": int(image.height),
            # 베이스에 먹이는 변형. 캔버스 안에서 키우거나 돌린다.
            "base_scale": 1.0,
            "base_rotation": 0.0,
            # 변형을 먹인 뒤의 크기(화면이 손잡이를 그리는 데 필요하다).
            "placed_width": int(image.width),
            "placed_height": int(image.height),
            # 사용자가 칠한 마스크(캔버스 좌표). 빈 곳 마스크와는 따로 보관해야
            # 오프셋을 다시 옮겼을 때 칠한 것을 잃지 않는다.
            "user_mask_bytes": b"",
            "strength": 99 if clean_mode == "inpaint" else 70,
            "noise": 0,
            "repeat": 1,
            "main_prompt": main_prompt,
            "negative_prompt": negative_prompt,
            # 캐릭터 프롬프트 슬롯을 소스 이미지/라이브 메인 UI에서 자동 채움(future01 패리티 복구).
            # 좌표는 **이 이미지 크기 기준의 픽셀**로 들어온다. 세션이 열릴 때 캔버스가
            # 곧 이미지 크기이므로 그대로 캔버스 좌표가 된다.
            "characters": self._session_characters_from_sources(
                params, prompt_ctx, int(image.width), int(image.height)
            ),
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
                # 캔버스 좌표(픽셀). 없으면 None - 화면이 마커를 안 그린다.
                "position": character.get("position") if isinstance(character.get("position"), dict) else None,
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
            # ⚠️ 캔버스 상태를 여기 안 실으면 화면이 캔버스를 볼 방법이 없다.
            #    `canvas_state()` 만 만들어 두고 합치는 것을 빠뜨렸었다.
            **self.canvas_state(),
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

    def canvas_state(self) -> dict[str, Any]:
        """화면이 캔버스를 그리는 데 필요한 값. 이미지 바이트는 넣지 않는다(미리보기로 간다)."""
        state = self.context.img2img_session
        return {
            # 화면은 이 값으로 캔버스 패널을 띄울지 정한다. `canvas_active` 로는 안 된다 -
            # 사용자가 캔버스를 끄면 패널까지 사라져 다시 켤 방법이 없어진다.
            "canvas_supported": bool(state.get("canvas_supported")),
            "canvas_active": bool(state.get("canvas_active")),
            "canvas_width": int(state.get("canvas_width") or 0),
            "canvas_height": int(state.get("canvas_height") or 0),
            "base_offset_x": int(state.get("base_offset_x") or 0),
            "base_offset_y": int(state.get("base_offset_y") or 0),
            "base_width": int(state.get("base_width") or 0),
            "base_height": int(state.get("base_height") or 0),
            "placed_width": int(state.get("placed_width") or 0),
            "placed_height": int(state.get("placed_height") or 0),
            "base_scale": float(state.get("base_scale") or 1.0),
            "base_rotation": float(state.get("base_rotation") or 0.0),
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
            # 화면이 옛 재개 dock 을 띄울지 정하는 데 쓴다 - V5 캔버스에는 이미
            # 편집/결과 보기/세션 닫기가 있어서 두 경로가 겹치면 안 된다.
            "canvas_supported": bool(state.get("canvas_supported")),
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
            # 캔버스 모드에서는 사용자가 칠한 것을 따로 붙잡아 둔다 - 오프셋을 다시
            # 옮기면 빈 곳 마스크가 달라지므로 합성을 매번 새로 해야 한다.
            context.img2img_session["user_mask_bytes"] = mask_bytes
            if context.img2img_session.get("canvas_active"):
                return self._recompose_canvas()
        elif key == "clear_mask":
            context.img2img_session["mask_bytes"] = b""
            context.img2img_session["mask_preview"] = ""
            context.img2img_session["has_mask"] = False
            context.img2img_session["user_mask_bytes"] = b""
            if context.img2img_session.get("canvas_active"):
                return self._recompose_canvas()
        elif key == "auto_mask":
            return self._auto_mask()
        elif key == "canvas_active":
            return self._set_canvas_active(context._coerce_bool(value))
        elif key == "canvas_size":
            return self._set_canvas_size(value)
        elif key == "base_offset":
            return self._set_base_offset(value)
        elif key == "base_scale":
            # 값만 오면 캔버스 한가운데 기준. `{"value":…, "at":{"x":…,"y":…}}` 로 오면
            # 그 점을 붙잡는다(휠·중앙버튼 드래그가 커서를 붙잡는 데 쓴다).
            if isinstance(value, dict):
                return self._set_base_transform(scale=value.get("value"), at=value.get("at"))
            return self._set_base_transform(scale=value)
        elif key == "base_rotation":
            if isinstance(value, dict):
                return self._set_base_transform(rotation=value.get("value"), at=value.get("at"))
            return self._set_base_transform(rotation=value)
        elif key == "base_reset":
            state = context.img2img_session
            state["base_scale"], state["base_rotation"] = 1.0, 0.0
            state["base_offset_x"] = state["base_offset_y"] = 0
            # 캔버스 크기도 원본으로 되돌린다. 이게 곧 "원본 그대로" 상태다 -
            # 화면의 `가상 캔버스` 토글이 하던 일을 초기화가 대신한다(사용자 지적
            # 2026-08-26: "역할이 모호합니다"). 실제로 토글은 켜나 끄나 결과가 같았다:
            # 캔버스=원본 크기 · 오프셋 0 · 배율 1 · 회전 0 이면 `build_payload` 가
            # 원본을 그대로 돌려주고 빈 곳 마스크도 안 생긴다.
            base_w = int(state.get("base_width") or 0)
            base_h = int(state.get("base_height") or 0)
            if base_w > 0 and base_h > 0:
                state["canvas_width"], state["canvas_height"] = base_w, base_h
            return self._recompose_canvas() if state.get("canvas_active") else self.module_state()
        elif key.startswith("char_position_"):
            index = context._index_from_key(key, "char_position_")
            chars = context.img2img_session.setdefault("characters", [])
            if index is not None and 0 <= index < len(chars):
                chars[index]["position"] = self._normalized_position(value)
        elif key == "add_character":
            context.img2img_session.setdefault("characters", []).append(
                {"active": True, "prompt": "", "uc": "", "position": None})
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

    # ------------------------------------------------------------------
    # V5 가상 캔버스
    # ------------------------------------------------------------------

    @staticmethod
    def _normalized_position(value: Any) -> dict[str, float] | None:
        """캔버스 픽셀 좌표 {x, y}. 못 읽으면 None(= 좌표 없음)."""
        if not isinstance(value, dict):
            return None
        try:
            return {"x": float(value.get("x")), "y": float(value.get("y"))}
        except (TypeError, ValueError):
            return None

    def _base_image(self):
        """세션의 원본(베이스) 이미지. 캔버스 합성은 늘 여기서 다시 시작한다 -
        합성 결과를 다시 합성하면 배경이 겹겹이 쌓인다.

        ⚠️ 세션이 사는 동안 이 그림은 **안 바뀐다.** 그런데 조작 한 번마다 PNG 를
           다시 디코드하고 1MP 로 다시 줄이고 있었다(실측 9ms). 창 번호와 리사이즈
           설정이 그대로면 쓰던 것을 그대로 준다.
        """
        state = self.context.img2img_session
        source = state.get("source_bytes") or state.get("image_bytes")
        if not source:
            raise RuntimeError("Img2Img source image is unavailable")
        resize_1mp = bool(state.get("resize_1mp", True))
        key = (int(state.get("window_id", 0) or 0), resize_1mp, len(source))
        cached = getattr(self, "_base_image_cache", None)
        if cached and cached[0] == key:
            return cached[1]
        image = self._session_image_from_bytes(bytes(source), resize_1mp=resize_1mp)
        self._base_image_cache = (key, image)
        return image

    def _anchor_from_canvas_point(self, point: Any) -> tuple[float, float, float, float] | None:
        """캔버스의 한 점을 '지금 그림의 어느 자리인가' 로 바꿔 둔다.

        확대/회전을 하고 나서도 그 점이 같은 자리를 가리키게 하려면, 변형 **전에**
        비율로 재 둬야 한다.

        ⚠️ 점을 안 주면 **캔버스 한가운데**다. 예전에는 앵커가 아예 없어 놓인 상자의
           좌상단이 고정됐고, 그래서 키울수록 그림이 우하단으로 도망갔다(실측: 200%
           에서 그림 한가운데가 캔버스 우하단 모서리, 400% 에서는 화면 밖).
        """
        state = self.context.img2img_session
        canvas_w = int(state.get("canvas_width") or 0)
        canvas_h = int(state.get("canvas_height") or 0)
        placed_w = int(state.get("placed_width") or 0)
        placed_h = int(state.get("placed_height") or 0)
        if canvas_w <= 0 or canvas_h <= 0 or placed_w <= 0 or placed_h <= 0:
            return None
        try:
            anchor_x = float(point["x"])
            anchor_y = float(point["y"])
        except (TypeError, ValueError, KeyError):
            anchor_x, anchor_y = canvas_w / 2.0, canvas_h / 2.0
        off_x = float(state.get("base_offset_x") or 0)
        off_y = float(state.get("base_offset_y") or 0)
        return (
            anchor_x,
            anchor_y,
            (anchor_x - off_x) / placed_w,
            (anchor_y - off_y) / placed_h,
        )

    def _recompose_canvas(
        self,
        anchor: tuple[float, float, float, float] | None = None,
        *,
        encode_canvas: bool = False,
    ) -> dict[str, Any]:
        """캔버스/오프셋/칠한 마스크로 전송용 이미지와 마스크를 다시 만든다.

        ⚠️ `encode_canvas=False` 면 **전송용 PNG 를 만들지 않는다.** 조작 한 번마다
           캔버스 전체를 PNG 로 굽고 있었는데(실측 62ms), 그건 생성할 때나 필요한
           물건이다. 대신 `canvas_dirty` 를 세워 두고, `generation_commands` 가
           그때 한 번 굽는다.
        """
        from PIL import Image

        from utils.v5_inpaint_canvas import build_payload

        state = self.context.img2img_session
        base = self._base_image()
        state["base_width"], state["base_height"] = int(base.width), int(base.height)

        canvas_w = int(state.get("canvas_width") or base.width)
        canvas_h = int(state.get("canvas_height") or base.height)

        user_mask = None
        raw = state.get("user_mask_bytes") or b""
        if raw:
            try:
                user_mask = Image.open(io.BytesIO(bytes(raw))).convert("L")
                # ⚠️ 칠한 마스크는 NAI 규약대로 **1/8 로 줄여** 보관돼 있다
                #    (`_decode_mask` -> `decode_mask_to_small_png`). 그대로 넘기면
                #    `merge_masks` 가 첫 겹의 크기를 기준으로 삼아 빈 곳 마스크까지
                #    1/8 로 끌어내리고, `downscale_mask` 가 거기서 또 1/8 을 한다
                #    -> 1/64. 캔버스 좌표로 되돌려 놓고 합쳐야 한다.
                if user_mask.size != (canvas_w, canvas_h):
                    user_mask = user_mask.resize((canvas_w, canvas_h), Image.Resampling.NEAREST)
            except Exception as exc:   # noqa: BLE001 - 마스크 하나 때문에 세션이 죽으면 안 된다
                print(f"[v5-canvas] user mask unreadable: {exc}", flush=True)
                user_mask = None

        payload = build_payload(
            base,
            canvas_w=canvas_w,
            canvas_h=canvas_h,
            offset_x=int(state.get("base_offset_x") or 0),
            offset_y=int(state.get("base_offset_y") or 0),
            scale=state.get("base_scale", 1.0),
            rotation=state.get("base_rotation", 0.0),
            user_mask=user_mask,
            anchor=anchor,
            encode_canvas=encode_canvas,
        )
        if encode_canvas:
            state["image_bytes"] = payload["canvas_bytes"]
            state["canvas_dirty"] = False
        else:
            # 전송본은 미뤄 둔다. 화면은 아래 미리보기만 있으면 된다.
            state["canvas_dirty"] = True
        state["width"], state["height"] = payload["width"], payload["height"]
        state["base_offset_x"], state["base_offset_y"] = payload["offset_x"], payload["offset_y"]
        state["placed_width"], state["placed_height"] = payload["placed_width"], payload["placed_height"]
        state["base_scale"], state["base_rotation"] = payload["scale"], payload["rotation"]
        state["mask_bytes"] = payload["mask_bytes"]
        state["has_mask"] = bool(payload["has_mask"])
        if payload["has_mask"]:
            state["mode"] = "inpaint"
        preview, preview_w, preview_h = self._image_preview_data_url(payload["canvas_image"])
        state["preview"], state["preview_width"], state["preview_height"] = preview, preview_w, preview_h
        return self.module_state()

    def _auto_mask(self) -> dict[str, Any]:
        """빈 곳과 **그 경계**를 한 번에 칠한다(사용자 지정 2026-08-26).

        ⚠️ 빈 곳만 딱 열면 이음매가 그대로 남는다. 베이스를 밀거나 돌린 자리에는 늘
           경계가 생기고, 그 위를 조금 덮어야 모델이 이어 그린다.
        ⚠️ 부풀리기는 **1/8 마스크 위에서** 한다. 캔버스 크기에서 16px 커널을 돌리면
           1216x832 기준 수천만 번 비교다 - 어차피 NAI 로는 1/8 이 나간다.
        """
        from PIL import Image

        from utils.v5_inpaint_canvas import (
            AUTO_MASK_RADIUS_PX,
            MASK_SCALE,
            build_payload,
            dilate_mask,
            downscale_mask,
            mask_is_empty,
            merge_masks,
            png_bytes,
        )

        state = self.context.img2img_session
        base = self._base_image()
        canvas_w = int(state.get("canvas_width") or base.width)
        canvas_h = int(state.get("canvas_height") or base.height)
        # 지금 놓인 그대로의 빈 곳. 기하는 `build_payload` 가 SSOT 다 - 여기서 다시
        # 계산하면 화면이 보는 것과 어긋날 자리가 생긴다.
        probe = build_payload(
            base,
            canvas_w=canvas_w,
            canvas_h=canvas_h,
            offset_x=int(state.get("base_offset_x") or 0),
            offset_y=int(state.get("base_offset_y") or 0),
            scale=state.get("base_scale", 1.0),
            rotation=state.get("base_rotation", 0.0),
            user_mask=None,
            # 빈 곳만 알면 된다 - 캔버스를 굽고 버릴 이유가 없다(62ms).
            encode_canvas=False,
        )
        gap = probe.get("mask_image")
        if gap is None or mask_is_empty(gap):
            return self.context._toast(
                "빈 곳이 없습니다 - 캔버스를 넓히거나 베이스를 옮겨 보세요", level="error"
            )
        grown = dilate_mask(downscale_mask(gap), AUTO_MASK_RADIUS_PX, scale=MASK_SCALE)
        # ⚠️ 손으로 칠한 것을 **덮지 않는다.** `자동으로 마스킹을 해준다` 는 더하는 것이지
        #    지우는 것이 아니다 - 예전에는 그대로 덮어써서 칠한 자리가 사라졌다
        #    (Codex 리뷰 2026-08-26 BLOCK 2). 지우는 길은 `마스크 지우기` 가 따로 있다.
        painted = state.get("user_mask_bytes") or b""
        if painted:
            try:
                existing = Image.open(io.BytesIO(bytes(painted))).convert("L")
                if existing.size != grown.size:
                    existing = existing.resize(grown.size, Image.Resampling.NEAREST)
                grown = merge_masks(grown, existing) or grown
            except Exception as exc:   # noqa: BLE001 - 칠한 것 하나 때문에 자동 마스킹이 죽으면 안 된다
                print(f"[v5-canvas] painted mask unreadable, auto mask only: {exc}", flush=True)
        state["mode"] = "inpaint"
        state["user_mask_bytes"] = png_bytes(grown)
        preview = grown.resize((canvas_w, canvas_h), Image.Resampling.NEAREST)
        state["mask_preview"] = (
            "data:image/png;base64,"
            + base64.b64encode(png_bytes(preview)).decode("ascii")
        )
        print(f"[v5-canvas] auto mask: gap + {AUTO_MASK_RADIUS_PX}px edge", flush=True)
        return self._recompose_canvas()

    def _set_canvas_active(self, active: bool) -> dict[str, Any]:
        state = self.context.img2img_session
        state["canvas_active"] = bool(active)
        if not active:
            # 캔버스를 끄면 예전 길로 돌아간다 - 베이스를 그대로 전송한다.
            base = self._base_image()
            state["image_bytes"] = self._image_to_png_bytes(base)
            state["canvas_dirty"] = False      # 방금 구웠다
            state["width"], state["height"] = int(base.width), int(base.height)
            state["base_offset_x"] = state["base_offset_y"] = 0
            state["mask_bytes"] = state.get("user_mask_bytes") or b""
            state["has_mask"] = bool(state["mask_bytes"])
            preview, pw, ph = self._image_preview_data_url(base)
            state["preview"], state["preview_width"], state["preview_height"] = preview, pw, ph
            return self.module_state()
        return self._recompose_canvas()

    def _set_canvas_size(self, value: Any) -> dict[str, Any]:
        from core.resolution_utils import parse_resolution_pair, snap_resolution_to_multiple

        pair = parse_resolution_pair(value)
        if not pair:
            return self.context._toast("캔버스 해상도를 읽지 못했습니다", level="error")
        width, height = snap_resolution_to_multiple(*pair)
        state = self.context.img2img_session
        state["canvas_width"], state["canvas_height"] = int(width), int(height)
        state["canvas_active"] = True
        return self._recompose_canvas()

    def _set_base_transform(
        self, *, scale: Any = None, rotation: Any = None, at: Any = None
    ) -> dict[str, Any]:
        """확대/회전. 오프셋과 달리 **캔버스를 자동으로 켜지 않는다** - 캔버스가 꺼진
        상태에서 베이스를 돌리면 전송 이미지가 말없이 달라져 예전 동작이 깨진다.

        `at` 은 붙잡을 캔버스 좌표. 안 주면 캔버스 한가운데다.
        ⚠️ 앵커는 **바꾸기 전에** 재야 한다 - 바꾼 뒤에 재면 이미 도망간 자리를 잰다.
        """
        from utils.v5_inpaint_canvas import clamp_scale, normalize_rotation

        state = self.context.img2img_session
        anchor = self._anchor_from_canvas_point(at if isinstance(at, dict) else None)
        if scale is not None:
            state["base_scale"] = clamp_scale(scale)
        if rotation is not None:
            state["base_rotation"] = normalize_rotation(rotation)
        if not state.get("canvas_active"):
            return self.module_state()
        return self._recompose_canvas(anchor)

    def _set_base_offset(self, value: Any) -> dict[str, Any]:
        position = self._normalized_position(value)
        if position is None:
            return self.context._toast("베이스 위치를 읽지 못했습니다", level="error")
        state = self.context.img2img_session
        state["base_offset_x"] = int(round(position["x"]))
        state["base_offset_y"] = int(round(position["y"]))
        state["canvas_active"] = True
        return self._recompose_canvas()

    def generation_commands(self, *, submission_id: str = "") -> list[dict[str, Any]]:
        state = self.context.img2img_session
        # ⚠️ 조작 중에는 전송본을 안 굽는다(`_recompose_canvas(encode_canvas=False)`).
        #    **여기가 그것을 굽는 유일한 자리다** - 빠뜨리면 화면과 다른 옛 그림이
        #    NAI 로 나간다. `image_bytes` 를 읽는 곳은 여기뿐이라 이 한 줄로 족하다.
        if state.get("canvas_dirty") and state.get("canvas_active"):
            self._recompose_canvas(encode_canvas=True)
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
        # ⚠️ 예전에는 (prompt, uc) 튜플만 실어 **좌표가 통째로 버려졌다**
        #    (api_service: "Sketchbook은 위치 미지원 -> 기본값(0.5, 0.5)").
        #    dict 로 실으면 그쪽이 position 을 함께 읽는다. 좌표를 안 준 캐릭터가
        #    하나라도 있으면 NAI 쪽에서 use_coords 가 꺼지므로(전원분이 있어야 켜짐)
        #    섞여 있어도 예전과 같은 결과가 된다.
        from utils.v5_inpaint_canvas import to_canvas_position

        canvas_w = int(state.get("width") or 0)
        canvas_h = int(state.get("height") or 0)
        char_data = []
        for character in state.get("characters") or []:
            if not character.get("active", True):
                continue
            prompt = str(character.get("prompt") or "").strip()
            if not prompt:
                continue
            entry = {"prompt": prompt, "uc": str(character.get("uc") or "").strip()}
            position = character.get("position")
            if isinstance(position, dict):
                ratio = to_canvas_position(canvas_w, canvas_h, position.get("x"), position.get("y"))
                if ratio:
                    entry["position"] = ratio
            char_data.append(entry)
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
