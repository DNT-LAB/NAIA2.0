# tabs/storyteller/story_box.py

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QSizePolicy, QToolButton, QMenu,
    QLabel, QInputDialog, QGridLayout, QApplication
)
from PyQt6.QtCore import Qt, QPoint, pyqtSignal, QEvent
from PyQt6.QtGui import QAction, QMouseEvent

from ui.theme import DARK_STYLES, DARK_COLORS
from tabs.storyteller.story_item_widget import StoryItemWidget
from tabs.storyteller.custom_dialogs import CustomInputDialog
from tabs.storyteller.flow_layout import FlowLayout

class StoryBox(QWidget):
    subgroup_add_requested = pyqtSignal(str, str)
    expanded = pyqtSignal(object)
    focused = pyqtSignal(object)
    collapsed = pyqtSignal(object)
    delete_requested = pyqtSignal(object)

    def __init__(self, title: str, variable_name: str, box_path: str, description: str = "", level: str = 'upper', is_global: bool = False, parent_box=None, parent=None):
        super().__init__(parent)
        self.title = title
        self.variable_name = variable_name
        self.box_path = box_path
        self.level = level
        self.description = description
        self.is_global = is_global
        self.parent_box = parent_box
        self.is_collapsed = False
        self.child_boxes = {}
        self.items = {}
        self.setStyleSheet(DARK_STYLES['collapsible_box'])
        self.init_ui()

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(0)
        self.main_layout.setContentsMargins(8, 6, 8, 8)
        self.toggle_button = QToolButton(text=f" {self.title}", checkable=True, checked=True)
        self.default_style = "QToolButton { background-color: transparent; color: white; }"
        self.focused_style = "QToolButton { background-color: #FAFAD2; color: #000; font-weight: bold; }"
        self.toggle_button.setStyleSheet(self.default_style)
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(Qt.ArrowType.DownArrow)
        self.toggle_button.toggled.connect(self.on_toggled)
        self.toggle_button.installEventFilter(self)
        self.toggle_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.toggle_button.customContextMenuRequested.connect(self.show_context_menu)
        self.description_label = QLabel(self.description)
        self.description_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; padding: 0px 10px 5px 10px;")
        self.description_label.setVisible(bool(self.description))
        self.description_label.setWordWrap(True)
        self.content_area = QScrollArea()
        self.content_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.content_area.setWidgetResizable(True)
        self.content_area.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")
        self.content_area.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.content_area.viewport().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.content_widget = QWidget()
        self.content_widget.installEventFilter(self)
        if self.level == 'upper':
            self.content_layout = QVBoxLayout(self.content_widget)
            self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        else:
            self.content_layout = FlowLayout(self.content_widget)
        self.content_layout.setSpacing(8)
        self.content_area.setWidget(self.content_widget)
        self.main_layout.addWidget(self.toggle_button)
        self.main_layout.addWidget(self.description_label)
        self.main_layout.addWidget(self.content_area)

    def eventFilter(self, obj, event: QEvent) -> bool:
        # 마우스 누름 이벤트일 때만 처리
        if event.type() == QEvent.Type.MouseButtonPress:
            # ▼▼▼▼▼ [수정] .toPoint()를 추가하여 QPointF를 QPoint로 변환 ▼▼▼▼▼
            clicked_widget = QApplication.widgetAt(event.globalPosition().toPoint())
            # ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲
            
            parent = clicked_widget
            while parent:
                # 위젯 계층을 따라 올라가면서,
                # 만약 클릭된 위젯이 다른 StoryBox의 자손이라면,
                # 이 이벤트 필터는 무시하고 해당 자식에게 처리를 넘김
                if isinstance(parent, StoryBox) and parent is not self:
                    return False # 이벤트 무시 (자식이 처리하도록 함)
                
                # 자기 자신을 만나면 루프 종료
                if parent is self:
                    break
                
                parent = parent.parent()

            # 위의 루프를 통과했다면, 클릭이 다른 자식 StoryBox가 아닌
            # 자신의 배경이나 아이템 위젯에서 발생한 것이므로 포커스를 요청함
            self.focused.emit(self)

        return super().eventFilter(obj, event)

    def add_subgroup(self, story_box_widget):
        if self.level == 'upper' and isinstance(self.content_layout, QVBoxLayout):
            story_box_widget.installEventFilter(self)
            self.content_layout.addWidget(story_box_widget)
            self.child_boxes[story_box_widget.variable_name] = story_box_widget
        else: 
            print(f"Warning: {self.title} is not an UpperLevel box.")
            
    def add_item(self, item_widget: StoryItemWidget):
        if self.level == 'lower':
            item_widget.installEventFilter(self) # 아이템 클릭 시에도 상위가 알아야 하므로 필터 설치
            self.items[item_widget.variable_name] = item_widget
            self.content_layout.addWidget(item_widget)
        else:
            print(f"Warning: {self.title} is not a LowerLevel box.")

    # ... [나머지 모든 메서드는 이전과 동일] ...
    def show_context_menu(self, position: QPoint):
        """제목 버튼에서 우클릭 시 컨텍스트 메뉴 표시"""
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background-color: {DARK_COLORS['bg_tertiary']}; color: {DARK_COLORS['text_primary']}; border: 1px solid {DARK_COLORS['border']}; }}
            QMenu::item:selected {{ background-color: {DARK_COLORS['accent_blue']}; }}
            QMenu::separator {{ height: 1px; background-color: {DARK_COLORS['border']}; margin: 5px 0px; }}
        """)
        
        # UpperLevel일 때만 '하위 그룹 추가' 옵션 표시
        if self.level == 'upper':
            add_subgroup_action = QAction("➕ 하위 그룹 추가", self)
            add_subgroup_action.triggered.connect(self._request_add_subgroup)
            menu.addAction(add_subgroup_action)
            menu.addSeparator()

        # 모든 레벨에 '그룹 삭제' 옵션 표시
        delete_action = QAction("❌ 그룹 삭제", self)
        delete_action.triggered.connect(self._request_delete)
        menu.addAction(delete_action)
        
        menu.exec(self.toggle_button.mapToGlobal(position))

    def _request_delete(self):
        """삭제 요청 시그널을 발생시킵니다."""
        self.delete_requested.emit(self)
        
    def _request_add_subgroup(self):
        text, ok = CustomInputDialog.getText(self, '하위 그룹 추가', '새 하위 그룹의 이름을 입력하세요:')
        if ok and text: self.subgroup_add_requested.emit(self.variable_name, text)
    def on_toggled(self, checked):
        self.is_collapsed = not checked
        self.toggle_button.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self.description_label.setVisible(checked and bool(self.description))
        if checked:
            self.content_area.setMinimumHeight(300)
            self.content_area.setMaximumHeight(16777215) # QWidget의 최대 높이 상수
            self.expanded.emit(self)
        else:
            self.content_area.setMinimumHeight(0)
            self.content_area.setMaximumHeight(0)
            self.collapsed.emit(self)
        self.content_area.setVisible(checked)
        if checked: self.expanded.emit(self)
        else: self.collapsed.emit(self)
    def collapse(self): self.toggle_button.setChecked(False)
    def set_focused(self, is_focused: bool):
        if is_focused: self.toggle_button.setStyleSheet(self.focused_style)
        else: self.toggle_button.setStyleSheet(self.default_style)

    def remove_item(self, variable_name: str):
        """변수명으로 지정된 StoryItemWidget을 레이아웃과 내부 목록에서 제거합니다."""
        if self.level == 'lower' and variable_name in self.items:
            item_widget = self.items[variable_name]
            
            # 1. 레이아웃에서 위젯 제거
            self.content_layout.removeWidget(item_widget)
            
            # 2. 위젯을 메모리에서 삭제하도록 예약
            item_widget.deleteLater()
            
            # 3. 내부 관리 딕셔너리에서 제거
            del self.items[variable_name]
            
            # 4. 레이아웃을 업데이트하여 빈 공간을 채움
            self.content_layout.update()
            print(f"✅ 아이템 '{variable_name}'이 '{self.title}' 그룹에서 제거되었습니다.")