"""Request-local lookup attribution and bounded execution diagnostics.

Source aliases are retrieval evidence. Only the existing reviewed sense table
can support a lexical meaning; neither aliases nor event observations prove roles.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
import time

from core.ollama_chat_semantics import alias_senses, norm, request_requirements, BY_ID


def validation_failure_key(tool, error):
    text = str(error)
    for category in ('Unknown owner_id', 'Unknown candidate_id', 'Candidate was not retrieved',
                     'Character identity mismatch', 'Unverified tags', 'direction mismatch',
                     'reference a planned actor id', 'source must be an exact substring'):
        if category in text:
            return (tool, category)
    return (tool, text)


class ExecutionTrace:
    def __init__(self):
        self.started = time.perf_counter()
        self.timings = {}
        self.failures = {}
        self.model_calls = 0

    @contextmanager
    def measure(self, stage):
        start = time.perf_counter()
        try:
            yield
        finally:
            row = self.timings.setdefault(stage, {'calls': 0, 'seconds': 0.0})
            row['calls'] += 1
            row['seconds'] += time.perf_counter() - start

    def failure(self, signature, turn):
        # An intervening successful lookup cannot erase an earlier failed finish.
        row = self.failures.setdefault(signature, {'turns': set(), 'count': 0})
        if turn not in row['turns']:
            row['turns'].add(turn)
            row['count'] += 1
        return row['count']

    def snapshot(self, calls_used, grounding=None):
        return {'version': 'chat-execution-v1', 'model_calls': self.model_calls,
                'tool_units': calls_used, 'wall_seconds': round(time.perf_counter()-self.started, 6),
                'timings': {k: {**v, 'seconds': round(v['seconds'], 6)} for k, v in self.timings.items()},
                'failure_counts': {str(k): v['count'] for k, v in self.failures.items()},
                'source_lookups': copy.deepcopy(grounding.observations) if grounding else {}}


class SourceGrounding:
    def __init__(self, plan):
        self.plan = plan
        self.requirements = {r['id']: r for r in plan['requirements']}
        actors = {a['id']: a for a in plan['actors']}
        self.named = {r['id']: [actors[a]['name'] for a in r['actors']
                               if actors[a]['identity'] == 'named']
                      for r in plan['requirements'] if r['kind'] == 'entity'}
        self.named = {k: v for k, v in self.named.items() if v}
        self.observations = {}
        self.lookup_count = 0

    def named_jobs(self, ids):
        jobs = {}
        for rid in ids:
            for name in self.named.get(rid, []):
                jobs.setdefault(name, []).append(rid)
        return [{'query': q, 'requirement_ids': rids} for q, rids in jobs.items()]

    def source_rows(self, rid, rows):
        """Exclude category-only hits from automatic auxiliary candidates.

        A reviewed alias (gift, breasts, etc.) remains usable even when its raw
        dictionary spelling happened to be stored as a category label.
        """
        req = self.requirements[rid]
        source = norm(req['source'])
        senses = alias_senses(source)
        reviewed = {norm(t) for s in senses for t in s['tags']}
        accepted = []
        for row in rows:
            tag = norm(row.get('tag'))
            exact_alias = (row.get('keyword_origin') in {'alias', 'both', 'reviewed_alias'}
                           and row.get('match_kind') in {'keyword_exact', 'reviewed_alias_exact',
                                                       'keyword_spacing_variant'})
            # Source callback is the production query adapter, but still verify
            # the spelling evidence rather than trusting arbitrary row labels.
            matched = norm(row.get('matched_keyword'))
            spelling = matched == source or (row.get('spacing_collision_free') is True
                and matched.replace(' ', '') == source.replace(' ', ''))
            from core.named_entity_aliases import is_named_entity_result

            if tag and (tag in reviewed or tag == source or (exact_alias and spelling)
                        or is_named_entity_result(row, source)):
                accepted.append(copy.deepcopy(row))
        self.observations[rid] = {
            'query': req['source'], 'status': ('candidates' if accepted else
                'label_only' if rows and all(r.get('keyword_origin') == 'label' for r in rows) else 'no_match'),
            'candidate_tags': [r['tag'] for r in accepted], 'excluded_count': len(rows)-len(accepted),
            'meaning_status': 'unknown'}
        return accepted

    def attribute(self, row, tool, args, origin):
        declared = list(args.get('requirement_ids', []))
        tag = norm(row.get('tag'))
        queries = args.get('queries', [args.get('query', '')])
        query = norm(row.get('search_query') or args.get('query') or (queries[0] if len(queries) == 1 else ''))
        mixed = args.get('_mixed_requirements', False) or len({
            norm(self.requirements[r]['source']) for r in declared if r in self.requirements}) > 1
        bound = []
        for rid in declared:
            req = self.requirements.get(rid)
            if req is None or origin == 'validation':
                continue
            if rid in self.named and tool != 'search_characters':
                continue
            observation = self.observations.get(rid, {})
            admitted = {norm(t) for t in observation.get('candidate_tags', [])}
            reviewed_req = request_requirements(req['source'])
            reviewed = {norm(t) for sid in reviewed_req['positive'] for t in BY_ID[sid]['tags']}
            if tool == 'search_events':
                # A bundle really may represent several conditions. This is
                # retrieval attribution only, never proof of actor roles.
                bound.append(rid)
            elif tool == 'search_characters':
                if rid in self.named:
                    bound.append(rid)
            elif tag in admitted or tag in reviewed:
                bound.append(rid)
            elif observation.get('status') == 'label_only' and (mixed or query == norm(req['source'])):
                continue  # Unknown source cannot borrow a different concept.
            elif row.get('keyword_origin') == 'label':
                continue
            elif not mixed or tag == query:
                # Keep explicit single-concept/many-requirement queries usable.
                # Merely matching part of a mixed query does not bind every ID.
                bound.append(rid)
        return {'requirement_ids': bound, 'declared_requirement_ids': declared,
                'unattributed_requirement_ids': [rid for rid in declared if rid not in bound]}

    def review(self, rid, selected):
        req = self.requirements[rid]
        senses = alias_senses(req['source'])
        tags = {norm(t) for t in selected}
        status, reason, ids = 'unknown', 'no_reviewed_meaning', []
        if not tags:
            reason = 'source_label_only' if self.observations.get(rid, {}).get('status') == 'label_only' else 'no_selection'
        elif len(senses) == 1 and req['kind'] in {'entity', 'attribute', 'action'}:
            allowed = {norm(t) for t in senses[0]['tags']}
            if tags.issubset(allowed):
                status, reason, ids = 'supported', 'reviewed_lexical_sense', [senses[0]['id']]
        return {'status': status, 'reason': reason, 'sense_ids': ids,
                'scope': 'Reviewed lexical meaning only; roles, causes and whole-request completeness are not certified.'}
