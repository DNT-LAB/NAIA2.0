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


def _slot_is_untouched(frame: Any) -> bool:
    """사용자가 **아무것도 넣지 않은** 슬롯인가.

    기본 상태의 빈 C1 을 가리키기 위한 것이다. 프롬프트/UC 만 보면 안 된다 —
    이름만 붙였거나 좌표만 잡아 둔 자리표시자 슬롯이 실제로 만들어진다:

        · 슬롯 우클릭 -> 프롬프트가 없어도 이름을 붙인다(`characterPanel.renameSlot`)
        · 화면은 **이름 없는** 빈 슬롯만 `(empty)` 로 그린다(`inactiveLabel`)
        · 좌표는 프롬프트와 무관하게 설정된다(`char_pos_N`)

    `uuid` 는 기준이 될 수 없다 — 정규화가 모든 슬롯에 만들어 준다.
    """
    if not isinstance(frame, dict):
        return True
    if str(frame.get("prompt") or "").strip():
        return False
    if str(frame.get("uc") or "").strip():
        return False
    if str(frame.get("custom_name") or "").strip():
        return False
    return not isinstance(frame.get("position"), dict)


def _state_of(frame: Any) -> str:
    if not isinstance(frame, dict):
        return ""
    return str(frame.get("slot_state") or "").strip().lower()


