from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from core.prompt_context import PromptContext
from core.wildcard_processor import WildcardProcessor, split_tags_smart


def _default_save_root() -> Path:
    user_data_dir = os.environ.get("NAIA_USER_DATA_DIR")
    if user_data_dir:
        return Path(user_data_dir).expanduser().resolve() / "save"
    return Path("save")


def _coerce_save_root(save_root: Path | str | None = None) -> Path:
    return Path(save_root).expanduser().resolve() if save_root is not None else _default_save_root()


def _legacy_save_fallback_enabled() -> bool:
    if os.environ.get("NAIA_DISABLE_LEGACY_SAVE_FALLBACK") == "1":
        return False
    if os.environ.get("NAIA_ELECTRON") == "1":
        return False
    return True


def _existing_character_settings_path(mode: str = "NAI", *, save_root: Path | str | None = None) -> Path:
    primary = character_settings_path(mode, save_root=save_root)
    if primary.exists():
        return primary
    legacy = Path("save").resolve() / primary.name
    if _legacy_save_fallback_enabled() and legacy != primary.resolve() and legacy.exists():
        return legacy
    return primary


def _save_root_from_context(app_context: Any) -> Path | None:
    runtime_paths = getattr(app_context, "runtime_paths", None)
    save_dir = getattr(runtime_paths, "save_dir", None)
    return Path(save_dir) if save_dir is not None else None


def character_settings_path(mode: str = "NAI", *, save_root: Path | str | None = None) -> Path:
    return _coerce_save_root(save_root) / f"CharacterModule_{str(mode or 'NAI').upper()}.json"


def default_character_settings() -> dict:
    return {
        "is_active": False,
        "reroll_on_generate": False,
        "character_frames": [],
    }


def normalize_slot_state(value: Any, is_enabled: bool = False) -> str:
    state = str(value or "").strip().lower()
    if state in {"active", "inactive", "cold"}:
        return state
    return "active" if is_enabled else "inactive"


def normalize_character_settings(raw: dict | None) -> dict:
    data = raw if isinstance(raw, dict) else {}
    settings = default_character_settings()
    settings["is_active"] = bool(data.get("is_active", settings["is_active"]))
    settings["reroll_on_generate"] = bool(data.get("reroll_on_generate", settings["reroll_on_generate"]))
    frames = data.get("character_frames", [])
    normalized_frames = []
    if isinstance(frames, list):
        for frame in frames:
            if not isinstance(frame, dict):
                continue
            is_enabled = bool(frame.get("is_enabled", False))
            slot_state = normalize_slot_state(frame.get("slot_state"), is_enabled)
            normalized_frames.append({
                "prompt": str(frame.get("prompt") or ""),
                "uc": str(frame.get("uc") or ""),
                "is_enabled": slot_state == "active",
                "slot_state": slot_state,
                "return_slot_state": str(frame.get("return_slot_state") or ""),
                "custom_name": str(frame.get("custom_name") or frame.get("slot_name") or ""),
            })
    settings["character_frames"] = normalized_frames
    return settings


def _checked(widget: Any) -> bool:
    try:
        return bool(widget is not None and widget.isChecked())
    except Exception:
        return False


def loaded_character_module_has_widget_state(module: Any) -> bool:
    return getattr(module, "activate_checkbox", None) is not None


def loaded_character_module_is_active(module: Any) -> bool:
    return _checked(getattr(module, "activate_checkbox", None))


def loaded_character_module_reroll_on_generate(module: Any) -> bool:
    return (
        loaded_character_module_is_active(module)
        and _checked(getattr(module, "reroll_on_generate_checkbox", None))
    )


def load_character_settings(
    mode: str = "NAI",
    path: Path | str | None = None,
    *,
    save_root: Path | str | None = None,
) -> dict:
    mode_key = str(mode or "NAI").upper()
    target = Path(path) if path is not None else _existing_character_settings_path(mode_key, save_root=save_root)
    try:
        if target.exists():
            data = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get(mode_key), dict):
                return normalize_character_settings(data.get(mode_key))
            return normalize_character_settings(data)
    except Exception as exc:
        print(f"[ERROR] Character settings load failed: {exc}")
    return default_character_settings()


