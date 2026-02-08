# CLAUDE.md — tabs/artist_thumb/

> **목적**: Artist Gallery Window 컴포넌트 개발 가이드. 4x2 그리드 갤러리 윈도우, 아티스트 썸네일 프레임, 관심 작가 토글, 커스텀 태그 생성 기능을 다룹니다.

---

## 목차

1. [개요](#개요)
2. [파일 구조](#파일-구조)
3. [ArtistGalleryWindow](#artistgallerywindow)
4. [ArtistThumbnailFrame](#artistthumbnailframe)
5. [시그널 및 통신](#시그널-및-통신)
6. [키보드/마우스 바인딩](#키보드마우스-바인딩)
7. [통합 방법](#통합-방법)
8. [스타일링](#스타일링)

---

## 개요

### 기능 설명

Artist Gallery Window는 아티스트 썸네일을 4x2 그리드로 표시하여 다음 기능을 제공합니다:

- 🖼️ **썸네일 그리드**: 한 페이지에 8개 아티스트 표시
- ⭐ **관심 작가 토글**: 헤더 클릭으로 관심 작가 등록/해제
- 📋 **작가명 복사**: 클립보드에 작가명 복사
- 🎨 **즉시 생성**: 선택한 작가로 이미지 생성
- 📝 **커스텀 태그 조합**: 여러 작가 태그 조합하여 생성
- 📄 **페이지네이션**: 키보드/마우스 휠로 페이지 이동

### 아키텍처

```
artist_thumb_tab.py
    ↓ opens
ArtistGalleryWindow (gallery_window.py)
    ↓ contains (8개)
ArtistThumbnailFrame (artist_frame.py)
```

---

## 파일 구조

```
tabs/artist_thumb/
├── __init__.py           # 패키지 초기화
├── gallery_window.py     # ArtistGalleryWindow 클래스
├── artist_frame.py       # ArtistThumbnailFrame 클래스
├── CLAUDE.md             # 이 문서
└── SRS_ARTIST_GALLERY_WINDOW.md  # 기능 요구사항 명세서
```

---

## ArtistGalleryWindow

**파일**: `gallery_window.py`

### 클래스 개요

```python
class ArtistGalleryWindow(QDialog):
    """4x2 그리드 갤러리 윈도우"""

    # 상수
    COLUMNS = 4
    ROWS = 2
    ITEMS_PER_PAGE = 8

    # 시그널
    favorite_toggled = pyqtSignal(str, bool)      # (artist_name, is_favorite)
    artist_clicked = pyqtSignal(str)               # artist_name
    generate_requested = pyqtSignal(str)           # artist_name
    custom_generate_requested = pyqtSignal(str)    # custom_tags
```

### 생성자 파라미터

| 파라미터 | 타입 | 설명 |
|----------|------|------|
| `artist_data` | `dict` | `{artist_name: [base64_thumbnail, ...]}` |
| `artist_list` | `list` | 정렬된 아티스트 이름 목록 |
| `favorite_artists` | `list` | 관심 작가 목록 |
| `current_mode` | `str` | 현재 API 모드 (타이틀에 표시) |
| `parent` | `QWidget` | 부모 위젯 |
| `title_suffix` | `str` | 윈도우 타이틀 접미사 (필터 옵션 표시용, 기본값: "") |

### 주요 메서드

```python
def _load_page(self, page: int):
    """지정된 페이지 로드"""

def _prev_page(self):
    """이전 페이지로 이동"""

def _next_page(self):
    """다음 페이지로 이동"""

def _jump_to_page(self):
    """스핀박스 값으로 페이지 이동"""

def _on_custom_generate(self):
    """커스텀 태그로 생성 요청"""

def update_favorite_status(self, artist_name: str, is_favorite: bool):
    """외부에서 관심 작가 상태 동기화"""
```

### 레이아웃 구조

```
┌─────────────────────────────────────────────────────────────┐
│                     Artist Gallery - {mode}                 │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │[artist]★ │  │[artist]  │  │[artist]★ │  │[artist]  │    │
│  │ [thumb]  │  │ [thumb]  │  │ [thumb]  │  │ [thumb]  │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │[artist]  │  │[artist]★ │  │[artist]  │  │[artist]★ │    │
│  │ [thumb]  │  │ [thumb]  │  │ [thumb]  │  │ [thumb]  │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
├─────────────────────────────────────────────────────────────┤
│ [<] 1/245 [>] │ 작가 태그 조합: [________] [생성] │ 이동: [__][이동] │
└─────────────────────────────────────────────────────────────┘
```

---

## ArtistThumbnailFrame

**파일**: `artist_frame.py`

### 클래스 개요

```python
class ArtistThumbnailFrame(QFrame):
    """개별 아티스트 썸네일 프레임"""

    # 시그널
    favorite_toggled = pyqtSignal(str, bool)  # (artist_name, is_favorite)
    artist_clicked = pyqtSignal(str)          # artist_name
    generate_requested = pyqtSignal(str)      # artist_name
```

### 생성자 파라미터

| 파라미터 | 타입 | 설명 |
|----------|------|------|
| `artist_name` | `str` | 아티스트 이름 |
| `thumbnail_data` | `str` | Base64 인코딩된 썸네일 |
| `is_favorite` | `bool` | 관심 작가 여부 |
| `parent` | `QWidget` | 부모 위젯 |

### 헤더 레이아웃 (5:1:1 비율)

```
┌─────────────────────────────────────┐
│ [artist_name]  ★  │ 📋 │ 🎨 │
│      (5)          │(1) │(1) │
└─────────────────────────────────────┘
```

| 요소 | 비율 | 동작 |
|------|------|------|
| 작가명 버튼 | 5 | 클릭 시 관심 작가 토글 |
| ★ 별표 | - | 관심 작가 상태 표시 |
| 📋 복사 버튼 | 1 | 작가명 클립보드 복사 |
| 🎨 생성 버튼 | 1 | 해당 작가로 생성 요청 |

### 관심 작가 스타일

| 상태 | 배경색 | 별표 |
|------|--------|------|
| 관심 작가 | `#2d5a2d` (녹색) | `#ffd700` (금색) ★ |
| 비관심 | `bg_primary` | 회색 ☆ |

### 주요 메서드

```python
def _load_thumbnail(self):
    """Base64 썸네일 로드 및 표시"""

def _update_favorite_style(self):
    """관심 작가 상태에 따른 스타일 업데이트"""

def set_favorite(self, is_favorite: bool):
    """외부에서 관심 작가 상태 설정"""

def set_uniform_size(self, width: int, height: int):
    """그리드 균등 분배를 위한 크기 설정"""
```

---

## 시그널 및 통신

### 시그널 흐름

```
ArtistThumbnailFrame
    │
    ├─ favorite_toggled ──→ ArtistGalleryWindow ──→ artist_thumb_tab.py
    │                           ↓
    │                       favorite_artists 업데이트
    │                       _save_favorite_artists()
    │
    ├─ artist_clicked ────→ ArtistGalleryWindow ──→ artist_thumb_tab.py
    │                                                  ↓
    │                                              listbox 선택
    │
    └─ generate_requested ─→ ArtistGalleryWindow ──→ artist_thumb_tab.py
                                                       ↓
                                                   _on_generate_clicked()

ArtistGalleryWindow (하단바)
    │
    └─ custom_generate_requested ─→ artist_thumb_tab.py
                                       ↓
                                   positive_prompt 덮어쓰기
                                   _on_generate_clicked()
```

### artist_thumb_tab.py 연결 코드

```python
def _open_gallery_window(self):
    from tabs.artist_thumb.gallery_window import ArtistGalleryWindow

    self.gallery_window = ArtistGalleryWindow(
        artist_data=self.artist_data,
        artist_list=artist_list,
        favorite_artists=self.favorite_artists,
        current_mode=self.current_mode,
        parent=self.widget
    )

    # 시그널 연결
    self.gallery_window.favorite_toggled.connect(self._on_gallery_favorite_toggled)
    self.gallery_window.artist_clicked.connect(self._on_gallery_artist_clicked)
    self.gallery_window.generate_requested.connect(self._on_gallery_generate_requested)
    self.gallery_window.custom_generate_requested.connect(self._on_gallery_custom_generate_requested)

    self.gallery_window.show()

def _on_gallery_custom_generate_requested(self, custom_tags: str):
    """커스텀 태그로 생성"""
    self.positive_prompt.setPlainText(custom_tags)
    QTimer.singleShot(100, self._on_generate_clicked)
```

---

## 키보드/마우스 바인딩

### 키보드 단축키 (QShortcut)

| 키 | 동작 |
|----|------|
| `←` / `A` | 이전 페이지 |
| `→` / `D` | 다음 페이지 |
| `Home` | 첫 페이지 |
| `End` | 마지막 페이지 |
| `Escape` | **블록** (창 닫지 않음) |

### 마우스 바인딩

| 동작 | 효과 |
|------|------|
| 휠 위 | 이전 페이지 |
| 휠 아래 | 다음 페이지 |
| 썸네일 클릭 | 아티스트 선택 (메인 탭) |
| 헤더 클릭 | 관심 작가 토글 |

### ESC 키 블록 처리

```python
def keyPressEvent(self, event):
    """ESC 키 블록"""
    if event.key() == Qt.Key.Key_Escape:
        event.ignore()
        return
    super().keyPressEvent(event)
```

---

## 통합 방법

### 1. 갤러리 버튼 추가 (artist_thumb_tab.py)

```python
# 갤러리 버튼 생성
self.gallery_button = QPushButton("🖼️ 갤러리 보기")
self.gallery_button.clicked.connect(self._open_gallery_window)
layout.addWidget(self.gallery_button)
```

### 2. 갤러리 윈도우 열기 (필터 옵션 지원)

```python
def _open_gallery_window(self):
    """갤러리 윈도우 열기 - filter_combo 옵션에 따라 다른 아티스트 리스트 표시"""
    from tabs.artist_thumb.gallery_window import ArtistGalleryWindow

    # 현재 필터 옵션 확인
    current_filter = self.filter_combo.currentText()

    # 필터에 따른 아티스트 리스트 생성
    if current_filter == "관심 작가 보기":
        base_list = [a for a in self.favorite_artists if a in self.artist_data and a in artist_dict]
        window_title_suffix = " (관심 작가)"
    elif current_filter == "제외 작가 보기":
        base_list = [a for a in self.banned_artists if a in self.artist_data and a in artist_dict]
        window_title_suffix = " (제외 작가)"
    elif current_filter not in ["전체 목록 보기", "+ 분류 그룹 추가"]:
        # 커스텀 필터 파일에서 아티스트 로드
        filter_file = os.path.join('artist_thumb', f"{current_filter}.txt")
        custom_artists = []
        if os.path.exists(filter_file):
            with open(filter_file, 'r', encoding='utf-8') as f:
                custom_artists = [line.strip() for line in f if line.strip()]
        base_list = [a for a in custom_artists if a in self.artist_data and a in artist_dict]
        window_title_suffix = f" ({current_filter})"
    else:
        base_list = [key for key in self.artist_data if key in artist_dict]
        window_title_suffix = ""

    # 가중치 기준 내림차순 정렬
    artist_list = sorted(base_list, key=lambda k: artist_dict.get(k, 0), reverse=True)

    self.gallery_window = ArtistGalleryWindow(
        artist_data=self.artist_data,
        artist_list=artist_list,
        favorite_artists=self.favorite_artists,
        current_mode=self.current_mode,
        parent=self.widget,
        title_suffix=window_title_suffix
    )

    # 시그널 연결
    self.gallery_window.favorite_toggled.connect(self._on_gallery_favorite_toggled)
    self.gallery_window.artist_clicked.connect(self._on_gallery_artist_clicked)
    self.gallery_window.generate_requested.connect(self._on_gallery_generate_requested)
    self.gallery_window.custom_generate_requested.connect(self._on_gallery_custom_generate_requested)

    self.gallery_window.show()
```

### 3. 콜백 메서드 구현

```python
def _on_gallery_favorite_toggled(self, artist_name: str, is_favorite: bool):
    """관심 작가 토글 동기화"""
    if is_favorite and artist_name not in self.favorite_artists:
        self.favorite_artists.append(artist_name)
    elif not is_favorite and artist_name in self.favorite_artists:
        self.favorite_artists.remove(artist_name)
    self._save_favorite_artists()

def _on_gallery_artist_clicked(self, artist_name: str):
    """아티스트 선택 → 메인 리스트에서 선택"""
    for i in range(self.artist_listbox.count()):
        if self.artist_listbox.item(i).text() == artist_name:
            self.artist_listbox.setCurrentRow(i)
            break

def _on_gallery_generate_requested(self, artist_name: str):
    """아티스트 선택 후 생성"""
    self._on_gallery_artist_clicked(artist_name)
    QTimer.singleShot(100, self._on_generate_clicked)

def _on_gallery_custom_generate_requested(self, custom_tags: str):
    """커스텀 태그로 생성"""
    self.positive_prompt.setPlainText(custom_tags)
    QTimer.singleShot(100, self._on_generate_clicked)
```

---

## 스타일링

### 사용 컴포넌트

```python
from ui.theme import DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
```

### 주요 색상

| 용도 | 키 | 값 |
|------|----|----|
| 배경 | `bg_primary` | 기본 배경 |
| 프레임 배경 | `bg_secondary` | 프레임 배경 |
| 버튼 배경 | `bg_tertiary` | 버튼 배경 |
| 테두리 | `border` | 테두리 |
| 텍스트 | `text_primary` | 기본 텍스트 |
| 보조 텍스트 | `text_secondary` | 보조 텍스트 |
| 강조 | `accent_blue` | 생성 버튼 |
| 관심 작가 | `#2d5a2d` | 녹색 배경 |
| 별표 | `#ffd700` | 금색 |

### 동적 스케일링

```python
# 크기
bar_height = get_scaled_size(66)
btn_height = get_scaled_size(36)
textedit_height = get_scaled_size(50)

# 폰트
font_size = get_scaled_font_size(14)
```

---

*문서 버전: 1.0*
*최종 업데이트: 2026-01-10*
*담당 영역: tabs/artist_thumb/ 디렉터리*
