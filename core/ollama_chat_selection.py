"""Run-local candidate references and factual event provenance.

This is a transport adapter, not a second semantic validator. Expanded finishes
must still pass the normal plan, grounding, direction and semantic checks.
"""
from __future__ import annotations

import copy


def norm(tag):
    return ' '.join(str(tag).replace('_', ' ').casefold().split())


class SelectionRegistry:
    def __init__(self):
        self.candidates = {}
        self.ids = {}
        self.bundles = {}

    def register(self, output, arguments):
        """Copy provider data; cached responses and other requests remain untouched."""
        output = copy.deepcopy(output)
        for event in output.get('events', []):
            for combo in event.get('combos', []):
                bid = combo.get('bundle_id')
                if not bid:
                    continue  # Legacy providers carry no certified bundle identity.
                conditions = {k: output.get(k) for k in ('rating', 'person_id', 'detail')}
                bundle = self.bundles.setdefault(bid, {
                    'bundle_id': bid, 'tags': list(combo['tags']), 'conditions': conditions,
                    'source': output.get('source'), 'observations': [], 'searches': []})
                if set(bundle['tags']) != set(combo['tags']) or bundle['conditions'] != conditions:
                    raise ValueError('Conflicting event bundle identity')
                observation = {'event_id': event['id'], 'count': combo.get('count')}
                search = {k: output.get(k) for k in ('query', 'matched_query')}
                search['requirement_ids'] = list(arguments.get('requirement_ids', []))
                for key, value in (('observations', observation), ('searches', search)):
                    if value not in bundle[key]:
                        bundle[key].append(value)
        rows = list(output.get('tags', []))
        rows += [r for s in output.get('searches', []) for r in s.get('results', [])]
        for row in rows:
            tag = str(row.get('tag') or '').strip()
            if not tag:
                continue
            key = norm(tag)
            cid = self.ids.setdefault(key, f'c{len(self.ids) + 1}')
            self.candidates.setdefault(cid, key)
            row['candidate_id'] = cid
        for event in output.get('events', []):
            for combo in event.get('combos', []):
                combo['candidate_ids'] = [self.ids[norm(t)] for t in combo['tags']
                                          if norm(t) in self.ids]
        return output

    def expand(self, compact, plan, ledger):
        if plan is None:
            raise ValueError('Use plan_search before finish_selection')
        actors = [{k: a[k] for k in ('id', 'name')} | {'tags': []} for a in plan['actors']]
        scopes = {a['id']: a['tags'] for a in actors}
        if 'common' in scopes:
            raise ValueError('Actor id common is reserved for shared tags')
        scopes['common'] = []
        claims = {r['id']: {'requirement_id': r['id'], 'tags': [], 'state': 'missing'}
                  for r in plan['requirements']}
        for choice in compact.get('choices', []):
            owner = choice['owner_id']
            if owner not in scopes:
                raise ValueError('Unknown owner_id; valid scopes: ' + ', '.join(scopes) +
                                 '. Use common for a word lookup; copy an ID, not an actor name.')
            rids = choice['requirement_ids']
            if not rids or len(rids) != len(set(rids)) or not set(rids).issubset(claims):
                raise ValueError('Choice must reference unique planned requirement_ids')
            for cid in choice['candidate_ids']:
                key = self.candidates.get(cid)
                if key is None or key not in ledger:
                    raise ValueError('Unknown candidate_id; current choices: ' + ', '.join(
                        f'{cid}={ledger[k]["tag"]}' for cid, k in self.candidates.items() if k in ledger))
                entry = ledger[key]
                evidence = {rid for e in entry.get('evidence', []) for rid in e.get('requirement_ids', [])}
                unbound = {rid for e in entry.get('evidence', []) for rid in e.get('unattributed_requirement_ids', [])}
                if not set(rids).issubset(evidence | unbound):
                    raise ValueError('Candidate was not retrieved for these requirement_ids; ' +
                        f'{cid}={entry["tag"]} links to {sorted(evidence)}. Select its linked requirements, '
                        'leave others unresolved, or search their concepts.')
                linked = [rid for rid in rids if rid in evidence]
                if not linked:
                    continue  # A partial query hit cannot select an unbound requirement.
                if entry['tag'] not in scopes[owner]:
                    scopes[owner].append(entry['tag'])
                for rid in linked:
                    claim = claims[rid]
                    claim['state'] = 'selected'
                    if entry['tag'] not in claim['tags']:
                        claim['tags'].append(entry['tag'])
        unresolved = set()
        for item in compact.get('unresolved', []):
            rid = item['requirement_id']
            # 모르는 id·중복·이미 선택된 요구는 건너뛴다(선택이 이긴다). 예전엔 ValueError 로 turn 을
            # 태웠고, 26B 가 그 뒤 plan_search 를 다시 불러 stopped 로 끝났다(2026-09-13 실측).
            if rid not in claims or rid in unresolved or claims[rid]['tags']:
                continue
            unresolved.add(rid)
            claims[rid]['state'] = item['state']
        result = {k: copy.deepcopy(v) for k, v in compact.items()
                  if k not in {'choices', 'unresolved'}}
        result.update(actors=actors, common_tags=scopes['common'],
                      relations=copy.deepcopy(compact.get('relations', [])), selections=list(claims.values()))
        return result

    def attach(self, result):
        """Describe the FINAL, semantically filtered tag set, never pre-filter claims."""
        if result.get('type') != 'scene_agent':
            return result
        scene = result['scene']
        scopes = {'common': scene['common_tags']}
        scopes.update({a['id']: a['tags'] for a in scene['actors']})
        selected = {norm(t) for tags in scopes.values() for t in tags}
        bundles, exact, subset = [], False, False
        for original in self.bundles.values():
            tags = {norm(t) for t in original['tags']}
            if not selected & tags:
                continue
            row = copy.deepcopy(original)
            row['retained_by_owner'] = {owner: [t for t in values if norm(t) in tags]
                                        for owner, values in scopes.items() if any(norm(t) in tags for t in values)}
            row['whole_bundle_retained'] = tags.issubset(selected)
            row['matches_final_tag_set'] = tags == selected
            row['semantic_certified'] = False
            exact |= tags == selected
            subset |= selected.issubset(tags)
            bundles.append(row)
        result['event_provenance'] = {
            'version': 'event-selection-v1', 'bundles': bundles,
            'tag_set_status': ('matches_observation' if exact else 'subset_of_observation' if subset else
                               'recomposed' if bundles else 'no_event_evidence'),
            'scope': 'Tag-set evidence only; actor ownership, direction and intent are not certified.'}
        return result
