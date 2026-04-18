from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QWidget, 
    QLineEdit, QCheckBox, QRadioButton, QPushButton,
    QButtonGroup, QFrame, QMessageBox
)
from PyQt6.QtCore import QTimer, QObject, pyqtSignal, QThread, Qt
from PyQt6.QtWidgets import QApplication
from interfaces.base_module import BaseMiddleModule
from ui.theme import get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size
import os
import json
import random
import subprocess
import platform

class DelayCountdownThread(QThread):
    """지연 시간 카운트다운을 시각화하는 스레드"""
    
    progress_updated = pyqtSignal(str)
    countdown_finished = pyqtSignal()
    
    def __init__(self, delay_seconds: float):
        super().__init__()
        self.delay_seconds = delay_seconds
        self.remaining_time = delay_seconds
        self.is_running = True
    
    def run(self):
        """카운트다운 실행"""
        import time
        # 카운트다운 시작
        
        # 즉시 첫 업데이트 표시
        self.progress_updated.emit(f"⏱️ 지연: {self.remaining_time:.1f}초 후 다음 생성")
        
        while self.remaining_time > 0 and self.is_running:
            # 0.1초 단위로 감소
            time.sleep(0.1)
            self.remaining_time -= 0.1
            
            if self.remaining_time > 0 and self.is_running:
                self.progress_updated.emit(f"⏱️ 지연: {self.remaining_time:.1f}초 후 다음 생성")
            
        if self.is_running:
            # 카운트다운 완료
            self.countdown_finished.emit()
        else:
            pass
            # 카운트다운 중단됨
    
    def stop(self):
        """스레드 중지"""
        self.is_running = False

class AutomationController(QObject):
    """자동화 타이머 및 카운터를 관리하는 컨트롤러"""
    
    automation_finished = pyqtSignal()
    progress_updated = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_progress)
        self.timer.moveToThread(QApplication.instance().thread())  # 메인 스레드로 이동
        
        # 자동화 설정
        self.automation_type = "unlimited"
        self.timer_minutes = 0
        self.remaining_seconds = 0
        self.count_limit = 0
        self.remaining_count = 0
        
        # 종료 옵션
        self.shutdown_on_finish = False
        self.notify_on_finish = True
        
        # 실행 상태
        self.is_running = False
        
    def start_automation(self, automation_type: str, timer_minutes: int = 0, count_limit: int = 0,
                        shutdown_on_finish: bool = False, notify_on_finish: bool = True):
        """자동화를 시작합니다."""
        self.automation_type = automation_type
        self.timer_minutes = timer_minutes
        self.count_limit = count_limit
        self.shutdown_on_finish = shutdown_on_finish
        self.notify_on_finish = notify_on_finish
        
        if automation_type == "timer":
            self.remaining_seconds = timer_minutes * 60
            self.timer.start(1000)  # 1초마다 업데이트
            print(f"🕒 타이머 시작: {timer_minutes}분 ({self.remaining_seconds}초)")
        elif automation_type == "count":
            self.remaining_count = count_limit
            print(f"🔢 횟수 제한 시작: {count_limit}회")
        
        self.is_running = True
        self.update_progress()  # 초기 상태 표시
        
    def stop_automation(self):
        """자동화를 중단합니다."""
        self.timer.stop()
        self.is_running = False
        self.progress_updated.emit("🛑 자동화 중단됨")
        
    def update_progress(self):
        """진행 상황을 업데이트합니다."""
        if self.automation_type == "timer":
            if self.remaining_seconds <= 0:
                self.finish_automation()
                return
                
            hours = self.remaining_seconds // 3600
            minutes = (self.remaining_seconds % 3600) // 60
            seconds = self.remaining_seconds % 60
            
            if hours > 0:
                time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            else:
                time_str = f"{minutes:02d}:{seconds:02d}"
                
            status_text = f"⏰ 자동화 진행 중 ({time_str} 남음)"
            self.progress_updated.emit(status_text)
            self.remaining_seconds -= 1
            
        elif self.automation_type == "count":
            status_text = f"🔢 자동화 진행 중 ({self.remaining_count}회 남음)"
            self.progress_updated.emit(status_text)
            
        elif self.automation_type == "unlimited":
            self.progress_updated.emit("♾️ 자동화 진행 중 (무제한)")
    
    def decrement_count(self):
        """카운트 기반 자동화에서 카운트를 감소시킵니다."""
        if self.automation_type == "count" and self.is_running:
            self.remaining_count -= 1
            if self.remaining_count <= 0:
                self.finish_automation()
            else:
                self.update_progress()
    
    def finish_automation(self):
        """자동화를 완료합니다."""
        self.timer.stop()
        self.is_running = False
        self.progress_updated.emit("✅ 자동화 완료")

        # 시그널 발행 (AutomationModule에서 체크박스 해제 및 알림 처리)
        self.automation_finished.emit()

        # 시스템 종료 기능 비활성화 (리스크 방지)
        # if self.shutdown_on_finish:
        #     self.shutdown_system()

    def shutdown_system(self):
        """시스템 종료를 실행합니다."""
        try:
            system = platform.system()
            if system == "Windows":
                subprocess.run(["shutdown", "/s", "/t", "120"])
            elif system == "Linux" or system == "Darwin":
                subprocess.run(["sudo", "shutdown", "-h", "+2"])
        except Exception as e:
            print(f"시스템 종료 오류: {e}")


