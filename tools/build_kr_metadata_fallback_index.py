from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.remote_api_server import RemoteBridge
from core.tag_search_index import KR_METADATA_FALLBACK_INDEX_PATH


DEFAULT_VERIFY_QUERIES = (
    "화면을 바라보다",
    "옷 끝자락을 잡아당기기",
    "와인 잔을 손에 쥐고있음",
)


def configure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def make_bridge() -> RemoteBridge:
    bridge = RemoteBridge.__new__(RemoteBridge)
    bridge._kr_tags_raw = {}
    bridge._tag_search_index = None
    bridge._tag_relation_ranker = None
    bridge._kr_tags_lock = threading.Lock()
    bridge._kr_tags_loaded = False
    bridge._char_analysis = {}
    bridge._autocomplete_translation_cache = {}
    return bridge


def main() -> int:
    configure_stdout()
    parser = argparse.ArgumentParser(
        description="Build the precomputed Korean metadata autocomplete fallback index."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=KR_METADATA_FALLBACK_INDEX_PATH,
        help=f"Output index path. Default: {KR_METADATA_FALLBACK_INDEX_PATH}",
    )
    parser.add_argument(
        "--verify-query",
        action="append",
        default=[],
        help="Korean query to run after the index is written. Can be repeated.",
    )
    args = parser.parse_args()

    total_start = time.perf_counter()
    bridge = make_bridge()

    load_start = time.perf_counter()
    bridge._load_kr_tags()
    load_ms = (time.perf_counter() - load_start) * 1000

    index = bridge._tag_search_index
    if index is None:
        raise SystemExit("TagSearchIndex was not created.")

    build_start = time.perf_counter()
    stats = index.write_metadata_fallback_index(args.output)
    build_ms = (time.perf_counter() - build_start) * 1000
    size_bytes = args.output.stat().st_size

    print(f"KR tag load: {load_ms:.1f} ms")
    print(f"metadata index build+write: {build_ms:.1f} ms")
    print(f"output: {args.output}")
    print(f"size: {size_bytes:,} bytes")
    print(
        "stats: "
        f"entries={stats['entry_count']:,}, "
        f"terms={stats['term_count']:,}, "
        f"postings={stats['posting_count']:,}"
    )

    verify_queries = args.verify_query or list(DEFAULT_VERIFY_QUERIES)
    for query in verify_queries:
        results = index.search_metadata_fallback(query, limit=5)
        tags = ", ".join(result.tag for result in results)
        print(f"verify {query}: {tags}")

    total_ms = (time.perf_counter() - total_start) * 1000
    print(f"total: {total_ms:.1f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
