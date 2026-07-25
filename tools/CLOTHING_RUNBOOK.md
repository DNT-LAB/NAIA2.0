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
python tools/thumb_bench.py --batches _pilot_head,_pilot_upper,_pilot_bottom,_pilot_torso,_pilot_lower,_pilot_outfit --out user-data/output/cloth_pilot
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

## 2. 본 배치 864장

파일럿이 통과한 프레이밍 그룹만 돌린다.

```bash
python tools/thumb_bench.py --batches cloth_headwear,cloth_hairacc,cloth_neck,cloth_eyewear,cloth_top,cloth_sleeve,cloth_handwear,cloth_bottom,cloth_under,cloth_swim,cloth_state,cloth_detail,cloth_pattern,cloth_accessory,cloth_dress,cloth_outer,cloth_traditional,cloth_uniform,cloth_style,cloth_armor --out user-data/output/cloth
```

다리·신발은 파일럿 통과 시에만 추가한다:
`--batches cloth_legwear,cloth_footwear`

축별 장수: 액세서리 116 · 모자 84 · 디테일 84 · 착의상태 64 · 상의 55 · 제복 53 ·
머리장식 49 · 목 43 · 속옷 39 · 원피스 34 · 하의 31 · 안경 31 · 신발 28 · 소매 24 ·
수영복 23 · 다리 23 · 전통 19 · 겉옷 16 · 갑옷 16 · 스타일 12 · 무늬 10 · 손 11

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

## 6. 사용자 판단이 필요해 남겨둔 것

이 항목들은 **임의로 결정하지 말고** 작업 종료 시 보고한다.

1. **원피스·제복·전통의 프레이밍** — 사용자 규칙("썸네일 크기로는 full body 소화가
   불가능")에 따라 `cowboy shot` 을 썼다. 그 결과 `short dress` / `long dress` 의
   기장 차이는 구분되지 않는다(34개 중 2개). 그대로 둘지 판단 필요.
2. **색·무늬 조합 78개** — `white shirt` / `striped shirt` 류는 썸네일을 만들지 않고
   `_cloth_combo.json` 에 본체+수식어로 분해해 뒀다. 팔레트로 조합하는 프론트 기능이
   생기기 전까지 이 78개는 탐색기·자동완성으로만 접근된다.
3. **`cloth_nsfw` 51개** — `body_nsfw` 40개와 함께 보류. 사용자가 직접.
4. **다리·신발 프레이밍** — §1 참조.
