# ui/remote_web/ — NAIA Remote Web Session

브라우저에서 NAIA 2.0 원격 제어. FastAPI + WebSocket 실시간 통신.

## 활성화

세 가지 경로 — 모두 같은 `start_remote_server()` 진입:

1. **CLI**: `python NAIA_cold_v4.py --web-session` (런처: `run_NAIA_web.bat` / `run_NAIA_web.command`) — 부팅 5초 후 서버 기동 + 기본 브라우저 자동 오픈
2. **Settings 영속화**: `Settings > Web Session > 자동 시작` 체크 — `app_settings.json` 에 저장, 다음 실행부터 (1)과 동일 동작
3. **수동**: `Settings > Web Session` 체크박스 토글

CLI 플래그는 `os.environ['NAIA_CLI_WEB_SESSION']` 로 배관되어 `SettingsTabModule.on_initialize()` 가 읽음 (`__init__` 내부에서 동기 실행되어 `app_context` 속성 주입 타이밍이 맞지 않음).

## 파일 구조

```
ui/remote_web/
├── index.html    # HTML 구조 (셸)
├── style.css     # CSS (모바일/PC 반응형, 768px 브레이크포인트)
└── app.js        # JS (WebSocket, 파라미터 동기화, 히스토리, 모듈, autocomplete)
```

서버: `core/remote_api_server.py` (RemoteBridge, WebSocketManager, FastAPI 라우트)

## 스레드 안전

- FastAPI → Qt: `pyqtSignal.emit()` + `QueuedConnection`
- Qt → asyncio: `asyncio.run_coroutine_threadsafe()`
- **FastAPI에서 Qt 위젯 직접 접근 금지** → `_cached_*` 딕셔너리 사용
- 에코 방지: 서버 `_syncing_*` / JS `syncingParams` 등
- 디바운스: 프롬프트 500ms, 파라미터 300ms, 모듈 텍스트 500ms

## 시그널 연결

**lambda 금지** — 메서드 참조만 사용 (disconnect 가능해야 함).
글로벌 추적: `_checkbox_connections`, `_param_signal_sources`

## 정적 파일 서빙

catch-all 라우트 금지 (API/WS 충돌). 명시적 경로:
```python
@app.get("/"), @app.get("/style.css"), @app.get("/app.js")
```
새 파일 추가 시 `create_app()`에 라우트 추가.

---

## PC/모바일 레이아웃

### PC (≥768px): CSS Grid

```
body {
  display: grid;
  grid-template-columns: 480px 1fr;
  grid-template-rows: auto 1fr;
}
```

- `header` → grid-column: 1 (좌측 컬럼에만 표시)
- `.app-layout` → `display: contents` (wrapper dissolve)
- `.control-panel` → grid-column: 1, grid-row: 2
- `.viewer-wrapper` → grid-column: 2, grid-row: 1 / -1 (전체 높이)

### 모바일 (<768px): Flex column (기존)

- body: `display: flex; flex-direction: column`
- drawer 토글 + 하단 컨트롤

---

## Autocomplete + Tag Tooltip 시스템

### 아키텍처

```
textarea input → getActiveTokenInfo() → scheduleAutocomplete()
  → WS autocomplete → 5단계 검색 (서버) → autocomplete_result
  → renderAutocomplete() → tag-tooltip (클릭 가능)

textarea click/keyup → checkTagHint() → WS tag_lookup
  → _lookup_tag_info (서버) → tag_lookup_result
  → onTagLookupResult() → tag-tooltip (info + related)
```

### `bindTagAssist(textarea)` — 범용 바인딩

autocomplete + hint + keyboard nav + IME 가드를 어떤 textarea에든 바인딩.
`acTarget`이 현재 활성 textarea를 추적.

**적용 위치:**
- `promptEdit` (init 시)
- `renderPromptEngineering()` 후 `modPrePrompt`, `modPostPrompt`
- `renderCharacter()` 후 character prompt textarea (`.mod-textarea:not(.mod-uc)`)
- **제외**: conditional prompt, negative prompt, auto-hide

### 데이터 소스 (`_kr_tags_raw`, ~17만 태그)

| _src | 소스 | 우선순위 |
|------|------|---------|
| 0 | interactive JSON (16,698) | 최우선 (relations, desc, keywords_kr) |
| 1 | KR_tags.parquet (~17K) | interactive에 없을 때 |
| 2 | e621_KR_tags.parquet (~5.4K) | 위 둘에 없을 때 |
| 3-10 | Filter lists (8개) | 그룹 소속만 |
| 11-13 | artist/character/copyright dicts (~129K) | 이름+freq만 |

### 카테고리 컬러 (`CAT_COLORS`)

