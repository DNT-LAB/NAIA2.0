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
ENGINE_CONSTANTS = ["POOLS","LAYERS","MIN_SUP","FLOOR","MIN_SHARE","EARLY_SHARE","MIN_LIFT","LIFT_CAP","MAX_SIZE","KEEP","BEAM","SCAN","CANDIDATE_K","FILL_SHARE","BASE_LIFT","CHAR_GATE","CP_GATE","SIDE_SHARE","BASE_SLOTS","XDRESS"]

class PresetEngine:
    """One independent search context per family; corpus arrays may be shared.

    namespace is used only by the legacy outfit facade, so patch.multiple on
    its module continues to affect both search and final recounting.
    """
    def __init__(self, namespace=None, pools=None):
        object.__setattr__(self, '_namespace', namespace)
        for name in ENGINE_CONSTANTS:
            if namespace is None or name not in namespace:
                value = globals()[name]
                setattr(self, name, value.copy() if isinstance(value, (dict, list, set)) else value)
        self.par = defaultdict(set)
        self._anc = {}
        self.keep_seed = False
        self.floor_basis = 'gsq'
        self.fill_enabled = True
        self.kind_fn = None
        self.side = {}
        if pools is not None:
            self.POOLS = pools

    def __getattribute__(self, name):
        if not name.startswith('__') and name != '_namespace':
            namespace = object.__getattribute__(self, '_namespace')
            if namespace is not None and name in namespace:
                value = namespace[name]
                if getattr(value, '_engine_wrapper', False) is not True:
                    return value
        return object.__getattribute__(self, name)

    def __setattr__(self, name, value):
        namespace = object.__getattribute__(self, '_namespace')
        if namespace is None:
            object.__setattr__(self, name, value)
        else:
            namespace[name] = value

    def anc(self, t):
        if t not in self._anc:
            seen, stack = set(), [t]
            while stack:
                for p in self.par.get(stack.pop(), ()):
                    if p not in seen:
                        seen.add(p)
                        stack.append(p)
            self._anc[t] = seen
        return self._anc[t]


    def kind(self, t):
        return self.kind_fn(t) if self.kind_fn is not None else self.KIND.get(t.split(' ')[-1], t.split(' ')[-1])


    def nm(self, t):
        return '-' if t < 0 else self.NAMES.get(int(t), str(t))


    def top_share(self, rids, arr, exact=False):
        if not rids.size:
            return 0.0, -1
        take = rids if exact or rids.size <= self.SCAN else np.random.default_rng(3).choice(rids, self.SCAN, replace=False)
        a = arr[take]
        n = a.size
        a = a[a >= 0]
        if not a.size:
            return 0.0, -1
        u, c = np.unique(a, return_counts=True)
        k = c.argmax()
        return float(c[k] / n), int(u[k])


    def gate_ok(self, rids):
        return self.top_share(rids, self.prim)[0] <= self.CHAR_GATE and self.top_share(rids, self.primcp)[0] <= self.CP_GATE


    def layer_setup(self, pool, layer):
        lut = np.zeros(256, bool); lut[[self.pid[f'{r}_{p}'] for r in layer for p in self.POOLS[pool]]] = True
        N = int(self.NLIVE[lut].sum()); full = np.zeros(self.ix.n_tags, np.int64); full[self.vid] = self.M[:, lut].sum(1)
        floor_scale = N / max(1, int(self.NLIVE[[self.pid[f'{r}_{p}'] for r in self.floor_basis for p in self.POOLS[pool]]].sum()))   # v3 하한은 gsq 기준
        return dict(lut=lut, N=N, full=full, pbase=full / max(N, 1), floor=max(30, int(self.FLOOR[pool] * floor_scale)), pool=pool, layer=layer)

    def count(self, take):
        st = self.ix.offsets[take].astype(np.int64); en = self.ix.offsets[take + 1].astype(np.int64); ln = en - st
        idx = np.repeat(st - np.concatenate(([0], np.cumsum(ln)[:-1])), ln) + np.arange(int(ln.sum()))
        b = self.ix.body[idx]; b = b[self.vocab[b]]
        return np.bincount(b, minlength=self.ix.n_tags)

    def try_add(self, S, name, blocked):
        if name in blocked or any(o.endswith(' ' + name) for o in S):
            return None
        a = self.anc(name)
        # 같은 옷의 세부형(끝 낱말 같음)만 바꾼다. 부분품(side-tie bikini bottom → bikini)은 전체를 지우지 않고 곁에 둔다
        # (같은 칸이면 상위 태그를 접는다: underwear → panties · hat → nurse cap · school uniform → serafuku)
        repl = [o for o in S if (o in a or name.endswith(' ' + o))
                and (self.kind(o) == self.kind(name) or self.SLOTS.get(o, 'OUTFIT') == self.SLOTS.get(name, 'OUTFIT'))]
        S2 = [o for o in S if o not in repl] + [name]
        if any(self.kind(o) == self.kind(name) for o in S2[:-1]):
            return None
        used = Counter(self.SLOTS.get(o, 'OUTFIT') for o in S2)
        if any(used[s] > self.CAP[s] for s in used):
            return None
        return S2

    def expand(self, st, state, K, fill_slots=None):
        S, rids, sc, blocked = state
        take = rids if rids.size <= self.SCAN else np.random.default_rng(1).choice(rids, self.SCAN, replace=False)
        take = np.sort(take)
        share = self.count(take) / take.size
        with np.errstate(divide='ignore', invalid='ignore'):
            lift = np.where(st['pbase'] > 0, share / st['pbase'], 0)
        if fill_slots is None:
            ms = self.EARLY_SHARE if len(S) <= 2 else self.MIN_SHARE
            ok = (share >= ms) & (lift >= self.LIFT_FLOOR) & (st['full'] >= st['floor'])
            score = np.where(ok, share * np.log(np.minimum(np.maximum(lift, 1.0), self.LIFT_CAP)), 0)
        else:
            ok = (share >= self.FILL_SHARE) & (lift >= 1.0) & (st['full'] >= st['floor'])
            score = np.where(ok, share, 0)
        if st.get('no_outfit'):
            score = np.where(self.OUTFIT_MASK, 0, score)
        out = []
        for t in np.argsort(-score)[:300]:
            if score[t] <= 0 or len(out) >= K:
                break
            name = self.ix.by_id[int(t)]
            if fill_slots is not None and self.SLOTS.get(name, 'OUTFIT') not in fill_slots:
                continue
            S2 = self.try_add(S, name, blocked)
            if S2 is None or (self.keep_seed and st['seed'] not in S2):
                continue
            new = _intersect_sorted(rids, self.ix.posting(int(t)))
            if new.size < st['floor_sup'] or not self.gate_ok(new):
                continue
            out.append((S2, new, sc + float(score[t]), blocked | self.anc(name) | {name}))
        return out

    def seed_rids(self, st, seed):
        sid = self.ix.resolve(seed)
        if sid is None:
            return None
        r = self.ix.posting(sid); r = r[r < self.NP]; r = r[st['lut'][self.ix.part_arr[r]]]
        return r[self.live[r] & ~self.DROP[r]]

    def assemble(self, st, seed, beam=BEAM, k_out=3):
        st['seed'] = seed
        rids = self.seed_rids(st, seed)
        if rids is None or rids.size < self.MIN_SUP[st['pool']]:
            return None, 'few'
        if self.top_share(rids, self.prim)[0] > self.CHAR_GATE:
            return None, 'character_bound'
        if self.top_share(rids, self.primcp)[0] > self.CP_GATE:
            return None, 'copyright_bound'
        st['floor_sup'] = max(self.MIN_SUP[st['pool']], int(rids.size * self.KEEP))
        states = [([seed], rids, 0.0, self.anc(seed) | {seed})]; finals = []
        for _ in range(self.MAX_SIZE - 1):
            nxt = {}
            for s in states:
                ex = self.expand(st, s, beam)
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
        return [self.fill(st, c) if self.fill_enabled else (c[0], [], c[2]) for c in chosen], 'ok'

    def fill(self, st, state):
        S, rids, sc, blocked = state; added = []
        for need in (('TOP', 'BODY', 'OUTFIT'), ('BOTTOM', 'BODY'), ('FEET',)):
            if len(S) >= self.MAX_SIZE + 1 or any(self.SLOTS.get(o, 'OUTFIT') in need for o in S):
                continue
            ex = self.expand(st, (S, rids, sc, blocked), 1, fill_slots=set(need) - {'OUTFIT'})
            if ex:
                S, rids, sc, blocked = ex[0]; added.append(S[-1])
        return S, [t for t in added if t in S], sc

    def exact(self, pool, tags):
        r = None
        for t in tags:
            p = self.ix.posting(self.ix.resolve(t)); p = p[p < self.NP]
            r = p if r is None else _intersect_sorted(r, p)
        plut = np.zeros(256, bool); plut[[self.pid[f'{x}_{p}'] for x in 'gsqe' for p in self.POOLS[pool]]] = True
        r = r[plut[self.ix.part_arr[r]]]
        r = r[self.live[r] & ~self.DROP[r]]
        part = self.ix.part_arr[r]
        per = {x: int(np.isin(part, [self.pid[f'{x}_{p}'] for p in self.POOLS[pool]]).sum()) for x in 'gsqe'}
        return r, per



    def join_check(self, db):
        """Compare map tag names with the source general-tag blob, not local ids."""
        from core.event_map.policy import normalize
        names = {i: normalize(n) for i, n in db.execute('SELECT id,name FROM tags')}
        population = np.flatnonzero(self.live)
        if population.size < 200:
            raise ValueError('join check requires 200 live records')
        covers = []
        for rid in np.random.default_rng(1).choice(population, 200, replace=False):
            row = db.execute('SELECT general FROM records WHERE id=?', (int(rid),)).fetchone()
            expected = {self.ix.by_id[int(t)] for t in self.ix.body[self.ix.offsets[rid]:self.ix.offsets[rid + 1]]}
            actual = {names.get(int(t), '') for t in np.frombuffer(row[0], '<u4')} if row and row[0] else set()
            covers.append(len(expected & actual) / max(1, len(expected)))
        result = {'sampled': 200, 'mean_cover': float(np.mean(covers))}
        log('join_check ' + json.dumps(result, sort_keys=True))
        if result['mean_cover'] < 0.99:
            raise ValueError('map/corpus join coverage below 0.99')
        return result


    def initialize(self, args):
        self.VOCAB = json.loads(args.vocab.read_text(encoding='utf-8'))
        if self.VOCAB['schema'] != 'naia.outfit_vocab.v1':
            raise ValueError('unsupported vocabulary schema')
        log('class_counts ' + json.dumps(check_counts(self.VOCAB['tags']), sort_keys=True))
        self.CAP, self.KIND = self.VOCAB['slots'], self.VOCAB['kind_alias']
        order = self.VOCAB.get('slot_order', ['HEAD', 'NECK', 'OUTFIT', 'BODY', 'TOP', 'UNDER',
                                         'WAIST', 'BOTTOM', 'ARMS', 'LEGS', 'FEET'])
        self.ORDER = {s: i for i, s in enumerate(order)}
        self.SLOTS = {n: row['slot'] for n, row in self.VOCAB['tags'].items() if row['class'] == 'garment'}
        self.ix = EventMapIndex(args.map)
        self.pid = {n: i for i, n in enumerate(self.ix.partitions)}
        self.NP = len(self.ix.part_arr)
        self.live = self.ix.offsets[1:self.NP + 1] > self.ix.offsets[:self.NP]
        db = sqlite3.connect(Path(args.corpus).resolve().as_uri() + '?mode=ro', uri=True)
        try:
            checked = self.join_check(db)
            self.NAMES = dict(db.execute('SELECT id,name FROM tags'))
            self.prim, self.primcp = np.full(self.NP, -2, np.int32), np.full(self.NP, -2, np.int32)
            glut = np.zeros(256, bool)
            glut[[self.pid[f'{r}_{p}'] for r in 'gsqe' for pp in self.POOLS.values() for p in pp]] = True
            rr = np.flatnonzero(glut[self.ix.part_arr] & self.live)
            for k in range(0, rr.size, 50000):
                lo, hi = int(rr[k]), int(rr[min(k + 50000, rr.size) - 1])
                for i, c, y in db.execute(
                        'SELECT id,character,copyright FROM records WHERE id BETWEEN ? AND ?', (lo, hi)):
                    if i < self.NP:
                        self.prim[i] = int(np.frombuffer(c, '<u4')[0]) if c else -1
                        self.primcp[i] = int(np.frombuffer(y, '<u4')[0]) if y else -1
            for tid, name in self.NAMES.items():
                if name == 'original':
                    self.primcp[self.primcp == tid] = -1
            if np.any(self.prim[rr] == -2) or np.any(self.primcp[rr] == -2):
                raise ValueError('missing corpus records in selected pools')
        finally:
            db.close()
        self.par.clear()
        self._anc.clear()
        im = pd.read_parquet(args.implications)
        # 맵 이름은 이모티콘의 밑줄을 남긴다(`^_^` · `>_<` 등 - core/event_map/index.py resolve 주석). 맵에 그 이름 그대로
        # 있으면 바꾸지 않는다 - 전부 공백으로 바꾸면 `^_^ -> closed eyes` 같은 함의가 끊긴다(Codex 리뷰 11-17).
        canon = lambda n: n if n in self.ix.by_name else n.replace('_', ' ')
        for a, c in im.loc[im.status == 'active', ['antecedent_name', 'consequent_name']].itertuples(index=False):
            self.par[canon(a)].add(canon(c))
        self.vocab = np.zeros(self.ix.n_tags, bool)
        self.MODMASK = np.zeros(self.ix.n_tags, bool)
        for i, n in self.ix.by_id.items():
            self.vocab[i] = n in self.SLOTS
            self.MODMASK[i] = self.VOCAB['tags'].get(n, {}).get('class') == 'modifier'
        self.vid = np.flatnonzero(self.vocab)
        excl = np.zeros(self.NP, bool)
        for tag in self.XDRESS:
            tid = self.ix.resolve(tag)
            if tid is not None:
                p = self.ix.posting(tid)
                excl[p[p < self.NP]] = True
        mlut = np.zeros(256, bool)
        mlut[[self.pid[f'{r}_{p}'] for r in 'gsqe' for p in self.POOLS['male']]] = True
        self.DROP = excl & mlut[self.ix.part_arr]
        eligible = self.live & ~self.DROP
        self.NLIVE = np.bincount(self.ix.part_arr[eligible], minlength=256)
        self.M = np.zeros((self.vid.size, 256), np.int64)
        for k, tid in enumerate(self.vid):
            p = self.ix.posting(int(tid))
            p = p[p < self.NP]
            p = p[eligible[p]]
            self.M[k] = np.bincount(self.ix.part_arr[p], minlength=256)
        self.LIFT_FLOOR = np.full(self.ix.n_tags, self.MIN_LIFT)
        self.OUTFIT_MASK = np.zeros(self.ix.n_tags, bool)
        for tid in self.vid:
            slot = self.SLOTS[self.ix.by_id[int(tid)]]
            if slot in self.BASE_SLOTS:
                self.LIFT_FLOOR[tid] = self.BASE_LIFT
            self.OUTFIT_MASK[tid] = slot == 'OUTFIT'
        self.STS = {(p, layer): self.layer_setup(p, layer) for p in self.POOLS for layer in self.LAYERS}
        log('male crossdressing posts dropped: %d' % np.count_nonzero(self.DROP & self.live))
        return checked


    def side_info(self, rids, tags):
        if not rids.size:
            return []
        take = rids if rids.size <= 50000 else np.sort(np.random.default_rng(5).choice(rids, 50000, replace=False))
        starts = self.ix.offsets[take].astype(np.int64)
        lengths = self.ix.offsets[take + 1].astype(np.int64) - starts
        indices = np.repeat(starts - np.concatenate(([0], np.cumsum(lengths)[:-1])), lengths) + np.arange(int(lengths.sum()))
        body = self.ix.body[indices]
        mc = np.bincount(body[self.MODMASK[body]], minlength=self.ix.n_tags) / take.size
        implied = set().union(*(self.anc(t) for t in tags))
        top = [t for t in np.argsort(-mc)[:12] if mc[t] >= self.SIDE_SHARE and self.ix.by_id[int(t)] not in implied][:4]
        return [[self.ix.by_id[int(t)], float(mc[t])] for t in top]



    def configure(self, *, slots, caps, order=None, pools=None, min_sup=None,
                  floor=None, floor_basis='gsq', kind_fn=None, keep_seed=True,
                  lift_floor_fn=None, score_mask=None, fill=False, max_size=6, side=None):
        self.SLOTS = dict(slots)
        self.CAP = {s: caps.get(s, caps.get('*', 2)) for s in sorted(set(slots.values()))}
        self.ORDER = order or {s: i for i, s in enumerate(sorted(self.CAP))}
        if pools is not None:
            self.POOLS = pools
        if min_sup is not None:
            self.MIN_SUP = min_sup
        if floor is not None:
            self.FLOOR = floor
        self.floor_basis, self.kind_fn, self.keep_seed = floor_basis, kind_fn, keep_seed
        self.fill_enabled, self.MAX_SIZE, self.side = fill, max_size, side or {}
        self.vocab = self.mask(slots)
        self.vid = np.flatnonzero(self.vocab)
        self.M = self.partition_counts(self.vid)
        self.LIFT_FLOOR = np.full(self.ix.n_tags, self.MIN_LIFT)
        if lift_floor_fn is not None:
            for tid in self.vid:
                self.LIFT_FLOOR[tid] = lift_floor_fn(self.ix.by_id[int(tid)])
        self.OUTFIT_MASK = np.zeros(self.ix.n_tags, bool) if score_mask is None else score_mask
        self.STS = {(p, l): self.layer_setup(p, l) for p in self.POOLS for l in self.LAYERS}
        self.side_base = {label: self.base_rates(mask) for label, mask in self.side.items()}
        return self

    def fork(self):
        other = PresetEngine()
        # Only immutable map/corpus data are shared. Each search owns its config.
        for name in ('ix', 'pid', 'NP', 'live', 'DROP', 'NLIVE', 'prim', 'primcp',
                     'NAMES', 'par', 'VOCAB'):
            setattr(other, name, getattr(self, name))
        return other

    def mask(self, names):
        result = np.zeros(self.ix.n_tags, bool)
        for name in names:
            tid = self.ix.resolve(name)
            if tid is not None:
                result[tid] = True
        return result

    def partition_counts(self, ids):
        matrix = np.zeros((len(ids), 256), np.int64)
        eligible = self.live & ~self.DROP
        for k, tid in enumerate(ids):
            p = self.ix.posting(int(tid))
            p = p[p < self.NP]
            p = p[eligible[p]]
            matrix[k] = np.bincount(self.ix.part_arr[p], minlength=256)
        return matrix

    def base_rates(self, mask):
        ids = np.flatnonzero(mask)
        matrix = self.partition_counts(ids)
        result = {}
        for key, st in self.STS.items():
            base = np.zeros(self.ix.n_tags)
            base[ids] = matrix[:, st['lut']].sum(1) / max(1, st['N'])
            result[key] = base
        return result

    def associations(self, rids, tags, mask, base, *, share_min=0.15, limit=4, sample=50000, exclude_implied=True):
        if not rids.size:
            return []
        take = rids if sample is None or rids.size <= sample else np.sort(
            np.random.default_rng(5).choice(rids, sample, replace=False))
        counts = np.zeros(self.ix.n_tags, np.int64)
        for begin in range(0, take.size, 50000):
            chunk = take[begin:begin + 50000]
            starts = self.ix.offsets[chunk].astype(np.int64)
            lengths = self.ix.offsets[chunk + 1].astype(np.int64) - starts
            indices = np.repeat(starts - np.concatenate(([0], np.cumsum(lengths)[:-1])), lengths) + np.arange(int(lengths.sum()))
            body = self.ix.body[indices]
            counts += np.bincount(body[mask[body]], minlength=self.ix.n_tags)
        share = counts / take.size
        lift = np.divide(share, base, out=np.zeros_like(share), where=base > 0)
        ok = mask & (share >= share_min) & (lift >= 2.0)
        implied = set(tags).union(*(self.anc(t) for t in tags)) if exclude_implied else set()
        for name in implied:
            tid = self.ix.resolve(name)
            if tid is not None:
                ok[tid] = False
        score = np.where(ok, share * np.log(np.maximum(1.0, np.minimum(lift, 30))), 0)
        top = [t for t in np.argsort(-score, kind='stable') if score[t] > 0][:limit]
        return [[self.ix.by_id[int(t)], round(float(share[t]), 4), round(float(lift[t]), 4)] for t in top]

    def family_side(self, pool, layer, rids, tags):
        return {label: self.associations(rids, tags, mask, self.side_base[label][pool, layer])
                for label, mask in self.side.items()}

    def pool_info(self):
        pools = {pool: {'partitions': [f'{r}_{p}' for r in 'gsqe' for p in parts],
                       'live_by_rating': {r: int(sum(self.NLIVE[self.pid[f'{r}_{p}']] for p in parts))
                                          for r in 'gsqe'}} for pool, parts in self.POOLS.items()}
        if 'male' in pools:
            pools['male']['dropped_crossdressing'] = int(np.count_nonzero(self.DROP & self.live))
        return pools


def git_head():
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                       stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return 'unknown'
