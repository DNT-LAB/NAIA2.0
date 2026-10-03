"""Pure tone advice and NAI V5 prompt edits. No session, filesystem or network access."""
from __future__ import annotations

from copy import deepcopy
import math
import re

# Edit recommendation policy here. Levels are named API values: default / strong.
RULES = (
    {"id": "yellow_high", "axis": "yellow", "side": "high", "title": "누런 기를 줄이기",
     "actions": [{"field": "negative_prompt", "op": "add", "tags": ["sepia", "warm colored"]}],
     "levels": [], "evidence": {"level": "single_seed", "note": "evaiyu 한 시드에서 b* -7.2 · -6.4, 둘은 합산된다"},
     "cautions": [], "verify": []},
    {"id": "chroma_low", "axis": "chroma", "side": "low", "title": "색을 더하기",
     "actions": [{"field": "negative_prompt", "op": "add", "tags": ["monochrome", "greyscale", "muted color"]},
                 {"field": "prompt", "op": "set_weight", "tags": ["colorful"], "weight": .5}],
     "levels": [], "evidence": {"level": "single_seed", "note": "hamsterfragment 한 시드에서 밝기 27.9 → 40.1 · 채도 4.6 → 9.6"},
     "cautions": ["colorful 은 0.5 까지 — 1 이면 배경이 바뀐다"], "verify": []},
    {"id": "line_faint", "axis": "line_contrast", "side": "low", "title": "선을 또렷하게",
     "actions": [{"field": "prompt", "op": "set_weight", "tags": ["ultra complexity"], "weight": .5}],
     "levels": [], "evidence": {"level": "validated_30", "note": "5시드 x 2구도, 선 대비 9/10 상승(중앙 +3.7)"},
     "cautions": ["그림이 다시 뽑힌다", "거칠기가 는다", "0.5 를 넘겨도 선은 더 안 선다"], "verify": []},
    {"id": "line_absent", "axis": "line_contrast", "side": "low", "title": "선을 드러내기",
     "actions": [{"field": "prompt", "op": "set_weight", "tags": ["jaggy lines"], "weight": 2},
                 {"field": "negative_prompt", "op": "add", "tags": ["no lineart"]}],
     "levels": [{"id": "strong", "label": "센 단계", "actions": [
         {"field": "prompt", "op": "set_weight", "tags": ["jaggy lines", "black outline"], "weight": 2},
         {"field": "negative_prompt", "op": "add", "tags": ["no lineart"]}]}],
     "evidence": {"level": "user_report", "note": "evaiyu 에서 선 대비 약 20 → 34 ~ 44 (시드가 다른 한 장씩)"},
     "cautions": ["센 단계는 선이 검고 굵어진다"], "verify": []},
    {"id": "line_thick", "axis": "line_width", "side": "high", "title": "선을 가늘게",
     "actions": [{"field": "prompt", "op": "set_weight", "tags": ["thick outlines"], "weight": -2},
                 {"field": "negative_prompt", "op": "set_weight", "tags": ["thick outlines"], "weight": 2}],
     "levels": [{"id": "strong", "label": "센 단계", "actions": [
         {"field": "prompt", "op": "set_weight", "tags": ["thick outlines"], "weight": -2.5},
         {"field": "negative_prompt", "op": "set_weight", "tags": ["thick outlines"], "weight": 2.5}]}],
     "evidence": {"level": "user_report", "note": "alkaid exec 3.7 → 2.0 ~ 2.8"},
     "cautions": ["작가마다 듣는 세기가 다르다", "지나치면 선이 사라진다", "프롬프트에 no lineart 를 같이 넣지 않는다"],
     "verify": ["line_contrast"]},
)

FIELDS = ("pre_prompt", "prompt", "post_prompt", "negative_prompt")
# 세기(strength) - 규칙의 가중치에 곱한다. 화면이 약하게 / 기본 / 세게를 고르고, 같은 값으로 시험 생성과 반영을 한다.
STRENGTH_MIN, STRENGTH_MAX = 0.25, 2.0


