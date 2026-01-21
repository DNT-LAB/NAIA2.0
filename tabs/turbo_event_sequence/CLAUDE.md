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
11. 🆕 **Event Viewer**: 생성한 이벤트 탐색 및 빠른 재생성
12. 🆕 **배경 정보 유지**: YOLO 인물 감지로 배경 보존하며 인물만 Inpaint
13. 🆕 **인페인트 편집기**: 히스토리 패널에서 개별 이미지 수동 인페인트 편집
14. 🆕 **개별 이미지 자동 저장**: 그리드 자동 저장 활성화 시 각 이미지를 즉시 개별 저장 (parent-child 페어 파일명)

---

## 폴더 구조 및 파일 크기

```
tabs/turbo_event_sequence/
├── turbo_event_sequence_tab.py       # 📌 메인 탭 (1410줄) - 상태 머신, 레이아웃
├── event_search_utils.py              # 📌 Parquet 검색 유틸 (440줄)
├── event_explorer_ui.py               # 이벤트 시각화 UI (694줄)
├── CLAUDE.md                          # 본 문서
├── widgets/
│   ├── event_search_widget.py         # ⭐ 검색 UI (1470줄) - 재사용 가능
│   ├── history_panel.py               # 히스토리 패널 (1280줄) - 드래그앤드롭, 개별 저장
│   ├── sequence_edit_widget.py        # 프롬프트 편집 (638줄)
│   ├── sequence_preview_widget.py     # 시퀀스 미리보기 (387줄)
│   ├── sequence_tab_container.py      # 탭 컨테이너 (216줄)
│   ├── image_viewer_widget.py         # 이미지 뷰어 (142줄)
│   ├── event_viewer_widget.py         # 🆕 Event Viewer 다이얼로그 (350줄)
│   ├── event_index_manager.py         # 🆕 이벤트 인덱스 JSON 관리 (300줄)
│   ├── thumbnail_grid.py              # 🆕 썸네일 그리드 위젯 (380줄)
│   ├── event_preview_panel.py         # 🆕 이벤트 미리보기 패널 (250줄)
│   └── sequence_inpaint_dialog.py     # 🆕 인페인트 편집 다이얼로그 (950줄)
├── workers/
│   ├── sequence_generation_worker.py  # NAI 생성 워커 (662줄)
│   └── person_mask_generator.py       # 🆕 YOLO 인물 마스크 생성기 (450줄)
├── .claude/
│   └── PRD_EVENT_VIEWER.md            # 🆕 Event Viewer PRD 문서
└── docs/                              # 참고 문서
    ├── PRD_SRS.md
    ├── WORKER_TASK.md
    └── MAIN_TASK.md

총 코드량: ~8,500줄
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

#### 🆕 배경 정보 유지 모드 (Keep Background)

`keep_background=True` 옵션을 사용하면 YOLO 인물 감지를 통해 배경을 유지하면서 인물 영역만 Inpaint합니다.

**캔버스 구성 (keep_background 모드)**:
```python
# 가로 방향: 상단 + 하단 모두 동일 이미지 배치
canvas.paste(resized, (0, 0))      # 상단
canvas.paste(resized, (0, 608))    # 하단 (동일 이미지)
draw.rectangle([(0, 600), (832, 616)], fill=(0, 0, 0))  # 중앙 경계선 확장

# 세로 방향: 좌측 + 우측 모두 동일 이미지 배치
canvas.paste(resized, (0, 0))      # 좌측
canvas.paste(resized, (608, 0))    # 우측 (동일 이미지)
draw.rectangle([(600, 0), (616, 832)], fill=(0, 0, 0))  # 중앙 경계선 확장
```

**마스크 생성**: `PersonMaskGenerator`가 YOLO로 인물 영역을 감지하여 해당 부분만 흰색(Inpaint 대상)으로 설정합니다.

---

### 4.1 PersonMaskGenerator (인물 마스크 생성기)

**파일**: `workers/person_mask_generator.py` (450줄)

**역할**: YOLO v8 기반 인물 세그멘테이션 및 Inpaint 마스크 생성

**의존성**: `ultralytics` (선택적 - 설치되지 않으면 기본 마스크로 폴백)

**모델**: `person_yolov8n-seg.pt` (자동 다운로드)

#### 주요 상수

```python
EXPANSION_RATIO = 1.07       # 마스크 확장 비율 (7% 확장 → ~50px padding)
CONFIDENCE_THRESHOLD = 0.25  # YOLO 신뢰도 임계값
```

#### 마스크 확장 (Morphological Dilation)

고립된 배경 영역(손/옷이 프레임 밖으로 나간 부분)을 포함시키기 위해 세그멘트 마스크를 형태학적 팽창(dilation)으로 확장합니다.

```python
from scipy import ndimage

