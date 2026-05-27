from __future__ import annotations

import re
from typing import Any

from core.conditional_prompt_settings import (
    get_conditional_prompt_store,
    normalize_conditional_engine_options,
)
from core.wildcard_processor import split_tags_smart


_WEIGHT_NAI_RE = re.compile(r"^\s*[+-]?\d+(?:\.\d+)?::(.*?)\s*::\s*$")
_WEIGHT_WEBUI_RE = re.compile(r"^\((.*):[+-]?\d+(?:\.\d+)?\)$")
_RATING_FUNC_RE = re.compile(r"^(~)?rating\(\s*([eqsg])(?:\s*,\s*source\s*=\s*([^)]+))?\s*\)$", re.IGNORECASE)
_CHAR_IN_RE = re.compile(r"^(~)?char_in\(\s*(\d+)\s*,\s*(.*?)\s*\)$", re.IGNORECASE)
_CHAR_ON_RE = re.compile(r"^(~)?char_on\(\s*(\d+)\s*\)$", re.IGNORECASE)
_CHAR_UC_TARGET_RE = re.compile(r"^(char|uc):(\d+|\*)$", re.IGNORECASE)
_FUNC_ACTION_RE = re.compile(r"^([A-Za-z_]\w*)\((.*)\)$")


def _strip_weight_format(text: str) -> str:
    value = str(text or "").strip()
    match = _WEIGHT_NAI_RE.match(value)
    if match:
        return match.group(1).strip()
    match = _WEIGHT_WEBUI_RE.match(value)
    if match:
        return match.group(1).strip()
    return value


def _remove_outer_quotes(text: str) -> str:
    value = str(text or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1].strip()
    return value


def _append_unique(out: list[str], value: str) -> None:
    value = str(value or "").strip()
    if value and value not in out:
        out.append(value)


