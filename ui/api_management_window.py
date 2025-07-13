import json
import os
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QTextEdit, QFrame, QMessageBox
)
from PyQt6.QtCore import QThread
from ui.theme import DARK_STYLES, DARK_COLORS
from core.api_validator import APIValidator
from core.context import AppContext

class APIManagementWindow(QWidget):
    """NAI 토큰 및 WebUI API를 관리하는 전용 위젯"""
    
    TIMESTAMP_FILE = "NAIA_api_timestamps.json"

    def __init__(self, app_context: AppContext, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        # ✅ [수정] main_window와 token_manager를 app_context에서 가져옴
        self.main_window = self.app_context.main_window
        self.token_manager = self.app_context.secure_token_manager
        
        self.worker_thread = None
        self.validator = None

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(16)
        
        main_layout.addWidget(self._create_nai_section())
        main_layout.addWidget(self._create_webui_section())
        main_layout.addStretch(1)

        self.nai_verify_btn.clicked.connect(self._verify_nai_token)
        self.webui_verify_btn.clicked.connect(self._verify_webui_url)
        self._load_data()

    def _create_section_frame(self, title_text: str) -> QFrame|QVBoxLayout:
        """섹션 제목과 프레임을 생성하는 헬퍼 메서드"""
        frame = QFrame()
        frame.setStyleSheet(DARK_STYLES['compact_card'])
        
        layout = QVBoxLayout(frame)
        layout.setSpacing(8)
        
        title_label = QLabel(title_text)
        title_label.setStyleSheet(DARK_STYLES['label_style'].replace("19px", "21px; font-weight: 600;"))
        layout.addWidget(title_label)
        
        return frame, layout

    def _create_nai_section(self) -> QFrame:
        """NAI 토큰 입력 섹션 UI 생성"""
        frame, layout = self._create_section_frame("🔑 NovelAI API Token")
        
        input_layout = QHBoxLayout()
        self.nai_token_input = QLineEdit()
        self.nai_token_input.setPlaceholderText("여기에 NAI 영구 토큰을 붙여넣으세요...")
        self.nai_token_input.setStyleSheet(DARK_STYLES['compact_lineedit'])
        # [보안 강화] 입력 내용을 숨기는 Password 모드 적용
        self.nai_token_input.setEchoMode(QLineEdit.EchoMode.Password)

        self.nai_verify_btn = QPushButton("검증")
        self.nai_verify_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.nai_verify_btn.setFixedWidth(80)
        input_layout.addWidget(self.nai_token_input)
        input_layout.addWidget(self.nai_verify_btn)
        layout.addLayout(input_layout)

        # ... 설명(desc_box) 부분은 그대로 ...
        desc_box = QTextEdit()
        desc_box.setReadOnly(True)
        desc_box.setText("NovelAI 영구 토큰을 입력하면 Opus 등급 구독 여부를 확인합니다. 검증에 성공한 토큰은 시스템 키링에 안전하게 암호화되어 저장됩니다.")
        desc_box.setFixedHeight(60)
        desc_box.setStyleSheet(DARK_STYLES['compact_textedit'])
        layout.addWidget(desc_box)

        self.nai_last_verified_label = QLabel("마지막 검증 일자: 정보 없음")
        self.nai_last_verified_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: 16px;")
        layout.addWidget(self.nai_last_verified_label)
        
        return frame

    def _create_webui_section(self) -> QFrame:
        """WebUI API 입력 섹션 UI 생성"""
        frame, layout = self._create_section_frame("🌐 Stable Diffusion WebUI API")

        # 입력 라인
        input_layout = QHBoxLayout()
        self.webui_url_input = QLineEdit()
        self.webui_url_input.setPlaceholderText("예: 127.0.0.1:7860")
        self.webui_url_input.setStyleSheet(DARK_STYLES['compact_lineedit'])
        self.webui_verify_btn = QPushButton("검증")
        self.webui_verify_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.webui_verify_btn.setFixedWidth(80)
        input_layout.addWidget(self.webui_url_input)
        input_layout.addWidget(self.webui_verify_btn)
        layout.addLayout(input_layout)
        
        # 설명
        desc_box = QTextEdit()
        desc_box.setReadOnly(True)
        desc_box.setText("실행 중인 WebUI의 주소를 입력합니다. (http:// 또는 https:// 포함) 연결 성공 시, 해당 주소가 저장됩니다.")
        desc_box.setFixedHeight(60)
        desc_box.setStyleSheet(DARK_STYLES['compact_textedit'])
        layout.addWidget(desc_box)
        
        # 마지막 검증 일자
        self.webui_last_verified_label = QLabel("마지막 검증 일자: 정보 없음")
        self.webui_last_verified_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: 16px;")
        layout.addWidget(self.webui_last_verified_label)

        return frame

    def _load_data(self):
        """키링에서 토큰을, JSON 파일에서 타임스탬프를 로드"""
        # 키링에서 토큰 로드
        self.nai_token_input.setText(self.token_manager.get_token('nai_token'))
        self.webui_url_input.setText(self.token_manager.get_token('webui_url'))

        # 파일에서 마지막 검증 시간 로드
        if os.path.exists(self.TIMESTAMP_FILE):
            try:
                with open(self.TIMESTAMP_FILE, 'r') as f:
                    data = json.load(f)
                if 'nai_token_last_verified' in data:
                    self.nai_last_verified_label.setText(f"마지막 검증 일자: {data['nai_token_last_verified']}")
                if 'webui_url_last_verified' in data:
                    self.webui_last_verified_label.setText(f"마지막 검증 일자: {data['webui_url_last_verified']}")
            except (json.JSONDecodeError, KeyError):
                pass

    def _save_timestamp(self, key: str):
        """검증 타임스탬프를 JSON 파일에 저장"""
        data = {}
        if os.path.exists(self.TIMESTAMP_FILE):
            with open(self.TIMESTAMP_FILE, 'r') as f:
                try: data = json.load(f)
                except json.JSONDecodeError: pass
        
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        data[f"{key}_last_verified"] = timestamp
        
        with open(self.TIMESTAMP_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        
        if key == 'nai_token':
            self.nai_last_verified_label.setText(f"마지막 검증 일자: {timestamp}")
        elif key == 'webui_url':
            self.webui_last_verified_label.setText(f"마지막 검증 일자: {timestamp}")

    def _verify_nai_token(self):
        token = self.nai_token_input.text()
        if not token:
            QMessageBox.warning(self, "입력 오류", "토큰을 입력해주세요.")
            return
            
        self.main_window.status_bar.showMessage("NAI 토큰 검증 중...")
        self.nai_verify_btn.setEnabled(False)
        
        # [수정] QThread와 워커를 사용한 백그라운드 작업 실행
        self.worker_thread = QThread()
        self.validator = APIValidator()
        self.validator.moveToThread(self.worker_thread)

        # 시그널-슬롯 연결
        self.worker_thread.started.connect(lambda: self.validator.run_nai_validation(token))
        self.validator.nai_validation_finished.connect(self._on_nai_validation_complete)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        
        self.worker_thread.start()

    def _verify_webui_url(self):
        """WebUI 연결 검증 스레드 시작"""
        url = self.webui_url_input.text()
        if not url:
            QMessageBox.warning(self, "입력 오류", "WebUI 주소를 입력해주세요.")
            return
        
        self.main_window.status_bar.showMessage("WebUI 연결 테스트 중...")
        self.webui_verify_btn.setEnabled(False)

        # [수정] QThread와 워커를 사용한 백그라운드 작업 실행
        self.worker_thread = QThread()
        self.validator = APIValidator()
        self.validator.moveToThread(self.worker_thread)

        # 시그널-슬롯 연결
        self.worker_thread.started.connect(lambda: self.validator.run_webui_validation(url))
        self.validator.webui_validation_finished.connect(self._on_webui_validation_complete)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        
        self.worker_thread.start()

    # [신규] NAI 검증 완료 시 호출될 슬롯
    def _on_nai_validation_complete(self, success: bool, value: str, message: str, message_type: str):
        self.nai_verify_btn.setEnabled(True)
        if success:
            self.token_manager.save_token('nai_token', value)
            self._save_timestamp('nai_token')
        
        self._show_result_message('NAI', message, message_type)
        self.worker_thread.quit() # 스레드 종료

    # [신규] WebUI 검증 완료 시 호출될 슬롯
    def _on_webui_validation_complete(self, success: bool, value: str, message: str, message_type: str):
        self.webui_verify_btn.setEnabled(True)
        if success:
            self.token_manager.save_token('webui_url', value)
            self._save_timestamp('webui_url')
        
        self._show_result_message('WebUI', message, message_type)
        self.worker_thread.quit() # 스레드 종료

    # [신규] 메시지 박스와 상태바를 업데이트하는 공통 메서드
    def _show_result_message(self, api_type: str, message: str, message_type: str):
        self.main_window.status_bar.showMessage(message, 10000)
        msg_box = QMessageBox(self)
        msg_box_map = { "info": QMessageBox.Icon.Information, "warning": QMessageBox.Icon.Warning, "error": QMessageBox.Icon.Critical }
        msg_box.setIcon(msg_box_map.get(message_type, QMessageBox.Icon.NoIcon))
        msg_box.setText(f"{api_type} 검증 결과")
        msg_box.setInformativeText(message)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.exec()

    def _update_verification_result(self, api_type: str, success: bool, value: str, message: str, message_type: str):
        """(메인 스레드) 검증 결과에 따라 UI 업데이트"""
        if api_type == 'nai':
            self.nai_verify_btn.setEnabled(True)
            if success:
                # [보안 강화] 토큰을 키링에 저장하고, 타임스탬프는 파일에 저장
                self.token_manager.save_token('nai_token', value)
                self._save_timestamp('nai_token')
        elif api_type == 'webui':
            self.webui_verify_btn.setEnabled(True)
            if success:
                # [보안 강화] URL을 키링에 저장하고, 타임스탬프는 파일에 저장
                self.token_manager.save_token('webui_url', value)
                self._save_timestamp('webui_url')
        
        # ... 메시지 박스 표시는 그대로 ...
        self.main_window.status_bar.showMessage(message, 10000)
        msg_box = QMessageBox(self)
        # ...
        msg_box.exec()