def guide():
    """축 · 쪽마다 어떤 보정이 있는지(그림과 무관한 안내). 화면의 축 툴팁이 쓴다."""
    return [{key: deepcopy(rule[key]) for key in ("id", "axis", "side", "title", "actions", "levels", "cautions")}
            for rule in RULES]


def scaled_actions(actions, strength=1.0):
    """세기를 곱한 actions. 가중치가 없는 추가(add)는 세기가 1 이 아니면 그 세기의 가중치 묶음으로 바뀐다."""
    strength = float(strength)
    if not math.isfinite(strength) or not STRENGTH_MIN <= strength <= STRENGTH_MAX:
        raise ValueError(f"strength must be between {STRENGTH_MIN:g} and {STRENGTH_MAX:g}")
    if strength == 1:
        return deepcopy(list(actions))
    scaled = []
    for action in actions:
        item = deepcopy(action)
        if item["op"] == "set_weight":
            item["weight"] = round(item["weight"] * strength, 2)
        else:
            item["op"], item["weight"] = "set_weight", round(strength, 2)
        scaled.append(item)
    return scaled
_MARKER = re.compile(r"(?P<weight>[+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*::|(?P<close>::)|(?P<comma>,)")


def normalize_fields(fields):
    if not isinstance(fields, dict) or set(fields) - set(FIELDS):
        raise ValueError("fields must be an object containing only prompt fields")
    if any(not isinstance(value, str) for value in fields.values()):
        raise ValueError("prompt fields must be strings")
    return {name: fields.get(name, "") for name in FIELDS}


def _tag(text):
    return " ".join(text.replace("_", " ").casefold().split())


class _Prompt:
    """Offsets refer to a virtual concatenation; edits are mapped to original fields.

    Inserted commas delimit fields but do not close weight groups. Group membership
    spans fields, so moving one tag never changes the weights of its neighbours.
    """
    def __init__(self, fields, negative=False):
        names = ("negative_prompt",) if negative else FIELDS[:3]
        self.ranges, self.text = {}, ""
        for name in names:
            if self.ranges:
                self.text += ", "
            start = len(self.text)
            self.text += fields[name]
            self.ranges[name] = (start, len(self.text))
        self.tokens, self.groups, stack = [], [], []

        def token(start, end):
            raw = self.text[start:end]
            if not raw.strip():
                return
            start += len(raw)-len(raw.lstrip())
            end -= len(raw)-len(raw.rstrip())
            field = next((name for name, (a, b) in self.ranges.items() if a <= start < b), None)
            if field is None:
                return
            weight = math.prod(g["weight"] for g in stack)
            if not math.isfinite(weight):
                raise ValueError("Nonfinite effective prompt weight")
            item = {"start": start, "end": end, "tag": _tag(self.text[start:end]), "field": field,
                    "groups": list(stack), "weight": weight}
            self.tokens.append(item)
            for group in stack:
                # Groups only need membership count and tag labels. Storing the
                # full item here creates a group <-> token cycle on every parse.
                group["tokens"].append({"tag": item["tag"]})

        cursor = 0
        for match in _MARKER.finditer(self.text):
            token(cursor, match.start())
            if match.group("weight") is not None:
                weight = float(match.group("weight"))
                if not math.isfinite(weight):
                    raise ValueError("Nonfinite prompt weight")
                group = {"start": match.start(), "number_end": match.end("weight"),
                         "weight": weight, "end": None, "tokens": []}
                self.groups.append(group)
                stack.append(group)
            elif match.group("close") and stack:
                stack.pop()["end"] = match.end()
            cursor = match.end()
        token(cursor, len(self.text))
        self.open_groups = stack

    def find(self, tag):
        return [t for t in self.tokens if t["tag"] == _tag(tag)]

    def replace(self, fields, start, end, text):
        for name, (a, b) in self.ranges.items():
            if a <= start <= end <= b:
                fields[name] = fields[name][:start-a] + text + fields[name][end-a:]
                return
        raise ValueError("Cannot edit a token split across prompt fields")

    def remove(self, fields, token):
        start, end = token["start"], token["end"]
        a, b = self.ranges[token["field"]]
        # Consume just one adjacent comma; never remove a weight delimiter.
        right = re.match(r"\s*,\s*", self.text[end:b])
        left = re.search(r",\s*$", self.text[a:start])
        if right:
            end += right.end()
        elif left:
            start = a + left.start()
        self.replace(fields, start, end, "")


