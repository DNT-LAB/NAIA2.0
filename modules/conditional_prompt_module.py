from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QCheckBox, QPushButton, QFrame, QScrollArea
)
from PyQt6.QtCore import Qt, QRegularExpression
from PyQt6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor
from interfaces.base_module import BaseMiddleModule
from interfaces.mode_aware_module import ModeAwareModule
from core.prompt_context import PromptContext
from ui.theme import DARK_COLORS, get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.modern_menu import setModernStyle
from typing import Dict, Any, List, Optional
import re

# NAI: '1.05::tag ::' → 'tag'
_WEIGHT_NAI_RE = re.compile(r'^([\d.]+)::(.+?)\s*::$')
# WEBUI: '(tag:1.05)' or '(tag (example):0.70)' → 'tag' or 'tag (example)'
# 마지막 ':숫자)' 패턴으로 분리 (태그 자체에 괄호 포함 가능)
_WEIGHT_WEBUI_RE = re.compile(r'^\((.+):([\d.]+)\)$')

# rating(X, source=Y) 확장 문법 (Phase 1.1)
# 예: rating(e, source=override)  / ~rating(s, source=row)  / rating(q)
_RATING_FUNC_RE = re.compile(
    r'^(~?)rating\s*\(\s*([eqsg])\s*(?:,\s*source\s*=\s*(auto|row|override|bayes)\s*)?\)$'
)

# 확장 조건자 (Phase 1.1b) — 블록-driven 문법, 파서 충돌 최소 설계
# char_in(N, <tag_expr>) 에서 tag_expr 는 tag / *tag / ~tag / ~!tag 형식
_CHAR_IN_RE = re.compile(r'^(~?)char_in\s*\(\s*(\d+)\s*,\s*(.+?)\s*\)$')
_CHAR_ON_RE = re.compile(r'^(~?)char_on\s*\(\s*(\d+)\s*\)$')
# 확장 액션 (Phase 1.1b) — char_set(N, state), char_replace(N, old, new)
_FUNC_ACTION_RE = re.compile(r'^([a-z_]+)\s*\(\s*(.*)\s*\)$', re.DOTALL)


def _is_pattern(tag: str) -> bool:
    """auto_hide 스타일 패턴(__tag, tag__, __tag__)인지 판별."""
    return tag.startswith("__") or tag.endswith("__")


def _match_pattern_tag(pattern: str, raw_tag: str) -> bool:
    """auto_hide 스타일 패턴 매칭. 패턴이 아니면 False 반환."""
    if pattern.startswith("__") and pattern.endswith("__"):
        # __tag__: 언더스코어 전부 제거 → 순수 서브스트링
        keyword = pattern.strip("_")
    elif pattern.startswith("__"):
        # __tag: 선행 __ 제거 → 서브스트링
        keyword = pattern.lstrip("_")
    elif pattern.endswith("__"):
        # tag__: 후행 __ 제거 → 서브스트링
        keyword = pattern.rstrip("_")
    else:
        return False
    return bool(keyword) and keyword in raw_tag


def _strip_weight_format(tag: str) -> str:
    """가중치 포맷에서 raw 태그명 추출. 세 가지 형식 지원:
    - NAI:   '1.05::tag ::' → 'tag'
    - WEBUI: '(tag:1.05)' → 'tag'
    - WEBUI (괄호 포함 태그): '(tag (example):0.7)' → 'tag (example)'
    - raw:   'tag' → 'tag'
    """
    tag = tag.strip()
    m = _WEIGHT_NAI_RE.match(tag)
    if m:
        return m.group(2).strip()
    m = _WEIGHT_WEBUI_RE.match(tag)
    if m:
        return m.group(1).strip()
    return tag


def _replace_tag_in_weight_format(weighted_tag: str, new_raw_tag: str) -> str:
    """가중치 포맷을 유지하면서 태그명만 교체.
    raw 태그(가중치 없음)이면 new_raw_tag 그대로 반환."""
    weighted_tag = weighted_tag.strip()
    m = _WEIGHT_NAI_RE.match(weighted_tag)
    if m:
        return f"{m.group(1)}::{new_raw_tag} ::"
    m = _WEIGHT_WEBUI_RE.match(weighted_tag)
    if m:
        return f"({new_raw_tag}:{m.group(2)})"
    return new_raw_tag


