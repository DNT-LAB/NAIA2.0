# -*- coding: utf-8 -*-
"""정책판(--policy full)과 무정책판(--policy none) 이벤트 맵 색인을 비교해 보고서를 쓴다.

사용법
    python tools/compare_event_map_policy.py --policy <full.naiamap> --nopolicy <none.naiamap> --out <폴더>

만드는 것 (--out 폴더)
    REPORT.md                 사람이 읽는 보고서 (무엇을 뺐나 · 어디를 고치나 · 질의 비교)
    compare.json              기계가 읽는 요약
    tags_post_block.csv       게시물째 버리게 만든 태그 - 규칙 · 등급별 버린 게시물 수
    tags_never_candidate.csv  정책판에서 후보로 안 내는 태그(무정책판에만 있다)
    tags_color.csv            질의 시점 색상 제외 태그(두 판 모두 색인에는 있다)
    tags_color_preserved.csv  색 단어가 들어 있지만 일부러 살린 태그
    tags_source_excluded.csv  원본 DB 단계에서 이미 후보가 아니었던 태그(두 판 공통)

읽기만 한다. 원본 관측 DB 경로는 색인 meta 에 적힌 것을 쓴다(--source 로 바꿀 수 있다).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from core.event_map import EventMapIndex  # noqa: E402
from core.event_map import policy as P  # noqa: E402

RATINGS = "gsqe"
PROBES = [
    ("armpits", [], None),
    ("armpits,armpit crease", [], None),
    ("stretching", [], None),
    ("kiss", [], ["e"]),
    ("sex", [], ["e"]),
    ("hug", [], ["q", "e"]),
    ("blood", [], None),
    ("school uniform", [], None),
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 << 20), b""):
            h.update(block)
    return h.hexdigest()


def posts_by_rating(idx: EventMapIndex) -> dict:
    import numpy as np
    lengths = np.diff(idx.offsets.astype(np.int64))
    live = np.flatnonzero(lengths > 0)
    owner = idx.part_arr[live[live < idx.part_arr.size]]
    counts = np.bincount(owner, minlength=len(idx.partitions))
    out = {r: 0 for r in RATINGS}
    for pid, n in enumerate(counts.tolist()):
        out[idx.partitions[pid][0]] += n
    return out


def line_of(pattern: str) -> int:
    """policy.py 에서 그 이름이 정의된 줄. 보고서의 '어디를 고치나' 가 늘 맞게."""
    for no, line in enumerate(Path(P.__file__).read_text(encoding="utf-8").splitlines(), 1):
        if re.match(pattern, line):
            return no
    return 0


def write_csv(path: Path, header: list, rows: list) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def fmt(n) -> str:
    return format(int(n), ",")


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="정책판/무정책판 이벤트 맵 비교 보고서")
    ap.add_argument("--policy", required=True, help="--policy full 로 만든 event_map.naiamap")
    ap.add_argument("--nopolicy", required=True, help="--policy none 으로 만든 event_map.naiamap")
    ap.add_argument("--out", required=True, help="보고서를 쓸 폴더")
    ap.add_argument("--source", help="원본 관측 DB (기본: 색인 meta 에 적힌 경로)")
    args = ap.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    pf, nf = Path(args.policy).resolve(), Path(args.nopolicy).resolve()
    A = EventMapIndex(pf)          # 정책판
    B = EventMapIndex(nf)          # 무정책판
    if A.meta.get("policy_mode") != "full" or B.meta.get("policy_mode") != "none":
        raise SystemExit("판이 뒤바뀌었거나 정책 표시가 없다: %s / %s"
                         % (A.meta.get("policy_mode"), B.meta.get("policy_mode")))
    src_path = Path(args.source or A.meta["source"]["path"])
    src = sqlite3.connect(src_path.as_uri() + "?mode=ro", uri=True)
    src_details = {n: json.loads(d) for n, d in src.execute("SELECT name,details FROM tags")}
    src_audit = A.meta["source"].get("source_audit") or {}
    print("읽음: 정책판 %s · 무정책판 %s · 원본 %s" % (pf.name, nf.name, src_path.name))

    # ── 1. 크기 · 해시 ──────────────────────────────────────────────────────
    files = {}
    for label, path in (("policy", pf), ("nopolicy", nf)):
        files[label] = {"path": str(path), "mb": round(path.stat().st_size / 1048576, 1),
                        "sha256": sha256(path)}

    # ── 2. 어휘 차이 ────────────────────────────────────────────────────────
    va, vb = set(A.by_name), set(B.by_name)
    only_b = sorted(vb - va, key=lambda t: -B.observed[B.by_name[t]])
    only_a = sorted(va - vb)
    if only_a:
        print("⚠️ 정책판에만 있는 태그가 있다(예상 밖): %s" % only_a[:10])
    role_count = lambda idx: Counter(idx.role[t] for t in idx.by_id)  # noqa: E731

    # 무정책판에만 있는 태그 = 정책이 후보에서 뺀 것. 이유를 원본 소분류로 가른다.
    never_rows = []
    for t in only_b:
        tid = B.by_name[t]
        d = src_details.get(t, {})
        sub = d.get("original_subgroup")
        rule = P.post_block_rule(t, sub, "full")
        why = ("게시물째 버림(%s)" % rule) if rule else "후보 제외 갈래(NEVER_CANDIDATE_SUBGROUPS)"
        never_rows.append([t, B.observed[tid], sub or "", B.role[tid], why])

    # 색상(질의 시점) - 두 판 모두 색인에는 있고, 정책판만 후보·뽑기에서 뺀다.
    color_rows = []
    for t in sorted(va, key=lambda t: -A.observed[A.by_name[t]]):
        reason = P.color_exclusion_reason(t)
        if reason:
            tid = A.by_name[t]
            color_rows.append([t, A.observed[tid], reason, A.role[tid], A.lane[tid]])
    preserved_rows = [[t, A.observed[A.by_name[t]] if t in A.by_name else 0]
                      for t in sorted(P.PRESERVE_TAGS)]

    # ── 3. 게시물 거르개 ─────────────────────────────────────────────────────
    ga, gb = A.meta["guard"], B.meta["guard"]
    block_rows = []
    for tag, per in sorted(ga["by_tag"].items(), key=lambda kv: -sum(kv[1].values())):
        sub = src_details.get(tag, {}).get("original_subgroup")
        rule = P.post_block_rule(tag, sub, "full")
        scope = P.adult_post_block(tag, sub, "full")
        in_b = gb["by_tag"].get(tag, {})
        # 원본 소분류가 금기·고어·어두운 내용이 아닌데 **이름 정규식으로만** 걸린 것 = 오탐 검토 대상
        name_only = rule in ("always_block", "adult_block_name") and sub not in (
            "taboo", "gore", "dark_content")
        block_rows.append([tag, rule, "전 등급" if scope == "all" else "Q/E",
                           sub or "", *[per.get(r, 0) for r in RATINGS], sum(per.values()),
                           "예" if in_b else "아니오", "예" if name_only else ""])

    pa, pb = posts_by_rating(A), posts_by_rating(B)

    # ── 4. 원본 단계 제외(두 판 공통) ─────────────────────────────────────────
    src_reason = Counter()
    src_rows = []
    for name, d in src_details.items():
        if d.get("preset_eligible") or d.get("reason") == "outside_general_prompt_projection":
            continue
        src_reason[d.get("reason")] += 1
        src_rows.append([name, d.get("reason"), d.get("original_group") or "",
                         d.get("original_subgroup") or "", d.get("admitted_posts") or 0])
    src_rows.sort(key=lambda r: (r[1], -int(r[4])))

    # ── 5. 질의 비교 ────────────────────────────────────────────────────────
    # ⚠️ scan_cap=0 - 표본 없이 교집합 전체를 센다. 표본으로 세면 두 판의 게시물이 수백 건만
    #    달라도 뜨는 표본이 달라져 순위가 흔들리고, 그 흔들림이 '정책 차이' 로 잘못 읽힌다
    #    (처음 뽑은 보고서에서 `uterus` 가 무정책판에만 있는 것처럼 나왔다 - 두 판 어휘에 다 있다).
    probes = []
    for pins, exclude, ratings in PROBES:
        pl = pins.split(",")
        ra = A.explore(pl, exclude=exclude, ratings=ratings, limit=12, scan_cap=0)
        rb = B.explore(pl, exclude=exclude, ratings=ratings, limit=12, scan_cap=0)
        ta = [c["tag"] for c in ra["candidates"]]
        tb = [c["tag"] for c in rb["candidates"]]
        sa = A.sample(pl, exclude=exclude, ratings=ratings, n=200, seed=7)
        sb = B.sample(pl, exclude=exclude, ratings=ratings, n=200, seed=7)
        avg = lambda s, f=len: (sum(f(x["tags"]) for x in s["samples"]) / len(s["samples"])  # noqa: E731
                                if s["samples"] else 0)
        n_color = lambda tags: sum(1 for t in tags if P.color_exclusion_reason(t))  # noqa: E731
        diff = [t for t in tb if t not in ta]
        # 정책판이 **뺀** 것(어휘에 없음 · 색상) 과, 두 판 어휘에 다 있는데 **순위만** 밀린 것을 가른다.
        removed = [t for t in diff if t not in A.by_name or A.color[A.by_name[t]]]
        shifted = [t for t in diff if t not in removed]
        probes.append({
            "pins": pl, "ratings": ratings or [],
            "status": [ra["status"], rb["status"]],
            "observed": [ra["observed_posts"], rb["observed_posts"]],
            "top_policy": ta, "top_nopolicy": tb,
            "only_nopolicy_removed_by_policy": removed,
            "only_nopolicy_rank_shift": shifted,
            "only_policy": [t for t in ta if t not in tb],
            "sample_avg_tags": [round(avg(sa), 1), round(avg(sb), 1)],
            "sample_avg_color_tags": [round(avg(sa, n_color), 1), round(avg(sb, n_color), 1)],
            "sample_example_nopolicy": sb["samples"][0]["prompt"] if sb["samples"] else "",
        })

    # ── CSV ────────────────────────────────────────────────────────────────
    write_csv(out / "tags_post_block.csv",
              ["tag", "rule", "scope", "source_subgroup", "posts_g", "posts_s", "posts_q", "posts_e",
               "posts_total(겹침 포함)", "무정책판에서도 버림", "이름으로만 걸림(오탐 검토)"], block_rows)
    write_csv(out / "tags_never_candidate.csv",
              ["tag", "observed_in_nopolicy", "source_subgroup", "role_in_nopolicy", "why_excluded_in_policy"],
              never_rows)
    write_csv(out / "tags_color.csv", ["tag", "observed", "reason", "role", "lane"], color_rows)
    write_csv(out / "tags_color_preserved.csv", ["tag", "observed"], preserved_rows)
    write_csv(out / "tags_source_excluded.csv",
              ["tag", "source_reason", "source_group", "source_subgroup", "source_admitted_posts"], src_rows)

    summary = {
        "files": files,
        "policy": {"mode": "full", "tags": A.n_tags, "roles": role_count(A), "records": A.total_posts,
                   "records_by_rating": pa, "guard": {k: v for k, v in ga.items() if k != "by_tag"}},
        "nopolicy": {"mode": "none", "tags": B.n_tags, "roles": role_count(B), "records": B.total_posts,
                     "records_by_rating": pb, "guard": {k: v for k, v in gb.items() if k != "by_tag"}},
        "vocab_only_in_nopolicy": len(only_b), "vocab_only_in_policy": len(only_a),
        "color_tags_in_vocab": len(color_rows),
        "source_excluded_by_reason": dict(src_reason),
        "source_audit": src_audit,
        "probes": probes,
    }
    (out / "compare.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── REPORT.md ──────────────────────────────────────────────────────────
    L = []
    w = L.append
    rel = lambda p: str(Path(p).relative_to(REPO)).replace("\\", "/")  # noqa: E731
    pol = rel(P.__file__)
    w("# 이벤트 맵 정책판 / 무정책판 비교 보고서")
    w("")
    w("작성: %s · 원본: `%s`" % (A.meta.get("built_at", ""), src_path.name))
    w("")
    w("## 1. 제출물")
    w("")
    w("| 판 | 파일 | 크기 | SHA-256 |")
    w("|---|---|---:|---|")
    for label, name in (("policy", "정책판 (`--policy full`)"), ("nopolicy", "무정책판 (`--policy none`)")):
        f = files[label]
        w("| %s | `%s` | %s MB | `%s` |" % (name, Path(f["path"]).name, f["mb"], f["sha256"]))
    w("")
    w("두 파일은 형식이 같습니다(`.naiamap`, `core/event_map/pack.py`). 같은 리더(`core/event_map/index.py`)로 열리고,"
      " 색인 meta 의 `policy_mode` 가 `full` / `none` 으로 다릅니다.")
    w("")
    w("## 2. 한눈에")
    w("")
    w("| | 정책판 | 무정책판 | 차이 |")
    w("|---|---:|---:|---:|")
    w("| 태그(어휘) | %s | %s | %+d |" % (fmt(A.n_tags), fmt(B.n_tags), B.n_tags - A.n_tags))
    w("| 게시물 | %s | %s | %+d |" % (fmt(A.total_posts), fmt(B.total_posts), B.total_posts - A.total_posts))
    for r in RATINGS:
        w("| └ %s 등급 | %s | %s | %+d |" % (r.upper(), fmt(pa[r]), fmt(pb[r]), pb[r] - pa[r]))
    w("| 게시물째 버린 수 | %s | %s | |" % (fmt(ga["dropped_all_ratings"] + ga["dropped_adult_ratings"]),
                                        fmt(gb["dropped_all_ratings"] + gb["dropped_adult_ratings"])))
    w("| 색상 제외(질의 시점) | 켬 (%s개) | 끔 | |" % fmt(len(color_rows)))
    w("")
    same = sum(1 for pr in probes
               if not pr["only_nopolicy_removed_by_policy"] and not pr["only_nopolicy_rank_shift"])
    avg_color = sum(pr["sample_avg_color_tags"][1] for pr in probes) / max(len(probes), 1)
    drop_gap = (ga["dropped_all_ratings"] + ga["dropped_adult_ratings"]
                - gb["dropped_all_ratings"] - gb["dropped_adult_ratings"])
    w("**요약.** 대표 질의 %d개 중 %d개는 상위 12개 후보가 두 판에서 같습니다. 두 판의 차이는 주로 세 가지입니다:"
      " (1) 무정책판에서 뽑은 실제 조합에는 **색상 태그가 평균 %.1f개** 더 들어갑니다,"
      " (2) 금기·고어·검열·기호 태그 **%d개**가 후보로 열립니다(`adult_taboo` 등 별도 갈래),"
      " (3) 정책판이 게시물 **%s건**(전체의 %.2f%%)을 더 버립니다."
      % (len(probes), same, avg_color, len(only_b), fmt(drop_gap), 100 * drop_gap / max(B.total_posts, 1)))
    w("")
    w("## 3. 무정책판에서 끈 것 — 정책판에만 걸리는 규칙")
    w("")
    w("정의는 모두 `%s` 에 있습니다." % pol)
    w("")
    w("| 규칙 | 정의 위치 | 걸리는 때 | 효과 | 정책판에서 빠진 양 |")
    w("|---|---|---|---|---:|")
    br = ga.get("by_rule", {})
    total = lambda d: sum(d.values()) if d else 0  # noqa: E731
    w("| 색상 제외 | `%s:%d` COLOR_PREFIX · `:%d` COLOR_TARGETS · `:%d` COLOR_ONLY_TAGS · `:%d` PRESERVE_TAGS"
      " | **질의 시점** | 후보·뽑기에서 색상 태그를 뺀다(색인에는 남는다) | 태그 %s개 |"
      % (pol, line_of(r"^COLOR_PREFIX"), line_of(r"^COLOR_TARGETS"), line_of(r"^COLOR_ONLY_TAGS"),
         line_of(r"^PRESERVE_TAGS"), fmt(len(color_rows))))
    w("| 게시물 거르개 · 전 등급 | `%s:%d` ALWAYS_BLOCK_RE | 빌드 시점 | 그 태그가 달린 게시물을 모든 등급에서 버린다"
      " | 게시물 %s건 |" % (pol, line_of(r"^ALWAYS_BLOCK_RE"), fmt(total(br.get("always_block")))))
    w("| 게시물 거르개 · Q/E (이름) | `%s:%d` ADULT_BLOCK_RE | 빌드 시점 | Q/E 게시물만 버린다 | 게시물 %s건 |"
      % (pol, line_of(r"^ADULT_BLOCK_RE"), fmt(total(br.get("adult_block_name")))))
    w("| 게시물 거르개 · Q/E (소분류) | `%s:%d` ADULT_BLOCK_SUBGROUPS | 빌드 시점 | Q/E 게시물만 버린다 | 게시물 %s건 |"
      % (pol, line_of(r"^ADULT_BLOCK_SUBGROUPS"), fmt(total(br.get("adult_block_subgroup")))))
    n_nc = sum(1 for r in never_rows if r[4].startswith("후보 제외"))
    w("| 후보 제외 갈래 | `%s:%d` NEVER_CANDIDATE_SUBGROUPS | 빌드 시점 | 태그를 어휘에서 뺀다(게시물은 남는다) | 태그 %s개 |"
      % (pol, line_of(r"^NEVER_CANDIDATE_SUBGROUPS"), fmt(n_nc)))
    w("")
    drop_a = ga["dropped_all_ratings"] + ga["dropped_adult_ratings"]
    drop_b = gb["dropped_all_ratings"] + gb["dropped_adult_ratings"]
    w("규칙별 게시물 수는 겹침을 포함해 셉니다(한 게시물이 두 규칙에 걸리면 두 번). 실제로 버린 게시물은 정책판 %s건,"
      " 무정책판 %s건(연령 하한뿐)이고, **정책 때문에 더 버린 게시물은 %s건**입니다. 게시물 수 차이(%s)가 이보다"
      " %s건 큰 것은, 무정책판에서 열린 태그 %s개 말고는 맵 태그가 없던 게시물이 무정책판에서만 게시물로 세어지기 때문입니다."
      % (fmt(drop_a), fmt(drop_b), fmt(drop_a - drop_b), fmt(B.total_posts - A.total_posts),
         fmt((B.total_posts - A.total_posts) - (drop_a - drop_b)), fmt(len(only_b))))
    w("")
    w("무정책판에서는 정책판이 후보에서 뺀 태그 %s개가 어휘에 들어가고, 갈래 이름이 따로 붙습니다:"
      " `adult_taboo` · `adult_gore` · `adult_dark` · `adult_meta` (`%s:%d` UNPOLICED_ROLE_BY_SUBGROUP)."
      " 시험하는 쪽에서 갈래로 거를 수 있습니다." % (fmt(len(only_b)), pol, line_of(r"^UNPOLICED_ROLE_BY_SUBGROUP")))
    w("")
    w("## 4. 두 판 모두에서 빠진 것 — 이 두 판의 스위치 밖인 것")
    w("")
    w("| 무엇 | 양 | 왜 두 판 모두 | 어디 |")
    w("|---|---:|---|---|")
    age_a, age_b = total(br.get("age_floor")), total(gb.get("by_rule", {}).get("age_floor"))
    if age_a != age_b:
        print("⚠️ 연령 하한 건수가 두 판에서 다르다: %d / %d" % (age_a, age_b))
    w("| 연령 하한: Q/E 게시물의 `aged down` | 게시물 %s건 | 이 두 판은 켠 채로 지었다."
      " 빌더의 `--age-floor off` 로 끌 수 있다(2026-09-12 테스터 이의로 추가) |"
      " `%s:%d` AGE_FLOOR_RE |" % (fmt(age_b), pol, line_of(r"^AGE_FLOOR_RE")))
    w("| 원본 DB 수용 거르개(연령 위험어 · rape/guro/ryona/scat/incest/bestiality/molest/necro/torture/snuff 등) |"
      " 게시물 %s건 | 원본 관측 DB 가 애초에 받지 않아 records 에 없다. Full 코퍼스"
      "(`tag-corpus-full-175-v1`)를 원본으로 주고 빌더의 `--guard age|none` 으로 열 수 있다 |"
      " 인계 꾸러미 `harness/tag_harness/scene_events.py` row_blocked |" % fmt(src_audit.get("row_guard_excluded", 0)))
    for reason, n in src_reason.most_common():
        w("| 원본 분류: `%s` | 태그 %s개 | 원본 분류기가 후보로 두지 않았다(이 도구의 정책이 아니다) | 인계 꾸러미 classify() |"
          % (reason, fmt(n)))
    w("")
    w("원본 분류로 빠진 태그 전체는 `tags_source_excluded.csv` 에 있습니다. `unknown_source_classification` 은 원본 태그 사전이"
      " 분류하지 못한 태그(예: `brown eyes`, `censored`)라, 뽑은 실제 조합에도 들어가지 않습니다."
      " Full 코퍼스로 지으면 이 태그들도 후보가 됩니다(어휘 16,310 -> 100,537)."
      " 대조는 `tools/compare_event_map_coverage.py`.")
    w("")
    w("## 5. 질의 비교")
    w("")
    w("같은 질의를 두 판에 던졌습니다. 후보는 **표본 없이** 교집합 전체로 센 상위 12개, 뽑기는 무작위 200개 평균입니다."
      " 무정책판에만 나온 후보는 **정책이 뺀 것**(정책판 어휘에 없거나 색상)과 **순위만 밀린 것**(두 판 어휘에 다 있다)으로 나눴습니다.")
    w("")
    for pr in probes:
        w("**`%s`**%s — 관측 정책판 %s건 / 무정책판 %s건 · 뽑은 조합 평균 태그 %s / %s개 (그중 색상 %s / %s개)"
          % (" + ".join(pr["pins"]), (" (등급 %s)" % ",".join(r.upper() for r in pr["ratings"])) if pr["ratings"] else "",
             fmt(pr["observed"][0]), fmt(pr["observed"][1]), pr["sample_avg_tags"][0], pr["sample_avg_tags"][1],
             pr["sample_avg_color_tags"][0], pr["sample_avg_color_tags"][1]))
        w("")
        w("- 정책판 상위: %s" % ", ".join(pr["top_policy"]))
        w("- 무정책판 상위: %s" % ", ".join(pr["top_nopolicy"]))
        if pr["only_nopolicy_removed_by_policy"]:
            w("- 무정책판에만 — 정책이 뺀 것: **%s**" % ", ".join(pr["only_nopolicy_removed_by_policy"]))
        if pr["only_nopolicy_rank_shift"]:
            w("- 무정책판에만 — 순위만 밀림: %s" % ", ".join(pr["only_nopolicy_rank_shift"]))
        if not pr["only_nopolicy_removed_by_policy"] and not pr["only_nopolicy_rank_shift"]:
            w("- 상위 12개 차이 없음")
        w("")
    w("## 6. 추가 · 제거하려면")
    w("")
    w("| 하고 싶은 것 | 고칠 곳 | 다시 빌드 |")
    w("|---|---|---|")
    w("| 색상 태그 하나를 **살리기** | `%s:%d` PRESERVE_TAGS 에 이름 추가 | 필요 없음(질의 시점) — 서버만 다시 띄우면 된다 |"
      % (pol, line_of(r"^PRESERVE_TAGS")))
    w("| 색상 태그를 **더 빼기** | 색 단어+대상이면 `:%d` COLOR_TARGETS 에 대상 추가, 통째로 색이면 `:%d` COLOR_ONLY_TAGS | 필요 없음 |"
      % (line_of(r"^COLOR_TARGETS"), line_of(r"^COLOR_ONLY_TAGS")))
    w("| 태그가 달린 게시물을 **모든 등급에서 버리기** | `:%d` ALWAYS_BLOCK_RE 정규식에 추가 | 필요 |" % line_of(r"^ALWAYS_BLOCK_RE"))
    w("| **Q/E 에서만** 버리기 | 태그 이름이면 `:%d` ADULT_BLOCK_RE, 원본 소분류 통째로면 `:%d` ADULT_BLOCK_SUBGROUPS | 필요 |"
      % (line_of(r"^ADULT_BLOCK_RE"), line_of(r"^ADULT_BLOCK_SUBGROUPS")))
    w("| 게시물은 두고 **후보로만 안 내기** | `:%d` NEVER_CANDIDATE_SUBGROUPS (원본 소분류 단위) | 필요 |"
      % line_of(r"^NEVER_CANDIDATE_SUBGROUPS"))
    w("| 막아 둔 것을 **다시 열기** | 위 목록에서 해당 항목을 지운다 | 필요(색상은 불필요) |")
    w("| 규칙을 통째로 끄고 비교하기 | 빌더 `--policy none` | — |")
    w("")
    w("빌드: `python tools/build_event_map_index.py --source <scene_events.175.sqlite3> --out-dir <폴더> --policy full|none`"
      " (4분 안팎). 이 보고서: `python tools/compare_event_map_policy.py --policy <full> --nopolicy <none> --out <폴더>`.")
    w("")
    w("⚠️ 정규식은 **단어 경계**로 겁니다. `\\brape\\b` 가 `raped` 를 못 잡아 새어 나온 것이 확장 규칙의 출발점이었습니다 —"
      " 새 이름을 넣을 때는 활용형까지 넣으세요. 원본 소분류는 `tags_never_candidate.csv` · `tags_post_block.csv` 의"
      " `source_subgroup` 열에서 확인할 수 있습니다.")
    w("")
    w("## 7. 태그 목록")
    w("")
    w("### 7-1. 게시물째 버리게 만든 태그 (정책판) — `tags_post_block.csv`")
    w("")
    w("| 태그 | 규칙 | 범위 | 원본 소분류 | G | S | Q | E | 무정책판에서도 버림 |")
    w("|---|---|---|---|---:|---:|---:|---:|---|")
    for r in block_rows:
        w("| `%s`%s | %s | %s | %s | %s | %s | %s | %s | %s |"
          % (r[0], " ⚑" if r[10] else "", r[1], r[2], r[3] or "-", *[fmt(x) for x in r[4:8]], r[9]))
    w("")
    flagged = [r for r in block_rows if r[10]]
    w("⚑ = 원본 소분류(금기·고어·어두운 내용)에 근거 없이 **이름 정규식으로만** 걸린 태그 %d개 — 오탐 검토 대상입니다."
      " 밈·작품명·연출 태그가 섞여 있습니다(예: %s). 살리려면 `%s:%d` ALWAYS_BLOCK_RE / `:%d` ADULT_BLOCK_RE 를"
      " 좁히거나 예외를 두면 됩니다."
      % (len(flagged), ", ".join("`%s`" % r[0] for r in flagged if "(" in r[0] or "lens" in r[0] or "emoji" in r[0])
         or ", ".join("`%s`" % r[0] for r in flagged[:5]),
         pol, line_of(r"^ALWAYS_BLOCK_RE"), line_of(r"^ADULT_BLOCK_RE")))
    w("")
    w("### 7-2. 정책판에서 후보로 안 내는 태그 (무정책판에만 있다) — `tags_never_candidate.csv`, %s개" % fmt(len(never_rows)))
    w("")
    by_sub = Counter(r[2] for r in never_rows)
    w("| 원본 소분류 | 개수 | 관측 많은 순 예 |")
    w("|---|---:|---|")
    for sub, n in by_sub.most_common():
        ex = [r[0] for r in never_rows if r[2] == sub][:10]
        w("| %s | %s | %s |" % (sub or "(없음)", n, ", ".join("`%s`" % e for e in ex)))
    w("")
    w("### 7-3. 색상 제외 태그 (질의 시점, 정책판만) — `tags_color.csv`, %s개" % fmt(len(color_rows)))
    w("")
    w("관측 많은 순 상위 60개: " + ", ".join("`%s`" % r[0] for r in color_rows[:60]))
    w("")
    w("색 단어가 들어 있어도 **일부러 살린** 태그(PRESERVE_TAGS): " + ", ".join("`%s`" % r[0] for r in preserved_rows))
    w("")
    w("### 7-4. 원본 단계에서 빠진 태그 (두 판 공통) — `tags_source_excluded.csv`, %s개" % fmt(len(src_rows)))
    w("")
    for reason, n in src_reason.most_common():
        ex = [r[0] for r in src_rows if r[1] == reason][:12]
        w("- `%s` %s개: %s" % (reason, fmt(n), ", ".join("`%s`" % e for e in ex)))
    w("")
    (out / "REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")

    A.close()
    B.close()
    src.close()
    print("보고서: %s" % (out / "REPORT.md"))
    for name in ("compare.json", "tags_post_block.csv", "tags_never_candidate.csv", "tags_color.csv",
                 "tags_color_preserved.csv", "tags_source_excluded.csv"):
        print("        %s" % (out / name))


if __name__ == "__main__":
    main()
