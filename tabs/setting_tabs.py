from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QLineEdit, QFileDialog, QGroupBox,
    QScrollArea, QMessageBox, QComboBox
)
from PyQt6.QtCore import QObject, QThread, pyqtSignal, QTimer, Qt
from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import QTextEdit
from interfaces.base_tab_module import BaseTabModule
from ui.theme import DARK_STYLES, DARK_COLORS, get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size, get_scaling_manager
from ui.scaling_settings_dialog import ScalingSettingsDialog
import json
import os
import time
from pathlib import Path
from typing import Dict, Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class _WebSessionReadyWorker(QObject):
    """로컬 Web Session 서버가 실제로 응답할 때까지 대기한다."""

    ready = pyqtSignal(str, int)
    timeout = pyqtSignal(str, int)
    finished = pyqtSignal()

    def __init__(
        self,
        url: str,
        request_id: int,
        timeout_seconds: float = 20.0,
        poll_interval_seconds: float = 0.25,
    ):
        super().__init__()
        self.url = url
        self.request_id = request_id
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

    def run(self):
        deadline = time.monotonic() + self.timeout_seconds
        request = Request(self.url, headers={"Cache-Control": "no-cache"})

        try:
            while not self._stop_requested and time.monotonic() < deadline:
                try:
                    with urlopen(request, timeout=1.0) as response:
                        status_code = getattr(response, "status", response.getcode())
                        if status_code < 500:
                            self.ready.emit(self.url, self.request_id)
                            return
                except HTTPError as exc:
                    if exc.code < 500:
                        self.ready.emit(self.url, self.request_id)
                        return
                except URLError:
                    pass
                except Exception:
                    pass

                time.sleep(self.poll_interval_seconds)

            if not self._stop_requested:
                self.timeout.emit(self.url, self.request_id)
        finally:
            self.finished.emit()

