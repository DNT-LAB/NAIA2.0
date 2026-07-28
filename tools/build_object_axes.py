# -*- coding: utf-8 -*-
"""사물(object) 슬롯의 축 분배 — wildcards/thumb/obj_*.txt + _obj_axes.json.

배경 섹션에서 배운 것이 그대로 적용된다: **태그가 화면을 못 채우면 NAI 가 자기
기본값으로 메운다.** 배경에서는 그 기본값이 실내=음식 정물 / 실외=뭉게구름이었다.

사물 축은 반대다 — 사물이 주체이므로 흰 배경에 물건 하나를 놓는 것이 맞다
(특징 슬롯의 `white background` 방식). 다만 **음식을 상쇄하면 안 된다** —
`food_tags` 가 181개(18%)라 배경에서 쓴 `-1:: food ::` 를 그대로 걸면 그것들이 죽는다.
그래서 음식을 별도 축으로 가르고, 상쇄는 축별로 건다.

`holding X` 와 200쌍이 겹치지만(자세 슬롯) 사물 축은 **물건 자체**를 보여준다 —
손이 없는 그림이라 용도가 다르다. 사용자 지시로 전량 생성한다.
"""
import json
from pathlib import Path

OUT = Path("wildcards/thumb")
# 절단선 500 -> 149 (사용자 지시 2026-07-27). 이 아래는 한글 설명이 거의 없어
# 그림이 유일한 설명 수단이 된다 — 썸네일의 값이 오히려 큰 구간이다.
CUT = 149

# (축, 라벨, 벤치 프레이밍, subgroup...)
AXIS_SPEC = (
    ("obj_food",      "음식·음료",  "food",   ("food_tags",)),
    ("obj_tool",      "도구·소지품", "object", ("tools",)),
    ("obj_weapon",    "무기",       "object", ("weapons",)),
    ("obj_container", "그릇·용기",  "object", ("containers",)),
    ("obj_tech",      "기계·전자",  "object", ("technology",)),
    ("obj_furniture", "가구",       "room",   ("furniture",)),
    ("obj_vehicle",   "탈것",       "vehicle", ("vehicles",)),
    ("obj_play",      "악기·놀이",  "object", ("instruments", "board_games", "cards")),
    # 아래 6개는 사물 슬롯에 소수(각 1~2개)만 얹혀 있고 전부 freq<500 이라 실제로는
    # 아무것도 안 들어온다. 그래도 적어 둔다 — assert 가 "빠진 서브그룹" 을 잡는데,
    # 이름을 안 적으면 절단선을 낮출 때 조용히 터진다.
    #   accessories/combat_actions = 소품·자세 축이 이미 담당
    #   birds/fish/other_animals   = 동물 축(별건, Creatures 그룹이 본체)
    #   medical_equipment          = 도구
    ("obj_etc",       "기타",       "object", ("etc", "insects", "art_objects",
                                              "cats", "objects", "accessories",
                                              "combat_actions", "birds", "fish",
                                              "other_animals", "medical_equipment")),
)


def main() -> int:
    import core.interactive_browse_index as ib
    from core.kr_tag_loader import load_kr_tag_records
    raw = load_kr_tag_records().raw
    idx = ib.InteractiveBrowseIndex(raw)
    F = lambda t: int((raw.get(t) or {}).get("freq", 0) or 0)   # noqa: E731

    pool: dict[str, str] = {}
    for s in idx.subgroups("object"):
        for g in ib.SLOT_GROUPS["object"]:
            v = idx._tree.get(g, {}).get(s["id"])
            if v:
                for t in v:
                    pool[t] = s["id"]
                break

    sub_axis = {sg: key for key, _l, _f, subs in AXIS_SPEC for sg in subs}
    # 서브그룹이 하나라도 빠지면 그 태그는 조용히 사라진다 — 배경/의상에서 같은
    # 실수를 반복했으므로 여기서 막는다.
    missing = {sg for sg in set(pool.values())} - set(sub_axis)
    assert not missing, f"축에 배정되지 않은 서브그룹: {sorted(missing)}"

    # 다른 슬롯이 이미 가져간 태그는 넣지 않는다. `bandages` 가 의상->부상 축으로
    # 이관됐는데 사물 풀에도 있어 두 축에 실렸고, 팩 빌더는 알파벳 순 첫 축이 이기므로
    # `obj_tool/bandages` 가 영영 안 채워졌다(생성해도 body_condition 으로 간다).
    # 동물·효과 빌더에는 이 검사가 있었는데 사물에만 없었다.
    _own = {k for k, _l, _f, _s in AXIS_SPEC}
    taken = set()
    for f in OUT.glob("*.txt"):
        if f.stem.startswith("_") or f.stem in _own:
            continue
        taken |= {l.strip() for l in f.read_text(encoding="utf-8").splitlines() if l.strip()}

    axes: dict[str, list[str]] = {}
    for tag, sg in pool.items():
        if F(tag) < CUT or tag in taken:
            continue
        axes.setdefault(sub_axis[sg], []).append(tag)

    total = 0
    (OUT / "_todo").mkdir(exist_ok=True)
    for key, _l, fr, _s in AXIS_SPEC:
        v = sorted(axes.get(key, []), key=lambda t: -F(t))
        if not v:
            continue
        axes[key] = v
        (OUT / f"{key}.txt").write_text("\n".join(v) + "\n", encoding="utf-8")
        (OUT / "_todo" / f"{key}.txt").write_text("\n".join(v) + "\n", encoding="utf-8")
        total += len(v)
        print(f"  {key:16s} {len(v):4d}  ({fr})  {', '.join(v[:6])}")

    (OUT / "_obj_axes.json").write_text(json.dumps(
        {"framing": {k: f for k, _l, f, _s in AXIS_SPEC},
         "label": {k: l for k, l, _f, _s in AXIS_SPEC}},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n총 {total}장 / freq>={CUT} / _obj_axes.json 기록")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
