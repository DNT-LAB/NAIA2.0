# CLAUDE.md — core/

> NAIA 2.0의 핵심 시스템 계층. AppContext, 컨트롤러, 파이프라인, API 브릿지.

---

## 디렉터리 구조 및 의존성

```
NAIA_cold_v4.py (메인)
    ↓
core/main_controller.py
    ↓
core/context.py (AppContext 생성)
    ↓
core/middle_section_controller.py ← modules/ 로드
core/tab_controller.py ← tabs/ 로드
core/prompt_generation_controller.py
core/generation_controller.py
```

**core/가 의존하는 것**: `interfaces/`, `ui/`, `utils/`, `data/`
**core/를 의존하는 것**: `modules/`, `tabs/`, `NAIA_cold_v4.py`

**상세 레퍼런스**:
- [Generation Queue 가이드](.claude/GENERATION_QUEUE_CLAUDE.md)
- [자동생성-큐 핸드오프 가이드](.claude/AUTO_GENERATION_HANDOFF_CLAUDE.md)
- [상세 변경 로그](.claude/CHANGELOG_CLAUDE.md)

---

## 주요 파일

| 파일 | 역할 |
|------|------|
| **context.py** | 중앙 상태 관리, 이벤트 버스, 파이프라인 훅 레지스트리 |
| **api_service.py** | API 호출 (NAI/WEBUI/COMFYUI), Auto-Outpainting |
| **generation_controller.py** | QThread 이미지 생성 워커, 시퀀스 생성 |
| **sequence_parser.py** | 시퀀스 프롬프트 파싱 (`:begin`, `:seq`, `:end`) |
| **generation_queue_manager.py** | 생성 큐 (우선순위, 일시정지) |
| **autocomplete_manager.py** | 태그 자동완성, NAI `::` 가중치 처리 |
| **comfyui_workflow_manager.py** | ComfyUI 워크플로우 관리 |
| **middle_section_controller.py** | 모듈 로딩, 아코디언 동작, 상태 영속성 |
| **comfyui_service.py** | ComfyUI 순수 HTTP 통신 (WebSocket 제거됨) |
| **wildcard_processor.py** | 와일드카드 치환 (랜덤/순차/종속), 오버라이드 지원 |
| **image_crud_controller.py** | 이미지 파일 CRUD, 분류 시스템 |
| **tab_controller.py** | 탭 로딩 및 관리 |
| **prompt_processor.py** | 프롬프트 파이프라인 |
| **wildcard_manager.py** | 와일드카드 파일 로딩, 가중치 파싱, 라인 제거 |
| **prompt_generation_controller.py** | 프롬프트 생성, side-effect 없는 생성 |
| **prompt_context.py** | PromptContext 데이터 클래스 |
| **mode_ware_manager.py** | 모드 인식 모듈 일괄 저장/로드 |
| **ui_state_manager.py** | UI 레이아웃 상태 저장/복원 (창 크기, 스플리터, 모듈 접기 등) |
| **generation_request.py** | GenerationRequest 데이터 클래스 |
| **filter_data_manager.py** | 텍스트/JSON 태그 사전 로드, noise whitelist |
| **tag_filter_helpers.py** | 공유 태그 필터링 (10라운드), 색상 예외 |

---

## AppContext (`context.py`)

중앙 허브. 공유 서비스, 이벤트 버스, 파이프라인 훅, API 모드 관리.

### 이벤트 버스

```python
app_context.subscribe("event_name", callback)      # 구독
app_context.unsubscribe("event_name", callback)    # 구독 해제 (수명주기 짧은 창에서 필수)
app_context.publish("event_name", {"key": "value"}) # 발행
```

`unsubscribe`는 동일 콜백이 중복 등록된 경우 모두 제거합니다. 다이얼로그/창처럼 수명주기가 짧은 구독자는 `closeEvent`에서 반드시 해제해야 누수가 없습니다.

### 주요 이벤트

