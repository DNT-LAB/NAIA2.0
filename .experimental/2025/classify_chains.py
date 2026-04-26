"""
Event chain 분류기 — axis-aware approach
classified parquet의 tag→category lookup을 재활용하여
32,741개 chain을 story / variant / borderline으로 분류.

핵심 아이디어: 어떤 축(axis)이 변하느냐로 판별
  - Story: pose_action/location/expression이 변함 (장면이 진행됨)
  - Variant: clothing/characteristic만 변함 (같은 장면에서 옷/캐릭터만 교체)
  - Borderline: 혼합 신호
"""

import json
import time
from pathlib import Path
from collections import Counter
from dataclasses import dataclass, field, asdict

from core.tag_axis_registry import (
    PRIMARY_AXES,
    apply_axis_overrides,
    is_person_count_tag,
    normalize_tag,
)

# --- tag lookup 빌드 (preprocess_general_tags.py와 동일 로직) ---

ROOT = Path(r"C:\VNR\NAIA2.0")
TAGLIST_DIR = ROOT / "data" / "taglist"
DATA_DIR = ROOT / "data"
CHAINS_DIR = ROOT / ".experimental" / "2025" / "event_chains"
OUTPUT_DIR = ROOT / ".experimental" / "2025" / "classified"

CATEGORIES = list(PRIMARY_AXES)

PRIORITY = {
    "clothing": 60, "expression": 50, "pose_action": 40,
    "sexual_or_nsfw": 45, "characteristic": 35,
    "location": 30, "object": 20, "meta": 10,
}

_EXTRA_EXPRESSION = {"?", "!", "!!", "??", "| |", "+++", "<|> <|>", "\\n/", "3 3", "x<"}


def _load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _load_flat(path):
    return set(_load_json(path).get("tags", []))


def _load_txt(path):
    return {l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}


def build_lookup() -> dict[str, str]:
    from collections import defaultdict

    expr = set(_load_json(TAGLIST_DIR / "expression_tags.json").get("modifiers", []))
    for g in _load_json(TAGLIST_DIR / "expression_tags.json").get("groups", {}).values():
        expr.update(g)
    expr |= _EXTRA_EXPRESSION

    pa = set()
    pa_data = _load_json(TAGLIST_DIR / "pose_action_tags.json")
    for g in pa_data.get("categories", {}).values():
        pa.update(g)
    pa.update(pa_data.get("uncategorized", []))

    cl_regions = _load_json(TAGLIST_DIR / "clothing_regions.json")
    cl = _load_txt(DATA_DIR / "clothes_list.txt")
    for g in cl_regions.get("regions", {}).values():
        cl.update(g)
    cl.update(cl_regions.get("unassigned_region", []))

    sets = {
        "expression": expr,
        "pose_action": pa,
        "location": _load_flat(TAGLIST_DIR / "location_tags.json"),
        "meta": _load_flat(TAGLIST_DIR / "meta_tags.json"),
        "object": _load_flat(TAGLIST_DIR / "object_tags.json"),
        "clothing": cl,
        "characteristic": _load_txt(DATA_DIR / "characteristic_list.txt"),
    }

    tag_cats = defaultdict(list)
    for cat, tags in sets.items():
        for t in tags:
            tag_cats[normalize_tag(t)].append(cat)

    lookup = {}
    for tag, cats in tag_cats.items():
        lookup[tag] = max(cats, key=lambda c: PRIORITY[c]) if len(cats) > 1 else cats[0]

    # Codex overrides
    ov_path = OUTPUT_DIR / "overlap_classification.json"
    if ov_path.exists():
        for item in _load_json(ov_path).get("misclassified", []):
            tag = normalize_tag(item["tag"])
            if tag in lookup:
                lookup[tag] = item["suggested"]

    apply_axis_overrides(
        lookup,
        allowed_axes=set(CATEGORIES + ["person_count", "person_focus"]),
    )

    return lookup


# --- 축별 분석 ---

# Story 축: 이것들이 변하면 장면이 진행되는 것
STORY_AXES = {"pose_action", "location", "expression"}
# Variant 축: 이것들만 변하면 같은 장면의 변형
VARIANT_AXES = {"clothing", "characteristic"}
# 무시 축
IGNORE_AXES = {"meta", "object", "uncategorized", "person_count", "person_focus", "sexual_or_nsfw"}


