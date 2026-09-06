"""Compare legacy/compact native finishes with fixed production retrieval and thinking.

Public development checks, not a semantic judge or a private holdout evaluator.
Reports comparability failures instead of treating unmatched runs as a speedup.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.compare_ollama_chat_plan import delivery_checks, metrics


def output_metrics(run):
    result = metrics(run)
    messages = [c.get('response', {}).get('message', {}) for r in run['cases'] for c in r['calls']]
    finishes = [f for m in messages for f in m.get('tool_calls', [])
                if f.get('function', {}).get('name') in {'finish', 'finish_selection'}]
    result.update(
        finish_tools=dict(Counter(f['function']['name'] for f in finishes)),
        finish_argument_bytes=sum(len(json.dumps(f['function']['arguments'], ensure_ascii=False,
                                 separators=(',', ':')).encode('utf-8')) for f in finishes),
        thinking_characters=sum(len(m.get('thinking', '')) for m in messages),
        successful_selection_tools=dict(Counter(r['result'].get('selection_tool', 'none') for r in run['cases'])))
    return result


def failure_signals(row):
    """Observable signals can overlap; they are not automatic root-cause labels."""
    result = row['result']
    trace = result.get('toolTrace', [])
    failed = [k for k,v in delivery_checks(row).items() if not v]
    return {
        'intent': ['no_accepted_plan'] if not result.get('intent_plan') and row['expected'].get('type') != 'clarification' else [],
        'retrieval': [t for t in trace if t.get('status') in {'no_match','choose_partition','unavailable'}],
        'selection': [r for r in result.get('coverage', {}).get('requirements', []) if r['state'] != 'selected'],
        'ownership_or_direction': [k for k in failed if k.startswith(('actor_tags:', 'direction:', 'relation:'))],
        'tool_errors': [t for t in trace if t.get('status') == 'error'],
        'failed_checks': failed,
    }


def compare(legacy, compact):
    checks = {key: legacy[key] == compact[key] for key in
              ('fixture_sha256','records_sha256','model','model_record','code_sha256')}
    checks.update(legacy_format=legacy.get('selection_format') == 'legacy',
                  compact_format=compact.get('selection_format') == 'compact',
                  unchanged_legacy=legacy.get('unchanged_during_run') is True,
                  unchanged_compact=compact.get('unchanged_during_run') is True)
    left, right = [{r['id']:r for r in run['cases']} for run in (legacy, compact)]
    checks['same_cases'] = left.keys() == right.keys()
    rows = []
    for key in left.keys() & right.keys():
        a, b = left[key], right[key]
        requests_a, requests_b = [[c['request'] for c in row['calls']] for row in (a,b)]
        checks['initial_request:' + key] = requests_a[:1] == requests_b[:1]
        checks['always_think:' + key] = all(r['think'] is True for r in requests_a + requests_b)
        checks['same_options:' + key] = len({json.dumps(r['options'], sort_keys=True) for r in requests_a + requests_b}) <= 1
        rows.append({'id':key, 'legacy_passed':all(delivery_checks(a).values()),
                     'compact_passed':all(delivery_checks(b).values()),
                     'legacy_signals':failure_signals(a), 'compact_signals':failure_signals(b)})
    return {'version':1, 'comparable':all(checks.values()), 'checks':checks,
            'legacy':output_metrics(legacy), 'compact':output_metrics(compact),
            'cases':sorted(rows, key=lambda r:r['id']),
            'limits':'One model/seed and public cases do not prove quality noninferiority. '
                     'Generated token counts include thinking; argument bytes are not tokens. '
                     'A fixed search implementation does not imply identical model-chosen queries.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legacy', type=Path, required=True)
    parser.add_argument('--compact', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('choose a new output path')
    comparison = compare(*(json.loads(p.read_text(encoding='utf-8')) for p in (args.legacy,args.compact)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in comparison.items() if k != 'cases'}, ensure_ascii=False, indent=2))
    return 0 if comparison['comparable'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
