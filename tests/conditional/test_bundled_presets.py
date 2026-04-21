"""번들 프리셋 5종 E2E 시뮬레이션 (Sub-phase 1.6).

검증 경로: `data/conditional_presets_bundled/*.json` → `rulebook_from_dict`
→ `serialize_rulebook` → 기존 엔진 `_apply_rules` 실행 → 기대 결과.

이 테스트는 프리셋 저장 포맷, 파서-직렬화기 왕복, 레거시 엔진 호환을 모두
관통하는 감지망이다. 각 번들이 의도한 UC 대로 동작하는지 최소 시나리오 1개씩.

주: 외부 리뷰 P1 에 따라 런타임 훅은 아직 engine_options 미연결. 본 테스트는
`_apply_rules` 를 직접 호출하며 `max_passes`/`stop_on_match` 는 번들 값
(`book.max_passes`, `book.stop_on_match`) 으로 명시 전달한다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Qt headless (conditional_prompt_module 이 QtWidgets 임포트하므로 필요)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from modules.conditional.dsl_serializer import serialize_rulebook  # noqa: E402
from modules.conditional.preset_io import (  # noqa: E402
    DEFAULT_BUNDLED_DIR,
    PresetStorage,
)
from modules.conditional_prompt_module import (  # noqa: E402
    PromptListModifierModule,
)
from tests.conditional.test_engine_headless import (  # noqa: E402
    MockAppContext,
    MockCharacterModule,
    MockSourceRow,
    make_context,
    make_module,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(scope="module")
def storage() -> PresetStorage:
    """실제 번들 디렉터리를 가리키는 스토리지 (build_bundled_presets 로 생성됨)."""
    return PresetStorage(bundled_dir=DEFAULT_BUNDLED_DIR)


def _run_book(module, book, ctx):
    """RuleBook → DSL → 엔진 실행. logs 은 무시."""
    dsl = serialize_rulebook(book)
    logs: list[str] = []
    return module._apply_rules(
        ctx,
        dsl,
        logs,
        max_passes=book.max_passes,
        stop_on_match=book.stop_on_match,
    )


# ============================================================================
# 번들 존재 + 로드 가능성
# ============================================================================


EXPECTED_BUNDLES = {
    "nsfw_auto_negative",
    "character_duo_link",
    "quality_boost",
    "resolution_force",
    "composite_filter",
}


class TestBundleAvailability:
    def test_all_files_present(self):
        names = {p.stem for p in DEFAULT_BUNDLED_DIR.glob("*.json")}
        assert EXPECTED_BUNDLES.issubset(names), (
            f"누락된 번들: {EXPECTED_BUNDLES - names}"
        )

    @pytest.mark.parametrize("name", sorted(EXPECTED_BUNDLES))
    def test_each_bundle_loads(self, storage, name):
        book = storage.load(name)
        assert book.rules, f"{name}: 빈 RuleBook"
        # 직렬화도 가능해야 함 (미래 파서/직렬화기 회귀 감지)
        dsl = serialize_rulebook(book)
        assert dsl.strip(), f"{name}: 빈 DSL"


# ============================================================================
# 번들 1 — nsfw_auto_negative (UC-4)
# ============================================================================


class TestNsfwAutoNegative:
    """rating=e → neg 에 nsfw_artifacts 등 append_list."""

    def test_explicit_rating_adds_neg_tags(self, storage):
        book = storage.load("nsfw_auto_negative")
        src = MockSourceRow(rating="e")
        app_ctx = MockAppContext(source_row=src)
        mod = make_module(app_ctx)
        ctx = make_context(main=["1girl"], source_row=src)

        _run_book(mod, book, ctx)

        neg_text = app_ctx.main_window.negative_prompt_textedit.toPlainText()
        assert "nsfw_artifacts" in neg_text
        assert "bad_anatomy" in neg_text

    def test_safe_rating_no_neg_injection(self, storage):
        book = storage.load("nsfw_auto_negative")
        src = MockSourceRow(rating="s")
        app_ctx = MockAppContext(source_row=src)
        mod = make_module(app_ctx)
        ctx = make_context(main=["1girl"], source_row=src)

        _run_book(mod, book, ctx)

        neg_text = app_ctx.main_window.negative_prompt_textedit.toPlainText()
        assert "nsfw_artifacts" not in neg_text
        assert "low_quality" not in neg_text


# ============================================================================
# 번들 2 — character_duo_link (UC-1a/b)
# ============================================================================


class TestCharacterDuoLink:
    def test_c1_looking_enables_c2(self, storage):
        book = storage.load("character_duo_link")
        cm = MockCharacterModule(
            characters=["1girl, looking at viewer", "1boy"],
            active_flags=[True, False],  # C2 초기 비활성
        )
        app_ctx = MockAppContext(char_module=cm)
        mod = make_module(app_ctx)
        ctx = make_context(main=["scene"])

        _run_book(mod, book, ctx)

        assert cm.character_widgets[1].active_checkbox.isChecked(), (
            "C1 이 viewer 를 보면 C2 가 활성화되어야 함"
        )

    def test_c1_solo_disables_c2(self, storage):
        book = storage.load("character_duo_link")
        cm = MockCharacterModule(
            characters=["1girl, solo", "1boy"],
            active_flags=[True, True],
        )
        app_ctx = MockAppContext(char_module=cm)
        mod = make_module(app_ctx)
        ctx = make_context(main=["scene"])

        _run_book(mod, book, ctx)

        assert not cm.character_widgets[1].active_checkbox.isChecked(), (
            "C1 이 solo 태그면 C2 가 비활성화되어야 함"
        )


# ============================================================================
# 번들 3 — quality_boost
# ============================================================================


class TestQualityBoost:
    def test_safe_rating_adds_prefix_quality(self, storage):
        book = storage.load("quality_boost")
        src = MockSourceRow(rating="s")
        app_ctx = MockAppContext(source_row=src)
        mod = make_module(app_ctx)
        ctx = make_context(prefix=["base"], main=["1girl"], source_row=src)

        result = _run_book(mod, book, ctx)

        assert "masterpiece" in result.prefix_tags
        assert "best quality" in result.prefix_tags

    def test_landscape_adds_postfix_detail(self, storage):
        book = storage.load("quality_boost")
        app_ctx = MockAppContext()
        mod = make_module(app_ctx)
        ctx = make_context(main=["landscape"])

        result = _run_book(mod, book, ctx)

        assert "highres" in result.postfix_tags
        assert "detailed background" in result.postfix_tags


# ============================================================================
# 번들 4 — resolution_force (UC-2)
# ============================================================================


class TestResolutionForce:
    def test_landscape_injects_resolution_tag(self, storage):
        book = storage.load("resolution_force")
        app_ctx = MockAppContext()
        mod = make_module(app_ctx)
        ctx = make_context(main=["landscape"])

        result = _run_book(mod, book, ctx)

        # api_service 가 prefix 의 `resolution:XXX` 를 인라인 파라미터로 파싱
        assert "resolution:landscape" in result.prefix_tags

    def test_portrait_injects_only_portrait(self, storage):
        """stop_on_match=True 가 걸려 있으므로 첫 매칭 후 중단."""
        book = storage.load("resolution_force")
        app_ctx = MockAppContext()
        mod = make_module(app_ctx)
        ctx = make_context(main=["portrait"])

        result = _run_book(mod, book, ctx)

        assert "resolution:portrait" in result.prefix_tags
        assert "resolution:landscape" not in result.prefix_tags


# ============================================================================
# 번들 5 — composite_filter (UC-3)
# ============================================================================


class TestCompositeFilter:
    def test_and_condition_adds_tag(self, storage):
        book = storage.load("composite_filter")
        app_ctx = MockAppContext()
        mod = make_module(app_ctx)
        ctx = make_context(main=["1girl", "solo", "blue eyes"])

        result = _run_book(mod, book, ctx)

        assert "simple_composition" in result.main_tags

    def test_pattern_replace(self, storage):
        book = storage.load("composite_filter")
        app_ctx = MockAppContext()
        mod = make_module(app_ctx)
        ctx = make_context(
            main=["red bad_shirt", "green bad_shirt", "blue hat"]
        )

        result = _run_book(mod, book, ctx)

        # __bad_shirt__= 패턴은 bad_shirt 포함 태그를 모두 제거하고 clean_shirt 를 삽입
        assert not any("bad_shirt" in t for t in result.main_tags), (
            f"bad_shirt 포함 태그가 남아있음: {result.main_tags}"
        )

    def test_nsfw_adds_clean_postfix(self, storage):
        book = storage.load("composite_filter")
        app_ctx = MockAppContext()
        mod = make_module(app_ctx)
        ctx = make_context(main=["nsfw"])

        result = _run_book(mod, book, ctx)

        assert "clean" in result.postfix_tags


# ============================================================================
# 통합 — 번들 리스트 API
# ============================================================================


class TestBundleListing:
    def test_list_includes_all_bundles(self, storage):
        infos = storage.list_all()
        names = {i.name for i in infos if i.is_bundled}
        # name 은 display name ("Nsfw Auto Negative") 로 저장되어 있음
        display_names = {
            b.replace("_", " ").title() for b in EXPECTED_BUNDLES
        }
        assert display_names.issubset(names), (
            f"누락: {display_names - names}"
        )

    def test_bundles_are_marked_read_only(self, storage):
        infos = storage.list_all()
        bundled = [i for i in infos if i.is_bundled]
        assert len(bundled) >= 5
        assert all(
            i.path.parent == DEFAULT_BUNDLED_DIR for i in bundled
        ), "번들은 `data/conditional_presets_bundled/` 하위여야 함"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