def _append(fields, target, text):
    parsed = _Prompt(fields, target == "negative_prompt")
    # Appended tags must not inherit an unterminated group, including cross-field groups.
    suffix = " ::" * len(parsed.open_groups)
    fields[target] = fields[target].rstrip() + suffix
    separator = " " if fields[target].rstrip().endswith(",") else ", "
    fields[target] += (separator if fields[target].strip() else "") + text


def _set_weight(fields, target, tag, weight):
    negative = target == "negative_prompt"
    parsed = _Prompt(fields, negative)
    matches = parsed.find(tag)
    if not matches:
        _append(fields, target, f"{weight:g}::{tag} ::")
        return
    # Work right to left, reparsing after each edit to keep offsets valid.
    for index in range(len(matches)-1, -1, -1):
        parsed = _Prompt(fields, negative)
        item = parsed.find(tag)[index]
        if item["weight"] == weight:
            continue
        groups = item["groups"]
        if not groups:
            parsed.replace(fields, item["start"], item["end"], f"{weight:g}::{tag} ::")
        elif len(groups) == 1 and len(groups[0]["tokens"]) == 1:
            group = groups[0]
            parsed.replace(fields, group["start"], group["number_end"], f"{weight:g}")
        else:
            parsed.remove(fields, item)
            _append(fields, target, f"{weight:g}::{tag} ::")


def _warnings(fields):
    warnings = []
    for negative in (False, True):
        parsed = _Prompt(fields, negative)
        for group in parsed.groups:
            if group["weight"] == 0 or (negative and group["weight"] < 0):
                field = next(name for name, (a, b) in parsed.ranges.items() if a <= group["start"] < b)
                warnings.append({"code": "zero_weight" if group["weight"] == 0 else "negative_weight",
                    "field": field, "weight": group["weight"], "tags": [t["tag"] for t in group["tokens"]],
                    "message": "가중치 0은 태그를 뺀 것과 같지 않다" if group["weight"] == 0 else "네거티브의 음수 가중치는 거꾸로 작동한다"})
    return warnings


def _action_status(actions, fields, target):
    pending, present, total, satisfied = [], 0, 0, 0
    for action in actions:
        parsed = _Prompt(fields, action["field"] == "negative_prompt")
        for tag in action["tags"]:
            matches = parsed.find(tag)
            total += 1
            present += bool(matches)
            weight = action.get("weight")
            if weight is None:
                done = bool(matches) and all(t["weight"] > 0 for t in matches)
            else:
                done = bool(matches) and all(t["weight"] >= weight if weight > 0 else t["weight"] <= weight for t in matches)
            satisfied += done
            if not done:
                pending.append({**deepcopy(action), "tags": [tag],
                    "field": matches[0]["field"] if matches else "negative_prompt" if action["field"] == "negative_prompt" else target,
                    "from_weight": matches[0]["weight"] if matches else None})
    state = "already_applied" if satisfied == total else "partly_applied" if present else "new"
    return pending, state


