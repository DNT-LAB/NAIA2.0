from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineSettings
from PyQt6.QtCore import QUrl, QStandardPaths, pyqtSignal, QTimer, Qt
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLineEdit,
    QLabel,
    QFrame,
    QScrollArea,
    QSplitter,
)
from interfaces.base_tab_module import BaseTabModule
from core.filter_data_manager import FilterDataManager
from core.tag_filter_helpers import _is_color_exception
import os
import sys
import re
import json
import io
import contextlib


DANBOORU_POST_PATTERN = r'danbooru\.donmai\.us/posts/(\d+)'
DANBOORU_DATA_GROUPS = ('artist', 'copyright', 'character', 'general', 'meta')
DANBOORU_PRIMARY_TAG_GROUPS = (
    ('artist', 'ARTIST'),
    ('copyright', 'COPYRIGHT'),
    ('character', 'CHARACTER'),
    ('meta', 'META'),
)
DANBOORU_GENERAL_GROUPS = (
    ('character_features', 'CHARACTER FEATURES'),
    ('subject_count', 'SUBJECT COUNT'),
    ('clothing_events', 'CLOTHING EVENTS'),
    ('clothes', 'CLOTHES'),
    ('colors', 'COLORS'),
    ('location_background', 'LOCATION / BACKGROUND'),
    ('expression', 'EXPRESSION'),
    ('pose_action', 'POSE / ACTION'),
    ('objects', 'OBJECTS'),
    ('meta_like', 'META-LIKE'),
    ('noise', 'LOW-FREQ / NOISE'),
    ('other', 'OTHER GENERALS'),
)
DANBOORU_FILTER_MANAGER_CACHE = None
PERSON_COUNT_RE = re.compile(r'^(?:[1-5](?:boy|boys|girl|girls|other|others)|6\+(?:boys|girls|others))$')

DANBOORU_BROWSER_QSS = """
QWidget#NaiaDanbooruBrowser {
    background: #0a0a0f;
    color: #e8e8f0;
    font-family: "Pretendard", "Malgun Gothic", "Segoe UI", sans-serif;
    font-size: 13px;
}

QFrame#NaiaDanbooruBrowserPanel,
QFrame#NaiaDanbooruToolbar,
QFrame#NaiaDanbooruTagPanel {
    background: #12121a;
    border: 1px solid #2a2a3d;
    border-radius: 8px;
}

QFrame#NaiaDanbooruToolbar {
    border-radius: 7px;
}

QLineEdit#NaiaDanbooruAddress {
    background: #1a1a26;
    color: #e8e8f0;
    border: 1px solid #2a2a3d;
    border-radius: 7px;
    padding: 7px 10px;
    selection-background-color: #7c6aef;
    selection-color: #ffffff;
}

QLineEdit#NaiaDanbooruAddress:focus {
    border: 1px solid #7c6aef;
}

QPushButton[naiaRole="secondary"] {
    background: #1a1a26;
    color: #e8e8f0;
    border: 1px solid #2a2a3d;
    border-radius: 7px;
    padding: 7px 10px;
    font-size: 12px;
    font-weight: 700;
}

QPushButton[naiaRole="secondary"]:hover {
    background: #222233;
    border-color: #3d3d5c;
}

QPushButton[naiaRole="primary"] {
    background: #7c6aef;
    color: #ffffff;
    border: 1px solid #9d8bff;
    border-radius: 7px;
    padding: 8px 12px;
    font-size: 12px;
    font-weight: 800;
}

QPushButton[naiaRole="primary"]:hover {
    background: #8f80f4;
}

QPushButton[naiaRole="primary"]:disabled,
QPushButton[naiaRole="secondary"]:disabled {
    background: #15151f;
    color: #555568;
    border-color: #242436;
}

QWebEngineView#NaiaDanbooruWebView {
    background: #0a0a0f;
    border: 1px solid #2a2a3d;
    border-radius: 8px;
}

QLabel#NaiaDanbooruPanelTitle {
    color: #ffffff;
    font-size: 17px;
    font-weight: 900;
}

QLabel#NaiaDanbooruStatus {
    color: #8888a0;
    font-size: 12px;
    font-weight: 700;
}

QLabel#NaiaDanbooruStatus[naiaTone="success"] {
    color: #48d27a;
}

QLabel#NaiaDanbooruStatus[naiaTone="warning"] {
    color: #f0b35a;
}

QLabel#NaiaDanbooruStatus[naiaTone="error"] {
    color: #ff7d8f;
}

QScrollArea#NaiaDanbooruTagScroll,
QScrollArea#NaiaDanbooruTagScroll > QWidget > QWidget {
    background: transparent;
    border: none;
}

QFrame[naiaRole="tag-group"] {
    background: #1a1a26;
    border: 1px solid #2a2a3d;
    border-radius: 7px;
}

QLabel[naiaRole="tag-title"] {
    color: #9d8bff;
    font-size: 12px;
    font-weight: 900;
    letter-spacing: 0px;
}

QLabel[naiaRole="tag-body"] {
    color: #e8e8f0;
    font-size: 12px;
    line-height: 1.35;
}

QLabel#NaiaDanbooruGeneralTitle {
    color: #ffffff;
    font-size: 13px;
    font-weight: 900;
    padding-top: 4px;
}

QSplitter::handle {
    background: #171723;
}
"""

