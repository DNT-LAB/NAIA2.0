# CLAUDE.md — ui/event_preset/

> **목적**: Danbooru 이벤트 택소노미 브라우저 + 멀티 이벤트 콤보 프롬프트 생성기. 385MB ZIP 데이터셋(`naia_prompt_preset`)을 기반으로 이벤트 탐색, 공기 태그 추천, 이미지 생성 파이프라인 연동을 제공한다.

**레퍼런스 문서**:
- [Full Mode 가이드](.claude/FULL_MODE_CLAUDE.md) — Quick Search 기반 raw 콤보 확장, allowlist 필터링, 다운로드 유도

---

## 파일 구조

```
ui/event_preset/
├── __init__.py                 # EventPresetWindow export
├── event_preset_window.py      # 메인 QMainWindow (~1780줄)
├── data_manager.py             # ZIP I/O + 에셋 로딩 + 파티션 캐시 (~310줄)
├── download_worker.py          # HuggingFace 다운로드 + 프로그레스 (~240줄)
├── engines.py                  # 비즈니스 로직 4개 엔진 (~860줄)
├── widgets.py                  # 커스텀 위젯 7개 (~820줄)
├── viewer_multi.py             # [참고용] 독립 뷰어 원본 (~3500줄)
└── naia_prompt_preset/         # [다운로드] 385MB ZIP 데이터
```

---

## 아키텍처

```
DataManager (ZIP I/O)
    ↓ load_base_assets / load_partition_data
TaxonomyEngine (인덱싱, 트리 프로젝션, 검색)
    ↓
StagingEngine (이벤트 스테이징, 콤보 교차)
    ↓
RecommendationEngine (공기 태그 쿼리/병합, 칩 상태)
    ↓
PromptBuilder (person + rating + events + deps + recs → 프롬프트)
    ↓
EventPresetWindow (3-panel UI, 생성 파이프라인 연동)
    └─ Widgets (FlowLayout, 칩, 델리게이트, 프리뷰)
```

---

## 핵심 파일별 요약

### `event_preset_window.py` — 메인 윈도우

**레이아웃**: QSplitter (2:3:5 비율)

| 패널 | 내용 |
|------|------|
| **LEFT** | 파티션 셀렉터 (Rating 토글 + Character 콤보 + 검색) → Subgroup 트리 → Event 리스트 |
| **CENTER** | QTabWidget 4탭 (Observed Combos / Expression / Clothing / Characteristic) |
| **RIGHT** | ImagePreviewWidget + StagingBar + RecommendedTagsPanel + Prompt QTextEdit + 버튼 행 |

**시그널**:
| 시그널 | 타입 | 용도 |
|--------|------|------|
| `window_closed` | `()` | 메인 윈도우에 닫힘 통보 |
| `apply_to_main_prompt` | `(dict)` | `on_instant_generation_requested` 경유 메인 프롬프트 전송 |

**3가지 생성 경로**:

| 버튼 | 경로 | 메인 프롬프트 |
|------|------|-------------|
| **Generate** | `generate_instant_source_silent` → `execute_generation_pipeline(input=...)` | 변경 안 함 |
| **메인 프롬프트에 전송** | `apply_to_main_prompt` emit → `on_instant_generation_requested` (파이프라인 경유) | 풀 버전으로 업데이트 |
| **전송 + 즉시 생성** | `apply_to_main_prompt` emit + `QTimer.singleShot(100)` → `execute_generation_pipeline` | 풀 버전으로 업데이트 + 이미지 생성 |

모든 생성 경로는 `event_preset_request` 플래그 사용 → `generation_completed_for_event_preset` 구독 → 프리뷰에 결과 표시.

**버튼 상태 통합**: `_set_generating_state(bool)`로 Generate + 전송+즉시생성 버튼을 동시에 제어. 두 경로가 `_generating` 플래그를 공유하므로 동시 실행 방지.

**검색 + 파티션 전환**: Rating/Character 변경 시 `_reapply_search_or_navigation()`으로 검색 활성 상태에 따라 검색 재실행 또는 일반 네비게이션 갱신.

### `data_manager.py` — 데이터 계층

- `is_data_available()` → ZIP 존재 + 유효성
- `load_base_assets()` → tag_catalog, taxonomy, recommendations 등
- `load_partition_data(name)` → step15 파티션 (캐시)
- `get_available_partitions()` → ZIP 내 파티션 스캔

