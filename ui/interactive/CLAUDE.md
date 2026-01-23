# CLAUDE.md — Interactive Mode

> **목적**: Interactive Mode는 NovelAI 이미지 생성 초보자를 위한 직관적이고 시각적인 UI를 제공합니다.

**문서 버전**: 1.2 (2025-01-22)

---

## 목차

1. [개요](#개요)
2. [아키텍처](#아키텍처)
3. [핵심 컴포넌트](#핵심-컴포넌트)
   - 3.1 [InteractiveWindow (메인 윈도우)](#1-interactivewindow-메인-윈도우)
   - 3.2 [BlockWidget (블록 베이스)](#2-blockwidget-블록-베이스-클래스)
   - 3.3 [DraggablePanel (플로팅 패널)](#3-draggablepanel-플로팅-패널)
   - 3.4 [InteractiveAutocompleteManager (자동완성)](#4-interactiveautocompletemanager-자동완성-시스템)
   - 3.5 [테마 시스템](#5-테마-시스템)
4. [블록 개발 가이드](#블록-개발-가이드)
5. [테마 시스템](#테마-시스템-1)
6. [실전 예제](#실전-예제)
7. [문제 해결](#문제-해결)

---

## 개요

### Interactive Mode란?

Interactive Mode는 **ComfyUI 스타일의 블록 기반 UI**로 구성된 초보자 친화적 이미지 생성 인터페이스입니다.

**핵심 특징**:
- 🎨 **좌우 분할 레이아웃**: 좌측 설정 패널 + 우측 이미지 뷰어
- 🧩 **블록 기반 UI**: 접을 수 있는 색상별 블록으로 기능 구분
- 📌 **플로팅 패널**: 이미지 위에 드래그 가능한 프롬프트 입력창
- 🎯 **단계별 가이드**: 인원 수 → 아티스트 → 구도 → 품질 순서

### 파일 구조

```
ui/
├── interactive_window.py          # 메인 윈도우 (좌우 레이아웃)
└── interactive/
    ├── block_widget.py            # 블록 베이스 클래스
    ├── interactive_theme.py       # ComfyUI 스타일 테마
    ├── draggable_panel.py         # 플로팅 패널 시스템
    ├── interactive_autocomplete.py # 자동완성 시스템 (tags_unified 기반)
    ├── tag_viewer_widget.py       # 3단 구조 태그 뷰어 (MainPrompt용)
    ├── interactive                # 태그 통합 데이터셋 (25MB, 확장자 없음)
    │
    ├── person_settings_block.py   # 인원 수 / Rating 설정
    ├── quick_search_block.py      # 퀵 서치 (태그 추천)
    ├── artist_tag_block.py         # 아티스트 태그 선택
    ├── composition_block.py        # X/Y/Z 축 구도 설정
    ├── quality_tag_block.py        # 품질 태그 설정
    ├── negative_prompt_block.py    # 네거티브 프롬프트
    │
    ├── main_prompt_block.py        # 메인 프롬프트 (플로팅)
    ├── additional_negative_prompt_block.py  # 추가 네거티브 (플로팅)
    │
    └── quick_search_data.py        # Quick Search 데이터 로더
```

---

## 아키텍처

### 레이아웃 구조

```
┌─────────────────────────────────────────────────────────┐
│  NAIA - Interactive Mode                    [메뉴바]    │
├──────────────┬──────────────────────────────────────────┤
│              │                                          │
│  좌측 패널    │          우측 패널 (이미지 뷰어)          │
│  (460px)     │                                          │
│              │  ┌────────────────┐  ┌──────────────┐   │
│ ┌──────────┐ │  │ 메인 프롬프트   │  │ 추가 네거티브 │   │
│ │인원수/목적│ │  │ (플로팅 1)     │  │ (플로팅 2)   │   │
│ └──────────┘ │  └────────────────┘  └──────────────┘   │
│ ┌──────────┐ │                                          │
│ │QuickSearch│ │        [생성된 이미지 표시]              │
│ └──────────┘ │                                          │
│ ┌──────────┐ │                                          │
│ │아티스트   │ │                                          │
│ └──────────┘ │                                          │
│ ┌──────────┐ │                                          │
│ │  구도     │ │                                          │
│ └──────────┘ │                                          │
│ ┌──────────┐ │                                          │
│ │  품질     │ │                                          │
│ └──────────┘ │                                          │
│ ┌──────────┐ │                                          │
│ │네거티브   │ │                                          │
│ └──────────┘ │                                          │
│              │                                          │
└──────────────┴──────────────────────────────────────────┘
```

### 데이터 흐름

```
PersonSettingsBlock (인원/Rating 변경)
    │
    └─[settingsChanged 시그널]─→ QuickSearchBlock.load_partition()
                                      │
                                      └─→ 파티션 로드 및 태그 추천
```

**시그널 체인**:
1. 사용자가 인원 수/Rating 변경
2. `PersonSettingsBlock.settingsChanged` 시그널 발행
3. `QuickSearchBlock`가 해당 파티션 로드
4. 매칭되는 태그 추천 표시

---

## 핵심 컴포넌트

### 1. InteractiveWindow (메인 윈도우)

**위치**: [ui/interactive_window.py](../interactive_window.py)

**역할**: 전체 레이아웃 관리 및 블록 초기화

**주요 기능**:
```python
class InteractiveWindow(QMainWindow):
    window_closed = pyqtSignal()  # 창 닫힘 시그널

    def __init__(self, parent_app=None):
        # 1. 좌측 패널 (고정 너비 460px)
        # 2. 우측 패널 (이미지 뷰어)
        # 3. 플로팅 패널 2개
```

**메뉴바 기능**:
- **📌 항상 위에 표시**: WindowStaysOnTopHint 토글

**좌측 패널 블록 순서**:
1. PersonSettingsBlock (항상 펼침)
2. QuickSearchBlock (기본 접힘)
3. ArtistTagBlock (기본 접힘)
4. CompositionBlock (기본 접힘)
5. QualityTagBlock (기본 접힘)
6. NegativePromptBlock (기본 접힘)

**우측 패널 플로팅**:
1. MainPromptBlock - 좌측 상단 (20, 20)
2. AdditionalNegativePromptBlock - 우측 상단 (350, 20)

### 2. BlockWidget (블록 베이스 클래스)

**위치**: [ui/interactive/block_widget.py](block_widget.py)

**ComfyUI 스타일 블록의 기반 클래스**

#### 구조

```python
class BlockWidget(QWidget):
    toggled = pyqtSignal(bool)  # 접기/펼치기 시그널

    def __init__(self, title: str, parent=None, block_type: str = 'default'):
        """
        Args:
            title: 블록 제목
            block_type: 'latent', 'conditioning', 'model', 'image',
                       'sampler', 'utility', 'control', 'default'
        """
```

#### 블록 타입별 색상

| 타입 | 색상 | 용도 |
|------|------|------|
| `latent` | 보라색 | 잠재 공간 관련 |
| `conditioning` | 빨간색/핑크 | 프롬프트/컨디셔닝 |
| `model` | 파란색 | 모델 설정 |
| `image` | 초록색 | 이미지 생성/처리 |
| `sampler` | 주황색 | 샘플러 설정 |
| `utility` | 청록색 | 유틸리티/도구 |
| `control` | 황금색 | 제어/설정 |
| `default` | 회색 | 기본 블록 |

#### 주요 메서드

```python
def toggle_collapse(self):
    """접기/펼치기 토글 (애니메이션 포함)"""

def get_content_layout(self) -> QVBoxLayout:
    """내용 레이아웃 반환 (위젯 추가용)"""

def set_collapsed(self, collapsed: bool):
    """프로그래밍 방식으로 접기/펼치기"""
```

#### UI 설계 가이드라인

**반드시 지켜야 할 규칙**:

1. **Vertical Policy**: `QSizePolicy.Policy.Maximum` 사용
   ```python
   self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
   ```

2. **레이아웃 끝에 Stretch 추가** (위젯이 상하로 늘어나는 것 방지)
   ```python
   layout = self.get_content_layout()
   # ... 위젯 추가 ...
   layout.addStretch()  # 필수!
   ```

3. **스타일 격리** (ID 선택자 사용)
   ```python
   button.setObjectName("my_button")
   button.setStyleSheet("QPushButton#my_button { ... }")
   ```

### 3. DraggablePanel (플로팅 패널)

**위치**: [ui/interactive/draggable_panel.py](draggable_panel.py)

**"포스트잇"처럼 자유롭게 이동 가능한 패널**

#### 핵심 기능

```python
class DraggablePanel(QWidget):
    def __init__(self, parent=None, child_widget=None):
        """
        Args:
            parent: 부모 위젯 (이미지 뷰어)
            child_widget: 내부 컨텐츠 (BlockWidget)
        """
```

**특징**:
- ✅ **다중 드래그**: 상단 핸들 + 빈 공간 드래그 모두 지원
- ✅ **Safe Move**: 화면 밖으로 나가도 최소 30px는 보임
- ✅ **Z-Order 관리**: 클릭/포커스 시 자동으로 최상단
- ✅ **자동 크기 조절**: 내부 블록 접기/펼치기에 동기화

#### FloatingPanelManager (싱글톤)

```python
class FloatingPanelManager:
    @classmethod
    def instance(cls):
        """싱글톤 인스턴스"""

    def register(self, panel):
        """패널 등록"""

    def activate_panel(self, panel):
        """패널을 최상단으로 올림"""
```

**자동 활성화 트리거**:
- 패널 클릭
- 드래그 시작
- 내부 TextEdit 포커스

#### 사용 예시

```python
# 플로팅 패널 생성
from ui.interactive.draggable_panel import DraggablePanel
from ui.interactive.main_prompt_block import MainPromptBlock

main_block = MainPromptBlock()
floating_panel = DraggablePanel(
    parent=image_viewer,
    child_widget=main_block
)

# 위치 및 크기 설정
floating_panel.setFixedWidth(get_scaled_size(320))
floating_panel.move(get_scaled_size(20), get_scaled_size(20))
floating_panel.show()
```

### 4. InteractiveAutocompleteManager (자동완성 시스템)

**위치**: [ui/interactive/interactive_autocomplete.py](interactive_autocomplete.py)

**tags_unified.json 기반의 위젯별 자동완성 시스템**

#### 개요

Interactive Mode 전용 자동완성 시스템으로, 각 블록마다 다른 데이터셋(카테고리)을 사용할 수 있습니다.

**핵심 특징**:
- ✅ **위젯별 데이터셋**: 각 TextEdit/LineEdit마다 다른 태그 카테고리 지정
- ✅ **풍부한 메타데이터**: 빈도, 분류, 설명, 한글 키워드, 연관 태그 제공
- ✅ **5단계 검색**: exact → starts_with → keyword → contains → description
- ✅ **NAI 구문 지원**: `::` 가중치 처리, 괄호 매칭, prefix 처리
- ✅ **한글 지원**: keywords_kr 필드로 한글 검색 가능

#### 데이터셋: tags_unified.json

**위치**: `ui/interactive/interactive` (확장자 없음, 25MB)

**구조**:
```json
{
  "bikini": {
    "freq": 150234,
    "group": "Clothing_Wear",
    "subgroup": "attire",
    "description": "비키니. 상하의가 분리된 여성용 수영복",
    "keywords_kr": "수영복, 비키니",
    "relations": {
      "parent": null,
      "children": ["black bikini", "string bikini", ...],
      "siblings": ["swimsuit", "one-piece swimsuit", ...],
      "word_match": ["bikini top", "bikini bottom", ...]
    },
    "source": "KR_tags"
  }
}
```

**통계**:
- 총 태그 수: 16,698개
- 설명 포함: 16,559개 (99%)
- 대분류: 9개 (의상, 인체, 음식/사물, 구도/메타, 표정/행동, 생물, 장소/배경, NSFW, 문화/기타)
- 소분류: 80개 이상

#### 9개 데이터셋 (카테고리)

| dataset_id | 대분류 (group) | 태그 수 | 예시 |
|------------|---------------|---------|------|
| `general` | 전체 | 16,698 | 모든 태그 |
| `clothing` | Clothing_Wear | 3,885 | bikini, dress, boots |
| `body` | Person_Body | 3,358 | blonde hair, blue eyes |
| `food_object` | Food_Object | 3,637 | sword, chair, apple |
| `composition` | Composition_Meta | 1,801 | solo, cowboy shot |
| `expression` | Expression_Action | 1,744 | smile, sitting |
| `creatures` | Creatures | 732 | cat ears, wings |
| `location` | Location_Background | 703 | outdoors, beach |
| `nsfw` | NSFW | 591 | (성인 태그) |

#### 아키텍처

```python
class InteractiveAutocompleteManager(QObject):
    def __init__(self, parent_window):
        """
        Args:
            parent_window: InteractiveWindow 인스턴스
        """
        self.parent_window = parent_window
        self.datasets = {}  # dataset_id -> tags_data
        self.widget_dataset_map = {}  # widget -> dataset_id
        self.registered_widgets = set()
```

**NOT 글로벌 싱글톤**: `core/autocomplete_manager.py`와 달리 인스턴스 기반

#### 위젯 등록 시스템

```python
def register_widget(self, widget, dataset_id="general"):
    """
    위젯을 자동완성에 등록하고 데이터셋 지정

    Args:
        widget: QTextEdit 또는 QLineEdit
        dataset_id: "general", "clothing", "body", "expression" 등

    Example:
        # MainPromptBlock에서
        autocomplete_manager.register_widget(
            self.prompt_edit,
            dataset_id="general"
        )

        # ClothingBlock에서 (가상)
        autocomplete_manager.register_widget(
            self.clothing_edit,
            dataset_id="clothing"
        )
    """
```

#### 검색 엔진 (5단계 우선순위)

```python
def _search_tags(self, query: str, dataset: dict) -> list:
    """
    반환: [(tag, tag_data), ...]

    우선순위:
    1. exact_matches: 완전 일치 (대소문자 무시)
    2. starts_with: 시작 문자 일치
    3. keyword_matches: keywords_kr 필드 매칭 (한글 검색)
    4. contains: 태그명에 쿼리 포함
    5. description_matches: 설명에 쿼리 포함

    각 티어 내에서 freq(빈도) 기준 정렬
    """
```

**예시**:
- `"bik"` 검색 → `bikini` (starts_with, freq: 150,234)
- `"수영복"` 검색 → `bikini` (keyword_matches, keywords_kr: "수영복, 비키니")
- `"여름"` 검색 → `summer`, `summer dress` (description_matches)

#### 풍부한 툴팁 시스템

자동완성 팝업에서 태그에 마우스를 올리면 다음 정보 표시:

```
태그: bikini
사용 횟수: 150,234
분류: 의상/착용
세부: attire
설명: 비키니. 상하의가 분리된 여성용 수영복
키워드: 수영복, 비키니
```

**구현**:
```python
def _populate_popup_with_counts(self, matches):
    for tag, tag_data in matches:
        count = tag_data.get("freq", 0)

        # 툴팁 구성
        tooltip_parts = [
            f"태그: {tag}",
            f"사용 횟수: {count:,}",
            f"분류: {group_kr}",
            f"세부: {subgroup}",
            f"설명: {description}",
            f"키워드: {keywords_kr}"
        ]
        item.setToolTip("\n".join(tooltip_parts))
```

#### 사용 예시

**InteractiveWindow에서 초기화**:
```python
# ui/interactive_window.py

from ui.interactive.interactive_autocomplete import InteractiveAutocompleteManager

class InteractiveWindow(QMainWindow):
    def __init__(self):
        # ... (기존 코드)

        # 자동완성 매니저 생성
        self.autocomplete_manager = InteractiveAutocompleteManager(self)

        # 블록 생성
        self.main_prompt_block = MainPromptBlock()

        # 위젯 등록 (블록 내부에서 호출)
        # self.autocomplete_manager.register_widget(...)
```

**블록에서 위젯 등록**:
```python
# ui/interactive/main_prompt_block.py

class MainPromptBlock(BlockWidget):
    def __init__(self, parent=None):
        super().__init__("메인 프롬프트", parent, block_type='image')
        self._init_content()

    def _init_content(self):
        layout = self.get_content_layout()

        # 프롬프트 입력
        self.prompt_edit = QTextEdit()
        layout.addWidget(self.prompt_edit)

        layout.addStretch()

    def register_autocomplete(self, autocomplete_manager):
        """InteractiveWindow에서 호출"""
        autocomplete_manager.register_widget(
            self.prompt_edit,
            dataset_id="general"  # 전체 태그 사용
        )
```

**카테고리별 등록 예시**:
```python
# 의상 전용 블록 (가상)
class ClothingInputBlock(BlockWidget):
    def register_autocomplete(self, autocomplete_manager):
        autocomplete_manager.register_widget(
            self.clothing_edit,
            dataset_id="clothing"  # 의상 태그만
        )

# 표정 전용 블록 (가상)
class ExpressionInputBlock(BlockWidget):
    def register_autocomplete(self, autocomplete_manager):
        autocomplete_manager.register_widget(
            self.expression_edit,
            dataset_id="expression"  # 표정/행동 태그만
        )
```

#### NAI 구문 처리

**지원 기능**:
- `::` 가중치: `1.2::masterpiece::` → "masterpiece" 추출
- 괄호 무시: `{curly}, [square], <angle>` → 괄호 제외하고 토큰 추출
- prefix 처리: `artist:crab_d` → "crab_d"만 자동완성
- 자동 쉼표 삽입: 완성 후 `, ` 추가

**주의**: NAI 가중치 편집 시 자동완성 무시
```python
# "1.2::master" 입력 중
# → "::" 감지 → 자동완성 비활성화
```

#### 무시 위젯 관리

```python
# 특정 위젯 이름 무시
autocomplete_manager.add_ignored_widget_name("my_special_edit")

# 특정 부모 위젯 하위 모두 무시
autocomplete_manager.add_ignored_parent_name("metadata_panel")

# 제거
autocomplete_manager.remove_ignored_widget_name("my_special_edit")
```

#### 활성화/비활성화

```python
# 일시 비활성화
autocomplete_manager.disable()

# 재활성화
autocomplete_manager.enable()
```

#### TagViewer 시스템 (3단 구조 뷰어)

**위치**: [ui/interactive/tag_viewer_widget.py](tag_viewer_widget.py)

MainPromptBlock 전용 3단 구조 태그 브라우저로, 전체 태그 데이터를 대분류/소분류/태그로 탐색할 수 있습니다.

**활성화 방법**:
```python
# 위젯에 use_tag_viewer 속성 설정
self.text_edit.setProperty("use_tag_viewer", True)
```

**레이아웃**:
```
┌─────────────────────────────────────────────┐
│  대분류 (1) │ 소분류 (2) │ 태그 리스트 (4)  │  ← 2/3 높이
├──────────────────────┬──────────────────────┤
│  기본 정보 (3)       │  연관 태그 (2)       │  ← 1/3 높이
└──────────────────────┴──────────────────────┘
```

**주요 특징**:
- ✅ **3단 구조**: 대분류 (1) : 소분류 (2) : 태그 (4) 너비 비율
- ✅ **크기**: 800x600 (일반 자동완성 팝업의 2배 높이)
- ✅ **자동 표시**: 텍스트박스 클릭 시 자동으로 나타남 (FocusIn 이벤트)
- ✅ **위치 고정**: 처음 표시된 위치에서 고정, 타이핑 중에도 움직이지 않음
- ✅ **윈도우 클램핑**: 부모 윈도우 경계를 초과하지 않도록 자동 조정
- ✅ **좌우 배치**: 위젯 위치에 따라 좌측 또는 우측에 배치
- ✅ **반투명 UI**: 85% 불투명도 (`rgba(43, 43, 43, 220)` + `opacity: 0.95`)
- ✅ **2분할 미리보기**: 기본 정보 (3) : 연관 태그 (2) 비율로 나뉨
  - 좌측: 태그, 빈도, 분류, 설명, 키워드
  - 우측: 상위, 하위, 형제, 관련 태그 (하이퍼링크)
- ✅ **하이퍼링크 네비게이션**: 연관 태그 클릭 → 자동 대분류/소분류 선택 → 태그 포커스
  - 모든 연관 태그 표시 (개수 제한 없음)
  - 존재하는 태그만 링크, 없는 태그는 회색 표시
- ✅ **IDE 간섭 방지**: WindowStaysOnTopHint 미사용 (InteractiveWindow 내부에서만 최상위)

**위치 계산 로직**:
```python
# 위젯이 창 중앙보다 왼쪽에 있으면 → 우측에 표시
if widget_center_x < window_center_x:
    popup_x = widget_top_right.x() + 20px

# 위젯이 창 중앙보다 오른쪽에 있으면 → 좌측에 표시
else:
    popup_x = widget_top_left.x() - viewer_width - 20px

# 윈도우 경계 클램핑 (10px 여백)
if popup_x < window_left:
    popup_x = window_left + 10px
elif popup_x + viewer_width > window_right:
    popup_x = window_right - viewer_width - 10px
```

**대분류 한글 매핑**:
```python
group_kr_map = {
    "Clothing_Wear": "의상/착용",
    "Person_Body": "인체/신체",
    "Food_Object": "음식/사물",
    "Composition_Meta": "구도/메타",
    "Expression_Action": "표정/행동",
    "Creatures": "생물/종족",
    "Location_Background": "장소/배경",
    "NSFW": "NSFW",
    "Culture_Misc": "문화/기타"
}
```

**미리보기 정보 (2분할)**:

좌측 - 기본 정보:
```
🏷️ 태그: bikini
📊 빈도: 150,234
📁 분류: Clothing_Wear > attire

📝 설명:
비키니. 상하의가 분리된 여성용 수영복

🔍 키워드: 수영복, 비키니
```

우측 - 연관 태그 (하이퍼링크):
```
⬆️ 상위 태그:
  swimwear [클릭 가능 링크]

⬇️ 하위 태그 (23개):
  • black bikini [클릭 가능 링크]
  • string bikini [클릭 가능 링크]
  • side-tie bikini [클릭 가능 링크]
  • micro bikini [클릭 가능 링크]
  ... (모든 23개 태그 표시, 제한 없음)

🔀 형제 태그 (15개):
  • swimsuit [클릭 가능 링크]
  • one-piece swimsuit [클릭 가능 링크]
  ... (모든 15개 태그 표시)

🔗 관련 태그 (8개):
  • bikini top [클릭 가능 링크]
  • bikini bottom [클릭 가능 링크]
  ... (모든 8개 태그 표시)
```

**하이퍼링크 동작**:
- 클릭 시 자동으로 대분류/소분류 선택
- 태그 리스트에서 해당 태그로 포커스 이동
- 미리보기 자동 업데이트
- 존재하지 않는 태그는 회색 텍스트로 표시 (클릭 불가)

**동작 흐름**:
1. 사용자가 MainPromptBlock 텍스트박스 클릭
2. FocusIn 이벤트 감지 → `use_tag_viewer` 속성 확인
3. TagViewer 생성 (지연 초기화)
4. 위젯 위치 계산 (좌/우 배치 결정)
5. 윈도우 경계 클램핑 적용
6. 초기 위치 기억 (`fixed_position`) → 타이핑 중에도 고정
7. TagViewer 표시 및 대분류 목록 채우기
8. 사용자가 대분류 선택 → 소분류 목록 업데이트
9. 사용자가 소분류 선택 → 태그 리스트 업데이트 (빈도순 정렬)
10. 태그 클릭 → 미리보기 영역에 상세 정보 표시
11. 태그 더블클릭 → 프롬프트에 삽입, TagViewer 숨김
12. 텍스트박스 포커스 아웃 → TagViewer 자동 숨김 및 위치 리셋

**사용 예시**:
```python
# main_prompt_block.py
class MainPromptBlock(BlockWidget):
    def _init_content(self):
        self.text_edit = QTextEdit()

        # TagViewer 사용 플래그 설정
        self.text_edit.setProperty("use_tag_viewer", True)

        # 자동완성 필터 (데이터셋 ID)
        self.text_edit.setProperty("autocomplete_filter", "general")

    def register_autocomplete(self, autocomplete_manager):
        autocomplete_manager.register_widget(
            self.text_edit,
            dataset_id="general"  # 전체 태그
        )
```

### 5. 테마 시스템

**위치**: [ui/interactive/interactive_theme.py](interactive_theme.py)

#### 색상 상수

```python
from ui.interactive.interactive_theme import COMMON_STYLES, INTERACTIVE_FONTS

# 공통 색상
COMMON_STYLES = {
    'text_primary': '#FFFFFF',
    'text_secondary': '#B0B0B0',
    'text_disabled': '#666666',
    'input_bg': '#2B2B2B',
    'input_border': '#333333',
    'input_focus': '#1976D2',
    'error': '#F44336',
}

# 폰트 크기 (스케일링 전 기본값)
INTERACTIVE_FONTS = {
    'header': 20,    # 블록 헤더
    'content': 18,   # 일반 내용
    'label': 18,     # 라벨
    'input': 18,     # 입력 필드
    'tiny': 16       # 작은 텍스트
}
```

#### 스타일 함수

```python
def get_header_style(block_type: str = 'default', collapsed: bool = False) -> str:
    """블록 헤더 스타일 생성"""

def get_content_style(block_type: str = 'default') -> str:
    """블록 내용 스타일 생성 (내부 위젯 포함)"""

def get_button_style(block_type: str = 'default') -> str:
    """버튼 스타일"""

def get_input_field_style() -> str:
    """입력 필드 스타일"""

def get_combobox_style() -> str:
    """콤보박스 스타일"""

def get_checkbox_style() -> str:
    """체크박스 스타일"""

def get_readonly_text_style() -> str:
    """읽기 전용 텍스트 스타일"""
```

#### 사용 예시

```python
from ui.interactive.interactive_theme import (
    COMMON_STYLES, INTERACTIVE_FONTS, FONT_FAMILY,
    get_label_style, get_combobox_style
)
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

# 라벨 스타일
label = QLabel("제목")
label.setStyleSheet(f"""
    color: {COMMON_STYLES['text_primary']};
    font-family: {FONT_FAMILY};
    font-size: {get_scaled_font_size(INTERACTIVE_FONTS['label'])}px;
    font-weight: bold;
""")

# 또는 헬퍼 함수 사용
self.setStyleSheet(get_label_style() + get_combobox_style())
```

---

## 블록 개발 가이드

### 블록 생성 체크리스트

#### 1단계: 파일 생성 및 기본 구조

```python
# ui/interactive/my_block.py
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import pyqtSignal

from ui.interactive.block_widget import BlockWidget
from ui.interactive.interactive_theme import COMMON_STYLES, INTERACTIVE_FONTS
from ui.scaling_manager import get_scaled_size, get_scaled_font_size

class MyBlock(BlockWidget):
    # 커스텀 시그널 정의 (필요시)
    value_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        # 블록 타입 선택: 'latent', 'conditioning', 'model', 'image',
        #                'sampler', 'utility', 'control', 'default'
        super().__init__("블록 제목", parent, block_type='utility')

        # ✅ 필수: Vertical Policy 설정
        from PyQt6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        self._init_content()

    def _init_content(self):
        layout = self.get_content_layout()

        # ✅ 위젯 추가
        label = QLabel("내용")
        layout.addWidget(label)

        # ✅ 필수: 레이아웃 끝에 Stretch
        layout.addStretch()
```

#### 2단계: 스타일 적용

**방법 1: 인라인 스타일**
```python
label = QLabel("제목")
label.setStyleSheet(f"""
    color: {COMMON_STYLES['text_primary']};
    font-family: {FONT_FAMILY};
    font-size: {get_scaled_font_size(INTERACTIVE_FONTS['label'])}px;
    font-weight: bold;
""")
```

**방법 2: 헬퍼 함수**
```python
from ui.interactive.interactive_theme import get_label_style

self.setStyleSheet(get_label_style())
```

**방법 3: ID 선택자 (스타일 격리)**
```python
button = QPushButton("클릭")
button.setObjectName("my_btn")
button.setStyleSheet(f"""
    QPushButton#my_btn {{
        background-color: {COMMON_STYLES['input_bg']};
        color: {COMMON_STYLES['text_primary']};
    }}
""")
```

#### 3단계: 위젯 추가 패턴

**수평 컨트롤 (균등 분배)**
```python
h_layout = QHBoxLayout()
h_layout.setSpacing(get_scaled_size(8))

btn1 = QPushButton("버튼 1")
btn2 = QPushButton("버튼 2")
btn3 = QPushButton("버튼 3")

h_layout.addWidget(btn1, 1)  # stretch factor
h_layout.addWidget(btn2, 1)
h_layout.addWidget(btn3, 1)

layout.addLayout(h_layout)
```

**구분선 (투명, 간격만 유지)**
```python
line = QFrame()
line.setFrameShape(QFrame.Shape.HLine)
line.setStyleSheet(f"""
    background-color: transparent;
    max-height: 1px;
    border: none;
    margin: {get_scaled_size(4)}px 0;
""")
layout.addWidget(line)
```

**콤보박스 (마우스 휠 비활성화)**
```python
def disable_wheel_event(self, widget):
    """콤보박스 스크롤 방지"""
    def wheelEvent(event):
        event.ignore()
    widget.wheelEvent = wheelEvent
    return widget

combo = QComboBox()
self.disable_wheel_event(combo)
combo.addItems(["옵션1", "옵션2"])
```

#### 4단계: 시그널 연결

```python
class MyBlock(BlockWidget):
    settings_changed = pyqtSignal(dict)  # 커스텀 시그널

    def _init_content(self):
        # ...

        # 위젯 변경 시 시그널 발행
        self.combo.currentIndexChanged.connect(self._on_value_changed)

    def _on_value_changed(self):
        """값 변경 시 시그널 발행"""
        data = {
            "value": self.combo.currentText(),
            "index": self.combo.currentIndex()
        }
        self.settings_changed.emit(data)
```

#### 5단계: InteractiveWindow에 등록

```python
# ui/interactive_window.py

# 블록 생성
from ui.interactive.my_block import MyBlock

my_block = MyBlock()
my_block.set_collapsed(True)  # 기본 접힘
left_layout.addWidget(my_block)

# 시그널 연결 (필요시)
my_block.settings_changed.connect(self._on_my_block_changed)
```

---

## 실전 예제

### 예제 1: 간단한 설정 블록

```python
# ui/interactive/simple_settings_block.py
from PyQt6.QtWidgets import QLabel, QCheckBox, QVBoxLayout, QSizePolicy
from PyQt6.QtCore import pyqtSignal

from ui.interactive.block_widget import BlockWidget
from ui.interactive.interactive_theme import COMMON_STYLES, INTERACTIVE_FONTS
from ui.scaling_manager import get_scaled_font_size

class SimpleSettingsBlock(BlockWidget):
    setting_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__("간단한 설정", parent, block_type='utility')
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._init_content()

    def _init_content(self):
        layout = self.get_content_layout()

        # 라벨
        label = QLabel("옵션을 선택하세요:")
        label.setStyleSheet(f"""
            color: {COMMON_STYLES['text_primary']};
            font-size: {get_scaled_font_size(INTERACTIVE_FONTS['label'])}px;
            font-weight: bold;
        """)
        layout.addWidget(label)

        # 체크박스
        self.checkbox = QCheckBox("고급 모드 활성화")
        self.checkbox.stateChanged.connect(self._on_checkbox_changed)
        layout.addWidget(self.checkbox)

        # ✅ 필수: Stretch
        layout.addStretch()

    def _on_checkbox_changed(self, state):
        """체크박스 변경 시그널"""
        is_checked = (state == 2)  # Qt.CheckState.Checked
        self.setting_changed.emit(is_checked)
```

### 예제 2: PersonSettingsBlock 분석

**위치**: [ui/interactive/person_settings_block.py](person_settings_block.py)

#### 핵심 기능
1. **인원 수 카운터**: 여성/남성/인외 0-6명
2. **Rating 선택**: General/Sensitive/Questionable/Explicit
3. **실시간 미리보기**: 생성될 태그 표시
4. **시그널 발행**: 변경 시 QuickSearchBlock에 알림

#### 커스텀 위젯: CountControl

```python
class CountControl(QWidget):
    """[Label] [◀] [값] [▶] 형태의 카운터"""
    valueChanged = pyqtSignal(int)

    def __init__(self, label_text, max_value=6, initial_value=0):
        # 라벨 + 감소버튼 + 값표시 + 증가버튼
        # 흰 배경에 검은 글씨 값 표시
```

#### 시그널 체인

```python
# PersonSettingsBlock 내부
self.control_girls.valueChanged.connect(self._update_preview)
self.control_boys.valueChanged.connect(self._update_preview)
self.rating_group.buttonClicked.connect(self._update_preview)

def _update_preview(self):
    # 1. 태그 생성 (1girl, 2boys, rating:sensitive 등)
    # 2. 미리보기 업데이트
    # 3. 시그널 발행
    self.settingsChanged.emit(selected_rating, person_info)
```

#### InteractiveWindow 연결

```python
# ui/interactive_window.py
person_block = PersonSettingsBlock()
quick_search_block = QuickSearchBlock()

# ✅ 시그널 연결: 인원/Rating 변경 시 QuickSearch 파티션 로드
person_block.settingsChanged.connect(quick_search_block.load_partition)
```

### 예제 3: CompositionBlock (구도 설정)

**위치**: [ui/interactive/composition_block.py](composition_block.py)

#### X/Y/Z 축 설정

```python
class CompositionBlock(BlockWidget):
    def __init__(self):
        super().__init__("X / Y / Z 축(구도) 정의", parent, block_type='utility')

    def _init_content(self):
        # X축 (수평 시점)
        self.combo_x = QComboBox()
        self.combo_x.addItems([
            "정의하지 않음",
            "정면",
            "측면(옆모습)",
            "3/4(반측면)",
            "후면(등)"
        ])

        # 태그 매핑
        self.tags_x = [
            "",
            "front view",
            "side view, 0.5::from side ::",
            "three-quarter view",
            "back view, 0.5::from behind ::"
        ]
```

#### 마우스 휠 비활성화

```python
def disable_wheel_event(self, widget):
    """스크롤 중 실수로 값 변경 방지"""
    def wheelEvent(event):
        event.ignore()
    widget.wheelEvent = wheelEvent
    return widget

combo = QComboBox()
self.disable_wheel_event(combo)
```

### 예제 4: QuickSearchBlock (태그 추천)

**위치**: [ui/interactive/quick_search_block.py](quick_search_block.py)

#### 파티션 로드 및 태그 추천

```python
class QuickSearchBlock(BlockWidget):
    def load_partition(self, rating: str, person_info: dict):
        """
        PersonSettingsBlock에서 호출됨

        Args:
            rating: 'general', 'sensitive', 'questionable', 'explicit'
            person_info: {'girls': 1, 'boys': 0, 'others': 0, 'total': 1}
        """
        # 1. 파티션 파일 결정 (예: s_1girl.tgp)
        # 2. 파티션 로드
        # 3. 자동 태그 설정 (1girl, 1boy 등)
        # 4. 추천 태그 업데이트
```

#### 데이터 검증 및 다운로드

```python
def _validate_and_load_metadata(self) -> bool:
    """메타데이터 검증 (13053개 이하면 재다운로드)"""
    tag_count = len(data.get('tag_to_id', {}))

    if tag_count <= 13053:
        # 구버전 감지 → 다운로드 다이얼로그
        self._show_download_dialog()
        return False

    return True

def _show_download_dialog(self):
    """다운로드 확인 다이얼로그"""
    reply = QMessageBox.question(
        self,
        "Quick Search 데이터 필요",
        "약 127MB의 데이터를 다운로드하시겠습니까?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )

    if reply == QMessageBox.StandardButton.Yes:
        self._start_download()
```

---

## 테마 시스템

### 블록 타입별 색상 선택 가이드

| 블록 용도 | 추천 타입 | 색상 | 예시 |
|----------|----------|------|------|
| 인물 설정 | `control` | 황금색 | PersonSettingsBlock |
| 프롬프트 입력 | `image` | 초록색 | MainPromptBlock |
| 아티스트 선택 | `conditioning` | 빨간색/핑크 | ArtistTagBlock |
| 구도/카메라 | `utility` | 청록색 | CompositionBlock |
| 품질 태그 | `conditioning` | 빨간색/핑크 | QualityTagBlock |
| 네거티브 | `default` | 회색 | NegativePromptBlock |
| Quick Search | `default` | 회색 | QuickSearchBlock |

### 색상 커스터마이징

```python
# interactive_theme.py에서 색상 수정
BLOCK_COLORS = {
    'my_custom': {
        'header': '#FF6B6B',  # 밝은 빨강
        'content': '#3D2525',  # 어두운 빨강
    },
}

# 사용
class MyBlock(BlockWidget):
    def __init__(self):
        super().__init__("제목", parent, block_type='my_custom')
```

### 스케일링 적용

```python
from ui.scaling_manager import get_scaled_size, get_scaled_font_size

# ✅ 올바른 방법
button.setFixedHeight(get_scaled_size(32))
label.setStyleSheet(f"font-size: {get_scaled_font_size(18)}px;")

# ❌ 잘못된 방법 (하드코딩)
button.setFixedHeight(32)
label.setStyleSheet("font-size: 18px;")
```

---

## 문제 해결

### Q1: 블록이 상하로 늘어나요

**원인**: `addStretch()` 누락 또는 SizePolicy 미설정

**해결**:
```python
def _init_content(self):
    layout = self.get_content_layout()

    # ✅ SizePolicy 설정 (생성자에서)
    self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

    # 위젯 추가
    layout.addWidget(label)

    # ✅ 필수: 레이아웃 끝에 Stretch
    layout.addStretch()
```

### Q2: 플로팅 패널이 화면 밖으로 사라졌어요

**원인**: Safe Move 로직이 동작하지 않음

**해결**: 패널의 일부(최소 30px)는 항상 화면에 보이도록 설계되어 있습니다.
- 핸들을 잡고 안쪽으로 드래그
- 또는 InteractiveWindow 재시작

### Q3: 콤보박스를 스크롤할 때 값이 바뀌어요

**원인**: 마우스 휠 이벤트 처리

**해결**:
```python
def disable_wheel_event(self, widget):
    def wheelEvent(event):
        event.ignore()
    widget.wheelEvent = wheelEvent
    return widget

combo = QComboBox()
self.disable_wheel_event(combo)
```

### Q4: 시그널이 전달되지 않아요

**체크리스트**:
```
[ ] 시그널 정의가 올바른가? (pyqtSignal)
[ ] connect()로 연결했는가?
[ ] emit()으로 발행했는가?
[ ] 시그널 시그니처가 일치하는가? (인자 타입/개수)
```

**디버깅**:
```python
# 시그널 발행 시
def _on_button_click(self):
    print("[DEBUG] 시그널 발행")
    self.button_clicked.emit()

# 시그널 수신 시
def _on_signal_received(self):
    print("[DEBUG] 시그널 수신됨")
```

### Q5: 스타일이 부모에서 상속되어 깨져요

**원인**: CSS 상속 (Cascading)

**해결**: ID 선택자로 격리
```python
button = QPushButton("버튼")
button.setObjectName("my_unique_btn")
button.setStyleSheet(f"""
    QPushButton#my_unique_btn {{
        background-color: {COMMON_STYLES['input_bg']};
    }}
""")
```

### Q6: Quick Search 데이터가 로드되지 않아요

**원인**: 메타데이터 파일 부재 또는 구버전

**해결**: 자동 다운로드 다이얼로그 표시
- 프로그램 시작 시 자동으로 검증
- 태그 수 13,053개 이하면 다운로드 안내
- 사용자 동의 후 자동 다운로드 및 설치

**수동 확인**:
```python
from pathlib import Path

metadata_file = Path("data/quick_search/metadata.tgpm")
print(f"파일 존재: {metadata_file.exists()}")

if metadata_file.exists():
    # 태그 수 확인 (코드 참조: quick_search_block.py)
    pass
```

### Q7: 자동완성이 작동하지 않아요

**원인**: 위젯이 등록되지 않았거나 데이터셋 로드 실패

**체크리스트**:
```
[ ] InteractiveWindow에서 autocomplete_manager 생성했는가?
[ ] 블록에서 register_autocomplete() 메서드 구현했는가?
[ ] InteractiveWindow에서 block.register_autocomplete() 호출했는가?
[ ] ui/interactive/interactive 데이터 파일이 존재하는가?
```

**디버깅**:
```python
# 위젯 등록 확인
print(f"등록된 위젯: {autocomplete_manager.registered_widgets}")
print(f"위젯-데이터셋 매핑: {autocomplete_manager.widget_dataset_map}")

# 데이터셋 로드 확인
print(f"로드된 데이터셋: {autocomplete_manager.datasets.keys()}")
for dataset_id, tags in autocomplete_manager.datasets.items():
    print(f"{dataset_id}: {len(tags)} 태그")
```

### Q8: 특정 위젯에서만 자동완성을 비활성화하고 싶어요

**해결**:
```python
# 방법 1: 위젯 이름으로 무시
autocomplete_manager.add_ignored_widget_name("metadata_edit")

# 방법 2: 부모 위젯 하위 전체 무시
autocomplete_manager.add_ignored_parent_name("settings_panel")

# 방법 3: 등록하지 않음 (가장 간단)
# register_autocomplete()를 호출하지 않으면 자동완성 없음
```

### Q9: 한글로 검색했는데 태그가 안 나와요

**원인**: keywords_kr 필드가 없는 태그

**설명**:
- tags_unified.json에서 keywords_kr 필드가 있는 태그만 한글 검색 가능
- keywords_kr이 없는 태그는 description 검색으로만 가능 (우선순위 낮음)

**해결**:
```python
# description 검색 우선순위는 5번째이므로 더 많이 입력
"수영복" → "bikini" (keywords_kr 매칭)
"여름옷" → 입력을 더 구체적으로: "summer dress" (영문으로)
```

**확인 방법**:
```python
import json
with open('ui/interactive/interactive', 'r', encoding='utf-8') as f:
    tags = json.load(f)

tag_data = tags.get('bikini', {})
print(f"한글 키워드: {tag_data.get('keywords_kr', '없음')}")
print(f"설명: {tag_data.get('description', '없음')}")
```

### Q10: 자동완성 팝업에서 선택했는데 이상한 위치에 삽입돼요

**원인**: NAI `::` 가중치 또는 괄호 처리 문제

**확인**:
- 입력 중인 토큰이 `::` 가중치인가? → 자동완성 비활성화됨
- 괄호 안에서 입력하는가? → 괄호 복원 로직 동작

**정상 동작**:
```
입력: "1girl, mast"
선택: "masterpiece"
결과: "1girl, masterpiece, "
```

**괄호 케이스**:
```
입력: "{mast"
선택: "masterpiece"
결과: "{masterpiece, "
```

---

## 개발 체크리스트

### 새 블록 추가 시

```
[ ] BlockWidget 상속
[ ] block_type 선택 (색상)
[ ] SizePolicy.Maximum 설정
[ ] layout.addStretch() 추가
[ ] 스케일링 함수 사용 (get_scaled_size, get_scaled_font_size)
[ ] 시그널 정의 및 연결 (필요시)
[ ] InteractiveWindow에 등록
[ ] 기본 접기 상태 설정 (set_collapsed)
[ ] 자동완성 등록 (필요시)
    - register_autocomplete(autocomplete_manager) 메서드 구현
    - 적절한 dataset_id 선택 (general, clothing, body, expression 등)
    - InteractiveWindow에서 block.register_autocomplete() 호출
[ ] 테스트: 접기/펼치기 애니메이션
[ ] 테스트: 다양한 해상도에서 레이아웃
[ ] 테스트: 자동완성 동작 (위젯별 데이터셋)
```

### 플로팅 패널 추가 시

```
[ ] DraggablePanel로 래핑
[ ] parent=image_viewer 설정
[ ] 고정 너비 설정 (setFixedWidth)
[ ] 초기 위치 설정 (move)
[ ] 내부 블록 접기/펼치기 시그널 연결 (자동 크기 조절)
[ ] show() 호출
[ ] 테스트: 드래그 동작
[ ] 테스트: Z-Order (여러 패널 클릭)
```

### 테마 수정 시

```
[ ] interactive_theme.py에서 BLOCK_COLORS 수정
[ ] 새 블록 타입 추가 시 get_block_style() 업데이트
[ ] 색상 대비 확인 (텍스트 가독성)
[ ] 모든 블록에서 일관성 확인
```

---

## 관련 문서

- **[../CLAUDE.md](../CLAUDE.md)**: 전체 프로젝트 가이드
- **[../ui/CLAUDE.md](../ui/CLAUDE.md)**: UI 시스템 가이드
- **tabs/studio/CLAUDE.md**: Studio Tab (다중 프레임 생성)

---

## 버전 히스토리

### v1.2 (2025-01-22)
- 🆕 **TagViewer 시스템 추가**: 3단 구조 태그 브라우저 (대분류/소분류/태그)
- ✅ **자동 표시**: 텍스트박스 클릭 시 TagViewer 자동으로 나타남 (FocusIn 이벤트)
- ✅ **윈도우 경계 클램핑**: TagViewer가 부모 윈도우를 초과하지 않도록 자동 조정
- ✅ **위치 고정**: 처음 표시된 위치에서 고정, 타이핑 중에도 움직이지 않음
- ✅ **반투명 UI**: 85% 불투명도로 이미지 뷰어와 조화
- ✅ **2분할 미리보기**: 기본 정보(좌) + 연관 태그(우) 3:2 비율
  - 좌측: 태그, 빈도, 분류, 설명, 키워드
  - 우측: 상위, 하위, 형제, 관련 태그 (HTML 하이퍼링크)
- 🆕 **하이퍼링크 네비게이션**: 연관 태그 클릭 시 자동 이동
  - 클릭 시 대분류/소분류 자동 선택
  - 태그 리스트에서 자동 포커스 및 스크롤
  - 존재하는 태그만 링크 활성화, 없는 태그는 회색 표시
  - 모든 연관 태그 표시 (개수 제한 제거)
- 🐛 **IDE 간섭 방지**: WindowStaysOnTopHint 제거 (InteractiveWindow 내부에서만 최상위)
- 📁 파일 추가: `tag_viewer_widget.py`

### v1.1 (2025-01-22)
- ✅ **InteractiveAutocompleteManager 추가**: tags_unified.json 기반 자동완성 시스템
- ✅ **위젯별 데이터셋**: 각 블록마다 다른 태그 카테고리 지정 가능
- ✅ **9개 카테고리**: general, clothing, body, food_object, composition, expression, creatures, location, nsfw
- ✅ **5단계 검색 엔진**: exact → starts_with → keyword → contains → description
- ✅ **한글 지원**: keywords_kr 필드로 한글 검색 가능
- ✅ **풍부한 메타데이터**: 빈도, 분류, 설명, 연관 태그 툴팁 표시
- ✅ **NAI 구문 지원**: `::` 가중치, 괄호 매칭, prefix 처리
- 📁 파일 구조에 `interactive_autocomplete.py` 및 `interactive` 데이터 파일 추가

### v1.0 (2025-01-21)
- 초기 문서 작성
- BlockWidget 아키텍처 설명
- DraggablePanel 시스템 문서화
- QuickSearchBlock 데이터 검증 및 다운로드 기능 추가
- 실전 예제 및 문제 해결 가이드 포함

---

**Happy Coding! 🎨**

*Interactive Mode로 초보자도 쉽게 고품질 이미지를 생성하세요!*
