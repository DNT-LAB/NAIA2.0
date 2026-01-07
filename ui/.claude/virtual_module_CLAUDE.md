# 임시 생성 창 시스템 (Virtual Module 패턴) 레퍼런스

> **레퍼런스 문서**: Virtual Module 패턴 상세 가이드입니다. 메인 문서에서 링크로 참조됩니다.

---

## 개요

**파일**: `ui/temp_generation_window.py`, `ui/temp_generation_params.py`

임시 생성 창 (Temporary Generation Window) 시스템은 메인 UI와 독립적으로 이미지를 생성할 수 있는 별도의 창을 제공합니다. 이 시스템의 핵심은 **Virtual Module 패턴**으로, 메인 UI 모듈의 경량 복제본을 생성하여 AppContext 파이프라인을 우회합니다.

### 주요 특징

- 🔄 **독립 생성**: 메인 UI와 별도로 이미지 생성 가능
- 🧩 **Virtual Module 패턴**: 메인 모듈의 상태 복사 및 독립 실행
- 🎯 **Manual Hook Execution**: AppContext 파이프라인 대신 직접 훅 실행
- 🔒 **Skip Flag 패턴**: 메인 UI 훅과 충돌 방지
- 📋 **Full-Tab 스크롤**: 전체 탭 스크롤 가능 UI 패턴

---

## Virtual Module 패턴

Virtual Module은 메인 UI 모듈의 **UI와 로직을 복제**하지만, AppContext 파이프라인에 등록되지 않는 경량 버전입니다.

### 설계 원칙

1. **독립성**: AppContext 파이프라인에 등록하지 않음
2. **상태 복사**: `initialize_from_main()` 메서드로 메인 모듈 상태 복제
3. **수동 훅 실행**: `execute_manual_hook()` 메서드로 직접 파이프라인 로직 실행
4. **충돌 방지**: Skip flag로 메인 모듈 훅과 동시 실행 방지

### 구현 예시: VirtualPromptEngineeringTab

**파일**: `ui/virtual_prompt_engineering_tab.py:1-470`

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QTextEdit, QCheckBox
from core.context import AppContext
from core.prompt_context import PromptContext
from ui.theme import DARK_COLORS, DARK_STYLES

