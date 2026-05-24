# CLAUDE.md — NAIA 2.0

Headless Remote Web 중심 AI 이미지 생성 앱. NovelAI / Stable Diffusion WebUI / ComfyUI 백엔드 지원. PyQt6 데스크톱 앱은 active source에서 제거되었으며 필요 시 git history로만 확인한다.

**우선순위**: 사용자 직접 요청 > 디렉터리별 CLAUDE.md > 본 문서

**상세 가이드**: 각 디렉터리의 `CLAUDE.md` 참조. 상세 레퍼런스는 `<dir>/.claude/*_CLAUDE.md`에 분리.

---

## 프로젝트 구조

```
NAIA2.0/
├── NAIA_web_headless.py        # 지원 Remote Web 진입점
├── app/web/remote/             # canonical Remote Web UI source
├── app/backend/                # optional shell/launcher backend adapters
├── app/electron/               # optional Electron shell
├── core/                       # headless services, runtime context, generation/search API
├── interfaces/                 # headless/runtime 계약 정의
├── release_assets/             # manifests, contracts, release gates
├── tests/                      # headless/electron/integration checks
├── utils/                      # 이미지 메타데이터, 토큰 계산, 번역
└── data/                       # Parquet 태그 DB, 텍스트 사전
```

실행:
- 지원 웹 세션 모드: `python NAIA_web_headless.py` (또는 `run_NAIA_web.bat` / `run_NAIA_web.command`)

의존성:
- 지원 웹 세션: `pip install -r requirements-headless.txt` 또는 `requirements.txt`

---

## 핵심 원칙

1. **AppContext 중심**: 모든 공유 상태/서비스는 `core/context.py`의 AppContext 통해 접근
2. **이벤트 기반 통신**: 직접 위젯 조작 금지. `app_context.publish()` / `subscribe()` 사용
3. **파이프라인 훅**: 모듈이 프롬프트 생성에 개입하는 표준 방법 (`get_pipeline_hook_info()` + `execute_pipeline_hook()`)
4. **UI 스레드 보호**: 네트워크/파일 IO → 반드시 QThread 분리
5. **고정 DPI 호환 헬퍼**: 기존 PyQt 화면은 `get_scaled_font_size()` / `get_scaled_size()`를 유지하되, future01에서는 1.0 고정값으로 동작

---

## AppContext 핵심 API

```python
app_context.subscribe("event_name", callback)       # 이벤트 구독
app_context.publish("event_name", {"data": "value"}) # 이벤트 발행
app_context.set_api_mode("NAI")                      # 모드 변경 (NAI/WEBUI/COMFYUI)
app_context.register_pipeline_hook(pipeline, hook_point, module, priority)
```

주요 이벤트: `api_mode_changed`, `prompt_generated`, `save_directory_changed`, `comfyui_workflow_changed`

---

## 모듈/탭 계약

**좌측 모듈** (`modules/*_module.py` → `BaseMiddleModule`):
```python
def get_title(self) -> str          # 필수: 모듈 제목
def create_widget(self, parent)     # 필수: UI 위젯
def get_order(self) -> int          # 선택: 순서 (기본 100)
def get_parameters(self) -> dict    # 선택: 생성 파라미터
```

**우측 탭** (`tabs/*_tab.py` → `BaseTabModule`):
```python
def get_tab_title(self) -> str      # 필수: 탭 제목
def create_widget(self, parent)     # 필수: UI 위젯
```

**모드 인식** (`ModeAwareModule` 다중 상속): `collect_current_settings()` / `apply_settings()` 구현. 설정 자동 저장/로드.

---

## 프롬프트 파이프라인

`core/prompt_processor.py` — 실행 순서:

```
pre_processing → 해상도 맞춤 → post_processing → 와일드카드 확장 → after_wildcard → final_hookpoint → 최종 포맷팅
```

훅 등록: `get_pipeline_hook_info()` → `{'target_pipeline': 'PromptProcessor', 'hook_point': '...', 'priority': N}`

PromptContext 주요 속성: `source_row`, `settings`, `prefix_tags`, `main_tags`, `postfix_tags`, `final_prompt`, `metadata`

---

## UI 필수 규칙

### 스타일링

```python
from ui.theme import DARK_STYLES, DARK_COLORS, get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
```

- 스타일은 `DARK_STYLES['primary_button']`, `get_dynamic_styles()['label_style']` 등 사용
- 커스텀 스타일: `f"font-size: {get_scaled_font_size(16)}px; padding: {get_scaled_size(8)}px;"`
- `QTextEdit` 생성 시 반드시 `setAcceptRichText(False)` 호출

### DARK_COLORS 주의

```python
# KeyError 발생하는 키:
DARK_COLORS['accent']        # → 'accent_blue' 사용
DARK_COLORS['accent_hover']  # → 'accent_blue_hover' 사용
```

### QThread 패턴

```python
self.thread = QThread()
self.worker = MyWorker()
self.worker.moveToThread(self.thread)
self.thread.finished.connect(self.worker.deleteLater)   # 필수
self.thread.finished.connect(self.thread.deleteLater)    # 필수
self.worker.finished.connect(self._on_result)
self.thread.started.connect(self.worker.run)
self.thread.start()
```

HTTP 요청 후 `_cleanup_http_threads()` 호출 필수 (Dummy 스레드 누적 방지).

---

## Remote Web 레이아웃

```
app/web/remote
├── prompt and generation controls
├── parameter panels
├── tool popups / detached module geometry
└── result and status panels
```

- Remote Web source of truth는 `app/web/remote`다.
- Desktop-only PyQt layout behavior must be rebuilt against headless/web contracts instead of restoring removed desktop code.

---

## 디렉터리별 상세 가이드

| 디렉터리 | CLAUDE.md | 핵심 내용 |
|----------|-----------|----------|
| `core/` | [core/CLAUDE.md](core/CLAUDE.md) | AppContext, 컨트롤러, 파이프라인, API 서비스 |
| `modules/` | [modules/CLAUDE.md](modules/CLAUDE.md) | 모듈 개발, 파이프라인 훅, 모드 인식 |
| `tabs/` | [tabs/CLAUDE.md](tabs/CLAUDE.md) | 탭 개발, 시그널 브리징, Studio Tab |
| `ui/` | [ui/CLAUDE.md](ui/CLAUDE.md) | 테마, 스케일링, CollapsibleBox, DetachedWindow |
| `ui/interactive/` | [ui/interactive/CLAUDE.md](ui/interactive/CLAUDE.md) | Interactive Mode 블록 시스템 |
| `interfaces/` | [interfaces/CLAUDE.md](interfaces/CLAUDE.md) | 계약 정의, Breaking Change 방지 |
| `utils/` | [utils/CLAUDE.md](utils/CLAUDE.md) | 이미지 메타데이터, 토큰 계산 |
| `data/` | [data/CLAUDE.md](data/CLAUDE.md) | Parquet DB, 텍스트 사전, 검색 |

---

## 코딩 스타일

- PEP 8 (라인 120자), 타입 힌트 권장, 한글 주석 허용
- 시그널/슬롯: 람다 대신 메서드 권장
- QThread 종료 시 `deleteLater` 필수
