# CLAUDE.md — Turbo Event Sequence Tab

> **목적**: Turbo Event Sequence 탭의 구조, 워크플로우, 핵심 API를 설명하는 개발자 가이드

---

## 개요

Turbo Event Sequence Tab은 **Sliding Window Inpaint 기반의 연속 이미지 시퀀스 생성** 기능을 제공합니다.
Parquet 데이터셋에서 Parent-Child 관계의 이벤트 시퀀스를 검색하고, NAI API를 통해 연속적인 이미지를 생성합니다.

### 핵심 기능

1. **이벤트 검색**: Parquet 데이터셋에서 Parent/Child 태그 기반 검색
2. **시퀀스 미리보기**: Parent + Children 태그 diff 시각화
3. **프롬프트 편집**: 생성 전 프롬프트 수정, Skip 설정, 프롬프트 엔지니어링 적용
4. **Sliding Window Inpaint**: Parent 이미지 참조 기반 연속 생성 (경계선 삽입)
5. **그리드 이미지**: 시퀀스 완료 시 자동 그리드 생성 및 저장
6. **연속 생성**: 다음 이벤트 자동 선택 및 5초 카운트다운 후 생성
7. **재생성**: 현재 보고 있는 이미지 개별 재생성
8. **드래그 앤 드롭 재정렬**: 히스토리 패널에서 이미지 순서 변경
9. 🆕 **빠른 생성 버튼**: ⏩ (결정+첫페이지), ⏭ (결정+전체생성)
10. 🆕 **랜덤 연속 생성**: 검색 결과에서 랜덤 이벤트 선택

---

## 폴더 구조 및 파일 크기

```
tabs/turbo_event_sequence/
├── turbo_event_sequence_tab.py       # 📌 메인 탭 (1354줄) - 상태 머신, 레이아웃
├── event_search_utils.py              # 📌 Parquet 검색 유틸 (440줄)
├── event_explorer_ui.py               # 이벤트 시각화 UI (694줄)
├── CLAUDE.md                          # 본 문서
├── widgets/
│   ├── event_search_widget.py         # ⭐ 검색 UI (1462줄) - 재사용 가능
│   ├── history_panel.py               # 히스토리 패널 (1246줄) - 드래그앤드롭
│   ├── sequence_edit_widget.py        # 프롬프트 편집 (638줄)
│   ├── sequence_preview_widget.py     # 시퀀스 미리보기 (387줄)
│   ├── sequence_tab_container.py      # 탭 컨테이너 (216줄)
│   └── image_viewer_widget.py         # 이미지 뷰어 (142줄)
├── workers/
│   └── sequence_generation_worker.py  # NAI 생성 워커 (662줄)
└── docs/                              # 참고 문서
    ├── PRD_SRS.md
    ├── WORKER_TASK.md
    └── MAIN_TASK.md

총 코드량: ~7,200줄
```

---

## 아키텍처 다이어그램

```
┌─────────────────────────────────────────────────────────────┐
│         TurboEventSequenceTab (Main Container)              │
│                  State Machine (5 states)                   │
└─────────────────────────────────────────────────────────────┘
           │              │               │              │
    ┌──────┴──────┐ ┌─────┴─────┐  ┌──────┴──────┐ ┌─────┴─────┐
    │  Left Panel │ │ Sequence  │  │ Right Panel │ │ Favorite  │
    │   (검색)    │ │  Container│  │  (생성/뷰어)│ │  Controls │
    └─────────────┘ └───────────┘  └─────────────┘ └───────────┘
           │              │               │
    ┌──────┴──────────────┴───────────────┴──────┐
    │                                            │
┌───────────────────────┐        ┌──────────────────────────┐
│  EventSearchWidget    │        │     SequenceTabContainer │
│  ⭐ 재사용 가능 핵심   │        │  (Preview + Edit Tabs)   │
│  - 검색 UI            │        │  - 시퀀스 확정           │
│  - 데이터셋 관리       │        │  - 빠른 생성 (⏩⏭)      │
│  - Favorites          │        │  - PE 토글               │
│  - 연속/랜덤 생성 제어 │        │                          │
│  - 페이지네이션        │        │                          │
└───────────────────────┘        └──────────────────────────┘
         │                                │
         ├─ EventSearcher (util)          ├─ SequencePreviewWidget
         ├─ DatasetDownloadWorker         └─ SequenceEditWidget
         └─ DatasetLoaderThread

┌─────────────────────────────────────────────────────────────┐
│          Right Panel (Generation & History)                 │
├─────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────────────┐ │
│  │  ImageViewerWidget - 현재/그리드 이미지 표시           │ │
│  └────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Controls - 방향/진행/버튼 (첫페이지/전체/다음/재생성) │ │
│  └────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  HistoryPanel - 썸네일 + 드래그앤드롭 + Skip + 그리드  │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│         SequenceGenerationWorker (Background Thread)        │
│  - txt2img (Parent)                                         │
│  - inpaint (Children - 이전 이미지 + 경계선)               │
│  - Rating 태그 매핑                                         │
│  - Sliding Window + Border Insertion                        │
└─────────────────────────────────────────────────────────────┘
```