# expansion_ratio를 픽셀 패딩으로 변환
padding_pixels = int(avg_dim * (expansion_ratio - 1.0))  # ~50px

# Morphological Dilation (4-connected)
struct = ndimage.generate_binary_structure(2, 1)
dilated = ndimage.binary_dilation(binary_mask, structure=struct, iterations=padding_pixels)
```

#### 주요 메서드

```python
def generate_mask(image: Image.Image, expansion_ratio: float = None) -> Image.Image:
    """이미지에서 인물 마스크 생성 (흰색=인물, 검정=배경)"""

def create_inpaint_mask_with_person(
    prev_image: Image.Image,
    canvas_size: Tuple[int, int],
    paste_size: Tuple[int, int],
    direction: str,
    mask_scale: int = 8
) -> Image.Image:
    """Inpaint용 1/8 크기 마스크 생성 (인물 영역만 Inpaint)"""

def is_available() -> bool:
    """YOLO 모델 사용 가능 여부"""
```

#### UI 연동

`TurboEventSequenceTab`의 `after_first_frame`에 `keep_background_checkbox`가 포함되어 있습니다:

```python
# after_first_frame 레이아웃 (2중 구조)
# 상단: regenerate_btn, next_page_btn, continue_all_btn
# 하단: keep_background_checkbox (🎭 배경 정보 유지)
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
def add_image(original_index, image)           # 이미지 추가 (고정 위치) + 🆕 개별 자동 저장
def update_grid_image(grid_image, trigger_auto_save=False)  # 그리드 업데이트
def get_ordered_images() -> list               # Skip 제외 이미지 반환
def is_order_changed() -> bool                 # 순서 변경 여부
def reset_order_changed()                      # 순서 변경 플래그 초기화
```

#### 🆕 개별 이미지 자동 저장 (2026-01-16)

**동작 방식:**

`add_image()` 메서드가 호출될 때 `auto_save_enabled=True`이면 각 이미지를 즉시 개별 저장합니다.

```python
# history_panel.py:757-759
def add_image(self, original_index: int, image):
    # ... (UI 업데이트 로직)

    # 🆕 자동 저장 활성화 시 개별 이미지 저장
    if self.auto_save_enabled and image:
        self._auto_save_individual_image(original_index, image)
```

**저장 로직:**
```python
def _auto_save_individual_image(self, original_index: int, image):
    """개별 이미지 자동 저장 (WEBP 형식, 동적 경로/grid 폴더)"""
    # 기존 그리드 저장과 동일한 경로 사용
    base_dir = self.app_context.image_crud_controller.get_save_directory()
    grid_dir = base_dir / "grid"

    # parent-child 파일명 형식 (타임스탬프 포함)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if original_index == 0:
        filename = f"parent_{timestamp}.webp"
    else:
        filename = f"parent-child{original_index}_{timestamp}.webp"

    # WEBP로 저장 (quality=95, method=6)
    image.save(str(grid_dir / filename), format='WEBP', quality=95, method=6)
```

**저장 타이밍:**
- **각 이미지 생성 직후** (API 응답 수신 → `image_generated` 시그널 → `add_image()` 호출)
- **최소 2초 간격** (API 생성 시간) → 타임스탬프 충돌 없음

**재생성 시 동작:**
- 동일 인덱스의 새 타임스탬프 파일 생성
- 이전 버전 파일은 유지됨 (버전 히스토리 보존)

**예시:**
```
첫 생성:
  parent_20260116_143025.webp
  parent-child1_20260116_143030.webp
  parent-child2_20260116_143035.webp

Child2 재생성:
  parent-child2_20260116_143045.webp  (새 파일 추가)
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

### 7. SequenceInpaintDialog (인페인트 편집기)

**파일**: `widgets/sequence_inpaint_dialog.py` (950줄)

**역할**: 히스토리 패널에서 개별 이미지를 수동으로 인페인트 편집하는 다이얼로그

#### 구성 클래스

| 클래스 | 역할 |
|--------|------|
| `MaskEditWidget` | 8x8 격자 기반 마스크 편집 캔버스 |
| `ResultWidget` | 원본/결과 비교, 재생성/확정 버튼 |
| `SequenceInpaintDialog` | 전체 다이얼로그 컨테이너 |

