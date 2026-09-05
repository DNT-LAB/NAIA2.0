"""Offline vocabulary census and retrieval coverage through the real Chat route.

No model inference or network requests. Source membership, dictionary-keyword
self-retrieval and public lexical expectations are deliberately separate metrics.
All writable WebSessionContext state is isolated below the new output directory.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.tag_axis_registry import normalize_tag
from core.tag_knowledge import normalize_tag_key
from core.tag_search_index import normalize_search_query

HANGUL = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")
LANES = ("autocomplete", "semantic", "chat_adapter", "chat_tool")
CODE = (
    "core/tag_search_index.py", "core/tag_knowledge.py", "core/kr_tag_loader.py",
    "core/tag_axis_registry.py", "core/named_entity_groups.py", "core/llm_search_index.py",
    "core/ollama_chat_pipeline.py", "core/ollama_chat_agent.py", "core/ollama_chat_semantics.py",
    "core/ollama_chat_plan.py",
    "core/ollama_assistant_service.py", "core/web_session_context.py", "core/headless_context_bootstrap.py",
    "app/backend/runtime/paths.py", "app/backend/server/autocomplete_commands.py",
    "app/backend/server/ollama_chat_tools.py", "app/backend/server/ollama_routes.py",
    "tools/ollama_chat_agent_eval.py", "tools/tag_search_coverage_eval.py",
)
DATA = (
    "data/interactive_tags.json", "data/KR_tags.parquet", "data/e621_KR_tags.parquet",
    "data/e621_data", "data/danbooru_tag_counts_by_rating.json", "data/characteristic_list.txt",
    "data/clothes_list.txt", "data/color.txt", "artist_dictionary.py", "danbooru_character.py",
    "result_dict_copyright.py",
)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    default=str).encode("utf-8")).hexdigest()


def file_hash(path):
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def snapshot():
    files = {ROOT / name for name in (*CODE, *DATA)}
    for folder in ("data/tag_index", "data/taglist"):
        files.update(p for p in (ROOT / folder).glob("*") if p.is_file())
    return {p.relative_to(ROOT).as_posix(): file_hash(p) for p in sorted(files)}


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def keyword_parts(record):
    """Keep syntax origins, including brackets discarded by TagSearchIndex."""
    for field in ("keywords_kr", "keywords"):
        parts = [p.strip() for p in str(record.get(field, "") or "").split(",") if p.strip()]
        for i, part in enumerate(parts):
            kind = "label" if i == 0 and re.fullmatch(r"<[^<>]+>", part) else (
                "unknown" if "<" in part or ">" in part else "alias")
            query = normalize_search_query(part.replace("<", "").replace(">", ""))
            if HANGUL.search(query):
                yield kind, query


def walk_research(node, path=()):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from walk_research(value, (*path, key))
    elif isinstance(node, list):
        for row in node:
            if isinstance(row, dict) and row.get("tag"):
                yield path, row


def source_cohorts():
    import pyarrow.parquet as pq
    cohorts = {}
    for name in ("KR_tags", "e621_KR_tags"):
        rows = pq.read_table(ROOT / "data" / (name + ".parquet")).to_pylist()
        # Source parquet escapes literal parentheses; the production loader
        # removes those escapes before TagSearchIndex ever receives a record.
        cohorts[name] = {normalize_tag_key(row["tag"]) for row in rows if row.get("tag")}
        if name == "e621_KR_tags":
            cohorts[name + "_NSFW"] = {normalize_tag_key(row["tag"]) for row in rows
                                               if row.get("category") == "NSFW"}
    research = json.loads((ROOT / "data/e621_data").read_text(encoding="utf-8"))
    research_rows = list(walk_research(research))
    cohorts["e621_research_all"] = {normalize_tag_key(row["tag"]) for _, row in research_rows}
    cohorts["e621_research_General"] = {normalize_tag_key(row["tag"]) for path, row in research_rows
                                                   if path[:1] == ("General",)}
    cohorts["e621_research_General_NSFW"] = {normalize_tag_key(row["tag"]) for path, row in research_rows
                                                        if path[:2] == ("General", "NSFW")}
    return cohorts


def census(raw, index, general, out):
    merged = defaultdict(list)
    for key, record in raw.items():
        tag = normalize_tag(record.get("_tag") or record.get("tag") or key)
        merged[tag].append(record)
    general_tags = {row.tag for row in general._recs}
    cohorts = source_cohorts()
    cohorts["merged_all"] = set(merged)
    cohorts["merged_named_entities"] = {tag for tag, rs in merged.items()
        if any(r.get("_cat") in {"character", "artist", "copyright"} for r in rs)}
    cohorts["merged_other"] = set(merged) - cohorts["merged_named_entities"]
    cohorts["llm_eligible"] = general_tags
    summary = {name: Counter() for name in cohorts}
    source_counts, axis_counts = Counter(), Counter()
    sample_pool = defaultdict(set)
    all_tags = sorted(set().union(*cohorts.values()))
    fields = ["tag", "cohorts", "in_raw", "in_tag_index", "in_llm_index", "description",
              "korean_description", "korean_keyword", "korean_label", "korean_alias",
              "label_only_korean", "positive_count", "source", "axis", "cat"]
    with gzip.open(out / "membership.tsv.gz", "wt", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for tag in all_tags:
            entry, records = index.entry_for(tag), merged.get(tag, [])
            parts = set(item for record in records for item in keyword_parts(record))
            kinds = {kind for kind, _ in parts}
            membership = [name for name, tags in cohorts.items() if tag in tags]
            row = dict(tag=tag, cohorts="|".join(membership), in_raw=bool(records),
                in_tag_index=entry is not None, in_llm_index=tag in general_tags,
                description=bool(entry and entry.desc.strip()),
                korean_description=bool(entry and HANGUL.search(entry.desc)),
                korean_keyword=bool(parts), korean_label="label" in kinds,
                korean_alias="alias" in kinds, label_only_korean=kinds == {"label"},
                positive_count=bool(entry and entry.freq > 0), source=entry.source if entry else "",
                axis=entry.axis if entry else "", cat=entry.cat if entry else "")
            writer.writerow(row)
            for name in membership:
                summary[name]["total"] += 1
                summary[name].update({key: int(value) for key, value in row.items() if isinstance(value, bool)})
            if entry:
                source_counts[entry.source] += 1
                axis_counts[entry.axis] += 1
                sample_pool[(entry.source, "canonical")].add((tag, tag))
                for kind, query in parts:
                    if 0 < len(query) <= 160:
                        sample_pool[(entry.source, kind)].add((tag, query))
    return dict(summary), sample_pool, {"source_counts": source_counts, "axis_counts": axis_counts,
        "raw_records": len(raw), "normalized_raw_tags": len(merged),
        "tag_index_entries": len(index._entries), "llm_index_entries": len(general_tags)}


def deterministic_samples(pool, count):
    cases, strata = [], []
    for (source, kind), pairs in sorted(pool.items()):
        eligible = [p for p in pairs if 0 < len(p[1]) <= 160]
        ordered = sorted(eligible, key=lambda p: (digest([source, kind, *p]), p))
        selected = ordered[:count]
        strata.append({"source": source, "kind": kind, "population_pairs": len(pairs),
                       "eligible_pairs": len(eligible), "sample_pairs": len(selected)})
        for tag, query in selected:
            cases.append({"id": "self_" + digest([source, kind, tag, query])[:20],
                "category": f"source={source};origin={kind}", "query": query,
                "expected_any": [tag], "forbidden": [], "source": source, "origin": kind,
                "expectation_basis": "Dictionary self-retrieval; source keyword is NOT certified meaning"})
    return cases, strata


class SearchProbe:
    """Replace only native model transport; production routing/filtering runs."""
    def __init__(self):
        from core.ollama_assistant_service import OllamaAssistantService
        self.queries, self.turn, self.output = [], 0, None
        def response(body):
            return SimpleNamespace(status_code=200, json=lambda: body)
        def post(path, payload, **kwargs):
            if path == "/api/show":
                return response({"capabilities": ["completion", "thinking", "tools"]})
            if path != "/api/chat":
                raise AssertionError("Unexpected model endpoint: " + path)
            self.turn += 1
            if self.turn == 1:
                name, arguments = 'plan_search', {
                    'mode': 'lookup', 'output': {'format': 'tags', 'language': 'en'}, 'actors': [],
                    'requirements': [{'id': 'probe', 'source': '사전 검색 경로를 측정합니다.',
                                      'kind': 'entity', 'actors': [], 'depends_on': []}],
                    'searches': [{'requirement_ids': ['probe'], 'tool': 'search_tags', 'query': q}
                                 for q in self.queries]}
            elif self.turn == 2:
                self.output = next(json.loads(m["content"]) for m in reversed(payload["messages"])
                    if m.get("role") == "tool" and m.get("tool_name") == "plan_search")
                if self.output.get('status') != 'error':
                    self.output = {'status': 'ok', 'searches': [s for result in self.output['results']
                                                             for s in result.get('searches', [])]}
                # Probe measures returned candidates only, not semantic finish.
                name, arguments = "finish", {"kind": "clarification", "summary": "검색 경로 측정 완료",
                                             'question': '어느 검색 결과를 검토할까요?',
                                             "actors": [], "relations": [], "common_tags": []}
            else:
                raise AssertionError("Probe must finish in two native turns")
            return response({"message": {"role": "assistant", "tool_calls": [
                {"function": {"name": name, "arguments": arguments}}]}})
        self.service = OllamaAssistantService(default_model="coverage:think", version_probe=lambda: "offline-probe",
            http_post=post, http_get=lambda *a, **k: response({"models": [{"name": "coverage:think"}]}))

    def run(self, client, queries):
        self.queries, self.turn, self.output = queries, 0, None
        response = client.post("/api/ollama/chat", json={"messages": [
            {"role": "user", "content": "사전 검색 경로를 측정합니다. 장면을 생성하지 않습니다."}]})
        response.raise_for_status()
        body = response.json()
        if not body.get("ok") or self.output is None or self.output.get("status") == "error":
            raise AssertionError({"route_result": body, "tool_output": self.output})
        actual = {row["query"]: row for row in self.output["searches"]}
        if set(actual) != set(queries):
            raise AssertionError("The route omitted a requested query")
        return actual


def tags(rows):
    return [normalize_tag(row["tag"]) for row in rows]


def measure_case(case, results, index, general_tags):
    expected = set(map(normalize_tag, case.get("expected_any", [])))
    out = {"case": case, "expected_in_index": sorted(t for t in expected if index.entry_for(t)),
           "expected_in_llm": sorted(expected & general_tags), "lanes": results}
    for lane in LANES:
        row = results[lane]
        actual = tags(row["rows"])
        rank = next((i + 1 for i, tag in enumerate(actual) if tag in expected), None)
        row.update(rank=rank, hit1=rank == 1 if expected else None,
                   hit6=rank is not None and rank <= 6 if expected else None,
                   returned=len(actual), forbidden_hits=sorted(set(actual) & set(case.get("forbidden", []))),
                   empty_control_pass=not actual if case.get("expect_empty") else None)
    if not expected:
        out["loss_stage"] = "negative_control"
    elif results["chat_tool"]["hit6"]:
        out["loss_stage"] = "delivered"
    elif not out["expected_in_index"]:
        out["loss_stage"] = "absent_from_tag_index"
    elif not out["expected_in_llm"]:
        out["loss_stage"] = "outside_general_chat_vocabulary"
    elif results["chat_adapter"]["hit6"]:
        out["loss_stage"] = "chat_tool_filter"
    elif not results["semantic"]["hit6"]:
        out["loss_stage"] = "not_in_semantic_top6"
    else:
        out["loss_stage"] = "chat_adapter_filter_or_rerank"
    return out


def summarize(rows):
    groups = {}
    for category in ["all", *sorted({row["case"]["category"] for row in rows})]:
        chosen = [row for row in rows if category == "all" or row["case"]["category"] == category]
        expected = [row for row in chosen if row["case"].get("expected_any")]
        lanes = {}
        for lane in LANES:
            values = [row["lanes"][lane] for row in expected]
            lanes[lane] = {"positive_cases": len(expected),
                "hit1": sum(v["hit1"] for v in values), "hit6": sum(v["hit6"] for v in values),
                "mrr6": sum(1 / v["rank"] for v in values if v["rank"] and v["rank"] <= 6) / len(values) if values else None,
                "cases_with_known_forbidden": sum(bool(row["lanes"][lane]["forbidden_hits"]) for row in chosen),
                "empty_results": sum(not row["lanes"][lane]["rows"] for row in chosen)}
        groups[category] = {"cases": len(chosen), "lanes": lanes,
            "loss_stage": dict(Counter(row["loss_stage"] for row in chosen))}
    return groups


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="New directory; never overwrite a prior run")
    parser.add_argument("--sample-per-stratum", type=int, default=24)
    parser.add_argument("--frozen-self", type=Path,
                        help="Reuse a previous self-queries-frozen.json for a paired data-change comparison")
    args = parser.parse_args(argv)
    if args.out.exists() or args.sample_per_stratum < 0:
        parser.error("Output must be a new directory and sample size must be nonnegative")
    fixture = json.loads(args.cases.read_text(encoding="utf-8"))
    cases = fixture["cases"]
    ids = [case["id"] for case in cases]
    if not ids or len(ids) != len(set(ids)):
        parser.error("Public cases need nonempty unique IDs")
    started = time.perf_counter()
    before = snapshot()
    fixture_hash = file_hash(args.cases)
    args.out.mkdir(parents=True)
    out = args.out.resolve()
    write_json(out / "source-before.json", before)
    write_json(out / "public-queries-frozen.json", fixture)
    from app.backend.runtime.paths import RuntimePaths
    from core.web_session_context import WebSessionContext
    from core.headless_token_store import InMemoryTokenManager
    from app.backend.server.autocomplete_commands import ensure_tag_search_index
    from app.backend.server.ollama_routes import ensure_llm_search_index
    from app.backend.server.ollama_chat_tools import search_chat_tags
    from tools.ollama_chat_agent_eval import production_chat_client
    paths = RuntimePaths(project_root=ROOT, resource_root=ROOT, user_root=out / "runtime", portable=True)
    context = WebSessionContext(repo_root=ROOT, runtime_paths=paths, token_manager=InMemoryTokenManager())
    context.headless_generation_execute_enabled = False
    index = ensure_tag_search_index(context)
    general = ensure_llm_search_index(context)
    raw = context.kr_tags_raw
    print(f"Loaded raw={len(raw)} TagSearchIndex={len(index._entries)} LLMSearchIndex={len(general._recs)}", flush=True)
    totals, pool, inventory = census(raw, index, general, out)
    self_fixture_hash = file_hash(args.frozen_self) if args.frozen_self else None
    if args.frozen_self:
        frozen = json.loads(args.frozen_self.read_text(encoding="utf-8"))
        samples, strata = frozen["cases"], frozen["strata"]
        if not isinstance(samples, list) or len({c["id"] for c in samples}) != len(samples):
            parser.error("Frozen self cases must have unique IDs")
    else:
        samples, strata = deterministic_samples(pool, args.sample_per_stratum)
    write_json(out / "self-queries-frozen.json", {"strata": strata, "cases": samples})
    write_json(out / "census.json", {"inventory": inventory, "cohorts": totals})
    all_cases = [("public", c) for c in cases] + [("self", c) for c in samples]
    unique_queries = list(dict.fromkeys(c["query"] for _, c in all_cases))
    print(f"Frozen {len(cases)} public + {len(samples)} dictionary cases; {len(unique_queries)} unique queries", flush=True)
    general_tags = {r.tag for r in general._recs}
    probe, measured = SearchProbe(), {}
    with production_chat_client(context, probe.service) as client, (out / "queries.jsonl").open("w", encoding="utf-8") as log:
        # Capture actual factory wiring, including Korean guard behavior, once per batch.
        for offset in range(0, len(unique_queries), 8):
            batch = unique_queries[offset:offset + 8]
            t = time.perf_counter()
            tool_results = probe.run(client, batch)
            route_seconds = time.perf_counter() - t
            for query in batch:
                results = {}
                for name, search in (("autocomplete", index.search_autocomplete), ("semantic", index.search_semantic)):
                    t = time.perf_counter()
                    rows = search(query, limit=6)
                    results[name] = {"rows": [{"tag": r.tag, "score": r.score, "desc": r.entry.desc,
                        "source": r.entry.source, "cat": r.entry.cat} for r in rows],
                        "seconds": time.perf_counter() - t}
                t = time.perf_counter()
                results["chat_adapter"] = {"rows": search_chat_tags(context, query, 6), "seconds": time.perf_counter() - t}
                results["chat_tool"] = {"rows": tool_results[query]["results"],
                    "note": tool_results[query].get("note"), "batch_route_seconds": route_seconds,
                    "batch_size": len(batch)}
                measured[query] = results
                log.write(json.dumps({"query": query, "lanes": results}, ensure_ascii=False) + "\n")
            log.flush()
            print(f"Measured {min(offset + 8, len(unique_queries))}/{len(unique_queries)} queries", flush=True)
        control_queries = ["가슴", "breasts"]
        baseline = probe.run(client, control_queries)
        # Reproduce the historical production Hangul preblock without editing code.
        def old_guard(ctx, query, limit=6):
            return [] if HANGUL.search(query) else search_chat_tags(ctx, query, limit)
        with patch("app.backend.server.ollama_chat_tools.search_chat_tags", old_guard):
            mutant = probe.run(client, control_queries)
        restored = probe.run(client, control_queries)
        witness = {"mutation": "Restore historical Hangul preblock at the route's imported search adapter",
            "baseline": {q: tags(v["results"]) for q, v in baseline.items()},
            "mutant": {q: tags(v["results"]) for q, v in mutant.items()},
            "restored": {q: tags(v["results"]) for q, v in restored.items()}}
        witness["passed"] = ("breasts" in witness["baseline"]["가슴"] and not witness["mutant"]["가슴"]
            and witness["mutant"]["breasts"] == witness["baseline"]["breasts"]
            and witness["restored"] == witness["baseline"])
    results = {"public": [], "self": []}
    for cohort, case in all_cases:
        # Per-case metrics must not modify rows shared by synonymous fixture cases.
        copied = json.loads(json.dumps(measured[case["query"]], ensure_ascii=False))
        results[cohort].append(measure_case(case, copied, index, general_tags))
    after = snapshot()
    stable = (before == after and fixture_hash == file_hash(args.cases) and
              (not args.frozen_self or self_fixture_hash == file_hash(args.frozen_self)))
    report = {"schema_version": 1, "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "execution_path": "WebSessionContext -> register_ollama_routes -> POST /api/ollama/chat -> native search_tags",
        "model": "Scripted native tool calls through OllamaAssistantService; no inference/no network",
        "context": {"type": type(context).__name__, "user_root": str(paths.user_root), "data_root": str(paths.data_dir),
                    "fallback_data_root": str(ROOT / "data")},
        "code_and_data_stable": stable, "source_before": before, "source_after": after,
        "fixture_sha256": fixture_hash, "records_sha256": digest(raw),
        "self_fixture_sha256": self_fixture_hash,
        "inventory": inventory, "cohorts": totals, "sample_strata": strata,
        "summary": {name: summarize(rows) for name, rows in results.items()},
        "mutation_witness": witness, "elapsed_seconds": time.perf_counter() - started,
        "limits": ["Local supplied source vocabulary only; not all upstream Danbooru/e621 tags",
                   "Source cohorts overlap; do not sum them", "Keyword self-retrieval is not semantic accuracy",
                   "Public lexical expectations are Codex-authored, not independent holdout",
                   "Missing candidate != missing scene meaning; unlisted candidate != false positive",
                   "Finite stratified query sample, not exhaustive query recall",
                   "No real model, UI, image generation, running-server or Portable lifecycle measurement",
                   "Latency is warmed in-process diagnostic timing, not user-facing p95"],
        "results": results}
    write_json(out / "report.json", report)
    print(json.dumps({"stable": stable, "mutation_passed": witness["passed"], "inventory": inventory,
        "public": report["summary"]["public"]["all"], "self": report["summary"]["self"]["all"],
        "elapsed_seconds": round(report["elapsed_seconds"], 2)}, ensure_ascii=False), flush=True)
    return 0 if stable and witness["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
