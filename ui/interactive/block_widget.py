# ui/interactive/block_widget.py
"""
BlockWidget - ComfyUI 스타일의 접을 수 있는 블록 패널

[UI Design Guidelines & Policies]
1. Block Structure
   - Vertical Policy: `QSizePolicy.Policy.Maximum`을 사용하여 컨텐츠 높이에 딱 맞게 유지하세요.
   - Width: 상위 컨테이너에서 고정 너비(예: 420px)를 제어합니다.

2. Content Layout
   - Vertical Stretch 방지: 메인 레이아웃 최하단에 `layout.addStretch()`를 추가하여 위젯들이 상단에 밀착되도록 하세요.
   - Horizontal Guidelines: 컨트롤들은 `QHBoxLayout`을 사용하여 한 줄에 배치하고, `stretch factor`를 활용해 균등 분배하세요.
   - Separators: 구분선은 `QFrame`을 사용하되, `background-color: transparent`로 설정하여 시각적 노이즈 없이 간격만 유지하는 것을 권장합니다.

3. Components & Styling
   - Buttons: Radio Button 대신 `Checkable QPushButton`을 선호합니다. 배경색은 `input_bg` 등 불투명색을 사용하여 겹침 현상을 방지하세요.
   - Style Isolation: 커스텀 위젯 스타일링 시 `setObjectName`과 ID 선택자(`QPushButton#my_id`)를 사용하여 부모 스타일 상속을 차단하세요.
   - Colors: `ui.interactive.interactive_theme`의 `COMMON_STYLES` 및 `DARK_COLORS`를 준수하세요.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtGui import QCursor

from ui.interactive.interactive_theme import (
    get_header_style,
    get_content_style,
    COMMON_STYLES
)
from ui.scaling_manager import get_scaled_size


class BlockWidget(QWidget):
    """접을 수 있는 블록 위젯 - ComfyUI 스타일"""

    toggled = pyqtSignal(bool)  # 접기/펼치기 상태 변경 시그널

    def __init__(self, title: str, parent=None, block_type: str = 'default'):
        """
        Args:
            title: 블록 제목
            parent: 부모 위젯
            block_type: 블록 타입 ('latent', 'conditioning', 'model', 'image',
                       'sampler', 'utility', 'control', 'default')
        """
        super().__init__(parent)

        self.title = title
        self.is_collapsed = False
        self.block_type = block_type

        self._init_ui()

    def _init_ui(self):
        """UI 초기화"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)  # 간격 제거

        # === 헤더 (그라디언트) ===
        self.header = QFrame()
        self.header.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.header.setStyleSheet(get_header_style(self.block_type, self.is_collapsed))

        header_layout = QVBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 0, 0)

        # 헤더 레이블 (화살표 + 제목)
        self.header_label = QLabel(f"▼ {self.title}")
        # 스타일은 이미 get_header_style()에서 QLabel에 적용됨
        header_layout.addWidget(self.header_label)

        # 헤더 클릭 이벤트
        self.header.mousePressEvent = lambda event: self.toggle_collapse()

        main_layout.addWidget(self.header)

        # === 내용 컨테이너 ===
        self.content_container = QFrame()
        self.content_container.setStyleSheet(get_content_style(self.block_type))

        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(
            get_scaled_size(12),
            get_scaled_size(10),
            get_scaled_size(12),
            get_scaled_size(10)
        )
        self.content_layout.setSpacing(get_scaled_size(8))

        main_layout.addWidget(self.content_container)

        # 애니메이션 설정
        self.animation = QPropertyAnimation(self.content_container, b"maximumHeight")
        self.animation.setDuration(200)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

    def toggle_collapse(self):
        """접기/펼치기 토글"""
        self.is_collapsed = not self.is_collapsed
        
        # 헤더 스타일 업데이트 (모서리 둥글기 등)
        self.header.setStyleSheet(get_header_style(self.block_type, self.is_collapsed))

        if self.is_collapsed:
            # 접기
            self.header_label.setText(f"► {self.title}")
            self.animation.setStartValue(self.content_container.height())
            self.animation.setEndValue(0)
            self.animation.start()
            self.content_container.setVisible(False)
        else:
            # 펼치기
            self.header_label.setText(f"▼ {self.title}")
            self.content_container.setVisible(True)
            self.content_container.setMaximumHeight(16777215)  # 제한 해제

        self.toggled.emit(not self.is_collapsed)

    def get_content_layout(self) -> QVBoxLayout:
        """내용 레이아웃 반환 (위젯 추가용)"""
        return self.content_layout

    def set_collapsed(self, collapsed: bool):
        """프로그래밍 방식으로 접기/펼치기 설정"""
        if self.is_collapsed != collapsed:
            self.toggle_collapse()
