from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, 
    QCheckBox, QPushButton, QFrame, QScrollArea
)
from PyQt6.QtCore import Qt
from interfaces.base_module import BaseMiddleModule
from interfaces.mode_aware_module import ModeAwareModule
from core.prompt_context import PromptContext
from ui.theme import get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size
from ui.modern_menu import setModernStyle
from typing import Dict, Any, List
import re

class PromptListModifierModule(BaseMiddleModule, ModeAwareModule):
    """
    🔀 조건부 프롬프트 모듈
    사용자가 정의한 규칙에 따라 prefix_tags, main_tags, postfix_tags 리스트를 동적으로 수정합니다.
    """

    def __init__(self):
        BaseMiddleModule.__init__(self)
        ModeAwareModule.__init__(self)

        # ModeAwareModule 필수 속성
        self.settings_base_filename = "PromptListModifierModule"
        self.current_mode = "NAI"
        
        # 호환성 설정
        self.NAI_compatibility = True
        self.WEBUI_compatibility = True
        
        # UI 위젯 인스턴스 변수
        self.enable_checkbox = None
        self.rules_textedit = None
        self.log_textedit = None
        self.widget = None

    def get_title(self) -> str:
        return "🔀 조건부 프롬프트"

    def get_order(self) -> int:
        return 901
    
    def get_module_name(self) -> str:
        return self.get_title()

    def create_widget(self, parent: QWidget) -> QWidget:
        """UI 위젯 생성"""
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)
        layout.setContentsMargins(8, 8, 8, 8)

        # 동적 스타일 가져오기
        dynamic_styles = get_dynamic_styles()
        
        # 스타일 정의
        textbox_style = dynamic_styles['compact_textedit']
        rules_textbox_style = dynamic_styles['compact_textedit']
        label_style = f"""
            QLabel {{
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-size: {get_scaled_font_size(19)}px;
                color: #FFFFFF;
                font-weight: 500;
            }}
        """

        # 활성화 체크박스
        self.enable_checkbox = QCheckBox("조건부 프롬프트 활성화")
        checkbox_style = f"""
            QCheckBox {{
                background-color: transparent;
                spacing: 8px;
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-size: {get_scaled_font_size(19)}px;
                color: #FFFFFF;
            }}
            QCheckBox::indicator {{
                width: {get_scaled_font_size(18)}px;
                height: {get_scaled_font_size(18)}px;
                border: 1px solid #666666;
                border-radius: 3px;
                background-color: #2B2B2B;
            }}
            QCheckBox::indicator:checked {{
                background-color: #1976D2;
                border: 1px solid #1976D2;
            }}
            QCheckBox::indicator:hover {{
                border: 1px solid #42A5F5;
            }}
        """
        self.enable_checkbox.setStyleSheet(checkbox_style)
        layout.addWidget(self.enable_checkbox)

        # 규칙 입력 섹션
        rules_label = QLabel("규칙 정의:")
        rules_label.setStyleSheet(label_style)
        layout.addWidget(rules_label)

        self.rules_textedit = QTextEdit()
        self.rules_textedit.setFixedHeight(200)
        self.rules_textedit.setStyleSheet(rules_textbox_style)
        setModernStyle(self.rules_textedit)
        self.rules_textedit.setPlaceholderText(
            "규칙 예시:\n"
            "(e):prefix+=nsfw^rating:explicit,\n"
            "(q):prefix+=\"nsfw, rating:questionable\",\n"
            "(full body):\"full body=upper body\",\n"
            "(sweat):sweat=sweat^sweatdrop^steam,\n"
            "(*1girl&s):main+=smiling,\n"
            "# 이 줄은 주석으로 무시됩니다\n\n"
            "구문 형식: (조건):실행문\n"
            "• 조건: tag (포함), ~tag (불포함), *tag (정확 일치), ~!tag (정확 불일치)\n"
            "• 등급: e, q, s, g (일치), ~e, ~q, ~s, ~g (불일치)\n"
            "• 논리 연산자: & (AND), | (OR)\n"
            "• 실행문: = (대체), += (리스트 추가), +: (추가)\n"
            "• 복수 태그: ^ 구분자 또는 \"쉼표, 구분\" (자동 리스트화)\n"
            "• 따옴표: 선택사항 (쉼표 포함 시 필수)\n"
            "• 주석: # 으로 시작하는 줄은 무시"
        )
        
        # 텍스트 변경 시 주석 하이라이팅
        self.rules_textedit.textChanged.connect(self._highlight_comments)
        layout.addWidget(self.rules_textedit)

        # 도움말 프레임
        help_frame = QFrame()
        help_frame.setStyleSheet(dynamic_styles['transparent_frame'])
        help_layout = QVBoxLayout(help_frame)
        help_layout.setSpacing(4)
        
        help_title = QLabel("📖 규칙 구문 가이드")
        help_title.setStyleSheet(label_style + "font-weight: bold;")
        help_layout.addWidget(help_title)
        
        help_text = QLabel(
            "• 조건부: (조건) 형식으로 반드시 괄호 사용\n"
            "• 기본: tag (포함), ~tag (불포함), *tag (정확 일치), ~!tag (정확 불일치)\n"
            "• 등급: e, q, s, g (일치), ~e, ~q, ~s, ~g (불일치)\n"
            "• 논리 연산자: & (AND), | (OR)\n"
            "• 실행문: = (대체), += (리스트 추가), +: (추가)\n"
            "• 복수 태그: ^ 구분자 (예: nsfw^rating:explicit) 또는 \"쉼표, 구분\"\n"
            "• 따옴표: 선택사항 (쉼표 포함된 복수 태그 시에만 필수)\n"
            "• 주석: # 으로 시작하는 줄은 무시됩니다\n"
            "• 예시: (e):prefix+=nsfw^rating:explicit → 등급 e면 두 태그를 prefix에 추가"
        )
        help_text.setStyleSheet(label_style + f"font-size: {get_scaled_font_size(16)}px; color: #B0B0B0;")
        help_text.setWordWrap(True)
        help_layout.addWidget(help_text)
        
        layout.addWidget(help_frame)

        # 실행 로그 섹션
        log_label = QLabel("실행 로그:")
        log_label.setStyleSheet(label_style)
        layout.addWidget(log_label)

        self.log_textedit = QTextEdit()
        self.log_textedit.setFixedHeight(250)
        self.log_textedit.setReadOnly(True)
        self.log_textedit.setStyleSheet(textbox_style + "color: #B0B0B0;")
        setModernStyle(self.log_textedit)
        self.log_textedit.setPlaceholderText("규칙 실행 로그가 여기에 표시됩니다...")
        layout.addWidget(self.log_textedit)

        # 테스트 버튼
        test_button = QPushButton("규칙 테스트")
        test_button.setStyleSheet(f"""
            QPushButton {{
                background-color: #1976D2;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-weight: 600;
                color: #FFFFFF;
                font-size: {get_scaled_font_size(19)}px;
            }}
            QPushButton:hover {{
                background-color: #1565C0;
            }}
            QPushButton:pressed {{
                background-color: #0D47A1;
            }}
        """)
        test_button.clicked.connect(self.test_rules)
        layout.addWidget(test_button)

        # 위젯 참조 저장
        self.widget = widget
        
        # 현재 모드에 따른 가시성 설정
        if hasattr(self, 'app_context') and self.app_context:
            current_mode = self.app_context.get_api_mode()
            if self.widget:
                self.update_visibility_for_mode(current_mode)

        return widget
    
    def _highlight_comments(self):
        """주석(#으로 시작하는 줄) 하이라이팅"""
        if not self.rules_textedit:
            return
            
        # 현재 커서 위치 저장
        cursor = self.rules_textedit.textCursor()
        cursor_position = cursor.position()
        
        # HTML 형식으로 텍스트 변환
        text = self.rules_textedit.toPlainText()
        lines = text.split('\n')
        
        html_lines = []
        for line in lines:
            stripped_line = line.strip()
            if stripped_line.startswith('#'):
                # 주석 줄은 연한 녹색으로 표시
                html_lines.append(f'<span style="color: #F8FFDF;">{line}</span>')
            else:
                html_lines.append(line)
        
        html_content = '<br>'.join(html_lines)
        
        # HTML 설정 (텍스트 변경 신호 차단)
        self.rules_textedit.blockSignals(True)
        self.rules_textedit.setHtml(f'<div style="font-family: monospace; color: #FFFFFF;">{html_content}</div>')
        
        # 커서 위치 복원
        cursor = self.rules_textedit.textCursor()
        cursor.setPosition(min(cursor_position, len(self.rules_textedit.toPlainText())))
        self.rules_textedit.setTextCursor(cursor)
        self.rules_textedit.blockSignals(False)

    def collect_current_settings(self) -> Dict[str, Any]:
        """현재 UI 상태를 딕셔너리로 수집"""
        if not all([self.enable_checkbox, self.rules_textedit]):
            return {}
        
        return {
            "enabled": self.enable_checkbox.isChecked(),
            "rules": self.rules_textedit.toPlainText(),
        }

    def apply_settings(self, settings: Dict[str, Any]):
        """설정을 UI에 적용"""
        if not all([self.enable_checkbox, self.rules_textedit]):
            return
        
        self.enable_checkbox.setChecked(settings.get("enabled", False))
        self.rules_textedit.setText(settings.get("rules", ""))

    def get_pipeline_hook_info(self) -> Dict[str, Any]:
        """파이프라인 훅 정보 반환"""
        return {
            'target_pipeline': 'PromptProcessor',
            'hook_point': 'after_wildcard',
            'priority': 2
        }

    def execute_pipeline_hook(self, context: PromptContext) -> PromptContext:
        """파이프라인 훅 실행"""
        if not self.enable_checkbox or not self.enable_checkbox.isChecked():
            return context
        
        print("🔀 조건부 프롬프트 훅 실행...")
        
        # 규칙 텍스트 가져오기
        rules_text = self.rules_textedit.toPlainText().strip()
        if not rules_text:
            return context
        
        # 규칙 처리 및 로그 생성
        logs = []
        modified_context = self._apply_rules(context, rules_text, logs)
        
        # 로그 UI 업데이트
        self._update_log_display(logs)
        
        return modified_context

    def _apply_rules(self, context: PromptContext, rules_text: str, logs: List[str]) -> PromptContext:
        """규칙을 적용하여 프롬프트 리스트를 수정"""
        # 규칙 파싱
        rules = self._parse_rules(rules_text)
        
        # 현재 태그 리스트 복사
        prefix_tags = context.prefix_tags.copy()
        main_tags = context.main_tags.copy()
        postfix_tags = context.postfix_tags.copy()
        
        # 규칙 실행 결과만 먼저 수집
        rule_results = []
        
        # 각 규칙 적용
        for rule in rules:
            try:
                condition = rule['condition']
                action = rule['action']
                
                # 조건 확인
                condition_met = self._check_condition(condition, prefix_tags, main_tags, postfix_tags)
                
                if condition_met:
                    # 액션 실행
                    prefix_tags, main_tags, postfix_tags = self._execute_action(
                        action, prefix_tags, main_tags, postfix_tags
                    )
                    rule_results.append({
                        'rule': rule['original'],
                        'met': True,
                        'description': action['description']
                    })
                else:
                    rule_results.append({
                        'rule': rule['original'],
                        'met': False,
                        'description': None
                    })
                    
            except Exception as e:
                rule_results.append({
                    'rule': rule['original'],
                    'met': False,
                    'description': f"Error: {str(e)}"
                })
        
        # 최상단에 규칙 실행 결과 추가
        # logs.append("=== 규칙 실행 결과 ===")
        for result in rule_results:
            if result['met']:
                logs.append(f"[Rule: {result['rule']}] -> Condition Met -> {result['description']}")
            else:
                error_msg = result['description'] if result['description'] and "Error:" in result['description'] else "Condition Not Met."
                logs.append(f"[Rule: {result['rule']}] -> {error_msg}")
        logs.append("")

        # 수정된 태그 리스트를 컨텍스트에 적용
        context.prefix_tags = prefix_tags
        context.main_tags = main_tags
        context.postfix_tags = postfix_tags
        
        return context

    def _parse_tag_list(self, tag_text: str) -> List[str]:
        """태그 문자열을 리스트로 파싱 (^ 구분자 또는 쉼표 구분자 지원) - 따옴표 완전 제거"""
        tag_text = tag_text.strip()
        
        # 전체 문자열 양끝 따옴표 제거
        if (tag_text.startswith('"') and tag_text.endswith('"')) or \
        (tag_text.startswith("'") and tag_text.endswith("'")):
            tag_text = tag_text[1:-1]
        
        if '^' in tag_text:
            # ^ 구분자 사용
            tags = [tag.strip() for tag in tag_text.split('^') if tag.strip()]
        elif ',' in tag_text:
            # 쉼표 구분자 사용
            tags = [tag.strip() for tag in tag_text.split(',') if tag.strip()]
        else:
            # 단일 태그
            tags = [tag_text] if tag_text else []
        
        # 각 개별 태그에서도 따옴표 제거
        cleaned_tags = []
        for tag in tags:
            tag = tag.strip()
            # 개별 태그의 양끝 따옴표 제거
            if (tag.startswith('"') and tag.endswith('"')) or \
            (tag.startswith("'") and tag.endswith("'")):
                tag = tag[1:-1]
            cleaned_tags.append(tag)
        
        return cleaned_tags

    def _parse_rules(self, rules_text: str) -> List[Dict]:
        """규칙 텍스트를 파싱하여 구조화된 규칙 리스트 생성 - 따옴표 인식 개선"""
        rules = []
        
        # 따옴표를 고려한 쉼표 분할
        rule_parts = self._split_rules_with_quotes(rules_text)
        
        for rule_part in rule_parts:
            try:
                # (조건):실행문 형식으로 분리
                match = re.match(r"\((.*?)\)\:(.*)", rule_part)
                if not match:
                    continue
                    
                condition_part, action_part = match.groups()
                condition_part = condition_part.strip()
                action_part = action_part.strip().strip('"')
                
                # 조건 파싱
                condition = self._parse_condition(condition_part)
                
                # 액션 파싱
                action = self._parse_action(action_part)
                
                rules.append({
                    'condition': condition,
                    'action': action,
                    'original': rule_part
                })
                
            except Exception as e:
                print(f"규칙 파싱 오류: {rule_part} -> {e}")
        
        return rules
    
    def _split_rules_with_quotes(self, rules_text: str) -> List[str]:
        """따옴표 내부의 쉼표는 무시하고 규칙을 분할 - 따옴표 없는 케이스도 지원, # 주석 처리"""
        rules = []
        current_rule = ""
        in_quotes = False
        quote_char = None
        paren_count = 0
        
        i = 0
        while i < len(rules_text):
            char = rules_text[i]
            
            # 괄호 카운팅 (조건부 영역 추적)
            if char == '(':
                paren_count += 1
            elif char == ')':
                paren_count -= 1
            
            # 따옴표 처리
            if char in ['"', "'"] and (i == 0 or rules_text[i-1] != '\\'):
                if not in_quotes:
                    in_quotes = True
                    quote_char = char
                elif char == quote_char:
                    in_quotes = False
                    quote_char = None
            
            # 쉼표 분할 조건
            if char == ',' and not in_quotes and paren_count == 0:
                # 따옴표 밖이고 조건부 괄호 밖의 쉼표를 발견하면 규칙 분할
                if current_rule.strip():
                    # # 주석 처리 - #로 시작하는 규칙은 무시
                    rule_text = current_rule.strip()
                    if not rule_text.startswith('#'):
                        rules.append(rule_text)
                current_rule = ""
            else:
                current_rule += char
            
            i += 1
        
        # 마지막 규칙 추가
        if current_rule.strip():
            rule_text = current_rule.strip()
            if not rule_text.startswith('#'):
                rules.append(rule_text)
        
        return rules

    def _parse_condition(self, condition_text: str) -> Dict:
        """조건 텍스트를 파싱 - 논리 연산자 지원"""
        condition_text = condition_text.strip()
        
        return {
            'type': 'logical',
            'expression': condition_text
        }

    def _parse_action(self, action_text: str) -> Dict:
        """액션 텍스트를 파싱 - 복수 태그 및 따옴표 선택사항 지원"""
        action_text = action_text.strip()
        
        # 외부 따옴표 제거 (있는 경우) - 더 정확한 방식
        action_text = self._remove_outer_quotes(action_text)
        
        if '+=' in action_text:
            # 삽입/추가 액션 처리
            parts = action_text.split('+=', 1)
            if len(parts) == 2:
                left_part = parts[0].strip()
                right_part = parts[1].strip()
                
                # right_part를 태그 리스트로 변환
                tag_list = self._parse_tag_list(right_part)
                
                # target_list+= 형태인지 확인
                if left_part in ['prefix', 'main', 'postfix']:
                    return {
                        'type': 'append_to_list',
                        'target_list': left_part,
                        'tag_list': tag_list,
                        'description': f'{tag_list} appended to {left_part}_tags.'
                    }
                else:
                    # existing_tag+= 형태
                    return {
                        'type': 'insert',
                        'existing_tag': left_part,
                        'tag_list': tag_list,
                        'description': f'{tag_list} inserted after "{left_part}".'
                    }
                    
        elif '+:' in action_text:
            # 추가 액션
            if action_text.startswith(('prefix+:', 'main+:', 'postfix+:')):
                target_list, tag_part = action_text.split('+:', 1)
                target_list = target_list.strip()
            else:
                target_list = 'main'
                tag_part = action_text.replace('+:', '', 1)
            
            tag_list = self._parse_tag_list(tag_part.strip())
            
            return {
                'type': 'append',
                'target_list': target_list,
                'tag_list': tag_list,
                'description': f'{tag_list} appended to {target_list}_tags.'
            }
            
        elif '=' in action_text:
            # 대체 액션
            parts = action_text.split('=', 1)
            if len(parts) == 2:
                old_tag = parts[0].strip()
                new_tag_part = parts[1].strip()
                
                # new_tag_part를 태그 리스트로 변환
                new_tag_list = self._parse_tag_list(new_tag_part)
                
                return {
                    'type': 'replace',
                    'old_tag': old_tag,
                    'new_tag_list': new_tag_list,
                    'description': f'"{old_tag}" replaced with {new_tag_list}.'
                }
        
        raise ValueError(f"Unknown action format: {action_text}")
    
    def _remove_outer_quotes(self, text: str) -> str:
        """외부 따옴표만 제거하는 헬퍼 메서드"""
        text = text.strip()
        if len(text) >= 2:
            if (text.startswith('"') and text.endswith('"')) or \
               (text.startswith("'") and text.endswith("'")):
                return text[1:-1]
        return text

    def _check_condition(self, condition: Dict, prefix_tags: List[str], main_tags: List[str], postfix_tags: List[str]) -> bool:
        """조건 확인 - 논리 연산자 지원"""
        if condition['type'] != 'logical':
            return False
            
        all_tags = prefix_tags + main_tags + postfix_tags
        expression = condition['expression']
        
        return self._evaluate_logical_expression(expression, all_tags)
    
    def _evaluate_logical_expression(self, expression: str, all_tags: List[str]) -> bool:
        """논리 표현식 평가"""
        if not expression:
            return True
        
        # AND 연산자로 분할 (상위 레벨)
        and_parts = re.split(r'\s*&\s*', expression)
        and_results = []
        
        for and_part in and_parts:
            # OR 연산자로 분할 (하위 레벨)
            or_parts = re.split(r'\s*\|\s*', and_part)
            or_results = []
            
            for or_part in or_parts:
                or_part = or_part.strip()
                result = self._evaluate_single_condition(or_part, all_tags)
                or_results.append(result)
            
            # OR 조건 평가 (하나라도 True면 True)
            and_results.append(any(or_results))
        
        # AND 조건 평가 (모두 True여야 True)
        return all(and_results)
    
    def _evaluate_single_condition(self, condition: str, all_tags: List[str]) -> bool:
        """단일 조건 평가"""
        condition = condition.strip()
        
        # 등급 조건 처리
        if condition in ['e', 'q', 's', 'g']:
            return self._check_rating_condition(condition, exact_match=True)
        elif condition in ['~e', '~q', '~s', '~g']:
            rating_char = condition[1:]  # ~ 제거
            return self._check_rating_condition(rating_char, exact_match=False)
        
        # 기존 태그 조건 처리
        if condition.startswith('~!'):
            # 정확 불일치 조건 (~!tag)
            tag = condition[2:]
            return tag not in all_tags
        elif condition.startswith('~'):
            # 불포함 조건 (~tag)
            tag = condition[1:]
            return not any(tag in element for element in all_tags)
        elif condition.startswith('*'):
            # 정확 일치 조건 (*tag)
            tag = condition[1:]
            return tag in all_tags
        else:
            # 포함 조건 (tag)
            return any(condition in element for element in all_tags)
    
    def _check_rating_condition(self, rating_char: str, exact_match: bool) -> bool:
        """등급 조건을 확인"""
        if not hasattr(self, 'app_context') or not self.app_context:
            return False
            
        current_source_row = self.app_context.current_source_row
        if current_source_row is None:
            return False
            
        # source_row에서 rating 값 추출
        row_rating = current_source_row.get('rating', None)
        if row_rating is None:
            return False
            
        # 등급 비교
        if exact_match:
            return row_rating == rating_char
        else:
            return row_rating != rating_char

    def _execute_action(self, action: Dict, prefix_tags: List[str], main_tags: List[str], postfix_tags: List[str]) -> tuple:
        """액션 실행 - 태그 리스트 처리 지원"""
        if action['type'] == 'append':
            # 기존 추가 액션
            target_list = action['target_list']
            tag_list = action.get('tag_list', [action.get('tag', '')])
            
            if target_list == 'prefix':
                prefix_tags.extend(tag_list)
            elif target_list == 'postfix':
                postfix_tags.extend(tag_list)
            else:  # main (기본값)
                main_tags.extend(tag_list)
                
        elif action['type'] == 'append_to_list':
            # 리스트별 추가 액션 (prefix+=, main+=, postfix+=)
            target_list = action['target_list']
            tag_list = action.get('tag_list', [])
            
            if target_list == 'prefix':
                prefix_tags.extend(tag_list)
            elif target_list == 'postfix':
                postfix_tags.extend(tag_list)
            else:  # main
                main_tags.extend(tag_list)
                
        elif action['type'] == 'insert':
            # 삽입 액션 (기존 태그 검색)
            existing_tag = action['existing_tag']
            tag_list = action.get('tag_list', [action.get('new_tag', '')])
            
            # prefix -> main -> postfix 순서로 검색
            for tag_list_ref in [prefix_tags, main_tags, postfix_tags]:
                for i, tag in enumerate(tag_list_ref):
                    if existing_tag in tag:
                        # 리스트의 태그들을 역순으로 삽입 (순서 유지)
                        for j, new_tag in enumerate(reversed(tag_list)):
                            tag_list_ref.insert(i + 1, new_tag)
                        return prefix_tags, main_tags, postfix_tags
                        
        elif action['type'] == 'replace':
            # 대체 액션
            old_tag = action['old_tag']
            new_tag_list = action.get('new_tag_list', [action.get('new_tag', '')])
            
            # prefix -> main -> postfix 순서로 검색하여 첫 번째 일치 항목 대체
            for tag_list_ref in [prefix_tags, main_tags, postfix_tags]:
                for i, tag in enumerate(tag_list_ref):
                    if old_tag == tag:
                        # 기존 태그를 제거하고 새 태그들을 그 자리에 삽입
                        tag_list_ref.pop(i)
                        for j, new_tag in enumerate(reversed(new_tag_list)):
                            tag_list_ref.insert(i, new_tag)
                        return prefix_tags, main_tags, postfix_tags
        
        return prefix_tags, main_tags, postfix_tags

    def _update_log_display(self, logs: List[str]):
        """로그 디스플레이 업데이트 - HTML 스타일링 지원"""
        if self.log_textedit:
            # HTML 형식으로 로그 변환
            html_logs = []
            html_logs.append(f'<div style="font-family: monospace; font-size: {get_scaled_font_size(12)}px;">')
            
            for log in logs:
                if "Condition Not Met" in log:
                    # 회색 글자로 처리
                    html_logs.append(f'<div style="color: #888888;">{log}</div>')
                elif "=== 규칙 실행 결과 ===" in log or "=== 최종 결과 ===" in log or "=== 규칙 테스트 시작" in log:
                    # 헤더는 굵게
                    html_logs.append(f'<div style="font-weight: bold; color: #FFFFFF;">{log}</div>')
                else:
                    # 일반 로그
                    html_logs.append(f'<div style="color: #FFFFFF;">{log}</div>')
            
            html_logs.append('</div>')
            
            # HTML 설정
            html_content = ''.join(html_logs)
            self.log_textedit.setHtml(html_content)
            
            # 스크롤을 맨 아래로
            self.log_textedit.verticalScrollBar().setValue(
                self.log_textedit.verticalScrollBar().maximum()
            )

    def test_rules(self):
        """규칙 테스트 실행 - 실제 시뮬레이션"""
        if not self.rules_textedit:
            return
        
        # 규칙 확인
        rules_text = self.rules_textedit.toPlainText().strip()
        if not rules_text:
            self.log_textedit.setText("규칙이 비어있습니다.")
            return
        
        # AppContext 확인
        if not hasattr(self, 'app_context') or not self.app_context:
            self.log_textedit.setText("AppContext가 설정되지 않았습니다.")
            return
        
        # 메인 윈도우에서 search_results 가져오기
        search_results = getattr(self.app_context.main_window, 'search_results', None)
        if not search_results or search_results.is_empty():
            self.log_textedit.setText("검색 결과가 없습니다. 먼저 검색을 수행해주세요.")
            return
        
        logs = []
        # logs.append("=== 규칙 테스트 시작 (실제 시뮬레이션) ===")
        
        try:
            # 1. 랜덤 source_row 샘플링
            df = search_results.get_dataframe()
            if df.empty:
                self.log_textedit.setText("검색 결과 데이터프레임이 비어있습니다.")
                return
            
            # 원본 데이터 보존을 위해 복사본 생성
            df_copy = df.copy()
            random_index = df_copy.index.to_series().sample(n=1).iloc[0]
            sample_row = df_copy.loc[random_index].copy()

            # 2. 테스트용 settings 생성
            test_settings = {
                'wildcard_standalone': False,
                'auto_fit_resolution': False,
                'test_mode': True
            }
            
            # 3. PromptContext 생성
            import pandas as pd
            from core.prompt_context import PromptContext
            
            test_context = PromptContext(source_row=sample_row, settings=test_settings)
            
            # general 태그를 main_tags로 파싱
            general_str = sample_row.get('general', '')
            if pd.notna(general_str) and isinstance(general_str, str):
                test_context.main_tags = [tag.strip() for tag in general_str.split(',') if tag.strip()]
            
            # 기본 prefix_tags 설정
            test_context.prefix_tags = ["masterpiece", "best quality"]
            test_context.postfix_tags = []
            

            
            # 4. AppContext에 임시 설정
            original_source_row = self.app_context.current_source_row
            original_prompt_context = self.app_context.current_prompt_context
            
            self.app_context.current_source_row = sample_row
            self.app_context.current_prompt_context = test_context
            
            # 5. 규칙 적용
            modified_context = self._apply_rules(test_context, rules_text, logs)
            
            # logs.append(f"샘플링된 행:")
            # logs.append(f"  rating: {sample_row.get('rating', 'None')}")
            # logs.append(f"  general: {sample_row.get('general', 'None')}")
            # logs.append(f"  character: {sample_row.get('character', 'None')}")
            # logs.append("")
            
            # logs.append(f"초기 상태:")
            # logs.append(f"  prefix_tags: {test_context.prefix_tags}")
            # logs.append(f"  main_tags: {test_context.main_tags}")
            # logs.append(f"  postfix_tags: {test_context.postfix_tags}")
            # logs.append("")

            # logs.append("")
            # logs.append("=== 최종 결과 ===")
            # logs.append(f"  prefix_tags: {modified_context.prefix_tags}")
            # logs.append(f"  main_tags: {modified_context.main_tags}")
            # logs.append(f"  postfix_tags: {modified_context.postfix_tags}")
            
            # 6. 실제 PromptProcessor로 전체 파이프라인 시뮬레이션 (선택사항)
            if hasattr(self.app_context, 'main_window') and hasattr(self.app_context.main_window, 'prompt_gen_controller'):
                # logs.append("")
                # logs.append("=== 전체 파이프라인 시뮬레이션 ===")
                try:
                    # 현재 컨텍스트를 AppContext에 다시 설정
                    self.app_context.current_prompt_context = modified_context
                    
                    # PromptProcessor 실행
                    processor = self.app_context.main_window.prompt_gen_controller.processor
                    final_context = processor.process()
                    
                    #logs.append(f"최종 프롬프트:")
                    #logs.append(f"  {final_context.final_prompt}")
                    
                except Exception as e:
                    logs.append(f"파이프라인 시뮬레이션 오류: {str(e)}")
            
        except Exception as e:
            logs.append(f"테스트 중 오류 발생: {str(e)}")
            import traceback
            logs.append(traceback.format_exc())
        
        finally:
            # 7. 원래 상태 복원
            if hasattr(self, 'app_context') and self.app_context:
                self.app_context.current_source_row = original_source_row
                self.app_context.current_prompt_context = original_prompt_context
        
        # 8. 로그 표시
        self._update_log_display(logs)

    def initialize_with_context(self, app_context):
        """AppContext 주입"""
        self.app_context = app_context

    def on_initialize(self):
        """모듈 초기화"""
        if hasattr(self, 'app_context') and self.app_context:
            print(f"✅ {self.get_title()}: AppContext 연결 완료")
            
            # 초기 가시성 설정
            current_mode = self.app_context.get_api_mode()
            if self.widget:
                self.update_visibility_for_mode(current_mode)
        
        # 설정 로드
        self.load_mode_settings()

    def get_parameters(self) -> Dict[str, Any]:
        """생성 파라미터 반환"""
        if not self.enable_checkbox or not self.enable_checkbox.isChecked():
            return {}
        
        return {
            "enabled": True,
            "rules": self.rules_textedit.toPlainText() if self.rules_textedit else ""
        }