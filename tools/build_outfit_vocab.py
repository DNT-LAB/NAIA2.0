"""Build editable outfit vocabulary, SRS 2026-11-17 and prototype v4."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MAP = r'C:\VNR\DEV\NAIA-Event-Map-Build\full-min5-20260912\event_map.naiamap'
CORPUS = r'C:\VNR\DEV\NAIA-TagSearch-Full-20260912\tag_corpus.full.175.sqlite3'
DATA = ROOT / 'tools/presets_data'
# 2026-11-17 첫 빌드 실측. 시제품 v5(4981 · 436 · 1639)와의 차이는 하이픈 색 고침(-framed · -tinted eyewear → color)과
# 역할 태그 오버라이드 몫이다. 이 값은 이후의 뜻하지 않은 어휘 흔들림을 잡는 가드다.
EXPECTED = {'garment': 4973, 'modifier': 427, 'color': 1664, 'state': 283, 'noslot': 445}


def log(message):
    print(str(message).encode('ascii', 'backslashreplace').decode('ascii'), flush=True)


def fingerprint(path):
    path = Path(path)
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(8 << 20), b''):
            h.update(block)
    return {'name': path.name, 'size': path.stat().st_size, 'sha256': h.hexdigest()}


def check_counts(tags):
    counts = Counter(row['class'] for row in tags.values())
    for cls, expected in EXPECTED.items():
        if abs(counts[cls] / expected - 1) > 0.02:
            raise ValueError('vocabulary count outside 2 percent: %s=%d' % (cls, counts[cls]))
    return dict(counts)


def json_bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      indent=None, separators=(',', ':'), allow_nan=False).encode('utf-8')


SLOTS9 = ['HEAD', 'NECK', 'OUTFIT', 'BODY', 'TOP', 'UNDER', 'WAIST', 'BOTTOM', 'ARMS', 'LEGS', 'FEET']
CAP = {'HEAD': 3, 'NECK': 2, 'OUTFIT': 2, 'BODY': 1, 'TOP': 3, 'UNDER': 2, 'WAIST': 1, 'BOTTOM': 2, 'ARMS': 2, 'LEGS': 2, 'FEET': 1}
NOUN = {}
for slot, words in {
    'HEAD': 'hat cap beret headdress hairband headband helmet crown tiara veil hood earrings glasses eyewear goggles mask ornament hairclip '
            'circlet headgear headwear hachimaki ears horns headpiece kanzashi bandana visor sunglasses monocle headset earmuffs halo',
    'NECK': 'choker necktie bowtie scarf collar necklace ascot neckerchief cravat jabot pendant ruff stole',
    'OUTFIT': 'uniform suit gakuran serafuku costume outfit maid butler nurse witch miko nun bunny tuxedo cheerleader waitress clothes',
    'BODY': 'dress gown kimono yukata robe habit hanfu leotard bodysuit swimsuit bikini playsuit unitard jumpsuit overalls romper bodystocking '
            'armor cheongsam sundress pajamas qipao',
    'TOP': 'shirt blouse jacket coat sweater cardigan vest hoodie top camisole cape capelet cloak poncho shawl haori parka blazer apron tunic '
           'tabard happi jersey waistcoat pauldrons pauldron breastplate corset bolero hanten raincoat windbreaker',
    'UNDER': 'bra panties thong underwear lingerie g-string pasties maebari sarashi negligee chemise babydoll',
    'WAIST': 'belt sash obi suspenders',
    'BOTTOM': 'skirt miniskirt microskirt pants shorts jeans trousers hakama buruma bloomers fundoshi trunks briefs curtain loincloth sarong '
              'culottes slacks sweatpants leggings-shorts',
    'ARMS': 'gloves glove gauntlets gauntlet sleeves bracelet bracelets cuffs armband armlet bracer bracers vambraces kote kurokote mittens',
    'LEGS': 'thighhighs pantyhose socks kneehighs leggings warmers stockings legwear strap anklet thighlet tabi',
    'FEET': 'shoes boots heels sandals sneakers loafers slippers geta zouri footwear janes pumps zori clogs',
}.items():
    for w in words.split():
        NOUN[w] = slot
NOUN['bottom'] = 'BOTTOM'; NOUN['bottoms'] = 'BOTTOM'
KIND = {'tabi': 'socks', 'miniskirt': 'skirt','microskirt': 'skirt', 'bracelets': 'bracelet', 'gauntlet': 'gauntlets', 'glove': 'gloves',
        'pauldron': 'pauldrons', 'bracer': 'bracers'}
D3SLOT = {
    ('attire', 'Headwear and Headgear'): 'HEAD', ('neck_and_neckwear', 'Detached Neckwear'): 'NECK', ('neck_and_neckwear', 'Chokers'): 'NECK',
    ('neck_and_neckwear', 'Necklaces'): 'NECK', ('neck_and_neckwear', 'Scarves'): 'NECK', ('neck_and_neckwear', 'Collared clothes'): 'TOP',
    ('attire', 'Shirts and Topwear'): 'TOP', ('attire', 'Pants and Bottomwear'): 'BOTTOM', ('attire', 'Legs and Feet'): 'LEGS',
    ('attire', 'Shoes and Footwear'): 'FEET', ('handwear', 'Gloves'): 'ARMS', ('handwear', 'Other handwear'): 'ARMS',
    ('sexual_attire', 'Lingerie'): 'UNDER', ('attire', 'Swimsuits and Bodysuits'): 'BODY', ('attire', 'Uniforms and Costumes'): 'OUTFIT',
    ('attire', 'Traditional Clothing'): 'OUTFIT', ('accessories', 'By body part · Head'): 'HEAD', ('accessories', 'By body part · Neck'): 'NECK',
    ('accessories', 'By body part · Arms'): 'ARMS', ('accessories', 'By body part · Legs'): 'LEGS', ('list_of_armor', 'Head'): 'HEAD',
    ('list_of_armor', 'Shoulders'): 'TOP', ('list_of_armor', 'Torso'): 'TOP', ('list_of_armor', 'Arms'): 'ARMS', ('list_of_armor', 'Legs'): 'LEGS',
    ('list_of_armor', 'Sets'): 'BODY', ('eyewear', 'Main'): 'HEAD', ('eyewear', 'Glasses'): 'HEAD', ('eyewear', 'Sunglasses'): 'HEAD',
    ('mask', 'Related tags · Types'): 'HEAD', ('mask', 'Related tags · Locations'): 'HEAD', ('mask', 'Related tags · Animals'): 'HEAD',
    ('fashion_style', 'J-Fashion'): 'OUTFIT', ('fashion_style', 'Cultural styles'): 'OUTFIT', ('fashion_style', 'Historical styles'): 'OUTFIT',
    ('fashion_style', 'Western fashion styles'): 'OUTFIT', ('fashion_style', 'Other Asian fashion styles'): 'OUTFIT',
}
for k in ['Types', 'Hats', 'Helmets', 'Crowns', 'Other', 'Non-specific styles', 'Accessories', 'Not headwear']:
    D3SLOT[('headwear', k)] = 'HEAD'
STRONG_MOD = {('fashion_style', 'General'), ('fashion_style', 'Decades'), ('attire', 'Fit and garment construction'),
              ('attire', 'Clothing states and adjustments'), ('sexual_attire', 'Exposure'), ('sleeves', 'Length'), ('sleeves', 'Trim'),
              ('sleeves', 'Actions'), ('sleeves', 'Miscellaneous'), ('neck_and_neckwear', 'Neckwear actions'), ('handwear', 'Glove interactions'),
              ('headwear', 'Actions / states'), ('mask', 'Related tags · Actions'), ('mask', 'Related tags · State'),
              ('mask', 'Related tags · Materials'), ('eyewear', 'Eyewear')}
WEAK_MOD = {('accessories', 'Decorations'), ('attire', 'Other')}
HAND_MOD = {'lapels', 'plunging neckline', 'halloween costume', 'eyewear on head', 'high collar', 'halterneck', 'v-neck', 'jewelry',
            'collarbone', 'cleavage', 'turtleneck', 'sleeveless', 'buttons', 'double-breasted', 'zipper', 'pocket', 'hood down', 'hood up',
            'meme attire'}
PATTERN = {'checkered', 'striped', 'plaid', 'polka', 'argyle', 'houndstooth', 'camouflage', 'floral', 'print', 'vertical-striped',
           'horizontal-striped', 'leopard', 'tiger', 'cow', 'animal', 'star', 'heart'}
NAMED_D3 = {('attire', 'Uniforms and Costumes'), ('attire', 'Traditional Clothing'), ('attire', 'Swimsuits and Bodysuits'), ('list_of_armor', 'Sets'),
            ('fashion_style', 'J-Fashion'), ('fashion_style', 'Cultural styles'), ('fashion_style', 'Historical styles'),
            ('fashion_style', 'Western fashion styles'), ('fashion_style', 'Other Asian fashion styles')}
PLAIN_D3 = {('attire', 'Shirts and Topwear'), ('attire', 'Pants and Bottomwear'), ('attire', 'Legs and Feet'), ('attire', 'Shoes and Footwear'),
            ('attire', 'Headwear and Headgear')}
STATE_RE = re.compile(r'^(open|torn|wet|unbuttoned|unzipped|unworn|removed|adjusting|untied|no|partially|loose|lifted|holding) |'
                      r' (lift|pull|aside|tug|grab|removed|down|around waist|on head|over eyes)$')
METAL = ('gold ', 'silver ')


def is_color(name, flagged, colors):
    word = name.split(' ')[0]
    return bool((flagged or word in colors or word.split('-')[0] in colors)
                and not name.startswith(METAL))


def classify(t, pos, old):
    b = t
    for metal in METAL:
        if b.startswith(metal):
            b = b[len(metal):]
            break
    if STATE_RE.search(b):
        return {'class': 'state', 'why': 'state_regex'}
    if b in HAND_MOD:
        return {'class': 'modifier', 'why': 'hand'}
    ps = pos.get(b, set())
    strong = sorted(ps & STRONG_MOD)
    if strong:
        return {'class': 'modifier', 'why': 'd3:' + '/'.join(strong[0])}
    words = b.split(' ')
    if words[-1] == 'clothes' and len(words) > 1 and words[0] in PATTERN:
        return {'class': 'modifier', 'why': 'pattern'}
    noun = NOUN.get(words[-1])
    if b.startswith('hair ') or b.endswith(' hair ornament'):
        noun = 'HEAD'
    elif b.startswith('neck ') and noun is None:
        noun = 'NECK'
    if ps and ps <= WEAK_MOD and noun is None:
        return {'class': 'modifier', 'why': 'decoration'}
    if noun:
        return {'class': 'garment', 'slot': noun, 'why': 'noun'}
    # Stable ordering resolves prototype set-iteration ambiguity.
    for p in sorted(ps):
        if p in D3SLOT:
            return {'class': 'garment', 'slot': D3SLOT[p], 'why': 'd3:' + '/'.join(p)}
    if old.get(b):
        return {'class': 'garment', 'slot': old[b], 'why': 'region6'}
    return {'class': 'noslot', 'why': 'no_slot'}


def main(argv=None):
    import pandas as pd
    from core.event_map.index import EventMapIndex
    from core.event_map.attire import attire_classifier
    from core.event_map.tree import TREE_PATH

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--map', default=MAP)
    ap.add_argument('--region6', type=Path, default=ROOT / 'core/clothes_preset/naia_clothes_preset')
    ap.add_argument('--overrides', type=Path, default=DATA / 'outfit_vocab_overrides.json')
    ap.add_argument('--out', type=Path, default=DATA / 'outfit_vocab.json')
    args = ap.parse_args(argv)
    overrides = json.loads(args.overrides.read_text(encoding='utf-8'))
    global HAND_MOD, PATTERN
    HAND_MOD = set(overrides.get('hand_modifiers', HAND_MOD))
    PATTERN = set(overrides.get('patterns', PATTERN))
    tree = json.loads(Path(TREE_PATH).read_text(encoding='utf-8'))
    pos = defaultdict(set)
    for d1 in tree['d1']:
        for d2 in d1['d2']:
            for d3 in d2.get('d3', []):
                for tag in d3.get('tags', []):
                    pos[tag].add((d2['id'].replace('tag_group:', ''), d3['id']))
    for ps in pos.values():
        if any(g == 'nudity' for g, _ in ps):
            ps.add(('fashion_style', 'General'))
    if zipfile.is_zipfile(args.region6):
        with zipfile.ZipFile(args.region6) as z:
            r6 = pd.read_parquet(io.BytesIO(z.read('clothing_region6_mapping_step42.parquet')))
    else:
        r6 = pd.read_parquet(args.region6)
    regions = {'HEAD_NECK_FACE': 'HEAD', 'UPPER_BODY': 'TOP', 'WAIST_HIP': 'BOTTOM',
               'ARMS_HANDS': 'ARMS', 'LEGS': 'LEGS', 'FEET': 'FEET'}
    old = {t: regions.get(s) for t, s in zip(r6.clothing_tag, r6.region6)}
    ix = EventMapIndex(args.map)
    try:
        ac = attire_classifier()
        eligible = [(i, n) for i, n in ix.by_id.items()
                    if ix.observed.get(i, 0) >= 30 and ac.is_attire(n)]
        first = Counter(n.split(' ')[0] for i, n in eligible if ix.color_arr[i])
        colors = {w for w, n in first.items() if n >= 8} - {'gold', 'silver'}
        tags = {}
        for i, n in eligible:
            if is_color(n, ix.color_arr[i], colors):
                tags[n] = {'class': 'color', 'why': 'color'}
            else:
                tags[n] = classify(n, pos, old)
        for tag, row in overrides['tags'].items():
            tags[tag] = dict(row)
        for tag, row in tags.items():
            if row['class'] not in EXPECTED or (row['class'] == 'garment' and row.get('slot') not in CAP):
                raise ValueError('invalid override: ' + tag)
            ps = pos.get(tag, set())
            row['named_candidate'] = bool(row['class'] == 'garment' and (
                ((row['slot'] in ('OUTFIT', 'BODY') or ps & NAMED_D3) and not ps & PLAIN_D3)
                or row.get('why') == 'role' or tag == 'wedding dress'))
        counts = check_counts(tags)
        result = {'schema': 'naia.outfit_vocab.v1',
                  'built_at': datetime.now(timezone.utc).isoformat(),
                  'inputs': {k: fingerprint(p) for k, p in {
                      'map': args.map, 'tree': TREE_PATH, 'region6': args.region6,
                      'overrides': args.overrides}.items()},
                  'slots': CAP, 'slot_order': SLOTS9, 'kind_alias': KIND, 'tags': tags}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(json_bytes(result))
        log('class_counts ' + json.dumps(counts, sort_keys=True))
    finally:
        ix.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        log('ERROR: ' + str(exc))
        sys.exit(1)
