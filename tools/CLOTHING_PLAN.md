# 의상 슬롯 썸네일 계획

특징 슬롯(머리/눈·얼굴/표정/신체/종족·수인)은 완료됐다 — 22축 1,480장.
이 문서는 그 다음인 **의상 슬롯**의 분류·규모·벤치 설계를 담는다.
분류 코드의 SSOT 는 `tools/thumb_clothing_build.py`이고, 여기는 왜 그렇게 했는지를 남긴다.

## 1. 규모 — 왜 freq>=2000 인가

의상 풀은 **4,017개**로 특징 슬롯 전체(약 3,000)보다 크다. 절단선별 잔여:

| 절단선 | 태그 수 |
|---|---|
| freq>=60 (특징 슬롯이 쓴 값) | 3,774 |
| freq>=500 | 1,818 |
| **freq>=2000** | **1,052** |
| freq>=5000 | 683 |
| freq>=10000 | 476 |

특징 슬롯 실적이 1,480장이었으므로 **freq>=2000(제외·조합 적용 후 915장)** 이 같은 자릿수다.
freq>=60 까지 열면 2.5배가 되어 하루 단위로 끊을 수 없다.

한편 의상은 특징과 성격이 다르다 — **99%가 한글 설명을 갖고 있고**, 이름만으로
짐작되는 것이 많다(`t-shirt`, `school uniform`). `harvin`이나 `sway back`처럼
썸네일이 없으면 아무것도 알 수 없는 태그와는 다르다. 그래서 썸네일의 가치가
가장 높은 쪽은 오히려 **빈도가 낮은 전문 용어**다:
`halterneck`, `criss-cross halter`, `pelvic curtain`, `underbust`, `bandeau`,
`tabard`, `buruma`, `sarashi`, `furisode`, `hagoromo`.
절단선은 이미지 품질(희귀 태그는 렌더가 불안정) 때문에 유지하되, 이 비대칭은 기억해 둔다.

## 2. 다른 슬롯으로 내보내는 것 (68개)

의상 슬롯에 있지만 **화면에 보이는 것이 옷이 아닌** 것들. 목적지 축은 모두 이미 있다.

| 대상 | 개수 | 목적지 | 근거 |
|---|---|---|---|
| `tanlines` 등 태닝 자국 | 8 | 신체>피부 | 옷이 만든 자국이지만 보이는 것은 피부색 경계다 |
| 화장·네일 (`makeup`, `lipstick`, `eyeshadow`, `nail polish`, `*nails`) | 23 | 문신·피어싱 | 얼굴·손에 칠하는 것. `facepaint`를 표식으로 옮긴 것과 같은 논리 |
| 붕대 (`bandaged *`, `bandaid on *`) | 28 | 신체>부상·오염 | 붕대는 부상의 표현. **5개는 이미 부상 축에 있어 중복이었다** |
| 가짜 부속 (`fake horns/wings/antlers/tail/animal ears`) | 6 | 종족·수인 각 축 | 초보자는 뿔을 찾으러 뿔 축에 간다. 가짜라도 화면에는 뿔이 보인다 |
| 그린 표시 (`drawn ears/tail/whiskers`) | 3 | 문신·피어싱 | 입체 부속이 아니라 몸에 **그린** 것이다(Codex 지적) |

`bandaged arm` / `bandaged leg` / `bandaged hand` / `bandage over one eye` /
`bandaged head` 5개는 부상·오염 축(썸네일 있음)과 의상 탐색기 양쪽에 노출되고 있었다.

## 3. 제외 (2,972개)

| 군 | 개수 | 근거 |
|---|---|---|
| freq<2000 | 2,494 | 규모 현실화 (§1) |
| 작품·캐릭터 한정 (괄호 포함) | 332 | 특정 캐릭터 의상. 초보자용이 아니고 대부분 저빈도. ⚠️ 괄호가 구분자인 10개(`pom pom (clothes)` 등)는 되살렸다 |
| 미착용 (`unworn *`) | 69 | 아무도 착용하지 않은 옷 = 소품. 1인 썸네일에서 무의미 |
| 폐기·모호 | 33 | 데이터가 쓰지 말라고 명시 (`torn legwear`, `checkered`, `underskirt` …) |
| 원본 비교 필요 (`alternate *`, `costume switch`, `no headwear`, `bespectacled`) | 15 | 캐릭터의 원래 의상을 알아야 의미가 생긴다 → 렌더 불가 |
| 렌더 불가·액션 | 8 | `clothes pull` / `skirt lift` 등은 행위다 → 액션 슬롯 |
| cosplay | 2 | 위 괄호 규칙과 대부분 겹친다 |
| 2인 필요 | 1 | `matching outfits` |
| 근접 중복 | 6 | `traditional nun`≈`habit`, `wristwatch`≈`watch` 등 |
| 작품 고유 아이템 | 5 | `super crown`, `v-fin`, `dynamax band` 등 |

