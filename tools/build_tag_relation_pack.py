# -*- coding: utf-8 -*-
"""메인 프롬프트 추천 카드용 태그 관계 팩을 굽는다 (`data/tag_relation_pack.json`).

원천은 Codex 의 관계 지도(`codex_out/search-quick-redesign/parallel-v1/`, 개발 머신에만 있다) 위의
**제품 조회 계약**(`product_contract/QUERY_CONTRACT.json`, 2026-09-26 4단계)이다. 관계 행마다 검토된
`display_type`(표시 유형)과 `edit_policy`(누르면 할 일)가 들어 있고, 빌더는 그것을 **그대로 옮긴다** -
칸(section)이나 단부루 함의로 유형을 다시 추정하지 않는다(계약 CONSUMER.ko.md).

    display_type -> 카드 줄(화면 이름)       edit_policy  -> op
    sibling      -> siblings(대안)          replace_seed -> 1  커서 태그 하나를 바꾼다
    subtype      -> variations(종류)        add          -> 0  뒤에 더한다
    companion    -> companions(함께)        none         -> 싣지 않는다(탐색 전용 · held · redirect)
    modifier     -> attributes(스타일)
    state · action · part · context -> state(상태) · action(동작) · parts(부분) · context(연출)
    navigation   -> 싣지 않는다

applicability 가 inapplicable(씨앗의 고정 사실과 어긋남)인 행도 싣지 않는다. conditional(조건 미확인)은 권하되
사실로 취급하지 않는다 - 누르는 것은 사용자다. 같은 태그가 여러 도메인·칸에 있으면 **검토된 바꾸기**를 먼저,
그다음 줄 순서로 하나만 고른다(한 도메인의 none 이 다른 도메인의 승인을 가리지 않는다).

`ko` = 카드에 보일 한국어 설명의 검토판(Codex `description_ko_canonical`, 사용자 지정 2026-09-27) 중 지금 사전
설명과 **다른 것만**. 표시 전용이다 - 검색 색인은 원래 설명을 그대로 읽는다.

순서: Siblings 는 축의 order(검토된 비교 순서), 없으면 게시물 수. 나머지는 P(대상|씨앗) x min(log2 lift, 3)
(교집합 >= --min-support), 그다음 게시물 수. 음의 lift 는 뒤로 민다 - 검토된 후보를 통계로 지우지 않는다.
형제의 낮은 공출현은 정상이라(standing/sitting 0.37) 형제 줄에는 LIFT 를 쓰지 않는다.

보이는 순서는 항목의 셋째 값(그 줄 안의 자리)이다(사용자 지정 2026-09-27: 비슷한 것끼리 + ABC). 목록 자체는
위 관련도 순 그대로라 대표 칩은 앞에서 고르고, 카드에는 이 자리 순으로 선다: 대안은 검토된 축 순서가 먼저,
그다음 ⇄(바꾸기) -> 색 -> 무늬·소재(Codex 칸 attributes) -> 모양(designs · types) -> 나머지, 묶음 안은 ABC.

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
DEFAULT_OUT = REPO / "data" / "tag_relation_pack.json"

SCHEMA = "naia.tag-relation-pack.v1"
BUILDER_VERSION = "2026-09-27.3"
# 카드에 그리는 순서. Companions(같이 쓰는 별개 개념: smile -> blush)는 적고 값이 커서 앞쪽에 둔다.
TYPES = ("siblings", "variations", "companions", "attributes", "state", "action", "parts", "context")
DISPLAY_TO_TYPE = {
    "sibling": "siblings", "subtype": "variations", "companion": "companions", "modifier": "attributes",
    "state": "state", "action": "action", "part": "parts", "context": "context",
}
EDIT_TO_OP = {"replace_seed": 1, "add": 0}
REQUIRED_FIELDS = ("display_type", "edit_policy", "applicability")
# 같은 대상이 여러 도메인·칸에 걸리면: 검토된 바꾸기가 먼저, 그다음 이 순서.
TYPE_PRIORITY = {t: i for i, t in enumerate(TYPES)}


class ContractError(ValueError):
    """카탈로그가 제품 조회 계약 이전 것이다(관계 행에 display_type · edit_policy 가 없다)."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def classify(row: dict) -> tuple[str, int] | None:
    """계약 필드 그대로 (카드 줄, op). 싣지 않을 행은 None."""
    missing = [k for k in REQUIRED_FIELDS if k not in row]
    if missing:
        raise ContractError(f"relation row lacks {missing} - rebuild from a product-contract catalog")
    if (row.get("applicability") or {}).get("status") == "inapplicable":
        return None
    kind = DISPLAY_TO_TYPE.get(row["display_type"])
    op = EDIT_TO_OP.get(row["edit_policy"])
    if kind is None or op is None:
        return None                         # navigation · edit_policy none = 탐색 전용, 삽입 금지
    return kind, op


