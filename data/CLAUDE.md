# CLAUDE.md — data/

> **목적**: NAIA 2.0의 정적 데이터 파일 저장소. 태그 데이터베이스, 필터 사전, 와일드카드 지원을 위한 데이터를 관리합니다.

---

## 목차

1. [개요](#개요)
2. [주요 파일 및 역할](#주요-파일-및-역할)
3. [텍스트 사전 파일](#텍스트-사전-파일)
4. [Parquet 태그 데이터베이스](#parquet-태그-데이터베이스)
5. [EZ Mode 데이터](#ez-mode-데이터)
6. [데이터 로딩 패턴](#데이터-로딩-패턴)
7. [실전 예제](#실전-예제)
8. [문제 해결](#문제-해결)
9. [체크리스트](#체크리스트)
10. [참고 자료](#참고-자료)
11. [요약](#요약)

---

## 개요

### data/ 디렉터리의 역할

data/는 NAIA 2.0의 **정적 데이터 저장소**로, 다음을 담당합니다:

- 📊 **태그 데이터베이스**: Parquet 형식의 대용량 태그 정보 (data/tags/)
- 📝 **필터 사전**: 특징/의류 태그 목록 (characteristic_list.txt, clothes_list.txt)
- 🔍 **검색 인덱스**: 멀티프로세싱 기반 고속 태그 검색
- 🤖 **EZ Mode 데이터**: 카테고리 인덱스 및 Co-occurrence 매트릭스 (data/ezmode/, data/.ezmode/)
- 🎨 **UI 지원**: 자동완성, 태그 정보 툴팁, 필터링

### 아키텍처

```
data/
  ├── tags/                    # Parquet 태그 데이터베이스
  │   ├── tags_00.parquet      # 분할된 데이터 파일
  │   ├── tags_01.parquet
  │   └── ...tags_129.parquet  # 130개 파일
  ├── characteristic_list.txt  # 특징 태그 사전 (1006개)
  ├── clothes_list.txt         # 의류 태그 사전 (3700개)
  ├── ezmode/                  # EZ Mode JSON 파일 (GitHub, 668KB)
  │   ├── category_index.json  # 카테고리 인덱스 (411개 카테고리)
  │   ├── output.json          # 태그 인덱스
  │   └── category_tags_merged.json  # 카테고리별 태그 목록
  └── .ezmode/                 # EZ Mode 매트릭스 (Hugging Face, 2.7GB)
      └── matrices/            # Co-occurrence 매트릭스 (1645개 파일)
          ├── build_summary.json
          ├── {category}_cooccur.npz
          ├── {category}_pmi.npz
          ├── {category}_condprob.npz
          └── {category}_metadata.json
```

**데이터 흐름**:
```
data/tags/*.parquet
    ↓ (멀티프로세싱 로드)
core/search_controller.py → core/search_engine.py
    ↓ (검색 결과)
tabs/search_tab.py (UI 표시)

data/characteristic_list.txt, clothes_list.txt
    ↓ (동기 로드)
core/filter_data_manager.py
    ↓ (필터링)
modules/ (모듈별 태그 제안)

data/ezmode/*.json
    ↓ (초기 로드)
ui/ezmode/ezmode_data_manager.py
    ↓ (카테고리 정보)
ui/ezmode/ezmode_step*.py (STEP 1~3 UI)

data/.ezmode/matrices/*.npz
    ↓ (LRU 캐싱, 최대 3개)
ui/ezmode/ezmode_data_manager.py
    ↓ (Co-occurrence 추천)
ui/ezmode/ezmode_step4.py (태그 추천)
```

### 다른 디렉터리와의 관계

```
data/
  ├── core/search_engine.py → Parquet 파일 검색
  ├── core/filter_data_manager.py → 텍스트 사전 로드
  ├── ui/modern_menu.py → 태그 정보 툴팁
  └── tabs/search_tab.py → 검색 UI
```

### 언제 data/를 수정하는가?

| 작업 | 수정 파일 |
|------|----------|
| **새 필터 사전 추가** | `data/*.txt` |
| **태그 데이터베이스 업데이트** | `data/tags/*.parquet` |
| **사전 항목 추가/수정** | `data/characteristic_list.txt`, `data/clothes_list.txt` |
| **데이터 구조 변경** | ⚠️ `core/search_engine.py`, `core/filter_data_manager.py` 함께 수정 |

⚠️ **주의**: 데이터 파일 구조 변경 시 소비자 코드 영향 확인 필수!

---

## 주요 파일 및 역할

### 파일 목록

| 파일/디렉터리 | 크기 | 역할 | 주요 사용처 |
|--------------|------|------|-----------|
| **tags/** | ~100MB+ | 130개로 분할된 태그 데이터베이스 | `core/search_controller.py`, `core/search_engine.py` |
| **tags/tags_00.parquet** | ~800KB | 첫 번째 분할 (44,887 rows) | 검색 엔진 |
| **tags/tags_01.parquet ~ tags_129.parquet** | 각 ~800KB | 나머지 분할 | 검색 엔진 |
| **characteristic_list.txt** | 34KB | 특징 태그 1006개 (신체/눈/머리/피부/꼬리/귀/날개/뿔/헤일로 등) | `core/filter_data_manager.py` |
| **clothes_list.txt** | 156KB | 의류 태그 3700개 (옷/신발/액세서리/장신구/헤어 등) | `core/filter_data_manager.py` |

### 데이터 구조

#### tags/*.parquet 스키마

| 컬럼 | 타입 | 설명 | 예시 |
|------|------|------|------|
| `id` | int64 | 이미지 고유 ID | 2229767 |
| `copyright` | object (str) | 저작권 태그 (출처) | "original", "kantai_collection" |
| `character` | object (str) | 캐릭터 태그 | "hatsune_miku", "original" |
| `artist` | object (str) | 아티스트 태그 | "artist_name", "unknown_artist" |
| `general` | object (str) | 일반 태그 (쉼표 구분) | "1girl, long hair, blue eyes" |
| `meta` | object (str) | 메타 태그 (품질/스타일) | "masterpiece, highres" |
| `rating` | object (str) | 등급 | "safe", "questionable", "explicit" |
| `score` | int64 | 점수 | 50 |
| `created_at` | object (str) | 생성 날짜 | "2023-01-01 12:00:00" |
| `tokens` | int64 | 토큰 수 | 120 |
| `image_width` | int32 | 이미지 너비 | 1024 |
| `image_height` | int32 | 이미지 높이 | 1536 |

**예시 row**:
```python
{
    'id': 2229767,
    'copyright': 'original',
    'character': '',
    'artist': '某个作者',
    'general': '1girl, solo, long hair, blue eyes, smile, dress, ...',
    'meta': 'masterpiece, best quality, highres',
    'rating': 'safe',
    'score': 85,
    'created_at': '2023-05-15 10:30:00',
    'tokens': 150,
    'image_width': 1024,
    'image_height': 1536
}
```

#### characteristic_list.txt 형식

**한 줄에 하나의 태그** (1006개):

```
flat chest
small breasts
medium breasts
large breasts
huge breasts
aqua eyes
black eyes
blue eyes
...
```

**카테고리** (묵시적, 순서로 구분):
1. 가슴 크기 (1-5)
2. 눈 색상 (6-20)
3. 눈동자 색상 (21-31)
4. 귀 (32-33)
5. 머리 색상/스타일 (34-205)
6. 피부 색상 (206-221)
7. 꼬리 (221-901)
8. 귀 (251-283, 동물귀)
9. 날개 (311-377)
10. 눈동자 형태 (378-401)
11. 눈 특징 (402-427)
12. 입술 색상 (429-439)
13. 직업/역할 (519-628)
14. 종족 (732-997)

#### clothes_list.txt 형식

**한 줄에 하나의 태그** (3700개):

```
balaclava
crown
hair bow
hair ribbon
hairband
...
```

**카테고리** (묵시적):
1. 머리 장식 (1-14)
2. 상의 (16-78)
3. 하의 (79-114)
4. 신발 (115-158)
5. 전신 의상 (159-295)
6. 액세서리 (295-378)
7. 패턴/프린트 (379-424)
8. 장식 (425-437)
9. 스타일 (438-457)
10. 드레스 (458-525)
11. 안경 (526-593)
12. 양말/스타킹 (594-664)
13. 목 장식 (665-706)
14. 소매 (707-757)
15. 속옷/란제리 (758-806)
16. 기타 의상 (807-3700)

---

## 텍스트 사전 파일

### 로딩 및 사용

**파일**: `core/filter_data_manager.py:4-41`

#### FilterDataManager 클래스

```python
class FilterDataManager:
    """data/ 디렉토리의 필터용 텍스트 파일들을 로드하고 관리"""

    def __init__(self, data_dir: str = 'data'):
        self.data_dir = data_dir

        # 각 텍스트 파일의 태그 목록
        self.clothes_list: List[str] = []
        self.characteristic_list: List[str] = []

        # 클래스 생성 시 모든 파일 로드
        self.load_all_filters()

    def _load_list_from_file(self, filename: str) -> List[str]:
        """지정된 파일에서 한 줄에 하나씩 있는 태그를 읽어 리스트로 반환"""
        file_path = os.path.join(self.data_dir, filename)

        if not os.path.exists(file_path):
            print(f"⚠️ 필터 파일 없음: {file_path}")
            return []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                # 비어있지 않은 라인만 읽어서 앞뒤 공백 제거
                tags = [line.strip() for line in f if line.strip()]
            print(f"✅ 필터 파일 로드 완료: {filename} ({len(tags)}개 태그)")
            return tags
        except Exception as e:
            print(f"❌ 필터 파일 로드 오류 ({filename}): {e}")
            return []

    def load_all_filters(self):
        """정의된 모든 필터 파일을 로드"""
        self.clothes_list = self._load_list_from_file('clothes_list.txt')
        self.characteristic_list = self._load_list_from_file('characteristic_list.txt')
```

#### 사용 예시

```python
from core.filter_data_manager import FilterDataManager

# 초기화
filter_manager = FilterDataManager(data_dir='data')

# 의류 태그 목록 가져오기
clothes = filter_manager.clothes_list
print(f"의류 태그 수: {len(clothes)}")  # 3700개
print(f"첫 10개: {clothes[:10]}")

# 특징 태그 목록 가져오기
characteristics = filter_manager.characteristic_list
print(f"특징 태그 수: {len(characteristics)}")  # 1006개

# 특정 태그 검색
if "long hair" in characteristics:
    print("✅ 'long hair' 태그 존재")

# 필터링 예시
def filter_by_category(tags, category_start_index, category_end_index):
    """카테고리별로 태그 필터링"""
    return tags[category_start_index:category_end_index]

# 눈 색상 태그만 추출 (6-20번째)
eye_colors = characteristics[5:20]
print(f"눈 색상 태그: {eye_colors}")
```

### 파일 형식 규칙

1. **UTF-8 인코딩** 필수
2. **한 줄에 하나의 태그**
3. **공백 라인 무시**
4. **주석 미지원** (모든 라인이 태그로 간주)
5. **대소문자 구분** (파일에 저장된 대로 사용)

### 새 사전 파일 추가

1. **파일 생성** (`data/my_new_list.txt`)
   ```
   tag1
   tag2
   tag3
   ```

2. **FilterDataManager 수정** (`core/filter_data_manager.py`)
   ```python
   class FilterDataManager:
       def __init__(self, data_dir: str = 'data'):
           # ... 기존 코드 ...
           self.my_new_list: List[str] = []  # 🆕 추가

       def load_all_filters(self):
           # ... 기존 코드 ...
           self.my_new_list = self._load_list_from_file('my_new_list.txt')  # 🆕 추가
   ```

3. **사용**
   ```python
   filter_manager = FilterDataManager()
   my_tags = filter_manager.my_new_list
   ```

---

## Parquet 태그 데이터베이스

### 분할 전략

**왜 130개 파일로 분할?**

1. **메모리 효율**: 전체 데이터를 한 번에 로드하지 않음
2. **멀티프로세싱**: 각 프로세스가 독립적으로 파일 처리
3. **병렬 검색**: CPU 코어 수만큼 동시 처리
4. **캐싱 효율**: 작은 파일은 디스크 캐시 효과 증대

**파일 크기**:
- 각 파일: ~800KB
- 총 크기: ~100MB+
- 각 파일: ~30,000-50,000 rows

### 검색 엔진 구조

**파일**: `core/search_controller.py:8-113`

#### SearchWorker (멀티프로세싱 워커)

```python
class SearchWorker(QObject):
    """실제 검색 작업을 수행하는 백그라운드 워커"""

    progress_updated = pyqtSignal(int, int)  # (완료된 수, 전체 수)
    partial_result_ready = pyqtSignal(object)  # 부분 검색 결과
    search_finished = pyqtSignal(int)  # 최종 결과 수
    error_occurred = pyqtSignal(str)

    def __init__(self, search_params: dict, tags_dir: str = 'data/tags'):
        super().__init__()
        self.search_params = search_params
        self.tags_dir = tags_dir
        self.is_cancelled = False

    def run_search(self):
        """멀티프로세싱을 사용하여 검색 실행"""
        # 파일 목록 가져오기
        files_to_search = [
            os.path.join(self.tags_dir, f)
            for f in os.listdir(self.tags_dir)
            if f.endswith('.parquet')
        ]

        if not files_to_search:
            self.error_occurred.emit("검색할 .parquet 파일이 없습니다.")
            return

        engine = SearchEngine()
        process_args = [(file, self.search_params) for file in files_to_search]
        total_files = len(files_to_search)
        completed_count = 0
        total_rows = 0

        try:
            # CPU 코어의 절반 사용 (최대 8개)
            num_processes = min(cpu_count() // 2, 8)
            if num_processes == 0:
                num_processes = 1

            with Pool(processes=num_processes) as pool:
                # 결과가 나오는 즉시 처리
                results_iterator = pool.starmap(engine.search_in_file, process_args)

                for df_result in results_iterator:
                    if self.is_cancelled:
                        pool.terminate()
                        break

                    completed_count += 1
                    if df_result is not None and not df_result.empty:
                        total_rows += len(df_result)
                        # 부분 결과 즉시 전달 (UI 갱신)
                        self.partial_result_ready.emit(df_result)

                    # 진행률 업데이트
                    self.progress_updated.emit(completed_count, total_files)

            if self.is_cancelled:
                self.search_finished.emit(0)
                return

            self.search_finished.emit(total_rows)

        except Exception as e:
            self.error_occurred.emit(f"검색 중 오류 발생: {e}")

    def cancel(self):
        """검색 취소"""
        self.is_cancelled = True
```

#### SearchController (UI 연결)

```python
class SearchController(QObject):
    """UI와 SearchEngine을 중재하고 비동기 검색을 관리"""

    search_progress = pyqtSignal(int, int)  # 진행률
    partial_search_result = pyqtSignal(object)  # 부분 결과
    search_complete = pyqtSignal(int)  # 완료
    search_error = pyqtSignal(str)  # 에러

    def __init__(self):
        super().__init__()
        self.worker_thread = None
        self.worker = None

    def start_search(self, search_params: dict):
        """비동기 검색 시작"""
        # QThread 생성
        self.worker_thread = QThread()
        self.worker = SearchWorker(search_params)
        self.worker.moveToThread(self.worker_thread)

        # 시그널 연결
        self.worker.progress_updated.connect(self.search_progress)
        self.worker.partial_result_ready.connect(self.partial_search_result)
        self.worker.search_finished.connect(self.on_search_finished)
        self.worker.error_occurred.connect(self.search_error)

        # 스레드 시작
        self.worker_thread.started.connect(self.worker.run_search)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.start()

    def cancel_search(self):
        """진행 중인 검색 취소"""
        if self.worker:
            self.worker.cancel()
        if self.worker_thread:
            self.worker_thread.quit()
            self.worker_thread.wait()

    def on_search_finished(self, total_count: int):
        """검색 완료 시 스레드 정리"""
        self.search_complete.emit(total_count)
        if self.worker_thread:
            self.worker_thread.quit()
```

### Parquet 파일 읽기

```python
import pandas as pd

# 단일 파일 로드
df = pd.read_parquet('data/tags/tags_00.parquet')
print(df.head())

# 컬럼 확인
print(df.columns.tolist())
# ['id', 'copyright', 'character', 'artist', 'general', 'meta', 'rating', 'score', 'created_at', 'tokens', 'image_width', 'image_height']

# 특정 태그 검색
query_tags = ['1girl', 'long hair']
matches = df[df['general'].str.contains('1girl', na=False)]
print(f"검색 결과: {len(matches)}개")

# 필터링
safe_images = df[df['rating'] == 'safe']
high_score = df[df['score'] > 50]
large_images = df[(df['image_width'] >= 1024) & (df['image_height'] >= 1024)]
```

### 데이터베이스 업데이트

1. **새 데이터 준비**
   ```python
   import pandas as pd

   # 새 데이터프레임 생성
   new_data = pd.DataFrame({
       'id': [1000000, 1000001],
       'copyright': ['original', 'original'],
       'character': ['', ''],
       'artist': ['artist_a', 'artist_b'],
       'general': ['1girl, solo, smile', '1boy, standing'],
       'meta': ['highres', 'highres'],
       'rating': ['safe', 'safe'],
       'score': [100, 80],
       'created_at': ['2025-01-01', '2025-01-02'],
       'tokens': [50, 40],
       'image_width': [1024, 1536],
       'image_height': [1536, 1024]
   })
   ```

2. **기존 파일과 병합**
   ```python
   # 기존 파일 로드
   old_df = pd.read_parquet('data/tags/tags_00.parquet')

   # 병합
   merged_df = pd.concat([old_df, new_data], ignore_index=True)

   # 중복 제거 (id 기준)
   merged_df = merged_df.drop_duplicates(subset=['id'], keep='last')

   # 저장
   merged_df.to_parquet('data/tags/tags_00.parquet')
   ```

3. **재분할 (필요 시)**
   ```python
   # 전체 데이터 로드
   all_data = []
   for i in range(130):
       file_path = f'data/tags/tags_{i:02d}.parquet'
       if os.path.exists(file_path):
           df = pd.read_parquet(file_path)
           all_data.append(df)

   full_df = pd.concat(all_data, ignore_index=True)

   # 130개로 재분할
   chunk_size = len(full_df) // 130
   for i in range(130):
       start_idx = i * chunk_size
       end_idx = start_idx + chunk_size if i < 129 else len(full_df)
       chunk_df = full_df.iloc[start_idx:end_idx]
       chunk_df.to_parquet(f'data/tags/tags_{i:02d}.parquet')
   ```

---

## EZ Mode 데이터

### 데이터 분리 전략

**2025-01-19 업데이트**: EZ Mode 데이터는 **크기에 따라 GitHub와 Hugging Face로 분리**하여 관리합니다.

| 위치 | 저장소 | 크기 | 파일 | 용도 |
|------|--------|------|------|------|
| `data/ezmode/` | **GitHub** | 668KB | JSON 파일 (3개) | 카테고리 인덱스, 태그 인덱스 |
| `data/.ezmode/matrices/` | **Hugging Face** | 2.7GB | Sparse 매트릭스 (1645개) | Co-occurrence 추천 데이터 |

**분리 이유**:
1. **GitHub 파일 크기 제한**: 100MB 이상 파일은 Git LFS 필요
2. **버전 관리 효율**: JSON 메타데이터는 자주 변경, 매트릭스는 정적
3. **다운로드 선택성**: 사용자가 필요할 때만 매트릭스 다운로드

### JSON 파일 (GitHub)

**위치**: `data/ezmode/`

#### 1. category_index.json

411개 카테고리의 메타데이터 및 UI 트리 구조.

**구조**:
```json
{
  "metadata": {
    "total_categories": 411,
    "version": "2025-01-19"
  },
  "categories": {
    "g_solo_1girl": {
      "rating": "g",
      "person_type": "solo",
      "person_count": {"1girl": 1},
      "special_tags": [],
      "tag_count": 12345
    },
    "e_multiple_1girl_many_boys": {
      "rating": "e",
      "person_type": "multiple",
      "person_count": {"1girl": 1, "many_boys": 3},
      "special_tags": [],
      "tag_count": 5678
    }
  },
  "ui_tree": {
    "g": {
      "solo": {
        "1girl": [
          {"category_id": "g_solo_1girl", "label": "일반", "special_tags": []},
          {"category_id": "g_solo_1girl_small_breasts", "label": "작은 가슴", "special_tags": ["small_breasts"]}
        ]
      }
    }
  },
  "available_options": {
    "ratings": ["g", "s", "q", "e"],
    "person_types": ["solo", "multiple"]
  }
}
```

**사용**:
- `ui/ezmode/ezmode_step1.py`: Rating 선택
- `ui/ezmode/ezmode_step2.py`: Person Count 선택
- `ui/ezmode/ezmode_step3.py`: Special Tags 선택

#### 2. output.json

전체 태그 목록 및 인덱스 (태그명 → 인덱스 매핑).

**구조**:
```json
{
  "1girl": 123456,
  "smile": 98765,
  "long_hair": 87654,
  ...
}
```

**사용**:
- `ui/ezmode/ezmode_data_manager.py`: 태그 인덱스 생성 (`tag_index`, `index_tag`)

#### 3. category_tags_merged.json

카테고리별로 사용 가능한 태그 목록 (필터링용).

**구조**:
```json
{
  "g_solo_1girl": ["1girl", "solo", "smile", "long_hair", ...],
  "e_multiple_1girl_many_boys": ["1girl", "hetero", "sex", ...]
}
```

**사용**:
- `ui/ezmode/ezmode_step4.py`: 카테고리 필터 (STEP 3 태그에 의한 필터링)

### 매트릭스 파일 (Hugging Face)

**위치**: `data/.ezmode/matrices/`

**다운로드 URL**:
```
https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/tags_70_tags_129_matrices.zip
```

**파일 구조** (카테고리당 4개 파일):
```
{category_id}_cooccur.npz     # Co-occurrence 매트릭스 (공출현 횟수)
{category_id}_pmi.npz          # Pointwise Mutual Information (연관성)
{category_id}_condprob.npz     # Conditional Probability (조건부 확률)
{category_id}_metadata.json    # 매트릭스 메타데이터
```

**예시**:
```
g_solo_1girl_cooccur.npz
g_solo_1girl_pmi.npz
g_solo_1girl_condprob.npz
g_solo_1girl_metadata.json
```

#### build_summary.json

전체 매트릭스 빌드 정보 (무결성 검증용).

**구조**:
```json
{
  "build_date": "2025-01-19",
  "total_categories": 411,
  "total_files": 1645,
  "version": "1.0"
}
```

**사용**:
- `ui/ezmode/ezmode_downloader.py`: 다운로드 후 무결성 검증
  - `build_summary.json` 존재 여부 확인
  - 전체 파일 수 1645개 검증 (80% 이상 = 1316개 이상)

### Person Count 정규화

**문제**: 매트릭스 파일명은 `many_boys`를 사용하지만, UI에서는 `3boys`, `4boys` 등을 표시.

**해결** (`ui/ezmode/ezmode_data_manager.py:226-254`):

```python
def _normalize_person_count(self, person_tag: str) -> str:
    """Person count 태그 정규화 (3+ → many_)

    Args:
        person_tag: 원본 태그 (예: '3boys', '4girls', '6+others')

    Returns:
        str: 정규화된 태그 (예: 'many_boys', 'many_girls', 'many_others')
    """
    replacements = {
        # boys
        '3boys': 'many_boys',
        '4boys': 'many_boys',
        '5boys': 'many_boys',
        '6+boys': 'many_boys',
        # girls
        '3girls': 'many_girls',
        '4girls': 'many_girls',
        '5girls': 'many_girls',
        '6+girls': 'many_girls',
        # others
        '3others': 'many_others',
        '4others': 'many_others',
        '5others': 'many_others',
        '6+others': 'many_others',
    }
    return replacements.get(person_tag, person_tag)
```

**적용 위치**:
- `build_category_id()`: 매트릭스 파일 경로 생성 시 정규화 적용
- Virtual Row: 프롬프트에는 원본 태그 유지 (예: `3boys`)

### 데이터 로딩 패턴

#### 초기 로드 (동기)

**파일**: `ui/ezmode/ezmode_data_manager.py:37-71`

```python
def load_initial_data(self) -> bool:
    """초기 데이터 로드 (category_index, tag_index)"""
    try:
        # 1. category_index.json
        category_path = self.data_dir / 'category_index.json'
        with open(category_path, 'r', encoding='utf-8') as f:
            self.category_index = json.load(f)

        # 2. output.json
        output_path = self.data_dir / 'output.json'
        with open(output_path, 'r', encoding='utf-8') as f:
            tag_totals = json.load(f)

        tags = sorted(tag_totals.keys())
        self.tag_index = {tag: idx for idx, tag in enumerate(tags)}
        self.index_tag = {idx: tag for tag, idx in self.tag_index.items()}

        self.data_loaded.emit()
        return True
    except Exception as e:
        self.load_error.emit(f"Data load failed: {e}")
        return False
```

**특징**:
- **동기 로딩**: UI 초기화 전 완료 필요
- **빠른 로딩**: JSON 파일 총 668KB로 1초 이내 완료
- **시그널 발행**: `data_loaded` 또는 `load_error`

#### 매트릭스 로드 (LRU 캐싱)

**파일**: `ui/ezmode/ezmode_data_manager.py:105-148`

```python
def load_matrices(self, category_id: str) -> Optional[Dict]:
    """매트릭스 로드 (캐싱)"""
    # 1. 캐시 확인
    if category_id in self.matrix_cache:
        print(f"[CACHE] Matrix loaded from cache: {category_id}")
        return self.matrix_cache[category_id]

    # 2. 디스크에서 로드
    try:
        base_path = self.matrices_dir / category_id

        matrices = {
            'cooccur': load_npz(f"{base_path}_cooccur.npz"),
            'pmi': load_npz(f"{base_path}_pmi.npz"),
            'condprob': load_npz(f"{base_path}_condprob.npz")
        }

        with open(f"{base_path}_metadata.json", 'r', encoding='utf-8') as f:
            matrices['metadata'] = json.load(f)

        # 3. LRU 캐시에 추가 (최대 3개)
        self._add_to_cache(category_id, matrices)

        return matrices
    except Exception as e:
        print(f"[ERROR] Matrix load failed ({category_id}): {e}")
        return None
```

**특징**:
- **LRU 캐싱**: 최대 3개 카테고리 캐싱
- **Scipy CSR**: Sparse 매트릭스 형식으로 메모리 효율
- **On-demand**: STEP 4에서 태그 선택 시에만 로드

#### 다운로드 (QThread)

**파일**: `ui/ezmode/ezmode_downloader.py:16-171`

**동작 흐름**:
```
1. 사용자가 EZ Mode 열기
2. check_ezmode_data_exists() 검증
   - build_summary.json 확인
   - 파일 수 1645개 (또는 80% 이상) 확인
3. 불완전 시 다운로드 다이얼로그 표시
4. EZModeDownloadWorker (QThread) 시작
   - Hugging Face ZIP 다운로드 (진행률 표시)
   - data/.ezmode/matrices/로 압축 해제
   - build_summary.json 검증
5. 완료 시 EZ Mode UI 표시
```

**주요 메서드**:
- `check_ezmode_data_exists()`: 데이터 존재 및 무결성 확인
- `get_data_directory_info()`: 상세 상태 정보 조회
- `_download_zip()`: 다운로드 (진행률 콜백)
- `_extract_zip()`: 압축 해제 (파일명만 추출, 경로 제거)

### 사용 예시

#### EZ Mode 데이터 확인

```python
from ui.ezmode.ezmode_downloader import check_ezmode_data_exists, get_data_directory_info

# 데이터 존재 확인
if check_ezmode_data_exists():
    print("[OK] EZ Mode 데이터 준비 완료")
else:
    # 상세 정보 조회
    info = get_data_directory_info()
    print(f"[!] 데이터 불완전: {info['matrices_count']}/{info['expected_count']}")
    print(f"    build_summary 존재: {info['build_summary_exists']}")
```

#### 카테고리 정보 조회

```python
from ui.ezmode.ezmode_data_manager import EZModeDataManager

manager = EZModeDataManager()
manager.load_initial_data()

# Rating 목록
ratings = manager.get_available_ratings()  # ['g', 's', 'q', 'e']

# Person Count 목록
person_counts = manager.get_available_person_counts('g', 'solo')
# ['1girl', '1boy', '1other']

# Special Tags 옵션
options = manager.get_available_options('g', 'solo', '1girl')
# [{'category_id': 'g_solo_1girl', 'label': '일반', 'special_tags': []}, ...]
```

#### 매트릭스 로드 및 추천

```python
# 카테고리 ID 생성
category_id = manager.build_category_id(
    rating='g',
    person_type='solo',
    person_count={'1girl': 1},
    special_tags=[]
)  # 'g_solo_1girl'

# 매트릭스 로드 (캐싱)
matrices = manager.load_matrices(category_id)

if matrices:
    cooccur_matrix = matrices['cooccur']  # CSR matrix
    pmi_matrix = matrices['pmi']
    condprob_matrix = matrices['condprob']
    metadata = matrices['metadata']

    print(f"매트릭스 크기: {cooccur_matrix.shape}")
    print(f"태그 수: {metadata['tag_count']}")
```

### 체크리스트

**EZ Mode 데이터 추가 시**:
```
[ ] JSON 파일은 data/ezmode/에 저장
[ ] 매트릭스 파일은 data/.ezmode/matrices/에 저장
[ ] .gitignore에 data/.ezmode/ 제외 확인
[ ] category_index.json 스키마 준수
[ ] build_summary.json 업데이트 (파일 수, 날짜)
[ ] Person Count 정규화 규칙 따르기 (3+ → many_)
[ ] 카테고리당 4개 파일 세트 완성 (cooccur, pmi, condprob, metadata)
```

**데이터 무결성 검증 시**:
```
[ ] build_summary.json 존재 확인
[ ] 전체 파일 수 1645개 (또는 80% 이상) 확인
[ ] 각 카테고리에 4개 파일 모두 존재
[ ] Sparse 매트릭스 로드 가능 (scipy.sparse.load_npz)
[ ] metadata.json 파싱 가능
```

---

## 데이터 로딩 패턴

### 동기 로딩 (텍스트 사전)

**적합한 경우**:
- 파일 크기가 작을 때 (< 1MB)
- 애플리케이션 초기화 시
- UI 블로킹이 허용될 때

**예시**:
```python
# 메인 스레드에서 직접 로드
filter_manager = FilterDataManager()
clothes = filter_manager.clothes_list  # 즉시 사용 가능
```

### 비동기 로딩 (Parquet 데이터베이스)

**적합한 경우**:
- 파일 크기가 클 때 (> 10MB)
- 사용자 요청에 의한 로딩
- UI 반응성이 중요할 때

**예시**:
```python
# QThread로 비동기 로드
class DataLoaderWorker(QObject):
    data_loaded = pyqtSignal(object)

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path

    def run(self):
        df = pd.read_parquet(self.file_path)
        self.data_loaded.emit(df)

# 사용
thread = QThread()
worker = DataLoaderWorker('data/tags/tags_00.parquet')
worker.moveToThread(thread)

worker.data_loaded.connect(lambda df: print(f"로드 완료: {len(df)} rows"))
thread.started.connect(worker.run)
thread.start()
```

### 멀티프로세싱 로딩 (대량 검색)

**적합한 경우**:
- 여러 파일을 병렬로 처리해야 할 때
- CPU 집약적 작업 (검색/필터링)
- GIL 우회가 필요할 때

**예시**: `core/search_controller.py` 참조

---

## 실전 예제

### 예제 1: 특정 카테고리 태그 추출 (5분)

**목표**: characteristic_list.txt에서 눈 색상 태그만 추출

```python
from core.filter_data_manager import FilterDataManager

# FilterDataManager 로드
filter_manager = FilterDataManager()

# 눈 색상 태그 추출 (6-20번째, 인덱스 5-19)
eye_colors = filter_manager.characteristic_list[5:20]

print(f"눈 색상 태그 ({len(eye_colors)}개):")
for tag in eye_colors:
    print(f"  - {tag}")

# 출력:
# 눈 색상 태그 (15개):
#   - aqua eyes
#   - black eyes
#   - blue eyes
#   - brown eyes
#   - green eyes
#   ...
```

### 예제 2: Parquet 파일에서 고득점 이미지 검색 (10분)

**목표**: 점수 80점 이상, 안전 등급, 1024×1024 이상 이미지 검색

```python
import pandas as pd
import glob

def search_high_quality_images():
    """고품질 이미지 검색"""
    results = []

    # 모든 parquet 파일 로드
    parquet_files = glob.glob('data/tags/*.parquet')

    for file_path in parquet_files:
        df = pd.read_parquet(file_path)

        # 필터링
        filtered = df[
            (df['score'] >= 80) &
            (df['rating'] == 'safe') &
            (df['image_width'] >= 1024) &
            (df['image_height'] >= 1024)
        ]

        if not filtered.empty:
            results.append(filtered)

    # 병합
    if results:
        final_df = pd.concat(results, ignore_index=True)
        print(f"✅ 검색 결과: {len(final_df)}개 이미지")
        print(f"평균 점수: {final_df['score'].mean():.2f}")
        print(f"평균 해상도: {final_df['image_width'].mean():.0f}×{final_df['image_height'].mean():.0f}")
        return final_df
    else:
        print("검색 결과 없음")
        return pd.DataFrame()

# 실행
high_quality_images = search_high_quality_images()
print(high_quality_images.head())
```

### 예제 3: 태그 자동완성 위젯 (15분)

**목표**: 사용자가 입력하면 clothes_list.txt에서 자동완성 제안

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem
from PyQt6.QtCore import Qt
from core.filter_data_manager import FilterDataManager

class TagAutocompleteWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.filter_manager = FilterDataManager()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 입력 필드
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("의류 태그 입력...")
        self.input_field.textChanged.connect(self.on_text_changed)

        # 제안 목록
        self.suggestion_list = QListWidget()
        self.suggestion_list.setMaximumHeight(200)
        self.suggestion_list.itemClicked.connect(self.on_suggestion_clicked)

        layout.addWidget(self.input_field)
        layout.addWidget(self.suggestion_list)

    def on_text_changed(self, text):
        """입력 변경 시 자동완성 제안"""
        self.suggestion_list.clear()

        if len(text) < 2:
            return

        # 의류 태그에서 검색
        matches = [
            tag for tag in self.filter_manager.clothes_list
            if text.lower() in tag.lower()
        ]

        # 최대 10개 제안
        for tag in matches[:10]:
            item = QListWidgetItem(tag)
            self.suggestion_list.addItem(item)

    def on_suggestion_clicked(self, item):
        """제안 클릭 시 입력 필드에 채우기"""
        self.input_field.setText(item.text())
        self.suggestion_list.clear()

# 사용
widget = TagAutocompleteWidget()
widget.show()
```

### 예제 4: 멀티프로세싱 태그 검색 (30분)

**목표**: SearchController를 사용한 비동기 태그 검색

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QPushButton, QProgressBar, QTextEdit
from PyQt6.QtCore import Qt
from core.search_controller import SearchController

class SearchWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.search_controller = SearchController()
        self.init_ui()
        self.setup_signals()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 검색 입력
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("검색할 태그 (쉼표로 구분)")

        # 검색 버튼
        self.search_button = QPushButton("검색")
        self.search_button.clicked.connect(self.on_search_clicked)

        # 진행률 바
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)

        # 결과 표시
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)

        layout.addWidget(self.search_input)
        layout.addWidget(self.search_button)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.result_text)

    def setup_signals(self):
        """검색 컨트롤러 시그널 연결"""
        self.search_controller.search_progress.connect(self.on_progress)
        self.search_controller.partial_search_result.connect(self.on_partial_result)
        self.search_controller.search_complete.connect(self.on_search_complete)
        self.search_controller.search_error.connect(self.on_search_error)

    def on_search_clicked(self):
        """검색 시작"""
        query = self.search_input.text().strip()
        if not query:
            return

        # UI 상태 업데이트
        self.search_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.result_text.clear()
        self.result_text.append("🔍 검색 중...\n")

        # 검색 파라미터 구성
        search_params = {
            'general': query,  # 검색할 태그
            'min_score': 0,
            'rating': 'all'
        }

        # 비동기 검색 시작
        self.search_controller.start_search(search_params)

    def on_progress(self, completed: int, total: int):
        """진행률 업데이트"""
        progress = int((completed / total) * 100)
        self.progress_bar.setValue(progress)
        self.result_text.append(f"진행률: {completed}/{total} 파일 ({progress}%)")

    def on_partial_result(self, df):
        """부분 결과 수신"""
        self.result_text.append(f"📊 부분 결과 수신: {len(df)}개 이미지")

    def on_search_complete(self, total_count: int):
        """검색 완료"""
        self.result_text.append(f"\n✅ 검색 완료: 총 {total_count}개 이미지")
        self.search_button.setEnabled(True)
        self.progress_bar.setVisible(False)

    def on_search_error(self, error_message: str):
        """검색 에러"""
        self.result_text.append(f"\n❌ 검색 오류: {error_message}")
        self.search_button.setEnabled(True)
        self.progress_bar.setVisible(False)

# 사용
widget = SearchWidget()
widget.show()
```

---

## 문제 해결

### Q1: 텍스트 파일 로딩이 실패해요

**증상**:
```
⚠️ 필터 파일 없음: data/characteristic_list.txt
```

**원인**:
1. 파일이 실제로 없음
2. 경로 오류
3. 인코딩 문제

**해결**:

1. **파일 존재 확인**:
```python
import os

file_path = 'data/characteristic_list.txt'
if os.path.exists(file_path):
    print(f"✅ 파일 존재: {file_path}")
else:
    print(f"❌ 파일 없음: {file_path}")

    # 현재 디렉터리 확인
    print(f"현재 디렉터리: {os.getcwd()}")

    # data/ 디렉터리 내용 확인
    if os.path.exists('data'):
        print(f"data/ 파일 목록: {os.listdir('data')}")
```

2. **인코딩 확인**:
```python
# UTF-8 강제
with open('data/characteristic_list.txt', 'r', encoding='utf-8') as f:
    lines = f.readlines()
print(f"✅ 로드 완료: {len(lines)}개 라인")
```

3. **상대 경로 문제**:
```python
# 절대 경로 사용
from pathlib import Path

repo_root = Path(__file__).parent.parent
data_dir = repo_root / 'data'
file_path = data_dir / 'characteristic_list.txt'

with open(file_path, 'r', encoding='utf-8') as f:
    tags = [line.strip() for line in f if line.strip()]
```

### Q2: Parquet 파일 로드가 너무 느려요

**증상**:
- 130개 파일 로드에 10초 이상 소요
- UI가 멈춤

**원인**:
1. 동기 로딩으로 메인 스레드 블로킹
2. 불필요한 전체 로드

**해결**:

1. **필요한 파일만 로드**:
```python
# ❌ 모든 파일 로드 (느림)
all_data = []
for i in range(130):
    df = pd.read_parquet(f'data/tags/tags_{i:02d}.parquet')
    all_data.append(df)

# ✅ 필요한 파일만 로드 (빠름)
df = pd.read_parquet('data/tags/tags_00.parquet')
```

2. **컬럼 선택 로드**:
```python
# ✅ 필요한 컬럼만 로드
df = pd.read_parquet(
    'data/tags/tags_00.parquet',
    columns=['id', 'general', 'score']
)
```

3. **비동기 로드** (이미 SearchController에서 구현됨):
```python
# core/search_controller.py 사용
search_controller = SearchController()
search_controller.start_search(search_params)
```

### Q3: 특정 태그를 찾을 수 없어요

**증상**:
```python
if "long_hair" in filter_manager.characteristic_list:
    # 실행되지 않음
```

**원인**:
1. 태그 이름 오타 (공백 vs 언더스코어)
2. 대소문자 불일치

**해결**:

```python
# ✅ 정확한 태그 이름 사용
if "long hair" in filter_manager.characteristic_list:  # 공백 사용
    print("✅ 태그 발견")

# ✅ 대소문자 무시 검색
tag_lower = "long hair".lower()
if any(tag.lower() == tag_lower for tag in filter_manager.characteristic_list):
    print("✅ 태그 발견 (대소문자 무시)")

# ✅ 부분 일치 검색
matches = [tag for tag in filter_manager.characteristic_list if "hair" in tag.lower()]
print(f"'hair' 포함 태그: {matches[:10]}")
```

### Q4: Parquet 파일 구조가 달라요

**증상**:
```python
KeyError: 'general'
```

**원인**:
- Parquet 파일이 예상과 다른 스키마를 가짐

**해결**:

```python
import pandas as pd

# 파일 구조 확인
df = pd.read_parquet('data/tags/tags_00.parquet')

print("컬럼 목록:")
print(df.columns.tolist())

print("\n데이터 타입:")
print(df.dtypes)

print("\n첫 5행:")
print(df.head())

# 컬럼 존재 확인
required_columns = ['id', 'general', 'score']
missing_columns = [col for col in required_columns if col not in df.columns]

if missing_columns:
    print(f"❌ 누락된 컬럼: {missing_columns}")
else:
    print("✅ 모든 필수 컬럼 존재")
```

### Q5: 검색 결과가 너무 많아요

**증상**:
- 검색 결과 10만 개 이상
- 메모리 부족

**원인**:
- 너무 일반적인 검색어 (예: "1girl")

**해결**:

```python
# ✅ 결과 수 제한
from core.search_controller import SearchController

search_params = {
    'general': '1girl, long hair',
    'min_score': 50,  # 점수 필터
    'rating': 'safe',  # 등급 필터
    'max_results': 1000  # 최대 결과 수 제한
}

# ✅ 정렬 후 상위 N개만
df_results = search_results_df.nlargest(1000, 'score')
```

---

## 체크리스트

### 새 텍스트 사전 파일 추가 시

```
[ ] UTF-8 인코딩으로 저장
[ ] 한 줄에 하나의 태그
[ ] 공백 라인 제거
[ ] FilterDataManager에 로딩 로직 추가
[ ] 로드 성공 메시지 확인
[ ] 소비자 코드에서 접근 테스트
```

### Parquet 파일 수정 시

```
[ ] 기존 스키마 확인
[ ] 모든 필수 컬럼 포함 (id, general, score 등)
[ ] 데이터 타입 일치 (int64, object, int32)
[ ] 중복 ID 제거
[ ] 파일 크기 확인 (~800KB 권장)
[ ] 검색 엔진 테스트
```

### 데이터 로딩 코드 작성 시

```
[ ] 파일 존재 확인 (os.path.exists)
[ ] 예외 처리 (try-except)
[ ] 인코딩 명시 (encoding='utf-8')
[ ] UI 스레드 블로킹 방지 (QThread 사용)
[ ] 메모리 효율 고려 (필요한 컬럼만 로드)
[ ] 진행률 표시 (대용량 파일)
```

### 검색 기능 구현 시

```
[ ] SearchController 사용 (멀티프로세싱)
[ ] 시그널 연결 (progress, result, error)
[ ] 취소 기능 구현
[ ] 결과 수 제한
[ ] 에러 처리
[ ] UI 상태 업데이트
```

---

## 참고 자료

### 관련 문서

- **[최상위 CLAUDE.md](../CLAUDE.md)**: 전체 프로젝트 개요
- **[core/CLAUDE.md](../core/CLAUDE.md)**: FilterDataManager, SearchController
- **[ui/CLAUDE.md](../ui/CLAUDE.md)**: ModernMenu (태그 툴팁)

### 주요 의존성

**data/를 사용하는 파일**:
- `core/filter_data_manager.py` - 텍스트 사전 로드
- `core/search_controller.py` - Parquet 검색
- `core/search_engine.py` - 검색 로직
- `ui/modern_menu.py` - 태그 정보 툴팁

**data/가 의존하는 외부 라이브러리**:
- `pandas` - Parquet 파일 읽기/쓰기
- `pyarrow` - Parquet 백엔드

### 예제 코드 위치

| 예제 | 파일 | 라인 |
|------|------|------|
| **FilterDataManager** | `core/filter_data_manager.py` | 4-41 |
| **SearchWorker** | `core/search_controller.py` | 8-69 |
| **SearchController** | `core/search_controller.py` | 72-113 |
| **Parquet 로드** | `core/search_engine.py` | - |

### 유용한 pandas 함수

| 함수 | 용도 | 예시 |
|------|------|------|
| `pd.read_parquet()` | Parquet 파일 읽기 | `df = pd.read_parquet('file.parquet')` |
| `df.to_parquet()` | Parquet 파일 쓰기 | `df.to_parquet('file.parquet')` |
| `df[df['col'] > value]` | 필터링 | `df[df['score'] > 80]` |
| `df.nlargest(n, 'col')` | 상위 N개 | `df.nlargest(100, 'score')` |
| `pd.concat()` | 데이터프레임 병합 | `pd.concat([df1, df2])` |
| `df.drop_duplicates()` | 중복 제거 | `df.drop_duplicates(subset=['id'])` |

### 디버깅 팁

1. **텍스트 파일 디버깅**:
```python
# 파일 내용 직접 확인
with open('data/characteristic_list.txt', 'r', encoding='utf-8') as f:
    lines = f.readlines()
    print(f"총 {len(lines)}개 라인")
    print(f"첫 10개: {lines[:10]}")
    print(f"마지막 10개: {lines[-10:]}")
```

2. **Parquet 파일 디버깅**:
```python
import pandas as pd

df = pd.read_parquet('data/tags/tags_00.parquet')
print(f"Shape: {df.shape}")
print(f"Columns: {df.columns.tolist()}")
print(f"Dtypes:\n{df.dtypes}")
print(f"Memory usage: {df.memory_usage(deep=True).sum() / 1024 / 1024:.2f} MB")
```

3. **검색 성능 측정**:
```python
import time

start_time = time.time()
# 검색 실행
end_time = time.time()

print(f"검색 시간: {end_time - start_time:.2f}초")
```

---

## 요약

**data/의 핵심**:
- ✅ **텍스트 사전**: 카테고리별 태그 목록 (characteristic, clothes)
- ✅ **Parquet 데이터베이스**: 분할된 대용량 태그 데이터 (130개 파일)
- ✅ **FilterDataManager**: 텍스트 사전 로딩
- ✅ **SearchController**: 멀티프로세싱 검색
- ✅ **비동기 로딩**: UI 반응성 유지

**다음 단계**:
1. FilterDataManager 사용법 숙지
2. SearchController로 태그 검색 구현
3. 커스텀 필터링 로직 추가

**막힐 때**:
- 텍스트 파일 → [Q1](#q1-텍스트-파일-로딩이-실패해요)
- Parquet 로딩 → [Q2](#q2-parquet-파일-로드가-너무-느려요)
- 태그 검색 → [Q3](#q3-특정-태그를-찾을-수-없어요)

---

*문서 버전: 1.0*
*작성: 2025-01-08*
*담당 영역: data/ 디렉터리*
