"""I.Sequence 용 story 데이터셋 빌더 (2026-10-17 사용자 지시).

입력: Dev0714 ``data/NAIA_event_dataset_1girl_story.parquet`` (Danbooru 게시물 행 + ``story_group_id`` · ``order_in_group``).
출력: ``events_v1.parquet`` 과 **같은 꼴**(그룹 1행 = group_id · peak_rating · frame_count · person · search_tags · frames JSON)
      -> 기본 ``<user-data>/data/sequence_preset/story_v1.parquet``. ``SequencePresetService`` 가 그대로 읽는다.

걸러 내는 것:
  - **거의 같은 컷** - 이웃 컷 태그의 Jaccard 가 ``--near-dup`` (기본 0.9) 이상인 이야기를 통째로 뺀다.
    같은 프롬프트로 두 컷을 그리면 연쇄가 앞 칸을 베낀다(2026-10-17 라이브 - Q 두 그룹 3컷이 2컷과 화소 차 8~9).
  - ``build_events`` 와 같은 차단(_BLOCK = 나이 표식 · 진짜 만화/멀티뷰 · 루프 애니메이션)이 든 이야기.
컷 순서는 데이터의 ``order_in_group`` 그대로(단계 정렬을 하지 않는다 - 이야기 순서다).
stage 는 화면 표시용 가벼운 분류다(아래 _stage).

python tools/sequence_preset/build_story_events.py --src <story.parquet> --out <story_v1.parquet> [--near-dup 0.9]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.sequence_preset.build_events import _BLOCK, EXPOSURE_SOFT, RATING_ORDER, person_cats  # noqa: E402

# 표시용 단계 - character_state_dag_1girl_story 의 상태 이름과 같은 키(STAGE_LABELS 가 한글로 바꾼다). 앞에 있을수록 우선.
_STAGE_RULES = [
    ("aftermath", {"after_sex", "after_vaginal", "after_anal", "after_fellatio", "cumdrip"}),
    ("release", {"cum", "ejaculation", "cum_in_pussy", "cum_on_body", "female_ejaculation", "orgasm"}),
    ("penetration", {"sex", "vaginal", "anal", "penetration", "imminent_penetration"}),
    ("oral_manual", {"fellatio", "oral", "handjob", "paizuri", "cunnilingus", "footjob"}),
    ("partnered_contact", {"groping", "grabbing_another's_breast", "kissing", "hetero"}),
    ("solo_stimulation", {"masturbation", "sex_toy", "vibrator", "dildo", "fingering"}),
]


def _stage(tags: set) -> str:
    for stage, keys in _STAGE_RULES:
        if tags & keys:
            return stage
    return "tease_exposure" if tags & EXPOSURE_SOFT else "baseline_presentation"


def _tags(general) -> set:
    """story 의 general = 쉼표 · 공백형('long hair') -> events_v1 과 같은 밑줄형 토큰('long_hair')."""
    return {t.strip().lower().replace(" ", "_") for t in str(general or "").split(",") if t.strip()}


def build(src: Path, out: Path, near_dup: float) -> dict:
    df = pd.read_parquet(src, columns=["id", "general", "rating", "story_group_id", "order_in_group"])
    df = df.sort_values(["story_group_id", "order_in_group", "id"])
    rows, dropped_dup, dropped_block, dropped_short = [], 0, 0, 0
    for gid, g in df.groupby("story_group_id", sort=False):
        frames = [{"id": int(r.id), "rating": str(r.rating), "tags": _tags(r.general)} for r in g.itertuples()]
        if len(frames) < 2:
            dropped_short += 1
            continue
        union = set().union(*(f["tags"] for f in frames))
        if union & _BLOCK:
            dropped_block += 1
            continue
        sets = [f["tags"] for f in frames]
        if any(len(a & b) / max(1, len(a | b)) >= near_dup for a, b in zip(sets, sets[1:])):
            dropped_dup += 1
            continue
        peak = max((f["rating"] for f in frames), key=lambda r: RATING_ORDER.get(r, 0))
        frame_list = [{"i": i, "id": f["id"], "rating": f["rating"], "stage": _stage(f["tags"]),
                       "tags": sorted(f["tags"])} for i, f in enumerate(frames)]
        rows.append({
            "group_id": int(gid), "peak_rating": peak, "frame_count": len(frame_list),
            "person": " ".join(person_cats(union)),
            "search_tags": " ".join(sorted(union)),
            "frames": json.dumps(frame_list, ensure_ascii=False),
        })
    out_df = pd.DataFrame(rows, columns=["group_id", "peak_rating", "frame_count", "person", "search_tags", "frames"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_parquet(out, index=False)
    return {
        "stories_in": int(df["story_group_id"].nunique()), "kept": len(out_df),
        "dropped_near_dup": dropped_dup, "dropped_block": dropped_block, "dropped_short": dropped_short,
        "peak": out_df["peak_rating"].value_counts().to_dict(),
        "frames": out_df["frame_count"].value_counts().sort_index().head(8).to_dict(),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--near-dup", type=float, default=0.9)
    args = ap.parse_args()
    stats = build(args.src, args.out, args.near_dup)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
