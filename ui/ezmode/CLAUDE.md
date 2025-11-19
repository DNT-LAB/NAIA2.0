# CLAUDE.md — ui/ezmode/

> **목적**: NAIA 2.0의 EZ Mode 시스템 가이드. 초보자를 위한 단계별 태그 선택 및 프롬프트 생성 기능.

**📝 최근 업데이트** (2025-01-19):
- ✅ 즉시 생성 기능 구현 완료 (Virtual Row 생성 → Main UI 태그 할당)
- ✅ 신호 타입 수정 (`pyqtSignal(dict)` → `pyqtSignal(object)` for pandas.Series)
- ✅ 윈도우 기본 너비 25% 감소 (1200px → 900px)
- ✅ KR_tags 툴팁 기능 추가 (Category, Description, Keywords)
- ✅ Hybrid 추천 알고리즘 가중치 조정 (CoOccur 70%, CondProb 10%, PMI 20%)
- ✅ **언더바 태그 제외** (STEP 4 추천에서 `_` 포함 태그 필터링)
- ✅ **STEP 3 태그 기반 초기 추천** (초기 로드 시 노란색 태그 표시)
- ✅ **와일드카드 태그 지원** (매트릭스에 없는 태그 허용, 보라색 배경)
- ✅ **자동 Rating 태그 추가** (g/s/q/e에 따라 rating 태그 자동 추가)
- ✅ **STEP 4 초기화 버튼** (STEP 4 태그만 리셋, STEP 1~3 유지)
- ✅ **Rating 변경 확인 다이얼로그** (STEP 2~4 초기화 경고)
- ✅ **데이터 구조 최적화** (GitHub: JSON 파일 668KB, Hugging Face: matrices 2.7GB)

---

## 목차

