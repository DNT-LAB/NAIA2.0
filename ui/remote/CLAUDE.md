# ui/remote/ - RemoteWindow 서브모듈

> **목적**: RemoteWindow의 탭별 코드를 Mixin 패턴으로 분리하여 유지보수성 향상

---

## 목차

1. [개요](#개요)
2. [디렉터리 구조](#디렉터리-구조)
3. [Mixin 패턴 설명](#mixin-패턴-설명)
4. [파일별 상세](#파일별-상세)
   - [quick_search_tab.py](#quick_search_tabpy) 🆕
   - [event_tab.py](#event_tabpy)
   - [instant_wc_tab.py](#instant_wc_tabpy)
   - [char_prompt_tab.py](#char_prompt_tabpy)
   - [char_ref_tab.py](#char_ref_tabpy)
   - [preset_tab.py](#preset_tabpy)
5. [리팩토링 가이드](#리팩토링-가이드)
6. [주의사항](#주의사항)

---

## 개요

### 리팩토링 배경

`ui/remote_window.py`가 5000줄 이상으로 커지면서:
- 코드 탐색이 어려움
- 하나의 탭 수정 시 다른 탭에 영향 우려
- 테스트 및 디버깅 복잡도 증가

### 해결 방법: Mixin 패턴

Python의 다중 상속을 활용하여 탭별 코드를 별도 클래스로 분리:

```python
# 기존
class RemoteWindow(QMainWindow):
    # 5000+ 줄의 모든 코드

# 리팩토링 후
class RemoteWindow(QMainWindow, EventTabMixin, InstantWcTabMixin):
    # 핵심 로직만 유지
    # 탭별 메서드는 Mixin에서 상속
```

### 효과

| 항목 | 이전 | 이후 |
|------|------|------|
| remote_window.py 줄 수 | ~5000줄+ | **~702줄** |
| 퀵 서치 탭 코드 | remote_window.py 내 | **quick_search_tab.py (~1310줄)** 🆕 |
| 이벤트 탭 코드 | remote_window.py 내 | event_tab.py (~1100줄) |
| INST.WC 탭 코드 | remote_window.py 내 | instant_wc_tab.py (~900줄) |
| 캐릭터 프롬프트 탭 코드 | remote_window.py 내 | char_prompt_tab.py (~1556줄) |
| 캐릭터 레퍼런스 탭 코드 | remote_window.py 내 | char_ref_tab.py (~1363줄) |
| 프리셋 탭 코드 | remote_window.py 내 | preset_tab.py (~939줄) |
| 탭 추가 시 | remote_window.py 수정 | 새 Mixin 파일 생성 |

> 📉 **총 코드 감소**: remote_window.py 5000줄+ → 702줄 (약 86% 감소)

---

## 디렉터리 구조

```
ui/remote/
├── __init__.py           # 모듈 export 정의
├── quick_search_tab.py   # 🆕 퀵 서치 탭 Mixin (태그 기반 랜덤 프롬프트 생성)
├── event_tab.py          # 이벤트 탭 Mixin
├── instant_wc_tab.py     # 인스턴트 와일드카드 탭 Mixin
├── char_prompt_tab.py    # 캐릭터 프롬프트 탭 Mixin
├── char_ref_tab.py       # 캐릭터 레퍼런스 탭 Mixin
├── preset_tab.py         # 프리셋 탭 Mixin
└── CLAUDE.md             # 본 문서
```

### __init__.py

```python
from .event_tab import EventTabMixin, EventItemWidget
from .instant_wc_tab import InstantWcTabMixin, WildcardItemWidget
from .char_prompt_tab import (
    CharPromptTabMixin, CharacterPromptFavoriteItemWidget,
    CHAR_PROMPT_FAVORITES_DIR, CHAR_PROMPT_FAVORITES_JSON, CHAR_PROMPT_FOLDERS_JSON,
    CHAR_PROMPT_THUMB_WIDTH, CHAR_PROMPT_THUMB_HEIGHT,
    CHAR_PROMPT_MANAGE_THUMB_WIDTH, CHAR_PROMPT_MANAGE_THUMB_HEIGHT
)
from .char_ref_tab import (
    CharRefTabMixin, CharRefFavoriteItemWidget,
    CHAR_REF_FAVORITES_DIR, CHAR_REF_FAVORITES_JSON, CHAR_REF_FOLDERS_JSON,
    FAVORITE_THUMB_WIDTH, FAVORITE_THUMB_HEIGHT,
    PREVIEW_THUMB_WIDTH, PREVIEW_THUMB_HEIGHT, THUMB_ASPECT_RATIO
)
from .preset_tab import (
    PresetTabMixin, PresetFavoriteItemWidget,
    PRESET_FAVORITES_DIR, PRESET_FAVORITES_JSON,
    PRESET_THUMB_WIDTH, PRESET_THUMB_HEIGHT,
    PRESET_PREVIEW_WIDTH, PRESET_PREVIEW_HEIGHT, PRESET_THUMB_ASPECT_RATIO
)

__all__ = [
    'EventTabMixin', 'EventItemWidget',
    'InstantWcTabMixin', 'WildcardItemWidget',
    'CharPromptTabMixin', 'CharacterPromptFavoriteItemWidget',
    'CharRefTabMixin', 'CharRefFavoriteItemWidget',
    'PresetTabMixin', 'PresetFavoriteItemWidget',
    # Constants
    'CHAR_PROMPT_FAVORITES_DIR', 'CHAR_PROMPT_FAVORITES_JSON', 'CHAR_PROMPT_FOLDERS_JSON',
    'CHAR_PROMPT_THUMB_WIDTH', 'CHAR_PROMPT_THUMB_HEIGHT',
    'CHAR_PROMPT_MANAGE_THUMB_WIDTH', 'CHAR_PROMPT_MANAGE_THUMB_HEIGHT',
    'CHAR_REF_FAVORITES_DIR', 'CHAR_REF_FAVORITES_JSON', 'CHAR_REF_FOLDERS_JSON',
    'FAVORITE_THUMB_WIDTH', 'FAVORITE_THUMB_HEIGHT',
    'PREVIEW_THUMB_WIDTH', 'PREVIEW_THUMB_HEIGHT', 'THUMB_ASPECT_RATIO',
    'PRESET_FAVORITES_DIR', 'PRESET_FAVORITES_JSON',
    'PRESET_THUMB_WIDTH', 'PRESET_THUMB_HEIGHT',
    'PRESET_PREVIEW_WIDTH', 'PRESET_PREVIEW_HEIGHT', 'PRESET_THUMB_ASPECT_RATIO'
]
```

---

## Mixin 패턴 설명

### Mixin이란?

Mixin은 다중 상속을 통해 클래스에 기능을 추가하는 패턴입니다:
- 독립적으로 인스턴스화하지 않음
- 다른 클래스와 함께 상속되어 기능 제공
- `self`를 통해 호스트 클래스의 속성/메서드에 접근

### 상속 순서

```python
class RemoteWindow(QMainWindow, QuickSearchTabMixin, EventTabMixin, InstantWcTabMixin, CharPromptTabMixin, CharRefTabMixin, PresetTabMixin):
```

- **QMainWindow**: 기본 클래스 (가장 먼저)
- **QuickSearchTabMixin**: 🆕 퀵 서치 탭 기능
- **EventTabMixin**: 이벤트 탭 기능
- **InstantWcTabMixin**: INST.WC 탭 기능
- **CharPromptTabMixin**: 캐릭터 프롬프트 탭 기능
- **CharRefTabMixin**: 캐릭터 레퍼런스 탭 기능
- **PresetTabMixin**: 프리셋 탭 기능

Python MRO(Method Resolution Order)에 따라 왼쪽에서 오른쪽으로 메서드 탐색

### Mixin 데이터 초기화

RemoteWindow의 `__init__`에서 각 Mixin의 데이터 초기화 메서드를 호출해야 함:

```python
def __init__(self, parent_app, ...):
    super().__init__()
    # ... 기본 초기화 ...

    # Mixin 데이터 초기화
    self._init_quick_search_data()  # QuickSearchTabMixin 🆕
    self._init_char_ref_data()      # CharRefTabMixin
    self._init_char_prompt_data()   # CharPromptTabMixin
    self._init_preset_data()        # PresetTabMixin
```

### self 사용

Mixin 내에서 `self`는 호스트 클래스(RemoteWindow)의 인스턴스를 가리킴:

```python
# instant_wc_tab.py 내부
class InstantWcTabMixin:
    def _get_wc_module(self):
        # self는 RemoteWindow 인스턴스
        return self.instant_wc_module  # RemoteWindow의 속성

    def _show_warning(self, title, message):
        # RemoteWindow의 메서드 호출
        QMessageBox.warning(self, title, message)
```

---

## 파일별 상세

### quick_search_tab.py 🆕

**클래스**: `QuickSearchTabMixin`, `QsPreviewPopup`, `SinglePartitionStore`, `FlowLayout`, `PartitionDataDownloadWorker`

**상수**:
```python
QUICK_SEARCH_DIR = Path("data/quick_search")
PARTITION_METADATA_FILE = QUICK_SEARCH_DIR / "partition_metadata.json"

# Person 선택 관련 상수
PERSON_CATEGORIES = ["none", "1girl", "2girls", "3girls", "4+girls", "1boy", "2boys", "3boys", "4+boys", "1other", "2others", "3others", "4+others", "6+girls", "6+boys", "6+others"]
PERSON_LABELS = {"none": "None", "1girl": "1 Girl", "2girls": "2 Girls", ...}
PERSON_AUTO_TAGS = {
    "1girl": ["solo", "1girl"],
    "2girls": ["2girls", "multiple_girls", "duo"],
    ...
}
```

**주요 클래스 설명**:

- **QuickSearchTabMixin**: 퀵 서치 탭의 메인 Mixin 클래스
- **QsPreviewPopup**: 프롬프트 미리보기 팝업 (클릭 시 표시, 외부 클릭으로 닫힘)
- **SinglePartitionStore**: 단일 파티션 데이터 캐싱 (메모리 효율성)
- **FlowLayout**: 태그 버튼용 유동 레이아웃
- **PartitionDataDownloadWorker**: 파티션 데이터 다운로드 워커 (QThread)

**QuickSearchTabMixin 주요 메서드**:
```python
# 데이터 초기화 (반드시 __init__에서 호출)
def _init_quick_search_data(self)

# UI 생성
def _create_quick_search_tab(self, parent_tabs: QTabWidget)
def _create_qs_filter_section(self) -> QWidget      # Rating/Person 필터 UI (접이식)
def _create_qs_include_section(self) -> QWidget     # Include 태그 섹션
def _create_qs_exclude_section(self) -> QWidget     # Exclude 태그 섹션
def _create_qs_tag_item(self, tag: str, freq: int) -> QPushButton  # 태그 버튼 생성

# 태그 리스트 관리
def _refresh_qs_tag_list(self)                      # 추천 태그 새로고침
def _on_qs_page_changed(self, page: int)            # 페이지 변경 처리
def _on_qs_tag_clicked(self, tag: str, freq: int, is_include: bool)  # 태그 클릭

# 필터 관련
def _on_qs_rating_changed(self)                     # Rating 변경 시 이벤트 수 갱신
def _on_qs_person_changed(self)                     # Person 변경 시 이벤트 수 갱신
def _update_qs_matching_event_count(self)           # 매칭 이벤트 수 라벨 업데이트
def _get_matching_event_count(self) -> int          # 현재 필터 조건의 매칭 수 계산

# 프롬프트 생성
def _on_qs_generate_clicked(self)                   # 생성 버튼 클릭
def _generate_qs_random_prompt(self) -> tuple[str, str]  # 랜덤 프롬프트 생성

# 미리보기 팝업
def _on_qs_preview_clicked(self)                    # 미리보기 버튼 클릭
def _show_qs_preview_popup(self, prompt: str, negative: str)  # 팝업 표시

# 데이터 로딩
def _load_partition_data(self, partition_key: str)  # 파티션 데이터 로딩
def _ensure_partition_data_downloaded(self)         # 다운로드 확인/시작
```

**UI 구조**:
```
Quick Search Tab
├── Filter Section (CollapsibleBox)
│   ├── Rating Selection (체크박스: general, sensitive, questionable, explicit)
│   └── Person Selection (체크박스: 1girl, 2girls, 1boy, etc.)
│       └── 매칭 이벤트 수 라벨 (동적 업데이트)
├── Include Tags Section
│   ├── 검색 입력창
│   └── 태그 플로우 레이아웃
├── Exclude Tags Section
│   ├── 검색 입력창
│   └── 태그 플로우 레이아웃
├── Recommended Tags Section
│   ├── 정렬 옵션 (빈도순/알파벳순)
│   ├── 3열 그리드 태그 버튼 (균등 너비)
│   └── 페이지네이션
└── Action Buttons
    ├── 미리보기 버튼
    └── 생성 버튼
```

**특징**:
- **EZMode STEP4 스타일 태그 버튼**: 빈도 표시, 클릭으로 Include/Exclude 추가
- **3열 균등 너비 그리드**: `setColumnStretch(0, 1), setColumnStretch(1, 1), setColumnStretch(2, 1)`
- **동적 필터링**: Rating/Person 선택 시 실시간 매칭 이벤트 수 업데이트
- **미리보기 팝업**: 생성될 프롬프트 미리보기, 외부 클릭으로 자동 닫힘
- **파티션 기반 데이터**: 대용량 태그 데이터를 파티션으로 분할 관리

**QsPreviewPopup 클래스**:
```python
class QsPreviewPopup(QFrame):
    """프롬프트 미리보기 팝업 위젯"""
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        # 외부 클릭 감지를 위한 이벤트 필터 설치
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event):
        """외부 클릭 감지 - 팝업 외부 클릭 시 닫기"""
        if event.type() == QEvent.Type.MouseButtonPress:
            if not self.geometry().contains(event.globalPosition().toPoint()):
                self.close()
                return True
        return super().eventFilter(obj, event)
```

---

### event_tab.py

**클래스**: `EventTabMixin`, `EventItemWidget`

**상수**:
```python
EVENT_THUMB_WIDTH = 120
EVENT_THUMB_HEIGHT = 167  # 368:512 비율 유지
```

**EventItemWidget 시그널**:
```python
instant_generate_requested = pyqtSignal(str)    # event_id
add_to_queue_requested = pyqtSignal(str)        # event_id
delete_requested = pyqtSignal(str)              # event_id
edit_requested = pyqtSignal(str, str)           # event_id, new_general
heart_changed = pyqtSignal(str, int)            # event_id, new_heart
rating_changed = pyqtSignal(str, str)           # event_id, new_rating
```

**EventTabMixin 주요 메서드**:
```python
# UI 생성
def _create_event_subtab(self, parent_tabs: QTabWidget)

# 데이터 관리
def _load_events(self)
def _save_events(self)
def _update_events_list(self)

# 필터링
def _on_event_search(self)
def _on_event_depth_search(self)
def _on_event_search_reset(self)

# 대기열
def _on_event_queue_all(self)
def _on_event_queue_clear(self)
def _on_event_generate_start(self)
def _on_event_instant_generate(self, event_id: str)

# 아이템 액션
def _on_event_add_to_queue(self, event_id: str)
def _on_event_delete(self, event_id: str)
def _on_event_edit_save(self, event_id: str, new_general: str)
def _on_event_heart_changed(self, event_id: str, new_heart: int)
def _on_event_rating_changed(self, event_id: str, new_rating: str)
```

### instant_wc_tab.py

**클래스**: `InstantWcTabMixin`, `WildcardItemWidget`

**상수**:
```python
WC_THUMB_WIDTH = 120
WC_THUMB_HEIGHT = 167  # 368:512 비율 유지
```

**WildcardItemWidget 시그널**:
```python
instant_generate_requested = pyqtSignal(str, str)  # file_key, item_key
add_to_queue_requested = pyqtSignal(str, str)      # file_key, item_key
delete_requested = pyqtSignal(str, str)            # file_key, item_key
edit_requested = pyqtSignal(str, str, str)         # file_key, item_key, new_value
heart_changed = pyqtSignal(str, str, int)          # file_key, item_key, new_heart
clip_requested = pyqtSignal(str, str)              # file_key, item_key
```

**InstantWcTabMixin 주요 메서드**:
```python
# UI 생성
def _create_instant_wc_subtab(self, parent_tabs: QTabWidget)

# 모듈 참조
def _get_wc_module(self)

# 리스트 관리
def _update_wc_list(self)
def _update_wc_file_combo(self)

# 메타데이터 (하트)
def _load_wc_metadata(self)
def _save_wc_metadata(self)
def _get_wc_heart(self, file_key: str, item_key: str) -> int
def _set_wc_heart(self, file_key: str, item_key: str, value: int)

# 필터링
def _on_wc_file_changed(self, text: str)
def _on_wc_search(self)
def _on_wc_depth_search(self)
def _on_wc_depth_reset(self)
def _on_wc_search_reset(self)

# 대기열
def _on_wc_queue_all(self)
def _on_wc_queue_clear(self)
def _update_wc_queue_label(self)
def _on_wc_generate_start(self)

# 아이템 액션
def _on_wc_instant_generate(self, file_key: str, item_key: str)
def _on_wc_add_to_queue(self, file_key: str, item_key: str)
def _on_wc_delete(self, file_key: str, item_key: str)
def _on_wc_edit_save(self, file_key: str, item_key: str, new_value: str)
def _on_wc_heart_changed(self, file_key: str, item_key: str, new_value: int)
def _on_wc_clip_image(self, file_key: str, item_key: str)
```

### char_prompt_tab.py 🆕

**클래스**: `CharPromptTabMixin`, `CharacterPromptFavoriteItemWidget`

**상수**:
```python
CHAR_PROMPT_FAVORITES_DIR = Path("save/character_prompt_favorites")
CHAR_PROMPT_FAVORITES_JSON = CHAR_PROMPT_FAVORITES_DIR / "favorites.json"
CHAR_PROMPT_FOLDERS_JSON = CHAR_PROMPT_FAVORITES_DIR / "folders.json"
CHAR_PROMPT_THUMB_WIDTH = 144
CHAR_PROMPT_THUMB_HEIGHT = 200
CHAR_PROMPT_MANAGE_THUMB_WIDTH = 150
CHAR_PROMPT_MANAGE_THUMB_HEIGHT = 208
```

**CharacterPromptFavoriteItemWidget 시그널**:
```python
apply_requested = pyqtSignal(str, str)            # name, prompt
delete_requested = pyqtSignal(str)                # name
edit_requested = pyqtSignal(str, str, str, str)   # name, prompt, uc, thumbnail
queue_requested = pyqtSignal(str, str)            # name, prompt
```

**CharPromptTabMixin 주요 메서드**:
```python
# 데이터 초기화 (반드시 __init__에서 호출)
def _init_char_prompt_data(self)

# UI 생성
def _create_char_prompt_subtab(self, parent_tabs: QTabWidget)

# 데이터 관리
def _load_char_prompt_favorites(self)
def _save_char_prompt_favorites(self)
def _load_char_prompt_folders(self)
def _save_char_prompt_folders(self)

# 리스트 관리
def _update_char_prompt_favorites_list(self)
def _on_char_prompt_folder_changed(self, folder_name: str)

# 폴더 관리
def _on_add_char_prompt_folder(self)
def _on_rename_char_prompt_folder(self)
def _on_delete_char_prompt_folder(self)

# 아이템 액션
def _on_char_prompt_apply(self, name: str, prompt: str)
def _on_char_prompt_delete(self, name: str)
def _on_char_prompt_edit(self, name: str, prompt: str, uc: str, thumbnail: str)
def _on_char_prompt_queue(self, name: str, prompt: str)

# 관리 다이얼로그
def _on_open_char_prompt_manage_dialog(self)
def _open_char_prompt_edit_dialog(self, favorite: dict)
def _add_new_char_prompt_favorite(self)
```

### char_ref_tab.py 🆕

**클래스**: `CharRefTabMixin`, `CharRefFavoriteItemWidget`

**상수**:
```python
CHAR_REF_FAVORITES_DIR = Path("save/character_reference")
CHAR_REF_FAVORITES_JSON = CHAR_REF_FAVORITES_DIR / "favorites.json"
CHAR_REF_FOLDERS_JSON = CHAR_REF_FAVORITES_DIR / "favorite_folders.json"
FAVORITE_THUMB_WIDTH = 120
FAVORITE_THUMB_HEIGHT = 167
PREVIEW_THUMB_WIDTH = 140
PREVIEW_THUMB_HEIGHT = 195
THUMB_ASPECT_RATIO = 368 / 512  # NAI 기본 이미지 비율
```

**CharRefFavoriteItemWidget 시그널**:
```python
apply_requested = pyqtSignal(dict)     # favorite 데이터
delete_requested = pyqtSignal(str)     # file_hash
edit_requested = pyqtSignal(dict)      # favorite 데이터
queue_requested = pyqtSignal(dict)     # favorite 데이터
```

**CharRefTabMixin 주요 메서드**:
```python
# 데이터 초기화 (반드시 __init__에서 호출)
def _init_char_ref_data(self)

# UI 생성
def _create_char_ref_subtab(self, parent_tabs: QTabWidget)

# 데이터 관리
def _load_char_ref_favorites(self)      # JSON 포맷 호환성 처리 포함
def _save_char_ref_favorites(self)
def _load_char_ref_folders(self)
def _save_char_ref_folders(self)

# 리스트 관리
def _update_char_ref_favorites_list(self)
def _on_char_ref_folder_changed(self, folder_name: str)

# 폴더 관리
def _on_add_char_ref_folder(self)
def _on_rename_char_ref_folder(self)
def _on_delete_char_ref_folder(self)

# 아이템 액션
def _on_char_ref_apply(self, favorite: dict)
def _on_char_ref_delete(self, file_hash: str)
def _on_char_ref_edit(self, favorite: dict)
def _on_char_ref_queue(self, favorite: dict)

# 이미지 관리
def _get_char_ref_image_path(self, file_hash: str) -> Path | None
def _get_char_ref_thumbnail_path(self, file_hash: str) -> Path | None
def _create_char_ref_thumbnail(self, file_hash: str)

# 관리 다이얼로그
def _on_open_char_ref_manage_dialog(self)
def _open_char_ref_edit_dialog(self, favorite: dict)
def _add_new_char_ref_favorite(self)
```

**⚠️ JSON 포맷 호환성 (중요)**:

`char_ref_tab.py`는 기존 데이터와의 하위 호환성을 위해 두 가지 JSON 포맷을 지원:

```python
# _load_char_ref_favorites() 내부
if isinstance(data, list):
    # 기존 포맷: 직접 리스트 [{"file_hash": ..., "name": ...}, ...]
    self.char_ref_favorites = data
else:
    # 새 포맷 (또는 다른 탭과 통일): {"favorites": [...]}
    self.char_ref_favorites = data.get("favorites", [])

# _save_char_ref_favorites() 내부
# 기존 호환성 유지: 직접 리스트로 저장
json.dump(self.char_ref_favorites, f, ...)
```

### preset_tab.py 🆕

**클래스**: `PresetTabMixin`, `PresetFavoriteItemWidget`

**상수**:
```python
PRESET_FAVORITES_DIR = Path("save/presets/favorites")
PRESET_FAVORITES_JSON = Path("save/presets/favorites.json")
PRESET_THUMB_WIDTH = 120
PRESET_THUMB_HEIGHT = 167
PRESET_PREVIEW_WIDTH = 140
PRESET_PREVIEW_HEIGHT = 195
PRESET_THUMB_ASPECT_RATIO = 368 / 512  # NAI 기본 이미지 비율
```

**PresetFavoriteItemWidget 시그널**:
```python
clicked = pyqtSignal(str)              # preset_name
delete_requested = pyqtSignal(str)     # preset_name
```

**PresetTabMixin 주요 메서드**:
```python
# 데이터 초기화 (반드시 __init__에서 호출)
def _init_preset_data(self)

# UI 생성
def _create_preset_tab(self, parent_tabs: QTabWidget)
def _create_preset_favorites_subtab(self, subtabs: QTabWidget)
def _create_preset_engineering_subtab(self, subtabs: QTabWidget)

# 데이터 관리
def _load_preset_favorites(self)
def _save_preset_favorites(self)
def _validate_preset_favorites(self)

# 그리드 관리
def _calculate_preset_thumbnail_size(self) -> tuple[int, int]
def _update_preset_favorites_grid(self)
def _update_current_preset_ui(self)

# 동기화 (양방향 - 원본 모듈 연동)
def _sync_preset_combo(self)                    # 리모트 → 원본
def _on_remote_preset_changed(self, index: int) # 리모트 콤보 변경
def _update_preset_display(self)                # UI 갱신

# 이미지 관리
def _open_preset_folder(self)                   # 폴더 열기
def _paste_thumbnail_from_clipboard(self)       # 클립보드에서 썸네일 붙여넣기
def _smart_crop_image(self, img: Image) -> Image # 스마트 크롭

# 아이템 액션
def _toggle_preset_favorite(self, preset_name: str)
def _on_preset_favorite_clicked(self, preset_name: str)
```

**⚠️ 양방향 동기화 시스템 (중요)**:

`preset_tab.py`는 원본 PresetModule과 양방향 동기화를 유지:

```python
# 동기화 플래그 - 무한 루프 방지
self._preset_sync_in_progress = False

# 리모트 → 원본 동기화
def _sync_preset_combo(self):
    if self._preset_sync_in_progress:
        return
    self._preset_sync_in_progress = True
    try:
        # 원본 콤보박스 값 업데이트
        original_combo.setCurrentIndex(remote_index)
    finally:
        self._preset_sync_in_progress = False

# 원본 → 리모트 동기화 (textChanged 시그널 연결)
original_combo.currentTextChanged.connect(self._update_preset_display)
```

**💡 전처리 체크박스 동기화**:

프리셋 엔지니어링 탭에서 전처리 체크박스들도 원본 모듈과 동기화:

```python
# 리모트 체크박스 저장
self.remote_preprocessing_checkboxes = {}

# 연결 설정 (양방향)
remote_checkbox.stateChanged.connect(
    lambda state, cb=original_checkbox: cb.setChecked(state == Qt.CheckState.Checked.value)
)
original_checkbox.stateChanged.connect(
    lambda state, cb=remote_checkbox: cb.setChecked(state == Qt.CheckState.Checked.value)
)
```

---

## 리팩토링 가이드

### 새 탭을 Mixin으로 분리하는 방법

#### 1단계: 관련 코드 식별

```bash
# remote_window.py에서 탭 관련 메서드 찾기
grep -n "def _.*탭이름" ui/remote_window.py
grep -n "self.탭이름_" ui/remote_window.py
```

#### 2단계: Mixin 파일 생성

```python
# ui/remote/새탭_tab.py

from PyQt6.QtWidgets import ...
from PyQt6.QtCore import ...
from ui.theme import DARK_COLORS, get_dynamic_styles, DARK_STYLES
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

# 상수 정의
TAB_THUMB_WIDTH = 120
TAB_THUMB_HEIGHT = 167

class TabItemWidget(QFrame):
    """개별 아이템 위젯"""
    # 시그널 정의
    action_requested = pyqtSignal(str)

    def __init__(self, item_id: str, item_data: dict, parent=None):
        super().__init__(parent)
        self.item_id = item_id
        self.item_data = item_data
        self._setup_ui()

    def _setup_ui(self):
        # UI 구성
        pass

class NewTabMixin:
    """새 탭 Mixin - RemoteWindow와 함께 상속"""

    def _create_new_subtab(self, parent_tabs: QTabWidget):
        """탭 UI 생성"""
        pass

    def _on_tab_action(self, item_id: str):
        """액션 핸들러"""
        pass
```

#### 3단계: __init__.py 업데이트

```python
# ui/remote/__init__.py
from .event_tab import EventTabMixin, EventItemWidget
from .instant_wc_tab import InstantWcTabMixin, WildcardItemWidget
from .new_tab import NewTabMixin, TabItemWidget  # 추가

__all__ = [
    'EventTabMixin', 'EventItemWidget',
    'InstantWcTabMixin', 'WildcardItemWidget',
    'NewTabMixin', 'TabItemWidget'  # 추가
]
```

#### 4단계: remote_window.py 수정

```python
# ui/remote_window.py

# import 추가
from ui.remote.new_tab import NewTabMixin, TabItemWidget

# 클래스 상속 수정
class RemoteWindow(QMainWindow, EventTabMixin, InstantWcTabMixin, NewTabMixin):
    ...
```

#### 5단계: 중복 코드 제거

remote_window.py에서 Mixin으로 이동한 코드 삭제:
- 위젯 클래스 (예: TabItemWidget)
- 관련 상수 (예: TAB_THUMB_WIDTH)
- 관련 메서드 (예: _create_new_subtab, _on_tab_action)

#### 6단계: 문법 검사

```bash
python -m py_compile ui/remote/new_tab.py
python -m py_compile ui/remote/__init__.py
python -m py_compile ui/remote_window.py
```

---

## 주의사항

### 1. self 참조 주의

Mixin 메서드에서 `self`는 RemoteWindow를 가리킴. 필요한 속성이 RemoteWindow에 있는지 확인:

```python
# ❌ 잘못된 예: Mixin에서 정의되지 않은 속성 사용
def _update_list(self):
    self.list_widget.clear()  # RemoteWindow에 list_widget이 있어야 함

# ✅ 올바른 예: hasattr로 확인
def _update_list(self):
    if hasattr(self, 'list_widget'):
        self.list_widget.clear()
```

### 2. import 순서

Mixin 파일에서 필요한 import를 모두 포함:

```python
# ui/remote/instant_wc_tab.py
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QTextEdit, QLineEdit, QComboBox,
    QCheckBox, QTabWidget, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap

from pathlib import Path
import json

from ui.theme import DARK_COLORS, get_dynamic_styles, DARK_STYLES
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
```

### 3. 순환 import 방지

Mixin에서 remote_window를 import하지 않음:

```python
# ❌ 순환 import 발생
from ui.remote_window import RemoteWindow

# ✅ self를 통해 접근
def _get_parent_app(self):
    return self.parent_app  # RemoteWindow의 속성
```

### 4. 메서드 이름 충돌 방지

탭별로 고유한 접두사 사용:

```python
# 이벤트 탭
def _on_event_search(self): ...
def _on_event_delete(self, event_id): ...

# INST.WC 탭
def _on_wc_search(self): ...
def _on_wc_delete(self, file_key, item_key): ...

# 새 탭
def _on_newtab_search(self): ...
def _on_newtab_delete(self, item_id): ...
```

### 5. 위젯 시그널 타입 주의

item_data에서 가져온 값의 타입 확인:

```python
# ❌ 타입 오류 가능
value = self.item_data.get("value", "")
self.text_edit.setPlainText(value)  # value가 dict면 에러

# ✅ 타입 검사 추가
value = self.item_data.get("value", "")
if isinstance(value, dict):
    value = str(value)
self.text_edit.setPlainText(value)
```

### 6. 문법 검사 필수

코드 수정 후 반드시 문법 검사:

```bash
# 모든 관련 파일 검사
python -m py_compile ui/remote/__init__.py
python -m py_compile ui/remote/event_tab.py
python -m py_compile ui/remote/instant_wc_tab.py
python -m py_compile ui/remote/char_prompt_tab.py
python -m py_compile ui/remote/char_ref_tab.py
python -m py_compile ui/remote/preset_tab.py
python -m py_compile ui/remote_window.py
```

---

## 체크리스트

### 새 Mixin 생성 시

```
[ ] Mixin 클래스와 ItemWidget 클래스 분리
[ ] 필요한 상수 정의 (THUMB_WIDTH, THUMB_HEIGHT 등)
[ ] 필요한 시그널 정의 (ItemWidget)
[ ] 필요한 import 모두 포함
[ ] __init__.py에 export 추가
[ ] remote_window.py에 상속 추가
[ ] remote_window.py에서 중복 코드 제거
[ ] 문법 검사 통과
[ ] 실행 테스트
```

### 기존 Mixin 수정 시

```
[ ] 메서드 이름 접두사 일관성 유지
[ ] self 참조 속성 존재 확인
[ ] 타입 안전성 확인
[ ] 문법 검사 통과
[ ] 실행 테스트
```

---

## 관련 문서

- **[ui/CLAUDE.md](../CLAUDE.md)**: UI 전체 가이드
- **[최상위 CLAUDE.md](../../CLAUDE.md)**: 프로젝트 개요

---

*문서 버전: 4.0*
*최종 업데이트: 2025-01-13*
*담당 영역: ui/remote/ 서브모듈*

**변경 이력**:

| 버전 | 날짜 | 변경사항 |
|------|------|----------|
| 4.0 | 2025-01-13 | 🆕 quick_search_tab.py 추가 (~1310줄)<br>📝 퀵 서치 탭 상세 문서화 (UI 구조, 클래스, 메서드)<br>🔧 3열 균등 너비 그리드, 미리보기 팝업 문서화 |
| 3.0 | 2025-01-12 | 🆕 preset_tab.py 추가<br>📉 remote_window.py 86% 감소 (5000줄 → 702줄)<br>🔧 양방향 동기화 시스템 문서화 |
| 2.0 | 2025-01-12 | 🆕 char_prompt_tab.py, char_ref_tab.py 추가<br>📉 remote_window.py 70% 감소 (5000줄 → 1577줄)<br>🔧 JSON 포맷 호환성 처리 문서화 |
| 1.0 | 2025-01-12 | 초기 문서 생성, event_tab.py, instant_wc_tab.py 상세 |
