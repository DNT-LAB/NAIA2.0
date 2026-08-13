# Dev0714 Quick Filter 검토 — 무엇을 대체하는가

> 대상: `C:\VNR\NAIA2.0` 저장소의 `Dev0714` 브랜치.
> 방법: 작업 트리를 건드리지 않고 `git show Dev0714:<path>` 로 읽고, 로컬에 있는
> `.tgp` 실물을 같은 코드 경로로 디코드해 실측했다.

---

## 0. 이름부터 바로잡는다 — 검토 대상은 Quick **Search** 다

**`Dev0714` 에는 `quickFilter.mjs` 가 없다.** `git ls-tree -r --name-only Dev0714`
에서 `quick` 이 걸리는 파일은 파이썬 셋뿐이고, `Dev0714:core/remote_api_server.py`
에는 `quick` 이 **0회** 나온다 — 그 브랜치에는 이 기능의 웹/HTTP 표면이 아예 없다.

이름이 비슷한 **다른 기능 둘**이 있다:

| | **Quick Search** (검토 대상) | **Quick Filter** |
|---|---|---|
| 브랜치 | `Dev0714` 이후 | `future01` 이후만 |
| 파일 | `ui/interactive/quick_search_{block,data}.py`, `ui/remote/quick_search_tab.py` | `ui/remote_web/js/features/quickFilter.mjs` |
| 스택 | PyQt6 데스크톱 | 브라우저 ES 모듈 + WebSocket |
| 인원 수 분류 | **있다 (13종)** | 없다 |
| 태그 추천 | **있다 (동시출현)** | 없다 |
| 실체 | 사전 구축 역인덱스 위의 동시출현 탐색기 | danbooru **검색**의 등급/포함/제외 프리필터 |

사용자가 말한 "인원 수 분류 방식"과 "태그 추천"은 전부 Quick Search 쪽이다.
`quickFilter.mjs` 는 `localStorage['naia_quick_filter_options']` 에 등급 체크박스와
포함/제외 칩을 저장하고 `tag_filter_search` 류 WS 메시지를 보내는 물건으로,
점수 계산이 전혀 없다.

---

## 1. 데이터 모델 (실측)

**포맷**: 커스텀 바이너리. parquet 도 JSON 도 아니다.

    magic 4B  b'TGP1'(파티션) / b'TGPS'(메타)
    version   uint16 LE
    length    uint32 LE
    payload   lzma.compress(pickle.dumps(dict))

payload 를 풀면 **같은 데이터가 두 벌** 들어 있다:

    event_tag_indices  uint16[nnz]     행 우선 CSR
    event_tag_indptr   int32[posts+1]
    tag_to_events      {tag_id: int32[]}   열 우선 역인덱스

**실물 측정** (`NAIA-Portable/user-data/data/quick_search/`, 52파티션 238MB):

| 파티션 | 디스크 | 이벤트 | nnz | 상주 | 적재 |
|---|---:|---:|---:|---:|---:|
| `s_1girl_solo.tgp` | 45.0 MB | 864,892 | 24,990,787 | **149.6 MB** | **2.42 s** |
| `q_1girl_solo.tgp` | 14.4 MB | 257,355 | 7,678,662 | 45.9 MB | 0.72 s |
| `e_other.tgp` | 0.14 MB | 3,123 | 59,798 | 0.4 MB | 0.01 s |

디스크 대비 **3.3배**로 부푼다. 한 번에 한 파티션만 상주한다.
전 파티션 합계 4,495,107 이벤트.

---

## 2. 인원 수 분류 — 사용자가 참고하라고 한 부분

### 13그룹 × 4등급 = 52파티션

`quick_search_block.py:55-60` 과 `quick_search_tab.py:541-546` 에 **똑같이 두 번**
적혀 있고, `ui/event_preset/engines.py:44-49` 에 순서만 다른 **세 번째 사본**이 있다.

    1girl_solo · 1boy_solo · 1girl · 1boy · 1girl_1boy
    1girl_multiple_boys · 1boy_multiple_girls
    2girls · 2boys · multiple_girls · multiple_boys
    multiple_girls_multiple_boys · other

