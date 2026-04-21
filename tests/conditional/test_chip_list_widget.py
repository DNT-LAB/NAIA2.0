"""ChipListWidget 테스트 (Sub-phase 1.4a).

헤드리스(offscreen) 실행. pytest-qt 없이 직접 시그널 연결로 검증.
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

from modules.conditional.ui.chip_list_widget import ChipListWidget  # noqa: E402


class _Recorder:
    """시그널 수신 기록."""

    def __init__(self):
        self.events: list[list[str]] = []

    def __call__(self, tags):
        # Qt 가 list 를 그대로 전달 — 복사본 저장
        self.events.append(list(tags))


@pytest.fixture
def chip():
    w = ChipListWidget()
    yield w
    w.deleteLater()


# ============================================================================
# set_tags / get_tags 왕복
# ============================================================================


class TestSetGet:
    def test_empty(self, chip):
        assert chip.get_tags() == []

    def test_single(self, chip):
        chip.set_tags(["blush"])
        assert chip.get_tags() == ["blush"]

    def test_multiple(self, chip):
        chip.set_tags(["a", "b", "c"])
        assert chip.get_tags() == ["a", "b", "c"]

    def test_ignores_empty_strings(self, chip):
        chip.set_tags(["a", "", "  ", "b"])
        assert chip.get_tags() == ["a", "b"]

    def test_deduplicates(self, chip):
        chip.set_tags(["a", "b", "a", "c", "b"])
        assert chip.get_tags() == ["a", "b", "c"]

    def test_strips_whitespace(self, chip):
        chip.set_tags(["  blush ", "smile"])
        assert chip.get_tags() == ["blush", "smile"]

    def test_rejects_non_str(self, chip):
        chip.set_tags(["a", None, 42, "b"])  # type: ignore[list-item]
        assert chip.get_tags() == ["a", "b"]

    def test_set_tags_returns_copy(self, chip):
        chip.set_tags(["a"])
        tags = chip.get_tags()
        tags.append("b")
        assert chip.get_tags() == ["a"], "get_tags 가 내부 상태 공유하면 안 됨"


# ============================================================================
# add_tag / clear / _remove_at
# ============================================================================


class TestMutations:
    def test_add_new(self, chip):
        ok = chip.add_tag("new")
        assert ok is True
        assert chip.get_tags() == ["new"]

    def test_add_duplicate_rejected(self, chip):
        chip.set_tags(["a"])
        ok = chip.add_tag("a")
        assert ok is False
        assert chip.get_tags() == ["a"]

    def test_add_empty_rejected(self, chip):
        assert chip.add_tag("") is False
        assert chip.add_tag("   ") is False
        assert chip.get_tags() == []

    def test_add_strips(self, chip):
        chip.add_tag("  blush  ")
        assert chip.get_tags() == ["blush"]

    def test_remove_at(self, chip):
        chip.set_tags(["a", "b", "c"])
        chip._remove_at(1)
        assert chip.get_tags() == ["a", "c"]

    def test_remove_at_out_of_range(self, chip):
        chip.set_tags(["a"])
        chip._remove_at(99)  # 무시
        assert chip.get_tags() == ["a"]

    def test_clear(self, chip):
        chip.set_tags(["a", "b"])
        chip.clear()
        assert chip.get_tags() == []


# ============================================================================
# 시그널
# ============================================================================


class TestSignal:
    def test_set_tags_emits(self, chip):
        rec = _Recorder()
        chip.tags_changed.connect(rec)
        chip.set_tags(["x"])
        assert rec.events == [["x"]]

    def test_add_tag_emits_on_accept(self, chip):
        rec = _Recorder()
        chip.tags_changed.connect(rec)
        chip.add_tag("new")
        assert rec.events == [["new"]]

    def test_add_duplicate_does_not_emit(self, chip):
        chip.set_tags(["a"])
        rec = _Recorder()
        chip.tags_changed.connect(rec)
        chip.add_tag("a")  # 중복 → 거부
        assert rec.events == []

    def test_remove_emits(self, chip):
        chip.set_tags(["a", "b"])
        rec = _Recorder()
        chip.tags_changed.connect(rec)
        chip._remove_at(0)
        assert rec.events == [["b"]]

    def test_clear_emits(self, chip):
        chip.set_tags(["a"])
        rec = _Recorder()
        chip.tags_changed.connect(rec)
        chip.clear()
        assert rec.events == [[]]

    def test_clear_noop_when_empty(self, chip):
        rec = _Recorder()
        chip.tags_changed.connect(rec)
        chip.clear()
        assert rec.events == []


# ============================================================================
# chip 레이아웃 렌더 수 (내부 구조 간단 검증)
# ============================================================================


class TestLayout:
    def _chip_count(self, chip) -> int:
        """chip_layout 의 실제 위젯 수 (stretch 제외)."""
        total = chip._chip_layout.count()
        widgets = 0
        for i in range(total):
            item = chip._chip_layout.itemAt(i)
            if item is not None and item.widget() is not None:
                widgets += 1
        return widgets

    def test_rendered_count_matches_tags(self, chip):
        chip.set_tags(["a", "b", "c"])
        assert self._chip_count(chip) == 3

    def test_empty_has_no_chips(self, chip):
        chip.set_tags([])
        assert self._chip_count(chip) == 0

    def test_refresh_after_remove(self, chip):
        chip.set_tags(["a", "b", "c"])
        chip._remove_at(1)
        assert self._chip_count(chip) == 2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
