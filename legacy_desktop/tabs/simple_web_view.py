from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineSettings
from PyQt6.QtCore import QUrl, QStandardPaths, QTimer, Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, 
                             QFrame, QTextEdit, QApplication, QDialog, QCheckBox, 
                             QScrollArea, QSplitter, QGroupBox)
from interfaces.base_tab_module import BaseTabModule
from legacy_desktop.ui.theme import DARK_STYLES, DARK_COLORS, get_dynamic_styles
from legacy_desktop.ui.scaling_manager import get_scaled_font_size
import os
import sys
import requests
import json

class SimpleWebViewTabModule(BaseTabModule):
    """API 주소를 홈페이지로 하는 간단한 웹뷰 탭 모듈"""

    def __init__(self):
        super().__init__()
        self.web_view_widget: SimpleWebViewTab = None
        self.api_url = None
        self.api_mode = None  # 현재 API 모드 (WEBUI 또는 COMFYUI)
        self.app_context = None  # AppContext 참조

    def get_tab_title(self) -> str:
        if self.api_mode == 'WEBUI':
            return "🌐 WebUI"
        elif self.api_mode == 'COMFYUI':
            return "🌐 ComfyUI"
        else:
            return "🌐 API 웹뷰"
        
    def get_tab_order(self) -> int:
        return 10  # 다른 탭들보다 뒤에 위치
    
    def get_tab_type(self) -> str:
        return 'dynamic'  # 동적 탭으로 설정
    
    def can_close_tab(self) -> bool:
        return True  # 닫기 가능

    def setup(self, api_url: str, api_mode: str = None, app_context=None, **kwargs):
        """동적 생성 시 API URL과 모드를 설정"""
        self.api_url = api_url
        self.api_mode = api_mode
        self.app_context = app_context

    def create_widget(self, parent: QWidget) -> QWidget:
        if self.web_view_widget is None:
            self.web_view_widget = SimpleWebViewTab(parent, api_mode=self.api_mode, app_context=self.app_context)
            # API URL이 설정되어 있으면 로드
            if self.api_url:
                QTimer.singleShot(100, lambda: self.web_view_widget.load_url(self.api_url))
                # WEBUI 모드일 경우 extension 체크
                if self.api_mode == 'WEBUI':
                    QTimer.singleShot(500, lambda: self.web_view_widget.check_webui_extensions(self.api_url))
        return self.web_view_widget

