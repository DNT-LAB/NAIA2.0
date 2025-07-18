import json
import os
import requests
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QTextEdit, QFrame, QMessageBox, QComboBox
)
from PyQt6.QtCore import QThread
from ui.theme import DARK_STYLES, DARK_COLORS
from core.api_validator import APIValidator
from core.context import AppContext

class APIManagementWindow(QWidget):
    """NAI 토큰, WebUI API, ComfyUI API를 관리하는 전용 위젯"""
    
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
        main_layout.addWidget(self._create_comfyui_section())  # 🆕 ComfyUI 섹션 추가
        main_layout.addStretch(1)

        self.nai_verify_btn.clicked.connect(self._verify_nai_token)
        self.webui_verify_btn.clicked.connect(self._verify_webui_url)
        self.comfyui_verify_btn.clicked.connect(self._verify_comfyui_url)  # 🆕 ComfyUI 검증
        self.comfyui_refresh_models_btn.clicked.connect(self._refresh_comfyui_models)  # 🆕 모델 새로고침
        
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

        # 설명
        desc_box = QTextEdit()
        desc_box.setReadOnly(True)
        desc_box.setText("NovelAI 영구 토큰을 입력하면 Opus 등급 구독 여부를 확인합니다. 토큰은 암호화되어 저장됩니다.")
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

    def _create_comfyui_section(self) -> QFrame:
        """🆕 ComfyUI API 입력 섹션 UI 생성"""
        frame, layout = self._create_section_frame("🎨 ComfyUI API")

        # URL 입력 라인
        url_input_layout = QHBoxLayout()
        self.comfyui_url_input = QLineEdit()
        self.comfyui_url_input.setPlaceholderText("예: 127.0.0.1:8188")
        self.comfyui_url_input.setStyleSheet(DARK_STYLES['compact_lineedit'])
        self.comfyui_verify_btn = QPushButton("검증")
        self.comfyui_verify_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.comfyui_verify_btn.setFixedWidth(80)
        url_input_layout.addWidget(self.comfyui_url_input)
        url_input_layout.addWidget(self.comfyui_verify_btn)
        layout.addLayout(url_input_layout)
        
        # 모델 선택 및 새로고침 라인
        model_layout = QHBoxLayout()
        model_label = QLabel("기본 모델:")
        model_label.setStyleSheet(DARK_STYLES['label_style'])
        model_label.setFixedWidth(80)
        
        self.comfyui_model_combo = QComboBox()
        self.comfyui_model_combo.setStyleSheet(DARK_STYLES['compact_lineedit'])
        self.comfyui_model_combo.addItem("연결 후 모델 목록을 불러오세요")
        
        self.comfyui_refresh_models_btn = QPushButton("새로고침")
        self.comfyui_refresh_models_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.comfyui_refresh_models_btn.setFixedWidth(100)
        self.comfyui_refresh_models_btn.setEnabled(False)  # 초기에는 비활성화
        
        model_layout.addWidget(model_label)
        model_layout.addWidget(self.comfyui_model_combo, 1)
        model_layout.addWidget(self.comfyui_refresh_models_btn)
        #layout.addLayout(model_layout)

        # 샘플링 모드 선택 라인
        sampling_layout = QHBoxLayout()
        sampling_label = QLabel("샘플링 모드:")
        sampling_label.setStyleSheet(DARK_STYLES['label_style'])
        sampling_label.setFixedWidth(80)
        
        self.comfyui_sampling_combo = QComboBox()
        self.comfyui_sampling_combo.setStyleSheet(DARK_STYLES['compact_lineedit'])
        self.comfyui_sampling_combo.addItems(["eps", "v_prediction"])
        
        sampling_layout.addWidget(sampling_label)
        sampling_layout.addWidget(self.comfyui_sampling_combo, 1)
        sampling_layout.addStretch()  # 오른쪽 여백
        #layout.addLayout(sampling_layout)
        
        # 설명
        desc_box = QTextEdit()
        desc_box.setReadOnly(True)
        desc_box.setText("실행 중인 ComfyUI 서버의 웹 주소를 입력합니다.")
        desc_box.setFixedHeight(80)
        desc_box.setStyleSheet(DARK_STYLES['compact_textedit'])
        layout.addWidget(desc_box)
        
        # 연결 상태 및 마지막 검증 일자
        self.comfyui_status_label = QLabel("연결 상태: 미연결")
        self.comfyui_status_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: 16px;")
        layout.addWidget(self.comfyui_status_label)
        
        self.comfyui_last_verified_label = QLabel("마지막 검증 일자: 정보 없음")
        self.comfyui_last_verified_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: 16px;")
        layout.addWidget(self.comfyui_last_verified_label)

        return frame

    def _load_data(self):
        """키링에서 토큰을, JSON 파일에서 타임스탬프를 로드"""
        # 키링에서 토큰 로드
        self.nai_token_input.setText(self.token_manager.get_token('nai_token'))
        self.webui_url_input.setText(self.token_manager.get_token('webui_url'))
        self.comfyui_url_input.setText(self.token_manager.get_token('comfyui_url'))  # 🆕 ComfyUI URL 로드
        
        # 저장된 ComfyUI 설정 로드
        saved_model = self.token_manager.get_token('comfyui_default_model')
        saved_sampling = self.token_manager.get_token('comfyui_sampling_mode')
        
        if saved_sampling:
            index = self.comfyui_sampling_combo.findText(saved_sampling)
            if index >= 0:
                self.comfyui_sampling_combo.setCurrentIndex(index)

        # 파일에서 마지막 검증 시간 로드
        if os.path.exists(self.TIMESTAMP_FILE):
            try:
                with open(self.TIMESTAMP_FILE, 'r') as f:
                    data = json.load(f)
                if 'nai_token_last_verified' in data:
                    self.nai_last_verified_label.setText(f"마지막 검증 일자: {data['nai_token_last_verified']}")
                if 'webui_url_last_verified' in data:
                    self.webui_last_verified_label.setText(f"마지막 검증 일자: {data['webui_url_last_verified']}")
                if 'comfyui_url_last_verified' in data:  # 🆕 ComfyUI 타임스탬프 로드
                    self.comfyui_last_verified_label.setText(f"마지막 검증 일자: {data['comfyui_url_last_verified']}")
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
        elif key == 'comfyui_url':  # 🆕 ComfyUI 타임스탬프 업데이트
            self.comfyui_last_verified_label.setText(f"마지막 검증 일자: {timestamp}")

    def _verify_nai_token(self):
        token = self.nai_token_input.text()
        if not token:
            QMessageBox.warning(self, "입력 오류", "토큰을 입력해주세요.")
            return
            
        self.main_window.status_bar.showMessage("NAI 토큰 검증 중...")
        self.nai_verify_btn.setEnabled(False)
        
        # QThread와 워커를 사용한 백그라운드 작업 실행
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

        # QThread와 워커를 사용한 백그라운드 작업 실행
        self.worker_thread = QThread()
        self.validator = APIValidator()
        self.validator.moveToThread(self.worker_thread)

        # 시그널-슬롯 연결
        self.worker_thread.started.connect(lambda: self.validator.run_webui_validation(url))
        self.validator.webui_validation_finished.connect(self._on_webui_validation_complete)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        
        self.worker_thread.start()

    def _verify_comfyui_url(self):
        """🆕 ComfyUI 연결 검증 (동기식으로 변경)"""
        url = self.comfyui_url_input.text()
        if not url:
            QMessageBox.warning(self, "입력 오류", "ComfyUI 주소를 입력해주세요.")
            return
        
        self.main_window.status_bar.showMessage("ComfyUI 연결 테스트 중...")
        self.comfyui_verify_btn.setEnabled(False)
        self.comfyui_status_label.setText("연결 상태: 검증 중...")

        # 🔧 동기식으로 직접 검증 실행 (threading 사용 안함)
        success, valid_url, message, message_type = self._validate_comfyui_url_sync(url)
        
        # 결과 처리
        self._on_comfyui_validation_complete(success, valid_url, message, message_type)

    def _refresh_comfyui_models(self):
        """🆕 ComfyUI 모델 목록 새로고침 (동기식으로 변경)"""
        url = self.comfyui_url_input.text()
        if not url:
            QMessageBox.warning(self, "오류", "먼저 ComfyUI URL을 입력하고 연결을 검증해주세요.")
            return
        
        self.main_window.status_bar.showMessage("ComfyUI 모델 목록 로딩 중...")
        self.comfyui_refresh_models_btn.setEnabled(False)
        
        # 🔧 동기식으로 직접 모델 목록 가져오기 (threading 사용 안함)
        success, models, message = self._fetch_comfyui_models_sync(url)
        
        # 결과 처리
        self._on_comfyui_models_loaded(success, models, message)

    def _validate_comfyui_url_sync(self, url: str) -> tuple:
        """🆕 ComfyUI URL 동기식 검증"""
        try:
            # URL 정규화
            clean_url = url.replace('http://', '').replace('https://', '').rstrip('/')
            protocols = [f"http://{clean_url}", f"https://{clean_url}"]
            
            for base_url in protocols:
                try:
                    response = requests.get(f"{base_url}/system_stats", timeout=5)
                    if response.status_code == 200:
                        stats = response.json()
                        device_info = stats.get('system', {})
                        gpu_name = device_info.get('gpu_name', 'Unknown GPU')
                        ram_total = device_info.get('ram_total', 0)
                        
                        ram_gb = ram_total / (1024**3) if ram_total > 0 else 0
                        message = f"✅ ComfyUI 연결 성공!\nGPU: {gpu_name}\nRAM: {ram_gb:.1f}GB"
                        return True, clean_url, message, "info"
                except requests.exceptions.RequestException:
                    continue
            
            return False, url, f"❌ ComfyUI 연결 실패: '{url}' 주소를 확인하고 서버가 실행 중인지 확인해주세요.", "error"
            
        except Exception as e:
            return False, url, f"❌ ComfyUI 검증 중 오류 발생: {str(e)}", "error"

    def _fetch_comfyui_models_sync(self, url: str) -> tuple:
        """🆕 ComfyUI 모델 목록 동기식 가져오기"""
        try:
            # URL 정규화
            clean_url = url.replace('http://', '').replace('https://', '').rstrip('/')
            normalized_url = f"http://{clean_url}"
            
            response = requests.get(f"{normalized_url}/object_info", timeout=10)
            
            if response.status_code == 200:
                object_info = response.json()
                
                # CheckpointLoaderSimple 노드에서 모델 목록 추출
                checkpoint_loader = object_info.get('CheckpointLoaderSimple', {})
                input_info = checkpoint_loader.get('input', {})
                required_info = input_info.get('required', {})
                ckpt_name_info = required_info.get('ckpt_name', [])
                
                if isinstance(ckpt_name_info, list) and len(ckpt_name_info) > 0:
                    models = ckpt_name_info[0]  # 첫 번째 요소가 모델 리스트
                    if isinstance(models, list) and len(models) > 0:
                        return True, models, f"모델 {len(models)}개 발견"
                    else:
                        return False, [], "사용 가능한 모델이 없습니다."
                else:
                    return False, [], "모델 정보를 찾을 수 없습니다."
            else:
                return False, [], f"API 응답 오류 (HTTP {response.status_code})"
                
        except requests.exceptions.Timeout:
            return False, [], "모델 목록 로드 시간 초과"
        except requests.exceptions.ConnectionError:
            return False, [], "ComfyUI 서버 연결 실패"
        except Exception as e:
            return False, [], f"모델 목록 로드 실패: {str(e)}"

    # NAI 검증 완료 시 호출될 슬롯
    def _on_nai_validation_complete(self, success: bool, value: str, message: str, message_type: str):
        self.nai_verify_btn.setEnabled(True)
        if success:
            self.token_manager.save_token('nai_token', value)
            self._save_timestamp('nai_token')
        
        self._show_result_message('NAI', message, message_type)
        self.worker_thread.quit()

    # WebUI 검증 완료 시 호출될 슬롯
    def _on_webui_validation_complete(self, success: bool, value: str, message: str, message_type: str):
        self.webui_verify_btn.setEnabled(True)
        if success:
            self.token_manager.save_token('webui_url', value)
            self._save_timestamp('webui_url')
        
        self._show_result_message('WebUI', message, message_type)
        self.worker_thread.quit()

    def _on_comfyui_validation_complete(self, success: bool, value: str, message: str, message_type: str):
        """🆕 ComfyUI 검증 완료 시 호출될 슬롯"""
        self.comfyui_verify_btn.setEnabled(True)
        
        if success:
            self.token_manager.save_token('comfyui_url', value)
            self._save_timestamp('comfyui_url')
            self.comfyui_status_label.setText("연결 상태: 연결됨 ✅")
            self.comfyui_refresh_models_btn.setEnabled(True)
            
            # 샘플링 모드 저장
            sampling_mode = self.comfyui_sampling_combo.currentText()
            self.token_manager.save_token('comfyui_sampling_mode', sampling_mode)
            
            # 자동으로 모델 목록 새로고침
            self._refresh_comfyui_models()
        else:
            self.comfyui_status_label.setText("연결 상태: 연결 실패 ❌")
            self.comfyui_refresh_models_btn.setEnabled(False)
        
        self._show_result_message('ComfyUI', message, message_type)

    def _on_comfyui_models_loaded(self, success: bool, models: list, message: str):
        """🆕 ComfyUI 모델 목록 로드 완료 시 호출될 슬롯"""
        self.comfyui_refresh_models_btn.setEnabled(True)
        
        if success and models:
            # 기존 아이템 제거
            self.comfyui_model_combo.clear()
            
            # 새 모델 목록 추가
            self.comfyui_model_combo.addItems(models)
            
            # 저장된 기본 모델이 있으면 선택
            saved_model = self.token_manager.get_token('comfyui_default_model')
            if saved_model and saved_model in models:
                index = self.comfyui_model_combo.findText(saved_model)
                if index >= 0:
                    self.comfyui_model_combo.setCurrentIndex(index)
            
            self.main_window.status_bar.showMessage(f"모델 {len(models)}개 로드 완료", 3000)
        else:
            self.comfyui_model_combo.clear()
            self.comfyui_model_combo.addItem("모델 로드 실패")
            self.main_window.status_bar.showMessage(f"모델 로드 실패: {message}", 5000)

    # 메시지 박스와 상태바를 업데이트하는 공통 메서드
    def _show_result_message(self, api_type: str, message: str, message_type: str):
        self.main_window.status_bar.showMessage(message, 10000)
        msg_box = QMessageBox(self)
        msg_box_map = { 
            "info": QMessageBox.Icon.Information, 
            "warning": QMessageBox.Icon.Warning, 
            "error": QMessageBox.Icon.Critical 
        }
        msg_box.setIcon(msg_box_map.get(message_type, QMessageBox.Icon.NoIcon))
        msg_box.setText(f"{api_type} 검증 결과")
        msg_box.setInformativeText(message)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.exec()

    def get_comfyui_settings(self) -> dict:
        """🆕 현재 ComfyUI 설정을 반환하는 메서드"""
        return {
            'url': self.comfyui_url_input.text(),
            'default_model': self.comfyui_model_combo.currentText() if self.comfyui_model_combo.count() > 0 else '',
            'sampling_mode': self.comfyui_sampling_combo.currentText()
        }

    def save_comfyui_settings(self):
        """🆕 현재 ComfyUI 설정을 저장하는 메서드"""
        settings = self.get_comfyui_settings()
        if settings['default_model'] and settings['default_model'] != "연결 후 모델 목록을 불러오세요":
            self.token_manager.save_token('comfyui_default_model', settings['default_model'])
        self.token_manager.save_token('comfyui_sampling_mode', settings['sampling_mode'])