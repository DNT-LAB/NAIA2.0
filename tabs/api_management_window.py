import json
import os
import requests
from datetime import datetime
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QFrame, QMessageBox, QComboBox, QCheckBox
)
from PyQt6.QtCore import QThread, Qt
from ui.theme import DARK_STYLES, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size
from core.api_validator import APIValidator
from core.context import AppContext
from interfaces.base_tab_module import BaseTabModule

class APIManagementTabModule(BaseTabModule):
    """'API 관리' 탭을 동적으로 로드하기 위한 모듈"""

    def __init__(self):
        super().__init__()
        self.widget: APIManagementWindow = None

    def get_tab_title(self) -> str:
        return "⚙️ API 관리"

    def get_tab_type(self) -> str:
        return 'closable' # 이 탭은 요청 시에만 로드됩니다.

    def can_close_tab(self) -> bool:
        # 이 탭은 닫을 수 있습니다.
        return True

    def create_widget(self, parent: QWidget) -> QWidget:
        if self.widget is None:
            self.widget = APIManagementWindow(self.app_context, parent)
        return self.widget

class APIManagementWindow(QWidget):
    """NAI 토큰, WebUI API, ComfyUI API를 관리하는 전용 위젯"""

    TIMESTAMP_FILE = "NAIA_api_timestamps.json"
    ACCOUNTS_FILE = "save/nai_accounts.json"

    def __init__(self, app_context: AppContext, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        # ✅ [수정] main_window와 token_manager를 app_context에서 가져옴
        self.main_window = self.app_context.main_window
        self.token_manager = self.app_context.secure_token_manager

        self.worker_thread = None
        self.validator = None

        # 🆕 추가 계정 관리
        self.accounts_data = self._load_accounts()
        self.account_rows = {}  # 🔄 dict로 변경: {account_id: checkbox_widget}

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
        self._update_round_robin_status()

    # ========== 🆕 계정 데이터 관리 ==========

    def _load_accounts(self) -> dict:
        """계정 메타데이터 로드 및 검증"""
        try:
            if os.path.exists(self.ACCOUNTS_FILE):
                with open(self.ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 🆕 main_account_enabled 기본값 설정
                    if 'main_account_enabled' not in data:
                        data['main_account_enabled'] = True

                    # 🆕 안전장치: 활성 계정이 하나도 없으면 메인 계정 자동 활성화
                    main_enabled = data.get('main_account_enabled', True)
                    additional_enabled_count = sum(1 for acc in data.get('accounts', []) if acc.get('enabled', False))

                    if not main_enabled and additional_enabled_count == 0:
                        print("⚠️ 활성 계정이 없습니다. 메인 계정을 자동으로 활성화합니다.")
                        data['main_account_enabled'] = True
                        data['auto_recovered'] = True  # 자동 복구 플래그
                        # 즉시 저장
                        try:
                            Path(self.ACCOUNTS_FILE).parent.mkdir(exist_ok=True)
                            with open(self.ACCOUNTS_FILE, 'w', encoding='utf-8') as f_save:
                                json.dump(data, f_save, indent=2, ensure_ascii=False)
                        except Exception as save_err:
                            print(f"⚠️ 자동 복구 상태 저장 실패: {save_err}")
                    else:
                        data['auto_recovered'] = False

                    return data
            else:
                return {
                    "accounts": [],
                    "round_robin_enabled": False,
                    "main_account_enabled": True,  # 🆕 기본값: 활성화
                    "auto_recovered": False
                }
        except Exception as e:
            print(f"⚠️ 계정 데이터 로드 실패: {e}")
            return {
                "accounts": [],
                "round_robin_enabled": False,
                "main_account_enabled": True,  # 🆕 기본값: 활성화
                "auto_recovered": False
            }

    def _save_accounts(self):
        """계정 메타데이터 저장"""
        try:
            Path(self.ACCOUNTS_FILE).parent.mkdir(exist_ok=True)
            with open(self.ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.accounts_data, f, indent=2, ensure_ascii=False)
            print(f"✅ 계정 데이터 저장 완료: {len(self.accounts_data['accounts'])}개")
        except Exception as e:
            print(f"❌ 계정 데이터 저장 실패: {e}")

    def _get_next_account_id(self) -> str:
        """다음 계정 ID 생성 (nai_token_1, nai_token_2, ...)"""
        existing_ids = [acc['id'] for acc in self.accounts_data['accounts']]
        index = 1
        while f"nai_token_{index}" in existing_ids:
            index += 1
        return f"nai_token_{index}"

    def _get_account_label(self, account_id: str) -> str:
        """계정 ID로부터 라벨 생성 (계정2, 계정3, ...)"""
        if account_id == "nai_token":
            return "메인 계정"

        # nai_token_1 -> "계정2"
        index = int(account_id.split('_')[-1])
        return f"계정{index + 1}"

    # ========== 유틸리티 메서드 ==========

    def _get_token_preview(self, token: str) -> str:
        """토큰의 앞 7자를 반환 (없으면 빈 문자열)"""
        if not token:
            return ""
        return token[:7] if len(token) >= 7 else token

    # ========== UI 생성 ==========

    def _create_section_frame(self, title_text: str) -> tuple:
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
        """🆕 NAI 토큰 입력 섹션 UI 생성 (멀티 계정 지원)"""
        frame, layout = self._create_section_frame("🔑 NovelAI API Token")

        # ─── 메인 계정 ───
        main_layout = QHBoxLayout()
        main_layout.setSpacing(8)

        # 🆕 메인 계정 체크박스
        self.main_account_checkbox = QCheckBox()
        self.main_account_checkbox.setChecked(self.accounts_data.get('main_account_enabled', True))
        self.main_account_checkbox.setFixedWidth(40)
        self.main_account_checkbox.stateChanged.connect(
            lambda state: self._on_main_account_enabled_changed(state == Qt.CheckState.Checked.value)
        )

        # 🆕 메인 계정 라벨 (토큰 프리뷰 포함)
        main_token = self.token_manager.get_token('nai_token')
        token_preview = self._get_token_preview(main_token)
        label_text = f"메인 계정 ({token_preview}...):" if token_preview else "메인 계정:"

        self.main_account_label = QLabel(label_text)
        self.main_account_label.setStyleSheet(DARK_STYLES['label_style'])
        self.main_account_label.setFixedWidth(200)

        self.nai_token_input = QLineEdit()
        self.nai_token_input.setPlaceholderText("여기에 NAI 영구 토큰을 붙여넣으세요...")
        self.nai_token_input.setStyleSheet(DARK_STYLES['compact_lineedit'])
        self.nai_token_input.setEchoMode(QLineEdit.EchoMode.Password)

        self.nai_verify_btn = QPushButton("검증")
        self.nai_verify_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.nai_verify_btn.setFixedWidth(80)

        main_layout.addWidget(self.main_account_checkbox)
        main_layout.addWidget(self.main_account_label)
        main_layout.addWidget(self.nai_token_input)
        main_layout.addWidget(self.nai_verify_btn)
        layout.addLayout(main_layout)

        self.nai_last_verified_label = QLabel("마지막 검증 일자: 정보 없음")
        self.nai_last_verified_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(16)}px;")
        layout.addWidget(self.nai_last_verified_label)

        # 설명
        desc_box = QTextEdit()
        desc_box.setReadOnly(True)
        desc_box.setText("NovelAI 영구 토큰을 입력하면 Opus 등급 구독 여부를 확인합니다. 토큰은 암호화되어 저장됩니다.")
        desc_box.setFixedHeight(60)
        desc_box.setStyleSheet(DARK_STYLES['compact_textedit'])
        layout.addWidget(desc_box)

        # 구분선
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        separator.setFixedHeight(1)
        layout.addWidget(separator)

        # ─── 추가 계정 섹션 ───
        additional_label = QLabel("추가 계정:")
        additional_label.setStyleSheet(DARK_STYLES['label_style'])
        layout.addWidget(additional_label)

        # 🆕 추가 계정 리스트 컨테이너
        self.accounts_list_layout = QVBoxLayout()
        self.accounts_list_layout.setSpacing(4)
        layout.addLayout(self.accounts_list_layout)

        # 기존 계정 로드
        for account in self.accounts_data['accounts']:
            self._add_account_row(account['id'], account['label'], account['enabled'])

        # [계정 추가] 버튼
        add_account_btn = QPushButton("➕ NovelAI 영구토큰 추가")
        add_account_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        add_account_btn.clicked.connect(self._on_add_account_clicked)
        layout.addWidget(add_account_btn)

        # ─── 라운드 로빈 모드 ───
        self.round_robin_checkbox = QCheckBox("라운드-로빈 모드")
        self.round_robin_checkbox.setStyleSheet(f"""
            QCheckBox {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(16)}px;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
            }}
        """)
        self.round_robin_checkbox.setChecked(self.accounts_data.get('round_robin_enabled', False))
        self.round_robin_checkbox.stateChanged.connect(self._on_round_robin_toggled)
        layout.addWidget(self.round_robin_checkbox)

        # 현재 상태 라벨
        self.round_robin_status_label = QLabel("")
        self.round_robin_status_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(14)}px;")
        layout.addWidget(self.round_robin_status_label)

        return frame

    def _add_account_row(self, account_id: str, label: str, enabled: bool):
        """🆕 계정 행 추가 (UI)"""
        row_layout = QHBoxLayout()
        row_layout.setSpacing(8)

        # 체크박스
        checkbox = QCheckBox()
        checkbox.setChecked(enabled)
        checkbox.setFixedWidth(40)
        checkbox.stateChanged.connect(lambda state, aid=account_id: self._on_account_enabled_changed(aid, state == Qt.CheckState.Checked.value))

        # 저장된 토큰 로드
        saved_token = self.token_manager.get_token(account_id)

        # 🆕 라벨 (토큰 프리뷰 포함)
        token_preview = self._get_token_preview(saved_token)
        label_text = f"{label} ({token_preview}...):" if token_preview else f"{label}:"

        label_widget = QLabel(label_text)
        label_widget.setStyleSheet(DARK_STYLES['label_style'])
        label_widget.setFixedWidth(180)

        # 토큰 입력
        token_input = QLineEdit()
        token_input.setPlaceholderText("토큰 입력...")
        token_input.setStyleSheet(DARK_STYLES['compact_lineedit'])
        token_input.setEchoMode(QLineEdit.EchoMode.Password)

        # 저장된 토큰 설정 (마스킹)
        if saved_token:
            token_input.setText(saved_token)

        # 검증 버튼
        verify_btn = QPushButton("검증")
        verify_btn.setStyleSheet(DARK_STYLES['primary_button'])
        verify_btn.setFixedWidth(80)
        verify_btn.clicked.connect(lambda checked, aid=account_id, inp=token_input: self._verify_additional_account(aid, inp))

        # 삭제 버튼
        delete_btn = QPushButton("✕")
        delete_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        delete_btn.setFixedWidth(40)
        delete_btn.clicked.connect(lambda checked, aid=account_id: self._on_delete_account_clicked(aid))

        row_layout.addWidget(checkbox)
        row_layout.addWidget(label_widget)
        row_layout.addWidget(token_input)
        row_layout.addWidget(verify_btn)
        row_layout.addWidget(delete_btn)

        self.accounts_list_layout.addLayout(row_layout)

        # 🔄 행 추적 (딕셔너리 방식)
        self.account_rows[account_id] = {
            'layout': row_layout,
            'checkbox': checkbox,
            'label': label_widget,  # 🆕 라벨도 저장 (업데이트용)
            'token_input': token_input,
            'verify_btn': verify_btn,
            'delete_btn': delete_btn
        }

    def _on_add_account_clicked(self):
        """🆕 [계정 추가] 버튼 클릭"""
        account_id = self._get_next_account_id()
        label = self._get_account_label(account_id)

        # 데이터 추가
        new_account = {
            'id': account_id,
            'label': label,
            'enabled': False,
            'last_verified': None
        }
        self.accounts_data['accounts'].append(new_account)
        self._save_accounts()

        # UI 추가
        self._add_account_row(account_id, label, False)

        print(f"✅ 계정 추가: {label} ({account_id})")

    def _on_delete_account_clicked(self, account_id: str):
        """🆕 [삭제] 버튼 클릭"""
        # 확인 대화상자
        reply = QMessageBox.question(
            self,
            "계정 삭제",
            f"'{self._get_account_label(account_id)}'를 삭제하시겠습니까?\n토큰도 함께 삭제됩니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # 데이터에서 제거
        self.accounts_data['accounts'] = [acc for acc in self.accounts_data['accounts'] if acc['id'] != account_id]
        self._save_accounts()

        # keyring에서 토큰 삭제
        try:
            import keyring
            keyring.delete_password(self.token_manager.SERVICE_NAME, account_id)
        except Exception as e:
            print(f"⚠️ keyring 토큰 삭제 실패: {e}")

        # UI에서 제거
        if account_id in self.account_rows:
            row_data = self.account_rows[account_id]
            row_layout = row_data['layout']

            # 레이아웃의 모든 위젯 제거
            while row_layout.count():
                item = row_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            # 레이아웃 제거
            self.accounts_list_layout.removeItem(row_layout)
            row_layout.deleteLater()

            # 추적 딕셔너리에서 제거
            self.account_rows.pop(account_id)

        self._update_round_robin_status()
        print(f"✅ 계정 삭제 완료: {account_id}")

    def _on_main_account_enabled_changed(self, enabled: bool):
        """🆕 메인 계정 활성화 체크박스 변경"""

        # 🆕 안전장치: 마지막 활성 계정을 비활성화하려는 시도 차단
        if not enabled:
            additional_enabled_count = sum(1 for acc in self.accounts_data['accounts'] if acc.get('enabled', False))
            if additional_enabled_count == 0:
                print("⚠️ 최소 1개 계정은 활성화 상태여야 합니다. 메인 계정을 비활성화할 수 없습니다.")
                # 체크박스를 다시 활성화 상태로 되돌림
                self.main_account_checkbox.setChecked(True)
                return

        self.accounts_data['main_account_enabled'] = enabled

        # 라운드-로빈 OFF 모드: 배타적 선택
        if not self.accounts_data.get('round_robin_enabled', False):
            if enabled:
                # 메인 계정 활성화 시 모든 추가 계정 비활성화
                for account_id, row_data in self.account_rows.items():
                    row_data['checkbox'].setChecked(False)
                    # 데이터도 업데이트
                    for account in self.accounts_data['accounts']:
                        if account['id'] == account_id:
                            account['enabled'] = False

        self._save_accounts()
        self._update_round_robin_status()
        print(f"{'✅' if enabled else '⚠️'} 메인 계정 {'활성화' if enabled else '비활성화'}")

    def _on_account_enabled_changed(self, account_id: str, enabled: bool):
        """🆕 계정 활성화 체크박스 변경"""

        # 🆕 안전장치: 마지막 활성 계정을 비활성화하려는 시도 차단
        if not enabled:
            main_enabled = self.accounts_data.get('main_account_enabled', True)
            other_enabled_count = sum(1 for acc in self.accounts_data['accounts']
                                      if acc.get('enabled', False) and acc['id'] != account_id)

            if not main_enabled and other_enabled_count == 0:
                print(f"⚠️ 최소 1개 계정은 활성화 상태여야 합니다. {account_id}를 비활성화할 수 없습니다.")
                # 체크박스를 다시 활성화 상태로 되돌림
                if account_id in self.account_rows:
                    self.account_rows[account_id]['checkbox'].setChecked(True)
                return

        # 데이터 업데이트
        for account in self.accounts_data['accounts']:
            if account['id'] == account_id:
                account['enabled'] = enabled
                break

        # 라운드-로빈 OFF 모드: 배타적 선택
        if not self.accounts_data.get('round_robin_enabled', False):
            if enabled:
                # 메인 계정 비활성화
                self.main_account_checkbox.setChecked(False)
                self.accounts_data['main_account_enabled'] = False

                # 다른 추가 계정들 비활성화
                for other_id, row_data in self.account_rows.items():
                    if other_id != account_id:
                        row_data['checkbox'].setChecked(False)
                        # 데이터도 업데이트
                        for account in self.accounts_data['accounts']:
                            if account['id'] == other_id:
                                account['enabled'] = False

        self._save_accounts()
        self._update_round_robin_status()
        print(f"{'✅' if enabled else '⚠️'} {account_id} {'활성화' if enabled else '비활성화'}")

    def _on_round_robin_toggled(self, state):
        """🆕 라운드-로빈 모드 체크박스 토글"""
        enabled = (state == Qt.CheckState.Checked.value)
        self.accounts_data['round_robin_enabled'] = enabled
        self._save_accounts()
        self._update_round_robin_status()
        print(f"🔄 라운드-로빈 모드: {'활성화' if enabled else '비활성화'}")

    def _update_round_robin_status(self):
        """🆕 라운드-로빈 상태 라벨 업데이트"""
        # 활성 계정 수 계산 (메인 포함)
        main_token = self.token_manager.get_token('nai_token')
        main_enabled = self.accounts_data.get('main_account_enabled', True)
        enabled_count = (1 if (main_token and main_enabled) else 0)
        enabled_count += sum(1 for acc in self.accounts_data['accounts'] if acc['enabled'])

        if self.accounts_data.get('round_robin_enabled', False):
            # 라운드-로빈 모드
            if enabled_count > 0:
                counter = self.app_context.image_crud_controller.get_counter()
                current_index = counter % enabled_count
                self.round_robin_status_label.setText(
                    f"현재: {enabled_count}개 계정 순환 중 (카운터: {counter}, 인덱스: {current_index})"
                )
            else:
                self.round_robin_status_label.setText("⚠️ 활성 계정이 없습니다")
        else:
            # 단일 모드
            if enabled_count > 0:
                self.round_robin_status_label.setText(f"현재: 단일 모드 (활성 계정: {enabled_count}개)")
            else:
                self.round_robin_status_label.setText("⚠️ 활성 계정이 없습니다")

    # ========== 검증 로직 ==========

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
        self.webui_last_verified_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(16)}px;")
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
        self.comfyui_sampling_combo.addItems(["eps", "v_prediction", "anima"])  # 🆕 anima 옵션 추가

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
        self.comfyui_status_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(16)}px;")
        layout.addWidget(self.comfyui_status_label)

        self.comfyui_last_verified_label = QLabel("마지막 검증 일자: 정보 없음")
        self.comfyui_last_verified_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(16)}px;")
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
        """메인 NAI 토큰 검증"""
        token = self.nai_token_input.text()
        if not token:
            QMessageBox.warning(self, "입력 오류", "토큰을 입력해주세요.")
            return

        # 🆕 테스트 토큰 처리
        if token == "api_test_BCF13af9#d":
            print("🧪 테스트 토큰 감지 - 검증 건너뛰기")
            self.token_manager.save_token('nai_token', token)
            self._save_timestamp('nai_token')
            QMessageBox.information(self, "NAI 검증 결과", "✅ 테스트 토큰 (검증 생략)")
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

    def _verify_additional_account(self, account_id: str, token_input: QLineEdit):
        """🆕 추가 계정 토큰 검증"""
        token = token_input.text()
        if not token:
            QMessageBox.warning(self, "입력 오류", f"{self._get_account_label(account_id)} 토큰을 입력해주세요.")
            return

        # 🆕 테스트 토큰 처리
        if token == "api_test_BCF13af9#d":
            print(f"🧪 {account_id} 테스트 토큰 감지 - 검증 건너뛰기")
            self.token_manager.save_token(account_id, token)

            # 메타데이터 업데이트
            for account in self.accounts_data['accounts']:
                if account['id'] == account_id:
                    account['last_verified'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    break
            self._save_accounts()

            QMessageBox.information(self, f"{self._get_account_label(account_id)} 검증 결과", "✅ 테스트 토큰 (검증 생략)")
            return

        self.main_window.status_bar.showMessage(f"{self._get_account_label(account_id)} 토큰 검증 중...")

        # QThread와 워커를 사용한 백그라운드 작업 실행
        self.worker_thread = QThread()
        self.validator = APIValidator()
        self.validator.moveToThread(self.worker_thread)

        # 시그널-슬롯 연결
        self.worker_thread.started.connect(lambda: self.validator.run_nai_validation(token))
        self.validator.nai_validation_finished.connect(
            lambda success, value, message, message_type: self._on_additional_account_validation_complete(
                account_id, success, value, message, message_type
            )
        )
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
        """메인 NAI 토큰 검증 완료"""
        self.nai_verify_btn.setEnabled(True)
        if success:
            self.token_manager.save_token('nai_token', value)
            self._save_timestamp('nai_token')

            # 🆕 라벨 업데이트 (토큰 프리뷰)
            token_preview = self._get_token_preview(value)
            label_text = f"메인 계정 ({token_preview}...):" if token_preview else "메인 계정:"
            self.main_account_label.setText(label_text)

        self._show_result_message('NAI', message, message_type)
        self.worker_thread.quit()

    def _on_additional_account_validation_complete(self, account_id: str, success: bool, value: str, message: str, message_type: str):
        """🆕 추가 계정 토큰 검증 완료"""
        if success:
            self.token_manager.save_token(account_id, value)

            # 메타데이터 업데이트
            for account in self.accounts_data['accounts']:
                if account['id'] == account_id:
                    account['last_verified'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    break
            self._save_accounts()

            # 🆕 라벨 업데이트 (토큰 프리뷰)
            if account_id in self.account_rows:
                label_base = self._get_account_label(account_id)
                token_preview = self._get_token_preview(value)
                label_text = f"{label_base} ({token_preview}...):" if token_preview else f"{label_base}:"
                self.account_rows[account_id]['label'].setText(label_text)

        label = self._get_account_label(account_id)
        self._show_result_message(label, message, message_type)
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