| _cat | 색상 | 용도 |
|------|------|------|
| artist | `#d4736a` | 아티스트 태그 |
| character | `#6abf7b` | 캐릭터 태그 |
| copyright | `#a87fd4` | 저작권/시리즈 |
| e621 | `#d4c36a` | e621 전용 태그 |

### Prefix 라우팅

`artist:ciloranko` → artist cat만 검색, `character:hatsune` → character만 검색

### NAI 구문 보존 (`swapToken`)

선택 시 현재 토큰의 weight/bracket 구조 보존:
- `0.7::tag` → `0.7::newTag`
- `(tag:1.2)` → `(newTag:1.2)`

### Related/Implies 태그 클릭

related/implies 태그 클릭 → 현재 토큰 뒤에 `, {tag}` 삽입

### WS 프로토콜

| 방향 | type | 데이터 |
|------|------|--------|
| Client→Server | `autocomplete` | `{query}` |
| Server→Client | `autocomplete_result` | `{query, results: [{tag, count, desc, group, cat}]}` |
| Client→Server | `tag_lookup` | `{tag}` |
| Server→Client | `tag_lookup_result` | `{tag, count, desc, group, subgroup, cat, implications?, related?}` |

---

## NAI 가중치 구문 하이라이트

메인 프롬프트 전용. NAI 모드에서만 활성화.

- `weight::content::` 파싱 → weight < 1.0 파란색, > 1.0 빨간색, `::` 녹색
- 오버레이 패턴: `.prompt-highlight-wrap` > `.prompt-highlight` + `.prompt-edit`
- `formatNaiHighlight()` — regex `(-?\d+(?:\.\d+)?)(::)([\s\S]*?)(::)` lazy 매칭
- `syncPromptHighlight()` — 스크롤 동기화
- NAI 모드 전환: `setNaiHighlightMode(mode)` (syncMode에서 호출)
- NAI 모드에서 textarea `resize: none` (오버레이 정렬 보호)

### 조건부 프롬프트 하이라이트

- `#` 주석 라인 회색 음영 → `.cond-rules-wrap` 오버레이 패턴
- `formatCondRules()` + `syncCondScroll()` 동기화

---

## 모듈 원격 제어 시스템

NAIA 메인 앱의 모듈을 웹 플로팅 패널로 제어. **오버레이 없음 (UI 잠금 없음)**.

### WS 프로토콜

| 방향 | type | 데이터 |
|------|------|--------|
| Client→Server | `get_module_state` | `{module_id}` |
| Client→Server | `set_module_param` | `{module_id, key, value}` |
| Server→Client | `module_state` | `{module_id, ...전체 상태}` |

### 구현된 모듈