def lift_score(stat: tuple[int, float, float] | None, min_support: int) -> float | None:
    """P(대상|씨앗) x min(log2 lift, 3). 교집합이 모자라면 None(순위는 빈도로), 음의 lift 는 -1."""
    if not stat:
        return None
    inter, p, lift = stat
    if inter < min_support or lift <= 0:
        return None
    return p * min(math.log2(lift), 3.0) if lift > 1 else -1.0


# 보이는 순서의 묶음(사용자 지정 2026-09-27). 색은 Codex 칸이 무늬·소재와 같아서(attributes) 낱말로 가른다 -
# 색 낱말은 런타임(추천 프롬프트의 색 거르기)과 한 벌이다.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from core.tag_relation_pack import COLOR_WORDS  # noqa: E402

# Codex 칸 -> 묶음: attributes = 무늬·소재, designs · types = 모양. 그 밖(상태·동작·부분·연출 칸)은 한 묶음.
FACET_BY_SECTION = {"attributes": 2, "designs": 3, "types": 3}
FACET_REPLACE, FACET_COLOR, FACET_OTHER = 0, 1, 4


def display_facet(tag: str, op: int, section: str | None) -> int:
    """보이는 순서의 묶음: ⇄(바꾸기) -> 색 -> 무늬·소재 -> 모양 -> 나머지."""
    if op == 1:
        return FACET_REPLACE
    for word in tag.replace("_", " ").split():
        if word in COLOR_WORDS or any(part in COLOR_WORDS for part in word.split("-")):
            return FACET_COLOR
    return FACET_BY_SECTION.get(section or "", FACET_OTHER)


def display_keys(kind: str, kept: list[tuple[str, int]], info: dict[str, tuple[int | None, str | None]]) -> list[int]:
    """kept(관련도 순 [(태그, op)])의 항목마다 **보이는 자리**. info = 태그 -> (축 순서, Codex 칸).

    대안(siblings)은 검토된 축 순서(짧은 머리 -> 긴 머리 같은 눈금)가 먼저다 - ABC 로 섞으면 눈금이 깨진다.
    """
    far = 1 << 30

    def sort_key(i: int):
        tag, op = kept[i]
        rank, section = info.get(tag, (None, None))
        axis = rank if kind == "siblings" and rank is not None else far
        return (axis, display_facet(tag, op, section), tag.lower(), tag)

    keys = [0] * len(kept)
    for pos, i in enumerate(sorted(range(len(kept)), key=sort_key)):
        keys[i] = pos
    return keys


def load_catalog(catalog_dir: Path):
    sys.path.insert(0, str(catalog_dir))
    import query  # noqa: WPS433 - Codex 조회 모듈을 그대로 써서 계약·상속·적용 판정을 한 곳에 둔다

    return query, query.load("sqlite")


def approved_domains(model, tag: str) -> list[str]:
    out = []
    for d in (model["nodes"].get(tag) or {}).get("review_domains", []):
        n = model["domains"][d]["nodes"].get(tag) or {}
        ir = n.get("independent_review") or {}
        if n.get("status") == "accepted" and ir.get("meaning_status") == ir.get("korean_status") == "pass":
            out.append(d)
    return out


