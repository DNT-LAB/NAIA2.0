# CLAUDE.md — Turbo Event Sequence Tab

> **목적**: Turbo Event Sequence 탭의 구조, 워크플로우, 핵심 API를 설명하는 개발자 가이드

---

## 개요

Turbo Event Sequence Tab은 **Sliding Window Inpaint 기반의 연속 이미지 시퀀스 생성** 기능을 제공합니다.
Parquet 데이터셋에서 Parent-Child 관계의 이벤트 시퀀스를 검색하고, NAI API를 통해 연속적인 이미지를 생성합니다.

### 핵심 기능

1. **이벤트 검색**: Parquet 데이터셋에서 Parent/Child 태그 기반 검색
2. **시퀀스 미리보기**: Parent + Children 태그 diff 시각화
3. **프롬프트 편집**: 생성 전 프롬프트 수정 및 Skip 설정
4. **Sliding Window Inpaint**: 첫 이미지 참조 기반 연속 생성
5. **그리드 이미지**: 시퀀스 완료 시 자동 그리드 생성 및 저장
6. **연속 생성**: 다음 이벤트 자동 선택 및 생성

---

## 폴더 구조

```
tabs/turbo_event_sequence/
├── turbo_event_sequence_tab.py   # 📌 메인 탭 모듈 (TurboEventSequenceTabModule, TurboEventSequenceTab)
├── event_search_utils.py          # 📌 Parquet 검색 유틸리티 (EventSearcher)
├── widgets/
│   ├── event_search_widget.py     # 검색 UI + 데이터셋 다운로드
│   ├── sequence_tab_container.py  # 미리보기/수정 탭 컨테이너
│   ├── sequence_preview_widget.py # 시퀀스 미리보기 (Tag diff)
│   ├── sequence_edit_widget.py    # 프롬프트 편집 + Skip 설정
│   ├── history_panel.py           # 생성된 이미지 히스토리
│   └── image_viewer_widget.py     # PIL Image 뷰어
├── workers/
│   ├── __init__.py
│   └── sequence_generation_worker.py  # NAI API 기반 생성 워커
└── docs/  # (참고용 문서)
    ├── PRD_SRS.md
    ├── WORKER_TASK.md
    └── MAIN_TASK.md
```

---

## 핵심 컴포넌트

### 1. TurboEventSequenceTab (메인 위젯)

**파일**: `turbo_event_sequence_tab.py:58-1186`

**역할**: 탭의 전체 레이아웃 및 워크플로우 관리

**상태 머신**:
```python
STATE_IDLE = 0           # 대기 중 (시퀀스 미선택)
STATE_CONFIRMED = 1      # 시퀀스 확정됨, 해상도 선택 필요
STATE_READY = 2          # 해상도 선택됨, 생성 가능
STATE_FIRST_DONE = 3     # 첫 페이지 생성 완료
STATE_GENERATING = 4     # 생성 중
```

**주요 시그널**:
```python
generation_started = pyqtSignal()   # 생성 시작
generation_stopped = pyqtSignal()   # 생성 종료
```

**핵심 메서드**:

| 메서드 | 설명 |
|--------|------|
| `_on_parent_selected(parent_id, sequence_df)` | Parent 선택 시 시퀀스 로드 |
| `_on_sequence_confirmed(prompts)` | 시퀀스 확정 → 자동 가로 해상도 선택 |
| `_start_single_generation(index, is_regenerate)` | 단일 이미지 생성 |
| `_start_full_generation(start_index)` | 전체 시퀀스 생성 |
| `_update_grid_image(is_sequence_complete)` | 그리드 이미지 생성/업데이트 |
| `_save_grid_image(grid_image)` | 그리드 저장 (save/turbo_events/) |

### 2. EventSearchWidget (검색 위젯)

**파일**: `widgets/event_search_widget.py:155-1291`

**역할**: 데이터셋 검색 UI, 다운로드, Favorites 관리

**데이터셋 설정**:
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

**주요 시그널**:
```python
parent_selected = pyqtSignal(int, object)       # Parent 선택
preview_image_ready = pyqtSignal(object)        # 미리보기 이미지
favorite_saved = pyqtSignal(int)                # Favorite 저장 완료
continuous_generation_requested = pyqtSignal(int)  # 연속 생성 요청
```

**외부 UI 컨트롤 참조 패턴**:
```python
def set_ui_controls(self, save_btn, countdown_label, skip_checkbox_getter):
    """탭에서 UI 컨트롤 참조 전달"""
    self._external_save_btn = save_btn
    self._external_countdown_label = countdown_label
    self._skip_checkbox_getter = skip_checkbox_getter

# 사용 시 안전한 접근
save_btn = getattr(self, '_external_save_btn', None)
if save_btn:
    save_btn.setText("💖 Favorite에 저장됨")
```

