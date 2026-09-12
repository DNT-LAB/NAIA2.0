# -*- coding: utf-8 -*-
"""이벤트 맵 두 판의 **커버리지**를 대조한다(정책 대조는 compare_event_map_policy.py).

무엇을 답하는가
    · 어느 원본으로 지었나, 스위치 셋(정책·행 거르개·연령 하한)이 어떻게 다르나
    · 태그가 몇 개 늘었나, 어느 갈래로 늘었나, 늘어난 것 중 실제로 쓸 만한 것은 무엇인가
    · 게시물이 몇 건 늘었나(등급별)
    · 같은 질의에서 후보 목록이 어떻게 달라지나

사용법
    python tools/compare_event_map_coverage.py ^
      --base "...\\submission-20260911\\nopolicy\\event_map.naiamap" ^
      --full "...\\full-20260912\\event_map.naiamap" ^
      --out  "...\\full-20260912\\report"

산출
    REPORT.md              사람이 읽는 보고서
    coverage.json          숫자 전부
    tags_added.csv         새로 들어온 태그(관측 수 내림차순, 갈래·역할 포함)
    tags_removed.csv       빠진 태그(있으면)
    queries.md             같은 질의의 후보 목록 나란히

읽을 때 주의: 관측 수는 **같은 게시물에 함께 달린 횟수**다. 의도의 정확도가 아니다.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from core.event_map import EventMapIndex  # noqa: E402

RATINGS = ("g", "s", "q", "e")

# 두 판에 같은 질의를 넣어 본다. (핀, 등급)
PROBES = [
    (["armpits", "armpit crease"], None),
    (["kiss"], ["e"]),
    (["sex"], ["e"]),
    (["aged down"], ["e"]),
    (["school uniform"], None),
    (["blood"], None),
    (["cat ears", "maid"], None),
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fmt(n) -> str:
    return format(int(n), ",")


def posts_by_rating(idx: EventMapIndex) -> dict:
    """본문이 비지 않은 게시물을 등급별로 센다(= 실제로 맵에 남은 게시물)."""
    import numpy as np
    lengths = np.diff(idx.offsets.astype(np.int64))
    live = np.flatnonzero(lengths > 0)
    owner = idx.part_arr[live[live < idx.part_arr.size]]
    counts = np.bincount(owner, minlength=len(idx.partitions))
    out = {r: 0 for r in RATINGS}
    for pid, n in enumerate(counts.tolist()):
        out[idx.partitions[pid][0]] += n
    return out


def describe(idx: EventMapIndex, path: Path) -> dict:
    m = idx.meta
    src = m.get("source") or {}
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "built_at": m.get("built_at"),
        "source_schema": src.get("schema"),
        "source_path": src.get("path"),
        "row_guard": m.get("row_guard") or "source",
        "policy_mode": m.get("policy_mode"),
        "age_floor": m.get("age_floor") or "on",
        "color_policy": m.get("color_policy"),
        "record_encoding": m.get("record_encoding"),
        "tags": len(idx.by_name),
        "lanes": m.get("lanes") or {},
        "posts": int(m.get("records") or 0),
        "rows_scanned": m.get("rows_scanned"),
        "posts_by_rating": posts_by_rating(idx),
        "incidences": int(idx.offsets[-1]),
        "dropped": (m.get("guard") or {}).get("dropped_all_ratings", 0),
        "dropped_adult": (m.get("guard") or {}).get("dropped_adult_ratings", 0),
    }


def probe(idx: EventMapIndex, pins: list, ratings) -> dict:
    missing = [p for p in pins if idx.resolve(p) is None]
    if missing:
        return {"status": "unknown_tag", "missing": missing}
    r = idx.explore(pins, ratings=ratings, limit=8)
    return {"status": "ok", "observed_posts": r["observed_posts"],
            "elapsed_ms": r.get("elapsed_ms"),
            "candidates": [{"tag": c["tag"], "observed": c["observed"],
                            "lift": round(c.get("lift") or 0, 2),
                            "lane": c.get("lane"), "role": c.get("role")}
                           for c in r["candidates"]]}


def write_csv(path: Path, header: list, rows: list) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="이벤트 맵 두 판의 커버리지 대조")
    ap.add_argument("--base", required=True, help="기준판 event_map.naiamap")
    ap.add_argument("--full", required=True, help="대조판 event_map.naiamap")
    ap.add_argument("--out", required=True, help="보고서를 쓸 폴더")
    args = ap.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    base_path, full_path = Path(args.base).resolve(), Path(args.full).resolve()

    print("기준 : %s" % base_path)
    print("대조 : %s" % full_path)
    base, full = EventMapIndex(base_path), EventMapIndex(full_path)
    try:
        b, f = describe(base, base_path), describe(full, full_path)

        added = sorted(set(full.by_name) - set(base.by_name),
                       key=lambda n: -full.observed[full.by_name[n]])
        removed = sorted(set(base.by_name) - set(full.by_name),
                         key=lambda n: -base.observed[base.by_name[n]])
        # 새로 들어온 태그를 갈래별로 센다. 관측 5건 미만은 후보 랭킹에 오르지 못한다(min_posts).
        by_lane: dict[str, dict] = {}
        for n in added:
            t = full.by_name[n]
            row = by_lane.setdefault(full.lane.get(t) or "?", {"tags": 0, "usable": 0, "observed": 0})
            row["tags"] += 1
            row["observed"] += full.observed[t]
            if full.observed[t] >= 5:
                row["usable"] += 1

        write_csv(out / "tags_added.csv", ["tag", "observed", "lane", "role"],
                  [[n, full.observed[full.by_name[n]], full.lane.get(full.by_name[n]),
                    full.role.get(full.by_name[n])] for n in added])
        if removed:
            write_csv(out / "tags_removed.csv", ["tag", "observed_in_base", "lane", "role"],
                      [[n, base.observed[base.by_name[n]], base.lane.get(base.by_name[n]),
                        base.role.get(base.by_name[n])] for n in removed])

        probes = []
        for pins, ratings in PROBES:
            probes.append({"pins": pins, "ratings": ratings,
                           "base": probe(base, pins, ratings),
                           "full": probe(full, pins, ratings)})

        data = {"base": b, "full": f, "added": len(added), "removed": len(removed),
                "added_by_lane": by_lane, "probes": probes}
        (out / "coverage.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

        # ── REPORT.md ──────────────────────────────────────────────────────
        L = []
        A = L.append
        A("# 이벤트 맵 커버리지 대조")
        A("")
        A("| | 기준판 | 대조판 |")
        A("|---|---|---|")
        rows = [
            ("파일", base_path.name, full_path.name),
            ("크기", "%.1f MB" % (b["bytes"] / 1048576), "%.1f MB" % (f["bytes"] / 1048576)),
            ("sha256", b["sha256"][:16] + "…", f["sha256"][:16] + "…"),
            ("빌드 시각", b["built_at"], f["built_at"]),
            ("원본 스키마", b["source_schema"], f["source_schema"]),
            ("정책", b["policy_mode"], f["policy_mode"]),
            ("행 거르개", b["row_guard"], f["row_guard"]),
            ("연령 하한", b["age_floor"], f["age_floor"]),
            ("색상 제외", b["color_policy"], f["color_policy"]),
            ("본문 부호화", b["record_encoding"], f["record_encoding"]),
            ("태그", fmt(b["tags"]), fmt(f["tags"])),
            ("게시물", fmt(b["posts"]), fmt(f["posts"])),
            ("태그-게시물 연결", fmt(b["incidences"]), fmt(f["incidences"])),
        ]
        for name, x, y in rows:
            A("| %s | %s | %s |" % (name, x, y))
        for r in RATINGS:
            A("| 게시물 %s | %s | %s |"
              % (r.upper(), fmt(b["posts_by_rating"][r]), fmt(f["posts_by_rating"][r])))
        A("")
        A("## 갈래")
        A("")
        A("| 갈래 | 기준판 | 대조판 |")
        A("|---|---|---|")
        for lane in sorted(set(b["lanes"]) | set(f["lanes"]),
                           key=lambda k: -(f["lanes"].get(k) or 0)):
            A("| %s | %s | %s |" % (lane, fmt(b["lanes"].get(lane) or 0),
                                    fmt(f["lanes"].get(lane) or 0)))
        A("")
        A("## 늘어난 태그 %s개" % fmt(len(added)))
        A("")
        A("`usable` = 관측 5건 이상. 그 미만은 후보 랭킹의 문턱(min_posts)에 걸려 화면에 안 뜬다.")
        A("")
        A("| 갈래 | 태그 | usable | 태그-게시물 연결 |")
        A("|---|---|---|---|")
        for lane, row in sorted(by_lane.items(), key=lambda kv: -kv[1]["tags"]):
            A("| %s | %s | %s | %s |"
              % (lane, fmt(row["tags"]), fmt(row["usable"]), fmt(row["observed"])))
        A("")
        A("관측 수 상위 30개:")
        A("")
        A("| 태그 | 관측 | 갈래 | 역할 |")
        A("|---|---|---|---|")
        for n in added[:30]:
            t = full.by_name[n]
            A("| `%s` | %s | %s | %s |"
              % (n, fmt(full.observed[t]), full.lane.get(t), full.role.get(t)))
        A("")
        if removed:
            A("## 빠진 태그 %s개" % fmt(len(removed)))
            A("")
            A("| 태그 | 기준판 관측 | 갈래 |")
            A("|---|---|---|")
            for n in removed[:30]:
                t = base.by_name[n]
                A("| `%s` | %s | %s |" % (n, fmt(base.observed[t]), base.lane.get(t)))
            A("")
            A("전체 목록은 `tags_removed.csv`.")
        else:
            A("## 빠진 태그 없음")
            A("")
            A("기준판의 태그가 전부 대조판에 있다.")
        A("")
        A("## 같은 질의, 다른 답")
        A("")
        for p in probes:
            pins = " + ".join("`%s`" % x for x in p["pins"])
            rat = ("(%s)" % ",".join(p["ratings"]).upper()) if p["ratings"] else "(전 등급)"
            A("### %s %s" % (pins, rat))
            A("")
            for side, label in (("base", "기준판"), ("full", "대조판")):
                r = p[side]
                if r["status"] != "ok":
                    A("- %s: **핀을 못 찾는다** (%s)" % (label, ", ".join(r["missing"])))
                    continue
                A("- %s: %s건 → %s" % (label, fmt(r["observed_posts"]),
                                       ", ".join("`%s`" % c["tag"] for c in r["candidates"]) or "(없음)"))
            A("")
        (out / "REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    finally:
        base.close()
        full.close()

    print()
    print("태그 %s개 늘고 %s개 빠졌다." % (fmt(len(added)), fmt(len(removed))))
    print("보고서: %s" % (out / "REPORT.md"))


if __name__ == "__main__":
    main()
