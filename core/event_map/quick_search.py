"""Bounded, deterministic observed-event lookup over the current .naiamap."""
from collections import Counter
import numpy as np

from core.event_map.random_link import ensure_event_map_service
from core.event_map.service import MapQueryError

SCAN_LIMIT = 4096
EVENT_GROUPS = ('expression', 'action', 'adult', 'situation')
# 조합을 접는 잣대(2026-09-13, 사용자 제보 "집계가 무한정 내려간다"):
#   게시물의 이벤트 태그 집합을 통째로 키로 세면 거의 전부 고유하다('maid' 27,823행 중 25,211행이 1회).
#   표본 안에서 MIN_SUPPORT_RATIO 이상 나오는 태그만 남겨 집합을 접고, MIN_COUNT 미만은 내지 않는다.
MIN_SUPPORT = 3            # 표본이 작아도 최소 3건은 같이 나와야 '자주'다
MIN_SUPPORT_RATIO = 0.02   # 표본의 2% - 4,096건이면 82건
MIN_COUNT = 2              # 같은 조합이 2번은 관측돼야 한다(1회는 조합이 아니라 한 게시물이다)
MAX_TAGS = 8
MIN_TAGS = 3
MAX_ROWS_PER_ANCHOR = 12   # 앵커 16개 × 12 = 최대 192행(8행 페이지 24쪽) - 40이면 640행이라 끝이 안 보였다(실측)


def _collapse(idx, pool, allowed, pinned):
    """표본 게시물마다 (분면, 접은 이벤트 태그 튜플) 을 세어 돌려준다."""
    counts = idx._count_tags(pool)
    support = max(MIN_SUPPORT, int(np.ceil(pool.size * MIN_SUPPORT_RATIO)))
    keep = allowed & (counts >= support)
    for t in pinned:
        keep[t] = True
    pin_arr = np.fromiter(pinned, dtype=np.int64, count=len(pinned))
    offsets, body, part_arr = idx.offsets, idx.body, idx.part_arr
    out = Counter()
    for rid in pool.tolist():
        sel = body[offsets[rid]:offsets[rid + 1]].astype(np.int64)
        sel = sel[keep[sel]]
        if sel.size > MAX_TAGS:
            # 핀은 남기고, 나머지는 표본 빈도 상위로 자른다 - 잘라도 그 게시물 태그의 부분집합이다.
            rest = sel[~np.isin(sel, pin_arr)]
            rest = rest[np.argsort(-counts[rest], kind='stable')[:MAX_TAGS - len(pinned)]]
            sel = np.concatenate([pin_arr, rest])
        if sel.size < MIN_TAGS:
            continue
        out[(int(part_arr[rid]), tuple(sorted(sel.tolist())))] += 1
    return out


def combinations(service, pins, rating='', person=''):
    return combinations_with_total(service, pins, rating, person)[0]


def combinations_with_total(service, pins, rating='', person=''):
    """(조합 행들, 핀을 전부 가진 게시물 수). 칩의 숫자는 행 수(상한 40)가 아니라 게시물 수다."""
    idx = service.index()
    ratings, persons = service._filters(idx, rating, person)
    tids, unknown = idx._resolve_many(pins)
    if unknown or not tids or len(tids) > MAX_TAGS or any(
        not idx.usable_arr[t] or idx.color_arr[t] or idx.population_arr[t] for t in tids
    ):
        return [], 0
    pool = idx._matching_posts(tids, idx._partition_filter(ratings, persons))
    total = int(pool.size)
    sampled = len(pool) > SCAN_LIMIT
    if sampled:
        pool = pool[np.linspace(0, len(pool)-1, SCAN_LIMIT, dtype=np.int64)]
    if pool.size == 0:
        return [], 0
    mask = service.group_mask(EVENT_GROUPS)
    allowed = mask & idx.usable_arr & ~idx.color_arr & ~idx.population_arr
    counts = _collapse(idx, pool, allowed, list(tids))
    rows = []
    for (partition, selected), count in sorted(counts.items(), key=lambda entry: (-entry[1], entry[0])):
        if count < MIN_COUNT:
            break
        if len(rows) >= MAX_ROWS_PER_ANCHOR:
            break
        tags = [idx.by_id[t] for t in selected]
        part = idx.partitions[partition]
        r, p = part.split('_', 1)
        value = ', '.join(tags)
        rows.append({'value':value, 'title':pins[-1], 'subtitle':value, 'anchor':pins[-1], 'tags':tags,
                     'rating':r, 'person':p, 'count':count, 'detail':'basic', 'sampled':sampled,
                     'meta':f"{r.upper()} · {p.replace('_',' ')} · {len(tags)}태그 · {'표본' if sampled else '관측'} {count:,}"})
    return rows, total


