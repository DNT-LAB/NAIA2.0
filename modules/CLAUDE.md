# CLAUDE.md — modules/

> 좌측 Middle Section에 로드되는 모듈 개발 가이드. BaseMiddleModule 상속, ModeAwareModule 다중 상속으로 모드별 설정 관리.

---

## 디렉터리 구조 및 의존성

```
modules/
  ├── interfaces/ 계약 준수 → BaseMiddleModule, ModeAwareModule
  ├── core/ 의존 → AppContext, 컨트롤러, 파이프라인
  ├── ui/ 사용 → theme, scaling_manager, modern_menu
  └── tabs/와 이벤트로 통신 → AppContext.publish/subscribe
```

**로딩**: `MiddleSectionController`가 `modules/*_module.py` 자동 스캔 → `BaseMiddleModule` 상속 클래스 인스턴스 생성 → AppContext 주입 → UI 배치

---

## 주요 파일

| 파일 | 주요 기능 | 특징 |
|------|----------|------|
| **character_module.py** | 캐릭터 검색, 5x5 위치 그리드 | ModeAware, 파이프라인 훅 |
| **character_reference_module.py** | Character Reference 관리 | NAI 전용 |
| **vibe_transfer_module.py** | Vibe Transfer 이미지 | NAI 전용, 다중 이미지 |
| **prompt_engineering_module.py** | 프롬프트 엔지니어링 | 태그 조작, 프리셋 랜덤화, Danbooru Auto-Weight(IDF), e621 Auto-Boost |
| **automation_module.py** | 자동 생성 | QThread, 타이머/횟수/무제한 |
| **instant_wildcard_module.py** | 인스턴트 와일드카드 | JSON 저장/로드 |
| **conditional_prompt_module.py** | 조건부 프롬프트 | 파이프라인 훅, 패턴 매칭(`__tag=,`) |
| **e621_event_module.py** | E621 이벤트 태그 | Parquet, 즐겨찾기, 숨김/복원 |
| **wildcard_status_module.py** | 와일드카드 상태 표시 | PromptContext 구독 |
| **ollama_module.py** | 자연어→태그 변환 (Ollama LLM) | Lazy 초기화, e621 NSFW Boost |

---

## BaseMiddleModule 계약 (`interfaces/base_module.py`)

### 필수 메서드

```python
def get_title(self) -> str: ...
def create_widget(self, parent) -> QWidget: ...
```

### 선택적 메서드

```python
def get_order(self) -> int: ...             # 기본 100, 낮을수록 위
def get_parameters(self) -> dict: ...       # 생성 API 추가 파라미터
def get_pipeline_hook_info(self) -> dict: ...  # 훅 등록 정보
def execute_pipeline_hook(self, context) -> PromptContext: ...  # 훅 실행 (반드시 context 반환)
def on_initialize(self): ...
def is_compatible_with_mode(self, mode: str) -> bool: ...
```

### 호환성 플래그

```python
def __init__(self):
    self.NAI_compatibility = True
    self.WEBUI_compatibility = True
    self.COMFYUI_compatibility = True
    self.app_context = None       # 자동 주입
    self.ignore_save_load = False  # True면 설정 저장/로드 무시
```

### AppContext 접근

```python
def initialize_with_context(self, app_context):
    self.app_context = app_context
    app_context.subscribe("api_mode_changed", self._on_mode_changed)
```

**주의**: `self.widget = widget` 저장 필수 (모드 가시성 제어용)

---

## ModeAwareModule 개발 (`interfaces/mode_aware_module.py`)

모드(NAI/WEBUI/COMFYUI)별 설정 자동 저장/로드. 설정 파일: `save/<settings_base_filename>_<MODE>.json`

### 필수 구현

```python
class MyModule(BaseMiddleModule, ModeAwareModule):
    def __init__(self):
        BaseMiddleModule.__init__(self)
        ModeAwareModule.__init__(self)
        self.settings_base_filename = "my_module"  # 필수

    def collect_current_settings(self) -> dict: ...  # UI → dict
    def apply_settings(self, settings: dict): ...    # dict → UI
    def get_module_name(self) -> str: ...             # 로깅용
```

### 자동 동작 (`on_mode_changed`)

1. 이전 모드 설정 저장
2. `current_mode` 변경
3. 새 모드 설정 로드
4. 가시성 업데이트

---

## 파이프라인 훅

### 훅 포인트 (실행 순서)

```
1. pre_processing       ← 가장 먼저
2. 해상도 자동 맞춤      (내부)
3. post_processing      ← 와일드카드 확장 전
4. 와일드카드 확장       (내부)
5. after_wildcard       ← 와일드카드 확장 후
6. final_hookpoint      ← 최종 포맷 전
7. 최종 포맷팅          (내부)
```

### 훅 등록 및 실행

