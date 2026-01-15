# CLAUDE.md — modules/

> **목적**: 좌측 Middle Section에 로드되는 모듈 개발 가이드. BaseMiddleModule을 상속하고 필요 시 ModeAwareModule을 다중 상속하여 모드별 설정을 관리합니다.

---

## 목차

1. [개요](#개요)
2. [주요 파일 및 역할](#주요-파일-및-역할)
3. [모듈 개발 기초](#모듈-개발-기초)
4. [ModeAware 모듈 개발](#modeaware-모듈-개발)
5. [파이프라인 훅 고급 기법](#파이프라인-훅-고급-기법)
6. [실전 예제](#실전-예제)
7. [단계별 튜토리얼](#단계별-튜토리얼)
8. [고급 패턴](#고급-패턴)
9. [문제 해결](#문제-해결)
10. [체크리스트](#체크리스트)
11. [참고 자료](#참고-자료)

---

## 개요

### modules/ 디렉터리의 역할

modules/는 **좌측 Middle Section**에 표시되는 모듈들을 포함합니다.

**핵심 특징**:
- 🔄 **동적 로딩**: `MiddleSectionController`가 `*_module.py` 파일을 자동 검색 및 로드
- 🎨 **파이프라인 훅**: 프롬프트 생성 과정에 개입 가능
- 🌐 **모드 인식**: ModeAwareModule로 NAI/WEBUI/COMFYUI별 설정 관리
- 🧩 **느슨한 결합**: AppContext 이벤트 시스템으로 다른 컴포넌트와 통신
- 📦 **CollapsibleBox**: 접을 수 있는 박스로 UI 구성

### 다른 디렉터리와의 관계

```
modules/
  ├── interfaces/ 계약 준수 → BaseMiddleModule, ModeAwareModule
  ├── core/ 의존 → AppContext, 컨트롤러, 파이프라인
  ├── ui/ 사용 → theme, scaling_manager, modern_menu
  └── tabs/와 이벤트로 통신 → AppContext.publish/subscribe
```

**로딩 흐름**:
```
NAIA_cold_v4.py
    ↓
core/middle_section_controller.py
    ↓
modules/ 스캔 (*.py)
    ↓
BaseMiddleModule 상속 클래스 찾기
    ↓
인스턴스 생성 → AppContext 주입 → UI 배치
```

### 언제 modules/를 수정/추가하는가?

| 작업 | 파일 |
|------|------|
| **새 생성 옵션 추가** | 새 모듈 작성 (`my_feature_module.py`) |
| **프롬프트 전/후처리** | 파이프라인 훅 사용 |
| **모드별 설정 관리** | ModeAwareModule 다중 상속 |
| **사용자 설정 UI** | create_widget() 구현 |
| **이벤트 발행/구독** | AppContext 활용 |

---

## 주요 파일 및 역할

| 파일 | 크기 | 주요 기능 | 특징 |
|------|------|----------|------|
| **character_module.py** | 44K | 캐릭터 검색 및 프롬프트 적용 | ModeAware, 파이프라인 훅, 다이얼로그 |
| **character_reference_module.py** | 65K | Character Reference (CR) 관리 | NAI 전용, 이미지 선택, CR strength |
| **vibe_transfer_module.py** | 99K | Vibe Transfer 이미지 관리 | NAI 전용, 다중 이미지, information_extracted |
| **prompt_engineering_module.py** | 85K | 프롬프트 엔지니어링 도구 | 태그 조작, 가중치, 재배치, 🆕 프리셋 랜덤화 |
| **automation_module.py** | 43K | 자동 생성 (타이머/횟수/무제한) | QThread, 지연 기능 |
| **instant_wildcard_module.py** | 40K | 인스턴트 와일드카드 관리 | JSON 저장/로드, 이미지 미리보기 |
| **conditional_prompt_module.py** | 38K | 조건부 프롬프트 | 파이프라인 훅, 조건 평가 |
| **e621_event_module.py** | 40K | E621 이벤트 태그 관리 | Parquet 데이터, 즐겨찾기, 숨김/복원, 검색 |
| **wildcard_status_module.py** | 16K | 와일드카드 상태 표시 | PromptContext 구독 |

---

## 모듈 개발 기초

### 최소 구현 (30초로 시작)

**파일 생성**: `modules/hello_world_module.py`

```python
from interfaces.base_module import BaseMiddleModule
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

class HelloWorldModule(BaseMiddleModule):
    """최소 구현 예제"""

    def __init__(self):
        super().__init__()
        # 호환성 플래그 (선택)
        self.NAI_compatibility = True
        self.WEBUI_compatibility = True
        self.COMFYUI_compatibility = True

    def get_title(self) -> str:
        """모듈 제목 (필수)"""
        return "👋 Hello World"

    def create_widget(self, parent) -> QWidget:
        """UI 위젯 생성 (필수)"""
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel("Hello, NAIA 2.0!"))

        # ⚠️ 중요: 위젯 참조 저장 (모드 가시성 제어용)
        self.widget = widget
        return widget
```

**저장 후 재시작하면 즉시 로드됩니다!**

### 전체 계약 (BaseMiddleModule)

`interfaces/base_module.py:9-63`

#### 필수 메서드

```python
class BaseMiddleModule(ABC):
    @abstractmethod
    def get_title(self) -> str:
        """모듈 제목"""

    @abstractmethod
    def create_widget(self, parent) -> QWidget:
        """UI 위젯 생성"""
```

#### 선택적 메서드

```python
def get_order(self) -> int:
    """UI 순서 (낮을수록 위에 표시, 기본: 100)"""
    return 100

def get_parameters(self) -> dict:
    """생성 API 호출 시 추가할 파라미터"""
    return {}

def get_pipeline_hook_info(self) -> dict:
    """파이프라인 훅 등록 정보"""
    return {}

def execute_pipeline_hook(self, context) -> PromptContext:
    """파이프라인 훅 실행"""
    return context

def on_initialize(self):
    """모듈 초기화 시 호출"""
    pass

def is_compatible_with_mode(self, mode: str) -> bool:
    """모드 호환성 확인"""
    # 기본 구현 있음
```

### 호환성 플래그

`interfaces/base_module.py:13-16`

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

**사용 예시**:
```python
# NAI 전용 모듈
self.NAI_compatibility = True
self.WEBUI_compatibility = False
self.COMFYUI_compatibility = False
```

### AppContext 접근

**초기화 시점**: `MiddleSectionController.initialize_modules_with_context()` 호출 시

`core/middle_section_controller.py:103-143`

```python
def initialize_with_context(self, app_context):
    """AppContext 주입 시 호출되는 메서드 (선택적)"""
    self.app_context = app_context

    # 이벤트 구독
    app_context.subscribe("api_mode_changed", self._on_mode_changed)
    app_context.subscribe("prompt_generated", self._on_prompt_generated)

def _on_mode_changed(self, data: dict):
    old_mode = data["old_mode"]
    new_mode = data["new_mode"]
    # 모드 변경 처리

def _on_prompt_generated(self, context):
    # 프롬프트 생성 완료 처리
    pass
```

---

## ModeAware 모듈 개발

### ModeAwareModule이란?

**파일**: `interfaces/mode_aware_module.py:6-134`

백엔드(NAI/WEBUI/COMFYUI)별로 **다른 설정을 자동으로 저장/로드**하는 모듈입니다.

**자동 기능**:
- 모드 전환 시 이전 모드 설정 저장
- 새 모드 설정 자동 로드
- 호환되지 않는 모드에서 자동 숨김
- 설정 파일 경로: `save/<settings_base_filename>_<MODE>.json`

### ModeAware 모듈 작성

**예제**: `modules/character_module.py:1-200+`

```python
from interfaces.base_module import BaseMiddleModule
from interfaces.mode_aware_module import ModeAwareModule
from core.context import AppContext

class MyModeAwareModule(BaseMiddleModule, ModeAwareModule):
    """모드 인식 모듈 예제"""

    def __init__(self):
        BaseMiddleModule.__init__(self)
        ModeAwareModule.__init__(self)

        # ⚠️ 필수: 설정 파일 베이스 이름
        self.settings_base_filename = "my_module_settings"

        # 호환성 플래그
        self.NAI_compatibility = True
        self.WEBUI_compatibility = True
        self.COMFYUI_compatibility = False  # ComfyUI 미지원

        # UI 위젯 참조 (설정 저장/로드에 사용)
        self.checkbox = None
        self.input_field = None

    def get_title(self) -> str:
        return "🎯 My ModeAware Module"

    def create_widget(self, parent):
        from PyQt6.QtWidgets import QWidget, QVBoxLayout, QCheckBox, QLineEdit

        widget = QWidget(parent)
        layout = QVBoxLayout(widget)

        self.checkbox = QCheckBox("옵션 활성화")
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("설정 값 입력")

        layout.addWidget(self.checkbox)
        layout.addWidget(self.input_field)

        # ⚠️ 위젯 참조 저장
        self.widget = widget
        return widget

    # ⚠️ 필수: 현재 UI 상태 수집
    def collect_current_settings(self) -> dict:
        """현재 UI 상태를 딕셔너리로 수집"""
        return {
            "checkbox_state": self.checkbox.isChecked(),
            "input_value": self.input_field.text()
        }

    # ⚠️ 필수: 설정을 UI에 적용
    def apply_settings(self, settings: dict):
        """저장된 설정을 UI에 적용"""
        if "checkbox_state" in settings:
            self.checkbox.setChecked(settings["checkbox_state"])
        if "input_value" in settings:
            self.input_field.setText(settings["input_value"])

    # ⚠️ 필수: 모듈 이름 반환 (로깅용)
    def get_module_name(self) -> str:
        return self.get_title()
```

### 설정 파일 구조

**위치**: `save/my_module_settings_NAI.json`

```json
{
  "NAI": {
    "checkbox_state": true,
    "input_value": "NAI 전용 설정"
  }
}
```

**위치**: `save/my_module_settings_WEBUI.json`

```json
{
  "WEBUI": {
    "checkbox_state": false,
    "input_value": "WEBUI 전용 설정"
  }
}
```

### ModeAware 자동 동작

`interfaces/mode_aware_module.py:103-119`

```python
def on_mode_changed(self, old_mode: str, new_mode: str):
    """모드 변경 시 자동 호출 (자동 등록됨)"""
    print(f"'{self.get_module_name()}' 모드 변경: {old_mode} → {new_mode}")

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

---

## 파이프라인 훅 고급 기법

### 훅 포인트 복습

`core/prompt_processor.py:14-33`

```
1. pre_processing       ← 가장 먼저 실행
2. 해상도 자동 맞춤      (내부)
3. post_processing      ← 와일드카드 확장 전
4. 와일드카드 확장       (내부)
5. after_wildcard       ← 와일드카드 확장 후
6. final_hookpoint      ← 최종 포맷 전
7. 최종 포맷팅          (내부)
```

### 훅 우선순위 활용

**시나리오**: 여러 모듈이 같은 훅 포인트를 사용할 때, 실행 순서를 제어합니다.

```python
# 모듈 A: 품질 태그 추가 (가장 먼저)
class QualityModule(BaseMiddleModule):
    def get_pipeline_hook_info(self) -> dict:
        return {
            'target_pipeline': 'PromptProcessor',
            'hook_point': 'post_processing',
            'priority': 5  # 낮은 번호 = 먼저 실행
        }

    def execute_pipeline_hook(self, context):
        context.prefix_tags.insert(0, "masterpiece")
        return context
```

```python
# 모듈 B: 커스텀 태그 추가 (나중에)
class CustomTagModule(BaseMiddleModule):
    def get_pipeline_hook_info(self) -> dict:
        return {
            'target_pipeline': 'PromptProcessor',
            'hook_point': 'post_processing',
            'priority': 20  # 높은 번호 = 나중에 실행
        }

    def execute_pipeline_hook(self, context):
        context.main_tags.append("custom_style")
        return context
```

**실행 순서**: QualityModule (5) → CustomTagModule (20)

### PromptContext 활용

`core/prompt_context.py:1-50`

```python
class PromptContext:
    # 태그 리스트
    prefix_tags: List[str]      # 맨 앞에 추가할 태그
    main_tags: List[str]        # 메인 태그
    postfix_tags: List[str]     # 맨 뒤에 추가할 태그
    global_append_tags: List[str]  # 전역 추가 태그

    # 원본 데이터
    source_row: pd.Series       # 검색 결과 행
    settings: dict              # 생성 설정

    # 메타데이터
    metadata: dict              # 자유 형식 메타데이터
    sequential_counters: dict   # 순차 카운터 ($sequence)
    wildcard_state: dict        # 와일드카드 상태

    # 최종 결과
    final_prompt: str           # 최종 프롬프트 (파이프라인 완료 후)
```

### 고급 훅 예제

#### 예제 1: 조건부 태그 추가

**파일**: `modules/conditional_prompt_module.py:100-200+`

```python
def execute_pipeline_hook(self, context):
    """조건에 따라 태그 추가"""

    # 조건 1: 특정 태그가 있으면
    if "1girl" in context.main_tags:
        context.main_tags.append("solo")

    # 조건 2: 메타데이터 기반
    if context.metadata.get("auto_quality", False):
        context.prefix_tags.extend(["best quality", "highly detailed"])

    # 조건 3: 설정 기반
    if context.settings.get("nsfw_mode", False):
        context.postfix_tags.append("nsfw")
    else:
        context.postfix_tags.append("safe")

    return context
```

#### 예제 2: 태그 조작

```python
def execute_pipeline_hook(self, context):
    """태그 제거, 치환, 재배치"""

    # 특정 태그 제거
    if "unwanted_tag" in context.main_tags:
        context.main_tags.remove("unwanted_tag")

    # 태그 치환
    context.main_tags = [
        "new_tag" if tag == "old_tag" else tag
        for tag in context.main_tags
    ]

    # 태그 재배치 (특정 태그를 맨 앞으로)
    if "important_tag" in context.main_tags:
        context.main_tags.remove("important_tag")
        context.main_tags.insert(0, "important_tag")

    return context
```

#### 예제 3: 메타데이터 활용

```python
def execute_pipeline_hook(self, context):
    """메타데이터에 정보 저장 (다른 모듈/탭에서 사용)"""

    # 메타데이터 저장
    context.metadata["processed_by_my_module"] = True
    context.metadata["tag_count"] = len(context.main_tags)

    # 순차 카운터 사용
    if "$sequence" not in context.sequential_counters:
        context.sequential_counters["$sequence"] = 0

    counter = context.sequential_counters["$sequence"]
    context.main_tags.append(f"gen_{counter:04d}")
    context.sequential_counters["$sequence"] += 1

    return context
```

---

## 실전 예제

### 예제 0: QTextEdit 올바른 사용법 (5분) 🆕

**목표**: Rich Text 붙여넣기 차단이 적용된 QTextEdit 사용

**2025-01-17 업데이트**: 모든 QTextEdit에 `setAcceptRichText(False)` 적용 필수

```python
# modules/my_text_module.py
from interfaces.base_module import BaseMiddleModule
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QLabel
from ui.theme import DARK_STYLES
from ui.modern_menu import setModernStyle

class MyTextModule(BaseMiddleModule):
    def __init__(self):
        super().__init__()
        self.NAI_compatibility = True
        self.WEBUI_compatibility = True
        self.COMFYUI_compatibility = True

    def get_title(self) -> str:
        return "📝 텍스트 모듈"

    def create_widget(self, parent):
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)

        # 라벨
        label = QLabel("프롬프트 입력:")
        layout.addWidget(label)

        # ✅ 올바른 QTextEdit 사용법
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setAcceptRichText(False)  # 필수! 서식 붙여넣기 차단
        self.prompt_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.prompt_edit.setPlaceholderText("프롬프트를 입력하세요...")
        setModernStyle(self.prompt_edit)  # 태그 정보 + 와일드카드 기능
        layout.addWidget(self.prompt_edit)

        # 읽기 전용 로그
        log_label = QLabel("로그:")
        layout.addWidget(log_label)

        self.log_display = QTextEdit()
        self.log_display.setAcceptRichText(False)  # 읽기 전용도 필수!
        self.log_display.setReadOnly(True)
        self.log_display.setStyleSheet(DARK_STYLES['compact_textedit'])
        layout.addWidget(self.log_display)

        self.widget = widget
        return widget
```

**중요 포인트**:
- ✅ `setAcceptRichText(False)` 필수 - 웹 복사 서식 차단
- ✅ `DARK_STYLES['compact_textedit']` 스타일 적용
- ✅ `setModernStyle()` 호출 - 태그 정보 표시 기능
- ✅ PromptHighlighter와 완벽 호환 - 하이라이팅 정상 작동

**테스트 방법**:
1. 웹 페이지에서 색상/폰트가 있는 텍스트 복사
2. QTextEdit에 붙여넣기 (Ctrl+V)
3. ✅ 성공: Plain Text만 붙여넣기됨 (서식 제거)
4. ❌ 실패: 색상/폰트가 그대로 나타남 (setAcceptRichText 누락)

### 예제 1: 자동 태그 추가 모듈 (15분)

**목표**: 체크박스로 켜고 끄는 자동 품질 태그 추가 모듈

```python
# modules/auto_quality_module.py
from interfaces.base_module import BaseMiddleModule
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QCheckBox
from ui.theme import get_dynamic_styles

class AutoQualityModule(BaseMiddleModule):
    def __init__(self):
        super().__init__()
        self.NAI_compatibility = True
        self.WEBUI_compatibility = True
        self.COMFYUI_compatibility = True

        self.enabled = True

    def get_title(self) -> str:
        return "✨ Auto Quality"

    def get_order(self) -> int:
        return 10  # 위쪽에 표시

    def create_widget(self, parent):
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
        self.enabled = (state == 2)  # Qt.CheckState.Checked

    def get_pipeline_hook_info(self) -> dict:
        return {
            'target_pipeline': 'PromptProcessor',
            'hook_point': 'post_processing',
            'priority': 5
        }

    def execute_pipeline_hook(self, context):
        if not self.enabled:
            return context

        quality_tags = ["masterpiece", "best quality", "highly detailed"]
        context.prefix_tags = quality_tags + context.prefix_tags

        print(f"✅ Auto Quality: {len(quality_tags)}개 태그 추가")
        return context
```

### 예제 2: 이벤트 통신 모듈 (30분)

**목표**: 탭에서 파라미터를 받아 자동으로 설정을 반영하는 모듈

```python
# modules/param_receiver_module.py
from interfaces.base_module import BaseMiddleModule
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

class ParamReceiverModule(BaseMiddleModule):
    def __init__(self):
        super().__init__()
        self.received_params = {}

    def get_title(self) -> str:
        return "📥 Param Receiver"

    def create_widget(self, parent):
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)

        self.status_label = QLabel("대기 중...")
        layout.addWidget(self.status_label)

        self.widget = widget
        return widget

    def initialize_with_context(self, app_context):
        self.app_context = app_context

        # 탭에서 발행하는 이벤트 구독
        app_context.subscribe("parameters_extracted", self._on_params_received)

    def _on_params_received(self, params: dict):
        self.received_params = params

        # UI 업데이트
        param_count = len(params)
        self.status_label.setText(f"✅ {param_count}개 파라미터 수신")

        print(f"📥 수신된 파라미터: {list(params.keys())}")
```

### 예제 3: 파일 저장/로드 모듈 (1시간)

**목표**: JSON 파일로 커스텀 프리셋을 저장/로드

```python
# modules/preset_manager_module.py
import json
from pathlib import Path
from interfaces.base_module import BaseMiddleModule
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QComboBox, QMessageBox

class PresetManagerModule(BaseMiddleModule):
    def __init__(self):
        super().__init__()
        self.preset_dir = Path("save/presets")
        self.preset_dir.mkdir(parents=True, exist_ok=True)

    def get_title(self) -> str:
        return "💾 Preset Manager"

    def create_widget(self, parent):
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)

        # 프리셋 선택
        self.preset_combo = QComboBox()
        self.load_preset_list()
        layout.addWidget(self.preset_combo)

        # 버튼
        load_btn = QPushButton("프리셋 로드")
        load_btn.clicked.connect(self._load_preset)
        layout.addWidget(load_btn)

        save_btn = QPushButton("현재 설정 저장")
        save_btn.clicked.connect(self._save_preset)
        layout.addWidget(save_btn)

        self.widget = widget
        return widget

    def load_preset_list(self):
        """프리셋 목록 로드"""
        self.preset_combo.clear()
        preset_files = list(self.preset_dir.glob("*.json"))
        for preset_file in preset_files:
            self.preset_combo.addItem(preset_file.stem)

    def _save_preset(self):
        """현재 설정 저장"""
        from PyQt6.QtWidgets import QInputDialog

        preset_name, ok = QInputDialog.getText(
            self.widget, "프리셋 저장", "프리셋 이름:"
        )
        if not ok or not preset_name:
            return

        # 현재 설정 수집 (다른 모듈들에서)
        settings = self._collect_current_settings()

        # JSON 저장
        preset_file = self.preset_dir / f"{preset_name}.json"
        with open(preset_file, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)

        QMessageBox.information(self.widget, "성공", f"'{preset_name}' 저장 완료!")
        self.load_preset_list()

    def _load_preset(self):
        """프리셋 로드"""
        preset_name = self.preset_combo.currentText()
        if not preset_name:
            return

        preset_file = self.preset_dir / f"{preset_name}.json"
        if not preset_file.exists():
            return

        with open(preset_file, 'r', encoding='utf-8') as f:
            settings = json.load(f)

        # 설정 적용 (다른 모듈들에게)
        self._apply_settings(settings)

        QMessageBox.information(self.widget, "성공", f"'{preset_name}' 로드 완료!")

    def _collect_current_settings(self) -> dict:
        """현재 설정 수집 (예시)"""
        return {
            "example_setting": "value"
        }

    def _apply_settings(self, settings: dict):
        """설정 적용 (예시)"""
        print(f"설정 적용: {settings}")
```

### 예제 4: 캐릭터 위치 시스템 (2시간) 🆕

**목표**: 다중 캐릭터의 화면 위치를 5x5 그리드로 제어하는 시스템 구축

**파일**: `modules/character_module.py:1000-1500`

**주요 기능**:
- 5x5 그리드 위치 설정 (A-E, 1-5)
- 실시간 위치 시각화 (25x25px 이미지)
- 랜덤 위치 배치 (가운데 C3 제외 옵션)
- 자동 리롤 (생성 시 위치 자동 재배치)
- 안전장치 (2명 미만 시 자동 비활성화)
- 좌표 매핑 (A-E → x: 0.1-0.9, 1-5 → y: 0.1-0.9)

#### 1. UI 구성 요소

```python
from PyQt6.QtWidgets import QCheckBox, QPushButton, QLabel, QHBoxLayout
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtCore import Qt
from PIL import Image, ImageDraw
from ui.theme import DARK_COLORS, DARK_STYLES
from ui.scaling_manager import get_scaled_size
import random

class CharacterModule(BaseMiddleModule):
    def __init__(self):
        super().__init__()

        # 🆕 캐릭터 위치 관련 속성
        self.enable_position_checkbox: QCheckBox = None
        self.position_button: QPushButton = None
        self.position_viewer: QLabel = None
        self.random_position_button: QPushButton = None
        self.auto_reroll_checkbox: QCheckBox = None
        self.character_positions: List[str] = ["C3"] * 6  # 기본 중앙
        self.exclude_center_on_random: bool = True  # 가운데 비우기 기본값

    def create_widget(self, parent):
        # ... 기존 UI 구성 ...

        # ✅ 위치 활성화 체크박스
        self.enable_position_checkbox = QCheckBox("캐릭터 위치 사용")
        self.enable_position_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.enable_position_checkbox.stateChanged.connect(self._on_position_toggle)

        # ✅ 위치 설정 버튼
        self.position_button = QPushButton("위치 설정")
        self.position_button.setStyleSheet(DARK_STYLES['secondary_button'])
        self.position_button.setFixedWidth(get_scaled_size(100))
        self.position_button.clicked.connect(self._open_position_manager)
        self.position_button.setEnabled(False)

        # ✅ 위치 미리보기 (60x60, 25x25 이미지를 50x50으로 스케일)
        self.position_viewer = QLabel()
        self.position_viewer.setFixedSize(get_scaled_size(60), get_scaled_size(60))
        self.position_viewer.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
            }}
        """)

        # ✅ 랜덤 위치 버튼
        self.random_position_button = QPushButton("🔄")
        self.random_position_button.setStyleSheet(DARK_STYLES['secondary_button'])
        self.random_position_button.setFixedWidth(get_scaled_size(45))
        self.random_position_button.setToolTip("위치 무작위 배치 (가운데 제외)")
        self.random_position_button.clicked.connect(self._on_random_position_clicked)
        self.random_position_button.setEnabled(False)

        # ✅ 자동 리롤 체크박스
        self.auto_reroll_checkbox = QCheckBox("A")
        self.auto_reroll_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.auto_reroll_checkbox.setToolTip("생성 시 위치 자동 리롤")
        self.auto_reroll_checkbox.setChecked(False)

        # 컨트롤 레이아웃 (한 줄에 배치)
        position_control_layout = QHBoxLayout()
        position_control_layout.addWidget(self.position_button)
        position_control_layout.addWidget(self.position_viewer)
        position_control_layout.addWidget(self.random_position_button)
        position_control_layout.addWidget(self.auto_reroll_checkbox)
        position_control_layout.addStretch()

        # ... 레이아웃에 추가 ...
```

#### 2. 위치 시각화 시스템

**개요**: 25x25px 이미지에 5x5 셀을 그려서 각 캐릭터의 위치를 표시합니다.

```python
def _update_position_viewer(self):
    """위치 시각화 이미지 업데이트"""
    # 25x25 이미지 생성 (5x5 그리드, 각 셀 5x5px)
    img = Image.new('RGB', (25, 25), DARK_COLORS['bg_secondary'])
    draw = ImageDraw.Draw(img)

    # 활성 캐릭터들의 위치에 사각형 그리기
    for idx, widget in enumerate(self.character_widgets):
        if not widget.active_checkbox.isChecked():
            continue

        if idx >= len(self.character_positions):
            continue

        pos = self.character_positions[idx]
        if not pos or len(pos) < 2:
            continue

        # 위치 파싱 (예: "D4" → col=3, row=3)
        col = ord(pos[0]) - ord('A')  # A=0, B=1, ..., E=4
        row = int(pos[1]) - 1          # 1=0, 2=1, ..., 5=4

        # 좌표 계산 (각 셀 5x5px)
        x = col * 5
        y = row * 5

        # 캐릭터별 색상 (파스텔 톤)
        colors = [
            (255, 182, 193),  # 핑크
            (173, 216, 230),  # 하늘색
            (144, 238, 144),  # 연두색
            (255, 218, 185),  # 복숭아색
            (221, 160, 221),  # 자주색
            (255, 255, 224)   # 크림색
        ]
        color = colors[idx % len(colors)]

        # 사각형 그리기 [x, y, x+4, y+4] (5x5 셀)
        draw.rectangle([x, y, x + 4, y + 4], fill=color, outline=None)

    # PIL → QPixmap 변환
    img_bytes = img.tobytes("raw", "RGB")
    q_image = QImage(img_bytes, 25, 25, 25 * 3, QImage.Format.Format_RGB888)
    pixmap = QPixmap.fromImage(q_image).scaled(
        get_scaled_size(50), get_scaled_size(50),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation  # 부드러운 스케일링
    )

    self.position_viewer.setPixmap(pixmap)
```

**좌표 매핑 표**:

| 위치 | col | row | x | y | 범위 | 실제 좌표 (API) |
|------|-----|-----|---|---|------|----------------|
| A1 | 0 | 0 | 0 | 0 | [0,0,4,4] | x:0.1, y:0.1 |
| C3 | 2 | 2 | 10 | 10 | [10,10,14,14] | x:0.5, y:0.5 |
| E5 | 4 | 4 | 20 | 20 | [20,20,24,24] | x:0.9, y:0.9 |

#### 3. 랜덤 위치 배치

```python
def _on_random_position_clicked(self):
    """🔄 랜덤 버튼 클릭 시 위치 무작위 배치"""
    # 활성 캐릭터 수 확인
    active_indices = [i for i, w in enumerate(self.character_widgets)
                      if w.active_checkbox.isChecked()]

    if len(active_indices) < 2:
        print("⚠️ 활성 캐릭터가 2명 미만입니다. 랜덤 배치 불가.")
        return

    # 5x5 그리드 전체 위치
    all_positions = [f"{col}{row}" for col in ['A', 'B', 'C', 'D', 'E']
                     for row in ['1', '2', '3', '4', '5']]

    # 가운데 C3 제외 옵션
    if self.exclude_center_on_random:
        all_positions = [pos for pos in all_positions if pos != 'C3']

    # 활성 캐릭터 수만큼 랜덤 선택 (중복 없이)
    selected_positions = random.sample(all_positions, len(active_indices))

    # 위치 할당
    for active_idx, position in zip(active_indices, selected_positions):
        while len(self.character_positions) <= active_idx:
            self.character_positions.append("C3")
        self.character_positions[active_idx] = position

    # 시각화 업데이트
    self._update_position_viewer()

    print(f"🎲 무작위 위치 배치 완료: {selected_positions}")
```

#### 4. 안전장치 (2명 미만 시 자동 비활성화)

```python
def _check_and_update_position_safety(self):
    """안전장치: 활성 캐릭터가 2명 미만이면 포지션 기능 자동 해제"""
    enabled_count = sum(1 for w in self.character_widgets
                        if w.active_checkbox.isChecked())

    if enabled_count < 2 and self.enable_position_checkbox.isChecked():
        # 자동 해제
        self.enable_position_checkbox.setChecked(False)
        self.enable_position_checkbox.setEnabled(False)
        print(f"⚠️ 활성 캐릭터 {enabled_count}명 → 포지션 기능 자동 해제 및 비활성화")
    elif enabled_count >= 2 and not self.enable_position_checkbox.isEnabled():
        # 다시 활성화 가능하도록 변경
        self.enable_position_checkbox.setEnabled(True)
        print(f"✅ 활성 캐릭터 {enabled_count}명 → 포지션 기능 활성화 가능")

# 캐릭터 추가/제거/체크박스 변경 시 호출
def add_character_widget(self, ...):
    # ... 위젯 추가 ...
    char_widget.active_checkbox.stateChanged.connect(
        lambda: self._check_and_update_position_safety()
    )
    self._check_and_update_position_safety()

def _remove_character_widget_internal(self, ...):
    # ... 위젯 제거 ...
    self._check_and_update_position_safety()
```

#### 5. 좌표 매핑 시스템 (API 전달)

```python
def get_parameters(self) -> dict:
    """모듈 파라미터 반환 (API 호출 시 사용)"""
    if not self.activate_checkbox or not self.activate_checkbox.isChecked():
        return {"characters": None}

    params = self.modifiable_clone.copy()

    # 🆕 캐릭터 위치 좌표 매핑
    if self.enable_position_checkbox and self.enable_position_checkbox.isChecked():
        # A: 자동 리롤 체크되어 있으면 먼저 위치 리롤
        if self.auto_reroll_checkbox and self.auto_reroll_checkbox.isChecked():
            self._on_random_position_clicked()

        # 좌표 매핑 테이블
        x_mapping = {'A': 0.1, 'B': 0.3, 'C': 0.5, 'D': 0.7, 'E': 0.9}
        y_mapping = {'1': 0.1, '2': 0.3, '3': 0.5, '4': 0.7, '5': 0.9}

        # 활성화된 캐릭터들의 위치만 변환
        character_coords = []
        for idx, widget in enumerate(self.character_widgets):
            if widget.active_checkbox.isChecked():
                if idx < len(self.character_positions):
                    pos = self.character_positions[idx]
                    if pos and len(pos) >= 2:
                        x = x_mapping.get(pos[0], 0.5)
                        y = y_mapping.get(pos[1], 0.5)
                        character_coords.append({'x': x, 'y': y})
                    else:
                        character_coords.append({'x': 0.5, 'y': 0.5})
                else:
                    character_coords.append({'x': 0.5, 'y': 0.5})

        params['character_positions'] = character_coords
        print(f"📍 캐릭터 위치 좌표: {character_coords}")

    return params
```

#### 6. API 서비스 통합

**파일**: `core/api_service.py:424-452`

```python
# API 파라미터 수집 시
if char_params and char_params.get("characters"):
    characters = char_params["characters"]
    ucs = char_params["uc"]
    # 🆕 캐릭터 위치 좌표 가져오기
    character_positions = char_params.get("character_positions", [])

    # 캐릭터 프롬프트를 v4_prompt에 추가
    for i, prompt in enumerate(characters):
        # 🆕 동적 좌표 사용 (위치가 지정되어 있으면 사용, 없으면 기본값 0.5)
        if i < len(character_positions):
            centers = [character_positions[i]]
        else:
            centers = [{"x": 0.5, "y": 0.5}]

        api_parameters['v4_prompt']['caption']['char_captions'].append({
            'char_caption': prompt,
            'centers': centers  # 동적 좌표 전달
        })
```

#### 7. 주요 특징 정리

| 기능 | 설명 | 코드 위치 |
|------|------|----------|
| **5x5 그리드** | A-E (열), 1-5 (행) | `character_module.py:1200` |
| **실시간 시각화** | 25x25px 이미지, 50x50px 표시 | `_update_position_viewer()` |
| **랜덤 배치** | 🔄 버튼, C3 제외 옵션 | `_on_random_position_clicked()` |
| **자동 리롤** | A 체크박스, 생성 시 리롤 | `get_parameters()` |
| **안전장치** | 2명 미만 시 자동 비활성화 | `_check_and_update_position_safety()` |
| **좌표 매핑** | A-E: 0.1-0.9, 1-5: 0.1-0.9 | `get_parameters()` |
| **API 통합** | 동적 좌표 전달 | `api_service.py:440-451` |

#### 8. 테스트 시나리오

```
1. 캐릭터 2명 추가
   → 위치 체크박스 활성화 가능

2. "위치 설정" 클릭
   → 5x5 그리드 다이얼로그 표시

3. C1: A1, C2: E5 설정
   → 미리보기에 두 점 표시 (좌상단, 우하단)

4. 🔄 버튼 클릭
   → 랜덤 위치 배치 (C3 제외)
   → 미리보기 업데이트

5. A 체크박스 활성화
   → 생성 버튼 클릭 시 자동 리롤

6. 이미지 생성
   → 콘솔 출력: "📍 캐릭터 위치 좌표: [{'x': 0.1, 'y': 0.1}, {'x': 0.9, 'y': 0.9}]"
   → API 호출 시 centers에 동적 좌표 전달

7. 캐릭터 1명 제거
   → 위치 기능 자동 비활성화
```

#### 9. 문제 해결

**Q: E5 위치가 표시되지 않아요**
- **원인**: 20x20 이미지에서 [16,16,19,19] 범위가 스케일링 시 손실됨
- **해결**: 25x25 이미지로 변경, SmoothTransformation 사용

**Q: 좌표가 항상 0.5로 나와요**
- **원인**: `character_positions` 파라미터가 API 서비스로 전달되지 않음
- **해결**: `get_parameters()`에서 `character_coords` 생성 및 반환 확인

**Q: 자동 리롤이 작동하지 않아요**
- **원인**: `auto_reroll_checkbox`가 체크되어 있지만 `_on_random_position_clicked()` 호출 안 됨
- **해결**: `get_parameters()`에서 체크박스 상태 확인 후 호출

**참고 문서**:
- `docs/character_position_coordinate_verification.md`: 좌표 계산 검증 문서
- `core/CLAUDE.md`: API 서비스 동적 좌표 처리

### 예제 5: E621 이벤트 모듈 (데이터 관리 패턴) 🆕

**목표**: Parquet 데이터 기반의 이벤트 태그 관리 모듈 이해

**e621_event_module.py 핵심 구조**:

```python
from interfaces.base_module import BaseMiddleModule
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QRadioButton, QButtonGroup, QDialog
)
from pathlib import Path
import json

class E621EventModule(BaseMiddleModule):
    def __init__(self):
        super().__init__()
        # 데이터 파일 경로
        self.parquet_path = Path("data/e621_sample.parquet")
        self.deleted_path = Path("save/e621_event/deleted.json")
        self.starred_path = Path("save/e621_event/starred.json")

        # 상태 관리
        self.event_dict = {}  # {key: (value0, value1)}
        self.deleted_keys = set()  # 숨긴 키
        self.starred_keys = set()  # 즐겨찾기 키
        self.current_keys = []  # 전체 키 (원본 순서)
        self.filtered_keys = []  # 검색 결과
        self.is_searching = False
```

**주요 기능**:

| 기능 | 설명 | 구현 방법 |
|------|------|-----------|
| **데이터 로드** | Parquet 파일에서 이벤트 데이터 로드 | `load_parquet_file()`, pandas 사용 |
| **검색** | key → value0 → value1 순서로 검색 | `on_search()`, 정규식 지원 |
| **즐겨찾기** | 별표 토글, 노란색 표시 | `on_star_clicked()`, JSON 저장 |
| **숨김/복원** | 항목 숨기기 및 복원 다이얼로그 | `on_hide_clicked()`, `HiddenItemsDialog` |
| **보기 모드** | 기본 보기 / 즐겨찾기 보기 전환 | 라디오버튼, `get_display_keys()` |

**UI 레이아웃**:

```
┌─────────────────────────────────────────────────┐
│ 이벤트 리스트: (○ 기본 보기) (○ 즐겨찾기 보기)  │
├─────────────────────────────────────────────────┤
│ [검색 입력] [검색] [초기화]                      │
├───────────────────────────────┬─────────────────┤
│                               │ [다음] (100px)  │
│  테이블 (Key | Value)         │ [생성] (100px)  │
│  - 즐겨찾기 항목: 노란색       │ [★/☆] (40px)   │
│                               │   (stretch)     │
│                               │ [관리] (40px)   │
│                               │ [숨김] (40px)   │
└───────────────────────────────┴─────────────────┘
│ 태그 값: [편집 가능 텍스트박스]                  │
│ 자동 숨김 태그: [입력]  □ 자동 강조처리 해제    │
└─────────────────────────────────────────────────┘
```

**핵심 헬퍼 메서드 - `get_display_keys()`**:

```python
def get_display_keys(self) -> list:
    """현재 보기 모드에 따른 표시 키 목록 반환"""
    # 1. 검색 상태 확인
    if self.is_searching:
        display_keys = self.filtered_keys
    else:
        display_keys = self.current_keys

    # 2. 즐겨찾기 보기 모드 필터링
    if self.radio_starred and self.radio_starred.isChecked():
        display_keys = [key for key in display_keys if key in self.starred_keys]

    return display_keys
```

**즐겨찾기 색상 표시**:

```python
def update_table(self):
    display_keys = self.get_display_keys()

    # 노란색 브러시 (즐겨찾기용)
    from PyQt6.QtGui import QColor, QBrush
    starred_color = QBrush(QColor("#FFD700"))  # Gold

    for i, key in enumerate(display_keys):
        is_starred = key in self.starred_keys

        key_item = QTableWidgetItem(key)
        if is_starred:
            key_item.setForeground(starred_color)
        self.table_widget.setItem(i, 0, key_item)
```

**숨긴 항목 복원 (원본 순서 유지)**:

```python
def restore_hidden_items(self, keys_to_restore: List[str]):
    import pandas as pd
    df = pd.read_parquet(self.parquet_path)

    # 복원할 항목 딕셔너리에 추가
    for _, row in df.iterrows():
        key = str(row.iloc[0])
        if key in keys_to_restore:
            self.event_dict[key] = (str(row.iloc[1]), str(row.iloc[2]))
            self.deleted_keys.discard(key)

    # ⚠️ 핵심: parquet 원본 순서대로 current_keys 재구성
    self.current_keys = []
    for _, row in df.iterrows():
        key = str(row.iloc[0])
        if key in self.event_dict:
            self.current_keys.append(key)
```

**라디오버튼 보기 모드**:

```python
# UI 설정
self.view_mode_group = QButtonGroup(self.widget)

self.radio_default = QRadioButton("기본 보기")
self.radio_default.setChecked(True)
self.radio_default.toggled.connect(self.on_view_mode_changed)
self.view_mode_group.addButton(self.radio_default, 0)

self.radio_starred = QRadioButton("즐겨찾기 보기")
self.radio_starred.toggled.connect(self.on_view_mode_changed)
self.view_mode_group.addButton(self.radio_starred, 1)

# 모드 변경 핸들러
def on_view_mode_changed(self, checked: bool):
    if checked:  # toggled는 체크/해제 모두 발생하므로 체크만 처리
        self.update_table()
```

**HiddenItemsDialog (숨긴 항목 관리)**:

```python
class HiddenItemsDialog(QDialog):
    """단일 선택 리스트로 숨긴 항목 복원"""

    def __init__(self, deleted_keys: set, parquet_path: Path, parent=None):
        super().__init__(parent)
        self.list_widget = QListWidget()
        # ⚠️ PyQt6 다중 선택 버그 방지: 단일 선택만 허용
        self.list_widget.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.list_widget.setDragDropMode(
            QAbstractItemView.DragDropMode.NoDragDrop
        )
```

**데이터 파일 구조**:

```
data/
└── e621_sample.parquet    # 원본 데이터 (3컬럼: key, value0, value1)

save/e621_event/
├── deleted.json           # {"deleted_keys": ["key1", "key2", ...]}
└── starred.json           # {"starred_keys": ["key3", "key4", ...]}
```

**학습 포인트**:
- ✅ Parquet + pandas로 대용량 데이터 효율적 처리
- ✅ JSON으로 사용자 상태 영속화 (숨김, 즐겨찾기)
- ✅ `get_display_keys()` 헬퍼로 일관된 필터링 로직
- ✅ 라디오버튼 그룹으로 보기 모드 전환
- ✅ 원본 순서 유지하며 항목 복원
- ✅ QDialog로 독립적인 관리 UI 제공

---

## 단계별 튜토리얼

### 30분 튜토리얼: Hello World + 이벤트

1. **파일 생성** (`modules/hello_event_module.py`)
2. **기본 구조** (BaseMiddleModule 상속)
3. **UI 작성** (버튼 + 라벨)
4. **이벤트 구독** (api_mode_changed)
5. **이벤트 발행** (버튼 클릭 시)
6. **테스트** (앱 재시작)

### 2시간 튜토리얼: 파이프라인 훅 모듈

1. **파일 생성** (`modules/my_hook_module.py`)
2. **훅 정보 반환** (get_pipeline_hook_info)
3. **훅 실행** (execute_pipeline_hook)
4. **UI 토글** (체크박스로 활성화/비활성화)
5. **디버깅** (print 문으로 확인)
6. **테스트** (프롬프트 생성 후 확인)

### 1일 튜토리얼: ModeAware 모듈

1. **파일 생성** (`modules/my_modeaware_module.py`)
2. **ModeAwareModule 다중 상속**
3. **설정 파일 베이스 이름 지정**
4. **collect_current_settings 구현**
5. **apply_settings 구현**
6. **호환성 플래그 설정**
7. **모드 전환 테스트** (NAI ↔ WEBUI)

### 1주 튜토리얼: 복합 모듈

1. **QThread 워커 사용** (무거운 작업)
2. **파일 저장/로드** (JSON/이미지)
3. **다이얼로그 통합** (검색, 설정)
4. **파이프라인 훅 + 이벤트 혼합**
5. **에러 처리** (try/except, 사용자 알림)
6. **리소스 정리** (cleanup 메서드)

---

## 고급 패턴

### QThread 패턴 (모듈에서 무거운 작업)

**예제**: `modules/automation_module.py:17-55`

```python
from PyQt6.QtCore import QThread, pyqtSignal

class HeavyWorkerThread(QThread):
    """무거운 작업을 수행하는 스레드"""
    progress_updated = pyqtSignal(str)
    work_finished = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.data = None

    def set_data(self, data):
        self.data = data

    def run(self):
        """스레드 실행 (UI 블로킹 없음)"""
        try:
            # 무거운 작업 수행
            result = self._do_heavy_work(self.data)

            # 완료 시그널
            self.work_finished.emit(result)
        except Exception as e:
            print(f"워커 에러: {e}")

    def _do_heavy_work(self, data):
        import time
        time.sleep(5)  # 예시: 5초 소요
        return {"status": "success"}

# 모듈에서 사용
class MyModule(BaseMiddleModule):
    def create_widget(self, parent):
        # ... UI 구성 ...

        btn = QPushButton("무거운 작업 시작")
        btn.clicked.connect(self._start_heavy_work)
        return widget

    def _start_heavy_work(self):
        self.worker = HeavyWorkerThread()
        self.worker.set_data({"key": "value"})
        self.worker.progress_updated.connect(self._on_progress)
        self.worker.work_finished.connect(self._on_finished)

        # ⚠️ 중요: 정리 연결
        self.worker.finished.connect(self.worker.deleteLater)

        self.worker.start()

    def _on_progress(self, message):
        print(f"진행: {message}")

    def _on_finished(self, result):
        print(f"완료: {result}")
```

### 다이얼로그 패턴

**예제**: `modules/character_module.py:24-400+`

```python
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QPushButton
from PyQt6.QtCore import pyqtSignal

class MyDialog(QDialog):
    """커스텀 다이얼로그"""
    result_selected = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("선택")
        self.setModal(True)  # 모달 다이얼로그

        layout = QVBoxLayout(self)

        ok_btn = QPushButton("확인")
        ok_btn.clicked.connect(self._on_ok)
        layout.addWidget(ok_btn)

    def _on_ok(self):
        result = {"selected": "value"}
        self.result_selected.emit(result)
        self.accept()  # 다이얼로그 닫기

# 모듈에서 사용
class MyModule(BaseMiddleModule):
    def create_widget(self, parent):
        # ... UI 구성 ...

        btn = QPushButton("다이얼로그 열기")
        btn.clicked.connect(self._open_dialog)
        return widget

    def _open_dialog(self):
        dialog = MyDialog(parent=self.widget)
        dialog.result_selected.connect(self._on_result)
        dialog.exec()  # 모달 실행

    def _on_result(self, result):
        print(f"선택 결과: {result}")
```

### 이미지 처리 패턴

**예제**: `modules/instant_wildcard_module.py:26-150`

```python
from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QPixmap, QPainter
from PyQt6.QtCore import Qt
from PIL import Image
from pathlib import Path

class ImagePreviewWidget(QWidget):
    """이미지 미리보기 위젯"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None

    def load_image(self, image_path: Path):
        """이미지 로드"""
        if image_path.exists():
            self._pixmap = QPixmap(str(image_path))
            self.update()  # 다시 그리기

    def clear_image(self):
        """이미지 클리어"""
        self._pixmap = None
        self.update()

    def paintEvent(self, event):
        """이미지 그리기"""
        painter = QPainter(self)

        if not self._pixmap:
            # 플레이스홀더 표시
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                           "이미지를 로드하세요")
            return

        # 위젯 크기에 맞춰 스케일링
        scaled_pixmap = self._pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        # 중앙 정렬
        x = (self.width() - scaled_pixmap.width()) // 2
        y = (self.height() - scaled_pixmap.height()) // 2
        painter.drawPixmap(x, y, scaled_pixmap)

# 모듈에서 사용
class MyModule(BaseMiddleModule):
    def create_widget(self, parent):
        # ... UI 구성 ...

        self.preview = ImagePreviewWidget()
        self.preview.load_image(Path("path/to/image.png"))
        return widget
```

### Skip Flag 패턴 (임시 창 이중 실행 방지)

**목적**: 임시 생성 창(Temporary Generation Window)과 메인 UI에서 동일한 파이프라인 훅이 중복 실행되는 것을 방지합니다.

**사용 사례**: 임시 창에서 Random/Next Prompt 버튼을 누를 때, 메인 UI의 훅과 임시 창의 Virtual Module 훅이 동시에 실행되어 서로 다른 규칙이 적용되는 문제를 해결합니다.

#### 문제 상황

임시 창에서 Random Prompt를 생성할 때, 다음과 같은 문제가 발생합니다:

```
Random/Next Prompt 버튼 클릭
    ↓
메인 UI trigger_random_prompt() 호출 (메인 UI 프롬프트 생성 로직 재사용)
    ↓
🔧 메인 PromptEngineeringModule.execute_pipeline_hook() 실행
   → Auto Hide: 태그 A, B, C 제거
    ↓
🔧 임시 창 VirtualPromptEngineeringTab.execute_manual_hook() 실행
   → Auto Hide: 태그 D, E, F 제거
    ↓
❌ 결과: 서로 다른 Auto Hide 규칙이 중복 적용되어 의도하지 않은 태그 제거
```

#### 해결책: AppContext Skip Flag

**핵심 아이디어**: AppContext에 동적 플래그를 추가하여, 특정 조건에서 메인 모듈의 훅 실행을 건너뜁니다.

**구현 단계**:

1. **AppContext에 플래그 추가** (동적 속성, 명시적 선언 불필요):
```python
# core/context.py (자동으로 추가됨)
# 사용 시 setattr/getattr로 동적 설정
self.app_context.skip_prompt_engineering_hook = False
```

2. **메인 모듈에서 플래그 확인** (`modules/prompt_engineering_module.py:343-346`):
```python
def execute_pipeline_hook(self, context: PromptContext) -> PromptContext:
    """기존 파이프라인 훅 로직 유지"""

    # 🆕 임시 창 프롬프트 생성 중에는 메인 UI 훅 건너뛰기
    if hasattr(self, 'app_context') and getattr(self.app_context, 'skip_prompt_engineering_hook', False):
        print("[DEBUG] 🚫 메인 PromptEngineeringModule 훅 건너뛰기 (임시 창 프롬프트 생성 중)")
        return context

    print("🔧 프롬프트 엔지니어링 훅 실행...")

    # ... 기존 로직 계속 실행 ...
    # 프리픽스 태그 추가
    # 포스트픽스 태그 추가
    # Auto Hide 처리
    # 전처리 옵션 적용

    return context
```

3. **임시 창 관리자에서 플래그 제어** (`NAIA_cold_v4.py:521-586`):
```python
class TempWindowManager:
    def handle_random_prompt_request(self, temp_window):
        """임시 창에서 Random/Next Prompt 요청 처리"""
        try:
            # 🆕 메인 PromptEngineeringModule 훅 비활성화
            self.main_window.app_context.skip_prompt_engineering_hook = True
            print("[DEBUG] ✅ skip_prompt_engineering_hook = True 설정")

            # 메인 UI의 Random Prompt 생성 로직 호출
            new_main_prompt = self.main_window.trigger_random_prompt()

            # 🆕 임시 창의 프롬프트 엔지니어링 훅 수동 실행
            if hasattr(temp_window, 'prompt_engineering_tab'):
                print(f"[DEBUG] 임시 창 프롬프트 엔지니어링 훅 실행 중...")

                # PromptContext 생성
                from core.prompt_context import PromptContext
                import pandas as pd

                source_row = self.main_window.app_context.current_source_row
                if source_row is None:
                    source_row = pd.Series({'general': None}, name="temp_window_random")

                # tags 파싱
                input_tags = [tag.strip() for tag in new_main_prompt.split(',') if tag.strip()]

                # PromptContext 초기화
                temp_context = PromptContext(
                    source_row=source_row,
                    settings={},
                    prefix_tags=[],
                    main_tags=input_tags,
                    postfix_tags=[]
                )

                # 수동 훅 실행
                try:
                    modified_context = temp_window.prompt_engineering_tab.execute_manual_hook(temp_context)
                    all_tags = modified_context.prefix_tags + modified_context.main_tags + modified_context.postfix_tags
                    new_main_prompt = ', '.join(all_tags)
                    print(f"[DEBUG] ✅ 임시 창 프롬프트 엔지니어링 적용 완료")
                except Exception as e:
                    print(f"[DEBUG] ⚠️ 임시 창 프롬프트 엔지니어링 훅 실행 오류: {e}")

            # 임시 창에 최종 프롬프트 적용
            temp_window.main_prompt_input.setPlainText(new_main_prompt)

        finally:
            # 🆕 메인 PromptEngineeringModule 훅 재활성화 (필수!)
            self.main_window.app_context.skip_prompt_engineering_hook = False
            print("[DEBUG] ✅ skip_prompt_engineering_hook = False 해제")
```

#### 실행 흐름 (수정 후)

```
Random/Next Prompt 버튼 클릭 (임시 창)
    ↓
skip_prompt_engineering_hook = True 설정
    ↓
메인 UI trigger_random_prompt() 호출
    ↓
🚫 메인 PromptEngineeringModule 훅 건너뛰기 (플래그 체크)
    ↓
프롬프트 생성 완료 (메인 UI 로직만 적용)
    ↓
🔧 임시 창 VirtualPromptEngineeringTab.execute_manual_hook() 실행
   → Auto Hide: 태그 D, E, F 제거 (임시 창 규칙 적용)
    ↓
skip_prompt_engineering_hook = False 해제 (finally 블록)
    ↓
✅ 결과: 임시 창 Auto Hide 규칙만 정확히 적용됨
```

#### 중요 포인트

1. **finally 블록 필수**: 예외 발생 시에도 플래그를 반드시 해제해야 합니다.
   ```python
   try:
       self.app_context.skip_xxx_hook = True
       # ... 작업 ...
   finally:
       self.app_context.skip_xxx_hook = False  # 필수!
   ```

2. **getattr 안전 접근**: 플래그가 없을 경우 기본값 False 반환
   ```python
   if getattr(self.app_context, 'skip_xxx_hook', False):
       return context
   ```

3. **디버깅 로그**: 플래그 설정/해제 시점 확인
   ```python
   print(f"[DEBUG] ✅ skip_xxx_hook = {value}")
   ```

4. **확장 가능**: 다른 모듈에도 동일한 패턴 적용 가능
   - `skip_character_hook`
   - `skip_wildcard_hook`
   - `skip_conditional_prompt_hook`

#### 관련 파일

- `modules/prompt_engineering_module.py:343-346` - Skip flag 체크
- `NAIA_cold_v4.py:521-586` - Flag 관리 (TempWindowManager)
- `ui/virtual_prompt_engineering_tab.py` - Virtual Module 구현
- `core/generation_controller.py:375-411` - Manual hook execution

#### 참고 사항

- **Virtual Module 패턴과의 조합**: Skip Flag는 Virtual Module 패턴과 함께 사용되어 임시 창 시스템의 독립성을 보장합니다. 자세한 내용은 `ui/CLAUDE.md`의 "임시 생성 창 시스템" 섹션을 참고하세요.

---

### EZ Mode: Selective Preprocessing Skip (2025-01-19)

**배경**: EZ Mode에서 "즉시 생성" 기능 사용 시, Prompt Engineering Module의 일부 전처리 기능만 선택적으로 비활성화해야 합니다.

**요구사항**:
- ✅ **유지**: 선행 고정 프롬프트 (Leading Fixed Prompt)
- ✅ **유지**: 후행 고정 프롬프트 (Trailing Fixed Prompt)
- ❌ **건너뛰기**: 작품명/작가명/캐릭터명 자동 추가 (preprocessing_options)
- ❌ **건너뛰기**: Auto Hide 태그 제거
- ❌ **건너뛰기**: 캐릭터 특징 제거 (remove_character_features)
- ❌ **건너뛰기**: 의류 정보 제거 (remove_clothes)
- ❌ **건너뛰기**: 색상 포함 태그 제거 (remove_color)
- ❌ **건너뛰기**: 위치/배경색 제거 (remove_location_and_background_color)

#### 구현: `skip_prompt_engineering_auto_hide` Flag

**파일**: `modules/prompt_engineering_module.py`

**1. 플래그 체크 및 초기화** (Line 352-389):
```python
def execute_pipeline_hook(self, context: PromptContext) -> PromptContext:
    """프롬프트 엔지니어링 훅"""

    # 🆕 EZ Mode 즉시 생성 시 전처리 옵션 및 Auto Hide만 건너뛰기
    skip_preprocessing = hasattr(self, 'app_context') and \
                        getattr(self.app_context, 'skip_prompt_engineering_auto_hide', False)

    if skip_preprocessing:
        print("[DEBUG] 🚫 Auto Hide 건너뛰기 (EZ Mode 즉시 생성)")

    # ... 선행/후행 고정 프롬프트 처리 (항상 실행) ...

    # 전처리 옵션 (조건부)
    if not skip_preprocessing:
        # 작품명, 작가명, 캐릭터명 자동 추가
        if checkbox_options.get("add_work_name"):
            # ...
    else:
        # EZ Mode: checkbox_options 초기화 (이후 코드에서 사용되지 않도록)
        checkbox_options = {}

    # Auto Hide (조건부)
    if not skip_preprocessing:
        # Auto Hide 로직 실행
        hidden_tags = self._auto_hide_tags(...)
        print(f"Auto Hide로 제거된 태그: {', '.join(hidden_tags) if hidden_tags else '없음'}")
    else:
        print("Auto Hide로 제거된 태그: 없음")

    # ... 나머지 로직 ...
```

**2. 추가 전처리 옵션 스킵** (Line 489-533):
```python
# 캐릭터 특징, 의류, 색상, 위치/배경색 제거 (조건부)
if not skip_preprocessing:
    # "remove_character_features"
    if checkbox_options.get("remove_character_features"):
        # ... 제거 로직 ...

    # "remove_clothes"
    if checkbox_options.get("remove_clothes"):
        # ... 제거 로직 ...

    # "remove_color"
    if checkbox_options.get("remove_color"):
        # ... 제거 로직 ...

    # "remove_location_and_background_color"
    if checkbox_options.get("remove_location_and_background_color"):
        # ... 제거 로직 ...
```

**3. EZ Mode 윈도우에서 플래그 설정** (`NAIA_cold_v4.py:3805-3807`):
```python
# EZ Mode 창 닫기 시 플래그 정리
if hasattr(self.app_context, 'skip_prompt_engineering_auto_hide') and \
   self.app_context.skip_prompt_engineering_auto_hide:
    self.app_context.skip_prompt_engineering_auto_hide = False
    print(f"[MainWindow] ✅ skip_prompt_engineering_auto_hide = False 해제 (Auto Hide 재활성화)")
```

**4. EZ Mode Controller에서 플래그 제어** (`ui/ezmode/ezmode_controller.py`):
```python
def _on_instant_generate(self):
    """즉시 생성 버튼 클릭"""
    # Virtual Row 생성 전 플래그 설정
    if hasattr(self, 'app_context'):
        self.app_context.skip_prompt_engineering_auto_hide = True
        print("[Controller] ✅ skip_prompt_engineering_auto_hide = True 설정")

    # Virtual Row 생성 및 신호 발행
    virtual_row = self._create_virtual_row()
    self.instant_generation_requested.emit(virtual_row)

    # Note: 플래그는 MainWindow에서 이미지 생성 완료 후 해제됨
```

#### 실행 흐름

```
EZ Mode "즉시 생성" 버튼 클릭
    ↓
skip_prompt_engineering_auto_hide = True 설정 (Controller)
    ↓
Virtual Row 생성 및 신호 발행
    ↓
MainWindow.on_generate_with_image_requested() 호출
    ↓
프롬프트 파이프라인 실행
    ↓
PromptEngineeringModule.execute_pipeline_hook() 실행
    ↓
플래그 체크: skip_preprocessing = True
    ↓
✅ 선행/후행 고정 프롬프트 적용
🚫 전처리 옵션 (작품명/작가명/캐릭터명) 건너뛰기
🚫 Auto Hide 건너뛰기
🚫 추가 전처리 (캐릭터 특징/의류/색상/위치) 건너뛰기
    ↓
이미지 생성 시작
    ↓
skip_prompt_engineering_auto_hide = False 해제 (MainWindow)
    ↓
✅ 결과: EZ Mode 태그 + 고정 프롬프트만 적용된 이미지 생성
```

#### 중요 포인트

1. **checkbox_options 초기화**: `skip_preprocessing = True`일 때 `checkbox_options = {}`로 초기화하여 이후 코드에서 KeyError 방지

2. **조건부 블록 포괄**: 모든 전처리 관련 코드(`if checkbox_options.get(...)`)를 `if not skip_preprocessing:` 블록 내부에 배치

3. **플래그 정리**: EZ Mode 창 닫기 시 또는 생성 완료 후 플래그를 반드시 `False`로 재설정

4. **디버깅 로그**: 각 단계마다 명확한 로그 출력으로 동작 확인
   ```
   [DEBUG] 🚫 Auto Hide 건너뛰기 (EZ Mode 즉시 생성)
   Auto Hide로 제거된 태그: 없음
   ```

#### 관련 파일

- `modules/prompt_engineering_module.py:352-389` - 플래그 체크 및 초기화
- `modules/prompt_engineering_module.py:489-533` - 추가 전처리 옵션 스킵
- `ui/ezmode/ezmode_controller.py` - 플래그 설정 (즉시 생성 시)
- `NAIA_cold_v4.py:3805-3807` - 플래그 정리 (EZ Mode 창 닫기 시)

#### 문제 해결

**Q**: 선행/후행 고정 프롬프트가 적용되지 않아요

**A**: `skip_preprocessing` 체크가 너무 이른 위치에 있는지 확인. 고정 프롬프트 처리는 플래그와 무관하게 항상 실행되어야 함.

**Q**: `checkbox_options` KeyError 발생

**A**: `else:` 블록에서 `checkbox_options = {}` 초기화가 누락되었는지 확인 (Line 387-389).

**Q**: Auto Hide가 계속 실행됨

**A**: `skip_preprocessing` 변수가 올바르게 설정되었는지 확인. `getattr(self.app_context, 'skip_prompt_engineering_auto_hide', False)` 값 확인.

---

## 문제 해결

### Q1: 모듈이 로드되지 않아요

**증상**: 앱을 재시작해도 모듈이 좌측에 표시되지 않음

**체크리스트**:
```
[ ] 파일명이 *_module.py인가?
[ ] BaseMiddleModule을 상속했는가?
[ ] get_title()과 create_widget()을 구현했는가?
[ ] 파이썬 문법 오류가 없는가?
```

**디버깅**:
```python
# 콘솔 출력 확인
# 로딩 실패 시 에러 메시지 표시됨
```

### Q2: 모드 전환 시 설정이 사라져요

**원인**: ModeAwareModule 미상속 또는 collect_current_settings 미구현

**해결**:
```python
class MyModule(BaseMiddleModule, ModeAwareModule):
    def __init__(self):
        BaseMiddleModule.__init__(self)
        ModeAwareModule.__init__(self)

        self.settings_base_filename = "my_module"

    def collect_current_settings(self) -> dict:
        return {"key": self.widget.text()}

    def apply_settings(self, settings: dict):
        if "key" in settings:
            self.widget.setText(settings["key"])
```

### Q3: 이벤트가 전달되지 않아요

**원인**: initialize_with_context()에서 구독 안 함

**해결**:
```python
def initialize_with_context(self, app_context):
    self.app_context = app_context

    # ✅ 여기서 구독
    app_context.subscribe("my_event", self._on_my_event)

def _on_my_event(self, data):
    print(f"이벤트 수신: {data}")
```

### Q4: 파이프라인 훅이 실행되지 않아요

**원인**: get_pipeline_hook_info() 미구현 또는 context 미반환

**해결**:
```python
def get_pipeline_hook_info(self) -> dict:
    return {
        'target_pipeline': 'PromptProcessor',
        'hook_point': 'post_processing',
        'priority': 10
    }

def execute_pipeline_hook(self, context):
    # 작업 수행
    context.main_tags.append("my_tag")

    # ✅ 반드시 context 반환
    return context
```

### Q5: UI가 업데이트되지 않아요

**원인**: QThread에서 직접 UI 수정 시도

**해결**:
```python
# ❌ 잘못된 방법
class MyWorker(QThread):
    def run(self):
        self.label.setText("업데이트")  # UI 스레드 아님!

# ✅ 올바른 방법
class MyWorker(QThread):
    update_label = pyqtSignal(str)

    def run(self):
        self.update_label.emit("업데이트")

# 모듈에서
def _start_worker(self):
    self.worker = MyWorker()
    self.worker.update_label.connect(self.label.setText)
    self.worker.start()
```

---

## 체크리스트

### 새 모듈 작성 시

```
[ ] 파일명이 *_module.py인가?
[ ] BaseMiddleModule 상속
[ ] get_title() 구현
[ ] create_widget() 구현
[ ] self.widget = widget 저장 (가시성 제어용)
[ ] 호환성 플래그 설정 (NAI/WEBUI/COMFYUI)
[ ] 동적 스타일 사용 (get_dynamic_styles)
[ ] 스케일링 함수 사용 (get_scaled_*)
```

### ModeAware 모듈 작성 시

```
[ ] ModeAwareModule 다중 상속
[ ] settings_base_filename 설정
[ ] collect_current_settings() 구현
[ ] apply_settings() 구현
[ ] get_module_name() 구현
[ ] 호환성 플래그 설정
```

### 파이프라인 훅 사용 시

```
[ ] get_pipeline_hook_info() 구현
[ ] 올바른 hook_point 지정
[ ] priority 설정 (충돌 방지)
[ ] execute_pipeline_hook()에서 context 반환
[ ] 부작용 최소화 (context만 수정)
```

### QThread 사용 시

```
[ ] QThread 클래스 정의
[ ] 시그널 정의 (progress, finished, error)
[ ] finished.connect(deleteLater) 연결 (메모리 누수 방지)
[ ] UI 업데이트는 시그널로만
```

### QTextEdit 사용 시 🆕 (2025-01-17)

```
[ ] setAcceptRichText(False) 호출 확인 (필수!)
[ ] DARK_STYLES['compact_textedit'] 스타일 적용
[ ] setModernStyle() 호출 (선택, 태그 정보 필요 시)
[ ] setPlaceholderText() 설정 (선택)
[ ] 웹 복사 붙여넣기 테스트 (서식 제거 확인)
[ ] PromptHighlighter 적용 시 하이라이팅 정상 확인
```

---

## 참고 자료

### 관련 문서

- **[최상위 CLAUDE.md](../CLAUDE.md)**: 전체 프로젝트 개요
- **[core/CLAUDE.md](../core/CLAUDE.md)**: 컨트롤러 및 파이프라인 상세
- **[interfaces/CLAUDE.md](../interfaces/CLAUDE.md)**: 계약 정의
- **[ui/CLAUDE.md](../ui/CLAUDE.md)**: UI 컴포넌트 및 테마

### 예제 코드 위치

| 예제 | 파일 | 특징 |
|------|------|------|
| **ModeAware 모듈** | `modules/character_module.py` | 다이얼로그, 파일 저장/로드 |
| **QThread 사용** | `modules/automation_module.py` | 타이머, 카운터 |
| **파일 저장/로드** | `modules/instant_wildcard_module.py` | JSON, 이미지 |
| **파이프라인 훅** | `modules/conditional_prompt_module.py` | 조건부 프롬프트 |
| **이벤트 구독** | `modules/wildcard_status_module.py` | PromptContext 구독 |

### 의존성

**modules/가 의존하는 디렉터리**:
- `interfaces/` - BaseMiddleModule, ModeAwareModule
- `core/` - AppContext, PromptContext, WildcardProcessor
- `ui/` - theme, scaling_manager, modern_menu

---

### 예제 5: 프리셋 랜덤화 시스템 (Preset Randomizer) 🆕 (2025-01-08)

**목표**: 여러 프리셋 중에서 무작위로 선택하여 적용하는 기능 구현

**파일**: `modules/prompt_engineering_module.py`

**주요 기능**:
- 퀵 프리셋 콤보박스에 `*randomized` 특수 항목 추가
- 랜덤 프리셋 풀(ListBox)에서 프리셋 추가/제거
- 자동 생성 시 랜덤하게 프리셋 선택 및 적용
- ListBox 아이템 클릭으로 수동 프리셋 로드

#### 1. UI 구성 요소

```python
# 인스턴스 변수 (__init__)
self.is_randomized_mode = False
self.randomized_preset_list = []  # ListBox에 표시될 프리셋 목록

# UI 위젯 참조
self.randomized_layout_widget = None  # *randomized 전용 UI 컨테이너
self.randomized_listbox = None  # QListWidget - 랜덤 프리셋 목록
self.randomized_combo = None  # 프리셋 선택 복제 콤보박스
self.randomized_add_btn = None  # [+추가] 버튼
self.randomized_remove_btn = None  # [-제거] 버튼
```

#### 2. UI 레이아웃 (create_widget)

```python
# === *randomized 전용 UI 레이아웃 ===
self.randomized_layout_widget = QWidget()
randomized_layout = QVBoxLayout(self.randomized_layout_widget)

# 1) 랜덤 프리셋 목록 Label
randomized_label = QLabel("랜덤 프리셋 목록:")

# 2) 랜덤 프리셋 목록 ListBox
self.randomized_listbox = QListWidget()
self.randomized_listbox.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
self.randomized_listbox.setFixedHeight(100)
self.randomized_listbox.itemClicked.connect(self._on_randomized_listbox_item_clicked)

# 3) 프리셋 선택 + 버튼 행
selection_layout = QHBoxLayout()
selection_label = QLabel("선택:")

self.randomized_combo = QComboBox()  # *randomized, default 제외한 프리셋 목록
self.randomized_add_btn = QPushButton("+추가")
self.randomized_remove_btn = QPushButton("-제거")

self.randomized_layout_widget.setVisible(False)  # 초기 숨김
```

#### 3. 콤보박스에 *randomized 항목 추가 (load_preset_list)

```python
def load_preset_list(self):
    # [*randomized]를 첫 번째로 추가
    self.preset_combo.addItem("*randomized")

    # default 및 기타 프리셋 추가
    self.preset_combo.addItems(preset_names)
```

#### 4. 프리셋 전환 처리 (on_preset_changed)

```python
def on_preset_changed(self, preset_name):
    if preset_name == "*randomized":
        # *randomized 모드 활성화
        self.is_randomized_mode = True
        self._show_randomized_ui()
        self.randomized_add_btn.setEnabled(False)  # 선택 전 비활성화
    else:
        # 일반 모드
        self.is_randomized_mode = False
        self._hide_randomized_ui()
        self.randomized_add_btn.setEnabled(True)
```

#### 5. 추가/제거 버튼 핸들러

```python
def _add_to_randomized_list(self):
    """복제 콤보박스에서 선택한 프리셋을 ListBox에 추가"""
    preset_name = self.randomized_combo.currentText()

    if not preset_name or preset_name in self.randomized_preset_list:
        return

    # ListBox에 추가
    self.randomized_listbox.addItem(preset_name)
    self.randomized_preset_list.append(preset_name)

    # 복제 콤보박스에서 해당 항목 숨김 (hide, not disable)
    self._update_randomized_combo()

def _remove_from_randomized_list(self):
    """ListBox에서 선택한 프리셋 제거"""
    current_item = self.randomized_listbox.currentItem()
    if not current_item:
        return

    preset_name = current_item.text()

    # ListBox에서 제거
    row = self.randomized_listbox.row(current_item)
    self.randomized_listbox.takeItem(row)
    self.randomized_preset_list.remove(preset_name)

    # 복제 콤보박스에서 해당 항목 복원
    self._update_randomized_combo()
```

#### 6. 복제 콤보박스 업데이트

```python
def _update_randomized_combo(self):
    """복제 콤보박스 업데이트 - *randomized, default 제외, 이미 추가된 항목 숨김"""
    self.randomized_combo.clear()

    for preset_name in self.preset_list:
        # *randomized, default 제외
        if preset_name in ["*randomized", "default"]:
            continue

        # 이미 ListBox에 있는 항목 숨김
        if preset_name in self.randomized_preset_list:
            continue

        self.randomized_combo.addItem(preset_name)

    # +추가 버튼 상태 갱신 (콤보에 항목이 있을 때만 활성화)
    has_items = self.randomized_combo.count() > 0
    self.randomized_add_btn.setEnabled(has_items and self.current_preset != "*randomized")
```

#### 7. 신호 통합 (random_prompt_triggered)

```python
def initialize_with_context(self, app_context):
    # 랜덤 프롬프트 신호 구독
    app_context.subscribe("random_prompt_triggered", self._on_random_prompt_triggered)
    app_context.subscribe("random_prompt_triggered_preset_randomizer", self._on_random_prompt_triggered)

def _on_random_prompt_triggered(self, _data=None):
    """random_prompt_triggered 신호 수신 시 호출 - 랜덤 프리셋 선택"""
    if self.current_preset != "*randomized":
        return

    if not self.randomized_preset_list:
        print("⚠️ 랜덤 프리셋 목록이 비어있습니다")
        return

    # 랜덤하게 프리셋 선택
    import random
    selected_preset = random.choice(self.randomized_preset_list)

    print(f"🎲 랜덤 프리셋 선택: {selected_preset}")
    self.load_preset_random(selected_preset)
```

#### 8. ListBox 아이템 클릭 핸들러

```python
def _on_randomized_listbox_item_clicked(self, item):
    """랜덤 프리셋 목록에서 아이템 클릭 시 해당 프리셋 로드"""
    if item is None:
        return

    selected_preset = item.text()
    if selected_preset:
        print(f"🎯 사용자가 랜덤 프리셋 목록에서 선택: {selected_preset}")
        self.load_preset_random(selected_preset)
```

#### 9. 랜덤 프리셋 로드 (부분 적용)

```python
def load_preset_random(self, preset_name: str):
    """랜덤 프리셋 로드 - pre_prompt, post_prompt만 적용, main_settings는 prompt 제외하고 적용"""
    preset_file = self.get_preset_dir() / f"{preset_name}.json"

    if not preset_file.exists():
        print(f"⚠️ 프리셋 파일을 찾을 수 없음: {preset_name}")
        return

    with open(preset_file, 'r', encoding='utf-8') as f:
        preset_data = json.load(f)

    # module_settings에서 pre_prompt, post_prompt만 적용
    module_settings = preset_data.get("module_settings", {})

    if "pre_prompt" in module_settings:
        self.pre_prompt_input.setPlainText(module_settings["pre_prompt"])

    if "post_prompt" in module_settings:
        self.post_prompt_input.setPlainText(module_settings["post_prompt"])

    # main_settings 적용 (prompt 제외)
    main_settings = preset_data.get("main_settings", {})
    if main_settings:
        main_settings.pop("prompt", None)  # prompt는 적용하지 않음

        if self.app_context:
            self.app_context.publish("apply_preset_main_settings", main_settings)
```

#### 10. API 모드 변경 시 처리

```python
def on_api_mode_changed_preset(self, data: dict):
    """API 모드 변경 시 프리셋 저장/로드"""
    # *randomized 모드에서는 저장하지 않고 상태만 초기화
    if self.current_preset == "*randomized":
        print("🎲 *randomized 모드 해제: 랜덤 프리셋 목록 초기화")
        self._reset_randomized_state()
    elif self.current_preset and self.current_preset != "(프리셋 없음)":
        self.save_current_preset()

def _reset_randomized_state(self):
    """*randomized 모드 상태 초기화"""
    self.is_randomized_mode = False
    self.randomized_preset_list.clear()

    if self.randomized_listbox:
        self.randomized_listbox.clear()

    if self.randomized_layout_widget:
        self.randomized_layout_widget.setVisible(False)

    # 복제 콤보박스 초기화
    self._update_randomized_combo()
```

#### 주요 특징 정리

| 기능 | 설명 | 코드 위치 |
|------|------|----------|
| **\*randomized 항목** | 퀵 프리셋 콤보박스 최상위 | `load_preset_list()` |
| **랜덤 프리셋 풀** | QListWidget으로 프리셋 목록 관리 | `create_widget()` |
| **추가/제거** | +추가로 풀에 추가, -제거로 풀에서 제거 | `_add_to_randomized_list()` |
| **항목 숨김** | 추가된 항목은 콤보에서 숨김 (비활성화 대신) | `_update_randomized_combo()` |
| **랜덤 선택** | 자동 생성 시 풀에서 무작위 선택 | `_on_random_prompt_triggered()` |
| **수동 로드** | ListBox 아이템 클릭 시 해당 프리셋 로드 | `_on_randomized_listbox_item_clicked()` |
| **부분 적용** | pre_prompt, post_prompt, main_settings(prompt 제외) | `load_preset_random()` |
| **모드 전환** | API 모드 변경 시 상태 초기화 | `_reset_randomized_state()` |

#### 테스트 시나리오

```
1. *randomized 선택
   → 랜덤 프리셋 UI 표시
   → +추가 버튼 비활성화

2. 콤보박스에서 프리셋 선택 후 +추가 클릭
   → ListBox에 추가됨
   → 콤보박스에서 해당 항목 숨김

3. ListBox에서 프리셋 클릭
   → 해당 프리셋의 pre_prompt, post_prompt, main_settings(prompt 제외) 적용

4. 자동 생성 실행
   → 랜덤으로 프리셋 선택
   → 콘솔: "🎲 랜덤 프리셋 선택: preset_name"

5. API 모드 변경 (NAI → WEBUI)
   → *randomized 상태 초기화
   → 콘솔: "🎲 *randomized 모드 해제: 랜덤 프리셋 목록 초기화"
```

#### 관련 신호

- `random_prompt_triggered`: 랜덤 프롬프트 생성 시 발행 (automation_module 등)
- `random_prompt_triggered_preset_randomizer`: 자동 생성 시 발행 (NAIA_cold_v4.py)
- `apply_preset_main_settings`: main_settings 적용 요청

---

## 변경 이력

### 2025-01-08: 프리셋 랜덤화 시스템 추가 🆕

**파일**: `modules/prompt_engineering_module.py`

**추가된 기능**:
- `*randomized` 특수 프리셋 항목
- 랜덤 프리셋 풀 UI (QListWidget, QComboBox, 추가/제거 버튼)
- 자동 생성 시 랜덤 프리셋 선택 (`_on_random_prompt_triggered`)
- ListBox 아이템 클릭 시 프리셋 로드 (`_on_randomized_listbox_item_clicked`)
- 부분 프리셋 로드 (`load_preset_random`) - pre_prompt, post_prompt, main_settings(prompt 제외)
- API 모드 변경 시 상태 초기화 (`_reset_randomized_state`)

**관련 파일**:
- `NAIA_cold_v4.py`: `random_prompt_triggered_preset_randomizer` 신호 발행 추가

---

### 2025-01-10: Vibe Transfer 메타데이터 복원 버그 수정

**파일**: `modules/vibe_transfer_module.py`

#### 문제
메타데이터에서 import한 Vibe Transfer 데이터가 API 요청에 반영되지 않아 생성 결과가 기대와 다름

#### 원인
1. **잘못된 encoding 키 사용**: `_add_vibe_frame_from_metadata()` 및 `_add_vibe_frame_from_noimage_import()`에서 `reference_strength_multiple` 값을 `vibe_encodings`의 키로 사용 (정답: `reference_information_extracted_multiple` 또는 기본값 1.0)
2. **NAID3 IE 값 누락**: `get_vibe_transfer_multiple_data()`에서 `frame.information_extracted` 사용 시 no_image 프레임은 항상 1.0으로 전달됨
3. **None 값 처리 미흡**: `reference_image_multiple`이 `None`인 경우 TypeError 발생

#### 수정 내용

**1. `_add_vibe_frame_from_metadata()` (line 1689-1771)**:
```python
# ❌ 이전 (잘못됨)
for i, strength in enumerate(strength_values):
    frame.vibe_encodings[float(strength)] = vibe_data['reference_image_multiple'][i]

# ✅ 수정 (올바름)
ref_img_multiple = vibe_data.get('reference_image_multiple') or []
ref_ie_multiple = vibe_data.get('reference_information_extracted_multiple') or []

if ref_ie_multiple and len(ref_ie_multiple) > 0:
    # NAID3: IE 값을 키로 사용
    for i, ie_value in enumerate(ref_ie_multiple):
        if i < len(ref_img_multiple):
            frame.vibe_encodings[float(ie_value)] = ref_img_multiple[i]
else:
    # NAID4/4.5: 기본값 1.0을 키로 사용
    for i, encoding in enumerate(ref_img_multiple):
        frame.vibe_encodings[1.0] = encoding
        break
```

**2. `get_vibe_transfer_multiple_data()` (line 2047-2108)**:
```python
# ❌ 이전
if is_naid3:
    reference_information_extracted_multiple.append(frame.information_extracted)  # 항상 1.0

# ✅ 수정
if is_naid3:
    reference_information_extracted_multiple.append(closest_key)  # 실제 encoding 키 사용
```

**3. None 값 안전 처리**:
- `reference_image_multiple`이 `None`이거나 빈 리스트인 경우 조기 종료
- 사용자에게 경고 메시지 표시

#### 관련 파일
- `ui/metadata_viewer.py`: Vibe Transfer 필드를 `important_fields`에 추가 (line 110-114)
- `core/api_service.py`: 디버깅 로그 정리

---

## 요약

**modules/ 개발 핵심**:
- ✅ **BaseMiddleModule** 상속 필수
- ✅ **ModeAwareModule** 다중 상속으로 모드별 설정 관리
- ✅ **파이프라인 훅**으로 프롬프트 생성 개입
- ✅ **AppContext 이벤트**로 느슨한 결합
- ✅ **QThread**로 UI 블로킹 방지
- ✅ **동적 스타일**로 테마 일관성
- ✅ **QTextEdit.setAcceptRichText(False)** 필수 (2025-01-17)
  - 🆕 웹 복사 서식 차단, PromptHighlighter 호환

**다음 단계**:
1. [ui/CLAUDE.md](../ui/CLAUDE.md)에서 QTextEdit 상세 가이드 확인
2. [tabs/CLAUDE.md](../tabs/CLAUDE.md)에서 탭 개발 학습
3. 예제 모듈 분석 (character, automation 등)
4. 실제 모듈 작성 연습

---

*문서 버전: 1.3*
*최종 업데이트: 2025-01-08*
*담당 영역: modules/ 디렉터리*
