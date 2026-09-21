"""검색 기록 - 사용자가 실행한 검색(검색어·제외어)을 최근 순으로 최대 500개 기억한다.

사용자 지정(2026-09-21): [검색 기록 | 검색] 단추. 기록은 검색이 가능해야 하고, 찾는 대상은
**검색·제외 칸만**(복잡하게 만들지 말 것) - 찾기는 프론트가 목록 위에서 한다.

- 저장: user-data 의 `remote_web_search_history.json`(필터 프리셋과 같은 자리·같은 방식 = 기기 공유).
- 같은 (검색어, 제외어)는 한 줄 - 다시 검색하면 맨 위로 올라가고 시각·행 수·등급이 갱신된다.
- 검색어와 제외어가 둘 다 비면 남기지 않는다(전체 검색은 다시 칠 필요가 없다).
- 여러 기기(Remote Web 클라이언트)가 한 백엔드를 나눠 쓰므로 read-modify-write 를 락으로 묶는다.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

MAX_ITEMS = 500
FILE_NAME = "remote_web_search_history.json"
_LOCK = threading.Lock()


def history_path(context: Any) -> Path:
    return Path(context._save_path(FILE_NAME))


def _normalize(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    query = str(raw.get("query") or "").strip()
    exclude = str(raw.get("exclude") or "").strip()
    if not query and not exclude:
        return None
    ratings = [r for r in "gsqe" if r in (raw.get("ratings") or [])]
    item: dict[str, Any] = {
        "query": query,
        "exclude": exclude,
        "ratings": ratings,
        "at": str(raw.get("at") or ""),
    }
    if isinstance(raw.get("rows"), int):
        item["rows"] = int(raw["rows"])
    bucket = raw.get("bucket")
    if isinstance(bucket, list) and len(bucket) == 2 and all(isinstance(v, int) for v in bucket):
        item["bucket"] = [int(bucket[0]), int(bucket[1])]
    if raw.get("period"):
        item["period"] = str(raw["period"])
    return item


def load_history(context: Any) -> list[dict[str, Any]]:
    try:
        path = history_path(context)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [item for item in (_normalize(x) for x in data) if item][:MAX_ITEMS]
    except Exception:
        pass
    return []


def _write(context: Any, items: list[dict[str, Any]]) -> None:
    path = history_path(context)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def record_search(context: Any, *, query: str, exclude: str, ratings: Any = None,
                  rows: int | None = None, bucket: Any = None, period: str | None = None) -> list[dict[str, Any]]:
    """한 번의 검색을 맨 위에 남긴다. 반환 = 갱신된 목록(최신이 앞)."""
    entry = _normalize({
        "query": query, "exclude": exclude, "ratings": sorted(ratings or []),
        "rows": rows, "bucket": list(bucket) if bucket is not None else None, "period": period,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    if entry is None:
        return load_history(context)
    key = (entry["query"], entry["exclude"])
    with _LOCK:
        items = [x for x in load_history(context) if (x["query"], x["exclude"]) != key]
        items.insert(0, entry)
        del items[MAX_ITEMS:]
        _write(context, items)
        return items


def delete_search(context: Any, *, query: str, exclude: str) -> list[dict[str, Any]]:
    key = (str(query or "").strip(), str(exclude or "").strip())
    with _LOCK:
        items = [x for x in load_history(context) if (x["query"], x["exclude"]) != key]
        _write(context, items)
        return items
