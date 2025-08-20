import os
import json
import base64
import io
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLineEdit, QLabel, QFileDialog, QMessageBox,
    QPushButton, QFrame, QScrollArea, QMenu, QApplication, QWidgetAction, QComboBox,
    QProgressDialog, QTextEdit, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize, QPoint, QThread, QBuffer, QIODevice
from PyQt6.QtGui import QPixmap, QPainter, QImage, QAction, QKeyEvent, QColor

from PIL import Image
from interfaces.base_tab_module import BaseTabModule
from ui.theme import DARK_STYLES, DARK_COLORS, get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from artist_dictionary import artist_dict


class StableImageWidget(QWidget):
    """
    이미지 표시 위젯 - Assets Tab에서 가져옴
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self._pil_image = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # Enable context menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def setPixmap(self, pixmap: QPixmap):
        if pixmap and not pixmap.isNull():
            self._pixmap = pixmap
            self._convert_to_pil()
        else:
            self._pixmap = None
            self._pil_image = None
        self.update()
    
    def _convert_to_pil(self):
        """Convert QPixmap to PIL Image preserving transparency"""
        if not self._pixmap:
            self._pil_image = None
            return
        
        # Convert QPixmap to QImage first to ensure RGBA format
        q_image = self._pixmap.toImage()
        q_image = q_image.convertToFormat(QImage.Format.Format_RGBA8888)
        
        # Save QImage to buffer as PNG
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.ReadWrite)
        q_image.save(buffer, 'PNG')
        
        # Get bytes from QBuffer
        byte_array = buffer.data()
        buffer.close()
        
        # Convert bytes to PIL Image and ensure RGBA
        pil_buffer = io.BytesIO(byte_array.data())
        self._pil_image = Image.open(pil_buffer)
        if self._pil_image.mode != 'RGBA':
            self._pil_image = self._pil_image.convert('RGBA')
    
    def setPilImage(self, pil_image: Image.Image):
        """Set image from PIL Image"""
        if pil_image:
            self._pil_image = pil_image
            # Convert to QPixmap
            from PIL.ImageQt import ImageQt
            q_image = ImageQt(pil_image.convert("RGBA"))
            self._pixmap = QPixmap.fromImage(q_image)
        else:
            self._pixmap = None
            self._pil_image = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(DARK_COLORS['bg_secondary']))
        
        if not self._pixmap:
            painter.setPen(QColor(DARK_COLORS['text_secondary']))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "생성된 이미지가 여기에 표시됩니다...")
            return

        widget_size = self.size()
        square_size = min(widget_size.width(), widget_size.height())
        
        scaled_pixmap = self._pixmap.scaled(
            QSize(square_size, square_size),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        
        x = (widget_size.width() - scaled_pixmap.width()) // 2
        y = (widget_size.height() - scaled_pixmap.height()) // 2
        painter.drawPixmap(x, y, scaled_pixmap)
        painter.end()
    
    def show_context_menu(self, pos: QPoint):
        """Show right-click context menu"""
        if not self._pixmap or not self._pil_image:
            return
        
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
            }}
            QMenu::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        
        copy_action = QAction("📋 이미지 복사", self)
        copy_action.triggered.connect(self.copy_to_clipboard)
        menu.addAction(copy_action)
        
        save_action = QAction("💾 이미지 저장", self)
        save_action.triggered.connect(self.save_image)
        menu.addAction(save_action)
        
        menu.exec(self.mapToGlobal(pos))
    
    def copy_to_clipboard(self):
        """Copy image to clipboard"""
        if self._pixmap:
            QApplication.clipboard().setPixmap(self._pixmap)
    
    def save_image(self):
        """Save image to file"""
        if self._pil_image:
            file_path, _ = QFileDialog.getSaveFileName(
                self, "이미지 저장", "", "PNG Files (*.png);;All Files (*)"
            )
            if file_path:
                self._pil_image.save(file_path)


from artist_dictionary import artist_dict


class ThumbnailDownloadWorker(QThread):
    """썸네일 데이터 다운로드 워커 스레드"""
    progress_updated = pyqtSignal(int, str)  # percent, message
    download_finished = pyqtSignal(bool, str)  # success, message
    
    def __init__(self, mode: str, target_path: Path, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.target_path = target_path
        
        # HuggingFace URLs
        self.urls = {
            "NAID4.5F-31000": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/NAID4.5_artist_thumbnail_31000/artist_thumbnail_nai",
            "NoobNAI-XL-33000": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/Noob_artist_thumbnail_33000/artist_thumbnail"
        }
        
    def run(self):
        """다운로드 실행"""
        try:
            url = self.urls.get(self.mode)
            if not url:
                self.download_finished.emit(False, f"알 수 없는 모드: {self.mode}")
                return
                
            self.progress_updated.emit(0, "다운로드 준비 중...")
            
            # 헤더 설정
            headers = {
                'User-Agent': 'NAIA/2.0.0 ArtistThumb Module'
            }
            
            request = urllib.request.Request(url, headers=headers)
            
            # 진행률 표시를 위한 다운로드
            def progress_hook(block_num, block_size, total_size):
                if total_size > 0:
                    percent = min(100, (block_num * block_size * 100) // total_size)
                    downloaded_mb = (block_num * block_size) / (1024 * 1024)
                    total_mb = total_size / (1024 * 1024)
                    self.progress_updated.emit(percent, f"다운로드 중... {percent}% ({downloaded_mb:.1f}/{total_mb:.1f} MB)")
                else:
                    downloaded_mb = (block_num * block_size) / (1024 * 1024)
                    self.progress_updated.emit(50, f"다운로드 중... {downloaded_mb:.1f} MB")
            
            # 임시 파일로 다운로드
            temp_path = self.target_path.with_suffix('.tmp')
            urllib.request.urlretrieve(url, temp_path, reporthook=progress_hook)
            
            # 파일 크기 검증
            file_size = temp_path.stat().st_size
            if file_size < (1024 * 1024):  # 1MB 미만이면 오류
                temp_path.unlink()
                self.download_finished.emit(False, f"다운로드된 파일이 너무 작습니다 ({file_size/1024:.1f} KB)")
                return
                
            # 임시 파일을 최종 경로로 이동
            if self.target_path.exists():
                self.target_path.unlink()
            temp_path.rename(self.target_path)
            
            self.progress_updated.emit(100, "다운로드 완료!")
            self.download_finished.emit(True, f"성공적으로 다운로드됨 ({file_size/(1024*1024):.1f} MB)")
            
        except urllib.error.HTTPError as e:
            error_msg = f"HTTP 오류 {e.code}: {e.reason}"
            self.download_finished.emit(False, error_msg)
        except urllib.error.URLError as e:
            error_msg = f"네트워크 오류: {e.reason}"
            self.download_finished.emit(False, error_msg)
        except Exception as e:
            error_msg = f"예상치 못한 오류: {str(e)}"
            self.download_finished.emit(False, error_msg)


class ArtistThumbModule(BaseTabModule):
    """아티스트 스타일 썸네일 뷰어 탭 모듈"""
    
    # 시그널 정의
    artist_selected = pyqtSignal(str)  # 아티스트 이름 전달
    copy_requested = pyqtSignal(str)   # 클립보드 복사 요청
    
    def __init__(self):
        super().__init__()
        self.widget = None
        self.artist_data = {}
        self.artist_list = []
        self.current_artist = None
        self.search_popup = None      # ✅ QListWidget 팝업
        self.max_suggestions = 20     # ✅ 원하는 추천 개수
        self.current_mode = None      # 현재 선택된 썸네일 모드
        self.tab_initialized = False  # 탭 초기화 여부
        
    def get_tab_title(self) -> str:
        return "🎨 Artist Thumb"
    
    def get_tab_order(self) -> int:
        return 50  # 중간 위치
    
    def get_tab_type(self) -> str:
        return 'core'  # 시작 시 자동 로드
    
    def on_tab_activated(self):
        """탭이 활성화될 때 호출 (사용자가 탭을 클릭했을 때)"""
        if not self.tab_initialized and hasattr(self, 'mode_combo'):
            self._check_and_initialize_data()
            self.tab_initialized = True
    
    def _check_and_initialize_data(self):
        """데이터 파일 체크 및 콤보박스 업데이트"""
        # data 폴더 체크
        data_path = Path("data")
        nai_file = data_path / "artist_thumbnail_nai.json"
        noob_file = data_path / "artist_thumbnail.json"
        
        # 콤보박스 초기화
        self.mode_combo.blockSignals(True)  # 시그널 차단
        self.mode_combo.clear()
        
        # NAI 파일 체크
        if nai_file.exists():
            try:
                with open(nai_file, 'r', encoding='utf-8') as file:
                    self.nai_data = json.load(file)
                    
                # 모드 추가
                self.mode_combo.addItems(["NAID4.5F-31000", "NoobNAI-XL-33000"])
                self.current_mode = "NAID4.5F-31000"
                self._previous_mode = "NAID4.5F-31000"
                self.mode_combo.setCurrentText("NAID4.5F-31000")
                
                # NAI 데이터 로드
                self.artist_data = self.nai_data
                self._update_artist_list_from_data()
                
                # NoobNAI 파일도 체크하여 저장
                if noob_file.exists():
                    try:
                        with open(noob_file, 'r', encoding='utf-8') as file:
                            self.noob_data = json.load(file)
                    except:
                        self.noob_data = {}
                else:
                    self.noob_data = {}
                    
                self.mode_combo.blockSignals(False)  # 시그널 재활성화
                return
            except:
                pass
        
        # NoobNAI 파일만 있는 경우
        elif noob_file.exists():
            try:
                with open(noob_file, 'r', encoding='utf-8') as file:
                    self.noob_data = json.load(file)
                    
                # 모드 추가
                self.mode_combo.addItems(["NAID4.5F-31000", "NoobNAI-XL-33000"])
                self.current_mode = "NoobNAI-XL-33000"
                self._previous_mode = "NoobNAI-XL-33000"
                self.mode_combo.setCurrentText("NoobNAI-XL-33000")
                
                # NoobNAI 데이터 로드
                self.artist_data = self.noob_data
                self._update_artist_list_from_data()
                
                self.nai_data = {}  # NAI 데이터는 비워둠
                self.mode_combo.blockSignals(False)  # 시그널 재활성화
                return
            except:
                pass
        
        # 두 파일 모두 없는 경우
        self.mode_combo.addItems(["다운로드 필요", "NAID4.5F-31000", "NoobNAI-XL-33000"])
        self.current_mode = "다운로드 필요"
        self._previous_mode = "다운로드 필요"
        self.mode_combo.setCurrentText("다운로드 필요")
        
        self.nai_data = {}
        self.noob_data = {}
        
        self.mode_combo.blockSignals(False)  # 시그널 재활성화
    
    def create_widget(self, parent: QWidget) -> QWidget:
        """메인 위젯 생성"""
        self.widget = QWidget(parent)
        
        # autocomplete_manager 무시 설정
        self.widget.setProperty("autocomplete_ignore", True)
        
        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(get_scaled_size(10), get_scaled_size(10), 
                                 get_scaled_size(10), get_scaled_size(10))
        
        # 동적 스타일 가져오기
        dynamic_styles = get_dynamic_styles()
        
        # 상단 툴바
        toolbar = self._create_toolbar()
        layout.addWidget(toolbar)
        
        # 메인 수평 레이아웃 (좌측: 리스트, 우측: 미리보기)
        main_horizontal_layout = QHBoxLayout()
        main_horizontal_layout.setSpacing(get_scaled_size(2))
        
        # 좌측 패널 (검색 + 리스트) - 250픽셀 고정
        left_panel = self._create_left_panel(dynamic_styles)
        left_panel.setFixedWidth(250)
        main_horizontal_layout.addWidget(left_panel)
        
        # 우측 패널 (이미지 미리보기)
        right_panel = self._create_right_panel()
        main_horizontal_layout.addWidget(right_panel)
        
        layout.addLayout(main_horizontal_layout)
        
        # 하단 정보 패널
        info_panel = self._create_info_panel()
        layout.addWidget(info_panel)
        
        # 검색 팝업만 초기화 (데이터 로드는 탭 활성화 시)
        self._init_search_popup()
        
        # artist_dict만으로 기본 리스트 초기화
        if artist_dict:
            self.artist_list = sorted(
                artist_dict.keys(),
                key=lambda k: artist_dict.get(k, 0),
                reverse=True
            )
            self._update_listbox(self.artist_list)
        
        return self.widget
    
    def _create_toolbar(self) -> QWidget:
        """상단 툴바 생성"""
        toolbar = QFrame()
        toolbar.setFrameStyle(QFrame.Shape.NoFrame)
        toolbar.setFixedHeight(get_scaled_size(40))
        
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 썸네일 모드 선택 레이블
        mode_label = QLabel("썸네일 모드 선택:")
        mode_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(16)}px;
            }}
        """)
        layout.addWidget(mode_label)
        
        # 썸네일 모드 콤보박스
        self.mode_combo = QComboBox()
        self.mode_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px {get_scaled_size(8)}px;
                font-size: {get_scaled_font_size(16)}px;
                min-width: {get_scaled_size(200)}px;
            }}
            QComboBox:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: {get_scaled_size(20)}px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: {get_scaled_size(5)}px solid transparent;
                border-right: {get_scaled_size(5)}px solid transparent;
                border-top: {get_scaled_size(5)}px solid {DARK_COLORS['text_primary']};
                margin-right: {get_scaled_size(5)}px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                selection-background-color: {DARK_COLORS['bg_hover']};
                padding: {get_scaled_size(4)}px;
            }}
        """)
        
        # 초기에는 기본 항목만 추가 (파일 체크는 탭 활성화 시)
        self.mode_combo.addItems(["다운로드 필요", "NAID4.5F-31000", "NoobNAI-XL-33000"])
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        layout.addWidget(self.mode_combo)
        
        layout.addStretch()
        
        return toolbar
    
    def _create_left_panel(self, dynamic_styles: dict) -> QWidget:
        """좌측 패널 (검색 + 리스트) 생성"""
        panel = QFrame()
        panel.setFrameStyle(QFrame.Shape.Box)
        panel.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(get_scaled_size(8), get_scaled_size(8),
                                 get_scaled_size(8), get_scaled_size(8))
        
        # 검색 필드
        search_label = QLabel("🔍 아티스트 검색:")
        search_label.setStyleSheet(f"font-size: {get_scaled_font_size(16)}px; color: {DARK_COLORS['text_primary']};")
        layout.addWidget(search_label)
        
        self.search_input = QLineEdit()
        self.search_input.setObjectName("artist_search_input")  # autocomplete 무시용
        self.search_input.setProperty("autocomplete_ignore", True)
        self.search_input.setPlaceholderText("아티스트 이름 입력...")
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(8)}px;
                font-size: {get_scaled_font_size(16)}px;
            }}
            QLineEdit:focus {{
                border-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        self.search_input.textChanged.connect(self._perform_search)
        layout.addWidget(self.search_input)
        
        # 아티스트 리스트
        list_label = QLabel("📋 아티스트 목록:")
        list_label.setStyleSheet(f"font-size: {get_scaled_font_size(16)}px; color: {DARK_COLORS['text_primary']}; margin-top: {get_scaled_size(10)}px;")
        layout.addWidget(list_label)
        
        self.artist_listbox = QListWidget()
        self.artist_listbox.setStyleSheet(f"""
            QListWidget {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                font-size: {get_scaled_font_size(16)}px;
                padding: {get_scaled_size(4)}px;
            }}
            QListWidget::item {{
                padding: {get_scaled_size(4)}px;
                border-bottom: 1px solid {DARK_COLORS['border']};
            }}
            QListWidget::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
            }}
            QListWidget::item:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        self.artist_listbox.itemSelectionChanged.connect(self._on_artist_selected)
        layout.addWidget(self.artist_listbox)
    
        
        return panel
    
    def _create_right_panel(self) -> QWidget:
        """우측 패널 (2차 분할 구조) 생성"""
        # 메인 컨테이너
        main_panel = QWidget()
        main_layout = QVBoxLayout(main_panel)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 서브 수평 레이아웃 (썸네일/프롬프트 : 생성 이미지)
        sub_horizontal_layout = QHBoxLayout()
        sub_horizontal_layout.setSpacing(get_scaled_size(2))
        
        # 왼쪽: 썸네일 + 프롬프트
        prompt_panel = self._create_prompt_panel()
        # 크기는 _create_prompt_panel에서 이미 고정됨
        
        # 오른쪽: 생성 이미지 (832x1216 고정)
        generation_panel = self._create_generation_panel()
        
        sub_horizontal_layout.addWidget(prompt_panel)
        sub_horizontal_layout.addWidget(generation_panel)
        sub_horizontal_layout.setStretchFactor(prompt_panel, 1)  # 썸네일 패널은 늘어남
        sub_horizontal_layout.setStretchFactor(generation_panel, 0)  # 생성 패널은 고정
        
        main_layout.addLayout(sub_horizontal_layout)
        return main_panel
    
    def _create_prompt_panel(self) -> QWidget:
        """왼쪽 서브패널: 썸네일 + 프롬프트 입력"""
        # 썸네일 이미지 (3:3.8 비율로 고정 크기 설정)
        # 3:3.8 비율 = 너비:높이 = 1:1.267
        thumbnail_width = 450
        thumbnail_height = int(thumbnail_width * 3.8 / 3.0)  # 570
        
        # 패널 너비를 썸네일 너비 + 패딩으로 설정
        panel_padding = get_scaled_size(8)
        panel_width = thumbnail_width + (panel_padding * 2)
        
        panel = QFrame()
        panel.setFrameStyle(QFrame.Shape.Box)
        panel.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        # 패널 크기 고정
        panel.setFixedWidth(panel_width)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(panel_padding, panel_padding,
                                 panel_padding, panel_padding)
        layout.setSpacing(get_scaled_size(8))
        
        dynamic_styles = get_dynamic_styles()
        
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px;
            }}
        """)
        # 크기를 고정으로 설정
        self.thumbnail_label.setFixedSize(thumbnail_width, thumbnail_height)
        self.thumbnail_label.setScaledContents(False)  # False로 설정하여 비율 유지
        self._show_default_thumbnail()
        layout.addWidget(self.thumbnail_label)
        
        # Positive Prompt
        pos_label = QLabel("Positive Prompt (아티스트 스타일 추가)")
        pos_label.setStyleSheet(dynamic_styles.get('label_style', ''))
        layout.addWidget(pos_label)
        
        self.positive_prompt = QTextEdit()
        self.positive_prompt.setPlaceholderText("아티스트 스타일과 함께 사용할 프롬프트...")
        self.positive_prompt.setStyleSheet(dynamic_styles.get('compact_textedit', ''))
        # 썸네일 너비에 맞춰 크기 조정
        self.positive_prompt.setFixedWidth(thumbnail_width)
        self.positive_prompt.setFixedHeight(get_scaled_size(120))
        layout.addWidget(self.positive_prompt)
        
        # Generate 버튼
        self.generate_btn = QPushButton("🎨 Generate (832x1216)")
        self.generate_btn.setStyleSheet(dynamic_styles.get('primary_button', ''))
        self.generate_btn.setFixedWidth(thumbnail_width)  # 썸네일 너비에 맞춤
        self.generate_btn.setFixedHeight(get_scaled_size(40))
        self.generate_btn.clicked.connect(self._on_generate_clicked)
        layout.addWidget(self.generate_btn)
        
        # 작가태그 앞에 들어갈 텍스트
        prefix_label = QLabel("작가태그 앞에 들어갈 텍스트:")
        prefix_label.setStyleSheet(dynamic_styles.get('label_style', ''))
        layout.addWidget(prefix_label)
        
        self.prefix_textedit = QTextEdit()
        self.prefix_textedit.setPlaceholderText("1girl, usada pekora, ...")
        self.prefix_textedit.setStyleSheet(dynamic_styles.get('compact_textedit', ''))
        self.prefix_textedit.setFixedWidth(thumbnail_width)
        self.prefix_textedit.setFixedHeight(get_scaled_size(100))
        layout.addWidget(self.prefix_textedit)
        
        # 작가태그 뒤에 들어갈 텍스트
        postfix_label = QLabel("작가태그 뒤에 들어갈 텍스트:")
        postfix_label.setStyleSheet(dynamic_styles.get('label_style', ''))
        layout.addWidget(postfix_label)
        
        self.postfix_textedit = QTextEdit()
        self.postfix_textedit.setPlaceholderText("no text, best quality, masterpiece, year 2024, ...")
        self.postfix_textedit.setStyleSheet(dynamic_styles.get('compact_textedit', ''))
        self.postfix_textedit.setFixedWidth(thumbnail_width)
        self.postfix_textedit.setFixedHeight(get_scaled_size(100))
        layout.addWidget(self.postfix_textedit)
        
        layout.addStretch()
        
        return panel
    
    def _create_generation_panel(self) -> QWidget:
        """오른쪽 서브패널: 생성 이미지 표시"""
        panel = QFrame()
        panel.setFrameStyle(QFrame.Shape.Box)
        panel.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(get_scaled_size(8), get_scaled_size(8),
                                 get_scaled_size(8), get_scaled_size(8))
        
        # StableImageWidget 사용
        self.generation_image = StableImageWidget()
        self.generation_image.setMinimumSize(416, 608)  # 832x1216의 절반 크기
        layout.addWidget(self.generation_image)
        
        return panel
    
    def _show_default_thumbnail(self):
        """기본 썸네일 이미지 표시"""
        # 빈 이미지 생성 (512x512)
        pixmap = QPixmap(512, 512)
        pixmap.fill(Qt.GlobalColor.darkGray)
        
        # 텍스트 추가
        painter = QPainter(pixmap)
        painter.setPen(Qt.GlobalColor.white)
        font = painter.font()
        font.setPointSize(24)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, 
                        "아티스트\n썸네일")
        painter.end()
        
        # 고정된 썸네일 크기로 스케일링
        if hasattr(self, 'thumbnail_label'):
            # 고정된 썸네일 크기 사용 (패딩 고려)
            padding = get_scaled_size(4) * 2  # 양쪽 패딩
            target_width = 450 - padding
            target_height = int(450 * 3.8 / 3.0) - padding
            
            scaled_pixmap = pixmap.scaled(
                target_width,
                target_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.thumbnail_label.setPixmap(scaled_pixmap)
    
    def _create_info_panel(self) -> QWidget:
        """하단 정보 패널 생성"""
        panel = QFrame()
        panel.setFrameStyle(QFrame.Shape.Box)
        panel.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(8)}px;
            }}
        """)
        panel.setFixedHeight(get_scaled_size(60))
        
        layout = QHBoxLayout(panel)
        
        # 현재 선택된 아티스트 정보
        self.info_label = QLabel("아티스트를 선택하세요")
        self.info_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(16)}px;
            }}
        """)
        layout.addWidget(self.info_label)
        
        layout.addStretch()
        
        # 복사 버튼
        copy_btn = QPushButton("📋 아티스트명 복사 (Ctrl+C)")
        copy_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
                border: none;
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px {get_scaled_size(12)}px;
                font-size: {get_scaled_font_size(14)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
            QPushButton:disabled {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_secondary']};
            }}
        """)
        copy_btn.clicked.connect(self._copy_artist_name)
        self.copy_button = copy_btn
        self.copy_button.setEnabled(False)
        layout.addWidget(copy_btn)
        
        return panel
    
    
    def _update_artist_list_from_data(self):
        """현재 artist_data로부터 아티스트 리스트 업데이트"""
        if self.artist_data:
            # artist_dict와 매칭되는 아티스트만 필터링
            self.artist_list = sorted(
                [key for key in self.artist_data if key in artist_dict],
                key=lambda k: artist_dict.get(k, 0),
                reverse=True
            )
            self._update_listbox(self.artist_list)
    
    def _on_mode_changed(self, mode: str):
        """썸네일 모드 변경 시 처리"""
        if mode == "다운로드 필요":
            # 아무것도 하지 않음
            return
            
        self.current_mode = mode
        
        # 파일 경로 결정
        data_path = Path("data")
        if mode == "NAID4.5F-31000":
            file_path = data_path / "artist_thumbnail_nai.json"
        elif mode == "NoobNAI-XL-33000":
            file_path = data_path / "artist_thumbnail.json"
        else:
            return
            
        # 파일 존재 확인
        if not file_path.exists():
            # 다운로드 확인 다이얼로그
            msg = QMessageBox(self.widget)
            msg.setWindowTitle("썸네일 데이터 다운로드")
            msg.setText(f"{mode} 썸네일 데이터가 필요합니다.")
            msg.setInformativeText(f"약 2.6GB의 데이터를 다운로드합니다.\n계속하시겠습니까?")
            msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg.setIcon(QMessageBox.Icon.Information)
            
            if msg.exec() == QMessageBox.StandardButton.Yes:
                self._download_thumbnail_data(mode, file_path)
            else:
                # 다운로드 취소 시 콤보박스를 이전 상태로
                if hasattr(self, '_previous_mode'):
                    self.mode_combo.blockSignals(True)
                    self.mode_combo.setCurrentText(self._previous_mode)
                    self.mode_combo.blockSignals(False)
        else:
            # 파일이 있으면 로드
            self._load_thumbnail_data(mode, file_path)
            
        # 현재 모드 저장
        self._previous_mode = mode
    
    def _download_thumbnail_data(self, mode: str, file_path: Path):
        """썸네일 데이터 다운로드"""
        # 진행률 다이얼로그 생성
        self.progress_dialog = QProgressDialog(self.widget)
        self.progress_dialog.setWindowTitle("다운로드 중")
        self.progress_dialog.setLabelText("썸네일 데이터를 다운로드하는 중...")
        self.progress_dialog.setRange(0, 100)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setCancelButton(None)  # 취소 버튼 제거
        self.progress_dialog.setMinimumDuration(0)
        
        # 다운로드 워커 생성
        self.download_worker = ThumbnailDownloadWorker(mode, file_path)
        self.download_worker.progress_updated.connect(self._on_download_progress)
        self.download_worker.download_finished.connect(self._on_download_finished)
        self.download_worker.start()
        
        self.progress_dialog.show()
    
    def _on_download_progress(self, percent: int, message: str):
        """다운로드 진행률 업데이트"""
        if hasattr(self, 'progress_dialog'):
            self.progress_dialog.setValue(percent)
            self.progress_dialog.setLabelText(message)
    
    def _on_download_finished(self, success: bool, message: str):
        """다운로드 완료 처리"""
        if hasattr(self, 'progress_dialog'):
            self.progress_dialog.close()
            
        if hasattr(self, 'download_worker'):
            self.download_worker.deleteLater()
            
        if success:
            QMessageBox.information(self.widget, "다운로드 완료", message)
            # 파일 로드
            data_path = Path("data")
            if self.current_mode == "NAID4.5F-31000":
                file_path = data_path / "artist_thumbnail_nai.json"
            else:
                file_path = data_path / "artist_thumbnail.json"
            self._load_thumbnail_data(self.current_mode, file_path)
        else:
            QMessageBox.critical(self.widget, "다운로드 실패", f"다운로드 중 오류가 발생했습니다:\n{message}")
            # 실패 시 콤보박스를 이전 상태로
            if hasattr(self, '_previous_mode'):
                self.mode_combo.blockSignals(True)
                self.mode_combo.setCurrentText(self._previous_mode)
                self.mode_combo.blockSignals(False)
    
    def _load_thumbnail_data(self, mode: str, file_path: Path):
        """썸네일 데이터 파일 로드"""
        # 로딩 다이얼로그 표시
        loading_dialog = QProgressDialog(self.widget)
        loading_dialog.setWindowTitle("파일 열기")
        loading_dialog.setLabelText("파일을 여는 중입니다...")
        loading_dialog.setRange(0, 0)  # Indeterminate progress
        loading_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        loading_dialog.setCancelButton(None)
        loading_dialog.setMinimumDuration(0)
        loading_dialog.show()
        
        # 이벤트 처리를 위한 짧은 지연
        QApplication.processEvents()
        
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                data = json.load(file)
                
            # 데이터 저장
            if mode == "NAID4.5F-31000":
                self.nai_data = data
                self.artist_data = self.nai_data
            else:
                self.noob_data = data
                self.artist_data = self.noob_data
                
            # 리스트 업데이트
            self._update_artist_list_from_data()
            
            loading_dialog.close()
            
        except Exception as e:
            loading_dialog.close()
            QMessageBox.critical(self.widget, "오류", f"파일을 열 수 없습니다:\n{str(e)}")
            # 실패 시 콤보박스를 이전 상태로
            if hasattr(self, '_previous_mode'):
                self.mode_combo.blockSignals(True)
                self.mode_combo.setCurrentText(self._previous_mode)
                self.mode_combo.blockSignals(False)
    
    
    def _update_listbox(self, items: List[str]):
        """리스트박스 업데이트 - 아티스트명만 표시"""
        self.artist_listbox.clear()
        
        for item in items:
            # 아티스트명만 표시
            list_item = QListWidgetItem(item)
            
            # 가중치는 툴팁으로만 표시
            weight = artist_dict.get(item, 0)
            list_item.setToolTip(f"아티스트: {item}\n가중치: {weight:,}")
            
            self.artist_listbox.addItem(list_item)
    
    def _perform_search(self):
        """검색 결과를 포커스를 훔치지 않는 QListWidget 팝업으로 표시"""
        search_text = self.search_input.text().strip().lower()
        
        # 최소 1글자 이상일 때만 검색 수행
        if len(search_text) < 1:
            if self.search_popup and self.search_popup.isVisible():
                self.search_popup.hide()
            # 빈 검색어일 때는 전체 리스트 업데이트 하지 않음 (성능 문제 방지)
            return

        results = []

        # 시작 매치 우선
        for artist in self.artist_list:
            al = artist.lower()
            if al.startswith(search_text):
                value = artist_dict.get(artist, 0)
                results.append((artist, value, 0))
                if len(results) >= self.max_suggestions:
                    break

        # 포함 매치 (모자라면)
        if len(results) < self.max_suggestions:
            for artist in self.artist_list:
                al = artist.lower()
                if search_text in al and not al.startswith(search_text):
                    value = artist_dict.get(artist, 0)
                    results.append((artist, value, 1))
                    if len(results) >= self.max_suggestions:
                        break

        # 정렬: 매치 타입 → 가중치
        results.sort(key=lambda x: (x[2], -x[1]))
        results = results[:self.max_suggestions]

        # 팝업 채우기/표시
        if results:
            self.search_popup.clear()
            for artist, weight, _ in results:
                # 가중치 짧게
                wtxt = f"{weight/1000:.1f}k" if weight >= 1000 else str(weight)
                # 고정폭 폰트를 위해 적절한 패딩 추가
                padding = max(50 - len(artist), 4)  # 최소 4칸 간격
                display_text = f"{artist}{' ' * padding}{wtxt}"
                item = QListWidgetItem(display_text)
                # 정렬용 실제 값 보관
                item.setData(Qt.ItemDataRole.UserRole, artist)
                self.search_popup.addItem(item)

            # 첫 항목 선택
            if self.search_popup.count() > 0:
                self.search_popup.setCurrentRow(0)

            # 위치/크기
            line = self.search_input
            global_pos = line.mapToGlobal(QPoint(0, line.height()))
            self.search_popup.move(global_pos)
            # 너비는 검색창보다 넓게, 높이는 최대 10개 항목
            self.search_popup.resize(max(line.width(), get_scaled_size(400)),
                                    self.search_popup.sizeHintForRow(0) * min(self.search_popup.count(), 10) + get_scaled_size(8))
            self.search_popup.show()
            # 포커스는 계속 라인에디트에
            self.search_input.setFocus()
        else:
            if self.search_popup.isVisible():
                self.search_popup.hide()


    
    def _on_artist_selected(self):
        """아티스트 선택 시"""
        current_item = self.artist_listbox.currentItem()
        
        if not current_item:
            return
        
        # 이제 리스트에는 아티스트명만 있으므로 직접 사용
        artist_name = current_item.text()
        self.current_artist = artist_name
        
        # 썸네일 표시
        self._display_artist_thumbnail(artist_name)
        
        # 정보 업데이트
        weight = artist_dict.get(artist_name, 0) if artist_dict else 0
        self.info_label.setText(f"선택된 아티스트: {artist_name} (가중치: {weight})")
        
        # 복사 버튼 활성화
        self.copy_button.setEnabled(True)
        
        # 프롬프트에 아티스트명 추가 (항상 자동 적용)
        if hasattr(self, 'positive_prompt'):
            current_positive = self.positive_prompt.toPlainText()
            # 기존 아티스트 태그 제거
            lines = current_positive.split(',')
            lines = [line.strip() for line in lines if not line.strip().startswith('artist:')]
            # 새 아티스트 태그 추가
            artist_tag = f"artist:{artist_name}"
            if lines:
                self.positive_prompt.setPlainText(f"{artist_tag}, {', '.join(lines)}")
            else:
                self.positive_prompt.setPlainText(artist_tag)
        
        # 시그널 발생
        self.artist_selected.emit(artist_name)
    
    def _display_artist_thumbnail(self, artist_name: str):
        """아티스트 썸네일 표시"""
        img_data_list = self.artist_data.get(artist_name, [])
        
        if img_data_list and img_data_list[0]:
            try:
                # base64 디코딩
                img_bytes = base64.b64decode(img_data_list[0])
                
                # QPixmap으로 직접 변환
                pixmap = QPixmap()
                pixmap.loadFromData(img_bytes)
                
                if hasattr(self, 'thumbnail_label'):
                    # 좌우 85픽셀씩 잘라내기 (검은색 썸네일 영역 제거)
                    if pixmap.width() > 170:  # 최소 170픽셀 이상일 때만 크롭
                        cropped_pixmap = pixmap.copy(
                            85,  # x 시작점
                            0,   # y 시작점
                            pixmap.width() - 170,  # 너비 (양쪽 85픽셀씩 제거)
                            pixmap.height()  # 높이 유지
                        )
                    else:
                        cropped_pixmap = pixmap
                    
                    # 고정된 썸네일 크기 사용 (패딩 고려)
                    # 라벨의 고정 크기에서 패딩을 뺀 실제 이미지 영역 계산
                    padding = get_scaled_size(4) * 2  # 양쪽 패딩
                    target_width = 450 - padding
                    target_height = int(450 * 3.8 / 3.0) - padding
                    
                    # 계산된 크기로 스케일링
                    scaled_pixmap = cropped_pixmap.scaled(
                        target_width,
                        target_height,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    self.thumbnail_label.setPixmap(scaled_pixmap)
                
            except Exception as e:
                print(f"썸네일 표시 오류: {e}")
                if hasattr(self, 'thumbnail_label'):
                    self._show_default_thumbnail()
        else:
            if hasattr(self, 'thumbnail_label'):
                self._show_default_thumbnail()
    
    def _display_artist_image(self, artist_name: str):
        """아티스트 이미지 표시 (하위 호환성)"""
        img_data_list = self.artist_data.get(artist_name, [])
        
        if img_data_list and img_data_list[0]:
            try:
                # base64 디코딩
                img_bytes = base64.b64decode(img_data_list[0])
                
                # PIL 이미지로 변환
                img = Image.open(io.BytesIO(img_bytes))
                img = img.resize((512, 512), Image.Resampling.LANCZOS)
                
                # QPixmap으로 변환
                img_bytes = io.BytesIO()
                img.save(img_bytes, format='PNG')
                img_bytes.seek(0)
                
                pixmap = QPixmap()
                pixmap.loadFromData(img_bytes.read())
                
                self.image_label.setPixmap(pixmap)
                
            except Exception as e:
                print(f"이미지 표시 오류: {e}")
                self._show_default_image()
        else:
            self._show_default_image()
    
    def _copy_artist_name(self):
        """현재 선택된 아티스트 이름 복사"""
        if self.current_artist:
            clipboard = QApplication.clipboard()
            clipboard.setText(self.current_artist)
            
            # 복사 완료 피드백
            original_text = self.copy_button.text()
            self.copy_button.setText("✅ 복사됨!")
            QTimer.singleShot(1000, lambda: self.copy_button.setText(original_text))
            
            # 시그널 발생
            self.copy_requested.emit(self.current_artist)
    
    def _on_popup_item_clicked(self, item):
        artist = item.data(Qt.ItemDataRole.UserRole)
        self._accept_suggestion(artist)

    def _accept_suggestion(self, artist: str):
        """선택한 추천어를 적용"""
        self.search_input.setText(artist)

        # 메인 리스트에서 해당 아티스트 선택
        for i in range(self.artist_listbox.count()):
            if self.artist_listbox.item(i).text() == artist:
                self.artist_listbox.setCurrentRow(i)
                self.artist_listbox.scrollToItem(self.artist_listbox.item(i))
                break

        if self.search_popup.isVisible():
            self.search_popup.hide()
        self.search_input.setFocus()

    def _init_search_popup(self):
        """QListWidget 기반 검색 팝업 초기화 (포커스 훔치지 않음)"""
        from PyQt6.QtWidgets import QListWidget
        self.search_popup = QListWidget(self.widget)
        self.search_popup.setWindowFlags(Qt.WindowType.ToolTip)
        # 포커스 훔치지 않기
        self.search_popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.search_popup.setMouseTracking(True)
        self.search_popup.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.search_popup.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.search_popup.setStyleSheet(f"""
            QListWidget {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                border: 2px solid {DARK_COLORS['accent_blue']};
                border-radius: {get_scaled_size(4)}px;
                font-size: {get_scaled_font_size(14)}px;
                font-family: 'Consolas', 'Courier New', monospace;
            }}
            QListWidget::item {{
                padding: {get_scaled_size(6)}px {get_scaled_size(8)}px;
            }}
            QListWidget::item:selected {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
            QListWidget::item:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        self.search_popup.itemClicked.connect(self._on_popup_item_clicked)

        # 라인에디트에서 키를 가로채 팝업 제어
        self.search_input.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.search_input and event.type() == event.Type.KeyPress:
            key = event.key()
            # 팝업이 열려 있을 때만 네비게이션
            if self.search_popup and self.search_popup.isVisible():
                if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                    current = self.search_popup.currentRow()
                    if key == Qt.Key.Key_Down:
                        current = min(current + 1, self.search_popup.count() - 1)
                    else:
                        current = max(current - 1, 0)
                    self.search_popup.setCurrentRow(current)
                    return True  # ✅ 라인에디트로 전달하지 않음

                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
                    item = self.search_popup.currentItem()
                    if item:
                        self._accept_suggestion(item.data(Qt.ItemDataRole.UserRole))
                    return True  # ✅ 기본 탭 이동/엔터 입력 막음

                if key == Qt.Key.Key_Escape:
                    self.search_popup.hide()
                    return True

            # 팝업이 닫혀있고 ↓면 팝업을 열고 첫 항목 선택
            if key == Qt.Key.Key_Down and self.search_popup and not self.search_popup.isVisible():
                self._perform_search()
                return True

        return super().eventFilter(obj, event)
    
    def _on_generate_clicked(self):
        """Generate 버튼 클릭 시 이미지 생성"""
        if not self.app_context:
            QMessageBox.warning(self.widget, "오류", "앱 컨텍스트가 없습니다.")
            return
            
        # Positive 프롬프트 가져오기
        positive = self.positive_prompt.toPlainText().strip()
        
        # Prefix와 Postfix 가져오기
        prefix = self.prefix_textedit.toPlainText().strip()
        postfix = self.postfix_textedit.toPlainText().strip()
        
        # 최종 프롬프트 조합: prefix + positive + postfix
        final_prompt_parts = []
        if prefix:
            final_prompt_parts.append(prefix)
        if positive:
            final_prompt_parts.append(positive)
        if postfix:
            final_prompt_parts.append(postfix)
        
        final_positive = ", ".join(final_prompt_parts)
        
        # Negative 프롬프트는 메인 윈도우에서 가져오기
        negative = ""
        if hasattr(self.app_context, 'main_window') and hasattr(self.app_context.main_window, 'negative_prompt_text'):
            negative = self.app_context.main_window.negative_prompt_text.toPlainText().strip()
        
        if not final_positive:
            QMessageBox.warning(self.widget, "경고", "프롬프트를 입력하세요.")
            return
        
        # 오버라이드 파라미터 준비
        override_params = {
            'input': final_positive,
            'negative_prompt': negative,
            'width': 832,
            'height': 1216,
            'random_resolution': False,
            'artist_thumb_request': True  # ArtistThumb 전용 식별자
        }
        
        # 자동 생성 체크박스 해제 (필요한 경우)
        if hasattr(self.app_context, 'main_window'):
            auto_generate_checkbox = self.app_context.main_window.generation_checkboxes.get("자동 생성")
            if auto_generate_checkbox and auto_generate_checkbox.isChecked():
                auto_generate_checkbox.setChecked(False)
        
        # ArtistThumb 전용 생성 완료 이벤트 구독
        self.app_context.subscribe("generation_completed_for_artist_thumb", self._on_generation_completed)
        
        # Generate 버튼 비활성화
        self.generate_btn.setEnabled(False)
        self.generate_btn.setText("🔄 생성 중...")
        
        # generation_controller의 execute_generation_pipeline 호출
        if hasattr(self.app_context, 'main_window'):
            gen_controller = self.app_context.main_window.generation_controller
            gen_controller.execute_generation_pipeline(overrides=override_params)
            print(f"🎨 ArtistThumb: 이미지 생성 시작 (832x1216)")
        else:
            print("⚠️ generation_controller를 찾을 수 없습니다.")
            # 오류 발생 시 버튼 복원
            self.generate_btn.setEnabled(True)
            self.generate_btn.setText("🎨 Generate (832x1216)")
    
    def _on_generation_completed(self, result):
        """이미지 생성 완료 콜백"""
        try:
            # ArtistThumb 전용 구독 해제
            if "generation_completed_for_artist_thumb" in self.app_context.subscribers:
                self.app_context.subscribers["generation_completed_for_artist_thumb"].remove(self._on_generation_completed)
            
            # result가 PIL Image인지 확인
            image_object = result
            if hasattr(image_object, 'mode'):  # PIL Image 확인
                # StableImageWidget에 표시
                if hasattr(self, 'generation_image'):
                    self.generation_image.setPilImage(image_object)
                    print("✅ ArtistThumb: 이미지 생성 완료")
                
                # Generate 버튼 복원
                self.generate_btn.setEnabled(True)
                self.generate_btn.setText("🎨 Generate (832x1216)")
                
                # 상태바 메시지
                if hasattr(self.app_context, 'main_window'):
                    self.app_context.main_window.status_bar.showMessage(
                        "✅ ArtistThumb: 이미지 생성 완료", 3000
                    )
            else:
                print(f"⚠️ 예상과 다른 결과 타입: {type(result)}")
                # 오류 시에도 버튼 복원
                self.generate_btn.setEnabled(True)
                self.generate_btn.setText("🎨 Generate (832x1216)")
                
        except Exception as e:
            print(f"❌ 생성 완료 처리 중 오류: {e}")
            print(f"결과 타입: {type(result)}")
            # 예외 시에도 버튼 복원
            self.generate_btn.setEnabled(True)
            self.generate_btn.setText("🎨 Generate (832x1216)")
    
    def cleanup(self):
        """탭 종료 시 정리"""
        if self.search_popup and self.search_popup.isVisible():
            self.search_popup.hide()