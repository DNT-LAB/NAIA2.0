# CLAUDE.md — NAIA 2.0 (최상위 개발 가이드)

> **목적**: Claude Code 및 주니어 개발자가 NAIA 2.0에서 효과적으로 작업할 수 있도록 돕는 가이드입니다.

**문서 구조**:
- **본 파일**: 프로젝트 개요, 빠른 시작, 핵심 개념, 개발 워크플로우
- **디렉터리별 CLAUDE.md**: 각 영역의 상세 가이드 (`core/`, `modules/`, `tabs/`, `ui/`, `interfaces/`, `utils/`, `data/`)
- **디렉터리별 `.claude/` 폴더**: 상세 레퍼런스 문서 (2,000줄 이상 문서는 세부 항목을 분리)
  - 예: `core/.claude/GENERATION_QUEUE_CLAUDE.md`, `core/.claude/CHANGELOG_CLAUDE.md`
- **AGENTS.md**: AI 협업을 위한 기술적 레퍼런스 (상세 API/계약/프로토콜)

**📝 문서 관리 방침** (2025-01-18):
- **CLAUDE.md 파일 크기 제한**: 각 CLAUDE.md는 2,000줄 이하로 유지
- **레퍼런스 분리**: 2,000줄 초과 시 상세 내용을 `<directory>/.claude/*_CLAUDE.md`로 분리
- **명명 규칙**: 레퍼런스 파일명은 반드시 `*_CLAUDE.md` 패턴 사용
- **Git 추적**: `.gitignore`에서 `!**/.claude/*.md` 예외 설정으로 레퍼런스 포함
- **링크 방식**: 메인 문서에서 핵심만 설명, 상세는 레퍼런스 링크로 안내
  - 예: `**상세 레퍼런스**: [Generation Queue 가이드](.claude/GENERATION_QUEUE_CLAUDE.md)`

**📚 문서화 현황** (2025-01-09 업데이트):
- ✅ **core/CLAUDE.md** (v1.5): AppContext, 컨트롤러, 파이프라인, API 서비스
  - 🆕 ImageCrudController 파일명 형식, 분류 시스템, 타임스탬프 폴더 토글
  - 🆕 **MiddleSectionController**: 모듈 상태 추적, 아코디언 동작, 자동 스크롤
  - 🆕 **SequenceParser**: 시퀀스 프롬프트 파싱 (`:begin`, `:seq`, `:end`)
  - 🆕 **GenerationController**: 시퀀스 생성 지원, NAI 랜덤 시드 처리
- ✅ **modules/CLAUDE.md** (v1.3): 모듈 개발 가이드, 파이프라인 훅, 모드 인식
  - 🆕 **프리셋 랜덤화 시스템**: `*randomized` 특수 프리셋, 랜덤 프리셋 풀 관리, 자동/수동 프리셋 선택
- ✅ **tabs/CLAUDE.md** (v1.6): 탭 개발 가이드, 시그널 브리징, 생명주기
  - 🆕 Settings 탭: 타임스탬프 폴더 토글, 분류 규칙 UI, 2차 분류 시스템
  - 🆕 **모듈/탭 가시성**: 프로그램 시작 시 자동 적용, 재시도 메커니즘, 디버깅 로그
  - 🐛 **버그 수정** (2025-01-21): 분류 방법 변경 시 크래시 해결 (AttributeError)
  - 🆕 **Studio Tab** (v2.0): 다중 프레임 그리드, 순차 생성, 프리셋 시스템, 그리드 내보내기
    - **tabs/studio/CLAUDE.md**: 전용 상세 가이드 추가
- ✅ **ui/CLAUDE.md** (v1.3): 테마 시스템, 스케일링, 공용 위젯, 분리 창
  - 🆕 **CollapsibleBox**: 상태 추적, 스크롤 위치 저장/복원, 프로그래밍 제어
  - 🆕 **PromptHighlighter**: 시퀀스 토큰 하이라이팅 (`:begin`, `:seq`, `:end`)
- ✅ **interfaces/CLAUDE.md** (완료): 계약 정의, 다중 상속 패턴, Breaking Change 방지
- ✅ **utils/CLAUDE.md** (완료): 이미지 메타데이터, 토큰 계산, 번역, 파라미터 관리
- ✅ **data/CLAUDE.md** (완료): Parquet 데이터베이스, 텍스트 사전, 검색 시스템

모든 디렉터리 문서는 실전 예제, 문제 해결 가이드, 체크리스트를 포함합니다.

**우선순위**: 사용자 직접 요청 > 디렉터리별 CLAUDE.md > 본 문서 > AGENTS.md

---

## 목차