---

## 핵심 컴포넌트

### 1. TurboEventSequenceTab (메인 위젯)

**파일**: `turbo_event_sequence_tab.py` (1354줄)

**역할**: 탭의 전체 레이아웃 및 워크플로우 관리

**상태 머신**:
```python
STATE_IDLE = 0           # 대기 중 (시퀀스 미선택)
STATE_CONFIRMED = 1      # 시퀀스 확정됨, 해상도 선택 필요
STATE_READY = 2          # 해상도 선택됨, 생성 가능
STATE_FIRST_DONE = 3     # 첫 페이지 생성 완료
STATE_GENERATING = 4     # 생성 중
```

**주요 상태 변수**:
```python
self.current_viewing_index = -1   # 현재 보고 있는 이미지 인덱스 (재생성용)
self._waiting_continuous_after_grid_save = False  # 연속 생성: 그리드 저장 대기
self._index_mapping = None        # Skip 기능용 인덱스 매핑 (Worker → 원본)
```

**핵심 메서드**:

| 메서드 | 설명 |
|--------|------|
| `_on_parent_selected(parent_id, sequence_df)` | Parent 선택 시 시퀀스 로드 |
| `_on_sequence_confirmed(prompts)` | 시퀀스 확정 → 자동 가로 해상도 선택 |
| `_on_quick_first_page(prompts)` | 🆕 ⏩ 빠른 결정 + 첫 페이지 생성 |
| `_on_quick_all_pages(prompts)` | 🆕 ⏭ 빠른 결정 + 전체 생성 |
| `_start_single_generation(index, is_regenerate)` | 단일 이미지 생성 |
| `_start_full_generation(start_index)` | 전체 시퀀스 생성 (Skip 필터링) |
| `_on_regenerate_clicked()` | 현재 보고 있는 인덱스 재생성 |
| `_update_grid_image(is_sequence_complete)` | 그리드 이미지 생성/업데이트 |

---

### 2. EventSearchWidget (검색 위젯) ⭐ 재사용 가능

**파일**: `widgets/event_search_widget.py` (1462줄)

**역할**: 데이터셋 검색 UI, 다운로드, Favorites 관리, 연속 생성 제어

**재사용성**: 이 위젯은 **새로운 터보 모드 시스템에서 그대로 재사용 가능**합니다.

#### 데이터셋 설정

```python
DATASET_CONFIG = {
    'NAIA_1girl': {
        'filename': 'NAIA_event_dataset_1girl.parquet',
        'url': 'https://huggingface.co/.../NAIA_event_dataset_1girl.parquet'
    },
    'Favorites': {
        'filename': 'NAIA_event_dataset_personal.parquet',
        'url': None  # 로컬 전용
    }
}
```

#### 주요 시그널

```python
parent_selected = pyqtSignal(int, object)          # Parent 선택 (parent_id, sequence_df)
preview_image_ready = pyqtSignal(object)           # 미리보기 이미지 (PIL Image)
favorite_saved = pyqtSignal(int)                   # Favorite 저장 완료 (parent_id)
continuous_generation_requested = pyqtSignal(int)  # 연속 생성 요청 (parent_id)
```