class SettingsTabModule(BaseTabModule):
    """Settings 탭을 관리하는 모듈"""
    
    # 설정 변경 시그널들
    autocomplete_toggled = pyqtSignal(bool)
    save_directory_changed = pyqtSignal(str)
    module_visibility_changed = pyqtSignal(str, bool)  # module_id, visible
    tab_visibility_changed = pyqtSignal(str, bool)     # tab_id, visible
    
    def __init__(self):
        super().__init__()
        self.settings_widget = None
        self.settings_data = {}
        self.settings_file = "app_settings.json"
        self._browser_wait_thread = None
        self._browser_wait_worker = None
        self._browser_wait_request_id = 0
        
    def get_tab_title(self) -> str:
        return "⚙️ Settings"
        
    def get_tab_order(self) -> int:
        return 999  # 가장 오른쪽에 위치
        
    def get_tab_type(self) -> str:
        return 'core'  # 항상 로드되는 핵심 탭
        
    def can_close_tab(self) -> bool:
        return False  # 설정 탭은 닫을 수 없음

    def create_widget(self, parent: QWidget) -> QWidget:
        if self.settings_widget is None:
            self.settings_widget = SettingsWidget(self.app_context, self)
        return self.settings_widget
        
    def on_initialize(self):
        """탭 초기화 완료 시 설정 로드"""
        self.load_settings()
        if self.settings_widget:
            self.settings_widget.update_ui_from_settings()
            # CLI --web-session 플래그(환경변수 경유)가 있으면 설정값보다 우선해서 자동 시작
            cli_force = os.environ.get('NAIA_CLI_WEB_SESSION') == '1'
            if cli_force or self.get_setting('web_session.auto_start', False):
                QTimer.singleShot(5000, self._auto_start_web_session)

    def _auto_start_web_session(self):
        """자동 시작: Web Session 활성화 + 브라우저 오픈"""
        if not self.settings_widget:
            return

        port = self.settings_widget._get_remote_port()
        url = f"http://localhost:{port}"

        if not self.settings_widget.web_session_checkbox.isChecked():
            self.settings_widget.web_session_checkbox.setChecked(True)

        self._open_browser_when_ready(url)

    def _open_browser_when_ready(self, url: str):
        """서버가 실제로 응답한 뒤 기본 브라우저를 연다."""
        self._stop_browser_wait()
        self._browser_wait_request_id += 1
        request_id = self._browser_wait_request_id

        self._browser_wait_thread = QThread()
        self._browser_wait_worker = _WebSessionReadyWorker(url, request_id=request_id)
        self._browser_wait_worker.moveToThread(self._browser_wait_thread)

        self._browser_wait_thread.started.connect(self._browser_wait_worker.run)
        self._browser_wait_worker.ready.connect(self._on_browser_wait_ready)
        self._browser_wait_worker.timeout.connect(self._on_browser_wait_timeout)
        self._browser_wait_worker.finished.connect(self._browser_wait_thread.quit)
        self._browser_wait_thread.finished.connect(self._browser_wait_worker.deleteLater)
        self._browser_wait_thread.finished.connect(self._browser_wait_thread.deleteLater)
        self._browser_wait_thread.finished.connect(self._clear_browser_wait_refs)
        self._browser_wait_thread.start()

    def _stop_browser_wait(self):
        """진행 중인 브라우저 오픈 대기를 중단한다."""
        worker = self._browser_wait_worker
        thread = self._browser_wait_thread

        if worker:
            worker.stop()

        if thread:
            thread.quit()
            thread.wait(1500)

        self._browser_wait_worker = None
        self._browser_wait_thread = None

    def _clear_browser_wait_refs(self):
        self._browser_wait_worker = None
        self._browser_wait_thread = None

    def _on_browser_wait_ready(self, url: str, request_id: int):
        if request_id != self._browser_wait_request_id:
            return
        self._open_url_in_browser(url)

    def _on_browser_wait_timeout(self, url: str, request_id: int):
        if request_id != self._browser_wait_request_id:
            return

        print(f"🌐 Web Session readiness check timed out, opening browser anyway: {url}")
        self._open_url_in_browser(url)

    @staticmethod
    def _open_url_in_browser(url: str):
        import webbrowser
        webbrowser.open(url)

    def cleanup(self):
        """앱 종료 시 cloudflared 터널 및 remote server 정리"""
        self._stop_browser_wait()
        if self.settings_widget:
            self.settings_widget.cleanup_services()
    
    def load_settings(self):
        """설정 파일에서 설정 로드"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    self.settings_data = json.load(f)
            else:
                self.settings_data = self._get_default_settings()
        except Exception as e:
            print(f"Settings load failed: {e}")
            self.settings_data = self._get_default_settings()
    
    def save_settings(self):
        """설정을 파일에 저장"""
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings_data, f, indent=2, ensure_ascii=False)
            print("Settings saved successfully.")
        except Exception as e:
            print(f"Settings save failed: {e}")
    
    def _get_default_settings(self) -> Dict[str, Any]:
        """기본 설정값 반환"""
        return {
            "autocomplete": {
                "enabled": True
            },
            "save_directory": {
                "base_path": "./output"
            },
            "module_visibility": {},
            "tab_visibility": {},
            "web_session": {
                "auto_start": False,
                "port": 7243
            },
            "ui": {
                "theme": "dark",
                "auto_save": True
            }
        }
    
    def get_setting(self, key_path: str, default=None):
        """점 표기법으로 설정값 가져오기 (예: 'autocomplete.enabled')"""
        keys = key_path.split('.')
        value = self.settings_data
        try:
            for key in keys:
                if isinstance(value, dict):
                    value = value.get(key)
                    if value is None:
                        return default
                else:
                    return default
            return value
        except (KeyError, TypeError, AttributeError):
            return default
    
    def set_setting(self, key_path: str, value):
        """점 표기법으로 설정값 설정하기"""
        keys = key_path.split('.')
        data = self.settings_data
        for key in keys[:-1]:
            if key not in data:
                data[key] = {}
            data = data[key]
        data[keys[-1]] = value
        self.save_settings()


class SettingsWidget(QWidget):
    """Settings UI 위젯"""
    _cf_progress = pyqtSignal(str)
    _cf_success = pyqtSignal(str)
    _cf_error = pyqtSignal(str)

    def __init__(self, app_context, settings_module: SettingsTabModule):
        super().__init__()
        self.app_context = app_context
        self.settings_module = settings_module
        self._cf_progress.connect(self._on_cf_progress)
        self._cf_success.connect(self._set_cloudflared_url)
        self._cf_error.connect(self._on_cloudflared_error)
        self.init_ui()

        # ✅ ImageCrudController 이벤트 구독
        if app_context:
            app_context.subscribe("image_counter_changed", self._on_counter_changed)

            # 초기 카운터 값 표시
            if hasattr(app_context, 'image_crud_controller'):
                initial_counter = app_context.image_crud_controller.get_counter()
                self.counter_value_label.setText(str(initial_counter))
        
    def init_ui(self):
        """UI 초기화"""
        # 메인 위젯 배경을 검은색으로 설정
        self.setStyleSheet(f"""
            QWidget {{
                background-color: #333333;
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(16)
        
        # 스크롤 영역 생성
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)
        
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(20)
        
        # 각 설정 섹션 추가
        scroll_layout.addWidget(self._create_remote_section())
        scroll_layout.addWidget(self._create_autocomplete_section())
        scroll_layout.addWidget(self._create_save_directory_section())
        scroll_layout.addWidget(self._create_module_management_section())
        scroll_layout.addWidget(self._create_tab_management_section())
        scroll_layout.addWidget(self._create_ui_settings_section())
        
        scroll_layout.addStretch()
        
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)
        
        # 하단 버튼들
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        reset_btn = QPushButton("기본값으로 리셋")
        reset_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        reset_btn.clicked.connect(self.reset_to_defaults)
        
        export_btn = QPushButton("설정 내보내기")
        export_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        export_btn.clicked.connect(self.export_settings)
        
        import_btn = QPushButton("설정 가져오기")
        import_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        import_btn.clicked.connect(self.import_settings)
        
        button_layout.addWidget(reset_btn)
        button_layout.addWidget(export_btn)
        button_layout.addWidget(import_btn)
        
        main_layout.addLayout(button_layout)
    
    def _create_section_frame(self, title: str) -> tuple[QGroupBox, QVBoxLayout]:
        """섹션 프레임 생성 헬퍼"""
        group_box = QGroupBox(title)
        group_box.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                font-size: {get_scaled_font_size(14)}px;
                color: {DARK_COLORS['text_primary']};
                border: 2px solid {DARK_COLORS['border']};
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: {DARK_COLORS['bg_secondary']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                background-color: {DARK_COLORS['bg_secondary']};
            }}
        """)
        
        layout = QVBoxLayout(group_box)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 20, 16, 16)
        
        return group_box, layout
    
    def _create_remote_section(self) -> QWidget:
        """Remote API 서버 설정 섹션"""
        section, layout = self._create_section_frame("🌐 Web Session")

        # 한 줄: 체크박스 + URL(서버 시작 시) + Copy + Port + Port입력
        top_row = QHBoxLayout()
        top_row.setSpacing(get_scaled_size(8))
        self.web_session_checkbox = QCheckBox("Web Session 활성화")
        self.web_session_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.web_session_checkbox.toggled.connect(self._on_web_session_toggled)
        top_row.addWidget(self.web_session_checkbox)

        self.web_session_autostart = QCheckBox("자동 시작")
        self.web_session_autostart.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.web_session_autostart.setToolTip("프로그램 실행 시 Web Session 자동 활성화")
        self.web_session_autostart.toggled.connect(self._on_web_session_autostart_toggled)
        top_row.addWidget(self.web_session_autostart)

        self.remote_url_label = QLabel("")
        self.remote_url_label.setStyleSheet(f"font-size: {get_scaled_font_size(16)}px; background: transparent;")
        self.remote_url_label.setOpenExternalLinks(True)
        top_row.addWidget(self.remote_url_label)

        self.remote_copy_btn = QPushButton("Copy")
        self.remote_copy_btn.setStyleSheet(DARK_STYLES['compact_button'])
        self.remote_copy_btn.setFixedWidth(get_scaled_size(90))
        self.remote_copy_btn.clicked.connect(self._copy_remote_url)
        self.remote_copy_btn.setVisible(False)
        top_row.addWidget(self.remote_copy_btn)

        port_label = QLabel("Port:")
        port_label.setStyleSheet(f"font-size: {get_scaled_font_size(16)}px; color: {DARK_COLORS['text_primary']}; background: transparent;")
        top_row.addWidget(port_label)

        self.remote_port_edit = QLineEdit("7243")
        self.remote_port_edit.setFixedWidth(get_scaled_size(105))
        self.remote_port_edit.setStyleSheet(DARK_STYLES['compact_lineedit'])
        self.remote_port_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.remote_port_edit.setValidator(QIntValidator(1024, 65535))
        self.remote_port_edit.setProperty("autocomplete_ignore", True)
        top_row.addWidget(self.remote_port_edit)

        top_row.addStretch()
        layout.addLayout(top_row)

        # Cloudflared: 체크박스 + URL + Copy 한 줄
        cf_row = QHBoxLayout()
        cf_row.setSpacing(get_scaled_size(8))
        self.cloudflared_checkbox = QCheckBox("Cloudflared 연결")
        self.cloudflared_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.cloudflared_checkbox.setEnabled(False)
        self.cloudflared_checkbox.toggled.connect(self._on_cloudflared_toggled)
        cf_row.addWidget(self.cloudflared_checkbox)

        self.cloudflared_url_label = QLabel("")
        self.cloudflared_url_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['accent_blue']};
                font-size: {get_scaled_font_size(16)}px;
                padding: 2px 0;
                background: transparent;
            }}
        """)
        self.cloudflared_url_label.setOpenExternalLinks(True)
        self._cloudflared_tunnel_url = ""
        cf_row.addWidget(self.cloudflared_url_label)

        self.cloudflared_copy_btn = QPushButton("Copy")
        self.cloudflared_copy_btn.setStyleSheet(DARK_STYLES['compact_button'])
        self.cloudflared_copy_btn.setFixedWidth(get_scaled_size(90))
        self.cloudflared_copy_btn.clicked.connect(self._copy_cloudflared_url)
        self.cloudflared_copy_btn.setVisible(False)
        cf_row.addWidget(self.cloudflared_copy_btn)

        cf_row.addStretch()
        layout.addLayout(cf_row)

        # Shared Server Mode
        shared_row = QHBoxLayout()
        shared_row.setSpacing(get_scaled_size(8))
        self.shared_server_mode_checkbox = QCheckBox("Shared Server Mode")
        self.shared_server_mode_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.shared_server_mode_checkbox.setToolTip(
            "각 웹 클라이언트가 독립적인 P.Eng/파라미터를 가집니다.\n"
            "Cloudflared 터널 사용 시 NAI 모드가 차단됩니다."
        )
        self.shared_server_mode_checkbox.toggled.connect(self._on_shared_server_mode_toggled)
        shared_row.addWidget(self.shared_server_mode_checkbox)

        self.shared_copy_peng = QCheckBox("Copy P.Eng")
        self.shared_copy_peng.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.shared_copy_peng.setToolTip("새 세션에 데스크톱 P.Eng 설정을 복사")
        self.shared_copy_peng.setEnabled(False)
        self.shared_copy_peng.toggled.connect(lambda c: setattr(self.app_context, 'shared_copy_peng', c) if self.app_context else None)
        shared_row.addWidget(self.shared_copy_peng)

        self.shared_copy_cond = QCheckBox("Copy Cond")
        self.shared_copy_cond.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.shared_copy_cond.setToolTip("새 세션에 데스크톱 Conditional Prompt를 복사")
        self.shared_copy_cond.setEnabled(False)
        self.shared_copy_cond.toggled.connect(lambda c: setattr(self.app_context, 'shared_copy_cond', c) if self.app_context else None)
        shared_row.addWidget(self.shared_copy_cond)

        shared_row.addStretch()
        layout.addLayout(shared_row)

        return section

    def _get_remote_port(self) -> int:
        """포트 번호 반환"""
        try:
            return int(self.remote_port_edit.text().strip())
        except ValueError:
            return 7243

    def _copy_remote_url(self):
        """로컬 URL 클립보드 복사"""
        import pyperclip
        url = f"http://localhost:{self._get_remote_port()}"
        pyperclip.copy(url)

    def _copy_cloudflared_url(self):
        """Cloudflared URL 클립보드 복사"""
        import pyperclip
        url = self._cloudflared_tunnel_url
        if url:
            pyperclip.copy(url)

    def _on_web_session_autostart_toggled(self, checked: bool):
        """자동 시작 설정 저장"""
        self.settings_module.set_setting('web_session.auto_start', checked)
        self.settings_module.set_setting('web_session.port', self._get_remote_port())
        self.settings_module.save_settings()

    def _on_shared_server_mode_toggled(self, checked: bool):
        """Shared Server Mode 서버에 반영 (영속화 안 함 — 매 실행마다 수동 활성화)"""
        if checked and hasattr(self, 'app_context') and self.app_context:
            if self.app_context.get_api_mode() == "NAI":
                self.shared_server_mode_checkbox.setChecked(False)
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Shared Server Mode",
                    "NAI 모드에서는 Shared Server Mode를 활성화할 수 없습니다.\n"
                    "먼저 WEBUI 또는 COMFYUI 모드로 전환해주세요.")
                return
        # Shared Mode ON: 자동 시작 비활성화, Copy 옵션 활성화
        if checked:
            self.web_session_autostart.setChecked(False)
            self.web_session_autostart.setEnabled(False)
            self.shared_copy_peng.setEnabled(True)
            self.shared_copy_cond.setEnabled(True)
        else:
            self.web_session_autostart.setEnabled(True)
            self.shared_copy_peng.setEnabled(False)
            self.shared_copy_peng.setChecked(False)
            self.shared_copy_cond.setEnabled(False)
            self.shared_copy_cond.setChecked(False)
        # app_context에 저장 (bridge 생성 전/후 모두 대응)
        if hasattr(self, 'app_context') and self.app_context:
            self.app_context.shared_server_mode = checked
        # 실행 중인 서버에 즉시 반영 + 클라이언트에 broadcast
        from core.remote_api_server import _bridge_instance
        if _bridge_instance:
            _bridge_instance.shared_server_mode = checked
            _bridge_instance._broadcast_json({
                "type": "session",
                "session_id": "",
                "shared_server_mode": checked,
            })
            # Shared OFF 전환 + NAI 모드면 Anlas 즉시 재송신 (pill 이 다시 뜨도록)
            if not checked and hasattr(self, 'app_context') and self.app_context \
                    and self.app_context.get_api_mode() == "NAI":
                _bridge_instance._refresh_anlas_async()

    def _on_web_session_toggled(self, checked: bool):
        """Web Session 활성화/비활성화"""
        if checked:
            port = self._get_remote_port()
            try:
                from core.remote_api_server import start_remote_server
                self.web_session_checkbox.setEnabled(False)
                start_remote_server(self.app_context, port=port)
                self.web_session_checkbox.setEnabled(True)
                self.remote_port_edit.setEnabled(False)
                url = f"http://localhost:{port}"
                self.remote_url_label.setText(
                    f'<a href="{url}" style="color: {DARK_COLORS["success"]}; '
                    f'font-size: {get_scaled_font_size(16)}px;">{url}</a>'
                )
                self.remote_copy_btn.setVisible(True)
                self.cloudflared_checkbox.setEnabled(True)
            except Exception as e:
                self.web_session_checkbox.setEnabled(True)
                self.web_session_checkbox.setChecked(False)
                self.remote_url_label.setText(
                    f'<span style="color: {DARK_COLORS["error"]}; '
                    f'font-size: {get_scaled_font_size(16)}px;">서버 시작 실패: {e}</span>'
                )
        else:
            if self.cloudflared_checkbox.isChecked():
                self.cloudflared_checkbox.setChecked(False)
            self.cloudflared_checkbox.setEnabled(False)
            try:
                from core.remote_api_server import stop_remote_server
                stop_remote_server()
            except Exception:
                pass
            self.remote_port_edit.setEnabled(True)
            self.remote_url_label.setText("")
            self.remote_copy_btn.setVisible(False)

    def _on_cloudflared_toggled(self, checked: bool):
        """Cloudflared 터널 연결/해제"""
        # Remote bridge 의 Setup 게이트가 참조하는 명시 플래그 (위젯 탐색 대체).
        if self.app_context:
            self.app_context.cloudflared_active = bool(checked)
        if checked:
            self._start_cloudflared()
        else:
            self._stop_cloudflared()

    def _on_cf_progress(self, msg: str):
        """Cloudflared 진행 상태 표시 (UI 스레드)"""
        self.cloudflared_url_label.setText(msg)

    def _start_cloudflared(self):
        """cloudflared 터널 시작"""
        self.cloudflared_url_label.setText("Cloudflared 연결 중...")
        import threading
        threading.Thread(target=self._connect_cloudflared, daemon=True).start()

    def _connect_cloudflared(self):
        """별도 스레드에서 cloudflared 연결"""
        try:
            from utils.cloudflared import start_tunnel
            port = self._get_remote_port()
            info = start_tunnel(port, on_progress=self._cf_progress.emit)
            self._cf_success.emit(info.tunnel_url)
        except Exception as e:
            self._cf_error.emit(str(e))

    def _set_cloudflared_url(self, url: str):
        """Cloudflared URL 표시"""
        self._cloudflared_tunnel_url = url
        self.cloudflared_url_label.setText(
            f'<a href="{url}" style="color: {DARK_COLORS["accent_blue"]}; '
            f'font-size: {get_scaled_font_size(16)}px; font-weight: bold;">{url}</a>'
        )
        self.cloudflared_copy_btn.setVisible(True)
        print(f"🌐 Cloudflared tunnel: {url}")

    def _on_cloudflared_error(self, error: str):
        """Cloudflared 연결 실패"""
        self.cloudflared_checkbox.setChecked(False)
        self.cloudflared_url_label.setText(
            f'<span style="color: {DARK_COLORS["error"]}; '
            f'font-size: {get_scaled_font_size(16)}px;">Cloudflared 실패: {error}</span>'
        )

    def _stop_cloudflared(self):
        """cloudflared 터널 종료"""
        try:
            from utils.cloudflared import stop_tunnel
            stop_tunnel(self._get_remote_port())
        except Exception:
            pass
        self._cloudflared_tunnel_url = ""
        self.cloudflared_url_label.setText("")
        self.cloudflared_copy_btn.setVisible(False)
        print("🌐 Cloudflared tunnel stopped")

    def cleanup_services(self):
        """앱 종료 시 서비스 정리"""
        if self.cloudflared_checkbox.isChecked():
            self._stop_cloudflared()
        if self.web_session_checkbox.isChecked():
            try:
                from core.remote_api_server import stop_remote_server
                stop_remote_server()
            except Exception:
                pass

    def _create_autocomplete_section(self) -> QWidget:
        """자동완성 설정 섹션"""
        section, layout = self._create_section_frame("🔍 자동완성 설정")
        
        # 자동완성 활성화
        self.autocomplete_checkbox = QCheckBox("자동완성 기능 활성화")
        self.autocomplete_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.autocomplete_checkbox.toggled.connect(self._on_autocomplete_toggled)
        layout.addWidget(self.autocomplete_checkbox)
        
        return section
    
    def _create_save_directory_section(self) -> QWidget:
        """저장 디렉토리 설정 섹션"""
        section, layout = self._create_section_frame("💾 저장 디렉토리 설정")
        
        # 기본 저장 경로
        path_layout = QHBoxLayout()
        path_label = QLabel("기본 저장 경로:")
        path_label.setStyleSheet(DARK_STYLES['label_style'])
        self.save_path_edit = QLineEdit()
        self.save_path_edit.setStyleSheet(DARK_STYLES['compact_lineedit'])
        self.save_path_edit.textChanged.connect(self._on_save_path_changed)
        
        browse_btn = QPushButton("찾아보기")
        browse_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        browse_btn.clicked.connect(self._browse_save_path)
        
        path_layout.addWidget(path_label)
        path_layout.addWidget(self.save_path_edit, 1)
        path_layout.addWidget(browse_btn)
        layout.addLayout(path_layout)

        # 🆕 타임스탬프 폴더 사용 여부
        self.use_timestamp_folder_checkbox = QCheckBox("날짜_시간 폴더 사용 (예: 20250109_143520/)")
        self.use_timestamp_folder_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.use_timestamp_folder_checkbox.setChecked(True)  # 기본값: 사용
        self.use_timestamp_folder_checkbox.toggled.connect(self._on_use_timestamp_folder_changed)
        layout.addWidget(self.use_timestamp_folder_checkbox)

        # ✅ 이미지 저장 카운터 표시
        counter_layout = QHBoxLayout()
        counter_label = QLabel("현재 저장 카운터:")
        counter_label.setStyleSheet(DARK_STYLES['label_style'])
        self.counter_value_label = QLabel("1")
        self.counter_value_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['success']};
                font-weight: bold;
                font-size: {get_scaled_font_size(16)}px;
                padding: 4px 8px;
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)

        reset_counter_btn = QPushButton("카운터 초기화")
        reset_counter_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        reset_counter_btn.clicked.connect(self._reset_image_counter)

        counter_layout.addWidget(counter_label)
        counter_layout.addWidget(self.counter_value_label)
        #counter_layout.addWidget(reset_counter_btn)
        counter_layout.addStretch()
        layout.addLayout(counter_layout)

        # 🆕 파일명 형식 선택
        filename_format_layout = QHBoxLayout()
        filename_format_label = QLabel("파일명 형식:")
        filename_format_label.setStyleSheet(DARK_STYLES['label_style'])

        self.filename_format_combo = QComboBox()
        self.filename_format_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.filename_format_combo.addItem("번호만 (00001.png)", "number_only")
        self.filename_format_combo.addItem("시간_번호 (143052_00001.png)", "time_number")
        self.filename_format_combo.addItem("날짜_시간 (20250108_143052.png)", "datetime")
        self.filename_format_combo.addItem("프롬프트 (prompt.png)", "prompt")
        self.filename_format_combo.addItem("와일드카드 (wildcard.png)", "wildcard")
        self.filename_format_combo.currentIndexChanged.connect(self._on_filename_format_changed)

        # 설명 레이블
        filename_format_desc = QLabel("※ 중복 방지: 번호만/시간_번호는 카운터 증가, 날짜_시간/프롬프트는 (1), (2) 추가")
        filename_format_desc.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(11)}px;
                font-style: italic;
            }}
        """)

        filename_format_layout.addWidget(filename_format_label)
        filename_format_layout.addWidget(self.filename_format_combo)
        filename_format_layout.addStretch()
        layout.addLayout(filename_format_layout)
        layout.addWidget(filename_format_desc)
        filename_format_desc.setVisible(False)

        # 🆕 분류 방법 선택
        classification_layout = QHBoxLayout()
        classification_label = QLabel("분류 방법:")
        classification_label.setStyleSheet(DARK_STYLES['label_style'])

        self.classification_method_combo = QComboBox()
        self.classification_method_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.classification_method_combo.addItem("분류 없음", "none")
        self.classification_method_combo.addItem("프롬프트 인식", "prompt_recognition")
        self.classification_method_combo.currentIndexChanged.connect(self._on_classification_method_changed)

        # 설명 레이블
        classification_desc = QLabel("※ 분류 시 하위 폴더에 자동 정리됩니다 (예: output/20250108_143052/character/)")
        classification_desc.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(11)}px;
                font-style: italic;
            }}
        """)

        classification_layout.addWidget(classification_label)
        classification_layout.addWidget(self.classification_method_combo)
        classification_layout.addStretch()
        layout.addLayout(classification_layout)
        layout.addWidget(classification_desc)
        classification_desc.setVisible(False)

        # 🆕 프롬프트 인식 분류 규칙 입력 필드
        self.classification_rules_label = QLabel("분류 규칙:")
        self.classification_rules_label.setStyleSheet(DARK_STYLES['label_style'])

        self.classification_rules_textedit = QTextEdit()
        self.classification_rules_textedit.setFixedHeight(120)
        self.classification_rules_textedit.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.classification_rules_textedit.setPlaceholderText(
            "예시:\n"
            "*1girl,\n"
            "(*solo&*1girl),\n"
            "(landscape|scenery),\n"
            "nsfw\n\n"
            "규칙:\n"
            "• *tag: 정확 일치 (퍼펙트 매칭)\n"
            "• &: AND 연산자\n"
            "• |: OR 연산자\n"
            "• 쉼표로 구분, 작성 순서대로 우선순위"
        )
        self.classification_rules_textedit.textChanged.connect(self._on_classification_rules_changed)

        # 설명 레이블
        rules_desc = QLabel("※ 위에서 아래 순서로 조건을 확인하며, 첫 번째 일치하는 조건의 폴더로 분류됩니다.")
        rules_desc.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(11)}px;
                font-style: italic;
            }}
        """)

        layout.addWidget(self.classification_rules_label)
        layout.addWidget(self.classification_rules_textedit)
        layout.addWidget(rules_desc)

        # 초기에는 숨김 (분류 없음이 기본값)
        self.classification_rules_label.setVisible(False)
        self.classification_rules_textedit.setVisible(False)
        rules_desc.setVisible(False)

        # 🆕 2차 분류 활성화 체크박스
        self.secondary_classification_checkbox = QCheckBox("2차 분류 활성화")
        self.secondary_classification_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.secondary_classification_checkbox.toggled.connect(self._on_secondary_classification_toggled)
        layout.addWidget(self.secondary_classification_checkbox)
        self.secondary_classification_checkbox.setVisible(False)

        # 🆕 2차 분류 방법 선택
        secondary_classification_layout = QHBoxLayout()
        secondary_classification_label = QLabel("2차 분류 방법:")
        secondary_classification_label.setStyleSheet(DARK_STYLES['label_style'])

        self.secondary_classification_method_combo = QComboBox()
        self.secondary_classification_method_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.secondary_classification_method_combo.addItem("분류 없음", "none")
        self.secondary_classification_method_combo.addItem("프롬프트 인식", "prompt_recognition")
        self.secondary_classification_method_combo.currentIndexChanged.connect(self._on_secondary_classification_method_changed)

        secondary_classification_layout.addWidget(secondary_classification_label)
        secondary_classification_layout.addWidget(self.secondary_classification_method_combo)
        secondary_classification_layout.addStretch()
        layout.addLayout(secondary_classification_layout)

        self.secondary_classification_label = secondary_classification_label
        self.secondary_classification_label.setVisible(False)
        self.secondary_classification_method_combo.setVisible(False)

        # 🆕 규칙 선택 콤보박스
        rule_selection_layout = QHBoxLayout()
        rule_selection_label = QLabel("규칙 선택:")
        rule_selection_label.setStyleSheet(DARK_STYLES['label_style'])

        self.rule_selection_combo = QComboBox()
        self.rule_selection_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.rule_selection_combo.currentIndexChanged.connect(self._on_rule_selection_changed)

        rule_selection_layout.addWidget(rule_selection_label)
        rule_selection_layout.addWidget(self.rule_selection_combo)
        rule_selection_layout.addStretch()
        layout.addLayout(rule_selection_layout)

        self.rule_selection_label = rule_selection_label
        self.rule_selection_label.setVisible(False)
        self.rule_selection_combo.setVisible(False)

        # 🆕 2차 분류 규칙 입력 필드 (동적으로 표시됨)
        self.secondary_rules_label = QLabel("")
        self.secondary_rules_label.setStyleSheet(DARK_STYLES['label_style'])

        self.secondary_rules_textedit = QTextEdit()
        self.secondary_rules_textedit.setFixedHeight(120)
        self.secondary_rules_textedit.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.secondary_rules_textedit.setPlaceholderText(
            "예시:\n"
            "*standing,\n"
            "(*sitting&*chair),\n"
            "lying\n\n"
            "2차 분류 규칙을 입력하세요."
        )
        self.secondary_rules_textedit.textChanged.connect(self._on_secondary_rules_changed)

        layout.addWidget(self.secondary_rules_label)
        layout.addWidget(self.secondary_rules_textedit)

        self.secondary_rules_label.setVisible(False)
        self.secondary_rules_textedit.setVisible(False)

        # 🆕 2차 분류 규칙 저장소 (규칙별로 저장)
        self.secondary_classification_rules = {}  # {rule_name: rules_text}
        self.classification_rules_desc = rules_desc  # 나중에 접근하기 위해 저장

        # TODO: 자동 분류 기능 구현 예정
        # self.classification_checkbox = QCheckBox("자동 분류 활성화 (모드/날짜별 하위폴더)")
        # self.classification_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        # self.classification_checkbox.toggled.connect(self._on_classification_toggled)
        # layout.addWidget(self.classification_checkbox)

        # TODO: 하위폴더 형식 기능 구현 예정
        # subfolder_layout = QHBoxLayout()
        # subfolder_label = QLabel("하위폴더 형식:")
        # subfolder_label.setStyleSheet(DARK_STYLES['label_style'])
        # self.subfolder_edit = QLineEdit()
        # self.subfolder_edit.setStyleSheet(DARK_STYLES['compact_lineedit'])
        # self.subfolder_edit.setPlaceholderText("{mode}/{date} 또는 {mode}/{timestamp}")
        # self.subfolder_edit.textChanged.connect(self._on_subfolder_format_changed)
        # subfolder_layout.addWidget(subfolder_label)
        # subfolder_layout.addWidget(self.subfolder_edit)
        # layout.addLayout(subfolder_layout)

        return section
    
    def _create_module_management_section(self) -> QWidget:
        """모듈 관리 섹션"""
        section, layout = self._create_section_frame("🧩 모듈 가시성 관리")
        
        # 모듈 목록 컨테이너 (일반 박스)
        self.module_container = QWidget()
        self.module_container.setStyleSheet(f"""
            QWidget {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 8px;
            }}
        """)
        self.module_layout = QVBoxLayout(self.module_container)
        self.module_layout.setSpacing(4)
        self.module_layout.setContentsMargins(8, 8, 8, 8)
        
        layout.addWidget(self.module_container)
        
        # 새로고침 버튼
        refresh_modules_btn = QPushButton("모듈 목록 새로고침")
        refresh_modules_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        refresh_modules_btn.clicked.connect(self._refresh_module_list)
        layout.addWidget(refresh_modules_btn)
        
        return section
    
    def _create_tab_management_section(self) -> QWidget:
        """탭 관리 섹션"""
        section, layout = self._create_section_frame("📑 탭 가시성 관리")
        
        # 탭 목록 컨테이너 (일반 박스)
        self.tab_container = QWidget()
        self.tab_container.setStyleSheet(f"""
            QWidget {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 8px;
            }}
        """)
        self.tab_layout = QVBoxLayout(self.tab_container)
        self.tab_layout.setSpacing(4)
        self.tab_layout.setContentsMargins(8, 8, 8, 8)
        
        layout.addWidget(self.tab_container)
        
        # 새로고침 버튼
        refresh_tabs_btn = QPushButton("탭 목록 새로고침")
        refresh_tabs_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        refresh_tabs_btn.clicked.connect(self._refresh_tab_list)
        layout.addWidget(refresh_tabs_btn)
        
        return section
    
    def _create_ui_settings_section(self) -> QWidget:
        """UI 설정 섹션"""
        section, layout = self._create_section_frame("🎨 UI 설정")
        
        # UI 스케일링 설정
        scaling_layout = QHBoxLayout()
        
        # 현재 스케일링 정보 표시
        scaling_manager = get_scaling_manager()
        current_scale = scaling_manager.get_scale_factor()
        auto_scaling = scaling_manager.is_auto_scaling_enabled()
        user_scale = scaling_manager.get_user_scale_factor()
        
        if auto_scaling:
            scale_text = f"자동 스케일링 ({current_scale:.1f}x)"
        else:
            scale_text = f"수동 스케일링 ({user_scale:.1f}x)"
            
        self.ui_scale_label = QLabel(f"UI 크기: {scale_text}")
        dynamic_styles = get_dynamic_styles()
        self.ui_scale_label.setStyleSheet(dynamic_styles['label_style'])
        
        # UI 크기 설정 버튼
        ui_scale_btn = QPushButton("UI 크기 설정")
        ui_scale_btn.setStyleSheet(dynamic_styles['secondary_button'])
        ui_scale_btn.clicked.connect(self._open_scaling_settings)
        ui_scale_btn.setToolTip("화면 해상도에 맞는 UI 크기를 설정합니다")
        
        scaling_layout.addWidget(self.ui_scale_label)
        scaling_layout.addStretch()
        scaling_layout.addWidget(ui_scale_btn)
        layout.addLayout(scaling_layout)
        
        # 자동 저장
        self.auto_save_checkbox = QCheckBox("설정 자동 저장")
        self.auto_save_checkbox.setStyleSheet(dynamic_styles['dark_checkbox'])
        self.auto_save_checkbox.toggled.connect(self._on_auto_save_toggled)
        layout.addWidget(self.auto_save_checkbox)
        
        return section
    
    # =========================
    # 이벤트 핸들러들
    # =========================
    
    def _on_autocomplete_toggled(self, checked: bool):
        """자동완성 토글"""
        self.settings_module.set_setting('autocomplete.enabled', checked)
        self.settings_module.autocomplete_toggled.emit(checked)
        
        # 실제 자동완성 시스템에 반영
        if hasattr(self.app_context, 'main_window'):
            main_window = self.app_context.main_window
            if hasattr(main_window, 'autocomplete_manager'):
                if checked:
                    main_window.autocomplete_manager.enable()
                else:
                    main_window.autocomplete_manager.disable()
    
    # TODO: 자동완성 세부 설정 기능들 (제거됨)
    # def _on_min_chars_changed(self, value: int):
    #     """최소 문자수 변경"""
    #     self.settings_module.set_setting('autocomplete.min_chars', value)
    
    # def _on_max_suggestions_changed(self, value: int):
    #     """최대 제안수 변경"""
    #     self.settings_module.set_setting('autocomplete.max_suggestions', value)
    
    def _on_save_path_changed(self, text: str):
        """저장 경로 변경"""
        self.settings_module.set_setting('save_directory.base_path', text)
        self.settings_module.save_directory_changed.emit(text)
        
        # AppContext를 통해 저장 경로 변경
        if self.app_context and hasattr(self.app_context, 'set_base_save_directory'):
            self.app_context.set_base_save_directory(text)
    
    def _browse_save_path(self):
        """저장 경로 찾아보기"""
        current_path = self.settings_module.get_setting('save_directory.base_path', './output')
        new_path = QFileDialog.getExistingDirectory(
            self, "저장 디렉토리 선택", current_path
        )
        if new_path:
            self.save_path_edit.setText(new_path)

    def _on_use_timestamp_folder_changed(self, checked: bool):
        """타임스탬프 폴더 사용 여부 변경"""
        if not hasattr(self.app_context, 'image_crud_controller'):
            return

        self.app_context.image_crud_controller.set_use_timestamp_folder(checked)
        print(f"✅ 타임스탬프 폴더 사용: {checked}")

    def _on_secondary_classification_toggled(self, checked: bool):
        """2차 분류 활성화 토글"""
        # 2차 분류 관련 UI 표시/숨김
        self.secondary_classification_label.setVisible(checked)
        self.secondary_classification_method_combo.setVisible(checked)

        if checked and self.secondary_classification_method_combo.currentData() == "prompt_recognition":
            self._update_rule_selection_combo()
            self.rule_selection_label.setVisible(True)
            self.rule_selection_combo.setVisible(True)
            self.secondary_rules_label.setVisible(True)
            self.secondary_rules_textedit.setVisible(True)
        else:
            self.rule_selection_label.setVisible(False)
            self.rule_selection_combo.setVisible(False)
            self.secondary_rules_label.setVisible(False)
            self.secondary_rules_textedit.setVisible(False)

        # ImageCrudController에 반영
        self._sync_secondary_settings_to_controller()

    def _on_secondary_classification_method_changed(self, index: int):
        """2차 분류 방법 변경"""
        method = self.secondary_classification_method_combo.currentData()

        if method == "prompt_recognition":
            # 규칙 선택 콤보박스 업데이트
            self._update_rule_selection_combo()
            self.rule_selection_label.setVisible(True)
            self.rule_selection_combo.setVisible(True)
            self.secondary_rules_label.setVisible(True)
            self.secondary_rules_textedit.setVisible(True)
        else:
            self.rule_selection_label.setVisible(False)
            self.rule_selection_combo.setVisible(False)
            self.secondary_rules_label.setVisible(False)
            self.secondary_rules_textedit.setVisible(False)

        # ImageCrudController에 반영
        self._sync_secondary_settings_to_controller()

    def _update_rule_selection_combo(self):
        """1차 분류 규칙에서 콤보박스 항목 업데이트"""
        # 기존 항목 제거
        self.rule_selection_combo.blockSignals(True)
        self.rule_selection_combo.clear()

        # 1차 분류 규칙 텍스트 가져오기
        rules_text = self.classification_rules_textedit.toPlainText().strip()

        if rules_text:
            # 쉼표로 분리하여 각 규칙 추출 (ImageCrudController와 동일한 방식)
            rules = [rule.strip() for rule in rules_text.split(',') if rule.strip()]

            for rule in rules:
                # 각 규칙을 폴더명으로 변환 (ImageCrudController._condition_to_folder_name과 동일한 로직)
                folder_name = self._rule_to_folder_name(rule)
                # 콤보박스에 추가 (표시: 원본 규칙, 데이터: 폴더명)
                self.rule_selection_combo.addItem(f"{folder_name} ({rule})", folder_name)

        self.rule_selection_combo.blockSignals(False)

        # 첫 번째 규칙 선택 시 해당 규칙 로드
        if self.rule_selection_combo.count() > 0:
            self.rule_selection_combo.setCurrentIndex(0)
            self._on_rule_selection_changed(0)

    def _rule_to_folder_name(self, rule: str) -> str:
        """규칙을 폴더명으로 변환 (ImageCrudController._condition_to_folder_name과 동일)"""
        import re

        folder_name = rule.strip()

        # 괄호 제거
        folder_name = folder_name.replace('(', '').replace(')', '')

        # 논리 연산자 치환
        folder_name = folder_name.replace('&', '_and_')
        folder_name = folder_name.replace('|', '_or_')

        # * 제거 (퍼펙트 매칭 표시)
        folder_name = folder_name.replace('*', '')

        # 공백 → 언더스코어
        folder_name = folder_name.replace(' ', '_')

        # 파일시스템 안전 문자만 허용 (영문, 숫자, _, -, .)
        folder_name = re.sub(r'[^\w\-.]', '_', folder_name)

        # 연속된 언더스코어 제거
        folder_name = re.sub(r'_+', '_', folder_name)

        # 앞뒤 언더스코어 제거
        folder_name = folder_name.strip('_')

        return folder_name if folder_name else "unknown"

    def _on_rule_selection_changed(self, index: int):
        """규칙 선택 변경 - 해당 규칙의 2차 분류 규칙 로드"""
        if index < 0:
            return

        rule_name = self.rule_selection_combo.currentData()
        if not rule_name:
            return

        # 레이블 업데이트
        self.secondary_rules_label.setText(f"{rule_name}에 대한 2차 분류 규칙:")

        # 저장된 2차 분류 규칙 로드
        saved_rules = self.secondary_classification_rules.get(rule_name, "")

        self.secondary_rules_textedit.blockSignals(True)
        self.secondary_rules_textedit.setPlainText(saved_rules)
        self.secondary_rules_textedit.blockSignals(False)

    def _on_secondary_rules_changed(self):
        """2차 분류 규칙 텍스트 변경 - 저장"""
        rule_name = self.rule_selection_combo.currentData()
        if not rule_name:
            return

        # 현재 입력된 규칙 저장
        rules_text = self.secondary_rules_textedit.toPlainText()
        self.secondary_classification_rules[rule_name] = rules_text

        print(f"✅ 2차 분류 규칙 저장: {rule_name} → {len(rules_text)} chars")

        # ImageCrudController에 반영
        if hasattr(self.app_context, 'image_crud_controller'):
            self.app_context.image_crud_controller.set_secondary_classification_rules(self.secondary_classification_rules)

    def _sync_secondary_settings_to_controller(self):
        """2차 분류 설정을 ImageCrudController에 동기화"""
        if not hasattr(self.app_context, 'image_crud_controller'):
            return

        # 2차 분류 활성화 여부
        enabled = self.secondary_classification_checkbox.isChecked()
        self.app_context.image_crud_controller.set_secondary_classification_enabled(enabled)

        # 2차 분류 방법
        method = self.secondary_classification_method_combo.currentData()
        self.app_context.image_crud_controller.set_secondary_classification_method(method)

        # 2차 분류 규칙
        self.app_context.image_crud_controller.set_secondary_classification_rules(self.secondary_classification_rules)

    # TODO: 자동 분류 기능 구현 예정
    # def _on_classification_toggled(self, checked: bool):
    #     """자동 분류 토글"""
    #     self.settings_module.set_setting('save_directory.classification_enabled', checked)
    
    # def _on_subfolder_format_changed(self, text: str):
    #     """하위폴더 형식 변경"""
    #     self.settings_module.set_setting('save_directory.subfolder_format', text)
    
    # TODO: 폰트 크기 변경 기능 구현 예정
    # def _on_font_size_changed(self, value: int):
    #     """폰트 크기 변경"""
    #     self.settings_module.set_setting('ui.font_size', value)
    #     # 실제 UI에 적용 (전역 폰트 변경 로직 필요)
    
    def _on_auto_save_toggled(self, checked: bool):
        """자동 저장 토글"""
        self.settings_module.set_setting('ui.auto_save', checked)
    
    def _refresh_module_list(self):
        """모듈 목록 새로고침"""
        # 기존 체크박스들 제거
        for i in reversed(range(self.module_layout.count())):
            child = self.module_layout.itemAt(i).widget()
            if child:
                child.setParent(None)
        
        if (hasattr(self.app_context, 'middle_section_controller') and 
            self.app_context.middle_section_controller):
            
            controller = self.app_context.middle_section_controller
            for module in controller.module_instances:
                checkbox = QCheckBox(module.get_title())
                checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
                
                # 현재 가시성 상태 확인
                module_id = module.__class__.__name__
                is_visible = self.settings_module.get_setting(f'module_visibility.{module_id}', True)
                checkbox.setChecked(is_visible)
                
                # 체크박스 토글 시 이벤트 연결
                checkbox.toggled.connect(
                    lambda checked, mid=module_id: self._on_module_visibility_changed(mid, checked)
                )
                
                self.module_layout.addWidget(checkbox)
    
    def _refresh_tab_list(self):
        """탭 목록 새로고침"""
        # 기존 체크박스들 제거
        for i in reversed(range(self.tab_layout.count())):
            child = self.tab_layout.itemAt(i).widget()
            if child:
                child.setParent(None)
        
        # 숨길 수 있는 탭들만 허용
        hideable_tabs = ['BrowserTabModule', 'PNGInfoTabModule', 'HookerTabModule', 'StorytellerTabModule', 'AssetsTabModule']
        
        # RightView의 TabController에서 탭 정보 가져오기
        if (hasattr(self.app_context, 'main_window') and 
            hasattr(self.app_context.main_window, 'image_window') and
            hasattr(self.app_context.main_window.image_window, 'tab_controller')):
            
            tab_controller = self.app_context.main_window.image_window.tab_controller
            for tab_id, instance in tab_controller.module_instances.items():
                # 숨길 수 있는 탭인지 확인
                if instance.__class__.__name__ in hideable_tabs:
                    checkbox = QCheckBox(instance.get_tab_title())
                    checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
                    
                    # 현재 가시성 상태 확인
                    is_visible = self.settings_module.get_setting(f'tab_visibility.{tab_id}', True)
                    checkbox.setChecked(is_visible)
                    
                    # 체크박스 토글 시 이벤트 연결
                    checkbox.toggled.connect(
                        lambda checked, tid=tab_id: self._on_tab_visibility_changed(tid, checked)
                    )
                    
                    self.tab_layout.addWidget(checkbox)
    
    def _on_module_visibility_changed(self, module_id: str, visible: bool):
        """모듈 가시성 변경"""
        self.settings_module.set_setting(f'module_visibility.{module_id}', visible)
        self.settings_module.module_visibility_changed.emit(module_id, visible)
        
        # 실제 모듈 가시성 적용
        if (hasattr(self.app_context, 'middle_section_controller') and 
            self.app_context.middle_section_controller):
            
            controller = self.app_context.middle_section_controller
            # module_instances에서 해당 모듈 찾기
            for module in controller.module_instances:
                if module.__class__.__name__ == module_id:
                    module_title = module.get_title()
                    # module_boxes에서 해당 박스 찾아서 가시성 조절
                    if module_title in controller.module_boxes:
                        box = controller.module_boxes[module_title]
                        box.setVisible(visible)
                        print(f"Module '{module_title}' visibility changed to {visible}")
                    break
    
    def _on_tab_visibility_changed(self, tab_id: str, visible: bool):
        """탭 가시성 변경"""
        self.settings_module.set_setting(f'tab_visibility.{tab_id}', visible)
        self.settings_module.tab_visibility_changed.emit(tab_id, visible)
        
        # 실제 탭 가시성 적용 (탭 숨기기/표시하기)
        if (hasattr(self.app_context, 'main_window') and 
            hasattr(self.app_context.main_window, 'image_window') and
            hasattr(self.app_context.main_window.image_window, 'tab_controller')):
            
            tab_controller = self.app_context.main_window.image_window.tab_controller
            if tab_id in tab_controller.tab_index_map:
                tab_index = tab_controller.tab_index_map[tab_id]
                tab_controller.tab_widget.setTabVisible(tab_index, visible)
    
    def update_ui_from_settings(self):
        """저장된 설정으로 UI 업데이트"""
        # Web Session 설정
        self.remote_port_edit.setText(
            str(self.settings_module.get_setting('web_session.port', 7243))
        )
        self.web_session_autostart.setChecked(
            self.settings_module.get_setting('web_session.auto_start', False)
        )
        # 자동완성 설정
        self.autocomplete_checkbox.setChecked(
            self.settings_module.get_setting('autocomplete.enabled', True)
        )

        # 저장 디렉토리 설정
        self.save_path_edit.setText(
            self.settings_module.get_setting('save_directory.base_path', './output')
        )

        # 🆕 타임스탬프 폴더 사용 여부 설정
        if hasattr(self, 'use_timestamp_folder_checkbox') and hasattr(self.app_context, 'image_crud_controller'):
            current_use_timestamp = self.app_context.image_crud_controller.get_use_timestamp_folder()
            self.use_timestamp_folder_checkbox.setChecked(current_use_timestamp)

        # 🆕 파일명 형식 설정
        if hasattr(self, 'filename_format_combo') and hasattr(self.app_context, 'image_crud_controller'):
            current_format = self.app_context.image_crud_controller.get_filename_format()
            # 콤보박스에서 해당 형식 찾기
            for i in range(self.filename_format_combo.count()):
                if self.filename_format_combo.itemData(i) == current_format:
                    self.filename_format_combo.setCurrentIndex(i)
                    break

        # 🆕 분류 방법 설정
        if hasattr(self, 'classification_method_combo') and hasattr(self.app_context, 'image_crud_controller'):
            current_method = self.app_context.image_crud_controller.get_classification_method()
            # 콤보박스에서 해당 방법 찾기
            for i in range(self.classification_method_combo.count()):
                if self.classification_method_combo.itemData(i) == current_method:
                    self.classification_method_combo.setCurrentIndex(i)
                    break

            # 🆕 분류 규칙 설정
            if hasattr(self, 'classification_rules_textedit'):
                current_rules = self.app_context.image_crud_controller.get_classification_rules()
                self.classification_rules_textedit.setPlainText(current_rules)

                # 프롬프트 인식 모드일 때만 규칙 필드 표시
                is_prompt_recognition = (current_method == "prompt_recognition")
                self.classification_rules_label.setVisible(is_prompt_recognition)
                self.classification_rules_textedit.setVisible(is_prompt_recognition)
                self.classification_rules_desc.setVisible(is_prompt_recognition)

        # UI 설정
        self.auto_save_checkbox.setChecked(
            self.settings_module.get_setting('ui.auto_save', True)
        )

        # 모듈 및 탭 목록 새로고침
        QTimer.singleShot(100, self._refresh_module_list)
        QTimer.singleShot(100, self._refresh_tab_list)

        # 🆕 저장된 가시성 설정 적용 (프로그램 시작 시)
        QTimer.singleShot(200, self._apply_saved_module_visibility)
        QTimer.singleShot(250, self._apply_saved_tab_visibility)

        # 🆕 저장된 자동완성 설정 적용 (AutoCompleteManager 초기화 후)
        QTimer.singleShot(1500, self._apply_saved_autocomplete_settings)

    def _on_counter_changed(self, data: dict):
        """
        [신규] ImageCrudController 카운터 변경 이벤트 핸들러

        Parameters:
            data (dict): {"new_counter": int}
        """
        new_counter = data.get("new_counter", 1)
        self.counter_value_label.setText(str(new_counter))
        print(f"✅ Settings 탭: 카운터 업데이트 → {new_counter}")

    def _on_filename_format_changed(self, index: int):
        """
        [신규] 파일명 형식 변경 핸들러

        Parameters:
            index (int): 콤보박스 인덱스
        """
        if not hasattr(self.app_context, 'image_crud_controller'):
            return

        # 선택된 형식 가져오기
        selected_format = self.filename_format_combo.currentData()

        # ImageCrudController에 반영
        try:
            self.app_context.image_crud_controller.set_filename_format(selected_format)
            print(f"✅ 파일명 형식 변경: {selected_format}")
        except Exception as e:
            QMessageBox.warning(self, "오류", f"파일명 형식 변경 실패: {e}")

    def _on_classification_method_changed(self, index: int):
        """
        [신규] 분류 방법 변경 핸들러

        Parameters:
            index (int): 콤보박스 인덱스
        """
        if not hasattr(self.app_context, 'image_crud_controller'):
            return

        # 선택된 방법 가져오기
        selected_method = self.classification_method_combo.currentData()

        # 🆕 프롬프트 인식 선택 시 규칙 입력 필드 표시
        is_prompt_recognition = (selected_method == "prompt_recognition")
        if hasattr(self, 'classification_rules_label'):
            self.classification_rules_label.setVisible(is_prompt_recognition)
            self.classification_rules_textedit.setVisible(is_prompt_recognition)
            self.classification_rules_desc.setVisible(is_prompt_recognition)

        # 🆕 2차 분류 체크박스 표시/숨김
        if hasattr(self, 'secondary_classification_checkbox'):
            self.secondary_classification_checkbox.setVisible(is_prompt_recognition)

            # 프롬프트 인식이 아닐 때는 2차 분류도 숨김
            if not is_prompt_recognition:
                self.secondary_classification_label.setVisible(False)
                self.secondary_classification_method_combo.setVisible(False)
                self.rule_selection_label.setVisible(False)
                self.rule_selection_combo.setVisible(False)
                self.secondary_rules_label.setVisible(False)
                self.secondary_rules_textedit.setVisible(False)

        # ImageCrudController에 반영
        try:
            self.app_context.image_crud_controller.set_classification_method(selected_method)
            print(f"✅ 분류 방법 변경: {selected_method}")
        except Exception as e:
            QMessageBox.warning(self, "오류", f"분류 방법 변경 실패: {e}")

    def _on_classification_rules_changed(self):
        """
        [신규] 분류 규칙 변경 핸들러
        """
        if not hasattr(self.app_context, 'image_crud_controller'):
            return

        rules_text = self.classification_rules_textedit.toPlainText().strip()
        self.app_context.image_crud_controller.set_classification_rules(rules_text)
        print(f"✅ 분류 규칙 업데이트: {len(rules_text)} 문자")

        # 🆕 2차 분류가 활성화되어 있고, 프롬프트 인식이 선택되어 있으면 규칙 콤보박스 업데이트
        if (hasattr(self, 'secondary_classification_checkbox') and
            self.secondary_classification_checkbox.isChecked() and
            self.secondary_classification_method_combo.currentData() == "prompt_recognition"):
            self._update_rule_selection_combo()

    def _reset_image_counter(self):
        """
        [신규] 이미지 저장 카운터 초기화 버튼 핸들러
        """
        if not hasattr(self.app_context, 'image_crud_controller'):
            QMessageBox.warning(self, "오류", "ImageCrudController를 찾을 수 없습니다.")
            return

        reply = QMessageBox.question(
            self,
            "카운터 초기화 확인",
            "이미지 저장 카운터를 1로 초기화하시겠습니까?\n\n"
            "⚠️ 기존 파일과 번호가 겹칠 수 있습니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.app_context.image_crud_controller.reset_counter()
            QMessageBox.information(self, "완료", "카운터가 1로 초기화되었습니다.")
    
    def _apply_saved_module_visibility(self, retry_count=0):
        """저장된 모듈 가시성 설정을 실제 UI에 적용"""
        max_retries = 3
        print(f"🔍 [SETTINGS] _apply_saved_module_visibility 호출됨 (시도 {retry_count + 1}/{max_retries + 1})")

        if not hasattr(self.app_context, 'middle_section_controller'):
            print("⚠️ [SETTINGS] middle_section_controller가 없습니다.")
            if retry_count < max_retries:
                print(f"  → 500ms 후 재시도...")
                QTimer.singleShot(500, lambda: self._apply_saved_module_visibility(retry_count + 1))
            return

        if not self.app_context.middle_section_controller:
            print("⚠️ [SETTINGS] middle_section_controller가 None입니다.")
            if retry_count < max_retries:
                print(f"  → 500ms 후 재시도...")
                QTimer.singleShot(500, lambda: self._apply_saved_module_visibility(retry_count + 1))
            return

        controller = self.app_context.middle_section_controller
        print(f"📊 [SETTINGS] 모듈 인스턴스 수: {len(controller.module_instances)}")
        print(f"📊 [SETTINGS] 모듈 박스 수: {len(controller.module_boxes)}")

        if not controller.module_boxes:
            print("⚠️ [SETTINGS] module_boxes가 비어있습니다. 모듈이 아직 생성되지 않았을 수 있습니다.")
            if retry_count < max_retries:
                print(f"  → 500ms 후 재시도...")
                QTimer.singleShot(500, lambda: self._apply_saved_module_visibility(retry_count + 1))
            return

        # 가시성 적용 성공
        applied_count = 0
        for module in controller.module_instances:
            module_id = module.__class__.__name__
            # 저장된 가시성 설정 가져오기 (기본값은 True)
            is_visible = self.settings_module.get_setting(f'module_visibility.{module_id}', True)

            module_title = module.get_title()
            print(f"  - 모듈 '{module_title}' ({module_id}): 설정 가시성={is_visible}")

            # 가시성이 False인 경우에만 숨기기
            if not is_visible:
                if module_title in controller.module_boxes:
                    box = controller.module_boxes[module_title]
                    box.setVisible(False)
                    print(f"    ✅ Module '{module_title}' hidden on startup")
                    applied_count += 1
                else:
                    print(f"    ⚠️ Module '{module_title}' not found in module_boxes")

        print(f"✅ [SETTINGS] 모듈 가시성 적용 완료 ({applied_count}개 숨김)")
    
    def _apply_saved_tab_visibility(self, retry_count=0):
        """저장된 탭 가시성 설정을 실제 UI에 적용"""
        max_retries = 3
        print(f"🔍 [SETTINGS] _apply_saved_tab_visibility 호출됨 (시도 {retry_count + 1}/{max_retries + 1})")

        if not (hasattr(self.app_context, 'main_window') and
                hasattr(self.app_context.main_window, 'image_window') and
                hasattr(self.app_context.main_window.image_window, 'tab_controller')):
            print("⚠️ [SETTINGS] tab_controller를 찾을 수 없습니다.")
            if retry_count < max_retries:
                print(f"  → 500ms 후 재시도...")
                QTimer.singleShot(500, lambda: self._apply_saved_tab_visibility(retry_count + 1))
            return

        tab_controller = self.app_context.main_window.image_window.tab_controller

        # 숨길 수 있는 탭들
        hideable_tabs = [
            'BrowserTabModule',      # 📦 Danbooru
            'PNGInfoTabModule',      # 📝 PNG Info
            'HookerTabModule',       # 🔍 Hooker
            'StorytellerTabModule',  # Storyteller 탭
            'AssetsTabModule'        # 🎨 Assets
        ]

        applied_count = 0
        for tab_id in hideable_tabs:
            if tab_id in tab_controller.tab_index_map:
                # 저장된 가시성 설정 가져오기 (기본값은 True)
                is_visible = self.settings_module.get_setting(f'tab_visibility.{tab_id}', True)

                print(f"  - 탭 '{tab_id}': 설정 가시성={is_visible}")

                # 탭 가시성 적용
                tab_index = tab_controller.tab_index_map[tab_id]
                tab_controller.tab_widget.setTabVisible(tab_index, is_visible)

                if not is_visible:
                    print(f"    ✅ Tab '{tab_id}' hidden on startup")
                    applied_count += 1

        print(f"✅ [SETTINGS] 탭 가시성 적용 완료 ({applied_count}개 숨김)")
    
    def _apply_saved_autocomplete_settings(self):
        """저장된 자동완성 설정을 실제로 적용"""
        # 저장된 자동완성 설정 가져오기
        autocomplete_enabled = self.settings_module.get_setting('autocomplete.enabled', True)

        # 실제 자동완성 시스템에 반영
        if hasattr(self.app_context, 'main_window'):
            main_window = self.app_context.main_window
            if hasattr(main_window, 'autocomplete_manager') and main_window.autocomplete_manager is not None:
                # AutoCompleteManager의 enable/disable 메서드 사용
                if autocomplete_enabled:
                    main_window.autocomplete_manager.enable()
                else:
                    main_window.autocomplete_manager.disable()
                print(f"🔍 Autocomplete {'enabled' if autocomplete_enabled else 'disabled'} on startup")
            else:
                print("⚠️ AutoCompleteManager가 아직 초기화되지 않았습니다.")
    
    def _apply_saved_ui_settings(self):
        """저장된 UI 설정을 실제로 적용"""
        # UI 스케일링 설정 적용
        if hasattr(self.app_context, 'main_window'):
            main_window = self.app_context.main_window
            
            # 스케일링 매니저 가져오기
            if hasattr(main_window, 'scaling_manager'):
                scaling_manager = main_window.scaling_manager
                
                # 저장된 UI 설정 가져오기
                auto_scaling = self.settings_module.get_setting('ui.auto_scaling', True)
                user_scale = self.settings_module.get_setting('ui.user_scale_factor', 1.0)
                
                # 설정 적용
                scaling_manager.set_auto_scaling_enabled(auto_scaling)
                if not auto_scaling:
                    scaling_manager.set_user_scale_factor(user_scale)
                    
                print(f"🎨 UI scaling applied on startup: auto={auto_scaling}, scale={user_scale}")
    
    def reset_to_defaults(self):
        """설정을 기본값으로 리셋"""
        reply = QMessageBox.question(
            self, "설정 리셋", 
            "모든 설정을 기본값으로 되돌리시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.settings_module.settings_data = self.settings_module._get_default_settings()
            self.settings_module.save_settings()
            self.update_ui_from_settings()
            QMessageBox.information(self, "완료", "설정이 기본값으로 초기화되었습니다.")
    
    def export_settings(self):
        """설정 내보내기"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "설정 내보내기", "naia_settings.json", "JSON Files (*.json)"
        )
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(self.settings_module.settings_data, f, indent=2, ensure_ascii=False)
                QMessageBox.information(self, "완료", f"설정이 {file_path}로 내보내졌습니다.")
            except Exception as e:
                QMessageBox.warning(self, "오류", f"설정 내보내기 실패: {e}")
    
    def import_settings(self):
        """설정 가져오기"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "설정 가져오기", "", "JSON Files (*.json)"
        )
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    imported_settings = json.load(f)
                
                # 설정 유효성 검사
                if self._validate_settings(imported_settings):
                    self.settings_module.settings_data = imported_settings
                    self.settings_module.save_settings()
                    self.update_ui_from_settings()
                    QMessageBox.information(self, "완료", "설정이 성공적으로 가져와졌습니다.")
                else:
                    QMessageBox.warning(self, "오류", "유효하지 않은 설정 파일입니다.")
            except Exception as e:
                QMessageBox.warning(self, "오류", f"설정 가져오기 실패: {e}")
    
    def _validate_settings(self, settings: dict) -> bool:
        """설정 데이터 유효성 검사"""
        required_keys = ['autocomplete', 'save_directory', 'ui']
        return all(key in settings for key in required_keys)
    
    def _open_scaling_settings(self):
        """UI 스케일링 설정 다이얼로그 열기"""
        dialog = ScalingSettingsDialog(self)
        dialog.scaling_changed.connect(self._on_scaling_changed)
        dialog.exec()
    
    def _on_scaling_changed(self, new_scale: float):
        """스케일링 변경 시 호출"""
        # 라벨 텍스트 업데이트
        scaling_manager = get_scaling_manager()
        auto_scaling = scaling_manager.is_auto_scaling_enabled()
        user_scale = scaling_manager.get_user_scale_factor()
        current_scale = scaling_manager.get_scale_factor()
        
        if auto_scaling:
            scale_text = f"자동 스케일링 ({current_scale:.1f}x)"
        else:
            scale_text = f"수동 스케일링 ({user_scale:.1f}x)"
            
        self.ui_scale_label.setText(f"UI 크기: {scale_text}")
        
        # 메인 윈도우의 스케일링 변경 이벤트 호출
        if (hasattr(self.app_context, 'main_window') and 
            hasattr(self.app_context.main_window, 'on_scaling_changed')):
            self.app_context.main_window.on_scaling_changed(new_scale)
