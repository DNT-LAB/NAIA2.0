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
from core.character_settings import (
    loaded_character_module_is_active,
    loaded_character_module_reroll_on_generate,
)
from core.wildcard_processor import WildcardProcessor
from ui.character_asset_storage_window import CharacterAssetStorageWindow
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
                tag_list = tags.split(', ')
                tag_list.insert(0, keyword)
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

        # TODO(web-dialog): 원래 캐릭터 사전 편집 dialog.exec() — Web Shell 패널/모달로 재구현 필요.
        # 현재는 dialog 호출 차단 — 사용자 행동 없이 종료.
        print("[Dialog/SKIPPED] 캐릭터 사전 편집 dialog 차단 — Web Shell 재구현 예정")
        dialog.deleteLater()
        return
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


class CharacterPositionGridDialog(QDialog):
    """5x5 그리드 위치 선택 다이얼로그"""

    position_selected = pyqtSignal(int, str)  # (char_index, position)

    def __init__(self, char_index: int, current_position: str, used_positions: List[str] = None, parent=None):
        super().__init__(parent)
        self.char_index = char_index
        self.current_position = current_position
        self.used_positions = used_positions or []  # 이미 사용 중인 위치들

        self.setWindowTitle(f"캐릭터 {char_index+1} 위치 선택")
        self.setFixedSize(get_scaled_size(350), get_scaled_size(400))
        self.setModal(True)

        # 다크 테마
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)

        self.init_ui()

    def init_ui(self):
        """UI 초기화"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(get_scaled_size(10))
        main_layout.setContentsMargins(
            get_scaled_size(15), get_scaled_size(15),
            get_scaled_size(15), get_scaled_size(15)
        )

        # 헤더
        header_label = QLabel("화면 위치를 선택하세요")
        header_label.setStyleSheet(f"font-size: {get_scaled_font_size(14)}px; color: {DARK_COLORS['text_primary']};")
        header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(header_label)

        # 5x5 그리드
        grid_frame = QFrame()
        grid_layout = QGridLayout(grid_frame)
        grid_layout.setSpacing(get_scaled_size(5))
        grid_layout.setContentsMargins(get_scaled_size(10), get_scaled_size(10),
                                      get_scaled_size(10), get_scaled_size(10))

        self.grid_buttons = {}

        for col_idx, col_label in enumerate(['A', 'B', 'C', 'D', 'E']):
            for row_idx in range(5):
                row_num = row_idx + 1
                pos = f"{col_label}{row_num}"

                button = QPushButton(pos)
                button.setFixedSize(get_scaled_size(50), get_scaled_size(50))

                # 이미 다른 캐릭터가 사용 중인 위치인지 확인
                is_used = pos in self.used_positions and pos != self.current_position

                if is_used:
                    # 사용 중인 위치: 빨간색 + 비활성화
                    button.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {DARK_COLORS['error']};
                            color: {DARK_COLORS['text_disabled']};
                            font-size: {get_scaled_font_size(12)}px;
                            border: 2px solid {DARK_COLORS['border']};
                            border-radius: 5px;
                        }}
                    """)
                    button.setEnabled(False)
                    button.setToolTip("다른 캐릭터가 사용 중입니다")
                elif pos == self.current_position:
                    # 현재 위치: 파란색 하이라이트
                    button.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {DARK_COLORS['accent_blue']};
                            color: white;
                            font-weight: bold;
                            font-size: {get_scaled_font_size(12)}px;
                            border: 2px solid {DARK_COLORS['accent_blue_hover']};
                            border-radius: 5px;
                        }}
                        QPushButton:hover {{
                            background-color: {DARK_COLORS['accent_blue_hover']};
                        }}
                    """)
                else:
                    # 사용 가능한 위치
                    button.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {DARK_COLORS['bg_secondary']};
                            color: {DARK_COLORS['text_primary']};
                            font-size: {get_scaled_font_size(12)}px;
                            border: 1px solid {DARK_COLORS['border']};
                            border-radius: 5px;
                        }}
                        QPushButton:hover {{
                            background-color: {DARK_COLORS['bg_hover']};
                            border: 1px solid {DARK_COLORS['accent_blue']};
                        }}
                    """)

                button.clicked.connect(lambda checked, p=pos: self._select_position(p))

                grid_layout.addWidget(button, row_idx, col_idx)
                self.grid_buttons[pos] = button

        main_layout.addWidget(grid_frame)

        # 취소 버튼
        cancel_button = QPushButton("✗ 취소")
        cancel_button.setStyleSheet(DARK_STYLES['secondary_button'])
        cancel_button.setFixedWidth(get_scaled_size(100))
        cancel_button.clicked.connect(self.reject)
        main_layout.addWidget(cancel_button, alignment=Qt.AlignmentFlag.AlignCenter)

    def _select_position(self, position: str):
        """위치 선택"""
        self.position_selected.emit(self.char_index, position)
        self.accept()