### 3. SequenceGenerationWorker (생성 워커)

**파일**: `workers/sequence_generation_worker.py:28-640`

**역할**: NAI API를 통한 시퀀스 이미지 생성 (QObject 기반)

**해상도 상수**:
```python
# 첫 번째 이미지 (txt2img)
SAMPLE_SIZE_H = (1152, 832)   # 가로 방향
SAMPLE_SIZE_V = (832, 1152)   # 세로 방향

# Inpaint 캔버스 (절반 확장)
CANVAS_SIZE_H = (832, 1216)   # 가로: 세로로 확장
CANVAS_SIZE_V = (1216, 832)   # 세로: 가로로 확장

# 이전 이미지 붙여넣기 영역 (정확히 절반)
PASTE_SIZE_H = (832, 608)     # 가로 방향
PASTE_SIZE_V = (608, 832)     # 세로 방향
```

**생성 흐름**:
```
1. start_generation() 호출
2. _subscribe_generation_events() - 이벤트 구독
3. _generate_next() - 다음 이미지 생성 요청
   ├── 첫 이미지: _request_txt2img_generation()
   └── 후속 이미지: _request_inpaint_generation()
4. _on_generation_completed() - 결과 수신
5. _crop_result() - Inpaint 결과에서 새 영역 추출
6. image_generated 시그널 발생
7. 반복...
8. generation_finished 시그널 발생
```

**Rating 태그 매핑**:
```python
RATING_TAG_MAP = {
    'g': ['rating:general'],
    's': ['rating:sensitive'],
    'q': ['rating:questionable'],
    'e': ['nsfw', 'rating:questionable'],
}
```

**네거티브 프롬프트 처리**:
```python
def _prepare_negative_prompt(self, negative_prompt: str) -> str:
    """split screen 방지 태그 추가"""
    split_screen_tag = "1.5::split screen::"
    return f"{split_screen_tag}, {negative_prompt}"
```

### 4. SequenceEditWidget (프롬프트 편집)

**파일**: `widgets/sequence_edit_widget.py:27-639`

**역할**: 프롬프트 수정, 태그 하이라이팅, Skip 설정

**하이라이트 색상**:
```python
ADDED_TAG_COLOR = "#FFEB3B"        # 연노랑 (추가된 태그)
AUTO_INSERTED_TAG_COLOR = "#9E9E9E" # 회색 (자동 삽입 태그)
```

**핵심 메서드**:
```python
def set_prompts(prompts: list)          # 프롬프트 설정
def set_highlight_index(index: int)     # 현재 생성 중 하이라이트
def get_disabled_indices() -> set       # Skip된 인덱스 반환
def set_disabled(index: int, disabled: bool)  # 외부에서 Skip 설정
def apply_prompt_engineering(prompt: str) -> str  # PE 적용
```

**시그널**:
```python
prompts_updated = pyqtSignal(list)           # 프롬프트 수정
prompt_engineering_toggled = pyqtSignal(bool) # PE 토글
disable_state_changed = pyqtSignal(int, bool) # Skip 상태 변경
```

### 5. HistoryPanel (히스토리 패널)

**파일**: `widgets/history_panel.py:310-802`

**역할**: 생성된 이미지 썸네일 표시, Skip 동기화, 그리드 관리

**인덱스 구조**:
```
- 0번: 결합된 그리드 이미지 (🖼️ Grid)
- 1번~: 개별 생성 결과 이미지 (#1, #2, ...)
```

**핵심 메서드**:
```python
def prepare_placeholders(count: int)    # 플레이스홀더 미리 생성
def add_image(original_index, image)    # 이미지 추가 (고정 위치)
def update_grid_image(grid_image)       # 그리드 업데이트
def get_ordered_images() -> list        # Skip 제외 이미지 반환
```

---

## 데이터 흐름

### 1. 시퀀스 선택 → 생성

```
EventSearchWidget
    │
    ├─[parent_selected]──▶ TurboEventSequenceTab._on_parent_selected()
    │                           │
    │                           └──▶ SequenceTabContainer.set_sequence()
    │                                     │
    │                                     ├──▶ SequencePreviewWidget
    │                                     │
    │                                     └──▶ SequenceEditWidget
    │
    └─[sequence_confirmed]──▶ TurboEventSequenceTab._on_sequence_confirmed()
                                    │
                                    └──▶ 자동 가로 해상도 선택
                                              │
                                              └──▶ STATE_READY 상태
```

### 2. 이미지 생성 흐름

