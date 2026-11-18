"""Classify preset families from the map and two-depth subcategories only."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import numpy as np
from presets_engine import ROOT, MAP, DATA, EventMapIndex, fingerprint, json_bytes, git_head, log

SINGLE_PARTS = ['1girl_solo', '1girl', '1boy_solo', '1boy']
MULTI_PARTS = ['1girl_1boy', '1girl_multiple_boys', '2girls', 'multiple_girls',
               '1boy_multiple_girls', '2boys', 'multiple_boys', 'multiple_girls_multiple_boys']
TARGET_PARTS = SINGLE_PARTS + ['1girl_1boy', '2girls', '2boys']
# 2026-11-17 첫 빌드 실측. 시제품(1399 · 780 · 667 · 484 · 217)보다 적은 것은 빈도 하한 200 을 대상 풀(한 사람 넷 + 1girl_1boy ·
# 2girls · 2boys)에서만 세기 때문이다(시제품은 모든 분면). 이후의 뜻하지 않은 어휘 흔들림을 잡는 가드.
# outfit_state 479 = 467 + 의상 어휘에서 state 로 옮긴 12개(11-17).
EXPECTED = {'event': 1314, 'link': 692, 'scene': 588, 'outfit_state': 479, 'expression': 204}
GENERIC_GARMENTS = set('clothes clothing outfit uniform underwear swimsuit legwear headwear eyewear footwear handwear neckwear'.split()) | {'bikini bottom', 'bikini top'}
PRE = sorted(['partially unbuttoned', 'partially unzipped', 'partially removed', 'unworn', 'naked', 'no', 'open', 'unbuttoned', 'untied', 'unzipped', 'undone', 'torn', 'wet', 'adjusting', 'tugging', 'removing', 'taking off', 'putting on', 'pulling', 'lifting', 'lifting own', 'holding', 'holding unworn', 'holding removed', 'unfastened', 'loose', 'see-through', 'wardrobe', 'grabbing', 'biting'], key=len, reverse=True)
SUF = sorted(['partially removed', 'removed', 'lift', 'lift up', 'pull', 'pulled down', 'aside', 'down', 'off', 'grab', 'tug', 'on head', 'around neck', 'around waist', 'only', 'malfunction', 'hold', 'slip', 'in mouth', 'over shoulder', 'partially unbuttoned', 'partially unzipped'], key=len, reverse=True)
TYPE_RULES = [
    ('lift', r' lift( up)?$|^lifting'),
    ('pull', r' (pull|pulled|pulled down|aside|down)$|^pulling|tug'),
    ('off', r'^(unworn|partially removed|removing|taking off)| removed$|undress'),
    ('open', r'^(open|unbuttoned|partially unbuttoned|untied|unzipped|partially unzipped|undone|unfastened|loose)'),
    ('damage', r'^(torn|wet|see-through|dirty|burnt|damaged)'),
    ('exposure', r'^(naked|no) | only$|^(topless|bottomless|nude|completely nude|topless male|topless female)$'),
    ('handle', r'^(adjusting|putting on|dressing|holding|grabbing)'),
    ('worn_elsewhere', r' (on head|around neck|around waist|over shoulder)$'),
]
TYPES = [t for t, _ in TYPE_RULES] + ['reveal', 'other']


def garment_names(vocabulary):
    return {n for n, row in vocabulary.items() if row['class'] == 'garment'} | GENERIC_GARMENTS


def garment_of(name, garments):
    for prefix in PRE:
        if name.startswith(prefix + ' ') and name[len(prefix) + 1:] in garments:
            return name[len(prefix) + 1:]
    for suffix in SUF:
        if name.endswith(' ' + suffix) and name[:-len(suffix) - 1] in garments:
            return name[:-len(suffix) - 1]
    return None


def state_type(name, sub=None):
    for kind, pattern in TYPE_RULES:
        if re.search(pattern, name):
            return kind
    return 'reveal' if sub == '착의·노출 상태' else 'other'


def classify(name, lane, color, role, group, sub, outfit, garments, overrides):
    if name in overrides.get('exclude', {}):
        return None
    override = overrides.get('family', {}).get(name)
    if override is not None:
        base = classify(name, lane, color, role, group, sub, outfit, garments,
                        {'exclude': overrides.get('exclude', {}), 'family': {}})
        row = dict(base or {}, **override)
        if row.get('family') == 'outfit_state':
            row.setdefault('kind', 'event' if role in {'event_core', 'adult_act'} or group == 'action' else 'state')
            row.setdefault('type', state_type(name, sub))
            row.setdefault('garment', garment_of(name, garments))
        return row
    if lane == 'guarded' or color or outfit.get('class') in {'garment', 'modifier', 'color', 'noslot'}:
        return None
    garment = garment_of(name, garments)
    row = None
    if (outfit.get('class') == 'state' or (group, sub) in
            {('clothing', '착의·노출 상태'), ('action', '옷 다루기')} or
            (group in {'action', 'adult', 'clothing', 'situation'} and garment is not None)):
        row = dict(family='outfit_state', kind='event' if role in {'event_core', 'adult_act'} or group == 'action' else 'state',
                   type=state_type(name, sub), garment=garment)
    elif group == 'expression':
        row = dict(family='expression', slot=sub)
    elif group == 'action' or (group == 'adult' and role == 'adult_act'):
        row = dict(family='event', slot=f'{group}:{sub}')
    elif group == 'scene':
        row = dict(family='scene', slot=sub)
    override = overrides.get('family', {}).get(name)
    if override is not None:
        row = dict(row or {}, **override)
    return row


def check_counts(tags):
    counts = Counter(row['family'] for row in tags.values())
    log('family_counts ' + json.dumps(dict(counts), sort_keys=True))
    for family, expected in EXPECTED.items():
        if abs(counts[family] / expected - 1) > 0.02:
            raise ValueError('vocabulary count outside 2 percent: %s=%d; update EXPECTED after first measured review' % (family, counts[family]))
    return dict(counts)


def build_vocab(ix, outfit, subcategories, overrides):
    if overrides.get('schema') != 'naia.preset_vocab_overrides.v1':
        raise ValueError('override schema')
    pid = {n: i for i, n in enumerate(ix.partitions)}
    live = ix.offsets[1:len(ix.part_arr) + 1] > ix.offsets[:len(ix.part_arr)]
    groups = {key: [pid[f'{r}_{p}'] for r in 'gsqe' for p in parts]
              for key, parts in [('single', SINGLE_PARTS), ('multi', MULTI_PARTS), ('target', TARGET_PARTS)]}
    garments, tags = garment_names(outfit), {}
    for tid in range(ix.n_tags):
        name = ix.by_id[tid]
        group, sub = subcategories.get(name, (None, None))
        row = classify(name, ix.lane.get(tid), ix.color[tid], ix.role[tid], group, sub,
                       outfit.get(name, {}), garments, overrides)
        if row is None:
            continue
        posts = ix.posting(tid)
        posts = posts[posts < len(live)]
        posts = posts[live[posts]]
        counts = np.bincount(ix.part_arr[posts], minlength=256)
        if counts[groups['target']].sum() < 200:
            continue
        multi, single = counts[groups['multi']].sum(), counts[groups['single']].sum()
        share = float(multi / max(1, multi + single))
        if row['family'] == 'event' and share >= 0.6:
            row['family'] = 'link'
        row.update(overrides.get('family', {}).get(name, {}))
        if row['family'] not in EXPECTED:
            raise ValueError('unknown family: ' + name)
        if row['family'] == 'outfit_state':
            if row.get('kind') not in {'event', 'state'} or row.get('type') not in TYPES or 'garment' not in row:
                raise ValueError('incomplete state override: ' + name)
        elif not isinstance(row.get('slot'), str):
            raise ValueError('missing slot: ' + name)
        row['multi_share'] = round(share, 4)
        tags[name] = row
    return tags


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--map', default=MAP)
    ap.add_argument('--subcategories', type=Path, default=ROOT / 'data/event_map_subcategories.json')
    ap.add_argument('--outfit-vocab', type=Path, default=DATA / 'outfit_vocab.json')
    ap.add_argument('--overrides', type=Path, default=DATA / 'preset_vocab_overrides.json')
    ap.add_argument('--out', type=Path, default=DATA / 'preset_vocab.json')
    args = ap.parse_args(argv)
    ix = EventMapIndex(args.map)
    try:
        outfit = json.loads(args.outfit_vocab.read_text(encoding='utf-8'))
        if outfit['schema'] != 'naia.outfit_vocab.v1':
            raise ValueError('outfit vocabulary schema')
        tags = build_vocab(ix, outfit['tags'], json.loads(args.subcategories.read_text(encoding='utf-8'))['tags'],
                           json.loads(args.overrides.read_text(encoding='utf-8')))
        counts = check_counts(tags)
        result = dict(schema='naia.preset_vocab.v1', multi_parts=MULTI_PARTS, single_parts=SINGLE_PARTS, tags=tags,
                      build=dict(built_at=datetime.now(timezone.utc).isoformat(), builder='build_preset_vocab.py',
                                 git_head=git_head(), counts=counts,
                                 inputs={k: fingerprint(p) for k, p in dict(map=args.map, outfit_vocab=args.outfit_vocab,
                                                                          subcategories=args.subcategories, overrides=args.overrides).items()}))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(json_bytes(result))
    finally:
        ix.close()


if __name__ == '__main__':
    main()
