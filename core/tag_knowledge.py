from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping


_HANGUL_RE = re.compile(r"[가-힣]")


def has_hangul(text: Any) -> bool:
    return bool(_HANGUL_RE.search(str(text or "")))


def normalize_tag_key(tag: Any) -> str:
    return " ".join(
        str(tag)
        .replace("\\(", "(")
        .replace("\\)", ")")
        .replace("_", " ")
        .strip()
        .lower()
        .split()
    )


def normalize_display_tag(tag: Any) -> str:
    return " ".join(
        str(tag)
        .replace("\\(", "(")
        .replace("\\)", ")")
        .replace("_", " ")
        .strip()
        .split()
    )


@dataclass
class ParquetTagMergeStats:
    added: int = 0
    records_updated: int = 0
    count_filled: int = 0
    description_filled: int = 0
    description_replaced: int = 0
    keywords_filled: int = 0
    keywords_replaced: int = 0
    body_translations_skipped: int = 0
    missing_sources: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class RatingCountMergeStats:
    path: str = ""
    records_seen: int = 0
    records_updated: int = 0
    missing_path: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass
class TranslationOverrideStats:
    records_seen: int = 0
    added: int = 0
    updated: int = 0
    description_applied: int = 0
    keywords_applied: int = 0
    missing_path: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def applied(self) -> int:
        return self.added + self.updated


def _refresh_lookup_fields(record: MutableMapping[str, Any]) -> None:
    description = str(record.get("description", "") or "")
    keywords = str(record.get("keywords_kr", "") or "")
    record["_desc_lower"] = description.lower()
    record["_kw_lower"] = keywords.replace("<", "").replace(">", "").lower() if keywords else ""


@dataclass
class SupplementIndex:
    """한국어 보강(별칭 · 키워드) 둘이 함께 쓰는 색인 — 정규 태그 -> 레코드들 · 붙여 쓴 한국어 키워드 -> 가진 태그들.

    보강마다 19만 태그의 키워드를 다시 정규화해 색인을 만들었다(두 번 · normalize 187만 번 · NAIA 를 켜고 첫 이름 칩까지
    20초 제보에서 실측 09-26). 한 번 만들고, 보강이 실제로 붙인 별칭만 더해 다음 보강이 그대로 쓴다 — 다시 만든 것과 같다."""

    records: dict[str, list]
    owners: dict[str, set]


def build_supplement_index(raw) -> SupplementIndex:
    from collections import defaultdict

    records, owners = defaultdict(list), defaultdict(set)
    for key, record in raw.items():
        tag = normalize_tag_key(record.get("_tag") or key)
        records[tag].append(record)
        for field_name in ("keywords_kr", "keywords"):
            for part in str(record.get(field_name) or "").split(","):
                keyword = normalize_tag_key(part.replace("<", "").replace(">", ""))
                if has_hangul(keyword):
                    owners[keyword.replace(" ", "")].add(tag)
    return SupplementIndex(records, owners)


