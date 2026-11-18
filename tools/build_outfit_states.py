"""Bake outfit state/event catalog and exact per-layer outfit-set links."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from presets_engine import ROOT, POOLS, fingerprint, json_bytes, git_head
from build_family_presets import add_inputs, initialize, load_vocab, MIN_SUP, FLOOR
from build_preset_vocab import TYPES


def calibration(states):
    def garments(name):
        return [row[0] for row in states.get(name, {}).get('pools', {}).get('female', {}).get('garments', [])]
    checks = {
        'open_jacket': garments('open jacket')[:1] == ['jacket'],
        'skirt_lift': states.get('skirt lift', {}).get('kind') == 'event' and
                      states.get('skirt lift', {}).get('type') == 'lift' and 'skirt' in garments('skirt lift'),
        'nude': states.get('nude', {}).get('kind') == 'state' and states.get('nude', {}).get('type') == 'exposure',
        'holding_hands_absent': 'holding hands' not in states,
        'no_bra': states.get('no bra', {}).get('kind') == 'state' and states.get('no bra', {}).get('type') == 'exposure',
    }
    if not all(checks.values()):
        raise ValueError('state calibration failed: ' + json.dumps(checks, sort_keys=True))
    return checks


def build_pack(args, engine, checked, vocabulary, outfit_pack):
    if outfit_pack.get('schema') != 'naia.outfit_presets.v1':
        raise ValueError('outfit pack schema')
    entries = {n: row for n, row in vocabulary['tags'].items() if row['family'] == 'outfit_state'}
    engine.configure(slots={n: row['kind'] for n, row in entries.items()}, caps={'*': 2},
                     pools=POOLS, min_sup=MIN_SUP, floor=FLOOR, kind_fn=lambda t: t)
    garment_mask = engine.mask(n for n, row in engine.VOCAB['tags'].items() if row['class'] == 'garment')
    garment_base = engine.base_rates(garment_mask)
    state_base = engine.base_rates(engine.mask(entries))
    states = {}
    for name, entry in sorted(entries.items()):
        rec = {key: entry[key] for key in ('kind', 'type', 'garment')}
        rec['pools'] = {}
        for pool in POOLS:
            rids, per = engine.exact(pool, [name])
            cs, cid = engine.top_share(rids, engine.prim, exact=True)
            ys, yid = engine.top_share(rids, engine.primcp, exact=True)
            status = ('few' if rids.size < MIN_SUP[pool] else 'character_bound' if cs > engine.CHAR_GATE
                      else 'copyright_bound' if ys > engine.CP_GATE else 'ok')
            rec['pools'][pool] = dict(status=status, support_by_rating=per, top_character=[cs, engine.nm(cid)],
                top_copyright=[ys, engine.nm(yid)], garments=engine.associations(rids, [name], garment_mask,
                    garment_base[pool, 'gsqe'], limit=6, sample=None, exclude_implied=False) if status == 'ok' else [])
        states[name] = rec
    masks = {(pool, kind): engine.mask(n for n, row in states.items() if row['kind'] == kind and
                                      row['pools'][pool]['status'] == 'ok')
             for pool in POOLS for kind in ('event', 'state')}
    by_set = {}
    for rec in outfit_pack['sets']:
        pool = rec['pool']
        rids, _ = engine.exact(pool, rec['tags'])
        layers = {}
        for layer in rec['layers']:
            st = engine.STS[pool, layer]
            rl = rids[st['lut'][engine.ix.part_arr[rids]]]
            sides = {kind: engine.associations(rl, rec['tags'], masks[pool, kind], state_base[pool, layer],
                                              share_min=0.10, limit=4, sample=None, exclude_implied=False)
                     for kind in ('event', 'state')}
            sides = {kind: rows for kind, rows in sides.items() if rows}
            if sides:
                layers[layer] = sides
        if layers:
            by_set[rec['id']] = layers
    checks = calibration(states)
    return dict(schema='naia.outfit_states.v1', note='tools/build_outfit_states.py 가 굽는다. 손으로 고치지 말 것',
        build=dict(built_at=datetime.now(timezone.utc).isoformat(), builder='build_outfit_states.py', git_head=git_head(),
                   inputs={k: fingerprint(p) for k, p in dict(map=args.map, corpus=args.corpus,
                       implications=args.implications, vocab=args.vocab, outfit_vocab=args.outfit_vocab).items()},
                   outfit_pack=fingerprint(args.outfit_pack), outfit_pack_inputs=outfit_pack['build']['inputs'],
                   join_check=checked, pools=engine.pool_info(), counts={'states': len(states), 'by_set': len(by_set)},
                   params=dict(MIN_SUP={p: MIN_SUP[p] for p in POOLS}, CHAR_GATE=0.5, CP_GATE=0.6, GATE='inclusion',
                               GARMENT_SHARE=0.15, SET_SHARE=0.10, MIN_LIFT=2.0, LIFT_CAP=30,
                               GARMENT_MAX=6, SET_MAX=4, EXACT=True), calibration=checks),
        types=TYPES, states=states, by_set=by_set)


def validate_pack(pack, vocabulary, outfit_pack=None, outfit_vocab=None):
    def require(ok, message):
        if not ok:
            raise ValueError(message)
    require(pack.get('schema') == 'naia.outfit_states.v1' and pack.get('types') == TYPES, 'state schema/types')
    expected = {n: r for n, r in vocabulary['tags'].items() if r['family'] == 'outfit_state'}
    require(set(pack['states']) == set(expected), 'state coverage')
    def associations(rows, limit, threshold):
        require(isinstance(rows, list) and len(rows) <= limit, 'association count')
        seen = set()
        for row in rows:
            require(isinstance(row, list) and len(row) == 3, 'association format')
            tag, share, lift = row
            require(isinstance(tag, str) and tag not in seen and threshold <= share <= 1 and
                    2 <= lift < float('inf'), 'association value')
            seen.add(tag)
    for name, rec in pack['states'].items():
        require(all(rec[k] == expected[name][k] for k in ('kind', 'type', 'garment')), 'state metadata')
        require(set(rec['pools']) == set(POOLS), 'state pools')
        for pool, row in rec['pools'].items():
            per = row['support_by_rating']
            require(set(per) == set('gsqe') and all(type(v) is int and v >= 0 for v in per.values()), 'state support')
            for key in ('top_character', 'top_copyright'):
                value = row[key]
                require(len(value) == 2 and 0 <= value[0] <= 1 and isinstance(value[1], str), 'state concentration')
            status = ('few' if sum(per.values()) < MIN_SUP[pool] else 'character_bound' if row['top_character'][0] > 0.5
                      else 'copyright_bound' if row['top_copyright'][0] > 0.6 else 'ok')
            require(row['status'] == status, 'state status')
            require(status == 'ok' or not row['garments'], 'bound garments')
            associations(row['garments'], 6, 0.15)
            if outfit_vocab is not None:
                require(all(outfit_vocab['tags'].get(t, {}).get('class') == 'garment' for t, _, _ in row['garments']), 'garment class')
    if outfit_pack is not None:
        require(pack['build']['outfit_pack_inputs'] == outfit_pack['build']['inputs'], 'outfit inputs changed')
        sets = {r['id']: r for r in outfit_pack['sets']}
        for set_id, layers in pack['by_set'].items():
            require(set_id in sets and bool(layers), 'unknown/empty set')
            rec = sets[set_id]
            require(set(layers) <= set(rec['layers']), 'set layers')
            for sides in layers.values():
                require(bool(sides) and set(sides) <= {'event', 'state'}, 'set kinds')
                for kind, rows in sides.items():
                    require(bool(rows), 'empty associations')
                    associations(rows, 4, 0.10)
                    require(all(t in pack['states'] and pack['states'][t]['kind'] == kind and
                                pack['states'][t]['pools'][rec['pool']]['status'] == 'ok' for t, _, _ in rows), 'set state status')
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    add_inputs(ap)
    ap.add_argument('--outfit-pack', type=Path, default=ROOT / 'data/outfit_presets.json')
    ap.add_argument('--out', type=Path, default=ROOT / 'data/outfit_states.json')
    ap.add_argument('--verify-repeat', action='store_true')
    args = ap.parse_args(argv)
    vocabulary = load_vocab(args.vocab)
    outfit_pack = json.loads(args.outfit_pack.read_text(encoding='utf-8'))
    engine, checked = initialize(args)
    try:
        pack = build_pack(args, engine, checked, vocabulary, outfit_pack)
        validate_pack(pack, vocabulary, outfit_pack, engine.VOCAB)
        if args.verify_repeat:
            repeated = build_pack(args, engine, checked, vocabulary, outfit_pack)
            repeated['build']['built_at'] = pack['build']['built_at']
            if json_bytes(pack) != json_bytes(repeated):
                raise ValueError('repeat build is not byte-identical')
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(json_bytes(pack))
    finally:
        engine.ix.close()


if __name__ == '__main__':
    main()
