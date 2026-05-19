# ui/clothes_preset/ — Clothes Preset Viewer (NAIA 2.0 통합)

> 의류 택소노미 브라우저. 6개 신체 부위 기반 의류 분류 + 콤보 탐색 + 추천/충돌 규칙 + 표정 그룹 피커.

## 파일 구조

| 파일 | 설명 |
|------|------|
| `__init__.py` | `ClothesPresetWindow` export |
| `clothes_preset_window.py` | 메인 QMainWindow (3-Panel) |
| `data_manager.py` | ZIP I/O + 캐시 + 데이터 로딩 |
| `engines.py` | 비즈니스 로직 (택소노미, 규칙, 표정 분류, 프롬프트) |
| `widgets.py` | ComboTableModel, FlowLayout, StagedTagChip, ExprTreeDelegate |
| `download_worker.py` | HuggingFace 다운로드 + 프로그레스 |
| `naia_clothes_preset` | ZIP 데이터 (7개 parquet + pkl 캐시) |

## 아키텍처 개요

```
NAIA_cold_v4.py
  └─ extra_features_menu → "👗 Clothes Preset"
     └─ _open_clothes_preset_window()
        ├─ ensure_data_available() → 다운로드 대화상자
        └─ ClothesPresetWindow(app_context, kr_tags_df)

ClothesPresetWindow (QMainWindow)
  ├─ data_manager.ClothesPresetDataManager  ← ZIP I/O + 캐시
  ├─ engines.ClothingTaxonomyEngine         ← 슬롯 할당/리전 매핑
  ├─ engines.RulesEngine                    ← 추천/충돌 규칙
  ├─ engines.build_expression_group_tree()  ← 표정 그룹 분류
  ├─ engines.PromptBuilder                  ← 프롬프트 빌드
  ├─ widgets.ComboTableModel                ← 3000행 최적화 테이블
  └─ widgets.ExprTreeDelegate               ← 표정 트리 pinned 렌더링
```

## 레이아웃 (QSplitter 4:3:3)

```
┌─────────────── LEFT (4) ──────────────┬──── CENTER (3) ────┬──── RIGHT (3) ────┐
│ [Combo Search] [Pair: Balanced ▼]     │ [Region Search 🔍] │                   │
│ "3000 combos"                         │                    │                   │
│ ┌─────────────────────────────────┐   │ ┌HEAD──┐ ┌UPPER─┐ │  Prompt (편집)    │
│ │ Combo Table (ComboTableModel)   │   │ │ tree │ │ tree │ │                   │
│ │ Clothing Combo | Posts | Tags   │   │ └──────┘ └──────┘ │  [Copy Clipboard] │
│ │ ... 3000 rows ...               │   │ ┌WAIST─┐ ┌ARMS──┐ │  [Clear All]      │
│ ├─────────────────────────────────┤   │ │ tree │ │ tree │ │                   │
│ │ Translation Panel (KR tags)     │   │ └──────┘ └──────┘ │  Status Label     │
│ │ Tag | Description | Category    │   │ ┌LEGS──┐ ┌STYLE─┐ │                   │
│ ├─────────────────────────────────┤   │ │ tree │ │ tree │ │                   │
│ │ Expression Tree (그룹별)        │   │ └──────┘ └──────┘ │                   │
│ │ > smile (40) > emoticon (41)   │   │                    │                   │
│ └─────────────────────────────────┘   │ 각 슬롯: staged +  │                   │
│                                       │ clear 버튼         │                   │
└───────────────────────────────────────┴────────────────────┴───────────────────┘
```

## 핵심 데이터 흐름

### 데이터 로딩
```
ClothesPresetDataManager.load_all()
  1. 로컬 캐시 (viewer_clothes_cache_step34.pkl) → 성공 시 반환
  2. ZIP 내장 캐시 → 성공 시 반환
  3. Cold build: 7개 parquet → 데이터 구축 → 로컬 캐시 저장
  → dict: combo_by_clothing, expr_by_combo, region_tags,
          reco_by_seed, avoid_by_seed, pair_by_seed,
          conflict_pairs, conflict_exclusion_score
```

