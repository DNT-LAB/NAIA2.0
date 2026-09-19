"""Audit English keyword coverage and replay SSH/Ollama-generated queries.

No model output becomes a dictionary entry. Gold canonical tags are local and
are never sent to the model. The remote model only proposes English queries;
both search variants and the actual native Chat postfilter replay those queries.
This is retrieval evaluation, not end-to-end scene/role-quality certification.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.english_tag_keywords import KEYWORDS, VERSION
from core.kr_tag_loader import load_kr_tag_records
from core.llm_search_index import LLMSearchIndex


def native_results(raw, index, queries):
    """Script only the model turns; use real adapter and pipeline postfilter."""
    from app.backend.server.ollama_chat_tools import search_chat_tags
    from core.intent_action_pipeline import GenerationInfoContext
    from core.ollama_chat_pipeline import OllamaChatPipeline

    def call(name, **args):
        return {'function': {'name': name, 'arguments': args}}

    class ReplayAssistant:
        default_model = 'retrieval-replay:think'

        def __init__(self):
            self.requests = []
            self.turns = iter([
                [call('search_tags', queries=queries)],
                [call('finish', kind='chat', summary='검색 검증', actors=[],
                      relations=[], common_tags=[])],
            ])

        def reasoning_chat_session(self):
            return nullcontext(self.default_model)

        def reasoning_chat_turn(self, messages, tools, **kwargs):
            self.requests.append(messages)
            return {'role': 'assistant', 'tool_calls': next(self.turns)}

    context = SimpleNamespace(repo_root=ROOT, kr_tags_raw=raw, llm_search_index=index)
    assistant = ReplayAssistant()
    pipeline = OllamaChatPipeline(
        assistant=assistant, assist_helpers=None,
        searcher=lambda q, limit, _ctx: search_chat_tags(context, q, limit),
        event_provider=lambda *args: [], character_search=lambda **kw: {},
        event_search=lambda **kw: {})
    pipeline.run('영문 검색어 확인', gen_context=GenerationInfoContext())
    for messages in reversed(assistant.requests):
        for message in messages:
            if message.get('role') == 'tool' and message.get('tool_name') == 'search_tags':
                output = json.loads(message['content'])
                if 'searches' not in output:
                    raise RuntimeError(f'Native search failed: {output}')
                return output['searches']
    raise RuntimeError('Native pipeline produced no search_tags evidence')


def remote_batch(host, model, batch, seed):
    # stdin transports JSON; no remote files, model install, or shell-interpolated
    # user text. Endpoint is loopback on the explicitly selected SSH host.
    terms = [{'id': i, 'korean': keyword} for i, (_tag, keyword, _aliases) in batch]
    prompt = (
        'Translate each Korean image-search keyword into ONE concise natural English '
        'search phrase (1-6 words). Preserve counts, colors, body parts and modifiers. '
        'Do not add scene details. Use ordinary English, not Danbooru tag syntax. '
        'Return JSON only: {"queries":[{"id":0,"english":"..."}]}. '
        'Include every supplied id exactly once. Terms: ' + json.dumps(terms, ensure_ascii=False)
    )
    payload = {'model': model, 'messages': [{'role': 'user', 'content': prompt}],
               'think': True, 'stream': False, 'format': 'json',
               'options': {'temperature': 1.0, 'top_p': 0.95, 'top_k': 64,
                           'num_ctx': 8192, 'num_predict': 4096, 'seed': seed}}
    result = subprocess.run(
        ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', host,
         'curl -sS --fail-with-body --max-time 240 -H "Content-Type: application/json" '
         '--data-binary @- http://127.0.0.1:11434/api/chat'],
        input=json.dumps(payload, ensure_ascii=False).encode(), capture_output=True, timeout=260)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace') or result.stdout.decode(errors='replace'))
    response = json.loads(result.stdout)
    content = response.get('message', {}).get('content', '')
    capture = {'request': payload, 'response': response, 'queries': [],
               'expected_ids': [i for i, _row in batch]}
    try:
        proposed = json.loads(content)['queries']
        ids = [row['id'] for row in proposed]
    except (ValueError, KeyError, TypeError) as exc:
        return {**capture, 'error': f'Invalid model JSON: {exc}'}
    expected = {i for i, _row in batch}
    if len(ids) != len(expected) or set(ids) != expected:
        return {**capture, 'error': f'Model ids did not match batch: {ids}'}
    if any(not isinstance(r.get('english'), str) or not r['english'].strip()
           or len(r['english']) > 160 or not r['english'].isascii() for r in proposed):
        return {**capture, 'error': 'Invalid English query from model'}
    return {**capture, 'queries': proposed}


def tags(rows):
    return [r['tag'] for r in rows]


def evaluate_queries(raw, old, new, cases):
    results = []
    for start in range(0, len(cases), 8):
        batch = cases[start:start + 8]
        queries = [q for _t, q in batch]
        before = native_results(raw, old, queries)
        after = native_results(raw, new, queries)
        if ([r['query'] for r in before] != queries
                or [r['query'] for r in after] != queries):
            raise RuntimeError('Native replay omitted or reordered queries')
        for (target, query), a, b in zip(batch, before, after):
            results.append({'target': target, 'query': query,
                'before_index': tags(old.search(query, 6)),
                'after_index': tags(new.search(query, 6)),
                'before_native': tags(a['results']), 'after_native': tags(b['results'])})
    summary = {'cases': len(results)}
    for key in ('before_index', 'after_index', 'before_native', 'after_native'):
        summary[key + '_hit6'] = sum(r['target'] in r[key] for r in results)
        summary[key + '_top1'] = sum(r[key][:1] == [r['target']] for r in results)
    summary['native_regressions'] = [r for r in results
        if r['target'] in r['before_native'] and r['target'] not in r['after_native']]
    return {'summary': summary, 'results': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remote-host', default='meno9428@ai')
    parser.add_argument('--model', default='naia-gemma4-e2b-iq3_m:think')
    parser.add_argument('--seed', type=int, default=20260918)
    parser.add_argument('--replay', type=Path, help='Reuse captured remote batches without new inference')
    parser.add_argument('--resume', type=Path, help='Retain completed batches and call only remaining batches')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.replay and args.resume:
        parser.error('Choose replay or resume, not both')
    if args.output.exists():
        parser.error('Refusing to overwrite an existing report directory')
    args.output.mkdir(parents=True)

    captures = []
    if args.replay or args.resume:
        captures = json.loads((args.replay or args.resume).read_text(encoding='utf-8'))
    if not args.replay:
        for start in range(len(captures) * 10, len(KEYWORDS), 10):
            print(f'Ollama query extraction {start + 1}-{min(start + 10, len(KEYWORDS))}', flush=True)
            captures.append(remote_batch(args.remote_host, args.model,
                                          list(enumerate(KEYWORDS))[start:start + 10], args.seed))
            # Save every completed call even if a later call fails.
            (args.output / 'remote_queries.json').write_text(
                json.dumps(captures, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    print('Loading corpora and auditing index parity', flush=True)
    baseline_raw = load_kr_tag_records(ROOT, include_korean_keyword_supplement=False).raw
    raw = load_kr_tag_records(ROOT).raw
    baseline = LLMSearchIndex.from_raw_tag_records(baseline_raw, include_english_keywords=False)
    old = LLMSearchIndex.from_raw_tag_records(raw, built_from=raw, include_english_keywords=False)
    new = LLMSearchIndex.from_raw_tag_records(raw, built_from=raw)
    source_path = ROOT / 'data/tag_index/korean_keyword_supplement.json'
    supplement = json.loads(source_path.read_text(encoding='utf-8'))['translations']
    eligible = {r.tag for r in new._recs}
    report = {'version': VERSION, 'scope': 'query extraction plus real native search/postfilter replay; not full model scene completion',
        'source_sha256': hashlib.sha256(source_path.read_bytes()).hexdigest(),
        'supplement_tags': len(supplement),
        'supplement_aliases': sum(len(r['aliases']) for r in supplement.values()),
        'supplement_english_eligible': len(set(supplement) & eligible),
        'index_stats': new.stats(),
        'korean_update_preserves_english_index': (
            baseline._recs == old._recs and baseline._exact == old._exact
            and baseline._postings == old._postings),
        'canonical_top1_failures': [r.tag for r in new._recs
            if tags(new.search(r.tag, 1)) != [r.tag]],
        'reviewed_source_missing': [t for t, ko, _en in KEYWORDS
            if ko not in {a['text'] for a in supplement.get(t, {}).get('aliases', [])}],
        'alias_target_missing': sorted({t for t, _ko, _en in KEYWORDS} - eligible),
        'reviewed_tags': len(KEYWORDS),
        'dictionary': evaluate_queries(raw, old, new, [(t, q) for t, _ko, aliases in KEYWORDS for q in aliases])}
    proposals = [row for capture in captures for row in capture['queries']]
    ids = [r['id'] for r in proposals]
    if len(ids) != len(set(ids)) or not set(ids).issubset(range(len(KEYWORDS))):
        raise ValueError('Duplicate/invalid evaluation ids')
    report['ollama_generation'] = {
        'requested_cases': len(KEYWORDS), 'valid_queries': len(proposals),
        'missing_ids': sorted(set(range(len(KEYWORDS))) - set(ids)),
        'errors': [c['error'] for c in captures if c.get('error')],
    }
    report['ollama'] = evaluate_queries(raw, old, new,
        [(KEYWORDS[r['id']][0], r['english']) for r in proposals])
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('dictionary', 'ollama')}, ensure_ascii=False))
    print('DICTIONARY', report['dictionary']['summary'])
    print('OLLAMA', report['ollama']['summary'])
    return int(bool(report['canonical_top1_failures'] or report['alias_target_missing']
                    or report['reviewed_source_missing'] or not report['korean_update_preserves_english_index']
                    or report['ollama_generation']['missing_ids']
                    or report['dictionary']['summary']['native_regressions']
                    or report['ollama']['summary']['native_regressions']))


if __name__ == '__main__':
    raise SystemExit(main())
