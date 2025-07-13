from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QWidget, 
    QLineEdit, QCheckBox, QRadioButton, QPushButton,
    QButtonGroup, QFrame, QMessageBox
)
from PyQt6.QtCore import QTimer, QThread, QObject, pyqtSignal
from interfaces.base_module import BaseMiddleModule
import os
import json
import random
import subprocess
import platform

class AutomationController(QThread):
    """자동화 타이머 및 카운터를 관리하는 컨트롤러"""
    
    automation_finished = pyqtSignal()
    progress_updated = pyqtSignal(str)  # 진행 상황 텍스트
    
    def __init__(self):
        super().__init__()
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_progress)
        
        # 자동화 설정
        self.automation_type = "unlimited"  # unlimited, timer, count
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
        elif automation_type == "count":
            self.remaining_count = count_limit
        
        self.is_running = True
        self.update_progress()
        
    def stop_automation(self):
        """자동화를 중단합니다."""
        self.timer.stop()
        self.is_running = False
        self.progress_updated.emit("자동화 중단됨")
        
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
                
            self.progress_updated.emit(f"자동화 ({time_str})")
            self.remaining_seconds -= 1
            
        elif self.automation_type == "count":
            self.progress_updated.emit(f"자동화 ({self.remaining_count})")
            
        elif self.automation_type == "unlimited":
            self.progress_updated.emit("자동화 (무제한)")
    
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
        self.progress_updated.emit("자동화 완료")
        
        # 완료 처리
        if self.shutdown_on_finish:
            self.shutdown_system()
        elif self.notify_on_finish:
            self.show_completion_notification()
            
        self.automation_finished.emit()
    
    def shutdown_system(self):
        """시스템 종료를 실행합니다."""
        try:
            system = platform.system()
            if system == "Windows":
                subprocess.run(["shutdown", "/s", "/t", "120"])  # 2분 후 종료
            elif system == "Linux" or system == "Darwin":  # macOS
                subprocess.run(["sudo", "shutdown", "-h", "+2"])  # 2분 후 종료
        except Exception as e:
            print(f"시스템 종료 오류: {e}")
    
    def show_completion_notification(self):
        """자동화 완료 알림을 표시합니다."""
        try:
            from PyQt6.QtWidgets import QApplication
            if QApplication.instance():
                msg = QMessageBox()
                msg.setWindowTitle("자동화 완료")
                msg.setText("자동 생성이 완료되었습니다!")
                msg.setIcon(QMessageBox.Icon.Information)
                msg.exec()
        except Exception as e:
            print(f"완료 알림 표시 오류: {e}")


