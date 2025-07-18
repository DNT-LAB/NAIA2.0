import os
import json
import time
from dataclasses import dataclass, field
from typing import Dict, Any
from io import BytesIO
import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTextEdit, QSplitter, QPushButton,
    QHBoxLayout, QCheckBox, QScrollArea, QMenu, QDialog, QFileDialog
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QMouseEvent, QPainter, QColor, QAction
from PIL import Image, ImageQt
from ui.theme import DARK_STYLES, DARK_COLORS
import piexif, io

# --- 1. ImageLabel 클래스: 오직 이미지 표시와 리사이징만 담당 ---
class ImageLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(1, 1)
        self.full_pixmap = None

    def setFullPixmap(self, pixmap: QPixmap | None):
        """원본 QPixmap을 저장하고, 첫 리사이징을 트리거합니다."""
        self.full_pixmap = pixmap
        # 위젯의 현재 크기에 맞춰 이미지 업데이트
        self.resizeEvent(None) 

    def resizeEvent(self, event):
        """위젯의 크기가 변경될 때마다 호출되는 이벤트 핸들러"""
        if self.full_pixmap is None:
            # Pixmap이 없으면, 초기 텍스트를 다시 설정
            self.setText("Generated Image")
            return

        scaled_pixmap = self.full_pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.setPixmap(scaled_pixmap)

@dataclass
class HistoryItem:
    image: Image.Image
    thumbnail: QPixmap
    info_text: str
    source_row: pd.Series
    raw_bytes: bytes | None = None
    filepath: str | None = None 
    metadata: Dict[str, Any] = field(default_factory=dict)
    comfyui_workflow: Dict[str, Any] = field(default_factory=dict)  # 🆕 ComfyUI 워크플로우 정보

class ImageHistoryWindow(QWidget):
    """이미지 히스토리 패널"""
    history_item_selected = pyqtSignal(HistoryItem)
    load_prompt_requested = pyqtSignal(str)
    reroll_requested = pyqtSignal(pd.Series)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.history_widgets: list[HistoryItemWidget] = []
        self.current_selected_widget: HistoryItemWidget | None = None
        self.init_ui()

    def init_ui(self):
        # [수정] 메인 레이아웃 및 제목 추가
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 0, 0, 4)
        main_layout.setSpacing(4)

        # [신규] 히스토리 제목 레이블
        title_label = QLabel("📜 히스토리")
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: 14px;
                font-weight: bold;
                padding: 4px;
            }}
        """)
        main_layout.addWidget(title_label)
        
        # [수정] 스크롤 영역 스타일 개선
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: #212121;
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
        """)
        
        container = QWidget()
        # [수정] 컨테이너 배경을 투명하게 하여 스크롤 영역의 배경색이 보이도록 함
        container.setStyleSheet("background-color: transparent;")
        
        self.history_layout = QVBoxLayout(container)
        self.history_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.history_layout.setContentsMargins(4, 4, 4, 4)
        self.history_layout.setSpacing(4)
        
        scroll_area.setWidget(container)
        main_layout.addWidget(scroll_area)

    def add_history_item(self, history_item: HistoryItem):
        """새로운 히스토리 아이템을 받아 위젯을 생성하고 목록 최상단에 추가"""
        item_widget = HistoryItemWidget(history_item)
        item_widget.item_selected.connect(self.on_item_selected)

        # [추가] HistoryItemWidget의 시그널을 ImageHistoryWindow의 시그널에 연결
        item_widget.load_prompt_requested.connect(self.load_prompt_requested)
        item_widget.reroll_requested.connect(self.reroll_requested)
        
        # 새 아이템을 레이아웃의 맨 위에 추가
        self.history_layout.insertWidget(0, item_widget)
        self.history_widgets.insert(0, item_widget)
        
        # 새로 추가된 아이템을 선택 상태로 만듦
        self.on_item_selected(history_item)

    def on_item_selected(self, history_item: HistoryItem):
        """히스토리 아이템이 선택되었을 때 처리"""
        # 이전에 선택된 위젯의 선택 상태 해제
        if self.current_selected_widget:
            self.current_selected_widget.set_selected(False)

        # 새로 선택된 위젯 찾아서 선택 상태로 변경
        for widget in self.history_widgets:
            if widget.history_item == history_item:
                widget.set_selected(True)
                self.current_selected_widget = widget
                break
        
        # 상위 위젯(ImageWindow)으로 선택된 아이템 정보 전달
        self.history_item_selected.emit(history_item)

    def remove_current_item(self):
        if not self.current_selected_widget:
            return False
        idx = self.history_widgets.index(self.current_selected_widget)
        widget_to_remove = self.current_selected_widget

        self.history_widgets.remove(widget_to_remove)
        self.history_layout.removeWidget(widget_to_remove)
        widget_to_remove.deleteLater()
        self.current_selected_widget = None

        # ↓ 삭제 후 아래(또는 위) 자동 선택
        if self.history_widgets:
            next_idx = min(idx, len(self.history_widgets)-1)
            self.select_item_by_idx(next_idx)
        return True

    def select_item_by_idx(self, idx):
        if 0 <= idx < len(self.history_widgets):
            self.on_item_selected(self.history_widgets[idx].history_item)

