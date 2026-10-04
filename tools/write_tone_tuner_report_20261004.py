"""Create the Korean report from the already-computed offline tables; no overwrite."""
from __future__ import annotations

import csv
import json
import platform
from pathlib import Path

import numpy
import pyarrow
import scipy

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/tone_tuner_2026_10_04"
REPORT = ROOT / "docs/TONE_TUNER_TAG_RESEARCH_2026_10_04.md"


def read_json(name):
    with (OUT / name).open(encoding="utf-8") as f:
        return json.load(f)


def num(value, digits=2):
    return "—" if value in ("", None) else f"{float(value):.{digits}f}"


def observation_table(rows):
    chosen = [("night", "lightness"), ("indoors", "lightness"), ("outdoors", "chroma"),
              ("day", "chroma"), ("sunlight", "lightness"), ("wet", "grain"),
              ("sweat", "grain"), ("skindentation", "sharpness"), ("tanlines", "chroma"),
              ("depth of field", "sharpness"), ("backlighting", "sharpness"), ("bloom", "sharpness")]
    index = {(x["tag"], x["axis"]): x for x in rows if x["slot"] == "prompt"}
    table = ["|태그 / 축|있음 / 없음|원시 평균 차|작가 내 차|동반 태그 보정 차 [95% CI]|BH q / 변동 작가 수|",
             "|---|---:|---:|---:|---|---:|"]
    for key in chosen:
        x = index[key]
        d = 3 if key[1] == "grain" else 2
        table.append(f"|`{key[0]}` / {key[1]}|{x['n_present']} / {x['n_absent']}|{num(x['delta_mean'], d)}|{num(x['within_beta'], d)}|{num(x['adjusted_beta'], d)} [{num(x['adjusted_low'], d)}, {num(x['adjusted_high'], d)}]|{num(x['adjusted_q_bh'], 5)} / {x['informative_artists']}|")
    return "\n".join(table)


