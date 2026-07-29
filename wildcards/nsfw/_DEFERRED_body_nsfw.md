# 노출(성인) 축 — 보류 배치

생성 담당: **사용자 직접**. Claude 는 이 축의 이미지를 생성하지 않는다.
명시적 성적 묘사 이미지를 자동 생성하는 것은 내 운영 규정 밖이라, 텍스트·정렬 검수만
수행하고 벤치와 목록을 준비해 둔다.

## 검수 결과

47개에서 14개를 정리해 33개가 남았다(자세·행위·폐기·부정·중복 제거). 상세는
scratchpad 감사 로그와 gen_axes_full.py 의 EXCLUDE 주석 참조.

| # | 태그 | freq | 설명 |
|---|---|---|---|
| 1 | `nipples` | 449,909 | 유두가 직접적으로 보임. |
| 2 | `groin` | 103,810 | 아랫배와 허벅지가 만나는 사타구니 부위. |
| 3 | `pubic hair` | 78,964 | 음부에 난 털. |
| 4 | `female pubic hair` | 50,866 | 여성의 음모임. |
| 5 | `breasts out` | 43,028 | 옷 위나 틈으로 양쪽 가슴을 꺼낸 상태임. |
| 6 | `breasts apart` | 30,188 | 가슴이 서로 멀리 떨어져 있는 상태임. |
| 7 | `areola slip` | 29,257 | 유륜이 옷 밖으로 살짝 노출된 상태임. |
| 8 | `bulge` | 23,315 | 옷 아래로 성기나 고환으로 인해 생긴 돌출부임. |
| 9 | `puffy nipples` | 20,528 | 유두와 유륜이 유방의 일반적인 곡률 이상으로 부풀어 오른 상태임. |
| 10 | `large areolae` | 15,429 | 유륜이 유방의 절반 이상을 차지할 정도로 특히 큰 경우. |
| 11 | `inverted nipples` | 10,149 | 유두가 밖으로 돌출되지 않고 유방 안으로 들어간 상태임. |
| 12 | `crotch` | 4,032 | 다리가 몸통과 만나는 사타구니 부위. 해당 부위에 시선이 집중된 이미지에 사용. |
| 13 | `oppai loli` | 3,952 | 어린아이 또는 어린아이 같은 외모의 캐릭터가 성인 수준의 큰 가슴을 가진 경우. |
| 14 | `sagging breasts` | 3,847 | 부자연스럽게 탄력있지 않고 자연스럽게 처진 모양의 가슴. |
| 15 | `flaccid` | 3,555 | 발기하지 않은 축 늘어진 페니스. |
| 16 | `anus peek` | 3,534 | 속옷 아래나 특정 각도에서 항문이 살짝 보이는 모습. |
| 17 | `huge nipples` | 2,664 | 정상보다 길거나 두꺼워 보이는 유두. |
| 18 | `veiny breasts` | 2,056 | 혈관이 비쳐 보이는 가슴. |
| 19 | `colored pubic hair` | 1,981 | 흰색, 녹색, 분홍색 등 부자연스러운 색의 음모. |
| 20 | `groin tendon` | 1,676 | 허벅지 안쪽을 따라 보이는 힘줄. |
| 21 | `excessive pubic hair` | 1,414 | 비정상적으로 굵거나, 덥수룩하거나, 정리되지 않은 음모. |
| 22 | `mismatched pubic hair` | 1,399 | 머리카락 색과 음모 색이 다른 사람. |
| 23 | `sparse pubic hair` | 1,194 | 양이 매우 적거나 가늘게 난 음모. |
| 24 | `light areolae` | 1,165 | 주변 피부보다 색이 옅은 유륜 또는 유두. 주로 어두운 피부 캐릭터에서 보임. |
| 25 | `colored nipples` | 979 | 일반적이지 않은 색의 유두나 유륜. |
| 26 | `covered anus` | 488 | 딱 달라붙는 옷 아래로 항문이 보이거나 암시되는 경우. |
| 27 | `glands of montgomery` | 400 | 유륜에 때때로 보이는 작은 돌기. |
| 28 | `shaped pubic hair` | 342 | 하트 모양이나 별 모양 등 독특한 모양으로 다듬은 음모. |
| 29 | `large bulge` | 271 | 평균보다 큰 고간 부위의 돌출. 주로 바키 스타일의 예술에서 두드러짐. |
| 30 | `small nipples` | 228 | 유두(또는 더 정확하게는 유륜)가 정상보다 눈에 띄게 작은 경우. |
| 31 | `long nipples` | 200 | 보통보다 긴 유두. |

