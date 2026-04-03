# CLAUDE.md — interfaces/

> **목적**: NAIA 2.0 모듈/탭 계약(ABC) 정의. 호환성 파괴 변경을 피하고, 상호 의존성을 최소화하세요.

---

## 아키텍처

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

interfaces는 `ui/`에 의존하지 않음.

---

## BaseMiddleModule 계약

**파일**: `interfaces/base_module.py`

### 필수 메서드

```python
@abstractmethod
def get_title(self) -> str: ...      # 모듈 제목 (이모지 가능)

@abstractmethod
def create_widget(self, parent) -> QWidget: ...  # UI 위젯 생성
# 반드시 self.widget = widget 저장 (가시성 제어용)
```

### 선택적 메서드

```python
def get_order(self) -> int: return 100           # UI 순서 (낮을수록 위)
def on_initialize(self): pass                     # AppContext 주입 후 초기화
def get_parameters(self) -> dict: return {}       # 생성 API 추가 파라미터
def execute_pipeline_hook(self, context): return context  # 파이프라인 훅
def get_pipeline_hook_info(self) -> dict: return {}       # 훅 등록 정보
def is_compatible_with_mode(self, mode: str) -> bool: ... # 모드 호환성 (기본 구현 제공)
```

### 속성

```python
def __init__(self):
    self.NAI_compatibility = True
    self.WEBUI_compatibility = True
    self.COMFYUI_compatibility = True
    self.app_context = None        # 자동 주입
    self.ignore_save_load = False  # True면 저장/로드 무시
```

### 파이프라인 훅

```python
def get_pipeline_hook_info(self) -> dict:
    return {
        'target_pipeline': 'PromptProcessor',
        'hook_point': 'post_processing',  # pre_processing | post_processing | after_wildcard | final_hookpoint
        'priority': 10  # 낮을수록 먼저 실행
    }

def execute_pipeline_hook(self, context):
    context.prefix_tags = ["masterpiece"] + context.prefix_tags
    return context  # 반드시 context 반환
```

---

## BaseTabModule 계약

**파일**: `interfaces/base_tab_module.py`

### 메타클래스

```python
class pyqtABCMeta(type(QObject), ABCMeta): pass  # QObject + ABC 결합
class BaseTabModule(QObject, ABC, metaclass=pyqtABCMeta): ...
```

QObject + ABC 직접 상속하면 메타클래스 충돌 발생. 반드시 `BaseTabModule` 사용.

### 공통 시그널

```python
parameters_extracted = pyqtSignal(dict)
instant_generation_requested = pyqtSignal(dict)
tab_status_changed = pyqtSignal(str, str)  # tab_id, status_message
```

### 필수 메서드

```python
@abstractmethod
def get_tab_title(self) -> str: ...

@abstractmethod
def create_widget(self, parent: QWidget) -> QWidget: ...
```

### 선택적 메서드

```python
def get_tab_order(self) -> int: return 999         # 낮을수록 왼쪽
def get_tab_type(self) -> str: return 'core'       # 'core' | 'closable' | 'permanent'
def can_close_tab(self) -> bool: ...               # closable이면 True
def on_tab_activated(self): pass
def on_tab_deactivated(self): pass
def on_tab_closing(self) -> bool: return True      # False면 닫기 취소
def cleanup(self): pass                             # 리소스 정리
def save_settings(self): pass
def load_settings(self): pass
def on_initialize(self): pass
```

### 속성

```python
def __init__(self):
    super().__init__()
    self.app_context = None
    self.tab_id = self.__class__.__name__

def initialize_with_context(self, app_context):
    self.app_context = app_context
```

---

## ModeAwareModule 믹스인

**파일**: `interfaces/mode_aware_module.py`

### 자동 제공 기능

1. 모드 전환 시 이전 모드 설정 자동 저장
2. 새 모드 설정 자동 로드
3. 호환되지 않는 모드에서 자동 숨김
4. 설정 파일 경로 자동 생성: `save/<base>_<MODE>.json`

### 필수 속성/메서드

