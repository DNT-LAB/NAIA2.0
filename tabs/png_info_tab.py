from typing import Union
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QTextEdit, QFileDialog, QMessageBox, QSplitter, QFrame, QScrollArea,
    QGroupBox, QLineEdit, QCheckBox, QProgressBar
)
from PyQt6.QtGui import QPixmap, QDragEnterEvent, QDropEvent, QFont
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QThread
from PIL import Image, ImageQt, ImageGrab
from PIL.PngImagePlugin import PngInfo
from ui.theme import DARK_COLORS, DARK_STYLES
from ui.scaling_manager import get_scaled_font_size
from ui.img2img_popup import Img2ImgPopup
from interfaces.base_tab_module import BaseTabModule
from utils.image_info import ImageMetadataExtractor
import json
import re
import os
import io
import urllib.request
import tempfile
import piexif
import piexif.helper

class PngInfoTabModule(BaseTabModule):
    """'PNG Info' 탭을 동적으로 로드하기 위한 모듈 래퍼"""
    
    def __init__(self):
        super().__init__()
        self.png_info_widget: PngInfoTab = None

    def get_tab_title(self) -> str:
        return "📝 PNG Info"
        
    def get_tab_order(self) -> int:
        return 3 # 탭 순서 정의

    def create_widget(self, parent: QWidget) -> QWidget:
        # 위젯이 아직 생성되지 않았을 때만 생성
        if self.png_info_widget is None:
            self.png_info_widget = PngInfoTab(parent)
            
            # AppContext 전달
            if hasattr(self, 'app_context') and self.app_context:
                self.png_info_widget.app_context = self.app_context
            
        return self.png_info_widget

# [신규] 비동기 이미지 다운로드를 위한 워커 클래스
class ImageDownloader(QObject):
    download_finished = pyqtSignal(str)
    download_error = pyqtSignal(str)
    download_progress = pyqtSignal(int)  # 새로 추가: 진행률 (0-100)

    def run(self, url):
        """완전 비동기 다운로드 및 변환 작업"""
        try:
            import urllib.request
            
            # 1. 헤더 확인하여 파일 타입 결정
            request = urllib.request.Request(url)
            response = urllib.request.urlopen(request)
            content_type = response.headers.get('Content-Type', '')
            
            # 2. PNG면 확장자 강제 설정, 아니면 원본 확장자 유지
            if 'image/png' in content_type or url.lower().endswith('.png'):
                suffix = '.png'
                needs_conversion = False
            else:
                suffix = '.png'  # 최종적으로는 PNG로
                needs_conversion = True
            
            # 3. 원본 바이트 다운로드
            original_bytes = response.read()
            self.download_progress.emit(60)
            
            if not needs_conversion:
                # PNG는 원본 바이트 그대로 저장
                temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                temp_path = temp_file.name
                temp_file.write(original_bytes)
                temp_file.close()
            else:
                # 다른 포맷은 메타데이터 보존하여 변환
                temp_path = self.convert_to_png_with_metadata(original_bytes)
            
            self.download_progress.emit(100)
            self.download_finished.emit(temp_path)
            
        except Exception as e:
            self.download_error.emit(f"이미지 다운로드 중 오류 발생:\n{str(e)}")

    def convert_to_png_with_metadata(self, image_bytes):
        """바이트 데이터를 메타데이터 보존하여 PNG로 변환"""
        from PIL.PngImagePlugin import PngInfo
        
        # 바이트에서 이미지 열기
        image_stream = io.BytesIO(image_bytes)
        
        with Image.open(image_stream) as img:
            # PNG면 원본 그대로 저장 (변환 불필요)
            if img.format == 'PNG':
                temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                temp_file.write(image_bytes)
                temp_file.close()
                return temp_file.name
            
            # 메타데이터 완전 보존
            pnginfo = PngInfo()
            parameters_added = False  # parameters 추가 여부 추적
            
            # 1. 기본 info 데이터 보존
            if hasattr(img, 'info') and img.info:
                for key, value in img.info.items():
                    if isinstance(value, str):
                        pnginfo.add_text(key, value)
                        if key == "parameters":
                            parameters_added = True
                    elif isinstance(value, bytes):
                        try:
                            # EXIF 데이터 특별 처리
                            if key.lower() == 'exif':
                                # EXIF를 PNG tEXt 청크로 변환하여 보존
                                try:
                                    exif_dict = piexif.load(value)
                                    user_comment = exif_dict.get("Exif", {}).get(piexif.ExifIFD.UserComment, b'')
                                    if user_comment and not parameters_added:
                                        try:
                                            # piexif helper로 시도
                                            comment_text = piexif.helper.UserComment.load(user_comment)
                                            if comment_text.strip():
                                                pnginfo.add_text("parameters", comment_text)
                                                parameters_added = True
                                        except ValueError:
                                            # 직접 UTF-16 디코딩 시도
                                            if user_comment.startswith(b'UNICODE\x00\x00'):
                                                utf16_data = user_comment[9:]
                                                comment_text = utf16_data.decode('utf-16le', errors='ignore')
                                                if comment_text.strip():
                                                    pnginfo.add_text("parameters", comment_text)
                                                    parameters_added = True
                                            else:
                                                # UTF-8 시도
                                                try:
                                                    comment_text = user_comment.decode('utf-8', errors='ignore')
                                                    if comment_text.strip():
                                                        pnginfo.add_text("parameters", comment_text)
                                                        parameters_added = True
                                                except:
                                                    pass
                                except Exception as e:
                                    print(f"EXIF 변환 실패: {e}")
                            else:
                                # 다른 바이너리 데이터는 UTF-8 시도
                                try:
                                    text_value = value.decode('utf-8', errors='ignore')
                                    if text_value.strip():
                                        pnginfo.add_text(key, text_value)
                                except Exception as e:
                                    print(f"메타데이터 변환 실패 ({key}): {e}")
                        except Exception as e:
                            print(f"메타데이터 처리 실패 ({key}): {e}")
            
            # 2. EXIF 데이터에서 직접 추출 (parameters가 아직 없을 때만)
            if not parameters_added:
                try:
                    # PIL의 getexif() 사용 (더 안전함)
                    if hasattr(img, 'getexif'):
                        exif_dict = img.getexif()
                        # UserComment 찾기 (태그 37510)
                        if 37510 in exif_dict:
                            user_comment = exif_dict[37510]
                            if isinstance(user_comment, (bytes, str)):
                                try:
                                    if isinstance(user_comment, bytes):
                                        comment_text = piexif.helper.UserComment.load(user_comment)
                                    else:
                                        comment_text = user_comment
                                    
                                    if comment_text and comment_text.strip():
                                        pnginfo.add_text("parameters", comment_text)
                                        parameters_added = True
                                except Exception as e:
                                    print(f"EXIF 직접 추출 실패: {e}")
                except Exception as e:
                    print(f"getexif() 실패: {e}")
            
            # PNG로 저장
            temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            temp_path = temp_file.name
            temp_file.close()
            
            img.save(temp_path, 'PNG', pnginfo=pnginfo)
            
        return temp_path

