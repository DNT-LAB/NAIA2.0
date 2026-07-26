# 의상 섹션 생성 실행서 (2026-07-26 06:00 KST 예약 실행용)

이 문서는 **이전 대화 기억이 없는 실행**을 전제로 쓴 자립형 절차서다.
분류 근거는 [CLOTHING_PLAN.md](CLOTHING_PLAN.md), 승인 근거는
[../wildcards/thumb/_APPROVAL.md](../wildcards/thumb/_APPROVAL.md) 를 먼저 읽는다.

작업 디렉터리는 `C:\VNR\DEV\NAIA2.0` 이고 모든 명령은 `PYTHONUTF8=1` 로 돈다.

## 0. 전제 확인 (건너뛰지 말 것)

```bash
python -c "import json;d=json.load(open('wildcards/thumb/_bench.json',encoding='utf-8'));print(len([k for k in d['batches'] if k.startswith('cloth')]),'개 의상 배치')"
```

- `_APPROVAL.md` 에 2026-07-26 06:00 KST 초기화가 적혀 있어야 한다. 없으면 **중단**하고 사용자에게 묻는다.
- `cloth_nsfw` 는 생성 대상이 아니다. `_bench.json` 에 정의가 없으므로 도구가 자동으로 건너뛴다.

## 1. 파일럿 18장 (반드시 먼저)

프레이밍 그룹 6종 × 대표 3장. 특징 슬롯에서 파일럿이 축 단위 실패 3건을 잡아
수백 장을 절약했다. 의상은 `nude, safe` 를 쓸 수 없어 **대조 의상**으로 배경 잡음을
잡는 새 방식이라 검증이 더 중요하다.

```bash
python tools/thumb_bench.py _pilot_head _pilot_upper _pilot_bottom _pilot_torso _pilot_lower _pilot_outfit --out user-data/output/cloth_pilot
```

### 파일럿 판정 기준

각 그룹에서 확인할 것:

| 그룹 | 프레이밍 | 확인 |
|---|---|---|
| `_pilot_head` | portrait + `white shirt` | 모자·후드가 잘리지 않는가. 흰 셔츠가 매번 같은가 |
| `_pilot_upper` | upper body | 상의 전체가 프레임에 들어오는가 |
| `_pilot_bottom` | cowboy shot + `white shirt` | 치마가 보이는가. 상의가 흰 셔츠로 고정됐는가 |
| `_pilot_torso` | cowboy shot | 속옷이 보이는가. 등급이 튀지 않는가 |
| `_pilot_lower` | lower body + `pleated skirt, white shirt` | **신발이 실제로 보이는가** (가장 위험) |
| `_pilot_outfit` | cowboy shot | 원피스 상반신으로 종류가 구분되는가 |

`_pilot_lower` 가 가장 위험하다. `lower body` 가 NAI 에서 잘 듣지 않으면
`feet focus` 또는 `full body` 로 바꿔야 하는데, 손발 왜곡은 NAI 의 약점이다.
**실패하면 다리·신발 2축(59장)만 보류하고 나머지 20축을 진행한다** — 이형 부위
발·다리 12개가 두 번 실패한 것과 같은 함정이라 억지로 밀지 않는다.

Vision 으로 18장을 직접 보고 판정한다. 파일럿을 건너뛰고 본 배치를 돌리지 않는다.

### 2026-07-26 파일럿 판정 — 6그룹 전부 PASS

| 그룹 | 판정 | 근거 |
|---|---|---|
| `_pilot_head` | PASS | 모자·후드·헤일로 모두 잘리지 않음. 헤일로가 상단에 온전히 들어옴 |
| `_pilot_upper` | PASS | shirt/jacket/collared shirt 구분됨. 얼굴 비중이 크지만 의류 정체성은 읽힘 |
| `_pilot_bottom` | PASS | 대조 의상 3/3 흰 상의 유지(1장은 칼라 없는 흰 티). 주름 식별됨 |
| `_pilot_torso` | PASS | underwear·bra 선명. `panties` 는 긴 흰 티에 가려 하단만 노출 — 프레이밍이 아닌 태그 특성 |
| **`_pilot_lower`** | **PASS** | **`lower body` 가 신발을 또렷하게 렌더. 부츠↔로퍼 구분, 발 왜곡 없음, 양말까지 보임** |
| `_pilot_outfit` | PASS | dress/leotard/sleeveless dress 구분됨. 기장 문제는 §6-1 그대로 |