class SilentWebEnginePage(QWebEnginePage):
    """JavaScript 콘솔 메시지를 필터링하는 커스텀 페이지 클래스"""

    # 무시할 메시지 패턴들
    IGNORE_PATTERNS = [
        'Permissions-Policy header',
        'Failed to create WebGPU',
        'font-size:0;color:transparent',
        'cloudflare',
        'Content Security Policy',
        'script-src',
        'unsafe-eval',
        'unsafe-inline',
        'Refused to load',
        'Refused to execute',
        'Refused to evaluate',
        '[Report Only]',
        'preloaded using link preload but not used',
    ]

    def javaScriptConsoleMessage(self, level, message, line, source):
        """JavaScript 콘솔 메시지 필터링"""
        # 무시할 패턴에 해당하면 출력하지 않음
        if any(pattern in message for pattern in self.IGNORE_PATTERNS):
            return

        # 나머지 메시지는 기본 동작 (출력)
        super().javaScriptConsoleMessage(level, message, line, source)


class BrowserTabModule(BaseTabModule):
    """'Danbooru' 브라우저 탭을 위한 모듈"""
    generate_with_image_requested = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.browser_widget: BrowserTab = None

    def get_tab_title(self) -> str:
        return "📦 Danbooru"
        
    def get_tab_order(self) -> int:
        return 2

    def create_widget(self, parent: QWidget) -> QWidget:
        if self.browser_widget is None:
            self.browser_widget = BrowserTab(parent)
            self.browser_widget.generate_prompt_requested.connect(self.instant_generation_requested)
            self.browser_widget.generate_with_image_requested.connect(self.generate_with_image_requested)
            # ✅ URL 로드를 위젯 생성 직후가 아닌 약간 지연해서 실행
            QTimer.singleShot(100, lambda: self.browser_widget.load_url("https://danbooru.donmai.us/"))
        return self.browser_widget

