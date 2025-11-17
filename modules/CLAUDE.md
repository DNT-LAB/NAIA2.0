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
| **prompt_engineering_module.py** | 78K | 프롬프트 엔지니어링 도구 | 태그 조작, 가중치, 재배치 |
| **automation_module.py** | 43K | 자동 생성 (타이머/횟수/무제한) | QThread, 지연 기능 |
| **instant_wildcard_module.py** | 40K | 인스턴트 와일드카드 관리 | JSON 저장/로드, 이미지 미리보기 |
| **conditional_prompt_module.py** | 38K | 조건부 프롬프트 | 파이프라인 훅, 조건 평가 |
| **e621_event_module.py** | 35K | E621 이벤트 태그 자동 추가 | 날짜 기반, 파이프라인 훅 |
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

## 변경 이력

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

*문서 버전: 1.2*
*최종 업데이트: 2025-01-17*
*담당 영역: modules/ 디렉터리*