#### 시그널

```python
# MaskEditWidget
generate_requested = pyqtSignal(dict)  # mask_data (full_mask, small_mask, strength)

# ResultWidget
regenerate_requested = pyqtSignal()    # 재생성 요청
edit_mask_requested = pyqtSignal()     # 마스크 편집 탭 전환
cancel_requested = pyqtSignal()        # 취소
confirm_requested = pyqtSignal()       # 확정

# SequenceInpaintDialog
image_confirmed = pyqtSignal(int, object)  # (history_index, PIL.Image)
```

#### 캔버스 크기 상수

```python
CANVAS_SIZE_H = (832, 1216)   # 가로 방향 캔버스
CANVAS_SIZE_V = (1216, 832)   # 세로 방향 캔버스
PASTE_SIZE_H = (832, 608)     # 가로 방향 Child 크기
PASTE_SIZE_V = (608, 832)     # 세로 방향 Child 크기
PARENT_SIZE_H = (1152, 832)   # 가로 방향 Parent 크기
PARENT_SIZE_V = (832, 1152)   # 세로 방향 Parent 크기
```

#### 마스크 편집 UI

**툴바 구성**:
- 브러시 크기 슬라이더 (8~160px, 8의 배수)
- 브러시 모양 토글 (사각형/원형)
- **Strength 슬라이더** (0.01~1.00, 기본값 0.7)

**마우스 조작**:
| 동작 | 기능 |
|------|------|
| 좌클릭 드래그 | 마스크 그리기 (파란색 오버레이) |
| 우클릭 드래그 | 마스크 지우기 |
| 마우스 휠 | 브러시 크기 조절 |

**스크롤바 비활성화**: 마우스 휠이 브러시 크기 조절에 사용되므로 QGraphicsView 스크롤바 비활성화

```python
self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
```

#### Child 이미지 캔버스 확장

Child 이미지(608x832 또는 832x608)는 NAI 인페인트를 위해 캔버스 크기로 확장:

```python
# 가로 방향: 상단 + 하단에 동일 이미지 배치
canvas.paste(child_image, (0, 0))      # 상단
canvas.paste(child_image, (0, 608))    # 하단
draw.rectangle([(0, 600), (832, 616)], fill=(0, 0, 0))  # 경계선

# 마스크도 동일하게 복제
new_mask.paste(small_mask, (0, 0))     # 상단 절반
new_mask.paste(small_mask, (0, 76))    # 하단 절반 (76 = 608/8)
```

#### 인페인트 요청 흐름

```
1. HistoryPanel: inpaint_requested 시그널 발행
      ↓
2. TurboEventSequenceTab: _on_inpaint_requested() 핸들러
   - confirmed_prompts에서 해당 인덱스의 프롬프트 추출
   - negative_prompt를 메인 UI에서 가져옴
      ↓
3. SequenceInpaintDialog 생성 (prompt, negative_prompt 전달)
      ↓
4. 사용자: 마스크 편집 후 "생성하기" 클릭
      ↓
5. _execute_inpaint(): GenerationController 호출
   - override_params에 식별자 포함:
     - turbo_sequence_request: True
     - sequence_inpaint_dialog: True
     - sequence_inpaint_request_id: UUID
      ↓
6. NAIA_cold_v4.py: generation_completed 이벤트 발행 (식별자 포함)
      ↓
7. _on_generation_completed(): 식별자로 필터링 후 결과 표시
      ↓
8. 사용자: "이미지 결정" 클릭
      ↓
9. image_confirmed 시그널 → HistoryPanel 이미지 업데이트
```

#### Override 파라미터 형식

```python
override_params = {
    'type': 'inpaint',
    'input': self.prompt,              # 프롬프트 직접 전달
    'negative_prompt': self.negative_prompt,
    'image_bytes': canvas_bytes.getvalue(),
    'mask_bytes': mask_bytes.getvalue(),
    'width': canvas.width,
    'height': canvas.height,
    'strength': strength,              # 동적 strength 값 (0.01~1.00)
    'noise': 0.0,
    'random_resolution': False,
    'turbo_sequence_request': True,    # 시퀀스 요청 식별자
    'sequence_inpaint_dialog': True,   # 인페인트 다이얼로그 식별자
    'sequence_inpaint_request_id': self._request_id,  # 요청 ID
}
```

#### HistoryPanel 연동

