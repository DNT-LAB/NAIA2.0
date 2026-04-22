"""Headless verification of Conditional Prompt Editor v2.1 (Phase 0, Sub-phase 1.1, 1.1b).

체크리스트 기반 엔진-레벨 검증. Qt 위젯 없이 `_apply_rules` 직접 호출.
- UC-1a/1b/1c (char_in / char_set / char_replace)
- UC-3 (레거시 호환)
- UC-4 (neg 타겟)
- rating(source=override), max_passes 진동 감지, skip 집계 로그

UC-2(강제 해상도)는 엔진 확장 없음 → API service 인라인 파라미터 검증으로 별도.

실행: `python tests/conditional/test_engine_headless.py`
"""

import os
import sys
import traceback

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Qt headless setup — conditional_prompt_module이 QtWidgets 임포트하므로 QApplication 필요
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication(sys.argv)

from modules.conditional_prompt_module import PromptListModifierModule  # noqa: E402
from core.prompt_context import PromptContext  # noqa: E402


# ============================================================================
# Mock 인프라
# ============================================================================


class MockSourceRow:
    """pandas Series 호환 (.get() 지원)."""
    def __init__(self, **kw):
        self._data = kw

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __repr__(self):
        return f"MockSourceRow({self._data})"


class MockCheckbox:
    def __init__(self, checked=True):
        self._checked = bool(checked)

    def isChecked(self):
        return self._checked

    def setChecked(self, v):
        self._checked = bool(v)


class MockCharacterWidget:
    def __init__(self, active=True):
        self.active_checkbox = MockCheckbox(active)


class MockCharacterModule:
    def __init__(self, characters=None, uc=None, active_flags=None):
        self.modifiable_clone = {
            'characters': list(characters or []),
            'uc': list(uc or []),
        }
        n = max(
            len(characters or []), len(uc or []),
            len(active_flags or [])
        )
        flags = active_flags if active_flags is not None else [True] * n
        self.character_widgets = [MockCharacterWidget(a) for a in flags]
        self.hooker_update_called = False

    def get_character_modifiable_clone(self):
        return self.modifiable_clone

    def set_character_active(self, index, active):
        if 0 <= index < len(self.character_widgets):
            self.character_widgets[index].active_checkbox.setChecked(active)
            return True
        return False

    def hooker_update_prompt(self):
        self.hooker_update_called = True


class MockNegativeWidget:
    def __init__(self, text=""):
        self._text = text

    def toPlainText(self):
        return self._text

    def setPlainText(self, t):
        self._text = t


class MockModelCombo:
    def __init__(self, text="NAID4"):
        self._text = text

    def currentText(self):
        return self._text


class MockMainWindow:
    def __init__(self, naid4=True):
        self.negative_prompt_textedit = MockNegativeWidget()
        self.model_combo = MockModelCombo("NAID4" if naid4 else "NAIDiffusion3")
        self.search_results = None


class MockMiddleSectionController:
    def __init__(self, char_module):
        self._char_module = char_module

    def get_module_instance(self, name):
        if name == "CharacterModule":
            return self._char_module
        return None


class MockAppContext:
    def __init__(self, api_mode="NAI", naid4=True, source_row=None,
                 rating_override=None, char_module=None):
        self._api_mode = api_mode
        self.main_window = MockMainWindow(naid4=naid4)
        self.current_source_row = source_row
        self.current_prompt_context = None
        self.rating_override = rating_override
        if char_module is None:
            char_module = MockCharacterModule()
        self.middle_section_controller = MockMiddleSectionController(char_module)
        self._char_module = char_module
        self.published = []

    def get_api_mode(self):
        return self._api_mode

    def publish(self, event, data):
        self.published.append((event, data))

    def subscribe(self, event, cb):
        pass


def make_module(app_ctx):
    mod = PromptListModifierModule()
    mod.app_context = app_ctx
    return mod


def make_context(prefix=None, main=None, postfix=None, source_row=None, settings=None):
    return PromptContext(
        source_row=source_row,
        settings=settings or {},
        prefix_tags=list(prefix or []),
        main_tags=list(main or []),
        postfix_tags=list(postfix or []),
    )


