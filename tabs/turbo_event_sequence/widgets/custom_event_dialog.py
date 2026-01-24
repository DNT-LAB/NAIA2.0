"""
Custom Event Dialog

사용자가 직접 이벤트 시퀀스를 생성할 수 있는 다이얼로그
- Parent 프롬프트 + 2~6개의 Child 프롬프트 입력
- 각 이벤트별 Rating 설정 + 테스트 버튼
- 썸네일 클릭으로 미리보기 영역에 이미지 표시
- 그리드 보기 버튼으로 전체 시퀀스 확인
- SequenceGenerationWorker를 통한 이미지 생성
- NAIA_event_dataset_personal.parquet에 저장
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QFrame,
    QLabel, QTextEdit, QPushButton,
    QScrollArea, QMessageBox, QComboBox, QSplitter
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QTextCharFormat, QColor, QSyntaxHighlighter, QTextDocument
from pathlib import Path
from datetime import datetime
import pandas as pd
from PIL import Image
from typing import Optional, TYPE_CHECKING

from ui.theme import DARK_STYLES, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

from .image_viewer_widget import ImageViewerWidget

if TYPE_CHECKING:
    from core.context import AppContext


class TagHighlighter(QSyntaxHighlighter):
    """캐릭터 특징/의류 태그 하이라이터"""

    def __init__(self, document: QTextDocument, characteristic_tags: set, clothes_tags: set):
        super().__init__(document)
        self.characteristic_tags = characteristic_tags
        self.clothes_tags = clothes_tags

        # 연한 녹색 하이라이팅
        self.highlight_format = QTextCharFormat()
        self.highlight_format.setForeground(QColor("#90EE90"))  # 연한 녹색

    def highlightBlock(self, text: str):
        """텍스트 블록 하이라이팅"""
        # 쉼표로 분리된 태그들 처리
        tags = [t.strip() for t in text.split(',')]
        current_pos = 0

        for tag in tags:
            if not tag:
                continue

            # 태그 위치 찾기
            tag_start = text.find(tag, current_pos)
            if tag_start == -1:
                continue

            # 특징/의류 태그면 하이라이팅
            if tag in self.characteristic_tags or tag in self.clothes_tags:
                self.setFormat(tag_start, len(tag), self.highlight_format)

            current_pos = tag_start + len(tag)


class PromptInputWidget(QFrame):
    """개별 프롬프트 입력 위젯 (썸네일 포함)"""

    removed = pyqtSignal(object)  # self를 전달
    test_requested = pyqtSignal(int, str, str)  # index, prompt, rating
    thumbnail_clicked = pyqtSignal(int, object)  # 🆕 index, image
    prompt_changed = pyqtSignal(int, str)  # 🆕 index, prompt (diff 계산용)
    copy_parent_requested = pyqtSignal(int)  # 🆕 index (Parent 복사 요청)
    copy_prev_requested = pyqtSignal(int)  # 🆕 index (Prev 복사 요청)

    # 썸네일 크기
    THUMB_SIZE = 80

    def __init__(self, index: int, is_parent: bool = False, parent=None,
                 characteristic_tags: set = None, clothes_tags: set = None):
        super().__init__(parent)
        self.index = index
        self.is_parent = is_parent
        self._image: Optional[Image.Image] = None
        self._selected = False  # 🆕 선택 상태
        self.characteristic_tags = characteristic_tags or set()
        self.clothes_tags = clothes_tags or set()
        self.highlighter = None  # 하이라이터 참조
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(6)}px;
            }}
        """)

        main_layout = QVBoxLayout(self)  # 🆕 수직 레이아웃으로 변경 (diff 라벨 추가)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(6)

        # 메인 콘텐츠 (썸네일 + 프롬프트 입력)
        content_layout = QHBoxLayout()
        content_layout.setSpacing(10)

        # 좌측: 썸네일 영역 (클릭 가능)
        self.thumb_frame = QFrame()
        self.thumb_frame.setFixedSize(get_scaled_size(self.THUMB_SIZE + 10), get_scaled_size(self.THUMB_SIZE + 30))
        self._update_thumbnail_style()  # 초기 스타일 적용

        thumb_layout = QVBoxLayout(self.thumb_frame)
        thumb_layout.setContentsMargins(4, 4, 4, 4)
        thumb_layout.setSpacing(2)

        # 썸네일 라벨
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(get_scaled_size(self.THUMB_SIZE), get_scaled_size(self.THUMB_SIZE))
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet(f"""
            background-color: {DARK_COLORS['bg_tertiary']};
            border-radius: {get_scaled_size(4)}px;
            color: {DARK_COLORS['text_secondary']};
            font-size: {get_scaled_font_size(20)}px;
        """)
        self.thumb_label.setText("⏳")
        thumb_layout.addWidget(self.thumb_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # 인덱스 라벨
        idx_text = "Parent" if self.is_parent else f"#{self.index}"
        self.idx_label = QLabel(idx_text)
        self.idx_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.idx_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(14)}px;
            color: {DARK_COLORS['text_secondary']};
            background-color: transparent;
            border: none;
        """)
        thumb_layout.addWidget(self.idx_label)

        # 🆕 썸네일 프레임 클릭 가능하게 설정
        self.thumb_frame.mousePressEvent = self._on_thumbnail_clicked

        content_layout.addWidget(self.thumb_frame)

        # 우측: 프롬프트 입력 영역
        right_layout = QVBoxLayout()
        right_layout.setSpacing(8)

        # 헤더 (라벨 + Rating + 테스트 버튼 + 삭제 버튼)
        header = QHBoxLayout()
        header.setSpacing(10)

        if self.is_parent:
            label_text = "🎬 Parent (시작 장면)"
            label_color = DARK_COLORS['accent_blue']
        else:
            label_text = f"📍 Child {self.index} (장면 {self.index + 1})"
            label_color = DARK_COLORS['text_secondary']

        self.label = QLabel(label_text)
        self.label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(17)}px;
            font-weight: bold;
            color: {label_color};
            border: none;
        """)
        header.addWidget(self.label)

        header.addStretch()

        # 🆕 Child만 복사 버튼 표시
        if not self.is_parent:
            # Child 1: Parent 복사만
            # Child 2+: Prev 복사 + Parent 복사
            if self.index > 1:
                # Prev 복사 버튼
                prev_copy_btn = QPushButton("Prev 복사")
                prev_copy_btn.setFixedHeight(get_scaled_size(28))
                prev_copy_btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {DARK_COLORS['bg_tertiary']};
                        color: {DARK_COLORS['text_secondary']};
                        border: 1px solid {DARK_COLORS['border']};
                        border-radius: {get_scaled_size(4)}px;
                        padding: {get_scaled_size(3)}px {get_scaled_size(8)}px;
                        font-size: {get_scaled_font_size(13)}px;
                    }}
                    QPushButton:hover {{
                        background-color: {DARK_COLORS['accent_blue']};
                        color: white;
                    }}
                """)
                prev_copy_btn.clicked.connect(lambda: self.copy_prev_requested.emit(self.index))
                header.addWidget(prev_copy_btn)

            # Parent 복사 버튼
            parent_copy_btn = QPushButton("Parent 복사")
            parent_copy_btn.setFixedHeight(get_scaled_size(28))
            parent_copy_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {DARK_COLORS['bg_tertiary']};
                    color: {DARK_COLORS['text_secondary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: {get_scaled_size(4)}px;
                    padding: {get_scaled_size(3)}px {get_scaled_size(8)}px;
                    font-size: {get_scaled_font_size(13)}px;
                }}
                QPushButton:hover {{
                    background-color: {DARK_COLORS['accent_blue']};
                    color: white;
                }}
            """)
            parent_copy_btn.clicked.connect(lambda: self.copy_parent_requested.emit(self.index))
            header.addWidget(parent_copy_btn)

        # Rating 콤보박스
        rating_label = QLabel("Rating:")
        rating_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(16)}px;
            color: {DARK_COLORS['text_secondary']};
            border: none;
        """)
        header.addWidget(rating_label)

        self.rating_combo = QComboBox()
        self.rating_combo.addItems(['e', 'q', 's', 'g'])
        self.rating_combo.setCurrentText('e')  # 기본값 e
        self.rating_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: white;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(5)}px {get_scaled_size(10)}px;
                font-size: {get_scaled_font_size(16)}px;
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid white;
                margin-right: 5px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: white;
                selection-background-color: {DARK_COLORS['accent_blue']};
                border: 1px solid {DARK_COLORS['border']};
            }}
        """)
        self.rating_combo.setFixedWidth(get_scaled_size(60))
        self.rating_combo.setFixedHeight(get_scaled_size(36))
        header.addWidget(self.rating_combo)

        # 테스트 버튼
        self.test_btn = QPushButton("테스트")
        self.test_btn.setFixedWidth(get_scaled_size(75))
        self.test_btn.setFixedHeight(get_scaled_size(36))
        self.test_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(5)}px {get_scaled_size(12)}px;
                font-size: {get_scaled_font_size(16)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QPushButton:disabled {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_secondary']};
            }}
        """)
        self.test_btn.clicked.connect(self._on_test_clicked)
        header.addWidget(self.test_btn)

        # Child만 삭제 버튼 표시
        if not self.is_parent:
            remove_btn = QPushButton("✕")
            remove_btn.setFixedSize(get_scaled_size(36), get_scaled_size(36))
            remove_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {DARK_COLORS['text_secondary']};
                    border: none;
                    font-size: {get_scaled_font_size(18)}px;
                }}
                QPushButton:hover {{
                    color: {DARK_COLORS['error']};
                }}
            """)
            remove_btn.clicked.connect(lambda: self.removed.emit(self))
            header.addWidget(remove_btn)

        right_layout.addLayout(header)

        # 프롬프트 입력 (🆕 폰트 크기 2px 증가, 높이 25% 증가)
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText(
            "태그를 쉼표로 구분하여 입력 (예: 1girl, standing, smile, school uniform)"
        )
        self.prompt_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(8)}px;
                font-size: {get_scaled_font_size(18)}px;
            }}
            QTextEdit:focus {{
                border-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        self.prompt_edit.setMinimumHeight(get_scaled_size(88))  # 70 * 1.25
        self.prompt_edit.setMaximumHeight(get_scaled_size(125))  # 100 * 1.25
        self.prompt_edit.textChanged.connect(self._on_prompt_changed)

        # 🆕 하이라이터 적용
        if self.characteristic_tags or self.clothes_tags:
            self.highlighter = TagHighlighter(
                self.prompt_edit.document(),
                self.characteristic_tags,
                self.clothes_tags
            )

        right_layout.addWidget(self.prompt_edit)

        content_layout.addLayout(right_layout, stretch=1)
        main_layout.addLayout(content_layout)

        # 🆕 Tag diff 라벨 (Child만 표시)
        if not self.is_parent:
            diff_container = QFrame()
            diff_container.setStyleSheet(f"""
                QFrame {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    border: none;
                    border-radius: {get_scaled_size(4)}px;
                    padding: {get_scaled_size(4)}px;
                }}
            """)
            diff_layout = QVBoxLayout(diff_container)
            diff_layout.setContentsMargins(8, 4, 8, 4)
            diff_layout.setSpacing(2)

            # Prev (삭제된 태그) - 주황색
            self.prev_diff_label = QLabel("")
            self.prev_diff_label.setWordWrap(True)
            self.prev_diff_label.setStyleSheet(f"""
                font-size: {get_scaled_font_size(13)}px;
                color: #FF8C00;
            """)
            self.prev_diff_label.hide()
            diff_layout.addWidget(self.prev_diff_label)

            # Parent (삭제된 태그) - 연주황색
            self.parent_diff_label = QLabel("")
            self.parent_diff_label.setWordWrap(True)
            self.parent_diff_label.setStyleSheet(f"""
                font-size: {get_scaled_font_size(13)}px;
                color: #FFB366;
            """)
            self.parent_diff_label.hide()
            diff_layout.addWidget(self.parent_diff_label)

            main_layout.addWidget(diff_container)
            self.diff_container = diff_container
            self.diff_container.hide()  # 초기에는 숨김

    def _on_thumbnail_clicked(self, event):
        """🆕 썸네일 클릭 이벤트"""
        if event.button() == Qt.MouseButton.LeftButton:
            if self._image is not None:
                self.thumbnail_clicked.emit(self.index, self._image)

    def _on_prompt_changed(self):
        """🆕 프롬프트 변경 시 diff 계산 시그널 발행"""
        if not self.is_parent:
            self.prompt_changed.emit(self.index, self.get_prompt())

    def _on_test_clicked(self):
        """테스트 버튼 클릭"""
        prompt = self.get_prompt()
        if prompt:
            self.test_requested.emit(self.index, prompt, self.get_rating())
        else:
            QMessageBox.warning(self, "입력 오류", "프롬프트를 입력하세요.")

    def update_tag_diff(self, prev_removed: set, parent_removed: set):
        """🆕 태그 diff 업데이트 (Prev, Parent)"""
        if self.is_parent:
            return  # Parent는 diff 표시 안 함

        # Child 1은 Prev가 없음 (Parent만 비교)
        show_prev = (self.index > 1) and len(prev_removed) > 0
        show_parent = len(parent_removed) > 0

        if show_prev:
            prev_str = ", ".join(list(prev_removed)[:8])
            if len(prev_removed) > 8:
                prev_str += f" (+{len(prev_removed) - 8})"
            count = len(prev_removed)
            self.prev_diff_label.setText(f"[Prev] (-{count}) {prev_str}")
            self.prev_diff_label.show()
        else:
            self.prev_diff_label.hide()

        if show_parent:
            parent_str = ", ".join(list(parent_removed)[:8])
            if len(parent_removed) > 8:
                parent_str += f" (+{len(parent_removed) - 8})"
            count = len(parent_removed)
            self.parent_diff_label.setText(f"[Parent] (-{count}) {parent_str}")
            self.parent_diff_label.show()
        else:
            self.parent_diff_label.hide()

        # diff가 있으면 컨테이너 표시
        if show_prev or show_parent:
            self.diff_container.show()
        else:
            self.diff_container.hide()

    def set_selected(self, selected: bool):
        """🆕 선택 상태 설정"""
        self._selected = selected
        self._update_thumbnail_style()

    def _update_thumbnail_style(self):
        """🆕 썸네일 스타일 업데이트 (선택 상태 반영)"""
        border_color = DARK_COLORS['accent_blue'] if self._selected else DARK_COLORS['border']
        border_width = 2 if self._selected else 1

        # 이미지가 있으면 커서 변경
        cursor_style = "cursor: pointer;" if self._image is not None else ""

        self.thumb_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: {border_width}px solid {border_color};
                border-radius: {get_scaled_size(4)}px;
                {cursor_style}
            }}
        """)

    def get_prompt(self) -> str:
        """프롬프트 텍스트 반환"""
        return self.prompt_edit.toPlainText().strip()

    def set_prompt(self, text: str):
        """프롬프트 텍스트 설정"""
        self.prompt_edit.setPlainText(text)

    def get_rating(self) -> str:
        """Rating 반환"""
        return self.rating_combo.currentText()

    def set_rating(self, rating: str):
        """Rating 설정"""
        self.rating_combo.setCurrentText(rating)

    def update_index(self, new_index: int):
        """인덱스 업데이트 (삭제 후 재정렬용)"""
        self.index = new_index
        self.label.setText(f"📍 Child {new_index} (장면 {new_index + 1})")
        self.idx_label.setText(f"#{new_index}")

    def set_image(self, image: Image.Image):
        """썸네일 이미지 설정"""
        self._image = image
        try:
            import io
            from PIL.ImageQt import ImageQt
            from PyQt6.QtGui import QPixmap

            # 썸네일 생성
            thumb = image.copy()
            thumb.thumbnail((get_scaled_size(self.THUMB_SIZE - 4), get_scaled_size(self.THUMB_SIZE - 4)), Image.Resampling.LANCZOS)

            # PNG 버퍼로 저장 후 다시 열기
            png_buffer = io.BytesIO()
            thumb.save(png_buffer, format='PNG')
            png_buffer.seek(0)
            clean_thumb = Image.open(png_buffer)
            clean_thumb.load()

            if clean_thumb.mode != 'RGBA':
                clean_thumb = clean_thumb.convert('RGBA')

            qimage = ImageQt(clean_thumb)
            pixmap = QPixmap.fromImage(qimage)
            self.thumb_label.setPixmap(pixmap)
            self.thumb_label.setStyleSheet(f"""
                background-color: {DARK_COLORS['bg_tertiary']};
                border-radius: {get_scaled_size(4)}px;
            """)
            png_buffer.close()

            # 🆕 스타일 업데이트 (커서 변경)
            self._update_thumbnail_style()
        except Exception as e:
            print(f"[PromptInputWidget] 썸네일 설정 오류: {e}")

    def get_image(self) -> Optional[Image.Image]:
        """이미지 반환"""
        return self._image

    def has_image(self) -> bool:
        """이미지가 있는지 확인"""
        return self._image is not None

    def clear_image(self):
        """이미지 클리어"""
        self._image = None
        self.thumb_label.clear()
        self.thumb_label.setText("⏳")
        self.thumb_label.setStyleSheet(f"""
            background-color: {DARK_COLORS['bg_tertiary']};
            border-radius: {get_scaled_size(4)}px;
            color: {DARK_COLORS['text_secondary']};
            font-size: {get_scaled_font_size(20)}px;
        """)
        self._update_thumbnail_style()

    def set_test_enabled(self, enabled: bool):
        """테스트 버튼 활성화/비활성화"""
        self.test_btn.setEnabled(enabled)


class CustomEventDialog(QDialog):
    """커스텀 이벤트 생성 다이얼로그"""

    # 시그널: 이벤트 생성 완료 시 parent_id 전달
    event_created = pyqtSignal(int)

    def __init__(self, data_dir: Path, app_context: 'AppContext' = None, parent=None):
        super().__init__(parent)
        self.data_dir = Path(data_dir)
        self.app_context = app_context
        self.child_widgets: list[PromptInputWidget] = []

        # 생성 워커
        self._generation_worker = None
        self._is_generating = False

        # 🆕 선택 상태 관리
        self._selected_widget_index: Optional[int] = None

        # 🆕 특징/의류 태그 로드
        self.characteristic_tags = set()
        self.clothes_tags = set()
        if app_context and hasattr(app_context, 'filter_data_manager'):
            filter_manager = app_context.filter_data_manager
            if hasattr(filter_manager, 'characteristic_list'):
                self.characteristic_tags = set(filter_manager.characteristic_list)
            if hasattr(filter_manager, 'clothes_list'):
                self.clothes_tags = set(filter_manager.clothes_list)
            print(f"[CustomEventDialog] 로드된 태그: 특징 {len(self.characteristic_tags)}개, 의류 {len(self.clothes_tags)}개")

        self._init_ui()
        self._apply_theme()
        self._update_child_test_buttons()

    def _init_ui(self):
        self.setWindowTitle("➕ Custom Event 생성")
        self.setMinimumSize(900, 700)
        self.resize(1000, 800)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 헤더
        header = self._create_header()
        layout.addWidget(header)

        # 메인 영역 (스플리터)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 좌측: 프롬프트 입력 영역
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        # 프롬프트 입력 영역 (스크롤 가능)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: {DARK_COLORS['bg_tertiary']};
                border-radius: {get_scaled_size(6)}px;
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {DARK_COLORS['bg_tertiary']};
            }}
        """)

        self.prompts_container = QWidget()
        self.prompts_container.setStyleSheet(f"""
            QWidget {{
                background-color: {DARK_COLORS['bg_tertiary']};
            }}
        """)
        self.prompts_layout = QVBoxLayout(self.prompts_container)
        self.prompts_layout.setContentsMargins(8, 8, 8, 8)
        self.prompts_layout.setSpacing(10)

        # Parent 프롬프트 (항상 존재, 맨 위에)
        self.parent_widget = PromptInputWidget(
            0, is_parent=True,
            characteristic_tags=self.characteristic_tags,
            clothes_tags=self.clothes_tags
        )
        self.parent_widget.test_requested.connect(self._on_test_requested)
        self.parent_widget.thumbnail_clicked.connect(self._on_thumbnail_clicked)  # 🆕
        self.parent_widget.prompt_changed.connect(self._on_prompt_changed)  # 🆕 (Parent 변경 시 모든 Child diff 재계산)

        # 🆕 Parent 기본 프롬프트 설정
        default_parent_prompt = (
            "1girl, small breasts, brown hair, green eyes, hair between eyes, hair intakes, low twintails, "
            "sidelocks, straight hair, very long hair, maid headdress, maid apron, black thighhighs, bow, "
            "collared shirt, dress shirt, frilled apron, wrist cuffs, green bow, hair ribbon, green ribbon"
        )
        self.parent_widget.set_prompt(default_parent_prompt)

        self.prompts_layout.addWidget(self.parent_widget)

        # 기본 Child 2개 추가
        self._add_child_widget()
        self._add_child_widget()

        # 하단 여백용 stretch
        self.prompts_layout.addStretch()

        scroll_area.setWidget(self.prompts_container)
        left_layout.addWidget(scroll_area, stretch=1)

        # Child 추가 버튼
        add_child_btn = QPushButton("➕ Child 장면 추가")
        add_child_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        add_child_btn.clicked.connect(self._add_child_widget)
        left_layout.addWidget(add_child_btn)

        splitter.addWidget(left_widget)

        # 우측: 이미지 뷰어
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        viewer_label = QLabel("🖼️ 미리보기")
        viewer_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(14)}px;
            font-weight: bold;
            color: {DARK_COLORS['text_primary']};
        """)
        right_layout.addWidget(viewer_label)

        self.image_viewer = ImageViewerWidget()
        self.image_viewer.set_placeholder_text("테스트 버튼을 눌러\n이미지를 생성하세요\n\n썸네일 클릭으로\n미리보기 변경")
        self.image_viewer.setMinimumSize(get_scaled_size(300), get_scaled_size(400))
        right_layout.addWidget(self.image_viewer, stretch=1)

        # 🆕 하단 영역 (상태 라벨 + 그리드 보기 버튼)
        bottom_layout = QHBoxLayout()

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(13)}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        bottom_layout.addWidget(self.status_label, stretch=1)

        # 🆕 그리드 보기 버튼
        self.grid_view_btn = QPushButton("🖼️ 그리드 보기")
        self.grid_view_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.grid_view_btn.setFixedHeight(get_scaled_size(32))
        self.grid_view_btn.clicked.connect(self._on_grid_view_clicked)
        self.grid_view_btn.setEnabled(False)  # 초기 비활성화
        bottom_layout.addWidget(self.grid_view_btn)

        right_layout.addLayout(bottom_layout)

        splitter.addWidget(right_widget)

        # 스플리터 비율 설정 (좌측 2 : 우측 1)
        splitter.setSizes([600, 300])

        layout.addWidget(splitter, stretch=1)

        # 하단 버튼
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("취소")
        cancel_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        self.create_btn = QPushButton("✅ 이벤트 생성")
        self.create_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.create_btn.clicked.connect(self._on_create_clicked)
        button_layout.addWidget(self.create_btn)

        layout.addLayout(button_layout)

    def _create_header(self) -> QFrame:
        """헤더 프레임 생성"""
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border-radius: {get_scaled_size(6)}px;
            }}
        """)

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)

        title = QLabel("➕ Custom Event 생성")
        title.setStyleSheet(f"""
            font-size: {get_scaled_font_size(18)}px;
            font-weight: bold;
            color: {DARK_COLORS['text_primary']};
        """)
        layout.addWidget(title)

        layout.addStretch()

        help_label = QLabel("Parent 이미지 생성 후 Child 테스트 가능")
        help_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(14)}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        layout.addWidget(help_label)

        return frame

    def _apply_theme(self):
        """다크 테마 적용"""
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_secondary']};
            }}
        """)

    def _add_child_widget(self):
        """Child 프롬프트 위젯 추가"""
        if len(self.child_widgets) >= 6:
            QMessageBox.warning(self, "제한", "최대 6개의 Child 장면만 추가할 수 있습니다.")
            return

        index = len(self.child_widgets) + 1
        child_widget = PromptInputWidget(
            index, is_parent=False,
            characteristic_tags=self.characteristic_tags,
            clothes_tags=self.clothes_tags
        )
        child_widget.removed.connect(self._on_child_removed)
        child_widget.test_requested.connect(self._on_test_requested)
        child_widget.thumbnail_clicked.connect(self._on_thumbnail_clicked)  # 🆕
        child_widget.prompt_changed.connect(self._on_prompt_changed)  # 🆕
        child_widget.copy_parent_requested.connect(self._on_copy_parent_requested)  # 🆕
        child_widget.copy_prev_requested.connect(self._on_copy_prev_requested)  # 🆕

        # Parent(0) 다음, stretch 앞에 삽입
        insert_position = 1 + len(self.child_widgets)
        self.prompts_layout.insertWidget(insert_position, child_widget)
        self.child_widgets.append(child_widget)

        # Child 테스트 버튼 상태 업데이트
        self._update_child_test_buttons()

    def _on_child_removed(self, widget: PromptInputWidget):
        """Child 위젯 삭제"""
        if len(self.child_widgets) <= 2:
            QMessageBox.warning(self, "제한", "최소 2개의 Child 장면이 필요합니다.")
            return

        self.child_widgets.remove(widget)
        self.prompts_layout.removeWidget(widget)
        widget.deleteLater()

        # 인덱스 재정렬
        for i, w in enumerate(self.child_widgets):
            w.update_index(i + 1)

    def _update_child_test_buttons(self):
        """Child 테스트 버튼 상태 업데이트 (Parent 이미지 필요)"""
        has_parent_image = self.parent_widget.has_image()
        for child in self.child_widgets:
            child.set_test_enabled(has_parent_image)

    def _on_copy_parent_requested(self, child_index: int):
        """🆕 Parent 복사 버튼 클릭"""
        parent_prompt = self.parent_widget.get_prompt()
        for child in self.child_widgets:
            if child.index == child_index:
                child.set_prompt(parent_prompt)
                print(f"[CustomEventDialog] Parent → Child {child_index} 복사 완료")
                break

    def _on_copy_prev_requested(self, child_index: int):
        """🆕 Prev 복사 버튼 클릭"""
        # 이전 Child 찾기
        prev_child = None
        for child in self.child_widgets:
            if child.index == child_index - 1:
                prev_child = child
                break

        if prev_child:
            prev_prompt = prev_child.get_prompt()
            for child in self.child_widgets:
                if child.index == child_index:
                    child.set_prompt(prev_prompt)
                    print(f"[CustomEventDialog] Child {child_index - 1} → Child {child_index} 복사 완료")
                    break

    def _on_prompt_changed(self, _index: int, _prompt: str):
        """🆕 프롬프트 변경 시 diff 재계산"""
        # Parent나 Child 프롬프트 변경 시 모든 diff 재계산
        self._recalculate_all_diffs()

    def _recalculate_all_diffs(self):
        """🆕 모든 Child의 태그 diff 재계산"""
        parent_tags = self._parse_tags(self.parent_widget.get_prompt())
        prev_tags = parent_tags

        for child in self.child_widgets:
            child_tags = self._parse_tags(child.get_prompt())

            # Prev와의 차이 (이전 Child)
            prev_removed = prev_tags - child_tags

            # Parent와의 차이
            parent_removed = parent_tags - child_tags

            # diff 업데이트
            child.update_tag_diff(prev_removed, parent_removed)

            prev_tags = child_tags

    def _parse_tags(self, prompt: str) -> set:
        """🆕 프롬프트를 태그 set으로 변환"""
        if not prompt:
            return set()
        return set(t.strip() for t in prompt.split(',') if t.strip())

    def _on_thumbnail_clicked(self, index: int, image: Image.Image):
        """🆕 썸네일 클릭 - 미리보기 영역에 이미지 표시"""
        # 이전 선택 해제
        if self._selected_widget_index is not None:
            self._deselect_widget(self._selected_widget_index)

        # 새 선택
        self._selected_widget_index = index
        self._select_widget(index)

        # 이미지 뷰어에 표시
        self.image_viewer.set_image(image)

        # 상태 업데이트
        if index == 0:
            self.status_label.setText("📸 Parent 이미지")
        else:
            self.status_label.setText(f"📸 Child #{index} 이미지")

    def _select_widget(self, index: int):
        """🆕 위젯 선택 상태로 변경"""
        if index == 0:
            self.parent_widget.set_selected(True)
        else:
            for child in self.child_widgets:
                if child.index == index:
                    child.set_selected(True)
                    break

    def _deselect_widget(self, index: int):
        """🆕 위젯 선택 해제"""
        if index == 0:
            self.parent_widget.set_selected(False)
        else:
            for child in self.child_widgets:
                if child.index == index:
                    child.set_selected(False)
                    break

    def _on_test_requested(self, index: int, prompt: str, rating: str):
        """테스트 생성 요청"""
        if self._is_generating:
            QMessageBox.warning(self, "생성 중", "이미지 생성이 진행 중입니다.")
            return

        is_parent = (index == 0)

        # Child는 Parent 이미지 필요
        if not is_parent and not self.parent_widget.has_image():
            QMessageBox.warning(
                self, "Parent 필요",
                "Child 테스트를 하려면 먼저 Parent 이미지를 생성해야 합니다."
            )
            return

        print(f"🧪 Test generation: index={index}, rating={rating}, prompt={prompt[:50]}...")

        # SequenceGenerationWorker를 통해 생성
        self._generate_test_image(index, prompt, rating, is_parent)

    def _generate_test_image(self, index: int, prompt: str, rating: str, is_parent: bool):
        """테스트 이미지 생성 (SequenceGenerationWorker 사용)"""
        if not self.app_context:
            QMessageBox.warning(self, "오류", "AppContext가 없습니다.")
            return

        try:
            from ..workers.sequence_generation_worker import SequenceGenerationWorker

            # 프롬프트 데이터 구성
            prompt_data = {
                'index': 0,  # 워커 내부 인덱스 (항상 0)
                'id': index,
                'general': prompt,
                'rating': rating,
                'is_parent': is_parent
            }

            # 이전 이미지 (Child인 경우 Parent 이미지 필요)
            prev_images = []
            if not is_parent and self.parent_widget.has_image():
                prev_images = [self.parent_widget.get_image()]

            # 워커 생성
            self._generation_worker = SequenceGenerationWorker(
                app_context=self.app_context,
                prompts=[prompt_data],
                direction='horizontal',
                strength=0.7,
                negative_prompt='',
                prev_images=prev_images,
                start_index=index,
                keep_background=False
            )

            # 시그널 연결
            self._generation_worker.image_generated.connect(self._on_image_generated)
            self._generation_worker.progress_updated.connect(self._on_progress_updated)
            self._generation_worker.generation_error.connect(self._on_generation_error)
            self._generation_worker.generation_finished.connect(self._on_generation_finished)

            # 생성 시작
            self._is_generating = True
            self._current_test_index = index
            self.status_label.setText("🔄 생성 중...")
            self.create_btn.setEnabled(False)

            self._generation_worker.start_generation()

        except Exception as e:
            print(f"❌ 테스트 생성 오류: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "오류", f"생성 실패: {e}")

    def _on_image_generated(self, index: int, image: Image.Image):
        """이미지 생성 완료"""
        print(f"✅ Image generated: index={index}")

        # 해당 위젯에 이미지 설정
        if index == 0:
            # Parent
            self.parent_widget.set_image(image)
            self._update_child_test_buttons()
        else:
            # Child
            for child in self.child_widgets:
                if child.index == index:
                    child.set_image(image)
                    break

        # 이미지 뷰어에 표시
        self.image_viewer.set_image(image)

        # 🆕 그리드 버튼 상태 업데이트
        self._update_grid_button_state()

    def _on_progress_updated(self, current: int, total: int, status: str):
        """진행 상황 업데이트"""
        self.status_label.setText(f"🔄 {status}")

    def _on_generation_error(self, index: int, error_msg: str):
        """생성 에러"""
        print(f"❌ Generation error: index={index}, error={error_msg}")
        self.status_label.setText(f"❌ 오류: {error_msg}")
        self._is_generating = False
        self.create_btn.setEnabled(True)

        # 워커 정리 (메모리 누수 방지)
        if self._generation_worker:
            self._generation_worker.cancel()
            self._generation_worker.deleteLater()
            self._generation_worker = None

    def _on_generation_finished(self, images: list):
        """생성 완료"""
        self._is_generating = False
        self.create_btn.setEnabled(True)
        self.status_label.setText("✅ 생성 완료")

        # 워커 정리 (메모리 누수 방지)
        if self._generation_worker:
            self._generation_worker.cancel()
            self._generation_worker.deleteLater()
            self._generation_worker = None

    def _update_grid_button_state(self):
        """🆕 그리드 보기 버튼 활성화 상태 업데이트"""
        # Parent + 최소 1개 Child 이미지 필요
        has_parent = self.parent_widget.has_image()
        child_count = sum(1 for child in self.child_widgets if child.has_image())

        can_create_grid = has_parent and child_count >= 1
        self.grid_view_btn.setEnabled(can_create_grid)

    def _create_grid_image(self) -> Optional[Image.Image]:
        """🆕 현재 생성된 이미지들로 그리드 생성"""
        # 이미지 수집 (Parent + Children)
        images = []

        # Parent
        if self.parent_widget.has_image():
            images.append(self.parent_widget.get_image())
        else:
            return None  # Parent 필수

        # Children
        for child in self.child_widgets:
            if child.has_image():
                images.append(child.get_image())

        if len(images) < 2:
            return None  # 최소 2개 필요 (Parent + Child 1개)

        # 그리드 생성 (history_panel.py 로직 참고)
        img_w, img_h = images[0].size
        count = len(images)

        cols = count
        rows = 1

        grid_w = img_w * cols
        grid_h = img_h * rows

        grid = Image.new('RGB', (grid_w, grid_h), (30, 30, 30))

        for i, img in enumerate(images):
            x = (i % cols) * img_w
            y = (i // cols) * img_h

            if img.size != (img_w, img_h):
                img = img.resize((img_w, img_h), Image.Resampling.LANCZOS)

            grid.paste(img, (x, y))

        return grid

    def _on_grid_view_clicked(self):
        """🆕 그리드 보기 버튼 클릭"""
        grid_image = self._create_grid_image()

        if grid_image:
            # 이미지 뷰어에 표시
            self.image_viewer.set_image(grid_image)

            # 모든 위젯 선택 해제
            if self._selected_widget_index is not None:
                self._deselect_widget(self._selected_widget_index)
                self._selected_widget_index = None

            self.status_label.setText("🖼️ 그리드 보기")
        else:
            QMessageBox.warning(self, "그리드 생성 실패", "그리드를 생성할 이미지가 부족합니다.")

    def _on_create_clicked(self):
        """이벤트 생성 버튼 클릭"""
        # 유효성 검사
        parent_prompt = self.parent_widget.get_prompt()
        if not parent_prompt:
            QMessageBox.warning(self, "입력 오류", "Parent 프롬프트를 입력하세요.")
            return

        child_prompts = [w.get_prompt() for w in self.child_widgets]
        if any(not p for p in child_prompts):
            QMessageBox.warning(self, "입력 오류", "모든 Child 프롬프트를 입력하세요.")
            return

        # Rating 수집
        parent_rating = self.parent_widget.get_rating()
        child_ratings = [w.get_rating() for w in self.child_widgets]

        # Parquet 저장
        try:
            parent_id = self._save_to_parquet(
                parent_prompt, parent_rating,
                child_prompts, child_ratings
            )

            if parent_id:
                QMessageBox.information(
                    self, "성공",
                    f"커스텀 이벤트가 생성되었습니다!\n\n"
                    f"Parent ID: {parent_id}\n"
                    f"Child 수: {len(child_prompts)}"
                )
                self.event_created.emit(parent_id)
                self.accept()

        except Exception as e:
            QMessageBox.critical(self, "오류", f"이벤트 생성 실패:\n{e}")
            import traceback
            traceback.print_exc()

    def _save_to_parquet(
        self,
        parent_prompt: str,
        parent_rating: str,
        child_prompts: list[str],
        child_ratings: list[str]
    ) -> int:
        """Parquet 파일에 저장"""

        personal_path = self.data_dir / 'NAIA_event_dataset_personal.parquet'

        # 기존 데이터 로드
        if personal_path.exists():
            existing_df = pd.read_parquet(personal_path)
            # 커스텀 ID 범위(10000000 이상)에서 최대값 찾기
            custom_ids = existing_df[existing_df['id'] >= 10000000]['id']
            if len(custom_ids) > 0:
                max_id = custom_ids.max()
            else:
                max_id = 10000000  # 커스텀 ID 시작점
        else:
            existing_df = pd.DataFrame()
            max_id = 10000000  # 커스텀 ID 시작점 (10000000으로 변경)

        # 새 ID 생성 (충돌 방지)
        parent_id = int(max_id) + 1
        now = datetime.now().isoformat()

        # 공통 메타데이터
        base_meta = {
            'copyright': None,
            'character': None,
            'artist': 'custom',
            'meta': None,
            'score': 0,
            'created_at': now,
            'tokens': None,
            'image_width': 832.0,
            'image_height': 1216.0,
            'updated_at': now,
            'up_score': 0.0,
            'down_score': 0.0,
            'fav_count': 0.0,
            'file_ext': 'png',
        }

        rows = []

        # Parent 행
        parent_tags = [t.strip() for t in parent_prompt.split(',') if t.strip()]
        parent_row = {
            'id': parent_id,
            'parent_id': None,
            'general': parent_prompt,
            'rating': parent_rating,
            'tag_count': float(len(parent_tags)),
            'tag_count_general': float(len(parent_tags)),
            'tag_count_artist': 1.0,
            'tag_count_character': 0.0,
            'tag_count_copyright': 0.0,
            'tag_count_meta': 0.0,
            'has_children': True,
            'has_active_children': True,
            'has_visible_children': True,
            **base_meta
        }
        rows.append(parent_row)

        # Child 행들
        for i, (child_prompt, child_rating) in enumerate(zip(child_prompts, child_ratings)):
            child_id = parent_id + i + 1
            child_tags = [t.strip() for t in child_prompt.split(',') if t.strip()]

            child_row = {
                'id': child_id,
                'parent_id': float(parent_id),
                'general': child_prompt,
                'rating': child_rating,
                'tag_count': float(len(child_tags)),
                'tag_count_general': float(len(child_tags)),
                'tag_count_artist': 1.0,
                'tag_count_character': 0.0,
                'tag_count_copyright': 0.0,
                'tag_count_meta': 0.0,
                'has_children': False,
                'has_active_children': False,
                'has_visible_children': False,
                **base_meta
            }
            rows.append(child_row)

        # DataFrame 생성 및 병합
        new_df = pd.DataFrame(rows)

        if len(existing_df) > 0:
            combined_df = pd.concat([existing_df, new_df], ignore_index=True)
        else:
            combined_df = new_df

        # 저장
        combined_df.to_parquet(personal_path, index=False)
        print(f"✅ Custom event saved: Parent ID = {parent_id}, Children = {len(child_prompts)}")

        return parent_id

    def closeEvent(self, event):
        """다이얼로그 닫힐 때 워커 정리 (메모리 누수 방지)"""
        if self._generation_worker:
            self._generation_worker.cancel()
            self._generation_worker.deleteLater()
            self._generation_worker = None
        super().closeEvent(event)