class CharacterPositionManagerDialog(QDialog):
    """캐릭터 위치 관리 다이얼로그"""

    positions_updated = pyqtSignal(list)  # List[str]

    def __init__(self, character_widgets: List, character_positions: List[str], parent_module, parent=None):
        super().__init__(parent)
        self.character_widgets = character_widgets
        self.character_positions = character_positions  # 🆕 복사본이 아닌 원본 참조 (실시간 업데이트)
        self.parent_module = parent_module  # 🆕 부모 모듈 참조

        self.setWindowTitle("캐릭터 위치 관리")
        self.setFixedSize(get_scaled_size(600), get_scaled_size(500))
        self.setModal(False)  # 🆕 Non-modal로 변경 (백그라운드에서 메인 UI 확인 가능)

        # 다크 테마 적용
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)

        self.init_ui()

    def init_ui(self):
        """UI 초기화"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(get_scaled_size(10))
        main_layout.setContentsMargins(
            get_scaled_size(15), get_scaled_size(15),
            get_scaled_size(15), get_scaled_size(15)
        )

        # --- 헤더 ---
        header_label = QLabel("각 캐릭터의 화면 위치를 설정하세요")
        header_label.setStyleSheet(f"font-size: {get_scaled_font_size(16)}px; color: {DARK_COLORS['text_primary']}; font-weight: bold;")
        main_layout.addWidget(header_label)

        # --- 캐릭터별 위치 버튼 ---
        char_scroll = QScrollArea()
        char_scroll.setWidgetResizable(True)
        char_scroll.setStyleSheet(f"""
            QScrollArea {{
                border: 1px solid {DARK_COLORS['border']};
                background-color: {DARK_COLORS['bg_secondary']};
            }}
        """)

        char_container = QWidget()
        char_layout = QVBoxLayout(char_container)
        char_layout.setSpacing(get_scaled_size(5))
        char_layout.setContentsMargins(get_scaled_size(5), get_scaled_size(5),
                                       get_scaled_size(5), get_scaled_size(5))

        self.position_buttons = []

        for idx, widget in enumerate(self.character_widgets):
            if not widget.active_checkbox.isChecked():
                continue

            # 캐릭터 행 프레임
            char_frame = QFrame()
            char_frame.setStyleSheet(f"""
                QFrame {{
                    background-color: {DARK_COLORS['bg_primary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: 5px;
                    padding: 5px;
                }}
            """)
            char_row_layout = QHBoxLayout(char_frame)
            char_row_layout.setContentsMargins(get_scaled_size(10), get_scaled_size(5),
                                              get_scaled_size(10), get_scaled_size(5))

            # 캐릭터 번호 + 이름 (프롬프트 첫 태그)
            prompt_text = widget.prompt_textbox.toPlainText()
            char_name = prompt_text.split(',')[0].strip() if prompt_text else f"캐릭터 {idx+1}"

            label = QLabel(f"[{idx+1}] {char_name[:30]}")
            label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(14)}px;")
            label.setFixedWidth(get_scaled_size(250))
            char_row_layout.addWidget(label)

            # 위치 버튼
            current_pos = self.character_positions[idx] if idx < len(self.character_positions) else "C3"
            pos_button = QPushButton(f"위치: {current_pos}")
            pos_button.setStyleSheet(DARK_STYLES['secondary_button'])
            pos_button.setFixedWidth(get_scaled_size(100))
            pos_button.clicked.connect(lambda checked, i=idx: self._open_grid_selector(i))
            char_row_layout.addWidget(pos_button)

            char_row_layout.addStretch()

            self.position_buttons.append((idx, pos_button))
            char_layout.addWidget(char_frame)

        char_layout.addStretch()
        char_scroll.setWidget(char_container)
        main_layout.addWidget(char_scroll)

        # --- 무작위 배치 옵션 ---
        random_frame = QFrame()
        random_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 5px;
                padding: 5px;
            }}
        """)
        random_layout = QHBoxLayout(random_frame)
        random_layout.setContentsMargins(get_scaled_size(10), get_scaled_size(5),
                                        get_scaled_size(10), get_scaled_size(5))

        random_button = QPushButton("🎲 무작위 배치")
        random_button.setStyleSheet(DARK_STYLES['primary_button'])
        random_button.setFixedWidth(get_scaled_size(170))
        random_button.clicked.connect(self._randomize_positions)
        random_layout.addWidget(random_button)

        self.exclude_center_checkbox = QCheckBox("가운데(C3) 제외")
        self.exclude_center_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        random_layout.addWidget(self.exclude_center_checkbox)

        random_layout.addStretch()
        main_layout.addWidget(random_frame)

        # 🆕 실시간 피드백: 확인/취소 버튼 제거
        # 위치 변경 시 즉시 부모 모듈에 반영됨

    def _open_grid_selector(self, char_index: int):
        """그리드 선택 다이얼로그 열기"""
        current_pos = self.character_positions[char_index] if char_index < len(self.character_positions) else "C3"

        # 다른 활성 캐릭터들이 사용 중인 위치 수집
        used_positions = []
        for idx, widget in enumerate(self.character_widgets):
            if idx != char_index and widget.active_checkbox.isChecked():
                if idx < len(self.character_positions):
                    pos = self.character_positions[idx]
                    if pos and len(pos) >= 2:
                        used_positions.append(pos)

        # TODO(web-dialog): 원래 CharacterPositionGridDialog.exec() — 캐릭터 위치 5x5 그리드 선택 모달.
        # Web Shell 패널로 재구현 필요. 현재는 차단.
        print(f"[Dialog/SKIPPED] CharacterPositionGridDialog 차단 (char_index={char_index}) — Web Shell 재구현 예정")

    def _on_position_selected(self, char_index: int, position: str):
        """그리드에서 위치 선택 시 (실시간 피드백)"""
        # 리스트 크기 확장 (필요 시)
        while len(self.character_positions) <= char_index:
            self.character_positions.append("C3")

        self.character_positions[char_index] = position

        # 버튼 텍스트 업데이트
        for idx, button in self.position_buttons:
            if idx == char_index:
                button.setText(f"위치: {position}")
                break

        # 🆕 실시간 피드백: 부모 모듈의 시각화 즉시 업데이트
        if hasattr(self.parent_module, '_update_position_viewer'):
            self.parent_module._update_position_viewer()
        print(f"📍 C{char_index+1} 위치 변경: {position}")

    def _randomize_positions(self):
        """무작위 위치 배치 (겹침 방지)"""
        import random

        # 가능한 위치 리스트
        all_positions = [f"{col}{row}" for col in "ABCDE" for row in "12345"]

        # 가운데 제외 옵션
        if self.exclude_center_checkbox.isChecked():
            all_positions = [p for p in all_positions if p != "C3"]

        # 활성화된 캐릭터 수만큼 샘플링 (중복 없이)
        active_indices = [idx for idx, widget in enumerate(self.character_widgets)
                          if widget.active_checkbox.isChecked()]

        if len(active_indices) > len(all_positions):
            QMessageBox.warning(self, "경고",
                              f"활성화된 캐릭터 수({len(active_indices)})가 가능한 위치({len(all_positions)})보다 많습니다.")
            return

        # 중복 없이 위치 샘플링
        random_positions = random.sample(all_positions, len(active_indices))

        # 위치 업데이트
        for i, idx in enumerate(active_indices):
            while len(self.character_positions) <= idx:
                self.character_positions.append("C3")
            self.character_positions[idx] = random_positions[i]

            # 버튼 텍스트 업데이트
            for btn_idx, button in self.position_buttons:
                if btn_idx == idx:
                    button.setText(f"위치: {random_positions[i]}")
                    break

        # 🆕 실시간 피드백: 부모 모듈의 시각화 즉시 업데이트
        if hasattr(self.parent_module, '_update_position_viewer'):
            self.parent_module._update_position_viewer()
        print(f"🎲 무작위 위치 배치 완료: {random_positions}")


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
        """캐릭터 검색 다이얼로그 열기.
        TODO(web-dialog): 원래 CharacterSearchDialog.exec() — Web Shell 패널로 재구현 필요."""
        print("[Dialog/SKIPPED] CharacterSearchDialog 차단 — Web Shell 재구현 예정")


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
        self.c1_asset_button: QPushButton = None
        self.character_asset_storage_button: QPushButton = None
        self.character_asset_storage_window = None
        self.processed_prompt_display: QTextEdit = None
        self.last_processed_data: dict = {'characters': [], 'uc': []}
        self.modifiable_clone: dict = {'characters': [], 'uc': []}

        # 🆕 캐릭터 위치 관련 속성
        self.enable_position_checkbox: QCheckBox = None
        self.position_button: QPushButton = None
        self.position_viewer: QLabel = None
        self.random_position_button: QPushButton = None  # 🆕 위치 랜덤 버튼
        self.auto_reroll_checkbox: QCheckBox = None  # 🆕 생성 시 자동 리롤
        self.character_positions: List[str] = ["C3"] * 6  # 기본 중앙 (최대 6명)
        self.exclude_center_on_random: bool = True  # 🆕 가운데 비우기 기본 활성화

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
            slot_state = self._slot_state_for_widget(widget)
            char_data.append({
                "prompt": widget.prompt_textbox.toPlainText(),
                "uc": widget.uc_textbox.toPlainText(),
                "is_enabled": slot_state == "active",
                "slot_state": slot_state,
                "return_slot_state": str(getattr(widget, "return_slot_state", "") or ""),
                "custom_name": str(getattr(widget, "custom_name", "") or ""),
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
                is_enabled = frame_data.get("is_enabled", True)
                slot_state = self._slot_state_from_settings(frame_data, is_enabled)
                self.add_character_widget(
                    prompt_text=frame_data.get("prompt", ""),
                    uc_text=frame_data.get("uc", ""),
                    is_enabled=slot_state == "active",
                    slot_state=slot_state,
                    return_slot_state=frame_data.get("return_slot_state", ""),
                    custom_name=frame_data.get("custom_name", frame_data.get("slot_name", "")),
                )

    def _normalize_slot_state(self, slot_state: str = None, is_enabled: bool = False) -> str:
        state = str(slot_state or "").strip().lower()
        if state in {"active", "inactive", "cold"}:
            return state
        return "active" if is_enabled else "inactive"

    def _slot_state_from_settings(self, frame_data: Dict[str, Any], is_enabled: bool) -> str:
        if "slot_state" in frame_data:
            return self._normalize_slot_state(frame_data.get("slot_state"), is_enabled)
        has_content = bool(str(frame_data.get("prompt", "")).strip() or str(frame_data.get("uc", "")).strip())
        if is_enabled:
            return "active"
        return "cold" if has_content else "inactive"

    def _slot_state_for_widget(self, widget) -> str:
        checkbox = getattr(widget, "active_checkbox", None)
        if checkbox is not None and checkbox.isChecked():
            return "active"
        state = self._normalize_slot_state(getattr(widget, "slot_state", None), False)
        return "cold" if state == "cold" else "inactive"

    def _on_character_active_changed(self, widget, state):
        checkbox = getattr(widget, "active_checkbox", None)
        widget.slot_state = "active" if checkbox and checkbox.isChecked() else "inactive"
        self._check_and_update_position_safety()

    def set_character_slot_state(self, index: int, slot_state: str) -> bool:
        if index < 0 or index >= len(self.character_widgets):
            return False
        widget = self.character_widgets[index]
        checkbox = getattr(widget, "active_checkbox", None)
        current_work_state = "active" if checkbox and checkbox.isChecked() else "inactive"
        requested_state = str(slot_state or "").strip().lower()
        if requested_state == "restore":
            requested_state = str(getattr(widget, "return_slot_state", "") or "inactive").strip().lower()
        next_state = self._normalize_slot_state(requested_state, current_work_state == "active")
        if next_state == "cold":
            widget.return_slot_state = current_work_state
        else:
            widget.return_slot_state = next_state
        widget.slot_state = next_state
        if checkbox:
            checkbox.blockSignals(True)
            checkbox.setChecked(next_state == "active")
            checkbox.blockSignals(False)
        self._check_and_update_position_safety()
        return True

    def set_character_custom_name(self, index: int, custom_name: str) -> bool:
        if index < 0 or index >= len(self.character_widgets):
            return False
        self.character_widgets[index].custom_name = str(custom_name or "").strip()
        return True

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
        self.c1_asset_button = QPushButton("캐릭터 에셋 생성")
        self.c1_asset_button.setStyleSheet(DARK_STYLES['primary_button'])
        self.c1_asset_button.setFixedWidth(220)
        self.c1_asset_button.setToolTip("선택한 첫 번째 캐릭터로 에셋 창을 엽니다.")
        self.c1_asset_button.clicked.connect(self.open_c1_asset_generation_window)
        self.character_asset_storage_button = QPushButton("에셋 스토리지")
        self.character_asset_storage_button.setStyleSheet(DARK_STYLES['secondary_button'])
        self.character_asset_storage_button.setFixedSize(get_scaled_size(150), get_scaled_size(54))
        self.character_asset_storage_button.setToolTip("저장된 캐릭터 에셋 보관함을 엽니다.")
        self.character_asset_storage_button.clicked.connect(self.open_character_asset_storage_window)

        action_row_widget = QWidget(options_frame)
        action_row_layout = QHBoxLayout(action_row_widget)
        action_row_layout.setContentsMargins(0, 0, 0, 0)
        action_row_layout.setSpacing(get_scaled_size(8))
        action_row_layout.addWidget(self.reroll_on_generate_checkbox)
        action_row_layout.addWidget(self.reroll_button)
        action_row_layout.addWidget(self.c1_asset_button)

        options_layout.addWidget(self.activate_checkbox, 0, 0, 1, 3)
        options_layout.addWidget(action_row_widget, 1, 0, 1, 3, Qt.AlignmentFlag.AlignLeft)

        # 🆕 캐릭터 위치 관리 UI
        self.enable_position_checkbox = QCheckBox("(2인이상체크) 캐릭터 포지션을 활성화 합니다")
        self.enable_position_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.enable_position_checkbox.setChecked(False)
        self.enable_position_checkbox.stateChanged.connect(self._on_position_toggle)

        self.position_button = QPushButton("📍")
        self.position_button.setStyleSheet(DARK_STYLES['secondary_button'])
        self.position_button.setFixedWidth(get_scaled_size(55))  # 🆕 120 → 160 (40 증가)
        self.position_button.clicked.connect(self._open_position_dialog)
        self.position_button.setEnabled(False)  # 초기 비활성화

        # 위치 시각화 라벨 (25x25px 이미지를 50x50px로 표시)
        from PIL import Image
        from PyQt6.QtGui import QPixmap, QImage
        temp_image = Image.new('RGB', (25, 25), DARK_COLORS['bg_secondary'])
        # PIL Image → QImage → QPixmap 변환
        temp_image_bytes = temp_image.tobytes("raw", "RGB")
        q_image = QImage(temp_image_bytes, 25, 25, 25 * 3, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(q_image).scaled(
            get_scaled_size(50), get_scaled_size(50),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.position_viewer = QLabel()
        self.position_viewer.setPixmap(pixmap)
        self.position_viewer.setFixedSize(get_scaled_size(60), get_scaled_size(60))
        self.position_viewer.setStyleSheet(f"""
            QLabel {{
                border: 1px solid {DARK_COLORS['border']};
                background-color: {DARK_COLORS['bg_secondary']};
            }}
        """)

        # 🆕 위치 랜덤 버튼
        self.random_position_button = QPushButton("🔄")
        self.random_position_button.setStyleSheet(DARK_STYLES['secondary_button'])
        self.random_position_button.setFixedWidth(get_scaled_size(55))
        self.random_position_button.setToolTip("위치 무작위 배치 (가운데 제외)")
        self.random_position_button.clicked.connect(self._on_random_position_clicked)
        self.random_position_button.setEnabled(False)  # 초기 비활성화

        # 🆕 생성 시 자동 리롤 체크박스
        self.auto_reroll_checkbox = QCheckBox("A")
        self.auto_reroll_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.auto_reroll_checkbox.setToolTip("생성 시 위치 자동 리롤")
        self.auto_reroll_checkbox.setChecked(False)

        # 버튼과 시각화 이미지를 같은 셀에 배치 (UI 밀림 방지)
        position_control_widget = QWidget()
        position_control_layout = QHBoxLayout(position_control_widget)
        position_control_layout.setContentsMargins(0, 0, 0, 0)
        position_control_layout.setSpacing(get_scaled_size(5))
        position_control_layout.addWidget(self.position_button)
        position_control_layout.addWidget(self.position_viewer)
        position_control_layout.addWidget(self.random_position_button)
        position_control_layout.addWidget(self.auto_reroll_checkbox)
        position_control_layout.addStretch()

        options_layout.addWidget(self.enable_position_checkbox, 2, 0)
        options_layout.addWidget(position_control_widget, 2, 1)
        options_layout.addWidget(self.character_asset_storage_button, 2, 2, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

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
        event_stream = getattr(self.app_context, "event_stream_runtime", None)
        if (
            event_stream
            and event_stream.should_freeze_character_prompts()
            and event_stream.has_freeze_snapshot()
        ):
            frozen_params = event_stream.get_frozen_character_params()
            if frozen_params is not None:
                frozen_copy = copy.deepcopy(frozen_params)
                self.last_processed_data = {
                    'characters': frozen_copy.get('characters') or [],
                    'uc': frozen_copy.get('uc') or [],
                }
                self.modifiable_clone = copy.deepcopy(self.last_processed_data)
                self.update_processed_display(
                    self.last_processed_data['characters'],
                    self.last_processed_data['uc'],
                )
                return self.get_or_create_context()

        if not loaded_character_module_is_active(self):
            if self.processed_prompt_display:
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
        event_stream = getattr(self.app_context, "event_stream_runtime", None)
        if event_stream and event_stream.should_freeze_random_prompt_side_effects():
            print("🔒 Event Stream: 랜덤 프롬프트 캐릭터 리롤을 동결합니다.")
            return
        if (
            loaded_character_module_is_active(self)
            and not loaded_character_module_reroll_on_generate(self)
        ):
            print("🔄️ 랜덤 프롬프트 요청으로 캐릭터 와일드카드를 갱신합니다.")
            self.process_and_update_view()

    def get_parameters(self) -> dict:
        """모듈의 파라미터를 반환합니다."""
        event_stream = getattr(self.app_context, "event_stream_runtime", None)
        if event_stream and event_stream.should_freeze_character_prompts():
            frozen_params = event_stream.get_frozen_character_params()
            if frozen_params is not None:
                return frozen_params

        if not loaded_character_module_is_active(self):
            return {"characters": None}

        # 기본 파라미터
        params = self.modifiable_clone.copy()

        # 🆕 캐릭터 위치 좌표 매핑
        if self.enable_position_checkbox and self.enable_position_checkbox.isChecked():
            # A: 생성 시 자동 리롤 체크되어 있으면 먼저 위치 리롤
            if self.auto_reroll_checkbox and self.auto_reroll_checkbox.isChecked():
                self._on_random_position_clicked()

            # 좌표 매핑 테이블
            x_mapping = {'A': 0.1, 'B': 0.3, 'C': 0.5, 'D': 0.7, 'E': 0.9}
            y_mapping = {'1': 0.1, '2': 0.3, '3': 0.5, '4': 0.7, '5': 0.9}

            # 활성화된 캐릭터들의 위치만 변환
            character_coords = []
            for idx, widget in enumerate(self.character_widgets):
                if widget.active_checkbox.isChecked():
                    if idx < len(self.character_positions):
                        pos = self.character_positions[idx]
                        if pos and len(pos) >= 2:
                            x = x_mapping.get(pos[0], 0.5)
                            y = y_mapping.get(pos[1], 0.5)
                            character_coords.append({'x': x, 'y': y})
                        else:
                            character_coords.append({'x': 0.5, 'y': 0.5})  # 기본값
                    else:
                        character_coords.append({'x': 0.5, 'y': 0.5})  # 기본값

            params['character_positions'] = character_coords
            print(f"📍 캐릭터 위치 좌표: {character_coords}")

        return params
    
    def sync_external_prompt_edits(self):
        """외부 모듈이 수정한 캐릭터 prompt/UC 결과를 UI에 반영한다."""
        if self.modifiable_clone:
            final_prompts = self.modifiable_clone.get('characters', [])
            final_ucs = self.modifiable_clone.get('uc', [])
            self.update_processed_display(final_prompts, final_ucs)

    def get_character_modifiable_clone(self) -> dict:
        """외부 모듈(Conditional Prompt v2 등)이 캐릭터 prompt/UC에
        read/write 접근하는 공식 엔트리.

        Returns:
            {'characters': list[str], 'uc': list[str]} 원본 dict 참조.
            수정 후에는 `sync_external_prompt_edits()`를 호출하여 UI를 동기화해야 함.
            NAID4 모드가 아니거나 모듈이 비활성화되면 빈 구조 반환.
        """
        if not isinstance(self.modifiable_clone, dict):
            return {'characters': [], 'uc': []}
        # characters/uc 키 보장
        self.modifiable_clone.setdefault('characters', [])
        self.modifiable_clone.setdefault('uc', [])
        return self.modifiable_clone

    def set_character_active(self, index: int, active: bool) -> bool:
        """외부 모듈(Conditional Prompt v2 등)에서 캐릭터 N의 active_checkbox 제어.

        Args:
            index: 0-based 인덱스 (DSL의 1-based를 호출자가 변환 후 전달).
            active: True=활성화, False=비활성화.

        Returns:
            True — 성공. False — 인덱스 없음, character_widgets 접근 실패,
            또는 active_checkbox 위젯 없음.
        """
        if not isinstance(self.character_widgets, list):
            return False
        if index < 0 or index >= len(self.character_widgets):
            return False
        widget = self.character_widgets[index]
        checkbox = getattr(widget, 'active_checkbox', None)
        if checkbox is None:
            return False
        try:
            checkbox.setChecked(active)
            return True
        except Exception:
            return False

    def update_processed_display(self, prompts: List[str], ucs: List[str]):
        """처리된 프롬프트를 하단 텍스트 박스에 표시합니다."""
        display_text = []
        for i, (prompt, uc) in enumerate(zip(prompts, ucs)):
            display_text.append(f"C{i+1}: {prompt}")
            display_text.append(f"UC{i+1}: {uc}\n")
        self.processed_prompt_display.setText("\n".join(display_text))

    def add_character_widget(
        self,
        prompt_text: str = "",
        uc_text: str = "",
        is_enabled: bool = True,
        slot_state: str = None,
        return_slot_state: str = "",
        custom_name: str = "",
    ):
        char_id = len(self.character_widgets) + 1
        char_widget = NAID4CharacterInput(char_id, self.remove_character_widget, self.app_context, self.scroll_layout.parentWidget())
        char_widget.slot_state = self._normalize_slot_state(slot_state, is_enabled)
        char_widget.return_slot_state = self._normalize_slot_state(
            return_slot_state,
            is_enabled,
        )
        if char_widget.return_slot_state == "cold":
            char_widget.return_slot_state = "inactive"
        char_widget.custom_name = str(custom_name or "").strip()
        char_widget.prompt_textbox.setText(prompt_text)
        char_widget.uc_textbox.setText(uc_text)
        char_widget.active_checkbox.setChecked(char_widget.slot_state == "active")

        # 🆕 active_checkbox 변경 시 안전장치 체크 연결
        char_widget.active_checkbox.stateChanged.connect(
            lambda state, widget=char_widget: self._on_character_active_changed(widget, state)
        )

        self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, char_widget)
        self.character_widgets.append(char_widget)
        self.update_widget_ids()

        # 🆕 위치 안전장치 체크
        self._check_and_update_position_safety()

    def _remove_character_widget_internal(self, widget_to_remove):
        """내부용 위젯 제거 메서드 (최소 개수 제한 없음)"""
        if widget_to_remove in self.character_widgets:
            self.character_widgets.remove(widget_to_remove)
            widget_to_remove.deleteLater()
            self.update_widget_ids()

            # 🆕 위치 안전장치 체크
            self._check_and_update_position_safety()

    def remove_character_widget(self, widget_to_remove):
        if len(self.character_widgets) > 1:
            self.character_widgets.remove(widget_to_remove)
            widget_to_remove.deleteLater()
            self.update_widget_ids()

            # 🆕 위치 안전장치 체크
            self._check_and_update_position_safety()

    def update_widget_ids(self):
        for i, widget in enumerate(self.character_widgets):
            widget.char_id = i + 1
            widget.active_checkbox.setText(f"C{widget.char_id}")

    # 🆕 캐릭터 위치 관리 메서드들
    def _on_position_toggle(self, state):
        """위치 활성화 체크박스 변경 시"""
        print(f"[DEBUG] _on_position_toggle called with state={state}")
        enabled_count = sum(1 for w in self.character_widgets if w.active_checkbox.isChecked())
        print(f"[DEBUG] Enabled character count: {enabled_count}")

        # PyQt6에서 stateChanged는 int를 전달: 0=Unchecked, 2=Checked
        if state == 2:  # Qt.CheckState.Checked
            if enabled_count < 2:
                # 2인 미만이면 경고 후 자동 해제
                QMessageBox.warning(
                    self.widget,
                    "경고",
                    "2인 이상 캐릭터가 활성화되어야 포지션 기능을 사용할 수 있습니다."
                )
                self.enable_position_checkbox.setChecked(False)
                return

            self.position_button.setEnabled(True)
            self.random_position_button.setEnabled(True)  # 🆕 랜덤 버튼도 활성화
            print(f"✅ 캐릭터 포지션 활성화 (활성 캐릭터: {enabled_count}명)")
        else:
            self.position_button.setEnabled(False)
            self.random_position_button.setEnabled(False)  # 🆕 랜덤 버튼도 비활성화
            # 위치 데이터 초기화
            self.character_positions = ["C3"] * 6
            self._update_position_viewer()
            print("❌ 캐릭터 포지션 비활성화")

    def _on_random_position_clicked(self):
        """🔄 랜덤 버튼 클릭 시 위치 무작위 배치"""
        import random

        # 활성화된 캐릭터 수 확인
        active_indices = [i for i, w in enumerate(self.character_widgets) if w.active_checkbox.isChecked()]

        if len(active_indices) < 2:
            print("⚠️ 활성 캐릭터가 2명 미만입니다. 랜덤 배치 불가.")
            return

        # 5x5 그리드 전체 위치
        all_positions = [f"{col}{row}" for col in ['A', 'B', 'C', 'D', 'E'] for row in ['1', '2', '3', '4', '5']]

        # 가운데 제외 옵션 (기본 True)
        if self.exclude_center_on_random:
            all_positions = [pos for pos in all_positions if pos != 'C3']

        # 활성 캐릭터 수만큼 랜덤 선택 (중복 없이)
        selected_positions = random.sample(all_positions, len(active_indices))

        # 위치 할당
        for active_idx, position in zip(active_indices, selected_positions):
            while len(self.character_positions) <= active_idx:
                self.character_positions.append("C3")
            self.character_positions[active_idx] = position

        # 시각화 업데이트
        self._update_position_viewer()

        print(f"🎲 무작위 위치 배치 완료: {selected_positions}")

    def _check_and_update_position_safety(self):
        """안전장치: 활성 캐릭터가 2명 미만이면 포지션 기능 자동 해제"""
        enabled_count = sum(1 for w in self.character_widgets if w.active_checkbox.isChecked())

        if enabled_count < 2 and self.enable_position_checkbox.isChecked():
            # 자동 해제
            self.enable_position_checkbox.setChecked(False)
            self.enable_position_checkbox.setEnabled(False)
            print(f"⚠️ 활성 캐릭터 {enabled_count}명 → 포지션 기능 자동 해제 및 비활성화")
        elif enabled_count >= 2 and not self.enable_position_checkbox.isEnabled():
            # 다시 활성화 가능하도록 변경
            self.enable_position_checkbox.setEnabled(True)
            print(f"✅ 활성 캐릭터 {enabled_count}명 → 포지션 기능 활성화 가능")

    def _open_position_dialog(self):
        """위치 관리 다이얼로그 열기 (실시간 피드백)"""
        dialog = CharacterPositionManagerDialog(
            character_widgets=self.character_widgets,
            character_positions=self.character_positions,
            parent_module=self,  # 🆕 부모 모듈 참조 전달
            parent=self.widget
        )
        # 🆕 Non-modal로 표시 (백그라운드에서 메인 UI 확인 가능)
        dialog.show()

    def _update_position_viewer(self):
        """위치 시각화 이미지 업데이트 (25x25px, 각 셀 5x5px)"""
        from PIL import Image, ImageDraw
        from PyQt6.QtGui import QPixmap, QImage
        from ui.theme import DARK_COLORS

        print("\n[DEBUG] === _update_position_viewer 호출 ===")

        # 25x25px 이미지 생성 (원본 크기 복원)
        img = Image.new('RGB', (25, 25), DARK_COLORS['bg_secondary'])
        draw = ImageDraw.Draw(img)

        # 색상 팔레트 (temp/characterpos.py와 동일)
        colors = [
            (255, 182, 193),  # Light Pink
            (173, 216, 230),  # Light Blue
            (144, 238, 144),  # Light Green
            (255, 255, 153),  # Light Yellow
            (216, 191, 216),  # Light Purple
            (250, 218, 185)   # Light Orange
        ]

        drawn_count = 0

        # 활성화된 캐릭터만 표시
        for idx, widget in enumerate(self.character_widgets):
            if not widget.active_checkbox.isChecked():
                print(f"[DEBUG] C{idx+1}: 비활성 (스킵)")
                continue

            if idx >= len(self.character_positions):
                print(f"[DEBUG] C{idx+1}: 위치 리스트 범위 초과 (스킵)")
                continue

            pos = self.character_positions[idx]
            if pos is None or len(pos) < 2:
                print(f"[DEBUG] C{idx+1}: 위치 없음 (pos={pos}, 스킵)")
                continue

            col = ord(pos[0]) - ord('A')  # A=0, B=1, ..., E=4
            row = int(pos[1]) - 1         # 1=0, 2=1, ..., 5=4

            # 5x5 셀 좌표 계산
            x = col * 5
            y = row * 5

            print(f"[DEBUG] C{idx+1}: pos={pos}, col={col}, row={row}, x={x}, y={y}")

            # 25x25 이미지 내에서 5x5 셀 그리기
            color = colors[idx % len(colors)]
            draw.rectangle([x, y, x+4, y+4], fill=color, outline=None)
            drawn_count += 1
            print(f"[DEBUG] C{idx+1}: 사각형 그리기 성공 - [{x},{y},{x+4},{y+4}] color={color}")

        print(f"[DEBUG] 총 {drawn_count}개 캐릭터 그려짐")

        # 🆕 디버깅용: 이미지 파일로 저장
        try:
            debug_path = "temp/debug_position_viewer.png"
            img.save(debug_path)
            print(f"[DEBUG] 이미지 저장됨: {debug_path}")
        except Exception as e:
            print(f"[DEBUG] 이미지 저장 실패: {e}")

        # PIL Image → QImage → QPixmap 변환
        img_bytes = img.tobytes("raw", "RGB")
        q_image = QImage(img_bytes, 25, 25, 25 * 3, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(q_image).scaled(
            get_scaled_size(50), get_scaled_size(50),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation  # FastTransformation → SmoothTransformation
        )

        if self.position_viewer:
            self.position_viewer.setPixmap(pixmap)

    def open_c1_asset_generation_window(self):
        """Open the C1 asset flow through a hidden temp window."""
        parent_widget = self.widget if getattr(self, 'widget', None) else None

        if not getattr(self, 'app_context', None) or not hasattr(self.app_context, 'main_window'):
            QMessageBox.warning(parent_widget, "오류", "메인 윈도우 컨텍스트를 찾을 수 없습니다.")
            return

        if not self.character_widgets:
            self.add_character_widget()

        selected_widget = None
        for widget in self.character_widgets:
            if widget.active_checkbox.isChecked():
                selected_widget = widget
                break

        if selected_widget is None:
            for widget in self.character_widgets:
                if widget.prompt_textbox.toPlainText().strip():
                    selected_widget = widget
                    break

        if selected_widget is None or not selected_widget.prompt_textbox.toPlainText().strip():
            QMessageBox.warning(parent_widget, "캐릭터 비어 있음", "체크된 캐릭터 프롬프트를 먼저 입력해주세요.")
            return

        main_window = self.app_context.main_window
        if not hasattr(main_window, 'temp_window_manager'):
            QMessageBox.warning(parent_widget, "오류", "TempWindowManager를 찾을 수 없습니다.")
            return

        temp_window = main_window.temp_window_manager.create_temp_window()

        main_prompt = main_window.main_prompt_textedit.toPlainText() if hasattr(main_window, 'main_prompt_textedit') else ""
        negative_prompt = main_window.negative_prompt_textedit.toPlainText() if hasattr(main_window, 'negative_prompt_textedit') else ""

        temp_window.set_prompts(main_prompt, negative_prompt)
        temp_window.set_initial_params(main_window)
        temp_window.initialize_from_main_modules(main_window)

        temp_window.open_character_asset_generation_window()

        if temp_window.character_asset_window:
            temp_window.character_asset_window.destroyed.connect(
                lambda *_args, window=temp_window: window.close()
            )

        temp_window.hide()

    def open_character_asset_storage_window(self):
        """Open the dedicated character asset storage window."""
        parent_widget = self.widget if getattr(self, 'widget', None) else None
        owner_window = getattr(self.app_context, "main_window", None) if getattr(self, 'app_context', None) else None

        if not getattr(self, 'app_context', None):
            QMessageBox.warning(parent_widget, "오류", "앱 컨텍스트를 찾을 수 없습니다.")
            return

        if not self.character_asset_storage_window:
            self.character_asset_storage_window = CharacterAssetStorageWindow(
                self.app_context,
                owner_window or parent_widget,
            )
            self.character_asset_storage_window.destroyed.connect(
                lambda *_args: setattr(self, "character_asset_storage_window", None)
            )

        self.character_asset_storage_window.load_storage_items()
        self.character_asset_storage_window.show()
        self.character_asset_storage_window.raise_()
        self.character_asset_storage_window.activateWindow()

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