### `download_worker.py` — 다운로드

- `EventPresetDownloadWorker(QThread)` — urllib + SSL, 취소 가능
- `EventPresetDownloadDialog(QDialog)` — NAIA 테마 프로그레스 바

### `engines.py` — 비즈니스 로직

| 클래스 | 역할 |
|--------|------|
| `TaxonomyEngine` | 택소노미 인덱스, 트리 프로젝션 (파티션별 정렬), 검색 필터 |
| `StagingEngine` | 이벤트 스테이징 (최대 3개), N-way 콤보 교차, 호환성 체크 |
| `RecommendationEngine` | 공기 태그 쿼리/병합, 칩 토글 상태, affinity 역방향 룩업, 색상 필터링 |
| `PromptBuilder` | person 태그 + rating + 이벤트 + deps + recs → 최종 프롬프트 문자열 |
| `QuickSearchComboProvider` | Full Mode용 Quick Search `.tgp` raw 콤보 추출 (allowlist 필터링) |

**QuickSearchComboProvider** (Full Mode):
- `data/quick_search/` `.tgp` 파티션 스토어에서 원시 이벤트 콤보를 추출
- `try_create(category_df, dependency_df)` 팩토리 — Quick Search 데이터 미설치 시 `None` 반환
- **Allowlist 필터링**: 이벤트 태그(`is_event`) + 이벤트-앵커 의존성 태그(`dependency_rules.parquet`)만 허용 (~4,200 태그)
- 파티션 스토어 lazy load + 캐시, CSR 버퍼 직접 접근으로 빠른 태그 추출
- 최대 `RAW_COMBO_LIMIT=1000`개 콤보 반환, 빈도 내림차순

### `widgets.py` — 커스텀 위젯

| 위젯 | 역할 |
|------|------|
| `FlowLayout(QLayout)` | 칩 래핑 레이아웃 (flexbox) |
| `RecommendedTagsPanel(QFrame)` | 자동 의존성 + Expression/Clothing/Characteristic 칩 행, [Clear] 버튼, 선택 칩 좌측 고정 |
| `RichComboDelegate` | HTML 렌더링 콤보박스 아이템 |
| `ComboTagDelegate` | 콤보 셀 내 이벤트/의존성 태그 색상 하이라이팅 |
| `ImagePreviewWidget(QLabel)` | PIL→QPixmap (BytesIO 변환으로 SEGFAULT 방지) |
| `StagingBar` | 스테이징 상태 표시 + Clear 버튼 |
| `SwitchPartitionBar` | 파티션 전환 콤보박스 |

---

## NAIA 메인 윈도우 통합 (`NAIA_cold_v4.py`)

| 위치 | 변경 |
|------|------|
| `extra_features_menu` | Event Preset 메뉴 액션 추가 |
| `_display_generated_image()` | `event_preset_request` 체크 → `generation_completed_for_event_preset` 발행 |
| `generation_controller.py` | `_on_generation_error()`에 event_preset 에러 라우팅 |
| 시그널 연결 | `apply_to_main_prompt` → `on_instant_generation_requested` |
| 상태 추적 | `self.event_preset_window`, `self.event_preset_window_open` |

---

## 주요 규칙

1. **해상도 고정**: 항상 1024x1024 (`override_params`에 width/height 지정)
2. **전처리 스킵**: `skip_prompt_engineering_auto_hide = True`로 메인 화면 전처리 옵션 + 자동 숨김 무시
3. **추천 태그 UX**: 선택된 칩은 이벤트 전환 시에도 유지 (좌측 고정), [Clear] 버튼으로 수동 초기화
4. **테이블 동작**: 데이터 갱신 시 첫 행 자동 선택, 클릭 시 해당 행 뷰포트 최상위로 스크롤
5. **테마**: `DARK_COLORS` + `get_scaled_font_size()` / `get_scaled_size()` 필수
6. **SEGFAULT 방지**: `ImagePreviewWidget`에서 `QImage` 참조를 `self._qimage`로 유지
7. **버튼 상태 통합**: Generate / 전송+즉시생성 버튼은 `_set_generating_state()`로 동시 제어
8. **구독 해제 필수**: `closeEvent`에서 `_unsubscribe_generation()` + `_unsubscribe_send_gen()` 모두 호출
