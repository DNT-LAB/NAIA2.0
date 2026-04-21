"""조건부 프롬프트 편집기 창 (Sub-phase 1.4e).

2-pane 레이아웃:
- 좌측(40%): PresetPanel — 프리셋 + 엔진 옵션 + 규칙 리스트
- 우측(60%): RulePanel — 선택된 규칙 편집

RuleBook 을 소유하며 사용자 편집을 조율한다. Apply 시 DSL 직렬화 후 모듈의
`rules_textedit` 에 주입 + `set_engine_options` + 활성 프리셋 기록. 닫기 시
반영 없음(기존 DSL 유지).

편집기는 열릴 때 모듈의 현재 DSL 을 `parse_rulebook` 로 복원한다. 파싱 실패
규칙은 `Rule(kind="raw")` 로 보존되어 UI 에도 raw 모드로 표시.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from modules.conditional.block_model import (
    Action,
    Rule,
    RuleBook,
    make_tag_leaf,
)
from modules.conditional.dsl_parser import parse_rulebook
from modules.conditional.dsl_serializer import serialize_rulebook
from modules.conditional.preset_io import (
    PresetStorage,
    get_default_storage,
)
from modules.conditional.ui.preset_panel import PresetPanel
from modules.conditional.ui.rule_panel import RulePanel
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.theme import DARK_COLORS, get_dynamic_styles


class RuleEditorWindow(QDialog):
    """2-pane 블록 편집 창. 비모달 / 단일 인스턴스."""

    rules_applied = pyqtSignal(str)  # Apply 시 DSL 본문 송신 (옵저버 용)

    def __init__(
        self,
        app_context,
        module,
        parent=None,
        *,
        storage: Optional[PresetStorage] = None,
    ):
        super().__init__(parent)
        self.app_context = app_context
        self.module = module
        self._storage = storage if storage is not None else get_default_storage()

        # 상태
        self._book: RuleBook = RuleBook()
        self._active_preset_name: Optional[str] = None
        self._current_rule_id: Optional[str] = None
        self._dirty: bool = False
        # 다이얼로그 없는 경로(테스트/자동화)에서의 기본 선택지.
        # "apply"(저장 후 닫기) / "discard"(변경 버림) / "cancel"(중단).
        self._auto_dirty_choice: Optional[str] = None

        self.setWindowTitle("조건부 프롬프트 편집기")
        self.setMinimumSize(get_scaled_size(1000), get_scaled_size(640))
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setStyleSheet(
            f"QDialog {{ background-color: {DARK_COLORS['bg_primary']}; }}"
        )

        self._build_ui()
        self._connect_signals()
        self.load_current_rules()
        self._refresh_preset_list()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        dynamic_styles = get_dynamic_styles()
        root = QVBoxLayout(self)
        margin = get_scaled_size(12)
        root.setContentsMargins(margin, margin, margin, margin)
        root.setSpacing(get_scaled_size(8))

        root.addLayout(self._build_header_row())

        # 2-pane
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        self._preset_panel = PresetPanel()
        splitter.addWidget(self._preset_panel)

        self._rule_panel = RulePanel()
        splitter.addWidget(self._rule_panel)

        # 40/60 — stretch factor
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)
        splitter.setSizes([get_scaled_size(400), get_scaled_size(600)])
        root.addWidget(splitter, stretch=1)

        root.addLayout(self._build_button_row(dynamic_styles))

    def _build_header_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(get_scaled_size(8))

        title = QLabel("🔀 조건부 프롬프트 편집기")
        title.setStyleSheet(
            f"color: {DARK_COLORS['text_primary']};"
            f" font-size: {get_scaled_font_size(18)}px;"
            f" font-weight: bold;"
        )
        row.addWidget(title)
        row.addStretch()

        self._active_preset_label = QLabel("")
        self._active_preset_label.setStyleSheet(
            f"color: {DARK_COLORS['text_secondary']};"
            f" font-size: {get_scaled_font_size(12)}px;"
        )
        row.addWidget(self._active_preset_label)
        return row

    def _build_button_row(self, dynamic_styles) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(get_scaled_size(6))

        reload_btn = QPushButton("🔄 현재 DSL 다시 불러오기")
        reload_btn.setStyleSheet(dynamic_styles['secondary_button'])
        reload_btn.clicked.connect(self.load_current_rules)
        row.addWidget(reload_btn)

        row.addStretch()

        apply_btn = QPushButton("✔ 모듈에 적용")
        apply_btn.setStyleSheet(dynamic_styles['primary_button'])
        apply_btn.clicked.connect(self._on_apply)
        row.addWidget(apply_btn)

        close_btn = QPushButton("닫기")
        close_btn.setStyleSheet(dynamic_styles['secondary_button'])
        close_btn.clicked.connect(self.close)
        row.addWidget(close_btn)
        return row

    # ------------------------------------------------------------------
    # 시그널 배선
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        p = self._preset_panel
        p.preset_load_requested.connect(self._on_preset_load)
        p.preset_save_requested.connect(self._on_preset_save)
        p.preset_delete_requested.connect(self._on_preset_delete)
        p.rule_selected.connect(self._on_rule_selected)
        p.rule_add_requested.connect(self._on_rule_add)
        p.rule_delete_requested.connect(self._on_rule_delete)
        p.engine_options_changed.connect(self._on_engine_options_changed)

        self._rule_panel.changed.connect(self._on_rule_panel_changed)

    # ------------------------------------------------------------------
    # 초기화/갱신
    # ------------------------------------------------------------------

    def load_current_rules(self) -> None:
        """모듈의 rules_textedit → RuleBook 으로 복원."""
        if not self._confirm_discard_if_dirty("현재 DSL 다시 불러오기"):
            return
        self._reload_from_module()

    def _reload_from_module(self) -> None:
        """dirty 체크 없이 모듈의 v2 DSL 을 읽어 _book 재구성.

        174 hotfix (FR-02): 편집기는 _rules_v2_dsl(`get_v2_dsl`) 만 파싱한다.
        레거시 DSL 은 자동 변환되지 않는다 — 사용자가 "레거시 → 신규 변환"
        버튼을 명시적으로 누를 때만 import.
        """
        text = ""
        if self.module is not None:
            if hasattr(self.module, 'get_v2_dsl'):
                text = self.module.get_v2_dsl() or ""
            else:
                # 하위 호환: 구버전 모듈은 rules_textedit 사용
                rules_textedit = getattr(self.module, 'rules_textedit', None)
                if rules_textedit is not None:
                    text = rules_textedit.toPlainText() or ""
        self._book = parse_rulebook(text)
        # 엔진 옵션은 모듈 현재값에서 가져오기 (프리셋 로드 시 덮어써짐)
        if self.module is not None and hasattr(
            self.module, 'get_engine_options'
        ):
            opts = self.module.get_engine_options()
            self._book.max_passes = int(opts.get('max_passes', 1))
            self._book.stop_on_match = bool(opts.get('stop_on_match', False))
        self._book.rules.sort(key=lambda r: r.priority)
        self._current_rule_id = None
        self._preset_panel.set_rulebook(self._book)
        self._rule_panel.set_rule(self._empty_rule())
        self._update_active_preset_label()
        self._set_dirty(False)

    def _refresh_preset_list(self) -> None:
        self._preset_panel.set_presets(self._storage.list_all())

    def _refresh_rule_list_preserving_selection(self) -> None:
        self._book.rules.sort(key=lambda r: r.priority)
        self._preset_panel.set_rulebook(self._book)
        if self._current_rule_id:
            for i, r in enumerate(self._book.rules):
                if r.id == self._current_rule_id:
                    self._preset_panel.set_selected_rule(i)
                    return
        self._preset_panel.set_selected_rule(-1)

    def _empty_rule(self) -> Rule:
        return Rule(
            kind="block",
            condition=make_tag_leaf(""),
            action=Action(kind="append_list", target="main", tags=[]),
        )

    # ------------------------------------------------------------------
    # 프리셋 핸들러
    # ------------------------------------------------------------------

    def _on_preset_load(self, name: str) -> None:
        if not self._confirm_discard_if_dirty(f"프리셋 '{name}' 로드"):
            return
        if not self._perform_load(name):
            QMessageBox.warning(
                self, "프리셋 로드", f"프리셋을 찾을 수 없습니다: {name}"
            )

    def _perform_load(self, name: str) -> bool:
        """다이얼로그 없는 로드 경로. 성공 시 True."""
        try:
            book = self._storage.load(name)
        except FileNotFoundError:
            return False
        self._book = book
        self._book.rules.sort(key=lambda r: r.priority)
        self._active_preset_name = name
        self._current_rule_id = None
        self._preset_panel.set_rulebook(self._book)
        self._rule_panel.set_rule(self._empty_rule())
        self._update_active_preset_label()
        self._set_dirty(False)
        return True

    def _on_preset_save(self, name: str) -> None:
        # 번들 프리셋은 덮어쓸 수 없으므로 항상 새 이름을 받는다.
        force_rename = self._preset_panel.is_selected_preset_bundled()
        if force_rename or not name.strip():
            prompt = (
                "번들 프리셋은 덮어쓸 수 없습니다. 새 이름으로 저장:"
                if force_rename
                else "새 프리셋 이름:"
            )
            new_name, ok = QInputDialog.getText(
                self, "프리셋 저장", prompt, text=name
            )
            if not ok or not new_name.strip():
                return
            name = new_name.strip()
            if force_rename and self._preset_panel.is_name_bundled(name):
                QMessageBox.warning(
                    self,
                    "프리셋 저장",
                    "번들과 동일한 이름은 사용할 수 없습니다.",
                )
                return
        ok, err = self._perform_save(name)
        if ok:
            QMessageBox.information(self, "저장 완료", f"'{name}' 저장됨.")
        else:
            QMessageBox.critical(self, "저장 실패", err or "unknown")

    def _perform_save(self, name: str) -> tuple:
        """다이얼로그 없는 저장 경로. (ok, error) 반환.

        번들 이름으로 저장 시도는 거부 (shadow 방지).
        """
        name = (name or "").strip()
        if not name:
            return False, "이름 누락"
        if self._preset_panel.is_name_bundled(name):
            return False, "번들과 동일한 이름은 사용할 수 없습니다."
        try:
            self._storage.save(name, self._book)
            self._active_preset_name = name
            self._update_active_preset_label()
            self._refresh_preset_list()
            return True, None
        except Exception as e:
            return False, str(e)

    def _on_preset_delete(self, name: str) -> None:
        reply = QMessageBox.question(
            self, "프리셋 삭제",
            f"정말 '{name}' 을(를) 삭제하시겠습니까?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._perform_delete(name)

    def _perform_delete(self, name: str) -> bool:
        """다이얼로그 없는 삭제 경로. 성공 시 True."""
        if self._storage.delete(name):
            if self._active_preset_name == name:
                self._active_preset_name = None
                self._update_active_preset_label()
            self._refresh_preset_list()
            return True
        return False

    # ------------------------------------------------------------------
    # Rule 핸들러
    # ------------------------------------------------------------------

    def _on_rule_selected(self, idx: int) -> None:
        if 0 <= idx < len(self._book.rules):
            rule = self._book.rules[idx]
            self._current_rule_id = rule.id
            self._rule_panel.set_rule(rule)
        else:
            self._current_rule_id = None
            self._rule_panel.set_rule(self._empty_rule())

    def _on_rule_panel_changed(self) -> None:
        if not self._current_rule_id:
            return
        updated = self._rule_panel.get_rule()
        updated.id = self._current_rule_id
        for i, r in enumerate(self._book.rules):
            if r.id == self._current_rule_id:
                self._book.rules[i] = updated
                break
        self._refresh_rule_list_preserving_selection()
        self._set_dirty(True)

    def _on_rule_add(self) -> None:
        new_rule = self._empty_rule()
        # 기존 최대 priority + 10 (맨 아래 배치)
        max_p = max((r.priority for r in self._book.rules), default=0)
        new_rule.priority = max_p + 10
        self._book.rules.append(new_rule)
        self._current_rule_id = new_rule.id
        self._refresh_rule_list_preserving_selection()
        self._rule_panel.set_rule(new_rule)
        self._set_dirty(True)

    def _on_rule_delete(self, idx: int) -> None:
        if not (0 <= idx < len(self._book.rules)):
            return
        removed = self._book.rules.pop(idx)
        if removed.id == self._current_rule_id:
            self._current_rule_id = None
            self._rule_panel.set_rule(self._empty_rule())
        self._preset_panel.set_rulebook(self._book)
        self._set_dirty(True)

    def _on_engine_options_changed(self, opts: dict) -> None:
        self._book.max_passes = int(opts.get('max_passes', 1))
        self._book.stop_on_match = bool(opts.get('stop_on_match', False))
        self._set_dirty(True)

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def _on_apply(self) -> None:
        ok = self._perform_apply()
        if not ok:
            QMessageBox.warning(self, "적용", "모듈 참조 없음.")
            return
        QMessageBox.information(
            self, "적용 완료",
            f"{len(self._book.rules)}개 규칙이 모듈에 적용되었습니다.",
        )

    def _perform_apply(self) -> bool:
        """다이얼로그 없는 적용 경로. 성공 시 True.

        174 hotfix (FR-10): DSL 은 모듈의 v2 저장소(`set_v2_dsl`)에 기록하고,
        _editor_mode 를 'v2' 로 전환한다. 레거시 rules_textedit 은 건드리지
        않아 사용자의 레거시 규칙이 유지된다. 구버전 모듈(v2 API 없음)에는
        하위 호환으로 rules_textedit 에 쓴다.
        """
        if self.module is None:
            return False
        dsl = serialize_rulebook(self._book)
        if hasattr(self.module, 'set_v2_dsl'):
            self.module.set_v2_dsl(dsl)
        else:
            rules_textedit = getattr(self.module, 'rules_textedit', None)
            if rules_textedit is not None:
                rules_textedit.setText(dsl)
        if hasattr(self.module, 'set_engine_options'):
            self.module.set_engine_options(
                max_passes=self._book.max_passes,
                stop_on_match=self._book.stop_on_match,
            )
        if hasattr(self.module, 'set_editor_mode'):
            self.module.set_editor_mode("v2")
        if self._active_preset_name is not None:
            self.module._active_preset_name = self._active_preset_name
        self.rules_applied.emit(dsl)
        self._set_dirty(False)
        return True

    # ------------------------------------------------------------------
    # Dirty 가드
    # ------------------------------------------------------------------

    def _set_dirty(self, flag: bool) -> None:
        self._dirty = bool(flag)
        self._update_active_preset_label()

    def is_dirty(self) -> bool:
        return self._dirty

    def set_auto_dirty_choice(self, choice: Optional[str]) -> None:
        """테스트/자동화용. "apply" / "discard" / "cancel" / None."""
        self._auto_dirty_choice = choice

    def _confirm_discard_if_dirty(self, context_label: str) -> bool:
        """dirty 면 Apply/Discard/Cancel 묻고, 진행 가능 여부 반환.

        반환 True = 계속 진행, False = 작업 취소.
        """
        if not self._dirty:
            return True
        choice = self._auto_dirty_choice or self._ask_dirty_choice(
            context_label
        )
        if choice == "apply":
            return self._perform_apply()
        if choice == "discard":
            self._set_dirty(False)
            return True
        return False

    def _ask_dirty_choice(self, context_label: str) -> str:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("저장되지 않은 변경")
        box.setText(
            f"'{context_label}' 전에 편집 내용을 저장하시겠습니까?"
        )
        apply_btn = box.addButton(
            "적용 후 계속", QMessageBox.ButtonRole.AcceptRole
        )
        discard_btn = box.addButton(
            "변경 버림", QMessageBox.ButtonRole.DestructiveRole
        )
        cancel_btn = box.addButton(
            "취소", QMessageBox.ButtonRole.RejectRole
        )
        box.setDefaultButton(cancel_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is apply_btn:
            return "apply"
        if clicked is discard_btn:
            return "discard"
        return "cancel"

    def _update_active_preset_label(self) -> None:
        name = self._active_preset_name or "(없음)"
        marker = " •" if self._dirty else ""
        self._active_preset_label.setText(
            f"활성 프리셋: {name}{marker}"
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def showEvent(self, event):
        # 최초 열림 시에만 모듈 DSL 재동기화. 재사용 인스턴스는 사용자 편집을 보존.
        if not getattr(self, "_initial_show_done", False):
            self._reload_from_module()
            self._refresh_preset_list()
            self._initial_show_done = True
        super().showEvent(event)

    def closeEvent(self, event):
        if not self._confirm_discard_if_dirty("편집기 닫기"):
            event.ignore()
            return
        super().closeEvent(event)
