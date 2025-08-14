import os
import subprocess
import platform
from PyQt6.QtWidgets import QVBoxLayout, QWidget, QLabel, QTextEdit, QPushButton, QHBoxLayout
from interfaces.base_module import BaseMiddleModule
from core.context import AppContext
from core.prompt_context import PromptContext
from ui.theme import DARK_STYLES, get_dynamic_styles # 테마 스타일 import
from ui.scaling_manager import get_scaled_font_size
from ui.modern_menu import setModernStyle

class WildcardStatusModule(BaseMiddleModule):
    """
    🎴 프롬프트 생성 시 사용된 와일드카드의 내역과 상태를 표시하는 UI 모듈
    """

    def __init__(self):
        super().__init__()
        self.history_textbox: QTextEdit = None
        self.state_textbox: QTextEdit = None
        self.ignore_save_load = True 

    def get_title(self) -> str:
        return "🃏 와일드카드 사용 현황"

    def get_order(self) -> int:
        # 다른 모듈들과의 순서를 고려하여 적절한 값으로 설정 (낮을수록 위)
        return 4 
    
    def initialize_with_context(self, context: AppContext):
        self.context = context
        self.context.subscribe("prompt_generated", self.update_view)
        # 와일드카드 리로드 콜백 등록
        self.context.wildcard_manager.register_reload_callback(self.on_wildcards_reloaded)
        print(f"✅ '{self.get_title()}' 모듈이 'prompt_generated' 이벤트를 구독합니다.")

    def create_widget(self, parent: QWidget) -> QWidget:
        """모듈의 UI 위젯을 생성합니다."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)

        # 동적 스타일 가져오기
        dynamic_styles = get_dynamic_styles()
        
        # 1. 사용된 와일드카드 내역 섹션
        history_label = QLabel("이번에 사용된 와일드카드")
        history_label.setStyleSheet(dynamic_styles['label_style'])
        layout.addWidget(history_label)

        self.history_textbox = QTextEdit()
        self.history_textbox.setReadOnly(True)
        self.history_textbox.setStyleSheet(dynamic_styles['compact_textedit'])
        self.history_textbox.setMinimumHeight(100)
        setModernStyle(self.history_textbox)
        self.history_textbox.setPlaceholderText("랜덤 프롬프트 생성 시 사용된 와일드카드 내역이 표시됩니다.")
        layout.addWidget(self.history_textbox)

        # 2. 순차 와일드카드 상태 섹션
        state_label = QLabel("순차/종속 와일드카드 상태 (현재 / 전체)")
        state_label.setStyleSheet(dynamic_styles['label_style'])
        layout.addWidget(state_label)

        self.state_textbox = QTextEdit()
        self.state_textbox.setReadOnly(True)
        self.state_textbox.setStyleSheet(dynamic_styles['compact_textedit'])
        self.state_textbox.setFixedHeight(80)
        setModernStyle(self.state_textbox)
        self.state_textbox.setPlaceholderText("활성화된 순차/종속 와일드카드가 없습니다.")
        layout.addWidget(self.state_textbox)

        # 하단 정보 및 버튼 섹션을 위한 수평 레이아웃
        bottom_layout = QHBoxLayout()
        
        total_wildcards = len(self.context.wildcard_manager.wildcard_dict_tree)
        
        self.count_label = QLabel(f"로드된 와일드카드: {total_wildcards}개")
        # 왼쪽 정렬 및 작은 폰트 스타일 적용
        dynamic_styles = get_dynamic_styles()
        font_size = get_scaled_font_size(12)
        self.count_label.setStyleSheet(dynamic_styles['label_style'] + f"font-size: {font_size}px; color: #B0B0B0;")
        bottom_layout.addWidget(self.count_label)
        
        # 스트레치를 추가하여 버튼을 오른쪽으로 밀어냄
        bottom_layout.addStretch()
        
        # 순차 리셋 버튼 추가
        self.reset_sequential_button = QPushButton("🔄 순차 리셋")
        self.reset_sequential_button.setStyleSheet(DARK_STYLES['compact_button'])
        self.reset_sequential_button.setFixedSize(130, 22)
        self.reset_sequential_button.clicked.connect(self.reset_sequential_wildcards)
        self.reset_sequential_button.setToolTip("모든 순차 와일드카드 카운터를 초기화합니다")
        bottom_layout.addWidget(self.reset_sequential_button)
        
        # 폴더 열기 버튼 추가
        self.open_folder_button = QPushButton("📁 폴더 열기")
        self.open_folder_button.setStyleSheet(DARK_STYLES['compact_button'])
        self.open_folder_button.setFixedSize(130, 22)
        self.open_folder_button.clicked.connect(self.open_wildcard_folder)
        self.open_folder_button.setToolTip("와일드카드 폴더를 파일 탐색기에서 엽니다")
        bottom_layout.addWidget(self.open_folder_button)
        
        # 리로드 버튼 추가
        self.reload_button = QPushButton("🔄 리로드")
        self.reload_button.setStyleSheet(DARK_STYLES['compact_button'])
        self.reload_button.setFixedSize(110, 22)
        self.reload_button.clicked.connect(self.reload_wildcards)
        self.reload_button.setToolTip("와일드카드 파일들을 다시 로드합니다")
        bottom_layout.addWidget(self.reload_button)
        
        layout.addLayout(bottom_layout)
        
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
            
    def reload_wildcards(self):
        """
        리로드 버튼 클릭 시 호출되는 함수.
        와일드카드 매니저에게 리로드를 요청합니다.
        """
        try:
            self.context.wildcard_manager.reload_wildcards()
        except Exception as e:
            print(f"❌ 와일드카드 리로드 중 오류 발생: {e}")
            
    def on_wildcards_reloaded(self, wildcard_count):
        """
        와일드카드 리로드 완료 시 호출되는 콜백 함수.
        와일드카드 개수 레이블을 업데이트합니다.
        """
        if hasattr(self, 'count_label') and self.count_label:
            self.count_label.setText(f"로드된 와일드카드: {wildcard_count}개")
            
    def reset_sequential_wildcards(self):
        """
        순차 리셋 버튼 클릭 시 호출되는 함수.
        AppContext의 current_prompt_context에서 순차 와일드카드 카운터와 상태를 초기화합니다.
        """
        try:
            if self.context.current_prompt_context:
                # 순차 카운터 초기화
                old_counter_count = len(self.context.current_prompt_context.sequential_counters)
                old_state_count = len(self.context.current_prompt_context.wildcard_state)
                
                self.context.current_prompt_context.sequential_counters.clear()
                self.context.current_prompt_context.wildcard_state.clear()
                
                print(f"🔄 순차 와일드카드 리셋 완료: 카운터 {old_counter_count}개, 상태 {old_state_count}개 초기화")
                
                # UI 즉시 업데이트
                self.state_textbox.clear()
                self.state_textbox.setPlaceholderText("순차 카운터가 리셋되었습니다. 다음 생성부터 새로 시작합니다.")
                
            else:
                print("⚠️ 현재 프롬프트 컨텍스트가 없어 리셋할 항목이 없습니다.")
                self.state_textbox.clear()
                self.state_textbox.setPlaceholderText("리셋할 순차 와일드카드가 없습니다.")
                
        except Exception as e:
            print(f"❌ 순차 와일드카드 리셋 중 오류 발생: {e}")

    def open_wildcard_folder(self):
        """
        폴더 열기 버튼 클릭 시 호출되는 함수.
        와일드카드 폴더를 파일 탐색기에서 엽니다.
        """
        try:
            wildcards_dir = self.context.wildcard_manager.wildcards_dir
            
            # 폴더가 존재하지 않으면 생성
            if not os.path.exists(wildcards_dir):
                os.makedirs(wildcards_dir)
            
            # 운영체제별로 폴더 열기 명령어 실행
            system = platform.system()
            if system == "Windows":
                os.startfile(wildcards_dir)
            elif system == "Darwin":  # macOS
                subprocess.run(["open", wildcards_dir])
            else:  # Linux
                subprocess.run(["xdg-open", wildcards_dir])
                
        except Exception as e:
            print(f"❌ 와일드카드 폴더 열기 중 오류 발생: {e}")