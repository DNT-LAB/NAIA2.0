"""
인스턴트 와일드카드 모듈
사용자 정의 와일드카드를 JSON 파일로 관리하고 빠르게 삽입할 수 있는 기능
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QTextEdit, QLabel, QMessageBox, QDialog, QDialogButtonBox,
    QLineEdit, QGroupBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject

from interfaces.base_module import BaseMiddleModule
from ui.theme import DARK_STYLES, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size


class AddWildcardDialog(QDialog):
    """와일드카드 추가 다이얼로그"""
    
    def __init__(self, parent=None, json_files=None, current_file=None, initial_text=""):
        super().__init__(parent)
        self.setWindowTitle("인스턴트 와일드카드 추가")
        self.setModal(True)
        self.setMinimumWidth(get_scaled_size(400))
        
        # 다크 테마 적용
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        
        self.json_files = json_files or []
        self.current_file = current_file
        self.initial_text = initial_text
        
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(get_scaled_size(10))
        
        # 대상 파일 선택
        file_layout = QHBoxLayout()
        file_label = QLabel("대상 파일:")
        file_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(16)}px;")
        file_layout.addWidget(file_label)
        
        self.file_combo = QComboBox()
        self.file_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.file_combo.addItems(self.json_files)
        if self.current_file and self.current_file in self.json_files:
            self.file_combo.setCurrentText(self.current_file)
        file_layout.addWidget(self.file_combo)
        layout.addLayout(file_layout)
        
        # 아이템명 입력
        name_layout = QHBoxLayout()
        name_label = QLabel("아이템명:")
        name_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(16)}px;")
        name_layout.addWidget(name_label)
        
        self.name_edit = QLineEdit()
        self.name_edit.setProperty("autocomplete_ignore", True)  # AutoComplete 제외
        self.name_edit.setStyleSheet(DARK_STYLES['compact_lineedit'])
        self.name_edit.setPlaceholderText("와일드카드 키 이름 입력")
        name_layout.addWidget(self.name_edit)
        layout.addLayout(name_layout)
        
        # 값 입력 (라벨 제거, TextEdit만)
        self.value_edit = QTextEdit()
        self.value_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.value_edit.setPlaceholderText("와일드카드 값 입력 (태그, 여러 줄 가능)")
        self.value_edit.setMinimumHeight(get_scaled_size(150))
        if self.initial_text:
            self.value_edit.setPlainText(self.initial_text)
        layout.addWidget(self.value_edit)
        
        # 버튼
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.setStyleSheet(f"""
            QPushButton {{
                font-size: {get_scaled_font_size(16)}px;
                padding: {get_scaled_size(8)}px {get_scaled_size(16)}px;
            }}
        """)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
    def get_data(self) -> tuple:
        """입력된 데이터 반환"""
        return (
            self.file_combo.currentText(),
            self.name_edit.text().strip(),
            self.value_edit.toPlainText()
        )


class WildcardSignals(QObject):
    """와일드카드 시그널 전용 클래스"""
    wildcards_updated = pyqtSignal(dict)


class InstantWildcardModule(BaseMiddleModule):
    """인스턴트 와일드카드 관리 모듈"""
    
    def __init__(self):
        super().__init__()
        # 시그널 객체 생성
        self.signals = WildcardSignals()
        self.widget = None
        self.instant_wildcard_dict = {}  # 전역 와일드카드 딕셔너리
        self.json_data = {}  # 파일별 데이터 저장
        self.save_path = Path("save/instant_wildcard")
        self.current_file = None
        self.current_key = None
        self.is_editing = False
        
        # 기본 파일 템플릿
        self.default_templates = {
            "default.json": {
                "quality": "masterpiece, best quality",
                "negative": "lowres, bad anatomy, bad hands",
                "style": "anime style, digital art"
            },
            "캐릭터.json": {
                "girl": "1girl, solo",
                "boy": "1boy, solo", 
                "multiple": "multiple girls"
            },
            "의상.json": {
                "school": "school uniform, skirt",
                "casual": "casual clothes, jeans",
                "formal": "formal wear, suit"
            },
            "장소.json": {
                "outdoor": "outdoors, sky, clouds",
                "indoor": "indoors, room",
                "city": "city, street, buildings"
            }
        }
        
    def get_title(self) -> str:
        return "☑️ 인스턴트 와일드카드"
    
    def get_order(self) -> int:
        # 조건부 프롬프트보다 위에 위치
        return 85
    
    def initialize_with_context(self, context):
        """AppContext 주입"""
        self.app_context = context
        
    def create_widget(self, parent=None) -> QWidget:
        if self.widget:
            return self.widget
            
        self.widget = QWidget(parent)
        content_layout = QVBoxLayout(self.widget)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(get_scaled_size(8))
        
        # 상단 컨트롤
        top_layout = QHBoxLayout()
        
        # 업데이트 버튼
        self.update_btn = QPushButton("와일드카드 업데이트")
        self.update_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.update_btn.clicked.connect(self.load_all_wildcards)
        top_layout.addWidget(self.update_btn)
        
        top_layout.addStretch()
        content_layout.addLayout(top_layout)
        
        # 파일 선택
        file_layout = QHBoxLayout()
        file_label = QLabel("파일:")
        file_label.setStyleSheet(f"font-size: {get_scaled_font_size(16)}px;")
        file_label.setFixedWidth(get_scaled_size(50))  # 고정 너비
        file_layout.addWidget(file_label)
        
        self.file_combo = QComboBox()
        self.file_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.file_combo.setFixedWidth(get_scaled_size(300))  # 고정 너비
        self.file_combo.currentTextChanged.connect(self.on_file_changed)
        file_layout.addWidget(self.file_combo)
        file_layout.addStretch()  # 왼쪽 정렬
        
        content_layout.addLayout(file_layout)
        
        # 키 선택
        key_layout = QHBoxLayout()
        key_label = QLabel("항목:")
        key_label.setStyleSheet(f"font-size: {get_scaled_font_size(16)}px;")
        key_label.setFixedWidth(get_scaled_size(50))  # 고정 너비
        key_layout.addWidget(key_label)
        
        self.key_combo = QComboBox()
        self.key_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.key_combo.setFixedWidth(get_scaled_size(300))  # 고정 너비
        self.key_combo.currentTextChanged.connect(self.on_key_changed)
        key_layout.addWidget(self.key_combo)
        key_layout.addStretch()  # 왼쪽 정렬
        
        content_layout.addLayout(key_layout)
        
        # 값 편집
        self.value_edit = QTextEdit()
        self.value_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.value_edit.setMinimumHeight(get_scaled_size(100))
        self.value_edit.setReadOnly(True)
        content_layout.addWidget(self.value_edit)
        
        # 액션 버튼
        button_layout = QHBoxLayout()
        
        self.edit_btn = QPushButton("수정")
        self.edit_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.edit_btn.clicked.connect(self.toggle_edit_mode)
        button_layout.addWidget(self.edit_btn)
        
        self.delete_btn = QPushButton("삭제")
        self.delete_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.delete_btn.clicked.connect(self.delete_item)
        button_layout.addWidget(self.delete_btn)
        
        self.add_btn = QPushButton("추가")
        self.add_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.add_btn.clicked.connect(self.add_item)
        button_layout.addWidget(self.add_btn)
        
        content_layout.addLayout(button_layout)
        
        # 스트레치 추가로 위쪽 정렬
        content_layout.addStretch()
        
        # 초기화
        self.initialize_wildcards()
        
        return self.widget
    
    def initialize_wildcards(self):
        """와일드카드 시스템 초기화"""
        # 폴더 생성
        self.save_path.mkdir(parents=True, exist_ok=True)
        
        # default.json 확인 및 초기 파일 생성
        default_file = self.save_path / "default.json"
        if not default_file.exists():
            self.create_initial_files()
        
        # 와일드카드 로드
        self.load_all_wildcards()
    
    def create_initial_files(self):
        """초기 JSON 파일들 생성"""
        for filename, content in self.default_templates.items():
            filepath = self.save_path / filename
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(content, f, ensure_ascii=False, indent=2)
                print(f"[OK] Initial file created: {filename}")
            except Exception as e:
                print(f"[ERROR] Failed to create file {filename}: {e}")
    
    def load_all_wildcards(self):
        """모든 와일드카드 파일 로드"""
        self.json_data.clear()
        self.instant_wildcard_dict.clear()
        
        # JSON 파일 목록 가져오기
        json_files = sorted([f.name for f in self.save_path.glob("*.json")])
        
        # default.json을 우선 로드
        if "default.json" in json_files:
            json_files.remove("default.json")
            json_files.insert(0, "default.json")
        
        # 파일별로 로드
        for filename in json_files:
            filepath = self.save_path / filename
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.json_data[filename] = data
                    
                    # instant_wildcard_dict에 추가
                    basename = filename.replace('.json', '')
                    for key, value in data.items():
                        # 중복 키 처리
                        if key in self.instant_wildcard_dict:
                            if basename != "default":
                                key = f"{key} ({basename})"
                        self.instant_wildcard_dict[key] = value
                        
            except Exception as e:
                print(f"[ERROR] Failed to load file {filename}: {e}")
        
        # UI 업데이트
        self.update_ui()
        
        # 시그널 발송
        self.signals.wildcards_updated.emit(self.instant_wildcard_dict)
        
        # WildcardManager에 인스턴트 와일드카드 업데이트
        if hasattr(self, 'app_context') and self.app_context:
            wildcard_manager = getattr(self.app_context, 'wildcard_manager', None)
            if wildcard_manager:
                wildcard_manager.update_instant_wildcards(self.instant_wildcard_dict)
        
        print(f"[OK] Wildcards loaded: {len(self.instant_wildcard_dict)} items")
    
    def update_ui(self):
        """UI 콤보박스 업데이트"""
        # 파일 콤보박스 업데이트
        self.file_combo.blockSignals(True)
        current_file = self.file_combo.currentText()
        self.file_combo.clear()
        self.file_combo.addItems(sorted(self.json_data.keys()))
        if current_file in self.json_data:
            self.file_combo.setCurrentText(current_file)
        elif self.json_data:
            self.file_combo.setCurrentIndex(0)
        self.file_combo.blockSignals(False)
        
        # 파일 변경 트리거
        if self.file_combo.currentText():
            self.on_file_changed(self.file_combo.currentText())
    
    def on_file_changed(self, filename):
        """파일 선택 변경"""
        if not filename or filename not in self.json_data:
            return
        
        self.current_file = filename
        data = self.json_data[filename]
        
        # 키 콤보박스 업데이트
        self.key_combo.blockSignals(True)
        self.key_combo.clear()
        self.key_combo.addItems(sorted(data.keys()))
        if data:
            self.key_combo.setCurrentIndex(0)
        self.key_combo.blockSignals(False)
        
        # 키 변경 트리거
        if self.key_combo.currentText():
            self.on_key_changed(self.key_combo.currentText())
    
    def on_key_changed(self, key):
        """키 선택 변경"""
        if not key or not self.current_file:
            return
        
        self.current_key = key
        data = self.json_data.get(self.current_file, {})
        value = data.get(key, "")
        
        # 값 표시
        self.value_edit.setPlainText(value)
    
    def toggle_edit_mode(self):
        """편집 모드 토글"""
        if not self.is_editing:
            # 편집 모드 진입
            self.is_editing = True
            self.edit_btn.setText("확인")
            self.delete_btn.setText("취소")
            self.value_edit.setReadOnly(False)
            self.file_combo.setEnabled(False)
            self.key_combo.setEnabled(False)
            self.add_btn.setEnabled(False)
        else:
            # 수정 확인/취소 처리
            if self.edit_btn.text() == "확인":
                self.save_edit()
            else:
                self.cancel_edit()
    
    def save_edit(self):
        """편집 내용 저장"""
        if not self.current_file or not self.current_key:
            return
        
        new_value = self.value_edit.toPlainText()
        
        # JSON 데이터 업데이트
        self.json_data[self.current_file][self.current_key] = new_value
        
        # 파일에 저장
        filepath = self.save_path / self.current_file
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self.json_data[self.current_file], f, ensure_ascii=False, indent=2)
            
            # instant_wildcard_dict 업데이트
            self.load_all_wildcards()
            
            QMessageBox.information(self.widget, "성공", "수정이 저장되었습니다.")
        except Exception as e:
            QMessageBox.critical(self.widget, "오류", f"저장 실패: {e}")
        
        # 편집 모드 종료
        self.exit_edit_mode()
    
    def cancel_edit(self):
        """편집 취소"""
        # 원래 값으로 복원
        if self.current_file and self.current_key:
            original_value = self.json_data[self.current_file].get(self.current_key, "")
            self.value_edit.setPlainText(original_value)
        
        # 편집 모드 종료
        self.exit_edit_mode()
    
    def exit_edit_mode(self):
        """편집 모드 종료"""
        self.is_editing = False
        self.edit_btn.setText("수정")
        self.delete_btn.setText("삭제")
        self.value_edit.setReadOnly(True)
        self.file_combo.setEnabled(True)
        self.key_combo.setEnabled(True)
        self.add_btn.setEnabled(True)
    
    def delete_item(self):
        """현재 항목 삭제"""
        if self.is_editing:
            # 편집 모드에서는 취소 동작
            self.cancel_edit()
            return
        
        if not self.current_file or not self.current_key:
            return
        
        # 확인 다이얼로그
        reply = QMessageBox.question(
            self.widget, 
            "삭제 확인",
            f"'{self.current_key}' 항목을 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # JSON 데이터에서 제거
            del self.json_data[self.current_file][self.current_key]
            
            # 파일에 저장
            filepath = self.save_path / self.current_file
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(self.json_data[self.current_file], f, ensure_ascii=False, indent=2)
                
                # 와일드카드 재로드
                self.load_all_wildcards()
                
                QMessageBox.information(self.widget, "성공", "항목이 삭제되었습니다.")
            except Exception as e:
                QMessageBox.critical(self.widget, "오류", f"삭제 실패: {e}")
    
    def add_item(self, initial_text=""):
        """새 항목 추가"""
        dialog = AddWildcardDialog(
            parent=self.widget,
            json_files=list(self.json_data.keys()),
            current_file=self.current_file,
            initial_text=initial_text
        )
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            filename, key, value = dialog.get_data()
            
            if not key:
                QMessageBox.warning(self.widget, "경고", "아이템명을 입력해주세요.")
                return
            
            # 중복 키 확인
            if key in self.json_data.get(filename, {}):
                reply = QMessageBox.question(
                    self.widget,
                    "중복 확인",
                    f"'{key}' 항목이 이미 존재합니다. 덮어쓰시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
            
            # 데이터 추가
            if filename not in self.json_data:
                self.json_data[filename] = {}
            self.json_data[filename][key] = value
            
            # 파일에 저장
            filepath = self.save_path / filename
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(self.json_data[filename], f, ensure_ascii=False, indent=2)
                
                # 와일드카드 재로드
                self.load_all_wildcards()
                
                # 추가한 항목으로 이동
                self.file_combo.setCurrentText(filename)
                self.key_combo.setCurrentText(key)
                
                QMessageBox.information(self.widget, "성공", "항목이 추가되었습니다.")
            except Exception as e:
                QMessageBox.critical(self.widget, "오류", f"추가 실패: {e}")
    
    def add_from_selection(self, text: str):
        """선택된 텍스트로부터 와일드카드 추가 (메인 윈도우에서 호출)"""
        self.add_item(initial_text=text)
    
    def get_wildcards(self) -> Dict[str, str]:
        """현재 로드된 와일드카드 딕셔너리 반환"""
        return self.instant_wildcard_dict.copy()
    
    def get_parameters(self) -> dict:
        """모듈 파라미터 반환 (생성 파이프라인용)"""
        return {}
    
    @property
    def wildcards_updated(self):
        """시그널 접근을 위한 프로퍼티"""
        return self.signals.wildcards_updated