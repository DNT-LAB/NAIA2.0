# CLAUDE.md — ui/

> **목적**: NAIA 2.0의 UI 시스템 가이드. 테마, 스케일링, 공용 위젯, RightView 탭 컨테이너를 다룹니다. 시각 일관성과 반응형 UI 유지가 최우선입니다.

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
10. [실전 예제](#실전-예제)
11. [문제 해결](#문제-해결)
12. [체크리스트](#체크리스트)
13. [참고 자료](#참고-자료)
14. [요약](#요약)

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

**Q: 하이라이팅이 안 보여요**
- A: `setAcceptRichText(False)`는 외부 서식만 차단합니다. PromptHighlighter는 정상 작동해야 합니다. QSyntaxHighlighter가 제대로 연결되었는지 확인하세요.

**Q: 프로그래밍 방식 서식도 안 돼요**
- A: `QTextCharFormat`과 `QTextCursor.setCharFormat()`은 정상 작동합니다. 외부 clipboard의 Rich Text만 차단됩니다.

**Q: setAcceptRichText(False)를 까먹었어요**
- A: 웹에서 복사한 텍스트를 붙여넣어보세요. 색상/폰트가 그대로 나타나면 누락된 것입니다.

---

## 메타데이터 뷰어

### MetadataViewerWindow

**파일**: `ui/metadata_viewer.py:19-1069`

이미지 메타데이터를 추출하여 표시하는 모달리스 다이얼로그입니다.

#### 주요 기능

**1. NovelAI 메타데이터 추출 및 병합**

`metadata_viewer.py:58-122`

최신 NovelAI 이미지는 **Stealth PNG** 방식으로 메타데이터를 저장하며, 다음과 같은 계층 구조를 가집니다:

```json
{
  "Software": "NovelAI",
  "Source": "NovelAI Diffusion V4.5 4BDE2A90",  // 최상위 레벨
  "Title": "...",
  "Description": "...",
  "Comment": {  // 중첩 JSON
    "prompt": "1girl, masterpiece, ...",
    "uc": "nsfw, lowres, ...",
    "steps": 28,
    "scale": 5.0,
    "seed": 123456789,
    "reference_image_multiple": [...],  // Vibe Transfer 데이터
    "reference_strength_multiple": [0.6],
    // ... 기타 생성 파라미터
  }
}
```

⚠️ **중요**: 구형 코드는 `Software == 'NovelAI'`일 때 전체 metadata를 Comment로 덮어씌워 **Source 필드가 유실**되었습니다. 현재는 중요 필드를 보존하는 병합 로직을 사용합니다:

```python
# 최신 방식 (ui/metadata_viewer.py:104-120)
if metadata.get('Software') == 'NovelAI':
    if isinstance(metadata.get('Comment'), dict):
        comment_data = metadata['Comment']
        # ✅ Source, Software 및 Vibe Transfer 필드 보존
        important_fields = [
            'Software', 'Source', 'Title', 'Description', 'Generation time',
            'reference_image_multiple', 'reference_strength_multiple',
            'reference_information_extracted_multiple', 'normalize_reference_strength_multiple'
        ]
        preserved = {k: v for k, v in metadata.items() if k in important_fields}

        # Comment 데이터를 기본으로 하고 중요 필드 병합
        result = comment_data.copy()
        result.update(preserved)
        return result
```

**변경 이력 (2025-01-10)**:
- ✅ Vibe Transfer 필드들(`reference_image_multiple`, `reference_strength_multiple`, `reference_information_extracted_multiple`, `normalize_reference_strength_multiple`)을 `important_fields`에 추가
- 🐛 **버그 수정**: 이전에는 NovelAI 메타데이터 병합 시 Vibe Transfer 필드가 유실되어 복원 기능이 작동하지 않았음

**2. Vibe Transfer 복원 기능**

`metadata_viewer.py:942-1033`

NovelAI v4/v4.5 이미지의 Vibe Transfer 데이터를 VibeTransferModule로 복원합니다.

**복원 조건**:
- ✅ 메타데이터에 `reference_image_multiple` 또는 `reference_strength_multiple` 필드 존재
- ✅ Source 필드가 알려진 NAID4 모델 해시와 일치
- ✅ 현재 선택된 모델과 이미지 모델이 일치 (버튼 활성화 조건)

**지원 모델**:
```python
model_map = {
    'NovelAI Diffusion V4.5 4BDE2A90': 'NAID4.5F',  # Full
    'NovelAI Diffusion V4.5 C02D4F98': 'NAID4.5C',  # Curated
    'NovelAI Diffusion V4 7ABFFA2A': 'NAID4.0C',    # v4 Curated
    'NovelAI Diffusion V4 37442FCA': 'NAID4.0F',    # v4 Full
    'Stable Diffusion XL 7BCCAA2C': None            # NAID3 (미지원)
}
```

**버튼 동작**:
- **활성화** (초록색): 현재 모델 = 이미지 모델 → 클릭하면 Vibe 데이터 복원
- **비활성화** (회색): 현재 모델 ≠ 이미지 모델 → 툴팁에 경고 메시지
- **미표시**: NAID3 또는 Vibe 데이터 없음

**복원 프로세스**:
```python
# 1. Vibe 데이터 추출 (metadata_viewer.py:1053-1060)
vibe_data = {
    'normalize_reference_strength_multiple': metadata.get('normalize_reference_strength_multiple'),
    'reference_image_multiple': metadata.get('reference_image_multiple'),
    'reference_strength_multiple': metadata.get('reference_strength_multiple'),
    'reference_information_extracted_multiple': metadata.get('reference_information_extracted_multiple'),  # ✅ NAID3 지원
    'source_model': self._get_model_compatibility()
}

# 2. VibeTransferModule에 no_image 모드로 프레임 추가 (1061-1072)
vibe_module._add_vibe_frame_from_metadata(no_image_path, vibe_data)
```

**주의사항**:
- `reference_information_extracted_multiple`은 NAID3 모델에서만 사용되며, NAID4/4.5에서는 `None` 또는 빈 리스트입니다
- `reference_image_multiple`이 `None`이거나 빈 리스트인 경우 조기 종료됩니다

**3. 3패널 레이아웃**

`metadata_viewer.py:104-353`

- **좌측**: 이미지 미리보기 + 모델 정보 + 액션 버튼
- **중앙**: 프롬프트/네거티브/캐릭터 프롬프트 (NAI v4)
  - 🆕 **Vibe Transfer 복원 버튼** (조건부 표시)
- **우측**: 파라미터 탭 + 원본 데이터 탭

**4. 액션 버튼**

`metadata_viewer.py:199-228`

| 버튼 | 기능 | 시그널 | 메서드 |
|------|------|--------|--------|
| 📝 프롬프트/네거티브 적용 | 메인 UI에 프롬프트 복사 | `apply_prompt` | `_on_apply_prompt` |
| ⚙️ 설정값 일괄 적용 | 모든 생성 파라미터 적용 | `apply_all_settings` | `_on_apply_settings` |
| 🖼️ img2img로 전송 | img2img 패널에 이미지 전송 | `send_to_img2img` | `_on_send_img2img` |
| 📦 Vibe Transfer 복원 | Vibe 데이터 복원 (조건부) | - | `_on_restore_vibe_transfer` |

**⚙️ 설정값 일괄 적용 내부 동작** (`metadata_viewer.py:879-903`)

```python
def _on_apply_settings(self):
    """설정값 일괄 적용"""
    settings = {
        'prompt': self._get_prompt_text(),
        'negative': self._get_negative_text()
    }

    # 소스 모드 식별을 위한 메타데이터 포함
    if 'Software' in self.metadata:
        settings['Software'] = self.metadata['Software']
    if 'type' in self.metadata:
        settings['type'] = self.metadata['type']

    # ✅ _extract_all_parameters() 활용하여 모든 파라미터 추출
    # (Comment, parameters, 직접 필드 등 모든 소스에서 추출)
    extracted_params = self._extract_all_parameters()
    settings.update(extracted_params)

    # 이미지 크기 추가 (덮어쓰기)
    settings['width'] = self.pil_image.width
    settings['height'] = self.pil_image.height

    self.apply_all_settings.emit(settings)
```

**주요 특징**:
- ✅ `_extract_all_parameters()` 메서드를 활용하여 **모든 소스에서 파라미터 추출**
  - Comment 필드 (dict/str 자동 처리)
  - parameters 필드
  - 직접 필드 (steps, scale, seed 등)
- ✅ NAI/WebUI 모드 자동 감지 (`Software`, `type` 필드)
- ✅ 이미지 해상도 자동 추출 (PIL 이미지에서)
- ✅ MainWindow의 `apply_settings_from_metadata`로 전달

**변경 이력 (2025-01-16)**:
- 🐛 **버그 수정**: 기존 코드는 `json.loads(self.metadata['Comment'])`로 파싱 시도했으나, `_validate_and_enhance_metadata`에서 이미 dict로 변환되어 예외 발생
- ✅ `_extract_all_parameters()` 활용으로 파라미터 추출 로직 통일
- ✅ steps, scale, sampler, scheduler 등 모든 생성 파라미터가 정상 추출되도록 수정

#### NovelAI 메타데이터 필드 (NAID4.5F 기준)

⚠️ **주의**: 아래 필드는 NAID4.5F 이미지에서 관찰된 것으로, **모델 버전, 생성 옵션에 따라 다를 수 있습니다**.

**최상위 필드** (Stealth PNG):
```python
'Software': 'NovelAI',
'Source': 'NovelAI Diffusion V4.5 4BDE2A90',
'Title': '...',
'Description': '...',
'Generation time': '...',
```

**Comment 내부 필드** (중첩 JSON):
```python
# 프롬프트
'prompt': str,
'uc': str,  # Negative prompt
'v4_prompt': dict,  # NAI v4 형식 프롬프트
'v4_negative_prompt': dict,

# 생성 파라미터
'steps': int,
'width': int,
'height': int,
'scale': float,  # CFG Scale
'uncond_scale': float,  # UC Strength
'cfg_rescale': float,
'seed': int,
'n_samples': int,
'noise_schedule': str,  # Scheduler
'sampler': str,
'sm': bool,  # SMEA
'sm_dyn': bool,  # SMEA+DYN
'skip_cfg_above_sigma': float,  # VAR+
'skip_cfg_below_sigma': float,

# Vibe Transfer (있을 경우)
'reference_image_multiple': [str],  # base64 인코딩된 이미지
'reference_information_extracted_multiple': [float],
'reference_strength_multiple': [float],

# Director Tools (있을 경우)
'director_references': [...],
'director_reference_strengths': [...],
'director_reference_images': [...],
'director_reference_descriptions': [...],

# 고급 옵션
'lora_unet_weights': str,
'lora_clip_weights': str,
'dynamic_thresholding': bool,
'dynamic_thresholding_percentile': float,
'dynamic_thresholding_mimic_scale': float,
'controlnet_strength': float,
'controlnet_model': str,

# 기타
'legacy_v3_extend': bool,
'deliberate_euler_ancestral_bug': bool,
'prefer_brownian': bool,
'cfg_sched_eligibility': str,
'explike_fine_detail': bool,
'minimize_sigma_inf': bool,
'uncond_per_vibe': bool,
'wonky_vibe_correlation': bool,
'stream': bool,
'version': int,
'request_type': str,
'signed_hash': str,
```

#### 사용 예시

**프로그래밍 방식으로 열기**:
```python
from ui.metadata_viewer import MetadataViewerWindow
from PIL import Image
from utils.image_info import ImageMetadataExtractor

# 이미지 로드
pil_image = Image.open('path/to/image.png')

# 메타데이터 추출
metadata = ImageMetadataExtractor.extract_metadata(pil_image)

# 뷰어 창 열기
viewer = MetadataViewerWindow(
    pil_image=pil_image,
    metadata=metadata,
    app_context=app_context,
    parent=None
)

# 시그널 연결
viewer.apply_prompt.connect(on_apply_prompt)
viewer.apply_all_settings.connect(on_apply_settings)
viewer.send_to_img2img.connect(on_send_img2img)

# Non-modal 창 표시
viewer.show()
```

#### 관련 유틸리티

**메타데이터 추출**: `utils/image_info.py:64-120`

```python
from utils.image_info import ImageMetadataExtractor

# PIL 이미지에서 추출
metadata = ImageMetadataExtractor.extract_metadata(pil_image)

# 파일 경로에서 추출
metadata = ImageMetadataExtractor.extract_metadata('path/to/image.png')

# 메타데이터 존재 여부 확인
has_meta = ImageMetadataExtractor.has_metadata(pil_image)
```

**지원 포맷**:
- PNG: tEXt 청크, Stealth PNG (RGBA 알파 채널)
- JPEG/WEBP: EXIF UserComment
- GIF: Comment 필드

---

## 해상도 관리 다이얼로그

### ResolutionManagerDialog

**파일**: `ui/resolution_manager_dialog.py`

랜덤 해상도 목록을 관리하는 다이얼로그로, 사용자가 해상도를 추가/삭제하고 JSON 파일에 저장할 수 있습니다.

#### 주요 기능

**1. 해상도 목록 관리**

`resolution_manager_dialog.py:44-56`

- 현재 저장된 해상도 목록을 QListWidget에 표시
- 선택한 항목 제거 기능
- 저장 시 `save/resolutions.json`에 자동 저장

**2. 새 해상도 추가**

`resolution_manager_dialog.py:58-101`

사용자가 너비/높이 입력 시:
- 자동으로 면적(픽셀 수) 계산 및 표시
- 1,048,576 픽셀(1024×1024) 초과 시 Anlas 경고 표시 (NAI 전용)
- 배수 조건 확인 (NAI: 64배수, WebUI: 8배수)
- 중복 방지

**🆕 3. 인접값 자동 제안** (2025-01-17)

`resolution_manager_dialog.py:194-240`

너비 또는 높이가 64의 배수가 아닐 때 자동으로 가장 가까운 하한값(lower)과 상한값(upper)을 제안합니다.

**표시 형식**:
```
너비와 높이는 64의 배수여야 합니다.
인접값 - 너비: 960 / 1024, 높이: 1088 / 1152
                                    [자동 맞춤]
```

**계산 로직**:
```python
# 하한값: 입력값을 64로 나눈 몫 × 64
width_lower = (width // 64) * 64

# 상한값: 하한값 + 64
width_upper = width_lower + 64

# 예시: 입력 1000 → 하한값 960, 상한값 1024
```

**특징**:
- 너비와 높이를 개별적으로 계산
- 유효하지 않은 값만 제안 (유효한 값은 표시 안 함)
- 회색 작은 글씨로 표시 (`DARK_COLORS['text_secondary']`, 11px)
- 자동 맞춤 버튼과 함께 표시

**4. 자동 맞춤 기능**

`resolution_manager_dialog.py:161-183`

"자동 맞춤" 버튼 클릭 시:
- 현재 입력값을 가장 가까운 64의 배수로 반올림
- 0으로 반올림되지 않도록 최소값 64로 제한
- 너비/높이 각각 독립적으로 처리

**5. 유효성 검사**

`resolution_manager_dialog.py:185-240`

- API 모드 자동 감지 (NAI: 64배수, WebUI: 8배수)
- 실시간 유효성 검사 (입력 시마다)
- 유효하지 않을 때만 경고 + 인접값 + 자동 맞춤 버튼 표시

#### 사용 예시

**NAIA_cold_v4.py에서 호출**:
```python
def open_resolution_manager(self):
    """해상도 관리 다이얼로그를 열고, 결과를 반영합니다."""
    dialog = ResolutionManagerDialog(self.resolutions, self)

    if dialog.exec():
        new_resolutions = dialog.get_updated_resolutions()
        if new_resolutions:
            self.resolutions = new_resolutions

            # ✅ 파일에 저장
            self._save_resolutions(self.resolutions)

            # 메인 UI 콤보박스 업데이트
            self.resolution_combo.clear()
            self.resolution_combo.addItems(self.resolutions)
```

#### UI 동작 예시

**케이스 1: 너비만 잘못된 경우**
```
입력: 너비 1000, 높이 1024

표시:
너비와 높이는 64의 배수여야 합니다.
인접값 - 너비: 960 / 1024
                        [자동 맞춤]
```

**케이스 2: 둘 다 잘못된 경우**
```
입력: 너비 1000, 높이 1100

표시:
너비와 높이는 64의 배수여야 합니다.
인접값 - 너비: 960 / 1024, 높이: 1088 / 1152
                        [자동 맞춤]
```

**케이스 3: 올바른 경우**
```
입력: 너비 1024, 높이 1024

(경고 메시지 없음, 자동 맞춤 버튼 숨김)
```

#### 저장/로드

**저장 파일**: `save/resolutions.json`

```json
[
  "1024 x 1024",
  "960 x 1088",
  "896 x 1152",
  "832 x 1216",
  "1088 x 960",
  "1152 x 896",
  "1216 x 832"
]
```

**저장 시점**:
- "저장 후 닫기" 버튼 클릭 시 (dialog.exec() == True)
- NAIA_cold_v4.py의 `_save_resolutions()` 메서드 호출

**로드 시점**:
- 앱 시작 시 (`_load_resolutions()`)
- 파일이 없으면 기본값 사용 및 생성

#### 관련 메서드

| 메서드 | 설명 | 파일 |
|--------|------|------|
| `get_updated_resolutions()` | 현재 목록 반환 | resolution_manager_dialog.py:153-158 |
| `add_resolution()` | 새 해상도 추가 | resolution_manager_dialog.py:122-144 |
| `remove_selected_resolution()` | 선택 항목 제거 | resolution_manager_dialog.py:145-152 |
| `update_validation_ui()` | 유효성 검사 + 인접값 표시 | resolution_manager_dialog.py:194-240 |
| `auto_fit_values()` | 자동 맞춤 | resolution_manager_dialog.py:161-183 |
| `_save_resolutions()` | JSON 저장 | NAIA_cold_v4.py:3649-3685 |
| `_load_resolutions()` | JSON 로드 | NAIA_cold_v4.py:3620-3647 |

---

## RightView 탭 컨테이너

### EnhancedTabWidget

**파일**: `ui/right_view.py:15-53`

QTabWidget을 확장하여 **우클릭 탭 분리** 기능을 추가합니다.

#### 주요 기능

**1. 우클릭 컨텍스트 메뉴**

`right_view.py:31-53`

```python
class EnhancedTabWidget(QTabWidget):
    tab_detach_requested = pyqtSignal(int)  # tab_index

    def show_context_menu(self, position: QPoint):
        # 메뉴 생성
        menu = QMenu(self)

        # "외부 창에서 열기" 액션
        detach_action = QAction("🔗 외부 창에서 열기", self)
        detach_action.triggered.connect(lambda: self.tab_detach_requested.emit(tab_index))
        menu.addAction(detach_action)

        # 메뉴 표시
        menu.exec(self.tabBar().mapToGlobal(position))
```

**2. 탭 분리 불가 설정**

```python
# 특정 탭을 분리 불가로 설정
enhanced_tab_widget.set_tab_detachable(tab_index, False)
```

### RightView

**파일**: `ui/right_view.py:55-250`

#### 역할

- TabController를 통한 탭 로딩
- 탭 시그널 브리징 (탭 → MainWindow)
- 탭 분리/복귀 관리

#### 시그널 브리징

`right_view.py:85-114`

```python
class RightView(QWidget):
    # MainWindow로 전달될 시그널들
    instant_generation_requested = pyqtSignal(dict)
    load_prompt_to_main_ui = pyqtSignal(str)
    generate_with_image_requested = pyqtSignal(dict)
    send_to_inpaint_requested = pyqtSignal(object)

    def __init__(self, app_context, parent=None):
        # TabController 초기화
        self.tab_controller = TabController(
            tabs_dir='tabs',
            app_context=self.app_context,
            tab_widget=self.tab_widget,
            parent=self
        )
        self.tab_controller.initialize_tabs()

        # ImageViewer 시그널 브리징
        image_viewer_module = self.tab_controller.get_tab_instance('ImageViewerModule')
        if image_viewer_module:
            image_viewer_module.instant_generation_requested.connect(
                self.instant_generation_requested
            )
            image_viewer_module.load_prompt_to_main_ui.connect(
                self.load_prompt_to_main_ui
            )
```

#### 탭 분리 메서드

`right_view.py:146-220`

```python
def detach_tab(self, tab_index: int, dock_to_window=None):
    """탭을 외부 창으로 분리"""

    # 1. 탭 정보 가져오기
    tab_title = self.tab_widget.tabText(tab_index)
    widget = self.tab_widget.widget(tab_index)

    # 2. DetachedWindow 생성
    detached_window = DetachedWindow(
        widget=widget,
        title=tab_title,
        tab_index=tab_index,
        parent_container=self
    )

    # 3. 닫기 시그널 연결
    detached_window.window_closed.connect(self.reattach_tab)

    # 4. 분리된 창 추적
    self.detached_windows[tab_index] = detached_window
    self.detached_widgets[tab_index] = widget

    # 5. 창 표시
    detached_window.show()
    detached_window.raise_()
    detached_window.activateWindow()
```

---

## 분리 창 시스템

### DetachedWindow

**파일**: `ui/detached_window.py:9-451`

완전히 독립적인 분리 창을 제공합니다.

#### 특징

**1. 완전 독립 창**

`detached_window.py:15-39`

```python
class DetachedWindow(QMainWindow):
    def __init__(self, widget, title, tab_index, parent_container=None):
        # ✅ parent=None으로 완전 독립
        super().__init__(parent=None)

        # 독립적인 윈도우 플래그
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowTitleHint
        )

        # 태스크바에 별도 아이콘 표시
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setWindowIcon(self.get_window_icon())
```

**2. 메뉴 바 제어**

`detached_window.py:148-227`

**창 메뉴 (&W)**:
- `Ctrl+T`: 항상 위에 표시 토글
- `Ctrl+F`: 이 창만 앞으로
- `Ctrl+M`: 이 창 최소화
- `Ctrl+Shift+M`: 메인 UI 활성화
- `Ctrl+R`: 탭으로 복귀

**도킹 메뉴 (&D)** (프롬프트 창 전용):
- 🔗 이미지 결과 창과 도킹

**3. 도킹 시스템**

`detached_window.py:127-146, 347-396`

두 창을 동기화:
- 이동 시 함께 이동 (`moveEvent`)
- 크기 변경 시 높이 동기화 (`resizeEvent`)
- 활성화 시 함께 앞으로 (`changeEvent`, `focusInEvent`)

**4. 키보드 단축키**

`detached_window.py:436-451`

- `F11`: 전체화면 토글
- `Esc`: 전체화면 나가기
- `Ctrl+Shift+M`: 메인 UI 활성화

#### 사용 예시

```python
from ui.detached_window import DetachedWindow

# 분리 창 생성
detached = DetachedWindow(
    widget=my_widget,
    title="내 모듈",
    tab_index=0,
    parent_container=self
)

# 닫기 시그널 연결
detached.window_closed.connect(self._on_window_closed)

# 창 표시
detached.show()
detached.raise_()
detached.activateWindow()
```

---

## 실전 예제

### 예제 1: 테마를 사용한 기본 위젯 (5분)

**목표**: DARK_STYLES로 일관된 UI 만들기

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLineEdit, QTextEdit
from ui.theme import DARK_STYLES, DARK_COLORS

class MyWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        # 메인 배경
        self.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")

        layout = QVBoxLayout(self)

        # 입력 필드
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("검색...")
        self.input_field.setStyleSheet(DARK_STYLES['compact_lineedit'])

        # 텍스트 에디터
        self.text_edit = QTextEdit()
        self.text_edit.setStyleSheet(DARK_STYLES['compact_textedit'])

        # 주요 버튼
        self.save_btn = QPushButton("저장")
        self.save_btn.setStyleSheet(DARK_STYLES['primary_button'])

        # 보조 버튼
        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.setStyleSheet(DARK_STYLES['secondary_button'])

        layout.addWidget(self.input_field)
        layout.addWidget(self.text_edit)
        layout.addWidget(self.save_btn)
        layout.addWidget(self.cancel_btn)
```

### 예제 2: 스케일링을 사용한 반응형 UI (10분)

**목표**: 모든 해상도에서 잘 보이는 UI

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from ui.theme import DARK_STYLES, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

class ResponsiveWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # ✅ 스케일링 적용된 여백
        layout.setContentsMargins(
            get_scaled_size(16),
            get_scaled_size(16),
            get_scaled_size(16),
            get_scaled_size(16)
        )
        layout.setSpacing(get_scaled_size(8))

        # ✅ 스케일링 적용된 폰트
        title = QLabel("제목")
        title.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(24)}px;
                font-weight: 600;
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        subtitle = QLabel("부제목")
        subtitle.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_secondary']};
            }}
        """)

        # ✅ 스케일링 적용된 버튼 크기
        button = QPushButton("확인")
        button.setStyleSheet(f"""
            {DARK_STYLES['primary_button']}
            QPushButton {{
                min-height: {get_scaled_size(40)}px;
                padding: {get_scaled_size(8)}px {get_scaled_size(24)}px;
            }}
        """)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(button)
```

### 예제 3: CollapsibleBox 활용 (15분)

**목표**: 모듈처럼 접고 펼칠 수 있는 섹션 생성

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QCheckBox, QSpinBox
from ui.collapsible import EnhancedCollapsibleBox
from ui.theme import DARK_STYLES

class SettingsPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        # 첫 번째 섹션
        general_box = EnhancedCollapsibleBox(title="일반 설정", detachable=False)
        general_content = QVBoxLayout()

        self.auto_save_cb = QCheckBox("자동 저장")
        self.auto_save_cb.setStyleSheet(DARK_STYLES['dark_checkbox'])

        self.interval_spin = QSpinBox()
        self.interval_spin.setStyleSheet(DARK_STYLES['compact_spinbox'])
        self.interval_spin.setRange(1, 60)
        self.interval_spin.setValue(5)

        general_content.addWidget(self.auto_save_cb)
        general_content.addWidget(QLabel("저장 간격 (분):"))
        general_content.addWidget(self.interval_spin)

        general_box.setContentLayout(general_content)

        # 두 번째 섹션
        advanced_box = EnhancedCollapsibleBox(title="고급 설정", detachable=True)
        advanced_content = QVBoxLayout()

        self.debug_cb = QCheckBox("디버그 모드")
        self.debug_cb.setStyleSheet(DARK_STYLES['dark_checkbox'])

        advanced_content.addWidget(self.debug_cb)

        advanced_box.setContentLayout(advanced_content)

        # 분리 시그널 연결
        advanced_box.module_detach_requested.connect(self._on_detach_requested)

        main_layout.addWidget(general_box)
        main_layout.addWidget(advanced_box)

    def _on_detach_requested(self, title, widget):
        print(f"분리 요청: {title}")
        # DetachedWindow로 열기 (생략)
```

### 예제 4: ModernMenu 통합 (10분)

**목표**: 컨텍스트 메뉴에 태그 정보 표시

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit
from ui.modern_menu import setModernStyle
from ui.theme import DARK_STYLES

class PromptEditor(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # QTextEdit 생성
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.prompt_edit.setPlaceholderText("태그를 입력하세요 (예: 1girl, smile)")

        # ✅ ModernMenu 적용 (태그 정보 + 인스턴트 와일드카드)
        setModernStyle(self.prompt_edit)

        layout.addWidget(self.prompt_edit)

    # 사용자가 태그 위에서 우클릭하면:
    # → data/KR_tags.parquet에서 태그 정보 로드
    # → 태그 이름, 사용 횟수, Category, Description 표시
    # → 텍스트 선택 시 "인스턴트 와일드카드 추가" 액션 제공
```

### 예제 5: 완전한 분리 가능 패널 (30분)

**목표**: 분리할 수 있는 모듈 패널 구현

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from ui.collapsible import EnhancedCollapsibleBox
from ui.detached_window import DetachedWindow
from ui.theme import DARK_STYLES, DARK_COLORS

class DetachablePanel(QWidget):
    def __init__(self):
        super().__init__()
        self.detached_windows = {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 분리 가능한 모듈 박스
        self.box = EnhancedCollapsibleBox(title="내 모듈", detachable=True)

        # 콘텐츠
        content_layout = QVBoxLayout()

        content_layout.addWidget(QLabel("모듈 콘텐츠"))

        btn = QPushButton("액션")
        btn.setStyleSheet(DARK_STYLES['primary_button'])
        content_layout.addWidget(btn)

        self.box.setContentLayout(content_layout)

        # 분리 시그널 연결
        self.box.module_detach_requested.connect(self._on_detach)

        layout.addWidget(self.box)

    def _on_detach(self, title, content_widget):
        """모듈 분리 요청"""
        print(f"분리 요청: {title}")

        # DetachedWindow 생성
        detached_window = DetachedWindow(
            widget=content_widget,
            title=title,
            tab_index=0,  # 모듈은 탭이 아니므로 더미 인덱스
            parent_container=self
        )

        # 닫기 시그널
        detached_window.window_closed.connect(self._on_window_closed)

        # 분리 상태 설정
        self.box.set_detached_state(True)

        # 창 추적
        self.detached_windows[title] = detached_window

        # 창 표시
        detached_window.show()
        detached_window.raise_()
        detached_window.activateWindow()

    def _on_window_closed(self, tab_index, widget):
        """분리 창 닫힘 → 복귀"""
        print("창 닫힘, 위젯 복귀")

        # 위젯을 원래 위치로 복원
        if self.box.content_area:
            widget.setParent(self.box.content_area)
            self.box.content_area.setWidget(widget)

        # 분리 상태 해제
        self.box.set_detached_state(False)

        # 추적 제거
        for title, window in list(self.detached_windows.items()):
            if window.original_widget == widget:
                del self.detached_windows[title]
                break
```

---

## 문제 해결

### Q1: 스타일이 적용되지 않아요

**증상**:
```python
button.setStyleSheet(DARK_STYLES['primary_button'])
# 버튼이 여전히 기본 스타일로 표시됨
```

**원인**:
1. 부모 위젯의 스타일시트가 우선순위 높음
2. Qt 스타일시트 특수성 규칙
3. DARK_STYLES가 최신 스케일 반영 안 됨

**해결**:

1. **스타일 직접 확인**:
```python
from ui.theme import DARK_STYLES

# 스타일 출력
print(DARK_STYLES['primary_button'])

# 정상 출력되는지 확인
```

2. **부모 스타일 확인**:
```python
# 부모 위젯에 너무 구체적인 스타일시트가 있는지 확인
print(parent_widget.styleSheet())

# 해결: 더 구체적인 선택자 사용
button.setStyleSheet(f"""
    QPushButton#myButton {{
        /* ... */
    }}
""")
button.setObjectName("myButton")
```

3. **동적 스타일 강제 갱신**:
```python
from ui.theme import get_dynamic_styles

# 최신 스케일 반영된 스타일 가져오기
latest_styles = get_dynamic_styles()
button.setStyleSheet(latest_styles['primary_button'])
```

### Q2: 스케일링이 작동하지 않아요

**증상**:
```python
font_size = get_scaled_font_size(21)
print(font_size)  # 항상 21 (스케일 안 됨)
```

**원인**:
1. ScalingManager 초기화 안 됨
2. 사용자가 자동 스케일링 비활성화
3. 스케일 팩터 범위 제한 (0.5~2.0)

**해결**:

1. **ScalingManager 상태 확인**:
```python
from ui.scaling_manager import get_scaling_manager

manager = get_scaling_manager()
print(f"현재 스케일: {manager.get_scale_factor()}")
print(f"자동 스케일링: {manager.is_auto_scaling_enabled()}")
print(f"사용자 스케일: {manager.get_user_scale_factor()}")
```

2. **강제 재계산**:
```python
manager.refresh_scaling()
```

3. **수동 스케일 설정**:
```python
# 1.5배로 강제
manager.set_auto_scaling_enabled(False)
manager.set_user_scale_factor(1.5)
```

### Q3: CollapsibleBox가 비어 보여요

**증상**:
```python
box = EnhancedCollapsibleBox(title="모듈")
box.setContentLayout(my_layout)
# 펼쳐도 내용이 안 보임
```

**원인**:
1. 레이아웃에 위젯이 없음
2. 위젯의 크기 정책 문제
3. 레이아웃이 None

**해결**:

1. **레이아웃 확인**:
```python
# 레이아웃에 위젯이 있는지 확인
print(f"레이아웃 항목 수: {my_layout.count()}")

# 위젯들이 표시되는지 확인
for i in range(my_layout.count()):
    widget = my_layout.itemAt(i).widget()
    if widget:
        print(f"위젯 {i}: {widget}, visible={widget.isVisible()}")
```

2. **크기 정책 확인**:
```python
# 콘텐츠 위젯 크기 정책 설정
content_widget = QWidget()
content_widget.setSizePolicy(
    QSizePolicy.Policy.Expanding,
    QSizePolicy.Policy.Preferred
)
content_widget.setLayout(my_layout)
```

3. **최소 크기 설정**:
```python
# 콘텐츠에 최소 높이 지정
content_widget.setMinimumHeight(100)
```

### Q4: DetachedWindow가 메인 창 뒤에 숨어요

**증상**:
- 분리 창을 열었는데 메인 창 뒤에 숨음
- 활성화가 안 됨

**원인**:
1. `raise_()`, `activateWindow()` 호출 안 함
2. 윈도우 플래그 문제
3. OS 창 관리자 제한

**해결**:

1. **명시적 활성화**:
```python
detached_window.show()
detached_window.raise_()
detached_window.activateWindow()

# 추가: 포커스 설정
detached_window.setFocus(Qt.FocusReason.OtherFocusReason)
```

2. **윈도우 플래그 확인**:
```python
# 항상 위에 표시 (임시)
detached_window.setWindowFlags(
    detached_window.windowFlags() | Qt.WindowType.WindowStaysOnTopHint
)
detached_window.show()
```

3. **지연 활성화**:
```python
from PyQt6.QtCore import QTimer

# 약간 지연 후 활성화
QTimer.singleShot(100, lambda: detached_window.raise_())
QTimer.singleShot(150, lambda: detached_window.activateWindow())
```

### Q5: ModernMenu 태그 정보가 안 나와요

**증상**:
```python
setModernStyle(text_edit)
# 우클릭해도 태그 정보 없음
```

**원인**:
1. `data/KR_tags.parquet` 파일 없음
2. 커서 위치에 태그 없음
3. DataFrame 로드 실패

**해결**:

1. **파일 확인**:
```python
import os

filepath = 'data/KR_tags.parquet'
if os.path.exists(filepath):
    print(f"✅ {filepath} 존재")

    import pandas as pd
    df = pd.read_parquet(filepath)
    print(f"태그 수: {len(df)}")
else:
    print(f"❌ {filepath} 없음")
```

2. **태그 형식 확인**:
```python
# 콤마로 구분된 태그여야 함
text_edit.setPlainText("1girl, smile, blue_eyes")

# 우클릭 시 각 태그 위치에서 정보 표시
```

3. **수동 로드 확인**:
```python
from ui.modern_menu import _load_kr_tags

kr_tags_df = _load_kr_tags()
print(f"로드된 태그: {len(kr_tags_df)}")

# 특정 태그 검색
result = kr_tags_df[kr_tags_df['tag'] == '1girl']
print(result)
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
  - 🆕 **웹 복사 서식 차단**: 색상코드, 폰트, 이탤릭체 등 차단
  - 🆕 **하이라이팅 호환**: PromptHighlighter 정상 작동
  - 🆕 **전역 적용**: 24개 QTextEdit 모두 적용됨
- ✅ **CollapsibleBox** 모듈 컨테이너
  - 🆕 **상태 추적**: `is_expanded()`, 스크롤 위치 저장/복원
  - 🆕 **프로그래밍 제어**: `expand()`, `collapse()`, `set_expanded()`
  - 🆕 **toggled 시그널**: 펼침/접힘 이벤트 알림
- ✅ **EnhancedTabWidget + RightView** 탭 시스템
- ✅ **DetachedWindow** 분리 창
- ✅ **ModernMenu** 컨텍스트 메뉴 + 태그 정보
- ✅ **UI 스레드 보호** 필수

**다음 단계**:
1. 기본 위젯 스타일링 실습 (예제 1)
2. 반응형 UI 작성 (예제 2)
3. CollapsibleBox 활용 (예제 3)
4. ModernMenu 통합 (예제 4)
5. 분리 가능 패널 구현 (예제 5)

**막힐 때**:
- 스타일 문제 → [Q1](#q1-스타일이-적용되지-않아요)
- 스케일링 문제 → [Q2](#q2-스케일링이-작동하지-않아요)
- CollapsibleBox 문제 → [Q3](#q3-collapsiblebox가-비어-보여요)
- DetachedWindow 문제 → [Q4](#q4-detachedwindow가-메인-창-뒤에-숨어요)
- ModernMenu 문제 → [Q5](#q5-modernmenu-태그-정보가-안-나와요)

---

*문서 버전: 1.5*
*최종 업데이트: 2025-01-17*
*담당 영역: ui/ 디렉터리*
*변경사항:*
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
