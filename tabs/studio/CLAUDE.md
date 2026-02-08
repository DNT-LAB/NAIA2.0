# CLAUDE.md — Studio Tab 개발 가이드

> **목적**: Studio Tab의 구조, 기능, 확장 방법을 설명하는 가이드입니다.

---

## 개요

Studio Tab은 **다중 프레임 이미지 생성 워크플로우**를 제공하는 고급 생성 도구입니다. 단일 이미지 생성을 넘어, 여러 프롬프트와 설정을 동시에 관리하고 순차적으로 생성할 수 있습니다.

### 핵심 기능

| 기능 | 설명 |
|------|------|
| **다중 프레임 그리드** | 3x4 (기본) 그리드로 최대 12개 프레임 동시 관리 |
| **이미지 스택** | 각 프레임은 여러 이미지를 스택으로 보관 (반복 생성 지원) |
| **개별 프롬프트** | 프레임별 개별 프롬프트 및 네거티브 프롬프트 설정 |
| **개별 해상도** | 프레임별 해상도 오버라이드 |
| **글로벌 프롬프트** | Prefix/Postfix/Negative 프롬프트 전역 적용 |
| **프리셋 시스템** | 프레임 구성을 프리셋으로 저장/불러오기 (부분 로드 지원) |
| **그리드 내보내기** | 여러 프레임 이미지를 하나의 그리드 이미지로 내보내기 (클립보드 복사 지원) |
| **시드 고정** | 마지막 생성 시드를 기억하여 동일 시드로 반복 생성 |
| **스택 네비게이션** | Expand 버튼으로 스택된 이미지를 탐색하고 선택 |

---

## 디렉터리 구조

```
tabs/studio/
├── CLAUDE.md              # 본 문서
├── __init__.py            # 모듈 초기화
├── frame.py               # ResultImageFrame - 개별 프레임 위젯
├── manager.py             # ResultImageFrameManager - 그리드 관리자
├── sequence_generator.py  # 🆕 시퀀스 텍스트 생성 유틸리티
└── dialogs/               # 다이얼로그 모음
    ├── __init__.py        # 다이얼로그 exports
    ├── prompt_dialog.py   # PromptSettingDialog - 프롬프트 편집 (Seed UI 숨김)
    ├── detached_textedit_dialog.py  # 분리형 텍스트 편집
    ├── export_dialog.py   # ExportViewsDialog - 그리드 이미지 내보내기 (클립보드 지원)
    ├── save_preset_dialog.py   # SavePresetDialog - 프리셋 저장
    ├── open_preset_dialog.py   # OpenPresetDialog - 프리셋 불러오기 (부분 로드, Get :Sequence)
    ├── events_dialog.py   # EventsDialog - 일괄 프롬프트 편집 (Get :Sequence)
    ├── preview_dialog.py  # PreviewDialog - 이미지 미리보기 (스택 네비게이션 지원)
    └── sequence_text_dialog.py  # 🆕 SequenceTextDialog - 시퀀스 텍스트 표시/복사
```

### 상위 파일

```
tabs/
├── studio_tab.py          # StudioTab - 메인 탭 클래스 (tabs/studio/ 사용)
└── studio/                # 본 디렉터리
```

---

## 핵심 컴포넌트

### 1. ResultImageFrame (`frame.py`)

개별 프레임 위젯으로, 이미지 표시와 프롬프트 관리를 담당합니다.

**주요 속성**:
```python
class ResultImageFrame(QFrame):
    index: int                    # 프레임 인덱스 (0-based)
    image_stack: list[QPixmap]    # 이미지 스택
    pil_image_stack: list[Image]  # PIL 이미지 스택 (저장/내보내기용)
    current_stack_index: int      # 현재 표시 중인 이미지 인덱스
    prompt_data: dict             # 프롬프트 설정
```

**prompt_data 구조**:
```python
{
    "prompt": str,           # 메인 프롬프트
    "negative_prompt": str,  # 네거티브 프롬프트
    "seed": int,             # 시드 (-1 = 랜덤)
    "enabled": bool,         # 생성 활성화 여부
    "resolution": str        # 해상도 (예: "1024 x 1024")
}
```

**시그널**:
```python
generate_requested = pyqtSignal(int)       # 생성 요청
delete_requested = pyqtSignal(int)         # 삭제 요청
prompt_edit_requested = pyqtSignal(int)    # 프롬프트 편집 요청
save_requested = pyqtSignal(int)           # 저장 요청
save_all_requested = pyqtSignal(int)       # 전체 저장 요청
resolution_changed = pyqtSignal(int, str)  # 해상도 변경
```