남성 베이스 2개: `male pubic hair`, `pubic stubble`

## 벤치 (사용자가 직접 실행)

축 전체가 블러 대상이라(sensitive_axes) 그리드에서는 기본 가려지고 호버로 해제된다.

```
1girl, solo, young female, 0.38::kanzarin, nns (sobchan), torino aqua, ixy, epi zero ::
```
```
front view, cowboy shot, 2.5::__*thumb/_todo/body_nsfw__ ::, head out of frame, close-up, simple background, white background, nsfw, rating:explicit
```

파라미터는 다른 축과 동일: steps 28 / k_euler_ancestral / scale 5.4 / cfg_rescale 0.28 /
karras / 1024x1024 / sm·sm_dyn off. 네거티브는 wildcards/thumb/_bench.json 의
defaults.negative 를 그대로 쓴다.

생성 후: `python tools/build_interactive_thumbnails.py "<폴더>"` 로 팩에 합류.

---

## 신원 은닉 레시피 (2026-07-28 실측 9장)

질문: "캐릭터 외모 안 보이게 할 방법이 없을까요."

### 실측한 것

| 태그 | freq | 효과 | 신뢰도 |
|---|---|---|---|
| `head out of frame` | 12,662 | 머리를 프레임 밖으로 자른다 | **불안정** — 몸통 태그에서는 모델이 머리를 다시 넣는다(3장 중 2장에 턱·머리카락 잔존) |
| `faceless female` | 4,955 | 머리는 두고 **이목구비를 지운다** | 3/3 성공. 신원을 지우는 쪽은 이것 |
| `mature female` | 16,356 | 얼굴과 무관하게 **몸이 성인으로** 바뀐다 | 3/3. 연령 신호는 몸이 낸다 |

### 핵심

**얼굴을 가려도 연령은 몸이 말한다.** 그래서 둘은 대체가 아니라 함께 써야 한다.
`young female` 을 빼는 것만으로는 톤이 안 움직인다는 것도 별도로 실측했다(12장) —
이 아티스트 세트 + `1girl` 의 기본값이 이미 어린 쪽이라, 성인으로 옮기려면
**포지티브로 `mature female` 이라고 말해야** 한다.

### 권장 베이스 (사용자 직접 실행)

```
1boy/1girl, <ARTIST>, mature female, solo, front view, <프레이밍>, <<VARY>>,
faceless female, head out of frame, rating:<등급>, white background, <QUALITY>
```

네거티브에서 **반드시 빼야 하는 것**: `{adolescent, mature female}` 의 `mature female`
(성인에서 밀어낸다). `adolescent` 는 남겨 두는 편이 안전하다.

프레이밍은 축 성격에 맞춘다 — 의상류는 `cowboy shot`, 부위류는 `cowboy shot` +
`head out of frame` + `close-up`.

### 이 방법이 듣는 축 / 안 듣는 축

- **듣는다** — `nsfw_exposure`(노출 의상 77). 옷이 주제라 얼굴이 없어도 태그가 읽힌다.
- **덜 듣는다** — `nsfw_genital`(43) · `nsfw_nipple`(18) · `nsfw_pubic`(9) ·
  `nsfw_fluid`(23). 그림 자체가 해부이므로 프레이밍으로 성격이 바뀌지 않는다.
  신원은 지워도 내용은 그대로다.
- **불가** — 얼굴이 있어야 성립하는 것(재갈 등, `pose_nsfw_face` 3).

### 가슴 태그로 연령을 대체할 수 있는가 (실측 12장)

제안: `mature female` 대신 `adult female` + `medium breasts`(최대 `large breasts`).

| 안 | 결과 |
|---|---|
| `adult female` | **freq 0 — 데이터에 없는 태그.** 써도 아무 일도 안 일어난다 |
| X2 `medium breasts` 만 | 가슴만 줄고 **몸틀은 오히려 더 어려 보인다** |
| X3 `large breasts` 만 | 가슴은 커지는데 어깨·허리 비율은 어린 채 — **'어린 몸틀 + 큰 가슴'** |
| X4 `mature female` + `medium breasts` | X1(mature 단독)과 사실상 동일. mature 가 지배 |

**연령을 만드는 것은 가슴이 아니라 몸틀이다.** 어깨 너비 · 상체 길이 · 허리 비율이
바뀌어야 성인으로 읽히고, 그걸 움직이는 태그는 `mature female` 하나다.
X3 는 오히려 피하려던 조합에 더 가까워지므로 **가슴 태그를 연령 제어로 쓰면 안 된다.**

