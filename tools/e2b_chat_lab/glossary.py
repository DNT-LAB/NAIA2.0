"""Optional, provenance-labelled English descriptions. Never modifies NAIA assets."""
import json
from collections import defaultdict
from tools.e2b_chat_lab.retrieval import english_words, stem
from pathlib import Path
from core.tag_axis_registry import normalize_tag


class Glossary:
    def __init__(self, path):
        self.path = Path(path)
        self.rows, self.duplicates = {}, set()
        self.error = ''
        try:
            with self.path.open(encoding='utf-8') as stream:
                for line in stream:
                    row = json.loads(line)
                    key = normalize_tag(row['tag'])
                    if key in self.rows:
                        self.duplicates.add(key)
                    self.rows[key] = row
        except Exception as exc:
            self.rows.clear()
            self.error = str(exc)
        self.english_index = defaultdict(set)
        for key, row in self.rows.items():
            if key in self.duplicates or row.get('quality_flags') or row.get('translation_status') != 'translated':
                continue
            for word in set(stem(w) for w in english_words(row.get('description_en', ''))):
                self.english_index[word].add(key)

    def search(self, query, limit=4):
        """English descriptions supplement names; callers must verify canonical tags."""
        words = set(stem(w) for w in english_words(query))
        if len(words) < 2:
            return []
        scores = defaultdict(int)
        for word in words:
            for tag in self.english_index.get(word, ()):
                scores[tag] += 1
        ranked = sorted((tag for tag, score in scores.items() if score >= 2 and score / len(words) >= .6),
                        key=lambda tag: (-scores[tag], len(self.rows[tag].get('description_en', '')), tag))
        return ranked[:limit]

    def describe(self, row):
        key = normalize_tag(row['tag'])
        source = self.rows.get(key)
        if not source or key in self.duplicates:
            return row | {'description_en': '', 'translation_status': 'ambiguous_key' if key in self.duplicates else 'unavailable'}
        flags = list(source.get('quality_flags') or [])
        normalized = lambda s: ' '.join(str(s or '').split())
        if normalized(row.get('desc')) != normalized(source.get('description_ko')):
            flags.append('current_description_differs')
        return row | {'description_en': source.get('description_en') or '',
                      'translation_status': 'needs_review' if flags else source.get('translation_status', 'unknown'),
                      'quality_flags': flags, 'translation_source': source.get('translation_source', '')}

    def state(self):
        return {'ready': bool(self.rows), 'count': len(self.rows), 'ambiguous_keys': len(self.duplicates),
                'path': str(self.path), 'error': self.error}