| module_id | 클래스 | 주요 위젯 |
|-----------|--------|----------|
| `prompt_engineering` | `PromptEngineeringModule` | preset, pre/post prompt, auto-hide, 전처리 체크박스 15개 |
| `automation` | `AutomationModule` | delay, random delay, repeat, 종료조건(radio 3개), start/stop |
| `character` | `CharacterModule` | activate, reroll_on_generate, 캐릭터별 prompt/uc |
| `conditional_prompt` | `PromptListModifierModule` | enable, rules (# 하이라이트), test, log |
| `character_reference` | `CharacterReferenceModule` | 이미지 업로드, Storage, Enable/RefType/Strength/Fidelity per frame, NAID4.5 전용 |
| `vibe_transfer` | `VibeTransferModule` | 이미지 업로드, Storage(모델별 탭), Enable/RefStrength/InfoExtracted per frame, Encode(2 Anlas), Normalize |
| `wildcard` | `WildcardStatusModule` | 히스토리, 순차 상태, prompt_squeeze, Manager(파일 브라우저/에디터/생성기) |
| `chunk` | (InstantWildcardModule via _read_chunk) | 인스턴트 와일드카드 트리 브라우저 → 커서 삽입. `$`/`@` 트리거 |

### 이미지 모듈 특수 패턴

- **이미지 업로드**: JS `uploadModuleImage()` → FileReader → 클라이언트 리사이즈(max 2048px) → base64 → `set_module_param(id, 'upload_image', base64)` → 서버 temp 파일 저장 → `_add_*_frame()`
- **Storage**: `set_module_param(id, 'get_storage', '')` → 서버 `_scan_*_storage()` → `storage_list` 메시지 → JS `onStorageList()` → 그리드 표시 → 클릭 시 `apply_storage`
- **썸네일**: `_generate_thumbnail_b64()` — PIL 128px JPEG quality 70 → base64 (~3-8KB/장)
- **슬라이더 디바운스**: `onModSlider()` — 300ms debounce로 WS 메시지 폭주 방지
- **상호 배타**: NAI에서 Char Ref ↔ Vibe Transfer 동시 사용 불가. enable 시 반대쪽 전체 disable + 양쪽 브로드캐스트
- **stealth_mode**: `_set_character_reference` / `_set_vibe_transfer` 전체를 `stealth_mode = True`로 감싸 QMessageBox 억제
- **뱃지**: 활성 프레임 수 표시. Char Ref 보라(#a87fd4), Vibe 주황(#d4a06a)

### 새 모듈 추가 절차 (3단계)

**1. 서버 (`core/remote_api_server.py`)** — `class_map` 등록 + read/set 함수
**2. 웹 HTML (`index.html`)** — 모듈 바에 버튼 추가
**3. 웹 JS (`app.js`)** — titles맵 + onModuleState 분기 + render 함수 + `bindTagAssist()` (필요 시)

### 위젯 타입별 패턴

| 위젯 | 읽기 (서버) | 쓰기 (서버) | HTML (웹) |
|------|------------|------------|-----------|
| QTextEdit | `.toPlainText()` | `.setPlainText(v)` | `<textarea oninput="onModTextEdit(...)">` |
| QCheckBox | `.isChecked()` | `.setChecked(v=="true")` | `<input type="checkbox" onchange="setModuleParam(...)">` |
| QComboBox | `.currentText()` + items | `.findText(v)` → `.setCurrentIndex()` | `<select onchange="setModuleParam(...)">` |
| QSpinBox | `.value()` | `.setValue(int/float(v))` | `<input type="number" onchange="setModuleParam(...)">` |
| QRadioButton | `.isChecked()` | `.setChecked(True)` | `<input type="radio" onchange="...">` |

---

## 검색 시스템

- `Prompt: {count}` 녹색 버튼 → 플로팅 검색 패널
- Search/Exclude Keyword, Rating 필터, Custom Parquets 로드, Restore

## 히스토리 시스템

- Remote WebSocket: 현재 생성 이미지와 메타데이터 broadcast만 담당
- 데스크톱 히스토리/액션: `tabs/image_window.py`의 `HistoryItem` + `ImageHistoryWindow` 모델을 기준으로 구현
- Load Prompt / Reroll / Queue 계열 액션은 Remote 전용 WebSocket 명령이 아니라 데스크톱 모델 어댑터가 필요
- Shared Mode: 호스트 전역 히스토리 변경 액션은 차단

## 단축키

- `Ctrl+Enter` → Generate, `Alt+Enter` → Random

### NAI 전용 모듈 모드 차단

- `syncMode()`: 비NAI 모드에서 Char Ref/Vibe 버튼에 `nai-only-disabled` 클래스 (opacity 0.35 + pointer-events none)
- `openModule()`: 비NAI 모드에서 클릭 시 toast 에러 + 차단
- HTML 기본값: `nai-only-disabled` 클래스 적용 → `syncMode()`에서 NAI면 해제

### 와일드카드 관리자 (WC → Browse Files)

- 파일 트리 브라우저 (폴더 접이식) + 파일 에디터 (읽기/편집/저장/삭제)
- Quick Add Entry (텍스트 추가) + 5회 랜덤 프리뷰
- 새 파일 생성, 구문 가이드 (Normal/Sequential/Dependent)
- 서버: `_scan_wildcard_tree()`, `_validate_wildcard_path()` (경로 탈출 방지), CRUD 함수
- `.txt` 파일만 허용, `.is_file()` 검증

### Chunk 모듈 (인스턴트 와일드카드 삽입)

- `$` 입력 시 별도 floating panel 자동 오픈 (트리거 위치 `chunkTriggerInfo` 기억)
- 모듈 바 "Chunk" 버튼으로도 별도 패널 접근 가능
- 아코디언 방식: 한 번에 하나의 그룹만 열림
- 아이템 클릭 → 값 전체가 커서 위치에 삽입 (트리거 문자 교체 또는 `, ` 삽입)
- 패널 종료 시 `chunkTriggerInfo` 초기화

### Autocomplete 와일드카드 검색

- `__keyword` 입력 → `autocomplete_wildcard` WS 타입 → `_search_wildcards()` → `__name__` 형태로 삽입
- wildcard 결과 청록색 (`#6ac4d4`), `__name__` prefix/suffix 표시

### 태그 괄호 이스케이프 (모드별)

- 모든 소스에서 `\(` → `(`, `\)` → `)` 정규화하여 중복 방지
- autocomplete 삽입 시: NAI 모드 → 그대로, WEBUI/ComfyUI → `(` → `\(` 역변환

### 조건부 프롬프트 `#` 주석

- `formatCondRules()`: 콤마 구분 엔트리별 `#` 감지 (따옴표 내 콤마 무시)
- `<span class="cond-comment">` 로 개별 엔트리 래핑

---

## Shared Server Mode (다중 사용자 독립 세션)

Settings > Web Session > "Shared Server Mode" 체크 시 활성화. 비영속 (앱 재시작 시 OFF).

### 세션 격리 대상

| 항목 | 저장 위치 | 주입 시점 |
|------|-----------|----------|
| P.Engineering (pre/post/auto-hide/전처리) | `session["p_eng_override"]` | `_inject_session_overrides()` → `app_context.session_p_eng_override` |
| Conditional Prompt (enabled/rules) | `session["cond_override"]` | `_inject_session_overrides()` → `app_context.session_cond_override` |
| Negative Prompt | `session["negative_prompt"]` | `_do_generate` / `on_prompt_generated` |
| 생성 파라미터 (해상도/스텝/CFG 등) | `session["params_override"]` | `execute_generation_pipeline(overrides=)` |
| Prompt Fixed / WC Solo | `session["options"]` | `_get_session_settings_override()` → `trigger_random_prompt(settings_override=)` |

### 1-time 초기화 패턴

세션의 override가 `None`이면 최초 1회만 데스크톱에서 복사(Copy P.Eng/Cond 체크 시) 또는 빈 dict로 초기화. 이후 세션이 소유.

### 차단 항목 (Shared Mode)

| 항목 | 클라이언트 | 서버 |
|------|-----------|------|
| Auto Gen | checkbox disabled | `set_option("auto_generate")` 무시 |
| NAI 모드 전환 | option disabled | `_do_set_mode("NAI")` 차단 |
| Automation / Wildcard / Chunk / Search | 버튼 `nai-only-disabled` | 모듈 진입 차단 |
| 검색 / Depth / Restore / Load Parquet | — | 서버 요청 무시 |
| `__` / `$` / `@` autocomplete 트리거 | `scheduleAutocomplete` 가드 | — |
| 히스토리 Delete | 버튼 disabled | — |

### WS별 Pending Overrides

`_do_random()` → `prompt_generated` → 자동생성 경로에서 비동기 간극 발생.
`_pending_overrides: dict[ws, {"params", "negative", "settings_override"}]`로 WS별 격리.

### Override Cleanup

- `_on_generation_finished` / `_on_generation_error`: `session_p_eng_override` / `session_cond_override` = None
- `_on_thread_finished`: 안전망 (cancel 시 위 콜백 누락 대비)
- WS disconnect: `_current_request_ws` 무효화 + pending 제거 + `_auto_generate_pending` 해제

### UI 미조작 원칙

세션별 옵션(WC Solo 등)은 `settings_override` dict로 전달. **데스크톱 UI 체크박스를 임시 조작하지 않음**.

---

## 히스토리 액션

- WebSocket에는 Remote 전용 히스토리 액션 명령을 두지 않는다.
- Load Prompt / Reroll / Queue Front·Back / Restore Params는 데스크톱 `ImageWindow`의 `HistoryItem` 기반 액션을 기준으로 확장한다.
- Remote에서 같은 기능을 노출해야 할 경우 서버 임시 버퍼를 만들지 말고 데스크톱 히스토리 모델을 읽는 어댑터를 추가한다.

## 생성 Progress Bar

- `startProgress()` / `finishProgress()`: 최근 5회 평균 기반 예측
- 100% 초과 시 주황색 2nd bar (`genProgressBar2`)
- interval/timeout 누적 방지: `_progressFinishTimeout` 추적

---

## 주요 함정

1. 모드 전환은 `toggle_search_mode()` 사용
2. boolean 직렬화: JS `String(this.checked)` → Python `value == "true"`
3. `stealth_mode`: 원격 depth action / character_reference / vibe_transfer 시 QMessageBox 억제
4. `generation_worker`는 매 생성마다 재생성 → 직접 시그널 연결 불가
5. 생성 결과 시 프롬프트 텍스트 덮어쓰기 금지
6. `btnGen.innerHTML` 사용 — `textContent`는 shortcut-hint span 파괴
7. SMEA/DYN 토글: `disabled` 클래스 가드 필수
8. Params → Quick flags 양방향 동기화
9. 한글 IME: `compositionstart`/`compositionend` 이벤트 처리 필수
10. relations 필드: str/list 혼재 → `isinstance` 가드 필수
11. `bindTagAssist()`: 모듈 렌더링 후 호출 (innerHTML 교체로 리스너 자동 GC)
12. `_fireModuleOninput(el)`: 동적 textarea의 oninput 핸들러 프로그래밍 실행
13. `escHtml()`: `'`/`"` 포함 이스케이프 (onclick attribute 인젝션 방지)
14. wildcard CRUD: `.txt` 전용 + `_validate_wildcard_path()` 경로 탈출 방지
15. `chunkTriggerInfo`: 모듈 닫힐 때 반드시 null 초기화 (stale 삽입 방지)
16. 태그 괄호 정규화: 모든 소스 `\(` → `(` 통일, 비NAI 삽입 시 역변환