class SimpleWebViewTab(QWidget):
    """태그 추출 기능이 제거된 간단한 웹뷰 탭"""
    
    def __init__(self, parent=None, api_mode=None, app_context=None):
        super().__init__(parent)
        self.api_mode = api_mode
        self.app_context = app_context
        self.setup_web_profile()
        self.init_ui()
        
    def init_ui(self):
        """UI 초기화"""
        main_layout = QVBoxLayout(self)
        
        # 주소 입력 바
        address_layout = QHBoxLayout()
        self.address_bar = QLineEdit()
        self.address_bar.setPlaceholderText("URL을 입력하세요...")
        self.address_bar.returnPressed.connect(self.navigate_to_url)
        
        self.go_button = QPushButton("이동")
        self.go_button.clicked.connect(self.navigate_to_url)
        
        self.back_button = QPushButton("←")
        self.forward_button = QPushButton("→")
        self.refresh_button = QPushButton("⟳")
        
        address_layout.addWidget(self.back_button)
        address_layout.addWidget(self.forward_button)
        address_layout.addWidget(self.refresh_button)
        address_layout.addWidget(self.address_bar)
        address_layout.addWidget(self.go_button)
        main_layout.addLayout(address_layout)
        
        # 웹뷰 생성
        self.browser = QWebEngineView()
        self.browser.setPage(self.page)
        main_layout.addWidget(self.browser, 1)
        self.browser.settings().setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True
        )
        
        # API Payload 버튼 영역 (WEBUI 모드에서만 사용)
        self.payload_frame = QFrame()
        self.payload_frame.setFixedHeight(34)
        payload_layout = QHBoxLayout(self.payload_frame)
        payload_layout.setContentsMargins(0, 0, 0, 0)
        
        self.payload_button = QPushButton("📋 클립보드에서 API Payload 가져오기")
        self.payload_button.clicked.connect(self.load_payload_from_clipboard)
        self.payload_button.setFixedHeight(32)
        dynamic_styles = get_dynamic_styles()
        self.payload_button.setStyleSheet(dynamic_styles['secondary_button'])
        
        payload_layout.addWidget(self.payload_button)
        payload_layout.addStretch()  # 왼쪽 정렬
        
        self.payload_frame.setVisible(False)  # 기본적으로 숨김
        main_layout.addWidget(self.payload_frame)
        
        # Extension 체크 결과 표시 영역 (WEBUI 모드에서만 사용)
        self.extension_display = QTextEdit()
        self.extension_display.setFixedHeight(150)
        self.extension_display.setReadOnly(True)
        self.extension_display.setStyleSheet(f"{dynamic_styles['compact_textedit']} font-size: {get_scaled_font_size(16)}px;")
        self.extension_display.setVisible(False)
        main_layout.addWidget(self.extension_display)

        # 버튼 연결
        self.back_button.clicked.connect(self.browser.back)
        self.forward_button.clicked.connect(self.browser.forward)
        self.refresh_button.clicked.connect(self.browser.reload)
        self.browser.urlChanged.connect(self.update_address_bar)
        
        self.update_address_bar(self.browser.url())
        
    def setup_web_profile(self):
        """웹 프로필 설정"""
        try:
            app_data_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
            profile_path = os.path.join(app_data_path, "simple_web_profile")
            os.makedirs(profile_path, exist_ok=True)
            
            self.profile = QWebEngineProfile("SimpleWebProfile")
            self.profile.setPersistentStoragePath(profile_path)
            
            # 저장 설정
            self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
            self.profile.setPersistentCookiesPolicy(
                QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
            )
            
            self.page = QWebEnginePage(self.profile)
            
            # 기본 웹 설정
            settings = self.page.settings()
            settings.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadImages, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, False)
            settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, False)
            settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, False)
            
            print("간단한 웹뷰 설정 완료")
            
        except Exception as e:
            print(f"웹뷰 설정 중 오류: {e}")
    
    def navigate_to_url(self):
        """주소창의 URL로 이동"""
        url = self.address_bar.text().strip()
        if not url:
            return
            
        # URL 형식 검증 및 보정
        if not url.startswith(('http://', 'https://')):
            if '.' in url and ' ' not in url:
                url = 'https://' + url
            else:
                url = f'https://www.google.com/search?q={url}'
        
        self.load_url(url)
    
    def update_address_bar(self, qurl):
        """주소 표시줄 업데이트"""
        self.address_bar.setText(qurl.toString())

    def load_url(self, url):
        """URL 로드"""
        if isinstance(url, str):
            qurl = QUrl(url)
        else:
            qurl = url
            
        self.browser.load(qurl)
        self.address_bar.setText(qurl.toString())
    
    def check_webui_extensions(self, api_url):
        """WEBUI extensions 체크"""
        if self.api_mode != 'WEBUI':
            return
        
        try:
            # API URL에서 /sdapi/v1/extensions 엔드포인트 구성
            base_url = api_url.rstrip('/')
            extensions_url = f"{base_url}/sdapi/v1/extensions"
            
            # GET 요청 보내기
            response = requests.get(extensions_url, timeout=5)
            response.raise_for_status()
            
            extensions = response.json()
            
            # sd-webui-api-payload-display 확인 (테스트용으로 _fail 체크)
            has_payload_display = False
            for ext in extensions:
                if ext.get('name') == 'sd-webui-api-payload-display':  # 테스트용
                    has_payload_display = True
                    break
            
            # Extension이 없는 경우 안내 메시지 표시
            if not has_payload_display:
                self.show_extension_guide()
            else:
                # Extension이 있으면 Payload 버튼 표시
                self.payload_frame.setVisible(True)
                print("[NAIA] sd-webui-api-payload-display Extension 감지 - Payload 버튼 활성화")
                
        except requests.exceptions.RequestException as e:
            print(f"Extension 체크 실패: {e}")
        except Exception as e:
            print(f"Extension 체크 중 오류: {e}")
    
    def show_extension_guide(self):
        """Extension 설치 안내 메시지 표시"""
        guide_text = """⚠️ 필수 Extension 안내

NAIA의 WEBUI모드는 sd-webui-api-payload-display Extension이 있어야 Adetailer와 같은 사용자의 Extension들을 Catch하고 NAIA에서 사용 가능하도록 설정할 수 있습니다.

다음 절차에 따라 설치해주세요:

1. WEBUI의 Extension 탭에 들어갑니다.
2. Available 이라고 표시된 탭에서 [Load from:] 버튼을 눌러 설치 가능한 Extension 리스트들을 다운로드 받습니다.
3. sd-webui-api-payload-display 를 찾아 Install 합니다.
   만약 없으면 Install from URL에서 https://github.com/huchenlei/sd-webui-api-payload-display 를 입력하여 직접 설치합니다.
4. 설치가 완료되면 Installed 탭에서 Apply and restart UI 버튼을 누르고 WEBUI를 재실행합니다.
"""
        
        self.extension_display.setPlainText(guide_text)
        self.extension_display.setVisible(True)
    
    def load_payload_from_clipboard(self):
        """클립보드에서 API Payload 가져와서 처리"""
        try:
            clipboard = QApplication.clipboard()
            clipboard_text = clipboard.text()
            
            if not clipboard_text:
                print("[NAIA] 클립보드가 비어있습니다")
                return
            
            # Rule 1: "APG's now your CFG" 이스케이프 처리
            processed_text = clipboard_text.replace(
                '"APG\'s now your CFG" for reForge',
                '\\"APG\'s now your CFG\\" for reForge'
            )
            
            # JSON 파싱 시도
            try:
                payload_data = json.loads(processed_text)
            except json.JSONDecodeError:
                print("[NAIA] 클립보드 내용이 유효한 JSON이 아닙니다")
                return
            
            # Rule 2: "alwayson_scripts" 부분만 추출
            if "alwayson_scripts" not in payload_data:
                print("[NAIA] alwayson_scripts를 찾을 수 없습니다")
                return
            
            alwayson_scripts = payload_data["alwayson_scripts"]
            
            # Rule 3: depth1을 key: value 쫍으로 변환
            extension_data = {}
            for script_name, script_config in alwayson_scripts.items():
                # 스크립트 이름 언이스케이프 처리
                clean_name = script_name.replace('\\"', '"')
                
                # args 추출
                if isinstance(script_config, dict) and "args" in script_config:
                    extension_data[clean_name] = script_config["args"]
                    print(f"[NAIA] Extension 감지: {clean_name}")
            
            # 데이터 처리 성공
            if extension_data:
                print(f"[NAIA] {len(extension_data)}개의 Extension 데이터를 성공적으로 가져왔습니다")
                
                # 예시: ADetailer 데이터 확인
                if "ADetailer" in extension_data:
                    adetailer_args = extension_data["ADetailer"]
                    print(f"[NAIA] ADetailer args 개수: {len(adetailer_args) if isinstance(adetailer_args, list) else 'N/A'}")
                
                # JSON 변환 윈도우 열기
                self.show_json_converter_window(extension_data)
                
                # 성공 메시지 표시
                self.payload_button.setText("✅ Payload 가져오기 성공")
                QTimer.singleShot(2000, lambda: self.payload_button.setText("📋 클립보드에서 API Payload 가져오기"))
            else:
                print("[NAIA] Extension 데이터를 찾을 수 없습니다")
                
        except Exception as e:
            print(f"[NAIA] Payload 처리 중 오류: {e}")
    
    def show_json_converter_window(self, extension_data):
        """사용자가 필요한 Extension만 선택하는 JSON 변환 윈도우.
        TODO(web-dialog): 원래 JsonConverterDialog.exec() — Web Shell 패널/모달로 재구현 필요."""
        print("[Dialog/SKIPPED] JsonConverterDialog 차단 — Web Shell 재구현 예정")