## 4. 색·무늬 조합 78개 — 팔레트로 처리

`white shirt` / `black skirt` / `red bow` 는 이름만으로 100% 짐작되는데도 이미지를
한 장씩 먹는다. 머리·눈·피부 색을 팔레트로 처리한 것과 같은 문제다.

본체 26종에 붙는다: `bow×9`, `dress×8`, `bikini×8`, `ribbon×7`, `jacket×6`,
`skirt×4`, `necktie×4`, `gloves×4`, `shirt×3`, `bowtie×3` …

무늬도 같은 성질이다 — `striped shirt` = `striped` + `shirt`.
⚠️ **수식어가 실제로 고를 수 있을 때만 분해한다.** 처음엔 무늬 전체를 수식어로 썼는데
`frilled`/`plaid`/`ribbed`/`fur-trimmed` 등 8개는 단독 태그가 없거나 제외돼 있어
`frilled skirt` 가 '고를 수 없는 수식어 + 치마'로 도달 불가가 됐다. 2단계 검사로 고쳤다.

⚠️ 기존 팔레트와 다른 점: 머리 색은 `blue hair` 한 태그를 고르는 것이지만,
의상은 **`shirt` 를 고른 상태에서 색을 고르면 태그가 `white shirt` 로 바뀌어야** 한다.
즉 태그 치환(composition)이 필요하고 이는 신규 프론트 기능이다.
간단한 대안은 그냥 78장을 생성하는 것이다 — 판단 필요(§7).
그때까지 이 78개는 탐색기·자동완성으로만 접근된다.

## 5. 축 분해 — `attire` 1,712 의 4분할

`attire` 한 subgroup 이 의상 풀의 43%다. 그 안에 성격이 다른 네 가지가 섞여 있다:
**옷 종류 / 착의 상태 / 디테일·실루엣 / 스타일·용도**. `body_expose` 잡동사니와 같은 병이다.

### 규칙 작성에서 두 번 자책할 일

1. `(clothes|clothing|outfit|dress|shirt|skirt|top|bottom)$` 로 상태를 잡으려 했더니
   `shirt` / `pleated skirt` / `t-shirt` / `tank top` 까지 '착의 상태'로 갔다
   (158개 중 121개 오분류). **상태는 조건 수식어로만 판정한다** — 의류 명사로 판정하지 않는다.
2. 디테일 검사를 의류 검사보다 먼저 두어 `frilled skirt` 가 하의가 아니라 디테일로 갔다.
   **의류 정체성이 수식어보다 앞선다.** 프릴 달린 치마는 여전히 치마다.

### 최종 23축 (915개) — Codex 3회 리뷰 반영 후

| 축 | 라벨 | 개수 | 축 | 라벨 | 개수 |
|---|---|---|---|---|---|
| `cloth_accessory` | 액세서리 | 116 | `cloth_footwear` | 신발 | 28 |
| `cloth_headwear` | 모자 | 84 | `cloth_sleeve` | 소매 | 24 |
| `cloth_detail` | 디테일·실루엣 | 84 | `cloth_swim` | 수영복 | 23 |
| `cloth_state` | 착의 상태 | 64 | `cloth_legwear` | 다리 | 23 |
| `cloth_top` | 상의 | 55 | `cloth_traditional` | 전통 의상 | 19 |
| `cloth_uniform` | 제복·코스튬 | 53 | `cloth_outer` | 겉옷 | 16 |
| `cloth_nsfw` | 노출 의상(성인) | 51 | `cloth_armor` | 갑옷 | 16 |
| `cloth_hairacc` | 머리 장식 | 49 | `cloth_style` | 스타일·용도 | 12 |
| `cloth_neck` | 목 | 43 | `cloth_handwear` | 손 | 11 |
| `cloth_under` | 속옷 | 39 | `cloth_pattern` | 무늬·프린트 | 10 |
| `cloth_dress` | 원피스·한벌 | 34 | | | |
| `cloth_bottom` | 하의 | 31 | | | |
| `cloth_eyewear` | 안경·마스크 | 31 | | | |