def _apply_korean_supplement(
    raw,
    path: str | Path,
    *,
    expected_kind: str,
    source_name: str,
    evidence_field: str,
    index: SupplementIndex | None = None,
) -> dict[str, Any]:
    """Apply a bounded, additive Korean keyword supplement.

    Both the reviewed lexical supplement and the extracted Danbooru keyword
    supplement use the same runtime safety checks. In particular, a compiled
    file may not override the active corpus: canonical tags are rechecked and
    compact Korean spellings that already belong to another tag are skipped.
    """
    from collections import defaultdict

    stats = {"tags": 0, "aliases": 0, "missing_tags": 0, "collisions": 0, "errors": []}
    path = Path(path)
    if not path.exists():
        return stats
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (payload.get("schema_version") != 1 or
                payload.get("kind") != expected_kind or
                payload.get("semantic_certified") is not False or
                not isinstance(payload.get("translations"), dict)):
            raise ValueError(f"invalid {source_name} schema")
        proposals = []
        for tag, value in payload["translations"].items():
            if normalize_tag_key(tag) != tag or not isinstance(value, dict):
                raise ValueError(f"invalid canonical tag: {tag!r}")
            aliases = value.get("aliases")
            if not isinstance(aliases, list) or not 1 <= len(aliases) <= 12:
                raise ValueError(f"invalid aliases for {tag!r}")
            for item in aliases:
                alias, basis = item.get("text"), item.get("basis")
                if (not isinstance(alias, str) or not has_hangul(alias) or
                        alias != normalize_tag_key(alias) or len(alias) > 160 or
                        any(c in alias for c in ",<>\n\r") or not isinstance(basis, list) or
                        not basis or not all(isinstance(b, str) and 0 < len(b) <= 160 for b in basis)):
                    raise ValueError(f"invalid alias evidence for {tag!r}")
                proposals.append((tag, alias, basis))
    except Exception as exc:
        stats["errors"].append(f"{path}: {exc}")
        return stats
    index = index or build_supplement_index(raw)
    records, owners = index.records, index.owners
    # 이번 보강이 내놓은 별칭 — 충돌 판정에만 쓴다(색인에는 실제로 붙인 것만 남겨 다음 보강이 다시 만든 색인과 같게)
    proposed = defaultdict(set)
    for tag, alias, _ in proposals:
        if tag in records:
            proposed[alias.replace(" ", "")].add(tag)
    changed = set()
    for tag, alias, basis in proposals:
        if tag not in records:
            stats["missing_tags"] += 1
            continue
        alias_key = alias.replace(" ", "")
        if (owners.get(alias_key, set()) | proposed.get(alias_key, set())) - {tag}:
            stats["collisions"] += 1
            continue
        record = records[tag][0]
        existing = {normalize_tag_key(k.replace("<", "").replace(">", ""))
                    for r in records[tag] for field_name in ("keywords_kr", "keywords")
                    for k in str(r.get(field_name) or "").split(",")}
        if alias in existing:
            continue
        previous = str(record.get("keywords_kr") or "")
        record["keywords_kr"] = previous + (", " if previous.strip() else "") + alias
        record.setdefault(evidence_field, {})[alias] = {
            "source": source_name, "version": payload.get("version"), "basis": basis}
        _refresh_lookup_fields(record)
        owners[alias_key].add(tag)            # 이제 keywords_kr 에 있다 — 다시 만든 색인과 같게
        changed.add(tag)
        stats["aliases"] += 1
    stats["tags"] = len(changed)
    return stats


def apply_korean_alias_supplement(raw, path: str | Path, *,
                                  index: SupplementIndex | None = None) -> dict[str, Any]:
    """Append reviewed lexical aliases without replacing metadata."""
    return _apply_korean_supplement(
        raw,
        path,
        expected_kind="korean_lexical_alias_supplement",
        source_name="korean_lexical_supplement",
        evidence_field="_korean_alias_sources",
        index=index,
    )


def apply_korean_keyword_supplement(raw, path: str | Path, *,
                                    index: SupplementIndex | None = None) -> dict[str, Any]:
    """Append bounded aliases extracted from classified tag keywords."""
    return _apply_korean_supplement(
        raw,
        path,
        expected_kind="korean_keyword_supplement",
        source_name="danbooru_keyword_supplement",
        evidence_field="_korean_keyword_sources",
        index=index,
    )


