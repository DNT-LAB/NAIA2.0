# CLAUDE.md — interfaces/

> **목적**: NAIA 2.0 모듈/탭 계약(ABC) 정의. 호환성 파괴 변경을 피하고, 상호 의존성을 최소화하세요.

---

## 목차

1. [개요](#개요)
2. [주요 파일 및 역할](#주요-파일-및-역할)
3. [BaseMiddleModule 계약](#basemiddlemodule-계약)
4. [BaseTabModule 계약](#basetabmodule-계약)
5. [ModeAwareModule 믹스인](#modeawaremodule-믹스인)
6. [다중 상속 패턴](#다중-상속-패턴)
7. [계약 수정 가이드라인](#계약-수정-가이드라인)
8. [실전 예제](#실전-예제)
9. [문제 해결](#문제-해결)
10. [체크리스트](#체크리스트)
11. [참고 자료](#참고-자료)
12. [요약](#요약)

---

## 개요

### interfaces/ 디렉터리의 역할

interfaces/는 NAIA 2.0의 **계약(Contract) 정의 계층**입니다:

- 📜 **ABC (Abstract Base Class)**: 모듈과 탭이 구현해야 할 인터페이스 정의
- 🔒 **안정성**: 계약 변경 시 호출부 전체 영향 → 신중한 수정 필요
- 🧩 **느슨한 결합**: 구체 구현에 의존하지 않고 계약에만 의존
- 🌐 **모드 인식**: ModeAwareModule로 백엔드별 설정 분리

### 아키텍처

```
interfaces/
  ├── base_module.py          → BaseMiddleModule (좌측 모듈 계약)
  ├── base_tab_module.py      → BaseTabModule (우측 탭 계약)
  └── mode_aware_module.py    → ModeAwareModule (모드별 설정 믹스인)
```

**의존성 그래프**:
```
modules/*.py, tabs/*.py
    ↓ (implements)
interfaces/base_*.py
    ↓ (uses)
core/context.py, core/prompt_context.py
```

### 다른 디렉터리와의 관계

| 디렉터리 | 관계 | 설명 |
|----------|------|------|
| **modules/** | 구현 | BaseMiddleModule + (선택) ModeAwareModule |
| **tabs/** | 구현 | BaseTabModule + (선택) ModeAwareModule |
| **core/** | 사용 | AppContext, PromptContext 타입 힌트 |
| **ui/** | 독립 | interfaces는 ui/에 의존하지 않음 |

### 언제 interfaces/를 수정하는가?

⚠️ **계약 변경은 호환성 파괴 위험이 큽니다!**

| 작업 | 영향 범위 | 권장 방법 |
|------|----------|----------|
| **새 필수 메서드 추가** | 모든 구현체 수정 필요 | ❌ 피하기. 선택적 메서드로 추가 |
| **선택적 메서드 추가** | 영향 없음 | ✅ 안전. 기본 구현 제공 |
| **메서드 시그니처 변경** | 모든 구현체 수정 필요 | ❌ 피하기. 새 메서드 추가 |
| **속성 추가** | `__init__`에 기본값 제공 시 안전 | ✅ 조건부 안전 |
| **계약 문서화** | 영향 없음 | ✅ 적극 권장 |

---

## 주요 파일 및 역할

### interfaces/ 파일 목록

| 파일 | 크기 | 역할 | 주요 클래스 |
|------|------|------|------------|
| **base_module.py** | 2.4K | 좌측 Middle Section 모듈 계약 | `BaseMiddleModule` |
| **base_tab_module.py** | 2.7K | 우측 Right Panel 탭 계약 | `BaseTabModule`, `pyqtABCMeta` |
| **mode_aware_module.py** | 5.0K | 모드별 설정 저장/로드 믹스인 | `ModeAwareModule` |

### 구현 통계

**BaseMiddleModule 구현체** (modules/ 디렉터리):
- character_module.py
- character_reference_module.py
- vibe_transfer_module.py
- prompt_engineering_module.py
- automation_module.py
- instant_wildcard_module.py
- conditional_prompt_module.py
- e621_event_module.py
- wildcard_status_module.py
- 기타 약 20개

**BaseTabModule 구현체** (tabs/ 디렉터리):
- image_viewer.py (ImageViewerModule)
- png_info_tab.py (PNGInfoTabModule)
- assets_tab.py (AssetsTabModule)
- setting_tabs.py (SettingsTabModule)
- web_view.py (BrowserTabModule)
- img2img_tab.py (Img2ImgTabModule)
- 기타 약 10개

---

## BaseMiddleModule 계약

### 파일 위치 및 구조

**파일**: `interfaces/base_module.py:9-63`

```python
from abc import ABC, abstractmethod
from PyQt6.QtWidgets import QWidget
from typing import Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.context import AppContext
    from core.prompt_context import PromptContext

class BaseMiddleModule(ABC):
    """중간 패널 모듈의 기본 인터페이스"""
```

### 필수 메서드 (Abstract)

#### get_title() → str

**목적**: 모듈 제목 반환 (이모지 포함 가능)

**파일**: `base_module.py:22-25`

```python
@abstractmethod
def get_title(self) -> str:
    """모듈 제목 반환"""
    pass
```

**구현 예시**:
```python
def get_title(self) -> str:
    return "✨ Auto Quality"
```

**체크리스트**:
```
[ ] 반환 타입: str
[ ] 짧고 명확한 이름 (20자 이내 권장)
[ ] 이모지 사용 가능 (시각적 구분)
[ ] 고유한 제목 (다른 모듈과 중복 방지)
```

#### create_widget(parent) → QWidget

**목적**: 모듈의 UI 위젯 생성

**파일**: `base_module.py:27-30`

```python
@abstractmethod
def create_widget(self, parent) -> QWidget:
    """UI 위젯 생성"""
    pass
```

**구현 예시**:
```python
def create_widget(self, parent) -> QWidget:
    from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

    widget = QWidget(parent)
    layout = QVBoxLayout(widget)
    layout.addWidget(QLabel("모듈 콘텐츠"))

    # ⚠️ 중요: 위젯 참조 저장 (가시성 제어용)
    self.widget = widget
    return widget
```

**체크리스트**:
```
[ ] 반환 타입: QWidget
[ ] parent 파라미터 사용
[ ] self.widget = widget 저장 (모드 가시성 제어)
[ ] 레이아웃 설정
[ ] 테마/스케일링 적용 (DARK_STYLES, get_scaled_*)
```

### 선택적 메서드 (Optional)

#### get_order() → int

**목적**: UI 표시 순서 결정 (낮을수록 위에)

**파일**: `base_module.py:35-37`

**기본값**: 100

```python
def get_order(self) -> int:
    """UI 순서 (낮을수록 위에 표시)"""
    return 100
```

**구현 예시**:
```python
def get_order(self) -> int:
    return 10  # 위쪽에 표시
```

#### on_initialize()

**목적**: 모듈 초기화 시 호출 (AppContext 주입 후)

**파일**: `base_module.py:39-41`

```python
def on_initialize(self):
    """모듈 초기화 시 호출"""
    pass
```

**구현 예시**:
```python
def on_initialize(self):
    print(f"✅ {self.get_title()} 초기화 완료")

    # 이벤트 구독
    if self.app_context:
        self.app_context.subscribe("api_mode_changed", self._on_mode_changed)
```

#### get_parameters() → dict

**목적**: 생성 API 호출 시 추가할 파라미터 반환

**파일**: `base_module.py:43-45`

```python
def get_parameters(self) -> dict:
    """생성 파라미터 반환"""
    return {}
```

**구현 예시**:
```python
def get_parameters(self) -> dict:
    """Character Reference 이미지 파라미터"""
    return {
        "reference_image": self.current_image_base64,
        "reference_strength": self.strength_slider.value() / 100.0
    }
```

**사용 위치**: `core/generation_controller.py` → API 호출 시 병합

#### execute_pipeline_hook(context) → PromptContext

**목적**: 프롬프트 생성 파이프라인 훅 실행

**파일**: `base_module.py:47-49`

```python
def execute_pipeline_hook(self, context) -> PromptContext:
    """파이프라인 훅 실행"""
    return context
```

**구현 예시**:
```python
def execute_pipeline_hook(self, context):
    """자동 품질 태그 추가"""
    if self.enabled:
        context.prefix_tags = ["masterpiece", "best quality"] + context.prefix_tags
    return context
```

**체크리스트**:
```
[ ] 반드시 context 반환
[ ] 부작용 최소화 (context만 수정)
[ ] 오류 발생 시 원본 context 반환
[ ] 실행 조건 체크 (enabled 플래그 등)
```

#### get_pipeline_hook_info() → dict

**목적**: 파이프라인 훅 등록 정보 반환

**파일**: `base_module.py:51-53`

```python
def get_pipeline_hook_info(self) -> dict:
    """파이프라인 훅 정보 반환"""
    return {}
```

**구현 예시**:
```python
def get_pipeline_hook_info(self) -> dict:
    return {
        'target_pipeline': 'PromptProcessor',
        'hook_point': 'post_processing',  # pre_processing, after_wildcard, final_hookpoint
        'priority': 10  # 낮을수록 먼저 실행
    }
```

**hook_point 옵션**:
- `pre_processing`: 가장 먼저 (원본 프롬프트 수정)
- `post_processing`: 와일드카드 확장 전
- `after_wildcard`: 와일드카드 확장 후
- `final_hookpoint`: 최종 포맷 전

#### is_compatible_with_mode(mode: str) → bool

**목적**: 특정 모드와 호환되는지 확인

**파일**: `base_module.py:55-63`

**기본 구현 제공**:
```python
def is_compatible_with_mode(self, mode: str) -> bool:
    """해당 모드와 호환되는지 확인 (기본 구현)"""
    if mode == "NAI":
        return getattr(self, 'NAI_compatibility', True)
    elif mode == "WEBUI":
        return getattr(self, 'WEBUI_compatibility', True)
    elif mode == "COMFYUI":
        return getattr(self, 'COMFYUI_compatibility', True)
    return True  # 알 수 없는 모드일 경우 기본적으로 표시
```

**오버라이드 예시**:
```python
def is_compatible_with_mode(self, mode: str) -> bool:
    # NAI 전용 모듈
    return mode == "NAI"
```

### 속성 (Attributes)

**파일**: `base_module.py:12-20`

```python
def __init__(self):
    # 모드 호환성 플래그
    self.NAI_compatibility = True
    self.WEBUI_compatibility = True
    self.COMFYUI_compatibility = True

    # AppContext (자동 주입됨)
    self.app_context = None

    # 저장/로드 무시 (일시적 모듈)
    self.ignore_save_load = False
```

**호환성 플래그 사용법**:
```python
class NAIOnlyModule(BaseMiddleModule):
    def __init__(self):
        super().__init__()
        self.NAI_compatibility = True
        self.WEBUI_compatibility = False
        self.COMFYUI_compatibility = False
```

---

## BaseTabModule 계약

### 파일 위치 및 구조

**파일**: `interfaces/base_tab_module.py:9-78`

```python
from abc import ABC, abstractmethod, ABCMeta
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import pyqtSignal, QObject
from typing import Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.context import AppContext

class pyqtABCMeta(type(QObject), ABCMeta):
    """PyQt6 QObject와 ABC를 결합한 메타클래스"""
    pass

class BaseTabModule(QObject, ABC, metaclass=pyqtABCMeta):
    """오른쪽 패널의 탭으로 동적 로드될 모든 모듈의 기반 추상 클래스"""
```

### 공통 시그널 (Common Signals)

**파일**: `base_tab_module.py:15-18`

```python
# 탭 간 통신을 위한 공통 시그널들
parameters_extracted = pyqtSignal(dict)
instant_generation_requested = pyqtSignal(dict)
tab_status_changed = pyqtSignal(str, str)  # tab_id, status_message
```

**사용 예시**:
```python
class MyTabModule(BaseTabModule):
    def _on_button_clicked(self):
        # 파라미터 추출 이벤트 발행
        params = {"width": 512, "height": 768}
        self.parameters_extracted.emit(params)

        # 즉시 생성 요청
        self.instant_generation_requested.emit(params)

        # 상태 변경 알림
        self.tab_status_changed.emit(self.tab_id, "생성 중...")
```

### 필수 메서드 (Abstract)

#### get_tab_title() → str

**목적**: 탭 제목 반환

**파일**: `base_tab_module.py:29-32`

```python
@abstractmethod
def get_tab_title(self) -> str:
    """탭의 제목을 반환합니다 (이모지 포함 가능)."""
    pass
```

**구현 예시**:
```python
def get_tab_title(self) -> str:
    return "🖼️ Image Viewer"
```

#### create_widget(parent: QWidget) → QWidget

**목적**: 탭의 UI 위젯 생성

**파일**: `base_tab_module.py:34-37`

```python
@abstractmethod
def create_widget(self, parent: QWidget) -> QWidget:
    """탭의 UI 위젯을 생성하여 반환합니다."""
    pass
```

**구현 예시**:
```python
def create_widget(self, parent: QWidget) -> QWidget:
    from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

    widget = QWidget(parent)
    layout = QVBoxLayout(widget)
    layout.addWidget(QLabel("탭 콘텐츠"))

    return widget
```

### 선택적 메서드 (Optional)

#### get_tab_order() → int

**목적**: 탭 표시 순서 (낮을수록 왼쪽)

**파일**: `base_tab_module.py:39-41`

**기본값**: 999

```python
def get_tab_order(self) -> int:
    """탭이 표시될 순서를 반환합니다. 숫자가 낮을수록 왼쪽에 표시됩니다."""
    return 999
```

#### get_tab_type() → str

**목적**: 탭 유형 반환

**파일**: `base_tab_module.py:43-45`

**기본값**: 'core'

**옵션**:
- `'core'`: 시작 시 자동 로드, 닫을 수 없음
- `'closable'`: 사용자가 수동으로 열고 닫을 수 있음
- `'permanent'`: 항상 표시, 닫을 수 없음

```python
def get_tab_type(self) -> str:
    """탭의 유형을 반환합니다 ('core', 'closable', 'permanent')"""
    return 'core'  # 기본값
```

#### can_close_tab() → bool

**목적**: 탭을 닫을 수 있는지 확인

**파일**: `base_tab_module.py:47-49`

```python
def can_close_tab(self) -> bool:
    """탭이 닫힐 수 있는지 여부를 반환합니다."""
    return self.get_tab_type() in ['closable']
```

### 라이프사이클 훅 (Lifecycle Hooks)

#### on_tab_activated()

**목적**: 탭이 활성화될 때 호출

**파일**: `base_tab_module.py:51-53`

```python
def on_tab_activated(self):
    """탭이 활성화될 때 호출되는 메서드 (선택사항)"""
    pass
```

**구현 예시**:
```python
def on_tab_activated(self):
    print(f"✅ {self.get_tab_title()} 탭 활성화")
    # 갤러리 새로고침, 이미지 로드 등
```

#### on_tab_deactivated()

**목적**: 탭이 비활성화될 때 호출

**파일**: `base_tab_module.py:55-57`

```python
def on_tab_deactivated(self):
    """탭이 비활성화될 때 호출되는 메서드 (선택사항)"""
    pass
```

#### on_tab_closing() → bool

**목적**: 탭이 닫히기 전에 호출. False 반환 시 닫기 취소

**파일**: `base_tab_module.py:59-61`

```python
def on_tab_closing(self) -> bool:
    """탭이 닫히기 전에 호출되는 메서드. False 반환 시 닫기 취소됩니다."""
    return True
```

**구현 예시**:
```python
def on_tab_closing(self) -> bool:
    if self.has_unsaved_changes:
        reply = QMessageBox.question(
            self.widget, "확인", "저장하지 않은 변경사항이 있습니다. 닫으시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        return reply == QMessageBox.StandardButton.Yes
    return True
```

#### cleanup()

**목적**: 탭이 제거될 때 리소스 정리

**파일**: `base_tab_module.py:63-65`

```python
def cleanup(self):
    """탭이 제거될 때 정리 작업을 수행합니다."""
    pass
```

**구현 예시**:
```python
def cleanup(self):
    # QThread 종료
    if hasattr(self, 'worker_thread') and self.worker_thread.isRunning():
        self.worker_thread.quit()
        self.worker_thread.wait()

    # 임시 파일 삭제
    if hasattr(self, 'temp_files'):
        for temp_file in self.temp_files:
            temp_file.unlink(missing_ok=True)
```

### 설정 저장/로드 (Optional)

#### save_settings()

**파일**: `base_tab_module.py:68-70`

```python
def save_settings(self):
    """탭의 설정을 저장합니다 (구현 선택사항)"""
    pass
```

#### load_settings()

**파일**: `base_tab_module.py:72-74`

```python
def load_settings(self):
    """탭의 설정을 로드합니다 (구현 선택사항)"""
    pass
```

### 초기화 훅

#### on_initialize()

**파일**: `base_tab_module.py:76-78`

```python
def on_initialize(self):
    """탭 초기화 완료 시 호출됩니다."""
    print(f"✅ {self.get_tab_title()} 탭 초기화 완료")
```

### 속성 (Attributes)

**파일**: `base_tab_module.py:20-27`

```python
def __init__(self):
    super().__init__()
    self.app_context = None
    self.tab_id = self.__class__.__name__  # 고유 식별자

def initialize_with_context(self, app_context: 'AppContext'):
    """모듈에 AppContext를 주입합니다."""
    self.app_context = app_context
```

---

## ModeAwareModule 믹스인

### 파일 위치 및 구조

**파일**: `interfaces/mode_aware_module.py:6-134`

```python
from abc import ABC, abstractmethod
import json
import os
from typing import Dict, Any

class ModeAwareModule(ABC):
    """모드별 설정 저장/로드 및 가시성 제어를 지원하는 모듈의 기본 인터페이스"""
```

### 자동 제공 기능

**ModeAwareModule을 상속하면 자동으로**:
1. ✅ 모드 전환 시 이전 모드 설정 자동 저장
2. ✅ 새 모드 설정 자동 로드
3. ✅ 호환되지 않는 모드에서 자동 숨김
4. ✅ 설정 파일 경로 자동 생성 (`save/<base>_<MODE>.json`)

### 필수 속성 설정

**파일**: `mode_aware_module.py:9-22`

```python
def __init__(self):
    # 🆕 필수 속성들을 기본값으로 초기화
    self.settings_base_filename = None  # ⚠️ 서브클래스에서 설정 필요
    self.current_mode = "NAI"  # 기본값

    # 필수: 각 모드 호환성 플래그
    if not hasattr(self, 'NAI_compatibility'):
        self.NAI_compatibility = True   # 기본값: NAI 호환
    if not hasattr(self, 'WEBUI_compatibility'):
        self.WEBUI_compatibility = True # 기본값: WEBUI 호환

    # UI 가시성 관련
    self.widget = None
    self.is_visible = True
```

**구현 시 필수**:
```python
class MyModule(BaseMiddleModule, ModeAwareModule):
    def __init__(self):
        BaseMiddleModule.__init__(self)
        ModeAwareModule.__init__(self)

        # ⚠️ 필수: 설정 파일 베이스 이름
        self.settings_base_filename = "my_module_settings"
```

### 필수 메서드 (Abstract)

#### collect_current_settings() → Dict[str, Any]

**목적**: 현재 UI 상태를 딕셔너리로 수집

**파일**: `mode_aware_module.py:121-124`

```python
@abstractmethod
def collect_current_settings(self) -> Dict[str, Any]:
    """현재 UI 상태에서 설정을 수집하여 반환"""
    pass
```

**구현 예시**:
```python
def collect_current_settings(self) -> Dict[str, Any]:
    return {
        "checkbox_enabled": self.checkbox.isChecked(),
        "slider_value": self.slider.value(),
        "text_input": self.input_field.text(),
        "combobox_index": self.combo.currentIndex()
    }
```

#### apply_settings(settings: Dict[str, Any])

**목적**: 저장된 설정을 UI에 적용

**파일**: `mode_aware_module.py:126-129`

```python
@abstractmethod
def apply_settings(self, settings: Dict[str, Any]):
    """설정을 UI에 적용"""
    pass
```

**구현 예시**:
```python
def apply_settings(self, settings: Dict[str, Any]):
    if "checkbox_enabled" in settings:
        self.checkbox.setChecked(settings["checkbox_enabled"])
    if "slider_value" in settings:
        self.slider.setValue(settings["slider_value"])
    if "text_input" in settings:
        self.input_field.setText(settings["text_input"])
    if "combobox_index" in settings:
        self.combo.setCurrentIndex(settings["combobox_index"])
```

#### get_module_name() → str

**목적**: 모듈 이름 반환 (로깅용)

**파일**: `mode_aware_module.py:131-134`

```python
@abstractmethod
def get_module_name(self) -> str:
    """모듈 이름 반환 (로깅용)"""
    pass
```

**구현 예시**:
```python
def get_module_name(self) -> str:
    return self.get_title()  # BaseMiddleModule의 get_title() 재사용
```

### 자동 제공 메서드

#### save_mode_settings(mode: str = None)

**파일**: `mode_aware_module.py:32-52`

```python
def save_mode_settings(self, mode: str = None):
    """현재 모드의 설정을 저장"""
    target_mode = mode or self.current_mode
    filename = self.get_mode_aware_filename(target_mode)

    # 현재 설정 수집
    current_settings = self.collect_current_settings()

    # 파일 저장
    mode_data = {target_mode: current_settings}
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(mode_data, f, indent=4, ensure_ascii=False)
```

**수동 호출 예시**:
```python
# 현재 모드 설정 저장
self.save_mode_settings()

# 특정 모드 설정 저장
self.save_mode_settings("NAI")
```

#### load_mode_settings(mode: str = None)

**파일**: `mode_aware_module.py:54-76`

```python
def load_mode_settings(self, mode: str = None):
    """지정된 모드의 설정을 로드"""
    target_mode = mode or self.current_mode
    filename = self.get_mode_aware_filename(target_mode)

    if not os.path.exists(filename):
        return

    with open(filename, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 해당 모드의 설정 가져오기
    mode_settings = data.get(target_mode, {})
    if mode_settings:
        self.apply_settings(mode_settings)
```

#### is_compatible_with_mode(mode: str) → bool

**파일**: `mode_aware_module.py:78-84`

```python
def is_compatible_with_mode(self, mode: str) -> bool:
    """해당 모드와 호환되는지 확인"""
    if mode == "NAI":
        return getattr(self, 'NAI_compatibility', True)
    elif mode == "WEBUI":
        return getattr(self, 'WEBUI_compatibility', True)
    return False
```

#### update_visibility_for_mode(mode: str)

**파일**: `mode_aware_module.py:86-101`

```python
def update_visibility_for_mode(self, mode: str):
    """강화된 가시성 업데이트"""
    should_be_visible = self.is_compatible_with_mode(mode)

    if self.widget and hasattr(self.widget, 'setVisible'):
        self.widget.setVisible(should_be_visible)
        self.is_visible = should_be_visible

        # 부모 위젯도 업데이트 (레이아웃 새로고침)
        if self.widget.parent():
            self.widget.parent().update()
```

#### on_mode_changed(old_mode: str, new_mode: str)

**파일**: `mode_aware_module.py:103-119`

**자동 호출**: `AppContext`의 `api_mode_changed` 이벤트 구독 시

```python
def on_mode_changed(self, old_mode: str, new_mode: str):
    """강화된 모드 변경 처리"""
    print(f"🔄 '{self.get_module_name()}' 모드 변경: {old_mode} → {new_mode}")

    # 1. 이전 모드 설정 저장
    if self.is_compatible_with_mode(old_mode):
        self.save_mode_settings(old_mode)

    # 2. 새 모드로 전환
    self.current_mode = new_mode

    # 3. 새 모드 설정 로드
    if self.is_compatible_with_mode(new_mode):
        self.load_mode_settings(new_mode)

    # 4. 가시성 업데이트
    self.update_visibility_for_mode(new_mode)
```

### 설정 파일 구조

**경로**: `save/<settings_base_filename>_<MODE>.json`

**예시**: `save/my_module_settings_NAI.json`

```json
{
  "NAI": {
    "checkbox_enabled": true,
    "slider_value": 75,
    "text_input": "NAI 전용 설정",
    "combobox_index": 2
  }
}
```

---

## 다중 상속 패턴

### 기본 패턴: BaseMiddleModule + ModeAwareModule

**파일**: `modules/character_module.py:1-50` (예시)

```python
from interfaces.base_module import BaseMiddleModule
from interfaces.mode_aware_module import ModeAwareModule

class MyModule(BaseMiddleModule, ModeAwareModule):
    """모드 인식 모듈 예제"""

    def __init__(self):
        # ⚠️ 순서 중요: 양쪽 __init__ 모두 호출
        BaseMiddleModule.__init__(self)
        ModeAwareModule.__init__(self)

        # 설정 파일 베이스 이름
        self.settings_base_filename = "my_module"

        # 호환성 플래그
        self.NAI_compatibility = True
        self.WEBUI_compatibility = True
        self.COMFYUI_compatibility = False

        # UI 위젯 참조
        self.widget = None

    # BaseMiddleModule 필수 메서드
    def get_title(self) -> str:
        return "🎯 My Module"

    def create_widget(self, parent):
        # ... UI 생성 ...
        self.widget = widget
        return widget

    # ModeAwareModule 필수 메서드
    def collect_current_settings(self) -> dict:
        return {"key": "value"}

    def apply_settings(self, settings: dict):
        pass

    def get_module_name(self) -> str:
        return self.get_title()
```

### 탭 + ModeAware 패턴

```python
from interfaces.base_tab_module import BaseTabModule
from interfaces.mode_aware_module import ModeAwareModule

class MyTab(BaseTabModule, ModeAwareModule):
    """모드 인식 탭 예제"""

    def __init__(self):
        BaseTabModule.__init__(self)
        ModeAwareModule.__init__(self)

        self.settings_base_filename = "my_tab"
        self.NAI_compatibility = True
        self.WEBUI_compatibility = True

    # BaseTabModule 필수 메서드
    def get_tab_title(self) -> str:
        return "📊 My Tab"

    def create_widget(self, parent):
        # ... UI 생성 ...
        return widget

    # ModeAwareModule 필수 메서드
    def collect_current_settings(self) -> dict:
        return {}

    def apply_settings(self, settings: dict):
        pass

    def get_module_name(self) -> str:
        return self.get_tab_title()
```

### MRO (Method Resolution Order) 주의사항

**Python의 MRO**:
```python
class MyModule(BaseMiddleModule, ModeAwareModule):
    pass

# MRO 확인
print(MyModule.__mro__)
# (<class 'MyModule'>, <class 'BaseMiddleModule'>, <class 'ModeAwareModule'>, <class 'ABC'>, <class 'object'>)
```

**충돌 방지**:
- `BaseMiddleModule`과 `ModeAwareModule` 모두 `is_compatible_with_mode()`를 정의
- MRO 순서상 `BaseMiddleModule.is_compatible_with_mode()`가 우선
- ModeAwareModule의 메서드를 사용하려면 명시적 호출:

```python
def on_mode_changed(self, old_mode, new_mode):
    # ModeAwareModule의 on_mode_changed 명시적 호출
    ModeAwareModule.on_mode_changed(self, old_mode, new_mode)
```

---

## 계약 수정 가이드라인

### 안전한 수정 (Breaking Change 아님)

✅ **선택적 메서드 추가** (기본 구현 제공)

```python
# interfaces/base_module.py
class BaseMiddleModule(ABC):
    # ... 기존 메서드들 ...

    # ✅ 새 선택적 메서드 (기본 구현 제공)
    def on_settings_changed(self):
        """설정 변경 시 호출 (선택사항)"""
        pass
```

✅ **속성 추가** (`__init__`에 기본값)

```python
def __init__(self):
    # 기존 속성들
    self.NAI_compatibility = True
    self.WEBUI_compatibility = True
    self.COMFYUI_compatibility = True

    # ✅ 새 속성 (기본값 제공)
    self.support_batch_generation = False
```

✅ **문서화 개선**

```python
@abstractmethod
def get_title(self) -> str:
    """
    모듈 제목 반환

    Returns:
        str: 모듈 제목 (이모지 포함 가능, 20자 이내 권장)

    Example:
        return "✨ Auto Quality"
    """
    pass
```

### 위험한 수정 (Breaking Change)

❌ **필수 메서드 추가** (모든 구현체 수정 필요)

```python
# ❌ 절대 하지 말 것
@abstractmethod
def new_required_method(self) -> str:
    """새 필수 메서드"""
    pass
```

**대안**: 선택적 메서드로 추가 후 점진적 마이그레이션

❌ **메서드 시그니처 변경**

```python
# ❌ 기존
def execute_pipeline_hook(self, context) -> PromptContext:
    pass

# ❌ 변경 (모든 구현체 깨짐)
def execute_pipeline_hook(self, context, options: dict) -> PromptContext:
    pass
```

**대안**: 새 메서드 추가 (`execute_pipeline_hook_v2`)

❌ **필수 속성 추가** (기본값 없음)

```python
# ❌ __init__에서 필수로 설정 요구
def __init__(self):
    # 서브클래스가 반드시 설정해야 함
    self.required_attribute = None  # ValueError 발생 가능
```

### 변경 시 체크리스트

```
[ ] 변경이 기존 구현체에 영향을 주는가?
[ ] 필수 메서드 추가인가? (❌ 피하기)
[ ] 메서드 시그니처 변경인가? (❌ 피하기)
[ ] 기본 구현을 제공하는가? (✅ 권장)
[ ] 문서화가 명확한가?
[ ] 예제 코드가 업데이트되었는가?
[ ] 마이그레이션 가이드가 제공되는가?
[ ] PR 설명에 영향 범위가 명시되었는가?
```

### 버전 관리 전략

**Semantic Versioning 적용**:

- **Major (1.0.0 → 2.0.0)**: Breaking Change (필수 메서드/시그니처 변경)
- **Minor (1.0.0 → 1.1.0)**: 선택적 메서드 추가
- **Patch (1.0.0 → 1.0.1)**: 버그 수정, 문서화

**Deprecation 패턴**:
```python
import warnings

def old_method(self):
    """Deprecated: Use new_method() instead."""
    warnings.warn(
        "old_method() is deprecated. Use new_method() instead.",
        DeprecationWarning,
        stacklevel=2
    )
    return self.new_method()

def new_method(self):
    """새 메서드"""
    pass
```

---

## 실전 예제

### 예제 1: 최소 모듈 (5분)

**목표**: BaseMiddleModule만 구현

```python
# modules/simple_module.py
from interfaces.base_module import BaseMiddleModule
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

class SimpleModule(BaseMiddleModule):
    def __init__(self):
        super().__init__()

    def get_title(self) -> str:
        return "📌 Simple"

    def create_widget(self, parent) -> QWidget:
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel("최소 구현 예제"))

        self.widget = widget
        return widget
```

### 예제 2: 모드 인식 모듈 (30분)

**목표**: BaseMiddleModule + ModeAwareModule

```python
# modules/mode_aware_example.py
from interfaces.base_module import BaseMiddleModule
from interfaces.mode_aware_module import ModeAwareModule
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QCheckBox, QLineEdit
from ui.theme import get_dynamic_styles

class ModeAwareExampleModule(BaseMiddleModule, ModeAwareModule):
    def __init__(self):
        BaseMiddleModule.__init__(self)
        ModeAwareModule.__init__(self)

        # 설정 파일 이름
        self.settings_base_filename = "mode_aware_example"

        # 호환성 플래그
        self.NAI_compatibility = True
        self.WEBUI_compatibility = True
        self.COMFYUI_compatibility = False

        # UI 참조
        self.checkbox = None
        self.input_field = None

    def get_title(self) -> str:
        return "🔄 ModeAware Example"

    def create_widget(self, parent) -> QWidget:
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)

        styles = get_dynamic_styles()

        self.checkbox = QCheckBox("옵션 활성화")
        self.checkbox.setStyleSheet(styles['dark_checkbox'])
        layout.addWidget(self.checkbox)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("설정 값")
        self.input_field.setStyleSheet(styles['compact_lineedit'])
        layout.addWidget(self.input_field)

        self.widget = widget
        return widget

    # ModeAwareModule 필수 메서드
    def collect_current_settings(self) -> dict:
        return {
            "checkbox_state": self.checkbox.isChecked(),
            "input_value": self.input_field.text()
        }

    def apply_settings(self, settings: dict):
        if "checkbox_state" in settings:
            self.checkbox.setChecked(settings["checkbox_state"])
        if "input_value" in settings:
            self.input_field.setText(settings["input_value"])

    def get_module_name(self) -> str:
        return self.get_title()
```

### 예제 3: 파이프라인 훅 모듈 (1시간)

**목표**: 프롬프트 생성 파이프라인에 개입

```python
# modules/pipeline_hook_example.py
from interfaces.base_module import BaseMiddleModule
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QCheckBox
from ui.theme import get_dynamic_styles
from core.prompt_context import PromptContext

class PipelineHookExampleModule(BaseMiddleModule):
    def __init__(self):
        super().__init__()
        self.enabled = True

    def get_title(self) -> str:
        return "🔧 Pipeline Hook"

    def create_widget(self, parent) -> QWidget:
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)

        styles = get_dynamic_styles()

        self.checkbox = QCheckBox("자동 품질 태그 추가")
        self.checkbox.setStyleSheet(styles['dark_checkbox'])
        self.checkbox.setChecked(True)
        self.checkbox.stateChanged.connect(self._on_checkbox_changed)
        layout.addWidget(self.checkbox)

        self.widget = widget
        return widget

    def _on_checkbox_changed(self, state):
        self.enabled = (state == 2)

    def get_pipeline_hook_info(self) -> dict:
        return {
            'target_pipeline': 'PromptProcessor',
            'hook_point': 'post_processing',
            'priority': 5
        }

    def execute_pipeline_hook(self, context: PromptContext) -> PromptContext:
        if not self.enabled:
            return context

        # 품질 태그 추가
        quality_tags = ["masterpiece", "best quality", "highly detailed"]
        context.prefix_tags = quality_tags + context.prefix_tags

        print(f"✅ {self.get_title()}: {len(quality_tags)}개 태그 추가됨")
        return context
```

### 예제 4: 탭 모듈 (1시간)

**목표**: BaseTabModule 구현

```python
# tabs/example_tab.py
from interfaces.base_tab_module import BaseTabModule
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from ui.theme import get_dynamic_styles

class ExampleTabModule(BaseTabModule):
    def __init__(self):
        super().__init__()

    def get_tab_title(self) -> str:
        return "📋 Example Tab"

    def get_tab_order(self) -> int:
        return 100

    def get_tab_type(self) -> str:
        return 'closable'  # 닫을 수 있는 탭

    def create_widget(self, parent: QWidget) -> QWidget:
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)

        layout.addWidget(QLabel("예제 탭 콘텐츠"))

        styles = get_dynamic_styles()

        btn = QPushButton("파라미터 추출")
        btn.setStyleSheet(styles['primary_button'])
        btn.clicked.connect(self._on_extract_params)
        layout.addWidget(btn)

        return widget

    def _on_extract_params(self):
        params = {"example_key": "example_value"}
        self.parameters_extracted.emit(params)

    def on_tab_activated(self):
        print(f"✅ {self.get_tab_title()} 활성화됨")

    def on_tab_deactivated(self):
        print(f"⏸️ {self.get_tab_title()} 비활성화됨")

    def cleanup(self):
        print(f"🧹 {self.get_tab_title()} 정리 완료")
```

---

## 문제 해결

### Q1: ModeAwareModule 상속 시 AttributeError

**증상**:
```
AttributeError: 'MyModule' object has no attribute 'settings_base_filename'
```

**원인**: `settings_base_filename` 미설정

**해결**:
```python
def __init__(self):
    BaseMiddleModule.__init__(self)
    ModeAwareModule.__init__(self)

    # ✅ 필수: 설정 파일 베이스 이름
    self.settings_base_filename = "my_module"
```

### Q2: 다중 상속 시 메서드 호출 순서 문제

**증상**: `is_compatible_with_mode()`가 예상과 다르게 동작

**원인**: MRO (Method Resolution Order) 순서

**해결**:
```python
# MRO 확인
print(MyModule.__mro__)

# 특정 부모 클래스 메서드 명시적 호출
def is_compatible_with_mode(self, mode: str) -> bool:
    # ModeAwareModule의 메서드 사용
    return ModeAwareModule.is_compatible_with_mode(self, mode)
```

### Q3: 계약 변경 시 기존 모듈이 깨짐

**증상**: 새 필수 메서드 추가 후 기존 모듈에서 에러

**원인**: Breaking Change

**해결**:
```python
# ❌ 잘못된 방법
@abstractmethod
def new_method(self):
    pass

# ✅ 올바른 방법 (기본 구현 제공)
def new_method(self):
    """새 메서드 (선택사항)"""
    pass
```

### Q4: pyqtABCMeta 관련 에러

**증상**:
```
TypeError: metaclass conflict: the metaclass of a derived class must be a (non-strict) subclass of the metaclasses of all its bases
```

**원인**: QObject와 ABC의 메타클래스 충돌

**해결**:
```python
# ✅ BaseTabModule 사용 (이미 pyqtABCMeta 적용됨)
from interfaces.base_tab_module import BaseTabModule

class MyTab(BaseTabModule):
    pass

# ❌ 직접 QObject + ABC 상속 금지
from PyQt6.QtCore import QObject
from abc import ABC

class MyTab(QObject, ABC):  # ❌ 에러 발생
    pass
```

### Q5: 설정 파일이 저장/로드되지 않음

**증상**: 모드 전환 시 설정이 초기화됨

**원인**: `collect_current_settings()` 또는 `apply_settings()` 미구현

**해결**:
```python
def collect_current_settings(self) -> dict:
    # ✅ 모든 UI 상태 수집
    return {
        "checkbox": self.checkbox.isChecked(),
        "slider": self.slider.value(),
        # ... 모든 설정 ...
    }

def apply_settings(self, settings: dict):
    # ✅ 안전하게 적용 (키 존재 확인)
    if "checkbox" in settings:
        self.checkbox.setChecked(settings["checkbox"])
    if "slider" in settings:
        self.slider.setValue(settings["slider"])
```

---

## 체크리스트

### 새 계약 설계 시

```
[ ] 최소 필수 메서드로 설계 (확장성 고려)
[ ] 모든 필수 메서드에 타입 힌트
[ ] 선택적 메서드는 기본 구현 제공
[ ] 문서화 (docstring + 예제)
[ ] Breaking Change 최소화
[ ] 기존 구현체와의 호환성 확인
```

### BaseMiddleModule 구현 시

```
[ ] get_title() 구현
[ ] create_widget() 구현
[ ] self.widget = widget 저장
[ ] 호환성 플래그 설정 (NAI/WEBUI/COMFYUI)
[ ] get_order() 오버라이드 (순서 조정 필요 시)
[ ] 파이프라인 훅 사용 시:
    [ ] get_pipeline_hook_info() 구현
    [ ] execute_pipeline_hook() 구현
    [ ] context 반드시 반환
```

### BaseTabModule 구현 시

```
[ ] get_tab_title() 구현
[ ] create_widget() 구현
[ ] get_tab_type() 오버라이드 (core/closable)
[ ] get_tab_order() 오버라이드 (순서 조정 필요 시)
[ ] 라이프사이클 훅 구현 (필요 시):
    [ ] on_tab_activated()
    [ ] on_tab_deactivated()
    [ ] on_tab_closing()
    [ ] cleanup()
```

### ModeAwareModule 구현 시

```
[ ] BaseMiddleModule 또는 BaseTabModule 먼저 상속
[ ] ModeAwareModule 다중 상속
[ ] 양쪽 __init__() 호출
[ ] settings_base_filename 설정
[ ] collect_current_settings() 구현
[ ] apply_settings() 구현
[ ] get_module_name() 구현
[ ] 호환성 플래그 설정
```

### 계약 수정 시

```
[ ] Breaking Change인가?
[ ] 기본 구현 제공하는가?
[ ] 문서화 업데이트
[ ] 예제 코드 업데이트
[ ] 마이그레이션 가이드 작성
[ ] PR 설명에 영향 범위 명시
[ ] 모든 기존 구현체 테스트
```

---

## 참고 자료

### 관련 문서

- **[최상위 CLAUDE.md](../CLAUDE.md)**: 전체 프로젝트 개요
- **[modules/CLAUDE.md](../modules/CLAUDE.md)**: BaseMiddleModule 구현 가이드
- **[tabs/CLAUDE.md](../tabs/CLAUDE.md)**: BaseTabModule 구현 가이드
- **[core/CLAUDE.md](../core/CLAUDE.md)**: AppContext, 컨트롤러

### 예제 코드 위치

| 예제 | 파일 | 라인 | 특징 |
|------|------|------|------|
| **BaseMiddleModule 구현** | `modules/character_module.py` | 1-50 | ModeAware 다중 상속 |
| **BaseTabModule 구현** | `tabs/png_info_tab.py` | 1-80 | 라이프사이클 훅 |
| **ModeAwareModule 사용** | `modules/character_module.py` | 20-100 | 설정 저장/로드 |
| **파이프라인 훅** | `modules/conditional_prompt_module.py` | 100-200 | execute_pipeline_hook |
| **pyqtABCMeta 정의** | `interfaces/base_tab_module.py` | 9-10 | 메타클래스 |

### Python ABC 참고 자료

- [Python ABC 공식 문서](https://docs.python.org/3/library/abc.html)
- [Abstract Base Classes in Python](https://realpython.com/python-interface/)
- [Method Resolution Order (MRO)](https://www.python.org/download/releases/2.3/mro/)

### PyQt6 참고 자료

- [PyQt6 공식 문서](https://www.riverbankcomputing.com/static/Docs/PyQt6/)
- [Qt Signals & Slots](https://doc.qt.io/qt-6/signalsandslots.html)
- [QObject 메타클래스](https://doc.qt.io/qt-6/qobject.html#meta-object-system)

---

## 요약

**interfaces/의 핵심**:
- ✅ **계약 정의 계층**: 모듈/탭이 구현할 인터페이스
- ✅ **BaseMiddleModule**: 좌측 모듈 계약 (get_title, create_widget 필수)
- ✅ **BaseTabModule**: 우측 탭 계약 (get_tab_title, create_widget 필수)
- ✅ **ModeAwareModule**: 모드별 설정 자동 저장/로드 믹스인
- ✅ **다중 상속 패턴**: Base + ModeAware 조합
- ✅ **안정성 우선**: Breaking Change 최소화, 선택적 메서드로 확장

**계약 수정 원칙**:
1. 필수 메서드 추가 금지 → 선택적 메서드로 추가
2. 메서드 시그니처 변경 금지 → 새 메서드 추가
3. 기본 구현 제공 → 기존 코드 호환성 유지
4. 문서화 철저 → 예제 코드 + 마이그레이션 가이드

**다음 단계**:
1. [modules/CLAUDE.md](../modules/CLAUDE.md)에서 모듈 개발 학습
2. [tabs/CLAUDE.md](../tabs/CLAUDE.md)에서 탭 개발 학습
3. 실제 모듈/탭 작성 연습

---

*문서 버전: 1.0*
*작성일: 2025-01-08*
*담당 영역: interfaces/ 디렉터리*
