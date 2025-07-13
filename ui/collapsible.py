from ui.theme import DARK_STYLES
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QSizePolicy, QToolButton
)
from PyQt6.QtCore import Qt

class CollapsibleBox(QWidget):
    """컴팩트한 어두운 테마의 접고 펼 수 있는 위젯"""
    def __init__(self, title="", parent=None):
        super(CollapsibleBox, self).__init__(parent)
        self.setStyleSheet(DARK_STYLES['collapsible_box'])

        self.toggle_button = QToolButton(text=f" {title}", checkable=True, checked=False)
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle_button.toggled.connect(self.on_toggled)

        self.content_area = QScrollArea()
        self.content_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.content_area.setMaximumHeight(0)
        self.content_area.setMinimumHeight(0)
        self.content_area.setWidgetResizable(True)
        self.content_area.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(8, 6, 8, 8)
        main_layout.addWidget(self.toggle_button)
        main_layout.addWidget(self.content_area)

    def on_toggled(self, checked):
        self.toggle_button.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        if checked:
            self.content_area.setMaximumHeight(16777215)
        else:
            self.content_area.setMaximumHeight(0)

    def setContentLayout(self, layout):
        content_widget = QWidget()
        content_widget.setStyleSheet("background-color: transparent;")
        content_widget.setLayout(layout)
        self.content_area.setWidget(content_widget)