미분류 0개, 축 간 중복 0개(특징 축 22개 포함 전수 검사).
생성 대상은 성인 축을 뺀 **22축 864장** + 파일럿 18장.

### 슬롯 2분할

22축을 팝업 하나에 담을 수 없어 나눴다 — `의상`(몸에 입는 것, 13축) /
`소품·장식`(부위에 차거나 거는 것, 10축). 각 슬롯에 탐색기 섹션을 하나 남겨
freq<2000 인 나머지 3,100개를 담당하게 했다.

### `cloth_accessory` 는 152 -> 116 으로 줄었다

착용 부위를 실측했을 때 **7곳**에 흩어져 있었다(전신·기타 34 / 머리·귀 24 / 팔·손 18 /
허리 17 / 목·가슴 15 / 휴대품 10 / 다리·발 5). 부위가 다르면 프레이밍이 달라야 하므로
한 그리드에 넣으면 대부분이 쓸모없는 썸네일이 된다(귀걸이를 full body 로 찍는 것과 같다).

Codex 도 독립적으로 같은 결론을 냈고("152개로 현재 한도 초과, 지나치게 이질적"),
부위별 축으로 흡수하면 신규 축 없이 150 미만으로 떨어진다고 했다. 실제로 그렇게 됐다:
목걸이 13개 -> 목 축(초커가 목에 있는데 목걸이가 딴 데 있었다), 머리 장식 8개 ->
머리 장식 축, 여밈·부품 13개(`buttons`/`buckle`/`epaulettes`/`strap`) -> 디테일.

## Codex 리뷰 결과 (3회, 총 382건)

| 회차 | 대상 | 지적 | 수용 |
|---|---|---|---|
| 1차 | 의류 본체 7축 | 194 | 약 55 |
| 2차 | 상태·디테일·무늬 + 이관·제외 | 53 | 약 45 |
| 3차 | 부위 착용물 10축 | 135 | 약 120 |

3차가 가장 정확했다. 대부분이 체계적 패턴이라 개별 나열 대신 규칙으로 넣었다
(`^single \w` / `(on head|around neck)$` / `necklace$` / `gag(ged)?$` 등).

### 받지 않은 것과 그 이유

- **수식어 기준 재배치 약 90건**(1차) — `pleated skirt`/`miniskirt`/`pencil skirt` 를
  전부 디테일로 옮기라고 했다. 그러면 하의 축에 `skirt`/`shorts`/`pants` 6개만 남고
  디테일 축이 '모든 치마 변형' 잡동사니가 된다. body_expose 의 catch-all 이 이름만
  바꿔 재발하는 것이다. 기준을 명문화해서 대신했다 — §5 참조.
- **`striped` 제외**(2차) — 데이터가 "너무 넓은 태그"라고 하지만, 무늬 조합 설계가
  `striped shirt` = `striped` + `shirt` 로 분해하는 것을 전제하므로 맨 수식어를
  지우면 설계가 깨진다.
- **`dirty clothes` -> 부상·오염**(2차) — 목적지 축의 벤치가 `nude, safe` 라 옷이
  없다. 얼굴 부상 33장을 몸통 프레이밍 축에 합류시켜 전량 재생성했던 실수와 같은
  형태라 받지 않았다. **목적지 축의 프레이밍을 먼저 확인한다**가 그때 얻은 교훈이다.
- `puffy sleeves`, `g-string`, `turtleneck sweater` 근접중복 제외 — 고빈도 상용
  태그이고 초보자가 실제로 구분해서 찾는다.

### 내 쪽 버그로 확인된 것