**대조 의상(control garment) 방식이 검증됐다** — 흰 상의를 고정하니 하의·머리 축의
배경 잡음이 실제로 잡혔다. 유일한 흔들림은 흰 상의의 *종류*(칼라/프릴/티셔츠)가
매번 다른 것인데, 색이 흰색으로 고정되므로 그리드 균일성에는 영향이 작다.

## 2. 본 배치 864장

파일럿이 통과한 프레이밍 그룹만 돌린다.

```bash
python tools/thumb_bench.py cloth_headwear cloth_hairacc cloth_neck cloth_eyewear cloth_top cloth_sleeve cloth_handwear cloth_bottom cloth_under cloth_swim cloth_state cloth_detail cloth_pattern cloth_accessory cloth_dress cloth_outer cloth_traditional cloth_uniform cloth_style cloth_armor --out user-data/output/cloth
```

배치 이름은 **위치 인자**다(`--batches` 플래그는 없다). 중단 후 재개는 `--skip-existing`.

다리·신발은 파일럿 통과 시에만 추가한다: `cloth_legwear cloth_footwear`
(2026-07-26 파일럿에서 **통과** — `lower body` 가 신발을 또렷하게 렌더했다)

축별 장수(2026-07-26 `--list` 실측, 합계 864): 액세서리 116 · 모자 84 · 디테일 84 ·
착의상태 62 · 상의 55 · 제복 53 · 머리장식 49 · 목 43 · 속옷 39 · 원피스 34 · 하의 31 ·
안경 31 · 신발 28 · 소매 24 · 다리 24 · 수영복 23 · 전통 19 · 겉옷 16 · 갑옷 16 ·
스타일 12 · 손 11 · 무늬 10

## 3. 팩 반영

```bash
python tools/build_interactive_thumbnails.py --prune
python tools/thumb_todo.py
```

`--prune` 은 재분류된 키를 삭제 대신 이동시킨다(무손실). `thumb_todo` 가 부족분을 낸다.

## 4. 검수

축별로 contact sheet 를 만들어 Vision 으로 본다. `--pack` 은 팩과 같은 192px
중앙 크롭을 적용해 실제 사용 화면과 난이도를 맞춘다.

```bash
python tools/thumb_sheet.py --axis cloth_top --pack
```

렌더되지 않은 태그는 시드를 바꿔 한 번 더 돌린다(`--seed`).

## 5. 프론트 확인

배선은 이미 끝나 있다 — 슬롯 `의상`(13축) + `소품·장식`(10축).
캐시 마커는 `20260725-ax52` / `ia52` 다. 이미지가 늘면 마커를 올린다.

```bash
python tools/thumb_axes_emit.py
```

## 5-1. 2026-07-26 실행 결과

864/864 생성, **실패 0 / 재시도 0**, 81분. 팩 2,350키(15.6MB). 22축 전부 `thumb_todo` DONE.
시드 재생성 30장 + 장신구 프레이밍 파일럿 3장 추가 → 이 구간 총 915회 사용.

캐시 마커는 `20260726-ax53` / `ia53` 으로 올렸다. **마커는 3곳이다** —
`interactivePanel.mjs`(ax), `app.js`(ia), 그리고 **`index.html` 의 `app.js?v=`**.
index.html 을 빼먹으면 app.js 자체가 캐시돼 변경이 반영되지 않는다.

### 검수에서 드러난 구조적 한계 3종 (시드로 해결 불가)

1. **부재(absence) 태그** — `no bra`/`no panties`/`no shirt`/`no socks`.
   렌더할 대상이 없어 '다른 옷을 입은 그림'이 나온다. 제외 후보.