def apply_korean_slang_supplement(raw, path: str | Path, *,
                                  index: SupplementIndex | None = None) -> dict[str, Any]:
    """손으로 고른 속어 키워드(검스 -> black pantyhose · 얼싸 -> facial)를 덧붙인다 — 자동으로 만든 두 보충(csv · 규칙표)은
    산출물이라 손 항목을 섞지 않는다(다시 만들면 사라진다). 같은 안전 검사: 태그를 만들지 않고, 다른 태그의 키워드와 겹치면
    건너뛴다(사용자 결정 2026-09-29 — Assist 되살리기가 속어를 영어로 잘못 풀었다: 검스 -> weapon · 발코키 -> stockings)."""
    return _apply_korean_supplement(
        raw,
        path,
        expected_kind="korean_slang_supplement",
        source_name="hand_slang_supplement",
        evidence_field="_korean_slang_sources",
        index=index,
    )


def _merge_text_field(
    record: MutableMapping[str, Any],
    *,
    field_name: str,
    candidate: str,
    replace_non_korean: bool,
) -> str | None:
    candidate = str(candidate or "")
    if not candidate.strip():
        return None

    existing = str(record.get(field_name, "") or "")
    if not existing.strip():
        record[field_name] = candidate
        return "filled"
    if replace_non_korean and has_hangul(candidate) and not has_hangul(existing):
        record[field_name] = candidate
        return "replaced"
    return None


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _fill_missing_count(
    record: MutableMapping[str, Any],
    count: Any,
    *,
    source: str,
) -> bool:
    candidate = _coerce_int(count)
    if candidate <= 0:
        return False
    current = _coerce_int(record.get("freq", record.get("count", 0)))
    if current > 0:
        return False
    record["freq"] = candidate
    record["_count_source"] = source
    return True


