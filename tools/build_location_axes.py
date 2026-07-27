# -*- coding: utf-8 -*-
"""배경(location) 슬롯의 축 분배 — wildcards/thumb/loc_*.txt + _loc_axes.json.

파일럿 25장으로 확인한 것(이게 이 파일의 존재 이유다):

  `scenery` 는 **실내를 죽이고 날씨를 살린다.**
    classroom + scenery -> 하늘 그림 / scenery 없이 -> 완벽한 교실 내부
    snowing  + scenery -> 설산      / scenery 없이 -> 눈사람(개념이 틀림)
  아티스트 세트(kanzarin/nns/torino aqua/ixy/epi zero)는 인물 일러스트레이터라
  풍경에서 하늘·구름이 화면을 먹는다 -> 배경 축에서는 뺀다.
  `wide shot` 은 웅장한 원경으로 끌어당긴다(forest/snowing 이 둘 다 설산) -> 안 쓴다.
  배경 '처리'(white/gradient background)는 반대로 **주체가 필요하다** — 무엇 뒤에
  있는지를 말하는 태그라 인물 없이는 의미가 없다.

그래서 프레이밍이 세 갈래다: interior(scenery 없음) / scenery / backdrop(1girl).
"""
import json
import re
from pathlib import Path

OUT = Path("wildcards/thumb")
CUT = 500

# (축, 라벨, 벤치 프레이밍, 이 축을 채우는 subgroup)
AXIS_SPEC = (
    ("loc_backdrop", "배경 처리", "backdrop", ()),      # 이름 규칙으로만 채운다
    ("loc_indoor",   "실내",      "interior", ()),      # 이름 규칙으로만 채운다
    ("loc_place",    "장소·건물", "scenery", ("locations", "real_world_locations")),
    ("loc_nature",   "자연",      "scenery", ("nature",)),
    ("loc_water",    "물",        "scenery", ("water",)),
    ("loc_sky",      "하늘·천체", "scenery", ("backgrounds",)),
    ("loc_weather",  "날씨·빛",   "scenery", ("weather", "fire")),
    ("loc_time",     "시간·계절", "scenery", ("time",)),
)

# 배경 '처리' — 장소가 아니라 배경을 어떻게 칠하느냐다. 주체가 있어야 보인다.
RE_BACKDROP = re.compile(
    r"(background$|^.* theme$|^blurry foreground$|^border$|^framed$"
    r"|^halftone|^paint splatter$|^diffraction spikes$)")
# 실내 — `scenery` 를 붙이면 창밖 하늘이 화면을 먹는다.
RE_INDOOR = re.compile(
    r"(indoors|room$|classroom|kitchen|bathroom|bedroom|office|library|hallway|corridor"
    r"|^stairs$|^window$|^curtains$|^bed$|^couch$|^desk$|^table$|^chair$|^mirror$"
    r"|floor$|^ceiling$|^tiles$|wall$|^shelf$|^bookshelf$|^locker|^shower|^bathtub"
    r"|^onsen$|^pool$|^cafe|^restaurant|^shop|^store|^church|^shrine interior)")
# 실외지만 실내 규칙에 걸리는 것 — 되돌린다.
RE_NOT_INDOOR = re.compile(r"(city|street|rooftop|stone wall|brick wall|castle wall)")


def main() -> int:
    import core.interactive_browse_index as ib
    from core.kr_tag_loader import load_kr_tag_records
    raw = load_kr_tag_records().raw
    idx = ib.InteractiveBrowseIndex(raw)
    F = lambda t: int((raw.get(t) or {}).get("freq", 0) or 0)   # noqa: E731

    pool: dict[str, str] = {}
    for s in idx.subgroups("location"):
        for g in ib.SLOT_GROUPS["location"]:
            v = idx._tree.get(g, {}).get(s["id"])
            if v:
                for t in v:
                    pool[t] = s["id"]
                break

    sub_axis = {sg: key for key, _l, _f, subs in AXIS_SPEC for sg in subs}
    axes: dict[str, list[str]] = {}
    for tag, sg in pool.items():
        if F(tag) < CUT:
            continue
        if RE_BACKDROP.search(tag):
            key = "loc_backdrop"
        elif RE_INDOOR.search(tag) and not RE_NOT_INDOOR.search(tag):
            key = "loc_indoor"
        else:
            key = sub_axis.get(sg, "loc_place")
        axes.setdefault(key, []).append(tag)

    total = 0
    for key, _l, _f, _s in AXIS_SPEC:
        v = sorted(axes.get(key, []), key=lambda t: -F(t))
        if not v:
            continue
        axes[key] = v
        (OUT / f"{key}.txt").write_text("\n".join(v) + "\n", encoding="utf-8")
        (OUT / "_todo" / f"{key}.txt").write_text("\n".join(v) + "\n", encoding="utf-8")
        total += len(v)
        print(f"  {key:16s} {len(v):4d}  ({_f})  {', '.join(v[:6])}")

    (OUT / "_loc_axes.json").write_text(json.dumps(
        {"framing": {k: f for k, _l, f, _s in AXIS_SPEC},
         "label": {k: l for k, l, _f, _s in AXIS_SPEC}},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n총 {total}장 / freq>={CUT} / _loc_axes.json 기록")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