| 이벤트 | 데이터 | 용도 |
|--------|--------|------|
| `api_mode_changed` | `{"old_mode": str, "new_mode": str}` | 모드 전환 |
| `prompt_generated` | `PromptContext` | 프롬프트 생성 완료 |
| `save_directory_changed` | `{"new_path": str}` | 저장 경로 변경 |
| `image_counter_changed` | `{"new_counter": int}` | 카운터 변경 |
| `scoped_wildcard_changed` | `{}` | 스코프 ComboBox 변경 |
| `comfyui_workflow_changed` | `{"has_custom": bool, "model_compat": str\|None, "locked_loader_class": str\|None, "locked_model_display": str\|None}` | ComfyUI 사용자 커스텀 워크플로우 로드/해제 시 UI 잠금 동기화 (175) |

### 파이프라인 훅 등록

```python
app_context.register_pipeline_hook(hook_info, module_instance)
# hook_info: {'target_pipeline': 'PromptProcessor', 'hook_point': str, 'priority': int}

app_context.get_pipeline_hooks('PromptProcessor', 'post_processing')
# → [module_instance, ...] (우선순위순)
```

### API 모드 변경

```python
app_context.set_api_mode("WEBUI")  # "NAI", "WEBUI", "COMFYUI"
app_context.get_api_mode()  # → str
```

### API Payload 저장 (디버깅용)

```python
app_context.store_api_payload(payload, api_type="Unknown")
app_context.get_api_payload()
```

---

## MiddleSectionController (`middle_section_controller.py`)

`modules/*_module.py` 동적 로딩, 모듈 상태 추적, 아코디언 동작.

**핵심 동작**:
- `load_modules()`: `*_module.py` 패턴 스캔, `BaseMiddleModule` 상속 클래스 자동 로드
- `initialize_modules_with_context()`: AppContext 주입, ModeAwareModule 자동 등록
- `on_api_mode_changed()`: 호환성 플래그 기반 가시성 업데이트

**모듈 상태 추적**:
- `module_states`: expanded(펼침), detached(분리), scroll_positions
- 아코디언 모드: 하나 펼치면 다른 모듈 자동 접힘 (분리된 모듈 제외)
- 100ms 지연 자동 스크롤
- 상태 파일: `save/module_states.json`

---

## TabController (`tab_controller.py`)

`tabs/*_tab.py` 동적 로딩. core 타입 탭만 시작 시 로드. closable 탭에 닫기 버튼 추가.

시그널: `tab_added(str, object)`, `tab_removed(str)`

---

## SearchController (`search_controller.py`)

멀티프로세싱 태그 검색. `max_file_index`로 검색 범위 제한 (None=전체, 129=130개, 149=150개).

시그널: `search_progress(int, int)`, `partial_search_result(object)`, `search_complete(int)`, `search_error(str)`

---

## PromptGenerationController (`prompt_generation_controller.py`)

UI와 PromptProcessor 중재. PromptContext 생성/초기화, 파이프라인 실행.

시그널: `prompt_generated(str)`, `generation_error(str)`, `prompt_popped(int)`, `resolution_detected(int, int)`

**`generate_instant_source_silent()`**: side-effect 없는 프롬프트 생성. `app_context` 상태를 save/restore (finally 블록). 실패 시 `None` 반환.

---

## 프롬프트 파이프라인 (`prompt_processor.py`)

```
1. pre_processing 훅       ← 모듈 개입
2. 해상도 자동 맞춤         (내부)
3. post_processing 훅      ← 모듈 개입
4. 와일드카드 확장           (내부)
5. after_wildcard 훅       ← 모듈 개입
6. final_hookpoint 훅      ← 모듈 개입
7. 최종 포맷팅              (내부: 인물 정렬, 인물 태그만 중복 제거, 괄호 이스케이프, 주석 포맷)
```

**와일드카드 라인 선택 모드** (`WildcardProcessor`):

| 모드 | 구문 | 선택 방식 | 가중치 |
|------|------|-----------|--------|
| 랜덤 | `__name__`, `<name>` | `random.choices(weights=)` | 적용 |
| 순차 | `__*name__` | `entries[counter % total][1]` | 무시 |
| 종속 | `__$master:slave__` | `entries[slave_index][1]` | 무시 |