| 버그 | 증상 | 발견 |
|---|---|---|
| 상태 정규식이 의류 명사로 판정 | `shirt`/`pleated skirt`/`t-shirt` 가 '착의 상태'로 (158 중 121) | 자체 |
| 디테일을 의류보다 먼저 검사 | `frilled skirt` 가 하의가 아니라 디테일로 | 자체 |
| `dress` 부분일치 | `dress shirt` 가 원피스로 | Codex 1차 |
| 제복이 수영복보다 먼저 | `school swimsuit`/`maid bikini` 가 제복으로 | Codex 1차 |
| 리다이렉트 문구 누락 | "~를 사용한다" 형태를 못 잡아 `highleg swimsuit` 잔존 | Codex 1차 |
| 접미 상태 미탐지 | `bra peek`/`bikini under clothes` 18건이 착용물로 | Codex 2차 |
| 괄호를 전부 작품명으로 간주 | `pom pom (clothes)`(28,680) 등 10개 통째 제외 | Codex 2차 |
| 개수 태그 오제외 | `multiple bracelets` 는 1인으로 렌더된다 | Codex 2차 |
| `patterns` subgroup 신뢰 | 트림·재질·여밈 14개가 '무늬'로 | Codex 2차 |
| 조합 수식어 도달 불가 | `frilled`/`plaid` 등 8개가 단독 태그로 없는데 분해 | 자체(2단계 검사 도입) |
| `loose` 접두 과일반화 | `loose socks`(교복 양말 종류)가 상태로 | 자체 |

## 6. 벤치 프롬프트 — 특징 축 방식을 그대로 쓸 수 없다

특징 축의 핵심 장치는 `nude, safe, rating:general` 이었다 — 옷이 특징을 가리지 않게 하고
NAI 가 필수 요소에만 집중하게 만든다. **의상은 옷이 주제이므로 이 장치를 쓸 수 없다.**

대체 장치는 **대조 의상(control garment)**: 변하지 않는 쪽을 고정해 변하는 쪽만 다르게 만든다.
`pleated skirt` 를 찍을 때 상의를 지정하지 않으면 NAI 가 매번 다른 상의를 그려서
그리드 전체가 시각적으로 시끄러워진다.

| 축 | 프레이밍 | 대조 의상 |
|---|---|---|
| 모자 / 머리 장식 / 안경·마스크 / 목 | `portrait, close-up` | `white shirt` |
| 상의 / 소매 / 손 | `upper body` | — |
| 하의 / 속옷 / 수영복 / 디테일 / 착의 상태 / 무늬 | `cowboy shot` | 하의축은 `white shirt` |
| 다리 | `cowboy shot` (하단) | `pleated skirt, white shirt` |
| 신발 | `lower body` 또는 `feet focus` | `pleated skirt, white shirt` |
| 원피스 / 제복 / 전통 / 스타일 / 갑옷 | 판단 필요 ↓ | — |

### 미해결 — 전신 의상의 프레이밍

사용자 지침: *"썸네일 크기로는 full body 소화가 불가능"* → 체형 축에 `cowboy shot` 을 썼다.
그런데 원피스·제복·전통은 **기장과 실루엣이 정체성**이라 `cowboy shot` 이면
`short dress` / `long dress` 를 구분할 수 없다. 두 요구가 충돌한다.
`cowboy shot` 기본 + 기장이 이름에 든 태그만 `full body` 로 분리하는 것이 후보이지만,
NAI 감각이 필요한 판단이라 사용자 확인 대상으로 남긴다.

### 신발·반지의 프레이밍

`feet focus` / 손 클로즈업은 NAI 의 약점(손발 왜곡)과 정면으로 겹친다.
이형 부위 축에서 발·다리 12개가 두 번 실패한 것과 같은 위험이다 — 파일럿 3장 필수.

## 7. 사용자 판단이 필요한 것

1. **전신 의상 프레이밍** — `cowboy shot`(썸네일 가독성) vs `full body`(기장 식별). §6
2. **색·무늬 조합 78개** — 태그 치환 팔레트를 새로 만들 것인가, 그냥 78장 생성할 것인가. §4
3. **`cloth_nsfw` 51개** — 노출(성인) 축과 합쳐 계속 보류할 것인가. (현재: 보류, 생성 안 함)
4. **의상 슬롯 분할** — ✅ 결정하고 배선했다: `의상`(13축) / `소품·장식`(10축).

## 8. 실행 순서

```bash
python tools/thumb_clothing_build.py     # 분류 확인 (미분류 0 이어야 한다)
python tools/thumb_axes_emit.py          # cloth_*.txt -> interactiveAxes.mjs
python tools/thumb_todo.py               # 팩 대비 부족분 산출
python tools/thumb_bench.py --dry-run    # 계획 확인
```

축당 파일럿 3장을 먼저 돌린다 — 특징 슬롯에서 파일럿 27장이 축 단위 프레이밍 실패
3건을 잡아 수백 장을 절약했다.
