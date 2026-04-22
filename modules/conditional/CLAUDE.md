# CLAUDE.md — modules/conditional/

> 조건부 프롬프트 편집기 v2.1 — 블록 기반 룰 편집 UI + DSL 왕복 + 런타임 복원 인프라.
>
> 런타임 훅(`PromptListModifierModule`)은 `modules/conditional_prompt_module.py`(상위) 에 있고, 본 패키지는 v2 전용의 데이터 모델 / 파서 / 직렬화 / 편집기 UI / 스냅샷 복원을 담당.

---

## 디렉터리 구조 & 의존

```
modules/conditional/
├── block_model.py         # ConditionNode / Action / Rule / RuleBook (dataclass)
├── dsl_parser.py          # DSL text → RuleBook 파싱
├── dsl_serializer.py      # RuleBook / Rule → DSL text 직렬화
├── preset_io.py           # Preset JSON 저장/로드, 번들 프리셋 loader
├── build_bundled_presets.py  # 번들 프리셋 빌드 스크립트 (개발용)
├── runtime_snapshot.py    # CharStateSnapshot (179 SDLC) — 복원 인프라
├── editor_window.py       # RuleEditorWindow (QDialog) — 편집기 5-pane 컨테이너
└── ui/
    ├── preset_panel.py         # 좌측 1열 — 프리셋 목록 / 불러오기·저장
    ├── rule_list_panel.py      # 좌측 2열 — 규칙 목록 (QListWidget + 커스텀 델리게이트)
    ├── rule_panel.py           # 우측 3/4열 모델 — 조건/액션 편집 조율
    ├── condition_editor.py     # 3열 — ConditionNodeEditor (leaf/group 재귀)
    ├── chip_list_widget.py     # 태그 리스트 chip 입력
    └── char_slot_combo.py      # 캐릭터 슬롯 인덱스 콤보 (QSpinBox 대체)
```

**의존**: `interfaces/` · `ui/` (theme, scaling) · `modules/conditional_prompt_module.py` (런타임 소비자)
**본 패키지 소비자**: `modules/conditional_prompt_module.py` (런타임 훅), 편집기는 `RuleEditorWindow` lazy 생성

---

## 데이터 모델 (`block_model.py`)

### `Rule` — 단일 규칙

```python
@dataclass
class Rule:
    id: str                          # UUID
    kind: Literal["block", "raw"]    # block=조건/액션 편집, raw=DSL 직접 입력 (legacy)
    enabled: bool = True
    priority: int = 100              # 낮을수록 먼저 (현재 UI 미노출, 내부 필드로만)
    name: str = ""                   # 사용자 레이블 (UI 미노출)
    condition: Optional[ConditionNode] = None
    action: Optional[Action] = None
    raw_dsl: str = ""                # kind="raw" 인 경우 legacy DSL 라인
```

### `ConditionNode` — 조건 트리 (leaf/group 재귀)

```python
@dataclass
class ConditionNode:
    kind: Literal["leaf", "group"] = "leaf"

    # leaf 공통
    leaf_kind: Optional[Literal["tag", "rating", "char_in", "char_on"]] = None
    negated: bool = False                  # rating / char_on 에만 의미 (tag/char_in 은 modifier 로 대체)

    # leaf: tag / char_in
    tag_value: str = ""
    tag_modifier: Literal["contains", "exact", "not_contains", "not_exact"] = "contains"
    char_tag_value: str = ""               # char_in 전용
    char_tag_modifier: TagModifier = "contains"

    # leaf: rating
    rating_value: Literal["e", "q", "s", "g"] = ""
    rating_source: Literal["auto", "row", "override", "bayes"] = "auto"

    # leaf: char_in / char_on
    char_index: Optional[int] = None       # 1-based (DSL 과 일치)

    # group
    logical: Optional[Literal["AND", "OR"]] = None
    children: List["ConditionNode"] = field(default_factory=list)
```

**NOT 정책**: `negated` 필드는 **`rating`/`char_on` leaf 에만 유효**. `tag`/`char_in` 은 `not_contains`/`not_exact` modifier 로 이미 부정 가능 → UI 에서 NOT 체크박스 조건부 숨김(`condition_editor.py`).

### `Action` — 단일 조작