**주요 메서드**:
```python
# 이미지 관리
add_image(pixmap, pil_image=None)  # 스택에 이미지 추가
show_next_image()                   # 다음 이미지 표시
show_prev_image()                   # 이전 이미지 표시
clear_stack()                       # 스택 초기화
get_current_pil_image()             # 현재 PIL 이미지 반환 (내보내기용)

# 프롬프트 관리
set_prompt_data(data)               # 프롬프트 설정
get_prompt_data()                   # 프롬프트 반환
has_prompt()                        # 프롬프트 설정 여부

# 해상도 관리
set_resolution(resolution)          # 해상도 설정
get_resolution()                    # 해상도 반환

# 상태 관리
set_generating_state(is_generating) # 생성 중 상태 표시
reset()                             # 초기 상태로 리셋
```

### 2. ResultImageFrameManager (`manager.py`)

프레임 그리드를 관리하고 순차 생성을 제어합니다.

**주요 속성**:
```python
class ResultImageFrameManager(QObject):
    frames: List[ResultImageFrame]  # 프레임 목록
    grid_rows: int                  # 그리드 행 수 (기본 3)
    grid_cols: int                  # 그리드 열 수 (기본 4)
    is_generating: bool             # 생성 진행 중 여부
    generation_queue: List[tuple]   # 생성 대기열 [(frame_index, repeat_index), ...]

    # 시드 고정 관련
    fix_seed_mode: bool             # 시드 고정 모드 활성화 여부
    last_generated_seed: Optional[int]  # 마지막 생성 시드
```

**시그널**:
```python
generation_started = pyqtSignal()              # 생성 시작
generation_stopped = pyqtSignal()              # 생성 중지
generation_progress = pyqtSignal(int, int)     # 진행률 (current, total)
frame_updated = pyqtSignal(int)                # 프레임 업데이트 요청
prompt_edit_requested = pyqtSignal(int)        # 프롬프트 편집 요청
```

**주요 메서드**:
```python
# 그리드 생성
create_grid(rows=3, cols=4)         # 스크롤 가능한 그리드 생성

# 프레임 관리
add_frame()                         # 새 프레임 추가
insert_frame_at(position)           # 특정 위치에 프레임 삽입
remove_frame(index)                 # 프레임 제거
get_frame(index)                    # 프레임 반환
get_active_frames()                 # 활성(프롬프트 있는) 프레임 목록

# 생성 제어
start_generation(repeat_count=1)    # 순차 생성 시작
stop_generation()                   # 생성 중지
on_generation_completed(index, pixmap, pil_image)  # 생성 완료 콜백
on_generation_failed(index, error)  # 생성 실패 콜백

# 뷰 저장/로드
save_current_view(filepath)         # 뷰 설정 저장
load_view(filepath)                 # 뷰 설정 로드
reset_all_frames()                  # 모든 프레임 리셋

# 시드 고정
set_fix_seed_mode(enabled)          # 시드 고정 모드 설정
get_last_seed()                     # 마지막 시드 반환
set_last_seed(seed)                 # 마지막 시드 저장
```

---

## 다이얼로그

### PromptSettingDialog (`dialogs/prompt_dialog.py`)

프레임별 프롬프트를 편집하는 다이얼로그입니다.

**기능**:
- 메인 프롬프트 입력 (자동완성 지원)
- 네거티브 프롬프트 입력
- ~~시드 설정~~ (v2.1에서 숨김 - 항상 랜덤 시드 사용, "Fix Seed" 체크박스로 대체)
- 해상도 선택 (프레임 헤더에서 설정)

### ExportViewsDialog (`dialogs/export_dialog.py`)

여러 프레임의 이미지를 하나의 그리드 이미지로 내보냅니다.

**기능**:
- 그리드 레이아웃 선택 (3/2/1 열)
- 비대칭 이미지 처리 (정사각형 크롭 또는 패딩)
- PNG/JPEG 저장
- **클립보드 복사** (v2.1 추가)
- QSplitter 기반 레이아웃 (좌측 설정, 우측 실시간 미리보기)

**레이아웃** (v2.1):
```
┌──────────────┬─────────────────────────────────┐
│  설정 패널    │        실시간 미리보기            │
│  (350-400px) │        (확장, 2.25x 크기)        │
└──────────────┴─────────────────────────────────┘
```

**상수**:
```python
MAX_IMAGE_SIZE = 768  # 그리드 셀 당 최대 크기
PREVIEW_SIZES = {1: 768, 2: 512, 3: 368}  # 열 수에 따른 미리보기 크기
```

