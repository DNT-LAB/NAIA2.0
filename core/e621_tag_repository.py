"""Lazy E621 dictionary/translation/classification storage boundary.

App-owned bundled data takes precedence over runtime copies. Dictionary and taxonomy
are read from e621_data. Tools may prefer translation JSON over Parquet.
An invalid selected source fails
closed instead of silently serving a different revision from another root.
Relations and observations are not repositories in this stage; existing
research annotations remain an unchanged display-only metadata adapter.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.site_tag_repository import LegacyTagRepository, SiteTagKey, TagClassificationRepository

# 표준 json 으로 읽는다. pandas 의 비공개 ujson_loads 는 80ms 빨랐지만 행마다 키 문자열을
# 공유하지 않아 상주 메모리가 30MiB 더 남았다(10-03 실측: 63.5 -> 94.0MiB) - 모듈을 처음 열 때
# 한 번 아끼는 시간과 바꿀 값이 아니다.


class SiteTranslationRepository:
    def __init__(self, site: str, metadata: Any):
        self.site = site
        self.legacy_metadata = metadata

    def get(self, key: SiteTagKey) -> dict[str, Any] | None:
        if key.site != self.site or key.exact_tag not in self.legacy_metadata._native:
            return None
        return self.legacy_metadata.for_tag(key.exact_tag)


class E621TagRepository:
    """Construction never reads or hashes any vocabulary or translation file."""

    def __init__(self, repo_root: Path, *, data_roots: list[Path] | None = None, prefer_catalog: bool = False):
        self.repo_root = Path(repo_root).resolve()
        roots = [self.repo_root / "data", *(data_roots or [])]
        self.data_roots = list(dict.fromkeys(
            root if root.is_absolute() else self.repo_root / root for root in map(Path, roots)
        ))
        self.dictionary: LegacyTagRepository | None = None
        self.classification: TagClassificationRepository | None = None
        self.translations: SiteTranslationRepository | None = None
        self.source_path: Path | None = None
        self.source_format: str | None = None
        self.last_error: str | None = None
        self.manifest: dict[str, Any] | None = None
        self.prefer_catalog = prefer_catalog

    @property
    def loaded(self) -> bool:
        return self.dictionary is not None

    def load(self) -> bool:
        if self.loaded:
            return True
        self.last_error = None
        for root in self.data_roots:
            catalog = root / "e621_catalog"
            legacy = root / "e621_data"
            source = legacy
            if not source.exists():
                continue
            try:
                tree = json.loads(legacy.read_bytes())
                rows, manifest, source_format = None, None, "legacy_json"
                if self.prefer_catalog:
                    from core.e621_catalog_format import load_catalog

                    rows, manifest = load_catalog(catalog)
                dictionary = LegacyTagRepository("e621", tree)
                from core.e621_research_metadata import E621ResearchMetadata

                metadata = E621ResearchMetadata(self.repo_root, dictionary.rows,
                    data_roots=self.data_roots, translation_rows=rows)
                # Publish a complete revision only after every component loaded.
                self.dictionary = dictionary
                self.classification = TagClassificationRepository(dictionary)
                self.translations = SiteTranslationRepository("e621", metadata)
                self.source_path, self.source_format, self.manifest = source, source_format, manifest
                return True
            except (OSError, ValueError, TypeError, KeyError) as exc:
                self.last_error = type(exc).__name__ + ": " + str(exc)
                return False
        return False

    def get(self, key: SiteTagKey) -> dict[str, Any] | None:
        if key.site != "e621" or not self.load():
            return None
        return self.dictionary.get(key)
