"""Compare Codex-authored fixtures and Ollama decomposition on one local index.

This is a representative query/grounding evaluation, not full Chat or vocabulary
coverage. Baseline-only never contacts Ollama or a translation service.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.llm_search_index import LLMSearchIndex, normalize_query
from core.ollama_assistant_service import OllamaAssistantService
from core.semantic_tag_discovery import ground_scene_segments


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    default=str).encode('utf-8')).hexdigest()


class Response:
    def __init__(self, status, body):
        self.status_code, self.body = status, body

    def json(self):
        return self.body


def request_json(base, path, payload=None, timeout=180):
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    req = Request(base.rstrip('/') + path, data=data,
                  headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=timeout) as response:
        return Response(response.status, json.loads(response.read()))


class CaptureTransport:
    def __init__(self, base, model, options, think, transport=request_json):
        self.base, self.model = base, model
        self.options, self.think, self.transport = options, think, transport
        self.calls = []

    def post(self, path, payload, **kwargs):
        payload = dict(payload)
        payload['model'] = self.model
        payload['options'] = {**payload.get('options', {}), **self.options}
        payload['think'] = self.think
        payload.setdefault('keep_alive', 60)
        call = {'request': payload, 'path': path}
        self.calls.append(call)
        start = time.perf_counter()
        try:
            result = self.transport(self.base, path, payload)
            call.update(status=result.status_code, response=result.json())
            return result
        except Exception as exc:
            call['error'] = str(exc)
            raise
        finally:
            call['elapsed_seconds'] = time.perf_counter() - start


def evaluate_segments(index, segments, expected, forbidden=()):
    queries = []

    def search(query, limit, context):
        rows = index.search(query, limit)
        queries.append({'query': query, 'limit': limit, 'rows': rows})
        return rows

    grounded = ground_scene_segments(segments, searcher=search, per_concept_limit=6)
    tags = sorted({normalize_query(row['tag']) for segment in grounded
                   for row in segment['tags']})
    expected_set = {normalize_query(tag) for tag in expected}
    indexed = {tag: any(normalize_query(row['tag']) == tag
                        for row in index.search(tag, 6)) for tag in sorted(expected_set)}
    matched = sorted(expected_set.intersection(tags))
    return {'segments': segments, 'queries': queries, 'grounded': grounded,
            'tags': tags, 'expected_indexed': indexed, 'matched_expected': matched,
            'exact_expected_recall': len(matched) / len(expected_set) if expected_set else None,
            'forbidden_hits': sorted(set(tags).intersection(map(normalize_query, forbidden)))}


def run_cases(cases, index, assistant=None, capture=None):
    results = []
    for case in cases:
        row = {'id': case['id'], 'category': case['category'], 'input': case['input'],
               'expected': case['expected'], 'forbidden': case.get('forbidden', [])}
        for lane in (['baseline', 'ollama'] if assistant else ['baseline']):
            start = time.perf_counter()
            before = len(capture.calls) if capture else 0
            try:
                if lane == 'baseline':
                    segments = case['segments']
                else:
                    response = assistant.decompose_scene(case['input'])
                    if not response.get('ok'):
                        raise ValueError(response.get('error') or 'decomposition failed')
                    segments = response.get('segments', [])
                    if not segments:
                        raise ValueError('empty decomposition')
                row[lane] = {'ok': True, **evaluate_segments(
                    index, segments, case['expected'], case.get('forbidden', []))}
            except Exception as exc:
                row[lane] = {'ok': False, 'error': str(exc), 'exact_expected_recall': 0.0}
            row[lane]['elapsed_seconds'] = time.perf_counter() - start
            if lane == 'ollama' and capture:
                row[lane]['calls'] = capture.calls[before:]
        results.append(row)
    summary = {}
    for lane in (['baseline', 'ollama'] if assistant else ['baseline']):
        items = [row[lane] for row in results]
        summary[lane] = {'attempted': len(items),
                         'failed': sum(not item['ok'] for item in items),
                         'mean_exact_expected_recall_including_failures':
                         sum(item.get('exact_expected_recall') or 0 for item in items) / max(1, len(items)),
                         'expected_not_indexed': sorted({tag for item in items
                             for tag, present in item.get('expected_indexed', {}).items() if not present}),
                         'forbidden_hits': sum(len(item.get('forbidden_hits', [])) for item in items)}
    return {'cases': results, 'summary': summary}


def validate_replay(source, fixture, cases):
    if source.get('fixture_sha256') != digest(fixture):
        raise ValueError('replay fixture_sha256 mismatch')
    if not source.get('requested_model'):
        raise ValueError('replay missing requested_model')
    stored = source.get('cases', [])
    ids = [row.get('id') for row in stored]
    if len(ids) != len(set(ids)):
        raise ValueError('replay duplicate case id')
    by_id = {row['id']: row for row in stored}
    for case in cases:
        row = by_id.get(case['id'])
        if row is None or row.get('input') != case['input']:
            raise ValueError(f"replay id/input mismatch: {case['id']}")
        for call in row.get('ollama', {}).get('calls', []):
            request = call.get('request', {})
            if request.get('model') != source['requested_model']:
                raise ValueError(f"replay request model mismatch: {case['id']}")
            response_model = call.get('response', {}).get('model')
            if response_model and response_model != source['requested_model']:
                raise ValueError(f"replay response model mismatch: {case['id']}")
            users = [m.get('content', '') for m in request.get('messages', []) if m.get('role') == 'user']
            if not users or not users[-1].endswith('User scene:\n' + case['input'][:2000]):
                raise ValueError(f"replay captured input mismatch: {case['id']}")
    return by_id


class ReplayAssistant:
    """Reprocess recorded content only; no HTTP transport or model instance."""
    def __init__(self, cases, by_id):
        self.pending = iter(cases)
        self.by_id = by_id
        self.calls = []

    def decompose_scene(self, text):
        case = next(self.pending)
        if text != case['input']:
            raise ValueError('replay case order/input mismatch')
        lane = self.by_id[case['id']].get('ollama', {})
        calls = lane.get('calls', [])
        self.calls.extend(calls)
        if len(calls) != 1:
            return {'ok': False, 'error': 'replay requires exactly one captured decomposition call'}
        call = calls[0]
        if call.get('error') or call.get('status') != 200:
            return {'ok': False, 'error': call.get('error') or f"recorded HTTP {call.get('status')}"}
        content = call.get('response', {}).get('message', {}).get('content')
        try:
            parsed = json.loads(content)
            segments = OllamaAssistantService._clean_scene_segments(parsed, text)
            if not segments:
                raise ValueError('empty replay decomposition')
            return {'ok': True, 'segments': segments}
        except (TypeError, ValueError) as exc:
            return {'ok': False, 'error': str(exc)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, default=ROOT / 'release_assets/ollama_chat_query_cases.json')
    parser.add_argument('--output', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--baseline-only', action='store_true')
    mode.add_argument('--replay', type=Path, help='Reprocess recorded model content without network/GPU calls')
    parser.add_argument('--limit-cases', type=int)
    parser.add_argument('--model', default='naia-gemma4-e4b-q4_k_m:think')
    parser.add_argument('--base-url', default='http://127.0.0.1:11434')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--num-ctx', type=int, default=4096)
    parser.add_argument('--num-predict', type=int, default=1024)
    parser.add_argument('--think', choices=['true', 'false'], default='false')
    args = parser.parse_args(argv)
    from core.kr_tag_loader import load_kr_tag_records
    records = load_kr_tag_records(str(ROOT), data_roots=[ROOT / 'data'])
    index = LLMSearchIndex.from_raw_tag_records(records.raw)
    fixture = json.loads(args.cases.read_text(encoding='utf-8'))
    cases = fixture['cases']
    if args.limit_cases is not None:
        if args.limit_cases <= 0:
            parser.error('--limit-cases must be positive')
        cases = cases[:args.limit_cases]
    options = {'seed': args.seed, 'num_ctx': args.num_ctx, 'num_predict': args.num_predict}
    capture = CaptureTransport(args.base_url, args.model, options, args.think == 'true')
    inventory = {'contacted': False}
    assistant = None
    source = None
    if args.replay:
        if args.output.resolve() == args.replay.resolve():
            parser.error('--output must not overwrite --replay source')
        source = json.loads(args.replay.read_text(encoding='utf-8'))
        try:
            by_id = validate_replay(source, fixture, cases)
        except ValueError as exc:
            parser.error(str(exc))
        assistant = ReplayAssistant(cases, by_id)
        capture = assistant
        inventory = source.get('inventory', {})
        options = source.get('options', {})
    elif not args.baseline_only:
        inventory = {'contacted': True}
        for name, path, payload in [('show', '/api/show', {'model': args.model}),
                                    ('tags', '/api/tags', None)]:
            try:
                inventory[name] = request_json(args.base_url, path, payload).json()
            except Exception as exc:
                inventory[name] = {'error': str(exc)}
        inventory['selected_model_records'] = [
            row for row in inventory.get('tags', {}).get('models', [])
            if row.get('name') == args.model or row.get('model') == args.model]
        inventory['capabilities'] = inventory.get('show', {}).get('capabilities', [])
        assistant = OllamaAssistantService(base_url=args.base_url,
                                           default_model=args.model, http_post=capture.post)
    report = {'schema_version': 1, 'baseline_source': 'Codex-authored fixture',
              'scope': 'Representative Korean query decomposition and grounding; not full Chat or exhaustive vocabulary coverage',
              'fixture_sha256': digest(fixture), 'records_sha256': digest(records.raw),
              'fixture_expected_preflight': {
                  tag: any(normalize_query(row['tag']) == tag for row in index.search(tag, 6))
                  for tag in sorted({normalize_query(tag) for case in cases for tag in case['expected']})},
              'requested_model': args.model, 'options': options, 'think': args.think == 'true',
              'inventory': inventory, **run_cases(cases, index, assistant, capture)}
    report['execution_mode'] = 'replay' if source is not None else ('baseline-only' if args.baseline_only else 'live')
    report['network_contacted_this_run'] = not args.baseline_only and source is None
    if source is not None:
        for key in ('requested_model', 'options', 'think', 'inventory'):
            report[key] = source.get(key)
        report['replay'] = {
            'live': False, 'source_path': str(args.replay.resolve()),
            'source_sha256': hashlib.sha256(args.replay.read_bytes()).hexdigest(),
            'source_records_sha256': source.get('records_sha256'),
            'inventory_is_recorded_snapshot': True,
            'current_code_sha256': {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                for path in ('tools/ollama_chat_query_eval.py', 'core/ollama_assistant_service.py',
                             'core/semantic_tag_discovery.py', 'core/llm_search_index.py')},
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report['summary'], ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