#### Public API

```python
class EventSearchWidget(QWidget):
    # 초기화
    def __init__(self, app_context, parent=None)

    # 외부 UI 컨트롤 연결 (선택적)
    def set_ui_controls(self, save_btn, countdown_label, skip_checkbox_getter)

    # 현재 시퀀스 설정 (Favorite 저장용)
    def set_current_sequence(self, parent_id: int, sequence_df)

    # 연속 생성 상태
    def is_continuous_generation_enabled(self) -> bool  # 일반 또는 랜덤
    def is_skip_generated_enabled(self) -> bool

    # 연속 생성 제어
    def start_countdown_to_next()      # 5초 카운트다운 시작
    def on_grid_saved(parent_id, save_path)  # 그리드 저장 완료 알림

    # Favorites
    def refresh_favorites()
```

#### 내부 상태

```python
self._current_selected_id          # 현재 선택된 Parent ID
self._current_sequence_df          # 현재 시퀀스 DataFrame
self._saved_favorites: set         # Favorite Parent ID 집합
self._continuous_generation: bool  # 일반 연속 생성 모드
self._random_continuous_generation: bool  # 🆕 랜덤 연속 생성 모드
self._filtered_df                  # 전체 필터링 결과 (페이지네이션용)
self._current_page                 # 현재 페이지 (0-indexed)
self._items_per_page = 250         # 페이지당 항목 수
```

#### 재사용 방법

```python
from tabs.turbo_event_sequence.widgets.event_search_widget import EventSearchWidget

# 새 탭에서 검색 위젯 생성
search_widget = EventSearchWidget(app_context, parent)

# 시그널 연결
search_widget.parent_selected.connect(on_parent_selected)
search_widget.preview_image_ready.connect(on_preview_ready)
search_widget.continuous_generation_requested.connect(on_continuous)
search_widget.favorite_saved.connect(on_favorite_saved)

# 외부 UI 컨트롤 연결 (선택적)
search_widget.set_ui_controls(save_btn, countdown_label, lambda: skip_checkbox.isChecked())
```

---

### 3. EventSearcher (검색 엔진)

**파일**: `event_search_utils.py` (440줄)

**역할**: Parquet 데이터셋 검색 유틸리티

#### Public API

```python
class EventSearcher:
    def __init__(self, parquet_path: str = None, df: pd.DataFrame = None)

    # 검색 메서드
    def search_parents(self, include, exclude, min_children, max_children, ratings) -> DataFrame
    def search_children(self, include, exclude, parent_ids, ratings, min_score) -> DataFrame
    def search_parents_by_child_tags(self, child_include, child_exclude,
                                      parent_include, parent_exclude, ...) -> DataFrame

    # 데이터 조회
    def get_sequence(self, parent_id: int) -> DataFrame  # Parent + Children
    def get_parent(self, parent_id: int) -> Series
    def get_children(self, parent_id: int) -> DataFrame

    # 유틸리티
    def get_random_parents(self, n: int, **search_kwargs) -> DataFrame
    def get_stats(self) -> dict  # {total_parents, total_children, children_per_parent stats}

    # 캐시된 속성
    @property
    def parent_df(self) -> DataFrame      # Parent만 필터링 (캐시)
    @property
    def children_df(self) -> DataFrame    # Children만 필터링 (캐시)
    @property
    def children_counts(self) -> Series   # {parent_id: count} (캐시)
```

---

### 4. SequenceGenerationWorker (생성 워커)

**파일**: `workers/sequence_generation_worker.py` (662줄)

**역할**: NAI API를 통한 시퀀스 이미지 생성

#### 해상도 상수

