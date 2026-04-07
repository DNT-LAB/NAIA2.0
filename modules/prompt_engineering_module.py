from PyQt6.QtWidgets import QVBoxLayout, QLabel, QWidget, QTextEdit, QCheckBox, QHBoxLayout, QComboBox, QPushButton, QDialog, QGridLayout, QLineEdit, QMessageBox, QListWidget, QListWidgetItem, QDialogButtonBox, QInputDialog, QSplitter, QSizePolicy, QApplication, QTabWidget
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer, QMimeData, QEvent
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QImage, QClipboard, QDoubleValidator
from interfaces.base_module import BaseMiddleModule
from core.prompt_context import PromptContext
from interfaces.mode_aware_module import ModeAwareModule
from ui.theme import get_dynamic_styles, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.modern_menu import setModernStyle
from typing import Dict, Any, Optional
from core.wildcard_processor import split_tags_smart
from core.tag_filter_helpers import _is_color_exception, apply_tag_filters
import os, json, re
from pathlib import Path

# 인원 태그 — 가중치/필터에서 공통 스킵 대상
_PERSON_TAGS = frozenset({
    "1boy","2boys","3boys","4boys","5boys","6+boys",
    "1girl","2girls","3girls","4girls","5girls","6+girls",
    "1other","2others","3others","4others","5others","6+others",
})

# 가중치 포맷 감지 패턴 (NAI: '1.05::tag ::', WEBUI: '(tag:1.05)')
_WEIGHT_NAI_DETECT = re.compile(r'^[\d.]+::.*::$')
_WEIGHT_WEBUI_DETECT = re.compile(r'^\(.*:[\d.]+\)$')