def classify_tags(tags: list[str], lookup: dict[str, str]) -> dict[str, set[str]]:
    """태그 목록을 축별 set으로 분류."""
    buckets: dict[str, set[str]] = {
        c: set() for c in CATEGORIES + ["person_count", "person_focus", "uncategorized"]
    }
    for raw in tags:
        tag = normalize_tag(raw)
        if is_person_count_tag(tag):
            buckets["person_count"].add(tag)
            continue
        cat = lookup.get(tag, "uncategorized")
        if cat not in buckets:
            cat = "uncategorized"
        buckets[cat].add(tag)
    return buckets


@dataclass
class TransitionMetrics:
    """두 프레임 간 축별 변화량."""
    axis_added: dict[str, int] = field(default_factory=dict)
    axis_removed: dict[str, int] = field(default_factory=dict)
    axis_changed: dict[str, int] = field(default_factory=dict)  # added + removed
    rating_change: str = ""  # e.g. "g→s"


def measure_transition(
    frame_a: dict[str, set[str]],
    frame_b: dict[str, set[str]],
    rating_a: str,
    rating_b: str,
) -> TransitionMetrics:
    m = TransitionMetrics()
    for axis in CATEGORIES:
        added = frame_b[axis] - frame_a[axis]
        removed = frame_a[axis] - frame_b[axis]
        m.axis_added[axis] = len(added)
        m.axis_removed[axis] = len(removed)
        m.axis_changed[axis] = len(added) + len(removed)
    if rating_a != rating_b:
        m.rating_change = f"{rating_a}→{rating_b}"
    return m


@dataclass
class ChainClassification:
    chain_id: int
    depth: int
    verdict: str  # story, variant, borderline
    confidence: float  # 0.0 ~ 1.0
    reason: str
    story_score: float = 0.0
    variant_score: float = 0.0
    axis_summary: dict = field(default_factory=dict)
    rating_progression: str = ""


