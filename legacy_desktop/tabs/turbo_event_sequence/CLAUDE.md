# CLAUDE.md — Turbo Event Sequence Tab

> **목적**: Turbo Event Sequence 탭의 구조, 워크플로우, 핵심 API 가이드

---

## 개요

Sliding Window Inpaint 기반의 연속 이미지 시퀀스 생성 탭. Parquet 데이터셋에서 Parent-Child 이벤트 시퀀스를 검색하고, NAI API를 통해 연속 이미지를 생성합니다.

**핵심 기능**: 이벤트 검색, 시퀀스 미리보기/편집, Sliding Window Inpaint, 그리드 자동 저장, 연속/랜덤 생성, 재생성, 드래그앤드롭 재정렬, 빠른 생성 버튼(결정+생성), Event Viewer, 배경 정보 유지(YOLO), 인페인트 편집기, 개별 이미지 자동 저장

---

## 폴더 구조

```
tabs/turbo_event_sequence/
├── turbo_event_sequence_tab.py       # 메인 탭 - 상태 머신, 레이아웃
├── event_search_utils.py              # Parquet 검색 유틸 (EventSearcher)
├── event_explorer_ui.py               # 이벤트 시각화 UI
├── widgets/
│   ├── event_search_widget.py         # 검색 UI (재사용 가능)
│   ├── history_panel.py               # 히스토리 패널 - 드래그앤드롭, 개별 저장
│   ├── sequence_edit_widget.py        # 프롬프트 편집
│   ├── sequence_preview_widget.py     # 시퀀스 미리보기
│   ├── sequence_tab_container.py      # 탭 컨테이너
│   ├── image_viewer_widget.py         # 이미지 뷰어
│   ├── sequence_inpaint_dialog.py     # 인페인트 편집기
│   ├── event_viewer_widget.py         # Event Viewer 다이얼로그
│   ├── event_index_manager.py         # JSON 인덱스 관리
│   ├── thumbnail_grid.py             # 2x5 썸네일 그리드
│   └── event_preview_panel.py         # 미리보기 패널
└── workers/
    ├── sequence_generation_worker.py  # Sliding Window Inpaint 생성
    └── person_mask_generator.py       # YOLO 인물 마스크 생성
```

---

## 아키텍처

```
TurboEventSequenceTab (State Machine: IDLE → CONFIRMED → READY → FIRST_DONE → GENERATING)
    ├── EventSearchWidget (검색, Favorites, 연속/랜덤 생성 제어)
    │     ├── EventSearcher (Parquet 검색 엔진)
    │     └── DatasetDownloadWorker / DatasetLoaderThread
    ├── SequenceTabContainer (Preview + Edit Tabs, 빠른 생성)
    │     ├── SequencePreviewWidget
    │     └── SequenceEditWidget
    ├── ImageViewerWidget + Controls + HistoryPanel
    └── SequenceGenerationWorker (Background Thread)
          └── PersonMaskGenerator (YOLO 기반)
```

---

## 핵심 컴포넌트

### 1. TurboEventSequenceTab

**상태 머신**:
```python
STATE_IDLE = 0           # 시퀀스 미선택
STATE_CONFIRMED = 1      # 시퀀스 확정, 해상도 선택 필요
STATE_READY = 2          # 해상도 선택됨, 생성 가능
STATE_FIRST_DONE = 3     # 첫 페이지 생성 완료
STATE_GENERATING = 4     # 생성 중
```

**핵심 메서드**:

| 메서드 | 설명 |
|--------|------|
| `_on_parent_selected(parent_id, sequence_df)` | Parent 선택 시 시퀀스 로드 |
| `_on_sequence_confirmed(prompts)` | 시퀀스 확정, 자동 가로 해상도 |
| `_on_quick_first_page(prompts)` | 결정 + 첫 페이지 생성 |
| `_on_quick_all_pages(prompts)` | 결정 + 전체 생성 |
| `_start_full_generation(start_index)` | 전체 시퀀스 생성 (Skip 필터링) |
| `_on_regenerate_clicked()` | 현재 인덱스 재생성 |

