"""Sub-phase 1.7 hotfix 회귀 테스트 — 외부 리뷰 2026-04-21 반영.

사용자가 "무시" 로 표기한 4건 중 문제 소지가 있는 3건을 수정한 부분의 동작
보장:

- **P1-A** `engine_options` 런타임 연결: `set_engine_options` 로 주입한
  max_passes/stop_on_match 가 `execute_pipeline_hook` 을 거쳐 적용되는지.
- **P1-B** `char:*` / `uc:*` 활성 필터링: 비활성 슬롯은 대상에서 제외되는지.
- **P2-A** `hooker_update_prompt` 호출: char/uc write 후 CharacterModule UI
  동기화 트리거가 불리는지.

P2-B (`global_uc` 런타임 stub) 는 파서 호환 유지 + 런타임 skip 로그로 묶어두며
본 스위트는 skip 동작만 확인.
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

from modules.conditional_prompt_module import (  # noqa: E402
    PromptListModifierModule,
)
from tests.conditional.test_engine_headless import (  # noqa: E402
    MockAppContext,
    MockCharacterModule,
    MockCharacterWidget,
    MockCheckbox,
    MockSourceRow,
    make_context,
    make_module,
)


class _MinimalCharMod:
    """hooker_update_prompt 미구현 / character_widgets 없음 — 후방호환 확인용."""

    def __init__(self):
        self.modifiable_clone = {"characters": ["1girl"], "uc": []}
        # character_widgets 없음 → 헬퍼가 모든 슬롯을 active 로 간주

    def get_character_modifiable_clone(self):
        return self.modifiable_clone

    # hooker_update_prompt 의도적으로 미정의


# ============================================================================
# P1-A: engine_options → execute_pipeline_hook
# ============================================================================


def _install_hook_prerequisites(mod, rules_text: str):
    """execute_pipeline_hook 이 진입 가능하도록 최소한의 상태를 구성."""
    # enable_checkbox / rules_textedit 은 실제 위젯 대신 Mock 으로 대체
    class _Chk:
        def isChecked(self):
            return True

    class _Rules:
        def __init__(self, text):
            self._text = text

        def toPlainText(self):
            return self._text

    mod.enable_checkbox = _Chk()
    mod.rules_textedit = _Rules(rules_text)
    mod.log_textedit = None  # _update_log_display 는 None 안전 처리


class TestEngineOptionsWiring:
    def test_default_is_single_pass(self):
        mod = make_module(MockAppContext())
        opts = mod.get_engine_options()
        assert opts["max_passes"] == 1
        assert opts["stop_on_match"] is False

    def test_setter_clamps_min_max_passes(self):
        mod = make_module(MockAppContext())
        mod.set_engine_options(max_passes=0, stop_on_match=False)
        assert mod.get_engine_options()["max_passes"] == 1

    def test_setter_coerces_types(self):
        mod = make_module(MockAppContext())
        mod.set_engine_options(max_passes=3.7, stop_on_match=1)  # type: ignore[arg-type]
        opts = mod.get_engine_options()
        assert opts["max_passes"] == 3
        assert opts["stop_on_match"] is True

    def test_stop_on_match_propagates_through_hook(self):
        """stop_on_match=True 시 첫 매칭 뒤의 규칙은 실행되지 않아야 한다."""
        mod = make_module(MockAppContext())
        mod.set_engine_options(max_passes=1, stop_on_match=True)
        _install_hook_prerequisites(
            mod, "(trigger):main+=first, (trigger):main+=second"
        )
        ctx = make_context(main=["trigger"])
        result = mod.execute_pipeline_hook(ctx)
        assert "first" in result.main_tags
        assert "second" not in result.main_tags, (
            "stop_on_match 가 런타임 훅으로 전파되지 않음"
        )

    def test_max_passes_propagates_through_hook(self):
        """max_passes>1 시 체이닝된 규칙이 여러 패스 동안 수렴한다."""
        mod = make_module(MockAppContext())
        mod.set_engine_options(max_passes=3, stop_on_match=False)
        _install_hook_prerequisites(
            mod, "(a):main+=b, (b):main+=c"
        )
        ctx = make_context(main=["a"])
        result = mod.execute_pipeline_hook(ctx)
        # pass1: a → b 추가. pass2: b → c 추가.
        assert "b" in result.main_tags
        assert "c" in result.main_tags, (
            "max_passes 가 런타임 훅으로 전파되지 않음 "
            f"(main_tags={result.main_tags})"
        )


# ============================================================================
# P1-B: char:* / uc:* 활성 슬롯 필터링
# ============================================================================


class TestCharStarActiveFilter:
    def test_char_star_skips_inactive_slots(self):
        cm = MockCharacterModule(
            characters=["1girl, cat", "1boy, dog", "robot"],
            active_flags=[True, False, True],  # C2 비활성
        )
        mod = make_module(MockAppContext(char_module=cm))
        ctx = make_context(main=["scene"])

        mod._apply_rules(ctx, "():char:*+=common", [])

        assert "common" in cm.modifiable_clone["characters"][0]
        assert "common" not in cm.modifiable_clone["characters"][1], (
            "비활성 C2 에 쓰여짐 (필터링 실패)"
        )
        assert "common" in cm.modifiable_clone["characters"][2]

    def test_uc_star_skips_inactive_slots(self):
        cm = MockCharacterModule(
            characters=["1girl", "1boy"],
            uc=["dull", "bland"],
            active_flags=[False, True],
        )
        mod = make_module(MockAppContext(char_module=cm))
        ctx = make_context(main=["scene"])

        mod._apply_rules(ctx, "():uc:*+=artifact", [])

        assert "artifact" not in cm.modifiable_clone["uc"][0], (
            "비활성 슬롯의 uc 에 쓰여짐"
        )
        assert "artifact" in cm.modifiable_clone["uc"][1]

    def test_char_star_no_active_slots_records_skip(self):
        cm = MockCharacterModule(
            characters=["1girl", "1boy"],
            active_flags=[False, False],
        )
        app_ctx = MockAppContext(char_module=cm)
        mod = make_module(app_ctx)
        ctx = make_context(main=["scene"])
        logs: list[str] = []
        mod._apply_rules(ctx, "():char:*+=common", logs)

        assert "common" not in cm.modifiable_clone["characters"][0]
        assert "common" not in cm.modifiable_clone["characters"][1]
        # skip 집계 로그 출력
        assert any("char:*" in l for l in logs)

    def test_char_n_is_unaffected_by_active_flag(self):
        """char:1 같은 명시 인덱스는 활성 여부와 무관하게 적용(명시는 사용자 의도)."""
        cm = MockCharacterModule(
            characters=["1girl", "1boy"],
            active_flags=[False, True],
        )
        mod = make_module(MockAppContext(char_module=cm))
        ctx = make_context(main=["scene"])

        mod._apply_rules(ctx, "():char:1+=explicit", [])

        assert "explicit" in cm.modifiable_clone["characters"][0], (
            "명시 인덱스는 활성 여부와 관계없이 쓰여야 함"
        )


# ============================================================================
# P2-A: hooker_update_prompt 호출
# ============================================================================


class TestHookerUpdateRefresh:
    def test_char_write_triggers_refresh(self):
        cm = MockCharacterModule(characters=["1girl"])
        mod = make_module(MockAppContext(char_module=cm))
        ctx = make_context(main=["scene"])

        assert not cm.hooker_update_called
        mod._apply_rules(ctx, "():char:1+=blush", [])
        assert cm.hooker_update_called, (
            "char:N write 후 hooker_update_prompt 미호출"
        )

    def test_uc_write_triggers_refresh(self):
        cm = MockCharacterModule(
            characters=["1girl"], uc=["dull"]
        )
        mod = make_module(MockAppContext(char_module=cm))
        ctx = make_context(main=["scene"])
        mod._apply_rules(ctx, "():uc:1+=blurry", [])
        assert cm.hooker_update_called

    def test_char_replace_triggers_refresh(self):
        cm = MockCharacterModule(characters=["1girl, old_tag"])
        mod = make_module(MockAppContext(char_module=cm))
        ctx = make_context(main=["scene"])
        mod._apply_rules(ctx, "():char_replace(1, old_tag, new_tag)", [])
        assert cm.hooker_update_called

    def test_char_star_refresh_runs_once_per_action(self):
        cm = MockCharacterModule(
            characters=["a", "b", "c"],
            active_flags=[True, True, True],
        )
        mod = make_module(MockAppContext(char_module=cm))
        ctx = make_context(main=["scene"])
        mod._apply_rules(ctx, "():char:*+=t", [])
        assert cm.hooker_update_called

    def test_char_write_without_hooker_method_does_not_crash(self):
        """hooker_update_prompt 미정의 / character_widgets 없는 Mock 도 안전."""
        cm = _MinimalCharMod()
        mod = make_module(MockAppContext(char_module=cm))
        ctx = make_context(main=["scene"])
        # 예외 없이 완주
        mod._apply_rules(ctx, "():char:1+=blush", [])
        assert "blush" in cm.modifiable_clone["characters"][0]


# ============================================================================
# P2-B: global_uc 런타임 stub (skip 로그만)
# ============================================================================


class TestGlobalUcStub:
    def test_global_uc_records_skip(self):
        mod = make_module(MockAppContext())
        ctx = make_context(main=["trigger"])
        logs: list[str] = []
        mod._apply_rules(ctx, "(trigger):global_uc+=ignored", logs)
        # skip 집계 로그에 global_uc 가 나타나야 함
        assert any("global_uc" in l for l in logs), (
            f"global_uc skip 로그 누락: {logs}"
        )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
