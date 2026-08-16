# -*- coding: utf-8 -*-
"""Event Preset 아카이브에서 **앵커별 범주 주변분포**를 증류한다.

⚠️ **이것은 아직 "레시피"가 아니다.** 의상/신체/표정을 각각 독립 집계한
주변분포(marginals)라, 각 범주의 상위 후보들이 **같은 게시물에 함께 나왔는지는
모른다.** 세 범주에서 하나씩 뽑아 한 줄로 묶으면 그건 관측된 조합이 아니라
합성된 조합이다 - 이 시스템이 처음에 저지른 실패와 같은 종류다(Codex 게이트).

용도는 **후보 생성 prior** 다. 실제 2~3태그 레시피는 joint support 를 원 코퍼스
또는 `event_observed_combo` 로 확인한 뒤에 만든다.


## 왜

조합 추천의 통계 모델(`core/tag_combo`)은 넓은 seed 에서 무너진다 - `sitting` 에
`feet/toes/soles`(0.35%), `embarrassed` 에 `peeing`(0.8%) 을 낸다. 원인은 지명
단계에 있다(`query.py:_tally` 가 게시물당 lift 상위 3개만 지명해서, `blush` 처럼
흔하면서 적합한 태그는 한 번도 세어지지 않는다).

그런데 **Event Preset 아카이브에 이미 답이 있다.** 행동(event) 태그를 축으로
의상/신체(characteristic)/표정이 **따로** 집계돼 있고, 인원 x 등급으로 파티션까지
갈려 있다. 실측:

    sitting  의상 skirt .26 · shirt .25    신체 long hair .60    표정 blush .41 · smile .36

이게 사용자가 어려워한다던 **의상-신체-액션** 구조 그 자체다.

## 왜 아카이브를 그대로 쓰지 않는가

Event Preset 은 **별도 다운로드(404MB)** 다. 그걸 전제로 깔면 안 받은 사용자에겐
조합 번들 179MB 보다 나쁘다(사용자 지적 2026-08-14). 그래서 원본을 요구하지 않고
**필요한 것만 증류해 우리 번들에 넣는다.**

## 등급

`e` 를 **포함한다.** 조합 모델 자체가 e 를 4.4% 포함하고 있고, "강한 NSFW/taboo
조합도 사용자 의도이며 프로그램이 제한할 근거가 없다"는 것이 이 기능의 제약이다.
여기서 e 를 빼면 새 계층이 조용히 내용 필터를 하는 셈이 된다.

## 색

색/무늬 후보는 버린다(`core/tag_combo/noise.py`). `sitting` 에 `blue eyes` 를
권하는 것은 정보가 아니다. **앵커는 거르지 않는다** - 사용자가 고른 것은 그대로 둔다.

## 쓰는 법

    python tools/build_event_recipe_bank.py --dry-run      # 크기/품질만 본다
    python tools/build_event_recipe_bank.py --out data/tag_combo/recipe_bank.json
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.tag_combo.noise import is_color_tag        # noqa: E402
from core.tag_combo.person import PERSON_GROUPS      # noqa: E402

# 아카이브 기본 위치. 저장소 `data/` 에는 없다(런타임 다운로드 자산).
DEFAULT_ARC = ROOT / "NAIA-Portable/user-data/data/event_preset/naia_prompt_preset"
RATINGS = ("e", "g", "q", "s")
KINDS = ("clothing", "characteristic", "expression")


def _read(z: zipfile.ZipFile, name: str) -> pd.DataFrame | None:
    if name not in z.namelist():
        return None
    return pd.read_parquet(io.BytesIO(z.read(name)))


def distill_group(z: zipfile.ZipFile, group: str, *, min_conf: float,
                  min_count: int, top_n: int, min_pmi: float) -> tuple[dict, dict]:
    """한 인원 그룹의 (레시피, 통계). 등급 4종을 합쳐 하나로 만든다."""
    cats = [c for c in (_read(z, f"partitions/{r}_{group}/event_catalog.parquet")
                        for r in RATINGS) if c is not None]
    if not cats:
        return {}, {"anchors": 0, "rows": 0, "note": "파티션 없음"}
    post = (pd.concat(cats, ignore_index=True)
              .groupby("event_tag", as_index=False)["post_count"].sum())
    pmap = dict(zip(post["event_tag"], post["post_count"]))

    out: dict[str, dict[str, list]] = {}
    stat = {"anchors": 0, "rows": 0, "dropped_color": 0, "dropped_conf": 0}
    for kind in KINDS:
        col = f"{kind}_tag"
        frames = [d for d in (_read(z, f"partitions/{r}_{group}/event_{kind}_cooccurrence.parquet")
                              for r in RATINGS) if d is not None]
        if not frames:
            continue
        # 등급 4종을 합친다.
        #
        # ⚠️ **PMI 를 count 가중 평균하면 안 된다.** 처음엔 그렇게 했는데, PMI 는
        # 로그 비율이라 등급마다 후보 기저율 P(B|r) 이 다르면 평균이 편향된다.
        # 올바른 것은 관측/기대의 pooled 비다:
        #
        #     PMI = ln( Σ_r count_r  /  Σ_r anchor_n_r · P(B|r) )
        #
        # 실측(clothing 20만 쌍): 옛 방식이 문턱 0.3 을 통과시킨 것 중 **4,832건이
        # 새 방식에서 탈락**했고 반대 방향은 **0건**이었다 - 즉 옛 방식은 한쪽으로
        # 과대 통과만 했다. 부호까지 뒤집힌 것이 4,194건(Codex 게이트).
        #
        # 저장된 열에서 복원한다: conf = count/anchor_n, pmi = ln(conf / P(B|r))
        # 이므로 anchor_n = count/conf, P(B|r) = conf / exp(pmi).
        raw = pd.concat(frames, ignore_index=True)
        raw = raw[(raw["confidence"] > 0) & raw["confidence"].notna()]
        raw["anchor_n"] = raw["count"] / raw["confidence"]
        raw["p_b_r"] = raw["confidence"] / np.exp(raw["pmi"])
        raw["expected"] = raw["anchor_n"] * raw["p_b_r"]
        df = (raw.groupby(["event_tag", col], as_index=False)
                 .agg(count=("count", "sum"), expected=("expected", "sum")))
        df = df[df["expected"] > 0]
        df["pmi"] = np.log(df["count"] / df["expected"])
        df = df.drop(columns=["expected"])
        del raw
        # 색/무늬 후보 제거. 어휘가 아니라 **후보**에만 건다.
        mask = ~df[col].map(is_color_tag)
        stat["dropped_color"] += int((~mask).sum())
        df = df[mask]
        # 앵커 빈도로 conf 를 낸다. 카탈로그에 없는 앵커는 버린다(정규화 불가).
        df["anchor_n"] = df["event_tag"].map(pmap)
        df = df[df["anchor_n"].notna() & (df["anchor_n"] > 0)]
        df["conf"] = df["count"] / df["anchor_n"]
        # **두 문턱을 다 건다.**
        #   conf  = 흔한가 (이 앵커에서 얼마나 자주 같이 오나)
        #   pmi   = 특징적인가 (앵커와 무관하게 그냥 흔한 것은 아닌가)
        # conf 만 걸었더니 sitting/standing/kneeling 이 전부 `long hair .60`,
        # `blush .4` 를 냈다 - 그건 코퍼스 기저율이지 그 앵커의 특징이 아니다.
        keep = ((df["conf"] >= min_conf) & (df["count"] >= min_count)
                & (df["pmi"] >= min_pmi))
        stat["dropped_conf"] += int((~keep).sum())
        df = df[keep]
        # **순위는 conf 로 매긴다.** pmi 로 매기면 희귀한 쪽으로 쏠린다 -
        # 목표는 "흔하면서 특징적인 것" 이라 pmi 는 문턱, conf 는 순위다.
        df = (df.sort_values(["event_tag", "conf"], ascending=[True, False])
                .groupby("event_tag").head(top_n))
        for anchor, sub in df.groupby("event_tag"):
            rec = out.setdefault(str(anchor), {})
            rec[kind] = [[str(r[col]), round(float(r["conf"]), 3),
                          round(float(r["pmi"]), 2)] for _, r in sub.iterrows()]
            stat["rows"] += len(sub)
        del df
    stat["anchors"] = len(out)
    return out, stat


def main() -> int:
    ap = argparse.ArgumentParser(description="Event Preset -> 레시피 뱅크 증류")
    ap.add_argument("--archive", default=str(DEFAULT_ARC))
    ap.add_argument("--out", default=str(ROOT / "data" / "tag_combo"
                                         / "anchor_feature_marginals.json"))
    ap.add_argument("--min-conf", type=float, default=0.05,
                    help="앵커 대비 조건부 확률 하한 (흔한가)")
    ap.add_argument("--min-pmi", type=float, default=0.30,
                    help="PMI 하한 (특징적인가). 자연로그라 0.3 = 상대위험 약 1.35배")
    ap.add_argument("--min-count", type=int, default=30,
                    help="동시출현 절대 하한 - 꼬리 잡음을 막는다")
    ap.add_argument("--top-n", type=int, default=8,
                    help="앵커 x 카테고리당 최대 후보 수")
    ap.add_argument("--dry-run", action="store_true", help="쓰지 않고 크기만 본다")
    args = ap.parse_args()

    arc = Path(args.archive)
    if not arc.exists():
        print(f"!! 아카이브가 없다: {arc}")
        print("   Event Preset 을 받은 설치에서 경로를 --archive 로 주거나,")
        print("   포터블의 user-data/data/event_preset 아래를 확인하라.")
        return 2

    z = zipfile.ZipFile(arc)
    bank: dict[str, dict] = {}
    t0 = time.time()
    print(f"{'group':<30} {'anchors':>8} {'rows':>9} {'color버림':>9} {'conf버림':>9}")
    print("-" * 70)
    for g in PERSON_GROUPS:
        rec, st = distill_group(z, g, min_conf=args.min_conf, min_pmi=args.min_pmi,
                                min_count=args.min_count, top_n=args.top_n)
        bank[g] = rec
        print(f"{g:<30} {st['anchors']:>8,} {st['rows']:>9,} "
              f"{st.get('dropped_color', 0):>9,} {st.get('dropped_conf', 0):>9,}")

    blob = json.dumps({"format": "NRB1", "minConf": args.min_conf,
                       "minCount": args.min_count, "topN": args.top_n, "minPmi": args.min_pmi,
                       "groups": bank}, ensure_ascii=False, separators=(",", ":"))
    total_anchors = sum(len(v) for v in bank.values())
    total_rows = sum(len(x) for v in bank.values() for r in v.values() for x in r.values())
    print("-" * 70)
    print(f"앵커 합계 {total_anchors:,} · 행 합계 {total_rows:,} · {time.time()-t0:.0f}s")
    print(f"JSON 크기 {len(blob.encode('utf-8'))/1e6:.1f}MB")
    import zlib
    print(f"deflate 후 {len(zlib.compress(blob.encode('utf-8'), 6))/1e6:.1f}MB")

    if args.dry_run:
        print("\n--dry-run 이라 쓰지 않았다.")
        return 0
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(blob, encoding="utf-8")
    print(f"저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
