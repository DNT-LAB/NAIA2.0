"""Extract compact, typed name bindings from the existing Korean Danbooru CSV.

No runtime CSV dependency and no online translation. Ambiguities are retained.
Labels and prose are not blindly copied into name aliases.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.kr_tag_loader import load_kr_tag_records
from core.tag_knowledge import normalize_tag_key

GENERIC = set('캐릭터 저작권 작품 시리즈 게임 애니메이션 만화 기타 미디어 등장인물 게임타이틀 개념그룹 인물 동방캐릭터 란마캐릭터 소녀 소년 여성 남성 여자 남자 미소녀 풀의신 여신 신 리본 녹색눈 흰머리 긴머리 금발 은발 개인세 인디버튜버 한글명 별명/애칭 한국어명 한국명 캐릭터명 한글이름 별명 애칭 격투 창작'.split())
GENERIC.update('라이트노벨 비주얼노벨 소설 코스튬 버튜버 칸무스 수영복 영문명 기본의상 오리지널캐릭터 등장캐릭터 모바일게임 동인게임'.split())
GENERIC.update('음악 보컬로이드곡 함선의인화 판타지 마법소녀 전투 운영체제 웹사이트 게임엔진 플랫폼 가상유튜버 그룹 프로젝트 브랜드 회사 기업 이벤트 노래 게임시리즈'.split())
GENERIC.update('영화 웹툰 게임사 제작사 게임작품'.split())
GENERIC.add('스고이')  # Serval's catchphrase is not a character name.
REVIEWED = {
    'ranma 1/2': ['란마', '란마 1/2'],
    'nahida (genshin impact)': ['나히다'],
    'pokemon': ['포켓몬', '포켓몬스터'],
    'nijisanji': ['니지산지'],
    'kantai collection': ['함대 컬렉션', '칸코레'],
    'warship girls r': ['전함소녀 R', '전함소녀'],
    'wuthering waves': ['명조', '명조: 워더링 웨이브'],
    'serval (kemono friends)': ['서벌'],  # Explicit <서벌> label on this source row.
}


def allowed(term):
    compact = term.replace(' ', '')
    return (bool(re.search('[가-힣]', term)) and 1 <= len(term) <= 100
            and compact not in GENERIC and not re.search(r'[,<>\n\r|]', term)
            and not re.fullmatch(r'(?:작품|시리즈|게임|애니메이션|애니|만화|소설|음악|캐릭터|미디어|저작권|원작|이름|명|그룹|타이틀|제목|분류|장르|출처|관련|[·/\s])+', term)
            and not re.match(r'^(한글명|영문명|별명/애칭|한국어명)\b', term))


def extract(source):
    rows = []
    stats = Counter()
    with source.open(encoding='utf-8-sig', newline='') as stream:
        for fields in csv.reader(stream):
            stats['source_rows'] += 1
            if len(fields) != 4 or fields[1] not in {'3', '4'}:
                continue
            tag, cat, _count, description = fields
            tag = normalize_tag_key(tag)
            keyword = description.partition('키워드:')[2]
            if not keyword and '| 검색어:' in description:
                keyword = '| 검색어:' + description.partition('| 검색어:')[2]
            if not keyword:
                stats['no_keyword_field'] += 1
                continue
            plain = re.sub(r'<[^<>]*>', '', keyword).replace('| 검색어:', ',')
            terms = [a.strip().strip('[]').strip() for a in plain.split(',')]
            aliases = [a for a in terms if allowed(a)]
            primary_field = re.sub(r'<[^<>]*>', '', keyword.partition('| 검색어:')[0])
            primary_terms = [a.strip().strip('[]').strip() for a in primary_field.split(',')]
            primary_names = [a for a in primary_terms if allowed(a)][:1]
            if cat == '3':
                # Copyright rows often contain only a title label, e.g.
                # <동물의 숲>. Character rows' labels still remain excluded.
                titles = [a.strip() for a in re.findall(r'<([^<>]+)>', keyword) if allowed(a.strip())]
                aliases.extend(titles)
                primary_names.extend(titles)
            # A copyright-specific category leaf is usable only if its literal
            # title also occurs in the prose. Character category leaves name
            # their WORK, not the character, and must never become aliases.
            heading = re.match(r'^\[([^]]+)\]', description)
            if cat == '4' and heading:
                work = normalize_tag_key(heading[1].split('>')[-1]).replace(' ', '')
                aliases = [a for a in aliases if normalize_tag_key(a).replace(' ', '') != work]
            if cat == '3' and heading:
                title = heading[1].split('>')[-1].strip()
                if allowed(title) and title in description[heading.end():].partition('키워드:')[0]:
                    aliases.append(title)
            rows.append((tag, 'copyright' if cat == '3' else 'character', aliases, primary_names))
    # Even unique <labels> can describe genres (e.g. 란마's <격투>).
    # Do not promote them to identity without a separately reviewed override.
    result = {}
    primary = defaultdict(set)
    for tag, category, aliases, primary_names in rows:
        aliases.extend(REVIEWED.get(tag, ()))
        for name in [*primary_names, *REVIEWED.get(tag, ())]:
            primary[normalize_tag_key(name).replace(' ', '')].add(category)
        aliases = sorted(set(aliases))[:16]
        if aliases:
            result[tag] = {'category': category, 'aliases': aliases}
    # Keywords also mention associated entities: a Miku song can list
    # 하츠네 미쿠, while a character lists their franchise. Use PRIMARY names
    # to identify these cross-category references, not every keyword (which
    # would incorrectly turn Miku into a song title and erase her own name).
    for row in result.values():
        if row['category'] == 'copyright':
            kept = [a for a in row['aliases']
                    if primary.get(normalize_tag_key(a).replace(' ', '')) != {'character'}]
            stats['cross_category_references_removed'] += len(row['aliases']) - len(kept)
            row['aliases'] = kept
    work_names = {normalize_tag_key(a).replace(' ', '') for row in result.values()
                  if row['category'] == 'copyright' for a in row['aliases']}
    for tag in list(result):
        row = result[tag]
        if row['category'] == 'character':
            kept = [a for a in row['aliases'] if normalize_tag_key(a).replace(' ', '') not in work_names]
            stats['cross_category_references_removed'] += len(row['aliases']) - len(kept)
            row['aliases'] = kept
        if not row['aliases']:
            del result[tag]
    return result, dict(stats)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--replace-generated', action='store_true')
    args = parser.parse_args()
    if (args.output.exists() or args.report.exists()) and not args.replace_generated:
        parser.error('Refusing to overwrite existing output')
    entities, stats = extract(args.source)
    raw = load_kr_tag_records(ROOT, include_named_entity_aliases=False).raw
    active = defaultdict(set)
    for key, info in raw.items():
        active[normalize_tag_key(info.get('_tag') or key)].add(info.get('_cat', ''))
    skipped = Counter()
    selected = {}
    for tag, item in entities.items():
        if tag not in active:
            skipped['missing_active_tag'] += 1
        elif active[tag] - {'', item['category']}:
            skipped['category_conflict'] += 1
        else:
            selected[tag] = item
    owners = defaultdict(set)
    for tag, item in selected.items():
        for alias in item['aliases']:
            owners[normalize_tag_key(alias)].add(tag)
    source = {'file': args.source.name, 'sha256': hashlib.sha256(args.source.read_bytes()).hexdigest()}
    payload = {'schema_version': 1, 'kind': 'named_entity_aliases', 'version': '20260919-v1',
               'source': source, 'semantic_certified': False, 'entities': dict(sorted(selected.items()))}
    report = {**stats, 'source': source, 'entities': len(selected),
              'categories': dict(Counter(i['category'] for i in selected.values())),
              'aliases': sum(len(i['aliases']) for i in selected.values()), 'skipped': dict(skipped),
              'ambiguous_aliases': {a: sorted(tags) for a, tags in owners.items() if len(tags) > 1}}
    for path, data in [(args.output, payload), (args.report, report)]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'ambiguous_aliases'}, ensure_ascii=False))
    print('ambiguous aliases', len(report['ambiguous_aliases']))


if __name__ == '__main__':
    main()
