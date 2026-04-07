# ui/remote_web/ — NAIA Remote Web Session

브라우저에서 NAIA 2.0 원격 제어. FastAPI + WebSocket 실시간 통신.

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

- 서버: `_image_history` 200장 버퍼, JSZip zip 다운로드
- 패널: 뷰어 오른쪽 inline, `◀ Save Delete ▶` 네비게이션

## 단축키

- `Ctrl+Enter` → Generate, `Alt+Enter` → Random

## 주요 함정

1. 모드 전환은 `toggle_search_mode()` 사용
2. boolean 직렬화: JS `String(this.checked)` → Python `value == "true"`
3. `stealth_mode`: 원격 depth action 시 QMessageBox 억제
4. `generation_worker`는 매 생성마다 재생성 → 직접 시그널 연결 불가
5. 생성 결과 시 프롬프트 텍스트 덮어쓰기 금지
6. `btnGen.innerHTML` 사용 — `textContent`는 shortcut-hint span 파괴
7. SMEA/DYN 토글: `disabled` 클래스 가드 필수
8. Params → Quick flags 양방향 동기화
9. 한글 IME: `compositionstart`/`compositionend` 이벤트 처리 필수
10. relations 필드: str/list 혼재 → `isinstance` 가드 필수
11. `bindTagAssist()`: 모듈 렌더링 후 호출 (innerHTML 교체로 리스너 자동 GC)
12. `_fireModuleOninput(el)`: 동적 textarea의 oninput 핸들러 프로그래밍 실행