```python
# 첫 번째 이미지 (txt2img)
SAMPLE_SIZE_H = (1152, 832)   # 가로 방향
SAMPLE_SIZE_V = (832, 1152)   # 세로 방향

# Inpaint 캔버스 (절반 확장)
CANVAS_SIZE_H = (832, 1216)   # 가로: 세로로 확장
CANVAS_SIZE_V = (1216, 832)   # 세로: 가로로 확장

# 이전 이미지 붙여넣기 영역
PASTE_SIZE_H = (832, 608)     # 가로 방향
PASTE_SIZE_V = (608, 832)     # 세로 방향
```

#### 시그널

```python
image_generated = pyqtSignal(int, object)      # (worker_index, PIL.Image)
progress_updated = pyqtSignal(int, int, str)   # (current, total, message)
generation_finished = pyqtSignal(list)          # [PIL.Image, ...]
generation_error = pyqtSignal(int, str)         # (index, error_msg)
generation_cancelled = pyqtSignal()
```

#### 경계선 삽입 (Split Screen 유도)

```python
# _create_inpaint_canvas()에서 경계선 추가
if self.direction == 'horizontal':
    # 600~608px 영역을 검은색으로 칠함 (세로 경계)
    draw.rectangle([(0, 600), (self.canvas_width, 608)], fill=(0, 0, 0))
else:  # vertical
    # 601~608px 영역을 검은색으로 칠함 (가로 경계)
    draw.rectangle([(601, 0), (608, self.canvas_height)], fill=(0, 0, 0))
```

---

### 5. HistoryPanel (히스토리 패널)

**파일**: `widgets/history_panel.py` (1246줄)

**역할**: 생성된 이미지 썸네일, Skip 동기화, 그리드 관리, 드래그 앤 드롭

#### 인덱스 구조

```
- 0번: 결합된 그리드 이미지 (🖼️ Grid) - 드래그 불가
- 1번~: 개별 생성 결과 이미지 (#1, #2, ...) - 드래그 가능
```

#### 주요 시그널

```python
image_selected = pyqtSignal(int, object)   # (history_index, PIL.Image)
skip_toggled = pyqtSignal(int, bool)       # (history_index, is_skipped)
grid_auto_saved = pyqtSignal(str)          # save_path
order_changed = pyqtSignal()               # 드래그앤드롭 재정렬
clear_and_reconfirm = pyqtSignal()
request_grid_update = pyqtSignal()
```

#### 주요 메서드

```python
def prepare_placeholders(count: int)           # 플레이스홀더 미리 생성
def add_image(original_index, image)           # 이미지 추가 (고정 위치)
def update_grid_image(grid_image, trigger_auto_save=False)  # 그리드 업데이트
def get_ordered_images() -> list               # Skip 제외 이미지 반환
def is_order_changed() -> bool                 # 순서 변경 여부
def reset_order_changed()                      # 순서 변경 플래그 초기화
```

---

### 6. SequenceTabContainer (탭 컨테이너)

**파일**: `widgets/sequence_tab_container.py` (216줄)

**역할**: 미리보기/수정 탭 전환, 시퀀스 확정 흐름

#### 시그널

```python
sequence_confirmed = pyqtSignal(list)          # 시퀀스 확정
prompts_updated = pyqtSignal(list)             # 프롬프트 수정
prompt_engineering_toggled = pyqtSignal(bool)  # PE 토글
quick_first_page_requested = pyqtSignal(list)  # 🆕 ⏩ 빠른 첫 페이지
quick_all_pages_requested = pyqtSignal(list)   # 🆕 ⏭ 빠른 전체 생성
```

---

## 시그널/슬롯 연결 맵

### 컴포넌트 간 상호작용