def advise(positions, fields):
    target = "post_prompt" if isinstance(fields, dict) and "post_prompt" in fields else "prompt"
    fields = normalize_fields(fields)
    indexed = {p["id"]: p for p in positions}
    suggestions = []
    for rule in RULES:
        position = indexed.get(rule["axis"])
        if not position or position.get("side") != rule["side"] or position.get("distance") is None:
            continue
        suggestion = deepcopy(rule)
        suggestion["distance"] = position["distance"]
        suggestion["prominent"] = abs(position["distance"]) >= 1
        suggestion["actions"], suggestion["state"] = _action_status(rule["actions"], fields, target)
        for level in suggestion["levels"]:
            level["actions"], level["state"] = _action_status(level["actions"], fields, target)
        suggestions.append(suggestion)
    return {"suggestions": suggestions, "warnings": _warnings(fields)}


def apply_suggestion(fields, suggestion_id, level=None, strength=1.0):
    target = "post_prompt" if isinstance(fields, dict) and "post_prompt" in fields else "prompt"
    before = normalize_fields(fields)
    fields = dict(before)
    rule = next((r for r in RULES if r["id"] == suggestion_id), None)
    if rule is None:
        raise ValueError("Unknown suggestion_id")
    actions = rule["actions"]
    if level not in (None, "default"):
        choice = next((v for v in rule["levels"] if v["id"] == level), None)
        if choice is None:
            raise ValueError("Unknown suggestion level")
        actions = choice["actions"]
    actions = scaled_actions(actions, strength)
    # Repair negative weights even when they are unrelated to the chosen rule.
    parsed = _Prompt(fields, True)
    for group in reversed(parsed.groups):
        if group["weight"] < 0:
            parsed.replace(fields, group["start"], group["number_end"], f"{abs(group['weight']):g}")
    for action in actions:
        destination = "negative_prompt" if action["field"] == "negative_prompt" else target
        tags = action["tags"]
        parsed = _Prompt(fields, destination == "negative_prompt")
        if action["op"] == "set_weight" and all(not parsed.find(tag) for tag in tags):
            _append(fields, destination, f"{action['weight']:g}::{', '.join(tags)} ::")
        else:
            for tag in tags:
                if action["op"] == "set_weight":
                    _set_weight(fields, destination, tag, action["weight"])
                else:
                    matches = _Prompt(fields, destination == "negative_prompt").find(tag)
                    if not matches:
                        _append(fields, destination, tag)
                    elif any(t["weight"] <= 0 for t in matches):
                        _set_weight(fields, destination, tag, 1)
    return {"fields": fields, "changes": [{"field": name, "before": before[name], "after": fields[name]}
                                          for name in FIELDS if before[name] != fields[name]]}


def apply_suggestions(fields, items):
    """여러 보정을 차례로 얹는다(순수 함수). items = [{"suggestion_id", "level", "strength"}] - 같은 보정은 한 번만."""
    before = normalize_fields(fields)
    keys = [name for name in FIELDS if name in fields]
    if not isinstance(items, list) or not items or len(items) > len(RULES):
        raise ValueError(f"items must list one to {len(RULES)} corrections")
    current, seen = dict(before), set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("suggestion_id"), str):
            raise ValueError("each item needs a suggestion_id")
        suggestion_id, level, strength = item["suggestion_id"], item.get("level"), item.get("strength", 1.0)
        if suggestion_id in seen:
            raise ValueError("the same correction is listed twice")
        seen.add(suggestion_id)
        if level is not None and not isinstance(level, str):
            raise ValueError("level must be null or a level id")
        if isinstance(strength, bool) or not isinstance(strength, (int, float)):
            raise ValueError("strength must be a number")
        # 어느 칸에 붙일지는 처음 받은 칸의 구성으로 정한다(중간 결과의 빈 칸이 끼어들지 않게).
        current = apply_suggestion({name: current[name] for name in keys}, suggestion_id, level, float(strength))["fields"]
    return {"fields": current, "changes": [{"field": name, "before": before[name], "after": current[name]}
                                           for name in FIELDS if before[name] != current[name]]}
