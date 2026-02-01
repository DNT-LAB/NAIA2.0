"""
Main Prompt Block - 메인 프롬프트 입력용 블록
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QSizePolicy,
    QCheckBox, QPushButton, QLineEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QRegularExpression
from PyQt6.QtGui import QTextCursor, QRegularExpressionValidator

from ui.interactive.block_widget import BlockWidget
from ui.interactive.interactive_theme import (
    COMMON_STYLES, INTERACTIVE_FONTS, FONT_FAMILY
)
from ui.interactive.random_filter_dialog import RandomFilterDialog, CONFIG_FILE
from ui.theme import DARK_COLORS
import json
from ui.scaling_manager import get_scaled_size, get_scaled_font_size

import random


class MainPromptBlock(BlockWidget):
    """
    메인 태그(프롬프트) 입력을 위한 블록 위젯
    """

    # 시그널 정의
    random_prompt_requested = pyqtSignal()  # 랜덤 프롬프트 요청
    generate_requested = pyqtSignal()  # 이미지 생성 요청

    def __init__(self, parent=None, app_context=None):
        # block_type='image' (메인 컨텐츠/생성 관련 - 녹색 계열 추천)
        super().__init__("메인 프롬프트", parent, block_type='image')
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        # AppContext 참조 (모드 확인용)
        self.app_context = app_context

        # QuickSearchBlock 참조 (InteractiveWindow에서 설정)
        self.quick_search_block = None

        # InteractiveAutocompleteManager 참조 (태그 데이터 접근용)
        self.autocomplete_manager = None

        # 🆕 고급 필터 설정 (Group:Subgroup -> bool)
        self.random_filter_config = self.load_random_filter_config()

        self._init_content()

    # 필터링할 태그 목록 (클래스 레벨 상수)
    UNWANTED_TAGS = {
        # 로고/사용자명 관련
        'patreon username', 'artist logo', 'twitter logo', 'pixiv logo',
        'logo parody', 'facebook logo', 'penguin logistics logo',
        'kingdom of kazimierz logo', 'ursus empire logo', 'tiktok logo',
        'twitch logo', 'artstation logo', 'subscribestar logo',
        'super smash bros. logo', 'playstation logo', 'kjerag logo',
        'great lungmen logo', 'tumblr logo', 'twitter x logo',
        'email address', 'web address', 'patreon logo', 'weibo username',
        'fanbox username', 'deviantart username', 'instagram username',
        'pixiv username', 'facebook username', 'tumblr username',
        'gumroad username', 'subscribestar username', 'twitter username',
        'name connection', 'artist self-insert', 'brand name imitation',
        'circle name', 'historical name connection', 'group name',
        'artist self-reference', 'weapon name', 'artist glove',
        'artist progress', 'place name', 'food name', 'artist name', 'signature',
        # Watermark 관련
        'watermark', 'sample watermark', 'character watermark',
        'commission watermark', 'copyright notice', 'pixiv id', 'kanji'
    }

    @staticmethod
    def _should_filter_tag(tag: str) -> bool:
        """
        태그를 필터링해야 하는지 확인

        Args:
            tag: 확인할 태그

        Returns:
            True if 필터링해야 함, False otherwise
        """
        tag_lower = tag.lower().strip()

        # 1. UNWANTED_TAGS에 정확히 매칭되는지 확인
        if tag_lower in MainPromptBlock.UNWANTED_TAGS:
            return True

        # 2. "text"를 포함하는지 확인
        if 'text' in tag_lower:
            return True

        return False

    def _init_content(self):
        layout = self.get_content_layout()

        # 상단 라벨 + 체크박스 + 버튼 영역
        header_layout = QHBoxLayout()
        header_layout.setSpacing(get_scaled_size(8))

        # 라벨
        label = QLabel("메인 태그를 입력합니다 :")
        label.setStyleSheet(f"""
            color: {COMMON_STYLES['text_primary']};
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(17)}px;
            font-weight: bold;
        """)
        header_layout.addWidget(label)

        # Stretch (왼쪽과 오른쪽 구분)
        header_layout.addStretch()

        # 태그 뷰어 관련 레거시 컨트롤 제거됨 (FloatingControlBar로 이동)
        # self.chk_tag_viewer ...
        # self.btn_show_viewer ...

        layout.addLayout(header_layout)

        layout.addLayout(header_layout)

        # 텍스트 에디터 (수정 가능)
        self.text_edit = QTextEdit()
        # 초기값은 비워둠 (요청 없음)
        self.text_edit.setPlaceholderText("프롬프트를 입력하세요...")

        # 필터 속성 설정 (general)
        self.text_edit.setProperty("autocomplete_filter", "general")
        self.text_edit.setProperty("autocomplete_ignore", True)

        # TagViewer 사용 플래그 (3단 구조 뷰어)
        # self.text_edit.setProperty("use_tag_viewer", True)
        
        # 높이 400 설정
        self.text_edit.setMinimumHeight(get_scaled_size(700)) 
        self.text_edit.setMinimumWidth(get_scaled_size(450))
        
        # 스타일 적용 (Editable)
        self.text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COMMON_STYLES['input_bg']};
                color: {COMMON_STYLES['text_primary']};
                border: 1px solid {COMMON_STYLES['input_border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(8)}px;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(20)}px;
            }}
            QTextEdit:focus {{
                border: 1px solid {COMMON_STYLES['input_focus']};
            }}
        """)
        
        layout.addWidget(self.text_edit)


        layout.addSpacing(get_scaled_size(10))

        # === 시드 설정 (User Request: 캐릭터 특징 제거 버튼 위) ===
        seed_layout = QHBoxLayout()
        seed_layout.setSpacing(get_scaled_size(8))

        seed_label = QLabel("시드:")
        seed_label.setStyleSheet(f"color: {COMMON_STYLES['text_primary']}; font-family: {FONT_FAMILY}; font-size: {get_scaled_font_size(14)}px; font-weight: bold;")
        seed_layout.addWidget(seed_label)

        self.seed_input = QLineEdit()
        self.seed_input.setPlaceholderText("랜덤 (비워두면 자동)")
        self.seed_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {COMMON_STYLES['input_bg']};
                color: {COMMON_STYLES['text_primary']};
                border: 1px solid {COMMON_STYLES['input_border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)
        # 숫자만 입력 가능
        regex = QRegularExpression("^[0-9]*$")
        validator = QRegularExpressionValidator(regex, self.seed_input)
        self.seed_input.setValidator(validator)
        
        seed_layout.addWidget(self.seed_input)

        self.chk_seed_fixed = QCheckBox("시드 고정")
        self.chk_seed_fixed.setStyleSheet(f"color: {COMMON_STYLES['text_primary']}; font-family: {FONT_FAMILY}; font-size: {get_scaled_font_size(14)}px;")
        seed_layout.addWidget(self.chk_seed_fixed)

        layout.addLayout(seed_layout)
        layout.addSpacing(get_scaled_size(8))

        # === 하단 옵션 (체크박스) ===
        self.chk_remove_features = QCheckBox("랜덤 프롬프트의 캐릭터 특징 제거")
        self.chk_remove_features.setChecked(True) # 예시 이미지 상 체크되어 있음
        layout.addWidget(self.chk_remove_features)

        self.chk_remove_clothes = QCheckBox("랜덤 프롬프트의 옷 제거")
        layout.addWidget(self.chk_remove_clothes)

        self.chk_remove_background = QCheckBox("랜덤 프롬프트의 배경 제거")
        layout.addWidget(self.chk_remove_background)

        layout.addSpacing(get_scaled_size(8))

        # === 고급 필터 설정 버튼 ===
        self.btn_advanced_filter = QPushButton("⚙️ 고급 필터 설정")
        self.btn_advanced_filter.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_advanced_filter.setFixedHeight(get_scaled_size(32))
        self.btn_advanced_filter.setStyleSheet(f"""
            QPushButton {{
                background-color: {COMMON_STYLES['input_bg']};
                color: {COMMON_STYLES['text_primary']};
                border: 1px solid {COMMON_STYLES['input_border']};
                border-radius: {get_scaled_size(4)}px;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(14)}px;
                font-weight: normal;
                padding: {get_scaled_size(4)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border: 1px solid {COMMON_STYLES['input_focus']};
            }}
            QPushButton:pressed {{
                background-color: {DARK_COLORS['bg_secondary']};
            }}
        """)
        self.btn_advanced_filter.clicked.connect(self._on_advanced_clicked)
        layout.addWidget(self.btn_advanced_filter)

        layout.addSpacing(get_scaled_size(8))

        # === 하단 버튼 (랜덤 / 생성) ===
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(get_scaled_size(8))
        
        # 1. 랜덤/다음 프롬프트 버튼 (어두운 회색)
        self.btn_random = QPushButton("랜덤/다음 프롬프트")
        self.btn_random.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_random.setFixedHeight(get_scaled_size(40))
        self.btn_random.setStyleSheet(f"""
            QPushButton {{
                background-color: #333333; /* Dark Gray */
                color: {COMMON_STYLES['text_primary']};
                border: 1px solid {COMMON_STYLES['input_border']};
                border-radius: {get_scaled_size(4)}px;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #444444;
            }}
            QPushButton:pressed {{
                background-color: #222222;
            }}
        """)
        btn_layout.addWidget(self.btn_random)

        # 2. 이미지 생성 요청 버튼 (파란색)
        self.btn_generate = QPushButton("🎨 이미지 생성 요청")
        self.btn_generate.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_generate.setFixedHeight(get_scaled_size(40))
        self.btn_generate.setStyleSheet(f"""
            QPushButton {{
                background-color: #1E88E5; /* Blue */
                color: white;
                border: none;
                border-radius: {get_scaled_size(4)}px;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #1976D2;
            }}
            QPushButton:pressed {{
                background-color: #0D47A1;
            }}
        """)
        btn_layout.addWidget(self.btn_generate)

        layout.addLayout(btn_layout)

        # ✅ 버튼 클릭 시그널 연결
        self.btn_random.clicked.connect(self._on_random_clicked)
        self.btn_generate.clicked.connect(self._on_generate_clicked)

        layout.addSpacing(get_scaled_size(8))

        # === 자동 생성 옵션 (배타적 선택) ===
        auto_gen_layout = QHBoxLayout()
        auto_gen_layout.setSpacing(get_scaled_size(8))

        # 반복 생성 체크박스
        self.chk_repeat_generation = QCheckBox("반복 생성")
        self.chk_repeat_generation.setStyleSheet(f"color: {COMMON_STYLES['text_primary']}; font-family: {FONT_FAMILY}; font-size: {get_scaled_font_size(14)}px;")
        self.chk_repeat_generation.stateChanged.connect(self._on_repeat_generation_toggled)
        auto_gen_layout.addWidget(self.chk_repeat_generation, 1)  # stretch=1

        # 자동 랜덤생성 체크박스
        self.chk_auto_random_generation = QCheckBox("자동 랜덤생성")
        self.chk_auto_random_generation.setStyleSheet(f"color: {COMMON_STYLES['text_primary']}; font-family: {FONT_FAMILY}; font-size: {get_scaled_font_size(14)}px;")
        self.chk_auto_random_generation.stateChanged.connect(self._on_auto_random_generation_toggled)
        auto_gen_layout.addWidget(self.chk_auto_random_generation, 1)  # stretch=1

        layout.addLayout(auto_gen_layout)

        # 상하 늘어짐 방지
        layout.addStretch()

    def get_prompt(self):
        """
        입력된 프롬프트 반환 (플레인 텍스트)

        HTML 포맷이 설정된 경우 카테고리 헤더(#로 시작)를 제거하고 태그만 반환
        """
        text = self.text_edit.toPlainText()

        # 카테고리 헤더 제거 (#로 시작하는 라인)
        lines = text.split('\n')
        cleaned_lines = []

        for line in lines:
            line = line.strip()
            if not line:  # 빈 줄 무시
                continue
            if line.startswith('#'):  # 카테고리 헤더 무시
                continue

            # 라인 내의 태그들을 필터링
            tags = [tag.strip() for tag in line.split(',') if tag.strip()]
            filtered_tags = [tag for tag in tags if not self._should_filter_tag(tag)]

            if filtered_tags:
                cleaned_lines.append(', '.join(filtered_tags))

        # 쉼표로 조인하고 정리
        result = ', '.join(cleaned_lines)

        # 연속된 쉼표 정리
        while ', ,' in result:
            result = result.replace(', ,', ',')

        # 앞뒤 쉼표 제거
        result = result.strip(', ')

        return result

    def get_categorized_tags(self):
        """
        프롬프트를 카테고리별로 분리하여 반환 (COMFYUI + ANIMA 모드용)

        Returns:
            dict: {
                "person_tags": str,      # 인원 수 태그 (1girl, 2girls 등)
                "character_tags": str,   # 캐릭터 관련 태그 (Creatures 그룹)
                "remaining_tags": str    # 나머지 태그
            }
        """
        text = self.text_edit.toPlainText()

        # PERSON_CATEGORIES 정의
        PERSON_CATEGORIES = [
            "none", "solo", "1girl", "2girls", "3girls", "4+girls",
            "multiple girls", "1boy", "2boys", "3boys", "4+boys",
            "multiple boys", "1other", "2others", "3others", "4+others",
            "6+girls", "6+boys", "6+others"
        ]

        # 카테고리 헤더 제거 후 태그 추출
        lines = text.split('\n')
        all_tags = []

        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # 쉼표로 분리
            tags = [tag.strip() for tag in line.split(',') if tag.strip()]
            # 필터링 적용
            filtered_tags = [tag for tag in tags if not self._should_filter_tag(tag)]
            all_tags.extend(filtered_tags)

        # 카테고리별로 분류
        person_tags = []
        character_tags = []
        remaining_tags = []

        # InteractiveAutocompleteManager에서 태그 데이터 가져오기
        tags_data = None
        if self.autocomplete_manager and hasattr(self.autocomplete_manager, 'datasets'):
            tags_data = self.autocomplete_manager.datasets.get("general", {})

        for tag in all_tags:
            tag_lower = tag.lower()

            # 1. PERSON_CATEGORIES 체크
            if tag_lower in PERSON_CATEGORIES:
                person_tags.append(tag)
                continue

            # 2. Creatures 그룹 체크 (캐릭터 태그)
            if tags_data and tag_lower in tags_data:
                tag_info = tags_data[tag_lower]
                group = tag_info.get("group", "")

                if group == "Creatures":
                    character_tags.append(tag)
                    continue

            # 3. 나머지
            remaining_tags.append(tag)

        return {
            "person_tags": ', '.join(person_tags),
            "character_tags": ', '.join(character_tags),
            "remaining_tags": ', '.join(remaining_tags)
        }

    def set_prompt(self, prompt_text: str):
        """프롬프트 설정 (플레인 텍스트)"""
        self.text_edit.setPlainText(prompt_text)

    def set_prompt_html(self, html_text: str):
        """프롬프트 설정 (HTML)"""
        self.text_edit.setHtml(html_text)

    def refresh_formatting(self):
        """현재 텍스트에 하이라이팅(카테고리 포맷)을 다시 적용"""
        current_text = self.get_prompt() # plain text cleaning (헤더 제거)
        if current_text:
            formatted_html = self._format_prompt_with_categories(current_text)
            self.set_prompt_html(formatted_html)
            
            # 커서를 끝으로 이동
            cursor = self.text_edit.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.text_edit.setTextCursor(cursor)

    def register_autocomplete(self, autocomplete_manager):
        """자동완성 매니저에 위젯 등록"""
        autocomplete_manager.register_widget(
            self.text_edit,
            dataset_id="general"  # 전체 태그 사용
        )
        # ✅ 매니저 참조 저장 (태그 데이터 접근용)
        self.autocomplete_manager = autocomplete_manager

    def set_quick_search_block(self, quick_search_block):
        """
        QuickSearchBlock 참조 설정 (InteractiveWindow에서 호출)

        Args:
            quick_search_block: QuickSearchBlock 인스턴스
        """
        self.quick_search_block = quick_search_block
        print(f"[MainPromptBlock] QuickSearchBlock 참조 설정됨")

    def generate_random_prompt(self):
        """외부에서 랜덤 프롬프트 생성을 요청할 때 사용"""
        self._on_random_clicked()

    def trigger_generation(self):
        """외부에서 이미지 생성을 요청할 때 사용"""
        self._on_generate_clicked()

    # ===== 버튼 클릭 핸들러 =====

    def _on_random_clicked(self):
        """랜덤/다음 프롬프트 버튼 클릭"""
        print("[MainPromptBlock] 랜덤/다음 프롬프트 버튼 클릭")

        if not self.quick_search_block:
            print("❌ QuickSearchBlock이 연결되지 않았습니다.")
            return

        # QuickSearchBlock에서 랜덤 프롬프트 가져오기
        random_prompt = self.quick_search_block.get_random_prompt()

        if not random_prompt:
            print("❌ 랜덤 프롬프트 생성 실패 (파티션 데이터가 없거나 이벤트가 없음)")

            # 경고 메시지 삽입 (노란색)
            warning_html = '<p style="color: #FFEB3B; font-weight: bold; margin-bottom: 8px;">⚠️ 현재 인원수/레이팅 조합에서는 매칭되는 이벤트가 없었습니다.</p>'

            cursor = self.text_edit.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.insertHtml(warning_html)
            cursor.insertBlock() # 줄바꿈
            return

        # 필터링 전 태그 개수
        original_tag_count = len([t.strip() for t in random_prompt.split(',') if t.strip()])
        print(f"📌 원본 프롬프트: {original_tag_count}개 태그")

        # 필터링 옵션 적용
        filtered_prompt = self._apply_filters(random_prompt)

        # 필터링 후 태그 개수
        filtered_tag_count = len([t.strip() for t in filtered_prompt.split(',') if t.strip()])
        removed_count = original_tag_count - filtered_tag_count

        if removed_count > 0:
            print(f"🔽 필터링 완료: {removed_count}개 태그 제거됨 ({original_tag_count} → {filtered_tag_count})")
        else:
            print(f"✅ 필터링 완료: 제거된 태그 없음 ({original_tag_count}개 유지)")

        # ✅ 대분류별로 포맷팅하여 표시
        formatted_html = self._format_prompt_with_categories(filtered_prompt)

        # HTML로 설정 (색상 하이라이팅 적용)
        self.set_prompt_html(formatted_html)

        print(f"✅ 랜덤 프롬프트 생성 완료")

    def get_seed(self) -> int:
        """
        현재 시드 값 반환 
        
        Returns:
            int: 입력된 시드 값. 비어있거나 유효하지 않으면 -1 (랜덤 의미)
        """
        text = self.seed_input.text().strip()
        if text and text.isdigit():
            return int(text)
        return -1

    def update_random_seed(self):
        """
        시드 고정이 설정되지 않은 경우 랜덤 시드 값 생성 및 UI 업데이트
        """
        if not self.chk_seed_fixed.isChecked():
            new_seed = random.randint(0, 9999999999)
            self.seed_input.setText(str(new_seed))
            print(f"[MainPromptBlock] 새 랜덤 시드 생성: {new_seed}")

    def _on_generate_clicked(self):
        """이미지 생성 요청 버튼 클릭"""
        print("[MainPromptBlock] 이미지 생성 요청 버튼 클릭")

        # 시그널 발행 (InteractiveWindow에서 처리)
        self.generate_requested.emit()

    def _on_repeat_generation_toggled(self, state):
        """반복 생성 체크박스 토글 핸들러 (배타적 선택)"""
        if state == Qt.CheckState.Checked.value:
            # 반복 생성이 체크되면 자동 랜덤생성 해제
            if self.chk_auto_random_generation.isChecked():
                self.chk_auto_random_generation.setChecked(False)
            print("[MainPromptBlock] 반복 생성 활성화")
        else:
            print("[MainPromptBlock] 반복 생성 비활성화")

    def _on_auto_random_generation_toggled(self, state):
        """자동 랜덤생성 체크박스 토글 핸들러 (배타적 선택)"""
        if state == Qt.CheckState.Checked.value:
            # 자동 랜덤생성이 체크되면 반복 생성 해제
            if self.chk_repeat_generation.isChecked():
                self.chk_repeat_generation.setChecked(False)
            print("[MainPromptBlock] 자동 랜덤생성 활성화")
        else:
            print("[MainPromptBlock] 자동 랜덤생성 비활성화")

    def is_repeat_generation_enabled(self) -> bool:
        """반복 생성 활성화 여부 반환"""
        return self.chk_repeat_generation.isChecked()

    def is_auto_random_generation_enabled(self) -> bool:
        """자동 랜덤생성 활성화 여부 반환"""
        return self.chk_auto_random_generation.isChecked()

    def _on_tag_viewer_toggled(self, state):
        """
        태그 뷰어 활성화 체크박스 토글 핸들러

        Args:
            state: Qt.CheckState (Checked or Unchecked)
        """
        is_checked = (state == Qt.CheckState.Checked.value)
        self.text_edit.setProperty("use_tag_viewer", is_checked)

        status = "활성화" if is_checked else "비활성화"
        print(f"[MainPromptBlock] 태그 뷰어 {status}")

    def _on_show_viewer_clicked(self):
        """
        [뷰어] 버튼 클릭 핸들러 - tag_viewer_widget 재호출

        체크박스가 비활성화 상태면 활성화하고, 포커스를 주어 자동으로 TagViewer 표시
        """
        if not self.chk_tag_viewer.isChecked():
            print("[MainPromptBlock] 태그 뷰어가 비활성화 상태 → 활성화합니다")
            self.chk_tag_viewer.setChecked(True)

        # text_edit에 포커스를 주면 eventFilter에서 use_tag_viewer 속성을 확인하여
        # 자동으로 TagViewer가 표시됨 (interactive_autocomplete.py:447-460)
        print("[MainPromptBlock] text_edit에 포커스를 주어 TagViewer 표시")
        self.text_edit.setFocus()

        # TagViewer가 이미 표시되어 있는 경우, 다시 표시하기 위해 포커스를 잠시 다른 곳으로 옮겼다가 돌림
        # (eventFilter는 FocusIn 이벤트에서만 동작하므로)
        if self.autocomplete_manager and hasattr(self.autocomplete_manager, 'tag_viewer'):
            tag_viewer = self.autocomplete_manager.tag_viewer
            if tag_viewer and tag_viewer.isVisible():
                print("[MainPromptBlock] TagViewer가 이미 표시됨 → 재표시 시도")
                # 포커스를 버튼으로 옮겼다가 다시 text_edit로
                self.btn_show_viewer.setFocus()
                QTimer.singleShot(50, lambda: self.text_edit.setFocus())

    def _on_advanced_clicked(self):
        """고급 필터 설정 버튼 클릭"""
        print("[MainPromptBlock] 고급 필터 설정 버튼 클릭")

        # 태그 데이터 가져오기 (InteractiveAutocompleteManager에서)
        tags_data = {}
        if self.autocomplete_manager and hasattr(self.autocomplete_manager, 'datasets'):
            tags_data = self.autocomplete_manager.datasets.get("general", {})

        # RandomFilterDialog 생성 및 표시
        dialog = RandomFilterDialog(parent=self, tags_data=tags_data)

        # 다이얼로그 실행
        if dialog.exec():  # 사용자가 '저장' 클릭
            # 새 설정 가져오기
            new_config = dialog.get_config()
            self.random_filter_config = new_config

            # 파일 저장 (다이얼로그 내부에서도 저장하지만, 멤버 변수 동기화를 위해)
            self.save_random_filter_config()

            print(f"✅ 고급 필터 설정 업데이트됨: {len(new_config)}개 항목")
        else:
            print("❌ 고급 필터 설정 취소됨")

    # ===== 포맷팅 로직 =====

    def _format_prompt_with_categories(self, prompt: str) -> str:
        """
        프롬프트를 대분류별로 그룹화하여 HTML 포맷으로 변환

        Args:
            prompt: 쉼표로 구분된 태그 문자열

        Returns:
            str: HTML 포맷 문자열 (카테고리 헤더는 연노랑색)
        """
        if not prompt:
            return ""

        # 태그 분리
        tags = [tag.strip() for tag in prompt.split(',') if tag.strip()]

        if not tags:
            return ""

        # PERSON_CATEGORIES 정의 (분류 없이 최상위 표시)
        PERSON_CATEGORIES = [
            "none", "solo", "1girl", "2girls", "3girls", "4+girls",
            "multiple girls", "1boy", "2boys", "3boys", "4+boys",
            "multiple boys", "1other", "2others", "3others", "4+others",
            "6+girls", "6+boys", "6+others"
        ]

        # 대분류 한글 매핑
        group_kr_map = {
            "Clothing_Wear": "의상/착용",
            "Person_Body": "인체/신체",
            "Food_Object": "음식/사물",
            "Composition_Meta": "구도/메타",
            "Expression_Action": "표정/행동",
            "Creatures": "생물/종족",
            "Location_Background": "장소/배경",
            "NSFW": "NSFW",
            "Culture_Misc": "문화/기타"
        }

        # 대분류별 표시 순서
        group_order = [
            "Person_Body",
            "Creatures",
            "Clothing_Wear",
            "NSFW",
            "Expression_Action",
            "Composition_Meta",
            "Location_Background",
            "Food_Object",
            "Culture_Misc"
        ]

        # 태그를 대분류별로 그룹화
        grouped_tags = {}
        top_tags = []  # PERSON_CATEGORIES (최상위, 분류 없이)
        uncategorized_tags = []  # 미분류 (바닥으로)

        # InteractiveAutocompleteManager에서 태그 데이터 가져오기
        tags_data = None
        if self.autocomplete_manager and hasattr(self.autocomplete_manager, 'datasets'):
            tags_data = self.autocomplete_manager.datasets.get("general", {})

        for tag in tags:
            tag_lower = tag.lower()

            # 1. PERSON_CATEGORIES 체크 (최우선)
            if tag_lower in PERSON_CATEGORIES:
                top_tags.append(tag)
                continue

            # 2. 태그 데이터에서 대분류 찾기
            if tags_data and tag_lower in tags_data:
                tag_info = tags_data[tag_lower]
                group = tag_info.get("group", "")

                if group:
                    if group not in grouped_tags:
                        grouped_tags[group] = []
                    grouped_tags[group].append(tag)
                else:
                    # 미분류이지만 "background" 포함 시 → 구도/메타로
                    if "background" in tag_lower:
                        # 🆕 배경 제거 옵션이 활성화되어 있으면 태그 버림
                        if self.chk_remove_background.isChecked():
                            continue  # 태그를 그룹에 추가하지 않고 건너뜀

                        if "Composition_Meta" not in grouped_tags:
                            grouped_tags["Composition_Meta"] = []
                        grouped_tags["Composition_Meta"].append(tag)
                    else:
                        uncategorized_tags.append(tag)
            else:
                # 데이터에 없는 태그
                # "background" 포함 시 → 장소/배경으로
                if "background" in tag_lower:
                    # 🆕 배경 제거 옵션이 활성화되어 있으면 태그 버림
                    if self.chk_remove_background.isChecked():
                        continue  # 태그를 그룹에 추가하지 않고 건너뜀

                    if "Location_Background" not in grouped_tags:
                        grouped_tags["Location_Background"] = []
                    grouped_tags["Location_Background"].append(tag)
                else:
                    uncategorized_tags.append(tag)

        # HTML 생성
        html_parts = []
        # Interactive Mode의 테마 폰트와 스케일링 적용
        font_size = get_scaled_font_size(20)
        html_parts.append(f'<html><body style="font-family: {FONT_FAMILY}; font-size: {font_size}px; color: #FFFFFF;">')

        # 1. PERSON_CATEGORIES 태그 먼저 표시 (분류 없이, 최상위)
        if top_tags:
            html_parts.append('<p style="margin: 4px 0;">')
            html_parts.append(', '.join(top_tags) + ',')  # 쉼표 추가
            html_parts.append('</p>')

        # 2. 대분류별로 표시
        for group in group_order:
            if group in grouped_tags:
                group_kr = group_kr_map.get(group, group)

                # 구분선 (빈 줄)
                html_parts.append('<p style="margin: 8px 0;"></p>')

                # 카테고리 헤더 (연노랑색 #으로 시작, 쉼표 추가)
                html_parts.append(f'<p style="margin: 4px 0; color: #FFFF99; font-weight: bold;">#{group_kr},</p>')

                # 태그 나열 (쉼표 추가)
                html_parts.append('<p style="margin: 4px 0;">')
                html_parts.append(', '.join(grouped_tags[group]) + ',')
                html_parts.append('</p>')

        # 3. 미분류 태그 마지막에 표시 (#미분류)
        if uncategorized_tags:
            # 구분선 (빈 줄)
            html_parts.append('<p style="margin: 8px 0;"></p>')

            # 카테고리 헤더 (쉼표 추가)
            html_parts.append(f'<p style="margin: 4px 0; color: #FFFF99; font-weight: bold;">#미분류,</p>')

            # 태그 나열 (쉼표 추가)
            html_parts.append('<p style="margin: 4px 0;">')
            html_parts.append(', '.join(uncategorized_tags) + ',')
            html_parts.append('</p>')

        html_parts.append('</body></html>')

        return ''.join(html_parts)

    # ===== 필터링 로직 =====

    def _apply_advanced_filters(self, prompt: str) -> str:
        """
        고급 필터 설정에 따라 프롬프트 필터링 (Group:Subgroup 기반)

        Args:
            prompt: 원본 프롬프트

        Returns:
            str: 필터링된 프롬프트
        """
        if not prompt:
            return prompt

        # 고급 필터가 비어있으면 필터링 안함
        if not self.random_filter_config:
            return prompt

        # autocomplete_manager가 없거나 데이터가 없으면 필터링 안함
        if not self.autocomplete_manager:
            print("⚠️ autocomplete_manager가 설정되지 않아 고급 필터를 적용할 수 없습니다.")
            return prompt

        tags_data = self.autocomplete_manager.datasets.get("general", {})
        if not tags_data:
            print("⚠️ 태그 데이터가 없어 고급 필터를 적용할 수 없습니다.")
            return prompt

        # 태그 분리 (쉼표로 구분)
        tags = [tag.strip() for tag in prompt.split(',')]

        filtered_tags = []
        removed_count = 0

        for tag in tags:
            # 빈 태그 제외
            if not tag:
                continue

            tag_lower = tag.lower()

            # 태그 데이터에서 group, subgroup 정보 가져오기
            tag_info = tags_data.get(tag_lower, {})
            group = tag_info.get("group", "")
            subgroup = tag_info.get("subgroup", "")

            # group과 subgroup이 모두 있는 경우만 필터링 적용
            if group and subgroup:
                key = f"{group}:{subgroup}"

                # 설정에서 해당 카테고리가 False인 경우 제거
                if key in self.random_filter_config and not self.random_filter_config[key]:
                    removed_count += 1
                    print(f"🔇 태그 제거됨 (고급 필터): {tag} ({key})")
                    continue

            # 필터링되지 않은 태그는 유지
            filtered_tags.append(tag)

        if removed_count > 0:
            print(f"✅ 고급 필터 적용: {removed_count}개 태그 제거됨")

        return ", ".join(filtered_tags)

    def _apply_filters(self, prompt: str) -> str:
        """
        체크박스 옵션에 따라 프롬프트 필터링

        Args:
            prompt: 원본 프롬프트

        Returns:
            str: 필터링된 프롬프트
        """
        if not prompt:
            return prompt

        # 🆕 1. 먼저 고급 필터 적용 (Group:Subgroup 기반)
        prompt = self._apply_advanced_filters(prompt)

        # 🆕 2. Auto-Hide 패턴 적용
        prompt = self._remove_auto_hide_tags(prompt)

        # 3. 체크박스 필터 적용 (캐릭터 특징, 옷, 배경)
        # 태그 분리 (쉼표로 구분)
        tags = [tag.strip() for tag in prompt.split(',')]

        filtered_tags = []

        for tag in tags:
            # 빈 태그 제외
            if not tag:
                continue

            tag_lower = tag.lower()

            # 0. 불필요한 태그 제거 (로고, watermark, text 포함 태그)
            if self._should_filter_tag(tag):
                continue

            # 1. 캐릭터 특징 제거
            if self.chk_remove_features.isChecked():
                if self._is_character_feature(tag_lower):
                    continue

            # 2. 옷 제거
            if self.chk_remove_clothes.isChecked():
                if self._is_clothing(tag_lower):
                    continue

            # 3. 배경 제거
            if self.chk_remove_background.isChecked():
                if self._is_background(tag_lower):
                    continue

            filtered_tags.append(tag)

        return ", ".join(filtered_tags)

    def _is_character_feature(self, tag: str) -> bool:
        """
        캐릭터 특징 태그 판별

        FilterDataManager의 characteristic_list를 사용하여 판별
        """
        # 가슴 크기 관련
        breast_sizes = [
            'flat chest', 'small breasts', 'medium breasts',
            'large breasts', 'huge breasts', 'gigantic breasts', 'alternate breast size'
        ]

        # FilterDataManager의 characteristic_list 사용
        characteristic_list = []
        if hasattr(self, 'app_context') and self.app_context:
            filter_data_manager = getattr(self.app_context, 'filter_data_manager', None)
            if filter_data_manager:
                characteristic_list = getattr(filter_data_manager, 'characteristic_list', [])

        # characteristic_list와 breast_sizes 결합
        all_features = characteristic_list + breast_sizes

        # 태그가 특징 리스트에 포함되는지 확인
        tag_lower = tag.lower().strip()
        return any(feature.lower() in tag_lower for feature in all_features)

    def _is_clothing(self, tag: str) -> bool:
        """
        의류 태그 판별 (InteractiveAutocompleteManager의 Clothing_Wear 그룹 사용)
        """
        # InteractiveAutocompleteManager에서 데이터 가져오기
        if not self.autocomplete_manager or not hasattr(self.autocomplete_manager, 'datasets'):
            # fallback: 하드코딩된 키워드 사용
            clothing_keywords = [
                'dress', 'skirt', 'shirt', 'jacket', 'coat', 'pants',
                'shorts', 'thighhighs', 'stockings', 'boots', 'shoes',
                'hat', 'cap', 'gloves', 'scarf', 'tie', 'bow',
                'uniform', 'school uniform', 'suit', 'bikini', 'swimsuit',
                'underwear', 'bra', 'panties', 'naked', 'nude',
                'kimono', 'yukata', 'apron', 'hoodie', 'sweater'
            ]
            return any(keyword in tag for keyword in clothing_keywords)

        # datasets에서 "clothing" 데이터셋 가져오기
        clothing_dataset = self.autocomplete_manager.datasets.get("clothing", {})

        # Clothing_Wear 그룹의 태그들
        clothing_tags = {
            tag_key.lower() for tag_key, tag_data in clothing_dataset.items()
            if tag_data.get("group") == "Clothing_Wear"
        }

        # 정확한 매칭 확인
        return tag.lower() in clothing_tags

    def _is_background(self, tag: str) -> bool:
        """
        배경 태그 판별
        """
        background_keywords = [
            'outdoors', 'indoors', 'sky', 'cloud', 'tree', 'grass',
            'building', 'city', 'street', 'beach', 'ocean', 'sea',
            'mountain', 'forest', 'night', 'day', 'sunset', 'sunrise',
            'room', 'bedroom', 'classroom', 'kitchen', 'bathroom',
            'simple background', 'white background', 'black background',
            'gradient background', 'abstract background'
        ]

        return any(keyword in tag for keyword in background_keywords)

    # ===== 고급 필터 관리 =====

    def load_random_filter_config(self) -> dict:
        """
        고급 필터 설정 로드 (save/random_filter_config.json)

        Returns:
            dict: Group:Subgroup -> bool 매핑 (기본값 {})
        """
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                print(f"✅ 고급 필터 설정 로드 완료: {len(config)}개 항목")
                return config
            except Exception as e:
                print(f"❌ 고급 필터 설정 로드 실패: {e}")
                return {}
        else:
            print(f"⚠️ 고급 필터 설정 파일 없음 (기본값 사용): {CONFIG_FILE}")
            return {}

    def save_random_filter_config(self):
        """고급 필터 설정 저장 (save/random_filter_config.json)"""
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.random_filter_config, f, indent=4, ensure_ascii=False)
            print(f"✅ 고급 필터 설정 저장 완료: {CONFIG_FILE}")
        except Exception as e:
            print(f"❌ 고급 필터 설정 저장 실패: {e}")

    def _remove_auto_hide_tags(self, prompt: str) -> str:
        """
        Auto-Hide 패턴에 따라 태그 제거

        패턴 문법 (NAIA 2.0 기반):
        - `tag`: 정확한 태그 제거
        - `_pattern_`: 'pattern'을 포함하는 태그 제거 (예: _hair_ → blonde hair 제거)
        - `_pattern`: 'pattern'으로 끝나는 태그 제거
        - `pattern_`: 'pattern'으로 시작하는 태그 제거
        - `__pattern__`: 공백 무시하고 'pattern'을 포함하는 태그 제거 (예: __longhair__ → long hair 제거)
        - `~keyword`: 보호 키워드 (제거에서 제외)

        Args:
            prompt: 원본 프롬프트

        Returns:
            str: 필터링된 프롬프트
        """
        # Auto-Hide 패턴 가져오기
        autohide_patterns_str = self.random_filter_config.get("autohide_patterns", "")
        if not autohide_patterns_str or not autohide_patterns_str.strip():
            return prompt

        # 태그 파싱
        tags = [t.strip() for t in prompt.split(',') if t.strip()]

        # 보호 키워드와 패턴 분리
        protected_keywords = set()
        auto_hide_patterns = []

        for item in autohide_patterns_str.split(','):
            item = item.strip()
            if not item:
                continue
            if item.startswith('~'):
                # 보호 키워드
                protected_keywords.add(item[1:].strip().lower())
            else:
                auto_hide_patterns.append(item)

        # 제거 대상 빌드
        to_remove = set()

        for pattern in auto_hide_patterns:
            pattern_lower = pattern.lower()

            # 패턴 매칭 로직 (NAIA 2.0 기반)
            if pattern.startswith('__') and pattern.endswith('__') and len(pattern) > 4:
                # __pattern__: 공백 무시 포함 매칭 (이중 언더스코어)
                search_term = pattern[2:-2].replace('_', '')
                for tag in tags:
                    if search_term.lower() in tag.lower().replace(' ', ''):
                        to_remove.add(tag)

            elif pattern.startswith('_') and pattern.endswith('_') and len(pattern) > 2:
                # _pattern_: 포함 매칭 (단일 언더스코어, 공백 기반)
                search_term = pattern[1:-1].replace('_', ' ')
                for tag in tags:
                    if search_term.lower() in tag.lower():
                        to_remove.add(tag)

            elif pattern.startswith('_') and not pattern.endswith('_'):
                # _pattern: 끝나는 매칭
                search_term = pattern[1:].replace('_', ' ')
                for tag in tags:
                    if tag.lower().endswith(search_term.lower()):
                        to_remove.add(tag)

            elif pattern.endswith('_') and not pattern.startswith('_'):
                # pattern_: 시작하는 매칭
                search_term = pattern[:-1].replace('_', ' ')
                for tag in tags:
                    if tag.lower().startswith(search_term.lower()):
                        to_remove.add(tag)

            else:
                # 정확한 매칭
                for tag in tags:
                    if tag.lower() == pattern_lower:
                        to_remove.add(tag)

        # 보호 키워드 제외
        if protected_keywords:
            protected_to_keep = set()
            for tag in to_remove:
                tag_lower = tag.lower()
                for protected in protected_keywords:
                    if protected in tag_lower or tag_lower == protected:
                        protected_to_keep.add(tag)
                        break
            to_remove -= protected_to_keep

            if protected_to_keep:
                print(f"🔒 보호된 태그: {', '.join(protected_to_keep)}")

        # 제거 적용
        filtered = [t for t in tags if t not in to_remove]

        if to_remove:
            print(f"🚫 Auto-Hide 제거: {len(to_remove)}개 태그 → {', '.join(sorted(to_remove))}")
        else:
            print("✅ Auto-Hide: 매칭된 태그 없음")

        return ", ".join(filtered)