파일명은 `{등급}_{인원}.tgp` (`quick_search_block.py:852`).

### 런타임 판정은 **스피너 값**의 if/elif 사슬 (`:795-824`)

    others > 0                      -> other          <- 가장 먼저 걸린다
    girls==1, boys==0               -> 1girl_solo / 1girl   (is_solo 로 갈림)
    girls==0, boys==1               -> 1boy_solo / 1boy
    girls==2 -> 2girls / girls>=3 -> multiple_girls
    boys==2  -> 2boys  / boys>=3  -> multiple_boys
    girls==1,boys==1 -> 1girl_1boy
    girls==1,boys>=2 -> 1girl_multiple_boys
    girls>=2,boys==1 -> 1boy_multiple_girls
    girls>=2,boys>=2 -> multiple_girls_multiple_boys

**결함 둘**:
1. `others > 0` 이 맨 앞이라 "여자 1 + 이형 1" 이 `other` 로 접힌다. 실측으로
   빌드 쪽은 그런 게시물을 `1girl` 에 넣어 뒀다 — `q_1girl` 의 4.8%가 `1other`
   태그를 갖는다. 사용자는 2,870건이 있는 곳 대신 3,260건짜리 파티션을 본다.
2. `girls==0, boys==0, others==0` 이면 사슬을 전부 통과해 기본값 `"1girl"` 로
   떨어진다. "사람 없음" 을 고르면 조용히 `1girl` 파티션이 붙는다.

### 빌드 쪽 판정은 저장소에 없다

`.tgp` 는 HuggingFace 에서 통째로 받는다(`quick_search_block.py:52`). 생성 스크립트가
브랜치 어디에도 없다. 파티션 안의 태그 커버리지를 재서 규칙을 역산했다 —
**순수 danbooru 인원 태그 존재 여부**다(`2girls` 있으면 2girls, `multiple girls` 만
있으면 multiple_girls…). 런타임 스피너 규칙과 **다른 물건**이라 위 결함 1이 생긴다.

---

## 3. 질의 경로와 점수 (핵심 결함)

    스피너 변경 -> settingsChanged -> load_partition(등급, 인원)
      -> 13분기 판정 -> PERSON_AUTO_TAGS + 숫자 태그 자동 추가
      -> f"{r}_{cat}.tgp" 를 **GUI 스레드에서 동기 적재** (LZMA, 최대 2.42초)
      -> update_recommendations()

`update_recommendations` (`:877-916`) 는 두 단계다:

1. **후보 집합** — `filter_events()` (`quick_search_data.py:70-122`). 포함 태그의
   포스팅 리스트를 **엄격 AND** 로 교집합. 빈도 낮은 순 정렬은 최적화로 들어가 있다.
   어휘 밖 태그가 하나라도 있으면 `:82-91` 에서 **즉시 0건**을 반환한다(의도적 선택).
2. **점수** — `get_tag_counts()` (`:124-155`). 매칭 게시물의 태그를 그냥 센다.

### **점수가 raw 동시출현 횟수뿐이다**

confidence 도 lift 도 PMI 도 IDF 도 없다. 정규화도 없다. `tag_freq` 는 메타에
들어 있는데 `quick_search_tab.py:1520` 에서 콜드스타트 폴백으로만 쓰고 분모로는
한 번도 안 쓴다.

결과적으로 목록 상단이 **항상 코퍼스 헤드**다 — `long hair` · `looking at viewer` ·
`breasts` · `blush`. `sword` 를 골라도 `armor` 보다 `long hair` 가 위에 온다.

이 문서와 함께 있는 실측이 그 크기를 말해 준다(`SPEC.md` 3장):

| 방법 | P@8 | **P@8_info** |
|---|---:|---:|
| corpus-head (아무것도 안 하는 stub) | 0.548 | **0.000** |
| **raw count = Quick Search 방식** | 0.627 | **0.065** |
| conf × min(log2 lift, 3) | 0.297 | **0.131** |

정보성 태그 기준으로 **stub 대비 두 배 남짓**이고, lift 방식의 절반이다.

### 그 밖에 확인한 것

