# 자세(pose) 섹션 — 생성·검수 기록

2026-07-26. 개별 슬롯 1,584 + 다인원 439 = **2,023장 완료**(실패 0 / Rate Limit 0).
성인 축 `pose_nsfw` 122 + `pose_nsfw_face` 3 은 보류 — 사용자가 직접 한다.

## 축 구성 (32축)

`_pose_axes.json` 이 축·라벨의 SSOT 다. 손으로 적지 말 것 — 세 군데에 적어 뒀다가
셋 다 낡았다(§실수 기록).

| 프레이밍 | 축 |
|---|---|
| full | posture(93+93) · leg(75) · action(119+119+117) · combat(35) |
| cowboy | holding(104+104+102) · clothing(104+103) · display(55) · body_touch(29) |
| upper | arm(100) |
| portrait | hand(98) · face_touch(61) · mouth(52) · gaze(21) |

다인원(`_m`)은 같은 프레이밍을 쓰되 **portrait 이 없다** — close-up 크롭에 두 사람이
안 들어간다. 얼굴 축이라도 다인원이면 upper 로 올린다.

## 인원 규칙

개별 슬롯 = 1인으로 렌더되는 것. 글로벌(씬) 슬롯 = 2명 이상 필요한 것.
판정 근거는 이벤트 프리셋 파티션의 실측 solo 비율 + 태그명의 own/another's 다
(`tools/build_pose_slots.py`). 2,249건 중 91% 가 실측, 9% 만 LLM 판단이다.

다인원 템플릿은 `2girls` 고정이다. 실측상 girl+boy 41~57% / 2girls 29~47% 로 우열이
없어(최신 10개 parquet), 데이터가 아니라 솔로 축과의 화면 톤을 기준으로 골랐다.
성별을 명시한 태그는 439개 중 2개뿐이다(`mixed-sex bathing`, `mixed-sex combat`) —
그 둘은 2girls 로 나오지만 태그별 템플릿을 따로 두지 않았다.

## 검수 결과

| 축 | 판정 |
|---|---|
| `pose_posture` | 통과. standing/sitting/lying/on back 이 한눈에 구분된다 — 전신 프레이밍의 목적 |
| `pose_clothing` | 통과. cowboy 가 옷 동작에 잘 맞는다 |
| `pose_leg` | 통과. toe scrunch·presenting foot·spread toes·plantar flexion 전부 보인다 |
| `pose_body_touch` | 통과. portrait 에서 프레임 밖이던 hand on own hip·covering privates·belly grab 이 보인다 |
| `pose_action_m` | 통과. 60칸 중 약 5개만 약함(imagining/peeking/twitching — 그림으로 표현이 안 되는 것) |
| `pose_face_touch` | 재분할로 해소 (아래) |

### 남은 문제 — `pose_display` 에 성격·유형(persona)이 섞였다

⚠️ **첫 판정은 틀렸다.** "`tomboy`/`tsundere`/`jimiko`/`mesugaki` 는 렌더가 안 되고
기본 그림과 구분이 안 된다"고 적었는데, 원본을 열어 보니 **제대로 나온다**:

- `jimiko` — 검은 뿔테 + 단정한 단발 + 홍조 + 뒷짐. 지미코 원형 그대로
- `mesugaki` — 반쯤 감은 내려보는 눈 + 도발적 웃음 + 트윈테일 + 앞으로 기운 자세

**192px 컨택트 시트에서 봤기 때문에 "그냥 여자애"로 읽혔다.** 축소본으로 판정하면
안경·표정 같은 작은 신호가 사라진다 — 의심스러우면 원본을 열어야 한다.

그러니 문제는 렌더가 아니라 **소속**이다. 성격은 자세가 아니다.
태그 DB 는 이미 `Expression_Action/personality` 로 17개를 분류해 두었는데,
내 fallback 이 이것들을 자세로 쓸어넣었다:

| 태그 | freq | 지금 위치 | solo 비율(실측) |
|---|---|---|---|
| `assertive female` | 5,866 | pose_display_m | 0.02 |
| `tomboy` | 4,069 | pose_display | 0.57 |
| `female pervert` | 2,808 | pose_display_m | 0.13 |
| `tsundere` | 2,342 | pose_display | 0.36 |
| `jimiko` | 1,056 | pose_display | 0.65 |
| `chuunibyou` | 679 | pose_display | 0.54 |
| `mesugaki` | 638 | pose_display | 0.59 |
| `messy sleeper` · `clumsy` | 201 · 123 | pose_display | 0.20 · 0.53 |
| `muscular uke` | 210 | pose_drop | — |
| `ptsd`·`hikikomori`·`unaware`·`glutton`·`age conscious`·`kuudere` | 57~94 | **어디에도 없음** | — |

다인원 배정(`assertive female` 등 solo 비율 0.02~0.13)은 실측 근거가 있다 —
그 성격은 상대가 있는 장면에서 쓰인다. **인원 분류가 틀린 게 아니라 축이 틀렸다.**

관련 태그가 다른 곳에도 있다: `gyaru`(8,477)는 `cloth_style`(패션 스타일이니 타당),
`serious`(16,007)·`shy`(4,141)는 `expression`(표정이니 맞음), `yandere`(3,500)는 없음.

**제안**: `persona` 축(성격·유형)을 신설해 표정 슬롯에 붙인다(태그 DB 가 이미
`Expression_Action` 소속으로 본다). 프레이밍은 cowboy 이고 **의상을 고정하지 않는다** —
성격은 머리·의상·표정을 한꺼번에 바꾸는데 `white shirt, pleated skirt` 로 묶으면
표현 통로 하나를 막는다(그래도 mesugaki 는 분홍 베스트를 밀어 넣었다).
대상 약 18개(personality 17 + `yandere`), 약 18장. **결정 대기.**

