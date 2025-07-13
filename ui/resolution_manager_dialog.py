from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QListWidget, QMessageBox, QGroupBox
)
from PyQt6.QtGui import QIntValidator
from PyQt6.QtCore import Qt
from .theme import DARK_COLORS, DARK_STYLES

class ResolutionManagerDialog(QDialog):
    """해상도 목록을 관리하는 전용 다이얼로그 위젯"""
    def __init__(self, current_resolutions, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.setWindowTitle("랜덤 해상도 설정")
        self.setMinimumSize(450, 500)
        self.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']}; color: {DARK_COLORS['text_primary']};")

        # UI 요소 초기화
        self.res_list_widget = QListWidget()
        self.width_input = QLineEdit()
        self.height_input = QLineEdit()
        self.area_label = QLabel("0")
        self.anlas_warning_label = QLabel("NAI 생성시 Anals가 소모됩니다.")

        # [신규] 유효성 검사 UI 요소
        self.validation_warning_label = QLabel()
        self.auto_fit_button = QPushButton("자동 맞춤")
        
        # UI 구성
        self.init_ui()
        
        # 초기 데이터 로드
        self.res_list_widget.addItems(current_resolutions)

        # 시그널 연결
        self.width_input.textChanged.connect(self.on_input_changed)
        self.height_input.textChanged.connect(self.on_input_changed)
        self.auto_fit_button.clicked.connect(self.auto_fit_values)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)

        # 1. 해상도 목록 표시 및 제어 영역
        list_group = QGroupBox("현재 목록")
        list_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        list_layout = QHBoxLayout()
        self.res_list_widget.setStyleSheet(DARK_STYLES['compact_textedit'])
        list_layout.addWidget(self.res_list_widget)
        
        remove_button = QPushButton("선택 항목 제거")
        remove_button.setStyleSheet(DARK_STYLES['secondary_button'])
        remove_button.clicked.connect(self.remove_selected_resolution)
        list_layout.addWidget(remove_button)
        list_group.setLayout(list_layout)
        main_layout.addWidget(list_group)

        # 2. 새 해상도 추가 영역
        add_group = QGroupBox("새 해상도 추가")
        add_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        add_layout = QGridLayout()
        add_layout.setSpacing(10)
        
        int_validator = QIntValidator(0, 8192)
        input_style = DARK_STYLES['compact_lineedit']
        self.width_input.setStyleSheet(input_style)
        self.width_input.setValidator(int_validator)
        self.width_input.setProperty("autocomplete_ignore", True)
        self.height_input.setStyleSheet(input_style)
        self.height_input.setValidator(int_validator)
        self.height_input.setProperty("autocomplete_ignore", True)

        add_layout.addWidget(QLabel("너비:"), 0, 0)
        add_layout.addWidget(self.width_input, 0, 1)
        add_layout.addWidget(QLabel("높이:"), 1, 0)
        add_layout.addWidget(self.height_input, 1, 1)
        add_layout.addWidget(QLabel("자동 계산 (면적):"), 2, 0)
        add_layout.addWidget(self.area_label, 2, 1)
        
        add_button = QPushButton("목록에 추가")
        add_button.setStyleSheet(DARK_STYLES['primary_button'])
        add_button.clicked.connect(self.add_resolution)
        add_layout.addWidget(add_button, 0, 2, 2, 1)

        self.anlas_warning_label.setStyleSheet(f"color: {DARK_COLORS['warning']}; font-weight: bold;")
        self.anlas_warning_label.setVisible(False)
        add_layout.addWidget(self.anlas_warning_label, 3, 0, 1, 3)

        validation_layout = QHBoxLayout()
        validation_layout.addWidget(self.validation_warning_label, 1) # 라벨이 남은 공간 차지
        validation_layout.addWidget(self.auto_fit_button)
        add_layout.addLayout(validation_layout, 4, 0, 1, 3)

        add_group.setLayout(add_layout)
        main_layout.addWidget(add_group)

        # 3. 하단 버튼 영역
        button_layout = QHBoxLayout()
        save_button = QPushButton("저장 후 닫기")
        save_button.setStyleSheet(DARK_STYLES['primary_button'])
        save_button.clicked.connect(self.accept)
        cancel_button = QPushButton("취소")
        cancel_button.setStyleSheet(DARK_STYLES['secondary_button'])
        cancel_button.clicked.connect(self.reject)
        
        button_layout.addStretch(1)
        button_layout.addWidget(save_button)
        button_layout.addWidget(cancel_button)
        main_layout.addLayout(button_layout)

    def update_area_label(self):
        try:
            width = int(self.width_input.text())
            height = int(self.height_input.text())
            area = width * height
            self.area_label.setText(f"{area:,}")
            self.anlas_warning_label.setVisible(area > 1048576)
        except ValueError:
            self.area_label.setText("0")
            self.anlas_warning_label.setVisible(False)
            
    def add_resolution(self):
        try:
            width = int(self.width_input.text())
            height = int(self.height_input.text())
            
            api_mode = self.main_window.get_current_api_mode()
            multiple = 64 if api_mode == "NAI" else 8
            if width % multiple != 0 or height % multiple != 0:
                QMessageBox.warning(self, "입력 오류", f"{api_mode} 모드에서는 너비와 높이가 각각 {multiple}의 배수여야 합니다.")
                return

            res_str = f"{width} x {height}"
            if self.res_list_widget.findItems(res_str, Qt.MatchFlag.MatchExactly):
                QMessageBox.warning(self, "입력 오류", "이미 목록에 있는 해상도입니다.")
                return
            
            self.res_list_widget.addItem(res_str)
            self.width_input.clear()
            self.height_input.clear()

        except ValueError:
            QMessageBox.warning(self, "입력 오류", "너비와 높이에 유효한 숫자를 입력하세요.")

    def remove_selected_resolution(self):
        selected_items = self.res_list_widget.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "알림", "제거할 항목을 목록에서 선택하세요.")
            return
        for item in selected_items:
            self.res_list_widget.takeItem(self.res_list_widget.row(item))
            
    def get_updated_resolutions(self):
        return [self.res_list_widget.item(i).text() for i in range(self.res_list_widget.count())]
    
    def on_input_changed(self):
        """입력값 변경 시 호출되는 통합 메서드"""
        self.update_area_label()
        self.update_validation_ui()

    def auto_fit_values(self):
        """'자동 맞춤' 버튼 클릭 시, 너비와 높이를 가장 가까운 배수로 수정합니다."""
        try:
            width = int(self.width_input.text()) if self.width_input.text() else 0
            height = int(self.height_input.text()) if self.height_input.text() else 0
            multiple = 64

            if width != 0 and width % multiple != 0:
                # 0으로 반올림되는 것을 방지하기 위해 최소값을 multiple로 설정
                corrected_width = max(multiple, round(width / multiple) * multiple)
                self.width_input.setText(str(corrected_width))
            
            if height != 0 and height % multiple != 0:
                corrected_height = max(multiple, round(height / multiple) * multiple)
                self.height_input.setText(str(corrected_height))

        except ValueError:
            # 입력값이 숫자가 아니면 아무 작업도 하지 않음
            pass

    def update_validation_ui(self):
        """입력값의 유효성을 검사하고 경고 UI를 업데이트합니다."""
        try:
            width = int(self.width_input.text()) if self.width_input.text() else 0
            height = int(self.height_input.text()) if self.height_input.text() else 0
            
            api_mode = self.main_window.get_current_api_mode()
            multiple = 64 if api_mode == "NAI" else 8

            is_width_valid = (width == 0) or (width % multiple == 0)
            is_height_valid = (height == 0) or (height % multiple == 0)
            
            if is_width_valid and is_height_valid:
                self.validation_warning_label.setVisible(False)
                self.auto_fit_button.setVisible(False)
            else:
                self.validation_warning_label.setText(f"너비와 높이는 {multiple}의 배수여야 합니다.")
                self.validation_warning_label.setVisible(True)
                self.auto_fit_button.setVisible(True)
        except ValueError:
            self.validation_warning_label.setVisible(False)
            self.auto_fit_button.setVisible(False)