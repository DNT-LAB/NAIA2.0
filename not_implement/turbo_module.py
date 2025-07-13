from PyQt6.QtWidgets import QVBoxLayout, QLabel, QWidget
from interfaces.base_module import BaseMiddleModule

class TurboModule(BaseMiddleModule):
    """⚡ 터보 옵션 모듈"""
    
    def get_title(self) -> str:
        return "⚡ 터보 옵션"
    
    def get_order(self) -> int:
        return 2
    
    def create_widget(self, parent: QWidget) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(6)
        
        label = QLabel("터보 옵션들이 여기에 추가됩니다...")
        if parent and hasattr(parent, 'get_dark_style'):
            label.setStyleSheet(parent.get_dark_style('label_style'))
        
        layout.addWidget(label)
        return widget

    def get_parameters(self):
        print(self.get_title, "은 미구현 입니다.")
