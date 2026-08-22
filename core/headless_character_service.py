"""Headless Character module settings service."""

from __future__ import annotations

import json
import threading
from typing import Any


# ⚠️ "활성 슬롯은 최소 하나" 는 **UI 규칙**이다(마지막 활성 슬롯의 ▼ 를 숨긴다).
# 백엔드에 강제하면 안 된다 - 활성 0 은 기존 계약상 정상 상태이고, 그걸 막으면
# 두 가지가 깨진다(실측):
#   · 유일한 슬롯을 Cold 로 보내 캐릭터 없이 생성
#     (test_no_active_frames_does_not_consume_snapshot)
#   · 슬롯 하나를 비활성으로 두고 조건부 규칙이 건너뛰는지 보는 경로
#     (test_inactive_slot_falls_back_to_the_frame)
# 여기서는 정렬 불변식만 세운다(core/character_settings.sort_character_frames).


class HeadlessCharacterService:
    def __init__(self, context: Any):
        self.context = context
        # Serializes every read-modify-save commit on the shared settings dict
        # and CharacterModule_{MODE}.json - WS set_param runs on the event loop
        # while REST bulk applies run on worker threads.
        self._commit_lock = threading.RLock()

    def settings_by_mode(self) -> dict[str, dict[str, Any]]:
        cache = getattr(self.context, "_character_settings_state", None)
        if not isinstance(cache, dict):
            cache = {}
            self.context._character_settings_state = cache
        return cache

    def settings_cache(self) -> dict[str, Any]:
        from core.character_settings import load_character_settings

        mode = self.context.get_api_mode()
        cache = self.settings_by_mode()
        if mode not in cache:
            cache[mode] = load_character_settings(
                mode,
                path=self.context._existing_save_path(f"CharacterModule_{str(mode or 'NAI').upper()}.json"),
            )
        return cache[mode]

    def save_settings(self, mode: str, settings: dict[str, Any]) -> None:
        from core.character_settings import normalize_character_settings

        mode_key = str(mode or "NAI").upper()
        normalized = normalize_character_settings(settings)
        self.settings_by_mode()[mode_key] = normalized
        path = self.context._save_path(f"CharacterModule_{mode_key}.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({mode_key: normalized}, ensure_ascii=False, indent=4),
            encoding="utf-8",
        )

    @staticmethod
    def ensure_frame(frames: list[dict[str, Any]], index: int) -> dict[str, Any]:
        while len(frames) <= index:
            frames.append({"prompt": "", "uc": "", "is_enabled": False, "slot_state": "inactive", "custom_name": ""})
        frame = frames[index]
        if not isinstance(frame, dict):
            frame = {"prompt": "", "uc": "", "is_enabled": False, "slot_state": "inactive", "custom_name": ""}
            frames[index] = frame
        return frame

    def state(self) -> dict[str, Any]:
        from core.character_settings import character_state_from_settings

        mode = self.context.get_api_mode()
        settings = self.settings_cache()
        state = character_state_from_settings(settings, app_context=self.context, mode=mode)
        state["available"] = True
        state["runtime"] = "web"
        return state

    def apply_asset(self, prompt: str, uc: str, mode: str = "c1") -> dict[str, Any]:
        with self._commit_lock:
            return self._apply_asset_locked(prompt, uc, mode)

    def _apply_asset_locked(self, prompt: str, uc: str, mode: str = "c1") -> dict[str, Any]:
        """Bulk slot apply for the Character Asset library.

        Shares set_param's commit invariants (conditional metadata cleanup,
        save_settings, snapshot invalidation) instead of letting callers poke
        the settings cache directly.

        - "c1": Dev0714 assign_c1 parity — write frames[0], make it the only
          active slot. Cold slots keep their state; custom names/uuids are
          preserved (only prompt/uc/state fields change).
        - "add_slot": append a fresh active frame.
        Either way the module itself is activated.
        """
        context = self.context
        api_mode = context.get_api_mode()
        settings = self.settings_cache()
        frames = settings.setdefault("character_frames", [])
        apply_mode = str(mode or "c1").strip().lower()
        if apply_mode == "add_slot":
            frames.append({
                "prompt": str(prompt or ""),
                "uc": str(uc or ""),
                "is_enabled": True,
                "slot_state": "active",
                "custom_name": "",
            })
        elif apply_mode == "c1":
            frame = self.ensure_frame(frames, 0)
            frame["prompt"] = str(prompt or "")
            frame["uc"] = str(uc or "")
            frame["is_enabled"] = True
            frame["slot_state"] = "active"
            for other in frames[1:]:
                if not isinstance(other, dict):
                    continue
                if str(other.get("slot_state") or "").strip().lower() == "cold":
                    continue
                other["is_enabled"] = False
                other["slot_state"] = "inactive"
        else:
            raise ValueError(f"unknown apply mode: {apply_mode}")
        settings["is_active"] = True
        prompt_context = getattr(context, "current_prompt_context", None)
        metadata = getattr(prompt_context, "metadata", None)
        if isinstance(metadata, dict):
            metadata.pop("conditional_character_overrides", None)
            metadata.pop("_conditional_character_slots", None)
            metadata.pop("conditional_character_skips", None)
        self.save_settings(api_mode, settings)
        from core.character_settings import clear_character_roll_snapshot

        clear_character_roll_snapshot(context, api_mode)
        return self.state()

    def set_param(self, key: str, value: Any) -> dict[str, Any] | None:
        with self._commit_lock:
            return self._set_param_locked(key, value)

    def _set_param_locked(self, key: str, value: Any) -> dict[str, Any] | None:
        context = self.context
        mode = context.get_api_mode()
        settings = self.settings_cache()
        frames = settings.setdefault("character_frames", [])
        # SSOT snapshot bookkeeping:
        #   - content edits invalidate the snapshot (next authoritative roll reflects
        #     the new content),
        #   - "preview_refresh" performs ONE fresh roll and stores it (manual seed),
        #   - "activated" / "reroll_on_generate" toggles do NOT touch the snapshot.
        invalidate_snapshot = False
        refresh_snapshot = False
        if key == "activated":
            settings["is_active"] = context._coerce_bool(value)
        elif key == "reroll_on_generate":
            settings["reroll_on_generate"] = context._coerce_bool(value)
        elif key == "add_character":
            frames.append({"prompt": "", "uc": "", "is_enabled": True, "slot_state": "active", "custom_name": ""})
            invalidate_snapshot = True
        elif key == "preview_refresh":
            refresh_snapshot = True
        elif key.startswith("remove_character_"):
            index = context._index_from_key(key, "remove_character_")
            if index is not None and 0 <= index < len(frames) and len(frames) > 1:
                # 삭제로 활성이 0이 될 수 있다. 승격시키지 않는다 - 캐릭터 0은
                # 유효한 상태이고(모듈을 끄거나 Cold 로 비우는 경로가 이미 그렇다)
                # 사용자가 지우려던 것을 되살리는 쪽이 더 놀랍다.
                frames.pop(index)
                invalidate_snapshot = True
        elif key.startswith("char_prompt_"):
            index = context._index_from_key(key, "char_prompt_")
            if index is not None:
                self.ensure_frame(frames, index)["prompt"] = str(value or "")
                invalidate_snapshot = True
        elif key.startswith("char_uc_"):
            index = context._index_from_key(key, "char_uc_")
            if index is not None:
                self.ensure_frame(frames, index)["uc"] = str(value or "")
                invalidate_snapshot = True
        elif key.startswith("char_active_"):
            index = context._index_from_key(key, "char_active_")
            if index is not None:
                frame = self.ensure_frame(frames, index)
                active = context._coerce_bool(value)
                frame["is_enabled"] = active
                frame["slot_state"] = "active" if active else "inactive"
                invalidate_snapshot = True
        elif key.startswith("char_slot_state_"):
            index = context._index_from_key(key, "char_slot_state_")
            if index is not None:
                frame = self.ensure_frame(frames, index)
                requested = str(value or "").strip().lower()
                if requested == "restore":
                    requested = str(frame.get("return_slot_state") or "inactive")
                if requested in {"active", "inactive", "cold"}:
                    if requested == "cold":
                        frame["return_slot_state"] = str(frame.get("slot_state") or "inactive")
                    frame["slot_state"] = requested
                    frame["is_enabled"] = requested == "active"
                    invalidate_snapshot = True
        elif key.startswith("char_slot_name_"):
            index = context._index_from_key(key, "char_slot_name_")
            if index is not None:
                self.ensure_frame(frames, index)["custom_name"] = str(value or "")
                invalidate_snapshot = True
        else:
            return None
        prompt_context = getattr(context, "current_prompt_context", None)
        metadata = getattr(prompt_context, "metadata", None)
        if isinstance(metadata, dict):
            metadata.pop("conditional_character_overrides", None)
            metadata.pop("_conditional_character_slots", None)
            metadata.pop("conditional_character_skips", None)
        self.save_settings(mode, settings)
        # SSOT snapshot maintenance (after save so the roll sees the latest frames).
        if refresh_snapshot:
            from core.character_settings import roll_character_params

            roll_character_params(
                context,
                mode=mode,
                settings=settings,
                reuse_current_context=False,
            )
        elif invalidate_snapshot:
            from core.character_settings import clear_character_roll_snapshot

            # The panel edits the active mode's frames — invalidate only that mode's
            # snapshot so an unrelated mode's valid roll is preserved.
            clear_character_roll_snapshot(context, mode)
        return self.state()