```python
@dataclass
class Action:
    kind: Literal["append_list", "append", "replace", "char_set", "char_replace"]
    target: str = "main"  # prefix|main|postfix|char:N|uc:N|char:*|uc:*|neg|global_uc
    preserve_weight: bool = True
    # kind 별 필드: tags / old_tag / new_tags / char_index / char_state / char_old_tag / char_new_tag
```

**주의**: `target="global_uc"` 는 런타임 스텁 (`_write_global_uc_target` no-op). 편집기 콤보에서는 숨김 처리 (legacy 프리셋 round-trip 만 보존).

### `RuleBook`

```python
@dataclass
class RuleBook:
    rules: List[Rule]
    max_passes: int = 1          # 룰 리스트 반복 적용 횟수 (진동 감지 시 조기 종료)
    stop_on_match: bool = False  # 한 규칙이라도 매칭되면 현재 패스 중단
```

---

## DSL 문법 (`dsl_parser.py` / `dsl_serializer.py`)

```
<condition>:<action>
```

### 조건 expressions

- **빈 조건(항상 참)**: `()`
- **단일 태그 포함**: `tag` / `(tag)` — substring match
- **정확 일치**: `*tag`
- **부정**: `~tag` (포함 안 함), `~!tag` (정확히 일치 안 함)
- **그룹 AND**: `a & b`, `(a & b)`
- **그룹 OR**: `a | b`, `(a | b)`
- **rating**: `e`/`q`/`s`/`g` 또는 `rating(e, source=override)`
- **char_in**: `char_in(1, smile)`, `char_in(2, *smile)`, `~char_in(1, smile)`
- **char_on**: `char_on(1)`, `~char_on(1)`

### 액션 expressions

- **태그 리스트 추가**: `main+=tag1, tag2` / `prefix+=tag` / `postfix+=tag`
- **문장 끝 append**: `main+tag` (공백 결합, 레거시 용)
- **태그 교체**: `main=new_tag` (전체 교체) / `old_tag=new_tag` (부분 치환)
- **캐릭터 활성/비활성**: `char_set(N, enabled|disabled)`
- **캐릭터 내부 태그 치환**: `char_replace(N, old, new)`
- **캐릭터 슬롯 타겟**: `char:N+=tag` / `uc:N=new_uc` / `char:*+=tag` (모든 활성 슬롯)

### 예

```
(1boy):char_set(2, disabled)
(rating=e):neg+=nsfw, explicit
(char_in(1, smile)):char_replace(1, smile, grin)
():main+=masterpiece, best quality
```

**조건 파싱 함정**: `rating=e` 같이 `=` 를 포함한 조건식과 액션 `target=value` 가 어휘 상 겹칠 수 있음. 파서가 최상위 `:` 를 기준으로 split 하므로 조건 내부의 `:` 는 escape 필요 (`char_in(1, \:tag)`).

---

## 런타임 통합 (`modules/conditional_prompt_module.py`)

### 훅 등록

```python
# conditional_prompt_module.py:680-685
def get_pipeline_hook_info(self):
    return {
        'target_pipeline': 'PromptProcessor',
        'hook_point': 'after_wildcard',
        'priority': 2
    }
```

### 실행 경로

`execute_pipeline_hook(context)` → `_apply_rules(context, rules_text, logs, max_passes, stop_on_match)` → `_parse_rules` → 룰 순회 → 액션 디스패치(`_write_prefix_main_postfix`/`_write_char_uc_target`/`_execute_char_set`/`_execute_char_replace`/`_write_neg_target`/...).

**v2 DSL 저장소**: `_rules_v2_dsl: str` (활성 모드="v2"). 레거시는 `rules_textedit.toPlainText()`. `_active_rules_text()` 가 모드에 따라 한쪽 선택.

**cond_override**: Shared Server Mode 에서 `app_context.session_cond_override` 가 세팅되면 enable_checkbox 무시하고 override 의 rules 사용.

### skip 카운터

인덱스 범위 밖 슬롯·모드 불일치·매칭 실패 등의 non-fatal 실패는 `_record_skip(target, reason)` 으로 누적 → `_flush_skip_logs(logs)` 가 최종 로그에 `⚠ Skip: target (reason) - N건` 형태로 출력. 편집기 저장 시 사전 경고는 **의도적으로 추가하지 않음** — 런타임이 일관되게 skip 처리.