- **단일 태그만 랭킹한다.** 조합을 내는 코드는 `QuickSearchComboProvider`
  (`ui/event_preset/engines.py:1049-1103`) 하나뿐인데, 이벤트 태그 **한 개**로만
  키잉되고 4,200개 허용목록으로 어휘를 줄인 뒤 raw count 로 정렬한다.
  게다가 `engines.py:913` 이 `Path("data/quick_search")` 를 하드코딩하는데
  future02 체크아웃에는 그 경로가 없어 `try_create()` 가 `None` 을 반환한다 —
  **이 체크아웃에서는 죽어 있다.**
- **백오프가 없다.** 교집합이 0이 되면 그냥 0건이다.
- **의미를 모른다.** 태그는 uint16 id 일 뿐이라 `short hair` 가 이미 있어도
  `long hair` 를 권한다. 같은 브랜치에 `core/tag_axis_registry.py` 가 있는데 안 쓴다.
- **캐싱/증분 없음.** 포함/제외를 누를 때마다 전체 파이프라인을 GUI 스레드에서
  다시 돈다.
- 원격 탭(`quick_search_tab.py:309-327`)의 `get_tag_counts` 는 CSR 을 안 쓰고
  역인덱스 전체를 순회하며 매칭 집합과 교집합한다 — 어휘 크기 × 평균 포스팅 길이.
  `s_1girl_solo` 에서 키 입력마다 2,500만 원소를 파이썬 set 으로 다시 만든다.

---

## 4. 어휘가 잘려 있다 — 이 검토의 결론을 가른 사실

`metadata.tgpm` 을 디코드하면 빌드 시점 필터가 그대로 적혀 있다:

    filters_applied = ["freq>=50", "color.txt with exceptions"]
    filters_removed = ["clothes_list", "characteristic_list", "location_background"]

즉 **의상·특징·배경 태그가 통째로 빠져 있다.** 773,722 종에서 16,625 만 남았다.
조합 추천이 다뤄야 할 어휘의 핵심이 없다.

덤으로 `event_tag_indices` 가 `uint16` 이라 **65,536 이 구조적 상한**인데 어디에도
적혀 있지 않다. 현재 16,625 는 그 25% 다.

그리고 이 코퍼스의 간선 신뢰도 자체가 이미 반증돼 있다 —
`tools/build_tag_cooccurrence.py:186-203` 이 측정하기를, 간선의 9.9%가 실제
게시물에 거의 없다(`hooded coat + cow ears` 코퍼스 3,333회 / 게시물 0회).

---

## 5. 판정

| 항목 | Quick Search | 새 시스템에서 |
|---|---|---|
| 원천 | `.tgp` (어휘 잘림, 간선 9.9% 허구) | `data/tags/*.parquet` 754만 게시물 |
| 어휘 | 16,625 (의상·특징·배경 없음) | 그룹당 5,367~23,122 (제한 없음) |
| 점수 | raw count | conf × min(log2 lift, 3) |
| 출력 | 단일 태그 | **튜플(조합)** |
| 백오프 | 없음(0건) | 정보량 최대 부분집합 + 크기 + 게이트 |
| 인원 분류 | 13그룹, 결함 2건 | 같은 13그룹, `""`→`other` 명시 |
| 적재 | 2.42초 (LZMA, GUI 스레드) | 375ms (mmap + CSR→CSC) |
| 상주 | 149.6 MB | 161 MB (게시물 5배로) |
| 캐릭터 편향 | 없음 | 질의 시점 집중도 필터 |

**인원 수 분류 방식만 계승하고 나머지는 대체한다.** 13그룹 목록과 우선순위
사슬은 이미 세 곳에 복제돼 있는 SSOT 라 그대로 따르되, 위에서 찾은 결함 둘
(`others>0` 선점, 0명 폴백)은 새 구현에서 반복하지 않는다.

포맷·점수·출력·백오프는 전부 바꾼다. `.tgp` 를 고쳐 쓰는 길은 없다 — 어휘가
빌드 시점에 잘려 있어서 무엇을 얹어도 의상 조합을 낼 수 없다.