### SavePresetDialog (`dialogs/save_preset_dialog.py`)

프레임 구성을 프리셋으로 저장합니다.

**기능**:
- 프리셋 이름 입력
- 폴더 선택/생성
- 썸네일 미리보기 (386x386, 검정 배경)

**저장 위치**: `save/studio_presets/`

**상수**:
```python
THUMB_SIZE = 386           # 저장용 썸네일 크기
PREVIEW_THUMB_SIZE = 96    # 미리보기 썸네일 크기
```

### OpenPresetDialog (`dialogs/open_preset_dialog.py`)

저장된 프리셋을 불러오는 3패널 다이얼로그입니다. **부분 로드** 기능을 지원합니다.

**레이아웃**:
```
┌─────────────┬─────────────────┬─────────────┐
│  TreeView   │   상세 정보      │  썸네일     │
│  (폴더/파일) │ (글로벌 프롬프트) │  (2열 그리드) │
│             │ (프레임 목록)    │             │
└─────────────┴─────────────────┴─────────────┘
```

**부분 로드 버튼** (v2.1):
- **Load Events Only**: 프레임 프롬프트만 로드 (글로벌 Prefix/Postfix/Negative 제외)
- **Load Pre/Postfix/Negative**: 글로벌 프롬프트만 로드 (프레임 데이터 제외)
- **Load All**: 전체 프리셋 로드 (기존 동작)

**로드 모드 상수**:
```python
LOAD_ALL = "all"              # 전체 로드
LOAD_EVENTS_ONLY = "events_only"  # 프레임만 로드
LOAD_GLOBAL_ONLY = "global_only"  # 글로벌 프롬프트만 로드
```

**상수**:
```python
THUMBNAIL_DISPLAY_SIZE = 180  # 표시용 썸네일 크기
```

**주요 메서드**:
```python
get_preset_data()  # 로드된 프리셋 데이터 반환
get_load_mode()    # 선택된 로드 모드 반환 (LOAD_ALL/LOAD_EVENTS_ONLY/LOAD_GLOBAL_ONLY)
```

### EventsDialog (`dialogs/events_dialog.py`)

모든 프레임의 프롬프트를 일괄 편집하는 다이얼로그입니다.

**레이아웃**:
```
┌───────────────────────────────────────────────────────────────┐
│ Batch Event Editor                                            │
├───────────────────────────────────────────────────────────────┤
│  #  │       Main Prompt              │  Additional Negative   │
├─────┼────────────────────────────────┼────────────────────────┤
│ [1] │ [prompt textarea (3:2 비율)]   │ [negative textarea]    │
│ [2] │ [prompt textarea]              │ [negative textarea]    │
│ ... │ ...                            │ ...                    │
└─────┴────────────────────────────────┴────────────────────────┘
│                    [Cancel]  [Get :Sequence]  [Apply]         │
└───────────────────────────────────────────────────────────────┘
```

**기능**:
- 모든 프레임의 메인 프롬프트와 네거티브 프롬프트를 한 화면에서 편집
- Apply 버튼으로 일괄 적용
- 기존 해상도, seed, enabled 상태는 보존
- 🆕 **Get :Sequence** 버튼: 현재 이벤트들을 :sequence 텍스트로 변환

**시그널**:
```python
dialog_opened = pyqtSignal()   # 다이얼로그 열림
dialog_closed = pyqtSignal()   # 다이얼로그 닫힘
```

**기본 크기**: 1200x750 (최소), 1350x900 (권장)

### SequenceTextDialog (`dialogs/sequence_text_dialog.py`) 🆕

프레임 이벤트를 :sequence 텍스트 형식으로 변환하여 표시하는 다이얼로그입니다.

**기능**:
- 프레임 데이터를 `:begin, :seq1 [prompt], -[neg], resolution:WxH, :seq2 ..., :end,` 형식으로 변환
- 읽기 전용 TextEdit로 결과 표시
- **Copy to Clipboard**: 전체 텍스트 복사 후 자동 닫힘
- **Copy without :resolution**: resolution 태그를 제외하고 복사 후 자동 닫힘

**버튼 레이아웃**:
```
[Copy to Clipboard] [Copy without :resolution] [Close]
```

**시퀀스 텍스트 형식**:
```
:begin, :seq1 happy, -sad, -angry, resolution:1024x1024, :seq2 excited, resolution:832x1216, :end,
```