class PngInfoTab(QWidget):
    """PNG 파일의 메타데이터 정보를 표시하는 탭"""
    
    # 파라미터 추출 완료 시그널
    parameters_extracted = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")
        self.current_image_path = None
        self.current_pil_image = None  # 현재 로드된 PIL 이미지 저장
        self.current_parameters = {}
        self.download_thread = None
        self.downloader = None
        self.app_context = None  # AppContext 저장용
        self.init_ui()
        
    def init_ui(self):
        """UI 초기화"""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)
        
        # 좌측: 이미지 드롭 영역
        left_panel = self.create_image_panel()
        
        # 우측: 정보 표시 영역
        right_panel = self.create_info_panel()
        
        # 스플리터로 좌우 나누기 (크기 조절 비활성화)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 35)  # 좌측 35%
        splitter.setStretchFactor(1, 65)  # 우측 65%
        
        # 스플리터 핸들 비활성화 (크기 조절 불가)
        splitter.setChildrenCollapsible(False)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: transparent;
                width: 0px;
                height: 0px;
            }
        """)
        
        main_layout.addWidget(splitter)
        
    def create_image_panel(self):
        """이미지 드롭 영역 생성"""
        panel = QFrame()
        panel.setStyleSheet(DARK_STYLES['compact_card'])
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # [이미지 정보 추출] 버튼을 맨 위에 추가
        self.extract_info_button = QPushButton("🔍 이미지 정보 추출")
        self.extract_info_button.clicked.connect(self.show_img2img_popup)
        self.extract_info_button.setEnabled(False)  # 이미지가 로드되기 전까지 비활성화
        self.extract_info_button.setStyleSheet(f"""
            QPushButton {{
                background-color: #2E7D32;
                border: 1px solid #388E3C;
                border-radius: 6px;
                padding: 10px 16px;
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-weight: 600;
                color: #FFFFFF;
                font-size: {get_scaled_font_size(20)}px;
            }}
            QPushButton:hover:enabled {{
                background-color: #388E3C;
                border: 1px solid #43A047;
                color: #FFFFFF;
            }}
            QPushButton:pressed:enabled {{
                background-color: #1B5E20;
                color: #FFFFFF;
            }}
            QPushButton:disabled {{
                background-color: #1B5E20;
                border: 1px solid #2E7D32;
                color: rgba(255, 255, 255, 0.5);
            }}
        """)
        layout.addWidget(self.extract_info_button)
        
        # 드래그 앤 드롭 영역
        self.drop_area = ImageDropArea(self)
        self.drop_area.file_dropped.connect(self.load_image_from_path)
        self.drop_area.web_url_dropped.connect(self.download_and_load_image)
        layout.addWidget(self.drop_area)
        
        # 프로그레스 바 추가 (기본적으로 숨김)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                background-color: {DARK_COLORS['bg_secondary']};
                text-align: center;
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-size: {get_scaled_font_size(14)}px;
                color: {DARK_COLORS['text_primary']};
                height: 20px;
            }}
            QProgressBar::chunk {{
                background-color: {DARK_COLORS['accent_blue']};
                border-radius: 3px;
            }}
        """)
        layout.addWidget(self.progress_bar)
        
        # 버튼 영역
        button_layout = QVBoxLayout()
        button_layout.setSpacing(8)
        
        self.load_button = QPushButton("📁 파일 선택")
        self.load_button.clicked.connect(self.select_image_file)
        self.load_button.setStyleSheet(DARK_STYLES['secondary_button'])
        
        self.paste_button = QPushButton("📋 클립보드 붙여넣기")
        self.paste_button.clicked.connect(self.paste_from_clipboard)
        self.paste_button.setStyleSheet(DARK_STYLES['primary_button'])
        
        self.clear_button = QPushButton("🗑️ 초기화")
        self.clear_button.clicked.connect(self.clear_all)
        self.clear_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 8px 16px;
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-weight: 500;
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(20)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['error']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['error']};
            }}
        """)
        
        button_layout.addWidget(self.load_button)
        button_layout.addWidget(self.paste_button)
        button_layout.addWidget(self.clear_button)
        layout.addLayout(button_layout)
        
        return panel
    
    def create_info_panel(self):
        """정보 표시 패널 생성"""
        panel = QFrame()
        panel.setStyleSheet(DARK_STYLES['compact_card'])
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        
        # 제목
        title_label = QLabel("📝 메타데이터 정보")
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-size: {get_scaled_font_size(18)}px;
                font-weight: 600;
                margin-bottom: 8px;
            }}
        """)
        layout.addWidget(title_label)
        
        # 탭 전환 버튼
        tab_button_layout = QHBoxLayout()
        tab_button_layout.setSpacing(4)
        
        self.raw_tab_button = QPushButton("원본 데이터")
        self.parsed_tab_button = QPushButton("파싱 결과")
        self.copy_tab_button = QPushButton("복사용 텍스트")
        
        for btn in [self.raw_tab_button, self.parsed_tab_button, self.copy_tab_button]:
            btn.setCheckable(True)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                    font-weight: 500;
                    color: {DARK_COLORS['text_secondary']};
                    font-size: {get_scaled_font_size(16)}px;
                }}
                QPushButton:checked {{
                    background-color: {DARK_COLORS['accent_blue']};
                    color: {DARK_COLORS['text_primary']};
                    border: 1px solid {DARK_COLORS['accent_blue']};
                    font-weight: 600;
                }}
                QPushButton:hover:!checked {{
                    background-color: {DARK_COLORS['bg_hover']};
                    color: {DARK_COLORS['text_primary']};
                }}
            """)
            
        self.raw_tab_button.clicked.connect(lambda: self.switch_tab('raw'))
        self.parsed_tab_button.clicked.connect(lambda: self.switch_tab('parsed'))
        self.copy_tab_button.clicked.connect(lambda: self.switch_tab('copy'))
        
        tab_button_layout.addWidget(self.raw_tab_button)
        tab_button_layout.addWidget(self.parsed_tab_button)
        tab_button_layout.addWidget(self.copy_tab_button)
        tab_button_layout.addStretch()
        
        layout.addLayout(tab_button_layout)
        
        # 정보 표시 영역들
        self.create_info_displays(layout)
        
        # 기본 탭 설정
        self.switch_tab('raw')
        
        return panel
        
    def create_info_displays(self, layout):
        """정보 표시 영역들 생성"""
        # 원본 데이터 표시
        self.raw_text_edit = QTextEdit()
        self.raw_text_edit.setReadOnly(True)
        self.raw_text_edit.setPlaceholderText("PNG 이미지를 드래그하거나 선택하세요...")
        self.raw_text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 8px;
                color: {DARK_COLORS['text_primary']};
                selection-background-color: {DARK_COLORS['accent_blue']};
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: {get_scaled_font_size(16)}px;
                line-height: 1.4;
            }}
            QTextEdit:focus {{
                border: 2px solid {DARK_COLORS['accent_blue']};
            }}
        """)
        
        # 파싱된 파라미터 표시
        self.parsed_scroll = QScrollArea()
        self.parsed_widget = QWidget()
        self.parsed_layout = QVBoxLayout(self.parsed_widget)
        self.parsed_scroll.setWidget(self.parsed_widget)
        self.parsed_scroll.setWidgetResizable(True)
        self.parsed_scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
            QScrollBar:vertical {{
                background-color: {DARK_COLORS['bg_secondary']};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {DARK_COLORS['border_light']};
                border-radius: 4px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {DARK_COLORS['accent_blue_light']};
            }}
        """)
        
        # 복사용 텍스트
        self.copy_text_edit = QTextEdit()
        self.copy_text_edit.setPlaceholderText("파라미터가 추출되면 여기에 복사 가능한 형태로 표시됩니다...")
        self.copy_text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 8px;
                color: {DARK_COLORS['text_primary']};
                selection-background-color: {DARK_COLORS['accent_blue']};
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: {get_scaled_font_size(16)}px;
                line-height: 1.4;
            }}
            QTextEdit:focus {{
                border: 2px solid {DARK_COLORS['accent_blue']};
            }}
        """)
        
        layout.addWidget(self.raw_text_edit)
        layout.addWidget(self.parsed_scroll)
        layout.addWidget(self.copy_text_edit)
        
        # 복사 버튼
        copy_button_layout = QHBoxLayout()
        copy_button_layout.setSpacing(8)
        
        self.copy_all_button = QPushButton("📋 전체 복사")
        self.copy_all_button.clicked.connect(self.copy_all_parameters)
        self.copy_all_button.setStyleSheet(DARK_STYLES['secondary_button'])
        
        self.export_button = QPushButton("💾 JSON 저장")
        self.export_button.clicked.connect(self.export_to_json)
        self.export_button.setStyleSheet(DARK_STYLES['secondary_button'])
        
        copy_button_layout.addWidget(self.copy_all_button)
        copy_button_layout.addWidget(self.export_button)
        copy_button_layout.addStretch()
        
        layout.addLayout(copy_button_layout)
        
    def switch_tab(self, tab_name):
        """탭 전환"""
        # 모든 버튼 체크 해제
        for btn in [self.raw_tab_button, self.parsed_tab_button, self.copy_tab_button]:
            btn.setChecked(False)
            
        # 모든 표시 영역 숨기기
        self.raw_text_edit.hide()
        self.parsed_scroll.hide()
        self.copy_text_edit.hide()
        
        # 선택된 탭만 표시
        if tab_name == 'raw':
            self.raw_tab_button.setChecked(True)
            self.raw_text_edit.show()
        elif tab_name == 'parsed':
            self.parsed_tab_button.setChecked(True)
            self.parsed_scroll.show()
        elif tab_name == 'copy':
            self.copy_tab_button.setChecked(True)
            self.copy_text_edit.show()
    
    def paste_from_clipboard(self):
        """클립보드에서 이미지 붙여넣기"""
        try:
            from PyQt6.QtWidgets import QApplication
            from PyQt6.QtCore import QMimeData
            import tempfile
            
            app = QApplication.instance()
            if not app:
                QMessageBox.warning(self, "오류", "QApplication을 찾을 수 없습니다.")
                return
            
            clipboard = app.clipboard()
            mime_data = clipboard.mimeData()
            
            # 이미지가 클립보드에 있는지 확인
            if mime_data.hasImage():
                # Use ImageGrab.grabclipboard() to preserve EXIF metadata
                # or one can use clipboard.image()
                pil_image = ImageGrab.grabclipboard()

                # 메타데이터 추출
                geninfo, metadata = self.read_info_from_image(pil_image)

                # 드롭 영역에 이미지 표시 (PIL Image 직접 전달)
                self.drop_area.set_image(pil_image)

                # 원본 데이터 표시
                self.display_raw_metadata(metadata, geninfo)

                # 파라미터 파싱 및 표시
                if geninfo:
                    parsed_params = self.parse_generation_parameters(geninfo)
                    self.current_parameters = parsed_params
                    self.display_parsed_parameters(parsed_params)
                    self.display_copy_text(parsed_params, geninfo)

                    # 시그널 발송
                    self.parameters_extracted.emit(parsed_params)

                self.current_image_path = None  # 클립보드 이미지는 경로가 없음
                self.current_pil_image = pil_image  # PIL 이미지 저장
                self.extract_info_button.setEnabled(True)  # 버튼 활성화
                print("✅ 클립보드 이미지 로드 완료")

            # URL이 클립보드에 있는 경우 (웹 이미지) - 파일이 아닌 웹 URL
            elif mime_data.hasUrls():
                urls = mime_data.urls()
                if urls:
                    url_str = urls[0].toString()
                    if any(url_str.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg']):
                        self.download_and_load_image(url_str)
                    else:
                        QMessageBox.warning(self, "경고", "이미지 URL이 아닙니다.")
                        
            # 텍스트 URL인 경우
            elif mime_data.hasText():
                text = mime_data.text().strip()
                if text.startswith(('http://', 'https://')) and any(text.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg']):
                    self.download_and_load_image(text)
                else:
                    QMessageBox.information(self, "정보", "클립보드에 이미지나 이미지 URL이 없습니다.")
            else:
                QMessageBox.information(self, "정보", "클립보드에 이미지나 이미지 URL이 없습니다.")
                
        except Exception as e:
            QMessageBox.critical(self, "오류", f"클립보드에서 이미지를 가져오는 중 오류:\n{str(e)}")
            print(f"❌클립보드 붙여넣기 오류: {str(e)}")
    
    def download_and_load_image(self, url):
        """웹 이미지 다운로드를 완전 비동기로 실행"""
        # UI 상태 변경
        self.drop_area.setText("⬇️\n\n이미지 다운로드 준비 중...")
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.set_buttons_enabled(False)

        # 스레드 생성 및 설정
        self.download_thread = QThread()
        self.downloader = ImageDownloader()
        self.downloader.moveToThread(self.download_thread)

        # 시그널-슬롯 연결
        self.downloader.download_finished.connect(self.on_download_finished)
        self.downloader.download_error.connect(self.on_download_error)
        self.downloader.download_progress.connect(self.on_download_progress)  # 새로 추가
        
        # 스레드 시작
        self.download_thread.started.connect(lambda: self.downloader.run(url))
        self.download_thread.finished.connect(self.download_thread.deleteLater)
        self.download_thread.start()

    def on_download_progress(self, percentage):
        """다운로드 진행률 업데이트"""
        self.progress_bar.setValue(percentage)
        if percentage < 95:
            self.drop_area.setText(f"⬇️\n\n다운로드 중... {percentage}%")
        else:
            self.drop_area.setText("🔄\n\nPNG 변환 중...")

    def on_download_finished(self, temp_path):
        """다운로드 완료 시 호출되는 슬롯"""
        self.progress_bar.setVisible(False)
        self.load_image_from_path(temp_path)
        self.set_buttons_enabled(True)
        if self.download_thread:
            self.download_thread.quit()

    def on_download_error(self, error_message):
        """다운로드 오류 시 호출되는 슬롯"""
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self, "오류", error_message)
        self.drop_area.clear_image()
        self.set_buttons_enabled(True)
        if self.download_thread:
            self.download_thread.quit()

    def set_buttons_enabled(self, enabled):
        """작업 중 버튼 비활성화를 위한 헬퍼 메서드"""
        self.load_button.setEnabled(enabled)
        self.paste_button.setEnabled(enabled)
        self.clear_button.setEnabled(enabled)
    
    def select_image_file(self):
        """이미지 파일 선택 다이얼로그"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "이미지 선택",
            "",
            "Image Files (*.png *.jpg *.jpeg *.gif *.webp);;PNG Files (*.png);;All Files (*)"
        )
        
        if file_path:
            self.load_image_from_path(file_path)
    
    def read_info_from_image(self, image: Image.Image):
        """통합 메타데이터 추출 - stealth PNG 지원 포함"""
        IGNORED_INFO_KEYS = {
            'jfif', 'jfif_version', 'jfif_unit', 'jfif_density', 'dpi',
            'loop', 'background', 'timestamp', 'duration', 'progressive', 'progression',
            'icc_profile', 'chromaticity', 'photoshop',
        }

        # ImageMetadataExtractor 사용하여 모든 메타데이터 추출 (stealth PNG 포함)
        extracted_metadata = ImageMetadataExtractor.extract_metadata(image)

        items = (image.info or {}).copy()
        geninfo = None

        # 1. 먼저 기본 parameters 필드 확인
        geninfo = items.pop('parameters', None)

        # 2. ImageMetadataExtractor가 추출한 데이터 확인
        if not geninfo and extracted_metadata:
            # WebUI 형식
            if extracted_metadata.get('type') == 'webui':
                prompt = extracted_metadata.get('prompt', '')
                negative = extracted_metadata.get('negative', '')
                params = extracted_metadata.get('parameters', {})

                # WebUI 형식으로 재구성
                geninfo = prompt
                if negative:
                    geninfo += f"\nNegative prompt: {negative}"

                # 파라미터 추가
                if params:
                    param_parts = []
                    for key, value in params.items():
                        param_parts.append(f"{key.replace('_', ' ').title()}: {value}")
                    if param_parts:
                        geninfo += "\n" + ", ".join(param_parts)

            # NovelAI 형식
            elif extracted_metadata.get('type') == 'nai' or extracted_metadata.get('Software') == 'NovelAI':
                if extracted_metadata.get('Software') == 'NovelAI':
                    extracted_metadata = extracted_metadata.get('Comment')
                prompt = extracted_metadata.get('prompt', '')
                uc = extracted_metadata.get('uc', '')
                params = extracted_metadata.get('parameters', {})
                if not params: params = extracted_metadata

                sampler_map = {
                    "k_euler_ancestral": "Euler a",
                    "k_euler": "Euler",
                    "k_dpmpp_2s_ancestral": "DPM++ 2S a",
                    "k_dpmpp_2m": "DPM++ 2M",
                    "k_dpmpp_sde": "DPM++ SDE",
                }
                sampler = params.get("sampler", "")

                geninfo = f"""{prompt}
Negative prompt: {uc}
Steps: {params.get('steps', '')}, Sampler: {sampler}, CFG scale: {params.get('scale', '')}, Seed: {params.get('seed', '')}, Size: {image.width}x{image.height}, Clip skip: 2, ENSD: 31337"""

        # 3. EXIF 데이터 확인 (기존 방식 유지)
        if not geninfo and "exif" in items:
            exif_data = items["exif"]
            try:
                exif = piexif.load(exif_data)
                user_comment = (exif or {}).get("Exif", {}).get(piexif.ExifIFD.UserComment, b'')

                if user_comment:
                    try:
                        geninfo = piexif.helper.UserComment.load(user_comment)
                    except ValueError:
                        try:
                            geninfo = user_comment.decode('utf8', errors="ignore")
                        except:
                            if user_comment.startswith(b'UNICODE\x00\x00'):
                                utf16_data = user_comment[9:]
                                geninfo = utf16_data.decode('utf-16le', errors='ignore')
            except Exception as e:
                print(f"EXIF 읽기 오류: {e}")

        # 4. GIF 댓글 확인
        if not geninfo and "comment" in items:
            if isinstance(items["comment"], bytes):
                geninfo = items["comment"].decode('utf8', errors="ignore")
            else:
                geninfo = items["comment"]

        # 무시할 키들 제거
        for field in IGNORED_INFO_KEYS:
            items.pop(field, None)

        return geninfo, items

    def display_raw_metadata(self, metadata, geninfo):
        """개선된 원본 메타데이터 표시"""
        raw_text = "🔍 이미지 메타데이터\n" + "="*50 + "\n\n"

        # 생성 정보가 있으면 먼저 표시
        if geninfo:
            raw_text += "📋 생성 정보 (Generation Info):\n"
            raw_text += f"{geninfo}\n\n"
            raw_text += "="*50 + "\n\n"

        # 나머지 메타데이터 표시
        if not metadata:
            # geninfo가 있으면 메타데이터가 성공적으로 추출된 것
            if geninfo:
                raw_text += "💡 생성 정보가 성공적으로 추출되었습니다. (Stealth PNG 또는 표준 메타데이터)\n"
                raw_text += "추가 메타데이터 필드는 없습니다."
            else:
                raw_text += "⚠️ 메타데이터를 찾을 수 없습니다.\n"
                raw_text += "이 이미지는 생성 정보를 포함하지 않습니다."
        else:
            raw_text += "📌 기타 메타데이터:\n\n"
            for key, value in metadata.items():
                # 값이 너무 길면 일부만 표시
                value_str = str(value)
                if len(value_str) > 500:
                    value_str = value_str[:500] + "... (truncated)"

                raw_text += f"🔹 {key}:\n"
                raw_text += f"{value_str}\n\n"

        self.raw_text_edit.setText(raw_text)

    def load_image_from_path(self, file_path):
        """이미지 파일 로드 및 메타데이터 추출"""
        try:
            if not os.path.exists(file_path):
                QMessageBox.warning(self, "오류", "파일을 찾을 수 없습니다.")
                return
                
            # PIL로 이미지 열기
            img = Image.open(file_path)
            self.current_image_path = file_path
            self.current_pil_image = img.copy()  # PIL 이미지 복사본 저장
            
            # 개선된 메타데이터 추출
            geninfo, metadata = self.read_info_from_image(img)
            
            # 드롭 영역에 이미지 표시
            self.drop_area.set_image(file_path)
            
            # 원본 데이터 표시 (전체 메타데이터)
            self.display_raw_metadata(metadata, geninfo)
            
            # 파라미터 파싱 및 표시 - 함수명 수정
            if geninfo:
                # geninfo를 직접 파싱
                parsed_params = self.parse_generation_parameters(geninfo)
                self.current_parameters = parsed_params
                self.display_parsed_parameters(parsed_params)
                self.display_copy_text(parsed_params, geninfo)
                
                # 시그널 발송
                self.parameters_extracted.emit(parsed_params)
            else:
                self.clear_parameter_displays()
            
            # 버튼 활성화
            self.extract_info_button.setEnabled(True)
            
            print(f"✅ 이미지 로드 완료: {file_path}")
                
        except Exception as e:
            QMessageBox.critical(self, "오류", f"이미지 로드 중 오류 발생:\n{str(e)}")
            print(f"❌ 이미지 로드 오류: {e}")


    def parse_generation_parameters(self, text):
        """개선된 생성 파라미터 텍스트 파싱"""
        params = {}
        
        try:
            lines = text.strip().split('\n')
            
            # 첫 번째 줄은 보통 프롬프트
            if lines:
                params['prompt'] = lines[0].strip()
            
            # 네가티브 프롬프트 찾기 (멀티라인 지원)
            negative_match = re.search(r'Negative prompt:\s*(.+?)(?=\n[A-Z][^:]*:|$)', text, re.DOTALL)
            if negative_match:
                params['negative_prompt'] = negative_match.group(1).strip()
            
            # 설정 파라미터들 파싱 (더 많은 패턴 지원)
            settings_patterns = [
                r'(Steps|Sampler|CFG scale|Seed|Size|Model hash|Model|Denoising strength|Clip skip|ENSD|Hires upscale|Hires steps|Hires upscaler|Version):\s*([^,\n]+)',
                r'(Width|Height):\s*(\d+)',
            ]
            
            for pattern in settings_patterns:
                for match in re.finditer(pattern, text):
                    key = match.group(1).lower().replace(' ', '_')
                    value = match.group(2).strip()
                    params[key] = value
            
            # 크기 정보 파싱
            size_match = re.search(r'Size:\s*(\d+)x(\d+)', text)
            if size_match:
                params['width'] = int(size_match.group(1))
                params['height'] = int(size_match.group(2))
            
            # NovelAI 특별 처리
            if 'ENSD: 31337' in text:
                params['source'] = 'NovelAI'
            
            return params
            
        except Exception as e:
            print(f"파라미터 파싱 오류: {e}")
            return {'raw_text': text}

    
    def parse_and_display_parameters(self, metadata):
        """파라미터 파싱 및 표시"""
        # AUTOMATIC1111 스타일 파라미터 찾기
        parameters_text = metadata.get('parameters', '')
        
        if not parameters_text:
            # 다른 키들도 확인
            for key in ['Parameters', 'generation_data', 'Software', 'Comment']:
                if key in metadata:
                    parameters_text = metadata[key]
                    break
        
        if parameters_text:
            parsed_params = self.parse_generation_parameters(parameters_text)
            self.current_parameters = parsed_params
            self.display_parsed_parameters(parsed_params)
            self.display_copy_text(parsed_params, parameters_text)
            
            # 시그널 발송
            self.parameters_extracted.emit(parsed_params)
        else:
            self.clear_parameter_displays()
    
    def display_parsed_parameters(self, params):
        """파싱된 파라미터 표시"""
        # 기존 위젯들 제거
        for i in reversed(range(self.parsed_layout.count())):
            widget = self.parsed_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        
        if not params:
            no_data_label = QLabel("파싱 가능한 파라미터가 없습니다.")
            no_data_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            no_data_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_secondary']};
                    font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                    font-size: {get_scaled_font_size(16)}px;
                    padding: 20px;
                }}
            """)
            self.parsed_layout.addWidget(no_data_label)
            return
        
        # 파라미터별 그룹 생성
        groups = {
            '프롬프트': ['prompt', 'negative_prompt'],
            '생성 설정': ['steps', 'sampler', 'cfg_scale', 'seed'],
            '이미지 설정': ['width', 'height', 'size'],
            '모델 정보': ['model', 'model_hash'],
            '기타': []
        }
        
        # 기타 그룹에 나머지 파라미터 추가
        used_params = set()
        for group_params in groups.values():
            used_params.update(group_params)
        
        groups['기타'] = [key for key in params.keys() if key not in used_params]
        
        for group_name, param_keys in groups.items():
            if not param_keys or not any(key in params for key in param_keys):
                continue
                
            group_box = QGroupBox(group_name)
            group_box.setStyleSheet(f"""
                QGroupBox {{
                    color: {DARK_COLORS['text_primary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: 4px;
                    margin-top: 12px;
                    font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                    font-size: {get_scaled_font_size(16)}px;
                    font-weight: 600;
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin;
                    subcontrol-position: top left;
                    padding: 4px 8px;
                    color: {DARK_COLORS['accent_blue']};
                }}
            """)
            group_layout = QVBoxLayout(group_box)
            group_layout.setContentsMargins(8, 16, 8, 8)
            group_layout.setSpacing(6)
            
            for key in param_keys:
                if key in params:
                    param_widget = self.create_parameter_widget(key, params[key])
                    group_layout.addWidget(param_widget)
            
            self.parsed_layout.addWidget(group_box)
        
        self.parsed_layout.addStretch()
    
    def create_parameter_widget(self, key, value):
        """파라미터 위젯 생성"""
        widget = QFrame()
        widget.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)
        
        # 키 레이블
        key_label = QLabel(f"{key.replace('_', ' ').title()}:")
        key_label.setStyleSheet(f"""
            QLabel {{
                font-weight: 600;
                color: {DARK_COLORS['text_primary']};
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-size: {get_scaled_font_size(15)}px;
                min-width: 100px;
            }}
        """)
        key_label.setMinimumWidth(100)
        
        # 값 표시 (긴 텍스트는 텍스트 에디트, 짧은 건 레이블)
        value_str = str(value)
        if len(value_str) > 50 or '\n' in value_str:
            value_widget = QTextEdit()
            value_widget.setPlainText(value_str)
            value_widget.setMaximumHeight(80)
            value_widget.setReadOnly(True)
            value_widget.setStyleSheet(f"""
                QTextEdit {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: 3px;
                    padding: 4px;
                    color: {DARK_COLORS['text_primary']};
                    font-family: 'Consolas', 'Monaco', monospace;
                    font-size: {get_scaled_font_size(14)}px;
                }}
            """)
        else:
            value_widget = QLineEdit(value_str)
            value_widget.setReadOnly(True)
            value_widget.setStyleSheet(f"""
                QLineEdit {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: 3px;
                    padding: 4px 8px;
                    color: {DARK_COLORS['text_primary']};
                    font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                    font-size: {get_scaled_font_size(15)}px;
                }}
            """)
        
        layout.addWidget(key_label)
        layout.addWidget(value_widget)
        
        return widget
    
    def display_copy_text(self, params, original_text):
        """복사용 텍스트 표시"""
        copy_text = "📋 복사용 파라미터\n" + "="*40 + "\n\n"
        
        # 원본 텍스트도 포함
        copy_text += "🔤 원본 파라미터:\n"
        copy_text += "-"*30 + "\n"
        copy_text += original_text + "\n\n"
        
        # JSON 형태
        copy_text += "📄 JSON 형태:\n"
        copy_text += "-"*30 + "\n"
        copy_text += json.dumps(params, indent=2, ensure_ascii=False)
        
        self.copy_text_edit.setText(copy_text)
    
    def clear_parameter_displays(self):
        """파라미터 표시 영역 초기화"""
        # 파싱된 파라미터 영역 초기화
        for i in reversed(range(self.parsed_layout.count())):
            widget = self.parsed_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        
        no_data_label = QLabel("파라미터 정보가 없습니다.")
        no_data_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        no_data_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-size: {get_scaled_font_size(16)}px;
                padding: 20px;
            }}
        """)
        self.parsed_layout.addWidget(no_data_label)
        
        # 복사용 텍스트 초기화
        self.copy_text_edit.clear()
        self.current_parameters = {}
    
    def copy_all_parameters(self):
        """전체 파라미터 클립보드에 복사"""
        if self.current_parameters:
            try:
                import pyperclip
                text = json.dumps(self.current_parameters, indent=2, ensure_ascii=False)
                pyperclip.copy(text)
                QMessageBox.information(self, "복사 완료", "파라미터가 클립보드에 복사되었습니다.")
            except ImportError:
                # pyperclip이 없으면 Qt 클립보드 사용
                from PyQt6.QtWidgets import QApplication
                clipboard = QApplication.clipboard()
                text = json.dumps(self.current_parameters, indent=2, ensure_ascii=False)
                clipboard.setText(text)
                QMessageBox.information(self, "복사 완료", "파라미터가 클립보드에 복사되었습니다.")
        else:
            QMessageBox.warning(self, "경고", "복사할 파라미터가 없습니다.")
    
    def export_to_json(self):
        """JSON 파일로 내보내기"""
        if not self.current_parameters:
            QMessageBox.warning(self, "경고", "내보낼 파라미터가 없습니다.")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "JSON 파일로 저장",
            "parameters.json",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(self.current_parameters, f, indent=2, ensure_ascii=False)
                QMessageBox.information(self, "저장 완료", f"파라미터가 저장되었습니다:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "오류", f"파일 저장 중 오류:\n{str(e)}")
    
    def clear_all(self):
        """모든 내용 지우기"""
        self.current_image_path = None
        self.current_pil_image = None
        self.current_parameters = {}
        self.drop_area.clear_image()
        self.raw_text_edit.clear()
        self.copy_text_edit.clear()
        self.clear_parameter_displays()
        self.extract_info_button.setEnabled(False)  # 버튼 비활성화
    
    def show_img2img_popup(self):
        """Img2ImgPopup을 표시합니다."""
        if not self.current_pil_image:
            QMessageBox.warning(self, "경고", "로드된 이미지가 없습니다.")
            return
        
        # MainWindow 찾기
        main_window = self.window()
        
        # Img2ImgPopup 표시
        popup = Img2ImgPopup(self.current_pil_image, self.app_context, main_window)
        
        # 시그널 연결 (MainWindow가 처리하도록)
        if hasattr(main_window, 'send_to_img2img'):
            popup.img2img_requested.connect(main_window.send_to_img2img)
        if hasattr(main_window, 'send_to_inpaint'):
            popup.inpaint_requested.connect(main_window.send_to_inpaint)
        if hasattr(main_window, 'activate_vibe_transfer'):
            popup.import_vibe_transfer_requested.connect(main_window.activate_vibe_transfer)
        if hasattr(main_window, 'on_tag_interrogation_requested'):
            popup.tag_interrogation_requested.connect(main_window.on_tag_interrogation_requested)

        # 팝업 위치 설정 (버튼 근처)
        button_pos = self.extract_info_button.mapToGlobal(self.extract_info_button.rect().center())
        popup.move(button_pos.x() - popup.width() // 2, button_pos.y())
        
        popup.exec()

class ImageDropArea(QLabel):
    file_dropped = pyqtSignal(str)
    web_url_dropped = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumSize(280, 180)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setText("📷\n\nPNG 이미지를 여기에\n드래그하여 놓으세요")
        self.setStyleSheet(f"""
            QLabel {{
                border: 2px dashed {DARK_COLORS['border_light']};
                border-radius: 8px;
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_secondary']};
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-size: {get_scaled_font_size(16)}px;
                font-weight: 500;
                padding: 20px;
            }}
        """)
        
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(f"""
                QLabel {{
                    border: 2px dashed {DARK_COLORS['success']};
                    border-radius: 8px;
                    background-color: {DARK_COLORS['bg_secondary']};
                    color: {DARK_COLORS['success']};
                    font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                    font-size: {get_scaled_font_size(16)}px;
                    font-weight: 600;
                    padding: 20px;
                }}
            """)
    
    def dragLeaveEvent(self, event):
        self.setStyleSheet(f"""
            QLabel {{
                border: 2px dashed {DARK_COLORS['border_light']};
                border-radius: 8px;
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_secondary']};
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-size: {get_scaled_font_size(16)}px;
                font-weight: 500;
                padding: 20px;
            }}
        """)
    
    def dropEvent(self, event: QDropEvent):
        """드롭 이벤트를 처리하는 핵심 메서드"""
        try:
            if event.mimeData().hasUrls():
                url = event.mimeData().urls()[0]
                
                # 1. 로컬 파일인 경우
                if url.isLocalFile():
                    file_path = url.toLocalFile()
                    # file_dropped 시그널 발생
                    self.file_dropped.emit(file_path)

                # 2. 웹 URL인 경우
                else:
                    url_str = url.toString()
                    # web_url_dropped 시그널 발생
                    self.web_url_dropped.emit(url_str)
        finally:
            self.dragLeaveEvent(event) # 스타일 초기화
    
    def set_image(self, image_input: Union[str, Image.Image]) -> None:
        """이미지 표시 - 파일 경로 또는 PIL Image 객체 모두 지원"""
        try:
            # PIL Image 객체인 경우
            if isinstance(image_input, Image.Image):
                # PIL Image를 QImage로 변환
                qimage = ImageQt.ImageQt(image_input)
                pixmap = QPixmap.fromImage(qimage)
                tooltip = "PIL Image"
            # 파일 경로인 경우
            else:
                pixmap = QPixmap(image_input)
                tooltip = f"📁 {os.path.basename(image_input)}"
            
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(
                    self.size(), 
                    Qt.AspectRatioMode.KeepAspectRatio, 
                    Qt.TransformationMode.SmoothTransformation
                )
                self.setPixmap(scaled_pixmap)
                self.setToolTip(tooltip)
                
                # 이미지가 로드되면 스타일 변경
                self.setStyleSheet(f"""
                    QLabel {{
                        border: 2px solid {DARK_COLORS['accent_blue']};
                        border-radius: 8px;
                        background-color: {DARK_COLORS['bg_secondary']};
                        padding: 4px;
                    }}
                """)
        except Exception as e:
            print(f"이미지 표시 오류: {e}")
    
    def clear_image(self):
        """이미지 지우기"""
        self.clear()
        self.setText("📷\n\nPNG 이미지를 여기에\n드래그하여 놓으세요")
        self.setToolTip("")
        self.setStyleSheet(f"""
            QLabel {{
                border: 2px dashed {DARK_COLORS['border_light']};
                border-radius: 8px;
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_secondary']};
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-size: {get_scaled_font_size(16)}px;
                font-weight: 500;
                padding: 20px;
            }}
        """)
