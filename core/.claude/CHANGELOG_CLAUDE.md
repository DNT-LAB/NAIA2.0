# core/ 변경사항 로그

> **상위 문서**: [core/CLAUDE.md](../CLAUDE.md)
> **목적**: core/ 디렉터리 변경사항 상세 이력

---

## 버전 1.8 (2025-01-21)

### 버그 수정

- 🐛 **Settings 탭 크래시 수정** ([tabs/setting_tabs.py:1015](../../tabs/setting_tabs.py#L1015))
  - **문제**: 분류 방법을 "프롬프트 인식"에서 "분류 없음"으로 변경 시 `AttributeError`로 프로그램 강제 종료
  - **원인**: 잘못된 속성명 참조 (`self.secondary_classification_method_label` → 존재하지 않음)
  - **해결**: 올바른 속성명 사용 (`self.secondary_classification_label`)
  - **영향**: 분류 방법 전환이 정상 작동, 사용자가 설정을 자유롭게 변경 가능
  - **관련 문서**: [tabs/CLAUDE.md Q7](../../tabs/CLAUDE.md#q7-분류-방법-변경-시-프로그램이-강제-종료돼요-settings-탭)

---

## 버전 1.7 (2025-01-18)

### 문서 구조 개선

- **레퍼런스 문서 분리**: Generation Queue, 자동생성-큐 핸드오프를 `.claude/` 폴더로 이동
  - [GENERATION_QUEUE_CLAUDE.md](.claude/GENERATION_QUEUE_CLAUDE.md)
  - [AUTO_GENERATION_HANDOFF_CLAUDE.md](.claude/AUTO_GENERATION_HANDOFF_CLAUDE.md)
- **문서 압축**: core/CLAUDE.md를 3,214줄 → ~1,785줄로 감축

---

## 버전 1.6 (2025-01-15)

### 히스토리 큐 추가 기능 개선

- **랜덤 해상도 옵션 적용**: 체크 시 무작위 해상도로 덮어쓰기
- **시드 고정 옵션 적용**: OFF 시 양수 무작위 시드 생성 (0~9999999999)
- **NovelAI API 음수 시드 오류 해결**: `seed=-1` → HTTP 400 방지
- **버튼 텍스트 자동 업데이트**: "🎨 이미지 생성 요청 (N)"
- **큐 이벤트 구독 시 `_update_button_with_queue_size()` 호출**
- **상태바 피드백 개선**: 큐 크기 표시

### 자동생성-큐 핸드오프 시스템

- **GenerationController 조정 플래그**:
  - `queue_hold_auto_gen`: 큐가 있는 동안 자동생성 보류
  - `auto_retry_pending`: 큐 때문에 보류된 자동재시도
- **큐 우선 처리 로직**: `execute_generation_pipeline`, `_on_thread_finished`
- **NAIA_cold_v4.py 자동생성 트리거 및 UI 통합**

---

## 버전 1.5 (2025-01-14)

### Sequence Generation Feature 구현

- **SequenceParser 모듈**: `:begin`, `:seq`, `:end` 구문 파싱 및 검증
- **GenerationController**: 시퀀스 감지 분기 및 일괄 큐 추가
- **NAI 모드 랜덤 시드 처리**: 각 시퀀스마다 다른 시드
- **WEBUI/COMFYUI**: 고정 시드 사용 (일관된 변화)
- **seed: 및 resolution: 태그 지원**
- **테스트**: 68개 유닛 테스트 + 62개 통합 테스트 (100% 통과)

---

## 버전 1.4 (2025-01-11)

### Generation Queue System 구현

- **GenerationRequest 데이터 클래스**: 요청 추적, 상태 관리
- **GenerationQueueManager**: 스레드 안전 큐, 우선순위 지원
- **GenerationController 통합**: 자동 큐 처리
- **MainController UI 통합**: 키보드 단축키 (Ctrl+Enter, Shift+Enter), 컨텍스트 메뉴
- **큐 이벤트 시스템**: `request_enqueued`, `request_dequeued`, `queue_paused` 등

---

## 버전 1.3 (2025-01-10)

### MiddleSectionController 개선

- **모듈 상태 추적 및 아코디언 동작**:
  - 모듈 펼침/접힘/분리 상태 추적
  - 스크롤 위치 자동 저장/복원
  - 아코디언 모드 (하나만 펼치기)
  - 자동 스크롤 (모듈로 이동)
  - 상태 영속성 (`save/module_states.json`)

---

## 버전 1.2 (2025-01-09)

### ImageCrudController 기능 추가

- **이미지 저장 로직 중앙화**
- **파일명 형식 지원**: `number_only`, `time_number`, `datetime`
- **프롬프트 기반 분류 시스템**: `prompt_recognition`, 논리 연산자 지원 (`&`, `|`, `*`)
- **타임스탬프 폴더 토글**: 선택적 날짜_시간 폴더 사용
- **2차 분류 시스템**: 계층적 폴더 구조 지원 (primary/secondary 경로)
- **카운터 재시작 시 1로 초기화 정책 적용**
- **설정 영속성**: `app_settings.json`에 모든 설정 저장/로드

---

## 이전 버전

상세한 이전 변경사항은 Git 커밋 히스토리를 참조하세요.

---

*문서 버전: 1.0*
*최종 업데이트: 2025-01-18*
*상위 문서: [core/CLAUDE.md](../CLAUDE.md)*
