"""Sub-phase 1.2 — Block 모델 + DSL 직렬화 유닛 테스트.

Qt 의존성 없음 (block_model / dsl_serializer 는 순수 Python).
실행: `python tests/conditional/test_block_serializer.py`

검증 범위:
- Leaf 조건자 (tag / rating / char_in / char_on) + 4종 modifier + negated
- Group 조건 (AND / OR / 중첩) + 괄호 우선순위
- Action (append_list / append / replace / char_set / char_replace)
- Rule (block / raw / enabled / disabled)
- RuleBook priority 정렬
- 엔진 왕복 (serialize → _parse_rules → _apply_rules 실행 가능)
"""

import os
import sys
import traceback

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from modules.conditional.block_model import (  # noqa: E402
    Action, ConditionNode, Rule, RuleBook,
    make_tag_leaf, make_rating_leaf, make_char_in_leaf, make_char_on_leaf,
    make_and_group, make_or_group,
)
from modules.conditional.dsl_serializer import (  # noqa: E402
    serialize_action, serialize_condition, serialize_rule, serialize_rulebook,
)


RESULTS = []


def check(name, actual, expected):
    passed = actual == expected
    RESULTS.append((name, passed, actual, expected))
    indicator = "✅" if passed else "❌"
    print(f"  {indicator} {name}")
    if not passed:
        print(f"     expected: {expected!r}")
        print(f"     actual:   {actual!r}")


def section(title):
    print(f"\n{title}")
    print("-" * len(title))


# ============================================================================
# Condition leaf
# ============================================================================


def test_tag_leaf():
    check("tag contains → 'smile'",
          serialize_condition(make_tag_leaf("smile")),
          "smile")
    check("tag exact → '*smile'",
          serialize_condition(make_tag_leaf("smile", "exact")),
          "*smile")
    check("tag not_contains → '~smile'",
          serialize_condition(make_tag_leaf("smile", "not_contains")),
          "~smile")
    check("tag not_exact → '~!smile'",
          serialize_condition(make_tag_leaf("smile", "not_exact")),
          "~!smile")
    check("tag negated + contains → '~smile'",
          serialize_condition(make_tag_leaf("smile", "contains", negated=True)),
          "~smile")


def test_rating_leaf():
    check("rating(e, auto) 단축형 → 'e'",
          serialize_condition(make_rating_leaf("e", "auto")),
          "e")
    check("rating(e, row) → 'rating(e, source=row)'",
          serialize_condition(make_rating_leaf("e", "row")),
          "rating(e, source=row)")
    check("rating(s, override) → 'rating(s, source=override)'",
          serialize_condition(make_rating_leaf("s", "override")),
          "rating(s, source=override)")
    check("~rating(e, auto) → '~e'",
          serialize_condition(make_rating_leaf("e", "auto", negated=True)),
          "~e")
    check("~rating(q, override) → '~rating(q, source=override)'",
          serialize_condition(make_rating_leaf("q", "override", negated=True)),
          "~rating(q, source=override)")


def test_char_in_leaf():
    check("char_in(1, smile)",
          serialize_condition(make_char_in_leaf(1, "smile")),
          "char_in(1, smile)")
    check("char_in(2, *smile) — 정확 토큰",
          serialize_condition(make_char_in_leaf(2, "smile", "exact")),
          "char_in(2, *smile)")
    check("char_in(1, ~smile) — 서브스트링 부정 (inner modifier)",
          serialize_condition(make_char_in_leaf(1, "smile", "not_contains")),
          "char_in(1, ~smile)")
    check("~char_in(1, smile) — outer negated",
          serialize_condition(make_char_in_leaf(1, "smile", negated=True)),
          "~char_in(1, smile)")


def test_char_on_leaf():
    check("char_on(1)",
          serialize_condition(make_char_on_leaf(1)),
          "char_on(1)")
    check("~char_on(2)",
          serialize_condition(make_char_on_leaf(2, negated=True)),
          "~char_on(2)")


