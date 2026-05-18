import os
import html
import json
import subprocess
import platform
from pathlib import Path
from PyQt6.QtWidgets import QVBoxLayout, QWidget, QLabel, QTextEdit, QPushButton, QHBoxLayout, QCheckBox, QComboBox
from PyQt6.QtCore import Qt
from interfaces.base_module import BaseMiddleModule
from core.context import AppContext
from core.prompt_context import PromptContext
from core.wildcard_status_settings import load_wildcard_status_settings, save_wildcard_status_settings
from ui.theme import DARK_STYLES, DARK_COLORS, get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size
from ui.modern_menu import setModernStyle

class WildcardStatusModule(BaseMiddleModule):
    """
    🎴 프롬프트 생성 시 사용된 와일드카드의 내역과 상태를 표시하는 UI 모듈
    """

    SETTINGS_PATH = "save/wildcard_status_settings.json"
    _SCOPE_NONE_LABEL = "없음"

    def __init__(self):
        super().__init__()
        self.history_textbox: QTextEdit = None
        self.state_textbox: QTextEdit = None
        self.prompt_squeeze_checkbox: QCheckBox = None
        self.scope_combo: QComboBox = None
        self.ignore_save_load = True
        self._last_wildcard_keys: list = []

    def get_title(self) -> str:
        return "🃏 와일드카드 모듈"

    def get_order(self) -> int:
        return 4

    def initialize_with_context(self, context: AppContext):
        self.context = context
        self.context.subscribe("prompt_generated", self.update_view)
        self.context.wildcard_manager.register_reload_callback(self.on_wildcards_reloaded)
        print(f"✅ '{self.get_title()}' 모듈이 'prompt_generated' 이벤트를 구독합니다.")
        self.sync_instant_wildcards_to_txt()

    def create_widget(self, parent: QWidget) -> QWidget:
        """모듈의 UI 위젯을 생성합니다."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)

        dynamic_styles = get_dynamic_styles()

        # 1. 사용된 와일드카드 내역 섹션 - 레이블과 관리 버튼
        history_header_layout = QHBoxLayout()
        history_header_layout.setContentsMargins(0, 0, 0, 0)

        history_label = QLabel("이번에 사용된 와일드카드")
        history_label.setStyleSheet(dynamic_styles['label_style'])
        history_header_layout.addWidget(history_label)

        history_header_layout.addStretch()

        self.manage_button = QPushButton("📝 와일드카드 관리 윈도우")
        self.manage_button.setStyleSheet(dynamic_styles['compact_button'])
        self.manage_button.setFixedHeight(get_scaled_font_size(22))
        self.manage_button.clicked.connect(self.open_wildcard_manager)
        self.manage_button.setToolTip("와일드카드를 검색, 편집, 관리할 수 있는 창을 엽니다")
        history_header_layout.addWidget(self.manage_button)

        layout.addLayout(history_header_layout)

        self.history_textbox = QTextEdit()
        self.history_textbox.setAcceptRichText(False)
        self.history_textbox.setReadOnly(True)
        self.history_textbox.setStyleSheet(dynamic_styles['compact_textedit'])
        self.history_textbox.setMinimumHeight(100)
        setModernStyle(self.history_textbox)
        self.history_textbox.setPlaceholderText("랜덤 프롬프트 생성 시 사용된 와일드카드 내역이 표시됩니다.")
        layout.addWidget(self.history_textbox)

        # 📌 Scope 설정 ComboBox
        scope_layout = QHBoxLayout()
        scope_layout.setContentsMargins(0, 0, 0, 0)
        scope_layout.setSpacing(6)

        scope_label = QLabel("스코프 설정:")
        scope_label.setStyleSheet(dynamic_styles['label_style'])
        scope_layout.addWidget(scope_label)

        self.scope_combo = QComboBox()
        self.scope_combo.addItem(self._SCOPE_NONE_LABEL)
        self.scope_combo.setToolTip("선택한 와일드카드의 아이템을 히스토리에서 추적합니다")
        self.scope_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.scope_combo.wheelEvent = lambda e: e.ignore()
        self.scope_combo.currentTextChanged.connect(self._on_scope_changed)
        scope_layout.addWidget(self.scope_combo, 1)

        layout.addLayout(scope_layout)

        # 2. 순차 와일드카드 상태 섹션
        state_label = QLabel("순차/종속 와일드카드 상태 (현재 / 전체)")
        state_label.setStyleSheet(dynamic_styles['label_style'])
        layout.addWidget(state_label)

        self.state_textbox = QTextEdit()
        self.state_textbox.setAcceptRichText(False)
        self.state_textbox.setReadOnly(True)
        self.state_textbox.setStyleSheet(dynamic_styles['compact_textedit'])
        self.state_textbox.setFixedHeight(80)
        setModernStyle(self.state_textbox)
        self.state_textbox.setPlaceholderText("활성화된 순차/종속 와일드카드가 없습니다.")
        layout.addWidget(self.state_textbox)

        # 하단 정보 및 버튼 섹션
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(4)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        button_height = get_scaled_font_size(24)

        self.reset_sequential_button = QPushButton("🔄 순차 리셋")
        self.reset_sequential_button.setStyleSheet(dynamic_styles['compact_button'])
        self.reset_sequential_button.setFixedHeight(button_height)
        self.reset_sequential_button.setMinimumWidth(get_scaled_font_size(110))
        self.reset_sequential_button.clicked.connect(self.reset_sequential_wildcards)
        self.reset_sequential_button.setToolTip("모든 순차 와일드카드 카운터를 초기화합니다")
        bottom_layout.addWidget(self.reset_sequential_button)

        self.open_folder_button = QPushButton("📁 폴더 열기")
        self.open_folder_button.setStyleSheet(dynamic_styles['compact_button'])
        self.open_folder_button.setFixedHeight(button_height)
        self.open_folder_button.setMinimumWidth(get_scaled_font_size(110))
        self.open_folder_button.clicked.connect(self.open_wildcard_folder)
        self.open_folder_button.setToolTip("와일드카드 폴더를 파일 탐색기에서 엽니다")
        bottom_layout.addWidget(self.open_folder_button)

        self.reload_button = QPushButton("🔄 리로드")
        self.reload_button.setStyleSheet(dynamic_styles['compact_button'])
        self.reload_button.setFixedHeight(button_height)
        self.reload_button.setMinimumWidth(get_scaled_font_size(90))
        self.reload_button.clicked.connect(self.reload_wildcards)
        self.reload_button.setToolTip("와일드카드 파일들을 다시 로드합니다")
        bottom_layout.addWidget(self.reload_button)

        total_wildcards = len(self.context.wildcard_manager.wildcard_dict_tree)
        self.count_label = QLabel(f"로드된 와일드카드: {total_wildcards}개")
        font_size = get_scaled_font_size(14)
        self.count_label.setStyleSheet(dynamic_styles['label_style'] + f"font-size: {font_size}px; color: #B0B0B0;")
        self.count_label.setFixedHeight(button_height)
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        bottom_layout.addWidget(self.count_label)

        bottom_layout.addStretch()
        layout.addLayout(bottom_layout)

        # 403 방지 체크박스
        self.prompt_squeeze_checkbox = QCheckBox("NovelAI 403 방지 (와일드카드 단독 모드)")
        self.prompt_squeeze_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.prompt_squeeze_checkbox.setToolTip(
            "와일드카드 단독 모드 + NAI 사용 시, 동일 프롬프트 반복 검출을 회피하기 위해\n"
            "기존 태그 조각을 극저 가중치로 삽입합니다. 생성 결과에 거의 영향 없음.")
        self.prompt_squeeze_checkbox.stateChanged.connect(self._on_squeeze_changed)
        layout.addWidget(self.prompt_squeeze_checkbox)

        # 저장된 설정 로드
        self._load_settings()

        # 초기 메시지 설정
        self.update_view(None)

        return widget

    # ── 히스토리 업데이트 ──

    def update_view(self, context: PromptContext):
        """
        'prompt_generated' 이벤트 수신 시 호출되는 콜백 함수.
        """
        if not self.history_textbox or not self.state_textbox:
            return

        # 데이터 준비 (백그라운드 스레드에서 안전)
        wildcard_keys = []
        history_entries = []  # [(name, last_value), ...]
        state_text = ""

        if context and context.wildcard_history:
            for name, values in context.wildcard_history.items():
                last_value = values[-1]
                history_entries.append((name, last_value))
                wildcard_keys.append(name)

        if context and context.wildcard_state:
            for name, state in context.wildcard_state.items():
                state_text += f"▶ {name}: {state['current']} / {state['total']}\n"

        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._update_ui_safe(history_entries, state_text, wildcard_keys))

    def _update_ui_safe(self, history_entries: list, state_text: str, wildcard_keys: list):
        """메인 스레드에서 안전하게 UI 업데이트"""
        try:
            self._last_wildcard_keys = wildcard_keys

            # 히스토리 텍스트 (scoped 항목은 연노랑색 HTML)
            if history_entries:
                self._render_history_html(history_entries)
            else:
                self.history_textbox.setPlaceholderText("사용된 와일드카드 없음")
                self.history_textbox.clear()

            # ComboBox 업데이트 (현재 scope 유지하면서 항목 갱신)
            self._update_scope_combo(wildcard_keys)

            # State 업데이트
            if state_text:
                self.state_textbox.setText(state_text)
            else:
                self.state_textbox.setPlaceholderText("활성화된 순차 와일드카드 없음")
                self.state_textbox.clear()

        except RuntimeError as e:
            print(f"⚠️ wildcard_status_module UI 업데이트 실패 (위젯 삭제됨): {e}")

    def _render_history_html(self, history_entries: list = None):
        """히스토리 텍스트박스를 HTML로 렌더링 (scoped 항목은 연노랑색)"""
        if history_entries is None:
            ctx = self.context.current_prompt_context
            if not ctx or not ctx.wildcard_history:
                return
            history_entries = [(n, v[-1]) for n, v in ctx.wildcard_history.items()]

        scoped_key = self.context.scoped_wildcard
        html_lines = []
        for name, last_value in history_entries:
            esc_name = html.escape(name)
            esc_value = html.escape(last_value)
            if scoped_key and name == scoped_key:
                html_lines.append(
                    f'<span style="color: #FFEE88;">📌 {esc_name}: {esc_value}</span>')
            else:
                html_lines.append(f'▶ {esc_name}: {esc_value}')
        self.history_textbox.setHtml('<br>'.join(html_lines))

    # ── Scope ComboBox ──

    def _update_scope_combo(self, wildcard_keys: list):
        """ComboBox 항목을 갱신하되 현재 선택을 유지"""
        current_scope = self.context.scoped_wildcard
        self.scope_combo.blockSignals(True)
        self.scope_combo.clear()
        self.scope_combo.addItem(self._SCOPE_NONE_LABEL)
        for key in wildcard_keys:
            self.scope_combo.addItem(key)
        # 기존 scope가 목록에 있으면 복원
        idx = self.scope_combo.findText(current_scope)
        if idx >= 0:
            self.scope_combo.setCurrentIndex(idx)
        else:
            self.scope_combo.setCurrentIndex(0)
            if current_scope:
                self.context.scoped_wildcard = ''
                self._save_settings()
        self.scope_combo.blockSignals(False)

    def _on_scope_changed(self, text: str):
        """ComboBox 선택 변경 시 — 오버라이드도 함께 해제"""
        if text == self._SCOPE_NONE_LABEL:
            self.context.scoped_wildcard = ''
        else:
            self.context.scoped_wildcard = text
        self.context.wildcard_override.clear()
        self._save_settings()
        self._render_history_html()
        self.context.publish("scoped_wildcard_changed", {})

    # ── 기존 기능들 ──

    def _on_squeeze_changed(self, state):
        enabled = self.prompt_squeeze_checkbox.isChecked()
        self.context.prompt_squeeze_enabled = enabled
        self._save_settings()

    def _load_settings(self):
        settings = load_wildcard_status_settings(self.SETTINGS_PATH)
        enabled = settings['prompt_squeeze_enabled']
        scoped = settings['scoped_wildcard']
        self.prompt_squeeze_checkbox.setChecked(enabled)
        self.context.prompt_squeeze_enabled = enabled
        self.context.scoped_wildcard = scoped

    def _save_settings(self):
        try:
            enabled = (
                self.prompt_squeeze_checkbox.isChecked()
                if self.prompt_squeeze_checkbox
                else getattr(self.context, 'prompt_squeeze_enabled', True)
            )
            save_wildcard_status_settings({
                'prompt_squeeze_enabled': enabled,
                'scoped_wildcard': self.context.scoped_wildcard
            }, self.SETTINGS_PATH)
        except Exception as e:
            print(f"⚠️ wildcard_status 설정 저장 실패: {e}")

    def reload_wildcards(self):
        try:
            self.sync_instant_wildcards_to_txt()
        except Exception as e:
            print(f"❌ 와일드카드 리로드 중 오류 발생: {e}")

    def on_wildcards_reloaded(self, wildcard_count):
        if hasattr(self, 'count_label') and self.count_label:
            self.count_label.setText(f"로드된 와일드카드: {wildcard_count}개")

    def reset_sequential_wildcards(self):
        try:
            if self.context.current_prompt_context:
                old_counter_count = len(self.context.current_prompt_context.sequential_counters)
                old_state_count = len(self.context.current_prompt_context.wildcard_state)

                self.context.current_prompt_context.sequential_counters.clear()
                self.context.current_prompt_context.wildcard_state.clear()

                print(f"🔄 순차 와일드카드 리셋 완료: 카운터 {old_counter_count}개, 상태 {old_state_count}개 초기화")

                if self.state_textbox:
                    self.state_textbox.clear()
                    self.state_textbox.setPlaceholderText("순차 카운터가 리셋되었습니다. 다음 생성부터 새로 시작합니다.")

            else:
                print("⚠️ 현재 프롬프트 컨텍스트가 없어 리셋할 항목이 없습니다.")
                if self.state_textbox:
                    self.state_textbox.clear()
                    self.state_textbox.setPlaceholderText("리셋할 순차 와일드카드가 없습니다.")

        except Exception as e:
            print(f"❌ 순차 와일드카드 리셋 중 오류 발생: {e}")

    def open_wildcard_folder(self):
        try:
            wildcards_dir = self.context.wildcard_manager.wildcards_dir

            if not os.path.exists(wildcards_dir):
                os.makedirs(wildcards_dir)

            system = platform.system()
            if system == "Windows":
                os.startfile(wildcards_dir)
            elif system == "Darwin":
                subprocess.run(["open", wildcards_dir])
            else:
                subprocess.run(["xdg-open", wildcards_dir])

        except Exception as e:
            print(f"❌ 와일드카드 폴더 열기 중 오류 발생: {e}")

    def open_wildcard_manager(self):
        try:
            from ui.wildcard_manager_window import WildcardManagerWindow

            if hasattr(self, 'wildcard_window') and self.wildcard_window:
                self.wildcard_window.close()

            self.wildcard_window = WildcardManagerWindow(self.context)
            self.wildcard_window.show()

        except Exception as e:
            print(f"❌ 와일드카드 관리 창 열기 중 오류 발생: {e}")

    def sync_instant_wildcards_to_txt(self):
        """
        save/instant_wildcard 폴더의 JSON 파일들을 읽어서
        wildcards/instant_wildcard 폴더에 대응하는 TXT 파일을 생성합니다.
        """
        try:
            instant_json_path = Path("save/instant_wildcard")
            wildcards_dir = Path(self.context.wildcard_manager.wildcards_dir)
            instant_txt_path = wildcards_dir / "instant_wildcard"

            instant_txt_path.mkdir(parents=True, exist_ok=True)

            if not instant_json_path.exists():
                print("📁 save/instant_wildcard 폴더가 없습니다. 인스턴트 와일드카드 변환을 건너뜁니다.")
                return

            json_files = list(instant_json_path.glob("*.json"))
            converted_count = 0

            for json_file in json_files:
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    txt_filename = json_file.stem + ".txt"
                    txt_file_path = instant_txt_path / txt_filename

                    with open(txt_file_path, 'w', encoding='utf-8') as f:
                        for key, value in data.items():
                            f.write(f"#{key}, {value}\n")

                    converted_count += 1
                    print(f"✅ 인스턴트 와일드카드 변환 완료: {json_file.name} -> {txt_filename}")

                except json.JSONDecodeError as e:
                    print(f"⚠️ JSON 파일 읽기 실패 ({json_file.name}): {e}")
                except Exception as e:
                    print(f"⚠️ 파일 변환 중 오류 ({json_file.name}): {e}")

            if converted_count > 0:
                print(f"📝 총 {converted_count}개의 인스턴트 와일드카드 파일을 TXT로 변환했습니다.")
                self.context.wildcard_manager.reload_wildcards()
            else:
                print("📝 변환할 인스턴트 와일드카드 파일이 없습니다.")

        except Exception as e:
            print(f"❌ 인스턴트 와일드카드 동기화 중 오류 발생: {e}")
