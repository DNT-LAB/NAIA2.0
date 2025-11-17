import os
import json
import copy
import pandas as pd
from pathlib import Path
from typing import List, Dict, Any
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QScrollArea, QGridLayout, QCheckBox, QTextEdit,
    QDialog, QLineEdit, QListWidget, QSplitter, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from ui.modern_menu import setModernStyle
from interfaces.base_module import BaseMiddleModule
from interfaces.mode_aware_module import ModeAwareModule
from core.context import AppContext
from core.prompt_context import PromptContext
from core.wildcard_processor import WildcardProcessor
from ui.theme import DARK_STYLES, DARK_COLORS, get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from danbooru_character import character_dict, character_dict_count


class CharacterSearchDialog(QDialog):
    """캐릭터 검색 다이얼로그 - danbooru_character.py 기반 + 커스텀 딕셔너리 지원"""

    character_selected = pyqtSignal(str, str)  # (prompt_tags, uc_tags)

    def __init__(self, parent_prompt_textbox: QTextEdit, parent_uc_textbox: QTextEdit, parent=None):
        super().__init__(parent)
        self.parent_prompt_textbox = parent_prompt_textbox
        self.parent_uc_textbox = parent_uc_textbox

        # Custom dictionary path
        self.custom_dict_path = Path("save/custom_character_dict.json")
        self.custom_dict = {}
        self.load_custom_dict()

        # State management
        self.is_editing = False
        self.current_character = None
        self.original_prompt = ""
        self.original_negative = ""

        self.setWindowTitle("캐릭터 검색")
        #self.resize(get_scaled_size(950), get_scaled_size(750))
        self.setModal(True)
        self.setFixedSize(get_scaled_size(950), get_scaled_size(700))

        # 다크 테마 적용
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)

        self.init_ui()

        # 초기 검색 실행
        self.do_search()

    def init_ui(self):
        """UI 초기화"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(get_scaled_size(10))
        main_layout.setContentsMargins(
            get_scaled_size(15), get_scaled_size(15),
            get_scaled_size(15), get_scaled_size(15)
        )

        # 검색 패널
        search_layout = QHBoxLayout()

        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("캐릭터 이름 또는 태그 검색 (3자 이상)")
        self.search_entry.setStyleSheet(DARK_STYLES['compact_lineedit'])
        self.search_entry.returnPressed.connect(self.do_search)
        self.search_entry.setProperty("autocomplete_ignore", True)
        search_layout.addWidget(self.search_entry, stretch=3)

        self.search_btn = QPushButton("검색 (엔터)")
        self.search_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.search_btn.clicked.connect(self.do_search)
        search_layout.addWidget(self.search_btn, stretch=1)

        main_layout.addLayout(search_layout)

        # 수평 레이아웃 (리스트박스 + 프롬프트 영역)
        content_layout = QHBoxLayout()
        content_layout.setSpacing(get_scaled_size(10))

        # ===== 왼쪽 패널: 캐릭터 리스트 (40% 비율) =====
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(get_scaled_size(5))

        # 캐릭터 리스트박스
        self.character_listbox = QListWidget()
        self.character_listbox.setStyleSheet(f"""
            QListWidget {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border_light']};
                border-radius: 4px;
                font-size: {get_scaled_font_size(14)}px;
                padding: {get_scaled_size(5)}px;
            }}
            QListWidget::item {{
                padding: {get_scaled_size(8)}px;
            }}
            QListWidget::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
                color: {DARK_COLORS['text_primary']};
            }}
            QListWidget::item:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}

            /* 세로 스크롤바 스타일 (다크 테마에서 보이도록) */
            QScrollBar:vertical {{
                width: {get_scaled_size(12)}px;
                margin: 0;
                background: {DARK_COLORS['bg_secondary']};
                border: none;
                border-radius: {get_scaled_size(6)}px;
            }}
            QScrollBar::handle:vertical {{
                background: {DARK_COLORS['accent_blue']};
                min-height: {get_scaled_size(30)}px;
                border-radius: {get_scaled_size(6)}px;
                margin: {get_scaled_size(2)}px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {DARK_COLORS['accent_blue_hover']};
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0px;
                subcontrol-origin: margin;
            }}
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """)
        # [8] 수평 스크롤 제거, 수직 스크롤만 허용
        self.character_listbox.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.character_listbox.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Word wrapping 비활성화 (스크롤 문제 해결)
        self.character_listbox.setWordWrap(False)

        # 텍스트가 잘리는 것 방지
        self.character_listbox.setTextElideMode(Qt.TextElideMode.ElideRight)

        # 크기 제약 설정
        self.character_listbox.setMinimumWidth(get_scaled_size(300))
        self.character_listbox.setMaximumHeight(get_scaled_size(400))  # 최대 높이 제한

        self.character_listbox.itemSelectionChanged.connect(self.on_listbox_select)
        left_layout.addWidget(self.character_listbox)

        # [7] 커스텀 딕셔너리 필터 체크박스
        self.custom_filter_checkbox = QCheckBox("⭐ 커스텀 딕셔너리만 보기")
        self.custom_filter_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.custom_filter_checkbox.toggled.connect(self.do_search)
        left_layout.addWidget(self.custom_filter_checkbox)

        content_layout.addWidget(left_panel, stretch=2)  # 40% 비율

        # ===== 오른쪽 패널: 프롬프트 영역 (60% 비율) =====
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(get_scaled_size(8))

        # [1] 캐릭터 프롬프트
        prompt_label = QLabel("캐릭터 프롬프트:")
        prompt_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(16)}px;")
        right_layout.addWidget(prompt_label)

        self.character_prompt = QTextEdit()
        self.character_prompt.setAcceptRichText(False)  # 서식 붙여넣기 차단
        self.character_prompt.setReadOnly(True)
        self.character_prompt.setPlaceholderText("캐릭터를 선택하면 태그가 표시됩니다")
        self.character_prompt.setStyleSheet(DARK_STYLES['compact_textedit'])
        #self.character_prompt.setProperty("autocomplete_ignore", True)
        self.character_prompt.setMinimumHeight(get_scaled_size(120))
        right_layout.addWidget(self.character_prompt)

        # [2] 네거티브 프롬프트
        negative_label = QLabel("Negative 프롬프트:")
        negative_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(16)}px;")
        right_layout.addWidget(negative_label)

        self.character_negative = QTextEdit()
        self.character_negative.setAcceptRichText(False)  # 서식 붙여넣기 차단
        self.character_negative.setReadOnly(True)
        self.character_negative.setPlaceholderText("negative 프롬프트를 추가하려면 [수정] 버튼을 눌러 추가 후 [저장] 하세요")
        self.character_negative.setStyleSheet(DARK_STYLES['compact_textedit'] + f"color: {DARK_COLORS['text_secondary']};")
        #self.character_negative.setProperty("autocomplete_ignore", True)
        self.character_negative.setMinimumHeight(get_scaled_size(80))
        right_layout.addWidget(self.character_negative)

        content_layout.addWidget(right_panel, stretch=3)  # 60% 비율

        main_layout.addLayout(content_layout)

        # ===== [3] 편집/저장 버튼 행 (우측 정렬) =====
        edit_button_layout = QHBoxLayout()
        edit_button_layout.addStretch()

        # [5] 초기화 버튼 (조건부 표시)
        self.reset_btn = QPushButton("초기화")
        self.reset_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.reset_btn.clicked.connect(self.on_reset_clicked)
        self.reset_btn.setVisible(False)  # 초기에는 숨김
        edit_button_layout.addWidget(self.reset_btn)

        self.edit_btn = QPushButton("수정")
        self.edit_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.edit_btn.clicked.connect(self.on_edit_clicked)
        edit_button_layout.addWidget(self.edit_btn)

        self.save_btn = QPushButton("저장")
        self.save_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.save_btn.clicked.connect(self.on_save_clicked)
        self.save_btn.setEnabled(False)  # 초기에는 비활성화
        edit_button_layout.addWidget(self.save_btn)

        main_layout.addLayout(edit_button_layout)

        # ===== [6] 커스텀 딕셔너리 추가 버튼 =====
        add_custom_layout = QHBoxLayout()
        self.add_custom_btn = QPushButton("➕ 커스텀 딕셔너리 추가")
        self.add_custom_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.add_custom_btn.clicked.connect(self.on_add_custom_clicked)
        add_custom_layout.addWidget(self.add_custom_btn)
        main_layout.addLayout(add_custom_layout)

        # ===== 삽입/닫기 버튼 행 =====
        action_button_layout = QHBoxLayout()

        self.insert_btn = QPushButton("프롬프트에 삽입")
        self.insert_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.insert_btn.clicked.connect(self.on_insert_clicked)
        action_button_layout.addWidget(self.insert_btn)

        self.close_btn = QPushButton("닫기")
        self.close_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.close_btn.clicked.connect(self.close)
        action_button_layout.addWidget(self.close_btn)

        main_layout.addLayout(action_button_layout)

    # ===== Custom Dictionary Management =====

    def load_custom_dict(self):
        """커스텀 딕셔너리 로드"""
        try:
            if self.custom_dict_path.exists():
                with open(self.custom_dict_path, 'r', encoding='utf-8') as f:
                    self.custom_dict = json.load(f)
                print(f"✅ 커스텀 딕셔너리 로드 완료: {len(self.custom_dict)}개")
            else:
                self.custom_dict = {}
        except Exception as e:
            print(f"❌ 커스텀 딕셔너리 로드 실패: {e}")
            self.custom_dict = {}

    def save_custom_dict(self):
        """커스텀 딕셔너리 저장"""
        try:
            # save 폴더 생성
            self.custom_dict_path.parent.mkdir(parents=True, exist_ok=True)

            with open(self.custom_dict_path, 'w', encoding='utf-8') as f:
                json.dump(self.custom_dict, f, ensure_ascii=False, indent=2)
            print(f"✅ 커스텀 딕셔너리 저장 완료: {len(self.custom_dict)}개")
        except Exception as e:
            print(f"❌ 커스텀 딕셔너리 저장 실패: {e}")

    # ===== Search & Selection =====

    def do_search(self):
        """[7] 검색 실행 (커스텀 필터 지원)"""
        search_keyword = self.search_entry.text().strip().lower()
        self.character_listbox.clear()

        all_matching_keywords = []
        show_custom_only = self.custom_filter_checkbox.isChecked()

        if show_custom_only:
            # 커스텀 딕셔너리만 표시
            for character in self.custom_dict.keys():
                count = character_dict_count.get(character, None)
                all_matching_keywords.append((character, count, True))  # True = custom
        else:
            # 일반 검색 (custom + character_dict)
            if search_keyword and len(search_keyword) >= 3:
                # 키워드 검색 모드 (count > 20)
                # 커스텀 딕셔너리 먼저 검색
                for character in self.custom_dict.keys():
                    if search_keyword in character.lower():
                        count = character_dict_count.get(character, None)
                        all_matching_keywords.append((character, count, True))

                # character_dict 검색
                for character, tags in character_dict.items():
                    if character not in self.custom_dict:  # 중복 제거
                        if (search_keyword in character.lower() or
                            search_keyword in tags.lower()):
                            count = character_dict_count.get(character, None)
                            if count is None or count > 20:
                                all_matching_keywords.append((character, count, False))
            else:
                # 기본 모드 (count > 50)
                # 커스텀 딕셔너리 먼저
                for character in self.custom_dict.keys():
                    count = character_dict_count.get(character, None)
                    all_matching_keywords.append((character, count, True))

                # character_dict에서 count > 50
                for character in character_dict.keys():
                    if character not in self.custom_dict:  # 중복 제거
                        count = character_dict_count.get(character, None)
                        if count and count > 50:
                            all_matching_keywords.append((character, count, False))

        # 정렬: 커스텀 우선, 그 다음 count 기준 내림차순
        all_matching_keywords.sort(
            key=lambda item: (not item[2], -(item[1] if item[1] is not None else -1))
        )

        # 리스트박스에 추가
        for keyword, count, is_custom in all_matching_keywords:
            display_count = str(count) if count is not None else "?"
            prefix = "⭐ " if is_custom else ""
            self.character_listbox.addItem(f"{prefix}{keyword} - {display_count}")

        # 결과 개수 표시
        print(f"✅ 캐릭터 검색 결과: {len(all_matching_keywords)}개 (커스텀: {sum(1 for _, _, is_c in all_matching_keywords if is_c)}개)")

    def on_listbox_select(self):
        """[5] 리스트박스 선택 이벤트 (커스텀 딕셔너리 우선)"""
        selected_items = self.character_listbox.selectedItems()
        if not selected_items:
            return

        selected_text = selected_items[0].text()
        # ⭐ 제거하고 키워드 추출
        keyword = selected_text.replace("⭐ ", "").split(" - ")[0]

        self.current_character = keyword

        # 커스텀 딕셔너리 우선 확인
        if keyword in self.custom_dict:
            # 커스텀 데이터 사용
            custom_data = self.custom_dict[keyword]
            prompt = custom_data.get('character_prompt', '')
            negative = custom_data.get('character_negative', '')

            self.character_prompt.setPlainText(prompt)
            self.character_negative.setPlainText(negative)

            # [5] 초기화 버튼 표시
            self.reset_btn.setVisible(True)

            print(f"✅ 커스텀 캐릭터 로드: {keyword}")
        else:
            # 기본 character_dict 사용
            if keyword in character_dict:
                tags = character_dict[keyword]
                # 첫 번째 태그(캐릭터 이름) 제거
                tag_list = tags.split(', ')
                if len(tag_list) >= 2:
                    filtered_tags = ", ".join(tag_list[1:])
                else:
                    filtered_tags = ", ".join(tag_list)

                self.character_prompt.setPlainText(filtered_tags)
                self.character_negative.setPlainText("")  # 기본적으로 비어있음
            else:
                self.character_prompt.setPlainText("(태그 정보 없음)")
                self.character_negative.setPlainText("")

            # 초기화 버튼 숨김
            self.reset_btn.setVisible(False)

        # 원본 값 저장 (취소 시 복원용)
        self.original_prompt = self.character_prompt.toPlainText()
        self.original_negative = self.character_negative.toPlainText()

    # ===== Edit/Save/Cancel/Reset Handlers =====

    def on_edit_clicked(self):
        """[3] 수정 버튼 클릭"""
        if not self.is_editing:
            # 수정 모드로 전환
            self.is_editing = True
            self.edit_btn.setText("취소")
            self.save_btn.setEnabled(True)
            self.character_prompt.setReadOnly(False)
            self.character_negative.setReadOnly(False)
            print("✏️ 수정 모드 활성화")
        else:
            # 취소 (원본 복원)
            self.is_editing = False
            self.edit_btn.setText("수정")
            self.save_btn.setEnabled(False)
            self.character_prompt.setReadOnly(True)
            self.character_negative.setReadOnly(True)

            # 원본 값 복원
            self.character_prompt.setPlainText(self.original_prompt)
            self.character_negative.setPlainText(self.original_negative)
            print("❌ 수정 취소")

    def on_save_clicked(self):
        """[4] 저장 버튼 클릭"""
        if not self.current_character:
            QMessageBox.warning(self, "경고", "저장할 캐릭터를 선택해주세요.")
            return

        # 현재 값 저장
        prompt = self.character_prompt.toPlainText().strip()
        negative = self.character_negative.toPlainText().strip()

        self.custom_dict[self.current_character] = {
            'character_prompt': prompt,
            'character_negative': negative
        }

        self.save_custom_dict()

        # 수정 모드 종료
        self.is_editing = False
        self.edit_btn.setText("수정")
        self.save_btn.setEnabled(False)
        self.character_prompt.setReadOnly(True)
        self.character_negative.setReadOnly(True)

        # 원본 값 업데이트
        self.original_prompt = prompt
        self.original_negative = negative

        # 초기화 버튼 표시
        self.reset_btn.setVisible(True)

        # 검색 결과 갱신 (⭐ 표시 업데이트)
        self.do_search()

        print(f"💾 캐릭터 저장 완료: {self.current_character}")

    def on_reset_clicked(self):
        """[5] 초기화 버튼 클릭 (커스텀 데이터 삭제)"""
        if not self.current_character:
            return

        reply = QMessageBox.question(
            self,
            "초기화 확인",
            f"'{self.current_character}'의 커스텀 설정을 삭제하고 기본 데이터로 복원하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # 커스텀 딕셔너리에서 제거
            if self.current_character in self.custom_dict:
                del self.custom_dict[self.current_character]
                self.save_custom_dict()

            # 기본 데이터 다시 로드
            self.on_listbox_select()

            # 검색 결과 갱신
            self.do_search()

            print(f"🔄 캐릭터 초기화 완료: {self.current_character}")

    # ===== Add Custom Character Dialog =====

    def on_add_custom_clicked(self):
        """[6] 커스텀 딕셔너리 추가 버튼 클릭"""
        dialog = AddCustomCharacterDialog(
            parent_prompt_textbox=self.parent_prompt_textbox,
            parent_uc_textbox=self.parent_uc_textbox,
            custom_dict=self.custom_dict,
            parent=self
        )

        if dialog.exec() == QDialog.DialogCode.Accepted:
            # 저장 완료, 딕셔너리 갱신
            self.save_custom_dict()
            self.do_search()

    # ===== Insert Action =====

    def on_insert_clicked(self):
        """[9] 프롬프트에 삽입 버튼 클릭 (replace 방식)"""
        prompt_content = self.character_prompt.toPlainText().strip()
        negative_content = self.character_negative.toPlainText().strip()

        if not prompt_content or prompt_content == "(태그 정보 없음)":
            return

        # [9] 기존 텍스트 삭제하고 삽입 (replace)
        if self.parent_prompt_textbox:
            self.parent_prompt_textbox.setPlainText(prompt_content)
            print(f"✅ 캐릭터 프롬프트 삽입 완료: {prompt_content[:50]}...")

        if self.parent_uc_textbox and negative_content:
            self.parent_uc_textbox.setPlainText(negative_content)
            print(f"✅ Negative 프롬프트 삽입 완료: {negative_content[:50]}...")

        # 다이얼로그 닫기
        self.accept()


class AddCustomCharacterDialog(QDialog):
    """[6] 커스텀 캐릭터 추가 다이얼로그"""

    def __init__(self, parent_prompt_textbox: QTextEdit, parent_uc_textbox: QTextEdit,
                 custom_dict: dict, parent=None):
        super().__init__(parent)
        self.parent_prompt_textbox = parent_prompt_textbox
        self.parent_uc_textbox = parent_uc_textbox
        self.custom_dict = custom_dict

        self.setWindowTitle("커스텀 캐릭터 추가")
        self.resize(get_scaled_size(600), get_scaled_size(500))
        self.setModal(True)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)

        self.init_ui()

    def init_ui(self):
        """UI 초기화"""
        layout = QVBoxLayout(self)
        layout.setSpacing(get_scaled_size(10))
        layout.setContentsMargins(
            get_scaled_size(15), get_scaled_size(15),
            get_scaled_size(15), get_scaled_size(15)
        )

        # 캐릭터 이름 입력
        name_label = QLabel("캐릭터 이름:")
        name_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(16)}px;")
        layout.addWidget(name_label)

        self.name_edit = QLineEdit()
        self.name_edit.setStyleSheet(DARK_STYLES['compact_lineedit'])
        self.name_edit.setPlaceholderText("예: hatsune miku")
        self.name_edit.setProperty("autocomplete_ignore", True)
        layout.addWidget(self.name_edit)

        # 프롬프트 입력
        prompt_label = QLabel("캐릭터 프롬프트:")
        prompt_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(16)}px;")
        layout.addWidget(prompt_label)

        self.prompt_edit = QTextEdit()
        self.prompt_edit.setAcceptRichText(False)  # 서식 붙여넣기 차단
        self.prompt_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
        #self.prompt_edit.setProperty("autocomplete_ignore", True)
        self.prompt_edit.setMinimumHeight(get_scaled_size(120))
        # 부모 프롬프트에서 자동 입력
        if self.parent_prompt_textbox:
            self.prompt_edit.setPlainText(self.parent_prompt_textbox.toPlainText())
        layout.addWidget(self.prompt_edit)

        # Negative 프롬프트 입력
        negative_label = QLabel("Negative 프롬프트:")
        negative_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(16)}px;")
        layout.addWidget(negative_label)

        self.negative_edit = QTextEdit()
        self.negative_edit.setAcceptRichText(False)  # 서식 붙여넣기 차단
        self.negative_edit.setStyleSheet(DARK_STYLES['compact_textedit'] + f"color: {DARK_COLORS['text_secondary']};")
        #self.negative_edit.setProperty("autocomplete_ignore", True)
        self.negative_edit.setMinimumHeight(get_scaled_size(80))
        # 부모 UC에서 자동 입력
        if self.parent_uc_textbox:
            self.negative_edit.setPlainText(self.parent_uc_textbox.toPlainText())
        layout.addWidget(self.negative_edit)

        # 버튼
        button_layout = QHBoxLayout()

        self.save_btn = QPushButton("저장")
        self.save_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.save_btn.clicked.connect(self.on_save_clicked)
        button_layout.addWidget(self.save_btn)

        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)

        layout.addLayout(button_layout)

    def on_save_clicked(self):
        """저장 버튼 클릭"""
        character_name = self.name_edit.text().strip().lower()
        prompt = self.prompt_edit.toPlainText().strip()
        negative = self.negative_edit.toPlainText().strip()

        # 유효성 검사
        if not character_name:
            QMessageBox.warning(self, "경고", "캐릭터 이름을 입력해주세요.")
            return

        if not prompt:
            QMessageBox.warning(self, "경고", "프롬프트를 입력해주세요.")
            return

        # 중복 키 확인
        if character_name in self.custom_dict:
            reply = QMessageBox.question(
                self,
                "중복 확인",
                f"'{character_name}'이(가) 이미 존재합니다. 덮어쓰시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # 저장
        self.custom_dict[character_name] = {
            'character_prompt': prompt,
            'character_negative': negative
        }

        print(f"💾 커스텀 캐릭터 추가: {character_name}")
        self.accept()


class NAID4CharacterInput(QWidget):
    """단일 캐릭터 입력을 위한 위젯 클래스"""
    def __init__(self, char_id: int, remove_callback, app_context=None, parent=None):
        super().__init__(parent)
        self.char_id = char_id
        self.remove_callback = remove_callback
        self.app_context = app_context
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.active_checkbox = QCheckBox(f"C{self.char_id}")
        self.active_checkbox.setChecked(True)
        self.active_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        layout.addWidget(self.active_checkbox)

        prompt_uc_layout = QVBoxLayout()
        self.prompt_textbox = QTextEdit()
        self.prompt_textbox.setAcceptRichText(False)  # 서식 붙여넣기 차단
        self.prompt_textbox.setPlaceholderText("캐릭터 프롬프트 (예: 1girl, ...)")
        self.prompt_textbox.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.prompt_textbox.setMinimumHeight(110)
        setModernStyle(self.prompt_textbox)
        prompt_uc_layout.addWidget(self.prompt_textbox)

        self.uc_textbox = QTextEdit()
        self.uc_textbox.setAcceptRichText(False)  # 서식 붙여넣기 차단
        self.uc_textbox.setPlaceholderText("부정 프롬프트 (UC)")
        self.uc_textbox.setStyleSheet(DARK_STYLES['compact_textedit'] + "color: #9E9E9E;")
        self.uc_textbox.setMinimumHeight(55)
        self.uc_textbox.setMaximumHeight(110)
        setModernStyle(self.uc_textbox)
        prompt_uc_layout.addWidget(self.uc_textbox)
        
        layout.addLayout(prompt_uc_layout)

        # 버튼 레이아웃 (세로 배치)
        button_layout = QVBoxLayout()
        button_layout.setSpacing(4)

        # 🔤 캐릭터 검색 버튼
        search_btn = QPushButton("🔤")
        search_btn.setFixedSize(30, 30)
        search_btn.setToolTip("캐릭터 검색")
        search_btn.clicked.connect(self.open_character_search)
        button_layout.addWidget(search_btn)

        # ❌ 제거 버튼
        remove_btn = QPushButton("❌")
        remove_btn.setFixedSize(30, 30)
        remove_btn.setToolTip("캐릭터 제거")
        remove_btn.clicked.connect(lambda: self.remove_callback(self))
        button_layout.addWidget(remove_btn)

        # 버튼 레이아웃 아래쪽 여백 채우기
        button_layout.addStretch()

        layout.addLayout(button_layout)

    def open_character_search(self):
        """캐릭터 검색 다이얼로그 열기"""
        dialog = CharacterSearchDialog(
            parent_prompt_textbox=self.prompt_textbox,
            parent_uc_textbox=self.uc_textbox,
            parent=self
        )
        dialog.exec()


class CharacterModule(BaseMiddleModule, ModeAwareModule):
    def __init__(self):
        BaseMiddleModule.__init__(self)
        ModeAwareModule.__init__(self)
        
        # 🆕 ModeAwareModule 필수 속성들
        self.settings_base_filename = "CharacterModule"
        self.current_mode = "NAI"  # 기본값
        
        # 🆕 호환성 설정 (NAI만 호환, WEBUI 비호환)
        self.NAI_compatibility = True
        self.WEBUI_compatibility = False
        self.COMFYUI_compatibility = False
        
        # 기존 속성들
        self.scroll_layout: QVBoxLayout = None
        self.wildcard_processor: WildcardProcessor = None
        self.character_widgets: List[NAID4CharacterInput] = []  # 🆕 누락된 속성 추가
        
        # UI 위젯 인스턴스 변수
        self.activate_checkbox: QCheckBox = None
        self.reroll_on_generate_checkbox: QCheckBox = None
        self.processed_prompt_display: QTextEdit = None
        self.last_processed_data: dict = {'characters': [], 'uc': []}
        self.modifiable_clone: dict = {'characters': [], 'uc': []}

    def get_title(self) -> str:
        return "👤 NAID4 캐릭터"

    def get_order(self) -> int:
        return 3
    
    def get_module_name(self) -> str:
        """ModeAwareModule 인터페이스 구현"""
        return self.get_title()
    
    def initialize_with_context(self, context: AppContext):
        """기존 메서드 유지"""
        self.app_context = context  # 🆕 app_context 설정
        self.wildcard_processor = WildcardProcessor(context.main_window.wildcard_manager)
        context.subscribe("random_prompt_triggered", self.on_random_prompt_triggered)
    
    def on_initialize(self):
        if hasattr(self, 'app_context') and self.app_context:
            # 모드 변경 이벤트는 이미 ModeAwareModuleManager에서 자동 구독됨
            print(f"✅ {self.get_title()}: AppContext 연결 완료")
            
            # 초기 가시성 설정
            current_mode = self.app_context.get_api_mode()
            if self.widget:
                self.update_visibility_for_mode(current_mode)

    def collect_current_settings(self) -> Dict[str, Any]:
        """현재 UI 상태에서 설정 수집"""
        if not self.activate_checkbox:
            return {}
        
        char_data = []
        for widget in self.character_widgets:
            char_data.append({
                "prompt": widget.prompt_textbox.toPlainText(),
                "uc": widget.uc_textbox.toPlainText(),
                "is_enabled": widget.active_checkbox.isChecked()
            })
        
        return {
            "is_active": self.activate_checkbox.isChecked(),
            "reroll_on_generate": self.reroll_on_generate_checkbox.isChecked() if self.reroll_on_generate_checkbox else False,
            "character_frames": char_data
        }
    
    def apply_settings(self, settings: Dict[str, Any]):
        """설정을 UI에 적용"""
        if not self.activate_checkbox:
            return
            
        self.activate_checkbox.setChecked(settings.get("is_active", False))
        
        if self.reroll_on_generate_checkbox:
            self.reroll_on_generate_checkbox.setChecked(settings.get("reroll_on_generate", False))
        
        # 기존 캐릭터 위젯들 제거
        for widget in self.character_widgets[:]:
            self._remove_character_widget_internal(widget)
        
        # 캐릭터 프레임 복원
        character_frames_data = settings.get("character_frames", [])
        if not character_frames_data:
            self.add_character_widget()  # 기본 위젯 하나 추가
        else:
            for frame_data in character_frames_data:
                self.add_character_widget(
                    prompt_text=frame_data.get("prompt", ""),
                    uc_text=frame_data.get("uc", ""),
                    is_enabled=frame_data.get("is_enabled", True)
                )

    def create_widget(self, parent: QWidget) -> QWidget:
        widget = QWidget(parent)
        main_layout = QVBoxLayout(widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # --- 상단 옵션 영역 ---
        options_frame = QFrame(widget)
        options_layout = QGridLayout(options_frame)
        options_layout.setContentsMargins(0, 0, 0, 0)

        # 체크박스 및 버튼 위젯 생성
        self.activate_checkbox = QCheckBox("캐릭터 프롬프트 옵션을 활성화 합니다. (NAID4 이상)")
        self.activate_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        
        self.reroll_on_generate_checkbox = QCheckBox("[랜덤]대신 [생성]시에 와일드카드를 개봉합니다.")
        self.reroll_on_generate_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        
        self.reroll_button = QPushButton("🔄️ 미리보기 갱신") 
        self.reroll_button.setStyleSheet(DARK_STYLES['secondary_button'])
        self.reroll_button.setFixedWidth(200)
        self.reroll_button.clicked.connect(self.process_and_update_view)

        options_layout.addWidget(self.activate_checkbox, 0, 0, 1, 2)
        options_layout.addWidget(self.reroll_on_generate_checkbox, 1, 0)
        options_layout.addWidget(self.reroll_button, 1, 1)

        main_layout.addWidget(options_frame)

        # 캐릭터 위젯 컨테이너
        char_widgets_container = QWidget(widget)
        self.scroll_layout = QVBoxLayout(char_widgets_container)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_layout.setContentsMargins(0, 5, 0, 5)
        
        add_button = QPushButton("+ 캐릭터 추가")
        add_button.setStyleSheet(DARK_STYLES['secondary_button'])
        add_button.clicked.connect(lambda: self.add_character_widget())
        self.scroll_layout.addWidget(add_button)
        
        main_layout.addWidget(char_widgets_container)

        processed_label = QLabel("최종 적용될 캐릭터 프롬프트 (와일드카드/Hook 처리 후)")
        processed_label.setStyleSheet(DARK_STYLES['label_style'])
        main_layout.addWidget(processed_label)

        self.processed_prompt_display = QTextEdit()
        self.processed_prompt_display.setAcceptRichText(False)  # 서식 붙여넣기 차단
        self.processed_prompt_display.setReadOnly(True)
        self.processed_prompt_display.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.processed_prompt_display.setFixedHeight(240)
        setModernStyle(self.processed_prompt_display)
        main_layout.addWidget(self.processed_prompt_display)

        # 🆕 생성된 위젯 저장 (가시성 제어용)
        self.widget = widget
        
        # 🆕 UI 생성 완료 후 즉시 가시성 설정
        if hasattr(self, 'app_context') and self.app_context:
            current_mode = self.app_context.get_api_mode()
            should_be_visible = self.is_compatible_with_mode(current_mode)
            widget.setVisible(should_be_visible)
            print(f"🔍 CharacterModule 초기 가시성: {should_be_visible} (모드: {current_mode})")
        
        # 모드별 설정 로드
        self.load_mode_settings()
        
        # 기본 캐릭터 위젯 추가
        if not self.character_widgets:
            self.add_character_widget()

        return widget

    def get_or_create_context(self) -> PromptContext:
        """순차 와일드카드 상태를 유지하기 위해 공유 컨텍스트를 가져오거나 생성합니다."""
        if hasattr(self, 'app_context') and self.app_context and self.app_context.current_prompt_context:
            # 메인 애플리케이션의 공유 컨텍스트가 있으면 사용
            return self.app_context.current_prompt_context
        else:
            # 없으면 모듈 전용 컨텍스트를 생성/재사용 (순차 카운터 보존)
            if not hasattr(self, '_module_context') or self._module_context is None:
                self._module_context = PromptContext(source_row=pd.Series(), settings={})
            return self._module_context

    def process_and_update_view(self) -> PromptContext:
        """와일드카드를 처리하고 UI를 업데이트하는 핵심 메소드"""
        if not self.activate_checkbox or not self.activate_checkbox.isChecked():
            self.processed_prompt_display.clear()
            self.last_processed_data = {'characters': [], 'uc': []}
            self.modifiable_clone = {'characters': [], 'uc': []} # ⬅️ 비활성화 시 복제본도 초기화
            return None

        # 🔧 [수정] 공유 컨텍스트 사용으로 순차 와일드카드 상태 보존
        context = self.get_or_create_context()
        processed_prompts, processed_ucs = [], []

        for widget in self.character_widgets:
            if widget.active_checkbox.isChecked():
                prompt_tags = [t.strip() for t in widget.prompt_textbox.toPlainText().split(',')]
                uc_tags = [t.strip() for t in widget.uc_textbox.toPlainText().split(',')]
                
                processed_prompts.append(', '.join(self.wildcard_processor.expand_tags(prompt_tags, context)))
                processed_ucs.append(', '.join(self.wildcard_processor.expand_tags(uc_tags, context)))
        
        self.last_processed_data = {'characters': processed_prompts, 'uc': processed_ucs}
        self.modifiable_clone = copy.deepcopy(self.last_processed_data)
        self.update_processed_display(processed_prompts, processed_ucs)
        return context

    def on_random_prompt_triggered(self):
        """'랜덤 프롬프트' 버튼 클릭 시 호출되는 이벤트 핸들러"""
        if self.activate_checkbox.isChecked() and not self.reroll_on_generate_checkbox.isChecked():
            print("🔄️ 랜덤 프롬프트 요청으로 캐릭터 와일드카드를 갱신합니다.")
            self.process_and_update_view()

    def get_parameters(self) -> dict:
        """모듈의 파라미터를 반환합니다."""
        if not self.activate_checkbox or not self.activate_checkbox.isChecked():
            return {"characters": None}

        return self.modifiable_clone
    
    def hooker_update_prompt(self):
        # ⬇️ Hooker에 의해 수정된 최종 결과를 UI에 업데이트하는 로직 추가
        if self.modifiable_clone:
            final_prompts = self.modifiable_clone.get('characters', [])
            final_ucs = self.modifiable_clone.get('uc', [])
            self.update_processed_display(final_prompts, final_ucs)

    def update_processed_display(self, prompts: List[str], ucs: List[str]):
        """처리된 프롬프트를 하단 텍스트 박스에 표시합니다."""
        display_text = []
        for i, (prompt, uc) in enumerate(zip(prompts, ucs)):
            display_text.append(f"C{i+1}: {prompt}")
            display_text.append(f"UC{i+1}: {uc}\n")
        self.processed_prompt_display.setText("\n".join(display_text))

    def add_character_widget(self, prompt_text: str = "", uc_text: str = "", is_enabled: bool = True):
        char_id = len(self.character_widgets) + 1
        char_widget = NAID4CharacterInput(char_id, self.remove_character_widget, self.app_context, self.scroll_layout.parentWidget())
        char_widget.prompt_textbox.setText(prompt_text)
        char_widget.uc_textbox.setText(uc_text)
        char_widget.active_checkbox.setChecked(is_enabled)
        
        self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, char_widget)
        self.character_widgets.append(char_widget)
        self.update_widget_ids()

    def _remove_character_widget_internal(self, widget_to_remove):
        """내부용 위젯 제거 메서드 (최소 개수 제한 없음)"""
        if widget_to_remove in self.character_widgets:
            self.character_widgets.remove(widget_to_remove)
            widget_to_remove.deleteLater()
            self.update_widget_ids()

    def remove_character_widget(self, widget_to_remove):
        if len(self.character_widgets) > 1:
            self.character_widgets.remove(widget_to_remove)
            widget_to_remove.deleteLater()
            self.update_widget_ids()

    def update_widget_ids(self):
        for i, widget in enumerate(self.character_widgets):
            widget.char_id = i + 1
            widget.active_checkbox.setText(f"C{widget.char_id}")
    
    def assign_c1(self, character_prompt: str, character_uc: str):
        """
        C1 위젯에 캐릭터 프롬프트와 UC를 할당하고 활성화합니다.
        
        Args:
            character_prompt: 캐릭터 프롬프트 텍스트
            character_uc: 캐릭터 UC 텍스트
        """
        # C1 위젯이 없으면 생성
        if not self.character_widgets:
            self.add_character_widget()
        
        # C1 위젯 (첫 번째 위젯)에 접근
        c1_widget = self.character_widgets[0]
        
        # 프롬프트와 UC 설정
        c1_widget.prompt_textbox.setPlainText(character_prompt)
        c1_widget.uc_textbox.setPlainText(character_uc)
        
        # 모든 캐릭터 위젯의 체크박스를 False로 설정
        for widget in self.character_widgets:
            widget.active_checkbox.setChecked(False)
        
        # C1만 True로 설정
        c1_widget.active_checkbox.setChecked(True)
        
        # CharacterModule 전체 활성화
        if self.activate_checkbox:
            self.activate_checkbox.setChecked(True)
        
        # 미리보기 갱신
        self.process_and_update_view()