**시그널 추가** (`history_panel.py`):
```python
inpaint_requested = pyqtSignal(int, object, str, bool)  # history_index, image, direction, is_parent
```

**핸들러** (`turbo_event_sequence_tab.py`):
```python
def _on_inpaint_requested(self, history_index: int, image, direction: str, is_parent: bool):
    # 프롬프트 추출 (confirmed_prompts에서)
    prompt = self.confirmed_prompts[history_index - 1].get('general', '')

    # 다이얼로그 생성
    self._inpaint_dialog = SequenceInpaintDialog(
        image=image,
        history_index=history_index,
        direction=direction,
        is_parent=is_parent,
        prompt=prompt,
        negative_prompt=negative_prompt,
        app_context=self.app_context,
        parent=None  # 모달리스
    )
    self._inpaint_dialog.image_confirmed.connect(self._on_inpaint_confirmed)
    self._inpaint_dialog.show()
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
    │     └─→ 🆕 _auto_save_individual_image() → parent-child{N}_{timestamp}.webp 저장
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
| 그리드 이미지 (미리보기용) | `save/turbo_events/{parent_id}` | JPEG (확장자 없음, 절반 해상도) |
| 자동 저장 그리드 (fullsize) | `{output_dir}/grid/sequence_grid_{timestamp}.webp` | WEBP (원본 해상도) |
| 🆕 개별 이미지 (Parent) | `{output_dir}/grid/parent_{timestamp}.webp` | WEBP (원본 해상도) |
| 🆕 개별 이미지 (Child) | `{output_dir}/grid/parent-child{N}_{timestamp}.webp` | WEBP (원본 해상도) |
| Favorites Parquet | `data/NAIA_event_dataset_personal.parquet` | Parquet |
| Favorites JSON | `data/NAIA_event_dataset_personal.json` | JSON |

**참고:**
- `{output_dir}`: `ImageCrudController.get_save_directory()` 반환값 (사용자 설정 저장 경로)
- 개별 이미지는 `auto_save_enabled=True`일 때만 저장됨
- 재생성 시 동일 인덱스의 새 타임스탬프 파일이 생성됨 (이전 버전 보존)

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

## Event Viewer 시스템 (2026-01-15 추가)

### 개요

Event Viewer는 `save/turbo_events` 폴더에 저장된 생성된 이벤트 그리드 이미지를 탐색하고,
선택한 이벤트의 시퀀스를 즉시 재생성할 수 있는 다이얼로그입니다.

### 구성 요소

```
┌─────────────────────────────────────────────────────────────────┐
│ 📂 Event Viewer                              [검색] [닫기]      │
├─────────────────────────────────────────────────────────────────┤
│ Parent: [Include]  [Exclude]   [🔍 검색] [🗑️ 클리어]            │
│ [2p] [3p] [4p] [5p] [6p]              [🔄 새로고침]             │
├────────────────────────┬────────────────────────────────────────┤
│  ThumbnailGrid (2x5)   │  EventPreviewPanel                     │
│  ┌───┐ ┌───┐           │  ┌────────────────────┐                │
│  │ T │ │ T │           │  │  선택한 이벤트      │                │
│  │ H │ │ H │           │  │  미리보기 이미지    │                │
│  │ U │ │ U │           │  │  (LargeImageViewer) │                │
│  └───┘ └───┘           │  └────────────────────┘                │
│  ID   ID               │  ID: 12345 | Pages: 4 | Rating: s-q-e  │
│  ...                   │  Tags: 1girl, solo, ...                 │
│  [◀ 이전] [다음 ▶]    │  [▶ 시퀀스 선택] [⏭ 바로 생성]         │
└────────────────────────┴────────────────────────────────────────┘
```

### 파일 구조

| 파일 | 역할 | 줄 수 |
|------|------|-------|
| `event_viewer_widget.py` | 메인 다이얼로그 (검색 UI + 키보드 바인딩) | ~510줄 |
| `event_index_manager.py` | JSON 인덱스 관리 (폴더-인덱스 동기화) | ~420줄 |
| `thumbnail_grid.py` | 2x5 썸네일 그리드 (비동기 로딩) | ~510줄 |
| `event_preview_panel.py` | 미리보기 패널 (이미지 + 정보 + 액션) | ~320줄 |

### UI 사양

| 항목 | 값 |
|------|-----|
| **최소 크기** | 1100 x 960 px |
| **기본 크기** | 1200 x 1000 px |
| **썸네일 크기** | 140 x 140 px (+ ID 라벨 18px) |
| **그리드 너비** | 320px 고정 |
| **폰트 최소 크기** | 15px (일부 ID 라벨 제외) |

### 키보드 바인딩

| 키 | 동작 |
|----|------|
| `←` / `→` | 썸네일 좌우 이동 |
| `↑` / `↓` | 썸네일 상하 이동 (2열 기준) |
| `Page Up` / `Page Down` | 페이지 넘김 |
| `Enter` | 시퀀스 선택 (다이얼로그 닫힘) |
| `Shift+Enter` | 바로 생성 (다이얼로그 유지) |
| `Escape` | 다이얼로그 닫기 |

### 마우스 스크롤

| 영역 | 동작 |
|------|------|
| **썸네일 그리드** | 페이지 스크롤 (위: 이전, 아래: 다음) |
| **미리보기 패널** | Z형 아이템 스크롤 (위: 이전, 아래: 다음 - 좌→우→다음줄 순서) |

### 인덱스 JSON 구조

**위치**: `save/turbo_events/generated_event_index.json`

```json
{
  "version": "1.1",
  "last_updated": "2026-01-15T12:34:56",
  "total_count": 150,
  "events": [
    {
      "id": 12345678,
      "general": "1girl, solo, blue_eyes, long_hair",
      "child_general": "kiss, 2girls, yuri hand_holding, ...",
      "ratings": ["s", "s", "q", "e"],
      "pages": 4,
      "created_at": "2026-01-10T10:00:00"
    }
  ]
}
```

**버전 1.1 변경사항**: `child_general` 필드 추가 (모든 child의 general 태그 합산)

### 시그널

```python
class EventViewerWidget(QDialog):
    event_selected = pyqtSignal(int, object)         # parent_id, sequence_df
    quick_generation_requested = pyqtSignal(int)     # parent_id
