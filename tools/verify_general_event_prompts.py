"""Verify exported lines, full joint counts and raw source witness rows offline."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from scipy import sparse

from tools.build_general_event_prompts import digest, normalize_atom, write_json, RATING_PROMPTS, blocked, row_blocked


def intersection(a, b):
    """Independent set-membership implementation, unlike builder searchsorted."""
    if len(a) > len(b):
        a, b = b, a
    return a[np.isin(a, b, assume_unique=True)]


def verify(directory):
    data = json.loads((directory / 'evidence.json').read_text(encoding='utf-8'))
    index = json.loads((directory / 'line_index.json').read_text(encoding='utf-8'))
    report = json.loads((directory / 'build_report.json').read_text(encoding='utf-8'))
    v3 = data['version'] >= 3
    lines = (directory / 'prompts.txt').read_text(encoding='utf-8').splitlines()
    assert len(lines) == len(index) == report['prompt_lines']
    assert all(line.strip() and not line.startswith('#') for line in lines)
    group_lines = {p.name: p.read_text(encoding='utf-8').splitlines() for p in (directory / 'by_group').glob('*.txt')}
    rating_files = {p.name: p.read_text(encoding='utf-8').splitlines() for p in (directory / 'by_rating').glob('*.txt')} if v3 else {}
    for row in index:
        example = data['events'][row['anchor']]['examples'][row['example_index']]
        suffix = [RATING_PROMPTS[example['rating']]] if v3 else []
        assert lines[row['line'] - 1] == example['prompt'] == ', '.join([*example['tags'], *suffix])
        assert group_lines[Path(row['group_file']).name][row['group_line'] - 1] == example['prompt']
        if v3:
            assert rating_files[Path(row['rating_file']).name][row['rating_line'] - 1] == example['prompt']
    frequency = pq.read_table(data['source']['frequency']['path']).to_pandas()
    metadata = {normalize_atom(t): v for t, v in json.loads(Path(data['source']['metadata']['path']).read_text(encoding='utf-8')).items()}
    vocabulary = sorted(set(normalize_atom(t) for t in frequency.tag) | {normalize_atom(t) for t in metadata})
    tag_ids = {tag: i for i, tag in enumerate(vocabulary)}
    queries = defaultdict(list)
    global_expected, global_pairs = {}, defaultdict(set)
    cache = Path(data['source'].get('index_cache_dir', str(directory / '_build_cache')))
    for anchor, event in data['events'].items():
        assert 1 <= len(event['examples']) <= data['policy']['max_examples_per_anchor']
        for example in event['examples']:
            assert anchor in example['tags'] and len(example['tags']) == len(set(example['tags']))
            queries[example['partition']].append((anchor, example))
            if v3:
                assert not any(blocked(t, metadata.get(t, {})) for t in example['tags'])
                assert len(example['source_row_indices']) == len(example['source_post_ids']) == 3
                for c in [*example['companions'], *example['candidates']]:
                    key = (anchor, c['tag'])
                    expected = {k: c[k] for k in ['global_cooccurrence', 'global_support',
                                                 'global_background_count', 'global_lift']}
                    expected['global_anchor_rows'] = example['global_anchor_rows']
                    expected['global_retained_rows'] = example['global_retained_rows']
                    assert key not in global_expected or global_expected[key] == expected
                    global_expected[key] = expected
                    global_pairs[anchor].add(c['tag'])
        if v3:
            for rating in data['policy']['ratings']:
                assert sum(v['rating'] == rating for v in event['examples']) <= data['policy']['max_examples_per_anchor_per_rating']
    if v3:
        ordered = sorted(data['events'], key=lambda t: (-data['events'][t]['frequency_table_count'], t))
        assert list(data['events']) == ordered
    witness_count = joint_checks = 0
    global_background = np.zeros(len(vocabulary), dtype=np.int64)
    global_observed, global_rows = defaultdict(int), 0
    parts = {Path(s['path']).stem: s for s in data['source']['partitions']}
    for part in sorted(parts if v3 else queries):
        examples = queries.get(part, [])
        matrix = sparse.load_npz(cache / f'{part}.npz').tocsc()
        ids = np.load(cache / f'{part}.ids.npy')
        source_row_ids = np.load(cache / f'{part}.rows.npy') if v3 else None
        if v3:
            assert len(source_row_ids) == len(ids) == matrix.shape[0]
            assert np.all(np.diff(source_row_ids) > 0)
            global_background += np.diff(matrix.indptr)
            global_rows += matrix.shape[0]
            for anchor, companions in global_pairs.items():
                aid = tag_ids[anchor]
                ar = matrix.indices[matrix.indptr[aid]:matrix.indptr[aid + 1]]
                if not len(ar):
                    continue
                for tag in companions:
                    cid = tag_ids[tag]
                    cr = matrix.indices[matrix.indptr[cid]:matrix.indptr[cid + 1]]
                    if len(cr):
                        global_observed[(anchor, tag)] += len(intersection(ar, cr))
        witnesses = defaultdict(list)
        local_stats = {}
        for anchor, example in examples:
            joint = None
            for tag in example['tags']:
                col = tag_ids[tag]
                hits = matrix.indices[matrix.indptr[col]:matrix.indptr[col + 1]]
                joint = hits if joint is None else intersection(joint, hits)
            assert len(joint) == example['joint_count'], (anchor, part, 'joint_count')
            assert example['source_post_ids'] == [int(i) for i in ids[joint[:3]]]
            if v3:
                assert example['source_row_indices'] == [int(i) for i in source_row_ids[joint[:3]]]
            col = tag_ids[anchor]
            assert matrix.indptr[col + 1] - matrix.indptr[col] == example['anchor_rows' if v3 else 'anchor_posts']
            anchor_rows = matrix.indices[matrix.indptr[col]:matrix.indptr[col + 1]]
            candidates = [*example['companions'], *example.get('candidates', [])] if v3 else example['companions']
            for companion in candidates:
                cid = tag_ids[companion['tag']]
                background_rows = matrix.indices[matrix.indptr[cid]:matrix.indptr[cid + 1]]
                key = (anchor, companion['tag'])
                if key not in local_stats:
                    local_stats[key] = len(intersection(anchor_rows, background_rows))
                cooc = local_stats[key]
                assert cooc == companion['cooccurrence']
                support = cooc / len(anchor_rows)
                lift = support / (len(background_rows) / matrix.shape[0])
                assert abs(support - companion['support']) <= .000001
                assert abs(lift - companion['lift']) <= .000001
                if v3:
                    assert len(background_rows) == companion['partition_background_count']
            if v3:
                assert example['partition_retained_rows'] == matrix.shape[0]
                assert len(joint) >= data['policy']['min_joint_rows']
                assert len(joint) / len(anchor_rows) >= data['policy']['min_joint_support']
                for row_id, post_id in zip(example['source_row_indices'], example['source_post_ids']):
                    witnesses[row_id].append((anchor, set(example['tags']), post_id))
            else:
                for post_id in example['source_post_ids']:
                    witnesses[post_id].append((anchor, set(example['tags'])))
            joint_checks += 1
        source = parts[part]
        assert digest(Path(source['path'])) == source['sha256'], (part, 'source changed')
        wanted = pa.array(sorted(witnesses), type=pa.int64())
        found = set()
        offset = 0
        # Reopen ORIGINAL parquet; this validates that sparse preprocessing did
        # not manufacture atom presence or attach the wrong original post id.
        for batch in pq.ParquetFile(source['path']).iter_batches(batch_size=65536, columns=['id', 'tag_string_general']):
            if v3:
                selected_rows = [i for i in witnesses if offset <= i < offset + batch.num_rows]
                matched = batch.take(pa.array([i - offset for i in selected_rows], type=pa.int64()))
                for row_id, post_id, text in zip(selected_rows, matched.column('id').to_pylist(), matched.column('tag_string_general').to_pylist()):
                    atoms = {normalize_atom(t) for t in text.split()}
                    assert not any(row_blocked(t, metadata.get(t, {})) for t in atoms)
                    for anchor, tags, expected_post_id in witnesses[row_id]:
                        assert post_id == expected_post_id and tags <= atoms
                        witness_count += 1
                    found.add(row_id)
                offset += batch.num_rows
                continue
            matched = batch.filter(pc.is_in(batch.column('id'), value_set=wanted))
            for post_id, text in zip(matched.column('id').to_pylist(), matched.column('tag_string_general').to_pylist()):
                atoms = {normalize_atom(t) for t in text.split()}
                for anchor, tags in witnesses[post_id]:
                    assert tags <= atoms, (anchor, part, post_id, tags - atoms)
                    witness_count += 1
                found.add(post_id)
        assert found == set(witnesses), (part, 'missing source witnesses')
        print(json.dumps({'partition': part, 'joint_checks': len(examples), 'source_witness_rows': len(found)}), flush=True)
    if v3:
        stats_path = cache / 'global_counts.npz'
        assert digest(stats_path) == data['source']['global_counts_sha256']
        with np.load(stats_path) as stats:
            np.testing.assert_array_equal(global_background, stats['background'])
            assert global_rows == int(stats['total_rows']) == data['source']['global_retained_rows']
            pair_table = stats['cooc']
            anchor_positions = {int(v): i for i, v in enumerate(stats['target_ids'])}
            companion_positions = {int(v): i for i, v in enumerate(stats['active_ids'])}
        for (anchor, tag), expected in global_expected.items():
            cooc = global_observed[(anchor, tag)]
            an, bg = int(global_background[tag_ids[anchor]]), int(global_background[tag_ids[tag]])
            assert cooc == expected['global_cooccurrence'] == int(pair_table[anchor_positions[tag_ids[anchor]], companion_positions[tag_ids[tag]]])
            assert an == expected['global_anchor_rows'] and bg == expected['global_background_count']
            assert global_rows == expected['global_retained_rows']
            support = cooc / an
            lift = support / (bg / global_rows)
            assert abs(support - expected['global_support']) <= .000001
            assert abs(lift - expected['global_lift']) <= .000001
            assert lift >= data['policy']['min_global_companion_lift']
    for name, expected in report['artifacts'].items():
        assert digest(directory / name) == expected['sha256']
    for source in data['source']['partitions']:
        if Path(source['path']).stem not in queries:
            assert digest(Path(source['path'])) == source['sha256']
    for name in ['frequency', 'metadata']:
        assert digest(Path(data['source'][name]['path'])) == data['source'][name]['sha256']
    result = {'status': 'passed', 'prompt_lines': len(lines), 'joint_count_checks': joint_checks,
              'raw_source_witness_checks': witness_count,
              'companion_support_and_lift_recomputed': True,
              'global_companion_pairs_recomputed': len(global_expected),
              'global_statistics_include_all_partitions': v3,
              'witness_addressing': 'original source row index plus post ID' if v3 else 'post ID',
              'source_hashes_unchanged': True, 'line_and_group_mapping_verified': True,
              'limits': 'Counts recomputed by set membership on the binary source index; raw source atoms checked for every witness. Source counts are rows, not unique post IDs. No image or semantic-quality guarantee.'}
    write_json(directory / 'verification.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    print(json.dumps(verify(parser.parse_args().directory)))