```python
class MyModule(BaseMiddleModule, ModeAwareModule):
    def __init__(self):
        BaseMiddleModule.__init__(self)
        ModeAwareModule.__init__(self)
        self.settings_base_filename = "my_module"  # 필수

    def collect_current_settings(self) -> dict:  # 현재 UI 상태 수집
        return {"checkbox": self.checkbox.isChecked()}

    def apply_settings(self, settings: dict):    # 저장된 설정 UI 적용
        if "checkbox" in settings:
            self.checkbox.setChecked(settings["checkbox"])

    def get_module_name(self) -> str:            # 로깅용
        return self.get_title()
```

### 자동 제공 메서드

- `save_mode_settings(mode=None)` - 현재/지정 모드 설정 저장
- `load_mode_settings(mode=None)` - 현재/지정 모드 설정 로드
- `is_compatible_with_mode(mode)` - 호환성 확인
- `update_visibility_for_mode(mode)` - 가시성 업데이트
- `on_mode_changed(old_mode, new_mode)` - 모드 변경 시 자동 저장/로드/가시성

### 설정 파일

경로: `save/my_module_NAI.json`

```json
{"NAI": {"checkbox": true, "slider": 75}}
```

---

## 다중 상속 패턴

### BaseMiddleModule + ModeAwareModule

```python
class MyModule(BaseMiddleModule, ModeAwareModule):
    def __init__(self):
        BaseMiddleModule.__init__(self)   # 순서 중요: 양쪽 모두 호출
        ModeAwareModule.__init__(self)
        self.settings_base_filename = "my_module"
```

### BaseTabModule + ModeAwareModule

```python
class MyTab(BaseTabModule, ModeAwareModule):
    def __init__(self):
        BaseTabModule.__init__(self)
        ModeAwareModule.__init__(self)
        self.settings_base_filename = "my_tab"
```

### MRO 충돌 주의

`BaseMiddleModule`과 `ModeAwareModule` 모두 `is_compatible_with_mode()` 정의. MRO 순서상 `BaseMiddleModule`이 우선. ModeAwareModule의 메서드가 필요하면 명시적 호출:

```python
ModeAwareModule.on_mode_changed(self, old_mode, new_mode)
```

---

## 계약 수정 가이드라인

### 안전한 수정

- 선택적 메서드 추가 (기본 구현 제공)
- 속성 추가 (`__init__`에 기본값)
- 문서화 개선

### 위험한 수정 (Breaking Change)

- 필수 메서드 추가 -> 대안: 선택적 메서드로 추가 후 점진적 마이그레이션
- 메서드 시그니처 변경 -> 대안: 새 메서드 추가 (`_v2`)
- 기본값 없는 필수 속성 추가

---

## 주의사항 및 함정

### ModeAwareModule AttributeError

`settings_base_filename` 미설정 시 발생. `__init__`에서 반드시 설정.

### pyqtABCMeta 메타클래스 충돌

`QObject + ABC` 직접 상속 금지. `BaseTabModule`을 통해서만 사용.

### 설정 저장/로드 안 될 때

`collect_current_settings()`가 빈 딕셔너리 반환하거나, `apply_settings()`에서 키 존재 확인 누락.

### execute_pipeline_hook 주의

- 반드시 context 반환
- 오류 시 원본 context 반환
- 부작용 최소화

---

## 관련 문서

- [modules/CLAUDE.md](../modules/CLAUDE.md) - BaseMiddleModule 구현 가이드
- [tabs/CLAUDE.md](../tabs/CLAUDE.md) - BaseTabModule 구현 가이드
- [core/CLAUDE.md](../core/CLAUDE.md) - AppContext, 컨트롤러

## 예제 코드 위치

| 예제 | 파일 |
|------|------|
| BaseMiddleModule + ModeAware | `modules/character_module.py` |
| BaseTabModule | `tabs/png_info_tab.py` |
| 파이프라인 훅 | `modules/conditional_prompt_module.py` |
| pyqtABCMeta | `interfaces/base_tab_module.py:9-10` |
