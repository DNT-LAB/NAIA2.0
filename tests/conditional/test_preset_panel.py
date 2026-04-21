"""PresetPanel 테스트 (3-pane 재설계 후).

검증:
- set_presets 시 번들/사용자 아이콘 + 툴팁
- 시그널: preset_load_requested / preset_save_requested / preset_delete_requested
- 번들 프리셋 선택 시 삭제 버튼 비활성, 삭제 시그널 억제
- 더블클릭 → 로드 시그널
- is_selected_preset_bundled / is_name_bundled / get_selected_preset_name

규칙 목록 / 엔진 옵션은 RuleListPanel / (제거됨) 으로 분리되어 이 파일에서 다루지 않음.
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

from modules.conditional.preset_io import PresetInfo  # noqa: E402
from modules.conditional.ui.preset_panel import PresetPanel  # noqa: E402


def _pi(name: str, *, bundled: bool = False, rule_count: int = 0):
    return PresetInfo(
        name=name,
        path=Path(f"/tmp/{name}.json"),
        description=f"desc {name}",
        is_bundled=bundled,
        rule_count=rule_count,
    )


class _Spy:
    def __init__(self):
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args if len(args) != 1 else args[0])


# ============================================================================
# 프리셋 리스트
# ============================================================================


class TestPresetList:
    def test_renders_bundled_and_user(self):
        p = PresetPanel()
        p.set_presets(
            [
                _pi("b1", bundled=True, rule_count=3),
                _pi("u1", bundled=False, rule_count=2),
            ]
        )
        assert p._preset_list.count() == 2
        assert "📦" in p._preset_list.item(0).text()
        assert "b1" in p._preset_list.item(0).text()
        assert "📄" in p._preset_list.item(1).text()

    def test_tooltip_from_description(self):
        p = PresetPanel()
        p.set_presets([_pi("x", bundled=False)])
        assert "desc x" in p._preset_list.item(0).toolTip()

    def test_empty(self):
        p = PresetPanel()
        p.set_presets([])
        assert p._preset_list.count() == 0
        assert p.get_selected_preset_name() is None


# ============================================================================
# 시그널
# ============================================================================


class TestPresetSignals:
    def _setup(self):
        p = PresetPanel()
        p.set_presets([
            _pi("bundle", bundled=True),
            _pi("mypreset", bundled=False),
        ])
        return p

    def test_load_by_button(self):
        p = self._setup()
        spy = _Spy()
        p.preset_load_requested.connect(spy)
        p._preset_list.setCurrentRow(1)  # mypreset
        p._on_load_clicked()
        assert spy.calls == ["mypreset"]

    def test_load_by_double_click(self):
        p = self._setup()
        spy = _Spy()
        p.preset_load_requested.connect(spy)
        p._preset_list.setCurrentRow(0)
        p._on_preset_double_clicked(None)
        assert spy.calls == ["bundle"]

    def test_save_emits_selected_name(self):
        p = self._setup()
        spy = _Spy()
        p.preset_save_requested.connect(spy)
        p._preset_list.setCurrentRow(1)
        p._on_save_clicked()
        assert spy.calls == ["mypreset"]

    def test_save_empty_when_no_selection(self):
        p = self._setup()
        spy = _Spy()
        p.preset_save_requested.connect(spy)
        p._preset_list.clearSelection()
        p._preset_list.setCurrentRow(-1)
        p._on_save_clicked()
        # 미선택 → 빈 이름 발행 (상위에서 다이얼로그로 처리)
        assert spy.calls == [""]

    def test_delete_user_preset(self):
        p = self._setup()
        spy = _Spy()
        p.preset_delete_requested.connect(spy)
        p._preset_list.setCurrentRow(1)  # user
        p._on_delete_clicked()
        assert spy.calls == ["mypreset"]

    def test_delete_bundled_ignored(self):
        p = self._setup()
        spy = _Spy()
        p.preset_delete_requested.connect(spy)
        p._preset_list.setCurrentRow(0)  # bundle
        p._on_delete_clicked()
        # 번들은 삭제 시그널 발행 안함 (방어)
        assert spy.calls == []

    def test_delete_button_disabled_for_bundle(self):
        p = self._setup()
        p._preset_list.setCurrentRow(0)
        assert not p._delete_btn.isEnabled()
        p._preset_list.setCurrentRow(1)
        assert p._delete_btn.isEnabled()

    def test_load_button_disabled_without_selection(self):
        p = self._setup()
        p._preset_list.clearSelection()
        p._preset_list.setCurrentRow(-1)
        assert not p._load_btn.isEnabled()


# ============================================================================
# 번들 판별
# ============================================================================


class TestBundleHelpers:
    def test_is_selected_preset_bundled(self):
        p = PresetPanel()
        p.set_presets([_pi("bundle", bundled=True), _pi("user", bundled=False)])
        p._preset_list.setCurrentRow(0)
        assert p.is_selected_preset_bundled() is True
        p._preset_list.setCurrentRow(1)
        assert p.is_selected_preset_bundled() is False

    def test_is_name_bundled(self):
        p = PresetPanel()
        p.set_presets([_pi("bundle", bundled=True), _pi("user", bundled=False)])
        assert p.is_name_bundled("bundle") is True
        assert p.is_name_bundled("user") is False
        assert p.is_name_bundled("nonexistent") is False

    def test_is_name_bundled_empty(self):
        p = PresetPanel()
        p.set_presets([_pi("bundle", bundled=True)])
        assert p.is_name_bundled("") is False
        assert p.is_name_bundled(None) is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
