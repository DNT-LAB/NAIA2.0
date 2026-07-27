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
CUT = 500
SUBGROUPS = ("other_animals", "cats", "birds", "insects", "fish")

AXIS_SPEC = (
    ("ani_mammal", "포유류",   "animal", ()),
    ("ani_bird",   "새",       "animal", ("birds",)),
    ("ani_bug",    "곤충·거미", "animal", ("insects",)),
    ("ani_aqua",   "물고기·수생", "animal", ("fish",)),
    ("ani_etc",    "기타 생물", "animal", ()),
)
# 포유류로 볼 이름. subgroup `other_animals`/`cats` 가 포유류와 그 외를 섞고 있다.
RE_MAMMAL = re.compile(
    r"\b(cat|dog|rabbit|mouse|rat|horse|bear|sheep|goat|cow|pig|fox|wolf|deer|tiger"
    r"|lion|panda|monkey|squirrel|hamster|ferret|bat|whale|dolphin|seal|otter"
    r"|raccoon|hedgehog|koala|kangaroo|elephant|giraffe|zebra|camel|llama|alpaca"
    r"|donkey|pony|puppy|kitten|corgi|shiba)\b")


def main() -> int:
    import core.interactive_browse_index as ib
    from core.kr_tag_loader import load_kr_tag_records
    raw = load_kr_tag_records().raw
    idx = ib.InteractiveBrowseIndex(raw)
    F = lambda t: int((raw.get(t) or {}).get("freq", 0) or 0)   # noqa: E731

    # 이미 다른 축에 있는 것은 건드리지 않는다(수인은 종족 슬롯).
    assigned = set()
    for p in OUT.glob("*.txt"):
        if p.stem.startswith("_"):
            continue
        assigned |= {l.strip() for l in p.read_text(encoding="utf-8").splitlines()
                     if l.strip()}

    pool: dict[str, str] = {}
    for group, tree in idx._tree.items():
        for sg, tags in tree.items():
            if sg in SUBGROUPS:
                for t in tags:
                    pool.setdefault(t, sg)

    sub_axis = {sg: key for key, _l, _f, subs in AXIS_SPEC for sg in subs}
    axes: dict[str, list[str]] = {}
    for tag, sg in pool.items():
        if F(tag) < CUT or tag in assigned:
            continue
        key = sub_axis.get(sg)
        if key is None:                       # other_animals / cats
            key = "ani_mammal" if RE_MAMMAL.search(tag) else "ani_etc"
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
