# ui/remote_web/ — NAIA Remote Web Session

브라우저에서 NAIA 2.0 원격 제어. FastAPI + WebSocket 실시간 통신.

## 파일 구조

```
ui/remote_web/
├── index.html    # HTML 구조 (셸)
├── style.css     # CSS (모바일/PC 반응형, 768px 브레이크포인트)
└── app.js        # JS (WebSocket, 파라미터 동기화, 히스토리, 모듈, 검색)
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

### 새 모듈 추가 절차 (3단계)

**1. 서버 (`core/remote_api_server.py`)**

`_find_module()`의 `class_map`에 등록:
```python
class_map = {
    "prompt_engineering": "PromptEngineeringModule",
    "automation": "AutomationModule",
    "character": "CharacterModule",
    "new_id": "NewModuleClassName",  # 추가
}
```

`_read_module_state()`에 분기 + 읽기 함수 추가.
`_do_set_module()`에 분기 + 쓰기 함수 추가.

**2. 웹 HTML (`index.html`)** — 모듈 바에 버튼 추가:
```html
<button class="module-btn" data-module="new_id" onclick="openModule('new_id')">New Module</button>
```

**3. 웹 JS (`app.js`)** — titles 맵 + onModuleState 분기 + render 함수:
```javascript
// openModule()의 titles에 추가
// onModuleState()에 분기 추가
function renderNewModule(m) { moduleBody.innerHTML = `...`; }
```

### 위젯 타입별 패턴

| 위젯 | 읽기 (서버) | 쓰기 (서버) | HTML (웹) |
|------|------------|------------|-----------|
| QTextEdit | `.toPlainText()` | `.setPlainText(v)` | `<textarea oninput="onModTextEdit(...)">` |
| QCheckBox | `.isChecked()` | `.setChecked(v=="true")` | `<input type="checkbox" onchange="setModuleParam(...)">` |
| QComboBox | `.currentText()` + items | `.findText(v)` → `.setCurrentIndex()` | `<select onchange="setModuleParam(...)">` |
| QSpinBox | `.value()` | `.setValue(int/float(v))` | `<input type="number" onchange="setModuleParam(...)">` |
| QRadioButton | `.isChecked()` | `.setChecked(True)` | `<input type="radio" onchange="...">` |

### 전처리 체크박스 (prompt_engineering)

key에 `pp_` 접두사 → 서버에서 `option_key_map` 역참조.

### 자동화 모듈 (automation)

radio 변경 시 `lastAutoState` 캐시 + 즉시 re-render (서버 왕복 없이 조건부 필드 표시).

### textarea XSS 방지

`escHtml()` 함수로 모든 textarea 내용 escape. `</textarea>` 공격 방지.

---

## 검색 시스템

### WS 프로토콜

| 방향 | type | 데이터 |
|------|------|--------|
| Client→Server | `get_search_state` | (없음) |
| Client→Server | `search` | `{query, exclude, rating_e/q/s/g}` |
| Client→Server | `load_parquet` | `{filename}` |
| Client→Server | `restore_snapshot` | (없음) |
| Server→Client | `search_state` | `{count, query, exclude, ratings, parquets}` |
| Server→Client | `search_progress` | `{completed, total}` |

### 검색 패널 (module-bar의 녹색 버튼)

- `Prompt: {count}` 버튼 → 플로팅 패널
- Remaining count + Restore 버튼
- Search Keyword / Exclude Keyword 입력
- Rating 필터 (Explicit, NSFW, Sensitive, General)
- Custom Parquets 목록 (save/custom_tags/ 폴더) → 클릭으로 로드
- 검색 진행률 실시간 표시

### 카운트 자동 갱신

- `prompt_generated` 이벤트에 `remaining` 필드 포함
- WS 연결 시 자동으로 `get_search_state` 요청

---

## 히스토리 시스템

- 서버: `_image_history: list[(webp_bytes, metadata)]` 최대 200장 버퍼
- 새로고침 시 전체 히스토리 복원 (WS 연결 시 순서대로 전송)
- 히스토리 패널: 뷰어 오른쪽 inline (열면 뷰어가 줄어듦, 오버레이 없음)
- 패널 열기 시 현재 이미지 자동 포커스 + Save/Delete 즉시 표시
- `◀ Save Delete ▶` 플로팅 네비게이션
- **Reached 200 액션**: Never mind (oldest 제거) / Stop (추가 중단) / Save-all-clear (zip 저장→클리어)
- `historySaving` 플래그: save-all-clear 비동기 중 race condition 방지

## UI 구조 (모바일)

```
[Header: NAIA-REMOTE  Provided by CLAUDE | NAI ▼ | CONNECTED ●]
[Viewer (패딩 0, 라운드 없음) | History Panel (inline)]
[▲ PROMPT / PARAMS / MODULES ▲  ← 열면 연보라+흰색 반전]
[bottom-controls: 옵션 + 해상도 + 버튼 통합, gap 4px 균일]
```

## 단축키

- `Ctrl+Enter` → Generate (PC에서 버튼에 힌트 표시, 모바일 숨김)
- `Alt+Enter` → Random

## 주요 함정

1. 모드 전환은 `toggle_search_mode()` 사용 (`set_api_mode()`만으론 토큰 전환 안됨)
2. boolean 직렬화: JS `String(this.checked)` → Python `value == "true"` (소문자)
3. `populateSelect`: 옵션 개수뿐 아니라 값도 비교
4. `stealth_mode`: 원격 모드 전환 시 QMessageBox.critical 억제
5. 모듈 인스턴스: `middle_section_controller.module_instances` (`.modules` 아님)
6. `generation_worker`는 매 생성마다 재생성 → 직접 시그널 연결 불가, AppContext 이벤트 사용
7. 하단 컨트롤은 `.bottom-controls` 하나로 통합 (분리하면 간격 불일치)
8. 생성 결과 시 프롬프트 텍스트 덮어쓰기 금지 (사용자 주석/줄바꿈 보존)
9. `btnGen.innerHTML` 사용 — `textContent`는 shortcut-hint span 파괴
10. SMEA/DYN 토글: `disabled` 클래스 가드 필수 (NAID3 외 모드)
11. Params 탭 flags → Quick flags 양방향 동기화 (`toggleFlag`에서 `qRndRes`/`qAutoRes` 토글)
