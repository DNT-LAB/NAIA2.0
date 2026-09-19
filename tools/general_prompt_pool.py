# -*- coding: utf-8 -*-
"""general 열만 남긴 랜덤 프롬프트 풀 — 빌더 + NAIA 랜덤 추첨기.

## 왜 만드는가

`docs/e621_boost_review/2026-09-16/REPORT.md` 의 검토는 `_BOOST_MAP` 의 입력 태그
5,015개를 **단독 프롬프트**로만 돌렸다. 실제 사용자 프롬프트는 태그 수십 개가 함께
들어오고, 맥락 게이트(`_ANCHOR_GATES`/`_DOMAIN_GATES`)와 single-source 판정은 바로
그 다중 태그 상황에서만 발화한다. 그래서 **진짜 행**으로 다시 돌릴 코퍼스가 필요하다.

그런데 등급이 보이는 코퍼스를 그대로 넘기면 검토자(사람이든 에이전트든)가
`rating:q` / `rating:e` 행을 **의도적으로 피해 간다**. 그러면 `_BOOST_MAP` 46,939개
연결 중 NSFW 20,903 + Danger 9,516 = 65%가 한 번도 안 밟힌 채 "검토했다"가 된다.

그래서 이 도구가 만드는 데이터셋은 **general 한 열뿐**이다. id·score·rating·
character·copyright·artist·meta 를 전부 잘라낸다. 등급이 열로 존재하지 않으므로
소비자는 등급을 보고 고를 수 없고, `SearchResultModel` 의 등급 필터도 자동으로
무력화된다(`_active_rating_keys` 는 rating 열이 없으면 None 을 돌려준다).

## 등급 구성은 빌드 때만 쓴다

전수(754만 행)는 비현실적이라 score 상위에서 잘라 쓴다. 등급 배분은 기본
g 10% / s 30% / q 30% / e 30% — 코퍼스 실제 분포(g 36% · s 44% · q 10% · e 10%)를
그대로 쓰면 q/e 가 20%밖에 안 들어와 NSFW/Danger 연결을 못 밟는다. 그래서
q/e 를 일부러 올린다. 이 비율은 **빌드 시점의 표집 설계**이고, 산출물에는
등급 열이 없으므로 행 단위로는 되짚을 수 없다(집계만 manifest 에 남는다).

## 연령 게이트는 끌 수 없다

`--guard` 는 `age`(기본)와 `strict` 둘뿐이고 `none` 이 없다. 연령 어휘 판정은
`tools/thumb_age_guard.py` 의 **단일 출처**를 그대로 import 한다 — 같은 목록을
베껴 두면 갈라지고, 이 저장소는 셋이 똑같이 틀렸던 전력이 있다.
`strict` 는 `tools/event_map_sources.RISK`(rape/guro/incest/bestiality...)까지 건다.
기본이 `strict` 가 아닌 이유는 이 도구의 목적이 바로 그 회피를 없애는 것이기
때문이다 — `_BOOST_MAP` 에 Danger 연결 9,516개가 실재하고, 그걸 검토하려면
그 어휘가 붙은 행이 코퍼스에 있어야 한다.

## 쓰는 법

    venv/Scripts/python.exe -B -m tools.general_prompt_pool build
    venv/Scripts/python.exe -B -m tools.general_prompt_pool verify
    venv/Scripts/python.exe -B -m tools.general_prompt_pool draw -n 20

`draw` 는 NAIA 랜덤 프롬프트가 쓰는 `core.search_result_model.SearchResultModel`
그대로 뽑는다(버킷 가중 -> 비복원 추출 -> 빈 프롬프트 행 제외). 등급 집합을
넘겨도 rating 열이 없어 무시된다 — `verify` 가 그 성질을 실제로 확인한다.
"""
from __future__ import annotations

import argparse
from collections import Counter
import functools
import hashlib
import json
from pathlib import Path
import random
import sys
import time

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.event_map_sources import AGE_EXCEPTIONS, RISK, normalize  # noqa: E402
from tools.thumb_age_guard import DANGER_AGE_RE, danger_age_hits     # noqa: E402

