# CLAUDE.md — data/

> NAIA 2.0의 정적 데이터 저장소. 태그 데이터베이스, 필터 사전, EZ Mode 데이터를 관리합니다.

---

## 디렉터리 구조

```
data/
  ├── tags/                    # Parquet 태그 데이터베이스 (150개 파일, ~100MB+)
  │   └── tags_00~149.parquet  # 각 ~800KB, ~30K-50K rows
  ├── taglist/                 # JSON 태그 필터 + 빈도 데이터
  │   ├── expression_tags.json     # 표정 태그 (modifiers + groups)
  │   ├── pose_action_tags.json    # 포즈/행동 태그 (categories)
  │   ├── location_tags.json       # 장소/배경 태그
  │   ├── meta_tags.json           # 메타/구도 태그
  │   ├── object_tags.json         # 사물 태그
  │   ├── clothing_regions.json    # 의류 Region 매핑
  │   └── unique_tags.json         # 태그 빈도 (noise 필터용)
  ├── characteristic_list.txt  # 특징 태그 사전 (UTF-8, 한 줄 = 하나의 태그)
  ├── clothes_list.txt         # 의류 태그 사전 (동일 형식)
  ├── ezmode/                  # EZ Mode JSON (GitHub, 668KB)
  │   ├── category_index.json  # 411개 카테고리 메타데이터 + UI 트리
  │   ├── output.json          # 태그명→인덱스 매핑
  │   └── category_tags_merged.json  # 카테고리별 태그 목록
  └── .ezmode/                 # EZ Mode 매트릭스 (Hugging Face, 2.7GB)
      └── matrices/            # 카테고리당 4개 파일 × 411 = 1645개
          ├── {category}_cooccur.npz / _pmi.npz / _condprob.npz
          └── {category}_metadata.json
```

## 데이터 흐름

```
data/tags/*.parquet  → core/search_controller.py (멀티프로세싱) → tabs/search_tab.py
data/*.txt           → core/filter_data_manager.py (동기 로드)  → modules/
data/taglist/*.json  → core/filter_data_manager.py (동기 로드)  → core/tag_filter_helpers.py
data/ezmode/*.json   → ui/ezmode/ezmode_data_manager.py         → ezmode STEP 1~3
data/.ezmode/       → ui/ezmode/ezmode_data_manager.py (LRU 3) → ezmode STEP 4
```

---

## Parquet 태그 데이터베이스

### 스키마

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | int64 | 이미지 고유 ID |
| `copyright` | str | 저작권 태그 |
| `character` | str | 캐릭터 태그 |
| `artist` | str | 아티스트 태그 |
| `general` | str | 일반 태그 (쉼표 구분) |
| `meta` | str | 메타 태그 |
| `rating` | str | `"safe"` / `"questionable"` / `"explicit"` |
| `score` | int64 | 점수 |
| `created_at` | str | 생성 날짜 |
| `tokens` | int64 | 토큰 수 |
| `image_width` | int32 | 너비 |
| `image_height` | int32 | 높이 |

### 분할 전략

150개로 분할하는 이유: 멀티프로세싱 병렬 검색, 메모리 효율, 디스크 캐시 효과.

### 검색 아키텍처

- `SearchWorker` (QObject): Pool(starmap)로 150개 파일 병렬 검색, CPU 코어의 절반 사용 (최대 8)
- `SearchController` (QObject): QThread + 시그널 (progress/partial_result/complete/error)
- 부분 결과를 즉시 UI에 전달 (`partial_result_ready` 시그널)

---

## 텍스트 사전 파일

### 형식 규칙

- UTF-8 인코딩, 한 줄에 하나의 태그, 공백 라인 무시, 주석 미지원, 대소문자 구분

### FilterDataManager (`core/filter_data_manager.py`)

```python
filter_manager = FilterDataManager(data_dir='data')
clothes = filter_manager.clothes_list          # 텍스트 사전 (list)
characteristics = filter_manager.characteristic_list
filter_manager._expression_set                 # JSON 필터 (set, 빠른 조회)
filter_manager._location_set
filter_manager._pose_action_set
filter_manager._meta_set
filter_manager._object_set
filter_manager.filter_noise_tags(tags)         # whitelist 기반 저빈도 필터
```

### 태그 필터 파이프라인 (`core/tag_filter_helpers.py`)

`apply_tag_filters()` — 10라운드 순차 필터링, `filter_log` 반환:

1. Auto Hide → 2. 캐릭터 특징 → 3. 의류 → 4. 색상 → 5. 위치/배경 → 6. 표정 → 7. 포즈/행동 → 8. 메타 → 9. 사물 → 10. 노이즈

### 새 사전 추가 방법

**텍스트 사전** (`.txt`):
1. `data/my_list.txt` 생성 (UTF-8, 한 줄 = 하나의 태그)
2. `FilterDataManager.__init__`에 `self.my_list = []` 추가
3. `load_all_filters()`에 `self.my_list = self._load_list_from_file('my_list.txt')` 추가

**JSON 필터** (`data/taglist/*.json`):
1. JSON 파일 생성 (`{"tags": [...]}` 또는 `{"categories": {...}}`)
2. `_load_json_filters()`에 로드 + set 변환 추가
3. `apply_tag_filters()`에 라운드 추가

---

## EZ Mode 데이터

### 데이터 분리

| 위치 | 저장소 | 크기 | 용도 |
|------|--------|------|------|
| `data/ezmode/` | GitHub | 668KB | 카테고리/태그 인덱스 (JSON) |
| `data/.ezmode/matrices/` | Hugging Face | 2.7GB | Co-occurrence 매트릭스 (Sparse) |

### Person Count 정규화

매트릭스 파일명은 `many_boys`를 사용하지만 UI는 `3boys` 등 표시.
`_normalize_person_count()` 메서드가 `3boys`→`many_boys` 등으로 변환.
Virtual Row 프롬프트에는 원본 태그 유지.

### 매트릭스 로딩

- 초기 로드: JSON 동기 (1초 이내), `data_loaded` 시그널
- 매트릭스: LRU 캐시 최대 3개, STEP 4 태그 선택 시 on-demand 로드
- 다운로드: `EZModeDownloadWorker` (QThread), `build_summary.json` 무결성 검증 (1645개 파일, 80%+ 허용)

### 다운로드 URL

```
https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/tags_70_tags_129_matrices.zip
```

---

## 주의사항

- 데이터 파일 구조 변경 시 `core/search_engine.py`, `core/filter_data_manager.py` 함께 수정 필수
- Parquet 필수 컬럼: `id`, `general`, `score` — 스키마 변경 시 검색 엔진 테스트 필요
- `data/.ezmode/`는 `.gitignore` 제외 (사용자가 필요 시 다운로드)
- 텍스트 사전에서 태그 검색 시 공백(`long hair`) vs 언더스코어(`long_hair`) 주의

## 주요 의존성

| 소비자 | 용도 |
|--------|------|
| `core/filter_data_manager.py` | 텍스트 사전 로드 |
| `core/search_controller.py` + `core/search_engine.py` | Parquet 검색 |
| `ui/modern_menu.py` | 태그 정보 툴팁 |
| `ui/ezmode/ezmode_data_manager.py` | EZ Mode 전체 |
| `ui/ezmode/ezmode_downloader.py` | 매트릭스 다운로드/검증 |

외부 라이브러리: `pandas`, `pyarrow`, `scipy` (sparse 매트릭스)