**주요 상태 변수**:
- `self._index_mapping` - Skip 기능용 Worker → 원본 인덱스 매핑
- `self._waiting_continuous_after_grid_save` - 연속 생성 그리드 저장 대기

### 2. EventSearchWidget (재사용 가능)

검색 UI, 데이터셋 다운로드, Favorites 관리, 연속/랜덤 생성 제어.

**시그널**:
```python
parent_selected = pyqtSignal(int, object)          # parent_id, sequence_df
continuous_generation_requested = pyqtSignal(int)  # 연속 생성 요청
```

**재사용**:
```python
from tabs.turbo_event_sequence.widgets.event_search_widget import EventSearchWidget
search_widget = EventSearchWidget(app_context, parent)
search_widget.parent_selected.connect(on_parent_selected)
```

### 3. EventSearcher (검색 엔진)

```python
class EventSearcher:
    def search_parents(self, include, exclude, min_children, max_children, ratings) -> DataFrame
    def search_parents_by_child_tags(self, child_include, child_exclude, ...) -> DataFrame
    def get_sequence(self, parent_id: int) -> DataFrame  # Parent + Children
    def get_random_parents(self, n: int, **search_kwargs) -> DataFrame
```

### 4. SequenceGenerationWorker

**해상도 상수**:
```python
SAMPLE_SIZE_H = (1152, 832)    # txt2img 가로
CANVAS_SIZE_H = (832, 1216)    # Inpaint 캔버스 가로
PASTE_SIZE_H  = (832, 608)     # 이전 이미지 붙여넣기 가로
# V 변형은 가로/세로 반전
```

**시그널**:
```python
image_generated = pyqtSignal(int, object)      # worker_index, PIL.Image
generation_finished = pyqtSignal(list)          # [PIL.Image, ...]
generation_error = pyqtSignal(int, str)
```

**경계선 삽입**: 600~608px 영역에 검은색 직사각형을 그려 Split Screen 유도.

**배경 정보 유지 모드** (`keep_background=True`): 상하(또는 좌우) 모두 동일 이미지를 배치하고, `PersonMaskGenerator`(YOLO)로 인물 영역만 Inpaint.

### 5. PersonMaskGenerator

YOLO v8 기반 인물 세그멘테이션. `ultralytics` 미설치 시 기본 마스크로 폴백.

```python
EXPANSION_RATIO = 1.07       # 마스크 확장 비율
CONFIDENCE_THRESHOLD = 0.25  # YOLO 신뢰도 임계값
```

### 6. HistoryPanel

```
- 0번: 결합된 그리드 이미지 (드래그 불가)
- 1번~: 개별 생성 결과 이미지 (드래그 가능)
```

**개별 이미지 자동 저장**: `auto_save_enabled=True`일 때 각 이미지 생성 직후 WEBP 저장.
- Parent: `{output_dir}/grid/parent_{timestamp}.webp`
- Child: `{output_dir}/grid/parent-child{N}_{timestamp}.webp`

### 7. SequenceInpaintDialog

히스토리 패널에서 개별 이미지 수동 인페인트 편집. 8x8 격자 기반 마스크, Strength 슬라이더(0.01~1.00), 요청 ID 기반 응답 필터링.

### 8. Event Viewer

생성된 이벤트 탐색 다이얼로그 (모달리스). 2x5 썸네일 그리드 + 미리보기 + 검색(Parent/Child 태그).

**키보드**: `arrow` 이동, `PgUp/PgDn` 페이지, `Enter` 선택, `Shift+Enter` 바로 생성(다이얼로그 유지)

---

## 시그널/슬롯 연결 맵

| Source | Signal | Purpose |
|--------|--------|---------|
| EventSearchWidget | `parent_selected` | 시퀀스 로드 |
| EventSearchWidget | `continuous_generation_requested` | 연속 생성 |
| SequenceTabContainer | `sequence_confirmed` | 생성 흐름 시작 |
| SequenceTabContainer | `quick_first_page_requested` / `quick_all_pages_requested` | 빠른 생성 |
| HistoryPanel | `image_selected` | 뷰어 업데이트 |
| HistoryPanel | `skip_toggled` | Skip 동기화 |
| HistoryPanel | `grid_auto_saved` | 연속 생성 트리거 |
| Worker | `image_generated` / `generation_finished` | 이미지 처리 |

