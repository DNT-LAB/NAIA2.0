# CLAUDE.md — ui/ezmode/

> **목적**: EZ Mode 시스템 가이드. 초보자를 위한 단계별 태그 선택 및 프롬프트 생성.

---

## 개요

EZ Mode는 **4단계 가이드 프롬프트 생성 도우미**입니다: Rating → Person Count → Special Tags → General Tags

Co-occurrence Matrix 기반 AI 추천 (Danbooru 3.2M+ 이미지 통계). 즉시 생성 지원.

**데이터 규모**: GitHub에 JSON 파일 668KB (`data/ezmode/`), Hugging Face에 매트릭스 2.7GB (`data/.ezmode/matrices/`).

---

## 아키텍처

```
EZModeWindow (QMainWindow)
    └── EZModeController (QWidget)
        ├── EZModeStep1 (Rating: g/s/q/e)
        ├── EZModeStep2 (Person Count: 1girl, 2boys 등)
        ├── EZModeStep3 (Special Tags: 카테고리별)
        ├── EZModeStep4 (General Tags: AI 추천 + 검색)
        └── 하단 고정 프레임 ("선택된 태그: N개" + "즉시 생성" 버튼)

EZModeDataManager (데이터 로딩 및 캐싱)
    ├── category_index.json (411개 카테고리)
    ├── output.json (40,000+ 태그)
    └── matrices/*.npz 동적 로드 (LRU, 최대 5개)
```

**신호 흐름**:
```
Step1.rating_selected → Step2 활성화
Step2.person_count_selected → Step3 활성화
Step3.special_tags_selected → Step4 활성화 (카테고리 결정 + 매트릭스 로드)
Step4.general_tags_selected → 하단 프레임 업데이트
하단 "즉시 생성" → Controller → Window → MainWindow (Virtual Row: pandas.Series)
```

---

## 주요 파일

| 파일 | 역할 |
|------|------|
| **ezmode_window.py** | 메인 윈도우, 의존성 체크, 다운로드 안내 |
| **ezmode_controller.py** | 중앙 컨트롤러, STEP 통합, Virtual Row 생성 |
| **ezmode_step1.py** | Rating 선택 (g/s/q/e) |
| **ezmode_step2.py** | Person Count 선택 (다중 선택 가능) |
| **ezmode_step3.py** | Special Tags 선택 (카테고리별) |
| **ezmode_step4.py** | General Tags 추천/선택, KR_tags 툴팁 |
| **ezmode_data_manager.py** | 데이터 로딩, 캐싱, 매트릭스 접근 |
| **ezmode_downloader.py** | 의존성 체크, 데이터 존재 확인 |

---

## 데이터 시스템

### 디렉터리 구조

```
data/ezmode/                  # GitHub (668KB)
├── category_index.json       # 411개 카테고리 목록
├── output.json               # 40,000+ 태그 정보
└── category_tags_merged.json # 카테고리 그룹 매핑

data/.ezmode/                 # Hugging Face 전용 (gitignore)
└── matrices/                 # 1,645개 파일 (2.7GB)
    ├── {category_id}_cooccur.npz   # 동시 등장 횟수
    ├── {category_id}_pmi.npz       # 상호 정보량
    ├── {category_id}_condprob.npz  # 조건부 확률
    ├── {category_id}_metadata.json
    └── build_summary.json
```

**로딩 전략**: 초기에 JSON 로드, 카테고리 활성화 시 매트릭스 동적 로드 + LRU 캐싱 (최대 5개).

---

## STEP별 기능

### STEP 2: Person Count

**함정**: `3+` 이상은 매트릭스 파일명에서 `many_`로 치환 (`3boys` → `many_boys`).

### STEP 4: General Tags 추천

**UI**: 검색 바 + 선택된 태그 영역 (150px) + 추천 태그 영역 (3열 그리드, 48개)

**추천 모드**:
1. **인기 태그** (선택 없을 때): Co-occurrence 행 합계 기반
2. **Hybrid** (선택 있을 때): CoOccur 60% + CondProb 30% + PMI 10% → Min-Max 0-99 스케일링

**55점 이상**: 연노랑 (#F0E68C) 하이라이팅

---

## 추천 시스템 핵심

### Hybrid 알고리즘

1. Co-occurrence: 동시 등장 횟수 합계
2. Conditional Probability: 조건부 확률 평균
3. PMI: 상호 정보량 평균
4. Min-Max Scaling → 가중 평균 (0.70 / 0.10 / 0.20) → 0-99 정수

### 태그 처리

- **정규화**: `_` ↔ ` ` 양쪽 버전 모두 인식
- **언더바 필터링**: 추천 결과에서 `_` 포함 태그 제외 (공백 버전만 표시)
- **STEP 3 기반 초기 추천**: STEP 4 진입 시 STEP 3 태그로 Hybrid 계산 (노란색 태그 표시)
- **와일드카드 태그**: 매트릭스에 없는 태그 허용, 보라색(#9B59B6) 표시, 추천 계산에서 제외
- **자동 Rating 태그**: Rating 선택 시 `rating:general`/`nsfw` 등 자동 추가 (와일드카드)

### 리셋 기능

- **STEP 4 초기화**: STEP 4 태그만 리셋, STEP 1~3 유지
- **Rating 변경 확인**: STEP 4 활성 상태에서 rating 변경 시 확인 다이얼로그 표시

---

## 즉시 생성 시스템

`_create_virtual_row()` → `pandas.Series` 생성 (Web View 클릭과 동일 구조).

**중요**: 시그널 타입은 반드시 `pyqtSignal(object)` (pandas.Series는 dict가 아님).

**태그 순서**: Person Count → Special Tags → General Tags

**Rating 매핑**: `'g'→'rating:safe'`, `'s'→'rating:sensitive'`, `'q'→'rating:questionable'`, `'e'→'rating:explicit'`

---

## 주요 함정/주의사항

- `pyqtSignal(dict)` 사용 금지 → `pyqtSignal(object)` 사용 (pandas.Series 전달)
- 매트릭스 캐싱 과다 시 메모리 문제 → LRU 최대 5개 제한
- 스케일링 함수 필수 (`get_scaled_font_size()`, `get_scaled_size()`)
- `data/.ezmode/` 디렉터리는 gitignore 대상

## TODO

1. Hugging Face 실제 다운로드 구현 (현재 Mock)
2. 카테고리 필터링 시스템 (STEP 4)
3. 알고리즘 가중치 설정 UI

---

## 관련 문서

- **[ui/CLAUDE.md](../CLAUDE.md)**: 테마, 스케일링, 공용 위젯
- **[data/CLAUDE.md](../../data/CLAUDE.md)**: 데이터베이스, Parquet 처리