def classify_chain(chain: dict, lookup: dict[str, str]) -> ChainClassification:
    frames_raw = chain["frames"]
    n_frames = len(frames_raw)
    n_transitions = n_frames - 1

    if n_transitions == 0:
        return ChainClassification(
            chain_id=chain["chain_id"], depth=chain["depth"],
            verdict="variant", confidence=1.0, reason="single frame",
        )

    # 모든 프레임 분류
    classified_frames = [classify_tags(f["tags"], lookup) for f in frames_raw]
    ratings = [f["rating"] for f in frames_raw]

    # 축별 전이 측정
    transitions = []
    for i in range(n_transitions):
        t = measure_transition(classified_frames[i], classified_frames[i + 1], ratings[i], ratings[i + 1])
        transitions.append(t)

    # --- 축별 집계 ---
    # 각 축이 변한 전이 수 (changed > 0인 전이 수)
    axis_active_transitions = {}
    axis_total_changes = {}
    for axis in CATEGORIES:
        active = sum(1 for t in transitions if t.axis_changed[axis] > 0)
        total = sum(t.axis_changed[axis] for t in transitions)
        axis_active_transitions[axis] = active
        axis_total_changes[axis] = total

    # rating 진행
    rating_changes = sum(1 for t in transitions if t.rating_change)
    rating_str = "→".join(ratings)

    # --- 축별 활성화 수 ---
    location_active = axis_active_transitions.get("location", 0)
    pose_active = axis_active_transitions.get("pose_action", 0)
    expr_active = axis_active_transitions.get("expression", 0)
    char_active = axis_active_transitions.get("characteristic", 0)
    cloth_active = axis_active_transitions.get("clothing", 0)

    char_total = axis_total_changes.get("characteristic", 0)
    pose_total = axis_total_changes.get("pose_action", 0)

    story_axes_active = pose_active + location_active + expr_active

    # --- per-transition: clothing이 story 축과 동시에 변하는지 체크 ---
    # clothing이 story 축과 동시에 변한 전이 수 (= story에 수반된 옷 변화)
    cloth_with_story = sum(
        1 for t in transitions
        if t.axis_changed["clothing"] > 0
        and any(t.axis_changed[a] > 0 for a in STORY_AXES)
    )
    # story 축 없이 clothing만 변한 전이 수 (= 순수 의상 교체)
    cloth_solo = cloth_active - cloth_with_story

    # characteristic 변화량 판정
    # char 1-2개 변화 + pose 동시 변화 → 각도 변화에 의한 부수적 태깅 차이
    char_is_incidental = (char_total <= 2 and pose_active >= 1)
    # char 3개 이상 변화 → 캐릭터 교체 신호
    char_is_swap = (char_total >= 3)

    # --- Story score ---
    story_score = 0.0

    # pose_action 변화
    if pose_active >= 2:
        story_score += 0.3
    elif pose_active == 1:
        story_score += 0.15

    # location 변화
    if location_active >= 2:
        story_score += 0.3
    elif location_active == 1:
        story_score += 0.2

    # expression 변화
    if expr_active >= 2:
        story_score += 0.2
    elif expr_active == 1:
        story_score += 0.1

    # rating 에스컬레이션
    if rating_changes >= 1:
        story_score += 0.15

    # 다축 동시 변화 (story 축 2개 이상이 동시에 변한 전이)
    multi_axis_transitions = sum(
        1 for t in transitions
        if sum(1 for a in STORY_AXES if t.axis_changed[a] > 0) >= 2
    )
    if multi_axis_transitions >= 2:
        story_score += 0.15
    elif multi_axis_transitions == 1:
        story_score += 0.05

    # clothing이 story와 동반 변화 → story 보너스 (포즈 바뀌면서 옷도 바뀜 = 진행)
    if cloth_with_story >= 1 and pose_active >= 1:
        story_score += 0.1

    # characteristic이 부수적이면 → variant 신호 차감 (story에 유리)
    if char_is_incidental:
        story_score += 0.05

    # --- Variant score ---
    variant_score = 0.0

    # characteristic 대량 변화 (캐릭터 교체)
    if char_is_swap:
        variant_score += 0.35
    elif char_active >= 1 and not char_is_incidental:
        variant_score += 0.2

    # 순수 clothing 교체 (story 축 동반 없이)
    if cloth_solo >= n_transitions * 0.5:
        variant_score += 0.3
    elif cloth_solo >= 1:
        variant_score += 0.1

    # story 축이 전혀 안 변함
    if pose_active == 0 and location_active == 0:
        variant_score += 0.25
    elif story_axes_active <= 1:
        variant_score += 0.1

    # expression만 변함 (포즈/장소 고정) → 약한 variant
    if expr_active >= 1 and pose_active == 0 and location_active == 0:
        variant_score += 0.05

    # --- zero_change 감지 ---
    is_zero_change = all(
        axis_active_transitions.get(a, 0) == 0
        for a in ["pose_action", "location", "expression", "clothing", "characteristic"]
    )

    # --- 캐릭터 변경 감지 (char_total >= 3 → diff_chars) ---
    # 어떤 verdict이든 캐릭터가 바뀌면 diff_chars로 분리
    if char_is_swap:
        verdict = "diff_chars"
        confidence = min(0.5 + char_total * 0.05, 1.0)
        reason = f"char changed ({char_total} tags across {char_active}t)"

    elif is_zero_change:
        verdict = "variant"
        confidence = 0.9
        reason = "zero meaningful axis change"

    elif story_score >= 0.35 and story_score > variant_score:
        verdict = "story"
        confidence = min(story_score, 1.0)
        reasons = []
        if pose_active >= 1:
            reasons.append(f"pose {pose_active}t")
        if location_active >= 1:
            reasons.append(f"location {location_active}t")
        if expr_active >= 1:
            reasons.append(f"expression {expr_active}t")
        if rating_changes >= 1:
            reasons.append(f"rating {rating_changes}t")
        if cloth_with_story >= 1:
            reasons.append(f"cloth+story {cloth_with_story}t")
        if char_is_incidental:
            reasons.append(f"char incidental ({char_total})")
        reason = "; ".join(reasons) or "multi-axis progression"

    else:
        # variant 흡수 (기존 variant + 기존 borderline 모두)
        verdict = "variant"
        confidence = max(variant_score, 0.3)
        reasons = []
        if cloth_solo >= 1:
            reasons.append(f"cloth solo {cloth_solo}t")
        if cloth_active >= 1 and cloth_solo == 0:
            reasons.append(f"cloth {cloth_active}t")
        if pose_active >= 1:
            reasons.append(f"weak pose {pose_active}t")
        if expr_active >= 1:
            reasons.append(f"expr {expr_active}t")
        if pose_active == 0 and location_active == 0:
            reasons.append("same composition")
        reason = "; ".join(reasons) or "same-char variant"
        reason = f"story={story_score:.2f} vs variant={variant_score:.2f}"

    return ChainClassification(
        chain_id=chain["chain_id"],
        depth=chain["depth"],
        verdict=verdict,
        confidence=round(confidence, 3),
        reason=reason,
        story_score=round(story_score, 3),
        variant_score=round(variant_score, 3),
        axis_summary={
            a: {"active_transitions": axis_active_transitions[a], "total_changes": axis_total_changes[a]}
            for a in CATEGORIES
        },
        rating_progression=rating_str,
    )