- `:begin`, `:end,` - 시퀀스 시작/끝 마커
- `:seqN` - 시퀀스 번호 (1부터 시작)
- `-tag` - 네거티브 프롬프트 태그 (각 태그에 - 접두사)
- `resolution:WxH` - 해상도 태그 (공백 제거됨)

**기본 크기**: 700x400 (최소), 900x500 (권장)

### sequence_generator.py 🆕

시퀀스 텍스트 생성 유틸리티 모듈입니다.

**함수**:
```python
generate_sequence_text(frames_data: List[Dict]) -> str
    # frames_data 구조: [{"prompt": str, "negative_prompt": str, "resolution": str}, ...]
    # 반환: ":begin, :seq1 ..., :end,"

generate_sequence_text_from_preset(preset_data: Dict) -> str
    # 프리셋 JSON에서 시퀀스 텍스트 생성
```

### PreviewDialog (`dialogs/preview_dialog.py`)

이미지 미리보기 다이얼로그입니다. **스택 네비게이션**을 지원합니다.

**기능**:
- 최대 1024px로 리사이즈된 고해상도 미리보기
- 스택에 여러 이미지가 있을 경우 네비게이션 바 표시
- `<` / `>` 버튼으로 이전/다음 이미지 탐색
- `SELECT (n/n)` 버튼으로 현재 이미지 선택 및 대표 이미지 변경

**스택 네비게이션 레이아웃** (stack_size > 1):
```
┌──────────────────────────────────────┐
│                                      │
│         [1024px 이미지 표시]          │
│                                      │
├──────────────────────────────────────┤
│  [<]        SELECT (2/5)        [>]  │
└──────────────────────────────────────┘
```

**시그널**:
```python
image_selected = pyqtSignal(int)  # 스택 인덱스, SELECT 버튼 클릭 시 발신
```

**생성자 파라미터**:
```python
PreviewDialog(
    frame_index: int,                    # 프레임 인덱스
    pil_image: Image = None,             # 단일 이미지 (레거시)
    pixmap: QPixmap = None,              # 단일 픽스맵 (레거시)
    parent = None,
    pil_image_stack: List[Image] = None, # 스택 이미지 목록
    pixmap_stack: List[QPixmap] = None,  # 스택 픽스맵 목록
    current_stack_index: int = 0,        # 초기 표시 인덱스
    on_select_callback: Callable = None  # SELECT 콜백
)
```

**상수**:
```python
PREVIEW_SIZE = 1024  # 미리보기 최대 크기
```

---

## 프리셋 JSON 형식 (v2.0)

```json
{
    "version": "2.0",
    "created_at": "2025-01-08T12:34:56.789000",
    "name": "my_preset",
    "global_prompts": {
        "prefix_prompt": "masterpiece, best quality",
        "postfix_prompt": "",
        "negative_prompt": "worst quality, bad anatomy"
    },
    "frames": [
        {
            "index": 0,
            "prompt_data": {
                "prompt": "1girl, solo",
                "negative_prompt": "",
                "seed": -1,
                "enabled": true,
                "resolution": "1024 x 1024"
            },
            "thumbnail": "base64_encoded_png_data..."
        },
        // ... 추가 프레임
    ]
}
```

**주요 필드**:
- `version`: 프리셋 포맷 버전 ("2.0")
- `global_prompts`: 전역 프롬프트 (Prefix, Postfix, Negative)
- `frames`: 프레임 데이터 배열
  - `prompt_data`: 프레임별 프롬프트 설정
  - `thumbnail`: Base64 인코딩된 386x386 PNG 썸네일

---

## 생성 워크플로우

### 순차 생성 프로세스

```
1. StudioTab._on_generate_all_clicked()
   ↓
2. Manager.start_generation(repeat_count)
   - 활성 프레임 수집
   - generation_queue 구성
   - generation_started 시그널 발신
   ↓
3. Manager._process_next_generation()
   - 큐에서 다음 항목 추출
   - 해당 프레임 generating 상태로 변경
   - frame_updated 시그널 발신
   ↓
4. StudioTab._generate_for_frame(frame_index)
   - 프레임의 prompt_data 수집
   - 글로벌 프롬프트 병합
   - 해상도 오버라이드 적용
   - API 호출
   ↓
5. Manager.on_generation_completed(index, pixmap, pil_image)
   - 프레임에 이미지 추가
   - generating 상태 해제
   - 다음 항목으로 진행 (3번으로)
   ↓
6. (큐 비어있음) generation_stopped 시그널 발신
```

### 프롬프트 병합 규칙

```python
final_prompt = f"{global_prefix} {frame_prompt} {global_postfix}".strip()
final_negative = f"{global_negative} {frame_negative}".strip()
```

