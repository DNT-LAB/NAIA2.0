"""Compare public operating-route runs without equating partial with semantic success."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.compare_ollama_chat_selection import output_metrics


STRUCTURE_FILES = {
    'core/ollama_chat_agent.py', 'core/ollama_chat_plan.py', 'core/ollama_chat_selection.py',
    'core/ollama_chat_execution.py', 'core/ollama_chat_pipeline.py', 'tools/ollama_chat_agent_eval.py'}


def distribution(values):
    values = sorted(values)
    if not values:
        return {'n': 0, 'sum': None, 'p50': None, 'p95': None}
    # Nearest rank; descriptive only on a small public pilot.
    import math
    return {'n': len(values), 'sum': sum(values), 'p50': statistics.median(values),
            'p95': values[max(0, math.ceil(.95*len(values))-1)]}


def summarize(run):
    rows = run['cases']
    timings = {}
    for row in rows:
        for key, value in row['result'].get('execution', {}).get('timings', {}).items():
            stage = timings.setdefault(key, {'calls': 0, 'seconds': 0.0})
            for field in stage:
                stage[field] += value[field]
    return {**output_metrics(run),
        'request_wall_seconds': distribution([r['request_wall_seconds'] for r in rows if 'request_wall_seconds' in r]),
        'case_http_seconds': distribution([sum(c['elapsed_seconds'] for c in r['calls']) for r in rows]),
        'model_calls_per_case': distribution([len(r['calls']) for r in rows]),
        'stage_timings': timings,
        'stop_reasons': dict(Counter(r['result'].get('stop_reason', 'none') for r in rows)),
        'cases_over_four_calls': [r['id'] for r in rows if len(r['calls']) > 4],
        'lexical_hint_counts': {r['id']: [sum(str(m.get('content', '')).count('Reviewed local lexical meanings')
            for m in c['request']['messages']) for c in r['calls']] for r in rows}}


def compare(before, after, kind='structure'):
    if kind not in {'structure', 'think'}:
        raise ValueError('unknown comparison kind')
    checks = {k: before.get(k) is not None and before[k] == after.get(k) for k in
              ('fixture_sha256', 'records_sha256', 'model', 'model_record')}
    checks.update(before_unchanged=before.get('unchanged_during_run') is True,
                  after_unchanged=after.get('unchanged_during_run') is True,
                  same_selection_format=before.get('selection_format') == after.get('selection_format') == 'compact')
    ah, bh = before['code_sha256'], after['code_sha256']
    differences = {p for p in ah.keys() | bh.keys() if ah.get(p) != bh.get(p)}
    checks['code_scope'] = differences.issubset(STRUCTURE_FILES) if kind == 'structure' else not differences
    if kind == 'structure':
        checks['policy'] = before.get('think_policy') == after.get('think_policy') == 'always'
    else:
        checks['policy'] = before.get('think_policy') == 'always' and after.get('think_policy') == 'first'
    left, right = [{r['id']: r for r in run['cases']} for run in (before, after)]
    checks['same_case_ids'] = left.keys() == right.keys()
    per_case = []
    for key in left.keys() & right.keys():
        a, b = left[key], right[key]
        checks['same_case:' + key] = a['expected'] == b['expected'] and a['input'] == b['input']
        ra, rb = [[c['request'] for c in row['calls']] for row in (a, b)]
        checks['options:' + key] = len({json.dumps(r['options'], sort_keys=True) for r in ra+rb}) <= 1
        checks['wire_think:' + key] = all(r['think'] is True for r in ra) and all(
            r['think'] == (True if kind == 'structure' else i == 0) for i, r in enumerate(rb))
        if kind == 'think':
            checks['same_initial_request:' + key] = ra[:1] == rb[:1]
        per_case.append({'id': key, 'before_passed': a['assessment']['passed'],
            'after_passed': b['assessment']['passed'], 'before_completion': a['result'].get('completion'),
            'after_completion': b['result'].get('completion'), 'before_calls': len(ra), 'after_calls': len(rb),
            'before_failed_checks': [k for k,v in a['assessment']['checks'].items() if not v],
            'after_failed_checks': [k for k,v in b['assessment']['checks'].items() if not v]})
    return {'version': 1, 'kind': kind, 'comparable': all(checks.values()), 'checks': checks,
            'changed_files': sorted(differences), 'before': summarize(before), 'after': summarize(after),
            'cases': sorted(per_case, key=lambda r: r['id']),
            'limits': 'Public content/delivery checks are not independent semantic judgments. '
                      'Shorter failed requests do not prove equal-quality speedup. Missing wall times are unavailable, '
                      'not zero. Stage timers can nest; do not add them to model HTTP totals. '
                      'First-run index loading and model loading are recorded, not charged to every warm search.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--kind', choices=['structure', 'think'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('choose a fresh output path')
    result = compare(json.loads(args.before.read_text(encoding='utf-8')),
                     json.loads(args.after.read_text(encoding='utf-8')), args.kind)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in {'cases', 'checks'}}, ensure_ascii=False, indent=2))
    return 0 if result['comparable'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
