"""DSL → Block 역파싱 테스트 (Sub-phase 1.3).

검증 범위:
1. Leaf 조건 파싱 (tag/rating/char_in/char_on + 접두사)
2. 그룹 조건 파싱 (AND/OR/중첩/우선순위)
3. 액션 파싱 (append_list/append/replace/char_set/char_replace)
4. 규칙 레벨 파싱 (enabled/disabled/raw fallback)
5. RuleBook 레벨 (여러 규칙, `#` 보존)
6. 직렬화↔역파싱 왕복 (AST 안정화, idempotent 확인)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.conditional.block_model import (  # noqa: E402
    Action,
    ConditionNode,
    Rule,
    RuleBook,
)
from modules.conditional.dsl_parser import (  # noqa: E402
    parse_action,
    parse_condition,
    parse_rule,
    parse_rulebook,
)
from modules.conditional.dsl_serializer import (  # noqa: E402
    serialize_action,
    serialize_condition,
    serialize_rule,
    serialize_rulebook,
)


# ============================================================================
# Leaf 조건
# ============================================================================


class TestParseLeafTag:
    def test_contains(self):
        c = parse_condition("blush")
        assert c.kind == "leaf" and c.leaf_kind == "tag"
        assert c.tag_value == "blush"
        assert c.tag_modifier == "contains"
        assert c.negated is False

    def test_exact(self):
        c = parse_condition("*blush")
        assert c.tag_modifier == "exact"
        assert c.tag_value == "blush"

    def test_not_contains(self):
        c = parse_condition("~blush")
        assert c.tag_modifier == "not_contains"
        assert c.tag_value == "blush"

    def test_not_exact(self):
        c = parse_condition("~!blush")
        assert c.tag_modifier == "not_exact"
        assert c.tag_value == "blush"

    def test_tag_with_space(self):
        c = parse_condition("blue hair")
        assert c.tag_value == "blue hair"
        assert c.tag_modifier == "contains"


class TestParseLeafRating:
    def test_legacy_exact(self):
        c = parse_condition("e")
        assert c.leaf_kind == "rating"
        assert c.rating_value == "e"
        assert c.rating_source == "auto"
        assert not c.negated

    def test_legacy_negated(self):
        c = parse_condition("~s")
        assert c.leaf_kind == "rating"
        assert c.rating_value == "s"
        assert c.negated

    def test_func_default_source(self):
        c = parse_condition("rating(q)")
        assert c.rating_value == "q"
        assert c.rating_source == "auto"

    def test_func_override_source(self):
        c = parse_condition("rating(e, source=override)")
        assert c.rating_source == "override"

    def test_func_row_source(self):
        c = parse_condition("rating(g, source=row)")
        assert c.rating_source == "row"

    def test_func_negated(self):
        c = parse_condition("~rating(e, source=override)")
        assert c.negated
        assert c.rating_source == "override"


class TestParseLeafChar:
    def test_char_in_basic(self):
        c = parse_condition("char_in(1, blush)")
        assert c.leaf_kind == "char_in"
        assert c.char_index == 1
        assert c.char_tag_value == "blush"
        assert c.char_tag_modifier == "contains"

    def test_char_in_exact(self):
        c = parse_condition("char_in(2, *blush)")
        assert c.char_index == 2
        assert c.char_tag_modifier == "exact"
        assert c.char_tag_value == "blush"

    def test_char_in_not_contains(self):
        c = parse_condition("char_in(3, ~smile)")
        assert c.char_tag_modifier == "not_contains"

    def test_char_in_negated(self):
        c = parse_condition("~char_in(1, blush)")
        assert c.negated
        assert c.char_index == 1

    def test_char_on(self):
        c = parse_condition("char_on(2)")
        assert c.leaf_kind == "char_on"
        assert c.char_index == 2

    def test_char_on_negated(self):
        c = parse_condition("~char_on(2)")
        assert c.negated


# ============================================================================
# 그룹 조건
# ============================================================================


class TestParseGroup:
    def test_and_flat(self):
        c = parse_condition("a&b")
        assert c.kind == "group" and c.logical == "AND"
        assert len(c.children) == 2
        assert c.children[0].tag_value == "a"
        assert c.children[1].tag_value == "b"

    def test_and_triple(self):
        c = parse_condition("a&b&c")
        assert c.logical == "AND"
        assert len(c.children) == 3

    def test_or_flat(self):
        c = parse_condition("a|b")
        assert c.logical == "OR"
        assert len(c.children) == 2

    def test_precedence_and_over_or(self):
        # a&b|c → (a&b) | c
        c = parse_condition("a&b|c")
        assert c.logical == "OR"
        assert c.children[0].logical == "AND"
        assert c.children[1].leaf_kind == "tag"
        assert c.children[1].tag_value == "c"

    def test_precedence_with_parens(self):
        # (a|b)&c → AND[OR[a,b], c]
        c = parse_condition("(a|b)&c")
        assert c.logical == "AND"
        assert c.children[0].logical == "OR"

    def test_nested_deep(self):
        c = parse_condition("a&(b|(c&d))")
        assert c.logical == "AND"
        right = c.children[1]
        assert right.logical == "OR"
        inner_and = right.children[1]
        assert inner_and.logical == "AND"

    def test_empty(self):
        c = parse_condition("")
        assert c.kind == "group" and not c.children

    def test_single_wrapped(self):
        c = parse_condition("(blush)")
        assert c.kind == "leaf"
        assert c.tag_value == "blush"

    def test_double_wrapped(self):
        c = parse_condition("((blush))")
        assert c.kind == "leaf"
        assert c.tag_value == "blush"


# ============================================================================
# 액션
# ============================================================================


class TestParseActionAppendList:
    def test_main(self):
        a = parse_action("main+=smile")
        assert a.kind == "append_list"
        assert a.target == "main"
        assert a.tags == ["smile"]

    def test_prefix_multiple(self):
        a = parse_action("prefix+=blush^smile^laugh")
        assert a.target == "prefix"
        assert a.tags == ["blush", "smile", "laugh"]

    def test_postfix(self):
        a = parse_action("postfix+=quality")
        assert a.target == "postfix"

    def test_neg(self):
        a = parse_action("neg+=bad_anatomy")
        assert a.target == "neg"

    def test_global_uc(self):
        a = parse_action("global_uc+=low_quality")
        assert a.target == "global_uc"

    def test_char_index_target(self):
        a = parse_action("char:1+=blue_hair")
        assert a.target == "char:1"
        assert a.tags == ["blue_hair"]

    def test_uc_index_target(self):
        a = parse_action("uc:2+=blurry")
        assert a.target == "uc:2"

    def test_char_star_target(self):
        a = parse_action("char:*+=common_tag")
        assert a.target == "char:*"

    def test_legacy_insert_raises(self):
        with pytest.raises(ValueError, match="insert"):
            parse_action("existing_tag+=new_tag")


class TestParseActionAppend:
    def test_target_specified(self):
        a = parse_action("postfix+:quality")
        assert a.kind == "append"
        assert a.target == "postfix"
        assert a.tags == ["quality"]

    def test_target_default_main(self):
        # 고정 타겟 아닌 경우 main 으로 fallback (엔진 호환)
        a = parse_action("+:blush")
        assert a.kind == "append"
        assert a.target == "main"


class TestParseActionReplace:
    def test_simple(self):
        a = parse_action("old_tag=new_tag")
        assert a.kind == "replace"
        assert a.old_tag == "old_tag"
        assert a.new_tags == ["new_tag"]

    def test_pattern_target(self):
        a = parse_action("__color__=red")
        assert a.kind == "replace"
        assert a.old_tag == "__color__"

    def test_multiple_new_tags(self):
        a = parse_action("old=a^b^c")
        assert a.new_tags == ["a", "b", "c"]

    def test_empty_rhs(self):
        a = parse_action("__tag__=")
        assert a.kind == "replace"
        assert a.new_tags == []


class TestParseActionFunc:
    def test_char_set_enabled(self):
        a = parse_action("char_set(2, enabled)")
        assert a.kind == "char_set"
        assert a.char_index == 2
        assert a.char_state == "enabled"

    def test_char_set_disabled(self):
        a = parse_action("char_set(3, disabled)")
        assert a.char_state == "disabled"

    def test_char_set_bad_state(self):
        with pytest.raises(ValueError):
            parse_action("char_set(1, maybe)")

    def test_char_replace(self):
        a = parse_action("char_replace(1, old, new)")
        assert a.kind == "char_replace"
        assert a.char_index == 1
        assert a.char_old_tag == "old"
        assert a.char_new_tag == "new"


# ============================================================================
# 규칙 레벨
# ============================================================================


class TestParseRule:
    def test_basic(self):
        r = parse_rule("(blush):main+=smile")
        assert r.kind == "block"
        assert r.enabled
        assert r.condition.tag_value == "blush"
        assert r.action.kind == "append_list"

    def test_disabled(self):
        r = parse_rule("#(blush):main+=smile")
        assert r.kind == "block"
        assert not r.enabled
        assert r.condition.tag_value == "blush"

    def test_disabled_with_space(self):
        r = parse_rule("# (blush):main+=smile")
        assert r.kind == "block"
        assert not r.enabled

    def test_raw_fallback_syntax_broken(self):
        r = parse_rule("this is garbage")
        assert r.kind == "raw"
        assert r.raw_dsl == "this is garbage"
        assert r.enabled

    def test_raw_fallback_insert_legacy(self):
        # existing_tag+=new 는 블록 모델 미지원 → raw
        r = parse_rule("(a):existing_tag+=new")
        assert r.kind == "raw"
        assert "existing_tag+=new" in r.raw_dsl

    def test_raw_disabled_retains_enabled_flag(self):
        r = parse_rule("#garbage nonsense")
        assert r.kind == "raw"
        assert not r.enabled
        # '#' 는 제거, raw_dsl 은 본문만 (serializer 가 재부착)
        assert r.raw_dsl == "garbage nonsense"

    def test_empty_line(self):
        r = parse_rule("   ")
        assert r.kind == "raw"
        assert r.raw_dsl == ""


# ============================================================================
# RuleBook
# ============================================================================


class TestParseRuleBook:
    def test_empty(self):
        book = parse_rulebook("")
        assert len(book.rules) == 0

    def test_whitespace_only(self):
        book = parse_rulebook("   \n\t\n  ")
        assert len(book.rules) == 0

    def test_single_rule(self):
        book = parse_rulebook("(blush):main+=smile")
        assert len(book.rules) == 1

    def test_multiple_rules(self):
        book = parse_rulebook(
            "(blush):main+=smile,\n(nsfw):prefix+=rating_explicit"
        )
        assert len(book.rules) == 2
        assert book.rules[0].condition.tag_value == "blush"
        assert book.rules[1].action.target == "prefix"

    def test_preserves_disabled(self):
        book = parse_rulebook(
            "(blush):main+=smile,\n#(nsfw):prefix+=x"
        )
        assert len(book.rules) == 2
        assert book.rules[0].enabled
        assert not book.rules[1].enabled

    def test_mixed_block_and_raw(self):
        book = parse_rulebook(
            "(blush):main+=smile,\nthis is garbage,\n(q):postfix+=quality"
        )
        assert len(book.rules) == 3
        assert book.rules[0].kind == "block"
        assert book.rules[1].kind == "raw"
        assert book.rules[2].kind == "block"

    def test_nested_parens_not_split_on_commas(self):
        # char_replace(1, old, new) 내부 쉼표는 규칙 분할하면 안 됨
        book = parse_rulebook("(char_on(1)):char_replace(1, old, new)")
        assert len(book.rules) == 1
        r = book.rules[0]
        assert r.kind == "block"
        assert r.action.kind == "char_replace"
        assert r.action.char_old_tag == "old"


# ============================================================================
# 왕복 (serialize ↔ parse)
# ============================================================================


def _assert_roundtrip_idempotent(dsl: str):
    """한 번 왕복 후 안정화 여부. AST 형태가 idempotent 면 2회차 결과 동일."""
    book1 = parse_rulebook(dsl)
    s1 = serialize_rulebook(book1)
    book2 = parse_rulebook(s1)
    s2 = serialize_rulebook(book2)
    assert s1 == s2, f"왕복 불안정:\n1차: {s1!r}\n2차: {s2!r}"


class TestRoundtrip:
    def test_simple_tag_rule(self):
        _assert_roundtrip_idempotent("(blush):main+=smile")

    def test_exact_tag(self):
        _assert_roundtrip_idempotent("(*blush):main+=smile")

    def test_not_contains(self):
        _assert_roundtrip_idempotent("(~blush):main+=smile")

    def test_not_exact(self):
        _assert_roundtrip_idempotent("(~!blush):main+=smile")

    def test_and_group(self):
        _assert_roundtrip_idempotent("(a&b):prefix+=foo")

    def test_or_group(self):
        _assert_roundtrip_idempotent("(a|b):prefix+=foo")

    def test_nested_precedence(self):
        _assert_roundtrip_idempotent("(a|b&c):main+=foo")

    def test_rating_legacy(self):
        _assert_roundtrip_idempotent("(e):main+=nsfw")

    def test_rating_func(self):
        _assert_roundtrip_idempotent(
            "(rating(q, source=override)):main+=safe_tag"
        )

    def test_char_in(self):
        _assert_roundtrip_idempotent("(char_in(1, blush)):main+=smile")

    def test_char_on(self):
        _assert_roundtrip_idempotent("(char_on(2)):char_set(3, disabled)")

    def test_char_set(self):
        _assert_roundtrip_idempotent("(char_on(1)):char_set(2, disabled)")

    def test_char_replace(self):
        _assert_roundtrip_idempotent(
            "(char_on(1)):char_replace(1, old, new)"
        )

    def test_replace(self):
        _assert_roundtrip_idempotent("(q):__tag__=new")

    def test_disabled_rule(self):
        _assert_roundtrip_idempotent("#(blush):main+=smile")

    def test_multiple_rules(self):
        dsl = (
            "(blush):main+=smile,\n"
            "(q):postfix+=quality,\n"
            "#(nsfw):prefix+=x"
        )
        _assert_roundtrip_idempotent(dsl)

    def test_neg_target(self):
        _assert_roundtrip_idempotent("(*bad):neg+=bad_anatomy")

    def test_char_index_target(self):
        _assert_roundtrip_idempotent("(char_on(1)):char:2+=blue_hair")

    def test_global_uc(self):
        _assert_roundtrip_idempotent("(*low_q):global_uc+=lowres")

    def test_raw_preserves_content(self):
        # insert 액션은 raw 로 가지만, raw 도 원문을 보존해야 함
        dsl = "(a):existing_tag+=new"
        book = parse_rulebook(dsl)
        assert book.rules[0].kind == "raw"
        reserialized = serialize_rulebook(book)
        # raw 는 원문 그대로
        assert "existing_tag+=new" in reserialized


# ============================================================================
# 구조적 왕복 확인 (AST 등가)
# ============================================================================


def _ast_equal(a: ConditionNode, b: ConditionNode) -> bool:
    if a.kind != b.kind:
        return False
    if a.kind == "leaf":
        return (
            a.leaf_kind == b.leaf_kind
            and a.negated == b.negated
            and a.tag_value == b.tag_value
            and a.tag_modifier == b.tag_modifier
            and a.rating_value == b.rating_value
            and a.rating_source == b.rating_source
            and a.char_index == b.char_index
            and a.char_tag_value == b.char_tag_value
            and a.char_tag_modifier == b.char_tag_modifier
        )
    if a.logical != b.logical:
        return False
    if len(a.children) != len(b.children):
        return False
    return all(_ast_equal(x, y) for x, y in zip(a.children, b.children))


class TestSerializeParseAstEquivalence:
    """블록 → DSL → 블록 왕복 시 AST 보존."""

    def test_simple_tag(self):
        orig = ConditionNode(
            kind="leaf",
            leaf_kind="tag",
            tag_value="blush",
            tag_modifier="contains",
        )
        roundtrip = parse_condition(serialize_condition(orig, is_root=True))
        assert _ast_equal(orig, roundtrip)

    def test_and_group(self):
        orig = ConditionNode(
            kind="group",
            logical="AND",
            children=[
                ConditionNode(kind="leaf", leaf_kind="tag", tag_value="a"),
                ConditionNode(kind="leaf", leaf_kind="tag", tag_value="b"),
            ],
        )
        roundtrip = parse_condition(serialize_condition(orig, is_root=True))
        assert _ast_equal(orig, roundtrip)

    def test_nested_and_or(self):
        orig = ConditionNode(
            kind="group",
            logical="AND",
            children=[
                ConditionNode(kind="leaf", leaf_kind="tag", tag_value="a"),
                ConditionNode(
                    kind="group",
                    logical="OR",
                    children=[
                        ConditionNode(
                            kind="leaf", leaf_kind="tag", tag_value="b"
                        ),
                        ConditionNode(
                            kind="leaf", leaf_kind="tag", tag_value="c"
                        ),
                    ],
                ),
            ],
        )
        roundtrip = parse_condition(serialize_condition(orig, is_root=True))
        assert _ast_equal(orig, roundtrip)


# ============================================================================
# 수동 실행
# ============================================================================


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