2. **`front view` 고정** — `back cutout`/`backless outfit`/`backless dress` 는
   등이 안 보인다. 태그별 `from behind` 오버라이드가 있어야 한다.
3. **소형 장신구 × cowboy shot** — §6-5 참조. 가장 큰 건이다.

### 재생성 결과

시드를 `7731905442` 로 바꿔 30장 재생성 → 19장 개선(병합), 11장 미개선(보류).
**주의: 재생성본이 원본보다 나쁠 수 있다.** 이번에 `male underwear`/`covered collarbone`/
`bike shorts under skirt` 3장이 **2인으로 렌더**돼(solo 위반) 원본보다 나빴다.
재생성 폴더를 통째로 병합하면 멀쩡한 원본이 덮인다 — **선별 병합 필수**.

### `thumb_axes_emit.py` 요약 줄은 믿지 말 것

"썸네일 축 22개" 는 `_manifest.json`(특징 축만 있는 구버전) 에서 세는 값이라
의상 축이 빠진 것처럼 보인다. 실제 `THUMB_TAGS` 는 `_referenced` 기준이라
cloth 23축이 정상 포함돼 있다. 확인은 `grep -c cloth_ interactiveAxes.mjs`.

## 6. 사용자 판단이 필요해 남겨둔 것

이 항목들은 **임의로 결정하지 말고** 작업 종료 시 보고한다.

1. **원피스·제복·전통의 프레이밍** — ⚠️**2026-07-26 실측으로 상당 부분 기우로 판명.**
   `cloth_outfit` 벤치가 예상보다 넓게 잡혀 `short dress`/`medium dress`/`long dress`/
   `evening gown`/`wedding dress` 가 **기장으로 구분된다**. 원피스 축은 손댈 것이 없다.
   대신 **하의 축에서 같은 문제가 실제로 발생**했다 — `pants`/`track pants`/`baggy pants`/
   `tight pants`/`yoga pants`/`high-waist pants`/`capri pants`/`long skirt` 8개가
   허벅지에서 잘려 서로 구분되지 않는다. 판단 대상은 원피스가 아니라 **하의 8개**다.
2. **색·무늬 조합** — ✅**2026-07-26 해결(배선 완료).** `_cloth_combo.json` 100개를
   프론트로 내보내(`CLOTH_COMBO` / `CLOTH_COMBO_REV`) 조언 플로트에서 색을 붙인다.

   > 여기 "팔레트 기능이 생기기 전까지 탐색기로만 접근된다"고 적어 둔 것이 **실제
   > 위험이었다**. 자세 슬롯에서 탐색기를 떼면서 의상도 같이 떼려다 재보니, 탐색기
   > 전용 1,251개 안에 `white shirt`(541,974 — DB 최다 의상 태그)·`black gloves`
   > (279,187)·`black skirt`(202,982)가 있었다. 그대로 뗐으면 사라졌다.

   색은 **마지막에 고른 옷 하나**에만 붙인다. 슬롯 전체 팔레트로 두면 shirt+skirt 를
   고른 뒤 흰색을 눌렀을 때 어느 쪽이 흰색인지 정할 수 없다.
   베이스마다 **확정된 색만** 낸다(35종, 대부분 1~4색) — 28색을 다 열면 `green shirt`
   처럼 실측으로 확인되지 않은 조합을 권하게 된다.
3. **`cloth_nsfw` 51개** — `body_nsfw` 40개와 함께 보류. 사용자가 직접.
4. **다리·신발 프레이밍** — ✅**해결.** 파일럿·본배치 모두 통과했다(§1, 52/52 선명).
   더 이상 판단 대상이 아니다.

