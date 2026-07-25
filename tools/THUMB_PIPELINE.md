# Interactive 특징 썸네일 파이프라인

초보자가 NAI 태그를 못 다루는 문제를 "주요 특징에 썸네일을 미리 제공"으로 푼다.
`data/interactive_thumbnails.json`(팩)과 `app/web/remote/js/features/interactiveAxes.mjs`
(축 정의)가 산출물이고, 아래 스크립트가 그 둘을 만든다.

전부 **repo 루트에서** 실행한다(상대 경로 기준).

```
python tools/thumb_axes_build.py --threshold 60   # 태그 DB -> wildcards/thumb/*.txt
python tools/thumb_todo.py                        # 팩과 대조해 미생성 목록 -> _todo/
python tools/thumb_manifest.py                    # 축별 프레이밍/현황 -> _manifest.json
python tools/thumb_bench_init.py                  # 축별 고정 베이스 -> _bench.json
python tools/thumb_axes_emit.py                   # wildcards -> interactiveAxes.mjs
python tools/thumb_bench.py <배치...>             # NAI 생성 (headless)
python tools/thumb_sheet.py <폴더> --pack         # 컨택트시트로 검수
python tools/build_interactive_thumbnails.py <폴더>   # 팩에 합류
python tools/build_interactive_thumbnails.py --prune  # 재분류 후 고아 키 정리
```

## 단일 출처

| 산출물 | 출처 |
|---|---|
`wildcards/thumb/<axis>.txt` | 태그 DB + `thumb_axes_build.py` 의 분류 규칙 |
`wildcards/thumb/_bench.json` | `thumb_bench_init.py` (승인 이미지 메타데이터 실측값) |
`interactiveAxes.mjs` | 위 두 개 + `_palette.json` |
`data/interactive_thumbnails.json` | 생성된 PNG + `build_interactive_thumbnails.py` |

`interactiveAxes.mjs` 를 손으로 고치지 말 것 — 다음 `thumb_axes_emit.py` 실행에 덮인다.

## 분류에서 배운 것 (같은 실수를 반복하지 않기 위해)

1. **catch-all 금지.** "규칙에 안 걸리면 X 축으로" 는 미분류 0을 보장하는 대신 X 를
   쓰레기통으로 만든다. 실제로 노출·강조 176개 중 131개가 행위/효과/내장/이형/폐기
   태그였다. 지금은 명시 배정이 최우선이고 안 걸리면 **미분류로 출력**한다.

2. **유니온은 재분류를 무력화한다.** "이미 생성한 태그를 잃지 말자"고 기존 목록과
   합집합을 하면, 방금 다른 축으로 옮긴 태그가 원래 축으로 되돌아온다. 두 번 겪었다
   (명시 목록 배정분, 그리고 정규식 배정분). `EXPLICIT` 지도가 이번 계산 결과 전체를
   담아 막는다.

3. **프레이밍은 축마다 다르고, 한 축 안에서도 갈린다.** `cowboy shot` +
   `head out of frame` 은 몸통에 화소를 몰아주지만 머리 부속(뿔/귀/아가미)을 잘라낸다.
   `_todo/` 는 `FRAMING_SPLIT` 으로 배치를 쪼갠다.

4. **파일럿을 먼저 돌린다.** 축당 3장이면 프레이밍 실패가 드러난다. 실제로 상태(얼굴이
   작아 홍조가 안 보임) / 꼬리(프레임 하단 잘림) / 날개(접힌 채 작게) 세 축을 27장으로
   잡아냈다. 전량 돌린 뒤 발견하면 수백 장이 낭비된다.

5. **데이터가 스스로 알려준다.** 태그 설명의 "폐기된 태그" / "모호한 태그" /
   "~를 사용한다" 는 전부 실제 문제였다. 반대로 **저빈도라고 빼면 안 된다** — freq 60
   이상은 유의미하다는 것이 사용자 판단이다.

6. **Danbooru 의 폐기 ≠ NAI 렌더 불가.** `french braid`(31,989) 는 Danbooru 에서
   폐기됐지만 NAI 는 잘 그린다. 이미 생성한 이미지가 있으면 규범 때문에 버리지 않는다.

## 프롬프트 철학 (사용자)

- `young female` 고정. 네거티브에 `{adolescent, mature female}`, `oldest female` 을
  넣어 성인 여성 톤을 회피한다.
- `nude, safe, rating:general` 은 **NAI 가 필수 요소에만 집중하게** 만드는 장치다.
  옷이 특징을 가리지 않고, 사용자 시선이 어디로 갈지도 통제된다.
- 구도는 그 요소를 **돋보이게** 하는 데 집중한다 — 뿔은 초상, 날개는 `spread wings` +
  뒤에서, 꼬리는 `tail raised` + cowboy, 체형은 얼굴을 버리고 몸통.
- 아티스트 0.38 저가중 + `watercolor (medium)` 0.4: 얇은 라인, 흰 배경, 균일한 톤.

## 승인 한도

`thumb_bench.py` 는 사용자가 명시 승인한 한도를 코드에서 강제한다 —
**3000 요청 / steps 28 / 1024x1024 고정**. 정의 파일이 바뀌어도 도구가 막는다.

## 보류

`노출(성인)` 축 33개는 자동 생성하지 않는다. 사유와 목록·벤치는
`wildcards/thumb/_DEFERRED_body_nsfw.md` 참조.
