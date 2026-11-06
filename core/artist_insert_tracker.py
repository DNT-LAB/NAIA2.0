"""삽입 목록은 실행 동안만 기억한다. PE 원문은 화면이 고친다."""
from __future__ import annotations

import copy
import importlib.util
import math
import re
import threading


_INIT_LOCK = threading.RLock()
_COLLAB_PIECE = re.compile(r"(?:-?\d*\.?\d+::)?\s*artist collaboration\s*(?:::)?", re.IGNORECASE)


class ArtistInsertTracker:
    def __init__(self, scope_getter=None):
        self._lock = threading.RLock()
        self._scope_getter = scope_getter
        self._rev = 0
        self._next_id = 1
        self._preset = ""
        self._mode = ""
        self._items = []
        self._solo = None

    def _snapshot(self):
        return copy.deepcopy({"rev": self._rev, "preset": self._preset, "mode": self._mode,
                              "items": self._items, "solo": self._solo})

    def snapshot(self):
        with self._lock:
            if self._items and self._scope_getter is not None:
                self.check_scope(*self._scope_getter())
            return self._snapshot()

    def check_scope(self, preset, mode):
        with self._lock:
            if self._items and (preset != self._preset or mode != self._mode):
                self.clear()
            return self._snapshot()

    @staticmethod
    def _fields(fields):
        if fields.keys() - {"weight", "with_prefix", "slot", "on"}:
            raise ValueError("Only weight, with_prefix, slot and on can be updated")
        result = dict(fields)
        if "weight" in result:
            try:
                weight = float(result["weight"])
            except (TypeError, ValueError, OverflowError):
                raise ValueError("weight must be a finite number from 0 to 5") from None
            if not math.isfinite(weight) or not 0 <= weight <= 5:
                raise ValueError("weight must be a finite number from 0 to 5")
            result["weight"] = round(weight, 2)
        if "slot" in result and result["slot"] not in ("pre", "post"):
            raise ValueError("slot must be pre or post")
        for key in ("with_prefix", "on"):
            if key in result and not isinstance(result[key], bool):
                raise ValueError(f"{key} must be a boolean")
        return result

    def _item(self, item_id):
        for item in self._items:
            if item["id"] == item_id:
                return item
        raise ValueError("Unknown tracker id")

    def add(self, artist, weight, slot, with_prefix=True, *, preset, mode):
        if not isinstance(artist, str) or not artist.strip():
            raise ValueError("artist is required")
        name = " ".join(artist.split())
        fields = self._fields({"weight": weight, "slot": slot, "with_prefix": with_prefix, "on": True})
        with self._lock:
            self.check_scope(preset, mode)
            if not self._items:
                self._preset, self._mode = preset, mode
            for item in self._items:
                if item["artist"].casefold() == name.casefold() and item["slot"] == slot:
                    if any(item[key] != value for key, value in fields.items()):
                        item.update(fields)
                        self._rev += 1
                    return self._snapshot()
            self._items.append({"id": f"t{self._next_id}", "artist": name, **fields})
            self._next_id += 1
            self._rev += 1
            return self._snapshot()

    def update(self, id, **fields):
        fields = self._fields(fields)
        with self._lock:
            item = self._item(id)
            if any(item[key] != value for key, value in fields.items()):
                item.update(fields)
                self._rev += 1
            return self._snapshot()

    def remove(self, id):
        with self._lock:
            self._items.remove(self._item(id))
            if self._solo and self._solo["id"] == id:
                self._solo = None
            self._rev += 1
            return self._snapshot()

    def set_solo(self, id, scope="all"):
        if scope not in ("all", "group"):
            raise ValueError("scope must be all or group")
        with self._lock:
            if id is not None:
                self._item(id)
            solo = {"id": id, "scope": scope} if id is not None else None
            if solo != self._solo:
                self._solo = solo
                self._rev += 1
            return self._snapshot()

    def clear(self):
        with self._lock:
            if self._items or self._solo or self._preset or self._mode:
                self._items = []
                self._solo = None
                self._preset = self._mode = ""
                self._rev += 1
            return self._snapshot()


def current_scope(context):
    from core.prompt_engineering_settings import get_prompt_engineering_store

    store = get_prompt_engineering_store(context)
    return str(store.state(store.mode()).get("current_preset") or ""), context.get_api_mode()


def artist_insert_tracker(context):
    with _INIT_LOCK:
        tracker = getattr(context, "artist_insert_tracker", None)
        if tracker is None:
            tracker = ArtistInsertTracker(lambda: current_scope(context))
            context.artist_insert_tracker = tracker
        return tracker