class AutomationModule(BaseMiddleModule):
    """⚙️ 자동화 설정 모듈"""
    
    def __init__(self):
        super().__init__()
        
        # 🆕 필수 호환성 플래그 추가
        self.NAI_compatibility = True
        self.WEBUI_compatibility = True
        self.ignore_save_load = True 
        
        # 콜백 함수들
        self.automation_status_callback = None
        self.generation_delay_callback = None
        self.get_auto_generate_status_callback = None
        self.get_automation_active_status_callback = None
        self.automation_controller = AutomationController()
        self.settings_file = os.path.join('save', 'AutomationModule.json')
        
        # 설정 변수들
        self.delay_seconds = 2.0
        self.random_delay = False
        self.repeat_count = 1
        
        # UI 위젯들
        self.delay_input = None
        self.random_delay_checkbox = None
        self.repeat_input = None
        self.automation_type_group = None
        self.timer_input = None
        self.count_input = None
        self.shutdown_checkbox = None
        self.notify_checkbox = None
        
        # 시그널 연결
        self.automation_controller.automation_finished.connect(self.on_automation_finished)
        self.automation_controller.progress_updated.connect(self.on_progress_updated)
    
    def get_title(self) -> str:
        return "⚙️ 자동화 설정"
    
    def get_order(self) -> int:
        return 1
    
    # 🆕 누락된 메서드 추가
    def initialize_with_context(self, context):
        """AppContext와 연결"""
        self.context = context  # 기존 코드 호환성
        self.app_context = context  # 새로운 모드 시스템용
    
    def create_widget(self, parent: QWidget) -> QWidget:
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)
        
        # 스타일 정의
        if parent and hasattr(parent, 'get_dark_style'):
            label_style = parent.get_dark_style('label_style')
            checkbox_style = parent.get_dark_style('dark_checkbox')
        else:
            label_style = ""
            checkbox_style = ""
        
        # 동적 스타일 가져오기
        dynamic_styles = get_dynamic_styles()
        input_style = dynamic_styles.get('input_field', "")
        
        # 자동화 설정 위젯 생성
        automation_widget = self.create_automation_widget(parent, label_style, checkbox_style, input_style)
        layout.addWidget(automation_widget)
        
        # 🆕 생성된 위젯 저장 (가시성 제어용)
        self.widget = widget
        
        # 🆕 현재 모드에 따른 가시성 설정
        if hasattr(self, 'app_context') and self.app_context:
            current_mode = self.app_context.get_api_mode()
            should_be_visible = (
                (current_mode == "NAI" and self.NAI_compatibility) or
                (current_mode == "WEBUI" and self.WEBUI_compatibility)
            )
            widget.setVisible(should_be_visible)
        
        return widget
    
    def create_automation_widget(self, parent, label_style, checkbox_style, input_style) -> QWidget:
        """자동화 설정 위젯 생성 (기존 코드 유지)"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)
        
        # === 지연 시간 설정 섹션 ===
        delay_frame = QFrame(widget)
        delay_frame.setFrameStyle(QFrame.Shape.Box)
        delay_layout = QVBoxLayout(delay_frame)
        
        delay_title = QLabel("🕐 생성 지연 설정")
        delay_title.setStyleSheet(f"{label_style} font-weight: bold; font-size: {get_scaled_font_size(14)}px;")
        delay_layout.addWidget(delay_title)
        
        delay_grid = QGridLayout()
        
        delay_label = QLabel("생성당 지연시간 (초):")
        delay_label.setStyleSheet(label_style)
        delay_grid.addWidget(delay_label, 0, 0)
        
        self.delay_input = QLineEdit(str(self.delay_seconds))
        self.delay_input.setStyleSheet(input_style)
        self.delay_input.setProperty("autocomplete_ignore", True)  # 자동완성 무시
        self.delay_input.textChanged.connect(self.on_delay_text_changed)
        delay_grid.addWidget(self.delay_input, 0, 1)
        
        # 랜덤 지연시간을 아래로 배치
        self.random_delay_checkbox = QCheckBox("랜덤 지연시간 (±50%)")
        self.random_delay_checkbox.setStyleSheet(checkbox_style)
        self.random_delay_checkbox.setChecked(self.random_delay)
        delay_grid.addWidget(self.random_delay_checkbox, 1, 0, 1, 2)
        
        repeat_label = QLabel("동일 이미지 반복 생성 횟수:")
        repeat_label.setStyleSheet(label_style)
        delay_grid.addWidget(repeat_label, 2, 0)
        
        self.repeat_input = QLineEdit(str(self.repeat_count))
        self.repeat_input.setStyleSheet(input_style)
        self.repeat_input.setProperty("autocomplete_ignore", True)  # 자동완성 무시
        delay_grid.addWidget(self.repeat_input, 2, 1)
        
        repeat_info_label = QLabel("* 자동 생성 상태일때만 작동합니다")
        repeat_info_label.setStyleSheet(f"{label_style} color: #888888; font-size: {get_scaled_font_size(11)}px; font-style: italic;")
        delay_grid.addWidget(repeat_info_label, 3, 0, 1, 2)
        
        delay_layout.addLayout(delay_grid)
        layout.addWidget(delay_frame)
        
        # === 자동화 종료 조건 섹션 ===
        automation_frame = QFrame(widget)
        automation_frame.setFrameStyle(QFrame.Shape.Box)
        automation_layout = QVBoxLayout(automation_frame)
        
        automation_title = QLabel("⏰ 자동화 종료 조건")
        automation_title.setStyleSheet(f"{label_style} font-weight: bold; font-size: {get_scaled_font_size(14)}px;")
        automation_layout.addWidget(automation_title)
        
        # 라디오 버튼 그룹
        self.automation_type_group = QButtonGroup()
        
        radio_layout = QHBoxLayout()
        
        self.unlimited_radio = QRadioButton("무제한")
        self.unlimited_radio.setStyleSheet(checkbox_style)
        self.unlimited_radio.setChecked(True)
        self.automation_type_group.addButton(self.unlimited_radio, 0)
        radio_layout.addWidget(self.unlimited_radio)
        
        self.timer_radio = QRadioButton("시간 제한")
        self.timer_radio.setStyleSheet(checkbox_style)
        self.automation_type_group.addButton(self.timer_radio, 1)
        radio_layout.addWidget(self.timer_radio)
        
        self.count_radio = QRadioButton("횟수 제한")
        self.count_radio.setStyleSheet(checkbox_style)
        self.automation_type_group.addButton(self.count_radio, 2)
        radio_layout.addWidget(self.count_radio)
        
        automation_layout.addLayout(radio_layout)
        
        # 조건별 입력 필드
        condition_grid = QGridLayout()
        
        # 시간 제한 옵션
        self.timer_label = QLabel("자동화 시간 (분):")
        self.timer_label.setStyleSheet(label_style)
        condition_grid.addWidget(self.timer_label, 0, 0)
        
        self.timer_input = QLineEdit("60")
        self.timer_input.setStyleSheet(input_style)
        self.timer_input.setProperty("autocomplete_ignore", True)  # 자동완성 무시
        condition_grid.addWidget(self.timer_input, 0, 1)
        
        # 횟수 제한 옵션
        self.count_label = QLabel("생성 횟수:")
        self.count_label.setStyleSheet(label_style)
        condition_grid.addWidget(self.count_label, 1, 0)
        
        self.count_input = QLineEdit("100")
        self.count_input.setStyleSheet(input_style)
        self.count_input.setProperty("autocomplete_ignore", True)  # 자동완성 무시
        condition_grid.addWidget(self.count_input, 1, 1)
        
        automation_layout.addLayout(condition_grid)
        
        # === 완료 시 동작 섹션 ===
        finish_layout = QVBoxLayout()
        
        self.shutdown_checkbox = QCheckBox("완료 시 시스템 종료")
        self.shutdown_checkbox.setStyleSheet(checkbox_style)
        finish_layout.addWidget(self.shutdown_checkbox)
        
        self.notify_checkbox = QCheckBox("완료 시 알림 표시")
        self.notify_checkbox.setStyleSheet(checkbox_style)
        self.notify_checkbox.setChecked(True)
        finish_layout.addWidget(self.notify_checkbox)
        
        # 완료 시 동작 섹션을 프레임으로 감싸기
        self.finish_frame = QFrame()
        self.finish_frame.setLayout(finish_layout)
        # 시스템 종료 기능 숨김 처리
        self.finish_frame.setVisible(False)
        automation_layout.addWidget(self.finish_frame)
        
        layout.addWidget(automation_frame)
        
        # === 제어 버튼 섹션 ===
        button_layout = QHBoxLayout()
        
        self.start_button = QPushButton("자동화 적용")
        self.start_button.setStyleSheet(f"""
            QPushButton {{
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: {get_scaled_font_size(14)}px;
            }}
            QPushButton:hover {{
                background-color: #45a049;
            }}
            QPushButton:pressed {{
                background-color: #3d8b40;
            }}
            QPushButton:disabled {{
                background-color: #666666;
                color: #999999;
            }}
        """)
        self.start_button.clicked.connect(self.start_automation)
        button_layout.addWidget(self.start_button)
        
        self.stop_button = QPushButton("자동화 중단")
        self.stop_button.setStyleSheet(f"""
            QPushButton {{
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: {get_scaled_font_size(14)}px;
            }}
            QPushButton:hover {{
                background-color: #da190b;
            }}
            QPushButton:pressed {{
                background-color: #be1e0e;
            }}
            QPushButton:disabled {{
                background-color: #666666;
                color: #999999;
            }}
        """)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_automation)
        button_layout.addWidget(self.stop_button)
        
        layout.addLayout(button_layout)
        
        # 상태 표시 프레임 (3줄 분리)
        status_frame = QFrame()
        status_frame.setFrameStyle(QFrame.Shape.Box)
        status_frame.setStyleSheet("background-color: #2a2a2a; border-radius: 5px; padding: 5px;")
        status_layout = QVBoxLayout(status_frame)
        status_layout.setSpacing(2)
        
        # 통일된 폰트 크기 설정
        status_font_size = get_scaled_font_size(13)
        
        # 1. 자동화 카운트 라벨
        self.automation_count_label = QLabel("🌐 자동화 대기 중")
        self.automation_count_label.setStyleSheet(f"{label_style} font-weight: bold; font-size: {status_font_size}px; color: #4CAF50;")
        status_layout.addWidget(self.automation_count_label)
        
        # 2. 반복 생성 정보 라벨
        self.repeat_info_label = QLabel("")
        self.repeat_info_label.setStyleSheet(f"{label_style} font-size: {status_font_size}px; color: #2196F3;")
        self.repeat_info_label.setVisible(False)  # 초기에는 숨김
        status_layout.addWidget(self.repeat_info_label)
        
        # 3. 지연시간 라벨
        self.delay_info_label = QLabel("")
        self.delay_info_label.setStyleSheet(f"{label_style} font-size: {status_font_size}px; color: #9C27B0;")
        status_layout.addWidget(self.delay_info_label)
        
        layout.addWidget(status_frame)
        
        # 기존 status_label 호환성을 위해 별칭 설정
        self.status_label = self.automation_count_label
        
        # 라디오 버튼 시그널 연결
        self.automation_type_group.buttonClicked.connect(self.on_automation_type_changed)
        
        # 초기 상태 설정
        self.update_condition_widgets_visibility()
        
        return widget
    
    def update_condition_widgets_visibility(self):
        """선택된 자동화 타입에 따라 위젯들의 가시성 업데이트"""
        if self.unlimited_radio.isChecked():
            self.timer_label.setVisible(False)
            self.timer_input.setVisible(False)
            self.count_label.setVisible(False)
            self.count_input.setVisible(False)
            # 시스템 종료 옵션 항상 숨김
            self.finish_frame.setVisible(False)
        elif self.timer_radio.isChecked():
            self.timer_label.setVisible(True)
            self.timer_input.setVisible(True)
            self.count_label.setVisible(False)
            self.count_input.setVisible(False)
            # 시스템 종료 옵션 항상 숨김
            self.finish_frame.setVisible(False)
        elif self.count_radio.isChecked():
            self.timer_label.setVisible(False)
            self.timer_input.setVisible(False)
            self.count_label.setVisible(True)
            self.count_input.setVisible(True)
            # 시스템 종료 옵션 항상 숨김
            self.finish_frame.setVisible(False)

    def on_delay_text_changed(self, text: str):
        """지연 시간 텍스트 변경 시 처리"""
        try:
            value = float(text) if text else 0.0
            self.delay_seconds = value
            if self.generation_delay_callback:
                self.generation_delay_callback(value)
        except ValueError:
            pass
    
    def on_automation_type_changed(self, button):
        """자동화 타입 변경 시 UI 업데이트"""
        self.update_condition_widgets_visibility()
    
    def start_automation(self):
        """자동화 시작"""
        automation_type = "unlimited"
        timer_minutes = 0
        count_limit = 0
        
        if self.timer_radio.isChecked():
            automation_type = "timer"
            try:
                timer_minutes = int(self.timer_input.text())
            except ValueError:
                timer_minutes = 60
        elif self.count_radio.isChecked():
            automation_type = "count"
            try:
                count_limit = int(self.count_input.text())
            except ValueError:
                count_limit = 100
        
        self.automation_controller.start_automation(
            automation_type=automation_type,
            timer_minutes=timer_minutes,
            count_limit=count_limit,
            shutdown_on_finish=self.shutdown_checkbox.isChecked(),
            notify_on_finish=self.notify_checkbox.isChecked()
        )
        
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

        # ✅ 설정 저장
        self.save_settings()

        # 초기 상태를 자동화 카운트 라벨에 표시
        if hasattr(self, 'automation_count_label'):
            if automation_type == "timer":
                self.automation_count_label.setText(f"⏰ 자동화 시작 ({timer_minutes}분)")
            elif automation_type == "count":
                self.automation_count_label.setText(f"🔢 자동화 시작 ({count_limit}회)")
            else:
                self.automation_count_label.setText("♾️ 자동화 시작 (무제한)")
            self.automation_count_label.setStyleSheet(f"font-weight: bold; font-size: {get_scaled_font_size(13)}px; color: #FF9800;")
        
        # 반복 생성 및 지연시간 라벨 초기화
        if hasattr(self, 'repeat_info_label'):
            self.repeat_info_label.setText("")
        if hasattr(self, 'delay_info_label'):
            self.delay_info_label.setText("")

    def _disable_auto_generate_immediately(self):
        """자동 생성 체크박스를 즉시 해제 (타이밍 이슈 방지)"""
        try:
            if hasattr(self, 'context') and hasattr(self.context, 'main_window'):
                main_window = self.context.main_window
                if hasattr(main_window, 'generation_checkboxes'):
                    auto_generate_checkbox = main_window.generation_checkboxes.get("자동 생성")
                    if auto_generate_checkbox and auto_generate_checkbox.isChecked():
                        auto_generate_checkbox.setChecked(False)
                        print("🔒 자동화 완료: 자동 생성 즉시 차단 (API 요청 방지)")
        except Exception as e:
            print(f"⚠️ 자동 생성 즉시 차단 실패: {e}")

    def show_completion_notification(self):
        """자동화 완료 알림을 표시합니다 (비차단 방식)."""
        try:
            # 리모트 클라이언트 연결 중이면 다이얼로그 억제
            if hasattr(self, 'app_context') and getattr(self.app_context, 'remote_bridge', None):
                bridge = self.app_context.remote_bridge
                if hasattr(bridge, '_has_clients') and bridge._has_clients():
                    print("🌐 Remote: 자동화 완료 알림 억제 (remote client connected)")
                    return

            # 부모 윈도우 찾기
            parent = None
            if hasattr(self, 'context') and hasattr(self.context, 'main_window'):
                parent = self.context.main_window

            msg = QMessageBox(parent)
            msg.setWindowTitle("자동화 완료")
            msg.setText("자동 생성이 완료되었습니다!")
            msg.setIcon(QMessageBox.Icon.Information)

            # ✅ exec() 대신 show() 사용 - 비차단 방식
            # exec()는 이벤트 루프를 차단하여 automation_finished 시그널 처리 지연
            # → 자동 생성 체크박스 해제가 지연되어 무한 API 요청 발생 위험
            msg.setWindowModality(Qt.WindowModality.NonModal)  # 비모달 설정
            msg.show()

            # 메시지 박스가 가비지 컬렉션되지 않도록 참조 유지
            self._completion_msg = msg

            print("✅ 자동화 완료 알림 표시 (비차단)")
        except Exception as e:
            print(f"⚠️ 완료 알림 표시 오류: {e}")

    def stop_automation(self):
        """자동화 중단"""
        self.automation_controller.stop_automation()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

        if hasattr(self, 'automation_count_label'):
            self.automation_count_label.setText("🚫 자동화 중단됨")
            self.automation_count_label.setStyleSheet(f"font-weight: bold; font-size: {get_scaled_font_size(13)}px; color: #F44336;")
        if hasattr(self, 'repeat_info_label'):
            self.repeat_info_label.setText("")
        if hasattr(self, 'delay_info_label'):
            self.delay_info_label.setText("")

        # 🔒 자동 생성 즉시 중단 (수동 중단 시에도 API 요청 방지)
        self._disable_auto_generate_immediately()

        # 🔔 외부 윈도우에 자동화 중단 알림 (ClothesPresetWindow 등)
        if hasattr(self, 'app_context') and self.app_context:
            self.app_context.publish("automation_stopped")

        # ✅ 설정 저장
        self.save_settings()
    
    def on_automation_finished(self):
        """자동화 완료 시 처리 (UI 업데이트)"""
        # 🔒 최우선: 자동 생성 즉시 차단 (API 요청 방지)
        self._disable_auto_generate_immediately()

        # UI 업데이트
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

        if hasattr(self, 'automation_count_label'):
            self.automation_count_label.setText("✅ 자동화 완료")
            self.automation_count_label.setStyleSheet(f"font-weight: bold; font-size: {get_scaled_font_size(13)}px; color: #4CAF50;")
        if hasattr(self, 'repeat_info_label'):
            self.repeat_info_label.setText("")
        if hasattr(self, 'delay_info_label'):
            self.delay_info_label.setText("")

        # 🔔 외부 윈도우에 자동화 완료 알림 (ClothesPresetWindow 등)
        if hasattr(self, 'app_context') and self.app_context:
            self.app_context.publish("automation_stopped")

        # ✅ 비차단 알림 표시
        if self.automation_controller and self.automation_controller.notify_on_finish:
            self.show_completion_notification()
    
    def on_progress_updated(self, text: str):
        """진행 상황 업데이트"""
        # 자동화 카운트 라벨에 표시
        if hasattr(self, 'automation_count_label') and self.automation_count_label:
            self.automation_count_label.setText(text)
            # 진행 중일 때는 주황색으로 표시
            self.automation_count_label.setStyleSheet(f"font-weight: bold; font-size: {get_scaled_font_size(13)}px; color: #FF9800;")
    
    def set_automation_status_callback(self, callback):
        """자동화 상태 업데이트 콜백 등록"""
        self.automation_status_callback = callback
    
    def set_generation_delay_callback(self, callback):
        """생성 지연 시간 변경 콜백 등록"""
        self.generation_delay_callback = callback
    
    def set_auto_generate_status_callback(self, callback):
        """자동 생성 상태 확인 콜백 등록"""
        self.get_auto_generate_status_callback = callback
    
    def set_automation_active_status_callback(self, callback):
        """자동화 활성 상태 확인 콜백 등록"""
        self.get_automation_active_status_callback = callback
    
    def get_generation_delay(self) -> float:
        """현재 지연 시간을 반환 (랜덤 지연 고려)"""
        # 자동화가 비활성화된 경우 지연시간 0 반환
        if not (self.automation_controller and self.automation_controller.is_running):
            return 0.0
            
        delay = self.delay_seconds
        
        try:
            if (hasattr(self, 'random_delay_checkbox') and 
                self.random_delay_checkbox and 
                self.random_delay_checkbox.isChecked()):
                original_delay = delay
                variation = delay * 0.5
                delay += random.uniform(-variation, variation)
                delay = max(0.0, delay)
                if delay != original_delay:
                    print(f"🎲 랜덤 지연 적용: {original_delay:.1f}초 → {delay:.1f}초")
        except (AttributeError, RuntimeError):
            pass
        
        return delay
    
    def notify_generation_completed(self):
        """생성 완료 시 카운트 감소 및 반복 생성 처리"""
        if self.automation_controller and self.automation_controller.automation_type == "count":
            self.automation_controller.decrement_count()
        
        return self.handle_repeat_generation()
    
    def handle_repeat_generation(self):
        """반복 생성 처리"""
        # 자동 생성 체크박스 확인
        try:
            if hasattr(self.context, 'main_window') and hasattr(self.context.main_window, 'generation_checkboxes'):
                auto_generate_checkbox = self.context.main_window.generation_checkboxes.get("자동 생성")
                if not (auto_generate_checkbox and auto_generate_checkbox.isChecked()):
                    # 자동 생성이 비활성화되면 카운터 리셋
                    self.current_repeat_count = 0
                    print("ℹ️ 자동 생성이 비활성화되어 반복 생성을 중단합니다.")
                    return True
        except Exception as e:
            print(f"⚠️ 자동 생성 상태 확인 실패: {e}")
            return True
        
        # 자동화 활성 상태 확인 - 자동화가 활성화되지 않았으면 반복 생성 사용 안 함
        if not (self.automation_controller and self.automation_controller.is_running):
            # 자동화가 아닌 경우 반복 생성 기능 비활성화
            # 반복 정보 라벨 숨김
            if hasattr(self, 'repeat_info_label') and self.repeat_info_label:
                self.repeat_info_label.setText("")
                self.repeat_info_label.setVisible(False)
            return True
        
        try:
            repeat_count = int(self.repeat_input.text()) if hasattr(self, 'repeat_input') and self.repeat_input and self.repeat_input.text() else 1
        except (ValueError, AttributeError, RuntimeError):
            repeat_count = 1
        
        # 반복 횟수가 1인 경우 반복 생성 사용 안 함
        if repeat_count <= 1:
            # 반복 정보 라벨 숨김
            if hasattr(self, 'repeat_info_label') and self.repeat_info_label:
                self.repeat_info_label.setText("")
                self.repeat_info_label.setVisible(False)
            return True
        
        # 초기화되지 않았거나 리셋된 경우 0으로 설정
        if not hasattr(self, 'current_repeat_count') or self.current_repeat_count == 0:
            self.current_repeat_count = 1  # 첫 번째 생성으로 설정
        else:
            self.current_repeat_count += 1
        
        # 반복 정보 라벨 표시
        if hasattr(self, 'repeat_info_label') and self.repeat_info_label:
            self.repeat_info_label.setVisible(True)
        
        print(f"🔄 반복 생성: {self.current_repeat_count}/{repeat_count}")
        
        if self.current_repeat_count >= repeat_count:
            self.current_repeat_count = 0
            print(f"✅ 반복 완료 ({repeat_count}회), 다음 프롬프트로 진행")
            # 반복 정보 라벨 숨김
            if hasattr(self, 'repeat_info_label') and self.repeat_info_label:
                self.repeat_info_label.setText("")
                self.repeat_info_label.setVisible(False)
            return True
        else:
            remaining = repeat_count - self.current_repeat_count
            print(f"🔁 동일 프롬프트로 재생성 ({remaining}회 남음)")
            
            # 반복 생성 정보를 중간 라인에 표시
            if hasattr(self, 'repeat_info_label') and self.repeat_info_label:
                self.repeat_info_label.setText(f"🔁 반복 생성: {self.current_repeat_count}/{repeat_count} ({remaining}회 남음)")
                self.repeat_info_label.setVisible(True)
            
            # 자동화가 활성화된 경우에만 지연시간 적용
            if self.automation_controller and self.automation_controller.is_running:
                delay = self.get_generation_delay()
                if delay > 0:
                    print(f"⏱️ 반복 생성 지연: {delay:.1f}초 후 실행")
                    if hasattr(self, 'delay_info_label') and self.delay_info_label:
                        self.start_delay_countdown(delay)
                else:
                    if hasattr(self, 'delay_info_label') and self.delay_info_label:
                        self.delay_info_label.setText("⚡ 지연 없음")
                    self.trigger_repeat_generation()
            else:
                # 자동화 비활성 시 지연 없이 즉시 실행
                print("ℹ️ 자동화 비활성 - 지연 없이 반복 생성")
                self.trigger_repeat_generation()
            
            return False
    
    def trigger_repeat_generation(self):
        """반복 생성 트리거"""
        try:
            # 카운트다운 스레드 정지
            if hasattr(self, 'countdown_thread') and self.countdown_thread and self.countdown_thread.isRunning():
                self.countdown_thread.stop()
                self.countdown_thread.wait()
            
            # 지연 라벨 초기화
            if hasattr(self, 'delay_info_label') and self.delay_info_label:
                self.delay_info_label.setText("")
            
            # 더 안정적인 generation_controller 접근
            if hasattr(self.context, 'main_window') and hasattr(self.context.main_window, 'generation_controller'):
                generation_controller = self.context.main_window.generation_controller
                if not (hasattr(generation_controller, 'is_generating') and generation_controller.is_generating):
                    generation_controller.execute_generation_pipeline()
                    print(f"🔁 반복 생성 트리거 성공")
                else:
                    print("⚠️ 이미 생성 중이므로 반복 생성 대기")
            else:
                print("❌ generation_controller를 찾을 수 없음")
                        
        except Exception as e:
            print(f"❌ 반복 생성 트리거 실패: {e}")
    
    def reset_repeat_counter(self):
        """반복 카운터 리셋"""
        self.current_repeat_count = 0
        # 반복 정보 라벨 숨김
        if hasattr(self, 'repeat_info_label') and self.repeat_info_label:
            self.repeat_info_label.setText("")
            self.repeat_info_label.setVisible(False)
        print("🔄 반복 카운터 리셋")
    
    def start_delay_countdown(self, delay_seconds: float):
        """지연 시간 카운트다운 시작"""
        try:
            # 기존 스레드 정리
            if hasattr(self, 'countdown_thread') and self.countdown_thread:
                if self.countdown_thread.isRunning():
                    self.countdown_thread.stop()
                    self.countdown_thread.wait()
                self.countdown_thread.deleteLater()
            
            # 새 카운트다운 스레드 생성
            self.countdown_thread = DelayCountdownThread(delay_seconds)
            self.countdown_thread.progress_updated.connect(self.update_delay_label)
            self.countdown_thread.countdown_finished.connect(self.trigger_repeat_generation)
            self.countdown_thread.start()
            
            print(f"⏱️ 카운트다운 시작: {delay_seconds:.1f}초")
            
        except Exception as e:
            print(f"❌ 카운트다운 시작 실패: {e}")
            import traceback
            traceback.print_exc()
            # 실패 시 즉시 트리거
            QTimer.singleShot(int(delay_seconds * 1000), self.trigger_repeat_generation)
    
    def update_delay_label(self, text: str):
        """지연 라벨 업데이트"""
        if hasattr(self, 'delay_info_label') and self.delay_info_label:
            self.delay_info_label.setText(text)
    
    def start_delay_countdown_for_new_prompt(self, delay_seconds: float):
        """새 프롬프트 생성을 위한 지연 카운트다운 시작 (NAIA_cold_v4.py에서 호출)"""
        try:
            # 기존 스레드 정리
            if hasattr(self, 'countdown_thread') and self.countdown_thread:
                if self.countdown_thread.isRunning():
                    self.countdown_thread.stop()
                    self.countdown_thread.wait()
                self.countdown_thread.deleteLater()
            
            # 새 카운트다운 스레드 생성
            self.countdown_thread = DelayCountdownThread(delay_seconds)
            self.countdown_thread.progress_updated.connect(self.update_delay_label)
            # 새 프롬프트 생성을 위한 콜백 연결
            self.countdown_thread.countdown_finished.connect(self.trigger_new_prompt_generation)
            self.countdown_thread.start()
            
            print(f"⏱️ 새 프롬프트 카운트다운 시작: {delay_seconds:.1f}초")
            
        except Exception as e:
            print(f"❌ 새 프롬프트 카운트다운 시작 실패: {e}")
            import traceback
            traceback.print_exc()
            # 실패 시 즉시 트리거
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(int(delay_seconds * 1000), self.trigger_new_prompt_generation)
    
    def trigger_new_prompt_generation(self):
        """새 프롬프트 생성 트리거 (카운트다운 완료 후)"""
        try:
            # 새 프롬프트 생성 트리거
            
            # 카운트다운 스레드 정지
            if hasattr(self, 'countdown_thread') and self.countdown_thread and self.countdown_thread.isRunning():
                self.countdown_thread.stop()
                self.countdown_thread.wait()
            
            # 지연 라벨 초기화
            if hasattr(self, 'delay_info_label') and self.delay_info_label:
                self.delay_info_label.setText("")
            
            # 메인 윈도우의 자동 생성 트리거 호출
            if hasattr(self.context, 'main_window') and hasattr(self.context.main_window, '_check_and_trigger_auto_generation'):
                self.context.main_window._check_and_trigger_auto_generation()
                print("✅ 새 프롬프트 생성 트리거 성공")
            else:
                print("❌ _check_and_trigger_auto_generation 메서드를 찾을 수 없음")
                
        except Exception as e:
            print(f"❌ 새 프롬프트 생성 트리거 실패: {e}")
    
    def get_parameters(self) -> dict:
        """모듈 파라미터 반환"""
        try:
            repeat_count = int(self.repeat_input.text()) if hasattr(self, 'repeat_input') and self.repeat_input and self.repeat_input.text() else 1
        except (ValueError, AttributeError, RuntimeError):
            repeat_count = 1
        
        try:
            random_delay = (
                self.random_delay_checkbox.isChecked() 
                if hasattr(self, 'random_delay_checkbox') and self.random_delay_checkbox 
                else False
            )
        except (AttributeError, RuntimeError):
            random_delay = False
        
        return {
            "delay_seconds": self.delay_seconds,
            "random_delay": random_delay,
            "repeat_count": repeat_count,
            "automation_active": self.automation_controller.is_running if self.automation_controller else False
        }
    
    def on_initialize(self):
        """모듈 초기화 시 설정 로드"""
        super().on_initialize()
        self.load_settings()
    
    def save_settings(self):
        """설정을 JSON 파일에 저장 (동일 이미지 반복 생성 횟수는 제외)"""
        if not all([self.delay_input, self.random_delay_checkbox]):
            return

        try:
            delay_seconds = float(self.delay_input.text()) if self.delay_input.text() else 2.0
        except ValueError:
            delay_seconds = 2.0

        try:
            timer_minutes = int(self.timer_input.text()) if self.timer_input.text() else 60
        except ValueError:
            timer_minutes = 60

        try:
            count_limit = int(self.count_input.text()) if self.count_input.text() else 100
        except ValueError:
            count_limit = 100

        # ✅ 저장할 설정 (repeat_count는 제외)
        settings = {
            "delay_seconds": delay_seconds,
            "random_delay": self.random_delay_checkbox.isChecked(),
            # "repeat_count": repeat_count,  # ❌ 제외: 매번 새로 설정해야 함
            "timer_minutes": timer_minutes,
            "count_limit": count_limit,
            "shutdown_on_finish": self.shutdown_checkbox.isChecked(),
            "notify_on_finish": self.notify_checkbox.isChecked(),
            "automation_type": (
                "timer" if self.timer_radio.isChecked() else
                "count" if self.count_radio.isChecked() else
                "unlimited"
            )
        }

        try:
            os.makedirs(os.path.dirname(self.settings_file), exist_ok=True)
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4, ensure_ascii=False)
            print(f"✅ '{self.get_title()}' 설정 저장 완료")
        except Exception as e:
            print(f"❌ '{self.get_title()}' 설정 저장 실패: {e}")
    
    def load_settings(self):
        """JSON 파일에서 설정 로드"""
        try:
            if not os.path.exists(self.settings_file):
                return
            
            with open(self.settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
            
            if self.delay_input:
                self.delay_input.setText(str(settings.get("delay_seconds", 2.0)))
                self.random_delay_checkbox.setChecked(settings.get("random_delay", False))
                # self.repeat_input.setText(str(settings.get("repeat_count", 1)))  # ❌ 제외: 항상 기본값 1로 유지
                self.repeat_input.setText("1")  # ✅ 항상 기본값으로 리셋
                self.timer_input.setText(str(settings.get("timer_minutes", 60)))
                self.count_input.setText(str(settings.get("count_limit", 100)))
                self.shutdown_checkbox.setChecked(settings.get("shutdown_on_finish", False))
                self.notify_checkbox.setChecked(settings.get("notify_on_finish", True))
                
                automation_type = settings.get("automation_type", "unlimited")
                if automation_type == "timer":
                    self.timer_radio.setChecked(True)
                elif automation_type == "count":
                    self.count_radio.setChecked(True)
                else:
                    self.unlimited_radio.setChecked(True)
                
                self.update_condition_widgets_visibility()
            
            print(f"✅ '{self.get_title()}' 설정 로드 완료.")
        except Exception as e:
            print(f"❌ '{self.get_title()}' 설정 로드 실패: {e}")

    def cleanup(self):
        """모듈 종료 시 리소스 정리 및 설정 저장"""
        # ✅ 설정 저장
        self.save_settings()

        # 타이머 정지
        if hasattr(self, 'automation_controller') and self.automation_controller:
            if hasattr(self.automation_controller, 'timer'):
                self.automation_controller.timer.stop()

        # 카운트다운 스레드 정리
        if hasattr(self, 'countdown_thread') and self.countdown_thread:
            if self.countdown_thread.isRunning():
                self.countdown_thread.stop()
                self.countdown_thread.wait()
            self.countdown_thread.deleteLater()

        print(f"✅ '{self.get_title()}' 정리 완료")
