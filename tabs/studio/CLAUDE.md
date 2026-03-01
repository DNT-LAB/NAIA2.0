# CLAUDE.md — Studio Tab 개발 가이드

> **목적**: Studio Tab의 구조, 기능, 확장 방법 가이드

---

## 개요

다중 프레임 이미지 생성 워크플로우. 여러 프롬프트와 설정을 동시에 관리하고 순차 생성.

**핵심 기능**: 3x4 그리드, 이미지 스택(반복 생성), 개별/글로벌 프롬프트, 개별 해상도, 프리셋 저장/로드(부분 로드), 그리드 내보내기(클립보드), 시드 고정, 스택 네비게이션, 시퀀스 텍스트 생성

---

## 디렉터리 구조

```
tabs/studio/
├── frame.py               # ResultImageFrame - 개별 프레임 위젯
├── manager.py             # ResultImageFrameManager - 그리드 관리자
├── sequence_generator.py  # 시퀀스 텍스트 생성 유틸리티
└── dialogs/
    ├── prompt_dialog.py          # 프롬프트 편집 (Seed UI 숨김)
    ├── export_dialog.py          # 그리드 내보내기 (클립보드 지원)
    ├── save_preset_dialog.py     # 프리셋 저장
    ├── open_preset_dialog.py     # 프리셋 불러오기 (부분 로드)
    ├── events_dialog.py          # 일괄 프롬프트 편집 (Get :Sequence)
    ├── preview_dialog.py         # 이미지 미리보기 (스택 네비게이션)
    ├── sequence_text_dialog.py   # 시퀀스 텍스트 표시/복사
    └── detached_textedit_dialog.py
```

상위: `tabs/studio_tab.py` (StudioTab - 메인 탭 클래스)

---

## 핵심 컴포넌트

### ResultImageFrame (`frame.py`)

**prompt_data 구조**:
```python
{"prompt": str, "negative_prompt": str, "seed": int, "enabled": bool, "resolution": str}
```

**시그널**: `generate_requested`, `delete_requested`, `prompt_edit_requested`, `save_requested`, `save_all_requested`, `resolution_changed`

**주요 메서드**: `add_image()`, `show_next/prev_image()`, `clear_stack()`, `get_current_pil_image()`, `set/get_prompt_data()`, `set_generating_state()`

### ResultImageFrameManager (`manager.py`)

그리드 관리 및 순차 생성 제어.

**시그널**: `generation_started`, `generation_stopped`, `generation_progress`, `frame_updated`, `prompt_edit_requested`

**주요 메서드**: `create_grid()`, `start_generation(repeat_count)`, `stop_generation()`, `on_generation_completed()`, `on_generation_failed()`, `save/load_view()`, `set_fix_seed_mode()`

### OpenPresetDialog - 부분 로드

```python
LOAD_ALL = "all"                  # 전체 로드
LOAD_EVENTS_ONLY = "events_only"  # 프레임만 로드
LOAD_GLOBAL_ONLY = "global_only"  # 글로벌 프롬프트만 로드
```

### sequence_generator.py

```python
generate_sequence_text(frames_data: List[Dict]) -> str
# 반환: ":begin, :seq1 happy, -sad, resolution:1024x1024, :seq2 ..., :end,"
```

---

## 프리셋 JSON 형식 (v2.0)

```json
{
    "version": "2.0",
    "global_prompts": {"prefix_prompt": "", "postfix_prompt": "", "negative_prompt": ""},
    "frames": [
        {"index": 0, "prompt_data": {...}, "thumbnail": "base64..."}
    ]
}
```

저장 위치: `save/studio_presets/`

---

## 생성 워크플로우

```
StudioTab._on_start_clicked()
  → Manager.start_generation(repeat_count) → generation_queue 구성
  → Manager._process_next_generation() → frame_updated 시그널
  → StudioTab._on_frame_updated(frame_index)
    → prompt_data 수집, 글로벌 Prefix/Postfix/Negative 병합
    → 독립 랜덤 시드 생성 (Fix Seed OFF 시)
    → gen_controller.execute_generation_pipeline(overrides=override_params)
  → "generation_completed_for_studio" 이벤트
  → StudioTab._on_image_generated() → PIL→QPixmap 변환 (BytesIO)
  → Manager: 큐 남으면 다음 / 비면 unlock
```

### 에러 처리

```
"generation_error_for_studio" 이벤트 → Manager.on_generation_failed() → 다음 프레임 또는 unlock
```

`execute_generation_pipeline`의 `except` 블록에서도 Studio 실패 이벤트를 발행하여 프레임 잠금 해제.

### 프롬프트 병합

```python
full_prompt = ", ".join([prefix, main_prompt, postfix])  # 빈 항목 제외
full_negative = ", ".join([global_negative, additional_negative])
```

---

## 중요 주의사항

### 시드 처리 (독립성 필수)

Studio는 메인 윈도우의 `seed_fix_checkbox`와 **독립적으로** 동작해야 함. override에 항상 seed를 명시적으로 설정.

```python
if fix_seed_mode:
    override_params['seed'] = last_seed  # 없으면 새 랜덤 생성
else:
    override_params['seed'] = random.randint(0, 9999999999)
```

### PIL -> QPixmap 변환 (ImageQt 사용 금지)

```python
# ImageQt는 반복 생성 시 SEGFAULT 발생 (버퍼 참조 문제)
# 반드시 BytesIO 기반 변환 사용
buffer = BytesIO()
image.save(buffer, format='PNG')
buffer.seek(0)
pixmap = QPixmap()
pixmap.loadFromData(buffer.getvalue())
```

### 자동완성 비활성화 (QLineEdit)

```python
line_edit.setProperty("autocomplete_ignore", True)
```

---

## 상수 참조

```python
# export_dialog.py
MAX_IMAGE_SIZE = 768
PREVIEW_SIZES = {1: 768, 2: 512, 3: 368}

# save_preset_dialog.py
THUMB_SIZE = 386, PREVIEW_THUMB_SIZE = 96

# open_preset_dialog.py
THUMBNAIL_DISPLAY_SIZE = 180

# preview_dialog.py
PREVIEW_SIZE = 1024
```

---

## 관련 문서

- [tabs/CLAUDE.md](../CLAUDE.md) - 탭 개발 가이드
- [ui/CLAUDE.md](../../ui/CLAUDE.md) - UI 컴포넌트 및 테마
