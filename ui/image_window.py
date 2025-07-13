import os
from dataclasses import dataclass, field
from typing import Dict, Any
import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTextEdit, QSplitter, QPushButton,
    QHBoxLayout, QCheckBox, QScrollArea, QMenu
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
            return

        widget_to_remove = self.current_selected_widget
        
        # 리스트와 레이아웃에서 위젯 제거
        self.history_widgets.remove(widget_to_remove)
        self.history_layout.removeWidget(widget_to_remove)
        widget_to_remove.deleteLater()
        
        self.current_selected_widget = None
        return True # 삭제 성공 여부 반환

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
        #control_layout.addWidget(self.toggle_history_button) # 버튼 추가, Splitter랑 기능 겹쳐서 현재 제외
        control_layout.addStretch()
        control_layout.addWidget(clear_button)
        control_layout.addWidget(self.save_button)
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
        
        load_action = QAction("프롬프트 불러오기", self)
        load_action.triggered.connect(self._load_current_prompt)
        menu.addAction(load_action)
        
        reroll_action = QAction("프롬프트 다시개봉", self)
        if self.current_history_item.source_row is None or self.current_history_item.source_row.empty:
            reroll_action.setEnabled(False)
        reroll_action.triggered.connect(self._reroll_current_prompt)
        menu.addAction(reroll_action)
        
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

    def save_image_with_metadata(self, filename: str, image_bytes: bytes, info_text: str):
        """이미지 바이트에 EXIF 메타데이터를 추가하여 파일로 저장합니다."""
        try:
            # 1. UserComment 형식으로 메타데이터 준비
            exif_dict = {"Exif": {piexif.ExifIFD.UserComment: piexif.helper.UserComment.dump(info_text, encoding="unicode")}}
            exif_bytes = piexif.dump(exif_dict)
            
            # 2. PIL Image 객체로 원본 바이트 열기
            img = Image.open(io.BytesIO(image_bytes))
            
            # 3. EXIF 데이터를 포함하여 저장
            img.save(filename, "PNG", exif=exif_bytes)
            print(f"✅ EXIF 포함 이미지 저장 성공: {filename}")
            return True
        except Exception as e:
            print(f"❌ EXIF 포함 이미지 저장 실패: {e}")
            # 실패 시 메타데이터 없이 저장 (선택적)
            with open(filename, 'wb') as f:
                f.write(image_bytes)
            return False

    def toggle_history_panel(self):
        self.history_visible = not self.history_visible
        self.image_history_window.setVisible(self.history_visible)
        self.toggle_history_button.setText("📜 히스토리 숨기기" if self.history_visible else "📜 히스토리 보이기")
        self.toggle_history_button.setChecked(self.history_visible)

    def update_image(self, image: Image.Image):
        """
        [수정] 이 메서드는 ImageWindow의 것입니다.
        외부의 요청을 받아, 자식 위젯인 self.main_image_label에 일을 시킵니다.
        """
        if not isinstance(image, Image.Image):
            self.main_image_label.setFullPixmap(None)
            return
            
        try:
            q_image = ImageQt.ImageQt(image)
            pixmap = QPixmap.fromImage(q_image)
            self.main_image_label.setFullPixmap(pixmap)
        except Exception as e:
            print(f"❌ 이미지 표시 오류: {e}")
            self.main_image_label.setText("이미지를 표시할 수 없습니다.")

    def update_info(self, text: str):
        """정보 텍스트 업데이트"""
        self.info_textbox.setText(text)

    def clear_all(self):
        # [수정] 히스토리에서 먼저 삭제 시도
        deleted = self.image_history_window.remove_current_item()
        # 삭제가 성공했거나, 원래 선택된 항목이 없었을 경우에만 메인 뷰 클리어
        if deleted or not self.image_history_window.current_selected_widget:
            self.update_image(None)
            self.update_info("")

    # [신규] 썸네일 생성 로직
    def create_thumbnail_with_background(self, source_image: Image.Image) -> QPixmap:
        # PIL 이미지를 QPixmap으로 변환
        source_pixmap = QPixmap.fromImage(ImageQt.ImageQt(source_image))
        
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
        
        return canvas

    def add_to_history(self, image: Image.Image, raw_bytes: bytes, info: str, source_row: pd.Series):
        if not isinstance(image, Image.Image):
            return

        # [수정] 새로운 썸네일 생성 함수 호출
        thumbnail_pixmap = self.create_thumbnail_with_background(image)
        
        filepath = None
        if self.auto_save_checkbox.isChecked():
            save_path = self.app_context.session_save_path
            filename = f"{self.save_counter:05d}.png"
            filepath = save_path / filename
            self.save_image_with_metadata(str(filepath), raw_bytes, info)
            self.save_counter += 1

        history_item = HistoryItem(
            image=image, thumbnail=thumbnail_pixmap,
            raw_bytes=raw_bytes, info_text=info, # raw_bytes와 info_text 저장
            source_row=source_row, filepath=str(filepath) if filepath else None
        )

        if self.image_history_window:
            self.image_history_window.add_history_item(history_item)

    def display_history_item(self, item: HistoryItem):
        """[수정] 선택된 히스토리 아이템의 내용을 메인 뷰어에 표시"""
        self.current_history_item = item # 현재 아이템 추적
        self.update_image(item.image)
        self.update_info(item.info_text) # 저장된 생성 정보로 업데이트

    def save_current_image(self):
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
        filename = f"{self.save_counter:05d}.png"
        file_path = save_path / filename
        
        # 3. 메타데이터와 함께 저장
        self.save_image_with_metadata(str(file_path), item.raw_bytes, item.info_text)
        
        # 4. 카운터 증가
        self.save_counter += 1
        
        # 5. 상태 메시지
        if hasattr(self.app_context, 'main_window') and hasattr(self.app_context.main_window, 'status_bar'):
            self.app_context.main_window.status_bar.showMessage(f"✅ 이미지 저장 완료: {filename}", 3000)
