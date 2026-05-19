from __future__ import annotations

import argparse
import re
import statistics
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legacy_desktop.core.remote_api_server import RemoteBridge
from core.tag_search_index import normalize_search_query


DEFAULT_QUERIES = [
    "와인 잔을 손에 쥐고있음",
    "화면을 바라보다",
    "옷 끝자락을 잡아당기기",
    "작은 하프 같은 악기",
    "커피 마시는 컵",
    "옷에 단 장식 핀",
    "손목에 따로 달린 소매",
    "얼굴 위에 앉음",
    "버스 안에 있음",
    "거미줄 타고 이동",
    "작은 강아지",
    "노란 강아지 캐릭터",
    "부적을 들고 있음",
    "물고기를 들고 있음",
    "망원경을 들고 있음",
    "파란 치마",
    "빛나는 갑옷",
    "귀까지 빨개짐",
    "방향 표시 화살표",
    "고기 꼬치구이",
    "얇게 썬 고기",
    "페인트 롤러 무기",
    "낙엽 여신",
    "동방 골동품 가게",
    "블아 아인",
]


FIXED_TRANSLATIONS = {
    "와인 잔을 손에 쥐고있음": "holding a wine glass in hand",
    "화면을 바라보다": "look at the screen",
    "옷 끝자락을 잡아당기기": "pulling the hem of clothes",
    "작은 하프 같은 악기": "a small harp-like instrument",
    "커피 마시는 컵": "a cup for drinking coffee",
    "옷에 단 장식 핀": "a decorative pin attached to clothes",
    "손목에 따로 달린 소매": "separate sleeves attached to the wrist",
    "얼굴 위에 앉음": "sitting on face",
    "버스 안에 있음": "inside a bus",
    "거미줄 타고 이동": "swinging on web",
    "작은 강아지": "small dog",
    "노란 강아지 캐릭터": "yellow dog character",
    "부적을 들고 있음": "holding charm",
    "물고기를 들고 있음": "holding fish",
    "망원경을 들고 있음": "holding telescope",
    "파란 치마": "blue skirt",
    "빛나는 갑옷": "glowing armor",
    "귀까지 빨개짐": "ear blush",
    "방향 표시 화살표": "direction arrow symbol",
    "고기 꼬치구이": "shish kebab",
    "얇게 썬 고기": "sliced meat",
    "페인트 롤러 무기": "paint roller weapon",
    "낙엽 여신": "fallen leaves goddess",
    "동방 골동품 가게": "touhou antique shop",
    "블아 아인": "blue archive ein",
}


KOREAN_WEAK_TOKENS = {
    "것",
    "같은",
    "하고",
    "있는",
    "있음",
    "있다",
    "하는",
    "하다",
    "하며",
    "마시는",
    "먹는",
    "단",
    "달린",
    "따로",
    "표시",
    "캐릭터",
}

KOREAN_PARTICLE_SUFFIXES = (
    "으로",
    "에서",
    "에게",
    "까지",
    "처럼",
    "보다",
    "하고",
    "하게",
    "한",
    "에",
    "을",
    "를",
    "이",
    "가",
    "은",
    "는",
    "의",
    "와",
    "과",
    "도",
    "만",
    "로",
)


@dataclass(frozen=True)
class TimedBlock:
    label: str
    count: int
    total_ms: float
    median_ms: float
    p95_ms: float
    max_ms: float


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
    return bridge


def configure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def now_ms() -> float:
    return time.perf_counter() * 1000.0


def percentile_95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]


def timed_block(label: str, queries: list[str], fn: Callable[[str], Any], repeats: int) -> TimedBlock:
    durations: list[float] = []
    total_start = now_ms()
    for _ in range(max(1, repeats)):
        for query in queries:
            start = now_ms()
            fn(query)
            durations.append(now_ms() - start)
    total_ms = now_ms() - total_start
    return TimedBlock(
        label=label,
        count=len(durations),
        total_ms=total_ms,
        median_ms=statistics.median(durations) if durations else 0.0,
        p95_ms=percentile_95(durations),
        max_ms=max(durations) if durations else 0.0,
    )


def normalize_korean_text(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^0-9a-z가-힣ㄱ-ㅎㅏ-ㅣ]+", " ", text)
    return " ".join(text.split())


def strip_korean_suffix(token: str) -> str:
    for suffix in KOREAN_PARTICLE_SUFFIXES:
        if token.endswith(suffix) and len(token) > len(suffix) + 1:
            return token[: -len(suffix)]
    return token


