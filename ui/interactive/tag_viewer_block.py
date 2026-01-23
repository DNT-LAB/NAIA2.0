"""
Tag Viewer Block - 태그 뷰어 독립형 블록
"""
from PyQt6.QtWidgets import QVBoxLayout, QSizePolicy
from PyQt6.QtCore import pyqtSignal
from ui.interactive.block_widget import BlockWidget
from ui.interactive.tag_viewer_widget import TagViewerWidget

class TagViewerBlock(BlockWidget):
    """
    TagViewerWidget을 BlockWidget으로 감싸서 Interactive Mode에서 사용.
    DraggablePanel과 호환되도록 toggled 시그널과 접기/펼치기 기능 제공.
    """

    # 내부 TagViewerWidget의 시그널을 프록시
    quick_search_requested = pyqtSignal(str)
    tag_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        # BlockWidget 초기화 (제목과 타입 지정)
        super().__init__("태그 뷰어", parent, block_type='utility')
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._init_content()

    def _init_content(self):
        """TagViewerWidget을 내용 영역에 추가"""
        layout = self.get_content_layout()

        # TagViewerWidget 생성 (parent를 self로 지정하여 window flags 방지)
        self.tag_viewer = TagViewerWidget(self)
        layout.addWidget(self.tag_viewer)

        # 내부 위젯의 시그널을 외부로 포워딩
        self.tag_viewer.quick_search_requested.connect(self.quick_search_requested.emit)
        self.tag_viewer.tag_selected.connect(self.tag_selected.emit)

        # 남는 공간 채우기 (상단 정렬)
        layout.addStretch()

    def get_tag_viewer(self):
        """내부 TagViewerWidget 반환 (외부 접근용)"""
        return self.tag_viewer

    # ===== 내부 TagViewerWidget의 메서드/속성 프록시 =====

    @property
    def target_widget(self):
        """타겟 위젯 프록시 (getter)"""
        return self.tag_viewer.target_widget

    @target_widget.setter
    def target_widget(self, widget):
        """타겟 위젯 프록시 (setter)"""
        self.tag_viewer.target_widget = widget

    @property
    def all_tags_data(self):
        """태그 데이터 프록시"""
        return self.tag_viewer.all_tags_data

    def set_tags_data(self, tags_data):
        """태그 데이터 설정 프록시"""
        self.tag_viewer.set_tags_data(tags_data)