# ============================================================================
# Condition group
# ============================================================================


def test_group_and():
    g = make_and_group(make_tag_leaf("1girl"), make_tag_leaf("smile"))
    check("AND (root) → '1girl&smile'",
          serialize_condition(g, is_root=True),
          "1girl&smile")
    check("AND (nested) → '(1girl&smile)'",
          serialize_condition(g, is_root=False),
          "(1girl&smile)")


def test_group_or():
    g = make_or_group(make_tag_leaf("cat"), make_tag_leaf("dog"))
    check("OR (root) → 'cat|dog'",
          serialize_condition(g, is_root=True),
          "cat|dog")


def test_group_nested_or_in_and():
    or_group = make_or_group(make_tag_leaf("cat"), make_tag_leaf("dog"))
    and_group = make_and_group(or_group, make_tag_leaf("cute"))
    check("(cat|dog)&cute — OR 내부 AND",
          serialize_condition(and_group),
          "(cat|dog)&cute")


def test_group_single_child_unwrap():
    g = make_and_group(make_tag_leaf("solo"))
    check("AND with single child → unwrap to leaf",
          serialize_condition(g),
          "solo")


def test_group_empty():
    g = make_and_group()
    check("빈 AND 그룹 → '' (무조건 매칭)",
          serialize_condition(g),
          "")


# ============================================================================
# Action
# ============================================================================


def test_action_append_list():
    a = Action(kind="append_list", target="prefix", tags=["nsfw", "rating:explicit"])
    check("prefix+=nsfw^rating:explicit",
          serialize_action(a),
          "prefix+=nsfw^rating:explicit")


def test_action_append():
    a = Action(kind="append", target="main", tags=["smile"])
    check("main+:smile",
          serialize_action(a),
          "main+:smile")


def test_action_replace_target_whole():
    a = Action(kind="replace", old_tag="neg", new_tags=["clean", "safe"])
    check("neg=clean^safe — 네거티브 전체 교체",
          serialize_action(a),
          "neg=clean^safe")


def test_action_replace_tag_exact():
    a = Action(kind="replace", old_tag="smile", new_tags=["grin"])
    check("smile=grin — 정확 일치 치환",
          serialize_action(a),
          "smile=grin")


def test_action_replace_pattern():
    a = Action(kind="replace", old_tag="__shirt", new_tags=[])
    check("__shirt= — 패턴 삭제",
          serialize_action(a),
          "__shirt=")


def test_action_char_set():
    a = Action(kind="char_set", char_index=2, char_state="disabled")
    check("char_set(2, disabled)",
          serialize_action(a),
          "char_set(2, disabled)")


def test_action_char_replace():
    a = Action(kind="char_replace", char_index=1,
               char_old_tag="girl", char_new_tag="boy")
    check("char_replace(1, girl, boy)",
          serialize_action(a),
          "char_replace(1, girl, boy)")


# ============================================================================
# Rule
# ============================================================================


def test_rule_enabled_block():
    r = Rule(
        condition=make_rating_leaf("e", "auto"),
        action=Action(kind="append_list", target="prefix", tags=["nsfw"]),
    )
    check("활성 규칙: (e):prefix+=nsfw",
          serialize_rule(r),
          "(e):prefix+=nsfw")


def test_rule_disabled_block():
    r = Rule(
        enabled=False,
        condition=make_tag_leaf("1girl"),
        action=Action(kind="append_list", target="main", tags=["solo"]),
    )
    check("비활성 규칙: #(1girl):main+=solo",
          serialize_rule(r),
          "#(1girl):main+=solo")


def test_rule_raw_enabled():
    r = Rule(kind="raw", raw_dsl="((deep penetration|cowgirl)&~!penis):pussy+=penis")
    check("Raw 규칙 (enabled): 원문 그대로",
          serialize_rule(r),
          "((deep penetration|cowgirl)&~!penis):pussy+=penis")


