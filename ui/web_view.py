from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineSettings
from PyQt6.QtCore import QUrl, QStandardPaths, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel, QTextEdit
import os
import sys
import re
import json

class BrowserTab(QWidget):
    # 태그 추출 완료 시그널
    tags_extracted = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.setup_selective_storage()
        
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
        
        # Danbooru 태그 추출 버튼
        self.extract_tags_button = QPushButton("📝 태그 추출")
        self.extract_tags_button.clicked.connect(self.extract_danbooru_tags)
        self.extract_tags_button.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                font-weight: bold;
                border-radius: 4px;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        
        address_layout.addWidget(self.back_button)
        address_layout.addWidget(self.forward_button)
        address_layout.addWidget(self.refresh_button)
        address_layout.addWidget(self.address_bar)
        address_layout.addWidget(self.go_button)
        address_layout.addWidget(self.extract_tags_button)
        
        main_layout.addLayout(address_layout)
        
        # 웹뷰 생성
        self.browser = QWebEngineView()
        main_layout.addWidget(self.browser)
        
        # 태그 추출 결과 표시 영역 (숨김 상태로 시작)
        self.tags_display = QTextEdit()
        self.tags_display.setMaximumHeight(200)
        self.tags_display.setReadOnly(True)
        self.tags_display.setStyleSheet("""
            QTextEdit {
                background-color: #f5f5f5;
                border: 1px solid #ddd;
                border-radius: 4px;
                font-family: Consolas, Monaco, monospace;
                font-size: 11px;
            }
        """)
        self.tags_display.setPlaceholderText("Danbooru 페이지에서 '📝 태그 추출' 버튼을 클릭하세요...")
        self.tags_display.hide()  # 초기에는 숨김
        main_layout.addWidget(self.tags_display)
        
        # 신호 연결
        self.back_button.clicked.connect(self.browser.back)
        self.forward_button.clicked.connect(self.browser.forward)
        self.refresh_button.clicked.connect(self.browser.reload)
        self.browser.urlChanged.connect(self.update_address_bar)
        
    def setup_selective_storage(self):
        """Danbooru 로그인 정보만 저장하는 선택적 스토리지 설정"""
        try:
            # 커스텀 프로필 생성
            app_data_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
            profile_path = os.path.join(app_data_path, "browser_profile")
            os.makedirs(profile_path, exist_ok=True)
            
            self.profile = QWebEngineProfile("DanbooruOnlyProfile")
            self.profile.setPersistentStoragePath(profile_path)
            
            # 저장 설정
            self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)
            self.profile.setPersistentCookiesPolicy(
                QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
            )
            
            # 새 페이지 생성하고 프로필 할당
            self.page = QWebEnginePage(self.profile, self.browser)
            self.browser.setPage(self.page)
            
            # 기본 웹 설정
            settings = self.page.settings()
            settings.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadImages, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, False)
            settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, False)
            settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, False)
            
            print("Danbooru 브라우저 설정 완료")
            
        except Exception as e:
            print(f"브라우저 설정 중 오류: {e}")
    
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
        """주소창 업데이트"""
        self.address_bar.setText(qurl.toString())
        
        # Danbooru 페이지인지 확인하여 태그 추출 버튼 상태 변경
        url_str = qurl.toString()
        pattern = r'danbooru\.donmai\.us/posts/(\d+)'
        if re.search(pattern, url_str):
            self.extract_tags_button.setEnabled(True)
            self.extract_tags_button.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                    font-weight: bold;
                    border-radius: 4px;
                    padding: 5px 10px;
                }
                QPushButton:hover {
                    background-color: #45a049;
                }
            """)
        else:
            self.extract_tags_button.setEnabled(False)
            self.extract_tags_button.setStyleSheet("""
                QPushButton {
                    background-color: #cccccc;
                    color: #666666;
                    font-weight: bold;
                    border-radius: 4px;
                    padding: 5px 10px;
                }
            """)
        
    def load_url(self, url):
        """URL 로드"""
        if isinstance(url, str):
            qurl = QUrl(url)
        else:
            qurl = url
            
        self.browser.load(qurl)
        self.address_bar.setText(qurl.toString())
    
    def extract_danbooru_tags(self):
        """현재 Danbooru 페이지에서 태그 정보 추출"""
        current_url = self.browser.url().toString()
        
        # URL에서 ID 추출
        if 'danbooru.donmai.us/posts/' not in current_url:
            self.tags_display.setText("❌ Danbooru 포스트 페이지가 아닙니다.")
            self.tags_display.show()
            return
        
        # JavaScript로 페이지 HTML과 URL 가져오기
        js_code = """
        (function() {
            const result = {
                url: window.location.href,
                html: document.documentElement.outerHTML
            };
            return result;
        })();
        """
        
        self.page.runJavaScript(js_code, self.process_page_data)
    
    def process_page_data(self, page_data):
        """JavaScript에서 받은 페이지 데이터 처리"""
        if not page_data:
            self.tags_display.setText("❌ 페이지 데이터를 가져올 수 없습니다.")
            # self.tags_display.show()
            return
        
        try:
            # URL에서 ID 추출
            url = page_data['url']
            pattern = r'danbooru\.donmai\.us/posts/(\d+)'
            match = re.search(pattern, url)
            
            if match:
                post_id = int(match.group(1))
            else:
                post_id = None
                
            if not post_id:
                self.tags_display.setText("❌ 포스트 ID를 찾을 수 없습니다.")
                # self.tags_display.show()
                return
            
            # HTML에서 태그 추출
            html = page_data['html']
            tags_data = self.parse_danbooru_tags(html, post_id)
            
            # 결과 표시
            self.display_extracted_tags(tags_data)
            
            # 시그널 발송
            # self.tags_extracted.emit(tags_data)
            
        except Exception as e:
            self.tags_display.setText(f"❌ 태그 추출 중 오류 발생: {str(e)}")
            # self.tags_display.show()
    
    def parse_danbooru_tags(self, html, post_id):
        """HTML에서 Danbooru 태그 정보 파싱"""
        tags_data = {
            'id': post_id,
            'artist': [],
            'copyright': [],
            'character': [],
            'general': [],
            'meta': []
        }
        
        # 각 태그 카테고리별로 추출
        categories = {
            'artist': r'<ul class="artist-tag-list">(.*?)</ul>',
            'copyright': r'<ul class="copyright-tag-list">(.*?)</ul>',
            'character': r'<ul class="character-tag-list">(.*?)</ul>',
            'general': r'<ul class="general-tag-list">(.*?)</ul>',
            'meta': r'<ul class="meta-tag-list">(.*?)</ul>'
        }
        
        for category, pattern in categories.items():
            # 해당 카테고리의 ul 태그 내용 찾기
            ul_match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
            if ul_match:
                ul_content = ul_match.group(1)
                
                # data-tag-name 속성 값들 추출
                tag_pattern = r'data-tag-name="([^"]*)"'
                tag_matches = re.findall(tag_pattern, ul_content)
                
                # HTML 엔티티 디코딩 및 정리
                for tag in tag_matches:
                    # HTML 엔티티 디코딩
                    tag = tag.replace('&amp;', '&')
                    tag = tag.replace('&lt;', '<')
                    tag = tag.replace('&gt;', '>')
                    tag = tag.replace('&quot;', '"')
                    tag = tag.replace('&#39;', "'")
                    
                    if tag and tag not in tags_data[category]:
                        tags_data[category].append(tag)
        
        return tags_data
    
    def display_extracted_tags(self, tags_data):
        """추출된 태그 정보를 표시"""
        result_text = f"🎯 Danbooru 태그 추출 결과 (ID: {tags_data['id']})\n"
        result_text += "=" * 50 + "\n\n"
        
        for category, tags in tags_data.items():
            if category == 'id':
                continue
                
            result_text += f"📌 {category.upper()}:\n"
            if tags:
                for tag in tags:
                    result_text += f"   • {tag}\n"
            else:
                result_text += "   (없음)\n"
            result_text += "\n"
        
        # JSON 형태로도 표시
        result_text += "📋 JSON 형태:\n"
        result_text += "-" * 30 + "\n"
        result_text += json.dumps(tags_data, indent=2, ensure_ascii=False)
        
        # self.tags_display.setText(result_text)
        # self.tags_display.show()
        
        print("🎯 Danbooru 태그 추출 완료:")
        # print(json.dumps(tags_data, indent=2, ensure_ascii=False))
        self.tags_extracted.emit(tags_data)

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
    
    print("WebEngine 고급 설정 완료 (CSP 포함)")

# 강화된 콘솔 출력 필터링
class ErrorFilter:
    """에러 메시지 필터링"""
    def __init__(self):
        self.original_stderr = sys.stderr
        
    def write(self, text):
        # CSP 관련 에러 패턴 추가
        ignore_patterns = [
            'ssl_client_socket_impl.cc',
            'Permissions-Policy header',
            'Failed to create WebGPU',
            'font-size:0;color:transparent',
            'cloudflare.com/cdn-cgi',
            'handshake failed',
            'net_error -101',
            # CSP 관련 패턴들 추가
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
    print("브라우저 에러 필터링 활성화 (CSP 포함)")