"""e621 택소노미 의미 확장기 — 하드코딩 시노님 맵을 데이터로 대체.

문제: danbooru substring 검색은 구(phrase)에서 토큰만 겹치는 잡음을 반환한다
("hands tied"→"tied sleeves", "having sex"→"shaving"). 작은 모델은 CoT가 없어
이를 못 거른다.

해결: e621는 wiki 본문에 `[[tag|text]]` 교차참조로 의미 그래프를 갖는다(20,987 태그).
"hands_tied"의 wiki_links = [arms_tied, bdsm, bound, bondage, rope, breast_bondage…].
개념을 이 그래프로 확장한 뒤, **출력 태그는 호출부가 danbooru 인덱스로 검증**한다
(e621=시소러스/확장기, danbooru=진실). 개별 태그 하드코딩 0.

설계 원칙: siblings(같은 부모)는 해부학 잡음(fingers/toes)이라 안 쓴다 — wiki_links만.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

_LINK_RE = re.compile(r"\[\[([^\]|]+)")
_LOCK = threading.Lock()
_INDEX: "E621SemanticIndex | None" = None


def _norm(name: str) -> str:
    """e621 태그명 정규화: 밑줄→공백, 소문자, (qualifier) 제거, 양끝 공백."""
    n = str(name).strip().lower().replace("_", " ")
    n = re.sub(r"\s*\([^)]*\)\s*$", "", n)  # "muzzle (object)" → "muzzle"
    return n.strip()


def _tokset(name: str) -> frozenset[str]:
    return frozenset(w for w in _norm(name).split() if len(w) >= 3)


class E621SemanticIndex:
    """e621_data를 한 번 로드해 name / tokenset / wiki-link 그래프 인덱스를 만든다."""

    def __init__(self, data_path: Path):
        self.ok = False
        self._name_to_count: dict[str, int] = {}
        self._tokset_to_names: dict[frozenset[str], list[str]] = {}
        self._wiki_links: dict[str, list[str]] = {}
        try:
            data = json.loads(Path(data_path).read_text(encoding="utf-8"))
        except Exception:
            return
        for path, entry in self._walk(data, []):
            raw = entry.get("tag")
            if not raw:
                continue
            name = _norm(raw)
            if not name:
                continue
            cnt = int(entry.get("count") or 0)
            # 같은 정규화명이 여러 번이면 최대 count 보존
            if cnt >= self._name_to_count.get(name, -1):
                self._name_to_count[name] = cnt
            ts = _tokset(raw)
            if ts:
                self._tokset_to_names.setdefault(ts, [])
                if name not in self._tokset_to_names[ts]:
                    self._tokset_to_names[ts].append(name)
            links = []
            for m in _LINK_RE.findall(str(entry.get("wiki_body") or "")):
                ln = m.strip()
                if ln.lower().startswith(("tag_group:", "tag:", "category:", "pool:")):
                    continue
                lnn = _norm(ln)
                if lnn and lnn != name and lnn not in links:
                    links.append(lnn)
            if links:
                self._wiki_links.setdefault(name, [])
                for ln in links:
                    if ln not in self._wiki_links[name]:
                        self._wiki_links[name].append(ln)
        self.ok = bool(self._name_to_count)

    @staticmethod
    def _walk(node: Any, path: list[str]):
        if isinstance(node, list):
            for e in node:
                if isinstance(e, dict):
                    yield tuple(path), e
        elif isinstance(node, dict):
            for k, v in node.items():
                yield from E621SemanticIndex._walk(v, path + [k])

    def _match(self, query: str) -> str | None:
        """개념 구 → 가장 적합한 e621 태그명(정규화). 정확명 > tokenset 동치 > 최대 부분."""
        q = _norm(query)
        if not q:
            return None
        if q in self._name_to_count:
            return q
        qt = _tokset(query)
        if not qt:
            return None
        if qt in self._tokset_to_names and self._tokset_to_names[qt]:
            # 동일 토큰셋 중 최고빈도
            return max(self._tokset_to_names[qt], key=lambda n: self._name_to_count.get(n, 0))
        # 부분(superset): 쿼리 토큰을 모두 포함하는 더 구체적 태그. 단 단일토큰 쿼리
        # ("girl")는 "monster girl" 류로 과확장되므로(Codex P0) 2토큰 이상에서만 허용.
        if len(qt) < 2:
            return None
        best, best_key = None, (-1, 0)
        for ts, names in self._tokset_to_names.items():
            if qt <= ts:  # 쿼리 토큰이 후보 토큰셋의 부분집합
                for n in names:
                    key = (self._name_to_count.get(n, 0), -len(n))
                    if key > best_key:
                        best, best_key = n, key
        return best

    def expand(self, query: str, limit: int = 12) -> list[tuple[str, int]]:
        """개념 구를 e621 wiki-link 의미 이웃으로 확장. [(태그명(공백), e621_count)] 빈도순.
        매칭 태그 자신 + 그 wiki_links. 호출부가 danbooru 인덱스로 검증해야 함."""
        if not self.ok:
            return []
        match = self._match(query)
        if match is None:
            return []
        out: dict[str, int] = {}
        # 매칭 태그 자신(실제 danbooru에도 흔히 존재: bound/bondage/rope 등)
        out[match] = self._name_to_count.get(match, 0)
        for ln in self._wiki_links.get(match, []):
            out.setdefault(ln, self._name_to_count.get(ln, 0))
        ranked = sorted(out.items(), key=lambda kv: kv[1], reverse=True)
        return ranked[:limit]


def get_index() -> E621SemanticIndex:
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    with _LOCK:
        if _INDEX is None:
            data_path = Path(__file__).resolve().parents[1] / "data" / "e621_data"
            _INDEX = E621SemanticIndex(data_path)
    return _INDEX


def expand_concept(query: str, limit: int = 12) -> list[tuple[str, int]]:
    """모듈 레벨 헬퍼 — 개념 구의 e621 의미 확장(빈도순 [(name, count)])."""
    return get_index().expand(query, limit=limit)


__all__ = ["E621SemanticIndex", "get_index", "expand_concept"]