---

## 캐릭터 액션 복원 시스템 (179 SDLC)

### 문제

조건부 액션 중 `char_set` 은 `CharacterModule.set_character_active()` 를 통해 **widget 의 active_checkbox 를 직접 토글** → 영구 변경. `char_replace` / `target=char:N` 은 `modifiable_clone` 만 수정하지만 다음 generate 에서 `process_and_update_view()` 가 호출되지 않으면 stale 누적.

### 해결 — `CharStateSnapshot` (`runtime_snapshot.py`)

매 generate 사이클마다 변경 직전 슬롯 상태(active_checkbox + prompt_textbox + uc_textbox + modifiable_clone 엔트리)를 idempotent 캡처, generate 종료 시 일괄 복원.

```python
# conditional_prompt_module.py 내부 사용 패턴
def _apply_rules(...):
    # 새 사이클 진입 — 이전 사이클 누수 복원(R1 fallback) 후 fresh
    if self._char_snapshot is not None and not self._char_snapshot.is_empty():
        self._char_snapshot.restore()
    self._char_snapshot = CharStateSnapshot(self._get_character_module())
    # ... 룰 평가 / 액션 디스패치 ...

def _execute_char_set(self, char_idx, state):
    # setter 호출 전 capture (idempotent)
    if self._char_snapshot is not None:
        self._char_snapshot.capture(char_idx)
    setter(char_idx, state == 'enabled')
```

### Ground Truth 계약

```
Cycle N:
  ground truth → 조건 평가 → mutation → API 호출 → 복원 → ground truth
Cycle N+1:
  ground truth (Cycle N 의 흔적 0) → 조건 fresh 평가 → ...
```

**원칙**: 사용자가 GUI 에서 설정한 슬롯 상태 = **단일 ground truth**. 조건부 룰 효과는 매 사이클 휘발적. 사이클 간 누적 없음. 조건 평가는 항상 원본 기반.

→ char 계열 모든 액션(`char_set`/`char_replace`/`char:N`/`uc:N`)이 **ephemeral** 로 통일됨. 사용자가 mutation 상태를 영구화하려면 widget 수동 조작 필요.

### 복원 트리거

```python
# conditional_prompt_module.py:2124 - initialize_with_context
app_context.subscribe("generation_finished", self._on_generate_done)
app_context.subscribe("generation_error", self._on_generate_done)
# M1 가드: _gen_event_subscribed 플래그로 재초기화 시 중복 등록 방지
```

**R1 fallback**: generation_finished 누락 경로 (silent generate, 이벤트 미라우팅 등) 에서 snapshot 이 남으면, **다음 generate 의 `_apply_rules` 진입 시** 강제 복원 후 fresh 시작. 설계 문서 §11.

### 신규 char 액션 추가 시 체크리스트

1. `_execute_*` 메서드 내에서 widget/clone 수정 **직전** `self._char_snapshot.capture(char_idx)` 호출
2. `char:*` 같이 다중 슬롯을 영향 주는 경우 루프 내에서 슬롯별 capture
3. capture 는 idempotent 라 여러 번 호출해도 첫 상태만 보존
4. 단위 테스트: `tests/conditional/test_char_action_restore.py` 에 capture/restore 라운드트립 추가

---

## UI 레이어

### `RuleEditorWindow` (`editor_window.py`) — 5-pane 레이아웃

```
[프리셋 목록] [규칙 목록] [조건 편집]    [액션 + DSL 미리보기]
  (고정 폭)   (고정 폭)   (stretch)        (stretch)
```

**특이점**: `RulePanel` 은 모델/시그널 조율만. 시각적으로는 숨기고 내부 `_condition_view` / `_action_view` / `_raw_container` 를 외부 컬럼으로 **reparent**. reparent 된 자식에 `_input_style()` cascade 가 끊기므로 `_build_action_panel` 의 actionCard 와 `_build_raw_container` 는 **자체 stylesheet 에 _input_style() 을 명시 포함**.

**DSL 미리보기**: 선택된 룰 하나만 `serialize_rule(rule)` 로 렌더. 고급 DSL 직접 편집과 같은 스타일(20px font, `#161616` 배경).

