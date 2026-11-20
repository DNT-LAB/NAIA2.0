"""Lazy catalog and thumbnail lookups for the preset bench."""
from __future__ import annotations

import base64
from collections import defaultdict
import hashlib
import json
import logging
from pathlib import Path
import threading

from core.outfit_tag_semantics import OutfitTagSemantics, POOLS
from core.preset_thumb_key import head_for, preset_thumb_key
from core.preset_thumbs import (
    KINDS, PRESET_THUMBS_INDEX_NAME, installed_signature, mark_corrupt, open_preset_thumbs, preset_thumbs_path,
)
from core.style_variants import is_webp


ROOT = Path(__file__).resolve().parents[1]
_LOG = logging.getLogger(__name__)
_FIELDS = ("id", "pool", "seed", "tags", "rank", "score", "layers", "support_by_rating", "side")
BROWSE_TAXONOMY_NAME = "preset_browse_taxonomy.json"
# 표에 아직 없는 시드(팩을 다시 구운 뒤 표를 안 고쳤을 때)가 숨지 않게 맨 끝에 모아 보인다.
UNSORTED_LABEL = "분류 전"


def _order(row):
    return min(row["rank"].values()), -max(row["score"].values()), row["id"]


class PresetBenchService:
    def __init__(self, runtime_paths, *, data_dir=ROOT / "data", thumbs_path=None):
        self.data_dir = Path(data_dir)
        self.thumbs_path = Path(thumbs_path) if thumbs_path is not None else preset_thumbs_path(runtime_paths)
        self.semantics = OutfitTagSemantics(self.data_dir / "outfit_presets.json",
                                            self.data_dir / "outfit_tag_index.json",
                                            pack_source=self._outfit_pack)
        self._load_lock = threading.Lock()
        self._by_id = None
        self.thumbs_lock = threading.RLock()
        self._signature = object()
        self._index = {}

    def _load(self):
        with self._load_lock:
            if self._by_id is not None:
                return
            states = json.loads((self.data_dir / "outfit_states.json").read_bytes())["by_set"]
            by_id = {}
            seeds = defaultdict(lambda: defaultdict(list))
            slots = {}
            slot_order = {}
            for pack_kind in ("outfit", "event", "expression", "scene"):
                raw = (self.data_dir / f"{pack_kind}_presets.json").read_bytes()
                pack = json.loads(raw)
                families = ("event", "link") if pack_kind == "event" else (pack_kind,)
                for family in families:
                    slot_order[family] = tuple(pack["slots"])
                if pack_kind == "outfit":
                    self._outfit_digest = hashlib.sha256(raw).hexdigest()
                    self._outfit_slots = pack["tag_slot"]
                for row in pack["sets"]:
                    kind = "outfit" if pack_kind == "outfit" else row["family"]
                    pool, seed = row["pool"], row["seed"]
                    summary = {field: row[field] for field in _FIELDS}
                    head = head_for(kind, pool)
                    summary.update(kind=kind, key=preset_thumb_key(kind, head, row["tags"]))
                    if kind == "outfit":
                        summary["states"] = states.get(row["id"], {})
                    by_id[row["id"]] = summary
                    seeds[kind, pool][seed].append(summary)
                    slots[kind, seed] = pack["tag_slot"].get(seed, "other")
            for seed_rows in seeds.values():
                for rows in seed_rows.values():
                    rows.sort(key=_order)
            # 탐색 분류(대분류 > 소분류 > 시드 · 게시물 수)는 빌더 칸과 별개인 손으로 고른 표다(11-20 v3).
            browse = json.loads((self.data_dir / BROWSE_TAXONOMY_NAME).read_bytes())
            if browse.get("schema") != "naia.preset_browse_taxonomy.v1":
                raise ValueError("Unknown preset browse taxonomy schema")
            self._browse = browse["families"]
            self._seeds = seeds
            self._slots = slots
            self._slot_order = slot_order
            self._by_id = by_id

    def _outfit_pack(self):
        self._load()
        rows = (row for row in self._by_id.values() if row["kind"] == "outfit")
        return {"sets": rows, "tag_slot": self._outfit_slots}, self._outfit_digest

    def _thumbs(self):
        with self.thumbs_lock:
            path = self.thumbs_path
            signature = installed_signature(path)
            if signature != self._signature:
                self._signature = signature
                self._index = {}
                if signature is None:
                    _LOG.info("Preset thumbnail pack unavailable")
                else:
                    try:
                        _, self._index = open_preset_thumbs(path, cache_path=path.parent / PRESET_THUMBS_INDEX_NAME)
                    except OSError:
                        self._signature = None  # Transient access failures retry on the next request.
                        _LOG.info("Preset thumbnail pack temporarily unavailable")
                    except (ValueError, KeyError, TypeError) as exc:
                        mark_corrupt(path, signature)
                        _LOG.warning("Invalid preset thumbnail pack: %s", ascii(str(exc)))
            return self._index, signature

    def _pool(self, kind, pool):
        if kind not in KINDS:
            raise ValueError("Unknown preset kind")
        self._load()
        if (kind, pool) not in self._seeds:
            raise ValueError("Unknown pool for preset kind")
        return self._seeds[kind, pool]

    def catalog(self, kind, pool):
        seeds = self._pool(kind, pool)
        index, _ = self._thumbs()
        if kind in self._browse:
            return self._browse_catalog(kind, pool, seeds, index)
        groups = defaultdict(list)
        for seed, rows in sorted(seeds.items(), key=lambda item: _order(item[1][0])):
            groups[self._slots[kind, seed]].append({
                "seed": seed, "sets": len(rows), "with_thumb": sum(row["key"] in index for row in rows),
            })
        ordered = dict.fromkeys((*self._slot_order[kind], *groups))
        return {"kind": kind, "pool": pool,
                "groups": [{"slot": slot, "seeds": groups[slot]} for slot in ordered if slot in groups]}

    def _browse_catalog(self, kind, pool, seeds, index):
        """대분류 > 소분류 > 시드(게시물 수 차례). 그 풀에 세트가 없는 시드 · 빈 소분류 · 빈 대분류는 뺀다."""
        def entry(seed, posts):
            rows = seeds[seed]
            return {"seed": seed, "sets": len(rows), "with_thumb": sum(row["key"] in index for row in rows),
                    "posts": posts}

        groups, placed = [], set()
        for category in self._browse[kind]:
            subs = []
            for sub in category["subcategories"]:
                items = [entry(tag, posts) for tag, posts in sub["tags"] if tag in seeds]
                placed.update(item["seed"] for item in items)
                if items:
                    subs.append({"name": sub["name"], "seeds": items})
            if subs:
                groups.append({"slot": category["category"], "label": category["category"], "subs": subs,
                               "seeds": [item for sub in subs for item in sub["seeds"]]})
        rest = sorted(set(seeds) - placed, key=lambda seed: _order(seeds[seed][0]))
        if rest:
            items = [entry(seed, 0) for seed in rest]
            groups.append({"slot": UNSORTED_LABEL, "label": UNSORTED_LABEL,
                           "subs": [{"name": UNSORTED_LABEL, "seeds": items}], "seeds": items})
        return {"kind": kind, "pool": pool, "groups": groups}

    def sets(self, kind, pool, seed):
        rows = self._pool(kind, pool).get(seed, ())
        index, _ = self._thumbs()
        return {"kind": kind, "pool": pool, "seed": seed,
                "sets": [dict(row, has_thumb=row["key"] in index) for row in rows]}

    def set_info(self, set_id):
        self._load()
        return self._by_id[set_id]

    def search(self, q, kind=None, translations=None):
        if kind is not None and kind not in KINDS:
            raise ValueError("Unknown preset kind")
        query = q.strip().casefold()
        if not query:
            return []
        self._load()
        matches = []
        translations = translations or {}
        for row in self._by_id.values():
            if kind is not None and kind != row["kind"]:
                continue
            for tag in (row["seed"], *row["tags"]):
                record = translations.get(tag.casefold().replace("\\(", "(").replace("\\)", ")"), {})
                if (query in tag.casefold()
                        or query in str(record.get("description") or record.get("desc") or "").casefold()
                        or query in str(record.get("keywords_kr") or "").casefold()):
                    matches.append({"kind": row["kind"], "pool": row["pool"], "seed": row["seed"],
                                    "set_id": row["id"], "matched": tag})
                    break
            if len(matches) == 200:
                break
        return matches

    def related(self, tag, pool, context):
        if pool not in POOLS:
            raise ValueError("Unknown outfit pool")
        result = self.semantics.related(tag, pool=pool, context=context)
        if result is None:
            raise KeyError(tag)
        index, _ = self._thumbs()
        for group in result["groups"]:
            group["sets"] = [dict(row, has_thumb=row["key"] in index) for row in group["sets"]]
        return result

    def thumbnail(self, key, if_none_match):
        with self.thumbs_lock:
            index, signature = self._thumbs()
            if key not in index:
                raise KeyError(key)
            etag = f'"{signature[0][:16]}-{key}"'
            if etag == if_none_match:
                return etag, None
            try:
                # Preserve the distinction between a temporary range read
                # failure and invalid bytes. __getitem__ folds both into KeyError.
                data = base64.b64decode(index._read(key), validate=True)
                if not is_webp(data):
                    raise ValueError("Invalid WebP")
            except (KeyError, OSError):
                self._signature = None
                raise KeyError(key) from None
            except ValueError as exc:
                self._index = {}
                mark_corrupt(self.thumbs_path, signature)
                _LOG.warning("Invalid preset thumbnail: %s", ascii(str(exc)))
                raise KeyError(key) from exc
            return etag, data
