"""RulePanel — 선택된 Rule 전체 편집 패널.

조건/액션 편집만 담당. 고급 옵션(kind / priority / name / enabled)은 UI 에서
제거되고 내부 필드로 왕복만 유지. raw kind 규칙은 레거시 DSL 형태로 로드될 때만
raw 편집기로 자동 스위칭.

공개 API:
    set_rule(Rule)
    get_rule() -> Rule
    set_rule_position(index, total)  # 요약 카드에 표시용
    set_rule_enabled(bool) / is_rule_enabled()
    get_summary_text() / get_brief_label()
    changed  # pyqtSignal
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from legacy_desktop.modules.conditional.block_model import (
    Action,
    ConditionNode,
    Rule,
    make_tag_leaf,
)
from legacy_desktop.modules.conditional.ui.char_slot_combo import (
    CharSlotComboBox,
    get_character_slots,
)
from legacy_desktop.modules.conditional.ui.chip_list_widget import ChipListWidget
from legacy_desktop.modules.conditional.ui.condition_editor import ConditionNodeEditor
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.theme import DARK_COLORS


_ACTION_KIND_ITEMS = (
    ("태그 추가", "append_list"),
    ("문장 끝에 붙이기", "append"),
    ("태그 교체", "replace"),
    ("캐릭터 사용 여부", "char_set"),
    ("캐릭터 태그 추가", "char_append"),
    ("캐릭터 태그 교체", "char_replace"),
)
_FIXED_TARGETS = ("prefix", "main", "postfix", "global_uc", "neg")
_CHAR_TARGET_KINDS = ("char", "uc")
_TARGET_ITEMS = (
    ("선행고정 뒤", "prefix"),
    ("메인 프롬프트", "main"),
    ("후행고정 뒤", "postfix"),
    ("공용 UC", "global_uc"),
    ("네거티브", "neg"),
    ("캐릭터 프롬프트", "char"),
    ("캐릭터 UC", "uc"),
)
_CHAR_STATE_ITEMS = (
    ("사용", "enabled"),
    ("사용 안 함", "disabled"),
)

# 175: 조건 영역 시각적 계층 — DARK_COLORS 의 bg_secondary/bg_tertiary 가
# 동일한 #2B2B2B 로 매핑되어 레이어 구분이 사라지는 문제를 방지하기 위한
# 로컬 팔레트. 루트(어둠) < 카드(보통) < 입력필드(가장 어둠)로 대비.
_PANEL_BG = "#1E1E1E"         # rule_panel 루트 배경
_CARD_BG = "#2D2D2D"          # 카드(액션 패널, 조건 편집기) 배경
_INPUT_BG = "#161616"         # 입력 필드 배경 (진짜 어둡게)
_CARD_BORDER = "#555555"      # 카드 테두리 (border_light 보다 약간 어둡게)
_INPUT_BORDER = "#444444"     # 입력 테두리

_VALID_KINDS = ("block", "raw")
_VALID_ACTION_KINDS = (
    "append_list", "append", "replace",
    "char_set", "char_replace", "char_append",
)


def _add_combo_items(combo: QComboBox, items) -> None:
    for text, value in items:
        combo.addItem(text, userData=value)


def _set_combo_value(combo: QComboBox, value: str, fallback: str) -> None:
    idx = combo.findData(value)
    if idx < 0:
        idx = combo.findData(fallback)
    if idx >= 0:
        combo.setCurrentIndex(idx)


def _combo_value(combo: QComboBox, fallback: str) -> str:
    value = combo.currentData()
    return value if isinstance(value, str) and value else fallback


class RulePanel(QWidget):
    """Rule 조건/액션 편집 패널. 3-pane 구조의 우측 pane."""

    changed = pyqtSignal()

    def __init__(
        self,
        rule: Optional[Rule] = None,
        parent: Optional[QWidget] = None,
        *,
        app_context=None,
    ):
        super().__init__(parent)
        # CharSlotComboBox 가 활성 슬롯 미리보기를 채울 때 사용. 없으면
        # fallback (1~10) 으로 동작.
        self._app_context = app_context
        # 숨김 필드 (UI 없이 roundtrip 만 유지)
        self._rule_kind: str = "block"
        self._rule_priority: int = 100
        self._rule_enabled: bool = True
        self._rule_name: str = ""
        self._rule_position: Optional[tuple[int, int]] = None
        self._build_ui()
        self.set_rule(rule or Rule())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_rule(self, rule: Rule) -> None:
        self._mute(True)
        try:
            self._rule_enabled = bool(rule.enabled)
            self._rule_name = rule.name or ""
            self._rule_priority = int(rule.priority)
            kind = rule.kind if rule.kind in _VALID_KINDS else "block"
            self._rule_kind = kind

            if kind == "raw":
                self._raw_edit.setPlainText(rule.raw_dsl or "")
            else:
                self._condition_editor.set_node(
                    rule.condition or make_tag_leaf("")
                )
                self._sync_action(rule.action or Action())
        finally:
            self._mute(False)
        self._update_visibility()
        self._update_summary()

    def get_rule(self) -> Rule:
        kind = self._rule_kind if self._rule_kind in _VALID_KINDS else "block"
        rule = Rule(
            kind=kind,
            name=self._rule_name,
            enabled=self._rule_enabled,
            priority=int(self._rule_priority),
        )
        if rule.kind == "raw":
            rule.raw_dsl = self._raw_edit.toPlainText()
            rule.condition = None
            rule.action = None
        else:
            rule.condition = self._condition_editor.get_node()
            rule.action = self._read_action()
        return rule

    def set_rule_position(self, index: Optional[int], total: int) -> None:
        self._rule_position = None if index is None else (index, total)
        self._update_summary()

    def set_rule_enabled(self, enabled: bool) -> None:
        self._rule_enabled = bool(enabled)
        self._update_summary()

    def is_rule_enabled(self) -> bool:
        return self._rule_enabled

    def get_summary_text(self) -> str:
        return self._summary_label.text().strip()

    def get_brief_label(self) -> str:
        rule = self.get_rule()
        if rule.kind == "raw":
            return "[고급][DSL]"
        cond = (
            "[묶음]"
            if rule.condition and rule.condition.kind == "group"
            else "[단일]"
        )
        action_map = {
            "append_list": "[추가]",
            "append": "[끝추가]",
            "replace": "[교체]",
            "char_set": "[캐릭터]",
            "char_replace": "[캐릭터교체]",
            "char_append": "[캐릭터추가]",
        }
        status = "[꺼짐] " if not rule.enabled else ""
        return (
            f"{status}{cond}"
            f"{action_map.get(rule.action.kind if rule.action else '', '[규칙]')}"
        )

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # 175 hotfix: 입력 스타일을 root stylesheet 에 포함시켜 cascade 방식으로
        # 적용. QComboBox 네이티브 스타일 overlay 문제 회피 (individual setStyleSheet
        # 은 Windows 에서 body 배경이 연해지는 증상).
        self.setStyleSheet(
            f"RulePanel {{"
            f"  background-color: {_PANEL_BG};"
            f"}}"
            f"QWidget {{"
            f"  color: {DARK_COLORS['text_primary']}; "
            f"  font-size: {get_scaled_font_size(17)}px;"
            f"}}"
            + self._input_style()
            + (
                f"QLabel {{"
                f"  border: none;"
                f"  background: transparent;"
                f"  font-size: {get_scaled_font_size(17)}px;"
                f"}}"
                f"QPushButton {{"
                f"  background-color: {DARK_COLORS['bg_tertiary']};"
                f"  color: {DARK_COLORS['text_primary']};"
                f"  border: 1px solid {_CARD_BORDER};"
                f"  border-radius: {get_scaled_size(4)}px;"
                f"  padding: {get_scaled_size(5)}px {get_scaled_size(12)}px;"
                f"  font-size: {get_scaled_font_size(17)}px;"
                f"}}"
                f"QPushButton:hover {{"
                f"  background-color: {DARK_COLORS['bg_hover']};"
                f"  border-color: {DARK_COLORS['border_light']};"
                f"}}"
                f"QPushButton:pressed {{"
                f"  background-color: {DARK_COLORS['bg_pressed']};"
                f"}}"
                f"QCheckBox {{"
                f"  font-size: {get_scaled_font_size(17)}px;"
                f"  spacing: {get_scaled_size(6)}px;"
                f"  color: {DARK_COLORS['text_primary']};"
                f"  background: transparent;"
                f"}}"
            )
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(
            get_scaled_size(8), get_scaled_size(8),
            get_scaled_size(8), get_scaled_size(8),
        )
        root.setSpacing(get_scaled_size(8))

        # 요약 라벨은 편집기 상단 intro 로 이관됨 (175 hotfix). 여기서는
        # get_summary_text() 호출부를 위해 내부 버퍼로만 유지.
        self._summary_label = QLabel("")
        self._summary_label.setVisible(False)

        # 175 5-pane: 조건/액션 을 각각 독립 뷰로 생성해 editor_window 가
        # 별도 컬럼으로 reparent 할 수 있게 한다. 각 뷰는 자체 스크롤 영역을
        # 소유하므로 묶음 조건의 child 가 많아져도 폼이 압축되지 않는다.
        self._condition_view = self._build_condition_view()
        self._action_view = self._build_action_view()

        # 호환 래퍼: 기존 테스트가 `_block_container.isVisibleTo(p)` 로 블록/raw
        # 토글을 확인하므로 유지. 표준 standalone 사용에서는 두 뷰가 이 래퍼
        # 안에 stack 되고, editor_window 5-pane 분리에서는 두 뷰가 외부 컬럼
        # 으로 reparent 되어 이 래퍼는 비어 있게 된다.
        self._block_container = QWidget()
        block_layout = QVBoxLayout(self._block_container)
        block_layout.setContentsMargins(0, 0, 0, 0)
        block_layout.setSpacing(get_scaled_size(10))
        block_layout.addWidget(self._condition_view, stretch=1)
        block_layout.addWidget(self._action_view, stretch=1)
        root.addWidget(self._block_container, stretch=1)

        self._raw_container = self._build_raw_container()
        root.addWidget(self._raw_container)

    def _build_condition_view(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("conditionViewCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(
            get_scaled_size(4), get_scaled_size(4),
            get_scaled_size(4), get_scaled_size(4),
        )
        layout.setSpacing(get_scaled_size(6))
        layout.addWidget(self._section_header("이 조건이 맞으면"))

        scroll = self._build_scroll_area()
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(get_scaled_size(6))
        self._condition_editor = ConditionNodeEditor()
        self._condition_editor.changed.connect(self._emit_changed)
        content_layout.addWidget(self._condition_editor)
        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, stretch=1)
        return frame

    def _build_action_view(self) -> QWidget:
        # 액션 폼은 고정된 몇 줄이므로 scroll 없이 content 자연 높이로 렌더.
        # 조건 영역과 달리 사용자 정의 중첩이 없기 때문이다.
        frame = QFrame()
        frame.setObjectName("actionViewCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(
            get_scaled_size(4), get_scaled_size(4),
            get_scaled_size(4), get_scaled_size(4),
        )
        layout.setSpacing(get_scaled_size(6))
        layout.addWidget(self._section_header("이렇게 바꾸기"))
        layout.addWidget(self._build_action_panel())
        layout.addStretch()
        return frame

    def _build_scroll_area(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        return scroll

    def _section_header(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            f"QLabel {{"
            f"  color: {DARK_COLORS['text_primary']};"
            f"  font-size: {get_scaled_font_size(18)}px;"
            f"  font-weight: bold;"
            f"  border-left: {get_scaled_size(3)}px solid"
            f"    {DARK_COLORS['accent_blue']};"
            f"  padding: {get_scaled_size(2)}px {get_scaled_size(10)}px;"
            f"  background: transparent;"
            f"}}"
        )
        return label

    def _build_action_panel(self) -> QWidget:
        container = QFrame()
        container.setObjectName("actionCard")
        container.setFrameShape(QFrame.Shape.StyledPanel)
        # 175 hotfix: editor_window 에서 action_view 가 reparent 되면 RulePanel
        # root stylesheet 의 input/label/checkbox 규칙 cascade 가 끊긴다. 카드
        # 자체에 입력 스타일 및 레이블/체크박스 규칙을 포함시켜 독립적으로
        # 렌더될 수 있게 한다.
        container.setStyleSheet(
            f"QFrame#actionCard {{"
            f"  background-color: {_CARD_BG};"
            f"  border: 1px solid {_CARD_BORDER};"
            f"  border-radius: {get_scaled_size(6)}px;"
            f"}}"
            + self._input_style()
            + (
                f"QLabel {{"
                f"  border: none;"
                f"  background: transparent;"
                f"  color: {DARK_COLORS['text_primary']};"
                f"  font-size: {get_scaled_font_size(17)}px;"
                f"}}"
                f"QCheckBox {{"
                f"  font-size: {get_scaled_font_size(17)}px;"
                f"  spacing: {get_scaled_size(6)}px;"
                f"  color: {DARK_COLORS['text_primary']};"
                f"  background: transparent;"
                f"}}"
            )
        )
        layout = QVBoxLayout(container)
        layout.setContentsMargins(
            get_scaled_size(10), get_scaled_size(10),
            get_scaled_size(10), get_scaled_size(10),
        )
        layout.setSpacing(get_scaled_size(8))

        top = QHBoxLayout()
        top.setSpacing(get_scaled_size(6))
        top.addWidget(QLabel("변경 방식:"))
        self._action_kind_combo = QComboBox()
        _add_combo_items(self._action_kind_combo, _ACTION_KIND_ITEMS)
        self._action_kind_combo.wheelEvent = lambda e: e.ignore()
        self._action_kind_combo.currentTextChanged.connect(
            self._on_action_kind_changed
        )
        top.addWidget(self._action_kind_combo)
        top.addStretch()
        layout.addLayout(top)

        self._target_row = self._build_target_row()
        layout.addWidget(self._target_row)
        self._tags_row = self._build_tags_row()
        layout.addWidget(self._tags_row)
        self._replace_row = self._build_replace_row()
        layout.addWidget(self._replace_row)
        self._func_char_row = self._build_func_char_row()
        layout.addWidget(self._func_char_row)
        return container

    def _build_target_row(self) -> QWidget:
        """적용 위치 행 — 2-line 레이아웃.

        Line 1 (상시): [레이블] [kind 콤보]
        Line 2 (`_target_slot_row`, char/uc 타겟 전용): [레이블] [슬롯 콤보] [체크박스]

        한 줄로 배치하면 한국어 레이블 폭 + slot combo min + 체크박스 폭 합이
        액션 pane 최소 폭(380px)을 초과하여 텍스트가 잘린다. 2줄로 분리해
        각 줄 내부에서 슬롯 콤보가 stretch 로 남는 공간을 흡수하도록 한다.
        """
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(get_scaled_size(4))

        # Line 1: 적용 위치 kind
        r1 = QHBoxLayout()
        r1.setContentsMargins(0, 0, 0, 0)
        r1.setSpacing(get_scaled_size(6))
        r1.addWidget(QLabel("적용 위치:"))
        self._target_kind_combo = QComboBox()
        _add_combo_items(self._target_kind_combo, _TARGET_ITEMS)
        self._target_kind_combo.wheelEvent = lambda e: e.ignore()
        # global_uc 는 런타임 스텁 → 드롭다운에서 숨김. legacy round-trip
        # 호환성을 위해 데이터 모델에는 남겨둔다.
        _hide_idx = self._target_kind_combo.findData("global_uc")
        if _hide_idx >= 0:
            self._target_kind_combo.view().setRowHidden(_hide_idx, True)
        self._target_kind_combo.currentTextChanged.connect(
            self._on_target_kind_changed
        )
        r1.addWidget(self._target_kind_combo, 1)  # stretch — pane 폭에 맞춤
        outer.addLayout(r1)

        # Line 2: 대상 슬롯 + 전체 모드 (char/uc 타겟 전용)
        self._target_slot_row = QWidget()
        r2 = QHBoxLayout(self._target_slot_row)
        r2.setContentsMargins(0, 0, 0, 0)
        r2.setSpacing(get_scaled_size(6))
        r2.addWidget(QLabel("대상 슬롯:"))
        # 캐릭터 슬롯 콤보 — 항목 자체가 1줄 미리보기 (예: "1: blue_hair").
        # 드롭다운 열면 showPopup 이 view 폭을 자동 확장해 전체 텍스트 표시.
        self._target_n_spin = CharSlotComboBox(
            lambda: get_character_slots(self._app_context)
        )
        self._target_n_spin.setValue(1)
        self._target_n_spin.currentIndexChanged.connect(self._emit_changed)
        r2.addWidget(self._target_n_spin, 1)  # stretch — 남는 공간 흡수

        self._target_wildcard_chk = QCheckBox("모든 활성 슬롯")
        self._target_wildcard_chk.stateChanged.connect(self._emit_changed)
        r2.addWidget(self._target_wildcard_chk)
        outer.addWidget(self._target_slot_row)
        return w

    def _build_tags_row(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(2))
        layout.addWidget(QLabel("추가할 태그:"))
        self._tags_chip = ChipListWidget(placeholder="태그 추가 (Enter)")
        self._tags_chip.tags_changed.connect(self._emit_changed)
        layout.addWidget(self._tags_chip)
        return w

    def _build_replace_row(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(4))

        old_row = QHBoxLayout()
        old_row.setSpacing(get_scaled_size(6))
        old_row.addWidget(QLabel("찾을 태그:"))
        self._replace_old_edit = QLineEdit()
        self._replace_old_edit.setPlaceholderText("예: __bad_tag__")
        self._replace_old_edit.textChanged.connect(self._emit_changed)
        old_row.addWidget(self._replace_old_edit, 1)
        layout.addLayout(old_row)

        layout.addWidget(QLabel("바꿀 태그:"))
        self._replace_new_chip = ChipListWidget(
            placeholder="교체 후 태그 추가"
        )
        self._replace_new_chip.tags_changed.connect(self._emit_changed)
        layout.addWidget(self._replace_new_chip)
        return w

    def _build_func_char_row(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(4))

        top = QHBoxLayout()
        top.setSpacing(get_scaled_size(6))
        top.addWidget(QLabel("대상 캐릭터"))
        # 캐릭터 슬롯 콤보 — char_set / char_replace / char_append 공통 대상.
        self._func_char_index_spin = CharSlotComboBox(
            lambda: get_character_slots(self._app_context)
        )
        self._func_char_index_spin.setValue(1)
        self._func_char_index_spin.currentIndexChanged.connect(
            self._emit_changed
        )
        top.addWidget(self._func_char_index_spin)

        # 상태 레이블 + 콤보 — 이전 구현은 QLabel 참조를 저장하지 않아
        # char_replace / char_append 모드에서도 "상태:" 가 계속 표시되는 버그.
        # 이제 label 을 필드로 보관해 _update_visibility 에서 함께 숨김.
        self._char_state_label = QLabel("상태:")
        top.addWidget(self._char_state_label)
        self._char_state_combo = QComboBox()
        _add_combo_items(self._char_state_combo, _CHAR_STATE_ITEMS)
        self._char_state_combo.wheelEvent = lambda e: e.ignore()
        self._char_state_combo.currentTextChanged.connect(self._emit_changed)
        top.addWidget(self._char_state_combo)
        top.addStretch()
        layout.addLayout(top)

        # "기존/새 태그" 줄 — char_replace 전용. 라벨도 참조 저장.
        repl_row = QHBoxLayout()
        repl_row.setSpacing(get_scaled_size(6))
        self._char_old_label = QLabel("기존 태그:")
        repl_row.addWidget(self._char_old_label)
        self._char_old_edit = QLineEdit()
        self._char_old_edit.textChanged.connect(self._emit_changed)
        repl_row.addWidget(self._char_old_edit, 1)
        self._char_new_label = QLabel("새 태그:")
        repl_row.addWidget(self._char_new_label)
        self._char_new_edit = QLineEdit()
        self._char_new_edit.textChanged.connect(self._emit_changed)
        repl_row.addWidget(self._char_new_edit, 1)
        layout.addLayout(repl_row)
        return w

    def _build_raw_container(self) -> QWidget:
        w = QWidget()
        # 175 hotfix: editor_window 에서 raw_container 가 reparent 되어도 스타일
        # 유지되도록 cascade root 를 여기에도 건다. (action_card 와 동일 이유)
        w.setStyleSheet(
            self._input_style()
            + (
                f"QLabel {{"
                f"  border: none;"
                f"  background: transparent;"
                f"  color: {DARK_COLORS['text_primary']};"
                f"  font-size: {get_scaled_font_size(17)}px;"
                f"}}"
            )
        )
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(4))
        layout.addWidget(QLabel("고급 DSL 직접 편집"))
        self._raw_edit = QTextEdit()
        self._raw_edit.setAcceptRichText(False)
        self._raw_edit.setPlaceholderText("(cond):action")
        self._raw_edit.textChanged.connect(self._emit_changed)
        self._raw_edit.setMinimumHeight(get_scaled_size(80))
        layout.addWidget(self._raw_edit)
        return w

    # ------------------------------------------------------------------
    # 내부 — sync/read/events
    # ------------------------------------------------------------------

    def _sync_action(self, action: Action) -> None:
        _set_combo_value(
            self._action_kind_combo,
            action.kind if action.kind in _VALID_ACTION_KINDS else "append_list",
            "append_list",
        )
        self._apply_target(action.target or "main")
        self._tags_chip.set_tags(list(action.tags or []))
        self._replace_old_edit.setText(action.old_tag or "")
        self._replace_new_chip.set_tags(list(action.new_tags or []))
        self._func_char_index_spin.setValue(
            max(1, int(action.char_index or 1))
        )
        _set_combo_value(
            self._char_state_combo,
            action.char_state if action.char_state in ("enabled", "disabled") else "enabled",
            "enabled",
        )
        self._char_old_edit.setText(action.char_old_tag or "")
        self._char_new_edit.setText(action.char_new_tag or "")

    def _apply_target(self, target: str) -> None:
        if target in _FIXED_TARGETS:
            _set_combo_value(self._target_kind_combo, target, "main")
            self._target_wildcard_chk.setChecked(False)
            self._target_n_spin.setValue(1)
            return
        if ":" in target:
            kind, _, rest = target.partition(":")
            if kind in _CHAR_TARGET_KINDS:
                _set_combo_value(self._target_kind_combo, kind, "main")
                if rest == "*":
                    self._target_wildcard_chk.setChecked(True)
                    self._target_n_spin.setValue(1)
                    return
                try:
                    self._target_n_spin.setValue(max(1, int(rest)))
                    self._target_wildcard_chk.setChecked(False)
                    return
                except ValueError:
                    pass
        # fallback
        _set_combo_value(self._target_kind_combo, "main", "main")
        self._target_wildcard_chk.setChecked(False)
        self._target_n_spin.setValue(1)

    def _compose_target(self) -> str:
        kind = _combo_value(self._target_kind_combo, "main")
        if kind in _FIXED_TARGETS:
            return kind
        if kind in _CHAR_TARGET_KINDS:
            if self._target_wildcard_chk.isChecked():
                return f"{kind}:*"
            return f"{kind}:{int(self._target_n_spin.value())}"
        return "main"

    def _read_action(self) -> Action:
        kind = _combo_value(self._action_kind_combo, "append_list")
        a = Action(
            kind=kind if kind in _VALID_ACTION_KINDS else "append_list"
        )
        if kind in ("append_list", "append"):
            a.target = self._compose_target()
            a.tags = self._tags_chip.get_tags()
        elif kind == "replace":
            a.old_tag = self._replace_old_edit.text().strip()
            a.new_tags = self._replace_new_chip.get_tags()
        elif kind == "char_set":
            a.char_index = int(self._func_char_index_spin.value())
            a.char_state = _combo_value(self._char_state_combo, "enabled")
        elif kind == "char_replace":
            a.char_index = int(self._func_char_index_spin.value())
            a.char_old_tag = self._char_old_edit.text().strip()
            a.char_new_tag = self._char_new_edit.text().strip()
        elif kind == "char_append":
            a.char_index = int(self._func_char_index_spin.value())
            a.tags = self._tags_chip.get_tags()
        return a

    def _update_visibility(self) -> None:
        is_block = self._rule_kind == "block"
        # 175 5-pane: editor_window 가 _condition_view / _action_view 를
        # 별도 컬럼으로 reparent 해도 토글이 동작하도록 두 뷰를 명시적으로
        # 토글. `_block_container` 는 reparent 이후 비어있지만 tests 호환을
        # 위해 가시성 플래그는 유지한다.
        self._block_container.setVisible(is_block)
        self._condition_view.setVisible(is_block)
        self._action_view.setVisible(is_block)
        self._raw_container.setVisible(not is_block)
        if not is_block:
            return
        ak = _combo_value(self._action_kind_combo, "append_list")
        # 적용 위치(target_row) 는 일반 prefix/main/postfix 대상 액션에서만.
        self._target_row.setVisible(ak in ("append_list", "append"))
        # 태그 리스트는 append/append_list + 신규 char_append 공용.
        self._tags_row.setVisible(
            ak in ("append_list", "append", "char_append")
        )
        self._replace_row.setVisible(ak == "replace")
        # char 계열 3종은 대상 캐릭터 슬롯이 필요 → func_char_row 공유.
        self._func_char_row.setVisible(
            ak in ("char_set", "char_replace", "char_append")
        )
        # target kind 에 따라 slot row 표시 (prefix/main/postfix 모드 전용).
        tk = _combo_value(self._target_kind_combo, "main")
        allow_char = tk in _CHAR_TARGET_KINDS
        self._target_slot_row.setVisible(allow_char)
        # 상태: char_set 전용 — 이전 버그(라벨 상시 표시) 수정.
        self._char_state_label.setVisible(ak == "char_set")
        self._char_state_combo.setVisible(ak == "char_set")
        # 기존/새 태그: char_replace 전용 — 라벨도 함께 숨김.
        self._char_old_label.setVisible(ak == "char_replace")
        self._char_old_edit.setVisible(ak == "char_replace")
        self._char_new_label.setVisible(ak == "char_replace")
        self._char_new_edit.setVisible(ak == "char_replace")

    def _on_action_kind_changed(self, _text: str) -> None:
        self._update_visibility()
        self._emit_changed()

    def _on_target_kind_changed(self, _text: str) -> None:
        self._update_visibility()
        self._emit_changed()

    def _emit_changed(self, *_args) -> None:
        self._update_summary()
        self.changed.emit()

    def _mute(self, muted: bool) -> None:
        widgets = [
            self._action_kind_combo,
            self._target_kind_combo, self._target_n_spin,
            self._target_wildcard_chk,
            self._tags_chip, self._replace_old_edit, self._replace_new_chip,
            self._func_char_index_spin, self._char_state_combo,
            self._char_old_edit, self._char_new_edit, self._raw_edit,
        ]
        for w in widgets:
            w.blockSignals(muted)

    def _set_kind_value(self, value: str) -> None:
        """외부/테스트 용 kind 전환. UI 위젯은 없으므로 내부 필드와 visibility 만 갱신."""
        if value not in _VALID_KINDS:
            value = "block"
        self._rule_kind = value
        self._update_visibility()
        self._update_summary()

    def _describe_target(self, target: str) -> str:
        mapping = {
            "prefix": "선행고정 뒤",
            "main": "메인 프롬프트",
            "postfix": "후행고정 뒤",
            "global_uc": "공용 UC",
            "neg": "네거티브",
        }
        if target in mapping:
            return mapping[target]
        if target == "char:*":
            return "모든 활성 캐릭터 프롬프트"
        if target == "uc:*":
            return "모든 활성 캐릭터 UC"
        if ":" in target:
            kind, _, index = target.partition(":")
            if kind == "char":
                return f"캐릭터 {index} 프롬프트"
            if kind == "uc":
                return f"캐릭터 {index} UC"
        return target or "메인 프롬프트"

    def _describe_condition(self, node: Optional[ConditionNode]) -> str:
        if node is None:
            return "조건 없음"
        if node.kind == "group":
            joiner = " 그리고 " if node.logical == "AND" else " 또는 "
            parts = [
                self._describe_condition(child)
                for child in (node.children or [])
            ]
            parts = [p for p in parts if p]
            if not parts:
                return "비어 있는 조건 묶음"
            return "(" + joiner.join(parts) + ")"
        if node.leaf_kind == "rating":
            text = f"등급이 {node.rating_value or 'e'}"
        elif node.leaf_kind == "char_in":
            mod = "포함"
            if node.char_tag_modifier == "exact":
                mod = "정확히 일치"
            elif node.char_tag_modifier == "not_contains":
                mod = "포함하지 않음"
            elif node.char_tag_modifier == "not_exact":
                mod = "정확히 일치하지 않음"
            text = (
                f"캐릭터 {node.char_index or 1} 안에 "
                f"'{node.char_tag_value or ''}' {mod}"
            )
        elif node.leaf_kind == "char_on":
            text = f"캐릭터 {node.char_index or 1} 슬롯이 켜져 있음"
        else:
            mod = "포함"
            if node.tag_modifier == "exact":
                mod = "정확히 일치"
            elif node.tag_modifier == "not_contains":
                mod = "포함하지 않음"
            elif node.tag_modifier == "not_exact":
                mod = "정확히 일치하지 않음"
            text = f"'{node.tag_value or ''}' {mod}"
        if node.negated:
            return f"{text} 아님"
        return text

    def _describe_action(self, action: Optional[Action]) -> str:
        if action is None:
            return "변경 없음"
        if action.kind in ("append_list", "append"):
            tags = ", ".join(action.tags or []) or "(태그 없음)"
            return f"{self._describe_target(action.target or 'main')}에 {tags} 추가"
        if action.kind == "replace":
            tags = ", ".join(action.new_tags or []) or "(태그 없음)"
            return f"'{action.old_tag or ''}'를 {tags}로 교체"
        if action.kind == "char_set":
            state = "사용" if action.char_state == "enabled" else "사용 안 함"
            return f"캐릭터 {action.char_index or 1}을 {state}"
        if action.kind == "char_replace":
            return (
                f"캐릭터 {action.char_index or 1}의 "
                f"'{action.char_old_tag or ''}'를 "
                f"'{action.char_new_tag or ''}'로 교체"
            )
        if action.kind == "char_append":
            tags = ", ".join(action.tags or []) or "(태그 없음)"
            return f"캐릭터 {action.char_index or 1} 프롬프트에 {tags} 추가"
        return action.kind or "변경 없음"

    def _update_summary(self) -> None:
        rule = self.get_rule()
        order_prefix = ""
        if self._rule_position is not None:
            index, total = self._rule_position
            order_prefix = f"[{index + 1}/{max(total, 1)}] "
        if not rule.enabled:
            self._summary_label.setText(
                f"{order_prefix}이 규칙은 현재 꺼져 있습니다."
            )
            return
        if rule.kind == "raw":
            text = rule.raw_dsl.strip() or "직접 입력할 DSL 이 비어 있습니다."
            self._summary_label.setText(
                f"{order_prefix}고급 DSL 직접 실행: {text}"
            )
            return
        condition_text = self._describe_condition(rule.condition)
        action_text = self._describe_action(rule.action)
        self._summary_label.setText(
            f"{order_prefix}{condition_text}일 때 {action_text}"
        )

    def _input_style(self) -> str:
        """condition_editor 와 동일 규약. 자세한 설명은 condition_editor 참조."""
        base = (
            f"  background-color: {_INPUT_BG};"
            f"  color: {DARK_COLORS['text_primary']};"
            f"  border: 1px solid {_INPUT_BORDER};"
            f"  border-radius: {get_scaled_size(4)}px;"
            f"  padding: {get_scaled_size(6)}px {get_scaled_size(8)}px;"
            f"  font-size: {get_scaled_font_size(17)}px;"
            f"  selection-background-color: {DARK_COLORS['accent_blue']};"
        )
        return (
            f"QLineEdit {{{base}}}"
            f"QComboBox {{{base}}}"
            f"QComboBox:hover {{ border-color: {DARK_COLORS['border_light']}; }}"
            f"QComboBox::drop-down {{"
            f"  subcontrol-origin: padding;"
            f"  subcontrol-position: right center;"
            f"  width: {get_scaled_size(20)}px;"
            f"  border: none;"
            f"  background: transparent;"
            f"}}"
            f"QComboBox QAbstractItemView {{"
            f"  background-color: {_INPUT_BG};"
            f"  color: {DARK_COLORS['text_primary']};"
            f"  border: 1px solid {_INPUT_BORDER};"
            f"  selection-background-color: {DARK_COLORS['accent_blue']};"
            f"  outline: 0;"
            f"}}"
            f"QSpinBox {{{base}}}"
            f"QSpinBox::up-button, QSpinBox::down-button {{"
            f"  background: transparent;"
            f"  border: none;"
            f"  width: {get_scaled_size(14)}px;"
            f"}}"
            f"QTextEdit {{{base}}}"
        )