class JsonConverterDialog(QDialog):
    """Extension 선택 및 JSON 변환 다이얼로그"""
    
    def __init__(self, extension_data, app_context=None, parent=None):
        super().__init__(parent)
        self.extension_data = extension_data
        self.app_context = app_context
        self.checkboxes = {}
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("JSON 변환 윈도우")
        self.setMinimumSize(800, 600)
        
        # 다크 테마 스타일
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
            QTextEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                font-family: monospace;
                font-size: {get_scaled_font_size(14)}px;
            }}
            QCheckBox {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(16)}px;
                padding: 4px;
            }}
            QCheckBox:checked {{
                color: {DARK_COLORS['text_primary']};
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
            }}
            QCheckBox::indicator:unchecked {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
            }}
            QCheckBox::indicator:checked {{
                background-color: {DARK_COLORS['accent_blue']};
                border: 1px solid {DARK_COLORS['accent_blue']};
            }}
            QGroupBox {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['text_primary']};
                border-radius: 4px;
                margin-top: 10px;
                padding-top: 10px;
                font-size: {get_scaled_font_size(16)}px;
            }}
            QGroupBox::title {{
                color: {DARK_COLORS['text_primary']};
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }}
        """)
        
        main_layout = QVBoxLayout(self)
        
        # Splitter로 왼쪽/오른쪽 분할
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 왼쪽: JSON 미리보기 TextEdit
        self.preview_text = QTextEdit()
        self.preview_text.setPlaceholderText("JSON 미리보기...")
        self.update_preview()
        splitter.addWidget(self.preview_text)
        
        # 오른쪽: Extension 체크박스 목록
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        # Extension 선택 그룹박스
        group_box = QGroupBox("Extension 선택")
        group_layout = QVBoxLayout(group_box)
        
        # 스크롤 영역
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        
        # scroll_widget 배경색을 약간 덜 진한 검은색으로
        scroll_widget.setStyleSheet(f"background-color: {DARK_COLORS['bg_tertiary']};")
        
        # 각 Extension에 대한 체크박스 생성
        for ext_name in sorted(self.extension_data.keys()):
            checkbox = QCheckBox(ext_name)
            checkbox.setChecked(False)  # 기본적으로 모두 해제
            checkbox.stateChanged.connect(self.update_preview)
            
            # 테두리 스타일
            checkbox.setStyleSheet(f"""
                QCheckBox {{
                    border: 1px solid {DARK_COLORS['text_primary']};
                    border-radius: 3px;
                    padding: 5px;
                    margin: 2px;
                }}
                QCheckBox:hover {{
                    background-color: {DARK_COLORS['bg_tertiary']};
                }}
            """)
            
            self.checkboxes[ext_name] = checkbox
            scroll_layout.addWidget(checkbox)
        
        scroll_layout.addStretch()
        scroll_widget.setLayout(scroll_layout)
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        group_layout.addWidget(scroll_area)
        group_box.setLayout(group_layout)
        right_layout.addWidget(group_box)
        
        # 전체 선택/해제 버튼
        select_buttons_layout = QHBoxLayout()
        select_all_btn = QPushButton("전체 선택")
        select_all_btn.clicked.connect(self.select_all)
        deselect_all_btn = QPushButton("전체 해제")
        deselect_all_btn.clicked.connect(self.deselect_all)
        select_buttons_layout.addWidget(select_all_btn)
        select_buttons_layout.addWidget(deselect_all_btn)
        right_layout.addLayout(select_buttons_layout)
        
        splitter.addWidget(right_widget)
        splitter.setSizes([400, 400])  # 초기 크기 설정
        
        main_layout.addWidget(splitter)
        
        # 하단 버튼
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        send_button = QPushButton("Send to Custom/Override API Parameters")
        send_button.clicked.connect(self.send_to_api_params)
        dynamic_styles = get_dynamic_styles()
        send_button.setStyleSheet(f"{dynamic_styles['primary_button']} background-color: {DARK_COLORS['accent_blue']};")
        
        cancel_button = QPushButton("취소")
        cancel_button.clicked.connect(self.reject)
        cancel_button.setStyleSheet(dynamic_styles['secondary_button'])
        
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(send_button)
        main_layout.addLayout(button_layout)
    
    def select_all(self):
        """모든 체크박스 선택"""
        for checkbox in self.checkboxes.values():
            checkbox.setChecked(True)
    
    def deselect_all(self):
        """모든 체크박스 해제"""
        for checkbox in self.checkboxes.values():
            checkbox.setChecked(False)
    
    def update_preview(self):
        """선택된 Extension에 따라 JSON 미리보기 업데이트"""
        selected_extensions = {}
        for ext_name, checkbox in self.checkboxes.items():
            if checkbox.isChecked():
                selected_extensions[ext_name] = self.extension_data[ext_name]
        
        # JSON 형식으로 변환
        json_output = self.format_as_custom_json(selected_extensions)
        self.preview_text.setPlainText(json_output)
    
    def format_as_custom_json(self, selected_extensions):
        """선택된 Extension을 사용자 정의 JSON 형식으로 변환"""
        # 올바른 JSON 형식으로 생성 (외부 중괄호 포함)
        result = {}
        
        for ext_name, args in selected_extensions.items():
            # args가 리스트인 경우 그대로 사용
            result[ext_name] = {
                "args": args
            }
        
        # JSON으로 변환 (들여쓰기 포함, 외부 중괄호 유지)
        json_str = json.dumps(result, indent=2, ensure_ascii=False)
        
        return json_str
    
    def send_to_api_params(self):
        """선택된 Extension을 API 파라미터로 전송"""
        # 현재 API 모드 확인
        if self.app_context and hasattr(self.app_context, 'current_api_mode'):
            if self.app_context.current_api_mode != 'WEBUI':
                print(f"[NAIA] 현재 모드가 WEBUI가 아닙니다 ({self.app_context.current_api_mode}). 요청을 차단합니다.")
                return
        
        selected_extensions = {}
        for ext_name, checkbox in self.checkboxes.items():
            if checkbox.isChecked():
                selected_extensions[ext_name] = self.extension_data[ext_name]
        
        if selected_extensions:
            print(f"[NAIA] {len(selected_extensions)}개의 Extension을 API Parameters로 전송")
            for ext_name in selected_extensions.keys():
                print(f"  - {ext_name}")
            
            # JSON 형식으로 변환
            json_output = self.format_as_custom_json(selected_extensions)
            
            # custom_script_textbox에 작성
            if self.app_context:
                try:
                    # MainWindow의 custom_script_textbox에 접근
                    main_window = self.app_context.main_window
                    if hasattr(main_window, 'custom_script_textbox'):
                        # 기존 내용 비우고 덧쓌워기
                        main_window.custom_script_textbox.clear()
                        main_window.custom_script_textbox.setPlainText(json_output)
                        print("[NAIA] custom_script_textbox에 Extension 데이터를 성공적으로 저장했습니다")
                    else:
                        print("[NAIA] custom_script_textbox를 찾을 수 없습니다")
                except Exception as e:
                    print(f"[NAIA] custom_script_textbox 접근 중 오류: {e}")
            
            self.accept()
        else:
            print("[NAIA] 선택된 Extension이 없습니다")

def setup_webengine_ssl_fix():
    """WebEngine SSL 및 CSP 에러 해결 설정"""
    flags = [
        # SSL 관련
        '--ignore-ssl-errors',
        '--ignore-certificate-errors',
        '--ignore-certificate-errors-spki-list',
        '--allow-running-insecure-content',
        '--disable-web-security',
        
        # CSP (Content Security Policy) 해결
        '--disable-web-security',
        '--disable-features=VizDisplayCompositor',
        '--disable-ipc-flooding-protection',
        
        # GPU/WebGL 관련 (에러 억제)
        '--disable-gpu',
        '--disable-software-rasterizer',
        '--disable-background-timer-throttling',
        '--disable-backgrounding-occluded-windows',
        '--disable-renderer-backgrounding',
        
        # 기타 에러 억제
        '--no-sandbox',
        '--disable-dev-shm-usage',
        '--disable-extensions',
        '--disable-plugins',
        '--disable-default-apps',
        '--no-first-run',
        '--disable-background-networking',
        
        # 로깅 레벨 조정 (에러 메시지 줄이기)
        '--log-level=3',
        '--silent-debugger-extension-api',
    ]
    
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = ' '.join(flags)
    os.environ['QTWEBENGINE_DISABLE_SANDBOX'] = '1'
    
    print("WebEngine 고급 설정 완료")

# 강화된 콘솔 출력 필터링
class ErrorFilter:
    """에러 메시지 필터링"""
    def __init__(self):
        self.original_stderr = sys.stderr
        
    def write(self, text):
        ignore_patterns = [
            'ssl_client_socket_impl.cc',
            'Permissions-Policy header',
            'Failed to create WebGPU',
            'font-size:0;color:transparent',
            'cloudflare.com/cdn-cgi',
            'handshake failed',
            'net_error -101',
            'Content Security Policy directive',
            'script-src',
            'unsafe-eval',
            'unsafe-inline',
            'Refused to load the script',
            'Refused to execute inline script',
            'Refused to evaluate a string as JavaScript',
            '[Report Only]'
        ]
        
        if not any(pattern in text for pattern in ignore_patterns):
            self.original_stderr.write(text)
    
    def flush(self):
        self.original_stderr.flush()

def enable_error_filtering():
    """에러 필터링 활성화"""
    sys.stderr = ErrorFilter()
    print("웹뷰 에러 필터링 활성화")