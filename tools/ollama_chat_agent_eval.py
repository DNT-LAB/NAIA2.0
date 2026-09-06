"""Live full Chat-agent evaluation against Codex-authored role/query fixtures.

No generation, downloads, prompt edits, or external translation calls. Unlike
the decomposition harness, exercises native thinking, tools, feedback and finish.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.ollama_assistant_service import OllamaAssistantService
from core.intent_action_pipeline import GenerationInfoContext
from core.llm_search_index import LLMSearchIndex, normalize_query
from tools.ollama_chat_query_eval import digest, request_json


def production_chat_client(context, assistant):
    """Use the actual HTTP route/factory, never rebuild its searcher in an eval."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.backend.server.ollama_routes import register_ollama_routes

    context.ollama_assistant_service = assistant
    app = FastAPI()
    async def inline(fn, *args):
        return fn(*args)
    register_ollama_routes(app, context, run_in_thread=inline)
    return TestClient(app)


def run_production_case(client, case):
    response = client.post('/api/ollama/chat', json={
        'messages': [*case.get('history', []), {'role': 'user', 'content': case['input']}],
        'context': case.get('context', {})})
    response.raise_for_status()
    return response.json()


def assess(case, result):
    scene = result.get("scene", {})
    names = {a["id"]: a["name"] for a in scene.get("actors", [])}
    relations = [{**r, "actor": names.get(r["actor_id"], ""),
                  "target": names.get(r["target_id"], "")} for r in scene.get("relations", [])]
    tags = {normalize_query(t) for a in scene.get("actors", []) for t in a.get("tags", [])}
    tags.update(map(normalize_query, scene.get("common_tags", [])))
    checks = {"completed": result.get("ok") is True,
              "type": result.get("type") == case.get("type", "scene_agent")}
    for expected in case.get("relations", []):
        key = f"relation:{expected['actor']}->{expected['target']}:{expected['action']}"
        checks[f"direction:{expected['actor']}->{expected['target']}"] = any(
            expected["actor"].casefold() in r["actor"].casefold()
            and expected["target"].casefold() in r["target"].casefold()
            and r["negated"] == expected.get("negated", False) for r in relations)
        checks[key] = any(expected["actor"].casefold() in r["actor"].casefold()
                          and expected["target"].casefold() in r["target"].casefold()
                          and re.search(expected["action"], r["action"], re.I)
                          and r["negated"] == expected.get("negated", False) for r in relations)
    if case.get("relations") and not case.get("allow_extra_relations"):
        checks["positive_relation_count"] = sum(not r["negated"] for r in relations) == sum(
            not r.get("negated", False) for r in case["relations"])
    for name, expected in case.get("actor_tags", {}).items():
        actual = {normalize_query(t) for a in scene.get("actors", [])
                  if name.casefold() == a["name"].casefold() for t in a["tags"]}
        checks[f"actor_tags:{name}"] = set(map(normalize_query, expected)).issubset(actual)
    for alternatives in case.get("tag_any", []):
        checks["tag:" + "|".join(alternatives)] = bool(tags.intersection(map(normalize_query, alternatives)))
    for tag in case.get("forbidden", []):
        checks[f"absent:{tag}"] = normalize_query(tag) not in tags
    # Server-side exact validation is not a model-initiated tool call.
    used = {t["tool"] for t in result.get("toolTrace", [])
            if t.get("origin") != "validation" and t.get("status") != "error"}
    for tool in case.get("tools", []):
        checks[f"tool:{tool}"] = tool in used
    successful = {t["tool"] for t in result.get("toolTrace", [])
                  if t.get("origin") != "validation" and t.get("status") == "ok" and t.get("tagCount", 0) > 0}
    for tool in case.get("successful_tools", []):
        checks[f"tool_success:{tool}"] = tool in successful
    if case.get('expected_output'):
        for key, value in case['expected_output'].items():
            actual = result.get('output', {}).get(key)
            # PLAN_SCHEMA accepts a language string, not an ISO-only enum.
            checks['output:' + key] = (str(actual).strip().casefold() in {'en', 'english', '영어'}
                                      if key == 'language' and value == 'en' else actual == value)
        if case['expected_output'].get('format') == 'sentence':
            checks['sentence_present'] = bool(result.get('output', {}).get('prompt', '').strip())
    if case.get('event_tag_set_status'):
        checks['event_tag_set_status'] = result.get('event_provenance', {}).get('tag_set_status') == case['event_tag_set_status']
    if case.get('event_detail'):
        checks['event_detail'] = any(b.get('conditions', {}).get('detail') == case['event_detail']
                                   for b in result.get('event_provenance', {}).get('bundles', []))
    return {"checks": checks, "passed": all(checks.values()), "relations": relations, "tags": sorted(tags)}