```python
def get_pipeline_hook_info(self) -> dict:
    return {
        'target_pipeline': 'PromptProcessor',
        'hook_point': 'post_processing',
        'priority': 10  # 낮을수록 먼저
    }

def execute_pipeline_hook(self, context):
    context.main_tags.append("my_tag")
    return context  # 반드시 반환
```

### PromptContext 주요 속성

```python
context.prefix_tags: List[str]       # 맨 앞 태그
context.main_tags: List[str]         # 메인 태그
context.postfix_tags: List[str]      # 맨 뒤 태그
context.global_append_tags: List[str]
context.source_row: pd.Series        # 검색 결과 행
context.settings: dict
context.metadata: dict               # 자유 형식
context.sequential_counters: dict
context.wildcard_state: dict
context.final_prompt: str
```

---

## 고급 패턴

### QThread (UI 블로킹 방지)

```python
class MyWorker(QThread):
    work_finished = pyqtSignal(dict)
    def run(self):
        result = self._do_heavy_work()
        self.work_finished.emit(result)

# 모듈에서
self.worker = MyWorker()
self.worker.work_finished.connect(self._on_finished)
self.worker.finished.connect(self.worker.deleteLater)  # 메모리 누수 방지
self.worker.start()
```

**주의**: QThread에서 직접 UI 수정 금지. 반드시 시그널로.

### Skip Flag 패턴 (임시 창 이중 실행 방지)

임시 생성 창에서 메인 UI 훅과 Virtual Module 훅 중복 방지.

```python
# 메인 모듈에서 플래그 체크
def execute_pipeline_hook(self, context):
    if getattr(self.app_context, 'skip_prompt_engineering_hook', False):
        return context  # 건너뛰기
    # ... 기존 로직 ...

# 임시 창 관리자에서
try:
    self.app_context.skip_prompt_engineering_hook = True
    # ... 작업 ...
finally:
    self.app_context.skip_prompt_engineering_hook = False  # 반드시 해제
```

**핵심**: `finally` 블록 필수, `getattr` 안전 접근 (기본값 `False`)

### EZ Mode Selective Skip

`skip_prompt_engineering_auto_hide` 플래그로 선행/후행 고정 프롬프트는 유지하면서 Auto Hide/전처리만 건너뛰기.

- 유지: Leading/Trailing Fixed Prompt
- 건너뛰기: 작품명/작가명 자동 추가, Auto Hide, 캐릭터 특징/의류/색상/위치 제거

`skip_preprocessing = True`일 때 `checkbox_options = {}`로 초기화 (이후 KeyError 방지).

### Ollama Module (Lazy 초기화 + v2 파이프라인)

| 클래스 | 역할 |
|--------|------|
| `TagDatabase` | e621/danbooru 태그 DB, 4-tier 검색, NSFW Boost |
| `DebugPanel(QDialog)` | 스테이지별 디버그 (`WA_DeleteOnClose=False`) |
| `OllamaStatusCheckWorker(QThread)` | 비동기 설치/서버 상태 확인 |
| `OllamaServerActionWorker(QThread)` | 비동기 서버 시작/중지 |
| `OllamaConversionWorker(QThread)` | v2 파이프라인 (5단계 LLM/Code 혼합) |
| `OllamaModule(BaseMiddleModule)` | UI (Lazy init, Session, Progress Bar) |

**v2 파이프라인 스테이지**: Pre-processing(5%) → 번역(15%) → 의도 분해 LLM(35%) → 후보 검색(50%) → e621 NSFW Boost(55%) → 태그 선택 LLM(80%) → 자연어 생성 LLM(95%) → 결과(100%)

**e621 NSFW Boost**: ACTION/SEXUAL_ACT/BODY_EXPOSURE/RESTRAINT 카테고리 전용. Phase 1a(Direct match, 3.0) → Phase 1c(Tag name index, 2.0) → Phase 2(Wiki link, 2.0/1.5) → Phase 3(Wiki text, 1.0). 최종 점수: `base_score * (log10(freq) / 4.0)`.

### 캐릭터 위치 시스템 (`character_module.py`)

5x5 그리드 (A-E열, 1-5행). 좌표 매핑: A-E→x:0.1-0.9, 1-5→y:0.1-0.9. 기본값 C3(0.5,0.5).

- 25x25px 시각화 이미지, SmoothTransformation
- 랜덤 배치 (C3 제외 옵션), 자동 리롤
- 2명 미만 시 자동 비활성화 안전장치
- `get_parameters()`에서 `character_positions` 생성 → `api_service.py`의 `centers`로 전달

### 프리셋 랜덤화 (`prompt_engineering_module.py`)

- `*randomized` 특수 프리셋: 풀에서 랜덤 선택
- `random_prompt_triggered` / `random_prompt_triggered_preset_randomizer` 이벤트 구독
- `load_preset_random()`: pre_prompt, post_prompt, main_settings(prompt 제외)만 적용
- API 모드 변경 시 상태 초기화

### 태그 필터링 (`core/tag_filter_helpers.py`)

