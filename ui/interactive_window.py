# ui/interactive_window.py
"""
Interactive Window - NovelAI 이미지 생성 초보자를 위한 간단한 UI

좌우 분할 레이아웃
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSplitter, QCheckBox, QPushButton, QScrollArea, QFrame,
    QApplication, QTextEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QAction

from ui.theme import DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.interactive.block_widget import BlockWidget
import json
import os


class InteractiveWindow(QMainWindow):
    """Interactive 창 - 좌우 분할 레이아웃"""

    window_closed = pyqtSignal()

    def __init__(self, parent_app=None, app_context=None):
        super().__init__(parent=None)
        self.parent_app = parent_app
        self.app_context = app_context

        # 윈도우가 닫힐 때 자동으로 삭제되도록 설정
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        # parent_app이 종료되면 이 창도 닫기 (시그널 연결)
        if parent_app:
            parent_app.destroyed.connect(self.close)
            print(f"[InteractiveWindow] parent_app의 destroyed 시그널에 연결됨")

        # Tag Viewer 위치 초기화 플래그 (1회만 실행)
        self._tag_viewer_repositioned = False

        # 플로팅 패널 최초 정렬 플래그 (1회만 실행)
        self._first_reposition_done = False

        # 🆕 모드별 설정 관리 (윈도우가 열린 시점의 모드로 고정)
        self.current_mode = app_context.current_api_mode if app_context else "NAI"
        print(f"[InteractiveWindow] 모드 고정: {self.current_mode}")

        # 윈도우 설정
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowTitleHint
        )

        self.setWindowTitle("NAIA - Interactive Mode")
        self.setMinimumSize(800, 1000)
        self.resize(1200, 1030)

        # 다크 테마 적용
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                border: none;
                background: {DARK_COLORS['bg_secondary']};
                width: 10px;
                margin: 0px 0px 0px 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {DARK_COLORS['border']};
                min-height: 20px;
                border-radius: 5px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)


        self._init_ui()



    def _init_ui(self):
        """UI 초기화 - 좌우 분할 레이아웃"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 메인 수평 레이아웃
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # === 좌측 패널 ===
        left_panel = QWidget()
        left_panel.setStyleSheet(f"""
            QWidget {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)
        
        left_main_layout = QVBoxLayout(left_panel)
        left_main_layout.setContentsMargins(0, 0, 0, 0)
        left_main_layout.setSpacing(0)

        # 1. Scroll Area (Upper)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background-color: transparent;")
        
        # 블록들이 들어갈 레이아웃 (기존 left_layout 변수 재사용)
        left_layout = QVBoxLayout(self.scroll_content)
        left_layout.setContentsMargins(16, 16, 16, 16)
        left_layout.setSpacing(12)
        
        self.scroll_area.setWidget(self.scroll_content)
        left_main_layout.addWidget(self.scroll_area)

        # BlockWidget 예시 - ComfyUI 스타일 테마 적용
        
        # 인원수 / 이미지 목적 블록
        from ui.interactive.person_settings_block import PersonSettingsBlock
        self.person_block = PersonSettingsBlock()  # ✅ self 저장
        left_layout.addWidget(self.person_block)

        # 퀵 서치 블록
        from ui.interactive.quick_search_block import QuickSearchBlock
        self.quick_search_block = QuickSearchBlock()  # ✅ self 저장
        self.quick_search_block.set_collapsed(True)
        left_layout.addWidget(self.quick_search_block)

        # 연결: 인원/Rating 설정 변경 시 Quick Search 파티션 로드
        self.person_block.settingsChanged.connect(self.quick_search_block.load_partition)

        # 아티스트 태그 블록
        from ui.interactive.artist_tag_block import ArtistTagBlock
        self.artist_block = ArtistTagBlock()  # ✅ self 저장
        self.artist_block.set_collapsed(False) # 기본 펼침
        left_layout.addWidget(self.artist_block)



        # 캐릭터 프롬프트 블록 제거됨 (플로팅으로 이동)




        # 퀄리티 태그 블록
        from ui.interactive.quality_tag_block import QualityTagBlock
        self.quality_block = QualityTagBlock()  # ✅ self 저장
        #self.quality_block.set_collapsed(False)
        left_layout.addWidget(self.quality_block)

        # 네거티브 프롬프트 블록
        from ui.interactive.negative_prompt_block import NegativePromptBlock
        self.negative_block = NegativePromptBlock()  # ✅ self 저장
        #self.negative_block.set_collapsed(False)
        left_layout.addWidget(self.negative_block)

        # 상단 정렬을 위해 남는 공간 채움
        left_layout.addStretch()

        # 2. Bottom Fixed Area (Footer)
        self.bottom_panel = QWidget()
        self.bottom_panel.setStyleSheet(f"background-color: {DARK_COLORS['bg_secondary']}; border-top: 1px solid {DARK_COLORS['border']};")
        self.bottom_layout = QVBoxLayout(self.bottom_panel)
        self.bottom_layout.setContentsMargins(16, 16, 16, 16)
        
        # 임시 라벨 (레이아웃 확인용, 비워둠)
        # lbl = QLabel("Bottom Area")
        # self.bottom_layout.addWidget(lbl)
        
        left_main_layout.addWidget(self.bottom_panel)

        # === 우측 패널 ===
        self.right_panel = QWidget()
        self.right_panel.setStyleSheet(f"""
            QWidget {{
                background-color: #1A1A1A;
            }}
        """)
        right_layout = QVBoxLayout(self.right_panel)
        # 하단 여백 제거 (컨트롤 바 밀착)
        right_layout.setContentsMargins(16, 16, 16, 0)
        right_layout.setSpacing(0)

        # 우측 패널 내용 (캔버스 영역)
        self.canvas_widget = QWidget()
        self.canvas_widget.setStyleSheet("background-color: #121212; border-radius: 8px;")
        right_layout.addWidget(self.canvas_widget, 1) # 높이 100% 사용 (Stretch 1)

        # [이미지 플레인] 이미지 패널을 가장 먼저 생성하여 Z-Order 최하단 유지
        from ui.interactive.image_plane import ImagePlane
        self.image_plane = ImagePlane(parent=self.right_panel)
        
        # 초기 흰색 배경 (1024x1024) 설정
        from PIL import Image
        blank_img = Image.new('RGB', (1024, 1024), color='white')
        self.image_plane.set_image(blank_img)
        # 초기 위치는 showEvent에서 잡음
        self.image_plane.show()

        # [하단 중앙] 컨트롤 바 (고정 배치)
        from ui.interactive.floating_control_bar import FloatingControlBar
        self.control_bar = FloatingControlBar(app_context=self.app_context)
        # 레이아웃에 추가 (하단 여백 및 정렬)
        right_layout.addWidget(self.control_bar, 0, Qt.AlignmentFlag.AlignCenter)

        # [Z-Order 보장] 패널 활성화 시 컨트롤 바를 항상 최상위로
        from ui.interactive.draggable_panel import FloatingPanelManager
        FloatingPanelManager.instance().panel_activated.connect(self.control_bar.raise_)
        

        # 패널 숨기기 시그널 연결 (체크되면 -> 숨김)
        self.control_bar.sidebar_toggled.connect(lambda checked: left_panel.setHidden(checked))

        # 플로팅 고정 시그널 연결 (체크되면 -> 자동 정렬 허용)
        self.is_floating_pinned = True
        self.control_bar.float_pin_toggled.connect(self._on_float_pin_toggled)

        # [독립 윈도우] 태그 뷰어 생성
        self.standalone_tag_viewer = None  # 지연 초기화 (데이터 로딩 후)
        self.control_bar.tags_clicked.connect(self._toggle_standalone_tag_viewer)



        # 좌측 패널 너비 고정 (스크롤바 공간 포함하여 여유있게 설정 - 기존 440 -> 460)
        left_panel.setFixedWidth(get_scaled_size(460))

        # 메인 레이아웃에 패널 직접 추가 (스플리터 제거)
        main_layout.addWidget(left_panel)
        main_layout.addWidget(self.right_panel)



        # [플로팅 패널] 메인 프롬프트를 이미지 뷰어 위에 띄우기
        from ui.interactive.draggable_panel import DraggablePanel
        from ui.interactive.main_prompt_block import MainPromptBlock

        # 1. 플로팅할 내용물 생성
        float_main_block = MainPromptBlock(app_context=self.app_context)
        self.main_prompt_block = float_main_block # ✅ self 저장
        float_main_block.set_collapsed(False) # 펼쳐진 상태로 시작
        
        # 2. 드래그 가능한 래퍼에 넣고, 부모를 self.right_panel로 설정 (전체 영역 이동 가능)
        self.floating_panel = DraggablePanel(parent=self.right_panel, child_widget=float_main_block)
        
        # 3. 크기 및 위치 조정
        self.floating_panel.setFixedWidth(get_scaled_size(360)) # 메인 프롬프트는 넓게
        self._setup_responsive_panel(self.floating_panel, float_main_block, expanded_w=360) # Main만 360
        # 초기 위치는 showEvent에서
        self.floating_panel.show()

        # [자동완성 시스템] Interactive Mode 전용 자동완성 매니저 초기화
        from ui.interactive.interactive_autocomplete import InteractiveAutocompleteManager

        self.autocomplete_manager = InteractiveAutocompleteManager(self)

        # 🆕 데이터 로딩 완료 시그널 연결 (태그 뷰어 데이터 설정)
        self.autocomplete_manager.data_loaded.connect(self._on_autocomplete_data_loaded)

        # MainPromptBlock에 자동완성 등록
        float_main_block.register_autocomplete(self.autocomplete_manager)

        # ✅ MainPromptBlock에 QuickSearchBlock 참조 설정
        float_main_block.set_quick_search_block(self.quick_search_block)

        # ✅ 이미지 생성 요청 시그널 연결
        float_main_block.generate_requested.connect(self._on_generate_requested)

        # [User Request] 컨트롤 바 버튼 연결
        self.control_bar.random_clicked.connect(float_main_block.generate_random_prompt)
        self.control_bar.generate_clicked.connect(float_main_block.trigger_generation)
        self.control_bar.random_generate_clicked.connect(self._on_control_bar_random_generate)

        # [플로팅 패널 2] 추가 네거티브 프롬프트
        from ui.interactive.additional_negative_prompt_block import AdditionalNegativePromptBlock

        float_add_neg_block = AdditionalNegativePromptBlock()
        self.additional_negative_block = float_add_neg_block  # ✅ self 저장
        float_add_neg_block.set_collapsed(True)

        self.floating_neg_panel = DraggablePanel(parent=self.right_panel, child_widget=float_add_neg_block)
        # 초기값: 접힘 상태이므로 작게 시작
        self.floating_neg_panel.setFixedWidth(get_scaled_size(220))
        self._setup_responsive_panel(self.floating_neg_panel, float_add_neg_block)
        # 초기 위치는 showEvent에서
        self.floating_neg_panel.show()

        # [플로팅] 구도 설정 블록
        from ui.interactive.composition_block import CompositionBlock

        float_comp_block = CompositionBlock()
        self.composition_block = float_comp_block  # ✅ self 저장
        float_comp_block.set_collapsed(True) 

        self.floating_comp_panel = DraggablePanel(parent=self.right_panel, child_widget=float_comp_block)
        self.floating_comp_panel.setFixedWidth(get_scaled_size(220))
        self._setup_responsive_panel(self.floating_comp_panel, float_comp_block)
        # 초기 위치는 showEvent에서
        self.floating_comp_panel.show()

        # [플로팅] 캐릭터 레퍼런스 블록 (NAID4.5 전용 - COMFYUI에서는 숨김)
        from ui.interactive.character_reference_block import CharacterReferenceBlock

        float_char_ref_block = CharacterReferenceBlock(app_context=self.app_context)
        self.char_ref_block = float_char_ref_block # ✅ self 저장
        # 기본값: 접힘 상태
        float_char_ref_block.set_collapsed(True)

        self.floating_char_ref_panel = DraggablePanel(
            parent=self.right_panel,
            child_widget=float_char_ref_block
        )
        self.floating_char_ref_panel.setFixedWidth(get_scaled_size(220)) # 초기 접힘
        self._setup_responsive_panel(self.floating_char_ref_panel, float_char_ref_block)

        # COMFYUI 모드에서는 캐릭터 레퍼런스 숨김
        if self.current_mode == "COMFYUI":
            self.floating_char_ref_panel.hide()
            print(f"🎨 COMFYUI 모드: 캐릭터 레퍼런스 블록 숨김")
        else:
            self.floating_char_ref_panel.show()

        # [플로팅] 이미지 태거 블록 (WD14)
        from ui.interactive.image_tagger_block import ImageTaggerBlock

        self.image_tagger_block = ImageTaggerBlock()
        self.image_tagger_block.set_collapsed(True) # 기본 접힘

        # 태그 추출 시그널 -> 메인 프롬프트에 추가 (또는 덮어쓰기?)
        # 여기서는 메인 프롬프트 끝에 추가하는 방식으로 구현
        self.image_tagger_block.tags_extracted.connect(self._on_tags_extracted_from_image)

        # ✅ ImageTaggerBlock에 QuickSearchBlock, MainPromptBlock, AppContext 참조 설정
        self.image_tagger_block.set_quick_search_block(self.quick_search_block)
        self.image_tagger_block.set_main_prompt_block(self.main_prompt_block)
        self.image_tagger_block.app_context = self.app_context  # AppContext 전달

        self.floating_tagger_panel = DraggablePanel(
            parent=self.right_panel,
            child_widget=self.image_tagger_block
        )
        self.floating_tagger_panel.setFixedWidth(get_scaled_size(220))
        self._setup_responsive_panel(self.floating_tagger_panel, self.image_tagger_block)
        self.floating_tagger_panel.show()

        # [플로팅] 태그 뷰어 (투명 헤더 + 드래그 가능)
        from ui.interactive.tag_viewer_widget import TagViewerWidget
        from ui.interactive.draggable_panel import DraggablePanel

        # TagViewerWidget 생성 (parent 지정하여 embedded 모드)
        self.tag_viewer_widget = TagViewerWidget(parent=self.right_panel)

        # ✅ 임베디드 모드에서도 고정 크기 설정 (내용 표시 보장)
        self.tag_viewer_widget.setFixedSize(get_scaled_size(1050), get_scaled_size(950))

        # DraggablePanel로 감싸기
        self.tag_viewer_panel = DraggablePanel(
            parent=self.right_panel,
            child_widget=self.tag_viewer_widget,
            header_opacity=0.4,  # 드래그 영역 확보 (약간 보이게)
            title="📌 태그 뷰어",
            header_height=get_scaled_size(54), # 헤더 높이 강제 설정
            font_size=get_scaled_font_size(22), # 폰트 크기 강제 설정
            borderless=True # 테두리 제거 요청
        )

        # 위치 설정 (초기 위치 제거 - _reposition_floating_panels에서 자동 설정됨)
        # self.tag_viewer_panel.move(get_scaled_size(50), get_scaled_size(50))

        # 컨트롤 바 '태그 뷰어' 버튼 연결 - 제거됨
        # self.control_bar.tag_viewer_clicked.connect(self._toggle_tag_viewer)

        # [기능 연결] 퀵 서치 요청
        self.tag_viewer_widget.quick_search_requested.connect(self._handle_quick_search_request)
        self.tag_viewer_panel.set_collapsed(True)

        # [기능 연결] 이미지 플레인 클릭 시 태그 뷰어 토글
        self.image_plane.clicked.connect(self._on_image_plane_clicked)

        # [기능 연결] 포커스 트래킹 (마지막 에디터 추적)
        QApplication.instance().focusChanged.connect(self._on_focus_changed)

        # [플로팅] 캐릭터 프롬프트 블록 6개
        from ui.interactive.character_prompt_block import CharacterPromptBlock

        self.char_blocks = []
        self.char_panels = [] # DraggablePanel 리스트

        # 위치 잡기 (MainPromptBlock 아래)
        char_start_y = get_scaled_size(420)

        for i in range(1, 7):
            block = CharacterPromptBlock(index=i, app_context=self.app_context)
            # 1번 블록 버튼 연결
            if i == 1:
                block.add_character_clicked.connect(self._on_add_character_click)
                block.set_collapsed(True)
            else:
                block.remove_character_clicked.connect(self._on_remove_character_click)
                block.set_collapsed(False)

            # 랜덤 필드 요청 연결
            if hasattr(block, 'random_field_requested'):
                block.random_field_requested.connect(self._handle_char_random_request)

            # 패널 생성
            panel = DraggablePanel(parent=self.right_panel, child_widget=block)

            # 초기 너비 설정 (1번은 접힘=220, 나머지는 펼침=300? 아니면 다 접힘?)
            # 위 loop에서 1번만 접힘(True), 나머지는 펼침(False)로 설정했음.
            if i == 1:
                panel.setFixedWidth(get_scaled_size(220))
            else:
                panel.setFixedWidth(get_scaled_size(300))

            self._setup_responsive_panel(panel, block)

            # 초기 위치: 좌측 중앙 (20, 420)
            # 초기 위치는 showEvent에서
            # panel.move(get_scaled_size(20), char_start_y)

            if i == 1:
                panel.show()
            else:
                panel.hide()

            self.char_blocks.append(block)
            self.char_panels.append(panel)

        # ✅ CharacterPromptBlock들에 자동완성 등록
        for block in self.char_blocks:
            if hasattr(block, 'register_autocomplete'):
                block.register_autocomplete(self.autocomplete_manager)

        # [Z-Order 보장] 컨트롤 바를 최상위로
        self.control_bar.raise_()





    def _setup_responsive_panel(self, panel, block, expanded_w=300, collapsed_w=220):
        """패널이 접히고 펼쳐질 때 너비를 조절하고 위치를 재정렬하는 헬퍼"""
        def on_toggled(is_expanded):
            target_w = get_scaled_size(expanded_w if is_expanded else collapsed_w)
            panel.setFixedWidth(target_w)
            # 위치 재정렬
            QTimer.singleShot(10, self._reposition_floating_panels)

        block.toggled.connect(on_toggled)

    def _on_float_pin_toggled(self, checked):
        """플로팅 고정 상태 변경 핸들러"""
        self.is_floating_pinned = checked
        if checked:
            self._reposition_floating_panels()

    def _reposition_floating_panels(self):
        """상단 플로팅 패널들을 현재 너비에 맞춰 순차적으로 재배치"""

        # 1. 상단 플로팅 패널 그룹 (최초 1회 또는 Pinned 상태일 때만 자동 정렬)
        first_run = not getattr(self, '_first_reposition_done', False)
        is_pinned = getattr(self, 'is_floating_pinned', True)

        if first_run or is_pinned:
            spacing = get_scaled_size(5)

            # 1. Main Prompt (항상 기준)
            self.floating_panel.move(spacing, spacing)

            # 다음 위치 계산
            next_x = self.floating_panel.x() + self.floating_panel.width() + spacing
            common_y = spacing # Top Aligned

            # 2. Character Prompts (1~6)
            # 1번 패널만 보이거나, 추가된 패널들만 보임
            # 보이는 패널만 정렬 대상
            for panel in self.char_panels:
                if panel.isVisible():
                    panel.move(next_x, common_y)
                    next_x += panel.width() + spacing

            # 3. Additional Negative Prompt
            if self.floating_neg_panel.isVisible():
                self.floating_neg_panel.move(next_x, common_y)
                next_x += self.floating_neg_panel.width() + spacing

            # 4. Composition Block
            if self.floating_comp_panel.isVisible():
                self.floating_comp_panel.move(next_x, common_y)
                next_x += self.floating_comp_panel.width() + spacing

            # 5. Character Reference
            if self.floating_char_ref_panel.isVisible():
                self.floating_char_ref_panel.move(next_x, common_y)
                next_x += self.floating_char_ref_panel.width() + spacing

            # 6. Image Tagger
            if hasattr(self, 'floating_tagger_panel') and self.floating_tagger_panel.isVisible():
                self.floating_tagger_panel.move(next_x, common_y)
                next_x += self.floating_tagger_panel.width() + spacing

            # 최초 실행이었다면 플래그 설정 및 is_floating_pinned을 False로 변경
            if first_run:
                self._first_reposition_done = True
                self.is_floating_pinned = False
                self.control_bar.chk_float_pin.setChecked(False)
                print("[UI] 플로팅 패널 최초 자동 정렬 완료 → is_floating_pinned = False")

        # [User Request] Tag Viewer 위치 동기화 (Pinned 옵션 무시 - 화이트리스트)
        # Composition Block 위치 변화에 따라 항상 따라다님
        # ⚠️ 1회만 실행 (플래그 체크)
        if not self._tag_viewer_repositioned and hasattr(self, 'tag_viewer_panel') and hasattr(self, 'floating_comp_panel'):
            # 현재 Composition Panel 위치 기준
            # 주의: 위에서 move()를 호출했을 수 있으므로 최신 geometry 사용

            # Comp Panel geometry 가져오기
            comp_geo = self.floating_comp_panel.geometry()

            # 중앙 정렬 좌표 계산
            # CompCenter - (TagWidth / 2)
            # Comp Block이 숨겨져 있을 수도 있음

            if self.floating_comp_panel.isVisible():
                target_x = comp_geo.center().x() - (self.tag_viewer_panel.width() // 2) + get_scaled_size(225)

                # 화면 좌측 이탈 방지
                if target_x < get_scaled_size(20):
                    target_x = get_scaled_size(20)

                # Y: Composition Block 바로 아래 + 여백
                target_y = comp_geo.bottom() + get_scaled_size(20)

                self.tag_viewer_panel.move(target_x, target_y)
                print(f"[UI] Tag Viewer Repositioned: ({target_x}, {target_y}) based on Composition Block")

                # 플래그 설정 (다음부터는 실행 안 함)
                self._tag_viewer_repositioned = True

    def showEvent(self, event):
        super().showEvent(event)
        self.showMaximized() # 전체화면(최대화)
        self.showMaximized() # 전체화면(최대화)
        QTimer.singleShot(100, self._on_show_init)

    def _on_show_init(self):
        """화면 표시 후 초기화 작업 (위치 잡기 등)"""
        self._center_image_plane()
        self._init_pos_floating_panels()
        
        # 저장된 데이터 로드 (프롬프트/파라미터 복원)
        self.load_interactive_data()

        # 🔧 태그 뷰어 데이터 로드는 _on_autocomplete_data_loaded()로 이동됨
        # (InteractiveAutocompleteManager의 data_loaded 시그널에서 처리)

        # 태그 뷰어 패널 초기 상태를 접힌 상태로 설정 (딜레이 적용)
        QTimer.singleShot(150, lambda: self.tag_viewer_panel.set_collapsed(True) if hasattr(self, 'tag_viewer_panel') else None)

    def _on_autocomplete_data_loaded(self):
        """
        InteractiveAutocompleteManager 데이터 로딩 완료 시 호출됨
        태그 뷰어에 데이터 설정
        """
        if hasattr(self, 'tag_viewer_widget') and hasattr(self, 'autocomplete_manager'):
            tags_data = getattr(self.autocomplete_manager, 'tags_data', {})
            print(f"✅ [TagViewer] 데이터 로드 완료: {len(tags_data)}개 태그")

            if tags_data:
                self.tag_viewer_widget.set_tags_data(tags_data)
                print(f"✅ [TagViewer] 대분류 개수: {self.tag_viewer_widget.group_list.count()}")
            else:
                print("⚠️ [TagViewer] 경고: tags_data가 비어있습니다!")

        # 독립 태그 뷰어 초기화 (지연 초기화)
        if hasattr(self, 'autocomplete_manager') and not self.standalone_tag_viewer:
            tags_data = getattr(self.autocomplete_manager, 'tags_data', {})
            if tags_data:
                self._init_standalone_tag_viewer(tags_data)

        # MainPromptBlock 포맷팅 갱신 (데이터가 로드되었으므로 정확한 하이라이팅 가능)
        if hasattr(self, 'main_prompt_block'):
            self.main_prompt_block.refresh_formatting()

    def _init_pos_floating_panels(self):
        """플로팅 패널 초기 위치 설정 (창 크기에 맞춰 배치)"""
        if not hasattr(self, 'right_panel'): return

        self._reposition_floating_panels()
        

        

        




    # def _toggle_tag_viewer(self):
    #     """태그 뷰어 플로팅 패널 토글 - 제거됨 (항상 표시)"""
    #     pass

    def _init_standalone_tag_viewer(self, tags_data):
        """
        독립 윈도우 태그 뷰어 초기화

        Args:
            tags_data: 태그 데이터 딕셔너리
        """
        from ui.interactive.tag_viewer_widget import TagViewerWidget

        # parent=None으로 생성하여 독립 윈도우 모드
        self.standalone_tag_viewer = TagViewerWidget(parent=None)

        # 윈도우 플래그 재설정 (일반 윈도우로, 최상위 고정 방지)
        self.standalone_tag_viewer.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowTitleHint
        )

        # 윈도우 제목 설정
        self.standalone_tag_viewer.setWindowTitle("NAIA - Tag Viewer")

        # 커스텀 닫기 버튼 숨김 (시스템 닫기 버튼 사용)
        if hasattr(self.standalone_tag_viewer, 'btn_close'):
            self.standalone_tag_viewer.btn_close.hide()

        # 태그 데이터 설정
        self.standalone_tag_viewer.set_tags_data(tags_data)

        # 초기 상태: 숨김
        self.standalone_tag_viewer.hide()

        print(f"✅ [독립 태그 뷰어] 초기화 완료: {len(tags_data)}개 태그")

    def _toggle_standalone_tag_viewer(self):
        """독립 윈도우 태그 뷰어 토글"""
        if not self.standalone_tag_viewer:
            print("⚠️ [독립 태그 뷰어] 아직 초기화되지 않았습니다.")
            return

        if self.standalone_tag_viewer.isVisible():
            self.standalone_tag_viewer.hide()
            print("[독립 태그 뷰어] 숨김")
        else:
            # 화면 중앙에 배치
            screen_geo = self.screen().geometry() if self.screen() else None
            if screen_geo:
                x = screen_geo.center().x() - (self.standalone_tag_viewer.width() // 2)
                y = screen_geo.center().y() - (self.standalone_tag_viewer.height() // 2)
                self.standalone_tag_viewer.move(x, y)

            self.standalone_tag_viewer.show()
            self.standalone_tag_viewer.raise_()
            self.standalone_tag_viewer.activateWindow()

            # 외부 클릭 시 자동 닫기 비활성화 (일반 윈도우 동작)
            # eventFilter는 showEvent에서 설치되므로, show() 호출 후 제거
            QApplication.instance().removeEventFilter(self.standalone_tag_viewer)

            print("[독립 태그 뷰어] 표시")

    def _on_image_plane_clicked(self):
        """이미지 플레인 클릭 시 태그 뷰어 패널 접기 (펼치기 불가)"""
        if hasattr(self, 'tag_viewer_panel'):
            # 항상 접힌 상태로만 설정 (토글 아님)
            self.tag_viewer_panel.set_collapsed(True)
            print("[InteractiveWindow] 이미지 플레인 클릭 → 태그 뷰어 패널 접기")

    def _on_focus_changed(self, old, new):
        """포커스 변경 감지 -> 태그 뷰어의 타겟 위젯 업데이트"""
        if isinstance(new, QTextEdit):
            # 태그 뷰어 내부의 에디터는 제외 (자신에게 삽입 방지)
            if self.tag_viewer_widget.isAncestorOf(new):
                return

            # 유효한 타겟으로 설정
            print(f"[InteractiveWindow] 포커스 변경 감지: {new.objectName() if new.objectName() else type(new).__name__}")

            # 필터 속성 확인
            allowed_groups = new.property("allowed_groups")
            allowed_subgroups = new.property("allowed_subgroups")
            print(f"  - allowed_groups: {allowed_groups}")
            print(f"  - allowed_subgroups: {allowed_subgroups}")

            self.tag_viewer_widget.target_widget = new
            print(f"  - target_widget 설정 완료")

    def _handle_quick_search_request(self, tag):
        """태그 뷰어에서 퀵 서치 요청"""
        if hasattr(self, 'quick_search_block'):
            # QuickSearchBlock의 force_single_search 메서드 호출
            # (포함/제외 태그 초기화 후 해당 태그만 포함 태그로 설정하고 추천 갱신)
            if hasattr(self.quick_search_block, 'force_single_search'):
                self.quick_search_block.force_single_search(tag)
                print(f"[InteractiveWindow] 퀵 서치 검색 실행: {tag}")
            else:
                print(f"[InteractiveWindow] 경고: QuickSearchBlock에 force_single_search 메서드가 없습니다.")

    def _center_image_plane(self):
        """ImagePlane을 캔버스(canvas_widget) 크기에 맞춰 리사이즈 후 중앙으로 이동"""
        if hasattr(self, 'image_plane') and hasattr(self, 'canvas_widget'):
            # 캔버스 영역 크기
            target_widget = self.canvas_widget
            rw = target_widget.width()
            rh = target_widget.height()

            # 1. 자동 리사이징 (적당한 크기로 설정 - 화면 꽉 채우기 방지)
            base_size = get_scaled_size(1152) # 적당한 기본 크기
            
            # ImagePlane의 비율에 맞춰 크기 계산
            aspect_ratio = self.image_plane.aspect_ratio
            
            if aspect_ratio > 1:
                # 가로가 긴 경우 너비 기준
                target_w = base_size
                target_h = int(target_w / aspect_ratio)
            else:
                # 세로가 긴 경우 높이 기준
                target_h = base_size
                target_w = int(target_h * aspect_ratio)

            self.image_plane.resize(target_w, target_h)

            # 2. 중앙 이동 (right_panel 좌표계 기준) + 우측 오프셋
            canvas_pos = target_widget.pos()
            
            offset_x = get_scaled_size(60)
            x = canvas_pos.x() + (rw - target_w) // 2 + offset_x
            y = canvas_pos.y() + (rh - target_h) // 2

            self.image_plane.move(x, y)




    def closeEvent(self, event):
        """윈도우 닫힐 때 현재 모드 설정 저장"""
        # 🆕 현재 모드 설정 저장
        self.save_interactive_data()
        print(f"[InteractiveWindow] {self.current_mode} 모드 설정 저장 후 종료")

        self.window_closed.emit()
        event.accept()

    def _on_tags_extracted_from_image(self, tags: str):
        """이미지 태거에서 추출된 태그를 메인 프롬프트에 덮어쓰기"""
        if not tags: return

        if hasattr(self, 'main_prompt_block'):
            # 덮어쓰기 방식: 기존 텍스트 무시하고 추출된 태그만 설정
            # 포맷팅 적용하여 설정
            formatted_html = self.main_prompt_block._format_prompt_with_categories(tags)
            self.main_prompt_block.set_prompt_html(formatted_html)

            # 알림
            print(f"[InteractiveWindow] 추출된 태그 {len(tags.split(','))}개로 덮어씀")

    def _on_add_character_click(self):
        """캐릭터 추가 버튼 클릭 시 숨겨진 플로팅 패널 노출"""
        from PyQt6.QtCore import QPoint # 로컬 임포트
        
        for i, panel in enumerate(self.char_panels):
            if not panel.isVisible():
                panel.show()
                # 나타날 때 위치를 살짝 비켜서 겹침 방지 (캐스케이딩)
                if i > 0:
                    prev_panel = self.char_panels[i-1]
                    # 이전 패널 위치 기준 + (30, 30)
                    new_pos = prev_panel.pos() + QPoint(30, 30)
                    panel.move(new_pos)
                break
        
        self._update_add_char_button_state()

    
    def _on_remove_character_click(self):
        """캐릭터 제거 버튼 클릭 시 해당 플로팅 패널 숨김"""
        sender_block = self.sender()
        # 블록 객체 찾기
        if sender_block in self.char_blocks:
            idx = self.char_blocks.index(sender_block)
            if 0 <= idx < len(self.char_panels):
                self.char_panels[idx].hide()
                
        self._update_add_char_button_state()

    def _update_add_char_button_state(self):
        """모든 캐릭터 블록이 보이면 1번 블록 버튼 숨김, 아니면 보임"""
        if self.char_blocks and hasattr(self.char_blocks[0], 'btn_add'):
            if all(panel.isVisible() for panel in self.char_panels):
                self.char_blocks[0].btn_add.setVisible(False)
            else:
                self.char_blocks[0].btn_add.setVisible(True)

    def _handle_char_random_request(self, editor, groups, subgroups, field_type="unknown"):
        """캐릭터 프롬프트 랜덤 생성 요청 처리 (성별 기반 Creatures 필터링 포함)"""
        if not hasattr(self, 'quick_search_block'): return
        if not hasattr(self, 'autocomplete_manager'): return

        # 📌 현재 선택된 성별 확인 (editor -> CharacterForm -> gender_group)
        current_gender = "girl"  # 기본값
        try:
            # editor의 parent는 container, container의 parent는 CharacterForm
            container = editor.parent()
            if container:
                char_form = container.parent()
                if char_form and hasattr(char_form, 'gender_group'):
                    checked_btn = char_form.gender_group.checkedButton()
                    if checked_btn and hasattr(checked_btn, 'value'):
                        current_gender = checked_btn.value
                        print(f"[Interactive] 현재 성별: {current_gender}")
        except Exception as e:
            print(f"[Interactive] 성별 확인 중 오류: {e}, 기본값(girl) 사용")

        # 1. QuickSearch에서 10개의 프롬프트 리스트(이중 리스트) 추출
        candidates_double_list = self.quick_search_block.get_random_tags(10)

        # 태그 데이터 접근
        tags_data = getattr(self.autocomplete_manager, 'tags_data', {})

        valid_lists = []

        for tag_list in candidates_double_list:
            filtered_tags = []
            for tag in tag_list:
                # 태그 데이터 조회
                tag_data = tags_data.get(tag)

                # 태그가 DB에 없으면(Unknown) 일단 제외
                if not tag_data:
                    continue

                t_group = tag_data.get('group')
                t_subgroup = tag_data.get('subgroup')

                # 그룹 필터링
                if groups and t_group not in groups:
                    continue

                # 서브그룹 필터링
                if subgroups and t_group in subgroups:
                    allowed_subs = subgroups[t_group]
                    if t_subgroup not in allowed_subs:
                        continue

                # 🆕 Creatures 그룹 성별 기반 필터링
                if t_group == "Creatures":
                    tag_lower = tag.lower()

                    if current_gender in ["girl", "boy"]:
                        # girl 또는 boy 선택 시: girl, boy를 포함하는 태그만 허용
                        if "girl" not in tag_lower and "boy" not in tag_lower:
                            continue
                    elif current_gender == "other":
                        # other 선택 시: girl, boy가 없는 태그만 허용 (draph, erune, miqo'te 등)
                        if "girl" in tag_lower or "boy" in tag_lower:
                            continue

                filtered_tags.append(tag)

            # 필터링 후 남은 태그가 있다면 유효 리스트에 추가
            if filtered_tags:
                valid_lists.append(filtered_tags)

        # 2. 유효한 리스트 중 하나를 랜덤 선택하고, 해당 리스트의 모든 태그를 입력
        if valid_lists:
            import random
            chosen_list = random.choice(valid_lists)

            # 🆕 의상 필드의 경우 가중치 추가 (첫 태그 앞: 0.5::, 마지막 태그 뒤: ::)
            if self.current_mode == "NAI":
                if field_type == "attire" and chosen_list:
                    # 첫 태그에 0.5:: 추가
                    chosen_list[0] = f"0.5::{chosen_list[0]}"
                    # 마지막 태그에 :: 추가
                    chosen_list[-1] = f"{chosen_list[-1]} ::"

            # 선택된 리스트의 모든 태그를 문자열로 변환
            new_tags_str = ", ".join(chosen_list)

            # 텍스트 덮어쓰기 (기존 내용 제거)
            editor.setText(new_tags_str)

            # 스크롤 최하단으로 이동
            cursor = editor.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            editor.setTextCursor(cursor)

            print(f"[Interactive] ✅ 랜덤 태그 추가 성공 (필드: {field_type}, 성별: {current_gender}, 태그 수: {len(chosen_list)})")

            # 🆕 필드 타입에 따라 툴팁 표시 (마우스 왼쪽에)
            self._show_field_tooltip(field_type)
        else:
            print(f"[Interactive] ❌ 랜덤 태그 실패: 10번 시도했으나 조건(groups={groups}, gender={current_gender})을 만족하는 태그를 찾지 못했습니다.")

    def _show_field_tooltip(self, field_type):
        """필드 타입에 따라 툴팁 표시 (마우스 왼쪽, 2초간)"""
        from PyQt6.QtWidgets import QToolTip
        from PyQt6.QtGui import QCursor
        from PyQt6.QtCore import QTimer

        tooltip_text = ""

        if field_type == "pose":
            tooltip_text = (
                "캐릭터 프롬프트의 표정 / 행위를 명세한 경우,\n"
                "메인 프롬프트에는 충돌이 발생할 수 있는\n"
                "표정 또는 행위가 없어야 합니다.\n"
                "충돌 발생시 multiple view가 발생합니다."
            )
        elif field_type == "attire":
            tooltip_text = (
                "캐릭터의 의상이 표정 / 행위 필드 혹은\n"
                "메인 프롬프트와 일치하는지 확인해야합니다.\n"
                "충돌 발생시 multiple view가 발생합니다."
            )

        if tooltip_text:
            # 마우스 위치 가져오기
            cursor_pos = QCursor.pos()

            # 마우스 왼쪽에 툴팁 표시 (x - 10)
            tooltip_pos = cursor_pos
            tooltip_pos.setX(tooltip_pos.x() - 10)

            # 툴팁 표시 (2초간)
            QToolTip.showText(tooltip_pos, tooltip_text, None)

            # 2초 후 자동으로 툴팁 숨김
            QTimer.singleShot(2000, lambda: QToolTip.hideText())

    def _on_control_bar_random_generate(self):
        """컨트롤 바의 [랜덤+생성] 버튼 핸들러"""
        if hasattr(self, 'main_prompt_block'):
            print("[InteractiveWindow] Control Bar -> Random + Generate")
            # 1. 랜덤 프롬프트 생성 (동기 실행)
            self.main_prompt_block.generate_random_prompt()
            # 2. 생성 요청 (동기 실행 - 시그널 발생)
            self.main_prompt_block.trigger_generation()

    def _get_batch_resolution_override(self):
        """
        배치 처리 윈도우에서 해상도 오버라이드 값 가져오기

        Returns:
            tuple or None: (width, height) 또는 None
        """
        # Image Tagger Block의 batch_window 참조 확인
        if hasattr(self, 'image_tagger_block'):
            tagger_block = self.image_tagger_block
            if hasattr(tagger_block, 'batch_window'):
                batch_window = tagger_block.batch_window
                if batch_window and hasattr(batch_window, 'get_resolution_override'):
                    return batch_window.get_resolution_override()
        return None

    def collect_generation_params(self) -> dict:
        """
        모든 블록에서 파라미터를 수집하여 GenerationRequest용 딕셔너리 생성

        Returns:
            dict: APIService.call_generation_api()에 전달할 파라미터
        """
        from core.generation_request import GenerationRequest, NAICharacterData, NAICharacterReferenceData
        import pandas as pd

        # ===== NovelAI 프롬프트 조합 규칙 =====

        # 1. Person Tags 수집 및 분류 (인원수/rating 기억, solo 버림)
        person_tags_raw = self.person_block.get_tags()  # list: ["1girl", "rating:sensitive", "solo"]

        person_count_tags = []  # 인원수 태그 저장
        person_rating_tags = []  # rating 태그 저장

        count_patterns = ['girl', 'boy', 'other']  # 1girl, 2girls, 1boy, 2boys 등

        for tag in person_tags_raw:
            tag_lower = tag.lower().strip()

            # solo는 무시
            if tag_lower == 'solo':
                continue

            # rating 태그 저장
            if tag_lower.startswith('rating:') or tag_lower == 'nsfw':
                person_rating_tags.append(tag.strip())
                continue

            # 인원수 태그 저장
            is_count = False
            for pattern in count_patterns:
                if pattern in tag_lower:
                    person_count_tags.append(tag.strip())
                    is_count = True
                    break

            # no humans도 인원수로 간주
            if 'no humans' in tag_lower:
                person_count_tags.append(tag.strip())

        # 2. 아티스트 태그 수집 및 파싱
        artist_tags_str = self.artist_block.get_tags()  # str
        artist_tags_list = [t.strip() for t in artist_tags_str.split(',') if t.strip()]

        # 3. 구도/메타 태그 수집 및 파싱 (중요: 태그 목록 저장)
        composition_tags_str = self.composition_block.get_prompt_text()  # str
        composition_tags_list = [t.strip() for t in composition_tags_str.split(',') if t.strip()]
        composition_tags_set = set(tag.lower() for tag in composition_tags_list)  # 소문자로 저장 (필터링용)

        # 4. 메인 프롬프트 수집 및 파싱
        main_prompt_str = self.main_prompt_block.get_prompt()  # 이미 # 제거됨
        main_tags_raw = [t.strip() for t in main_prompt_str.split(',') if t.strip()]

        # Main Prompt에서 인원수 태그 추출
        main_count_tags = []
        main_other_tags = []

        for tag in main_tags_raw:
            tag_lower = tag.lower()

            # 인원수 태그 확인
            is_count = False
            for pattern in count_patterns:
                if pattern in tag_lower:
                    main_count_tags.append(tag)
                    is_count = True
                    break

            if 'no humans' in tag_lower:
                main_count_tags.append(tag)
                is_count = True

            if not is_count:
                main_other_tags.append(tag)

        # 5. 퀄리티 태그 수집 및 파싱
        quality_tags_str = self.quality_block.get_quality_tags()  # str
        quality_tags_list = [t.strip() for t in quality_tags_str.split(',') if t.strip()]

        # 6. 네거티브 프롬프트 수집
        negative_prompt = self.negative_block.get_negative_prompt()  # str
        additional_negative = self.additional_negative_block.get_prompt()  # str

        negative_parts = [negative_prompt, additional_negative]
        final_negative = ', '.join([p for p in negative_parts if p.strip()])

        # ===== 프롬프트 조합 시작 =====
        final_tags_list = []

        # STEP 1: 인원수 태그 (Main에 있으면 우선, 없으면 Person에서)
        if main_count_tags:
            final_tags_list.extend(main_count_tags)
        elif person_count_tags:
            final_tags_list.extend(person_count_tags)

        # STEP 2: Artist Tags 추가
        final_tags_list.extend(artist_tags_list)

        # STEP 3: Composition Tags 추가
        final_tags_list.extend(composition_tags_list)

        # STEP 4: Main Prompt의 나머지 태그 추가 (중복 제거 + composition 필터링)
        existing_tags_lower = set(tag.lower() for tag in final_tags_list)

        for tag in main_other_tags:
            tag_lower = tag.lower()

            # 중복 체크
            if tag_lower in existing_tags_lower:
                continue

            # Composition 필터링 (Composition Block에 태그가 있었다면)
            if composition_tags_list and tag_lower in composition_tags_set:
                continue

            final_tags_list.append(tag)
            existing_tags_lower.add(tag_lower)

        # STEP 5: Rating 적용 (이미 rating: 태그가 없으면)
        has_rating = any('rating:' in tag.lower() or tag.lower() == 'nsfw' for tag in final_tags_list)

        if not has_rating and person_rating_tags:
            final_tags_list.extend(person_rating_tags)

        # STEP 6: Quality Tags 추가 (마지막)
        final_tags_list.extend(quality_tags_list)

        # 최종 프롬프트 문자열 생성
        final_prompt = ', '.join(final_tags_list)

        # 8. 캐릭터 프롬프트 수집 (visible 블록만)
        character_prompts = []
        character_negatives = []
        character_names = []  # 🆕 캐릭터명 별도 수집 (ANIMA 모드용)

        for block, panel in zip(self.char_blocks, self.char_panels):
            if panel.isVisible():
                char_data = block.get_prompt_data()  # {"prompt": str, "negative": str}
                prompt = char_data.get('prompt', '').strip()
                if prompt and not (prompt == "girl" or prompt == "boy" or prompt == "other"):  # 빈 프롬프트 제외
                    character_prompts.append(prompt)
                    character_negatives.append(char_data.get('negative', ''))

                    # 🆕 캐릭터명 수집 (form.input_character_name)
                    if hasattr(block, 'form') and hasattr(block.form, 'input_character_name'):
                        char_name = block.form.input_character_name.text().strip()
                        character_names.append(char_name)
                    else:
                        character_names.append("")

        # 9. NAICharacterData 생성 (캐릭터가 있는 경우만)
        # COMFYUI 모드: 캐릭터 프롬프트를 메인 프롬프트에 합치고, 네거티브를 메인 네거티브에 합침
        nai_characters = None
        if self.current_mode == "COMFYUI":
            # COMFYUI 파라미터 패널에서 sampling_mode 확인
            panel_params = {}
            if hasattr(self, 'control_bar') and hasattr(self.control_bar, 'param_panel'):
                panel_params = self.control_bar.param_panel.get_params()

            is_anima_mode = panel_params.get('sampling_mode') == 'anima'

            if is_anima_mode:
                # 🎨 ANIMA 모드: 특별한 순서로 프롬프트 조합
                # 1. 퀄리티 태그
                quality_tags_str = self.quality_block.get_quality_tags()

                # 1.5 Rating 태그 자동 추가 (없는 경우)
                rating_keywords = ["safe", "sensitive", "nsfw", "explicit"]
                has_rating = any(keyword in quality_tags_str.lower() for keyword in rating_keywords)

                if not has_rating and person_rating_tags:
                    # person_rating_tags의 첫 번째 아이템 가져오기
                    first_rating = person_rating_tags[0].lower().strip()

                    # rating 태그 매핑
                    rating_map = {
                        'rating:general': 'safe',
                        'rating:sensitive': 'sensitive',
                        'rating:nsfw': 'nsfw',
                        'rating:explicit': 'explicit'
                    }

                    # 매핑된 태그 추가
                    if first_rating in rating_map:
                        rating_tag = rating_map[first_rating]
                        if quality_tags_str:
                            quality_tags_str = f"{quality_tags_str}, {rating_tag}"
                        else:
                            quality_tags_str = rating_tag
                        print(f"   ✨ Rating 태그 자동 추가: {rating_tag}")

                # 2. 메인 프롬프트에서 카테고리별 태그 추출
                categorized = self.main_prompt_block.get_categorized_tags()
                person_tags = categorized['person_tags']
                character_tags = categorized['character_tags']
                remaining_tags = categorized['remaining_tags']

                # 3. 캐릭터 프롬프트 블럭 내용 분리
                # character_prompts에서 캐릭터명과 특징 분리
                char_names_filtered = []  # 캐릭터명/작품명만 (비어있지 않은 것만)
                char_features = []  # 캐릭터 특징들 (body, pose, attire 등)

                for idx, char_prompt in enumerate(character_prompts):
                    # 해당 블록의 캐릭터명 가져오기
                    char_name = character_names[idx] if idx < len(character_names) else ""

                    # 프롬프트에서 태그 분리
                    tags = [tag.strip() for tag in char_prompt.split(',') if tag.strip()]

                    # 캐릭터명이 있으면 프롬프트에서 제거
                    if char_name:
                        char_names_filtered.append(char_name)
                        # 프롬프트에서 캐릭터명 제거
                        tags = [tag for tag in tags if tag.lower() != char_name.lower()]

                    # 'girl', 'boy', 'other' 제거 (NAI용 성별 태그)
                    tags = [tag for tag in tags if tag.lower() not in ('girl', 'boy', 'other')]

                    # 나머지는 특징들
                    char_features.extend(tags)

                char_prompt_combined = ', '.join(char_names_filtered) if char_names_filtered else ""
                char_features_str = ', '.join(char_features) if char_features else ""

                # character_tags에 캐릭터 특징 추가
                if char_features_str:
                    if character_tags:
                        character_tags = f"{char_features_str}, {character_tags}"
                    else:
                        character_tags = char_features_str

                # 4. 아티스트 태그
                artist_tags = self.artist_block.get_tags()

                # 5. 캐릭터 태그 (character_tags from main_prompt + 캐릭터 특징)
                # 6. 메인 프롬프트 (remaining_tags)

                # 최종 조합 (ANIMA 순서)
                anima_parts = [
                    quality_tags_str,    # 1. 퀄리티 태그
                    person_tags,         # 2. 인원 수
                    char_prompt_combined,# 3. 캐릭터명/작품명
                    artist_tags,         # 4. 아티스트 태그
                    character_tags,      # 5. 캐릭터 특징 + 캐릭터 태그
                    remaining_tags       # 6. 메인 프롬프트
                ]

                final_prompt = ', '.join([p for p in anima_parts if p.strip()])

                # 캐릭터 네거티브를 메인 네거티브 뒤에 추가
                char_negative_combined = ', '.join([n for n in character_negatives if n.strip()])
                if char_negative_combined:
                    if final_negative:
                        final_negative = f"{final_negative}, {char_negative_combined}"
                    else:
                        final_negative = char_negative_combined

                print(f"🎨 COMFYUI + ANIMA 모드: 특별한 순서로 프롬프트 조합 완료")
                print(f"   순서: 퀄리티 → 인원수 → 캐릭터블럭 → 아티스트 → 캐릭터태그 → 메인")
            else:
                # 기본 COMFYUI 모드 (EPS, V-Pred)
                if character_prompts:
                    # 캐릭터 프롬프트를 메인 프롬프트 뒤에 추가
                    char_prompt_combined = ', '.join(character_prompts)
                    if final_prompt:
                        final_prompt = f"{final_prompt}, {char_prompt_combined}"
                    else:
                        final_prompt = char_prompt_combined

                    # 캐릭터 네거티브를 메인 네거티브 뒤에 추가
                    char_negative_combined = ', '.join([n for n in character_negatives if n.strip()])
                    if char_negative_combined:
                        if final_negative:
                            final_negative = f"{final_negative}, {char_negative_combined}"
                        else:
                            final_negative = char_negative_combined

                    print(f"🎨 COMFYUI: 캐릭터 프롬프트 통합 완료 ({len(character_prompts)}개)")
        else:
            # NAI/WEBUI: 기존 방식 (NAICharacterData 사용)
            if character_prompts:
                nai_characters = NAICharacterData(
                    characters=character_prompts,
                    uc=character_negatives
                    # character_positions는 나중에 추가 (현재는 없음)
                )

        # 9.5 Character Reference 데이터 수집 및 변환
        nai_char_reference = None
        if hasattr(self, 'char_ref_block'):
            char_ref_simple = self.char_ref_block.get_data()  # CharacterReferenceData 객체 (간단한 형태)
            if char_ref_simple:
                # CharacterReferenceData를 NAICharacterReferenceData로 변환
                # (API 서비스가 요구하는 Director Tool 형식)

                # style_aware에 따라 정보 추출 모드 결정
                # 1 = character&style, 0 = character only
                ie_value = 1 if char_ref_simple.style_aware else 0

                nai_char_reference = NAICharacterReferenceData(
                    director_reference_descriptions=[{
                        "caption": {
                            "base_caption": "character&style" if char_ref_simple.style_aware else "character",
                            "char_captions": []
                        },
                        "legacy_uc": False
                    }],
                    director_reference_images=[char_ref_simple.image_base64],
                    director_reference_information_extracted=[ie_value],
                    director_reference_secondary_strength_values=[char_ref_simple.fidelity],
                    director_reference_strength_values=[1],  # 기본 강도
                    controlnet_strength=1,
                    inpaint_img2img_strength=1,
                    normalize_reference_strength_multiple=True
                )

        # 10. GenerationRequest 생성용 딕셔너리
        # source_row는 빈 Series로 생성 (Interactive Mode는 데이터베이스 기반이 아님)
        source_row = pd.Series(dtype=object)

        # 11. params 딕셔너리 구성 (APIService가 요구하는 기본 파라미터)
        # 배치 처리 윈도우에서 해상도 오버라이드 체크
        resolution_override = self._get_batch_resolution_override()
        if resolution_override:
            width, height = resolution_override
            print(f"[InteractiveWindow] 배치 윈도우 해상도 오버라이드 적용: {width}x{height}")
        else:
            width, height = self.control_bar.get_resolution()

        # 시드 값 가져오기
        seed = 0
        if hasattr(self, 'main_prompt_block') and hasattr(self.main_prompt_block, 'get_seed'):
            val = self.main_prompt_block.get_seed()
            if val != -1:
                seed = val
            else:
                import random
                seed = random.randint(0, 9999999999) # 랜덤 fallback

        # 파라미터 패널에서 생성 설정 가져오기
        panel_params = self.control_bar.param_panel.get_params()

        params = {
            'input': final_prompt,  # ✅ api_service는 'input' 키 사용
            'negative_prompt': final_negative,
            # 파라미터 패널에서 가져온 설정
            'model': panel_params.get('model', 'NAID4.5F'),
            'width': width,
            'height': height,
            'steps': panel_params.get('steps', 28),
            'cfg_scale': panel_params.get('cfg_scale', 5.0),
            'sampler': panel_params.get('sampler', 'k_euler_ancestral'),
            'seed': seed,  # 설정된 시드 사용
            'n_samples': 1,
            'ucPreset': 0,  # Heavy
            'qualityToggle': panel_params.get('VAR+', True),
            'sm': False,  # SMEA
            'sm_dyn': False,  # SMEA DYN
            'noise_schedule': panel_params.get('scheduler', 'karras'),
            'cfg_rescale': panel_params.get('cfg_rescale', 0.25),
        }

        # ComfyUI 모드 전용 파라미터 추가
        if self.current_mode == "COMFYUI":
            params['sampling_mode'] = panel_params.get('sampling_mode', 'eps')
            params['workflow_type'] = panel_params.get('workflow_type', 'checkpoint')
            print(f"🎨 ComfyUI 모드: sampling_mode={params['sampling_mode']}, workflow_type={params['workflow_type']}")

        # 12. GenerationRequest 객체 생성
        generation_request = GenerationRequest(
            params=params,
            source_row=source_row,
            nai_characters=nai_characters,
            nai_character_reference=nai_char_reference  # Character Reference 추가
        )

        # 13. APIService는 GenerationRequest 객체를 직접 받거나,
        #     params dict를 받을 수 있음. 여기서는 둘 다 반환
        return {
            'generation_request': generation_request,
            'params': params,  # 하위 호환성을 위해 포함
            'nai_characters': nai_characters,
            'nai_character_reference': nai_char_reference
        }

    def _on_generate_requested(self):
        """
        MainPromptBlock에서 이미지 생성 요청 시그널을 받아 처리
        (Assets Tab 패턴: GenerationController를 통한 비동기 생성)
        """
        if not self.app_context:
            print("[InteractiveWindow] app_context가 없어 이미지 생성을 실행할 수 없습니다.")
            return

        try:
            # [User Request] 생성 시 랜덤 시드 업데이트 (고정 안된 경우)
            if hasattr(self.main_prompt_block, 'update_random_seed'):
                self.main_prompt_block.update_random_seed()

            # [User Request] 현재 상태 저장 (save/interactive_data.json)
            self.save_interactive_data()

            # 1. 파라미터 수집
            gen_data = self.collect_generation_params()
            generation_request = gen_data['generation_request']

            # 2. override_params 준비 (GenerationController용)
            override_params = generation_request.params.copy()

            # Interactive Mode 전용 식별자 추가
            override_params['interactive_mode_request'] = True

            # NAI 캐릭터 데이터 또는 Character Reference 포함 시 GenerationRequest 전달
            if generation_request.nai_characters or generation_request.nai_character_reference:
                override_params['_generation_request'] = generation_request

            # 디버깅 로그
            print(f"[InteractiveWindow] 이미지 생성 요청:")
            print(f"  - Prompt: {override_params['input'][:100]}...")
            print(f"  - Negative: {override_params['negative_prompt'][:100]}...")
            if generation_request.nai_characters:
                print(f"  - Characters: {len(generation_request.nai_characters.characters)}명")
            if generation_request.nai_character_reference:
                print(f"  - Character Reference: 이미지 포함됨 (Fidelity: {generation_request.nai_character_reference.director_reference_secondary_strength_values[0]})")

            # 3. Interactive Mode 전용 이벤트 구독 (성공 + 에러 + 진행도)
            self.app_context.subscribe("generation_completed_for_interactive", self._on_generation_completed)
            self.app_context.subscribe("generation_error", self._on_generation_error)
            self.app_context.subscribe("generation_progress", self._on_generation_progress)

            # 4. 생성 버튼 비활성화 (MainPromptBlock)
            if hasattr(self.main_prompt_block, 'btn_generate'):
                self.main_prompt_block.btn_generate.setEnabled(False)
                self.main_prompt_block.btn_generate.setText("🔄 생성 중...")

            # 5. GenerationController의 execute_generation_pipeline 호출
            if hasattr(self.app_context, 'main_window'):
                gen_controller = self.app_context.main_window.generation_controller
                gen_controller.execute_generation_pipeline(overrides=override_params)
                print(f"🎨 Interactive Mode: 이미지 생성 시작")
            else:
                print("⚠️ generation_controller를 찾을 수 없습니다.")
                self._restore_generate_button()

        except Exception as e:
            print(f"[InteractiveWindow] 이미지 생성 중 오류: {e}")
            import traceback
            traceback.print_exc()
            self._restore_generate_button()

    def _on_generation_completed(self, result):
        """
        이미지 생성 완료 콜백 (비동기)

        Args:
            result: PIL Image 객체
        """
        try:
            # Interactive Mode 전용 구독 해제 (성공 + 에러 + 진행도)
            if "generation_completed_for_interactive" in self.app_context.subscribers:
                self.app_context.subscribers["generation_completed_for_interactive"].remove(self._on_generation_completed)
            if "generation_error" in self.app_context.subscribers:
                if self._on_generation_error in self.app_context.subscribers["generation_error"]:
                    self.app_context.subscribers["generation_error"].remove(self._on_generation_error)
            if "generation_progress" in self.app_context.subscribers:
                if self._on_generation_progress in self.app_context.subscribers["generation_progress"]:
                    self.app_context.subscribers["generation_progress"].remove(self._on_generation_progress)

            # result가 PIL Image인지 확인
            if hasattr(result, 'mode'):  # PIL Image 확인
                # ImagePlane에 이미지 표시
                if hasattr(self, 'image_plane'):
                    self.image_plane.set_image(result)
                    print("✅ Interactive Mode: 이미지 생성 완료 및 표시")
                else:
                    print("⚠️ ImagePlane을 찾을 수 없습니다.")

                # 생성 버튼 복원
                self._restore_generate_button()

                # 상태바 메시지
                if hasattr(self.app_context, 'main_window'):
                    self.app_context.main_window.status_bar.showMessage(
                        "✅ Interactive Mode: 이미지 생성 완료", 3000
                    )

                # 🆕 자동 반복 생성 로직
                if hasattr(self, 'main_prompt_block'):
                    if self.main_prompt_block.is_repeat_generation_enabled():
                        # 반복 생성: 0.5초 후 다시 생성
                        print("[InteractiveWindow] 반복 생성 활성화 → 0.5초 후 재생성")
                        QTimer.singleShot(500, self.main_prompt_block.trigger_generation)
                    elif self.main_prompt_block.is_auto_random_generation_enabled():
                        # 자동 랜덤생성: 0.5초 후 랜덤 프롬프트 + 생성
                        print("[InteractiveWindow] 자동 랜덤생성 활성화 → 0.5초 후 랜덤 + 생성")
                        QTimer.singleShot(500, self._on_control_bar_random_generate)

            else:
                print(f"⚠️ 예상과 다른 결과 타입: {type(result)}")
                self._restore_generate_button()

        except Exception as e:
            print(f"❌ 생성 완료 처리 중 오류: {e}")
            print(f"결과 타입: {type(result)}")
            import traceback
            traceback.print_exc()
            self._restore_generate_button()

    def _on_generation_progress(self, progress_data: dict):
        """
        이미지 생성 진행도 콜백 (ComfyUI 전용)

        Args:
            progress_data: 진행도 정보 {"current": int, "total": int, "percent": int}
        """
        try:
            percent = progress_data.get("percent", 0)

            # 생성 버튼 텍스트에 진행도 표시
            if hasattr(self.main_prompt_block, 'btn_generate'):
                self.main_prompt_block.btn_generate.setText(f"🔄 생성 중... {percent}%")

        except Exception as e:
            print(f"❌ 진행도 업데이트 중 오류: {e}")

    def _on_generation_error(self, error_data: dict):
        """
        이미지 생성 오류 콜백 (비동기)

        Args:
            error_data: 오류 정보 딕셔너리 {"message": str, "interactive_mode_request": bool}
        """
        try:
            # Interactive Mode 요청이 아니면 무시
            if not error_data.get("interactive_mode_request"):
                return

            error_message = error_data.get("message", "알 수 없는 오류가 발생했습니다.")
            print(f"❌ Interactive Mode 생성 오류: {error_message}")

            # Interactive Mode 전용 구독 해제 (성공 + 에러 + 진행도)
            if "generation_completed_for_interactive" in self.app_context.subscribers:
                if self._on_generation_completed in self.app_context.subscribers["generation_completed_for_interactive"]:
                    self.app_context.subscribers["generation_completed_for_interactive"].remove(self._on_generation_completed)
            if "generation_error" in self.app_context.subscribers:
                if self._on_generation_error in self.app_context.subscribers["generation_error"]:
                    self.app_context.subscribers["generation_error"].remove(self._on_generation_error)
            if "generation_progress" in self.app_context.subscribers:
                if self._on_generation_progress in self.app_context.subscribers["generation_progress"]:
                    self.app_context.subscribers["generation_progress"].remove(self._on_generation_progress)

            # 생성 버튼 복원
            self._restore_generate_button()

            # 사용자에게 에러 알림 (QMessageBox)
            from PyQt6.QtWidgets import QMessageBox
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("이미지 생성 실패")
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setText("이미지 생성 중 오류가 발생했습니다.")

            # 에러 메시지가 너무 길면 200자로 제한
            display_message = error_message if len(error_message) <= 200 else error_message[:200] + "..."
            msg_box.setInformativeText(display_message)

            # 전체 메시지를 상세 정보로 표시
            msg_box.setDetailedText(error_message)

            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg_box.exec()

            # 상태바 메시지
            if hasattr(self.app_context, 'main_window'):
                self.app_context.main_window.status_bar.showMessage(
                    "❌ Interactive Mode: 이미지 생성 실패", 5000
                )

        except Exception as e:
            print(f"❌ 에러 처리 중 오류: {e}")
            import traceback
            traceback.print_exc()
            # 최소한 버튼은 복원
            self._restore_generate_button()

    def _restore_generate_button(self):
        """생성 버튼을 원래 상태로 복원"""
        if hasattr(self, 'main_prompt_block') and hasattr(self.main_prompt_block, 'btn_generate'):
            self.main_prompt_block.btn_generate.setEnabled(True)
            self.main_prompt_block.btn_generate.setText("🎨 이미지 생성")

    def _on_mode_changed(self, data: dict):
        """
        API 모드 변경 시 호출됨 (NAI ↔ WEBUI ↔ COMFYUI)

        Args:
            data: {"old_mode": str, "new_mode": str}
        """
        old_mode = data.get("old_mode")
        new_mode = data.get("new_mode")

        print(f"[InteractiveWindow] 모드 변경 감지: {old_mode} → {new_mode}")

        # 1. 이전 모드 설정 저장
        if old_mode:
            self.save_interactive_data(mode=old_mode)
            print(f"✅ {old_mode} 모드 설정 저장 완료")

        # 2. 새 모드 설정 로드
        if new_mode:
            self.current_mode = new_mode
            self.load_interactive_data(mode=new_mode)
            print(f"✅ {new_mode} 모드 설정 로드 완료")

        # 3. 파라미터 패널 교체
        if hasattr(self, 'control_bar') and new_mode:
            self.control_bar.switch_parameter_panel(new_mode)
            print(f"✅ 파라미터 패널 교체 완료: {new_mode}")

    def _get_mode_filename(self, mode: str = None) -> str:
        """
        모드별 설정 파일 경로 반환

        Args:
            mode: API 모드 (NAI, WEBUI, COMFYUI). None이면 현재 모드 사용

        Returns:
            str: 설정 파일 경로
        """
        if mode is None:
            mode = self.current_mode

        save_dir = os.path.join(os.getcwd(), 'save')
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        # NAI 모드는 기존 파일명 유지 (호환성)
        if mode == "NAI":
            filename = 'interactive_data.json'
        else:
            filename = f'interactive_data_{mode}.json'

        return os.path.join(save_dir, filename)

    def save_interactive_data(self, mode: str = None):
        """
        현재 블록들의 텍스트와 파라미터를 JSON 파일로 저장 (모드별)

        Args:
            mode: API 모드 (NAI, WEBUI, COMFYUI). None이면 현재 모드 사용

        저장 대상:
        - ArtistTagBlock, QualityTagBlock, NegativePromptBlock, MainPromptBlock의 텍스트
        - ParameterPanel의 설정값
        """
        try:
            data = {}

            # 1. 텍스트 데이터 수집
            if hasattr(self, 'artist_block'):
                data['artist_tags'] = self.artist_block.get_tags()

            if hasattr(self, 'quality_block'):
                data['quality_tags'] = self.quality_block.get_quality_tags()

            if hasattr(self, 'negative_block'):
                data['negative_prompt'] = self.negative_block.get_negative_prompt()

            if hasattr(self, 'main_prompt_block'):
                # MainPromptBlock은 get_prompt()가 정제된 값을 반환하므로 raw text 사용
                if hasattr(self.main_prompt_block, 'text_edit'):
                    data['main_prompt'] = self.main_prompt_block.text_edit.toPlainText()

            # 2. 파라미터 데이터 수집
            if hasattr(self, 'control_bar') and hasattr(self.control_bar, 'param_panel'):
                data['parameters'] = self.control_bar.param_panel.get_params()

            # 🆕 모드별 저장 경로 사용
            save_path = self._get_mode_filename(mode)

            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)

            mode_name = mode if mode else self.current_mode
            print(f"[InteractiveWindow] {mode_name} 모드 데이터 저장됨: {save_path}")

        except Exception as e:
            print(f"[InteractiveWindow] 상태 데이터 저장 실패: {e}")

    def load_interactive_data(self, mode: str = None):
        """
        저장된 JSON 파일에서 상태를 읽어와 복원 (모드별)

        Args:
            mode: API 모드 (NAI, WEBUI, COMFYUI). None이면 현재 모드 사용
        """
        # 🆕 모드별 로드 경로 사용
        save_path = self._get_mode_filename(mode)
        mode_name = mode if mode else self.current_mode

        if not os.path.exists(save_path):
            print(f"[InteractiveWindow] {mode_name} 모드 데이터 파일 없음 (첫 실행 또는 초기화됨)")

            # COMFYUI 모드: 기본값 설정
            if mode_name == "COMFYUI":
                print(f"🎨 COMFYUI 모드 기본값 설정 중...")

                # 퀄리티 태그 기본값
                if hasattr(self, 'quality_block'):
                    self.quality_block.set_text("newest, year2024, year2025, masterpiece, best quality, score_7, highres")

                # 아티스트 태그 기본값
                if hasattr(self, 'artist_block'):
                    self.artist_block.set_text("(@nanatsuta:0.55), (@signalviolet:0.6)")

                # 네거티브 프롬프트 기본값
                if hasattr(self, 'negative_block'):
                    self.negative_block.set_text("worst quality, low quality, score_1, score_2, score_3, blurry, jpeg artifacts, sepia, mutated, bad hands, watermark, patreon username, web address, patreon logo, weibo username, watermark")

                print(f"✅ COMFYUI 모드 기본값 설정 완료")

            return

        try:
            with open(save_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 1. 텍스트 데이터 복원
            if 'artist_tags' in data and hasattr(self, 'artist_block'):
                self.artist_block.set_text(data['artist_tags'])

            if 'quality_tags' in data and hasattr(self, 'quality_block'):
                self.quality_block.set_text(data['quality_tags'])

            if 'negative_prompt' in data and hasattr(self, 'negative_block'):
                self.negative_block.set_text(data['negative_prompt'])

            if 'main_prompt' in data and hasattr(self, 'main_prompt_block'):
                # MainPromptBlock은 raw text 설정
                if hasattr(self.main_prompt_block, 'text_edit'):
                    self.main_prompt_block.text_edit.setPlainText(data['main_prompt'])
                    # HTML 포맷팅 이슈가 있을 수 있지만, 저장된 raw text를 그대로 복원

            # 2. 파라미터 데이터 복원
            if 'parameters' in data and hasattr(self, 'control_bar') and hasattr(self.control_bar, 'param_panel'):
                self.control_bar.param_panel.set_params(data['parameters'])

            mode_name = mode if mode else self.current_mode
            print(f"[InteractiveWindow] {mode_name} 모드 데이터 로드됨: {len(data)} 항목")

        except Exception as e:
            print(f"[InteractiveWindow] 상태 데이터 로드 실패: {e}")

