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
    # 채도 · 밝기의 손잡이는 **네거티브**에 있다(사용자 발견 2026-10-04) - 프롬프트에 넣는 태그는 그림을 다시 뽑는다.
    # 어두운 작가 셋 x 2시드(같은 시드의 짝 6쌍) + v1v404 의 2 x 2 에서 둘이 갈렸다: `grey theme` 은 채도만, 아래 묶음은 밝기를 올린다.
    # `grey theme` 2.5 는 채도를 기준의 네 배 가까이 넘겨서 단계로 두지 않았다(세기는 화면의 약하게 0.5 · 세게 1.5).
    # 옛 묶음(네거티브 monochrome · greyscale · muted color + 프롬프트 0.5::colorful)은 한 시드에서 한꺼번에 본 것이었고,
    # colorful 은 여기에 더해도 거의 안 보탰다(채도 60.1 → 61.8).
    {"id": "chroma_low", "axis": "chroma", "side": "low", "title": "색을 더하기",
     "actions": [{"field": "negative_prompt", "op": "add", "tags": ["grey theme"]}],
     "levels": [], "evidence": {"level": "validated_pairs",
                                "note": "어두운 작가 3 x 2시드, 채도 6/6 상승(중앙 +76%) · 구도 유지 0.90"},
     "cautions": ["장면이 이미 가진 색이 짙어진다(파란 그림은 더 파랗게)", "밝기는 그대로이거나 조금 내려간다"], "verify": [],
     "opposes": [{"field": "prompt", "tags": ["grey theme"], "message": "채도를 내리는 자리에 있다. 색을 더하려면 이것부터 뺀다"}]},
    # 높을 때는 같은 태그를 **프롬프트**에 넣는다. 네거티브에서 색을 빼려던 것(colorful · pink theme)은 다른 원색으로 바뀌거나
    # 더 짙어졌다(milo monzon: +13% · +5%). 프롬프트 쪽인데도 그림이 남는다 - 원색 배경이 회색 쪽으로 바뀌는 방식이다.
    # 다이얼이 아니라 **스위치**처럼 듣는다 - 꺾이는 가중치가 작가마다 다르다: milo monzon 은 0.5 와 1 사이(40.9 → 34.2 → 15.7 → 15.3),
    # sirhoopsalot 은 0.25 와 0.5 사이(28.0 → 25.3 → 6.6 → 5.8, 무채색 근처까지 넘친다). 1.5 는 1 보다 더 내리지 못한다.
    # 기본을 1 로 둔 까닭: 채도가 높던 넉 장에서 1 은 둘을 기준 부근에 놓았고(15.7 · 14.5) 0.5 는 그 둘을 못 내렸다 - 넘치는 둘은 0.5 에서도 넘쳤다.
    {"id": "chroma_high", "axis": "chroma", "side": "high", "title": "색을 덜기",
     "actions": [{"field": "prompt", "op": "add", "tags": ["grey theme"]}],
     "levels": [], "evidence": {"level": "validated_pairs", "note": "작가 3 x 2시드, 채도 6/6 하락(중앙 -64%) · 구도 유지 0.70 - milo monzon 은 기준 부근으로, sirhoopsalot 은 무채색 근처까지"},
     "cautions": ["원색 배경이 회색 쪽으로 바뀐다", "켜지듯 듣는다 — 작가에 따라 약하게(0.5)로는 모자라거나 이미 무채색 가까이 넘친다",
                  "밝기 · 또렷함이 오르는 편이다"],
     "verify": ["lightness", "sharpness"],
     "opposes": [{"field": "negative_prompt", "tags": ["grey theme"], "message": "채도를 올리는 자리에 있다. 색을 덜려면 이것부터 뺀다"}]},
    # 셋 가운데 무엇이 일하는지는 갈라 보지 않았다. 밝은 그림(밝기 69)에서는 안 움직였다 - 낮은 쪽에만 붙인다.
    {"id": "lightness_low", "axis": "lightness", "side": "low", "title": "밝게",
     "actions": [{"field": "negative_prompt", "op": "add", "tags": ["black theme", "dark", "muted color"]}],
     "levels": [], "evidence": {"level": "validated_pairs",
                                "note": "어두운 작가 3 x 2시드, 밝기 6/6 상승(중앙 +13) · 구도 유지 0.76(최저 0.20)"},
     "cautions": ["배경이 밝은 것으로 바뀐다 — 그림이 달라질 수 있다", "채도도 같이 오르는 편이다", "검은 옷의 색이 바뀔 수 있다",
                  "이미 밝은 그림에서는 움직이지 않는다"],
     "verify": ["chroma"]},
    # `ultra complexity` 는 **또렷함**을 올리는 손잡이다(사용자 지적 2026-10-03). 30장 검증에서 고주파 에너지는 10/10 올랐고
    # 선 대비는 9/10 · 중앙 +3.7 로 약했다 - 처음에는 선 대비 축에만 붙여 놓아 또렷함 축이 '보정 없음' 으로 나왔다.
    {"id": "sharpness_low", "axis": "sharpness", "side": "low", "title": "또렷하게",
     "actions": [{"field": "prompt", "op": "set_weight", "tags": ["ultra complexity"], "weight": .5}],
     "levels": [], "evidence": {"level": "validated_30", "note": "5시드 x 2구도, 고주파 에너지 10/10 상승(중앙 +34) · 선 대비 9/10"},
     "cautions": ["그림이 다시 뽑힌다", "거칠기가 는다", "0.5 를 넘겨도 선은 더 안 선다"], "verify": [],
     "opposes": [{"field": "negative_prompt", "tags": ["high contrast"], "message": "또렷함을 내리는 자리에 있다. 또렷하게 하려면 이것부터 뺀다"}]},
    # 높을 때는 네거티브의 `high contrast` - 그림을 유지한 채 무르게 한다. `ultra complexity` 를 음수로 내리던 것(한 시드의 근거)은
    # 그림이 다시 뽑혀서 바꿨다(2026-10-04).
    {"id": "sharpness_high", "axis": "sharpness", "side": "high", "title": "부드럽게",
     "actions": [{"field": "negative_prompt", "op": "add", "tags": ["high contrast"]}],
     "levels": [], "evidence": {"level": "validated_30", "note": "5시드 x 2구도(작가 없음), 또렷함 10/10 하락(중앙 -17%) · 구도 유지 0.93"},
     "cautions": ["명암 대비 · 선 대비도 조금 내려간다"], "verify": ["line_contrast"]},
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
    """축 · 쪽마다 어떤 보정이 있는지(그림과 무관한 안내). 화면의 축 툴팁이 쓴다. 반대 칸 표(opposes)는 싣지 않는다."""
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


