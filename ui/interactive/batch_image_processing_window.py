# ui/interactive/batch_image_processing_window.py
"""
Batch Image Processing Window - 여러 이미지를 순차적으로 WD14 태그 추출
"""

import os
from typing import List, Optional
from PIL import Image

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QGridLayout, QLabel, QPushButton, QProgressBar, QFrame, QRadioButton, QButtonGroup, QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject, QTimer
from PyQt6.QtGui import QPixmap

from ui.theme import DARK_COLORS
from ui.scaling_manager import get_scaled_size, get_scaled_font_size
from ui.interactive.interactive_theme import COMMON_STYLES, get_button_style, FONT_FAMILY


class BatchImageProcessingWindow(QMainWindow):
    """배치 이미지 처리 윈도우"""

    def __init__(self, file_paths: List[str], quick_search_block=None, main_prompt_block=None, app_context=None, parent=None):
        super().__init__(parent)
        self.file_paths = file_paths
        self.quick_search_block = quick_search_block
        self.main_prompt_block = main_prompt_block
        self.app_context = app_context

        # 처리 큐
        self.processing_queue = []  # 처리 대기 중인 아이템 인덱스
        self.current_processing_index = None  # 현재 처리 중인 아이템 인덱스

        # 아이템 위젯 리스트
        self.item_widgets = []

        # Threshold 설정 (기본값 0.51)
        self.threshold = 0.51

        # 순차 생성 관련
        self.sequential_generation_queue = []  # 순차 생성 대기 큐
        self.current_generating_index = None  # 현재 생성 중인 아이템 인덱스
        self.is_sequential_generating = False  # 순차 생성 진행 중 여부
        self.resolution_mode = "aspect_ratio"  # "random", "aspect_ratio", "control_panel"
        self.current_resolution_override = None  # 현재 생성에 사용할 해상도 오버라이드
        self._generation_callback_registered = False  # 이벤트 구독 상태 추적
        self.auto_remove_completed = False  # 생성 완료시 자동 삭제 여부

        self.setWindowTitle(f"배치 이미지 태거 - {len(file_paths)}개 이미지")
        self.setMinimumSize(get_scaled_size(1200), get_scaled_size(800))

        # 다크 테마 적용
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        self._init_ui()
        # 자동 시작 제거 - 사용자가 버튼을 눌러야 시작

    def closeEvent(self, event):
        """윈도우 닫기 시 정리"""
        print("[BatchWindow] 윈도우 닫기 - 리소스 정리 시작")

        # 순차 생성 취소
        if self.is_sequential_generating:
            self._cancel_sequential_generation()

        # 모든 워커 스레드 종료
        for item in self.item_widgets:
            if item and hasattr(item, 'worker') and item.worker:
                if item.worker.isRunning():
                    item.worker.terminate()
                    item.worker.wait()

        # ⚠️ 구독 해제는 InteractiveWindow에서 처리됨 (여기서는 하지 않음)

        print("[BatchWindow] 리소스 정리 완료")
        super().closeEvent(event)

    def _init_ui(self):
        """UI 초기화"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # === 헤더 영역 ===
        header_widget = QWidget()
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)

        # 제목
        header_label = QLabel(f"📦 배치 이미지 태거 - 총 {len(self.file_paths)}개 이미지")
        header_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(18)}px;
                font-weight: bold;
                padding: 8px;
            }}
        """)
        header_layout.addWidget(header_label)

        # 설정 영역 (Threshold + 시작 버튼)
        settings_layout = QHBoxLayout()
        settings_layout.setSpacing(get_scaled_size(8))

        # Threshold 라벨
        lbl_th = QLabel("Threshold:")
        lbl_th.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(14)}px;")
        settings_layout.addWidget(lbl_th)

        # Threshold 버튼 그룹
        from PyQt6.QtWidgets import QButtonGroup
        from ui.interactive.image_tagger_block import ThresholdButton

        self.threshold_group = QButtonGroup(self)
        self.threshold_group.setExclusive(True)

        self.btn_th_051 = ThresholdButton("0.51", 0.51)
        self.btn_th_061 = ThresholdButton("0.61", 0.61)
        self.btn_th_071 = ThresholdButton("0.71", 0.71)

        self.threshold_group.addButton(self.btn_th_051)
        self.threshold_group.addButton(self.btn_th_061)
        self.threshold_group.addButton(self.btn_th_071)

        # 기본 선택: 0.51
        self.btn_th_051.setChecked(True)

        # Threshold 변경 시 값 업데이트
        self.threshold_group.buttonClicked.connect(self._on_threshold_changed)

        settings_layout.addWidget(self.btn_th_051)
        settings_layout.addWidget(self.btn_th_061)
        settings_layout.addWidget(self.btn_th_071)

        settings_layout.addSpacing(get_scaled_size(20))

        # 태그 추출 시작 버튼
        self.btn_start = QPushButton("⚡ 태그 추출 시작")
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.setFixedHeight(get_scaled_size(36))
        self.btn_start.setStyleSheet(get_button_style(bg_color=DARK_COLORS['accent_blue'], text_color="white"))
        self.btn_start.clicked.connect(self._start_batch_processing)
        settings_layout.addWidget(self.btn_start)

        settings_layout.addStretch()

        header_layout.addLayout(settings_layout)

        main_layout.addWidget(header_widget)

        # 스크롤 영역
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: {DARK_COLORS['bg_secondary']};
            }}
        """)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(8, 8, 8, 8)
        scroll_layout.setSpacing(16)

        # 그리드 레이아웃 (3열)
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(16)

        # 각 이미지에 대한 아이템 위젯 생성
        for i, file_path in enumerate(self.file_paths):
            item_widget = BatchImageItem(file_path, i, self.quick_search_block)
            item_widget.extraction_requested.connect(lambda idx=i: self._on_extraction_requested(idx))
            item_widget.generation_requested.connect(lambda idx=i: self._on_generation_requested(idx))
            item_widget.close_requested.connect(self._on_item_close_requested)

            # 3열 그리드 배치
            row = i // 3
            col = i % 3
            self.grid_layout.addWidget(item_widget, row, col)

            self.item_widgets.append(item_widget)
            self.processing_queue.append(i)

        scroll_layout.addLayout(self.grid_layout)
        scroll_layout.addStretch()

        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)

        # === 하단: 순차 생성 섹션 ===
        self._init_sequential_generation_section(main_layout)

    def _init_sequential_generation_section(self, parent_layout):
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
        self.lbl_generation_status = QLabel("")
        self.lbl_generation_status.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(13)}px;
            }}
        """)
        header_layout.addWidget(self.lbl_generation_status)

        section_layout.addLayout(header_layout)

        # 해상도 옵션
        resolution_layout = QHBoxLayout()
        resolution_layout.setSpacing(get_scaled_size(16))

        res_label = QLabel("해상도:")
        res_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(14)}px;")
        resolution_layout.addWidget(res_label)

        self.resolution_group = QButtonGroup(self)
        self.resolution_group.setExclusive(True)

        # 이미지 비율 적용 (기본값)
        self.radio_aspect = QRadioButton("이미지 비율")
        self.radio_aspect.setChecked(True)
        self.radio_aspect.setStyleSheet(f"""
            QRadioButton {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
            }}
            QRadioButton::indicator {{
                width: {get_scaled_size(18)}px;
                height: {get_scaled_size(18)}px;
            }}
        """)
        self.resolution_group.addButton(self.radio_aspect)
        resolution_layout.addWidget(self.radio_aspect)

        # 랜덤으로
        self.radio_random = QRadioButton("랜덤")
        self.radio_random.setStyleSheet(f"""
            QRadioButton {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
            }}
            QRadioButton::indicator {{
                width: {get_scaled_size(18)}px;
                height: {get_scaled_size(18)}px;
            }}
        """)
        self.resolution_group.addButton(self.radio_random)
        resolution_layout.addWidget(self.radio_random)

        # 컨트롤 패널 옵션 적용
        self.radio_control_panel = QRadioButton("컨트롤 패널")
        self.radio_control_panel.setStyleSheet(f"""
            QRadioButton {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
            }}
            QRadioButton::indicator {{
                width: {get_scaled_size(18)}px;
                height: {get_scaled_size(18)}px;
            }}
        """)
        self.resolution_group.addButton(self.radio_control_panel)
        resolution_layout.addWidget(self.radio_control_panel)

        # 라디오 버튼 변경 시 값 업데이트
        self.resolution_group.buttonClicked.connect(self._on_resolution_mode_changed)

        resolution_layout.addStretch()
        section_layout.addLayout(resolution_layout)

        # 옵션 체크박스
        options_layout = QHBoxLayout()
        options_layout.setSpacing(get_scaled_size(16))

        # 자동 삭제 체크박스
        self.chk_auto_remove = QCheckBox("생성 완료시 목록에서 삭제")
        self.chk_auto_remove.setStyleSheet(f"""
            QCheckBox {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
            }}
            QCheckBox::indicator {{
                width: {get_scaled_size(18)}px;
                height: {get_scaled_size(18)}px;
            }}
        """)
        self.chk_auto_remove.stateChanged.connect(self._on_auto_remove_changed)
        options_layout.addWidget(self.chk_auto_remove)

        options_layout.addStretch()
        section_layout.addLayout(options_layout)

        # 순차 생성 버튼들
        button_layout = QHBoxLayout()
        button_layout.setSpacing(get_scaled_size(12))
        button_layout.addStretch()

        self.btn_sequential_start = QPushButton("🎬 순차 생성 시작")
        self.btn_sequential_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sequential_start.setFixedHeight(get_scaled_size(40))
        self.btn_sequential_start.setFixedWidth(get_scaled_size(160))
        self.btn_sequential_start.setStyleSheet(get_button_style(bg_color=DARK_COLORS['accent_blue'], text_color="white"))
        self.btn_sequential_start.clicked.connect(self._start_sequential_generation)
        button_layout.addWidget(self.btn_sequential_start)

        # 취소 버튼 (생성 중일 때만 표시)
        self.btn_sequential_cancel = QPushButton("⏹ 취소")
        self.btn_sequential_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sequential_cancel.setFixedHeight(get_scaled_size(40))
        self.btn_sequential_cancel.setFixedWidth(get_scaled_size(100))
        self.btn_sequential_cancel.setStyleSheet(get_button_style(bg_color=DARK_COLORS['error'], text_color="white"))
        self.btn_sequential_cancel.clicked.connect(self._cancel_sequential_generation)
        self.btn_sequential_cancel.hide()  # 초기에는 숨김
        button_layout.addWidget(self.btn_sequential_cancel)

        button_layout.addStretch()
        section_layout.addLayout(button_layout)

        parent_layout.addWidget(section_frame)

    def _on_resolution_mode_changed(self):
        """해상도 모드 변경"""
        if self.radio_aspect.isChecked():
            self.resolution_mode = "aspect_ratio"
        elif self.radio_random.isChecked():
            self.resolution_mode = "random"
        elif self.radio_control_panel.isChecked():
            self.resolution_mode = "control_panel"
        print(f"[BatchWindow] 해상도 모드 변경: {self.resolution_mode}")

    def _on_auto_remove_changed(self, state):
        """자동 삭제 체크박스 변경"""
        self.auto_remove_completed = (state == Qt.CheckState.Checked.value)
        print(f"[BatchWindow] 자동 삭제: {'ON' if self.auto_remove_completed else 'OFF'}")

    def _on_threshold_changed(self):
        """Threshold 버튼 변경 시 값 업데이트"""
        checked_button = self.threshold_group.checkedButton()
        if checked_button and hasattr(checked_button, 'value'):
            self.threshold = checked_button.value
            print(f"[BatchWindow] Threshold 변경: {self.threshold}")

    def _start_batch_processing(self):
        """태그 추출 시작 버튼 클릭"""
        print(f"[BatchWindow] 배치 처리 시작 (Threshold: {self.threshold})")
        self.btn_start.setEnabled(False)
        self.btn_start.setText("처리 중...")
        self._process_next()

    def _start_auto_processing(self):
        """자동 처리 시작 (레거시 메서드 - 더 이상 사용 안 함)"""
        if self.processing_queue:
            self._process_next()

    def _process_next(self):
        """큐에서 다음 아이템 처리"""
        if not self.processing_queue:
            print("[BatchWindow] 모든 이미지 처리 완료")
            # 모든 처리 완료 시 시작 버튼 다시 활성화
            self.btn_start.setEnabled(True)
            self.btn_start.setText("⚡ 태그 추출 시작")
            return

        # 큐에서 첫 번째 아이템 가져오기
        next_index = self.processing_queue[0]
        self.current_processing_index = next_index

        # 해당 아이템의 추출 시작 (None 체크)
        item = self.item_widgets[next_index]
        if item:
            item.start_extraction()
        else:
            # 아이템이 제거된 경우 스킵
            print(f"[BatchWindow] 아이템 {next_index}가 제거되어 스킵")
            if next_index in self.processing_queue:
                self.processing_queue.remove(next_index)
            self._process_next()

    def _on_extraction_completed(self, index: int, tags: str):
        """아이템 추출 완료 시 호출"""
        print(f"[BatchWindow] 아이템 {index} 추출 완료: {len(tags.split(','))}개 태그")

        # 큐에서 제거
        if index in self.processing_queue:
            self.processing_queue.remove(index)

        # 다음 아이템 처리
        self._process_next()

    def _on_extraction_requested(self, index: int):
        """추출 버튼 클릭: 태그를 메인 프롬프트로 전송"""
        print(f"[BatchWindow] 아이템 {index} 메인 프롬프트로 전송 요청")

        # None 체크
        if index >= len(self.item_widgets) or self.item_widgets[index] is None:
            return

        item = self.item_widgets[index]
        if not item.extracted_tags:
            print(f"[BatchWindow] 아이템 {index} 추출된 태그가 없습니다")
            return

        # Main Prompt Block에 태그 설정
        if self.main_prompt_block:
            # 포맷팅 적용하여 설정
            formatted_html = self.main_prompt_block._format_prompt_with_categories(item.extracted_tags)
            self.main_prompt_block.set_prompt_html(formatted_html)
            print(f"[BatchWindow] 메인 프롬프트 업데이트 완료: {len(item.extracted_tags.split(','))}개 태그")
        else:
            print("[BatchWindow] ❌ Main Prompt 블록이 연결되지 않았습니다")

    def _on_generation_requested(self, index: int):
        """생성 버튼 클릭: 태그를 메인 프롬프트로 전송하고 이미지 생성"""
        print(f"[BatchWindow] 아이템 {index} 생성 요청")

        # None 체크
        if index >= len(self.item_widgets) or self.item_widgets[index] is None:
            return

        item = self.item_widgets[index]
        if not item.extracted_tags:
            print(f"[BatchWindow] 아이템 {index} 추출된 태그가 없습니다")
            return

        # Main Prompt Block에 태그 설정 및 생성
        if self.main_prompt_block:
            # 포맷팅 적용하여 설정
            formatted_html = self.main_prompt_block._format_prompt_with_categories(item.extracted_tags)
            self.main_prompt_block.set_prompt_html(formatted_html)
            print(f"[BatchWindow] 메인 프롬프트 업데이트 완료: {len(item.extracted_tags.split(','))}개 태그")

            # 이미지 생성 트리거
            self.main_prompt_block.trigger_generation()
            print("[BatchWindow] 이미지 생성 요청됨")
        else:
            print("[BatchWindow] ❌ Main Prompt 블록이 연결되지 않았습니다")

    def _on_item_close_requested(self, index: int):
        """아이템 닫기 요청"""
        print(f"[BatchWindow] 아이템 {index} 닫기 요청")

        # 위젯 가져오기 (None 체크)
        if index >= len(self.item_widgets) or self.item_widgets[index] is None:
            print(f"[BatchWindow] 아이템 {index}가 이미 제거되었거나 존재하지 않음")
            return

        item = self.item_widgets[index]

        # 그리드에서 제거
        self.grid_layout.removeWidget(item)
        item.setParent(None)
        item.deleteLater()

        # 리스트에서 제거 (None으로 표시)
        self.item_widgets[index] = None

        # 처리 큐에서 제거
        if index in self.processing_queue:
            self.processing_queue.remove(index)

        # 순차 생성 큐에서도 제거
        if index in self.sequential_generation_queue:
            self.sequential_generation_queue.remove(index)

        # 현재 처리 중인 아이템이면 다음으로 진행
        if self.current_processing_index == index:
            self.current_processing_index = None
            self._process_next()

        # 현재 생성 중인 아이템이면 다음으로 진행
        if self.current_generating_index == index:
            self.current_generating_index = None
            self._process_next_generation()

        print(f"[BatchWindow] 아이템 {index} 제거 완료")

    # === 순차 생성 관련 메서드 ===

    def _start_sequential_generation(self):
        """순차 생성 시작 - 모든 아이템을 한번에 큐에 추가"""
        print(f"[BatchWindow] 순차 생성 시작 (해상도 모드: {self.resolution_mode})")

        # 기존 상태 초기화 (다시 눌렀을 때)
        self.sequential_generation_queue.clear()
        self.current_generating_index = None
        self.current_resolution_override = None

        # 태그 추출이 완료된 아이템들만 찾기
        items_to_generate = []
        for i, item in enumerate(self.item_widgets):
            if item and item.extracted_tags:
                items_to_generate.append((i, item))
                self.sequential_generation_queue.append(i)

        if not items_to_generate:
            print("[BatchWindow] 순차 생성할 아이템이 없습니다 (태그 추출 완료된 아이템 없음)")
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "알림", "태그가 추출된 이미지가 없습니다.\n먼저 태그 추출을 완료해주세요.")
            return

        print(f"[BatchWindow] 순차 생성 큐: {len(items_to_generate)}개 아이템")

        # 순차 생성 플래그 설정
        self.is_sequential_generating = True

        # 버튼 상태 변경
        self.btn_sequential_start.setEnabled(False)
        self.btn_sequential_start.setText("⏳ 생성 중...")
        self.btn_sequential_start.hide()  # 시작 버튼 숨김
        self.btn_sequential_cancel.show()  # 취소 버튼 표시

        # 상태 라벨 업데이트
        total_count = len(items_to_generate)
        self.lbl_generation_status.setText(f"⏳ 0/{total_count} 완료 (큐: {total_count}개)")

        # 생성 완료 이벤트 구독 (최초 1회만)
        if self.app_context and not self._generation_callback_registered:
            try:
                self.app_context.subscribe("generation_completed_for_interactive", self._on_batch_generation_completed)
                self._generation_callback_registered = True
                print("[BatchWindow] ✅ 생성 완료 이벤트 구독 성공")
            except Exception as e:
                print(f"[BatchWindow] ❌ 이벤트 구독 실패: {e}")

        # 🎯 모든 아이템을 순차적으로 큐에 추가 (딜레이를 두고)
        # 첫 번째는 즉시 실행 → is_generating = True 설정
        # 나머지는 100ms 간격으로 실행 → 자동으로 큐에 추가됨
        for idx, item in items_to_generate:
            # 해상도 설정
            if self.resolution_mode == "aspect_ratio":
                resolution = self._calculate_resolution_from_aspect_ratio(item.file_path)
            elif self.resolution_mode == "random":
                resolution = self._get_random_resolution()
            else:  # control_panel
                resolution = None

            # 해상도 저장 (딕셔너리에 저장)
            if not hasattr(self, '_item_resolutions'):
                self._item_resolutions = {}
            self._item_resolutions[idx] = resolution  # None도 저장 (control_panel 모드)

            # 아이템 상태 표시
            item.btn_waiting.setText("⏳ 대기 중...")
            item.btn_waiting.show()
            item.btn_extract.hide()
            item.btn_generate.hide()

            # QTimer를 사용하여 순차적으로 생성 요청 (각 100ms 간격)
            # 첫 번째는 즉시(0ms), 나머지는 100ms씩 지연
            delay_ms = items_to_generate.index((idx, item)) * 100

            # 람다 함수에서 idx와 item을 캡처 (클로저 문제 방지)
            QTimer.singleShot(delay_ms, lambda i=idx, itm=item, res=resolution: self._trigger_single_generation(i, itm, res))

        print(f"[BatchWindow] ✅ 총 {len(items_to_generate)}개 아이템 생성 요청 스케줄링 완료")

        # 첫 번째 아이템을 현재 생성 인덱스로 설정 (완료 콜백에서 사용)
        self.current_generating_index = self.sequential_generation_queue[0] if self.sequential_generation_queue else None

    def _trigger_single_generation(self, idx: int, item, resolution):
        """단일 아이템 생성 트리거 (QTimer 콜백용)"""
        print(f"[BatchWindow] 🎬 아이템 {idx} 생성 트리거 (해상도: {resolution})")

        # 메인 프롬프트에 태그 설정
        if self.main_prompt_block:
            formatted_html = self.main_prompt_block._format_prompt_with_categories(item.extracted_tags)
            self.main_prompt_block.set_prompt_html(formatted_html)
            print(f"[BatchWindow] 아이템 {idx} 메인 프롬프트 업데이트: {len(item.extracted_tags.split(','))}개 태그")

            # 🔑 현재 생성 인덱스 설정 (파라미터 수집 시 사용됨)
            self.current_generating_index = idx

            # 이미지 생성 트리거 (첫 번째는 즉시 실행, 나머지는 큐에 추가됨)
            self.main_prompt_block.trigger_generation()
            print(f"[BatchWindow] ✅ 아이템 {idx} 생성 요청 완료")

    def _cancel_sequential_generation(self):
        """순차 생성 취소"""
        print("[BatchWindow] 순차 생성 취소됨")

        # 큐 비우기
        self.sequential_generation_queue.clear()
        self.is_sequential_generating = False
        self.current_generating_index = None
        self.current_resolution_override = None

        # ⚠️ 구독 해제는 InteractiveWindow에서 처리됨

        # 버튼 상태 복원
        self.btn_sequential_start.setEnabled(True)
        self.btn_sequential_start.setText("🎬 순차 생성 시작")
        self.btn_sequential_start.show()
        self.btn_sequential_cancel.hide()

        # 상태 라벨 초기화
        self.lbl_generation_status.setText("")

    def _process_next_generation(self):
        """다음 아이템 생성"""
        if not self.sequential_generation_queue:
            print("[BatchWindow] 순차 생성 큐가 비었습니다")
            # ⚠️ 실제 완료 처리는 _on_batch_generation_completed에서 queue_manager를 확인해서 처리
            return

        # 큐에서 다음 아이템 가져오기
        next_index = self.sequential_generation_queue[0]
        self.current_generating_index = next_index

        # None 체크
        item = self.item_widgets[next_index]
        if not item or not item.extracted_tags:
            print(f"[BatchWindow] 아이템 {next_index} 스킵 (제거되었거나 태그 없음)")
            self.sequential_generation_queue.remove(next_index)
            self._process_next_generation()
            return

        print(f"[BatchWindow] 아이템 {next_index} 생성 시작")

        # 해상도 설정 (오버라이드 값 저장)
        self._apply_resolution_for_item(next_index)

        # 메인 프롬프트에 태그 설정 및 생성
        if self.main_prompt_block:
            formatted_html = self.main_prompt_block._format_prompt_with_categories(item.extracted_tags)
            self.main_prompt_block.set_prompt_html(formatted_html)
            print(f"[BatchWindow] 메인 프롬프트 업데이트: {len(item.extracted_tags.split(','))}개 태그")

            # 생성 완료 이벤트 구독 (최초 1회만)
            if self.app_context and not self._generation_callback_registered:
                try:
                    self.app_context.subscribe("generation_completed_for_interactive", self._on_batch_generation_completed)
                    self._generation_callback_registered = True
                    print("[BatchWindow] ✅ 생성 완료 이벤트 구독 성공")
                except Exception as e:
                    print(f"[BatchWindow] ❌ 이벤트 구독 실패: {e}")
            elif not self.app_context:
                print("[BatchWindow] ⚠️ AppContext가 없어 이벤트 구독 불가")

            # 아이템 상태 표시
            item.btn_waiting.setText("⏳ 생성 중...")
            item.btn_waiting.show()
            item.btn_extract.hide()
            item.btn_generate.hide()

            # 이미지 생성 트리거
            print(f"[BatchWindow] 🎬 아이템 {next_index} 생성 트리거 (해상도: {self.current_resolution_override})")
            self.main_prompt_block.trigger_generation()

            # 큐에서 제거 (완료 후 다음으로 진행)
            self.sequential_generation_queue.remove(next_index)
        else:
            print("[BatchWindow] ❌ Main Prompt 블록이 연결되지 않았습니다")
            self.sequential_generation_queue.remove(next_index)
            self._process_next_generation()

    def _on_batch_generation_completed(self, result):
        """배치 생성 완료 콜백"""
        print(f"[BatchWindow] 🎉 이미지 생성 완료 콜백 호출됨! (result type: {type(result).__name__})")

        # 순차 생성 중이 아니면 무시
        if not self.is_sequential_generating:
            print("[BatchWindow] 순차 생성 중이 아님 - 콜백 무시")
            return

        # 큐에서 완료된 아이템 인덱스 가져오기 (FIFO - 첫 번째 아이템)
        completed_index = None
        if self.sequential_generation_queue:
            completed_index = self.sequential_generation_queue.pop(0)  # 큐 앞에서 제거
            print(f"[BatchWindow] 완료된 아이템 (큐에서 pop): {completed_index}")
        elif self.current_generating_index is not None:
            # 큐가 비어있으면 current_generating_index 사용 (마지막 아이템)
            completed_index = self.current_generating_index
            print(f"[BatchWindow] 완료된 아이템 (current_index 사용): {completed_index}")

        # 아이템 상태 업데이트
        if completed_index is not None and completed_index < len(self.item_widgets):
            item = self.item_widgets[completed_index]
            if item:
                # 생성 버튼을 녹색 "완료" 버튼으로 변경
                item.btn_waiting.hide()
                item.btn_extract.show()

                # 생성 버튼을 녹색 완료 버튼으로 스타일 변경
                item.btn_generate.setText("✅ 완료")
                item.btn_generate.setStyleSheet(get_button_style(bg_color="#2d7a4f", text_color="white"))  # 녹색
                item.btn_generate.show()
                print(f"[BatchWindow] 아이템 {completed_index} 완료 처리")

                # 🔧 편법: Interactive Window의 image_plane 강제 업데이트
                self._force_update_interactive_image(result)

                # 자동 삭제 옵션이 켜져있으면 아이템 제거
                if self.auto_remove_completed:
                    print(f"[BatchWindow] 아이템 {completed_index} 자동 삭제")
                    self._on_item_close_requested(completed_index)

        # GenerationQueueManager에서 남은 큐 크기 확인
        queue_manager = self.app_context.generation_queue_manager if self.app_context else None
        remaining_queue = queue_manager.get_queue_size() if queue_manager else 0

        print(f"[BatchWindow] GenerationQueue 남은 개수: {remaining_queue}")

        # 큐가 비었으면 순차 생성 완료
        if remaining_queue == 0 and not self.sequential_generation_queue:
            print("[BatchWindow] 🎊 모든 이미지 생성 완료!")
            self.is_sequential_generating = False
            self.current_generating_index = None

            # 버튼 상태 복원
            self.btn_sequential_start.setEnabled(True)
            self.btn_sequential_start.setText("🎬 순차 생성 시작")
            self.btn_sequential_start.show()
            self.btn_sequential_cancel.hide()

            # 상태 라벨 업데이트
            self.lbl_generation_status.setText("✅ 완료")
        else:
            # 아직 큐가 남아있으면 상태 업데이트만
            total_count = len([w for w in self.item_widgets if w and w.extracted_tags])
            completed_count = total_count - len(self.sequential_generation_queue)
            self.lbl_generation_status.setText(f"⏳ {completed_count}/{total_count} 완료 (큐: {remaining_queue}개)")
            print(f"[BatchWindow] 진행 중... ({completed_count}/{total_count}, 큐: {remaining_queue}개)")

            # 다음 아이템 인덱스를 current_generating_index로 설정
            if self.sequential_generation_queue:
                self.current_generating_index = self.sequential_generation_queue[0]
                print(f"[BatchWindow] 다음 처리 예정 아이템: {self.current_generating_index}")

        # ⚠️ 구독 해제는 InteractiveWindow에서 처리됨 (여기서는 하지 않음)

    def _force_update_interactive_image(self, result):
        """
        🔧 편법: Interactive Window의 image_plane을 강제로 업데이트

        result가 PIL Image이거나 dict에 'image' 키가 있을 때만 작동합니다.
        """
        try:
            # result에서 이미지 추출
            pil_image = None
            if hasattr(result, 'mode'):  # PIL Image 객체
                pil_image = result
            elif isinstance(result, dict) and 'image' in result:
                pil_image = result['image']

            if not pil_image:
                print("[BatchWindow] 강제 업데이트: 이미지를 찾을 수 없음")
                return

            # Interactive Window 찾기 (parent chain 탐색)
            interactive_window = None

            # 방법 1: main_prompt_block의 부모 윈도우 탐색
            if self.main_prompt_block:
                widget = self.main_prompt_block
                while widget:
                    if hasattr(widget, 'image_plane'):
                        interactive_window = widget
                        break
                    widget = widget.parent() if hasattr(widget, 'parent') else None

            # 방법 2: 현재 BatchWindow의 부모 탐색
            if not interactive_window:
                widget = self.parent()
                while widget:
                    if hasattr(widget, 'image_plane'):
                        interactive_window = widget
                        break
                    widget = widget.parent() if hasattr(widget, 'parent') else None

            if interactive_window and hasattr(interactive_window, 'image_plane'):
                # 이미지 강제 업데이트
                interactive_window.image_plane.set_image(pil_image)
                print(f"[BatchWindow] ✅ Interactive Window 이미지 강제 업데이트 완료")
            else:
                print("[BatchWindow] ⚠️ Interactive Window를 찾을 수 없음")

        except Exception as e:
            print(f"[BatchWindow] ❌ 이미지 강제 업데이트 실패: {e}")
            import traceback
            traceback.print_exc()

    def _apply_resolution_for_item(self, index: int):
        """아이템의 이미지에 따라 해상도 설정"""
        item = self.item_widgets[index]
        if not item:
            return

        if self.resolution_mode == "aspect_ratio":
            # 이미지 비율 적용
            resolution = self._calculate_resolution_from_aspect_ratio(item.file_path)
            self.current_resolution_override = resolution
            print(f"[BatchWindow] 이미지 비율 적용: {resolution}")

        elif self.resolution_mode == "random":
            # 랜덤 해상도
            resolution = self._get_random_resolution()
            self.current_resolution_override = resolution
            print(f"[BatchWindow] 랜덤 해상도: {resolution}")

        elif self.resolution_mode == "control_panel":
            # 컨트롤 패널의 현재 설정 사용 (오버라이드 없음)
            self.current_resolution_override = None
            print("[BatchWindow] 컨트롤 패널 옵션 사용")

    def get_resolution_override(self):
        """해상도 오버라이드 값 반환 (InteractiveWindow에서 호출)"""
        # 순차 생성 중이고 _item_resolutions가 있으면 딕셔너리에서 가져오기
        if hasattr(self, '_item_resolutions') and self.current_generating_index is not None:
            resolution = self._item_resolutions.get(self.current_generating_index)
            print(f"[BatchWindow] get_resolution_override() → 아이템 {self.current_generating_index}: {resolution}")
            return resolution
        # 레거시 방식 (단일 아이템 생성)
        return self.current_resolution_override

    def _calculate_resolution_from_aspect_ratio(self, image_path: str) -> tuple:
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
                # (1024, 1536),  # Tall Portrait: 1,572,864 pixels - 초과!
                # (1536, 1024),  # Wide Landscape: 1,572,864 pixels - 초과!
            ]

            # 픽셀 총합 검증된 해상도만 필터링
            valid_resolutions = [r for r in standard_resolutions if r[0] * r[1] <= MAX_PIXELS]

            if not valid_resolutions:
                print(f"[BatchWindow] ⚠️ 유효한 해상도가 없습니다. 기본값 사용")
                return (1024, 1024)

            # 비율이 가장 가까운 해상도 선택
            best_match = min(valid_resolutions, key=lambda r: abs(r[0]/r[1] - aspect_ratio))

            # 최종 검증
            if best_match[0] * best_match[1] > MAX_PIXELS:
                print(f"[BatchWindow] ⚠️ 해상도 {best_match}의 픽셀 총합이 1,048,576을 초과합니다. 기본값 사용")
                return (1024, 1024)

            return best_match

        except Exception as e:
            print(f"[BatchWindow] 이미지 비율 계산 실패: {e}")
            return (1024, 1024)  # 기본값

    def _get_random_resolution(self) -> tuple:
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


