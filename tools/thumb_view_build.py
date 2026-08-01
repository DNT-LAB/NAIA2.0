# -*- coding: utf-8 -*-
"""구도 축 빌더 — 시점·프레이밍·시선·화면구성.

## 왜 신설하는가

태그 DB 의 `image_composition` 서브그룹 202개가 **어느 썸네일 축에도 없었다**
(실측: freq>=300 인 126개 전부 겹침 0). `full body` 480,518 · `cowboy shot`
372,799 · `from behind` 142,085 · `pov` 74,180 처럼 최상위 빈도 태그들이
통째로 빠져 있었다. 사용자가 "구도 쉽게 만든다고 넣어놨다가 생략된 것 같다"고
지적한 그 구멍이다.

## e621 어휘를 넣는 이유

성인 도감에서는 e621 계열을 `_excluded_foreign.txt` 로 뺐다 — Danbooru 학습
모델이 그 어휘를 못 그리기 때문이다. **구도는 다르다.** `front view` 165,377 ·
`first person view` 94,612 · `low-angle view` 58,791 처럼 e621 쪽 시점 어휘가
실제로 잘 먹는다는 사용자 실측이 있다(2026-07-29). freq>=300 만 쓴다.

e621 태그는 서브그룹이 구도로 안 잡혀 있어 규칙으로 못 뽑는다. 그래서
`E621_VIEW` 만 손으로 적는다 — 그 외에는 전부 DB 에서 파생시킨다.

## 축을 넷으로 쪼개는 이유

한 축에 126개를 넣으면 "몸 어디까지 보이나"(프레이밍)와 "어디서 보나"(각도)와
"어디를 보나"(시선)가 한 그리드에 섞인다. 사용자가 고를 때 셋은 각각 다른
질문이다. 의상에서 `attire` 를 4분할한 것과 같은 이유.

배경은 여기 두지 않는다 — `loc_backdrop` 이 이미 그 축이다.
"""
import json
import re
from pathlib import Path

from core.kr_tag_loader import load_kr_tag_records

OUT = Path("wildcards/thumb")
CUT = 300
SRC_SUBGROUPS = ("image_composition", "composition", "pov")

# e621 계열(source 빈칸). 서브그룹이 구도로 안 잡혀 규칙으로 못 뽑는다.
# 제외한 것: `* background`(배경 축 소관) · `*-framed eyewear`(안경) ·
# `three-quarter sleeves`(의상) · `* focus`(NSFW 부위 강조) ·
# `from behind position`(체위) · `three quarter view`(철자 변형 중복).
E621_VIEW = {
    "front view": "view_angle",          # 165,377
    "from front position": "view_angle",  # 128,276
    "first person view": "view_angle",   # 94,612
    "side view": "view_angle",           # 75,307
    "low-angle view": "view_angle",      # 58,791
    "three-quarter view": "view_angle",  # 44,560
    "high-angle view": "view_angle",     # 27,298
    "x-ray view": "view_angle",          # 6,789
    # `female pov`(2,656)는 KR 쪽에 이미 있는데 짝인 `male pov` 만 NSFW 그룹으로
    # 튀어 있다. 지금까지 고쳐온 것과 같은 그룹 배정 잡음이라 짝을 맞춘다.
    "male pov": "view_angle",            # 46,606
    "looking at partner": "view_gaze",   # 39,257
    "cropped": "view_shot",              # 9,785
    "eyes out of frame": "view_shot",    # 1,648
}

# 규칙 — 위에서부터 먼저 맞는 것이 이긴다.
RULES = (
    # 배경·초점 효과는 **소유 빌더 소관**이다. 처음엔 여기서 그 파일들에 덧붙였는데
    # `build_location_axes.py` · `build_effect_axes.py` 가 통째로 덮어써서 다시
    # 돌리면 사라질 자리였다. 여기서는 집계만 하고 파일은 건드리지 않는다.
    ("(loc_backdrop 소관)", re.compile(r"background$|^backdrop")),
    ("(fx_effect 소관)", re.compile(r"^bokeh$|^depth of field$|^double exposure$|^contrast$")),
    # 몸이 어디까지 보이나 / 어디가 잘렸나.
    ("view_shot", re.compile(
        r"\bshot$|^(full|upper|lower) body$|out of frame|^cropped|^crop\b"
        r"|boxed$|^portrait$|^close-up$|^round image$|^rounded corners$|^mugshot$")),
    # 카메라가 어디에 있나.
    ("view_angle", re.compile(
        r"^from |angle$|\bview$|^perspective$|foreshortening|^pov$|pov$"
        r"|straight-on|^profile$|^sideways$|^isometric$|vanishing point")),
    # 시선이 어디로 가나.
    ("view_gaze", re.compile(r"^looking |^facing |^eye contact$|look$|^shaded face$")),
    # 화면을 어떻게 나누나 / 같은 대상을 몇 개 놓나.
    ("view_layout", re.compile(
        r"^multiple |inset$|^split |symmetry$|^collage$|^side-by-side$|lineup$"
        r"|^turnaround$|comparison$|^sequential$|^clone$|^\d+others$"
        r"|^group picture$|formation$|^negative space$|^tachi-e$|^zoom layer$"
        r"|^selfie$|^lineart$|^grid |^harem$|^surrounded$|^sandwiched$"
        # 처음 돌렸을 때 미분류로 샌 화면 구성들. 나머지 미분류는 구도가 아니라
        # 밈·상황이라(`if they mated` · `odd one out`) 규칙을 넓히지 않는다.
        r"|^cross-section$|^framed$|^viewfinder$|^finger frame$|^behind another$")),
)