def _opposing(opposes, fields):
    """권하는 보정과 반대로 당기는 태그가 **반대 칸**에 이미 있는가. 같은 태그를 낮으면 네거티브에, 높으면 프롬프트에 넣는 규칙에서
    시험 → 반영을 거듭하면 생긴다(넘쳐서 반대쪽 보정이 나왔는데 앞서 넣은 것이 남아 있다). 그 축이 벗어났을 때만 본다."""
    found = []
    for item in opposes:
        parsed = _Prompt(fields, item["field"] == "negative_prompt")
        for tag in item["tags"]:
            for token in parsed.find(tag):
                if token["weight"] > 0:
                    found.append({"code": "opposing_tag", "field": token["field"], "weight": token["weight"], "tags": [tag],
                                  "message": item["message"]})
    return found


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
    suggestions, opposing = [], []
    for rule in RULES:
        position = indexed.get(rule["axis"])
        if not position or position.get("side") != rule["side"] or position.get("distance") is None:
            continue
        suggestion = deepcopy(rule)
        opposing.extend(_opposing(suggestion.pop("opposes", ()), fields))
        suggestion["distance"] = position["distance"]
        suggestion["prominent"] = abs(position["distance"]) >= 1
        suggestion["actions"], suggestion["state"] = _action_status(rule["actions"], fields, target)
        for level in suggestion["levels"]:
            level["actions"], level["state"] = _action_status(level["actions"], fields, target)
        suggestions.append(suggestion)
    return {"suggestions": suggestions, "warnings": _warnings(fields) + opposing}


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