**⚠️ 전개 결과 형식 차이** (`wildcard_processor.py`):

| 구문 | 반환 형식 | 예시 |
|------|-----------|------|
| `$wildcard` | 개별 태그 리스트 | `['tag1', 'tag2', 'tag3']` |
| `__wildcard__` | 콤마 합쳐진 단일 문자열 | `['tag1, tag2, tag3']` |

`__wildcard__`는 `_expand_recursive`에서 `''.join(result_parts)` 반환 (복합 패턴 `prefix__wc__suffix` 지원 목적). 개별 태그를 순회하는 downstream 훅에서는 콤마 split 필요.

---

## GenerationController (`generation_controller.py`)

QThread 워커로 비동기 이미지 생성.

### GenerationWorker

시그널: `generation_started()`, `generation_progress(str)`, `generation_finished(dict)`, `generation_error(str)`

**스레드 안전한 진행률**: `_progress_callback`은 `generation_progress.emit()`만 호출. UI 업데이트와 이벤트 발행은 메인 스레드 슬롯에서.

### 에러 처리 (`_on_generation_error`)

| 요청 타입 | 파라미터 키 | 에러 이벤트 |
|-----------|------------|------------|
| Interactive Mode | `interactive_mode_request` | `generation_error` |
| Turbo Sequence | `turbo_sequence_request` | `generation_error` |
| Event Preset | `event_preset_request` | `generation_error` |
| Clothes Preset | `clothes_preset_request` | `generation_error` |
| Character Viewer | `character_viewer_request` | `generation_error` |
| Character Asset | `character_asset_request` (+`character_asset_request_id`) | `generation_error` |
| Studio | `studio_request` | `generation_error_for_studio` |
| Img2Img Batch | `img2img_batch_request` | 직접 콜백 |
| 일반 (자동 생성) | - | 자동 재시도 |

**`generation_error` 이벤트 데이터**: 공통 `message` + 요청 타입 플래그(+식별자). 여러 구독자가 같은 채널을 공유하므로, 각 구독자는 자기 플래그(예: `character_asset_request`)와 id를 확인해 남의 요청을 무시해야 합니다.

**새 특수 요청 타입 추가 시**: 반드시 `_on_generation_error`에 핸들러 추가. 누락 시 요청자가 실패 알림 못 받아 잠금 상태.

### 캐릭터 프롬프트 캡처 우선순위

1. `params['sketchbook_character_prompts']` (Img2ImgWindow override, tuple->dict 변환)
2. 메인 UI `CharacterModule.character_widgets` (active만)

### 임시 창 Virtual Module 훅

`temp_window_prompt_engineering_tab` 파라미터가 있으면 Virtual Module의 `execute_manual_hook()`을 수동 실행. 와일드카드 확장 이후, API 호출 이전.

**주의**: 이미지 생성 버튼에서는 Virtual Module 훅 미적용. Random/Next Prompt에서만 적용.

### 와일드카드 단독 모드

`params['wildcard_standalone'] == True` → 빈 `source_row` 생성하여 DB 태그 없이 와일드카드만 사용.

---

## ImageCrudController (`image_crud_controller.py`)

이미지 저장 중앙화, Thread-safe 카운터, 파일 중복 방지.

### 파일명 형식

`_filename_format`: `"number_only"`, `"time_number"`, `"datetime"`

### 분류 시스템

`_classification_method`: `"none"`, `"prompt_recognition"`

**분류 규칙 구문**:
- `*tag`: 퍼펙트 매칭 (정확히 일치)
- `tag`: 포함 검사
- `&`: AND, `|`: OR, `()`: 그룹핑
- 쉼표로 규칙 구분 (순서 = 우선순위)
- 미매칭 시 `"misc"` 폴더

**폴더명 변환**: `&`→`_and_`, `|`→`_or_`, `*`/`()`/공백 제거 또는 `_`

### 경로 구조