def active_character_frames(settings: dict | None) -> list[dict]:
    normalized = normalize_character_settings(settings)
    if not normalized.get("is_active"):
        return []
    return [
        frame
        for frame in normalized.get("character_frames", [])
        if frame.get("slot_state") == "active" and str(frame.get("prompt") or "").strip()
    ]


def _get_prompt_context(app_context, *, reuse_current_context: bool = True) -> PromptContext:
    existing = getattr(app_context, "current_prompt_context", None)
    if reuse_current_context and existing is not None:
        return existing
    source_row = getattr(app_context, "current_source_row", None)
    if source_row is None:
        source_row = pd.Series({}, name="character_headless")
    return PromptContext(source_row=source_row, settings={})


def _expand_character_text(text: str, processor: WildcardProcessor | None, context: PromptContext) -> str:
    pieces = [piece.strip() for piece in split_tags_smart(str(text or ""))]
    pieces = [piece for piece in pieces if piece]
    if not pieces:
        return ""
    if processor is None:
        return ", ".join(pieces)
    return ", ".join(processor.expand_tags(pieces, context))


def character_params_from_settings(
    app_context,
    mode: str = "NAI",
    settings: dict | None = None,
    *,
    reuse_current_context: bool = True,
    save_root: Path | str | None = None,
) -> dict:
    if save_root is None:
        save_root = _save_root_from_context(app_context)
    normalized = (
        normalize_character_settings(settings)
        if settings is not None
        else load_character_settings(mode, save_root=save_root)
    )
    frames = active_character_frames(normalized)
    if not frames:
        return {"characters": None}

    processor = None
    wildcard_manager = getattr(app_context, "wildcard_manager", None)
    if wildcard_manager is not None:
        processor = WildcardProcessor(wildcard_manager)
    context = _get_prompt_context(app_context, reuse_current_context=reuse_current_context)

    characters = []
    ucs = []
    for frame in frames:
        prompt = _expand_character_text(frame.get("prompt", ""), processor, context)
        uc = _expand_character_text(frame.get("uc", ""), processor, context)
        if prompt:
            characters.append(prompt)
            ucs.append(uc)

    if not characters:
        return {"characters": None}
    return {
        "characters": characters,
        "uc": ucs,
    }


def _format_processed_preview(characters: list[str], ucs: list[str]) -> str:
    display_text = []
    for i, (prompt, uc) in enumerate(zip(characters, ucs)):
        display_text.append(f"C{i + 1}: {prompt}")
        display_text.append(f"UC{i + 1}: {uc}\n")
    return "\n".join(display_text)


def character_state_from_settings(
    settings: dict | None,
    app_context=None,
    mode: str = "NAI",
    *,
    save_root: Path | str | None = None,
) -> dict:
    if save_root is None and app_context is not None:
        save_root = _save_root_from_context(app_context)
    normalized = (
        normalize_character_settings(settings)
        if settings is not None
        else load_character_settings(mode, save_root=save_root)
    )
    frames = normalized.get("character_frames", [])
    characters = []
    for idx, frame in enumerate(frames):
        slot_state = normalize_slot_state(frame.get("slot_state"), bool(frame.get("is_enabled")))
        characters.append({
            "id": idx + 1,
            "active": slot_state == "active",
            "slot_state": slot_state,
            "return_slot_state": str(frame.get("return_slot_state") or ""),
            "custom_name": str(frame.get("custom_name") or ""),
            "prompt": str(frame.get("prompt") or ""),
            "uc": str(frame.get("uc") or ""),
        })

    processed_characters: list[str] = []
    processed_ucs: list[str] = []
    if app_context is not None:
        params = character_params_from_settings(
            app_context,
            mode=mode,
            settings=normalized,
            reuse_current_context=False,
            save_root=save_root,
        )
        processed_characters = [str(value) for value in params.get("characters") or []]
        processed_ucs = [str(value) for value in params.get("uc") or []]

    return {
        "type": "module_state",
        "module_id": "character",
        "activated": bool(normalized.get("is_active")),
        "reroll_on_generate": bool(normalized.get("reroll_on_generate")),
        "characters": characters,
        "character_count": len(characters),
        "active_count": sum(1 for item in characters if item.get("active")),
        "cold_count": sum(1 for item in characters if item.get("slot_state") == "cold"),
        "processed_characters": processed_characters,
        "processed_ucs": processed_ucs,
        "character_token_count": 0,
        "processed_preview_text": _format_processed_preview(processed_characters, processed_ucs),
    }
