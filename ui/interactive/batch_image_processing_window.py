# ui/interactive/batch_image_processing_window.py
"""
Batch Image Processing Window - 여러 이미지를 순차적으로 WD14 태그 추출 및 생성
"""

import os
from typing import List, Optional
from PIL import Image

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QGridLayout, QLabel, QPushButton, QProgressBar, QFrame, QRadioButton, 
    QButtonGroup, QCheckBox, QComboBox, QTextEdit, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject, QTimer
from PyQt6.QtGui import QPixmap

from ui.theme import DARK_COLORS
from ui.scaling_manager import get_scaled_size, get_scaled_font_size
from ui.interactive.interactive_theme import COMMON_STYLES, get_button_style, FONT_FAMILY
from legacy_desktop.core.ollama_service import OllamaService, OllamaWorker


class BatchImageProcessingWindow(QMainWindow):
    """배치 이미지 처리 윈도우"""

    def __init__(self, file_paths: List[str], quick_search_block=None, main_prompt_block=None, app_context=None, parent=None):
        super().__init__(parent)
        self.file_paths = file_paths
        self.quick_search_block = quick_search_block
        self.main_prompt_block = main_prompt_block
        self.app_context = app_context
        
        # Ollama 서비스 초기화
        self.ollama_service = OllamaService()

        # 처리 큐 (태그 추출용)
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
        
        # Ollama 워커 참조
        self.ollama_worker = None

        self.setWindowTitle(f"배치 이미지 처리 - {len(file_paths)}개 이미지")
        self.setMinimumSize(get_scaled_size(1200), get_scaled_size(900))

        # 다크 테마 적용
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        self._init_ui()

    def closeEvent(self, event):
        """윈도우 닫기 시 정리"""
        print("[BatchWindow] 윈도우 닫기 - 리소스 정리 시작")

        if self.is_sequential_generating:
            self._cancel_sequential_generation()

        if self.ollama_worker and self.ollama_worker.isRunning():
            self.ollama_worker.terminate()
            self.ollama_worker.wait()

        for item in self.item_widgets:
            if item and hasattr(item, 'worker') and item.worker:
                if item.worker.isRunning():
                    item.worker.terminate()
                    item.worker.wait()

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

        header_label = QLabel(f"📦 배치 이미지 처리 - 총 {len(self.file_paths)}개 이미지")
        header_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(18)}px; font-weight: bold;")
        header_layout.addWidget(header_label)

        # 설정 영역 (Threshold + 시작 버튼)
        settings_layout = QHBoxLayout()
        settings_layout.setSpacing(get_scaled_size(8))

        lbl_th = QLabel("WD14 Threshold:")
        lbl_th.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(14)}px;")
        settings_layout.addWidget(lbl_th)

        from PyQt6.QtWidgets import QButtonGroup
        from ui.interactive.image_tagger_block import ThresholdButton

        self.threshold_group = QButtonGroup(self)
        for val in [0.51, 0.61, 0.71]:
            btn = ThresholdButton(str(val), val)
            if val == 0.51: btn.setChecked(True)
            self.threshold_group.addButton(btn)
            settings_layout.addWidget(btn)

        self.threshold_group.buttonClicked.connect(self._on_threshold_changed)

        settings_layout.addSpacing(get_scaled_size(20))

        self.btn_start_extraction = QPushButton("⚡ 태그 추출 시작")
        self.btn_start_extraction.setFixedHeight(get_scaled_size(36))
        self.btn_start_extraction.setStyleSheet(get_button_style(bg_color=DARK_COLORS['accent_blue'], text_color="white"))
        self.btn_start_extraction.clicked.connect(self._start_batch_extraction)
        settings_layout.addWidget(self.btn_start_extraction)

        settings_layout.addStretch()
        header_layout.addLayout(settings_layout)
        main_layout.addWidget(header_widget)

        # 스크롤 영역 (이미지 그리드)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(f"QScrollArea {{ border: none; background-color: {DARK_COLORS['bg_secondary']}; }}")

        scroll_content = QWidget()
        self.grid_layout = QGridLayout(scroll_content)
        self.grid_layout.setSpacing(16)

        for i, file_path in enumerate(self.file_paths):
            item_widget = BatchImageItem(file_path, i, self.quick_search_block)
            item_widget.extraction_requested.connect(lambda idx=i: self._on_extraction_requested(idx))
            item_widget.generation_requested.connect(lambda idx=i: self._on_generation_requested(idx))
            item_widget.close_requested.connect(self._on_item_close_requested)

            self.grid_layout.addWidget(item_widget, i // 3, i % 3)
            self.item_widgets.append(item_widget)
            self.processing_queue.append(i)

        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)

        # === 하단: 생성 설정 섹션 ===
        self._init_generation_settings_section(main_layout)

    def _init_generation_settings_section(self, parent_layout):
        """생성 및 백엔드 설정 섹션"""
        section_frame = QFrame()
        section_frame.setStyleSheet(f"QFrame {{ background-color: {DARK_COLORS['bg_secondary']}; border: 1px solid {DARK_COLORS['border']}; border-radius: 8px; }}")
        section_layout = QVBoxLayout(section_frame)
        section_layout.setContentsMargins(16, 12, 16, 12)
        section_layout.setSpacing(12)

        # 1. 헤더
        header_layout = QHBoxLayout()
        title_label = QLabel("🎬 생성 및 백엔드 설정")
        title_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(16)}px; font-weight: bold;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        
        self.lbl_generation_status = QLabel("")
        header_layout.addWidget(self.lbl_generation_status)
        section_layout.addLayout(header_layout)

        # 2. 해상도 및 백엔드
        top_row = QHBoxLayout()
        
        # 해상도
        res_label = QLabel("해상도:")
        top_row.addWidget(res_label)
        self.resolution_group = QButtonGroup(self)
        for mode, label in [("aspect_ratio", "이미지 비율"), ("random", "랜덤"), ("control_panel", "컨트롤 패널")]:
            rb = QRadioButton(label)
            if mode == "aspect_ratio": rb.setChecked(True)
            self.resolution_group.addButton(rb)
            top_row.addWidget(rb)
        self.resolution_group.buttonClicked.connect(self._on_resolution_mode_changed)

        top_row.addSpacing(20)

        # 백엔드
        be_label = QLabel("백엔드:")
        top_row.addWidget(be_label)
        self.combo_backend = QComboBox()
        self.combo_backend.addItems(["Follow Global", "NovelAI", "ComfyUI"])
        self.combo_backend.setFixedWidth(get_scaled_size(120))
        top_row.addWidget(self.combo_backend)

        top_row.addStretch()
        section_layout.addLayout(top_row)

        # 3. Ollama 설정
        ollama_frame = QFrame()
        ollama_frame.setStyleSheet(f"QFrame {{ background-color: {DARK_COLORS['bg_primary']}; border: 1px solid {DARK_COLORS['border']}; border-radius: 6px; }}")
        ollama_layout = QVBoxLayout(ollama_frame)
        
        ollama_header = QHBoxLayout()
        self.chk_use_ollama = QCheckBox("🦙 Ollama 프롬프트 정제")
        self.chk_use_ollama.setStyleSheet("font-weight: bold;")
        self.chk_use_ollama.stateChanged.connect(self._on_ollama_toggled)
        ollama_header.addWidget(self.chk_use_ollama)

        self.combo_ollama_model = QComboBox()
        self.combo_ollama_model.setFixedWidth(get_scaled_size(200))
        self.combo_ollama_model.setEnabled(False)
        ollama_header.addWidget(self.combo_ollama_model)
        
        self.btn_refresh_ollama = QPushButton("🔄")
        self.btn_refresh_ollama.setFixedWidth(get_scaled_size(30))
        self.btn_refresh_ollama.setEnabled(False)
        self.btn_refresh_ollama.clicked.connect(self._refresh_ollama_models)
        ollama_header.addWidget(self.btn_refresh_ollama)
        
        ollama_header.addStretch()
        ollama_layout.addLayout(ollama_header)

        self.txt_ollama_system = QTextEdit()
        self.txt_ollama_system.setPlaceholderText("Ollama 시스템 프롬프트...")
        self.txt_ollama_system.setFixedHeight(get_scaled_size(50))
        self.txt_ollama_system.setEnabled(False)
        self.txt_ollama_system.setPlainText("Convert these WD14 tags into a descriptive and natural image prompt. Output only the prompt.")
        ollama_layout.addWidget(self.txt_ollama_system)
        
        section_layout.addWidget(ollama_frame)

        # 4. 하단 버튼
        bottom_row = QHBoxLayout()
        self.chk_auto_remove = QCheckBox("생성 완료 시 목록에서 삭제")
        self.chk_auto_remove.stateChanged.connect(self._on_auto_remove_changed)
        bottom_row.addWidget(self.chk_auto_remove)
        
        bottom_row.addStretch()
        
        self.btn_sequential_start = QPushButton("🎬 순차 생성 시작")
        self.btn_sequential_start.setFixedHeight(get_scaled_size(40))
        self.btn_sequential_start.setFixedWidth(get_scaled_size(160))
        self.btn_sequential_start.setStyleSheet(get_button_style(bg_color=DARK_COLORS['accent_blue'], text_color="white"))
        self.btn_sequential_start.clicked.connect(self._start_sequential_generation)
        bottom_row.addWidget(self.btn_sequential_start)

        self.btn_sequential_cancel = QPushButton("⏹ 취소")
        self.btn_sequential_cancel.setFixedHeight(get_scaled_size(40))
        self.btn_sequential_cancel.setFixedWidth(get_scaled_size(100))
        self.btn_sequential_cancel.setStyleSheet(get_button_style(bg_color=DARK_COLORS['error'], text_color="white"))
        self.btn_sequential_cancel.clicked.connect(self._cancel_sequential_generation)
        self.btn_sequential_cancel.hide()
        bottom_row.addWidget(self.btn_sequential_cancel)
        
        section_layout.addLayout(bottom_row)
        parent_layout.addWidget(section_frame)

    # === 이벤트 핸들러 ===

    def _on_threshold_changed(self):
        checked = self.threshold_group.checkedButton()
        if checked: self.threshold = checked.value

    def _on_resolution_mode_changed(self):
        btn = self.resolution_group.checkedButton()
        if not btn: return
        label = btn.text()
        if "비율" in label: self.resolution_mode = "aspect_ratio"
        elif "랜덤" in label: self.resolution_mode = "random"
        else: self.resolution_mode = "control_panel"

    def _on_auto_remove_changed(self, state):
        self.auto_remove_completed = (state == Qt.CheckState.Checked.value)

    def _on_ollama_toggled(self, state):
        enabled = (state == Qt.CheckState.Checked.value)
        self.combo_ollama_model.setEnabled(enabled)
        self.btn_refresh_ollama.setEnabled(enabled)
        self.txt_ollama_system.setEnabled(enabled)
        if enabled and self.combo_ollama_model.count() == 0:
            self._refresh_ollama_models()

    def _refresh_ollama_models(self):
        models = self.ollama_service.get_models()
        self.combo_ollama_model.clear()
        if models:
            self.combo_ollama_model.addItems(models)
        else:
            self.combo_ollama_model.addItem("Ollama 미연결")

    # === 태그 추출 로직 ===

    def _start_batch_extraction(self):
        print("[BatchWindow] 배치 태그 추출 시작")
        self.btn_start_extraction.setEnabled(False)
        self.btn_start_extraction.setText("추출 중...")
        self._process_next_extraction()

    def _process_next_extraction(self):
        if not self.processing_queue:
            print("[BatchWindow] 모든 태그 추출 완료")
            self.btn_start_extraction.setEnabled(True)
            self.btn_start_extraction.setText("⚡ 태그 추출 시작")
            return

        idx = self.processing_queue[0]
        item = self.item_widgets[idx]
        if item:
            item.start_extraction()
        else:
            self.processing_queue.pop(0)
            self._process_next_extraction()

    def _on_extraction_completed(self, index: int, tags: str):
        if index in self.processing_queue:
            self.processing_queue.remove(index)
        self._process_next_extraction()

    def _on_extraction_requested(self, index: int):
        item = self.item_widgets[index]
        if item and item.extracted_tags:
            formatted_html = self.main_prompt_block._format_prompt_with_categories(item.extracted_tags)
            self.main_prompt_block.set_prompt_html(formatted_html)

    def _on_generation_requested(self, index: int):
        item = self.item_widgets[index]
        if item and item.extracted_tags:
            self._on_extraction_requested(index)
            self.main_prompt_block.trigger_generation()

    def _on_item_close_requested(self, index: int):
        item = self.item_widgets[index]
        if not item: return
        
        if self.current_generating_index == index:
            QMessageBox.warning(self, "경고", "현재 생성 중인 아이템은 삭제할 수 없습니다.")
            return

        self.grid_layout.removeWidget(item)
        item.setParent(None)
        item.deleteLater()
        self.item_widgets[index] = None
        if index in self.processing_queue: self.processing_queue.remove(index)
        if index in self.sequential_generation_queue: self.sequential_generation_queue.remove(index)

    # === 순차 생성 로직 (Refactored) ===

    def _start_sequential_generation(self):
        self.sequential_generation_queue = [i for i, item in enumerate(self.item_widgets) if item and item.extracted_tags]
        if not self.sequential_generation_queue:
            QMessageBox.warning(self, "알림", "태그 추출이 완료된 아이템이 없습니다.")
            return

        self.is_sequential_generating = True
        self.btn_sequential_start.hide()
        self.btn_sequential_cancel.show()
        
        if self.app_context and not self._generation_callback_registered:
            self.app_context.subscribe("generation_completed_for_interactive", self._on_batch_generation_completed)
            self._generation_callback_registered = True

        self._process_next_sequential_step()

    def _cancel_sequential_generation(self):
        self.is_sequential_generating = False
        self.sequential_generation_queue.clear()
        self.current_generating_index = None
        self.btn_sequential_start.show()
        self.btn_sequential_cancel.hide()
        self.lbl_generation_status.setText("취소됨")
        if self.ollama_worker and self.ollama_worker.isRunning():
            self.ollama_worker.terminate()

    def _process_next_sequential_step(self):
        if not self.is_sequential_generating or not self.sequential_generation_queue:
            self._finish_sequential_generation()
            return

        idx = self.sequential_generation_queue[0]
        self.current_generating_index = idx
        item = self.item_widgets[idx]
        
        total = len(self.item_widgets)
        completed = total - len(self.sequential_generation_queue)
        self.lbl_generation_status.setText(f"⏳ {completed}/{total} 처리 중...")

        if self.chk_use_ollama.isChecked():
            self._run_ollama_refinement(idx, item.extracted_tags)
        else:
            self._trigger_generation(idx, item.extracted_tags)

    def _run_ollama_refinement(self, idx, tags):
        model = self.combo_ollama_model.currentText()
        system = self.txt_ollama_system.toPlainText()
        
        item = self.item_widgets[idx]
        item.btn_waiting.setText("🦙 Ollama...")
        item.btn_waiting.show()
        item.btn_extract.hide()
        item.btn_generate.hide()

        self.ollama_worker = OllamaWorker(tags, model=model, system_prompt=system)
        self.ollama_worker.finished.connect(lambda prompt: self._on_ollama_finished(idx, prompt))
        self.ollama_worker.error.connect(lambda err: self._on_ollama_error(idx, err))
        self.ollama_worker.start()

    def _on_ollama_finished(self, idx, refined_prompt):
        print(f"[Batch] Ollama 정제 완료: {refined_prompt[:50]}...")
        self._trigger_generation(idx, refined_prompt)

    def _on_ollama_error(self, idx, err):
        print(f"[Batch] Ollama 에러: {err}")
        # 에러 시 원본 태그로 진행
        item = self.item_widgets[idx]
        self._trigger_generation(idx, item.extracted_tags)

    def _trigger_generation(self, idx, prompt):
        item = self.item_widgets[idx]
        
        # UI 업데이트
        formatted_html = self.main_prompt_block._format_prompt_with_categories(prompt)
        self.main_prompt_block.set_prompt_html(formatted_html)
        
        # 해상도 오버라이드
        self._apply_resolution_for_item(idx)
        
        # 백엔드 강제 설정 (필요시)
        backend = self.combo_backend.currentText()
        if backend == "NovelAI": self.app_context.set_api_mode("NAI")
        elif backend == "ComfyUI": self.app_context.set_api_mode("COMFYUI")
        
        item.btn_waiting.setText("🎨 생성 중...")
        item.btn_waiting.show()
        
        print(f"[Batch] 아이템 {idx} 생성 트리거")
        self.main_prompt_block.trigger_generation()
        # _on_batch_generation_completed 에서 다음 단계로

    def _on_batch_generation_completed(self, result):
        if not self.is_sequential_generating: return
        
        idx = self.current_generating_index
        if idx is not None:
            item = self.item_widgets[idx]
            if item:
                item.btn_waiting.hide()
                item.btn_generate.setText("✅ 완료")
                item.btn_generate.setStyleSheet(get_button_style(bg_color="#2d7a4f", text_color="white"))
                item.btn_generate.show()
                item.btn_extract.show()
                
                self._force_update_interactive_image(result)
                
                if self.auto_remove_completed:
                    self._on_item_close_requested(idx)

        if self.sequential_generation_queue:
            self.sequential_generation_queue.pop(0)
            
        # 다음 단계
        QTimer.singleShot(500, self._process_next_sequential_step)

    def _finish_sequential_generation(self):
        self.is_sequential_generating = False
        self.current_generating_index = None
        self.btn_sequential_start.show()
        self.btn_sequential_cancel.hide()
        self.lbl_generation_status.setText("✅ 모든 작업 완료")

    # === 유틸리티 ===

    def _force_update_interactive_image(self, result):
        try:
            pil_image = None
            if hasattr(result, 'mode'): pil_image = result
            elif isinstance(result, dict) and 'image' in result: pil_image = result['image']
            
            if not pil_image: return

            # Interactive Window 찾기
            win = self.parent()
            while win:
                if hasattr(win, 'image_plane'):
                    win.image_plane.set_image(pil_image)
                    break
                win = win.parent() if hasattr(win, 'parent') else None
        except: pass

    def _apply_resolution_for_item(self, index: int):
        item = self.item_widgets[index]
        if not item: return

        if self.resolution_mode == "aspect_ratio":
            self.current_resolution_override = self._calculate_resolution_from_aspect_ratio(item.file_path)
        elif self.resolution_mode == "random":
            self.current_resolution_override = self._get_random_resolution()
        else:
            self.current_resolution_override = None

    def get_resolution_override(self):
        return self.current_resolution_override

    def _calculate_resolution_from_aspect_ratio(self, image_path: str) -> tuple:
        try:
            with Image.open(image_path) as img:
                w, h = img.size
            aspect = w / h
            # NAI Standard
            standard = [(832, 1216), (1216, 832), (1024, 1024)]
            return min(standard, key=lambda r: abs(r[0]/r[1] - aspect))
        except: return (1024, 1024)

    def _get_random_resolution(self) -> tuple:
        import random
        return random.choice([(832, 1216), (1216, 832), (1024, 1024)])