LABEL = {
    "view_shot": "프레이밍",
    "view_angle": "시점·각도",
    "view_gaze": "시선",
    "view_layout": "화면 구성",
}


def main() -> int:
    raw = load_kr_tag_records().raw
    F = lambda t: int((raw.get(t) or {}).get("freq", 0) or 0)  # noqa: E731

    # 이미 다른 축이 가져간 태그는 건드리지 않는다 — 팩 키가 `<축>/<태그>` 하나뿐이라
    # 두 축에 같은 태그가 있으면 뒤쪽이 영영 안 찬다(`bandages` · `hand in another's
    # panties` 로 두 번 겪었다).
    # **성인 도감도 봐야 한다.** `wildcards/thumb/` 만 보면 `futanari pov` 가
    # `nsfw_pairing` 과 `view_angle` 양쪽에 들어간다(실측). 성인 도감 빌더가 SFW 축을
    # 안 봐서 `hand in another's panties` 가 겹쳤던 것의 정확한 반대 방향이다.
    # **자기 출력 파일은 빼야 한다.** 두 번째 실행에서 직전 결과가 전부 `taken` 으로
    # 잡혀 축이 0개가 된다(실측). 이 프로젝트에서 일곱 번째 겪는 함정이라
    # 목록을 손으로 적지 않고 `LABEL` 키에서 파생시킨다.
    _own = set(LABEL)
    taken: dict[str, str] = {}
    for p in list(OUT.glob("*.txt")) + list(Path("wildcards/nsfw").glob("*.txt")):
        if p.stem.startswith("_") or p.stem in _own:
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                taken.setdefault(line.strip(), p.stem)

    pool: dict[str, str] = {}          # 태그 -> 강제 배정(없으면 규칙)
    for t, d in raw.items():
        if str(d.get("subgroup", "") or "") in SRC_SUBGROUPS and F(t) >= CUT:
            pool[t] = ""
    for t, dest in E621_VIEW.items():
        if t not in raw:
            raise SystemExit(f"E621_VIEW: 태그 DB 에 없다 -> {t!r}")
        if F(t) < CUT:
            raise SystemExit(f"E621_VIEW: freq<{CUT} -> {t!r} ({F(t)})")
        pool[t] = dest

    axes: dict[str, list[str]] = {k: [] for k in LABEL}
    extra: dict[str, list[str]] = {}   # 기존 축(loc_backdrop/fx_effect)에 덧붙일 것
    unmatched: list[str] = []
    skipped: list[tuple[str, str]] = []
    for t in sorted(pool, key=lambda x: -F(x)):
        if t in taken:
            skipped.append((t, taken[t]))
            continue
        dest = pool[t]
        if not dest:
            for key, rx in RULES:
                if rx.search(t):
                    dest = key
                    break
        if not dest:
            unmatched.append(t)
        elif dest in axes:
            axes[dest].append(t)
        else:
            extra.setdefault(dest, []).append(t)

    for k, v in axes.items():
        (OUT / f"{k}.txt").write_text("\n".join(v) + "\n", encoding="utf-8")
    # 남의 축에는 쓰지 않는다 — 그 축의 빌더가 통째로 덮어쓰므로 사라진다.

    (OUT / "_view_axes.json").write_text(
        json.dumps({"label": LABEL, "framing": {k: "subject" for k in LABEL}},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"구도 풀 {len(pool)}개 (DB 서브그룹 {len(pool)-len(E621_VIEW)} + e621 {len(E621_VIEW)}) / 절단선 freq>={CUT}")
    for k, v in axes.items():
        print(f"  {k:<14}{LABEL[k]:<10}{len(v):>4}  {', '.join(v[:6])}")
    for k, v in extra.items():
        print(f"  -> {k:<22}{len(v):>4} (다른 빌더 소관, 여기서 쓰지 않음)")
    if skipped:
        print(f"  이미 다른 축이 가져감 {len(skipped)}: {skipped[:6]}")
    # 미분류는 숨기지 않는다 — 목록으로 남겨야 "이건 왜 없지" 를 다시 조사하지 않는다.
    (OUT / "_view_unmatched.txt").write_text("\n".join(unmatched) + "\n", encoding="utf-8")
    print(f"  미분류 {len(unmatched)}개 -> _view_unmatched.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