def test_rule_raw_disabled():
    r = Rule(kind="raw", enabled=False, raw_dsl="(e):main+=x")
    check("Raw 규칙 (disabled): '#' prefix",
          serialize_rule(r),
          "#(e):main+=x")


def test_rule_char_set_action():
    r = Rule(
        condition=make_char_in_leaf(1, "1boy"),
        action=Action(kind="char_set", char_index=2, char_state="disabled"),
    )
    check("조합: (char_in(1, 1boy)):char_set(2, disabled)",
          serialize_rule(r),
          "(char_in(1, 1boy)):char_set(2, disabled)")


# ============================================================================
# RuleBook
# ============================================================================


def test_rulebook_priority_order():
    book = RuleBook(rules=[
        Rule(priority=200,
             condition=make_tag_leaf("b"),
             action=Action(kind="append_list", target="main", tags=["later"])),
        Rule(priority=100,
             condition=make_tag_leaf("a"),
             action=Action(kind="append_list", target="main", tags=["first"])),
    ])
    expected = "(a):main+=first,\n(b):main+=later"
    check("RuleBook priority 오름차순 정렬",
          serialize_rulebook(book),
          expected)


def test_rulebook_mixed_raw_block():
    book = RuleBook(rules=[
        Rule(priority=100,
             condition=make_rating_leaf("e", "auto"),
             action=Action(kind="append_list", target="prefix", tags=["nsfw"])),
        Rule(priority=150, kind="raw",
             raw_dsl="((deep|cowgirl)&~!penis):pussy+=penis"),
        Rule(priority=200, enabled=False,
             condition=make_tag_leaf("disabled"),
             action=Action(kind="append_list", target="main", tags=["x"])),
    ])
    expected = (
        "(e):prefix+=nsfw,\n"
        "((deep|cowgirl)&~!penis):pussy+=penis,\n"
        "#(disabled):main+=x"
    )
    check("RuleBook 혼합 (block + raw + disabled)",
          serialize_rulebook(book),
          expected)


# ============================================================================
# 엔진 왕복 — serializer 결과가 기존 엔진에서 실행 가능한지
# ============================================================================


def test_roundtrip_engine_execution():
    """serialize → _apply_rules 로 실행 → 기대 태그 상태 확인."""
    # Qt 필요 (conditional_prompt_module)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication(sys.argv)
    from modules.conditional_prompt_module import PromptListModifierModule
    from core.prompt_context import PromptContext

    class _Ctx:
        current_source_row = None
        rating_override = None
        main_window = None
        middle_section_controller = None
        def get_api_mode(self): return "NAI"
        def publish(self, *a, **kw): pass
        def subscribe(self, *a, **kw): pass

    mod = PromptListModifierModule()
    mod.app_context = _Ctx()

    # 블록 구성 → DSL → 엔진 실행
    book = RuleBook(rules=[
        Rule(priority=100,
             condition=make_and_group(
                 make_tag_leaf("1girl"),
                 make_tag_leaf("smile"),
             ),
             action=Action(kind="append_list", target="main", tags=["happy"])),
    ])
    dsl = serialize_rulebook(book)

    ctx = PromptContext(
        source_row=None, settings={},
        prefix_tags=[], main_tags=["1girl", "smile"], postfix_tags=[],
    )
    logs = []
    result = mod._apply_rules(ctx, dsl, logs)

    # 기대: happy 가 main 에 추가
    passed = "happy" in result.main_tags
    RESULTS.append(("엔진 왕복: (1girl&smile):main+=happy → 실행 결과",
                    passed, result.main_tags, "main 에 'happy' 포함"))
    print(f"  {'✅' if passed else '❌'} 엔진 왕복: 블록→DSL→엔진 실행 동치")
    if not passed:
        print(f"     DSL: {dsl!r}")
        print(f"     result.main_tags: {result.main_tags}")


