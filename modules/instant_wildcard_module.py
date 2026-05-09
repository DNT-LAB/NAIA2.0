"""
인스턴트 와일드카드 모듈
사용자 정의 와일드카드를 JSON 파일로 관리하고 빠르게 삽입할 수 있는 기능
"""

import os
import json
import platform
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QTextEdit, QLabel, QMessageBox, QDialog, QDialogButtonBox,
    QLineEdit, QGroupBox, QSizePolicy, QApplication, QSplitter,
    QInputDialog
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QImage

from interfaces.base_module import BaseMiddleModule
from ui.theme import DARK_STYLES, DARK_COLORS, get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from utils.clipboard_image import pixmap_from_clipboard


class PreviewImageWidget(QWidget):
    """와일드카드 이미지 미리보기 위젯 - 클립보드 지원"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self.current_file = None
        self.current_key = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(f"background-color: {DARK_COLORS['bg_secondary']};")
        
        # 클립보드 붙여넣기 지원
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
    
    def set_item(self, filename: str, key: str):
        """현재 아이템 설정"""
        self.current_file = filename.replace('.json', '') if filename else None
        self.current_key = key
        self.load_preview_image()
    
    def load_preview_image(self):
        """와일드카드 미리보기 이미지 로드"""
        if not self.current_file or not self.current_key:
            self._pixmap = None
            self.update()
            return
        
        # 이미지 파일 경로 (self.current_file은 이미 .json이 제거된 상태)
        image_path = Path("save") / "instant_wildcard" / "images" / self.current_file / f"{self.current_key}.png"
        if image_path.exists():
            self._pixmap = QPixmap(str(image_path))
        else:
            self._pixmap = None
        self.update()
    
    def save_preview_image(self):
        """현재 이미지를 와일드카드 미리보기로 저장 (512px 리사이즈)"""
        if not self._pixmap or not self.current_file or not self.current_key:
            return
        
        # 이미지 디렉토리 생성
        image_dir = Path("save") / "instant_wildcard" / "images" / self.current_file
        image_dir.mkdir(parents=True, exist_ok=True)
        
        # 512px로 리사이즈 (긴 쪽이 512가 되도록)
        original_size = self._pixmap.size()
        width = original_size.width()
        height = original_size.height()
        
        if width > height:
            new_width = 512
            new_height = int(512 * height / width)
        else:
            new_height = 512
            new_width = int(512 * width / height)
        
        # 리사이즈하여 저장
        resized_pixmap = self._pixmap.scaled(
            new_width, new_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        
        # 이미지 저장
        image_path = image_dir / f"{self.current_key}.png"
        resized_pixmap.save(str(image_path), "PNG")
        print(f"🖼️ 와일드카드 이미지 저장: {self.current_file}/{self.current_key} ({new_width}x{new_height})")
    
    def clear_preview(self):
        """프리뷰 클리어"""
        self._pixmap = None
        self.current_file = None
        self.current_key = None
        self.update()
    
    def keyPressEvent(self, event):
        """Ctrl+V로 클립보드 이미지 붙여넣기"""
        if event.key() == Qt.Key.Key_V and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self.paste_from_clipboard()
    
    def paste_from_clipboard(self):
        """클립보드에서 이미지 붙여넣기"""
        clipboard = QApplication.clipboard()
        pixmap = pixmap_from_clipboard(clipboard)
        if not pixmap.isNull():
            self._pixmap = pixmap
            self.update()
            # 자동 저장 (512px 리사이즈)
            if self.current_file and self.current_key:
                self.save_preview_image()
                # 리사이즈된 이미지 다시 로드
                self.load_preview_image()
            return True
        return False
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(DARK_COLORS['bg_secondary']))
        
        if not self._pixmap:
            painter.setPen(QColor(DARK_COLORS['text_secondary']))
            font = QFont()
            font.setPointSize(get_scaled_font_size(12))
            painter.setFont(font)
            
            # 안내 텍스트
            text = "와일드카드 이미지\n\n클릭 후 Ctrl+V로\n이미지를 붙여넣으세요\n\n(512px로 자동 리사이즈)"
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)
            return
        
        # 이미지 표시
        widget_size = self.size()
        
        # 위젯 크기에 맞춰 이미지를 스케일링 (비율 유지)
        scaled_pixmap = self._pixmap.scaled(
            widget_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        
        # 중앙 정렬
        x = (widget_size.width() - scaled_pixmap.width()) // 2
        y = (widget_size.height() - scaled_pixmap.height()) // 2
        
        painter.drawPixmap(x, y, scaled_pixmap)


class AddWildcardDialog(QDialog):
    """와일드카드 추가 다이얼로그"""
    
    def __init__(self, parent=None, json_files=None, current_file=None, initial_text="", module_instance=None):
        super().__init__(parent)
        self.setWindowTitle("인스턴트 와일드카드 추가")
        self.setModal(False)  # 모달리스로 변경
        self.resize(get_scaled_size(800), get_scaled_size(400))  # 크기 증가
        
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
        self.module_instance = module_instance  # 모듈 인스턴스 참조
        self.result_callback = None  # 결과 처리 콜백
        
        self.init_ui()
        
    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setSpacing(get_scaled_size(10))
        
        # 왼쪽 패널 (기존 UI)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setSpacing(get_scaled_size(10))
        
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
        self.file_combo.currentTextChanged.connect(self.on_file_changed)
        file_layout.addWidget(self.file_combo)
        left_layout.addLayout(file_layout)
        
        # 아이템명 입력
        name_layout = QHBoxLayout()
        name_label = QLabel("아이템명:")
        name_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(16)}px;")
        name_layout.addWidget(name_label)
        
        self.name_edit = QLineEdit()
        self.name_edit.setProperty("autocomplete_ignore", True)  # AutoComplete 제외
        self.name_edit.setStyleSheet(DARK_STYLES['compact_lineedit'])
        self.name_edit.setPlaceholderText("와일드카드 키 이름 입력")
        self.name_edit.textChanged.connect(self.on_name_changed)
        name_layout.addWidget(self.name_edit)
        left_layout.addLayout(name_layout)
        
        # 값 입력
        value_label = QLabel("와일드카드 값:")
        value_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(16)}px;")
        left_layout.addWidget(value_label)

        self.value_edit = QTextEdit()
        self.value_edit.setAcceptRichText(False)  # 서식 붙여넣기 차단
        self.value_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.value_edit.setPlaceholderText("와일드카드 값 입력 (태그, 여러 줄 가능)")
        self.value_edit.setMinimumHeight(get_scaled_size(150))
        if self.initial_text:
            self.value_edit.setPlainText(self.initial_text)
        left_layout.addWidget(self.value_edit)
        
        # 버튼
        button_layout = QHBoxLayout()
        
        self.ok_button = QPushButton("추가")
        self.ok_button.setStyleSheet(DARK_STYLES['primary_button'])
        self.ok_button.clicked.connect(self.on_ok_clicked)
        button_layout.addWidget(self.ok_button)
        
        self.cancel_button = QPushButton("취소")
        self.cancel_button.setStyleSheet(DARK_STYLES['secondary_button'])
        self.cancel_button.clicked.connect(self.close)
        button_layout.addWidget(self.cancel_button)
        
        left_layout.addLayout(button_layout)
        
        # 오른쪽 패널 (이미지 프리뷰)
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setSpacing(get_scaled_size(8))
        
        preview_label = QLabel("와일드카드 이미지:")
        preview_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(16)}px;")
        right_layout.addWidget(preview_label)
        
        self.preview_widget = PreviewImageWidget()
        self.preview_widget.setMinimumWidth(get_scaled_size(250))
        right_layout.addWidget(self.preview_widget)
        
        # 메인 레이아웃에 추가
        main_layout.addWidget(left_widget, 2)  # 왼쪽 패널 비율 2
        main_layout.addWidget(right_widget, 1)  # 오른쪽 패널 비율 1
        
    def on_file_changed(self, filename):
        """파일 선택이 변경되었을 때 이미지 프리뷰 업데이트"""
        if self.name_edit.text():
            self.preview_widget.set_item(filename, self.name_edit.text())
    
    def on_name_changed(self, name):
        """아이템명이 변경되었을 때 이미지 프리뷰 업데이트"""
        if self.file_combo.currentText():
            self.preview_widget.set_item(self.file_combo.currentText(), name)
    
    def on_ok_clicked(self):
        """확인 버튼 클릭 시 처리"""
        data = self.get_data()
        if not data[1]:  # 아이템명이 없으면
            QMessageBox.warning(self, "경고", "아이템명을 입력해주세요.")
            return
        
        if self.result_callback:
            self.result_callback(data)
        
        self.accept()  # 다이얼로그 닫기
    
    def set_result_callback(self, callback):
        """결과 처리 콜백 설정"""
        self.result_callback = callback
    
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
        self.instant_wildcard_tree = {}  # 파일별 그룹화된 와일드카드 트리
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
        main_layout = QVBoxLayout(self.widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(get_scaled_size(8))
        
        # 상단 컨트롤
        top_layout = QHBoxLayout()
        
        # 업데이트 버튼
        self.update_btn = QPushButton("와일드카드 업데이트")
        self.update_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.update_btn.clicked.connect(self.load_all_wildcards)
        top_layout.addWidget(self.update_btn)
        
        # 와일드카드 그룹 추가 버튼
        self.add_group_btn = QPushButton("📁 그룹 추가")
        self.add_group_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.add_group_btn.clicked.connect(self.add_wildcard_group)
        top_layout.addWidget(self.add_group_btn)
        
        # 폴더 열기 버튼 추가
        self.open_folder_btn = QPushButton("📂 폴더 열기")
        self.open_folder_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.open_folder_btn.clicked.connect(self.open_save_folder)
        self.open_folder_btn.setToolTip(f"인스턴트 와일드카드 저장 폴더를 엽니다\n{self.save_path}")
        top_layout.addWidget(self.open_folder_btn)
        
        top_layout.addStretch()
        main_layout.addLayout(top_layout)
        
        # 메인 스플리터 (좌우 분할)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 왼쪽 패널 (기존 컨트롤)
        left_widget = QWidget()
        content_layout = QVBoxLayout(left_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(get_scaled_size(8))
        
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
        self.value_edit.setAcceptRichText(False)  # 서식 붙여넣기 차단
        self.value_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.value_edit.setMinimumHeight(get_scaled_size(100))
        self.value_edit.setReadOnly(True)
        content_layout.addWidget(self.value_edit)
        
        # 액션 버튼 (크기 조정 및 이름변경 버튼 추가)
        button_layout = QHBoxLayout()
        
        self.edit_btn = QPushButton("수정")
        self.edit_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.edit_btn.setFixedWidth(get_scaled_size(100))  # 버튼 크기 줄임
        self.edit_btn.clicked.connect(self.toggle_edit_mode)
        button_layout.addWidget(self.edit_btn)
        
        self.delete_btn = QPushButton("삭제")
        self.delete_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.delete_btn.setFixedWidth(get_scaled_size(100))  # 버튼 크기 줄임
        self.delete_btn.clicked.connect(self.delete_item)
        button_layout.addWidget(self.delete_btn)
        
        self.rename_btn = QPushButton("이름변경")
        self.rename_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.rename_btn.setFixedWidth(get_scaled_size(100))  # 이름변경 버튼
        self.rename_btn.clicked.connect(self.rename_item)
        button_layout.addWidget(self.rename_btn)
        
        self.add_btn = QPushButton("추가")
        self.add_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.add_btn.setFixedWidth(get_scaled_size(100))  # 버튼 크기 줄임
        self.add_btn.clicked.connect(self.add_item)
        button_layout.addWidget(self.add_btn)
        
        content_layout.addLayout(button_layout)
        
        # 스트레치 추가로 위쪽 정렬
        content_layout.addStretch()
        
        # 오른쪽 패널 (이미지 프리뷰)
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(get_scaled_size(8))
        
        preview_label = QLabel("와일드카드 이미지:")
        preview_label.setStyleSheet(f"font-size: {get_scaled_font_size(16)}px;")
        right_layout.addWidget(preview_label)
        
        self.preview_widget = PreviewImageWidget()
        self.preview_widget.setMinimumWidth(get_scaled_size(200))
        right_layout.addWidget(self.preview_widget)
        
        # 스플리터에 위젯 추가
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([400, 200])  # 초기 크기 비율
        
        main_layout.addWidget(splitter)
        
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
        self.instant_wildcard_tree.clear()
        
        # JSON 파일 목록 가져오기 (메타데이터 파일 제외)
        json_files = sorted([f.name for f in self.save_path.glob("*.json") if f.name != "wc_metadata.json"])
        
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
                    
                    # instant_wildcard_tree에 파일별로 그룹화
                    basename = filename.replace('.json', '')
                    self.instant_wildcard_tree[basename] = data.copy()
                    
                    # instant_wildcard_dict에 추가
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
        
        # WildcardManager에 인스턴트 와일드카드 업데이트 (딕셔너리와 트리 모두 전달)
        if hasattr(self, 'app_context') and self.app_context:
            wildcard_manager = getattr(self.app_context, 'wildcard_manager', None)
            if wildcard_manager:
                wildcard_manager.update_instant_wildcards(self.instant_wildcard_dict, self.instant_wildcard_tree)
        
        print(f"[OK] Wildcards loaded: {len(self.instant_wildcard_dict)} items")
    
    def add_wildcard_group(self):
        """새로운 와일드카드 그룹(JSON 파일) 추가"""
        # 사용자로부터 그룹 이름 입력받기
        group_name, ok = QInputDialog.getText(
            self.widget,
            "와일드카드 그룹 추가",
            "새 그룹 이름을 입력하세요:\n(영문, 숫자, 언더스코어만 사용 가능)",
            QLineEdit.EchoMode.Normal,
            ""
        )
        
        if not ok or not group_name:
            return
        
        # 파일명 유효성 검사
        import re
        if not re.match(r'^[a-zA-Z0-9_가-힣]+$', group_name):
            QMessageBox.warning(
                self.widget,
                "경고",
                "그룹 이름은 영문, 숫자, 한글, 언더스코어만 사용할 수 있습니다."
            )
            return
        
        # .json 확장자 추가
        if not group_name.endswith('.json'):
            group_name += '.json'
        
        # 파일 경로 생성
        filepath = self.save_path / group_name
        
        # 이미 존재하는 파일인지 확인
        if filepath.exists():
            QMessageBox.warning(
                self.widget,
                "경고",
                f"'{group_name}' 파일이 이미 존재합니다."
            )
            return
        
        # 새 JSON 파일 생성 (빈 딕셔너리로 시작)
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
            
            # 생성 성공 메시지
            QMessageBox.information(
                self.widget,
                "성공",
                f"'{group_name}' 그룹이 생성되었습니다."
            )
            
            # 와일드카드 다시 로드하여 UI 업데이트
            self.load_all_wildcards()
            
            # 새로 생성한 파일을 선택
            if group_name in self.json_data:
                index = self.file_combo.findText(group_name)
                if index >= 0:
                    self.file_combo.setCurrentIndex(index)
            
        except Exception as e:
            QMessageBox.critical(
                self.widget,
                "오류",
                f"파일 생성 중 오류가 발생했습니다:\n{str(e)}"
            )
    
    def open_save_folder(self):
        """인스턴트 와일드카드 저장 폴더를 파일 탐색기에서 엽니다."""
        try:
            # 폴더가 존재하지 않으면 생성
            if not self.save_path.exists():
                self.save_path.mkdir(parents=True, exist_ok=True)
            
            # 운영체제별로 폴더 열기
            system = platform.system()
            if system == "Windows":
                os.startfile(str(self.save_path))
            elif system == "Darwin":  # macOS
                subprocess.run(["open", str(self.save_path)])
            else:  # Linux
                subprocess.run(["xdg-open", str(self.save_path)])
            
            print(f"📂 인스턴트 와일드카드 폴더 열기: {self.save_path}")
            
        except Exception as e:
            print(f"❌ 폴더 열기 실패: {e}")
            QMessageBox.warning(
                self.widget,
                "경고",
                f"폴더를 열 수 없습니다:\n{str(e)}"
            )
    
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
        
        # 이미지 프리뷰 업데이트
        if hasattr(self, 'preview_widget'):
            self.preview_widget.set_item(self.current_file, key)
    
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
        """현재 항목 삭제 (이미지 파일도 함께 삭제)"""
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
            # 이미지 파일 삭제 (filename에서 .json 제거)
            basename = self.current_file.replace('.json', '')
            image_path = Path("save") / "instant_wildcard" / "images" / basename / f"{self.current_key}.png"
            if image_path.exists():
                try:
                    image_path.unlink()
                    print(f"🗑️ 이미지 파일 삭제: {image_path}")
                except Exception as e:
                    print(f"⚠️ 이미지 파일 삭제 실패: {e}")
            
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
    
    def rename_item(self):
        """현재 항목 이름 변경 (이미지 파일도 함께 이름 변경)"""
        if self.is_editing:
            # 편집 모드에서는 동작하지 않음
            return
        
        if not self.current_file or not self.current_key:
            return
        
        # 새 이름 입력 받기
        new_name, ok = QInputDialog.getText(
            self.widget,
            "이름 변경",
            f"'{self.current_key}'의 새 이름을 입력하세요:",
            QLineEdit.EchoMode.Normal,
            self.current_key
        )
        
        if ok and new_name and new_name != self.current_key:
            # 중복 검사
            if new_name in self.json_data[self.current_file]:
                QMessageBox.warning(
                    self.widget,
                    "경고",
                    f"'{new_name}' 이름이 이미 존재합니다."
                )
                return
            
            try:
                # 이미지 파일 이름 변경 (filename에서 .json 제거)
                basename = self.current_file.replace('.json', '')
                old_image_path = Path("save") / "instant_wildcard" / "images" / basename / f"{self.current_key}.png"
                new_image_path = Path("save") / "instant_wildcard" / "images" / basename / f"{new_name}.png"
                
                if old_image_path.exists():
                    try:
                        old_image_path.rename(new_image_path)
                        print(f"📝 이미지 파일 이름 변경: {old_image_path} → {new_image_path}")
                    except Exception as e:
                        print(f"⚠️ 이미지 파일 이름 변경 실패: {e}")
                
                # JSON 데이터에서 이름 변경
                value = self.json_data[self.current_file][self.current_key]
                del self.json_data[self.current_file][self.current_key]
                self.json_data[self.current_file][new_name] = value
                
                # 파일에 저장
                filepath = self.save_path / self.current_file
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(self.json_data[self.current_file], f, ensure_ascii=False, indent=2)
                
                # 와일드카드 재로드
                self.load_all_wildcards()
                
                # 새 이름으로 선택 유지
                index = self.key_combo.findText(new_name)
                if index >= 0:
                    self.key_combo.setCurrentIndex(index)
                
                QMessageBox.information(self.widget, "성공", f"항목 이름이 '{new_name}'으로 변경되었습니다.")
                
            except Exception as e:
                QMessageBox.critical(self.widget, "오류", f"이름 변경 실패: {e}")
    
    def add_item(self, initial_text=""):
        """새 항목 추가"""
        dialog = AddWildcardDialog(
            parent=self.widget,
            json_files=list(self.json_data.keys()),
            current_file=self.current_file,
            initial_text=initial_text,
            module_instance=self
        )
        
        # 결과 처리 콜백 설정
        def handle_result(data):
            filename, key, value = data
            
            if not key:
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
        
        dialog.set_result_callback(handle_result)
        dialog.show()  # exec() 대신 show() 사용
    
    def add_from_selection(self, text: str):
        """선택된 텍스트로부터 와일드카드 추가 (메인 윈도우에서 호출)"""
        self.add_item(initial_text=text)
    
    def get_wildcards(self) -> Tuple[Dict[str, str], Dict[str, Dict[str, str]]]:
        """현재 로드된 와일드카드 딕셔너리와 트리 반환
        
        Returns:
            tuple: (instant_wildcard_dict, instant_wildcard_tree)
                - instant_wildcard_dict: 전역 와일드카드 딕셔너리 (중복 키는 suffix 포함)
                - instant_wildcard_tree: 파일별 그룹화된 와일드카드 트리
        """
        return self.instant_wildcard_dict.copy(), self.instant_wildcard_tree.copy()
    
    def get_parameters(self) -> dict:
        """모듈 파라미터 반환 (생성 파이프라인용)"""
        return {}
    
    @property
    def wildcards_updated(self):
        """시그널 접근을 위한 프로퍼티"""
        return self.signals.wildcards_updated

    def delete_wildcard(self, file_key: str, item_key: str) -> bool:
        """와일드카드 삭제 API (RemoteWindow에서 호출)

        Args:
            file_key: 파일 키 (예: "character")
            item_key: 아이템 키 (예: "my_character")

        Returns:
            bool: 성공 여부
        """
        # file_key에 .json 붙이기
        filename = f"{file_key}.json"

        if filename not in self.json_data:
            print(f"⚠️ 파일을 찾을 수 없음: {filename}")
            return False

        if item_key not in self.json_data[filename]:
            print(f"⚠️ 키를 찾을 수 없음: {item_key}")
            return False

        try:
            # JSON 데이터에서 제거
            del self.json_data[filename][item_key]

            # 파일에 저장
            filepath = self.save_path / filename
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self.json_data[filename], f, ensure_ascii=False, indent=2)

            # 와일드카드 재로드
            self.load_all_wildcards()

            # UI 업데이트 (현재 선택된 항목이었다면)
            if self.current_file == filename and self.current_key == item_key:
                self.refresh_key_combo()

            print(f"✅ 와일드카드 삭제됨: {file_key}::{item_key}")
            return True

        except Exception as e:
            print(f"⚠️ 와일드카드 삭제 실패: {e}")
            return False

    def update_wildcard_value(self, file_key: str, item_key: str, new_value: str) -> bool:
        """와일드카드 값 업데이트 API (RemoteWindow에서 호출)

        Args:
            file_key: 파일 키 (예: "character")
            item_key: 아이템 키 (예: "my_character")
            new_value: 새 값

        Returns:
            bool: 성공 여부
        """
        # file_key에 .json 붙이기
        filename = f"{file_key}.json"

        if filename not in self.json_data:
            print(f"⚠️ 파일을 찾을 수 없음: {filename}")
            return False

        if item_key not in self.json_data[filename]:
            print(f"⚠️ 키를 찾을 수 없음: {item_key}")
            return False

        try:
            # JSON 데이터 업데이트
            self.json_data[filename][item_key] = new_value

            # 파일에 저장
            filepath = self.save_path / filename
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self.json_data[filename], f, ensure_ascii=False, indent=2)

            # 와일드카드 재로드
            self.load_all_wildcards()

            # UI 업데이트 (현재 선택된 항목이었다면)
            if self.current_file == filename and self.current_key == item_key:
                self.value_edit.setPlainText(new_value)

            print(f"✅ 와일드카드 값 업데이트됨: {file_key}::{item_key}")
            return True

        except Exception as e:
            print(f"⚠️ 와일드카드 값 업데이트 실패: {e}")
            return False
