"""Bake outfit sets from a vocabulary; no tree or classifier dependency.

The search functions are ported from prototype v5. Threads share the one pair
of primary-character/copyright arrays; no cache or temporary files are needed.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import csv
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
from build_outfit_vocab import MAP, CORPUS, DATA, check_counts, fingerprint, json_bytes, log
from core.event_map.index import EventMapIndex, _intersect_sorted

POOLS = {'female': ['1girl_solo', '1girl'], 'male': ['1boy_solo', '1boy']}
LAYERS = ['g', 'gs', 'gsq', 'gsqe']
MIN_SUP = {'female': 80, 'male': 25}
FLOOR = {'female': 2000, 'male': 250}
MIN_SHARE, EARLY_SHARE, MIN_LIFT, LIFT_CAP, MAX_SIZE, KEEP = 0.15, 0.08, 1.6, 30.0, 8, 0.02
BEAM, SCAN, CANDIDATE_K = 4, 200000, 4
FILL_SHARE, BASE_LIFT = 0.35, 1.1
CHAR_GATE, CP_GATE, SIDE_SHARE = 0.5, 0.6, 0.25
BASE_SLOTS = {'TOP', 'BOTTOM', 'BODY', 'LEGS', 'FEET'}
XDRESS = ['crossdressing', 'otoko no ko', 'trap']
PARAMS = dict(MIN_SUP=MIN_SUP, FLOOR=FLOOR, EARLY_SHARE=EARLY_SHARE,
              MIN_SHARE=MIN_SHARE, MIN_LIFT=MIN_LIFT, BASE_LIFT=BASE_LIFT,
              BASE_SLOTS=sorted(BASE_SLOTS), LIFT_CAP=LIFT_CAP, MAX_SIZE=MAX_SIZE,
              KEEP=KEEP, BEAM=BEAM, K=CANDIDATE_K, VARIANTS={'gsqe': 3, 'other': 1},
              VARIANT_DIFFERENCE=2, SCAN=SCAN, CHAR_GATE=CHAR_GATE, CP_GATE=CP_GATE,
              FILL_SHARE=FILL_SHARE, FILL_LIFT=1.0, SIDE_SHARE=SIDE_SHARE,
              SIDE_MAX=4, SIDE_SCAN=50000, SCAN_SEED=1, GATE_SEED=3, SIDE_SEED=5)
_anc = {}
par = defaultdict(set)


def anc(t):
    if t not in _anc:
        seen, stack = set(), [t]
        while stack:
            for p in par.get(stack.pop(), ()):
                if p not in seen:
                    seen.add(p)
                    stack.append(p)
        _anc[t] = seen
    return _anc[t]


def kind(t):
    return KIND.get(t.split(' ')[-1], t.split(' ')[-1])


def nm(t):
    return '-' if t < 0 else NAMES.get(int(t), str(t))


def top_share(rids, arr, exact=False):
    if not rids.size:
        return 0.0, -1
    take = rids if exact or rids.size <= SCAN else np.random.default_rng(3).choice(rids, SCAN, replace=False)
    a = arr[take]
    n = a.size
    a = a[a >= 0]
    if not a.size:
        return 0.0, -1
    u, c = np.unique(a, return_counts=True)
    k = c.argmax()
    return float(c[k] / n), int(u[k])


def gate_ok(rids):
    return top_share(rids, prim)[0] <= CHAR_GATE and top_share(rids, primcp)[0] <= CP_GATE


def layer_setup(pool, layer):
    lut = np.zeros(256, bool); lut[[pid[f'{r}_{p}'] for r in layer for p in POOLS[pool]]] = True
    N = int(NLIVE[lut].sum()); full = np.zeros(ix.n_tags, np.int64); full[vid] = M[:, lut].sum(1)
    floor_scale = N / max(1, int(NLIVE[[pid[f'{r}_{p}'] for r in 'gsq' for p in POOLS[pool]]].sum()))   # v3 하한은 gsq 기준
    return dict(lut=lut, N=N, full=full, pbase=full / max(N, 1), floor=max(30, int(FLOOR[pool] * floor_scale)), pool=pool, layer=layer)

def count(take):
    st = ix.offsets[take].astype(np.int64); en = ix.offsets[take + 1].astype(np.int64); ln = en - st
    idx = np.repeat(st - np.concatenate(([0], np.cumsum(ln)[:-1])), ln) + np.arange(int(ln.sum()))
    b = ix.body[idx]; b = b[vocab[b]]
    return np.bincount(b, minlength=ix.n_tags)

def try_add(S, name, blocked):
    if name in blocked or any(o.endswith(' ' + name) for o in S):
        return None
    a = anc(name)
    # 같은 옷의 세부형(끝 낱말 같음)만 바꾼다. 부분품(side-tie bikini bottom → bikini)은 전체를 지우지 않고 곁에 둔다
    # (같은 칸이면 상위 태그를 접는다: underwear → panties · hat → nurse cap · school uniform → serafuku)
    repl = [o for o in S if (o in a or name.endswith(' ' + o))
            and (kind(o) == kind(name) or SLOTS.get(o, 'OUTFIT') == SLOTS.get(name, 'OUTFIT'))]
    S2 = [o for o in S if o not in repl] + [name]
    if any(kind(o) == kind(name) for o in S2[:-1]):
        return None
    used = Counter(SLOTS.get(o, 'OUTFIT') for o in S2)
    if any(used[s] > CAP[s] for s in used):
        return None
    return S2

def expand(st, state, K, fill_slots=None):
    S, rids, sc, blocked = state
    take = rids if rids.size <= SCAN else np.random.default_rng(1).choice(rids, SCAN, replace=False)
    take = np.sort(take)
    share = count(take) / take.size
    with np.errstate(divide='ignore', invalid='ignore'):
        lift = np.where(st['pbase'] > 0, share / st['pbase'], 0)
    if fill_slots is None:
        ms = EARLY_SHARE if len(S) <= 2 else MIN_SHARE
        ok = (share >= ms) & (lift >= LIFT_FLOOR) & (st['full'] >= st['floor'])
        score = np.where(ok, share * np.log(np.minimum(np.maximum(lift, 1.0), LIFT_CAP)), 0)
    else:
        ok = (share >= FILL_SHARE) & (lift >= 1.0) & (st['full'] >= st['floor'])
        score = np.where(ok, share, 0)
    if st.get('no_outfit'):
        score = np.where(OUTFIT_MASK, 0, score)
    out = []
    for t in np.argsort(-score)[:300]:
        if score[t] <= 0 or len(out) >= K:
            break
        name = ix.by_id[int(t)]
        if fill_slots is not None and SLOTS.get(name, 'OUTFIT') not in fill_slots:
            continue
        S2 = try_add(S, name, blocked)
        if S2 is None:
            continue
        new = _intersect_sorted(rids, ix.posting(int(t)))
        if new.size < st['floor_sup'] or not gate_ok(new):
            continue
        out.append((S2, new, sc + float(score[t]), blocked | anc(name) | {name}))
    return out

def seed_rids(st, seed):
    sid = ix.resolve(seed)
    if sid is None:
        return None
    r = ix.posting(sid); r = r[r < NP]; r = r[st['lut'][ix.part_arr[r]]]
    return r[live[r] & ~DROP[r]]

def assemble(st, seed, beam=BEAM, k_out=3):
    rids = seed_rids(st, seed)
    if rids is None or rids.size < MIN_SUP[st['pool']]:
        return None, 'few'
    if top_share(rids, prim)[0] > CHAR_GATE:
        return None, 'character_bound'
    if top_share(rids, primcp)[0] > CP_GATE:
        return None, 'copyright_bound'
    st['floor_sup'] = max(MIN_SUP[st['pool']], int(rids.size * KEEP))
    states = [([seed], rids, 0.0, anc(seed) | {seed})]; finals = []
    for _ in range(MAX_SIZE - 1):
        nxt = {}
        for s in states:
            ex = expand(st, s, beam)
            if not ex:
                finals.append(s)
            for e in ex:
                key = frozenset(e[0])
                if key not in nxt or nxt[key][2] < e[2]:
                    nxt[key] = e
        states = sorted(nxt.values(), key=lambda e: -e[2])[:beam]
        if not states:
            break
    finals += states
    finals.sort(key=lambda e: -e[2])
    chosen = []
    for f in finals:
        if all(len(set(f[0]) ^ set(c[0])) >= 2 for c in chosen):
            chosen.append(f)
        if len(chosen) >= k_out:
            break
    return [fill(st, c) for c in chosen], 'ok'

def fill(st, state):
    S, rids, sc, blocked = state; added = []
    for need in (('TOP', 'BODY', 'OUTFIT'), ('BOTTOM', 'BODY'), ('FEET',)):
        if len(S) >= MAX_SIZE + 1 or any(SLOTS.get(o, 'OUTFIT') in need for o in S):
            continue
        ex = expand(st, (S, rids, sc, blocked), 1, fill_slots=set(need) - {'OUTFIT'})
        if ex:
            S, rids, sc, blocked = ex[0]; added.append(S[-1])
    return S, [t for t in added if t in S], sc

def exact(pool, tags):
    r = None
    for t in tags:
        p = ix.posting(ix.resolve(t)); p = p[p < NP]
        r = p if r is None else _intersect_sorted(r, p)
    plut = np.zeros(256, bool); plut[[pid[f'{x}_{p}'] for x in 'gsqe' for p in POOLS[pool]]] = True
    r = r[plut[ix.part_arr[r]]]
    r = r[live[r] & ~DROP[r]]
    part = ix.part_arr[r]
    per = {x: int(np.isin(part, [pid[f'{x}_{p}'] for p in POOLS[pool]]).sum()) for x in 'gsqe'}
    return r, per



def join_check(db):
    """Compare map tag names with the source general-tag blob, not local ids."""
    from core.event_map.policy import normalize
    names = {i: normalize(n) for i, n in db.execute('SELECT id,name FROM tags')}
    population = np.flatnonzero(live)
    if population.size < 200:
        raise ValueError('join check requires 200 live records')
    covers = []
    for rid in np.random.default_rng(1).choice(population, 200, replace=False):
        row = db.execute('SELECT general FROM records WHERE id=?', (int(rid),)).fetchone()
        expected = {ix.by_id[int(t)] for t in ix.body[ix.offsets[rid]:ix.offsets[rid + 1]]}
        actual = {names.get(int(t), '') for t in np.frombuffer(row[0], '<u4')} if row and row[0] else set()
        covers.append(len(expected & actual) / max(1, len(expected)))
    result = {'sampled': 200, 'mean_cover': float(np.mean(covers))}
    log('join_check ' + json.dumps(result, sort_keys=True))
    if result['mean_cover'] < 0.99:
        raise ValueError('map/corpus join coverage below 0.99')
    return result


def initialize(args):
    global ix, pid, NP, live, DROP, NLIVE, M, vid, vocab, SLOTS, CAP, KIND, ORDER
    global prim, primcp, NAMES, LIFT_FLOOR, OUTFIT_MASK, MODMASK, VOCAB, STS
    VOCAB = json.loads(args.vocab.read_text(encoding='utf-8'))
    if VOCAB['schema'] != 'naia.outfit_vocab.v1':
        raise ValueError('unsupported vocabulary schema')
    log('class_counts ' + json.dumps(check_counts(VOCAB['tags']), sort_keys=True))
    CAP, KIND = VOCAB['slots'], VOCAB['kind_alias']
    order = VOCAB.get('slot_order', ['HEAD', 'NECK', 'OUTFIT', 'BODY', 'TOP', 'UNDER',
                                     'WAIST', 'BOTTOM', 'ARMS', 'LEGS', 'FEET'])
    ORDER = {s: i for i, s in enumerate(order)}
    SLOTS = {n: row['slot'] for n, row in VOCAB['tags'].items() if row['class'] == 'garment'}
    ix = EventMapIndex(args.map)
    pid = {n: i for i, n in enumerate(ix.partitions)}
    NP = len(ix.part_arr)
    live = ix.offsets[1:NP + 1] > ix.offsets[:NP]
    db = sqlite3.connect(Path(args.corpus).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        checked = join_check(db)
        NAMES = dict(db.execute('SELECT id,name FROM tags'))
        prim, primcp = np.full(NP, -2, np.int32), np.full(NP, -2, np.int32)
        glut = np.zeros(256, bool)
        glut[[pid[f'{r}_{p}'] for r in 'gsqe' for pp in POOLS.values() for p in pp]] = True
        rr = np.flatnonzero(glut[ix.part_arr] & live)
        for k in range(0, rr.size, 50000):
            lo, hi = int(rr[k]), int(rr[min(k + 50000, rr.size) - 1])
            for i, c, y in db.execute(
                    'SELECT id,character,copyright FROM records WHERE id BETWEEN ? AND ?', (lo, hi)):
                if i < NP:
                    prim[i] = int(np.frombuffer(c, '<u4')[0]) if c else -1
                    primcp[i] = int(np.frombuffer(y, '<u4')[0]) if y else -1
        for tid, name in NAMES.items():
            if name == 'original':
                primcp[primcp == tid] = -1
        if np.any(prim[rr] == -2) or np.any(primcp[rr] == -2):
            raise ValueError('missing corpus records in selected pools')
    finally:
        db.close()
    par.clear()
    _anc.clear()
    im = pd.read_parquet(args.implications)
    for a, c in im.loc[im.status == 'active', ['antecedent_name', 'consequent_name']].itertuples(index=False):
        par[a.replace('_', ' ')].add(c.replace('_', ' '))
    vocab = np.zeros(ix.n_tags, bool)
    MODMASK = np.zeros(ix.n_tags, bool)
    for i, n in ix.by_id.items():
        vocab[i] = n in SLOTS
        MODMASK[i] = VOCAB['tags'].get(n, {}).get('class') == 'modifier'
    vid = np.flatnonzero(vocab)
    excl = np.zeros(NP, bool)
    for tag in XDRESS:
        tid = ix.resolve(tag)
        if tid is not None:
            p = ix.posting(tid)
            excl[p[p < NP]] = True
    mlut = np.zeros(256, bool)
    mlut[[pid[f'{r}_{p}'] for r in 'gsqe' for p in POOLS['male']]] = True
    DROP = excl & mlut[ix.part_arr]
    eligible = live & ~DROP
    NLIVE = np.bincount(ix.part_arr[eligible], minlength=256)
    M = np.zeros((vid.size, 256), np.int64)
    for k, tid in enumerate(vid):
        p = ix.posting(int(tid))
        p = p[p < NP]
        p = p[eligible[p]]
        M[k] = np.bincount(ix.part_arr[p], minlength=256)
    LIFT_FLOOR = np.full(ix.n_tags, MIN_LIFT)
    OUTFIT_MASK = np.zeros(ix.n_tags, bool)
    for tid in vid:
        slot = SLOTS[ix.by_id[int(tid)]]
        if slot in BASE_SLOTS:
            LIFT_FLOOR[tid] = BASE_LIFT
        OUTFIT_MASK[tid] = slot == 'OUTFIT'
    STS = {(p, layer): layer_setup(p, layer) for p in POOLS for layer in LAYERS}
    log('male crossdressing posts dropped: %d' % np.count_nonzero(DROP & live))
    return checked


def side_info(rids, tags):
    if not rids.size:
        return []
    take = rids if rids.size <= 50000 else np.sort(np.random.default_rng(5).choice(rids, 50000, replace=False))
    starts = ix.offsets[take].astype(np.int64)
    lengths = ix.offsets[take + 1].astype(np.int64) - starts
    indices = np.repeat(starts - np.concatenate(([0], np.cumsum(lengths)[:-1])), lengths) + np.arange(int(lengths.sum()))
    body = ix.body[indices]
    mc = np.bincount(body[MODMASK[body]], minlength=ix.n_tags) / take.size
    implied = set().union(*(anc(t) for t in tags))
    top = [t for t in np.argsort(-mc)[:12] if mc[t] >= SIDE_SHARE and ix.by_id[int(t)] not in implied][:4]
    return [[ix.by_id[int(t)], float(mc[t])] for t in top]


def run_seed(job):
    pool, start, seed = job
    records, statuses, dropped = {}, {}, 0
    for layer in LAYERS:
        st = dict(STS[pool, layer], no_outfit=start == 'free')
        result, status = assemble(st, seed, k_out=3 if layer == 'gsqe' else 1)
        statuses[layer] = status
        for rank, (tags, added, score) in enumerate(result or [], 1):
            tags = sorted(tags, key=lambda t: (ORDER[SLOTS[t]], t))
            r, per = exact(pool, tags)
            rl = r[st['lut'][ix.part_arr[r]]]
            cs, cid = top_share(rl, prim, exact=True)
            ys, yid = top_share(rl, primcp, exact=True)
            if cs > CHAR_GATE or ys > CP_GATE or rl.size < st['floor_sup']:
                dropped += 1
                continue
            key = tuple(tags)
            rec = records.setdefault(key, dict(pool=pool, start=start, seed=seed, tags=tags,
                fill=[], layers=[], rank={}, support_by_rating=per, support_by_layer={},
                top_character={}, top_copyright={}, side={}, score={}))
            # Filling may converge two beam variants. Keep the higher ranked one.
            if layer in rec['layers']:
                continue
            rec['fill'] = sorted(set(rec['fill']) | set(added), key=lambda t: (ORDER[SLOTS[t]], t))
            rec['layers'].append(layer)
            rec['rank'][layer] = rank
            rec['support_by_layer'][layer] = int(rl.size)
            rec['top_character'][layer] = [cs, nm(cid)]
            rec['top_copyright'][layer] = [ys, nm(yid)]
            rec['side'][layer] = side_info(rl, tags)
            rec['score'][layer] = float(score)
    output = sorted(records.values(), key=lambda r: tuple(r['tags']))
    for number, rec in enumerate(output, 1):
        rec['id'] = '%s-%s-%s-%d' % (pool[0], start, seed, number)
    return output, statuses, dropped


def calibration():
    jobs = [('male', 'free', 'hakama'), ('male', 'free', 'armor'),
            ('female', 'free', 'bikini'), ('female', 'free', 'silver dress'),
            ('female', 'free', 'beret'), ('female', 'free', 'thighhighs'),
            ('female', 'named', 'tracen school uniform'), ('female', 'named', 'maid')]
    results = {job: run_seed(job) for job in jobs}

    def first(pool, start, seed, layer):
        rows = [r for r in results[pool, start, seed][0] if layer in r['layers']]
        if not rows:
            raise ValueError('calibration produced no set: ' + seed + '/' + layer)
        return min(rows, key=lambda r: r['rank'][layer])

    checks = {}
    hakama = first('male', 'free', 'hakama', 'gsqe')
    checks['hakama'] = {'kimono', 'hakama'} <= set(hakama['tags']) and hakama['top_character']['gsqe'][0] <= CHAR_GATE
    armor = first('male', 'free', 'armor', 'gsqe')
    checks['armor'] = bool({'breastplate', 'pauldrons'} & set(armor['tags'])) and len(armor['tags']) >= 3
    checks['bikini_gs'] = 'bikini' in first('female', 'free', 'bikini', 'gs')['tags']
    checks['silver_dress'] = results['female', 'free', 'silver dress'][1]['gsqe'] == 'character_bound'
    checks['beret_g'] = not ({'school uniform', 'serafuku', 'sailor collar', 'neckerchief'} &
                             set(first('female', 'free', 'beret', 'g')['tags']))
    checks['thighhighs'] = (first('female', 'free', 'thighhighs', 'g')['tags'] !=
                           first('female', 'free', 'thighhighs', 'gsqe')['tags'])
    checks['tracen_school_uniform'] = results['female', 'named', 'tracen school uniform'][1]['gsqe'] == 'copyright_bound'
    checks['maid'] = {'maid', 'maid headdress'} <= set(first('female', 'named', 'maid', 'gsqe')['tags'])
    checks['g_support'] = all(r['support_by_rating']['g'] >= MIN_SUP[r['pool']]
                             for rows, _, _ in results.values() for r in rows if 'g' in r['layers'])
    log('calibration ' + json.dumps(checks, sort_keys=True))
    if not all(checks.values()):
        raise ValueError('calibration checks failed')
    return checks


def candidate_csv():
    rows = []
    candidates = sorted(n for n, entry in VOCAB['tags'].items()
                        if entry.get('named_candidate') or entry.get('why') == 'role' or n == 'wedding dress')
    for tag in candidates:
        # 어느 풀에서도 빈도 하한(gsqe)에 못 미치는 후보는 표에서 뺀다(시제품 v4 와 같음). 역할 태그는 늘 남긴다.
        tid = ix.resolve(tag)
        if VOCAB['tags'][tag].get('why') != 'role' and (tid is None or not any(
                STS[p, 'gsqe']['full'][tid] >= STS[p, 'gsqe']['floor'] for p in POOLS)):
            continue
        row = {'tag': tag, 'slot': SLOTS.get(tag, 'OUTFIT')}
        for pool in POOLS:
            suffix = pool[0]
            st = dict(STS[pool, 'gsqe'], no_outfit=False)
            r = seed_rids(st, tag)
            if r is None:
                r = np.empty(0, np.int64)
            cs, cid = top_share(r, prim, exact=True)
            ys, yid = top_share(r, primcp, exact=True)
            result = None
            tid = ix.resolve(tag)
            if tid is not None and st['full'][tid] >= st['floor']:
                result, _ = assemble(st, tag, beam=1, k_out=1)
            tags = []
            if result:
                proposed, _, _ = result[0]
                exact_r, _ = exact(pool, proposed)
                if (exact_r.size >= st['floor_sup'] and top_share(exact_r, prim, True)[0] <= CHAR_GATE
                        and top_share(exact_r, primcp, True)[0] <= CP_GATE):
                    tags = sorted(proposed, key=lambda t: (ORDER[SLOTS[t]], t))
            row.update({f'posts_{suffix}': int(r.size), f'char_{suffix}': cs,
                        f'charname_{suffix}': nm(cid), f'cp_{suffix}': ys, f'cpname_{suffix}': nm(yid),
                        f'set_{suffix}': ', '.join(tags), f'setlen_{suffix}': len(tags)})
        big = 'f' if row['posts_f'] >= row['posts_m'] else 'm'
        row['auto'] = ('작품교복' if row['cp_' + big] >= CP_GATE else
                       '캐릭터의상' if row['char_' + big] >= CHAR_GATE else
                       '원피스류' if row['slot'] == 'BODY' else
                       '단품' if row['slot'] != 'OUTFIT' else 'review')
        row['posts_total'] = row['posts_f'] + row['posts_m']
        rows.append(row)
    rows.sort(key=lambda r: (r['auto'], -r['posts_total'], r['tag']))
    fields = ['tag', 'slot'] + [f'{field}_{s}' for s in 'fm'
             for field in ('posts', 'char', 'charname', 'cp', 'cpname', 'set', 'setlen')] + ['auto', 'posts_total']
    buf = io.StringIO(newline='')
    writer = csv.DictWriter(buf, fieldnames=fields, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    log('named_candidates %d' % len(rows))
    return buf.getvalue().encode('utf-8')


def validate_pack(pack, vocabulary, ancestors):
    def require(ok, message):
        if not ok:
            raise ValueError(message)

    require(pack.get('schema') == 'naia.outfit_presets.v1', 'schema')
    require({'schema', 'note', 'build', 'slots', 'tag_slot', 'seed_status', 'sets'} <= pack.keys(), 'pack keys')
    require({'built_at', 'builder', 'git_head', 'params', 'inputs', 'join_check', 'pools', 'counts'} <= pack['build'].keys(), 'build keys')
    check_counts(vocabulary['tags'])
    seen_ids, seen_records = set(), set()
    for rec in pack['sets']:
        require({'id', 'pool', 'start', 'seed', 'rank', 'layers', 'tags', 'fill', 'support_by_rating',
                 'support_by_layer', 'top_character', 'top_copyright', 'side', 'score'} <= rec.keys(), 'record keys')
        tags, layers = rec['tags'], rec['layers']
        require(rec['pool'] in POOLS and rec['start'] in ('free', 'named'), 'pool/start')
        require(tags and len(tags) == len(set(tags)), 'empty or duplicate tags')
        require(layers and layers == [l for l in LAYERS if l in layers], 'layers')
        require(rec['id'] not in seen_ids, 'duplicate id')
        seen_ids.add(rec['id'])
        key = (rec['pool'], rec['start'], rec['seed'], tuple(sorted(tags)))
        require(key not in seen_records, 'unmerged record')
        seen_records.add(key)
        used = Counter()
        for tag in tags:
            require(tag in pack['tag_slot'], 'missing slot')
            entry = vocabulary['tags'][tag]
            require(entry['class'] == 'garment', 'non garment')
            require(pack['tag_slot'][tag] == entry['slot'], 'slot mismatch')
            used[entry['slot']] += 1
        require(all(n <= pack['slots'][s] for s, n in used.items()), 'slot cap')
        require(rec['start'] != 'free' or not used['OUTFIT'], 'free OUTFIT')
        require(set(rec['fill']) <= set(tags), 'fill not in tags')
        for a in tags:
            for b in tags:
                require(a == b or pack['tag_slot'][a] != pack['tag_slot'][b] or b not in ancestors(a),
                        'same slot implication')
        per = rec['support_by_rating']
        require(set(per) == set('gsqe') and all(isinstance(v, int) and v >= 0 for v in per.values()), 'rating support')
        for field in ('rank', 'support_by_layer', 'top_character', 'top_copyright', 'side', 'score'):
            require(set(rec[field]) == set(layers), 'layer keys: ' + field)
        for layer in layers:
            require(rec['support_by_layer'][layer] == sum(per[r] for r in layer), 'layer support')
            require(rec['support_by_layer'][layer] >= MIN_SUP[rec['pool']], 'minimum support')
            require(isinstance(rec['rank'][layer], int) and rec['rank'][layer] >= 1, 'rank')
            require(0 <= rec['top_character'][layer][0] <= CHAR_GATE, 'character gate')
            require(0 <= rec['top_copyright'][layer][0] <= CP_GATE, 'copyright gate')
            require(len(rec['side'][layer]) <= 4, 'side count')
            for tag, share in rec['side'][layer]:
                require(vocabulary['tags'][tag]['class'] == 'modifier' and SIDE_SHARE <= share <= 1, 'side modifier')
                require(not any(tag in ancestors(t) for t in tags), 'implied side')
    return True


def build_pack(args, checked):
    curation = json.loads(args.curation.read_text(encoding='utf-8')) if args.curation.exists() else {}
    if not args.curation.exists():
        log('WARNING: no curation file; named sets will be empty')
    for tag, row in curation.items():
        if row.get('status') not in ('include', 'exclude', 'review'):
            raise ValueError('invalid curation status: ' + tag)
        if row['status'] == 'include' and tag not in SLOTS:
            raise ValueError('curated tag is not a garment in vocabulary: ' + tag)
    only = {s.strip() for s in args.seeds.split(',') if s.strip()}
    jobs, counts = [], {'free_seeds': {}, 'named_seeds': {}, 'sets': {}, 'seed_status': {},
                       'dropped_final_gate': 0, 'available_free_seeds': {}}
    for pool in POOLS:
        full = STS[pool, 'gsqe']['full']
        free = [n for n, s in SLOTS.items() if s != 'OUTFIT' and ix.resolve(n) is not None
                and full[ix.resolve(n)] >= FLOOR[pool]]
        counts['available_free_seeds'][pool] = len(free)
        free = sorted(n for n in free if not only or n in only)
        named = sorted(n for n, row in curation.items() if row['status'] == 'include' and (not only or n in only))
        counts['free_seeds'][pool], counts['named_seeds'][pool] = len(free), len(named)
        jobs.extend((pool, start, seed) for start, seeds in [('free', free), ('named', named)] for seed in seeds)
    jobs.sort(key=lambda j: (j[2], j[0], j[1]))
    records, statuses = [], {p: {} for p in POOLS}
    for pool in POOLS:
        counts['seed_status'][pool] = dict.fromkeys(['ok', 'few', 'character_bound', 'copyright_bound'], 0)
    # Thread workers share immutable primary arrays and index mmap; each job owns its layer state.
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for job, (rows, state, dropped) in zip(jobs, executor.map(run_seed, jobs)):
            pool, start, seed = job
            records.extend(rows)
            for status in state.values():
                counts['seed_status'][pool][status] += 1
            failed = {l: s for l, s in state.items() if s != 'ok'}
            if failed:
                statuses[pool].setdefault(seed, {}).update(failed)
            counts['dropped_final_gate'] += dropped
            log('seed %s/%s/%s sets=%d' % (pool, start, seed, len(rows)))
    records.sort(key=lambda r: (r['pool'], r['start'], r['seed'], tuple(r['tags'])))
    for pool in POOLS:
        counts['sets'][pool] = sum(r['pool'] == pool for r in records)
    pools = {}
    for pool in POOLS:
        pools[pool] = {'partitions': [f'{r}_{p}' for r in 'gsqe' for p in POOLS[pool]],
                       'live_by_rating': {r: int(sum(NLIVE[pid[f'{r}_{p}']] for p in POOLS[pool])) for r in 'gsqe'}}
    pools['male']['dropped_crossdressing'] = int(np.count_nonzero(DROP & live))
    try:
        git_head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, stderr=subprocess.DEVNULL,
                                           text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        git_head = 'unknown'
    inputs = {k: fingerprint(p) for k, p in {'map': args.map, 'corpus': args.corpus,
              'implications': args.implications, 'vocab': args.vocab}.items()}
    inputs['curation'] = fingerprint(args.curation) if args.curation.exists() else None
    return {'schema': 'naia.outfit_presets.v1',
            'note': '의상 세트 프리셋 - tools/build_outfit_presets.py 가 굽는다. 손으로 고치지 말 것',
            'build': {'built_at': datetime.now(timezone.utc).isoformat(), 'builder': 'build_outfit_presets.py',
                      'git_head': git_head, 'params': dict(PARAMS, seeds=sorted(only)),
                      'inputs': inputs, 'join_check': checked, 'pools': pools, 'counts': counts},
            'slots': CAP, 'tag_slot': {t: SLOTS[t] for r in records for t in r['tags']},
            'seed_status': statuses, 'sets': records}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--map', default=MAP)
    ap.add_argument('--corpus', default=CORPUS)
    ap.add_argument('--implications', type=Path, default=ROOT / 'data/danbooru_tag_snapshot/tag_implications.parquet')
    ap.add_argument('--vocab', type=Path, default=DATA / 'outfit_vocab.json')
    ap.add_argument('--curation', type=Path, default=DATA / 'named_outfit_curation.json')
    ap.add_argument('--out', type=Path, default=ROOT / 'data/outfit_presets.json')
    ap.add_argument('--candidates', type=Path, default=DATA / 'named_outfit_candidates.csv')
    ap.add_argument('--seeds', default='', help='Comma-separated subset; calibration always runs')
    ap.add_argument('--workers', type=int, default=max(1, min(8, (os.cpu_count() or 1) // 2)))
    ap.add_argument('--verify-repeat', action='store_true', help='Repeat a subset and compare bytes without built_at')
    args = ap.parse_args(argv)
    if args.workers < 1:
        ap.error('--workers must be positive')
    if args.verify_repeat and not args.seeds:
        ap.error('--verify-repeat requires --seeds')
    try:
        checked = initialize(args)
        checks = calibration()
        pack = build_pack(args, checked)
        pack['build']['calibration'] = checks
        validate_pack(pack, VOCAB, anc)
        if args.verify_repeat:
            repeated = build_pack(args, checked)
            repeated['build']['calibration'] = checks
            repeated['build']['built_at'] = pack['build']['built_at']
            if json_bytes(repeated) != json_bytes(pack):
                raise ValueError('repeat build is not byte-identical')
            log('repeat_bytes PASS')
        candidates = candidate_csv()
        payload = json_bytes(pack)
        args.candidates.parent.mkdir(parents=True, exist_ok=True)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.candidates.write_bytes(candidates)
        args.out.write_bytes(payload)
        log('counts ' + json.dumps(pack['build']['counts'], sort_keys=True))
        log('pack_bytes %d' % len(payload))
    finally:
        if 'ix' in globals():
            ix.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        log('ERROR: ' + str(exc))
        sys.exit(1)