def _better(new: tuple, old: tuple | None) -> bool:
    """(kind, op, rank) 둘 중 남길 것 - 검토된 바꾸기가 먼저, 그다음 줄 순서."""
    if old is None:
        return True
    return (-new[1], TYPE_PRIORITY[new[0]]) < (-old[1], TYPE_PRIORITY[old[0]])


def collect_candidates(query, model, keep) -> dict[str, dict[str, tuple[str, int, int | None, str]]]:
    """씨앗 -> {대상: (줄, op, 축 순서, Codex 칸)}. 축 순서는 형제 줄에만 쓴다(검토된 order 안의 자리),
    칸(attributes · designs · types …)은 보이는 순서의 묶음에만 쓴다 - 줄은 계약의 display_type 이 정한다."""
    out: dict[str, dict[str, tuple[str, int, int | None, str]]] = {}
    for seed in sorted(model["nodes"]):
        doms = approved_domains(model, seed)
        if not doms:
            continue
        picked: dict[str, tuple[str, int, int | None, str]] = {}
        for d in doms:
            r = query.domain_lookup(model, d, seed)
            axes = r.get("axes") or {}
            for section, rows in r.get("sections", {}).items():
                for row in rows:
                    target = row["tag"]
                    if (target == seed or not row.get("insertable") or row.get("review_status") != "independent_pass"
                            or not keep(target)):
                        continue
                    got = classify(row)
                    if got is None:
                        continue
                    order = (axes.get(row.get("axis_id") or "") or {}).get("order") or []
                    rank = order.index(target) if target in order else None
                    cand = (got[0], got[1], rank, section)
                    if _better(cand, picked.get(target)):
                        picked[target] = cand
        if picked:
            out[seed] = picked
    return out


def read_pair_stats(pairs_path: Path, wanted: dict[str, set[str]]) -> dict[tuple[str, str], tuple[int, float, float]]:
    """Codex 가 잰 Full 모집단 공출현에서 필요한 (씨앗, 대상) 쌍만 뽑는다. 쌍은 문자열 정렬 순서다."""
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


def order_seed(seed: str, picked: dict[str, tuple[str, int, int | None, str]], stats, freq, per_type: int,
               min_support: int, counts: dict[str, int]) -> dict[str, list[list]]:
    """줄마다 [[태그, op, 보이는 자리], ...] - 목록은 관련도 순(대표 칩은 앞에서 고른다), 셋째 값이 화면 순서."""
    by_type: dict[str, list[tuple[str, int, int | None, str]]] = defaultdict(list)
    for target, (kind, op, rank, section) in picked.items():
        by_type[kind].append((target, op, rank, section))
    out: dict[str, list[list]] = {}
    for kind in TYPES:
        items = by_type.get(kind)
        if not items:
            continue
        if kind == "siblings":
            far = 1 << 30
            ranked = [(t, op) for t, op, _rank, _section in sorted(
                items, key=lambda x: (x[2] if x[2] is not None else far, -freq(x[0]), x[0]))]
        else:
            scored, rest = [], []
            for target, op, _rank, _section in items:
                s = lift_score(stats.get((seed, target)), min_support)
                if s is not None and s >= 0:
                    scored.append((s, target, op))
                else:
                    if s is not None:
                        counts["negative_lift_demoted"] += 1
                    rest.append((0.0, target, op))
            scored.sort(key=lambda x: (-x[0], -freq(x[1]), x[1]))
            rest.sort(key=lambda x: (-freq(x[1]), x[1]))
            ranked = [(t, op) for _, t, op in scored + rest]
        if not ranked:
            continue
        if len(ranked) > per_type:
            counts["truncated"] += len(ranked) - per_type
        kept = ranked[:per_type]
        info = {t: (rank, section) for t, _op, rank, section in items}
        out[kind] = [[t, op, key] for (t, op), key in zip(kept, display_keys(kind, kept, info))]
    return out


def korean_overrides(model, raw) -> dict[str, str]:
    """카드에 보일 대표 한국어 - 사전(raw)에 있는 태그 중 지금 설명과 다른 것만(같으면 실을 까닭이 없다)."""
    out: dict[str, str] = {}
    for tag in sorted(model["nodes"]):
        text = " ".join(str(model["nodes"][tag].get("description_ko_canonical") or "").split())
        info = raw.get(tag)
        if not text or not isinstance(info, dict):
            continue
        if text != " ".join(str(info.get("description") or "").split()):
            out[tag] = text
    return out