class CommentHighlighter(QSyntaxHighlighter):
    """# 으로 시작해서 첫 번째 쉼표까지 회색 처리하는 구문 하이라이터"""

    def __init__(self, parent=None):
        super().__init__(parent)

        # 회색 포맷 설정
        self.comment_format = QTextCharFormat()
        self.comment_format.setForeground(QColor("#808080"))

    def highlightBlock(self, text: str):
        """각 텍스트 블록(줄)에 대해 하이라이팅 적용 - 쉼표 단위로 규칙 분리"""
        # 한 줄 내에서 쉼표로 구분된 여러 규칙을 처리
        # 예: "(e):prefix+=nsfw, #(~e):prefix+=, (q):main+=test,"

        pos = 0
        while pos < len(text):
            # 현재 위치에서 다음 쉼표 찾기
            comma_index = text.find(',', pos)

            if comma_index == -1:
                # 더 이상 쉼표가 없으면 나머지 전체 확인
                segment = text[pos:].strip()
                if segment.startswith('#'):
                    # 나머지 전체를 회색 처리
                    self.setFormat(pos, len(text) - pos, self.comment_format)
                break
            else:
                # 쉼표를 찾았으면 해당 구간 확인
                segment = text[pos:comma_index].strip()

                if segment.startswith('#'):
                    # # 으로 시작하면 쉼표까지 (쉼표 포함) 회색 처리
                    # pos부터 comma_index+1까지의 실제 문자열 길이 계산
                    self.setFormat(pos, comma_index - pos + 1, self.comment_format)

                # 다음 구간으로 이동 (쉼표 다음부터)
                pos = comma_index + 1

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

        # 새 편집기 창 (단일 인스턴스, lazy 생성)
        self._rule_editor_window = None

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

        # 편집기 열기 버튼 (신규 GUI, v2.1 Phase 0)
        # SDLC R-40 준수: DARK_COLORS 토큰만 사용 (하드코딩 색상 금지)
        editor_button = QPushButton("🔧 편집기 열기 (Preview)")
        editor_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['success']};
                color: {DARK_COLORS['text_primary']};
                border: none;
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(8)}px {get_scaled_size(16)}px;
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-weight: 600;
                font-size: {get_scaled_font_size(18)}px;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
            QPushButton:pressed {{
                background-color: {DARK_COLORS['bg_pressed']};
            }}
        """)
        editor_button.setToolTip(
            "블록 기반 조건부 규칙 편집기 창을 엽니다 (개발 중).\n"
            "기존 규칙 정의 텍스트박스는 그대로 사용할 수 있습니다."
        )
        editor_button.clicked.connect(self._open_rule_editor)
        layout.addWidget(editor_button)

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
        self.rules_textedit.setAcceptRichText(False)  # 서식 붙여넣기 차단
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
            "(e):__shirts=,\n"
            "# 이 줄은 주석으로 무시됩니다\n\n"
            "구문 형식: (조건):실행문\n"
            "• 조건: tag (포함), ~tag (불포함), *tag (정확 일치), ~!tag (정확 불일치)\n"
            "• 등급: e, q, s, g (일치), ~e, ~q, ~s, ~g (불일치)\n"
            "• 논리 연산자: & (AND), | (OR)\n"
            "• 실행문: = (대체), += (리스트 추가), +: (추가)\n"
            "• 패턴 대체: __tag=, (포함 삭제), tag__=, __tag__=, (Auto Hide 동일 문법)\n"
            "• 복수 태그: ^ 구분자 또는 \"쉼표, 구분\" (자동 리스트화)\n"
            "• 따옴표: 선택사항 (쉼표 포함 시 필수)\n"
            "• 주석: # 으로 시작하는 줄은 무시"
        )

        # QSyntaxHighlighter 적용
        self.comment_highlighter = CommentHighlighter(self.rules_textedit.document())

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
            "• 패턴 대체: __tag=, (포함 삭제), tag__=, __tag__=, (Auto Hide 동일)\n"
            "• 복수 태그: ^ 구분자 (예: nsfw^rating:explicit) 또는 \"쉼표, 구분\"\n"
            "• 따옴표: 선택사항 (쉼표 포함된 복수 태그 시에만 필수)\n"
            "• 주석: # 으로 시작하는 줄은 무시됩니다\n"
            "• 예시: (e):__shirts=, → 등급 e면 shirts 포함 태그 전부 삭제"
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
        self.log_textedit.setAcceptRichText(False)  # 서식 붙여넣기 차단
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

    def _open_rule_editor(self):
        """새 규칙 편집기 창을 띄운다. 단일 인스턴스로 재사용."""
        if self._rule_editor_window is None:
            try:
                from modules.conditional.editor_window import RuleEditorWindow
            except ImportError as e:
                print(f"❌ 편집기 창 모듈 로드 실패: {e}")
                return

            parent = None
            if hasattr(self, 'app_context') and self.app_context is not None:
                parent = getattr(self.app_context, 'main_window', None)

            self._rule_editor_window = RuleEditorWindow(
                app_context=getattr(self, 'app_context', None),
                module=self,
                parent=parent,
            )

        self._rule_editor_window.show()
        self._rule_editor_window.raise_()
        self._rule_editor_window.activateWindow()

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
        # Shared Server Mode: 세션 오버라이드 우선
        cond_override = getattr(self.app_context, 'session_cond_override', None) if hasattr(self, 'app_context') else None
        if cond_override is not None:
            if not cond_override.get("enabled"):
                return context
            rules_text = cond_override.get("rules", "").strip()
        else:
            if not self.enable_checkbox or not self.enable_checkbox.isChecked():
                return context
            rules_text = self.rules_textedit.toPlainText().strip()

        print("🔀 조건부 프롬프트 훅 실행...")

        if not rules_text:
            return context
        
        # 규칙 처리 및 로그 생성
        logs = []
        modified_context = self._apply_rules(context, rules_text, logs)
        
        # 로그 UI 업데이트
        self._update_log_display(logs)
        
        return modified_context

    def _apply_rules(self, context: PromptContext, rules_text: str, logs: List[str],
                     *, max_passes: int = 1, stop_on_match: bool = False) -> PromptContext:
        """규칙을 적용하여 프롬프트 리스트를 수정.

        Args:
            max_passes: 규칙 리스트를 최대 몇 번 반복 적용할지. 기본 1(단일 패스, 레거시 동작).
                신규 모드 프리셋의 engine_options.max_passes로 지정. 고정점 혹은 진동 감지 시 조기 종료.
            stop_on_match: 한 규칙이라도 매칭되면 현재 패스 중단. 기본 False.
        """
        # Phase 1.1: Skip 카운터 초기화 (타 모드 char/uc 건너뜀 집계용)
        self._skip_counters = {}

        rules = self._parse_rules(rules_text)
        prefix_tags = context.prefix_tags.copy()
        main_tags = context.main_tags.copy()
        postfix_tags = context.postfix_tags.copy()

        snapshot_history: List[int] = []
        first_pass_results: List[Dict] = []
        passes_run = 0

        for pass_num in range(max(1, max_passes)):
            prefix_tags, main_tags, postfix_tags, results, pass_matched = (
                self._apply_rules_single_pass(
                    rules, prefix_tags, main_tags, postfix_tags,
                    stop_on_match=stop_on_match,
                )
            )
            passes_run += 1
            if pass_num == 0:
                first_pass_results = results

            if stop_on_match and pass_matched:
                if max_passes > 1:
                    logs.append(f"🛑 stop_on_match 발동 (pass {pass_num + 1})")
                break

            # 고정점 / 진동 감지 (snapshot queue 길이 3 → A↔B 진동 포함)
            snap = hash((tuple(prefix_tags), tuple(main_tags), tuple(postfix_tags)))
            if snap in snapshot_history[-3:]:
                if pass_num > 0:
                    logs.append(f"🔁 루프 고정점/진동 감지 (pass {pass_num + 1})")
                break
            snapshot_history.append(snap)

            # 매칭 없으면 조기 종료 (더 반복할 이유 없음)
            if not pass_matched:
                break

        # 첫 패스 상세 로그
        self._log_rule_results(logs, first_pass_results)
        if max_passes > 1:
            logs.append(f"↻ 실행 패스: {passes_run} / max_passes={max_passes}")
        logs.append("")

        # Phase 1.1: 집계된 skip 로그 출력 (silent 금지 원칙)
        self._flush_skip_logs(logs)

        context.prefix_tags = prefix_tags
        context.main_tags = main_tags
        context.postfix_tags = postfix_tags

        return context

    def _apply_rules_single_pass(self, rules, prefix_tags, main_tags, postfix_tags,
                                 *, stop_on_match: bool):
        """단일 패스. 각 규칙을 순서대로 평가/실행하고 결과 리스트 반환."""
        results: List[Dict] = []
        matched = False
        for rule in rules:
            try:
                condition = rule['condition']
                action = rule['action']
                condition_met = self._check_condition(
                    condition, prefix_tags, main_tags, postfix_tags
                )
                if condition_met:
                    prefix_tags, main_tags, postfix_tags = self._execute_action(
                        action, prefix_tags, main_tags, postfix_tags
                    )
                    results.append({
                        'rule': rule['original'],
                        'met': True,
                        'description': action['description'],
                    })
                    matched = True
                    if stop_on_match:
                        break
                else:
                    results.append({
                        'rule': rule['original'],
                        'met': False,
                        'description': None,
                    })
            except Exception as e:
                results.append({
                    'rule': rule['original'],
                    'met': False,
                    'description': f"Error: {str(e)}",
                })
        return prefix_tags, main_tags, postfix_tags, results, matched

    def _log_rule_results(self, logs: List[str], results: List[Dict]):
        """규칙 실행 결과를 로그에 기록."""
        for result in results:
            if result['met']:
                logs.append(
                    f"[Rule: {result['rule']}] -> Condition Met -> {result['description']}"
                )
            else:
                desc = result['description']
                error_msg = desc if desc and "Error:" in desc else "Condition Not Met."
                logs.append(f"[Rule: {result['rule']}] -> {error_msg}")

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
            
            # 따옴표 처리 (큰따옴표만 인용 구분자로 사용 - 작은따옴표는 태그 내 아포스트로피로 허용)
            if char == '"' and (i == 0 or rules_text[i-1] != '\\'):
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

        # Phase 1.1b: 함수형 액션 (char_set, char_replace) 먼저 매칭
        func_action = self._try_parse_func_action(action_text)
        if func_action is not None:
            return func_action

        if '+=' in action_text:
            # 삽입/추가 액션 처리
            parts = action_text.split('+=', 1)
            if len(parts) == 2:
                left_part = parts[0].strip()
                right_part = parts[1].strip()
                
                # right_part를 태그 리스트로 변환
                tag_list = self._parse_tag_list(right_part)
                
                # target_list+= 형태인지 확인 (Phase 1.1+1.1b: char:N/uc:N/global_uc/neg 확장)
                if (left_part in ['prefix', 'main', 'postfix', 'global_uc', 'neg']
                        or self._is_char_uc_target(left_part)):
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
            # 추가 액션 (Phase 1.1+1.1b: char:N/uc:N/global_uc/neg 확장)
            left, _sep, rest = action_text.partition('+:')
            left = left.strip()
            if (left in ('prefix', 'main', 'postfix', 'global_uc', 'neg')
                    or self._is_char_uc_target(left)):
                target_list = left
                tag_part = rest
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
                
                desc = (f'Pattern "{old_tag}" — matched tags replaced with {new_tag_list}.'
                        if _is_pattern(old_tag)
                        else f'"{old_tag}" replaced with {new_tag_list}.')
                return {
                    'type': 'replace',
                    'old_tag': old_tag,
                    'new_tag_list': new_tag_list,
                    'description': desc
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
    
    def _matching_paren(self, s: str, start: int) -> int:
        """시작 괄호의 짝을 찾음"""
        depth = 1
        for i in range(start + 1, len(s)):
            if s[i] == '(':
                depth += 1
            elif s[i] == ')':
                depth -= 1
                if depth == 0:
                    return i
        return -1

    def _split_by_operator(self, expression: str, operator: str) -> List[str]:
        """괄호 밖의 연산자로만 분할"""
        parts = []
        current = ""
        depth = 0

        for char in expression:
            if char == '(':
                depth += 1
                current += char
            elif char == ')':
                depth -= 1
                current += char
            elif char == operator and depth == 0:
                parts.append(current.strip())
                current = ""
            else:
                current += char

        if current.strip():
            parts.append(current.strip())

        return parts if len(parts) > 1 else [expression]

    def _evaluate_logical_expression(self, expression: str, all_tags: List[str]) -> bool:
        """논리 표현식 평가 - 중첩 괄호 지원"""
        expression = expression.strip()

        if not expression:
            return True

        # 최외곽 괄호 제거 (매칭되는 경우만)
        while expression.startswith('(') and expression.endswith(')'):
            matching_index = self._matching_paren(expression, 0)
            if matching_index == len(expression) - 1:
                expression = expression[1:-1].strip()
            else:
                break

        # AND 연산자 분할 (괄호 밖에서만)
        and_parts = self._split_by_operator(expression, '&')
        if len(and_parts) > 1:
            return all(self._evaluate_logical_expression(part, all_tags) for part in and_parts)

        # OR 연산자 분할 (괄호 밖에서만)
        or_parts = self._split_by_operator(expression, '|')
        if len(or_parts) > 1:
            return any(self._evaluate_logical_expression(part, all_tags) for part in or_parts)

        # 단일 조건 평가
        return self._evaluate_single_condition(expression, all_tags)
    
    def _evaluate_single_condition(self, condition: str, all_tags: List[str]) -> bool:
        """단일 조건 평가"""
        condition = condition.strip()

        # Phase 1.1: rating(X, source=Y) 확장 문법 (기존 단순 rating보다 우선 매칭)
        m = _RATING_FUNC_RE.match(condition)
        if m:
            negated = m.group(1) == '~'
            rating_char = m.group(2)
            source = m.group(3) or 'auto'
            return self._check_rating_condition_v2(rating_char, source, negated=negated)

        # Phase 1.1b: char_in(N, tag_expr) — 캐릭터 N 프롬프트 내부 태그 조건
        m = _CHAR_IN_RE.match(condition)
        if m:
            negated = m.group(1) == '~'
            try:
                char_idx = int(m.group(2)) - 1
            except ValueError:
                return False
            tag_expr = m.group(3).strip()
            return self._check_char_in_condition(char_idx, tag_expr, negated=negated)

        # Phase 1.1b: char_on(N) — 캐릭터 N 활성 상태
        m = _CHAR_ON_RE.match(condition)
        if m:
            negated = m.group(1) == '~'
            try:
                char_idx = int(m.group(2)) - 1
            except ValueError:
                return False
            return self._check_char_on_condition(char_idx, negated=negated)

        # 등급 조건 처리 (기존 동작 유지 — source='row' 고정)
        if condition in ['e', 'q', 's', 'g']:
            return self._check_rating_condition(condition, exact_match=True)
        elif condition in ['~e', '~q', '~s', '~g']:
            rating_char = condition[1:]  # ~ 제거
            return self._check_rating_condition(rating_char, exact_match=False)

        # 기존 태그 조건 처리
        if condition.startswith('~!'):
            # 정확 불일치 조건 (~!tag)
            tag = condition[2:].strip()
            result = tag not in all_tags
            print(f"  [~!{tag}] -> {result} (all_tags count: {len(all_tags)})")
            return result
        elif condition.startswith('~'):
            # 불포함 조건 (~tag)
            tag = condition[1:].strip()
            result = not any(tag in element for element in all_tags)
            print(f"  [~{tag}] -> {result}")
            return result
        elif condition.startswith('*'):
            # 정확 일치 조건 (*tag)
            tag = condition[1:].strip()
            result = tag in all_tags
            print(f"  [*{tag}] -> {result} (searching '{tag}' in {len(all_tags)} tags: {all_tags[:3]}...)")
            return result
        else:
            # 포함 조건 (tag)
            result = any(condition in element for element in all_tags)
            print(f"  [{condition}] -> {result}")
            return result
    
    def _check_rating_condition(self, rating_char: str, exact_match: bool) -> bool:
        """등급 조건 체크 (레거시 호환 경로).

        기존 동작 유지: source_row['rating']만 조회. 없으면 False.
        신규 rating(x, source=y) 문법은 `_check_rating_condition_v2`를 직접 호출.
        """
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

    # ====================================================================
    # Phase 1.1 — DSL 엔진 확장 헬퍼
    # ====================================================================

    def _check_rating_condition_v2(self, rating_char: str, source: str,
                                   *, negated: bool) -> bool:
        """rating 조건 v2 — source ∈ {auto, row, override, bayes}.

        - auto: override → row 순, 없으면 None (조건 실패)
        - row: current_source_row['rating']만
        - override: app_context.rating_override만
        - bayes: Phase 1.1 미구현 → None
        rating이 None이면 skip 카운터 증가 + False 반환.
        """
        row_rating = self._lookup_rating(source)
        if row_rating is None:
            self._record_skip(f"rating(source={source})", "rating 정보 없음")
            return False
        matched = (row_rating == rating_char)
        return (not matched) if negated else matched

    def _lookup_rating(self, source: str):
        """source에 따라 현재 rating 조회."""
        app_ctx = getattr(self, 'app_context', None)
        if app_ctx is None:
            return None

        if source == 'override':
            return getattr(app_ctx, 'rating_override', None)

        if source == 'row':
            row = getattr(app_ctx, 'current_source_row', None)
            if row is None:
                return None
            try:
                return row.get('rating', None)
            except Exception:
                return None

        if source == 'bayes':
            # Phase 1.1 미구현
            return None

        # source == 'auto': override → row → None
        ov = getattr(app_ctx, 'rating_override', None)
        if ov is not None:
            return ov
        row = getattr(app_ctx, 'current_source_row', None)
        if row is not None:
            try:
                r = row.get('rating', None)
                if r is not None:
                    return r
            except Exception:
                pass
        return None

    def _get_character_module(self):
        """CharacterModule 인스턴스를 안전하게 반환 (없으면 None)."""
        app_ctx = getattr(self, 'app_context', None)
        if app_ctx is None:
            return None
        controller = getattr(app_ctx, 'middle_section_controller', None)
        if controller is None:
            return None
        try:
            return controller.get_module_instance("CharacterModule")
        except Exception:
            return None

    def _is_naid4_mode(self) -> bool:
        """NAI + NAID4 모델 활성 여부."""
        app_ctx = getattr(self, 'app_context', None)
        if app_ctx is None:
            return False
        try:
            if app_ctx.get_api_mode() != "NAI":
                return False
        except Exception:
            return False
        mw = getattr(app_ctx, 'main_window', None)
        if mw is None:
            return False
        model_combo = getattr(mw, 'model_combo', None)
        if model_combo is None:
            return False
        try:
            return "NAID4" in model_combo.currentText()
        except Exception:
            return False

    def _parse_char_uc_target(self, target):
        """'char:N' / 'uc:N' / 'char:*' / 'uc:*' → (kind, index_or_star). 아니면 None.

        index는 0-based int로 반환 (DSL은 1-based).
        """
        if not isinstance(target, str) or ':' not in target:
            return None
        kind, _, rest = target.partition(':')
        if kind not in ('char', 'uc'):
            return None
        rest = rest.strip()
        if rest == '*':
            return (kind, '*')
        try:
            idx = int(rest)
            if idx < 1:
                return None
            return (kind, idx - 1)
        except ValueError:
            return None

    def _is_char_uc_target(self, target) -> bool:
        return self._parse_char_uc_target(target) is not None

    def _record_skip(self, target: str, reason: str):
        """타겟 skip을 누적 (후에 _flush_skip_logs로 출력)."""
        if not hasattr(self, '_skip_counters') or self._skip_counters is None:
            self._skip_counters = {}
        key = f"{target} ({reason})"
        self._skip_counters[key] = self._skip_counters.get(key, 0) + 1

    def _flush_skip_logs(self, logs: List[str]):
        """누적된 skip을 집계하여 로그에 추가 (silent 금지)."""
        counters = getattr(self, '_skip_counters', None)
        if not counters:
            return
        for key, count in sorted(counters.items()):
            logs.append(f"⚠ Skip: {key} - {count}건")
        self._skip_counters = {}

    def _write_char_uc_target(self, target: str, tag_list: List[str], *, op: str):
        """char:N / uc:N / char:* / uc:* 타겟에 write.

        op='append' → 기존 문자열에 ', '로 이어붙이기.
        op='replace' → 전체 교체.
        NAID4 아니거나 인덱스가 존재하지 않으면 skip 카운터 증가.
        """
        if not tag_list:
            return

        if not self._is_naid4_mode():
            try:
                mode_name = self.app_context.get_api_mode()
            except Exception:
                mode_name = "Unknown"
            self._record_skip(target, f"{mode_name}/NAID4 아닌 모델은 char/uc 미지원")
            return

        parsed = self._parse_char_uc_target(target)
        if parsed is None:
            self._record_skip(target, "타겟 파싱 실패")
            return
        kind_str, idx = parsed  # 'char'|'uc', int or '*'

        char_mod = self._get_character_module()
        if char_mod is None:
            self._record_skip(target, "CharacterModule 없음")
            return

        try:
            clone = char_mod.get_character_modifiable_clone()
        except AttributeError:
            clone = getattr(char_mod, 'modifiable_clone', None)
        if not isinstance(clone, dict):
            self._record_skip(target, "modifiable_clone 접근 실패")
            return

        field = 'characters' if kind_str == 'char' else 'uc'
        char_list = clone.setdefault(field, [])

        if idx == '*':
            if not char_list:
                self._record_skip(target, "활성 캐릭터 0명")
                return
            indices = list(range(len(char_list)))
        else:
            if idx >= len(char_list):
                self._record_skip(
                    target,
                    f"인덱스 {idx + 1} 존재 안함 (캐릭터 수 {len(char_list)})",
                )
                return
            indices = [idx]

        new_tags_str = ', '.join(str(t) for t in tag_list if t)
        for i in indices:
            current = char_list[i] if i < len(char_list) else ""
            if op == 'append':
                if current.strip():
                    char_list[i] = f"{current}, {new_tags_str}"
                else:
                    char_list[i] = new_tags_str
            elif op == 'replace':
                char_list[i] = new_tags_str

        clone[field] = char_list

    def _write_global_uc_target(self, tag_list: List[str], *, op: str):
        """global_uc 타겟 write. Phase 1.1에서는 저장 경로 미확정 → skip 집계만.

        Phase 1.8(모드 토글 + 변환 도구) 혹은 별도 sub-phase에서 실제
        Global UC 위젯/AppContext 경로 확정 후 구현.
        """
        if not tag_list:
            return
        self._record_skip("global_uc", "Phase 1.8에서 저장 경로 확정 예정")

    # ====================================================================
    # Phase 1.1b — 함수형 확장 (char_in/char_on 조건, char_set/char_replace
    # 액션, neg 타겟)
    # ====================================================================

    def _try_parse_func_action(self, action_text: str) -> Optional[Dict]:
        """함수형 액션 파싱. 인식 가능한 함수면 action dict 반환, 아니면 None.

        형식: `func_name(arg1, arg2, ...)`
        지원: char_set(N, enabled|disabled), char_replace(N, old, new)
        """
        m = _FUNC_ACTION_RE.match(action_text)
        if not m:
            return None
        func_name = m.group(1)
        args_str = m.group(2)
        args = [a.strip() for a in args_str.split(',')] if args_str.strip() else []

        if func_name == 'char_set':
            if len(args) != 2:
                raise ValueError(
                    f"char_set 은 2개 인자 필요 (N, enabled|disabled): {action_text}"
                )
            try:
                char_idx = int(args[0])
            except ValueError:
                raise ValueError(
                    f"char_set: 첫 인자는 1-based 정수 인덱스: {args[0]}"
                )
            state = args[1].lower()
            if state not in ('enabled', 'disabled'):
                raise ValueError(
                    f"char_set: 두번째 인자는 enabled|disabled: {state}"
                )
            return {
                'type': 'func_char_set',
                'char_index': char_idx - 1,
                'state': state,
                'description': f'Character {char_idx} set to {state}',
            }

        if func_name == 'char_replace':
            if len(args) != 3:
                raise ValueError(
                    f"char_replace 은 3개 인자 필요 (N, old, new): {action_text}"
                )
            try:
                char_idx = int(args[0])
            except ValueError:
                raise ValueError(
                    f"char_replace: 첫 인자는 1-based 정수 인덱스: {args[0]}"
                )
            return {
                'type': 'func_char_replace',
                'char_index': char_idx - 1,
                'old_tag': args[1],
                'new_tag': args[2],
                'description': f'Character {char_idx}: "{args[1]}" → "{args[2]}"',
            }

        # 인식 못 한 함수명 — 함수형 아님으로 반환, 기존 파싱으로 fallback
        return None

    def _get_character_tags(self, char_idx: int, *, field: str = 'characters') -> Optional[List[str]]:
        """캐릭터 N의 프롬프트(field='characters') 또는 UC(field='uc')를
        콤마 분리된 개별 태그 리스트로 반환. 실패 시 None."""
        char_mod = self._get_character_module()
        if char_mod is None:
            return None
        try:
            clone = char_mod.get_character_modifiable_clone()
        except AttributeError:
            clone = getattr(char_mod, 'modifiable_clone', None)
        if not isinstance(clone, dict):
            return None
        char_list = clone.get(field, [])
        if char_idx < 0 or char_idx >= len(char_list):
            return None
        raw_str = char_list[char_idx]
        if not isinstance(raw_str, str) or not raw_str.strip():
            return []
        return [t.strip() for t in raw_str.split(',') if t.strip()]

    def _check_char_in_condition(self, char_idx: int, tag_expr: str,
                                 *, negated: bool) -> bool:
        """char_in(N, tag|*tag|~tag|~!tag) 조건 평가.

        inner 접두사:
          '*'   : 정확 토큰 일치
          '~'   : 서브스트링 불포함
          '~!'  : 정확 토큰 불일치
          (없음): 서브스트링 포함
        outer `~` (negated) 은 전체 결과 뒤집기.
        """
        char_tags = self._get_character_tags(char_idx, field='characters')
        if char_tags is None:
            self._record_skip(
                f"char_in({char_idx + 1},...)",
                "캐릭터 정보 없음",
            )
            return False

        te = tag_expr.strip()
        if te.startswith('~!'):
            tag = te[2:].strip()
            matched = tag not in char_tags
        elif te.startswith('~'):
            tag = te[1:].strip()
            matched = not any(tag in element for element in char_tags)
        elif te.startswith('*'):
            tag = te[1:].strip()
            matched = tag in char_tags
        else:
            matched = any(te in element for element in char_tags)

        return (not matched) if negated else matched

    def _check_char_on_condition(self, char_idx: int, *, negated: bool) -> bool:
        """char_on(N) 조건 — 캐릭터 N의 active_checkbox 체크 상태."""
        char_mod = self._get_character_module()
        if char_mod is None:
            self._record_skip(f"char_on({char_idx + 1})", "CharacterModule 없음")
            return False
        widgets = getattr(char_mod, 'character_widgets', None)
        if widgets is None:
            self._record_skip(f"char_on({char_idx + 1})", "character_widgets 없음")
            return False
        if char_idx < 0 or char_idx >= len(widgets):
            self._record_skip(
                f"char_on({char_idx + 1})",
                f"인덱스 존재 안함 (총 {len(widgets)}명)",
            )
            return False
        widget = widgets[char_idx]
        checkbox = getattr(widget, 'active_checkbox', None)
        if checkbox is None:
            self._record_skip(f"char_on({char_idx + 1})", "active_checkbox 없음")
            return False
        try:
            is_on = bool(checkbox.isChecked())
        except Exception:
            return False
        return (not is_on) if negated else is_on

    def _execute_char_set(self, char_idx: int, state: str):
        """char_set(N, enabled|disabled) 실행 — 캐릭터 활성/비활성 토글."""
        if not self._is_naid4_mode():
            try:
                mode_name = self.app_context.get_api_mode()
            except Exception:
                mode_name = "Unknown"
            self._record_skip(
                f"char_set({char_idx + 1},{state})",
                f"{mode_name}/NAID4 아닌 모델은 char 토글 미지원",
            )
            return

        char_mod = self._get_character_module()
        if char_mod is None:
            self._record_skip(
                f"char_set({char_idx + 1},{state})", "CharacterModule 없음"
            )
            return

        setter = getattr(char_mod, 'set_character_active', None)
        if setter is None or not callable(setter):
            self._record_skip(
                f"char_set({char_idx + 1},{state})",
                "set_character_active API 없음",
            )
            return

        try:
            ok = setter(char_idx, state == 'enabled')
            if not ok:
                self._record_skip(
                    f"char_set({char_idx + 1},{state})",
                    "인덱스 없음 또는 위젯 접근 실패",
                )
        except Exception as e:
            self._record_skip(
                f"char_set({char_idx + 1},{state})",
                f"예외: {e}",
            )

    def _execute_char_replace(self, char_idx: int, old_tag: str, new_tag: str):
        """char_replace(N, old, new) 실행 — 캐릭터 N prompt 내부 정확 토큰 치환.

        가중치 포맷(NAI `1.05::tag ::`, WEBUI `(tag:1.05)`) 래핑은 보존.
        매칭 없으면 skip 카운터만 증가.
        """
        if not self._is_naid4_mode():
            try:
                mode_name = self.app_context.get_api_mode()
            except Exception:
                mode_name = "Unknown"
            self._record_skip(
                f"char_replace({char_idx + 1},...)",
                f"{mode_name}/NAID4 아닌 모델은 char 치환 미지원",
            )
            return

        char_mod = self._get_character_module()
        if char_mod is None:
            self._record_skip(
                f"char_replace({char_idx + 1},...)", "CharacterModule 없음"
            )
            return

        try:
            clone = char_mod.get_character_modifiable_clone()
        except AttributeError:
            clone = getattr(char_mod, 'modifiable_clone', None)
        if not isinstance(clone, dict):
            self._record_skip(
                f"char_replace({char_idx + 1},...)",
                "modifiable_clone 접근 실패",
            )
            return

        char_list = clone.get('characters', [])
        if char_idx < 0 or char_idx >= len(char_list):
            self._record_skip(
                f"char_replace({char_idx + 1},...)",
                f"인덱스 존재 안함 (총 {len(char_list)}명)",
            )
            return

        current = char_list[char_idx]
        if not isinstance(current, str) or not current.strip():
            self._record_skip(
                f"char_replace({char_idx + 1},{old_tag},...)",
                "프롬프트 비어있음",
            )
            return

        old_tag_s = old_tag.strip()
        new_tag_s = new_tag.strip()
        tags = [t.strip() for t in current.split(',') if t.strip()]
        replaced = 0
        for i, t in enumerate(tags):
            raw = _strip_weight_format(t)
            if raw == old_tag_s:
                if raw != t.strip():
                    tags[i] = _replace_tag_in_weight_format(t, new_tag_s)
                else:
                    tags[i] = new_tag_s
                replaced += 1

        if replaced == 0:
            self._record_skip(
                f"char_replace({char_idx + 1},{old_tag_s},...)",
                "매칭 태그 없음",
            )
            return

        char_list[char_idx] = ', '.join(tags)
        clone['characters'] = char_list

    def _write_negative_target(self, tag_list: List[str], *, op: str):
        """neg 타겟 write — non-D4 네거티브 프롬프트 위젯 직접 수정.

        주의: 이 호출은 파이프라인 훅에서 실행되며, 훅이 워커 스레드인 경우
        Qt 위젯 직접 접근이 스레드 안전성 이슈가 될 수 있음. Sub-phase 1.7
        실증에서 시그널 경유로 전환 여부 재검토.
        """
        if not tag_list:
            return
        app_ctx = getattr(self, 'app_context', None)
        if app_ctx is None:
            self._record_skip("neg", "AppContext 없음")
            return
        mw = getattr(app_ctx, 'main_window', None)
        if mw is None:
            self._record_skip("neg", "MainWindow 없음")
            return
        widget = getattr(mw, 'negative_prompt_textedit', None)
        if widget is None:
            self._record_skip("neg", "negative_prompt_textedit 없음")
            return
        try:
            current = widget.toPlainText()
        except Exception as e:
            self._record_skip("neg", f"위젯 read 실패: {e}")
            return

        new_joined = ', '.join(str(t) for t in tag_list if t)
        if op == 'append':
            new_text = f"{current}, {new_joined}" if current.strip() else new_joined
        elif op == 'replace':
            new_text = new_joined
        else:
            return

        try:
            widget.setPlainText(new_text)
        except Exception as e:
            self._record_skip("neg", f"위젯 write 실패: {e}")

    def _execute_action(self, action: Dict, prefix_tags: List[str], main_tags: List[str], postfix_tags: List[str]) -> tuple:
        """액션 실행 - 태그 리스트 처리 지원"""
        # Phase 1.1b: 함수형 액션 (char_set, char_replace) 먼저 분기
        if action['type'] == 'func_char_set':
            self._execute_char_set(action['char_index'], action['state'])
            return prefix_tags, main_tags, postfix_tags

        if action['type'] == 'func_char_replace':
            self._execute_char_replace(
                action['char_index'], action['old_tag'], action['new_tag']
            )
            return prefix_tags, main_tags, postfix_tags

        if action['type'] == 'append':
            # 기존 추가 액션 (Phase 1.1+1.1b: char:N/uc:N/global_uc/neg 분기)
            target_list = action['target_list']
            tag_list = action.get('tag_list', [action.get('tag', '')])

            if target_list == 'prefix':
                prefix_tags.extend(tag_list)
            elif target_list == 'postfix':
                postfix_tags.extend(tag_list)
            elif target_list == 'main':
                main_tags.extend(tag_list)
            elif target_list == 'global_uc':
                self._write_global_uc_target(tag_list, op='append')
            elif target_list == 'neg':
                self._write_negative_target(tag_list, op='append')
            elif self._is_char_uc_target(target_list):
                self._write_char_uc_target(target_list, tag_list, op='append')
            else:  # 미인식 시 main 기본
                main_tags.extend(tag_list)

        elif action['type'] == 'append_to_list':
            # 리스트별 추가 액션 (prefix+=/main+=/postfix+=, Phase 1.1+1.1b: char/uc/global_uc/neg)
            target_list = action['target_list']
            tag_list = action.get('tag_list', [])

            if target_list == 'prefix':
                prefix_tags.extend(tag_list)
            elif target_list == 'postfix':
                postfix_tags.extend(tag_list)
            elif target_list == 'main':
                main_tags.extend(tag_list)
            elif target_list == 'global_uc':
                self._write_global_uc_target(tag_list, op='append')
            elif target_list == 'neg':
                self._write_negative_target(tag_list, op='append')
            elif self._is_char_uc_target(target_list):
                self._write_char_uc_target(target_list, tag_list, op='append')
            else:  # fallback
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
            # SDLC R-50: replace 분기는 길이가 커 _execute_replace_action 으로 분리
            return self._execute_replace_action(
                action, prefix_tags, main_tags, postfix_tags
            )

        # 모든 경로의 최종 반환 (append / append_to_list / insert-미매칭 fallthrough)
        # Sub-phase 1.1b 리팩토링 회귀 수정: 이 라인 누락 시 None 반환 → 호출자 unpack 실패
        return prefix_tags, main_tags, postfix_tags

    def _execute_replace_action(self, action: Dict, prefix_tags: List[str],
                                main_tags: List[str], postfix_tags: List[str]) -> tuple:
        """replace 액션 실행 — SDLC R-50 준수를 위해 _execute_action에서 분리.

        지원 old_tag:
          - 'global_uc' / 'neg' / char:N / uc:N / char:* / uc:* → 전체 교체 위임
          - __tag / tag__ / __tag__ → 패턴 매칭 일괄 치환/삭제
          - 그 외 → 정확 일치 단일 치환 (prefix → main → postfix 순)
        """
        old_tag = action['old_tag']
        new_tag_list = action.get('new_tag_list', [action.get('new_tag', '')])

        # Phase 1.1+1.1b: 특수 타겟은 전체 교체로 위임
        if old_tag == 'global_uc':
            self._write_global_uc_target(new_tag_list, op='replace')
            return prefix_tags, main_tags, postfix_tags
        if old_tag == 'neg':
            self._write_negative_target(new_tag_list, op='replace')
            return prefix_tags, main_tags, postfix_tags
        if self._is_char_uc_target(old_tag):
            self._write_char_uc_target(old_tag, new_tag_list, op='replace')
            return prefix_tags, main_tags, postfix_tags

        if _is_pattern(old_tag):
            self._apply_pattern_replace(
                old_tag, new_tag_list, prefix_tags, main_tags, postfix_tags
            )
            return prefix_tags, main_tags, postfix_tags

        # 정확 일치 모드: prefix -> main -> postfix 순서로 첫 번째 일치 항목 대체
        for tag_list_ref in [prefix_tags, main_tags, postfix_tags]:
            for i, tag in enumerate(tag_list_ref):
                raw_tag = _strip_weight_format(tag)
                if old_tag == raw_tag:
                    # 첫 번째 새 태그에 기존 가중치 포맷 유지
                    # 단, 새 태그가 이미 가중치 포맷이면 사용자 의도 존중 — 승계하지 않음
                    weighted_new_list = list(new_tag_list)
                    if weighted_new_list and raw_tag != tag.strip():
                        first_new = weighted_new_list[0].strip()
                        if not (_WEIGHT_NAI_RE.match(first_new) or _WEIGHT_WEBUI_RE.match(first_new)):
                                weighted_new_list[0] = _replace_tag_in_weight_format(tag, weighted_new_list[0])
                        # 기존 태그를 제거하고 새 태그들을 그 자리에 삽입
                        tag_list_ref.pop(i)
                        for j, new_tag in enumerate(reversed(weighted_new_list)):
                            tag_list_ref.insert(i, new_tag)
                        return prefix_tags, main_tags, postfix_tags

        return prefix_tags, main_tags, postfix_tags

    def _apply_pattern_replace(self, old_tag: str, new_tag_list: List[str],
                               prefix_tags: List[str], main_tags: List[str],
                               postfix_tags: List[str]):
        """패턴 대체 (`__tag`, `tag__`, `__tag__`) — 매칭되는 모든 태그 일괄 처리.

        주의: `__wildcard__` 전개 결과는 콤마 합쳐진 단일 문자열일 수 있음
              (예: "red hair, platform footwear, nun" — 1개 요소).
              이 경우 매칭 서브태그만 제거하고 나머지를 보존.
        """
        for tag_list_ref in [prefix_tags, main_tags, postfix_tags]:
            for i in range(len(tag_list_ref) - 1, -1, -1):
                element = tag_list_ref[i]
                raw_element = _strip_weight_format(element)

                # 콤마 구분 복합 요소 처리 (__wildcard__ 전개 결과)
                if ',' in raw_element:
                    sub_tags = [t.strip() for t in raw_element.split(',') if t.strip()]
                    remaining = [t for t in sub_tags if not _match_pattern_tag(old_tag, t)]
                    if len(remaining) < len(sub_tags):
                        if remaining:
                            tag_list_ref[i] = ', '.join(remaining)
                        else:
                            tag_list_ref.pop(i)
                elif _match_pattern_tag(old_tag, raw_element):
                    if new_tag_list:
                        # 치환: 가중치 포맷 승계 + 삽입
                        weighted_new_list = list(new_tag_list)
                        if weighted_new_list and raw_element != element.strip():
                            first_new = weighted_new_list[0].strip()
                            if not (_WEIGHT_NAI_RE.match(first_new) or _WEIGHT_WEBUI_RE.match(first_new)):
                                weighted_new_list[0] = _replace_tag_in_weight_format(element, weighted_new_list[0])
                        tag_list_ref.pop(i)
                        for j, new_tag in enumerate(reversed(weighted_new_list)):
                            tag_list_ref.insert(i, new_tag)
                    else:
                        tag_list_ref.pop(i)

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
            
            # 디버깅: 초기 상태 출력
            logs.insert(0, "")
            logs.insert(0, f"  postfix_tags: {test_context.postfix_tags}")
            logs.insert(0, f"  main_tags: {test_context.main_tags[:5]}{'...' if len(test_context.main_tags) > 5 else ''}")
            logs.insert(0, f"  prefix_tags: {test_context.prefix_tags}")
            logs.insert(0, f"초기 상태:")
            logs.insert(0, f"  general: {sample_row.get('general', 'None')[:100]}...")
            logs.insert(0, f"  character: {sample_row.get('character', 'None')}")
            logs.insert(0, f"  rating: {sample_row.get('rating', 'None')}")
            logs.insert(0, f"샘플링된 행:")
            logs.insert(0, "=== 규칙 테스트 시작 ===")

            # 5. 규칙 적용
            modified_context = self._apply_rules(test_context, rules_text, logs)

            logs.append("")
            logs.append("=== 최종 결과 ===")
            logs.append(f"  prefix_tags: {modified_context.prefix_tags}")
            logs.append(f"  main_tags: {modified_context.main_tags[:5]}{'...' if len(modified_context.main_tags) > 5 else ''}")
            logs.append(f"  postfix_tags: {modified_context.postfix_tags}")
            
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