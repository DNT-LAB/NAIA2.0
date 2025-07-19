# ui/hooker_view.py
import os, json
from .hooker.safe_executer import SafeExecutor
from PyQt6.Qsci import QsciScintilla, QsciLexerPython
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel, 
    QFrame, QTextEdit, QPushButton, QSplitter, QGroupBox, QCheckBox, QComboBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QUrl
from PyQt6.QtGui import QFont, QColor, QDesktopServices
from core.prompt_context import PromptContext
from typing import Dict, List, Any, Optional
from PyQt6.QtWidgets import QDialog, QLineEdit, QDialogButtonBox
from ui.theme import DARK_STYLES 
import copy

class NewScriptDialog(QDialog):
    """새 스크립트 이름을 입력받는 커스텀 다이얼로그."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("새 스크립트 생성")
        self.setMinimumWidth(350)
        
        # 다크 테마 적용
        self.setStyleSheet(f"""
            QDialog {{ 
                background-color: #2B2B2B; 
            }}
            QLabel {{ 
                color: #FFFFFF;
                font-size: 20px; 
            }}
            QLineEdit {{ 
                background-color: #3C3F41; 
                border: 1px solid #555; 
                padding: 8px; 
                font-size: 20px;
                color: #FFFFFF;
                border-radius: 4px;
            }}
            QPushButton {{ 
                background-color: #1976D2; 
                color: white;
                font-weight: bold;
                padding: 8px 16px; 
                border: none; 
                border-radius: 4px; 
                font-size: 20px; 
            }}
            QPushButton:hover {{ 
                background-color: #1565C0; 
            }}
        """)

        layout = QVBoxLayout(self)
        
        label = QLabel("새 스크립트 파일명을 입력하세요 (.json 제외):")
        layout.addWidget(label)

        self.name_input = QLineEdit(self)
        layout.addWidget(self.name_input)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def get_script_name(self):
        return self.name_input.text().strip()

class TagDisplayWidget(QWidget):
    """태그 리스트를 시각적으로 표시하는 위젯"""
    
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.title = title
        self.tags = []
        self.highlighted_tags = []  # 새롭게 추가된 태그들
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(2)
        
        # 제목 라벨
        title_label = QLabel(self.title)
        title_label.setMaximumHeight(40)
        title_label.setStyleSheet("""
            QLabel {
                font-weight: bold;
                color: #FFFFFF;
                background-color: #3D3D3D;
                padding: 4px 8px;
                border-radius: 4px;
                margin-bottom: 2px;
            }
        """)
        layout.addWidget(title_label)
        
        # 태그 표시 영역
        self.tag_display = QTextEdit()
        self.tag_display.setReadOnly(True)
        self.tag_display.setMaximumHeight(180)  # 1.5배 증가 (120 -> 180)
        self.tag_display.setStyleSheet("""
            QTextEdit {
                background-color: #2D2D2D;
                border: 1px solid #555555;
                border-radius: 4px;
                color: #FFFFFF;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 20px;
                padding: 4px;
            }
        """)
        layout.addWidget(self.tag_display)
    
    def update_tags(self, tags: List[str], highlighted_tags: List[str] = None):
        """태그 리스트 업데이트 (하이라이트 지원)"""
        self.tags = tags.copy()
        self.highlighted_tags = highlighted_tags or []
        
        if not tags:
            self.tag_display.setHtml('<span style="color: #888888; font-style: italic;">Empty</span>')
            return
        
        html_parts = []
        for tag in tags:
            if tag in self.highlighted_tags:
                # 연노랑색으로 하이라이트
                html_parts.append(f'<span style="background-color: #FFFF99; color: #000000; padding: 1px 3px; border-radius: 2px;">{tag}</span>')
            else:
                html_parts.append(f'<span style="color: #FFFFFF;">{tag}</span>')
        
        html_content = ', '.join(html_parts)
        self.tag_display.setHtml(html_content)

    def update_tags_temp(self, before_tags: List[str], after_tags: List[str]):
        """검증 전과 후의 태그를 비교하여 변경점을 하이라이트하여 표시합니다."""
        set_before = set(before_tags)
        set_after = set(after_tags)

        added_tags = set_after - set_before
        removed_tags = set_before - set_after
        
        # 순서를 유지하기 위해 후(after) 태그 리스트를 기준으로 HTML 생성
        html_parts = []
        for tag in after_tags:
            if tag in added_tags:
                # 추가된 태그: 노란색 배경
                html_parts.append(f'<span style="background-color: #FFFF99; color: #000000; padding: 1px 3px; border-radius: 2px;">{tag}</span>')
            else:
                # 유지된 태그: 흰색
                html_parts.append(f'<span style="color: #FFFFFF;">{tag}</span>')

        # 삭제된 태그들을 맨 뒤에 추가
        for tag in sorted(list(removed_tags)):
            # 삭제된 태그: 회색 취소선
            html_parts.append(f'<span style="color: #888888; text-decoration: line-through;">{tag}</span>')

        if not html_parts:
            self.tag_display.setHtml('<span style="color: #888888; font-style: italic;">Empty</span>')
            return
            
        html_content = ', '.join(html_parts)
        self.tag_display.setHtml(html_content)


class PipelineStageWidget(QWidget):
    """파이프라인 단계별 정보를 표시하는 위젯"""
    def __init__(self, stage_name: str, app_context, hooker_view, parent=None):
        super().__init__(parent)
        self.stage_name = stage_name
        self.app_context = app_context
        self.hooker_view = hooker_view # ⬅️ hooker_view 참조 저장
        self.previous_context = None
        self.current_context = None
        self.init_ui()
    
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)  # 마진 최소화
        main_layout.setSpacing(4)  # 간격 최소화
        
        # 단계 제목
        stage_label = QLabel(f"📋 {self.stage_name}")
        stage_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                font-weight: bold;
                color: #4A9EFF;
                background-color: #1E1E1E;
                padding: 6px 10px;
                border-radius: 4px;
                border-left: 4px solid #4A9EFF;
            }
        """)
        main_layout.addWidget(stage_label)
        
        # 태그 표시 영역
        tags_frame = QFrame()
        tags_frame.setFrameStyle(QFrame.Shape.Box)
        tags_frame.setStyleSheet("""
            QFrame {
                background-color: #1A1A1A;
                border: 1px solid #444444;
                border-radius: 4px;
                padding: 2px;
            }
        """)
        frame_layout = QHBoxLayout(tags_frame)
        frame_layout.setContentsMargins(2, 2, 2, 2)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        frame_layout.addWidget(self.splitter)
        
        # Prefix Tags
        self.prefix_widget = TagDisplayWidget("Prefix Tags")
        self.splitter.addWidget(self.prefix_widget) 
        
        # Main Tags  
        self.main_widget = TagDisplayWidget("Main Tags")
        self.splitter.addWidget(self.main_widget) 
        
        # Postfix Tags
        self.postfix_widget = TagDisplayWidget("Postfix Tags")
        self.splitter.addWidget(self.postfix_widget)
        self.splitter.setMinimumHeight(240)
        self.splitter.setSizes([120, 260, 120])
        
        main_layout.addWidget(tags_frame)

        # ⬇️ 캐릭터 정보 표시를 위한 컨테이너 추가
        self.character_display_container = QFrame()
        self.character_display_container.setStyleSheet("QFrame { border: 1px solid #4D82B8; border-radius: 4px; }")
        self.character_display_layout = QVBoxLayout(self.character_display_container)
        self.character_display_layout.setContentsMargins(5, 5, 5, 5)
        self.character_display_layout.setSpacing(4)
        main_layout.addWidget(self.character_display_container)
        self.character_display_container.setVisible(False) # ⬅️ 기본적으로 숨김
        
        # Removed Tags (2단계 이후에만 표시)
        self.removed_widget = TagDisplayWidget("Removed Tags")
        self.removed_widget.tag_display.setMaximumHeight(60)
        self.removed_widget.tag_display.setStyleSheet("""
            QTextEdit {
                background-color: #2D1A1A;
                border: 1px solid #AA5555;
                border-radius: 4px;
                color: #FFAAAA;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 20px;
                padding: 4px;
            }
        """)
        main_layout.addWidget(self.removed_widget)
        self.toggle_button = QPushButton("▼ 사용자 조작 영역 (접기)")
        self.toggle_button.setStyleSheet("""
            QPushButton {
                font-weight: bold;
                color: #DDDDDD;
                background-color: #3D3D3D;
                border: 1px solid #555555;
                padding: 5px;
                text-align: left;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #4A4A4A;
            }
        """)
        
        self.user_content_area = QFrame()
        self.user_content_area.setFrameShape(QFrame.Shape.StyledPanel)
        self.user_content_area.setStyleSheet("""
            QFrame {
                border: 1px solid #444;
                border-radius: 4px;
                background-color: #2A2A2A;
            }
        """)
        
        user_layout = QVBoxLayout(self.user_content_area)
        user_layout.setSpacing(5)

        # 1. Scintilla 위젯을 담을 컨테이너(래퍼) 생성
        scintilla_container = QWidget()
        scintilla_container.setFixedHeight(340) # ⬅️ 컨테이너의 높이를 원하는 값으로 고정

        # 2. 컨테이너 내부 레이아웃 설정 (여백과 간격 0으로 설정)
        container_layout = QVBoxLayout(scintilla_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        # 3. Scintilla 위젯 생성 및 설정 (여기서는 높이 설정 제거)
        self.command_input = QsciScintilla()
        self.command_input.setLexer(QsciLexerPython(self.command_input))
        self.command_input.setUtf8(True)
        self.command_input.setFont(QFont("Consolas", 11))
        self.command_input.setAutoIndent(True)
        self.command_input.setIndentationsUseTabs(False)
        self.command_input.setTabWidth(4)
        self.command_input.setMarginsBackgroundColor(QColor("#333333"))
        self.command_input.setMarginLineNumbers(0, True)
        self.command_input.setMarginWidth(0, "000")
        
        # 4. Scintilla 위젯을 컨테이너의 레이아웃에 추가
        container_layout.addWidget(self.command_input)

        # 5. 최종적으로 컨테이너를 메인 레이아웃에 추가
        user_layout.addWidget(scintilla_container)

        # 2. 실행 버튼
        self.verify_button = QPushButton("코드 검증") # ⬅️ 텍스트 및 변수명 변경
        self.verify_button.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; padding: 5px; }")
        self.verify_button.clicked.connect(self.on_verify_clicked) # ⬅️ 연결 메서드명 변경
        user_layout.addWidget(self.verify_button)

        # 3. 결과 출력창
        self.result_output = QTextEdit()
        self.result_output.setReadOnly(True)
        self.result_output.setStyleSheet("QTextEdit { background-color: #1A1A1A; color: #A0A0A0}")
        self.result_output.setFont(QFont("Pretendard", 11))
        self.result_output.setMinimumHeight(110)
        user_layout.addWidget(self.result_output)
        
        # 버튼 클릭 시 toggle_user_area 함수 호출
        self.toggle_button.clicked.connect(self.toggle_user_area)

        main_layout.addWidget(self.toggle_button)
        main_layout.addWidget(self.user_content_area)
        
        # 초기에 접힌 상태로 시작하려면 아래 두 줄의 주석을 해제하세요.
        self.toggle_button.setText("▶ 사용자 조작 영역 (펼치기)")
        self.user_content_area.setVisible(False)

    def toggle_user_area(self):
        # 콘텐츠 영역의 현재 표시 상태를 확인하여 토글
        is_visible = self.user_content_area.isVisible()
        self.user_content_area.setVisible(not is_visible)
        
        # 버튼 텍스트의 화살표 아이콘 변경
        if is_visible:
            self.toggle_button.setText("▶ 사용자 조작 영역 (펼치기)")
        else:
            self.toggle_button.setText("▼ 사용자 조작 영역 (접기)")

    def update_widget(self, updated_vars: dict):
        """검증된 태그 목록으로 현재 위젯의 태그 표시를 임시 업데이트합니다."""
        
        # 검증 전(before) 태그 목록 가져오기
        before_prefix = self.current_context.prefix_tags
        before_main = self.current_context.main_tags
        before_postfix = self.current_context.postfix_tags
        before_removed = self.current_context.removed_tags if hasattr(self.current_context, 'removed_tags') else []

        # 검증 후(after) 태그 목록 가져오기
        after_prefix = updated_vars.get('prefix_tags', [])
        after_main = updated_vars.get('main_tags', [])
        after_postfix = updated_vars.get('postfix_tags', [])
        after_removed = updated_vars.get('removed_tags', [])

        # 새로 만든 update_tags_temp 메서드를 사용하여 위젯 업데이트
        self.prefix_widget.update_tags_temp(before_prefix, after_prefix)
        self.main_widget.update_tags_temp(before_main, after_main)
        self.postfix_widget.update_tags_temp(before_postfix, after_postfix)
        self.removed_widget.update_tags_temp(before_removed, after_removed)

    def update_context(self, context: PromptContext, previous_context: PromptContext = None):
        """컨텍스트 정보로 위젯 업데이트"""
        self.current_context = copy.deepcopy(context)
        self.previous_context = previous_context
        
        # 이전 단계와 비교하여 새로 추가된 태그 찾기
        if previous_context:
            prev_prefix = set(previous_context.prefix_tags)
            prev_main = set(previous_context.main_tags)
            prev_postfix = set(previous_context.postfix_tags)
            
            new_prefix = [tag for tag in context.prefix_tags if tag not in prev_prefix]
            new_main = [tag for tag in context.main_tags if tag not in prev_main]
            new_postfix = [tag for tag in context.postfix_tags if tag not in prev_postfix]
        else:
            new_prefix = new_main = new_postfix = []
        
        # 태그 위젯 업데이트
        self.prefix_widget.update_tags(context.prefix_tags, new_prefix)
        self.main_widget.update_tags(context.main_tags, new_main)
        self.postfix_widget.update_tags(context.postfix_tags, new_postfix)
        
        # Removed Tags 업데이트 (있는 경우)
        if self.removed_widget and hasattr(context, 'removed_tags'):
            # After-wildcard 단계인 경우, 이전 단계의 removed_tags 제외하고 새로 제거된 것만 표시
            if self.stage_name == "After-wildcard" and previous_context and hasattr(previous_context, 'removed_tags'):
                # 이전 단계에서 이미 제거된 태그들 제외
                prev_removed = set(previous_context.removed_tags)
                new_removed_tags = [tag for tag in context.removed_tags if tag not in prev_removed]
                self.removed_widget.update_tags(new_removed_tags)
            else:
                # Post-process 단계는 그대로 표시
                self.removed_widget.update_tags(context.removed_tags)

    def set_input_enabled(self, enabled: bool):
        """스크립트 입력창의 활성화/비활성화 상태를 설정합니다."""
        self.command_input.setReadOnly(not enabled)
        # 비활성화 상태일 때 시각적으로 구분되도록 스타일 변경
        if enabled:
            self.command_input.setStyleSheet("background-color: #1E1E1E; color: #D0D0D0;")
        else:
            self.command_input.setStyleSheet("background-color: #2D2D2D; color: #888888;")

    def on_verify_clicked(self):
        """'코드 검증' 버튼 클릭 시 호출되는 슬롯."""
        if not self.current_context:
            self.result_output.setText("오류: 먼저 파이프라인을 실행하여 컨텍스트를 로드해야 합니다.")
            return

        # ⬇️ HookerView의 중앙 집중식 메서드를 호출하여 모든 변수를 한번에 가져옴
        allowed_vars = self.hooker_view._get_script_variables(self.current_context)
        variable_info_text = self._generate_variable_list_text(allowed_vars)

        code = self.command_input.text()
        if not code.strip():
            self.result_output.setText(variable_info_text + "정보: 실행할 코드를 입력하세요.")
            return

        executor = SafeExecutor(allowed_vars)
        output, updated_vars, success = executor.execute(code)

        if success:
            result_text = "--- 실행 출력 ---\n"
            result_text += output if output else "(출력 없음)"
            self.result_output.setText(variable_info_text + result_text)
            self.update_widget(updated_vars)
        else:
            self.result_output.setText(variable_info_text + output)

    def set_character_display_visibility(self, visible: bool):
        """캐릭터 정보 컨테이너의 가시성을 설정합니다."""
        self.character_display_container.setVisible(visible)

    def _generate_variable_list_text(self, available_vars: dict) -> str:
        """사용 가능한 변수 목록을 설명하는 텍스트를 생성합니다."""
        # 기본 변수와 필터 변수 분리
        core_vars = ['prefix_tags', 'main_tags', 'postfix_tags', 'removed_tags', 'characters', 'character_uc']
        
        script_vars = {k: v for k, v in available_vars.items() if k in core_vars}
        filter_vars = {k: v for k, v in available_vars.items() if k not in core_vars}

        output_text = "--- 사용 가능 변수 ---\n"
        output_text += ", ".join(sorted(script_vars.keys())) + "\n"
        
        if filter_vars:
            output_text += "--- 사용 가능 필터 ---\n"
            # 필터는 3개씩 묶어서 줄바꿈하여 보기 좋게 표시
            sorted_filters = sorted(filter_vars.keys())
            filter_lines = [", ".join(sorted_filters[i:i+3]) for i in range(0, len(sorted_filters), 3)]
            output_text += "\n".join(filter_lines) + "\n\n"
            
        return output_text

    def update_character_display(self, char_data: dict):
        """캐릭터 모듈의 데이터로 UI를 업데이트합니다."""
        # 1. 기존에 있던 라벨들 모두 삭제
        for i in reversed(range(self.character_display_layout.count())): 
            widget = self.character_display_layout.itemAt(i).widget()
            if widget is not None:
                widget.deleteLater()

        # 2. char_data에서 활성화된 캐릭터 프롬프트 가져오기
        active_characters = char_data.get('characters', [])
        if not active_characters:
            return

        # 3. 컨테이너 높이 동적 설정
        container_height = len(active_characters) * 56
        self.character_display_container.setMaximumHeight(container_height)

        # 4. 각 캐릭터에 대한 라벨 생성 및 추가
        for i, prompt in enumerate(active_characters):
            # 라벨 텍스트가 너무 길면 잘라내기
            display_prompt = prompt
            
            char_label = QLabel(f"C{i+1}: {display_prompt}")
            char_label.setFixedHeight(50)
            char_label.setWordWrap(True) # 자동 줄바꿈
            char_label.setStyleSheet("""
                QLabel {
                    background-color: #2C3E50;
                    color: #ECF0F1;
                    padding: 8px;
                    border-radius: 3px;
                    font-size: 18px;
                }
            """)
            self.character_display_layout.addWidget(char_label)