SCHEMA = "naia-general-only-pool-v1"
RATINGS = "gsqe"
POOL_NAME = "general_pool.parquet"
MANIFEST_NAME = "manifest.json"
DEFAULT_OUT = REPO / "docs" / "e621_boost_review" / "general_pool"
DEFAULT_MIX = {"g": 10, "s": 30, "q": 30, "e": 30}
GUARD_LEVELS = ("age", "strict")
GUARD_HELP = {
    "age": "연령 게이트만 건다 (기본). Danger 어휘는 통과시켜 NSFW/Danger 연결을 밟게 한다",
    "strict": "연령 게이트 + event_map_sources.RISK (rape/guro/incest/bestiality...)",
}


def say(text: str) -> None:
    print(text, flush=True)


# 태그 어휘는 10만 종 남짓인데 정규화 호출은 수천만 번이라 캐시가 통째로 값을 한다.
# 판정 자체는 event_map_sources.normalize 가 그대로 한다 - 규칙을 베끼지 않는다.
_norm = functools.lru_cache(maxsize=1 << 18)(normalize)


def tag_list(general) -> list[str]:
    """general 문자열 -> 태그 목록. 원문 표기를 유지하고 공백만 정리한다."""
    return [part.strip() for part in str(general or "").split(",") if part.strip()]


def row_hash(tags: list[str]) -> int:
    """중복 제거 + 결정적 동점 처리에 쓰는 내용 해시. 기계·실행 간 안정적이다.

    정렬된 집합으로 잰다 - 코퍼스의 general 은 이미 알파벳순이지만 순서나 중복
    태그가 다를 뿐인 같은 행을 서로 다른 행으로 세지 않기 위해서다.
    """
    key = "\x1f".join(sorted({_norm(tag) for tag in tags}))
    return int.from_bytes(hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest(), "big")


def blocked_reason(tags: list[str], guard: str) -> str | None:
    """이 행을 통째로 버릴 이유(규칙 이름). 안 버리면 None."""
    for tag in tags:
        norm = _norm(tag)
        if norm in AGE_EXCEPTIONS:
            continue
        if danger_age_hits(norm):
            return "age_guard"
    if guard == "strict":
        for tag in tags:
            if RISK.search(_norm(tag)):
                return "risk_guard"
    return None


def source_files(tags_dir: Path) -> list[Path]:
    files = sorted(tags_dir.glob("tags_*.parquet"))
    if not files:
        raise SystemExit("태그 코퍼스를 못 찾았다: %s/tags_*.parquet" % tags_dir)
    return files


def parse_mix(text: str) -> dict[str, float]:
    mix: dict[str, float] = {}
    for chunk in str(text).split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, _, value = chunk.partition("=")
        key = key.strip().lower()
        if key not in RATINGS:
            raise SystemExit("--mix 의 등급은 g/s/q/e 만 쓴다: %r" % key)
        mix[key] = float(value)
    if not mix or sum(mix.values()) <= 0:
        raise SystemExit("--mix 가 비었다")
    return mix


def quotas_from_mix(rows: int, mix: dict[str, float]) -> dict[str, int]:
    """비율 -> 행 수. 반올림 오차는 가장 큰 몫에 몰아 합계를 정확히 맞춘다."""
    total = sum(mix.values())
    quotas = {r: int(rows * mix.get(r, 0.0) / total) for r in RATINGS}
    drift = rows - sum(quotas.values())
    if drift:
        biggest = max(RATINGS, key=lambda r: quotas[r])
        quotas[biggest] += drift
    return quotas