---

## 확장 가이드

### 새 다이얼로그 추가

1. `dialogs/` 폴더에 새 파일 생성:

```python
# dialogs/my_dialog.py
from PyQt6.QtWidgets import QDialog, QVBoxLayout
from ui.theme import DARK_COLORS, get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

class MyDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("My Dialog")
        self.setModal(True)

        # 다크 테마 적용
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
            QLabel {{
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        self._create_ui()
```

2. `dialogs/__init__.py`에 export 추가:

```python
from tabs.studio.dialogs.my_dialog import MyDialog

__all__ = [
    # ... 기존 항목
    'MyDialog'
]
```

### 프레임 기능 확장

`ResultImageFrame` 클래스에 새 시그널/메서드 추가:

```python
# frame.py
class ResultImageFrame(QFrame):
    # 새 시그널 추가
    my_custom_signal = pyqtSignal(int, str)

    def my_custom_method(self):
        """새 기능 구현"""
        self.my_custom_signal.emit(self.index, "data")
```

Manager에서 시그널 연결:

```python
# manager.py
def _create_frame(self, index: int) -> ResultImageFrame:
    frame = ResultImageFrame(index)
    # 새 시그널 연결
    frame.my_custom_signal.connect(self._on_my_custom_signal)
    return frame

def _on_my_custom_signal(self, index: int, data: str):
    # 시그널 처리
    pass
```

---

## 스타일링 규칙

### 다크 테마 색상

```python
from ui.theme import DARK_COLORS

# 배경
DARK_COLORS['bg_primary']      # 메인 배경
DARK_COLORS['bg_secondary']    # 보조 배경
DARK_COLORS['bg_tertiary']     # 3차 배경

# 텍스트
DARK_COLORS['text_primary']    # 기본 텍스트 (흰색)
DARK_COLORS['text_secondary']  # 보조 텍스트 (회색)
DARK_COLORS['text_disabled']   # 비활성 텍스트

# 강조
DARK_COLORS['accent_blue']     # 파란색 강조
DARK_COLORS['success']         # 성공 (녹색)
DARK_COLORS['warning']         # 경고 (노란색)
```

### 스케일링 함수

```python
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

# 폰트 크기 (기준: 12px)
font_size = get_scaled_font_size(12)

# 일반 크기 (패딩, 마진, 위젯 크기 등)
padding = get_scaled_size(8)
width = get_scaled_size(100)
```

### 자동완성 비활성화

QLineEdit에 자동완성이 불필요한 경우:

```python
line_edit = QLineEdit()
line_edit.setProperty("autocomplete_ignore", True)
```

---

## 체크리스트

### 새 다이얼로그 추가 시

- [ ] 다크 테마 스타일 적용
- [ ] 모든 텍스트에 `text_primary` 색상 사용
- [ ] 스케일링 함수 사용 (`get_scaled_size`, `get_scaled_font_size`)
- [ ] QLineEdit에 `autocomplete_ignore` 속성 적용 (필요시)
- [ ] `__init__.py`에 export 추가

### 프레임 기능 수정 시

- [ ] 시그널 정의 및 Manager 연결
- [ ] 상태 변경 시 UI 업데이트
- [ ] 리사이즈 이벤트 디바운싱 고려
- [ ] 메모리 누수 방지 (deleteLater 사용)

---

## 관련 문서

- [tabs/CLAUDE.md](../CLAUDE.md) - 탭 개발 가이드
- [ui/CLAUDE.md](../../ui/CLAUDE.md) - UI 컴포넌트 및 테마
- [CLAUDE.md](../../CLAUDE.md) - 프로젝트 최상위 가이드

---

*문서 버전: 2025-01-09*
*Studio Tab v2.2 - 시드 고정, 스택 네비게이션, 부분 로드, 일괄 편집, 시퀀스 생성*
*변경사항 (v2.2):*
- *🆕 시퀀스 텍스트 생성 기능 추가*
  - *`sequence_generator.py` - 시퀀스 텍스트 변환 유틸리티*
  - *`SequenceTextDialog` - 시퀀스 텍스트 표시/복사 다이얼로그*
  - *EventsDialog, OpenPresetDialog에 "Get :Sequence" 버튼 추가*
  - *"Copy without :resolution" 버튼으로 해상도 태그 제외 복사 지원*
- *🐛 Fix Seed 버그 수정: last_seed가 -1일 때 랜덤 시드 생성*
- *🆕 Fix Seed 체크박스 레이블에 현재 시드 값 표시 (예: "Fix Seed (1234567890)")*
