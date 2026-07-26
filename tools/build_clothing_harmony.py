# -*- coding: utf-8 -*-
"""의상 조합 규칙(Harmony) 캐시 생성.

    python tools/build_clothing_harmony.py

## 출처

`core/clothes_preset/naia_clothes_preset` (51MB ZIP). 파티션은 `gsq_1girl_solo`
하나뿐이다 — 1인 이미지 기준이라 Interactive 의 **캐릭터별 개별 슬롯**과 정확히 맞는다.

| 테이블 | 행 | 쓰임 |
|---|---|---|
| clothing_region6_mapping | 3,917 | 태그 -> 착용 부위 6종 |
| clothing_conflict_rules | 5,246 | 같이 입지 않는 조합 (동시 등장 0에 가까움) |
| clothing_discouraged_rules | 18,885 | 어울리지 않는 조합 (lift < 1) |
| clothing_recommendation_rules | 109,014 | 같이 쓰이는 조합 (lift 높음) |

## 왜 걸러서 캐시하는가

전량을 런타임에 올릴 이유가 없다. 우리 의상 축(`wildcards/thumb/cloth_*.txt`,
1,644개)에 **양쪽 태그가 모두 있는 규칙만** 남긴다. 실측 커버리지:
충돌 87% / 비권장 86% / 추천 64%. 추천이 낮은 것은 seed 가 작품 한정 코스프레
태그인 경우가 많아서인데, 그것들은 애초에 축에서 제외했으므로 손실이 아니다.

## 임계값

- 충돌: `exclusion_score >= 0.9` — 동시 등장이 사실상 없는 것만. 경고는 강하게
  말하는 UI 라 오탐이 비싸다.
- 비권장: `avoid_score` 상위 N개/시드. 전량은 시드당 수십 개라 화면에 못 쓴다.
- 추천: `rank <= 8`. 이미 점수 순으로 rank 가 매겨져 있다.
"""
from __future__ import annotations

import io
import json
import zipfile
from collections import defaultdict
from pathlib import Path

import pandas as pd

ARCHIVE = Path("core/clothes_preset/naia_clothes_preset")
AXIS_DIR = Path("wildcards/thumb")
OUT = Path("data/interactive_clothing_harmony.json")

CONFLICT_MIN = 0.9      # exclusion_score
REC_TOP = 8             # 시드당 추천 개수
AVOID_TOP = 5           # 시드당 비권장 개수
REGION_LABEL_KO = {
    "HEAD_NECK_FACE": "머리·목·얼굴", "UPPER_BODY": "상체", "ARMS_HANDS": "팔·손",
    "WAIST_HIP": "허리·엉덩이", "LEGS": "다리", "FEET": "발",
}


def load_axis_tags() -> dict[str, str]:
    out: dict[str, str] = {}
    for p in AXIS_DIR.glob("cloth_*.txt"):
        for line in p.read_text(encoding="utf-8").splitlines():
            t = line.strip()
            if t:
                out.setdefault(t, p.stem)
    return out


def main() -> int:
    if not ARCHIVE.exists():
        raise SystemExit(f"아카이브 없음: {ARCHIVE}")
    axis = load_axis_tags()
    z = zipfile.ZipFile(ARCHIVE)
    rd = lambda n: pd.read_parquet(io.BytesIO(z.read(n + ".parquet")))

    # 1) 부위 매핑
    # ⚠️ `subgroup_fallback` 은 "그 서브그룹이니 일단 여기"라는 기본값이지 실제 부위가
    # 아니다. 액세서리 축에서 HEAD_NECK_FACE 로 간 154개 중 122개가 이것이었고,
    # `bag`/`sash`/`obi`/`backpack` 까지 머리·목·얼굴로 들어가 있었다.
    # 근거가 태그 이름·서브그룹 직결인 것만 쓴다(confidence 0.8 이상).
    reg = rd("clothing_region6_mapping_step42")
    trusted = reg[(reg.mapping_confidence >= 0.8)
                  & (reg.mapping_reason != "subgroup_fallback")]
    region = {r.clothing_tag: r.region6 for r in trusted.itertuples()
              if r.clothing_tag in axis}
    weak = {r.clothing_tag: r.region6 for r in reg.itertuples()
            if r.clothing_tag in axis and r.clothing_tag not in region}

    # 2) 충돌 — 무향이므로 양방향으로 넣는다
    con = rd("clothing_conflict_rules_gsq_1girl_solo")
    con = con[(con.tag_a.isin(axis)) & (con.tag_b.isin(axis))
              & (con.exclusion_score >= CONFLICT_MIN)]
    conflict: dict[str, list[str]] = defaultdict(list)
    for r in con.itertuples():
        conflict[r.tag_a].append(r.tag_b)
        conflict[r.tag_b].append(r.tag_a)
    conflict = {k: sorted(set(v)) for k, v in conflict.items()}

    # 3) 추천 / 비권장 — 시드 기준 상위 N
    rec = rd("clothing_recommendation_rules_gsq_1girl_solo")
    rec = rec[(rec.seed_tag.isin(axis)) & (rec.candidate_tag.isin(axis))
              & (rec["rank"] <= REC_TOP)]
    recommend: dict[str, list[str]] = defaultdict(list)
    for r in rec.sort_values("rank").itertuples():
        if len(recommend[r.seed_tag]) < REC_TOP:
            recommend[r.seed_tag].append(r.candidate_tag)

    dis = rd("clothing_discouraged_rules_gsq_1girl_solo")
    dis = dis[(dis.seed_tag.isin(axis)) & (dis.avoid_tag.isin(axis))
              & (dis["rank"] <= AVOID_TOP)]
    avoid: dict[str, list[str]] = defaultdict(list)
    for r in dis.sort_values("rank").itertuples():
        if len(avoid[r.seed_tag]) < AVOID_TOP:
            avoid[r.seed_tag].append(r.avoid_tag)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "source": str(ARCHIVE).replace("\\", "/"),
        "partition": "gsq_1girl_solo",
        "region_labels": REGION_LABEL_KO,
        "thresholds": {"conflict_min": CONFLICT_MIN, "rec_top": REC_TOP,
                       "avoid_top": AVOID_TOP},
        "region": region,
        "region_weak": weak,
        "conflict": conflict,
        "recommend": dict(recommend),
        "avoid": dict(avoid),
    }, ensure_ascii=False), encoding="utf-8")

    print(f"축 태그 {len(axis)}개 기준")
    print(f"  부위 매핑  {len(region):5d}개 신뢰 ({len(region)*100//len(axis)}% 커버)"
          f" + 약한 근거 {len(weak)}개 별도 보관")
    print(f"  충돌       {len(conflict):5d}개 시드 / 쌍 {len(con):,}")
    print(f"  추천       {len(recommend):5d}개 시드")
    print(f"  비권장     {len(avoid):5d}개 시드")
    print(f"저장: {OUT} ({OUT.stat().st_size/1048576:.1f}MB)")

    # 부위 매핑이 없는 축 태그 = 재분할이나 수동 보완 대상
    miss = sorted(set(axis) - set(region) - set(weak))
    print(f"\n부위 미매핑 {len(miss)}개 (상위 12): {miss[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
