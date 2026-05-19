# 탭 개발 고급 패턴

> **참조**: 이 문서는 [tabs/CLAUDE.md](../CLAUDE.md)의 상세 고급 패턴 레퍼런스입니다.

---

## 목차

1. [패턴 1: QThread 비동기 작업](#패턴-1-qthread-비동기-작업)
2. [패턴 2: Drag & Drop 통합](#패턴-2-drag--drop-통합)
3. [패턴 3: WebEngine JavaScript 통신](#패턴-3-webengine-javascript-통신)
4. [패턴 4: 설정 영속성](#패턴-4-설정-영속성-json-저장로드)

---

## 패턴 1: QThread 비동기 작업

**시나리오**: 이미지 다운로드를 UI 스레드를 차단하지 않고 수행

**PNG Info 탭 예시** (`png_info_tab.py:49-106`)

```python
class ImageDownloader(QObject):
    """비동기 이미지 다운로드 워커"""

    download_finished = pyqtSignal(str)  # temp_path
    download_error = pyqtSignal(str)
    download_progress = pyqtSignal(int)  # 0-100

    def run(self, url: str):
        """백그라운드 스레드에서 실행"""
        try:
            # 1. 다운로드
            response = urllib.request.urlopen(url)
            content_type = response.headers.get('Content-Type', '')

            # 2. 진행률 업데이트
            self.download_progress.emit(50)

            # 3. 임시 파일 저장
            temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            temp_file.write(response.read())
            temp_file.close()

            self.download_progress.emit(100)
            self.download_finished.emit(temp_file.name)

        except Exception as e:
            self.download_error.emit(f"다운로드 오류: {str(e)}")
```

**메인 탭에서 사용**:
```python
def download_and_load_image(self, url: str):
    """비동기 다운로드 시작"""

    # 1. UI 상태 변경
    self.progress_bar.setVisible(True)
    self.set_buttons_enabled(False)

    # 2. 워커 및 스레드 생성
    self.download_thread = QThread()
    self.downloader = ImageDownloader()
    self.downloader.moveToThread(self.download_thread)

    # 3. 시그널 연결
    self.downloader.download_finished.connect(self.on_download_finished)
    self.downloader.download_error.connect(self.on_download_error)
    self.downloader.download_progress.connect(self.on_download_progress)

    # 4. 스레드 시작
    self.download_thread.started.connect(lambda: self.downloader.run(url))
    self.download_thread.finished.connect(self.download_thread.deleteLater)
    self.download_thread.start()

def on_download_finished(self, temp_path: str):
    """다운로드 완료"""
    self.progress_bar.setVisible(False)
    self.load_image_from_path(temp_path)
    self.set_buttons_enabled(True)

    # 스레드 정리
    if self.download_thread:
        self.download_thread.quit()
        self.download_thread.wait()

def on_download_error(self, error_msg: str):
    """다운로드 실패"""
    self.progress_bar.setVisible(False)
    QMessageBox.critical(self, "오류", error_msg)
    self.set_buttons_enabled(True)

    if self.download_thread:
        self.download_thread.quit()
```

---

## 패턴 2: Drag & Drop 통합

**ImageDropArea 패턴** (`png_info_tab.py:1159-1284`)

```python
class ImageDropArea(QLabel):
    """이미지 드래그&드롭 영역"""

    file_dropped = pyqtSignal(str)  # 로컬 파일 경로
    web_url_dropped = pyqtSignal(str)  # 웹 URL

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setText("📷\n\n이미지를 드래그하세요")

    def dragEnterEvent(self, event: QDragEnterEvent):
        """드래그 진입 시 비주얼 피드백"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(f"""
                QLabel {{
                    border: 2px dashed {DARK_COLORS['success']};
                    color: {DARK_COLORS['success']};
                }}
            """)

    def dragLeaveEvent(self, event):
        """드래그 이탈 시 원래 스타일 복원"""
        self.setStyleSheet(f"""
            QLabel {{
                border: 2px dashed {DARK_COLORS['border_light']};
                color: {DARK_COLORS['text_secondary']};
            }}
        """)

    def dropEvent(self, event: QDropEvent):
        """드롭 이벤트 처리"""
        try:
            if event.mimeData().hasUrls():
                url = event.mimeData().urls()[0]

                # 로컬 파일
                if url.isLocalFile():
                    file_path = url.toLocalFile()
                    self.file_dropped.emit(file_path)

                # 웹 URL
                else:
                    url_str = url.toString()
                    self.web_url_dropped.emit(url_str)

        finally:
            self.dragLeaveEvent(event)

    def set_image(self, pixmap: QPixmap):
        """이미지 표시"""
        scaled = pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.setPixmap(scaled)
```

**사용 예시**:
```python
def create_image_panel(self):
    """드롭 영역이 있는 패널"""
    panel = QFrame()
    layout = QVBoxLayout(panel)

    # 드롭 영역
    self.drop_area = ImageDropArea(self)
    self.drop_area.file_dropped.connect(self.load_image_from_path)
    self.drop_area.web_url_dropped.connect(self.download_and_load_image)

    layout.addWidget(self.drop_area)
    return panel
```

---

## 패턴 3: WebEngine JavaScript 통신

**JavaScript 실행 및 결과 수신** (`web_view.py:219-241`)

```python
def extract_danbooru_tags(self):
    """현재 페이지에서 JavaScript로 데이터 추출"""

    js_code = """
    (function() {
        const result = {
            url: window.location.href,
            html: document.documentElement.outerHTML
        };
        return result;
    })();
    """

    # JavaScript 실행 및 결과를 콜백으로 수신
    self.page.runJavaScript(js_code, self.process_page_data)

def process_page_data(self, page_data):
    """JavaScript 결과 처리"""
    if not page_data:
        return

    url = page_data['url']
    html = page_data['html']

    # HTML 파싱
    tags_data = self.parse_danbooru_tags(html, post_id)

    # 결과 표시
    self.display_extracted_tags(tags_data)
```

**HTML 파싱** (`web_view.py:276-318`)

```python
import re

def parse_danbooru_tags(self, html: str, post_id: int) -> dict:
    """정규식으로 HTML 파싱"""

    tags_data = {
        'id': post_id,
        'artist': [],
        'copyright': [],
        'character': [],
        'general': [],
        'meta': []
    }

    categories = {
        'artist': r'<ul class="artist-tag-list">(.*?)</ul>',
        'copyright': r'<ul class="copyright-tag-list">(.*?)</ul>',
        'character': r'<ul class="character-tag-list">(.*?)</ul>',
        'general': r'<ul class="general-tag-list">(.*?)</ul>',
        'meta': r'<ul class="meta-tag-list">(.*?)</ul>'
    }

    for category, pattern in categories.items():
        ul_match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if ul_match:
            ul_content = ul_match.group(1)

            # data-tag-name 속성 추출
            tag_pattern = r'data-tag-name="([^"]*)"'
            tag_matches = re.findall(tag_pattern, ul_content)

            for tag in tag_matches:
                # HTML 엔티티 디코딩
                tag = tag.replace('&amp;', '&')
                tag = tag.replace('&lt;', '<')
                tag = tag.replace('&gt;', '>')

                if tag and tag not in tags_data[category]:
                    tags_data[category].append(tag)

    return tags_data
```

---

## 패턴 4: 설정 영속성 (JSON 저장/로드)

**Settings 탭 패턴** (`setting_tabs.py:54-117`)

```python
class SettingsTabModule(BaseTabModule):
    def __init__(self):
        super().__init__()
        self.settings_data = {}
        self.settings_file = "app_settings.json"

    def load_settings(self):
        """설정 파일 로드"""
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
        """설정 파일 저장"""
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings_data, f, indent=2, ensure_ascii=False)
            print("Settings saved successfully.")
        except Exception as e:
            print(f"Settings save failed: {e}")

    def _get_default_settings(self) -> dict:
        """기본 설정값"""
        return {
            "autocomplete": {"enabled": True},
            "save_directory": {"base_path": "./output"},
            "module_visibility": {},
            "tab_visibility": {},
            "ui": {"theme": "dark", "auto_save": True}
        }

    def get_setting(self, key_path: str, default=None):
        """점 표기법으로 설정 가져오기 (예: 'autocomplete.enabled')"""
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
        """점 표기법으로 설정 저장"""
        keys = key_path.split('.')
        data = self.settings_data
        for key in keys[:-1]:
            if key not in data:
                data[key] = {}
            data = data[key]
        data[keys[-1]] = value
        self.save_settings()
```

**사용 예시**:
```python
# 설정 읽기
autocomplete_enabled = settings_module.get_setting('autocomplete.enabled', True)

# 설정 쓰기
settings_module.set_setting('autocomplete.enabled', False)

# 중첩 설정
settings_module.set_setting('module_visibility.MyModule', False)
```

---

*문서 버전: 1.0*
*생성일: 2025-01-18*