def _seed_missing_positions(settings: dict) -> None:
    """POS: CUSTOM 일 때 좌표가 빈 활성 슬롯에 AUTO 배치의 **빈 자리**를 뿌린다.

    사용자가 보던 배치(AUTO)에서 이어서 옮기게 하려는 것이다.

    ⚠️ 켜는 순간만 뿌리면 **그 뒤에 추가·활성화된 슬롯이 좌표 없이 남는다.**
    그러면 `resolved_character_positions` 가 "부분 좌표" 로 보고 그 요청을 통째로
    AUTO 배치로 떨어뜨려, 켜 둔 CUSTOM 이 조용히 무효가 된다. 그래서 쓰기가
    지나가는 `save_settings` 한 곳에서 매번 채운다 - 호출부마다 부르면
    **언젠가 한 곳이 빠진다**(Codex 지적: 캐릭터 에셋의 add_slot 이 그랬다).

    ⚠️ 이미 있는 좌표는 절대 덮지 않는다 - 슬롯은 삭제되기 전까지 사용자가 정한
    자리를 기억해야 한다(사용자 지정). 자리 고르기는 생성 경로와 **같은 함수**
    (`fill_missing_positions`)를 쓴다 - 둘로 나누면 화면과 요청이 갈린다.

    ⚠️ 게이트는 `active_character_frames` 의 **상위집합**이어야 한다 - 여기서
    채운 좌표가 저쪽 셈에 안 들어가면 부분 좌표가 된다. 반대로 여기가 더 넓은
    것은 안전하다(저쪽이 쓰는 슬롯은 전부 채워져 있다).

    지금은 실제로 더 넓다: 여기는 `slot_state == "active"` 로 보고 저쪽은
    `is_enabled`(= active and not muted)로 본다. **일부러 그렇다** - 꺼 둔 슬롯도
    좌표를 받아 둬야 다시 켰을 때 자리가 살아 있다. 슬롯은 삭제되기 전까지 자기
    자리를 기억한다(사용자 지정).
    """
    from core.character_settings import fill_missing_positions, normalize_position

    if not settings.get("is_active"):
        return
    frames = settings.get("character_frames") or []
    active = [f for f in frames
              if isinstance(f, dict) and _state_of(f) == "active"
              and str(f.get("prompt") or "").strip()]
    known = [normalize_position(f.get("position")) for f in active]
    if all(position is not None for position in known):
        return
    filled = fill_missing_positions(known)
    for frame, position, was in zip(active, filled, known):
        if was is None:
            frame["position"] = position


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
        # POS 씨앗은 **여기서만** 뿌린다. 프레임을 바꾸는 길이 여럿이라
        # (set_param · 캐릭터 에셋 적용 · 앞으로 생길 것들) 호출부마다 걸면
        # 언젠가 한 곳이 빠지고, 빠진 그 길이 CUSTOM 을 통째로 무효로 만든다.
        # 정렬이 끝난 뒤여야 씨앗이 최종 순서를 보고 놓인다.
        if normalized.get("use_custom_positions"):
            _seed_missing_positions(normalized)
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

    def apply_bulk_characters(self, characters: list[str], characters_uc: list[str],
                              existing: str = "inactive") -> dict[str, Any]:
        with self._commit_lock:
            return self._apply_bulk_characters_locked(characters, characters_uc, existing)

    def _apply_bulk_characters_locked(self, characters: list[str], characters_uc: list[str],
                                      existing: str = "inactive") -> dict[str, Any]:
        """메타데이터의 캐릭터 프롬프트를 슬롯에 통째로 얹는다.

        ⚠️ 이 키(`bulk_characters`)는 프런트가 **오래 전부터 보내고 있었는데 받는 곳이
           없었다.** `set_param` 이 `else: return None` 으로 떨어져 백엔드가
           "Module parameter is not supported in this runtime" 토스트를 보냈고,
           프런트는 그 전에 이미 "Applied N character prompts" 를 띄운 뒤였다 —
           **성공 토스트와 실패 토스트가 나란히 뜨고 캐릭터는 안 들어갔다.**

        `existing` 은 **기존 슬롯을 어떻게 할지**다(사용자에게 묻는다):

            "inactive"   기존을 비활성 무리로 보내고 새 것을 활성으로 덧붙인다.
                         아무것도 잃지 않는다 - 되돌리려면 다시 켜면 된다.
            "overwrite"  기존(비-cold)을 버리고 새 것으로 갈아치운다.

        어느 쪽이든 **cold 슬롯은 건드리지 않는다.** cold 는 사용자가 일부러 치워 둔
        것이라 "기존 캐릭터" 로 취급하면 놀란다 - `_apply_asset_locked` 와 같은 규약이다.

        ## 좌표 정책 (의도적 선택, Codex 리뷰 2026-08-24)

        새 슬롯은 좌표 없이 만든다. POS 가 CUSTOM 이면 `_seed_missing_positions` 가
        저장 중에 AUTO 링의 **빈 자리**를 뿌린다. 그 함수는 **활성 슬롯만** 자리를
        차지한 것으로 세므로:

            inactive 로 밀려난 기존 슬롯의 좌표는 링 자리를 잡아 두지 않는다
            -> 새 활성 슬롯이 같은 점을 받을 수 있고,
               나중에 그 슬롯을 다시 켜면 두 슬롯이 같은 자리에 선다

        **그대로 둔다.** 비활성 슬롯은 생성에 안 나가므로 링 자리를 예약하면 안 된다
        (치워 둔 슬롯이 많을수록 아홉 자리가 금세 마른다). 재활성화 시의 겹침은
        사용자가 옮기면 되고, 좌표 시스템 전체를 바꿀 만한 이득이 아니다.
        ⚠️ 이건 이 함수가 만든 성질이 아니라 **선재 동작**이다 - 슬롯을 하나 끄고
           새로 추가해도 똑같다.
        """
        context = self.context
        api_mode = context.get_api_mode()
        settings = self.settings_cache()
        frames = settings.setdefault("character_frames", [])
        mode = str(existing or "inactive").strip().lower()
        if mode not in {"inactive", "overwrite"}:
            raise ValueError(f"unknown existing mode: {existing}")

        prompts = [str(p or "") for p in (characters or [])]
        ucs = [str(u or "") for u in (characters_uc or [])]
        # 길이가 다를 수 있다 - 네거티브만 짧게 온 메타데이터가 실제로 있다.
        fresh = [{
            "prompt": prompts[i],
            "uc": ucs[i] if i < len(ucs) else "",
            "is_enabled": True,
            "slot_state": "active",
            "is_muted": False,
            "custom_name": "",
        } for i in range(len(prompts)) if prompts[i].strip()]
        if not fresh:
            raise ValueError("no character prompts to apply")

        def is_cold(frame: Any) -> bool:
            return (isinstance(frame, dict)
                    and str(frame.get("slot_state") or "").strip().lower() == "cold")

        cold = [f for f in frames if is_cold(f)]
        if mode == "overwrite":
            kept = cold
        else:
            kept = []
            for frame in frames:
                if is_cold(frame):
                    kept.append(frame)
                    continue
                if not isinstance(frame, dict):
                    continue
                # 기본 상태의 **빈 C1** 까지 비활성으로 남기면 무리가 쓰레기로 찬다.
                # ⚠️ 다만 "비었다" 의 기준을 프롬프트/UC 로만 잡으면 안 된다 -
                #    사용자가 이름을 붙이거나 좌표만 잡아 둔 자리표시자 슬롯이
                #    소리 없이 사라진다. 그건 도달 가능한 상태다:
                #    슬롯을 우클릭하면 프롬프트가 없어도 이름을 붙일 수 있고
                #    (`characterPanel.renameSlot`), 화면은 이름 없는 빈 슬롯만
                #    `(empty)` 로 그린다(`inactiveLabel`). 좌표도 프롬프트와 무관하게
                #    설정된다(`char_pos_N`).
                #    "아무것도 잃지 않는다" 는 약속을 지키려면 넷 다 비어야 버린다.
                if _slot_is_untouched(frame):
                    continue
                frame["slot_state"] = "inactive"
                frame["is_enabled"] = False
                kept.append(frame)
        frames[:] = fresh + kept

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
            # ⚠️ mute 도 함께 푼다. `is_enabled` 는 이제 **파생값**이라
            #    (`active and not muted`), 꺼 둔 C1 에 에셋을 얹으면 여기서 True 로
            #    써도 다음 정규화가 다시 False 로 만든다 - 적용은 됐는데 슬롯이
            #    조용히 꺼져 있게 된다. 사용자가 "이걸 C1 으로 쓴다" 고 한 것이므로
            #    켜 주는 것이 맞다.
            frame["is_muted"] = False
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
        elif key == "position_mode":
            # POS: AUTO -> CUSTOM -> RAND -> AUTO (사용자 지정).
            # 스냅샷은 건드리지 않는다 - 좌표는 굴림의 일부가 아니다.
            # CUSTOM 으로 들어오는 순간 빈 좌표에 AUTO 자리를 뿌린다(save_settings).
            # 사용자가 보던 배치에서 이어 옮기게 하려는 것이고, 배치 규칙을 파이썬
            # 한 곳에만 두려는 것이다 - 프런트가 같은 표를 또 들면 언젠가 갈린다.
            from core.character_settings import normalize_position_mode

            settings["position_mode"] = normalize_position_mode(value)
            settings["use_custom_positions"] = settings["position_mode"] == "custom"
        elif key == "use_custom_positions":
            # 옛 이름. 정규화가 `position_mode` 를 우선하므로 **둘 다** 써야 먹는다
            # - 미러만 바꾸면 다음 정규화에서 옛 모드로 조용히 되돌아간다.
            settings["use_custom_positions"] = context._coerce_bool(value)
            settings["position_mode"] = "custom" if settings["use_custom_positions"] else "auto"
        elif key.startswith("char_pos_"):
            index = context._index_from_key(key, "char_pos_")
            if index is not None:
                from core.character_settings import normalize_position

                frame = self.ensure_frame(frames, index)
                raw = value
                if isinstance(raw, str):
                    parts = [part.strip() for part in raw.split(",")]
                    raw = {"x": parts[0], "y": parts[1]} if len(parts) == 2 else None
                frame["position"] = normalize_position(raw)
        elif key == "bulk_characters":
            # 메타데이터 뷰어의 캐릭터 일괄 적용. 값은 JSON 문자열이다
            # (`{characters, characters_uc, existing}`). 커밋 규약은
            # `_apply_bulk_characters_locked` 가 스스로 지키므로 여기서 끝낸다.
            payload = value
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (TypeError, ValueError):
                    payload = None
            if not isinstance(payload, dict):
                return None
            return self._apply_bulk_characters_locked(
                payload.get("characters") or [],
                payload.get("characters_uc") or [],
                str(payload.get("existing") or "inactive"),
            )
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
        elif key.startswith("char_muted_"):
            # ✔/✘ - **제자리에서** 끈다. 무리는 그대로라 번호도 그대로다.
            # `char_active_N`(옛 체크박스)과 다르다 - 그건 무리를 옮긴다.
            index = context._index_from_key(key, "char_muted_")
            if index is not None:
                frame = self.ensure_frame(frames, index)
                muted = context._coerce_bool(value)
                frame["is_muted"] = muted
                # 파생값도 함께 세운다 - 정규화가 다시 세우지만, 이 사이에
                # 프레임을 읽는 경로(스냅샷 무효화 판정 등)가 옛 값을 본다.
                frame["is_enabled"] = (
                    str(frame.get("slot_state") or "") == "active" and not muted
                )
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
        elif key.startswith("char_connect_"):
            # Connect - 앞선 활성 슬롯의 전개 결과를 물려받는다. 값은 원본 슬롯의
            # **uuid**(빈 문자열이면 연결 해제).
            #
            # 여기서는 넘어온 값을 그대로 적기만 한다. 유효성(자기 참조 · 없는 uuid ·
            # 뒤를 가리킴)은 `normalize_character_settings` 안의
            # `_prune_character_links` 가 저장·로드 양쪽에서 판정한다 — 순서가 걸린
            # 판정이라 프레임을 정렬한 뒤에 해야 옳고, 그 자리가 거기다.
            index = context._index_from_key(key, "char_connect_")
            if index is not None:
                self.ensure_frame(frames, index)["connect_to"] = str(value or "").strip()
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