def main():
    print("=" * 60)
    print("Event Chain classifier - axis-aware")
    print("=" * 60)

    t0 = time.time()
    lookup = build_lookup()
    print(f"[lookup] {len(lookup):,} tags, {time.time() - t0:.1f}s")

    # chain 파일 로드
    chain_files = sorted(CHAINS_DIR.glob("event_*.json"))
    print(f"[chains] {len(chain_files):,} files")

    results = []
    counts = Counter()
    t1 = time.time()

    for i, path in enumerate(chain_files):
        chain = json.loads(path.read_text(encoding="utf-8"))
        cl = classify_chain(chain, lookup)
        results.append(asdict(cl))
        counts[cl.verdict] += 1

        if (i + 1) % 5000 == 0:
            elapsed = time.time() - t1
            print(f"  {i + 1:,}/{len(chain_files):,} ({elapsed:.1f}s) - S:{counts['story']} V:{counts['variant']} B:{counts['borderline']}")

    elapsed = time.time() - t1
    print(f"\n{'=' * 60}")
    print(f"Done. {len(results):,} chains, {elapsed:.1f}s")
    print(f"  Story:      {counts['story']:>6,} ({counts['story']/len(results)*100:.1f}%)")
    print(f"  Variant:    {counts['variant']:>6,} ({counts['variant']/len(results)*100:.1f}%)")
    print(f"  Diff chars: {counts['diff_chars']:>6,} ({counts['diff_chars']/len(results)*100:.1f}%)")
    print(f"  Total:      {len(results):>6,}")

    # 저장
    out_path = OUTPUT_DIR / "chain_classification.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[saved] {out_path} ({out_path.stat().st_size / 1e6:.1f}MB)")

    # 요약 통계
    print(f"\n=== Confidence distribution ===")
    for v in ["story", "variant", "diff_chars"]:
        subset = [r for r in results if r["verdict"] == v]
        if subset:
            confs = [r["confidence"] for r in subset]
            print(f"  {v:12s}: avg={sum(confs)/len(confs):.3f}, min={min(confs):.3f}, max={max(confs):.3f}")

    # 각 verdict에서 샘플 5개씩
    print(f"\n=== Samples ===")
    for v in ["story", "variant", "diff_chars"]:
        subset = sorted([r for r in results if r["verdict"] == v], key=lambda r: -r["confidence"])
        print(f"\n--- {v} (top 5 by confidence) ---")
        for r in subset[:5]:
            print(f"  chain {r['chain_id']:>6d} (depth={r['depth']}) conf={r['confidence']:.3f}: {r['reason']}")
            print(f"    rating: {r['rating_progression']}")
            axes = {a: r['axis_summary'][a]['total_changes'] for a in STORY_AXES | VARIANT_AXES if r['axis_summary'][a]['total_changes'] > 0}
            print(f"    axes: {axes}")


if __name__ == "__main__":
    main()
