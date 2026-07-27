# -*- coding: utf-8 -*-
"""시각효과·기호·색조 축 — wildcards/thumb/fx_*.txt + _fx_axes.json.

`meta` 슬롯 1,999개 중 **썸네일이 필요한 것만** 뽑는다. 실측 분해:

  시각효과 138  blurry/sparkle/petals/shadow  -> 필요
  기호     122  heart/star/cross/?            -> 필요
  색조      28  monochrome/sepia/spot color   -> 필요
  글자      84  speech bubble 는 필요, artist name/signature 는 불필요
  구도     127  full body/upper body          -> **3축 콤보 프리셋**이 담당
  인원      18  1girl/2girls/solo             -> **캐릭터 헤더**가 담당
  메타     209  comic/sketch/border/연도       -> 시각 태그가 아니다

프레이밍: 효과·기호·색조는 **주체가 있어야 보인다**(배경 처리 축과 같은 성격).
`monochrome` 을 빈 화면에 걸면 흑백 아무것도 아닌 그림이 된다.
"""
import json
import re
from pathlib import Path

OUT = Path("wildcards/thumb")
CUT = 500

AXIS_SPEC = (
    ("fx_effect", "시각 효과", "subject", ("effects",)),
    ("fx_symbol", "기호·말풍선", "subject", ("symbols",)),
    ("fx_tone",   "색조·화풍",  "subject", ("colors",)),
)
# 글자 서브그룹에서 **화면에 그려지는 것**만 남긴다. 서명·워터마크·계정명은
# 그림의 요소가 아니라 메타데이터다.
TEXT_KEEP = re.compile(
    r"(speech bubble|thought bubble|emphasis lines|motion lines|spoken|text bubble"
    r"|^translated$|sound effects|onomatopoeia|^engrish text$|^english text$"
    r"|^japanese text$|^korean text$|^chinese text$|^heart censor|^censored$)")


def main() -> int:
    import core.interactive_browse_index as ib
    from core.kr_tag_loader import load_kr_tag_records
    raw = load_kr_tag_records().raw
    idx = ib.InteractiveBrowseIndex(raw)
    F = lambda t: int((raw.get(t) or {}).get("freq", 0) or 0)   # noqa: E731

    assigned = set()
    for p in OUT.glob("*.txt"):
        if p.stem.startswith("_"):
            continue
        assigned |= {l.strip() for l in p.read_text(encoding="utf-8").splitlines()
                     if l.strip()}

    pool: dict[str, str] = {}
    for s in idx.subgroups("meta"):
        for g in ib.SLOT_GROUPS["meta"]:
            v = idx._tree.get(g, {}).get(s["id"])
            if v:
                for t in v:
                    pool[t] = s["id"]
                break

    sub_axis = {sg: key for key, _l, _f, subs in AXIS_SPEC for sg in subs}
    axes: dict[str, list[str]] = {}
    for tag, sg in pool.items():
        if F(tag) < CUT or tag in assigned:
            continue
        key = sub_axis.get(sg)
        if key is None and sg == "text" and TEXT_KEEP.search(tag):
            key = "fx_symbol"          # 말풍선·효과음은 기호와 같은 성격
        if key:
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
        print(f"  {key:12s} {len(v):4d}  ({fr})  {', '.join(v[:8])}")

    (OUT / "_fx_axes.json").write_text(json.dumps(
        {"framing": {k: f for k, _l, f, _s in AXIS_SPEC},
         "label": {k: l for k, l, _f, _s in AXIS_SPEC}},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n총 {total}장 / freq>={CUT} / _fx_axes.json 기록")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