def build(catalog_dir: Path, per_type: int, min_support: int) -> dict:
    sys.path.insert(0, str(REPO))
    from core.kr_tag_loader import load_kr_tag_records
    from app.backend.server.prompt_tools_routes import _recommendable

    with contextlib.redirect_stdout(io.StringIO()):
        raw = load_kr_tag_records(REPO, data_roots=[REPO / "data"]).raw
    keep = _recommendable(SimpleNamespace(repo_root=str(REPO)), raw)

    def freq(tag: str) -> int:
        return int((raw.get(tag) or {}).get("freq", 0) or 0)

    query, model = load_catalog(catalog_dir)
    candidates = collect_candidates(query, model, keep)
    wanted = {seed: {t for t, (kind, *_rest) in picked.items() if kind != "siblings"}
              for seed, picked in candidates.items()}
    pairs_path = catalog_dir / "evidence" / "pairs.jsonl"
    stats = read_pair_stats(pairs_path, wanted)
    counts: dict[str, int] = defaultdict(int)
    seeds = {}
    for seed in sorted(candidates):
        rows = order_seed(seed, candidates[seed], stats, freq, per_type, min_support, counts)
        if rows:
            seeds[seed] = rows
    ko = korean_overrides(model, raw)
    by_type = defaultdict(int)
    replace = 0
    for rows in seeds.values():
        for kind, items in rows.items():
            by_type[kind] += len(items)
            replace += sum(item[1] for item in items)
    contract = catalog_dir / "product_contract" / "QUERY_CONTRACT.json"
    return {
        "schema": SCHEMA,
        "builder_version": BUILDER_VERSION,
        "types": list(TYPES),
        "ops": {"0": "add", "1": "replace"},
        "rules": {
            "per_type": per_type,
            "min_support": min_support,
            "typing": "Codex product query contract: display_type -> row, edit_policy -> op; none/navigation dropped",
            "applicability": "inapplicable rows dropped; conditional kept as a suggestion (the user clicks)",
            "merge": "same target across domains: reviewed replace first, then row order",
            "order": "siblings by reviewed axis order then post count; others by P(t|s) * min(log2 lift, 3), then post count",
            "negative_lift": "demoted, not dropped",
            "display": ("items stay in relevance order (lead chips come from the front); the third field is the on-card position: siblings by reviewed axis order first, then replace, colour, pattern/material (section attributes), shape (designs/types), rest - A-Z inside"),
            "ko": "reviewed canonical Korean (Codex description_ko_canonical) where it differs from the dictionary; display only",
        },
        "source": {
            "catalog_sqlite_sha256": sha256_file(catalog_dir / "data" / "catalog.sqlite"),
            "pairs_jsonl_sha256": sha256_file(pairs_path),
            "query_contract_sha256": sha256_file(contract),
        },
        "stats": {
            "seeds": len(seeds),
            "items": sum(by_type.values()),
            "by_type": {k: by_type[k] for k in TYPES},
            "replace_items": replace,
            "pair_stats_used": len(stats),
            "ko_overrides": len(ko),
            "counts": dict(sorted(counts.items())),
        },
        "seeds": seeds,
        "ko": ko,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--catalog-dir", type=Path, default=DEFAULT_CATALOG_DIR)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--per-type", type=int, default=16)
    ap.add_argument("--min-support", type=int, default=30)
    args = ap.parse_args(argv)
    pack = build(args.catalog_dir, args.per_type, args.min_support)
    text = json.dumps(pack, ensure_ascii=False, separators=(",", ":"), sort_keys=False) + "\n"
    tmp = args.out.with_suffix(args.out.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, args.out)
    s = pack["stats"]
    print(f"wrote {args.out} ({len(text.encode('utf-8')) / 1e6:.2f} MB) seeds={s['seeds']} items={s['items']} "
          f"by_type={s['by_type']} replace={s['replace_items']} counts={s['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
