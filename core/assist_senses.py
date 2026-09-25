"""Assist v2 — 동음이의어 뜻 검사: 결과 태그의 뜻을 이벤트 맵의 실제 공기로 확인한다 (2026-09-25).

'배를 깎아 접시에 담고 포크를 곁에 둔다' 가 belly 로 나왔다(모델 영문이 태그 그대로라 다른 검사를 거치지 않는다).
사전의 '배' 는 belly · watercraft · pear … 를 가리킨다. 문장의 다른 태그(plate · fork)와 **실제 게시물에 함께 달리는** 쪽이
그 문장의 뜻이다 — 이벤트 맵이 그 근거다(Codex 스키마 실험처럼 맵을 모델에게 읽히지 않고, 프로그램이 판정에 쓴다).

실측(오프라인, docs/assist_vocab_handoff/choose/eventmap_offline_20260925/summary.md):
  - 새로 동결한 동음이의어 23문장: 사전 첫 순위 13 -> 맵(나이브 베이즈) 20~21.
  - 앱 실측 결과 7세트(수백 건)에 이 규칙 그대로: 바꿈 4 = belly -> pear 2(정답) · seat -> chair 2, 기대를 깬 것 0.
    '진짜 동음이의어' 조건 없이는 12번 바꿔 기대를 6번 깼다(shirt -> unworn shirt · coat -> blue coat · smile -> laughing).

바꾸는 조건(전부): 요청 명사의 사전 뜻이 둘 이상 · 결과에 그 뜻 중 하나가 있다 · 그 뜻은 문맥 근거가 없다 · 다른 뜻이
나이브 베이즈 최고이고 문맥 근거가 있다 · 두 뜻이 낱말을 나누지 않고 드문 쪽 게시물의 5% 미만에만 함께 달린다
(같은 뜻의 갈래는 10~100%, 서로 다른 뜻은 0~1.5% — 실측).
"""
from __future__ import annotations

import math
from typing import Any, Callable, Iterable

M_EST = 20.0            # m-추정 평활 — 공기 0 은 '증거 없음'(기저 확률로), 흔한 뜻의 0 만 반대 증거가 된다
MIN_LIFT = math.log(2.0)
MIN_CO = 3
RELATED_SHARE = 0.05    # 드문 쪽 게시물 중 함께 달린 비율 — 이 이상이면 같은 뜻의 갈래
COMMON_SHARE = 0.05     # 게시물의 5% 넘게 달린 태그는 무엇과도 함께 나와 근거가 못 된다(문맥 · 뜻 둘 다 뺀다)
MAX_CONTEXT = 6         # 문맥은 드문 쪽부터 여섯 — 드문 태그가 뜻을 더 잘 가르고, 첫 요청의 목록 풀기도 짧다(최대 392ms 였다)


class Cooccur:
    """이벤트 맵 게시물 목록의 교집합 크기(짝마다 캐시). 목록 자체는 색인이 캐시한다(posting lru 512)."""

    def __init__(self, index: Any):
        self.index = index
        self.total = int(getattr(index, "total_posts", 0) or 0) or 1
        self._pairs: dict[tuple[int, int], int] = {}

    def tid(self, tag: str) -> int | None:
        return self.index.resolve(tag) if tag else None

    def n(self, tid: int) -> int:
        # 게시물 수는 색인의 표에서(목록 크기와 같다) — 흔한 태그의 목록을 풀면 shirt 113ms · 1girl 238ms 였다
        observed = getattr(self.index, "observed", None)
        if observed is not None and tid in observed:
            return int(observed[tid])
        return int(self.index.posting(tid).size)

    def co(self, a: int, b: int) -> int:
        import numpy as np

        key = (a, b) if a < b else (b, a)
        if key not in self._pairs:
            self._pairs[key] = int(np.intersect1d(self.index.posting(a), self.index.posting(b),
                                                  assume_unique=True).size)
        return self._pairs[key]

    def common(self, tid: int) -> bool:
        return self.n(tid) > COMMON_SHARE * self.total

    def log_lift(self, a: int, b: int) -> float:
        return math.log((self.co(a, b) + 0.5) * self.total / ((self.n(a) + 1) * (self.n(b) + 1)))


def naive_bayes(cooc: Cooccur, sense: int, ctx: list[int]) -> float:
    """ln P(s) + Σ ln P(c|s), P(c|s) = (공기 + m·P(c)) / (n(s) + m). 라플라스는 문맥과 한 번도 안 만난 드문 뜻을 띄웠다."""
    ns = cooc.n(sense)
    return math.log(ns + 1) + sum(
        math.log((cooc.co(sense, c) + M_EST * cooc.n(c) / cooc.total) / (ns + M_EST)) for c in ctx)


def supported(cooc: Cooccur, sense: int, ctx: list[int]) -> bool:
    """문맥 태그 하나 이상과 기댓값의 2배 이상 · 3건 이상 함께 달렸나."""
    return any(cooc.log_lift(sense, c) >= MIN_LIFT and cooc.co(sense, c) >= MIN_CO for c in ctx)


def _words(tag: str) -> set[str]:
    return {w for w in "".join(ch if ch.isalnum() else " " for ch in tag.lower()).split() if w}


def homonym_swaps(nouns: Iterable[str], tags: list[str], senses_of: Callable[[str], list[str]],
                  cooc: Cooccur) -> list[tuple[str, str, str]]:
    """[(명사, 바꿀 태그, 새 태그)] — 조건은 머리말. 결과 태그 목록(tags)은 바꾸지 않는다(부르는 쪽이 바꾼다)."""
    swaps: list[tuple[str, str, str]] = []
    have = list(dict.fromkeys(tags))
    for word in dict.fromkeys(nouns):
        senses = [s for s in senses_of(word) if cooc.tid(s) is not None]
        if len(senses) < 2:
            continue
        present = [s for s in senses if s in have]
        if not present or any(cooc.common(cooc.tid(s)) for s in present):
            continue
        ctx = [cooc.tid(t) for t in have if t not in senses and cooc.tid(t) is not None]
        ctx = sorted({c for c in ctx if not cooc.common(c)}, key=cooc.n)[:MAX_CONTEXT]
        if len(ctx) < 2:
            continue
        ids = {s: cooc.tid(s) for s in senses if not cooc.common(cooc.tid(s))}
        if not ids:
            continue
        best = max(ids, key=lambda s: (naive_bayes(cooc, ids[s], ctx), -senses.index(s)))
        if best in present or not supported(cooc, ids[best], ctx):
            continue
        if any(supported(cooc, cooc.tid(s), ctx) for s in present):
            continue
        related = False
        for s in present:
            a, b = cooc.tid(s), ids[best]
            if _words(s) & _words(best) or cooc.co(a, b) >= RELATED_SHARE * min(cooc.n(a), cooc.n(b)):
                related = True
        if related:
            continue
        for s in present:
            swaps.append((word, s, best))
    return swaps
