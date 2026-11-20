"""Wire-Flow 테스트 실행기 - 그래프를 한 번 흘려 노드마다 Probe 를 남긴다(사용자 지시 2026-10-31).

⚠️ **테스트 전용**: 생성 파이프라인은 아직 이것을 부르지 않는다. 다음 단계(생성 연결)가 같은 실행기를 쓰므로
    여기서 노드 뜻을 바꾸면 그대로 생성 결과가 바뀐다 - Probe 가 곧 그 시험대다.

뜻(노드 종류 · 포트는 core/wireflow_store.NODE_PORTS 가 계약):
- 상태 = 구역별 태그 목록(prefix · main · postfix · char:1~6 · neg · uc:1~6) + 변수(숫자) + 마지막 뽑기 + 이름 붙은 뽑기.
- 선 = 실행 흐름. 입력 노드가 시작점이다(캔버스 위→아래, 왼→오른 순서). 캐릭터 입력은 그 슬롯이 비어 있으면 시작하지 않는다.
- 조건(Switch, 변수 저장의 '조건')은 조건부 프롬프트와 **같은 문법 · 같은 평가기**(`tag` `*tag` `~tag` `!tag` `&` `|` `char_in`)에
  변수 비교 `%wet >= 1`(`%wet` 만 = 0 이 아님 · `~%wet` = 아님)를 더한다. 섞어 쓸 수 있다(`outdoors & %wet >= 1`).
- Switch = if / elif / else - 위에서부터 **처음 맞는 줄 하나**의 포트(b1 · b2 …)로 나간다. 아무것도 안 맞으면 else.
  빈 줄은 건너뛴다(맞지 않음). 사용자 지시 2026-11-01.
  줄마다 **입력**을 고른다 - 흘러온 프롬프트 또는 변수(이름은 그냥 글자 · 화면은 목록에서 고른다) - 와
  **비교**(일치 · 포함 · 불일치 · 미포함). 나가는 점에 **선이 없는 줄은 꺼진 줄**이라 건너뛴다(사용자 결정).
- 변수 = 숫자(변수 저장) 또는 글(변수 뽑기). 변수 뽑기 = 글칸에서 한 줄을 뽑아 변수에만 담는다(프롬프트는 그대로) ·
  같은 이름의 뽑기(`@이름`)로도 남아 Concat 이 다시 쓸 수 있다.
- 와일드카드 전개도 조건부 동작과 같은 처리기(WildcardProcessor) - 이번 실행 하나 동안만 순차 카운터가 이어진다.
- 고리(loop)는 허용 - 대신 단계 한도(MAX_STEPS)에서 멈추고 그렇게 적는다.
- Concat = 글 · 와일드카드 · `@뽑기이름` 을 전개해 한 구역 앞/뒤에 붙이거나 비우고 넣는다.
- 줄기(stream) = 흐름이 시작된 입력 노드의 구역(메인 프롬프트 -> main · 캐릭터 슬롯 -> char:N).
  **노드는 '넣을 곳' 을 고르지 않는다** - 흘러온 줄기를 읽고 고친다(사용자 결정 2026-10-31 · 11-01 모든 노드).
  Switch · 태그는 그 줄기를 보고(메인 줄기 = 앞 · 메인 · 뒤), 네거티브는 그 줄기의 짝(메인 -> neg · 캐릭터 N -> uc:N)에 넣는다.
  옛 저장본의 target · scope 값은 남아 있어도 읽지 않는다.
- 인스턴트 와일드카드 = 노드 안 글칸(워크플로우와 함께 저장 · 와일드카드 폴더엔 파일 없음)에서 한 줄.
  줄 문법은 와일드카드 파일과 같다(`#` 주석 · `30:줄` 가중치 · 줄 안의 `__x__` `<a|b>` 도 전개).
- Final Prompt = 끝 노드. 지금 PE 의 선행/후행 고정을 붙여 **메인 프롬프트를 대치**한다(사용자 결정 2026-10-31).
  ⚠️ 생성 연결 때 계약: Final 이 닿은 실행이면 PE 훅은 선행/후행을 **붙이지 않는다**(두 번 붙음) -
     결과의 `final.replaces_main` 이 그 표식이다. Final 이 없으면 지금처럼 PE 가 붙인다.
"""
from __future__ import annotations