```
TurboEventSequenceTab._start_full_generation()
    │
    └──▶ SequenceGenerationWorker.start_generation()
              │
              ├──▶ (txt2img) GenerationController.execute_generation_pipeline()
              │         │
              │         └──▶ [generation_completed 이벤트]
              │                   │
              │                   └──▶ _on_generation_completed()
              │                             │
              │                             └──▶ image_generated 시그널
              │
              └──▶ (inpaint) _request_inpaint_generation()
                        │
                        └──▶ _create_inpaint_canvas() + _create_inpaint_mask()
                                  │
                                  └──▶ GenerationController...
```

### 3. 그리드 저장 → 연속 생성

```
TurboEventSequenceTab._on_full_generation_finished()
    │
    └──▶ _update_grid_image(is_sequence_complete=True)
              │
              └──▶ _save_grid_image(grid_image)
                        │
                        ├──▶ save/turbo_events/{parent_id} 저장
                        │
                        └──▶ [연속 생성 모드?]
                                  │
                                  └──▶ EventSearchWidget.start_countdown_to_next()
                                            │
                                            └──▶ 5초 카운트다운
                                                      │
                                                      └──▶ continuous_generation_requested
```

---

## 주요 워크플로우

### 1. 데이터셋 다운로드

```python
# event_search_widget.py
1. _check_and_load_dataset() - 파일 존재 확인
2. _start_download(mode) - DatasetDownloadWorker 시작
3. DatasetDownloadWorker.run() - urllib로 다운로드
4. _on_download_finished() - 로드 시작
5. _load_dataset() - DatasetLoaderThread로 비동기 로드
```

### 2. Favorites 저장

```python
# event_search_widget.py:1049-1111
1. _on_save_favorite_clicked()
2. 기존 parquet 로드 (있으면)
3. 현재 시퀀스 병합
4. parquet 저장
5. JSON에 ID 추가 (_save_favorites_json)
6. favorite_saved 시그널 발생
```

### 3. Skip 기능 동기화

```
HistoryPanel.skip_toggled
    │
    └──▶ TurboEventSequenceTab._on_history_skip_toggled(history_index, is_skipped)
              │
              └──▶ SequenceEditWidget.set_disabled(original_index, is_skipped)

SequenceEditWidget.disable_state_changed
    │
    └──▶ TurboEventSequenceTab._on_disable_state_changed(index, disabled)
              │
              └──▶ _update_grid_image() (Skip된 이미지 제외)
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

4. **MiddleSectionController** (`core/middle_section_controller.py`)
   - `get_module_instance("PromptEngineeringModule")` - 모듈 인스턴스 획득

### 이벤트 구독

```python
# SequenceGenerationWorker에서 구독
app_context.subscribe('generation_completed', callback)
app_context.subscribe('generation_error', callback)
```

### Override 파라미터 (turbo_sequence_request)

```python
override_params = {
    'type': 'inpaint',  # Inpaint 시
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

## 주의사항

### 1. PIL 이미지 Lazy Loading 문제

```python
# 항상 load() 호출 필요
if hasattr(image, 'load'):
    image.load()
```

### 2. PNG 버퍼 변환 (WEBP 등 호환성)

```python
# image_viewer_widget.py, history_panel.py 패턴
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

---

## 디버깅 팁

### 1. 생성 흐름 추적

```python
# turbo_event_sequence_tab.py에서 print 확인
print(f"🎯 Parent selected: {parent_id}")
print(f"✅ Sequence confirmed: {len(prompts)} prompts")
print(f"🚀 Starting full sequence generation...")
```

### 2. 워커 상태 확인

```python
# sequence_generation_worker.py
print(f"[SequenceWorker] 처리된 프롬프트 ({actual_index}): {prompt[:100]}...")
```

### 3. 그리드 레이아웃 확인

```python
# _update_grid_image() 출력
print(f"🖼️ Grid image created: {grid_w}x{grid_h} ({count} images, {layout_type})")
```

---

## 확장 가이드

### 새 데이터셋 모드 추가

```python
# event_search_widget.py의 DATASET_CONFIG에 추가
DATASET_CONFIG = {
    'NewMode': {
        'filename': 'new_dataset.parquet',
        'url': 'https://...',
        'description': '설명'
    },
    ...
}
```

### 새 해상도 옵션 추가

```python
# sequence_generation_worker.py의 상수 수정
SAMPLE_SIZE_NEW = (width, height)
CANVAS_SIZE_NEW = (canvas_w, canvas_h)
PASTE_SIZE_NEW = (paste_w, paste_h)
```

---

*문서 버전: 2025-01-14*
*최종 검토: Turbo Event Sequence Tab 전체 구조 분석*
