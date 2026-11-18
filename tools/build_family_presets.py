"""Bake event (including link), expression and scene preset packs."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path

from presets_engine import (PresetEngine, ROOT, DATA, MAP, CORPUS, POOLS, LAYERS,
                            PARAMS, fingerprint, json_bytes, git_head, log)

LINK_POOLS = {'girl_boy': ['1girl_1boy'], 'girl_girl': ['2girls'], 'boy_boy': ['2boys']}
ALL_POOLS = dict(POOLS, **LINK_POOLS)
MIN_SUP = dict(female=80, male=25, girl_boy=60, girl_girl=60, boy_boy=30)
FLOOR = dict(female=2000, male=250, girl_boy=1000, girl_girl=1000, boy_boy=300)
SIDE = {'event': {'props': 'object', 'place': 'scene', 'face': 'expression'},
        'link': {'pose': 'event', 'face': 'expression', 'place': 'scene', 'props': 'object'},
        'expression': {'pose': 'event'}, 'scene': {'props': 'object'}}
GENRES = {'hetero', 'yuri', 'yaoi', 'bara'}


def load_vocab(path):
    vocabulary = json.loads(path.read_text(encoding='utf-8'))
    if vocabulary['schema'] != 'naia.preset_vocab.v1':
        raise ValueError('preset vocabulary schema')
    return vocabulary


def initialize(args):
    engine = PresetEngine(pools=ALL_POOLS)
    engine.MIN_SUP, engine.FLOOR = MIN_SUP, FLOOR
    try:
        checked = engine.initialize(argparse.Namespace(map=args.map, corpus=args.corpus,
                                    vocab=args.outfit_vocab, implications=args.implications))
    except BaseException:
        if hasattr(engine, 'ix'):
            engine.ix.close()
        raise
    return engine, checked


def install(source, family, vocabulary, subcategories):
    engine = source.fork()
    tags = vocabulary['tags']
    slots = {n: row['slot'] for n, row in tags.items() if row['family'] == family}
    # 곁 정보도 어휘표 규칙 0 을 따른다: guarded lane · 색 전용 태그(red flower 등)는 싣지 않는다(11-17 감사에서 444건).
    usable = {n for t, n in engine.ix.by_id.items()
              if engine.ix.lane.get(t) != 'guarded' and not engine.ix.color[t]}
    masks = {label: engine.mask(n for n in engine.ix.by_id.values()
                               if n in usable and (subcategories.get(n, [None])[0] == 'object' if target == 'object'
                                                   else tags.get(n, {}).get('family') == target))
             for label, target in SIDE[family].items()}
    return engine.configure(slots=slots, caps={'*': 2}, pools=LINK_POOLS if family == 'link' else POOLS,
                            min_sup=MIN_SUP, floor=FLOOR, kind_fn=lambda t: t, keep_seed=True,
                            max_size=5 if family == 'expression' else 6, side=masks)


def run_seed(engine, family, pool, seed):
    records, statuses, dropped = {}, {}, 0
    for layer in LAYERS:
        st = dict(engine.STS[pool, layer], no_outfit=False)
        result, status = engine.assemble(st, seed, k_out=3 if layer == 'gsqe' else 1)
        statuses[layer] = status
        for rank, (tags, _, score) in enumerate(result or [], 1):
            tags = sorted(tags, key=lambda t: (engine.ORDER[engine.SLOTS[t]], t))
            rids, per = engine.exact(pool, tags)
            rl = rids[st['lut'][engine.ix.part_arr[rids]]]
            cs, cid = engine.top_share(rl, engine.prim, exact=True)
            ys, yid = engine.top_share(rl, engine.primcp, exact=True)
            if cs > engine.CHAR_GATE or ys > engine.CP_GATE or rl.size < st['floor_sup']:
                dropped += 1
                continue
            rec = records.setdefault(tuple(tags), dict(family=family, pool=pool, seed=seed, tags=tags,
                layers=[], rank={}, support_by_rating=per, support_by_layer={},
                top_character={}, top_copyright={}, side={}, score={}))
            if layer in rec['layers']:
                continue
            rec['layers'].append(layer)
            rec['rank'][layer] = rank
            rec['support_by_layer'][layer] = int(rl.size)
            rec['top_character'][layer] = [cs, engine.nm(cid)]
            rec['top_copyright'][layer] = [ys, engine.nm(yid)]
            rec['side'][layer] = engine.family_side(pool, layer, rl, tags)
            rec['score'][layer] = float(score)
    output = sorted(records.values(), key=lambda r: tuple(r['tags']))
    for number, rec in enumerate(output, 1):
        rec['id'] = f'{family}-{pool}-{seed}-{number}'
    return output, statuses, dropped


def calibration(engines):
    results, checks = [], {}
    def first(family, pool, seed, layer):
        rows, _, _ = run_seed(engines[family], family, pool, seed)
        results.extend(rows)
        rows = [r for r in rows if layer in r['layers']]
        if not rows:
            raise ValueError('calibration produced no set: ' + seed + '/' + layer)
        return min(rows, key=lambda r: r['rank'][layer])
    def side(row, layer, label):
        return {t[0] for t in row['side'][layer].get(label, [])}
    if 'event' in engines:
        r = first('event', 'female', 'reading', 'gsqe')
        # book 은 holding book 의 함의 조상이라 곁 정보에서 빠지는 게 맞다 - 함의되지 않은 소품으로 본다.
        checks['event_reading'] = {'reading', 'holding book'} <= set(r['tags']) and bool(
            {'open book', 'bookshelf'} & side(r, 'gsqe', 'props'))
        checks['event_seed_kept'] = 'sitting' in first('event', 'female', 'sitting', 'gsqe')['tags']
        checks['event_holding_cup'] = 'sitting' in first('event', 'female', 'holding cup', 'gsqe')['tags']
        checks['link_holding_hands'] = 'interlocked fingers' in first('link', 'girl_girl', 'holding hands', 'g')['tags']
        r = first('link', 'girl_boy', 'lap pillow', 'gsqe')
        checks['link_lap_pillow'] = bool({'sleeping', 'lying'} & (set(r['tags']) | side(r, 'gsqe', 'pose')))
        checks['link_no_genre'] = not (GENRES & set(engines['link'].SLOTS))
    if 'expression' in engines:
        checks['expr_seed_kept'] = 'smile' in first('expression', 'female', 'smile', 'gsqe')['tags']
        checks['expr_angry'] = {'angry', 'v-shaped eyebrows'} <= set(first('expression', 'female', 'angry', 'gsqe')['tags'])
    if 'scene' in engines:
        checks['scene_classroom'] = bool({'desk', 'school desk'} & side(first('scene', 'female', 'classroom', 'gsqe'), 'gsqe', 'props'))
        checks['scene_kitchen'] = 'stove' in side(first('scene', 'female', 'kitchen', 'gsqe'), 'gsqe', 'props')
    checks['g_support'] = all(r['support_by_rating']['g'] >= MIN_SUP[r['pool']] for r in results if 'g' in r['layers'])
    if not all(checks.values()):
        raise ValueError('calibration failed: ' + json.dumps(checks, sort_keys=True))
    return checks


def validate_pack(pack, vocabulary, ancestors=lambda _: set(), subcategories=None):
    def require(ok, message):
        if not ok:
            raise ValueError(message)
    family = pack.get('schema', '').removeprefix('naia.').removesuffix('_presets.v1')
    require(family in {'event', 'expression', 'scene'}, 'schema')
    require({'note', 'build', 'slots', 'tag_slot', 'seed_status', 'sets'} <= pack.keys(), 'pack keys')
    require({'built_at', 'builder', 'git_head', 'params', 'inputs', 'join_check', 'pools', 'counts', 'calibration'} <= pack['build'].keys(), 'build keys')
    ids, records = set(), set()
    for rec in pack['sets']:
        require({'id', 'family', 'pool', 'seed', 'tags', 'layers', 'rank', 'support_by_rating',
                 'support_by_layer', 'top_character', 'top_copyright', 'side', 'score'} <= rec.keys(), 'record keys')
        fam, pool, tags, layers = rec['family'], rec['pool'], rec['tags'], rec['layers']
        require(fam == family or (family == 'event' and fam == 'link'), 'family')
        require(pool in (LINK_POOLS if fam == 'link' else POOLS), 'family/pool')
        require(tags and len(tags) == len(set(tags)) and len(tags) <= (5 if fam == 'expression' else 6), 'tags/size')
        require(rec['seed'] in tags, 'seed lost')
        require(layers and layers == [l for l in LAYERS if l in layers], 'layers')
        require(rec['id'] not in ids, 'duplicate id')
        ids.add(rec['id'])
        key = (fam, pool, rec['seed'], tuple(sorted(tags)))
        require(key not in records, 'unmerged record')
        records.add(key)
        used = Counter()
        for tag in tags:
            entry = vocabulary['tags'].get(tag, {})
            require(entry.get('family') == fam, 'tag family')
            require(tag in pack['tag_slot'] and pack['tag_slot'][tag] == entry.get('slot'), 'slot mismatch')
            used[entry['slot']] += 1
        require(all(n <= pack['slots'].get(s, 0) <= 2 for s, n in used.items()), 'slot cap')
        require(fam != 'link' or not GENRES.intersection(tags), 'genre')
        per = rec['support_by_rating']
        require(set(per) == set('gsqe') and all(type(v) is int and v >= 0 for v in per.values()), 'rating support')
        for field in ('rank', 'support_by_layer', 'top_character', 'top_copyright', 'side', 'score'):
            require(set(rec[field]) == set(layers), 'layer keys: ' + field)
        implied = set(tags).union(*(ancestors(t) for t in tags))
        for layer in layers:
            require(rec['support_by_layer'][layer] == sum(per[r] for r in layer), 'layer support')
            require(rec['support_by_layer'][layer] >= MIN_SUP[pool], 'minimum support')
            require(type(rec['rank'][layer]) is int and 1 <= rec['rank'][layer] <= (3 if layer == 'gsqe' else 1), 'rank')
            require(math.isfinite(rec['score'][layer]), 'score')
            for field, gate in [('top_character', 0.5), ('top_copyright', 0.6)]:
                val = rec[field][layer]
                require(isinstance(val, list) and len(val) == 2 and isinstance(val[1], str) and 0 <= val[0] <= gate, field)
            require(set(rec['side'][layer]) == set(SIDE[fam]), 'side labels')
            for label, rows in rec['side'][layer].items():
                require(isinstance(rows, list) and len(rows) <= 4, 'side count')
                seen = set()
                for row in rows:
                    require(isinstance(row, list) and len(row) == 3, 'side format')
                    tag, share, lift = row
                    require(isinstance(tag, str) and tag not in seen and tag not in implied, 'side tag')
                    seen.add(tag)
                    require(0.15 <= share <= 1 and math.isfinite(lift) and lift >= 2.0, 'side thresholds')
                    target = SIDE[fam][label]
                    if target != 'object':
                        require(vocabulary['tags'].get(tag, {}).get('family') == target, 'side family')
                    elif subcategories is not None:
                        require(subcategories.get(tag, [None])[0] == 'object', 'side object')
    return True


def build_pack(args, family, engines, checked, vocabulary):
    only = {s.strip() for s in args.seeds.split(',') if s.strip()}
    jobs, records, statuses = [], [], {}
    counts = dict(available_seeds={}, seeds={}, sets={}, seed_status={}, dropped_final_gate=0)
    for fam, engine in engines.items():
        for pool in engine.POOLS:
            available = sorted(n for n in engine.SLOTS if engine.ix.resolve(n) is not None and
                               engine.STS[pool, 'gsqe']['full'][engine.ix.resolve(n)] >= FLOOR[pool])
            seeds = [n for n in available if not only or n in only]
            counts['available_seeds'][pool], counts['seeds'][pool] = len(available), len(seeds)
            counts['seed_status'][pool] = dict.fromkeys(['ok', 'few', 'character_bound', 'copyright_bound'], 0)
            statuses[pool] = {}
            jobs.extend((fam, pool, seed) for seed in seeds)
    jobs.sort(key=lambda j: (j[2], j[1], j[0]))
    def work(job):
        fam, pool, seed = job
        return run_seed(engines[fam], fam, pool, seed)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for job, (rows, state, dropped) in zip(jobs, executor.map(work, jobs)):
            fam, pool, seed = job
            records.extend(rows)
            for status in state.values():
                counts['seed_status'][pool][status] += 1
            failed = {l: s for l, s in state.items() if s != 'ok'}
            if failed:
                statuses[pool][seed] = failed
            counts['dropped_final_gate'] += dropped
    records.sort(key=lambda r: (r['pool'], r['family'], r['seed'], tuple(r['tags'])))
    pools, slots, tag_slot = {}, {}, {}
    for engine in engines.values():
        pools.update(engine.pool_info())
        slots.update(engine.CAP)
        tag_slot.update(engine.SLOTS)
    counts['sets'] = {p: sum(r['pool'] == p for r in records) for p in pools}
    checks = calibration(engines)
    checks['g_support'] = checks['g_support'] and all(r['support_by_rating']['g'] >= MIN_SUP[r['pool']] for r in records if 'g' in r['layers'])
    if family == 'event':
        checks['link_no_genre'] = checks['link_no_genre'] and all(not GENRES.intersection(r['tags']) for r in records if r['family'] == 'link')
    if not all(checks.values()):
        raise ValueError('final calibration failed')
    params = {k: PARAMS[k] for k in ('EARLY_SHARE', 'MIN_SHARE', 'MIN_LIFT', 'LIFT_CAP', 'KEEP', 'BEAM', 'K',
              'VARIANTS', 'VARIANT_DIFFERENCE', 'SCAN', 'CHAR_GATE', 'CP_GATE', 'SCAN_SEED', 'GATE_SEED', 'SIDE_SEED')}
    params.update(MIN_SUP={p: MIN_SUP[p] for p in pools}, FLOOR={p: FLOOR[p] for p in pools},
                  FLOOR_BASIS='gsq', MAX_SIZE=5 if family == 'expression' else 6, KEEP_SEED=True,
                  SIDE_SHARE=0.15, SIDE_LIFT=2.0, SIDE_MAX=4, SIDE_SCAN=50000, seeds=sorted(only))
    return dict(schema=f'naia.{family}_presets.v1', note='tools/build_family_presets.py 가 굽는다. 손으로 고치지 말 것',
        build=dict(built_at=datetime.now(timezone.utc).isoformat(), builder='build_family_presets.py', git_head=git_head(),
                   params=params, inputs={k: fingerprint(p) for k, p in dict(map=args.map, corpus=args.corpus,
                   implications=args.implications, vocab=args.vocab, outfit_vocab=args.outfit_vocab,
                   subcategories=args.subcategories).items()}, join_check=checked, pools=pools, counts=counts, calibration=checks),
        slots=slots, tag_slot={t: tag_slot[t] for r in records for t in r['tags']}, seed_status=statuses, sets=records)


def add_inputs(ap):
    ap.add_argument('--map', default=MAP)
    ap.add_argument('--corpus', default=CORPUS)
    ap.add_argument('--implications', type=Path, default=ROOT / 'data/danbooru_tag_snapshot/tag_implications.parquet')
    ap.add_argument('--outfit-vocab', type=Path, default=DATA / 'outfit_vocab.json')
    ap.add_argument('--vocab', type=Path, default=DATA / 'preset_vocab.json')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    add_inputs(ap)
    ap.add_argument('--family', nargs='+', choices=['event', 'expression', 'scene'], default=['event', 'expression', 'scene'])
    ap.add_argument('--subcategories', type=Path, default=ROOT / 'data/event_map_subcategories.json')
    ap.add_argument('--out', type=Path, help='Single-family output path')
    ap.add_argument('--seeds', default='')
    ap.add_argument('--workers', type=int, default=max(1, min(8, (os.cpu_count() or 1) // 2)))
    ap.add_argument('--verify-repeat', action='store_true')
    args = ap.parse_args(argv)
    if args.workers < 1 or (args.out and len(args.family) != 1) or (args.verify_repeat and not args.seeds):
        ap.error('positive workers required; --out needs one family; --verify-repeat needs --seeds')
    vocabulary = load_vocab(args.vocab)
    subcategories = json.loads(args.subcategories.read_text(encoding='utf-8'))['tags']
    source, checked = initialize(args)
    try:
        for family in dict.fromkeys(args.family):
            engines = {f: install(source, f, vocabulary, subcategories) for f in ([family, 'link'] if family == 'event' else [family])}
            pack = build_pack(args, family, engines, checked, vocabulary)
            validate_pack(pack, vocabulary, source.anc, subcategories)
            if args.verify_repeat:
                repeated = build_pack(args, family, engines, checked, vocabulary)
                repeated['build']['built_at'] = pack['build']['built_at']
                if json_bytes(repeated) != json_bytes(pack):
                    raise ValueError('repeat build is not byte-identical')
            out = args.out or ROOT / f'data/{family}_presets.json'
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(json_bytes(pack))
            log(f'{family}: {len(pack["sets"])} sets')
    finally:
        source.ix.close()


if __name__ == '__main__':
    main()
