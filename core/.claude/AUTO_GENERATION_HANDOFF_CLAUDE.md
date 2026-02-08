# 자동생성-큐 핸드오프 시스템 - 상세 레퍼런스

> **상위 문서**: [core/CLAUDE.md](../CLAUDE.md)
> **목적**: 자동생성 모드와 큐 시스템의 상호작용, 핸드오프 메커니즘 상세 가이드

---

## 목차

1. [개요](#개요)
2. [핵심 원칙](#핵심-원칙)
3. [NAIA_cold_v4.py: 자동생성 트리거](#naia_cold_v4py-자동생성-트리거)
4. [GenerationController: 큐-자동생성 조정](#generationcontroller-큐-자동생성-조정)
5. [전체 흐름도](#전체-흐름도)
6. [검증 시나리오](#검증-시나리오)
7. [문제 해결](#문제-해결)

---

## 개요

자동생성 모드와 수동 큐 시스템이 동시에 동작할 때, **큐 우선 처리** 원칙으로 핸드오프를 수행합니다.

**참조 문서**: `docs/AUTOGEN_QUEUE_HANDOFF_PLAN.md`

### 핵심 원칙

1. **큐가 비어있지 않으면** → 큐 우선 처리, 자동생성 대기
2. **큐가 비면** → 자동생성 재개, 보류된 재시도 실행
3. **UI 피드백** → 버튼 상태로 현재 상태 표시

### 주요 컴포넌트

| 컴포넌트 | 역할 | 주요 플래그 |
|---------|------|-----------|
| **NAIA_cold_v4.py** | 자동생성 트리거 | - |
| **GenerationController** | 큐-자동생성 조정 | `queue_hold_auto_gen`, `auto_retry_pending` |
| **GenerationQueueManager** | 큐 상태 관리 | `is_paused`, `is_empty()` |

---

## 핵심 원칙

### 원칙 1: 큐 우선 처리

```
[생성 요청]
    ↓
큐에 요청 있음? ──Yes──→ 큐 먼저 처리, 자동생성 보류
    No
    ↓
자동생성 실행
```

### 원칙 2: 큐 완료 후 자동생성 재개

```
[큐 처리 완료]
    ↓
큐 비어있음? ──Yes──→ 자동생성 보류 해제
    No                   ↓
    ↓                보류된 재시도 실행
큐 계속 처리             ↓
                     자동생성 사이클 재개
```

### 원칙 3: UI 피드백

버튼 텍스트와 상태바로 현재 상태를 명확히 표시:

| 상황 | 버튼 텍스트 | 상태바 메시지 |
|------|-----------|-------------|
| 큐 처리 중 | 🎨 이미지 생성 요청 (3) | "큐 처리 중... 자동생성 대기" |
| 자동생성 중 | 🔄 생성 중... | "자동 생성 중..." |
| 대기 중 | 🎨 이미지 생성 요청 | "" |

---

## NAIA_cold_v4.py: 자동생성 트리거

**파일**: `NAIA_cold_v4.py:2104-2120`

### 자동생성 조건 체크

```python
def _check_and_trigger_auto_generation(self):
    """자동 생성 조건을 확인하고 조건이 만족되면 다음 사이클을 시작"""

    auto_generate_checkbox = self.generation_checkboxes.get("자동 생성")
    prompt_fixed_checkbox = self.generation_checkboxes.get("프롬프트 고정")

    if not auto_generate_checkbox.isChecked():
        return  # 자동 생성 체크박스가 없으면 종료

    try:
        # 🆕 [큐 우선] 큐가 비어있지 않으면 큐 처리가 끝날 때까지 자동생성 대기
        if hasattr(self, 'app_context') and self.app_context:
            queue_manager = self.app_context.generation_queue_manager
            if queue_manager and not queue_manager.is_empty() and not queue_manager.is_paused():
                self.status_bar.showMessage("큐 처리 중... 자동생성 대기")
                QTimer.singleShot(500, self._check_and_trigger_auto_generation)
                return

        # 이후 기존 체크 (is_generating, thread.isRunning, 반복 생성 중 등)
        # ...
    except Exception as e:
        print(f"❌ 자동 생성 트리거 오류: {e}")
```

**동작 순서**:
1. **큐 상태 확인** (최우선)
2. 큐가 있으면 → 500ms 후 재시도, 상태바 메시지 표시
3. 큐 없으면 → 기존 조건 체크 (`is_generating`, 스레드 상태 등)

### 랜덤 프롬프트 버튼 상태 관리

**파일**: `NAIA_cold_v4.py:3642-3677`

```python
def update_random_prompt_button_state(self):
    """generation_checkboxes 상태에 따라 random_prompt_btn을 활성화/비활성화"""

    try:
        # "프롬프트 고정" 체크박스 확인
        prompt_fixed_checkbox = self.generation_checkboxes.get("프롬프트 고정")
        prompt_fixed = prompt_fixed_checkbox and prompt_fixed_checkbox.isChecked()

        if prompt_fixed:
            # 프롬프트 고정 모드
            self.random_prompt_btn.setEnabled(False)
            self.random_prompt_btn.setText("프롬프트 고정됨")
            # detached_random_btn도 동기화
        else:
            # 일반 모드 (활성화)
            self.random_prompt_btn.setEnabled(True)
            self.random_prompt_btn.setText("랜덤/다음 프롬프트")

    except Exception as e:
        print(f"❌ 버튼 상태 업데이트 오류: {e}")
```

**우선순위**:
1. **프롬프트 고정** → "프롬프트 고정됨" + 비활성화
2. **일반 모드** → "랜덤/다음 프롬프트" + 활성화

**참고**: 큐 처리 중에도 프롬프트 생성 가능 (스레드 안전성 검증 완료)

### 큐 이벤트 구독

**파일**: `NAIA_cold_v4.py:575-581`

```python
# AppContext 초기화 시점 (self.app_context 생성 후)

# 큐 이벤트 구독 - 상태 동기화
for queue_event in [
    "queue_request_enqueued", "queue_request_dequeued",
    "queue_queue_paused", "queue_queue_resumed",
    "queue_queue_cleared", "queue_request_removed"
]:
    self.app_context.subscribe(queue_event, lambda _=None: self.update_random_prompt_button_state())
```

**효과**:
- 큐 상태가 변경될 때마다 UI 동기화
- 현재는 프롬프트 고정 상태만 체크 (큐 상태는 버튼 제한 없음)

---

## GenerationController: 큐-자동생성 조정

**파일**: `core/generation_controller.py:233-773`

### 조정 플래그

```python
class GenerationController:
    def __init__(self, context: 'AppContext', module_instances: list):
        # ... 기존 코드 ...

        # 🆕 큐-자동생성 간 조정 플래그
        self.queue_hold_auto_gen = False  # 큐가 있는 동안 자동생성 보류
        self.auto_retry_pending = False   # 큐 때문에 보류된 자동재시도
```

#### `queue_hold_auto_gen`

**목적**: 큐가 비어있지 않을 때 자동생성을 보류

**설정 시점**:
- `execute_generation_pipeline()`: 큐 발견 시 `True`
- `_on_thread_finished()`: 큐 발견 시 `True`, 큐 비면 `False`

**사용 위치**:
- `_check_and_trigger_auto_generation()` (NAIA_cold_v4.py): 자동생성 트리거 전 체크

#### `auto_retry_pending`

**목적**: 에러 발생 시 자동재시도를 큐 완료 후로 연기

**설정 시점**:
- `_on_generation_error()`: 큐 있고 재시도 가능 시 `True`
- `_retry_auto_generation()`: 큐 있으면 `True`
- `_on_thread_finished()`: 큐 비고 플래그 True이면 재시도 실행 후 `False`

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

**핵심 로직**:
- 대기 중 + 큐 존재 → `queue_hold_auto_gen = True` → 큐 디스패치
- 이후 자동생성 요청은 `_check_and_trigger_auto_generation()`에서 차단됨

### 자동재시도 시 큐 체크

```python
def _retry_auto_generation(self):
    """자동 생성 재시도 실행"""

    try:
        # 🆕 큐가 존재하면 재시도를 보류하고 큐를 먼저 처리
        queue_manager = self.context.generation_queue_manager
        if (not queue_manager.is_empty()) and (not queue_manager.is_paused()):
            self.auto_retry_pending = True
            self.queue_hold_auto_gen = True
            print("[QUEUE] 큐 우선. 자동 재시도 보류.")
            QTimer.singleShot(0, self._process_next_queue_request)
            return

        # 자동 생성이 여전히 활성화되어 있는지 확인
        auto_generate_checkbox = self.context.main_window.generation_checkboxes.get("자동 생성")
        if not (auto_generate_checkbox and auto_generate_checkbox.isChecked()):
            print("⚠️ 자동 생성이 비활성화되어 재시도를 중단합니다.")
            self.auto_retry_count = 0
            return

        # 재시도 실행
        # ...
    except Exception as e:
        print(f"❌ 자동 재시도 중 오류: {e}")
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

**동작 순서**:
1. 자동재시도 가능 + 큐 존재 → 재시도 보류 (`auto_retry_pending = True`)
2. 자동재시도 불가 + 큐 존재 → 큐 우선 처리
3. 큐 없음 → 정상 에러 처리

### 스레드 종료 시 핸드오프 결정

```python
def _on_thread_finished(self):
    """스레드 완료 시 정리 및 다음 작업 결정"""

    # 스레드 정리
    def _cleanup():
        try:
            if self.generation_thread:
                self.generation_thread.wait(50)
        except Exception:
            pass
        finally:
            self.generation_thread = None
            self.generation_worker = None
            _force_cleanup_all_threads()

    _cleanup()

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

---

## 전체 흐름도

```
사용자 액션
    ↓
[자동생성 ON]           [수동 생성 버튼 클릭]
    ↓                        ↓
_check_and_trigger    execute_generation_pipeline
    ↓                        ↓
    └─────[큐 체크]──────────┘
              ↓
    큐 비어있음?  ──No──→ 큐 우선 처리
              Yes               ↓
              ↓            큐 요청 실행
         정상 생성              ↓
              ↓            생성 완료
              ↓                 ↓
         생성 완료         큐 남았음?
              ↓                Yes ──→ 다음 큐 처리
         큐 있음?               No
              Yes                ↓
              ↓            자동생성 재개
         큐 처리               (queue_hold_auto_gen = False)
              No
              ↓
         자동생성 계속
```

---

## 검증 시나리오

### 시나리오 1: 자동생성 ON + 사용자 클릭 2회

```
1. 자동생성 활성화 상태
2. 사용자가 "생성" 버튼 2회 연속 클릭
3. 첫 요청 → 즉시 실행
4. 둘째 요청 → 큐에 추가 (is_generating = True)
5. 첫 요청 완료 → 스레드 종료
6. _on_thread_finished → 큐 발견 → queue_hold_auto_gen = True
7. 다음 큐 요청 처리 (자동생성 차단)
8. 둘째 요청 완료 → 큐 비어있음
9. queue_hold_auto_gen = False → 자동생성 재개
```

**예상 결과**:
- ✅ 두 요청 모두 처리됨
- ✅ 큐가 비기 전까지 자동생성 대기
- ✅ 큐 완료 후 자동생성 즉시 재개

### 시나리오 2: 에러 발생 + 자동재시도 ON + 큐 존재

```
1. 자동생성 중 에러 발생
2. auto_retry_count < max_auto_retries (재시도 가능)
3. 큐 체크 → has_queue = True
4. auto_retry_pending = True (재시도 보류)
5. 큐 처리 시작
6. 큐 완료 → _on_thread_finished
7. has_queue = False → auto_retry_pending = True 감지
8. _retry_auto_generation 실행 (보류된 재시도)
```

**예상 결과**:
- ✅ 큐 우선 처리
- ✅ 큐 완료 후 자동재시도 실행
- ✅ 재시도 카운트 유지

### 시나리오 3: 자동생성 중 큐 추가

```
상황:
- 자동생성 활성화
- 생성 중에 사용자가 수동 버튼 클릭 2회

동작:
1. 자동생성 첫 번째 이미지 생성 중
2. 사용자 클릭 → 큐에 추가 (요청 1)
3. 사용자 다시 클릭 → 큐에 추가 (요청 2)
4. 자동생성 완료 → _on_thread_finished
5. has_queue = True → queue_hold_auto_gen = True
6. 큐 요청 1 처리
7. 완료 → 큐 요청 2 처리
8. 완료 → 큐 비어있음
9. queue_hold_auto_gen = False → 자동생성 재개
```

**예상 결과**:
- ✅ 자동생성 일시 중단
- ✅ 큐 완전 처리 후 재개
- ✅ 충돌 없음

---

## 문제 해결

### Q1: 큐가 있는데 자동생성이 계속 실행됨

**원인**: `_check_and_trigger_auto_generation`에서 큐 체크 누락

**확인**:
```python
# NAIA_cold_v4.py:2114-2120
if hasattr(self, 'app_context') and self.app_context:
    queue_manager = self.app_context.generation_queue_manager
    if queue_manager and not queue_manager.is_empty() and not queue_manager.is_paused():
        # 큐가 있으면 대기해야 함
        self.status_bar.showMessage("큐 처리 중... 자동생성 대기")
        QTimer.singleShot(500, self._check_and_trigger_auto_generation)
        return
```

**해결**:
- 큐 체크 로직이 자동생성 트리거 최상단에 있는지 확인
- 큐 존재 시 500ms 후 재시도 로직 확인

### Q2: 큐 완료 후 자동재시도가 실행되지 않음

**원인**: `auto_retry_pending` 플래그가 해제되지 않음

**확인**:
```python
# generation_controller.py:1682-1685 (_on_thread_finished)
if has_queue == False:
    if self.auto_retry_pending:
        self.auto_retry_pending = False  # ← 반드시 False로 설정
        QTimer.singleShot(0, self._retry_auto_generation)
```

**해결**:
- `_on_thread_finished`에서 `auto_retry_pending` 체크 및 해제 확인
- 재시도 실행 로그 확인 (`[AUTO] 보류된 자동 재시도 실행.`)

### Q3: 자동생성이 큐를 무시하고 끼어듬

**원인**: `queue_hold_auto_gen` 플래그가 제대로 설정/체크되지 않음

**확인**:
```python
# generation_controller.py:_on_thread_finished
if has_queue:
    self.queue_hold_auto_gen = True  # ← 확인
    QTimer.singleShot(0, self._process_next_queue_request)
else:
    self.queue_hold_auto_gen = False  # ← 확인
```

**해결**:
- 스레드 종료 시 `queue_hold_auto_gen` 설정 확인
- 자동생성 트리거에서 이 플래그 체크 여부 확인 (NAIA_cold_v4.py)

---

*문서 버전: 1.0*
*최종 업데이트: 2025-01-18*
*상위 문서: [core/CLAUDE.md](../CLAUDE.md)*