class BatchImageItem(QFrame):
    """배치 처리 개별 아이템 위젯"""
    extraction_requested = pyqtSignal(int)
    generation_requested = pyqtSignal(int)
    close_requested = pyqtSignal(int)

    def __init__(self, file_path: str, index: int, quick_search_block=None, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.index = index
        self.quick_search_block = quick_search_block
        self.extracted_tags = None
        self.worker = None
        self.is_processing = False

        self.setFixedSize(get_scaled_size(320), get_scaled_size(420))
        self.setStyleSheet(f"QFrame {{ background-color: {DARK_COLORS['bg_primary']}; border: 1px solid {DARK_COLORS['border']}; border-radius: 8px; padding: 8px; }}")
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Header
        header = QHBoxLayout()
        header.addStretch()
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(get_scaled_size(24), get_scaled_size(24))
        btn_close.setStyleSheet(f"QPushButton {{ background: transparent; color: {DARK_COLORS['text_secondary']}; border: none; font-size: {get_scaled_font_size(16)}px; font-weight: bold; }} QPushButton:hover {{ color: {DARK_COLORS['error']}; }}")
        btn_close.clicked.connect(lambda: self.close_requested.emit(self.index))
        header.addWidget(btn_close)
        layout.addLayout(header)

        # Image
        self.image_label = QLabel()
        self.image_label.setFixedSize(get_scaled_size(280), get_scaled_size(280))
        self.image_label.setStyleSheet(f"background-color: {DARK_COLORS['bg_secondary']}; border: 1px solid {DARK_COLORS['border']}; border-radius: 4px;")
        try:
            pix = QPixmap(self.file_path)
            if not pix.isNull():
                self.image_label.setPixmap(pix.scaled(280, 280, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        except: pass
        layout.addWidget(self.image_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # Filename
        name_lbl = QLabel(os.path.basename(self.file_path))
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(11)}px;")
        name_lbl.setWordWrap(True)
        layout.addWidget(name_lbl)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(get_scaled_size(6))
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # Buttons
        self.btn_container = QWidget()
        self.btn_container.setFixedHeight(get_scaled_size(40))
        btn_layout = QHBoxLayout(self.btn_container)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        
        self.btn_waiting = QPushButton("WD14 대기중")
        self.btn_waiting.setEnabled(False)
        self.btn_waiting.setFixedHeight(get_scaled_size(36))
        self.btn_waiting.setStyleSheet(get_button_style(bg_color=DARK_COLORS['border'], text_color=DARK_COLORS['text_secondary']))
        btn_layout.addWidget(self.btn_waiting)

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

        btn_layout.addWidget(self.btn_extract)
        btn_layout.addWidget(self.btn_generate)
        layout.addWidget(self.btn_container)

    def start_extraction(self):
        self.is_processing = True
        self.btn_waiting.setText("추출 중...")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()

        from ui.interactive.image_tagger_block import TaggerWorker
        try:
            parent = self.window()
            th = parent.threshold if hasattr(parent, 'threshold') else 0.51
            img = Image.open(self.file_path).convert("RGB")
            self.worker = TaggerWorker(img, general_th=th)
            self.worker.finished.connect(self._on_extraction_finished)
            self.worker.error.connect(lambda e: self._on_extraction_error(e))
            self.worker.start()
        except Exception as e:
            self._on_extraction_error(str(e))

    def _on_extraction_finished(self, result):
        self.progress_bar.hide()
        self.is_processing = False
        tags = result.get("general", [])
        if not tags:
            self.btn_waiting.setText("태그 없음")
            return

        cleaned = [t[0].replace("_", " ") for t in tags]
        self.extracted_tags = ", ".join(cleaned)
        
        self.btn_waiting.hide()
        self.btn_extract.show()
        self.btn_generate.show()
        
        parent = self.window()
        if hasattr(parent, '_on_extraction_completed'):
            parent._on_extraction_completed(self.index, self.extracted_tags)

    def _on_extraction_error(self, err):
        self.progress_bar.hide()
        self.is_processing = False
        self.btn_waiting.setText("오류")
        print(f"Error: {err}")