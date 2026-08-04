# -*- coding: utf-8 -*-
"""⚠ 이 빌더는 **그냥 돌리면 안 된다.**

축 .txt 는 더 이상 이 스크립트의 출력이 아니다. 오분류를 손으로 고쳐 온 결과가
쌓여 있어 **.txt 가 SSOT** 다. 지금 이대로 실행하면 커밋된 분류에서 태그 4개가
사라진다(2026-08-03 실측, `tools/check_axis_drift.py`).

돌려야 한다면:

    python tools/check_axis_drift.py --only build_location_axes   # 무엇이 사라지는지 먼저 본다
    # 사라질 태그를 이 파일의 명시 배정에 옮긴 뒤에 실행하고,
    python tools/snapshot_axis_classification.py --check   # 분류가 안 어긋났는지 확인

되돌릴 근거는 `data/interactive_axis_snapshot.json` 에 있다.

이 스크립트를 남겨 두는 이유는 하나다 — 태그 사전에 새로 생긴 태그를 축으로
끌어오는 일은 아직 이것만 할 수 있다. 그때도 위 절차를 거쳐라.

---

배경(location) 슬롯의 축 분배 — wildcards/thumb/loc_*.txt + _loc_axes.json.

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
# 절단선 500 -> 149 (사용자 지시 2026-07-27). 이 아래는 한글 설명이 거의 없어
# 그림이 유일한 설명 수단이 된다 — 썸네일의 값이 오히려 큰 구간이다.
CUT = 149

# (축, 라벨, 벤치 프레이밍, 이 축을 채우는 subgroup)
AXIS_SPEC = (
    ("loc_backdrop", "배경 처리", "backdrop", ()),      # 이름 규칙으로만 채운다
    ("loc_indoor",   "실내",      "interior", ()),      # 이름 규칙으로만 채운다
    ("loc_place",    "장소",      "scenery", ("locations", "real_world_locations")),
    ("loc_object",   "구조물·사물", "object", ()),      # 이름 목록으로만 채운다
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

# ── 장소 축의 3분할 (검수 실측 기반) ────────────────────────────────────────
# 1차 생성 104장을 눈으로 보고 나눴다. 이름 규칙으로는 안 갈린다 — "그 안에 서서
# 둘러볼 수 있는가" 는 데이터에 없는 구분이라 목록으로 적되 assert 로 누락을 막는다.
#
# 광경(loc_place)     하늘이 자연스럽다. 상쇄를 걸면 오히려 밋밋해진다.
# 구조물(loc_object)  화면을 못 채워 뭉게구름이 들어찼다 -> 하늘을 눌러야 한다.
# 실내(loc_indoor)    애초에 실내인데 `locations` subgroup 이라 여기 섞였다.
_TO_INDOOR = {
    "tatami", "under covers", "bath", "chalkboard", "train interior", "stage",
    "bar (place)", "shouji", "sink", "car interior", "toilet stall", "infirmary",
    "prison", "elevator", "interior", "urinal", "closet", "loaded interior",
    "sauna", "casino", "cockpit", "wrestling ring",
}
_TO_OBJECT = {
    "building", "house", "castle", "temple", "shrine", "torii", "pagoda", "tower",
    "clock tower", "lighthouse", "windmill", "apartment", "skyscraper", "bridge",
    "gate", "fence", "railing", "guard rail", "lamppost", "power lines",
    "utility pole", "smokestack", "arch", "fountain", "ferris wheel", "food stand",
    "convenience store", "bus stop", "tent", "porch", "door", "sliding doors",
    "open door", "doorway", "pov doorway", "open window", "broken window",
    "round window", "balcony", "veranda", "pool ladder", "debris", "broken glass",
    "tombstone", "beach umbrella", "neon lights", "city lights", "architecture",
    "east asian architecture", "scarlet devil mansion", "school", "train station",
    "gym", "flight deck",
}


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

    # `image_composition` 서브그룹의 `* background` 20개는 이 풀(location 그룹)에
    # 없다. 배경 처리 축은 여기 하나뿐이므로 이름 규칙으로 끌어온다.
    # (`thumb_view_build.py` 가 이 파일에 덧붙이고 있었으나, 이 빌더가 통째로
    #  덮어쓰므로 사라질 자리였다. 축의 writer 는 하나여야 한다.)
    for _t, _d in raw.items():
        if str(_d.get("subgroup", "")) not in ("image_composition", "composition"):
            continue
        if F(_t) >= CUT and RE_BACKDROP.search(_t):
            pool.setdefault(_t, "backgrounds")

    sub_axis = {sg: key for key, _l, _f, subs in AXIS_SPEC for sg in subs}
    axes: dict[str, list[str]] = {}
    for tag, sg in pool.items():
        if F(tag) < CUT:
            continue
        if tag in _TO_INDOOR:
            key = "loc_indoor"
        elif tag in _TO_OBJECT:
            key = "loc_object"
        elif RE_BACKDROP.search(tag):
            key = "loc_backdrop"
        elif RE_INDOOR.search(tag) and not RE_NOT_INDOOR.search(tag):
            key = "loc_indoor"
        else:
            key = sub_axis.get(sg, "loc_place")
        axes.setdefault(key, []).append(tag)

    # 목록에 적은 태그가 실제로 풀에 있었는지 — 오타나 절단선 변경으로 조용히 빠지면
    # 그 태그는 원래 축에 남아 잘못된 프레이밍으로 다시 찍힌다.
    _placed = {t for v in axes.values() for t in v}
    _lost = (_TO_INDOOR | _TO_OBJECT) - _placed
    assert not _lost, f"목록에 있으나 풀에서 사라진 태그: {sorted(_lost)}"

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
