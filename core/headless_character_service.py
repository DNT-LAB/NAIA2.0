"""Headless Character module settings service."""

from __future__ import annotations

import json
from typing import Any


class HeadlessCharacterService:
    def __init__(self, context: Any):
        self.context = context

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
        state["headless"] = True
        return state

    def set_param(self, key: str, value: Any) -> dict[str, Any] | None:
        context = self.context
        mode = context.get_api_mode()
        settings = self.settings_cache()
        frames = settings.setdefault("character_frames", [])
        if key == "activated":
            settings["is_active"] = context._coerce_bool(value)
        elif key == "reroll_on_generate":
            settings["reroll_on_generate"] = context._coerce_bool(value)
        elif key == "add_character":
            frames.append({"prompt": "", "uc": "", "is_enabled": True, "slot_state": "active", "custom_name": ""})
        elif key == "preview_refresh":
            pass
        elif key.startswith("remove_character_"):
            index = context._index_from_key(key, "remove_character_")
            if index is not None and 0 <= index < len(frames) and len(frames) > 1:
                frames.pop(index)
        elif key.startswith("char_prompt_"):
            index = context._index_from_key(key, "char_prompt_")
            if index is not None:
                self.ensure_frame(frames, index)["prompt"] = str(value or "")
        elif key.startswith("char_uc_"):
            index = context._index_from_key(key, "char_uc_")
            if index is not None:
                self.ensure_frame(frames, index)["uc"] = str(value or "")
        elif key.startswith("char_active_"):
            index = context._index_from_key(key, "char_active_")
            if index is not None:
                frame = self.ensure_frame(frames, index)
                active = context._coerce_bool(value)
                frame["is_enabled"] = active
                frame["slot_state"] = "active" if active else "inactive"
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
        elif key.startswith("char_slot_name_"):
            index = context._index_from_key(key, "char_slot_name_")
            if index is not None:
                self.ensure_frame(frames, index)["custom_name"] = str(value or "")
        else:
            return None
        self.save_settings(mode, settings)
        return self.state()
