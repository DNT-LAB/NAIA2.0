from __future__ import annotations

import argparse
import contextlib
import io
import json
import statistics
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.remote_api_server as remote_api_server
from core.remote_api_server import RemoteBridge


FIXTURE_PATH = ROOT / "tests" / "fixtures" / "autocomplete_eval_samples.json"
EXCLUDED_CATEGORY_NEEDLES = (
    "캐릭터",
    "작품",
    "저작권",
    "character",
    "copyright",
    "작가",
    "아티스트",
    "창작자",
    "시리즈",
    "미디어",
    "게임 > 캐릭터",
)
DEFAULT_TOP_LIMIT = 12
EXCLUDED_RESULT_TOP_LIMIT = 3


@dataclass(frozen=True)
class EvalFailure:
    bundle_id: str
    query: str
    expected_tags: tuple[str, ...]
    actual_tags: tuple[str, ...]
    reason: str


def configure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def load_fixture(path: str | Path = FIXTURE_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_fixture_shape(data: dict[str, Any]) -> None:
    bundles = data.get("bundles")
    if not isinstance(bundles, list) or len(bundles) != 12:
        raise AssertionError("autocomplete eval fixture must contain 12 bundles")
    if data.get("bundleCount") != 12:
        raise AssertionError("autocomplete eval fixture bundleCount must be 12")
    if data.get("bundleSize") != 50:
        raise AssertionError("autocomplete eval fixture bundleSize must be 50")
    nsfw_count = 0
    for bundle in bundles:
        samples = bundle.get("samples")
        if not isinstance(samples, list) or len(samples) != 50:
            raise AssertionError(f"{bundle.get('bundleId')} must contain 50 samples")
        for sample in samples:
            expected = sample.get("expectedTags")
            if not isinstance(expected, list) or not 1 <= len(expected) <= 3:
                raise AssertionError(f"{bundle.get('bundleId')} sample expectedTags must contain 1-3 tags")
            category = str(sample.get("sourceCategory") or "")
            if any(needle.lower() in category.lower() for needle in EXCLUDED_CATEGORY_NEEDLES):
                raise AssertionError(f"excluded category leaked into fixture: {category}")
            if bundle.get("nsfw") or sample.get("nsfw"):
                nsfw_count += 1
    if nsfw_count < 200:
        raise AssertionError("autocomplete eval fixture must keep at least four NSFW bundles")


def has_excluded_category(value: Any) -> bool:
    category = str(value or "").lower()
    return any(needle.lower() in category for needle in EXCLUDED_CATEGORY_NEEDLES)


def iter_samples(
    data: dict[str, Any],
    *,
    per_bundle: int | None = None,
) -> Iterable[tuple[str, dict[str, Any]]]:
    for bundle in data.get("bundles", []):
        bundle_id = str(bundle.get("bundleId") or "")
        samples = bundle.get("samples", [])
        limit = len(samples) if per_bundle is None else min(per_bundle, len(samples))
        for sample in samples[:limit]:
            yield bundle_id, sample


def make_bridge() -> RemoteBridge:
    bridge = RemoteBridge.__new__(RemoteBridge)
    bridge._kr_tags_raw = {}
    bridge._tag_search_index = None
    bridge._tag_relation_ranker = None
    bridge._kr_tags_lock = threading.Lock()
    bridge._kr_tags_loaded = False
    bridge._char_analysis = {}
    bridge._autocomplete_translation_cache = {}
    bridge._autocomplete_result_cache = {}
    with contextlib.redirect_stdout(io.StringIO()):
        bridge._load_kr_tags()
        bridge._search_kr_metadata_fallback("화면을 바라보다", DEFAULT_TOP_LIMIT, allow_build=True)
    return bridge


def evaluate_fixture(
    data: dict[str, Any],
    *,
    per_bundle: int | None = None,
    top_limit: int = DEFAULT_TOP_LIMIT,
) -> dict[str, Any]:
    validate_fixture_shape(data)
    original_translator = remote_api_server.korean_to_english
    remote_api_server.korean_to_english = lambda query: ""
    try:
        bridge = make_bridge()
        failures: list[EvalFailure] = []
        durations: list[float] = []
        checked = 0
        for bundle_id, sample in iter_samples(data, per_bundle=per_bundle):
            query = str(sample.get("query") or "")
            expected_tags = tuple(str(tag) for tag in sample.get("expectedTags", []) if tag)
            start = time.perf_counter()
            rows, _ = bridge._search_kr_tags_with_translation(query, top_limit)
            durations.append((time.perf_counter() - start) * 1000.0)
            checked += 1
            actual_tags = tuple(str(row.get("tag") or "") for row in rows[:top_limit])
            if not any(tag in actual_tags for tag in expected_tags):
                failures.append(
                    EvalFailure(bundle_id, query, expected_tags, actual_tags, "expected tag missing")
                )
                continue
            top_row = rows[0] if rows else {}
            if top_row.get("candidateType") == "translation_hint" or top_row.get("insertPolicy") == "manual":
                failures.append(
                    EvalFailure(bundle_id, query, expected_tags, actual_tags, "manual hint ranked first")
                )
                continue
            if any(has_excluded_category(row.get("group", "")) for row in rows[:EXCLUDED_RESULT_TOP_LIMIT]):
                failures.append(
                    EvalFailure(bundle_id, query, expected_tags, actual_tags, "excluded category ranked top3")
                )
    finally:
        remote_api_server.korean_to_english = original_translator

    sorted_durations = sorted(durations)
    p95 = sorted_durations[min(len(sorted_durations) - 1, int(len(sorted_durations) * 0.95))] if sorted_durations else 0.0
    return {
        "checked": checked,
        "failed": len(failures),
        "failures": failures,
        "total_ms": sum(durations),
        "median_ms": statistics.median(durations) if durations else 0.0,
        "p95_ms": p95,
        "max_ms": max(durations) if durations else 0.0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Korean autocomplete regression fixture.")
    parser.add_argument("--fixture", default=str(FIXTURE_PATH), help="Fixture JSON path.")
    parser.add_argument("--per-bundle", type=int, default=None, help="Limit samples per bundle.")
    parser.add_argument("--top-limit", type=int, default=DEFAULT_TOP_LIMIT, help="Autocomplete rows to inspect.")
    parser.add_argument("--max-p95-ms", type=float, default=250.0, help="Fail when per-query p95 exceeds this budget.")
    return parser.parse_args()


def main() -> int:
    configure_stdout()
    args = parse_args()
    data = load_fixture(args.fixture)
    summary = evaluate_fixture(data, per_bundle=args.per_bundle, top_limit=args.top_limit)
    print("Autocomplete regression evaluation")
    print(f"- checked: {summary['checked']}")
    print(f"- failed: {summary['failed']}")
    print(
        f"- timing: total={summary['total_ms']:.2f}ms "
        f"median={summary['median_ms']:.3f}ms p95={summary['p95_ms']:.3f}ms max={summary['max_ms']:.3f}ms"
    )
    for failure in summary["failures"][:20]:
        print(
            f"- FAIL {failure.bundle_id} query={failure.query!r} "
            f"expected={list(failure.expected_tags)!r} actual={list(failure.actual_tags[:5])!r} "
            f"reason={failure.reason}"
        )
    if summary["failed"]:
        return 1
    if args.max_p95_ms and float(summary["p95_ms"]) > args.max_p95_ms:
        print(f"- FAIL p95 exceeded {args.max_p95_ms:.3f}ms")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