# [신규] 히스토리 목록의 개별 항목을 표시하는 위젯
class HistoryItemWidget(QWidget):
    # 위젯이 클릭되었을 때 HistoryItem 객체를 전달하는 시그널
    load_prompt_requested = pyqtSignal(str)
    reroll_requested = pyqtSignal(pd.Series)
    item_selected = pyqtSignal(HistoryItem)

    def __init__(self, history_item: HistoryItem, parent=None):
        super().__init__(parent)
        self.history_item = history_item
        self.is_selected = False
        self.init_ui()
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setPixmap(self.history_item.thumbnail)
        self.thumbnail_label.setScaledContents(True)
        self.thumbnail_label.setFixedSize(128, 128) # 썸네일 크기 고정
        
        layout.addWidget(self.thumbnail_label)
        self.update_selection_style()

    def show_context_menu(self, pos):
        """우클릭 시 컨텍스트 메뉴를 표시합니다."""
        menu = QMenu(self)
        menu_style = f"""
            QMenu {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 5px;
            }}
            QMenu::item {{
                padding: 8px 20px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {DARK_COLORS['border']};
                margin: 5px 0px;
            }}
        """
        menu.setStyleSheet(menu_style)
        
        # "프롬프트 불러오기" 액션
        load_action = QAction("프롬프트 불러오기", self)
        load_action.triggered.connect(self.emit_load_prompt)
        menu.addAction(load_action)
        
        # "프롬프트 다시개봉" 액션
        reroll_action = QAction("프롬프트 다시개봉", self)
        # source_row가 없는 경우 비활성화
        if self.history_item.source_row is None or self.history_item.source_row.empty:
            reroll_action.setEnabled(False)
        reroll_action.triggered.connect(self.emit_reroll_prompt)
        menu.addAction(reroll_action)

        copy_png_action = QAction("PNG로 클립보드 복사", self)
        copy_webp_action = QAction("WEBP로 클립보드 복사", self)
        copy_png_action.triggered.connect(lambda: self.copy_image_to_clipboard('PNG'))
        copy_webp_action.triggered.connect(lambda: self.copy_image_to_clipboard('WEBP'))
        menu.addAction(copy_png_action)
        menu.addAction(copy_webp_action)
        menu.exec(self.mapToGlobal(pos))

    def emit_load_prompt(self):
        """'프롬프트 불러오기' 시그널을 발생시킵니다."""
        info = self.history_item.info_text
        # Negative prompt 이전 부분만 추출
        positive_prompt = info.split('Negative prompt:')[0].strip()
        self.load_prompt_requested.emit(positive_prompt)

    def emit_reroll_prompt(self):
        """'프롬프트 다시개봉' 시그널을 발생시킵니다."""
        self.reroll_requested.emit(self.history_item.source_row)

    def show_comfyui_workflow(self):
        """🆕 ComfyUI 워크플로우 정보를 보여주는 다이얼로그"""
        try:
            dialog = QDialog(self)
            dialog.setWindowTitle("ComfyUI 워크플로우 정보")
            dialog.setModal(True)
            dialog.resize(600, 400)
            
            layout = QVBoxLayout(dialog)
            
            # 워크플로우 정보 표시
            text_edit = QTextEdit()
            text_edit.setReadOnly(True)
            text_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
            
            # JSON을 보기 좋게 포맷
            formatted_text = ""
            for key, value in self.history_item.comfyui_workflow.items():
                formatted_text += f"=== {key} ===\n"
                if isinstance(value, dict):
                    formatted_text += json.dumps(value, indent=2, ensure_ascii=False)
                else:
                    formatted_text += str(value)
                formatted_text += " "
            
            text_edit.setPlainText(formatted_text)
            layout.addWidget(text_edit)
            
            # 버튼
            button_layout = QHBoxLayout()
            
            # 워크플로우 저장 버튼
            save_btn = QPushButton("워크플로우 저장")
            save_btn.setStyleSheet(DARK_STYLES['secondary_button'])
            save_btn.clicked.connect(lambda: self.save_comfyui_workflow())
            button_layout.addWidget(save_btn)
            
            # 닫기 버튼
            close_btn = QPushButton("닫기")
            close_btn.setStyleSheet(DARK_STYLES['secondary_button'])
            close_btn.clicked.connect(dialog.accept)
            button_layout.addWidget(close_btn)
            
            layout.addLayout(button_layout)
            
            dialog.exec()
            
        except Exception as e:
            print(f"❌ 워크플로우 다이얼로그 표시 실패: {e}")

    def save_comfyui_workflow(self):
        """🆕 ComfyUI 워크플로우를 파일로 저장"""
        try:
            if 'workflow' in self.history_item.comfyui_workflow:
                # 파일 저장 다이얼로그
                file_path, _ = QFileDialog.getSaveFileName(
                    self,
                    "ComfyUI 워크플로우 저장",
                    f"comfyui_workflow_{int(time.time())}.json",
                    "JSON Files (*.json)"
                )
                
                if file_path:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(self.history_item.comfyui_workflow['workflow'], f, indent=2, ensure_ascii=False)
                    
                    print(f"✅ 워크플로우 저장 완료: {file_path}")
            else:
                print("⚠️ 저장할 워크플로우 정보가 없습니다.")
                
        except Exception as e:
            print(f"❌ 워크플로우 저장 실패: {e}")
        
    def mousePressEvent(self, event: QMouseEvent):
        """위젯 클릭 시 item_selected 시그널 발생"""
        # [수정] 좌클릭 시에만 선택 시그널 발생
        if event.button() == Qt.MouseButton.LeftButton:
            self.item_selected.emit(self.history_item)
        super().mousePressEvent(event)

    def set_selected(self, selected: bool):
        """선택 상태 업데이트 및 스타일 변경"""
        self.is_selected = selected
        self.update_selection_style()

    def update_selection_style(self):
        """선택 상태에 따라 테두리 스타일 변경"""
        if self.is_selected:
            self.thumbnail_label.setStyleSheet(f"""
                QLabel {{ 
                    border: 2px solid {DARK_COLORS['accent_blue']}; 
                    border-radius: 4px;
                }}
            """)
        else:
            self.thumbnail_label.setStyleSheet("border: none;")

    def copy_image_to_clipboard(self, fmt='PNG'):
        from PyQt6.QtWidgets import QApplication
        import io
        pil_img = self.history_item.image
        buf = io.BytesIO()
        if fmt == 'PNG':
            pil_img.save(buf, format='PNG')
        else:
            pil_img.save(buf, format='WEBP', quality=90, method=6)
        buf.seek(0)
        qimg = QPixmap()
        qimg.loadFromData(buf.getvalue())
        QApplication.clipboard().setPixmap(qimg)
        print(f"✅ 이미지가 클립보드에 복사되었습니다. ({fmt})")

