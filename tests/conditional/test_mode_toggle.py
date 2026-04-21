"""Sub-phase 1.8 — 레거시↔신규 모드 토글 + 프리셋 로드 + 변환 도구.

검증 범위:
- 기본 모드 = legacy (기존 사용자 회귀 방지)
- collect_current_settings / apply_settings 가 editor_mode /
  engine_options / active_preset 필드를 왕복
- 레거시 설정(필드 없음)도 안전하게 흡수 (기본값 fallback)
- `load_preset_by_name` 이 rules_textedit + engine_options + active_preset 갱신
- `convert_legacy_to_preset` 이 현재 DSL 을 파싱/저장하고 통계 반환
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
from modules.conditional.preset_io import PresetStorage  # noqa: E402
from modules.conditional_prompt_module import (  # noqa: E402
    PromptListModifierModule,
)
from tests.conditional.test_engine_headless import (  # noqa: E402
    MockAppContext,
)


# ============================================================================
# 경량 Mock 위젯 — UI 없이 collect/apply 경로 테스트
# ============================================================================


class _FakeCheckbox:
    def __init__(self, v=False):
        self._v = v

    def isChecked(self):
        return self._v

    def setChecked(self, v):
        self._v = bool(v)


class _FakeTextEdit:
    def __init__(self, text=""):
        self._text = text

    def toPlainText(self):
        return self._text

    def setText(self, t):
        self._text = str(t)


def _primed_module(rules_text: str = "") -> PromptListModifierModule:
    mod = PromptListModifierModule()
    mod.app_context = MockAppContext()
    mod.enable_checkbox = _FakeCheckbox(True)
    mod.rules_textedit = _FakeTextEdit(rules_text)
    mod.log_textedit = None
    return mod


# ============================================================================
# 기본값 / 설정 왕복
# ============================================================================


class TestEditorModeDefault:
    def test_default_is_legacy(self):
        mod = _primed_module()
        assert mod.get_editor_mode() == "legacy"

    def test_no_active_preset_initially(self):
        mod = _primed_module()
        assert mod.get_active_preset_name() is None


class TestSettingsRoundtrip:
    def test_collect_includes_new_fields(self):
        mod = _primed_module("(a):main+=b")
        mod.set_editor_mode("v2")
        mod.set_engine_options(max_passes=3, stop_on_match=True)
        mod._active_preset_name = "my_preset"
        mod.set_v2_dsl("(v2rule):main+=v2tag")

        s = mod.collect_current_settings()
        assert s["editor_mode"] == "v2"
        assert s["engine_options"]["max_passes"] == 3
        assert s["engine_options"]["stop_on_match"] is True
        assert s["active_preset"] == "my_preset"
        assert s["rules"] == "(a):main+=b"
        # 174 hotfix: rules_v2 필드 왕복
        assert s["rules_v2"] == "(v2rule):main+=v2tag"

    def test_apply_restores_rules_v2(self):
        """174 hotfix: apply_settings 가 rules_v2 필드를 복원."""
        mod = _primed_module()
        mod.apply_settings(
            {
                "enabled": True,
                "rules": "(legacy):main+=l",
                "rules_v2": "(v2):main+=v",
                "editor_mode": "v2",
            }
        )
        assert mod.get_v2_dsl() == "(v2):main+=v"
        assert mod.rules_textedit.toPlainText() == "(legacy):main+=l"

    def test_apply_without_rules_v2_defaults_empty(self):
        """과거 설정(rules_v2 없음) 은 빈 문자열로 fallback."""
        mod = _primed_module()
        mod.apply_settings({"enabled": True, "rules": "(a):main+=b"})
        assert mod.get_v2_dsl() == ""

    def test_apply_restores_new_fields(self):
        mod = _primed_module()
        mod.apply_settings(
            {
                "enabled": True,
                "rules": "(q):main+=quality",
                "editor_mode": "v2",
                "engine_options": {"max_passes": 4, "stop_on_match": True},
                "active_preset": "loaded_preset",
            }
        )
        assert mod.get_editor_mode() == "v2"
        opts = mod.get_engine_options()
        assert opts["max_passes"] == 4
        assert opts["stop_on_match"] is True
        assert mod.get_active_preset_name() == "loaded_preset"
        assert mod.rules_textedit.toPlainText() == "(q):main+=quality"

    def test_apply_legacy_settings_without_new_fields(self):
        """editor_mode/engine_options 없는 과거 설정도 안전 로드."""
        mod = _primed_module()
        mod.apply_settings({"enabled": True, "rules": "(a):main+=b"})
        assert mod.get_editor_mode() == "legacy"
        assert mod.get_engine_options() == {
            "max_passes": 1,
            "stop_on_match": False,
        }
        assert mod.get_active_preset_name() is None

    def test_apply_invalid_mode_falls_back_to_legacy(self):
        mod = _primed_module()
        mod.apply_settings(
            {"enabled": True, "rules": "", "editor_mode": "nonsense"}
        )
        assert mod.get_editor_mode() == "legacy"

    def test_apply_invalid_engine_options_falls_back(self):
        mod = _primed_module()
        mod.apply_settings(
            {
                "enabled": True,
                "rules": "",
                "engine_options": "not_a_dict",  # 잘못된 타입
            }
        )
        # 이전 값 유지
        assert mod.get_engine_options() == {
            "max_passes": 1,
            "stop_on_match": False,
        }


# ============================================================================
# 프리셋 로드 API
# ============================================================================


@pytest.fixture
def temp_storage(tmp_path) -> PresetStorage:
    return PresetStorage(
        save_dir=tmp_path / "save",
        bundled_dir=tmp_path / "bundled",
    )


class TestLoadPresetByName:
    def test_load_applies_to_module(self, temp_storage):
        book = RuleBook(
            rules=[
                Rule(
                    kind="block",
                    condition=make_tag_leaf("blush"),
                    action=Action(
                        kind="append_list", target="main", tags=["smile"]
                    ),
                ),
            ],
            max_passes=4,
            stop_on_match=True,
        )
        temp_storage.save("mytest", book)

        mod = _primed_module()
        ok = mod.load_preset_by_name("mytest", storage=temp_storage)

        assert ok
        assert mod.get_active_preset_name() == "mytest"
        # engine_options 가 RuleBook 의 값으로 갱신
        opts = mod.get_engine_options()
        assert opts["max_passes"] == 4
        assert opts["stop_on_match"] is True
        # 174 hotfix: v2 저장소에 DSL 주입 + v2 모드 전환
        assert "blush" in mod.get_v2_dsl()
        assert "smile" in mod.get_v2_dsl()
        assert mod.get_editor_mode() == "v2"
        # 레거시 DSL 은 덮어쓰지 않는다
        assert mod.rules_textedit.toPlainText() == ""

    def test_load_missing_returns_false(self, temp_storage):
        mod = _primed_module()
        ok = mod.load_preset_by_name("does_not_exist", storage=temp_storage)
        assert ok is False
        assert mod.get_active_preset_name() is None


# ============================================================================
# 변환 도구 (레거시 DSL → 블록 프리셋)
# ============================================================================


class TestConvertLegacyToPreset:
    def test_convert_basic_dsl(self, temp_storage):
        mod = _primed_module(
            "(blush):main+=smile,\n(q):prefix+=quality"
        )
        result = mod.convert_legacy_to_preset(
            "converted", description="테스트", storage=temp_storage
        )

        assert result["saved"] is True
        assert result["error"] is None
        assert result["total"] == 2
        assert result["block_count"] == 2
        assert result["raw_count"] == 0
        assert result["path"].exists()

    def test_convert_with_raw_fallback(self, temp_storage):
        # existing_tag+= (insert 레거시) 는 블록 모델 미지원 → raw
        mod = _primed_module(
            "(a):main+=b,\n(c):existing_tag+=new"
        )
        result = mod.convert_legacy_to_preset(
            "mixed", storage=temp_storage
        )
        assert result["saved"] is True
        assert result["total"] == 2
        assert result["block_count"] == 1
        assert result["raw_count"] == 1

    def test_convert_empty_dsl_still_saves_empty(self, temp_storage):
        mod = _primed_module("")
        result = mod.convert_legacy_to_preset(
            "empty_preset", storage=temp_storage
        )
        assert result["saved"] is True
        assert result["total"] == 0
        assert result["path"].exists()

    def test_convert_rejects_empty_name(self, temp_storage):
        mod = _primed_module("(a):main+=b")
        result = mod.convert_legacy_to_preset("", storage=temp_storage)
        assert result["saved"] is False
        assert result["error"] is not None

    def test_roundtrip_via_convert_then_load(self, temp_storage):
        mod = _primed_module("(blush):main+=smile")
        save_result = mod.convert_legacy_to_preset(
            "trip", storage=temp_storage
        )
        assert save_result["saved"]

        # 새 모듈에서 로드 (174 hotfix: v2 저장소에 주입)
        mod2 = _primed_module()
        assert mod2.load_preset_by_name("trip", storage=temp_storage)
        assert "blush" in mod2.get_v2_dsl()
        assert "smile" in mod2.get_v2_dsl()
        assert mod2.get_editor_mode() == "v2"


# ============================================================================
# 174 hotfix — 실행 경로 분기 (FR-02 / FR-10 / FR-11b)
# ============================================================================


class TestActiveRulesSource:
    def test_legacy_mode_reads_rules_textedit(self):
        mod = _primed_module("(legacy):main+=a")
        mod.set_v2_dsl("(v2):main+=b")
        mod.set_editor_mode("legacy")
        assert mod._active_rules_text() == "(legacy):main+=a"

    def test_v2_mode_reads_v2_dsl(self):
        mod = _primed_module("(legacy):main+=a")
        mod.set_v2_dsl("(v2):main+=b")
        mod.set_editor_mode("v2")
        assert mod._active_rules_text() == "(v2):main+=b"

    def test_v2_mode_empty_v2_returns_empty(self):
        mod = _primed_module("(legacy):main+=a")
        mod.set_editor_mode("v2")
        # v2 저장소 비어있으면 레거시로 fallback 하지 않는다
        assert mod._active_rules_text() == ""


class TestGetParametersBranches:
    def test_legacy_returns_legacy_rules(self):
        mod = _primed_module("(legacy):main+=a")
        mod.set_v2_dsl("(v2):main+=b")
        params = mod.get_parameters()
        assert params["rules"] == "(legacy):main+=a"

    def test_v2_returns_v2_rules(self):
        mod = _primed_module("(legacy):main+=a")
        mod.set_v2_dsl("(v2):main+=b")
        mod.set_editor_mode("v2")
        params = mod.get_parameters()
        assert params["rules"] == "(v2):main+=b"

    def test_disabled_returns_empty(self):
        mod = _primed_module("(legacy):main+=a")
        mod.set_v2_dsl("(v2):main+=b")
        mod.enable_checkbox.setChecked(False)
        assert mod.get_parameters() == {}


class TestModeRadioUI:
    """실제 create_widget 경로에서 라디오가 _editor_mode 를 조작하는지 검증."""

    def _build_ui_module(self):
        mod = PromptListModifierModule()
        mod.app_context = MockAppContext()
        # 실제 QWidget 경로로 라디오 생성. 부모 QWidget 을 모듈에 부착해
        # Python 가비지 컬렉션으로 라디오가 사라지지 않도록 유지.
        from PyQt6.QtWidgets import QWidget
        mod._test_parent = QWidget()
        mod.create_widget(mod._test_parent)
        return mod

    def test_initial_radio_reflects_legacy(self):
        mod = self._build_ui_module()
        assert mod._mode_legacy_radio.isChecked() is True
        assert mod._mode_v2_radio.isChecked() is False

    def test_v2_radio_toggle_changes_mode(self):
        mod = self._build_ui_module()
        mod._mode_v2_radio.setChecked(True)
        assert mod.get_editor_mode() == "v2"
        assert mod.rules_textedit.isReadOnly() is True

    def test_legacy_radio_toggle_restores_legacy(self):
        mod = self._build_ui_module()
        mod._mode_v2_radio.setChecked(True)
        assert mod.get_editor_mode() == "v2"
        mod._mode_legacy_radio.setChecked(True)
        assert mod.get_editor_mode() == "legacy"
        assert mod.rules_textedit.isReadOnly() is False

    def test_set_editor_mode_syncs_radio(self):
        mod = self._build_ui_module()
        mod.set_editor_mode("v2")
        assert mod._mode_v2_radio.isChecked() is True
        assert mod._mode_legacy_radio.isChecked() is False
        mod.set_editor_mode("legacy")
        assert mod._mode_legacy_radio.isChecked() is True
        assert mod._mode_v2_radio.isChecked() is False


class TestExecutePipelineHookBranch:
    """execute_pipeline_hook 이 _active_rules_text 를 통해 올바른 소스를 사용."""

    def _make_context(self, main_tags):
        import pandas as pd
        from core.prompt_context import PromptContext
        return PromptContext(
            source_row=pd.Series({'rating': 's'}),
            settings={},
            prefix_tags=[],
            main_tags=list(main_tags),
            postfix_tags=[],
        )

    def test_legacy_mode_applies_legacy_dsl(self):
        mod = _primed_module("(girl):main+=from_legacy")
        mod.set_v2_dsl("(girl):main+=from_v2")
        mod.set_editor_mode("legacy")
        ctx = self._make_context(["girl"])
        result = mod.execute_pipeline_hook(ctx)
        assert "from_legacy" in result.main_tags
        assert "from_v2" not in result.main_tags

    def test_v2_mode_applies_v2_dsl(self):
        mod = _primed_module("(girl):main+=from_legacy")
        mod.set_v2_dsl("(girl):main+=from_v2")
        mod.set_editor_mode("v2")
        ctx = self._make_context(["girl"])
        result = mod.execute_pipeline_hook(ctx)
        assert "from_v2" in result.main_tags
        assert "from_legacy" not in result.main_tags

    def test_v2_mode_empty_does_not_apply_legacy(self):
        """v2 모드 + 빈 v2 DSL → 레거시 규칙이 새어나오지 않아야 함."""
        mod = _primed_module("(girl):main+=from_legacy")
        mod.set_editor_mode("v2")
        ctx = self._make_context(["girl"])
        result = mod.execute_pipeline_hook(ctx)
        assert "from_legacy" not in result.main_tags


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
