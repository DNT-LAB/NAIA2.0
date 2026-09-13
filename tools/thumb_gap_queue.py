# -*- coding: utf-8 -*-
"""이벤트 맵이 드러낸 썸네일 구멍을 **기존 축에 배정해** `_todo/` 큐로 만든다.

## 왜 따로 만드나

`thumb_todo.py` 는 *축 파일 대비 팩* 을 잰다. 축 파일에 애초에 안 들어간 태그는
거기서 영원히 안 보인다 - 실제로 표시 축이 전부 DONE 인데 이벤트 맵(어휘 100,537)
에서는 4,209개가 그림 없이 글자로만 뜬다. 잣대가 다르다.

## 배정을 손으로 적지 않는다

이 저장소에서 반복된 사고가 **"목록을 두 군데에 손으로 적음"** 이다. 그래서 여기서는
지도를 만들지 않고 **이미 축에 들어가 있는 태그들의 subgroup 분포에서 되읽는다**:

    subgroup 'legwear' 의 기존 태그 99개 중 97개가 cloth_legwear 축 -> 지배 축 확정
    그 subgroup 의 구멍 태그는 같은 축으로 간다

지배율(`--dominance`)과 표본 하한(`--min-sample`)을 못 넘는 subgroup 은 **배정하지
않고 미배정으로 출력한다**. catch-all 은 금지다 - 규칙에 안 걸린 것을 아무 축에나
넣으면 그 축이 쓰레기통이 된다(노출·강조 176개 중 131개가 그렇게 망가진 전례).

## 안 넣는 것

- 빌더가 이미 제외한 것(`thumb_axes_build.EXCLUDE` 실행 결과 + 의상 빌더 제외표)
- 인원 태그(맵 갈래 `population` + `\\d+girls` 류 이름)
- 관계형 메타(`_relational_meta.txt`) · 정책 제외(`_skip.txt`) · 미렌더 확정(`_unrendered.txt`)
- 그릴 수 없는 계열(메타·스타일·미디어·텍스트·저작권 ...) - 한글 사전 대분류로 거른다
- 벤치 정의(`_bench.json`)가 없는 축 - 프레이밍이 없으면 생성 조건이 정해지지 않는다
- 이미 팩에 그림이 있는 태그

## 쓰는 법

    python tools/thumb_gap_queue.py --report           # 배정만 보고 쓰지 않는다
    python tools/thumb_gap_queue.py --write --cap 3300 # _todo/ 에 쓴다(관측수 내림차순)

`--write` 는 기존 `_todo/*.txt` 를 덮지 않고 **새 태그만 덧붙인다**(이미 있는 줄은 건너뜀).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

THUMB = ROOT / "wildcards" / "thumb"
NSFW = ROOT / "wildcards" / "nsfw"
TODO = THUMB / "_todo"
BENCH_FILE = THUMB / "_bench.json"
PACK = ROOT / "data" / "interactive_thumbnails.json"
KR_PARQUET = ROOT / "data" / "KR_tags.parquet"

# 한글 사전 대분류 중 **그림으로 만들 수 없는 것**. 썸네일은 그림이므로 여기 걸리면 뺀다.
NODRAW = {"메타", "스타일", "미디어", "텍스트", "정보", "저작권", "장르", "아트",
          "연출", "개념", "설정", "문화/기타", "서명", "미술"}
# 인원 태그 이름 규칙. 맵 갈래 `population` 이 7개뿐이라 이름으로 한 번 더 훑는다.
POP_RE = re.compile(r"^\d+\+?(girls?|boys?|others?)$"
                    r"|^(multiple |solo focus|male focus|female focus|no humans|animal focus)")
# 중간 산출물. 축이 아니다(thumb_axis_index 와 같은 판단).
NOT_AXES = {"pose_solo", "pose_multi", "pose_drop", "expression_from_pose"}

# UI 에서 태그에 닿는 길은 그리드(THUMB_TAGS) 말고도 있다. 팔레트·슬라이더·시선 버튼·
# ALT 패널로 닿는 태그는 **그림이 필요 없다** - 거기서는 칩/슬라이더로 고르지 썸네일을
# 안 쓴다. 그리드만 세고 "누락" 이라 보고했다가 사용자가 스크린샷으로 반증한 적이 있다.
REACH_EXPORTS = ("PALETTES", "SLIDERS", "CLOTH_COMBO", "CLOTH_COMBO_REV",
                 "AXIS_COLOR_TAGS", "GAZE_TARGETS", "GLOSS_TAGS", "COLOR_SWATCH",
                 "SENSITIVE_TAGS", "VIEW_GLOBAL_TAGS")
AXES_MJS = ROOT / "app" / "web" / "remote" / "js" / "features" / "interactiveAxes.mjs"
PANEL_MJS = ROOT / "app" / "web" / "remote" / "js" / "features" / "interactivePanel.mjs"

# 무늬 변형. `striped panties` 는 `panties` 그림 + 팔레트로 닿는다 - 변형마다 찍지 않는다.
# 색은 색인이 이미 뺀다(`color_exclusion_reason`). 무늬는 안 빼므로 여기서 맡는다.
PATTERN_WORDS = ("striped", "plaid", "checkered", "polka dot", "argyle", "camouflage",
                 "floral", "patterned", "multicolored", "two-tone", "gradient",
                 "print", "leopard print", "cow print", "zebra print")
# 부재 태그. 그릴 대상이 없어 렌더가 원리적으로 실패한다(실측: no bra/no panties/no shirt).
# ⚠️ `unworn *` 은 여기 해당하지 않는다 - 벗겨진 채 **존재**해서 그려진다.
ABSENCE_RE = re.compile(r"^no\s+\S")


def reach_tags() -> set[str]:
    """그리드 밖 경로로 닿는 태그. mjs 를 문자열로 훑는다(노드 없이)."""
    out: set[str] = set()
    if AXES_MJS.exists():
        text = AXES_MJS.read_text(encoding="utf-8")
        for name in REACH_EXPORTS:
            start = text.find(f"export const {name}")
            if start < 0:
                continue
            end = text.find("\nexport ", start + 1)
            chunk = text[start:end if end > 0 else len(text)]
            out |= {m for m in re.findall(r'"([^"\\\n]{2,60})"', chunk)}
            out |= {m for m in re.findall(r"'([^'\\\n]{2,60})'", chunk)}
    if PANEL_MJS.exists():   # ALT 패널은 패널이 소유한다(축 파일에 없다)
        out |= set(re.findall(r"tag:\s*'([^']+)'", PANEL_MJS.read_text(encoding="utf-8")))
    return out


def lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def excluded_tags() -> set[str]:
    """빌더가 이미 '안 만든다'고 판정한 것 전부."""
    out: set[str] = set()
    for name in ("_relational_meta.txt", "_skip.txt"):
        out |= set(lines(THUMB / name))
    for path in (THUMB / "_unrendered.txt", NSFW / "_unrendered.txt"):
        for line in lines(path):
            cols = [c.strip() for c in line.split("\t")]
            out.add(cols[1] if len(cols) >= 2 else cols[0])
    # thumb_axes_build 는 EXCLUDE 를 실행 중에 조립한다(상수만 읽으면 절반만 잡힌다).
    # --dry 로 돌려 그 판정을 그대로 받는다. 실패하면 조용히 넘어가지 않고 알린다.
    try:
        env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8")
        res = subprocess.run([sys.executable, str(ROOT / "tools" / "thumb_axes_build.py"),
                              "--threshold", "60", "--dry"],
                             capture_output=True, text=True, encoding="utf-8",
                             env=env, timeout=900)
        for line in (res.stdout or "").splitlines():
            if line.startswith("EXCLUDE 로 제외"):
                out |= {t.strip() for t in line.split(":", 1)[1].split(",") if t.strip()}
    except Exception as exc:       # noqa: BLE001
        print(f"  !! 빌더 EXCLUDE 를 못 읽었습니다({exc}) — 제외 목록이 불완전합니다.")
    return out


def axis_subgroup_map(raw: dict, dominance: float, min_sample: int):
    """기존 축 파일에서 subgroup -> 지배 축 지도를 되읽는다."""
    per_sub: dict[str, Counter] = defaultdict(Counter)
    for path in sorted(THUMB.glob("*.txt")):
        axis = path.stem
        if axis.startswith("_") or axis in NOT_AXES:
            continue
        for tag in lines(path):
            rec = raw.get(tag.lower())
            sub = (rec or {}).get("subgroup")
            if sub:
                per_sub[sub][axis] += 1
    mapping, weak = {}, {}
    for sub, counter in per_sub.items():
        axis, n = counter.most_common(1)[0]
        total = sum(counter.values())
        if total >= min_sample and n / total >= dominance:
            mapping[sub] = (axis, n / total, total)
        else:
            weak[sub] = (axis, n / total, total)
    return mapping, weak


def main() -> int:
    ap = argparse.ArgumentParser(description="이벤트 맵 구멍 -> _todo 큐")
    ap.add_argument("--index", default=str(ROOT / "NAIA-Portable" / "user-data" / "data"
                                           / "event_map" / "event_map.naiamap"))
    ap.add_argument("--cap", type=int, default=3300, help="큐에 올릴 최대 장수")
    ap.add_argument("--min-observed", type=int, default=60,
                    help="이벤트 맵 관측수 하한 (사용자 기준: 60 이상은 유의미)")
    ap.add_argument("--dominance", type=float, default=0.8)
    ap.add_argument("--min-sample", type=int, default=10)
    ap.add_argument("--report", action="store_true", help="쓰지 않고 배정만 본다")
    ap.add_argument("--dump-unassigned", default=None,
                    help="미배정 태그를 판단용 맥락과 함께 TSV 로 쓴다(사람/서브에이전트용)")
    ap.add_argument("--assign-file", default=None,
                    help="손으로 정한 배정표(TSV: 태그<TAB>축). 자동 배정에 더한다")
    ap.add_argument("--write", action="store_true", help="_todo/ 에 덧붙인다")
    args = ap.parse_args()

    import pandas as pd
    from core.event_map.index import load_index
    from core.kr_tag_loader import load_kr_tag_records

    raw = load_kr_tag_records().raw
    bench = json.loads(BENCH_FILE.read_text(encoding="utf-8"))["batches"]
    pack_tags = {k.split("/", 1)[1] for k in json.loads(PACK.read_text(encoding="utf-8"))}
    drop = excluded_tags()
    reach = reach_tags()
    print(f"그리드 밖 도달 경로 태그 {len(reach):,}개(팔레트·슬라이더·시선·ALT) 제외")
    kr = pd.read_parquet(KR_PARQUET)
    category = dict(zip(kr["tag"], kr["category"]))

    hand_assign: dict[str, str] = {}
    if args.assign_file:
        for line in lines(Path(args.assign_file)):
            cols = [c.strip() for c in line.split("\t")]
            if len(cols) >= 2 and cols[0] and cols[1]:
                hand_assign[cols[0]] = cols[1]
        print(f"손 배정표 {len(hand_assign):,}건 읽음 ({args.assign_file})")

    mapping, weak = axis_subgroup_map(raw, args.dominance, args.min_sample)
    print(f"subgroup 지도: 확정 {len(mapping)}개 / 약함(배정 안 함) {len(weak)}개")

    ix = load_index(args.index)
    assigned: dict[str, list[tuple[int, str]]] = defaultdict(list)
    unassigned: list[tuple[int, str, str]] = []
    for tid in range(ix.n_tags):
        if ix.role[tid] == "population" or not ix.eligible[tid] or ix.color[tid]:
            continue
        name = ix.by_id[tid]
        obs = ix.observed[tid]
        if obs < args.min_observed or POP_RE.match(name):
            continue
        if name in pack_tags or name in drop or name in reach:
            continue
        if ABSENCE_RE.match(name):
            continue
        # `<무늬> <기본형>` 이고 기본형에 이미 그림이 있으면 팔레트로 닿는다.
        if any(name.startswith(p + " ") and name[len(p) + 1:] in pack_tags
               for p in PATTERN_WORDS):
            continue
        cat = category.get(name) or category.get(name.lower())
        if not cat or cat.split(">")[0].strip() in NODRAW:
            continue
        rec = raw.get(name.lower())
        sub = (rec or {}).get("subgroup")
        manual = hand_assign.get(name) or hand_assign.get(name.lower())
        hit = mapping.get(sub) if sub else None
        if manual:
            if manual == "-":          # 손으로 '안 만든다'고 판정한 것
                continue
            if manual not in bench:
                print(f"  !! 배정표의 축 '{manual}' 에 벤치 정의가 없습니다 (태그 {name!r})")
                continue
            assigned[manual].append((obs, name))
            continue
        if not hit:
            unassigned.append((obs, name, sub or "(subgroup 없음)", rec))
            continue
        axis = hit[0]
        if axis not in bench:            # 프레이밍이 없으면 생성 조건이 정해지지 않는다
            unassigned.append((obs, name, f"{sub} -> {axis}(벤치 정의 없음)", rec))
            continue
        assigned[axis].append((obs, name))

    flat = sorted(((obs, axis, name) for axis, v in assigned.items() for obs, name in v),
                  reverse=True)
    queued = flat[:args.cap]
    print(f"\n배정 {len(flat):,}장 / 미배정 {len(unassigned):,}장 "
          f"-> 큐에 {len(queued):,}장 (상한 {args.cap:,})")

    per_axis = Counter(axis for _, axis, _ in queued)
    print(f"\n{'축':<22}{'장수':>6}  프레이밍")
    for axis, n in per_axis.most_common():
        print(f"{axis:<22}{n:>6}  {bench[axis].get('framing','?')}")

    print(f"\n큐 상위 25:")
    for obs, axis, name in queued[:25]:
        print(f"{obs:>9,}  {axis:<20} {name}")
    print(f"\n미배정 상위 15 (손으로 판단해야 하는 것):")
    for obs, name, why, _ in sorted(unassigned, key=lambda r: -r[0])[:15]:
        print(f"{obs:>9,}  {name:<34} {why}")

    if args.dump_unassigned:
        out = Path(args.dump_unassigned)
        out.parent.mkdir(parents=True, exist_ok=True)
        with io.open(out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("tag\tobserved\tsubgroup\tgroup\tkr_category\tdescription\n")
            for obs, name, why, rec in sorted(unassigned, key=lambda r: -r[0]):
                rec = rec or {}
                desc = str(rec.get("description") or "").replace("\t", " ").replace("\n", " ")
                cat = category.get(name) or category.get(name.lower()) or ""
                fh.write(f"{name}\t{obs}\t{why}\t{rec.get('group','')}\t{cat}\t{desc[:160]}\n")
        print(f"\n미배정 {len(unassigned):,}건 -> {out}")

    if args.write:
        TODO.mkdir(parents=True, exist_ok=True)
        added = 0
        for axis in per_axis:
            path = TODO / f"{axis}.txt"
            have = set(lines(path))
            new = [name for obs, a, name in queued if a == axis and name not in have]
            if not new:
                continue
            # 줄바꿈을 고정한다. Windows 기본으로 쓰면 기존 파일과 섞여 diff 가 통째로 뒤집힌다.
            with io.open(path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write("\n".join(new) + "\n")
            added += len(new)
            print(f"  + {axis}.txt  {len(new)}장")
        print(f"\n_todo 에 {added}장 추가.  다음: python tools/thumb_bench.py <축...>")
    else:
        print("\n(--write 를 주지 않아 아무것도 쓰지 않았습니다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
