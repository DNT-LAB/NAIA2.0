# ui/metadata_viewer.py
"""이미지 메타데이터 뷰어 윈도우"""

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                            QTextEdit, QFrame, QGroupBox, QLineEdit, QCheckBox,
                            QGridLayout, QScrollArea, QWidget, QSplitter, QTabWidget,
                            QSizePolicy, QMessageBox)
from PyQt6.QtGui import QPixmap, QFont
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PIL import Image
from PIL.ImageQt import ImageQt
from typing import Dict, Any, Optional
import json
from legacy_desktop.ui.theme import get_dynamic_styles, DARK_COLORS, DARK_STYLES
from legacy_desktop.ui.scaling_manager import get_scaled_font_size, get_scaled_size
from utils.image_info import ImageMetadataExtractor


class MetadataViewerWindow(QDialog):
    """이미지 메타데이터를 표시하는 윈도우"""
    
    # 시그널 정의
    send_to_img2img = pyqtSignal(Image.Image, dict)
    apply_prompt = pyqtSignal(str, str)  # prompt, negative
    apply_all_settings = pyqtSignal(dict)
    
    def __init__(self, pil_image: Image.Image, metadata: Dict[str, Any],
                 app_context=None, parent=None):
        super().__init__(parent)
        self.pil_image = pil_image
        self.app_context = app_context
        self.dynamic_styles = get_dynamic_styles()

        # 메타데이터 검증 및 보강
        self.metadata = self._validate_and_enhance_metadata(metadata)

        self.setWindowTitle("이미지 메타데이터")
        # Non-modal로 변경
        self.setModal(False)
        self.resize(1400, 800)

        # 창이 항상 위에 표시되도록 설정 (선택적)
        # self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        # 창 닫기 버튼 동작 설정 - DeleteOnClose 제거하여 메모리 관리
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        # 전체 다이얼로그 다크 테마
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        self.init_ui()

    def _validate_and_enhance_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """메타데이터 검증 및 보강 - 필요시 ImageMetadataExtractor로 재추출"""
        # 메타데이터가 비어있거나 주요 필드가 없으면 재추출 시도
        has_prompt = False
        has_params = False

        # Comment 필드가 딕셔너리인지 확인
        if 'Comment' in metadata:
            if isinstance(metadata['Comment'], dict):
                has_prompt = 'prompt' in metadata['Comment']
                has_params = 'steps' in metadata['Comment'] or 'scale' in metadata['Comment']
            elif isinstance(metadata['Comment'], str):
                # Comment가 문자열이면 JSON 파싱 시도
                try:
                    comment_data = json.loads(metadata['Comment'])
                    metadata['Comment'] = comment_data
                    has_prompt = 'prompt' in comment_data
                    has_params = 'steps' in comment_data or 'scale' in comment_data
                except:
                    pass

        # 직접 prompt 필드 확인
        if not has_prompt:
            has_prompt = 'prompt' in metadata

        # parameters 필드 확인
        if not has_params:
            has_params = 'parameters' in metadata

        # 메타데이터가 불완전하면 ImageMetadataExtractor로 재추출
        if not has_prompt or not has_params:
            try:
                extracted = ImageMetadataExtractor.extract_metadata(self.pil_image)
                if extracted:
                    # 기존 메타데이터와 병합 (추출된 데이터 우선)
                    merged = metadata.copy()
                    merged.update(extracted)
                    print("✅ MetadataViewerWindow: ImageMetadataExtractor로 메타데이터 보강 완료")
                    return merged
            except Exception as e:
                print(f"⚠️ MetadataViewerWindow: 메타데이터 재추출 실패: {e}")
        
        # NAI Stealth Info 처리 (구형 호환성)
        # ⚠️ 주의: Software == 'NovelAI'일 때 Comment로 덮어씌우면 Source 필드가 사라짐!
        # 최신 NAI 이미지는 Stealth PNG에 Software, Source가 상위 레벨에 있고
        # Comment 안에 프롬프트와 파라미터가 있는 구조
        if metadata.get('Software') == 'NovelAI':
            # Comment가 딕셔너리이고 상위 레벨에 중요 필드가 있으면 병합
            if isinstance(metadata.get('Comment'), dict):
                comment_data = metadata['Comment']
                # Source, Software, Title, Description 등 상위 필드 보존
                # ✅ Vibe Transfer 필드들도 보존
                important_fields = [
                    'Software', 'Source', 'Title', 'Description', 'Generation time',
                    'reference_image_multiple', 'reference_strength_multiple',
                    'reference_information_extracted_multiple', 'normalize_reference_strength_multiple'
                ]
                preserved = {k: v for k, v in metadata.items() if k in important_fields}

                # Comment 데이터를 기본으로 하고 중요 필드 병합
                result = comment_data.copy()
                result.update(preserved)
                return result
            else:
                # 구형 포맷: Comment로 덮어씌우기 (하위 호환성)
                metadata = metadata.get('Comment')

        return metadata
        
    def init_ui(self):
        """UI 초기화"""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # v4 캐릭터 데이터 사전 추출 (버튼 표시 판단에 필요)
        if 'v4_prompt' in self.metadata and 'caption' in self.metadata.get('v4_prompt', {}):
            self._extract_v4_characters()

        # 왼쪽: 이미지 미리보기
        left_panel = self.create_left_panel()
        
        # 중앙: 프롬프트 정보
        center_panel = self.create_center_panel()
        
        # 오른쪽: 추가 메타데이터
        right_panel = self.create_right_panel()
        
        # 스플리터로 패널 배치
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(center_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 30)  # 왼쪽 30%
        splitter.setStretchFactor(1, 40)  # 중앙 40%
        splitter.setStretchFactor(2, 30)  # 오른쪽 30%
        
        main_layout.addWidget(splitter)
        
    def create_left_panel(self) -> QFrame:
        """왼쪽 패널 - 이미지 미리보기"""
        panel = QFrame()
        panel.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 8px;
            }}
        """)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        
        # 이미지 표시
        image_label = QLabel()
        image_label.setMinimumSize(400, 400)
        image_label.setMaximumSize(600, 600)
        image_label.setStyleSheet(f"""
            background-color: {DARK_COLORS['bg_secondary']}; 
            border: 1px solid {DARK_COLORS['border']};
            border-radius: 4px;
        """)
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setScaledContents(False)
        
        # PIL 이미지를 QPixmap으로 변환
        q_image = ImageQt(self.pil_image.convert("RGBA"))
        pixmap = QPixmap.fromImage(q_image)
        
        # 라벨 크기에 맞춰 스케일
        scaled_pixmap = pixmap.scaled(
            image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        image_label.setPixmap(scaled_pixmap)
        layout.addWidget(image_label)
        
        # 이미지 정보
        width, height = self.pil_image.size
        info_text = f"크기: {width} × {height} | 비율: {width/height:.2f}"
        info_label = QLabel(info_text)
        info_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(14)}px;
            color: {DARK_COLORS['text_secondary']};
            padding: 5px;
            background-color: {DARK_COLORS['bg_secondary']};
            border: 1px solid {DARK_COLORS['border']};
            border-radius: 4px;
        """)
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info_label)
        
        # 모델 정보
        model_info = self._get_model_info()
        model_label = QLabel(f"🤖 모델: {model_info}")
        model_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(15)}px;
            font-weight: bold;
            color: {DARK_COLORS['accent_blue']};
            padding: 8px;
            background-color: {DARK_COLORS['bg_secondary']};
            border: 1px solid {DARK_COLORS['border']};
            border-radius: 4px;
        """)
        layout.addWidget(model_label)
        
        # 버튼들
        button_layout = QVBoxLayout()
        button_layout.setSpacing(5)
        
        # 프롬프트 적용 버튼
        prompt_btn = QPushButton("📝 프롬프트/네거티브 적용")
        prompt_btn.setStyleSheet(self.dynamic_styles['secondary_button'])
        prompt_btn.clicked.connect(self._on_apply_prompt)
        button_layout.addWidget(prompt_btn)
        
        # 설정값 일괄 적용 버튼
        settings_btn = QPushButton("⚙️ 설정값 일괄 적용")
        settings_btn.setStyleSheet(self.dynamic_styles['primary_button'])
        settings_btn.clicked.connect(self._on_apply_settings)
        button_layout.addWidget(settings_btn)

        # 설정값 + 캐릭터 일괄 적용 버튼 (캐릭터 데이터가 있을 때만)
        if self.metadata.get('characters') or self.metadata.get('char_captions'):
            char_settings_btn = QPushButton("🎭 설정값 + 캐릭터 일괄 적용")
            char_settings_btn.setStyleSheet(self.dynamic_styles['primary_button'])
            char_settings_btn.clicked.connect(self._on_apply_settings_with_characters)
            button_layout.addWidget(char_settings_btn)

        # img2img 전송 버튼
        img2img_btn = QPushButton("🖼️ img2img로 전송")
        img2img_btn.setStyleSheet(self.dynamic_styles['secondary_button'])
        img2img_btn.clicked.connect(self._on_send_img2img)
        button_layout.addWidget(img2img_btn)
        
        # 닫기 버튼
        close_btn = QPushButton("닫기")
        close_btn.setStyleSheet(self.dynamic_styles['secondary_button'])
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
        layout.addStretch()
        
        return panel
        
    def create_center_panel(self) -> QFrame:
        """중앙 패널 - 프롬프트 정보"""
        panel = QFrame()
        panel.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 8px;
            }}
        """)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        
        # v4_prompt 형식 처리
        if 'v4_prompt' in self.metadata and 'caption' in self.metadata['v4_prompt']:
            self._extract_v4_characters()
        
        # 프롬프트 섹션 (리사이즈 가능)
        prompt_text = self._get_prompt_text()
        if prompt_text:
            prompt_label = QLabel("📝 프롬프트")
            prompt_label.setStyleSheet(f"""
                font-size: {get_scaled_font_size(19)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
                padding: 5px;
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            """)
            layout.addWidget(prompt_label)
            
            prompt_edit = QTextEdit()
            prompt_edit.setPlainText(prompt_text)
            prompt_edit.setReadOnly(True)
            prompt_edit.setMinimumHeight(150)
            prompt_edit.setStyleSheet(f"""
                QTextEdit {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    color: {DARK_COLORS['text_primary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: 4px;
                    padding: 8px;
                    font-size: {get_scaled_font_size(18)}px;
                    font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                }}
            """)
            layout.addWidget(prompt_edit, 1)  # stretch factor 1 for resize
        
        # 네거티브 프롬프트 섹션 (리사이즈 가능)
        negative_text = self._get_negative_text()
        if negative_text:
            negative_label = QLabel("🚫 네거티브 프롬프트")
            negative_label.setStyleSheet(f"""
                font-size: {get_scaled_font_size(19)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
                padding: 5px;
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            """)
            layout.addWidget(negative_label)
            
            negative_edit = QTextEdit()
            negative_edit.setPlainText(negative_text)
            negative_edit.setReadOnly(True)
            negative_edit.setMinimumHeight(100)
            negative_edit.setStyleSheet(f"""
                QTextEdit {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    color: {DARK_COLORS['text_primary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: 4px;
                    padding: 8px;
                    font-size: {get_scaled_font_size(18)}px;
                    font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                }}
            """)
            layout.addWidget(negative_edit, 1)  # stretch factor 1 for resize

        comfy_summary = self._get_comfyui_summary_text()
        if comfy_summary:
            workflow_label = QLabel("🧩 ComfyUI 워크플로우")
            workflow_label.setStyleSheet(f"""
                font-size: {get_scaled_font_size(19)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
                padding: 5px;
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            """)
            layout.addWidget(workflow_label)

            workflow_edit = QTextEdit()
            workflow_edit.setPlainText(comfy_summary)
            workflow_edit.setReadOnly(True)
            workflow_edit.setMinimumHeight(120)
            workflow_edit.setStyleSheet(f"""
                QTextEdit {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    color: {DARK_COLORS['text_primary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: 4px;
                    padding: 8px;
                    font-size: {get_scaled_font_size(16)}px;
                    font-family: 'Consolas', 'Monaco', monospace;
                }}
            """)
            layout.addWidget(workflow_edit, 1)
        
        # 캐릭터 프롬프트 (NAI v4)
        if self.metadata.get('characters') or self.metadata.get('char_captions'):
            char_label = QLabel("🎭 캐릭터 프롬프트 (NAI v4)")
            char_label.setStyleSheet(f"""
                font-size: {get_scaled_font_size(19)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
                padding: 5px;
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            """)
            layout.addWidget(char_label)
            
            char_text = self._format_character_prompts()
            char_edit = QTextEdit()
            char_edit.setPlainText(char_text)
            char_edit.setReadOnly(True)
            char_edit.setMinimumHeight(100)
            char_edit.setStyleSheet(f"""
                QTextEdit {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    color: {DARK_COLORS['text_primary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: 4px;
                    padding: 8px;
                    font-size: {get_scaled_font_size(18)}px;
                    font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                }}
            """)
            layout.addWidget(char_edit, 1)  # stretch factor 1 for resize
            
        # Vibe Transfer 복원 버튼 추가 (vibe 데이터가 있을 때만)
        if self._has_vibe_transfer_data():
            vibe_button = self._create_vibe_restore_button()
            if vibe_button:  # 모델 호환성 체크 후 버튼이 생성된 경우만 추가
                layout.addWidget(vibe_button)
        
        return panel
    
    def create_right_panel(self) -> QFrame:
        """오른쪽 패널 - 추가 메타데이터"""
        panel = QFrame()
        panel.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 8px;
            }}
        """)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        
        # 탭 위젯으로 구성
        tab_widget = QTabWidget()
        tab_widget.setStyleSheet(DARK_STYLES.get('dark_tabs', ''))
        
        # 파라미터 탭
        params_tab = self.create_params_tab()
        tab_widget.addTab(params_tab, "⚙️ 파라미터")
        
        # 원본 데이터 탭
        raw_tab = self.create_raw_tab()
        tab_widget.addTab(raw_tab, "📄 원본 데이터")
        
        layout.addWidget(tab_widget)
        
        return panel
    
    def create_params_tab(self) -> QWidget:
        """파라미터 탭"""
        widget = QWidget()
        widget.setStyleSheet(f"""
            background-color: {DARK_COLORS['bg_secondary']};
        """)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 스크롤 영역
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: none;
            }}
        """)
        
        scroll_widget = QWidget()
        scroll_layout = QGridLayout(scroll_widget)
        scroll_layout.setSpacing(10)
        scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        
        # 파라미터 추출 및 정리
        extracted_params = self._extract_all_parameters()
        
        row = 0
        
        # 주요 생성 파라미터 (순서대로)
        main_params = [
            ('steps', 'Steps'),
            ('scale', 'CFG Scale'),
            ('uncond_scale', 'UC Strength'),
            ('cfg_rescale', 'CFG Rescale'),
            ('seed', 'Seed'),
            ('sampler', 'Sampler'),
            ('noise_schedule', 'Scheduler'),
            ('sm', 'SMEA'),
            ('sm_dyn', 'SMEA+DYN'),
            ('VAR+', 'VAR+')
        ]
        
        # 해상도 추가
        if self.pil_image:
            width, height = self.pil_image.size
            self._add_parameter_row(scroll_layout, row, 'Resolution', f"{width} x {height}")
            row += 1
        
        # 주요 파라미터 표시
        for param_key, display_name in main_params:
            if param_key in extracted_params:
                self._add_parameter_row(scroll_layout, row, display_name, extracted_params[param_key])
                row += 1
        
        # 구분선 추가
        if row > 0:
            separator = QFrame()
            separator.setFrameShape(QFrame.Shape.HLine)
            separator.setStyleSheet(f"""
                QFrame {{
                    background-color: {DARK_COLORS['border']};
                    max-height: 1px;
                    margin: 10px 0px;
                }}
            """)
            scroll_layout.addWidget(separator, row, 0, 1, 2)
            row += 1
        
        # 추가 파라미터
        additional_params = [
            ('enable_hr', 'Hires Fix'),
            ('hr_scale', 'Hires Scale'),
            ('hr_upscaler', 'Upscaler'),
            ('denoising_strength', 'Denoising'),
            ('strength', 'Img2Img Strength'),
            ('model', 'Model')
        ]
        
        for param_key, display_name in additional_params:
            if param_key in extracted_params:
                self._add_parameter_row(scroll_layout, row, display_name, extracted_params[param_key])
                row += 1
        
        # 메타데이터 필드
        displayed_keys = {key for key, _ in main_params}
        displayed_keys.update({key for key, _ in additional_params})
        displayed_keys.update({'width', 'height'})
        remaining_params = [
            key for key in extracted_params.keys()
            if key not in displayed_keys
        ]

        if remaining_params:
            separator = QFrame()
            separator.setFrameShape(QFrame.Shape.HLine)
            separator.setStyleSheet(f"""
                QFrame {{
                    background-color: {DARK_COLORS['border']};
                    max-height: 1px;
                    margin: 10px 0px;
                }}
            """)
            scroll_layout.addWidget(separator, row, 0, 1, 2)
            row += 1

            for key in remaining_params:
                self._add_parameter_row(scroll_layout, row, key.replace('_', ' ').title(), extracted_params[key])
                row += 1

        meta_fields = ['Software', 'Source', 'Title', 'Description']
        has_meta = False
        for field in meta_fields:
            if field in self.metadata:
                if not has_meta:
                    # 구분선 추가
                    separator = QFrame()
                    separator.setFrameShape(QFrame.Shape.HLine)
                    separator.setStyleSheet(f"""
                        QFrame {{
                            background-color: {DARK_COLORS['border']};
                            max-height: 1px;
                            margin: 10px 0px;
                        }}
                    """)
                    scroll_layout.addWidget(separator, row, 0, 1, 2)
                    row += 1
                    has_meta = True
                
                self._add_parameter_row(scroll_layout, row, field, self.metadata[field])
                row += 1
        
        # 빈 공간 추가 (위쪽 정렬 유지)
        spacer = QWidget()
        spacer.setSizePolicy(
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Expanding
        )
        scroll_layout.addWidget(spacer, row, 0, 1, 2)
        
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)
        
        return widget
    
    def _add_parameter_row(self, layout: QGridLayout, row: int, label_text: str, value: Any):
        """파라미터 행 추가"""
        from PyQt6.QtWidgets import QSizePolicy
        
        # 라벨
        label = QLabel(f"{label_text}:")
        label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(14)}px;
            color: {DARK_COLORS['text_secondary']};
            font-weight: bold;
            padding-right: 10px;
        """)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        # 값 위젯
        if isinstance(value, bool):
            widget_val = QCheckBox()
            widget_val.setChecked(value)
            widget_val.setEnabled(False)
            widget_val.setStyleSheet(DARK_STYLES.get('dark_checkbox', ''))
        else:
            widget_val = QLineEdit(str(value))
            widget_val.setReadOnly(True)
            widget_val.setMinimumWidth(150)
            widget_val.setStyleSheet(f"""
                QLineEdit {{
                    background-color: {DARK_COLORS['bg_primary']};
                    color: {DARK_COLORS['text_primary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: 3px;
                    padding: 5px 8px;
                    font-size: {get_scaled_font_size(13)}px;
                    font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                }}
            """)
        
        layout.addWidget(label, row, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(widget_val, row, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    
    def _extract_all_parameters(self) -> Dict[str, Any]:
        """모든 소스에서 파라미터 추출 및 통합"""
        params = {}
        
        # 1. Comment 필드에서 추출 (NAI)
        if 'Comment' in self.metadata:
            try:
                comment_data = json.loads(self.metadata['Comment'])
                # NAI 파라미터 매핑
                if 'steps' in comment_data:
                    params['steps'] = comment_data['steps']
                if 'scale' in comment_data:
                    params['scale'] = comment_data['scale']
                if 'cfg_rescale' in comment_data:
                    params['cfg_rescale'] = comment_data['cfg_rescale']
                if 'uncond_scale' in comment_data:
                    params['uncond_scale'] = comment_data.get('uncond_scale', 1.0)
                if 'seed' in comment_data:
                    params['seed'] = comment_data['seed']
                if 'sampler' in comment_data:
                    params['sampler'] = comment_data['sampler']
                if 'noise_schedule' in comment_data:
                    params['noise_schedule'] = comment_data['noise_schedule']
                if 'sm' in comment_data:
                    params['sm'] = comment_data['sm']
                if 'sm_dyn' in comment_data:
                    params['sm_dyn'] = comment_data['sm_dyn']
                if 'skip_cfg_above_sigma' in comment_data:
                    # VAR+ 파라미터 - 0 또는 null이 아니면 True
                    skip_val = comment_data['skip_cfg_above_sigma']
                    params['VAR+'] = bool(skip_val and skip_val != 0)
                    
                # 추가 파라미터도 가져오기
                for key in ['width', 'height', 'strength', 'model']:
                    if key in comment_data:
                        params[key] = comment_data[key]
            except:
                pass
        
        # 2. parameters 필드에서 추출
        if 'parameters' in self.metadata:
            meta_params = self.metadata['parameters']
            # WebUI 파라미터 매핑
            if 'steps' in meta_params:
                params['steps'] = meta_params['steps']
            if 'cfg_scale' in meta_params:
                params['scale'] = meta_params['cfg_scale']
            if 'seed' in meta_params:
                params['seed'] = meta_params['seed']
            if 'sampler_name' in meta_params:
                params['sampler'] = meta_params['sampler_name']
            elif 'sampler' in meta_params:
                params['sampler'] = meta_params['sampler']
            if 'scheduler' in meta_params:
                params['noise_schedule'] = meta_params['scheduler']
            if 'denoising_strength' in meta_params:
                params['denoising_strength'] = meta_params['denoising_strength']
            if 'enable_hr' in meta_params:
                params['enable_hr'] = meta_params['enable_hr']
            if 'hr_scale' in meta_params:
                params['hr_scale'] = meta_params['hr_scale']
            if 'hr_upscaler' in meta_params:
                params['hr_upscaler'] = meta_params['hr_upscaler']
            if 'model' in meta_params:
                params['model'] = meta_params['model']
            
            # 나머지 파라미터도 추가
            for key, value in meta_params.items():
                if key not in params:
                    params[key] = value
        
        # 3. 직접 필드에서 추출
        direct_fields = ['steps', 'scale', 'seed', 'sampler', 'cfg_rescale', 
                        'uncond_scale', 'sm', 'sm_dyn', 'noise_schedule', 'skip_cfg_above_sigma']
        for field in direct_fields:
            if field in self.metadata and field not in params:
                if field == 'skip_cfg_above_sigma':
                    # VAR+ 파라미터로 변환
                    skip_val = self.metadata[field]
                    params['VAR+'] = bool(skip_val and skip_val != 0)
                else:
                    params[field] = self.metadata[field]
        
        for field in ['workflow_nodes', 'workflow_type', 'clip_model', 'vae', 'batch_size', 'sampling_mode']:
            if field in self.metadata and field not in params:
                params[field] = self.metadata[field]

        return params
    
    def create_raw_tab(self) -> QWidget:
        """원본 데이터 탭"""
        widget = QWidget()
        widget.setStyleSheet(f"""
            background-color: {DARK_COLORS['bg_secondary']};
        """)
        layout = QVBoxLayout(widget)
        
        # JSON 형식으로 표시
        raw_edit = QTextEdit()
        
        # 민감한 정보 필터링
        safe_metadata = {k: v for k, v in self.metadata.items() 
                        if k not in ['exif', 'icc_profile']}
        
        try:
            raw_text = json.dumps(safe_metadata, indent=2, ensure_ascii=False)
        except:
            raw_text = str(safe_metadata)
        
        raw_edit.setPlainText(raw_text)
        raw_edit.setReadOnly(True)
        raw_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 8px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: {get_scaled_font_size(12)}px;
            }}
        """)
        
        layout.addWidget(raw_edit)
        
        return widget
    
    def _get_prompt_text(self) -> str:
        """프롬프트 텍스트 추출"""
        # 1. Comment 필드가 딕셔너리인 경우 (이미 파싱됨)
        if 'Comment' in self.metadata:
            comment = self.metadata['Comment']
            if isinstance(comment, dict) and 'prompt' in comment:
                return comment['prompt']
            # Comment가 문자열이면 JSON 파싱 시도
            elif isinstance(comment, str):
                try:
                    comment_data = json.loads(comment)
                    if 'prompt' in comment_data:
                        return comment_data['prompt']
                except:
                    pass

        # 2. 직접 prompt 필드
        if 'prompt' in self.metadata:
            return self.metadata['prompt']

        # 3. Description 필드 (NAI의 경우)
        if 'Description' in self.metadata:
            return self.metadata['Description']

        return ""
    
    def _get_negative_text(self) -> str:
        """네거티브 프롬프트 텍스트 추출"""
        # 1. Comment 필드가 딕셔너리인 경우 (이미 파싱됨)
        if 'Comment' in self.metadata:
            comment = self.metadata['Comment']
            if isinstance(comment, dict) and 'uc' in comment:
                return comment['uc']
            # Comment가 문자열이면 JSON 파싱 시도
            elif isinstance(comment, str):
                try:
                    comment_data = json.loads(comment)
                    if 'uc' in comment_data:
                        return comment_data['uc']
                except:
                    pass

        # 2. 직접 uc 또는 negative 필드
        if 'uc' in self.metadata:
            return self.metadata['uc']
        if 'negative' in self.metadata:
            return self.metadata['negative']

        return ""
    
    def _get_model_info(self) -> str:
        """모델 정보 추출"""
        # Software 필드 확인 (NAI)
        if 'Software' in self.metadata:
            software = self.metadata.get('Software', '')
            if software == 'NovelAI':
                # Source 필드에서 모델 정보 추출
                source = self.metadata.get('Source', '')
                if source:
                    return source
                
                # Comment 필드에서 추가 정보 확인
                if 'Comment' in self.metadata:
                    try:
                        comment_data = json.loads(self.metadata['Comment'])
                        if 'source' in comment_data:
                            return comment_data['source']
                    except:
                        pass
                
                return 'NovelAI'
            return software
        
        # model 필드 확인 (WebUI)
        if 'model' in self.metadata.get('parameters', {}):
            return self.metadata['parameters']['model']
        
        # checkpoint 필드 확인  
        if 'Model' in self.metadata:
            return self.metadata['Model']
        
        # type 필드로 폴백
        type_info = self.metadata.get('type', 'unknown')
        if type_info == 'nai':
            return 'NovelAI'
        elif type_info == 'webui':
            return 'Stable Diffusion WebUI'
        
        return type_info.upper()
    
    def _get_comfyui_summary_text(self) -> str:
        """Return a compact workflow summary for ComfyUI metadata."""
        if self.metadata.get('type') != 'comfyui':
            return ""

        params = self._extract_all_parameters()
        lines = []

        workflow_type = params.get('workflow_type')
        if workflow_type:
            lines.append(f"Workflow Type: {workflow_type}")

        workflow_nodes = self.metadata.get('workflow_nodes')
        if workflow_nodes:
            lines.append(f"Detected Nodes: {workflow_nodes}")

        for key, label in [
            ('model', 'Model'),
            ('clip_model', 'CLIP'),
            ('vae', 'VAE'),
            ('sampler', 'Sampler'),
            ('noise_schedule', 'Scheduler'),
            ('steps', 'Steps'),
            ('scale', 'CFG Scale'),
            ('cfg_rescale', 'CFG Rescale'),
            ('seed', 'Seed'),
            ('batch_size', 'Batch Size'),
            ('sampling_mode', 'Sampling Mode'),
        ]:
            value = params.get(key)
            if value is not None and value != '':
                lines.append(f"{label}: {value}")

        if 'workflow' in self.metadata:
            lines.append("Workflow JSON: available")
        if 'prompt_api' in self.metadata:
            lines.append("Prompt API JSON: available")

        return "\n".join(lines)

    def _extract_v4_characters(self):
        """NAI v4 형식에서 캐릭터 프롬프트 추출"""
        try:
            if 'v4_prompt' in self.metadata:
                self.metadata['characters'] = []
                if 'caption' in self.metadata['v4_prompt'] and 'char_captions' in self.metadata['v4_prompt']['caption']:
                    for char_data in self.metadata['v4_prompt']['caption']['char_captions']:
                        if isinstance(char_data, dict) and 'char_caption' in char_data:
                            self.metadata['characters'].append(char_data['char_caption'])
                        elif isinstance(char_data, str):
                            self.metadata['characters'].append(char_data)
            
            if 'v4_negative_prompt' in self.metadata:
                self.metadata['characters_uc'] = []
                if 'caption' in self.metadata['v4_negative_prompt'] and 'char_captions' in self.metadata['v4_negative_prompt']['caption']:
                    for char_data in self.metadata['v4_negative_prompt']['caption']['char_captions']:
                        if isinstance(char_data, dict) and 'char_caption' in char_data:
                            self.metadata['characters_uc'].append(char_data['char_caption'])
                        elif isinstance(char_data, str):
                            self.metadata['characters_uc'].append(char_data)
        except Exception as e:
            print(f"Error extracting v4 characters: {e}")
    
    def _format_character_prompts(self) -> str:
        """캐릭터 프롬프트 포맷팅"""
        text = ""
        characters = self.metadata.get('characters', [])
        characters_uc = self.metadata.get('characters_uc', [])
        
        if not characters and 'char_captions' in self.metadata:
            characters = self.metadata.get('char_captions', [])
        
        for i, char in enumerate(characters):
            text += f"C{i+1} Prompt: {char}\n"
            if i < len(characters_uc):
                text += f"C{i+1} Negative: {characters_uc[i]}\n"
            text += "\n"
        
        return text.strip()
    
    def _on_apply_prompt(self):
        """프롬프트 적용"""
        try:
            prompt = self._get_prompt_text()
            negative = self._get_negative_text()
            
            # 시그널 발송 (기존 연결된 슬롯이 있을 경우를 위해)
            self.apply_prompt.emit(prompt, negative)
            
            # app_context를 통한 직접 적용 (시그널 연결이 없을 경우를 위해)
            if self.app_context and hasattr(self.app_context, 'main_window'):
                main_window = self.app_context.main_window
                
                # 메인 프롬프트 적용
                if hasattr(main_window, 'main_prompt_textedit'):
                    main_window.main_prompt_textedit.setPlainText(prompt)
                elif hasattr(main_window, 'prompt_input'):
                    main_window.prompt_input.setPlainText(prompt)
                    
                # 네거티브 프롬프트 적용
                if hasattr(main_window, 'negative_prompt_textedit'):
                    main_window.negative_prompt_textedit.setPlainText(negative)
                elif hasattr(main_window, 'negative_prompt_input'):
                    main_window.negative_prompt_input.setPlainText(negative)
                    
                print(f"✅ 메타데이터에서 프롬프트 적용 완료 (직접 방식)")
                if hasattr(main_window, 'status_bar'):
                    main_window.status_bar.showMessage("프롬프트가 적용되었습니다.", 3000)
            
            # TODO(web-dialog): 원래 QMessageBox(Information) "적용 완료" — Web Shell 토스트로 재구현 필요.
            print("[Dialog/INFO] 적용 완료: 프롬프트가 적용되었습니다.")

        except Exception as e:
            # TODO(web-dialog): 원래 QMessageBox.critical "오류" — Web Shell error 토스트로 재구현 필요.
            print(f"[Dialog/ERROR] 오류: 프롬프트 적용 실패 — {str(e)}")
        
    def _on_apply_settings(self):
        """설정값 일괄 적용"""
        # 경고 메시지는 NAIA_cold_v4.py의 apply_settings_from_metadata에서 표시하므로 여기서는 제외
        settings = {
            'prompt': self._get_prompt_text(),
            'negative': self._get_negative_text()
        }

        # 소스 모드 식별을 위한 메타데이터 포함
        if 'Software' in self.metadata:
            settings['Software'] = self.metadata['Software']
        if 'type' in self.metadata:
            settings['type'] = self.metadata['type']
        for key in ['workflow', 'workflow_api', 'prompt_api', 'workflow_type']:
            if key in self.metadata:
                settings[key] = self.metadata[key]

        # ✅ _extract_all_parameters() 활용하여 모든 파라미터 추출
        # (Comment, parameters, 직접 필드 등 모든 소스에서 추출)
        extracted_params = self._extract_all_parameters()
        settings.update(extracted_params)

        # 이미지 크기 추가 (덮어쓰기)
        settings['width'] = self.pil_image.width
        settings['height'] = self.pil_image.height

        self.apply_all_settings.emit(settings)
        # 적용 완료 메시지는 표시하지 않음

    def _on_apply_settings_with_characters(self):
        """설정값 + 캐릭터 일괄 적용"""
        settings = {
            'prompt': self._get_prompt_text(),
            'negative': self._get_negative_text()
        }

        if 'Software' in self.metadata:
            settings['Software'] = self.metadata['Software']
        if 'type' in self.metadata:
            settings['type'] = self.metadata['type']
        for key in ['workflow', 'workflow_api', 'prompt_api', 'workflow_type']:
            if key in self.metadata:
                settings[key] = self.metadata[key]

        extracted_params = self._extract_all_parameters()
        settings.update(extracted_params)

        settings['width'] = self.pil_image.width
        settings['height'] = self.pil_image.height

        # 캐릭터 데이터 포함
        characters = self.metadata.get('characters', [])
        if not characters:
            characters = self.metadata.get('char_captions', [])
        characters_uc = self.metadata.get('characters_uc', [])

        if characters:
            settings['characters'] = characters
            settings['characters_uc'] = characters_uc

        self.apply_all_settings.emit(settings)

    def _on_send_img2img(self):
        """img2img로 전송"""
        self.send_to_img2img.emit(self.pil_image, self.metadata)
        # TODO(web-dialog): 원래 QMessageBox(Information) "전송 완료" — Web Shell 토스트로 재구현 필요.
        print("[Dialog/INFO] 전송 완료: 이미지가 img2img로 전송되었습니다.")
    
    def _has_vibe_transfer_data(self) -> bool:
        """메타데이터에 vibe transfer 데이터가 있는지 확인"""
        vibe_fields = ['reference_image_multiple',
                       'reference_strength_multiple']

        for field in vibe_fields:
            if field in self.metadata and self.metadata[field]:
                return True

        return False
    
    def _get_model_compatibility(self) -> Optional[str]:
        """메타데이터의 모델과 현재 모델의 호환성 확인"""
        # 메타데이터에서 모델 정보 확인
        model_hash = self.metadata.get('Source', '')

        # 모델 매핑
        model_map = {
            'NovelAI Diffusion V4.5 4BDE2A90': 'NAID4.5F',  # NovelAI Diffusion V4.5 Full
            'NovelAI Diffusion V4.5 C02D4F98': 'NAID4.5C',  # NovelAI Diffusion V4.5 Curated
            'NovelAI Diffusion V4 7ABFFA2A': 'NAID4.0C',  # NovelAI Diffusion V4 Curated
            'NovelAI Diffusion V4 37442FCA': 'NAID4.0F',  # NovelAI Diffusion V4 Full
            'Stable Diffusion XL 7BCCAA2C': None         # NAID3 - 지원하지 않음
        }

        # 해시 매칭
        for hash_key, model_name in model_map.items():
            if hash_key in model_hash:
                return model_name

        return None
    
    def _create_vibe_restore_button(self) -> Optional[QPushButton]:
        """Vibe Transfer 복원 버튼 생성"""
        required_model = self._get_model_compatibility()

        # NAID3 모델은 지원하지 않음
        if required_model is None:
            return None
        
        # 현재 모델 확인
        current_model = None
        if hasattr(self.app_context, 'main_window') and hasattr(self.app_context.main_window, 'model_combo'):
            current_text = self.app_context.main_window.model_combo.currentText()
            # 모델명에서 NAID 형식 추출
            if 'NAID4.5F' in current_text:
                current_model = 'NAID4.5F'
            elif 'NAID4.5C' in current_text:
                current_model = 'NAID4.5C'
            elif 'NAID4.0C' in current_text:
                current_model = 'NAID4.0C'
            elif 'NAID4.0F' in current_text:
                current_model = 'NAID4.0F'
        
        # 버튼 생성
        vibe_button = QPushButton(f"📦 Vibe Transfer 복원 ({required_model})")
        vibe_button.setStyleSheet(f"""
            QPushButton {{
                background-color: #3A2F5F;
                border: 1px solid #5A4A8F;
                color: #C8B8FF;
                font-size: {get_scaled_font_size(19)}px;
                font-weight: 500;
                border-radius: 4px;
                padding: 10px 24px;
                margin-top: 10px;
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
            }}
            QPushButton:hover {{
                background-color: #4A3F6F;
                border: 1px solid #6A5A9F;
            }}
            QPushButton:pressed {{
                background-color: #2A1F4F;
            }}
            QPushButton:disabled {{
                background-color: #2A2A2A;
                color: #666666;
                border: 1px solid #444444;
            }}
        """)
        
        # 모델 호환성 체크
        if current_model != required_model:
            vibe_button.setEnabled(False)
            vibe_button.setToolTip(f"❌ 현재 모델이 {required_model}이 아닙니다.\n이미지의 vibe는 {required_model} 모델에서만 복원 가능합니다.")
        else:
            vibe_button.setEnabled(True)
            vibe_button.setToolTip(f"✅ Vibe Transfer 데이터를 복원합니다.")
            vibe_button.clicked.connect(self._on_restore_vibe_transfer)

        return vibe_button
    
    def _on_restore_vibe_transfer(self):
        """Vibe Transfer 데이터를 복원하여 모듈에 추가"""
        try:
            # VibeTransferModule 찾기
            if not self.app_context or not hasattr(self.app_context, 'main_window'):
                QMessageBox.warning(self, "경고", "Vibe Transfer 모듈을 찾을 수 없습니다.")
                return
            
            main_window = self.app_context.main_window
            if not hasattr(main_window, 'middle_section_controller'):
                QMessageBox.warning(self, "경고", "Vibe Transfer 모듈을 찾을 수 없습니다.")
                return
                
            vibe_module = main_window.middle_section_controller.get_module_instance("VibeTransferModule")
            if not vibe_module:
                QMessageBox.warning(self, "경고", "Vibe Transfer 모듈이 로드되지 않았습니다.")
                return
            
            # vibe 데이터 추출
            import hashlib
            ref_img_multiple = self.metadata.get('reference_image_multiple') or []
            ref_str_multiple = self.metadata.get('reference_strength_multiple') or []
            ref_ie_multiple  = self.metadata.get('reference_information_extracted_multiple') or []
            source_model = self._get_model_compatibility()

            if not ref_img_multiple:
                QMessageBox.warning(self, "경고", "Metadata에 유효한 Vibe Transfer 데이터가 없습니다.")
                return

            # reference_image_multiple의 각 항목 = 독립적인 vibe 1개 → 프레임 1개씩 생성
            added_count = 0
            for i, encoding in enumerate(ref_img_multiple):
                per_vibe_data = {
                    'reference_image_multiple': [encoding],
                    'reference_strength_multiple': [ref_str_multiple[i]] if i < len(ref_str_multiple) else [0.6],
                    'reference_information_extracted_multiple': [ref_ie_multiple[i]] if i < len(ref_ie_multiple) else [],
                    'source_model': source_model,
                }
                per_hash = hashlib.sha256(encoding.encode()).hexdigest()[:16]
                no_image_path = f"no_image_metadata_{per_hash}"
                frame = vibe_module._add_vibe_frame_from_metadata(no_image_path, per_vibe_data)
                if frame:
                    added_count += 1

            QMessageBox.information(self, "성공", f"Vibe Transfer {added_count}개가 복원되었습니다.")
            
        except Exception as e:
            print(f"Error restoring vibe transfer: {e}")
            QMessageBox.critical(self, "오류", f"Vibe Transfer 복원 실패:\n{str(e)}")
