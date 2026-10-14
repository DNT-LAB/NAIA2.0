# -*- coding: utf-8 -*-
"""영구 제외 — Search 의 붉은 줄(`search_filter_state.exclude_permanent`)을 이벤트 맵에도 건다(사용자 지시 2026-10-14).

사용자가 보고 싶지 않은 조합(예: futanari · splatoon · guro · loli)을 **미리** 막는 사용자 필터다.
걸린 태그가 하나라도 달린 **게시물을 세지 않는다** - 그러면 그 조합 자체가 후보 · 실제 조합 · 랜덤에 나오지 않는다.
걸린 태그는 후보로도 내지 않는다.

문법은 Search 제외어와 같다(`core/search_engine._apply_filters`):
  * 쉼표 목록.
  * `*tag` = 태그 전체 일치.
  * 그 밖은 **단어 첫머리 일치** - `loli` 는 `lolita fashion` · `oppai loli` · `lolicon` 을 막는다.
    ⚠️ Search 는 순수 부분 일치라 `loli` 가 `hololive …` 를, `guro` 가 `ganguro` 를 같이 막는다(실측 2026-10-14,
    포터블 색인). 여기서는 단어 중간에서 시작하는 일치는 받지 않는다(앞 글자가 영숫자면 아니다).
  * `{a|b}` 는 항 각각.
태그 이름은 색인 규칙대로 소문자 · 밑줄 = 빈칸으로 맞춘다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PermanentBlock:
    text: str
    tags: np.ndarray      # bool[n_tags]  - 걸린 태그
    posts: np.ndarray     # bool[n_posts] - 걸린 태그가 달린 게시물
    names: tuple[str, ...]  # 걸린 태그 이름(게시물 수가 많은 순)

    @property
    def tag_count(self) -> int:
        return len(self.names)


def parse_terms(text: str) -> list[tuple[str, bool]]:
    """`(항, 전체 일치인가)` 목록. 빈 항은 버린다."""
    out: list[tuple[str, bool]] = []
    for raw in str(text or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        parts = raw[1:-1].split("|") if raw.startswith("{") and raw.endswith("}") else [raw]
        for part in parts:
            term = part.strip().lower().replace("_", " ")
            exact = term.startswith("*")
            term = term.lstrip("*").strip()
            if term:
                out.append((term, exact))
    return out


def build_block(idx, text: str) -> PermanentBlock | None:
    """색인에 맞춰 막을 태그 · 게시물을 만든다. 걸리는 것이 없으면 None."""
    terms = parse_terms(text)
    if not terms:
        return None
    tag_mask = np.zeros(int(idx.n_tags), dtype=bool)
    for term, exact in terms:
        if exact:
            tid = idx.resolve(term)
            if tid is not None:
                tag_mask[int(tid)] = True
    subs = [re.compile(r"(?:^|[^a-z0-9])" + re.escape(term)) for term, exact in terms if not exact]
    if subs:
        for tid, name in idx.by_id.items():
            low = str(name).lower()
            if any(p.search(low) for p in subs):
                tag_mask[int(tid)] = True
    hits = np.flatnonzero(tag_mask)
    if hits.size == 0:
        return None
    post_mask = np.zeros(int(idx.offsets.size) - 1, dtype=bool)
    for tid in hits:
        post_mask[idx.posting(int(tid))] = True
    order = sorted(hits.tolist(), key=lambda t: -int(idx.observed.get(t, 0) or 0))
    return PermanentBlock(text=str(text or ""), tags=tag_mask, posts=post_mask,
                          names=tuple(idx.by_id[t] for t in order))
