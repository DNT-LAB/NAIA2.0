from __future__ import annotations

import json
import os
import uuid
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


def _new_character_uuid() -> str:
    return uuid.uuid4().hex


def _frame_uuid(frame: dict[str, Any], *, create: bool = False) -> str:
    for key in ("uuid", "slot_uuid"):
        value = str(frame.get(key) or "").strip()
        if value:
            return value
    legacy = frame.get("id")
    if isinstance(legacy, str):
        value = legacy.strip()
        if value and not value.isdigit():
            return value
    return _new_character_uuid() if create else ""


def _normalize_character_settings_with_migration(raw: dict | None) -> tuple[dict, bool]:
    data = raw if isinstance(raw, dict) else {}
    settings = default_character_settings()
    settings["is_active"] = bool(data.get("is_active", settings["is_active"]))
    settings["reroll_on_generate"] = bool(data.get("reroll_on_generate", settings["reroll_on_generate"]))
    frames = data.get("character_frames", [])
    normalized_frames = []
    migrated = False
    if isinstance(frames, list):
        for frame in frames:
            if not isinstance(frame, dict):
                continue
            is_enabled = bool(frame.get("is_enabled", False))
            slot_state = normalize_slot_state(frame.get("slot_state"), is_enabled)
            frame_uuid = _frame_uuid(frame, create=True)
            if frame.get("uuid") != frame_uuid:
                migrated = True
            normalized_frames.append({
                "uuid": frame_uuid,
                "prompt": str(frame.get("prompt") or ""),
                "uc": str(frame.get("uc") or ""),
                "is_enabled": slot_state == "active",
                "slot_state": slot_state,
                "return_slot_state": str(frame.get("return_slot_state") or ""),
                "custom_name": str(frame.get("custom_name") or frame.get("slot_name") or ""),
            })
    settings["character_frames"] = normalized_frames
    return settings, migrated


def normalize_character_settings(raw: dict | None) -> dict:
    settings, _migrated = _normalize_character_settings_with_migration(raw)
    return settings


def _save_migrated_character_settings(path: Path, mode_key: str, settings: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({mode_key: settings}, ensure_ascii=False, indent=4), encoding="utf-8")
    except Exception as exc:
        print(f"[WARN] Character settings migration save failed: {exc}")


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
            raw_settings = data.get(mode_key) if isinstance(data, dict) and isinstance(data.get(mode_key), dict) else data
            normalized, migrated = _normalize_character_settings_with_migration(raw_settings)
            if migrated:
                _save_migrated_character_settings(target, mode_key, normalized)
            return normalized
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


