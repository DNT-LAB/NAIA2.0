"""History 창의 최근 검색어 · 즐겨찾기(11-23 사용자 지정).

검색어 한 벌 = 포함 · 제외 태그(서버 문법 - `*tag` 는 정확히, 아니면 부분) + 본문 글자.
출처 · 폴더 칩 · 범위는 담지 않는다 - 불러오면 지금 화면의 거르개를 그대로 쓴다.
파일은 user-data 의 save 폴더에 하나 - 앱 창 · 외부 브라우저 · 휴대폰이 같은 목록을 본다.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

FILENAME = "output_search_saved.json"
VERSION = 1
MAX_RECENT = 30
MAX_FAVORITES = 200
MAX_TAGS = 40
MAX_TAG_CHARS = 120
MAX_TEXT_CHARS = 300
MAX_TITLE_CHARS = 60


def _clean_tags(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        raise ValueError("tags must be a list")
    seen, out = set(), []
    for value in raw:
        if not isinstance(value, str):
            raise ValueError("tags must be strings")
        tag = value.strip().lower()[:MAX_TAG_CHARS]
        if tag in ("", "*") or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    if len(out) > MAX_TAGS:
        raise ValueError("too many tags")
    return out


def clean_query(raw: Any) -> dict[str, Any]:
    """검색어 한 벌을 고르게. 잘못된 모양은 ValueError."""
    if not isinstance(raw, dict) or raw.keys() - {"include", "exclude", "text"}:
        raise ValueError("query must be {include, exclude, text}")
    text = raw.get("text", "")
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    return {"include": _clean_tags(raw.get("include", [])), "exclude": _clean_tags(raw.get("exclude", [])),
            "text": text.strip()[:MAX_TEXT_CHARS]}


def query_key(q: dict[str, Any]) -> str:
    """같은 검색인지 - 칩 순서는 상관없다."""
    return json.dumps([sorted(q["include"]), sorted(q["exclude"]), q["text"].casefold()], ensure_ascii=False)


def is_empty(q: dict[str, Any]) -> bool:
    return not (q["include"] or q["exclude"] or q["text"])


def _clean_title(raw: Any) -> str:
    if not isinstance(raw, str):
        raise ValueError("title must be a string")
    title = " ".join(raw.split())[:MAX_TITLE_CHARS]
    if not title:
        raise ValueError("title is empty")
    return title


class SavedSearches:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data: dict[str, list] | None = None

    # ── 파일 ──────────────────────────────────────────────────────────────
    def _load(self) -> dict[str, list]:
        if self._data is not None:
            return self._data
        recent, favorites = [], []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file() else {}
        except (OSError, ValueError) as exc:
            print(f"[warn] saved searches unreadable: {exc}", flush=True)
            raw = {}
        raw = raw if isinstance(raw, dict) else {}
        seen = set()
        for item in raw.get("recent") or []:
            try:
                q = clean_query(item.get("q"))
            except (AttributeError, ValueError):
                continue
            if is_empty(q) or query_key(q) in seen:
                continue
            seen.add(query_key(q))
            recent.append({"q": q, "at": float(item.get("at") or 0)})
        ids = set()
        for item in raw.get("favorites") or []:
            try:
                q, title, fid = clean_query(item.get("q")), _clean_title(item.get("title")), str(item.get("id") or "")
            except (AttributeError, ValueError):
                continue
            if not fid or fid in ids:
                continue
            ids.add(fid)
            favorites.append({"id": fid, "title": title, "q": q, "at": float(item.get("at") or 0)})
        self._data = {"recent": recent[:MAX_RECENT], "favorites": favorites[:MAX_FAVORITES]}
        return self._data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps({"version": VERSION, **self._data}, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
        temp.replace(self.path)

    def _snapshot(self) -> dict[str, Any]:
        data = self._load()
        return {"recent": [dict(r, q=dict(r["q"])) for r in data["recent"]],
                "favorites": [dict(f, q=dict(f["q"])) for f in data["favorites"]]}

    def _favorite(self, fid: Any) -> dict[str, Any]:
        for fav in self._load()["favorites"]:
            if fav["id"] == fid:
                return fav
        raise LookupError("favorite not found")

    # ── 바깥 ──────────────────────────────────────────────────────────────
    def state(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot()

    def apply(self, body: dict[str, Any]) -> dict[str, Any]:
        """action 하나를 적용하고 바뀐 전체를 돌려준다. 모양이 틀리면 ValueError, 없는 id 는 LookupError."""
        if not isinstance(body, dict):
            raise ValueError("expected an object")
        action = body.get("action")
        allowed = {"recent": {"q"}, "recent_remove": {"q"}, "recent_clear": set(), "add": {"title", "q"},
                   "rename": {"id", "title"}, "update": {"id", "q"}, "delete": {"id"}}
        if action not in allowed or body.keys() - {"action"} != allowed[action]:
            raise ValueError("unknown action or fields")
        with self._lock:
            data = self._load()
            now = time.time()
            if action in ("recent", "recent_remove"):
                q = clean_query(body["q"])
                key = query_key(q)
                data["recent"] = [r for r in data["recent"] if query_key(r["q"]) != key]
                if action == "recent" and not is_empty(q):
                    data["recent"] = [{"q": q, "at": now}, *data["recent"]][:MAX_RECENT]
            elif action == "recent_clear":
                data["recent"] = []
            elif action == "add":
                q = clean_query(body["q"])
                if is_empty(q):
                    raise ValueError("query is empty")
                if len(data["favorites"]) >= MAX_FAVORITES:
                    raise ValueError("too many favorites")
                fid = format(int(now * 1000), "x")
                used = {f["id"] for f in data["favorites"]}
                n = 0
                while fid in used:
                    n += 1
                    fid = f"{format(int(now * 1000), 'x')}{n:x}"
                data["favorites"].insert(0, {"id": fid, "title": _clean_title(body["title"]), "q": q, "at": now})
            elif action == "rename":
                self._favorite(body["id"])["title"] = _clean_title(body["title"])
            elif action == "update":
                q = clean_query(body["q"])
                if is_empty(q):
                    raise ValueError("query is empty")
                fav = self._favorite(body["id"])
                fav["q"], fav["at"] = q, now
            else:
                fav = self._favorite(body["id"])
                data["favorites"] = [f for f in data["favorites"] if f is not fav]
            self._save()
            return self._snapshot()


_LOCK = threading.Lock()


def saved_searches(context) -> SavedSearches:
    with _LOCK:
        store = getattr(context, "_output_saved_searches", None)
        if store is None:
            save_dir = getattr(getattr(context, "runtime_paths", None), "save_dir", None)
            if save_dir is None:
                raise RuntimeError("runtime_paths.save_dir is required for saved searches")
            store = SavedSearches(Path(save_dir) / FILENAME)
            context._output_saved_searches = store
        return store
