# ui/remote/batch_image_tab.py
"""
Batch Image Tagger Tab Mixin - RemoteWindow에서 사용하는 배치 이미지 태거

RemoteWindow의 원격 규칙:
- parent_app.on_generate_with_image_requested(source_row_dict) 사용
- parent_app.on_instant_generation_requested(source_row) 폴백
"""

import os
from typing import List, Optional
from pathlib import Path
from PIL import Image

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QProgressBar, QFrame, QRadioButton,
    QButtonGroup, QCheckBox, QScrollArea, QFileDialog, QTabWidget, QTextEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap

from ui.theme import DARK_COLORS, DARK_STYLES
from ui.scaling_manager import get_scaled_size, get_scaled_font_size
from ui.interactive.interactive_theme import get_button_style

# Tagger 관련 import
from ui.interactive.image_tagger_block import ThresholdButton, TaggerWorker

# 상수
BATCH_IMAGE_THUMB_WIDTH = 280
BATCH_IMAGE_THUMB_HEIGHT = 280


class BatchImageTabMixin:
    """배치 이미지 태거 탭 Mixin"""

    def _init_batch_image_data(self):
        """배치 이미지 탭 데이터 초기화"""
        self.batch_file_paths = []  # 현재 로드된 이미지 파일 경로
        self.batch_processing_queue = []  # 처리 대기 중인 아이템 인덱스
        self.batch_current_processing_index = None  # 현재 처리 중인 아이템 인덱스
        self.batch_item_widgets = []  # 아이템 위젯 리스트
        self.batch_threshold = 0.51  # Threshold 설정 (기본값)

        # 순차 생성 관련
        self.batch_sequential_generation_queue = []  # 순차 생성 대기 큐
        self.batch_current_generating_index = None  # 현재 생성 중인 아이템 인덱스
        self.batch_is_sequential_generating = False  # 순차 생성 진행 중 여부
        self.batch_resolution_mode = "aspect_ratio"  # "random", "aspect_ratio", "control_panel"
        self.batch_auto_remove_completed = False  # 생성 완료시 자동 삭제 여부
        self._batch_generation_callback_registered = False  # 이벤트 구독 상태 추적
        self._batch_item_resolutions = {}  # {index: (width, height)}
        self._batch_last_completed_index = None  # 마지막으로 완료 처리한 인덱스 (중복 이벤트 방지)

    def _create_batch_image_content_widget(self):
        """배치 이미지 태거 컨텐츠 위젯 생성 (탭 없이 위젯만 반환)"""
        batch_widget = QWidget()
        batch_layout = QVBoxLayout(batch_widget)
        batch_layout.setContentsMargins(8, 8, 8, 8)
        batch_layout.setSpacing(8)

        # === 상단 Row 1: 타이틀 + 파일 추가 버튼 ===
        title_row = QHBoxLayout()
        title_label = QLabel("🖼️ 배치 이미지 태거")
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['accent_blue']};
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
            }}
        """)
        title_row.addWidget(title_label)
        title_row.addStretch()

        # 파일 추가 버튼 (높이 증가, 너비 증가)
        add_files_btn = QPushButton("➕ 이미지 추가")
        add_files_btn.setStyleSheet(DARK_STYLES['primary_button'])
        add_files_btn.setFixedSize(get_scaled_size(190), get_scaled_size(40))
        add_files_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_files_btn.clicked.connect(self._on_batch_add_files)
        title_row.addWidget(add_files_btn)

        # 모두 제거 버튼
        clear_all_btn = QPushButton("🗑️ 모두 제거")
        clear_all_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['warning']};
                border: 1px solid {DARK_COLORS['warning']};
                border-radius: 4px;
                padding: 4px 12px;
                font-size: {get_scaled_font_size(12)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['warning']};
                color: {DARK_COLORS['bg_primary']};
            }}
        """)
        clear_all_btn.setFixedWidth(get_scaled_size(100))
        clear_all_btn.clicked.connect(self._on_batch_clear_all)
        title_row.addWidget(clear_all_btn)

        batch_layout.addLayout(title_row)

        # === 상단 Row 2: Threshold 설정 + 태그 추출 시작 버튼 ===
        settings_layout = QHBoxLayout()
        settings_layout.setSpacing(get_scaled_size(8))

        # Threshold 라벨
        lbl_th = QLabel("Threshold:")
        lbl_th.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(14)}px;")
        settings_layout.addWidget(lbl_th)

        # Threshold 버튼 그룹
        self.batch_threshold_group = QButtonGroup(self)
        self.batch_threshold_group.setExclusive(True)

        self.batch_btn_th_051 = ThresholdButton("0.51", 0.51)
        self.batch_btn_th_061 = ThresholdButton("0.61", 0.61)
        self.batch_btn_th_071 = ThresholdButton("0.71", 0.71)

        self.batch_threshold_group.addButton(self.batch_btn_th_051)
        self.batch_threshold_group.addButton(self.batch_btn_th_061)
        self.batch_threshold_group.addButton(self.batch_btn_th_071)

        # 기본 선택: 0.51
        self.batch_btn_th_051.setChecked(True)

        # Threshold 변경 시 값 업데이트
        self.batch_threshold_group.buttonClicked.connect(self._on_batch_threshold_changed)

        settings_layout.addWidget(self.batch_btn_th_051)
        settings_layout.addWidget(self.batch_btn_th_061)
        settings_layout.addWidget(self.batch_btn_th_071)

        settings_layout.addSpacing(get_scaled_size(20))

        # 이미지 개수 라벨
        self.batch_count_label = QLabel("이미지: 0개")
        self.batch_count_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(12)}px;")
        settings_layout.addWidget(self.batch_count_label)

        settings_layout.addStretch()

        # 태그 추출 시작 버튼
        self.batch_btn_start = QPushButton("⚡ 태그 추출 시작")
        self.batch_btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.batch_btn_start.setFixedHeight(get_scaled_size(36))
        self.batch_btn_start.setStyleSheet(get_button_style(bg_color=DARK_COLORS['accent_blue'], text_color="white"))
        self.batch_btn_start.clicked.connect(self._batch_start_processing)
        settings_layout.addWidget(self.batch_btn_start)

        batch_layout.addLayout(settings_layout)

        # === 중간: 이미지 그리드 (스크롤 영역) + 플레이스홀더 ===
        # 컨테이너 위젯 (그리드와 플레이스홀더를 전환하기 위함)
        self.batch_content_container = QWidget()
        content_container_layout = QVBoxLayout(self.batch_content_container)
        content_container_layout.setContentsMargins(0, 0, 0, 0)
        content_container_layout.setSpacing(0)

        # 스크롤 영역 (배치 모드)
        self.batch_scroll_area = QScrollArea()
        self.batch_scroll_area.setWidgetResizable(True)
        self.batch_scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 6px;
                background-color: {DARK_COLORS['bg_secondary']};
            }}
        """)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(8, 8, 8, 8)
        scroll_layout.setSpacing(16)

        # 그리드 레이아웃 (3열)
        self.batch_grid_layout = QGridLayout()
        self.batch_grid_layout.setSpacing(16)

        scroll_layout.addLayout(self.batch_grid_layout)
        scroll_layout.addStretch()

        self.batch_scroll_area.setWidget(scroll_content)

        # 플레이스홀더 위젯 (빈 공간 - 단일 이미지 분석 모드)
        self.batch_placeholder_widget = self._create_placeholder_widget()

        # 단일 이미지 분석 위젯 (초기에는 None, 필요 시 생성)
        self.batch_single_analysis_widget = None

        # 컨테이너에 추가
        content_container_layout.addWidget(self.batch_scroll_area)
        content_container_layout.addWidget(self.batch_placeholder_widget)

        batch_layout.addWidget(self.batch_content_container, 1)

        # 초기 상태: 플레이스홀더 표시
        self._update_batch_content_visibility()

        # === 하단: 순차 생성 섹션 ===
        self._init_batch_sequential_generation_section(batch_layout)

        return batch_widget

    def _create_batch_image_subtab(self, parent_tabs: QTabWidget):
        """배치 이미지 태거 서브탭 생성 (QTabWidget에 탭으로 추가)"""
        batch_widget = self._create_batch_image_content_widget()
        parent_tabs.addTab(batch_widget, "🖼️ 배치 태거")

    def _create_placeholder_widget(self):
        """빈 공간 플레이스홀더 위젯 생성"""
        placeholder = QWidget()
        placeholder_layout = QVBoxLayout(placeholder)
        placeholder_layout.setContentsMargins(0, 0, 0, 0)
        placeholder_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 중앙 컨텐츠
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setSpacing(get_scaled_size(20))
        center_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 안내 메시지
        msg_label = QLabel("단일 이미지 분석 시작하기")
        msg_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(18)}px;
                font-weight: bold;
            }}
        """)
        msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(msg_label)

        # 버튼 레이아웃
        button_layout = QHBoxLayout()
        button_layout.setSpacing(get_scaled_size(16))

        # 이미지 업로드 버튼
        upload_btn = QPushButton("📤 이미지 업로드")
        upload_btn.setStyleSheet(DARK_STYLES['primary_button'])
        upload_btn.setFixedSize(get_scaled_size(200), get_scaled_size(50))
        upload_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        upload_btn.clicked.connect(self._on_single_image_upload)
        button_layout.addWidget(upload_btn)

        # 클립보드 버튼
        clipboard_btn = QPushButton("📋 클립보드에서 이미지 복사")
        clipboard_btn.setStyleSheet(DARK_STYLES['primary_button'])
        clipboard_btn.setFixedSize(get_scaled_size(250), get_scaled_size(50))
        clipboard_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clipboard_btn.clicked.connect(self._on_single_image_from_clipboard)
        button_layout.addWidget(clipboard_btn)

        center_layout.addLayout(button_layout)

        placeholder_layout.addWidget(center_widget)

        return placeholder

    def _update_batch_content_visibility(self):
        """배치 컨텐츠 가시성 업데이트 (빈 공간 vs 그리드 vs 단일 분석)"""
        has_items = len(self.batch_item_widgets) > 0
        has_single_analysis = self.batch_single_analysis_widget is not None

        if has_single_analysis:
            # 단일 이미지 분석 모드
            self.batch_scroll_area.hide()
            self.batch_placeholder_widget.hide()
            if self.batch_single_analysis_widget:
                self.batch_single_analysis_widget.show()
        elif has_items:
            # 배치 모드
            self.batch_scroll_area.show()
            self.batch_placeholder_widget.hide()
            if self.batch_single_analysis_widget:
                self.batch_single_analysis_widget.hide()
        else:
            # 빈 공간 - 플레이스홀더 표시
            self.batch_scroll_area.hide()
            self.batch_placeholder_widget.show()
            if self.batch_single_analysis_widget:
                self.batch_single_analysis_widget.hide()

    def _on_single_image_upload(self):
        """단일 이미지 업로드 버튼 클릭"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "이미지 파일 선택",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp)"
        )

        if file_path:
            print(f"[BatchImage] 단일 이미지 업로드: {file_path}")
            self._show_single_image_analysis(file_path)

    def _on_single_image_from_clipboard(self):
        """클립보드에서 이미지 복사 버튼 클릭"""
        from PyQt6.QtWidgets import QApplication, QMessageBox
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()

        if mime_data.hasImage():
            # 클립보드에서 이미지 가져오기
            image = clipboard.image()
            if not image.isNull():
                # 임시 파일로 저장
                import tempfile
                temp_dir = tempfile.gettempdir()
                temp_path = os.path.join(temp_dir, "clipboard_image.png")
                image.save(temp_path, "PNG")
                print(f"[BatchImage] 클립보드에서 이미지 복사: {temp_path}")
                self._show_single_image_analysis(temp_path, from_clipboard=True)
            else:
                QMessageBox.warning(self, "알림", "클립보드에 유효한 이미지가 없습니다.")
        else:
            QMessageBox.warning(self, "알림", "클립보드에 이미지가 없습니다.")

    def _show_single_image_analysis(self, image_path: str, from_clipboard: bool = False):
        """단일 이미지 분석 위젯 표시"""
        print(f"[BatchImage] 단일 이미지 분석 시작: {image_path}")

        # 단일 분석 위젯이 없으면 생성
        if self.batch_single_analysis_widget is None:
            self.batch_single_analysis_widget = self._create_single_analysis_widget()
            # 컨테이너에 추가
            self.batch_content_container.layout().addWidget(self.batch_single_analysis_widget)

        # 이미지 로드 및 표시
        self._load_single_image(image_path, from_clipboard)

        # 가시성 업데이트
        self._update_batch_content_visibility()

        # WD14 자동 추출 시작
        self._start_single_image_extraction(image_path)

    def _init_batch_sequential_generation_section(self, parent_layout):
        """순차 생성 섹션 초기화"""
        section_frame = QFrame()
        section_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 8px;
            }}
        """)

        section_layout = QVBoxLayout(section_frame)
        section_layout.setContentsMargins(16, 12, 16, 12)
        section_layout.setSpacing(12)

        # 제목 + 상태 라벨
        header_layout = QHBoxLayout()
        title_label = QLabel("🎬 순차 생성")
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
            }}
        """)
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        # 진행 상태 라벨
        self.batch_lbl_generation_status = QLabel("")
        self.batch_lbl_generation_status.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(13)}px;
            }}
        """)
        header_layout.addWidget(self.batch_lbl_generation_status)

        section_layout.addLayout(header_layout)

        # 해상도 옵션
        resolution_layout = QHBoxLayout()
        resolution_layout.setSpacing(get_scaled_size(16))

        res_label = QLabel("해상도:")
        res_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(14)}px;")
        resolution_layout.addWidget(res_label)

        self.batch_resolution_group = QButtonGroup(self)
        self.batch_resolution_group.setExclusive(True)

        # 이미지 비율 적용 (기본값)
        self.batch_radio_aspect = QRadioButton("이미지 비율")
        self.batch_radio_aspect.setChecked(True)
        self.batch_radio_aspect.setStyleSheet(f"""
            QRadioButton {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
            }}
            QRadioButton::indicator {{
                width: {get_scaled_size(18)}px;
                height: {get_scaled_size(18)}px;
            }}
        """)
        self.batch_resolution_group.addButton(self.batch_radio_aspect)
        resolution_layout.addWidget(self.batch_radio_aspect)

        # 랜덤으로
        self.batch_radio_random = QRadioButton("랜덤")
        self.batch_radio_random.setStyleSheet(f"""
            QRadioButton {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
            }}
            QRadioButton::indicator {{
                width: {get_scaled_size(18)}px;
                height: {get_scaled_size(18)}px;
            }}
        """)
        self.batch_resolution_group.addButton(self.batch_radio_random)
        resolution_layout.addWidget(self.batch_radio_random)

        # 기본 설정 옵션 적용
        self.batch_radio_control_panel = QRadioButton("기본 설정을 따름")
        self.batch_radio_control_panel.setStyleSheet(f"""
            QRadioButton {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
            }}
            QRadioButton::indicator {{
                width: {get_scaled_size(18)}px;
                height: {get_scaled_size(18)}px;
            }}
        """)
        self.batch_resolution_group.addButton(self.batch_radio_control_panel)
        resolution_layout.addWidget(self.batch_radio_control_panel)

        # 라디오 버튼 변경 시 값 업데이트
        self.batch_resolution_group.buttonClicked.connect(self._on_batch_resolution_mode_changed)

        resolution_layout.addStretch()
        section_layout.addLayout(resolution_layout)

        # 옵션 체크박스
        options_layout = QHBoxLayout()
        options_layout.setSpacing(get_scaled_size(16))

        # 자동 삭제 체크박스
        self.batch_chk_auto_remove = QCheckBox("생성 완료시 목록에서 삭제")
        self.batch_chk_auto_remove.setStyleSheet(f"""
            QCheckBox {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
            }}
            QCheckBox::indicator {{
                width: {get_scaled_size(18)}px;
                height: {get_scaled_size(18)}px;
            }}
        """)
        self.batch_chk_auto_remove.stateChanged.connect(self._on_batch_auto_remove_changed)
        options_layout.addWidget(self.batch_chk_auto_remove)

        options_layout.addStretch()
        section_layout.addLayout(options_layout)

        # 순차 생성 버튼들
        button_layout = QHBoxLayout()
        button_layout.setSpacing(get_scaled_size(12))
        button_layout.addStretch()

        self.batch_btn_sequential_start = QPushButton("🎬 순차 생성 시작")
        self.batch_btn_sequential_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.batch_btn_sequential_start.setFixedHeight(get_scaled_size(40))
        self.batch_btn_sequential_start.setFixedWidth(get_scaled_size(160))
        self.batch_btn_sequential_start.setStyleSheet(get_button_style(bg_color=DARK_COLORS['accent_blue'], text_color="white"))
        self.batch_btn_sequential_start.clicked.connect(self._batch_start_sequential_generation)
        button_layout.addWidget(self.batch_btn_sequential_start)

        # 취소 버튼 (생성 중일 때만 표시)
        self.batch_btn_sequential_cancel = QPushButton("⏹ 취소")
        self.batch_btn_sequential_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.batch_btn_sequential_cancel.setFixedHeight(get_scaled_size(40))
        self.batch_btn_sequential_cancel.setFixedWidth(get_scaled_size(100))
        self.batch_btn_sequential_cancel.setStyleSheet(get_button_style(bg_color=DARK_COLORS['error'], text_color="white"))
        self.batch_btn_sequential_cancel.clicked.connect(self._batch_cancel_sequential_generation)
        self.batch_btn_sequential_cancel.hide()  # 초기에는 숨김
        button_layout.addWidget(self.batch_btn_sequential_cancel)

        button_layout.addStretch()
        section_layout.addLayout(button_layout)

        parent_layout.addWidget(section_frame)

    # === 이벤트 핸들러 ===

    def _on_batch_add_files(self):
        """파일 추가 버튼 클릭"""
        file_dialog = QFileDialog(self)
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        file_dialog.setNameFilter("Images (*.png *.jpg *.jpeg *.webp *.bmp)")

        if file_dialog.exec():
            selected_files = file_dialog.selectedFiles()
            if selected_files:
                self._batch_add_images(selected_files)

    def _batch_add_images(self, file_paths: List[str]):
        """이미지 파일들을 그리드에 추가"""
        print(f"[BatchImage] 이미지 추가: {len(file_paths)}개")

        for file_path in file_paths:
            # 중복 체크
            if file_path in self.batch_file_paths:
                print(f"[BatchImage] 중복 스킵: {file_path}")
                continue

            # 인덱스 생성
            index = len(self.batch_file_paths)
            self.batch_file_paths.append(file_path)

            # Quick Search 블록 참조 가져오기
            quick_search_block = None
            if hasattr(self, 'qs_tag_to_id'):
                # QuickSearchTabMixin의 데이터를 사용할 수 있도록 임시 객체 생성
                class QuickSearchBlockStub:
                    def __init__(self, tag_to_id):
                        self.tag_to_id = tag_to_id
                quick_search_block = QuickSearchBlockStub(self.qs_tag_to_id)

            # 아이템 위젯 생성
            item_widget = BatchImageItem(file_path, index, quick_search_block)
            # extraction_requested 시그널은 사용하지 않음 (btn_extract는 직접 start_extraction 호출)
            item_widget.generation_requested.connect(lambda idx=index: self._on_batch_generation_requested(idx))
            item_widget.view_requested.connect(lambda idx=index: self._on_batch_view_requested(idx))
            item_widget.close_requested.connect(self._on_batch_item_close_requested)

            # 3열 그리드 배치
            row = index // 3
            col = index % 3
            self.batch_grid_layout.addWidget(item_widget, row, col)

            self.batch_item_widgets.append(item_widget)
            # 주의: batch_processing_queue에는 추가하지 않음
            # (배치 추출 시작 버튼을 눌렀을 때만 큐에 추가됨)

        # 개수 라벨 업데이트
        self.batch_count_label.setText(f"이미지: {len(self.batch_file_paths)}개")

        # 가시성 업데이트 (배치 모드로 전환)
        self._update_batch_content_visibility()

    def _on_batch_clear_all(self):
        """모두 제거 버튼 클릭"""
        if not self.batch_item_widgets:
            return

        # 확인 다이얼로그
        if not self._show_question("확인", "모든 이미지를 제거하시겠습니까?"):
            return

        # 모든 아이템 제거
        for item in self.batch_item_widgets:
            if item:
                self.batch_grid_layout.removeWidget(item)
                item.setParent(None)
                item.deleteLater()

        # 데이터 초기화
        self.batch_file_paths.clear()
        self.batch_item_widgets.clear()
        self.batch_processing_queue.clear()
        self.batch_sequential_generation_queue.clear()
        self.batch_current_processing_index = None
        self.batch_current_generating_index = None
        self._batch_item_resolutions.clear()

        # 개수 라벨 업데이트
        self.batch_count_label.setText("이미지: 0개")

        # 가시성 업데이트 (플레이스홀더로 복귀)
        self._update_batch_content_visibility()

        print("[BatchImage] 모든 이미지 제거 완료")

    def _on_batch_threshold_changed(self):
        """Threshold 버튼 변경 시 값 업데이트"""
        checked_button = self.batch_threshold_group.checkedButton()
        if checked_button and hasattr(checked_button, 'value'):
            self.batch_threshold = checked_button.value
            print(f"[BatchImage] Threshold 변경: {self.batch_threshold}")

    def _on_batch_resolution_mode_changed(self):
        """해상도 모드 변경"""
        if self.batch_radio_aspect.isChecked():
            self.batch_resolution_mode = "aspect_ratio"
        elif self.batch_radio_random.isChecked():
            self.batch_resolution_mode = "random"
        elif self.batch_radio_control_panel.isChecked():
            self.batch_resolution_mode = "control_panel"
        print(f"[BatchImage] 해상도 모드 변경: {self.batch_resolution_mode}")

    def _on_batch_auto_remove_changed(self, state):
        """자동 삭제 체크박스 변경"""
        self.batch_auto_remove_completed = (state == Qt.CheckState.Checked.value)
        print(f"[BatchImage] 자동 삭제: {'ON' if self.batch_auto_remove_completed else 'OFF'}")

    def _batch_start_processing(self):
        """태그 추출 시작 버튼 클릭 - 모든 아이템을 큐에 추가하고 순차 처리"""
        if not self.batch_item_widgets:
            self._show_warning("알림", "추가된 이미지가 없습니다.")
            return

        print(f"[BatchImage] 배치 처리 시작 (Threshold: {self.batch_threshold})")

        # 큐 초기화 및 모든 아이템 추가
        self.batch_processing_queue.clear()
        for i in range(len(self.batch_item_widgets)):
            if self.batch_item_widgets[i] is not None:
                self.batch_processing_queue.append(i)

        print(f"[BatchImage] 처리 큐: {len(self.batch_processing_queue)}개 아이템")

        self.batch_btn_start.setEnabled(False)
        self.batch_btn_start.setText("처리 중...")
        self._batch_process_next()

    def _batch_process_next(self):
        """큐에서 다음 아이템 처리"""
        if not self.batch_processing_queue:
            print("[BatchImage] 모든 이미지 처리 완료")
            # 모든 처리 완료 시 시작 버튼 다시 활성화
            self.batch_btn_start.setEnabled(True)
            self.batch_btn_start.setText("⚡ 태그 추출 시작")
            return

        # 큐에서 첫 번째 아이템 가져오기
        next_index = self.batch_processing_queue[0]
        self.batch_current_processing_index = next_index

        # 해당 아이템의 추출 시작 (None 체크)
        item = self.batch_item_widgets[next_index]
        if item:
            item.start_extraction(self.batch_threshold)
        else:
            # 아이템이 제거된 경우 스킵
            print(f"[BatchImage] 아이템 {next_index}가 제거되어 스킵")
            if next_index in self.batch_processing_queue:
                self.batch_processing_queue.remove(next_index)
            self._batch_process_next()

    def _on_batch_extraction_completed(self, index: int, tags: str):
        """아이템 추출 완료 시 호출 (개별 추출 또는 배치 추출 모두)"""
        print(f"[BatchImage] 아이템 {index} 추출 완료: {len(tags.split(','))}개 태그")

        # 큐에 있는 아이템인지 확인 (배치 처리 중인 경우)
        was_in_queue = index in self.batch_processing_queue

        # 큐에서 제거
        if was_in_queue:
            self.batch_processing_queue.remove(index)
            # 배치 처리 중일 때만 다음 아이템 처리
            self._batch_process_next()
            print(f"[BatchImage] 배치 처리: 다음 아이템으로 진행")
        else:
            # 개별 추출인 경우 - 다음 아이템 처리하지 않음
            print(f"[BatchImage] 개별 추출 완료 (큐와 무관)")

    def _on_batch_extraction_requested(self, index: int):
        """
        [미사용] 추출된 태그를 메인 프롬프트로 전송 (생성하지 않음)

        주의: 현재 extraction_requested 시그널이 emit되지 않아 호출되지 않습니다.
        개별 아이템의 btn_extract는 직접 start_extraction()을 호출합니다.
        """
        print(f"[BatchImage] 아이템 {index} 메인 프롬프트로 전송 요청")

        # None 체크
        if index >= len(self.batch_item_widgets) or self.batch_item_widgets[index] is None:
            return

        item = self.batch_item_widgets[index]
        if not item.extracted_tags:
            print(f"[BatchImage] 아이템 {index} 추출된 태그가 없습니다")
            return

        # RemoteWindow 규칙: parent_app을 통해 메인 UI에 태그 전송
        if self.parent_app:
            # source_row_dict 생성
            source_row_dict = {
                'prompt': item.extracted_tags,
                'general_tags': item.extracted_tags,
                'prefix_tags': '',
                'postfix_tags': '',
            }

            # 메인 UI에 프롬프트만 전송 (생성은 하지 않음)
            if hasattr(self.parent_app, 'on_instant_generation_requested'):
                import pandas as pd
                source_row = pd.Series(source_row_dict)
                self.parent_app.on_instant_generation_requested(source_row)
                print(f"[BatchImage] 메인 프롬프트 업데이트 완료: {len(item.extracted_tags.split(','))}개 태그")
            else:
                print("[BatchImage] ❌ parent_app에 on_instant_generation_requested 메서드가 없습니다")
        else:
            print("[BatchImage] ❌ parent_app이 연결되지 않았습니다")

    def _on_batch_generation_requested(self, index: int):
        """생성 버튼 클릭: 태그를 메인 프롬프트로 전송하고 이미지 생성"""
        print(f"[BatchImage] 아이템 {index} 생성 요청")

        # None 체크
        if index >= len(self.batch_item_widgets) or self.batch_item_widgets[index] is None:
            return

        item = self.batch_item_widgets[index]
        if not item.extracted_tags:
            print(f"[BatchImage] 아이템 {index} 추출된 태그가 없습니다")
            return

        # RemoteWindow 규칙: parent_app을 통해 생성 요청
        if self.parent_app:
            # source_row_dict 생성 (Quick Search/Event 탭과 동일한 구조)
            source_row_dict = {
                'general': item.extracted_tags,
                'rating': 'g',  # 기본 rating
                'character': '',
                'artist': '',
                'copyright': '',
                'meta': '',
                'quality': '',
            }

            # 메인 UI에 생성 요청
            if hasattr(self.parent_app, 'on_generate_with_image_requested'):
                self.parent_app.on_generate_with_image_requested(source_row_dict)
                print(f"[BatchImage] 생성 요청 완료: {len(item.extracted_tags.split(','))}개 태그")
            elif hasattr(self.parent_app, 'on_instant_generation_requested'):
                import pandas as pd
                source_row = pd.Series(source_row_dict)
                self.parent_app.on_instant_generation_requested(source_row)
                print(f"[BatchImage] 생성 요청 완료 (폴백): {len(item.extracted_tags.split(','))}개 태그")
            else:
                print("[BatchImage] ❌ parent_app에 생성 메서드가 없습니다")
        else:
            print("[BatchImage] ❌ parent_app이 연결되지 않았습니다")

    def _on_batch_view_requested(self, index: int):
        """보기 버튼 클릭: 추출된 프롬프트를 팝업으로 표시"""
        print(f"[BatchImage] 아이템 {index} 프롬프트 보기 요청")

        # None 체크
        if index >= len(self.batch_item_widgets) or self.batch_item_widgets[index] is None:
            return

        item = self.batch_item_widgets[index]

        # 추출된 태그가 없으면 경고
        if not item.extracted_tags:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "알림", "추출된 태그가 없습니다.")
            return

        # 프롬프트 뷰어 다이얼로그 생성
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton
        from PyQt6.QtCore import Qt

        dialog = QDialog(self)
        dialog.setWindowTitle(f"추출된 프롬프트 - {os.path.basename(item.file_path)}")
        dialog.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)
        dialog.resize(get_scaled_size(800), get_scaled_size(600))

        layout = QVBoxLayout(dialog)

        # 파일명 라벨
        from PyQt6.QtWidgets import QLabel
        filename_label = QLabel(f"📄 {os.path.basename(item.file_path)}")
        filename_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
                padding: 8px;
            }}
        """)
        layout.addWidget(filename_label)

        # 태그 개수 라벨
        tag_count = len(item.extracted_tags.split(',')) if item.extracted_tags else 0
        count_label = QLabel(f"총 {tag_count}개 태그")
        count_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(12)}px;
                padding: 0px 8px 8px 8px;
            }}
        """)
        layout.addWidget(count_label)

        # 프롬프트 텍스트 에디트
        prompt_edit = QTextEdit()
        prompt_edit.setPlainText(item.extracted_tags)
        prompt_edit.setReadOnly(True)
        prompt_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 6px;
                padding: 12px;
                font-size: {get_scaled_font_size(17)}px;
                font-family: 'Consolas', 'Monaco', monospace;
            }}
        """)
        layout.addWidget(prompt_edit, 1)

        # 하단 버튼 영역
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        # 복사 버튼
        copy_btn = QPushButton("📋 클립보드에 복사")
        copy_btn.setStyleSheet(DARK_STYLES['primary_button'])
        copy_btn.setFixedHeight(get_scaled_size(36))
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        def copy_to_clipboard():
            from PyQt6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            clipboard.setText(item.extracted_tags)
            copy_btn.setText("✅ 복사 완료!")
            QTimer.singleShot(1500, lambda: copy_btn.setText("📋 클립보드에 복사"))

        copy_btn.clicked.connect(copy_to_clipboard)
        button_layout.addWidget(copy_btn)

        # 닫기 버튼
        close_btn = QPushButton("닫기")
        close_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        close_btn.setFixedHeight(get_scaled_size(36))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(dialog.accept)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

        dialog.exec()

    def _on_batch_item_close_requested(self, index: int):
        """아이템 닫기 요청"""
        print(f"[BatchImage] 아이템 {index} 닫기 요청")

        # 위젯 가져오기 (None 체크)
        if index >= len(self.batch_item_widgets) or self.batch_item_widgets[index] is None:
            print(f"[BatchImage] 아이템 {index}가 이미 제거되었거나 존재하지 않음")
            return

        item = self.batch_item_widgets[index]

        # 그리드에서 제거
        self.batch_grid_layout.removeWidget(item)
        item.setParent(None)
        item.deleteLater()

        # 리스트에서 제거 (None으로 표시)
        self.batch_item_widgets[index] = None

        # 처리 큐에서 제거
        if index in self.batch_processing_queue:
            self.batch_processing_queue.remove(index)

        # 순차 생성 큐에서도 제거
        if index in self.batch_sequential_generation_queue:
            self.batch_sequential_generation_queue.remove(index)

        # 현재 처리 중인 아이템이면 다음으로 진행
        if self.batch_current_processing_index == index:
            self.batch_current_processing_index = None
            self._batch_process_next()

        # ⚠️ 현재 생성 중인 아이템이면 batch_current_generating_index를 유지
        # (중복 이벤트 필터링에 필요, 다음 아이템 생성은 _on_batch_generation_completed에서 자동 처리)
        if self.batch_current_generating_index == index:
            print(f"[BatchImage] 현재 생성 중인 아이템 {index} 제거됨 (인덱스는 유지하여 중복 이벤트 방지)")

        # 개수 라벨 업데이트
        remaining_count = sum(1 for item in self.batch_item_widgets if item is not None)
        self.batch_count_label.setText(f"이미지: {remaining_count}개")

        print(f"[BatchImage] 아이템 {index} 제거 완료")

    # === 순차 생성 관련 메서드 ===

    def _batch_start_sequential_generation(self):
        """순차 생성 시작 - 첫 번째 아이템만 요청, 나머지는 완료 시그널 받을 때마다 순차 처리"""
        print(f"[BatchImage] 순차 생성 시작 (해상도 모드: {self.batch_resolution_mode})")

        # ⚠️ 메인 앱이 현재 생성 중인지 확인
        if self.parent_app and hasattr(self.parent_app, 'generation_controller'):
            gc = self.parent_app.generation_controller
            if hasattr(gc, 'is_generating') and gc.is_generating:
                print("[BatchImage] ❌ 메인 앱이 현재 생성 중입니다")
                self._show_warning("알림", "현재 이미지 생성이 진행 중입니다.\n완료 후 다시 시도해주세요.")
                return

        # 기존 상태 초기화 (다시 눌렀을 때)
        self.batch_sequential_generation_queue.clear()
        self.batch_current_generating_index = None
        self._batch_item_resolutions.clear()
        self._batch_last_completed_index = None  # 중복 이벤트 필터링 초기화

        # 태그 추출이 완료된 아이템들만 찾기
        items_to_generate = []
        for i, item in enumerate(self.batch_item_widgets):
            if item and item.extracted_tags:
                items_to_generate.append((i, item))
                self.batch_sequential_generation_queue.append(i)

        if not items_to_generate:
            print("[BatchImage] 순차 생성할 아이템이 없습니다 (태그 추출 완료된 아이템 없음)")
            self._show_warning("알림", "태그가 추출된 이미지가 없습니다.\n먼저 태그 추출을 완료해주세요.")
            return

        print(f"[BatchImage] 순차 생성 큐: {len(items_to_generate)}개 아이템")

        # 순차 생성 플래그 설정
        self.batch_is_sequential_generating = True

        # 버튼 상태 변경
        self.batch_btn_sequential_start.setEnabled(False)
        self.batch_btn_sequential_start.setText("⏳ 생성 중...")
        self.batch_btn_sequential_start.hide()  # 시작 버튼 숨김
        self.batch_btn_sequential_cancel.show()  # 취소 버튼 표시

        # 상태 라벨 업데이트
        total_count = len(items_to_generate)
        self.batch_lbl_generation_status.setText(f"⏳ 0/{total_count} 완료 (대기: {total_count}개)")

        # 생성 완료 이벤트 구독 (최초 1회만)
        if self.parent_app and hasattr(self.parent_app, 'app_context') and not self._batch_generation_callback_registered:
            try:
                app_context = self.parent_app.app_context
                app_context.subscribe("generation_completed_for_redirect", self._on_batch_generation_completed)
                self._batch_generation_callback_registered = True
                print("[BatchImage] ✅ 생성 완료 이벤트 구독 성공")
            except Exception as e:
                print(f"[BatchImage] ❌ 이벤트 구독 실패: {e}")

        # 모든 아이템의 해상도 미리 계산 및 UI 상태 설정
        for idx, item in items_to_generate:
            # 해상도 설정
            if self.batch_resolution_mode == "aspect_ratio":
                resolution = self._batch_calculate_resolution_from_aspect_ratio(item.file_path)
            elif self.batch_resolution_mode == "random":
                resolution = self._batch_get_random_resolution()
            else:  # control_panel
                resolution = None

            # 해상도 저장 (딕셔너리에 저장)
            self._batch_item_resolutions[idx] = resolution  # None도 저장 (control_panel 모드)

            # 아이템 상태 표시 (모두 대기 상태로)
            item.btn_waiting.setText("⏳ 대기 중...")
            item.btn_waiting.show()
            item.btn_extract.hide()
            item.btn_generate.hide()
            item.btn_view.hide()

        # 🎯 첫 번째 아이템만 생성 요청 (나머지는 완료 시그널 받을 때마다 하나씩)
        if self.batch_sequential_generation_queue:
            first_idx = self.batch_sequential_generation_queue[0]
            first_item = self.batch_item_widgets[first_idx]
            first_resolution = self._batch_item_resolutions.get(first_idx)

            # ⚠️ batch_current_generating_index는 _batch_trigger_single_generation 내부에서 설정됨
            print(f"[BatchImage] 🎬 첫 번째 아이템 {first_idx} 생성 시작")

            # 첫 번째 아이템 생성 트리거 (내부에서 batch_current_generating_index 업데이트됨)
            self._batch_trigger_single_generation(first_idx, first_item, first_resolution)

    def _batch_trigger_single_generation(self, idx: int, item, resolution):
        """단일 아이템 생성 트리거 (QTimer 콜백용)"""
        print(f"[BatchImage] 🎬 아이템 {idx} 생성 트리거 (해상도: {resolution})")

        if not self.parent_app:
            print("[BatchImage] ❌ parent_app이 연결되지 않았습니다")
            return

        # ⚠️ 순차 생성이 취소되었는지 확인
        if not self.batch_is_sequential_generating:
            print(f"[BatchImage] ❌ 순차 생성이 취소됨 - 아이템 {idx} 생성 중단")
            return

        # ⚠️ 메인 앱이 현재 생성 중인지 확인 (큐에 들어가지 않도록)
        if hasattr(self.parent_app, 'generation_controller'):
            gc = self.parent_app.generation_controller
            if hasattr(gc, 'is_generating') and gc.is_generating:
                # 생성 중이면 500ms 후 재시도 (순차 생성이 여전히 활성화된 경우)
                print(f"[BatchImage] ⏸️ 메인 앱이 생성 중이므로 500ms 후 재시도")
                QTimer.singleShot(500, lambda: self._batch_trigger_single_generation(idx, item, resolution))
                return

        # 🔑 현재 생성 인덱스 설정
        self.batch_current_generating_index = idx

        # source_row_dict 생성 (Quick Search/Event 탭과 동일한 구조)
        source_row_dict = {
            'general': item.extracted_tags,
            'rating': 'g',  # 기본 rating
            'character': '',
            'artist': '',
            'copyright': '',
            'meta': '',
            'quality': '',
        }

        # 해상도 오버라이드 설정 (메인 앱에서 파라미터 수집 시 사용)
        # ⚠️ 주의: RemoteWindow에서는 해상도 오버라이드를 직접 설정할 수 없으므로
        # source_row_dict에 해상도 정보를 포함시키거나, 별도 메커니즘 필요
        # 현재는 생성 요청만 수행 (해상도는 메인 UI 설정 사용)

        # 메인 UI에 생성 요청
        if hasattr(self.parent_app, 'on_generate_with_image_requested'):
            self.parent_app.on_generate_with_image_requested(source_row_dict)
            print(f"[BatchImage] ✅ 아이템 {idx} 생성 요청 완료")
        elif hasattr(self.parent_app, 'on_instant_generation_requested'):
            import pandas as pd
            source_row = pd.Series(source_row_dict)
            self.parent_app.on_instant_generation_requested(source_row)
            QTimer.singleShot(100, self.parent_app.generation_controller.execute_generation_pipeline)
            print(f"[BatchImage] ✅ 아이템 {idx} 생성 요청 완료 (폴백)")
        else:
            print("[BatchImage] ❌ parent_app에 생성 메서드가 없습니다")

    def _batch_cancel_sequential_generation(self):
        """순차 생성 취소 - 현재 생성 중인 것은 완료되고, 나머지 대기 중인 항목들은 취소"""
        print("[BatchImage] 순차 생성 취소됨")

        # 큐 비우기
        cancelled_count = len(self.batch_sequential_generation_queue)
        self.batch_sequential_generation_queue.clear()
        self.batch_is_sequential_generating = False
        self.batch_current_generating_index = None
        self._batch_item_resolutions.clear()
        self._batch_last_completed_index = None  # 중복 이벤트 필터링 초기화

        # 버튼 상태 복원
        self.batch_btn_sequential_start.setEnabled(True)
        self.batch_btn_sequential_start.setText("🎬 순차 생성 시작")
        self.batch_btn_sequential_start.show()
        self.batch_btn_sequential_cancel.hide()

        # 상태 라벨 업데이트
        self.batch_lbl_generation_status.setText(f"❌ 취소됨 ({cancelled_count}개 대기 항목 취소)")
        print(f"[BatchImage] {cancelled_count}개 대기 항목 취소됨")

        # 대기 중이던 아이템들의 버튼 상태 복원
        for item in self.batch_item_widgets:
            if item and item.btn_waiting.isVisible():
                item.btn_waiting.hide()
                item.btn_extract.show()
                if item.extracted_tags:
                    item.btn_generate.show()
                    item.btn_view.show()

    # [제거됨] _batch_process_next_generation 메서드는 더 이상 사용되지 않습니다
    # 이제 _on_batch_generation_completed에서 직접 다음 아이템을 트리거합니다

    def _on_batch_generation_completed(self, result):
        """배치 생성 완료 콜백 (AppContext 이벤트) - 다음 아이템 자동 요청"""
        print(f"[BatchImage] 🎉 이미지 생성 완료 콜백 호출됨!")

        # 순차 생성 중이 아니면 무시
        if not self.batch_is_sequential_generating:
            print("[BatchImage] 순차 생성 중이 아님 - 콜백 무시")
            return

        # ⚠️ 이벤트 시작 시점의 현재 생성 인덱스 캡처 (중요!)
        completed_index = self.batch_current_generating_index
        if completed_index is None:
            print("[BatchImage] ⚠️ 완료된 아이템 인덱스를 알 수 없습니다")
            return

        # ⚠️ 중복 이벤트 필터링: 마지막으로 완료 처리한 인덱스와 동일하면 무시
        if self._batch_last_completed_index == completed_index:
            print(f"[BatchImage] ⚠️ 중복 완료 이벤트 무시 - index: {completed_index} (이미 처리됨)")
            return

        # ⚠️ 큐에 없으면 이미 제거된 것 (순서 오류)
        if completed_index not in self.batch_sequential_generation_queue:
            print(f"[BatchImage] ⚠️ 아이템 {completed_index}가 큐에 없음 (이미 제거됨)")
            return

        # ⚠️ 큐의 첫 번째 아이템이 아니면 순서가 맞지 않음
        if self.batch_sequential_generation_queue[0] != completed_index:
            print(f"[BatchImage] ⚠️ 순서 불일치 - 예상: {self.batch_sequential_generation_queue[0]}, 실제: {completed_index}")
            return

        # 완료 처리 시작
        self._batch_last_completed_index = completed_index
        print(f"[BatchImage] 완료 처리 시작: 아이템 {completed_index}")

        # 큐에서 완료된 아이템 제거
        self.batch_sequential_generation_queue.pop(0)
        print(f"[BatchImage] 완료된 아이템 {completed_index} 큐에서 제거됨")

        # 아이템 상태 업데이트
        if completed_index < len(self.batch_item_widgets):
            item = self.batch_item_widgets[completed_index]
            if item:
                # 생성 버튼을 녹색 "완료" 버튼으로 변경
                item.btn_waiting.hide()
                item.btn_extract.show()

                # 생성 버튼을 녹색 완료 버튼으로 스타일 변경
                item.btn_generate.setText("✅ 완료")
                item.btn_generate.setStyleSheet(get_button_style(bg_color="#2d7a4f", text_color="white"))  # 녹색
                item.btn_generate.show()
                item.btn_view.show()
                print(f"[BatchImage] 아이템 {completed_index} 완료 처리")

                # 자동 삭제 옵션이 켜져있으면 아이템 제거
                if self.batch_auto_remove_completed:
                    print(f"[BatchImage] 아이템 {completed_index} 자동 삭제")
                    self._on_batch_item_close_requested(completed_index)

        # 큐에 남은 아이템 확인
        if self.batch_sequential_generation_queue:
            # 다음 아이템 생성 요청
            next_idx = self.batch_sequential_generation_queue[0]
            next_item = self.batch_item_widgets[next_idx]
            next_resolution = self._batch_item_resolutions.get(next_idx)

            # ⚠️ batch_current_generating_index는 _batch_trigger_single_generation 내부에서 설정됨

            # 상태 업데이트
            total_count = len([w for w in self.batch_item_widgets if w and w.extracted_tags])
            completed_count = total_count - len(self.batch_sequential_generation_queue)
            remaining_count = len(self.batch_sequential_generation_queue)
            self.batch_lbl_generation_status.setText(f"⏳ {completed_count}/{total_count} 완료 (대기: {remaining_count}개)")
            print(f"[BatchImage] 진행 중... ({completed_count}/{total_count}, 대기: {remaining_count}개)")

            # 🎯 다음 아이템 생성 트리거 (내부에서 batch_current_generating_index 업데이트됨)
            print(f"[BatchImage] 🎬 다음 아이템 {next_idx} 생성 시작")
            self._batch_trigger_single_generation(next_idx, next_item, next_resolution)
        else:
            # 모든 아이템 완료
            print("[BatchImage] 🎊 모든 이미지 생성 완료!")
            self.batch_is_sequential_generating = False
            self.batch_current_generating_index = None
            self._batch_last_completed_index = None  # 중복 이벤트 필터링 초기화

            # 버튼 상태 복원
            self.batch_btn_sequential_start.setEnabled(True)
            self.batch_btn_sequential_start.setText("🎬 순차 생성 시작")
            self.batch_btn_sequential_start.show()
            self.batch_btn_sequential_cancel.hide()

            # 상태 라벨 업데이트
            self.batch_lbl_generation_status.setText("✅ 완료")

    # === 해상도 관련 유틸리티 ===

    def _batch_calculate_resolution_from_aspect_ratio(self, image_path: str) -> tuple:
        """이미지 비율에 따른 해상도 계산"""
        try:
            with Image.open(image_path) as img:
                width, height = img.size

            # 비율 계산
            aspect_ratio = width / height

            # NovelAI 표준 해상도 기준으로 가장 가까운 비율 찾기
            # 픽셀 총합 1,048,576 이하만 허용
            MAX_PIXELS = 1_048_576
            standard_resolutions = [
                (832, 1216),   # Portrait: 1,011,712 pixels
                (1216, 832),   # Landscape: 1,011,712 pixels
                (1024, 1024),  # Square: 1,048,576 pixels
            ]

            # 픽셀 총합 검증된 해상도만 필터링
            valid_resolutions = [r for r in standard_resolutions if r[0] * r[1] <= MAX_PIXELS]

            if not valid_resolutions:
                print(f"[BatchImage] ⚠️ 유효한 해상도가 없습니다. 기본값 사용")
                return (1024, 1024)

            # 비율이 가장 가까운 해상도 선택
            best_match = min(valid_resolutions, key=lambda r: abs(r[0]/r[1] - aspect_ratio))

            # 최종 검증
            if best_match[0] * best_match[1] > MAX_PIXELS:
                print(f"[BatchImage] ⚠️ 해상도 {best_match}의 픽셀 총합이 1,048,576을 초과합니다. 기본값 사용")
                return (1024, 1024)

            return best_match

        except Exception as e:
            print(f"[BatchImage] 이미지 비율 계산 실패: {e}")
            return (1024, 1024)  # 기본값

    def _batch_get_random_resolution(self) -> tuple:
        """랜덤 해상도 반환 (픽셀 총합 1,048,576 이하만)"""
        import random
        MAX_PIXELS = 1_048_576
        resolutions = [
            (832, 1216),   # 1,011,712 pixels
            (1216, 832),   # 1,011,712 pixels
            (1024, 1024),  # 1,048,576 pixels
        ]
        # 픽셀 검증
        valid_resolutions = [r for r in resolutions if r[0] * r[1] <= MAX_PIXELS]
        if valid_resolutions:
            return random.choice(valid_resolutions)
        return (1024, 1024)  # 기본값

    # === 단일 이미지 분석 메서드들 ===

    def _create_single_analysis_widget(self):
        """단일 이미지 분석 위젯 생성 (좌우 분할: 이미지 | 텍스트+버튼)"""
        single_widget = QWidget()
        single_layout = QHBoxLayout(single_widget)
        single_layout.setContentsMargins(8, 8, 8, 8)
        single_layout.setSpacing(16)

        # === 왼쪽: 이미지 영역 ===
        left_frame = QFrame()
        left_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 8px;
            }}
        """)
        left_layout = QVBoxLayout(left_frame)
        left_layout.setContentsMargins(8, 8, 8, 8)

        self.single_image_label = QLabel()
        self.single_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.single_image_label.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)
        self.single_image_label.setMinimumSize(get_scaled_size(400), get_scaled_size(400))
        left_layout.addWidget(self.single_image_label)

        single_layout.addWidget(left_frame, 1)

        # === 오른쪽: 텍스트 + 버튼 영역 ===
        right_frame = QFrame()
        right_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 8px;
            }}
        """)
        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(12)

        # 제목
        title_label = QLabel("추출된 태그")
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
            }}
        """)
        right_layout.addWidget(title_label)

        # 태그 개수 라벨
        self.single_tag_count_label = QLabel("0개 태그")
        self.single_tag_count_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(12)}px;
            }}
        """)
        right_layout.addWidget(self.single_tag_count_label)

        # 태그 텍스트 에디트
        self.single_tags_edit = QTextEdit()
        self.single_tags_edit.setReadOnly(True)
        self.single_tags_edit.setPlaceholderText("태그 추출 중...")
        self.single_tags_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 6px;
                padding: 12px;
                font-size: {get_scaled_font_size(17)}px;
                font-family: 'Consolas', 'Monaco', monospace;
            }}
        """)
        right_layout.addWidget(self.single_tags_edit, 1)

        # 버튼 영역
        button_layout = QHBoxLayout()
        button_layout.setSpacing(get_scaled_size(12))

        # 생성 버튼
        self.single_btn_generate = QPushButton("🎨 생성")
        self.single_btn_generate.setStyleSheet(DARK_STYLES['primary_button'])
        self.single_btn_generate.setFixedHeight(get_scaled_size(40))
        self.single_btn_generate.setCursor(Qt.CursorShape.PointingHandCursor)
        self.single_btn_generate.clicked.connect(self._on_single_generate_clicked)
        self.single_btn_generate.setEnabled(False)  # 초기에는 비활성화
        button_layout.addWidget(self.single_btn_generate)

        # 클립보드 복사 버튼
        self.single_btn_copy = QPushButton("📋 복사")
        self.single_btn_copy.setStyleSheet(DARK_STYLES['secondary_button'])
        self.single_btn_copy.setFixedHeight(get_scaled_size(40))
        self.single_btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.single_btn_copy.clicked.connect(self._on_single_copy_clicked)
        self.single_btn_copy.setEnabled(False)  # 초기에는 비활성화
        button_layout.addWidget(self.single_btn_copy)

        # 닫기 버튼
        self.single_btn_close = QPushButton("✕ 닫기")
        self.single_btn_close.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 8px 16px;
                font-size: {get_scaled_font_size(14)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['error']};
                color: white;
            }}
        """)
        self.single_btn_close.setFixedHeight(get_scaled_size(40))
        self.single_btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.single_btn_close.clicked.connect(self._on_single_close_clicked)
        button_layout.addWidget(self.single_btn_close)

        right_layout.addLayout(button_layout)

        single_layout.addWidget(right_frame, 1)

        # 단일 분석 데이터 저장용
        self.single_image_path = None
        self.single_extracted_tags = None

        return single_widget

    def _load_single_image(self, image_path: str, from_clipboard: bool = False):
        """단일 이미지 로드 및 표시"""
        self.single_image_path = image_path

        try:
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                # 이미지 크기에 맞게 스케일링
                scaled_pixmap = pixmap.scaled(
                    get_scaled_size(800), get_scaled_size(800),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.single_image_label.setPixmap(scaled_pixmap)
            else:
                self.single_image_label.setText("이미지 로드 실패")
        except Exception as e:
            print(f"[BatchImage] 단일 이미지 로드 실패: {e}")
            self.single_image_label.setText("이미지 로드 실패")

    def _start_single_image_extraction(self, image_path: str):
        """단일 이미지 WD14 추출 시작"""
        print(f"[BatchImage] WD14 태그 추출 시작: {image_path}")

        # UI 초기화
        self.single_tags_edit.setPlainText("")
        self.single_tags_edit.setPlaceholderText("태그 추출 중...")
        self.single_tag_count_label.setText("추출 중...")
        self.single_btn_generate.setEnabled(False)
        self.single_btn_copy.setEnabled(False)

        # 워커 스레드 시작
        try:
            pil_image = Image.open(image_path).convert("RGB")
            worker = TaggerWorker(pil_image, general_th=self.batch_threshold)
            worker.finished.connect(self._on_single_extraction_finished)
            worker.error.connect(self._on_single_extraction_error)
            worker.start()

            # worker 참조 저장 (가비지 컬렉션 방지)
            self.single_worker = worker
        except Exception as e:
            print(f"[BatchImage] 이미지 로드 실패: {e}")
            self._on_single_extraction_error(str(e))

    def _on_single_extraction_finished(self, result):
        """단일 이미지 추출 완료"""
        print("[BatchImage] WD14 태그 추출 완료")

        general_tags = result.get("general", [])

        if not general_tags:
            self.single_tags_edit.setPlainText("")
            self.single_tags_edit.setPlaceholderText("추출된 태그가 없습니다.")
            self.single_tag_count_label.setText("0개 태그")
            return

        # 태그 문자열 생성
        cleaned_tags = [t[0].replace("_", " ") for t in general_tags]
        tag_str = ", ".join(cleaned_tags)

        # Quick Search 필터링 (있으면)
        if hasattr(self, 'qs_tag_to_id') and self.qs_tag_to_id:
            tags = [t.strip() for t in tag_str.split(',') if t.strip()]
            valid_tags = [t for t in tags if t in self.qs_tag_to_id]
            filtered_tags = ', '.join(valid_tags)
        else:
            filtered_tags = tag_str

        self.single_extracted_tags = filtered_tags
        self.single_tags_edit.setPlainText(filtered_tags)
        self.single_tags_edit.setPlaceholderText("")

        tag_count = len(filtered_tags.split(',')) if filtered_tags else 0
        self.single_tag_count_label.setText(f"{tag_count}개 태그")

        # 버튼 활성화
        self.single_btn_generate.setEnabled(True)
        self.single_btn_copy.setEnabled(True)

    def _on_single_extraction_error(self, err_msg):
        """단일 이미지 추출 에러"""
        print(f"[BatchImage] 추출 에러: {err_msg}")
        self.single_tags_edit.setPlainText("")
        self.single_tags_edit.setPlaceholderText(f"오류 발생: {err_msg}")
        self.single_tag_count_label.setText("오류")

    def _on_single_generate_clicked(self):
        """단일 이미지 생성 버튼 클릭"""
        if not self.single_extracted_tags:
            print("[BatchImage] 추출된 태그가 없습니다")
            return

        # RemoteWindow 규칙: parent_app을 통해 생성 요청
        if self.parent_app:
            source_row_dict = {
                'general': self.single_extracted_tags,
                'rating': 'g',
                'character': '',
                'artist': '',
                'copyright': '',
                'meta': '',
                'quality': '',
            }

            if hasattr(self.parent_app, 'on_generate_with_image_requested'):
                self.parent_app.on_generate_with_image_requested(source_row_dict)
                print(f"[BatchImage] 단일 이미지 생성 요청 완료")
            elif hasattr(self.parent_app, 'on_instant_generation_requested'):
                import pandas as pd
                source_row = pd.Series(source_row_dict)
                self.parent_app.on_instant_generation_requested(source_row)
                print(f"[BatchImage] 단일 이미지 생성 요청 완료 (폴백)")
        else:
            print("[BatchImage] ❌ parent_app이 연결되지 않았습니다")

    def _on_single_copy_clicked(self):
        """단일 이미지 클립보드 복사 버튼 클릭"""
        if not self.single_extracted_tags:
            return

        from PyQt6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(self.single_extracted_tags)

        # 버튼 텍스트 일시적으로 변경
        original_text = self.single_btn_copy.text()
        self.single_btn_copy.setText("✅ 복사 완료!")
        QTimer.singleShot(1500, lambda: self.single_btn_copy.setText(original_text))

    def _on_single_close_clicked(self):
        """단일 이미지 분석 닫기"""
        print("[BatchImage] 단일 이미지 분석 닫기")

        # 단일 분석 위젯 제거
        if self.batch_single_analysis_widget:
            self.batch_content_container.layout().removeWidget(self.batch_single_analysis_widget)
            self.batch_single_analysis_widget.setParent(None)
            self.batch_single_analysis_widget.deleteLater()
            self.batch_single_analysis_widget = None

        # 가시성 업데이트 (빈 공간으로 복귀)
        self._update_batch_content_visibility()


class BatchImageItem(QFrame):
    """배치 처리 개별 아이템 위젯"""

    extraction_requested = pyqtSignal(int)  # index - 재추출
    generation_requested = pyqtSignal(int)  # index - 생성
    view_requested = pyqtSignal(int)  # index - 보기
    close_requested = pyqtSignal(int)  # index - 위젯 닫기 요청

    def __init__(self, file_path: str, index: int, quick_search_block=None, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.index = index
        self.quick_search_block = quick_search_block

        self.extracted_tags = None  # 추출된 태그 문자열
        self.worker = None
        self.is_processing = False  # 현재 처리 중인지 여부

        # 위젯 크기 고정
        self.setFixedSize(get_scaled_size(320), get_scaled_size(420))

        self.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 8px;
                padding: 8px;
            }}
        """)

        self._init_ui()

    def _init_ui(self):
        """UI 초기화"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # === 헤더: 우측 상단 [x] 버튼 ===
        header_layout = QHBoxLayout()
        header_layout.addStretch()

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(get_scaled_size(24), get_scaled_size(24))
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {DARK_COLORS['text_secondary']};
                border: none;
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                color: {DARK_COLORS['error']};
            }}
        """)
        btn_close.clicked.connect(self._on_close_clicked)
        header_layout.addWidget(btn_close)

        layout.addLayout(header_layout)

        # 이미지 프리뷰
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setFixedSize(get_scaled_size(BATCH_IMAGE_THUMB_WIDTH), get_scaled_size(BATCH_IMAGE_THUMB_HEIGHT))
        self.image_label.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)

        # 이미지 로드 및 표시
        try:
            pixmap = QPixmap(self.file_path)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(
                    get_scaled_size(BATCH_IMAGE_THUMB_WIDTH), get_scaled_size(BATCH_IMAGE_THUMB_HEIGHT),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.image_label.setPixmap(scaled_pixmap)
        except Exception as e:
            print(f"[BatchItem] 이미지 로드 실패: {e}")

        layout.addWidget(self.image_label)

        # 파일명 라벨
        file_name = os.path.basename(self.file_path)
        name_label = QLabel(file_name)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(12)}px;
            }}
        """)
        name_label.setWordWrap(True)
        layout.addWidget(name_label)

        # 진행바 (추출 중에만 표시) - 고정 높이
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(get_scaled_size(6))
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {DARK_COLORS['accent_blue']}; }}")
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # 버튼 영역 - 고정 높이로 크기 변동 방지
        self.button_container = QWidget()
        self.button_container.setFixedHeight(get_scaled_size(40))  # 고정 높이
        self.button_layout = QVBoxLayout(self.button_container)
        self.button_layout.setContentsMargins(0, 0, 0, 0)
        self.button_layout.setSpacing(4)

        # 대기중 버튼 (초기에는 숨김, 순차 생성 중에만 표시)
        self.btn_waiting = QPushButton("⏳ 대기 중...")
        self.btn_waiting.setEnabled(False)
        self.btn_waiting.setFixedHeight(get_scaled_size(36))
        self.btn_waiting.setStyleSheet(get_button_style(bg_color=DARK_COLORS['border'], text_color=DARK_COLORS['text_secondary']))
        self.button_layout.addWidget(self.btn_waiting)
        self.btn_waiting.hide()  # 초기에는 숨김

        # 버튼들 - [추출][생성][보기] 3개 버튼
        action_layout = QHBoxLayout()
        action_layout.setSpacing(4)

        # 추출 버튼 (초기 상태에서 표시, 사용자가 선택적으로 추출 가능)
        self.btn_extract = QPushButton("추출")
        self.btn_extract.setFixedHeight(get_scaled_size(36))
        self.btn_extract.setStyleSheet(get_button_style(bg_color=DARK_COLORS['accent_blue'], text_color="white"))
        self.btn_extract.clicked.connect(self._on_extract_clicked)
        # 초기 상태에서 표시됨 (사용자가 원할 때 추출 가능)

        # 생성 버튼 (추출 완료 후 표시)
        self.btn_generate = QPushButton("생성")
        self.btn_generate.setFixedHeight(get_scaled_size(36))
        self.btn_generate.setStyleSheet(get_button_style(bg_color=DARK_COLORS['accent_blue'], text_color="white"))
        self.btn_generate.clicked.connect(lambda: self.generation_requested.emit(self.index))
        self.btn_generate.hide()  # 초기에는 숨김

        # 보기 버튼 (추출 완료 후 표시)
        self.btn_view = QPushButton("보기")
        self.btn_view.setFixedHeight(get_scaled_size(36))
        self.btn_view.setStyleSheet(get_button_style(bg_color=DARK_COLORS['bg_tertiary'], text_color=DARK_COLORS['text_primary']))
        self.btn_view.clicked.connect(lambda: self.view_requested.emit(self.index))
        self.btn_view.hide()  # 초기에는 숨김

        action_layout.addWidget(self.btn_extract)
        action_layout.addWidget(self.btn_generate)
        action_layout.addWidget(self.btn_view)

        self.button_layout.addLayout(action_layout)

        layout.addWidget(self.button_container)

    def _on_extract_clicked(self):
        """추출 버튼 클릭 시 처리 (재추출 가능)"""
        # 부모 윈도우에서 threshold 가져오기
        parent_window = self.window()
        threshold = 0.51  # 기본값
        if hasattr(parent_window, 'batch_threshold'):
            threshold = parent_window.batch_threshold

        # 재추출 시작
        self.start_extraction(threshold)

    def _on_close_clicked(self):
        """[x] 버튼 클릭 시 처리"""
        if self.is_processing:
            # 처리 중인 경우 중지 확인
            from PyQt6.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self,
                "확인",
                "현재 처리 중입니다. 중지하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                # 워커 스레드 중지
                if self.worker and self.worker.isRunning():
                    self.worker.terminate()
                    self.worker.wait()
                self.close_requested.emit(self.index)
        else:
            # 처리 중이 아닌 경우 바로 닫기
            self.close_requested.emit(self.index)

    def start_extraction(self, threshold: float):
        """태그 추출 시작"""
        print(f"[BatchItem {self.index}] 태그 추출 시작 (Threshold: {threshold})")

        # 처리 중 플래그 설정
        self.is_processing = True

        # 버튼 상태 변경 (추출 버튼 텍스트 변경)
        self.btn_extract.setText("추출 중...")
        self.btn_extract.setEnabled(False)  # 추출 중에는 비활성화
        self.btn_generate.hide()
        self.btn_view.hide()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()

        # 워커 스레드 시작
        try:
            pil_image = Image.open(self.file_path).convert("RGB")
            self.worker = TaggerWorker(pil_image, general_th=threshold)
            self.worker.finished.connect(self._on_extraction_finished)
            self.worker.error.connect(self._on_extraction_error)
            self.worker.start()
        except Exception as e:
            print(f"[BatchItem {self.index}] 이미지 로드 실패: {e}")
            self._on_extraction_error(str(e))

    def _on_extraction_finished(self, result):
        """추출 완료"""
        self.progress_bar.hide()
        self.is_processing = False  # 처리 완료

        general_tags = result.get("general", [])

        if not general_tags:
            print(f"[BatchItem {self.index}] 태그 없음")
            self.btn_extract.setText("태그 없음")
            self.btn_extract.setEnabled(False)
            return

        # 태그 문자열 생성
        cleaned_tags = [t[0].replace("_", " ") for t in general_tags]
        tag_str = ", ".join(cleaned_tags)

        # Quick Search 필터링
        if self.quick_search_block and hasattr(self.quick_search_block, 'tag_to_id'):
            tags = [t.strip() for t in tag_str.split(',') if t.strip()]
            valid_tags = [t for t in tags if t in self.quick_search_block.tag_to_id]
            filtered_tags = ', '.join(valid_tags)
        else:
            filtered_tags = tag_str

        self.extracted_tags = filtered_tags
        print(f"[BatchItem {self.index}] 추출 완료: {len(filtered_tags.split(','))}개 태그")

        # UI 업데이트: 추출 버튼 원래대로, 생성/보기 버튼 표시
        self.btn_extract.setText("추출")
        self.btn_extract.setEnabled(True)
        self.btn_extract.show()
        self.btn_generate.show()
        self.btn_view.show()

        # 부모 위젯에 완료 알림 (Mixin 메서드 호출)
        parent_window = self.window()
        if hasattr(parent_window, '_on_batch_extraction_completed'):
            parent_window._on_batch_extraction_completed(self.index, filtered_tags)

    def _on_extraction_error(self, err_msg):
        """추출 에러"""
        self.progress_bar.hide()
        self.is_processing = False  # 처리 완료 (에러)
        self.btn_extract.setText("오류 발생")
        self.btn_extract.setEnabled(False)
        print(f"[BatchItem {self.index}] 오류: {err_msg}")