| Source | Target | Signal | Purpose |
|--------|--------|--------|---------|
| EventSearchWidget | Tab | `parent_selected` | 시퀀스 로드 |
| EventSearchWidget | Tab | `continuous_generation_requested` | 연속 생성 시작 |
| SequenceTabContainer | Tab | `sequence_confirmed` | 생성 흐름 시작 |
| SequenceTabContainer | Tab | `quick_first_page_requested` | ⏩ 빠른 생성 |
| SequenceTabContainer | Tab | `quick_all_pages_requested` | ⏭ 빠른 생성 |
| SequenceEditWidget | Container | `prompts_updated` | 프롬프트 업데이트 |
| SequenceEditWidget | Tab | `disable_state_changed` | Skip 동기화 |
| HistoryPanel | Tab | `image_selected` | 뷰어 업데이트 |
| HistoryPanel | Tab | `skip_toggled` | Skip 상태 동기화 |
| HistoryPanel | Tab | `grid_auto_saved` | 연속 생성 트리거 |
| HistoryPanel | Tab | `order_changed` | 재생성 비활성화 |
| Worker | Tab | `image_generated` | 히스토리 추가 |
| Worker | Tab | `generation_finished` | 완료 처리 |

---

## 데이터 흐름

### 1. 검색 → 선택 → 생성

```
User: 검색 필터 입력 + Search 클릭
    │
    ↓
EventSearchWidget._on_search_clicked()
    ├─→ EventSearcher.search_parents() / search_parents_by_child_tags()
    └─→ _update_table(results) → 페이지네이션 적용
              │
User: 테이블 행 클릭
    │
    ↓
EventSearchWidget._on_table_cell_clicked()
    ├─→ _update_preview(parent_id)  # 미리보기 이미지
    ├─→ searcher.get_sequence(parent_id)
    └─→ parent_selected.emit(parent_id, sequence_df)
              │
              ↓
TurboEventSequenceTab._on_parent_selected()
    ├─→ SequenceTabContainer.set_sequence(sequence_df)
    │     ├─→ SequencePreviewWidget (prompt_processor 적용)
    │     └─→ SequenceEditWidget.set_prompts()
    └─→ search_widget.set_current_sequence() (Favorite용)
```

### 2. 시퀀스 확정 → 생성

```
User: "✅ 결정" 또는 "⏩" 또는 "⏭" 클릭
    │
    ↓
SequenceTabContainer
    ├─→ _on_sequence_confirmed()     → sequence_confirmed.emit()
    ├─→ _on_quick_first_page()       → quick_first_page_requested.emit()
    └─→ _on_quick_all_pages()        → quick_all_pages_requested.emit()
              │
              ↓
TurboEventSequenceTab
    ├─→ _on_sequence_confirmed()     → 자동 가로 해상도 선택
    ├─→ _on_quick_first_page()       → 확정 + _start_single_generation(0)
    └─→ _on_quick_all_pages()        → 확정 + _start_full_generation(0)
```

### 3. 이미지 생성 흐름

```
TurboEventSequenceTab._start_full_generation()
    │
    ├─→ disabled_indices 필터링 → prompts_to_generate
    ├─→ _index_mapping 생성 (Worker→원본 인덱스)
    │
    └─→ SequenceGenerationWorker.start_generation()
              │
              ├─→ is_parent_prompt == True
              │     └─→ txt2img 요청
              │
              └─→ is_parent_prompt == False
                    ├─→ base_reference_image 또는 _generated_images[0]
                    ├─→ _create_inpaint_canvas() + 경계선 삽입
                    ├─→ _create_inpaint_mask()
                    └─→ inpaint 요청
                              │
              ↓
image_generated.emit(worker_index, image)
    │
    ↓
Tab._on_image_generated()
    ├─→ actual_index = _index_mapping[worker_index]
    ├─→ HistoryPanel.add_image(actual_index, image)
    └─→ _update_grid_image()
```

### 4. 연속 생성 흐름

```
generation_finished.emit([images])
    │
    ↓
Tab._on_full_generation_finished()
    ├─→ _update_grid_image(is_sequence_complete=True)
    │     └─→ HistoryPanel.update_grid_image(trigger_auto_save=True)
    │               └─→ _auto_save_grid() → grid_auto_saved.emit()
    │
    └─→ [연속 생성 모드 체크]
              │
              ↓
Tab._on_grid_auto_saved()
    └─→ search_widget.start_countdown_to_next()
              │
              ↓
5초 카운트다운
    │
    ↓
_find_next_parent_id() 또는 _find_random_parent_id()
    │
    ↓
_select_next_event(parent_id)
    └─→ continuous_generation_requested.emit(parent_id)
              │
              ↓
Tab._on_continuous_generation_requested()
    └─→ _on_full_sequence_clicked()  # 자동 생성 시작
```