1. [프로젝트 개요](#프로젝트-개요)
2. [빠른 시작 (Quick Start)](#빠른-시작-quick-start)
3. [핵심 아키텍처 개념](#핵심-아키텍처-개념)
4. [개발 워크플로우](#개발-워크플로우)
5. [디렉터리별 가이드](#디렉터리별-가이드)
6. [중요 시스템 가이드](#중요-시스템-가이드)
7. [문제 해결 및 디버깅](#문제-해결-및-디버깅)

---

## 프로젝트 개요

### NAIA 2.0이란?

NAIA 2.0은 **PyQt6 기반의 AI 이미지 생성 데스크톱 애플리케이션**입니다.

**핵심 특징**:
- 🎨 **다중 백엔드 지원**: NovelAI, Stable Diffusion WebUI, ComfyUI
- 🧩 **모듈식 아키텍처**: 플러그인 방식의 확장 가능한 구조
- 🔄 **이벤트 기반 통신**: 느슨한 결합으로 유지보수성 확보
- 🎯 **모드 인식 시스템**: 백엔드별 자동 설정 전환

### 핵심 원칙 (반드시 지켜야 함)

1. **AppContext 중심 설계**: 모든 공유 상태/서비스는 `AppContext`를 통해 접근
2. **이벤트 기반 통신**: 직접 위젯 조작 금지. 이벤트 발행/구독 사용
3. **파이프라인 훅 시스템**: 프롬프트 생성 과정에 모듈이 개입할 수 있는 표준화된 방법
4. **UI 스레드 보호**: 네트워크/파일 IO는 반드시 QThread로 분리
5. **동적 스케일링**: 모든 UI 요소는 해상도별 스케일링 함수 사용

### 기술 스택

| 분야 | 기술 |
|------|------|
| **UI** | PyQt6, PyQt6-WebEngine |
| **데이터** | pandas, pyarrow |
| **네트워크** | requests, websocket-client |
| **이미지** | Pillow (PIL) |
| **보안** | cryptography (Fernet), keyring |
| **토큰화** | tiktoken |

---

## 빠른 시작 (Quick Start)

### 처음 시작하는 개발자를 위한 5단계

#### 1단계: 환경 설정 (5분)

```bash
# 가상환경 생성 및 활성화
python -m venv venv

# Windows
venv\Scripts\activate.bat

# macOS/Linux
source venv/bin/activate

# 의존성 설치
pip install -r requirements.txt  # Windows
pip install -r requirements_mac.txt  # macOS
```

#### 2단계: 프로젝트 구조 이해 (10분)

```
NAIA2.0/
├── NAIA_cold_v4.py          # 📌 메인 진입점
├── core/                     # 📌 핵심 시스템 (컨트롤러, API, 파이프라인)
│   ├── context.py           # AppContext - 중앙 상태 관리
│   ├── *_controller.py      # 각종 컨트롤러
│   └── prompt_processor.py  # 프롬프트 파이프라인
├── interfaces/               # 📌 계약 정의 (추상 클래스)
│   ├── base_module.py       # 모듈 인터페이스
│   └── mode_aware_module.py # 모드 인식 모듈 인터페이스
├── modules/                  # 📌 좌측 패널 모듈 (자동 로드)
│   └── *_module.py          # BaseMiddleModule 상속
├── tabs/                     # 📌 우측 패널 탭 (자동 로드)
│   └── *_tab.py             # BaseTabModule 상속
├── ui/                       # 📌 UI 컴포넌트 및 테마
│   ├── theme.py             # 다크 테마 및 스타일
│   └── scaling_manager.py   # 동적 스케일링
├── utils/                    # 📌 유틸리티 함수
└── data/                     # 📌 데이터 파일 (태그, 와일드카드 등)
```

#### 3단계: 첫 번째 모듈 작성 (15분)

**파일 생성**: `modules/hello_world_module.py`

```python
from interfaces.base_module import BaseMiddleModule
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel

class HelloWorldModule(BaseMiddleModule):
    """간단한 예제 모듈"""

    def __init__(self):
        super().__init__()
        # 호환성 플래그 (어떤 모드에서 보일지)
        self.NAI_compatibility = True
        self.WEBUI_compatibility = True
        self.COMFYUI_compatibility = True

    def get_title(self) -> str:
        """모듈 제목 (좌측 패널에 표시됨)"""
        return "👋 Hello World"

    def get_order(self) -> int:
        """UI 순서 (낮을수록 위에 표시)"""
        return 10

    def create_widget(self, parent) -> QWidget:
        """UI 위젯 생성"""
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)

        label = QLabel("Hello, NAIA 2.0!")
        button = QPushButton("클릭해보세요")
        button.clicked.connect(self._on_button_click)

        layout.addWidget(label)
        layout.addWidget(button)

        # 위젯 참조 저장 (가시성 제어에 필요)
        self.widget = widget
        return widget

    def _on_button_click(self):
        """버튼 클릭 이벤트"""
        print("버튼이 클릭되었습니다!")

        # AppContext를 통한 이벤트 발행 예시
        if hasattr(self, 'app_context') and self.app_context:
            self.app_context.publish("hello_world_clicked", {"message": "Hello!"})
```

#### 4단계: 애플리케이션 실행 (1분)

```bash
python NAIA_cold_v4.py
```

좌측 패널에서 "👋 Hello World" 모듈을 확인할 수 있습니다!

#### 5단계: 다음 단계 학습 (30분)

1. **이벤트 구독 학습**: 다른 모듈의 이벤트를 받아보기
2. **파이프라인 훅 추가**: 프롬프트 생성 과정에 개입하기
3. **모드 인식 모듈 작성**: 백엔드별로 다른 설정 저장/로드
4. **첫 번째 탭 작성**: 우측 패널에 새 탭 추가

👉 상세한 내용은 [디렉터리별 가이드](#디렉터리별-가이드)를 참고하세요.

---

## 핵심 아키텍처 개념

### 1. AppContext: 중앙 상태 관리자

`core/context.py:20-100`

**역할**:
- 공유 서비스 등록 및 접근 (API, 데이터 매니저, 토큰 등)
- 이벤트 버스 (발행/구독)
- 파이프라인 훅 레지스트리
- API 모드 관리 (NAI/WEBUI/COMFYUI)

**주요 메서드**:
```python
# 이벤트 구독
app_context.subscribe("event_name", callback_function)

# 이벤트 발행
app_context.publish("event_name", {"data": "value"})

# API 모드 변경
app_context.set_api_mode("NAI")  # or "WEBUI", "COMFYUI"

# 파이프라인 훅 등록
app_context.register_pipeline_hook(pipeline_name, hook_point, module, priority)
```

**중요 이벤트**:
- `api_mode_changed`: API 모드 변경 시
- `prompt_generated`: 프롬프트 생성 완료 시
- `save_directory_changed`: 저장 경로 변경 시

### 2. 모듈 시스템: 플러그인 아키텍처

#### Left Panel (Middle Section)

- **위치**: `modules/*_module.py`
- **계약**: `BaseMiddleModule` (interfaces/base_module.py)
- **로딩**: 자동 검색 및 로드 by `MiddleSectionController`

**필수 구현**:
```python
class MyModule(BaseMiddleModule):
    def get_title(self) -> str:
        """모듈 제목"""

    def create_widget(self, parent) -> QWidget:
        """UI 위젯 생성"""
```

**선택적 구현**:
```python
def get_order(self) -> int:
    """UI 순서 (기본값: 100)"""

def get_parameters(self) -> dict:
    """생성 파라미터 반환"""

def get_pipeline_hook_info(self) -> dict:
    """파이프라인 훅 정보"""

def execute_pipeline_hook(self, context) -> PromptContext:
    """파이프라인 훅 실행"""
```

#### Right Panel (Tabs)

- **위치**: `tabs/*_tab.py`
- **계약**: `BaseTabModule` (interfaces/base_tab_module.py)
- **로딩**: 자동 검색 및 로드 by `TabController`

**필수 구현**:
```python
class MyTab(BaseTabModule):
    def get_tab_title(self) -> str:
        """탭 제목"""

    def create_widget(self, parent) -> QWidget:
        """UI 위젯 생성"""
```

**공통 시그널**:
```python
# 탭에서 사용 가능한 PyQt 시그널
self.parameters_extracted.emit(params_dict)
self.instant_generation_requested.emit()
self.tab_status_changed.emit("status_message")
```

### 3. 프롬프트 파이프라인: 훅 시스템

`core/prompt_processor.py:1-144`

프롬프트 생성은 여러 단계를 거치며, 각 단계마다 모듈이 개입할 수 있습니다.

**실행 순서**:
```
1. pre_processing       (프롬프트 전처리)
     ↓
2. 해상도 자동 맞춤      (내부 처리)
     ↓
3. post_processing      (프롬프트 후처리)
     ↓
4. 와일드카드 확장       (내부 처리)
     ↓
5. after_wildcard       (와일드카드 확장 후)
     ↓
6. final_hookpoint      (최종 훅)
     ↓
7. 최종 포맷팅          (내부 처리)
```

**훅 등록 예시**:
```python
def get_pipeline_hook_info(self) -> dict:
    return {
        'target_pipeline': 'PromptProcessor',
        'hook_point': 'post_processing',  # 어느 단계에 개입할지
        'priority': 10  # 낮을수록 먼저 실행
    }

def execute_pipeline_hook(self, context: PromptContext) -> PromptContext:
    # context 수정
    context.main_tags.append("my_custom_tag")

    # 반드시 context 반환
    return context
```

**PromptContext 주요 속성**:
```python
context.source_row          # 원본 데이터 (pandas Series)
context.settings            # 생성 설정
context.prefix_tags         # 프리픽스 태그 (리스트)
context.main_tags           # 메인 태그 (리스트)
context.postfix_tags        # 포스트픽스 태그 (리스트)
context.global_append_tags  # 전역 추가 태그
context.metadata            # 메타데이터 딕셔너리
context.final_prompt        # 최종 프롬프트 (str)
```

### 4. 모드 인식 시스템: 백엔드별 설정 관리

`interfaces/mode_aware_module.py:1-134`

백엔드(NAI/WEBUI/COMFYUI)별로 다른 설정을 저장/로드해야 하는 모듈은 `ModeAwareModule`을 다중 상속합니다.

**구현 예시**:
```python
from interfaces.base_module import BaseMiddleModule
from interfaces.mode_aware_module import ModeAwareModule

class MyModeAwareModule(BaseMiddleModule, ModeAwareModule):
    def __init__(self):
        BaseMiddleModule.__init__(self)
        ModeAwareModule.__init__(self)

        # 설정 파일 베이스 이름
        self.settings_base_filename = "my_module_settings"

        # 호환성 플래그 (이 모듈은 NAI와 WEBUI만 지원)
        self.NAI_compatibility = True
        self.WEBUI_compatibility = True
        self.COMFYUI_compatibility = False

    def collect_current_settings(self) -> dict:
        """현재 UI 상태를 딕셔너리로 수집"""
        return {
            "checkbox_state": self.my_checkbox.isChecked(),
            "text_value": self.my_input.text()
        }

    def apply_settings(self, settings: dict):
        """저장된 설정을 UI에 적용"""
        if "checkbox_state" in settings:
            self.my_checkbox.setChecked(settings["checkbox_state"])
        if "text_value" in settings:
            self.my_input.setText(settings["text_value"])

    def get_module_name(self) -> str:
        """모듈 이름 (로깅용)"""
        return self.get_title()
```

**자동 동작**:
- 모드 변경 시 자동으로 이전 모드 설정 저장
- 새 모드 설정 자동 로드
- 호환되지 않는 모드에서 자동 숨김

**설정 파일 위치**: `save/<settings_base_filename>_<MODE>.json`

예: `save/my_module_settings_NAI.json`, `save/my_module_settings_WEBUI.json`

---

## 개발 워크플로우

### 새 기능 추가 표준 프로세스

#### 1단계: 계획 및 설계 (Before Coding)

```
[ ] 어느 영역에 속하는가? (모듈/탭/컨트롤러/UI)
[ ] 다른 컴포넌트와의 의존성은? (이벤트/훅/서비스)
[ ] 어떤 모드에서 동작하는가? (NAI/WEBUI/COMFYUI/전체)
[ ] UI 스레드를 블로킹하는가? (→ QThread 필요)
```

#### 2단계: 파일 생성 및 기본 구조

```python
# modules/my_feature_module.py
from interfaces.base_module import BaseMiddleModule
from ui.theme import get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

class MyFeatureModule(BaseMiddleModule):
    def __init__(self):
        super().__init__()
        # 호환성 플래그 설정
        self.NAI_compatibility = True
        self.WEBUI_compatibility = True
        self.COMFYUI_compatibility = True

    def get_title(self) -> str:
        return "🆕 My Feature"

    def get_order(self) -> int:
        return 50  # 순서 조정

    def create_widget(self, parent):
        # TODO: UI 구현
        pass
```

#### 3단계: 이벤트/훅 연결

**이벤트 구독 (다른 컴포넌트의 알림 받기)**:
```python
def initialize_with_context(self, app_context):
    """AppContext 주입 시 호출됨"""
    self.app_context = app_context

    # 이벤트 구독
    app_context.subscribe("api_mode_changed", self._on_mode_changed)
    app_context.subscribe("prompt_generated", self._on_prompt_generated)

def _on_mode_changed(self, data: dict):
    old_mode = data["old_mode"]
    new_mode = data["new_mode"]
    print(f"모드 변경: {old_mode} → {new_mode}")

def _on_prompt_generated(self, context):
    print(f"생성된 프롬프트: {context.final_prompt}")
```

**파이프라인 훅 (프롬프트 생성 과정에 개입)**:
```python
def get_pipeline_hook_info(self) -> dict:
    return {
        'target_pipeline': 'PromptProcessor',
        'hook_point': 'post_processing',
        'priority': 20
    }

def execute_pipeline_hook(self, context):
    # 프롬프트 수정
    context.main_tags.append("my_tag")
    return context
```

#### 4단계: UI 구현 (스케일링 적용)

**반드시 지켜야 할 규칙**:
```python
from ui.theme import get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

def create_widget(self, parent):
    widget = QWidget(parent)
    layout = QVBoxLayout(widget)

    # ✅ 올바른 방법: 동적 스타일 사용
    dynamic_styles = get_dynamic_styles()

    label = QLabel("My Label")
    label.setStyleSheet(dynamic_styles['label_style'])

    button = QPushButton("Click Me")
    button.setStyleSheet(dynamic_styles['primary_button'])

    # ❌ 잘못된 방법: 하드코딩
    # button.setStyleSheet("font-size: 16px; padding: 8px;")

    # ✅ 커스텀 스타일이 필요한 경우
    custom_widget.setStyleSheet(f"""
        QWidget {{
            font-size: {get_scaled_font_size(18)}px;
            padding: {get_scaled_size(10)}px;
        }}
    """)

    layout.addWidget(label)
    layout.addWidget(button)

    self.widget = widget  # 가시성 제어를 위해 저장
    return widget
```

#### 5단계: 테스트

**로컬 테스트 체크리스트**:
```
[ ] 모듈/탭이 올바르게 로드되는가?
[ ] UI가 모든 스케일에서 정상 표시되는가? (Settings → UI 설정에서 확인)
[ ] 모드 전환 시 가시성/설정이 올바르게 동작하는가?
[ ] 이벤트/훅이 예상대로 동작하는가?
[ ] 메모리 누수가 없는가? (스레드 정리 확인)
```

#### 6단계: 정리 및 문서화

```python
def cleanup(self):
    """모듈 종료 시 리소스 정리"""
    # 타이머 정지
    if hasattr(self, 'timer'):
        self.timer.stop()

    # 스레드 종료
    if hasattr(self, 'worker_thread'):
        self.worker_thread.quit()
        self.worker_thread.wait()
```

---

## 디렉터리별 가이드

각 디렉터리의 `CLAUDE.md`에 상세한 가이드가 있습니다. 작업 전 반드시 해당 문서를 읽으세요.

### 📁 core/ - 핵심 시스템

**파일**: [core/CLAUDE.md](core/CLAUDE.md)

**주요 컴포넌트**:
- `context.py` - AppContext (중앙 상태 관리)
- `*_controller.py` - 각종 컨트롤러
- `prompt_processor.py` - 프롬프트 파이프라인
- `api_service.py` - API 브릿지
- `generation_controller.py` - 이미지 생성 컨트롤러

**언제 수정하는가?**:
- 새로운 컨트롤러 추가
- 파이프라인 단계 수정
- API 통신 로직 변경
- 핵심 서비스 추가

### 📁 modules/ - 좌측 패널 모듈

**파일**: [modules/CLAUDE.md](modules/CLAUDE.md)

**모듈 예시**:
- `character_module.py` - 캐릭터 설정
- `automation_module.py` - 자동 생성
- `instant_wildcard_module.py` - 즉석 와일드카드

**언제 추가하는가?**:
- 새로운 생성 옵션 추가
- 프롬프트 전/후처리 기능
- 사용자 설정 UI

### 📁 tabs/ - 우측 패널 탭

**파일**: [tabs/CLAUDE.md](tabs/CLAUDE.md)

**탭 예시**:
- `image_window.py` - 이미지 뷰어 (core)
- `png_info_tab.py` - 메타데이터 뷰어
- `assets_tab.py` - 에셋 관리
- 🆕 `studio_tab.py` - 다중 프레임 생성 (상세: [tabs/studio/CLAUDE.md](tabs/studio/CLAUDE.md))

**언제 추가하는가?**:
- 새로운 뷰/패널 필요
- 독립적인 기능 페이지
- 이미지/데이터 표시 화면

### 📁 ui/ - UI 컴포넌트 및 테마

**파일**: [ui/CLAUDE.md](ui/CLAUDE.md)

**주요 파일**:
- `theme.py` - 다크 테마 및 스타일
- `scaling_manager.py` - 동적 스케일링
- `right_view.py` - 탭 컨테이너
- `modern_menu.py` - 컨텍스트 메뉴

**언제 수정하는가?**:
- 새 UI 컴포넌트 추가
- 테마 색상/스타일 변경
- 스케일링 로직 수정

### 📁 interfaces/ - 계약 정의

**파일**: [interfaces/CLAUDE.md](interfaces/CLAUDE.md)

**주요 파일**:
- `base_module.py` - 모듈 인터페이스
- `base_tab_module.py` - 탭 인터페이스
- `mode_aware_module.py` - 모드 인식 인터페이스

**언제 수정하는가?**:
- 계약 변경 (신중히!)
- 새 공통 메서드 추가
- 시그널 추가

⚠️ **주의**: 계약 변경은 모든 모듈/탭에 영향을 미칩니다. PR 시 영향 범위를 명시하세요.

### 📁 utils/ - 유틸리티

**파일**: [utils/CLAUDE.md](utils/CLAUDE.md)

**주요 파일**:
- `token_calculator.py` - 토큰 카운팅
- `image_info.py` - 이미지 메타데이터 추출

**언제 추가하는가?**:
- 공통 헬퍼 함수
- 독립적인 유틸리티
- 데이터 변환 로직

### 📁 data/ - 데이터 파일

**파일**: [data/CLAUDE.md](data/CLAUDE.md)

**주요 파일**:
- `tags/*.parquet` - 분할된 태그 데이터베이스 (130개 파일, ~100MB+)
- `characteristic_list.txt` - 특징 태그 사전 (1006개)
- `clothes_list.txt` - 의류 태그 사전 (3700개)

**주요 컴포넌트**:
- `FilterDataManager` - 텍스트 사전 로딩 (core/filter_data_manager.py)
- `SearchController` - 멀티프로세싱 검색 (core/search_controller.py)

**언제 수정하는가?**:
- 태그 데이터베이스 업데이트
- 필터 사전 항목 추가/수정
- 새 데이터 소스 추가

⚠️ **주의**: 데이터 파일 구조 변경 시 소비자 코드(FilterDataManager, SearchController) 영향 확인 필수

---

## 중요 시스템 가이드

### QThread 메모리 누수 방지 ⚠️

**문제**: HTTP 요청 후 "Dummy" 스레드가 누적되어 성능 저하

**해결**: 반드시 다음 패턴 사용 (`core/api_service.py:90-131`)

```python
def my_api_call(self):
    try:
        with requests.Session() as session:
            response = session.post(url, ...)
            session.close()

            # 어댑터 정리
            if hasattr(session, 'adapters'):
                for adapter in session.adapters.values():
                    if hasattr(adapter, 'poolmanager') and adapter.poolmanager:
                        adapter.poolmanager.clear()

        # ⚠️ 필수: HTTP 스레드 정리
        self._cleanup_http_threads()

        return result
    except Exception as e:
        print(f"API 호출 실패: {e}")
```

**QThread 워커 패턴**:
```python
# 워커 클래스
class MyWorker(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def run(self):
        try:
            result = self.do_work()
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))

# 컨트롤러에서 사용
self.thread = QThread()
self.worker = MyWorker()
self.worker.moveToThread(self.thread)

# ⚠️ 중요: deleteLater 연결
self.thread.finished.connect(self.worker.deleteLater)
self.thread.finished.connect(self.thread.deleteLater)

# 시그널 연결
self.worker.finished.connect(self._on_finished)
self.thread.started.connect(self.worker.run)

# 시작
self.thread.start()
```

### 동적 UI 스케일링 시스템

**개요**: FHD/QHD/4K 등 다양한 해상도 지원

**필수 규칙**:
```python
from ui.theme import get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

# ❌ 절대 하지 마세요
widget.setStyleSheet("font-size: 16px; padding: 8px;")

# ✅ 올바른 방법
dynamic_styles = get_dynamic_styles()
widget.setStyleSheet(dynamic_styles['primary_button'])

# ✅ 커스텀 스타일
widget.setStyleSheet(f"""
    QWidget {{
        font-size: {get_scaled_font_size(16)}px;
        padding: {get_scaled_size(8)}px;
    }}
""")
```

**가용 스타일 키**:
```python
dynamic_styles = get_dynamic_styles()

# 버튼
dynamic_styles['primary_button']
dynamic_styles['secondary_button']
dynamic_styles['compact_button']

# 입력
dynamic_styles['compact_textedit']
dynamic_styles['compact_lineedit']
dynamic_styles['compact_combobox']

# 기타
dynamic_styles['label_style']
dynamic_styles['dark_checkbox']
dynamic_styles['dark_tabs']
dynamic_styles['collapsible_box']
```

**스케일링 테스트**: Settings → 🎨 UI 설정 → UI 크기 설정

### 토큰 카운팅 시스템

**위치**: `utils/token_calculator.py`

**기능**:
- tiktoken 기반 CLIP 토큰 근사 계산
- 모드별 가중치 구문 처리 (NAI `::`, WebUI `()`)
- 실시간 토큰 카운트 표시

**사용 예시**:
```python
from utils.token_calculator import get_token_calculator

calculator = get_token_calculator()

# NAI 모드
nai_prompt = "1girl, 1.2::masterpiece::, artist:crab_d"
nai_tokens = calculator.count_tokens(nai_prompt, current_mode="NAI")

# WEBUI 모드
webui_prompt = "1girl, (masterpiece:1.2), artist:crab_d"
webui_tokens = calculator.count_tokens(webui_prompt, current_mode="WEBUI")

print(f"NAI: {nai_tokens} tokens, WEBUI: {webui_tokens} tokens")
```

### 프롬프트 태그 자동 완성

**위치**: `core/autocomplete_manager.py`, `ui/modern_menu.py`

**기능**:
- KR_tags.parquet 기반 태그 제안
- 한글/영문 검색 지원
- 카테고리별 필터링

**TextEdit에 적용**:
```python
from ui.modern_menu import setModernStyle

# 자동으로 컨텍스트 메뉴 + 자동완성 적용
my_textedit = QTextEdit()
setModernStyle(my_textedit)
```

### Instant Wildcard 시스템

**위치**: `modules/instant_wildcard_module.py`

**기능**:
- 텍스트 선택 → 우클릭 → 와일드카드 추가
- JSON 기반 저장 (`save/instant_wildcard/`)
- `__key__` 구문으로 프롬프트에서 사용

**모듈에서 사용**:
```python
from ui.modern_menu import setModernStyle

# TextEdit에 자동으로 와일드카드 메뉴 추가됨
self.prompt_edit = QTextEdit()
setModernStyle(self.prompt_edit)
```

### 이미지 메타데이터 시스템

**위치**: `utils/image_info.py`, `ui/metadata_viewer.py`

**지원 포맷**:
- PNG (tEXt, parameters)
- JPEG/WEBP (EXIF UserComment)
- GIF (Comment)
- Stealth PNG

**사용 예시**:
```python
from utils.image_info import extract_all_metadata_from_image

metadata = extract_all_metadata_from_image(image_path)

if metadata:
    print(f"Prompt: {metadata.get('prompt', 'N/A')}")
    print(f"Steps: {metadata.get('steps', 'N/A')}")
    print(f"Sampler: {metadata.get('sampler', 'N/A')}")
```

---

## 문제 해결 및 디버깅

### 자주 발생하는 문제

#### Q1: 모듈이 로드되지 않아요

**체크리스트**:
```
[ ] 파일명이 *_module.py 패턴인가?
[ ] BaseMiddleModule을 상속했는가?
[ ] get_title()과 create_widget()을 구현했는가?
[ ] 파이썬 문법 오류가 없는가? (콘솔 확인)
```

**디버깅**:
```python
# core/middle_section_controller.py에 임시 출력 추가
print(f"[DEBUG] 로드된 모듈: {module_class.__name__}")
```

#### Q2: 이벤트가 전달되지 않아요

**체크리스트**:
```
[ ] initialize_with_context()에서 구독했는가?
[ ] 이벤트 이름이 정확한가? (대소문자 구분)
[ ] 발행자가 올바른 이벤트명을 사용하는가?
[ ] 콜백 함수 시그니처가 맞는가?
```

**디버깅**:
```python
# 이벤트 발행 시
print(f"[EVENT] 발행: {event_name}, 데이터: {data}")

# 이벤트 구독 시
def _on_event(self, data):
    print(f"[EVENT] 수신: {data}")
```

#### Q3: 파이프라인 훅이 실행되지 않아요

**체크리스트**:
```
[ ] get_pipeline_hook_info()를 구현했는가?
[ ] target_pipeline이 'PromptProcessor'인가?
[ ] hook_point가 올바른가? (pre_processing, post_processing 등)
[ ] execute_pipeline_hook()가 context를 반환하는가?
```

**디버깅**:
```python
def execute_pipeline_hook(self, context):
    print(f"[HOOK] {self.get_title()} 실행됨")
    # ... 로직 ...
    return context
```

#### Q4: UI가 멈춰요 (블로킹)

**원인**: UI 스레드에서 무거운 작업 수행

**해결**: QThread로 분리
```python
# ❌ 잘못된 방법
def on_button_click(self):
    result = requests.get(url)  # UI 블로킹!
    self.label.setText(result.text)

# ✅ 올바른 방법
def on_button_click(self):
    self.thread = QThread()
    self.worker = NetworkWorker(url)
    self.worker.moveToThread(self.thread)

    self.worker.finished.connect(self._on_result)
    self.thread.started.connect(self.worker.run)
    self.thread.finished.connect(self.worker.deleteLater)
    self.thread.finished.connect(self.thread.deleteLater)

    self.thread.start()

def _on_result(self, result):
    self.label.setText(result)
```

#### Q5: 모드 전환 시 설정이 사라져요

**원인**: ModeAwareModule을 상속하지 않음

**해결**:
```python
from interfaces.mode_aware_module import ModeAwareModule

class MyModule(BaseMiddleModule, ModeAwareModule):
    def __init__(self):
        BaseMiddleModule.__init__(self)
        ModeAwareModule.__init__(self)

        self.settings_base_filename = "my_module"

    def collect_current_settings(self) -> dict:
        return {"key": "value"}

    def apply_settings(self, settings: dict):
        # 설정 적용
        pass
```

### 유용한 디버깅 도구

#### 콘솔 출력
```python
# 간단한 로깅
print(f"[DEBUG] 값: {value}")

# 상세 로깅
import traceback
try:
    # 코드
except Exception as e:
    print(f"[ERROR] {e}")
    traceback.print_exc()
```

#### PyQt Inspector
```python
# 위젯 트리 출력
def print_widget_tree(widget, indent=0):
    print("  " * indent + widget.__class__.__name__)
    for child in widget.children():
        if isinstance(child, QWidget):
            print_widget_tree(child, indent + 1)
```

#### 이벤트 모니터
```python
# AppContext에 모든 이벤트 로깅
original_publish = app_context.publish

def debug_publish(event_name, *args, **kwargs):
    print(f"[EVENT] {event_name}: {args}, {kwargs}")
    return original_publish(event_name, *args, **kwargs)

app_context.publish = debug_publish
```

---

## 추가 참고 자료

### 관련 문서

- **AGENTS.md**: AI 협업을 위한 상세 기술 레퍼런스
- **각 디렉터리의 CLAUDE.md**: 영역별 상세 가이드
- **modules/module_development_guide.md**: 모듈 개발 상세 가이드 (영문)

### 예제 모듈/탭

**학습용 추천 코드**:

| 파일 | 학습 포인트 |
|------|------------|
| `modules/character_module.py` | 모드 인식, 이벤트 발행, **🆕 캐릭터 위치 시스템 (5x5 그리드, 동적 좌표, 시각화)** |
| `modules/instant_wildcard_module.py` | 파일 저장/로드, UI 통합 |
| `modules/automation_module.py` | QThread 사용, 자동화 로직 |
| `tabs/png_info_tab.py` | 탭 구조, 메타데이터 처리 |
| `tabs/assets_tab.py` | 복잡한 탭, 서브 모듈 |
| 🆕 `tabs/studio_tab.py` | 다중 프레임 그리드, 순차 생성, 프리셋 시스템 |

### 코딩 스타일 가이드

**Python 스타일**:
- PEP 8 준수 (단, 라인 길이는 120자까지 허용)
- 타입 힌트 권장 (`def func(arg: str) -> int:`)
- 1글자 변수명 지양 (`i`, `j` 제외)
- 명확한 함수/변수 이름

**Qt 스타일**:
- 시그널/슬롯 연결 시 람다 대신 메서드 사용 권장
- UI와 로직 분리
- 메모리 누수 주의 (deleteLater 사용)

**주석**:
- 한글 주석 허용
- 복잡한 로직은 Why 설명
- TODO/FIXME 명확히 표시

---

## 기여 및 PR 가이드

### PR 체크리스트

제출 전 확인:

```
[ ] 모든 모드(NAI/WEBUI/COMFYUI)에서 테스트했는가?
[ ] UI 스케일링이 올바르게 적용되었는가?
[ ] 모드 전환 시 설정이 유지되는가?
[ ] 메모리 누수가 없는가? (스레드 정리 확인)
[ ] 새 파일이 네이밍 규칙을 따르는가?
[ ] 이벤트/훅이 올바르게 동작하는가?
[ ] 에러 처리가 적절한가?
```

### PR 설명 템플릿

```markdown
## 변경 내용

- [ ] 새 모듈/탭 추가
- [ ] 기존 기능 개선
- [ ] 버그 수정
- [ ] 리팩토링
- [ ] 문서 업데이트

## 상세 설명

(무엇을 왜 변경했는지)

## 영향 범위

- [ ] core/ - 컨트롤러/파이프라인
- [ ] modules/ - 좌측 모듈
- [ ] tabs/ - 우측 탭
- [ ] ui/ - UI 컴포넌트
- [ ] interfaces/ - 계약 변경 (주의!)

## 테스트 방법

1. ...
2. ...

## 스크린샷/캡처

(UI 변경 시 첨부)

## 파이프라인 훅 변경 사항

(해당 시 우선순위/단계 설명)
```

---

## 마치며

이 문서는 NAIA 2.0 개발의 시작점입니다.

**다음 단계**:
1. 관심 있는 디렉터리의 `CLAUDE.md` 읽기
2. 예제 모듈/탭 코드 분석
3. 간단한 Hello World 모듈 작성
4. 실제 기능 개발 시작

**막힐 때**:
- 콘솔 출력 확인 (대부분의 에러가 표시됨)
- 유사한 기존 모듈/탭 참고
- 디렉터리별 CLAUDE.md 재확인
- AGENTS.md에서 상세 계약 확인

**Happy Coding! 🎨**

---

*문서 버전: 2025-01-09*
*최종 검토: Studio Tab 문서화 추가*
