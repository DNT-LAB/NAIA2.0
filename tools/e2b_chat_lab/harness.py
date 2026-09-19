"""Small bounded E2B harness, independent of OllamaChatAgent and Assist.

Only preferences and runtime settings persist. Transcript, Memory.md, summaries and tool traces
are process memory, all invalidated atomically by New conversation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from copy import deepcopy
import json
import re
import threading
import time
import uuid
import requests
from tools.e2b_chat_lab.context_budget import (CONTEXT_SIZES, DEFAULT_CONTEXT_SIZE, OUTPUT_RESERVE,
    SAFETY_MARGIN, ContextBudgetError, fit_messages, valid_context_size)
from tools.e2b_chat_lab.pipeline import (INTENT_SCHEMA, DESIGN_SCHEMA, CONVERT_SCHEMA, wants_composition,
                                         source_intent, check_preserved, merged_searches, tag_candidates, render_conversion)
from tools.e2b_chat_lab.retrieval import retrieval_plan, event_pin_candidates, evidence_catalog
from tools.e2b_chat_lab.relations import RELATION_SCHEMA, REVIEW_SCHEMA, bind_sources

PROMPTS = Path(__file__).parent / 'prompts'
SYSTEM = (PROMPTS / 'system.md').read_text(encoding='utf-8')
ROUTER = (PROMPTS / 'intent.md').read_text(encoding='utf-8')
DESIGNER = (PROMPTS / 'design.md').read_text(encoding='utf-8')
COMPACTOR = (PROMPTS / 'compact.md').read_text(encoding='utf-8')
COMPOSER = (PROMPTS / 'compose.md').read_text(encoding='utf-8')
FALLBACK = (PROMPTS / 'fallback.md').read_text(encoding='utf-8')
ANSWER = (PROMPTS / 'answer.md').read_text(encoding='utf-8')
REVIEWER = (PROMPTS / 'review.md').read_text(encoding='utf-8')
MODEL = 'gemma4:e2b-it-qat'


def obj(properties, required=None):
    return {'type': 'object', 'properties': properties, 'required': list(properties) if required is None else required, 'additionalProperties': False}


def string(n=160):
    return {'type': 'string', 'maxLength': n}


def array(item, n=8):
    return {'type': 'array', 'items': item, 'maxItems': n}


LIMIT = {'type': 'integer', 'minimum': 1, 'maximum': 8}
TOOL_PARAMS = {
    'search_tags': obj({'query': string(), 'query_ko': string(240), 'limit': LIMIT}, ['query']),
    'fast_search': obj({'query': string(), 'source': {'type': 'string', 'enum': ['tag', 'artist', 'character', 'wildcard', 'preset', 'event']},
                        'limit': LIMIT, 'rating': string(8), 'person': string(80),
                        'offset': {'type': 'integer', 'minimum': 0, 'maximum': 192}}, ['query', 'source']),
    'event_map': obj({'pins': array(string(100)), 'exclude': array(string(100)), 'limit': LIMIT,
                      'rating': string(8), 'person': string(80)}, ['pins']),
    'seek_conversation': obj({'query': string(), 'round_id': {'type': 'integer', 'minimum': 0, 'maximum': 10000},
                              'offset': {'type': 'integer', 'minimum': 0, 'maximum': 10000}, 'limit': LIMIT}, ['query']),
}
TOOL_DESC = {
    'search_tags': 'Search canonical TagSearchIndex for short Korean/English tag concepts and descriptions.',
    'fast_search': 'NAIA Fast Search: tag, artist, character, wildcard, preset, event. Events come from the current Event Map.',
    'event_map': 'Explore observed co-occurrence around exact English tag pins. Preserves exclusions. Counts are evidence, not intent.',
    'seek_conversation': 'Seek original earlier rounds. Use round_id or a keyword query. Follow next_offset for the next exact 1000-character excerpt. Current conversation only.',
}
TOOLS = [{'type': 'function', 'function': {'name': name, 'description': TOOL_DESC[name], 'parameters': schema}}
         for name, schema in TOOL_PARAMS.items()]
ROUTE_SCHEMA = RELATION_SCHEMA
COMPOSE_SCHEMA = CONVERT_SCHEMA
COMPACT_SCHEMA = obj({'retain_round_ids': array({'type': 'integer', 'minimum': 1, 'maximum': 300}, 4),
                      'preference_suggestions': array(obj({'value': string(240), 'evidence': string(240)}), 2)})


def validate(value, schema):
    kind = schema['type']
    if kind == 'object':
        if not isinstance(value, dict) or set(value) - set(schema['properties']) or set(schema['required']) - set(value):
            raise ValueError('Invalid object fields')
        for key, val in value.items():
            validate(val, schema['properties'][key])
    elif kind == 'array':
        if not isinstance(value, list) or len(value) > schema['maxItems']:
            raise ValueError('Invalid array')
        for val in value:
            validate(val, schema['items'])
    elif kind == 'integer':
        if type(value) is not int or not schema['minimum'] <= value <= schema['maximum']:
            raise ValueError('Invalid integer')
    elif kind == 'string':
        if not isinstance(value, str) or not schema.get('minLength',0) <= len(value) <= schema.get('maxLength', 1000) or '\x00' in value:
            raise ValueError('Invalid text')
        if 'enum' in schema and value not in schema['enum']:
            raise ValueError('Invalid enum')


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def clean_answer(text):
    text = re.sub(r'<think>.*?(?:</think>|$)', '', str(text), flags=re.S | re.I)
    return text.strip()


def structured(text, schema):
    # Gemma's renderer can wrap JSON despite Ollama format. Unwrap syntax only;
    # never execute text or accept arbitrary tool argument coercion.
    text = str(text).strip()
    if text.startswith('```') and text.endswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    data = json.loads(text)
    if schema == COMPACT_SCHEMA and isinstance(data, dict):
        data = {key: data[key] for key in schema['properties'] if key in data}
        data.setdefault('preference_suggestions', [])
    validate(data, schema)
    return data


class Stopped(Exception):
    pass


class Ollama:
    def __init__(self, endpoint='http://127.0.0.1:11435', model=MODEL):
        from urllib.parse import urlparse
        url = urlparse(endpoint)
        if url.scheme != 'http' or url.hostname not in {'127.0.0.1', 'localhost', '::1'} or url.username or url.password:
            raise ValueError('This lab only connects to a local Ollama endpoint')
        self.endpoint, self.model = endpoint.rstrip('/'), model

    def status(self):
        try:
            r = requests.get(self.endpoint + '/api/tags', timeout=3)
            r.raise_for_status()
            names = [m['name'] for m in r.json().get('models', [])]
            return {'ready': self.model in names, 'model': self.model, 'think': False, 'endpoint': self.endpoint}
        except Exception as exc:
            return {'ready': False, 'model': self.model, 'think': False, 'error': str(exc)}

    def chat(self, messages, *, tools=None, schema=None, timeout=90, tokens=700, context_size=DEFAULT_CONTEXT_SIZE, temperature=0.15):
        valid_context_size(context_size)
        payload = {'model': self.model, 'messages': messages, 'stream': False, 'think': False,
                   'keep_alive': '10m', 'options': {'temperature': temperature, 'num_ctx': context_size,
                   'num_predict': tokens, 'seed': 42, 'truncate': False, 'shift': False}}
        if tools:
            payload['tools'] = tools
        if schema:
            payload['format'] = schema
        started = time.monotonic()
        response = requests.post(self.endpoint + '/api/chat', json=payload, timeout=(3, max(1, min(120, timeout))))
        response.raise_for_status()
        data = response.json()
        if data.get('error') or not isinstance(data.get('message'), dict):
            raise ValueError(data.get('error') or 'Missing model message')
        msg = data['message']
        if msg.get('thinking'):
            raise ValueError('Model returned thinking despite think=false; response rejected')
        if data.get('done_reason') == 'length':
            raise ValueError('Model output reached its token limit')
        return msg, {'seconds': round(time.monotonic() - started, 2), 'input_tokens': data.get('prompt_eval_count', 0),
                     'output_tokens': data.get('eval_count', 0), 'think': False}


@dataclass
class Run:
    id: str
    session_id: str
    request_id: str
    text: str
    context_size: int = DEFAULT_CONTEXT_SIZE
    status: str = 'running'
    stage: str = 'routing'
    started: float = field(default_factory=time.monotonic)
    finished: float | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    trace: list = field(default_factory=list)
    usage: list = field(default_factory=list)
    route: dict = field(default_factory=dict)
    retrieval_intent: dict = field(default_factory=dict)
    scene_requested: bool = False
    answer: str = ''
    error: str = ''
    compaction: str = ''
    compaction_error: str = ''
    validation: list = field(default_factory=list)
    fallback_used: bool = False
    fallback_reason: str = ''

    def view(self):
        return {key: deepcopy(getattr(self, key)) for key in
                ('id', 'text', 'status', 'stage', 'trace', 'usage', 'route', 'answer', 'error', 'compaction', 'compaction_error', 'validation', 'fallback_used', 'fallback_reason')} | {
                    'context_size': self.context_size,
                    'elapsed': round((self.finished or time.monotonic()) - self.started, 1)}


class Lab:
    MAX_CALLS = 6
    MAX_TOOLS = 8
    MAX_SECONDS = 300

    def __init__(self, model, assets, state_dir):
        self.model, self.assets = model, assets
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.preference_path = self.state_dir / 'UserPreferences.md'
        self.settings_path = self.state_dir / 'settings.json'
        self.context_size = DEFAULT_CONTEXT_SIZE
        if self.settings_path.exists():
            self.context_size = valid_context_size(json.loads(self.settings_path.read_text(encoding='utf-8'))['context_size'])
        if not self.preference_path.exists():
            self.preference_path.write_text('# User preferences\n\n아직 저장된 선호가 없습니다.\n', encoding='utf-8')
        self.lock = threading.RLock()
        self.worker_active = False
        self.session_id = uuid.uuid4().hex
        self.summary = self.memory = ''
        self.archive = []
        self.current = None
        self.requests = {}

    def preferences(self):
        return self.preference_path.read_text(encoding='utf-8')[:3000]

    def save_preferences(self, text):
        if not isinstance(text, str) or len(text) > 3000:
            raise ValueError('선호 문서는 3000자 이하로 입력하세요.')
        with self.lock:
            tmp = self.preference_path.with_suffix('.tmp')
            tmp.write_text(text, encoding='utf-8')
            tmp.replace(self.preference_path)

    def set_context_size(self, value):
        value = valid_context_size(value)
        with self.lock:
            if self.worker_active:
                raise RuntimeError('답변이 끝난 뒤 컨텍스트 크기를 변경하세요.')
            tmp = self.settings_path.with_suffix('.tmp')
            tmp.write_text(dump({'context_size': value}), encoding='utf-8')
            tmp.replace(self.settings_path)
            self.context_size = value

    def state(self):
        with self.lock:
            return {'session_id': self.session_id, 'busy': self.worker_active, 'summary': self.summary,
                    'harness_version': 'creative-grounding-v9',
                    'context': {'size': self.context_size, 'choices': list(CONTEXT_SIZES),
                                'input_budget': self.context_size - OUTPUT_RESERVE - SAFETY_MARGIN,
                                'output_reserve': OUTPUT_RESERVE, 'safety_margin': SAFETY_MARGIN,
                                'last_exchange_round': self.archive[-1]['round_id'] if self.archive else None},
                    'memory': self.memory, 'preferences': self.preferences(), 'system_prompt': SYSTEM,
                    'rounds': deepcopy(self.archive), 'run': self.current.view() if self.current else None}

    def reset(self):
        with self.lock:
            if self.current:
                self.current.cancel.set()
            self.session_id = uuid.uuid4().hex
            self.archive.clear()
            self.summary = self.memory = ''
            self.current = None
            self.requests.clear()
        return self.state()

    def cancel(self):
        with self.lock:
            if self.current and self.worker_active:
                self.current.cancel.set()
                self.current.stage = 'cancel_requested'

    def submit(self, text, request_id, session_id):
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise ValueError('메시지는 1–4000자로 입력하세요.')
        if not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9-]{8,80}', request_id):
            raise ValueError('Invalid request ID')
        with self.lock:
            if session_id != self.session_id:
                raise ValueError('대화가 변경되었습니다. 화면을 새로고침하세요.')
            if request_id in self.requests:
                prior = self.requests[request_id]
                if prior.text != text.strip():
                    raise ValueError('Request ID reused with different text')
                return prior.id
            if self.worker_active:
                raise RuntimeError('이전 모델 호출이 끝날 때까지 기다려 주세요.')
            if len(self.archive) >= 300:
                raise ValueError('실험 세션 300라운드에 도달했습니다. 새 대화를 시작하세요.')
            run = Run(uuid.uuid4().hex, self.session_id, request_id, text.strip(), context_size=self.context_size)
            self.current = self.requests[request_id] = run
            self.worker_active = True
            threading.Thread(target=self._work, args=(run,), daemon=True).start()
            return run.id

    def alive(self, run):
        if run.cancel.is_set() or run.session_id != self.session_id:
            raise Stopped('cancelled')

    def check(self, run):
        self.alive(run)
        if time.monotonic() - run.started > self.MAX_SECONDS:
            raise TimeoutError('전체 실행 시간 한도에 도달했습니다.')

    def call_model(self, run, messages, *, schema=None, tools=None, tokens=700, stage='answer'):
        self.check(run)
        if len(run.usage) >= self.MAX_CALLS:
            raise RuntimeError('Model call budget exceeded')
        messages, budget = fit_messages(messages, run.context_size, tokens, schema=schema, tools=tools)
        run.stage = stage
        temperature = 0.65 if stage in {'grounded_answer','answer_revision','fallback_answer','answer'} else 0.15
        record = {'stage': stage, 'think': False, 'temperature': temperature, **budget}
        run.usage.append(record)  # Failed calls consume the same budget.
        msg, usage = self.model.chat(messages, schema=schema, tools=tools,
                                    timeout=self.MAX_SECONDS - (time.monotonic() - run.started), tokens=tokens,
                                    context_size=run.context_size, temperature=temperature)
        record.update(usage)
        self.check(run)
        if schema:
            return structured(msg.get('content', ''), schema)
        return msg

    def context(self):
        active = next((r for r in reversed(self.archive) if self._active_scene(r)), None)
        source_ids = active['route'].get('source_rounds',active['route'].get('scene_source_rounds', [active['round_id']])) if active else []
        old_design = active['route'].get('design') if active else None
        # Previous prose encouraged literal editing ("kneeling while standing").
        # Carry forward concrete settings, not the old display explanation.
        prior_pose = {k:old_design[k] for k in ('stance_en','body_en','left_hand_en','right_hand_en','camera_en','action_en') if k in old_design} if old_design else None
        last = self.archive[-1] if self.archive else None
        return {'UserPreferences.md': self.preferences(), 'Memory.md': '' if last else self.memory,
                'compacted_conversation': self.summary,
                'last_exchange': {'round_id': last['round_id'], 'user': last['user'],
                                  'assistant': last.get('assistant', ''), 'error': last.get('error', ''),
                                  'fallback_used': last.get('fallback_used', False)} if last else None,
                'active_intent': active['route'].get('must_keep',[]) if active else [],
                'active_design': prior_pose,
                'active_sources': [{'round_id': r['round_id'], 'user': r['user']} for r in reversed(self.archive) if r['round_id'] in source_ids],
                'recent_rounds': [{'round_id': r['round_id'], 'user_excerpt': r['user'][:300]}
                                  for r in self.archive[-3:-1]],
                'seekable_rounds': len(self.archive)}

    def seek(self, args, *, full=False):
        query, wanted = args.get('query', '').casefold(), args.get('round_id', 0)
        terms = re.findall(r'[\w]+', query)
        ranked = []
        for row in self.archive:
            hay = (row['user'] + '\n' + row['assistant']).casefold()
            score = sum(hay.count(t) for t in terms) if terms else 1
            if wanted:
                score = 100 if row['round_id'] == wanted else 0
            if score:
                ranked.append((score, row['round_id'], row))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        offset = args.get('offset', 0)
        items = []
        for _, _, r in ranked[:min(args.get('limit', 2), 3)]:
            end = max(len(r['user']), len(r['assistant'])) if full else offset + 1000
            items.append({'round_id': r['round_id'], 'user': r['user'][offset:end], 'assistant': r['assistant'][offset:end],
                          'offset': offset, 'next_offset': end if end < max(len(r['user']), len(r['assistant'])) else None})
        return {'source': 'current-session original transcript; exact excerpts, follow next_offset', 'items': items}

    def dispatch(self, run, name, args):
        self.check(run)
        if len(run.trace) >= self.MAX_TOOLS:
            raise RuntimeError('Tool budget exceeded')
        event = {'name': str(name)[:80], 'arguments': deepcopy(args), 'status': 'running'}
        run.trace.append(event)
        run.stage = 'tool:' + str(name)
        try:
            if name not in TOOL_PARAMS:
                raise ValueError('Tool is not in the allowlist')
            validate(args, TOOL_PARAMS[name])
            if name == 'event_map' and not args['pins']:
                raise ValueError('At least one pin required')
            if any(t['name'] == name and t['arguments'] == args for t in run.trace[:-1]):
                raise ValueError('Duplicate search; use the earlier result')
            data = self.seek(args) if name == 'seek_conversation' else self.assets.call(name, args)
            self.check(run)
            # Bound tool output structurally; never chop JSON in the middle.
            data = bound(data)
            event.update(status='ok', result=data)
            return data
        except Stopped:
            raise
        except Exception as exc:
            data = {'error': str(exc), 'tool': str(name), 'no_evidence': True}
            event.update(status='error', result=data)
            return data

    def _compact(self, run, context, round_id):
        run.stage = 'compacting'
        records = [*self.archive, {'round_id': round_id, 'user': run.text, 'route': run.route,
                                  'error': run.error, 'fallback_used': run.fallback_used}]
        evidence = {'rounds': [{'round_id': r['round_id'], 'user_excerpt': r['user'][:240]} for r in self.archive[-12:]],
                    'latest_user': run.text, 'current_round_id': round_id}
        selected, suggestions = [r['round_id'] for r in self.archive[-4:]], []
        try:
            data = self.call_model(run, [{'role': 'system', 'content': COMPACTOR},
                                         {'role': 'user', 'content': dump(evidence)}],
                                   schema=COMPACT_SCHEMA, tokens=450, stage='compacting')
            allowed_ids = {r['round_id'] for r in records}
            if not set(data['retain_round_ids']) <= allowed_ids:
                raise ValueError('Compaction referenced a nonexistent round')
            selected = data['retain_round_ids']
            # Persisted suggestions use the actual quote, never an inferred trait.
            suggestions = [{'value': p['evidence'], 'evidence': p['evidence']} for p in data['preference_suggestions']
                           if p['evidence'].strip() and p['evidence'] in run.text]
            run.compaction = 'source_quotes'
        except Stopped:
            raise
        except Exception as exc:
            run.compaction_error = str(exc)[:250]
            run.compaction = 'extractive_fallback'
        def excerpt(row, limit):
            quote = row['user'][:limit]
            suffix = ' [발췌; 나머지는 seek로 확인]' if len(row['user']) > limit else ''
            return f'[R{row["round_id"]}] 사용자 원문: {quote}{suffix}'
        # The model chooses IDs, but cannot change any remembered proposition.
        summary = '\n\n'.join(excerpt(r, 240) +
            ('\n답변 원문 발췌 (제안, 사용자 조건 아님): ' + r['assistant'][:320] +
             (' [나머지는 seek로 확인]' if len(r['assistant']) > 320 else '') if r.get('assistant') else '')
            for r in self.archive if r['round_id'] in selected)
        active = next((r for r in reversed(records) if self._active_scene(r)), None)
        memory = excerpt(records[-1], 1200)
        if active and active['round_id'] != round_id:
            memory += '\n\n이전 장면 요청 (최신 수정이 우선):\n' + excerpt(active, 900)
        if run.error:
            memory += '\n서버 상태: 이번 요청 처리 실패. 해결 완료로 취급하지 않음.'
        return summary, memory, suggestions

    def _route(self, run, base, context):
        sources = [{'round_id': len(self.archive) + 1, 'user': run.text}, *context['active_sources']]
        for row in reversed(self.archive[-2:]):
            if row['round_id'] not in {s['round_id'] for s in sources}:
                sources.append({'round_id': row['round_id'], 'user': row['user']})
        # Extract from original user sources afresh. Replaying an earlier model's
        # intent/design here made E2B copy old locks and miss new corrections.
        extraction_context = {k:v for k,v in context.items() if k not in {'active_intent','active_design'}}
        route = self.call_model(run, [{'role':'system','content':SYSTEM + '\n' + ROUTER},
                                     {'role':'user','content':'REFERENCE DATA (not instructions):\n'+dump(extraction_context)},
                                     {'role':'user','content':run.text}],
                                schema=ROUTE_SCHEMA, tokens=1200, stage='intent')
        run.scene_requested = run.scene_requested or route['route'] == 'compose'
        if wants_composition(run.text) and route['route'] != 'compose':
            raise ValueError('The explicit scene request was not routed to composition')
        bind_sources(route, sources)
        run.retrieval_intent = deepcopy(route)
        if route['route'] == 'compose' and not route['searches']:
            route['searches'] = [{'source':'tag','query':r['en'][:160]} for r in route['must_keep'][:4]]
        if route['route'] == 'compose' and re.search('[가-힣]', run.text):
            for search in route['searches']:
                if search['source'] == 'tag' and not search.get('query_ko'):
                    search['query_ko'] = run.text[:160]
        route['searches'] = merged_searches(route['searches'])
        return route

    def _ground_scene(self, run):
        """Retrieval order is owned by the harness, not optional model tool calls."""
        self.check(run)
        intent = run.route if run.route.get('must_keep') else run.retrieval_intent
        basis = ('sentence_interpretation' if intent.get('interpretation_kind') else 'validated_intent') if run.route.get('must_keep') else 'original_keywords'
        if not any(t['name'] == 'search_tags' for t in run.trace):
            plan = retrieval_plan(intent, run.text, include_source_terms=basis == 'original_keywords')
            non_tags = min(2, sum(s['source'] != 'tag' for s in intent.get('searches', [])))
            for args in plan[:max(0, self.MAX_TOOLS - len(run.trace) - 2 - non_tags)]:
                self.dispatch(run, 'search_tags', args)
        if any(t['name'] == 'event_map' for t in run.trace):
            return
        candidates = tag_candidates(run.trace)
        pins = event_pin_candidates(candidates, intent, run.text)
        try:
            self.check(run)
            if hasattr(self.assets, 'event_pins'):
                pins = self.assets.event_pins(pins)
        except (Stopped, TimeoutError):
            raise
        except Exception as exc:
            run.route['grounding'] = {'status': 'unavailable', 'event_queries': 0, 'reason': str(exc), 'basis': basis}
            return
        if not pins or len(run.trace) >= self.MAX_TOOLS:
            run.route['grounding'] = {'status': 'no_valid_pins' if not pins else 'budget_exhausted',
                                      'event_queries': 0, 'reason': 'No supported canonical event pins; no unrelated query substituted.', 'basis': basis}
            return
        from tools.e2b_chat_lab.creative_retrieval import event_query_plan
        plan = event_query_plan(pins, candidates) if intent.get('interpretation_kind') == 'creative_scene_v9' else [pins[:2]]
        outcomes = []
        for selected in plan:
            if len(outcomes) >= 2 or len(run.trace) >= self.MAX_TOOLS:
                break
            args = {'pins': selected, 'limit': 6}
            result = self.dispatch(run, 'event_map', args)
            outcomes.append((args, result))
            if not result.get('error') and result.get('ok') is not False and result.get('observed_posts') == 0 and len(selected) > 1 and len(outcomes) < 2 and len(run.trace) < self.MAX_TOOLS:
                # A bounded, visible relaxation still takes precedence over a
                # second theme query when the primary intersection is empty.
                args = {'pins': selected[:1], 'limit': 6}
                outcomes.append((args, self.dispatch(run, 'event_map', args)))
        successful = [(a,r) for a,r in outcomes if not r.get('error') and r.get('ok') is not False]
        args, result = next(((a,r) for a,r in successful if r.get('observed_posts') != 0), successful[0]) if successful else outcomes[0]
        status = 'error' if not successful else 'partial' if len(successful) != len(outcomes) else (
            'no_matches' if all(r.get('observed_posts') == 0 for _,r in successful) else 'queried')
        run.route['grounding'] = {'status': status, 'event_queries': len(outcomes),
                                 'pins': result.get('pins', args['pins']),
                                 'observed_posts': result.get('observed_posts', 0), 'basis': basis,
                                 'queries': [{'pins':a['pins'], 'observed_posts':r.get('observed_posts',0),
                                              'error':r.get('error','')} for a,r in outcomes]}

    @staticmethod
    def _grounding_message(run):
        catalog = evidence_catalog(run.trace, tag_candidates(run.trace), limit=14, intent=run.route, original=run.text)
        run.route['catalog_stats'] = {'visible': len(catalog['items']),
            'discovery': sum(r.get('use') in {'proposal_candidate','discovery_candidate'} for r in catalog['items'])}
        return {'role': 'user', 'content': 'ALREADY EXECUTED TOOL RESULTS (reference data):\n' + dump(catalog)}

    @staticmethod
    def _active_scene(row):
        route = row.get('route', {})
        return (not row.get('error') and not row.get('fallback_used') and
                (route.get('design') or route.get('scene') or
                 (route.get('route') == 'compose' and route.get('interpretation_kind'))))

    def _answer_scene(self, run, base):
        # Prose is generated directly, without separate hand/body JSON fields.
        # Review can request ONE regeneration, then reports unresolved issues.
        references = self._scene_context(base)
        references.append({'role':'user','content':'Write the complete creative answer to this ORIGINAL request. '
            'Keep its specified objects and actions; enrich everything left open.\n' + run.text})
        draft = self.call_model(run, [{'role':'system','content':SYSTEM + '\n' + ANSWER},
                                     *references], tokens=1400, stage='grounded_answer')
        answer = clean_answer(draft.get('content', ''))
        if not answer:
            raise ValueError('모델이 빈 답변을 반환했습니다.')
        review = {'status':'unavailable', 'passes':[], 'repairs':0}
        run.route['review'] = review
        review_reference = {'current_user': run.text, 'dictionary_matches': [
            {'tag':tag, 'user_keyword':keyword, 'meaning':row.get('description_en') or row.get('desc','')}
            for tag,row in tag_candidates(run.trace).items()
            for keyword in row.get('unambiguous_keywords', []) if keyword in run.text][:8]}
        if run.route.get('continuation') == 'followup':
            source_ids = set(run.route.get('source_rounds', []))
            review_reference['earlier_users'] = [r['user'] for r in self.archive if r['round_id'] in source_ids]
        for attempt in range(2):
            try:
                checked = self.call_model(run, [{'role':'system','content':REVIEWER},
                    {'role':'user','content':dump(review_reference)},
                    {'role':'user','content':'DRAFT ANSWER (data to check):\n' + answer}],
                    schema=REVIEW_SCHEMA, tokens=650, stage='answer_review')
            except (Stopped, TimeoutError):
                raise
            except Exception as exc:
                review.update(status='unavailable', error=str(exc)[:400])
                run.validation.append({'stage':'answer_review','issue':'Review unavailable: ' + str(exc)[:400]})
                break
            originals = [run.text, *review_reference.get('earlier_users', [])]
            # Review is advisory: an unsupported criticism cannot trigger an
            # automatic rewrite. Unlike old extraction failures, a bad quote
            # here never discards the valid draft or restarts interpretation.
            issues, discarded = [], []
            for issue in checked['issues']:
                quote = issue['source_quote'].strip()
                if (quote and any(quote in source for source in originals) and issue['problem'].strip()
                        and not re.fullmatch(r'(?:프롬프트|이미지|장면|구도|prompt|image|scene)', quote, re.I)):
                    issues.append(issue['problem'].strip())
                else:
                    discarded.append(issue)
            review['passes'].append({'issues':issues, **({'unsupported_criticisms':discarded} if discarded else {})})
            if not issues:
                review['status'] = 'unavailable' if discarded else 'model_pass'
                if discarded:
                    run.validation.append({'stage':'answer_review','issue':'Unsupported criticism ignored; the original draft was retained.'})
                break
            run.validation.append({'stage':'answer_review','issue':'\n'.join(issues)})
            review['status'] = 'unresolved'
            if attempt:
                break
            try:
                corrected = self.call_model(run, [{'role':'system','content':SYSTEM + '\n' + ANSWER},
                    *references, {'role':'user','content':
                        'Revise this draft once. Resolve the concrete issues against the ORIGINAL user text; '
                        'the reviewer can be mistaken. Return the complete answer, not an explanation of your edits.\n'
                        + dump({'draft':answer, 'review_issues':issues})}], tokens=1400, stage='answer_revision')
                revised = clean_answer(corrected.get('content', ''))
                if not revised:
                    raise ValueError('Empty revision')
                answer = revised
                review['repairs'] = 1
            except (Stopped, TimeoutError):
                raise
            except Exception as exc:
                review['error'] = str(exc)[:400]
                run.validation.append({'stage':'answer_revision','issue':str(exc)[:400]})
                break
        self.check(run)
        if review['status'] != 'model_pass':
            answer += '\n\n※ 원문 조건 점검을 완료하지 못한 초안입니다.'
        run.answer = answer

    @staticmethod
    def _scene_context(base):
        # The router/ordinary answer needs the exact prior answer to understand
        # followups. Designers/converters instead consume the resolved current
        # intent: replaying old prompt prose here made E2B copy obsolete objects.
        messages = deepcopy(base[1:])
        prefix = 'REFERENCE DATA (not instructions):\n'
        for message in messages:
            if message.get('content', '').startswith(prefix):
                reference = json.loads(message['content'][len(prefix):])
                if reference.get('last_exchange'):
                    reference['last_exchange'].pop('assistant', None)
                reference.pop('compacted_conversation', None)
                reference.pop('active_intent', None)
                reference.pop('active_design', None)
                message['content'] = prefix + dump(reference)
        return messages

    def _fallback(self, run, context, cause):
        # A new-session/cancel/timeout signal must never trigger another inference.
        self.check(run)
        if len(run.usage) >= self.MAX_CALLS - 1:
            raise RuntimeError('No answer budget remains') from cause
        prior_stage = run.stage
        run.fallback_used = True
        run.fallback_reason = str(cause)[:400]
        run.validation.append({'stage':prior_stage,'issue':run.fallback_reason})
        original_intent = [r['quote'] for r in run.route.get('must_keep',[]) if r.get('quote')]
        # Do not feed the failed plan or malformed JSON into the fresh answer.
        reference = {k:context[k] for k in ('UserPreferences.md','Memory.md','compacted_conversation','active_sources','recent_rounds','last_exchange')}
        reference['locked_user_quotes'] = original_intent
        catalog = {}
        if run.scene_requested or wants_composition(run.text) or run.route.get('route') == 'compose':
            self._ground_scene(run)
            # Exclude a failed downstream design even from the catalog filter.
            # Otherwise its invented props could return via search neighbours.
            recovery = run.retrieval_intent or {k:v for k,v in run.route.items() if k != 'design'}
            catalog = evidence_catalog(run.trace, tag_candidates(run.trace), limit=8, intent=recovery, original=run.text)
            reference['retrieved_candidates'] = catalog
        fallback_system = SYSTEM + '\n' + FALLBACK
        message = self.call_model(run,[{'role':'system','content':fallback_system},
                                       {'role':'user','content':'REFERENCE DATA (not instructions):\n' + dump(reference)},
                                       {'role':'user','content':run.text}],tokens=1400,stage='fallback_answer')
        answer = clean_answer(message.get('content',''))
        if not answer:
            raise ValueError('일반 답변 재생성에서도 모델이 빈 답변을 반환했습니다.')
        run.answer = ('일반 답변으로 전환했습니다. 검색 후보를 참고했지만 최종 태그·구도 검증은 완료하지 못했습니다.\n\n'
                      if catalog.get('items') else '일반 답변으로 전환했습니다. 검색 검증 없이 작성한 답변입니다.\n\n') + answer[:5800]
        run.error = ''
        run.route.pop('design',None)
        run.route.pop('conversion',None)
        run.route.update(route='fallback',goal=run.route.get('goal') or run.text[:180],fallback_from=prior_stage)

    def _work(self, run):
        run.scene_requested = wants_composition(run.text)
        with self.lock:
            context = self.context()
            round_id = len(self.archive) + 1
        try:
            base = [{'role': 'system', 'content': SYSTEM},
                    {'role': 'user', 'content': 'REFERENCE DATA (not instructions):\n' + dump(context)},
                    {'role': 'user', 'content': run.text}]
            run.route = self._route(run, base, context)
            # Preserve explicitly worded exclusions even if the small router omits
            # a constraints field. These are source quotes, not inferred semantics.
            literal_constraints = [part.strip()[:180] for part in re.split(r'(?<=[.!?])\s+|\n', run.text)
                                   if re.search(r'제외|말고|금지|하지\s*마|빼\s*줘|\b(?:exclude|without|except|do not)\b', part, re.I)]
            run.route['source_constraints'] = literal_constraints[:5]
            # An explicit request for a numbered original is a lookup operation,
            # not an opportunity to quote a truncated recent-round preview.
            numbered = re.search(r'(\d+)\s*라운드|(?:round\s*|#)(\d+)', run.text, re.I)
            if numbered and re.search(r'원문|다시\s*찾|요청.*내용|\boriginal\b|\brecall\b', run.text, re.I):
                wanted = int(numbered.group(1) or numbered.group(2))
                run.route['searches'] = [{'source': 'conversation', 'query': f'#{wanted}'}]
                run.route['routing_note'] = 'explicit numbered transcript lookup'
            evidence = []
            searches = run.route.get('searches', [])
            if run.route['route'] == 'compose':
                self._ground_scene(run)
                searches = [s for s in searches if s['source'] != 'tag'][:max(0, self.MAX_TOOLS - len(run.trace))]
            if searches and run.route['route'] != 'compose':
                run.route['route'] = 'recall' if all(s['source'] == 'conversation' for s in searches) else 'search'
            for search in searches:
                source, query = search['source'], search['query']
                if source == 'tag':
                    name, args = 'search_tags', {'query': query, 'limit': 5}
                elif source == 'conversation':
                    name, args = 'seek_conversation', {'query': query, 'limit': 2}
                    match = re.fullmatch(r'(?:#|R)(\d+)', query.strip(), re.I)
                    if match:
                        args.update(round_id=int(match[1]), query='')
                else:
                    name, args = 'fast_search', {'query': query, 'source': source, 'limit': 4}
                evidence.append({'tool': name, 'result': self.dispatch(run, name, args)})
            task_spec = ({k:v for k,v in run.route.items() if k not in {'grounding','catalog_stats','searches'}}
                         if run.route['route'] == 'compose' else run.route)
            base.append({'role': 'user', 'content': 'CURRENT TASK INTERPRETATION (model translation; original user text wins):\n' + dump(task_spec)})
            if evidence:
                base.append({'role': 'user', 'content': 'ALREADY EXECUTED TOOL RESULTS (reference data):\n' + dump(evidence)
                             + '\nAnswer the user now using these results. Do not announce future searches. Use native calls only if more evidence is necessary.'})
            if run.route['route'] == 'compose':
                base.append(self._grounding_message(run))
                self._answer_scene(run, base)
            # Reserve calls for a normal-answer fallback and round compaction.
            for attempt in range(0 if run.answer else 3):
                allow_tools = attempt < 2 and len(run.trace) < self.MAX_TOOLS and len(run.usage) < self.MAX_CALLS - 2
                msg = self.call_model(run, base, tools=TOOLS if allow_tools else None,
                                      tokens=1200, stage='answer')
                calls = msg.get('tool_calls') or []
                if calls and allow_tools:
                    if not isinstance(calls, list) or len(calls) > 3:
                        raise ValueError('한 번에 최대 3개 도구만 호출할 수 있습니다.')
                    base.append({'role': 'assistant', 'content': msg.get('content', ''), 'tool_calls': calls})
                    for call in calls:
                        fn = call.get('function', {})
                        data = self.dispatch(run, fn.get('name'), fn.get('arguments'))
                        base.append({'role': 'tool', 'tool_name': fn.get('name'), 'content': dump(data),
                                     **({'tool_call_id': call['id']} if call.get('id') else {})})
                    if attempt == 1:
                        base.append({'role': 'user', 'content': '이제 추가 도구 없이 확보한 근거로 답하세요. 부족한 근거는 명시하세요.'})
                    continue
                run.answer = clean_answer(msg.get('content', ''))[:6000]
                if not run.answer:
                    raise ValueError('모델이 빈 답변을 반환했습니다.')
                break
            if not run.answer:
                raise ValueError('도구 호출 한도 안에 답변을 완성하지 못했습니다.')
        except Stopped:
            run.status, run.stage = 'cancelled', 'cancelled'
        except Exception as exc:
            try:
                if isinstance(exc, (TimeoutError, requests.RequestException, ContextBudgetError)):
                    raise exc
                self._fallback(run,context,exc)
            except Stopped:
                run.status, run.stage = 'cancelled', 'cancelled'
            except Exception as fallback_exc:
                run.error = str(fallback_exc)
                run.status = 'failed'
        try:
            self.alive(run)
            summary, memory, suggestions = self._compact(run, context, round_id)
            self.alive(run)
            with self.lock:
                self.alive(run)
                self.summary, self.memory = summary, memory
                self.archive.append({'round_id': round_id, 'user': run.text, 'assistant': run.answer,
                                     'error': run.error, 'route': run.route, 'trace': deepcopy(run.trace),
                                     'compaction': run.compaction, 'preference_suggestions': suggestions,
                                     'validation': deepcopy(run.validation), 'fallback_used':run.fallback_used,
                                     'fallback_reason':run.fallback_reason})
                run.status = 'failed' if run.error else 'completed'
                run.stage = run.status
        except Stopped:
            run.status, run.stage = 'cancelled', 'cancelled'
        except Exception as exc:
            run.error = str(exc)
            run.status, run.stage = 'failed', 'failed'
        finally:
            with self.lock:
                run.finished = time.monotonic()
                self.worker_active = False


def bound(value, depth=0):
    if depth > 6:
        return '[nested data omitted]'
    if isinstance(value, str):
        return value[:1200]
    if isinstance(value, list):
        return [bound(v, depth + 1) for v in value[:8]]
    if isinstance(value, dict):
        return {k: bound(v, depth + 1) for k, v in list(value.items())[:18]}
    return value