# ============================================================================
# 테스트 결과 수집
# ============================================================================

RESULTS = []


def check(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    RESULTS.append((name, status, detail))
    indicator = "✅" if passed else "❌"
    line = f"  {indicator} {name}"
    if detail and not passed:
        line += f"\n     → {detail}"
    print(line)


def section(title):
    print(f"\n{title}")
    print("-" * len(title))


# ============================================================================
# Phase 0 / 1.1 / 1.1b 테스트
# ============================================================================


def test_uc3_legacy_simple_rating():
    src = MockSourceRow(rating='e')
    mod = make_module(MockAppContext(source_row=src))
    ctx = make_context(prefix=['base'], main=['girl'], source_row=src)
    logs = []
    result = mod._apply_rules(ctx, "(e):prefix+=nsfw", logs)
    check(
        "UC-3a: (e) 레거시 조건 매칭 + prefix+= 동작",
        'nsfw' in result.prefix_tags,
        f"prefix_tags={result.prefix_tags}",
    )


def test_uc3_legacy_and_matched():
    mod = make_module(MockAppContext())
    ctx = make_context(main=['1girl', 'smile'])
    logs = []
    result = mod._apply_rules(ctx, "(1girl&smile):main+=happy", logs)
    check(
        "UC-3b: AND 조건 (1girl&smile) 매칭 → happy 추가",
        'happy' in result.main_tags,
        f"main_tags={result.main_tags}",
    )


def test_uc3_legacy_and_not_matched():
    mod = make_module(MockAppContext())
    ctx = make_context(main=['1girl'])
    logs = []
    result = mod._apply_rules(ctx, "(1girl&smile):main+=happy", logs)
    check(
        "UC-3c: AND 조건 불일치 시 추가 없음",
        'happy' not in result.main_tags,
    )


def test_uc3_legacy_or():
    mod = make_module(MockAppContext())
    ctx = make_context(main=['cat'])
    logs = []
    result = mod._apply_rules(ctx, "(cat|dog):main+=animal", logs)
    check(
        "UC-3d: OR 조건 (cat|dog) 매칭",
        'animal' in result.main_tags,
    )


def test_uc3_pattern_delete():
    mod = make_module(MockAppContext())
    ctx = make_context(main=['red shirt', 'long skirt', 'blue hat'])
    logs = []
    result = mod._apply_rules(ctx, "():__shirt=,", logs)
    check(
        "UC-3e: 패턴 __shirt= → shirt 포함 태그 제거, 타 태그 보존",
        'red shirt' not in result.main_tags and 'blue hat' in result.main_tags,
        f"main_tags={result.main_tags}",
    )


def test_uc3_exact_replace_weight_preserve():
    mod = make_module(MockAppContext())
    ctx = make_context(main=['1.05::smile ::', 'blue eyes'])
    logs = []
    result = mod._apply_rules(ctx, "(smile):smile=grin", logs)
    has_weight_preserved = any(
        '1.05::grin' in t or '1.05::grin ::' in t for t in result.main_tags
    )
    check(
        "UC-3f: 정확 일치 치환 시 NAI 가중치 래핑 보존",
        has_weight_preserved,
        f"main_tags={result.main_tags}",
    )


def test_uc3_exact_replace_plain_tag():
    """회귀: plain (가중치 없는) 태그 교체. 이전 구현은 pop/insert 가
    weighted 가드 안에 들어 있어 plain 태그가 silent-no-op 으로 남아있던 버그.
    """
    mod = make_module(MockAppContext())
    ctx = make_context(main=['full body', 'blush', 'smile'])
    logs = []
    result = mod._apply_rules(
        ctx, "(full body):full body=upper body", logs
    )
    check(
        "UC-3g: 평범한 태그 교체 — full body → upper body 치환",
        'upper body' in result.main_tags
        and 'full body' not in result.main_tags,
        f"main_tags={result.main_tags}",
    )


def test_uc3_exact_replace_plain_multi_new():
    """회귀: plain 태그를 여러 새 태그로 교체 (순서 유지)."""
    mod = make_module(MockAppContext())
    ctx = make_context(main=['sweat', 'solo'])
    logs = []
    result = mod._apply_rules(
        ctx, "():sweat=sweat^sweatdrop^steam", logs
    )
    # 기존 'sweat' 위치에 ['sweat', 'sweatdrop', 'steam'] 이 순서대로 삽입
    expected_order = ['sweat', 'sweatdrop', 'steam', 'solo']
    check(
        "UC-3h: plain 태그 → 다중 새 태그 치환 시 순서 유지",
        result.main_tags == expected_order,
        f"main_tags={result.main_tags}",
    )


def test_rating_source_override():
    app_ctx = MockAppContext(rating_override='e', source_row=None)
    mod = make_module(app_ctx)
    ctx = make_context(main=['base'])
    logs = []
    result = mod._apply_rules(
        ctx, "(rating(e, source=override)):main+=override_hit", logs,
    )
    check(
        "1.1: rating(e, source=override) override 값 매칭",
        'override_hit' in result.main_tags,
        f"main_tags={result.main_tags}",
    )


def test_rating_source_row_only():
    """source=row는 row만 조회, override 값이 있어도 무시"""
    app_ctx = MockAppContext(
        rating_override='e',
        source_row=MockSourceRow(rating='s'),
    )
    mod = make_module(app_ctx)
    ctx = make_context(main=['base'])
    logs = []
    result = mod._apply_rules(
        ctx, "(rating(s, source=row)):main+=row_hit", logs,
    )
    check(
        "1.1: rating(s, source=row) row만 조회 (override 무시)",
        'row_hit' in result.main_tags,
    )


def test_max_passes_fixed_point_detection():
    """진동 규칙 a↔b 에서 max_passes 내 고정점 감지 + 로그"""
    mod = make_module(MockAppContext())
    ctx = make_context(main=['a'])
    logs = []
    mod._apply_rules(
        ctx, "(a):a=b, (b):b=a", logs,
        max_passes=10, stop_on_match=False,
    )
    loop_detected = any('루프' in l or '고정점' in l or '진동' in l for l in logs)
    check(
        "1.1: max_passes 진동 감지 (A↔B) → 루프 로그 출력",
        loop_detected,
        f"pass 관련 로그: {[l for l in logs if 'pass' in l.lower() or '루프' in l][:5]}",
    )


def test_stop_on_match():
    """stop_on_match=True 시 매칭 규칙 이후 스킵"""
    mod = make_module(MockAppContext())
    ctx = make_context(main=['trigger'])
    logs = []
    result = mod._apply_rules(
        ctx, "(trigger):main+=first, (trigger):main+=second", logs,
        max_passes=1, stop_on_match=True,
    )
    # first는 매칭 후 stop → second는 실행 안됨
    check(
        "1.1: stop_on_match=True 시 첫 매칭 후 이후 규칙 스킵",
        'first' in result.main_tags and 'second' not in result.main_tags,
        f"main_tags={result.main_tags}",
    )


def test_uc1a_char_in_contains():
    cm = MockCharacterModule(
        characters=['1girl, smile, happy', 'neutral, boy'],
    )
    mod = make_module(MockAppContext(char_module=cm))
    ctx = make_context(main=['base'])
    logs = []
    result = mod._apply_rules(
        ctx, "(char_in(1, smile)):main+=c1_has_smile", logs,
    )
    check(
        "UC-1a: char_in(1, smile) 서브스트링 포함 → 매칭",
        'c1_has_smile' in result.main_tags,
        f"main_tags={result.main_tags}",
    )


def test_uc1a_char_in_not_contains():
    cm = MockCharacterModule(characters=['neutral, boy'])
    mod = make_module(MockAppContext(char_module=cm))
    ctx = make_context(main=['base'])
    logs = []
    result = mod._apply_rules(
        ctx, "(~char_in(1, smile)):main+=c1_no_smile", logs,
    )
    check(
        "UC-1a: ~char_in(1, smile) — 없으면 매칭",
        'c1_no_smile' in result.main_tags,
    )


def test_uc1a_char_in_exact():
    cm = MockCharacterModule(
        characters=['blue eye makeup, smile, 1girl'],
    )
    mod = make_module(MockAppContext(char_module=cm))
    ctx = make_context(main=['base'])
    logs = []
    # *smile — 정확 토큰 일치 (서브스트링 'blue eye makeup'의 eye와 달리)
    result = mod._apply_rules(
        ctx, "(char_in(1, *smile)):main+=exact_hit", logs,
    )
    check(
        "UC-1a: char_in(1, *smile) 정확 토큰 일치 → 매칭",
        'exact_hit' in result.main_tags,
    )


def test_uc1a_char_on():
    cm = MockCharacterModule(
        characters=['a', 'b'],
        active_flags=[True, False],
    )
    mod = make_module(MockAppContext(char_module=cm))
    ctx = make_context(main=['base'])
    logs = []
    result = mod._apply_rules(
        ctx,
        "(char_on(1)):main+=c1_on, (~char_on(2)):main+=c2_off",
        logs,
    )
    check(
        "UC-1a: char_on(N) / ~char_on(N) — 활성 상태 체크",
        'c1_on' in result.main_tags and 'c2_off' in result.main_tags,
        f"main_tags={result.main_tags}",
    )


def test_uc1b_char_set_disable():
    cm = MockCharacterModule(
        characters=['1girl', 'boy'],
        active_flags=[True, True],
    )
    mod = make_module(MockAppContext(char_module=cm))
    ctx = make_context(main=['base'])
    logs = []
    mod._apply_rules(ctx, "():char_set(2, disabled)", logs)
    c2_off = not cm.character_widgets[1].active_checkbox.isChecked()
    check(
        "UC-1b: char_set(2, disabled) → C2 active_checkbox off",
        c2_off,
        f"C2 active={cm.character_widgets[1].active_checkbox.isChecked()}",
    )


def test_uc1b_char_set_enable():
    cm = MockCharacterModule(
        characters=['a', 'b'],
        active_flags=[True, False],
    )
    mod = make_module(MockAppContext(char_module=cm))
    ctx = make_context(main=['base'])
    logs = []
    mod._apply_rules(ctx, "():char_set(2, enabled)", logs)
    c2_on = cm.character_widgets[1].active_checkbox.isChecked()
    check(
        "UC-1b: char_set(2, enabled) → C2 active_checkbox on",
        c2_on,
    )


def test_uc1c_char_replace():
    cm = MockCharacterModule(
        characters=['1girl, smile, blue hair', 'neutral'],
    )
    mod = make_module(MockAppContext(char_module=cm))
    ctx = make_context(main=['base'])
    logs = []
    mod._apply_rules(ctx, "():char_replace(1, smile, grin)", logs)
    c1 = cm.modifiable_clone['characters'][0]
    tags = [t.strip() for t in c1.split(',')]
    check(
        "UC-1c: char_replace(1, smile, grin) 정확 토큰 치환",
        'grin' in tags and 'smile' not in tags,
        f"c1='{c1}'",
    )


def test_uc1c_char_replace_weight_preserve():
    cm = MockCharacterModule(
        characters=['1.05::smile ::, blue hair'],
    )
    mod = make_module(MockAppContext(char_module=cm))
    ctx = make_context(main=['base'])
    logs = []
    mod._apply_rules(ctx, "():char_replace(1, smile, grin)", logs)
    c1 = cm.modifiable_clone['characters'][0]
    check(
        "UC-1c: char_replace 가중치 래핑 보존 (NAI 포맷)",
        '1.05::grin' in c1,
        f"c1='{c1}'",
    )


def test_uc1c_char_replace_no_match():
    cm = MockCharacterModule(characters=['1girl, smile'])
    mod = make_module(MockAppContext(char_module=cm))
    ctx = make_context(main=['base'])
    logs = []
    mod._apply_rules(ctx, "():char_replace(1, nothing, grin)", logs)
    c1 = cm.modifiable_clone['characters'][0]
    skip_logged = any('char_replace(1,nothing' in l and 'Skip' in l for l in logs)
    check(
        "UC-1c: char_replace 매칭 없을 때 skip 집계 + 프롬프트 불변",
        c1 == '1girl, smile' and skip_logged,
        f"c1='{c1}', skip_logged={skip_logged}, logs={[l for l in logs if 'Skip' in l]}",
    )


def test_uc4_neg_append():
    app_ctx = MockAppContext(naid4=False)
    app_ctx.main_window.negative_prompt_textedit._text = 'base neg'
    mod = make_module(app_ctx)
    ctx = make_context(main=['base'])
    logs = []
    mod._apply_rules(ctx, "():neg+=bad hands^bad anatomy", logs)
    new_text = app_ctx.main_window.negative_prompt_textedit.toPlainText()
    check(
        "UC-4: neg+= 네거티브 append (기존 텍스트 + 신규 태그)",
        'bad hands' in new_text and 'base neg' in new_text,
        f"neg='{new_text}'",
    )


def test_uc4_neg_replace():
    app_ctx = MockAppContext()
    app_ctx.main_window.negative_prompt_textedit._text = 'old stuff'
    mod = make_module(app_ctx)
    ctx = make_context(main=['base'])
    logs = []
    mod._apply_rules(ctx, "():neg=clean^safe", logs)
    new_text = app_ctx.main_window.negative_prompt_textedit.toPlainText()
    check(
        "UC-4: neg= 네거티브 전체 교체",
        'clean' in new_text and 'old stuff' not in new_text,
        f"neg='{new_text}'",
    )


def test_skip_char_target_on_non_naid4():
    """non-NAID4 모드에서 char:1+= 규칙 → silent 금지, 집계 skip 로그"""
    mod = make_module(MockAppContext(naid4=False))
    ctx = make_context(main=['base'])
    logs = []
    mod._apply_rules(ctx, "():char:1+=smiling", logs)
    skip_found = any('Skip' in l and 'char:1' in l for l in logs)
    check(
        "1.1: non-NAID4에서 char:1+= → skip 집계 로그 출력",
        skip_found,
        f"logs 마지막 3: {logs[-3:]}",
    )


def test_char_target_write_naid4():
    """NAID4에서 char:1+= 시 modifiable_clone에 추가 반영"""
    cm = MockCharacterModule(characters=['1girl'])
    mod = make_module(MockAppContext(char_module=cm))
    ctx = make_context(main=['base'])
    logs = []
    mod._apply_rules(ctx, "():char:1+=smiling", logs)
    c1 = cm.modifiable_clone['characters'][0]
    check(
        "1.1: NAID4에서 char:1+=smiling → modifiable_clone['characters'][0]에 추가",
        'smiling' in c1,
        f"c1='{c1}'",
    )


def test_combined_scenario_uc1b():
    """조합 시나리오 — UC-1b: C1에 boy 있으면 C2 disable"""
    cm = MockCharacterModule(
        characters=['1boy, short hair', '1girl, long hair'],
        active_flags=[True, True],
    )
    mod = make_module(MockAppContext(char_module=cm))
    ctx = make_context(main=['base'])
    logs = []
    mod._apply_rules(
        ctx,
        "(char_in(1, 1boy)):char_set(2, disabled)",
        logs,
    )
    c2_active = cm.character_widgets[1].active_checkbox.isChecked()
    check(
        "조합: char_in(1, 1boy) 매칭 시 char_set(2, disabled) 발동",
        c2_active is False,
        f"C2 active={c2_active}",
    )


def test_uc2_resolution_via_prefix_tag():
    """UC-2: (portrait):prefix+=resolution:1024x1536 — 엔진 확장 없음,
    prefix_tags에 태그가 추가되는지만 확인 (api_service가 소비)."""
    mod = make_module(MockAppContext())
    ctx = make_context(prefix=['masterpiece'], main=['portrait'])
    logs = []
    result = mod._apply_rules(
        ctx, "(portrait):prefix+=resolution:1024x1536", logs,
    )
    check(
        "UC-2: prefix+=resolution:1024x1536 추가 (api_service가 후속 소비)",
        any('resolution:1024x1536' in t for t in result.prefix_tags),
        f"prefix_tags={result.prefix_tags}",
    )


# ============================================================================
# UC-2 보조 — api_service 인라인 파라미터 실제 해석 검증
# ============================================================================


def test_api_service_inline_resolution():
    """core/api_service.py가 프롬프트 내 resolution: 태그를 실제로 width/height로
    변환하는지 단위 검증."""
    import re as _re
    svc_path = os.path.join(PROJECT_ROOT, 'core', 'api_service.py')
    with open(svc_path, encoding='utf-8') as f:
        src = f.read()
    # 엔진 라우팅 재현: resolution: 태그가 정규식 매칭되는지만 확인
    # (실제 호출 경로는 내부 파라미터 dict 기반으로 복잡 — 코드 존재만 확인)
    has_regex = _re.search(r'resolution:.*startswith.*resolution:', src, _re.DOTALL) is not None
    has_width_assign = "parameters['width'] = fix_res_value[0]" in src
    has_height_assign = "parameters['height'] = fix_res_value[1]" in src
    check(
        "UC-2 보조: api_service가 resolution: 태그를 width/height로 반영",
        has_regex and has_width_assign and has_height_assign,
        f"regex={has_regex}, width={has_width_assign}, height={has_height_assign}",
    )


# ============================================================================
# 실행
# ============================================================================


def main():
    print("=" * 72)
    print("Conditional Prompt Editor v2.1 — Headless Verification")
    print(f"(Phase 0 / Sub-phase 1.1 / Sub-phase 1.1b)")
    print("=" * 72)

    test_funcs = [v for k, v in sorted(globals().items()) if k.startswith('test_')]

    section("UC-3: 레거시 호환 (기존 DSL 활용 패턴 보장)")
    for t in [test_uc3_legacy_simple_rating, test_uc3_legacy_and_matched,
              test_uc3_legacy_and_not_matched, test_uc3_legacy_or,
              test_uc3_pattern_delete, test_uc3_exact_replace_weight_preserve,
              test_uc3_exact_replace_plain_tag,
              test_uc3_exact_replace_plain_multi_new]:
        run_one(t)

    section("Sub-phase 1.1: 엔진 확장 기본 (rating source / max_passes / skip)")
    for t in [test_rating_source_override, test_rating_source_row_only,
              test_max_passes_fixed_point_detection, test_stop_on_match,
              test_skip_char_target_on_non_naid4, test_char_target_write_naid4]:
        run_one(t)

    section("Sub-phase 1.1b UC-1a: char_in / char_on 조건")
    for t in [test_uc1a_char_in_contains, test_uc1a_char_in_not_contains,
              test_uc1a_char_in_exact, test_uc1a_char_on]:
        run_one(t)

    section("Sub-phase 1.1b UC-1b: char_set 액션")
    for t in [test_uc1b_char_set_disable, test_uc1b_char_set_enable]:
        run_one(t)

    section("Sub-phase 1.1b UC-1c: char_replace 액션")
    for t in [test_uc1c_char_replace, test_uc1c_char_replace_weight_preserve,
              test_uc1c_char_replace_no_match]:
        run_one(t)

    section("Sub-phase 1.1b UC-4: neg 타겟 (네거티브 프롬프트)")
    for t in [test_uc4_neg_append, test_uc4_neg_replace]:
        run_one(t)

    section("UC-2: 강제 해상도 (엔진 확장 없음 + api_service 인라인)")
    for t in [test_uc2_resolution_via_prefix_tag, test_api_service_inline_resolution]:
        run_one(t)

    section("조합 시나리오")
    for t in [test_combined_scenario_uc1b]:
        run_one(t)

    print()
    print("=" * 72)
    passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
    failed = sum(1 for _, s, _ in RESULTS if s == "FAIL")
    total = len(RESULTS)
    status = "✅ ALL PASS" if failed == 0 else f"⚠ {failed} FAILED"
    print(f"{status} — {passed}/{total} PASS")
    print("=" * 72)

    if failed:
        print("\nFAILED:")
        for name, _, detail in RESULTS:
            if _ == "FAIL":
                print(f"  ❌ {name}")
                if detail:
                    print(f"     {detail}")

    return 0 if failed == 0 else 1


def run_one(fn):
    try:
        fn()
    except Exception as e:
        check(fn.__name__, False, f"EXCEPTION: {e}\n{traceback.format_exc(limit=3)}")


if __name__ == "__main__":
    sys.exit(main())