import operator
import random
import re
from typing import Any

from core.conditional.expr_utils import split_by_operator, strip_redundant_outer_parens
from core.conditional_tag_split import split_tags_bracket_aware
from core.wireflow_store import NODE_PORTS, clean_graph, switch_row_fields

MAX_STEPS = 200
_VAR_COMPARE = re.compile(r"^%\s*([^\s<>=!]+)\s*(>=|<=|==|!=|>|<|=)\s*(-?\d+(?:\.\d+)?)$")
_NUM_COMPARE = re.compile(r"^(>=|<=|==|!=|>|<|=)\s*(-?\d+(?:\.\d+)?)$")
_VAR_BARE = re.compile(r"^%\s*([^\s<>=!]+)$")
_WEIGHT_PATTERN = re.compile(r"^(\d+):(?!:)(.*)")     # 와일드카드 파일과 같은 가중치(`30:줄` · `0.5::x` 는 아님)
MAX_VISITS_KEPT = 20
SLOTS = range(1, 7)
AREAS = ("prefix", "main", "postfix", *(f"char:{n}" for n in SLOTS), "neg", *(f"uc:{n}" for n in SLOTS))
_COMPARE = {">=": operator.ge, ">": operator.gt, "==": operator.eq, "!=": operator.ne, "<=": operator.le, "<": operator.lt}


def _norm(tag: str) -> str:
    return " ".join(str(tag).strip().lower().replace("_", " ").split())


def split_tags(text: Any) -> list[str]:
    """프롬프트 글 -> 태그. `#` 줄(주석)은 버리고 줄바꿈은 쉼표처럼 본다."""
    if isinstance(text, (list, tuple)):
        text = ", ".join(str(tag) for tag in text)
    lines = [line for line in str(text or "").splitlines() if not line.strip().startswith("#")]
    return [tag.strip() for tag in split_tags_bracket_aware(", ".join(lines)) if tag.strip()]


def instant_lines(text: Any) -> list[tuple[int, str]]:
    """인스턴트 와일드카드 글칸 -> (가중치, 줄). 빈 줄 · `#` 줄은 후보가 아니다."""
    out: list[tuple[int, str]] = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _WEIGHT_PATTERN.match(line)
        weight, body = (int(match.group(1)), match.group(2).strip()) if match else (100, line)
        if body and weight > 0:
            out.append((weight, body))
    return out


def pe_fixed_prompts(app_context: Any) -> tuple[list[str], list[str]]:
    """지금 PE 의 선행/후행 고정 - 생성 때 PE 훅이 읽는 것과 같은 길(이벤트 스트림 동결 · 세션 덮어쓰기 · 저장본).
    `<anchor:ID>` 는 그 그룹의 작가로 바꾼다(PE 훅과 같다). 와일드카드는 부르는 쪽이 전개한다."""
    try:
        from core.artist_anchor import expand_tags as expand_anchor_tags
        from core.prompt_engineering_runtime import PromptEngineeringHeadlessPostHook

        options = PromptEngineeringHeadlessPostHook(app_context)._current_options() or {}
        anchors = options.get("anchor_groups") or {}
        pre = expand_anchor_tags(split_tags(options.get("pre_prompt")), anchors)
        post = expand_anchor_tags(split_tags(options.get("post_prompt")), anchors)
    except Exception:
        return [], []
    return [str(t) for t in pre if str(t).strip()], [str(t) for t in post if str(t).strip()]


