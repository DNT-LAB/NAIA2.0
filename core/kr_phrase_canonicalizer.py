from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KR_PHRASE_CANONICAL_RULES_PATH = (
    PROJECT_ROOT / "data" / "tag_index" / "kr_phrase_canonical_rules.json"
)
_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class KrPhraseCanonicalMatch:
    tag: str
    confidence: float
    rule_id: str
    axis: str


def normalize_kr_phrase(value: Any) -> str:
    text = str(value or "").replace("_", " ").strip().lower()
    text = re.sub(r"[^\w가-힣ㄱ-ㅎㅏ-ㅣ]+", " ", text)
    return _SPACE_RE.sub(" ", text).strip()


def _compact(value: str) -> str:
    return value.replace(" ", "")


def _value_matches(text: str, compact_text: str, value: Any) -> bool:
    normalized = normalize_kr_phrase(value)
    if not normalized:
        return False
    return normalized in text or _compact(normalized) in compact_text


def _load_rules_uncached(path: Path) -> tuple[dict[str, Any], ...]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ()
    if not isinstance(loaded, dict):
        return ()
    rules = loaded.get("rules")
    if not isinstance(rules, list):
        return ()
    return tuple(rule for rule in rules if isinstance(rule, dict))


@lru_cache(maxsize=8)
def load_kr_phrase_canonical_rules(
    path: str | Path = DEFAULT_KR_PHRASE_CANONICAL_RULES_PATH,
) -> tuple[dict[str, Any], ...]:
    return _load_rules_uncached(Path(path))


def match_kr_phrase_canonical_tags(
    query: str,
    *,
    rules: Iterable[dict[str, Any]] | None = None,
    limit: int | None = None,
) -> list[KrPhraseCanonicalMatch]:
    text = normalize_kr_phrase(query)
    if not text:
        return []
    compact_text = _compact(text)
    rule_items = tuple(rules) if rules is not None else load_kr_phrase_canonical_rules()
    matches: list[KrPhraseCanonicalMatch] = []
    seen_tags: set[str] = set()

    for rule in rule_items:
        forbidden = rule.get("forbiddenTerms") or []
        if isinstance(forbidden, str):
            forbidden = [forbidden]
        if any(_value_matches(text, compact_text, term) for term in forbidden):
            continue

        patterns = rule.get("patterns") or []
        if isinstance(patterns, str):
            patterns = [patterns]
        required = rule.get("requiredTerms") or []
        if isinstance(required, str):
            required = [required]

        has_pattern = any(_value_matches(text, compact_text, pattern) for pattern in patterns)
        has_required = bool(required) and all(
            _value_matches(text, compact_text, term)
            for term in required
        )
        if not has_pattern and not has_required:
            continue

        raw_tags = rule.get("tags") or []
        if isinstance(raw_tags, str):
            raw_tags = [raw_tags]
        try:
            confidence = float(rule.get("confidence", 0.92))
        except (TypeError, ValueError):
            confidence = 0.92
        confidence = min(max(confidence, 0.0), 1.0)
        rule_id = str(rule.get("id") or "")
        axis = str(rule.get("axis") or "")
        for raw_tag in raw_tags:
            tag = str(raw_tag or "").strip()
            if not tag or tag in seen_tags:
                continue
            seen_tags.add(tag)
            matches.append(
                KrPhraseCanonicalMatch(
                    tag=tag,
                    confidence=confidence,
                    rule_id=rule_id,
                    axis=axis,
                )
            )
            if limit is not None and len(matches) >= limit:
                return matches
    return matches
