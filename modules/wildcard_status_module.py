from PyQt6.QtWidgets import QVBoxLayout, QWidget, QLabel, QTextEdit
from interfaces.base_module import BaseMiddleModule
from core.context import AppContext
from core.prompt_context import PromptContext
from ui.theme import DARK_STYLES # 테마 스타일 import

class WildcardStatusModule(BaseMiddleModule):
    """
    🎴 프롬프트 생성 시 사용된 와일드카드의 내역과 상태를 표시하는 UI 모듈
    """

    def __init__(self):
        super().__init__()
        self.history_textbox: QTextEdit = None
        self.state_textbox: QTextEdit = None

    def get_title(self) -> str:
        return "🃏 와일드카드 사용 현황"

    def get_order(self) -> int:
        # 다른 모듈들과의 순서를 고려하여 적절한 값으로 설정 (낮을수록 위)
        return 4 
    
    def initialize_with_context(self, context: AppContext):
        self.context = context
        self.context.subscribe("prompt_generated", self.update_view)
        print(f"✅ '{self.get_title()}' 모듈이 'prompt_generated' 이벤트를 구독합니다.")

    def create_widget(self, parent: QWidget) -> QWidget:
        """모듈의 UI 위젯을 생성합니다."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)

        # 1. 사용된 와일드카드 내역 섹션
        history_label = QLabel("이번에 사용된 와일드카드")
        history_label.setStyleSheet(DARK_STYLES['label_style'])
        layout.addWidget(history_label)

        self.history_textbox = QTextEdit()
        self.history_textbox.setReadOnly(True)
        self.history_textbox.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.history_textbox.setMinimumHeight(100)
        self.history_textbox.setPlaceholderText("랜덤 프롬프트 생성 시 사용된 와일드카드 내역이 표시됩니다.")
        layout.addWidget(self.history_textbox)

        # 2. 순차 와일드카드 상태 섹션
        state_label = QLabel("순차/종속 와일드카드 상태 (현재 / 전체)")
        state_label.setStyleSheet(DARK_STYLES['label_style'])
        layout.addWidget(state_label)

        self.state_textbox = QTextEdit()
        self.state_textbox.setReadOnly(True)
        self.state_textbox.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.state_textbox.setFixedHeight(80)
        self.state_textbox.setPlaceholderText("활성화된 순차/종속 와일드카드가 없습니다.")
        layout.addWidget(self.state_textbox)

        total_wildcards = len(self.context.wildcard_manager.wildcard_dict_tree)
        
        self.count_label = QLabel(f"로드된 와일드카드: {total_wildcards}개")
        # 오른쪽 정렬 및 작은 폰트 스타일 적용
        self.count_label.setStyleSheet(DARK_STYLES['label_style'] + "font-size: 12px; color: #B0B0B0;")
        layout.addWidget(self.count_label)
        
        # 초기 메시지 설정
        self.update_view(None)

        return widget

    def update_view(self, context: PromptContext):
        """
        'prompt_generated' 이벤트 수신 시 호출되는 콜백 함수.
        context 객체에서 와일드카드 정보를 추출하여 UI를 업데이트합니다.
        """
        if not self.history_textbox or not self.state_textbox:
            return

        # 1. 사용 내역 (History) 업데이트
        if context and context.wildcard_history:
            history_text = ""
            for name, values in context.wildcard_history.items():
                last_value = values[-1] # 마지막으로 선택된 값
                history_text += f"▶ {name}: {last_value}\n"
            self.history_textbox.setText(history_text)
        else:
            self.history_textbox.setPlaceholderText("사용된 와일드카드 없음")
            self.history_textbox.clear()

        # 2. 상태 (State) 업데이트
        if context and context.wildcard_state:
            state_text = ""
            for name, state in context.wildcard_state.items():
                state_text += f"▶ {name}: {state['current']} / {state['total']}\n"
            self.state_textbox.setText(state_text)
        else:
            self.state_textbox.setPlaceholderText("활성화된 순차 와일드카드 없음")
            self.state_textbox.clear()