### 스테이징 시스템 (2-Level)

```
_region_staged (Source of Truth)      _staged_tags (Promoted Only)
  dict[str, list[str]]                  list[str]
  슬롯별 모든 선택 태그           →     상위 20%/slot OR 40%/subgroup
                                         (by post_count)
  프롬프트 출력에 전체 사용              rules/combo 필터링에 사용
```

- **promoted 태그**: 연노랑(#F5E6A3) 칩 + combo 테이블 하이라이트
- **리전 호환성 필터**: 같은 슬롯 내 combo 교집합이 0이 되는 태그 트리에서 숨김

### 표정 트리 (Expression Tree)

- `expr_global` → `build_expression_group_tree()` → 11개 감정 그룹으로 분류
- 클릭 토글: 1개만 pinned (파란색 배경), `ExprTreeDelegate`가 hover 무관 렌더링
- pinned combo 태그 → 프롬프트에 추가

### 인터랙션
```
콤보 테이블 행 선택 → _on_combo_selected → 번역+프롬프트 갱신
리전 트리 더블클릭 → _region_staged[slot] 추가 → _refresh_all
표정 트리 클릭 → _staged_expressions 토글 → 프롬프트 갱신
우클릭 콤보 → "Stage Combo Tags" → 전체 갱신
```

### `_refresh_all_from_staging()` 캐스케이드
```
_refresh_all_from_staging()
├─ _recompute_staged_tags()     → promoted 재계산
├─ _refresh_staging()           → 슬롯별 staged 칩 갱신
├─ _refresh_rules()             → 추천/회피/페어 집계
├─ _refresh_seed_regions()      → 시드 리전 카운트
├─ _refresh_region_tables()     → 6개 트리 리빌드 (호환성 필터 포함)
├─ _refresh_combo_candidates()  → 콤보 테이블 필터링
└─ _rebuild_prompt_preview()    → 프롬프트 갱신
```

## event_preset과의 차이점

| 항목 | event_preset | clothes_preset |
|------|-------------|----------------|
| 데이터 | 385MB HF 다운로드 | 소형 ZIP (로컬/HF) |
| 택소노미 | 평면 이벤트 | 6개 신체 부위 계층 |
| LEFT 패널 | 파티션→트리→리스트 | 콤보 테이블+번역+표현 |
| CENTER | 4-탭 QTabWidget | 6-슬롯 QGridLayout |
| RIGHT | 이미지+생성+전송 | 프롬프트+클립보드 복사만 |
| 생성 연동 | Generate/Send/Send+Gen | 없음 (클립보드만) |
| 규칙 | Affinity만 | 4종 (reco/avoid/pair/conflict) |
| 검색 | 영어 | 영어+한글 (kr_tags_df) |
| 번역 | 없음 | Translation Panel |

## 한글 검색 구현

`ClothesPresetWindow._build_kr_search_index()`:
- `kr_tags_df`의 `desc`/`keywords` 필드에서 한글 토큰 추출
- `_kr_index: dict[str, set[str]]` — 한글 단어 → 영어 태그 집합
- CENTER 검색창에 한글 입력 시 `_kr_search()` → 영어 태그로 변환 후 필터

## 주의사항

- **캐시**: `CACHE_VERSION = 1` — 데이터 구조 변경 시 반드시 버전 업. ZIP 내장 pkl 캐시는 cache_key 검증 생략
- **ZIP 경로**: `data_manager.py`에서 `Path(__file__).resolve().parent / PACKAGE_FILE_NAME`
- **QThread 없음**: 캐시 사용으로 빠름
- **PINNED_ROLE**: `UserRole + 101` (ComboTableModel.HtmlRole = `UserRole + 100`과 충돌 방지)
