"""Compare fixed public cases under always/first thinking, without tuning fixtures.

The authored-query lane calls the same production Chat tool via a scripted model
transport; it is not a live Codex API or an independent semantic judge.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def delivery_checks(row):
    expected, result = row['expected'], row['result']
    checks = dict(row['assessment']['checks'])
    if expected.get('type') != 'clarification':
        checks['plan_present'] = bool(result.get('intent_plan'))
        checks['coverage_present'] = result.get('coverage', {}).get('plan_present') is True
    if expected.get('expected_output'):
        output = result.get('output', {})
        checks['output_format'] = output.get('format') == expected['expected_output']['format']
        language = str(output.get('language', '')).strip().casefold()
        checks['output_language'] = language in {'en', 'english', '영어'}
        checks['sentence_present'] = bool(output.get('prompt', '').strip())
        # Only a shallow format check, not a claim of sentence meaning/fidelity.
        # Short sentences such as "A is smiling" are valid. Word-count floors
        # measure verbosity, not delivery; this only checks that English text exists.
        checks['sentence_has_english_text'] = bool(re.search(r'[a-zA-Z]', output.get('prompt', '')))
    return checks


def metrics(run):
    rows = run['cases']
    calls = [c for row in rows for c in row['calls']]
    return {
        'cases': len(rows), 'content_passed': sum(row['assessment']['passed'] for row in rows),
        'delivery_passed': sum(all(delivery_checks(row).values()) for row in rows),
        'completion': dict(Counter(row['result'].get('completion', 'error') for row in rows)),
        'accepted_plans': sum(bool(row['result'].get('intent_plan')) for row in rows),
        'native_http_calls': len(calls), 'failed_http_calls': sum('error' in c for c in calls),
        'http_seconds': sum(c['elapsed_seconds'] for c in calls),
        'case_seconds': sum(row['result'].get('elapsed_seconds', 0) for row in rows),
        'eval_tokens': sum(c.get('response', {}).get('eval_count', 0) for c in calls),
        'decode_seconds': sum(c.get('response', {}).get('eval_duration', 0) for c in calls) / 1e9,
        'prefill_seconds': sum(c.get('response', {}).get('prompt_eval_duration', 0) for c in calls) / 1e9,
        'load_seconds': sum(c.get('response', {}).get('load_duration', 0) for c in calls) / 1e9,
        'post_first_median_seconds': statistics.median(
            [c['elapsed_seconds'] for row in rows for c in row['calls'][1:]]) if any(len(r['calls']) > 1 for r in rows) else None,
    }


def compare(first, always):
    checks = {key: first[key] == always[key] for key in
        ('fixture_sha256', 'records_sha256', 'model', 'model_record', 'code_sha256')}
    checks['first_policy'] = first.get('think_policy') == 'first'
    checks['always_policy'] = always.get('think_policy') == 'always'
    checks['unchanged_first'] = first.get('unchanged_during_run') is True
    checks['unchanged_always'] = always.get('unchanged_during_run') is True
    a, b = {r['id']: r for r in first['cases']}, {r['id']: r for r in always['cases']}
    checks['same_cases'] = a.keys() == b.keys()
    per_case = []
    for key in a.keys() & b.keys():
        requests_a, requests_b = [c['request'] for c in a[key]['calls']], [c['request'] for c in b[key]['calls']]
        checks['initial_request:' + key] = (requests_a[:1] == requests_b[:1])
        checks['policy:' + key] = (all(r['think'] == (i == 0) for i, r in enumerate(requests_a))
                                   and all(r['think'] is True for r in requests_b))
        checks['options:' + key] = len({json.dumps(r['options'], sort_keys=True)
                                        for r in requests_a + requests_b}) <= 1
        per_case.append({'id': key, 'first': a[key]['assessment'], 'always': b[key]['assessment'],
            'first_delivery': delivery_checks(a[key]), 'always_delivery': delivery_checks(b[key]),
            'first_plan': a[key]['result'].get('intent_plan'), 'always_plan': b[key]['result'].get('intent_plan'),
            'first_coverage': a[key]['result'].get('coverage'), 'always_coverage': b[key]['result'].get('coverage'),
            'first_output': a[key]['result'].get('output'), 'always_output': b[key]['result'].get('output')})
    return {'delivery_criteria_version': 2,
            'comparable': all(checks.values()), 'comparability_checks': checks,
            'first': metrics(first), 'always': metrics(always), 'cases': sorted(per_case, key=lambda r: r['id'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--first', type=Path, required=True)
    parser.add_argument('--always', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('choose a new output directory')
    first, always = [json.loads(p.read_text(encoding='utf-8')) for p in (args.first, args.always)]
    comparison = compare(first, always)
    args.out.mkdir(parents=True)
    from app.backend.runtime.paths import RuntimePaths
    from core.web_session_context import WebSessionContext
    from core.headless_token_store import InMemoryTokenManager
    from tools.tag_search_coverage_eval import SearchProbe, digest, file_hash
    from tools.ollama_chat_agent_eval import production_chat_client
    from app.backend.server.autocomplete_commands import ensure_tag_search_index
    paths = RuntimePaths(project_root=ROOT, resource_root=ROOT, user_root=args.out / 'runtime', portable=True)
    context = WebSessionContext(repo_root=ROOT, runtime_paths=paths, token_manager=InMemoryTokenManager())
    context.headless_generation_execute_enabled = False
    ensure_tag_search_index(context)
    before = {p: file_hash(ROOT / p) for p in first['code_sha256']}
    queries = list(dict.fromkeys(q for row in first['cases'] for q in row['expected'].get('baseline_queries', [])))
    probe, results = SearchProbe(), {}
    with production_chat_client(context, probe.service) as client:
        for offset in range(0, len(queries), 8):
            results.update(probe.run(client, queries[offset:offset + 8]))
    after = {p: file_hash(ROOT / p) for p in before}
    comparison['authored_queries'] = {
        'scope': 'Frozen authored general-tag queries, after production Chat tool filters; no live Codex inference or character/event baseline',
        'results': results, 'records_sha256': digest(context.kr_tags_raw), 'code_sha256': before,
        'same_runtime_as_live': before == after == first['code_sha256'],
        'same_records_as_live': digest(context.kr_tags_raw) == first['records_sha256']}
    (args.out / 'comparison.json').write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in comparison.items() if k not in {'cases', 'authored_queries'}}, ensure_ascii=False, indent=2))
    return 0 if comparison['comparable'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