# 페이지 캐시: 프론트가 스크롤로 다음 쪽을 청할 때마다 앵커 16개를 다시 세지 않는다. 색인 객체가 바뀌면 버린다.
_PAGE_CACHE: dict = {}
_PAGE_CACHE_MAX = 8


def _cached_rows(service, key, build):
    idx = service.index()
    hit = _PAGE_CACHE.get(key)
    if hit is not None and hit[0] is idx:
        return hit[1], hit[2]
    rows, events = build()
    if len(_PAGE_CACHE) >= _PAGE_CACHE_MAX:
        _PAGE_CACHE.pop(next(iter(_PAGE_CACHE)))
    _PAGE_CACHE[key] = (idx, rows, events)
    return rows, events


def search(context, query, limit, opts, lookup=None):
    service = ensure_event_map_service(context)
    if opts.get('event_detail') == 'deep':
        return [], '3–8태그 조합만 지원합니다.', {'exhausted':True, 'events':[]}
    terms = [part.strip() for part in query.split(',') if part.strip()]
    if not terms or len(terms) > 8:
        return [], '3–8태그 조합', {'exhausted':True, 'events':[]}
    excluded = set(str(opts.get('event_exclude') or '').split(','))
    rating, person = opts.get('rating', ''), opts.get('person', '')

    def build():
        anchors = service.suggest(terms[-1], limit=16, kr_lookup=lookup)['items']
        found_by_anchor, events = [], []
        for anchor in anchors:
            if anchor.get('blocked'):
                continue
            tag = anchor['tag']
            found, total = combinations_with_total(service, terms[:-1]+[tag], rating, person)
            if not found:
                continue
            # 칩의 숫자 = 그 앵커(+앞 핀)를 전부 가진 게시물 수. 행 수는 앵커당 40으로 자르므로 뜻이 없다.
            events.append({'tag':tag,'label':tag,'count':total,'rank':1})
            found_by_anchor.append((tag, found))
        return found_by_anchor, events

    found_by_anchor, events = _cached_rows(service, (query, rating, person), build)
    rows = [row for tag, found in found_by_anchor if tag not in excluded for row in found]
    # A post's same event set may match more than one anchor.
    unique = {}
    for row in rows:
        unique.setdefault((row['rating'],row['person'],tuple(row['tags'])),row)
    rows = list(unique.values())
    offset = int(opts.get('event_offset') or 0)
    return rows[offset:offset+limit], 'naiamap · 3–8태그 조합 · 큰 결과는 게시물 표본 집계', {
        'events':events,'exhausted':offset+limit >= len(rows),'offset':offset,'data_source':'naiamap'}


def neighbors(context, anchor, tags, rating, person, limit):
    service = ensure_event_map_service(context)
    if not 3 <= len(tags) <= 8:
        raise MapQueryError('bad_request', '조합은 3~8개 태그여야 합니다.')
    idx = service.index()
    tids, unknown = idx._resolve_many(tags)
    if unknown:
        return {'supersets': [], 'near': [], 'data_source': 'naiamap'}
    tags = [idx.by_id[t] for t in tids]
    chosen = set(tags)
    anchor_id = idx.resolve(anchor)
    if len(chosen) < 3 or anchor_id not in tids:
        raise MapQueryError('bad_request', '선택한 조합에 anchor가 포함되어야 합니다.')
    anchor = idx.by_id[anchor_id]
    supersets = [r for r in combinations(service, tags, rating, person) if set(r['tags']) > chosen]
    near = [r for r in combinations(service, [anchor], rating, person)
            if len(chosen - set(r['tags'])) == 1 and len(set(r['tags']) - chosen) == 1]
    for row in supersets + near:
        row['anchor'] = row['title'] = anchor
    return {'supersets':supersets[:limit], 'near':near[:limit], 'data_source':'naiamap'}
