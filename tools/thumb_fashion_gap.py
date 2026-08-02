# -*- coding: utf-8 -*-
"""패션·관계 그룹의 공백을 기존 축으로 재분류한다.

## 무엇을 찾았나

태그 사전 전수 대조(2026-08-02): 빈도 3,000 이상인데 썸네일도 축도 없는 태그를
훑었다. 색·크기·성인·이미 있는 것을 빼고 **Danbooru 풀에 실재하는 것만** 남겼다.

    89개 — 무늬/프린트 40 · 관계 13 · 의상 부위 36

## e621 은 뺐다

`Expressions`(33) · `Actions`(120) · `Effects`(35) · `Danger`(196)은 전부 e621
어휘라 제외했다(사용자 지시). **판별자는 `source` 필드가 아니라 Danbooru 풀
존재 여부다** — `source` 는 패션 그룹도 비어 있는데 그쪽은 100% Danbooru 다.
실측: Expressions 33개 중 Danbooru 풀에 있는 것 0개, 패션 500+ 중 100%.

한 번 `Expressions` 를 표정 축으로 끌어왔다가 이 대조로 되돌렸다.

## 어디로 보내나

무늬는 이미 `cloth_pattern` 축이 있다(25개). 프린트 계열은 **본체 + 수식어**라
`cloth_pattern` 의 정체("무늬를 옷 전체에 건다")와 맞는다.

관계(`siblings`·`couple`·`twins`)는 2명 이상이 필요하다 — 다인원 축 소관이라
`pose_multi_relation` 을 신설한다. 나머지 의상은 부위별 기존 축으로 보낸다.

사용: python tools/thumb_fashion_gap.py
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.kr_tag_loader import load_kr_tag_records  # noqa: E402
from tools.nsfw_explicit_vocab import is_explicit_vocab  # noqa: E402

OUT = Path("wildcards/thumb")
CUT = 3000
RATING = Path("data/tag_rating.json")

# 서브그룹(한글 라벨) -> 기존 축. 무늬/프린트는 한 축으로 모은다.
SUB_AXIS = {
    "무늬": "cloth_pattern", "패턴": "cloth_pattern", "의상 패턴": "cloth_pattern",
    "액세서리": "cloth_accessory", "장신구": "cloth_accessory",
    "의상": "cloth_style", "스타일": "cloth_style", "유니폼": "cloth_uniform",
    "수영복": "cloth_swim", "양말": "cloth_legwear", "양말류": "cloth_legwear",
    "상의": "cloth_top", "하의": "cloth_bottom", "원피스": "cloth_dress",
    "모자": "cloth_headwear", "장갑": "cloth_handwear", "속옷": "cloth_under",
    "신발": "cloth_footwear", "의상 디테일": "cloth_detail",
    # 서브그룹 라벨이 여러 벌이다(같은 개념에 이름이 둘 이상). 실측으로 나온 것을 붙인다.
    "전통 의상": "cloth_traditional", "전통의상": "cloth_traditional",
    "헤어 장식": "cloth_hairacc", "헤어 액세서리": "cloth_hairacc",
    "머리 장식": "cloth_hairacc", "리본": "cloth_hairacc",
    "교복": "cloth_uniform", "의상 요소": "cloth_detail",
    "스타킹": "cloth_legwear", "레그웨어": "cloth_legwear",
    "안경": "cloth_eyewear", "안경류": "cloth_eyewear",
    "가방": "cloth_carried", "갑옷": "cloth_armor", "소매": "cloth_sleeve",
    "옷깃": "cloth_neck", "칼라": "cloth_neck", "겉옷": "cloth_outer",
    "아우터": "cloth_outer", "한벌옷": "cloth_dress", "드레스": "cloth_dress",
    "스커트": "cloth_bottom", "화장": "marking", "장식": "cloth_accessory",
    "민속 의상": "cloth_traditional", "코스튬": "cloth_uniform",
    "운동복": "cloth_style", "체육복": "cloth_style", "실내복": "cloth_style",
    "전신": "cloth_style", "의류": "cloth_style", "의류 요소": "cloth_detail",
    "의류 상태": "cloth_state", "언더웨어": "cloth_under", "헤어컬러": "hair_pattern",
}
# 관계는 2명 이상이 필요하다 — 신설 축.
RELATION_AXIS = "pose_multi_relation"
RELATION_LABEL = "관계"


def main() -> int:
    raw = load_kr_tag_records().raw
    rating = json.loads(RATING.read_text(encoding="utf-8"))["tags"]
    F = lambda t: int((raw.get(t) or {}).get("freq", 0) or 0)   # noqa: E731

    pack = json.loads(Path("data/interactive_thumbnails.json").read_text(encoding="utf-8"))
    have = {k.split("/", 1)[1] for k in pack if "/" in k}
    axis_tags = set()
    for p in list(OUT.glob("*.txt")) + list(Path("wildcards/nsfw").glob("*.txt")):
        if p.stem.startswith("_"):
            continue
        axis_tags |= {l.strip() for l in p.read_text(encoding="utf-8").splitlines()
                      if l.strip() and not l.startswith("#")}

    COLOR = ("black", "white", "red", "blue", "green", "yellow", "pink", "purple",
             "brown", "grey", "gray", "orange", "aqua", "silver", "gold", "beige",
             "blonde", "navy", "light", "dark", "pale", "multicolored", "two-tone",
             "striped", "checkered", "plaid", "polka dot", "gradient", "rainbow")
    re_color = re.compile(r"^(" + "|".join(COLOR) + r")\b", re.I)

    add: dict[str, list[str]] = {}
    skipped = []
    for t, d in raw.items():
        g = str(d.get("group") or "")
        sg = str(d.get("subgroup") or "")
        if F(t) < CUT or t in have or t in axis_tags:
            continue
        if t not in rating:                      # Danbooru 풀에 없으면 e621
            continue
        if re_color.search(t) or is_explicit_vocab(t):
            continue
        if g == "Culture_Misc" and sg == "relationships":
            add.setdefault(RELATION_AXIS, []).append(t)
            continue
        if not g.startswith("패션"):
            continue
        key = SUB_AXIS.get(g.split(">")[-1].strip())
        if key is None:
            skipped.append((t, g))
            continue
        add.setdefault(key, []).append(t)

    for key, tags in sorted(add.items()):
        p = OUT / f"{key}.txt"
        cur = [l.strip() for l in p.read_text(encoding="utf-8").splitlines()
               if l.strip()] if p.exists() else []
        merged = cur + [t for t in sorted(tags, key=lambda x: -F(x)) if t not in cur]
        p.write_text("\n".join(merged) + "\n", encoding="utf-8")
        print(f"  {key:20s} +{len(tags):3d} -> {len(merged):4d}개  "
              f"{', '.join(sorted(tags, key=lambda x: -F(x))[:5])}")

    if RELATION_AXIS in add:
        (OUT / "_relation_axes.json").write_text(json.dumps({
            "note": ["관계 축(2명 이상). tools/thumb_fashion_gap.py 가 만든다."],
            "label": {RELATION_AXIS: RELATION_LABEL},
            "framing": {RELATION_AXIS: "full"},
        }, ensure_ascii=False), encoding="utf-8")

    if skipped:
        print(f"\n  (축을 못 정한 것 {len(skipped)}개: "
              f"{', '.join(f'{t}[{g}]' for t, g in skipped[:6])})")
    print(f"\n총 {sum(len(v) for v in add.values())}개 배정 / {len(add)}축")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