def _conditional_character_override(app_context, *, reuse_current_context: bool) -> dict | None:
    if not reuse_current_context:
        return None
    context = getattr(app_context, "current_prompt_context", None)
    metadata = getattr(context, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    override = metadata.get("conditional_character_overrides")
    if not isinstance(override, dict):
        return None
    if "characters" not in override:
        return None
    characters = [str(value) for value in override.get("characters") or [] if str(value).strip()]
    if not characters:
        return {"characters": None}
    raw_ucs = [str(value) for value in override.get("uc") or []]
    ucs = [raw_ucs[index] if index < len(raw_ucs) else "" for index in range(len(characters))]
    return {
        "characters": characters,
        "uc": ucs,
    }


def conditional_character_override_active(app_context) -> bool:
    """True if an active per-run conditional character override is present on the
    current prompt context (e.g. produced by `char:1+=__wc__` at after_wildcard).
    Such an override outranks the SSOT snapshot for the actual payload."""
    return _conditional_character_override(app_context, reuse_current_context=True) is not None


CHARACTER_FREEZE_STORE_ATTR = "_character_freeze_store"


def _character_freeze_store(app_context, *, create: bool = False) -> dict[str, dict[str, str]] | None:
    if app_context is None:
        return None
    store = getattr(app_context, CHARACTER_FREEZE_STORE_ATTR, None)
    if isinstance(store, dict):
        return store
    if not create:
        return None
    store = {}
    setattr(app_context, CHARACTER_FREEZE_STORE_ATTR, store)
    return store


def read_frozen_character_slots(app_context) -> dict[str, dict[str, str]]:
    store = _character_freeze_store(app_context)
    if not isinstance(store, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for slot, payload in store.items():
        if not isinstance(payload, dict):
            continue
        prompt = str(payload.get("prompt") or "")
        if not prompt.strip():
            continue
        out[str(slot)] = {"prompt": prompt, "uc": str(payload.get("uc") or "")}
    return out


def frozen_character_slots_payload(app_context) -> list[dict[str, str]]:
    return [
        {"slot": slot, "prompt": payload["prompt"], "uc": payload.get("uc", "")}
        for slot, payload in sorted(read_frozen_character_slots(app_context).items())
    ]


def set_frozen_character_slot(app_context, slot: Any, prompt: Any, uc: Any = "") -> bool:
    slot_key = str(slot or "").strip()
    prompt_text = str(prompt or "").strip()
    if not slot_key or not prompt_text:
        return False
    store = _character_freeze_store(app_context, create=True)
    if store is None:
        return False
    store[slot_key] = {"prompt": prompt_text, "uc": str(uc or "")}
    return True


def clear_frozen_character_slot(app_context, slot: Any | None = None) -> bool:
    store = _character_freeze_store(app_context)
    if not isinstance(store, dict):
        return False
    if slot is None:
        changed = bool(store)
        store.clear()
        return changed
    return store.pop(str(slot or "").strip(), None) is not None


def _active_frame_slot_ids(frames: list[dict]) -> list[str]:
    return [str(_frame_uuid(frame) or index) for index, frame in enumerate(frames, 1)]


def _snapshot_result(snapshot: dict, frame_slot_ids: list[str]) -> dict:
    characters = [str(value) for value in snapshot.get("characters") or []]
    ucs = [str(value) for value in snapshot.get("uc") or []]
    ids = [str(value) for value in snapshot.get("character_ids") or [] if str(value).strip()]
    if not ids:
        ids = frame_slot_ids[:len(characters)]
    while len(ucs) < len(characters):
        ucs.append("")
    result = {"characters": characters, "uc": ucs, "character_ids": ids}
    rolls = snapshot.get("wildcard_rolls")
    if isinstance(rolls, list) and rolls:
        result["wildcard_rolls"] = [dict(roll) for roll in rolls if isinstance(roll, dict)]
    return result


def _overlay_frozen_character_slots(app_context, result: dict, frame_slot_ids: list[str]) -> dict:
    frozen = read_frozen_character_slots(app_context)
    if not frozen:
        return result
    characters = list(result.get("characters") or [])
    ucs = list(result.get("uc") or [])
    ids = [str(value) for value in result.get("character_ids") or []]
    if not ids:
        ids = frame_slot_ids[:len(characters)]
    id_to_index = {slot_id: index for index, slot_id in enumerate(ids) if slot_id}
    for frame_index, slot_id in enumerate(frame_slot_ids):
        payload = frozen.get(slot_id)
        if not payload:
            continue
        index = id_to_index.get(slot_id, frame_index if frame_index < len(characters) else None)
        if index is None:
            continue
        while len(characters) <= index:
            characters.append("")
        while len(ucs) <= index:
            ucs.append("")
        while len(ids) <= index:
            ids.append(frame_slot_ids[len(ids)] if len(ids) < len(frame_slot_ids) else slot_id)
        characters[index] = payload["prompt"]
        ucs[index] = payload.get("uc", "")
        ids[index] = slot_id
    return {"characters": characters, "uc": ucs, "character_ids": ids}


def _character_rolls_from_context(context: PromptContext, start_index: int) -> list[dict[str, Any]]:
    rolls = getattr(context, "wildcard_rolls", None)
    if not isinstance(rolls, list) or len(rolls) <= start_index:
        return []
    return [
        dict(roll)
        for roll in rolls[start_index:]
        if isinstance(roll, dict) and roll.get("location") == "character"
    ]


def _replay_character_snapshot_rolls(app_context, snapshot: dict, *, reuse_current_context: bool) -> None:
    if not reuse_current_context:
        return
    rolls = snapshot.get("wildcard_rolls")
    if not isinstance(rolls, list) or not rolls:
        return
    context = getattr(app_context, "current_prompt_context", None)
    if context is None:
        return
    target_rolls = getattr(context, "wildcard_rolls", None)
    if isinstance(target_rolls, list):
        target_rolls.extend(dict(roll) for roll in rolls if isinstance(roll, dict))
    history = getattr(context, "wildcard_history", None)
    if isinstance(history, dict):
        for roll in rolls:
            if not isinstance(roll, dict):
                continue
            key = str(roll.get("key") or "")
            if key:
                history.setdefault(key, []).append(str(roll.get("value") or ""))


def _expand_character_text(
    text: str,
    processor: WildcardProcessor | None,
    context: PromptContext,
    slot=None,
    slot_label=None,
) -> str:
    pieces = [piece.strip() for piece in split_tags_smart(str(text or ""))]
    pieces = [piece for piece in pieces if piece]
    if not pieces:
        return ""
    if processor is None:
        return ", ".join(pieces)
    # location='character'(+slot)으로 캐릭터 블록 와일드카드 롤을 위치 인식 기록한다(Wildcard
    # Watch 블록별 뷰). slot은 안정 uuid, slot_label은 표시용 1-based 번호다.
    return ", ".join(processor.expand_tags(pieces, context, location='character', slot=slot, slot_label=slot_label))


def character_params_from_settings(
    app_context,
    mode: str = "NAI",
    settings: dict | None = None,
    *,
    reuse_current_context: bool = True,
    save_root: Path | str | None = None,
    prefer_snapshot: bool = False,
) -> dict:
    """Resolve the character params for this call, with the SSOT precedence:

      1. An active conditional character override (per-run, e.g. ``char:1+=__wc__``)
         ALWAYS wins — return it. The snapshot must never bypass it.
      2. No active frames (module disabled / all slots inactive/empty) → no
         characters. A stale snapshot is NOT consumed while inactive (it may still
         persist so re-enabling restores the roll).
      3. ``prefer_snapshot`` and a stored (mode-keyed) snapshot exists → reuse it
         verbatim (NO re-roll). This is how Generate (reroll OFF / Ollama) and the
         random prompt grounding stay identical to what was rolled.
      4. Otherwise perform ONE fresh wildcard expansion and return it.

    This function does NOT persist the snapshot — storage is explicit at the
    authoritative roll sites (Random / Generate / Refresh) via
    ``store_character_roll_snapshot``, so one-off callers (Seed Fan-out,
    event-stream freeze) can expand without clobbering the session snapshot.
    Steps 1 and 2 are pure reads and run for ALL callers, so a disabled module
    or an active conditional override is honored everywhere.
    """
    if save_root is None:
        save_root = _save_root_from_context(app_context)
    # (1) Conditional override is per-run and outranks the snapshot.
    # ⚠️ 불변식(재발 버그 영역 — "피곤한 버그"): 이 분기는 아래 step 4의
    # _expand_character_text(와일드카드 전개)를 *우회*한다. 조건부 훅은 after_wildcard
    # (파이프라인의 유일한 전개 패스 이후)에 돌기 때문에, override 생산자
    # (conditional_prompt_runtime._store_character_overrides)가 emit하는 모든 캐릭터
    # 텍스트의 와일드카드를 *스스로* 전개해 둬야 한다. 표면별로 하나씩 누락돼 5회 재발했다:
    #   S1 액션 주입(char:N+=__wc__) 5c72e6e6 · S2 char_replace 8dd8bb9e ·
    #   S3 슬롯 베이스(캐릭터 칸 직접 입력) 97572409.
    # override에는 raw 토큰을 절대 넣지 말 것. (로컬 상세: CONDITIONAL_CHAR_WILDCARD_TRAP.md)
    override = _conditional_character_override(app_context, reuse_current_context=reuse_current_context)
    if override is not None:
        return override
    normalized = (
        normalize_character_settings(settings)
        if settings is not None
        else load_character_settings(mode, save_root=save_root)
    )
    # (2) Inactive / no active frames → never consume a stale snapshot.
    frames = active_character_frames(normalized)
    if not frames:
        return {"characters": None}

    frame_slot_ids = _active_frame_slot_ids(frames)

    # (3) Reuse the stored roll without re-rolling. Frozen slots overlay the
    # snapshot so a user pin wins without forcing unrelated slots to reroll.
    if prefer_snapshot:
        snapshot = read_character_roll_snapshot(app_context, mode)
        if snapshot is not None:
            result = _snapshot_result(snapshot, frame_slot_ids)
            result = _overlay_frozen_character_slots(app_context, result, frame_slot_ids)
            _replay_character_snapshot_rolls(app_context, snapshot, reuse_current_context=reuse_current_context)
            return result

    # (4) Fresh expansion (not stored here — see docstring).
    processor = None
    wildcard_manager = getattr(app_context, "wildcard_manager", None)
    if wildcard_manager is not None:
        processor = WildcardProcessor(wildcard_manager)
    context = _get_prompt_context(app_context, reuse_current_context=reuse_current_context)
    roll_start = len(context.wildcard_rolls) if isinstance(getattr(context, "wildcard_rolls", None), list) else 0
    frozen = read_frozen_character_slots(app_context)

    characters = []
    ucs = []
    character_ids = []
    for slot_index, frame in enumerate(frames, 1):
        slot = frame_slot_ids[slot_index - 1] if slot_index - 1 < len(frame_slot_ids) else str(slot_index)
        frozen_payload = frozen.get(slot)
        if frozen_payload:
            prompt = frozen_payload["prompt"]
            uc = frozen_payload.get("uc", "")
        else:
            prompt = _expand_character_text(
                frame.get("prompt", ""),
                processor,
                context,
                slot=slot,
                slot_label=slot_index,
            )
            uc = _expand_character_text(
                frame.get("uc", ""),
                processor,
                context,
                slot=slot,
                slot_label=slot_index,
            )
        if prompt:
            characters.append(prompt)
            ucs.append(uc)
            character_ids.append(slot)

    if not characters:
        return {"characters": None}
    return {
        "characters": characters,
        "uc": ucs,
        "character_ids": character_ids,
        "wildcard_rolls": _character_rolls_from_context(context, roll_start),
    }



# ─────────────────────────────────────────────────────────────────────────────
# SSOT character roll snapshot
#
# The character-prompt wildcard roll has exactly ONE source of truth at runtime:
# ``app_context._character_roll_snapshot`` = {MODE: {"characters": [...], "uc": [...]}}.
# It is the only roll — preview, Random box, Ollama boost grounding, and the NAI
# Generate payload all read the SAME snapshot. It is RUNTIME ONLY and must never
# be written to CharacterModule_*.json.
#
# Mode-keyed: a NAI roll is stored under "NAI" and only read back under "NAI", so
# switching API mode (or a stray request carrying a different api_mode) can never
# apply another mode's characters. (NAI v4/v4.5 is the only consumer of char
# captions anyway — see api_service _call_nai_api — but mode-keying is a cheap
# extra guard and keeps per-mode previews independent.)
#
# Who rolls (authoritative writers): Random (when reroll_on_generate is False),
# the "Refresh Preview" button, and Generate (when reroll_on_generate is True or
# no snapshot exists yet). State reads (panel open / get_module_state / set_param
# echo / preview render) NEVER re-roll — they only read the snapshot.
# ─────────────────────────────────────────────────────────────────────────────

CHARACTER_ROLL_SNAPSHOT_ATTR = "_character_roll_snapshot"


def _snapshot_mode_key(mode: str | None) -> str:
    return str(mode or "NAI").upper()


def _snapshot_store(app_context) -> dict | None:
    store = getattr(app_context, CHARACTER_ROLL_SNAPSHOT_ATTR, None)
    return store if isinstance(store, dict) else None


def read_character_roll_snapshot(app_context, mode: str = "NAI") -> dict | None:
    """Return the stored SSOT roll snapshot for ``mode`` ({"characters", "uc"}) or None."""
    store = _snapshot_store(app_context)
    if store is None:
        return None
    snapshot = store.get(_snapshot_mode_key(mode))
    if isinstance(snapshot, dict) and snapshot.get("characters"):
        return snapshot
    return None


def store_character_roll_snapshot(app_context, params: dict | None, mode: str = "NAI") -> dict | None:
    """Store ``params`` (an expanded character roll) as the SSOT snapshot for ``mode``.

    Returns the stored snapshot. If ``params`` carries no characters this is a
    NO-OP — it does NOT clear an existing snapshot. (An empty result usually means
    the module went inactive or a conditional override produced nothing for this
    run; the persisted roll must survive so re-enabling restores it. Explicit
    invalidation on content edits goes through ``clear_character_roll_snapshot``.)
    """
    if app_context is None:
        return None
    if not (isinstance(params, dict) and params.get("characters")):
        return None
    store = _snapshot_store(app_context)
    if store is None:
        store = {}
        setattr(app_context, CHARACTER_ROLL_SNAPSHOT_ATTR, store)
    snapshot = {
        "characters": [str(value) for value in params.get("characters") or []],
        "uc": [str(value) for value in params.get("uc") or []],
    }
    character_ids = [str(value) for value in params.get("character_ids") or [] if str(value).strip()]
    if character_ids:
        snapshot["character_ids"] = character_ids
    rolls = params.get("wildcard_rolls")
    if isinstance(rolls, list) and rolls:
        snapshot["wildcard_rolls"] = [dict(roll) for roll in rolls if isinstance(roll, dict)]
    store[_snapshot_mode_key(mode)] = snapshot
    return snapshot


def clear_character_roll_snapshot(app_context, mode: str | None = None) -> None:
    """Invalidate the SSOT snapshot. With ``mode`` clears just that mode; otherwise
    clears every mode (used on character content edits — the active mode is what
    the panel edits, and clearing all is the safe superset)."""
    if app_context is None:
        return
    store = _snapshot_store(app_context)
    if store is None:
        return
    if mode is None:
        store.clear()
    else:
        store.pop(_snapshot_mode_key(mode), None)


def roll_character_params(
    app_context,
    mode: str = "NAI",
    settings: dict | None = None,
    *,
    reuse_current_context: bool = False,
    save_root: Path | str | None = None,
) -> dict:
    """Perform ONE fresh character-prompt wildcard expansion and store it as the
    SSOT snapshot for ``mode``. Used by Random (reroll OFF) and Refresh Preview.
    Returns the expanded params ({"characters", "uc"} or {"characters": None}).

    Honors the same precedence as ``character_params_from_settings``: an active
    conditional override or an inactive module short-circuits before any roll.
    A conditional override (reuse_current_context=True) is per-run and is NOT
    persisted as the snapshot.
    """
    params = character_params_from_settings(
        app_context,
        mode=mode,
        settings=settings,
        reuse_current_context=reuse_current_context,
        save_root=save_root,
        prefer_snapshot=False,
    )
    # Only persist a genuine fresh expansion. A conditional override (returned via
    # reuse_current_context=True) must not become the persistent snapshot.
    override_active = (
        reuse_current_context
        and _conditional_character_override(app_context, reuse_current_context=True) is not None
    )
    if not override_active:
        store_character_roll_snapshot(app_context, params, mode)
    return params


def read_reroll_on_generate(app_context, mode: str = "NAI") -> bool:
    """Read the "Process wildcards on Generate" flag from the HEADLESS character
    settings (settings cache → disk fallback). Not the desktop module helper.
    """
    if app_context is not None:
        getter = getattr(app_context, "_character_settings_cache", None)
        if callable(getter):
            try:
                cached = getter()
            except Exception:
                cached = None
            if isinstance(cached, dict):
                return bool(cached.get("reroll_on_generate", False))
    try:
        save_root = _save_root_from_context(app_context) if app_context is not None else None
        loaded = load_character_settings(mode, save_root=save_root)
        return bool(loaded.get("reroll_on_generate", False))
    except Exception:
        return False


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
            "slot_uuid": str(_frame_uuid(frame) or ""),
            "active": slot_state == "active",
            "slot_state": slot_state,
            "return_slot_state": str(frame.get("return_slot_state") or ""),
            "custom_name": str(frame.get("custom_name") or ""),
            "prompt": str(frame.get("prompt") or ""),
            "uc": str(frame.get("uc") or ""),
        })

    # SSOT: the preview reads the stored roll snapshot for this mode — it NEVER
    # re-rolls. Opening the panel / any get_module_state / any set_param echo must
    # show the SAME roll that Random/Refresh/Generate produced. If no snapshot
    # exists yet (or the module has no active frames) the preview is empty (the
    # frontend shows the "Use Refresh Preview" placeholder). Gating on active
    # frames keeps the preview consistent with what Generate would actually send.
    processed_characters: list[str] = []
    processed_ucs: list[str] = []
    if app_context is not None and active_character_frames(normalized):
        snapshot = read_character_roll_snapshot(app_context, mode)
        if snapshot is not None:
            processed_characters = [str(value) for value in snapshot.get("characters") or []]
            processed_ucs = [str(value) for value in snapshot.get("uc") or []]

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
