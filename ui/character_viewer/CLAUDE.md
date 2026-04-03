# CLAUDE.md — ui/character_viewer/

> **목적**: 캐릭터 분석 데이터 뷰어 + 프롬프트 생성 + 썸네일 관리 윈도우.

---

## 파일 구조

```
ui/character_viewer/
├── __init__.py                      # CharacterViewerWindow export
└── character_viewer_window.py       # 메인 윈도우 (~1520줄)
```

## 데이터 의존

| 파일 | 위치 | 용도 |
|------|------|------|
| `copyright_groups.json` | `data/` | 작품별 캐릭터 그룹 |
| `character_analysis.json` | `data/` | 캐릭터별 PC/CH/Alternate 분석 |
| `character_thumbnails/` | `data/` | 생성 썸네일 JPEG + `index.json` |
| `character_viewer_tags.json` | `save/` | Prefix/Postfix 태그 저장 |

## 레이아웃

QSplitter 3-panel: `[Groups] | [Characters] | [Characters Grid / Detail]`

- **Left**: 작품 그룹 리스트 (검색 + All 포함)
- **Middle**: 캐릭터 리스트 (이름 + 태그 검색, 350ms 디바운스)
- **Right**: QTabWidget 2탭
  - **Characters**: 4×3 그리드 (썸네일 cover 모드, 페이지네이션, 썸네일 우선 정렬)
  - **Detail**: (PC/CH/Attire 트리 + 프리뷰) / (프롬프트 + 컨트롤)

## 시그널

| 시그널 | 타입 | 용도 |
|--------|------|------|
| `window_closed` | `()` | 메인 윈도우에 닫힘 통보 |
| `apply_to_main_prompt` | `(dict)` | Send to Main → 메인 프롬프트 전송 |

## 생성 경로

| 버튼 | 동작 |
|------|------|
| **Copy** | prompt_edit 클립보드 복사 |
| **Send to Main** | `apply_to_main_prompt` emit → `on_instant_generation_requested` |
| **Generate** | overrides로 직접 생성 (메인 프롬프트 미변경), 896×1152 고정 |

## 연속 생성

- `[연속 생성]` 체크 시 생성 완료 후 자동으로 다음 캐릭터 생성
- `[빈 썸네일만]` 체크 시 이미 썸네일이 있는 캐릭터 스킵
- 딜레이: AutomationModule의 `get_generation_delay()` 반영 (기본 500ms)
- `automation_stopped` 이벤트 구독 → 자동화 중단 시 연속 생성 해제

## 썸네일 시스템

- 개별 JPEG 파일 + `index.json` (경량 인덱스)
- 원본 → max 416×608 리사이즈, JPEG quality 85
- 그리드: `KeepAspectRatioByExpanding` + 1/3 상단 기준 크롭 (캐릭터 얼굴 가시성)

## NAIA 메인 윈도우 통합

| 위치 | 변경 |
|------|------|
| `extra_features_menu` | Character Viewer 메뉴 액션 |
| `_display_generated_image()` | `character_viewer_request` → `generation_completed_for_character_viewer` 발행 |
| `generation_controller.py` | `_on_generation_error()`에 CV 에러 라우팅 |

## 주요 규칙

1. **그리드 피드백 루프 방지**: `grid_container`에 `QSizePolicy.Ignored` + `cell.setFixedSize()`
2. **SEGFAULT 방지**: `_preview_qimage` 참조 유지 (GC 방지)
3. **검색 false match 방지**: `breast_size.distribution`에서 최빈 태그만 검색 문자열에 포함
4. **closeEvent**: `_unsubscribe_generation()` + `automation_stopped` 구독 해제 필수