def _known_artists(context):
    """라우트의 _mix_known_artists와 같은 사전·세션 캐시. 파일에는 쓰지 않는다."""
    cache = getattr(context, "_mix_known_artists_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        context._mix_known_artists_cache = cache
    if "" not in cache:
        service = getattr(context, "artist_thumbnail_service", None)
        if service is not None:
            weights = service._artist_weights("")
        else:
            from pathlib import Path

            path = Path(context.repo_root) / "artist_dictionary.py"
            weights = {}
            if path.is_file():
                spec = importlib.util.spec_from_file_location("naia_artist_dictionary", path)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    weights = getattr(module, "artist_dict", {})
        cache[""] = frozenset(" ".join(str(name).split()).casefold() for name in weights)
    return cache[""]


def replace_artist_pieces(text, artist, api_mode, token=""):
    """홀로 선 조각만 교체한다. 묶음 속 작가는 그대로 둔다."""
    name = str(artist)
    num = r"-?\d*\.?\d+"
    if str(api_mode).upper() == "NAI":
        name = r"(?:artist:)?" + re.escape(name)
        piece = rf"(?:{num}::{name}\s*::|{name})"
    else:
        name = re.escape(re.sub(r"([()])", r"\\\1", name))
        name = "@?" + name
        piece = rf"(?:\({name}:{num}\)|{name})"
    pattern = re.compile(rf"(^|[,\n])([ \t]*)({piece})(?=[ \t]*(?:,|\n|$))", re.IGNORECASE)
    found = False

    def replace(match):
        nonlocal found
        if text[:match.start(3)].count("::") % 2:
            return match.group(0)
        replacement = token if not found else ""
        found = True
        return match.group(1) + match.group(2) + replacement

    return pattern.sub(replace, text), found


def strip_other_artists_text(context, text):
    """글에서 작가 토큰을 모두 뺀다(삽입 솔로 '전체' 와 같은 걷기). `artist collaboration` 은 작가가 아니라 남긴다."""
    from core.artist_mix_preset import strip_artists

    stripped = strip_artists(str(text or ""), known=_known_artists(context), allow_bare=True)
    collab = [raw for raw in stripped["removed"] if _COLLAB_PIECE.fullmatch(raw.strip())]
    return ", ".join(part for part in [stripped["text"], *collab] if part)


def exclusive_options(context, options):
    """[다른 작가 숨김](결과 화면 작가 패널 · 사용자 지정 2026-11-06) - 생성 한 번의 사본에서 다른 작가를 걷는다.
    PE 프리픽스 · 포스트픽스의 작가 토큰을 빼고 랜덤 행의 작가(Remove Author 꺼짐일 때 붙는 것)를 끈다.
    저장한 PE 글은 그대로다. 와일드카드가 펼쳐 넣는 작가는 못 걷는다(펼치기 전 글만 본다)."""
    from core.wildcard_processor import split_tags_smart

    result = dict(options)
    for slot in ("pre", "post"):
        value = options.get(f"{slot}_prompt") or []
        text = ", ".join(value) if isinstance(value, list) else str(value)
        result[f"{slot}_prompt"] = split_tags_smart(strip_other_artists_text(context, text))
    preprocessing = dict(options.get("preprocessing_options") or {})
    preprocessing["remove_author"] = True
    result["preprocessing_options"] = preprocessing
    return result


def solo_options(context, options, snapshot):
    """생성 한 번의 사본만 고친다. 저장한 PE 글·목록은 그대로다."""
    from core.artist_mix_preset import strip_artists
    from core.artist_thumbnail_service import ArtistThumbnailService
    from core.wildcard_processor import split_tags_smart

    solo = snapshot["solo"]
    target = next(item for item in snapshot["items"] if item["id"] == solo["id"])
    mode = snapshot["mode"]
    result = dict(options)
    texts = {}
    for slot in ("pre", "post"):
        value = options.get(f"{slot}_prompt") or []
        texts[slot] = ", ".join(value) if isinstance(value, list) else str(value)
    if solo["scope"] == "all":
        known = _known_artists(context)
        for slot in texts:
            stripped = strip_artists(texts[slot], known=known, allow_bare=True)
            # `artist collaboration` 은 믹스에선 작가 묶음의 일부지만 작가가 아니다 - 솔로에도 남긴다(대개 음수로 섞임을 막는다).
            collab = [raw for raw in stripped["removed"] if _COLLAB_PIECE.fullmatch(raw.strip())]
            texts[slot] = ", ".join(part for part in [stripped["text"], *collab] if part)
    else:
        for item in snapshot["items"]:
            if item["id"] != target["id"]:
                slot = item["slot"]
                texts[slot], _ = replace_artist_pieces(texts[slot], item["artist"], mode)
    token = ArtistThumbnailService.format_artist_token(
        target["artist"], target["weight"], mode, with_prefix=target["with_prefix"])
    slot = target["slot"]
    texts[slot], found = replace_artist_pieces(texts[slot], target["artist"], mode, token)
    if not found:
        texts[slot] = f"{token}, {texts[slot]}" if slot == "pre" else f"{texts[slot]}, {token}"
    for slot, text in texts.items():
        result[f"{slot}_prompt"] = split_tags_smart(text)
    return result