---

## 파일 저장 경로

| 파일 유형 | 경로 | 포맷 |
|-----------|------|------|
| 그리드 이미지 | `save/turbo_events/{parent_id}` | JPEG (확장자 없음) |
| 자동 저장 그리드 | `{output_dir}/grid/sequence_grid_{timestamp}.webp` | WEBP |
| Favorites Parquet | `data/NAIA_event_dataset_personal.parquet` | Parquet |
| Favorites JSON | `data/NAIA_event_dataset_personal.json` | JSON |

---

## 외부 의존성

### 필요한 모듈/컴포넌트

1. **GenerationController** (`core/generation_controller.py`)
   - `execute_generation_pipeline(overrides=params)` 호출

2. **PromptEngineeringModule** (`modules/prompt_engineering_module.py`)
   - `preprocess_prompt_turbo(prompt)` - 프롬프트 엔지니어링 적용
   - `pre_textedit`, `post_textedit` - 선행/후행 고정 프롬프트

3. **ImageCrudController** (`core/image_crud_controller.py`)
   - `get_save_directory()` - 저장 경로

### Override 파라미터

```python
override_params = {
    'type': 'inpaint',
    'input': prompt,
    'negative_prompt': negative_prompt,
    'image_bytes': canvas_bytes,
    'mask_bytes': mask_bytes,
    'width': width,
    'height': height,
    'strength': 0.7,
    'noise': 0.0,
    'random_resolution': False,
    'turbo_sequence_request': True,      # 식별자
    'turbo_sequence_index': index,       # 현재 인덱스
}
```

---

## 재사용 가이드 (새 터보 모드 시스템)

### 직접 재사용 가능한 컴포넌트

| 컴포넌트 | 파일 | 용도 |
|----------|------|------|
| **EventSearchWidget** | `widgets/event_search_widget.py` | 검색 UI 전체 |
| **EventSearcher** | `event_search_utils.py` | Parquet 검색 엔진 |
| **HistoryPanel** | `widgets/history_panel.py` | 썸네일 + 드래그앤드롭 |
| **ThumbnailWidget** | `widgets/history_panel.py` | 개별 썸네일 |
| **ImageViewerWidget** | `widgets/image_viewer_widget.py` | PIL 이미지 뷰어 |

### 적응 필요한 컴포넌트

| 컴포넌트 | 적응 포인트 |
|----------|------------|
| **SequenceGenerationWorker** | 생성 로직 (인페인트 제거 시) |
| **SequenceEditWidget** | 프롬프트 구조 변경 시 |
| **TurboEventSequenceTab** | 상태 머신, 새 워크플로우 |

### 새 탭 구현 예시

```python
from tabs.turbo_event_sequence.widgets.event_search_widget import EventSearchWidget
from tabs.turbo_event_sequence.widgets.history_panel import HistoryPanel
from tabs.turbo_event_sequence.event_search_utils import EventSearcher

class NewTurboTab(QWidget):
    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context

        # 검색 위젯 재사용
        self.search_widget = EventSearchWidget(app_context, self)
        self.search_widget.parent_selected.connect(self._on_parent_selected)
        self.search_widget.continuous_generation_requested.connect(self._on_continuous)

        # 히스토리 패널 재사용
        self.history_panel = HistoryPanel(app_context, self)
        self.history_panel.image_selected.connect(self._on_image_selected)

        # 레이아웃 구성...

    def _on_parent_selected(self, parent_id: int, sequence_df):
        # 새 워크플로우 구현
        pass
```

---

## TODO: 향후 개선 계획

### 1. 인페인트 미사용 터보 모드

새로운 터보 모드 시스템 구현 시 참고 사항:

- [ ] `EventSearchWidget` 그대로 재사용
- [ ] 새 `SimpleTurboTab` 생성 (인페인트 없이 txt2img만)
- [ ] `SequenceGenerationWorker` 대신 새 워커 작성
- [ ] 연속 생성 로직은 기존 패턴 재사용

