# -*- coding: utf-8 -*-
"""동물(Creatures) 축 — wildcards/thumb/ani_*.txt + _ani_axes.json.

`animal`(61,629)·`bird`(59,167)·`cat`(39,884) 같은 **동물 자체**가 어느 축에도 없었다.
소품 탐색기가 유일한 경로였고, 그래서 그 탐색기를 뗄 수 없었다.

`cat girl`/`rabbit girl` 같은 수인은 이미 `종족·수인` 슬롯에 있다 — 여기 남은 것은
동물이다. `animal on head`/`cat on lap` 같은 **상호작용**은 자세 슬롯 소속이므로
이 축은 "화면에 이 동물이 있다" 를 보여준다.
"""
import json
import re
from pathlib import Path

OUT = Path("wildcards/thumb")
# 절단선 500 -> 149 (사용자 지시 2026-07-27). 이 아래는 한글 설명이 거의 없어
# 그림이 유일한 설명 수단이 된다 — 썸네일의 값이 오히려 큰 구간이다.
CUT = 149
# `dogs`·`reptiles` 가 빠져 있었다 — 그래서 `dog`(14,935)·`wolf`·`lizard` 가
# 동물 축 어디에도 없이 추천 글자 칩으로만 떴다(2026-08-04 전수조사).
SUBGROUPS = ("other_animals", "cats", "birds", "insects", "fish", "plants",
             "dogs", "reptiles")

# 서브그룹 밖에 있지만 이 축이 맞는 것. DB 가 엉뚱한 서브그룹에 넣어 둔 것들이다
# (`butterflyfish`·`glowing butterfly` 는 food_tags, `petals on liquid` 는 구도).
EXTRA = {
    "butterflyfish": "ani_aqua",
    "glowing butterfly": "ani_bug",
    "petals on liquid": "ani_plant",
    "white snake": "ani_etc",       # `snake` 는 reptiles 인데 이쪽은 서브그룹이 없다
}

AXIS_SPEC = (
    ("ani_mammal", "포유류",   "animal", ()),
    ("ani_bird",   "새",       "animal", ("birds",)),
    ("ani_bug",    "곤충·거미", "animal", ("insects",)),
    ("ani_aqua",   "물고기·수생", "animal", ("fish",)),
    ("ani_etc",    "기타 생물", "animal", ()),
    # 식물·꽃. `flower`(357,472)는 DB 전체에서 손꼽히는 태그인데 축이 없어
    # 탐색기로만 닿았다 — 동물과 같은 상황이었다. 프레이밍은 동물과 같다
    # (흰 배경 단독). 꽃다발·화분도 여기 둔다.
    ("ani_plant",  "식물·꽃",  "animal", ("plants",)),
)
# 포유류로 볼 이름. subgroup `other_animals`/`cats` 가 포유류와 그 외를 섞고 있다.
RE_MAMMAL = re.compile(
    r"\b(cat|dog|rabbit|mouse|rat|horse|bear|sheep|goat|cow|pig|fox|wolf|deer|tiger"
    r"|lion|panda|monkey|squirrel|hamster|ferret|bat|whale|dolphin|seal|otter"
    r"|raccoon|hedgehog|koala|kangaroo|elephant|giraffe|zebra|camel|llama|alpaca"
    r"|donkey|pony|puppy|kitten|corgi|shiba|husky|doberman|pyrenees|samoyed"
    r"|retriever|shepherd|poodle|dachshund|chihuahua)\b")


def main() -> int:
    import core.interactive_browse_index as ib
    from core.kr_tag_loader import load_kr_tag_records
    raw = load_kr_tag_records().raw
    idx = ib.InteractiveBrowseIndex(raw)
    F = lambda t: int((raw.get(t) or {}).get("freq", 0) or 0)   # noqa: E731

    # 이미 다른 축에 있는 것은 건드리지 않는다(수인은 종족 슬롯).
    # **자기 출력 파일을 읽으면 안 된다.** 두 번째 실행에서 직전 결과가 전부
    # `assigned` 로 잡혀 축이 스스로를 밀어낸다(실측: ani_mammal 27 -> 9,
    # fx_effect 135 -> 75). 이 축들이 만드는 파일은 제외한다.
    _own = {k for k, _l, _f, _s in AXIS_SPEC}
    assigned = set()
    for p in OUT.glob("*.txt"):
        if p.stem.startswith("_") or p.stem in _own:
            continue
        assigned |= {l.strip() for l in p.read_text(encoding="utf-8").splitlines()
                     if l.strip()}

    # `_relational_meta` 는 중간 산출물이 아니라 **이미 처리된 제외 목록**이다
    # (사용자 지시로 캐릭터 쪽에 넘길 `alternate *` 28개). `_` 규칙으로 건너뛰면
    # 빼 둔 태그가 축으로 되돌아온다 — 실측 2건(fx_tone / obj_weapon).
    _rm = OUT / "_relational_meta.txt"
    if _rm.exists():
        assigned |= {l.strip() for l in _rm.read_text(encoding="utf-8").splitlines()
                     if l.strip()}

    pool: dict[str, str] = {}
    for group, tree in idx._tree.items():
        for sg, tags in tree.items():
            if sg in SUBGROUPS:
                for t in tags:
                    pool.setdefault(t, sg)

    sub_axis = {sg: key for key, _l, _f, subs in AXIS_SPEC for sg in subs}
    sub_axis["reptiles"] = "ani_etc"          # 파충류는 포유류 정규식에 안 걸린다
    axes: dict[str, list[str]] = {}
    for tag, sg in pool.items():
        if F(tag) < CUT or tag in assigned:
            continue
        key = sub_axis.get(sg)
        if key is None:                       # other_animals / cats / dogs
            key = "ani_mammal" if RE_MAMMAL.search(tag) else "ani_etc"
        axes.setdefault(key, []).append(tag)
    for tag, key in EXTRA.items():
        if tag in raw and tag not in assigned and tag not in axes.get(key, []):
            axes.setdefault(key, []).append(tag)

    total = 0
    (OUT / "_todo").mkdir(exist_ok=True)
    for key, _l, fr, _s in AXIS_SPEC:
        v = sorted(axes.get(key, []), key=lambda t: -F(t))
        if not v:
            continue
        (OUT / f"{key}.txt").write_text("\n".join(v) + "\n", encoding="utf-8")
        (OUT / "_todo" / f"{key}.txt").write_text("\n".join(v) + "\n", encoding="utf-8")
        total += len(v)
        print(f"  {key:14s} {len(v):4d}  ({fr})  {', '.join(v[:8])}")

    (OUT / "_ani_axes.json").write_text(json.dumps(
        {"framing": {k: f for k, _l, f, _s in AXIS_SPEC},
         "label": {k: l for k, l, _f, _s in AXIS_SPEC}},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n총 {total}장 / freq>={CUT} / _ani_axes.json 기록")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
