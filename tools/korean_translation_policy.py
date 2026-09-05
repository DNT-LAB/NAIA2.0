"""Evidence-based scope exclusions for translation tooling, not runtime search."""
import json
from pathlib import Path
import re

PATH = Path(__file__).with_suffix('.json')


def load_policy():
    return json.loads(PATH.read_text(encoding='utf-8'))


def exclusion(tag, records, policy):
    if tag in policy['explicit']:
        return dict(policy['explicit'][tag])
    for row in records:
        text = str(row.get('description') or '')
        if any(re.search(p, text, re.I) for p in policy['description_patterns']):
            return {'reason': 'unusable_definition', 'evidence': text}
    return None