def korean_query_tokens(query: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in normalize_korean_text(query).split():
        for token in (raw, strip_korean_suffix(raw)):
            if len(token) < 2 or token in KOREAN_WEAK_TOKENS or token in seen:
                continue
            seen.add(token)
            tokens.append(token)
    return tokens


def loose_kr_metadata_search(bridge: RemoteBridge, query: str, limit: int = 12) -> list[dict[str, Any]]:
    tokens = korean_query_tokens(query)
    if not tokens:
        return []
    scored: list[tuple[float, int, str, dict[str, Any], list[str]]] = []
    for key, info in bridge._kr_tags_raw.items():
        tag = str(info.get("_tag") or key)
        desc = normalize_korean_text(info.get("description") or info.get("desc") or "")
        keywords = normalize_korean_text(info.get("keywords_kr") or info.get("keywords") or "")
        category = normalize_korean_text(info.get("group") or info.get("category") or "")
        blob = " ".join(part for part in (normalize_korean_text(tag), desc, keywords, category) if part)
        matched: list[str] = []
        score = 0.0
        for token in tokens:
            token_score = 0.0
            if token and token in normalize_korean_text(tag):
                token_score = max(token_score, 4.0)
            if token and token in keywords:
                token_score = max(token_score, 5.0)
            if token and token in desc:
                token_score = max(token_score, 3.0)
            if token and token in category:
                token_score = max(token_score, 1.0)
            if token_score:
                matched.append(token)
                score += token_score
        if not matched:
            continue
        coverage = len(matched) / max(1, len(tokens))
        if len(matched) < 2 and score < 5.0:
            continue
        score += coverage * 3.0
        freq = int(info.get("freq") or info.get("count") or 0)
        scored.append((score, freq, tag, info, matched))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    rows: list[dict[str, Any]] = []
    for score, freq, tag, info, matched in scored[:limit]:
        rows.append(
            {
                "tag": tag,
                "count": freq,
                "desc": info.get("description") or info.get("desc") or "",
                "group": info.get("group") or info.get("category") or "",
                "cat": info.get("_cat") or "",
                "_score": round(score, 3),
                "_matched": matched,
            }
        )
    return rows


def final_recommended_queries(translated: str, limit: int = 6) -> list[str]:
    queries: list[str] = []
    for level in RemoteBridge._translation_search_query_levels(None, translated):
        for query in level:
            if query not in queries:
                queries.append(query)
            if len(queries) >= limit:
                return queries
    return queries


def search_with_fixed_translation(
    bridge: RemoteBridge,
    query: str,
    limit: int = 12,
    *,
    reset_result_cache: bool = False,
) -> list[dict[str, Any]]:
    translated = FIXED_TRANSLATIONS.get(query, "")
    if translated:
        bridge._autocomplete_translation_cache[normalize_search_query(query)] = translated
    if reset_result_cache:
        bridge._autocomplete_result_cache.pop((normalize_search_query(query), int(limit or 0)), None)
    rows, _ = bridge._search_kr_tags_with_translation(query, limit)
    return rows


def search_translation_levels_with_fixed_translation(bridge: RemoteBridge, query: str) -> list[dict[str, Any]]:
    translated = normalize_search_query(FIXED_TRANSLATIONS.get(query, ""))
    if not translated:
        return []
    rows: list[dict[str, Any]] = []
    for query_level in RemoteBridge._translation_search_query_levels(None, translated):
        level_rows: list[dict[str, Any]] = []
        for translated_query in query_level:
            translated_query_size = len(translated_query.split())
            if translated_query_size <= 1:
                translated_query_limit = 2
            elif translated_query_size == 2:
                translated_query_limit = 4
            else:
                translated_query_limit = 6
            level_rows.extend(bridge._search_kr_tags(translated_query, translated_query_limit))
        if level_rows:
            rows = level_rows
            break
    return rows[:12]


def first_tags(rows: list[dict[str, Any]], limit: int = 3) -> str:
    tags = [str(row.get("tag") or "") for row in rows[:limit] if row.get("tag")]
    return ", ".join(tags) if tags else "-"


def schema_rows(rows: list[dict[str, Any]], limit: int = 3) -> str:
    values: list[str] = []
    for row in rows[:limit]:
        tag = str(row.get("tag") or "")
        if not tag:
            continue
        candidate = row.get("candidate") if isinstance(row.get("candidate"), dict) else {}
        candidate_type = row.get("candidateType") or candidate.get("type") or "-"
        source = row.get("source") or candidate.get("source") or "-"
        score = row.get("autocompleteScore") or candidate.get("score")
        try:
            score_text = f"{float(score):.3f}"
        except (TypeError, ValueError):
            score_text = "-"
        values.append(f"{tag} ({candidate_type}/{source}/{score_text})")
    return ", ".join(values) if values else "-"


def print_cost_table(blocks: list[TimedBlock]) -> None:
    print("\nCost summary")
    print("| block | calls | total ms | median ms | p95 ms | max ms |")
    print("|---|---:|---:|---:|---:|---:|")
    for block in blocks:
        print(
            f"| {block.label} | {block.count} | {block.total_ms:.2f} | "
            f"{block.median_ms:.3f} | {block.p95_ms:.3f} | {block.max_ms:.3f} |"
        )


def print_sample_results(bridge: RemoteBridge, queries: list[str]) -> None:
    print("\nSample result comparison")
    print("| query | current | fixed translation levels | indexed KR metadata | loose KR metadata | schema-aware final | final recommended |")
    print("|---|---|---|---|---|---|---|")
    for query in queries:
        current = bridge._search_kr_tags(query, 12)
        translated_rows = search_translation_levels_with_fixed_translation(bridge, query)
        indexed_rows = bridge._search_kr_metadata_fallback(query, 12)
        loose_rows = loose_kr_metadata_search(bridge, query, 12)
        final_rows = search_with_fixed_translation(bridge, query, 12, reset_result_cache=True)
        fallback = final_recommended_queries(FIXED_TRANSLATIONS.get(query, ""))
        print(
            "| "
            + " | ".join(
                [
                    query,
                    first_tags(current),
                    first_tags(translated_rows),
                    first_tags(indexed_rows),
                    first_tags(loose_rows),
                    schema_rows(final_rows),
                    ", ".join(fallback[:3]) if fallback else "-",
                ]
            )
            + " |"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure Remote Web autocomplete fallback costs without mutating data.",
    )
    parser.add_argument("--repeats", type=int, default=5, help="Repeats per query for timing blocks.")
    parser.add_argument("--limit", type=int, default=12, help="Search limit for result sampling.")
    parser.add_argument(
        "--network-translation",
        action="store_true",
        help="Also measure real korean_to_english-backed _search_kr_tags_with_translation once per query.",
    )
    return parser.parse_args()


def main() -> int:
    configure_stdout()
    args = parse_args()
    bridge = make_bridge()
    warm_start = now_ms()
    bridge._load_kr_tags()
    warm_ms = now_ms() - warm_start
    metadata_warm_start = now_ms()
    bridge._search_kr_metadata_fallback("화면을 바라보다", args.limit)
    metadata_warm_ms = now_ms() - metadata_warm_start
    queries = list(DEFAULT_QUERIES)

    print("Autocomplete fallback cost measurement")
    print(f"- query count: {len(queries)}")
    print(f"- repeats: {args.repeats}")
    print(f"- index warmup ms: {warm_ms:.2f}")
    print(f"- metadata fallback first-touch ms: {metadata_warm_ms:.2f}")
    print(f"- raw tag records: {len(bridge._kr_tags_raw):,}")
    print(f"- fixed translations: {len(FIXED_TRANSLATIONS):,}")

    blocks = [
        timed_block("current _search_kr_tags", queries, lambda q: bridge._search_kr_tags(q, args.limit), args.repeats),
        timed_block(
            "fixed translation levels",
            queries,
            lambda q: search_translation_levels_with_fixed_translation(bridge, q),
            args.repeats,
        ),
        timed_block("indexed KR metadata fallback", queries, lambda q: bridge._search_kr_metadata_fallback(q, args.limit), args.repeats),
        timed_block("loose KR metadata scan", queries, lambda q: loose_kr_metadata_search(bridge, q, args.limit), args.repeats),
    ]
    blocks.append(
        timed_block(
            "schema-aware final fallback",
            queries,
            lambda q: search_with_fixed_translation(bridge, q, args.limit, reset_result_cache=True),
            args.repeats,
        )
    )
    for query in queries:
        search_with_fixed_translation(bridge, query, args.limit, reset_result_cache=True)
    blocks.append(
        timed_block(
            "schema-aware cached result",
            queries,
            lambda q: search_with_fixed_translation(bridge, q, args.limit),
            args.repeats,
        )
    )
    blocks.append(
        timed_block(
            "final recommended generation",
            queries,
            lambda q: final_recommended_queries(FIXED_TRANSLATIONS.get(q, "")),
            args.repeats,
        )
    )
    if args.network_translation:
        blocks.append(
            timed_block(
                "real translation + current fallback",
                queries,
                lambda q: bridge._search_kr_tags_with_translation(q, args.limit),
                1,
            )
        )
        blocks.append(
            timed_block(
                "cached translation + current fallback",
                queries,
                lambda q: bridge._search_kr_tags_with_translation(q, args.limit),
                args.repeats,
            )
        )

    print_cost_table(blocks)
    print_sample_results(bridge, queries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