| 타임스탬프 폴더 | 분류 | 2차 분류 | 경로 |
|----------------|------|---------|------|
| True | None | - | `output/20250109_143520/00001.png` |
| True | "1girl" | "solo" | `output/20250109_143520/1girl/solo/00001.png` |
| False | "1girl" | None | `output/1girl/00001.png` |

### save_image 반환값

`(success: bool, filepath: Optional[str], error_message: Optional[str])`

---

## API 서비스 (`api_service.py`)

### 다중 백엔드 분기

`call_generation_api()`: `api_mode`에 따라 `_call_nai_api`, `_call_webui_api`, `_call_comfyui_api` 분기. 입력 정리 (주석 제거, 개행 제거), 재시도 로직 포함.

### HTTP 스레드 정리

**모든 API 호출 후 반드시 `_cleanup_http_threads()` 호출**. urllib3 풀, requests 세션, Qt 스레드 풀, GC 정리.

### Auto-Outpainting (`_single_pass_outpainting`)

`type == 'auto_outpainting'` 인터셉트 → OutpaintWindow 데이터 있으면 직접 사용, 없으면 기본 캔버스 자동 생성 (가로→1:1, 세로→3:2) → 마스크 생성 → `type='inpaint'`로 재호출.

### 캐릭터 위치 좌표

`character_positions` 파라미터를 `v4_prompt.caption.char_captions[].centers`로 전달.

좌표 매핑: A-E→x:0.1-0.9, 1-5→y:0.1-0.9. Fallback: 기본값 `{"x": 0.5, "y": 0.5}`.

---

## ComfyUIWorkflowManager (`comfyui_workflow_manager.py`)

ComfyUI API 워크플로우의 파싱/검증/파라미터 치환. 기본 워크플로우(base/anima) 내장 + 사용자 import 워크플로우 지원.

### 모델 호환성 3-state (175)

사용자가 import 한 워크플로우의 **체크포인트 로더가 표준인지** 판정하여 `node_map["model_compat"]` 에 기록:

| 값 | 판정 기준 | apply_params 시 모델 치환 |
|----|-----------|--------------------------|
| `native_checkpoint` | terminal 로더가 `CheckpointLoaderSimple` | ✅ `ckpt_name` 교체 |
| `native_unet` | terminal 로더가 `UNETLoader` + CLIPLoader 존재 | ✅ `unet_name` 교체 |
| `locked_unknown` | 표준 로더 아님 (커스텀 — INT8/GGUF/NF4 등) | 🔒 skip, 워크플로우 원본값 유지 |

### Sampler-centric 역추적

KSampler/SamplerCustom 의 `model` 입력을 따라 **terminal 로더 노드를 식별**. 중간에 놓인 패치 노드(SageAttention, TorchCompile, RescaleCFG, ModelPatch 등)는 자동 pass-through.

Helper: `_trace_model_source_to_terminal(nodes_by_id, links_data, start_id, is_ui_format)` — UI/API 두 포맷 모두 처리. 순환 / max_depth(64) 초과 / dangling link 시 `None` → 호출부가 LOCKED 귀결.

Helper: `_extract_locked_model_display(terminal_node, is_ui_format)` — `.safetensors`/`.ckpt`/`.gguf`/`.pt`/`.bin`/`.onnx` 확장자 문자열을 inputs/widgets_values 에서 추출 (UI 표시용, 자동 치환 힌트 아님).

### user_workflow_node_map 스키마

```python
{
    "model_compat": "native_checkpoint" | "native_unet" | "locked_unknown",
    "workflow_type": "checkpoint" | "unet" | "locked",  # apply_params 분기용 (하위 호환)

    # native_checkpoint
    "checkpoint_loader": "<node_id>",

    # native_unet
    "unet_loader": "<node_id>",
    "clip_loader": "<node_id>",
    "vae_loader": "<node_id>",          # optional

    # locked_unknown
    "locked_loader_node_id": "<node_id>",
    "locked_loader_class":   "<class_type>",
    "locked_model_display":  "<filename.safetensors>",

    # 공통
    "sampler":         "<ksampler_node_id>",
    "positive_prompt": "<clip_text_encode_id>",
    "negative_prompt": "<clip_text_encode_id>",
    "latent_image":    "<empty_latent_id>",
    "rescale_cfg":     "<node_id>",     # optional
    "model_sampler":   "<node_id>",     # ModelSamplingDiscrete, optional
    "ays_scheduler":   "<node_id>",     # optional
}
```

