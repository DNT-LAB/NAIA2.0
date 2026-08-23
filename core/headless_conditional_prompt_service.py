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
        return self.context._module_state_payload("conditional_prompt", {
            "enabled": bool(settings.get("enabled", False)),
            "editor_mode": editor_mode,
            "rules": active_rules,
            "active_rules": active_rules,
            "rules_legacy": rules_legacy,
            "rules_v2": rules_v2,
            "rules_v2_book": self._rulebook_dict_from_dsl(rules_v2, engine_options),
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
    ) -> dict[str, Any]:
        payload = self.state()
        if simulation is not None:
            payload["simulation"] = simulation
            payload["local_dirty"] = True
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
    def _write_active_rules(cls, settings: dict[str, Any], dsl: str) -> None:
        settings[cls._rules_key(settings)] = dsl

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

        name = str(payload.get("name") or "").strip()
        source_preset = str(payload.get("source_preset") or "").strip()
        activate_raw = payload.get("activate", False)
        activate = activate_raw is True or (
            isinstance(activate_raw, str) and activate_raw.strip().lower() == "true"
        )
        book_data = payload.get("book") if isinstance(payload.get("book"), dict) else None

        if not name:
            return self._state_with(messages=[self._toast_message("조건부 프리셋 이름이 비어 있습니다.", "error")])

        storage = self._storage()
        if any(info.name == name and info.is_bundled for info in storage.list_all()):
            return self._state_with(messages=[self._toast_message("번들 프리셋과 같은 이름으로 저장할 수 없습니다.", "error")])

        book = None
        try:
            if book_data is not None:
                book = rulebook_from_dict(book_data)
            elif source_preset:
                book = storage.load(source_preset)
            else:
                # ⚠️ **화면에 보이는 규칙**을 담는다. 예전에는 `rules_v2` 로 못박혀
                # 있어서, Legacy 편집기를 쓰던 사용자가 저장을 누르면 자기가 보고
                # 있지도 않은(대개 비어 있는) v2 텍스트가 프리셋이 됐다.
                book = parse_rulebook(self._active_rules(settings))
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

        storage.save(name, book)
        self._set_active_preset(settings, name)
        if activate:
            self._write_active_rules(settings, serialize_rulebook(book))
            self._set_engine_options(settings, {
                "max_passes": book.max_passes,
                "stop_on_match": book.stop_on_match,
            })
        store.apply_settings(settings)
        return self._state_with(messages=[self._toast_message(f"조건부 프리셋 저장: {name}", "success")])

    def _handle_preset_load(self, store, settings: dict[str, Any], text_value: str) -> dict[str, Any]:
        from core.conditional.dsl_serializer import serialize_rulebook

        name = text_value.strip()
        if not name:
            return self._state_with(messages=[self._toast_message("로드할 프리셋 이름이 비어 있습니다.", "error")])
        try:
            book = self._storage().load(name)
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
        self._write_active_rules(settings, serialize_rulebook(book))
        # 프리셋의 옵션은 **그 프리셋을 부른 모드에만** 실린다.
        self._set_engine_options(settings, {
            "max_passes": book.max_passes,
            "stop_on_match": book.stop_on_match,
        })
        self._set_active_preset(settings, name)
        store.apply_settings(settings)
        return self._state_with(messages=[self._toast_message(f"조건부 프리셋 로드: {name}", "success")])

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
            if removed:
                self._set_active_preset(settings, settings.get(self._preset_key(settings)))
                store.apply_settings(settings)
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
            try:
                settings = store.collect_settings(other)
            except Exception:
                continue
            changed = False
            for key in ("active_preset_legacy", "active_preset_v2", "active_preset"):
                if str(settings.get(key) or "") == name:
                    settings[key] = None
                    changed = True
            if changed:
                store.apply_settings(settings, other)

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
            result = self._run_simulation(dsl)
            return self._state_with(simulation=result)

        # legacy "test"
        # ⚠️ 예전 식은 `str(A if cond else B or "")` 이라 우선순위가 어긋나 있었다 -
        #    v2 인데 `rules_v2` 가 비어 있으면 `str(None)` = **문자열 "None"** 이
        #    DSL 로 파싱됐다. 헬퍼 한 곳으로 모은다.
        result = self._run_simulation(self._active_rules(settings))
        self._last_log = self._format_sim_log(result)
        return self.state()

    @staticmethod
    def _format_sim_log(result: dict[str, Any]) -> str:
        if not result.get("ok"):
            return f"=== 시뮬레이션 실패 ===\nError: {result.get('error') or '알 수 없는 오류'}"
        lines = [f"=== 시뮬레이션 성공 — 매칭 {int(result.get('matched_count') or 0)}개 ==="]
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
        return "\n".join(lines)

    def _run_simulation(self, dsl_text: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": False,
            "error": None,
            "matched_rule_texts": [],
            "matched_count": 0,
            "final_prompt": None,
            "sample": None,
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
            context.session_cond_override = {"enabled": True, "rules": text}
            context.session_cond_simulate = recorder
            final = service.generate_instant_source_silent(sample_row, settings)
            result["ok"] = True
            result["final_prompt"] = final
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
