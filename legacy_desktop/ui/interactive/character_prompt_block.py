from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTextEdit, QButtonGroup, QSizePolicy, QComboBox, QLineEdit
)
from PyQt6.QtCore import Qt, pyqtSignal
from legacy_desktop.ui.interactive.block_widget import BlockWidget
from legacy_desktop.ui.interactive.interactive_theme import (
    COMMON_STYLES, INTERACTIVE_FONTS, FONT_FAMILY, get_readonly_text_style, get_input_text_style
)
from legacy_desktop.ui.theme import DARK_COLORS
from legacy_desktop.ui.scaling_manager import get_scaled_size, get_scaled_font_size

# 캐릭터 딕셔너리 import (character_name -> prompt_string)
try:
    from danbooru_character import character_dict
    print(f"✅ character_dict 로딩 완료: {len(character_dict)}개 캐릭터")
except ImportError:
    print("⚠️ danbooru_character.character_dict를 찾을 수 없습니다. 빈 딕셔너리 사용")
    character_dict = {}

class GenderButton(QPushButton):
    """성별 선택 버튼"""
    def __init__(self, text, value, parent=None):
        super().__init__(text, parent)
        self.value = value
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(get_scaled_size(32))
        
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {COMMON_STYLES['text_primary']};
                border: 1px solid {COMMON_STYLES['input_border']};
                border-radius: {get_scaled_size(4)}px;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(16)}px;
            }}
            QPushButton:hover {{
                border-color: {COMMON_STYLES['text_secondary']};
            }}
            QPushButton:checked {{
                background-color: {COMMON_STYLES['input_focus']};
                color: white;
                border-color: {COMMON_STYLES['input_focus']};
                font-weight: bold;
            }}
        """)

class CharacterForm(QWidget):
    """단일 캐릭터 설정 폼"""
    random_requested = pyqtSignal(object, list, object, str) # editor, groups, subgroups (dict or None), field_type

    def __init__(self, parent=None, app_context=None, parent_window=None):
        super().__init__(parent)
        self.app_context = app_context
        self.parent_window = parent_window
        self._init_ui()
        
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(get_scaled_size(10))
        
        # 1. 성별 선택 (girl | boy | other)
        gender_layout = QHBoxLayout()
        gender_layout.setSpacing(8)
        
        self.gender_group = QButtonGroup(self)
        self.gender_group.setExclusive(True)
        
        self.btn_girl = GenderButton("Girl", "girl")
        self.btn_boy = GenderButton("Boy", "boy")
        self.btn_other = GenderButton("Other", "other")
        
        # 기본값 girl
        self.btn_girl.setChecked(True)
        
        for btn in [self.btn_girl, self.btn_boy, self.btn_other]:
            self.gender_group.addButton(btn)
            gender_layout.addWidget(btn, 1) # 균등 분할
            
        layout.addLayout(gender_layout)

        # 1.5. 캐릭터 / 작품명 (QLineEdit)
        char_name_container = QWidget()
        char_name_container.setStyleSheet("background-color: transparent;")
        char_name_layout = QVBoxLayout(char_name_container)
        char_name_layout.setContentsMargins(0, 0, 0, 0)
        char_name_layout.setSpacing(4)

        # 라벨 + 버튼 영역 (Header Row)
        char_name_header = QWidget()
        char_name_header.setStyleSheet("background-color: transparent;")
        char_name_header_layout = QHBoxLayout(char_name_header)
        char_name_header_layout.setContentsMargins(0, 0, 0, 0)
        char_name_header_layout.setSpacing(8)

        char_name_label = QLabel("캐릭터 / 작품명")
        char_name_label.setStyleSheet(f"""
            color: {COMMON_STYLES['text_secondary']};
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(16)}px;
            font-weight: bold;
            background-color: transparent;
            border: none;
        """)
        char_name_header_layout.addWidget(char_name_label)
        char_name_header_layout.addStretch()  # 우측 공간 확보

        # 랜덤 버튼 (🎲)
        self.btn_char_random = QPushButton("🎲")
        self.btn_char_random.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_char_random.setFixedSize(get_scaled_size(24), get_scaled_size(24))
        self.btn_char_random.setToolTip("랜덤 캐릭터/작품 선택")
        self.btn_char_random.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: #FFFFFF;
                border: none;
                margin: 0px;
                padding: 0px;
                text-align: center;
                font-family: 'Segoe UI Emoji';
                font-size: {get_scaled_font_size(18)}px;
            }}
            QPushButton:hover {{
                color: {DARK_COLORS['accent_blue']};
            }}
        """)
        self.btn_char_random.clicked.connect(self._on_char_random_clicked)
        char_name_header_layout.addWidget(self.btn_char_random)

        # 새로고침 버튼 (🔄)
        self.btn_char_refresh = QPushButton("🔄")
        self.btn_char_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_char_refresh.setFixedSize(get_scaled_size(24), get_scaled_size(24))
        self.btn_char_refresh.setToolTip("캐릭터/작품 새로고침")
        self.btn_char_refresh.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: #FFFFFF;
                border: none;
                margin: 0px;
                padding: 0px;
                text-align: center;
                font-family: 'Segoe UI Emoji';
                font-size: {get_scaled_font_size(18)}px;
            }}
            QPushButton:hover {{
                color: {DARK_COLORS['accent_blue']};
            }}
        """)
        self.btn_char_refresh.clicked.connect(self._on_char_refresh_clicked)
        char_name_header_layout.addWidget(self.btn_char_refresh)

        self.input_character_name = QLineEdit()
        self.input_character_name.setPlaceholderText("특정 캐릭터 태그 미사용시 공란")
        self.input_character_name.setStyleSheet(f"""
            QLineEdit {{
                background-color: {COMMON_STYLES['input_bg']};
                color: {COMMON_STYLES['text_primary']};
                border: 1px solid {COMMON_STYLES['input_border']};
                border-radius: 4px;
                padding: {get_scaled_size(8)}px;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(14)}px;
            }}
            QLineEdit:focus {{
                border: 1px solid {DARK_COLORS['accent_blue']};
            }}
        """)
        self.input_character_name.setProperty("autocomplete_ignore", True)
        self.input_character_name.setProperty("autocomplete_filter", "character")

        char_name_layout.addWidget(char_name_header)
        char_name_layout.addWidget(self.input_character_name)
        layout.addWidget(char_name_container)

        # 2. 입력 필드들
        self.input_body = self._create_input_field("체형 / 특징 (Body / Features)", field_type="body")
        # Person_Body (체형, 가슴, 귀, 눈, 얼굴, 머리카락, 헤어스타일, 기계/사이버, 피부색, 꼬리, 문신, 날개)
        # + Creatures (성별 기반 필터링: girl/boy/other에 따라 동적 필터)
        # 타이핑 자동완성 (autocomplete_filter) + 포커스 시 TagViewer (use_tag_viewer)
        self.input_body.setProperty("autocomplete_filter", "body")
        self.input_body.setProperty("autocomplete_ignore", True)
        # self.input_body.setProperty("use_tag_viewer", True)
        self.input_body.setProperty("allowed_groups", ["Person_Body", "Creatures"])
        self.input_body.setProperty("allowed_subgroups", {
            "Person_Body": [
                "body_type",        # 체형
                "breasts_tags",     # 가슴
                "ears_tags",        # 귀
                "eyes",             # 눈
                "eyes_tags",        # 눈 태그
                "face_tags",        # 얼굴 태그
                "hair",             # 머리카락
                "hair_color",       # 머리색
                "hair_styles",      # 헤어스타일
                "mechanical",       # 기계/사이버
                "skin_color",       # 피부색
                "tail",             # 꼬리
                "tattoo",           # 문신
                "wings"             # 날개
            ]
            # Creatures: 전체 서브그룹 허용 (성별 기반 태그 레벨 필터링은 랜덤 핸들러에서 처리)
        })

        self.input_pose = self._create_input_field("표정 / 행위 (Expression / Action)", field_type="pose")
        # Expression_Action (표정/행동) - 특정 서브그룹만 허용
        self.input_pose.setProperty("autocomplete_filter", "expression")
        # self.input_pose.setProperty("use_tag_viewer", True)
        self.input_pose.setProperty("autocomplete_ignore", True)
        self.input_pose.setProperty("allowed_groups", ["Expression_Action"])
        self.input_pose.setProperty("allowed_subgroups", {
            "Expression_Action": [
                "activity",             # 활동
                "clothing_action",      # 의복 동작
                "combat_actions",       # 전투 행동
                "emotion",              # 감정
                "expression",           # 표정
                "gesture",              # 제스처
                "gestures",             # 제스처 (복수형)
                "interaction",          # 상호작용
                "interactions",         # 상호작용 (복수형)
                "personality",          # 성격
                "pose",                 # 자세
                "state",                # 상태
                "verbs_and_gerunds"     # 동사/행위
            ]
        })

        self.input_attire = self._create_input_field("의상 (Attire / Outfit)", field_type="attire")
        # Clothing_Wear (의상/착용)
        self.input_attire.setProperty("autocomplete_filter", "clothing")
        # self.input_attire.setProperty("use_tag_viewer", True)
        self.input_attire.setProperty("autocomplete_ignore", True)
        self.input_attire.setProperty("allowed_groups", ["Clothing_Wear"])

        # 네거티브는 붉은색 테두리로 강조
        self.input_negative = self._create_input_field("네거티브 프롬프트 (Negative Prompt)", field_type="negative", show_random_btn=False)
        self.input_negative.setStyleSheet(get_input_text_style() + f"border: 1px solid {COMMON_STYLES['error']};")
        # general (전체 태그)
        self.input_negative.setProperty("autocomplete_filter", "general")
        # self.input_negative.setProperty("use_tag_viewer", True)
        self.input_negative.setProperty("allowed_groups", None)  # 전체 그룹 허용
        self.input_negative.setProperty("autocomplete_ignore", True)

    def _create_input_field(self, label_text, field_type="unknown", show_random_btn=True):
        container = QWidget()
        container.setStyleSheet("background-color: transparent;")
        l = QVBoxLayout(container)
        l.setContentsMargins(0,0,0,0)
        l.setSpacing(4)

        # 라벨 영역 (Header Row) - 버튼 추가를 위한 HBox 구조
        header_widget = QWidget()
        header_widget.setStyleSheet("background-color: transparent;")
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        lbl = QLabel(label_text)
        lbl.setStyleSheet(f"""
            color: {COMMON_STYLES['text_secondary']};
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(16)}px;
            font-weight: bold;
            background-color: transparent;
            border: none;
        """)
        header_layout.addWidget(lbl)
        header_layout.addStretch() # 우측 공간 확보 (버튼 추가용)

        editor = QTextEdit()
        editor.setFixedHeight(get_scaled_size(140)) # Small textedit
        editor.setMinimumWidth(get_scaled_size(450))
        editor.setStyleSheet(get_input_text_style())

        # 필드 타입 저장 (랜덤 요청 시 사용)
        editor.setProperty("field_type", field_type)

        if show_random_btn:
            # Random Button
            btn_random = QPushButton("🎲")
            btn_random.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_random.setFixedSize(get_scaled_size(24), get_scaled_size(24))
            btn_random.setToolTip("랜덤 태그 추가 (Quick Search 기반)")
            btn_random.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: #FFFFFF;
                    border: none;
                    margin: 0px;
                    padding: 0px;
                    text-align: center;
                    font-family: 'Segoe UI Emoji';
                    font-size: {get_scaled_font_size(18)}px;
                }}
                QPushButton:hover {{
                    color: {DARK_COLORS['accent_blue']};
                }}
            """)

            # Connect signal now that editor exists
            btn_random.clicked.connect(lambda: self._on_random_clicked(editor))

            # Add button to header layout
            header_layout.addWidget(btn_random)

        l.addWidget(header_widget)
        l.addWidget(editor)


        self.layout().addWidget(container)
        return editor

    def _on_random_clicked(self, editor):
        groups = editor.property("allowed_groups")
        subgroups = editor.property("allowed_subgroups")
        field_type = editor.property("field_type") or "unknown"
        self.random_requested.emit(editor, groups, subgroups, field_type)

    def get_data(self):
        gender_btn = self.gender_group.checkedButton()
        gender = gender_btn.value if gender_btn else "girl"

        return {
            "gender": gender,
            "character_name": self.input_character_name.text(),
            "body": self.input_body.toPlainText(),
            "pose": self.input_pose.toPlainText(),
            "attire": self.input_attire.toPlainText(),
            "negative": self.input_negative.toPlainText()
        }
        
    def set_data(self, data):
        """데이터 복원"""
        gender = data.get('gender', 'girl')
        if gender == 'girl': self.btn_girl.setChecked(True)
        elif gender == 'boy': self.btn_boy.setChecked(True)
        else: self.btn_other.setChecked(True)

        self.input_character_name.setText(data.get('character_name', ''))
        self.input_body.setText(data.get('body', ''))
        self.input_pose.setText(data.get('pose', ''))
        self.input_attire.setText(data.get('attire', ''))
        self.input_negative.setText(data.get('negative', ''))

    def _on_char_random_clicked(self):
        """랜덤 버튼 클릭: character_dict에서 랜덤 선택"""
        import random

        try:
            # 전역 character_dict 사용
            if not character_dict:
                print("⚠️ character_dict가 비어있습니다.")
                return

            # 랜덤 선택
            character_name, character_prompt = random.choice(list(character_dict.items()))

            # NAI 모드가 아닌 경우 괄호 이스케이프
            if self.app_context and self.app_context.current_api_mode != 'NAI':
                character_name = character_name.replace('(', r'\(').replace(')', r'\)')

            # input_character_name에 설정
            self.input_character_name.setText(character_name)

            # 필터링 로직 적용
            self._apply_character_prompt(character_prompt)

            print(f"✅ 랜덤 캐릭터 선택: {character_name}")

        except Exception as e:
            print(f"⚠️ 랜덤 캐릭터 선택 실패: {e}")
            import traceback
            traceback.print_exc()

    def _on_char_refresh_clicked(self):
        """새로고침 버튼 클릭: 현재 입력된 캐릭터명으로 프롬프트 조회"""
        try:
            # 현재 입력값 가져오기
            current_text = self.input_character_name.text().strip()
            if not current_text:
                print("⚠️ 캐릭터/작품명이 입력되지 않았습니다.")
                return

            # 전역 character_dict 사용
            if not character_dict:
                print("⚠️ character_dict가 비어있습니다.")
                return

            # ',' 로 분리하고 strip하여 순서대로 조회
            tags = [tag.strip() for tag in current_text.split(',') if tag.strip()]

            character_prompt = None
            matched_tag = None
            for tag in tags:
                if tag in character_dict:
                    character_prompt = character_dict[tag]
                    matched_tag = tag
                    break

            if not character_prompt:
                print(f"⚠️ 매칭되는 캐릭터를 찾을 수 없습니다: {tags}")
                return

            # 필터링 로직 적용
            self._apply_character_prompt(character_prompt)

            print(f"✅ 캐릭터 프롬프트 새로고침: {matched_tag}")

        except Exception as e:
            print(f"⚠️ 캐릭터 프롬프트 새로고침 실패: {e}")
            import traceback
            traceback.print_exc()

    def _apply_character_prompt(self, character_prompt: str):
        """
        캐릭터 프롬프트를 body와 attire로 분리하여 적용

        Args:
            character_prompt: character_dict에서 가져온 프롬프트 문자열
        """
        try:
            # InteractiveAutocompleteManager 접근
            parent_window = self.parent_window

            # parent_window를 찾지 못했으면 다시 시도
            if not parent_window:
                print("⚠️ parent_window를 찾을 수 없습니다. 재탐색 중...")
                from PyQt6.QtWidgets import QApplication
                for widget in QApplication.topLevelWidgets():
                    if hasattr(widget, 'autocomplete_manager') and widget.__class__.__name__ == 'InteractiveWindow':
                        parent_window = widget
                        print(f"✅ QApplication을 통해 InteractiveWindow 발견")
                        break

            if not parent_window:
                print("⚠️ InteractiveWindow를 찾을 수 없습니다. 프롬프트를 그대로 적용합니다.")
                # 프롬프트를 그대로 attire에 적용
                self.input_attire.setText(character_prompt)
                return

            autocomplete_manager = getattr(parent_window, 'autocomplete_manager', None)
            if not autocomplete_manager:
                print("⚠️ InteractiveAutocompleteManager를 찾을 수 없습니다. 프롬프트를 그대로 적용합니다.")
                # 프롬프트를 그대로 attire에 적용
                self.input_attire.setText(character_prompt)
                return

            # character_prompt를 ', '로 split
            tags = [tag.strip() for tag in character_prompt.split(',') if tag.strip()]

            # body 데이터셋 가져오기
            body_dataset = autocomplete_manager.datasets.get('body', {})

            # Person_Body 그룹 필터링
            person_body_tags = {
                tag: data for tag, data in body_dataset.items()
                if data.get('group') == 'Person_Body'
            }

            # 태그 분류
            body_tags = []
            attire_tags = []

            for tag in tags:
                if tag in person_body_tags:
                    body_tags.append(tag)
                else:
                    attire_tags.append(tag)

            # 필드에 덮어씌우기
            self.input_body.setText(', '.join(body_tags))
            self.input_attire.setText(', '.join(attire_tags))

            print(f"  📦 Body: {len(body_tags)}개 태그")
            print(f"  👗 Attire: {len(attire_tags)}개 태그")

        except Exception as e:
            print(f"⚠️ 캐릭터 프롬프트 적용 실패: {e}")
            import traceback
            traceback.print_exc()

