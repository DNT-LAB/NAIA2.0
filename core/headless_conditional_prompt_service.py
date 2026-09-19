"""Headless Conditional Prompt module state service.

Provides the Remote Web editor contract ported from future01:
- ``state()`` reconstructs the structured rule book from the persisted DSL so the
  block editor survives reloads, lists user/bundled presets, and advertises the
  edit/preset/test capabilities.
- ``set_param`` handles explicit rule-book apply (``rules_v2_book``), preset CRUD
  (``preset_save`` / ``preset_load`` / ``preset_delete``) and simulation
  (``simulate_v2`` / ``test``).

The DSL stays the source of truth (the runtime hook in
``core/conditional_prompt_runtime.py`` consumes it); the block book is a derived
view produced by ``core.conditional.dsl_parser`` / ``dsl_serializer``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class HeadlessConditionalPromptService:
    def __init__(self, context: Any):
        self.context = context
        self._last_log = ""

    # ------------------------------------------------------------------
    # Preset storage (runtime-aware paths)
    # ------------------------------------------------------------------

    def _storage(self):
        from core.conditional.preset_io import PresetStorage

        runtime_paths = getattr(self.context, "runtime_paths", None)
        save_root = getattr(runtime_paths, "save_dir", None)
        save_dir = Path(save_root) / "conditional_presets" if save_root else None
        # bundled_dir defaults to <project>/data/conditional_presets_bundled.
        return PresetStorage(save_dir=save_dir)

    def _preset_infos(self) -> list[dict[str, Any]]:
        try:
            infos = []
            for info in self._storage().list_all():
                infos.append({
                    "name": info.name,
                    "description": info.description,
                    "is_bundled": bool(info.is_bundled),
                    "rule_count": int(info.rule_count),
                    # 어느 편집기에서 저장했나 - 목록 배지와 교차 편집기 안내용.
                    # 이 필드가 생기기 전 프리셋은 None(배지 없음).
                    "source_mode": info.source_mode,
                })
            return infos
        except Exception as exc:
            print(f"Remote: conditional preset list failed - {exc}")
            return []

    def _rulebook_dict_from_dsl(self, dsl_text: str, engine_options: dict[str, Any]) -> dict[str, Any]:
        """v2 DSL → RuleBook JSON the web editor consumes."""
        from core.conditional_prompt_settings import normalize_conditional_engine_options

        opts = normalize_conditional_engine_options(engine_options or {})
        try:
            from dataclasses import asdict

            from core.conditional.dsl_parser import parse_rulebook
            from core.conditional.preset_io import SCHEMA_VERSION

            book = parse_rulebook(dsl_text or "")
            book.max_passes = int(opts.get("max_passes", book.max_passes))
            book.stop_on_match = bool(opts.get("stop_on_match", book.stop_on_match))
            return {
                "schema_version": SCHEMA_VERSION,
                "name": "",
                "description": "",
                "engine_options": {
                    "max_passes": book.max_passes,
                    "stop_on_match": book.stop_on_match,
                },
                "rules": [asdict(rule) for rule in book.rules],
            }
        except Exception as exc:
            print(f"Remote: conditional RuleBook decode failed - {exc}")
            return {
                "schema_version": 1,
                "name": "",
                "description": "",
                "engine_options": opts,
                "rules": [],
            }

    @staticmethod
    def _lint(rules_text: str) -> list[dict[str, Any]]:
        """죽은 조건(`~*tag`, `~(...)`, 빈 피연산자 …) 경고. **규칙을 막지 않는다** —
        이미 그런 규칙이 돌고 있는 설치본의 출력을 바꾸지 않으려고 차단 대신 알림만 한다."""
        try:
            from core.conditional.lint import lint_rules_text

            return lint_rules_text(rules_text or "")
        except Exception as exc:
            print(f"Remote: conditional lint failed - {exc}")
            return []

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def state(self) -> dict[str, Any]:
        from core.conditional_prompt_settings import (
            get_conditional_prompt_store,
            normalize_conditional_engine_options,
        )

        store = get_conditional_prompt_store(self.context)
        settings = store.collect_settings()
        editor_mode = self._editor_mode(settings)
        rules_legacy = str(settings.get("rules") or "")
        rules_v2 = str(settings.get("rules_v2") or "")
        active_rules = self._active_rules(settings)
        engine_options = normalize_conditional_engine_options(settings.get("engine_options") or {})
        # ⚠️ v2 book 에는 **v2 칸의 옵션**을 실어야 한다. 지금 모드의 미러를 쓰면
        #    Legacy 에 서 있는 동안 v2 book 이 Legacy 의 max_passes 를 달고 나가고,
        #    프런트가 그 book 을 되돌려 보내는 순간(모드 전환 직후 저장 등) 잘못된
        #    값이 v2 칸에 영구히 박힌다(Codex 지적, 실행으로 확인: legacy=3/v2=7 인데
        #    book 이 3 으로 나왔다).
        engine_options_v2 = normalize_conditional_engine_options(
            settings.get("engine_options_v2") or {}
        )
        return self.context._module_state_payload("conditional_prompt", {
            "enabled": bool(settings.get("enabled", False)),
            "editor_mode": editor_mode,
            "rules": active_rules,
            "active_rules": active_rules,
            "rules_legacy": rules_legacy,
            "rules_v2": rules_v2,
            "rules_v2_book": self._rulebook_dict_from_dsl(rules_v2, engine_options_v2),
            "lint": self._lint(active_rules),
            "engine_options": engine_options,
            # 프리셋 이름은 모드별이다. 화면은 `active_preset`(지금 모드 것)만 쓰면
            # 되지만, 양쪽을 함께 보내 두면 "반대편엔 무엇이 걸려 있나" 도 그릴 수 있다.
            "active_preset": str(settings.get(self._preset_key(settings)) or ""),
            "active_preset_legacy": str(settings.get("active_preset_legacy") or ""),
            "active_preset_v2": str(settings.get("active_preset_v2") or ""),
            # ⚠️ 조건부가 켜져 있는데 **지금 편집기의 규칙이 비어** 있으면 아무 일도
            #    안 일어난다. 모드별로 규칙을 따로 두는 기능이라 한쪽이 빈 채 남기
            #    쉽고, 그 상태는 생성 결과에서만 드러난다 - 화면이 말해 줘야 한다.
            "active_rules_empty": not active_rules.strip(),
            # 프리셋 로드·복제로 규칙이 갈렸을 때 되돌릴 것이 있는지(본문은 안 싣는다).
            "rules_undo": self._undo_summary(settings),
            "presets": self._preset_infos(),
            "can_test_rules": True,
            "can_manage_presets": True,
            "can_edit_rulebook": True,
            "capabilities": {
                "test_rules": True,
                "manage_presets": True,
                "edit_rulebook": True,
            },
            "log": self._last_log,
        })

    def _state_with(
        self,
        *,
        messages: list[dict[str, Any]] | None = None,
        simulation: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self.state()
        if simulation is not None:
            payload["simulation"] = simulation
            payload["local_dirty"] = True
        # ⚠️ `extra` 는 **한 번 실린 뒤 사라지는** 값이다(다음 `state()` 에는 없다).
        #    프런트가 이걸로 대화상자를 여는 경우 플래그를 자기 쪽에 복사해 둬야
        #    다른 에코가 끼어들어도 상자가 닫히지 않는다.
        if extra:
            payload.update(extra)
        if messages:
            payload["_headless_extra_messages"] = messages
        return payload

    @staticmethod
    def _toast_message(message: str, level: str = "info") -> dict[str, Any]:
        return {"type": "toast", "message": message, "level": level}

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def set_param(self, key: str, value: Any) -> dict[str, Any] | None:
        from core.conditional_prompt_settings import (
            get_conditional_prompt_store,
            normalize_conditional_engine_options,
        )

        context = self.context
        store = get_conditional_prompt_store(context)
        settings = store.collect_settings()
        text_value = str(value or "")

        if key == "enabled":
            settings["enabled"] = context._coerce_bool(value)
        elif key in {"editor_mode", "mode"}:
            if text_value in {"legacy", "v2"}:
                settings["editor_mode"] = text_value
        elif key == "rules_legacy":
            settings["rules"] = text_value
        elif key == "rules_v2":
            settings["rules_v2"] = text_value
        elif key == "rules":
            if settings.get("editor_mode") == "v2":
                settings["rules_v2"] = text_value
            else:
                settings["rules"] = text_value
        elif key == "engine_options":
            parsed = json.loads(text_value or "{}")
            if isinstance(parsed, dict):
                self._set_engine_options(settings, parsed)
        elif key == "max_passes":
            options = dict(self._active_engine_options(settings))
            options["max_passes"] = context._coerce_int(value, default=1, minimum=1, maximum=20)
            self._set_engine_options(settings, options)
        elif key == "stop_on_match":
            options = dict(self._active_engine_options(settings))
            options["stop_on_match"] = context._coerce_bool(value)
            self._set_engine_options(settings, options)
        elif key == "rules_v2_book":
            return self._apply_rules_v2_book(store, settings, text_value)
        elif key == "preset_save":
            return self._handle_preset_save(store, settings, text_value)
        elif key == "preset_load":
            return self._handle_preset_load(store, settings, text_value)
        elif key == "preset_delete":
            return self._handle_preset_delete(store, settings, text_value)
        elif key == "rules_undo":
            return self._handle_rules_undo(store, settings)
        elif key in {"simulate_v2", "test"}:
            return self._handle_simulation(key, settings, text_value)
        else:
            return None

        store.apply_settings(settings)
        return self.state()

    # ------------------------------------------------------------------
    # 편집기 모드와 규칙 텍스트
    #
    # ⚠️ 규칙 텍스트가 **두 칸**(`rules` = Legacy, `rules_v2` = 블록 편집기)이고
    #    실행은 `editor_mode` 가 가리키는 쪽만 쓴다. 프리셋 저장·로드가 이걸 안 보고
    #    `rules_v2` 에 못박혀 있어서 Legacy 사용자에게는 프리셋이 통째로 고장나
    #    있었다 - 저장하면 화면에 없는 것이 저장되고, 로드하면 편집기가 바뀌면서
    #    자기 규칙이 사라졌다. 그래서 두 곳 다 이 헬퍼를 지나게 한다.
    # ------------------------------------------------------------------

    @staticmethod
    def _editor_mode(settings: dict[str, Any]) -> str:
        mode = str(settings.get("editor_mode") or "legacy")
        return mode if mode in {"legacy", "v2"} else "legacy"

    @classmethod
    def _rules_key(cls, settings: dict[str, Any]) -> str:
        return "rules_v2" if cls._editor_mode(settings) == "v2" else "rules"

    @classmethod
    def _active_rules(cls, settings: dict[str, Any]) -> str:
        return str(settings.get(cls._rules_key(settings)) or "")

    @classmethod
    def _write_active_rules(cls, settings: dict[str, Any], dsl: str, *, reason: str = "") -> None:
        """규칙 칸을 **통째로** 갈아 끼운다. 갈리기 전 값은 한 세대 보관한다.

        ⚠️ 이 함수를 지나는 것은 프리셋 로드·복제·활성화처럼 **사용자가 직접 친
        글이 아닌 것으로 칸을 덮는** 경로뿐이다. 그 셋이 실제로 사용자의 손으로 쓴
        Legacy DSL 을 되돌릴 길 없이 지웠다(제보 2026-09-19). 타이핑 경로
        (`rules_legacy` / `rules_v2` set_param)는 여기를 지나지 않으므로 한 타마다
        보관본이 갈리는 일은 없다.
        """
        key = cls._rules_key(settings)
        previous = str(settings.get(key) or "")
        if previous.strip() and previous != dsl:
            cls._stash_undo(settings, previous, reason)
        settings[key] = dsl

    # ------------------------------------------------------------------
    # 되돌리기 한 세대
    # ------------------------------------------------------------------

    @classmethod
    def _undo_slot(cls, settings: dict[str, Any]) -> str:
        return "v2" if cls._editor_mode(settings) == "v2" else "legacy"

    @classmethod
    def _stash_undo(cls, settings: dict[str, Any], text: str, reason: str) -> None:
        from datetime import datetime

        undo = dict(settings.get("rules_undo") or {})
        undo[cls._undo_slot(settings)] = {
            "text": text,
            "reason": reason,
            "at": datetime.now().isoformat(timespec="seconds"),
        }
        settings["rules_undo"] = undo

    @classmethod
    def _undo_entry(cls, settings: dict[str, Any]) -> dict[str, Any] | None:
        entry = (settings.get("rules_undo") or {}).get(cls._undo_slot(settings))
        if not isinstance(entry, dict):
            return None
        return entry if str(entry.get("text") or "").strip() else None

    @classmethod
    def _undo_summary(cls, settings: dict[str, Any]) -> dict[str, Any]:
        """화면에 실을 요약. **본문은 싣지 않는다.**

        ⚠️ 규칙 텍스트를 state 에 더 실으면 패널의 재렌더 시그니처가 규칙과 함께
        요동쳐 타이핑 중 캐럿이 날아간다(이 파일 계열의 회귀). 되돌릴 것이 있는지와
        사유·시각만 보낸다 - 본문은 서버가 쥐고 있다가 `rules_undo` 요청에 쓴다.
        """
        entry = cls._undo_entry(settings)
        if entry is None:
            return {"available": False}
        return {
            "available": True,
            "reason": str(entry.get("reason") or ""),
            "at": str(entry.get("at") or ""),
        }

    def _handle_rules_undo(self, store, settings: dict[str, Any]) -> dict[str, Any]:
        entry = self._undo_entry(settings)
        if entry is None:
            return self._state_with(messages=[
                self._toast_message("되돌릴 이전 규칙이 없습니다.", "error"),
            ])
        key = self._rules_key(settings)
        current = str(settings.get(key) or "")
        settings[key] = str(entry["text"])
        # 되돌리기 자체도 한 세대를 남긴다 - 잘못 눌렀으면 다시 누르면 제자리로 온다.
        undo = dict(settings.get("rules_undo") or {})
        slot = self._undo_slot(settings)
        if current.strip():
            from datetime import datetime

            undo[slot] = {
                "text": current,
                "reason": "되돌리기 직전",
                "at": datetime.now().isoformat(timespec="seconds"),
            }
        else:
            undo.pop(slot, None)
        settings["rules_undo"] = undo
        store.apply_settings(settings)
        return self._state_with(messages=[
            self._toast_message("이전 규칙으로 되돌렸습니다.", "success"),
        ])

    # ⚠️ 프리셋 이름도 **모드별**이다. 규칙 칸이 나뉘어 있는데 이름표만 하나면,
    #    모드를 바꿨을 때 규칙은 이쪽 것인데 이름은 저쪽 것이 뜬다(실측). 모드마다
    #    다른 프리셋을 쓰려는 것이 이 기능의 목적이라 더 어긋나 보인다.
    @classmethod
    def _preset_key(cls, settings: dict[str, Any]) -> str:
        return "active_preset_v2" if cls._editor_mode(settings) == "v2" else "active_preset_legacy"

    @classmethod
    def _set_active_preset(cls, settings: dict[str, Any], name: str | None) -> None:
        settings[cls._preset_key(settings)] = name
        settings["active_preset"] = name        # 옛 단일 키를 지금 모드로 비춘다

    # ⚠️ 엔진 옵션도 **모드별**이다. RuleBook JSON 이 옵션을 규칙과 함께 담으므로
    #    옵션은 프리셋의 일부다 - 칸이 하나면 프리셋을 부를 때마다 반대편 모드의
    #    옵션까지 덮어써서, Legacy 로 돌아왔을 때 이름·규칙은 L 인데 max_passes 는
    #    V 것이 된다(Codex 지적, 코드로 확인).
    @classmethod
    def _engine_key(cls, settings: dict[str, Any]) -> str:
        return "engine_options_v2" if cls._editor_mode(settings) == "v2" else "engine_options_legacy"

    @classmethod
    def _active_engine_options(cls, settings: dict[str, Any]) -> dict[str, Any]:
        from core.conditional_prompt_settings import normalize_conditional_engine_options

        return normalize_conditional_engine_options(settings.get(cls._engine_key(settings)) or {})

    @classmethod
    def _set_engine_options(cls, settings: dict[str, Any], options: Any) -> None:
        from core.conditional_prompt_settings import normalize_conditional_engine_options

        normalized = normalize_conditional_engine_options(options or {})
        settings[cls._engine_key(settings)] = normalized
        settings["engine_options"] = dict(normalized)   # 엔진이 읽는 이름을 비춘다

    def _apply_rules_v2_book(self, store, settings: dict[str, Any], text_value: str) -> dict[str, Any]:
        from core.conditional.dsl_serializer import serialize_rulebook
        from core.conditional_prompt_settings import normalize_conditional_engine_options

        book, data = self._book_from_json_value(text_value)
        opts = normalize_conditional_engine_options(
            data.get("engine_options")
            or {"max_passes": book.max_passes, "stop_on_match": book.stop_on_match}
        )
        book.max_passes = opts["max_passes"]
        book.stop_on_match = opts["stop_on_match"]
        dsl = serialize_rulebook(book)
        settings["rules_v2"] = dsl
        # ⚠️ 모드를 먼저 v2 로 옮긴 **뒤에** 옵션을 쓴다. 순서가 바뀌면 v2 의 옵션이
        #    legacy 칸에 들어간다(`_engine_key` 가 그때의 모드를 본다).
        settings["editor_mode"] = "v2"
        self._set_engine_options(settings, opts)
        store.apply_settings(settings)
        return self.state()

    def _book_from_json_value(self, value: str):
        """JSON ({"book": {...}} or a raw book dict) → (RuleBook, raw_dict)."""
        from core.conditional.preset_io import rulebook_from_dict

        data = json.loads(value or "{}")
        if isinstance(data, dict) and isinstance(data.get("book"), dict):
            data = data["book"]
        if not isinstance(data, dict):
            data = {}
        return rulebook_from_dict(data), data

    def _handle_preset_save(self, store, settings: dict[str, Any], text_value: str) -> dict[str, Any]:
        from core.conditional.dsl_parser import parse_rulebook
        from core.conditional.dsl_serializer import serialize_rulebook
        from core.conditional.preset_io import rulebook_from_dict
        from core.conditional_prompt_settings import normalize_conditional_engine_options

        try:
            payload = json.loads(text_value or "{}")
        except Exception:
            payload = {}
        if isinstance(payload, str):
            payload = {"name": payload}
        if not isinstance(payload, dict):
            payload = {}

        def _flag(key: str) -> bool:
            raw = payload.get(key, False)
            return raw is True or (isinstance(raw, str) and raw.strip().lower() == "true")

        name = str(payload.get("name") or "").strip()
        source_preset = str(payload.get("source_preset") or "").strip()
        activate = _flag("activate")
        overwrite = _flag("overwrite")
        book_data = payload.get("book") if isinstance(payload.get("book"), dict) else None

        if not name:
            return self._state_with(messages=[self._toast_message("조건부 프리셋 이름이 비어 있습니다.", "error")])

        storage = self._storage()
        if any(info.name == name and info.is_bundled for info in storage.list_all()):
            return self._state_with(messages=[self._toast_message("번들 프리셋과 같은 이름으로 저장할 수 없습니다.", "error")])

        # ⚠️ 덮어쓰기는 **물어보고** 한다. 프리셋 이름칸이 활성 프리셋 이름으로 미리
        #    채워져 있어서(패널 `renderPresetPane`), [저장]을 누르면 지금 걸려 있는
        #    프리셋이 아무 경고 없이 갈렸다 - New Editor 에서 눌렀다면 Legacy 에서
        #    만든 프리셋이 통째로 v2 내용이 된다(사용자 제보 2026-09-19, 실측 재현).
        #    이름이 아니라 **파일 존재**로 재는 이유는 `user_conflict` 주석에 있다.
        conflict = storage.user_conflict(name)
        if conflict is not None and not overwrite:
            return self._state_with(
                extra={"preset_overwrite_prompt": {
                    "name": name,
                    "existing": conflict.name,
                    "rule_count": int(conflict.rule_count),
                    # 정규화 때문에 다른 이름을 덮게 되는 경우 - 이걸 말해 주지 않으면
                    # 사용자는 자기가 무엇을 지우는지 모른다.
                    "renamed": conflict.name != name,
                }},
            )

        book = None
        # 문서 전체 원문 - 규칙마다의 `source_text` 가 줄을 지키고, 이것이 줄 사이의
        # 배치(한 줄에 쉼표로 이어 쓴 형식·빈 줄)를 지킨다. 불러올 때 뜻이 같을 때만 쓴다.
        source_dsl: str | None = None
        source_mode: str | None = None
        try:
            if book_data is not None:
                book = rulebook_from_dict(book_data)
                source_mode = self._editor_mode(settings)
            elif source_preset:
                # 복제 - 원본의 원문·출처까지 함께 옮긴다. 안 옮기면 복제본만
                # 줄 배치가 달라져 "복제했는데 내용이 다르다" 가 된다.
                book, meta = storage.load_with_meta(source_preset)
                raw_source = meta.get("source_dsl")
                source_dsl = str(raw_source) if isinstance(raw_source, str) else None
                raw_mode = meta.get("source_mode")
                source_mode = raw_mode if raw_mode in {"legacy", "v2"} else None
            else:
                # ⚠️ **화면에 보이는 규칙**을 담는다. 예전에는 `rules_v2` 로 못박혀
                # 있어서, Legacy 편집기를 쓰던 사용자가 저장을 누르면 자기가 보고
                # 있지도 않은(대개 비어 있는) v2 텍스트가 프리셋이 됐다.
                source_dsl = self._active_rules(settings)
                source_mode = self._editor_mode(settings)
                book = parse_rulebook(source_dsl)
                opts = self._active_engine_options(settings)
                book.max_passes = opts["max_passes"]
                book.stop_on_match = opts["stop_on_match"]
        except FileNotFoundError:
            return self._state_with(messages=[
                self._toast_message(f"복제할 조건부 프리셋을 찾을 수 없습니다: {source_preset}", "error"),
            ])
        except Exception as exc:
            return self._state_with(messages=[self._toast_message(f"프리셋 저장 실패: {exc}", "error")])

        if book is None:
            return self._state_with(messages=[self._toast_message("프리셋 저장 실패: 규칙을 해석할 수 없습니다.", "error")])

        storage.save(name, book, source_dsl=source_dsl, source_mode=source_mode)
        # ⚠️ 이름표는 **화면의 규칙이 그 프리셋일 때만** 건다. 복제나 빈 프리셋은
        #    파일만 만들고 화면을 안 건드리므로(아래 activate 참조), 여기서 이름표를
        #    걸면 "이름은 V5 인데 규칙은 옛것" 인 불일치가 남는다.
        from_screen = book_data is None and not source_preset
        if activate or from_screen:
            self._set_active_preset(settings, name)
        if activate:
            self._write_active_rules(
                settings, serialize_rulebook(book), reason=f"프리셋 적용: {name}",
            )
            self._set_engine_options(settings, {
                "max_passes": book.max_passes,
                "stop_on_match": book.stop_on_match,
            })
        store.apply_settings(settings)
        if from_screen or activate:
            note = f"조건부 프리셋 저장: {name}"
        else:
            # 복제·빈 프리셋은 더 이상 지금 규칙을 갈아치우지 않는다 - 그 사실을
            # 말해 주지 않으면 "복제했는데 아무 일도 안 일어난다" 로 보인다.
            note = f"조건부 프리셋 생성: {name} — 현재 규칙은 그대로입니다"
        return self._state_with(messages=[self._toast_message(note, "success")])

    def _handle_preset_load(self, store, settings: dict[str, Any], text_value: str) -> dict[str, Any]:
        from core.conditional.dsl_serializer import serialize_rulebook

        name = text_value.strip()
        if not name:
            return self._state_with(messages=[self._toast_message("로드할 프리셋 이름이 비어 있습니다.", "error")])
        try:
            book, meta = self._storage().load_with_meta(name)
        except FileNotFoundError:
            return self._state_with(messages=[
                self._toast_message(f"조건부 프리셋을 찾을 수 없습니다: {name}", "error"),
            ])
        except Exception as exc:
            return self._state_with(messages=[self._toast_message(f"프리셋 로드 실패: {exc}", "error")])

        # ⚠️ **편집기 모드를 바꾸지 않는다.** 예전에는 로드가 `rules_v2` 에 쓰고
        # `editor_mode` 를 v2 로 못박아서, Legacy 를 쓰던 사용자는 프리셋을 부르는
        # 순간 낯선 블록 편집기로 끌려가고 자기 규칙은 화면에서 사라졌다
        # (`settings["rules"]` 에 남아 있지만 비활성이라 보이지 않는다).
        self._write_active_rules(
            settings, self._restore_preset_text(book, meta), reason=f"프리셋 불러오기: {name}",
        )
        # 프리셋의 옵션은 **그 프리셋을 부른 모드에만** 실린다.
        self._set_engine_options(settings, {
            "max_passes": book.max_passes,
            "stop_on_match": book.stop_on_match,
        })
        self._set_active_preset(settings, name)
        store.apply_settings(settings)
        messages = [self._toast_message(f"조건부 프리셋 로드: {name}", "success")]
        # ⚠️ 프리셋은 **두 편집기 공용**이다. 반대쪽에서 저장한 것을 부르면 지금 칸이
        #    그 내용으로 바뀌는데, 예고가 없으면 "New Editor 기준으로 Legacy 내용이
        #    바뀌었다" 로 체감된다(사용자 제보). 막지는 않는다 - 되돌리기가 있고,
        #    불러오기는 자주 쓰는 동작이라 확인까지 세우면 마찰만 커진다(사용자 결정).
        saved_mode = meta.get("source_mode")
        if saved_mode in {"legacy", "v2"} and saved_mode != self._editor_mode(settings):
            other = "New Editor" if saved_mode == "v2" else "Legacy DSL"
            messages.append(self._toast_message(
                f"{other} 에서 저장된 프리셋입니다 — 지금 편집기의 규칙이 그 내용으로 바뀌었습니다.",
                "info",
            ))
        return self._state_with(messages=messages)

    @staticmethod
    def _restore_preset_text(book, meta: dict[str, Any]) -> str:
        """프리셋을 화면에 되돌릴 텍스트.

        저장해 둔 문서 원문(`source_dsl`)이 **지금 규칙과 같은 뜻이면 그대로** 쓴다.
        규칙마다의 원문(`Rule.source_text`)이 줄 하나하나를 지키는 데 더해, 이쪽은
        줄 사이의 배치(한 줄에 쉼표로 이어 쓴 형식·빈 줄)까지 지킨다.

        ⚠️ 뜻을 **다시 재서** 판정한다. 그래서 누군가 이 프리셋을 블록 편집기에서
        고쳐 저장하며 `source_dsl` 을 갱신하지 않았더라도 낡은 원문이 되살아나지
        않는다 - "지우는 걸 잊었다" 로 데이터가 어긋나는 길을 아예 막는다.
        """
        from core.conditional.dsl_parser import parse_rulebook
        from core.conditional.dsl_serializer import serialize_rulebook

        generated = serialize_rulebook(book)
        source = meta.get("source_dsl")
        if isinstance(source, str) and source.strip():
            try:
                if serialize_rulebook(parse_rulebook(source)) == generated:
                    return source
            except Exception as exc:   # 원문이 깨졌어도 로드는 살아야 한다
                print(f"Remote: conditional preset source_dsl check failed: {exc}")
        return generated

    def _handle_preset_delete(self, store, settings: dict[str, Any], text_value: str) -> dict[str, Any]:
        name = text_value.strip()
        if name and self._storage().delete(name):
            # 지운 이름이 걸려 있던 **모든 모드**에서 뗀다. 한쪽만 떼면 다른 모드가
            # 없는 프리셋 이름을 계속 내걸고, 그걸 누르면 "찾을 수 없음" 이 뜬다.
            removed = False
            for key in ("active_preset_legacy", "active_preset_v2"):
                if str(settings.get(key) or "") == name:
                    settings[key] = None
                    removed = True
            # ⚠️ 지금 모드의 쓰기도 감싼다. 파일은 **이미 unlink 된 뒤**라(위 `delete`),
            #    여기서 예외가 올라가면 프리셋은 사라졌는데 요청은 실패로 끝나고
            #    이름표는 남아 사용자가 다시 지울 수도 없다(Codex 3차 지적).
            #    다른 모드 정리와 같은 처리다 - 한쪽만 감싸 둔 것이 구멍이었다.
            if removed:
                try:
                    self._set_active_preset(settings, settings.get(self._preset_key(settings)))
                    store.apply_settings(settings)
                except Exception as exc:
                    print(f"Remote: conditional preset label cleanup failed for current mode: {exc}")
            # ⚠️ 프리셋 **파일은 API 모드 공용**인데 설정은 NAI/WEBUI/COMFYUI 로
            #    갈린다. 지금 모드에서만 떼면 다른 모드가 지워진 이름을 계속 내걸고,
            #    누르면 "찾을 수 없음" 이 뜬다(Codex 지적, 코드로 확인).
            self._forget_preset_in_other_modes(store, name)
            return self._state_with(messages=[self._toast_message(f"조건부 프리셋 삭제: {name}", "success")])
        return self._state_with(messages=[
            self._toast_message(f"삭제할 사용자 프리셋을 찾을 수 없습니다: {name}", "error"),
        ])

    def _forget_preset_in_other_modes(self, store, name: str) -> None:
        """지운 프리셋 이름을 **다른 API 모드**의 이름표에서도 뗀다.

        ⚠️ 부분 업데이트로 보내지 않는다. `apply_settings` 는 받은 dict 를 현재
        값 위에 얹은 뒤 정규화하는데, 새 키만 None 으로 지우고 옛 alias
        (`active_preset`)를 그대로 두면 남은 alias 가 다시 살아난다. 그래서
        **전체 설정을 읽어 고쳐 통째로** 되돌려 준다.
        """
        from core.conditional_prompt_settings import normalize_conditional_mode

        current = normalize_conditional_mode(store.mode())
        for other in ("NAI", "WEBUI", "COMFYUI"):
            if other == current:
                continue
            # ⚠️ 쓰기까지 감싼다. 프리셋 파일은 **이미 지워진 뒤**라, 여기서 예외가
            #    올라가면 삭제는 성공했는데 요청은 실패로 보이고 사용자는 다시 지울
            #    수도 없다(Codex 지적). 한 모드가 실패해도 나머지는 계속 뗀다.
            try:
                settings = store.collect_settings(other)
                changed = False
                for key in ("active_preset_legacy", "active_preset_v2", "active_preset"):
                    if str(settings.get(key) or "") == name:
                        settings[key] = None
                        changed = True
                if changed:
                    store.apply_settings(settings, other)
            except Exception as exc:
                print(f"Remote: conditional preset label cleanup failed for {other}: {exc}")

    # ------------------------------------------------------------------
    # Simulation
    # ------------------------------------------------------------------

    def _handle_simulation(self, key: str, settings: dict[str, Any], text_value: str) -> dict[str, Any]:
        if key == "simulate_v2":
            try:
                from core.conditional.dsl_serializer import serialize_rulebook

                book, _data = self._book_from_json_value(text_value)
                dsl = serialize_rulebook(book)
            except Exception as exc:
                return self._state_with(simulation={
                    "ok": False,
                    "error": f"규칙 직렬화 실패: {exc}",
                    "matched_rule_texts": [],
                    "matched_count": 0,
                    "final_prompt": None,
                    "sample": None,
                })
            result = self._run_simulation(dsl, {
                "max_passes": book.max_passes, "stop_on_match": book.stop_on_match,
            })
            return self._state_with(simulation=result)

        # legacy "test"
        # ⚠️ 예전 식은 `str(A if cond else B or "")` 이라 우선순위가 어긋나 있었다 -
        #    v2 인데 `rules_v2` 가 비어 있으면 `str(None)` = **문자열 "None"** 이
        #    DSL 로 파싱됐다. 헬퍼 한 곳으로 모은다.
        result = self._run_simulation(self._active_rules(settings), self._active_engine_options(settings))
        self._last_log = self._format_sim_log(result)
        return self.state()

    @staticmethod
    def _format_sim_log(result: dict[str, Any]) -> str:
        if not result.get("ok"):
            return f"=== 시뮬레이션 실패 ===\nError: {result.get('error') or '알 수 없는 오류'}"
        lines = [f"=== 시뮬레이션 성공 — 매칭 {int(result.get('matched_count') or 0)}개 ==="]
        options = result.get("engine_options") or {}
        lines.append(f"검색 샘플 테스트 · 모듈 ON 가정 · max_passes={options.get('max_passes', 1)} · stop_on_match={options.get('stop_on_match', False)}")
        lines.append("수동 Generate는 현재 입력에서 neg 규칙만 평가합니다. 테스트 샘플과 조건이 다를 수 있습니다.")
        sample = result.get("sample") or {}
        if sample:
            lines.append(
                f"샘플: rating={sample.get('rating') or '-'} / "
                f"character={sample.get('character') or '-'} / artist={sample.get('artist') or '-'}"
            )
        for rule in result.get("matched_rule_texts") or []:
            lines.append(f"Condition Met: {rule}")
        if result.get("final_prompt"):
            lines.append("")
            lines.append(str(result["final_prompt"]))
        lines.extend(["", "[네거티브 적용 전]", str(result.get("negative_before") or "(비어 있음)"),
                      "[네거티브 적용 후]", str(result.get("negative_after") or "(비어 있음)")])
        return "\n".join(lines)

    def _run_simulation(self, dsl_text: str, engine_options: dict[str, Any] | None = None) -> dict[str, Any]:
        from core.conditional_prompt_settings import normalize_conditional_engine_options
        from core.headless_generation_service import HeadlessGenerationService

        options = normalize_conditional_engine_options(engine_options or {})
        base_negative = str(getattr(self.context, "negative_prompt_text", "") or "")
        result: dict[str, Any] = {
            "ok": False,
            "error": None,
            "matched_rule_texts": [],
            "matched_count": 0,
            "final_prompt": None,
            "sample": None,
            "engine_options": options,
            "forced_enabled": True,
            "negative_before": base_negative,
            "negative_after": base_negative,
            "conditional_negative_ops": [],
        }
        text = str(dsl_text or "").strip()
        if not text:
            result["error"] = "규칙이 비어있습니다."
            return result

        context = self.context
        try:
            from core.headless_random_prompt_service import HeadlessRandomPromptService

            rps = getattr(context, "headless_random_prompt_service", None)
            if rps is None:
                rps = HeadlessRandomPromptService(context)
                context.headless_random_prompt_service = rps
            settings = rps._random_settings(None)
            rps._ensure_headless_runtime()
            if not rps._ensure_search_results(settings):
                result["error"] = "검색 결과가 없습니다. 먼저 검색을 수행하세요."
                return result
            service = rps._prompt_generation_service()
        except Exception as exc:
            result["error"] = f"시뮬레이션 준비 실패: {exc}"
            return result

        sample_row = self._sample_row()
        if sample_row is None:
            result["error"] = "샘플 행을 추출할 수 없습니다."
            return result
        result["sample"] = self._sample_summary(sample_row)

        saved_override = getattr(context, "session_cond_override", None)
        saved_recorder = getattr(context, "session_cond_simulate", None)
        recorder: list[str] = []
        try:
            context.session_cond_override = {"enabled": True, "rules": text, "engine_options": options}
            context.session_cond_simulate = recorder
            generated = service.generate_instant_source_result_silent(sample_row, settings)
            if generated.error or generated.context is None:
                raise RuntimeError(generated.error or "시뮬레이션 결과가 없습니다.")
            ops = generated.context.metadata.get("conditional_negative_ops") or []
            result["ok"] = True
            result["final_prompt"] = generated.final_prompt
            result["conditional_negative_ops"] = ops
            result["negative_after"] = HeadlessGenerationService.merge_negative_ops(base_negative, ops)
            matched = [r for r in recorder if r]
            result["matched_rule_texts"] = matched
            result["matched_count"] = len(set(matched))
        except Exception as exc:
            result["error"] = f"시뮬레이션 실행 실패: {exc}"
        finally:
            context.session_cond_override = saved_override
            context.session_cond_simulate = saved_recorder
        return result

    def _sample_row(self):
        context = self.context
        for attr in ("search_results", "search_results_snapshot", "search_results_master_base_snapshot"):
            source = getattr(context, attr, None)
            if source is None:
                continue
            frame = None
            getter = getattr(source, "get_dataframe", None)
            if callable(getter):
                try:
                    frame = getter()
                except Exception:
                    frame = None
            elif getattr(source, "empty", None) is not None:
                frame = source
            if frame is None or getattr(frame, "empty", True):
                continue
            try:
                return frame.sample(n=1).iloc[0].copy()
            except Exception:
                continue
        return None

    @staticmethod
    def _sample_summary(row) -> dict[str, Any]:
        def _get(key: str) -> str:
            try:
                return str(row.get(key, "") or "").strip()
            except Exception:
                return ""

        def _first(value: str) -> str:
            return value.split(",")[0].strip() if value else ""

        return {
            "rating": (_get("rating")[:1] if _get("rating") else ""),
            "character": _first(_get("character")),
            "artist": _first(_get("artist")),
            "general_preview": _get("general")[:120],
        }