---

## 데이터 흐름

### 생성 흐름

```
_start_full_generation()
  → disabled_indices 필터링, _index_mapping 생성
  → SequenceGenerationWorker.start_generation()
    → Parent: txt2img / Children: inpaint (경계선 + 이전 이미지)
    → image_generated.emit(worker_index, image)
  → Tab._on_image_generated()
    → actual_index = _index_mapping[worker_index]
    → HistoryPanel.add_image() → 개별 자동 저장
    → _update_grid_image()
```

### 연속 생성 흐름

```
generation_finished → _update_grid_image(is_sequence_complete=True)
  → HistoryPanel._auto_save_grid() → grid_auto_saved.emit()
  → search_widget.start_countdown_to_next() → 5초 카운트다운
  → _find_next_parent_id() 또는 _find_random_parent_id()
  → continuous_generation_requested.emit() → 자동 생성 시작
```

---

## 파일 저장 경로

| 파일 유형 | 경로 | 포맷 |
|-----------|------|------|
| 그리드 미리보기 | `save/turbo_events/{parent_id}` | JPEG (절반 해상도) |
| 자동 저장 그리드 | `{output_dir}/grid/sequence_grid_{timestamp}.webp` | WEBP |
| 개별 Parent | `{output_dir}/grid/parent_{timestamp}.webp` | WEBP |
| 개별 Child | `{output_dir}/grid/parent-child{N}_{timestamp}.webp` | WEBP |
| Favorites | `data/NAIA_event_dataset_personal.parquet` | Parquet |

---

## 외부 의존성

- **GenerationController**: `execute_generation_pipeline(overrides=params)` 호출
- **PromptEngineeringModule**: `preprocess_prompt_turbo(prompt)`, `pre_textedit`/`post_textedit`
- **ImageCrudController**: `get_save_directory()`

**Override 파라미터 (인페인트)**:
```python
override_params = {
    'type': 'inpaint', 'input': prompt, 'negative_prompt': neg,
    'image_bytes': canvas_bytes, 'mask_bytes': mask_bytes,
    'width': w, 'height': h, 'strength': 1.0, 'noise': 0.0,
    'random_resolution': False, 'turbo_sequence_request': True,
}
```

---

## 주의사항

### PIL 이미지 Lazy Loading
```python
if hasattr(image, 'load'):
    image.load()
```

### 인덱스 매핑 (Skip 기능)
```python
# Worker 인덱스 → 원본 인덱스 변환
self._index_mapping = [idx for idx, _ in prompts_with_indices]
actual_index = index_mapping[worker_index]
```

### 히스토리 인덱스 변환
```python
# 히스토리 0번 = 그리드, 1번 = 인덱스 0, ...
self.current_viewing_index = history_index - 1
```

### 그리드 자동 저장 중복 방지
```python
# 시퀀스 완료 시에만 trigger_auto_save=True
self.history_panel.update_grid_image(grid_image, trigger_auto_save=is_sequence_complete)
```

### 모달리스 다이얼로그 (Event Viewer)
부모 없이 생성 (`parent=None`) + `show()` 사용. `exec()`나 `parent=self`는 owned window가 되어 항상 위에 표시됨.

```python
self._event_viewer = EventViewerWidget(data_dir, events_dir, None)
self._event_viewer.show()
```

### 포커스 관리 (Event Viewer)
이미지/썸네일 클릭 시 `mousePressEvent`에서 부모 QDialog로 포커스 반환. QLineEdit 포커스 중에는 방향키 기본 동작 유지.

---

## 재사용 가이드

| 컴포넌트 | 재사용성 |
|----------|---------|
| **EventSearchWidget** | 그대로 재사용 가능 |
| **EventSearcher** | 그대로 재사용 가능 |
| **HistoryPanel** | 그대로 재사용 가능 |
| **ImageViewerWidget** | 그대로 재사용 가능 |
| **SequenceGenerationWorker** | 적응 필요 (생성 로직) |
| **TurboEventSequenceTab** | 적응 필요 (상태 머신) |