```

### 검색 기능

- **Parent Include/Exclude**: Parent의 general 태그 필터링
- **Child Include/Exclude**: Child의 general 태그 필터링 (모든 child 태그 합산)
- **Pages 필터**: 2p, 3p, 4p, 5p, 6p 토글 버튼
- **페이지네이션**: 한 페이지 10개씩 (2x5 그리드)

### 통합 포인트

**TurboEventSequenceTab에서 연결**:
```python
# 버튼 클릭
self.search_widget.event_viewer_btn.clicked.connect(self._on_open_event_viewer)

# Event Viewer 시그널
self._event_viewer.event_selected.connect(self._on_event_viewer_selected)
self._event_viewer.quick_generation_requested.connect(self._on_event_viewer_quick_generate)
```

### 바로 생성 동작

"바로 생성" (⏭) 버튼 또는 `Shift+Enter` 키는 **다이얼로그를 닫지 않고** 생성을 시작합니다.
연속 작업이 가능하도록 설계되었습니다.

```python
def _on_quick_generate(self, parent_id: int):
    """바로 생성 (다이얼로그 유지)"""
    sequence_df = self.index_manager.get_sequence_df(parent_id)
    if sequence_df is not None:
        self.quick_generation_requested.emit(parent_id)
        self.status_label.setText(f"✅ 생성 시작: {parent_id}")
        # 다이얼로그는 닫지 않음 - 연속 작업 가능
```

### 성능 최적화

1. **썸네일 비동기 로딩**: QThread 사용
2. **캐시**: 최대 50개 썸네일 캐시
3. **Lazy Indexing**: Event Viewer 열 때만 동기화
4. **인덱스 증분 갱신**: 새 이벤트 생성 시만 추가

### 포커스 관리 시스템

Event Viewer 다이얼로그에서 키보드 네비게이션이 원활하게 동작하도록 포커스 관리 시스템이 구현되어 있습니다.

#### 문제 상황

1. **검색 입력 필드 포커스**: QLineEdit에 포커스가 있으면 방향키가 텍스트 커서 이동에 사용됨
2. **이미지 영역 클릭**: 썸네일이나 미리보기 패널 클릭 후 포커스가 해당 위젯에 머물러 키보드 이벤트 처리 불가

#### 해결 방법

**1. keyPressEvent에서 포커스 위젯 감지**

```python
def keyPressEvent(self, event: QKeyEvent):
    key = event.key()

    # 검색 입력 필드에 포커스가 있는지 확인
    focused_widget = self.focusWidget()
    is_input_focused = isinstance(focused_widget, QLineEdit)

    # Escape, Page Up/Down은 항상 처리
    if key == Qt.Key.Key_Escape:
        self.close()
        return

    if key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
        # 페이지 넘김 처리
        return

    # 입력 필드에 포커스가 있으면 방향키는 기본 동작 (텍스트 커서 이동)
    if is_input_focused:
        super().keyPressEvent(event)
        return

    # 썸네일 선택 이동
    if key == Qt.Key.Key_Left:
        self._move_selection(-1)
        return
    # ... 다른 키 처리