선별 판단이 필요한 것: `ptsd`(정신질환 — 시각 원형이 아니다) · `muscular uke`(BL
전용, 이미 제외) · `female pervert`(성적 함의) · `height conscious`/`age conscious`
(관계 서술이라 성격이 아니다) · `unaware`(장면 상태).

### 렌더가 실제로 안 되는 것 (별건)

`have to pee` · `shaking head` · `hobble` · `object floating above hand` ·
`spread navel` · `spread armpit` — 이쪽은 그림으로 표현할 대상이 없다. 제외 후보.

### 계층 탐색기는 뺐다 (2026-07-26 결정)

탐색기가 보여주던 2,360개 중 **1,757개(74%)가 이미 썸네일에 있는 중복**이었고,
탐색기에만 있는 514개는 **전부 freq 50~99 에 한글 설명이 0/514** 였다.
그중 9개는 freq 0 비표준 별칭이라 정식 태그보다 나쁘다:

| 탐색기의 것 | freq | 정식 태그 | freq |
|---|---|---|---|
| `hands on hips` | 0 | `hands on own hips` | 16,940 |
| `looking back at viewer` | 0 | `looking back` | 161,757 |
| `hands together` | 0 | `own hands together` | 46,327 |
| `reaching out` | 0 | `reaching` | 16,303 |

원래 전제("썸네일이 freq>=100 만 덮으므로 나머지는 탐색기가 담당한다")는 맞았다 —
100 이상은 한 개도 새지 않았다. 그래서 남는 것이 **쓸 수 없는 것들**이었다.

트리만 떼고 `scope` 섹션으로 검색 범위는 남겼다. 검색창은 이제 그리드를 거르고
태그명과 한글 설명 양쪽을 본다 — `앉` 으로 sitting/squatting/wariza/seiza 가 나온다.
다른 슬롯(표정/의상/소품)은 browse 그대로다.

### 알려진 한계 — 좁은 창에서 조언 플로트가 사라진다

`@media (max-width: 1279px) { .ia-aside { display: none } }` — 옆에 공간이 없어
숨기는 건 맞지만 대체 표시가 없어 전제조건 안내가 통째로 안 보인다.
후보: 좁은 폭에서는 '필요한 것' 한 줄만 팝업 안쪽에 붙인다(추천은 버린다).

## 이번 세션의 실수 기록 — 전부 "조용히 틀리던" 것들

같은 뿌리가 다섯 번 나왔다: **목록을 두 군데에 손으로 적었다.**

1. **다인원 축이 `1girl, solo`** (384장). 축을 개별/다인원으로 가른 이유를 템플릿이
   뒤집었다. `hug` 은 인형을 안은 1인, `piggyback` 은 혼자 허리 숙인 그림.
2. **`_todo/` 가 축 파일과 분리** (71장). thumb_bench 는 `_todo/<axis>.txt` 를 읽는데
   build_pose_axes 는 `<axis>.txt` 만 썼다. 신설 `pose_leg` 는 `_todo` 파일이 없어
   경고 한 줄만 남기고 **통째로 건너뛰었다** — batch_tags 는 없는 파일을 정상으로 본다.
3. **축 이름의 `·` 가 프레이밍 경계** (6축 33개). 라벨이 "얼굴·몸에 손" 이었다.
   축 이름에 두 부위가 들어가면 프레이밍이 갈린다는 신호다(네 번째 반복).
4. **접미사 없는 축을 다인원 패스가 덮어씀** (눈 태그 13개). `expression_from_pose` 는
   인원과 무관해 일부러 접미사를 안 붙였는데, 쓰기가 패스 안에 있었다.
5. **`openSlot` 이 씬 슬롯 `sections` 누락** (다인원 439개). 캐릭터 경로에만 있던 줄이라
   다인원 자세가 UI 에서 한 번도 닿은 적이 없었다.
6. **중간 산출물이 축을 가로챔** (31장). `load_axis_tags` 가 `pose_multi.txt` 를 축으로
   읽고, setdefault 는 알파벳 순 첫 파일이 이기므로 `pose_posture_m` 의 31개를 뺏었다.

2·3·5·6 은 파생 + assert 로 바꿨다. 그 assert 가 즉시 6번의 뿌리(중간 산출물이 축과
같은 `pose_*` 접두를 쓴다)를 잡아냈다.

## 다시 돌리는 순서

```bash
python tools/build_pose_slots.py          # 인원 분류 (solo/multi/drop)
PYTHONPATH=. python tools/build_pose_axes.py   # 축 분배 + _todo 동기화
python tools/thumb_bench_init.py          # _bench.json (축 정의에서 파생)
PYTHONPATH=. python tools/thumb_axes_emit.py   # interactiveAxes.mjs
python tools/thumb_bench.py <축...> --out user-data/output/pose   # 있는 것은 건너뛴다
PYTHONPATH=. python tools/build_interactive_thumbnails.py user-data/output/pose --prune
```

`thumb_bench` 는 계획을 시작할 때 한 번에 만든다. 도는 중에 축 파일을 바꾸면
그 실행은 옛 목록을 계속 찍는다 — 바꿨으면 멈추고 다시 띄워야 한다(건너뛰기가
되므로 손해는 없다).

## 미생성

- `pose_nsfw` 122 + `pose_nsfw_face` 3 — 보류(사용자 직접).
- `expression_from_pose` 14 — 자세에서 표정 슬롯으로 넘긴 눈 태그.
  `_todo/expression.txt` 에 올려 뒀다. 표정 배치(portrait, 2.5::)로 찍으면 된다.
