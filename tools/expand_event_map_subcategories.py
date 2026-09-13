"""Enrich missing subcategories using exact Interactive tag membership only."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_event_map_category_mapping import source_info

ROOT = Path(__file__).resolve().parents[1]
SLOT_GROUP = {
    "의상": "clothing", "소품·장식": "clothing", "머리": "body", "신체": "body",
    "종족·수인": "body", "눈·얼굴": "body", "표정": "expression", "자세": "action",
    "배경": "scene", "사물": "object", "동물": "object", "성인": "adult",
    "효과·기호": "meta", "연출": "meta", "구도": "cast", "다인원": "cast",
}
# Explicit translations of existing subgroup IDs, constrained to compatible map groups.
# Generic subgroup labels (etc/meta/metatags/activity/attire/pose/expression) are
# deliberately omitted: they are not a useful expansion of a broad category.
SUBGROUPS = {
    "object": {
        "weapons": "무기", "tools": "도구", "plants": "식물", "other_animals": "기타 동물",
        "fish": "물고기", "insects": "곤충", "vehicles": "탈것", "birds": "새",
        "furniture": "가구", "dogs": "개", "cats": "고양이", "containers": "용기",
        "cards": "카드", "board_games": "보드게임", "instruments": "악기",
        "art_objects": "미술품", "reptiles": "파충류", "fire": "불", "water": "물",
        "food_tags": "음식", "technology": "기술·기기", "legendary_creatures": "상상 동물",
    },
    "clothing": {
        "legwear": "다리 의상", "headwear": "모자", "accessories": "장신구", "bra": "브래지어",
        "armor": "갑옷", "sexual_attire": "성인 의상", "patterns": "무늬", "mask": "마스크",
        "hair_accessories": "머리 장식", "costume_props": "의상 소품", "neck_and_neckwear": "목 장식",
        "sleeves": "소매", "panties": "팬티", "handwear": "장갑", "eyewear": "안경",
        "footwear": "신발", "fashion_style": "패션 스타일", "face_accessories": "얼굴 장식",
    },
    "body": {
        "body_type": "체형", "ass": "엉덩이", "anatomy": "해부·부위", "body_parts": "신체 부위",
        "hands": "손", "eyes_tags": "눈", "animal_features": "동물 특징", "kemonomimi": "동물 귀",
        "hair_styles": "헤어스타일", "tail": "꼬리", "face_tags": "얼굴", "eyes": "눈",
        "breasts_tags": "가슴", "skin_markings": "피부 표식", "genitals": "성기",
        "tattoo": "문신", "wings": "날개", "hair": "머리카락", "fluids": "체액",
    },
    "meta": {
        "symbols": "기호", "symbol": "기호", "year_tags": "연도", "text": "문자·텍스트",
        "scan": "스캔", "quality": "품질", "effects": "효과", "colors": "색상",
        "patterns": "무늬", "phrases": "문구", "parody": "패러디", "surreal": "초현실 표현",
        "censoring": "검열", "censorship": "검열", "lighting": "조명", "design_elements": "디자인 요소",
    },
    "scene": {"real_world_locations": "실제 장소", "weather": "날씨", "time": "시간대", "nature": "자연"},
    "cast": {"count": "인원수", "image_composition": "화면 구성", "focus_tags": "강조 대상",
             "focus": "강조 대상", "pov": "시점", "relationships": "인물 관계"},
    "expression": {"emotion": "감정", "personality": "성격 표현", "reaction": "반응"},
    "action": {"clothing_action": "옷 다루기", "gesture": "몸짓", "gestures": "몸짓",
               "interaction": "상호작용", "interactions": "상호작용", "posture": "신체 자세",
               "combat_actions": "전투 동작", "dances": "춤", "self_touch": "자기 접촉"},
    "situation": {"transformation": "변신", "personality": "성격", "culture": "문화",
                  "sports": "스포츠", "memes": "밈", "meme": "밈", "holidays_and_celebrations": "기념일·행사",
                  "occupation": "직업", "jobs": "직업", "relationships": "인물 관계",
                  "history": "역사", "music": "음악", "dances": "춤", "archetype": "인물 유형",
                  "anticipation": "예고·직전 상황"},
    "adult": {"sexual_positions": "체위", "simulated_sex_acts": "유사 성행위", "sex_acts": "성행위",
              "sex_act": "성행위", "sex_objects": "성인용품", "taboo": "금기", "fetish": "페티시",
              "bondage_state": "구속 상태", "gore": "고어", "nudity": "탈의·노출",
              "genitals": "성기", "fluids": "체액", "insertion": "삽입", "exposure": "노출"},
}


def expand(path: Path) -> dict:
    original = source_info(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    tags = data["tags"]
    axes_path = ROOT / "app/web/remote/js/features/interactiveAxes.mjs"
    labels_path = ROOT / "data/interactive_axis_labels.json"
    taxonomy_path = ROOT / "data/interactive_tags.json"
    script = "import {THUMB_TAGS} from " + json.dumps(axes_path.as_uri()) + ";process.stdout.write(JSON.stringify(THUMB_TAGS));"
    axes = json.loads(subprocess.check_output(["node", "--input-type=module", "-e", script], encoding="utf-8"))
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))

    def canonical(raw: str) -> str | None:
        for key in (raw.strip(), raw.strip().lower(), " ".join(raw.replace("_", " ").casefold().split())):
            if key in tags:
                return key
        return None

    memberships = defaultdict(list)
    for axis, members in axes.items():
        group = SLOT_GROUP.get(labels["slots"].get(axis))
        label = labels["labels"].get(axis)
        if not group or not label or label == axis:
            continue
        for raw in members:
            tag = canonical(raw)
            if tag:
                memberships[tag].append({"group": group, "label": label, "axis": axis})
    tax = {}
    for raw, row in taxonomy.items():
        tag = canonical(raw)
        if tag:
            tax[tag] = row

    results = Counter()
    for tag, row in tags.items():
        if not row["category"] or row["subcategory_status"] != "missing":
            continue
        matches = [m for m in memberships[tag] if m["group"] == row["group"]
                   and m["label"] != row["top_category"]]
        choices = sorted({m["label"] for m in matches})
        subgroup = tax.get(tag, {}).get("subgroup")
        fallback = SUBGROUPS.get(row["group"], {}).get(subgroup)
        if fallback == row["top_category"]:
            fallback = None
        if len(choices) == 1:
            label = choices[0]
            evidence = {"method": "interactive_axis_membership", "axes": sorted({m["axis"] for m in matches})}
        elif not choices and fallback:
            label = fallback
            evidence = {"method": "interactive_taxonomy_subgroup", "subgroup": subgroup,
                        "taxonomy_group": tax[tag].get("group")}
        else:
            reason = "multiple_axis_categories" if choices else "no_specific_compatible_category"
            row["subcategory_resolution"] = {"reason": reason, "candidate_labels": choices}
            results[reason] += 1
            continue
        row["subcategory"] = label
        row["subcategory_status"] = "mapped"
        row["subcategory_evidence"] = evidence
        row["flags"] = [flag for flag in row["flags"] if flag != "subcategory_missing"]
        row["flags"].append("subcategory_enriched")
        results[evidence["method"]] += 1

    summary = data["summary"]
    summary["flag_counts"] = dict(Counter(f for r in tags.values() for f in r["flags"]))
    summary["subcategory_status_counts"] = dict(Counter(r["subcategory_status"] for r in tags.values()))
    data["subcategory_expansion"] = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "input": original,
        "sources": {"axes": source_info(axes_path), "labels": source_info(labels_path),
                    "taxonomy": source_info(taxonomy_path), "rules": source_info(Path(__file__))},
        "policy": "Fill classified tags missing subcategories using exact Interactive membership. Preserve original category, group, source, conflicts and existing subcategories. Multiple axis labels remain unresolved. Generic or incompatible taxonomy subgroups are not used.",
        "source_category_note": "category and top_category retain the original source text; an enriched subcategory is independent and carries subcategory_evidence.",
        "counts": dict(results),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"expansion": dict(results), "subcategories": summary["subcategory_status_counts"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mapping", type=Path)
    args = parser.parse_args()
    print(json.dumps(expand(args.mapping), ensure_ascii=False, indent=2))