```

**2. 이미지 영역 클릭 시 다이얼로그로 포커스 반환**

모든 클릭 가능한 위젯에 `mousePressEvent`를 오버라이드하여 부모 QDialog로 포커스를 반환:

```python
def mousePressEvent(self, event: QMouseEvent):
    """마우스 클릭 시 부모 다이얼로그로 포커스 이동"""
    super().mousePressEvent(event)

    # 부모 위젯 체인을 따라 QDialog 찾기
    parent = self.parent()
    while parent is not None:
        if parent.inherits("QDialog"):
            parent.setFocus()
            break
        parent = parent.parent()
```

#### 적용된 위젯

| 파일 | 위젯 | 역할 |
|------|------|------|
| `thumbnail_grid.py` | `ThumbnailItem` | 개별 썸네일 클릭 |
| `event_preview_panel.py` | `LargeImageViewer` | 큰 이미지 뷰어 클릭 |
| `event_preview_panel.py` | `EventPreviewPanel` | 미리보기 패널 전체 클릭 |
| `event_viewer_widget.py` | `_on_thumbnail_clicked()` | 썸네일 선택 시 `self.setFocus()` |

#### 핵심 포인트

1. **QDialog.inherits("QDialog")**: 부모 체인에서 QDialog 타입 확인
2. **포커스 반환 시점**: `mousePressEvent`에서 `super()` 호출 후 처리
3. **검색 필드 예외**: QLineEdit에 포커스가 있을 때는 방향키 기본 동작 유지
4. **항상 처리되는 키**: Escape, Page Up/Down은 포커스 위치와 무관하게 동작

### ThumbnailItem 구조

썸네일 아이템은 이미지와 ID 라벨이 분리된 구조입니다:

```
┌─────────────────┐
│                 │
│    이미지       │  ← 140 x 140 px
│                 │
├─────────────────┤
│    12345678     │  ← 18px 높이, 10pt 폰트
└─────────────────┘
```

ID가 8자리를 초과하면 `1234..78` 형태로 축약됩니다.

---

## 최근 변경사항 (2026-01-15)

### 기능 추가

1. **Event Viewer 시스템** 🆕
   - 생성한 이벤트 탐색 다이얼로그
   - 2x5 썸네일 그리드 + 미리보기 패널
   - JSON 인덱스 기반 빠른 검색
   - 시퀀스 선택 / 바로 생성 기능
   - 위치: `widgets/event_viewer_widget.py`

2. **빠른 생성 버튼** (⏩, ⏭)
   - ⏩: 결정 + 첫 페이지 생성 (주황색)
   - ⏭: 결정 + 전체 시퀀스 생성 (녹색)
   - 위치: `sequence_preview_widget.py`

3. **랜덤 연속 생성**
   - 검색 결과에서 랜덤 이벤트 선택
   - `_find_random_parent_id()` 메서드
   - 랜덤 모드 아이콘: 🎲

4. **페이지네이션 개선**
   - 페이지당 250개 항목
   - 연속 생성 시 자동 페이지 전환

### UI 개선 (2026-01-15 후반)

1. **Event Viewer UI 크기 조정**
   - 최소 높이: 960px → 다이얼로그 기본 1200x1000px
   - 썸네일 크기: 100px → 140px
   - 그리드 너비: 320px 고정
   - 폰트 크기: 15px 이상으로 통일 (가독성 개선)

2. **썸네일 ID 라벨 분리**
   - ID 텍스트를 이미지 오버레이에서 이미지 하단으로 이동
   - ID 라벨 전용 영역: 18px 높이
   - ID 폰트 크기: 10pt (축소 - 공간 효율)
   - 8자리 초과 시 `1234..78` 형태로 축약

3. **키보드 바인딩 추가**
   - `←`/`→`: 썸네일 좌우 이동
   - `↑`/`↓`: 썸네일 상하 이동
   - `Page Up`/`Page Down`: 페이지 넘김
   - `Enter`: 시퀀스 선택
   - `Shift+Enter`: 바로 생성 (다이얼로그 유지)
   - `Escape`: 닫기

4. **마우스 스크롤 지원 추가**
   - 썸네일 그리드 영역: 페이지 스크롤
   - 미리보기 패널 영역: 아이템 스크롤

5. **포커스 관리 시스템**
   - 문제: 검색 입력 필드나 이미지 영역 클릭 후 키보드 네비게이션 불가
   - 해결: 이미지/썸네일 영역 클릭 시 자동으로 다이얼로그에 포커스 반환
   - 적용 위젯: `ThumbnailItem`, `LargeImageViewer`, `EventPreviewPanel`

6. **Child 검색 기능** 🆕
   - Child Include/Exclude 입력 필드 추가
   - 인덱스 버전 1.0 → 1.1 업그레이드 (`child_general` 필드 추가)
   - 기존 인덱스는 자동으로 재빌드됨

7. **바로 생성 동작 변경**
   - 변경 전: 다이얼로그 자동 닫힘
   - 변경 후: 다이얼로그 유지 (연속 작업 가능)

8. **모달리스 창 구현** 🆕
   - Event Viewer를 비차단(modeless) 창으로 변경
   - 메인 윈도우와 동시 사용 가능
   - 일반 윈도우처럼 z-order 전환 가능

9. **배경 정보 유지 (Keep Background)** 🆕
   - YOLO v8 인물 세그멘테이션 기반 배경 보존 Inpaint
   - `PersonMaskGenerator` 클래스 추가 (`workers/person_mask_generator.py`)
   - Morphological Dilation으로 마스크 확장 (EXPANSION_RATIO=1.07)
   - `after_first_frame` UI 2중 레이아웃으로 재구성
   - `ultralytics` 미설치 시 기본 마스크로 폴백

10. **인페인트 편집기 (SequenceInpaintDialog)** 🆕
   - 히스토리 패널에서 개별 이미지 수동 인페인트 편집
   - 8x8 격자 기반 마스크 편집 캔버스
   - Strength 슬라이더 추가 (0.01~1.00, 기본값 0.7)
   - QGraphicsView 스크롤바 비활성화 (휠=브러시 크기)
   - Child 이미지 캔버스 자동 확장 (상하/좌우 복제)
   - 요청 ID 기반 응답 필터링
   - 위치: `widgets/sequence_inpaint_dialog.py`

### 버그 수정

1. **그리드 자동 저장 중복**
   - 원인: `update_grid_image()` 호출마다 저장
   - 수정: `trigger_auto_save` 파라미터로 제어

2. **DARK_COLORS['accent'] KeyError**
   - 수정: `accent_blue`, `accent_blue_hover` 사용

3. **Event Viewer 항상 위에 표시 문제** 🆕
   - 원인: QDialog를 부모와 함께 생성하면 OS가 "owned window"로 취급
   - 증상: WindowFlags 제거해도 창이 항상 메인 윈도우 위에 고정됨
   - 수정: 부모 없이 생성 (`EventViewerWidget(data_dir, events_dir, None)`)

4. **히스토리 패널 드래그 앤 드롭 버그** 🆕
   - **Grid 바로 뒤 드롭 불가**: `target_index > 0` 조건이 index 1도 차단 → `>= 1`로 변경
   - **마지막 위치 뒤 드롭 불가**: `_get_drop_target_index`가 `len-1` 반환 → `len` 반환
   - **Grid 앞으로 이미지 이동**: 레이아웃/리스트 인덱스 불일치 → 리스트 먼저 수정 후 레이아웃 재구성
   - 위치: `widgets/history_panel.py:_reorder_widgets()`

5. **인페인트 관련 버그** 🆕
   - **썸네일 재클릭 시 이전 이미지 표시**: `ThumbnailWidget.image` 대신 `self.images[index]` 사용
   - **다이얼로그 이미지 잔상**: 기존 다이얼로그 닫고 새로 생성
   - **Child 인페인트 시 prev_image 오류**: `selected_index - 1` 대신 항상 `images[1]` (Parent) 사용

---

## PyQt6 모달리스 다이얼로그 가이드

### 문제 상황

QDialog를 부모와 함께 생성하면 OS가 "owned window"로 취급하여:
- 부모 윈도우 앞에 항상 표시됨
- `setWindowFlags()`로도 z-order 변경 불가
- 사용자가 메인 윈도우 작업 시 불편함

### 해결 방법

**1. 부모 없이 생성 (권장)**

```python
# ❌ 잘못된 방법 - owned window가 됨
self._dialog = MyDialog(data_dir, events_dir, self)  # parent=self