**더티 가드**: 편집 중인 내용 버려질 위험이 있는 동작(프리셋 로드/삭제/닫기 등) 전에 `_ask_dirty_choice` 모달. "적용 후 계속" / "변경 버림" / "취소" 3지선다.

**다이얼로그 다크 스타일**: root stylesheet 에 QMessageBox / QInputDialog 규칙 cascade. QDialog 배경 규칙이 자식 다이얼로그에 전파되는 것을 활용.

### `RuleListPanel` (`ui/rule_list_panel.py`) — 커스텀 델리게이트

`QListWidget + RuleItemDelegate`. 아이템 데이터는 dict 로 UserRole 에 저장:

```python
{
    "enabled": bool,
    "kind_color": "#RRGGBB", "kind_label": "단일|묶음|고급",
    "action_color": "#RRGGBB", "action_label": "추가|교체|DSL|...",
    "detail": "요약 텍스트",
    "order": int,
}
```

**페인팅 요소**: 상태 점(성공/비활성 색 8px 원) + 종류 배지 + 액션 배지 + elide 디테일 + 우측 `#N` 인덱스. 비활성 룰은 배지 alpha 140 / 텍스트 muted.

**중요**: `::item:selected` 스타일시트 규칙을 **제거**해야 함 (델리게이트가 직접 selection bg 를 페인팅하는데, stylesheet 의 selection 색이 먼저 덧칠돼 배지를 가림).

### `ConditionNodeEditor` (`ui/condition_editor.py`) — 재귀 leaf/group 에디터

모든 위젯을 **일괄 생성 후 visibility 토글**로 kind 전환. set_node/get_node 왕복이 안정적 (rebuild 없음). group 의 자식 editor 는 재귀 생성, 삭제 요청은 `request_delete` 시그널로 부모에 전달.

### `CharSlotComboBox` (`ui/char_slot_combo.py`) — 슬롯 미리보기 콤보

QSpinBox 대체. 드롭다운 열 때마다 `CharacterModule.character_widgets` 조회해 `"1: hatsune miku, smile"` / `"3: (비어있음)"` / `"2: 1girl · 비활성"` 형태 항목 표시. 저장된 슬롯 번호가 범위 밖이면 `(슬롯 없음)` 임시 항목 추가로 round-trip 보존.

```python
self._target_n_spin = CharSlotComboBox(
    lambda: get_character_slots(self._app_context)
)
self._target_n_spin.setValue(1)  # 기존 QSpinBox API 호환
```

### Input 스타일 cascade

input 위젯(QComboBox/QLineEdit/QSpinBox/QTextEdit)에 `setStyleSheet` 을 **개별로** 걸면 Qt WindowsVista 네이티브 스타일이 QComboBox body 에 overlay 로 덧칠돼 배경이 연해지는 증상 발생. → **root widget 의 stylesheet 에 `QLineEdit {...} QComboBox {...} ...` selector 로 cascade** 시키는 방식 사용.

세부는 `rule_panel._input_style()` 참조. reparent 되는 섹션은 자체 stylesheet 로 반드시 포함해야 함.

---

## Preset I/O (`preset_io.py`)

### 포맷

프리셋 JSON: `{"version": int, "name": str, "rules": [...], "max_passes": int, "stop_on_match": bool}`

### 번들 프리셋

`data/conditional_presets/*.json` — 기본 제공 세트. `build_bundled_presets.py` 로 생성.

### 호환성

- Rule 의 필드 중 UI 에 노출 안 된 것(priority/kind/name)은 round-trip 용 내부 저장
- Action 의 target 중 드롭다운에서 숨겨진 항목(`global_uc`)은 로드 시 findData 로 매칭 (콤보에 hidden 항목으로 보존)

---

## 테스트