class WireFlowTestRun:
    def __init__(self, app_context: Any, graph: Any, test_input: dict[str, Any] | None = None):
        self.app_context = app_context
        self.graph = clean_graph(graph)
        self.nodes = {node["id"]: node for node in self.graph["nodes"]}
        test_input = test_input if isinstance(test_input, dict) else {}
        self.areas: dict[str, list[str]] = {area: [] for area in AREAS}
        self.areas["main"] = split_tags(test_input.get("main"))
        self.areas["neg"] = split_tags(test_input.get("negative"))
        self.vars: dict[str, float] = {}
        self.last_roll: list[str] | None = None
        self.captures: dict[str, list[str]] = {}
        self.probes: dict[str, list[dict[str, Any]]] = {}
        self.visit_counts: dict[str, int] = {}
        self.steps = 0
        self.notes: list[str] = []
        self.final: dict[str, Any] | None = None     # Final Prompt 가 붙인 PE 선행/후행
        self.stream = "main"                         # 지금 흐르는 줄기 - 시작한 입력 노드의 구역
        self.out_edges: dict[tuple[str, str], list[str]] = {}
        for edge in self.graph["edges"]:
            self.out_edges.setdefault((edge["from"]["node"], edge["from"]["port"]), []).append(edge["to"]["node"])
        self._engine = None
        self._prompt_context = None
        characters = test_input.get("characters")
        if not isinstance(characters, list):
            characters = self._current_characters()
        for n, text in zip(SLOTS, characters):
            self.areas[f"char:{n}"] = split_tags(text)

    def _current_characters(self) -> list[str]:
        """테스트 입력에 캐릭터가 없으면 지금 캐릭터 설정에서 - 켜진 슬롯만(끈 · 음소거 슬롯은 빈 칸)."""
        engine = self._cond_engine()
        try:
            frames = engine._character_frames()
        except Exception:
            return []
        out: list[str] = []
        for index, frame in enumerate(frames[:len(SLOTS)]):
            active = isinstance(frame, dict) and engine._character_active(index)
            out.append(str(frame.get("prompt") or "") if active else "")
        return out

    # ── 빌려 쓰는 것(조건부와 같은 평가기 · 처리기) ───────────────────────────
    def _cond_engine(self):
        if self._engine is None:
            from core.conditional_prompt_runtime import HeadlessConditionalRuleEngine

            self._engine = HeadlessConditionalRuleEngine(self.app_context)
        return self._engine

    def _context(self):
        """조건 평가 · 와일드카드 전개에 쓰는 PromptContext - 실행 하나 동안 하나(순차 카운터가 이어진다)."""
        if self._prompt_context is None:
            import pandas as pd
            from core.prompt_context import PromptContext

            self._prompt_context = PromptContext(source_row=pd.Series(dtype=object), settings={})
        ctx = self._prompt_context
        ctx.prefix_tags = list(self.areas["prefix"])
        ctx.main_tags = list(self.areas["main"])
        ctx.postfix_tags = list(self.areas["postfix"])
        ctx.metadata["_conditional_character_slots"] = [
            {"prompt": ", ".join(self.areas[f"char:{n}"]), "uc": ", ".join(self.areas[f"uc:{n}"]),
             "active": bool(self.areas[f"char:{n}"])} for n in SLOTS]
        return ctx

    def _wildcard_manager(self):
        manager = getattr(self.app_context, "wildcard_manager", None)
        if manager is None:
            try:
                from core.wildcard_runtime import ensure_wildcard_manager

                ensure_wildcard_manager(self.app_context)
            except Exception:
                return None
            manager = getattr(self.app_context, "wildcard_manager", None)
        return manager

    def _expand(self, tags: list[str]) -> list[str]:
        """`__x__` · `<a|b>` · `$x` 를 전개한다. 없으면 그대로."""
        if not any(("__" in tag) or ("<" in tag) or tag.lstrip().startswith("$") for tag in tags):
            return list(tags)
        manager = self._wildcard_manager()
        if manager is None:
            return list(tags)
        from core.wildcard_processor import WildcardProcessor

        ctx = self._context()
        ctx.global_append_tags = []
        try:
            expanded = WildcardProcessor(manager).expand_tags(list(tags), ctx)
        except Exception:
            return list(tags)
        out: list[str] = []
        for item in [*expanded, *ctx.global_append_tags]:
            out.extend(split_tags(item))
        ctx.global_append_tags = []
        return out

    def _matches(self, condition: str, tags: list[str]) -> bool:
        engine = self._cond_engine()
        scope: list[str] = []
        for tag in tags:
            engine._append_condition_tag_value(scope, tag)
        return bool(engine._evaluate_logical_expression(condition, scope, self._context()))

    def _neg_area(self) -> str:
        """줄기의 네거티브 짝 - 메인 -> 메인 네거티브 · 캐릭터 N -> 그 캐릭터 UC."""
        return f"uc:{self.stream[5:]}" if self.stream.startswith("char:") else "neg"

    def _condition(self, expr: str, tags: list[str]) -> bool:
        """태그 조건(조건부 프롬프트 평가기) + `%변수` 비교. `%` 가 없으면 평가기에 그대로 맡긴다."""
        expr = strip_redundant_outer_parens(str(expr or "").strip())
        if "%" not in expr:
            return self._matches(expr, tags)
        for op, join in (("|", any), ("&", all)):
            parts = split_by_operator(expr, op)
            if len(parts) > 1:
                return join(self._condition(part, tags) for part in parts)
        if expr[:1] in "~!":
            return not self._condition(expr[1:], tags)
        if expr.startswith("%"):
            return self._var_compare(expr)
        return self._matches(expr, tags)          # 태그 글자 안의 % - 평가기 몫

    def _var_compare(self, expr: str) -> bool:
        match = _VAR_COMPARE.match(expr)
        if match:
            name, op, value = match.groups()
            have = self.vars.get(name, 0)
            if not isinstance(have, (int, float)):
                return op == "!="                    # 글 변수와 숫자 비교 - 같을 수 없다
            return _COMPARE.get("==" if op == "=" else op, operator.eq)(have, float(value))
        match = _VAR_BARE.match(expr)
        return bool(match) and self.vars.get(match.group(1), 0) != 0

    def _row_hit(self, cond: str, subject: str, mode: str, tags: list[str]) -> bool:
        """Switch 한 줄. 불일치 · 미포함 = 일치 · 포함의 반대."""
        negate = mode in ("ne", "nothas")
        exact = mode in ("eq", "ne")
        if not subject:
            hit = self._condition(_exactify(cond) if exact else cond, tags)
            return hit != negate
        value = self.vars.get(subject)
        number = _NUM_COMPARE.match(cond.strip())
        if number and isinstance(value, (int, float)):
            op, limit = number.groups()
            hit = _COMPARE.get("==" if op == "=" else op, operator.eq)(value, float(limit))
            return hit != negate
        if value is None:
            return negate                              # 아직 없는 변수 - 일치 · 포함은 아니다
        text = _norm(_fmt(value))
        alts = [_norm(alt) for alt in split_by_operator(cond, "|") if _norm(alt)]
        hit = (text in alts) if exact else any(alt in text for alt in alts)
        return hit != negate

    def _scope_tags(self, stream: str) -> list[str]:
        """조건이 보는 태그 - 캐릭터 줄기는 그 슬롯, 메인 줄기는 앞 · 메인 · 뒤."""
        if stream.startswith("char:"):
            return list(self.areas.get(stream, []))
        return [*self.areas["prefix"], *self.areas["main"], *self.areas["postfix"]]

    # ── 상태 고치기 ───────────────────────────────────────────────────────
    def _add(self, area: str, tags: list[str]) -> None:
        if area not in self.areas:
            return
        have = {_norm(tag) for tag in self.areas[area]}
        for tag in tags:
            if _norm(tag) not in have:
                self.areas[area].append(tag)
                have.add(_norm(tag))

    def _add_front(self, area: str, tags: list[str]) -> None:
        """앞에 붙인다 - 이미 있는 태그는 제자리에 둔다(겹쳐 넣지 않는다)."""
        have = {_norm(tag) for tag in self.areas[area]}
        front: list[str] = []
        for tag in tags:
            if _norm(tag) not in have:
                front.append(tag)
                have.add(_norm(tag))
        self.areas[area] = front + self.areas[area]

    def _concat_source(self, text: Any) -> tuple[list[str], list[str]]:
        """Concat 의 '무엇을' -> (태그, 못 찾은 것). `@이름` = 앞에서 이름 붙인 뽑기."""
        tags: list[str] = []
        missing: list[str] = []
        for tag in split_tags(text):
            if tag.startswith("@"):
                name = tag[1:].strip()
                if name in self.captures:
                    tags.extend(self.captures[name])
                else:
                    missing.append(tag)
                continue
            tags.append(tag)
        expanded = self._expand(tags)
        missing.extend(tag for tag in expanded if "__" in tag)      # 전개되지 않은 와일드카드
        return [tag for tag in expanded if "__" not in tag], missing

    def _snapshot(self) -> dict[str, Any]:
        return {"areas": {area: list(tags) for area, tags in self.areas.items()}, "vars": dict(self.vars)}

    @staticmethod
    def _diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        changes: dict[str, Any] = {}
        for area in AREAS:
            old, new = before["areas"][area], after["areas"][area]
            if old == new:
                continue
            old_n, new_n = {_norm(t) for t in old}, {_norm(t) for t in new}
            changes[area] = {"added": [t for t in new if _norm(t) not in old_n],
                             "removed": [t for t in old if _norm(t) not in new_n]}
        var_changes = {name: [before["vars"].get(name), value] for name, value in after["vars"].items()
                       if before["vars"].get(name) != value}
        return {"areas": changes, "vars": var_changes}

    # ── 노드 ───────────────────────────────────────────────────────────────
    def _run_node(self, node: dict[str, Any]) -> tuple[str | None, str, list[str] | None]:
        """(나갈 포트 | None, 사람이 읽는 메모, 뽑기)."""
        kind, p = node["type"], node["params"]
        if kind == "input_main":
            return "out", f"메인 {len(self.areas['main'])}개", None
        if kind == "input_character":
            slot = f"char:{p.get('slot') or 1}"
            return "out", f"캐릭터 {slot[5:]} · {len(self.areas.get(slot, []))}개", None
        if kind == "switch":
            tags = self._scope_tags(self.stream)
            trail: list[str] = []
            for n, (cond, subject, mode) in enumerate(switch_row_fields(p), 1):
                word, cond = ("if" if n == 1 else "elif"), cond.strip()
                if not cond:
                    trail.append(f"{word} (빈 줄)")
                    continue
                label = f"{subject}({_fmt(self.vars[subject]) if subject in self.vars else '없음'}) " if subject else ""
                label += f"{_MODE_WORD[mode]} {cond}" if subject or mode != "has" else cond   # 프롬프트 · 포함 = 예전 그대로
                if (node["id"], f"b{n}") not in self.out_edges:
                    trail.append(f"{word} {label} (선 없음 · 꺼짐)")
                    continue
                hit = self._row_hit(cond, subject, mode, tags)
                trail.append(f"{word} {label} {'✓' if hit else '✗'}")
                if hit:
                    return f"b{n}", f"{_area_name(self.stream)}: {' · '.join(trail)} → 갈래 {n}", None
            return "else", f"{_area_name(self.stream)}: {' · '.join(trail)} → else", None
        if kind == "wildcard_open":
            text = str(p.get("wildcard") or "").strip()
            if not text:
                return "out", "와일드카드가 비어 있음", None
            if "__" not in text and "<" not in text and not text.startswith("$"):
                text = f"__{text}__"
            roll = self._expand(split_tags(text) or [text])
            note = f"{text} → {', '.join(roll) or '(빈 뽑기)'} · {_area_name(self.stream)}"
            if roll and all("__" in tag for tag in roll):
                note = f"{text} 를 찾지 못했습니다"
                roll = []
            self._add(self.stream, roll)
            self.last_roll = roll
            capture = str(p.get("capture") or "").strip()
            if capture:
                self.captures[capture] = list(roll)
            return "out", note, roll
        if kind == "tag_edit":
            op, area = str(p.get("op") or "add"), self.stream
            tags = self._expand(split_tags(p.get("tags")))
            if not tags:
                return "out", "태그가 비어 있음", None
            if op == "remove":
                drop = {_norm(t) for t in tags}
                before = len(self.areas[area])
                self.areas[area] = [t for t in self.areas[area] if _norm(t) not in drop]
                return "out", f"{before - len(self.areas[area])}개 뺌", None
            if op == "replace":
                swap = self._expand(split_tags(p.get("with")))
                find = {_norm(t) for t in tags}
                out: list[str] = []
                hits = 0
                for tag in self.areas[area]:
                    if _norm(tag) not in find:
                        out.append(tag)
                        continue
                    hits += 1
                    for new in swap:            # 바꿀 태그가 이미 있으면 겹쳐 넣지 않는다
                        if _norm(new) not in {_norm(x) for x in out}:
                            out.append(new)
                self.areas[area] = out
                return "out", (f"{hits}개 바꿈" if hits else "바꿀 태그를 찾지 못함"), None
            self._add(area, tags)
            return "out", f"{_area_name(area)} += {', '.join(tags)}", None
        if kind == "var_set":
            name = str(p.get("var") or "").strip()
            if not name:
                return "out", "변수 이름이 비어 있음", None
            when = str(p.get("when") or "").strip()
            if when:
                pool = self.last_roll if self.last_roll is not None else self._scope_tags(self.stream)
                if not self._condition(when, pool):
                    return "out", f"조건 {when} 아님 - 그대로", None
            value = float(p.get("value") or 0)
            if str(p.get("op") or "set") == "add":
                have = self.vars.get(name, 0)
                self.vars[name] = (have if isinstance(have, (int, float)) else 0) + value   # 글 변수엔 더할 수 없다 - 0 부터
            else:
                self.vars[name] = value
            return "out", f"%{name} = {_fmt(self.vars[name])}", None
        if kind in ("output_prompt", "output_negative"):
            area = self.stream if kind == "output_prompt" else self._neg_area()
            tags = self._expand(split_tags(p.get("tags")))
            if not tags:
                return "out", "태그가 비어 있음", None
            self._add(area, tags)
            return "out", f"{_area_name(area)} += {', '.join(tags)}", None
        if kind == "concat":
            area, pos = self.stream, str(p.get("pos") or "back")
            tags, missing = self._concat_source(p.get("source"))
            lack = f" · 못 찾음: {', '.join(missing)}" if missing else ""
            if not tags and pos != "replace":
                return "out", f"붙일 것이 비어 있음{lack}", None
            if pos == "replace":
                self.areas[area] = []
                self._add(area, tags)
            elif pos == "front":
                self._add_front(area, tags)
            else:
                self._add(area, tags)
            self.last_roll = tags
            capture = str(p.get("capture") or "").strip()
            if capture:
                self.captures[capture] = list(tags)
            where = f"{_area_name(area)} " + {"front": "앞에", "replace": "비우고"}.get(pos, "뒤에")
            return "out", f"{where} → {', '.join(tags) or '(빈 것)'}{lack}", tags
        if kind == "var_draw":
            name = str(p.get("name") or "").strip()
            if not name:
                return "out", "변수 이름이 비어 있음", None
            lines = instant_lines(p.get("lines"))
            if not lines:
                return "out", "후보가 비어 있음", None
            weights, bodies = zip(*lines)
            tags, missing = self._concat_source(random.choices(bodies, weights=weights, k=1)[0])
            lack = f" · 못 찾음: {', '.join(missing)}" if missing else ""
            self.vars[name] = ", ".join(tags)
            self.captures[name] = list(tags)
            self.last_roll = tags
            return "out", f"{name} = {self.vars[name] or '(빈 값)'} · {len(lines)}줄 중{lack}", tags
        if kind == "instant_wildcard":
            lines = instant_lines(p.get("lines"))
            if not lines:
                return "out", "글칸이 비어 있음", None
            weights, bodies = zip(*lines)
            line = random.choices(bodies, weights=weights, k=1)[0]
            tags, missing = self._concat_source(line)
            lack = f" · 못 찾음: {', '.join(missing)}" if missing else ""
            front = str(p.get("pos") or "back") == "front"
            (self._add_front if front else self._add)(self.stream, tags)
            self.last_roll = tags
            capture = str(p.get("capture") or "").strip()
            if capture:
                self.captures[capture] = list(tags)
            where = f"{_area_name(self.stream)} {'앞에' if front else '뒤에'}"
            return "out", f"{len(lines)}줄 중 → {', '.join(tags) or '(빈 줄)'} · {where}{lack}", tags
        if kind == "final_prompt":
            if self.final is not None:
                return None, "이미 Final Prompt 를 지났습니다 - 이번 것은 건너뜀", None
            pre, post = pe_fixed_prompts(self.app_context)
            pre = self._expand(pre) if str(p.get("pre") or "on") != "off" else []
            post = self._expand(post) if str(p.get("post") or "on") != "off" else []
            prefix = self.areas["prefix"]
            self.areas["prefix"] = []
            self._add("prefix", [*pre, *prefix])        # PE 선행이 맨 앞(PE 훅과 같은 차례)
            self._add("postfix", post)
            self.final = {"node": node["id"], "pre": pre, "post": post}
            return None, f"PE 선행 {len(pre)} · 후행 {len(post)} 붙임 → 메인 프롬프트 대치", None
        return None, "모르는 노드", None

    def _starts(self) -> list[dict[str, Any]]:
        starts = [n for n in self.graph["nodes"] if not NODE_PORTS[n["type"]][0]]
        return sorted(starts, key=lambda n: (n["y"], n["x"]))

    def _record(self, node_id: str, visit: dict[str, Any]) -> None:
        self.visit_counts[node_id] = self.visit_counts.get(node_id, 0) + 1
        rows = self.probes.setdefault(node_id, [])
        if len(rows) < MAX_VISITS_KEPT:
            rows.append(visit)

    def run(self) -> dict[str, Any]:
        out_edges = self.out_edges
        starts = self._starts()
        if not starts:
            self.notes.append("입력 노드가 없어 흐름이 시작되지 않았습니다.")
        stopped = False
        for start in starts:
            if start["type"] == "input_character":
                slot = f"char:{start['params'].get('slot') or 1}"
                if not self.areas.get(slot):
                    self._record(start["id"], {"step": None, "port": None, "skipped": True,
                                               "note": f"캐릭터 {slot[5:]} 이 비어 있어 시작하지 않음"})
                    continue
            self.stream = (f"char:{start['params'].get('slot') or 1}" if start["type"] == "input_character"
                           else "main")
            stack = [start["id"]]
            while stack:
                if self.steps >= MAX_STEPS:
                    stopped = True
                    break
                node = self.nodes[stack.pop()]
                self.steps += 1
                before = self._snapshot()
                try:
                    port, note, roll = self._run_node(node)
                except Exception as exc:     # 한 노드의 실패가 테스트 전체를 죽이지 않게 - Probe 에 적는다
                    port, note, roll = None, f"오류: {exc}", None
                after = self._snapshot()
                self._record(node["id"], {"step": self.steps, "port": port, "note": note, "roll": roll,
                                          "diff": self._diff(before, after), "state": after})
                if port:
                    stack.extend(reversed(out_edges.get((node["id"], port), [])))
            if stopped:
                self.notes.append(f"단계 한도({MAX_STEPS})에서 멈췄습니다 - 고리(loop)가 끝나지 않는지 확인하세요.")
                break
        prompt = [*self.areas["prefix"], *self.areas["main"], *self.areas["postfix"]]
        return {
            "final": {"main": ", ".join(prompt), "negative": ", ".join(self.areas["neg"]),
                      "characters": [", ".join(self.areas[f"char:{n}"]) for n in SLOTS],
                      "character_uc": [", ".join(self.areas[f"uc:{n}"]) for n in SLOTS],
                      "vars": dict(self.vars),
                      "replaces_main": self.final is not None,
                      "pe": {"pre": list(self.final["pre"]), "post": list(self.final["post"])} if self.final else None},
            "probes": self.probes,
            "visits": self.visit_counts,
            "steps": self.steps,
            "stopped": stopped,
            "notes": self.notes,
        }


_MODE_WORD = {"eq": "일치", "has": "포함", "ne": "불일치", "nothas": "미포함"}


def _exactify(expr: str) -> str:
    """'일치' 로 프롬프트를 볼 때 - 접두 없는 잎을 `*잎`(정확히 같은 태그)으로. `~` `!` `*` `%` 잎은 그대로."""
    expr = strip_redundant_outer_parens(str(expr or "").strip())
    for op in ("|", "&"):
        parts = split_by_operator(expr, op)
        if len(parts) > 1:
            return f" {op} ".join(f"({_exactify(part)})" for part in parts)
    if not expr or expr[0] in "*~!%(":
        return expr
    return f"*{expr}"


def _area_name(area: str) -> str:
    if area.startswith("char:"):
        return f"캐릭터 {area[5:]}"
    if area.startswith("uc:"):
        return f"캐릭터 {area[3:]} UC"
    return {"neg": "네거티브", "prefix": "앞", "postfix": "뒤"}.get(area, "메인")


def _fmt(value: Any) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(num)) if num.is_integer() else f"{num:g}"


def run_wireflow_test(app_context: Any, graph: Any, test_input: dict[str, Any] | None = None) -> dict[str, Any]:
    return WireFlowTestRun(app_context, graph, test_input).run()
