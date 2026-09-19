"""Read-only full-corpus name-binding audit and representative route probes."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.kr_tag_loader import load_kr_tag_records
from core.named_entity_aliases import NamedEntityIndex
from core.llm_search_index import LLMSearchIndex
from app.backend.server.autocomplete_commands import search_kr_tags
from app.backend.server.ollama_chat_tools import search_chat_tags, search_characters


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists')
    start = time.perf_counter()
    baseline = load_kr_tag_records(ROOT, include_named_entity_aliases=False)
    loaded = load_kr_tag_records(ROOT)
    index = NamedEntityIndex(loaded.raw)
    context = SimpleNamespace(repo_root=ROOT, kr_tags_raw=loaded.raw, runtime_paths=None,
                              autocomplete_state=SimpleNamespace(kr_tags_loaded=True))
    source = json.loads((ROOT / 'data/tag_index/named_entity_aliases.json').read_text(encoding='utf-8'))
    failures = [(tag, a) for tag, item in source['entities'].items() for a in item['aliases']
                if tag not in index.exact.get(a.lower().replace('_', ' '), ())]
    old = LLMSearchIndex.from_raw_tag_records(baseline.raw)
    new = LLMSearchIndex.from_raw_tag_records(loaded.raw)
    general_removed = sorted({r.tag for r in old._recs} - {r.tag for r in new._recs})
    probes = {}
    for q in ['나히다', '란마', '란마 1/2', '원신', '하츠네 미쿠', '하츠네미쿠',
              '미쿠', '샴푸', '블루아카이브', 'copyright:란마', 'character:나히다',
              'artist:나히다', 'art', 'arti', 'artist', 'artist ', 'artist collaboration']:
        before = time.perf_counter()
        autocomplete = search_kr_tags(context, q, 12)
        probes[q] = {'autocomplete': autocomplete, 'elapsed_ms': round((time.perf_counter()-before)*1000, 2)}
        if ':' not in q:
            probes[q]['agent'] = search_chat_tags(context, q, 6)
    probes['나히다']['character_tool'] = search_characters(context, '나히다')
    report = {'load_stats': loaded.named_entity_stats, 'warnings': loaded.warnings,
              'source_entities': len(source['entities']),
              'source_aliases': sum(len(v['aliases']) for v in source['entities'].values()),
              'categories': dict(Counter(v['category'] for v in source['entities'].values())),
              'unreachable_aliases': failures, 'general_index_removed': general_removed,
              'raw_tag_set_preserved': set(baseline.raw) == set(loaded.raw),
              'counts_preserved': all(baseline.raw[k].get('freq') == v.get('freq') for k, v in loaded.raw.items()),
              'probe_results': probes, 'seconds': round(time.perf_counter()-start, 2)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k != 'probe_results'}, ensure_ascii=False))
    for q, result in probes.items():
        print(q, '=>', [r['tag'] for r in result['autocomplete'][:3]])
    return int(bool(failures or general_removed or not report['raw_tag_set_preserved'] or not report['counts_preserved']))


if __name__ == '__main__':
    raise SystemExit(main())