class AutomationModule(BaseMiddleModule):
    """⚙️ 자동화 설정 모듈"""
    
    def __init__(self):
        super().__init__()  # BaseMiddleModule 초기화
        
        # 콜백 함수들 (시그널 대신 사용)
        self.automation_status_callback = None
        self.generation_delay_callback = None
        self.get_auto_generate_status_callback = None  # 자동 생성 상태 확인 콜백
        self.get_automation_active_status_callback = None  # [신규] 자동화 활성 상태 확인 콜백
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
    
    def create_widget(self, parent: QWidget) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)
        
        # 스타일 정의
        if parent and hasattr(parent, 'get_dark_style'):
            label_style = parent.get_dark_style('label_style')
            checkbox_style = parent.get_dark_style('dark_checkbox')
        else:
            label_style = ""
            checkbox_style = ""
        
        # 자동화 설정 위젯 생성
        automation_widget = self.create_automation_widget(parent, label_style, checkbox_style)
        layout.addWidget(automation_widget)
        
        return widget
    
    def create_automation_widget(self, parent, label_style, checkbox_style) -> QWidget:
        """자동화 설정 위젯 생성"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)
        
        # === 지연 시간 설정 섹션 ===
        delay_frame = QFrame()
        delay_frame.setFrameStyle(QFrame.Shape.Box)
        delay_layout = QVBoxLayout(delay_frame)
        
        delay_title = QLabel("🕐 생성 지연 설정")
        delay_title.setStyleSheet(f"{label_style} font-weight: bold; font-size: 14px;")
        delay_layout.addWidget(delay_title)
        
        delay_grid = QGridLayout()
        
        delay_label = QLabel("생성당 지연시간 (초):")
        delay_label.setStyleSheet(label_style)
        delay_grid.addWidget(delay_label, 0, 0)
        
        self.delay_input = QLineEdit(str(self.delay_seconds))
        self.delay_input.setStyleSheet("background-color: #212121; color: white; border: 1px solid #555; border-radius: 4px; padding: 5px;")
        self.delay_input.textChanged.connect(self.on_delay_text_changed)
        delay_grid.addWidget(self.delay_input, 0, 1)
        
        # 랜덤 지연시간을 아래로 배치
        self.random_delay_checkbox = QCheckBox("랜덤 지연시간 (±50%)")
        self.random_delay_checkbox.setStyleSheet(checkbox_style)
        self.random_delay_checkbox.setChecked(self.random_delay)
        delay_grid.addWidget(self.random_delay_checkbox, 1, 0, 1, 2)  # 2칸 차지
        
        repeat_label = QLabel("동일 이미지 반복 생성 횟수:")
        repeat_label.setStyleSheet(label_style)
        delay_grid.addWidget(repeat_label, 2, 0)
        
        self.repeat_input = QLineEdit(str(self.repeat_count))
        self.repeat_input.setStyleSheet("background-color: #212121; color: white; border: 1px solid #555; border-radius: 4px; padding: 5px;")
        delay_grid.addWidget(self.repeat_input, 2, 1)
        
        # [신규] 반복 생성 조건 안내 레이블 추가
        repeat_info_label = QLabel("* 자동 생성 상태일때만 작동합니다")
        repeat_info_label.setStyleSheet(f"{label_style} color: #888888; font-size: 11px; font-style: italic;")
        delay_grid.addWidget(repeat_info_label, 3, 0, 1, 2)  # 2칸 차지
        
        delay_layout.addLayout(delay_grid)
        layout.addWidget(delay_frame)
        
        # === 자동화 종료 조건 섹션 ===
        automation_frame = QFrame()
        automation_frame.setFrameStyle(QFrame.Shape.Box)
        automation_layout = QVBoxLayout(automation_frame)
        
        automation_title = QLabel("⏰ 자동화 종료 조건")
        automation_title.setStyleSheet(f"{label_style} font-weight: bold; font-size: 14px;")
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
        self.timer_input.setStyleSheet("background-color: #212121; color: white; border: 1px solid #555; border-radius: 4px; padding: 5px;")
        condition_grid.addWidget(self.timer_input, 0, 1)
        
        # 횟수 제한 옵션
        self.count_label = QLabel("생성 횟수:")
        self.count_label.setStyleSheet(label_style)
        condition_grid.addWidget(self.count_label, 1, 0)
        
        self.count_input = QLineEdit("100")
        self.count_input.setStyleSheet("background-color: #212121; color: white; border: 1px solid #555; border-radius: 4px; padding: 5px;")
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
        automation_layout.addWidget(self.finish_frame)
        
        layout.addWidget(automation_frame)
        
        # === 제어 버튼 섹션 ===
        button_layout = QHBoxLayout()
        
        self.start_button = QPushButton("자동화 적용")
        # 적용 버튼 스타일 (녹색 계열)
        self.start_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
            QPushButton:disabled {
                background-color: #666666;
                color: #999999;
            }
        """)
        self.start_button.clicked.connect(self.start_automation)
        button_layout.addWidget(self.start_button)
        
        self.stop_button = QPushButton("자동화 중단")
        # 중단 버튼 스타일 (빨간색 계열)
        self.stop_button.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
            QPushButton:pressed {
                background-color: #be1e0e;
            }
            QPushButton:disabled {
                background-color: #666666;
                color: #999999;
            }
        """)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_automation)
        button_layout.addWidget(self.stop_button)
        
        layout.addLayout(button_layout)
        
        # 상태 표시 레이블
        self.status_label = QLabel("자동화 대기 중")
        self.status_label.setStyleSheet(f"{label_style} font-weight: bold; color: #4CAF50;")
        layout.addWidget(self.status_label)
        
        # 라디오 버튼 시그널 연결
        self.automation_type_group.buttonClicked.connect(self.on_automation_type_changed)
        
        # 초기 상태 설정 (무제한이 선택되어 있으므로 관련 위젯들 숨김)
        self.update_condition_widgets_visibility()
        
        return widget
    
    def update_condition_widgets_visibility(self):
        """선택된 자동화 타입에 따라 위젯들의 가시성 업데이트"""
        if self.unlimited_radio.isChecked():
            # 무제한: 모든 조건 관련 위젯 숨김
            self.timer_label.setVisible(False)
            self.timer_input.setVisible(False)
            self.count_label.setVisible(False)
            self.count_input.setVisible(False)
            self.finish_frame.setVisible(False)
        elif self.timer_radio.isChecked():
            # 시간 제한: 시간 관련 위젯만 표시
            self.timer_label.setVisible(True)
            self.timer_input.setVisible(True)
            self.count_label.setVisible(False)
            self.count_input.setVisible(False)
            self.finish_frame.setVisible(True)
        elif self.count_radio.isChecked():
            # 횟수 제한: 횟수 관련 위젯만 표시
            self.timer_label.setVisible(False)
            self.timer_input.setVisible(False)
            self.count_label.setVisible(True)
            self.count_input.setVisible(True)
            self.finish_frame.setVisible(True)

    def on_delay_text_changed(self, text: str):
        """지연 시간 텍스트 변경 시 처리"""
        try:
            value = float(text) if text else 0.0
            self.delay_seconds = value
            # 콜백 함수가 등록되어 있으면 호출
            if self.generation_delay_callback:
                self.generation_delay_callback(value)
        except ValueError:
            # 잘못된 입력은 무시
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
        self.status_label.setText("자동화 설정이 적용되었습니다.")
        self.status_label.setStyleSheet("color: #FF9800; font-weight: bold;")
    
    def stop_automation(self):
        """자동화 중단"""
        self.automation_controller.stop_automation()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText("자동화 설정이 중단되었습니다.")
        self.status_label.setStyleSheet("color: #F44336; font-weight: bold;")
    
    def on_automation_finished(self):
        """자동화 완료 시 처리"""
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText("자동화 완료")
        self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
    
    def on_progress_updated(self, text: str):
        """진행 상황 업데이트"""
        # 콜백 함수가 등록되어 있으면 호출
        if self.automation_status_callback:
            self.automation_status_callback(text)
    
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
        delay = self.delay_seconds
        
        try:
            if (hasattr(self, 'random_delay_checkbox') and 
                self.random_delay_checkbox and 
                self.random_delay_checkbox.isChecked()):
                # ±50% 랜덤 변동
                variation = delay * 0.5
                delay += random.uniform(-variation, variation)
                delay = max(0.0, delay)  # 음수 방지
        except (AttributeError, RuntimeError):
            pass  # 위젯 오류 시 기본 지연 시간 사용
        
        return delay
    
    def notify_generation_completed(self):
        """생성 완료 시 카운트 감소 및 반복 생성 처리"""
        # 1. 자동화 카운트 감소
        if self.automation_controller and self.automation_controller.automation_type == "count":
            self.automation_controller.decrement_count()
        
        # 2. 반복 생성 처리
        self.handle_repeat_generation()
    
    def handle_repeat_generation(self):
        """반복 생성 처리 - 동일 프롬프트로 설정된 횟수만큼 반복"""
        # [수정] 자동 생성 상태 확인 - 비활성화 시 반복 생성 건너뛰기
        if self.get_auto_generate_status_callback:
            auto_generate_enabled = self.get_auto_generate_status_callback()
            if not auto_generate_enabled:
                #print("⚠️ 자동 생성이 비활성화되어 있어 반복 생성을 건너뜁니다.")
                return True  # 반복 없이 바로 다음으로 진행
        
        # [신규] 자동화 설정 상태 확인 - 자동화가 비활성화되어 있으면 반복 무시
        if self.get_automation_active_status_callback:
            automation_active = self.get_automation_active_status_callback()
            if not automation_active:
                print("ℹ️ 자동화 설정이 비활성화되어 있어 반복 생성을 무시하고 다음 프롬프트로 진행합니다.")
                return True  # 반복 없이 바로 다음으로 진행
        
        try:
            repeat_count = int(self.repeat_input.text()) if hasattr(self, 'repeat_input') and self.repeat_input and self.repeat_input.text() else 1
        except (ValueError, AttributeError, RuntimeError):
            repeat_count = 1
        
        # 반복 카운터가 없으면 초기화
        if not hasattr(self, 'current_repeat_count'):
            self.current_repeat_count = 0
        
        # 현재 반복 횟수 증가
        self.current_repeat_count += 1
        
        print(f"🔄 반복 생성: {self.current_repeat_count}/{repeat_count}")
        
        # 설정된 횟수만큼 반복했으면 다음 프롬프트로 진행
        if self.current_repeat_count >= repeat_count:
            self.current_repeat_count = 0  # 카운터 리셋
            print(f"✅ 반복 완료 ({repeat_count}회), 다음 프롬프트로 진행")
            # 다음 프롬프트 생성 허용
            return True
        else:
            # 아직 반복이 남았으면 동일 프롬프트로 재생성
            remaining = repeat_count - self.current_repeat_count
            print(f"🔁 동일 프롬프트로 재생성 ({remaining}회 남음)")
            
            # 상태 업데이트
            if self.automation_status_callback:
                self.automation_status_callback(f"🔁 반복 생성 중... ({remaining}회 남음)")
            
            # 지연 시간 후 재생성 트리거
            delay = self.get_generation_delay()
            if delay > 0:
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(int(delay * 1000), self.trigger_repeat_generation)
            else:
                self.trigger_repeat_generation()
            
            # 다음 프롬프트 생성 차단
            return False
    
    def trigger_repeat_generation(self):
        """반복 생성 트리거 - 메인 윈도우의 생성 함수 호출"""
        try:
            # 메인 윈도우 참조를 통해 이미지 생성 트리거
            if self.automation_status_callback:
                # 상태 업데이트
                try:
                    repeat_count = int(self.repeat_input.text()) if self.repeat_input and self.repeat_input.text() else 1
                except:
                    repeat_count = 1
                remaining = repeat_count - self.current_repeat_count
                self.automation_status_callback(f"🔁 반복 생성 중... ({remaining}회 남음)")
            
            # 메인 윈도우의 생성 컨트롤러 호출
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                for widget in app.topLevelWidgets():
                    if hasattr(widget, 'generation_controller'):
                        # 현재 생성 중이 아닐 때만 실행
                        if not (hasattr(widget.generation_controller, 'is_generating') and widget.generation_controller.is_generating):
                            widget.generation_controller.execute_generation_pipeline()
                        break
                        
        except Exception as e:
            print(f"❌ 반복 생성 트리거 실패: {e}")
    
    def reset_repeat_counter(self):
        """반복 카운터 리셋 - 새로운 프롬프트 생성 시 호출"""
        self.current_repeat_count = 0
        print("🔄 반복 카운터 리셋")
    
    def get_parameters(self) -> dict:
        """모듈 파라미터 반환"""
        # repeat_count 안전하게 가져오기
        try:
            repeat_count = int(self.repeat_input.text()) if hasattr(self, 'repeat_input') and self.repeat_input and self.repeat_input.text() else 1
        except (ValueError, AttributeError, RuntimeError):
            repeat_count = 1
        
        # 위젯 상태 안전하게 가져오기
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
        """설정을 JSON 파일에 저장"""
        if not all([self.delay_input, self.random_delay_checkbox, self.repeat_input]):
            return
        
        # 안전하게 값 가져오기
        try:
            delay_seconds = float(self.delay_input.text()) if self.delay_input.text() else 2.0
        except ValueError:
            delay_seconds = 2.0
            
        try:
            repeat_count = int(self.repeat_input.text()) if self.repeat_input.text() else 1
        except ValueError:
            repeat_count = 1
            
        try:
            timer_minutes = int(self.timer_input.text()) if self.timer_input.text() else 60
        except ValueError:
            timer_minutes = 60
            
        try:
            count_limit = int(self.count_input.text()) if self.count_input.text() else 100
        except ValueError:
            count_limit = 100
        
        settings = {
            "delay_seconds": delay_seconds,
            "random_delay": self.random_delay_checkbox.isChecked(),
            "repeat_count": repeat_count,
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
        except Exception as e:
            print(f"❌ '{self.get_title()}' 설정 저장 실패: {e}")
    
    def load_settings(self):
        """JSON 파일에서 설정 로드"""
        try:
            if not os.path.exists(self.settings_file):
                return
            
            with open(self.settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
            
            # UI 위젯이 생성된 후에만 설정 적용
            if self.delay_input:
                self.delay_input.setText(str(settings.get("delay_seconds", 2.0)))
                self.random_delay_checkbox.setChecked(settings.get("random_delay", False))
                self.repeat_input.setText(str(settings.get("repeat_count", 1)))
                self.timer_input.setText(str(settings.get("timer_minutes", 60)))
                self.count_input.setText(str(settings.get("count_limit", 100)))
                self.shutdown_checkbox.setChecked(settings.get("shutdown_on_finish", False))
                self.notify_checkbox.setChecked(settings.get("notify_on_finish", True))
                
                # 자동화 타입 복원
                automation_type = settings.get("automation_type", "unlimited")
                if automation_type == "timer":
                    self.timer_radio.setChecked(True)
                elif automation_type == "count":
                    self.count_radio.setChecked(True)
                else:
                    self.unlimited_radio.setChecked(True)
                
                self.update_condition_widgets_visibility()  # UI 상태 업데이트
            
            print(f"✅ '{self.get_title()}' 설정 로드 완료.")
        except Exception as e:
            print(f"❌ '{self.get_title()}' 설정 로드 실패: {e}")