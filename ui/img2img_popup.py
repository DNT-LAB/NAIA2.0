from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, pyqtSignal
from PIL import Image
from PIL.ImageQt import ImageQt
from .theme import DARK_STYLES, DARK_COLORS, get_dynamic_styles
from .scaling_manager import get_scaled_font_size
from utils.image_info import ImageMetadataExtractor
from .metadata_viewer import MetadataViewerWindow

class Img2ImgPopup(QDialog):
    img2img_requested = pyqtSignal(Image.Image)
    inpaint_requested = pyqtSignal(Image.Image)
    import_vibe_transfer_requested = pyqtSignal(Image.Image)

    def __init__(self, pil_image: Image.Image,  app_context=None, parent=None):
        super().__init__(parent)
        self.pil_image = pil_image
        self.app_context = app_context
        self.parent_widget = parent
        
        # 메타데이터 확인
        self.has_metadata = ImageMetadataExtractor.has_metadata(pil_image)
        self.metadata = None
        if self.has_metadata:
            self.metadata = ImageMetadataExtractor.extract_metadata(pil_image)
        
        self.setWindowTitle("이미지 작업 선택")
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        
        # 팝업 스타일링
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border_light']};
                border-radius: 8px;
            }}
        """)
        
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 10, 15, 15)
        main_layout.setSpacing(10)
        
        # 1. 타이틀(헤더)
        title_label = QLabel("이미지가 감지되었습니다. 수행할 작업을 선택하세요.")
        title_label.setStyleSheet(f"{DARK_STYLES['label_style']} font-weight: 600;")
        main_layout.addWidget(title_label)
        
        # 2. 이미지 미리보기
        image_preview_label = QLabel()
        image_preview_label.setFixedSize(512, 512)
        image_preview_label.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']}; border-radius: 4px;")
        image_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # PIL 이미지를 QPixmap으로 변환하고 리사이즈
        q_image = ImageQt(self.pil_image.convert("RGBA"))
        pixmap = QPixmap.fromImage(q_image)
        scaled_pixmap = pixmap.scaled(512, 512, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        image_preview_label.setPixmap(scaled_pixmap)
        main_layout.addWidget(image_preview_label)
        
        # 3. 버튼들
        img2img_button = QPushButton("Img2Img 탭으로 이미지 전송")
        img2img_button.setFixedSize(512, 40)
        img2img_button.setStyleSheet(DARK_STYLES['primary_button'])
        img2img_button.clicked.connect(self.on_img2img_selected)
        main_layout.addWidget(img2img_button)
        
        inpaint_button = QPushButton("Inpaint 탭으로 이미지 전송")
        inpaint_button.setFixedSize(512, 40)
        inpaint_button.setStyleSheet(DARK_STYLES['secondary_button'])
        inpaint_button.clicked.connect(self.on_inpaint_selected)
        main_layout.addWidget(inpaint_button)
        
        # 메타데이터 버튼 (메타데이터가 있을 때만 표시)
        if self.has_metadata:
            metadata_button = QPushButton("📄 메타데이터 읽기")
            metadata_button.setFixedSize(512, 40)
            # 메타데이터가 있으면 강조 스타일 적용 (동적 폰트 크기 사용)
            font_size = get_scaled_font_size(19)  # 다른 버튼과 동일한 크기
            metadata_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: #2D5016;
                    border: 1px solid #4A7C28;
                    color: #A8E6CF;
                    font-size: {font_size}px;
                    font-weight: 500;
                    border-radius: 4px;
                    padding: 8px 24px;
                    font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                }}
                QPushButton:hover {{
                    background-color: #3A6B1E;
                    border: 1px solid #5A8C38;
                }}
                QPushButton:pressed {{
                    background-color: #254011;
                }}
            """)
            metadata_button.clicked.connect(self.on_metadata_view)
            main_layout.addWidget(metadata_button)
        
        # Import Vibe Transfer 버튼 (NAI 모드일 때만 표시)
        if self.app_context and hasattr(self.app_context, 'get_api_mode'):
            if self.app_context.get_api_mode() == "NAI":
                import_vibe_button = QPushButton("📦 Import Vibe Transfer")
                import_vibe_button.setFixedSize(512, 40)
                
                # 동적 폰트 크기 사용
                font_size = get_scaled_font_size(19)
                import_vibe_button.setStyleSheet(f"""
                    QPushButton {{
                        background-color: #3A2F5F;
                        border: 1px solid #5A4A8F;
                        color: #C8B8FF;
                        font-size: {font_size}px;
                        font-weight: 500;
                        border-radius: 4px;
                        padding: 8px 24px;
                        font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                    }}
                    QPushButton:hover {{
                        background-color: #4A3F6F;
                        border: 1px solid #6A5A9F;
                    }}
                    QPushButton:pressed {{
                        background-color: #2A1F4F;
                    }}
                """)
                import_vibe_button.clicked.connect(self.on_import_vibe_transfer)
                main_layout.addWidget(import_vibe_button)
        
        # 4. 닫기 버튼
        close_button = QPushButton("닫기")
        close_button.setFixedSize(512, 40)
        close_button.setStyleSheet(DARK_STYLES['secondary_button'])
        close_button.clicked.connect(self.reject) # 다이얼로그 닫기
        main_layout.addWidget(close_button)

    def on_img2img_selected(self):
        """Img2Img 버튼 클릭 시 신호를 발생시키고 닫습니다."""
        print("Img2Img 작업 요청 신호 발생")
        self.img2img_requested.emit(self.pil_image)
        self.accept() # 다이얼로그 닫기

    def on_inpaint_selected(self):
        """Inpaint 버튼 클릭 시 신호를 발생시키고 닫습니다."""
        print("Inpaint 작업 요청 신호 발생")
        self.inpaint_requested.emit(self.pil_image)
        self.accept()
    
    def on_metadata_view(self):
        """메타데이터 뷰어 윈도우를 엽니다."""
        if not self.metadata:
            QMessageBox.warning(self, "경고", "메타데이터를 읽을 수 없습니다.")
            return
        
        # 메타데이터 뷰어 열기 (non-modal)
        self.viewer = MetadataViewerWindow(
            self.pil_image, 
            self.metadata,
            self.app_context,
            self.parent_widget
        )
        
        # 시그널 연결 (MainWindow에서 처리하도록)
        if self.parent_widget:
            # 프롬프트 적용 시그널 연결
            if hasattr(self.parent_widget, 'apply_prompt_from_metadata'):
                self.viewer.apply_prompt.connect(self.parent_widget.apply_prompt_from_metadata)
            
            # 설정 적용 시그널 연결
            if hasattr(self.parent_widget, 'apply_settings_from_metadata'):
                self.viewer.apply_all_settings.connect(self.parent_widget.apply_settings_from_metadata)
            
            # img2img 시그널 연결
            if hasattr(self.parent_widget, 'send_to_img2img_with_metadata'):
                self.viewer.send_to_img2img.connect(self.parent_widget.send_to_img2img_with_metadata)
        
        # show()로 변경하여 non-modal 윈도우로 표시
        self.viewer.show()
        
        # 현재 팝업도 닫기 (사용자가 메타데이터 윈도우에서 작업 가능)
        self.accept()
    
    def on_import_vibe_transfer(self):
        """Import Vibe Transfer 버튼 클릭 시 신호를 발생시키고 닫습니다."""
        print("Import Vibe Transfer 작업 요청 신호 발생")
        self.import_vibe_transfer_requested.emit(self.pil_image)
        self.accept()
