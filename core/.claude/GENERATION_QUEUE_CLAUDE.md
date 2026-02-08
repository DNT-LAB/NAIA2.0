# Generation Queue System - 상세 레퍼런스

> **상위 문서**: [core/CLAUDE.md](../CLAUDE.md)
> **목적**: Generation Queue 시스템의 상세 사용법, 시나리오, 문제 해결 가이드

---

## 목차

1. [개요](#개요)
2. [GenerationRequest 데이터 클래스](#generationrequest-데이터-클래스)
3. [GenerationQueueManager API](#generationqueuemanager-api)
4. [GenerationController 통합](#generationcontroller-통합)
5. [MainController UI 통합](#maincontroller-ui-통합)
6. [큐 이벤트 시스템](#큐-이벤트-시스템)
7. [사용 시나리오](#사용-시나리오)
8. [문제 해결](#문제-해결)
9. [콘솔 출력 예시](#콘솔-출력-예시)

---

## 개요

생성 큐 시스템은 이미지 생성 중에도 추가 요청을 큐에 저장하고, 순차적으로 처리할 수 있게 합니다.

**주요 특징**:
- 🚀 **비동기 큐잉**: 생성 중에도 버튼 활성 상태 유지, 클릭 시 큐에 추가
- 📊 **우선순위 지원**: 긴급 요청 (priority 100) vs 일반 요청 (priority 0)
- 🔒 **스레드 안전**: `threading.Lock`을 사용한 동기화
- ⏸️ **일시정지/재개**: 큐 처리를 일시적으로 중단 가능
- 🗑️ **큐 관리**: 비우기, 특정 요청 제거
- 📢 **이벤트 발행**: 큐 상태 변경 시 AppContext를 통해 알림

**파일**:
- `core/generation_request.py:1-135` - GenerationRequest 데이터 클래스
- `core/generation_queue_manager.py:1-288` - GenerationQueueManager
- `core/generation_controller.py:233-773` - GenerationController 통합

---

## GenerationRequest 데이터 클래스

**파일**: `core/generation_request.py:11-135`

### 구조

```python
from dataclasses import dataclass
from typing import Dict, Any, Optional
from datetime import datetime
import uuid
import pandas as pd

@dataclass
class GenerationRequest:
    # 필수 속성
    params: Dict[str, Any]              # 생성 파라미터
    source_row: pd.Series               # 소스 데이터

    # 자동 생성 속성
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.now)

    # 우선순위 및 상태
    priority: int = 0                   # 우선순위 (0=일반, 100=긴급)
    status: str = "pending"             # 상태: pending/processing/completed/failed

    # 재시도
    max_retries: int = 0                # 최대 재시도 횟수
    retry_count: int = 0                # 현재 재시도 횟수

    # 타임스탬프
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # 에러
    error_message: Optional[str] = None
```

### 상태 전환 메서드

#### 처리 시작

```python
request.mark_processing()
# → status: "pending" → "processing"
# → started_at: 현재 시간
```

#### 완료

```python
request.mark_completed()
# → status: "processing" → "completed"
# → completed_at: 현재 시간
```

#### 실패

```python
request.mark_failed("에러 메시지")
# → status: "processing" → "failed"
# → error_message: 에러 메시지
# → completed_at: 현재 시간
```

#### 재시도 가능 여부

```python
if request.can_retry():
    request.retry_count += 1
    request.mark_processing()  # 재시도 시작
```

### 유틸리티 메서드

#### 경과 시간

```python
elapsed = request.get_elapsed_time()
# → created_at부터 현재까지 경과 시간(초)
# → started_at 있으면 그 시점부터
```

#### 완료 여부

```python
is_done = request.is_done()
# → status가 "completed" 또는 "failed"인지 확인
```

---

## GenerationQueueManager API

**파일**: `core/generation_queue_manager.py:16-288`

### 초기화

```python
from core.generation_queue_manager import GenerationQueueManager

queue_manager = GenerationQueueManager(app_context)
```

### 큐에 요청 추가

#### 일반 추가 (큐 끝에)

```python
from core.generation_request import GenerationRequest

request = GenerationRequest(
    params={"input": "1girl, solo", ...},
    source_row=current_row,
    priority=0
)

request_id = queue_manager.enqueue_request(request)
# → 큐 끝에 추가
# → 이벤트 발행: "queue_request_enqueued"
```

#### 우선순위 추가 (우선순위에 따라 위치 결정)

```python
urgent_request = GenerationRequest(
    params={"input": "1girl, masterpiece", ...},
    source_row=current_row,
    priority=100  # 긴급
)

request_id = queue_manager.enqueue_with_priority(urgent_request)
# → 우선순위가 높은 요청은 큐 앞쪽에 삽입
# → 같은 우선순위는 순서대로 삽입
```

#### 우선순위 삽입 로직

```
큐: [P:50] [P:50] [P:10] [P:0] [P:0]
새 요청: P:30

1. P:50 확인 → 30 < 50, 계속
2. P:50 확인 → 30 < 50, 계속
3. P:10 확인 → 30 > 10, 여기에 삽입!

결과: [P:50] [P:50] [P:30] [P:10] [P:0] [P:0]
```

### 큐에서 요청 가져오기

```python
next_request = queue_manager.dequeue_request()

if next_request:
    # 요청 처리
    next_request.mark_processing()
    # ... API 호출 ...
else:
    # 큐가 비어있거나 일시정지 상태
    pass
```

**주의**:
- 일시정지 상태 (`_is_paused=True`)이면 `None` 반환
- 큐가 비어있으면 `None` 반환

### 큐 제어

#### 일시정지

```python
queue_manager.pause_queue()
# → 이후 dequeue_request()는 None 반환
# → 이벤트 발행: "queue_queue_paused"
```

#### 재개

```python
queue_manager.resume_queue()
# → dequeue_request() 정상 동작
# → 이벤트 발행: "queue_queue_resumed"
```

#### 큐 비우기

```python
queue_manager.clear_queue()
# → 모든 대기 요청 제거
# → 이벤트 발행: "queue_queue_cleared"
```

#### 특정 요청 제거

```python
success = queue_manager.remove_request(request_id)
# → True: 제거 성공, False: 찾을 수 없음
# → 이벤트 발행: "queue_request_removed"
```

### 큐 상태 조회

#### 큐 크기

```python
size = queue_manager.get_queue_size()
```

#### 일시정지 여부

```python
is_paused = queue_manager.is_paused()
```

#### 큐가 비어있는지

```python
is_empty = queue_manager.is_empty()
```

#### 다음 요청 미리보기

```python
next_req = queue_manager.peek_next_request()
# → 제거하지 않고 확인만
```

#### 모든 요청 목록

```python
all_requests = queue_manager.get_all_requests()
# → 복사본 반환 (원본 보호)
```

#### 통계 정보

```python
stats = queue_manager.get_queue_stats()
# → {
#     "total": 5,
#     "is_paused": False,
#     "priority_counts": {0: 3, 100: 2},
#     "has_urgent": True
# }
```

---

## GenerationController 통합

**파일**: `core/generation_controller.py:233-773`

### 초기화: 큐-자동생성 조정 플래그

```python
class GenerationController:
    def __init__(self, context: 'AppContext', module_instances: list):
        # ... 기존 코드 ...

        # 🆕 큐-자동생성 간 조정 플래그
        self.queue_hold_auto_gen = False  # 큐가 있는 동안 자동생성 보류
        self.auto_retry_pending = False   # 큐 때문에 보류된 자동재시도
```

**핵심 원리**:
- `queue_hold_auto_gen`: 큐가 비지 않으면 `True`, 자동생성/수동생성이 큐를 방해하지 않도록 함
- `auto_retry_pending`: 에러 발생 시 자동재시도를 큐 완료 후로 연기

### 생성 요청 시 큐 우선 처리

```python
def execute_generation_pipeline(self, overrides=None, priority=0, from_queue=False):
    """7단계 생성 파이프라인 실행"""

    # 1. 이미 생성 중인 경우 → 큐에 추가
    if self.is_generating and not from_queue:
        print(f"[QUEUE] 생성 중이므로 큐에 추가 (우선순위: {priority})")
        self._enqueue_current_request(overrides, priority)
        return

    # 2. 🆕 큐 우선: 대기 상태이고 큐가 있다면 큐를 먼저 처리
    try:
        queue_manager = self.context.generation_queue_manager
        if (not from_queue) and (not self.is_generating) \
            and (not queue_manager.is_empty()) and (not queue_manager.is_paused()):
            self.queue_hold_auto_gen = True
            self._update_button_with_queue_size()
            QTimer.singleShot(0, self._process_next_queue_request)
            return
    except Exception:
        pass

    # 3. 생성 시작
    # ...
```

**동작 순서**:
1. 생성 중 → 큐에 추가 (충돌 방지)
2. **대기 중 + 큐 존재 → 큐 우선 처리** (자동생성/수동생성 양보)
3. 큐 비어있음 → 정상 생성 시작

### 큐에 요청 추가

```python
def _enqueue_current_request(self, overrides, priority):
    """현재 설정으로 요청을 큐에 추가"""

    # 파라미터 수집
    params = self._collect_current_params(overrides)

    # 요청 생성
    request = GenerationRequest(
        params=params,
        source_row=self.context.current_source_row.copy(),
        priority=priority,
        max_retries=0
    )

    # 큐에 추가 (우선순위에 따라)
    queue_manager = self.context.generation_queue_manager
    queue_manager.enqueue_with_priority(request)

    # 버튼 텍스트 업데이트
    self._update_button_with_queue_size()
```

### 버튼 텍스트 자동 업데이트

```python
def _update_button_with_queue_size(self):
    """생성 버튼 텍스트를 큐 크기로 업데이트"""
    queue_manager = self.context.generation_queue_manager
    queue_size = queue_manager.get_queue_size()

    if self.is_generating:
        # 생성 중일 때
        if queue_size > 0:
            btn_text = f"🔄 생성 중... ({queue_size})"
        else:
            btn_text = "🔄 생성 중..."
    else:
        # 생성 중이 아닐 때
        if queue_size > 0:
            btn_text = f"🎨 이미지 생성 요청 ({queue_size})"
        else:
            btn_text = "🎨 이미지 생성 요청"

    self.context.main_window.generate_button_main.setText(btn_text)
    if hasattr(self.context.main_window, 'detached_generate_btn'):
        self.context.main_window.detached_generate_btn.setText(btn_text)
```

**버튼 텍스트 상태표**:

| 생성 상태 | 큐 크기 | 버튼 텍스트 |
|----------|---------|------------|
| 생성 중 | 0 | 🔄 생성 중... |
| 생성 중 | 2 | 🔄 생성 중... (2) |
| 대기 중 | 0 | 🎨 이미지 생성 요청 |
| 대기 중 | 1 | 🎨 이미지 생성 요청 (1) |
| 대기 중 | 5 | 🎨 이미지 생성 요청 (5) |

### 생성 완료 후 핸드오프

```python
def _on_generation_finished(self, result: dict):
    """생성 완료 시 큐 확인 및 다음 요청 처리"""

    # 성공 시 재시도 카운터 리셋
    self.auto_retry_count = 0

    # UI 업데이트
    self.context.main_window.update_ui_with_result(result)

    # 🆕 큐가 있으면 스레드 종료 시점까지 is_generating 유지
    # (자동생성이 끼어들지 못하도록 차단)
    queue_manager = self.context.generation_queue_manager
    if not queue_manager.is_empty() and not queue_manager.is_paused():
        print(f"[QUEUE] 생성 완료. 큐 우선 처리... (남은 큐: {queue_manager.get_queue_size()})")
        # 다음 요청 디스패치는 _on_thread_finished에서 수행
    else:
        # 큐가 비어있으면 정상 종료
        self._update_button_with_queue_size()
        print("[QUEUE] 큐 비어있음. 자동생성 즉시 가능.")
```

### 에러 발생 시 큐 우선 처리

```python
def _on_generation_error(self, error_message: str):
    """생성 오류 시 호출 - 큐 우선 처리"""

    print(f"❌ 생성 오류 발생: {error_message}")

    auto_generate_checkbox = self.context.main_window.generation_checkboxes.get("자동 생성")
    is_auto_generation = auto_generate_checkbox and auto_generate_checkbox.isChecked()

    queue_manager = self.context.generation_queue_manager
    has_queue = not queue_manager.is_empty() and not queue_manager.is_paused()

    if is_auto_generation and self.auto_retry_count < self.max_auto_retries:
        # 자동재시도 가능
        self.auto_retry_count += 1

        if has_queue:
            # 🆕 큐가 있으면 재시도 보류
            self.auto_retry_pending = True
            print("[QUEUE] 큐 우선. 자동 재시도 보류.")
        else:
            # 큐 없으면 즉시 재시도
            QTimer.singleShot(self.retry_delay_ms, self._retry_auto_generation)

    elif has_queue:
        # 🆕 재시도 불가 + 큐 존재 → 큐 우선 처리
        print(f"[QUEUE] 오류 발생. 큐 우선 처리... (남은 큐: {queue_manager.get_queue_size()})")
        # 스레드 종료 시점에 큐 디스패치 수행

    else:
        # 재시도도 안 하고 큐도 없으면 종료
        # UI 업데이트 및 버튼 활성화
        # ...
```

### 스레드 종료 시 핸드오프 결정

```python
def _on_thread_finished(self):
    """스레드 완료 시 정리 및 다음 작업 결정"""

    # 스레드 정리
    # ...

    # 🆕 is_generating 해제 및 핸드오프 결정
    try:
        self.is_generating = False

        queue_manager = self.context.generation_queue_manager
        has_queue = (not queue_manager.is_empty()) and (not queue_manager.is_paused())

        if has_queue:
            # 큐 우선 처리: 자동생성을 보류하고 다음 요청 즉시 디스패치
            self.queue_hold_auto_gen = True
            print(f"[QUEUE] 스레드 종료. 큐 디스패치 시작... (남은 큐: {queue_manager.get_queue_size()})")
            QTimer.singleShot(0, self._process_next_queue_request)
        else:
            # 큐가 비면 자동생성 보류 해제
            if self.queue_hold_auto_gen:
                print("[QUEUE] 큐 비었음. 자동생성 보류 해제.")
            self.queue_hold_auto_gen = False

            # 보류 중인 자동 재시도 수행
            if self.auto_retry_pending:
                self.auto_retry_pending = False
                print("[AUTO] 보류된 자동 재시도 실행.")
                QTimer.singleShot(0, self._retry_auto_generation)

        # UI 상태 업데이트
        self._update_button_with_queue_size()

    except Exception as _e:
        print(f"[GEN] thread-finish 후 디스패치 오류: {_e}")
```

**핵심 로직**:
1. **has_queue = True**: `queue_hold_auto_gen = True` → 큐 디스패치 → 자동생성 차단
2. **has_queue = False**: `queue_hold_auto_gen = False` → 보류된 재시도 실행 → 자동생성 허용

### 다음 요청 처리

```python
def _process_next_queue_request(self):
    """큐에서 다음 요청을 가져와 실행"""

    queue_manager = self.context.generation_queue_manager

    # 큐가 존재하는 동안 자동생성은 보류
    self.queue_hold_auto_gen = (not queue_manager.is_empty()) and (not queue_manager.is_paused())

    # 안전: 스레드 실행 중이면 대기
    if self.generation_thread and self.generation_thread.isRunning():
        print("[QUEUE] 이미 생성 중입니다. 디스패처 대기.")
        return

    # 안전: 이미 생성 중이면 대기
    if self.is_generating:
        print("[QUEUE] 이미 생성 중입니다. 디스패처 대기.")
        return

    if queue_manager.is_empty():
        print("[QUEUE] 큐가 비어있습니다. 대기 종료.")
        return

    # 다음 요청 가져오기
    next_request = queue_manager.dequeue_request()

    if not next_request:
        print("[QUEUE] 요청을 가져오지 못했습니다 (일시정지 상태일 수 있음)")
        return

    # 요청 처리 시작
    print(f"[QUEUE] 요청 가져옴: {next_request.request_id[:8]}...")
    next_request.mark_processing()

    # 소스 데이터 복원
    self.context.current_source_row = next_request.source_row

    # 생성 실행 (from_queue=True로 재귀 방지)
    self.execute_generation_pipeline(
        overrides=next_request.params,
        priority=next_request.priority,
        from_queue=True
    )
```

---

## MainController UI 통합

**파일**: `core/main_controller.py:249-362`

### 키보드 단축키

```python
def _setup_keyboard_shortcuts(self):
    """키보드 단축키 설정"""
    mw = self.main_window

    # Ctrl+Enter: 일반 생성 (우선순위 0)
    ctrl_enter = QShortcut(
        QKeySequence(Qt.Modifier.CTRL.value | Qt.Key.Key_Return.value),
        mw
    )
    ctrl_enter.activated.connect(lambda: self.trigger_generation(priority=0))

    # Shift+Enter: 긴급 생성 (우선순위 100)
    shift_enter = QShortcut(
        QKeySequence(Qt.Modifier.SHIFT.value | Qt.Key.Key_Return.value),
        mw
    )
    shift_enter.activated.connect(lambda: self.trigger_generation(priority=100))
```

**사용법**:
- **Ctrl+Enter**: 일반 생성 (큐 끝에 추가)
- **Shift+Enter**: 긴급 생성 (우선순위에 따라 앞쪽에 삽입)

### 우클릭 컨텍스트 메뉴

```python
def _show_queue_context_menu(self, position):
    """큐 관리 컨텍스트 메뉴 표시"""

    menu = QMenu(self.main_window)
    queue_manager = self.main_window.app_context.generation_queue_manager

    queue_size = queue_manager.get_queue_size()

    # 큐 상태 표시
    status_action = QAction(f"📊 대기 중: {queue_size}개", self.main_window)
    status_action.setEnabled(False)
    menu.addAction(status_action)

    menu.addSeparator()

    # 일시정지/재개
    if queue_manager.is_paused():
        pause_action = QAction("▶️ 큐 재개", self.main_window)
        pause_action.triggered.connect(queue_manager.resume_queue)
    else:
        pause_action = QAction("⏸️ 큐 일시정지", self.main_window)
        pause_action.triggered.connect(queue_manager.pause_queue)

    menu.addAction(pause_action)

    # 큐 비우기
    clear_action = QAction("🗑️ 큐 비우기", self.main_window)
    clear_action.triggered.connect(self._clear_queue_with_confirmation)
    clear_action.setEnabled(queue_size > 0)
    menu.addAction(clear_action)

    # 메뉴 표시
    menu.exec(self.main_window.generate_button_main.mapToGlobal(position))
```

**사용법**:
1. 생성 버튼 우클릭
2. 메뉴에서 선택:
   - **대기 중: N개**: 현재 큐 크기 표시 (비활성)
   - **⏸️ 큐 일시정지** / **▶️ 큐 재개**: 큐 처리 제어
   - **🗑️ 큐 비우기**: 모든 대기 요청 제거 (확인 대화상자)

---

## 큐 이벤트 시스템

GenerationQueueManager는 큐 상태 변경 시 다음 이벤트를 발행합니다:

| 이벤트 이름 | 데이터 구조 | 발행 시점 |
|------------|------------|----------|
| `queue_request_enqueued` | `{"request_id": str, "priority": int, "queue_size": int, "position": int}` | 요청 추가 시 |
| `queue_request_dequeued` | `{"request_id": str, "priority": int, "queue_size": int}` | 요청 가져올 시 |
| `queue_request_removed` | `{"request_id": str, "queue_size": int}` | 요청 제거 시 |
| `queue_queue_paused` | `{"queue_size": int}` | 일시정지 시 |
| `queue_queue_resumed` | `{"queue_size": int}` | 재개 시 |
| `queue_queue_cleared` | `{"cleared_count": int}` | 큐 비우기 시 |

### 이벤트 구독 예시

```python
def initialize_with_context(self, app_context):
    self.app_context = app_context

    # 큐 이벤트 구독
    app_context.subscribe("queue_request_enqueued", self._on_queue_updated)
    app_context.subscribe("queue_request_dequeued", self._on_queue_updated)

def _on_queue_updated(self, data: dict):
    queue_size = data.get("queue_size", 0)
    print(f"큐 업데이트: {queue_size}개 대기 중")
```

---

## 사용 시나리오

### 시나리오 1: 일반 사용 (연속 생성)

```
사용자 액션:
1. 생성 버튼 클릭 (또는 Ctrl+Enter)
   → 생성 시작, 버튼 텍스트: "생성 중..."

2. 생성 중에 다시 버튼 클릭
   → 큐에 추가 (우선순위 0), 버튼 텍스트: "생성 중... (1)"

3. 또 클릭
   → 큐에 추가, 버튼 텍스트: "생성 중... (2)"

결과:
- 첫 번째 생성 완료
- 500ms 후 큐의 첫 번째 요청 자동 처리
- 두 번째 생성 완료
- 500ms 후 큐의 두 번째 요청 자동 처리
- 모두 완료
```

### 시나리오 2: 긴급 요청 추가

```
사용자 액션:
1. 일반 생성 3회 추가 (Ctrl+Enter x3)
   → 큐: [P:0] [P:0] [P:0]

2. 긴급 요청 추가 (Shift+Enter)
   → 큐: [P:100] [P:0] [P:0] [P:0]

결과:
- 긴급 요청이 큐 앞쪽에 삽입됨
- 현재 생성 완료 후 긴급 요청 먼저 처리
```

### 시나리오 3: 큐 일시정지

```
사용자 액션:
1. 생성 중에 요청 5개 큐에 추가
   → 큐: [P:0] [P:0] [P:0] [P:0] [P:0]

2. 생성 버튼 우클릭 → "⏸️ 큐 일시정지"
   → 큐 일시정지

3. 현재 생성 완료
   → 다음 큐 처리 안 함 (일시정지 상태)

4. 생성 버튼 우클릭 → "▶️ 큐 재개"
   → 다음 요청 자동 처리 시작
```

### 시나리오 4: 자동 생성과 큐

```
상황:
- "자동 생성" 체크박스 활성화
- 생성 중에 수동으로 버튼 클릭

동작:
1. 자동 생성으로 이미지 생성 중
2. 사용자가 버튼 클릭 → 큐에 추가
3. 자동 생성 완료
4. 큐에 요청이 있으므로 큐 먼저 처리
5. 큐 비워진 후 자동 생성 재개

→ 큐가 자동 생성보다 우선순위가 높음
```

### 시나리오 5: 히스토리에서 큐에 추가

```
사용자 액션:
1. 생성된 이미지 히스토리 목록에서 우클릭
2. "⬆️ 큐 앞에 추가" 또는 "⬇️ 큐 뒤에 추가" 선택

동작:
- 해당 이미지의 generation_params를 사용하여 GenerationRequest 생성
- 현재 UI 설정 반영:
  - "랜덤 해상도" 체크 시 → 무작위 해상도로 덮어쓰기
  - "시드 고정" 체크 OFF 시 → 무작위 시드 생성 (0~9999999999)
- 우선순위에 따라 큐에 추가
  - "큐 앞에 추가": priority=100 (긴급)
  - "큐 뒤에 추가": priority=0 (일반)
- 상태바 피드백: "✅ 큐 뒤에 추가됨 (대기 중: 1)"
- 버튼 텍스트 자동 업데이트: "🎨 이미지 생성 요청 (1)"

결과:
- 동일한 설정으로 이미지를 다시 생성할 수 있음
- 랜덤 옵션 적용으로 변형 생성 가능
- generation_params가 없는 이미지는 버튼 비활성화됨
```

**주의사항**:
- NovelAI API는 음수 시드를 받지 않음 (`seed: -1` → HTTP 400 오류)
- 무작위 시드는 0~9999999999 범위의 양수 정수 생성
- `extra_noise_seed`도 동일한 값으로 설정해야 함

---

## 문제 해결

### Q1: 큐에 추가되지 않아요

**증상**: 생성 중에 버튼 클릭 시 큐에 추가되지 않음

**원인**:
- `is_generating` 플래그가 False
- `from_queue` 파라미터가 True

**해결**:
```python
# GenerationController에서
def execute_generation_pipeline(self, overrides=None, priority=0, from_queue=False):
    # ✅ from_queue=False일 때만 큐에 추가
    if self.is_generating and not from_queue:
        self._enqueue_current_request(overrides, priority)
        return
```

### Q2: 큐가 자동으로 처리되지 않아요

**증상**: 생성 완료 후 큐에 요청이 있지만 처리되지 않음

**원인**:
- `_on_generation_finished()`에서 큐 처리 로직 누락
- 큐가 일시정지 상태

**해결**:
```python
def _on_generation_finished(self, result: dict):
    # ...

    # ✅ 큐 확인 및 처리
    queue_manager = self.context.generation_queue_manager

    if not queue_manager.is_empty():
        QTimer.singleShot(500, self._process_next_queue_request)
```

### Q3: 우선순위가 작동하지 않아요

**증상**: 긴급 요청이 일반 요청보다 나중에 처리됨

**원인**:
- `enqueue_request()` 사용 (우선순위 무시)
- 우선순위 값이 잘못됨

**해결**:
```python
# ❌ 잘못된 방법
queue_manager.enqueue_request(request)  # 항상 큐 끝에 추가

# ✅ 올바른 방법
queue_manager.enqueue_with_priority(request)  # 우선순위에 따라 삽입
```

---

## 콘솔 출력 예시

```
[QUEUE] 생성 중이므로 요청을 큐에 추가합니다 (우선순위: 0)
[QUEUE] 일반 요청 추가: a3b4c5d6... (위치: 2, 큐 크기: 3)
🚀 이벤트 발행: 'queue_request_enqueued' (구독자: 0개)

[QUEUE] 요청 가져옴: a3b4c5d6... (남은 큐: 2)
🚀 이벤트 발행: 'queue_request_dequeued' (구독자: 0개)

[QUEUE] 생성 완료. 다음 요청 처리 중... (남은 큐: 2)

[QUEUE] 요청 가져옴: b4c5d6e7... (남은 큐: 1)
[QUEUE] 생성 완료. 다음 요청 처리 중... (남은 큐: 1)

[QUEUE] 요청 가져옴: c5d6e7f8... (남은 큐: 0)
[QUEUE] 모든 생성 완료. 큐가 비어있습니다.

[QUEUE] ⏸️ 큐 일시정지 (대기 중: 5)
[QUEUE] ▶️ 큐 재개 (대기 중: 5)
[QUEUE] 🗑️ 큐 비우기 완료: 5개 요청 제거됨
```

---

*문서 버전: 1.0*
*최종 업데이트: 2025-01-18*
*상위 문서: [core/CLAUDE.md](../CLAUDE.md)*