### 2. 이미지 영역 및 히스토리 개선 (퍼즐식 합성)

**배경**: 한 번에 여러 인페인트 이미지를 생성한 뒤, 사용자가 퍼즐식으로 합치는 기능 필요

**개선 항목**:

- [ ] **다중 이미지 생성 지원**
  - 각 프롬프트마다 N개 이미지 생성 옵션
  - 히스토리 패널에 트리 구조로 표시 (프롬프트 > 변형들)

- [ ] **퍼즐식 그리드 조합 UI**
  - 드래그앤드롭으로 각 슬롯에 이미지 배치
  - 같은 프롬프트의 여러 변형 중 선택
  - 실시간 그리드 미리보기

- [ ] **히스토리 패널 확장**
  - 확장/축소 가능한 그룹 (프롬프트별)
  - 각 그룹 내 변형 이미지 가로 스크롤
  - 선택된 이미지 표시 (체크마크)

- [ ] **그리드 조합 모드**
  - "조합 모드" 토글 버튼
  - 그리드 슬롯 클릭 → 해당 프롬프트의 변형들 팝업
  - 변형 선택 시 즉시 그리드 반영

- [ ] **저장 옵션 확장**
  - 최종 그리드만 저장 / 모든 변형 저장
  - 조합 히스토리 저장 (어떤 변형을 선택했는지)

---

## 주의사항

### 1. PIL 이미지 Lazy Loading

```python
# 항상 load() 호출 필요
if hasattr(image, 'load'):
    image.load()
```

### 2. PNG 버퍼 변환 (WEBP 등 호환성)

```python
png_buffer = io.BytesIO()
image.save(png_buffer, format='PNG')
png_buffer.seek(0)
clean_image = Image.open(png_buffer)
clean_image.load()
```

### 3. 외부 UI 컨트롤 안전한 접근

```python
# getattr로 안전하게 접근
save_btn = getattr(self, '_external_save_btn', None)
if save_btn:
    save_btn.setText("...")
```

### 4. 인덱스 매핑 (Skip 기능)

```python
# Worker 인덱스 → 원본 인덱스 변환
self._index_mapping = [idx for idx, _ in prompts_with_indices]

# 시그널 수신 시 변환
if index_mapping and worker_index < len(index_mapping):
    actual_index = index_mapping[worker_index]
```

### 5. 히스토리 인덱스 → 원본 인덱스 변환

```python
# 히스토리 0번 = 그리드 (-1), 1번 = 인덱스 0, 2번 = 인덱스 1, ...
self.current_viewing_index = history_index - 1
```

### 6. 그리드 자동 저장 중복 방지

```python
# update_grid_image()에 trigger_auto_save 파라미터 사용
# 시퀀스 완료 시에만 True로 설정
self.history_panel.update_grid_image(grid_image, trigger_auto_save=is_sequence_complete)
```

---

## 최근 변경사항 (2025-01-15)

### 기능 추가

1. **빠른 생성 버튼** (⏩, ⏭)
   - ⏩: 결정 + 첫 페이지 생성 (주황색)
   - ⏭: 결정 + 전체 시퀀스 생성 (녹색)
   - 위치: `sequence_preview_widget.py`

2. **랜덤 연속 생성**
   - 검색 결과에서 랜덤 이벤트 선택
   - `_find_random_parent_id()` 메서드
   - 랜덤 모드 아이콘: 🎲

3. **페이지네이션 개선**
   - 페이지당 250개 항목
   - 연속 생성 시 자동 페이지 전환

### 버그 수정

1. **그리드 자동 저장 중복**
   - 원인: `update_grid_image()` 호출마다 저장
   - 수정: `trigger_auto_save` 파라미터로 제어

2. **DARK_COLORS['accent'] KeyError**
   - 수정: `accent_blue`, `accent_blue_hover` 사용

---

*문서 버전: 2025-01-15*
*최종 검토: 빠른 생성, 랜덤 연속 생성, 재사용 가이드, TODO 추가*