# ✅ 올바른 방법 - 독립 창으로 동작
self._dialog = MyDialog(data_dir, events_dir, None)  # parent=None
```

**2. show() 사용 (exec() 대신)**

```python
# ❌ 잘못된 방법 - 블로킹 모달
self._dialog.exec()

# ✅ 올바른 방법 - 비차단 모달리스
self._dialog.show()
```

**3. 창 중복 생성 방지**

```python
def _on_open_dialog(self):
    """다이얼로그 열기 (모달리스)"""
    # 이미 열려있으면 포커스만 이동
    if hasattr(self, '_dialog') and self._dialog and self._dialog.isVisible():
        self._dialog.raise_()
        self._dialog.activateWindow()
        return

    # 새 다이얼로그 생성 (부모 없이)
    self._dialog = MyDialog(data, None)
    self._dialog.show()
```

### 메모리 관리

**Q: 부모 없이 생성하면 메모리 누수가 발생하나요?**

**A: 아니요.** Python GC가 자동으로 처리합니다.

| 상황 | 메모리 처리 |
|------|------------|
| 창 닫기 (X 버튼) | 위젯 숨김 → 다음 열기 시 새 인스턴스로 교체 → 이전 인스턴스 GC 수거 |
| 새 인스턴스 할당 | `self._dialog = MyDialog()` → 이전 참조 사라짐 → GC 수거 |
| 탭 닫기 | 탭 파괴 시 `self._dialog` 참조도 사라짐 → GC 수거 |

**명시적 정리가 필요한 경우:**

| 상황 | 필요 여부 | 이유 |
|------|----------|------|
| 일반적인 창 닫기 | ❌ 불필요 | GC가 처리 |
| 탭 닫힐 때 열린 창 닫기 | ⚠️ 권장 (UX) | 관련 창도 같이 닫히는 게 자연스러움 |
| QThread가 돌고 있는 경우 | ✅ 필요 | 스레드 명시적 종료 필요 |
| 순환 참조 | ✅ 필요 | GC가 즉시 수거 못함 |

**선택적 UX 개선 (탭 닫힐 때 창도 닫기):**

```python
def cleanup(self):
    """탭 닫힐 때 관련 창도 닫기 (UX 개선)"""
    if hasattr(self, '_dialog') and self._dialog:
        self._dialog.close()
