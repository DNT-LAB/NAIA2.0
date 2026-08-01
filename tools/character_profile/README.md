# 캐릭터 프로필 빌더 (이식본, 후속 작업용)

`data/copyright_groups.json`(1.3MB)과 `data/character_analysis.json`(28.5MB)을 만드는
스크립트 묶음. **원본은 `C:\VNR\NAIA2.0\.experimental\` 이고 2026-07-30 에 그대로 복사했다.**
이 리포에서 아직 실행한 적 없다 — 후속 작업 재료로 가져온 것이다.

## 왜 가져왔나

캐릭터 뷰어의 데이터가 어떻게 만들어졌는지 이 리포 안에서는 추적이 불가능했다.
`tools/` 에는 검증용(`audit_tag_assets.py` 등)만 있어서, 산출물에서 역추론할 수밖에 없었다.
프리셋을 만들려면 재생성 경로를 손에 쥐고 있어야 한다.

## 파이프라인

`rebuild_pipeline.py` 가 오케스트레이터다(`build_from_new_data.py` 의 step 5+6 추출본).

    입력  .experimental/tag_classifier_project/1girl_solo_filtered.parquet  (295MB)
          .experimental/tag_classifier_project/1girl_char_frequency.json    (3.6MB)
    출력  data/copyright_groups.json
          data/character_analysis.json

**입력 두 개는 이 리포에 없다.** `C:\VNR\NAIA2.0\.experimental\tag_classifier_project\`
에 있고, 295MB 라 옮기지 않았다. 돌리려면 경로를 맞추거나 그쪽에서 실행해야 한다.

나머지는 보조다:

| 파일 | 역할 |
|---|---|
| `rebuild_copyright_groups.py` | parquet 의 실제 copyright 분포로 그룹 재구축 |
| `populate_copyright_groups.py` | 그룹에 캐릭터 명단 채우기 |
| `analyze_characters.py` | 캐릭터별 태그 통계(색·특징·성별) 산출 |
| `add_breast_size.py` · `add_alternate_costumes.py` | 필드 추가 |
| `resolve_multi_characters.py` | 다중 캐릭터 행 정리 |
| `rebuild_from_output_parts.py` | 분할 산출물 병합 |

## 알려진 한계 — **남성 데이터가 없다**

이건 버그가 아니라 설계다. 코드가 명시한다:

    populate_copyright_groups.py:3   "1girl+solo 데이터셋이므로 모든 캐릭터는 girl로 분류."
    populate_copyright_groups.py:83  "# boy는 빈 배열 유지"
    rebuild_copyright_groups.py:164  groups[gk] = {"girl": girl_list, "boy": []}

`analyze_characters.py:179` 의 `analysis["gender"] = gender` 는 판정이 아니라 **캐릭터가
어느 통에 있었는지를 복사**한다. 통이 girl 하나뿐이라 9,738명 전원이 `gender: "girl"` 이다.

### 그 부작용 (2026-07-30 실측)

남성 캐릭터 **이름**은 목록에 들어와 있다 — `1girl solo` 그림에 그 태그가 붙은 것
(젠더벤드·2차창작)이 캐릭터로 승격됐기 때문이다. 그래서 값이 틀린다:

    zhongli (genshin impact)  gender=girl  breast_size 분포에 large breasts 31.4%
    kaeya (genshin impact)    gender=girl  characteristics 에 `dark-skinned female`
    joseph joestar            gender=girl  breast_size 분포 있음

사용자가 `kaeya` 를 고르면 `dark-skinned female` 이 특징으로 제시된다.
남성 지원 여부와 별개로 **지금 값 자체가 틀린 것**이다.

### 고치는 길 세 가지

1. 그대로 둔다 — 여성 전용 도구라고 명시하고 감수
2. 오염된 항목을 목록에서 뺀다(남성 캐릭터 판별 후 제외)
3. `boy` 통을 실제로 채운다 — `1boy_solo_filtered.parquet` 으로 같은 파이프라인을
   한 번 더 돌린다. **스키마와 코드는 이미 준비돼 있다**:
   `analyze_characters.py:153` 이 `for gender in ("girl", "boy")` 로 양쪽을 읽는다.
   막힌 곳은 입력 데이터셋뿐이다.

3번이 구조적으로 가장 깨끗하지만 `1boy` 데이터셋을 새로 만들어야 하고,
그건 이 리포가 아니라 `C:\VNR\NAIA2.0` 쪽 파이프라인 작업이다.

## 현재 데이터 실측 (2026-07-30)

    작품 1,644 / 캐릭터 9,738 (girl 9,738 · boy 0)
    작품당 캐릭터: 1명 874(53%) · 2~4명 448 · 5~9명 171 · 10~29명 105 · 30~99명 30 · 100+ 16
    최대: original 473 · kantai collection 344 · idolmaster 287 · azur lane 251
    근거 행수(total_rows) 중위 84 — 10,000+ 13명(0.1%) · 1,000+ 527 · 100+ 2,443 · 30+ 5,462
    필드 보유: total_rows/personal_color/characteristics/gender/aliases 전원,
              breast_size 8,747(89.8%), alternates 1,602(16.5%)
    썸네일: 40장 (0.4%)