class BrowserTab(QWidget):
    # 태그 추출 완료 시그널
    generate_prompt_requested = pyqtSignal(dict)
    generate_with_image_requested = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        # ✅ 순서 변경: 프로필 설정을 UI 초기화보다 먼저
        self.filter_manager = self._load_filter_manager()
        self.characteristic = (
            self.filter_manager.characteristic_list
            if self.filter_manager is not None
            else self._load_list_from_file()
        )
        self.setup_selective_storage()
        self.init_ui()
        self.extracted_tags_data = {}
        
    def init_ui(self):
        """UI 초기화"""
        self.setObjectName("NaiaDanbooruBrowser")
        self.setStyleSheet(DANBOORU_BROWSER_QSS)
        self._last_auto_extract_post_id = None
        self._tag_title_labels = {}
        self._tag_body_labels = {}
        self._tag_group_frames = {}

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        browser_panel = QFrame()
        browser_panel.setObjectName("NaiaDanbooruBrowserPanel")
        browser_layout = QVBoxLayout(browser_panel)
        browser_layout.setContentsMargins(10, 10, 10, 10)
        browser_layout.setSpacing(8)

        toolbar = QFrame()
        toolbar.setObjectName("NaiaDanbooruToolbar")
        address_layout = QHBoxLayout(toolbar)
        address_layout.setContentsMargins(8, 8, 8, 8)
        address_layout.setSpacing(8)

        self.back_button = self._create_toolbar_button("←")
        self.forward_button = self._create_toolbar_button("→")
        self.refresh_button = self._create_toolbar_button("⟳")

        self.address_bar = QLineEdit()
        self.address_bar.setObjectName("NaiaDanbooruAddress")
        self.address_bar.setPlaceholderText("URL, post ID, or tag query")
        self.address_bar.returnPressed.connect(self.navigate_to_url)

        self.go_button = self._create_toolbar_button("이동")
        self.go_button.clicked.connect(self.navigate_to_url)

        address_layout.addWidget(self.back_button)
        address_layout.addWidget(self.forward_button)
        address_layout.addWidget(self.refresh_button)
        address_layout.addWidget(self.address_bar)
        address_layout.addWidget(self.go_button)
        browser_layout.addWidget(toolbar)

        # ✅ 웹뷰 생성 시점 변경: 프로필이 이미 설정된 상태에서 생성
        self.browser = QWebEngineView()
        self.browser.setObjectName("NaiaDanbooruWebView")
        self.browser.setPage(self.page)  # 이미 생성된 페이지 설정
        browser_layout.addWidget(self.browser, 1)
        splitter.addWidget(browser_panel)

        tag_panel = QFrame()
        tag_panel.setObjectName("NaiaDanbooruTagPanel")
        tag_layout = QVBoxLayout(tag_panel)
        tag_layout.setContentsMargins(12, 12, 12, 12)
        tag_layout.setSpacing(10)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title = QLabel("Extracted Tags")
        title.setObjectName("NaiaDanbooruPanelTitle")
        self.extract_tags_button = self._create_toolbar_button("태그 다시 읽기")
        self.extract_tags_button.setEnabled(False)
        self.extract_tags_button.clicked.connect(self.extract_danbooru_tags)
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self.extract_tags_button)
        tag_layout.addLayout(title_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.generate_prompt_button = QPushButton("프롬프트 생성")
        self.generate_prompt_button.setProperty("naiaRole", "primary")
        self.generate_prompt_button.clicked.connect(self._on_generate_prompt_clicked)
        self.generate_prompt_button.setEnabled(False)

        self.generate_with_image_button = QPushButton("프롬프트+이미지 생성")
        self.generate_with_image_button.setProperty("naiaRole", "primary")
        self.generate_with_image_button.clicked.connect(self._on_generate_with_image_clicked)
        self.generate_with_image_button.setEnabled(False)
        action_row.addWidget(self.generate_prompt_button)
        action_row.addWidget(self.generate_with_image_button)
        tag_layout.addLayout(action_row)

        self.status_label = QLabel()
        self.status_label.setObjectName("NaiaDanbooruStatus")
        self.status_label.setWordWrap(True)
        tag_layout.addWidget(self.status_label)

        self.tag_scroll = QScrollArea()
        self.tag_scroll.setObjectName("NaiaDanbooruTagScroll")
        self.tag_scroll.setWidgetResizable(True)
        self.tag_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tag_content = QWidget()
        tag_content_layout = QVBoxLayout(tag_content)
        tag_content_layout.setContentsMargins(0, 0, 0, 0)
        tag_content_layout.setSpacing(8)

        for key, label in DANBOORU_PRIMARY_TAG_GROUPS:
            group = self._create_tag_group(key, label)
            tag_content_layout.addWidget(group)

        self.general_breakdown_title = QLabel("GENERAL BREAKDOWN · 0")
        self.general_breakdown_title.setObjectName("NaiaDanbooruGeneralTitle")
        tag_content_layout.addWidget(self.general_breakdown_title)

        for key, label in DANBOORU_GENERAL_GROUPS:
            group = self._create_tag_group(f"general:{key}", label)
            tag_content_layout.addWidget(group)

        tag_content_layout.addStretch(1)
        self.tag_scroll.setWidget(tag_content)
        tag_layout.addWidget(self.tag_scroll, 1)

        splitter.addWidget(tag_panel)
        splitter.setSizes([880, 360])
        main_layout.addWidget(splitter, 1)

        self._clear_tag_panel()

        self.back_button.clicked.connect(self.browser.back)
        self.forward_button.clicked.connect(self.browser.forward)
        self.refresh_button.clicked.connect(self.browser.reload)
        self.browser.urlChanged.connect(self.update_address_bar)
        self.browser.loadFinished.connect(self._on_load_finished)
        
        self.update_address_bar(self.browser.url())

    def _create_toolbar_button(self, text):
        button = QPushButton(text)
        button.setProperty("naiaRole", "secondary")
        button.setMinimumHeight(34)
        return button

    def _create_tag_group(self, key, label):
        group = QFrame()
        group.setProperty("naiaRole", "tag-group")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(5)

        title = QLabel(f"{label} · 0")
        title.setProperty("naiaRole", "tag-title")
        body = QLabel("—")
        body.setProperty("naiaRole", "tag-body")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        layout.addWidget(title)
        layout.addWidget(body)
        self._tag_title_labels[key] = title
        self._tag_body_labels[key] = body
        self._tag_group_frames[key] = group
        return group
        
    def setup_selective_storage(self):
        """Danbooru 로그인 정보만 저장하는 선택적 스토리지 설정"""
        try:
            # ✅ 프로필과 페이지를 먼저 생성
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
            
            # ✅ 페이지를 미리 생성해서 인스턴스 변수로 저장 (JS 콘솔 메시지 필터링 적용)
            self.page = SilentWebEnginePage(self.profile)
            
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
            if url.isdigit():
                url = f'https://danbooru.donmai.us/posts/{url}'
            elif '.' in url and ' ' not in url:
                url = 'https://' + url
            else:
                query = url.replace(' ', '+')
                url = f'https://danbooru.donmai.us/posts?tags={query}'
        
        self.load_url(url)
    
    def update_address_bar(self, qurl):
        self.address_bar.setText(qurl.toString())
        
        url_str = qurl.toString()
        post_id = self._post_id_from_url(url_str)
        is_danbooru_post = post_id is not None
        
        self.extract_tags_button.setEnabled(is_danbooru_post)

        if is_danbooru_post:
            self._set_status(f"#{post_id} 포스트 로드 중...", "warning")
        else:
            self._hide_generation_widgets()
            self._clear_tag_panel()

    def _post_id_from_url(self, url):
        match = re.search(DANBOORU_POST_PATTERN, url)
        return int(match.group(1)) if match else None

    def _on_load_finished(self, ok):
        """페이지 로드 후 Danbooru 포스트면 자동으로 태그를 추출합니다."""
        if not ok:
            self._set_status("페이지 로드에 실패했습니다.", "error")
            return

        post_id = self._post_id_from_url(self.browser.url().toString())
        if post_id is None:
            return

        if self._last_auto_extract_post_id == post_id and self.extracted_tags_data:
            return

        self._last_auto_extract_post_id = post_id
        QTimer.singleShot(150, self.extract_danbooru_tags)

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
        post_id = self._post_id_from_url(current_url)
        if post_id is None:
            self._set_status("Danbooru 포스트 페이지가 아닙니다.", "error")
            self._clear_tag_panel()
            return

        self._set_status(f"#{post_id} 태그를 읽는 중...", "warning")
        self.extract_tags_button.setEnabled(False)
        
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
            self._set_status("페이지 데이터를 가져올 수 없습니다.", "error")
            self.extract_tags_button.setEnabled(True)
            return
        
        try:
            # URL에서 ID 추출
            url = page_data['url']
            post_id = self._post_id_from_url(url)
                
            if not post_id:
                self._set_status("포스트 ID를 찾을 수 없습니다.", "error")
                self.extract_tags_button.setEnabled(True)
                return
            
            # HTML에서 태그 추출
            html = page_data['html']
            tags_data = self.parse_danbooru_tags(html, post_id)

            # 결과 표시
            self.display_extracted_tags(tags_data)
            
        except Exception as e:
            self._set_status(f"태그 추출 중 오류 발생: {str(e)}", "error")
            self.extract_tags_button.setEnabled(True)
    
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
                        tags_data[category].append(tag.replace("_", " "))
        
        return tags_data
    
    def display_extracted_tags(self, tags_data):
        """추출된 태그를 UI에 표시"""
        tags_data = self._normalize_extracted_tags(tags_data)
        self.extracted_tags_data = tags_data

        for key, label in DANBOORU_PRIMARY_TAG_GROUPS:
            tags = tags_data.get(key, [])
            self._tag_title_labels[key].setText(f"{label} · {len(tags)}")
            self._tag_body_labels[key].setText(', '.join(tags) if tags else '—')

        self._render_general_breakdown(tags_data.get('general', []))
        self._set_status(f"#{tags_data.get('id')} 태그를 자동으로 읽었습니다.", "success")
        self.extract_tags_button.setEnabled(True)
        self._show_generation_widgets()
        print("🎯 Danbooru 태그 추출 및 표시 완료")

    def _normalize_extracted_tags(self, tags_data):
        normalized = {'id': tags_data.get('id')}

        for key in DANBOORU_DATA_GROUPS:
            seen = set()
            normalized[key] = []
            for tag in tags_data.get(key, []):
                cleaned = tag.replace("_", " ").strip()
                if cleaned and cleaned not in seen:
                    normalized[key].append(cleaned)
                    seen.add(cleaned)

        cs = normalized.get('character', [])
        gs = normalized.get('general', [])
        characteristic_set = set(self.characteristic)
        tags_to_move = [tag for tag in gs if tag in characteristic_set and tag not in cs]
        for tag in tags_to_move:
            cs.append(tag)
            gs.remove(tag)

        return normalized

    def _render_general_breakdown(self, general_tags):
        classified = self._classify_general_tags(general_tags)
        total = sum(len(tags) for tags in classified.values())
        self.general_breakdown_title.setText(f"GENERAL BREAKDOWN · {total}")

        for key, label in DANBOORU_GENERAL_GROUPS:
            frame_key = f"general:{key}"
            tags = classified.get(key, [])
            self._tag_title_labels[frame_key].setText(f"{label} · {len(tags)}")
            self._tag_body_labels[frame_key].setText(', '.join(tags) if tags else '—')
            self._tag_group_frames[frame_key].setVisible(bool(tags))

    def _classify_general_tags(self, general_tags):
        classified = {key: [] for key, _label in DANBOORU_GENERAL_GROUPS}
        fm = self.filter_manager

        for tag in general_tags:
            bucket = self._general_tag_bucket(tag, fm)
            classified[bucket].append(tag)

        return classified

    def _general_tag_bucket(self, tag, fm):
        if PERSON_COUNT_RE.match(tag):
            return 'subject_count'

        if fm is None:
            return 'other'

        if tag in fm.characteristic_list:
            return 'character_features'
        if tag in fm._clothing_event_set:
            return 'clothing_events'
        if tag in fm.clothes_list or fm.get_garment_region(tag):
            return 'clothes'
        if (
            fm.color_list
            and not _is_color_exception(tag)
            and any(color in tag for color in fm.color_list)
        ):
            return 'colors'
        if tag in fm._location_set:
            return 'location_background'
        if tag in fm._expression_set:
            return 'expression'
        if tag in fm._pose_action_set:
            return 'pose_action'
        if tag in fm._object_set:
            return 'objects'
        if tag in fm._meta_set:
            return 'meta_like'
        if fm._valid_tag_whitelist and tag not in fm._valid_tag_whitelist:
            return 'noise'
        return 'other'

    def _load_filter_manager(self):
        global DANBOORU_FILTER_MANAGER_CACHE
        try:
            if DANBOORU_FILTER_MANAGER_CACHE is None:
                with contextlib.redirect_stdout(io.StringIO()):
                    DANBOORU_FILTER_MANAGER_CACHE = FilterDataManager('data')
            return DANBOORU_FILTER_MANAGER_CACHE
        except Exception as e:
            print(f"Filter manager load error: {e}")
            return None

    def _load_list_from_file(self):
        """지정된 파일에서 한 줄에 하나씩 있는 태그를 읽어 리스트로 반환합니다."""
        file_path = os.path.join('data', 'characteristic_list.txt')
        
        if not os.path.exists(file_path):
            print(f"⚠️ 필터 파일 없음: {file_path}")
            return []
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                # 비어있지 않은 라인만 읽어서 앞뒤 공백 제거 후 리스트에 추가
                tags = [line.strip() for line in f if line.strip()]
            return tags
        except Exception as e:
            print(f"❌ 필터 파일 로드 오류 : {e}")
            return []

    def _show_generation_widgets(self):
        """생성 버튼들을 활성화합니다."""
        self.generate_prompt_button.setEnabled(True)
        self.generate_with_image_button.setEnabled(True)

    def _hide_generation_widgets(self):
        """생성 버튼들을 비활성화합니다."""
        self.generate_prompt_button.setEnabled(False)
        self.generate_with_image_button.setEnabled(False)

    def _clear_tag_panel(self):
        self.extracted_tags_data = {}
        for key, label in DANBOORU_PRIMARY_TAG_GROUPS:
            self._tag_title_labels[key].setText(f"{label} · 0")
            self._tag_body_labels[key].setText("—")
        self.general_breakdown_title.setText("GENERAL BREAKDOWN · 0")
        for key, label in DANBOORU_GENERAL_GROUPS:
            frame_key = f"general:{key}"
            self._tag_title_labels[frame_key].setText(f"{label} · 0")
            self._tag_body_labels[frame_key].setText("—")
            self._tag_group_frames[frame_key].hide()
        self._set_status("포스트를 선택하면 자동으로 태그를 읽습니다.", "warning")
        self.extract_tags_button.setEnabled(False)

    def _set_status(self, text, tone="warning"):
        self.status_label.setText(text)
        self.status_label.setProperty("naiaTone", tone)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _on_generate_prompt_clicked(self):
        """프롬프트 생성 버튼 클릭 시 호출"""
        if self.extracted_tags_data:
            print(f"🚀 프롬프트 생성 시그널 발송: {self.extracted_tags_data}")
            self.generate_prompt_requested.emit(self.extracted_tags_data)
        else:
            print("❌ 추출된 태그 데이터가 없습니다.")

    def _on_generate_with_image_clicked(self):
        """프롬프트+이미지 생성 버튼 클릭 시 호출"""
        if self.extracted_tags_data:
            print(f"🚀 프롬프트+이미지 생성 시그널 발송: {self.extracted_tags_data}")
            self.generate_with_image_requested.emit(self.extracted_tags_data)
        else:
            print("❌ 추출된 태그 데이터가 없습니다.")

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
    # 이미 필터링이 적용되어 있으면 스킵
    if isinstance(sys.stderr, ErrorFilter):
        return
    sys.stderr = ErrorFilter()


# 모듈 로드 시 자동으로 에러 필터링 활성화
enable_error_filtering()
