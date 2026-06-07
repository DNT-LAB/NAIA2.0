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


def _as_float(value: Any, default: float) -> float:
    """0.0 같은 유효한 0 값을 보존하는 float 변환(누락/None/비수치만 default)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# NAI UI model key -> encode-vibe API model string (mirrors api_service.py model_mapping).
_NAI_MODEL_MAP = {
    "NAID4.5F": "nai-diffusion-4-5-full",
    "NAID4.5C": "nai-diffusion-4-5-curated",
    "NAID4.0F": "nai-diffusion-4-full",
    "NAID4.0C": "nai-diffusion-4-curated-preview",
    "NAID3": "nai-diffusion-3",
}
_ENCODE_VIBE_URL = "https://image.novelai.net/ai/encode-vibe"
_ENCODE_UNAVAILABLE_REASON = "Vibe 인코딩은 NAI 모드 + NAI 토큰 + 소스 이미지가 있을 때만 가능합니다."


def _post_encode_vibe(token: str, source_bytes: bytes, ie: float, api_model: str) -> str:
    """POST /ai/encode-vibe (2 Anlas). 순수 네트워크 호출 — 영속/프레임/Storage 접근 없음."""
    import requests

    resp = requests.post(
        _ENCODE_VIBE_URL,
        json={
            "image": base64.b64encode(source_bytes).decode("ascii"),
            "information_extracted": ie,
            "model": api_model,
        },
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=180,
    )
    resp.raise_for_status()
    return base64.b64encode(resp.content).decode("utf-8")


def encode_vibe_bytes(context: Any, source_bytes: bytes, ie: float, *, model_key: str | None = None) -> str:
    """1회성 vibe 인코딩(Storyteller Use Vibe 등): 검증 후 encode-vibe를 호출해 인코딩
    문자열만 돌려준다. Storage/프레임/영속(_persist, _save_encoding_to_storage,
    vibe_transfer_frames)을 일절 건드리지 않는다 — 휘발성 보장은 구조적. 실패는 예외.

    ``model_key`` 명시 시 그 모델 키로 인코딩한다(요청-로컬 호출용 — 큐 프레임이 baking 한
    모델로 인코딩해 라이브 컨텍스트 모델 드리프트와 무관하게 한다). 미지정 시 현재 모델(기존 동작)."""
    if str(context.get_api_mode() or "").upper() != "NAI":
        raise RuntimeError("Vibe 인코딩은 NAI 모드에서만 가능합니다.")
    if model_key is not None:
        resolved_model = str(model_key or "")
        is_naid3 = "NAID3" in resolved_model.upper()
    else:
        resolved_model = str(context._current_model_key() or "")
        is_naid3 = context._is_naid3_model()
    if is_naid3:
        raise RuntimeError("NAID3 모델은 Vibe 인코딩을 지원하지 않습니다.")
    if not source_bytes:
        raise RuntimeError("인코딩할 소스 이미지가 없습니다.")
    try:
        token = str(context.secure_token_manager.get_token("nai_token") or "")
    except Exception:
        token = ""
    if not token:
        raise RuntimeError("NAI 토큰이 필요합니다 (API 설정 → NAI).")
    ie = max(0.01, min(1.0, round(float(ie), 2)))
    api_model = _NAI_MODEL_MAP.get(resolved_model, "nai-diffusion-4-5-full")
    encoding = _post_encode_vibe(token, bytes(source_bytes), ie, api_model)
    if not encoding:
        raise RuntimeError("Vibe 인코딩 응답이 비어 있습니다.")
    return encoding


class HeadlessVibeTransferService:
    def __init__(self, context: Any):
        self.context = context

    # ----- 영속 (재시작 복원): VibeTransferModule_{mode}.json -----
    def _settings_mode(self) -> str:
        return str(self.context.get_api_mode() or "NAI").upper()

    def _ensure_loaded(self) -> None:
        """첫 접근/모드 변경 시 디스크에서 활성 프레임을 1회 로드한다.

        프레임 리스트는 모드별 파일(데스크톱 호환)에 영속된다. 이미 현재 모드로
        로드했으면 no-op. 상호배타 cross-disable이 미로드 상대를 깨우도록 여기서
        디스크의 enabled 상태까지 복원한다.
        """
        context = self.context
        mode = self._settings_mode()
        if getattr(context, "_vibe_frames_loaded_mode", None) == mode:
            return
        context._vibe_frames_loaded_mode = mode
        frames, normalize = self._load_persisted(mode)
        context.vibe_transfer_frames = frames
        context.vibe_transfer_normalize = normalize

    def _load_persisted(self, mode: str) -> tuple[list[dict[str, Any]], bool]:
        try:
            path = self.context._existing_save_path(f"VibeTransferModule_{mode}.json")
            if not path.exists():
                return [], False
            data = json.loads(path.read_text(encoding="utf-8"))
            block = data.get(mode) if isinstance(data, dict) else None
            if not isinstance(block, dict):
                block = data if isinstance(data, dict) else {}
            raw_frames = block.get("vibe_frames")
            normalize = bool(block.get("normalize_strength", False))
            frames: list[dict[str, Any]] = []
            if isinstance(raw_frames, list):
                for raw in raw_frames:
                    frame = self._frame_from_persisted(raw)
                    if frame is not None:
                        frames.append(frame)
            return frames, normalize
        except Exception as exc:
            print(f"[ERROR] Vibe Transfer settings load failed: {exc}")
            return [], False

    def _frame_from_persisted(self, raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None
        encodings = raw.get("vibe_encodings") if isinstance(raw.get("vibe_encodings"), dict) else {}
        encodings = {str(k): str(v) for k, v in encodings.items() if v}
        file_hash = str(raw.get("file_hash") or "")
        source_model = str(raw.get("target_model") or raw.get("source_model") or "")
        image_data = ""
        thumbnail = ""
        if file_hash and not raw.get("is_no_image"):
            try:
                image_path = self.context._existing_save_path(
                    "vibe_transfer", source_model, "images", f"{file_hash}.png"
                )
                if image_path.exists():
                    from PIL import Image

                    with Image.open(image_path) as image:
                        image_data = base64.b64encode(image_to_png_bytes(image.convert("RGBA"))).decode("ascii")
                        thumbnail = thumbnail_b64(image)
            except Exception:
                image_data = ""
                thumbnail = ""
        return {
            "file_hash": file_hash,
            "file_name": str(raw.get("file_name") or (f"{file_hash}.png" if file_hash else "vibe.png")),
            "file_path": str(raw.get("file_path") or ""),
            "image_bytes": b"",
            "image_data": image_data,
            "thumbnail": thumbnail,
            "is_enabled": bool(raw.get("is_enabled")),
            "is_no_image": bool(raw.get("is_no_image", True)),
            "is_naid3": "NAID3" in source_model,
            "reference_strength": _as_float(raw.get("reference_strength"), 0.6),
            "information_extracted": _as_float(raw.get("information_extracted"), 1.0),
            "vibe_encodings": encodings,
            "storage_type": str(raw.get("storage_type") or ""),
            "source_model": source_model,
        }

    @staticmethod
    def _persistable_frame(frame: dict[str, Any]) -> dict[str, Any]:
        return {
            "file_hash": str(frame.get("file_hash") or ""),
            "file_path": str(frame.get("file_path") or ""),
            "file_name": str(frame.get("file_name") or ""),
            "reference_strength": _as_float(frame.get("reference_strength"), 0.6),
            "information_extracted": _as_float(frame.get("information_extracted"), 1.0),
            "is_enabled": bool(frame.get("is_enabled")),
            "is_no_image": bool(frame.get("is_no_image")),
            "target_model": str(frame.get("source_model") or frame.get("target_model") or ""),
            "storage_type": str(frame.get("storage_type") or ""),
            "vibe_encodings": {str(k): str(v) for k, v in (frame.get("vibe_encodings") or {}).items() if v},
        }

    def _persist(self) -> None:
        context = self.context
        mode = self._settings_mode()
        try:
            frames = [self._persistable_frame(frame) for frame in context.vibe_transfer_frames]
            payload = {mode: {"normalize_strength": bool(context.vibe_transfer_normalize), "vibe_frames": frames}}
            path = context._save_path(f"VibeTransferModule_{mode}.json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=4), encoding="utf-8")
        except Exception as exc:
            print(f"[ERROR] Vibe Transfer settings save failed: {exc}")

    @staticmethod
    def _is_float_like(value: Any) -> bool:
        try:
            float(value)
            return True
        except Exception:
            return False

    def disable_all_frames(self) -> None:
        # 상호배타 cross-disable의 영속 진입점: 미로드 상대도 깨워 디스크의 enabled를
        # 끄고 저장한다(재시작 시 stale 부활 방지).
        self._ensure_loaded()
        changed = False
        for frame in self.context.vibe_transfer_frames:
            if frame.get("is_enabled"):
                frame["is_enabled"] = False
                changed = True
        if changed:
            self._persist()

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

    # ----- Vibe 인코딩 (NAI /ai/encode-vibe 포팅, 2 Anlas/회) -----
    def _runtime_can_encode(self) -> bool:
        context = self.context
        if str(context.get_api_mode() or "").upper() != "NAI":
            return False
        if context._is_naid3_model():
            return False
        try:
            return bool(context.secure_token_manager.get_token("nai_token"))
        except Exception:
            return False

    def _frame_source_candidates(self, frame: dict[str, Any]):
        file_hash = str(frame.get("file_hash") or "")
        if not file_hash:
            return []
        models = []
        for model in (str(frame.get("source_model") or ""), self.context._current_model_key()):
            if model and model not in models:
                models.append(model)
        return [
            self.context._existing_save_path("vibe_transfer", model, "images", f"{file_hash}.png")
            for model in models
        ]

    def _frame_has_source(self, frame: dict[str, Any]) -> bool:
        raw = frame.get("image_bytes")
        if isinstance(raw, (bytes, bytearray)) and raw:
            return True
        return any(path.exists() for path in self._frame_source_candidates(frame))

    def _frame_source_bytes(self, frame: dict[str, Any]) -> bytes:
        raw = frame.get("image_bytes")
        if isinstance(raw, (bytes, bytearray)) and raw:
            return bytes(raw)
        for path in self._frame_source_candidates(frame):
            if path.exists():
                try:
                    return path.read_bytes()
                except Exception:
                    return b""
        return b""

    def begin_encode(self, key: str) -> dict[str, Any]:
        """Validate + atomically CLAIM the frame for encoding (the broadcast then shows
        'Encoding…'). Returns ``{"ok": bool, "messages": [...]}``. ok=False (with a
        toast) when the frame is missing, cannot be encoded, or is ALREADY encoding —
        the caller MUST then not start a second /ai/encode-vibe call, which would spend
        Anlas twice and let two workers mutate the same frame."""
        context = self.context
        self._ensure_loaded()
        index = context._index_from_key(key, "encode_")
        frames = context.vibe_transfer_frames
        if index is None or not (0 <= index < len(frames)):
            return {"ok": False, "messages": [context._toast("Vibe 프레임을 찾을 수 없습니다.", level="error")]}
        frame = frames[index]
        if frame.get("encoding_in_progress"):
            return {"ok": False, "messages": [context._toast("이미 인코딩 중입니다.", level="info")]}
        if not self._runtime_can_encode():
            return {"ok": False, "messages": [context._toast("Vibe 인코딩은 NAI 모드 + NAI 토큰이 필요합니다 (NAID3 제외).", level="error")]}
        if frame.get("is_no_image") or not self._frame_has_source(frame):
            return {"ok": False, "messages": [context._toast("인코딩할 소스 이미지가 없습니다.", level="error")]}
        frame["encoding_in_progress"] = True
        return {"ok": True, "messages": [self.module_state()]}

    def perform_encode(self, key: str, value: Any = None) -> list[dict[str, Any]]:
        """Blocking: POST /ai/encode-vibe for the requested IE, store the encoding,
        persist (active state + storage), return [toast, module_state]. Must run off
        the event loop (executor) — the encode is a network call. Assumes begin_encode
        already claimed the frame; ``encoding_in_progress`` stays True for the whole
        network call (so a duplicate request is rejected) and is cleared here in a
        finally, before the final module_state is built.

        ``value`` is the target IE from the encode command (the slider value the user
        wants to encode at). It is authoritative because dragging the slider to an
        un-encoded IE does NOT round-trip to the backend, so frame.information_extracted
        can be stale; fall back to it only when no value is supplied."""
        context = self.context
        self._ensure_loaded()
        index = context._index_from_key(key, "encode_")
        frames = context.vibe_transfer_frames
        if index is None or not (0 <= index < len(frames)):
            return [context._toast("Vibe 프레임을 찾을 수 없습니다.", level="error")]
        frame = frames[index]
        toast = None
        try:
            can = self._runtime_can_encode()
            source_bytes = b"" if frame.get("is_no_image") else self._frame_source_bytes(frame)
            token = (context.secure_token_manager.get_token("nai_token") or "") if can else ""
            if not can:
                toast = context._toast("Vibe 인코딩은 NAI 모드 + NAI 토큰이 필요합니다.", level="error")
            elif not source_bytes:
                toast = context._toast("인코딩할 소스 이미지를 찾을 수 없습니다.", level="error")
            elif not token:
                toast = context._toast("NAI 토큰이 필요합니다 (API 설정 → NAI).", level="error")
            else:
                ie = round(_as_float(value, _as_float(frame.get("information_extracted"), 1.0)), 2)
                ie = max(0.01, min(1.0, ie))
                model_key = context._current_model_key()
                api_model = _NAI_MODEL_MAP.get(model_key, "nai-diffusion-4-5-full")
                encoding = _post_encode_vibe(token, source_bytes, ie, api_model)
                if not encoding:
                    toast = context._toast("Vibe 인코딩 응답이 비어 있습니다.", level="error")
                else:
                    frame["information_extracted"] = ie  # the freshly-encoded IE becomes current
                    encodings = frame.get("vibe_encodings")
                    if not isinstance(encodings, dict):
                        encodings = {}
                    encodings[f"{ie:.2f}"] = encoding
                    frame["vibe_encodings"] = encodings
                    frame["source_model"] = frame.get("source_model") or model_key
                    self._persist()
                    self._save_encoding_to_storage(frame, source_bytes, model_key)
                    toast = context._toast(f"Vibe 인코딩 완료 — IE {ie:.2f} (2 Anlas 소모)", level="success")
        except Exception as exc:
            toast = context._toast(f"Vibe 인코딩 실패: {exc}", level="error")
        finally:
            frame["encoding_in_progress"] = False
        return [toast, self.module_state()] if toast else [self.module_state()]

    def _save_encoding_to_storage(self, frame: dict[str, Any], source_bytes: bytes, model_key: str) -> None:
        context = self.context
        file_hash = str(frame.get("file_hash") or "")
        if not file_hash or not model_key:
            return
        try:
            json_path = context._save_path("vibe_transfer", model_key, f"{file_hash}.json")
            json_path.parent.mkdir(parents=True, exist_ok=True)
            existing: dict[str, Any] = {}
            if json_path.exists():
                try:
                    loaded = json.loads(json_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        existing = loaded
                except Exception:
                    existing = {}
            enc = existing.get("encodings") if isinstance(existing.get("encodings"), dict) else {}
            enc.update({str(k): str(v) for k, v in (frame.get("vibe_encodings") or {}).items() if v})
            existing.update({
                "file_hash": file_hash,
                "file_name": str(frame.get("file_name") or f"{file_hash}.png"),
                "encodings": enc,
            })
            json_path.write_text(json.dumps(existing, ensure_ascii=False, indent=4), encoding="utf-8")
            img_path = context._save_path("vibe_transfer", model_key, "images", f"{file_hash}.png")
            img_path.parent.mkdir(parents=True, exist_ok=True)
            if source_bytes and not img_path.exists():
                img_path.write_bytes(source_bytes)
        except Exception as exc:
            print(f"[ERROR] Vibe encoding storage save failed: {exc}")

    def module_state(self) -> dict[str, Any]:
        context = self.context
        self._ensure_loaded()
        runtime_can_encode = self._runtime_can_encode()
        frames = []
        enabled_count = 0
        strength_total = 0.0
        for index, frame in enumerate(context.vibe_transfer_frames):
            encodings = frame.get("vibe_encodings") if isinstance(frame.get("vibe_encodings"), dict) else {}
            encoding_keys = sorted(float(key) for key in encodings.keys() if self._is_float_like(key))
            information_extracted = _as_float(frame.get("information_extracted"), 1.0)
            active_encoding = min(encoding_keys, key=lambda key: abs(key - information_extracted)) if encoding_keys else None
            has_encoding = active_encoding is not None and abs(active_encoding - information_extracted) < 1e-9
            if frame.get("is_enabled") and encodings:
                enabled_count += 1
                strength_total += _as_float(frame.get("reference_strength"), 0.6)
            frame_can_encode = (
                runtime_can_encode
                and not frame.get("is_no_image")
                and self._frame_has_source(frame)
            )
            frames.append({
                "index": index,
                "file_hash": frame.get("file_hash", ""),
                "file_name": frame.get("file_name", ""),
                "is_enabled": bool(frame.get("is_enabled")),
                "is_no_image": bool(frame.get("is_no_image")),
                "is_naid3": context._is_naid3_model(),
                "reference_strength": _as_float(frame.get("reference_strength"), 0.6),
                "information_extracted": information_extracted,
                "has_encoding": has_encoding,
                "active_encoding": active_encoding,
                "encoding_in_progress": bool(frame.get("encoding_in_progress")),
                "can_encode": frame_can_encode,
                "encoding_unavailable_reason": "" if frame_can_encode else _ENCODE_UNAVAILABLE_REASON,
                "encoding_keys": encoding_keys,
                "thumbnail": frame.get("thumbnail", ""),
            })
        unavailable_actions = [
            "cluster_save",
            "cluster_delete",
            "cluster_rename",
            "cluster_thumbnail",
            "restore_metadata",
        ]
        if not runtime_can_encode:
            unavailable_actions.insert(0, "encode")
        return context._module_state_payload("vibe_transfer", {
            "can_encode": runtime_can_encode,
            "can_write_clusters": False,
            "can_restore_metadata": False,
            "unavailable_actions": unavailable_actions,
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
        self._ensure_loaded()
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
            return context._toast("Vibe encoding is not available in this runtime; use stored encoded Vibe entries.", level="error")
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
            return context._toast(f"Vibe Transfer action is not available in this runtime: {key}", level="info")
        else:
            return None
        self._persist()
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
            "can_encode": False,
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
            "can_write_clusters": False,
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
        self._ensure_loaded()
        reference_images = []
        reference_strengths = []
        reference_info = []
        for frame in list(context.vibe_transfer_frames):
            encodings = frame.get("vibe_encodings") if isinstance(frame.get("vibe_encodings"), dict) else {}
            if not frame.get("is_enabled") or not encodings:
                continue
            try:
                target_ie = _as_float(frame.get("information_extracted"), 1.0)
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
            reference_strengths.append(_as_float(frame.get("reference_strength"), 0.6))
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