class PresetPreviewWidget(QWidget):
    """프리셋 이미지 미리보기 위젯 - 클립보드 지원"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self.preset_name = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(f"background-color: {DARK_COLORS['bg_secondary']};")
        
        # 클립보드 붙여넣기 지원
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
    
    def set_preset_name(self, preset_name: str):
        """현재 프리셋 이름 설정"""
        self.preset_name = preset_name
        self.load_preview_image()
    
    def load_preview_image(self):
        """프리셋 미리보기 이미지 로드"""
        if not self.preset_name:
            self._pixmap = None
            self.update()
            return
        
        # 이미지 파일 경로
        image_path = Path("save") / "presets" / "previews" / f"{self.preset_name}.png"
        if image_path.exists():
            self._pixmap = QPixmap(str(image_path))
        else:
            self._pixmap = None
        self.update()
    
    def save_preview_image(self):
        """현재 이미지를 프리셋 미리보기로 저장"""
        if not self._pixmap or not self.preset_name:
            return
        
        # previews 디렉토리 생성
        preview_dir = Path("save") / "presets" / "previews"
        preview_dir.mkdir(parents=True, exist_ok=True)
        
        # 이미지 저장
        image_path = preview_dir / f"{self.preset_name}.png"
        self._pixmap.save(str(image_path), "PNG")
        print(f"🖼️ 프리셋 미리보기 이미지 저장: {self.preset_name}")
    
    def clear_preview(self):
        """프리뷰 클리어"""
        self._pixmap = None
        self.preset_name = None
        self.update()
    
    def keyPressEvent(self, event):
        """Ctrl+V로 클립보드 이미지 붙여넣기"""
        if event.key() == Qt.Key.Key_V and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self.paste_from_clipboard()
    
    def paste_from_clipboard(self):
        """클립보드에서 이미지 붙여넣기"""
        clipboard = QApplication.clipboard()
        mimeData = clipboard.mimeData()
        
        if mimeData.hasImage():
            image = clipboard.image()
            if not image.isNull():
                self._pixmap = QPixmap.fromImage(image)
                self.update()
                # 자동 저장
                if self.preset_name:
                    self.save_preview_image()
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
            text = "프리셋 미리보기 이미지\n\n클릭 후 Ctrl+V로\n이미지를 붙여넣으세요"
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
        painter.end()
    
    def mousePressEvent(self, event):
        """클릭 시 포커스 설정 (Ctrl+V 받기 위함)"""
        self.setFocus()
        super().mousePressEvent(event)

class PromptEngineeringModule(BaseMiddleModule, ModeAwareModule):
    """
    🔧 프롬프트 엔지니어링/자동화 모듈
    선행/후행 프롬프트 추가, 태그 제거 등 프롬프트 엔지니어링 로직을 담당합니다.
    '파이프라인 훅' 시스템을 통해 PromptProcessor의 처리 과정에 직접 개입합니다.
    """

    class _E621AfterWildcardHook:
        """after_wildcard hook 위임 객체.
        와일드카드 단독 모드 + e621 Auto-Boost 동시 사용 시에만 작동.
        전개된 prefix_tags를 e621 입력으로 사용하여 main_tags에 추가."""

        def __init__(self, parent: 'PromptEngineeringModule'):
            self._parent = parent

        def get_title(self):
            return "e621 Auto-Boost (after_wildcard)"

        def execute_pipeline_hook(self, context):
            return self._parent._execute_e621_after_wildcard(context)

    class _DanbooruAfterWildcardHook:
        """after_wildcard hook 위임 객체.
        와일드카드 단독 모드 + Danbooru Auto-Weight 동시 사용 시에만 작동.
        전개된 prefix_tags에 가중치를 in-place 적용."""

        def __init__(self, parent: 'PromptEngineeringModule'):
            self._parent = parent

        def get_title(self):
            return "Danbooru Auto-Weight (after_wildcard)"

        def execute_pipeline_hook(self, context):
            return self._parent._execute_danbooru_weight_after_wildcard(context)

    def __init__(self):
        BaseMiddleModule.__init__(self)
        ModeAwareModule.__init__(self)
        self.start_expanded = True

        # 🆕 ModeAwareModule 필수 속성들
        self.settings_base_filename = "PromptEngineeringModule"
        self.current_mode = "NAI"
        
        # 🆕 필수 호환성 플래그 추가
        self.NAI_compatibility = True
        self.WEBUI_compatibility = True
        self.COMFYUI_compatibility = True
        
        # UI 위젯들을 저장할 인스턴스 변수 초기화
        self.pre_textedit = None
        self.post_textedit = None
        self.auto_hide_textedit = None
        self.auto_hide_toggle_btn = None
        self.auto_hide_collapsed = False
        self.preprocessing_checkboxes = {}
        self._debug_window = None
        self._e621_settings_window = None
        self._e621_settings = self._load_e621_settings()
        self._danbooru_weight_settings_window = None
        self._danbooru_weight_settings = self._load_danbooru_weight_settings()
        self._danbooru_tag_counts = None  # lazy-load cache
        self._danbooru_rating_totals = [1, 1, 1, 1]  # [g, s, q, e] — _get_danbooru_tag_counts()에서 설정

        # 기존 설정 파일 경로 유지
        self.settings_file = os.path.join('save', 'PromptEngineeringModule.json')

        # 파라미터 key로 사용할 영문명 매핑
        self.option_key_map = {
            "랜덤 프롬프트의 작가명을 제거": "remove_author",
            "랜덤 프롬프트의 작품명을 제거": "remove_work_title",
            "랜덤 프롬프트의 캐릭터명을 제거": "remove_character_name",
            "랜덤 프롬프트의 캐릭터 특징을 제거": "remove_character_features",
            "랜덤 프롬프트의 의류 태그를 제거": "remove_clothes",
            "랜덤 프롬프트의 색상포함 태그를 제거": "remove_color",
            "랜덤 프롬프트의 장소와 배경색을 제거": "remove_location_and_background_color",
            "랜덤 프롬프트의 표정 태그를 제거": "remove_expression",
            "랜덤 프롬프트의 포즈/행동 태그를 제거": "remove_pose_action",
            "랜덤 프롬프트의 메타 태그를 제거": "remove_meta_tags",
            "랜덤 프롬프트의 사물 태그를 제거": "remove_object_tags",
            "랜덤 프롬프트의 저빈도 태그를 제거": "remove_noise_tags",
            "e621 Auto-Boost": "e621_auto_boost",
            "Danbooru Auto-Weight": "danbooru_auto_weight",
            "태그 함축 압축 (Implication)": "tag_implication_compression",
        }
        
        # 퀵 프리셋 관련 초기화
        self.preset_combo = None
        self.preset_add_btn = None  # 퀵 프리셋 "추가" 버튼
        self.current_preset = "default"
        self.last_preset = "default"
        self.preset_list = []

        # *randomized 모드 관련
        self.is_randomized_mode = False
        self.randomized_preset_list = []  # ListBox에 표시될 프리셋 목록

        # *randomized UI 위젯 참조
        self.randomized_layout_widget = None  # randomized 전용 UI 컨테이너
        self.randomized_listbox = None  # QListWidget
        self.randomized_combo = None  # 프리셋 선택 복제 콤보박스
        self.randomized_add_btn = None  # [추가] 버튼
        self.randomized_remove_btn = None  # [제거] 버튼

    def get_title(self) -> str:
        return "🔧 프롬프트 엔지니어링/자동화/프리셋"

    def get_order(self) -> int:
        return 0
    
    def get_module_name(self) -> str:
        """ModeAwareModule 인터페이스 구현"""
        return self.get_title()
    
    def collect_current_settings(self) -> Dict[str, Any]:
        """현재 UI 상태에서 설정 수집"""
        if not all([self.pre_textedit, self.post_textedit, self.auto_hide_textedit]):
            return {}

        settings = {
            "pre_prompt": self.pre_textedit.toPlainText(),
            "post_prompt": self.post_textedit.toPlainText(),
            "auto_hide_prompt": self.auto_hide_textedit.toPlainText(),
            "auto_hide_collapsed": self.auto_hide_collapsed,
            "preprocessing_options": {
                self.option_key_map.get(text): cb.isChecked()
                for text, cb in self.preprocessing_checkboxes.items()
            },
            "e621_settings": self._e621_settings,
            "danbooru_weight_settings": self._danbooru_weight_settings,
        }
        return settings
    
    def apply_settings(self, settings: Dict[str, Any]):
        """설정을 UI에 적용"""
        if not all([self.pre_textedit, self.post_textedit, self.auto_hide_textedit]):
            print("    ⚠️ UI 위젯이 아직 준비되지 않음")
            return

        print(f"    - 모듈 설정 적용:")
        
        # 텍스트 설정 적용
        pre_prompt = settings.get("pre_prompt", "")
        post_prompt = settings.get("post_prompt", "")
        auto_hide = settings.get("auto_hide_prompt", "")
        
        print(f"      pre_prompt 길이: {len(pre_prompt)}")
        print(f"      post_prompt 길이: {len(post_prompt)}")
        print(f"      auto_hide 길이: {len(auto_hide)}")
        
        self.pre_textedit.setText(pre_prompt)
        self.post_textedit.setText(post_prompt)
        self.auto_hide_textedit.setText(auto_hide)

        # 자동 숨김 프롬프트 접기 상태 적용
        collapsed = settings.get("auto_hide_collapsed", False)
        self._set_auto_hide_collapsed(collapsed)

        # 체크박스 설정 적용
        options = settings.get("preprocessing_options", {})
        print(f"      preprocessing_options: {options}")
        
        for text, cb in self.preprocessing_checkboxes.items():
            key = self.option_key_map.get(text)
            if key in options:
                cb.setChecked(options[key])
                print(f"      체크박스 '{text}' = {options[key]}")

        # e621 설정 복원
        e621 = settings.get("e621_settings")
        if e621:
            self._e621_settings = e621
            self._save_e621_settings()

        # danbooru weight 설정 복원
        dw = settings.get("danbooru_weight_settings")
        if dw:
            self._danbooru_weight_settings = dw
            self._save_danbooru_weight_settings()
    
    # 🆕 누락된 메서드 추가
    def initialize_with_context(self, context):
        """AppContext와 연결"""
        self.context = context  # 기존 코드에서 사용하는 self.context 유지
        self.app_context = context  # 새로운 모드 시스템용

        # 랜덤 프리셋 선택용 신호 구독
        if self.app_context:
            self.app_context.subscribe("random_prompt_triggered", self._on_random_prompt_triggered)
            self.app_context.subscribe("random_prompt_triggered_preset_randomizer", self._on_random_prompt_triggered)
    
    def create_widget(self, parent: QWidget) -> QWidget:
        # after_wildcard hook 등록 (와일드카드 단독 + e621 동시 사용 대응)
        if hasattr(self, 'app_context') and self.app_context:
            self.app_context.register_pipeline_hook(
                {'target_pipeline': 'PromptProcessor', 'hook_point': 'after_wildcard', 'priority': 10},
                self._E621AfterWildcardHook(self),
            )
            self.app_context.register_pipeline_hook(
                {'target_pipeline': 'PromptProcessor', 'hook_point': 'after_wildcard', 'priority': 15},
                self._DanbooruAfterWildcardHook(self),
            )

        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        layout.setSpacing(6)

        # 동적 스타일 가져오기
        dynamic_styles = get_dynamic_styles()
        
        # 퀵 프리셋 UI 추가
        preset_layout = QHBoxLayout()
        preset_layout.setSpacing(4)
        
        preset_label = QLabel("퀵 프리셋:")
        preset_label.setStyleSheet(dynamic_styles['label_style'])
        preset_label.setFixedWidth(100)
        preset_layout.addWidget(preset_label)
        
        self.preset_combo = QComboBox()
        self.preset_combo.setStyleSheet(dynamic_styles['compact_combobox'])
        self.preset_combo.addItem("(프리셋 없음)")  # 초기 플레이스홀더
        self.preset_combo.currentTextChanged.connect(self.on_preset_changed)
        # 마우스 휠로 값이 변경되지 않도록 설정
        self.preset_combo.wheelEvent = lambda e: e.ignore()
        preset_layout.addWidget(self.preset_combo, 1)
        
        self.preset_add_btn = QPushButton("추가")
        self.preset_add_btn.setStyleSheet(dynamic_styles['compact_button'])
        self.preset_add_btn.setFixedWidth(80)
        self.preset_add_btn.clicked.connect(self.add_preset)
        preset_layout.addWidget(self.preset_add_btn)
        
        manage_btn = QPushButton("관리")
        manage_btn.setStyleSheet(dynamic_styles['compact_button'])
        manage_btn.setFixedWidth(80)
        manage_btn.clicked.connect(self.manage_presets)
        preset_layout.addWidget(manage_btn)
        
        layout.addLayout(preset_layout)

        # === *randomized 전용 UI 레이아웃 ===
        self.randomized_layout_widget = QWidget()
        randomized_layout = QVBoxLayout(self.randomized_layout_widget)
        randomized_layout.setContentsMargins(0, 5, 0, 5)
        randomized_layout.setSpacing(4)

        # 1) 랜덤 프리셋 목록 Label
        randomized_label = QLabel("랜덤 프리셋 목록:")
        randomized_label.setStyleSheet(dynamic_styles['label_style'])
        randomized_layout.addWidget(randomized_label)

        # 2) 랜덤 프리셋 목록 ListBox
        self.randomized_listbox = QListWidget()
        self.randomized_listbox.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.randomized_listbox.setFixedHeight(100)
        self.randomized_listbox.setStyleSheet(f"""
            QListWidget {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                padding: 4px;
                font-size: {get_scaled_font_size(14)}px;
            }}
            QListWidget::item {{
                padding: 3px;
            }}
            QListWidget::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
            }}
        """)
        randomized_layout.addWidget(self.randomized_listbox)

        # ListBox 아이템 클릭 시 해당 프리셋 로드
        self.randomized_listbox.itemClicked.connect(self._on_randomized_listbox_item_clicked)

        # 3) 프리셋 선택 + 버튼 행
        selection_layout = QHBoxLayout()
        selection_layout.setSpacing(4)

        # "선택:" Label 추가
        selection_label = QLabel("선택:")
        selection_label.setStyleSheet(dynamic_styles['label_style'])
        selection_label.setFixedWidth(60)
        selection_layout.addWidget(selection_label)

        self.randomized_combo = QComboBox()
        self.randomized_combo.setStyleSheet(dynamic_styles['compact_combobox'])
        self.randomized_combo.wheelEvent = lambda e: e.ignore()
        self.randomized_combo.setMinimumWidth(150)
        self.randomized_combo.currentTextChanged.connect(self._on_randomized_combo_changed)
        selection_layout.addWidget(self.randomized_combo, 1)

        self.randomized_add_btn = QPushButton("+추가")
        self.randomized_add_btn.setStyleSheet(dynamic_styles['compact_button'])
        self.randomized_add_btn.setFixedWidth(70)
        self.randomized_add_btn.clicked.connect(self._add_to_randomized_list)
        selection_layout.addWidget(self.randomized_add_btn)

        self.randomized_remove_btn = QPushButton("-제거")
        self.randomized_remove_btn.setStyleSheet(dynamic_styles['compact_button'])
        self.randomized_remove_btn.setFixedWidth(70)
        self.randomized_remove_btn.clicked.connect(self._remove_from_randomized_list)
        selection_layout.addWidget(self.randomized_remove_btn)

        randomized_layout.addLayout(selection_layout)

        self.randomized_layout_widget.setVisible(False)  # 초기 숨김
        layout.addWidget(self.randomized_layout_widget)

        # 선행 고정 프롬프트
        pre_label = QLabel("선행 고정 프롬프트:")
        pre_label.setStyleSheet(dynamic_styles['label_style'])
        layout.addWidget(pre_label)

        self.pre_textedit = QTextEdit()
        self.pre_textedit.setAcceptRichText(False)  # 서식 붙여넣기 차단
        self.pre_textedit.setFixedHeight(160)
        self.pre_textedit.setStyleSheet(dynamic_styles['compact_textedit'])
        setModernStyle(self.pre_textedit)
        layout.addWidget(self.pre_textedit)

        # 후행 고정 프롬프트
        post_label = QLabel("후행 고정 프롬프트:")
        post_label.setStyleSheet(dynamic_styles['label_style'])
        layout.addWidget(post_label)

        self.post_textedit = QTextEdit()
        self.post_textedit.setAcceptRichText(False)  # 서식 붙여넣기 차단
        self.post_textedit.setFixedHeight(160)
        self.post_textedit.setStyleSheet(dynamic_styles['compact_textedit'])
        setModernStyle(self.post_textedit)
        layout.addWidget(self.post_textedit)

        # 자동 숨김 프롬프트 (접기/펼치기)
        auto_hide_header = QHBoxLayout()
        auto_hide_header.setSpacing(4)
        auto_hide_label = QLabel("자동 숨김 프롬프트:")
        auto_hide_label.setStyleSheet(dynamic_styles['label_style'])
        auto_hide_header.addWidget(auto_hide_label)
        auto_hide_header.addStretch()
        self.auto_hide_toggle_btn = QPushButton("접기")
        self.auto_hide_toggle_btn.setFixedSize(get_scaled_size(50), get_scaled_size(20))
        self.auto_hide_toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                font-size: {get_scaled_font_size(11)}px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        self.auto_hide_toggle_btn.clicked.connect(self._toggle_auto_hide)
        auto_hide_header.addWidget(self.auto_hide_toggle_btn)
        layout.addLayout(auto_hide_header)

        self.auto_hide_textedit = QTextEdit()
        self.auto_hide_textedit.setAcceptRichText(False)  # 서식 붙여넣기 차단
        self.auto_hide_textedit.setFixedHeight(160)
        self.auto_hide_textedit.setStyleSheet(dynamic_styles['compact_textedit'])
        setModernStyle(self.auto_hide_textedit)
        layout.addWidget(self.auto_hide_textedit)

        # 프롬프트 전처리 옵션들 (2단 그리드)
        preprocessing_header = QHBoxLayout()
        preprocessing_header.setSpacing(4)
        preprocessing_label = QLabel("프롬프트 전처리 옵션:")
        preprocessing_label.setStyleSheet(dynamic_styles['label_style'])
        preprocessing_header.addWidget(preprocessing_label)
        preprocessing_header.addStretch()
        self.debug_window_btn = QPushButton("디버깅 윈도우")
        self.debug_window_btn.setFixedSize(get_scaled_size(90), get_scaled_size(20))
        self.debug_window_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                font-size: {get_scaled_font_size(11)}px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        self.debug_window_btn.clicked.connect(self._open_debug_window)
        preprocessing_header.addWidget(self.debug_window_btn)
        layout.addLayout(preprocessing_header)

        # 연노랑색 체크박스 스타일 (작가명/작품명/캐릭터명용) — dark_checkbox 기반, 색상만 변경
        yellow_checkbox_style = dynamic_styles['dark_checkbox'].replace(
            f"color: {DARK_COLORS['text_primary']};",
            "color: #FFFACD;",
            1
        )

        checkbox_grid = QGridLayout()
        checkbox_grid.setSpacing(get_scaled_size(4))
        checkbox_grid.setContentsMargins(0, 0, 0, 0)
        # 연분홍색 체크박스 스타일 (실험적 기능용)
        pink_checkbox_style = dynamic_styles['dark_checkbox'].replace(
            f"color: {DARK_COLORS['text_primary']};",
            "color: #FFD1DC;",
            1
        )
        # 연청록색 체크박스 스타일 (Danbooru Auto-Weight용)
        teal_checkbox_style = dynamic_styles['dark_checkbox'].replace(
            f"color: {DARK_COLORS['text_primary']};",
            "color: #B2DFDB;",
            1
        )

        # 첫 3개(작가명/작품명/캐릭터명)는 연노랑색
        yellow_keys = {"remove_author", "remove_work_title", "remove_character_name"}
        pink_keys = {"e621_auto_boost"}
        teal_keys = {"danbooru_auto_weight", "tag_implication_compression"}
        # 설정 버튼이 필요한 항목 — 셀 내 HBoxLayout(체크박스 + 버튼)으로 배치
        _settings_btn_map = {
            "e621_auto_boost":       ("#FFD1DC", self._open_e621_settings),
            "danbooru_auto_weight":  ("#B2DFDB", self._open_danbooru_weight_settings),
        }
        for i, text in enumerate(self.option_key_map.keys()):
            cb = QCheckBox(text)
            key = self.option_key_map[text]
            if key in yellow_keys:
                cb.setStyleSheet(yellow_checkbox_style)
            elif key in pink_keys:
                cb.setStyleSheet(pink_checkbox_style)
            elif key in teal_keys:
                cb.setStyleSheet(teal_checkbox_style)
            else:
                cb.setStyleSheet(dynamic_styles['dark_checkbox'])
            row = i // 2
            col = i % 2
            if key in _settings_btn_map:
                color, handler = _settings_btn_map[key]
                cell_layout = QHBoxLayout()
                cell_layout.setSpacing(get_scaled_size(4))
                cell_layout.setContentsMargins(0, 0, 0, 0)
                cell_layout.addWidget(cb)
                settings_btn = QPushButton("설정")
                settings_btn.setFixedHeight(get_scaled_size(20))
                settings_btn.setFixedWidth(get_scaled_size(36))
                settings_btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: transparent;
                        color: {color};
                        border: 1px solid {color};
                        border-radius: {get_scaled_size(3)}px;
                        font-size: {get_scaled_font_size(10)}px;
                        padding: 0px;
                    }}
                    QPushButton:hover {{
                        background-color: {DARK_COLORS['bg_hover']};
                    }}
                """)
                settings_btn.clicked.connect(handler)
                cell_layout.addWidget(settings_btn)
                cell_layout.addStretch()
                checkbox_grid.addLayout(cell_layout, row, col)
            else:
                checkbox_grid.addWidget(cb, row, col)
            self.preprocessing_checkboxes[text] = cb
        layout.addLayout(checkbox_grid)

        # 🆕 생성된 위젯 저장 (가시성 제어용)
        self.widget = widget
        
        # 🆕 현재 모드에 따른 가시성 설정
        if hasattr(self, 'app_context') and self.app_context:
            current_mode = self.app_context.get_api_mode()
            should_be_visible = (
                (current_mode == "NAI" and self.NAI_compatibility) or
                (current_mode == "WEBUI" and self.WEBUI_compatibility)
            )
            widget.setVisible(should_be_visible)

        return widget

    def _toggle_auto_hide(self):
        """자동 숨김 프롬프트 접기/펼치기 토글"""
        self._set_auto_hide_collapsed(not self.auto_hide_collapsed)

    def _set_auto_hide_collapsed(self, collapsed: bool):
        """자동 숨김 프롬프트 접기 상태 설정"""
        self.auto_hide_collapsed = collapsed
        if self.auto_hide_textedit:
            self.auto_hide_textedit.setVisible(not collapsed)
        if self.auto_hide_toggle_btn:
            self.auto_hide_toggle_btn.setText("펼치기" if collapsed else "접기")

    def _open_debug_window(self):
        """전처리 디버깅 윈도우 열기"""
        from modules.filter_debug_window import FilterDebugWindow

        # C/C++ 삭제 안전 처리
        try:
            if self._debug_window is not None:
                self._debug_window.isVisible()
        except RuntimeError:
            self._debug_window = None

        if self._debug_window is None:
            self._debug_window = FilterDebugWindow(self.widget)

        self._debug_window.show()
        self._debug_window.raise_()
        self._debug_window.activateWindow()

    # ─── e621 설정 관리 ───────────────────────────────────────
    _E621_SETTINGS_FILE = os.path.join('save', 'e621_boost_user.json')

    def _load_e621_settings(self) -> dict:
        """e621 사용자 설정 로드"""
        try:
            with open(self._E621_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"weight": 0.0, "hidden_tags": [], "mode": "stable"}

    def _save_e621_settings(self):
        """e621 사용자 설정 저장"""
        os.makedirs(os.path.dirname(self._E621_SETTINGS_FILE), exist_ok=True)
        with open(self._E621_SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(self._e621_settings, f, ensure_ascii=False, indent=2)

    def _open_e621_settings(self):
        """e621 설정 윈도우 열기 (비모달)"""
        # C/C++ 삭제 안전 처리
        try:
            if self._e621_settings_window is not None:
                self._e621_settings_window.isVisible()
        except RuntimeError:
            self._e621_settings_window = None

        if self._e621_settings_window is None:
            self._e621_settings_window = _E621SettingsWindow(self._e621_settings, parent=self.widget)
            self._e621_settings_window.settings_changed.connect(self._on_e621_settings_changed)

        self._e621_settings_window.load_settings(self._e621_settings)
        self._e621_settings_window.show()
        self._e621_settings_window.raise_()
        self._e621_settings_window.activateWindow()

    def _on_e621_settings_changed(self, settings: dict):
        """e621 설정 윈도우에서 저장 시 호출"""
        self._e621_settings = settings
        self._save_e621_settings()

    # ─── Danbooru Auto-Weight 설정 관리 ─────────────────────────
    _DANBOORU_WEIGHT_SETTINGS_FILE = os.path.join('save', 'danbooru_auto_weight_user.json')

    def _load_danbooru_weight_settings(self) -> dict:
        try:
            with open(self._DANBOORU_WEIGHT_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"magnitude": 3}

    def _save_danbooru_weight_settings(self):
        os.makedirs(os.path.dirname(self._DANBOORU_WEIGHT_SETTINGS_FILE), exist_ok=True)
        with open(self._DANBOORU_WEIGHT_SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(self._danbooru_weight_settings, f, ensure_ascii=False, indent=2)

    def _open_danbooru_weight_settings(self):
        try:
            if self._danbooru_weight_settings_window is not None:
                self._danbooru_weight_settings_window.isVisible()
        except RuntimeError:
            self._danbooru_weight_settings_window = None

        if self._danbooru_weight_settings_window is None:
            self._danbooru_weight_settings_window = _DanbooruWeightSettingsWindow(
                self._danbooru_weight_settings, parent=self.widget, module=self
            )
            self._danbooru_weight_settings_window.settings_changed.connect(self._on_danbooru_weight_settings_changed)

        self._danbooru_weight_settings_window.load_settings(self._danbooru_weight_settings)
        self._danbooru_weight_settings_window.show()
        self._danbooru_weight_settings_window.raise_()
        self._danbooru_weight_settings_window.activateWindow()

    def _on_danbooru_weight_settings_changed(self, settings: dict):
        self._danbooru_weight_settings = settings
        self._save_danbooru_weight_settings()

    # Rating → 인덱스 매핑 (danbooru_tag_counts_by_rating.json의 partition_order와 일치)
    _RATING_INDEX = {"g": 0, "s": 1, "q": 2, "e": 3}
    # 정규화 클리핑 범위 (클래스 상수 — 설정 윈도우에서도 참조)
    _danbooru_norm_low_default = 1.0
    _danbooru_norm_high_default = 10.0
    # Magnitude 레벨 → (min_w, max_w, scale) 매핑 (10단계, 앵커 보간)
    _DANBOORU_MAGNITUDE_TABLE = {
        1:  {"min_weight": 0.88, "max_weight": 1.15, "scale": 0.15, "label": "약한"},
        2:  {"min_weight": 0.84, "max_weight": 1.25, "scale": 0.25, "label": "중간"},
        3:  {"min_weight": 0.80, "max_weight": 1.35, "scale": 0.35, "label": "추천"},
        4:  {"min_weight": 0.75, "max_weight": 1.42, "scale": 0.42, "label": "강한"},
        5:  {"min_weight": 0.70, "max_weight": 1.50, "scale": 0.50, "label": "최대"},
        6:  {"min_weight": 0.62, "max_weight": 1.60, "scale": 0.60, "label": "최대+"},
        7:  {"min_weight": 0.55, "max_weight": 1.70, "scale": 0.70, "label": "최대++"},
        8:  {"min_weight": 0.50, "max_weight": 1.80, "scale": 0.80, "label": "극한"},
        9:  {"min_weight": 0.45, "max_weight": 1.90, "scale": 0.90, "label": "극한+"},
        10: {"min_weight": 0.40, "max_weight": 2.00, "scale": 1.00, "label": "극한++"},
    }

    def _get_danbooru_tag_counts(self) -> dict:
        """Rating 조건부 태그 빈도 데이터 로드 + 전역 IDF 범위 사전 계산 (lazy, 1회만)"""
        if self._danbooru_tag_counts is not None:
            return self._danbooru_tag_counts
        import math
        path = Path(__file__).resolve().parent.parent / "data" / "danbooru_tag_counts_by_rating.json"
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        meta = data.pop("_meta")
        self._danbooru_rating_totals = meta["total_posts"]  # [g, s, q, e]
        self._danbooru_tag_counts = data  # {tag: [g, s, q, e]}

        # 전역 IDF 범위 사전 계산 (정규화 기준)
        global_total = sum(self._danbooru_rating_totals)
        global_idfs = {}
        for tag, counts in data.items():
            gc = sum(counts)
            if gc > 0:
                global_idfs[tag] = -math.log2(gc / global_total)
        self._danbooru_global_idfs = global_idfs
        # 정규화 범위: 실용 태그 대역 (IDF 1~10) 으로 클리핑
        self._danbooru_norm_low = self._danbooru_norm_low_default
        self._danbooru_norm_high = self._danbooru_norm_high_default
        self._danbooru_global_total = global_total
        print(f"[Danbooru Auto-Weight] loaded {len(data):,} tags, "
              f"norm range: {self._danbooru_norm_low}~{self._danbooru_norm_high}")
        return self._danbooru_tag_counts

    # Rating 보정 블렌드 비율 (0=전역만, 1=rating만)
    _RATING_BLEND = 0.3

    @staticmethod
    def _strip_weight_syntax(tag: str) -> str:
        """태그에서 가중치 래핑 구문을 제거하여 순수 태그명만 반환.
        NAI: '1.20::tag ::' → 'tag'
        A1111/ComfyUI: '(tag:1.20)' → 'tag'
        """
        s = tag.strip()
        # NAI 형식 처리
        # 완전체: '0.89::tag ::' → 'tag'
        # 그룹 앞쪽: '1.05::tag1' (쉼표로 잘림) → 'tag1'
        # 그룹 뒤쪽: 'tag2 ::' (쉼표로 잘림) → 'tag2'
        if '::' in s:
            # 후행 '::' 먼저 제거
            if s.endswith('::'):
                s = s[:-2].strip()
            # 선행 'weight::' 제거
            if '::' in s:
                parts = s.split('::', 1)
                try:
                    float(parts[0].strip())
                    s = parts[1].strip()
                except ValueError:
                    pass
        # A1111/ComfyUI 형식: '(tag:weight)'
        if s.startswith('(') and s.endswith(')'):
            inner = s[1:-1]
            colon_idx = inner.rfind(':')
            if colon_idx > 0:
                try:
                    float(inner[colon_idx + 1:])
                    s = inner[:colon_idx].strip()
                except ValueError:
                    pass
        return s

    def _infer_rating_from_tags(self, tags: list) -> str:
        """태그 분포 기반 rating 추론 (와일드카드 단독 모드 전용).
        danbooru_tag_counts_by_rating.json의 per-rating 빈도를 사용하여
        Naive Bayes 방식으로 가장 높은 우도를 가진 rating을 반환.
        """
        import math

        if not tags:
            return 's'

        tag_counts = self._get_danbooru_tag_counts()
        totals = self._danbooru_rating_totals  # [g, s, q, e]
        vocab_size = len(tag_counts)

        # 로그 사전확률 (uniform — 편향 없이 시작)
        log_scores = [0.0, 0.0, 0.0, 0.0]  # g, s, q, e

        matched = 0
        for tag in tags:
            clean = self._strip_weight_syntax(tag)
            if clean in _PERSON_TAGS or clean not in tag_counts:
                continue
            counts = tag_counts[clean]
            matched += 1
            for ri in range(4):
                # Laplace smoothing: (count + 1) / (total + V)
                prob = (counts[ri] + 1) / (totals[ri] + vocab_size)
                log_scores[ri] += math.log(prob)

        if matched < 3:
            return 's'  # 데이터 부족 — 보수적 기본값

        # 가장 높은 score의 rating 선택
        max_score = max(log_scores)
        rating_labels = ['g', 's', 'q', 'e']
        best_ri = log_scores.index(max_score)
        best_rating = rating_labels[best_ri]

        print(f"[Danbooru Auto-Weight] inferred rating='{best_rating}' "
              f"from {matched} tags (scores: "
              f"g={log_scores[0]-max_score:.1f}, s={log_scores[1]-max_score:.1f}, "
              f"q={log_scores[2]-max_score:.1f}, e={log_scores[3]-max_score:.1f})")
        return best_rating

    def _compress_implied_main_tags(self, main_tags: list) -> list:
        """main_tags에서 단어 부분집합 관계인 태그를 제거.
        예: 'pleated skirt'가 있으면 'skirt'는 함축되므로 제거.
        Returns: [{'removed': str, 'by': str}, ...] 제거된 태그와 근거."""
        entries = []
        for tag in main_tags:
            t = tag.strip()
            if t and not t.startswith('#'):
                entries.append((tag, set(t.split())))

        if len(entries) < 2:
            return []

        to_remove = {}  # tag_a -> tag_b (superset)
        for i, (tag_a, ws_a) in enumerate(entries):
            for j, (tag_b, ws_b) in enumerate(entries):
                if i != j and ws_a < ws_b:  # proper subset
                    to_remove[tag_a] = tag_b
                    break

        if not to_remove:
            return []

        result = [{'removed': k, 'by': v} for k, v in sorted(to_remove.items())]
        main_tags[:] = [t for t in main_tags if t not in to_remove]
        print(f"[Implication] {len(result)}개 태그 압축: {[r['removed'] for r in result]}")
        return result

    def _apply_danbooru_auto_weight(self, main_tags: list, context: PromptContext, *, min_valid_count: int = 3):
        """전역 IDF + Rating 조건부 보정 블렌딩, 전역 범위 정규화 (main_tags in-place 수정)

        blended_idf = global_idf + α * (rating_idf - global_idf)
        norm = (blended_idf - global_min) / (global_max - global_min)   # 전역 범위 [0,1]
        weight = 1.0 + scale * (2*norm - 1)
        """
        import math

        try:
            tag_counts = self._get_danbooru_tag_counts()
        except Exception as e:
            print(f"⚠️ Danbooru Auto-Weight: 태그 데이터 로드 실패 — {e}")
            return

        settings = self._danbooru_weight_settings
        mag = settings.get("magnitude", 3)
        mag_params = self._DANBOORU_MAGNITUDE_TABLE.get(mag, self._DANBOORU_MAGNITUDE_TABLE[3])
        scale = mag_params["scale"]
        min_w = mag_params["min_weight"]
        max_w = mag_params["max_weight"]
        # 커스텀 오버라이드 적용
        if settings.get("override_on"):
            scale = settings.get("override_scale", scale)
            min_w = settings.get("override_min", min_w)
            max_w = settings.get("override_max", max_w)
        invert = settings.get("invert_weight", False)
        is_nai = context.settings.get('api_mode') == 'NAI'
        alpha = settings.get("rating_blend", self._RATING_BLEND)

        # Rating 조건부: 오버라이드 > source_row > 추론 > fallback
        if settings.get("rating_override_on") and settings.get("rating_override") in self._RATING_INDEX:
            rating = settings["rating_override"]
        else:
            _raw_rating = context.source_row.get('rating', None)
            # NaN/None/NaT 등 pandas missing 타입 모두 처리
            rating = str(_raw_rating).strip().lower() if _raw_rating is not None and _raw_rating == _raw_rating else None
            if rating not in self._RATING_INDEX:
                # 와일드카드 단독 모드: 태그에서 추론
                if context.settings.get('wildcard_standalone', False):
                    rating = self._infer_rating_from_tags(main_tags)
                else:
                    rating = 's'  # fallback
        ri = self._RATING_INDEX[rating]
        rating_total = max(self._danbooru_rating_totals[ri], 1)

        # 실용 대역 클리핑 정규화 범위 (IDF 1~10)
        n_low = self._danbooru_norm_low
        n_high = self._danbooru_norm_high
        n_range = n_high - n_low

        global_idfs = self._danbooru_global_idfs

        # 1단계: 각 태그의 블렌딩 IDF 계산
        blended_values = []
        valid_count = 0
        for tag in main_tags:
            clean = tag.strip()
            if clean in _PERSON_TAGS or clean not in tag_counts:
                blended_values.append(None)
                continue
            # 전역 IDF
            g_idf = global_idfs.get(clean)
            if g_idf is None:
                blended_values.append(None)
                continue
            # Rating 조건부 IDF
            r_count = tag_counts[clean][ri]
            if r_count > 0:
                r_idf = -math.log2(r_count / rating_total)
                blended = g_idf + alpha * (r_idf - g_idf)
            else:
                # 해당 rating에서 미출현 → 전역 IDF만 사용
                blended = g_idf
            blended_values.append(blended)
            valid_count += 1

        if valid_count < min_valid_count:
            print(f"[Danbooru Auto-Weight] skipped (valid tags={valid_count} < {min_valid_count})")
            return

        # 2단계: 전역 범위 정규화 → 가중치 계산 → 미세 섭동 → 래핑
        import random
        weighted_count = 0
        for idx, tag in enumerate(main_tags):
            bv = blended_values[idx]
            if bv is None:
                continue

            norm = max(0.0, min(1.0, (bv - n_low) / n_range))
            if invert:
                norm = 1.0 - norm
            weight = 1.0 + scale * (2 * norm - 1)
            weight = max(min_w, min(max_w, weight))

            if abs(weight - 1.0) < 0.01:
                continue

            # 미세 섭동: 85% 0~2%, 10% 2~5%, 4% 5~8%, 1% 8~10%
            # 각 구간 내에서도 하한 쪽에 편향 (beta 분포 α=1, β=3)
            r = random.random()
            if r < 0.85:
                jitter_mag = random.betavariate(1, 3) * 0.02
            elif r < 0.95:
                jitter_mag = 0.02 + random.betavariate(1, 3) * 0.03
            elif r < 0.99:
                jitter_mag = 0.05 + random.betavariate(1, 3) * 0.03
            else:
                jitter_mag = 0.08 + random.betavariate(1, 3) * 0.02
            jitter = jitter_mag * random.choice((-1, 1))
            weight = weight * (1.0 + jitter)
            weight = max(min_w, min(max_w, weight))

            clean = tag.strip()
            if is_nai:
                main_tags[idx] = f"{weight:.2f}::{clean} ::"
            else:
                main_tags[idx] = f"({clean}:{weight:.2f})"
            weighted_count += 1

        print(f"[Danbooru Auto-Weight] {weighted_count}/{valid_count} tags weighted "
              f"(rating={rating}, mag={mag} [{mag_params['label']}], {min_w}~{max_w})")

    def _run_e621_boost(self, context, input_tags: list, target_tags: list):
        """e621 추천을 실행하여 target_tags에 결과를 추가한다."""
        try:
            if not hasattr(self, '_e621_recommend'):
                import importlib.util
                _e621_file = Path(__file__).resolve().parent.parent / "data" / "e621_boost_static.py"
                _spec = importlib.util.spec_from_file_location("e621_boost_static", _e621_file)
                _mod = importlib.util.module_from_spec(_spec)
                _spec.loader.exec_module(_mod)
                self._e621_recommend = _mod.recommend_detailed
            recommend_detailed = self._e621_recommend
            boost_prompt = ", ".join(input_tags)
            print(f"[e621 DEBUG] input tags ({len(input_tags)}): {boost_prompt[:200]}{'...' if len(boost_prompt) > 200 else ''}")
            _mode = self._e621_settings.get("mode", "stable")
            boost_results = recommend_detailed(boost_prompt, top_n=15, diversity_cap=3, mode=_mode)
            print(f"[e621 DEBUG] results ({len(boost_results)}): {[(t, f'{s:.4f}', c) for t, s, c, src in boost_results]}")
            if boost_results:
                # 숨김 태그 필터링
                _hidden = set(self._e621_settings.get("hidden_tags", []))
                boost_tags = [tag.replace("_", " ") for tag, score, cat, src in boost_results
                              if tag not in _PERSON_TAGS and tag not in _hidden]
                # 가중치 래핑
                weight = self._e621_settings.get("weight", 0.0)
                if boost_tags and weight != 0:
                    is_nai = context.settings.get('api_mode') == 'NAI'
                    if is_nai:
                        boost_tags[0] = f"{weight}::" + boost_tags[0]
                        boost_tags[-1] = boost_tags[-1] + " ::"
                    else:
                        boost_tags[0] = "(" + boost_tags[0]
                        boost_tags[-1] = boost_tags[-1] + f":{weight})"
                target_tags.extend(boost_tags)
                context.metadata['e621_boost_tags'] = [
                    {"tag": tag, "score": score, "cat": cat, "src": src}
                    for tag, score, cat, src in boost_results
                ]
                context.metadata['e621_debug_info'] = {
                    'input_tags': input_tags,
                    'results': [
                        {"tag": tag, "score": score, "cat": cat, "src": src}
                        for tag, score, cat, src in boost_results
                    ],
                }
                main_window = getattr(self.app_context, 'main_window', None) if hasattr(self, 'app_context') and self.app_context else None
                if main_window and hasattr(main_window, 'main_prompt_highlighter'):
                    main_window.main_prompt_highlighter.set_e621_tags(set(boost_tags))
                print(f"🔥 e621 Auto-Boost: {len(boost_results)} tags added")
        except ImportError:
            print("⚠️ e621_boost_static not found — Auto-Boost skipped")
        except Exception as e:
            print(f"⚠️ e621 Auto-Boost error: {e}")

    def _execute_e621_after_wildcard(self, context) -> 'PromptContext':
        """after_wildcard hook: 와일드카드 단독 + e621 동시 사용 시에만 작동."""
        if '_e621_source_tags' not in context.metadata:
            return context
        _e621_source = context.metadata.pop('_e621_source_tags')
        _e621_input = list(context.prefix_tags) + _e621_source
        self._run_e621_boost(context, _e621_input, context.main_tags)
        self._update_debug_window(context.metadata)
        return context

    def _execute_danbooru_weight_after_wildcard(self, context) -> 'PromptContext':
        """after_wildcard hook (priority 15): 와일드카드 단독 + Danbooru Auto-Weight 동시 사용 시
        전개된 prefix_tags에 가중치를 in-place 적용. e621(priority 10) 이후에 실행.
        또한, 조건부 프롬프트 등이 main_tags에 추가한 미처리 태그에도 가중치 적용."""
        if '_danbooru_weight_deferred' not in context.metadata:
            # deferred가 아니어도 main_tags 미처리 태그 처리는 수행
            applied = context.metadata.get('_danbooru_weight_applied_tags')
            if applied is not None and context.main_tags:
                self._apply_weight_to_new_main_tags(context, applied)
            return context
        context.metadata.pop('_danbooru_weight_deferred')
        if context.prefix_tags:
            # __wildcard__ 전개 결과가 'tag1, tag2, tag3' 형태의 단일 문자열일 수 있음
            # 개별 태그로 분리하여 in-place 교체
            flat_tags = []
            for tag in context.prefix_tags:
                if ',' in tag:
                    flat_tags.extend(t.strip() for t in tag.split(',') if t.strip())
                else:
                    flat_tags.append(tag)
            context.prefix_tags[:] = flat_tags
            print(f"[Danbooru Auto-Weight] after_wildcard: applying to {len(context.prefix_tags)} prefix_tags")
            self._apply_danbooru_auto_weight(context.prefix_tags, context)
        # main_tags 미처리 태그에도 가중치 적용
        applied = context.metadata.get('_danbooru_weight_applied_tags')
        if applied is not None and context.main_tags:
            self._apply_weight_to_new_main_tags(context, applied)
        return context

    def _apply_weight_to_new_main_tags(self, context, applied_tags: set):
        """main_tags에서 Auto-Weight 미적용 raw 태그를 찾아 가중치 적용.
        이미 가중치 포맷, e621 그룹 래핑 태그는 스킵."""
        # e621 부스트 태그 수집 — 그룹 래핑 간섭 방지
        e621_tags = set()
        for item in context.metadata.get('e621_boost_tags', []):
            e621_tags.add(item['tag'].replace('_', ' '))

        new_tags = []
        in_e621_group = False
        for i, tag in enumerate(context.main_tags):
            clean = tag.strip()
            # 이미 가중치 포맷이면 스킵
            if _WEIGHT_NAI_DETECT.match(clean) or _WEIGHT_WEBUI_DETECT.match(clean):
                continue
            # e621 그룹 래핑 감지: '1.05::tag' (opening) ~ 'tag ::' (closing)
            if clean.endswith('::'):
                in_e621_group = False  # 그룹 종료
                continue
            if re.match(r'^[\d.]+::', clean):
                in_e621_group = True   # 그룹 시작
                continue
            if in_e621_group:
                continue               # 그룹 중간 태그
            # e621 부스트 태그면 스킵 (가중치 0인 경우 래핑 없이 추가됨)
            if clean in e621_tags:
                continue
            # 이미 post_processing에서 처리된 태그면 스킵
            if clean in applied_tags:
                continue
            new_tags.append(i)
        if not new_tags:
            return
        # 미처리 태그만 추출하여 가중치 적용
        temp_tags = [context.main_tags[i] for i in new_tags]
        print(f"[Danbooru Auto-Weight] after_wildcard: applying to {len(temp_tags)} new main_tags")
        self._apply_danbooru_auto_weight(temp_tags, context, min_valid_count=1)
        # 결과를 원래 위치에 반영
        for j, idx in enumerate(new_tags):
            context.main_tags[idx] = temp_tags[j]

    def _update_debug_window(self, metadata: dict):
        """디버그 윈도우가 열려있으면 새 데이터를 추가한다."""
        try:
            if self._debug_window is None or not self._debug_window.isVisible():
                return
        except RuntimeError:
            self._debug_window = None
            return

        filter_log = metadata.get('filter_log', [])
        source_info = metadata.get('debug_source_info', {})
        original = metadata.get('original_tag_count', 0)
        remaining = metadata.get('remaining_tag_count', 0)
        e621_info = metadata.get('e621_debug_info')
        impl_info = metadata.get('implication_compressed_tags')
        self._debug_window.add_entry(source_info, filter_log, original, remaining, e621_info, impl_info)

    def get_pipeline_hook_info(self) -> Dict[str, Any]:
        return {
            'target_pipeline': 'PromptProcessor',
            'hook_point': 'post_processing',
            'priority': 10
        }
    
    def execute_pipeline_hook(self, context: PromptContext) -> PromptContext:
        """기존 파이프라인 훅 로직 유지"""

        # 🆕 FR-3: 임시 창 프롬프트 생성 중에는 메인 UI 훅 건너뛰기
        if hasattr(self, 'app_context') and getattr(self.app_context, 'skip_prompt_engineering_hook', False):
            print("[DEBUG] 🚫 메인 PromptEngineeringModule 훅 건너뛰기 (임시 창 프롬프트 생성 중)")
            return context

        print("🔧 프롬프트 엔지니어링 훅 실행...")

        # Shared Server Mode: 세션 오버라이드 우선
        session_override = getattr(self.app_context, 'session_p_eng_override', None) if hasattr(self, 'app_context') else None
        if session_override is not None:
            # 빈 dict → 전부 빈 값으로 (데스크톱 폴백 방지)
            options = {
                "pre_prompt": split_tags_smart(session_override.get("pre_prompt", "")),
                "post_prompt": split_tags_smart(session_override.get("post_prompt", "")),
                "auto_hide": split_tags_smart(session_override.get("auto_hide", "")),
                "preprocessing_options": {},
            }
            # 전처리 옵션: 세션에 있으면 사용, 없으면 전부 OFF
            if "preprocessing_options" in session_override:
                options["preprocessing_options"] = session_override["preprocessing_options"]
        else:
            options = self.get_parameters()

        # 🆕 EZ Mode: 전처리 옵션 및 Auto Hide 건너뛰기 플래그 (선행/후행 프롬프트는 유지)
        skip_preprocessing = hasattr(self, 'app_context') and getattr(self.app_context, 'skip_prompt_engineering_auto_hide', False)

        # 메인UI의 전역 데이터 파이프라인에 접근
        filter_manager = self.context.filter_data_manager

        # 1. 선행/후행 프롬프트 추가
        _prefix_tags = options["pre_prompt"]
        _postfix_tags = options["post_prompt"]

        # context의 태그 리스트 앞/뒤에 추가
        prefix_tags = _prefix_tags + context.prefix_tags
        postfix_tags = context.postfix_tags + _postfix_tags
        main_tags = context.main_tags
        removed_tags = context.removed_tags
        source_row = context.source_row

        # 2. 자동 태그 제거 옵션 처리 (EZ Mode에서는 건너뛰기)
        if not skip_preprocessing:
            checkbox_options = options["preprocessing_options"]

            # 🆕 ANIMA 모드 감지 (6-part 프롬프트 구조)
            api_mode = context.settings.get('api_mode')
            sampling_mode = context.settings.get('comfyui_sampling_mode')
            is_anima_mode = (api_mode == 'COMFYUI' and sampling_mode == 'anima')

            # "remove_work_title"
            if not checkbox_options.get("remove_work_title"):
                copyright = source_row.get("copyright")
                if isinstance(copyright, str) and copyright:
                    if is_anima_mode:
                        # ANIMA: metadata에 저장 (나중에 위치 2에 배치)
                        context.metadata['anima_copyright'] = copyright
                    else:
                        # NAI/WEBUI: prefix_tags에 추가
                        prefix_tags.insert(0, copyright)

            # "remove_author"
            if not checkbox_options.get("remove_author"):
                artist = source_row.get("artist")
                if isinstance(artist, str) and artist:
                    if is_anima_mode:
                        # ANIMA: metadata에 저장 (나중에 위치 1에 배치)
                        context.metadata['anima_artist'] = artist
                    else:
                        # NAI/WEBUI: prefix_tags에 추가
                        prefix_tags.insert(0, artist)

            # "remove_character_name"
            if not checkbox_options.get("remove_character_name"):
                character = source_row.get("character")
                if isinstance(character, str) and character:
                    if is_anima_mode:
                        # ANIMA: metadata에 저장 (나중에 위치 3에 배치)
                        context.metadata['anima_character'] = character
                    else:
                        # NAI/WEBUI: prefix_tags에 추가
                        prefix_tags.insert(0, character)
        else:
            # EZ Mode: checkbox_options 초기화 (이후 코드에서 사용하지 않도록)
            checkbox_options = {}

        # 자동숨김프롬프트 처리 (EZ Mode에서는 건너뛰기)
        auto_hide = options["auto_hide"]

        if skip_preprocessing:
            print("[DEBUG] 🚫 전처리 옵션 및 Auto Hide 건너뛰기 (EZ Mode 즉시 생성)")
            auto_hide = []

        # 3. Auto Hide + 필터 체크박스 통합 처리 (공유 헬퍼)
        # e621 boost용 원본 태그 보존 (필터링 전 전체 맥락)
        _e621_source_tags = list(main_tags)
        original_count = len(main_tags)
        filter_result = apply_tag_filters(
            main_tags, removed_tags, checkbox_options, auto_hide,
            filter_manager, track_clothing_regions=True,
        )

        # 의류 Region 추적 결과를 metadata에 기록
        if filter_result.get('removed_clothes_by_region'):
            context.metadata['removed_clothes_by_region'] = filter_result['removed_clothes_by_region']

        # 디버그 윈도우용 데이터 수집
        if filter_result.get('filter_log'):
            context.metadata['filter_log'] = filter_result['filter_log']
            context.metadata['original_tag_count'] = original_count
            context.metadata['remaining_tag_count'] = len(main_tags)
        context.metadata['debug_source_info'] = {
            'character': source_row.get('character', ''),
            'copyright': source_row.get('copyright', ''),
            'artist': source_row.get('artist', ''),
            'id': source_row.get('id', ''),
        }
        # ★ Tag implication compression — Auto-Weight 이전에 처리
        if not skip_preprocessing and checkbox_options.get("tag_implication_compression"):
            compressed = self._compress_implied_main_tags(main_tags)
            if compressed:
                context.metadata['implication_compressed_tags'] = compressed

        # Danbooru Auto-Weight (e621 boost 전에 적용)
        _danbooru_weight_enabled = not skip_preprocessing and checkbox_options.get("danbooru_auto_weight")
        if _danbooru_weight_enabled:
            # 적용 전 raw 태그명 기록 (after_wildcard에서 미처리 태그 감지용)
            pre_weight_tags = {tag.strip() for tag in main_tags}
            self._apply_danbooru_auto_weight(main_tags, context)
            context.metadata['_danbooru_weight_applied_tags'] = pre_weight_tags
            _is_wildcard_standalone = context.settings.get('wildcard_standalone', False)
            if _is_wildcard_standalone:
                context.metadata['_danbooru_weight_deferred'] = True

        # e621 Auto-Boost
        _e621_enabled = not skip_preprocessing and checkbox_options.get("e621_auto_boost")
        _is_wildcard_standalone = context.settings.get('wildcard_standalone', False)

        if not _e621_enabled:
            # 비활성 시 하이라이팅 클리어
            main_window = getattr(self.app_context, 'main_window', None) if hasattr(self, 'app_context') and self.app_context else None
            if main_window and hasattr(main_window, 'main_prompt_highlighter') and main_window.main_prompt_highlighter._e621_tags:
                main_window.main_prompt_highlighter.set_e621_tags(set())
        elif _is_wildcard_standalone:
            # 와일드카드 단독 모드: after_wildcard hook에서 처리 (원본 태그 보존)
            context.metadata['_e621_source_tags'] = list(_e621_source_tags)
            print("[e621] 와일드카드 단독 모드 — after_wildcard에서 처리 예정")
        else:
            # 일반 모드: 여기서 즉시 처리
            self._run_e621_boost(context, list(prefix_tags) + _e621_source_tags, main_tags)

        self._update_debug_window(context.metadata)

        # 수정된 context를 다음 훅 또는 파이프라인으로 전달
        context.prefix_tags = prefix_tags
        context.postfix_tags = postfix_tags
        context.main_tags = main_tags

        return context

    def preprocess_prompt_turbo(self, prompt: str) -> str:
        # 메인UI의 전역 데이터 파이프라인에 접근
        filter_manager = None
        if hasattr(self, 'context') and self.context:
            filter_manager = getattr(self.context, 'filter_data_manager', None)

        # 메인 태그 파싱 (<...> 블록 보존)
        main_tags = split_tags_smart(prompt)
        removed_tags = []

        options = self.get_parameters()
        checkbox_options = options["preprocessing_options"]
        auto_hide = options["auto_hide"]

        # Auto Hide + 필터 체크박스 통합 처리 (공유 헬퍼)
        apply_tag_filters(main_tags, removed_tags, checkbox_options, auto_hide, filter_manager)

        # 최종 프롬프트 조합
        return ", ".join(main_tags)


    def preprocess_prompt(self, prompt: str, source_row: Optional[Dict[str, Any]] = None) -> str:
        """
        문자열을 받아서 현재 UI 설정에 따른 전처리만 수행하고 결과 문자열을 반환합니다.

        Args:
            prompt: 전처리할 프롬프트 문자열 (콤마로 구분된 태그들)
            source_row: 원본 데이터 (artist, copyright, character 등).
                       None이면 해당 태그 추가 로직은 건너뜀

        Returns:
            전처리된 프롬프트 문자열

        Example:
            >>> module = PromptEngineeringModule()
            >>> result = module.preprocess_prompt("1girl, blue hair, school uniform")
            >>> print(result)  # 현재 설정에 따라 필터링된 결과
        """
        if source_row is None:
            source_row = {}

        options = self.get_parameters()

        # 메인UI의 전역 데이터 파이프라인에 접근
        filter_manager = None
        if hasattr(self, 'context') and self.context:
            filter_manager = getattr(self.context, 'filter_data_manager', None)

        # 1. 선행/후행 프롬프트
        prefix_tags = options["pre_prompt"]
        postfix_tags = options["post_prompt"]

        # 메인 태그 파싱 (<...> 블록 보존)
        main_tags = split_tags_smart(prompt)
        removed_tags = []

        # 2. 자동 태그 제거 옵션 처리
        checkbox_options = options["preprocessing_options"]

        # "remove_work_title" - 제거 옵션이 꺼져있으면 copyright 추가
        if not checkbox_options.get("remove_work_title"):
            copyright_val = source_row.get("copyright")
            if isinstance(copyright_val, str) and copyright_val:
                prefix_tags = [copyright_val] + prefix_tags

        # "remove_author" - 제거 옵션이 꺼져있으면 artist 추가
        if not checkbox_options.get("remove_author"):
            artist = source_row.get("artist")
            if isinstance(artist, str) and artist:
                prefix_tags = [artist] + prefix_tags

        # "remove_character_name" - 제거 옵션이 꺼져있으면 character 추가
        if not checkbox_options.get("remove_character_name"):
            character = source_row.get("character")
            if isinstance(character, str) and character:
                prefix_tags = [character] + prefix_tags

        # 3. Auto Hide + 필터 체크박스 통합 처리 (공유 헬퍼)
        auto_hide = options["auto_hide"]
        apply_tag_filters(main_tags, removed_tags, checkbox_options, auto_hide, filter_manager)

        # 최종 프롬프트 조합
        final_tags = prefix_tags + main_tags + postfix_tags
        return ", ".join(final_tags)

    def get_parameters(self) -> Dict[str, Any]:
        """프롬프트 엔지니어링 모듈의 현재 파라미터를 수집하여 반환합니다."""
        # 각 체크박스의 상태를 수집
        options = {}
        for text, checkbox in self.preprocessing_checkboxes.items():
            key = self.option_key_map.get(text, text)
            options[key] = checkbox.isChecked()

        # 최종 파라미터 딕셔너리 구성
        params = {
            "pre_prompt": split_tags_smart(self.pre_textedit.toPlainText()),
            "post_prompt": split_tags_smart(self.post_textedit.toPlainText()),
            "auto_hide": split_tags_smart(self.auto_hide_textedit.toPlainText()),
            "preprocessing_options": options
        }
        return params

    def on_initialize(self):
        if hasattr(self, 'app_context') and self.app_context:
            print(f"✅ {self.get_title()}: AppContext 연결 완료")
            
            # 초기 가시성 설정
            current_mode = self.app_context.get_api_mode()
            if self.widget:
                self.update_visibility_for_mode(current_mode)
            
            # API 모드 변경 시그널 연결
            self.app_context.subscribe("api_mode_changed", self.on_api_mode_changed_preset)
            
        self.load_mode_settings()
        
        # 지연 초기화 - MainWindow가 완전히 초기화된 후 실행
        # 500ms 지연으로 충분한 초기화 시간 확보
        QTimer.singleShot(500, self.delayed_preset_initialization)
    
    # ==================== 퀵 프리셋 관련 메서드 ====================
    
    def delayed_preset_initialization(self):
        """MainWindow 초기화 완료 후 프리셋 초기화"""
        # 프리셋 목록 로드
        self.load_preset_list()
        
        # 마지막 사용한 프리셋 정보 로드
        last_used = self.load_last_used_preset_info()
        
        preset_dir = self.get_preset_dir()
        default_file = preset_dir / "default.json"
        
        # default 프리셋이 없으면 현재 UI 상태로 생성
        if not default_file.exists():
            # 현재 UI 상태를 default 프리셋으로 저장
            self.save_current_preset("default")
            print(f"📝 Default 프리셋을 현재 UI 상태로 생성했습니다.")
        
        # 사용할 프리셋 결정
        preset_to_load = None
        if last_used and last_used in self.preset_list:
            # 마지막 사용한 프리셋이 존재하면 그것을 사용
            preset_to_load = last_used
            print(f"📂 마지막 사용 프리셋 복원: {last_used}")
        elif "default" in self.preset_list:
            # 그렇지 않으면 default 사용
            preset_to_load = "default"
            print(f"📂 기본 프리셋 로드: default")
        
        # 프리셋 로드 및 적용
        if preset_to_load and self.preset_combo:
            # 신호를 차단하고 프리셋 설정
            self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentText(preset_to_load)
            self.preset_combo.blockSignals(False)
            
            # 프리셋 로드
            self.load_preset(preset_to_load)
            
            # 현재 프리셋 상태 업데이트
            self.current_preset = preset_to_load
            self.last_preset = preset_to_load
    
    def get_preset_dir(self) -> Path:
        """현재 API 모드에 따른 프리셋 디렉토리 경로 반환"""
        if not hasattr(self, 'app_context') or not self.app_context:
            mode = "NAI"
        else:
            mode = self.app_context.get_api_mode() or "NAI"
        
        preset_dir = Path("save") / "presets" / mode
        preset_dir.mkdir(parents=True, exist_ok=True)
        return preset_dir
    
    def load_preset_list(self):
        """프리셋 목록을 로드하고 콤보박스에 설정"""
        if not self.preset_combo:
            return

        preset_dir = self.get_preset_dir()

        # JSON 파일 목록 가져오기
        json_files = sorted(preset_dir.glob("*.json"))
        preset_names = [f.stem for f in json_files]

        # default를 맨 앞으로
        if "default" in preset_names:
            preset_names.remove("default")
            preset_names.insert(0, "default")

        # preset_list는 실제 파일 기반 프리셋만 포함 (*randomized 제외)
        self.preset_list = preset_names

        # 콤보박스 업데이트
        current_text = self.preset_combo.currentText()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()

        # *randomized를 첫 번째로 추가 (파일 기반이 아님)
        self.preset_combo.addItem("*randomized")

        if preset_names:
            self.preset_combo.addItems(preset_names)
            # 이전 선택 복원 또는 default 선택
            if current_text == "*randomized":
                self.preset_combo.setCurrentText("*randomized")
            elif current_text in preset_names:
                self.preset_combo.setCurrentText(current_text)
            elif "default" in preset_names:
                self.preset_combo.setCurrentText("default")
        else:
            # 프리셋이 없으면 *randomized만 표시
            pass  # *randomized는 이미 추가됨

        self.preset_combo.blockSignals(False)
    
    def create_default_preset(self, filepath: Path):
        """기본 프리셋 파일 생성"""
        mode = self.app_context.get_api_mode() if hasattr(self, 'app_context') and self.app_context else "NAI"
        
        if mode == "NAI":
            default_data = {
                "module_settings": {
                    "pre_prompt": "masterpiece, best quality",
                    "post_prompt": "",
                    "auto_hide_prompt": "",
                    "preprocessing_options": {
                        "remove_author": False,
                        "remove_work_title": False,
                        "remove_character_name": False,
                        "remove_character_features": False,
                        "remove_clothes": False,
                        "remove_color": False,
                        "remove_location_and_background_color": False
                    }
                },
                "main_settings": {
                    "prompt": "",
                    "negative": "lowres, {bad}, error, fewer, extra, missing, worst quality, jpeg artifacts, bad quality, watermark, unfinished, displeasing, chromatic aberration, signature, extra digits, artistic error, username, scan, [abstract]",
                    "cfg_scale": 5.0,
                    "sampler": "k_euler",
                    "steps": 28
                }
            }
        elif mode == "WEBUI":
            default_data = {
                "module_settings": {
                    "pre_prompt": "",
                    "post_prompt": "",
                    "auto_hide_prompt": "",
                    "preprocessing_options": {
                        "remove_author": False,
                        "remove_work_title": False,
                        "remove_character_name": False,
                        "remove_character_features": False,
                        "remove_clothes": False,
                        "remove_color": False,
                        "remove_location_and_background_color": False
                    }
                },
                "main_settings": {
                    "prompt": "",
                    "negative": "",
                    "cfg_scale": 7.0,
                    "sampler": "Euler",
                    "steps": 20
                }
            }
        else:  # COMFYUI
            default_data = {
                "module_settings": {
                    "pre_prompt": "",
                    "post_prompt": "",
                    "auto_hide_prompt": "",
                    "preprocessing_options": {
                        "remove_author": False,
                        "remove_work_title": False,
                        "remove_character_name": False,
                        "remove_character_features": False,
                        "remove_clothes": False,
                        "remove_color": False,
                        "remove_location_and_background_color": False
                    }
                },
                "main_settings": {
                    "prompt": "",
                    "negative": "",
                    "workflow": "default"
                }
            }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(default_data, f, ensure_ascii=False, indent=2)
    
    def save_current_preset(self, preset_name: Optional[str] = None):
        """현재 설정을 프리셋으로 저장"""
        if not preset_name:
            preset_name = self.current_preset
        
        preset_dir = self.get_preset_dir()
        preset_file = preset_dir / f"{preset_name}.json"
        
        # 기존 프리셋 파일에서 description 읽기
        existing_description = None
        if preset_file.exists():
            try:
                with open(preset_file, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                    existing_description = existing_data.get("description")
            except Exception:
                pass  # 파일 읽기 실패 시 무시
        
        # 모듈 설정 수집
        module_settings = self.collect_current_settings()
        
        # 메인 UI 설정 수집
        main_settings = self.collect_main_ui_settings()
        
        # 현재 API 모드 저장
        current_mode = self.app_context.get_api_mode() if hasattr(self, 'app_context') and self.app_context else "NAI"
        
        preset_data = {
            "module_settings": module_settings,
            "main_settings": main_settings,
            "api_mode": current_mode  # 프리셋이 저장된 API 모드 기록
        }
        
        # 기존 description이 있으면 유지
        if existing_description is not None:
            preset_data["description"] = existing_description
        
        with open(preset_file, 'w', encoding='utf-8') as f:
            json.dump(preset_data, f, ensure_ascii=False, indent=2)
        
        print(f"💾 프리셋 저장: {preset_name}")
    
    def load_preset(self, preset_name: str):
        """프리셋 로드 및 적용"""
        preset_dir = self.get_preset_dir()
        preset_file = preset_dir / f"{preset_name}.json"
        
        if not preset_file.exists():
            print(f"⚠️ 프리셋 파일을 찾을 수 없음: {preset_name}")
            return
        
        print(f"🔄 프리셋 로드 시작: {preset_name}")
        
        try:
            with open(preset_file, 'r', encoding='utf-8') as f:
                preset_data = json.load(f)
            
            print(f"  - 프리셋 데이터 키: {list(preset_data.keys())}")
            
            # 프리셋이 저장된 API 모드 확인
            preset_mode = preset_data.get("api_mode", "NAI")
            current_mode = self.app_context.get_api_mode() if hasattr(self, 'app_context') and self.app_context else "NAI"
            
            if preset_mode != current_mode:
                print(f"  ⚠️ 프리셋 모드({preset_mode})와 현재 모드({current_mode})가 다름 - 변환 시도")
            
            # 메인 윈도우가 준비되었는지 확인
            main_window = getattr(self.app_context, 'main_window', None) if hasattr(self, 'app_context') and self.app_context else None
            
            # 모듈 설정은 항상 적용
            if "module_settings" in preset_data:
                print(f"  - module_settings 적용 중...")
                self.apply_settings(preset_data["module_settings"])
                print(f"  - module_settings 적용 완료")
            else:
                print(f"  - module_settings 없음")
            
            # 메인 UI 설정은 메인 윈도우가 준비된 경우에만 적용
            if "main_settings" in preset_data and main_window:
                print(f"  - main_settings 적용 중...")
                # 기존 키 이름 호환성 처리
                main_settings = preset_data["main_settings"]
                if 'sm' in main_settings:
                    main_settings['SMEA'] = main_settings.pop('sm', False)
                if 'sm_dyn' in main_settings:
                    main_settings['DYN'] = main_settings.pop('sm_dyn', False)
                if 'variety' in main_settings:
                    main_settings['VAR+'] = main_settings.pop('variety', False)
                if 'decrisper' in main_settings:
                    main_settings['DECRISP'] = main_settings.pop('decrisper', False)
                
                self.apply_main_ui_settings(main_settings)
                print(f"  - main_settings 적용 완료")
            elif "main_settings" in preset_data and not main_window:
                print(f"⚠️ 메인 UI가 아직 준비되지 않아 UI 설정 적용을 건너뜁니다.")
            else:
                print(f"  - main_settings 없음")
            
            print(f"📂 프리셋 로드 완료: {preset_name}")
            
        except Exception as e:
            import traceback
            print(f"❌ 프리셋 로드 실패: {e}")
            traceback.print_exc()
    
    def on_preset_changed(self, preset_name: str):
        """프리셋 변경 시 호출"""
        if not preset_name or preset_name == self.current_preset or preset_name == "(프리셋 없음)":
            return

        print(f"🔄 프리셋 변경: {self.current_preset} → {preset_name}")

        # === *randomized 특수 처리 ===
        if preset_name == "*randomized":
            # 이전 프리셋 저장 (randomized로 진입 전, 파일 기반 프리셋만)
            if self.current_preset and self.current_preset not in ["(프리셋 없음)", "*randomized"]:
                self.save_current_preset(self.current_preset)
                print(f"  - 이전 프리셋 '{self.current_preset}' 저장 완료")

            # Randomized 모드 활성화
            self.is_randomized_mode = True
            self._show_randomized_ui()

            # 상태 업데이트
            self.last_preset = self.current_preset
            self.current_preset = "*randomized"

            # *randomized는 마지막 사용 프리셋으로 저장하지 않음
            print(f"🎲 Randomized Mode 활성화")
            return

        # === *randomized에서 다른 프리셋으로 전환 ===
        if self.current_preset == "*randomized":
            self.is_randomized_mode = False
            self._hide_randomized_ui()
            # *randomized는 파일 저장 없음, 바로 새 프리셋 로드로 진행

        # 이전 프리셋 저장 (파일 기반 프리셋만)
        if self.current_preset and self.current_preset not in ["(프리셋 없음)", "*randomized"]:
            self.save_current_preset(self.current_preset)
            print(f"  - 이전 프리셋 '{self.current_preset}' 저장 완료")

        # 새 프리셋 로드
        self.load_preset(preset_name)

        # 프리셋 상태 업데이트
        self.last_preset = self.current_preset
        self.current_preset = preset_name

        # 마지막 사용 프리셋 정보 저장
        self.save_last_used_preset_info()
    
    def add_preset(self):
        """새 프리셋 추가 다이얼로그"""
        dialog = QDialog(self.widget if self.widget else None)
        dialog.setWindowTitle("새 프리셋 추가")
        dialog.setStyleSheet(f"background-color: {DARK_COLORS['background']};")
        
        layout = QGridLayout(dialog)
        dynamic_styles = get_dynamic_styles()
        
        # 이름 입력
        name_label = QLabel("프리셋 이름:")
        name_label.setStyleSheet(dynamic_styles['label_style'])
        layout.addWidget(name_label, 0, 0)
        
        name_input = QLineEdit()
        name_input.setStyleSheet(dynamic_styles['compact_lineedit'])
        name_input.setProperty("autocomplete_ignore", True)
        layout.addWidget(name_input, 0, 1)
        
        # 안내 메시지
        info_label = QLabel("현재 설정이 복사됩니다.")
        info_label.setStyleSheet(dynamic_styles['label_style'])
        layout.addWidget(info_label, 1, 0, 1, 2)  # 두 컬럼에 걸쳐 표시
        
        # 버튼
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.setStyleSheet(dynamic_styles['primary_button'])
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons, 2, 0, 1, 2)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            preset_name = name_input.text().strip()
            
            if not preset_name:
                QMessageBox.warning(self.widget, "경고", "프리셋 이름을 입력해주세요.")
                return
            
            # 파일명에 사용할 수 없는 문자 제거
            invalid_chars = '<>:"/\\|?*'
            for char in invalid_chars:
                preset_name = preset_name.replace(char, '')
            
            preset_dir = self.get_preset_dir()
            preset_file = preset_dir / f"{preset_name}.json"
            
            if preset_file.exists():
                reply = QMessageBox.question(
                    self.widget, 
                    "확인", 
                    f"'{preset_name}' 프리셋이 이미 존재합니다. 덮어쓰시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
            
            # 현재 설정으로 새 프리셋 생성
            self.save_current_preset(preset_name)
            
            # 목록 업데이트 및 선택
            self.load_preset_list()
            self.preset_combo.setCurrentText(preset_name)
    
    def manage_presets(self):
        """프리셋 관리 다이얼로그"""
        dialog = QDialog(self.widget if self.widget else None)
        dialog.setWindowTitle("프리셋 관리")
        dialog.resize(1200, 700)  # 크기 증가
        dialog.setStyleSheet(f"background-color: {DARK_COLORS['background']};")
        
        main_layout = QVBoxLayout(dialog)
        dynamic_styles = get_dynamic_styles()
        
        # 메인 스플리터 생성 (3열 구조)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 왼쪽 패널 (이미지 프리뷰 + 설명)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(10)
        
        # 이미지 프리뷰 위젯
        preview_label = QLabel("프리셋 이미지:")
        preview_label.setStyleSheet(dynamic_styles['label_style'])
        left_layout.addWidget(preview_label)
        
        preview_widget = PresetPreviewWidget()
        preview_widget.setMinimumHeight(300)
        preview_widget.setMaximumWidth(400)
        left_layout.addWidget(preview_widget, 2)
        
        # 설명 텍스트 편집 위젯
        desc_label = QLabel("프리셋 설명:")
        desc_label.setStyleSheet(dynamic_styles['label_style'])
        left_layout.addWidget(desc_label)
        
        desc_textedit = QTextEdit()
        desc_textedit.setAcceptRichText(False)  # 서식 붙여넣기 차단
        desc_textedit.setMaximumHeight(150)
        desc_textedit.setStyleSheet(dynamic_styles['compact_textedit'])
        desc_textedit.setPlaceholderText("이 프리셋에 대한 설명을 작성하세요...")
        left_layout.addWidget(desc_textedit, 1)
        
        # 중앙 패널 (프리셋 목록)
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        
        list_label = QLabel("프리셋 목록:")
        list_label.setStyleSheet(dynamic_styles['label_style'])
        center_layout.addWidget(list_label)
        
        # 프리셋 목록
        list_widget = QListWidget()
        list_widget.setStyleSheet(f"""
            QListWidget {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                padding: 5px;
                font-size: {get_scaled_font_size(16)}px;
            }}
            QListWidget::item {{
                padding: 5px;
                color: white;
            }}
            QListWidget::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
            }}
            QListWidget::item:hover {{
                background-color: {DARK_COLORS['bg_tertiary']};
            }}
        """)
        
        # 프리셋 목록 로드
        preset_dir = self.get_preset_dir()
        preset_data = {}
        for preset_file in sorted(preset_dir.glob("*.json")):
            list_widget.addItem(preset_file.stem)
            try:
                with open(preset_file, 'r', encoding='utf-8') as f:
                    preset_data[preset_file.stem] = json.load(f)
            except:
                pass
        
        center_layout.addWidget(list_widget)
        
        # 버튼들
        button_layout = QHBoxLayout()
        
        save_desc_btn = QPushButton("설명 저장")
        save_desc_btn.setStyleSheet(dynamic_styles['secondary_button'])
        def save_description():
            current_item = list_widget.currentItem()
            if current_item:
                preset_name = current_item.text()
                self.save_preset_description(preset_name, desc_textedit.toPlainText())
                # preset_data 업데이트
                if preset_name in preset_data:
                    preset_data[preset_name]["description"] = desc_textedit.toPlainText()
                QMessageBox.information(dialog, "성공", f"{preset_name} 프리셋의 설명이 저장되었습니다.")
            else:
                QMessageBox.warning(dialog, "경고", "설명을 저장할 프리셋을 선택해주세요.")
        save_desc_btn.clicked.connect(save_description)
        button_layout.addWidget(save_desc_btn)
        
        rename_btn = QPushButton("이름 변경")
        rename_btn.setStyleSheet(dynamic_styles['secondary_button'])
        rename_btn.clicked.connect(lambda: self.rename_preset(list_widget))
        button_layout.addWidget(rename_btn)
        
        delete_btn = QPushButton("삭제")
        delete_btn.setStyleSheet(dynamic_styles['secondary_button'])
        delete_btn.clicked.connect(lambda: self.delete_preset(list_widget))
        button_layout.addWidget(delete_btn)
        
        # 선택 버튼 (현재 포커스된 프리셋을 적용하고 창을 닫음)
        select_btn = QPushButton("선택")
        select_btn.setStyleSheet(dynamic_styles['primary_button'])
        def apply_selected_preset():
            current_item = list_widget.currentItem()
            if current_item and self.preset_combo:
                preset_name = current_item.text()
                # 콤보박스에 프리셋 이름 설정
                self.preset_combo.setCurrentText(preset_name)
                # 프리셋 로드 (이미 정의된 메서드 사용)
                self.load_preset(preset_name)
                # 다이얼로그 닫기
                dialog.close()
            elif not current_item:
                QMessageBox.warning(dialog, "경고", "적용할 프리셋을 선택해주세요.")
        select_btn.clicked.connect(apply_selected_preset)
        button_layout.addWidget(select_btn)
        
        center_layout.addLayout(button_layout)
        
        # 오른쪽 패널 (프리셋 설정 상세 정보)
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        detail_label = QLabel("프리셋 상세 정보:")
        detail_label.setStyleSheet(dynamic_styles['label_style'])
        right_layout.addWidget(detail_label)
        
        # 프리셋 설정 표시용 TextEdit
        detail_textedit = QTextEdit()
        detail_textedit.setAcceptRichText(False)  # 서식 붙여넣기 차단
        detail_textedit.setReadOnly(True)
        detail_textedit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                padding: 10px;
                font-family: monospace;
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)
        right_layout.addWidget(detail_textedit)
        
        # 스플리터에 패널 추가
        splitter.addWidget(left_panel)
        splitter.addWidget(center_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([350, 300, 550])  # 초기 크기 비율
        
        main_layout.addWidget(splitter)
        
        # 리스트 선택 이벤트 연결
        def on_preset_selected():
            current_item = list_widget.currentItem()
            if current_item:
                preset_name = current_item.text()
                
                # 이미지 프리뷰 업데이트
                preview_widget.set_preset_name(preset_name)
                
                # 프리셋 데이터 로드 및 표시
                if preset_name in preset_data:
                    data = preset_data[preset_name]
                    
                    # 설명 로드
                    desc = data.get("description", "")
                    desc_textedit.setText(desc)
                    
                    # 상세 정보 표시
                    detail_text = self.format_preset_details(data)
                    detail_textedit.setText(detail_text)
                else:
                    desc_textedit.clear()
                    detail_textedit.clear()
            else:
                preview_widget.clear_preview()
                desc_textedit.clear()
                detail_textedit.clear()
        
        list_widget.itemSelectionChanged.connect(on_preset_selected)
        
        # 첫 번째 항목 선택
        if list_widget.count() > 0:
            list_widget.setCurrentRow(0)
        
        # 모달리스 다이얼로그로 표시 (exec 대신 show 사용)
        dialog.show()
    
    def format_preset_details(self, preset_data: Dict) -> str:
        """프리셋 데이터를 읽기 쉬운 텍스트로 포맷팅"""
        lines = []
        
        # module_settings
        if "module_settings" in preset_data:
            lines.append("═══ 모듈 설정 ═══\n")
            settings = preset_data["module_settings"]
            
            if settings.get("pre_prompt"):
                lines.append("▶ 선행 프롬프트:")
                lines.append(f"  {settings['pre_prompt']}\n")
            
            if settings.get("post_prompt"):
                lines.append("▶ 후행 프롬프트:")
                lines.append(f"  {settings['post_prompt']}\n")
            
            if settings.get("auto_hide_prompt"):
                lines.append("▶ 자동 숨김 프롬프트:")
                lines.append(f"  {settings['auto_hide_prompt']}\n")
            
            if settings.get("preprocessing_options"):
                active_options = [k for k, v in settings["preprocessing_options"].items() if v]
                if active_options:
                    lines.append("▶ 전처리 옵션:")
                    for opt in active_options:
                        lines.append(f"  ✓ {opt}")
                    lines.append("")
        
        # main_settings
        if "main_settings" in preset_data:
            lines.append("\n═══ 메인 설정 ═══\n")
            settings = preset_data["main_settings"]
            
            if "prompt" in settings:
                lines.append("▶ 메인 프롬프트:")
                lines.append(f"  {settings['prompt']}\n")
            
            if "negative" in settings:
                lines.append("▶ 네거티브 프롬프트:")
                lines.append(f"  {settings['negative']}\n")
            
            if "cfg_scale" in settings:
                lines.append(f"▶ CFG Scale: {settings['cfg_scale']}")
            
            if "sampler" in settings:
                lines.append(f"▶ 샘플러: {settings['sampler']}")
            
            if "steps" in settings:
                lines.append(f"▶ 스텝: {settings['steps']}")
            
            # 체크박스 옵션들
            checkboxes = []
            for key in ["SMEA", "DYN", "VAR+", "DECRISP", "sm", "sm_dyn", "variety", "decrisper"]:
                if key in settings and settings[key]:
                    checkboxes.append(key)
            
            if checkboxes:
                lines.append(f"▶ 활성 옵션: {', '.join(checkboxes)}")
        
        return "\n".join(lines)
    
    def rename_preset(self, list_widget: QListWidget):
        """프리셋 이름 변경"""
        current_item = list_widget.currentItem()
        if not current_item:
            QMessageBox.warning(self.widget, "경고", "이름을 변경할 프리셋을 선택해주세요.")
            return
        
        old_name = current_item.text()
        
        if old_name == "default":
            QMessageBox.warning(self.widget, "경고", "기본 프리셋은 이름을 변경할 수 없습니다.")
            return
        
        new_name, ok = QInputDialog.getText(self.widget, "이름 변경", "새 이름:", text=old_name)
        
        if ok and new_name and new_name != old_name:
            # 파일명에 사용할 수 없는 문자 제거
            invalid_chars = '<>:"/\\|?*'
            for char in invalid_chars:
                new_name = new_name.replace(char, '')
            
            preset_dir = self.get_preset_dir()
            old_file = preset_dir / f"{old_name}.json"
            new_file = preset_dir / f"{new_name}.json"
            
            if new_file.exists():
                QMessageBox.warning(self.widget, "경고", f"'{new_name}' 프리셋이 이미 존재합니다.")
                return
            
            old_file.rename(new_file)
            current_item.setText(new_name)
            
            # 콤보박스 업데이트
            self.load_preset_list()
    
    def delete_preset(self, list_widget: QListWidget):
        """프리셋 삭제"""
        current_item = list_widget.currentItem()
        if not current_item:
            QMessageBox.warning(self.widget, "경고", "삭제할 프리셋을 선택해주세요.")
            return
        
        preset_name = current_item.text()
        
        if preset_name == "default":
            QMessageBox.warning(self.widget, "경고", "기본 프리셋은 삭제할 수 없습니다.")
            return
        
        reply = QMessageBox.question(
            self.widget,
            "확인",
            f"'{preset_name}' 프리셋을 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            preset_dir = self.get_preset_dir()
            preset_file = preset_dir / f"{preset_name}.json"
            preset_file.unlink()
            
            # 목록에서 제거
            list_widget.takeItem(list_widget.row(current_item))
            
            # 콤보박스 업데이트
            self.load_preset_list()
    
    def on_api_mode_changed_preset(self, data: dict):
        """API 모드 변경 시 프리셋 처리"""
        # *randomized 모드인 경우 저장 건너뛰고 초기화
        if self.current_preset == "*randomized":
            print("🎲 *randomized 모드 해제: 랜덤 프리셋 목록 초기화")
            self._reset_randomized_state()
        elif self.current_preset and self.current_preset != "(프리셋 없음)":
            # 이전 모드의 현재 프리셋 저장 (일반 프리셋만)
            self.save_current_preset()
            self.save_last_used_preset_info()

        # 새 모드의 프리셋 목록 로드
        self.load_preset_list()
        
        # 새 모드의 마지막 사용 프리셋 로드
        last_used = self.load_last_used_preset_info()
        
        preset_to_load = None
        if last_used and last_used in self.preset_list:
            preset_to_load = last_used
            print(f"📂 마지막 사용 프리셋 복원: {last_used}")
        elif "default" in self.preset_list:
            preset_to_load = "default"
            print(f"📂 기본 프리셋 로드: default")
        
        if preset_to_load:
            self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentText(preset_to_load)
            self.preset_combo.blockSignals(False)
            self.load_preset(preset_to_load)
            self.current_preset = preset_to_load
            self.last_preset = preset_to_load
    
    def collect_main_ui_settings(self) -> Dict[str, Any]:
        """메인 UI 설정 수집 - app_context를 통해 접근"""
        settings = {}
        
        if not hasattr(self, 'app_context') or not self.app_context:
            return settings
        
        # MainWindow 인스턴스 가져오기
        main_window = getattr(self.app_context, 'main_window', None)
        if not main_window:
            return settings
        
        try:
            # 프롬프트 텍스트
            if hasattr(main_window, 'main_prompt_textedit'):
                settings['prompt'] = main_window.main_prompt_textedit.toPlainText()
            
            if hasattr(main_window, 'negative_prompt_textedit'):
                settings['negative'] = main_window.negative_prompt_textedit.toPlainText()
            
            # 생성 파라미터 — 위젯에서 직접 읽기 (get_main_parameters()는 시드 부작용 있음)
            mode = self.app_context.get_api_mode()
            if mode == "NAI":
                if hasattr(main_window, 'cfg_scale_slider'):
                    settings['cfg_scale'] = main_window.cfg_scale_slider.value() / 10.0
                else:
                    settings['cfg_scale'] = 5.0

                if hasattr(main_window, 'sampler_combo'):
                    settings['sampler'] = main_window.sampler_combo.currentText()
                else:
                    settings['sampler'] = 'k_euler'

                if hasattr(main_window, 'steps_spinbox'):
                    settings['steps'] = main_window.steps_spinbox.value()
                else:
                    settings['steps'] = 28
                # 체크박스들 - advanced_checkboxes 딕셔너리에서 가져오기
                if hasattr(main_window, 'advanced_checkboxes'):
                    settings['SMEA'] = main_window.advanced_checkboxes.get("SMEA", QCheckBox()).isChecked()
                    settings['DYN'] = main_window.advanced_checkboxes.get("DYN", QCheckBox()).isChecked()
                    settings['VAR+'] = main_window.advanced_checkboxes.get("VAR+", QCheckBox()).isChecked()
                    settings['DECRISP'] = main_window.advanced_checkboxes.get("DECRISP", QCheckBox()).isChecked()
                else:
                    settings['SMEA'] = False
                    settings['DYN'] = False
                    settings['VAR+'] = False
                    settings['DECRISP'] = False
            elif mode == "WEBUI":
                if hasattr(main_window, 'cfg_scale_slider'):
                    settings['cfg_scale'] = main_window.cfg_scale_slider.value() / 10.0
                else:
                    settings['cfg_scale'] = 7.0

                if hasattr(main_window, 'sampler_combo'):
                    settings['sampler'] = main_window.sampler_combo.currentText()
                else:
                    settings['sampler'] = 'Euler'

                # WEBUI에서는 scheduler도 저장해야 함
                if hasattr(main_window, 'scheduler_combo'):
                    settings['scheduler'] = main_window.scheduler_combo.currentText()
                else:
                    settings['scheduler'] = 'SGM Uniform'

                if hasattr(main_window, 'steps_spinbox'):
                    settings['steps'] = main_window.steps_spinbox.value()
                else:
                    settings['steps'] = 20

                # WEBUI 전용 설정들
                if hasattr(main_window, 'enable_hr_checkbox'):
                    settings['enable_hr'] = main_window.enable_hr_checkbox.isChecked()
                else:
                    settings['enable_hr'] = False

                if hasattr(main_window, 'hr_scale_spinbox'):
                    settings['hr_scale'] = main_window.hr_scale_spinbox.value()
                else:
                    settings['hr_scale'] = 1.5
                    
                if hasattr(main_window, 'hr_upscaler_combo'):
                    settings['hr_upscaler'] = main_window.hr_upscaler_combo.currentText()
                else:
                    settings['hr_upscaler'] = 'Lanczos'

                # denoising_strength도 저장
                if hasattr(main_window, 'denoising_strength_slider'):
                    settings['denoising_strength'] = main_window.denoising_strength_slider.value() / 100.0
                else:
                    settings['denoising_strength'] = 0.5
            elif mode == "COMFYUI":
                if hasattr(main_window, 'cfg_scale_slider'):
                    settings['cfg_scale'] = main_window.cfg_scale_slider.value() / 10.0
                else:
                    settings['cfg_scale'] = 7.0

                if hasattr(main_window, 'sampler_combo'):
                    settings['sampler'] = main_window.sampler_combo.currentText()
                else:
                    settings['sampler'] = 'euler'

                if hasattr(main_window, 'scheduler_combo'):
                    settings['scheduler'] = main_window.scheduler_combo.currentText()
                else:
                    settings['scheduler'] = 'normal'

                if hasattr(main_window, 'steps_spinbox'):
                    settings['steps'] = main_window.steps_spinbox.value()
                else:
                    settings['steps'] = 20

                # ComfyUI 전용 설정
                if hasattr(main_window, 'v_prediction_checkbox'):
                    settings['v_prediction'] = main_window.v_prediction_checkbox.isChecked()
                else:
                    settings['v_prediction'] = False

                if hasattr(main_window, 'zsnr_checkbox'):
                    settings['zsnr'] = main_window.zsnr_checkbox.isChecked()
                else:
                    settings['zsnr'] = False
            
        except Exception as e:
            print(f"⚠️ 메인 UI 설정 수집 중 오류: {e}")
        
        return settings
    
    def apply_main_ui_settings(self, settings: Dict[str, Any]):
        """메인 UI에 설정 적용"""
        if not hasattr(self, 'app_context') or not self.app_context:
            print("    ⚠️ app_context 없음")
            return
        
        main_window = getattr(self.app_context, 'main_window', None)
        if not main_window:
            print("    ⚠️ main_window 없음")
            return
        
        print(f"    - 메인 UI 설정 적용:")
        print(f"      설정 키: {list(settings.keys())}")
        
        try:
            # 프롬프트 텍스트 적용
            if 'prompt' in settings:
                if hasattr(main_window, 'main_prompt_textedit'):
                    main_window.main_prompt_textedit.setPlainText(settings['prompt'])
                    print(f"      메인 프롬프트 적용 (길이: {len(settings['prompt'])})")
                else:
                    print(f"      ⚠️ main_prompt_textedit 없음")
            
            if 'negative' in settings:
                if hasattr(main_window, 'negative_prompt_textedit'):
                    main_window.negative_prompt_textedit.setPlainText(settings['negative'])
                    print(f"      네거티브 프롬프트 적용 (길이: {len(settings['negative'])})")
                else:
                    print(f"      ⚠️ negative_prompt_textedit 없음")
            
            mode = self.app_context.get_api_mode()
            
            # NAI 모드 설정
            if mode == "NAI":
                print(f"      NAI 모드 설정 적용 중...")
                
                if 'cfg_scale' in settings:
                    if hasattr(main_window, 'cfg_scale_slider'):
                        # cfg_scale은 슬라이더로 구현되어 있으며 10배수로 저장됨
                        slider_value = int(float(settings['cfg_scale']) * 10)
                        main_window.cfg_scale_slider.setValue(slider_value)
                        # 라벨도 업데이트
                        if hasattr(main_window, 'cfg_value_label'):
                            main_window.cfg_value_label.setText(str(settings['cfg_scale']))
                        print(f"        cfg_scale: {settings['cfg_scale']}")
                    else:
                        print(f"        ⚠️ cfg_scale_slider 없음")
                
                if 'sampler' in settings:
                    if hasattr(main_window, 'sampler_combo'):
                        index = main_window.sampler_combo.findText(settings['sampler'])
                        if index >= 0:
                            main_window.sampler_combo.setCurrentIndex(index)
                            print(f"        sampler: {settings['sampler']}")
                        else:
                            print(f"        ⚠️ sampler '{settings['sampler']}' 찾을 수 없음")
                    else:
                        print(f"        ⚠️ sampler_combo 없음")
                
                if 'steps' in settings:
                    if hasattr(main_window, 'steps_spinbox'):
                        main_window.steps_spinbox.setValue(int(settings['steps']))
                        print(f"        steps: {settings['steps']}")
                    else:
                        print(f"        ⚠️ steps_spinbox 없음")
                
                # 체크박스들 - advanced_checkboxes 딕셔너리 사용
                if hasattr(main_window, 'advanced_checkboxes'):
                    if 'SMEA' in settings and "SMEA" in main_window.advanced_checkboxes:
                        main_window.advanced_checkboxes["SMEA"].setChecked(settings['SMEA'])
                        print(f"        SMEA: {settings['SMEA']}")
                    
                    if 'DYN' in settings and "DYN" in main_window.advanced_checkboxes:
                        main_window.advanced_checkboxes["DYN"].setChecked(settings['DYN'])
                        print(f"        DYN: {settings['DYN']}")
                    
                    if 'VAR+' in settings and "VAR+" in main_window.advanced_checkboxes:
                        main_window.advanced_checkboxes["VAR+"].setChecked(settings['VAR+'])
                        print(f"        VAR+: {settings['VAR+']}")
                    
                    if 'DECRISP' in settings and "DECRISP" in main_window.advanced_checkboxes:
                        main_window.advanced_checkboxes["DECRISP"].setChecked(settings['DECRISP'])
                        print(f"        DECRISP: {settings['DECRISP']}")
                else:
                    print(f"        ⚠️ advanced_checkboxes 없음")
            
            # WEBUI 모드 설정
            elif mode == "WEBUI":
                # WEBUI는 NAI와 동일한 위젯 이름을 사용
                if 'cfg_scale' in settings and hasattr(main_window, 'cfg_scale_slider'):
                    # cfg_scale을 슬라이더 값으로 변환 (1.0~30.0 → 10~300)
                    main_window.cfg_scale_slider.setValue(int(float(settings['cfg_scale']) * 10))
                    print(f"        WEBUI cfg_scale: {settings['cfg_scale']}")
                
                if 'sampler' in settings and hasattr(main_window, 'sampler_combo'):
                    sampler_value = settings['sampler']
                    
                    # NAI sampler를 WEBUI sampler로 매핑 시도
                    sampler_mapping = {
                        'k_euler_ancestral': 'Euler a',
                        'k_euler': 'Euler',
                        'k_dpmpp_2m': 'DPM++ 2M',
                        'k_dpmpp_2s_ancestral': 'DPM++ 2S a',
                        'k_dpmpp_sde': 'DPM++ SDE',
                        'k_dpmpp_2m_sde': 'DPM++ 2M SDE',
                        'ddim_v3': 'DDIM'
                    }
                    
                    # NAI sampler라면 WEBUI 형식으로 변환
                    if sampler_value in sampler_mapping:
                        sampler_value = sampler_mapping[sampler_value]
                    
                    index = main_window.sampler_combo.findText(sampler_value)
                    if index >= 0:
                        main_window.sampler_combo.setCurrentIndex(index)
                        print(f"        WEBUI sampler: {sampler_value}")
                    else:
                        print(f"        ⚠️ WEBUI sampler '{sampler_value}' 찾을 수 없음")
                
                if 'steps' in settings and hasattr(main_window, 'steps_spinbox'):
                    main_window.steps_spinbox.setValue(int(settings['steps']))
                    print(f"        WEBUI steps: {settings['steps']}")
                
                # scheduler 설정 적용
                if 'scheduler' in settings and hasattr(main_window, 'scheduler_combo'):
                    index = main_window.scheduler_combo.findText(settings['scheduler'])
                    if index >= 0:
                        main_window.scheduler_combo.setCurrentIndex(index)
                        print(f"        WEBUI scheduler: {settings['scheduler']}")
                    else:
                        print(f"        ⚠️ WEBUI scheduler '{settings['scheduler']}' 찾을 수 없음")
                
                # WEBUI 전용 설정들
                if 'enable_hr' in settings and hasattr(main_window, 'enable_hr_checkbox'):
                    main_window.enable_hr_checkbox.setChecked(settings['enable_hr'])
                    print(f"        WEBUI enable_hr: {settings['enable_hr']}")
                
                if 'hr_scale' in settings and hasattr(main_window, 'hr_scale_spinbox'):
                    main_window.hr_scale_spinbox.setValue(float(settings['hr_scale']))
                    print(f"        WEBUI hr_scale: {settings['hr_scale']}")
                
                if 'hr_upscaler' in settings and hasattr(main_window, 'hr_upscaler_combo'):
                    index = main_window.hr_upscaler_combo.findText(settings['hr_upscaler'])
                    if index >= 0:
                        main_window.hr_upscaler_combo.setCurrentIndex(index)
                        print(f"        WEBUI hr_upscaler: {settings['hr_upscaler']}")
                
                # denoising_strength 설정 적용
                if 'denoising_strength' in settings and hasattr(main_window, 'denoising_strength_slider'):
                    # 0.0~1.0 값을 0~100 슬라이더 값으로 변환
                    slider_value = int(float(settings['denoising_strength']) * 100)
                    main_window.denoising_strength_slider.setValue(slider_value)
                    print(f"        WEBUI denoising_strength: {settings['denoising_strength']}")
            
            # ComfyUI 모드 설정
            elif mode == "COMFYUI":
                print("      ComfyUI 모드 설정 적용 중...")
                
                if 'cfg_scale' in settings and hasattr(main_window, 'cfg_scale_slider'):
                    main_window.cfg_scale_slider.setValue(int(float(settings['cfg_scale']) * 10))
                    print(f"        ComfyUI cfg_scale: {settings['cfg_scale']}")
                
                if 'sampler' in settings and hasattr(main_window, 'sampler_combo'):
                    index = main_window.sampler_combo.findText(settings['sampler'])
                    if index >= 0:
                        main_window.sampler_combo.setCurrentIndex(index)
                        print(f"        ComfyUI sampler: {settings['sampler']}")
                    else:
                        print(f"        ⚠️ ComfyUI sampler '{settings['sampler']}' 찾을 수 없음")
                
                if 'scheduler' in settings and hasattr(main_window, 'scheduler_combo'):
                    index = main_window.scheduler_combo.findText(settings['scheduler'])
                    if index >= 0:
                        main_window.scheduler_combo.setCurrentIndex(index)
                        print(f"        ComfyUI scheduler: {settings['scheduler']}")
                    else:
                        print(f"        ⚠️ ComfyUI scheduler '{settings['scheduler']}' 찾을 수 없음")
                
                if 'steps' in settings and hasattr(main_window, 'steps_spinbox'):
                    main_window.steps_spinbox.setValue(int(settings['steps']))
                    print(f"        ComfyUI steps: {settings['steps']}")
                
                # ComfyUI 전용 설정
                if 'v_prediction' in settings and hasattr(main_window, 'v_prediction_checkbox'):
                    main_window.v_prediction_checkbox.setChecked(settings['v_prediction'])
                    print(f"        ComfyUI v_prediction: {settings['v_prediction']}")
                
                if 'zsnr' in settings and hasattr(main_window, 'zsnr_checkbox'):
                    main_window.zsnr_checkbox.setChecked(settings['zsnr'])
                    print(f"        ComfyUI zsnr: {settings['zsnr']}")
            
        except Exception as e:
            import traceback
            print(f"⚠️ 메인 UI 설정 적용 중 오류: {e}")
            traceback.print_exc()
    
    def save_on_exit(self):
        """프로그램 종료 시 현재 프리셋 저장"""
        if self.current_preset and self.current_preset != "(프리셋 없음)":
            self.save_current_preset()
            self.save_last_used_preset_info()
    
    def save_last_used_preset_info(self):
        """마지막 사용한 프리셋 정보 저장"""
        if not self.current_preset or self.current_preset == "(프리셋 없음)":
            return
        
        mode = self.app_context.get_api_mode() if hasattr(self, 'app_context') and self.app_context else "NAI"
        
        last_used_file = Path("save") / "presets" / "last_used_preset.json"
        last_used_file.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            mode: self.current_preset
        }
        
        # 기존 데이터가 있으면 병합
        if last_used_file.exists():
            try:
                with open(last_used_file, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                    existing_data.update(data)
                    data = existing_data
            except:
                pass
        
        try:
            with open(last_used_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"💾 마지막 사용 프리셋 저장: {self.current_preset} ({mode})")
        except Exception as e:
            print(f"⚠️ 마지막 사용 프리셋 정보 저장 실패: {e}")
    
    def load_last_used_preset_info(self) -> Optional[str]:
        """마지막 사용한 프리셋 정보 로드"""
        mode = self.app_context.get_api_mode() if hasattr(self, 'app_context') and self.app_context else "NAI"
        
        last_used_file = Path("save") / "presets" / "last_used_preset.json"
        
        if not last_used_file.exists():
            return None
        
        try:
            with open(last_used_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get(mode)
        except Exception as e:
            print(f"⚠️ 마지막 사용 프리셋 정보 로드 실패: {e}")
            return None
    
    def save_preset_description(self, preset_name: str, description: str):
        """프리셋 설명 저장"""
        if not preset_name:
            return
        
        preset_dir = self.get_preset_dir()
        preset_file = preset_dir / f"{preset_name}.json"
        
        if not preset_file.exists():
            return
        
        try:
            # 기존 프리셋 데이터 로드
            with open(preset_file, 'r', encoding='utf-8') as f:
                preset_data = json.load(f)
            
            # 설명 추가/업데이트
            preset_data["description"] = description
            
            # 저장
            with open(preset_file, 'w', encoding='utf-8') as f:
                json.dump(preset_data, f, ensure_ascii=False, indent=2)
            
            print(f"📝 프리셋 설명 저장: {preset_name}")
        except Exception as e:
            print(f"⚠️ 프리셋 설명 저장 실패: {e}")

    # ==================== *randomized 전용 메서드 ====================

    def _show_randomized_ui(self):
        """*randomized 선택 시 전용 UI 표시"""
        if self.randomized_layout_widget:
            self.randomized_layout_widget.setVisible(True)

        # 퀵 프리셋 "추가" 버튼 비활성화 (*randomized 선택 시 새 프리셋 추가 불가)
        if self.preset_add_btn:
            self.preset_add_btn.setEnabled(False)

        # 복제 콤보박스 업데이트 (randomized_add_btn 상태도 여기서 설정됨)
        self._update_randomized_combo()

    def _hide_randomized_ui(self):
        """*randomized 해제 시 전용 UI 숨김"""
        if self.randomized_layout_widget:
            self.randomized_layout_widget.setVisible(False)

        # 퀵 프리셋 "추가" 버튼 활성화
        if self.preset_add_btn:
            self.preset_add_btn.setEnabled(True)

    def _reset_randomized_state(self):
        """*randomized 관련 상태 초기화 (원본 프리셋은 건드리지 않음)"""
        # randomized 모드 플래그 해제
        self.is_randomized_mode = False

        # 랜덤 프리셋 목록 초기화
        self.randomized_preset_list = []

        # ListBox 비우기
        if self.randomized_listbox:
            self.randomized_listbox.clear()

        # UI 숨김 (preset_add_btn 활성화 포함)
        self._hide_randomized_ui()

        # 현재 프리셋을 default로 리셋
        self.current_preset = "default"
        self.last_preset = "default"

    def _update_randomized_combo(self):
        """복제 콤보박스 업데이트 - *randomized, default, 이미 추가된 항목 제외"""
        if self.randomized_combo is None:
            print("⚠️ randomized_combo가 None입니다")
            return

        self.randomized_combo.blockSignals(True)
        self.randomized_combo.clear()

        for preset_name in self.preset_list:
            # *randomized와 default는 복제 콤보박스에서 제외
            if preset_name in ["*randomized", "default"]:
                continue

            # 이미 ListBox에 있는 항목도 제외 (숨김 처리)
            if preset_name in self.randomized_preset_list:
                continue

            self.randomized_combo.addItem(preset_name)

        # 첫 번째 항목 선택
        if self.randomized_combo.count() > 0:
            self.randomized_combo.setCurrentIndex(0)

        self.randomized_combo.blockSignals(False)

        # randomized_add_btn 상태 업데이트: 콤보박스에 항목이 있으면 활성화
        self._update_randomized_add_btn_state()

    def _update_randomized_add_btn_state(self):
        """randomized_add_btn 활성화 상태 업데이트"""
        if self.randomized_add_btn is None or self.randomized_combo is None:
            return

        # 콤보박스에 선택 가능한 항목이 있으면 활성화, 없으면 비활성화
        if self.randomized_combo.count() > 0 and self.randomized_combo.currentText():
            self.randomized_add_btn.setEnabled(True)
        else:
            self.randomized_add_btn.setEnabled(False)

    def _on_randomized_combo_changed(self, _text: str):
        """복제 콤보박스 선택 변경 시 호출"""
        self._update_randomized_add_btn_state()

    def _add_to_randomized_list(self):
        """복제 콤보박스에서 선택한 프리셋을 ListBox에 추가"""
        if self.randomized_combo is None or self.randomized_listbox is None:
            print(f"⚠️ _add_to_randomized_list: combo={self.randomized_combo}, listbox={self.randomized_listbox}")
            return

        preset_name = self.randomized_combo.currentText()

        if not preset_name or preset_name in self.randomized_preset_list:
            print(f"⚠️ _add_to_randomized_list: preset_name={preset_name}, already_in_list={preset_name in self.randomized_preset_list}")
            return

        # ListBox에 추가
        self.randomized_listbox.addItem(preset_name)
        self.randomized_preset_list.append(preset_name)

        # 복제 콤보박스 업데이트 (해당 항목 숨김 및 +추가 버튼 상태 갱신)
        self._update_randomized_combo()

        print(f"🎲 랜덤 프리셋 목록에 추가: {preset_name} (총 {len(self.randomized_preset_list)}개)")

    def _remove_from_randomized_list(self):
        """ListBox에서 선택한 프리셋 제거"""
        if self.randomized_listbox is None:
            return

        current_item = self.randomized_listbox.currentItem()

        if not current_item:
            return

        preset_name = current_item.text()

        # ListBox에서 제거
        row = self.randomized_listbox.row(current_item)
        self.randomized_listbox.takeItem(row)

        if preset_name in self.randomized_preset_list:
            self.randomized_preset_list.remove(preset_name)

        # 복제 콤보박스 업데이트 (해당 항목 활성화 복원 및 +추가 버튼 상태 갱신)
        self._update_randomized_combo()

        print(f"🎲 랜덤 프리셋 목록에서 제거: {preset_name}")

    def _on_randomized_listbox_item_clicked(self, item):
        """랜덤 프리셋 목록에서 아이템 클릭 시 해당 프리셋 로드"""
        if item is None:
            return

        selected_preset = item.text()
        if selected_preset:
            print(f"🎯 사용자가 랜덤 프리셋 목록에서 선택: {selected_preset}")
            self.load_preset_random(selected_preset)

    def _on_random_prompt_triggered(self, _data=None):
        """random_prompt_triggered 신호 수신 시 호출 - 랜덤 프리셋 선택"""
        # *randomized 모드가 아니면 무시
        if self.current_preset != "*randomized":
            return

        # 랜덤 프리셋 목록이 비어있으면 무시
        if not self.randomized_preset_list:
            print("⚠️ 랜덤 프리셋 목록이 비어있습니다")
            return

        # 랜덤하게 프리셋 선택
        import random
        selected_preset = random.choice(self.randomized_preset_list)

        print(f"🎲 랜덤 프리셋 선택: {selected_preset}")

        # 선택된 프리셋 로드 (pre_prompt, post_prompt만 적용)
        self.load_preset_random(selected_preset)

    def load_preset_random(self, preset_name: str):
        """랜덤 프리셋 로드 - pre_prompt, post_prompt만 적용 (auto_hide, options 무시), main_settings는 prompt 제외하고 적용"""
        preset_dir = self.get_preset_dir()
        preset_file = preset_dir / f"{preset_name}.json"

        if not preset_file.exists():
            print(f"⚠️ 프리셋 파일을 찾을 수 없음: {preset_name}")
            return

        try:
            with open(preset_file, 'r', encoding='utf-8') as f:
                preset_data = json.load(f)

            # module_settings에서 pre_prompt, post_prompt만 추출하여 적용
            if "module_settings" in preset_data:
                module_settings = preset_data["module_settings"]

                # UI 위젯 확인
                if not all([self.pre_textedit, self.post_textedit]):
                    print("⚠️ UI 위젯이 준비되지 않음")
                    return

                # pre_prompt, post_prompt만 적용 (auto_hide, preprocessing_options 무시)
                pre_prompt = module_settings.get("pre_prompt", "")
                post_prompt = module_settings.get("post_prompt", "")

                self.pre_textedit.setText(pre_prompt)
                self.post_textedit.setText(post_prompt)

                print(f"🎲 랜덤 프리셋 모듈 설정 적용: {preset_name} (pre: {len(pre_prompt)}자, post: {len(post_prompt)}자)")

            # main_settings 적용 (prompt 제외)
            main_window = getattr(self.app_context, 'main_window', None) if hasattr(self, 'app_context') and self.app_context else None

            if "main_settings" in preset_data and main_window:
                main_settings = preset_data["main_settings"].copy()  # 원본 보존을 위해 복사

                # prompt는 제외 (랜덤 프리셋에서는 prompt를 변경하지 않음)
                main_settings.pop('prompt', None)

                # 기존 키 이름 호환성 처리
                if 'sm' in main_settings:
                    main_settings['SMEA'] = main_settings.pop('sm', False)
                if 'sm_dyn' in main_settings:
                    main_settings['DYN'] = main_settings.pop('sm_dyn', False)
                if 'variety' in main_settings:
                    main_settings['VAR+'] = main_settings.pop('variety', False)
                if 'decrisper' in main_settings:
                    main_settings['DECRISP'] = main_settings.pop('decrisper', False)

                self.apply_main_ui_settings(main_settings)
                print(f"🎲 랜덤 프리셋 메인 UI 설정 적용 완료: {preset_name}")

            print(f"🎲 랜덤 프리셋 적용 완료: {preset_name}")

        except Exception as e:
            import traceback
            print(f"❌ 랜덤 프리셋 로드 실패: {e}")
            traceback.print_exc()


class _E621SettingsWindow(QWidget):
    """e621 Auto-Boost 사용자 설정 윈도우 (비모달)"""
    settings_changed = pyqtSignal(dict)

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("e621 Auto-Boost 설정")
        self.resize(500, 400)
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
            QLabel {{
                color: {DARK_COLORS['text_primary']};
            }}
            QLineEdit, QTextEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                padding: 4px;
            }}
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                padding: 4px 12px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)

        layout = QVBoxLayout(self)

        # ── 가중치 섹션 ──
        weight_label = QLabel("가중치 (0 = 비활성, 범위: -5.0 ~ 5.0)")
        weight_label.setToolTip("e621 태그 묶음에 적용할 NovelAI 가중치\n예: 0.8 → 0.8::tag1, tag2, ..., tagN ::")
        layout.addWidget(weight_label)

        self._weight_edit = QLineEdit()
        self._weight_edit.setPlaceholderText("예: 0.8")
        self._weight_edit.setProperty("autocomplete_ignore", True)
        validator = QDoubleValidator(-5.0, 5.0, 4, self)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self._weight_edit.setValidator(validator)

        step_btn_style = f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: #FFD1DC;
                border: 1px solid #FFD1DC;
                border-radius: 3px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """
        weight_row = QHBoxLayout()
        weight_row.setSpacing(get_scaled_size(4))
        btn_l = QPushButton("<")
        btn_l.setFixedSize(get_scaled_size(32), get_scaled_size(28))
        btn_l.setStyleSheet(step_btn_style)
        btn_r = QPushButton(">")
        btn_r.setFixedSize(get_scaled_size(32), get_scaled_size(28))
        btn_r.setStyleSheet(step_btn_style)
        def _step_weight(delta):
            try:
                val = float(self._weight_edit.text().strip())
            except ValueError:
                val = 0.0
            val = round(max(-5.0, min(5.0, val + delta)), 2)
            self._weight_edit.setText(str(val))
        btn_l.clicked.connect(lambda: _step_weight(-0.05))
        btn_r.clicked.connect(lambda: _step_weight(0.05))
        weight_row.addWidget(btn_l)
        weight_row.addWidget(self._weight_edit, 1)
        weight_row.addWidget(btn_r)
        layout.addLayout(weight_row)

        # ── 적용 모드 섹션 ──
        mode_label = QLabel("적용 모드")
        mode_label.setToolTip(
            "stable: dedup 그룹에서 최고 score 1개만 선택 (결정적)\n"
            "confused: 최소 1개 보장 + 나머지 score 비례 확률 추가 (다양성)"
        )
        layout.addWidget(mode_label)

        self._mode_combo = QComboBox()
        self._mode_combo.addItem("stable — 안정 (그룹당 1개)", "stable")
        self._mode_combo.addItem("confused — 다양성 (확률적 다중 선택)", "confused")
        self._mode_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                padding: 4px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        layout.addWidget(self._mode_combo)

        # ── 숨김 태그 섹션 ──
        hidden_label = QLabel("숨김 태그 (쉼표로 구분, 추천에서 제외)")
        hidden_label.setToolTip("예: chastity device, gaping anus, magic user")
        layout.addWidget(hidden_label)

        self._hidden_edit = QTextEdit()
        self._hidden_edit.setMinimumHeight(200)
        self._hidden_edit.setProperty("autocomplete_ignore", True)
        self._hidden_edit.setPlaceholderText("예: chastity device, gaping anus, magic user")
        layout.addWidget(self._hidden_edit)

        # ── 저장/닫기 버튼 (3:1) ──
        btn_row = QHBoxLayout()
        self._save_btn = QPushButton("저장")
        self._save_btn.clicked.connect(self._save)
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(self._save_btn, 3)
        btn_row.addWidget(close_btn, 1)
        layout.addLayout(btn_row)

        self.load_settings(settings)

    def load_settings(self, settings: dict):
        """설정을 UI에 반영 (언더바→공백으로 표시)"""
        self._weight_edit.setText(str(settings.get("weight", 0.0)))
        # mode
        mode = settings.get("mode", "stable")
        idx = self._mode_combo.findData(mode)
        self._mode_combo.setCurrentIndex(max(0, idx))
        # hidden tags
        hidden_tags = settings.get("hidden_tags", [])
        display_tags = [tag.replace("_", " ") for tag in hidden_tags]
        self._hidden_edit.setPlainText(", ".join(display_tags) if display_tags else "")

    def _save(self):
        """저장 버튼 클릭 시 — 1초간 피드백"""
        self.settings_changed.emit(self._collect())
        self._save_btn.setText("저장됨!")
        self._save_btn.setEnabled(False)
        QTimer.singleShot(1000, lambda: (
            self._save_btn.setText("저장"),
            self._save_btn.setEnabled(True),
        ))

    def _collect(self) -> dict:
        try:
            weight = float(self._weight_edit.text().strip())
            weight = max(-5.0, min(5.0, weight))
        except ValueError:
            weight = 0.0
        # 쉼표/개행 split + strip, 공백→언더스코어, 빈 문자열 제거
        import re
        raw = self._hidden_edit.toPlainText()
        hidden_tags = []
        for tag in re.split(r'[,\n]+', raw):
            tag = tag.strip().replace(" ", "_")
            if tag and tag not in hidden_tags:
                hidden_tags.append(tag)
        mode = self._mode_combo.currentData() or "stable"
        return {"weight": weight, "hidden_tags": hidden_tags, "mode": mode}

    def closeEvent(self, event):
        """닫을 때 자동 저장"""
        self.settings_changed.emit(self._collect())
        super().closeEvent(event)


class _DanbooruWeightSettingsWindow(QWidget):
    """Danbooru Auto-Weight 사용자 설정 윈도우 (비모달, 실시간 미리보기)"""
    settings_changed = pyqtSignal(dict)

    # 레이팅별 샘플 프롬프트 (다양한 빈도 대역 포함)
    _SAMPLE_CASES = {
        "e": ("Explicit", [
            "breasts", "blush", "open mouth", "navel", "nipples",
            "nude", "sweat", "spread legs", "sex", "cowgirl position",
            "girl on top", "bed", "pillow", "on back", "tongue out",
            "saliva", "cum", "fellatio", "onsen", "steam",
        ]),
        "s": ("Sensitive", [
            "long hair", "blue eyes", "smile", "looking at viewer",
            "school uniform", "thighhighs", "hair ornament", "ponytail",
            "heterochromia", "pleated skirt", "wind", "cherry blossoms",
            "umbrella", "lantern", "rooftop", "starry sky",
        ]),
        "q": ("Questionable", [
            "breasts", "cleavage", "navel", "thighs", "midriff",
            "swimsuit", "bikini", "wet", "ass", "sideboob",
            "underboob", "side-tie bikini bottom", "see-through",
            "cameltoe", "garter straps", "maid",
        ]),
        "g": ("General", [
            "sky", "cloud", "smile", "sitting", "standing",
            "tree", "flower", "grass", "no humans", "scenery",
            "building", "sunset", "rain", "snow", "mountain",
            "river", "lamp", "ruins",
        ]),
    }

    def __init__(self, settings: dict, parent=None, module=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Danbooru Auto-Weight 설정")
        self.resize(960, 750)
        self._module = module  # PromptEngineeringModule 참조 (데이터 공유용)
        self._tag_data = None  # fallback lazy
        self._global_idfs = None
        self._rating_totals = None

        fs = get_scaled_font_size
        ss = get_scaled_size

        tab_style = f"""
            QTabWidget::pane {{
                border: 1px solid {DARK_COLORS['border']};
                background-color: {DARK_COLORS['bg_secondary']};
            }}
            QTabBar::tab {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                padding: 5px 14px;
                font-size: {fs(19)}px;
            }}
            QTabBar::tab:selected {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                border-bottom: 2px solid #B2DFDB;
            }}
        """

        self.setStyleSheet(f"""
            QWidget {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                font-size: {fs(19)}px;
            }}
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {fs(19)}px;
            }}
            QLineEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                padding: 5px;
                font-size: {fs(20)}px;
            }}
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                padding: 6px 14px;
                font-size: {fs(19)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
            {tab_style}
        """)

        hint_style = f"color: #FFFACD; font-size: {fs(18)}px; margin-bottom: 2px;"
        mag_table = PromptEngineeringModule._DANBOORU_MAGNITUDE_TABLE

        # ── 메인 레이아웃: 좌측 설정 | 우측 미리보기 ──
        root = QHBoxLayout(self)
        root.setSpacing(ss(14))

        # ━━━ 좌측: 설정 패널 ━━━
        left = QVBoxLayout()
        left.setSpacing(ss(8))

        left.addWidget(QLabel("가중치 강도"))

        # < [2단계 - 보통] > 컨트롤
        mag_row = QHBoxLayout()
        mag_row.setSpacing(ss(6))
        step_btn_style = f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: #B2DFDB;
                border: 1px solid #B2DFDB;
                border-radius: 4px;
                font-size: {fs(24)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """
        self._mag_down = QPushButton("\u25C0")
        self._mag_down.setFixedSize(ss(44), ss(44))
        self._mag_down.setStyleSheet(step_btn_style)
        self._mag_down.clicked.connect(lambda: self._step_magnitude(-1))
        mag_row.addWidget(self._mag_down)

        self._mag_label = QLabel("")
        self._mag_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mag_label.setStyleSheet(f"""
            background-color: {DARK_COLORS['bg_secondary']};
            border: 1px solid {DARK_COLORS['border']};
            border-radius: 4px;
            padding: 8px;
            font-size: {fs(22)}px;
            font-weight: bold;
        """)
        mag_row.addWidget(self._mag_label, 1)

        self._mag_up = QPushButton("\u25B6")
        self._mag_up.setFixedSize(ss(44), ss(44))
        self._mag_up.setStyleSheet(step_btn_style)
        self._mag_up.clicked.connect(lambda: self._step_magnitude(1))
        mag_row.addWidget(self._mag_up)
        left.addLayout(mag_row)

        # 현재 레벨 설명
        self._mag_desc = QLabel("")
        self._mag_desc.setStyleSheet(hint_style)
        self._mag_desc.setWordWrap(True)
        self._mag_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(self._mag_desc)

        left.addSpacing(ss(8))

        # ── 커스텀 오버라이드 (통합 체크박스 1개) ──
        sep2 = QWidget()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        left.addWidget(sep2)
        left.addSpacing(ss(4))

        self._override_cb = QCheckBox("커스텀 오버라이드")
        self._override_cb.setStyleSheet(f"font-size: {fs(17)}px; color: {DARK_COLORS['text_secondary']};")
        left.addWidget(self._override_cb)

        # 오버라이드 컨테이너 (체크 시 활성화)
        self._override_container = QWidget()
        ov_layout = QVBoxLayout(self._override_container)
        ov_layout.setContentsMargins(ss(8), ss(4), 0, 0)
        ov_layout.setSpacing(ss(4))

        override_edit_style = f"""
            QLineEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                padding: 3px;
                font-size: {fs(17)}px;
            }}
        """

        def _make_param_row(parent_layout, label_text, placeholder, lo, hi, step, hint_text):
            """라벨 + < edit > + hint"""
            lbl = QLabel(label_text)
            lbl.setStyleSheet(f"font-size: {fs(16)}px; color: {DARK_COLORS['text_secondary']};")
            parent_layout.addWidget(lbl)
            row = QHBoxLayout()
            row.setSpacing(ss(4))
            btn_l = QPushButton("<")
            btn_l.setFixedSize(ss(28), ss(24))
            btn_l.setStyleSheet(step_btn_style)
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            edit.setProperty("autocomplete_ignore", True)
            edit.setStyleSheet(override_edit_style)
            vld = QDoubleValidator(lo, hi, 2, self)
            vld.setNotation(QDoubleValidator.Notation.StandardNotation)
            edit.setValidator(vld)
            btn_r = QPushButton(">")
            btn_r.setFixedSize(ss(28), ss(24))
            btn_r.setStyleSheet(step_btn_style)
            def _step(delta):
                try:
                    val = float(edit.text().strip())
                except ValueError:
                    val = float(placeholder)
                edit.setText(str(round(max(lo, min(hi, val + delta)), 2)))
            btn_l.clicked.connect(lambda: _step(-step))
            btn_r.clicked.connect(lambda: _step(step))
            row.addWidget(btn_l)
            row.addWidget(edit, 1)
            row.addWidget(btn_r)
            parent_layout.addLayout(row)
            hint_lbl = QLabel(hint_text)
            hint_lbl.setStyleSheet(f"color: #FFFACD; font-size: {fs(15)}px;")
            hint_lbl.setWordWrap(True)
            parent_layout.addWidget(hint_lbl)
            edit.textChanged.connect(lambda _: self._update_preview())
            return edit

        self._override_scale_edit = _make_param_row(
            ov_layout, "스케일", "0.35", 0.0, 5.0, 0.05,
            "weight = 1.0 ± scale. 실제 범위를 결정하는 핵심 값")
        self._override_min_edit = _make_param_row(
            ov_layout, "하한", "0.80", 0.0, 5.0, 0.05,
            "흔한 태그의 최저 가중치 (권장: 0.4 ~ 1.0)")
        self._override_max_edit = _make_param_row(
            ov_layout, "상한", "1.35", 0.0, 10.0, 0.05,
            "희귀 태그의 최고 가중치 (권장: 1.0 ~ 2.0)")

        ov_layout.addSpacing(ss(4))

        # Rating 블렌드
        blend_lbl = QLabel("Rating 블렌드")
        blend_lbl.setStyleSheet(f"font-size: {fs(16)}px; color: {DARK_COLORS['text_secondary']};")
        ov_layout.addWidget(blend_lbl)
        blend_row = QHBoxLayout()
        blend_row.setSpacing(ss(4))
        self._blend_down = QPushButton("<")
        self._blend_down.setFixedSize(ss(28), ss(24))
        self._blend_down.setStyleSheet(step_btn_style)
        self._blend_down.clicked.connect(lambda: self._step_blend(-0.1))
        self._blend_label = QLabel("")
        self._blend_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._blend_label.setStyleSheet(f"""
            background-color: {DARK_COLORS['bg_secondary']};
            border: 1px solid {DARK_COLORS['border']};
            border-radius: 3px; padding: 3px; font-size: {fs(17)}px;
        """)
        self._blend_up = QPushButton(">")
        self._blend_up.setFixedSize(ss(28), ss(24))
        self._blend_up.setStyleSheet(step_btn_style)
        self._blend_up.clicked.connect(lambda: self._step_blend(0.1))
        blend_row.addWidget(self._blend_down)
        blend_row.addWidget(self._blend_label, 1)
        blend_row.addWidget(self._blend_up)
        ov_layout.addLayout(blend_row)
        blend_hint = QLabel("0.0 = 전역만, 0.3 = 기본, 0.5+ = rating 강하게 반영")
        blend_hint.setStyleSheet(f"color: #FFFACD; font-size: {fs(15)}px;")
        blend_hint.setWordWrap(True)
        ov_layout.addWidget(blend_hint)

        left.addWidget(self._override_container)

        # ── Rating 오버라이드 ──
        left.addSpacing(ss(4))
        sep_rating = QWidget()
        sep_rating.setFixedHeight(1)
        sep_rating.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        left.addWidget(sep_rating)
        left.addSpacing(ss(4))

        self._rating_override_cb = QCheckBox("Rating 오버라이드")
        self._rating_override_cb.setStyleSheet(f"font-size: {fs(17)}px; color: {DARK_COLORS['text_secondary']};")
        left.addWidget(self._rating_override_cb)

        rating_hint = QLabel("IDF 보정에 사용할 rating을 강제 지정합니다.\n자동 판별(parquet/추론) 대신 선택한 rating 기준으로 가중치를 계산합니다.")
        rating_hint.setStyleSheet(f"color: #FFFACD; font-size: {fs(15)}px;")
        rating_hint.setWordWrap(True)
        left.addWidget(rating_hint)

        self._rating_override_container = QWidget()
        ro_layout = QHBoxLayout(self._rating_override_container)
        ro_layout.setContentsMargins(ss(8), ss(4), 0, 0)
        ro_layout.setSpacing(ss(6))

        self._rating_override_btns = {}
        _rating_labels = [("g", "General"), ("s", "Sensitive"), ("q", "Questionable"), ("e", "Explicit")]
        rating_btn_style_off = f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: {fs(16)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """
        rating_btn_style_on = f"""
            QPushButton {{
                background-color: #2E7D32;
                color: #FFFFFF;
                border: 1px solid #4CAF50;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: {fs(16)}px;
                font-weight: bold;
            }}
        """
        self._rating_btn_style_off = rating_btn_style_off
        self._rating_btn_style_on = rating_btn_style_on

        for code, label in _rating_labels:
            btn = QPushButton(f"{label[0]}  ({code})")
            btn.setCheckable(True)
            btn.setStyleSheet(rating_btn_style_off)
            btn.clicked.connect(lambda checked, c=code: self._on_rating_override_clicked(c))
            ro_layout.addWidget(btn, 1)
            self._rating_override_btns[code] = btn

        left.addWidget(self._rating_override_container)
        self._rating_override_container.setEnabled(False)
        self._rating_override_cb.toggled.connect(self._rating_override_container.setEnabled)
        self._rating_override_cb.toggled.connect(lambda _: self._update_preview())
        self._selected_rating_override = 's'  # 기본 선택
        self._rating_override_btns['s'].setChecked(True)
        self._rating_override_btns['s'].setStyleSheet(rating_btn_style_on)

        # 체크 OFF: 컨테이너 비활성, 체크 ON: 활성
        self._override_container.setEnabled(False)
        self._override_cb.toggled.connect(self._override_container.setEnabled)
        self._override_cb.toggled.connect(lambda _: self._update_preview())

        # 오버라이드 내 아무 슬라이더 조작 시 자동 체크 ON
        for edit in [self._override_scale_edit, self._override_min_edit, self._override_max_edit]:
            _orig = edit.focusInEvent
            def _on_focus(event, _orig=_orig):
                self._override_cb.setChecked(True)
                _orig(event)
            edit.focusInEvent = _on_focus

        left.addStretch()

        # 저장/닫기
        btn_row = QHBoxLayout()
        self._save_btn = QPushButton("저장")
        self._save_btn.clicked.connect(self._save)
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(self._save_btn, 3)
        btn_row.addWidget(close_btn, 1)
        left.addLayout(btn_row)

        root.addLayout(left, 2)

        # ━━━ 구분선 ━━━
        sep = QWidget()
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        root.addWidget(sep)

        # ━━━ 우측: 탭 미리보기 패널 ━━━
        right = QVBoxLayout()
        right.setSpacing(ss(4))

        self._tab_widget = QTabWidget()
        self._preview_tabs = {}
        preview_font_style = f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: none;
                padding: 8px;
                font-family: 'Consolas', 'D2Coding', monospace;
                font-size: {fs(19)}px;
                line-height: 1.4;
            }}
        """
        for rating in ["e", "s", "q", "g"]:
            label, _ = self._SAMPLE_CASES[rating]
            te = QTextEdit()
            te.setReadOnly(True)
            te.setProperty("autocomplete_ignore", True)
            te.setStyleSheet(preview_font_style)
            self._preview_tabs[rating] = te
            self._tab_widget.addTab(te, f"{label} ({rating})")
        right.addWidget(self._tab_widget)

        # 가중치 반전 체크박스
        self._invert_cb = QCheckBox("가중치 반전 (고빈도 태그 강화, 저빈도 태그 약화)")
        self._invert_cb.setStyleSheet(f"font-size: {fs(15)}px; color: {DARK_COLORS['text_secondary']}; spacing: {ss(6)}px;")
        self._invert_cb.setChecked(settings.get("invert_weight", False))
        self._invert_cb.toggled.connect(lambda _: self._update_preview())
        right.addWidget(self._invert_cb)

        root.addLayout(right, 4)

        # 초기값 설정
        self._magnitude = settings.get("magnitude", 3)
        self._blend = settings.get("rating_blend", 0.3)
        self._sync_override_edits()
        # 저장된 오버라이드 복원
        if settings.get("override_on"):
            self._override_scale_edit.setText(str(settings.get("override_scale", 0.35)))
            self._override_min_edit.setText(str(settings.get("override_min", 0.80)))
            self._override_max_edit.setText(str(settings.get("override_max", 1.35)))
            self._override_cb.setChecked(True)
        # Rating 오버라이드 복원 (시그널 차단)
        if settings.get("rating_override_on"):
            self._rating_override_cb.blockSignals(True)
            self._rating_override_cb.setChecked(True)
            self._rating_override_cb.blockSignals(False)
            self._rating_override_container.setEnabled(True)
            override_rating = settings.get("rating_override", 's')
            if override_rating in self._rating_override_btns:
                self._set_rating_override_selection(override_rating)
        self._update_mag_display()
        self._update_blend_display()
        self._update_preview()

    def _ensure_tag_data(self):
        """미리보기용 태그 데이터 — 모듈 캐시 공유, 없으면 자체 로드"""
        if self._tag_data is not None:
            return
        # 모듈이 이미 로드한 데이터가 있으면 공유
        if self._module and self._module._danbooru_tag_counts is not None:
            self._tag_data = self._module._danbooru_tag_counts
            self._global_idfs = self._module._danbooru_global_idfs
            self._rating_totals = self._module._danbooru_rating_totals
            return
        # 모듈 데이터 없으면 자체 로드 (설정 윈도우 단독 오픈 시)
        import math
        path = Path(__file__).resolve().parent.parent / "data" / "danbooru_tag_counts_by_rating.json"
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            meta = data.pop("_meta")
            self._rating_totals = meta["total_posts"]
            self._tag_data = data
            global_total = sum(self._rating_totals)
            self._global_idfs = {}
            for tag, counts in data.items():
                gc = sum(counts)
                if gc > 0:
                    self._global_idfs[tag] = -math.log2(gc / global_total)
        except Exception:
            self._tag_data = {}
            self._global_idfs = {}
            self._rating_totals = [1, 1, 1, 1]

    def _set_rating_override_selection(self, code: str):
        """버튼 시각 상태만 갱신 — preview 호출 없음 (초기화/load용)"""
        self._selected_rating_override = code
        for c, btn in self._rating_override_btns.items():
            if c == code:
                btn.setChecked(True)
                btn.setStyleSheet(self._rating_btn_style_on)
            else:
                btn.setChecked(False)
                btn.setStyleSheet(self._rating_btn_style_off)

    def _on_rating_override_clicked(self, code: str):
        """Rating 오버라이드 버튼 클릭 — 라디오 동작 (하나만 선택)"""
        if code not in self._rating_override_btns:
            return
        self._set_rating_override_selection(code)
        self._update_preview()

    def _step_magnitude(self, delta):
        """magnitude 증감 — 오버라이드 해제 + edit을 프리셋 값으로 동기화"""
        self._magnitude = max(1, min(10, self._magnitude + delta))
        self._override_cb.setChecked(False)
        self._sync_override_edits()
        self._update_mag_display()
        self._update_preview()

    def _sync_override_edits(self):
        """오버라이드 edit을 현재 magnitude 프리셋 값으로 동기화"""
        params = PromptEngineeringModule._DANBOORU_MAGNITUDE_TABLE.get(self._magnitude, {})
        self._override_scale_edit.setText(str(params.get("scale", 0.35)))
        self._override_min_edit.setText(str(params.get("min_weight", 0.80)))
        self._override_max_edit.setText(str(params.get("max_weight", 1.35)))

    def _step_blend(self, delta):
        """rating blend 증감"""
        self._blend = round(max(0.0, min(1.0, self._blend + delta)), 1)
        self._update_blend_display()
        self._update_preview()

    def _update_blend_display(self):
        """blend 라벨 갱신"""
        self._blend_label.setText(f"\u03B1 = {self._blend:.1f}")
        self._blend_down.setEnabled(self._blend > 0.0)
        self._blend_up.setEnabled(self._blend < 1.0)

    def _update_mag_display(self):
        """magnitude 라벨/설명 갱신"""
        mag = self._magnitude
        params = PromptEngineeringModule._DANBOORU_MAGNITUDE_TABLE.get(mag, {})
        label = params.get("label", "?")
        min_w = params.get("min_weight", 0)
        max_w = params.get("max_weight", 0)
        self._mag_label.setText(f"{mag}단계 — {label}")
        self._mag_desc.setText(f"흔한 태그 {min_w} ~ 희귀 태그 {max_w}")
        # 경계에서 버튼 비활성
        self._mag_down.setEnabled(mag > 1)
        self._mag_up.setEnabled(mag < 10)

    def _calc_weight(self, tag, rating, scale, min_w, max_w, invert=False):
        """단일 태그의 가중치 계산 — PromptEngineeringModule과 동일 공식"""
        import math
        if not self._global_idfs or tag not in self._global_idfs:
            return None
        g_idf = self._global_idfs[tag]
        ri = PromptEngineeringModule._RATING_INDEX[rating]
        r_total = max(self._rating_totals[ri], 1)
        r_count = self._tag_data[tag][ri]
        alpha = self._blend
        n_low = PromptEngineeringModule._danbooru_norm_low_default
        n_high = PromptEngineeringModule._danbooru_norm_high_default
        if r_count > 0:
            r_idf = -math.log2(r_count / r_total)
            blended = g_idf + alpha * (r_idf - g_idf)
        else:
            blended = g_idf
        norm = max(0.0, min(1.0, (blended - n_low) / (n_high - n_low)))
        if invert:
            norm = 1.0 - norm
        weight = 1.0 + scale * (2 * norm - 1)
        return max(min_w, min(max_w, weight))

    def _update_preview(self):
        """현재 설정으로 각 탭의 샘플 미리보기 갱신"""
        self._ensure_tag_data()
        params = PromptEngineeringModule._DANBOORU_MAGNITUDE_TABLE.get(self._magnitude, {})
        scale = params.get("scale", 0.35)
        min_w = params.get("min_weight", 0.8)
        max_w = params.get("max_weight", 1.3)
        # 오버라이드 적용
        if self._override_cb.isChecked():
            def _pf(edit, default):
                try: return float(edit.text().strip())
                except ValueError: return default
            scale = _pf(self._override_scale_edit, scale)
            min_w = _pf(self._override_min_edit, min_w)
            max_w = _pf(self._override_max_edit, max_w)

        # Rating 오버라이드: 모든 탭의 IDF 보정을 지정 rating 기준으로 계산
        _rating_override_on = self._rating_override_cb.isChecked()
        _rating_override = self._selected_rating_override
        _invert = self._invert_cb.isChecked()

        for tab_idx, (rating, te) in enumerate(self._preview_tabs.items()):
            tab_label, tags = self._SAMPLE_CASES[rating]
            calc_rating = _rating_override if _rating_override_on else rating
            # 탭 제목에 오버라이드 표시
            if _rating_override_on and calc_rating != rating:
                override_label = self._SAMPLE_CASES[calc_rating][0]
                self._tab_widget.setTabText(tab_idx, f"{tab_label} ({rating}) \u2190 {override_label}")
            else:
                self._tab_widget.setTabText(tab_idx, f"{tab_label} ({rating})")
            results = []
            for tag in tags:
                w = self._calc_weight(tag, calc_rating, scale, min_w, max_w, invert=_invert)
                if w is not None:
                    results.append((tag, w))
            results.sort(key=lambda x: x[1])

            lines = []
            max_bar = 12  # 최대 바 길이 (문자 수)
            if results:
                w_lo = min(w for _, w in results)
                w_hi = max(w for _, w in results)
                w_range = w_hi - w_lo if w_hi > w_lo else 1.0
                for tag, w in results:
                    bar_len = int((w - w_lo) / w_range * max_bar)
                    bar = "\u2588" * bar_len
                    lines.append(f"  {tag:25s} {w:.2f} {bar}")
                lines.append("")
                spread_line = f"  spread: {w_hi - w_lo:.2f}"
                if _rating_override_on and calc_rating != rating:
                    spread_line += f"  (IDF: {calc_rating} 기준)"
                lines.append(spread_line)
            te.setPlainText("\n".join(lines))

    def _current_settings(self) -> dict:
        s = {"magnitude": self._magnitude, "rating_blend": self._blend}
        override_on = self._override_cb.isChecked()
        s["override_on"] = override_on
        if override_on:
            def _pf(edit, default):
                try: return float(edit.text().strip())
                except ValueError: return default
            s["override_scale"] = _pf(self._override_scale_edit, 0.35)
            s["override_min"] = _pf(self._override_min_edit, 0.80)
            s["override_max"] = _pf(self._override_max_edit, 1.35)
        # Rating 오버라이드
        s["rating_override_on"] = self._rating_override_cb.isChecked()
        s["rating_override"] = self._selected_rating_override
        # 가중치 반전
        s["invert_weight"] = self._invert_cb.isChecked()
        return s

    def load_settings(self, settings: dict):
        self._magnitude = settings.get("magnitude", 3)
        self._blend = settings.get("rating_blend", 0.3)
        # Rating 오버라이드 복원 (시그널 차단하여 중복 preview 방지)
        self._rating_override_cb.blockSignals(True)
        if settings.get("rating_override_on"):
            self._rating_override_cb.setChecked(True)
            override_rating = settings.get("rating_override", 's')
            if override_rating in self._rating_override_btns:
                self._set_rating_override_selection(override_rating)
            else:
                self._set_rating_override_selection('s')
        else:
            self._rating_override_cb.setChecked(False)
        self._rating_override_cb.blockSignals(False)
        self._rating_override_container.setEnabled(self._rating_override_cb.isChecked())
        # 가중치 반전 복원
        self._invert_cb.setChecked(settings.get("invert_weight", False))
        self._update_mag_display()
        self._update_blend_display()
        self._update_preview()

    def _save(self):
        self.settings_changed.emit(self._current_settings())
        self._save_btn.setText("저장됨!")
        self._save_btn.setEnabled(False)
        QTimer.singleShot(1000, lambda: (
            self._save_btn.setText("저장"),
            self._save_btn.setEnabled(True),
        ))

    def closeEvent(self, event):
        self.settings_changed.emit(self._current_settings())
        super().closeEvent(event)