class HookerView(QWidget):
    """PromptProcessor 파이프라인을 실시간으로 감시하는 위젯 (RightView의 탭으로 사용)"""
    
    # 커스텀 시그널
    pipeline_monitored = pyqtSignal(dict)
    
    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.parent_right_view = parent
        
        # 파이프라인 단계별 위젯들
        self.stage_widgets = {}
        
        # 파이프라인 감시 상태
        self.is_monitoring = False
        self.captured_contexts = {}  # 단계별 컨텍스트 저장
        
        # 원본 파이프라인 메서드 참조 저장
        self.original_methods = {}
        self._is_syncing = False
        # ⬇️ 스크립트 관리용 변수 및 경로 추가
        self.save_dir = "ui/hooker/save"
        self.hooker_dir = "ui/hooker"
        self.is_edit_mode = False
        self.script_before_edit = None
        
        self.is_naid4_mode = False
        self.char_module = None
        self.filter_variables = {}
        
        self.init_ui()
        self.setup_event_connections()
        self._populate_script_combobox() # ⬅️ 초기 스크립트 목록 로드
    
    def init_ui(self):
        """UI 초기화"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)
        
        # 상단 컨트롤 패널
        control_panel = self.create_control_panel()
        main_layout.addWidget(control_panel)
        
        # 스크롤 가능한 파이프라인 단계 표시 영역
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #1A1A1A;
                border: 1px solid #333333;
                border-radius: 6px;
            }
        """)
        
        # 단계별 위젯들을 담을 컨테이너
        stages_container = QWidget()
        stages_container.setStyleSheet("background-color: #2B2B2B;")
        stages_layout = QVBoxLayout(stages_container)
        stages_layout.setSpacing(4)
        stages_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        # 파이프라인 단계별 위젯 생성
        stage_names = ["Pre-process", "Post-process", "After-wildcard", "Final-process"]
        for stage_name in stage_names:
            stage_widget = PipelineStageWidget(stage_name, self.app_context, hooker_view=self, parent=self)
            self.stage_widgets[stage_name] = stage_widget
            stages_layout.addWidget(stage_widget)

        all_splitters = [w.splitter for w in self.stage_widgets.values()]
        for splitter in all_splitters:
            # splitterMoved 시그널을 동기화 슬롯에 연결
            splitter.splitterMoved.connect(self._synchronize_splitters)
        
        scroll_area.setWidget(stages_container)
        main_layout.addWidget(scroll_area)
    
    def _synchronize_splitters(self, pos, index):
        """하나의 스플리터가 움직이면 다른 모든 스플리터를 동기화합니다."""
        if self._is_syncing:
            return  # 재귀적 호출 방지
            
        self._is_syncing = True
        try:
            # 신호를 보낸 스플리터(움직인 스플리터)를 찾음
            source_splitter = self.sender()
            if not source_splitter:
                return

            # 움직인 스플리터의 현재 크기(비율)를 가져옴
            sizes = source_splitter.sizes()
            
            # 다른 모든 스플리터에 동일한 크기를 적용
            for stage_widget in self.stage_widgets.values():
                if stage_widget.splitter is not source_splitter:
                    stage_widget.splitter.setSizes(sizes)
        finally:
            self._is_syncing = False # 플래그 리셋

    def create_control_panel(self) -> QWidget:
        """새로운 스크립트 관리 컨트롤 패널 생성"""
        panel = QFrame()
        layout = QHBoxLayout(panel)
        layout.setSpacing(10)
        layout.setContentsMargins(0, 5, 0, 5)

        # 1. 후킹 기능 활성화 체크박스
        self.enable_hooking_checkbox = QCheckBox("후킹 기능 활성화")
        self.enable_hooking_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'] + "font-size: 18px;")
        self.enable_hooking_checkbox.toggled.connect(self._on_enable_hooking_toggled)
        layout.addWidget(self.enable_hooking_checkbox)

        layout.addStretch()

        # 2. 스크립트 선택 UI
        script_label = QLabel("스크립트:")
        script_label.setStyleSheet(DARK_STYLES['label_style'] + "font-size: 18px;")
        layout.addWidget(script_label)
        
        self.script_combo = QComboBox()
        self.script_combo.setMinimumWidth(300) # ⬅️ 너비 1.5배 증가
        self.script_combo.setStyleSheet(DARK_STYLES['compact_combobox'] + "font-size: 18px;")
        self.script_combo.currentIndexChanged.connect(self._on_script_selected)
        layout.addWidget(self.script_combo)

        # 3. 버튼들
        button_style = DARK_STYLES['secondary_button'] + "font-size: 18px; padding: 8px 16px;"

        self.save_button = QPushButton("저장")
        self.save_button.setStyleSheet(button_style)
        self.save_button.clicked.connect(self._on_save_clicked)
        self.save_button.setEnabled(False)
        layout.addWidget(self.save_button)

        self.edit_button = QPushButton("수정")
        self.edit_button.setStyleSheet(button_style)
        self.edit_button.clicked.connect(self._on_edit_clicked)
        layout.addWidget(self.edit_button)
        
        self.add_button = QPushButton("추가")
        self.add_button.setStyleSheet(button_style)
        self.add_button.clicked.connect(self._on_add_clicked)
        layout.addWidget(self.add_button)

        self.open_folder_button = QPushButton("폴더 열기")
        self.open_folder_button.setStyleSheet(button_style)
        self.open_folder_button.clicked.connect(self._on_open_folder_clicked)
        layout.addWidget(self.open_folder_button)
        
        return panel
    
    def setup_event_connections(self):
        """이벤트 연결 설정"""
        if self.app_context:
            self.app_context.subscribe("prompt_generated", self.on_prompt_generated)
            print("🔗 Hooker 뷰: 이벤트 구독 완료")
    
    def toggle_monitoring(self):
        """파이프라인 감시 토글"""
        if not self.is_monitoring:
            self.start_monitoring()
        else:
            self.stop_monitoring()
    
    def start_monitoring(self):
        """파이프라인 감시 시작"""
        self._load_filter_files()
        if not self.app_context:
            print("❌ AppContext가 없어 감시를 시작할 수 없습니다.")
            return
        
        try:
            # PromptProcessor 인스턴스 찾기
            if hasattr(self.app_context, 'main_window') and hasattr(self.app_context.main_window, 'prompt_gen_controller'):
                processor = self.app_context.main_window.prompt_gen_controller.processor

                # ⬇️ NAI D4 모드 체크 및 캐릭터 모듈 참조 저장 (1회 실행)
                try:
                    self.is_naid4_mode = (self.app_context.get_api_mode() == "NAI" and 
                                          "NAID4" in self.app_context.main_window.model_combo.currentText())
                    
                    if self.is_naid4_mode:
                        self.char_module = self.app_context.middle_section_controller.get_module_instance("CharacterModule")
                        print("✅ NAI D4 모드가 활성화되어 캐릭터 모듈에 연결합니다.")
                except Exception as e:
                    print(f"⚠️ 캐릭터 모듈 연결 중 오류 발생: {e}")
                    self.is_naid4_mode = False
                    self.char_module = None

                # 각 스테이지 위젯에 가시성 전파
                for widget in self.stage_widgets.values():
                    widget.set_character_display_visibility(self.is_naid4_mode)
                
                # 원본 메서드들을 후킹
                self.hook_processor_methods(processor)
                
                self.is_monitoring = True
                self.enable_hooking_checkbox.setChecked(True) # ⬅️ UI 동기화
                print("🔍 파이프라인 감시 시작됨")
                
        except Exception as e:
            print(f"❌ 파이프라인 감시 시작 실패: {e}")
    
    def stop_monitoring(self):
        """파이프라인 감시 중지"""
        try:
            # 원본 메서드들 복원
            self.restore_original_methods()
            
            self.is_monitoring = False
            self.enable_hooking_checkbox.setChecked(False) # ⬅️ UI 동기화
            print("🔍 파이프라인 감시 중지됨")
            
        except Exception as e:
            print(f"❌ 파이프라인 감시 중지 실패: {e}")
    
    def hook_processor_methods(self, processor):
        """PromptProcessor의 메서드들을 후킹"""
        # 원본 메서드들 저장
        self.original_methods = {
            '_step_2_fit_resolution': processor._step_2_fit_resolution,
            '_run_hooks': processor._run_hooks,
            '_step_3_expand_wildcards': processor._step_3_expand_wildcards
        }
        
        # 후킹된 메서드들로 교체
        processor._step_2_fit_resolution = self.hooked_step_2_fit_resolution
        processor._run_hooks = self.hooked_run_hooks
        processor._step_3_expand_wildcards = self.hooked_step_3_expand_wildcards
        
        # processor 참조 저장
        self.processor = processor
    
    def restore_original_methods(self):
        """원본 메서드들 복원"""
        if hasattr(self, 'processor') and self.original_methods:
            for method_name, original_method in self.original_methods.items():
                setattr(self.processor, method_name, original_method)
    
    def hooked_step_2_fit_resolution(self, context):
        """_step_2_fit_resolution 후킹"""
        # 1. 원본 메서드 실행
        result = self.original_methods['_step_2_fit_resolution'](context)
        
        # 2. Pre-process 단계의 사용자 코드 실행 및 결과 적용
        modified_context = self._execute_user_script_for_stage("Pre-process", result)
        
        # 3. 최종 결과를 UI에 캡처
        self.capture_context("Pre-process", modified_context)
        
        # 4. 다음 단계로 수정된 컨텍스트 전달
        return modified_context
    
    def hooked_run_hooks(self, hook_point, context):
        """_run_hooks 후킹"""
        
        # 1. 처리할 훅 포인트가 아니면 원본 메서드만 실행하고 반환
        if hook_point not in ["post_processing", "final_hookpoint"]:
            return self.original_methods['_run_hooks'](hook_point, context)
            
        # 2. 훅 포인트에 해당하는 원본 메서드 실행
        result = self.original_methods['_run_hooks'](hook_point, context)
        
        # 3. 훅 포인트에 따라 분기하여 처리
        if hook_point == "post_processing":
            # "Post-process" 단계의 사용자 코드 실행 및 결과 적용
            stage_name = "Post-process"
            previous_context = self.captured_contexts.get("Pre-process")
            modified_context = self._execute_user_script_for_stage(stage_name, result)

            # 최종 결과를 UI에 캡처
            self.capture_context(stage_name, modified_context, previous_context)
            
            # 다음 단계로 수정된 컨텍스트 전달
            return modified_context

        elif hook_point == "final_hookpoint":
            # "Final-process" 단계의 사용자 코드 실행 및 결과 적용
            stage_name = "Final-process"
            previous_context = self.captured_contexts.get("After-wildcard")
            modified_context = self._execute_user_script_for_stage(stage_name, result)

            # 최종 결과를 UI에 캡처
            self.capture_context(stage_name, modified_context, previous_context)

            # ⬇️ 최종 단계가 끝난 후, 캐릭터 모듈의 UI 업데이트 메서드 호출
            if self.is_naid4_mode and self.char_module and not self.char_module.reroll_on_generate_checkbox.isChecked():
                print("🔄️ Hooker 파이프라인 완료. 캐릭터 모듈 UI를 최종 갱신합니다.")
                self.char_module.hooker_update_prompt()

            # 다음 단계로 수정된 컨텍스트 전달
            return modified_context
    
    def hooked_step_3_expand_wildcards(self, context):
        """_step_3_expand_wildcards 후킹"""
        # 1. 원본 메서드 실행
        result = self.original_methods['_step_3_expand_wildcards'](context)
        
        # 2. After-wildcard 단계의 사용자 코드 실행 및 결과 적용
        modified_context = self._execute_user_script_for_stage("After-wildcard", result)

        # 3. 최종 결과를 UI에 캡처
        self.capture_context("After-wildcard", modified_context, self.captured_contexts.get("Post-process"))
        
        # 4. 다음 단계로 수정된 컨텍스트 전달
        return modified_context
    
    def capture_context(self, stage_name: str, context: PromptContext, previous_context: PromptContext = None):
        """특정 단계의 컨텍스트 캡처 및 UI 업데이트"""
        # 컨텍스트 저장
        self.captured_contexts[stage_name] = copy.deepcopy(context)
        
        # UI 업데이트 (메인 스레드에서 실행)
        if stage_name in self.stage_widgets:
            widget = self.stage_widgets[stage_name]
            widget.update_context(context, previous_context)
            
            # ⬇️ 캐릭터 정보 표시 업데이트 로직 추가
            if self.is_naid4_mode and self.char_module:
                character_data = self.char_module.modifiable_clone
                widget.update_character_display(character_data)
        
        print(f"🔍 [{stage_name}] 컨텍스트 캡처됨 - Prefix: {len(context.prefix_tags)}, Main: {len(context.main_tags)}, Postfix: {len(context.postfix_tags)}")
    
    def clear_all_data(self):
        """모든 데이터 초기화"""
        self.captured_contexts.clear()
        
        # 모든 단계 위젯 초기화
        for stage_widget in self.stage_widgets.values():
            empty_context = PromptContext(
                source_row=None,
                settings={},
                prefix_tags=[],
                main_tags=[],
                postfix_tags=[],
                removed_tags=[]
            )
            stage_widget.update_context(empty_context)
        
        print("🧹 파이프라인 감시 데이터 초기화됨")
    
    def on_prompt_generated(self, data: dict):
        """프롬프트 생성 완료 이벤트 핸들러"""
        if self.is_monitoring:
            print("🔍 프롬프트 생성 완료 - 파이프라인 데이터 유지됨")
    
    def cleanup(self):
        """정리 작업"""
        if self.is_monitoring:
            self.stop_monitoring()
        print("🧹 Hooker 뷰 정리 완료")
            
    def _execute_user_script_for_stage(self, stage_name: str, context: PromptContext) -> PromptContext:
        """특정 스테이지의 사용자 코드를 실행하고, 변경된 컨텍스트를 반환합니다."""
        widget = self.stage_widgets.get(stage_name)
        if not widget:
            return context

        code = widget.command_input.text()

        try:
            # ⬇️ 중앙 집중식 메서드를 호출하여 변수 목록을 가져옴 (오류 수정)
            allowed_vars = self._get_script_variables(context)
            variable_info_text = widget._generate_variable_list_text(allowed_vars)

            if not code.strip():
                widget.result_output.setText(variable_info_text.strip())
                return context

            widget.result_output.clear()

            executor = SafeExecutor(allowed_vars)
            output, updated_vars, success = executor.execute(code)

            if success:
                context.prefix_tags = updated_vars['prefix_tags']
                context.main_tags = updated_vars['main_tags']
                context.postfix_tags = updated_vars['postfix_tags']
                context.removed_tags = updated_vars['removed_tags']

                if self.is_naid4_mode and self.char_module:
                    modified_char_prompts = updated_vars.get('characters', [])
                    modified_char_uc = updated_vars.get('character_uc', [])
                    joined_char_prompts = [','.join(tags) for tags in modified_char_prompts]
                    joined_char_uc = [','.join(tags) for tags in modified_char_uc]
                    self.char_module.modifiable_clone['characters'] = joined_char_prompts
                    self.char_module.modifiable_clone['uc'] = joined_char_uc

                widget.result_output.setText(variable_info_text + f"--- 자동 실행 완료 ---\n{output if output else '(출력 없음)'}")
                return context
            else:
                widget.result_output.setText(variable_info_text + output)
                return context

        except Exception as e:
            widget.result_output.setText(f"치명적인 오류 발생: {e}")
            return context

    def _load_filter_files(self):
        """'ui/hooker/filter_dict' 폴더에서 텍스트 파일을 로드하여 변수로 만듭니다."""
        filter_dir = "ui/hooker/filter_dict"
        if not os.path.exists(filter_dir):
            print(f"⚠️ 필터 디렉토리({filter_dir})를 찾을 수 없습니다.")
            return

        for filename in os.listdir(filter_dir):
            if filename.endswith(".txt"):
                # 파일명에서 확장자를 제거하여 변수명으로 사용
                var_name = os.path.splitext(filename)[0]
                try:
                    with open(os.path.join(filter_dir, filename), 'r', encoding='utf-8') as f:
                        # 각 라인을 읽어 리스트로 저장 (공백 라인 제외)
                        lines = [line.strip() for line in f if line.strip()]
                        self.filter_variables[var_name] = lines
                        print(f"✅ 필터 로드: '{var_name}' ({len(lines)}개 항목)")
                except Exception as e:
                    print(f"❌ 필터 파일 '{filename}' 로드 실패: {e}")

    def _on_enable_hooking_toggled(self, checked):
        """'후킹 기능 활성화' 체크박스 토글 시 호출"""
        if checked:
            if not self.is_monitoring:
                self.start_monitoring()
        else:
            if self.is_monitoring:
                self.stop_monitoring()

    def _populate_script_combobox(self):
        """'save' 폴더를 스캔하여 콤보박스를 채웁니다."""
        os.makedirs(self.save_dir, exist_ok=True)
        
        scripts = [f.replace(".json", "") for f in os.listdir(self.save_dir) if f.endswith(".json")]
        
        # ⬇️ 스크립트가 하나도 없으면 default.json 생성
        if not scripts:
            default_path = os.path.join(self.save_dir, "default.json")
            with open(default_path, 'w', encoding='utf-8') as f:
                json.dump({}, f)
            print("ℹ️ 스크립트가 없어 'default.json'을 생성했습니다.")
            scripts.append("default")

        self.script_combo.blockSignals(True)
        self.script_combo.clear()
        self.script_combo.addItems(sorted(scripts))
        self.script_combo.blockSignals(False)
        
        if self.script_combo.count() > 0:
            self._on_script_selected(0)

    def _on_script_selected(self, index):
        """콤보박스에서 스크립트를 선택했을 때 호출"""
        if self.is_edit_mode: return
        
        # ⬇️ 스크립트 선택 시 항상 입력창 비활성화
        for widget in self.stage_widgets.values():
            widget.set_input_enabled(False)
            
        script_name = self.script_combo.currentText()
        if script_name:
            self._load_script(script_name)

    def _load_script(self, script_name):
        """스크립트 파일의 내용을 UI에 로드합니다."""
        file_path = os.path.join(self.save_dir, f"{script_name}.json")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                script_data = json.load(f)
            
            for stage_name, widget in self.stage_widgets.items():
                code = script_data.get(stage_name, "")
                widget.command_input.setText(code)
            print(f"✅ 스크립트 '{script_name}' 로드 완료.")
        except Exception as e:
            print(f"❌ 스크립트 '{script_name}' 로드 실패: {e}")
            for widget in self.stage_widgets.values():
                widget.command_input.clear()
    
    def _toggle_edit_mode(self, enable):
        """UI의 편집/일반 모드를 전환합니다."""
        self.is_edit_mode = enable
        self.script_combo.setEnabled(not enable)
        self.add_button.setEnabled(not enable)
        self.save_button.setEnabled(enable)
        
        # ⬇️ 모든 자식 위젯의 입력창 상태 변경
        for widget in self.stage_widgets.values():
            widget.set_input_enabled(enable)
        
        if enable:
            self.script_before_edit = self.script_combo.currentText()
            self.edit_button.setText("취소")
        else:
            self.edit_button.setText("수정")
            if self.script_before_edit:
                if self.script_combo.currentText() != self.script_before_edit:
                     self.script_combo.setCurrentText(self.script_before_edit)
                else:
                    self._load_script(self.script_before_edit)
                self.script_before_edit = None
    
    def _on_save_clicked(self):
        """'저장' 버튼 클릭 시, 현재 스크립트를 파일에 저장합니다."""
        script_name = self.script_combo.currentText()
        if not script_name: return

        script_data = {stage: widget.command_input.text() for stage, widget in self.stage_widgets.items()}
        file_path = os.path.join(self.save_dir, f"{script_name}.json")

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(script_data, f, indent=4)
            print(f"✅ 스크립트 '{script_name}' 저장 완료.")
        except Exception as e:
            print(f"❌ 스크립트 '{script_name}' 저장 실패: {e}")
        
        self._toggle_edit_mode(False) # 저장 후 편집 모드 종료

    def _on_edit_clicked(self):
        """'수정'/'취소' 버튼 클릭 시 모드를 전환합니다."""
        self._toggle_edit_mode(not self.is_edit_mode)

    def _on_add_clicked(self):
        """'추가' 버튼 클릭 시, 새 스크립트 생성 다이얼로그를 엽니다."""
        dialog = NewScriptDialog(self)
        if dialog.exec():
            new_name = dialog.get_script_name()
            if not new_name: return
            
            file_path = os.path.join(self.save_dir, f"{new_name}.json")
            if os.path.exists(file_path):
                print(f"⚠️ 이미 존재하는 스크립트명입니다: {new_name}")
                return
            
            # 새 빈 스크립트 파일 생성
            with open(file_path, 'w') as f:
                json.dump({}, f)

            self._populate_script_combobox()
            self.script_combo.setCurrentText(new_name)

    def _on_open_folder_clicked(self):
        """'폴더 열기' 버튼 클릭 시, ui/hooker 폴더를 엽니다."""
        os.makedirs(self.hooker_dir, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.hooker_dir))

    def _get_script_variables(self, context: PromptContext) -> dict:
        """스크립트 실행에 필요한 모든 변수가 포함된 딕셔너리를 반환합니다."""
        allowed_vars = {
            **self.filter_variables,
            'prefix_tags': context.prefix_tags,
            'main_tags': context.main_tags,
            'postfix_tags': context.postfix_tags,
            'removed_tags': getattr(context, 'removed_tags', []), 
        }

        if self.is_naid4_mode and self.char_module:
            char_data_clone = self.char_module.modifiable_clone
            char_prompts = [s.split(',') for s in char_data_clone.get('characters', [])]
            char_uc = [s.split(',') for s in char_data_clone.get('uc', [])]
            allowed_vars['characters'] = char_prompts
            allowed_vars['character_uc'] = char_uc

        return allowed_vars