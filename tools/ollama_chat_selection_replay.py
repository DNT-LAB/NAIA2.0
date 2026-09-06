"""Isolate post-plan selection with authored plans and REAL production search.

Only the initial planning model reply is scripted. Subsequent turns call the
local 4B via the normal agent and HTTP route. This does not measure intent reading.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.ollama_chat_agent_eval import production_chat_client, run_production_case, assess
from tools.ollama_chat_query_eval import request_json, digest
from tools.compare_ollama_chat_selection import output_metrics, failure_signals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--plans', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', default='naia-gemma4-e4b-q4_k_m:think')
    parser.add_argument('--base-url', default='http://127.0.0.1:11434')
    args = parser.parse_args()
    if args.output.exists() or args.output.with_suffix('.runtime').exists():
        parser.error('choose a fresh output and runtime path')
    fixture = json.loads(args.cases.read_text(encoding='utf-8'))
    plans = json.loads(args.plans.read_text(encoding='utf-8'))
    cases = [c for c in fixture['cases'] if c['id'] in plans['plans']]
    if set(c['id'] for c in cases) != set(plans['plans']):
        parser.error('plans must reference existing unique public cases')
    from app.backend.runtime.paths import RuntimePaths
    from core.web_session_context import WebSessionContext
    from core.headless_token_store import InMemoryTokenManager
    from app.backend.server.autocomplete_commands import ensure_tag_search_index
    from app.backend.server.ollama_routes import ensure_llm_search_index
    from core.ollama_assistant_service import OllamaAssistantService
    from core.ollama_chat_agent import OllamaChatAgent, _validate
    from core.ollama_chat_plan import PLAN_SCHEMA, validate_plan
    for case in cases:
        plan = plans['plans'][case['id']]
        _validate(plan, PLAN_SCHEMA)
        validate_plan(plan, case['input'])
    paths = RuntimePaths(project_root=ROOT, resource_root=ROOT,
                         user_root=args.output.with_suffix('.runtime').resolve(), portable=True)
    context = WebSessionContext(repo_root=ROOT, runtime_paths=paths, token_manager=InMemoryTokenManager())
    context.headless_generation_execute_enabled = False
    ensure_tag_search_index(context)
    ensure_llm_search_index(context)
    files = ['core/ollama_chat_agent.py','core/ollama_chat_plan.py','core/ollama_chat_selection.py',
             'core/ollama_chat_semantics.py','core/ollama_chat_pipeline.py','core/ollama_assistant_service.py',
             'app/backend/server/ollama_routes.py','app/backend/server/ollama_chat_tools.py',
             'core/tag_search_index.py','core/llm_search_index.py','core/kr_tag_loader.py',
             'core/tag_knowledge.py','app/backend/server/autocomplete_commands.py',
             'tools/ollama_chat_agent_eval.py','tools/ollama_chat_query_eval.py',
             'core/event_preset/fast_search_catalog.py','core/event_preset/fast_search_catalog.json',
             'core/event_preset/fast_search_catalog_deep.json', 'tools/ollama_chat_selection_replay.py']
    def hashes():
        return {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files}
    report = {'scope':__doc__, 'fixture_sha256':digest(fixture), 'plans_sha256':digest(plans),
              'plans':plans, 'records_sha256':digest(context.kr_tags_raw), 'code_sha256':hashes(),
              'model':args.model, 'model_show':request_json(args.base_url,'/api/show',{'model':args.model}).json(),
              'model_inventory':request_json(args.base_url,'/api/tags').json(), 'runs':{}}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    # Alternate order across cases. One process/context, same current data.
    rows = {'legacy':[], 'compact':[]}
    for i,case in enumerate(cases):
        for mode in (('legacy','compact') if i % 2 == 0 else ('compact','legacy')):
            calls, initial_search, turn = [], None, 0
            def post(path, payload, **kw):
                nonlocal initial_search, turn
                if path == '/api/chat':
                    turn += 1
                    if turn == 1:
                        from types import SimpleNamespace
                        body = {'message':{'role':'assistant','tool_calls':[{'function':{
                            'name':'plan_search','arguments':copy.deepcopy(plans['plans'][case['id']])}}]}}
                        return SimpleNamespace(status_code=200,json=lambda:body)
                    if turn == 2:
                        initial_search = next(json.loads(m['content'])['results'] for m in reversed(payload['messages'])
                                              if m.get('tool_name')=='plan_search')
                started = time.monotonic()
                timeout = kw.get('timeout', 125)
                if isinstance(timeout, tuple): timeout = timeout[-1]
                snapshot = copy.deepcopy(payload)
                try:
                    response = request_json(args.base_url,path,payload,timeout=timeout)
                except Exception as exc:
                    if path == '/api/chat':
                        calls.append({'request':snapshot,'error':str(exc),'elapsed_seconds':time.monotonic()-started})
                    raise
                if path == '/api/chat':
                    calls.append({'request':snapshot,'response':response.json(),'elapsed_seconds':time.monotonic()-started})
                return response
            OllamaChatAgent.THINK_POLICY = 'always'
            OllamaChatAgent.SELECTION_FORMAT = mode
            service = OllamaAssistantService(default_model=args.model,base_url=args.base_url,http_post=post)
            with production_chat_client(context, service) as client:
                result = run_production_case(client,case)
            row = {'id':case['id'],'expected':case,'input':case['input'],'result':result,
                   'assessment':assess(case,result),'calls':calls,'initial_search':initial_search}
            rows[mode].append(row)
            report['runs'] = {k:{'cases':v} for k,v in rows.items()}
            args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'id':case['id'],'format':mode,'passed':row['assessment']['passed'],
                              'completion':result.get('completion'),'calls':len(calls)},ensure_ascii=True),flush=True)
    checks = {'unchanged_code':report['code_sha256']==hashes(),
              'unchanged_records':report['records_sha256']==digest(context.kr_tags_raw)}
    for a,b in zip(rows['legacy'],rows['compact']):
        checks['same_real_search:'+a['id']] = a['initial_search'] is not None and a['initial_search']==b['initial_search']
        requests = [c['request'] for row in (a,b) for c in row['calls']]
        checks['always_think:'+a['id']] = all(r['think'] is True for r in requests)
        checks['same_options:'+a['id']] = len({json.dumps(r['options'],sort_keys=True) for r in requests}) <= 1
    report['comparison'] = {'comparable':all(checks.values()),'checks':checks,
        **{mode:output_metrics({'cases':cases}) for mode,cases in rows.items()},
        'failure_signals':{mode:{c['id']:failure_signals(c) for c in cases} for mode,cases in rows.items()},
        'limits':'Authored plan replay does NOT measure initial intent decomposition or end-to-end success. '
                 'Model retries/searches after the first fixed search may differ. One model/seed, public cases.'}
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report['comparison'].items() if k!='failure_signals'},ensure_ascii=True,indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