### comfyui_workflow_changed 이벤트

`load_workflow_from_metadata` 성공 / `clear_user_workflow` 시 AppContext 경유로 발행. ComfyUIParameterPanel이 구독해 `model_combo` 잠금/해제 토글. AppContext 주입은 `context.py:33-34` 에서 자동.

### LOCKED 파이프라인 계약

`apply_params_to_workflow` 에서 `model_compat == "locked_unknown"` 이면 **모델 치환을 명시적으로 skip**. 프롬프트/시드/해상도/샘플러/RescaleCFG 는 정상 치환. 중간 패치 노드의 설정(sage_attention, torch.compile mode 등)은 건드리지 않고 그대로 유지 — ComfyUI 서버에 해당 커스텀 노드 팩이 설치돼 있으면 그대로 실행됨.

### Import 팝업 (WorkflowValidationDialog)

`analyze_workflow_for_ui()` 는 `model_compat` 상태를 반환하며, locked 인 경우 `locked_loader_class` / `locked_model_display` 도 함께 제공. `core/comfyui_utils.py:WorkflowValidationDialog` 가 이를 받아 native/locked 분기로 상태 라벨을 표시.

**회귀 안전망**: `tests/comfyui/test_workflow_compat.py` — 15 테스트 (native 2종 regression + ANIMA INT8 locked 전체 경로 + 순환/dangling/max_depth 견고성 + locked→locked 전환 시 payload 갱신).

---

## WildcardManager (`wildcard_manager.py`)

### 가중치 구문

`{정수}:텍스트` (`{정수}::` NAI 가중치는 제외). 정규식: `^(\d+):(?!:)(.*)`

```python
"100: 0.68::artist:ciloranko ::"  → (100, "0.68::artist:ciloranko ::")
"500:high_weight"                → (500, "high_weight")
"plain text"                     → (100, "plain text")  # 기본 가중치
"100::nai_hundred"               → (100, "100::nai_hundred")  # NAI 구문, 기본값
```

**자료구조**: `wildcard_dict_tree[key] = list[tuple[int, str]]`

**소비자 영향**:
- `WildcardProcessor`: 랜덤 모드 `random.choices(weights=)`, 순차/종속 `entries[index][1]`
- `WildcardCombinationGenerator`: `[text for _, text in entries]`

### 라인 제거 (`remove_line`)

`remove_line(key, value)` → txt 파일에서 value에 해당하는 라인 제거. 가중치 파싱 후 text 정확 매치 → fallback contains 검색. 마지막 라인 보호.

### 오버라이드 (`wildcard_override`)

`app_context.wildcard_override: dict` — `{actual_key: value}` 형태. `WildcardProcessor._get_wildcard_line()`의 일반 무작위 분기에서 오버라이드 값 우선 반환. 순차/종속은 영향 없음. `_app_context_ref`(weakref)로 접근.

### 스코프 추적 (`scoped_wildcard`)

`app_context.scoped_wildcard: str` — 스코프에 등록된 와일드카드 키 (최대 1개). 생성 시 해당 키의 선택값이 `HistoryItem.prompt_context['scoped_wildcard_history']`에 저장. ImageWindow에서 WC 관리 메뉴(복사/정제 추가/고정/제거) 제공.

---

## AutoCompleteManager (`autocomplete_manager.py`)

전역 이벤트 필터 기반 QLineEdit/QTextEdit 자동완성.

### `_get_active_token_info(widget)` 반환값

```python
{'text': str, 'stripped_text': str, 'prefix': str, 'suffix': str,
 'start': int, 'end': int, 'weight_prefix': str, 'weight_suffix': str,
 'is_weight_value': bool}
```

### 핵심 동작