5. **🆕 소형 장신구 38개의 프레이밍 — 이번 실행 최대 발견.**
   `cloth_accessory` 116개 중 **38개(33%)** 가 `cowboy shot` 에서 판독 불가다:
   귀 19(`earrings`·`hoop earrings`·`earclip`·`ear ribbon` …) / 손가락·손목 12
   (`ring`·`bracelet`·`bangle`·`watch` …) / 소형 일반 7(`jewelry`·`gem`·`chain` …).
   192px 팩 크롭에서 귀는 약 15px라 **시드로는 절대 해결되지 않는다.**

   **파일럿 3장으로 근거를 만들어 뒀다** — `earrings`/`ring`/`bracelet` 을 portrait
   (`cloth_head` 템플릿)로 찍으니 **셋 다 또렷하게 읽힌다**
   (`user-data/output/cloth_redo/_pilot_acc_portrait/`).

   선택지:
   - (A) 38개를 portrait 로 재생성 → 38회. 축 안에 두 프레이밍이 섞인다.
   - (B) 38개를 `cloth_hairacc`/`cloth_neck` 처럼 portrait 축으로 분리 → 축 재편 필요.
   - (C) 그대로 둔다 → 액세서리 축의 1/3이 사실상 빈 썸네일.

   파일럿 3장은 **축 일관성을 깨지 않으려고 팩에 병합하지 않았다.** 결정 후 반영한다.

---

## 7. 계층 탐색기 재평가 (2026-07-26 측정)

자세 슬롯에서 탐색기를 뗀 뒤 나머지 슬롯도 같은 방식으로 재봤다.

| 슬롯 | 스코프 | 썸네일 중복 | 탐색기 전용 | 전용의 성격 |
|---|---|---|---|---|
| 자세 | 2,360 | 1,757 (74%) | 514 | 전부 freq 50~99 · 한글 설명 0/514 → **제거함** |
| 표정 | 382 | 332 (86%) | 24 | 1개만 freq 100 이상 → **제거 가능** |
| 의상 | 2,082 | 759 (36%) | 1,251 | freq 1000+ 가 90개 → **유지** |
| 소품 | 1,443 | 614 (42%) | 824 | freq 1000+ 가 77개 → **유지** |

자세의 전용분은 *꼬리*였는데 의상은 *머리*다. 같은 처리를 하면 안 된다.

### 의상 탐색기를 떼려면 먼저 정리해야 하는 것

조합 100개를 빼도 전용이 1,192개 남는다. 그중 고빈도는 **축에서 미끄러진 것들**이다:

| 태그 | freq | 있어야 할 곳 |
|---|---|---|
| `no headwear` | 18,999 | 착의 상태(`cloth_state`) |
| `unworn hat` | 13,706 | 착의 상태 |
| `unworn panties` | 5,380 | 착의 상태 |
| `unworn skirt` | 5,220 | 착의 상태 |
| `unworn clothes` | 4,791 | 착의 상태 |
| `unworn eyewear` / `unworn shoes` | 8,708 / 7,307 | 착의 상태 |
| `alternate hairstyle` | 60,753 | **머리 슬롯** (의상 탐색 범위에 섞였다) |
| `alternate hair length` | 12,425 | **머리 슬롯** |
| `official alternate hairstyle` | 19,513 | **머리 슬롯** |
| `nude` / `completely nude` | 269,994 / 109,029 | 보류한 성인 계열 |
| `cosplay` / `official alternate costume` | 72,527 / 194,610 | 메타 태그 — 축 소속 판단 필요 |

`unworn *` 계열을 `cloth_state` 로 옮기고 `alternate *` 를 머리 슬롯으로 넘기면
의상 탐색기도 뗄 수 있는 상태가 된다. 옮긴 태그는 썸네일이 없어 '준비 중' 으로
뜨므로 생성이 뒤따라야 한다(약 20~30장).

### 참고 — 탐색기 전용에 섞인 함정

freq 0 인 비표준 별칭이 자세에서 9개 나왔다. 정식 태그는 이미 썸네일에 있다.

| 탐색기의 것 | freq | 정식 태그 | freq |
|---|---|---|---|
| `hands on hips` | 0 | `hands on own hips` | 16,940 |
| `looking back at viewer` | 0 | `looking back` | 161,757 |
| `hands together` | 0 | `own hands together` | 46,327 |

의상·소품 스코프도 같은 검사를 해봐야 한다(아직 안 했다).