```
tests/conditional/
├── test_engine_headless.py        # 엔진 단위 (26/26) — 룰 평가 / 액션 디스패치 / 파서
├── test_dsl_parser.py             # DSL 파싱 세부
├── test_block_serializer.py       # 직렬화 왕복
├── test_preset_io.py              # 프리셋 JSON 호환성
├── test_bundled_presets.py        # 번들 프리셋 파싱 검증
├── test_char_snapshot.py          # CharStateSnapshot 단위 (10/10)
├── test_char_action_restore.py    # 복원 통합 (11/11) — capture/restore 라운드트립
├── test_rule_panel.py             # UI — 왕복 / 시그널
├── test_rule_list_panel.py        # UI — 델리게이트 / 선택 동기화
├── test_condition_editor.py       # UI — 재귀 노드 편집
├── test_preset_panel.py           # UI — 프리셋 목록
├── test_editor_window.py          # UI — 5-pane 통합
├── test_mode_toggle.py            # legacy ↔ v2 편집기 모드 전환
├── test_chip_list_widget.py       # chip UI
└── test_hotfix_17.py              # 과거 핫픽스 회귀
```

**실행**: `python tests/conditional/test_*.py` (직접 실행 패턴, pytest 아님)

**Unicode 주의**: Windows 콘솔 기본 cp949 → 이모지/em-dash 가 포함된 print 는 `PYTHONIOENCODING=utf-8` 설정 필요.

---

## 주요 함정 / 주의사항

### 1. `widget.wheelEvent = lambda e: e.ignore()` 패턴

콤보박스/스핀박스는 프로젝트 관례대로 휠 스크롤 차단 필수. 슬롯 선택 콤보/조건 kind 콤보 등 모든 선택 위젯에 적용. 관례 출처: `ui/interactive/CLAUDE.md:190`.

### 2. `setStyleSheet` cascade vs per-widget

QComboBox body 배경은 per-widget stylesheet 에서 Qt native style 이 overlay 로 덧칠함. root stylesheet cascade 방식으로만 일관된 배경 색 유지 가능.

### 3. Widget reparenting 시 스타일 cascade 끊김

`RulePanel._action_view` / `_raw_container` 가 `editor_window` 의 다른 컬럼으로 reparent 되면 RulePanel 의 root stylesheet cascade 가 끊김. reparent 되는 섹션은 **자체 stylesheet 에 `_input_style()` 을 명시 포함** 해야 input 위젯 다크 테마 유지.

### 4. DSL syntax 실수

- `():char_set(N, state)` 처럼 **조건은 괄호**, `:` 로 조건/액션 구분
- `true =>` 같은 다른 DSL 문법은 지원 안 함 (파서가 조용히 룰 0개 반환 → 액션 실행 안 됨)
- **테스트 작성 시 주의**: 잘못된 syntax 는 경고 없이 룰 무시 → 테스트가 false negative 로 통과

### 5. Character 슬롯 인덱스

- DSL/Action 은 **1-based** (`char_set(1, ...)` = 첫 번째 캐릭터)
- Python API (`character_widgets[0]`, `set_character_active(0, ...)`) 는 **0-based**
- `_execute_char_*` 내부에서 `char_idx` 는 이미 0-based 로 변환된 값. `{char_idx + 1}` 로 로그 출력

### 6. 조건부 훅은 `after_wildcard` 에 등록

`post_processing` 이 아닌 `after_wildcard` — 와일드카드 확장 후에 실행되므로 룰의 태그 비교 대상이 확장된 실제 태그. 신규 조건 훅 추가 시 hook_point 일관성 유지.

### 7. Snapshot 은 main thread 한정

Qt 이벤트 루프 단일 스레드라 race 없음. 다만 generate API 호출은 QThread 워커라, generation_finished 이벤트는 signal 을 통해 main thread 로 마샬링됨. snapshot 조작은 전부 main thread.

---

## 설계 문서 (로컬, `*.md` gitignore)

- `docs/CONDITIONAL_PROMPT_V2_IMPLEMENTATION_PLAN.md` — Phase A~D 전체 구현 계획
- `docs/HANDOFF_CONDITIONAL_PROMPT_V2_2026_04_21.md` — 3인 에이전트 합의 설계 핸드오프
- `docs/CONDITIONAL_CHAR_ACTION_RESTORATION.md` — 179 SDLC 설계 (B안 스냅샷 + Ground Truth 계약)

---

## 참고

- `modules/CLAUDE.md` — 상위 모듈 가이드 (BaseMiddleModule / ModeAwareModule / 파이프라인 훅)
- `core/CLAUDE.md` — PromptProcessor / AppContext 이벤트 / GenerationController
- `ui/CLAUDE.md` — 테마 / 스케일링 / CollapsibleBox
