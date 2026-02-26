# ui/clothes_preset/ — Clothes Preset Viewer (NAIA 2.0 통합)

> 의류 택소노미 브라우저. 6개 신체 부위 기반 의류 분류 + 콤보 탐색 + 추천/충돌 규칙 + 표현(expression) 연관 분석.

## 파일 구조

| 파일 | 설명 | 줄 수 |
|------|------|-------|
| `__init__.py` | `ClothesPresetWindow` export | ~3 |
| `clothes_preset_window.py` | 메인 QMainWindow (3-Panel) | ~750 |
| `data_manager.py` | ZIP I/O + 캐시 + 데이터 로딩 | ~380 |
| `engines.py` | 비즈니스 로직 4개 엔진 | ~350 |
| `widgets.py` | ComboTableModel (QAbstractTableModel) | ~90 |
| `download_worker.py` | HuggingFace 다운로드 + 프로그레스 | ~200 |
| `viewer_clothes.py` | [참고용] 원본 독립 뷰어 | ~1700 |
| `INTEGRATION.md` | [참고용] 원본 통합 문서 | |
| `naia_clothes_preset` | ZIP 데이터 (확장자 없음, 7개 parquet) | |

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
  ├─ engines.ExpressionEngine               ← 표현 콤보 집계
  ├─ engines.PromptBuilder                  ← 프롬프트 빌드
  └─ widgets.ComboTableModel                ← 3000행 최적화 테이블
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
│ │ Expression Table                │   │ └──────┘ └──────┘ │                   │
│ │ Expression | Score | Tags       │   │                    │                   │
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

### 인터랙션
```
콤보 테이블 행 선택 → _on_combo_selected → 번역+표현 갱신+프롬프트 갱신
리전 트리 더블클릭 → _add_selected_region_tag → staged_tags 추가 → _refresh_all
우클릭 콤보 → "Stage Combo Tags" → 전체 갱신
Pair 모드 변경 → _on_pair_mode_changed → 규칙 재필터 → 전체 갱신
검색 (콤보/리전) → 디바운스 타이머 → 갱신
```

### `_refresh_all_from_staging()` 캐스케이드
```
_refresh_all_from_staging()
├─ _refresh_staging()           → 슬롯별 staged 라벨 갱신
├─ _refresh_rules()             → 추천/회피/페어 집계
├─ _refresh_seed_regions()      → 시드 리전 카운트
├─ _refresh_region_tables()     → 6개 트리 전체 리빌드
├─ _refresh_combo_candidates()  → 콤보 테이블 필터링 + 표현 갱신
└─ _refresh_translation_panel() → KR 태그 번역 패널
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

- **캐시 버전**: `CACHE_VERSION = "step34_naia_v1"` — 데이터 구조 변경 시 반드시 버전 업
- **ZIP 경로**: `clothes_preset_window.py` 기준 `../clothes_preset/naia_clothes_preset`가 아님. `data_manager.py`에서 `Path(__file__).resolve().parent / PACKAGE_FILE_NAME` 사용
- **QThread 없음**: 데이터 로딩이 가볍고 캐시 사용으로 빠름. 차후 필요 시 QThread 분리
- **generation_controller.py 수정 불필요**: Send/Generate 기능 없음
