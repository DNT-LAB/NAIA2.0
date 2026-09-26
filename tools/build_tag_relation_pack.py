# -*- coding: utf-8 -*-
"""메인 프롬프트 추천 카드용 태그 관계 팩을 굽는다 (`data/tag_relation_pack.json`).

원천은 Codex 의 관계 지도(`codex_out/search-quick-redesign/parallel-v1/`, 개발 머신에만 있다)다.
Event Map 태그 29,412개를 위키 원문으로 판독·독립 검토한 관계를 태그마다 **유형별 추천 목록**으로
미리 펼쳐 둔다. 런타임은 이 작은 파일만 읽는다 - 107MB 카탈로그와 458MB 공출현은 싣지 않는다.

유형과 누르면 하는 일(op: 1 = 바꾸기, 0 = 더하기). 한 줄은 한 가지 일만 한다:

    siblings    같은 층의 대안(카탈로그 `related`)                 바꾸기 - 함께 두면 open mouth + closed mouth 처럼 모순
    variations  씨앗을 **함의**하는 더 구체적인 것(white shirt,     바꾸기 - 씨앗의 뜻을 품으니 잃는 것이 없다
                dress shirt, very long hair)
    attributes  종류·모양·속성 칸의 나머지(frills, sleeveless)      더하기 - 바꿔 넣으면 옷이 사라진다
    state · action · parts · context                               더하기. 단 씨앗의 부정(no X · unworn X)은 바꾸기

씨앗이 함의하는 상위형(dress shirt -> collared shirt)은 어느 줄에도 넣지 않는다 - 카드의 implies 줄이 이미 보인다.

순서: siblings 는 게시물 수, 나머지는 LIFT 점수 P(대상|씨앗) x min(log2 lift, 3) (교집합 >= --min-support).
서로 대신 쓰는 태그는 함께 안 나와 lift 가 1 미만인 게 정상이라(standing/sitting 0.37) siblings 에는 LIFT 를 쓰지 않는다.
더하기 후보 중 lift 가 1 미만으로 **측정된** 것은 뺀다 - 같이 안 쓰이는 것을 더하라고 권하는 꼴이다(long hair 에 short hair).

유형 판정은 지금 데이터의 칸(section) + 단부루 함의로 한 **임시 규칙**이다. Codex 가 관계 유형·축·배타 여부를
채우면(누락 목록 2026-09-26) `classify()` 한 곳만 고치고 다시 굽는다.

    python tools/build_tag_relation_pack.py
    python tools/build_tag_relation_pack.py --catalog-dir <parallel-v1> --out data/tag_relation_pack.json
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG_DIR = REPO / "codex_out" / "search-quick-redesign" / "parallel-v1"
DEFAULT_IMPLICATIONS = REPO / "data" / "danbooru_tag_snapshot" / "tag_implications.parquet"
DEFAULT_OUT = REPO / "data" / "tag_relation_pack.json"

SCHEMA = "naia.tag-relation-pack.v1"
BUILDER_VERSION = "2026-09-26.3"
TYPES = ("siblings", "variations", "attributes", "state", "action", "parts", "context")
# 같은 대상이 여러 칸에 걸리면 앞선 유형 하나만 남긴다(한 카드에 같은 칩이 두 번 나오지 않게).
TYPE_PRIORITY = {t: i for i, t in enumerate(
    ("variations", "siblings", "attributes", "state", "action", "parts", "context"))}
VARIATION_SECTIONS = {"types", "designs", "attributes", "named_styles"}
SECTION_TYPE = {"states": "state", "events": "action", "parts": "parts", "contexts": "context"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class Implications:
    """단부루 함의(active)의 전이 판정. 이름은 공백 표기로 맞춘다."""

    def __init__(self, pairs: list[tuple[str, str]]):
        self.edges: dict[str, set[str]] = defaultdict(set)
        for a, b in pairs:
            self.edges[a].add(b)
        self._memo: dict[tuple[str, str], bool] = {}

    @classmethod
    def from_parquet(cls, path: Path) -> "Implications":
        import pyarrow.parquet as pq

        table = pq.read_table(path, columns=["antecedent_name", "consequent_name", "status"])
        rows = table.to_pylist()
        return cls([(norm(r["antecedent_name"]), norm(r["consequent_name"]))
                    for r in rows if str(r.get("status") or "") == "active"])

    def implies(self, a: str, b: str, depth: int = 6) -> bool:
        key = (a, b)
        hit = self._memo.get(key)
        if hit is not None:
            return hit
        seen, frontier, found = {a}, {a}, False
        for _ in range(depth):
            nxt = set()
            for x in frontier:
                for y in self.edges.get(x, ()):
                    if y == b:
                        found = True
                        break
                    if y not in seen:
                        seen.add(y)
                        nxt.add(y)
                if found:
                    break
            if found or not nxt:
                break
            frontier = nxt
        self._memo[key] = found
        return found


def norm(name: str) -> str:
    return " ".join(str(name or "").replace("_", " ").split()).lower()


def negation_of(target: str, seed: str) -> bool:
    """씨앗을 부정하는 태그인가(no shirt · unworn shirt · shirt removed). 단수·복수 둘 다 본다."""
    forms = {seed}
    if seed.endswith("s"):
        forms.add(seed[:-1])
    else:
        forms.add(seed + "s")
    return any(target in (f"no {f}", f"unworn {f}", f"{f} removed") for f in forms)


def classify(section: str, own: bool, seed: str, target: str, imp: Implications) -> tuple[str, int] | None:
    """(유형, op) 또는 None(추천하지 않음). Codex 가 관계 유형을 채우면 여기만 바꾼다."""
    if imp.implies(seed, target):
        return None                           # 상위형(grin -> smile, dress shirt -> collared shirt) - implies 줄이 보인다
    if section == "related":
        if not own:
            return None                       # 부모의 '비슷한 것' 은 씨앗의 형제가 아니다
        if imp.implies(target, seed):
            return "variations", 1            # related 로 적혀 있지만 실제로는 구체형(breasts -> large breasts)
        return "siblings", 1
    if section in VARIATION_SECTIONS:
        # 부모에게서 물려받은 줄이라도 씨앗을 함의하면 구체형이다(long hair -> very long hair).
        return ("variations", 1) if imp.implies(target, seed) else ("attributes", 0)
    kind = SECTION_TYPE.get(section)
    if kind is None:
        return None
    return kind, 1 if negation_of(target, seed) else 0


def lift_score(stat: tuple[int, float, float] | None, min_support: int) -> float | None:
    """P(대상|씨앗) x min(log2 lift, 3). 교집합이 모자라면 None(순위는 빈도로)."""
    if not stat:
        return None
    inter, p, lift = stat
    if inter < min_support or lift <= 0:
        return None
    return p * min(math.log2(lift), 3.0) if lift > 1 else -1.0


def load_catalog(catalog_dir: Path):
    sys.path.insert(0, str(catalog_dir))
    import query  # noqa: WPS433 - Codex 도구를 그대로 써서 상속·적용 판정을 한 곳에 둔다

    return query, query.load("sqlite")


def approved_domains(model, tag: str) -> list[str]:
    out = []
    for d in (model["nodes"].get(tag) or {}).get("review_domains", []):
        n = model["domains"][d]["nodes"].get(tag) or {}
        ir = n.get("independent_review") or {}
        if n.get("status") == "accepted" and ir.get("meaning_status") == ir.get("korean_status") == "pass":
            out.append(d)
    return out


def collect_candidates(query, model, imp: Implications, keep) -> dict[str, dict[str, tuple[str, int]]]:
    """씨앗 -> {대상: (유형, op)}. 여러 범위의 결과를 유형 우선순위로 합친다."""
    out: dict[str, dict[str, tuple[str, int]]] = {}
    for seed in sorted(model["nodes"]):
        doms = approved_domains(model, seed)
        if not doms:
            continue
        picked: dict[str, tuple[str, int]] = {}
        for d in doms:
            r = query.domain_lookup(model, d, seed)
            for section, rows in r.get("sections", {}).items():
                for row in rows:
                    target = row["tag"]
                    if (target == seed or not row.get("insertable") or row.get("review_status") != "independent_pass"
                            or not keep(target)):
                        continue
                    # 씨앗의 고정 사실과 어긋나는 줄(american flag panties -> white panties)은 빼고,
                    # 조건 미확인(conditional)·조건 없음(candidate_only)만 권한다(Codex 검토 2026-09-26).
                    if (row.get("applicability") or {}).get("status") == "inapplicable":
                        continue
                    got = classify(section, row.get("inherited_from") is None, seed, target, imp)
                    if got is None:
                        continue
                    prev = picked.get(target)
                    if prev is None or TYPE_PRIORITY[got[0]] < TYPE_PRIORITY[prev[0]]:
                        picked[target] = got
                    elif prev[0] == got[0] and got[1] > prev[1]:
                        picked[target] = got
        if picked:
            out[seed] = picked
    return out


def read_pair_stats(pairs_path: Path, wanted: dict[str, set[str]]) -> dict[tuple[str, str], tuple[int, float, float]]:
    """Codex 가 잰 Full 모집단 공출현에서 필요한 (씨앗, 대상) 쌍만 뽑는다."""
    stats: dict[tuple[str, str], tuple[int, float, float]] = {}
    with open(pairs_path, "r", encoding="utf-8") as fh:
        for line in fh:
            head = line[:line.index("]") + 1]
            a, b = json.loads(head[head.index("["):])
            hit_ab = b in wanted.get(a, ())
            hit_ba = a in wanted.get(b, ())
            if not (hit_ab or hit_ba):
                continue
            full = json.loads(line)["populations"]["full"]
            if full.get("status") != "measured_exact":
                continue
            f = full["filters"]["all"]
            if hit_ab:
                stats[(a, b)] = (int(f["intersection"]), float(f["p_b_given_a"]), float(f["lift"]))
            if hit_ba:
                stats[(b, a)] = (int(f["intersection"]), float(f["p_a_given_b"]), float(f["lift"]))
    return stats


def order_seed(seed: str, picked: dict[str, tuple[str, int]], stats, freq, per_type: int, min_support: int,
               dropped: dict[str, int]) -> dict[str, list[list]]:
    by_type: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for target, (kind, op) in picked.items():
        by_type[kind].append((target, op))
    out: dict[str, list[list]] = {}
    for kind in TYPES:
        items = by_type.get(kind)
        if not items:
            continue
        if kind == "siblings":
            ranked = sorted(items, key=lambda x: (-freq(x[0]), x[0]))
        else:
            scored, rest = [], []
            for target, op in items:
                s = lift_score(stats.get((seed, target)), min_support)
                if s is not None and s < 0 and op == 0:
                    dropped["negative_lift"] += 1
                    continue
                (scored if s is not None and s >= 0 else rest).append((s or 0.0, target, op))
            scored.sort(key=lambda x: (-x[0], -freq(x[1]), x[1]))
            rest.sort(key=lambda x: (-freq(x[1]), x[1]))
            ranked = [(t, op) for _, t, op in scored + rest]
        if not ranked:
            continue
        if len(ranked) > per_type:
            dropped["truncated"] += len(ranked) - per_type
        out[kind] = [[t, op] for t, op in ranked[:per_type]]
    return out


def build(catalog_dir: Path, implications_path: Path, per_type: int, min_support: int) -> dict:
    sys.path.insert(0, str(REPO))
    from core.kr_tag_loader import load_kr_tag_records
    from app.backend.server.prompt_tools_routes import _recommendable

    with contextlib.redirect_stdout(io.StringIO()):
        raw = load_kr_tag_records(REPO, data_roots=[REPO / "data"]).raw
    keep = _recommendable(SimpleNamespace(repo_root=str(REPO)), raw)

    def freq(tag: str) -> int:
        return int((raw.get(tag) or {}).get("freq", 0) or 0)

    query, model = load_catalog(catalog_dir)
    imp = Implications.from_parquet(implications_path)
    candidates = collect_candidates(query, model, imp, keep)
    wanted = {seed: {t for t, (kind, _) in picked.items() if kind != "siblings"} for seed, picked in candidates.items()}
    pairs_path = catalog_dir / "evidence" / "pairs.jsonl"
    stats = read_pair_stats(pairs_path, wanted)
    dropped: dict[str, int] = defaultdict(int)
    seeds = {}
    for seed in sorted(candidates):
        rows = order_seed(seed, candidates[seed], stats, freq, per_type, min_support, dropped)
        if rows:
            seeds[seed] = rows
    counts = defaultdict(int)
    replace = 0
    for rows in seeds.values():
        for kind, items in rows.items():
            counts[kind] += len(items)
            replace += sum(op for _, op in items)
    catalog_sqlite = catalog_dir / "data" / "catalog.sqlite"
    return {
        "schema": SCHEMA,
        "builder_version": BUILDER_VERSION,
        "types": list(TYPES),
        "ops": {"0": "add", "1": "replace"},
        "rules": {
            "per_type": per_type,
            "min_support": min_support,
            "order": "siblings by post count; others by P(t|s) * min(log2 lift, 3), then post count",
            "negative_lift_add_dropped": True,
            "typing": "interim: catalog section + active Danbooru implication (Codex gap list 2026-09-26)",
            "applicability": "inapplicable rows (conflict with the seed's known facts) are dropped",
        },
        "source": {
            "catalog_sqlite_sha256": sha256_file(catalog_sqlite),
            "pairs_jsonl_sha256": sha256_file(pairs_path),
            "implications_sha256": sha256_file(implications_path),
        },
        "stats": {
            "seeds": len(seeds),
            "items": sum(counts.values()),
            "by_type": {k: counts[k] for k in TYPES},
            "replace_items": replace,
            "pair_stats_used": len(stats),
            "dropped": dict(sorted(dropped.items())),
        },
        "seeds": seeds,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--catalog-dir", type=Path, default=DEFAULT_CATALOG_DIR)
    ap.add_argument("--implications", type=Path, default=DEFAULT_IMPLICATIONS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--per-type", type=int, default=16)
    ap.add_argument("--min-support", type=int, default=30)
    args = ap.parse_args(argv)
    pack = build(args.catalog_dir, args.implications, args.per_type, args.min_support)
    text = json.dumps(pack, ensure_ascii=False, separators=(",", ":"), sort_keys=False) + "\n"
    tmp = args.out.with_suffix(args.out.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, args.out)
    s = pack["stats"]
    print(f"wrote {args.out} ({len(text.encode('utf-8')) / 1e6:.2f} MB) seeds={s['seeds']} items={s['items']} "
          f"by_type={s['by_type']} replace={s['replace_items']} dropped={s['dropped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