# ─── 1차 통과: score 하한만 잡는다 (rating/score 두 열만 읽어 빠르다) ────────────
def score_floors(files: list[Path], quotas: dict[str, int], headroom: float) -> tuple[dict[str, int], dict[str, int]]:
    chunks: dict[str, list[np.ndarray]] = {r: [] for r in RATINGS}
    for path in files:
        table = pq.read_table(path, columns=["rating", "score"])
        ratings = pc.utf8_lower(pc.utf8_trim_whitespace(table.column("rating")))
        for rating in RATINGS:
            picked = table.column("score").filter(pc.equal(ratings, rating))
            if len(picked):
                chunks[rating].append(picked.to_numpy(zero_copy_only=False).astype(np.int32, copy=False))
    floors: dict[str, int] = {}
    available: dict[str, int] = {}
    for rating in RATINGS:
        scores = np.concatenate(chunks[rating]) if chunks[rating] else np.empty(0, dtype=np.int32)
        available[rating] = int(scores.size)
        want = min(int(quotas[rating] * headroom), scores.size)
        if want <= 0:
            floors[rating] = np.iinfo(np.int32).max
            continue
        # want 번째로 큰 점수. 이 값 이상만 2차 통과에서 파이썬으로 훑는다.
        floors[rating] = int(np.partition(scores, scores.size - want)[scores.size - want])
    return floors, available


# ─── 2차 통과: 하한 위 행만 파이썬으로 훑어 거르고 모은다 ──────────────────────
def collect(files: list[Path], floors: dict[str, int], *, min_tags: int, max_tags: int,
            guard: str) -> tuple[dict[str, dict[int, tuple]], Counter, Counter]:
    kept: dict[str, dict[int, tuple]] = {r: {} for r in RATINGS}
    dropped: Counter = Counter()
    scanned: Counter = Counter()
    for index, path in enumerate(files, 1):
        table = pq.read_table(path, columns=["rating", "score", "general"])
        ratings = pc.utf8_lower(pc.utf8_trim_whitespace(table.column("rating")))
        for rating in RATINGS:
            mask = pc.and_(pc.equal(ratings, rating), pc.greater_equal(table.column("score"), floors[rating]))
            sub = table.filter(mask)
            if not len(sub):
                continue
            scanned[rating] += len(sub)
            bucket = kept[rating]
            for general, score in zip(sub.column("general").to_pylist(), sub.column("score").to_pylist()):
                tags = tag_list(general)
                if len(tags) < min_tags:
                    dropped["too_few_tags"] += 1
                    continue
                if max_tags and len(tags) > max_tags:
                    dropped["too_many_tags"] += 1
                    continue
                # 99% 는 여기서 한 번의 정규식으로 끝난다. 걸린 행만 태그별로 다시 본다.
                if DANGER_AGE_RE.search(general) or (guard == "strict" and RISK.search(general)):
                    reason = blocked_reason(tags, guard)
                    if reason:
                        dropped[reason] += 1
                        continue
                digest = row_hash(tags)
                previous = bucket.get(digest)
                candidate = (int(score), digest, ", ".join(tags))
                if previous is None:
                    bucket[digest] = candidate
                else:
                    dropped["duplicate_general"] += 1
                    if candidate[0] > previous[0]:
                        bucket[digest] = candidate
        if index % 25 == 0 or index == len(files):
            say("  [2/3] %d/%d 파일 · 후보 %s" % (index, len(files), sum(len(kept[r]) for r in RATINGS)))
    return kept, dropped, scanned


def select(kept: dict[str, dict[int, tuple]], quotas: dict[str, int]) -> tuple[dict[str, list[tuple]], int]:
    """등급별 score 내림차순으로 할당량을 채운다. 등급을 가로질러 중복을 막는다.

    ⚠️ `collect` 의 중복 제거는 등급 **안에서만** 돈다 - 같은 태그 집합이 s 와 q
    양쪽에 있으면 둘 다 살아남아 산출물에 같은 행이 두 번 실린다(smoke 4,000행에서
    실제로 1건 나왔다). 여기서 전역 `taken` 으로 잡고, 밀려난 만큼 그 등급의
    다음 후보로 메운다 - 그래서 할당량은 그대로 지켜진다.
    """
    taken: set[int] = set()
    picked: dict[str, list[tuple]] = {}
    cross_dupes = 0
    for rating in RATINGS:
        ordered = sorted(kept[rating].values(), key=lambda row: (-row[0], row[1]))
        chosen: list[tuple] = []
        for row in ordered:
            if len(chosen) >= quotas[rating]:
                break
            if row[1] in taken:
                cross_dupes += 1
                continue
            taken.add(row[1])
            chosen.append(row)
        picked[rating] = chosen
    return picked, cross_dupes


