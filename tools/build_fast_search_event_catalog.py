"""Build the read-only Ctrl+F catalog from local observed Event Preset rows.

This is an offline build tool, not a runtime dependency or downloader. It keeps
one strongest qualifying observation per taxonomy anchor and partition, without
appending retained dependency tags or inventing prompt combinations. The shared
archive and translation corpus are never changed.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile


ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS = ROOT / 'core/event_preset/event_preset_category_translations_ko.json'
TAXONOMY_MEMBER = 'base/event_taxonomy_v2_1.parquet'
MIN_MEANINGFUL_TAGS = 3
MAX_TOTAL_TAGS = 8
POPULATION_TAGS = frozenset({
    '1girl', '2girls', '3girls', '4girls', '5girls', '6+girls',
    '1boy', '2boys', '3boys', '4boys', '5boys', '6+boys',
    '1other', '2others', '3others', '4others', '5others', '6+others',
    'multiple girls', 'multiple boys', 'multiple others',
    'solo', 'solo focus', 'no humans',
})
POPULATION_PATTERN = re.compile(r'\d+\+?(?:girl|boy|other)s?\Z')
EXCLUDED_AGE_MARKERS = (
    'loli', 'shota', 'lolicon', 'shotacon', 'child', 'children', 'underage',
    'minor', 'minors', 'toddler', 'baby', 'infant', 'young', 'teen', 'teenager',
    'preteen', 'adolescent', 'aged down', 'age regression', 'ageplay', 'kodomo',
    'lolidom', 'onee-loli', 'onee-shota', 'onii-shota', 'shotadom', 'toddlercon',
    'child carry', 'baby carry', 'babywearing', 'kindergarten uniform',
)


def normalize_atom(value: str) -> str:
    return ' '.join(str(value).strip('[] ').replace('_', ' ').casefold().split())


def atoms(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, str):
        return ()
    return tuple(dict.fromkeys(part.strip() for part in raw.split(',') if part.strip()))


def is_population(tag: str) -> bool:
    normalized = normalize_atom(tag)
    return normalized in POPULATION_TAGS or POPULATION_PATTERN.fullmatch(normalized) is not None


def excluded_age_markers(tags: tuple[str, ...]) -> set[str]:
    return {normalize_atom(tag) for tag in tags} & set(EXCLUDED_AGE_MARKERS)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def translated_terms(tag: str, translations: dict) -> tuple[str, list[str]]:
    row = translations.get(tag, {})
    label = str(row.get('labelKo') or tag).strip()
    candidates = row.get('labelKoCandidates') or []
    if not isinstance(candidates, list):
        candidates = []
    aliases = list(dict.fromkeys(str(value).strip() for value in [row.get('labelKo'), *candidates]
                                if isinstance(value, str) and value.strip()))
    return label, aliases


def write_catalog(path: Path, payload: dict) -> None:
    """One event per line keeps the asset compact and its diffs bounded."""
    compact = lambda value: json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    lines = ['{']
    for key in ('version', 'source', 'policy'):
        lines.append(f'  {json.dumps(key)}:{compact(payload[key])},')
    lines.append('  "events":{')
    rows = list(payload['events'].items())
    for index, (tag, row) in enumerate(rows):
        lines.append(f'    {compact(tag)}:{compact(row)}' + (',' if index + 1 < len(rows) else ''))
    lines.extend(['  }', '}', ''])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines), encoding='utf-8', newline='\n')


def build(archive_path: Path, output_path: Path, report_path: Path) -> dict:
    import pandas as pd  # Only the offline builder needs parquet dependencies.

    archive_path = archive_path.resolve()
    output_path = output_path.resolve()
    report_path = report_path.resolve()
    if archive_path in (output_path, report_path) or output_path == report_path:
        raise ValueError('Archive, catalog, and report must be separate files')
    translation_bytes = TRANSLATIONS.read_bytes()
    translations = json.loads(translation_bytes)['events']
    variants = defaultdict(list)
    partition_metrics = []
    age_hits = Counter()
    with zipfile.ZipFile(archive_path) as archive:
        taxonomy_bytes = archive.read(TAXONOMY_MEMBER)
        taxonomy = pd.read_parquet(io.BytesIO(taxonomy_bytes))
        taxonomy_anchors = set(taxonomy.event_tag)
        members = sorted(name for name in archive.namelist()
                         if name.startswith('partitions/') and name.endswith('/event_observed_combo.parquet'))
        if len(members) != 52:
            raise ValueError(f'Expected 52 observed partitions; found {len(members)}')
        for member in members:
            partition = member.split('/')[1]
            frame = pd.read_parquet(io.BytesIO(archive.read(member)))
            catalog = pd.read_parquet(io.BytesIO(archive.read(f'partitions/{partition}/event_catalog.parquet')))
            metrics = {'partition': partition, 'source_rows': len(frame)}
            valid_anchors = taxonomy_anchors & set(catalog.event_tag)
            frame = frame[frame.event_tag.isin(valid_anchors)].copy()
            metrics['taxonomy_catalog_rows'] = len(frame)
            frame['_tags'] = frame.observed_event_combo.map(atoms)
            frame['_total'] = frame['_tags'].map(len)
            frame['_meaningful'] = frame['_tags'].map(lambda values: sum(not is_population(v) for v in values))
            frame['_has_anchor'] = [anchor in tags for anchor, tags in zip(frame.event_tag, frame['_tags'])]
            qualified = frame[(frame['count'] > 0) & frame['_has_anchor']
                              & (frame['_meaningful'] >= MIN_MEANINGFUL_TAGS)
                              & (frame['_total'] <= MAX_TOTAL_TAGS)].copy()
            metrics.update({
                'under_three_meaningful_rows': int((frame['_meaningful'] < MIN_MEANINGFUL_TAGS).sum()),
                'over_eight_total_rows': int((frame['_total'] > MAX_TOTAL_TAGS).sum()),
                'missing_anchor_rows': int((~frame['_has_anchor']).sum()),
                'nonpositive_count_rows': int((frame['count'] <= 0).sum()),
                'qualified_before_age_filter': len(qualified),
            })
            allowed = []
            for anchor, tags, dependencies in zip(qualified.event_tag, qualified['_tags'], qualified.retained_dependency_tags):
                hits = excluded_age_markers((anchor, *tags, *atoms(dependencies)))
                age_hits.update(hits)
                allowed.append(not hits)
            qualified = qualified.loc[allowed]
            metrics['age_filtered_rows'] = metrics['qualified_before_age_filter'] - len(qualified)
            qualified.sort_values(['count', 'observed_event_combo'], ascending=[False, True], kind='stable', inplace=True)
            best = qualified.drop_duplicates('event_tag')
            metrics['selected_anchor_partition_rows'] = len(best)
            metrics['selected_count_one_rows'] = int((best['count'] == 1).sum())
            partition_metrics.append(metrics)
            for anchor, tags, count in zip(best.event_tag, best['_tags'], best['count']):
                variants[anchor].append({'partition': partition, 'tags': list(tags), 'count': int(count)})

    events = {}
    for anchor in sorted(variants):
        label, aliases = translated_terms(anchor, translations)
        events[anchor] = {'label': label, 'aliases': aliases,
                          'variants': sorted(variants[anchor], key=lambda row: row['partition'])}
    payload = {
        'version': 1,
        'source': {
            'archive_name': archive_path.name,
            'archive_sha256': sha256(archive_path),
            'archive_bytes': archive_path.stat().st_size,
            'taxonomy_member': TAXONOMY_MEMBER,
            'taxonomy_sha256': hashlib.sha256(taxonomy_bytes).hexdigest(),
            'translation_path': TRANSLATIONS.relative_to(ROOT).as_posix(),
            'translation_sha256': hashlib.sha256(translation_bytes).hexdigest(),
            'partitions': [row['partition'] for row in partition_metrics],
        },
        'policy': {
            'min_non_population_tags': MIN_MEANINGFUL_TAGS,
            'max_total_unique_tags': MAX_TOTAL_TAGS,
            'min_observed_count': 1,
            'population_tags': sorted(POPULATION_TAGS),
            'population_pattern': POPULATION_PATTERN.pattern,
            'selection': 'one strongest qualifying observed row per taxonomy/catalog anchor and partition; count descending, raw observed CSV ascending',
            'copied_tags': 'unique observed_event_combo atoms in original order; no retained dependencies appended',
            'age_filter_scope': 'anchor, observed atoms, and retained dependency atoms before selection',
            'age_marker_matching': 'exact casefolded atoms with underscore/space equivalence; only explicitly listed compounds',
            'excluded_age_markers': list(EXCLUDED_AGE_MARKERS),
            'translations': 'existing labelKo and labelKoCandidates only',
        },
        'events': events,
    }
    write_catalog(output_path, payload)
    report = {
        'archive': str(archive_path), 'output': str(output_path),
        'source': payload['source'], 'policy': payload['policy'],
        'catalog_sha256': sha256(output_path), 'catalog_bytes': output_path.stat().st_size,
        'taxonomy_anchors': len(taxonomy_anchors), 'selected_anchors': len(events),
        'selected_anchor_partition_rows': sum(len(event['variants']) for event in events.values()),
        'selected_unique_bundles': len({tuple(row['tags']) for event in events.values() for row in event['variants']}),
        'age_marker_row_hits': dict(sorted(age_hits.items())),
        'partition_metrics': partition_metrics,
        'verification': {
            'archive_read_only': True,
            'no_network_or_model_calls': True,
            'selection_source': 'observed_event_combo rows, intersected with taxonomy and per-partition event_catalog',
            'labels_source': 'existing Korean category translations; no new meanings generated',
            'limits': 'Observed tags are examples, not a guarantee of coherent intent. Exclusion markers are a bounded lexical filter, not an exhaustive age classifier.',
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    report = build(args.archive, args.output, args.report)
    print(json.dumps({key: report[key] for key in ('catalog_sha256', 'catalog_bytes', 'selected_anchors',
                                                 'selected_anchor_partition_rows', 'selected_unique_bundles')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