def main():
    catalog = read_json("catalog_draft.json")
    summary = read_json("observational_summary.json")
    subset = read_json("size_sensitivity_summary.json")
    with (OUT / "observational_effects.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    nai = [it["tags"][0] for it in catalog["items"] if it["kind"] == "nai_only"]
    nl = [it["tags"][0] for it in catalog["items"] if it["kind"] == "natural_language"]
    report = r"""# Tone Tuner 태그 조사 — 2026-10-04

## 먼저: §3 패널 모델에 대한 이견

**[추정·설계 의견] ‘한 항목 = 하나의 양방향 연속 슬라이더’는 기본 모델로 삼지 않는 편이 안전하다.** 떠 있는 창과 **같은 시드 한 장 시험 → 전후 비교 → 명시 반영** 흐름에는 이견이 없다. 다만 자리·효과·상태를 다음처럼 분리해야 한다.

1. **자리 선택 + 세기**를 기본으로 한다. 프롬프트/네거티브/프롬프트 음수는 서로 다른 조건 경로다. 왼쪽을 무조건 ‘반대 효과’로 읽지 않는다. `negative:colorful`은 채도 감소가 아니라 증가했던 기록도 있다. `grey theme`의 양방향 효과는 특별히 검증된 사례이지 모든 태그의 법칙이 아니다.
2. **끄기 = 삭제**, `0::tag ::` 삽입이 아니다. 0 상태·영점 프리셋 상태·기준 그림의 0점은 서로 다르다. 현재 프롬프트가 소유한 태그를 UI가 임의로 지우면 안 된다. 반영 전 변경 diff, 소유 범위, 원문 보존·되돌리기 계약을 정한다.
3. 지금 상태를 단일 숫자에 억지로 맞추지 않는다. **중복, 별칭, 양쪽 공존, 서로 다른 가중치, 열린/중첩 묶음, 전역/캐릭터 칸**은 ‘혼합/충돌’ 상태로 보여야 한다. prefix의 `0.75::`가 postfix에서 닫히므로 칸마다 파싱하면 틀린다. `detailed background`는 영점에서 **−0.25**다.
4. 연도(2020~2026)는 배타 선택, complexity는 범주와 가중치의 별도 선택, `grey theme`·굵은 선은 **비선형/임계형**, 밝기 셋은 묶음 recipe로 다룬다. ‘오른쪽일수록 더 좋아짐’은 보장할 수 없다.
5. **국소 표면 조정과 내용·스타일 전환**을 나눈다. `shiny skin`과 `wet`, `muscular`, `tan`은 같은 종류의 개선 손잡이가 아니다. 피부색·주름·체형은 품질 서열이 아니다. ‘장면형/내용형’에는 재구성 경고를 붙인다.
6. 이 초안의 모든 `weight_range`는 **검증할 가중치 구간 제안**이다. 안전 범위·제품 기본값·무료 생성 보장이 아니다. 네거티브의 음수 가중치는 목록 전체에서 금지했다.

**[실측·읽기 전용 재현] 먼저 해결할 별도 문제:** 현행 advisor의 숫자 가중치 정규식은 숫자로 끝난 작가명 뒤의 닫는 `::`를 새 가중치로 오인한다. 아래 §8에 재현을 남겼다. 이번 조사에서는 코어를 고치지 않았다. 패널 상태 읽기/편집을 붙이기 전에 Claude가 별도 수정 여부를 결정해야 한다.

## 1. 핵심 요약: 가장 값진 후보와 이유

근거 표기: **[실측]** 이번 실행의 파일 대조·관찰 통계·읽기 전용 파서 재현. **[기록]** 저장소 메모·프리셋·이전 생성 측정(이번에 재측정하지 않음). **[지식]** 표현의 일반적 의미. **[추정]** V5 효과/안전 세기/위험의 가설. **[커뮤니티]** 외부 경험담(이번 새 채택 없음). **[웹]** 이번에는 없음: 외부 서비스 호출 금지에 따라 웹·NovelAI 모두 호출하지 않았다. 로컬 메모의 ‘공식’은 최신 공식 문서를 직접 확인했다는 뜻이 아니다.

|우선 후보|값진 이유 / 자리|근거와 경계|
|---|---|---|
|`grey theme`|prompt로 채도 감소 / UC로 증가하는 비교 기준|[기록] 각각 6쌍. prompt 1에서 −64%·유지0.70, UC +76%·0.90. 스위치·배경 전환. §20.4/20.6|
|UC `high contrast`|그림을 유지하며 무르게 하는 기준|[기록] 10/10 또렷함 하락·중앙−17%·유지0.93. 채도 손잡이 아님. §20|
|prompt `ultra complexity` 0.15→0.5|또렷함 증가와 질감 부작용의 기준|[기록] 10/10 증가·중앙+34·유지0.81, 거칠기도10/10 증가. 높은 재구성 위험. §18|
|UC `black theme, dark, muted color`|어두운 그림 밝히기 / **개별 몫 분해**|[기록] 밝기6/6·+13.3·유지0.76/최저0.20. 세 단독 효과는 아직 모름. §20.4|
|`shiny skin`|사용자가 명시한 피부 끝 범위를 대표하는 국소 후보|[실측] 코퍼스129,045·관찰prompt0건. [지식/추정] 광택 의미는 있으나 V5 개선 미검증. ROI가 먼저 필요|
|`oiled`|광택과 액체 표면을 `wet`·`sweat`와 구별|[실측] 코퍼스355·관찰0. `oil`은 deprecated. [추정] 물성·장면 전환 여부를 함께 확인|
|`sweat` / `wet`|표면 묘사와 내용 공변을 분리할 수 있는 실제 관찰 후보|[실측] 257/86건. wet의 grain 차는 보정 후 크게 줄고, sweat는 전역 grain 증가 근거 없음|
|UC `flat color`|평면 채색 억제가 음영·광택을 늘리는지 확인|[지식] 평면 채색 의미. [추정] 억제≠채도 상승·품질 개선. 영점·UC 기존 상태부터 고정|
|UC `blending` / `bloom`|면 경계·빛 번짐을 각각 누를 후보|[추정] 고주파만 증가하고 얼굴 질감이 나빠질 수 있다. bloom 관찰3건이라 결론 불가|
|`detailed skin texture` / `detailed eyes`|현재 측정 축이 놓치는 세밀함을 시험|[실측] sparse index 미색인. [추정] 자연어 요구; 자동완성 빈도와 효능을 혼동하지 않음|
|`jaggy lines` + UC `no lineart`|선 소실 대응 재현 / 단독 효과 분해|[기록] 사용자 발견, 약20→34~44이나 시드 다른 장들. 고주파 증가≠좋은 선|
|prompt 음수 `thick outlines`|굵기 조정과 선 소실을 구분|[기록] 같은 시드 조합2.80→1.96. 음수 prompt+양수UC 묶음 근거이며 개별 효능 아님|

**[실측] 193항목·12묶음**을 만들었다. `candidate` 180, `research_hold` 7, `alias_hidden` 6. **193개를 모두 효과 검증했다는 뜻이 아니다.** 단일 어휘 192개 중 별칭 합치기 및 빠진 canonical 대상으로 관찰 집합은 189개이며, 추가 1항목은 밝기 묶음이다. priority1은20, priority2는78, priority3은95개다. 효과 있는 항목/제품 승인 수가 아니라 연구 순서다.

## 2. 범위·자료·빈도의 뜻

인계 문서 전체와 지정 개발 기준, 두 조사 기록, mood_bench README, 현행 `RULES`, 스타일 목록, Interactive 축, 빈도표, active 별칭 스냅샷을 읽었다. 화면·서버·생성·인스펙터 규칙 구현은 하지 않았다. 외부 데이터셋 원본이나 Portable 파일은 열지 않았다. manifest의 원본 경로 문자열은 **출처 기록만** 읽고, 그 경로를 따라가지 않았다. 그림 재측정도 하지 않았으며 기존 measurement JSONL을 분석했다.

### 2.1 자료 대조

|자료|이번 사용·근거|
|---|---|
|`data/taglist/style_meta_tags.json`|[실측] 11분류375태그 전 항목에 판정 행 부여 → `thumb_audit.csv`|
|`data/interactive_axis_tags.json`|[실측] skin32개 전 항목 대조 → `skin_axis_audit.csv`; catalog에는9개, 피부색/노출 경계/털·비늘 등23개는 별도 내용 선택기로 유보|
|`data/danbooru_tag_counts_by_rating.json`|[실측] 2026-09-24 생성된175샤드9,127,780게시물의 **자동완성 sparse index**, g/s/q/e 합계. 성인 등급 제외 없음|
|`data/danbooru_tag_snapshot/{tags,tag_aliases}.parquet`|[실측] 2026-04-08 준비본. category와deprecated, `status == active`만 별칭 채택. 사이트 post_count는 별도 모집단|
|`reference_prompts.jsonl` + `reference_measurements.jsonl`|[실측] 4,054줄 path/file/크기 일치·path 중복 없음·측정 오류 없음; 같은 줄 조인|
|`core/image_tone_reference.py`, `image_tone_advisor.py`|[실측] 현행 축/표준/편집 규칙 읽기만; 동작 변경 없음|
|`docs/mood_bench/raw_levers/manifest.json`|[기록] UC 바탕과 원래 조건을 대조. 누락된 단독 효과를 임의로 채우지 않음|
|`core/headless_memo_service.py:61-99`|[기록] V5 전용 어휘·공식 UC라고 기록된 문구. `depthness`가 DOF 상위 버전이라는 물음표 메모는 사실로 채택하지 않음|

**빈도 해석:** `corpus_count = null`은 **미색인/미집계**, 0건 확정이 아니다. 품질 어휘의 코퍼스0건은 앞선 조사 §1의 직접 집계 **[기록]**으로만 참조했다. 이번 작업에서 원본175샤드를 다시 세지는 않았다. `masterpiece`의 동명 작가 레코드 같은 이름 충돌은 NAI 품질 조건과 분리했다. bundle은 합집합 빈도를 안 셌으므로 null+`per_tag_corpus_count`다. 빈도가 크다고 손잡이 효과·안정성이 큰 것은 아니다.

### 2.2 Thumb 375개를 어떻게 처리했나

**[실측]** catalog에 포함된 원문84개(보류/별칭도 포함), 작가/프랜차이즈133+시대풍9=142개는 Tuner 밖, 도구/매체·전면 화풍·내용 전환142개는 고급 선택으로 유보, 별칭/폐기 추가 검토7개. 합계375. 단순 폐기가 아니라 항목별 이유를 CSV에 남겼다. ‘그림을 개선’과 ‘다른 양식을 선택’은 다른 요청이다.

**[실측]** Thumb 밖의 보완: complexity/depthness/연도2020~2026, 색 테마 여러 종, 자연어 조명, 피부·신체 표면32항목, 얼굴9항목, 내용 공변 관찰용 시간·날씨10항목. 피부 그룹32개와 Interactive skin32개는 **같은 집합이 아니다**. 성인 체액·신체 표현은 남겼고 `adult_only`를 붙였다. 미성년의 성적 내용에 관한 후보·검증 recipe는 만들지 않았다.

### 2.3 실체·별칭·충돌

**[실측]** Danbooru 일반131·메타10·active 별칭6, NAI 전용25, 자연어/미확인 표현21항목. 이 중 일반1개는 밝기 묶음이다. NAI/자연어는 빈도 순위에 섞지 않았고 아래에서 별도 열거한다. ‘자연어’ 표기는 zero-count 이름 레코드가 있더라도 학습 태그 실체가 확인되지 않았다는 보수적 분류를 포함한다.

|관계|판정|
|---|---|
|`pale colors` → `pale color`|[실측] active 별칭. 중복 다이얼 금지|
|`cel shading (2d)` → `anime coloring`|[실측] active 별칭. **bare `cel shading`은 deprecated이고 활성 치환 관계를 확인 못함**; 이름 유사성만으로 합치지 않음|
|`muscle` → `muscular`|[실측] active 별칭. 근육 체형은 국소 질감과 다름|
|`water drops` → `water drop`|[실측] active 별칭. 원문은 hidden 연결용; canonical 후보를 별도 승인해야 함|
|`translucent skin` → `see-through body`|[실측] active 별칭. 전신 내용 변형 위험; 피부의 약한 투과 다이얼로 승인하지 않음|
|`erect nipples` → `covered nipples`|[실측] active 별칭. 옷 아래 형태를 뜻하는 canonical과 노출된 피부 표면을 혼동하지 않음; hidden으로 보류|
|`oil`, `shiny hair`, `areolae`, `text`|[실측] snapshot deprecated; 관측 빈도가 있어도 자동 기본 후보로 승인하지 않음|
|`screentone` ↔ `screentones`|[실측] active 별칭 없음. 단수는 공식 UC **메모의 문구**, 복수는 실제 Danbooru 표현. 모델 효능은 별도|
|`flat color` ↔ `depthness`/광택, `no lineart` ↔ 선 계열|[지식/추정] 의미상 충돌. 강도·덧셈·네거티브 반전은 V5 미검증|
|`grey theme`, `high contrast`의 양쪽 공존|[기록] 기존 반대 칸 경고 대상. 단순히 가중치 두 값을 빼서 상쇄했다고 표시하면 안 됨|
|`film grain`, `chromatic aberration`, `halftone`, `dithering`|[기록] Heavy/Human focus UC에 있음. 포지티브 시험 전 **실제로 남아 있는 UC**를 확인. 한 칸만 바꾸는 조건을 사전에 정의|

영점에 있는 어휘는 `in_zero_preset`과 실제 부호의 `zero_preset_weights`로 기록했다. 예: `high complexity`1, `low complexity`−0.25, `detailed background`−0.25, `ultra complexity`0.15, year2024·masterpiece·very aesthetic·high-quality digital art·no text·depthness1. prefix의 artist collaboration−1·countershade0.75는 패널 항목으로 자동 추가하지 않았지만 상태 파싱 연구에는 포함했다.

## 3. §5.2 관찰 연구 — 실제 실행 결과

### 3.1 표본 자체의 주의점

**[실측]** 4,054장의 seed는 전부 고유하다. 같은 시드 처치/무처치 짝은 없다. 작가는 **2,325명**이며, 714명은1장, 1,525명은2장, 74명은3장, 8명은4장, 나머지4명은5/6/7/18장이다. 따라서 인계 문서의 ‘작가는 그림마다 다르므로 교란이 아니다’는 해석은 채택하지 않았다. **작가 배정·반복도 교란 가능성**이다. 작가별 품질 판정·프로필은 만들지 않고 통계적 차감만 했다.

**[실측]** 해상도도 전부832×1216은 아니다. 4,025장만 해당하며 29장은1024×1024(13),1216×832(4),1152×896(3),960×1088(3),1088×960(3),896×1152(2),1536×1024(1)이다. 마지막1장은1280×853으로 분석됐다. steps23·scale6.7·sampler `k_euler_ancestral`은 동일. sampler의 noise schedule/모델ID는 이 JSONL 필드에 없으므로 전송 조건 동일성까지 증명하지 못한다. 본표는4054장 모두, 별도 동일 크기 민감도는4025장이다.

**[실측]** 기본 스타일 조건 대부분은 상수다. masterpiece·very aesthetic·high-quality digital art·high complexity·ultra complexity·no text·depthness는4054장 모두 positive prompt에 있다. low complexity/detailed background는 **음수 언급**이라 positive-presence에는 안 잡힌다. `year 2024`3834장, `year 2025`220장은 작가 내 변동이0이라 연도 효과를 분리 못한다. UC의 lowres·bad anatomy·artistic error·film grain 등도 사실상 상수여서 **UC 효과를 이 표본으로 검증할 수 없다**. 원문의 일부 UC 희소 추가 표현은 n=1이라 역시 비교 불가다.

### 3.2 분석 방법·산출 표

1. 숫자 `w::… ::` 중첩 묶음의 유효 가중치를 파싱하고 underscore/공백을 정규화했다. `0`과음수는 삭제/부재로 간주하지 않았다. active 별칭만 canonical로 합쳤다. 정확한 태그 단위 대조라 substring 매칭은 쓰지 않았다. 이 표본에는 brace/bracket 가중치가0건; 파서는 해당 문법을 조용히 무시하지 않고 오류로 막는다.
2. prompt와UC를 따로 비교했다. **해당 칸에0/음수 언급이 있는 표본, 반대 칸에 동일 개념이 양수로 있는 표본**은 그 비교에서 제외하고 제외 수를 남겼다. 같은 태그의0가중치를 무처치군에 섞지 않았다.
3. 189개 canonical후보 ×2칸 ×18지표 = **6,804행**. ‘있음’/‘없음’이 각각2장 이상인 행은610개, 태그는34개(자리 모두 prompt). 이건 성공 수가 아니라 **통계를 낼 수 있는 비교 수**다. 보정 p값은574행, 있음/없음20장 이상+변동 작가10명 이상인 기술 분석 행은266개다.
4. 원시 평균/중앙값 차이·표본 전체SD로 나눈 차이·Welch95%CI를 냈다. WelchCI는 작가 반복을 무시한 탐색용이다. 작가 고정효과(작가 내 평균 차감), 이어서32개 동반 태그의 FWL 잔차 비교로 민감도를 봤다. CI는작가 cluster CR1+t근사이며 sparse태그의 정밀도 보장은 없다. 단일 노출이 있는 작가가 적을수록 CI를 특히 경계한다.
5. 32개 controls는 백색/단순/그라데이션/흐린배경, 실내외·낮밤·일몰·하늘, shot·인원, 피부색·sweat/wet, 머리/옷색이다. 표본에서 상수인 열은SVD rank로 제거했다. **잔여 교란은 여전히 크다**: blush·steam·wet clothes·water·thighhighs 등은 이 control set 밖이다. 또 일부 통제는 매개변수일 수 있다. 따라서 보정 결과도 인과 효과가 아니다.
6. 모든 추정 가능한 tag-slot-axis검정에 BH q를 따로 계산했다(원시610, 보정574개). ‘q<.05’는 기술적 연관 신호이며 생성 효과 승인선이 아니다. 방향·빈도·교란 정보를 보고 **새 생성 검증 순서**를 고르는 데만 쓴다.
7. 선 굵기는 `width_reliable == false`인 **900장**을 해당 축에서만 제외했다(3154장 남음). 나머지18지표의 결측은0이다. 선 소실 때 정상 굵기처럼 보이는 문제 때문에 굵기 하나만 성공으로 판정하지 않는다.

전체값·원시95%CI·중앙값·가중치·제외 수·보정CI·q는 [observational_effects.csv](tone_tuner_2026_10_04/observational_effects.csv), 동반 태그는 [co_tags.json](tone_tuner_2026_10_04/co_tags.json), 분모·조건·해시는 [observational_summary.json](tone_tuner_2026_10_04/observational_summary.json)에 있다. 행/표본 수를 ‘검증된 손잡이 수’로 읽지 않는다.

### 3.3 대표 결과 [실측—관찰]

차이는 **태그 있음 − 없음**, 단위는 해당 인스펙터 출력값이다. 보정CI는 작가+동반 태그 보정이며 해상도에 대한 본표 보정은 없다(§3.5 동일 크기 재분석으로 확인). ‘변동 작가’는 같은 작가 안에서 노출이 바뀐 작가 수다.

__OBS_TABLE__

**읽을 결론:**

- `night`의 밝기 연관은 원시−18.04, 작가 내−21.03, 동반태그 보정−19.00으로 유지된다. **어둡게 하는 장면 조건** 후보이지 같은 그림의 노출 손잡이로 승인된 것이 아니다. 밤·달·야외 내용이 공변한다.
- `indoors` 밝기, `outdoors` 채도 연관도 남는다. 반면 `day`는 원시 밝기−0.79, `sunlight`는−1.45라 **태그 이름만 보고 전역 밝기 상승이라고 주장할 수 없다**. 흰 무처치 배경이 비교군일 수 있다.
- `wet`의grain원시+0.298→작가내+0.145→보정+0.095, CI에0이 있다. 물/옷/배경 영향과 구별하지 못했다. `sweat`의grain은 원시−0.018·보정−0.047로, 땀이 전역 거칠기를 올린다는 증거가 아니다. **기존 grain은 피부 디테일의 대리지표로 부적합**하다.
- `skindentation` sharpness는 원시−14.45→작가내+10.22로 부호가 바뀐다. 억제하면 더 선명해진다고 읽으면 안 된다. thighhighs·의복·작가 배정이 섞여 있다.
- `tanlines` 채도원시+5.96, 보정+4.66이나 BH q=.192다. 색 차이의 내용 조건이지 피부색 품질 서열·인과 손잡이는 아니다.
- `depth of field`는 전역sharpness하락과 연관되지만 눈/얼굴 세밀함 악화를 뜻하지 않는다. 배경의 흐림만 증가해도 전체값이 낮아진다. backlighting10건/bloom3건은 sparse라 방향을 확정하지 않는다.

### 3.4 피부와 핵심 스타일의 표본 빈도·교란 [실측]

|태그|positive prompt 노출|해석|
|---|---:|---|
|`shiny skin`, `oiled`, `silky skin`, `detailed skin texture`|각0|모델 효과 검증 불가. 필터 때문에 빠졌을 가능성을 효과 없음으로 읽지 않음|
|`tan`, `pale skin`, `dark skin`, `freckles`|각0|Interactive에 있어도 이 분석에 변동이 없으면 추정 불가|
|`sweat`, `sweatdrop`, `wet`|257 /122 /86|국소 액체/표정 기호/젖은 내용 구분 필요|
|`skindentation`, `tanlines`, `veins`, `muscular`|55 /37 /5 /1|veins·근육은 너무 적음; 피부 표면과 형태를 분리|
|`grey theme`, `flat color`, `blending`, `high contrast`|각0|기존 같은 시드 기록을 참고할 뿐 관찰 표본에서 검증 불가|
|`backlighting`, `sunlight`, `bloom`, `depth of field`|10 /28 /3 /39|조명·초점·내용 공변 후보|
|`film grain`, `chromatic aberration`|prompt3 /6, UC각4054|양쪽 충돌 표본을 제외하면 single-slot무처치 비교 없음|

동반 태그 비율(노출군 대 비노출군): sweat–blush72.8% vs40.0%, sweat–steam16.3% vs0.26%; wet–swimsuit53.5% vs26.0%, wet–water25.6% vs2.0%; skindentation–thighhighs67.3% vs16.4%; night–outdoors57.1% vs5.8%; sunlight–window35.7% vs1.2%. **어떤 태그가 같이 들어 있다는 관찰은 태그 관계의 의미 승인·몸의 소유자·작용 방향 증명이 아니다.** 높은 raw차만으로 보정카드를 만들지 않는다.

밝기↔테두리밝기의 Pearson상관 **0.94842469**를 재확인했다. 테두리는 실제 배경 mask가 아니므로 ‘밝기는 무조건 배경’으로 일반화하지 않지만 이 표본에서는 배경 배치의 영향이 큰 것은 확인된다.

### 3.5 해상도 민감도 [실측]

832×1216의4025장만 따로 동일 분석을 실행했다. 선 굵기 불신뢰886장. 새 이미지 생성·재측정이 아니라 같은 기록의 부분집합이다.

|태그 / 축|4054장 보정 차|4025장 보정 차 [95%CI]|
|---|---:|---|
|night / 밝기|−19.00|−19.02 [−26.48, −11.56]|
|indoors / 밝기|−4.83|−4.82 [−7.56, −2.08]|
|outdoors / 채도|+3.61|+3.63 [+1.51, +5.75]|
|sweat /grain|−0.047|−0.043 [−0.120, +0.034]|
|wet /grain|+0.095|+0.086 [−0.067, +0.238]|
|skindentation /sharpness|+5.80|+5.76 [−33.91, +45.42]|

이 대표 결론은29장 제거로 크게 바뀌지 않았다. 다만 초점/해상도/ROI/묘사 밀도의 전체 교란이 없어졌다는 뜻은 아니다. 전체행은 [size_sensitivity_effects.csv](tone_tuner_2026_10_04/size_sensitivity_effects.csv), 크기 분모는 [size_sensitivity_summary.json](tone_tuner_2026_10_04/size_sensitivity_summary.json)에 있다.

## 4. 지표의 구멍 — 가벼운 단일 그림 지표 제안

**[추정·미구현]** 피부·얼굴·눈·배경은 **사용자 수동ROI/다각형**을 먼저 받아야 한다. 중앙 사각형=인물, skin색 threshold=피부라는 가정은 어두운 피부·조명·의상·배경에서 속는다. ML 없이 자동으로 모든 그림의 피부/눈을 찾는다고 약속하지 않는다. ROI를 같은 시드 전후에도 그대로 쓰면 위치가 달라진 그림에서 틀리므로 사람이 재확인한다.

|측정안|가벼운 계산 / 무엇을 재나|속는 그림 / 같이 볼 것|
|---|---|---|
|피부 반사 면적·크기|피부ROI의 L*상위 분위+주변 대비로 밝은 blob 면적/개수/등가반경. 절대·상대 threshold 둘 다 보고, 클리핑 비율 별도|흰 피부·역광·물방울·의상·얼룩이 광택으로 잡힘. 밝은 픽셀≠기름 피부. 하이라이트 지속적 경계와 사람 판독 필요|
|피부 미세결 다중척도|ROI에서 강한 선/물방울 경계를 제외한 고주파 MAD·σ1/2/4 DoG 에너지, smooth영역 대비|JPEG·grain·해칭·주근깨·머리카락을 모공으로 오인. ‘많을수록 좋다’ 점수로 쓰지 않음|
|피부 광택 폭·국소 경사|밝은 반사blob에 직교 단면을 놓아 폭/명암 falloff·주변 중간톤 비율|그림의 스타일마다 물성이 다름. flat cel하이라이트를 실제 거칠기/매끈함으로 번역할 수 없음|
|눈/홍채 구조 밀도|수동 눈ROI를 해상도 정규화, edge density·방향 분포·반사blob 수·구역별 엔트로피|속눈썹·반사·잡음만 늘어도 디테일처럼 보임. 눈 정체성·동공 정오·미감은 못 잼|
|머리/입술 반사|각ROI의 밝은밴드 폭/연속성, HSV/Lab국소대비|염색 streak·흰 머리·그림체의 띠를 광택으로 오인. shiny hair deprecated어휘 효능과 별개|
|배경 밀도|배경ROI의 edge점유·연결성분 수·multiscaleentropy, 큰 균일영역 면적과 함께|글자·체커·복잡한 노이즈도 점수가 높음. detailed background의 좋은 묘사로 단정 못함|
|인물-배경 분리|수동 두ROI의 L*/chroma중앙값 차, 경계 양쪽의 국소 대비; 명암 블록 상관 별도|검은 의상·배경 변색만으로 상승. depthness/ultra의 실제 입체감과 같지 않음|
|색수차/그레인/블록흔적|RGB경계 위치 차, 평탄ROI 잔차의 isotropy, 8px격자 불연속·계조run 분포|색 선화/망점/디더링/원본PNG에도 모델이 그린 가짜JPEG흔적. 자동UC승인·파일압축 판정 불가|
|해부·손·추가손가락·문자|**현재 픽셀 지표 없음**. 사람 체크리스트/수동 count. ML없다는 조건이면 완전 자동 판정 안 함|전역sharpness·grain으로 해부 정오·문자 여부를 판정하지 않음|

관측값은 한 장에서 낼 수 있지만 **태그가 바꿨다는 판단은 처치 전후 쌍**이 필요하다. ROI크기/해상도/threshold/제외 규칙을 로그에 남기고 같은 척도에서만 비교한다. 구도 유지의 L*32px블록 상관은 의미·정체성 보존이나 같은 손의 유지 점수가 아니다.

## 5. 실제 생성 검증 줄 — Claude의 사용자 연구 세션용, 이번에는 실행 안 함

**[추정·계획]** 우선 기초 계약: 최종 prefix/content/postfix/UC·캐릭터 캡션·모델ID·해상도·분석크기·seed·steps·CFG/rescale·sampler/noise schedule·기존UC·바뀐 한 조건을manifest에 고정한다. 영점 프리셋·구도A·832×1216·23steps. 해부/피부 시험은 **명확한 성인 인물**만 사용한다. 성인/국소 표면이 구도A의 의복에 가려지면 고정된 별도 성인 구도B로 시험하고 A결과와 합치지 않는다.

**한 손잡이 = 12~20장:** 3작가×2seed×(baseline+조건1)=12장, 약/강2조건까지는18장. 2작가×2seed×4조건=16장. 밝기 분해는2작가×2seed×(baseline+단독3+묶음)=20장. 조건을 달리한 기존그림을 baseline처럼 쓰지 않는다. 공유baseline을 저장해도 독립쌍처럼 중복 집계하지 않는다.

아래 성공 방향은 **미리 정할 가설**이다. 방향 일치쌍 수/전체쌍·중앙 크기·범위·반대 결과·부작용을 모두 보고한다. 유지0.9는 참고 목표이지 보편 통과선이 아니다(기록의 남남상관 중앙0.47,최대0.73). 태그 이름이 맞는 쪽으로 움직여도 사람 판독·내용 유지가 실패하면 ‘개선 승인’하지 않는다.

|순서 / 시험|붙일 자리·조건 한 줄|겨눌 성공 방향 / 반드시 함께 보기|
|---|---|---|
|0 기존 recipe 비교 기준|UC grey theme1 / UC high contrast1을 각각 독립12장으로 재현|채도↑/또렷함↓. 기존기록 범위와 전후차/구도 유지 비교; **새 손잡이 발견 수에 넣지 않음**|
|1 피부 광택|prompt shiny skin0.5/1,18장. 반대칸 동일개념은 시작조건에서 정리|피부ROI의 반사비율/분포↑, 형태·피부색·옷 유지. sharpness증가만으로 성공 판정 금지|
|2 오일 vs 젖음 vs 땀|prompt oiled /wet /sweat를 **각각 한 조건**으로16장(공유baseline)|액체/반사ROI변화·눈 판독. 배경수면/옷투명도/성인내용 추가를 부작용으로 별도 기재|
|3 평면 채색 억제|UC flat color0.5/1,18장|음영분포·반사/인물배경 분리↑가설, 채도·grain·선·구도 함께. prompt음수 경로는 이후 별도|
|4 면/빛 번짐 분리|UC blending 또는UC bloom을 각각12장|국소경계/halo감소, 명도·광택·눈 세밀함 유지. 2개를 동시에 붙이지 않음|
|5 피부 상세 자연어|prompt detailed skin texture0.5/1,18장|피부ROI중간척도 묘사 변화+사람의 개선판독. 잡음/주름/모공 추가는 자동성공 아님|
|6 눈 상세 자연어|prompt detailed eyes0.5/1,18장|눈ROI구조밀도·홍채/반사 자연스러움↑, 눈형태/동공정오 유지|
|7 밝기 묶음 분해|UC black theme /dark /muted color /세 묶음,20장|밝기↑·배경/의상 변경 최소. **각 단독이 기여했는지**와 묶음효과를 분리|
|8 선 드러내기 분해|prompt jaggy lines2 /UC no lineart1 /둘의recipe,16장|선 대비↑, 폭·grain과 구도 유지. 기존 사용자묶음에서 단독효과를 분리|
|9 굵은 선 분해|prompt −1/−2::thick outlines와 UC양수 단독을 분리,2작가×2seed×4조건16장|width↓이면서 line_contrast가 무너지지 않음. 선 소실/10px이상 폭 측정불신뢰를 실패·보류로 보고|
|10 배경 초점|prompt blurry background0.5/1 또는DOF를 각각18장|배경ROI고주파↓, 눈/얼굴ROI또렷함 유지. 전역sharpness↓ 자체를 열화로 판정 금지|
|11 색/조명 장면형|prompt night /sunlight /backlighting를 각각12장|관찰방향이 개입에서도 재현되는지·장면 재구성 정도; 로컬보정 손잡이로 자동 승격 금지|
|12 오류 억제|UC bad hands 또는extra digits를 각각12장|사람 판독의 형태 오류빈도↓, 손 내용·포즈/정체성 유지. 전역지표는 성공조건 아님|

그 밖의 각 항목도 catalog의 `test_recipe`에 자리·가중치·겨눈축/국소ROI/사람판독을 남겼다. 미검증항목은 포지티브·UC **각각 독립 검증**한다. 음수prompt는 기존기록이 있는high/ultra/low complexity·thick outlines와추정simple illustration만 기록했고, 네거티브에음수는 어떤 실험안에도 넣지 않았다. low complexity−0.5의붕괴기록은 안전 경고이며 ‘그 이하 세기를 더 시험하자’는 제안이 아니다.

## 6. 카탈로그 스키마와 구현 전 결정

§6 필수 필드는 유지하고 top-level `{schema, groups, count_scope, source_sha256, policies, items}`로 감쌌다. JSONL이 아니라 JSON배열을items에 담았다. 항목193개 모두kind/evidence enum·priority·가중치 부호·연도 하한 검사를 통과했다. **타입/모양 검사이지 의미효능 검사 아님**.

- 추가: `corpus_count_status`, `canonical_corpus_count`, `snapshot`, `thumb_member`, `interactive_axes`로 빈도·실체·학습효능을 분리.
- 추가: `default_slot`, `control_type`, `status`, `adult_only`, `warnings`, `test_recipe`로 슬롯기반/배타형/비선형/보류/성인 내용 구분.
- `slots`마다 `evidence_level`, `validation`, `range_status`를 붙였다. 이전생성기록은recorded이고, 이번관찰은별도의 `observation.evidence_level=measured`, **association_only**다. 전역evidence만 읽어 UC역효과가 검증됐다고 해석하지 않는다.
- `slots`에 없는 경로는 **효과 미검증·범위 제안 안 함**이라는 뜻이다. 특히 대부분의 프롬프트 음수 경로는 네거티브와 동치라는 근거가 없어 제안하지 않았다. 효과가 없다는 뜻이 아니다(`policies.unlisted_slots`).
- `axis_hint`에slot추가. 슬롯에따라반대 방향이면`slot_dependent`다. 피부는전신sharpness를억지로연결하지않고`measurable=none`, ROI구멍을기재. 지표가있어도`partial`이지좋음/나쁨점수아님.
- `in_zero_preset` 외에원래가중치목록/UC바탕/공식UC메모를각각기록. **프리셋이태그를이미넣어뒀다면추가보다가중치수정**, 중복상태는확인후반영.
- 별칭은hidden매핑레코드이며독립항목으로켜지않는다. aliascanonical이초안에없다면그대상을별도승인해야한다. 대조편의를위해기록을남겼지전부노출승인한것은아니다.
- 이번 범위의`danbooru_general`/meta는로컬이름/빈도/스냅샷대조다. deprecated나0countname은효능보장불가. 외부공식문서·위키정의의최신확인은미실시.

## 7. 묶음별 전체 후보 표

다음 전체표는193항목의축소보기다. **빈도순랭킹이아니며**, kind별구분을유지한다. 가중치·다른자리·충돌·별칭·관찰분모·근거출처의완전한값은catalog JSON이정본초안이다. ‘UC기본자리’항목의포지티브설명은열화/내용표현자체를설명할뿐포지티브사용권장이아니다.

### 별도로 두는 NAI 전용 25항목 [기록]

__NAI_LIST__

### 별도로 두는 자연어·미확인 21항목 [추정]

__NL_LIST__

이전조사의raw코퍼스0건기록이있어도이번sparse미색인값을0으로변환하지않았다. `top aesthetic`은Thumb에만있고V5지원확인부족, `shiny hair`/`text`/`detailed background`는deprecated/0count상태도함께기록했다.

__GROUP_TABLES__

## 8. 범위 안에서 발견한 별도 문제: 숫자로 끝난 작가명 파싱

**[실측]** `core/image_tone_advisor.py:104,157-170`의정규식/토큰화는다음입력에서95를새가중치로읽는다.

```text
1.15::artist:anam95 ::, 0.75::solo ::, high complexity
기대: artist:anam95=1.15, solo=0.75, high complexity=1
현재 advisor: artist:anam=1.15, solo=81.9375, high complexity=109.25; 열린묶음2
```

관찰prompt의 **481/4054장**에숫자로끝난artist닫힘형태가있었다(모든481장의제품동작전체를검증했다는뜻아님). 이조사의파서는해당닫힘을tag일부로인식하는별도경계검사를썼고, 숫자작가3형태/중첩/부호/열린묶음검사시험을남겼다. 코어는그대로다.

**제안:** Claude가별도좁은수정승인을받아숫자접미작가·숫자연도·칸간묶음·중첩그룹·원문편집비회귀를시험한다. 이번결과는 **advisor의상태파서재현**이며실제NAI인코더·생성페이로드가똑같이오염됐다는증거는아니다.

## 9. 실행·검증·재현 명령

PowerShell5.1, 저장소루트. UTF-8·newlineLF·create-only출력. `PYTHONDONTWRITEBYTECODE=1`로core/data캐시쓰기를피한다. 설치/외부호출없음. Python/라이브러리버전: **__VERSIONS__**.

실제로실행한분석(최초출력경로; 이미파일이있으므로재실행은아래fresh경로사용):

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:OPENBLAS_NUM_THREADS='1'
venv\Scripts\python.exe -X utf8 tools\research_tone_tuner_20261004.py
venv\Scripts\python.exe -X utf8 tools\research_tone_tuner_size_sensitivity_20261004.py
venv\Scripts\python.exe -X utf8 tools\write_tone_tuner_report_20261004.py
```

수치재현(기존산출물덮어쓰기없음):

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:OPENBLAS_NUM_THREADS='1'
$out='docs/tone_tuner_2026_10_04/repro_'+(Get-Date -Format 'yyyyMMdd_HHmmss')
venv\Scripts\python.exe -X utf8 tools\research_tone_tuner_20261004.py --out $out
venv\Scripts\python.exe -X utf8 tools\research_tone_tuner_size_sensitivity_20261004.py --out $out
```

**같은 입력 source SHA에서 본표 4054장/2325작가/추정 610행/보정 574행, 동일 크기 4025장/제외 29장을 summary로 대조**한다. 수치 재현은 품질 효능 재현이 아니다. 13개 입력 파일 SHA-256은 catalog/summary에 저장했다. 이 기준 표본 핵심 둘의 SHA:

```text
reference_prompts.jsonl      1cfda95ec07f4616f0a9d0c06b0ecafab706775f7e009d508b51078147555a60
reference_measurements.jsonl 30a541fb001e347a830dd5b56d68afecd049315c0740ae4a1efc60fd41228d60
```

파서재현(읽기전용·파일출력없음)과focused시험:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
venv\Scripts\python.exe -X utf8 tools\research_tone_tuner_20261004.py --diagnose-advisor
venv\Scripts\python.exe -X utf8 -m pytest tests\test_tone_tuner_research_20261004.py -q -p no:cacheprovider --basetemp .codex_tmp\pt
```

**[실측] 20 passed**. weightedparser/부호/중첩/숫자artist/별칭cycle/null빈도/BH/작가차감/조인실패/출력경계/create-only/schema/통계행합계/동일크기subset/원천hash를검사했다. 앱회귀전체·실제생성·UI/무료구간조건을시험했다는뜻아님.

## 10. 만든 파일 전부·불변경·열린 질문

### 만든 파일

- `docs/TONE_TUNER_TAG_RESEARCH_2026_10_04.md`
- `docs/tone_tuner_2026_10_04/catalog_draft.json`
- `docs/tone_tuner_2026_10_04/observational_effects.csv`
- `docs/tone_tuner_2026_10_04/co_tags.json`
- `docs/tone_tuner_2026_10_04/observational_summary.json`
- `docs/tone_tuner_2026_10_04/thumb_audit.csv`
- `docs/tone_tuner_2026_10_04/skin_axis_audit.csv`
- `docs/tone_tuner_2026_10_04/group_tables.md`
- `docs/tone_tuner_2026_10_04/size_sensitivity_effects.csv`
- `docs/tone_tuner_2026_10_04/size_sensitivity_summary.json`
- `tools/research_tone_tuner_20261004.py`
- `tools/research_tone_tuner_size_sensitivity_20261004.py`
- `tools/write_tone_tuner_report_20261004.py`
- `tests/test_tone_tuner_research_20261004.py`

기존파일변경·git쓰기·이미지생성·네트워크·Portable접근없음. 다른세션의기존dirty목록은건드리지않았다. pytest용`.codex_tmp/pt`만scratch로사용했으며감독자가`.codex_tmp`를정리한다. 데이터표본/그림복사·서버/프로세스실행·패키지설치없음.

### 사용자/Claude가 정할 것

1. **패널기본모델:** 자리선택+가중치/연도배타선택/비선형recipe/혼합상태분리를수용하는가? 태그원문소유·중복·양쪽공존·캐릭터칸·되돌리기계약은어디까지인가?
2. **숫자artist파서:** 별도코어수정승인및focused비회귀시험을먼저할지. 이조사에서수정하지않았다.
3. **국소ROI:** 수동ROI를최초검증규격에넣을지, 사람판독만으로시작할지. 자동피부검출을전제하지않는다.
4. **‘개선’의성공판정:** 피부색/체형/주름/성인체액등내용선택과미감·표면개선을어떻게분리할지. 전역지표의0점근접을품질정답으로쓰지않는다.
5. **최초생성예산:** 위1~6의피부·음영·자연어묶음부터갈지, 이미효과가있는recipe 재현부터갈지. 각12~20장이지193항목전수실험의승인이아니다.
6. **기본노출범위:** 후보180개전체가아니라먼저검증된소수만보일지,고급/연구탭에나머지를둘지. hidden별칭canonical의추가·deprecated표현·미색인자연어는별도승인.
7. **외부정의확인:** 다른허용된연구세션에서NAI V5최신공식어휘/UC·Danbooru위키를검증할지. 이번로컬기록은최신웹검증아님.

**마무리:** §3의모델이견을맨앞에썼고, §5.2는4054장전부를실제분석했다. 193항목의초안과원시/보정/크기민감도표를남겼다. 생성효능은기존기록과새관찰을구분했고, 새생성으로증명하지않았다.
"""
    report = report.replace("__OBS_TABLE__", observation_table(rows))
    report = report.replace("__NAI_LIST__", ", ".join(f"`{t}`" for t in nai))
    report = report.replace("__NL_LIST__", ", ".join(f"`{t}`" for t in nl))
    report = report.replace("__VERSIONS__", f"Python {platform.python_version()}, numpy {numpy.__version__}, scipy {scipy.__version__}, pyarrow {pyarrow.__version__}")
    grouped = (OUT / "group_tables.md").read_text(encoding="utf-8")
    grouped = grouped.replace("# 묶음별 전체 후보 표", "### 전체 표").replace("\n## ", "\n### ")
    report = report.replace("__GROUP_TABLES__", grouped)
    # Verify this report is grounded in the intended artifacts before any write.
    assert summary["n_pairs"] == 4054 and summary["catalog_items"] == 193
    assert subset["n_pairs"] == 4025
    assert len(rows) == 6804
    assert "__OBS_TABLE__" not in report
    with REPORT.open("x", encoding="utf-8", newline="\n") as f:
        f.write(report)
    print("CREATED", REPORT.relative_to(ROOT))


if __name__ == "__main__":
    main()