class VirtualPromptEngineeringTab(QWidget):
    """
    Virtual Module for Prompt Engineering in Temporary Generation Window.

    이 모듈은 메인 PromptEngineeringModule의 UI와 로직을 복제하지만,
    AppContext 파이프라인에 등록되지 않고 수동으로 훅을 실행합니다.
    """

    def __init__(self, app_context: AppContext, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.main_module = None  # 메인 모듈 참조

        # UI 위젯 참조
        self.pre_textedit = None
        self.post_textedit = None
        self.auto_hide_textedit = None
        self.preprocessing_checkboxes = {}

        # 옵션 키 매핑
        self.option_key_map = {
            "랜덤 프롬프트의 작가명을 제거": "remove_author",
            "랜덤 프롬프트의 캐릭터명을 제거": "remove_character",
            # ... 7개 옵션
        }

        self.init_ui()

    def init_ui(self):
        """Full-tab 스크롤 패턴으로 UI 구성"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 스크롤 영역 생성
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")

        # 실제 콘텐츠 위젯
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)

        # 프리픽스 섹션
        self.pre_textedit = QTextEdit()
        self.pre_textedit.setAcceptRichText(False)  # 필수!
        self.pre_textedit.setStyleSheet(DARK_STYLES['compact_textedit'])
        content_layout.addWidget(self.pre_textedit)

        # ... 나머지 UI 구성 ...

        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)

    def initialize_from_main(self, main_module):
        """
        메인 PromptEngineeringModule에서 상태를 복사합니다.

        Parameters:
            main_module: PromptEngineeringModule 인스턴스
        """
        self.main_module = main_module

        # 텍스트 필드 복사
        if hasattr(main_module, 'pre_textedit') and main_module.pre_textedit:
            self.pre_textedit.setPlainText(main_module.pre_textedit.toPlainText())

        if hasattr(main_module, 'post_textedit') and main_module.post_textedit:
            self.post_textedit.setPlainText(main_module.post_textedit.toPlainText())

        # ... 체크박스 상태 복사 ...

    def execute_manual_hook(self, context: PromptContext) -> PromptContext:
        """
        수동 파이프라인 훅 실행 (메인 모듈 로직 복제).

        이 메서드는 GenerationController에서 직접 호출되며,
        메인 PromptEngineeringModule.execute_pipeline_hook()과 동일한 로직을 실행합니다.

        Parameters:
            context (PromptContext): 프롬프트 컨텍스트

        Returns:
            PromptContext: 수정된 컨텍스트
        """
        print("🔧 [VirtualPromptEngineeringTab] 프롬프트 엔지니어링 훅 수동 실행...")

        # 프리픽스 태그 추가
        prefix_text = self.pre_textedit.toPlainText().strip()
        if prefix_text:
            prefix_tags = [tag.strip() for tag in prefix_text.split(',') if tag.strip()]
            context.prefix_tags = prefix_tags + context.prefix_tags

        # 포스트픽스 태그 추가
        postfix_text = self.post_textedit.toPlainText().strip()
        if postfix_text:
            postfix_tags = [tag.strip() for tag in postfix_text.split(',') if tag.strip()]
            context.postfix_tags = context.postfix_tags + postfix_tags

        # Auto Hide 처리 (복잡한 로직)
        # ... 470줄의 로직 ...

        return context
```

---

## Manual Hook Execution 패턴

Virtual Module의 훅은 AppContext 파이프라인에 등록되지 않고, GenerationController에서 직접 호출됩니다.

### GenerationController 통합

**파일**: `core/generation_controller.py:375-411`

```python
# 임시 창 프롬프트 엔지니어링 훅 수동 실행
if 'temp_window_prompt_engineering_tab' in params:
    prompt_eng_tab = params['temp_window_prompt_engineering_tab']
    print(f"[TempWindow] 프롬프트 엔지니어링 훅 수동 실행 중...")

    # PromptContext 생성
    from core.prompt_context import PromptContext
    import pandas as pd

    source_row = self.context.current_source_row
    if source_row is None:
        source_row = pd.Series({'general': None}, name="temp_window")

    # tags 파싱 (쉼표로 분리)
    input_tags = [tag.strip() for tag in params['input'].split(',') if tag.strip()]

    # PromptContext 초기화
    temp_context = PromptContext(
        source_row=source_row,
        settings=params,
        prefix_tags=[],
        main_tags=input_tags,
        postfix_tags=[]
    )

    # 수동 훅 실행
    try:
        modified_context = prompt_eng_tab.execute_manual_hook(temp_context)

        # 수정된 태그를 다시 문자열로 결합
        all_tags = modified_context.prefix_tags + modified_context.main_tags + modified_context.postfix_tags
        params['input'] = ', '.join(all_tags)

        print(f"✅ [TempWindow] 프롬프트 엔지니어링 적용 완료")
    except Exception as e:
        print(f"⚠️ [TempWindow] 프롬프트 엔지니어링 훅 실행 오류: {e}")
```

### TempGenerationWindow 통합

**파일**: `ui/temp_generation_window.py:234-283`

```python
# Virtual Module 생성
self.prompt_engineering_tab = VirtualPromptEngineeringTab(self.app_context)
self.tab_widget.addTab(self.prompt_engineering_tab, "🔧 프롬프트 엔지니어링")

# 초기화 (메인 모듈에서 상태 복사)
def initialize_from_main_window(self, main_window):
    main_pe_module = main_window.app_context.middle_section_controller.get_module_instance("PromptEngineeringModule")
    if main_pe_module:
        self.prompt_engineering_tab.initialize_from_main(main_pe_module)
```

**⚠️ 중요: 이미지 생성 버튼 vs 랜덤 프롬프트 버튼**

임시 창에는 두 가지 생성 버튼이 있으며, **각각 다른 동작**을 합니다:

#### 1. 🎨 이미지 생성 버튼 (`on_generate_clicked`)

**목적**: 메인 프롬프트 텍스트를 **그대로** 사용하여 이미지 생성

**동작**:
- 메인 프롬프트 내용만 사용
- 선행/후행 고정 프롬프트 적용 **안 됨**
- Virtual Module 훅 실행 **안 됨**

**구현** (`ui/temp_generation_window.py:278-283`):
```python
def on_generate_clicked(self):
    params = self._collect_generation_params()

    # ❌ 비활성화: 이미지 생성 버튼에서는 메인 프롬프트만 사용
    # 선행/후행 고정 프롬프트는 Random/Next Prompt 버튼을 눌렀을 때만 적용됨
    # if hasattr(self, 'prompt_engineering_tab'):
    #     params['temp_window_prompt_engineering_tab'] = self.prompt_engineering_tab

    self.generate_requested.emit(self.window_id, params)
```

**사용 시나리오**:
```
사용자가 메인 프롬프트에 "1girl, smile, sitting"을 직접 입력
    ↓
이미지 생성 버튼 클릭
    ↓
프롬프트: "1girl, smile, sitting" (입력한 그대로)
```

#### 2. 🔀 Random/Next Prompt 버튼 (`on_random_prompt_clicked`)

**목적**: 선행/후행 고정 프롬프트가 **적용된** 랜덤 프롬프트 생성

**동작**:
- 메인 UI의 `trigger_random_prompt()` 호출
- 선행/후행 고정 프롬프트 자동 적용
- 생성된 프롬프트를 임시 창 메인 프롬프트에 복사

**구현** (`core/temp_window_manager.py:139-186`):
```python
def handle_random_prompt_request(self, window_id: int):
    # 메인 UI의 프롬프트 임시 저장
    original_main = self.main_window.main_prompt_edit.toPlainText()
    original_negative = self.main_window.negative_prompt_edit.toPlainText()

    try:
        # 메인 UI의 프롬프트 생성 (선행/후행 고정 프롬프트 적용됨)
        self.main_window.trigger_random_prompt()

        # 생성된 프롬프트 가져오기
        new_main = self.main_window.main_prompt_edit.toPlainText()
        new_negative = self.main_window.negative_prompt_edit.toPlainText()

        # 임시 창에 복사
        temp_window.update_prompts(new_main, new_negative)
    finally:
        # 메인 UI 복원 (오염 방지)
        self.main_window.main_prompt_edit.setPlainText(original_main)
        self.main_window.negative_prompt_edit.setPlainText(original_negative)
```

**사용 시나리오**:
```
선행 고정 프롬프트: "masterpiece, best quality"
후행 고정 프롬프트: "highly detailed"
    ↓
Random/Next Prompt 버튼 클릭
    ↓
랜덤 태그 생성: "1girl, sitting, park"
    ↓
최종 프롬프트: "masterpiece, best quality, 1girl, sitting, park, highly detailed"
    ↓
임시 창 메인 프롬프트에 복사됨
```

#### 동작 비교표

| 항목 | 이미지 생성 버튼 | Random/Next Prompt 버튼 |
|------|-----------------|------------------------|
| **메인 프롬프트 사용** | ✅ 입력한 그대로 | ✅ 랜덤 생성 후 복사 |
| **선행/후행 고정 프롬프트** | ❌ 적용 안 됨 | ✅ 자동 적용 |
| **Virtual Module 훅** | ❌ 실행 안 됨 | ❌ 실행 안 됨 (메인 UI 훅만) |
| **메인 UI 오염** | ❌ 없음 | ❌ 없음 (복원됨) |
| **용도** | 직접 입력한 프롬프트로 테스트 | 랜덤 프롬프트 + 고정 프롬프트 조합 |

#### 수정 이력

**2025-01-20**: 이미지 생성 버튼에서 Virtual Module 훅 전달 비활성화
- **문제**: 이미지 생성 버튼에서도 선행/후행 고정 프롬프트가 적용됨
- **원인**: `on_generate_clicked()`에서 `temp_window_prompt_engineering_tab` 파라미터를 항상 전달
- **해결**: 해당 코드 주석 처리 → 메인 프롬프트만 사용
- **영향**: Random/Next Prompt 버튼은 영향 없음 (메인 UI의 `trigger_random_prompt()` 사용)

---

## Skip Flag 패턴 (Double Execution 방지)

임시 창에서 Random/Next Prompt 버튼을 누를 때, 메인 UI의 PromptEngineeringModule 훅과 임시 창의 VirtualPromptEngineeringTab 훅이 **동시에 실행되는 것을 방지**합니다.

### 문제 상황

```
Random/Next Prompt 버튼 클릭
    ↓
메인 UI trigger_random_prompt() 호출
    ↓
🔧 메인 PromptEngineeringModule 훅 실행 (Auto Hide: 태그 A, B, C 제거)
    ↓
🔧 임시 창 VirtualPromptEngineeringTab 훅 실행 (Auto Hide: 태그 D, E, F 제거)
    ↓
❌ 결과: 서로 다른 Auto Hide 규칙이 중복 적용됨
```

### 해결책: Skip Flag

**AppContext 플래그 추가**:
```python
# core/context.py (자동 추가됨, 명시적 선언 불필요)
self.skip_prompt_engineering_hook = False  # 동적 속성
```

**메인 모듈에서 플래그 확인** (`modules/prompt_engineering_module.py:343-346`):
```python
def execute_pipeline_hook(self, context: PromptContext) -> PromptContext:
    """기존 파이프라인 훅 로직 유지"""

    # 임시 창 프롬프트 생성 중에는 메인 UI 훅 건너뛰기
    if hasattr(self, 'app_context') and getattr(self.app_context, 'skip_prompt_engineering_hook', False):
        print("[DEBUG] 🚫 메인 PromptEngineeringModule 훅 건너뛰기 (임시 창 프롬프트 생성 중)")
        return context

    print("🔧 프롬프트 엔지니어링 훅 실행...")
    # ... 기존 로직 계속 ...
```

**TempWindowManager에서 플래그 관리** (`NAIA_cold_v4.py:521-586`):
```python
def handle_random_prompt_request(self, temp_window):
    try:
        # 메인 PromptEngineeringModule 훅 비활성화
        self.main_window.app_context.skip_prompt_engineering_hook = True
        print("[DEBUG] ✅ skip_prompt_engineering_hook = True 설정")

        # Random Prompt 생성 (메인 UI 훅 건너뜀)
        new_main_prompt = self.main_window.trigger_random_prompt()

        # 임시 창의 프롬프트 엔지니어링 훅 수동 실행
        if hasattr(temp_window, 'prompt_engineering_tab'):
            # PromptContext 생성
            temp_context = PromptContext(
                source_row=...,
                settings={},
                prefix_tags=[],
                main_tags=input_tags,
                postfix_tags=[]
            )

            # 수동 훅 실행
            modified_context = temp_window.prompt_engineering_tab.execute_manual_hook(temp_context)
            all_tags = modified_context.prefix_tags + modified_context.main_tags + modified_context.postfix_tags
            new_main_prompt = ', '.join(all_tags)

        # 임시 창에 프롬프트 적용
        temp_window.main_prompt_input.setPlainText(new_main_prompt)

    finally:
        # 메인 PromptEngineeringModule 훅 재활성화
        self.main_window.app_context.skip_prompt_engineering_hook = False
        print("[DEBUG] ✅ skip_prompt_engineering_hook = False 해제")
```

### 실행 흐름 (수정 후)

```
Random/Next Prompt 버튼 클릭
    ↓
skip_prompt_engineering_hook = True 설정
    ↓
메인 UI trigger_random_prompt() 호출
    ↓
🚫 메인 PromptEngineeringModule 훅 건너뛰기 (플래그 체크)
    ↓
🔧 임시 창 VirtualPromptEngineeringTab 훅 실행 (Auto Hide: 태그 D, E, F 제거)
    ↓
skip_prompt_engineering_hook = False 해제
    ↓
✅ 결과: 임시 창 Auto Hide 규칙만 적용됨
```

---

## Full-Tab Scrolling 패턴

Virtual Module은 전체 탭이 스크롤 가능한 UI 패턴을 사용합니다.

```python
def init_ui(self):
    main_layout = QVBoxLayout(self)
    main_layout.setContentsMargins(0, 0, 0, 0)

    # 전체 탭을 감싸는 QScrollArea
    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    scroll_area.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")

    # 실제 콘텐츠
    content_widget = QWidget()
    content_layout = QVBoxLayout(content_widget)

    # UI 요소들 추가
    content_layout.addWidget(...)

    scroll_area.setWidget(content_widget)
    main_layout.addWidget(scroll_area)
```

---

## TempGenerationWindow 추가 기능

### 1. 프롬프트 고정 (Prompt Fixed)

**위치**: `ui/temp_generation_window.py:190-193, 311-322`

**구현**:
```python
# UI 생성
self.prompt_fixed_checkbox = QCheckBox("프롬프트 고정")
self.prompt_fixed_checkbox.setToolTip("체크 시: Random/Next Prompt 버튼 비활성화")
self.prompt_fixed_checkbox.stateChanged.connect(self._on_prompt_fixed_changed)

# 체크박스 상태 변경 핸들러
def _on_prompt_fixed_changed(self, state):
    """프롬프트 고정 체크박스 상태 변경 시 Random 버튼 활성화/비활성화"""
    is_fixed = (state == Qt.CheckState.Checked.value)
    self.random_prompt_btn.setEnabled(not is_fixed)
```

### 2. 와일드카드 단독 모드

**위치**: `ui/temp_generation_window.py:195-197, 286-287`

**구현**:
```python
# UI 생성
self.wildcard_standalone_checkbox = QCheckBox("와일드카드 단독 모드")
self.wildcard_standalone_checkbox.setToolTip("데이터베이스 태그 없이 와일드카드만 사용")

# 생성 로직 (GenerationController)
if params.get('wildcard_standalone', False):
    # 와일드카드 단독 모드: 빈 데이터로 source_row 생성
    empty_data = {
        'general': None,
        'character': None,
        'copyright': None,
        'artist': None,
        'meta': None
    }
    source_row = pd.Series(empty_data, name="wildcard_standalone")
```

### 3. 메인 UI 적용 (Apply to Main UI)

**위치**: `ui/temp_generation_window.py:324-453`, `NAIA_cold_v4.py:3218-3377`

5개 섹션 선택적 적용:
- 메인 프롬프트 (기본 ✅)
- 네거티브 프롬프트 (기본 ✅)
- 생성 파라미터 (기본 ✅)
- 캐릭터 (기본 ❌, 텍스트 덤핑)
- 프롬프트 엔지니어링 (기본 ❌, 전체 설정 복사)

---

## 체크리스트: Virtual Module 작성

```
[ ] QWidget 상속 (BaseMiddleModule 아님!)
[ ] app_context 참조 저장
[ ] main_module 참조 저장 (initialize_from_main에서 설정)
[ ] Full-tab 스크롤 패턴 사용
[ ] 모든 QTextEdit에 setAcceptRichText(False) 적용
[ ] DARK_COLORS['bg_primary'] 배경색 적용
[ ] initialize_from_main() 메서드 구현
[ ] execute_manual_hook() 메서드 구현 (메인 모듈 로직 복제)
[ ] TempGenerationWindow에 탭 추가
[ ] GenerationController에 수동 훅 실행 로직 추가
[ ] 필요 시 Skip Flag 패턴 구현 (double execution 방지)
```

---

## 디버깅 팁

**Virtual Module이 작동하지 않는 경우**:

1. **상태 복사 실패**: `initialize_from_main()` 호출 확인
2. **훅 미실행**: `params['temp_window_xxx_tab']` 키 전달 확인
3. **Double Execution**: Skip flag 설정/해제 로그 확인
4. **UI 업데이트 안 됨**: QThread 시그널/슬롯 연결 확인

**디버깅 로그 추가**:
```python
def execute_manual_hook(self, context):
    print(f"[DEBUG] Virtual Module 훅 실행: {self.__class__.__name__}")
    print(f"[DEBUG] 입력 태그: {context.main_tags}")

    # ... 로직 ...

    print(f"[DEBUG] 출력 태그: {all_tags}")
    return context
```

---

*레퍼런스 문서 버전: 1.0*
*최종 업데이트: 2025-01-17*
