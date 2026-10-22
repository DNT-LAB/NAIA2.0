"""Read-only character benchmark: nine runs, GC enabled, no user-data writes.

Run from the repository: python tools/bench_character_search.py --phase before|after
The before phase is run on the original source; after uses compact responses.
No server, installation, user configuration, or persistent cache is needed.
"""
from __future__ import annotations
import argparse
import gc
import json
import math
from pathlib import Path
import statistics
import sys
import time
import tracemalloc

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.character_viewer_service import CharacterViewerService
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


def service():
    # Deliberately nonexistent root prevents legacy thumbnail adoption.
    svc = CharacterViewerService(ROOT / '.codex_tmp/bench_readonly', data_root=ROOT / 'data')
    svc._thumb_index = {}
    svc._favorites = set()
    svc._hidden = set()
    if hasattr(svc, 'preview_index_cache_path'):
        svc.preview_index_cache_path = None
    return svc


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--phase', choices=['before', 'after'], required=True)
    parser.add_argument('--preview-index', type=Path, help='Existing sidecar to benchmark read-only reuse')
    args = parser.parse_args()
    after = args.phase == 'after'
    svc = service()
    svc.analysis()
    svc.debut_index()
    svc.groups()
    if after:
        tracemalloc.start()
        svc.warm_search_index()
        retained, peak = tracemalloc.get_traced_memory()
        for i in range(64):
            svc.build_list(exclude=[f'__benchmark_absent_feature_{i}__'])
        saturated, query_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        print(f'Index retained={retained / 2**20:.3f} MiB; build peak={peak / 2**20:.3f} MiB; '
              f'with 64 full-result caches={saturated / 2**20:.3f} MiB; total peak={query_peak / 2**20:.3f} MiB')
        svc._search_index.clear_results()
    svc.build_list()
    print(f'phase={args.phase}; characters={sum(1 for _ in svc._iter_all_chars())}; runs=9; GC={gc.isenabled()}; empty user state')
    print('| case | service median ms | service p95 ms | service+JSON median ms | service+JSON p95 ms | bytes | total |')
    print('|---|---:|---:|---:|---:|---:|---:|')

    def bench(label, call, clear=False):
        times, end_times = [], []
        for _ in range(9):
            if clear and after:
                svc._search_index.clear_results()
            start = time.perf_counter()
            result = call()
            mid = time.perf_counter()
            body = JSONResponse(result if after else jsonable_encoder(result)).body
            end = time.perf_counter()
            times.append((mid-start)*1000)
            end_times.append((end-start)*1000)
        p95 = lambda values: sorted(values)[math.ceil(.95*len(values))-1]
        print(f'| {label} | {statistics.median(times):.3f} | {p95(times):.3f} | {statistics.median(end_times):.3f} | {p95(end_times):.3f} | {len(body)} | {result.get("total", "-")} |')

    for query in ('miku', 'pink hair', '미쿠', 'ㅁㅋ', '하츠네', 'work:genshin impact'):
        bench(query + ' (uncached)', lambda q=query: svc.build_list(query=q), clear=True)
    svc.build_list(query='pink hair')
    bench('next page (cached)', lambda: svc.build_list(query='pink hair', page=1))
    bench('empty / compact' if after else 'empty / all_items',
          lambda: svc.build_list(**({'compact': True} if after else {'include_all': True})), clear=True)
    bench('groups', lambda: svc.build_groups())
    def cold_thumb():
        cold = service()
        return {'has_thumbnail': cold.has_thumbnail('vocaloid', 'hatsune miku')}
    bench('bundle cold keys (no disk cache)', cold_thumb)
    if after and args.preview_index:
        from core.character_preview_index import PreviewKeyIndex
        def reused_thumb():
            index = PreviewKeyIndex(svc.preview_path, args.preview_index, cache_write=False)
            assert index.reused, 'Expected an existing valid sidecar; benchmark never writes one'
            return {'has_thumbnail': 'vocaloid::hatsune miku' in index}
        bench('bundle saved keys (restart)', reused_thumb)
        print(f'Bundle sidecar bytes={args.preview_index.stat().st_size}')
    if after:
        bench('catalog (once per version)', svc.build_catalog)
        ids = svc.build_list(query='work:genshin impact', compact=True)['ids']
        assert ids == svc.build_list(include=['work:genshin impact'], compact=True)['ids']
        print('work query == include filter: PASS')
        for query in ('미쿠', 'ㅁㅋ', '하츠네'):
            rows = svc.build_list(query=query)['items']
            position = next((i for i, row in enumerate(rows) if row['character'] == 'hatsune miku'), None)
            assert position is not None and position < 3, (query, position)
            print(f'{query}: hatsune miku rank={position+1}')


if __name__ == '__main__':
    main()
