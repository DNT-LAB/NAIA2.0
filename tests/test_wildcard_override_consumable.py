"""wildcard_override 가 리스트로 주어졌을 때 큐처럼 한 항목씩 소비되는지 검증."""

import weakref

import pandas as pd

from core.prompt_context import PromptContext
from core.wildcard_processor import WildcardProcessor


class _FakeManager:
    def __init__(self, tree, ctx_obj):
        self.wildcard_dict_tree = tree
        self._app_context_ref = weakref.ref(ctx_obj)


class _FakeAppContext:
    def __init__(self):
        self.wildcard_override = {}


def _make_processor(entries_by_key):
    ctx_app = _FakeAppContext()
    # entries_by_key: {"hair": ["red", "blue", "green"]} → [(100, "red"), ...]
    tree = {
        key: [(100, value) for value in values]
        for key, values in entries_by_key.items()
    }
    mgr = _FakeManager(tree, ctx_app)
    return WildcardProcessor(mgr), ctx_app


def _new_context():
    return PromptContext(source_row=pd.Series(dtype=object), settings={})


def test_wildcard_override_list_is_consumed_in_order():
    processor, ctx_app = _make_processor({"hair": ["red", "blue", "green"]})
    ctx_app.wildcard_override["hair"] = ["green", "red"]
    context = _new_context()

    first = processor._get_wildcard_line("hair", context)
    second = processor._get_wildcard_line("hair", context)

    assert first == "green"
    assert second == "red"
    # 큐가 비워졌어야 함
    assert ctx_app.wildcard_override["hair"] == []


def test_wildcard_override_falls_back_to_random_when_list_exhausted():
    processor, ctx_app = _make_processor({"hair": ["red"]})
    # 빈 리스트 → fall through 해서 일반 분기 (이 경우 entries 가 단 1개라 결정적)
    ctx_app.wildcard_override["hair"] = []
    context = _new_context()

    chosen = processor._get_wildcard_line("hair", context)

    assert chosen == "red"


def test_wildcard_override_string_remains_fixed_value():
    """기존 동작: str 형태 오버라이드는 호출마다 같은 값을 반환하고 카운터 동결."""
    processor, ctx_app = _make_processor({"hair": ["red", "blue"]})
    ctx_app.wildcard_override["hair"] = "purple"
    context = _new_context()

    first = processor._get_wildcard_line("hair", context)
    second = processor._get_wildcard_line("hair", context)

    assert first == "purple"
    assert second == "purple"
    # str 오버라이드는 그대로 유지
    assert ctx_app.wildcard_override["hair"] == "purple"
