"""캐릭터 이름 찾기 — Fast Search(Ctrl+F) 의 캐릭터 갈래가 쓴다.

옛 Ollama Chat 도구(ollama_chat_tools.search_characters)에서 옮겨 왔다 — Ollama 파이프라인을 회수하면서(2026-09-26)
Chat 은 사라졌지만 이 검색은 Fast Search 가 계속 쓴다. 이름 색인(core.named_entity_aliases)에 먼저 묻고, 없으면
캐릭터 도감(분석 카탈로그)의 이름 · 한국어 키워드에서 찾는다.
"""

from __future__ import annotations

import re
from typing import Any


def search_characters(context: Any, query: str) -> dict:
    from app.backend.server.character_viewer_routes import character_viewer_service

    if not query.strip() or len(query) > 160:
        return {"status": "invalid_query", "characters": [], "tags": []}
    from core.named_entity_aliases import ensure_named_entity_index

    bound = ensure_named_entity_index(context).search(query, categories={'character'}, limit=6, prefix=True)
    if bound:
        rows = [{**row, 'work': row['group'], 'exact': row['match_kind'] != 'entity_name_prefix'} for row in bound]
        return {'status': 'ok', 'characters': rows, 'tags': rows,
                'ambiguous': rows[0]['entity_candidate_count'] > 1,
                'note': 'Name bindings are candidates. Preserve the full canonical name and work. '
                        'If ambiguous, ask for the work or full name; do not choose by popularity.'}
    svc = character_viewer_service(context)
    if not isinstance(getattr(context, "kr_tags_raw", None), dict):
        # 옛 Ollama 쪽은 LLM 색인을 만들며 채웠다 — 자동완성과 같은 로더로 raw 만 채운다(색인은 만들지 않는다).
        from app.backend.server.autocomplete_commands import _ensure_kr_raw

        _ensure_kr_raw(context)
    records = getattr(context, "kr_tags_raw", {}) or {}
    # The general tag index excludes characters; the catalog owns their names.
    needle = query.strip().replace("_", " ").casefold()
    matches = []
    for group, entries in svc.analysis().items():
        for name, data in entries.items():
            record = records.get(name.replace("_", " "), records.get(name, {}))
            # Bracketed entries are category words, not character-name aliases.
            aliases = [x.strip() for x in re.sub(r"<[^>]*>", "", str(record.get("keywords_kr", ""))).split(",") if x.strip()]
            names = [name.replace("_", " "), *aliases]
            if any(needle in n.casefold() for n in names):
                matches.append({"tag": name, "work": group,
                                "names": names, "exact": any(needle == n.casefold() for n in names),
                                "count": int(data.get("total_rows", 0) or 0)})
    matches.sort(key=lambda row: (not row["exact"], -row["count"], row["tag"]))
    rows, seen = [], set()
    for row in matches:
        key = row["tag"].replace("_", " ").casefold()
        if key not in seen:
            rows.append(row)
            seen.add(key)
        if len(rows) == 6:
            break
    return {"status": "ok" if rows else "no_match", "characters": rows, "tags": rows,
            "note": "Match the original full name and work. Never replace the requested character with a different popular match."}


__all__ = ["search_characters"]