def merge_parquet_tag_records(
    raw: MutableMapping[str, MutableMapping[str, Any]],
    parquet_sources: Iterable[tuple[str | Path, int]],
    *,
    source_allowlists: Mapping[int, Iterable[str]] | None = None,
    body_translation_sources: Iterable[int] = (),
) -> ParquetTagMergeStats:
    """Merge KR parquet tag metadata into interactive tag records.

    `interactive` remains the structural source for relations and UI grouping.
    Korean parquet metadata is allowed to fill empty fields and replace English
    descriptions/keywords, because those fields are user-facing in Web Remote.

    `body_translation_sources` = 키워드 없는 행이 '위키 본문을 통째로 옮긴 번역' 인 표의 src 키(e621 = 2).
    그런 행은 읽기용이라 공용 어휘에 싣지 않는다(사용자 지정 2026-10-04) - 실으면 메인 자동완성 · Assist 가 보는
    설명 9,938개가 마크업 섞인 긴 위키 번역으로 바뀌고, 한국어 검색에 본문 속 낱말이 걸린다.
    """

    stats = ParquetTagMergeStats()

    try:
        import pandas as pd
    except Exception as exc:  # pragma: no cover - environment failure
        stats.errors.append(f"pandas import failed: {exc}")
        return stats

    body_translation_sources = set(body_translation_sources)
    for pq_path, src_key in parquet_sources:
        normalized_allowlist = None
        if source_allowlists is not None and src_key in source_allowlists:
            normalized_allowlist = {normalize_tag_key(tag) for tag in source_allowlists[src_key]}
        path = Path(pq_path)
        if not path.exists():
            stats.missing_sources.append(str(path))
            continue
        try:
            columns = ["tag", "count", "category", "desc", "keywords"]
            if src_key in body_translation_sources:
                # 번역 본문 행(키워드 없음)은 읽을 때부터 거른다 - 2만6천 개의 긴 글을 풀었다 버리면 기동 때 40MB 를 더 쓴다.
                # 아래 줄 단위 검사는 그대로 둔다(공백뿐인 키워드 등).
                skipped_at_read = pd.read_parquet(path, columns=["keywords"])["keywords"].fillna("").eq("").sum()
                stats.body_translations_skipped += int(skipped_at_read)
                df = pd.read_parquet(path, columns=columns, filters=[("keywords", "!=", "")])
            else:
                df = pd.read_parquet(path, columns=columns)
        except Exception as exc:
            stats.errors.append(f"{path}: {exc}")
            continue

        # iterrows 는 줄마다 Series 를 만들어 3.9만 줄에 1초가 넘었다 — 값은 아래에서 전부 str/int 로 바꿔 쓰므로 dict 로 읽는다
        for row in df.to_dict("records"):
            tag_raw = normalize_display_tag(row["tag"])
            tag_lower = normalize_tag_key(tag_raw)
            if normalized_allowlist is not None and tag_lower not in normalized_allowlist:
                continue
            keywords = str(row.get("keywords", "") or "")
            description = str(row.get("desc", "") or "")
            if src_key in body_translation_sources and not keywords.strip():
                stats.body_translations_skipped += 1
                continue

            if tag_lower in raw:
                existing = raw[tag_lower]
                updated = False

                if _fill_missing_count(existing, row.get("count", 0), source=str(path)):
                    stats.count_filled += 1
                    updated = True

                desc_action = _merge_text_field(
                    existing,
                    field_name="description",
                    candidate=description,
                    replace_non_korean=True,
                )
                if desc_action == "filled":
                    stats.description_filled += 1
                    updated = True
                elif desc_action == "replaced":
                    stats.description_replaced += 1
                    updated = True

                kw_action = _merge_text_field(
                    existing,
                    field_name="keywords_kr",
                    candidate=keywords,
                    replace_non_korean=True,
                )
                if kw_action == "filled":
                    stats.keywords_filled += 1
                    updated = True
                elif kw_action == "replaced":
                    stats.keywords_replaced += 1
                    updated = True

                if updated:
                    existing["_translation_source"] = str(path)
                    existing["_kr_category"] = str(row.get("category", "") or "")
                    _refresh_lookup_fields(existing)
                    stats.records_updated += 1
                continue

            entry: dict[str, Any] = {
                "_tag": tag_raw,
                "_src": src_key,
                "freq": int(row.get("count", 0) or 0),
                "description": description,
                "group": str(row.get("category", "") or ""),
                "subgroup": "",
                "keywords_kr": keywords,
                "_translation_source": str(path),
                "_kr_category": str(row.get("category", "") or ""),
            }
            if src_key == 2:
                entry["_cat"] = "e621"
            _refresh_lookup_fields(entry)
            raw[tag_lower] = entry
            stats.added += 1

        if src_key in body_translation_sources:
            # 걸러 낸 번역 본문 열을 풀 때 Arrow 가 잡은 메모리를 돌려준다. 안 하면 기동 뒤에도 30MB 쯤이 남는다
            # (실측 2026-10-04: 읽은 직후 +59MB → 돌려준 뒤 +27MB, 한글화 전 +18MB).
            del df
            try:
                import pyarrow

                pyarrow.default_memory_pool().release_unused()
            except Exception:
                pass

    return stats


def merge_e621_research_records(
    raw: MutableMapping[str, MutableMapping[str, Any]],
    data_path: str | Path,
    src_key: int = 14,
) -> ParquetTagMergeStats:
    """Temporarily limit shared E621 vocabulary until the site-aware index lands.

    In the reviewed expansion, all new unreviewed rows are in the two
    unclassified folders. Curated folders plus the pre-expansion 'domestic'
    exception equal all 20,980 original tags and 100 reviewed additions.
    The research module still reads the full dictionary independently.
    Keep existing shared records (including their frequency/description) and
    omit wiki bodies. This rule is temporary, not a semantic approval heuristic
    for future bulk imports; revalidate the bounded vocabulary before expansion.
    """
    stats = ParquetTagMergeStats()
    path = Path(data_path)
    if not path.exists():
        stats.missing_sources.append(str(path))
        return stats
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        stats.errors.append(f"{path}: {exc}")
        return stats

    def walk(node: Any, group: str, unclassified: bool = False) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, str(key), unclassified or key in {"일반 미분류", "종 미분류"})
            return
        if not isinstance(node, list):
            return
        for item in node:
            if not isinstance(item, dict) or "tag" not in item:
                continue
            if unclassified and item["tag"] != "domestic":
                continue
            tag_raw = normalize_display_tag(item.get("tag"))
            tag_lower = normalize_tag_key(tag_raw)
            if not tag_lower or tag_lower in raw:
                continue
            try:
                freq = int(item.get("count") or 0)
            except (TypeError, ValueError):
                freq = 0
            korean = str(item.get("kor") or "").strip()
            entry: dict[str, Any] = {
                "_tag": tag_raw,
                "_src": src_key,
                "_cat": "e621",
                "freq": freq,
                "description": "",
                "group": group,
                "subgroup": "",
                "keywords_kr": korean,
                "_translation_source": str(path),
            }
            _refresh_lookup_fields(entry)
            raw[tag_lower] = entry
            stats.added += 1

    walk(payload, "e621")
    return stats

