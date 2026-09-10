"""Offline general-tag prompt examples with joint evidence from raw post partitions.

No runtime, user-data, wildcard, ZIP or catalog writes. Use a NEW output directory.
Examples are observed tag SUBSETS, not full source rows or model-generated prose.
Counts use retained source ROWS, not unique post IDs. Partition lift ranks
context; exact global lift gates background candidates on the same retained
corpus. Source ratings describe provenance, not the generated image's rating.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import inspect
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from scipy import sparse

from core.tag_combo.noise import ARTIFACT_TAGS, is_color_tag
from tools.build_fast_search_event_catalog import is_population, normalize_atom
from tools.thumb_age_guard import danger_age_hits
from core.event_preset.fast_search_catalog import PERSON_IDS

GROUPS = frozenset({'Food_Object', 'Expression_Action', 'Clothing_Wear',
                    'Location_Background', 'Creatures', 'Composition_Meta', 'Culture_Misc'})
COMPOSITION = frozenset({'effects', 'image_composition', 'lighting', 'composition',
                         'surreal', 'pose', 'framing'})
CULTURE = frozenset({'jobs', 'holidays_and_celebrations', 'culture', 'history',
                     'occupation', 'music', 'sports', 'events'})
NOISE = ARTIFACT_TAGS | {'signature', 'watermark', 'artist name', 'character name',
                        'copyright name', 'commentary', 'translated', 'dated',
                        'speech bubble', 'english text', 'japanese text', 'logo',
                        'simple background', 'white background', 'looking at viewer'}
# Keep corpus admission separate from output vocabulary. Ordinary adult tags
# must not erase general-anchor source rows in Q/E; they still cannot be emitted.
ADULT_CONTENT_RE = re.compile(r'\b(?:sex|nude|naked|nipples?|penis|pussy|vaginal|cum|semen|'
                              r'masturbat\w*|fellan?ti\w*|cunnilingus|oral|anal|asshole)\b', re.I)
RISK_CONTENT_RE = re.compile(r'\b(?:rape|guro|ryona|scat|feces|incest|bestial\w*|molest\w*|'
                             r'necro\w*|amputee|mutilat\w*|torture|snuff)\b', re.I)
AGE_EXCEPTIONS = {'lolita fashion', 'gothic lolita', 'sweet lolita', 'babydoll'}
RATING_PROMPTS = {'g': 'rating:general', 's': 'rating:sensitive',
                  'q': 'rating:questionable', 'e': 'rating:explicit'}
INDEX_CONTRACT = 'general-context-rows-v3'


def row_blocked(tag, info):
    return (bool(danger_age_hits(tag)) and tag not in AGE_EXCEPTIONS
            or bool(RISK_CONTENT_RE.search(tag)) or info.get('group') == 'Danger')


def blocked(tag, info):
    """Anchor/companion exclusion, intentionally stricter than row admission."""
    return row_blocked(tag, info) or bool(ADULT_CONTENT_RE.search(tag)) or info.get('group') == 'NSFW'


def visual(tag, info):
    group, sub = info.get('group'), info.get('subgroup')
    return (group in GROUPS and tag not in NOISE and not blocked(tag, info)
            and not is_population(tag)
            and (group != 'Composition_Meta' or sub in COMPOSITION)
            and (group != 'Culture_Misc' or sub in CULTURE))


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def read_partition(path, vocabulary, keep, reject, *, return_row_ids=False):
    """One binary row per retained source record. Never aggregate independent tags.

    Arrow splits raw underscore-delimited atoms; integer lookup, filtering and
    sparse assembly keep the full raw corpus practical without sampling.
    """
    lookup = pa.array([tag.replace(' ', '_') for tag in vocabulary])
    matrices, post_ids, row_ids = [], [], []
    source_rows = rejected_rows = unknown_atoms = 0
    for batch in pq.ParquetFile(path).iter_batches(batch_size=32768, columns=['id', 'tag_string_general']):
        raw = pc.fill_null(batch.column('tag_string_general'), '')
        lists = pc.split_pattern(raw, pattern=' ')
        tokens = pc.list_flatten(lists)
        rows = np.asarray(pc.list_parent_indices(lists), dtype=np.int64)
        cols = np.asarray(pc.fill_null(pc.index_in(tokens, value_set=lookup), len(vocabulary)), dtype=np.int32)
        unknown = cols == len(vocabulary)
        unknown_atoms += int(unknown.sum())
        bad = np.bincount(rows[reject[cols]], minlength=batch.num_rows) > 0
        # A lexical risk marker outside the frequency/metadata dictionaries must
        # not bypass row rejection merely because integer lookup missed it.
        if unknown.any():
            missing = tokens.filter(pa.array(unknown)).to_pylist()
            rejected_unknown = np.array([row_blocked(normalize_atom(t), {}) for t in missing])
            bad[rows[unknown][rejected_unknown]] = True
        bad |= np.asarray(pc.equal(raw, ''))
        selected = keep[cols]
        matrix = sparse.csr_matrix((np.ones(int(selected.sum()), dtype=np.int32),
                                    (rows[selected], cols[selected])),
                                   shape=(batch.num_rows, len(vocabulary)))
        matrix.sum_duplicates()
        matrix.data[:] = 1
        matrices.append(matrix[~bad])
        post_ids.append(np.asarray(batch.column('id'))[~bad])
        row_ids.append(np.arange(source_rows, source_rows + batch.num_rows, dtype=np.int64)[~bad])
        source_rows += batch.num_rows
        rejected_rows += int(bad.sum())
    matrix = sparse.vstack(matrices, format='csr')
    ids = np.concatenate(post_ids)
    stats = {'source_rows': source_rows, 'retained_rows': len(ids),
             'rejected_rows': rejected_rows, 'unknown_atom_occurrences': unknown_atoms,
             'duplicate_id_extra_rows': len(ids) - len(np.unique(ids))}
    result = (matrix, ids, stats)
    return (*result, np.concatenate(row_ids)) if return_row_ids else result


def posting(csc, col):
    return csc.indices[csc.indptr[col]:csc.indptr[col + 1]]


def intersect_rows(a, b):
    """Sorted unique postings intersection without repeatedly sorting huge unions."""
    if len(a) > len(b):
        a, b = b, a
    if not len(a):
        return a
    positions = np.searchsorted(b, a)
    valid = positions < len(b)
    short, positions = a[valid], positions[valid]
    return short[b[positions] == short]


def make_example(matrix, csc, ids, anchor, vocabulary, metadata, background,
                 *, support=.20, joint_support=.05, min_joint=10, max_tags=5,
                 min_global_lift=3., global_stats=None, cooc_counts=None, source_row_ids=None,
                 min_companions=2, min_qe_skew=0., qe_background=None, rated_qe=False,
                 action_min_count=0):
    """Greedy contextual subset; every addition must keep joint support.

    Marginal lift nominates candidates only. A companion cannot be appended
    unless the intersection for the ENTIRE partial prompt passes the threshold.
    """
    rows = posting(csc, anchor)
    n = len(rows)
    cooc = (np.asarray(matrix[rows].sum(axis=0)).ravel() if cooc_counts is None else cooc_counts)
    if global_stats is None:
        # Small fixture/single-corpus callers; production always supplies the
        # aggregate of ALL admitted partitions including non-nominated ones.
        global_stats = {'rows': matrix.shape[0], 'anchor_count': n,
                        'background': background, 'cooc': cooc}
    floor = max(min_joint, math.ceil(n * support))
    joint_floor = max(min_joint, math.ceil(n * joint_support))
    candidates = []
    # 행동 갈래를 열면 비율 문턱 아래도 훑어야 한다. 끄면(0) 스캔 범위가 예전과 같다.
    scan_floor = min(floor, min_joint) if action_min_count else floor
    for col in np.flatnonzero(cooc >= scan_floor):
        tag = vocabulary[col]
        if col == anchor or not visual(tag, metadata.get(tag, {})) or is_color_tag(tag):
            continue
        # 의상·물건 앵커의 행동은 구조적으로 비율이 낮다(dress lift = dress 의 2.1%).
        # 증거의 양을 비율 대신 관측 건수로 재고, 그때만 비율 문턱을 면제한다.
        action = metadata.get(tag, {}).get('group') == 'Expression_Action'
        exempt = (action and action_min_count
                  and int(global_stats['cooc'][col]) >= action_min_count)
        if int(cooc[col]) < floor and not exempt:
            continue
        confidence = int(cooc[col]) / n
        lift = confidence / (int(background[col]) / matrix.shape[0])
        global_cooc = int(global_stats['cooc'][col])
        global_support = global_cooc / global_stats['anchor_count']
        global_background = int(global_stats['background'][col])
        global_lift = global_support / (global_background / global_stats['rows'])
        if global_lift < min_global_lift:
            continue
        entry = {'col': int(col), 'tag': tag, 'cooccurrence': int(cooc[col]),
                 'support': confidence, 'lift': lift,
                 'partition_background_count': int(background[col]),
                 'global_cooccurrence': global_cooc, 'global_support': global_support,
                 'global_background_count': global_background, 'global_lift': global_lift}
        if qe_background is not None and global_background:
            # 이 태그가 Q/E 쪽에 얼마나 치우쳐 있는가. 어휘 목록이 아니라 관측 분포다.
            entry['qe_share'] = int(qe_background[col]) / global_background
        if exempt:
            entry['support_exempt'] = 'action_min_count'
        candidates.append(entry)
    candidates.sort(key=lambda c: (-c['lift'], -c['cooccurrence'], c['tag']))
    anchor_group = metadata[vocabulary[anchor]]['group']
    # For a physical object, an action supplies the missing "what is happening".
    if anchor_group in {'Food_Object', 'Clothing_Wear', 'Creatures'}:
        candidates.sort(key=lambda c: metadata[c['tag']]['group'] != 'Expression_Action')
    # 비율 문턱을 면제받은 행동은 마지막에 얹는다. 먼저 넣으면 얇은 조합이 joint 를 좁혀
    # 뒤따르는 강한 동반을 떨어뜨린다(실측: shirt 가 collared shirt 495,973건을 잃었다).
    candidates.sort(key=lambda c: bool(c.get('support_exempt')))
    chosen, joint = [], rows
    group_counts = Counter({anchor_group: 1})
    for candidate in candidates:
        group = metadata[candidate['tag']]['group']
        if group_counts[group] >= 2:
            continue
        overlap = intersect_rows(joint, posting(csc, candidate['col']))
        # 행동 갈래는 조합 자체도 비율이 아니라 관측 행 수로 잰다. 앵커가 클수록 비율 문턱이
        # 절대 건수로는 터무니없이 커진다(hat 은 5% 가 16,717행인데 실제 조합은 7,572행이다).
        floor_here = (max(min_joint, min(joint_floor, action_min_count))
                      if candidate.get('support_exempt') else joint_floor)
        if len(overlap) < floor_here:
            continue
        # A much broader tag already present in >=98% of the current joint adds
        # little (holding sword -> holding weapon -> holding). This is a bounded
        # statistical redundancy rule, not a claim about ontology implications.
        specific_background = min(int(background[c]) for c in [anchor, *[c['col'] for c in chosen]])
        if len(overlap) >= .98 * len(joint) and background[candidate['col']] >= 1.5 * specific_background:
            continue
        chosen.append(candidate)
        joint = overlap
        group_counts[group] += 1
        if len(chosen) == max_tags - 1:
            break
    if len(chosen) < min_companions:
        return None
    # Q/E 분면에서 뽑은 줄은 그 등급을 스스로 설명해야 한다. 남은 동반이 전부 등급 중립이면
    # rating 토큰만 explicit 이 되어 무엇이 나올지 통제되지 않는다 - 그런 줄은 내지 않는다.
    if rated_qe and min_qe_skew > 0 and not any(c.get('qe_share', 0.) >= min_qe_skew for c in chosen):
        return None
    # Population is taken from an actual matching source row, then verified with
    # the same joint threshold. "other" is never guessed to mean "1girl".
    population = [int(c) for c in matrix[int(joint[0])].indices if is_population(vocabulary[c])]
    accepted_population = []
    # 동반을 절대 문턱으로 받았다면 인원도 같은 잣대로 재야 한다. 아니면 행동 갈래 예시가
    # 인원 없이 나온다(hat, hand on headwear 에 1girl, solo 가 빠졌다).
    population_floor = (max(min_joint, min(joint_floor, action_min_count))
                        if any(c.get('support_exempt') for c in chosen) else joint_floor)
    for col in population:
        overlap = intersect_rows(joint, posting(csc, col))
        if len(overlap) >= population_floor:
            accepted_population.append(col)
            joint = overlap
    tags = [vocabulary[c] for c in accepted_population] + [vocabulary[anchor]] + [c['tag'] for c in chosen]
    clean = lambda c: {k: round(v, 6) if isinstance(v, float) else v
                        for k, v in c.items() if k not in {'col', 'score'}}
    return {'tags': tags, 'prompt': ', '.join(tags), 'anchor_rows': n,
            'global_anchor_rows': global_stats['anchor_count'],
            'partition_retained_rows': matrix.shape[0], 'global_retained_rows': global_stats['rows'],
            'joint_count': len(joint), 'joint_support': round(len(joint) / n, 6),
            'population_tags': [vocabulary[c] for c in accepted_population],
            'companions': [clean(c) for c in chosen],
            'candidates': [clean(c) for c in candidates],
            'source_post_ids': [int(i) for i in ids[joint[:3]]],
            'source_row_indices': [int(i) for i in (source_row_ids if source_row_ids is not None
                                                   else np.arange(matrix.shape[0]))[joint[:3]]]}


def choose_partitions(rows, limit):
    """Largest support first, then other person categories before same-person ratings."""
    ordered = sorted(rows, key=lambda x: (-x[1], x[0]))
    chosen, persons = [], set()
    for distinct in (True, False):
        for row in ordered:
            if row in chosen or (distinct and row[0].split('_', 1)[1] in persons):
                continue
            chosen.append(row)
            persons.add(row[0].split('_', 1)[1])
            if len(chosen) == limit:
                return chosen
    return chosen


def build(args):
    out = args.output.resolve()
    if out.exists():
        raise ValueError('Output directory must be new; existing artifacts are never overwritten')
    source = args.partitions.resolve()
    paths = sorted(p for p in source.glob('*.parquet') if p.stem.split('_', 1)[0] in args.ratings)
    expected = {f'{r}_{p}' for r in args.ratings for p in PERSON_IDS}
    if {p.stem for p in paths} != expected:
        raise ValueError('Expected every person partition for each selected rating')
    if sum(pq.ParquetFile(p).metadata.num_rows for p in paths) >= np.iinfo(np.int32).max:
        raise ValueError('Source exceeds the int32 cooccurrence count bound')
    metadata = {normalize_atom(t): info for t, info in json.loads(args.metadata.read_text(encoding='utf-8')).items()}
    frequency = pq.read_table(args.frequency).to_pandas()
    counts = {normalize_atom(t): int(c) for t, c in zip(frequency.tag, frequency['count'])}
    vocabulary = sorted(set(counts) | set(metadata))
    index = {tag: i for i, tag in enumerate(vocabulary)}
    keep = np.array([visual(t, metadata.get(t, {})) or is_population(t) for t in vocabulary] + [False])
    reject = np.array([row_blocked(t, metadata.get(t, {})) for t in vocabulary] + [False])
    eligible = {t for t in vocabulary if counts.get(t, 0) >= args.min_count and visual(t, metadata.get(t, {}))}
    anchors_from = getattr(args, 'anchors_from', None)
    baseline = json.loads(anchors_from.read_text(encoding='utf-8')) if anchors_from else None
    frozen = set(baseline['events']) if baseline else eligible
    if not frozen <= eligible:
        raise ValueError('Frozen anchors must remain within the unchanged visual anchor scope')
    targets = sorted(frozen, key=lambda t: (-counts[t], t))
    target_ids = [index[t] for t in targets]
    target_index = {t: i for i, t in enumerate(targets)}
    active_ids = np.flatnonzero(keep[:-1])
    min_global_lift = getattr(args, 'min_global_lift', 3.)
    min_companions = getattr(args, 'min_companions', 2)
    min_qe_skew = getattr(args, 'min_qe_skew', 0.)
    action_min_count = getattr(args, 'action_min_count', 0)
    signature_text = (json.dumps(vocabulary) + inspect.getsource(read_partition)
                      + inspect.getsource(row_blocked) + RISK_CONTENT_RE.pattern
                      + json.dumps(sorted(AGE_EXCEPTIONS)) + digest(ROOT / 'tools/thumb_age_guard.py'))
    signature = hashlib.sha256(signature_text.encode() + keep.tobytes() + reject.tobytes()).hexdigest()
    out.mkdir(parents=True)
    cache = out / '_build_cache'
    previous = None
    if args.reuse_index:
        previous = json.loads((args.reuse_index / 'build_report.json').read_text(encoding='utf-8'))
        if (previous['source']['frequency']['sha256'] != digest(args.frequency)
                or previous['source']['metadata']['sha256'] != digest(args.metadata)
                or previous['policy']['ratings'] != args.ratings
                or previous['source'].get('index_signature') != signature):
            raise ValueError('Reused index must have the same frequency, metadata and rating sources')
    cache.mkdir()
    old_cache = Path(previous['source']['index_cache_dir']) if previous else None
    nominated = defaultdict(list)
    manifest = []
    global_background = np.zeros(len(vocabulary), dtype=np.int64)
    # 같은 어휘를 Q/E 분면에서만 따로 센다. qe_share 의 분자가 된다.
    qe_background = np.zeros(len(vocabulary), dtype=np.int64)
    global_cooc = np.zeros((len(targets), len(active_ids)), dtype=np.int64)
    global_rows = 0
    for path in paths:
        if previous:
            before = next((m for m in previous['source']['partitions'] if m['path'] == str(path)), None)
            if before is None or digest(path) != before['sha256']:
                raise ValueError(f'Reused source changed: {path}')
            matrix = sparse.load_npz(old_cache / f'{path.stem}.npz')
            ids = np.load(old_cache / f'{path.stem}.ids.npy')
            original_rows = np.load(old_cache / f'{path.stem}.rows.npy')
            if matrix.shape != (len(ids), len(vocabulary)):
                raise ValueError(f'Reused index shape mismatch: {path.stem}')
            stats = {k: before[k] for k in ['source_rows', 'retained_rows', 'rejected_rows',
                                           'unknown_atom_occurrences', 'duplicate_id_extra_rows']}
        else:
            matrix, ids, stats, original_rows = read_partition(path, vocabulary, keep, reject, return_row_ids=True)
        sparse.save_npz(cache / f'{path.stem}.npz', matrix, compressed=False)
        np.save(cache / f'{path.stem}.ids.npy', ids)
        np.save(cache / f'{path.stem}.rows.npy', original_rows)
        background = np.asarray(matrix.sum(axis=0)).ravel()
        np.save(cache / f'{path.stem}.background.npy', background)
        # Exact global numerator, not local P(c|anchor) divided by global P(c).
        # Bulk sparse multiplication also avoids revisiting millions of rows
        # once for each anchor during extraction.
        part_cooc = (matrix[:, target_ids].T @ matrix[:, active_ids]).tocsr()
        part_cooc.sum_duplicates()
        global_cooc += part_cooc.toarray()
        sparse.save_npz(cache / f'{path.stem}.cooc.npz', part_cooc)
        global_background += background
        if path.stem.split('_', 1)[0] in {'q', 'e'}:
            qe_background += background
        global_rows += len(ids)
        for tag in targets:
            n = int(background[index[tag]])
            if n >= args.min_events:
                nominated[tag].append((path.stem, n))
        manifest.append({'path': str(path), 'sha256': digest(path), 'bytes': path.stat().st_size, **stats})
        print(json.dumps({'phase': 'index_and_global_counts', 'partition': path.stem, **stats}), flush=True)
    np.savez_compressed(cache / 'global_counts.npz', background=global_background,
                        cooc=global_cooc, active_ids=active_ids, target_ids=np.array(target_ids),
                        total_rows=np.array(global_rows), qe_background=qe_background)
    by_partition = defaultdict(list)
    for tag in targets:
        # Examine every qualified partition; only then cap exported examples
        # separately by rating, so abundant G/S contexts cannot crowd out Q/E.
        for part, _ in nominated[tag]:
            by_partition[part].append(tag)
    variants = defaultdict(list)
    for part, tags in sorted(by_partition.items()):
        matrix = sparse.load_npz(cache / f'{part}.npz')
        ids = np.load(cache / f'{part}.ids.npy')
        original_rows = np.load(cache / f'{part}.rows.npy')
        part_cooc = sparse.load_npz(cache / f'{part}.cooc.npz')
        csc = matrix.tocsc()
        csc.sort_indices()
        background = np.load(cache / f'{part}.background.npy')
        for tag in tags:
            ti = target_index[tag]
            cooc = np.zeros(len(vocabulary), dtype=np.int64)
            cooc[active_ids] = part_cooc[ti].toarray().ravel()
            global_vector = np.zeros(len(vocabulary), dtype=np.int64)
            global_vector[active_ids] = global_cooc[ti]
            row = make_example(matrix, csc, ids, index[tag], vocabulary, metadata, background,
                               support=args.support, joint_support=args.joint_support,
                               min_global_lift=min_global_lift, cooc_counts=cooc, source_row_ids=original_rows,
                               min_companions=min_companions, min_qe_skew=min_qe_skew,
                               action_min_count=action_min_count,
                               qe_background=qe_background,
                               rated_qe=part.split('_', 1)[0] in {'q', 'e'},
                               global_stats={'rows': global_rows,
                                             'anchor_count': int(global_background[index[tag]]),
                                             'background': global_background, 'cooc': global_vector})
            if row:
                rating = part.split('_', 1)[0]
                row['rating_token'] = RATING_PROMPTS[rating]
                row['prompt'] = ', '.join([*row['tags'], row['rating_token']])
                variants[tag].append({'partition': part, 'rating': rating,
                                      'person': part.split('_', 1)[1], **row})
        print(json.dumps({'phase': 'extract', 'partition': part, 'anchors': len(tags)}), flush=True)
    events = {}
    for tag in targets:
        available = {v['partition']: v for v in variants[tag]}
        selected, seen = [], set()
        for rating in args.ratings:
            ordered = choose_partitions([(p, v['anchor_rows']) for p, v in available.items()
                                         if v['rating'] == rating], len(available))
            # 동반이 많은 예시를 먼저. 안정 정렬이라 동률이면 위의 지지도/인원 다양성 순서를 지킨다.
            # 이것이 없으면 큰 파티션의 1개짜리가 작은 파티션의 3개짜리를 밀어낸다(실측 362 앵커).
            ordered = sorted(ordered, key=lambda pr: -len(available[pr[0]]['companions']))
            rating_selected = 0
            for part, _ in ordered:
                row = available[part]
                key = (rating, tuple(sorted(row['tags'])))
                if key in seen:
                    continue
                selected.append(row)
                seen.add(key)
                rating_selected += 1
                if rating_selected == args.variants:
                    break
        if selected:
            info = metadata[tag]
            events[tag] = {'group': info['group'], 'subgroup': info.get('subgroup', ''),
                           'frequency_table_count': counts[tag],
                           'keywords_kr': info.get('keywords_kr', ''),
                           'description_ko': info.get('description', ''), 'examples': selected}
    policy = {'anchor_min_frequency': args.min_count, 'anchor_groups': sorted(GROUPS),
              'ratings': args.ratings, 'min_anchor_rows_per_partition': args.min_events,
              'max_examples_per_anchor': args.variants * len(args.ratings),
              'max_examples_per_anchor_per_rating': args.variants, 'min_companion_support': args.support,
              'min_global_companion_lift': min_global_lift, 'min_joint_support': args.joint_support,
              'global_lift': 'P(companion|anchor, all retained partitions) / P(companion, all retained partitions)',
              'partition_lift': 'local conditional / local background; ranking only, not the background rejection gate',
              'redundancy': 'skip a candidate present in at least 98% of the current joint if its background count is at least 1.5x the most specific selected tag',
              'min_joint_rows': 10,
              'non_population_tags': [1 + min_companions, 5],
              'min_companions': min_companions,
              'min_qe_skew': min_qe_skew,
              'action_min_count': action_min_count,
              'action_lane': 'an Expression_Action companion may skip the ratio support floor when its '
                             'observed cooccurrence with the anchor reaches action_min_count; that companion '
                             'is also admitted on an absolute joint floor of action_min_count rows instead of '
                             'the ratio. Such a companion is appended after every ordinary one so a thin '
                             'action supplements rather than replaces. The global lift gate, colour '
                             'exclusion and group cap still apply',
              'qe_skew': 'observed q/e share of a companion across retained partitions; a q/e example '
                         'must contain at least one companion at or above the threshold',
              'source_row_filter': 'age guard, bounded risk markers and Danger group only; ordinary adult tags do not reject rows',
              'output_tag_filter': 'unchanged general visual groups; ordinary adult, risk and age markers remain excluded from anchors and companions',
              'selection': 'global lift gate, partition lift ranking, action priority for objects/clothes/creatures; richer examples first, then largest support and different persons within each rating; at most two tags per metadata group',
              'count_semantics': 'source rows, not unique post IDs; joint count includes all observed output atoms including population, but excludes rendered rating metadata',
              'person_semantics': 'only actual source population atoms; no inferred person tokens',
              'format': 'plain observed tags followed by rating metadata token; no anchor weights',
              'sort': 'anchor frequency table count descending, then normalized tag; rating order g,s,q,e and per-rating partition rank',
              'coverage_limit': 'known visual groups only; unknown metadata, anatomy, explicit anchors and nonvisual metadata excluded; abstain if support is insufficient'}
    provenance = {'partitions': manifest,
                  'index_cache_dir': str(cache),
                  'index_contract': INDEX_CONTRACT, 'index_signature': signature,
                  'global_retained_rows': global_rows,
                  'global_counts_sha256': digest(cache / 'global_counts.npz'),
                  'anchors_from': ({'path': str(anchors_from.resolve()), 'sha256': digest(anchors_from)} if anchors_from else None),
                  'index_builder_sha256': (previous['source'].get('index_builder_sha256', previous['source']['builder_sha256'])
                                           if previous else digest(Path(__file__))),
                  'frequency': {'path': str(args.frequency.resolve()), 'sha256': digest(args.frequency)},
                  'metadata': {'path': str(args.metadata.resolve()), 'sha256': digest(args.metadata)},
                  'builder_sha256': digest(Path(__file__)),
                  'helper_sha256': {str(p.relative_to(ROOT)): digest(p) for p in
                                    [ROOT / 'core/tag_combo/noise.py', ROOT / 'tools/thumb_age_guard.py',
                                     ROOT / 'tools/build_fast_search_event_catalog.py']}}
    write_json(out / 'evidence.json', {'version': 3, 'policy': policy, 'source': provenance, 'events': events})
    groups, ratings = defaultdict(list), {r: [] for r in args.ratings}
    line_map, all_lines = [], []
    for tag, event in events.items():
        for i, row in enumerate(event['examples']):
            groups[event['group']].append(row['prompt'])
            ratings[row['rating']].append(row['prompt'])
            all_lines.append(row['prompt'])
            line_map.append({'line': len(all_lines), 'anchor': tag, 'example_index': i,
                             'group_file': f"by_group/{event['group']}.txt",
                             'group_line': len(groups[event['group']]),
                             'rating_file': f"by_rating/{row['rating']}.txt",
                             'rating_line': len(ratings[row['rating']])})
    (out / 'by_group').mkdir()
    for group, lines in groups.items():
        (out / 'by_group' / f'{group}.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (out / 'by_rating').mkdir()
    for rating, lines in ratings.items():
        (out / 'by_rating' / f'{rating}.txt').write_text('\n'.join(lines) + ('\n' if lines else ''), encoding='utf-8')
    (out / 'prompts.txt').write_text('\n'.join(all_lines) + '\n', encoding='utf-8')
    write_json(out / 'line_index.json', line_map)
    qualified = {tag for tag, c in counts.items() if c >= args.min_count}
    exclusions = Counter('missing_metadata' if tag not in metadata else
                         'blocked' if blocked(tag, metadata[tag]) else
                         'nonvisual_or_out_of_scope' for tag in qualified - eligible)
    examples = [row for event in events.values() for row in event['examples']]
    companion_counts = Counter(c['tag'] for row in examples for c in row['companions'])
    missing_per_rating = {r: [{'tag': t, 'reason': 'insufficient_partition_support'
                              if not any(p.startswith(r + '_') for p, _ in nominated[t]) else 'insufficient_joint_context'}
                             for t in targets if not any(v['rating'] == r for v in events.get(t, {}).get('examples', []))]
                          for r in args.ratings}
    quality = {'rows_with_partition_lift_below_2': sum(any(c['lift'] < 2 for c in row['companions']) for row in examples),
               'rows_with_global_lift_below_3': sum(any(c['global_lift'] < 3 for c in row['companions']) for row in examples),
               'top_companions': [{'tag': t, 'rows': n,
                                   'median_partition_lift': float(np.median([c['lift'] for row in examples for c in row['companions'] if c['tag'] == t])),
                                   'median_global_lift': float(np.median([c['global_lift'] for row in examples for c in row['companions'] if c['tag'] == t]))}
                                  for t, n in companion_counts.most_common(20)]}
    write_json(out / 'quality_metrics.json', quality)
    prior_report = (json.loads(anchors_from.with_name('build_report.json').read_text(encoding='utf-8'))
                    if anchors_from and anchors_from.with_name('build_report.json').exists() else {})
    prior_missing = {r['tag']: r['reason'] for r in prior_report.get('no_examples', [])}
    coverage = [{'tag': t, 'frequency_count': counts[t], 'group': metadata.get(t, {}).get('group', ''),
                 'status': ('exported' if t in events else
                            'missing_metadata' if t not in metadata else
                            'output_blocked' if blocked(t, metadata[t]) else
                            'nonvisual_or_out_of_scope' if t not in eligible else
                            'outside_frozen_baseline' if t not in frozen else
                            'insufficient_partition_support' if not nominated[t] else 'insufficient_joint_context'),
                 'ratings': sorted({v['rating'] for v in events.get(t, {}).get('examples', [])}),
                 'prior_v2_no_examples_reason': prior_missing.get(t, '')}
                for t in sorted(qualified, key=lambda t: (-counts[t], t))]
    write_json(out / 'coverage.json', coverage)
    write_json(out / 'missing_metadata.json', [row for row in coverage if row['status'] == 'missing_metadata'])
    write_json(out / 'no_examples_by_rating.json', missing_per_rating)
    report = {'frequency_threshold_tags': len(qualified), 'eligible_anchors': len(eligible),
              'target_anchors': len(targets), 'outside_frozen_baseline': len(eligible - frozen),
              'exported_anchors': len(events), 'prompt_lines': len(all_lines),
              'unique_prompt_lines': len(set(all_lines)), 'excluded_by_policy': dict(exclusions),
              'unique_rating_tag_sets': len({(v['rating'], tuple(sorted(v['tags']))) for v in examples}),
              'rating_prompt_lines': {r: len(lines) for r, lines in ratings.items()},
              'rating_anchors': {r: len(targets) - len(missing_per_rating[r]) for r in args.ratings},
              'group_anchors': dict(Counter(e['group'] for e in events.values())),
              'no_examples': [{'tag': t, 'reason': 'insufficient_partition_support' if not nominated[t]
                               else 'insufficient_joint_context'} for t in targets if t not in events],
              'source_rows': sum(m['source_rows'] for m in manifest),
              'retained_rows': sum(m['retained_rows'] for m in manifest),
              'quality_metrics': quality,
              'policy': policy, 'source': provenance,
              'artifacts': {name: {'sha256': digest(out / name), 'bytes': (out / name).stat().st_size}
                            for name in ['prompts.txt', 'evidence.json', 'line_index.json', 'coverage.json',
                                         'quality_metrics.json', 'missing_metadata.json', 'no_examples_by_rating.json']}}
    write_json(out / 'build_report.json', report)
    print(json.dumps({k: report[k] for k in ['exported_anchors', 'prompt_lines', 'eligible_anchors']}, ensure_ascii=False))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--partitions', type=Path, required=True)
    parser.add_argument('--frequency', type=Path, required=True)
    parser.add_argument('--metadata', type=Path, default=ROOT / 'data/interactive_tags.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--anchors-from', type=Path, help='Freeze anchor names from a prior evidence.json')
    parser.add_argument('--reuse-index', type=Path,
                        help='Previous output directory with the SAME row-filter/index implementation; sources and shape are checked')
    parser.add_argument('--ratings', nargs='+', choices=list(RATING_PROMPTS), default=list(RATING_PROMPTS))
    parser.add_argument('--min-count', type=int, default=1000)
    parser.add_argument('--min-events', type=int, default=50)
    parser.add_argument('--variants', type=int, default=3, help='Maximum examples per anchor PER RATING')
    parser.add_argument('--min-global-lift', type=float, default=3.)
    parser.add_argument('--support', type=float, default=.20)
    parser.add_argument('--joint-support', type=float, default=.05)
    parser.add_argument('--min-companions', type=int, default=2,
                        help='Minimum companions beside the anchor; 1 keeps anchors whose only '
                             'qualifying context is a single tag (shirt -> collared shirt)')
    parser.add_argument('--min-qe-skew', type=float, default=0.,
                        help='A q/e example must carry a companion whose observed q/e share reaches '
                             'this value; 0 disables the check')
    parser.add_argument('--action-min-count', type=int, default=0,
                        help='An Expression_Action companion may skip the ratio support floor once its '
                             'observed cooccurrence reaches this count; 0 disables the lane')
    args = parser.parse_args()
    if (not 0 < args.joint_support <= args.support <= 1 or args.min_count < 1
            or args.min_events < 1 or args.variants < 1 or args.min_global_lift <= 0
            or not math.isfinite(args.min_global_lift) or len(set(args.ratings)) != len(args.ratings)
            or args.min_companions < 1 or not 0 <= args.min_qe_skew <= 1
            or args.action_min_count < 0):
        parser.error('Thresholds must be positive, 0 < joint-support <= support <= 1, and ratings unique')
    build(args)


if __name__ == '__main__':
    main()