class HeadlessConditionalRuleEngine:
    """Small PyQt-free evaluator for the legacy conditional prompt DSL."""

    def __init__(self, app_context):
        self.app_context = app_context

    @staticmethod
    def _condition_tag_variants(value: Any) -> list[str]:
        variants: list[str] = []

        def add_variants(candidate: str) -> None:
            candidate = str(candidate or "").strip()
            if not candidate:
                return
            for base in (candidate, candidate.replace(r"\(", "(").replace(r"\)", ")")):
                _append_unique(variants, base)
                raw = _strip_weight_format(base)
                _append_unique(variants, raw)
                if raw.startswith("(") and raw.endswith(")"):
                    _append_unique(variants, raw[1:-1])

        if value is None:
            return variants
        if isinstance(value, (list, tuple, set)):
            for item in value:
                for candidate in HeadlessConditionalRuleEngine._condition_tag_variants(item):
                    _append_unique(variants, candidate)
            return variants
        if not isinstance(value, str):
            return variants
        add_variants(value)
        for tag in split_tags_smart(value):
            add_variants(tag)
        return variants

    @classmethod
    def _append_condition_tag_value(cls, out: list[str], value: Any) -> None:
        for candidate in cls._condition_tag_variants(value):
            _append_unique(out, candidate)

    @classmethod
    def _append_condition_tag_group_value(cls, out: list[str], value: Any, group: str) -> None:
        cls._append_condition_tag_value(out, value)
        for tag in cls._condition_tag_variants(value):
            lower = tag.lower()
            if group == "artist":
                normalized = tag[1:].strip() if tag.startswith("@") else tag
                if lower.startswith("artist:"):
                    normalized = tag[len("artist:"):].strip()
                elif lower.startswith("@artist:"):
                    normalized = tag[len("@artist:"):].strip()
                for candidate in (
                    normalized,
                    f"artist:{normalized}",
                    f"@{normalized}",
                    f"@artist:{normalized}",
                ):
                    _append_unique(out, candidate)
            elif group == "copyright":
                normalized = tag
                for prefix in ("copyright:", "work_title:", "worktitle:"):
                    if lower.startswith(prefix):
                        normalized = tag[len(prefix):].strip()
                        break
                for candidate in (
                    normalized,
                    f"copyright:{normalized}",
                    f"work_title:{normalized}",
                    f"worktitle:{normalized}",
                ):
                    _append_unique(out, candidate)
            elif group == "character":
                normalized = tag[len("character:"):].strip() if lower.startswith("character:") else tag
                for candidate in (normalized, f"character:{normalized}"):
                    _append_unique(out, candidate)

    def _condition_tag_scope(self, context) -> list[str]:
        tags: list[str] = []
        for item in list(context.prefix_tags) + list(context.main_tags) + list(context.postfix_tags):
            self._append_condition_tag_value(tags, item)
        metadata = getattr(context, "metadata", None) or {}
        for key, group in (
            ("anima_character", "character"),
            ("anima_copyright", "copyright"),
            ("anima_artist", "artist"),
        ):
            self._append_condition_tag_group_value(tags, metadata.get(key), group)
        return tags

    def _rating_from_context(self, context) -> str:
        override = getattr(self.app_context, "rating_override", None)
        if override:
            return str(override).strip().lower()[:1]
        row = getattr(context, "source_row", None)
        try:
            return str(row.get("rating", "")).strip().lower()[:1]
        except Exception:
            return ""

    def _character_frames(self) -> list[dict[str, Any]]:
        try:
            settings = self.app_context._character_settings_cache()
        except Exception:
            return []
        frames = settings.get("character_frames") if isinstance(settings, dict) else []
        return frames if isinstance(frames, list) else []

    def _character_scope(self, index: int) -> list[str]:
        frames = self._character_frames()
        if index < 0 or index >= len(frames) or not isinstance(frames[index], dict):
            return []
        tags: list[str] = []
        self._append_condition_tag_value(tags, frames[index].get("prompt"))
        return tags

    def _character_active(self, index: int) -> bool:
        frames = self._character_frames()
        if index < 0 or index >= len(frames) or not isinstance(frames[index], dict):
            return False
        frame = frames[index]
        return bool(frame.get("is_enabled")) or str(frame.get("slot_state") or "").lower() == "active"

    @staticmethod
    def _parse_char_uc_target(target: str) -> tuple[str, int | str] | None:
        match = _CHAR_UC_TARGET_RE.match(str(target or "").strip())
        if not match:
            return None
        kind = match.group(1).lower()
        raw_index = match.group(2)
        if raw_index == "*":
            return kind, "*"
        index = int(raw_index)
        if index < 1:
            return None
        return kind, index - 1

    @classmethod
    def _is_char_uc_target(cls, target: str) -> bool:
        return cls._parse_char_uc_target(target) is not None

    def _character_slots(self, context) -> list[dict[str, Any]]:
        metadata = getattr(context, "metadata", None)
        if isinstance(metadata, dict):
            existing = metadata.get("_conditional_character_slots")
            if isinstance(existing, list):
                return [dict(slot) for slot in existing if isinstance(slot, dict)]

        frames = self._character_frames()
        settings = getattr(context, "settings", None) or {}
        settings_chars = list(settings.get("characters") or []) if isinstance(settings, dict) else []
        settings_ucs = list(settings.get("uc") or []) if isinstance(settings, dict) else []
        slots: list[dict[str, Any]] = []

        if frames:
            active_position = 0
            for index, frame in enumerate(frames):
                frame = frame if isinstance(frame, dict) else {}
                active = self._character_active(index)
                prompt = str(frame.get("prompt") or "")
                uc = str(frame.get("uc") or "")
                if active:
                    if active_position < len(settings_chars):
                        prompt = str(settings_chars[active_position] or "")
                    if active_position < len(settings_ucs):
                        uc = str(settings_ucs[active_position] or "")
                    active_position += 1
                slots.append({"prompt": prompt, "uc": uc, "active": active})
            return slots

        total = max(len(settings_chars), len(settings_ucs))
        for index in range(total):
            prompt = str(settings_chars[index] or "") if index < len(settings_chars) else ""
            uc = str(settings_ucs[index] or "") if index < len(settings_ucs) else ""
            slots.append({"prompt": prompt, "uc": uc, "active": bool(prompt.strip())})
        return slots

    @staticmethod
    def _record_character_skip(context, target: str, reason: str) -> None:
        metadata = getattr(context, "metadata", None)
        if not isinstance(metadata, dict):
            return
        skips = metadata.setdefault("conditional_character_skips", [])
        if isinstance(skips, list):
            skips.append({"target": target, "reason": reason})

    def _store_character_overrides(self, context, slots: list[dict[str, Any]]) -> None:
        settings = getattr(context, "settings", None)
        if not isinstance(settings, dict):
            context.settings = {}
            settings = context.settings
        metadata = getattr(context, "metadata", None)
        if not isinstance(metadata, dict):
            context.metadata = {}
            metadata = context.metadata

        characters: list[str] = []
        ucs: list[str] = []
        for slot in slots:
            prompt = str(slot.get("prompt") or "").strip()
            if slot.get("active") and prompt:
                characters.append(prompt)
                ucs.append(str(slot.get("uc") or "").strip())

        settings["characters"] = characters
        settings["uc"] = ucs
        metadata["_conditional_character_slots"] = [dict(slot) for slot in slots]
        metadata["conditional_character_overrides"] = {
            "characters": characters,
            "uc": ucs,
        }

    def _write_char_uc_target(
        self,
        context,
        target: str,
        tags: list[str],
        *,
        op: str,
    ) -> None:
        parsed = self._parse_char_uc_target(target)
        if parsed is None:
            return
        slots = self._character_slots(context)
        if not slots:
            self._record_character_skip(context, target, "no character slots")
            return
        kind, index = parsed
        if index == "*":
            indices = [slot_index for slot_index, slot in enumerate(slots) if slot.get("active")]
            if not indices:
                self._record_character_skip(context, target, "no active character slots")
                return
        elif isinstance(index, int) and 0 <= index < len(slots):
            indices = [index]
        else:
            self._record_character_skip(context, target, f"index {int(index) + 1} missing")
            return

        text = ", ".join(str(tag).strip() for tag in tags if str(tag).strip())
        if op == "append" and not text:
            return
        field = "prompt" if kind == "char" else "uc"
        for slot_index in indices:
            current = str(slots[slot_index].get(field) or "").strip()
            if op == "append" and current and text:
                slots[slot_index][field] = f"{current}, {text}"
            elif op in {"append", "set"}:
                slots[slot_index][field] = text
        self._store_character_overrides(context, slots)

    def _execute_char_set(self, context, char_index: int, state: str) -> None:
        slots = self._character_slots(context)
        if char_index < 0 or char_index >= len(slots):
            self._record_character_skip(context, f"char_set({char_index + 1})", "index missing")
            return
        slots[char_index]["active"] = state == "enabled"
        self._store_character_overrides(context, slots)

    def _execute_char_replace(self, context, char_index: int, old_tag: str, new_tag: str) -> None:
        slots = self._character_slots(context)
        if char_index < 0 or char_index >= len(slots):
            self._record_character_skip(context, f"char_replace({char_index + 1})", "index missing")
            return
        tags = [tag.strip() for tag in split_tags_smart(str(slots[char_index].get("prompt") or "")) if tag.strip()]
        old_value = str(old_tag or "").strip()
        new_value = str(new_tag or "").strip()
        replaced = False
        for index, tag in enumerate(tags):
            if tag == old_value or _strip_weight_format(tag) == old_value:
                tags[index] = new_value
                replaced = True
        if not replaced:
            self._record_character_skip(context, f"char_replace({char_index + 1})", "tag missing")
            return
        slots[char_index]["prompt"] = ", ".join(tag for tag in tags if tag)
        self._store_character_overrides(context, slots)

    @staticmethod
    def _matching_paren(text: str, start: int) -> int:
        depth = 1
        for index in range(start + 1, len(text)):
            if text[index] == "(":
                depth += 1
            elif text[index] == ")":
                depth -= 1
                if depth == 0:
                    return index
        return -1

    @staticmethod
    def _split_by_operator(expression: str, operator: str) -> list[str]:
        parts: list[str] = []
        current: list[str] = []
        depth = 0
        for char in expression:
            if char == "(":
                depth += 1
            elif char == ")":
                depth = max(0, depth - 1)
            if char == operator and depth == 0:
                part = "".join(current).strip()
                if part:
                    parts.append(part)
                current = []
            else:
                current.append(char)
        part = "".join(current).strip()
        if part:
            parts.append(part)
        return parts if len(parts) > 1 else [expression]

    def _evaluate_logical_expression(self, expression: str, tags: list[str], context) -> bool:
        expression = str(expression or "").strip()
        if not expression:
            return True
        while expression.startswith("(") and expression.endswith(")"):
            end = self._matching_paren(expression, 0)
            if end != len(expression) - 1:
                break
            expression = expression[1:-1].strip()
        and_parts = self._split_by_operator(expression, "&")
        if len(and_parts) > 1:
            return all(self._evaluate_logical_expression(part, tags, context) for part in and_parts)
        or_parts = self._split_by_operator(expression, "|")
        if len(or_parts) > 1:
            return any(self._evaluate_logical_expression(part, tags, context) for part in or_parts)
        return self._evaluate_single_condition(expression, tags, context)

    def _evaluate_single_condition(self, condition: str, tags: list[str], context) -> bool:
        condition = _remove_outer_quotes(condition)
        rating_match = _RATING_FUNC_RE.match(condition)
        if rating_match:
            negated = rating_match.group(1) == "~"
            expected = rating_match.group(2).lower()
            matched = self._rating_from_context(context) == expected
            return not matched if negated else matched
        char_in_match = _CHAR_IN_RE.match(condition)
        if char_in_match:
            negated = char_in_match.group(1) == "~"
            index = int(char_in_match.group(2)) - 1
            matched = self._evaluate_logical_expression(char_in_match.group(3), self._character_scope(index), context)
            return not matched if negated else matched
        char_on_match = _CHAR_ON_RE.match(condition)
        if char_on_match:
            negated = char_on_match.group(1) == "~"
            index = int(char_on_match.group(2)) - 1
            matched = self._character_active(index)
            return not matched if negated else matched

        if condition in {"e", "q", "s", "g"}:
            return self._rating_from_context(context) == condition
        if condition in {"~e", "~q", "~s", "~g"}:
            return self._rating_from_context(context) != condition[1:]

        if condition.startswith("~!"):
            needles = self._condition_tag_variants(condition[2:].strip())
            return not any(needle in tags for needle in needles)
        if condition.startswith("~"):
            needles = self._condition_tag_variants(condition[1:].strip())
            return not any(needle in tag for needle in needles for tag in tags)
        if condition.startswith("!"):
            needles = self._condition_tag_variants(condition[1:].strip())
            return any(needle in tags for needle in needles)
        if condition.startswith("*"):
            needles = self._condition_tag_variants(condition[1:].strip())
            return any(needle in tag for needle in needles for tag in tags)
        needles = self._condition_tag_variants(condition)
        return any(needle in tags for needle in needles)

    def _parse_tag_list(self, tag_text: str) -> list[str]:
        tag_text = _remove_outer_quotes(tag_text)
        if "^" in tag_text:
            tags = [tag.strip() for tag in tag_text.split("^") if tag.strip()]
        else:
            tags = [tag.strip() for tag in split_tags_smart(tag_text) if tag.strip()]
        return [_remove_outer_quotes(tag) for tag in tags]

    def _split_rules_with_quotes(self, rules_text: str) -> list[str]:
        rules: list[str] = []
        current: list[str] = []
        in_quotes = False
        depth = 0
        text = str(rules_text or "")
        for index, char in enumerate(text):
            if char == '"' and (index == 0 or text[index - 1] != "\\"):
                in_quotes = not in_quotes
            elif not in_quotes and char == "(":
                depth += 1
            elif not in_quotes and char == ")":
                depth = max(0, depth - 1)
            if char == "," and not in_quotes and depth == 0:
                rule = "".join(current).strip()
                if rule and not rule.startswith("#"):
                    rules.append(rule)
                current = []
            else:
                current.append(char)
        rule = "".join(current).strip()
        if rule and not rule.startswith("#"):
            rules.append(rule)
        return rules

    def _parse_rule(self, rule_text: str) -> dict[str, Any] | None:
        rule_text = str(rule_text or "").strip()
        if not rule_text.startswith("("):
            return None
        end = self._matching_paren(rule_text, 0)
        if end < 0 or end + 1 >= len(rule_text) or rule_text[end + 1] != ":":
            return None
        action = self._parse_action(rule_text[end + 2:].strip())
        if not action:
            return None
        return {"condition": rule_text[1:end].strip(), "action": action, "original": rule_text}

    def _parse_rules(self, rules_text: str) -> list[dict[str, Any]]:
        rules: list[dict[str, Any]] = []
        for part in self._split_rules_with_quotes(rules_text):
            rule = self._parse_rule(part)
            if rule is not None:
                rules.append(rule)
        return rules

    def _try_parse_func_action(self, action_text: str) -> dict[str, Any] | None:
        match = _FUNC_ACTION_RE.match(action_text)
        if not match:
            return None
        func_name = match.group(1)
        args_text = match.group(2).strip()
        args = [arg.strip() for arg in args_text.split(",")] if args_text else []
        if func_name == "char_set" and len(args) == 2:
            try:
                char_index = int(args[0]) - 1
            except ValueError:
                return None
            state = args[1].lower()
            if state not in {"enabled", "disabled"}:
                return None
            return {"type": "func_char_set", "char_index": char_index, "state": state}
        if func_name == "char_replace" and len(args) == 3:
            try:
                char_index = int(args[0]) - 1
            except ValueError:
                return None
            return {
                "type": "func_char_replace",
                "char_index": char_index,
                "old_tag": args[1],
                "new_tag": args[2],
            }
        return None

    def _parse_action(self, action_text: str) -> dict[str, Any] | None:
        action_text = _remove_outer_quotes(action_text)
        func_action = self._try_parse_func_action(action_text)
        if func_action is not None:
            return func_action
        if "+=" in action_text:
            target, value = action_text.split("+=", 1)
            tags = self._parse_tag_list(value)
            target = target.strip()
            return {
                "type": "append_to_list" if target in {"prefix", "main", "postfix"} or self._is_char_uc_target(target) else "insert",
                "target": target,
                "tags": tags,
            }
        if "+:" in action_text:
            target, _sep, value = action_text.partition("+:")
            target = target.strip()
            if target not in {"prefix", "main", "postfix"} and not self._is_char_uc_target(target):
                value = action_text.replace("+:", "", 1)
                target = "main"
            return {"type": "append_to_list", "target": target, "tags": self._parse_tag_list(value)}
        if "=" in action_text:
            old, value = action_text.split("=", 1)
            target = old.strip()
            if self._is_char_uc_target(target):
                return {"type": "set_character_target", "target": target, "tags": self._parse_tag_list(value)}
            return {"type": "replace", "old": old.strip(), "tags": self._parse_tag_list(value)}
        return None

    @staticmethod
    def _target_list(prefix_tags: list[str], main_tags: list[str], postfix_tags: list[str], target: str) -> list[str]:
        if target == "prefix":
            return prefix_tags
        if target == "postfix":
            return postfix_tags
        return main_tags

    @staticmethod
    def _tag_matches_action_target(tag: str, target: str) -> bool:
        if target.startswith("*"):
            return target[1:].strip() in tag
        return tag == target

    def _execute_action(
        self,
        context,
        action: dict[str, Any],
        prefix_tags: list[str],
        main_tags: list[str],
        postfix_tags: list[str],
    ) -> tuple[list[str], list[str], list[str]]:
        action_type = action.get("type")
        if action_type == "append_to_list":
            target = str(action.get("target") or "main")
            if self._is_char_uc_target(target):
                self._write_char_uc_target(context, target, list(action.get("tags") or []), op="append")
            else:
                self._target_list(prefix_tags, main_tags, postfix_tags, target).extend(list(action.get("tags") or []))
        elif action_type == "insert":
            target = str(action.get("target") or "")
            tags = list(action.get("tags") or [])
            for tag_list in (prefix_tags, main_tags, postfix_tags):
                for index, tag in enumerate(tag_list):
                    if self._tag_matches_action_target(str(tag), target):
                        tag_list[index + 1:index + 1] = tags
                        return prefix_tags, main_tags, postfix_tags
        elif action_type == "replace":
            target = str(action.get("old") or "")
            replacements = list(action.get("tags") or [])
            for tag_list in (prefix_tags, main_tags, postfix_tags):
                index = 0
                while index < len(tag_list):
                    if self._tag_matches_action_target(str(tag_list[index]), target):
                        tag_list[index:index + 1] = replacements
                        index += len(replacements)
                    else:
                        index += 1
        elif action_type == "set_character_target":
            self._write_char_uc_target(
                context,
                str(action.get("target") or ""),
                list(action.get("tags") or []),
                op="set",
            )
        elif action_type == "func_char_set":
            self._execute_char_set(
                context,
                int(action.get("char_index") or 0),
                str(action.get("state") or "enabled"),
            )
        elif action_type == "func_char_replace":
            self._execute_char_replace(
                context,
                int(action.get("char_index") or 0),
                str(action.get("old_tag") or ""),
                str(action.get("new_tag") or ""),
            )
        return prefix_tags, main_tags, postfix_tags

    def apply(
        self,
        context,
        rules_text: str,
        *,
        max_passes: int = 1,
        stop_on_match: bool = False,
    ):
        rules = self._parse_rules(rules_text)
        if not rules:
            return context
        prefix_tags = list(context.prefix_tags)
        main_tags = list(context.main_tags)
        postfix_tags = list(context.postfix_tags)
        seen: set[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = set()

        for _pass_index in range(max(1, int(max_passes or 1))):
            matched = False
            scope_context = context
            scope_context.prefix_tags = prefix_tags
            scope_context.main_tags = main_tags
            scope_context.postfix_tags = postfix_tags
            scope = self._condition_tag_scope(scope_context)
            for rule in rules:
                if self._evaluate_logical_expression(str(rule["condition"]), scope, scope_context):
                    recorder = getattr(self.app_context, "session_cond_simulate", None)
                    if isinstance(recorder, list):
                        recorder.append(str(rule.get("original") or ""))
                    prefix_tags, main_tags, postfix_tags = self._execute_action(
                        scope_context,
                        rule["action"],
                        prefix_tags,
                        main_tags,
                        postfix_tags,
                    )
                    matched = True
                    if stop_on_match:
                        break
                    scope_context.prefix_tags = prefix_tags
                    scope_context.main_tags = main_tags
                    scope_context.postfix_tags = postfix_tags
                    scope = self._condition_tag_scope(scope_context)
            snapshot = (tuple(prefix_tags), tuple(main_tags), tuple(postfix_tags))
            if not matched or snapshot in seen:
                break
            seen.add(snapshot)

        context.prefix_tags = prefix_tags
        context.main_tags = main_tags
        context.postfix_tags = postfix_tags
        return context


class ConditionalPromptHeadlessHook:
    """Deferred WebSession hook for the conditional prompt module."""

    def __init__(self, app_context):
        self.app_context = app_context
        self._store = get_conditional_prompt_store(app_context)

    def get_title(self) -> str:
        return "Conditional Prompt"

    def get_pipeline_hook_info(self) -> dict[str, Any]:
        return {
            "target_pipeline": "PromptProcessor",
            "hook_point": "after_wildcard",
            "priority": 2,
        }

    def _session_override(self) -> dict[str, Any] | None:
        override = getattr(self.app_context, "session_cond_override", None)
        return override if isinstance(override, dict) else None

    def _active_settings(self) -> dict[str, Any] | None:
        override = self._session_override()
        if override is not None:
            if not override.get("enabled"):
                return None
            rules = str(override.get("rules") or "").strip()
            if not rules:
                return None
            return {
                "enabled": True,
                "rules": rules,
                "rules_v2": rules,
                "editor_mode": "v2",
                "engine_options": normalize_conditional_engine_options(
                    override.get("engine_options") or {}
                ),
                "active_preset": None,
            }

        settings = self._store.collect_settings()
        if not settings.get("enabled"):
            return None
        editor_mode = str(settings.get("editor_mode") or "legacy")
        rules_key = "rules_v2" if editor_mode == "v2" else "rules"
        rules = str(settings.get(rules_key) or "").strip()
        if not rules:
            return None
        settings = dict(settings)
        settings["rules"] = str(settings.get("rules") or "")
        settings["rules_v2"] = str(settings.get("rules_v2") or "")
        settings["engine_options"] = normalize_conditional_engine_options(
            settings.get("engine_options") or {}
        )
        return settings

    def _load_module(self):
        middle_controller = getattr(self.app_context, "middle_section_controller", None)
        if middle_controller is None or not hasattr(middle_controller, "get_module_instance"):
            return None
        return middle_controller.get_module_instance("PromptListModifierModule")

    def execute_pipeline_hook(self, context):
        active_settings = self._active_settings()
        if active_settings is None:
            return context

        module = self._load_module()
        if module is not None and hasattr(module, "execute_pipeline_hook"):
            if self._session_override() is None and hasattr(module, "apply_settings"):
                module.apply_settings(active_settings)
            return module.execute_pipeline_hook(context)

        editor_mode = str(active_settings.get("editor_mode") or "legacy")
        rules_text = (
            str(active_settings.get("rules_v2") or "")
            if editor_mode == "v2"
            else str(active_settings.get("rules") or "")
        )
        if not rules_text.strip():
            rules_text = str(active_settings.get("rules") or active_settings.get("rules_v2") or "")
        options = normalize_conditional_engine_options(active_settings.get("engine_options") or {})
        return HeadlessConditionalRuleEngine(self.app_context).apply(
            context,
            rules_text,
            max_passes=options.get("max_passes", 1),
            stop_on_match=bool(options.get("stop_on_match", False)),
        )


def register_conditional_prompt_headless_runtime(app_context) -> ConditionalPromptHeadlessHook:
    hook = getattr(app_context, "conditional_prompt_headless_hook", None)
    if isinstance(hook, ConditionalPromptHeadlessHook):
        return hook
    hook = ConditionalPromptHeadlessHook(app_context)
    app_context.register_pipeline_hook(hook.get_pipeline_hook_info(), hook)
    setattr(app_context, "conditional_prompt_headless_hook", hook)
    return hook