def assess_review(case, result, criteria):
    """Independent, versioned expectations; never import the runtime rule table."""
    expected = copy.deepcopy(case)
    expected['forbidden'] = list(dict.fromkeys(case.get('forbidden', []) + criteria.get('forbidden', [])))
    outcome = assess(expected, result)
    if 'max_actors' in criteria:
        outcome['checks']['actor_count'] = len(result.get('scene', {}).get('actors', [])) <= criteria['max_actors']
    outcome['content_passed'] = all(outcome['checks'].values())
    completion = result.get('completion', 'unavailable')
    outcome['completion'] = completion
    outcome['checks']['semantic_completion'] = completion == (
        'needs_clarification' if expected.get('type') == 'clarification' else 'complete')
    outcome['passed'] = all(outcome['checks'].values())
    return outcome


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=ROOT / "release_assets/ollama_chat_agent_cases.json")
    parser.add_argument("--model", default="naia-gemma4-e4b-q4_k_m:think")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ids", nargs="*")
    parser.add_argument("--system-file", type=Path, help="Offline experiment only: replace the agent system instructions")
    parser.add_argument("--event-data-root", type=Path, help="Read existing Event Preset assets from this data root")
    parser.add_argument("--review-cases", type=Path, help="Additional versioned meaning expectations; base score stays unchanged")
    parser.add_argument("--seed", type=int, help="Offline sampling experiment; default keeps the production seed")
    parser.add_argument('--think-policy', choices=['always', 'first'],
                        help='Isolated comparison: only the per-turn think policy changes')
    parser.add_argument('--selection-format', choices=['legacy', 'compact'],
                        help='Isolated comparison: completion tool/contract; retrieval and think stay fixed')
    args = parser.parse_args(argv)
    if args.system_file:
        import core.ollama_chat_agent as agent_module
        agent_module.SYSTEM = args.system_file.read_text(encoding="utf-8")
    if args.output.exists():
        parser.error('output already exists; choose a new evidence path')
    if args.think_policy:
        from core.ollama_chat_agent import OllamaChatAgent
        OllamaChatAgent.THINK_POLICY = args.think_policy
    if args.selection_format:
        from core.ollama_chat_agent import OllamaChatAgent
        OllamaChatAgent.SELECTION_FORMAT = args.selection_format
    from app.backend.runtime.paths import RuntimePaths
    from core.web_session_context import WebSessionContext
    from core.headless_token_store import InMemoryTokenManager
    from app.backend.server.ollama_routes import ensure_llm_search_index
    from app.backend.server.autocomplete_commands import ensure_tag_search_index
    runtime_root = args.output.resolve().with_suffix('.runtime')
    if runtime_root.exists():
        parser.error('isolated runtime path already exists')
    paths = RuntimePaths(project_root=ROOT, resource_root=ROOT, user_root=runtime_root, portable=True)
    context = WebSessionContext(repo_root=ROOT, runtime_paths=paths, token_manager=InMemoryTokenManager())
    context.headless_generation_execute_enabled = False
    ensure_tag_search_index(context)
    ensure_llm_search_index(context)
    if args.event_data_root:
        from core.event_preset_service import EventPresetService
        context.event_preset_service = EventPresetService(ROOT, data_root=args.event_data_root.resolve())
    fixture = json.loads(args.cases.read_text(encoding="utf-8"))
    review = json.loads(args.review_cases.read_text(encoding='utf-8')) if args.review_cases else None
    ids = [case["id"] for case in fixture.get("cases", [])]
    if not ids or len(ids) != len(set(ids)):
        parser.error("cases must be nonempty and have unique ids")
    if args.ids and set(args.ids) - set(ids):
        parser.error("unknown case ids: " + ", ".join(sorted(set(args.ids) - set(ids))))
    if args.output.resolve() in {args.cases.resolve(), args.system_file.resolve() if args.system_file else None,
                               args.review_cases.resolve() if args.review_cases else None}:
        parser.error("output must not overwrite an input fixture or system file")
    model_show = request_json(args.base_url, "/api/show", {"model": args.model}).json()
    model_tags = request_json(args.base_url, "/api/tags").json()
    model_shows = {args.model: model_show}
    calls = []
    def post(path, payload, **kwargs):
        started = time.monotonic()
        payload = copy.deepcopy(payload)
        if path == '/api/chat' and args.seed is not None:
            payload.setdefault('options', {})['seed'] = args.seed
        snapshot = copy.deepcopy(payload)
        timeout = kwargs.get("timeout", 125)
        if isinstance(timeout, tuple):
            timeout = timeout[-1]
        try:
            result = request_json(args.base_url, path, payload, timeout=timeout)
        except Exception as exc:
            if path == '/api/chat':
                calls.append({'request': snapshot, 'error': str(exc),
                              'elapsed_seconds': time.monotonic() - started})
            raise
        if path == "/api/chat":
            calls.append({"request": snapshot, "response": result.json(),
                          "elapsed_seconds": time.monotonic() - started})
        elif path == '/api/show':
            model_shows[payload['model']] = result.json()
        return result
    assistant = OllamaAssistantService(base_url=args.base_url, default_model=args.model, http_post=post)
    report = {"schema_version": 3, "baseline_source": "Codex-authored expected roles and direct local queries; not a live Codex API",
        "execution_path": "POST /api/ollama/chat via register_ollama_routes (in-process ASGI; live Ollama)",
        "context": {"type": "WebSessionContext", "runtime_paths": str(runtime_root),
                    "scope": "Production route/factory, isolated writable state, generation disabled"},
        "baseline_stage": "production pipeline searcher, before Chat tool postfilter",
        "tag_data_roots": [str(ROOT / 'data')],
        "fixture_sha256": digest(fixture), "records_sha256": digest(context.kr_tags_raw),
        "model": args.model, "model_show": model_show,
        "model_inventory": model_tags, "model_shows": model_shows,
        "model_record": [m for m in model_tags.get("models", []) if m.get("name") == args.model],
        "code_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in (
            "core/ollama_chat_agent.py", "core/ollama_chat_pipeline.py", "core/ollama_assistant_service.py",
            "core/ollama_chat_semantics.py", "core/ollama_chat_plan.py", "core/ollama_chat_selection.py",
            "core/event_preset/fast_search_catalog.py", "core/event_preset/fast_search_catalog.json",
            "core/event_preset/fast_search_catalog_deep.json",
            "app/backend/server/ollama_chat_tools.py", "app/backend/server/ollama_routes.py",
            "app/backend/server/autocomplete_commands.py", "core/tag_search_index.py",
            "core/llm_search_index.py", "core/kr_tag_loader.py", "core/tag_knowledge.py",
            "tools/ollama_chat_agent_eval.py")}, "cases": []}
    if review is not None:
        report['meaning_criteria'] = {'sha256': digest(review), 'fixture': review}
    if args.seed is not None:
        report['sampling_experiment'] = {'seed': args.seed, 'scope': 'Only the local evaluation request options'}
    if args.think_policy:
        report['think_policy'] = args.think_policy
    if args.selection_format:
        report['selection_format'] = args.selection_format
    if args.system_file:
        report["system_experiment"] = {"path": str(args.system_file),
            "sha256": hashlib.sha256(args.system_file.read_bytes()).hexdigest()}
    if args.event_data_root:
        asset = args.event_data_root.resolve() / "event_preset/naia_prompt_preset"
        if args.output.resolve() == asset:
            parser.error("output must not overwrite the Event Preset archive")
        report["event_data"] = {"path": str(asset), "exists": asset.is_file(),
            "sha256": hashlib.sha256(asset.read_bytes()).hexdigest() if asset.is_file() else None}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with production_chat_client(context, assistant) as client:
        # Creates/reuses exactly the same production pipeline as a Chat request.
        client.get('/api/ollama/chat/progress').raise_for_status()
        for case in fixture["cases"]:
            if args.ids and case["id"] not in args.ids:
                continue
            calls.clear()
            baseline = [{"query": q, "rows": context.ollama_chat_pipeline.searcher(
                q, 6, GenerationInfoContext())} for q in case.get("baseline_queries", [])]
            result = run_production_case(client, case)
            row = {"id": case["id"], "input": case["input"], "baseline": baseline,
                   "expected": case, "result": result, "assessment": assess(case, result), "calls": list(calls)}
            if review is not None:
                row['meaning_assessment'] = assess_review(case, result, review.get('cases', {}).get(case['id'], {}))
            report["cases"].append(row)
            report["summary"] = {"attempted": len(report["cases"]),
                                 "passed": sum(c["assessment"]["passed"] for c in report["cases"])}
            if review is not None:
                report['summary']['meaning_content_passed'] = sum(c['meaning_assessment']['content_passed'] for c in report['cases'])
                report['summary']['meaning_complete_passed'] = sum(c['meaning_assessment']['passed'] for c in report['cases'])
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"id": case["id"], **row["assessment"], "error": result.get("error", "")}, ensure_ascii=False), flush=True)
    report['code_sha256_after'] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                                   for p in report['code_sha256']}
    report['records_sha256_after'] = digest(context.kr_tags_raw)
    report['unchanged_during_run'] = (report['code_sha256'] == report['code_sha256_after']
                                    and report['records_sha256'] == report['records_sha256_after'])
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if all(c["assessment"]["passed"] for c in report["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