class CharacterPromptBlock(BlockWidget):
    add_character_clicked = pyqtSignal()
    remove_character_clicked = pyqtSignal()
    random_field_requested = pyqtSignal(object, list, object, str) # editor, groups, subgroups, field_type

    def __init__(self, index=1, parent=None, app_context=None):
        # 타이틀: 캐릭터 프롬프트 {index}
        super().__init__(f"캐릭터 프롬프트 {index}", parent, block_type='latent')
        self.index = index
        self.app_context = app_context
        self._init_content()
        
    def _init_content(self):
        layout = self.get_content_layout()
        layout.setSpacing(get_scaled_size(12))

        # CharacterPromptBlock의 parent는 InteractiveWindow
        parent_window = self.parent()
        search_depth = 0
        max_depth = 10

        while parent_window and not hasattr(parent_window, 'autocomplete_manager') and search_depth < max_depth:
            parent_window = parent_window.parent()
            search_depth += 1

        # InteractiveWindow를 찾았는지 확인
        if parent_window and hasattr(parent_window, 'autocomplete_manager'):
            print(f"✅ InteractiveWindow 발견 (depth: {search_depth})")
        else:
            print(f"⚠️ InteractiveWindow를 찾을 수 없습니다 (searched depth: {search_depth})")
            # 대체 방법: QApplication을 통해 InteractiveWindow 찾기
            from PyQt6.QtWidgets import QApplication
            for widget in QApplication.topLevelWidgets():
                if hasattr(widget, 'autocomplete_manager') and widget.__class__.__name__ == 'InteractiveWindow':
                    parent_window = widget
                    print(f"✅ QApplication을 통해 InteractiveWindow 발견")
                    break

        self.form = CharacterForm(parent=self, app_context=self.app_context, parent_window=parent_window)
        self.form.random_requested.connect(self.random_field_requested.emit)
        layout.addWidget(self.form)
        
        # 시선 선택 (콤보박스 3개)
        gaze_selectors = self._create_gaze_selectors()
        layout.addWidget(gaze_selectors)
        
        # 버튼 생성
        if self.index == 1:
            self.btn_add = QPushButton(" + 캐릭터 추가 ")
            self.btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_add.setStyleSheet(f"""
                QPushButton {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    color: {COMMON_STYLES['text_primary']};
                    border: 1px solid {COMMON_STYLES['input_border']};
                    border-radius: 4px;
                    padding: 10px;
                    font-family: {FONT_FAMILY};
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {DARK_COLORS['bg_hover']};
                }}
            """)
            self.btn_add.clicked.connect(self.add_character_clicked.emit)
            layout.addWidget(self.btn_add)

            # COMFYUI 모드에서 "+ 캐릭터 추가" 버튼 숨김
            if self.app_context and self.app_context.current_api_mode == 'COMFYUI':
                self.btn_add.hide()
        else:
            self.btn_remove = QPushButton(" - 캐릭터 제거 ")
            self.btn_remove.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_remove.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {COMMON_STYLES['text_secondary']};
                    border: 1px solid {COMMON_STYLES['input_border']};
                    border-radius: 4px;
                    padding: 10px;
                    font-family: {FONT_FAMILY};
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {DARK_COLORS['bg_hover']};
                    color: {COMMON_STYLES['text_primary']};
                }}
            """)
            self.btn_remove.clicked.connect(self.remove_character_clicked.emit)
            layout.addWidget(self.btn_remove)
        
    def get_data(self):
        # 폼 데이터에 시선 데이터 추가?
        # 일단 폼 데이터만 반환하도록 두고, 필요하면 확장
        data = self.form.get_data()
        # 시선 데이터 추가 (태그 값)
        gaze_data = [cb.currentData() for cb in self.gaze_combos]
        data['gaze'] = gaze_data
        return data

    def get_prompt_data(self):
        """
        이미지 생성용 프롬프트 데이터 반환

        Returns:
            dict: {"prompt": str, "negative": str}
        """
        data = self.get_data()

        # COMFYUI 모드 확인
        is_comfyui = self.app_context and self.app_context.current_api_mode == 'COMFYUI'

        parts = []

        # 0. 캐릭터 / 작품명 (있는 경우 맨 앞에)
        character_name = data.get('character_name', '').strip()
        if character_name:
            parts.append(character_name)

        # 1. 성별 태그 (필수, 기본값 "girl")
        gender = data.get('gender', 'girl')
        parts.append(gender)

        # 2. 신체 (input_body)
        body = data.get('body', '').strip()
        if body:
            parts.append(body)

        # 3. 자세 (input_pose)
        pose = data.get('pose', '').strip()
        if pose:
            parts.append(pose)

        # 4. 의상 (input_attire)
        attire = data.get('attire', '').strip()
        if attire:
            parts.append(attire)

        # 5. 시선 (gaze_combos) - 비어있지 않은 항목만
        gaze_list = data.get('gaze', [])
        gaze_tags = [g for g in gaze_list if g]  # 빈 문자열 제외
        if gaze_tags:
            parts.extend(gaze_tags)

        # 최종 프롬프트 조합
        full_prompt = ', '.join(parts)

        # 네거티브 프롬프트
        negative = data.get('negative', '').strip()

        # COMFYUI 모드: 모든 내용(시선 포함)을 하나의 문자열로 합침
        if is_comfyui:
            print(f"🎨 COMFYUI 캐릭터 프롬프트: 모든 필드 통합 (시선 포함)")

        return {
            "prompt": full_prompt,
            "negative": negative
        }

    def set_data(self, data):
        self.form.set_data(data)
        # 시선 데이터 복원 로직 필요하면 추가

    def _create_gaze_selectors(self):
        wrapper = QWidget()
        wrapper.setStyleSheet("background-color: transparent;")
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setSpacing(4) # 좁은 간격
        
        # 공통 스타일
        combo_style = f"""
            QComboBox {{
                background-color: {COMMON_STYLES['input_bg']};
                color: {COMMON_STYLES['text_primary']};
                border: 1px solid {COMMON_STYLES['input_border']};
                border-radius: 4px;
                padding: 4px;
                font-family: {FONT_FAMILY};
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox QAbstractItemView {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {COMMON_STYLES['text_primary']};
                selection-background-color: {DARK_COLORS['bg_hover']};
            }}
        """

        # 데이터 정의
        gaze1_items = [
            ("정의하지 않음", ""),
            ("정면(앞을 봄)", "looking forward"),
            ("위를 봄", "looking up"),
            ("아래를 봄", "looking down"),
            ("옆을 봄(측면 시선)", "looking aside"),
            ("시선을 피함(외면)", "looking away"),
            ("뒤를 돌아봄", "looking back"),
            ("멀리 바라봄", "looking afar"),
            ("관객/카메라를 봄", "looking at viewer"),
            ("뒤돌아 관객을 봄", "looking back at viewer")
        ]
        gaze2_items = [
            ("정의하지 않음", ""),
            ("다른 사람을 봄", "looking at another"),
            ("파트너를 봄", "looking at partner"),
            ("자기 자신을 봄", "looking at self"),
            ("관객을 봄(명시)", "looking at viewer")
        ]
        gaze3_items = [
            ("정의하지 않음", ""),
            ("가슴을 봄", "looking at breasts"),
            ("자기 가슴을 봄", "looking at own breasts"),
            ("엉덩이를 봄", "looking at butt"),
            ("배를 봄", "looking at belly"),
            ("발을 봄", "looking at feet"),
            ("가슴/흉부를 봄", "looking at chest"),
            ("성기를 봄", "looking at genitalia"),
            ("부풀어 오른 부분을 봄", "looking at bulge"),
            ("항문을 봄", "looking at anus")
        ]
        
        all_gaze_items = [gaze1_items, gaze2_items, gaze3_items]

        # 시선 1~3
        self.gaze_combos = []
        for i, items in enumerate(all_gaze_items):
            row_layout = QHBoxLayout()
            row_layout.setContentsMargins(0, 0, 0, 0)
            
            lbl = QLabel(f"시선{i+1}:")
            lbl.setFixedWidth(get_scaled_size(40))
            lbl.setStyleSheet(f"color: {COMMON_STYLES['text_secondary']}; font-family: {FONT_FAMILY}; background-color: transparent;")
            
            combo = QComboBox()
            combo.setCursor(Qt.CursorShape.PointingHandCursor)
            combo.setStyleSheet(combo_style)
            
            for text, tag in items:
                combo.addItem(text, tag)
            
            row_layout.addWidget(lbl)
            row_layout.addWidget(combo)
            
            wrapper_layout.addLayout(row_layout)
            self.gaze_combos.append(combo)

        return wrapper

    def register_autocomplete(self, autocomplete_manager):
        """
        자동완성 매니저에 위젯 등록

        각 입력 필드는 다른 데이터셋(카테고리)을 사용합니다:
        - input_body: body (Person_Body + Creatures)
        - input_pose: expression (Expression_Action)
        - input_attire: clothing (Clothing_Wear)
        - input_negative: general (전체 태그)
        """
        # Body/Features - 캐릭터 외형 (인체/신체 + 생물/종족)
        autocomplete_manager.register_widget(
            self.form.input_body,
            dataset_id="body"
        )

        # Expression/Action - 표정/행동
        autocomplete_manager.register_widget(
            self.form.input_pose,
            dataset_id="expression"
        )

        # Attire/Outfit - 의상
        autocomplete_manager.register_widget(
            self.form.input_attire,
            dataset_id="clothing"
        )

        # Negative Prompt - 전체 태그
        autocomplete_manager.register_widget(
            self.form.input_negative,
            dataset_id="general"
        )