class BatchImageItem(QFrame):
    """배치 처리 개별 아이템 위젯"""

    extraction_requested = pyqtSignal(int)  # index
    generation_requested = pyqtSignal(int)  # index
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
        self.image_label.setFixedSize(get_scaled_size(280), get_scaled_size(280))
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
                    get_scaled_size(280), get_scaled_size(280),
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

        # 초기 상태: WD14 대기중 버튼
        self.btn_waiting = QPushButton("WD14 대기중")
        self.btn_waiting.setEnabled(False)
        self.btn_waiting.setFixedHeight(get_scaled_size(36))
        self.btn_waiting.setStyleSheet(get_button_style(bg_color=DARK_COLORS['border'], text_color=DARK_COLORS['text_secondary']))
        self.button_layout.addWidget(self.btn_waiting)

        # 완료 후 버튼들 (초기에는 숨김)
        action_layout = QHBoxLayout()
        action_layout.setSpacing(4)

        self.btn_extract = QPushButton("추출")
        self.btn_extract.setFixedHeight(get_scaled_size(36))
        self.btn_extract.setStyleSheet(get_button_style(bg_color=DARK_COLORS['accent_blue'], text_color="white"))
        self.btn_extract.clicked.connect(lambda: self.extraction_requested.emit(self.index))
        self.btn_extract.hide()

        self.btn_generate = QPushButton("생성")
        self.btn_generate.setFixedHeight(get_scaled_size(36))
        self.btn_generate.setStyleSheet(get_button_style(bg_color=DARK_COLORS['accent_blue'], text_color="white"))
        self.btn_generate.clicked.connect(lambda: self.generation_requested.emit(self.index))
        self.btn_generate.hide()

        action_layout.addWidget(self.btn_extract)
        action_layout.addWidget(self.btn_generate)

        self.button_layout.addLayout(action_layout)

        layout.addWidget(self.button_container)

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

    def start_extraction(self):
        """태그 추출 시작"""
        print(f"[BatchItem {self.index}] 태그 추출 시작")

        # 처리 중 플래그 설정
        self.is_processing = True

        # 버튼 상태 변경
        self.btn_waiting.setText("추출 중...")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()

        # 워커 스레드 시작
        from ui.interactive.image_tagger_block import TaggerWorker

        try:
            # 부모 윈도우의 Threshold 값 사용
            parent_window = self.window()
            threshold = parent_window.threshold if isinstance(parent_window, BatchImageProcessingWindow) else 0.51

            print(f"[BatchItem {self.index}] Threshold 사용: {threshold}")

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
            self.btn_waiting.setText("태그 없음")
            self.btn_waiting.setEnabled(False)
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

        # UI 업데이트: 대기중 버튼 숨기고, 추출/생성 버튼 표시
        self.btn_waiting.hide()
        self.btn_extract.show()
        self.btn_generate.show()

        # 부모 윈도우에 완료 알림
        parent_window = self.window()
        if isinstance(parent_window, BatchImageProcessingWindow):
            parent_window._on_extraction_completed(self.index, filtered_tags)

    def _on_extraction_error(self, err_msg):
        """추출 에러"""
        self.progress_bar.hide()
        self.is_processing = False  # 처리 완료 (에러)
        self.btn_waiting.setText("오류 발생")
        self.btn_waiting.setEnabled(False)
        print(f"[BatchItem {self.index}] 오류: {err_msg}")
