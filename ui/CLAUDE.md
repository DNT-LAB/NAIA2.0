# CLAUDE.md — ui/

> **목적**: NAIA 2.0의 UI 시스템 가이드. 테마, 스케일링, 공용 위젯, RightView 탭 컨테이너를 다룹니다.

**📚 레퍼런스 문서** (상세 내용):
- [NovelAI 메타데이터 필드](.claude/metadata_fields_CLAUDE.md)
- [Virtual Module 패턴 가이드](.claude/virtual_module_CLAUDE.md)
- [실전 예제 모음](.claude/examples_CLAUDE.md)
- [문제 해결 가이드](.claude/troubleshooting_CLAUDE.md)

---

## 목차

1. [개요](#개요)
2. [주요 파일 및 역할](#주요-파일-및-역할)
3. [테마 시스템](#테마-시스템)
4. [스케일링 시스템](#스케일링-시스템)
5. [공용 위젯](#공용-위젯)
6. [메타데이터 뷰어](#메타데이터-뷰어)
7. [해상도 관리 다이얼로그](#해상도-관리-다이얼로그)
8. [RightView 탭 컨테이너](#rightview-탭-컨테이너)
9. [분리 창 시스템](#분리-창-시스템)
10. [임시 생성 창 시스템](#임시-생성-창-시스템)
11. [리모트 컨트롤 창](#리모트-컨트롤-창)
12. [체크리스트](#체크리스트)
13. [참고 자료](#참고-자료)

---

## 개요

### ui/ 디렉터리의 역할

ui/는 NAIA 2.0의 **시각적 표현 계층**을 담당합니다:

- 🎨 **테마**: DARK_COLORS 팔레트 및 동적 스타일 생성
- 📏 **스케일링**: DPI 기반 반응형 UI (FHD/QHD/4K 지원)
- 🧩 **공용 위젯**: CollapsibleBox, ModernMenu, DetachedWindow
- 📑 **탭 컨테이너**: EnhancedTabWidget, RightView
- 🔗 **분리/도킹**: 모듈/탭 외부 창 시스템

### 아키텍처

```
NAIA_cold_v4.py (메인 윈도우)
    ↓
ui/theme.py (색상 + 스타일)
ui/scaling_manager.py (DPI 계산)
    ↓
ui/collapsible.py (좌측 모듈 컨테이너)
ui/right_view.py (우측 탭 컨테이너)
ui/modern_menu.py (컨텍스트 메뉴)
ui/detached_window.py (분리 창)
```

**핵심 원칙**:
1. **일관성**: 모든 위젯은 DARK_STYLES 사용
2. **반응성**: get_scaled_font_size/get_scaled_size 필수
3. **UI 스레드 보호**: 무거운 작업은 QThread로 분리
4. **접근성**: 다크 테마 + 충분한 대비

### 다른 디렉터리와의 관계

```
ui/
  ├── core/tab_controller.py, core/middle_section_controller.py에서 사용
  ├── modules/와 tabs/에서 스타일 가져옴
  ├── interfaces/base_tab_module.py, base_middle_module.py에 독립적
  └── utils/image_info.py 등 유틸리티와 협력
```

### 언제 ui/를 수정하는가?

| 작업 | 수정 파일 |
|------|----------|
| **새 색상 추가** | `ui/theme.py` (DARK_COLORS) |
| **새 스타일 추가** | `ui/theme.py` (generate_dark_styles) |
| **스케일 정책 변경** | `ui/scaling_manager.py` |
| **CollapsibleBox 수정** | `ui/collapsible.py` ⚠️ |
| **탭 컨테이너 수정** | `ui/right_view.py` ⚠️ |
| **분리 창 동작 수정** | `ui/detached_window.py` |
| **컨텍스트 메뉴 수정** | `ui/modern_menu.py` |

⚠️ = 전체 UI 영향, 신중히 진행

---

## 주요 파일 및 역할

### UI 시스템 파일

| 파일 | 크기 | 역할 | 주요 클래스/함수 |
|------|------|------|-----------------|
| **theme.py** | 21K | 테마 색상 및 스타일 정의 | `DARK_COLORS`, `generate_dark_styles()`, `DARK_STYLES` |
| **scaling_manager.py** | 7.9K | DPI 기반 UI 스케일링 | `ScalingManager`, `get_scaled_font_size()`, `get_scaled_size()` |
| **collapsible.py** | 10K | 접을 수 있는 모듈 박스 | `EnhancedCollapsibleBox`, `CollapsibleBox` |
| **right_view.py** | 14K | 탭 컨테이너 및 브리징 | `RightView`, `EnhancedTabWidget` |
| **detached_window.py** | 17K | 독립 분리 창 | `DetachedWindow` |
| **modern_menu.py** | 26K | 컨텍스트 메뉴 스타일 | `setModernStyle()`, `setDarkStyle()` |
| **metadata_viewer.py** | 24K | 이미지 메타데이터 뷰어 | `MetadataViewerWindow` (NAI Stealth PNG, Vibe Transfer 복원) |
| **wildcard_manager_window.py** | - | 와일드카드 관리 창 | - |
| **hooker_view.py** | - | 훅 뷰어 (디버깅) | - |
| **resolution_manager_dialog.py** | 8.4K | 해상도 관리 다이얼로그 | `ResolutionManagerDialog` (인접값 자동 제안) |
| **scaling_settings_dialog.py** | - | 스케일링 설정 다이얼로그 | - |
| **inpaint_window.py** | - | 인페인트 윈도우 | - |
| **img2img_panel.py** | - | Img2Img 패널 | - |

---

## 테마 시스템

### 색상 팔레트

**파일**: `ui/theme.py:9-32`

```python
DARK_COLORS = {
    # 배경색
    'bg_primary': '#212121',      # 메인 배경 (매우 어두운 회색)
    'bg_secondary': '#2B2B2B',    # 서브 배경
    'bg_tertiary': '#2B2B2B',     # 카드/위젯 배경
    'bg_hover': '#404040',        # 호버 상태
    'bg_pressed': '#4A4A4A',      # 눌린 상태

    # 텍스트색
    'text_primary': '#FFFFFF',    # 주요 텍스트 (흰색)
    'text_secondary': "#B0B0B0",  # 보조 텍스트 (회색)
    'text_disabled': '#666666',   # 비활성 텍스트

    # 강조색
    'accent_blue': '#1976D2',     # 강조 파란색
    'accent_blue_hover': '#1565C0',
    'accent_blue_light': '#42A5F5',

    # 경계선
    'border': '#333333',          # 기본 경계선
    'border_light': '#666666',    # 밝은 경계선

    # 상태 색상
    'success': '#4CAF50',         # 성공 (녹색)
    'warning': '#FF9800',         # 경고 (주황)
    'error': '#F44336',           # 오류 (빨강)
}
```

**사용 예시**:
```python
from ui.theme import DARK_COLORS

# QWidget 배경색 설정
widget.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")

# 강조 버튼
button.setStyleSheet(f"background-color: {DARK_COLORS['accent_blue']};")
```

### 동적 스타일 생성

**파일**: `ui/theme.py:35-539`

`generate_dark_styles()`는 **스케일링 팩터를 반영한 동적 스타일**을 생성합니다.

**기본 폰트 크기** (QHD 2560x1440 기준):
```python
BASE_FONT_SIZES = {
    'main': 21,          # 메인 텍스트
    'title': 21,         # 제목
    'button': 18,        # 버튼
    'input': 22,         # 입력 필드
    'input_small': 19,   # 작은 입력 필드
    'label': 19,         # 레이블
    'label_small': 16,   # 작은 레이블
    'tab': 19,           # 탭
    'combobox': 19,      # 콤보박스
    'status': 18,        # 상태 표시줄
    'compact': 16,       # 압축 텍스트
    'tiny': 14,          # 아주 작은 텍스트
    'large': 24          # 큰 텍스트
}
```

**기본 크기** (QHD 기준):
```python
BASE_SIZES = {
    'padding_small': 4,
    'padding_medium': 8,
    'padding_large': 12,
    'margin_small': 2,
    'margin_medium': 4,
    'border_radius': 4,
    'border_radius_large': 6,
    'button_height': 16,
    'input_height': 20,
    'checkbox_size': 18,
    'icon_small': 16,
    'icon_medium': 20,
    'icon_large': 24,
    'scrollbar_width': 8,
    'slider_handle': 18
}
```

### DARK_STYLES 사용법

`DARK_STYLES`는 미리 정의된 스타일 딕셔너리입니다.

**주요 스타일 키**:

| 키 | 용도 | 예시 |
|----|------|------|
| `primary_button` | 강조 버튼 | 생성 버튼 |
| `secondary_button` | 보조 버튼 | 취소 버튼 |
| `compact_button` | 작은 버튼 | 인라인 버튼 |
| `toggle_button` | 토글 버튼 | ON/OFF 스위치 |
| `compact_textedit` | 텍스트 편집기 | 프롬프트 입력 |
| `compact_lineedit` | 한 줄 입력 | 검색 바 |
| `dark_checkbox` | 체크박스 | 옵션 선택 |
| `dark_tabs` | 탭 위젯 | 탭 컨테이너 |
| `compact_combobox` | 콤보박스 | 드롭다운 |
| `compact_spinbox` | 숫자 입력 | Steps 설정 |
| `compact_slider` | 슬라이더 | CFG Scale |
| `collapsible_box` | CollapsibleBox | 모듈 컨테이너 |
| `label_style` | 레이블 | 설명 텍스트 |

**사용 예시**:
```python
from ui.theme import DARK_STYLES

# 주요 버튼
self.generate_btn = QPushButton("생성")
self.generate_btn.setStyleSheet(DARK_STYLES['primary_button'])

# 보조 버튼
self.cancel_btn = QPushButton("취소")
self.cancel_btn.setStyleSheet(DARK_STYLES['secondary_button'])

# 텍스트 입력
self.prompt_edit = QTextEdit()
self.prompt_edit.setStyleSheet(DARK_STYLES['compact_textedit'])

# 콤보박스
self.model_combo = QComboBox()
self.model_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
```

### 커스텀 스타일 확장

기존 스타일을 확장하려면:

```python
from ui.theme import DARK_STYLES, DARK_COLORS

# 기본 스타일에 추가
custom_style = f"""
    {DARK_STYLES['primary_button']}
    QPushButton {{
        min-width: 150px;  /* 추가 속성 */
    }}
"""
button.setStyleSheet(custom_style)
```

---

## 스케일링 시스템

### ScalingManager 개요

**파일**: `ui/scaling_manager.py:13-178`

`ScalingManager`는 **DPI 및 해상도 기반 자동 스케일링**을 제공합니다.

#### 지원 해상도

| 해상도 | 권장 스케일 팩터 | 용도 |
|--------|-----------------|------|
| 3840×2160 (4K) | 1.5 | 대형 디스플레이 |
| 2560×1440 (QHD) | 1.0 | **기준 해상도** |
| 1920×1080 (FHD) | 0.8 | 일반 노트북/모니터 |
| 1680×1050 | 0.75 | 중소형 모니터 |
| 1366×768 | 0.65 | 작은 노트북 |
| 1280×720 (HD) | 0.6 | 최소 지원 |

### 스케일링 계산 로직

**파일**: `ui/scaling_manager.py:31-77`

```python
def calculate_scale_factor(self):
    """현재 환경에 맞는 스케일 팩터 계산"""

    # 1. 주 화면 DPI 가져오기
    physical_dpi = primary_screen.physicalDotsPerInch()
    logical_dpi = primary_screen.logicalDotsPerInch()

    # 2. 해상도 정보
    width = geometry.width()
    height = geometry.height()

    # 3. DPI 기반 스케일
    dpi_scale = physical_dpi / self._base_dpi  # 96.0

    # 4. 해상도 기반 스케일
    resolution_scale = self._get_resolution_scale_factor(width, height)

    # 5. 최종 스케일 (더 작은 값 선택)
    base_scale = min(dpi_scale, resolution_scale)
    self._current_scale = base_scale * self._user_scale_factor

    # 6. 범위 제한 (0.5 ~ 2.0)
    self._current_scale = max(0.5, min(2.0, self._current_scale))
```

### 스케일링 함수 사용법

#### get_scaled_font_size()

**파일**: `ui/scaling_manager.py:197-199`

```python
from ui.scaling_manager import get_scaled_font_size

# QHD 기준 21px → FHD에서 17px로 자동 조정
font_size = get_scaled_font_size(21)

# 스타일시트에 사용
label.setStyleSheet(f"font-size: {get_scaled_font_size(21)}px;")
```

#### get_scaled_size()

**파일**: `ui/scaling_manager.py:192-194`

```python
from ui.scaling_manager import get_scaled_size

# QHD 기준 8px → FHD에서 6px로 자동 조정
padding = get_scaled_size(8)

# 레이아웃에 사용
layout.setContentsMargins(
    get_scaled_size(12),
    get_scaled_size(12),
    get_scaled_size(12),
    get_scaled_size(12)
)
```

#### get_current_scale_factor()

```python
from ui.scaling_manager import get_current_scale_factor

# 현재 스케일 팩터 확인 (디버깅용)
current_scale = get_current_scale_factor()
print(f"현재 스케일 팩터: {current_scale}")  # 예: 0.8 (FHD)
```

### 사용자 정의 스케일

**설정 파일**: `save/ui_scaling_settings.json`

```json
{
  "auto_scaling_enabled": true,
  "user_scale_factor": 1.0
}
```

**프로그래밍 방식으로 변경**:
```python
from ui.scaling_manager import get_scaling_manager

manager = get_scaling_manager()

# 사용자 정의 스케일 (1.2배)
manager.set_user_scale_factor(1.2)

# 자동 스케일링 비활성화
manager.set_auto_scaling_enabled(False)

# 스케일링 새로고침 (화면 변경 시)
manager.refresh_scaling()
```

---

## 공용 위젯

### CollapsibleBox: 접을 수 있는 모듈 컨테이너

**파일**: `ui/collapsible.py:11-275`

#### 기본 사용법

```python
from ui.collapsible import EnhancedCollapsibleBox

# CollapsibleBox 생성
box = EnhancedCollapsibleBox(title="내 모듈", parent=None, detachable=True)

# 콘텐츠 레이아웃 설정
content_layout = QVBoxLayout()
content_layout.addWidget(QLabel("모듈 내용"))
content_layout.addWidget(QPushButton("버튼"))

box.setContentLayout(content_layout)

# 분리 시그널 연결
box.module_detach_requested.connect(self._on_module_detach)
```

#### 주요 시그널

| 시그널 | 파라미터 | 설명 |
|--------|----------|------|
| `module_detach_requested` | (str, object) | 모듈 분리 요청 (title, content_widget) |
| `toggled` | (str, bool) | 펼침/접힘 상태 변경 (title, is_expanded) |

#### 주요 메서드

| 메서드 | 설명 | 파라미터 |
|--------|------|----------|
| `setContentLayout(layout)` | 콘텐츠 레이아웃 설정 | QVBoxLayout, QHBoxLayout 등 |
| `update_anlas(value)` | Anlas 표시 업데이트 (NAI) | int 또는 None |
| `set_detached_state(bool)` | 분리 상태 설정 | True=분리됨, False=복귀됨 |
| `get_content_widget()` | 콘텐츠 위젯 반환 | - |
| **🆕 `is_expanded()`** | **현재 펼쳐진 상태 확인** | **반환: bool** |
| **🆕 `set_expanded(expanded, emit_signal)`** | **프로그래밍 방식 펼치기/접기** | **expanded: bool, emit_signal: bool=True** |
| **🆕 `expand(emit_signal)`** | **펼치기 (편의 메서드)** | **emit_signal: bool=True** |
| **🆕 `collapse(emit_signal)`** | **접기 (편의 메서드)** | **emit_signal: bool=True** |
| **🆕 `get_scroll_position()`** | **현재 스크롤 위치 반환** | **반환: int** |
| **🆕 `set_scroll_position(position)`** | **스크롤 위치 설정** | **position: int** |

#### 특징

**1. 접기/펼치기**

`collapsible.py:122-131`

- 제목 버튼 클릭 시 자동 토글
- 화살표 아이콘: ▶ (접힘) / ▼ (펼침)

**2. 우클릭 컨텍스트 메뉴**

`collapsible.py:76-106`

- "🔗 외부 창에서 열기" 액션
- `detachable=True`일 때만 표시

**3. 분리 상태 플레이스홀더**

`collapsible.py:229-270`

분리된 모듈 자리에 표시:
```
🔗
'모듈 이름' 모듈이
외부 창에서 열려있습니다
```

**🆕 4. 스크롤 위치 자동 저장/복원**

`collapsible.py:325-347`

- 접을 때 자동으로 스크롤 위치 저장
- 펼칠 때 저장된 위치로 복원
- `_saved_scroll_position` 내부 변수로 추적

**🆕 5. 프로그래밍 방식 제어**

`collapsible.py:291-323`

```python
# 상태 확인
if box.is_expanded():
    print("펼쳐진 상태")

# 프로그래밍 방식으로 펼치기/접기
box.expand(emit_signal=True)    # 시그널 발행하며 펼치기
box.collapse(emit_signal=False)  # 시그널 없이 접기

# 직접 설정
box.set_expanded(True, emit_signal=True)

# 스크롤 위치 제어
scroll_pos = box.get_scroll_position()
box.set_scroll_position(100)
```

**사용 예시**:
```python
# 아코디언 동작: 다른 박스들 접기
for title, other_box in self.boxes.items():
    if other_box != current_box:
        other_box.collapse(emit_signal=False)  # 시그널 없이 접기

# 상태 복원
if title in saved_expanded_modules:
    box.expand(emit_signal=False)
    box.set_scroll_position(saved_positions.get(title, 0))
```

### ModernMenu: 컨텍스트 메뉴 스타일링

**파일**: `ui/modern_menu.py:61-255`

#### 기본 사용법

```python
from ui.modern_menu import setModernStyle

# QTextEdit에 적용
self.prompt_edit = QTextEdit()
setModernStyle(self.prompt_edit)

# QPlainTextEdit에도 적용 가능
self.plain_edit = QPlainTextEdit()
setModernStyle(self.plain_edit)
```

#### 다크 테마 버전

```python
from ui.modern_menu import setDarkStyle

self.dark_edit = QTextEdit()
setDarkStyle(self.dark_edit)
```

#### 기능

**1. 태그 정보 툴팁**

`modern_menu.py:133-183`

- `data/KR_tags.parquet` 로딩
- 커서 위치 태그 분석
- 태그 정보 표시:
  - 태그 이름 + 사용 횟수
  - Category
  - Description
  - Keywords

**2. 인스턴트 와일드카드 통합**

`modern_menu.py:104-131`

- 텍스트 선택 시 "➕ 인스턴트 와일드카드 추가" 액션
- InstantWildcardModule 자동 감지
- AppContext 계층 탐색

**3. 스케일링 적용**

`modern_menu.py:191-246`

- 모든 크기가 `get_scaled_size()` 사용
- 폰트 크기는 `get_scaled_font_size()` 사용
- 반응형 컨텍스트 메뉴

### QTextEdit 사용 가이드

#### 기본 원칙: Rich Text 차단

**2025-01-17 업데이트**: 모든 QTextEdit에 `setAcceptRichText(False)` 적용 필수

**배경**:
- 웹에서 복사한 텍스트에 색상코드, 폰트, 이탤릭체 등의 서식이 포함됨
- 사용자가 의도하지 않은 서식이 붙여넣기되어 혼란 발생
- Plain Text 모드로 통일하여 일관성 확보

#### 표준 패턴

**모든 QTextEdit 생성 시 필수**:

```python
from PyQt6.QtWidgets import QTextEdit
from ui.theme import DARK_STYLES

# ✅ 올바른 방법 (필수)
self.prompt_edit = QTextEdit()
self.prompt_edit.setAcceptRichText(False)  # 서식 붙여넣기 차단
self.prompt_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
self.prompt_edit.setPlaceholderText("프롬프트를 입력하세요...")

# ❌ 잘못된 방법 (setAcceptRichText 누락)
self.prompt_edit = QTextEdit()
self.prompt_edit.setStyleSheet(DARK_STYLES['compact_textedit'])  # 서식 차단 없음!
```

#### 동작 원리

**setAcceptRichText(False) 효과**:

**차단됨 ❌**:
- 웹에서 복사한 색상코드, 폰트, 크기
- 사용자의 수동 서식 적용 (Ctrl+B, Ctrl+I)
- HTML/Rich Text 드래그앤드롭
- 이탤릭체, 굵게, 밑줄 등 모든 서식

**정상 작동 ✅**:
- `PromptHighlighter`의 구문 하이라이팅 (댓글, 가중치, 시퀀스 토큰)
- 프로그래밍 방식 포맷 적용 (`QTextCharFormat`, `setFormat`)
- Plain Text 입력 및 붙여넣기
- 모든 기존 기능

#### 코드 예시

**1. 기본 텍스트 입력**:
```python
# 프롬프트 입력
self.main_prompt = QTextEdit()
self.main_prompt.setAcceptRichText(False)  # 필수
self.main_prompt.setStyleSheet(DARK_STYLES['compact_textedit'])
setModernStyle(self.main_prompt)  # 컨텍스트 메뉴 + 태그 정보
```

**2. 읽기 전용 표시**:
```python
# 로그 표시용
self.log_display = QTextEdit()
self.log_display.setAcceptRichText(False)  # 읽기 전용도 필수
self.log_display.setReadOnly(True)
self.log_display.setStyleSheet(DARK_STYLES['compact_textedit'])
```

**3. 다이얼로그 내 사용**:
```python
class MyDialog(QDialog):
    def __init__(self):
        super().__init__()

        self.description_edit = QTextEdit()
        self.description_edit.setAcceptRichText(False)  # 다이얼로그도 동일
        self.description_edit.setPlaceholderText("설명 입력...")
```

#### 하이라이팅과의 호환성

**PromptHighlighter는 정상 작동**:

```python
from NAIA_cold_v4 import PromptHighlighter

# QTextEdit 생성
self.prompt_edit = QTextEdit()
self.prompt_edit.setAcceptRichText(False)  # Plain Text 모드

# ✅ 하이라이터는 정상 작동 (내부 포맷 사용)
highlighter = PromptHighlighter(self.prompt_edit.document())

# 결과:
# - 외부 서식은 차단됨
# - 하이라이팅은 정상 표시 (댓글, 가중치, 시퀀스 토큰)
```

#### 적용 범위

**NAIA 2.0 전역 적용** (2025-01-17):

| 파일 | 개수 | 위치 |
|------|------|------|
| `NAIA_cold_v4.py` | 2개 | 메인/네거티브 프롬프트 |
| `modules/character_module.py` | 7개 | 캐릭터 프롬프트, 편집 다이얼로그 |
| `modules/character_reference_module.py` | 2개 | CR 프롬프트/UC |
| `modules/conditional_prompt_module.py` | 2개 | 규칙, 로그 |
| `modules/prompt_engineering_module.py` | 5개 | 선행/후행/자동숨김 프롬프트 |
| `modules/instant_wildcard_module.py` | 2개 | 와일드카드 값 편집 |
| `modules/wildcard_status_module.py` | 2개 | 히스토리, 상태 표시 |
| `modules/e621_event_module.py` | 2개 | 이벤트 태그 |

**총 24개 QTextEdit에 적용됨**

#### 체크리스트

**새 QTextEdit 작성 시**:
```
[ ] setAcceptRichText(False) 호출 확인
[ ] DARK_STYLES['compact_textedit'] 스타일 적용
[ ] setModernStyle() 호출 (선택, 태그 정보 필요 시)
[ ] setPlaceholderText() 설정 (선택)
[ ] 웹 복사 붙여넣기 테스트 (서식 제거 확인)
```

#### 문제 해결

자주 발생하는 문제와 해결 방법은 [.claude/troubleshooting_CLAUDE.md](.claude/troubleshooting_CLAUDE.md)를 참조하세요:

- **Q1**: 스타일이 적용되지 않아요
- **Q2**: 스케일링이 작동하지 않아요
- **Q3**: CollapsibleBox가 비어 보여요
- **Q4**: DetachedWindow가 메인 창 뒤에 숨어요
- **Q5**: ModernMenu 태그 정보가 안 나와요

---

## 분리 창 시스템

### DetachedWindow 개요

`ui/detached_window.py`의 `DetachedWindow` 클래스는 위젯을 메인 윈도우에서 독립된 창으로 분리하는 기능을 제공합니다.

**특징**:
- 완전히 독립적인 창 (태스크바에 별도 아이콘)
- 항상 위에 표시 토글 지원
- 도킹 시스템 (프롬프트 창 ↔ 이미지 결과 창)
- 창 닫힘 시 자동 복귀

### 사용 사례

| 분리 대상 | 위치 | 상태 플래그 |
|-----------|------|-------------|
| 프롬프트 탭 | `NAIA_cold_v4.py` | `prompt_tabs_detached` |
| Custom API 파라미터 | `NAIA_cold_v4.py` | `custom_api_detached` |
| 이미지 생성 결과 탭 | `tabs/image_window.py` | 탭 분리 시스템 |

### 기본 사용 패턴

```python
from ui.detached_window import DetachedWindow

# 1. 상태 플래그 초기화 (__init__에서)
self.my_widget_detached = False
self.my_widget_window = None

# 2. 분리 함수
def detach_my_widget(self):
    if self.my_widget_detached:
        return

    # 위젯을 레이아웃에서 분리
    self.parent_layout.removeWidget(self.my_widget)
    self.my_widget.setParent(None)

    # 래핑 위젯 생성
    detached_widget = QWidget()
    detached_layout = QVBoxLayout(detached_widget)
    detached_layout.addWidget(self.my_widget)

    # DetachedWindow 생성
    self.my_widget_window = DetachedWindow(
        detached_widget,
        "창 제목",
        -1,  # tab_index (-1 = 탭이 아님)
        parent_container=self
    )
    self.my_widget_window.window_closed.connect(self.on_my_widget_window_closed)
    self.my_widget_window.setMinimumSize(400, 300)
    self.my_widget_window.show()

    self.my_widget_detached = True

# 3. 복귀 함수
def reattach_my_widget(self):
    if not self.my_widget_detached:
        return

    # 창에서 위젯 회수
    if self.my_widget_window:
        detached_widget = self.my_widget_window.get_original_widget()
        if detached_widget and detached_widget.layout():
            detached_widget.layout().removeWidget(self.my_widget)
        self.my_widget_window.close()

    # 원래 레이아웃에 추가
    self.my_widget.setParent(None)
    self.parent_layout.addWidget(self.my_widget)

    self.my_widget_detached = False
    self.my_widget_window = None

# 4. 창 닫힘 이벤트
def on_my_widget_window_closed(self, tab_index, widget):
    self.reattach_my_widget()
```

### Custom API 파라미터 분리 창 (2025-01-08)

**구현 위치**: `NAIA_cold_v4.py`

**UI 구조**:
- `custom_api_checkbox` 옆에 🔓/🔒 Detach 버튼
- 버튼은 항상 표시되며, 체크박스가 켜질 때만 활성화
- 분리 시 텍스트박스 높이가 80px → 300px+ 로 확장

**상태 플래그**:
- `custom_api_detached`: 분리 상태 추적
- `custom_api_window`: DetachedWindow 인스턴스 참조

**메서드**:
- `toggle_custom_api_detach()`: 분리/복귀 토글
- `detach_custom_api()`: 외부 창으로 분리
- `reattach_custom_api()`: 원래 위치로 복귀
- `on_custom_api_window_closed()`: 창 닫힘 이벤트 처리

**파라미터 전달**: 분리된 상태에서도 `custom_script_textbox.toPlainText()` 호출로 정상 동작 (위젯 인스턴스 동일)

---

## 리모트 컨트롤 창

### 개요

**파일**: `ui/remote_window.py`

`RemoteWindow`는 메인 윈도우와 독립적으로 동작하는 **컴팩트한 제어 패널**입니다. 멀티 모니터 환경에서 메인 윈도우의 핵심 기능을 분리하여 편리하게 접근할 수 있습니다.

**특징**:
- 🎛️ **탭 기반 UI**: P.엔지니어링, 캐릭터, 이벤트 탭
- 🔗 **모듈 연동**: 메인 윈도우의 모듈과 양방향 동기화
- ⭐ **프리셋 즐겨찾기**: 프리셋 설정을 즐겨찾기로 저장/로드
- 🖼️ **캐릭터 레퍼런스 즐겨찾기**: 이미지 + 메타데이터 저장/로드
- 📋 **클립보드/업로드 지원**: 직접 이미지 업로드 기능

### 탭 구조

```
RemoteWindow
├── P.엔지니어링 탭 (구현 완료)
│   ├── 프리셋 섹션
│   │   ├── 썸네일 + 콤보박스 + 관리 버튼
│   │   └── 즐겨찾기 그리드
│   └── 캐릭터 레퍼런스 섹션
│       ├── Storage 콤보박스 + 현재 썸네일
│       ├── Style Aware + Fidelity 슬라이더
│       ├── C1 자동 할당 체크박스
│       ├── 업로드/클립보드/메타데이터 편집 버튼
│       └── 즐겨찾기 그리드
├── 캐릭터 탭 (구현 완료)
│   ├── 캐릭터 프롬프트 서브탭
│   │   ├── 상단: 인원 수 라디오 (1~6명), 슬롯 선택 라디오 (C1~C6)
│   │   ├── 중단: 폴더 콤보박스 + 폴더 추가/캐릭터 삭제 버튼
│   │   └── 즐겨찾기 그리드 (선택 강조, 좌측 상단 정렬)
│   ├── 즐겨찾기 관리 서브탭
│   │   ├── 좌측: 대형 썸네일 (150x208)
│   │   ├── 우측 상단: 폴더/아이템 콤보박스
│   │   ├── 중단: 프롬프트/UC 편집 영역
│   │   └── 하단: 캐릭터 검색/썸네일 생성/등록/수정/삭제 버튼
│   └── 캐릭터 레퍼런스 서브탭
└── 이벤트 탭 (구현 완료)
    ├── 상단 필터
    │   ├── Rating 체크박스 (g, s, q, e)
    │   ├── 태그 검색 (입력 + 검색 버튼)
    │   ├── 심층 검색 (입력 + 검색 버튼)
    │   └── 정보 표시 (전체/현재 row 수, 초기화 버튼들)
    ├── 이벤트 목록 (스크롤 영역)
    │   └── EventItemWidget (각 이벤트 아이템)
    └── 하단 대기열 관리
        ├── 현재 검색 결과 모두 대기열로 보내기 버튼
        ├── 남은 대기열 표시 + 비우기 버튼
        ├── 자동 생성 체크박스
        └── 생성 시작 버튼
```

### 주요 클래스

#### RemoteWindow (QMainWindow)

**위치**: `ui/remote_window.py`

**생성자 파라미터**:
```python
def __init__(self, main_window, parent=None):
    """
    main_window: MainWindow 인스턴스 (모듈 참조용)
    parent: 부모 위젯
    """
```

**주요 속성**:
```python
# 모듈 참조
self.main_window           # MainWindow 인스턴스
self.preset_manager        # PresetManager 인스턴스
self.character_ref_module  # CharacterReferenceModule 인스턴스

# 프리셋 관련
self.preset_thumbnail_label   # 현재 프리셋 썸네일
self.preset_combo             # 프리셋 콤보박스
self.preset_favorites_folder  # 즐겨찾기 저장 경로

# 캐릭터 레퍼런스 관련
self.char_ref_storage_combo       # Storage 콤보박스
self.char_ref_thumbnail_label     # 현재 썸네일
self.char_ref_style_aware_check   # Style Aware 체크박스
self.char_ref_fidelity_slider     # Fidelity 슬라이더
self.char_ref_auto_assign_check   # C1 자동 할당 체크박스
self.char_ref_favorites_folder    # 즐겨찾기 저장 경로
```

#### CharRefFavoriteItemWidget (QFrame)

**위치**: `ui/remote_window.py`

캐릭터 레퍼런스 즐겨찾기 그리드의 개별 아이템 위젯입니다.

**생성자 파라미터**:
```python
def __init__(self, favorite_data: dict, thumbnail_path: Path = None,
             thumb_width: int = None, thumb_height: int = None,
             is_selected: bool = False, parent=None):
    """
    favorite_data: 즐겨찾기 데이터 (file_hash, style_aware, fidelity, has_metadata)
    thumbnail_path: 썸네일 이미지 경로
    thumb_width/thumb_height: 썸네일 크기
    is_selected: 선택 상태 (녹색 테두리 표시)
    """
```

**시각적 표시**:
- 썸네일 이미지
- Style Aware 체크 표시 (✓)
- Fidelity 값 (예: 0.85)
- 메타데이터 없음 표시 ("No metadata")
- 선택 시 녹색 테두리 (`DARK_COLORS['success']`)

#### CharacterPromptFavoriteItemWidget (QFrame)

**위치**: `ui/remote_window.py`

캐릭터 프롬프트 즐겨찾기 그리드의 개별 아이템 위젯입니다.

**생성자 파라미터**:
```python
def __init__(self, favorite_data: dict, thumbnail_path: Path = None,
             thumb_width: int = None, thumb_height: int = None,
             is_selected: bool = False, parent=None):
    """
    favorite_data: 즐겨찾기 데이터 (name, folder, prompt, uc, thumbnail)
    thumbnail_path: 썸네일 이미지 경로
    thumb_width/thumb_height: 썸네일 크기 (기본: 90x125)
    is_selected: 선택 상태 (녹색 테두리 표시)
    """
```

**시각적 표시**:
- 썸네일 이미지 (없으면 👤 아이콘)
- 캐릭터 이름 (하단 텍스트)
- 선택 시 녹색 테두리 (`DARK_COLORS['success']`)
- 호버 시 파란색 테두리 (`DARK_COLORS['accent_blue']`)

**주요 메서드**:
```python
def set_selected(self, selected: bool):
    """선택 상태 변경 및 스타일 업데이트"""

def _update_style(self):
    """선택 상태에 따른 테두리 색상 변경"""
```

#### EventItemWidget (QFrame)

**위치**: `ui/remote_window.py`

이벤트 탭의 개별 이벤트 아이템 위젯입니다. 1줄 전체를 사용하며 썸네일과 편집 가능한 태그 영역을 포함합니다.

**생성자 파라미터**:
```python
def __init__(self, event_id: str, event_data: dict, parent=None):
    """
    event_id: 이벤트 고유 ID
    event_data: 이벤트 데이터 (source_row, thumbnail, heart, general 등)
    """
```

**주요 시그널**:
```python
instant_generate_requested = pyqtSignal(str)    # 즉시 생성 요청 (event_id)
add_to_queue_requested = pyqtSignal(str)        # 대기열 추가 요청 (event_id)
delete_requested = pyqtSignal(str)              # 삭제 요청 (event_id)
edit_requested = pyqtSignal(str, str)           # 편집 저장 요청 (event_id, new_general)
heart_changed = pyqtSignal(str, int)            # 하트 값 변경 (event_id, new_heart)
rating_changed = pyqtSignal(str, str)           # Rating 변경 (event_id, new_rating)
```

**UI 레이아웃**:
```
┌─────────────────────────────────────────────────────────────┐
│ [썸네일]  │  [General 태그 TextEdit (4:1 상단)]             │
│ 120x167   │─────────────────────────────────────────────────│
│ 중앙크롭  │  [R:등급][✏️수정][🗑️삭제][⚡즉시][📋대기열][♥-][♥값][♥+] │
└─────────────────────────────────────────────────────────────┘
```

**주요 메서드**:
```python
def _load_thumbnail(self):
    """썸네일 로드 - 중앙 크롭하여 영역을 꽉 채움"""
    # KeepAspectRatioByExpanding으로 확대 후 중앙 크롭

def _on_rating_clicked(self):
    """Rating 순환 변경 (g → s → q → e → g)"""

def _on_edit_clicked(self):
    """General 태그 수정 저장"""

def _change_heart(self, delta: int):
    """하트 값 증감"""
```

**썸네일 중앙 크롭**:
```python
# KeepAspectRatioByExpanding으로 확대하여 빈 공간 없이 채움
scaled = pixmap.scaled(
    EVENT_THUMB_WIDTH, EVENT_THUMB_HEIGHT,
    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
    Qt.TransformationMode.SmoothTransformation
)
# 중앙 크롭: 확대된 이미지에서 중앙 부분만 추출
if scaled.width() > EVENT_THUMB_WIDTH or scaled.height() > EVENT_THUMB_HEIGHT:
    x = (scaled.width() - EVENT_THUMB_WIDTH) // 2
    y = (scaled.height() - EVENT_THUMB_HEIGHT) // 2
    cropped = scaled.copy(x, y, EVENT_THUMB_WIDTH, EVENT_THUMB_HEIGHT)
```

### 프리셋 즐겨찾기 시스템

**저장 위치**: `save/remote_preset_favorites/`

**데이터 구조** (`favorites.json`):
```json
{
  "favorites": [
    {
      "preset_name": "my_preset",
      "timestamp": "2025-01-10T12:34:56"
    }
  ]
}
```

**관련 메서드**:
```python
# 즐겨찾기 등록/해제 토글
def _on_preset_toggle_favorite(self)

# 즐겨찾기 그리드 업데이트
def _update_preset_favorites_grid(self)

# 즐겨찾기 아이템 클릭 → 프리셋 적용
def _on_preset_favorite_clicked(self, preset_name)

# 즐겨찾기 아이템 삭제
def _on_preset_favorite_delete(self, preset_name)
```

### 캐릭터 프롬프트 즐겨찾기 시스템

**저장 위치**: `save/character_prompt_favorites/`

캐릭터 프롬프트와 UC를 폴더별로 관리하는 시스템입니다.

**디렉터리 구조**:
```
save/character_prompt_favorites/
├── favorites.json       # 즐겨찾기 목록
├── folders.json         # 폴더 목록
└── thumb_*.png          # 썸네일 이미지
```

**데이터 구조** (`favorites.json`):
```json
{
  "favorites": [
    {
      "name": "sakuya",
      "folder": "기본",
      "prompt": "izayoi sakuya, maid, silver hair",
      "uc": "bad anatomy",
      "thumbnail": "thumb_sakuya_0.png"
    }
  ]
}
```

**데이터 구조** (`folders.json`):
```json
{
  "folders": ["기본", "동방", "블루아카"]
}
```

**관련 메서드**:
```python
# 즐겨찾기 그리드 업데이트 (선택 강조, 좌측 상단 정렬)
def _update_char_prompt_favorites_grid(self)

# 즐겨찾기 클릭 → 선택 슬롯에 적용
def _on_char_prompt_favorite_clicked(self, fav_data: dict)

# 캐릭터 삭제
def _on_char_prompt_delete_character(self)

# 폴더 추가
def _on_char_prompt_add_folder(self)

# 신규 캐릭터 등록
def _on_manage_register_clicked(self)

# 썸네일 생성 (이미지 생성 후 자동 반환)
def _on_manage_gen_thumb_clicked(self)
```

**썸네일 생성 흐름**:
1. 인원 수를 1로 임시 설정
2. C1 프롬프트/UC를 입력값으로 임시 교체
3. `generation_completed_for_redirect` 이벤트 구독
4. 가상 row로 이미지 생성 요청 (`general: "upper body"`)
5. 생성 완료 시 썸네일 영역에 이미지 표시
6. 원래 C1 프롬프트/UC 및 인원 수 복원

**선택 상태 추적**:
```python
# 현재 선택된 캐릭터
self._char_prompt_selected_fav = fav_data

# 그리드 업데이트 시 선택 상태 확인
is_selected = (self._char_prompt_selected_fav.get("name") == fav_data.get("name") and
               self._char_prompt_selected_fav.get("folder") == fav_data.get("folder"))
```

### 캐릭터 레퍼런스 즐겨찾기 시스템

**저장 위치**: `save/remote_char_ref_favorites/`

**데이터 구조** (`favorites.json`):
```json
{
  "favorites": [
    {
      "file_hash": "432c6abdf8c9...",
      "style_aware": true,
      "fidelity": 0.85,
      "has_metadata": true,
      "timestamp": "2025-01-10T12:34:56"
    }
  ]
}
```

**썸네일/메타데이터 저장**:
- `thumbnails/<file_hash>.png` - 썸네일 이미지
- `metadata/<file_hash>.json` - 캐릭터 메타데이터

**관련 메서드**:
```python
# Storage 콤보박스 변경 → UI만 업데이트 (프레임 추가 안함)
def _on_char_ref_storage_changed(self, text: str)

# Storage에서 프레임 적용 (생성 시에만 호출)
def _apply_char_ref_from_storage(self, file_hash: str,
                                  clear_existing: bool = True,
                                  auto_assign_c1: bool = False)

# 현재 UI 상태 업데이트 (콤보박스 기준)
def _update_char_ref_current_ui(self)

# 즐겨찾기 등록/해제 토글
def _on_char_ref_toggle_favorite(self)

# 즐겨찾기 아이템 클릭 → Storage 검증 후 적용
def _on_char_ref_favorite_clicked(self, file_hash: str)

# 메타데이터 편집 다이얼로그
def _open_metadata_edit_dialog(self)

# 클립보드 이미지 붙여넣기
def _on_char_ref_clipboard_image(self)

# 파일 업로드
def _on_char_ref_upload_image(self)
```

### 해시 기반 파일 관리

캐릭터 레퍼런스 이미지는 SHA-256 해시로 관리됩니다.

**해시 계산**:
```python
import hashlib

def get_file_hash(file_path: Path) -> str:
    """파일의 SHA-256 해시 (앞 12자리)"""
    with open(file_path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()[:12]
```

**Storage 연동**:
```python
# 콤보박스에서 해시로 아이템 선택
def _select_char_ref_in_combo_by_hash(self, file_hash: str) -> bool:
    """해시값으로 콤보박스 아이템 선택"""
    for i in range(self.char_ref_storage_combo.count()):
        if self.char_ref_storage_combo.itemData(i) == file_hash:
            self.char_ref_storage_combo.setCurrentIndex(i)
            return True
    return False
```

### 즐겨찾기 검증 로직

즐겨찾기 아이템 클릭 시 Storage에서 원본 이미지 존재 여부를 검증합니다.

```python
def _on_char_ref_favorite_clicked(self, file_hash: str):
    """즐겨찾기 아이템 클릭 → Storage 검증 후 적용"""

    # Storage 콤보박스에서 해시 검색
    found = False
    for i in range(self.char_ref_storage_combo.count()):
        if self.char_ref_storage_combo.itemData(i) == file_hash:
            found = True
            break

    if not found:
        # 원본 이미지가 삭제된 경우 경고
        QMessageBox.warning(
            self, "경고",
            "원본 이미지가 Storage에서 삭제되었습니다.\n"
            "즐겨찾기를 제거하시겠습니까?"
        )
        return

    # 정상 적용
    self._apply_char_ref_from_storage(file_hash)
```

### C1 자동 할당 기능

**체크박스**: "C1 캐릭터 프롬프트에 메타데이터 자동 할당"

**동작**:
1. 캐릭터 레퍼런스 적용 시 메타데이터가 있으면
2. CharacterModule의 `assign_c1()` 메서드 호출
3. C1 외 모든 캐릭터 위젯 비활성화
4. C1에 메타데이터 자동 입력

**관련 코드** (`modules/character_module.py:1583-1614`):
```python
def assign_c1(self, metadata: dict):
    """C1에 메타데이터 할당, 나머지 비활성화"""

    # 모든 프레임 비활성화
    for frame in self.character_frames:
        frame.setEnabled(False)

    # C1만 활성화
    if self.character_frames:
        c1 = self.character_frames[0]
        c1.setEnabled(True)

        # 메타데이터 적용
        if 'chara_name' in metadata:
            c1.name_input.setText(metadata['chara_name'])
        if 'chara_prompt' in metadata:
            c1.prompt_edit.setPlainText(metadata['chara_prompt'])
        if 'undesired_content' in metadata:
            c1.uc_edit.setPlainText(metadata['undesired_content'])
```

### 메타데이터 편집 다이얼로그

**다이얼로그 필드**:
- Character Name (QLineEdit)
- Character Prompt (QTextEdit, 16px 폰트)
- Undesired Content (QTextEdit, 16px 폰트)

**저장 위치**: `save/remote_char_ref_favorites/metadata/<file_hash>.json`

**데이터 구조**:
```json
{
  "chara_name": "캐릭터 이름",
  "chara_prompt": "캐릭터 프롬프트",
  "undesired_content": "제외할 태그"
}
```

### 클립보드/업로드 처리

**임시 이미지 처리 흐름**:

1. 클립보드 붙여넣기 또는 파일 업로드
2. 임시 파일로 저장 (`save/char_ref_temp/`)
3. SHA-256 해시 계산
4. CharacterReferenceModule의 Storage에 등록
5. Storage 콤보박스에서 해당 해시 선택
6. UI 업데이트

```python
def _on_char_ref_clipboard_image(self):
    """클립보드 이미지 붙여넣기"""
    clipboard = QApplication.clipboard()

    # QImage로 가져오기
    image = clipboard.image()
    if image.isNull():
        QMessageBox.warning(self, "경고", "클립보드에 이미지가 없습니다.")
        return

    # 임시 파일로 저장
    temp_dir = Path("save/char_ref_temp")
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"clipboard_{int(time.time())}.png"
    image.save(str(temp_path))

    # Storage에 등록 후 해시 반환
    file_hash = self._register_to_storage(temp_path)

    # 콤보박스에서 선택
    self._select_char_ref_in_combo_by_hash(file_hash)
```

### 이벤트 탭 시스템

**저장 위치**: `save/remote_events/`

이벤트 탭은 이미지 생성 히스토리에서 데이터 프레임을 저장하고, 나중에 해당 설정으로 재생성할 수 있는 시스템입니다.

**디렉터리 구조**:
```
save/remote_events/
├── events.json          # 이벤트 목록 및 메타데이터
└── thumbnails/          # 썸네일 이미지
    └── <event_id>.png
```

**데이터 구조** (`events.json`):
```json
{
  "events": [
    {
      "id": "evt_1704123456_abc123",
      "source_row": { ... },      // 원본 데이터 프레임 (pandas Series → dict)
      "thumbnail": "evt_xxx.png",  // 썸네일 파일명
      "heart": 0,                  // 우선순위 (정렬용)
      "general": "1girl, smile",   // General 태그 (편집 가능)
      "timestamp": "2025-01-10T12:34:56"
    }
  ]
}
```

**필터링 시스템**:

1. **Rating 필터**: 체크박스 (g, s, q, e) - 복수 선택 가능
2. **태그 검색**: General 태그에서 키워드 검색
3. **심층 검색**: 기존 필터에 추가로 AND 조건 적용

**필터 적용 로직**:
```python
def _on_event_filter_changed(self):
    """필터 변경 시 이벤트 목록 업데이트"""
    filtered_events = []

    for event in self.all_events:
        # Rating 필터
        rating = event.get("source_row", {}).get("rating", "g")
        if not self._is_rating_checked(rating):
            continue

        # 태그 검색 필터
        general = event.get("general", "")
        if self.event_search_input.text():
            if self.event_search_input.text().lower() not in general.lower():
                continue

        # 심층 검색 필터 (스택)
        for depth_keyword in self.event_depth_stack:
            if depth_keyword.lower() not in general.lower():
                continue

        filtered_events.append(event)

    self._update_events_list(filtered_events)
```

**대기열 시스템**:

```python
# 대기열에 추가
def _on_event_add_to_queue(self, event_id: str):
    if event_id not in self.event_queue:
        self.event_queue.append(event_id)
    self._update_event_queue_label()

# 대기열 비우기
def _on_event_queue_clear(self):
    self.event_queue.clear()
    self._update_event_queue_label()

# 대기열 상태 표시 업데이트
def _update_event_queue_label(self):
    count = len(self.event_queue) if hasattr(self, 'event_queue') else 0
    self.event_queue_count_label.setText(f"남은 대기열: {count}")

# 생성 시작
def _on_event_generate_start(self):
    if not self.event_queue:
        self._show_warning("알림", "대기열이 비어 있습니다.")
        return

    event_id = self.event_queue.pop(0)
    self._update_event_queue_label()
    self._on_event_instant_generate(event_id)
```

**중복 검사**:

이벤트 저장 시 general 태그 값으로 중복 검사:
```python
def _save_event_to_remote(self, event_data: dict):
    general_tags = event_data.get("general", "")

    # 기존 이벤트에서 동일한 general 태그 검색
    for existing in self.all_events:
        if existing.get("general", "") == general_tags:
            # 중복 발견 - 경고 또는 스킵
            return False

    # 저장 진행
    self.all_events.append(event_data)
    self._save_events_to_file()
    return True
```

**하트 기반 정렬**:

```python
def _sort_events_by_heart(self):
    """하트 값으로 내림차순 정렬"""
    self.all_events.sort(key=lambda e: e.get("heart", 0), reverse=True)
```

### 시각적 피드백

**선택된 즐겨찾기 표시**:

```python
class CharRefFavoriteItemWidget(QFrame):
    def _update_style(self):
        """선택 상태에 따른 스타일 업데이트"""
        if self._is_selected:
            # 선택됨: 녹색 테두리
            self.setStyleSheet(f"""
                QFrame {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    border: 2px solid {DARK_COLORS['success']};
                    border-radius: 4px;
                }}
            """)
        else:
            # 미선택: 기본 테두리
            self.setStyleSheet(f"""
                QFrame {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: 4px;
                }}
            """)

    def set_selected(self, selected: bool):
        """선택 상태 변경"""
        self._is_selected = selected
        self._update_style()
```

**메타데이터 없음 표시**:

```python
# 썸네일 위에 "No metadata" 텍스트 오버레이
if not favorite_data.get('has_metadata', False):
    no_meta_label = QLabel("No metadata")
    no_meta_label.setStyleSheet(f"""
        color: {DARK_COLORS['warning']};
        font-size: {get_scaled_font_size(10)}px;
        background: rgba(0,0,0,0.5);
        padding: 2px;
    """)
    thumb_layout.addWidget(no_meta_label, alignment=Qt.AlignmentFlag.AlignBottom)
```

### 체크리스트

**RemoteWindow 사용 시**:
```
[ ] main_window 참조 전달
[ ] 모듈 초기화 대기 (QTimer.singleShot 사용)
[ ] Storage 콤보박스 초기화
[ ] 즐겨찾기 폴더 생성 확인
[ ] 해시 기반 파일 관리 이해
[ ] C1 자동 할당 로직 확인
```

**즐겨찾기 구현 시**:
```
[ ] favorites.json 구조 준수
[ ] 썸네일/메타데이터 별도 저장
[ ] 삭제 시 관련 파일 정리
[ ] Storage 검증 로직 구현
[ ] 시각적 피드백 (선택 테두리)
```

---

## 체크리스트

### 새 UI 컴포넌트 추가 시

```
[ ] DARK_COLORS 사용 (색상 하드코딩 금지)
[ ] DARK_STYLES 또는 get_dynamic_styles() 사용
[ ] get_scaled_font_size() 사용 (모든 폰트)
[ ] get_scaled_size() 사용 (모든 크기/패딩/마진)
[ ] UI 스레드에서 무거운 작업 금지 (QThread 사용)
[ ] 크기 정책 명시 (Expanding, Preferred 등)
[ ] 접근성 확인 (텍스트 대비, 최소 크기)
[ ] 여러 해상도에서 테스트 (FHD/QHD/4K)
```

### 스타일시트 작성 시

```
[ ] DARK_COLORS 팔레트 사용
[ ] get_scaled_font_size() 함수 호출 (f-string 내)
[ ] get_scaled_size() 함수 호출 (f-string 내)
[ ] 선택자 특수성 고려 (부모 스타일과 충돌 확인)
[ ] hover/pressed 상태 스타일 정의
[ ] disabled 상태 스타일 정의
[ ] 브라우저 개발자 도구처럼 Qt Style Sheet Debugger 활용
```

### CollapsibleBox 사용 시

```
[ ] 제목 명확히 (모듈 이름)
[ ] detachable 파라미터 설정 (True/False)
[ ] setContentLayout() 호출
[ ] 콘텐츠 레이아웃에 최소 1개 이상 위젯
[ ] module_detach_requested 시그널 연결
[ ] 분리 시 DetachedWindow 생성
[ ] 복귀 시 set_detached_state(False) 호출
```

### DetachedWindow 사용 시

```
[ ] widget, title, tab_index, parent_container 전달
[ ] window_closed 시그널 연결
[ ] show() + raise_() + activateWindow() 호출
[ ] 복귀 로직 구현 (window_closed 핸들러)
[ ] 메모리 누수 방지 (deleteLater 또는 추적 딕셔너리)
[ ] 도킹 기능 필요 시 도킹 메뉴 추가
```

### ModernMenu 적용 시

```
[ ] QTextEdit 또는 QPlainTextEdit만 사용
[ ] setModernStyle() 또는 setDarkStyle() 호출
[ ] data/KR_tags.parquet 파일 존재 확인
[ ] InstantWildcardModule 사용 시 AppContext 설정
[ ] 태그 형식: 콤마로 구분 (예: "1girl, smile")
```

---

## 참고 자료

### 관련 문서

- **[최상위 CLAUDE.md](../CLAUDE.md)**: 전체 프로젝트 개요
- **[core/CLAUDE.md](../core/CLAUDE.md)**: MiddleSectionController, TabController
- **[modules/CLAUDE.md](../modules/CLAUDE.md)**: 모듈 개발 (CollapsibleBox 사용)
- **[tabs/CLAUDE.md](../tabs/CLAUDE.md)**: 탭 개발 (RightView 통합)

### 주요 의존성

**ui/가 의존하는 디렉터리**:
- `data/KR_tags.parquet` - 태그 정보 (ModernMenu)
- `save/ui_scaling_settings.json` - 스케일링 설정

**ui/를 의존하는 디렉터리**:
- `modules/` - DARK_STYLES, CollapsibleBox
- `tabs/` - DARK_STYLES, EnhancedTabWidget
- `core/` - RightView, DetachedWindow
- `NAIA_cold_v4.py` - 모든 UI 컴포넌트

### 예제 코드 위치

| 예제 | 파일 | 라인 |
|------|------|------|
| **DARK_COLORS 정의** | `ui/theme.py` | 9-32 |
| **동적 스타일 생성** | `ui/theme.py` | 35-539 |
| **스케일 계산** | `ui/scaling_manager.py` | 31-77 |
| **CollapsibleBox 생성** | `ui/collapsible.py` | 17-75 |
| **우클릭 메뉴** | `ui/collapsible.py` | 76-106 |
| **🆕 상태 추적 메서드** | `ui/collapsible.py` | 291-347 |
| **🆕 스크롤 위치 저장/복원** | `ui/collapsible.py` | 325-347 |
| **ModernMenu 적용** | `ui/modern_menu.py` | 61-255 |
| **태그 정보 표시** | `ui/modern_menu.py` | 133-183 |
| **🆕 MetadataViewer 메타데이터 병합** | `ui/metadata_viewer.py` | 58-122 |
| **🆕 Vibe Transfer 복원 버튼** | `ui/metadata_viewer.py` | 942-1033 |
| **🆕 NovelAI 메타데이터 추출** | `utils/image_info.py` | 64-120 |
| **DetachedWindow 생성** | `ui/detached_window.py` | 15-87 |
| **도킹 시스템** | `ui/detached_window.py` | 89-146, 347-396 |
| **RightView 초기화** | `ui/right_view.py` | 66-114 |
| **탭 분리** | `ui/right_view.py` | 146-220 |

### 유용한 PyQt6 클래스

| 클래스 | 용도 | 파일 |
|--------|------|------|
| `QToolButton` | CollapsibleBox 제목 | `ui/collapsible.py` |
| `QScrollArea` | CollapsibleBox 콘텐츠 | `ui/collapsible.py` |
| `QMenu` | 컨텍스트 메뉴 | `ui/modern_menu.py`, `ui/collapsible.py` |
| `QAction` | 메뉴 액션 | `ui/detached_window.py` |
| `QMainWindow` | 분리 창 | `ui/detached_window.py` |
| `QTabWidget` | 탭 컨테이너 | `ui/right_view.py` |
| `QTabBar` | 탭 바 (탭 목록) | `ui/right_view.py` |
| `QSplitter` | 크기 조절 가능 분할 | - |

### 디버깅 팁

1. **스타일시트 디버깅**:
```python
# 현재 적용된 스타일시트 확인
print(widget.styleSheet())

# 부모 스타일시트 확인
print(widget.parent().styleSheet())

# 계산된 스타일 확인 (Qt Designer 없이는 어려움)
```

2. **스케일링 디버깅**:
```python
from ui.scaling_manager import get_scaling_manager

manager = get_scaling_manager()
print(f"현재 스케일: {manager.get_scale_factor()}")
print(f"자동 스케일링: {manager.is_auto_scaling_enabled()}")
print(f"사용자 스케일: {manager.get_user_scale_factor()}")

# 스케일 변경 감지
manager.scaling_changed.connect(lambda scale: print(f"스케일 변경: {scale}"))
```

3. **레이아웃 디버깅**:
```python
def debug_layout(layout, indent=0):
    """레이아웃 구조 출력"""
    prefix = "  " * indent
    print(f"{prefix}Layout: {layout.__class__.__name__}, count={layout.count()}")
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item.widget():
            w = item.widget()
            print(f"{prefix}  Widget: {w.__class__.__name__}, size={w.size()}, visible={w.isVisible()}")
        elif item.layout():
            debug_layout(item.layout(), indent + 1)

debug_layout(my_layout)
```

---

## 요약

**ui/의 핵심**:
- ✅ **DARK_COLORS + DARK_STYLES** 필수 사용
- ✅ **get_scaled_font_size() / get_scaled_size()** 모든 크기
- ✅ **QTextEdit.setAcceptRichText(False)** 필수 (2025-01-17)
- ✅ **CollapsibleBox** 모듈 컨테이너 (상태 추적, 스크롤 위치 저장/복원)
- ✅ **EnhancedTabWidget + RightView** 탭 시스템
- ✅ **DetachedWindow** 분리 창
- ✅ **ModernMenu** 컨텍스트 메뉴 + 태그 정보
- ✅ **UI 스레드 보호** 필수

**다음 단계**:
1. [실전 예제](.claude/examples_CLAUDE.md)로 기본 위젯 스타일링 실습
2. 반응형 UI 작성
3. CollapsibleBox 활용
4. ModernMenu 통합
5. 분리 가능 패널 구현

**막힐 때**:
- 스타일/스케일링/위젯 문제 → [문제 해결 가이드](.claude/troubleshooting_CLAUDE.md)
- Virtual Module 구현 → [Virtual Module 가이드](.claude/virtual_module_CLAUDE.md)
- 메타데이터 필드 확인 → [메타데이터 레퍼런스](.claude/metadata_fields_CLAUDE.md)

---

*문서 버전: 2.3*
*최종 업데이트: 2025-01-11*
*담당 영역: ui/ 디렉터리*
*변경사항:*
- *🆕 **캐릭터 탭 (Character Tab) 구현 완료** (v2.3)*
  - *캐릭터 프롬프트 서브탭: 인원 수/슬롯 선택, 폴더별 즐겨찾기 그리드*
  - *즐겨찾기 관리 서브탭: 대형 썸네일, 프롬프트/UC 편집, 신규 등록*
  - *CharacterPromptFavoriteItemWidget 클래스 (선택 강조, 좌측 상단 정렬)*
  - *썸네일 생성: generation_completed_for_redirect 이벤트 활용*
  - *캐릭터 삭제 기능 (폴더 삭제 → 캐릭터 삭제로 변경)*
  - *저장 경로: save/character_prompt_favorites/ (favorites.json, folders.json)*
- *🆕 **이벤트 탭 (Event Tab) 구현 완료** (v2.2)*
  - *EventItemWidget 클래스: 썸네일 중앙 크롭, General 태그 편집, 버튼 액션*
  - *필터링 시스템: Rating 필터, 태그 검색, 심층 검색 (스택 방식)*
  - *대기열 시스템: 추가/비우기/생성 시작, 자동 생성 옵션*
  - *하트 기반 우선순위 정렬*
  - *중복 검사 (general 태그 기준)*
  - *저장 경로: save/remote_events/ (events.json, thumbnails/)*
- *🆕 **리모트 컨트롤 창 (RemoteWindow)** 문서화 (v2.1)*
  - *P.엔지니어링 탭: 프리셋 즐겨찾기, 캐릭터 레퍼런스 즐겨찾기*
  - *CharRefFavoriteItemWidget 클래스 (선택 상태 시각화)*
  - *해시 기반 파일 관리, Storage 검증 로직*
  - *C1 자동 할당 기능, 메타데이터 편집 다이얼로그*
  - *클립보드/업로드 처리 흐름*
- *🆕 **ResolutionManagerDialog 인접값 자동 제안** (v1.5)*
  - *너비/높이가 64배수가 아닐 때 가장 가까운 lower/upper 값 표시*
  - *표시 형식: "인접값 - 너비: 960 / 1024, 높이: 1088 / 1152"*
  - *유효하지 않은 값만 개별적으로 계산 및 표시*
  - *회색 작은 글씨 (DARK_COLORS['text_secondary'], 11px)*
  - *파일: ui/resolution_manager_dialog.py:194-240*
- *🐛 **버그 수정**: MetadataViewerWindow._on_apply_settings 파라미터 추출 로직 수정 (v1.4)*
  - *기존: `json.loads(Comment)` 실패 시 파라미터 누락 (prompt, negative, width, height만 전달)*
  - *수정: `_extract_all_parameters()` 활용으로 모든 파라미터 정상 추출*
  - *영향: steps, scale, sampler, scheduler 등 모든 생성 파라미터가 MainWindow로 전달됨*
- *🆕 PromptHighlighter: 시퀀스 토큰 하이라이팅 (`:begin`, `:seq`, `:end`) - NAIA_cold_v4.py (v1.3)*
- *🆕 MetadataViewerWindow 섹션 추가 (NovelAI Stealth PNG, Vibe Transfer 복원) (v1.3)*
- *🆕 NovelAI 메타데이터 구조 문서화 (NAID4.5F 기준) (v1.3)*
- *🆕 메타데이터 병합 로직 설명 (Source 필드 보존) (v1.3)*
- *CollapsibleBox 상태 추적 기능 추가 (v1.1)*
- *스크롤 위치 자동 저장/복원 (v1.1)*
- *프로그래밍 방식 제어 메서드 (v1.1)*
*압축 이력: 2785줄 → 약 800줄 (약 71% 감소)*
*레퍼런스 파일 4개로 상세 내용 분리*
