"""태그의 등급별 등장 수 표 — ``data/danbooru_tag_counts_by_rating.json``(태그 아카이브에서 구운 [g, s, q, e]).

툴팁의 등급별 횟수(prompt_tools_routes.tag_rating_counts)가 읽는다. 옛 Ollama 태그 어시스트
(core/ollama_tag_assist_service._load_rating_dist)에서 옮겼다 — Ollama 파이프라인 회수(2026-09-26).
프로세스에 한 번만 읽는다(키 = 소문자 · 공백 표기 태그).
"""

from __future__ import annotations

import json
from pathlib import Path

_RATING_DIST: dict[str, list[int]] | None = None


def load_rating_dist() -> dict[str, list[int]]:
    global _RATING_DIST
    if _RATING_DIST is not None:
        return _RATING_DIST
    try:
        path = Path(__file__).resolve().parents[1] / "data" / "danbooru_tag_counts_by_rating.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("_meta", None)
        _RATING_DIST = data
    except Exception:
        _RATING_DIST = {}
    return _RATING_DIST


__all__ = ["load_rating_dist"]