def test_roundtrip_complex_nested():
    """((cat|dog)&cute):main+=pet 왕복."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication(sys.argv)
    from modules.conditional_prompt_module import PromptListModifierModule
    from core.prompt_context import PromptContext

    class _Ctx:
        current_source_row = None; rating_override = None
        main_window = None; middle_section_controller = None
        def get_api_mode(self): return "NAI"
        def publish(self, *a, **kw): pass
        def subscribe(self, *a, **kw): pass

    mod = PromptListModifierModule()
    mod.app_context = _Ctx()

    or_grp = make_or_group(make_tag_leaf("cat"), make_tag_leaf("dog"))
    cond = make_and_group(or_grp, make_tag_leaf("cute"))
    book = RuleBook(rules=[
        Rule(condition=cond,
             action=Action(kind="append_list", target="main", tags=["pet"])),
    ])
    dsl = serialize_rulebook(book)

    ctx = PromptContext(
        source_row=None, settings={},
        prefix_tags=[], main_tags=["cat", "cute"], postfix_tags=[],
    )
    logs = []
    result = mod._apply_rules(ctx, dsl, logs)

    passed = "pet" in result.main_tags
    RESULTS.append(("엔진 왕복: 중첩 ((cat|dog)&cute) 실행 동치",
                    passed, result.main_tags, "main 에 'pet' 포함"))
    print(f"  {'✅' if passed else '❌'} 엔진 왕복: 중첩 그룹 실행 동치")
    if not passed:
        print(f"     DSL: {dsl!r}")
        print(f"     result: {result.main_tags}")


# ============================================================================
# 실행
# ============================================================================


def main():
    print("=" * 72)
    print("Conditional Prompt Editor v2.1 — Sub-phase 1.2 Block/Serializer Tests")
    print("=" * 72)

    section("Condition Leaf — Tag")
    run(test_tag_leaf)

    section("Condition Leaf — Rating")
    run(test_rating_leaf)

    section("Condition Leaf — char_in")
    run(test_char_in_leaf)

    section("Condition Leaf — char_on")
    run(test_char_on_leaf)

    section("Condition Group — AND / OR / Nested / 단일child / 빈")
    run(test_group_and)
    run(test_group_or)
    run(test_group_nested_or_in_and)
    run(test_group_single_child_unwrap)
    run(test_group_empty)

    section("Action")
    run(test_action_append_list)
    run(test_action_append)
    run(test_action_replace_target_whole)
    run(test_action_replace_tag_exact)
    run(test_action_replace_pattern)
    run(test_action_char_set)
    run(test_action_char_replace)

    section("Rule")
    run(test_rule_enabled_block)
    run(test_rule_disabled_block)
    run(test_rule_raw_enabled)
    run(test_rule_raw_disabled)
    run(test_rule_char_set_action)

    section("RuleBook")
    run(test_rulebook_priority_order)
    run(test_rulebook_mixed_raw_block)

    section("엔진 왕복 실행 검증")
    run(test_roundtrip_engine_execution)
    run(test_roundtrip_complex_nested)

    print()
    print("=" * 72)
    passed = sum(1 for _, p, _, _ in RESULTS if p)
    failed = sum(1 for _, p, _, _ in RESULTS if not p)
    status = "✅ ALL PASS" if failed == 0 else f"⚠ {failed} FAILED"
    print(f"{status} — {passed}/{len(RESULTS)} PASS")
    print("=" * 72)

    if failed:
        print("\nFAILED:")
        for name, p, actual, expected in RESULTS:
            if not p:
                print(f"  ❌ {name}")
                print(f"     expected: {expected!r}")
                print(f"     actual:   {actual!r}")

    return 0 if failed == 0 else 1


def run(fn):
    try:
        fn()
    except Exception as e:
        RESULTS.append((fn.__name__, False, f"EXCEPTION: {e}", "OK"))
        print(f"  ❌ {fn.__name__}: EXCEPTION")
        traceback.print_exc(limit=3)


if __name__ == "__main__":
    sys.exit(main())
