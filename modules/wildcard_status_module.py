import os
import json
import subprocess
import platform
from pathlib import Path
from PyQt6.QtWidgets import QVBoxLayout, QWidget, QLabel, QTextEdit, QPushButton, QHBoxLayout
from PyQt6.QtCore import Qt
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
        return "🃏 와일드카드 모듈"

    def get_order(self) -> int:
        # 다른 모듈들과의 순서를 고려하여 적절한 값으로 설정 (낮을수록 위)
        return 4 
    
    def initialize_with_context(self, context: AppContext):
        self.context = context
        self.context.subscribe("prompt_generated", self.update_view)
        # 와일드카드 리로드 콜백 등록
        self.context.wildcard_manager.register_reload_callback(self.on_wildcards_reloaded)
        print(f"✅ '{self.get_title()}' 모듈이 'prompt_generated' 이벤트를 구독합니다.")
        
        # 인스턴트 와일드카드를 txt 파일로 변환
        self.sync_instant_wildcards_to_txt()

    def create_widget(self, parent: QWidget) -> QWidget:
        """모듈의 UI 위젯을 생성합니다."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)

        # 동적 스타일 가져오기
        dynamic_styles = get_dynamic_styles()
        
        # 1. 사용된 와일드카드 내역 섹션 - 레이블과 관리 버튼
        history_header_layout = QHBoxLayout()
        history_header_layout.setContentsMargins(0, 0, 0, 0)
        
        history_label = QLabel("이번에 사용된 와일드카드")
        history_label.setStyleSheet(dynamic_styles['label_style'])
        history_header_layout.addWidget(history_label)
        
        history_header_layout.addStretch()
        
        # 와일드카드 관리 윈도우 버튼
        self.manage_button = QPushButton("📝 와일드카드 관리 윈도우")
        self.manage_button.setStyleSheet(dynamic_styles['compact_button'])
        self.manage_button.setFixedHeight(get_scaled_font_size(22))
        self.manage_button.clicked.connect(self.open_wildcard_manager)
        self.manage_button.setToolTip("와일드카드를 검색, 편집, 관리할 수 있는 창을 엽니다")
        history_header_layout.addWidget(self.manage_button)
        
        layout.addLayout(history_header_layout)

        self.history_textbox = QTextEdit()
        self.history_textbox.setAcceptRichText(False)  # 서식 붙여넣기 차단
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
        self.state_textbox.setAcceptRichText(False)  # 서식 붙여넣기 차단
        self.state_textbox.setReadOnly(True)
        self.state_textbox.setStyleSheet(dynamic_styles['compact_textedit'])
        self.state_textbox.setFixedHeight(80)
        setModernStyle(self.state_textbox)
        self.state_textbox.setPlaceholderText("활성화된 순차/종속 와일드카드가 없습니다.")
        layout.addWidget(self.state_textbox)

        # 하단 정보 및 버튼 섹션을 위한 수평 레이아웃
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(4)  # 버튼 간 간격 설정
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        
        # 버튼 높이를 동적 스케일링으로 설정
        button_height = get_scaled_font_size(24)
        
        # 순차 리셋 버튼 추가
        self.reset_sequential_button = QPushButton("🔄 순차 리셋")
        self.reset_sequential_button.setStyleSheet(dynamic_styles['compact_button'])
        self.reset_sequential_button.setFixedHeight(button_height)
        self.reset_sequential_button.setMinimumWidth(get_scaled_font_size(110))
        self.reset_sequential_button.clicked.connect(self.reset_sequential_wildcards)
        self.reset_sequential_button.setToolTip("모든 순차 와일드카드 카운터를 초기화합니다")
        bottom_layout.addWidget(self.reset_sequential_button)
        
        # 폴더 열기 버튼 추가
        self.open_folder_button = QPushButton("📁 폴더 열기")
        self.open_folder_button.setStyleSheet(dynamic_styles['compact_button'])
        self.open_folder_button.setFixedHeight(button_height)
        self.open_folder_button.setMinimumWidth(get_scaled_font_size(110))
        self.open_folder_button.clicked.connect(self.open_wildcard_folder)
        self.open_folder_button.setToolTip("와일드카드 폴더를 파일 탐색기에서 엽니다")
        bottom_layout.addWidget(self.open_folder_button)
        
        # 리로드 버튼 추가
        self.reload_button = QPushButton("🔄 리로드")
        self.reload_button.setStyleSheet(dynamic_styles['compact_button'])
        self.reload_button.setFixedHeight(button_height)
        self.reload_button.setMinimumWidth(get_scaled_font_size(90))
        self.reload_button.clicked.connect(self.reload_wildcards)
        self.reload_button.setToolTip("와일드카드 파일들을 다시 로드합니다")
        bottom_layout.addWidget(self.reload_button)
        
        # 로드된 와일드카드 개수 레이블
        total_wildcards = len(self.context.wildcard_manager.wildcard_dict_tree)
        self.count_label = QLabel(f"로드된 와일드카드: {total_wildcards}개")
        # 레이블도 동일한 높이로 설정하여 정렬
        font_size = get_scaled_font_size(14)
        self.count_label.setStyleSheet(dynamic_styles['label_style'] + f"font-size: {font_size}px; color: #B0B0B0;")
        self.count_label.setFixedHeight(button_height)
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        bottom_layout.addWidget(self.count_label)
        
        # 오른쪽 여백을 위한 스트레치
        bottom_layout.addStretch()
        
        layout.addLayout(bottom_layout)
        
        # 초기 메시지 설정
        self.update_view(None)

        return widget

    def update_view(self, context: PromptContext):
        """
        'prompt_generated' 이벤트 수신 시 호출되는 콜백 함수.
        context 객체에서 와일드카드 정보를 추출하여 UI를 업데이트합니다.

        🔧 스레드 안전 개선:
        - 백그라운드 스레드에서 호출 가능 (ComfyUI 생성 중)
        - QTimer.singleShot으로 메인 스레드에서 UI 업데이트
        - 타이머 충돌 완전 해결
        """
        if not self.history_textbox or not self.state_textbox:
            return

        # 데이터 준비 (백그라운드 스레드에서 안전)
        history_text = ""
        state_text = ""

        # 1. 사용 내역 (History) 데이터 준비
        if context and context.wildcard_history:
            for name, values in context.wildcard_history.items():
                last_value = values[-1]  # 마지막으로 선택된 값
                history_text += f"▶ {name}: {last_value}\n"

        # 2. 상태 (State) 데이터 준비
        if context and context.wildcard_state:
            for name, state in context.wildcard_state.items():
                state_text += f"▶ {name}: {state['current']} / {state['total']}\n"

        # 🔧 메인 스레드에서 UI 업데이트 (스레드 안전)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._update_ui_safe(history_text, state_text, context))

    def _update_ui_safe(self, history_text: str, state_text: str, context):
        """
        메인 스레드에서 안전하게 UI 업데이트

        🔧 이 메서드는 반드시 메인 스레드에서만 호출됨 (QTimer.singleShot 보장)
        """
        try:
            # History 업데이트
            if history_text:
                self.history_textbox.setText(history_text)
            else:
                self.history_textbox.setPlaceholderText("사용된 와일드카드 없음")
                self.history_textbox.clear()

            # State 업데이트
            if state_text:
                self.state_textbox.setText(state_text)
            else:
                self.state_textbox.setPlaceholderText("활성화된 순차 와일드카드 없음")
                self.state_textbox.clear()

        except RuntimeError as e:
            # 위젯이 이미 삭제된 경우 무시
            print(f"⚠️ wildcard_status_module UI 업데이트 실패 (위젯 삭제됨): {e}")
            
    def reload_wildcards(self):
        """
        리로드 버튼 클릭 시 호출되는 함수.
        인스턴트 와일드카드를 동기화하고 와일드카드 매니저에게 리로드를 요청합니다.
        """
        try:
            # 인스턴트 와일드카드를 먼저 동기화
            self.sync_instant_wildcards_to_txt()
            # 이미 sync_instant_wildcards_to_txt에서 reload_wildcards()를 호출하므로
            # 여기서는 별도로 호출하지 않음 (중복 방지)
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
    
    def open_wildcard_manager(self):
        """
        와일드카드 관리 윈도우를 엽니다.
        """
        try:
            from ui.wildcard_manager_window import WildcardManagerWindow
            
            # 이미 열려있는 창이 있으면 닫고 새로 열기
            if hasattr(self, 'wildcard_window') and self.wildcard_window:
                self.wildcard_window.close()
            
            # 새 창 생성
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
            # 경로 설정
            instant_json_path = Path("save/instant_wildcard")
            wildcards_dir = Path(self.context.wildcard_manager.wildcards_dir)
            instant_txt_path = wildcards_dir / "instant_wildcard"
            
            # instant_wildcard 폴더가 없으면 생성
            instant_txt_path.mkdir(parents=True, exist_ok=True)
            
            # save/instant_wildcard 폴더가 없으면 종료
            if not instant_json_path.exists():
                print("📁 save/instant_wildcard 폴더가 없습니다. 인스턴트 와일드카드 변환을 건너뜁니다.")
                return
            
            # 모든 JSON 파일 처리
            json_files = list(instant_json_path.glob("*.json"))
            converted_count = 0
            
            for json_file in json_files:
                try:
                    # JSON 파일 읽기
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    # 대응하는 TXT 파일 경로 생성 (확장자만 변경)
                    txt_filename = json_file.stem + ".txt"
                    txt_file_path = instant_txt_path / txt_filename
                    
                    # TXT 파일로 변환하여 저장
                    with open(txt_file_path, 'w', encoding='utf-8') as f:
                        for key, value in data.items():
                            # #{key}, {value} 형식으로 각 줄 작성
                            f.write(f"#{key}, {value}\n")
                    
                    converted_count += 1
                    print(f"✅ 인스턴트 와일드카드 변환 완료: {json_file.name} -> {txt_filename}")
                    
                except json.JSONDecodeError as e:
                    print(f"⚠️ JSON 파일 읽기 실패 ({json_file.name}): {e}")
                except Exception as e:
                    print(f"⚠️ 파일 변환 중 오류 ({json_file.name}): {e}")
            
            if converted_count > 0:
                print(f"📝 총 {converted_count}개의 인스턴트 와일드카드 파일을 TXT로 변환했습니다.")
                # 와일드카드 매니저에 리로드 요청
                self.context.wildcard_manager.reload_wildcards()
            else:
                print("📝 변환할 인스턴트 와일드카드 파일이 없습니다.")
                
        except Exception as e:
            print(f"❌ 인스턴트 와일드카드 동기화 중 오류 발생: {e}")