```

### Event Viewer 구현 예시

```python
# turbo_event_sequence_tab.py

def _on_open_event_viewer(self):
    """Event Viewer 열기 (모달리스)"""
    from .widgets.event_viewer_widget import EventViewerWidget

    # 이미 열려있으면 포커스만 이동
    if hasattr(self, '_event_viewer') and self._event_viewer and self._event_viewer.isVisible():
        self._event_viewer.raise_()
        self._event_viewer.activateWindow()
        return

    # Event Viewer 생성 (부모 없이 - 독립 창)
    self._event_viewer = EventViewerWidget(data_dir, events_dir, None)
    self._event_viewer.event_selected.connect(self._on_event_viewer_selected)
    self._event_viewer.quick_generation_requested.connect(self._on_event_viewer_quick_generate)
    self._event_viewer.show()
```

---

## 변경 이력

### 2026-01-16: 개별 이미지 자동 저장 기능 추가

**추가된 기능:**
- 그리드 자동 저장 활성화 시 각 이미지를 즉시 개별 파일로 저장
- parent-child 페어 파일명 형식 (타임스탬프 포함)
- 기존 그리드 저장과 동일한 경로 사용 (`{output_dir}/grid/`)

**수정된 파일:**
- `widgets/history_panel.py` (+37줄)
  - `add_image()`: 자동 저장 로직 추가
  - `_auto_save_individual_image()`: 새 메서드 추가

**저장 경로:**
- Parent: `{output_dir}/grid/parent_{timestamp}.webp`
- Child: `{output_dir}/grid/parent-child{N}_{timestamp}.webp`

**동작:**
- 각 이미지 생성 직후 즉시 저장 (최소 2초 간격)
- 재생성 시 새 타임스탬프 파일 생성 (이전 버전 보존)
- `save/turbo_events` 미리보기 저장 기능과 독립적

---

*문서 버전: 2026-01-16*
*최종 검토: 개별 이미지 자동 저장 기능 추가*
