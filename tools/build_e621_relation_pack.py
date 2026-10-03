"""Build a bounded, site-separated E621 relation pack from pinned offline inputs.

Build dependencies: numpy, scipy, pyarrow. Runtime uses only the standard library.
Cooccurrences are exact for the admitted snapshot, not semantic relationships.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
import math
from pathlib import Path
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA = "naia.e621-relations.v1"
MAX_BYTES = 10_000_000


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def select_relations(rows, ids):
    kept, audit = [], Counter()
    for row in rows:
        kind = row["relation"]
        if row["site"] != "e621" or kind not in ("alias", "implication"):
            audit["unsupported"] += 1
        elif row["upstream_status"] != "active":
            audit[kind + "_inactive"] += 1
        elif row["source"] not in ids or row["target"] not in ids:
            audit[kind + "_outside_vocabulary"] += 1
        else:
            kept.append([kind, ids[row["source"]], ids[row["target"]], row["source_id"]])
            audit[kind + "_included"] += 1
    return sorted(kept), dict(audit)


def select_crosswalk(rows, ids):
    kept = []
    for row in rows:
        if (row.get("review_status") == "root_definition_passage_review"
                and row.get("source_site") == "e621" and row.get("target_site") == "danbooru"
                and row.get("e621") in ids and row.get("danbooru")):
            kept.append({**row, "automatic_rewrite_allowed": False,
                         "translation_transfer_allowed": False, "edit_permission": False})
    return sorted(kept, key=lambda row: (row["e621"], row["danbooru"], row["relation"]))


RANK = "pair count * log2(lift) desc, pair count desc, exact tag asc"


def implication_ancestors(relations):
    """source id -> every tag it implies, transitively (kimono -> japanese_clothing -> ... -> clothing)."""
    parents = {}
    for kind, source, target, _ in relations:
        if kind == "implication" and source != target:
            parents.setdefault(source, set()).add(target)
    closure = {}
    for source in parents:
        seen, stack = set(), list(parents[source])
        while stack:
            node = stack.pop()
            if node not in seen and node != source:
                seen.add(node)
                stack.extend(parents.get(node, ()))
        closure[source] = seen
    return closure


def top_candidates(source, counts, marginals, total, *, k, min_support, min_lift, excluded=None):
    """Stable exact top K after edge support/lift filters; IDs follow exact tag order.

    Rank = pair count * log2(lift): how often the pair occurs, weighted by how specific it is.
    Lift alone ranked rare child tags first (feet -> 3_toes, white_fur -> one obscure species);
    pair count alone ranks base-rate tags first. `excluded` drops tags the source already implies -
    they co-occur by definition and would fill every slot (kimono -> four clothing ancestors).
    """
    import numpy as np
    targets, support = counts.indices, counts.data
    lift = support.astype(np.float64) * total / (marginals[source] * marginals[targets])
    valid = (targets != source) & (support >= min_support) & (lift >= min_lift)
    if excluded is not None and len(excluded):
        valid &= ~np.isin(targets, excluded)
    targets, support, lift = targets[valid], support[valid], lift[valid]
    order = np.lexsort((targets, -support, -(support * np.log2(lift))))[:k]
    return targets[order], support[order]


def pair_ratings(a, b, ratings):
    import numpy as np
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    at = np.searchsorted(big, small)
    valid = at < len(big)
    matched = small[valid]
    matched = matched[big[at[valid]] == matched]
    return np.bincount(ratings[matched], minlength=3).astype("<u4")


def encode_pack(meta, names, tag_counts, offsets, edges, relations, crosswalk):
    output = io.BytesIO()
    members = {
        "meta.json": json.dumps(meta, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(),
        "tags.json": json.dumps(names, ensure_ascii=False, separators=(",", ":")).encode(),
        "tag_counts.u32": tag_counts.astype("<u4").tobytes(),
        "offsets.u32": offsets.astype("<u4").tobytes(),
        "cooccurrence.u32": edges.astype("<u4").tobytes(),
        "relations.json": json.dumps(relations, separators=(",", ":")).encode(),
        "crosswalk.json": json.dumps(crosswalk, ensure_ascii=False, separators=(",", ":")).encode(),
    }
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as pack:
        for name, blob in members.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            pack.writestr(info, blob, compresslevel=9)
    result = output.getvalue()
    if len(result) > MAX_BYTES:
        raise ValueError(f"pack exceeds {MAX_BYTES} bytes: {len(result)}; lower K or raise min-support")
    return result


def build(args):
    import numpy as np
    import pyarrow.parquet as pq
    from scipy.sparse import csr_matrix
    from core.event_map.pack import PackReader
    from core.site_tag_repository import collect_legacy_tags

    if (args.k < 1 or args.min_support < 1 or not math.isfinite(args.min_lift)
            or args.min_lift <= 0 or args.block_size < 1):
        raise ValueError("K, min-support, min-lift and block-size must be positive")
    started = time.perf_counter()
    names = sorted({r["tag"] for r in collect_legacy_tags(json.loads(args.vocabulary.read_bytes()))})
    if len(names) != args.expected_vocabulary:
        raise ValueError(f"expected {args.expected_vocabulary} product tags, got {len(names)}")
    ids = {name: i for i, name in enumerate(names)}
    relations, relation_audit = select_relations(pq.read_table(args.source / "e621_relations.parquet").to_pylist(), ids)
    crosswalk_rows = pq.read_table(args.source / "crosswalk_reviewed.parquet").to_pylist()
    crosswalk = select_crosswalk(crosswalk_rows, ids)
    reader = PackReader(args.source / "e621_events.e621map")
    meta = reader.json_of("meta")
    if meta.get("schema") != "naia.e621-observations.v1" or meta.get("site") != "e621":
        reader.close()
        raise ValueError("expected the site-separated E621 observations schema")
    tags = reader.json_of("tags")

    def view(section, dtype):
        start, length = reader.span(section)
        return np.frombuffer(reader.map, dtype=dtype, count=length // np.dtype(dtype).itemsize, offset=start)

    body, post_offsets, ratings = view("body", "<u4"), view("offsets", "<u8"), view("ratings", "u1")
    denominator = np.bincount(ratings, minlength=3)
    if len(denominator) != 3 or meta.get("rating_values") != ["s", "q", "e"]:
        raise ValueError("unknown rating values")
    raw_to_product = np.array([ids.get(name, -1) for name, _ in tags], dtype=np.int32)
    tag_counts = np.zeros((len(names), 3), dtype="<u4")
    # Chunking limits temporary rating/body arrays to roughly 100k posts.
    for lo in range(0, len(ratings), 100_000):
        hi = min(lo + 100_000, len(ratings))
        tag_ids = raw_to_product[body[int(post_offsets[lo]):int(post_offsets[hi])]]
        per_assignment = np.repeat(ratings[lo:hi], np.diff(post_offsets[lo:hi + 1]).astype(np.int64))
        valid = tag_ids >= 0
        packed_ids = tag_ids[valid] * 3 + per_assignment[valid]
        tag_counts += np.bincount(packed_ids, minlength=len(names) * 3).reshape(-1, 3).astype("<u4")
    marginals_all = tag_counts.sum(axis=1)
    raw_ids = sorted((i for i, (name, _) in enumerate(tags)
                      if name in ids and marginals_all[ids[name]] >= args.min_support),
                     key=lambda i: tags[i][0])
    product_ids = np.array([ids[tags[i][0]] for i in raw_ids], dtype=np.uint32)
    # Any edge passing min_support has both marginals >= min_support. No eligible
    # pair is lost by this optimization; every admitted s/q/e post participates.
    raw = csr_matrix((np.ones(len(body), dtype=np.int32), body, post_offsets),
                     shape=(len(ratings), len(tags)))
    matrix = raw[:, raw_ids].T.tocsr()
    del raw
    matrix.sort_indices()
    transpose = matrix.T.tocsr()
    marginals = np.asarray(matrix.sum(axis=1)).ravel().astype(np.float64)
    offsets = np.zeros(len(names) + 1, dtype="<u4")
    records = []
    # Implied tags, as row numbers of this matrix (rows follow raw_ids, not product ids).
    row_of = {int(product): row for row, product in enumerate(product_ids)}
    implied_rows = {row_of[source]: np.array(sorted(row_of[t] for t in targets if t in row_of), dtype=np.int64)
                    for source, targets in implication_ancestors(relations).items() if source in row_of}
    for lo in range(0, len(raw_ids), args.block_size):
        hi = min(lo + args.block_size, len(raw_ids))
        counts = matrix[lo:hi] @ transpose
        for source in range(lo, hi):
            row = counts.getrow(source - lo)
            targets, supports = top_candidates(source, row, marginals, len(ratings),
                k=args.k, min_support=args.min_support, min_lift=args.min_lift,
                excluded=implied_rows.get(source))
            for target, support in zip(targets, supports):
                a = matrix.indices[matrix.indptr[source]:matrix.indptr[source + 1]]
                b = matrix.indices[matrix.indptr[target]:matrix.indptr[target + 1]]
                s, q, e = pair_ratings(a, b, ratings)
                if int(s) + int(q) + int(e) != int(support):
                    raise ValueError("rating intersections disagree with sparse product")
                records.append((int(product_ids[target]), int(s), int(q), int(e)))
            offsets[int(product_ids[source]) + 1] = len(targets)
        print(json.dumps({"processed_tags": hi, "total_eligible_tags": len(raw_ids),
                          "edges": len(records), "seconds": round(time.perf_counter() - started, 2)}), flush=True)
    offsets = np.cumsum(offsets, dtype="<u4")
    edges = np.array(records, dtype="<u4").reshape(-1, 4)
    pack_meta = {
        "schema": SCHEMA, "site": "e621", "vocabulary_count": len(names),
        "vocabulary_sha256": sha256(args.vocabulary), "rating_values": ["s", "q", "e"],
        "denominators": dict(zip(("s", "q", "e"), map(int, denominator))),
        "total_posts": len(ratings), "k": args.k, "min_support": args.min_support,
        "min_lift": args.min_lift, "rank": RANK,
        "cooccurrence_excludes": "tags the source implies, transitively",
        "eligible_marginal_tags": len(raw_ids), "tags_with_cooccurrences": int(np.count_nonzero(np.diff(offsets))),
        "cooccurrence_edges": len(edges), "relation_audit": relation_audit,
        "crosswalk_included": len(crosswalk), "crosswalk_excluded": len(crosswalk_rows) - len(crosswalk),
        "sources": {
            "observations": {"file": "e621_events.e621map", "sha256": sha256(args.source / "e621_events.e621map"),
                             "snapshot": meta["snapshot"], "retrieved_at": None, "audit": meta["audit"]},
            "relations": {"file": "e621_relations.parquet", "sha256": sha256(args.source / "e621_relations.parquet"),
                          "snapshot": args.relations_snapshot, "retrieved_at": None,
                          "snapshot_evidence": "Pinned source date supplied via --relations-snapshot; independent of filesystem timestamps."},
            "crosswalk": {"file": "crosswalk_reviewed.parquet", "sha256": sha256(args.source / "crosswalk_reviewed.parquet"),
                          "e621_definition_snapshot": args.relations_snapshot,
                          "danbooru_definition_snapshot": None, "reviewed_at": None, "retrieved_at": None,
                          "date_note": "Review file records definition hashes and wiki IDs, but no review/retrieval or Danbooru wiki snapshot date."},
        },
        "policy": {"automatic_rewrite_allowed": False, "edit_permission": False,
                   "cooccurrence_semantic_approval": False, "rating_filter": None,
                   "relation_scope": "both E621 endpoints in product vocabulary; crosswalk E621 endpoint only",
                   "missing_edge": "below threshold, outside top K, or absent; not proof of incompatibility",
                   "suggest": "approximate union of stored pair evidence; no multi-tag intersection count"},
    }
    blob = encode_pack(pack_meta, names, tag_counts, offsets, edges, relations, crosswalk)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(blob)
    report = {**pack_meta, "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(),
              "build_seconds": time.perf_counter() - started}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"bytes": len(blob), "build_seconds": report["build_seconds"]}), flush=True)
    # Mmap views belong only to the offline builder; release them before closing.
    del body, post_offsets, ratings
    reader.close()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--vocabulary", type=Path, default=ROOT / "data/e621_data")
    parser.add_argument("--output", type=Path, default=ROOT / "data/e621_relations.pack")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--relations-snapshot", required=True)
    parser.add_argument("--expected-vocabulary", type=int, default=172608)
    parser.add_argument("--k", type=int, default=16)
    parser.add_argument("--min-support", type=int, default=100)
    parser.add_argument("--min-lift", type=float, default=2.0)
    parser.add_argument("--block-size", type=int, default=128)
    build(parser.parse_args())