`apply_tag_filters()`: 10라운드 순차 필터링. `prompt_engineering_module.py`와 `virtual_prompt_engineering_tab.py`에서 공유.

1. Auto Hide → 2. 캐릭터 특징 → 3. 의류 → 4. 색상 → 5. 위치/배경 → 6. 표정 → 7. 포즈/행동 → 8. 메타 → 9. 사물 → 10. 노이즈

`_is_color_exception(tag)`: 색상과 무관한 태그 보호 (예: `blueberry`, `rainbow`, `covered`).

### 필터 디버깅 윈도우 (`filter_debug_window.py`)

`FilterDebugWindow(QDialog)`: 라운드별 필터 제거 내역 시각화. 소스 정보(캐릭터/작품/아티스트/ID) + 라운드별 색상 코딩 (주황=제거, 초록=통과, 회색=비활성). e621 Auto-Boost 섹션(연주황색)으로 입력 태그 및 추천 결과 표시.

### Danbooru Auto-Weight (`prompt_engineering_module.py`)

IDF(역문서빈도) 기반 태그 자동 가중치. Danbooru 800만 건의 태그 빈도 데이터(`danbooru_tag_counts_by_rating.json`)를 사용.

- **원리**: `blended_idf = global_idf + α*(rating_idf - global_idf)` → 정규화 → `weight = 1.0 + scale*(2*norm - 1)`
- **Rating 판별 우선순위**: Rating 오버라이드(설정) > `source_row['rating']`(parquet) > `_infer_rating_from_tags`(Naive Bayes 추론, 와일드카드 단독) > `'s'` fallback
- **Rating 오버라이드**: 설정 윈도우에서 G/S/Q/E 강제 지정 가능. `_danbooru_weight_settings`에 `rating_override_on`, `rating_override` 키로 저장
- **가중치 구문 파싱**: `_strip_weight_syntax()` — NAI(`0.89::tag ::`)와 A1111(`(tag:1.2)`) 양쪽 형식 지원. 후행 `::` 먼저 제거 → 선행 `weight::` 제거 순서 (그룹 래핑 뒤쪽 조각 처리)
- **`__wildcard__` 전개 호환**: `_execute_danbooru_weight_after_wildcard`에서 콤마 합쳐진 단일 문자열을 개별 태그로 flat split 후 가중치 적용 (wildcard_processor가 `__wc__`를 `['tag1, tag2']` 형태로 반환하므로)
- **after_wildcard hook**: priority 15 (e621 priority 10 이후). `_DanbooruWeightAfterWildcardHook` 위임 객체
- **설정 윈도우**: `_DanbooruWeightSettingsWindow` — 강도(1-10단계), 커스텀 오버라이드(scale/min/max), Rating 블렌드(α), Rating 오버라이드(G/S/Q/E), 4탭 실시간 미리보기

### e621 Auto-Boost (`prompt_engineering_module.py`)

`data/e621_boost_static.py`의 `recommend_detailed()`를 호출하여 main_tags 뒤에 추천 태그를 추가. 하이라이터 연주황색 표시.

- **일반 모드**: `post_processing` hook에서 즉시 처리 (prefix_tags + 필터링 전 원본 main_tags)
- **와일드카드 단독 모드**: `post_processing`에서 원본 태그를 `context.metadata['_e621_source_tags']`에 보존 → `after_wildcard` hook에서 전개된 prefix_tags와 합쳐 처리
- **after_wildcard hook 등록**: `create_widget()`에서 `_E621AfterWildcardHook` 위임 객체를 직접 `register_pipeline_hook()` 호출로 등록 (get_pipeline_hook_info 미사용)

---

## 주요 함정/주의사항

### QTextEdit 사용 시

```python
self.prompt_edit = QTextEdit()
self.prompt_edit.setAcceptRichText(False)  # 필수! 서식 붙여넣기 차단
setModernStyle(self.prompt_edit)  # 태그 자동완성 + 와일드카드 메뉴
```

읽기 전용 QTextEdit도 `setAcceptRichText(False)` 필수.

### 모듈 로드 안 됨

- 파일명 `*_module.py` 패턴인지 확인
- `BaseMiddleModule` 상속, `get_title()` + `create_widget()` 구현 확인
- 파이썬 문법 오류 콘솔 확인

### 파이프라인 훅 미실행

- `get_pipeline_hook_info()` 반환값 확인: `target_pipeline: 'PromptProcessor'`
- `execute_pipeline_hook()`에서 `return context` 누락 확인
- `initialize_with_context()` 호출 전 등록 시도 확인

### 모드 전환 시 설정 유실

- `ModeAwareModule` 다중 상속 확인
- `settings_base_filename` 설정 확인
- `collect_current_settings()` / `apply_settings()` 구현 확인

### UI 스레드 블로킹

QThread에서 직접 UI 수정 금지. `pyqtSignal.emit()` → 메인 스레드 슬롯 패턴.
`worker.finished.connect(worker.deleteLater)` 필수 (메모리 누수 방지).