- **NAI `::` 가중치 편집 시**: 자동완성 무시 (`is_weight_value=True`)
- **가중치 보존**: `0.7::art` → `artist:xxx` 선택 시 `0.7::artist:xxx` 유지
- **괄호 쌍 매칭**: 앞뒤 괄호가 쌍을 이루는 경우만 prefix/suffix로 분리
- **엔터 시 토큰 갱신**: `active_token_info`를 엔터 시점에 다시 가져옴 (200ms 타이머 불일치 방지)
- **팝업 외부 클릭**: 자동 닫기

### 자동완성 제외

```python
widget.setProperty("autocomplete_ignore", True)
# 기본 제외: "search_input", "exclude_input", "negative_prompt", "delay_input" 등
```

---

## 생성 큐 시스템

비동기 큐잉, 우선순위, 스레드 안전, 일시정지/재개.

**상세 레퍼런스**: [Generation Queue 가이드](.claude/GENERATION_QUEUE_CLAUDE.md)

## 자동생성-큐 핸드오프

큐가 비어있지 않으면 큐 우선, 비면 자동생성 재개. 플래그: `queue_hold_auto_gen`, `auto_retry_pending`.

**상세 레퍼런스**: [자동생성-큐 핸드오프 가이드](.claude/AUTO_GENERATION_HANDOFF_CLAUDE.md)

## 검색 결과 스냅샷 자동 복원 (`NAIA_cold_v4.py`)

`search_results` 소진 시 자동 생성 루프가 멈추지 않도록, 데이터 유입 시점에 메모리 스냅샷을 보관하고 소진 시 자동 복원.

**변수**: `self._search_results_snapshot: Optional[pd.DataFrame]`

**스냅샷 저장 시점** (`_save_search_snapshot()`):
- 일반 검색 완료 (`on_search_complete`)
- 불러오기 (`load_custom_parquet`)
- 합치기 (`merge_custom_parquet`)
- 심층검색 할당 (`on_depth_search_results_assigned`)

**자동 복원 시점** (`_restore_from_snapshot()`):
- `_check_and_trigger_auto_generation()`에서 `search_results.is_empty()` 감지 시
- `trigger_random_prompt()`에서 수동 랜덤 생성 시 `is_empty()` 감지 시

**휘발 조건**: 명시적 복원(`restore_search_results`) / 새 데이터 덮어쓰기 / 프로그램 종료

---

## UIStateManager (`ui_state_manager.py`)

프로그램 종료 시 UI 레이아웃을 `save/ui_state.json`에 저장하고, 시작 시 복원.

**저장 항목**:
- 창 위치/크기 (`saveGeometry`/`restoreGeometry`) + 최대화 상태
- 좌/우 패널 스플리터 비율
- 프롬프트 FixedBox 높이
- 생성 파라미터 패널 펼침/접힘
- 좌측 스크롤 위치
- 모듈 접기/펼치기 상태 (`MiddleSectionController`에 위임 → `save/module_states.json`)

**호출 시점**:
- 저장: `MainWindow.closeEvent()` → `ui_state_manager.save_state(self)`
- 복원: `MainWindow.__init__()` 말미 `QTimer.singleShot(150ms)` → `restore_state(self)`

---

## 주요 함정/주의사항

### QObject::killTimer 방지 (크로스 스레드)

- Background thread에서 Qt 객체 접근 금지
- UI 업데이트는 `pyqtSignal.emit()` → 메인 스레드 슬롯 (QTimer.singleShot 대신)
- 진행률 콜백: 시그널 emit만. UI 업데이트/이벤트 발행은 메인 스레드에서
- 워커가 필요한 UI 데이터: 스레드 시작 전 메인 스레드에서 캡처하여 전달
- ComfyUI: WebSocket 제거됨, 순수 HTTP 폴링 사용

### HTTP "Dummy" 스레드 누적 방지

모든 API 호출 후 `_cleanup_http_threads()` 호출 필수. `requests.Session` 어댑터 풀 정리 포함.

### 이벤트 미전달 디버깅

1. `initialize_with_context()`에서 구독했는지 확인
2. 이벤트 이름 대소문자 정확히 일치
3. 콜백 시그니처: 인자 1개 (`data: dict`)
