"""Headless Character Reference module state service."""

from __future__ import annotations

from core.nai_character_reference_spec import (
    REFERENCE_TYPES, clamp_strength, cr_profile, normalize_reference_type, source_image_data,
)

import base64
import io
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from core.headless_image_utils import data_url_payload, image_hash, image_to_png_bytes, thumbnail_b64
from core.ref_vibe_library import get_ref_vibe_library, reference_settings, safe_component


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
        context.character_reference_bypass = self._load_bypass(mode)

    def _load_bypass(self, mode: str) -> bool:
        """REFERENCE bypass(사용자 2026-11-25) - 켜면 `ref:` 를 부른 장에는 모듈 칸을 안 보낸다. 모드별 파일에 같이 둔다."""
        try:
            path = self.context._existing_save_path(f"CharacterReferenceModule_{mode}.json")
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            block = data.get(mode) if isinstance(data, dict) else None
            return bool(block.get("bypass")) if isinstance(block, dict) else False
        except Exception:      # noqa: BLE001 - 못 읽으면 끈 채로(모듈 칸이 가는 쪽 = 원래 동작)
            return False

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
        ref_type = normalize_reference_type(raw.get("reference_type"))
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

    def capture_snapshot(self) -> dict[str, Any]:
        self._ensure_loaded()
        frames = [self._persistable_frame(frame) for frame in self.context.character_reference_frames]
        return {"frames": frames, "bypass": bool(getattr(self.context, "character_reference_bypass", False))}

    def restore_snapshot(self, section: Any, image_directory: Path) -> None:
        from core.snapshot_reference_transfer import (
            merge_reference_frames, restore_reference_images, validate_reference_section,
        )

        raw_frames = validate_reference_section(section, "character_reference")
        self._ensure_loaded()
        restore_reference_images(self.context, "character_reference", raw_frames, image_directory)
        frames = [self._frame_from_persisted(raw) for raw in raw_frames]
        # enable 액션의 상대 도구 끄기를 거치면 스냅샷에 기록된 두 도구의 상태가 바뀐다.
        self.context.character_reference_frames = merge_reference_frames(self.context.character_reference_frames, frames)
        # bypass 도 스냅샷과 함께 돌아온다(리뷰 #6) - 이 키가 없는 옛 스냅샷은 지금 값을 둔다
        if isinstance(section, dict) and "bypass" in section:
            self.context.character_reference_bypass = bool(section.get("bypass"))
        self._persist(raise_errors=True)

    def _persist(self, *, raise_errors: bool = False) -> None:
        context = self.context
        mode = self._settings_mode()
        try:
            frames = [self._persistable_frame(frame) for frame in context.character_reference_frames]
            payload = {mode: {"frames": frames, "bypass": bool(getattr(context, "character_reference_bypass", False))}}
            path = context._save_path(f"CharacterReferenceModule_{mode}.json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=4), encoding="utf-8")
        except Exception as exc:
            # 스냅샷은 구역별 실패를 보고해야 한다. 기존 편집 경로의 오류 처리는 유지한다.
            if raise_errors:
                raise
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
        """프레임이 들고 있을 원본(여백 없음 · 2026-11-25 V5).

        4.5 캔버스 여백 · V5 버킷 잘라 내기는 요청 목(api_service -> `adapt_payload`)에서 모델에 맞춰 한다.
        """
        return source_image_data(image)

    def save_storage(self, frame: dict[str, Any]) -> None:
        raw = frame.get("image_bytes")
        file_hash = str(frame.get("file_hash") or "")
        if not raw or not file_hash:
            return
        target = self.context._save_path("character_reference", "images", f"{file_hash}.png")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(raw)
        get_ref_vibe_library(self.context).record("character_reference", file_hash,
                                                 created_at=target.stat().st_mtime)

    def _save_library_settings(self, frame):
        file_hash = str(frame.get("file_hash") or "")
        if file_hash and self.context._existing_save_path("character_reference", "images", f"{file_hash}.png").is_file():
            get_ref_vibe_library(self.context).record("character_reference", file_hash, settings=frame)

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

    def _cr_profile_payload(self) -> dict[str, Any] | None:
        """화면이 쓸 이 모델의 CR 사양(유형 목록 · Strength 상한 · Fidelity 칸)."""
        try:
            spec = self.context._remote_state_service()._current_nai_model_spec()
        except Exception:
            return None
        profile = cr_profile(spec)
        return profile.to_payload() if profile is not None else None

    def module_state(self) -> dict[str, Any]:
        self._ensure_loaded()
        display_names = get_ref_vibe_library(self.context).display_names(
            "character_reference", [f.get("file_hash", "") for f in self.context.character_reference_frames]
        )
        profile = self._cr_profile_payload()
        anima = self._anima_block()
        # Outfit 을 못 받는 모델(V4.5)에선 Outfit 칸을 꺼 둔 것처럼 보인다(사용자 지시 2026-11-25). 켬 설정은 그대로 -
        # 요청 목(adapt_payload)이 어차피 뺀다 · V5 로 돌아가면 다시 켜진 채다. ANIMA 칸은 NAI 사양과 무관하다.
        no_outfit = anima is None and profile is not None and not profile.get("outfit")
        frames = []
        for index, frame in enumerate(self.context.character_reference_frames):
            frames.append({
                "index": index,
                "file_hash": frame.get("file_hash", ""),
                "file_name": frame.get("file_name", ""),
                "display_name": display_names.get(frame.get("file_hash", ""), ""),
                "is_enabled": bool(frame.get("is_enabled")),
                "reference_type": frame.get("reference_type", "character&style"),
                "strength": _as_float(frame.get("strength"), 1.0),
                "fidelity": _as_float(frame.get("fidelity"), 0.8),
                "thumbnail": frame.get("thumbnail", ""),
                "is_blocked": no_outfit and frame.get("reference_type") == "costume",
            })
        state = {"is_naid45": self.context._is_naid45_model(), "frames": frames,
                 "cr_profile": profile, "bypass": bool(getattr(self.context, "character_reference_bypass", False))}
        if anima is not None:
            state["anima"] = anima
            # ANIMA 줄은 칸마다 그 그림의 캐릭터 프롬프트를 보여 주고 고친다(사용자 지시 2026-11-05) - 저장은 그림 쪽
            # (character_reference/metadata/<해시>.json · NAI 보관함의 '캐릭터 프롬프트' 와 같은 값).
            prompts = get_ref_vibe_library(self.context).character_prompts([f["file_hash"] for f in frames])
            for frame in frames:
                frame.update(prompts.get(frame["file_hash"]) or {"character_prompt": "", "character_uc": ""})
        return self.context._module_state_payload("character_reference", state)

    # ----- ANIMA 참조(Ref Adapter v2 · 사용자 지정 2026-11-05) -----
    # 관리형 ANIMA(COMFYUI 모드 + 내장 엔진)에서만. 칸은 위의 것 그대로(모드별 파일이라 NAI 의 칸과 따로) - 다른 것은
    # 설정(참조 세기 등 · 칸마다가 아니라 하나) · 켤 수 있는 수(MAX_REFS) · 추가 구성 요소 설치 상태.
    def _anima_mode(self) -> bool:
        if self._settings_mode() != "COMFYUI":
            return False
        try:
            from core.anima_engine import integration
            return integration.managed_selected(self.context)
        except Exception:
            return False

    def _anima_engine_root(self) -> str:
        from core.anima_engine import integration
        from core.anima_engine.settings import load_settings
        return load_settings(integration.save_root_of(self.context)).engine_root or ""

    def _anima_block(self) -> dict[str, Any] | None:
        if not self._anima_mode():
            return None
        from core.anima_engine import ref_adapter, reference
        return {"settings": reference.load_settings(self.context), "defaults": dict(reference.REF_DEFAULTS),
                "max_refs": reference.MAX_REFS, "addon": ref_adapter.status(self._anima_engine_root()),
                "character_prompts": reference.load_prompt_option(self.context)}

    def _anima_param(self, key: str, value: Any) -> dict[str, Any] | list | None:
        # 추가 구성 요소 받기는 여기가 아니라 POST /api/anima-engine/ref-adapter/install(엔진 설치처럼 이 PC 에서만)
        from core.anima_engine import reference
        if not self._anima_mode():
            return self.context._toast("ANIMA 참조는 내장 ANIMA 엔진에서만 씁니다.", level="info")
        try:
            reference.save_setting(self.context, key[len("anima_"):], value)
        except ValueError:
            return self.context._toast("참조 설정 값을 확인해 주세요.", level="error")
        return self.module_state()

    def _anima_limit_reached(self, index: int | None = None) -> bool:
        """ANIMA 에서 하나 더 켜면 MAX_REFS 를 넘는가(index = 켜려는 칸 - 이미 켜져 있으면 넘지 않는다)."""
        if not self._anima_mode():
            return False
        from core.anima_engine.reference import MAX_REFS
        frames = self.context.character_reference_frames
        on = sum(1 for i, f in enumerate(frames) if f.get("is_enabled") and i != index)
        return on >= MAX_REFS

    def _anima_limit_toast(self):
        from core.anima_engine.reference import MAX_REFS
        return [self.context._toast(f"ANIMA 참조는 {MAX_REFS}장까지 켭니다 - 다른 칸을 끄고 켜 주세요.", level="info"),
                self.module_state()]

    def set_param(self, key: str, value: Any) -> dict[str, Any] | None:
        context = self.context
        self._ensure_loaded()
        if key.startswith("anima_"):
            return self._anima_param(key, value)
        if key == "upload_image":
            # 값 = base64 그대로, 또는 {"image": base64, "reference_type": 칸 유형}(의상 · 스타일 칸 업로드 · 2026-11-25)
            text = str(value or "")
            upload_type = ""
            if text.lstrip().startswith("{"):
                try:
                    request = json.loads(text)
                    text = str(request.get("image") or "")
                    upload_type = normalize_reference_type(request.get("reference_type"), "")
                except (ValueError, TypeError, AttributeError):
                    return context._toast("Character Reference upload request could not be read", level="error")
            image_bytes = base64.b64decode(data_url_payload(text))
            frame = self.frame_from_bytes(image_bytes, file_name="remote_upload.png")
            if upload_type:
                frame["reference_type"] = upload_type
            # 같은 이미지가 이미 있으면 새 칸을 만들지 않는다(사용자 제보 2026-10-23: 결과 우클릭 > Set as ... 를 누를 때마다
            # 같은 그림이 R1 · R2 · R3 으로 쌓였다). 켜짐 상태는 그대로 - 업로드는 원래 끈 채로 넣는다.
            existing = next((f for f in context.character_reference_frames if f.get("file_hash") == frame["file_hash"]), None)
            if existing is not None:
                slot = context.character_reference_frames.index(existing) + 1
                return [context._toast(f"이미 R{slot} 칸에 있는 이미지입니다.", level="info"), self.module_state()]
            self.save_storage(frame)
            context.character_reference_frames.append(frame)
        elif key.startswith("remove_frame_"):
            index = context._index_from_key(key, "remove_frame_")
            if index is not None and 0 <= index < len(context.character_reference_frames):
                context.character_reference_frames.pop(index)
        elif key == "move_frame":
            # 칸 순서 바꾸기(끌어 놓기 · 사용자 지시 2026-11-06) - ANIMA 는 이 차례가 붙이는 차례이자 left/right 이다.
            # 칸은 해시로 지목한다: 다른 탭이 칸을 빼거나 옮긴 뒤의 낡은 번호가 엉뚱한 칸을 옮기지 않게.
            try:
                request = json.loads(str(value or ""))
                file_hash = str(request.get("file_hash") or "")
                target = int(request.get("to"))
            except (ValueError, TypeError, AttributeError):
                return context._toast("칸 순서 요청을 읽지 못했습니다.", level="error")
            frames = context.character_reference_frames
            index = next((i for i, f in enumerate(frames) if str(f.get("file_hash") or "") == file_hash), None)
            if index is None or not file_hash:
                return self.module_state()
            target = max(0, min(len(frames) - 1, target))
            if target == index:
                return self.module_state()
            frames.insert(target, frames.pop(index))
        elif key == "bypass":
            # REFERENCE bypass 체크박스(사용자 2026-11-25) - 칸은 그대로 두고 `ref:` 를 부른 장에만 안 보낸다(api_service)
            context.character_reference_bypass = str(value).strip().lower() in ("1", "true", "on", "yes")
        elif key == "clear_frames":
            # 프레임만 비운다 - storage(save/character_reference/images)는 보존.
            context.character_reference_frames.clear()
        elif key.startswith("enable_"):
            index = context._index_from_key(key, "enable_")
            if index is not None and 0 <= index < len(context.character_reference_frames):
                enabling = context._coerce_bool(value)
                if enabling and self._anima_limit_reached(index):
                    return self._anima_limit_toast()
                context.character_reference_frames[index]["is_enabled"] = enabling
                if enabling:
                    self.save_storage(context.character_reference_frames[index])
                    self._save_library_settings(context.character_reference_frames[index])
                    context._disable_all_vibe_frames()
        elif key.startswith("strength_"):
            index = context._index_from_key(key, "strength_")
            if index is not None and 0 <= index < len(context.character_reference_frames):
                # 저장은 0~5(V5 상한) - 모델 상한(4.5 = 1)으로 자르는 것은 요청 목이 한다.
                context.character_reference_frames[index]["strength"] = clamp_strength(value)
                self._save_library_settings(context.character_reference_frames[index])
        elif key.startswith("fidelity_"):
            index = context._index_from_key(key, "fidelity_")
            if index is not None and 0 <= index < len(context.character_reference_frames):
                context.character_reference_frames[index]["fidelity"] = max(0.0, min(1.0, float(value)))
                self._save_library_settings(context.character_reference_frames[index])
        elif key.startswith("ref_type_"):
            index = context._index_from_key(key, "ref_type_")
            ref_type = str(value or "").strip().lower()
            if index is not None and 0 <= index < len(context.character_reference_frames) and ref_type in REFERENCE_TYPES:
                context.character_reference_frames[index]["reference_type"] = ref_type
                self._save_library_settings(context.character_reference_frames[index])
        elif key == "get_storage":
            return self.scan_storage()
        elif key == "apply_storage":
            try:
                request = json.loads(value) if str(value or "").lstrip().startswith("{") else {"file_hash": value}
                file_hash = safe_component(request.get("file_hash"))
            except (ValueError, TypeError, AttributeError):
                return context._toast("Invalid Character Reference storage request", level="error")
            library = get_ref_vibe_library(context)
            settings = reference_settings(library.metadata("character_reference", file_hash).get("settings"))
            if isinstance(request.get("settings"), dict):
                settings = reference_settings({**settings, **request["settings"]})
            # 이미 활성에 있으면 새 칸을 만들지 않고 그 칸을 켠다(사용자 제보 2026-10-23 - [적용] 을 누를 때마다 쌓였다).
            existing = next((f for f in context.character_reference_frames if str(f.get("file_hash") or "") == file_hash), None)
            if self._anima_limit_reached(None if existing is None else context.character_reference_frames.index(existing)):
                return self._anima_limit_toast()
            if existing is not None:
                existing["is_enabled"] = True
                if isinstance(request.get("settings"), dict):
                    existing.update(settings)
                    library.record("character_reference", file_hash, used=True, settings=settings)
                else:
                    library.record("character_reference", file_hash, used=True)
                context._disable_all_vibe_frames()
                self._persist()
                return self.module_state()
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
            frame.update(settings)
            library.record("character_reference", file_hash, used=True, settings=settings,
                           created_at=image_path.stat().st_mtime)
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
        # 칸 번호(1부터)는 꺼 둔 칸까지 센다 - 화면의 칸 차례와 같게
        enabled = [(index + 1, frame) for index, frame in enumerate(list(context.character_reference_frames))
                   if frame.get("is_enabled")]
        if not enabled:
            return {}
        descriptions = []
        images = []
        ie = []
        strengths = []
        fidelities = []
        slots = []
        for slot, frame in enabled:
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
            strength = round(clamp_strength(frame.get("strength")) * 20) / 20.0
            fidelity = 1.0 - max(0.0, min(1.0, _as_float(frame.get("fidelity"), 0.8)))
            fidelities.append(round(fidelity * 20) / 20.0)
            strengths.append(strength)
            # 히스토리 '레퍼런스 정보' 용 - 목록과 같은 차례 · api_service 가 실제로 보냈는지를 붙여 남긴다
            slots.append({
                "slot": slot,
                "file_hash": str(frame.get("file_hash") or ""),
                "reference_type": str(frame.get("reference_type") or "character&style"),
                "strength": strength,
                "fidelity": round(max(0.0, min(1.0, _as_float(frame.get("fidelity"), 0.8))), 2),
            })
        if not descriptions:
            return {}
        try:
            names = get_ref_vibe_library(context).display_names("character_reference", [s["file_hash"] for s in slots])
        except Exception:      # noqa: BLE001 - 이름은 보여 주기용이다. 못 읽어도 생성은 간다
            names = {}
        for entry in slots:
            entry["name"] = names.get(entry["file_hash"], "") or entry["file_hash"][:16]
        return {
            "director_reference_descriptions": descriptions,
            "director_reference_images": images,
            "director_reference_information_extracted": ie,
            "director_reference_strength_values": strengths,
            "director_reference_secondary_strength_values": fidelities,
            "controlnet_strength": 1,
            "inpaintImg2ImgStrength": 1,
            "normalize_reference_strength_multiple": True,
            "_reference_slots": slots,
            # 켜 두었으면 요청 목이 이 장에 `ref:` 호출이 있을 때만 위 목록을 빼고 보낸다
            **({"_reference_bypass": True} if getattr(context, "character_reference_bypass", False) else {}),
        }
