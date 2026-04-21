"""RuleEditorWindow 통합 테스트 (Sub-phase 1.4e).

핵심 로직은 다이얼로그 없는 `_perform_*` 메소드로 분리되어 있으므로 직접
호출하여 검증. Qt 다이얼로그 경로는 통합 smoke 만 확인.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from modules.conditional.block_model import (  # noqa: E402
    Action,
    Rule,
    RuleBook,
    make_tag_leaf,
)
from modules.conditional.editor_window import RuleEditorWindow  # noqa: E402
from modules.conditional.preset_io import (  # noqa: E402
    PresetStorage,
    rulebook_to_dict,
)
from modules.conditional_prompt_module import (  # noqa: E402
    PromptListModifierModule,
)
from tests.conditional.test_engine_headless import (  # noqa: E402
    MockAppContext,
)
from tests.conditional.test_mode_toggle import (  # noqa: E402
    _primed_module,
)


@pytest.fixture
def storage(tmp_path) -> PresetStorage:
    return PresetStorage(
        save_dir=tmp_path / "save",
        bundled_dir=tmp_path / "bundled",
    )


@pytest.fixture
def module():
    mod = _primed_module("")
    yield mod
    # no teardown needed (garbage collection)


@pytest.fixture
def window(module, storage):
    w = RuleEditorWindow(
        module.app_context, module, storage=storage
    )
    yield w
    w.deleteLater()


def _sample_book() -> RuleBook:
    return RuleBook(
        rules=[
            Rule(
                kind="block",
                priority=10,
                condition=make_tag_leaf("blush"),
                action=Action(
                    kind="append_list", target="main", tags=["smile"]
                ),
            ),
            Rule(
                kind="block",
                priority=20,
                condition=make_tag_leaf("nsfw"),
                action=Action(
                    kind="append_list", target="neg", tags=["bad"]
                ),
            ),
        ],
        max_passes=3,
        stop_on_match=True,
    )


# ============================================================================
# 초기 로드
# ============================================================================


class TestInitialLoad:
    def test_empty_module_dsl_produces_empty_book(self, window):
        assert len(window._book.rules) == 0
        assert window._current_rule_id is None

    def test_parses_module_dsl(self, module, storage):
        module.rules_textedit.setText(
            "(blush):main+=smile,\n(nsfw):prefix+=quality"
        )
        w = RuleEditorWindow(module.app_context, module, storage=storage)
        assert len(w._book.rules) == 2
        texts = [r.condition.tag_value for r in w._book.rules]
        assert "blush" in texts
        assert "nsfw" in texts
        w.deleteLater()

    def test_inherits_engine_options_from_module(self, module, storage):
        module.set_engine_options(max_passes=5, stop_on_match=True)
        w = RuleEditorWindow(module.app_context, module, storage=storage)
        assert w._book.max_passes == 5
        assert w._book.stop_on_match is True
        w.deleteLater()


# ============================================================================
# Rule CRUD
# ============================================================================


class TestRuleCrud:
    def test_rule_selected_populates_panel(self, window):
        window._book = _sample_book()
        window._preset_panel.set_rulebook(window._book)
        window._on_rule_selected(0)
        assert window._current_rule_id == window._book.rules[0].id
        shown = window._rule_panel.get_rule()
        assert shown.condition.tag_value == "blush"

    def test_rule_panel_edit_relays_to_book(self, window):
        window._book = _sample_book()
        window._preset_panel.set_rulebook(window._book)
        window._on_rule_selected(0)
        # Rule 편집: action.tags 추가
        window._rule_panel._tags_chip.add_tag("happy")
        # 편집 후 book 에 반영
        target_rule = next(
            r for r in window._book.rules
            if r.id == window._current_rule_id
        )
        assert "happy" in (target_rule.action.tags or [])

    def test_priority_change_triggers_resort(self, window):
        window._book = _sample_book()
        window._preset_panel.set_rulebook(window._book)
        # 첫 rule 선택 후 priority 를 30 으로 높임 → 두 번째보다 뒤로
        window._on_rule_selected(0)
        window._rule_panel._priority_spin.setValue(30)
        # book 재정렬
        assert window._book.rules[0].priority <= window._book.rules[1].priority

    def test_rule_add(self, window):
        window._book = _sample_book()
        window._preset_panel.set_rulebook(window._book)
        before = len(window._book.rules)
        window._on_rule_add()
        assert len(window._book.rules) == before + 1
        # priority 는 기존 max + 10
        assert window._book.rules[-1].priority >= 30

    def test_rule_delete(self, window):
        window._book = _sample_book()
        window._preset_panel.set_rulebook(window._book)
        window._on_rule_selected(0)
        # delete idx=0
        window._on_rule_delete(0)
        assert len(window._book.rules) == 1
        assert window._current_rule_id is None

    def test_engine_options_sync_to_book(self, window):
        window._on_engine_options_changed(
            {"max_passes": 7, "stop_on_match": True}
        )
        assert window._book.max_passes == 7
        assert window._book.stop_on_match is True


# ============================================================================
# 프리셋 로드/저장/삭제
# ============================================================================


class TestPresetOperations:
    def test_preset_load_replaces_book(self, window, storage):
        book = _sample_book()
        storage.save("mypre", book)
        window._refresh_preset_list()
        assert window._perform_load("mypre") is True
        assert len(window._book.rules) == 2
        assert window._active_preset_name == "mypre"
        assert window._book.max_passes == 3

    def test_preset_load_missing(self, window):
        assert window._perform_load("does_not_exist") is False
        assert window._active_preset_name is None

    def test_perform_save_creates_file(self, window, storage):
        window._book = _sample_book()
        ok, err = window._perform_save("saved_test")
        assert ok, err
        assert window._active_preset_name == "saved_test"
        # 리스트 갱신
        loaded = storage.load("saved_test")
        assert len(loaded.rules) == 2

    def test_perform_save_rejects_empty_name(self, window):
        window._book = _sample_book()
        ok, err = window._perform_save("")
        assert ok is False
        assert err is not None

    def test_perform_delete(self, window, storage):
        window._book = _sample_book()
        window._perform_save("to_delete")
        assert storage.exists("to_delete", include_bundled=False)

        ok = window._perform_delete("to_delete")
        assert ok is True
        assert not storage.exists("to_delete", include_bundled=False)
        assert window._active_preset_name is None

    def test_perform_delete_missing(self, window):
        ok = window._perform_delete("never_existed")
        assert ok is False


# ============================================================================
# Apply
# ============================================================================


class TestApply:
    def test_perform_apply_injects_dsl(self, window, module):
        window._book = _sample_book()
        ok = window._perform_apply()
        assert ok is True
        assert "blush" in module.rules_textedit.toPlainText()
        assert "nsfw" in module.rules_textedit.toPlainText()

    def test_perform_apply_sets_engine_options(self, window, module):
        window._book = _sample_book()
        window._perform_apply()
        opts = module.get_engine_options()
        assert opts["max_passes"] == 3
        assert opts["stop_on_match"] is True

    def test_perform_apply_sets_v2_mode(self, window, module):
        window._book = _sample_book()
        window._perform_apply()
        assert module.get_editor_mode() == "v2"

    def test_perform_apply_preserves_active_preset(
        self, window, module, storage
    ):
        storage.save("applied_preset", _sample_book())
        window._on_preset_load("applied_preset")
        window._perform_apply()
        assert module._active_preset_name == "applied_preset"

    def test_perform_apply_no_module(self, storage):
        app_ctx = MockAppContext()
        w = RuleEditorWindow(app_ctx, None, storage=storage)
        ok = w._perform_apply()
        assert ok is False
        w.deleteLater()

    def test_rules_applied_signal_emits(self, window):
        window._book = _sample_book()
        received = []
        window.rules_applied.connect(lambda dsl: received.append(dsl))
        window._perform_apply()
        assert len(received) == 1
        assert "blush" in received[0]


# ============================================================================
# load_current_rules 재진입 (모듈 편집 후 다시 불러오기)
# ============================================================================


class TestReload:
    def test_reload_reflects_module_dsl(self, window, module):
        module.rules_textedit.setText("(a):main+=b")
        window.load_current_rules()
        assert len(window._book.rules) == 1
        assert window._book.rules[0].condition.tag_value == "a"

    def test_reload_with_raw_fallback(self, window, module):
        # existing_tag+= 는 블록 미지원 → raw
        module.rules_textedit.setText("(a):existing_tag+=new")
        window.load_current_rules()
        assert len(window._book.rules) == 1
        assert window._book.rules[0].kind == "raw"


# ============================================================================
# Dirty 가드 (SRS FR-11 / NFR-11)
# ============================================================================


class TestDirtyGuard:
    def test_initial_state_not_dirty(self, window):
        assert window.is_dirty() is False

    def test_rule_add_sets_dirty(self, window):
        window._on_rule_add()
        assert window.is_dirty() is True

    def test_rule_delete_sets_dirty(self, window):
        window._book = _sample_book()
        window._preset_panel.set_rulebook(window._book)
        window._on_rule_delete(0)
        assert window.is_dirty() is True

    def test_engine_options_change_sets_dirty(self, window):
        window._on_engine_options_changed(
            {"max_passes": 5, "stop_on_match": False}
        )
        assert window.is_dirty() is True

    def test_rule_panel_change_sets_dirty(self, window):
        window._book = _sample_book()
        window._preset_panel.set_rulebook(window._book)
        window._on_rule_selected(0)
        # clear dirty (selection 은 dirty 아님)
        window._set_dirty(False)
        window._rule_panel._tags_chip.add_tag("angry")
        assert window.is_dirty() is True

    def test_apply_clears_dirty(self, window, module):
        window._on_rule_add()
        assert window.is_dirty() is True
        window._perform_apply()
        assert window.is_dirty() is False

    def test_perform_load_clears_dirty(self, window, storage):
        storage.save("clear_dirty", _sample_book())
        window._refresh_preset_list()
        window._on_rule_add()
        assert window.is_dirty() is True
        window.set_auto_dirty_choice("discard")
        assert window._perform_load("clear_dirty") is True
        assert window.is_dirty() is False

    def test_reload_with_dirty_cancel(self, window, module):
        window._on_rule_add()
        window.set_auto_dirty_choice("cancel")
        before_count = len(window._book.rules)
        module.rules_textedit.setText("(changed):main+=x")
        window.load_current_rules()
        # 취소 → 변경 유지 (reload 적용 안됨)
        assert len(window._book.rules) == before_count
        assert window.is_dirty() is True

    def test_reload_with_dirty_discard(self, window, module):
        window._on_rule_add()
        assert window.is_dirty() is True
        window.set_auto_dirty_choice("discard")
        module.rules_textedit.setText("(reloaded):main+=y")
        window.load_current_rules()
        # discard 후 reload 됨
        assert len(window._book.rules) == 1
        assert window._book.rules[0].condition.tag_value == "reloaded"
        assert window.is_dirty() is False

    def test_reload_with_dirty_apply(self, window, module):
        window._on_rule_add()
        window.set_auto_dirty_choice("apply")
        # apply 경로: 먼저 _perform_apply 가 실행되어 DSL 이 모듈로 주입되고,
        # 그 뒤 _reload_from_module 이 모듈에서 다시 파싱한다. 즉 현재 book 이
        # 유지되어야 한다 (빈 규칙 1개).
        window.load_current_rules()
        assert window.is_dirty() is False
        assert len(window._book.rules) >= 1

    def test_close_with_dirty_cancel_is_blocked(self, window):
        window._on_rule_add()
        window.set_auto_dirty_choice("cancel")
        # closeEvent 직접 호출 대신 close() 경로 확인
        accepted = window.close()
        # cancel 이면 close 무시 → 창 여전히 존재
        assert accepted is False

    def test_close_with_dirty_discard_proceeds(self, window):
        window._on_rule_add()
        window.set_auto_dirty_choice("discard")
        assert window.close() is True

    def test_preset_load_with_dirty_cancel(self, window, storage):
        storage.save("pcancel", _sample_book())
        window._refresh_preset_list()
        window._book.rules.clear()
        window._on_rule_add()
        window.set_auto_dirty_choice("cancel")
        window._on_preset_load("pcancel")
        assert window._active_preset_name is None
        assert window.is_dirty() is True


# ============================================================================
# 번들 shadow 방지
# ============================================================================


class TestBundleShadow:
    def _write_bundle(self, storage, name):
        # 번들 디렉터리에 직접 파일 생성 → is_bundled=True 로 표시됨
        storage.bundled_dir.mkdir(parents=True, exist_ok=True)
        import json as _json


        path = storage.bundled_dir / f"{name}.json"
        path.write_text(
            _json.dumps(rulebook_to_dict(_sample_book(), name=name)),
            encoding="utf-8",
        )

    def test_perform_save_rejects_bundle_name(
        self, window, storage
    ):
        self._write_bundle(storage, "bundled_rule")
        window._refresh_preset_list()
        ok, err = window._perform_save("bundled_rule")
        assert ok is False
        assert err is not None
        assert "번들" in err

    def test_perform_save_allows_non_bundle_name(
        self, window, storage
    ):
        self._write_bundle(storage, "bundled_rule")
        window._refresh_preset_list()
        window._book = _sample_book()
        ok, err = window._perform_save("my_copy")
        assert ok is True, err

    def test_is_name_bundled_helper(self, window, storage):
        self._write_bundle(storage, "helper_bundle")
        window._refresh_preset_list()
        assert window._preset_panel.is_name_bundled("helper_bundle") is True
        assert window._preset_panel.is_name_bundled("other") is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