1. [개요](#개요)
2. [아키텍처](#아키텍처)
3. [주요 파일 및 역할](#주요-파일-및-역할)
4. [데이터 시스템](#데이터-시스템)
5. [STEP별 기능](#step별-기능)
6. [추천 시스템](#추천-시스템)
7. [즉시 생성 시스템](#즉시-생성-시스템)
8. [개발 가이드](#개발-가이드)
9. [TODO: 미구현 기능](#todo-미구현-기능)
10. [문제 해결](#문제-해결)
11. [참고 자료](#참고-자료)

---

## 개요

### EZ Mode란?

EZ Mode는 **초보자를 위한 단계별 프롬프트 생성 도우미**입니다.

**핵심 특징**:
- 🎯 **4단계 가이드**: Rating → Person Count → Special Tags → General Tags
- 🤖 **AI 추천**: Co-occurrence Matrix 기반 태그 추천
- 📊 **빅데이터**: Danbooru 3.2M 이미지 태그 통계 활용
- 🚀 **즉시 생성**: 선택한 태그로 바로 이미지 생성

### 사용 시나리오

```
사용자: "여자 캐릭터 이미지를 만들고 싶은데 어떤 태그를 써야 할지 모르겠어요"

EZ Mode 워크플로우:
1. STEP 1: "어떤 수위의 이미지를 만들까요?" → "Safe" 선택
2. STEP 2: "몇 명의 캐릭터가 있나요?" → "1girl" 선택
3. STEP 3: "특별한 요소가 있나요?" → "school_uniform" 선택
4. STEP 4: AI 추천 태그 표시
   - "black_hair (95점)" ← 교복과 자주 함께 등장
   - "long_hair (92점)"
   - "smile (88점)"
   - ... 48개 추천

사용자: 원하는 태그 클릭 → "즉시 생성" 버튼 → 이미지 생성 시작!
```

### 데이터 규모

| 항목 | 수량 | 크기 | 저장소 |
|------|------|------|--------|
| **출처 이미지** | 3.2M+ | - | - |
| **카테고리** | 411개 | 234KB | GitHub |
| **태그 정보** | 40,000+ | 431KB | GitHub |
| **매트릭스 파일** | 1,645개 | 2.7GB | Hugging Face |
| **총 데이터 크기** | - | ~2.7GB | - |

**GitHub 저장소**: `category_index.json` + `output.json` = **668KB**
**Hugging Face**: `matrices/` 폴더 = **2.7GB**

---

## 아키텍처

### 컴포넌트 구조

```
EZModeWindow (QMainWindow)
    └── EZModeController (QWidget)
        ├── EZModeStep1 (Rating 선택)
        ├── EZModeStep2 (Person Count 선택)
        ├── EZModeStep3 (Special Tags 선택)
        ├── EZModeStep4 (General Tags 추천 및 선택)
        └── 하단 고정 프레임
            ├── "선택된 태그: N개" 라벨
            └── "즉시 생성" 버튼

EZModeDataManager (데이터 로딩 및 캐싱)
    ├── category_index.json 로드
    ├── output.json 로드
    └── matrices/*.npz 동적 로드
```

### 신호 흐름

```
EZModeStep1.rating_selected
    ↓
EZModeController._on_rating_selected()
    ↓ activate
EZModeStep2.person_count_selected
    ↓
EZModeController._on_person_count_selected()
    ↓ activate
EZModeStep3.special_tags_selected
    ↓
EZModeController._on_special_tags_selected()
    ↓ activate
EZModeStep4.general_tags_selected
    ↓
EZModeController._on_general_tags_selected()
    ↓ update UI
하단 프레임 ("선택된 태그: N개" + "즉시 생성" 버튼)
    ↓ click
EZModeController.instant_generation_requested
    ↓
EZModeWindow.instant_generation_requested
    ↓
MainWindow.on_generate_with_image_requested()
    ↓
프롬프트 생성 + 이미지 생성 시작
```

### 데이터 흐름

```
1. 초기 로드 (한 번만):
   category_index.json → EZModeDataManager.category_index
   output.json → EZModeDataManager.tags_data

2. 카테고리 활성화 시 (동적):
   STEP 3 선택 → category_id 결정
   matrices/{category_id}_*.npz 로드 → 캐싱

3. 추천 계산:
   선택된 태그들 → Co-occurrence Matrix 조회
   → Hybrid 알고리즘 적용 → 상위 48개 반환
```

---

## 주요 파일 및 역할

### UI 컴포넌트

| 파일 | 크기 | 역할 | 주요 기능 |
|------|------|------|----------|
| **ezmode_window.py** | 7.9K | 메인 윈도우 | 의존성 체크, 데이터 다운로드 안내, 컨트롤러 통합, 신호 릴레이 |
| **ezmode_controller.py** | 9.7K | 중앙 컨트롤러 | 4개 STEP 통합, 신호 브리징, 하단 프레임 관리, **Virtual Row 생성** |
| **ezmode_step1.py** | 6.2K | STEP 1 | Rating 선택 (g/s/q/e) |
| **ezmode_step2.py** | 13K | STEP 2 | Person Count 선택 (1girl, 2boys 등) |
| **ezmode_step3.py** | 12K | STEP 3 | Special Tags 선택 (카테고리별 태그) |
| **ezmode_step4.py** | 31K | STEP 4 | General Tags 추천 및 선택, **KR_tags 툴팁 기능** |
| **ezmode_prompt_display.py** | 10K | ⚠️ **Deprecated** | ~~우측 프롬프트 표시~~ (제거 예정, 사용되지 않음) |

### 데이터 시스템

| 파일 | 크기 | 역할 |
|------|------|------|
| **ezmode_data_manager.py** | 9.0K | 데이터 로딩, 캐싱, 매트릭스 접근 |
| **ezmode_downloader.py** | 5.4K | 의존성 체크, 데이터 존재 확인 |

### 초기화 파일

| 파일 | 역할 |
|------|------|
| **__init__.py** | 모듈 익스포트 |

---

## 데이터 시스템

### 데이터 디렉터리 구조

**분리 구조**:
```
data/ezmode/                  # GitHub 저장소에 포함
├── category_index.json       # 카테고리 목록 (411개, 234KB)
├── output.json               # 태그 정보 (40,000+ 태그, 431KB)
└── category_tags_merged.json # 카테고리 그룹 매핑

data/.ezmode/                 # Hugging Face 전용 (gitignore)
└── matrices/                 # Co-occurrence 매트릭스 (2.7GB)
    ├── e_multiple_1boy_1girl_furry_large_breasts_cooccur.npz
    ├── e_multiple_1boy_1girl_furry_large_breasts_pmi.npz
    ├── e_multiple_1boy_1girl_furry_large_breasts_condprob.npz
    ├── e_multiple_1boy_1girl_furry_large_breasts_metadata.json
    ├── ... (411 카테고리 × 4 파일 = 1,644개)
    └── build_summary.json
```

**저장소 분리**:
- **GitHub (`data/ezmode/`)**: JSON 파일들 (총 668KB)
- **Hugging Face (`data/.ezmode/matrices/`)**: 매트릭스 파일 (2.7GB, ZIP 압축)

**참고**:
- `ezmode/`: 일반 폴더, GitHub 저장소에 포함 (JSON 파일 배포용)
- `.ezmode/`: 숨김 폴더, Hugging Face 전용 (대용량 매트릭스)
- 프로그램 시작 시 matrices 미발견 시 자동으로 다운로드 안내 표시

**.gitignore 구성**:
```gitignore
# EZ Mode 데이터 분리 구조
# - data/ezmode/: GitHub 포함 (JSON 파일들)
# - data/.ezmode/: Hugging Face 전용 (matrices만)
data/.ezmode/
```

**사용자 워크플로우**:
1. GitHub 저장소 클론 → `data/ezmode/*.json` 자동 포함 (668KB)
2. 프로그램 실행 → matrices 미발견 → 다운로드 안내
3. Hugging Face에서 다운로드 → `data/.ezmode/matrices/` 압축 해제 (2.7GB)

### category_index.json

**구조**:
```json
{
  "metadata": {
    "total_categories": 411,
    "source_directory": "./output/matrices"
  },
  "available_options": {
    "ratings": ["e", "g", "q", "s"],
    "person_types": ["multiple", "solo"],
    "person_counts": ["1boy", "1girl", "1other", "2boys", ...],
    "special_tags": ["child", "furry", "futanari", "large_breasts", ...]
  },
  "categories": {
    "e_multiple_1boy_1girl_furry_large_breasts": {
      "category_id": "e_multiple_1boy_1girl_furry_large_breasts",
      "rating": "e",
      "type": "multiple",
      "person_count": {"1boy": 1, "1girl": 1},
      "special_tags": ["furry", "large_breasts"],
      "total_rows": 662
    },
    ...
  }
}
```

**용도**:
- STEP 1-3 선택에 따른 카테고리 ID 결정
- 411개 카테고리 조합 (rating × person_count × special_tags)

### output.json

**구조**:
```json
{
  "1girl": {
    "category_id": 0,
    "frequency": 1234567
  },
  "hatsune_miku": {
    "category_id": 1,
    "frequency": 56789
  },
  ...
}
```

**용도**: 태그 → 카테고리 매핑, 빈도 정보

### Co-occurrence Matrix

**파일명 패턴**: `{category_id}_{type}.npz`

**타입**:
- `cooccur`: Co-occurrence (동시 등장 횟수)
- `pmi`: Pointwise Mutual Information (상호 정보량)
- `condprob`: Conditional Probability (조건부 확률)
- `metadata.json`: 카테고리 메타데이터

**형식**: Sparse Matrix (CSR format, scipy)

**크기**:
- 총 1,645개 파일
- 411개 카테고리 × 4개 파일 = 1,644개
- `build_summary.json` 1개

### 데이터 로딩 전략

**EZModeDataManager**:

1. **초기 로드** (앱 시작 시):
   ```python
   def load_initial_data(self):
       # category_index.json 로드 (필수)
       # output.json 로드 (필수)
       # KR_tags.parquet 로드 (선택, 툴팁용)
   ```

2. **동적 로드** (카테고리 활성화 시):
   ```python
   def load_category_matrices(self, category_id: int):
       # {category_id}_cooccur.npz 로드
       # {category_id}_pmi.npz 로드
       # {category_id}_cond.npz 로드
       # 캐싱 (self.matrices_cache[category_id])
   ```

3. **메모리 관리**:
   ```python
   def clear_cache(self):
       # 모든 로드된 매트릭스 해제
       # 메모리 정리
   ```

**캐싱 정책**:
- 최대 5개 카테고리 매트릭스 캐싱
- LRU (Least Recently Used) 방식
- 창 닫기 시 전체 캐시 해제

---

## STEP별 기능

### STEP 1: Rating 선택

**파일**: `ezmode_step1.py`

**목적**: 이미지 수위 선택

**선택지**:
- `g` - Safe (일반)
- `s` - Sensitive (민감)
- `q` - Questionable (선정적)
- `e` - Explicit (성인)

**동작**:
1. 4개 버튼 표시
2. 사용자 클릭 → `rating_selected` 시그널 발행
3. Controller → STEP 2 활성화

**코드 예시**:
```python
def _on_rating_clicked(self):
    button = self.sender()
    rating = button.property('rating')

    # 시그널 발행
    self.rating_selected.emit(rating)

    # 버튼 스타일 업데이트 (선택 상태)
    self._update_button_styles()
```

### STEP 2: Person Count 선택

**파일**: `ezmode_step2.py`

**목적**: 캐릭터 인원 선택

**카테고리**:
- Solo (1명)
- Multiple Girls (여성 복수)
- Multiple Boys (남성 복수)
- Multiple Others (기타 복수)

**선택지 예시**:
- `1girl`, `2girls`, `3girls`, `4girls`, `5girls`, `6+girls`
- `1boy`, `2boys`, `3boys`, `4boys`, `5boys`, `6+boys`
- `1other`, `2others`, `3others`, ...

**⚠️ 중요**: `3+` 이상의 태그는 매트릭스 파일명에서 `many_`로 치환됩니다
- `3boys`, `4boys`, `5boys`, `6+boys` → `many_boys`
- `3girls`, `4girls`, `5girls`, `6+girls` → `many_girls`
- `3others`, `4others`, `5others`, `6+others` → `many_others`

**동작**:
1. Rating 선택 시 활성화
2. 카테고리 탭 표시
3. 태그 버튼 클릭 → `person_count_selected` 시그널 발행
4. Controller → STEP 3 활성화

**특징**:
- 다중 선택 가능 (예: `1girl + 1boy`)
- 선택된 태그는 강조 표시

### STEP 3: Special Tags 선택

**파일**: `ezmode_step3.py`

**목적**: 카테고리별 특수 태그 선택

**카테고리 예시**:
- Character (캐릭터)
- Copyright (작품)
- Artist (아티스트)
- Style (스타일)
- Meta (메타)

**동작**:
1. Person Count 선택 시 활성화
2. 카테고리 탭 표시 (category_index.json 기반)
3. 각 카테고리별 태그 리스트 표시
4. 태그 클릭 → 선택/해제 토글
5. `special_tags_selected` 시그널 발행 (선택된 모든 태그)
6. Controller → STEP 4 활성화 + 카테고리 결정

**카테고리 결정 로직**:
```python
# 선택된 태그들의 카테고리 우선순위
1. Character > Copyright > Artist > Style > Meta
2. 가장 높은 우선순위 카테고리 선택
3. 해당 카테고리의 매트릭스 로드
```

### STEP 4: General Tags 추천 및 선택

**파일**: `ezmode_step4.py` (가장 복잡)

**목적**: AI 추천 태그 선택 및 검색

**UI 구성**:

1. **검색 바**:
   - 태그 직접 입력 가능
   - Enter로 추가

2. **선택된 태그 영역** (150px 고정):
   - FlowLayout으로 자동 줄바꿈
   - `✕ 태그명` 버튼 (클릭 시 제거)
   - 툴팁: KR_tags 정보 (Category, Description, Keywords)

3. **추천 태그 영역** (나머지 공간):
   - 3열 그리드 레이아웃
   - 48개 추천 태그 표시
   - 점수 표시: `태그명 (0-99점)`
   - 55점 이상: 연노랑 (#F0E68C)
   - 툴팁: KR_tags 정보

**추천 모드**:

1. **인기 태그 모드** (선택된 태그 없을 때):
   - Co-occurrence Matrix 행 합계 기반
   - 가장 많이 등장하는 태그 추천

2. **Hybrid 모드** (선택된 태그 있을 때):
   - Co-occurrence 60%
   - Conditional Probability 30%
   - PMI 10%
   - Min-Max Scaling으로 0-99 점수화

**동작**:
1. Special Tags 선택 시 활성화
2. 매트릭스 로드 (category_id 기반)
3. 추천 태그 계산 (48개)
4. 태그 클릭 → 선택 목록에 추가
5. `general_tags_selected` 시그널 발행
6. Controller → 하단 프레임 업데이트

---

## 추천 시스템

### Hybrid 알고리즘

**파일**: `ezmode_step4.py:546-602`

**알고리즘 단계**:

1. **Co-occurrence 점수 계산**:
   ```python
   cooccur_scores = cooccur_matrix[selected_indices, :].sum(axis=0)
   # 선택된 태그들과 동시 등장 횟수 합계
   ```

2. **Conditional Probability 점수 계산**:
   ```python
   cond_scores = cond_matrix[selected_indices, :].mean(axis=0)
   # 선택된 태그가 있을 때 다른 태그가 등장할 확률
   ```

3. **PMI 점수 계산**:
   ```python
   pmi_scores = pmi_matrix[selected_indices, :].mean(axis=0)
   # 태그 간 상호 정보량 (연관성 측정)
   ```

4. **Min-Max Scaling**:
   ```python
   def min_max_scale(scores):
       min_val = scores.min()
       max_val = scores.max()
       if max_val - min_val == 0:
           return np.ones_like(scores)
       return (scores - min_val) / (max_val - min_val)
   ```

5. **가중 평균**:
   ```python
   alpha_cooccur = 0.70  # 사용자 조정 가능
   alpha_cond = 0.10
   alpha_pmi = 0.20

   final_score = (
       alpha_cooccur * cooccur_normalized +
       alpha_cond * cond_normalized +
       alpha_pmi * pmi_normalized
   )
   ```

6. **0-99 정수 스케일링**:
   ```python
   min_score = final_scores.min()
   max_score = final_scores.max()
   scaled_score = int(((score - min_score) / (max_score - min_score)) * 99)
   ```

### 태그 정규화 및 필터링

#### 정규화 (Normalization)

**문제**: Danbooru 태그는 언더스코어(`_`)와 공백(` `) 두 가지 형태 존재

**해결**:
```python
def _normalize_tag(self, tag: str) -> List[str]:
    """태그를 언더스코어/공백 양쪽 버전 반환"""
    variants = [tag]
    if '_' in tag:
        variants.append(tag.replace('_', ' '))
    if ' ' in tag:
        variants.append(tag.replace(' ', '_'))
    return variants
```

**사용 예시**:
```python
# "large_breasts"와 "large breasts" 모두 인식
tag_variants = self._normalize_tag(selected_tag)
for variant in tag_variants:
    if variant in tag_index:
        idx = tag_index[variant]
        # 매트릭스 조회
```

#### 언더바 태그 필터링 (2025-01-19)

**파일**: `ezmode_step4.py:648-650, 723-725`

**목적**: 추천 결과에서 언더바(`_`)가 포함된 태그를 제외하여 공백 버전만 표시

**구현**:
```python
# _get_recommended_tags() - Line 648-650
for idx in top_indices:
    if idx in index_tag and hybrid_scores[idx] > 0:
        tag = index_tag[idx]

        # ✅ FIX: 언더바가 포함된 태그 제외
        if '_' in tag:
            continue

# _get_popular_tags() - Line 723-725
for idx in top_indices:
    if idx in index_tag and tag_popularity[idx] > 0:
        tag = index_tag[idx]

        # ✅ FIX: 언더바가 포함된 태그 제외
        if '_' in tag:
            continue
```

**효과**:
- ❌ 제외됨: `large_breasts`, `small_breasts`, `bare_shoulders`
- ✅ 표시됨: `large breasts`, `small breasts`, `bare shoulders`

#### STEP 3 태그 기반 초기 추천 (2025-01-19)

**파일**: `ezmode_step4.py:529-533`

**문제**: STEP 4에서 아무 태그도 클릭하지 않았을 때, 전역 인기도만 사용하여 모든 태그가 낮은 점수 → 노란색(55+) 태그 없음

**해결**:
```python
# 기존 (문제):
# if not self.selected_tags:
#     return self._get_popular_tags(top_n, excluded_tags_from_steps)

# 수정 (해결):
# ✅ FIX: STEP 4 태그가 없어도 STEP 3 태그를 기반으로 Hybrid 추천 계산
# (기존에는 global popularity만 사용하여 노란색 태그가 없었음)
# 단, STEP 3 태그도 없으면 인기 태그 반환
if not self.selected_tags and not excluded_tags_from_steps:
    return self._get_popular_tags(top_n, excluded_tags_from_steps)
```

**효과**:
- STEP 3에서 `large breasts` 선택 시
- STEP 4 초기 로드에서 관련 태그들이 높은 점수(55+)로 노란색 표시됨
- 예: `breasts`, `nipples`, `cleavage` 등

#### 와일드카드 태그 (2025-01-19)

**파일**: `ezmode_step4.py`

**목적**: 매트릭스에 존재하지 않는 태그도 사용자가 직접 추가하여 프롬프트에 포함할 수 있도록 지원

**기능**:
- 검색 바에서 매트릭스에 없는 태그 입력 시 와일드카드로 허용
- 보라색 배경(#9B59B6)으로 표시하여 일반 태그와 구분
- 추천 계산에서 제외 (매트릭스에 없으므로)

**구현**:
```python
# Line 124: 와일드카드 태그 추적
self.wildcard_tags = set()

# Line 292-322: 검색 입력 처리
def _on_search_enter(self):
    """검색 입력 Enter 이벤트 (와일드카드 태그 지원)"""
    search_text = self.search_input.text().strip()

    if not search_text or search_text in self.selected_tags:
        return

    # 태그 존재 확인
    if search_text in self.data_manager.tag_index:
        # 매트릭스에 존재하는 정상 태그
        self.selected_tags.append(search_text)
        print(f"[OK] Tag added: {search_text}")
    else:
        # 매트릭스에 없는 와일드카드 태그
        self.selected_tags.append(search_text)
        self.wildcard_tags.add(search_text)
        print(f"[OK] Wildcard tag added: {search_text} (not in matrix)")

    self.search_input.clear()
    self._update_selected_tags_display()
    self._update_recommendations()

# Line 332-361: 선택된 태그 표시 (보라색 배경)
if tag in self.wildcard_tags:
    bg_color = "#9B59B6"  # 보라색 (와일드카드)
else:
    bg_color = DARK_COLORS['accent_blue']  # 파란색 (일반 태그)

# Line 578-590: 추천 계산에서 제외
normal_tags = [tag for tag in self.selected_tags if tag not in self.wildcard_tags]
all_selected_tags = normal_tags + excluded_tags_from_steps
```

**효과**:
- 사용자 정의 태그 추가 가능 (예: `masterpiece`, `best quality`)
- 와일드카드는 보라색으로 표시되어 시각적으로 구분
- 추천 알고리즘은 정상 태그만 사용하여 정확도 유지

#### 자동 Rating 태그 (2025-01-19)

**파일**: `ezmode_step4.py:287-311`

**목적**: Rating 선택 시 해당하는 rating 태그를 자동으로 와일드카드 태그로 추가

**자동 추가 태그**:
| Rating | 자동 추가 태그 |
|--------|---------------|
| General (g) | `rating:general` |
| Sensitive (s) | `rating:sensitive` |
| Questionable (q) | `rating:questionable`, `nsfw` |
| Explicit (e) | `rating:explicit`, `nsfw` |

**구현**:
```python
# Line 287-311: set_context() 메서드에서 자동 추가
if rating == 'g':
    self.selected_tags.insert(0, 'rating:general')
    self.wildcard_tags.add('rating:general')
elif rating == 's':
    self.selected_tags.insert(0, 'rating:sensitive')
    self.wildcard_tags.add('rating:sensitive')
elif rating == 'q':
    self.selected_tags.insert(0, 'nsfw')
    self.selected_tags.insert(0, 'rating:questionable')
    self.wildcard_tags.add('rating:questionable')
    self.wildcard_tags.add('nsfw')
elif rating == 'e':
    self.selected_tags.insert(0, 'nsfw')
    self.selected_tags.insert(0, 'rating:explicit')
    self.wildcard_tags.add('rating:explicit')
    self.wildcard_tags.add('nsfw')
```

**효과**:
- STEP 1에서 선택한 rating이 자동으로 태그에 포함됨
- 프롬프트에 rating 정보가 명시적으로 전달됨
- 가장 앞에 위치하여 우선순위 확보

### 리셋 기능

**파일**: `ezmode_controller.py`, `ezmode_step4.py`

#### STEP 4 초기화 버튼 (2025-01-19)

**목적**: STEP 4에서 선택한 태그만 초기화하고 STEP 1~3 태그는 유지

**UI 위치**: 하단 고정 프레임, "선택된 태그" 라벨 옆

**구현**:

```python
# ezmode_controller.py:123-146 - 초기화 버튼 UI
self.reset_step4_btn = QPushButton("초기화")
self.reset_step4_btn.setMinimumHeight(get_scaled_size(40))
self.reset_step4_btn.setEnabled(False)  # 초기 비활성화
self.reset_step4_btn.clicked.connect(self._on_reset_step4)

# ezmode_controller.py:420-438 - 초기화 이벤트 핸들러
def _on_reset_step4(self):
    """STEP 4 초기화 버튼 클릭"""
    if hasattr(self, 'step4'):
        self.step4.reset_step4_tags()
        print("[Controller] STEP 4 tags reset")

# ezmode_step4.py:320-351 - 초기화 메서드
def reset_step4_tags(self):
    """STEP 4 태그만 초기화 (STEP 1~3 태그 유지)"""
    # STEP 4에서 추가한 태그만 제거
    step4_tags = [tag for tag in self.selected_tags
                  if tag not in self.excluded_tags_from_steps
                  and tag not in self.wildcard_tags]

    for tag in step4_tags:
        self.selected_tags.remove(tag)

    # 와일드카드 태그 중 rating 태그만 유지
    rating_tags = {tag for tag in self.wildcard_tags
                   if tag.startswith('rating:') or tag == 'nsfw'}
    self.wildcard_tags = rating_tags

    # UI 업데이트
    self._update_selected_tags_display()
    self._update_recommendations()
```

**효과**:
- STEP 4에서 추가한 일반 태그만 제거
- STEP 1~3 태그 (Person Count, Special Tags, Auto Rating Tags) 유지
- 빠른 재선택 가능

#### Rating 변경 확인 다이얼로그 (2025-01-19)

**파일**: `ezmode_controller.py:222-258`

**목적**: Rating 변경 시 STEP 2~4 초기화 경고

**동작**:
1. STEP 4가 활성화된 상태에서 rating 변경 시도
2. 확인 다이얼로그 표시
3. 취소 → 이전 rating으로 복원
4. 확인 → STEP 2~4 완전 초기화

**구현**:
```python
# Line 222-258: Rating 선택 이벤트 핸들러
def _on_rating_selected(self, rating: str):
    """STEP 1: Rating 선택 이벤트"""
    # 이미 활성화된 상태에서 rating 변경 시 확인
    if hasattr(self, 'current_rating') and self.current_rating and self.current_rating != rating:
        if hasattr(self, 'step4') and self.step4.isEnabled():
            # 확인 다이얼로그
            reply = QMessageBox.question(
                self,
                "Rating 변경 확인",
                f"Rating을 변경하면 STEP 2~4의 모든 선택이 초기화됩니다.\n\n"
                f"현재: {self.current_rating.upper()} → 변경: {rating.upper()}\n\n"
                f"계속하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.No:
                # 취소 - STEP1의 선택을 이전 rating으로 되돌림
                self.step1.set_rating(self.current_rating)
                return

            # 확인 - STEP 2, 3, 4 초기화
            self._reset_steps_234()

    # Rating 저장 및 STEP 2 활성화
    self.current_rating = rating
    self.step2.setEnabled(True)

# Line 466-489: STEP 2~4 초기화 메서드
def _reset_steps_234(self):
    """STEP 2, 3, 4 초기화"""
    # STEP 2 초기화
    self.current_person_count = {}
    if hasattr(self, 'step2'):
        self.step2.clear_selection()
        self.step2.setEnabled(True)

    # STEP 3 초기화
    self.current_special_tags = []
    if hasattr(self, 'step3'):
        self.step3.clear_selection()
        self.step3.setEnabled(False)

    # STEP 4 초기화
    self.current_general_tags = []
    if hasattr(self, 'step4'):
        self.step4.reset_all()
        self.step4.setEnabled(False)

    # 하단 프레임 업데이트
    self._update_bottom_frame()
```

**효과**:
- 실수로 rating 변경하여 모든 선택이 사라지는 것 방지
- 사용자가 명시적으로 확인 후 진행
- 취소 시 이전 상태 완전 복원

---

## 즉시 생성 시스템

### 개요

EZ Mode의 "즉시 생성" 기능은 선택한 모든 태그를 Main UI에 자동으로 할당하고 이미지 생성을 시작합니다.

**워크플로우**:
```
1. 사용자가 태그 선택 완료
2. 하단 "즉시 생성" 버튼 클릭
3. Controller가 Virtual Row (pandas.Series) 생성
4. 신호 체인: Controller → Window → MainWindow
5. MainWindow가 태그 할당 + 이미지 생성 시작
```

### Virtual Row 생성

**파일**: `ezmode_controller.py:254-342`

Virtual Row는 **Web View에서 클릭한 것과 동일한 구조**의 가상 데이터입니다.

**구조**:
```python
virtual_row = pd.Series({
    # 메인 태그 (모든 선택된 태그를 쉼표로 연결)
    'general': '1girl, 1boy, large_breasts, breasts, nipples, ...',

    # 메타 정보
    'meta': 'rating:explicit',  # rating 태그
    'rating': 'e',              # g/s/q/e

    # 출처 표시
    'source': 'EZ Mode',

    # 태그 개수
    'tag_count_general': 11,
    'tag_count_meta': 1,

    # 기타 Danbooru 호환 필드 (40+ fields)
    'character': '',
    'copyright': '',
    'artist': '',
    'id': 0,
    'score': 0,
    ...
})
```

**포함 태그 순서**:
1. **Person Count** (STEP 2): `1girl`, `1boy` 등
2. **Special Tags** (STEP 3): `large_breasts` 등
3. **General Tags** (STEP 4): `breasts`, `nipples`, `smile` 등

### 신호 흐름

**전체 체인**:

```python
# 1. Controller: 버튼 클릭
def _on_instant_generate(self):
    virtual_row = self._create_virtual_row()  # pandas.Series 생성
    self.instant_generation_requested.emit(virtual_row)

# 2. Window: 신호 릴레이
instant_generation_requested = pyqtSignal(object)  # pandas.Series 전달

# 3. MainWindow 연결 (NAIA_cold_v4.py)
self.ez_mode_window.instant_generation_requested.connect(
    self.on_generate_with_image_requested
)

# 4. MainWindow: 태그 할당 + 생성
def on_generate_with_image_requested(self, row: pd.Series):
    # row에서 태그 추출
    # Main UI에 할당
    # 이미지 생성 시작
```

**신호 타입 중요사항**:

⚠️ **pyqtSignal 타입은 반드시 `object`**:
```python
# ✅ 올바른 방법
instant_generation_requested = pyqtSignal(object)

# ❌ 잘못된 방법
instant_generation_requested = pyqtSignal(dict)  # pandas.Series는 dict가 아님!
```

### Rating 매핑

**파일**: `ezmode_controller.py:279-285`

```python
rating_map = {
    'g': 'rating:safe',
    's': 'rating:sensitive',
    'q': 'rating:questionable',
    'e': 'rating:explicit'
}
rating_tag = rating_map.get(self.current_rating, '')
```

**결과**:
- STEP 1에서 선택한 rating이 `meta` 필드에 `rating:xxx` 형태로 저장됨
- Main UI에서 이를 파싱하여 적절한 프롬프트 생성

### 디버깅 출력

**파일**: `ezmode_controller.py:335-341`

```python
print(f"[DEBUG] Virtual row created:")
print(f"  - Rating: {self.current_rating}")
print(f"  - Person Count: {list(self.current_person_count.keys())}")
print(f"  - Special Tags: {self.current_special_tags}")
print(f"  - General Tags ({len(self.current_general_tags)}): {self.current_general_tags[:5]}...")
print(f"  - Total tags: {len(all_tags)}")
```

**출력 예시**:
```
[DEBUG] Virtual row created:
  - Rating: e
  - Person Count: ['1girl', '1boy']
  - Special Tags: ['large_breasts']
  - General Tags (11): ['breasts', 'nipples', 'camisole lift', 'hetero', 'camisole']...
  - Total tags: 14
🚀 [Controller] Instant generation requested with virtual row
```

---

## 개발 가이드

### 새 STEP 추가하기

1. **파일 생성**: `ui/ezmode/ezmode_step5.py`

2. **기본 구조**:
```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import pyqtSignal

class EZModeStep5(QWidget):
    """STEP 5: Your Feature"""

    # 시그널 정의
    your_signal = pyqtSignal(dict)

    def __init__(self, data_manager, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.init_ui()
        self.setEnabled(False)  # 초기 비활성화

    def init_ui(self):
        # UI 구성
        pass

    def set_context(self, ...):
        """STEP 4 완료 시 호출"""
        self.setEnabled(True)
        # 데이터 초기화
```

3. **Controller 통합**:
```python
# ezmode_controller.py

# Import
from ui.ezmode.ezmode_step5 import EZModeStep5

# __init__에 추가
self.step5 = EZModeStep5(self.data_manager)
self.step5.your_signal.connect(self._on_your_event)
self.content_layout.addWidget(self.step5)

# 이전 STEP 완료 시 활성화
def _on_general_tags_selected(self, general_tags: list):
    # ...
    self.step5.set_context(...)
```

### 툴팁 추가하기

**Step 4 패턴 참고**:

```python
# 1. KR_tags 로드
self.kr_tags_df = pd.DataFrame()
self._load_kr_tags()

# 2. 툴팁 설정 메서드
def _set_tag_tooltip(self, button: QPushButton, tag: str):
    if self.kr_tags_df.empty:
        return

    matching_rows = self.kr_tags_df[self.kr_tags_df['tag'] == tag]
    if not matching_rows.empty:
        data = matching_rows.iloc[0]

        tooltip_lines = []
        if pd.notna(data.get('category')):
            tooltip_lines.append(f"Category: {data['category']}")
        if pd.notna(data.get('desc')):
            tooltip_lines.append(data['desc'])
        if pd.notna(data.get('keywords')):
            tooltip_lines.append(f"Keywords: {data['keywords']}")

        if tooltip_lines:
            button.setToolTip('\n'.join(tooltip_lines))

# 3. 버튼 생성 시 적용
tag_btn = QPushButton(tag)
self._set_tag_tooltip(tag_btn, tag)
```

### 스타일링 가이드

**필수 규칙**:
```python
from ui.theme import DARK_COLORS, DARK_STYLES
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

# ✅ 올바른 방법
button.setStyleSheet(f"""
    QPushButton {{
        font-size: {get_scaled_font_size(18)}px;
        background-color: {DARK_COLORS['bg_secondary']};
        padding: {get_scaled_size(8)}px;
    }}
""")

# ❌ 잘못된 방법
button.setStyleSheet("font-size: 18px; padding: 8px;")
```

---

## TODO: 미구현 기능

### 1. Hugging Face 데이터 다운로드

**파일**: `ezmode_downloader.py`

**현재 상태**: Mock 구현 (안내만 표시)

**구현 필요 사항**:

```python
class EZModeDownloader(QObject):
    """EZ Mode 데이터 다운로더 (Hugging Face)"""

    # 시그널
    download_progress = pyqtSignal(int, str)  # (percent, message)
    download_finished = pyqtSignal(bool, str)  # (success, message)

    def __init__(self):
        super().__init__()
        # TODO: Hugging Face API 초기화

    def start_download(self):
        """다운로드 시작"""
        # TODO: 구현 필요
        # 1. Hugging Face 저장소 연결
        # 2. data/ezmode/ 디렉터리 생성
        # 3. category_index.json 다운로드
        # 4. output.json 다운로드
        # 5. matrices/*.npz 다운로드 (104 x 3 = 312개 파일)
        # 6. 진행 상태 시그널 발행
        # 7. 완료 시그널 발행
```

**참고 구현**: `tabs/assets/artist_thumb.py:1080-1200` (ArtistThumbDownloader)

**Hugging Face 저장소**:
```
저장소: [YOUR_HF_REPO]/naia-ezmode-matrices
브랜치: main
파일명: ezmode_matrices.zip (2.7GB)

압축 해제 후 구조:
matrices/
├── e_multiple_1boy_1girl_furry_large_breasts_cooccur.npz
├── e_multiple_1boy_1girl_furry_large_breasts_pmi.npz
├── e_multiple_1boy_1girl_furry_large_breasts_condprob.npz
├── e_multiple_1boy_1girl_furry_large_breasts_metadata.json
├── ... (411 카테고리 × 4 파일 = 1,644개)
└── build_summary.json

압축 해제 위치: data/.ezmode/matrices/
```

**참고**:
- `category_index.json`과 `output.json`은 GitHub 저장소에 이미 포함됨
- Hugging Face에는 `matrices/` 폴더만 ZIP 압축하여 업로드
- 다운로드 후 `data/.ezmode/matrices/`에 자동 압축 해제

**다운로드 UI**:
```python
# ezmode_window.py

def _show_download_dialog(self, data_info: dict) -> bool:
    # 이미 구현됨 (Mock)
    # TODO: EZModeDownloader 연결

def _start_download(self):
    """다운로드 시작"""
    # TODO: 구현 필요
    self.downloader = EZModeDownloader()
    self.downloader.download_progress.connect(self._on_download_progress)
    self.downloader.download_finished.connect(self._on_download_finished)

    # 진행 다이얼로그 표시
    self.progress_dialog = QProgressDialog(
        "EZ Mode 데이터 다운로드 중...",
        "취소",
        0, 100,
        self
    )
    self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)

    # 다운로드 시작 (QThread)
    self.downloader.start_download()
```

### 2. 초기 설정 기능

**구현 필요 사항**:

1. **알고리즘 가중치 설정**:
   ```python
   # Settings 탭에 EZ Mode 섹션 추가

   class EZModeSettingsWidget(QWidget):
       """EZ Mode 설정"""

       def __init__(self):
           # Co-occurrence 가중치 슬라이더 (0-100%)
           self.cooccur_slider = QSlider()

           # Conditional Probability 가중치 슬라이더
           self.cond_slider = QSlider()

           # PMI 가중치 슬라이더
           self.pmi_slider = QSlider()

           # 합계 100% 검증

       def save_settings(self):
           # save/ezmode_settings.json
           settings = {
               'algorithm': {
                   'cooccur_weight': self.cooccur_slider.value() / 100,
                   'cond_weight': self.cond_slider.value() / 100,
                   'pmi_weight': self.pmi_slider.value() / 100
               },
               'ui': {
                   'highlight_threshold': 55,  # 노란색 표시 임계값
                   'recommendation_count': 48   # 추천 태그 수
               }
           }
   ```

2. **캐시 설정**:
   ```python
   # 최대 캐시 크기
   'cache': {
       'max_categories': 5,      # 최대 캐시된 카테고리 수
       'auto_clear_on_close': True  # 창 닫기 시 자동 정리
   }
   ```

3. **데이터 관리**:
   ```python
   # 데이터 위치 변경
   'data': {
       'base_path': 'data/ezmode/',  # 기본 경로
       'allow_custom_path': False     # 커스텀 경로 허용 여부
   }
   ```

### 3. 카테고리 필터링 시스템 (우선순위: 높음)

**파일**: `ezmode_step4.py` (신규 섹션 추가)

**목적**: 선택된 태그와 추천 태그 사이에 카테고리 필터 UI를 추가하여 특정 카테고리만 표시

**UI 위치**:
```
┌─────────────────────────────────────┐
│ [검색 바]                            │ ← 기존
├─────────────────────────────────────┤
│ 선택된 태그 영역 (150px)             │ ← 기존
├─────────────────────────────────────┤
│ 🆕 [카테고리 필터 섹션] (60-80px)    │ ← 신규 추가
│ [General] [Artist] [Character] ...  │
├─────────────────────────────────────┤
│ 추천 태그 영역 (나머지 공간)         │ ← 기존
└─────────────────────────────────────┘
```

#### 3.1 데이터 준비: 1차 카테고리 추출

**난이도**: ⭐⭐⭐ (복잡)

**파일**: `data/ezmode/category_primary.json` (신규 생성)

**목표**: `KR_tags.parquet`의 `category` 필드에서 " > " 이전의 1차 카테고리 목록 추출

**category 필드 형식 예시**:
```
"General > Body"
"General > Face"
"Artist > Style"
"Character > Original"
"Copyright > Series"
"Meta > Quality"
```

**구현 단계**:

1. **1차 카테고리 추출 스크립트 작성** (`utils/extract_primary_categories.py`):
   ```python
   import pandas as pd
   import json
   from pathlib import Path
   from collections import Counter

   def extract_primary_categories():
       """KR_tags.parquet에서 1차 카테고리 목록 추출"""

       # KR_tags.parquet 로드
       kr_tags_path = Path("data/KR_tags.parquet")
       if not kr_tags_path.exists():
           print("[ERROR] KR_tags.parquet not found")
           return

       df = pd.read_parquet(kr_tags_path)

       # category 필드에서 1차 카테고리 추출
       primary_categories = set()
       category_counts = Counter()

       for idx, row in df.iterrows():
           category = row.get('category')
           if pd.notna(category) and isinstance(category, str):
               # " > " 이전 부분 추출
               if ' > ' in category:
                   primary = category.split(' > ')[0].strip()
               else:
                   primary = category.strip()

               primary_categories.add(primary)
               category_counts[primary] += 1

       # 결과 정렬 (빈도순)
       sorted_categories = sorted(category_counts.items(),
                                  key=lambda x: x[1],
                                  reverse=True)

       # JSON 형식으로 저장
       result = {
           "categories": [cat for cat, count in sorted_categories],
           "counts": {cat: count for cat, count in sorted_categories},
           "total_tags": len(df),
           "categorized_tags": sum(category_counts.values())
       }

       output_path = Path("data/ezmode/category_primary.json")
       output_path.parent.mkdir(parents=True, exist_ok=True)

       with open(output_path, 'w', encoding='utf-8') as f:
           json.dump(result, f, indent=2, ensure_ascii=False)

       print(f"✅ Primary categories extracted: {len(primary_categories)}")
       print(f"   Output: {output_path}")
       print(f"\n📊 Top 10 categories:")
       for cat, count in sorted_categories[:10]:
           print(f"   {cat}: {count} tags")

   if __name__ == "__main__":
       extract_primary_categories()
   ```

2. **스크립트 실행**:
   ```bash
   python utils/extract_primary_categories.py
   ```

3. **예상 출력** (`data/ezmode/category_primary.json`):
   ```json
   {
     "categories": [
       "General",
       "Artist",
       "Character",
       "Copyright",
       "Meta",
       "Style",
       ...
     ],
     "counts": {
       "General": 25000,
       "Artist": 8000,
       "Character": 5000,
       ...
     },
     "total_tags": 40000,
     "categorized_tags": 38500
   }
   ```

#### 3.2 UI 구현: 카테고리 필터 버튼

**파일**: `ezmode_step4.py` (메서드 추가)

**구현 내용**:

1. **데이터 로딩**:
   ```python
   def _load_primary_categories(self):
       """1차 카테고리 목록 로드"""
       try:
           category_path = Path("data/ezmode/category_primary.json")
           if category_path.exists():
               with open(category_path, 'r', encoding='utf-8') as f:
                   data = json.load(f)
                   self.primary_categories = data.get("categories", [])
                   print(f"[OK] Primary categories loaded: {len(self.primary_categories)}")
           else:
               print("[WARN] category_primary.json not found, using defaults")
               self.primary_categories = ["General", "Artist", "Character", "Copyright", "Meta"]
       except Exception as e:
           print(f"[ERROR] Failed to load primary categories: {e}")
           self.primary_categories = []
   ```

2. **UI 섹션 추가** (선택된 태그와 추천 태그 사이):
   ```python
   def _create_category_filter_section(self) -> QWidget:
       """카테고리 필터 섹션 생성"""
       filter_frame = QFrame()
       filter_frame.setFixedHeight(get_scaled_size(70))
       filter_frame.setStyleSheet(f"""
           QFrame {{
               background-color: {DARK_COLORS['bg_tertiary']};
               border-top: 1px solid {DARK_COLORS['border']};
               border-bottom: 1px solid {DARK_COLORS['border']};
           }}
       """)

       layout = QVBoxLayout(filter_frame)
       layout.setContentsMargins(8, 8, 8, 8)
       layout.setSpacing(4)

       # 라벨
       label = QLabel("카테고리 필터:")
       label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(14)}px;")
       layout.addWidget(label)

       # 버튼 영역 (FlowLayout)
       btn_widget = QWidget()
       btn_layout = FlowLayout(btn_widget)
       btn_layout.setSpacing(4)

       # "전체" 버튼
       all_btn = QPushButton("전체")
       all_btn.setCheckable(True)
       all_btn.setChecked(True)  # 초기 상태: 전체 선택
       all_btn.clicked.connect(lambda: self._on_category_filter_all())
       self._style_category_button(all_btn, True)
       btn_layout.addWidget(all_btn)
       self.category_filter_buttons = {"전체": all_btn}

       # 카테고리 버튼들
       for category in self.primary_categories:
           btn = QPushButton(category)
           btn.setCheckable(True)
           btn.setChecked(False)
           btn.clicked.connect(lambda checked, cat=category: self._on_category_filter_toggled(cat, checked))
           self._style_category_button(btn, False)
           btn_layout.addWidget(btn)
           self.category_filter_buttons[category] = btn

       layout.addWidget(btn_widget)

       return filter_frame

   def _style_category_button(self, btn: QPushButton, is_all: bool):
       """카테고리 버튼 스타일 적용"""
       btn.setFixedHeight(get_scaled_size(28))
       btn.setStyleSheet(f"""
           QPushButton {{
               font-size: {get_scaled_font_size(14)}px;
               background-color: {DARK_COLORS['bg_secondary']};
               color: {DARK_COLORS['text_primary']};
               border: 1px solid {DARK_COLORS['border']};
               border-radius: {get_scaled_size(4)}px;
               padding: {get_scaled_size(4)}px {get_scaled_size(12)}px;
           }}
           QPushButton:checked {{
               background-color: {DARK_COLORS['accent_blue']};
               color: white;
               border-color: {DARK_COLORS['accent_blue']};
           }}
           QPushButton:hover {{
               background-color: {DARK_COLORS['bg_hover']};
           }}
       """)
   ```

3. **필터 로직**:
   ```python
   def _on_category_filter_all(self):
       """전체 카테고리 선택"""
       all_btn = self.category_filter_buttons["전체"]

       # 전체 버튼이 체크되면 다른 버튼 모두 해제
       if all_btn.isChecked():
           for cat, btn in self.category_filter_buttons.items():
               if cat != "전체":
                   btn.setChecked(False)

       # 추천 태그 다시 표시
       self._update_recommendations()

   def _on_category_filter_toggled(self, category: str, checked: bool):
       """특정 카테고리 필터 토글"""
       # 카테고리 버튼이 하나라도 체크되면 "전체" 해제
       if checked:
           self.category_filter_buttons["전체"].setChecked(False)
       else:
           # 모든 카테고리가 해제되면 "전체" 자동 체크
           any_checked = any(btn.isChecked() for cat, btn in self.category_filter_buttons.items() if cat != "전체")
           if not any_checked:
               self.category_filter_buttons["전체"].setChecked(True)

       # 추천 태그 다시 표시
       self._update_recommendations()

   def _get_active_category_filters(self) -> List[str]:
       """현재 활성화된 카테고리 필터 반환"""
       if self.category_filter_buttons["전체"].isChecked():
           return []  # 빈 리스트 = 필터 없음 (전체 표시)

       return [cat for cat, btn in self.category_filter_buttons.items()
               if cat != "전체" and btn.isChecked()]
   ```

4. **추천 태그 필터링 적용**:
   ```python
   def _display_recommended_tags(self, recommended_tags: List[Tuple[str, int, float]]):
       """추천 태그 표시 (카테고리 필터 적용)"""
       # 활성 필터 가져오기
       active_filters = self._get_active_category_filters()

       # 기존 버튼 제거
       for i in reversed(range(self.recommended_layout.count())):
           widget = self.recommended_layout.itemAt(i).widget()
           if widget:
               widget.deleteLater()

       # 필터링 및 표시
       displayed_count = 0
       for tag, score, cooccur_count in recommended_tags:
           # 카테고리 필터 적용
           if active_filters:
               tag_category = self._get_tag_primary_category(tag)
               if tag_category not in active_filters:
                   continue  # 필터에 맞지 않으면 건너뛰기

           # 버튼 생성 및 표시
           btn = self._create_tag_button(tag, score, cooccur_count)
           self.recommended_layout.addWidget(btn, displayed_count // 3, displayed_count % 3)
           displayed_count += 1

       print(f"[DEBUG] Displayed {displayed_count} tags (filters: {active_filters or 'None'})")

   def _get_tag_primary_category(self, tag: str) -> str:
       """태그의 1차 카테고리 반환"""
       if self.kr_tags_df.empty:
           return "General"  # 기본값

       matching_rows = self.kr_tags_df[self.kr_tags_df['tag'] == tag]
       if not matching_rows.empty:
           category = matching_rows.iloc[0].get('category')
           if pd.notna(category) and isinstance(category, str):
               if ' > ' in category:
                   return category.split(' > ')[0].strip()
               else:
                   return category.strip()

       return "General"  # 기본값
   ```

#### 3.3 통합 및 테스트

**init_ui() 수정**:
```python
def init_ui(self):
    # ... 기존 코드 ...

    # 선택된 태그 영역
    self.selected_tags_area = self._create_selected_tags_area()
    layout.addWidget(self.selected_tags_area)

    # 🆕 카테고리 필터 섹션 추가
    self.category_filter_section = self._create_category_filter_section()
    layout.addWidget(self.category_filter_section)

    # 추천 태그 영역
    self.recommended_scroll = self._create_recommended_area()
    layout.addWidget(self.recommended_scroll)
```

**테스트 시나리오**:
1. STEP 4 진입
2. 카테고리 필터에서 "General" 선택 → General 카테고리 태그만 표시
3. "Artist" 추가 선택 → General + Artist 카테고리 태그 표시
4. "전체" 클릭 → 모든 태그 표시

#### 3.4 구현 우선순위 및 난이도

| 단계 | 작업 | 난이도 | 우선순위 |
|------|------|--------|----------|
| 3.1 | 1차 카테고리 추출 스크립트 | ⭐⭐⭐ | 높음 |
| 3.2 | UI 구현 (필터 버튼) | ⭐⭐ | 높음 |
| 3.3 | 필터 로직 및 태그 표시 | ⭐⭐⭐ | 높음 |
| 3.4 | 테스트 및 디버깅 | ⭐⭐ | 높음 |

### 4. 고급 기능

**구현 우선순위 낮음**:

1. **태그 히스토리**:
   - 선택한 태그 조합 저장
   - 즐겨찾기 기능
   - 빠른 불러오기

2. **프리셋 시스템**:
   - "포트레이트"
   - "풍경"
   - "일러스트"
   - 사용자 정의 프리셋

3. **검색 고도화**:
   - 정규식 검색
   - 카테고리 필터
   - 태그 제외 검색

---

## 문제 해결

### Q1: 데이터가 로드되지 않아요

**증상**:
```
[WARN] KR_tags.parquet 파일을 찾을 수 없습니다.
[ERROR] category_index.json not found
```

**원인**: 데이터 파일 누락

**해결**:
1. `data/ezmode/` 디렉터리 확인
2. `category_index.json`, `output.json` 존재 확인
3. `matrices/` 디렉터리 및 312개 `.npz` 파일 확인
4. TODO: 다운로드 기능 구현 후 자동 다운로드

### Q2: 추천 태그가 이상해요

**증상**: 관련 없는 태그가 추천됨

**원인**:
1. 가중치 불균형
2. 매트릭스 데이터 오류
3. 태그 정규화 실패

**해결**:
```python
# 1. 가중치 조정
alpha_cooccur = 0.70  # Co-occurrence 비중 증가
alpha_cond = 0.10
alpha_pmi = 0.20

# 2. 디버깅 출력 추가
print(f"[DEBUG] Cooccur scores: {cooccur_scores[:10]}")
print(f"[DEBUG] Final scores: {final_scores[:10]}")

# 3. 태그 정규화 확인
print(f"[DEBUG] Tag variants: {self._normalize_tag(selected_tag)}")
```

### Q3: 메모리 사용량이 너무 높아요

**증상**: 메모리 1GB+ 사용

**원인**: 매트릭스 캐싱 과다

**해결**:
```python
# ezmode_data_manager.py

# 1. 캐시 크기 제한
MAX_CACHE_SIZE = 3  # 5 → 3으로 감소

# 2. LRU 캐시 구현
from collections import OrderedDict

self.matrices_cache = OrderedDict()

def load_category_matrices(self, category_id: int):
    # 캐시 크기 초과 시 가장 오래된 항목 제거
    if len(self.matrices_cache) >= MAX_CACHE_SIZE:
        self.matrices_cache.popitem(last=False)

    # 로드 및 캐싱
    ...
```

### Q4: UI가 느려요 (렉)

**증상**: 태그 클릭 시 지연, 버튼 생성 느림

**원인**: 메인 스레드에서 무거운 연산

**해결**:
```python
# QThread로 추천 계산 분리

class RecommendationWorker(QObject):
    finished = pyqtSignal(list)

    def __init__(self, data_manager, selected_tags):
        super().__init__()
        self.data_manager = data_manager
        self.selected_tags = selected_tags

    def run(self):
        # 추천 계산 (무거운 작업)
        recommended = self._calculate_recommendations()
        self.finished.emit(recommended)

# STEP 4에서 사용
self.worker_thread = QThread()
self.worker = RecommendationWorker(self.data_manager, self.selected_tags)
self.worker.moveToThread(self.worker_thread)
self.worker.finished.connect(self._on_recommendations_ready)
self.worker_thread.started.connect(self.worker.run)
self.worker_thread.start()
```

---

## 참고 자료

### 관련 문서

- **[ui/CLAUDE.md](../CLAUDE.md)**: 테마, 스케일링, 공용 위젯
- **[tabs/CLAUDE.md](../../tabs/CLAUDE.md)**: 탭 개발 (유사 패턴)
- **[data/CLAUDE.md](../../data/CLAUDE.md)**: 데이터베이스, Parquet 처리

### 데이터 소스

- **Danbooru**: https://danbooru.donmai.us/
- **태그 통계**: 3.2M+ 이미지 기반
- **Co-occurrence Matrix**: Sparse Matrix (CSR format)

### 알고리즘 참고

- **Co-occurrence Analysis**: https://en.wikipedia.org/wiki/Co-occurrence
- **Pointwise Mutual Information**: https://en.wikipedia.org/wiki/Pointwise_mutual_information
- **Conditional Probability**: https://en.wikipedia.org/wiki/Conditional_probability

### 유사 구현

| 기능 | 참고 파일 | 학습 포인트 |
|------|----------|------------|
| **Hugging Face 다운로드** | `tabs/assets/artist_thumb.py` | ArtistThumbDownloader 클래스 |
| **Progress Dialog** | `tabs/assets/artist_thumb.py` | 다운로드 진행 상태 표시 |
| **데이터 캐싱** | `core/filter_data_manager.py` | 메모리 관리, LRU 캐시 |
| **툴팁** | `NAIA_cold_v4.py:4463-4555` | show_prompt_context_menu |

---

## 요약

**EZ Mode의 핵심**:
- ✅ **4단계 가이드**: Rating → Person → Special → General
- ✅ **AI 추천**: Co-occurrence Matrix 기반
- ✅ **즉시 생성**: 선택 → 생성 원클릭
- ✅ **툴팁**: KR_tags 정보 표시

**완료된 기능**:
- ✅ 전체 UI 구조
- ✅ 데이터 로딩 시스템
- ✅ Hybrid 추천 알고리즘 (CoOccur 70%, CondProb 10%, PMI 20%)
- ✅ 신호 흐름 통합
- ✅ 툴팁 기능 (KR_tags 정보 표시)
- ✅ 언더바 태그 필터링 (추천에서 제외)
- ✅ STEP 3 태그 기반 초기 추천 (노란색 태그 표시)

**TODO (우선순위 순)**:
1. 🔴 **카테고리 필터링 시스템** (높음) - 1차 카테고리 추출 및 필터 UI
2. 🔴 **Hugging Face 다운로드** (필수)
3. 🟡 **초기 설정 UI** (권장)
4. 🟢 **고급 기능** (선택)

**다음 단계**:
1. Hugging Face 저장소 생성
2. EZModeDownloader 구현
3. Settings 탭에 EZ Mode 섹션 추가

---

## 변경 이력

### v1.2 (2025-01-19)

**🔧 버그 수정 및 개선**:
- **언더바 태그 필터링** (`ezmode_step4.py:648-650, 723-725`)
  - 추천 결과에서 `_` 포함 태그 제외 (예: `large_breasts` → 제외, `large breasts` → 표시)
  - `_get_recommended_tags()` 및 `_get_popular_tags()` 모두 적용
- **STEP 3 태그 기반 초기 추천** (`ezmode_step4.py:529-533`)
  - STEP 4 초기 로드 시 STEP 3 태그를 사용하여 Hybrid 추천 계산
  - 기존: 전역 인기도만 사용 → 모든 태그 낮은 점수 (노란색 없음)
  - 수정: STEP 3 태그로 추천 계산 → 관련 태그들 55+ 점수 (노란색 표시)

**📝 문서화**:
- 언더바 태그 필터링 섹션 추가
- STEP 3 태그 기반 초기 추천 섹션 추가
- TODO: 카테고리 필터링 시스템 상세 가이드 추가 (3.1-3.4)

### v1.1 (2025-01-19)

**🚀 즉시 생성 기능 구현**:
- Virtual Row 생성 로직 추가 (`ezmode_controller.py:254-342`)
- pandas.Series 기반 Web View 호환 구조
- 신호 타입 수정: `pyqtSignal(dict)` → `pyqtSignal(object)`
- 하단 고정 프레임: "선택된 태그: N개" + "즉시 생성" 버튼
- Main UI 태그 할당 및 이미지 생성 연동 완료

**🎨 UI 개선**:
- 윈도우 기본 너비 25% 감소: 1200px → 900px
- Controller 100% 너비 유지 (Placeholder 제거)
- 태그 버튼 KR_tags 툴팁 기능 추가

**⚙️ 알고리즘 개선**:
- Hybrid 추천 가중치 조정: CoOccur 70%, CondProb 10%, PMI 20%
- Min-Max Scaling 적용으로 0-99 점수 정규화
- 55점 이상 노란색 하이라이팅

**📝 문서화**:
- 즉시 생성 시스템 섹션 추가
- Virtual Row 구조 상세 설명
- 신호 흐름 다이어그램
- Rating 매핑 테이블

### v1.0 (2025-01-18)

**초기 릴리스**:
- 4단계 가이드 시스템 (Rating → Person → Special → General)
- Co-occurrence Matrix 기반 추천 시스템
- EZModeDataManager 데이터 로딩 및 캐싱
- 의존성 체크 및 다운로드 안내 UI
- 카테고리별 태그 분류 (104개 카테고리)

---

*문서 버전: 1.2*
*최종 업데이트: 2025-01-19 (v1.2 - 언더바 필터링, STEP 3 기반 초기 추천, 카테고리 필터링 TODO)*
*담당 영역: ui/ezmode/ 디렉터리*
*작성자: Claude Code*