def merge_rating_count_records(
    raw: MutableMapping[str, MutableMapping[str, Any]],
    counts_path: str | Path,
) -> RatingCountMergeStats:
    stats = RatingCountMergeStats(path=str(counts_path))
    path = Path(counts_path)
    if not path.exists():
        stats.missing_path = True
        return stats

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        stats.errors.append(f"{path}: {exc}")
        return stats

    if not isinstance(payload, dict):
        stats.errors.append(f"{path}: expected object")
        return stats

    for raw_tag, value in payload.items():
        if raw_tag == "_meta":
            continue
        stats.records_seen += 1
        tag_lower = normalize_tag_key(raw_tag)
        record = raw.get(tag_lower)
        if record is None:
            continue
        if isinstance(value, list):
            total = sum(_coerce_int(item) for item in value)
        elif isinstance(value, dict):
            total = sum(_coerce_int(item) for item in value.values())
        else:
            total = _coerce_int(value)
        if _fill_missing_count(record, total, source=str(path)):
            stats.records_updated += 1

    return stats


def apply_translation_overrides(
    raw: MutableMapping[str, MutableMapping[str, Any]],
    overrides_path: str | Path,
) -> TranslationOverrideStats:
    stats = TranslationOverrideStats()
    path = Path(overrides_path)
    if not path.exists():
        stats.missing_path = True
        return stats

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        stats.errors.append(f"{path}: {exc}")
        return stats

    translations = payload.get("translations", {})
    if not isinstance(translations, dict):
        stats.errors.append(f"{path}: translations must be an object")
        return stats

    for raw_tag, value in translations.items():
        if not isinstance(value, dict):
            stats.errors.append(f"{path}: invalid override for {raw_tag!r}")
            continue
        stats.records_seen += 1

        tag = normalize_display_tag(raw_tag)
        tag_lower = normalize_tag_key(raw_tag)
        record = raw.get(tag_lower)
        added = False
        if record is None:
            record = {
                "_tag": tag,
                "_src": int(value.get("src", 20) or 20),
                "freq": int(value.get("freq", 0) or 0),
                "description": "",
                "group": str(value.get("group", "") or ""),
                "subgroup": str(value.get("subgroup", "") or ""),
                "keywords_kr": "",
            }
            raw[tag_lower] = record
            added = True

        description = str(value.get("description", "") or "")
        if description.strip():
            record["description"] = description
            stats.description_applied += 1
        keywords = str(value.get("keywords_kr", value.get("keywords", "")) or "")
        if keywords.strip():
            record["keywords_kr"] = keywords
            stats.keywords_applied += 1

        if value.get("group") and not record.get("group"):
            record["group"] = str(value.get("group") or "")
        if value.get("subgroup") and not record.get("subgroup"):
            record["subgroup"] = str(value.get("subgroup") or "")
        record["_translation_override_source"] = str(value.get("source", path.as_posix()))
        _refresh_lookup_fields(record)

        if added:
            stats.added += 1
        else:
            stats.updated += 1

    return stats
