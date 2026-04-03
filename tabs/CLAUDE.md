# CLAUDE.md — tabs/

> **목적**: NAIA 2.0의 우측 탭 모듈 개발 가이드. TabController를 통한 동적 로딩, RightView 통합, core/closable 타입, 통신 패턴.

---

## 아키텍처

```
RightView (ui/right_view.py)
    ↓ owns
EnhancedTabWidget (QTabWidget)
    ↓ managed by
TabController (core/tab_controller.py)
    ↓ loads
tabs/*.py (BaseTabModule subclasses)
```

**로딩 흐름**:
1. `TabController._load_tab_modules()` → glob `tabs/*.py` → BaseTabModule 서브클래스 발견
2. `TabController.initialize_tabs()` → `get_tab_type() == 'core'`만 자동 로드, `get_tab_order()` 정렬
3. RightView 시그널 브리징 → MainWindow로 전달

**의존 관계**:
```
tabs/
  ├── interfaces/base_tab_module.py를 상속
  ├── core/tab_controller.py에 의해 관리
  ├── ui/right_view.py에 표시
  └── core/context.py (AppContext) 주입받음
```

---

## 주요 파일

### 탭 모듈

| 파일 | 타입 | 주요 기능 |
|------|------|----------|
| **image_window.py** | core | 이미지 뷰어, 히스토리, 큐 추가, Img2Img 윈도우 연동 |
| **png_info_tab.py** | core | PNG/JPEG/WebP 메타데이터 파싱, Stealth PNG |
| **setting_tabs.py** | core | 자동완성, 저장 경로, 분류 규칙, 모듈/탭 가시성, UI 스케일 |
| **studio_tab.py** | core | 다중 프레임 그리드, 순차 생성, 프리셋 (상세: [studio/CLAUDE.md](studio/CLAUDE.md)) |
| **turbo_event_sequence/** | core | 터보 이벤트 시퀀스 (상세: [turbo_event_sequence/CLAUDE.md](turbo_event_sequence/CLAUDE.md)) |
| **assets_tab.py** | closable | rembg 통합, 배경 제거 |
| **web_view.py** | closable | Danbooru 브라우저, 태그 추출 |
| **artist_thumb_tab.py** | closable | 아티스트 갤러리 (4x2 그리드), 관심 작가 토글 |
| **character_prompt_editor.py** | closable | 캐릭터별 프롬프트 관리 |

### 관련 시스템 파일

| 파일 | 역할 |
|------|------|
| `interfaces/base_tab_module.py` | 탭 계약 정의 (ABC) |
| `core/tab_controller.py` | 탭 로딩 및 생명주기 관리 |
| `ui/right_view.py` | 탭 컨테이너 및 이벤트 브리지 |
| `ui/detached_window.py` | 탭 분리 창 관리 |

---

## 탭 타입: core vs closable

| 특성 | core | closable |
|------|------|----------|
| **로딩 시점** | 시작 시 자동 | 사용자 요청 시 |
| **닫기 버튼** | 없음 | 있음 |
| **사용 예** | 항상 필요한 기능 | 선택적 기능 |

**closable 탭 동적 추가**:
```python
self.image_window.tab_controller.add_tab_by_name('Img2ImgTabModule')
img2img_tab = self.image_window.tab_controller.get_tab_instance('Img2ImgTabModule')
```

---

## 탭 통신 패턴

### 패턴 1: 시그널 → RightView 브리징 → MainWindow

탭에서 `parameters_extracted.emit(params)` → RightView에서 브리징 연결 → MainWindow에서 수신.

```python
# ui/right_view.py
png_info_module.parameters_extracted.connect(self._relay_parameters)
```

### 패턴 2: AppContext 이벤트 버스

```python
# 발행
self.app_context.publish("autocomplete_toggled", {"enabled": checked})

# 구독
app_context.subscribe("autocomplete_toggled", self._on_autocomplete_changed)
```

### 패턴 비교

| 패턴 | 사용 시기 |
|------|----------|
| **시그널 직접 연결** | 특정 탭 <-> MainWindow |
| **AppContext 이벤트** | 전역 알림, 다대다 통신 |
| **MainWindow 직접 참조** | 사용 금지 (레거시) |

---

## 주의사항 및 함정

### 탭이 로드되지 않을 때

- 파일명이 `*_module.py` 패턴이 아닌 경우 (예: `tabs/my_tab.py` 는 로드 안 됨)
- `BaseTabModule`을 상속하지 않은 경우
- `get_tab_type() == 'closable'`인데 수동 추가하지 않은 경우

### AppContext가 None

`__init__`에서 `app_context` 접근 불가. `initialize_with_context()` 또는 `on_initialize()`에서 접근.

### 시그널 연결 안 될 때

RightView 브리징 코드가 누락되었는지 확인. 탭 시그널은 자동으로 MainWindow에 전달되지 않음.

### 모듈/탭 가시성 시작 시 미적용

`update_ui_from_settings`에서 `QTimer.singleShot(200, self._apply_saved_module_visibility)` 호출 필요. 컨트롤러 준비 대기를 위한 재시도 메커니즘(최대 3회) 구현.

### 메모리 누수 방지

`cleanup()`에서 타이머 정지, QThread 종료, 위젯 deleteLater 호출 필수.

---

## Img2Img 윈도우 연동 (image_window.py)

`show_img2img_popup()`에서 `current_history_item`을 확인하여 독립 Img2ImgWindow에 전달. 이전 생성의 캐릭터 프롬프트가 새 윈도우에서도 유지됨.

```python
history_item = self.current_history_item
if history_item and hasattr(main_window, 'img2img_window_manager'):
    popup.img2img_requested.connect(
        lambda img, hi=history_item: main_window.img2img_window_manager.create_window(
            img, mode='img2img', history_item=hi
        )
    )
```

---

## 히스토리 큐 추가 기능 (image_window.py)

히스토리 이미지 우클릭 → 큐 앞/뒤에 추가. `generation_params`가 없는 이미지는 메뉴 자동 비활성화.

**주의사항**:
```python
# NovelAI API는 음수 시드 불가 → 0~9999999999 범위로 생성
random_seed = random.randint(0, 9999999999)
params['seed'] = random_seed
params['extra_noise_seed'] = random_seed

# random_resolution 플래그 추가하면 중복 처리 발생 → 해상도 직접 덮어쓰기
params['width'] = width
params['height'] = height
```

---

## 관련 문서

- [core/CLAUDE.md](../core/CLAUDE.md) - TabController, AppContext
- [ui/CLAUDE.md](../ui/CLAUDE.md) - RightView, 테마, 스케일링
- [interfaces/CLAUDE.md](../interfaces/CLAUDE.md) - BaseTabModule 계약
- [studio/CLAUDE.md](studio/CLAUDE.md) - Studio Tab 전용 가이드
- [turbo_event_sequence/CLAUDE.md](turbo_event_sequence/CLAUDE.md) - Turbo Event Sequence 탭 가이드

---

## 예제 코드 위치

| 예제 | 파일 |
|------|------|
| 최소 탭 구현 | `tabs/img2img_tab.py` |
| QThread 워커 | `tabs/png_info_tab.py` |
| WebEngine 설정 | `tabs/web_view.py` |
| 설정 영속성 | `tabs/setting_tabs.py` |
| 큐 추가 기능 | `tabs/image_window.py:591-663` |

**상세 예제/튜토리얼**: [.claude/examples_CLAUDE.md](.claude/examples_CLAUDE.md), [.claude/tutorials_CLAUDE.md](.claude/tutorials_CLAUDE.md), [.claude/advanced_patterns_CLAUDE.md](.claude/advanced_patterns_CLAUDE.md)
