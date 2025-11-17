# ui/temp_generation_window.py
"""
임시 생성 창 (Temporary Generation Window)

메인 프롬프트를 오염시키지 않고 테스트 생성을 수행할 수 있는 간소화된 독립 창입니다.
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QPushButton, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QCloseEvent
from ui.theme import DARK_COLORS, DARK_STYLES
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.temp_generation_params import TempGenerationParamsWidget


class TempGenerationWindow(QMainWindow):
    """임시 생성 창 - 간소화된 독립 생성 UI"""

    # 시그널 정의
    generate_requested = pyqtSignal(int, dict)  # (window_id, params)
    params_update_requested = pyqtSignal(dict)  # (params)
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

        # === 수평 분할 레이아웃 (좌: 프롬프트 40%, 우: 파라미터 60%) ===
        content_h_layout = QHBoxLayout()
        content_h_layout.setSpacing(get_scaled_size(16))

        # === 좌측 패널: 프롬프트 ===
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
        self.negative_prompt_edit.setPlaceholderText("네거티브 프롬프트를 입력하세요 (선택 사항)")
        self.negative_prompt_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.negative_prompt_edit.setMinimumHeight(get_scaled_size(150))
        left_layout.addWidget(self.negative_prompt_edit, stretch=2)

        # === 우측 패널: 생성 파라미터 ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(get_scaled_size(8))

        # 파라미터 타이틀
        params_label = QLabel("생성 파라미터:")
        params_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_primary']};
                font-weight: 500;
            }}
        """)
        right_layout.addWidget(params_label)

        # 파라미터 위젯 (스크롤 가능)
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

        right_layout.addWidget(params_scroll)

        # === 수평 레이아웃에 패널 추가 (40:60 비율) ===
        content_h_layout.addWidget(left_panel, stretch=40)
        content_h_layout.addWidget(right_panel, stretch=60)

        # === 버튼 행 ===
        button_row = QHBoxLayout()
        button_row.setSpacing(get_scaled_size(12))

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

        button_row.addWidget(self.generate_btn, stretch=2)
        button_row.addWidget(self.update_main_ui_btn, stretch=1)

        # 메인 레이아웃에 추가
        main_v_layout.addLayout(content_h_layout)
        main_v_layout.addLayout(button_row)

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

    def on_update_main_ui_clicked(self):
        """
        메인 UI에 적용 버튼 클릭 시 처리

        1. 확인 다이얼로그 표시
        2. 프롬프트 및 파라미터 수집
        3. params_update_requested 시그널 발행
        """
        from PyQt6.QtWidgets import QMessageBox

        # 1. 확인 다이얼로그
        reply = QMessageBox.question(
            self,
            "파라미터 적용 확인",
            "현재 임시 창의 파라미터를 메인 UI에 적용하시겠습니까?\n"
            "메인 UI의 현재 설정이 덮어씌워집니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # 2. 프롬프트 및 파라미터 수집
        params = {
            'input': self.main_prompt_edit.toPlainText(),
            'negative_prompt': self.negative_prompt_edit.toPlainText()
        }

        # 파라미터 위젯에서 생성 파라미터 수집
        generation_params = self.params_widget.collect_parameters()
        params.update(generation_params)

        # 3. 시그널 발행
        print(f"[TempGenerationWindow #{self.window_id}] 메인 UI 파라미터 업데이트 요청")
        print(f"  - Main: {params['input'][:50]}{'...' if len(params['input']) > 50 else ''}")
        print(f"  - Model: {params.get('model', 'N/A')}")
        print(f"  - Steps: {params.get('steps', 'N/A')}")

        self.params_update_requested.emit(params)

        # 성공 메시지
        QMessageBox.information(
            self,
            "적용 완료",
            "메인 UI에 파라미터가 성공적으로 적용되었습니다."
        )

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
