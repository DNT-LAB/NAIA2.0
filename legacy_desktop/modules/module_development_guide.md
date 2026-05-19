# NAIA 2.0 커스텀 모듈 개발 가이드

## 📋 목차

1. [개요](#개요)
2. [모듈 아키텍처](#모듈-아키텍처)
3. [BaseMiddleModule 기본 구현](#basemiddlemodule-기본-구현)
4. [ModeAwareModule 고급 구현](#modeawaremodule-고급-구현)
5. [설정 저장/로드 시스템](#설정-저장로드-시스템)
6. [파이프라인 훅 시스템](#파이프라인-훅-시스템)
7. [모듈 예시](#모듈-예시)
8. [모범 사례 및 주의사항](#모범-사례-및-주의사항)

---

## 개요

NAIA 2.0은 모듈화된 아키텍처를 통해 개발자가 독립적인 기능 모듈을 쉽게 추가할 수 있도록 설계되었습니다. 이 가이드는 `BaseMiddleModule`과 `ModeAwareModule` 인터페이스를 기반으로 한 커스텀 모듈 개발 방법을 설명합니다.

### 주요 특징
- **모듈 자동 검색**: `modules/` 디렉토리의 `*_module.py` 파일 자동 로드
- **모드별 설정 관리**: NAI/WEBUI 모드별 독립적인 설정 저장/로드
- **파이프라인 훅**: 프롬프트 생성 과정에 직접 개입 가능
- **가시성 제어**: 모드별 호환성에 따른 자동 UI 표시/숨김
- **이벤트 시스템**: 모듈 간 느슨한 결합을 위한 pub/sub 패턴

---

## 모듈 아키텍처

### 1. 모듈 계층 구조

```
BaseMiddleModule (추상 클래스)
├── 기본 UI 모듈 (설정 저장 불필요)
└── ModeAwareModule (추상 클래스)
    └── 고급 UI 모듈 (모드별 설정 저장/로드)
```

### 2. 파일 구조

```
modules/
├── simple_module.py          # 기본 모듈
├── advanced_module.py        # 모드 대응 모듈
└── feature_module.py         # 기능 모듈
```

### 3. 모듈 생명주기

1. **로드**: `MiddleSectionController`가 `*_module.py` 파일 검색
2. **인스턴스 생성**: 클래스 인스턴스화
3. **컨텍스트 주입**: `initialize_with_context()` 호출
4. **초기화**: `on_initialize()` 호출
5. **UI 생성**: `create_widget()` 호출
6. **등록**: `ModeAwareModule`인 경우 자동 등록

---

## BaseMiddleModule 기본 구현

### 필수 메서드

```python
from abc import ABC, abstractmethod
from PyQt6.QtWidgets import QWidget
from interfaces.base_module import BaseMiddleModule

class MySimpleModule(BaseMiddleModule):
    def __init__(self):
        super().__init__()
        
        # 🔧 호환성 설정
        self.NAI_compatibility = True      # NAI 모드 호환 여부
        self.WEBUI_compatibility = True    # WEBUI 모드 호환 여부
        
        # 🚫 설정 저장 무시 (선택사항)
        self.ignore_save_load = True       # True: 설정 저장/로드 안함
        
    @abstractmethod
    def get_title(self) -> str:
        """모듈 제목 반환"""
        return "🔧 내 간단한 모듈"
    
    @abstractmethod
    def create_widget(self, parent: QWidget) -> QWidget:
        """UI 위젯 생성"""
        widget = QWidget(parent)
        # UI 구성 로직
        return widget
    
    def get_order(self) -> int:
        """UI 표시 순서 (낮을수록 위에 표시)"""
        return 100
    
    def get_parameters(self) -> dict:
        """생성 파라미터 반환 (이미지 생성 시 사용)"""
        return {}
    
    def on_initialize(self):
        """모듈 초기화 시 호출"""
        pass
```

### 선택적 메서드

```python
def initialize_with_context(self, app_context):
    """AppContext 주입 시 호출"""
    self.app_context = app_context
    
    # 이벤트 구독 예시
    app_context.subscribe("prompt_generated", self.on_prompt_generated)

def on_prompt_generated(self, data: dict):
    """프롬프트 생성 완료 시 호출되는 이벤트 핸들러"""
    pass

def execute_pipeline_hook(self, context) -> 'PromptContext':
    """파이프라인 훅 실행 (고급 기능)"""
    return context

def get_pipeline_hook_info(self) -> dict:
    """파이프라인 훅 정보 반환"""
    return {
        'target_pipeline': 'PromptProcessor',
        'hook_point': 'post_processing',
        'priority': 10
    }
```

---

## ModeAwareModule 고급 구현

모드별 설정 저장/로드가 필요한 경우 `ModeAwareModule`을 추가로 상속받습니다.

```python
from interfaces.base_module import BaseMiddleModule
from interfaces.mode_aware_module import ModeAwareModule
from typing import Dict, Any

class MyAdvancedModule(BaseMiddleModule, ModeAwareModule):
    def __init__(self):
        BaseMiddleModule.__init__(self)
        ModeAwareModule.__init__(self)
        
        # 🔧 ModeAware 필수 설정
        self.settings_base_filename = "MyAdvancedModule"  # 파일명 접두사
        self.current_mode = "NAI"                         # 현재 모드
        
        # 🔧 호환성 설정
        self.NAI_compatibility = True
        self.WEBUI_compatibility = True
        
        # UI 위젯 참조 저장용
        self.my_textbox = None
        self.my_checkbox = None
    
    def get_title(self) -> str:
        return "🚀 내 고급 모듈"
    
    def get_module_name(self) -> str:
        """ModeAware 인터페이스 구현"""
        return self.get_title()
    
    def create_widget(self, parent: QWidget) -> QWidget:
        from PyQt6.QtWidgets import QVBoxLayout, QTextEdit, QCheckBox
        
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        
        # UI 구성
        self.my_textbox = QTextEdit()
        self.my_checkbox = QCheckBox("옵션 활성화")
        
        layout.addWidget(self.my_textbox)
        layout.addWidget(self.my_checkbox)
        
        # 🔧 위젯 참조 저장 (가시성 제어용)
        self.widget = widget
        
        return widget
    
    def collect_current_settings(self) -> Dict[str, Any]:
        """현재 UI 상태를 딕셔너리로 수집"""
        if not self.my_textbox or not self.my_checkbox:
            return {}
        
        return {
            "text_content": self.my_textbox.toPlainText(),
            "checkbox_state": self.my_checkbox.isChecked(),
            "custom_data": "어떤 값이든 가능"
        }
    
    def apply_settings(self, settings: Dict[str, Any]):
        """설정을 UI에 적용"""
        if not self.my_textbox or not self.my_checkbox:
            return
        
        self.my_textbox.setText(settings.get("text_content", ""))
        self.my_checkbox.setChecked(settings.get("checkbox_state", False))
    
    def on_initialize(self):
        """모듈 초기화"""
        # 기존 설정 마이그레이션 (필요시)
        self._migrate_legacy_settings()
        
        if hasattr(self, 'app_context') and self.app_context:
            current_mode = self.app_context.get_api_mode()
            if self.widget:
                self.update_visibility_for_mode(current_mode)
    
    def _migrate_legacy_settings(self):
        """기존 설정 파일을 새로운 모드별 시스템으로 마이그레이션"""
        # 구현 생략 (필요시 PromptEngineeringModule 참고)
        pass
```

---

## 설정 저장/로드 시스템

### 1. 설정 파일 구조

**기본 모듈**: 설정 저장 안함 (`ignore_save_load = True`)

**ModeAware 모듈**: 모드별 개별 파일
```
save/
├── MyAdvancedModule_NAI.json     # NAI 모드 설정
├── MyAdvancedModule_WEBUI.json   # WEBUI 모드 설정
└── MyAdvancedModule.json.backup  # 마이그레이션 백업
```

### 2. 설정 파일 내용

```json
{
  "NAI": {
    "text_content": "사용자 입력 텍스트",
    "checkbox_state": true,
    "custom_data": "모든 JSON 직렬화 가능한 데이터"
  }
}
```

### 3. 자동 저장/로드 시점

- **저장**: 앱 종료 시, 모드 변경 시
- **로드**: 앱 시작 시, 모드 변경 시

### 4. 수동 저장/로드

```python
# 현재 모드 설정 저장
self.save_mode_settings()

# 특정 모드 설정 저장
self.save_mode_settings("NAI")

# 특정 모드 설정 로드
self.load_mode_settings("WEBUI")
```

---

## 파이프라인 훅 시스템

프롬프트 생성 과정에 직접 개입하여 태그를 수정하거나 추가 처리를 수행할 수 있습니다.

### 훅 포인트

1. **`pre_processing`**: 와일드카드 확장 전
2. **`post_processing`**: 와일드카드 확장 후, 최종 포매팅 전

### 훅 구현 예시

```python
def get_pipeline_hook_info(self) -> dict:
    return {
        'target_pipeline': 'PromptProcessor',  # 대상 파이프라인
        'hook_point': 'post_processing',       # 훅 포인트
        'priority': 10                         # 우선순위 (낮을수록 먼저 실행)
    }

def execute_pipeline_hook(self, context) -> 'PromptContext':
    """파이프라인 훅 실행"""
    print(f"🔧 {self.get_title()} 훅 실행...")
    
    # 태그 수정 예시
    context.main_tags.append("custom_tag")
    context.prefix_tags.insert(0, "quality_boost")
    
    # 조건부 태그 제거
    if "unwanted_tag" in context.main_tags:
        context.main_tags.remove("unwanted_tag")
        context.removed_tags.append("unwanted_tag")
    
    return context
```

---

## 모듈 예시

### 1. 간단한 정보 표시 모듈

```python
# modules/info_display_module.py
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from interfaces.base_module import BaseMiddleModule

class InfoDisplayModule(BaseMiddleModule):
    def __init__(self):
        super().__init__()
        self.ignore_save_load = True  # 설정 저장 불필요
    
    def get_title(self) -> str:
        return "ℹ️ 정보 표시"
    
    def get_order(self) -> int:
        return 10  # 최상단에 표시
    
    def create_widget(self, parent: QWidget) -> QWidget:
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        
        info_label = QLabel("현재 버전: NAIA 2.0\n상태: 정상")
        layout.addWidget(info_label)
        
        return widget
```

### 2. 태그 필터링 모듈

```python
# modules/tag_filter_module.py
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QCheckBox
from interfaces.base_module import BaseMiddleModule
from interfaces.mode_aware_module import ModeAwareModule
from typing import Dict, Any

class TagFilterModule(BaseMiddleModule, ModeAwareModule):
    def __init__(self):
        BaseMiddleModule.__init__(self)
        ModeAwareModule.__init__(self)
        
        self.settings_base_filename = "TagFilterModule"
        self.current_mode = "NAI"
        
        # UI 위젯 참조
        self.filter_textbox = None
        self.enable_checkbox = None
    
    def get_title(self) -> str:
        return "🔍 태그 필터"
    
    def get_module_name(self) -> str:
        return self.get_title()
    
    def create_widget(self, parent: QWidget) -> QWidget:
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        
        self.enable_checkbox = QCheckBox("필터 활성화")
        self.filter_textbox = QTextEdit()
        self.filter_textbox.setPlaceholderText("제거할 태그들을 쉼표로 구분")
        
        layout.addWidget(self.enable_checkbox)
        layout.addWidget(self.filter_textbox)
        
        self.widget = widget
        return widget
    
    def collect_current_settings(self) -> Dict[str, Any]:
        if not self.filter_textbox or not self.enable_checkbox:
            return {}
        
        return {
            "filter_enabled": self.enable_checkbox.isChecked(),
            "filter_tags": self.filter_textbox.toPlainText()
        }
    
    def apply_settings(self, settings: Dict[str, Any]):
        if not self.filter_textbox or not self.enable_checkbox:
            return
        
        self.enable_checkbox.setChecked(settings.get("filter_enabled", False))
        self.filter_textbox.setText(settings.get("filter_tags", ""))
    
    def get_pipeline_hook_info(self) -> dict:
        return {
            'target_pipeline': 'PromptProcessor',
            'hook_point': 'post_processing',
            'priority': 5
        }
    
    def execute_pipeline_hook(self, context) -> 'PromptContext':
        if not self.enable_checkbox or not self.enable_checkbox.isChecked():
            return context
        
        filter_text = self.filter_textbox.toPlainText()
        filter_tags = [tag.strip() for tag in filter_text.split(',') if tag.strip()]
        
        for tag in filter_tags:
            if tag in context.main_tags:
                context.main_tags.remove(tag)
                context.removed_tags.append(tag)
        
        print(f"🔍 태그 필터: {len(filter_tags)}개 태그 제거됨")
        return context
```

---

## 모범 사례 및 주의사항

### ✅ 모범 사례

1. **명확한 모듈명**: 파일명과 클래스명을 명확하게 작성
   ```python
   # 파일: character_enhancement_module.py
   class CharacterEnhancementModule(BaseMiddleModule):
   ```

2. **적절한 순서 설정**: `get_order()`로 논리적 순서 배치
   ```python
   def get_order(self) -> int:
       return 50  # 0-100: 기본 모듈, 100-200: 고급 모듈
   ```

3. **호환성 플래그 명시**: 모드별 호환성 명확히 설정
   ```python
   self.NAI_compatibility = True    # NAI 전용 기능
   self.WEBUI_compatibility = False  # WEBUI 미지원
   ```

4. **에러 처리**: 모든 UI 조작에 방어 코드 추가
   ```python
   def collect_current_settings(self) -> Dict[str, Any]:
       if not self.my_widget:
           return {}
       
       try:
           return {"value": self.my_widget.text()}
       except Exception as e:
           print(f"❌ 설정 수집 실패: {e}")
           return {}
   ```

5. **리소스 정리**: 필요시 리소스 해제 구현
   ```python
   def cleanup(self):
       """모듈 정리 시 호출"""
       if hasattr(self, 'timer'):
           self.timer.stop()
   ```

### ⚠️ 주의사항

1. **순환 참조 방지**: AppContext 직접 저장 대신 필요시에만 접근
2. **UI 스레드 준수**: UI 업데이트는 메인 스레드에서만 수행
3. **설정 호환성**: 기존 설정 구조 변경 시 마이그레이션 로직 구현
4. **메모리 누수**: 이벤트 구독 해제 및 위젯 정리 필수
5. **예외 처리**: 모든 사용자 입력과 파일 I/O에 예외 처리

### 🚫 피해야 할 실수

```python
# ❌ 잘못된 예시
class BadModule(BaseMiddleModule):
    def __init__(self):
        # super().__init__() 누락
        pass
    
    def get_title(self):
        # 반환 타입 힌트 누락
        pass
    
    def create_widget(self, parent):
        # 위젯 생성 후 self.widget 저장 누락
        widget = QWidget(parent)
        return widget  # self.widget = widget 누락

# ✅ 올바른 예시
class GoodModule(BaseMiddleModule):
    def __init__(self):
        super().__init__()
    
    def get_title(self) -> str:
        return "✅ 올바른 모듈"
    
    def create_widget(self, parent: QWidget) -> QWidget:
        widget = QWidget(parent)
        self.widget = widget  # 가시성 제어를 위해 필요
        return widget
```

---

## 결론

NAIA 2.0의 모듈 시스템은 확장성과 유지보수성을 위해 설계되었습니다. 이 가이드를 참고하여 프로젝트의 아키텍처 철학에 맞는 모듈을 개발하시기 바랍니다.

### 추가 자료

- **BaseMiddleModule**: `interfaces/base_module.py`
- **ModeAwareModule**: `interfaces/mode_aware_module.py`  
- **참고 구현**: `modules/character_module.py`, `modules/prompt_engineering_module.py`
- **아키텍처 문서**: `README.md` 상단 섹션 참조

### 도움이 필요한 경우

1. 기존 모듈 코드 분석
2. `AppContext`의 이벤트 시스템 활용
3. 파이프라인 훅의 고급 활용법
4. 커스텀 UI 컴포넌트 개발

---

*이 문서는 NAIA 2.0 아키텍처를 기반으로 작성되었으며, 프로젝트 발전에 따라 업데이트될 수 있습니다.*