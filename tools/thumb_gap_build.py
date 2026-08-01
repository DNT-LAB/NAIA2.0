# -*- coding: utf-8 -*-
"""사전 칩이 드러낸 축 공백을 메운다 — 직업·행사·기계 신설 + 기존 축 보강.

## 왜

사전 칩(추천) 전수 조사에서 그림 없는 칩 346종/1,936회가 남았다(2026-08-01,
저빈도·고유명·결함 태그를 걷어낸 뒤). 그룹별로 보니 **축이 아예 없는 개념**이
덩어리로 나왔다.

    Culture_Misc/jobs        nun 12,744 · office lady 10,849 · miko 10,073 …
    Culture_Misc/holidays    christmas 23,519 · halloween 20,256 · new year 14,169 …
    Food_Object/technology   robot 34,172 · android 10,847 · cyborg 4,838 …

직업과 명절은 **의상·상황 개념인데 어느 축에도 없었다.** 사전이 계속 권하는데
그림이 없으니 사용자는 그 태그로 갈 방법이 없다.

## 어디에 넣나

  신설  job    직업·역할     (cowboy shot — 의상이 대상이라 전신은 필요 없다)
  신설  event  행사·명절     (cowboy shot — 소품과 의상이 함께 보여야 한다)
  신설  mech   기계·사이보그 (cowboy shot — 팔·눈 등 부분 개조가 많다)
  보강  cloth_armor    pauldrons · arm guards …
  보강  body_feature   veins · fins · oni horns …
  보강  pose_hand      pov hands · between fingers …

**남의 축 파일에 직접 쓰지 않는다** — 그 축의 빌더가 통째로 덮어쓰므로 사라진다.
보강분은 `_gap_extra.json` 에 내고 각 빌더가 읽어 간다.

## 관계형 메타는 여기 없다

`official alternate costume`·`cosplay`·`adapted costume` 은 "원작과 다르다"는
뜻이라 그림으로 그릴 것이 없다. ALT 목록으로 갔다(사용자 지시).

사용: python tools/thumb_gap_build.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.kr_tag_loader import load_kr_tag_records  # noqa: E402

OUT = Path("wildcards/thumb")
CUT = 300

LABEL = {"job": "직업·역할", "event": "행사·명절", "mech": "기계·사이보그"}
FRAMING = {"job": "cloth_outfit", "event": "cloth_outfit", "mech": "cowboy"}

# 신설 축 — 서브그룹에서 파생시킨다(손으로 적지 않는다).
NEW_FROM_SUBGROUP = {
    "job": ("jobs",),
    "event": ("holidays_and_celebrations",),
    "mech": ("technology",),
}
# 서브그룹에 있어도 그림으로 구분되지 않는 것. 근거를 적는다.
NEW_SKIP = {
    "pocky day", "cat day", "bunny day", "maid day", "koishi day",
    "twintails day", "miku day", "anniversary",   # 날짜 기념일 — 그림에 안 나타난다
    "party popper",                                # 소품 축 소관
}


def main() -> int:
    raw = load_kr_tag_records().raw
    F = lambda t: int((raw.get(t) or {}).get("freq", 0) or 0)          # noqa: E731
    SG = lambda t: str((raw.get(t) or {}).get("subgroup", "") or "")   # noqa: E731

    own = set(LABEL)
    taken: dict[str, str] = {}
    for p in list(OUT.glob("*.txt")) + list(Path("wildcards/nsfw").glob("*.txt")):
        if p.stem.startswith("_") or p.stem in own:
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                taken.setdefault(line.strip(), p.stem)

    axes: dict[str, list[str]] = {}
    for key, subs in NEW_FROM_SUBGROUP.items():
        picked = [t for t in raw
                  if SG(t) in subs and F(t) >= CUT
                  and t not in taken and t not in NEW_SKIP]
        picked.sort(key=lambda x: -F(x))
        axes[key] = picked
        (OUT / f"{key}.txt").write_text("\n".join(picked) + "\n", encoding="utf-8")
        print(f"  {key:8s} {LABEL[key]:10s} {len(picked):4d}개  {', '.join(picked[:6])}")

    (OUT / "_gap_axes.json").write_text(json.dumps({
        "note": ["사전 칩이 드러낸 축 공백. tools/thumb_gap_build.py 가 만든다.",
                 "직업·행사·기계는 의상/상황 개념인데 어느 축에도 없었다."],
        "label": LABEL, "framing": FRAMING,
    }, ensure_ascii=False), encoding="utf-8")
    total = sum(len(v) for v in axes.values())
    print(f"\n신설 3축 / {total}개  (절단선 freq>={CUT})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