# --- 2. ImageWindow 클래스: 위젯들을 담는 컨테이너이자, 외부와의 소통 창구 ---
class ImageWindow(QWidget):
    instant_generation_requested = pyqtSignal(object)
    load_prompt_to_main_ui = pyqtSignal(str)

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        # 모든 멤버 변수를 먼저 선언합니다.
        self.main_image_label: ImageLabel = None
        self.info_textbox: QTextEdit = None
        self.info_panel: QWidget = None
        self.auto_save_checkbox: QCheckBox = None
        self.image_history_window: ImageHistoryWindow = None
        self.info_visible = True
        self.app_context = app_context
        self.history_visible = True 
        self.toggle_history_button: QPushButton = None
        self.save_counter = 1  
        self.current_history_item = None 
        # 🆕 ComfyUI 워크플로우 캐시
        self.comfyui_workflow_cache: Dict[int, Dict] = {}

        self.init_ui()

    def init_ui(self):
        # 1. ImageWindow 자체의 메인 레이아웃 (수평)
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 2. 전체를 좌우로 나눌 메인 수평 스플리터
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- 3. 왼쪽 패널 구성 ---
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 0, 4, 0)
        left_layout.setSpacing(4)

        # 3-1. 컨트롤 버튼 영역 (상단)
        control_layout = QHBoxLayout()
        self.auto_save_checkbox = QCheckBox("자동 저장")
        self.auto_save_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])

        self.toggle_history_button = QPushButton("📜 히스토리 숨기기")
        self.toggle_history_button.setCheckable(True)
        self.toggle_history_button.setChecked(True)
        self.toggle_history_button.setStyleSheet(DARK_STYLES['secondary_button'])
        self.toggle_history_button.clicked.connect(self.toggle_history_panel)

        self.save_button = QPushButton("💾 이미지 저장")
        self.save_button.setStyleSheet(DARK_STYLES['secondary_button'])
        self.save_button.setToolTip("현재 보고 있는 이미지를 EXIF 정보와 함께 저장합니다.")
        self.save_button.clicked.connect(self.save_current_image)
        
        self.save_as_webp_checkbox = QCheckBox("WEBP로 저장")
        self.save_as_webp_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])

        # 초기화 버튼
        clear_button = QPushButton("🗑️ 지우기")
        clear_button.setStyleSheet("""
            QPushButton {
                background-color: #d32f2f;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #f44336;
            }
        """)
        clear_button.clicked.connect(self.clear_all)
        control_layout.addWidget(self.auto_save_checkbox)
        control_layout.addStretch()
        control_layout.addWidget(clear_button)
        control_layout.addWidget(self.save_button)
        control_layout.addWidget(self.save_as_webp_checkbox)

        self.open_folder_button = QPushButton("폴더 열기")
        self.open_folder_button.setStyleSheet(DARK_STYLES['secondary_button'])
        self.open_folder_button.clicked.connect(self.open_folder)
        control_layout.addWidget(self.open_folder_button)

        left_layout.addLayout(control_layout)

        # 수직 스플리터 생성
        image_info_splitter = QSplitter(Qt.Orientation.Vertical)
        image_info_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #555555;
                border: 1px solid #777777;
                height: 1px;
                margin: 0px 1px;
                border-radius: 1px;
            }
            QSplitter::handle:hover {
                background-color: #666666;
            }
        """)

        # 3-2-a. 이미지 표시 영역
        self.main_image_label = ImageLabel()
        self.main_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_image_label.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 8px;
                color: {DARK_COLORS['text_secondary']};
                font-size: 14px;
            }}
        """)
        self.main_image_label.setText("Generated Image")
        
        # 3-2-b. 정보 패널 (제목 + 텍스트박스)
        self.info_panel = QWidget()
        info_panel_layout = QVBoxLayout(self.info_panel)
        info_panel_layout.setContentsMargins(0, 4, 0, 0)
        info_panel_layout.setSpacing(4)
        
        info_title = QLabel("📝 생성 정보")
        info_title.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-weight: bold;
                font-size: 12px;
                padding: 2px 4px;
            }}
        """)
        info_panel_layout.addWidget(info_title)
        
        self.info_textbox = QTextEdit()
        self.info_textbox.setReadOnly(True)
        self.info_textbox.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.info_textbox.setPlaceholderText("생성 정보가 여기에 표시됩니다...")
        info_panel_layout.addWidget(self.info_textbox)

        # 수직 스플리터에 이미지와 정보 패널 추가
        image_info_splitter.addWidget(self.main_image_label)
        image_info_splitter.addWidget(self.info_panel)
        image_info_splitter.setStretchFactor(0, 50)
        image_info_splitter.setStretchFactor(1, 1)
        
        # 왼쪽 패널 레이아웃에 수직 스플리터 추가
        left_layout.addWidget(image_info_splitter)

        # --- 4. 오른쪽 패널 구성 (이미지 히스토리) ---
        self.image_history_window = ImageHistoryWindow(self)
        self.image_history_window.history_item_selected.connect(self.display_history_item)
        self.image_history_window.setFixedWidth(140)

        # --- 5. 최종 조립 ---
        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(self.image_history_window)
        main_splitter.setStretchFactor(0, 70)
        main_splitter.setStretchFactor(1, 30)
        main_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #555555;
                border: 2px solid #777777;
                width: 2px; /* 수평 스플리터는 width로 두께 조절 */
                margin: 1px 0px;
                border-radius: 1px;
            }
            QSplitter::handle:hover {
                background-color: #666666;
            }
        """)
        main_layout.addWidget(main_splitter)

        # [추가] 히스토리 창에서 오는 시그널들을 메인 윈도우로 전달할 슬롯에 연결
        self.image_history_window.load_prompt_requested.connect(self.load_prompt_to_main_ui)
        self.image_history_window.reroll_requested.connect(self.instant_generation_requested)
        
        # [추가] 메인 이미지 레이블에 컨텍스트 메뉴 설정
        self.main_image_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.main_image_label.customContextMenuRequested.connect(self.show_main_image_context_menu)

    def show_main_image_context_menu(self, pos):
        """메인 이미지 우클릭 시 컨텍스트 메뉴를 표시합니다."""
        if not self.current_history_item:
            return
            
        menu = QMenu(self)
        menu_style = f"""
            QMenu {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 5px;
            }}
            QMenu::item {{
                padding: 8px 20px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {DARK_COLORS['border']};
                margin: 5px 0px;
            }}
        """
        menu.setStyleSheet(menu_style)
        load_action = QAction("프롬프트 불러오기", self)
        load_action.triggered.connect(self._load_current_prompt)
        menu.addAction(load_action)
        
        reroll_action = QAction("프롬프트 다시개봉", self)
        if self.current_history_item.source_row is None or self.current_history_item.source_row.empty:
            reroll_action.setEnabled(False)
        reroll_action.triggered.connect(self._reroll_current_prompt)
        menu.addAction(reroll_action)
        
        copy_png_action = QAction("PNG로 클립보드 복사", self)
        copy_webp_action = QAction("WEBP로 클립보드 복사", self)
        copy_png_action.triggered.connect(lambda: self.copy_image_to_clipboard('PNG'))
        copy_webp_action.triggered.connect(lambda: self.copy_image_to_clipboard('WEBP'))
        menu.addAction(copy_png_action)
        menu.addAction(copy_webp_action)
        
        menu.exec(self.main_image_label.mapToGlobal(pos))

    def _load_current_prompt(self):
        """현재 표시 중인 이미지의 프롬프트를 불러옵니다."""
        if self.current_history_item:
            info = self.current_history_item.info_text
            positive_prompt = info.split('Negative prompt:')[0].strip()
            self.load_prompt_to_main_ui.emit(positive_prompt)

    def _reroll_current_prompt(self):
        """현재 표시 중인 이미지의 프롬프트로 다시 생성을 요청합니다."""
        if self.current_history_item and self.current_history_item.source_row is not None:
            self.instant_generation_requested.emit(self.current_history_item.source_row)

    def _show_current_comfyui_workflow(self):
        """🆕 현재 이미지의 ComfyUI 워크플로우를 표시합니다."""
        if self.current_history_item and self.current_history_item.comfyui_workflow:
            # HistoryItemWidget의 show_comfyui_workflow 메소드를 재사용
            temp_widget = HistoryItemWidget(self.current_history_item)
            temp_widget.show_comfyui_workflow()

    def _save_current_comfyui_workflow(self):
        """🆕 현재 이미지의 ComfyUI 워크플로우를 저장합니다."""
        if self.current_history_item and self.current_history_item.comfyui_workflow:
            # HistoryItemWidget의 save_comfyui_workflow 메소드를 재사용
            temp_widget = HistoryItemWidget(self.current_history_item)
            temp_widget.save_comfyui_workflow()

    # 🆕 ComfyUI 메타데이터 처리 메소드들
    def strip_comfyui_metadata(self, image_object):
        """ComfyUI 메타데이터를 제거한 깨끗한 이미지 반환"""
        try:
            print("🧹 ComfyUI 이미지 메타데이터 정리 시작")
            
            # ComfyUI 메타데이터 추출 및 저장
            comfyui_metadata = {}
            if hasattr(image_object, 'info') and image_object.info:
                print(f"메타데이터 키: {list(image_object.info.keys())}")
                
                # ComfyUI가 사용하는 주요 메타데이터 키들
                comfyui_keys = ['workflow', 'prompt', 'parameters', 'ComfyUI']
                
                for key in image_object.info:
                    if any(comfyui_key.lower() in key.lower() for comfyui_key in comfyui_keys):
                        comfyui_metadata[key] = image_object.info[key]
                        print(f"  - ComfyUI 메타데이터 발견: {key} ({len(str(image_object.info[key]))} chars)")
            
            # 새로운 이미지 생성 (메타데이터 없음)
            clean_image = Image.new(image_object.mode, image_object.size)
            clean_image.paste(image_object)
            
            # 기본 정보만 유지 (Qt 호환성 확보)
            clean_info = {}
            safe_keys = ['dpi', 'aspect']  # Qt가 안전하게 처리할 수 있는 키들
            
            for key in safe_keys:
                if hasattr(image_object, 'info') and image_object.info and key in image_object.info:
                    clean_info[key] = image_object.info[key]
            
            clean_image.info = clean_info
            
            print(f"✅ ComfyUI 메타데이터 제거 완료: {image_object.size}")
            print(f"  - 제거된 ComfyUI 메타데이터: {len(comfyui_metadata)}개")
            print(f"  - 유지된 안전한 메타데이터: {len(clean_info)}개")
            
            return clean_image, comfyui_metadata
            
        except Exception as e:
            print(f"⚠️ 메타데이터 제거 실패, 원본 사용: {e}")
            return image_object, {}

    def extract_comfyui_workflow_info(self, comfyui_metadata):
        """ComfyUI 메타데이터에서 유용한 정보 추출"""
        try:
            workflow_info = {}
            
            for key, value in comfyui_metadata.items():
                if 'workflow' in key.lower():
                    try:
                        if isinstance(value, str):
                            workflow_data = json.loads(value)
                            workflow_info['workflow'] = workflow_data
                            print(f"✅ 워크플로우 데이터 파싱 성공: {len(workflow_data)} 노드")
                    except json.JSONDecodeError:
                        print(f"⚠️ 워크플로우 JSON 파싱 실패: {key}")
                        
                elif 'prompt' in key.lower():
                    try:
                        if isinstance(value, str):
                            prompt_data = json.loads(value)
                            workflow_info['prompt'] = prompt_data
                            print(f"✅ 프롬프트 데이터 파싱 성공")
                    except json.JSONDecodeError:
                        print(f"⚠️ 프롬프트 JSON 파싱 실패: {key}")
            
            return workflow_info
            
        except Exception as e:
            print(f"❌ ComfyUI 정보 추출 실패: {e}")
            return {}

    def create_safe_thumbnail_for_comfyui(self, image_object, target_size=128):
        """ComfyUI 이미지 전용 안전한 썸네일 생성"""
        try:
            print("🎨 ComfyUI 이미지 썸네일 생성 시작")
            
            # 1. ComfyUI 메타데이터 정리
            clean_image, comfyui_metadata = self.strip_comfyui_metadata(image_object)
            
            # 2. ComfyUI 워크플로우 정보 추출 (나중에 사용할 수 있도록)
            workflow_info = self.extract_comfyui_workflow_info(comfyui_metadata)
            
            # 3. 컬러 모드 정규화
            if clean_image.mode in ('RGBA', 'LA', 'P'):
                # 투명도 처리
                background = Image.new('RGB', clean_image.size, (255, 255, 255))
                if clean_image.mode == 'P':
                    clean_image = clean_image.convert('RGBA')
                
                if clean_image.mode in ('RGBA', 'LA'):
                    background.paste(clean_image, mask=clean_image.split()[-1])
                else:
                    background.paste(clean_image)
                clean_image = background
            elif clean_image.mode not in ('RGB', 'L'):
                clean_image = clean_image.convert('RGB')
            
            # 4. PIL에서 먼저 리사이즈 (더 효율적이고 안전)
            original_size = clean_image.size
            
            # 비율 유지하면서 리사이즈
            if original_size[0] > original_size[1]:
                new_width = target_size
                new_height = int((target_size * original_size[1]) / original_size[0])
            else:
                new_height = target_size
                new_width = int((target_size * original_size[0]) / original_size[1])
            
            # 고품질 리샘플링으로 리사이즈
            resized_image = clean_image.resize(
                (new_width, new_height), 
                Image.Resampling.LANCZOS
            )
            
            # 5. 완전히 깨끗한 PNG로 변환
            img_buffer = BytesIO()
            resized_image.save(
                img_buffer, 
                format='PNG', 
                optimize=True,
                # PNG 메타데이터 완전 제거
                pnginfo=None
            )
            img_buffer.seek(0)
            
            # 6. QPixmap으로 안전하게 로드
            pixmap = QPixmap()
            success = pixmap.loadFromData(img_buffer.getvalue(), 'PNG')
            
            if not success:
                print("❌ QPixmap 로드 실패")
                return None, workflow_info
            
            print(f"✅ ComfyUI 썸네일 생성 성공: {pixmap.size()}")
            
            # 7. 메모리 정리
            img_buffer.close()
            del clean_image, resized_image, img_buffer
            
            return pixmap, workflow_info
            
        except Exception as e:
            print(f"❌ ComfyUI 썸네일 생성 실패: {e}")
            import traceback
            traceback.print_exc()
            return None, {}

    def save_image_with_metadata(self, filename: str, image_bytes: bytes, info_text: str, as_webp=False):
        """
        [수정] 이미지 바이트를 EXIF 손실 없이 그대로 파일에 저장합니다.
        info_text 매개변수는 이제 사용되지 않지만 호환성을 위해 남겨둡니다.
        """
        try:
            if as_webp:
                # 이미지 객체로부터 WEBP로 저장
                img = Image.open(io.BytesIO(image_bytes))
                exif = img.info.get('exif', b'')
                img.save(filename, format='WEBP', quality=95, method=6, exif=exif)
                print(f"✅ WEBP(95%, exif) 저장 완료: {filename}")
            else:
                with open(filename, 'wb') as f:
                    f.write(image_bytes)
                print(f"✅ PNG 저장 완료: {filename}")
            return True
        except Exception as e:
            print(f"❌ 이미지 저장 실패: {e}")
            return False

    def toggle_history_panel(self):
        self.history_visible = not self.history_visible
        self.image_history_window.setVisible(self.history_visible)
        self.toggle_history_button.setText("📜 히스토리 숨기기" if self.history_visible else "📜 히스토리 보이기")
        self.toggle_history_button.setChecked(self.history_visible)

    def update_image(self, image: Image.Image):
        """
        WebP 등 다양한 형식을 지원하는 안전한 이미지 업데이트 (ComfyUI 메타데이터 처리 포함)
        """
        if not isinstance(image, Image.Image):
            self.main_image_label.setFullPixmap(None)
            return
            
        try:
            # 🆕 ComfyUI 이미지인지 확인
            has_comfyui_metadata = False
            if hasattr(image, 'info') and image.info:
                comfyui_keys = ['workflow', 'prompt', 'parameters', 'ComfyUI']
                has_comfyui_metadata = any(
                    any(comfyui_key.lower() in str(key).lower() for comfyui_key in comfyui_keys)
                    for key in image.info.keys()
                )
            
            # 🎨 [수정된 부분] ComfyUI 이미지를 감지하면 메타데이터를 제거하는 대신,
            # WebP와 동일하게 메모리 내에서 PNG로 재처리하여 완벽하게 정제합니다.
            # 이 방식은 Qt와 충돌을 일으키는 모든 비표준 데이터를 제거하는 가장 안전한 방법입니다.
            if (hasattr(image, 'format') and image.format == 'WEBP') or has_comfyui_metadata:
                if has_comfyui_metadata:
                    print("🎨 ComfyUI 이미지 감지됨 - 안전한 PNG 변환 처리 시작")
                else:
                    print("🔄 WebP 이미지를 PNG로 변환 중...")

                import io
                png_buffer = io.BytesIO()
                
                # RGBA 모드로 변환하여 투명도 정보 보존
                if image.mode != 'RGBA':
                    image = image.convert('RGBA')
                
                # PNG로 저장하며 모든 비표준 메타데이터를 제거
                image.save(png_buffer, format='PNG')
                png_buffer.seek(0)
                
                # 정제된 PNG 데이터로부터 새로운 PIL Image 객체 생성
                image = Image.open(png_buffer)
                
                # ImageQt.ImageQt를 통해 QImage로 변환
                q_image = ImageQt.ImageQt(image)
                png_buffer.close()
            else:
                # PNG나 기타 형식은 기존 방식 사용
                q_image = ImageQt.ImageQt(image)
            
            pixmap = QPixmap.fromImage(q_image)
            
            if pixmap.isNull():
                print("❌ QPixmap 변환 실패")
                self.main_image_label.setText("이미지를 표시할 수 없습니다.")
                return
                
            self.main_image_label.setFullPixmap(pixmap)
            print("✅ 이미지 업데이트 완료")
            
        except Exception as e:
            print(f"❌ 이미지 표시 오류: {e}")
            import traceback
            traceback.print_exc()
            self.main_image_label.setText("이미지를 표시할 수 없습니다.")

    def update_info(self, text: str):
        """정보 텍스트 업데이트"""
        self.info_textbox.setText(text)

    def clear_all(self):
        deleted = self.image_history_window.remove_current_item()
        # ↓ 삭제 후 남은 항목 있으면 갱신, 없으면 초기화
        if self.image_history_window.current_selected_widget:
            self.display_history_item(self.image_history_window.current_selected_widget.history_item)
        else:
            self.update_image(None)
            self.update_info("")

    def create_thumbnail_with_background(self, source_image: Image.Image) -> QPixmap:
        """
        WebP 등 다양한 형식을 지원하는 안전한 썸네일 생성 (ComfyUI 메타데이터 처리 포함)
        """
        try:
            # 🆕 ComfyUI 이미지인지 확인
            has_comfyui_metadata = False
            if hasattr(source_image, 'info') and source_image.info:
                comfyui_keys = ['workflow', 'prompt', 'parameters', 'ComfyUI']
                has_comfyui_metadata = any(
                    any(comfyui_key.lower() in str(key).lower() for comfyui_key in comfyui_keys)
                    for key in source_image.info.keys()
                )
            
            # ComfyUI 이미지의 경우 전용 함수 사용
            if has_comfyui_metadata:
                print("🎨 ComfyUI 썸네일 생성 모드")
                pixmap, workflow_info = self.create_safe_thumbnail_for_comfyui(source_image, 128)
                if pixmap and not pixmap.isNull():
                    # 128x128 배경에 중앙 정렬
                    canvas = QPixmap(128, 128)
                    canvas.fill(QColor("black"))
                    
                    x = (128 - pixmap.width()) // 2
                    y = (128 - pixmap.height()) // 2
                    
                    painter = QPainter(canvas)
                    painter.drawPixmap(x, y, pixmap)
                    painter.end()
                    
                    return canvas
            
            # 기존 로직 (NAI, WebUI 등)
            # WebP 형식인 경우 PNG로 변환
            if hasattr(source_image, 'format') and source_image.format == 'WEBP':
                print("🔄 WebP 이미지를 PNG로 변환 중...")
                # 메모리 내에서 PNG로 변환
                import io
                png_buffer = io.BytesIO()
                # RGBA 모드로 변환하여 투명도 처리
                if source_image.mode != 'RGBA':
                    source_image = source_image.convert('RGBA')
                source_image.save(png_buffer, format='PNG')
                png_buffer.seek(0)
                
                # PNG로 변환된 이미지 다시 열기
                converted_image = Image.open(png_buffer)
                source_pixmap = QPixmap.fromImage(ImageQt.ImageQt(converted_image))
                png_buffer.close()
            else:
                # PNG나 기타 형식은 기존 방식 사용
                source_pixmap = QPixmap.fromImage(ImageQt.ImageQt(source_image))
            
            # 썸네일이 제대로 생성되었는지 확인
            if source_pixmap.isNull():
                print("❌ 썸네일 생성 실패: QPixmap이 null입니다.")
                # 기본 플레이스홀더 이미지 생성
                placeholder = QPixmap(128, 128)
                placeholder.fill(QColor("gray"))
                return placeholder
            
            # 1. 원본 비율을 유지하며 가장 긴 쪽이 128px이 되도록 리사이즈
            scaled_pixmap = source_pixmap.scaled(
                QSize(128, 128),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            
            # 2. 128x128 크기의 검은색 배경 QPixmap 생성
            canvas = QPixmap(128, 128)
            canvas.fill(QColor("black"))
            
            # 3. 배경의 중앙에 리사이즈된 이미지를 그릴 위치 계산
            x = (128 - scaled_pixmap.width()) // 2
            y = (128 - scaled_pixmap.height()) // 2
            
            # 4. QPainter를 사용하여 배경 위에 이미지 그리기
            painter = QPainter(canvas)
            painter.drawPixmap(x, y, scaled_pixmap)
            painter.end()
            
            print("✅ 썸네일 생성 완료")
            return canvas
            
        except Exception as e:
            print(f"❌ 썸네일 생성 실패: {e}")
            import traceback
            traceback.print_exc()
            # 기본 플레이스홀더 이미지 생성
            placeholder = QPixmap(128, 128)
            placeholder.fill(QColor("gray"))
            return placeholder

    def add_to_history(self, image: Image.Image, raw_bytes: bytes, info: str, source_row: pd.Series):
        if not isinstance(image, Image.Image):
            return

        # ⬇️ [핵심 수정] 외부에서 받은 info 대신, 이미지에서 직접 정보를 추출합니다.
        info_text = self.extract_info_from_image(image, info)
        # ⬆️ 이 한 줄로 모든 정보 추출 로직이 처리됩니다.

        # ComfyUI 워크플로우 정보는 별도로 관리 (컨텍스트 메뉴용)
        comfyui_workflow = {}
        if 'prompt' in image.info:
            try:
                workflow_data = json.loads(image.info['prompt'])
                comfyui_workflow['workflow'] = workflow_data
            except Exception:
                pass
        
        # 썸네일 생성
        thumbnail_pixmap = self.create_thumbnail_with_background(image)
        
        # 자동 저장 로직
        filepath = None
        is_webp = self.save_as_webp_checkbox.isChecked()
        if self.auto_save_checkbox.isChecked():
            save_path = self.app_context.session_save_path
            suffix = "webp" if is_webp else "png"
            filename = f"{self.save_counter:05d}.{suffix}"
            filepath = save_path / filename
            # 저장 함수에는 이제 info_text를 새로 생성한 것으로 전달
            self.save_image_with_metadata(str(filepath), raw_bytes, info_text, as_webp=is_webp)
            self.save_counter += 1

        history_item = HistoryItem(
            image=image, 
            thumbnail=thumbnail_pixmap,
            raw_bytes=raw_bytes, 
            info_text=info_text,  # 새로 추출한 텍스트로 저장
            source_row=source_row, 
            filepath=str(filepath) if filepath else None,
            comfyui_workflow=comfyui_workflow
        )

        if self.image_history_window:
            self.image_history_window.add_history_item(history_item)

    def display_history_item(self, item: HistoryItem):
        """[수정] 선택된 히스토리 아이템의 내용을 메인 뷰어에 표시"""
        self.current_history_item = item # 현재 아이템 추적
        self.update_image(item.image)
        self.update_info(item.info_text) # 저장된 생성 정보로 업데이트

    def save_current_image(self):
        is_webp = self.save_as_webp_checkbox.isChecked()
        """[수정] '이미지 저장' 버튼 클릭 시, 대화상자 없이 바로 저장"""
        if not hasattr(self, 'current_history_item') or not self.current_history_item:
            # status_bar 접근 방법 수정
            if hasattr(self.app_context, 'main_window') and hasattr(self.app_context.main_window, 'status_bar'):
                self.app_context.main_window.status_bar.showMessage("⚠️ 저장할 이미지를 목록에서 선택해주세요.", 3000)
            return

        item = self.current_history_item
        if not item.raw_bytes:
            if hasattr(self.app_context, 'main_window') and hasattr(self.app_context.main_window, 'status_bar'):
                self.app_context.main_window.status_bar.showMessage("⚠️ 저장할 이미지의 원본 데이터가 없습니다.", 3000)
            return
        
        # 1. AppContext에서 세션 저장 경로를 가져옴
        save_path = self.app_context.session_save_path
        
        # 2. 새로운 파일명 생성 (자동 저장과 카운터 공유)
        suffix = "webp" if is_webp else "png"
        filename = f"{self.save_counter:05d}.{suffix}"
        file_path = save_path / filename
        
        # 3. 메타데이터와 함께 저장
        self.save_image_with_metadata(str(file_path), item.raw_bytes, item.info_text, as_webp=is_webp)
        
        # 4. 카운터 증가
        self.save_counter += 1
        
        # 5. 상태 메시지
        if hasattr(self.app_context, 'main_window') and hasattr(self.app_context.main_window, 'status_bar'):
            self.app_context.main_window.status_bar.showMessage(f"✅ 이미지 저장 완료: {filename}", 3000)
    
    def extract_info_from_image(self, image: Image.Image, _info):
        """
        [신규] PIL 이미지 객체에서 다양한 소스(ComfyUI, WebUI 등)의 생성 정보를 추출합니다.
        가장 구체적인 형식부터 확인하여 정확도를 높입니다.
        """
        if not hasattr(image, 'info'):
            return "이미지에 메타데이터가 없습니다."

        info = image.info
        source_info = ""

        # 1. ComfyUI 확인 ('prompt' 키, JSON 형식)
        if 'prompt' in info and isinstance(info.get('prompt'), str):
            try:
                # ComfyUI 워크플로우는 JSON 형식이므로 파싱 시도
                prompt_data = json.loads(info['prompt'])
                if isinstance(prompt_data, dict): # 유효한 JSON 객체인지 확인
                    source_info = "[ComfyUI] "
                    # 주요 정보 추출 (예시)
                    positive_prompt = next((node['inputs']['text'] for node in prompt_data.values() if node.get('class_type') == 'CLIPTextEncode'), "N/A")
                    negative_prompt = "N/A" # 필요시 네거티브 노드 파싱 로직 추가
                    ksampler_node = next((node['inputs'] for node in prompt_data.values() if node.get('class_type') == 'KSampler'), None)

                    source_info += f"Prompt: {positive_prompt}\n"
                    if ksampler_node:
                        source_info += f"Steps: {ksampler_node.get('steps')}, Sampler: {ksampler_node.get('sampler_name')}, CFG: {ksampler_node.get('cfg')}, Seed: {ksampler_node.get('seed')}"
                    return source_info
            except (json.JSONDecodeError, TypeError):
                # JSON이 아니면 다음 단계로
                pass

        # 2. A1111 WebUI 확인 ('parameters' 키, 텍스트 형식)
        if 'parameters' in info and isinstance(info.get('parameters'), str):
            return f"[WebUI] {info['parameters']}"

        # 3. Novel AI 확인 ('Comment' 키, 텍스트 형식)
        if 'Comment' in info and isinstance(info.get('Comment'), str):
             return f"[Novel AI] {info['Comment']}"

        # 4. 표준 EXIF 확인 (위에서 정보를 못 찾았을 경우의 최후 수단)
        try:
            return f"Source: EXIF (UserComment) {_info}"
        except Exception:
            pass

        return "추출할 수 있는 생성 정보가 없습니다."
    
    def open_folder(self):
        import sys, subprocess
        folder = str(self.app_context.session_save_path)
        if sys.platform.startswith('darwin'):
            subprocess.run(['open', folder])
        elif os.name == 'nt':
            os.startfile(folder)
        elif os.name == 'posix':
            subprocess.run(['xdg-open', folder])

    def copy_image_to_clipboard(self, fmt='PNG'):
        from PyQt6.QtWidgets import QApplication
        import io
        pil_img = self.current_history_item.image
        buf = io.BytesIO()
        if fmt == 'PNG':
            pil_img.save(buf, format='PNG')
        else:
            pil_img.save(buf, format='WEBP', quality=90, method=6)
        buf.seek(0)
        qimg = QPixmap()
        qimg.loadFromData(buf.getvalue())
        QApplication.clipboard().setPixmap(qimg)
        print(f"✅ 이미지가 클립보드에 복사되었습니다. ({fmt})")