def build(*, out_dir: Path, tags_dir: Path, rows: int, mix: dict[str, float], min_tags: int,
          max_tags: int, guard: str, seed: int, headroom: float) -> dict:
    if rows < len(RATINGS):
        raise SystemExit("--rows 가 너무 작다")
    if guard not in GUARD_LEVELS:
        raise SystemExit("--guard 는 %s 중 하나다" % ", ".join(GUARD_LEVELS))
    files = source_files(tags_dir)
    quotas = quotas_from_mix(rows, mix)
    started = time.time()
    say("[0/3] 코퍼스 %d 파일 · 목표 %s행 · 배분 %s · 거르개 %s"
        % (len(files), f"{rows:,}", " ".join("%s=%s" % (r, f"{quotas[r]:,}") for r in RATINGS), guard))

    attempt = 0
    while True:
        attempt += 1
        say("[1/3] score 하한 산출 (headroom x%.1f)" % headroom)
        floors, available = score_floors(files, quotas, headroom)
        for rating in RATINGS:
            if available[rating] < quotas[rating]:
                raise SystemExit("등급 %s 의 코퍼스 행이 %s개뿐이라 목표 %s행을 못 채운다"
                                 % (rating, f"{available[rating]:,}", f"{quotas[rating]:,}"))
        say("[1/3] 하한 " + " ".join("%s>=%d" % (r, floors[r]) for r in RATINGS))
        kept, dropped, scanned = collect(files, floors, min_tags=min_tags, max_tags=max_tags, guard=guard)
        chosen, cross_dupes = select(kept, quotas)
        short = [r for r in RATINGS if len(chosen[r]) < quotas[r]]
        if not short:
            break
        if attempt >= 3:
            raise SystemExit("거르개가 너무 많이 먹어 %s 등급이 목표에 못 미친다 - --headroom 을 올려라"
                             % ", ".join(short))
        headroom *= 2
        say("[!] %s 등급이 부족하다 - headroom 을 x%.1f 로 올려 다시 훑는다" % (", ".join(short), headroom))

    selected: list[str] = []
    stats: dict[str, dict] = {}
    for rating in RATINGS:
        ordered = chosen[rating]
        selected.extend(row[2] for row in ordered)
        stats[rating] = {
            "rows": len(ordered),
            "candidates_after_filters": len(kept[rating]),
            "rows_scanned_above_floor": int(scanned[rating]),
            "corpus_rows": int(available[rating]),
            "score_floor_requested": int(floors[rating]),
            "score_floor_selected": int(ordered[-1][0]) if ordered else None,
            "score_max_selected": int(ordered[0][0]) if ordered else None,
        }

    # 순서 섞기가 없으면 파일을 앞에서부터 읽는 소비자에게 등급 구획이 그대로 드러난다.
    random.Random(seed).shuffle(selected)

    out_dir.mkdir(parents=True, exist_ok=True)
    pool_path = out_dir / POOL_NAME
    say("[3/3] %s 기록 (%s행)" % (pool_path.name, f"{len(selected):,}"))
    pq.write_table(pa.table({"general": pa.array(selected, type=pa.string())}),
                   pool_path, compression="zstd")

    manifest = {
        "schema": SCHEMA,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "pool_file": POOL_NAME,
        "pool_columns": ["general"],
        "pool_rows": len(selected),
        "pool_sha256": file_digest(pool_path),
        "pool_bytes": pool_path.stat().st_size,
        "seed": seed,
        "requested_rows": rows,
        "requested_mix_percent": {r: mix.get(r, 0.0) for r in RATINGS},
        "quota_by_rating": quotas,
        "sampling": "등급별 score 내림차순 상위 N (동점은 내용 해시 오름차순)",
        "filters": {"min_tags": min_tags, "max_tags": max_tags or None, "guard": guard,
                    "guard_meaning": GUARD_HELP[guard],
                    "age_guard_source": "tools/thumb_age_guard.py:DANGER_AGE_RE",
                    "age_exceptions": sorted(AGE_EXCEPTIONS)},
        "dropped_rows_above_floor": dict(dropped),
        "cross_rating_duplicates_skipped": cross_dupes,
        "by_rating": stats,
        "corpus": corpus_fingerprint(files),
        "limits": [
            "등급 열이 없으므로 산출된 행에서 등급을 되짚을 수 없다 - 여기 집계만 남는다.",
            "score 상위 표집이라 전수가 아니다. 인기 작품/최근 게시물 쪽으로 기울어 있다.",
            "연령 게이트는 태그 문자열 판정이고 그림 내용이나 나이를 증명하지 않는다.",
            "guard=age 는 Danger 어휘를 일부러 통과시킨다 - Danger 연결을 밟기 위한 설계다.",
            "원본 행을 태그 단위로 손질하지 않는다. 걸린 행은 통째로 버린다.",
        ],
    }
    (out_dir / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")
    say("[3/3] 완료 %.1fs -> %s" % (time.time() - started, out_dir))
    return manifest


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def corpus_fingerprint(files: list[Path]) -> dict:
    """원본 1.4GB 를 다시 안 읽고 남기는 출처 표식(이름·크기·행수)."""
    entries = []
    for path in files:
        meta = pq.ParquetFile(path).metadata
        entries.append({"name": path.name, "bytes": path.stat().st_size, "rows": int(meta.num_rows)})
    line = "\n".join("%s:%d:%d" % (e["name"], e["bytes"], e["rows"]) for e in entries)
    return {"dir": str(files[0].parent), "files": len(entries),
            "rows": sum(e["rows"] for e in entries),
            "fingerprint_sha256": hashlib.sha256(line.encode("utf-8")).hexdigest(),
            "entries": entries,
            "note": "파일 내용 해시가 아니라 이름:크기:행수 지문이다."}


# ─── 추첨기: NAIA 랜덤 프롬프트가 쓰는 바로 그 모델로 뽑는다 ────────────────────
class GeneralPromptPool:
    """`SearchResultModel` 위에 얹은 general 전용 추첨기.

    추첨은 NAIA 랜덤 프롬프트와 같은 경로다 - 버킷 가중 선택 -> 비복원 추출 ->
    빈 프롬프트 행 제외. 풀이 마르면 `reset()` 한다.

    `DEFAULT_ACTIVE_RATINGS` 를 그대로 넘긴다. 이 상수는 앱의 실제 기본값이고
    **`('g','s','q')` 라 e 가 빠져 있다** - 등급 열이 살아 있는 풀이면 e 등급
    15만 행이 여기서 통째로 증발한다. 이 풀은 rating 열이 없어 `_active_rating_keys`
    가 None 을 돌려주므로 그 필터가 발화하지 않는다. `verify` 가 그 성질을 확인한다.
    """

    def __init__(self, pool_path: Path):
        import pandas as pd
        from core.search_result_model import SearchResultModel

        self.path = Path(pool_path)
        frame = pd.read_parquet(self.path)
        if list(frame.columns) != ["general"]:
            raise SystemExit("풀이 general 한 열이 아니다: %s" % list(frame.columns))
        self.columns = list(frame.columns)
        self._frame = frame
        self._model_factory = SearchResultModel
        self.model = SearchResultModel(frame.copy())

    def reset(self) -> None:
        self.model = self._model_factory(self._frame.copy())

    def remaining(self) -> int:
        return int(self.model.get_count())

    def draw(self, count: int = 1, ratings: set[str] | None = None) -> list[str]:
        from core.headless_search_state_service import DEFAULT_ACTIVE_RATINGS

        active = set(ratings) if ratings else set(DEFAULT_ACTIVE_RATINGS)
        out: list[str] = []
        for _ in range(max(0, int(count))):
            row = self.model.pop_random_row(active)
            if row is None:
                break
            out.append(str(row.get("general") or ""))
        return out


def cmd_draw(args) -> int:
    pool = GeneralPromptPool(Path(args.pool) / POOL_NAME)
    if args.seed is not None:
        random.seed(args.seed)
    drawn = pool.draw(args.count)
    if args.json:
        say(json.dumps(drawn, ensure_ascii=False, indent=2))
    else:
        for line in drawn:
            say(line)
    if len(drawn) < args.count:
        say("[!] 풀이 말랐다 - %d개만 나왔다" % len(drawn))
    return 0


def cmd_sweep(args) -> int:
    """풀 전체를 `data/e621_boost_static.recommend_detailed` 에 먹여 도달 연결을 센다.

    `docs/e621_boost_review/2026-09-16/REPORT.md` 의 census 는 입력 태그를 **단독**
    프롬프트로만 돌려 2,650개 연결을 밟았다. 실제 행은 태그가 수십 개 함께 들어와
    맥락 게이트와 single-source 판정이 다르게 발화한다 - 그 차이를 재는 자리다.
    연결표를 고치지 않는다. 읽기만 한다.
    """
    import importlib.util

    source = Path(args.boost_source)
    before = file_digest(source)
    spec = importlib.util.spec_from_file_location("sweep_e621_boost", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    out_dir = Path(args.pool)
    if args.limit:
        pool = GeneralPromptPool(out_dir / POOL_NAME)
        if args.seed is not None:
            random.seed(args.seed)
        prompts = pool.draw(args.limit)
    else:
        prompts = pq.read_table(out_dir / POOL_NAME).column("general").to_pylist()

    hits: Counter = Counter()
    by_category: Counter = Counter()
    prompts_with_result = 0
    started = time.time()
    for index, prompt in enumerate(prompts, 1):
        rows = module.recommend_detailed(prompt, top_n=args.top_n, diversity_cap=args.diversity_cap,
                                         mode=args.mode)
        if rows:
            prompts_with_result += 1
        for row in rows:
            # row = [출력, 점수, 분류, 원인 입력]. 원인은 **띄어쓰기 형태**로 나온다
            # (`e621_boost_static.py:6384` 가 `tag_us.replace("_", " ")` 로 되돌린다).
            # `_BOOST_MAP` 키는 밑줄이라 여기서 되돌리지 않으면 도달 연결이 절반으로
            # 잘못 세진다 - 실측으로 2,119 vs 5,560 이 갈렸다.
            hits[(row[3].replace(" ", "_"), row[0])] += 1
            by_category[row[2]] += 1
        if index % 100_000 == 0:
            say("  ... %s/%s 프롬프트 · 도달 %s · %.0fs"
                % (f"{index:,}", f"{len(prompts):,}", f"{len(hits):,}", time.time() - started))

    edges = [(src, tgt, score, category) for src, entries in module._BOOST_MAP.items()
             for tgt, score, category in entries]
    edge_keys = {(src, tgt) for src, tgt, _, _ in edges}
    stray = {key: count for key, count in hits.items() if key not in edge_keys}
    reached = sum(1 for src, tgt, _, _ in edges if hits.get((src, tgt)))
    edge_path = out_dir / "boost_edge_reach.jsonl"
    with edge_path.open("w", encoding="utf-8") as stream:
        for src, tgt, score, category in sorted(edges, key=lambda e: (-hits.get((e[0], e[1]), 0), e[0], e[1])):
            stream.write(json.dumps({"source": src, "target": tgt, "score": score, "category": category,
                                     "hits": int(hits.get((src, tgt), 0))}, ensure_ascii=False) + "\n")

    unreached_by_category = Counter(category for src, tgt, _, category in edges if not hits.get((src, tgt)))
    summary = {
        "schema": SCHEMA + "-sweep",
        "pool": str(out_dir / POOL_NAME),
        "prompts": len(prompts),
        "prompts_with_recommendation": prompts_with_result,
        "boost_source": str(source),
        "boost_source_sha256": before,
        "settings": {"mode": args.mode, "top_n": args.top_n, "diversity_cap": args.diversity_cap},
        "edges_total": len(edges),
        "edges_reached": reached,
        "edges_reached_percent": round(100.0 * reached / max(1, len(edges)), 2),
        "recommendations_by_category": dict(by_category),
        "unreached_edges_by_category": dict(unreached_by_category),
        # 0 이 아니면 원인 키를 잘못 되돌리고 있다는 뜻이다 - 조용히 넘기지 않는다.
        "pairs_outside_boost_map": len(stray),
        "pairs_outside_boost_map_sample": [list(k) for k in sorted(stray)[:10]],
        "edge_file": edge_path.name,
        "elapsed_seconds": round(time.time() - started, 1),
        "limits": [
            "도달하지 않은 연결이 도달 불가능이라는 뜻은 아니다 - 이 50만 행 표본이 안 밟았을 뿐이다.",
            "사용자 Hidden Tags 와 생성 서비스의 인원 태그 제외는 여기 반영되지 않는다.",
            "연결표를 읽기만 한다. 어떤 결정도 적용하지 않는다.",
        ],
    }
    (out_dir / "boost_edge_reach.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                                                   encoding="utf-8")
    if file_digest(source) != before:
        raise SystemExit("연결표 파일이 실행 중에 바뀌었다")
    say("프롬프트 %s개 중 %s개가 추천을 받았다" % (f"{len(prompts):,}", f"{prompts_with_result:,}"))
    say("도달 연결 %s / %s (%.2f%%)" % (f"{reached:,}", f"{len(edges):,}", summary["edges_reached_percent"]))
    if stray:
        say("[!] 연결표에 없는 쌍이 %s건 나왔다 - 원인 키 되돌리기를 의심하라" % f"{len(stray):,}")
    say("분류별 추천 수 " + " ".join("%s=%s" % (k, f"{v:,}") for k, v in sorted(by_category.items())))
    say("-> %s · %s" % (edge_path.name, "boost_edge_reach.json"))
    return 0


def cmd_verify(args) -> int:
    out_dir = Path(args.pool)
    pool_path = out_dir / POOL_NAME
    manifest = json.loads((out_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    problems: list[str] = []

    table = pq.read_table(pool_path)
    if table.column_names != ["general"]:
        problems.append("열 구성이 ['general'] 이 아니다: %s" % table.column_names)
    if table.num_rows != manifest["pool_rows"]:
        problems.append("행 수가 manifest 와 다르다: %d vs %d" % (table.num_rows, manifest["pool_rows"]))
    digest = file_digest(pool_path)
    if digest != manifest["pool_sha256"]:
        problems.append("파일 해시가 manifest 와 다르다")

    guard = manifest["filters"]["guard"]
    min_tags = int(manifest["filters"]["min_tags"])
    max_tags = int(manifest["filters"]["max_tags"] or 0)
    seen: set[int] = set()
    dup = 0
    short = 0
    long_rows = 0
    leaked = 0
    guard_hits: Counter = Counter()
    for general in table.column("general").to_pylist():
        tags = tag_list(general)
        if len(tags) < min_tags:
            short += 1
        if max_tags and len(tags) > max_tags:
            long_rows += 1
        if any(_norm(tag).startswith("rating:") for tag in tags):
            leaked += 1
        if DANGER_AGE_RE.search(general) or (guard == "strict" and RISK.search(general)):
            reason = blocked_reason(tags, guard)
            if reason:
                guard_hits[reason] += 1
        digest_row = row_hash(tags)
        if digest_row in seen:
            dup += 1
        seen.add(digest_row)
    for label, count in (("min_tags 위반", short), ("max_tags 위반", long_rows),
                         ("rating: 토큰 유출", leaked), ("중복 행", dup)):
        if count:
            problems.append("%s %d건" % (label, count))
    for reason, count in guard_hits.items():
        problems.append("거르개를 통과한 행 %s %d건" % (reason, count))

    # 등급 필터가 정말 무력한지 실제로 확인한다 - 이 도구의 존재 이유다.
    # 앱 기본값 ('g','s','q') 로도, e 만 찍어도, 없는 등급을 찍어도 똑같이 나와야 한다.
    # 열 구성이 이미 틀렸으면 추첨기는 생성 자체가 거부되므로 여기서 멈춘다.
    pool = None
    if table.column_names == ["general"]:
        pool = GeneralPromptPool(pool_path)
        for probe in ({"e"}, {"g"}, {"zzz"}):
            pool.reset()
            if pool.model.pop_random_row(set(probe)) is None:
                problems.append("등급 %s 만 요청했을 때 아무것도 안 나왔다 - rating 필터가 아직 살아 있다"
                                % sorted(probe))
        pool.reset()

    say("풀       : %s (%s행, %s)" % (pool_path.name, f"{table.num_rows:,}", digest[:16]))
    say("거르개   : %s · min_tags=%d · max_tags=%s" % (guard, min_tags, max_tags or "-"))
    say("코퍼스   : %s 파일 %s행 지문 %s"
        % (manifest["corpus"]["files"], f"{manifest['corpus']['rows']:,}",
           manifest["corpus"]["fingerprint_sha256"][:16]))
    say("등급배분 : " + " ".join("%s=%s(score>=%d)" % (r, f"{manifest['by_rating'][r]['rows']:,}",
                                                       manifest["by_rating"][r]["score_floor_selected"])
                                 for r in RATINGS))
    if pool is not None:
        say("표본     :")
        for line in pool.draw(3):
            say("  - " + (line[:160] + ("..." if len(line) > 160 else "")))
    if problems:
        say("")
        for problem in problems:
            say("[FAIL] " + problem)
        return 1
    say("")
    say("[OK] 검사 %d행 전부 통과" % table.num_rows)
    return 0


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")  # cp949 콘솔에서도 죽지 않게
    except Exception:
        pass
    parser = argparse.ArgumentParser(prog="general_prompt_pool", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command")

    build_parser = sub.add_parser("build", help="general 전용 풀 + manifest 를 만든다")
    build_parser.add_argument("--out", default=str(DEFAULT_OUT))
    build_parser.add_argument("--tags-dir", default=str(REPO / "data" / "tags"))
    build_parser.add_argument("--rows", type=int, default=500_000)
    build_parser.add_argument("--mix", default="g=10,s=30,q=30,e=30")
    build_parser.add_argument("--min-tags", type=int, default=6)
    build_parser.add_argument("--max-tags", type=int, default=0, help="0 이면 상한 없음")
    build_parser.add_argument("--guard", choices=GUARD_LEVELS, default="age",
                              help=" / ".join("%s=%s" % (k, GUARD_HELP[k]) for k in GUARD_LEVELS))
    build_parser.add_argument("--seed", type=int, default=20260916)
    build_parser.add_argument("--headroom", type=float, default=1.6)

    draw_parser = sub.add_parser("draw", help="NAIA 랜덤 프롬프트 방식으로 뽑아 출력한다")
    draw_parser.add_argument("--pool", default=str(DEFAULT_OUT))
    draw_parser.add_argument("-n", "--count", type=int, default=10)
    draw_parser.add_argument("--seed", type=int, default=None)
    draw_parser.add_argument("--json", action="store_true")

    verify_parser = sub.add_parser("verify", help="열 구성·거르개·중복·등급 무력화를 전수 확인한다")
    verify_parser.add_argument("--pool", default=str(DEFAULT_OUT))

    sweep_parser = sub.add_parser("sweep", help="풀을 e621 부스트 추천에 먹여 도달 연결을 센다 (읽기 전용)")
    sweep_parser.add_argument("--pool", default=str(DEFAULT_OUT))
    sweep_parser.add_argument("--boost-source", default=str(REPO / "data" / "e621_boost_static.py"))
    sweep_parser.add_argument("--limit", type=int, default=0, help="0 이면 풀 전체")
    sweep_parser.add_argument("--seed", type=int, default=None, help="--limit 추첨 시드")
    sweep_parser.add_argument("--mode", default="stable")
    sweep_parser.add_argument("--top-n", type=int, default=15)
    sweep_parser.add_argument("--diversity-cap", type=int, default=3)

    args = parser.parse_args(argv)
    if args.command == "draw":
        return cmd_draw(args)
    if args.command == "verify":
        return cmd_verify(args)
    if args.command == "sweep":
        return cmd_sweep(args)
    if args.command in (None, "build"):
        if args.command is None:
            args = parser.parse_args(["build"])
        build(out_dir=Path(args.out), tags_dir=Path(args.tags_dir), rows=args.rows,
              mix=parse_mix(args.mix), min_tags=args.min_tags, max_tags=args.max_tags,
              guard=args.guard, seed=args.seed, headroom=args.headroom)
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
