"""Site-specific reading metadata for the E621 research module.

This deliberately does not use the merged autocomplete dictionary: an identically
spelled Danbooru tag can have a different meaning. Annotations are a small bundled
reading aid, never a prompt rewrite table or a source of generation instructions.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


ANNOTATION_SCHEMA = "naia.e621-research-annotations.v1"


def body_sha256(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class E621ResearchMetadata:
    def __init__(self, repo_root: Path, native_rows: list[dict[str, Any]],
                 data_roots: list[Path] | None = None,
                 translation_rows: list[dict[str, Any]] | None = None):
        self._native: dict[str, dict[str, Any]] = {}
        self._body_tags: set[str] = set()
        for row in native_rows:
            tag = str(row.get("tag") or "")
            if not tag:
                continue
            self._native.setdefault(tag, row)
            if str(row.get("wiki_body") or row.get("wiki_preview") or "").strip():
                self._body_tags.add(tag)
        # App-owned E621 assets must receive bundle updates, not remain hidden
        # behind an old runtime copy (runtime_install_manager documents this).
        base = Path(repo_root).resolve()
        self._roots = list(dict.fromkeys(
            root if root.is_absolute() else base / root
            for root in map(Path, [base / "data", *(data_roots or [])])
        ))
        self._translations: dict[str, dict[str, Any]] = {}
        self._annotations: dict[str, dict[str, Any]] = {}
        self._search_annotations: dict[str, dict[str, Any]] = {}
        self._links: dict[str, list[dict[str, Any]]] = {}
        self._stale: set[str] = set()
        self._stale_search: set[str] = set()
        self._warnings: list[str] = []
        self._metadata_available = False
        self._load_translations(translation_rows)
        self._load_annotations()
        described = {tag for tag, value in self._translations.items() if value.get("desc")}
        described.update(self._annotations)
        self._described = described
        self._searchable = {
            tag for tag in self._native
            if re.search(r"[가-힣ㄱ-ㅎㅏ-ㅣ]", " ".join(str(value or "") for value in (
                self._native[tag].get("kor"),
                self._translations.get(tag, {}).get("desc"),
                self._translations.get(tag, {}).get("keywords"),
                self._annotations.get(tag, {}).get("label"),
                self._annotations.get(tag, {}).get("description"),
                self._annotations.get(tag, {}).get("keywords"),
                self._search_annotations.get(tag, {}).get("label"),
                self._search_annotations.get(tag, {}).get("keywords"),
            )))
        }
        self._summary = {
            "total": len(self._native),
            "with_body": len(self._body_tags),
            "with_korean_description": len(described),
            "with_korean_search": len(self._searchable),
            "reviewed_korean_search": len(self._search_annotations),
            "without_description": len(self._native.keys() - self._body_tags - described),
            "reviewed_direct_definition": len(self._annotations),
            "with_cross_site_links": len(self._links),
            "metadata_available": self._metadata_available,
            "warning": " · ".join(self._warnings),
        }

    def _path(self, name: str) -> Path | None:
        return next((root / name for root in self._roots if (root / name).is_file()), None)

    def _load_translations(self, rows: list[dict[str, Any]] | None = None) -> None:
        path = self._path("e621_KR_tags.parquet") if rows is None else None
        if rows is None and path is None:
            self._warnings.append("한국어 설명 사전이 없어 설명 보유 상태를 모두 확인할 수 없습니다.")
            return
        try:
            if rows is None:
                import pyarrow.parquet as pq
                rows = pq.read_table(path, columns=["tag", "desc", "keywords"]).to_pylist()
            for row in rows:
                tag = str(row.get("tag") or "")
                if tag in self._native:
                    self._translations[tag] = {
                        "desc": str(row.get("desc") or "").strip(),
                        "keywords": str(row.get("keywords") or "").strip(),
                    }
            self._metadata_available = True
        except Exception:
            self._warnings.append("한국어 설명 사전을 읽지 못했습니다. 저장된 위키 본문은 계속 볼 수 있습니다.")

    def _load_annotations(self) -> None:
        path = self._path("e621_research_annotations.json")
        if path is None:
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("schema") != ANNOTATION_SCHEMA:
                raise ValueError("Unsupported annotation schema")
            descriptions = payload.get("descriptions", [])
            links = payload.get("cross_site_links", [])
            search_terms = payload.get("korean_search", [])
            if not all(isinstance(items, list) for items in (descriptions, links, search_terms)):
                raise ValueError("Invalid annotation collections")
            for row in descriptions:
                if not isinstance(row, dict):
                    continue
                tag = str(row.get("e621_tag") or "")
                if tag not in self._native or row.get("review_status") != "reviewed_direct_definition":
                    continue
                # Older Korean descriptions are preserved. This supplement only
                # fills gaps; it does not silently overrule an existing decision.
                if (self._translations.get(tag) or {}).get("desc"):
                    continue
                body = str(self._native[tag].get("wiki_body") or "")
                if not body or body_sha256(body) != row.get("e621_body_sha256"):
                    self._stale.add(tag)
                    continue
                if str(row.get("description") or "").strip() and row.get("independent_review") is True:
                    self._annotations[tag] = row
            for row in search_terms:
                if not isinstance(row, dict):
                    continue
                tag = str(row.get("e621_tag") or "")
                if (tag not in self._native or row.get("review_status") != "reviewed_search_terms"
                        or row.get("independent_review") is not True):
                    continue
                body = str(self._native[tag].get("wiki_body") or "")
                if not body or body_sha256(body) != row.get("e621_body_sha256"):
                    self._stale_search.add(tag)
                    continue
                label = str(row.get("label") or "").strip()
                keywords = row.get("keywords", [])
                if not isinstance(keywords, list) or not all(isinstance(x, str) for x in keywords):
                    continue
                if re.search(r"[가-힣ㄱ-ㅎㅏ-ㅣ]", " ".join([label, *keywords])):
                    self._search_annotations[tag] = row
            for row in links:
                if not isinstance(row, dict):
                    continue
                tag = str(row.get("e621_tag") or "")
                if tag not in self._native or not row.get("danbooru_tag"):
                    continue
                entry = dict(row)
                expected_hash = row.get("e621_body_sha256")
                body = str(self._native[tag].get("wiki_body") or "")
                if row.get("status") == "reviewed_direct_evidence" and (
                    not expected_hash or row.get("independent_review") is not True
                    or {s.get("site") for s in row.get("sources", [])
                        if isinstance(s, dict) and s.get("body_sha256")} != {"e621", "danbooru"}
                ):
                    entry["status"] = "unverified_evidence"
                    entry["status_label"] = "검토 근거 확인 필요"
                    entry["semantic_approval"] = False
                elif expected_hash and body_sha256(body) != expected_hash:
                    entry["status"] = "stale_evidence"
                    entry["status_label"] = "근거 변경 · 재검토 필요"
                    entry["semantic_approval"] = False
                entry.update(site="danbooru", tag=row["danbooru_tag"],
                             automatic_rewrite_allowed=False, translation_transfer_allowed=False)
                self._links.setdefault(tag, []).append(entry)
            if self._stale:
                self._warnings.append(f"근거 본문이 달라진 한국어 설명 {len(self._stale)}개는 적용하지 않았습니다.")
            if self._stale_search:
                self._warnings.append(f"근거 본문이 달라진 한국어 검색어 {len(self._stale_search)}개는 적용하지 않았습니다.")
        except Exception:
            self._warnings.append("추가 검토 자료를 읽지 못했습니다. 기존 설명으로 표시합니다.")

    def for_tag(self, exact_tag: str) -> dict[str, Any]:
        native = self._native.get(exact_tag, {})
        legacy = self._translations.get(exact_tag, {})
        annotation = self._annotations.get(exact_tag, {})
        search = self._search_annotations.get(exact_tag, {})
        description = str(annotation.get("description") or legacy.get("desc") or "")
        if annotation:
            status, label = "reviewed_direct_definition", "직접 정의 검토 완료"
        elif exact_tag in self._stale:
            status, label = "stale_evidence", "근거 변경 · 재검토 필요"
        elif description:
            status, label = "legacy_unverified", "기존 설명 · 검토 기록 미연결"
        elif not self._metadata_available:
            status, label = "metadata_unavailable", "한국어 설명 사전 확인 불가"
        else:
            status, label = "no_korean_description", "한국어 설명 없음"
        source_label = "검토 보충 자료" if annotation else "e621 한국어 사전" if description else ""
        if annotation and annotation.get("native_body_matches_review_source") is False:
            source_label += " · 저장 본문과 다른 위키 판본 기준"
        return {
            "has_body": exact_tag in self._body_tags,
            "has_korean_description": bool(description),
            "has_korean_search": exact_tag in self._searchable,
            "korean_label": str(annotation.get("label") or native.get("kor") or search.get("label") or ""),
            "korean_description": description,
            "korean_keywords": ", ".join(str(value) for value in (
                annotation.get("keywords"), legacy.get("keywords"), search.get("label"),
                *search.get("keywords", []),
            ) if value),
            "search_review_status": "reviewed_search_terms" if search else "stale_evidence" if exact_tag in self._stale_search else "",
            "search_source_label": "저장 본문과 다른 위키 판본 기준" if search.get("native_body_matches_review_source") is False else "",
            "search_evidence": search.get("sources", []),
            "review_status": status,
            "review_label": label,
            "description_source": source_label,
            "description_evidence": annotation.get("sources", []),
            "cross_site_links": self._links.get(exact_tag, []),
        }

    def summary(self) -> dict[str, Any]:
        return dict(self._summary)
