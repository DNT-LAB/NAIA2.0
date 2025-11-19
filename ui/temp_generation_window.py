# ui/temp_generation_window.py
"""
임시 생성 창 (Temporary Generation Window)

메인 프롬프트를 오염시키지 않고 테스트 생성을 수행할 수 있는 간소화된 독립 창입니다.
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QPushButton, QScrollArea, QTabWidget, QCheckBox, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QCloseEvent
from ui.theme import DARK_COLORS, DARK_STYLES
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.temp_generation_params import TempGenerationParamsWidget
from ui.virtual_character_tab import VirtualCharacterTab
from ui.virtual_prompt_engineering_tab import VirtualPromptEngineeringTab


class TempGenerationWindow(QMainWindow):
    """임시 생성 창 - 간소화된 독립 생성 UI"""

    # 시그널 정의
    generate_requested = pyqtSignal(int, dict)  # (window_id, params)
    params_update_requested = pyqtSignal(dict)  # (params)
    random_prompt_requested = pyqtSignal(int)  # (window_id) - 🆕 FR-4 개선
    window_closing = pyqtSignal(int)  # (window_id)

    def __init__(self, window_id: int, app_context, parent=None):
        """
        임시 생성 창 초기화

        Args:
            window_id: 고유 창 식별자
            app_context: AppContext 인스턴스
            parent: 부모 위젯 (None으로 설정하여 완전 독립)
        """
        super().__init__(parent=parent)

        self.window_id = window_id
        self.app_context = app_context

        # 버튼 피드백 스타일 (LightGrey)
        self.FEEDBACK_STYLE = f"""
            QPushButton {{
                background-color: {DARK_COLORS['text_disabled']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 8px;
                font-size: {get_scaled_font_size(18)}px;
                font-weight: 500;
            }}
        """

        self.init_ui()

        print(f"✅ [TempGenerationWindow] 임시 창 #{self.window_id} 생성됨")

    def init_ui(self):
        """UI 초기화 - 수평 분할 레이아웃 (좌: 프롬프트, 우: 파라미터)"""
        # 창 설정
        self.setWindowTitle(f"NAIA - 임시 생성 #{self.window_id}")
        self.setMinimumSize(900, 600)  # 파라미터 추가로 더 넓게
        self.resize(1200, 750)

        # 완전 독립 창 플래그
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowTitleHint
        )

        # 다크 테마 적용
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        # 중앙 위젯 설정
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 메인 레이아웃 (수직: 상단=콘텐츠, 하단=버튼)
        main_v_layout = QVBoxLayout(central_widget)
        main_v_layout.setContentsMargins(
            get_scaled_size(16),
            get_scaled_size(16),
            get_scaled_size(16),
            get_scaled_size(16)
        )
        main_v_layout.setSpacing(get_scaled_size(12))

        # === 수평 분할 레이아웃 (좌: 프롬프트 40%, 우: 탭 UI 60%) ===
        content_h_layout = QHBoxLayout()
        content_h_layout.setSpacing(get_scaled_size(16))

        # === 좌측 패널: 프롬프트 ===
        left_panel = self._create_left_panel()

        # === 우측 패널: 탭 UI ===
        right_panel = self._create_right_panel()

        # === 수평 레이아웃에 패널 추가 (40:60 비율) ===
        content_h_layout.addWidget(left_panel, stretch=40)
        content_h_layout.addWidget(right_panel, stretch=60)

        # === 버튼 행 ===
        button_row = QHBoxLayout()
        button_row.setSpacing(get_scaled_size(12))

        # 🆕 FR-4: Random/Next Prompt 버튼
        self.random_prompt_btn = QPushButton("🔀 Random/Next Prompt")
        self.random_prompt_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.random_prompt_btn.setMinimumHeight(get_scaled_size(45))
        self.random_prompt_btn.clicked.connect(self.on_random_prompt_clicked)

        # Generate 버튼
        self.generate_btn = QPushButton("🎨 이미지 생성")
        self.generate_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.generate_btn.setMinimumHeight(get_scaled_size(45))
        self.generate_btn.clicked.connect(self.on_generate_clicked)

        # 메인 UI에 적용 버튼
        self.update_main_ui_btn = QPushButton("📤 메인 UI에 적용")
        self.update_main_ui_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.update_main_ui_btn.setMinimumHeight(get_scaled_size(45))
        self.update_main_ui_btn.clicked.connect(self.on_update_main_ui_clicked)

        button_row.addWidget(self.random_prompt_btn, stretch=1)  # 🆕 FR-4
        button_row.addWidget(self.generate_btn, stretch=2)
        button_row.addWidget(self.update_main_ui_btn, stretch=1)

        # 메인 레이아웃에 추가
        main_v_layout.addLayout(content_h_layout)
        main_v_layout.addLayout(button_row)

    def _create_left_panel(self) -> QWidget:
        """좌측 패널: 프롬프트 입력"""
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(get_scaled_size(12))

        # Main Prompt
        main_label = QLabel("Main Prompt:")
        main_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_primary']};
                font-weight: 500;
            }}
        """)
        left_layout.addWidget(main_label)

        self.main_prompt_edit = QTextEdit()
        self.main_prompt_edit.setAcceptRichText(False)  # ✅ 2025-01-17: 서식 붙여넣기 차단
        self.main_prompt_edit.setPlaceholderText("메인 프롬프트를 입력하세요 (예: 1girl, smile)")
        self.main_prompt_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.main_prompt_edit.setMinimumHeight(get_scaled_size(200))
        left_layout.addWidget(self.main_prompt_edit, stretch=3)

        # Negative Prompt
        negative_label = QLabel("Negative Prompt:")
        negative_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_primary']};
                font-weight: 500;
            }}
        """)
        left_layout.addWidget(negative_label)

        self.negative_prompt_edit = QTextEdit()
        self.negative_prompt_edit.setAcceptRichText(False)  # ✅ 2025-01-17: 서식 붙여넣기 차단
        self.negative_prompt_edit.setPlaceholderText("네거티브 프롬프트를 입력하세요 (선택 사항)")
        self.negative_prompt_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.negative_prompt_edit.setMinimumHeight(get_scaled_size(150))
        left_layout.addWidget(self.negative_prompt_edit, stretch=2)

        # 🆕 FR-5: 프롬프트 제어 체크박스
        checkbox_row = QHBoxLayout()
        checkbox_row.setSpacing(get_scaled_size(12))

        self.prompt_fixed_checkbox = QCheckBox("프롬프트 고정")
        self.prompt_fixed_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.prompt_fixed_checkbox.setToolTip("체크 시: Random/Next Prompt 버튼 비활성화")
        self.prompt_fixed_checkbox.stateChanged.connect(self._on_prompt_fixed_changed)

        self.wildcard_standalone_checkbox = QCheckBox("와일드카드 단독 모드")
        self.wildcard_standalone_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.wildcard_standalone_checkbox.setToolTip("체크 시: 데이터베이스 태그 없이 와일드카드만 확장")

        checkbox_row.addWidget(self.prompt_fixed_checkbox)
        checkbox_row.addWidget(self.wildcard_standalone_checkbox)
        checkbox_row.addStretch()

        left_layout.addLayout(checkbox_row)

        return left_panel

    def _create_right_panel(self) -> QWidget:
        """우측 패널: 탭 UI (생성 파라미터 + 가상 모듈)"""
        # QTabWidget 생성
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(DARK_STYLES['dark_tabs'])

        # Tab 0: 생성 파라미터
        self.params_widget = TempGenerationParamsWidget(self.app_context)

        params_scroll = QScrollArea()
        params_scroll.setWidget(self.params_widget)
        params_scroll.setWidgetResizable(True)
        params_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        params_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        params_scroll.setStyleSheet(f"""
            QScrollArea {{
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                background-color: {DARK_COLORS['bg_secondary']};
            }}
        """)

        self.tab_widget.addTab(params_scroll, "⚙️ 생성 파라미터")

        # Tab 1: 가상 캐릭터 모듈
        self.character_tab = VirtualCharacterTab(self.app_context)
        self.tab_widget.addTab(self.character_tab, "👤 캐릭터")

        # Tab 2: 가상 프롬프트 엔지니어링 모듈 (FR-3)
        self.prompt_engineering_tab = VirtualPromptEngineeringTab(self.app_context)
        self.tab_widget.addTab(self.prompt_engineering_tab, "🔧 프롬프트 엔지니어링")

        return self.tab_widget

    def on_generate_clicked(self):
        """
        Generate 버튼 클릭 시 처리

        1. 버튼 피드백 시작 ("요청 전달됨" + LightGrey)
        2. 프롬프트 및 파라미터 수집
        3. generate_requested 시그널 발행
        4. 1초 후 버튼 복원
        """
        # 1. 버튼 피드백 시작
        self.generate_btn.setText("요청 전달됨")
        self.generate_btn.setStyleSheet(self.FEEDBACK_STYLE)
        self.generate_btn.setEnabled(False)

        # 2. 프롬프트 및 파라미터 수집
        params = {
            'input': self.main_prompt_edit.toPlainText(),
            'negative_prompt': self.negative_prompt_edit.toPlainText()
        }

        # 파라미터 위젯에서 생성 파라미터 수집
        generation_params = self.params_widget.collect_parameters()
        params.update(generation_params)

        # 🆕 Fix: reroll_on_generate가 True면 생성 시점에 와일드카드 처리 (UI 스레드에서)
        if hasattr(self, 'character_tab'):
            if (hasattr(self.character_tab, 'reroll_on_generate_checkbox') and
                self.character_tab.reroll_on_generate_checkbox and
                self.character_tab.reroll_on_generate_checkbox.isChecked()):
                print(f"[TempGenerationWindow #{self.window_id}] 🔄 reroll_on_generate=True → 캐릭터 와일드카드 처리")
                self.character_tab.process_and_update_view()

        # 캐릭터 탭에서 파라미터 수집
        if hasattr(self, 'character_tab'):
            character_params = self.character_tab.get_parameters()
            params.update(character_params)

        # 🆕 FR-3: 프롬프트 엔지니어링 훅 수동 실행
        # ❌ 비활성화: 이미지 생성 버튼에서는 메인 프롬프트만 사용해야 함
        # 선행/후행 고정 프롬프트는 Random/Next Prompt 버튼을 눌렀을 때만 적용됨
        # if hasattr(self, 'prompt_engineering_tab'):
        #     params['temp_window_prompt_engineering_tab'] = self.prompt_engineering_tab
        #     print(f"[TempGenerationWindow #{self.window_id}] 프롬프트 엔지니어링 탭 참조 전달")

        # 🆕 FR-5: 와일드카드 단독 모드 추가
        if hasattr(self, 'wildcard_standalone_checkbox'):
            params['wildcard_standalone'] = self.wildcard_standalone_checkbox.isChecked()

        # 3. 시그널 발행
        print(f"[TempGenerationWindow #{self.window_id}] 생성 요청 발행")
        print(f"  - Main: {params['input'][:50]}{'...' if len(params['input']) > 50 else ''}")
        print(f"  - Negative: {params['negative_prompt'][:50]}{'...' if len(params['negative_prompt']) > 50 else ''}")
        print(f"  - Model: {params.get('model', 'N/A')}")
        print(f"  - Steps: {params.get('steps', 'N/A')}")
        print(f"  - CFG Scale: {params.get('scale', 'N/A')}")

        self.generate_requested.emit(self.window_id, params)

        # 4. 1초 후 버튼 복원
        QTimer.singleShot(1000, self.restore_button_state)

    def restore_button_state(self):
        """버튼 상태 복원 (원래 텍스트 + 스타일)"""
        self.generate_btn.setText("🎨 이미지 생성")
        self.generate_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.generate_btn.setEnabled(True)

        print(f"[TempGenerationWindow #{self.window_id}] 버튼 상태 복원됨")

    def _on_prompt_fixed_changed(self, state):
        """
        프롬프트 고정 체크박스 상태 변경 시 처리
        체크 시: Random/Next Prompt 버튼 비활성화
        """
        is_fixed = (state == Qt.CheckState.Checked.value)
        self.random_prompt_btn.setEnabled(not is_fixed)

        if is_fixed:
            print(f"[TempGenerationWindow #{self.window_id}] 프롬프트 고정: Random/Next Prompt 버튼 비활성화")
        else:
            print(f"[TempGenerationWindow #{self.window_id}] 프롬프트 고정 해제: Random/Next Prompt 버튼 활성화")

    def on_update_main_ui_clicked(self):
        """
        메인 UI에 적용 버튼 클릭 시 처리

        체크박스 다이얼로그를 표시하여 사용자가 어떤 섹션을 적용할지 선택하도록 합니다.
        - 메인 프롬프트
        - 네거티브 프롬프트
        - 생성 파라미터
        - 캐릭터
        - 프롬프트 엔지니어링
        """
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QCheckBox, QPushButton, QLabel

        # 선택 다이얼로그 생성
        dialog = QDialog(self)
        dialog.setWindowTitle("메인 UI에 적용할 항목 선택")
        dialog.setMinimumWidth(get_scaled_size(400))

        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setSpacing(get_scaled_size(12))

        # 안내 라벨
        info_label = QLabel("메인 UI에 적용할 항목을 선택하세요:")
        info_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(14)}px;
                color: {DARK_COLORS['text_primary']};
                padding: 8px;
            }}
        """)
        dialog_layout.addWidget(info_label)

        # 체크박스 생성
        apply_main_prompt = QCheckBox("메인 프롬프트")
        apply_main_prompt.setChecked(True)
        apply_main_prompt.setStyleSheet(DARK_STYLES['dark_checkbox'])

        apply_negative_prompt = QCheckBox("네거티브 프롬프트")
        apply_negative_prompt.setChecked(True)
        apply_negative_prompt.setStyleSheet(DARK_STYLES['dark_checkbox'])

        apply_generation_params = QCheckBox("생성 파라미터")
        apply_generation_params.setChecked(True)
        apply_generation_params.setStyleSheet(DARK_STYLES['dark_checkbox'])

        apply_character = QCheckBox("캐릭터")
        apply_character.setChecked(False)
        apply_character.setStyleSheet(DARK_STYLES['dark_checkbox'])

        apply_prompt_engineering = QCheckBox("프롬프트 엔지니어링")
        apply_prompt_engineering.setChecked(False)
        apply_prompt_engineering.setStyleSheet(DARK_STYLES['dark_checkbox'])

        dialog_layout.addWidget(apply_main_prompt)
        dialog_layout.addWidget(apply_negative_prompt)
        dialog_layout.addWidget(apply_generation_params)
        dialog_layout.addWidget(apply_character)
        dialog_layout.addWidget(apply_prompt_engineering)

        # 버튼
        button_layout = QHBoxLayout()
        ok_btn = QPushButton("적용")
        ok_btn.setStyleSheet(DARK_STYLES['primary_button'])
        ok_btn.clicked.connect(dialog.accept)

        cancel_btn = QPushButton("취소")
        cancel_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        cancel_btn.clicked.connect(dialog.reject)

        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        dialog_layout.addLayout(button_layout)

        # 다이얼로그 스타일
        dialog.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        # 다이얼로그 실행
        if dialog.exec() != QDialog.DialogCode.Accepted:
            print(f"[TempGenerationWindow #{self.window_id}] 메인 UI 적용 취소됨")
            return

        # 선택된 항목 수집
        apply_sections = {
            'main_prompt': apply_main_prompt.isChecked(),
            'negative_prompt': apply_negative_prompt.isChecked(),
            'generation_params': apply_generation_params.isChecked(),
            'character': apply_character.isChecked(),
            'prompt_engineering': apply_prompt_engineering.isChecked()
        }

        # 파라미터 수집 (선택된 항목만)
        params = {'apply_sections': apply_sections}

        if apply_sections['main_prompt']:
            params['input'] = self.main_prompt_edit.toPlainText()

        if apply_sections['negative_prompt']:
            params['negative_prompt'] = self.negative_prompt_edit.toPlainText()

        if apply_sections['generation_params']:
            generation_params = self.params_widget.collect_parameters()
            params.update(generation_params)

        if apply_sections['character']:
            if hasattr(self, 'character_tab'):
                # get_parameters() 대신 탭 참조 자체를 전달 (텍스트 덤핑용)
                params['temp_window_character_tab'] = self.character_tab

        if apply_sections['prompt_engineering']:
            if hasattr(self, 'prompt_engineering_tab'):
                params['temp_window_prompt_engineering_tab'] = self.prompt_engineering_tab

        # 시그널 발행
        print(f"[TempGenerationWindow #{self.window_id}] 메인 UI 파라미터 업데이트 요청")
        print(f"  - 적용 섹션: {[k for k, v in apply_sections.items() if v]}")

        self.params_update_requested.emit(params)

        # 성공 메시지
        QMessageBox.information(
            self,
            "적용 완료",
            f"선택한 항목이 메인 UI에 성공적으로 적용되었습니다.\n\n"
            f"적용된 항목: {', '.join([k for k, v in apply_sections.items() if v])}"
        )

    def on_random_prompt_clicked(self):
        """
        🆕 FR-4: Random/Next Prompt 버튼 클릭 시 처리 (개선됨)

        시그널을 발행하여 외부(TempWindowManager)에서 처리하도록 위임합니다.
        이를 통해 메인 UI를 오염시키지 않고 독립적으로 프롬프트를 생성할 수 있습니다.
        """
        print(f"[TempGenerationWindow #{self.window_id}] Random/Next Prompt 요청 (시그널 발행)")

        # 시그널 발행: 외부에서 프롬프트를 생성하고 update_prompts()로 결과 전달
        self.random_prompt_requested.emit(self.window_id)

    def update_prompts(self, main_prompt: str, negative_prompt: str):
        """
        🆕 FR-4: 외부에서 생성된 프롬프트를 임시 창에 반영

        Args:
            main_prompt: 메인 프롬프트
            negative_prompt: 네거티브 프롬프트
        """
        self.main_prompt_edit.setPlainText(main_prompt)
        self.negative_prompt_edit.setPlainText(negative_prompt)

        print(f"[TempGenerationWindow #{self.window_id}] 프롬프트 업데이트 완료")
        print(f"  - Main: {main_prompt[:50]}{'...' if len(main_prompt) > 50 else ''}")
        print(f"  - Negative: {negative_prompt[:50]}{'...' if len(negative_prompt) > 50 else ''}")

    def set_prompts(self, main_prompt: str = "", negative_prompt: str = ""):
        """
        프롬프트 텍스트 설정

        Args:
            main_prompt: 메인 프롬프트 텍스트
            negative_prompt: 네거티브 프롬프트 텍스트

        임시 생성 창을 열 때 기존 UI의 프롬프트를 복제하는 데 사용됩니다.
        """
        if main_prompt:
            self.main_prompt_edit.setPlainText(main_prompt)
            print(f"[TempGenerationWindow #{self.window_id}] 메인 프롬프트 설정: {main_prompt[:50]}{'...' if len(main_prompt) > 50 else ''}")

        if negative_prompt:
            self.negative_prompt_edit.setPlainText(negative_prompt)
            print(f"[TempGenerationWindow #{self.window_id}] 네거티브 프롬프트 설정: {negative_prompt[:50]}{'...' if len(negative_prompt) > 50 else ''}")

    def set_initial_params(self, main_window):
        """
        메인 윈도우에서 생성 파라미터 복사

        Args:
            main_window: ModernMainWindow 인스턴스

        임시 생성 창을 열 때 메인 UI의 현재 생성 파라미터를 복제하는 데 사용됩니다.
        """
        print(f"[TempGenerationWindow #{self.window_id}] 메인 윈도우에서 파라미터 복사 중...")
        self.params_widget.set_initial_values(main_window)
        print(f"[TempGenerationWindow #{self.window_id}] 파라미터 복사 완료")

    def initialize_from_main_modules(self, main_window):
        """
        🆕 Issue 2 Fix: 메인 UI의 모든 모듈 상태를 가상 탭으로 복사 (Wrapper Method)

        Args:
            main_window: ModernMainWindow 인스턴스

        이 메서드는 메인 UI의 모듈 상태를 임시 창의 가상 탭으로 한 번에 복사합니다.
        향후 새로운 가상 탭(프롬프트 엔지니어링 등)을 추가할 때 이 메서드에만 추가하면 됩니다.
        """
        print(f"[TempGenerationWindow #{self.window_id}] 메인 UI 모듈 상태 복사 시작...")

        # 1. 캐릭터 모듈 초기화
        if hasattr(self, 'character_tab') and hasattr(main_window, 'app_context'):
            main_character_module = main_window.app_context.middle_section_controller.get_module_instance("CharacterModule")
            if main_character_module:
                print(f"  - CharacterModule 상태 복사 중...")
                self.character_tab.initialize_from_main(main_character_module)
                print(f"  - CharacterModule 복사 완료")
            else:
                print(f"  ⚠️ CharacterModule을 찾을 수 없습니다")

        # 2. 프롬프트 엔지니어링 모듈 초기화 (FR-3)
        if hasattr(self, 'prompt_engineering_tab') and hasattr(main_window, 'app_context'):
            main_pe_module = main_window.app_context.middle_section_controller.get_module_instance("PromptEngineeringModule")
            if main_pe_module:
                print(f"  - PromptEngineeringModule 상태 복사 중...")
                self.prompt_engineering_tab.initialize_from_main(main_pe_module)
                print(f"  - PromptEngineeringModule 복사 완료")
            else:
                print(f"  ⚠️ PromptEngineeringModule을 찾을 수 없습니다")

        print(f"[TempGenerationWindow #{self.window_id}] 모든 모듈 상태 복사 완료")

    def update_params_ui_for_mode(self, api_mode: str, nai_model: str = None):
        """
        API 모드 변경에 따라 파라미터 UI 업데이트

        Args:
            api_mode: "NAI", "WEBUI", "COMFYUI"
            nai_model: NAI 모델 (예: "NAID4.5F", "NAID3")
        """
        self.params_widget.update_ui_for_mode(api_mode, nai_model)

    def closeEvent(self, event: QCloseEvent):
        """
        창 닫기 이벤트

        window_closing 시그널을 발행하여 TempWindowManager가 정리할 수 있도록 합니다.
        """
        print(f"🔄 [TempGenerationWindow] 창 #{self.window_id} 닫기 요청")
        self.window_closing.emit(self.window_id)
        event.accept()
