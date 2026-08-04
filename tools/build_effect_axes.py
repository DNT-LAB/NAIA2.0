# -*- coding: utf-8 -*-
"""⚠ 이 빌더는 **그냥 돌리면 안 된다.**

축 .txt 는 더 이상 이 스크립트의 출력이 아니다. 오분류를 손으로 고쳐 온 결과가
쌓여 있어 **.txt 가 SSOT** 다. 지금 이대로 실행하면 커밋된 분류에서 태그 1개가
사라진다(2026-08-03 실측, `tools/check_axis_drift.py`).

돌려야 한다면:

    python tools/check_axis_drift.py --only build_effect_axes   # 무엇이 사라지는지 먼저 본다
    # 사라질 태그를 이 파일의 명시 배정에 옮긴 뒤에 실행하고,
    python tools/snapshot_axis_classification.py --check   # 분류가 안 어긋났는지 확인

되돌릴 근거는 `data/interactive_axis_snapshot.json` 에 있다.

이 스크립트를 남겨 두는 이유는 하나다 — 태그 사전에 새로 생긴 태그를 축으로
끌어오는 일은 아직 이것만 할 수 있다. 그때도 위 절차를 거쳐라.

---

시각효과·기호·색조 축 — wildcards/thumb/fx_*.txt + _fx_axes.json.

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
# 절단선 500 -> 149 (사용자 지시 2026-07-27). 이 아래는 한글 설명이 거의 없어
# 그림이 유일한 설명 수단이 된다 — 썸네일의 값이 오히려 큰 구간이다.
CUT = 149

AXIS_SPEC = (
    ("fx_effect", "시각 효과", "subject", ("effects",)),
    ("fx_symbol", "기호·말풍선", "subject", ("symbols",)),
    ("fx_tone",   "색조·화풍",  "subject", ("colors",)),
    # 조명은 처음에 빠져 있었다 — 위 세 서브그룹만 읽었기 때문이다. 그 결과
    # `lens flare`(24,719) · `backlighting`(24,669) · `glint`(18,535) 이 어느 축에도
    # 없어서 씬 '효과' 트리가 유일한 경로였다. 섹션 전수 조사에서 드러났다.
    ("fx_light",  "조명",      "subject", ("lighting",)),
)
# 글자 서브그룹에서 **화면에 그려지는 것**만 남긴다. 서명·워터마크·계정명은
# 그림의 요소가 아니라 메타데이터다.
TEXT_KEEP = re.compile(
    r"(speech bubble|thought bubble|emphasis lines|motion lines|spoken|text bubble"
    r"|^translated$|sound effects|onomatopoeia|^engrish text$|^english text$"
    r"|^japanese text$|^korean text$|^chinese text$|^heart censor|^censored$)")


# 다른 그룹에서 fx_effect 로 들여오는 것. 이 축의 풀은 `Composition_Meta` 의
# `effects` 서브그룹만 보므로 규칙으로는 안 잡힌다.
#
# **`thumb_view_build.py` 에서 여기로 옮겼다.** 그쪽이 이 파일에 덧붙이고 있었는데
# 이 빌더가 통째로 덮어쓰므로 다시 돌리면 사라졌다. 축의 writer 는 하나여야 한다.
IMPORTED = {
    # 움직임 묘사. `motion lines` · `motion blur` · `afterimage` · `speed lines` 가
    # 이미 이 축에 있는 그 계열인데, 형제들은 `Composition_Meta` 인데 이것만
    # `NSFW` 그룹으로 튀어 성인 도감에 갇혀 있었다(`cream on face` 와 같은 형태).
    # 여성이 뛸 때 가슴이 출렁이는 묘사다 — 성적 행위가 아니다(사용자 판단 2026-07-30).
    "bouncing breasts",
    # 초점·노출 효과. 서브그룹이 `image_composition` 이라 `effects` 풀에 없다.
    "depth of field", "bokeh", "contrast", "double exposure",
}


def main() -> int:
    import core.interactive_browse_index as ib
    from core.kr_tag_loader import load_kr_tag_records
    raw = load_kr_tag_records().raw
    idx = ib.InteractiveBrowseIndex(raw)
    F = lambda t: int((raw.get(t) or {}).get("freq", 0) or 0)   # noqa: E731

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

    # `_relational_meta` 는 중간 산출물이 아니라 **이미 처리된 제외 목록**이다.
    # `_` 규칙으로 건너뛰면 빼 둔 태그가 축으로 되돌아온다(실측 2건).
    _p = OUT / "_relational_meta.txt"
    if _p.exists():
        assigned |= {l.strip() for l in _p.read_text(encoding="utf-8").splitlines()
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
        # 개행이 든 태그는 축 파일을 왕복하지 못하고(빈 줄 + 조각으로 갈라진다)
        # 파일명도 못 만든다. `\n/` 이모티콘의 손상 판본(freq 727)이 그래서 몇 번을
        # 돌려도 '미생성 1' 로 남았다 — 정상 판본(백슬래시+n)은 따로 있고 이미 있다.
        if not tag.strip() or any(c in tag for c in "\r\n\t"):
            continue
        if F(tag) < CUT or tag in assigned:
            continue
        key = sub_axis.get(sg)
        if key is None and sg == "text" and TEXT_KEEP.search(tag):
            key = "fx_symbol"          # 말풍선·효과음은 기호와 같은 성격
        if key:
            axes.setdefault(key, []).append(tag)

    for tag in sorted(IMPORTED):
        if tag not in raw:
            raise SystemExit(f"IMPORTED: 태그 DB 에 없다 -> {tag!r}")
        if tag in assigned:
            continue                      # 다른 축이 이미 가져갔다
        if tag not in axes.setdefault("fx_effect", []):
            axes["fx_effect"].append(tag)

    # `_todo` 는 벤치가 읽는 **생성 대기열**이다. 축 파일 전체를 적으면 이미 만든
    # 것까지 다시 큐에 올라 예산을 먹고 뒤쪽 축이 통째로 잘린다(실측 1회).
    # 그래서 팩에 없는 것만 적는다.
    pack_path = Path("data/interactive_thumbnails.json")
    done = set()
    if pack_path.exists():
        done = set(json.loads(pack_path.read_text(encoding="utf-8")))

    total = 0
    (OUT / "_todo").mkdir(exist_ok=True)
    for key, _l, fr, _s in AXIS_SPEC:
        v = sorted(axes.get(key, []), key=lambda t: -F(t))
        if not v:
            continue
        (OUT / f"{key}.txt").write_text("\n".join(v) + "\n", encoding="utf-8")
        todo = [t for t in v if f"{key}/{t}" not in done]
        (OUT / "_todo" / f"{key}.txt").write_text(
            ("\n".join(todo) + "\n") if todo else "", encoding="utf-8")
        total += len(v)
        print(f"  {key:12s} {len(v):4d}  (미생성 {len(todo):3d} · {fr})  {', '.join(v[:8])}")

    (OUT / "_fx_axes.json").write_text(json.dumps(
        {"framing": {k: f for k, _l, f, _s in AXIS_SPEC},
         "label": {k: l for k, l, _f, _s in AXIS_SPEC}},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n총 {total}장 / freq>={CUT} / _fx_axes.json 기록")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