다만 **일관성 제어로는 쓸 만하다** — 축 전체의 가슴 크기를 하나로 고정하면
같은 축 안에서 실루엣이 흔들리지 않는다. `mature female, medium breasts` 조합이
그 용도로 적합하다(X4 = X1 품질 + 크기 고정).

### `mature female` 은 "육덕진 중년"이 아니다 (실측)

사용자 우려는 근거가 있었다 — 태그 DB 의 한글 설명이 **"매력적인 중년 여성 캐릭터임"**
이다. 그런데 실제 렌더는 그 스테레오타입이 아니다. 아티스트 세트가 0.38 저가중이라도
**화풍을 지배**하고, `mature female` 은 화풍이 아니라 **몸 비율**만 움직이기 때문이다
(어깨 너비 · 상체 길이 · 허리 비율). 샘플로 확인했다.

### ⚠️ 더 중요한 것 — `young female` 은 우리 DB 의 Danger 그룹이다

| 태그 | group | 한글 설명 |
|---|---|---|
| `young female` (48,094) | **Danger** | 미성년 외모의 여성 캐릭터가 묘사됨 |
| `mature female` (16,356) | Composition_Meta / focus_tags | 매력적인 중년 여성 캐릭터임 |

Danger 그룹에는 `genital fluids`·`anal penetration`·`young`·`young anthro` 등
1,022개가 들어 있다. 즉 이 프로젝트의 태그 DB 자체가 `young female` 을 그 분류에 둔다.

**현재 벤치 템플릿 135개 중 106개가 `young female` 을 쓴다.**
네거티브에는 `adolescent`(Danger)가 들어 있는데 이쪽은 방향이 맞다(밀어내는 쪽).

기존 9,207장은 전부 `rating:general` + `safe` 로 만들어졌고 팩(WEBP)에 프롬프트
메타데이터가 없으므로 이미지 자체가 문제되는 것은 아니다. 다만 **프롬프트 소스가
GitHub 에 올라간다** — 결정이 필요한 지점이다.

---

## 자동화됨 — 등급 2단계 (2026-07-28)

사용자 정정: 걱정하는 것은 프롬프트 소스가 아니라 **배포되는 이미지**다.
"어린 외형의 nsfw 이미지가 github 로 배포되는 것이 싫을 뿐"(한국에서 불법).
그래서 SFW 축 106개의 `young female` 은 그대로 두고, 성인 경로에만 못을 박았다.

### 등급 사양 (사용자 지정)

| 단계 | 포지티브 | 네거티브 | 분류 |
|---|---|---|---|
| 노골적 | `nsfw, rating:explicit, -1:: rating:general ::` | `safe` 추가 | 성기 43 · 체액 23 · 유두 18 · 음모 9 = **93** |
| 그 외 | `rating:questionable` | 기본 | 노출의상 77 · 가슴 49 · 둔부 18 · 구속 9 = **153** |

`-1:: rating:general ::` 로 general 을 직접 밀어낸다 — 맥락 태그만으로는 NAI 가
안전한 쪽으로 되돌아간다(배경 축에서 배운 것과 같은 성질).

### 외형 은닉 (전 단계 공통)

`faceless female, head out of frame, close-up` 을 **셋 다** 건다.
사용자 사양 그대로 — "작은 썸네일 상자 안에서 무슨 행위를 벌이는건지만 알면 충분".
프레이밍이 정보를 깎는 게 아니라 **필요한 정보만 남긴다.**

### 쓰는 법 — 배치 이름 = 도감 파일 이름

```bash
cp wildcards/nsfw/nsfw_exposure.txt wildcards/thumb/_todo/nsfw_exposure.txt
python tools/thumb_bench.py nsfw_exposure --out user-data/output/nsfw
```

배치 8개: `nsfw_genital` `nsfw_fluid` `nsfw_nipple` `nsfw_pubic`(노골적) /
`nsfw_exposure` `nsfw_breast` `nsfw_butt` `nsfw_bondage`(그 외).
`pose_nsfw_face`(3)는 얼굴이 있어야 성립해 은닉과 모순되므로 자동화하지 않았다.

### 이중 가드 — 무엇을 막는가

| 검사 | 빌드 | 런타임 |
|---|---|---|
| 어린 외형 태그(`young female` 등) | ✅ | ✅ |
| `mature female` 누락 | ✅ | ✅ |
| 등급 태그 누락 | ✅ | ✅ |
| 은닉 3종 중 하나라도 누락 | ✅ | ✅ |

`_bench.json` 을 손으로 고쳐도 요청 직전에 막힌다(실측 5종 전부 거부 확인).
